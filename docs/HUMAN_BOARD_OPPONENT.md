# 人类战团对手（board-only 注入）

> 状态：已实现（引擎 + PyO3 + 数据层 + 训练接线 + 测试）。
> 一句话：把 **10k+ MMR 真实观测里的战团（board）** 注入某个 bot 座位，只替换
> `board`（+ 派生 `tier`），不动 hand / shop / pool / 资源语义；每回合每座位**一次**引擎
> 调用，开销可忽略。**这是近似对手，不是忠实对手状态**（`source=human_board_approx`）。

---

## 1. 动机：t10 之后我们自己的快照库太弱

`data/real_library/strength_calibration.json`（真实 10k+ 观测 vs 我们的
`runs/library/snaps_champ`，同一把 `strength = Σ(atk+hp)` 定义）显示：**t8 之前我们的库不弱，
t10 之后迅速崩**——`p50` 比值从 t1–t6 的 0.38–0.91× 一路涨到 t10 的 2.79×、t15 的 25.37×：

| turn | 真实 n | 真实 p50 | 真实 p90 | 我们 p50 | p50 比值（真实/我们） |
|---|---|---|---|---|---|
| 1 | 362 | 3 | 7 | 8 | 0.38× |
| 2 | 364 | 5 | 11 | 12.5 | 0.40× |
| 3 | 362 | 15 | 27 | 18.5 | 0.81× |
| 4 | 356 | 26 | 46 | 34 | 0.76× |
| 5 | 364 | 48 | 73 | 53 | 0.91× |
| 6 | 364 | 77 | 129 | 85 | 0.91× |
| 7 | 362 | 131 | 238 | 124.5 | 1.05× |
| 8 | 362 | 266 | 465 | 195 | 1.36× |
| 9 | 364 | 546.5 | 1268 | 305 | 1.79× |
| **10** | 344 | 1128.5 | 2948 | 405 | **2.79×** |
| 11 | 310 | 2203 | 6644 | 540 | 4.08× |
| 12 | 230 | 4458 | 13288 | 669 | 6.66× |
| 13 | 160 | 9666.5 | 31366.4 | 751 | 12.87× |
| 14 | 84 | 21136 | 74435 | 993 | 21.28× |
| **15** | 40 | 26516 | 170585 | 1045 | **25.37×** |

结论：**s6 的难点不在「生成更强战团」，而在「后期没有可信的高强度对手」**。镜像快照
（`docs/MIRROR_SNAPSHOT_DESIGN.md`）依赖我们自己的采集库，t10 之后样本本身偏弱，于是
`mirror` 在后期只是「把偏弱的战团换了个座位」。人类战团库（4,284 条 10k+ MMR 帧，
t1–t17 全覆盖）正好补这个缺口：**它给的是「该回合真实人类会有什么战团」的强度分布**。

## 2. 数据与近似边界（必须如实标注）

数据源：`data/real_library/library_real_degraded.jsonl`（4,284 行；每行一个座位在
**recruit 阶段末 / combat 之前**的观测）。

行内可用字段：`turn`、`strength`、`board:[{card, atk, hp, position}]`、`hero`、`game_id`、
`quality=degraded`（`degraded_reasons` 含 `library_ready_false`、`hidden_counters_incomplete`）。
**没有** tier、gold、hand、shop、共享池差量、hidden counters。

因此本功能只做 **board-only 近似**，并在所有 meta 里写 `human_board_source=human_board_approx`：

| 项 | 处理 | 是否忠实 |
|---|---|---|
| board 随从（卡 / atk / hp / 顺序） | 注入并替换旧 board | ✅ 来自真实观测 |
| `tier` | 人类数据没有 → 按回合近似（`turn_tier`，上限 6） | ⚠️ 近似 |
| hand / shop / gold / 资源 / 技能计数 | **完全不动**（保留该 bot 当前局的值） | ❌ 不还原 |
| 共享池占用 | 新随从 `pool_copies=0`（不占池）；旧 board 持有量归还 | ⚠️ 池语义中立（`pool_delta_unknown`） |
| 隐藏计数（this-game 加成、avenge、任务进度…） | 不还原 | ❌ 不还原 |
| EID / typed 引用 | 全部重新分配并清悬空引用 | — |

**不要在报告/论文里把它写成「真实对手状态」**：它只是「该回合、该强度分位的战团模板」。
真实观测缺失的池/手牌/hidden 状态我们**没有**推断，也**没有**伪造。

另外一个时间上的近似：人类帧是**回合末**战团，注入发生在**回合开始**。即 t 回合的人类
EOT 战团被挪到 t 回合起点，所以对手比「t 回合初应有的样子」偏强一点——这正是我们想要的
方向（追赶后期强度），但要在论文里写明。

## 3. 引擎接口：`Game::inject_board`

```rust
pub fn inject_board(
    &mut self,
    seat: usize,
    minions: &[(CardId, i32, i32)],   // 按位置排列，≤ cfg.board_size
    tier: Option<u8>,                 // None = 保留当前局 tier
) -> BoardInjectReport;               // { applied, reason, board_len, tier,
                                      //   pool_held, pool_initial, pool_balance_ok,
                                      //   returned_parts }
```

Python / PyO3：`game.inject_board(seat, [[card, atk, hp], ...], tier=None) -> dict`。

语义要点（实现：`rust/crates/hsbg-engine/src/snapshot.rs`）：

- **只改** `board`（+ 可选 `tier`）与派生 `last_board`；`hand / hand_queue / shop /
  gold / max_gold_bonus / upgrade_cost / free_refreshes / health / armor / alive /
  placement / hero / powers / stats / pending / scheduled / effects / quests / rewards /
  trinkets / secrets / counters / owed / scouted / seen_board / 配对簿记` 全部保留当前局原值；
- **不设置 `ended_turn`**：被注入的座位本回合照常行动（bot 在人类战团之上继续买/打）。
  这与镜像快照相反——镜像整场面=回合末，必须 `ended_turn=true`；
- 新随从一律 `alloc_eid()` 重新分配（旧 EID 不复用），`pool_copies=0`、`pool_parts` 清空、
  `killed_by=0`、`max_hp = hp`（recruit 阶段满血）、`peak_atk/peak_hp` 同步；
- 旧 board 的持有量按 `Minion::visit_pool_parts` 归还共享池 → 注入前后
  `invariants::pool_balance` 的总量与逐物种守恒都成立（`pool_balance_ok` 恒真，
  调用方仍应对 False 报警）；
- 指向被移除旧实体的 typed 引用就地清空（不是 fail-closed，因为移除 board 本身是语义）：
  手牌 `link / group / src`、`hand_queue_marks` 的 `hid / link / src`、`hats`、
  `revert_golden`、`discover_targets`；
- **逐座位事务**：先完整校验（不分配 EID、不动 pool、不改玩家），再一次性提交。非法输入
  只返回 `applied=false` + `reason`，**`state_json` 与 `next_eid` 都不变**。拒绝原因：
  `not_recruit` / `seat_out_of_range(N)` / `not_alive` / `already_ended` / `dying(health=)`
  / `pending_choice(N)` / `too_many_minions(N>7)` / `bad_tier(N)` / `unknown_card(i:cid)`
  / `not_minion(i:card)` / `bad_stats(i:atk/hp)` / `pool_overflow(...)`；
- PyO3 侧**不抛异常**：连形状错误（`bad_minion#0(2 items, expected 3)`、
  `bad_minion#1.atk(...)`）也走 `applied=false`，采集循环不需要 try/except 分支。

## 4. 数据层：`hsbg/az/train/human_board_pool.py`

- `HumanBoardPool(path, sample="auto")`：读 JSONL → 按 `turn` 分桶；桶内按
  `strength = Σ(atk+hp)` 升序做**最近秩分位**（`p50/p75/p90/max`，与
  `MirrorSnapshotPool.get` 同一算法；同强度多条用 `rng` 随机抽）；
- `sample(turn, rng=None, mode=None) -> [[card, atk, hp], ...]`：`mode=None` 用池的
  `sample_mode`，`"auto"` 走难度曲线（见 §7）；桶内按 `position` 排序后输出；
  该回合没有数据时退化到**最近回合**并计 `nearest_fallbacks`；
- `stats()`：行数 / 保留数 / 过滤计数 / 每回合 `n,p50,p75,p90,max` / 难度曲线；
- 过滤阈值（宁可少用，不把脏帧带进对局，全部计数）：
  `empty_board`（空战团）、`board_over_7`、`bad_entry`（缺字段/非整数）、`bad_stats`
  （`atk<0` 或 `hp<=0` 或 `card<=0`）、`stat_outlier`（单随从 `atk+hp > 100_000`）、
  `strength_outlier`（战团 `Σ > 250_000`）、`not_minion`（卡表种类）、`bad_turn`；
  另有 `strength_mismatch`：行内 `strength` 与 `Σ(atk+hp)` 不一致时**只打点、以实际战团为准**
  （实测真实库里 0 条不一致）。
- 真实库实测（`stats()`）：`rows=4284`、`kept=4275`、过滤 `empty_board=4`、
  `stat_outlier=4`、`strength_outlier=1`、`bad_lines=0`，`turn 1..17` 连续。

`turn_tier(turn)`（人类数据没有 tier）：t1→1、t2→2、t3–4→3、t5–6→4、t7–8→5、t9–10→6、
t11+→6（**上限 6**：tier 7 需要 Norgannon 奖励的 `Player::tier7`，不在这里凭空解锁）。

## 5. 训练侧接线

`collect_ppo_lockstep(..., human_board_pool=None, human_board_p=0.0,
human_board_seats=2, human_board_sample="auto", human_board_set_tier=True)`：

- 注入窗口：每个**新回合**开始、任何座位行动前（与镜像快照同一个窗口，`_maybe_inject`
  = 先镜像、后人类战团）；
- 每回合从**全部非 learner 座位**里随机抽 `human_board_seats` 个，逐座位独立掷
  `human_board_p`；命中后 `attempt+=1` → `pool.sample(turn)` → `game.inject_board(seat, board,
  turn_tier(turn))`（**每座位一次引擎调用**）；
- 引擎拒绝只记 `rejected`（该座位保持原状态，本回合照常被 bot 驱动）；
- meta（每次采集都写）：
  `human_board_source=human_board_approx`、`human_board_attempt / applied / rejected /
  missing / skipped_by_mirror / errors / pool_unbalanced / nearest_bucket / tier_set /
  last_rejected / rejected_by_reason`，以及开关与参数
  `human_board_on / p / seats / sample / set_tier / boards`。

CLI（`scripts/train_entity_sync.py`，默认全关 = 零影响）：

```bash
# 建议的 s6 起手式（与镜像快照同时开也行）
PYTHONPATH=rust/python:. python scripts/train_entity_sync.py \
  --lockstep 1 --games 32 \
  --human-boards data/real_library/library_real_degraded.jsonl \
  --human-board-p 0.15 --human-board-seats 2 --human-board-sample auto \
  --out runs/az_s6
```

校验：`--human-board-p>0` 需要 `--human-board-seats>0` 且 `--lockstep 1`（否则 warn 后忽略，
与 `--mirror-p` 一致）；`--human-boards` 为空时默认取真实库路径。只在 lockstep 路径生效
（`process_pool` 里按文件 mtime 缓存池，热更新友好）。

## 6. 与镜像快照的组合策略

两者**可以同时开**，但**同座位同回合只允许一个**：

1. `_maybe_mirror` 先跑，把本回合**实际成功**的镜像座位写进 `mirror_applied_seats`
   （`mirror_snapshots.inject_turn(..., applied_out=...)`）；
2. `_maybe_human_board` 后跑，命中这些座位时**直接跳过**并记 `human_board_skipped_by_mirror`；
3. 兜底：镜像注入会把座位置 `ended_turn=true`，而 `inject_board` 对 `already_ended` 一律
   拒绝 → 即使调用顺序写错也不会在同一座位/回合上叠两次。

分工建议：**镜像快照负责「整场面忠实」（t≤10 我们的库还够用的阶段），人类战团负责
「后期强度补位」（t≥10）**。注意两者语义不同：镜像座位本回合不再行动（整场面=回合末），
人类战团座位本回合照常行动（board-only 起点）。

## 7. 难度曲线建议（分位 × turn × p）

人类库分位（`HumanBoardPool.stats()`，过滤后）：

| turn | n | p50 | p75 | p90 | max |
|---|---|---|---|---|---|
| 5 | 386 | 48 | 60 | 73 | 144 |
| 8 | 403 | 261 | 368 | 504 | 1306 |
| 10 | 414 | 1145 | 1888 | 3030 | 31822 |
| 12 | 273 | 4858 | 9399 | 18542 | 98122 |
| 13 | 190 | 10140 | 18690 | 31142 | 117023 |
| 14 | 96 | 23243 | 43195 | 74441 | 190337 |
| 15 | 40 | 26838 | 56507 | 68061 | 160069 |

**建议调度（`--human-board-sample auto` 的默认就是它）**：

| turn | 分位 | 理由 |
|---|---|---|
| ≤8 | p50 | 我们的库 t≤8 不弱（0.38–1.36×），先学「正常对局」，别一上来就被碾压 |
| 9–12 | p75 | 我们开始落后（1.79–6.66×），用上四分位把难度推到真实中上 |
| ≥13 | p90 | 我们落后 12.9–25.4×，必须用高尾补位（p99/max 含离群值，不建议） |

`human_board_p` / `human_board_seats` 的 s6 建议（按训练阶段，不是按 turn）：

| 阶段 | p | seats | 分位 | 说明 |
|---|---|---|---|---|
| 冷启动 / 恢复训练 | 0.10 | 2 | auto | 每回合约 0.2 个座位被注入，足够给梯度信号 |
| 稳态 s6 | **0.15** | **2–3** | auto | 本任务默认；实测 wall +3.2%（<5%） |
| 后期加压（可选） | 0.25 | 3 | auto | 每回合约 0.75 个座位；仍远低于极端值 |
| 极端（不建议常用） | 1.0 | 7 | auto | 7 座全人类 + t13+ p90 = 直接碾压，wall +19% |

若与镜像快照同开，建议 `mirror_p 0.3 / mirror_seats 3` + `human_board_p 0.15 /
human_board_seats 3`：镜像占一部分座位（本回合不行动，整场面忠实），人类战团补剩下的
（本回合照常行动，后期强度补位）。同座位冲突会自动让路并计入 `skipped_by_mirror`。

## 8. 开销实测

复现脚本：`scripts/bench_human_board.py`（CPU tiny，不需要 GPU）。

```bash
PYTHONPATH=rust/python:. python scripts/bench_human_board.py --reps 21 --games 4
```

环境：CPU、`arch=tiny`（`hidden=128`）、lockstep bot 对手、`sims=0`、4 局、同 seed，
每个 arm 交替 21 次取中位数（机器同时有其它训练/竞技场任务，取中位更稳）：

| arm | collect_s（中位） | 相对 off | 注入自身耗时 | 占 collect_s | 去掉注入后的 wall |
|---|---|---|---|---|---|
| off（默认） | 116.6 ms | — | 0 | — | — |
| **p=0.15, seats=2（默认）** | **120.3 ms** | **+3.11%** | 1.41 ms / 4 局 | 1.17% | +1.91% |
| p=1.0, seats=7（极端上界） | 138.2 ms | +18.49% | 6.88 ms / 4 局 | 4.98% | +12.59% |

- 微基准（稳定态）：`Game.inject_board` **2.95 µs/次**；`pool.sample` 分位采样
  2.84 µs/次（桶内排序缓存 + `bisect` 取同强度区间）；`inject_turn` 全路径
  **6.2 µs/回合**（p=0.15 / 2 座）、22.9 µs（p=1.0 / 2 座）；
- 折算：默认配置每局约 15 回合 × 2 座位 → ~30 次引擎调用 ≈ **0.2 ms/局**，相对单局
  collect（~30 ms）约 **0.4–1.2%**，满足「每回合每座位一次引擎调用 + <2% wall」的设计目标；
- `p=0.15` 的 **+3.1%** 里有一半不是注入本身，而是**对手变强 → 战斗更久/更多死亡结算**
  的合法开销（去掉注入自身耗时后为 +1.9%），故仍 **<5% 验收线**；`p=1.0/seats=7` 只是上界
  （它是「7 座全人类 + auto 分位」的极端：既慢在注入 469 次，也慢在超大战斗）。

## 9. 测试与验收

```bash
# 引擎（含新增 tests/board_inject.rs）
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine
# Python（池 / 采样 / 过滤 / 驱动 / 接线）
PYTHONPATH=rust/python:. python -m pytest tests/test_human_board_pool.py -q
PYTHONPATH=rust/python:. python -m pytest tests -q
# 开销实测（§8）
PYTHONPATH=rust/python:. python scripts/bench_human_board.py --reps 21 --games 4
```

实测结果（本机）：`cargo test --release -p hsbg-engine` **41 个测试套件全绿（0 failed）**；
`pytest tests -q` **281 passed / 0 failed / 8 skipped**（含本文件相关的 15 项）。

Rust（`rust/crates/hsbg-engine/tests/board_inject.rs`）：

- `injects_board_and_tier_keeps_other_fields`：board/tier 被替换，hand/shop/gold/health/
  alive/placement/hero 保持，`ended_turn` 不变，`last_board` 同步，EID 全新且全局唯一；
- `pool_conserved_with_mixed_triple_and_zero_copies`：异种三连按 `pool_parts` 归还、
  注入实体 `pool_copies=0`、总量与逐物种守恒；
- `dangling_references_to_removed_minions_are_cleared`：手牌 `link/src`、`hats`、
  `revert_golden`、`discover_targets` 指向被移除旧实体时清空；
- `rejections_leave_state_untouched`：阶段/座位/存活/待淘汰/pending/数量/tier/未知卡/
  非 minion/非法数值 → `state_json` 与 `next_eid` 都不变；
- `injection_keeps_games_playable_and_terminal`：2 局每回合 7 座注入（≥100 次）→ 池守恒、
  `invariants::check` 为空、正常终局。

Python（`tests/test_human_board_pool.py`，15 项）：分桶/分位/同强度随机/`auto` 曲线/
`position` 排序/过滤计数/真实库全回合覆盖/`load_pool`/`turn_tier`；引擎驱动 CPU 冒烟
（2 局、p=1.0、0 errors、池平衡、终局、只出现预期拒绝原因）；注入后座位仍可行动、
board 与采样一致、`set_tier` 生效；镜像优先（`skipped_by_mirror`）；`p=0` 时同 seed
终局 `state_json` 字节一致；接线断言（signature / `CollectConfig` / CLI / meta 键）。

手工 CPU 冒烟（`p=1.0, seats=3, 6 局`）：`applied=152`（>100）、`errors=0`、
`pool_unbalanced=0`、`missing=0`、6/6 局正常终局（学习者名次 5–8，说明对手确实更强），
拒绝原因只有 `not_alive=45`、`pending_choice=40`。

镜像 + 人类战团同开（`mirror_p=0.7/seats=3`、`human_board_p=1.0/seats=5`，4 局）：
`mirror_applied=66`、`human_board_applied=135`、**`human_board_skipped_by_mirror=47`**、
`errors=0`、`illegal_actions=0`、池守恒。

## 10. 已知限制 / 后续

1. **没有 pool 差量**：注入实体不占共享池，旧 board 归还。若将来拿到「池差量已知」的
   人类库，应改为扣减对应物种（`pool_delta_known`），与镜像快照的同一 TODO 合并做；
2. **没有 hand/shop/gold/hidden**：bot 会在人类战团之上用自己的手牌/商店继续打，后期
   board 可能比真实更强（复合效应），这也是为什么建议 `p` 不要超过 0.25；
3. **tier 是近似的**（turn 表 + 上限 6），不是观测值；
4. **t16+ 样本很少**（t16=16、t17=3 条），t18 之后退化到 t17 桶，后期难度曲线会「封顶」；
5. 人类帧是「回合末」、注入在「回合初」，对手会略偏强（有意为之）；
6. 没有任何「合法性重放」校验：我们**不**重放人类动作，也不声称该战团在引擎里可达
   （卡表同版本但组合/加成历史不同），只保证引擎状态自洽（池守恒、EID 唯一、引用不悬空）。

## 11. 保真度扩展（2026-10-31）

上面 §2 的「board-only 近似」仍是**默认行为**（`--human-board-fidelity board`，逐位不变）。
若需要把**手牌 / 可推断 counters（关键词位、金身、圣盾层数、tavern tier）**一起注入：

```bash
PYTHONPATH=rust/python:. python scripts/build_fidelity_library.py --stats   # 一次性
python scripts/train_entity_sync.py ... \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-fidelity full     # board | hand | full
```

数据可得性矩阵、三档配对数字、开销、训练接线与局限见 **`docs/FIDELITY_INJECTION.md`**；
实现为 `hsbg/az/train/human_obs_full.py`（Python 侧封装，Rust 核心零改动）。
