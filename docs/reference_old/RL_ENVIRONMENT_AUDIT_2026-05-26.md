# HSRL 强化学习环境实现审计报告

审计日期：2026-05-26  
审计对象：`hsrl/env/`, `hsrl/train/`, `hsrl/trajectory/`, `hsrl/advisor/`  
目标：评估 RL 环境是否可作为高保真训练基线，以及是否需要重构。  
结论：需要重构，但不建议推倒重写。应做“环境契约与动作/观测接口重构”，核心游戏引擎可以保留。

---

## 0. 执行摘要

当前 RL 环境已经具备可运行雏形：Gymnasium 单智能体封装、Discrete(50) 动作、Dict/flat observation、action mask、dense reward、trajectory opponent、Advisor 映射和多智能体自博弈框架都已存在。

但本轮审计发现多个训练级阻断问题：

| 等级 | 问题 | 影响 |
|------|------|------|
| P0 | `SelfPlayTrainer` 调用 `MultiAgentBattlegroundsEnv(dense_scale=..., preferences=...)`，但环境构造函数不接受这些参数 | 自博弈训练入口直接不可运行 |
| P0 | `BattlegroundsEnv.reset(seed=...)` 没有把 seed 传给 `Game`，同 seed 不可复现 | RL 训练、回放、对照实验不可信 |
| P1 | `init_cards()` 未导入 `hsrl.cards.spells` | 新进程训练环境 CardDB 不完整，法术池和法术动作缺失 |
| P1 | start-of-game hero power choice 没有 `action_mask`，`action_masks()` 在 `_game is None` 时崩溃 | MaskablePPO/MaskableDQN 对选择型英雄不可用 |
| P1 | `REARRANGE` 的 `_can_rearrange` 状态没有传入 `action_masks()` / `_build_info()` | mask 暴露非法动作，训练数据污染 |
| P1 | `build_action_mask()` 在满场时禁止所有 hand card，包括 spell | 满场无法施放法术，策略学习偏离真实游戏 |
| P1 | 默认随机对手英雄可导致 `reset(seed=0)` 崩溃 | 环境 reset 不稳定 |
| P2 | observation 使用 Python `hash()` 作为 card/anomaly/trinket 特征 | 跨进程/训练-推理特征不稳定 |
| P2 | 动作空间缺少站位、磁力目标、部分选择/发现的统一交互模型 | 高保真策略学习受限 |

判断：当前环境适合继续做引擎机制 smoke test，不适合作为最终 RL 训练基线。建议先完成一个收敛的 Env API 重构，再进入大规模训练。

---

## 1. 本轮验证命令

```bash
python -m pytest hsrl/tests/test_advisor.py -q
# 39 passed

python -m pytest hsrl/tests/test_rng_reproducibility.py -q
# 5 passed

python -m pytest hsrl/tests/test_discover_decision_state.py -q
# 9 passed

PYTHONPATH=. python /tmp/hsrl_rl_env_audit_smoke.py
# 复现 seed、mask、start-choice、spell mask 问题
```

直接阻断复现：

```bash
python -c "from hsrl.env.multi_agent_env import MultiAgentBattlegroundsEnv; MultiAgentBattlegroundsEnv(hero_ids=['BG20_HERO_100']*8, dense_scale=1.0)"
# TypeError: MultiAgentBattlegroundsEnv.__init__() got an unexpected keyword argument 'dense_scale'
```

```bash
python -c "from hsrl.env.battlegrounds_env import BattlegroundsEnv; e=BattlegroundsEnv(hero_id='BG20_HERO_100'); e.reset(seed=0)"
# AttributeError: 'NoneType' object has no attribute 'set_tag'
```

---

## 2. P0/P1 发现

### P0-001 自博弈训练入口不可运行

证据：

- `hsrl/train/self_play_trainer.py:332-339` 调用：
  - `dense_scale=...`
  - `preferences=...`
- `hsrl/env/multi_agent_env.py:93-102` 的 `MultiAgentBattlegroundsEnv.__init__()` 没有这两个参数。

影响：

- `SelfPlayTrainer` 当前无法创建环境。
- 文档里的三阶段 reward curriculum 没有落到环境实现。
- `_select_opponent_action()` 存在，但未接入 `MultiAgentBattlegroundsEnv` 的非 RL agent 行为，model-pool opponent 也没有真正参与行动。

结论：自博弈模块需要接口重构，不是单点 bugfix。

### P0-002 Reset seed 没有进入 Game

证据：

`BattlegroundsEnv.reset(seed=123)` 只执行：

- `super().reset(seed=seed)`
- `random.seed(seed)`

但 `Game.create_game()` 内部是 `game = Game([])`，没有传 seed。smoke 结果：

```text
obs_equal: False
tavern_equal: False
game_seed_1: None
game_seed_2: None
```

影响：

- 同 seed 不复现。
- vectorized env、多进程训练、trajectory 生成和 offline BC 数据无法稳定对照。
- 当前 `test_rng_reproducibility.py` 测的是手工 `Game([], seed=...)`，没有覆盖 `BattlegroundsEnv.reset(seed=...)`。

### P1-001 `init_cards()` 没有导入 spells 包

证据：

`hsrl/cards/__init__.py` 只导入：

- minions pool/scripts/tokens
- heroes pool/scripts
- trinkets scripts
- rewards scripts
- anomalies scripts

没有导入 `hsrl.cards.spells`。

新进程验证：

```text
CARDS.get("BG28_503") -> None
CARDS.get("EXAMPLE_TAVERN_SPELL_EFFECT") -> None
SPELL card count -> 42
```

影响：

- 训练环境初始化时 CardDB 不是完整 spell registry。
- `SpellPool` 与 `build_action_mask()` 的 spell 行为可能和审计工具统计不一致。
- Advisor/训练/测试在不同 import 顺序下看到不同 CardDB，属于高风险隐性状态污染。

### P1-002 start-choice 状态破坏 maskable env 契约

证据：

`BattlegroundsEnv.reset()` 在需要开局英雄技能选择时返回 zero observation 和 `choice_info`，但没有 `action_mask`。此时 `_game is None`。

smoke：

```text
start_choice: True
has_action_mask: False
game_is_none: True
action_masks_ok: False
AttributeError("'NoneType' object has no attribute 'tavern'")
```

经 `make_env()` 包装后，`ActionMaskWrapper` 因没有 `action_mask` 保持默认全 1：

```text
mask_sum: 50
first_10: [1,1,1,1,1,1,1,1,1,1]
```

影响：

- MaskablePPO/MaskableDQN 会看到 50 个动作全部合法。
- 对选择型英雄，训练初始状态的动作语义和普通 recruit action 混在一起。

### P1-003 `REARRANGE` mask 状态失效

证据：

`BattlegroundsEnv` 维护 `_can_rearrange`，但：

- `_build_info()` 调用 `build_action_mask()` 时没有传 `can_rearrange`。
- `action_masks()` 也没有传 `can_rearrange`。

smoke：

```text
can_rearrange_state: False
info_rearrange: True
api_rearrange: True
direct_false_rearrange: False
```

影响：

- 训练算法会采样环境状态认为非法的 `REARRANGE`。
- `ActionMaskWrapper` 和 `info["action_mask"]` 与环境内部状态不一致。

### P1-004 满场时 spell 被错误 mask 掉

证据：

`hsrl/env/action.py:96-103`：

```python
if i < len(player.hand) and board_count < 7:
    card = player.hand[i]
    if ct in (CardType.MINION, CardType.SPELL):
        mask[PLAY_OFFSET + i] = True
```

这把 spell 和 minion 共用 `board_count < 7` 限制。Advisor 端 `build_action_mask_from_state()` 已经把 spell 特判为不需要 board space。

smoke：

```text
board_count: 7
hand_cardtype: SPELL
play_spell_action_valid: False
```

影响：

- 满场无法施放 tavern spell / Blood Gem / target spell。
- 策略会错误学习“满场不能用法术”，影响后期局势和 trinket/spellcraft 体系。

### P1-005 默认随机对手可导致 reset 崩溃

证据：

```bash
BattlegroundsEnv(hero_id="BG20_HERO_100").reset(seed=0)
```

失败栈：

- `Game.start_game()` 调 `p.data.scripts.on_summon(p, self)`
- `FirstRefreshFreeScript.on_summon()` 使用 `source.controller.set_tag(...)`
- 但 `source` 是 `Player`，`Player.controller is None`

影响：

- 随机 hero pool 中抽到对应脚本时，RL env reset 直接失败。
- SubprocVecEnv 中这会表现为 worker crash，训练难定位。

---

## 3. 表征与策略质量问题

### 3.1 Observation 过粗

当前 observation 主要编码：

- stats
- tier
- cost
- race
- 少量 keyword
- 少量 hook flags

缺口：

- tavern 和 board 没有稳定 card id。
- deathrattle、battlecry、avenge、spellcraft、rally、trinket 精确效果不可见。
- hero id / hero power id 没有稳定编码。
- opponent 信息默认不进入单智能体 observation。

这不是立即崩溃问题，但会限制策略上限。对于高保真 RL，模型必须能区分“同身材但完全不同语义”的卡。

### 3.2 Python `hash()` 不适合特征编码

使用位置：

- `hsrl/env/observation.py:87`
- `hsrl/env/observation.py:190`
- `hsrl/env/observation.py:250`
- `hsrl/advisor/state_mapper.py:119`
- `hsrl/advisor/state_mapper.py:224`

验证：

```bash
python -c "print((hash('BG20_100') % 1000) / 1000.0)"
# 0.718
python -c "print((hash('BG20_100') % 1000) / 1000.0)"
# 0.486
```

影响：

- 多进程训练中不同 worker 的同一 card id 特征可能不同。
- 训练和 Advisor 推理进程特征不一致。
- checkpoint 无法稳定解释。

---

## 4. Trajectory / BC 数据问题

### 4.1 Trajectory 生成没有 seed 到 Game

`hsrl/trajectory/generate.py:34-45` 手工创建 `Game([])`，没有传 seed。虽然外层 `random.seed(seed)` 用于选 hero，但 game 内部池抽取、combat shuffle、spell pool 等走 `game.rng`，仍不可复现。

### 4.2 BC collector 也没有 seed 到 Game

`hsrl/train/bc_collector.py:168-174` 和 `bc_collector_v2.py:161-165` 都是：

```python
random.seed(seed)
np.random.seed(seed)
chosen = random_heroes(...)
game = Game.create_game(...)
```

而 `Game.create_game()` 不接收 seed。

影响：

- offline BC 数据不可复现。
- 失败样本和训练轨迹无法按 seed 重建。

### 4.3 Trajectory opponent 注入是“冻结 board”，不是完整 opponent policy

`TrajectoryOpponent.apply_to_player()` 只重建 board/health/tier，清空 hand/graveyard，gold 置 0。它适合做 frozen combat opponent，不等价于完整对局行为。

这不是 bug，但训练文档应明确：trajectory opponent 是“历史战斗面板注入”，不是“对手策略模拟”。

---

## 5. 是否需要重构

需要，但范围应控制。

不需要重写：

- `core/game.py` 游戏引擎。
- card registry。
- 大部分 action/reward 计算。
- Advisor transport。

需要重构：

1. `BattlegroundsEnv` 的状态机和 Gymnasium/maskable 契约。
2. action space 的选择/目标/站位/磁力/发现统一模型。
3. CardDB 初始化入口。
4. seed 传播链路。
5. observation 的稳定 card/entity 编码。
6. `MultiAgentBattlegroundsEnv` 与 `SelfPlayTrainer` 的接口。

建议定义一个清晰边界：

- `core/` 是规则引擎。
- `env/` 只负责把引擎状态转换为 MDP/POMDP。
- 所有“等待选择”的状态都必须是显式 RL mode，且必须提供合法 action mask。
- 所有随机源必须从 env seed 进入 `Game(seed=...)`。

---

## 6. 重构路线

### Phase 1：阻断修复，不改策略结构

目标：训练入口能稳定 reset/step，不崩溃。

1. `init_cards()` 导入 `hsrl.cards.spells`。
2. `Game.create_game(..., seed=None)` 并传入 `Game([], seed=seed)`。
3. `BattlegroundsEnv.reset()` 把 seed 传给 `Game.create_game()`。
4. 修复 `FirstRefreshFreeScript.on_summon()` 这类 hero passive 的 source 约定。
5. `action_masks()` 和 `_build_info()` 传 `can_rearrange=self._can_rearrange`。
6. `build_action_mask()` 满场时允许 spell，禁止 minion。
7. start-choice reset 返回合法 `action_mask`，`action_masks()` 支持 `_awaiting_start_choice`。

必须新增测试：

```bash
python -m pytest hsrl/tests/test_env_contract.py -q
```

覆盖：

- same seed reset same observation/tavern。
- start-choice mask only exposes option actions。
- action_masks() before game creation does not crash。
- full-board spell play is valid。
- rearrange mask follows `_can_rearrange`。
- default `BattlegroundsEnv(...).reset(seed=0)` 不崩溃。

### Phase 2：动作空间重构

目标：从 Discrete(50) 的“粗动作”扩展到可表达 BG 决策。

建议保守方案：

- 保留 Discrete 编码，扩容到固定上限。
- 拆出 `ActionMode`：
  - `NORMAL`
  - `TARGET_SELECT`
  - `TRINKET_SELECT`
  - `START_CHOICE`
  - `DISCOVER_SELECT`
  - `POSITION_SELECT`
  - `MAGNETIC_TARGET_SELECT`
- 每个 mode 都由同一个 `action_masks()` 返回合法动作。

不建议继续把 0-6 同时复用为 tavern slot、target index、trinket index、hero choice，但如果短期保留复用，必须在 observation/info 中显式编码 mode。

### Phase 3：Observation schema 重构

目标：训练/Advisor/BC 数据使用同一份稳定 schema。

建议：

1. 建立 `CardIdEncoder`：
   - 固定 vocabulary 文件。
   - 输出 integer id 或 embedding index。
   - 禁止 Python `hash()`。
2. tavern/hand/board/trinket 都加入 stable card id。
3. hero/anomaly/quest/trinket/id 都使用同一编码。
4. 把 `StateMapper` 和 `env.observation` 的维度常量统一来源，避免手动镜像。

### Phase 4：Self-play 接口重构

目标：让自博弈真实可运行。

1. `MultiAgentBattlegroundsEnv.__init__()` 明确支持 `dense_scale`、`preferences`，或从 `SelfPlayTrainer` 移除这些参数。
2. 多智能体 env 支持 target/trinket/discover/start-choice mode。
3. model-pool opponent 接入 action loop，而不是只加载不用。
4. 每个 RL agent 独立 reward tracker、mask、mode、pending target。

### Phase 5：数据管线重构

目标：BC/trajectory/replay 可复现。

1. `Game.create_game(seed=...)` 统一入口。
2. trajectory generator、BC collector、RL env 都使用同一 seed contract。
3. 失败游戏不要静默丢弃，只记录 failure metadata。
4. 保存 schema version、card vocabulary version、patch version。

---

## 7. 最终判断

当前 RL 环境不建议直接开始大规模训练。原因不是模型结构，而是 MDP 接口本身存在可复现性、合法动作、选择状态、CardDB 初始化和 self-play wiring 的硬问题。

建议立即进行“中等规模重构”：

- 不动核心规则引擎。
- 先修 Env contract 和 seed/card registry。
- 再重构 action mode 和 observation schema。
- 最后修 self-play/model-pool。

完成 Phase 1 后可以恢复单智能体 smoke training；完成 Phase 2-3 后再开始正式 RL 训练；完成 Phase 4 后再做自博弈。
