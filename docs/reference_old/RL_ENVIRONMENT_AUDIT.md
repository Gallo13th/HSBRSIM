# HrSRL RL 环境审计报告

> **审计日期**: 2026-06-03
> **目标**: 为 RL 环境重写做准备，系统分析当前实现中可复用、需删除、需重设计的部分。
> **基线版本**: Patch 35.6.0.243002

---

## 目录

1. [当前架构总览](#1-当前架构总览)
2. [可复用 — 接口与协议层](#2-可复用--接口与协议层)
3. [可删除 — 手写编码层](#3-可删除--手写编码层)
4. [需重设计 — 训练系统](#4-需重设计--训练系统)
5. [依赖关系图](#5-依赖关系图)
6. [重写优先级与路线图](#6-重写优先级与路线图)

---

## 1. 当前架构总览

### 1.1 文件清单

```
hsrl/env/
├── action.py              # 动作空间 — Discrete(50) + mask + decode
├── observation.py         # 观察空间 — 手写 374-dim 编码
├── observation_spec.py    # 维度常量 — GLOBAL_DIM, FLAT_DIM...
├── card_encoder.py        # CardID 编码器 — 确定性 hash → [0,1)
├── reward.py              # 奖励函数 — per-action + combat + terminal
├── battlegrounds_env.py   # 单 Agent Gym Env
└── multi_agent_env.py     # 多 Agent 自对弈 Env

hsrl/train/
├── network.py             # Dual-Head MLP 网络
├── wrappers.py            # FlattenDictObsWrapper + ActionMaskWrapper
├── ppo_trainer_v2.py      # PPO 微调训练器
├── self_play_trainer.py   # 自对弈 PPO 训练器
├── self_play_config.py    # 课程配置
├── bc_collector_v3.py     # BC 数据收集
├── bc_trainer_v3.py       # BC 策略训练
├── board_eval.py          # BoardEval 战斗预测网络
├── game_value.py          # GameValue v2 (61-dim POMDP)
├── game_value_sp.py       # GameValue v4 (397-dim POMDP)
├── value_dense.py         # DenseValue 网络
├── value_network.py       # Value 网络抽象
├── combat_data.py         # 战斗数据编码
├── model_pool.py          # 模型池管理
├── opponent_selector.py   # 对手选择器
└── train_v3.py            # 恢复训练脚本

hsrl/agents/
├── agent_utils.py         # 共享工具: save/restore, 模拟, 价值网络加载
├── search_agent.py        # 混合 SearchAgent (启发式 + GameValue fallback)
├── az_agent.py            # AlphaZero MCTS Agent
├── heuristic_demo.py      # 全启发式 8 人对战 demo
├── self_play_demo.py      # 8 混合 agent 自对弈 demo
└── agent_vs_heuristic_demo.py  # 1 agent vs 7 启发式审计 demo
```

### 1.2 当前数据流

```
Game (game.py)
  │
  ├─→ Observation (observation.py)
  │     │ encode_global(20) + encode_player(15)
  │     │ + encode_tavern(7×13) + encode_hand(10×12)
  │     │ + encode_board(7×16) + encode_trinkets(2×8)
  │     └─→ 374-dim flat vector
  │
  ├─→ Action (action.py)
  │     │ Discrete(50)
  │     │ build_action_mask() → bool[50]
  │     │ decode_action() → game.buy/sell/play/refresh...
  │     └─→ engine API calls
  │
  └─→ Reward (reward.py)
        │ RewardTracker: snapshot HP → combat delta
        │ PLACEMENT_REWARDS: {1:20, 2:10, ... 8:-20}
        └─→ scalar reward
```

---

## 2. 可复用 — 接口与协议层

这些组件定义了 Agent 与 Game 引擎之间的**契约**，是稳定的抽象边界，应当保留或仅做微小调整。

### 2.1 Action Space (`env/action.py`)

**状态: KEEP** — 这是整个 RL 系统的核心接口。

| 组件 | 说明 |
|------|------|
| `ActionMode` (IntEnum) | 6 种动作模式: `NORMAL=0, START_CHOICE=1, TARGET_SELECT=2, TRINKET_SELECT=3, DISCOVER_SELECT=4, POSITION_SELECT=5` |
| 动作布局 (30 active + 20 reserved) | `BUY 0-6, SELL 7-13, PLAY 14-23, REFRESH 24, UPGRADE 25, FREEZE 26, HERO_POWER 27, END_TURN 28, GET_BUDDY 29, REARRANGE 30, SECOND_HERO_POWER 31` |
| `detect_action_mode(game, player, ...)` | 优先级链: `START_CHOICE > DISCOVER > TARGET > TRINKET > NORMAL` |
| `build_action_mask(game, player, ...)` | 基于金币、手牌空间、英雄技能 CD 等动态生成合法动作掩码 |
| `decode_action(action_id, game, player)` | 将整数动作翻译为 Game 引擎 API 调用 |
| `_do_*` 辅助函数 | `_do_buy, _do_sell, _do_play, _do_refresh, _do_upgrade, _do_freeze, _do_hero_power, _do_secondary_hero_power, _do_rearrange` |

**重写时的注意事项**:
- 动作空间布局 (`BUY_OFFSET=0` 等) 已与引擎 API 耦合，不应随意更改
- `build_action_mask` 的逻辑必须覆盖所有引擎限制 (金币、手牌上限 10、棋盘上限 7)
- 新增引擎能力时 (如 Secondary Hero Power)，需在 mask 和 decode 中同步添加

### 2.2 Reward System (`env/reward.py`)

**状态: KEEP** — 奖励函数签名和核心计算逻辑应保留。

| 组件 | 说明 |
|------|------|
| `PLACEMENT_REWARDS` | `{1:20, 2:10, 3:5, 4:2, 5:-2, 6:-5, 7:-10, 8:-20}` |
| `compute_dense_reward(player, turn, ...)` | 密集奖励: `(board_delta)×RECRUIT_SCALE + turn×SURVIVAL_SCALE + board×STRENGTH_SCALE + combat_delta×COMBAT_SCALE` |
| `compute_placement(player, all_players)` | 排名算法: 存活优先 → HP → 死亡回合 → 玩家序号 |
| `compute_board_score(player)` | 棋盘强度的快速 Q-score 估算 |
| `compute_board_strength(player)` | 总 ATK+Health 和 |
| `RewardTracker` 类 | 记录回合开始 HP → 战斗后计算 damage_dealt - damage_taken + knockout_bonus |
| `RECRUIT_SCALE = 0.05` | 每次招募动作的棋盘增量系数 |
| `COMBAT_DAMAGE_SCALE = 0.3` | 战斗伤害差系数 |
| `KNOCKOUT_BONUS = 2.0` | 淘汰对手的额外奖励 |

**重写时的注意事项**:
- 奖励函数签名应保持与 Game 引擎解耦 (通过 Player 对象和观察值计算)
- 新的价值网络可能需要不同粒度的奖励信号 (per-action vs per-turn)
- `RewardTracker` 的接口 (`snapshot_turn_start()`, `compute_combat_reward()`, `compute_terminal_reward()`) 设计良好，可复用

### 2.3 Multi-Agent Environment Shell

**状态: KEEP skeleton** — 多 Agent 回合管理逻辑应保留。

| 组件 | 文件 | 说明 |
|------|------|------|
| `MultiAgentBattlegroundsEnv` | `multi_agent_env.py` | 管理 8 人游戏的回合流转 |
| `StepResult` dataclass | `multi_agent_env.py` | `(observation, reward, terminated, truncated, info, turn_ended)` |
| `reset(seed)` → `dict[int, dict]` | `multi_agent_env.py` | 创建新游戏, 自动播放非 RL 对手, 返回初始观察 |
| `step(idx, action)` → `StepResult` | `multi_agent_env.py` | RL agent 执行动作, 计算奖励, 检测结束 |
| `active_rl_agents` property | `multi_agent_env.py` | 返回尚未结束回合的存活 RL agent |
| `set_opponent_policy(fn)` | `multi_agent_env.py` | 模型池对手回调: `fn(idx, obs, mask) → action` |
| `_resolve_turn_end()` | `multi_agent_env.py` | 所有 RL agent 结束 → 自动播放剩余对手 → 战斗 → 新回合 |

**回合生命周期**:
```
1. _start_recruit_phase() — 金币/刷新/回合开始效果
2. 自动播放启发式对手 (非 RL 玩家)
3. RL agent 通过 step() 依次行动
4. 所有存活 RL agent 发送 END_TURN
5. _resolve_turn_end()
   ├── 自动播放剩余对手
   ├── 注入轨迹棋盘 (如使用轨迹对手)
   └── end_recruit_phase() → 战斗 → 新回合
```

**重写时的注意事项**:
- 回合管理等状态机逻辑应保持不变
- 可以简化观察构建和奖励计算的连接点
- 考虑支持并行 agent 执行 (目前是顺序执行)

### 2.4 与 Game 引擎的映射关系

这是**不能改变**的契约关系:

| 动作 ID | 常量 | 引擎 API |
|---------|------|---------|
| 0-6 | `BUY_OFFSET` | `game.buy_minion(player, entity)` / `game.buy_spell(player, entity)` |
| 7-13 | `SELL_OFFSET` | `game.sell_minion(player, minion)` |
| 14-23 | `PLAY_OFFSET` | `game.play_minion(player, card)` / `game.play_spell(player, spell)` |
| 24 | `REFRESH` | `game.refresh_tavern(player)` + `SpendGold(player, 1)` |
| 25 | `UPGRADE` | `game.queue_action(UpgradeTavern(player))` |
| 26 | `FREEZE` | `minion.set_tag(FROZEN, not any_frozen)` |
| 27 | `HERO_POWER` | `game.use_hero_power(player)` |
| 28 | `END_TURN` | 触发回合结束逻辑 |
| 29 | `GET_BUDDY` | `game.get_buddy(player)` |
| 30 | `REARRANGE` | 启发式排序算法 (Taunt 优先, 高 ATK 优先) |
| 31 | `SECOND_HERO_POWER` | `UseSecondaryHeroPower(player)` |

---

## 3. 可删除 — 手写编码层

这些组件将游戏状态**手工编码**为固定维度向量。重写后应由模型**端到端学习**编码。

### 3.1 Observation Encoding (`env/observation.py` + `env/observation_spec.py`)

**状态: DELETE** — 全部替换为实体级编码。

**当前编码方式**:

| 组件 | Shape | 编码逻辑 |
|------|-------|---------|
| `_encode_global` | `(20,)` | `turn/20.0, phase==RECRUIT, alive/8.0, cap/15.0, anomaly_hash, rank/8.0` |
| `_encode_player` | `(15,)` | `hp/40.0, armor/20.0, gold/10.0, tier/7.0, upgrade_cost/10.0, hand/10.0, board/7.0, hp_cost/10.0, hp_used, extra_uses, triple_tier/7.0, free_refresh/5.0, spell_discount/10.0, bg_atk/50.0, bg_health/50.0` |
| `_encode_tavern_entity` | `(13,)` | `atk/100.0, health/100.0, tech_level/7.0, cost/10.0, race/12.0, is_minion, is_spell, taunt, ds, poison, reborn, frozen, card_id_hash` |
| `_encode_hand_entity` | `(12,)` | `atk/100.0, health/100.0, tech_level/7.0, cost/10.0, race/12.0, is_minion, is_spell, golden, battlecry, turns_in_hand/5.0, card_id_hash, spellcraft` |
| `_encode_board_minion` | `(16,)` | `atk/100.0, health/100.0, max_health/100.0, tech_level/7.0, race/12.0, taunt, ds, poison, venomous, reborn, windfury, cleave, golden, exhausted, ds_intact, card_id_hash` |
| `_encode_trinket` | `(8,)` | `present, cost/10.0, tech_level/7.0, has_soc, has_eot, has_sot, card_id_hash, 1 reserved` |

**问题**:
1. **硬编码归一化**: `health/40.0` 对后期身材爆炸 (100+) 不适用
2. **固定槽位**: 棋盘最多 7 个随从，但 Agent 需要理解站位、相邻关系
3. **card_id 丢失语义**: `encode_card_id` 将卡牌 ID 压缩为一个 `[0,1)` 浮点数，破坏了卡牌间的语义关系
4. **无上下文**: 不知道哪个随从是核心成长单位、哪个是 buff 工具人
5. **全局信息稀疏**: 20 维中只用了 6 维

**删除文件清单**:
- `hsrl/env/observation.py` — 全部 `_encode_*` 函数
- `hsrl/env/observation_spec.py` — 全部维度常量
- `hsrl/env/card_encoder.py` — `CardIdEncoder` 类

**重写方向**:

```
当前: Game → hand-crafted features → 374-dim vector → MLP
目标: Game → entity tokens (card_id + stats + position) → Transformer → hidden → heads
```

### 3.2 Simple MLP Network (`train/network.py`)

**状态: DELETE** — 将被 Transformer/Attention 架构替换。

当前网络:
```
obs(374) → Linear(256)+ReLU → Linear(128)+ReLU → Linear(64)+ReLU
                                                ├→ Linear(50) → Policy logits
                                                └→ Linear(1)  → Value
```

**问题**:
1. 374 个特征**平铺为 1D 向量**，丢失了实体间的结构关系
2. 不考虑实体类型 (board minion / hand card / tavern entity 语义不同)
3. 无法建模随从间的协同效应 (例如: 你的两个 Beast 随从 + Goldrinn 亡语)
4. 没有位置编码 (站位对战斗结果有决定性影响)

**删除文件清单**:
- `hsrl/train/network.py` — `BattlegroundsNetwork` 类

### 3.3 Gymnasium Observation Wrappers (`train/wrappers.py`)

**状态: DELETE** — 不再需要。

| 组件 | 说明 |
|------|------|
| `FlattenDictObsWrapper` | 将 `gym.Dict` 观察展平为 `Box(374,)` — 因为手写编码已替换 |
| `ActionMaskWrapper` | 缓存 action_mask — **保留思路**但需重新实现以适应新 Env |

**删除文件清单**:
- `hsrl/train/wrappers.py` — 全部内容 (需重写)

### 3.4 价值网络 (多个版本)

**状态: DELETE** — 统一为一个多任务网络。

| 文件 | 说明 | 删除原因 |
|------|------|---------|
| `train/game_value.py` | GameValue v2 (61-dim POMDP) | 手写 POMDP 编码, 过时的教师信号 |
| `train/game_value_sp.py` | GameValue v4 (397-dim POMDP) | 手写 POMDP 编码, 过时 |
| `train/value_dense.py` | DenseValue (397-dim) | 手写编码, 过时 |
| `train/board_eval.py` | BoardEval (战斗预测 98.4%) | Board 嵌入应集成到主网络中 |
| `train/combat_data.py` | 战斗对数据编码 | 应在主数据管道中统一处理 |

---

## 4. 需重设计 — 训练系统

### 4.1 观察编码 (P0 — 最高优先级)

**目标**: 从手写 374-dim 向量 → 实体级 Transformer 编码。

```
当前 (手写特征):
  obs[0] = min(turn / 20.0, 1.0)
  obs[4] = encode_card_id(anomaly_id)  # hash → 0.0-1.0
  obs[20+...] = min(entity.atk / 100.0, 1.0)

目标 (实体级 Token):
  global_tokens:  [turn_emb, phase_emb, anomaly_emb, ...]
  entity_tokens:  [
    {type: board, card_id: BG26_801, atk: 5, health: 8, pos: 2, keywords: [taunt, reborn], ...},
    {type: hand, card_id: BG25_010, cost: 3, race: undead, ...},
    {type: tavern, card_id: BG19_010, frozen: false, ...},
    ...
  ]
  → card_id embedding (learned 32-dim)
  → numerical features (learned projection)
  → concat → entity token
  → cross-attention transformer layers
  → pooled → policy_head + value_head
```

**设计考虑**:
- 卡牌 embedding 表: `(vocab_size ≈ 5200, embed_dim)` — 共享给所有实体
- Token 序列长度可变 (手牌 0-10, 棋盘 0-7, 酒馆 0-7, 饰品 0-2)
- 使用 padding mask 处理变长序列
- 考虑预训练卡牌 embedding (从卡牌文本或游戏对局数据)

### 4.2 动作空间 (P1)

**当前**: `Discrete(50)` — 固定槽位映射

**保持 Discrete(50) 的理由**:
- 与引擎 API 的**直接映射** (buy_tavern[0] → 购买第一个酒馆位置)
- 简单、可调试
- 动作掩码机制 (`build_action_mask`) 已经成熟
- RL 社区对 Discrete action spaces 有成熟的算法支持

**可选改进**:
- **Hierarchical**: 高级动作 (BUY/SELL/PLAY/REFRESH) → 槽位选择。对于 autoregressive 模型可能更优。
- **Autoregressive**: 每步产生一个动作序列，直到 END_TURN。适合 Transformer 解码器。

**推荐**: 先保持 `Discrete(50)` 以降低风险，后续再探索 autoregressive。

### 4.3 网络架构 (P1)

**推荐方向**:

```
方案 A (保守): Entity Encoder + MLP
  entity_tokens → Shared Encoder (2-layer Transformer) → pooled → MLP(256,128) → Policy+Value
  优点: 增量改进, 风险低

方案 B (进取): Full Transformer
  entity_tokens → Transformer(4-8 layers, 4-8 heads) → CLS token → Policy+Value
  优点: 最灵活, 适合未来扩展到多任务

方案 C (激进): Autoregressive Decoder
  entity_tokens → Encoder → Decoder → autoregressive action sequence
  优点: 自然建模多步决策, 适合复杂回合
```

**卡牌 Embedding 表设计**:

```python
# 共享嵌入表
card_embed = nn.Embedding(num_cards=5200, embedding_dim=64)
# 数值特征投影
stat_proj = nn.Linear(num_stats, 32)  # atk, health, cost, tier, race, keywords...
# 实体 token
entity_token = torch.cat([card_embed(card_id), stat_proj(stats)], dim=-1)  # 96-dim
```

### 4.4 训练 Pipeline (P2)

**当前流程** (过于复杂):
```
1. combat_data.py     → 收集战斗对数据
2. board_eval.py      → 训练 BoardEval 网络
3. game_value.py      → 训练 GameValue 网络 (使用 BoardEval 教师)
4. bc_collector_v3.py → 用 SearchAgent 收集 BC 数据
5. bc_trainer_v3.py   → BC 训练策略
6. ppo_trainer_v2.py  → PPO 微调
或
7. self_play_trainer.py → 自对弈 PPO 训练
```

**目标流程** (简化):
```
1. 离线数据收集: 轨迹对手 → 多 Agent 环境 → 自对弈数据
2. 在线训练: PPO (clip range, GAE) + 多 Agent 环境
3. 单一训练脚本: 支持从头训练和恢复训练
```

**删除文件清单**:
- `train/board_eval.py` — 合并到主网络
- `train/game_value.py` — 合并到主网络
- `train/game_value_sp.py` — 合并到主网络
- `train/value_dense.py` — 合并到主网络
- `train/bc_collector_v3.py` — 替换为在线自对弈数据收集
- `train/bc_trainer_v3.py` — 替换为在线 PPO
- `train/ppo_trainer_v2.py` — 重写
- `train/self_play_trainer.py` — 重写
- `train/combat_data.py` — 合并到数据管道
- `train/train_v3.py` — 重写

### 4.5 Agent 系统 (P3)

| 当前 Component | 状态 | 说明 |
|---------------|------|------|
| `search_agent.py` | **DELETE** | 手动 Q-score + 启发式优先级 → 替换为 learned policy |
| `az_agent.py` | **KEEP (参考)** | AlphaZero MCTS 框架可参考, 但 value network 需更新 |
| `agent_utils.py` | **PARTIAL KEEP** | `save_player_state/restore_player_state` 对 MCTS 有用; `simulate_action` 需更新 |

### 4.6 保留文件汇总

| 文件 | 状态 | 说明 |
|------|------|------|
| `env/action.py` | **KEEP** | Action space 契约 |
| `env/reward.py` | **KEEP** | 奖励计算 |
| `env/multi_agent_env.py` | **KEEP** | 多 Agent 环境骨架 |
| `hsrl/core/game.py` | **KEEP** | 游戏引擎 (不修改) |
| `hsrl/core/actions.py` | **KEEP** | Action 系统 (不修改) |
| `agents/agent_utils.py` | **PARTIAL KEEP** | save/restore 功能 |
| `agents/az_agent.py` | **KEEP (参考)** | MCTS 框架 |
| `train/model_pool.py` | **KEEP** | 模型池对手管理 |
| `train/opponent_selector.py` | **KEEP** | 对手课程选择 |

---

## 5. 依赖关系图

```
                      ┌──────────────────────┐
                      │   Game Engine (KEEP)  │
                      │   game.py, actions.py │
                      └──────────┬───────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
    ┌─────────────┐    ┌─────────────┐    ┌──────────────┐
    │ Action (KEEP)│    │Obs (DELETE) │    │Reward (KEEP) │
    │ Discrete(50) │    │ 374-dim     │    │ compute_*    │
    │ mask+decode  │    │ hand-coded  │    │ RewardTracker│
    └──────┬───────┘    └──────┬──────┘    └──────┬───────┘
           │                  │                   │
           └──────────────────┼───────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │ MultiAgentEnv     │
                    │ (KEEP skeleton)   │
                    │ step/reset/mask   │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │ Network     │  │ Wrappers    │  │ Trainers    │
    │ (DELETE)    │  │ (DELETE)    │  │ (DELETE)    │
    │ MLP(374→50) │  │ FlattenDict │  │ BC+PPO+SP   │
    └─────────────┘  └─────────────┘  └─────────────┘
```

**不变层** (不应修改):
- `Game` 引擎 API (`game.buy_minion`, `game.sell_minion`, ...)
- Action 空间枚举和映射 (`BUY_OFFSET=0`, `decode_action`)
- 奖励函数签名 (`compute_dense_reward`, `RewardTracker`)

**可变层** (重写目标):
- Observation 编码 (手写 → 学习)
- 网络架构 (MLP → Transformer)
- 训练流程 (BC+PPO → 统一 PPO)
- Agent 策略 (启发式 → learned)

---

## 6. 重写优先级与路线图

### Phase 1: 新 Observation 编码器 (P0)

| 任务 | 说明 |
|------|------|
| 设计实体级 token 表示 | card_id embedding + numerical projection |
| 实现 `EntityEncoder` | 替代 `_encode_*` 函数 |
| 编写编码器测试 | 确保覆盖所有实体类型 (board/hand/tavern/trinket) |
| 删除旧文件 | `observation.py`, `observation_spec.py`, `card_encoder.py` |

### Phase 2: 新网络架构 (P1)

| 任务 | 说明 |
|------|------|
| 实现 Transformer encoder | 2-4 layer, multi-head attention |
| 实现 Policy/Value heads | 基于共享编码 |
| 删除 `network.py` | 旧 MLP 网络 |
| 编写网络测试 | 前向传播形状验证 |

### Phase 3: 统一训练脚本 (P2)

| 任务 | 说明 |
|------|------|
| 重写 `ppo_trainer.py` | 使用新网络 + 新观察 |
| 删除旧 trainers | `bc_*`, `game_value*`, `value_dense*`, `board_eval*`, `combat_data*` |
| 实现 model save/load | 支持 checkpoint 恢复 |
| 编写端到端训练测试 | 小规模训练 → 验证 loss 下降 |

### Phase 4: 新 Agent (P3)

| 任务 | 说明 |
|------|------|
| 实现 learned policy agent | 替代 SearchAgent |
| 实现 MCTS agent (可选) | 基于新价值网络 |
| 删除 `search_agent.py` | 手动启发式 agent |

### Phase 5: 性能优化 (P4)

| 任务 | 说明 |
|------|------|
| 并行自对弈数据收集 | 加速训练 |
| 分布式训练支持 | 多 GPU |

---

## 附录: 关键接口契约 (不可变)

### A.1 Action → Engine 映射

```
BUY_OFFSET(0-6):   game.buy_minion/minion(player, tavern[i])
SELL_OFFSET(7-13):  game.sell_minion(player, board[i])
PLAY_OFFSET(14-23): game.play_minion/minion(player, hand[i])
REFRESH(24):        game.refresh_tavern(player); SpendGold(1)
UPGRADE(25):        game.queue_action(UpgradeTavern(player))
FREEZE(26):         toggle FROZEN tag on tavern minions
HERO_POWER(27):     game.use_hero_power(player)
END_TURN(28):       end recruit phase → combat
GET_BUDDY(29):      game.get_buddy(player)
REARRANGE(30):      reorder board minions
SECOND_HERO_POWER(31): UseSecondaryHeroPower(player)
```

### A.2 StepResult 契约

```python
@dataclass
class StepResult:
    observation: dict       # 新: entity tokens → 旧: gym Dict
    reward: float           # scalar
    terminated: bool        # agent eliminated
    truncated: bool         # max_turns reached
    info: dict              # {action_mask, turn, gold, health, ...}
    turn_ended: bool        # True iff action == END_TURN
```

### A.3 Reward 签名

```python
# Per-step recruit delta
(board_score_after - board_score_before) * RECRUIT_SCALE  # 0.05

# Per-turn combat
(damage_dealt - damage_taken) * COMBAT_DAMAGE_SCALE       # 0.3
+ knockout_bonus                                           # 2.0

# Terminal
PLACEMENT_REWARDS[rank]  # 20, 10, 5, 2, -2, -5, -10, -20
```
