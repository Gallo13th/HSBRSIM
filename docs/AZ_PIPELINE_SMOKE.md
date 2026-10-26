# AZ-MCTS 训练管线 smoke 测试记录（100 局）

> 目的：在远程开发机验证**完整训练管线可运行**（数据→训练→checkpoint→评测），
> 不是强度/规模实验。设计见 [AZ_MCTS_SELFPLAY_DESIGN.md](AZ_MCTS_SELFPLAY_DESIGN.md)。

## 1. 组件

| 步骤 | 实现 |
|---|---|
| 自对弈数据 | `scripts/az_pipeline_smoke.py`：8 座全部用逐步 MCTS（`hsbg/search/engine_mcts.py`）决策；记录每座位 `(features, cards, mask, π, rank)` |
| 搜索 | Python 原型 PUCT（节点存 `Game.copy`、合法掩码、`EndTurn` 后 bot 推进、温度采样）；对手推进用引擎 bot（smoke 近似） |
| 网络 | `hsbg/policy/std_net.py`（torch）或 `hsbg/policy/numpy_net.py`（numpy 回退）：3227 features → 245 policy + 8 rank value |
| 训练 | policy CE(π) + value CE(rank)，2 epochs |
| 评测 | seat0 策略（search-off）vs 7 bot ×10 局，平均名次 |

## 2. 远程运行（`biocourse-glt` / oulab-cs9）

```bash
cd ~/projects/HSBRSIM
python3 scripts/az_pipeline_smoke.py --games 100 --sims 1 --epochs 2 \
    --eval-games 10 --out runs/az_smoke2 --backend numpy
```

## 3. 结果（2026-10-26）

| 指标 | 数值 |
|---|---:|
| 局数 | 100 |
| 决策/样本 | 50,754 |
| 数据采集 | 12.0 s |
| 训练（2 epochs） | 2.1 s |
| 端到端 | 18.5 s |
| 训练 loss | 7.278 → 6.021 |
| 评测（10 局随机策略） | mean rank 8.0（**仅验证流程；1 sim/随机初始化，强度无意义**） |
| 产物 | `runs/az_smoke2/{data.npz, model.npz, report.json}` |

## 4. 限制与说明

1. **后端**：远程 numpy 后端（torch 2.14.1 wheel 为 CUDA 构建，缺 `libcublasLt` 无法
   import；后续应在远程装 CPU-only torch 或补齐 CUDA 运行库）。pipeline 已支持
   `--backend torch`，环境就绪即用。
2. **搜索是 Python 原型**，性能未优化；设计目标是 Rust 搜索核（M1）。
3. 搜索内部对手用引擎 bot（不是 8 座模型）；外层 8 座均用搜索。M1 改 Rust 核后
   统一为模型/league 对手。
4. 随机初始化 + 1 sim 下策略会反复选 Freeze 等无进展动作，smoke 加了“同回合
   >8 个动作强制 EndTurn”的防退化；正式训练由搜索价值学习解决。
5. 网络只用 features（cards 未编码），hidden=128；不代表最终模型规模。
6. 数据/checkpoint 在 `runs/`（git 忽略），未提交。

## 5. 下一步（M1）

- Rust 搜索核 + 批量 NN 评估（目标 ≥500 sims/s/core）；
- 8 座全搜索 + 成对矩阵 bootstrap；数据质量门禁；
- CPU-only torch（或 CUDA 运行库）接入 torch 后端训练；
- 小规模（1k–10k 局）验证“搜索 π 优于 raw policy”，再定数据规模。
