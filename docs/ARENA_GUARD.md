# 竞技场部署侧换位去抖守卫（ARENA_MOVE_GUARD）

> 一句话：训练期一直开着的「换位去抖守卫」必须在**部署/评测路径**也开着。
> 不带守卫的 s14 评测路径实测每回合换位 **p90 = 38 次**、max 打满 40 的动作上限，
> 23% 的回合净盘面完全不变（纯空转）。竞技场 `scripts/arena_agent.py` 现在
> **默认开启**同一套规则；`ARENA_MOVE_GUARD=0` 一键回退到旧行为。

相关实现：`hsbg/az/train/move_guard.py`（规则唯一实现，训练/部署共用）、
`scripts/arena_agent.py`（竞技场 `act` 接入 + 回合识别）、
`scripts/quality_monitor.py --policy arena`（离线驱动部署路径做度量）、
`tests/test_arena_move_guard.py`（15 项单测）、`docs/MOVE_GUARD.md`（训练侧规则）。

## 1. 为什么部署必须带守卫

s14 质量面板（96 局，seed_base 750000，`runs/quality/s14_70M.json`，**无守卫**）：

| 指标 | 值 |
|---|---|
| moves/turn 均值 | **6.81** |
| moves/turn p50 / **p90** / max | 0 / **38** / **40** |
| 有换位的回合占比 | 26.5% |
| 净盘面完全不变的回合比例 | **23.1%** |
| 有换位但净盘面不变的回合比例 | 33.0% |

同一 checkpoint 走**竞技场部署路径**（`scripts/arena_agent.act`，16 局，见 §5）更差：
moves/turn 均值 **8.87**、p90 **39.2**、max **40**，有换位的回合里 **50%** 净盘面不变。

原因很直接：Move 段（196..244）有 49 个动作，网络只要反复 argmax 同一个
`Move(from=a,to=b)` 就能无限刷决策，而盘面**不变**（换位只改棋盘顺序）。
每回合 40 个动作的预算被空转吃光，挤掉了买牌/升级/上怪的真实决策。

训练侧同一 checkpoint 打开守卫后：换位 29 → **2–3 次/回合**、净盘面不变
24.6% → 15%。所以：

1. **部署不开守卫 = 训练/推理分布不一致**：训练期模型从未见过「可以无限连按
   换位」的动作分布，部署时却允许，属于纯 OOD 空转；
2. 线上/计分对局是**每回合动作预算有限**的真实环境，空转直接损失回合预算；
3. 这不是模型能力问题，是**部署路径漏了一条训练侧已有的约束** —— 修在
   `arena_agent.act` 里，模型权重、checkpoint 格式、观测/动作布局都不变。

## 2. 开关与默认值

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `ARENA_MOVE_GUARD` | **`1`（开）** | `0/false/no/off/none` = 关闭（旧行为逐位一致）；其它值 = 开 |
| `ARENA_MOVE_CAP` | **`3`** | 每回合换位次数上限；达到后屏蔽**全部** 49 个换位动作 |
| `ARENA_MOVE_REPEAT_LIMIT` | **`2`** | 同一 `(from,to)` 本回合出现 `>= N` 次后屏蔽（`1` = 不允许重复） |
| `ARENA_CARD_MAP` | `runs/arena/card_map.json` | 设 `off`/`native` = 不做竞技场 36.6→37.0 卡牌映射（**离线用本地引擎观测驱动 `act` 时必须**） |
| `ARENA_ACTION_LOG` | 空（关） | 逐决策 JSONL；守卫开启时额外写 `move_guard` / `guard_forced` / `guard_blocked` / `moves_this_turn` / `turn_key` / `move_cap` / `move_repeat_limit` |

**默认开的理由**：s14 训练（`runs/az_entity_s14`）的 `CollectConfig.move_guard`
一直开着，守卫参数就是训练 CLI 的默认 `cap=3 / repeat_limit=2`。部署侧跟随训练，
不需要额外配置。

**回退方式**（线上不改代码）：

```bash
ARENA_MOVE_GUARD=0 ... python scripts/arena_client.py ...   # 单次回退
```

`ARENA_MOVE_GUARD=0` 时 `act` **不构造守卫、不建回合状态、不改 mask、不新增日志键**，
动作序列与旧代码逐位一致（单测 `test_guard_off_is_bitwise_legacy` 用 6 步固定
observation 序列逐位对拍纯 masked argmax）。也可以在 `arena_client.py` 的启动环境里
固定该变量做 A/B。

## 3. 与训练守卫的一致性

部署侧**直接复用训练那个类**，不是抄一份规则：

```python
from hsbg.az.train.move_guard import MoveGuard   # scripts/arena_agent.py
```

因此规则逐条相同（`MoveGuard.guarded_mask`）：

1. 逆换位屏蔽：本回合上一步是 `Move(a→b)` 时屏蔽 `Move(b→a)`；
2. 同动作上限：同一 `(from,to)` 本回合出现 `>= repeat_limit` 次后屏蔽；
3. 每回合 cap：本回合已选换位 `>= cap` 次后屏蔽全部 49 个换位；
4. 空掩码回退：被清空后若只剩 EndTurn（或没有合法动作），返回 EndTurn 并计
   `move_guard_forced`（与训练一样，属于环境确定性约束，不是行为分布采样）。

差异只在**状态键**：

| 维度 | 训练 `PPOSelfPlayPolicy` | 竞技场 `arena_agent.act` |
|---|---|---|
| 局 | `game_id`（采集侧递增） | `context["match_id"]`（缺失 = 0；字符串 id 进程内 hash） |
| 座位 | `seat` 参数 | `context["seat"]`（缺失 = 0） |
| 回合 | `game.turn` | `context["turn"]` → 观测指纹兜底（§4），映射成单调 `gen` |
| 动作记录 | `note_action`（实际执行的动作） | 同左 |

统计键名与训练 `move_guard_meta()` 完全一致：`move_guard`、`move_cap`、
`move_repeat_limit`、`move_guard_decisions`、`move_guard_moves`、
`move_guard_blocked_inverse|repeat|cap`、`move_guard_forced`；
`arena_agent.describe()` 额外给出 `enabled` / `seats_tracked`。
进程退出时若 `ARENA_ACTION_LOG` 打开，会打印一行 `[arena-agent] move guard: {...}`，
可直接核对线上守卫真的在工作。

## 4. 回合判定启发式（没有 reborn/replay 状态）

竞技场只给 `(match_id, seat, turn, phase, actions_used, action_limit, player_view)`，
没有本地引擎的完整回放/重生状态，所以「新回合」按下面的优先级判定：

1. `context["turn"]` 变化 = 新回合（**竞技场每步都给，主路径**）；
2. 之前没有 `context.turn`、现在有了 = 保守视为新回合；
3. 始终没有 `context.turn`（离线/旧客户端）→ 退回**观测指纹**：
   `features[0] * 20`（`global.turn`）+ 棋盘/手牌/酒馆的**卡牌多重集**变化 = 新回合。

指纹的选择理由：换位只改棋盘**顺序**（多重集不变），买/卖/刷新才会改多重集。
所以它在同一回合内相对稳定，但**不能区分**「同回合内买了一张牌」和「新回合」：
没有 `context.turn` 时会**提前重置**（漏挡一点，绝不会跨回合泄漏状态）。

明确局限：

1. **turn 数值复用**：reborn / 断线重连 / replay 若让 `turn` 数值不前进而进入新阶段，
   守卫会沿用上一段计数（偏保守，不会额外放宽）。换局请调用
   `arena_agent.reset_state()`（清回合历史、保留累计统计）；正常流程里每个
   `match_id` 天然隔离。
2. **座位**：`context.seat` 缺失按 0 处理；多座位并发（`continuous` 模式）必须由
   context 正确给出 seat，否则两个座位会共用一个回合状态。
3. **重试去重**：不按 `actions_used` 去重；同一 `(match, seat, turn)` 若被上层重试
   调用两次会记两次动作。竞技场 client 的 HTTP 重试不会重放 policy，实际不会触发。
4. 守卫**只**约束 Move 段（196..244）：不改引擎、不改观测、不改其它动作的分布。

## 5. 验证：部署路径短跑（守卫关 vs 开）

口径：`scripts/quality_monitor.py --policy arena` 用本地引擎 v1 观测驱动
`scripts/arena_agent.act`（**与线上同一条代码路径**），s14 checkpoint
`runs/az_entity_s14/model.pt`，16 局，seed_base 750000，cuda:7（训练在 cuda:3–6，
未打扰）。两组的唯一差别是 `ARENA_MOVE_GUARD`。驱动侧按竞技场的
`context.action_limit` 限制每回合 40 个动作（与训练评测 `max_actions_per_turn` 同口径；
不加这一条，本地引擎不会像服务器那样强制结束回合，无守卫策略会把 20,000 步预算刷满
→ 对局 truncation，短跑跑不完 —— 本次调试中实际发生：无守卫 16 局跑了 30 分钟只到第
12 局，单局 18k+ 步）。

| 组 | moves/turn 均值 | p50 | p90 | max | 有换位且净盘面不变 | 净盘面不变回合比 | mean_rank | top4 | win |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| arena 路径，守卫**关**（`ARENA_MOVE_GUARD=0`） | **8.87** | 0 | **39.2** | **40** | **50.0%** | 33.3% | 1.94 | 100% | 37.5% |
| arena 路径，守卫**开**（默认，`cap=3/repeat=2`） | **0.76** | 0 | **3** | **3** | **1.3%** | 20.1% | 1.69 | 100% | 50.0% |
| 参照：训练侧守卫（`--policy selfplay --move-guard 1`） | 0.75 | 0 | 3 | 3 | 0% | 16.1% | 1.69 | 100% | 56.3% |

结论：

- 部署守卫把 moves/turn 从 **8.87 / p90 39.2 / max 40** 压到
  **0.76 / p90 3 / max 3**，达到目标（均值 ≤3、p90 ≤5）；
- 有换位且净盘面不变的回合占比 50.0% → **1.3%**（空转基本消失）；
- 与训练侧守卫（0.75 / p90 3 / max 3）**几乎逐项相同** —— 「训练开着守卫、部署也开着」
  时两边行为一致；
- 16 局上的 mean_rank/top4 差异（1.94 → 1.69）样本太小，**不作为强度结论**；
  这里只证明「去抖生效且不打坏对局」。

守卫计数（`arena_s14_guard_on_g16.json` 的 `move_guard_meta`，16 局 / 281 回合）：
`decisions=4148`、`moves=213`、`blocked_inverse=149`、`blocked_repeat=113`、
`blocked_cap=30766`、`forced=0`。`blocked_cap` 很大的原因是口径与训练 meta 一致
（按**被清掉的动作位**累计：cap 用满后每个决策都会清掉当时全部合法换位位）。

单测：`tests/test_arena_move_guard.py`（**15 项**）覆盖逆换位、重复上限、cap、新回合
重置（context.turn 与观测指纹两条路径）、空掩码 forced 回退、关闭时逐位等价（含
action log 键集合）、默认值/非法环境变量兜底、以及「部署守卫就是训练那个类」的同一性
检查。


## 6. 复现命令

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM

# 部署路径（guard 关，基线）
ARENA_DEVICE=cuda:7 PYTHONPATH=rust/python:. $P scripts/quality_monitor.py \
  --checkpoint runs/az_entity_s14/model.pt --policy arena --device cuda:7 \
  --games 16 --seed-base 750000 --move-guard 0 \
  --out runs/quality/arena_s14_guard_off_g16.json

# 部署路径（guard 开，默认参数）
ARENA_DEVICE=cuda:7 PYTHONPATH=rust/python:. $P scripts/quality_monitor.py \
  --checkpoint runs/az_entity_s14/model.pt --policy arena --device cuda:7 \
  --games 16 --seed-base 750000 --move-guard 1 \
  --out runs/quality/arena_s14_guard_on_g16.json

# 训练侧守卫（参照）
ARENA_DEVICE=cuda:7 PYTHONPATH=rust/python:. $P scripts/quality_monitor.py \
  --checkpoint runs/az_entity_s14/model.pt --policy selfplay --device cuda:7 \
  --games 16 --seed-base 750000 --move-guard 1 \
  --out runs/quality/s14_guard_on_g16.json

# 单测
$P -m pytest tests/test_arena_move_guard.py -q
```

线上启用/回退：什么都不用做（默认开）；要回退就 `ARENA_MOVE_GUARD=0`。
