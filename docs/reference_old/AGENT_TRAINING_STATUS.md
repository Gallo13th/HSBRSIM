# HrSRL Agent 训练状态总结

> 日期: 2026-06-04 | 基线引擎: Patch 35.6.0.243002

---

## 1. 当前模型架构

### 1.1 ScaledModel (~5.25M params)

```
build_observation_v2() → 37 entity slots → EntityTokenizerV2 → EntityTransformer → Heads
  ├─ EntityTokenizerV2: card embedding(1500×128) + entity MLP(8→128) + summary projectors
  ├─ EntityTransformer: d=256, h=4, layers=6, ff=1024 — MHA over 37 entity tokens
  ├─ HierarchicalActionHead: 8-way type classifier + 24-way pointer → Discrete(50)
  └─ DistributionalValueHead: P(rank=1..8) → E[rank] → V(s)
```

### 1.2 文件清单

| 文件 | 用途 |
|------|------|
| `hsrl/policy/model_5m.py` | ScaledModel + ScaledTokenizer (5.25M) |
| `hsrl/policy/entity_tokenizer_v2.py` | CardIndexer(1500) + EntityTokenizerV2 (37 slots) |
| `hsrl/policy/transformer.py` | EntityTransformer (d=256, h=4, 6 layers) |
| `hsrl/policy/heads.py` | HierarchicalActionHead |
| `hsrl/policy/value_head.py` | DistributionalValueHead |
| `hsrl/policy/bc_train.py` | Phase 0: BC from heuristic (单轮) |
| `hsrl/policy/iter_train.py` | Phase 1: 迭代 BC (多轮 self-improvement) |
| `hsrl/policy/gpu_train.py` | GPU 训练脚本 |
| `hsrl/policy/quick_train.py` | 快速训练脚本 |
| `hsrl/rl_env/observation/observation_v2.py` | build_observation_v2() — 37 entity slots |
| `hsrl/rl_env/observation/entity_schema.py` | TokenGroup 枚举 + 槽位偏移常量 |
| `hsrl/rl_env/reward/board_score.py` | compute_board_score_v2() |

---

## 2. 训练结果

### 2.1 BC 训练 (Phase 0)

| 教师 | 回合数 | BC avg raw | Random avg raw | Gap |
|------|--------|------------|----------------|-----|
| 弱启发式 (随机买) | 7 | 35-40 | 15-27 | +1.0~+1.8 |
| 强启发式 (SearchAgent) | 15 | 32-40 | 25-39 | +0.1~+0.8 |

强启发式在 15 回合下 gap 缩小，因为随机策略有更多时间填满场面。

### 2.2 迭代 BC (Phase 1)

15 回合 × 6 轮迭代结果:

| 轮 | BCsc | BCraw | BCcnt | BCt | Rsc | Gap |
|----|------|-------|-------|-----|-----|-----|
| 1 (HEUR) | 2.2 | 33 | 6.6 | 2.2 | 1.4 | +0.8 |
| 2 (BC) | 1.9 | 40 | 6.9 | 2.4 | 1.3 | +0.5 |
| 3 (BC) | 1.6 | 32 | 5.8 | 1.9 | 1.4 | +0.1 |
| 4 (BC) | 2.3 | 38 | 6.8 | 2.6 | 1.6 | +0.7 |
| 5 (BC) | 1.7 | 32 | 5.7 | 2.1 | 1.1 | +0.5 |
| 6 (BC) | 2.0 | 40 | 6.8 | 2.6 | 1.4 | +0.7 |

**最佳阵容 (R6)**: raw=50, tier=T3, 鱼人协同 (Papa Mrrglton, Pufferquil 等)

---

## 3. 已验证工作的组件

| 组件 | 状态 |
|------|------|
| ObservationV2 (37 entity slots) | ✓ |
| EntityTokenizerV2 (1500 card vocab) | ✓ |
| ScaledModel 5.25M (forward/backward) | ✓ |
| BC training on GPU (3.5K samples/s) | ✓ |
| 迭代 BC: HEUR→BC→BC multi-round | ✓ |
| BC 策略 > 随机基线 | ✓ (gap 0.5-1.8) |
| Value head: board_score prediction (MSE 15→2) | ✓ |
| 现有测试套件 (772 passed) | ✓ |

---

## 4. 核心瓶颈

### 4.1 Q-score 启发式天花板

强启发式只按 atk+health 选怪，无法发现:
- 铜须/瑞文等光环随从的间接价值
- 种族协同路线 (龙体系需多个组件)
- 战吼引擎 (需多回合积累)

BC 模型无法超越教师 — 教师没见过的好策略，模型也学不到。

### 4.2 15 回合下随机基线升高

15 回合给随机策略更多时间填满场面 (raw 25-39)，BC vs 随机 gap 缩窄到 <1.0。

---

## 5. 下一步方向

1. **PPO 微调**: BC 初始化 → PPO 探索 → 发现超越启发式的策略
2. **Pointer loss**: 加入 pointer 损失让模型学会选择"哪个"而不仅是"什么类型"
3. **真实轨迹数据**: 用 HDT 收集的真人数据作为 BC teacher
4. **Value-guided search distillation**: SearchAgent 深度搜索 → BC distill
