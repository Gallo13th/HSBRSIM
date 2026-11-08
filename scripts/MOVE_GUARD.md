# 换位去抖守卫（Move de-bounce guard）

> 一句话：在**采集/策略层**给 `Move`（动作 196..244）加三条去抖规则——挡掉逆换位、
> 挡掉同一 `(from,to)` 的重复、每回合换位次数到 cap 后屏蔽全部换位——让策略从
> 「同一动作连按几十次」变成「每回合最多几次有意义的调整」。**默认关闭**，关闭时与
> 旧路径逐位等价。

相关实现：`hsbg/az/train/move_guard.py`（规则/统计）、`hsbg/az/train/ppo.py`
（`CollectConfig.move_guard` + `PPOSelfPlayPolicy` 采样前改写 mask）、
`hsbg/az/train/parallel_collect.py` / `hsbg/az/train/process_pool.py`（meta 汇总）、
`scripts/train_entity_sync.py` / `scripts/train_az_ppo.py`（CLI）、
`scripts/quality_monitor.py`（评测指标）、`tests/test_move_guard.py`。

## 1. 动机（实测）

- 换位动作段：`A_MOVE=196`，`Move(from,to) = 196 + from*7 + to`，共 49 个（`196..244`）。
- 从 `runs/az_entity_s9` 的 checkpoint 实测（`scripts/quality_monitor.py --games 64`，
  采样策略；见 §7.2 的 A 行）：
  - 全部回合平均 2.61 次/回合，但**有换位发生的回合平均 19.9 次、最高 40 次**
    （打满 `--max-actions-per-turn`）；
  - 其中 74–93% 是**同一个动作连按**（历史实测）；
  - 在换过位的回合里，**24.6% 的回合净盘面不变**（`board_end` 的卡牌序列 ==
    `board_start`，纯空转），白白消耗 40 动作/回合的决策上限，也让 PPO 的换位
    logprob 被反复强化。
- `--move-head-split 1`（有向双投影）只让方向选择有偏好（连按 93%→74%），
  没有解决「同一动作连按」本身，且 human 面板显著劣化（本次 A/B 复现：+0.51）。

守卫的作用是**改变行为分布的非支撑集**：被禁的换位在采样时概率恒 0，采集到的
on-policy 样本自然把「连按」的 logprob 压下去。

## 2. 规则

对 learner 的每个决策，在采样**之前**改写动作 mask（只动 `Move` 段，其它动作不变）：

| 规则 | 触发条件 | 效果 | 计数键 |
|---|---|---|---|
| 逆换位屏蔽 | 本回合 learner **上一步**是 `Move(from=a,to=b)`（a≠b） | 屏蔽 `Move(from=b,to=a)`（撤销动作） | `move_guard_blocked_inverse` |
| 同动作上限 | 同一 `(from,to)` 本回合已出现 `>= move_repeat_limit` 次 | 屏蔽该动作 | `move_guard_blocked_repeat` |
| 每回合换位上限 | 本回合已选换位 `>= move_cap` 次 | 屏蔽全部 49 个换位 | `move_guard_blocked_cap` |

- 优先级：`cap > inverse > repeat`。`blocked_*` 记的是**被清掉的合法动作位数**
  （同一位只记一条规则），不是决策数。
- 「上一步」= 本回合 learner 的上一个动作（含非换位动作）。因此
  `Move(0,1)` → `Buy` → `Move(1,0)` **不**算逆换位（买入不会改变棋盘顺序，
  保留这一点是为了避免把有用的回摆一并禁掉；见 §8 讨论）。
- 状态按 `(game_id, seat, turn)` 隔离：lock-step 多局共用一个 policy 时互不影响，
  回合切换自动重置。
- **空掩码回退**：若屏蔽后只剩 `EndTurn`（或没有任何合法动作且 `EndTurn` 合法），
  回退为「只允许 EndTurn」并计 `move_guard_forced`；该决策按环境确定性约束记
  `forced=True`、`logprob=0`，不进 PPO 策略损失。若 `EndTurn` 也不合法，
  则完全回退原 mask（本决策不受守卫影响、不计数）。
- 记录的 `mask` 是**守卫后的 mask**：`old_logprob` 与实际采样分布一致（on-policy），
  被禁动作在损失里概率恒 0。

## 3. 参数 / CLI

| CLI | 默认 | 说明 |
|---|---|---|
| `--move-guard {0,1}` | `0` | 1=启用换位去抖守卫；**0=关闭（逐位等价）** |
| `--move-cap N` | `3` | 每回合换位次数上限（`0`=本回合禁止换位） |
| `--move-repeat-limit N` | `2` | 同一 `(from,to)` 本回合出现 `>=N` 次后屏蔽（`1`=不允许重复） |

`CollectConfig` 新增同名字段：`move_guard: bool = False`、`move_cap: int = 3`、
`move_repeat_limit: int = 2`。`scripts/quality_monitor.py` 也接受这三个参数，
用于在评测时对比「开/关守卫」的行为分布。

> 守卫只在 `PPOSelfPlayPolicy` 采样路径生效：`--lockstep 1`（s9 主路径）与逐局
> 采集路径都生效；Rust 采集器（`--rust-collector 1`，不经 Python 采样）不支持，
> 训练入口会 fail-fast。

## 4. 采集 meta

启用后写入 `history.jsonl` 的 `collect` 段（多进程按 shard 求和；关闭时**不新增任何键**）：

| 键 | 含义 |
|---|---|
| `move_guard` | 开关（true） |
| `move_cap` / `move_repeat_limit` | 生效参数 |
| `move_guard_decisions` | 守卫下的 learner 决策数 |
| `move_guard_moves` | 守卫下实际选中的换位次数 |
| `move_guard_blocked_inverse` / `_repeat` / `_cap` | 三类规则清掉的合法动作位数 |
| `move_guard_forced` | 屏蔽后只剩 EndTurn（守卫强制结束本回合）的次数 |

## 5. 评测指标（`scripts/quality_monitor.py`）

新增（对 64 局逐回合统计）：

- `moves_per_turn_mean` / `_p90` / `_max`：全部回合的平均/90 分位/最大换位次数；
- `moves_per_move_legal_turn_mean`：只在「本回合出现过合法换位」的回合上平均；
- `moves_per_move_turn_mean`：只在「本回合真的换过位」的回合上平均（空转回合的强度）；
- `net_board_unchanged_ratio`：`board_end == board_start` 的回合比例（全部回合）；
- `net_board_unchanged_move_ratio`：**只在换过位的回合里**净盘面不变的比例（空转率）；
- `tier_p50_t9` / `tier_p50_t12`：t9 / t12 的酒馆等级 p50。

> **部署侧（TavernArena）同样必须开守卫**：`scripts/arena_agent.act` 已接入同一个
> `MoveGuard`，`ARENA_MOVE_GUARD` 默认 `1`（`ARENA_MOVE_CAP=3`、
> `ARENA_MOVE_REPEAT_LIMIT=2`）。不开时竞技场路径实测 moves/turn 均值 8.87 /
> p90 39.2 / max 40、50% 的有换位回合净盘面不变；开了是 0.76 / p90 3 / max 3。
> 开关、回合判定启发式与验证见 **`docs/ARENA_GUARD.md`**，
> `scripts/quality_monitor.py --policy arena` 可离线复现部署路径。

> 注意：本次顺带修了 `_play` 的驱动循环——历史实现用 `while needs_action(p)` 连续
> 推进，引擎在 EndTurn 后可能立刻进入下一回合，会把两个回合的 learner 动作记进
> 同一 turn 行（实测出现「单回合 73 次换位」的假数据）。现与 official eval
> （`hsbg/az/train/evaluate.py`）一致：**每个 pass 每个座位只走一步**。
> 因此本文件的历史 `quality.json` 与新数字不能直接混比。

## 6. 单测

`tests/test_move_guard.py`（16 项）：

- 逆换位被屏蔽 / 只对「上一步是换位」生效；
- 同动作上限（默认 2 次后屏蔽）、cap 生效（全部换位清 0）；
- 空掩码回退：只剩 EndTurn → forced 计数；EndTurn 不合法 → 完全回退原 mask；
- `move_guard=0`：mask/record 键集合/动作与概率与旧路径逐位一致；掩码里没有 Move 时
  守卫开/关动作序列完全相同（不扰动 RNG 流）；
- 多局（game_id）/多回合（turn）/多座位（seat）状态隔离；
- 真实引擎 lock-step 采集：meta 写入守卫统计、每回合换位 ≤ cap、逆换位永不出现；
  关闭守卫时 meta 不出现任何 guard 键。

## 7. A/B（cuda:7，从 `runs/az_entity_s9/model.pt` 起，40 iter，同 seed 14100）

协议与 s9 一致（`--lockstep 1 --games 192 --processes 4 --gpus 7`，其余超参同主训练，
checkpoint `runs/ab_move_guard/base.pt` = 启动时 s9 `model.pt` 的副本，sha256
`734fd9b9…e25f`），仅切换守卫/换头：

- **A**：现状（`--move-guard 0 --move-head-split 0`）
- **B**：A + `--move-guard 1 --move-head-split 1`
- **C**：A + `--move-guard 1`

三组均为 40 iter、seed 14100、无中断。评测（全部 cuda:7、greedy 面板不带守卫）：

- `quality_monitor.py --games 64 --seed-base 520000`（另跑 `--move-guard 1` 对照）；
- human 面板 96 局（`--games 96 --seats 8 --smoke --baseline-bot 0 --quantile auto`，
  seed_base 100000）；
- bot 面板 64 局（`c0_gate.py --games 64 --seats 8 --smoke`，seed_base 100000）。

产物：`runs/ab_move_guard/{A,B,C}/{model.pt,history.jsonl}`、`runs/ab_move_guard/eval/*.json`、
`runs/ab_move_guard/base.pt`（起点 checkpoint 副本）、`runs/ab_move_guard/logs/*.log`。

### 7.1 训练侧（40 iter）

| 组 | learner decisions | 训练中换位/决策 | guard：moves / blocked inv·rep·cap / forced | entropy（末） |
|---|---|---|---|---|
| A | 1,321,828 | —（守卫关） | — | 0.606 |
| B | 1,436,854 | 17.0% | 243,663 / 164,934·21,784·16,829,620 / 0 | 1.059 |
| C | 1,207,549 | 2.3% | 27,614 / 20,871·14,010·2,464,626 / 0 | 0.539 |

B 的 entropy 明显更高：`move_head_split` 给 Move 段新加了**随机初始化**的有向投影，
40 iter（lr=1.2e-6）远不足以把它训到与主干一致，是 B 变差的主要混淆项（见 7.3）。
`move_guard_forced` 在真实采集里为 0（`EndTurn` 通常还有别的合法动作可采样）。

附带效果：打满 40 动作/回合（`max_actions_per_turn` 强制 EndTurn）的次数
A 6,170 → B 1,592 → C 1,112——守卫把「连按换位 → 打满 40 动作」的循环直接拆掉了；
采集吞吐不受影响（A/B/C 分别 3,216/2,872/3,048 decisions/s，差异主要是同卡评测抢占）。

### 7.2 `quality_monitor.py --games 64`（换位次数 / 净盘面不变 / tier）

`moves/move_turn` = 只在「本回合换过位」的回合上平均（最能暴露连按空转）；
`net unchanged (move)` = 这些回合里 `board_end == board_start` 的比例。

| 组 | guard | 换位/回合（全部） | 换位/换位回合 | 最大/回合 | net unchanged (move) | net unchanged（全部） | tier p50 t9/t12 | mean rank |
|---|---|---|---|---|---|---|---|---|
| A | 0 | 2.613 | **19.91** | 40 | **24.63%** | 27.45% | 5 / 6 | 2.078 |
| A | 1 | 0.360 | 2.35 | 3 | 3.29% | 26.23% | 5 / 6 | 1.812 |
| B | 0 | 18.676 | 23.91 | 39 | 0.26% | 12.77% | 5 / 6 | 2.469 |
| B | 1 | 2.308 | 2.94 | 3 | 0.62% | 12.66% | 5 / 6 | 2.344 |
| C | 0 | 2.797 | 17.85 | 40 | 15.00% | 27.24% | 5 / 6 | 1.922 |
| C | 1 | 0.351 | **2.31** | **3** | **3.82%** | 24.43% | 5 / 6 | 1.734 |

- 开守卫后，**同一份权重**（A guard 0→1）从 19.91 次/换位回合掉到 2.35、最大 40→3，
  空转率 24.6%→3.3%：规则直接改变了行为分布（被禁换位在采样时概率为 0），与训练无关。
- C 在 `guard=0` 评测里仍是 17.85 次/换位回合、空转 15%：40 iter（~1.2M decisions）
  **不足以让权重自己戒掉连按**；守卫的作用在采集/评测时的 mask，而不是权重性质。
- tier p50 t9/t12 三组完全一致（5/6），守卫没有牺牲经济/升级节奏。

### 7.3 面板（greedy，评测侧不带守卫 = 部署口径）

| 组 | human 96 mean rank | human top4 | Δ(组−A) human [95% CI] | bot 64 mean rank | bot top4 | bot win | Δ(组−A) bot [95% CI] |
|---|---|---|---|---|---|---|---|
| A | 6.833 | 3.1% | — | 2.031 | 93.8% | 45.3% | — |
| B | 7.344 | 2.1% | **+0.510 [+0.229, +0.792]** | 2.922 | 76.6% | 45.3% | **+0.891 [+0.125, +1.672]** |
| C | **6.792** | **5.2%** | **−0.042 [−0.198, +0.115]** | **1.922** | 93.8% | **56.3%** | −0.109 [−0.453, +0.234] |

（配对 bootstrap 5000 次，同一 seed/seat 逐局配对；96 局 human、64 局 bot。）

- **C（只开守卫）在两个面板都不劣于 A**：human 差值 −0.04（CI 上界 +0.115 < +0.15），
  bot 还略好（1.92 vs 2.03，win 56.3% vs 45.3%）。
- **B（守卫 + 换头）显著劣化**：human +0.51、bot +0.89，CI 都不含 0。这与背景里
  「`--move-head-split 1` 让 human 面板显著劣化」一致，归因是随机初始化的有向投影
  未训练充分（entropy 1.06 vs 0.54–0.61），**不是守卫本身**。

### 7.4 判据核对

| 判据 | A | B | C |
|---|---|---|---|
| 换位次数 ≤5/回合（guard=1） | 0.36（max 3） | 2.31（max 3） | **0.35（max 3）** |
| 净盘面不变（换位回合）<5%（guard=1） | 3.29% | 0.62% | **3.82%** |
| human 面板不劣化（B−A ≤ +0.15） | 基线 | ✗ +0.51 | ✓ −0.04（C−A） |

## 8. 结论与建议

**建议 s9 启用守卫，但不启用 `--move-head-split`：**

```bash
--move-guard 1 --move-cap 3 --move-repeat-limit 2 --move-head-split 0
```

理由：

1. 采集侧立刻把「换位/换位回合」从 19.9 降到 2.3、最大 40→3，空转率 24.6%→3.8%，
   判据（≤5 次/回合、空转 <5%）都满足；
2. human 面板与 A 等价（配对 Δ −0.04，CI 上界 +0.115 ≤ +0.15），bot 面板略好
   （1.92 vs 2.03），tier 曲线不变 —— 没有用强度换去抖；
3. 加上 `--move-head-split 1` 的 B 在 human/bot 双双显著劣化（+0.51 / +0.89），
   且 40 iter 内 split 头 entropy 仍 1.06，属于已知的换头噪声，不应与守卫一起上；
4. 推荐参数就用默认 `cap=3 / repeat_limit=2`：B/C 的 `guard=1` 评测里换位/回合
   ≈0.35–2.3、最大 3，离 cap 还有余量；若后续 t12+ 盘面需要更多调整，可在长跑里
   用 `--move-cap 4/5` 做一次消融（本次未测）。

**必须注意的两点：**

- 守卫是**行为分布约束**（采样前改 mask），不是权重性质。40 iter（~1.3M decisions）
  不足以让策略在「关掉守卫」时自己停止连按：C 在 `guard=0` 评测里仍是 17.9 次/
  换位回合。因此训练全程保持 `--move-guard 1`；如果希望 **arena/部署** 也去抖，
  需要在 arena/评测侧套同一份 mask（本次按任务范围只做采集/策略层，未改 arena）。
- 守卫把「逆换位」限定为**紧邻上一步**的撤销；若中间夹了购买/打出，回摆不会被禁。
  这是有意的（买入不改变棋盘顺序，回摆仍可能是有意义的调整）；若长跑发现仍有
  2–3 步循环空转，可以把规则扩展成「本回合出现过的 (a,b) 的逆动作也屏蔽」，
  但那是更强的约束，需要重新 A/B。
