# HrSRL Policy — 实体级 Transformer 强化学习系统

> **版本**: 1.0
> **目标参数量**: ~87.5K (0.1M 规模)
> **基线引擎**: HrSRL Game Engine (Patch 35.6.0.243002)
> **模块路径**: `hsrl/policy/`

---

## 目录

1. [架构总览](#1-架构总览)
2. [组件详解](#2-组件详解)
3. [数据流](#3-数据流)
4. [训练策略](#4-训练策略)
5. [API 参考](#5-api-参考)
6. [文件清单](#6-文件清单)
7. [已知问题与限制](#7-已知问题与限制)
8. [训练与评估命令](#8-训练与评估命令)
9. [验证记录](#9-验证记录)

---

## 1. 架构总览

### 1.1 设计原则

1. **Object-centric**: 游戏实体（随从、法术、英雄）作为独立 token，保留结构信息
2. **Learnable embeddings**: 卡牌 ID → 学习得到的向量，替代手写 hash 编码
3. **Attention-based**: Transformer 建模 entity 间的交叉注意力
4. **Hierarchical action**: 动作类型分类器 + 实体指针，适应动态变化的棋盘/手牌/酒馆
5. **Distributional value**: 预测 P(rank=1..8) 的完整分布，而非单一标量

### 1.2 模型架构图

```
Game Engine (hsrl/core/)
  │
  ├─→ Entity Obs Builder ──→ Tokenized Entities
  │     card_indices(24), stats(24×8), mask, types, positions, global(10)
  │
  ▼
EntityTokenizer (37,104 params)
  ├── card_embedding:     Embedding(1500, 24)
  ├── type_embedding:     Embedding(4, 24)
  ├── pos_embedding:      Embedding(8, 24)
  ├── entity_stats_mlp:   Linear(8→16→24)
  └── global_projection:  Linear(10→24)
  │
  ▼
EntityTransformer (39,216 params)
  ├── input_proj:         Linear(24→48)
  ├── TransformerLayer ×2: MHA(d=48,h=4,d_ff=96) + FF + LayerNorm
  └── final_norm:         LayerNorm(48)
  │
  ├──────────────────┬──────────────────┐
  ▼                  ▼                  ▼
entity_reps      global_rep      用于 value head
(B,N,48)         (B,48)
  │                  │
  ▼                  ▼
HierarchicalActionHead (2,768 params)   DistributionalValueHead (8,408 params)
  ├── type_head:  Linear(48→8)          ├── combiner: Linear(144→48)
  ├── ptr_query:  Linear(48→24)         ├── trunk:    Linear(48→24→8)
  ├── ptr_key:    Linear(48→24)         └── head:     Linear(8→8)
  └── slot_biases: tavern(7)+board(7)+hand(10)
  │                                     │
  ▼                                     ▼
type_logits(8) + ptr_scores(24)        P(rank=1..8) → value = -E[rank]
  │
  ▼
Discrete action (0-49)
 → game.buy_minion / game.sell_minion / game.play_minion / ...
```

### 1.3 参数量分解

| 组件 | 参数量 | 占比 |
|------|--------|------|
| Card Embedding (1500 × 24) | 36,000 | 41.1% |
| Entity type + Position embedding | 288 | 0.3% |
| Entity stats MLP + Global proj | 816 | 0.9% |
| Transformer input proj | 1,200 | 1.4% |
| Transformer Layer 1 (MHA + FF) | 18,768 | 21.5% |
| Transformer Layer 2 (MHA + FF) | 18,768 | 21.5% |
| Final LayerNorm | 96 | 0.1% |
| Action type head | 392 | 0.4% |
| Pointer head (query + key) | 1,176 | 1.3% |
| Slot biases (7+7+10) | 24 | 0.0% |
| Value combiner | 4,656 | 5.3% |
| Value trunk | 1,376 | 1.6% |
| Value placement head | 72 | 0.1% |
| **总计** | **87,496** | **100%** |

---

## 2. 组件详解

### 2.1 EntityTokenizer (`entity_tokenizer.py`)

**职责**: 将原始游戏状态转换为可学习的 token 序列。

**CardIndexer**: 确定性的 card_id → int 映射。
```python
indexer = get_card_indexer()
idx = indexer.encode("BG20_HERO_100")  # → 整数
```
- 词汇量: ~905 (当前) / 1500 (预留)
- Index 0 = UNKNOWN/PADDING

**EntityTokenizer (nn.Module)**:
```
输入: card_indices(B,24), entity_stats(B,24,8), entity_mask(B,24),
      entity_types(B,24), entity_positions(B,24), global_features(B,10)

每个 entity 的 token = card_embedding(card_idx)
                     + type_embedding(tavern/board/hand)
                     + pos_embedding(position) [仅 board entities]
                     + entity_stats_mlp([atk, health, tier, cost, race, is_minion, is_spell, is_golden])

Global token = global_projection([turn, phase, gold, tier, hp, armor, hand_size, board_size, alive, damage_cap])

输出: entity_tokens(B,24,24), entity_mask(B,24), global_token(B,1,24)
```

### 2.2 EntityTransformer (`transformer.py`)

**职责**: entity tokens 间的交叉自注意力。

```
输入: entity_tokens(B,N,24), entity_mask(B,N), global_token(B,1,24)

1. input_proj: 24 → 48
2. 序列: [global_token(B,1,48), entities(B,N,48)] = (B, 1+N, 48)
3. TransformerEncoderLayer ×2:
   - MHA: 4 heads × 12 dim/head, pre-norm
   - FF: Linear(48→96)→GELU→Linear(96→48)
   - Dropout(0.1)
4. final_norm

输出: entity_reps(B,N,48), global_rep(B,48)
```

### 2.3 HierarchicalActionHead (`heads.py`)

**职责**: 层级式动作选择——先选动作类型，再指向具体 entity。

```
动作类型 (8 种):
  TYPE_BUY=0, TYPE_SELL=1, TYPE_PLAY=2,
  TYPE_REFRESH=3, TYPE_UPGRADE=4, TYPE_FREEZE=5,
  TYPE_HERO_POWER=6, TYPE_END_TURN=7

Pointer 空间 (24 slots):
  tavern[0..6]  → ptr[0..6]    (7 slots)
  board[0..6]   → ptr[7..13]   (7 slots)
  hand[0..9]    → ptr[14..23]  (10 slots)
```

**动作采样流程**:
```python
1. type_logits = action_type_head(global_rep)    # (B, 8)
2. type_probs = softmax(type_logits * mask)
3. action_type = sample(type_probs)
4. If BUY/SELL/PLAY:
     query = pointer_query(global_rep)           # (B, 24)
     keys = pointer_key(entity_reps)             # (B, N, 24)
     scores = dot(query, keys) + slot_biases     # (B, N)
     group_scores = max_pool(scores, by group)   # (B, group_size)
     slot = sample(softmax(group_scores))
5. discrete_action = hierarchical_to_discrete(action_type, slot)
```

**双向映射** (50-way ↔ 层级):
```python
# Discrete → Hierarchical
_discrete_to_hierarchical(0)   → (TYPE_BUY, slot=0)
_discrete_to_hierarchical(24)  → (TYPE_REFRESH, slot=0)

# Hierarchical → Discrete
_hierarchical_to_discrete(TYPE_BUY, 3)    → 3
_hierarchical_to_discrete(TYPE_REFRESH, 0) → 24
```

### 2.4 DistributionalValueHead (`value_head.py`)

**职责**: 预测 P(rank=1..8) 分布，输出 GAE 用的标量 value。

```
输入: global_rep(B,48), entity_reps(B,N,48), entity_mask(B,N)

1. Pool entities: mean_pool(B,48) + max_pool(B,48)
2. combined = concat[global_rep, mean_pool, max_pool]  → (B, 144)
3. Linear(144→48) → ReLU
4. Linear(48→24) → ReLU
5. Linear(24→8)  → ReLU
6. Linear(8→8)   → placement_logits  → softmax → P(rank=k)

输出:
  expected_placement = Σ(k × P(k))  ∈ [1, 8]
  value = -expected_placement       (GAE: higher = better)
```

### 2.5 Observation Builder (`obs_builder.py`)

**职责**: Game engine → entity token 数据的桥接层。仅使用公开 Game API。

```
build_entity_observation(game, player) → dict:
  card_indices:     (24,) int64      # CardIndexer 编码
  entity_stats:     (24, 8) float32  # atk, health, tier, cost, race, ...
  entity_mask:      (24,) bool       # 哪些 slot 被占用
  entity_types:     (24,) int64      # 0=tavern, 1=board, 2=hand
  entity_positions: (24,) int64      # board 站位 (1-7)
  global_features:  (10,) float32    # turn, gold, tier, hp, ...
  slot_counts:      (3,) int32       # [n_tavern, n_board, n_hand]
```

**Entity 布局** (24 slots):
```
slots  0..6:  tavern (7)
slots  7..13: board   (7)
slots 14..23: hand    (10)
```

### 2.6 RolloutBuffer (`rollout_buffer.py`)

**职责**: PPO rollout 数据的存储、采样和 GAE 计算。

```python
buffer = RolloutBuffer(capacity=2048)

# 添加 transition
buffer.add(Transition(obs=entity_obs, action=a, reward=r, done=d,
                       log_prob=lp, value=v, type_mask=tm))

# GAE 计算
advantages, returns = buffer.compute_gae(gamma=0.99, gae_lambda=0.95)

# 采样 batch
batch = buffer.sample(batch_size=64)
# batch['_indices'] → 用于从 pre-computed GAE 中索引
# batch['obs_batch'] → EntityObsBatch
# batch['actions'], rewards, dones, old_log_probs, old_values, type_masks
```

### 2.7 SearchTeacher (`search_teacher.py`)

**职责**: 用 value head 做 lookahead search，生成改进的动作分布作为蒸馏目标。

```
generate_targets(game, player):
  ┌─ Greedy (depth=1): ─────────────────────┐
  │ for each legal action:                   │
  │   save_state → simulate → V(s') → restore│
  │ Boltzmann(V/τ) → target_probs            │
  └──────────────────────────────────────────┘

  ┌─ Beam (depth≥2): ───────────────────────┐
  │ for each legal action a₁:               │
  │   simulate → V(s₁')                      │
  │   for follow-up a₂:                      │
  │     simulate → V(s₂')                    │
  │   blend V(s₁') + max V(s₂')             │
  │ top beam_width paths → aggregate Q       │
  │ Boltzmann → target_probs                 │
  └──────────────────────────────────────────┘
```

**性能**: ~50 evals/s (CPU, greedy depth=1)

### 2.8 训练器

| 文件 | 类 | 训练方式 |
|------|-----|---------|
| `ppo_trainer.py` | `PPOTrainer` | PPO (clipped surrogate + GAE) |
| `distill_trainer.py` | `DistillTrainer` | KL(policy ‖ teacher) + value MSE |
| `training_config.py` | `PPOTrainConfig` | 超参数 + 三阶段课程 |

---

## 3. 数据流

### 3.1 前向推理 (单步)

```
1. game engine 产生状态
   └→ build_entity_observation(game, player)
       └→ {card_indices, entity_stats, mask, types, positions, global_features}

2. _obs_to_batch(entity_obs) → {B=1 的 tensor batch}

3. HrSRLPolicy.forward(batch)
   ├→ EntityTokenizer → entity_tokens + global_token
   ├→ EntityTransformer → entity_reps + global_rep
   └→ HierarchicalActionHead → type_logits(8) + ptr_scores(24)

4. HrSRLPolicy.sample_action(batch, type_mask)
   ├→ softmax(type_logits × mask) → sample type
   ├→ if BUY/SELL/PLAY: pointer → sample slot
   └→ hierarchical_to_discrete(type, slot) → action 0-49

5. decode_action(action, game, player) → engine API call
```

### 3.2 训练数据流

```
───────────────── PPO Training ─────────────────
MultiAgentBattlegroundsEnv (8 players)
  │ reset() → auto-play heuristics → RL agent acts
  │ for each RL decision:
  │   obs = build_entity_observation()
  │   action = policy.sample_action(obs, mask)
  │   result = env.step(idx, action) → (next_obs, reward, done)
  │   buffer.add(Transition(obs, action, reward, done, log_prob, value))
  │
  ▼
RolloutBuffer
  │ compute_gae(gamma, lambda) → advantages, returns
  │ sample(batch_size) → batch + _indices
  ▼
PPO Update
  │ forward(batch) → log_probs, values
  │ ratio = exp(log_probs - old_log_probs)
  │ L = -min(ratio×adv, clip(ratio)×adv) + MSE(value, return) - entropy
  │ optimizer.step()

───────────────── Distillation Training ─────────────────
SearchTeacher.generate_targets(state) → target_probs, target_value
  │ KL(policy ‖ teacher) + MSE(value, target)
  ▼
DistillTrainer._distill_step()
```

### 3.3 动作空间映射

```
Engine API ←→ Discrete(50) ←→ Hierarchical(8+24)

game.buy_minion(p, tavern[i])    ← 0-6   ← TYPE_BUY + ptr[0..6]
game.sell_minion(p, board[i])    ← 7-13  ← TYPE_SELL + ptr[7..13]
game.play_minion(p, hand[i])     ← 14-23 ← TYPE_PLAY + ptr[14..23]
game.refresh_tavern(p)           ← 24    ← TYPE_REFRESH
game.queue_action(UpgradeTavern) ← 25    ← TYPE_UPGRADE
toggle FROZEN tags               ← 26    ← TYPE_FREEZE
game.use_hero_power(p)           ← 27    ← TYPE_HERO_POWER
end recruit phase                ← 28    ← TYPE_END_TURN
game.get_buddy(p)                ← 29    ← (reserved)
rearrange board                  ← 30    ← (reserved)
UseSecondaryHeroPower(p)         ← 31    ← (reserved)
```

---

## 4. 训练策略

### 4.1 推荐训练流程

```
阶段 0 (当前):    纯随机策略自对弈 → placement-weighted 训练
                   信号嘈杂，仅验证管道功能 ✓

阶段 1 (推荐):    SearchTeacher(depth=1) → 蒸馏训练
                   每局 ~200 states × 13 evals = 2600 forward passes
                   约 500-1000 局给出有意义信号

阶段 2:           SearchTeacher(depth=2, beam=3) → 蒸馏训练
                   多步 lookahead 捕获跨回合联动

阶段 3:           PPO self-play + population training
                   多策略池防止坍缩
```

### 4.2 超参数 (PPOTrainConfig)

```python
# Network
d_model=48, n_heads=4, n_layers=2, d_ff=96

# PPO
lr=3e-4, gamma=0.99, gae_lambda=0.95
clip_epsilon=0.2, c1=0.5, c2=0.01
n_epochs=10, batch_size=64
games_per_iteration=32

# Curriculum
Phase 1: 1 RL + 7 heuristic, dense reward, 300 iters
Phase 2: 2-4 RL + mixed, dense, 150 iters
Phase 3: 4-7 RL + sparse, placement-only, 150 iters
```

### 4.3 在 ~0.1M 参数下不应使用的策略

| 策略 | 原因 |
|------|------|
| Dreamer-style world model | 需要独立 RSSM (≥5M params)，不可能压缩到 0.1M |
| MuZero dynamics model | representation+dynamics+prediction 三件套 > 3× policy |
| Pure model-free RL (无 search) | 信用分配差，样本效率极低 |
| 纯模仿学习 | 无足够高质量人类轨迹 |

---

## 5. API 参考

### 5.1 创建模型

```python
from hsrl.policy.policy_network import HrSRLPolicy
from hsrl.policy.value_head import DistributionalValueHead

policy = HrSRLPolicy()           # 79,088 params
value_head = DistributionalValueHead()  # 8,408 params
```

### 5.2 构建观察

```python
from hsrl.policy.obs_builder import build_entity_observation
from hsrl.policy.ppo_trainer import _obs_to_batch

obs = build_entity_observation(game, player)
batch = _obs_to_batch(obs, device='cpu')
```

### 5.3 前向推理

```python
type_logits, ptr_scores, global_rep, entity_reps = policy(batch)

# 采样动作
from hsrl.env.action import build_action_mask
from hsrl.policy.ppo_trainer import _mask_50_to_type

mask_50 = build_action_mask(game, player)
type_mask = _mask_50_to_type(mask_50)
action, log_prob = policy.sample_action(batch, type_mask.unsqueeze(0))
```

### 5.4 价值评估

```python
v_out = value_head(global_rep, entity_reps, batch['entity_mask'])
# v_out['value']            → scalar for GAE
# v_out['expected_placement'] → E[rank] 1-8
# v_out['placement_probs']    → P(rank=k) for k=1..8
```

### 5.5 Search Teacher

```python
from hsrl.policy.search_teacher import SearchTeacher

teacher = SearchTeacher(policy, value_head, search_depth=1, temperature=0.5)
targets = teacher.generate_targets(game, player)
# targets['target_probs']  → {action_id: probability, ...}
# targets['target_value']  → expected value
# targets['q_values']      → {action_id: Q(s,a), ...}
```

### 5.6 PPO 训练

```python
from hsrl.policy.ppo_trainer import PPOTrainer
from hsrl.policy.training_config import PPOTrainConfig

config = PPOTrainConfig(games_per_iteration=32, batch_size=64)
trainer = PPOTrainer(config, device='cpu')
trainer.train()  # 运行 600 iterations
```

### 5.7 蒸馏训练

```python
from hsrl.policy.distill_trainer import DistillTrainer

dt = DistillTrainer(policy, value_head, search_depth=1)
dt.train(total_iterations=300)
```

---

## 6. 文件清单

### `hsrl/policy/` 模块 (12 文件)

```
__init__.py              模块入口，导出 CardIndexer, EntityTokenizer, build_entity_observation
entity_tokenizer.py      CardIndexer + EntityTokenizer (37,104 params)
obs_builder.py           build_entity_observation() — Game → token 桥接
transformer.py           EntityTransformer (39,216 params) + TransformerEncoderLayer
heads.py                 HierarchicalActionHead (2,768 params) + pointer helpers
policy_network.py        HrSRLPolicy 顶层 + 动作空间双向映射
value_head.py            DistributionalValueHead (8,408 params)
training_config.py       PPOTrainConfig — 超参数 + 三阶段课程
rollout_buffer.py        RolloutBuffer — 数据存储 + GAE 计算
ppo_trainer.py           PPOTrainer — PPO 训练循环
search_teacher.py        SearchTeacher — lookahead search 教师
distill_trainer.py       DistillTrainer — KL 蒸馏训练
```

### 依赖的外部文件 (不修改)

```
hsrl/core/game.py            Game engine — snapshot/restore for search
hsrl/core/player.py          Player entity — gold/health/board/hand
hsrl/core/enums.py           GameTag, Race, CardType
hsrl/env/action.py           Action space Discrete(50) + mask + decode
hsrl/env/reward.py           RewardTracker, compute_placement, PLACEMENT_REWARDS
hsrl/env/multi_agent_env.py  MultiAgentBattlegroundsEnv — multi-agent training env
hsrl/agents/agent_utils.py   save/restore_player_state, simulate_action, populate_tavern
```

---

## 7. 已知问题与限制

### 7.1 性能

| 操作 | 耗时 (CPU) |
|------|-----------|
| 单步前向推理 | ~10ms |
| SearchTeacher depth=1 (13 actions) | ~250ms |
| 完整对局 (8 RL agents, ~200 steps) | ~3s |
| SearchTeacher 数据收集 (200 states) | ~4s |

### 7.2 训练信号质量

- **Placement-based 权重**: 在 <10 局规模下 = 噪声
- **Search Teacher**: 每状态 ~13 次前向推理，CPU 上较慢
- **建议**: GPU 上运行 SearchTeacher 数据收集

### 7.3 已修复的 Bug

| Bug | 症状 | 修复 |
|-----|------|------|
| Beetle `source.position` | AttributeError | 用 `board.index(source)` |
| ClunkerJunker 无限递归 | `play_minion → resolve_queue` 循环 | 直接 `queue_action(AttachMagnetic)` |
| CardData 参数名 | `card_id=` → `id=` | agent_utils.py 修复 |
| Gradient inplace 错误 | version > 0 | `.gather()` 替代索引循环 |
| obs_builder 越界 | idx=31 > 24 | 修正 padding 计算 |

---

## 8. 训练与评估命令

### 8.1 验证管道完整性

```bash
# 卡牌索引构建
python -c "
from hsrl.policy.entity_tokenizer import get_card_indexer
print(len(get_card_indexer()))  # → ~905
"

# 前向推理测试
python -c "
import torch
from hsrl.policy.policy_network import HrSRLPolicy
p = HrSRLPolicy()
feed = {k: torch.randint(0, 99, (2, 24)) if 'indices' in k or 'types' in k or 'positions' in k
        else torch.randn(2, 24, 8) if 'stats' in k
        else torch.ones(2, 24, dtype=torch.bool) if 'mask' in k
        else torch.randn(2, 10) for k in ['card_indices','entity_stats','entity_mask','entity_types','entity_positions','global_features']}
tl, ps, _, _ = p(feed)
print(tl.shape, ps.shape)  # → (2,8) (2,24)
"

# 完整管道测试
python -m pytest hsrl/tests/ -q  # → 736 passed
```

### 8.2 4v4 评估

```python
# 见 benchmark 脚本模式:
# 1. 收集训练数据 (2 games × 8 agents)
# 2. 50 epochs placement-weighted 训练
# 3. 4 games × 4v4 eval
```

### 8.3 正式训练 (需 GPU)

```bash
# SearchTeacher 蒸馏训练 (推荐)
python -m hsrl.policy.distill_trainer --games 100 --depth 2 --epochs 50

# PPO 自对弈训练
python -m hsrl.policy.ppo_trainer --games 32 --iterations 600
```

---

## 9. 验证记录

| 日期 | 验证项 | 结果 |
|------|--------|------|
| 2026-06-03 | CardIndexer 构建 (vocab=905) | ✓ |
| 2026-06-03 | EntityTokenizer forward (37K) | ✓ |
| 2026-06-03 | EntityTransformer forward (39K) | ✓ |
| 2026-06-03 | Action head 类型+指针 | ✓ |
| 2026-06-03 | Value head 分布 rank 预测 | ✓ |
| 2026-06-03 | 完整 forward pass (87.5K params) | ✓ |
| 2026-06-03 | 动作空间双向转换 (50↔层级) | ✓ |
| 2026-06-03 | PPO rollout 收集 | ✓ |
| 2026-06-03 | GAE 计算 | ✓ |
| 2026-06-03 | SearchTeacher 目标生成 | ✓ |
| 2026-06-03 | DistillTrainer 初始化 | ✓ |
| 2026-06-03 | Gradient (.gather() 修复) | ✓ |
| 2026-06-03 | 8-agent multi-agent env | ✓ |
| 2026-06-03 | Self-play data collection | ✓ |
| 2026-06-03 | Mini-batch training loop | ✓ |
| 2026-06-03 | 4v4 eval (8 agents × 4 games) | ✓ |
| 2026-06-03 | Bug: Beetle position | ✓ 已修复 |
| 2026-06-03 | Bug: ClunkerJunker recursion | ✓ 已修复 |
| 2026-06-03 | Bug: CardData parameter | ✓ 已修复 |
| 2026-06-03 | Bug: Gradient inplace | ✓ 已修复 |
| 2026-06-03 | Bug: obs_builder index | ✓ 已修复 |
| 2026-06-03 | 现有测试套件 | ✓ 736 passed |
