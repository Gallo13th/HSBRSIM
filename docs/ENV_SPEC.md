# 环境层接口契约（ENV_SPEC）

本文件是**环境 ↔ 策略 ↔ 训练 ↔ 评测**四方共同遵守的接口规范。
权威实现：`hsbg/env/spec.py`（数据结构）、`hsbg/env/`（行为）。
修改任何字段或语义时，先改 spec.py，再同步本文档，并升 `Observation.version`。

> **版本历史**
> - **v2**（2026-10-18）：`Observation.extra`（决策状态袋）。
> - **v3**（2026-10-22）：新增 `ActionKind.MOVE_MINION`（棋盘重排，动作枚举
>   追加在末尾，既有 12 类索引不变）；选择步 `extra["pending_choice_options"]`
>   暴露选项结构化第二 id/list（Dark Gift 的 `gift_id`、任务 offer 的
>   `reward_id`）；不可暂停阶段（EoT/淘汰/对手招募/终局清理）被自动结算的
>   智能体选择**不再静默**：`info["agent_choice_autoresolved"]` /
>   `info["auto_resolved_choices"]` / `stats` 计数 / `_errors` 日志三重标记。
>   全部为**向后兼容的新增**（既有字段/语义不变）。
> - **v3.1**（2026-10-23，P1）：choose 路径统一走引擎原子入口
>   `Game.take_choice(index, owner=)`（owner/队列原子，不再手写 pop+choose）；
>   选择结算回调抛错（`resolution_error`/failed 终态）不再被当成普通非法动作
>   丢弃：`ApplyResult.failed/choice_kind/choice_index/resolution_error`、
>   `info["choice_failed"]`/`info["resolution_error"]`/
>   `info["choice_resolution_errors"]`/`info["choice_failures"]` 与
>   `stats["choice_resolution_errors"]`/`agent_choice_autoresolved_failed`
>   全链路留痕，并刷新观测（不返回仍显示已消费选择的旧 obs）。
>   同时给出「EoT/淘汰/对手期能否暂停」探测结论（见 §3）。

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
| `version` | 协议版本（当前 **3**） |
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
| `extra` | **v2 新增；v3 增键**：决策相关但非实体槽位的状态（纯 dict，可 pickle） |
| `log` | 调试日志（策略不得依赖） |

`Observation.version = 3`。`extra` 的常用键（与 `info["obs_extra"]` 同源）：

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
| `pending_choice_options` | **v3**：选择步选项结构（见 §2.1） |
| `env_stats` | **v3**：含 `agent_choice_autoresolved` 等自动结算计数 |

### 2.1 选择步选项结构（v3）

`EntityToken` 表达不了「二元组选项」的第二 id（Dark Gift 的 `gift_id`、任务
offer 的 `reward_id`）。v3 用 **extra 兼容方案**（不改 `EntityToken` 字段）：
`phase="choice"` 时 `extra["pending_choice_options"]` 为列表，元素与
`CandidateAction(kind="choose", option=i)` 的 `option` 下标一一对应：

```python
{"index": i,            # 选项下标（= choose.option）
 "card_id": str,        # 主卡 id（minion/quest/trinket/spell/...）
 "secondary_id": str|None,  # Dark Gift 的 gift_id / 任务 offer 的 reward_id
 "label": str|None,    # 引擎提供 labels 时的分支文本，否则 None
 "name": str,          # 主卡显示名（调试可读，策略应优先用 id）
 "secondary_name": str|None,
 "cost": int}          # 选项卡花费（未知 -1；饰品商店用）
```

`PendingChoice.prompt` 目前恒为空；`choose_one` 的 options 仍是脚本 key
（分支 label 需引擎侧提供 `labels` 属性后自动透传）。

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
| `move_minion` | **v3**：棋盘重排（`board[src_slot]` → 目标槽位） | src, position（目标槽位 0..n-1） |

**目标组合**：环境为需要目标的动作生成所有合法目标组合（例如战吼目标
可指向己方棋盘/酒馆；磁力只能指向己方机械；法术按其目标规则）。若某动作
的合法目标集合为空，则不生成该候选。

**棋盘重排（v3，`move_minion`）**：招募期可把棋盘随从拖到其它槽位（位置影响
战斗攻击顺序、Cleave/相邻效果）。实现说明：

- 引擎（vendored `hsrl2`）**没有公开 reorder API**。env 层采用最小可行接口：
  改 `hero.board` 列表顺序 + 调用引擎既有 `game._update_positions(hero)` 重算
  `ZONE_POSITION`；不 fire 事件、不触发 on_summon/入场/死亡流程、不动其它状态。
  因此语义与客户端拖拽换位一致（同一批实体，仅顺序变化）。
- 当前**枚举**只生成相邻交换（`board[i] ↔ board[i+1]`，共 n-1 个候选），
  避免 n*(n-1)（满场 42）挤占 `CANDIDATE_MAX=64` 的手牌打出预算；任意排列
  可经多次相邻交换达成。`apply_action` 本身已支持任意目标槽位（0..n-1），
  若后续放宽枚举只需改 driver。
- 观测无需新字段：`board` 元组顺序即槽位，`extra["board_states"][].zone_position`
  同步反映新顺序。

**选择结算契约（v3.1，P1）**：所有 choose 路径统一调用引擎原子入口
`Game.take_choice(index, owner=)`（`Game` 侧契约：owner 不符/空队列**不 pop**；
pop 后结算抛错 → 选择标记 `failed + resolution_error`，终态不可重试）。

- 交互式 choose（`env.step`）：越界/owner 不符在 take_choice 前被拦截（队列
  不消费）→ `info["invalid"]=True`、`action_error_type=GameStateError`；
  结算回调抛错 → `ApplyResult.failed=True`，env 返回
  `info["invalid"]=True` + `info["choice_failed"]=True` +
  `info["resolution_error"]={kind,index,error_type,error,resolution_error}`，
  并**刷新观测**（失败选择已消费；若还有嵌套/后续选择则继续暴露为
  `phase="choice"`），对局可继续（不会卡死）。
  > 注意：该分支虽仍按"非法动作"给惩罚/计数，但选择已被引擎消费（failed
  > 终态），所以状态**已推进**且观测必须刷新——与"普通非法动作不推进状态"
  > 语义不同（`failed`/`resolution_error` 是区分标志）。
- 自动结算（对手招募/EoT/淘汰/终局清理/`auto_choice=True`）：失败记录进
  `info["choice_resolution_errors"]`、`info["choice_failures"]`、
  `stats["choice_resolution_errors"]`、`agent_choice_autoresolved_failed`
  与 `env._errors`（`choice_failed:<where>:...`）。

**不可暂停阶段的选择（v3 可见性 + v3.1 探测结论）**：`end_recruit_phase` 内
（EoT/战斗/淘汰）产生的智能体 `PendingChoice` 仍按既有契约自动结算；v3 起
**不再静默**：

- `info["agent_choice_autoresolved"]`：本局累计自动结算的智能体选择数；
- `info["auto_resolved_choices"]`：最近明细（≤64 条，纯数据；结算失败的
  记录带 `failed/error_type/error`）；
- `stats["agent_choice_autoresolved"]` + 按场景细分
  `agent_choice_autoresolved_{end_recruit_phase,opponent_phase,game_over,
  auto_choice_config}`（`obs.extra["env_stats"]` 可见）；
- `env._errors` 追加 `auto_choice:<where>:kind=...:picked=i/n:turn=T`（有界）；
- **新回合开始后**产生的智能体选择（任务/饰品三选一）仍会保留为
  `phase="choice"` 决策步（ChoiceQueue `hold_fn` 契约不变）。

**可暂停性探测（2026-10-23）**——结论与依据（回归：
`tests/test_env_choice_contract.py::test_probe_*`）：

1. **EoT / 淘汰 / 战斗：不可暂停。** `Game.end_recruit_phase` 是普通同步方法
   （非 generator/coroutine，无 `resume/continue` 入口，源码无 `yield/await`）。
   选择是在该方法调用栈内部由 `ChoiceQueue.append` 就地结算的；若在 append
   中抛异常"挂起"，会中止 `end_recruit_phase` 的后续步骤（战斗/淘汰/下一回合
   开始不完整），引擎没有续跑状态可恢复 → 只能当场结算 + 留痕。
2. **对手招募期：技术上可行但当前不实现（设计债，P2）。** 该阶段由 env 自己的
   `_drive_opponents` 循环驱动，可以保留智能体选择并中断；但 `_end_turn_step`
   目前是单 step 完成「驱动对手 → end_recruit_phase」的原子流程，要暂停必须
   改成**跨 step 的 end_turn 续跑状态机**（step 语义/奖励/终止契约扩展），且会
   改变"选择创建时刻 vs 结算时刻"的时序（可能影响后续对手动作与战斗）。
   当前统一 auto-resolve 并记入 `where="opponent_phase"` 的诊断。
3. **战斗期选择：按 live 语义自动结算**（战斗中玩家无决策），仍留痕。
4. 新回合开始后的（任务/饰品）选择可 hold → 作为 `phase="choice"` 决策步。

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
  terminated_reason, seed, episode_steps`；v3 起另含
  `agent_choice_autoresolved` / `auto_resolved_choices`（不可暂停阶段自动
  结算的智能体选择）；v3.1 起另含 `choice_resolution_errors` /
  `agent_choice_autoresolved_failed` / `choice_failures`（累计）与
  `choice_failed` / `resolution_error`（本步 choose 结算失败时）——见 §3。
- `obs.extra["env_stats"]` 同步包含上述 stats 计数（与 info 同源）。

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

## 9. 2026-10-26 增补：后端可插拔 / 快照 / 不变量（向后兼容）

> 本节为 AutoTavern 借鉴升级（`docs/AUTOTAVERN_UPGRADE.md`）新增说明。
> **`Observation` 字段与语义未变，`Observation.version` 仍为 3**；新增
> 能力全部是环境层叠加模块/可选后端，不破坏既有 checkpoint 与消费方。

### 9.1 可插拔后端（`hsbg.rl.envs.make_env`）

| backend | 类 | 说明 |
|---|---|---|
| `hsrl2` / `real` | `hsbg.env.BattlegroundsEnv` | **默认**，37.0.0 引擎，本文 §1–§8 全部契约 |
| `auto` | 同上（不可用回退 `mock`） | 历史语义保留 |
| `mock` | `MockBattlegroundsEnv` | 无引擎的确定性合成环境（测试用） |
| `taverngym` | `hsbg.backends.TavernGymEnv` | **可选参照后端**（AutoTavern Rust 引擎，36.6.3；需安装 `taverngym`） |

`TavernGymEnv` 同样实现 `hsbg.rl.api.EnvLike` 并返回 `hsbg.env.spec.Observation`，
但它是**参照/评测**后端，不是训练后端的直接替代：

- 数据版本 36.6.3（本仓库 37.0.0），卡池/数值/英雄不同，动作/观测空间不同；
- 候选动作为 TavernGym 245 维精确 legal mask 的展开，数量可能 **超过**
  `spec.CANDIDATE_MAX=64`（按 64 padding 的编码器会丢动作，故不用于现有策略训练）；
- `tavern`/`trinkets`/`choice` 槽位可能超过本文的展示上限（不截断，文档注明）；
- 仅两处 spec 外扩展：`kind="cancel"`（取消目标选择）与
  `extra["taverngym"]`（原始 245 维 mask / flat 动作下标 / turn_raw 等）。

详见 `docs/TAVERNGYM_BACKEND.md`；`tests/test_backend_taverngym.py`（42 项）覆盖
EnvLike 契约、mask 内动作全部可执行、确定性、save/load 字节一致、与上游
`taverngym.SoloEnv` 逐步 state 等价。

### 9.2 环境精确快照 / 恢复（`hsbg.env.snapshot`）

```python
from hsbg.env.snapshot import snapshot, restore, clone_env
snap = snapshot(env)            # O(几 ms)，不改变 env
...                             # 任意推进
restore(env, snap)              # 原地恢复：obs/候选/统计/RNG 逐位一致
twin = clone_env(env)           # 独立 env 副本
```

覆盖：引擎全状态（`hsbg.planning.model.clone`，含 RNG/PendingChoice/
pending_hand_queue/deferred_actions/池/战斗记忆）、名次账本、大厅视图别名、
env 事件监听重绑、全部环境计数器/统计/选择留痕，并重建 `_obs`/候选。
验收语义：snapshot→restore→相同动作序列与「不 snapshot 的原轨迹」逐步
观测/奖励一致；快照不改变原 env；连续 snapshot/restore 幂等；决策步稳态
之外/终止后/跨构造配置快照会抛 `SnapshotError`（明确报错，不产出不一致快照）。
限制（对手策略实例状态不重建、策略外部 RNG 不纳入等）见 `docs/ENV_SNAPSHOT.md`。

### 9.3 结构不变量（`hsbg.env.invariants`）

移植自 AutoTavern `invariants.rs` 的只读检查（不修改状态/不消耗 RNG/不触发事件）：
`check_game(game) -> List[str]`、`check_env(env) -> List[str]`、
`state_digest(...)`（跨进程稳定的状态摘要，供快照对拍）。

- 检查：棋盘/手牌/酒馆容量、tier/金币/存活血量、随从属性（atk≥0、
  hp≤max_hp）、实体唯一性、名次合法、候选/观测一致性；
- **不移植**池守恒：HSBRSIM 明确允许「效果生成副本不占池」（RULES §2.3；
  金色返还、purge、注入等），总量/分种族守恒按设计不成立；改为池簿记合法性
  弱检查（剩余量非负、purge 后不回池、不超过初始份数上限）；
- 已知偏差用显式开关（`strict_tavern_slots` / `strict_unique_ranks`），
  默认不误报；偏差登记见 `docs/ENV_SNAPSHOT.md`；
- 接入：`python scripts/validate_env.py --games 20 --check-invariants`
  （默认关闭，不影响既有验收行为）。

### 9.4 精确动作掩码验收

`tests/test_env_invariants.py` / 环境契约测试保证：
**`env.legal_actions()`（= `obs.candidates`）中的每个候选都能被引擎接受并推进
状态**（在 clone 上逐个尝试，不污染主局）；`env.action_mask()` 与候选
长度/顺序一致；非法动作返回 `info["invalid"]=True` 且状态不推进。
与 AutoTavern「`Game::legal_mask` 允许的动作都被 `apply` 接受」的契约等价。

---

## 10. 2026-10-26 第二阶段增补：AutoTavern 标准 profile（std）

> 用户决策（P2）：HSBRSIM 与 AutoTavern（TavernGym）做**可比基线**——动作空间与
> 观测全面对齐；游戏内支持但双方未实现的操作作为扩展动作补充。旧候选动作/实体
> token 观测量接口保留为 **legacy profile**，`Observation`（v3）字段与语义不变。
> 本节为**新增 profile**，不改变 §1–§9 的 legacy 契约。

### 10.1 标准动作空间（`hsbg.env.action_space_std`）

前 **245** 个动作与 AutoTavern `N_ACTIONS=245` **索引/语义/`action_name` 逐位一致**：

| 索引 | 数量 | 动作 |
|---|---|---|
| 0 / 1 / 2 / 3 | 1 each | EndTurn / Refresh / Freeze / Upgrade |
| 4..5 | 2 | HeroPower(slot 0..1) |
| 6 / 7 | 1 each | DarkGift / Cancel |
| 8..15 | 8 | Buy(shop slot 0..7) |
| 16..22 | 7 | Sell(board slot 0..6) |
| 23..29 | 7 | Activate(board slot 0..6) |
| 30..45 | 16 | Choose(option 0..15) |
| 46..125 | 80 | Play{hand 0..9, pos 0..7} |
| 126..195 | 70 | Magnetize{hand 0..9, board 0..6} |
| 196..244 | 49 | Move{from 0..6, to 0..6} |

**扩展段（索引 ≥245，只追加、不改变前 245）**：`N_EXT_ACTIONS=29`、
`N_TOTAL_ACTIONS=274`：

| 索引 | 动作 | 依据 |
|---|---|---|
| 245 | Unfreeze | AutoTavern 只有 Freeze 无解冻；游戏可点掉整馆冻结，HSBRSIM 引擎已有 `unfreeze_tavern`（F-23） |
| 246..249 | HeroPower(slot 2..5) 预留 | HSBRSIM `hero_power_ids` 为列表，未来多技能扩展（P2-C 操作探针 OPS-09） |
| 250..265 | Choose(option 16..31) 预留 | AT 固定 16 选项；HSBRSIM `PendingChoice.options` 无固定上限（发现/饰品/任务） |
| 266..273 | FreezeSlot(slot 0..7) | 按槽位冻结/解冻（7 随从 + 1 法术槽）；证据：37.0.0 卡面 `BG22_HERO_004p` “Freeze them both” + P2-C ops_probe OPS-02；两引擎均无公开单槽 API，P3 环境接入时补引擎/env 映射 |

模块同时提供 `encode/decode`、`SEGMENTS`、`is_std_index/segment_of`、
`candidate_to_std*/std_to_candidate`（与 legacy `CandidateAction` 双向投影；
目标折叠到后续 `Choose`，`hero_power` 槽位属于有损投影，详见
`docs/ACTION_SPACE_STD.md` §5）。**扩展动作当前仅有编码/mask 位定义；
环境层应用（如 UNFREEZE）在 P3 接入**（未实现时 mask 恒 False）。

### 10.2 标准观测（`hsbg.env.obs_std`）

与 AutoTavern `layout()` **32 项逐位一致**：`features` = **3227** 个 float、
`cards` = **124** 个卡牌索引；块顺序/块大小/字段偏移见 `docs/OBS_STD.md`
（MINION_F=31、ITEM_F=40、GLOBAL_F=53、N_QUESTS=3、QUEST_F=2、N_SECRETS=5、
OPP_F=9、N_OPP=7、PENDING_KINDS=9、N_SHOP=8、N_BOARD=7、N_HAND=10、
N_CHOICE=16、N_POS=8、N_POWERS=2）。`decode_blocks(features, cards)` 提供只读
块视图；`N_CARDS` 词表由**数据版本**决定（AT 36.6.3 参考 3984；HSBRSIM 37.0.0
以生成数据的卡表为准）。

### 10.3 可比性契约与迁移

- **同引擎 + 同数据版本**时，标准 profile 的动作索引与观测块**逐位可比**；
- 跨数据版本（AT 36.6.3 vs HSBRSIM 37.0.0）时，动作索引仍逐位可比，
  但 `cards` 卡牌下标需按 `card id` 重映射（块布局与浮点字段语义可比）；
- 旧策略/checkpoint 属 **legacy profile**（`Observation` v3 + 动态候选动作），
  不自动兼容 std profile；迁移与重训计划见 `docs/ACTION_SPACE_STD.md` §7、
  `docs/OBS_STD.md` §9–10；
- P3 接入环境/训练时：新增 245 维（+扩展）`action_mask`、std 观测编码器与
  固定动作空间策略头；legacy profile 保留用于对照与既有资产。
