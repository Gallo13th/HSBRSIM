# 环境层接口契约（ENV_SPEC）

本文件是**环境 ↔ 策略 ↔ 训练 ↔ 评测**四方共同遵守的接口规范。
权威实现：`hsbg/env/spec.py`（数据结构）、`hsbg/env/`（行为）。
修改任何字段或语义时，先改 spec.py，再同步本文档，并升 `Observation.version`。

---

## 1. 总体模型

酒馆战棋是 8 人同时进行的回合制游戏。环境采用「单智能体 + 7 个脚本对手」：

- 智能体固定为 `heroes[agent_index]`（默认 0 号）。
- 每回合（招募阶段）智能体可以执行任意多个原子动作，直到选择 `end_turn`。
- `end_turn` 后环境**自动**驱动所有对手完成其招募阶段，再调用引擎
  `game.end_recruit_phase()`：配对 → 逐对 `run_combat` → 幽灵战 → 淘汰 → 下一回合。
- 智能体被淘汰或仅剩 1 人时 episode 结束。
- 引擎的 `PendingChoice`（发现/三选一/任务/饰品/英雄技能目标）以「选择步」
  出现：观测 `phase="choice"`，候选动作只有 `choose`。

```
reset() ──► obs(招募/选择)
   ▲                 │ step(action)
   │                 ▼
   └── 环境推进 ◄── 引擎结算
        │
        ├─ 有智能体待选选择 → 返回 phase="choice" 的 obs
        ├─ 智能体存活且未结束 → 返回 phase="recruit" 的 obs
        └─ 智能体淘汰/游戏结束 → terminated=True, 名次奖励
```

## 2. Observation（观测）

`hsbg.env.spec.Observation` 字段（完整定义见源码）：

| 字段 | 含义 |
|------|------|
| `version` | 协议版本（当前 1） |
| `turn` | 回合数（1 起） |
| `phase` | `"recruit"` / `"choice"` / `"game_over"` |
| `hero` | `HeroToken`：health/armor/tier/gold/upgrade_cost/power_* |
| `board` | 己方棋盘随从，从左到右（≤7） |
| `hand` | 手牌（≤10） |
| `tavern` | 本回合酒馆展示（随从+酒馆法术，≤7） |
| `trinkets` | 已获得饰品（≤2） |
| `quest` | 当前任务（可为 None） |
| `opponent_board` | **上一场**对手的战前战团（官方可见信息，≤7） |
| `lobby` | 8 名玩家摘要（血量/护甲/等级/存活/名次） |
| `alive_count` / `total_players` / `rank` | 大厅统计与当前名次 |
| `pending_choice` | `PendingChoice`：kind/options/for_agent；非 choice 步为 None |
| `candidates` | 本步合法候选动作元组（顺序即动作下标） |
| `extra` | **v2 新增**：决策相关但非实体槽位的状态（纯 dict，可 pickle） |
| `log` | 调试日志（策略不得依赖） |

`Observation.version = 2`。`extra` 的常用键（与 `info["obs_extra"]` 同源）：

| 键 | 含义 |
|----|------|
| `frozen_tavern` | 酒馆是否冻结 |
| `power_uses_left` / `second_power_id` | 英雄技能本回合剩余次数（主/副槽） |
| `quest_progress` / `quest_reward` | 任务进度与奖励 |
| `dark_gift_uses_left` | 本局暗黑赠礼剩余次数 |
| `next_opponent` / `last_opponent` | 下一/上一对手身份（可见信息） |
| `elimination_order` | 已淘汰玩家顺序 |
| `last_combat` | 最近一场战斗结果摘要 |
| `pending_hand_queue` | 满手等待入场的生成卡数 |
| `minion_flags` | 随从的 EXHAUSTED/FROZEN/ACTIVATE_USED/WINDFURY_ATTACKS 等 |

`extra` 必须可 pickle、禁止放引擎对象；训练侧可选择性编码（不要求策略使用全部键）。

`EntityToken`：`card_id, card_type, zone, slot, atk, health, tier, cost,
races, keywords, golden, entity_id, name`。

**槽位语义**：`zone+slot` 唯一确定观测中的一个实体；候选动作用
`src_zone/src_slot`、`tgt_zone/tgt_slot` 引用它们。每步重新构建观测，
槽位下标只在**当前 obs** 内有效。

## 3. Action（动作）

候选动作 `hsbg.env.spec.CandidateAction`：

| kind | 语义 | 关键字段 |
|------|------|----------|
| `buy` | 从酒馆购买 `tavern[src_slot]` | src |
| `sell` | 出售 `board[src_slot]` | src |
| `play_minion` | 从手牌打出 `hand[src_slot]` | src, position, tgt（战吼/磁力目标） |
| `play_spell` | 从手牌施放 `hand[src_slot]` | src, tgt |
| `reroll` | 刷新酒馆 | — |
| `upgrade` | 升级酒馆 | — |
| `freeze` | 冻结酒馆（**单向**：仅未冻结时生成；不提供解冻，下回合自动刷新清除） | — |
| `hero_power` | 使用英雄技能 | tgt（可选） |
| `activate` | 使用 `board[src_slot]` 的 Activate | src |
| `use_dark_gift` | S14 黑暗赠礼 | — |
| `end_turn` | 结束招募阶段 | — |
| `choose` | 结算选择 `option` | option |

**目标组合**：环境为需要目标的动作生成所有合法目标组合（例如战吼目标
可指向己方棋盘/酒馆；磁力只能指向己方机械；法术按其目标规则）。若某动作
的合法目标集合为空，则不生成该候选。

**非法动作**：环境中永远不应出现非法候选；若调用方传入非候选动作，
环境返回不推进状态、`reward=invalid_action`、`info["invalid"]=True`。

**防死循环（关键）**：`freeze` 免费且可切换，未训练策略会反复选择它
（实测 2991/3000 步）。环境因此提供三层保护：

1. `max_actions_per_turn`（默认 40）：本回合成功动作达到预算后，候选只
   保留 `end_turn`（`choose` 步不受影响）；回合切换自动重置。
2. `freeze` 单向化：每回合最多 1 次。
3. 无进展保护：同一回合连续 3 次动作后关键状态（金币/生命/费用/手牌/
   酒馆/棋盘/冻结标记/场面战力）完全无变化 → 候选只保留 `end_turn`。

## 4. Env API

```python
from hsbg.env import BattlegroundsEnv
from hsbg.env.spec import EnvConfig, RewardConfig

env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=42)
obs = env.reset(seed=42)                 # -> Observation
obs, reward, terminated, truncated, info = env.step(action)
env.legal_actions()                      # -> Tuple[CandidateAction, ...]（== obs.candidates）
env.action_mask()                        # -> Tuple[bool, ...]（长度 = len(candidates)）
env.close()
```

构造参数（见 `EnvConfig`）：`num_players` / `opponent` / `hero_id` /
`anomaly` / `max_turns` / `max_steps` / `max_actions_per_turn` /
`auto_choice` / `seed` / `reward`。

- `reset(seed=None)`：创建 8 名英雄、`game.start_game()`、应用异变（可选）、
  自动结算对手的选择、返回智能体首个决策观测。
- `step(action)`：校验动作 → 应用到引擎 → 自动结算对手选择 → 自动驱动对手
  招募（仅当智能体 `end_turn`）→ 返回新观测与奖励。
- 确定性：同一 `seed` + 同一动作序列 ⇒ 完全相同的观测/奖励。
- 多进程安全：`env` 可在 worker 进程内创建；观测是纯数据（可 pickle）。
- 兼容外观：提供 `observation_space` / `action_space` 属性（`dict`/`None`），
  以及 `reset/step` 五元组，便于 Gymnasium 包装；但**不**依赖 gymnasium。

### step 内部顺序（必须严格执行）

智能体动作 → `game` 结算 → 若有智能体 `PendingChoice` → 返回 choice obs；
否则若智能体 `end_turn` → 驱动 7 个对手（每人：结算选择 → 执行动作序列 →
`end_recruit_phase` 由引擎统一调用）→ 结算战斗/淘汰 → 若智能体淘汰或
`game.finished` → terminated，否则下一回合 recruit obs。

对手招募动作序列由 `hsbg.agents` 的策略决定，**必须**：
1. 每次动作后 `pop+choose` 结算其 PendingChoice；
2. 受 `max_opponent_actions` 保护；
3. 只使用引擎公开 API（`Game.buy_from_tavern` 等），不得直接篡改棋盘。

### 终止契约（所有分支强制，2026-10-18）

**任何分支都不得返回「终局态但 `terminated=False`」的 `(obs, reward, False, False, info)`**。
统一 helper 在每个 step 分支（招募动作 / choice / end_turn / invalid）之后检查，
按优先级：

1. 智能体淘汰（`not agent.is_alive`）→ `terminated=True`、`reason="eliminated"`、
   `rank = 淘汰时存活数 + 1`、给 placement 奖励；
2. 游戏结束（`game.finished`）→ `terminated=True`、`reason="game_over"`；
3. 步数超限（`max_steps`）→ `truncated=True`、`reason="max_steps"`；
4. 回合超限（`max_turns`）→ `truncated=True`、`reason="max_turns"`；
5. 兜底：`obs.phase == "game_over"` 或 `candidates` 为空但 `_done=False`
   → 立即收口（`terminated=True`），**不得**继续返回 invalid。

已经在终局后再次 `step()`：返回 `terminated=True`、`invalid=False`、
`info["episode_done"]=True`，且 `episode_steps` 不再增长。
所有终局 `info` 必含：`rank / agent_rank / terminated_reason / truncated /
episode_steps / alive_count`。

（回归：`tests/test_env_coverage.py::TestTerminationContract`，
含真实复现 `seed=24` 的自伤英雄技能淘汰路径。）

## 5. Reward（奖励）

`RewardConfig`（默认值见源码）：

- **终局名次**：`placement * (1 - 2*(rank-1)/(num_players-1))`
  （第 1 名 +1，最后一名 -1）。
- **生命变化**：`health_delta * (health_after - health_before)`（每回合）。
- **战斗净伤害**：`combat_damage * (造成伤害 - 承受伤害)/10`。
- **棋盘战力变化**：`board_power_delta * Δ(sum atk+health)/50`。
- 非法动作惩罚、超时惩罚、每步惩罚。
- 所有奖励在 episode 内累加；训练侧再做 return 标准化。
- `info` 必须含：`turn, rank, health, alive_count, combat, wrong_action,
  terminated_reason, seed, episode_steps`。

## 6. 对手与教师

`hsbg.agents` 提供统一接口：

```python
class OpponentPolicy(Protocol):
    name: str
    def choose(self, game, hero, env_ctx) -> Optional[object]:
        """返回下一个要执行的动作（引擎层 action descriptor），None=结束回合。"""
```

内置：
- `random`：随机合法动作；
- `heuristic`：贪心买/打/升级/刷新（默认对手）；
- `teacher`：更强的规划启发式（BC 教师；可后续接入搜索）。

对手必须**同构**（同样受金币/手牌/等级限制），禁止作弊读取智能体隐藏信息。

## 7. 可观测性边界（POMDP）

智能体只能看到：
- 自己的完整信息；
- 上一场对手的战前战团；
- 大厅公开信息（血量/护甲/等级/存活）。

**禁止**把对手当前手牌/金币/酒馆展示放进观测。`opponent_board` 用
`game.last_opponent_warband(hero)` 取（官方可见）。历史对手信息可后续以
`Observation` 扩展字段提供，但必须升 version。

## 8. 工程约束

- 环境层单步开销目标：< 5 ms（不含战斗）；单局 8 人 < 500 ms。
- 不做 I/O、不打日志到 stdout（通过 `info`/`log` 字段）。
- 训练用向量化：`hsbg/env/vec_env.py` 基于 `multiprocessing`，接口
  `VecEnv(num_envs, env_kwargs)`，`reset() -> List[Observation]`，
  `step(actions) -> (List[Obs], rewards, dones, infos)`，支持 auto-reset。
- 每个环境实例独占一个 `Game`；禁止全局单例。
