# 架构（AutoTavern-only）

```text
scripts/ (train/eval/verify)
        │
hsbg/az/                          ← 唯一搜索 / 自对弈 / 训练栈
├── env_api.py    引擎鸭子接口：observe(seat) / legal_mask(seat) / step / state_json
├── belief.py     determinization / 信念采样（只用公开信息）
├── puct.py       PUCT 选择 / Dirichlet 根噪声 / visit 分布
├── search.py     PIMC：每个隐藏世界一棵树，根 visit 跨世界聚合
├── policy.py     叶评估器（uniform / heuristic / bot prior / net / rollout）与基线 agent
└── train/        entity transformer / 数据 / selfplay / PPO / 评测 / 报告
        │
hsbg/env/                        ← 唯一动作/观测 profile
├── action_space_std.py           0..244 AutoTavern 逐位一致；245..273 扩展
└── obs_std.py                    3227 floats + 124 cards；layout() 32 项
        │
rust/ hsbg_engine                ← 唯一模拟器（AutoTavern TavernGym fork）
        │  observe / legal_mask / state_json（PyO3）
data/ + data/p2/                 ← 官方 37.0.0.255790 派生 + AutoTavern schema
benchmarks/tavernbench/          ← 静态决策基准（只读 vendored）
```

## 数据流：一次决策

```text
hsbg_engine Game
  │ observe(seat) -> features[3227] + cards[124]
  │ legal_mask(seat) -> mask[245]
  ▼
hsbg.az.search.search(game, seat, config)
  ├─ belief sampler：从公开观测采样 W 个隐藏世界
  ├─ 每个世界：PUCT（Rust mcts_search 或 Python 对照）
  ├─ 根 visit 跨世界聚合成 π[245]
  └─ 采样 / argmax + 根先验 tie-break -> action
  ▼
game.step(seat, action)
```

## 自对弈 / 训练

```text
8 座自对弈（MCTS 或网络策略）
  → (features, cards, mask, π, action, rank)
  → 策略 CE(π) + 名次价值 CE（AlphaZero 监督）
  → PPO（masked、clip、GAE、KL 早停；π 可作辅助目标）
  → checkpoint → 固定 seed 评测（mean rank / top4 / win / legal rate）
```

## 不变量

- 引擎规则不在 Python 层重写；搜索/训练只调用引擎公开 API。
- 决策输入只允许 `observe(seat)` 与 `legal_mask(seat)`，不允许 `view/state_json` 的隐藏字段进策略。
- 同 seed + 同动作序列 ⇒ 同轨迹。
- 每步候选 = `legal_mask` 允许的动作；非法概率必须为 0。
- 观测不含对手手牌/金币/酒馆；对手信息仅公开血量/等级/上次见到的战团。
- 全仓库只保留这一套引擎/搜索/训练栈；没有其他 fallback。
