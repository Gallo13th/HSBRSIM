# HSBRSIM — AutoTavern 引擎上的酒馆战棋 AlphaZero

把《炉石传说·酒馆战棋》做成可训练、可评估、可复现的 AlphaZero 智能体。

**唯一模拟器**：`rust/` 的 `hsbg_engine`（[MCG-NJU/AutoTavern](https://github.com/MCG-NJU/AutoTavern)
TavernGym 的 fork，MIT），数据基线 **37.0.0.255790**。
**唯一训练/搜索栈**：`hsbg/az` —— 不完全信息 MCTS（PIMC/ISMCTS + PUCT）→ 8 座自对弈 → PPO。
**唯一动作/观测契约**：245 动作 + 精确 mask；3227 floats + 124 cards（与 AutoTavern 逐位对齐）。

> 全仓库只保留 AutoTavern 引擎 + 不完全信息 MCTS + 自对弈 + PPO 这一条路径。

## 架构

```text
hsbg/
├── env/                # 标准 profile：action_space_std（245 + 扩展 29）= 274；obs_std（3227+124）
├── az/                 # 唯一搜索/自对弈/训练栈
│   ├── env_api.py      # 引擎鸭子接口：observe / legal_mask / step / state_json
│   ├── belief.py       # determinization / 信念采样（公开信息）
│   ├── puct.py         # PUCT 节点 / Dirichlet / visit 分布
│   ├── search.py       # PIMC（Rust mcts_search 或 Python 对照）
│   └── train/          # entity transformer、selfplay、PPO、评测、报告
├── eval/               # 纯函数评测指标
└── paths.py
rust/                   # hsbg_engine：AutoTavern TavernGym fork（Rust + PyO3，37.0.0.255790）
data/                   # 官方 37.0.0.255790 派生 + AutoTavern schema（data/p2）
benchmarks/tavernbench/ # vendored TavernBench（960/368）
```

## 安装

```bash
python -m pip install -e .
cd rust && python -m pip install -e . && cd ..    # 需要 Rust 1.98 + maturin
python -c "import hsbg_engine as E; print(E.game_version(), E.data_info())"
# 37.0.0.255790 {'cards': 3983, ...}
```

## 快速开始

```python
import hsbg_engine as E
g = E.Game(seed=1)
while not g.is_over():
    for p in range(g.num_players):
        if g.needs_action(p):
            g.step(p, g.bot_action(p))
print(list(g.placements()))
```

```bash
# 1) 门禁（Rust 测试 + Python 测试 + 8 局 smoke + TavernBench + AZ smoke）
python scripts/verify_all.py --fast

# 2) 搜索自对弈 + 监督训练 smoke（MCTS π -> entity/tiny 网络）
python scripts/az_selfplay_smoke.py --games 2 --epochs 2 --arch tiny --device cpu

# 3) PPO（MCTS 引导的自对弈轨迹 -> clipped PPO）
python scripts/train_az_ppo.py --games 2 --epochs 1 --arch tiny --device cpu
```

## 关键契约

- **引擎即权威**：规则/数值以 `hsbg_engine` + 官方 37.0.0.255790 数据为准；任何偏离登记 `rust/FORK.md`。
- **动作**：0..244 与 AutoTavern 逐位一致；245..273 是 HSBRSIM 扩展（Unfreeze / 备用技能槽 / 备用选择槽 / FreezeSlot）。
- **观测**：3227 floats + 124 cards，`layout()` 32 项与 AutoTavern 一致；卡牌下标跨数据版本不可复用。
- **搜索**：只保留不完全信息 MCTS（PIMC + PUCT）与自对弈；其他搜索实现不再存在。
- **训练**：MCTS 自对弈产生 `(obs, mask, π, action, rank)` → 策略/价值监督 + PPO 微调；评测固定 seed。
- **确定性**：同 seed + 同动作序列逐位一致；`state_json` 精确存档。

## 测试

```bash
python -m pytest tests -q
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine
python scripts/run_tavernbench.py --check
```

## 文档

- `docs/ARCHITECTURE.md` — 分层与数据流
- `docs/ENGINE.md` — `hsbg_engine` fork/数据/构建
- `docs/ACTION_OBS.md` — 动作/观测契约
- `docs/AZ_MCTS_SELFPLAY_DESIGN.md` / `docs/AZ_IMPERFECT_SEARCH_DESIGN.md` — MCTS/自对弈设计
- `docs/TRAINING.md` — MCTS + 自对弈 + PPO 快速指南
- `docs/TRAINING_DESIGN.md` — **完整训练系统设计**（搜索/叶评估/吞吐/剪枝/PPO）
- `docs/TRAINING_PLAN_V2.md` — **v2 计划**（entity 14.8M / 异步 actor-learner / 重搜做题 / 冷启动联赛）
- `docs/TRAINING_RUNTIME_HANDOFF.md` — **接手文档**（BC 数据来源 / 对手课程 / actor 架构 / 决策与评分示例）
- `docs/COMPUTE_PLAN_4GPU.md` — **4 GPU / 多 CPU / 6–12h 长训练计算计划**
- `docs/COMPUTE_BENCHMARK.md` — **18M/56+1、4 GPU、worker/sims 吞吐实测**
- `docs/AT_LAYOUT_CONTRACT.md` — **AT 3227/124/245 数据与动作契约**
- `docs/ACTOR_RUST_OPTIONS.md` — **Rust actor / GIL 分析与方案**
- `docs/VERIFICATION.md` — 门禁与预期
- `docs/TAVERNBENCH.md` — 决策基准
