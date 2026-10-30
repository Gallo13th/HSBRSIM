# 换位动作（reposition / `MOVE_MINION` / Move 196..244）全链路审计

> 审计日期：2026-10-30。结论先行：**换位在动作空间 / 引擎掩码 / `Game.step` / 训练采样 /
> 竞技场映射五层全部实现且可达**；「模型实战时不调整站位」是**策略层**现象，根因在
> entity 模型的 Move 指针头（`hsbg/az/train/entity_model.py:336-338`）——状态相关项
> `hb_i · hb_j` 对 `i↔j` **对称**，方向偏好只剩 `move_bias` 的反对称部分（实测 ≤1.8e-3，
> 而跨组合 logit 极差 12.06）。附带实测：只要换位被选中，模型会把**同一个换位**连按
> 25–40 次（per-turn 动作上限），即「要么不动，要么原地来回搓」。
>
> 复现：`scripts/probe_reposition.py` 的 6 个模式（engine/collect/eval/trace/head/arena，
> 命令见 §8）；回归测试：`tests/test_position_action_audit.py`（5 项）。

## 0. 结论表（每一层的证据）

| # | 层 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 动作空间 `hsbg/env/action_space_std.py` | ✅ 已定义 | `A_MOVE=196`（L138），`SEGMENTS` 的 `("move",196,245,49,...)`（L190-191），编码 `196+from*7+to`（L392-395），解码 L440-442；245 位里 **196..244 共 49 位**是换位 |
| 2 | 引擎 `hsbg_engine`（Rust） | ✅ 掩码置位 + step 接受 + 真改顺序 | `actions.rs:279-286` 按 `n*(n-1)` 置位；`actions.rs:117-123` 解码；`recruit.rs:2045-2054` `move_minion` 真做 `remove/insert`；实测 4 随从 → **12 位 True**，`step(197)` 接受，棋盘 `2631,3310,2752,9 → 3310,2631,2752,9`，`from==to` 抛 `ValueError: bad move` |
| 3 | 训练侧 `parallel_collect.py` / `ppo.py` | ✅ 无任何过滤 | 采样就是 `self._rng.choice(N_ACTIONS, p=mu64)`（`ppo.py:2072`），`mu` 只被 `legal_mask` 掩码；实测一个采集 batch（16 局 / 4184 决策）**换位被采样 760 次 = 18.16%**，其中 3488 个决策有合法换位 |
| 4 | 竞技场适配 `scripts/arena_agent.py` | ✅ 索引原样透传（无丢失） | `act()` 直接返回模型给的 0..244 索引（L121-168），`arena_client.py:188-192` 只校验「合法」后原样 POST；本地 245 动作名序列 sha256 与竞技场公开 manifest 的 `action_layout_sha256` **完全一致**（`be2e9758…e674bd`），196..244 = 49 个 `Move { from, to }` |
| 5 | 策略实际行为（greedy，64 局） | ⚠️ 差异极大：**旧模型 ≈ 0，新模型 18.8% 且是空转** | arena 部署的 `model_30m.pt`：**1 / 10470 = 0.0096%**（8709 次可换位）；`champion_c0_3004.pt`：1301/12564=10.4%；`az_entity_s8b/step_000701`：2929/15594=**18.8%**，但其中 646/681 是**同一动作连按**，每回合 25.2 次（上限 40） |

**问题出在哪一层**：不在 1/2/3/4，在 **5（策略/模型头）**。§6 给出根因与最小改动点
（模型侧，需重训；未擅自改，见 §7）。

## 1. 动作空间：245 位里 196..244 = 49 个换位

`hsbg/env/action_space_std.py`：

```text
138: A_MOVE = 196
190:     ("move", A_MOVE, A_MOVE + N_BOARD * N_BOARD, N_BOARD * N_BOARD,
191:      "棋盘重排 from 0..6 → to 0..6"),
392:     if isinstance(action, Move):
393:         src = _check_int(action.src, field="Move.src", lo=0, hi=N_BOARD - 1)
394:         to = _check_int(action.to, field="Move.to", lo=0, hi=N_BOARD - 1)
395:         return A_MOVE + src * N_BOARD + to
440:     if A_MOVE <= index < A_MOVE + N_BOARD * N_BOARD:
441:         src, to = divmod(index - A_MOVE, N_BOARD)
442:         return Move(src=src, to=to)
```

- 编码与 BC 数据一致：`196 + from*7 + to`（`scripts/firestone_bc_parse.py:75`、
  `data/firestone_bc/SCHEMA.md:52`、`docs/BC_DATA_FEASIBILITY.md:125`）。
- `tests/test_action_space_std.py` 已锁 `A_MOVE=196` 与全 274 位 round-trip；
  `docs/AT_LAYOUT_CONTRACT.md:37` 写的是 `196..245 Move(from 0..7, to 0..7)`。
- 实测（`--mode engine`）：
  `A_MOVE=196`、`move_segment=[196,244]`、`encode(Move(0,1))=197`、`encode(Move(6,0))=238`、
  `decode(196..244)` 49 位全对。

结论：**动作空间有换位段，49 位，位置正确**。

## 2. 引擎：会置位、会接受、会改顺序（Rust 侧无需改动）

`rust/crates/hsbg-engine/src/actions.rs`：

```text
 49: pub const A_MOVE: usize = A_MAGNETIZE + N_HAND * N_BOARD;      // 196
 50: pub const N_ACTIONS: usize = A_MOVE + N_BOARD * N_BOARD;       // 245
117:             _ if a < N_ACTIONS => {
118:                 let k = a - A_MOVE;
119:                 Action::Move { from: k / N_BOARD, to: k % N_BOARD }
279:         let n = pl.board.len().min(N_BOARD);
280:         for f in 0..n {
281:             for t in 0..n {
282:                 if f != t {
283:                     m[A_MOVE + f * N_BOARD + t] = true;
```

`rust/crates/hsbg-engine/src/recruit.rs:2045-2054`：

```rust
2045: pub fn move_minion(&mut self, p: PlayerId, from: usize, to: usize) -> ActResult {
2046:     self.check_turn(p)?;
2047:     let b = &mut self.players[p].board;
2048:     if from >= b.len() || to >= b.len() || from == to {
2049:         return Err("bad move");
2051:     let m = b.remove(from);
2052:     b.insert(to, m);
2053:     Ok(())
```

注意两点（都不是 bug，但影响训练动态）：

- `apply()` 会给 `actions_this_turn += 1`（`actions.rs:135`），即**换位要吃本回合动作预算**；
  `from==to` 被拒绝且不扣预算（L137-142）。
- `pending`（Discover/ChooseOne/Target）态下 `legal_mask` 只置位 Choose/Cancel
  （`actions.rs:220-226`），**换位段必然全 0** —— 探针必须先解 pending 再测（脚本里
  `_settle_seat()` 就是干这个的）。

实测（`--mode engine --seed 12345 --turn 6`，engine bot 打到第 6 回合后注入/使用真实棋盘）：

```json
{"turn": 6, "board_len": 4, "board_sig_before": ["2631","3310","2752","9"],
 "mask_legal_total": 29,
 "mask_move_legal": 12,                          // = 4 * 3 = n*(n-1)
 "mask_move_true_bits": [197,198,199,203,205,206,210,211,213,217,218,219],
 "mask_identity_move_legal": [false,...],         // 7 个 from==to 全 False
 "step_action": {"index": 197, "src": 0, "to": 1},
 "step_accepted": true,
 "board_sig_after": ["3310","2631","2752","9"],
 "board_order_changed": true,
 "identity_move_accepted": false, "identity_move_error": "ValueError: bad move"}
```

结论：**引擎能力齐全，掩码正确，`step` 接受且顺序真的变化**；`n*(n-1)` 位（不是 `n²`）与
「`from==to` 非法」一致。无需改 Rust。

## 3. 训练侧：没有任何地方过滤换位

链路只有两处处理 mask，且都只做「按引擎掩码裁剪」：

- `hsbg/az/train/common.py:145-147` `mask_from_bytes` = `u8[245] -> bool[245]`，逐位复制，
  不改任何段；`masked_normalize`（L150-162）只把非法位清零并归一。
- `hsbg/az/train/ppo.py:2043-2077` `PPOSelfPlayPolicy.decide`：
  `_observe`（L1990-1994）取 `game.legal_mask(seat)`；行为分布
  `mu = p_net | target_pi | mixed`（L2055-2064），最后
  `action = int(self._rng.choice(N_ACTIONS, p=mu64))`（**L2072**），越界/非法才回退
  （L2073-2074）。**没有按动作段的白名单/黑名单**。
- `hsbg/az/train/parallel_collect.py:599-604`：`mask = mask_from_bytes(g.legal_mask(seat))`，
  动作非法才 `illegal += 1` 并回退到 `flatnonzero(mask)[0]`；采集 meta 里
  `illegal_actions` 实测 0。
- PPO loss 的 `forced/valid`（`ppo.py:1421-1430`）只排除「回合动作数守卫」样本，
  与动作段无关；`bc_type` 的 9 类白名单（`docs/BC_AUX.md:476`）只影响**辅助类型 CE**，
  不影响行为采样。
- Rust 采集器 / lockstep 采集器里也没有 `A_MOVE` / `196` 的过滤分支
  （全仓 `grep -rn "A_MOVE" hsbg/ rust/` 只有常量、编码、头切片）。

实测（`--mode collect`，`step_000701`，16 局，`behavior=net`，T=1.0，cuda:7）：

```json
{"decisions": 4184, "move_selected": 760, "move_selected_share": 0.1816,
 "decisions_with_move_legal": 3488, "move_legal_bits_total": 125850,
 "forced": 29, "illegal": 0,
 "action_hist": {"end_turn":243,"refresh":494,"freeze":9,"upgrade":61,
   "hero_power":81,"dark_gift":48,"buy":515,"sell":317,"activate":10,
   "choose":581,"play":1030,"magnetize":35,"move":760}}
```

结论：**换位被采样 760 次（18.16%）> 0**，训练侧没有过滤。`tests/test_position_action_audit.py::
test_ppo_selfplay_samples_legal_move_without_filtering` 把行为分布全部压在某个换位上，
`decide()` 必须原样返回该索引（已通过）。

## 4. 竞技场适配：原样透传，布局逐字节一致（无丢弃点）

`scripts/arena_agent.py`：`act()`（L121-168）用 masked argmax 得到 0..244 的**同一个索引**
并直接 `return action`（L168），中间没有任何「动作段 → 竞技场 API 动作」的重编码；
唯一可能改写的地方是兜底 `action = int(action) if mask[action] else flatnonzero(mask)[0]`
（L144），只在模型给了非法位时触发（实测 `legal_action_rate = 1.0`，从不触发）。

`scripts/arena_client.py:188-192` 拿到返回值后**只校验**、不做映射：

```text
188: if isinstance(action,bool) or not isinstance(action,numbers.Integral) or not 0<=action<245
189:        or not observation['action_mask'][action]:
190:     raise ValueError('Policy must return a legal integer action')
191: payload={...}; payload.update(action=int(action), ...)
```

即：**不存在「静默丢弃成 end_turn / 跳过」的代码路径**——非法会直接抛 `ValueError` 结束对局。

更关键的是，竞技场布局与本地**逐字节一致**。2026-10-30 抓取
`https://rizling.top/api/v1/manifest`（无需密钥）：

```json
protocol_version: "2"
environment: {"package":"taverngym","version":"1.1.0","game_version":"36.6.3.253932"}
ruleset_id: "tg36-bc45cfc55a0e5cd6c14c"
observation.layout: {..., "N_BOARD":7, "A_MOVE":196, "N_ACTIONS":245, ...}
actions[196..244] = "Move { from: 0, to: 0 }" … "Move { from: 6, to: 6 }"   (49 个)
action_layout_sha256 = be2e97586b88025ead313ce26dc24fc5817c46cd3bf731662a92d34876e674bd
```

把本地 `hsbg_engine.action_name(0..244)` 序列按 manifest 同样的 canonical JSON 哈希：

```text
local sha256  = be2e97586b88025ead313ce26dc24fc5817c46cd3bf731662a92d34876e674bd
manifest sha  = be2e97586b88025ead313ce26dc24fc5817c46cd3bf731662a92d34876e674bd
name_diffs    = 0 / 245
arena actions[197] = "Move { from: 0, to: 1 }"   # 与我们 A_MOVE+1 完全一致
```

并且把真实 checkpoint 接到 `arena_agent.act()`、构造「只有 203 号动作（Move{1→0}）合法」
的观测，返回就是 `203`（`--mode arena` 实测 `unchanged: true`）。

结论：**arena 层没有映射丢失**。若线上真的出现「不换位」，只可能是
(a) 竞技场 `action_mask` 没给换位位（服务端问题，客户端可观测，见 §7 的 `ARENA_ACTION_LOG`），
或 (b) 模型自己没选（§5/§6 实测就是这一条）。

## 5. 策略行为：64 局实测（同一口径，全部 greedy）

口径 = `hsbg.az.train.evaluate.evaluate_policy`（seat0 = learner，其余 7 座引擎 bot，
seed 420000..420063，`PPOGreedyPolicy(max_actions_per_turn=40)`，masked argmax），
`--mode eval`：

| checkpoint | 决策数 | 换位被选 | 占比 | 有合法换位的决策 | 换位/可换位 | mean rank | top4 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `runs/az_entity_kl_30m/model_30m.pt`（**docs/ARENA.md 里上线用的 30M**） | 10470 | **1** | **0.0096%** | 8709 | 0.011% | 3.50 | 73.4% |
| `runs/az_entity_kl_30m/snapshots/step_001001/model.pt`（30M 跑满 1001 iter） | 10962 | 173 | 1.58% | 9133 | 1.9% | 3.58 | 67.2% |
| `runs/champion_c0_3004.pt`（stage-2 冠军，也在 arena 跑过） | 12564 | 1301 | 10.35% | 10430 | 12.5% | 3.23 | 78.1% |
| `runs/az_entity_s8b/snapshots/step_000701/model.pt`（当前训练最新快照） | 15594 | 2929 | 18.78% | 12967 | 22.6% | 1.91 | 95.3% |

- 全部 `legal_action_rate = 1.0`、`truncated_games = 0`、`illegal = 0`：换位动作 100% 被引擎接受。
- 「**从不换位**」的观感在 `model_30m.pt` 上成立（8709 次机会只选 1 次）。注意该
  checkpoint 的 meta 写 `trainer_updates=10`（同目录 `model.pt` 为 1001），即它是该 run 的
  **早期快照**，策略接近 BC 初始化；这也解释了它为什么几乎不换位。

### 5b. 一旦换位被选中：同一动作连按（`--mode trace`，16 局）

| checkpoint | 换位次数 | step 接受 | 顺序真的变了 | 同一动作连按 | 每回合换位均值/上限 | 每回合不同换位动作数 |
|---|---:|---:|---:|---:|---:|---:|
| `step_000701` | 681 | 681 | 675（6 次是换了同卡随从，肉眼不可见） | **646** | **25.2 / 40（动作上限）** | **1.30** |
| `model_30m.pt` | 0 | — | — | — | — | — |

即：s8b 的换位几乎都是「在某个回合末尾把同一对随从反复对调，直到 40 次动作上限把回合
顶掉」——27 个有换位的回合里 12 个回合结束时棋盘序列与开始时完全相同。

## 6. 根因：Move 指针头对「方向」不可辨识

`hsbg/az/train/entity_model.py`：

```text
192: self.move_bias = nn.Parameter(torch.zeros(N_BOARD, N_BOARD))
336: # move 196..244: board from × board to
337: mv = torch.einsum("bid,bjd->bij", hb, hb)
338: logits[:, 196:245] = self.pointer_scale * mv.reshape(B, N_BOARD * N_BOARD) + self.move_bias.reshape(1, -1)
```

`mv[i,j] = hb_i · hb_j` **对 i↔j 完全对称**，所以

```text
logit(Move{i→j}) - logit(Move{j→i}) = move_bias[i,j] - move_bias[j,i]      （状态无关！）
```

实测（`--mode head`，第 6 回合、注入 4 随从的同一局面）：

| checkpoint | 跨组合 logit 极差 | **方向差 max** | move_bias 反对称 max | 最佳换位 logit | 最佳非换位合法 logit | 差 |
|---|---:|---:|---:|---:|---:|---:|
| `step_000701` | 12.06 | **0.0018** | 0.001784 | -11.25 | +7.93 | **19.18** |
| `model_30m.pt` | 7.26 | **0.0012** | 0.001209 | -17.30 | +12.96 | **30.26** |

两件事：

1. **方向不可学**：状态相关项对称，模型无法从棋盘学「该把嘲讽放最左 / 该躲顺劈」；
   换位方向偏好只剩 `move_bias`（三个 checkpoint 的反对角几乎相同，offdiag ≈ -0.041），
   幅度比跨组合极差小 4 个数量级。
2. **量级整体偏低**：常规招募阶段（还有 buy/play/refresh 可选时）换位 logit 比最佳非换位
   低 19–30 nats → 模型**在有意义的决策点上永远不换位**；只有当别的动作都被掩掉
   （没钱、没手牌、只剩 EndTurn/Sell/Move）时，换位才可能赢过 EndTurn —— 于是出现 §5b
   的「同一 swap 连按到动作上限」。两个极端（0.0096% ↔ 18.8%）都来自同一个头。

这与人类 BC 的 3.8% reposition 也对得上：BC 阶段类型辅助头把 move 归到 `-1`
（`docs/BC_AUX.md:476`，不进 9 类 CE），逐动作 CE 又只占 `bc_coef` 权重，所以 BC 先验里
move 几乎没有抬升；PPO 阶段又没有可学的方向信号，于是 move 的概率质量由
「表示相似度 + 常数偏置」随机决定。

## 7. 实际改了什么 / 没改什么

### 已改（`scripts/arena_agent.py`，对局行为零变化）

1. **修潜在口径 bug：checkpoint 的 `norm_mean/norm_std` 之前被忽略**。
   之前 `_prepare` 直接喂原始 features；`hsbg/az/train/ppo.py:909-918`（`PPOEvaluator`）与
   `scripts/eval_az_checkpoint.py:76` 都会带 norm。现在 `_load()` 读 `meta["norm_mean"]`，
   `_prepare()`（L104-119）在存在时先减均值/除标准差。当前三个 checkpoint 都没有 norm 统计，
   所以**对现有线上结果零影响**，但以后带 norm 的 checkpoint 不会再静默降级。
2. **加可观测性（opt-in，默认关闭）**：`ARENA_ACTION_LOG=<path>` 时每个决策追一行 JSON
   （`action` / `segment` / `mask_legal` / `move_legal_bits` / 累计计数），进程退出时打印
   各动作段计数（`_counters` L47-58、`act` L145-168、`describe` L171-178）。
   下次线上跑即可直接回答「竞技场掩码到底有没有给换位位、模型选了几次」。
3. **未改** `entity_model.py`（§6 的根因）：它被正在跑的 `runs/az_entity_s8b` 训练 import，
   改架构会改变 checkpoint 兼容性；按任务约定「先报告」。
4. **未改 Rust**：引擎侧没有缺失。

> 边界说明：工作区里 `hsbg/az/train/{ppo,parallel_collect,process_pool}.py` 与
> `scripts/train_entity_sync.py` 在我审计前就有未提交改动（tier-target 奖励，见
> `docs/TIER_TARGET.md`），与换位无关；本次审计只读这 4 个文件，未改一行，也不影响正在跑的
> `runs/az_entity_s8b`（PID 2662390，审计期间持续运行）。

### §6 的最小改动点（建议，未应用）

把对称点积改成**有向**双投影（新参数只在新开关打开时创建，旧 checkpoint 完全不受影响）：

```python
# entity_model.py build_entity_net(...) 增加 directed_move: bool = False
if directed_move:
    self.move_from = nn.Linear(d, d)   # 源位置 query
    self.move_to = nn.Linear(d, d)     # 目标位置 key
...
if directed_move:
    # 非对称：(B,7,7)，logit(i->j) 与 logit(j->i) 不再相等
    mv = torch.einsum("bid,bjd->bij", self.move_from(hb), self.move_to(hb))
else:
    mv = torch.einsum("bid,bjd->bij", hb, hb)
logits[:, 196:245] = self.pointer_scale * mv.reshape(B, N_BOARD * N_BOARD) \
    + self.move_bias.reshape(1, -1)
```

补充建议（可选，与上面独立）：

- 给 move 段一个**显式先验**（例如按「人类 reposition 3.8%」初始化 `move_bias` 或加
  move 段 entropy 正则），避免「要么 0.01% 要么 18.8%」的两极；
- 评测/对局侧可加**去抖守卫**：同一回合内「与上一动作互为逆换位」或「同一 (from,to)
  重复」时把该位从合法集里摘掉（只影响部署/评测，需明确标注不是训练口径）。
  本仓库 `PPOGreedyPolicy` 的 40 动作守卫已经兜底，但会白烧动作预算（arena 上限 100）。

### 回归测试（`tests/test_position_action_audit.py`，5 项全绿）

```text
test_move_segment_is_frozen_in_action_space             # 196..244 段/编码/round-trip
test_move_names_match_engine_and_arena_layout_hash      # 245 名 = arena manifest sha256
test_engine_masks_accepts_and_applies_move              # n*(n-1) 位、step 改顺序、identity 拒绝
test_ppo_selfplay_samples_legal_move_without_filtering  # 采样链路不丢换位
test_arena_agent_returns_move_index_unchanged           # arena_agent 原样透传换位索引
```

运行：

```bash
PYTHONPATH=rust/python:. /home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python \
  -m pytest tests/test_position_action_audit.py -q
```

## 8. 复现命令

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python   # 训练环境（torch cu124）
export PYTHONPATH=rust/python:.

# 1) 引擎：掩码置位 / step 接受 / 顺序变化（无需 GPU）
$P scripts/probe_reposition.py --mode engine --seed 12345 --turn 6

# 2) 训练采集里换位被采样多少次
$P scripts/probe_reposition.py --mode collect \
  --checkpoint runs/az_entity_s8b/snapshots/step_000701/model.pt \
  --games 16 --workers 8 --device cuda:7 --seed 9001

# 3) 64 局 greedy 动作分布（换位选中次数/占比/名次）
$P scripts/probe_reposition.py --mode eval \
  --checkpoint runs/az_entity_s8b/snapshots/step_000701/model.pt \
  --games 64 --device cuda:7 --seed 420000 --out /tmp/reposition_eval.json

# 4) 换位是否真改顺序 / 是否同一 swap 连按（16 局）
$P scripts/probe_reposition.py --mode trace \
  --checkpoint runs/az_entity_s8b/snapshots/step_000701/model.pt \
  --games 16 --device cuda:7 --seed 420000 --out /tmp/reposition_trace.json

# 5) Move 头方向性诊断（§6 的数字）
$P scripts/probe_reposition.py --mode head \
  --checkpoint runs/az_entity_s8b/snapshots/step_000701/model.pt \
  --device cuda:7 --seed 12345 --turn 6

# 6) 竞技场布局哈希 + act() 透传
curl -sS https://rizling.top/api/v1/manifest -o /tmp/arena_manifest.json
$P scripts/probe_reposition.py --mode arena \
  --checkpoint runs/az_entity_s8b/snapshots/step_000701/model.pt \
  --device cuda:7 --manifest /tmp/arena_manifest.json
```

## 9. 线上核验（下次跑 arena 时）

没有 `ARENA_API_KEY` 时无法抓线上对局（本次未跑）。有 key 时用：

```bash
ARENA_ACTION_LOG=runs/arena/actions_$(date +%s).jsonl \
ARENA_MODEL=runs/az_entity_s8b/snapshots/step_000701/model.pt \
PYTHONPATH=rust/python:.:scripts $P scripts/arena_client.py \
  --url https://rizling.top --mode practice --policy arena_agent:act --games 10 \
  --catalog-sha256 c4c42e6ce5060e1b79fbcd5f4edbf6d17495f0f52690072481d690610f7ef6d7 \
  --expected-ruleset tg36-bc45cfc55a0e5cd6c14c
```

- `move_legal_bits == 0` 全程 → 竞技场服务端掩码没给换位位（服务端问题，联系我们/换 ruleset）；
- `move_legal_bits > 0` 但 `move_selected == 0` → 模型不选（§5/§6，策略问题）；
- `move_selected` 很多但同一动作连按 → §5b 的空转（模型头问题）。
