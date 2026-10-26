# AZ-MCTS 1k 局小规模验证（Rust 搜索核）

> 目的：验证 **Rust MCTS 搜索核 + 训练管线** 在 1k 局规模下的可运行性、吞吐与初步质量；
> 不是 scaling/强度实验。设计见 [AZ_MCTS_SELFPLAY_DESIGN.md](AZ_MCTS_SELFPLAY_DESIGN.md)。

## 1. 环境与命令

- 远程机 `biocourse-glt` / `oulab-cs9`；conda env `hiermolgen`（torch **2.6.0+cu124**，8×GPU 可用）；
- `hsbg_engine` 含 Rust MCTS 核（`mcts_search`，commit `2ccec00`）；
- 命令：
```bash
PYTHONPATH=$HOME/projects/HSBRSIM/rust/python \
~/.conda/envs/hiermolgen/bin/python scripts/az_pipeline_smoke.py \
  --games 1000 --sims 2 --epochs 3 --eval-games 100 \
  --out runs/az_1k --backend torch --device cuda --search rust --sample-stride 4
```

## 2. 吞吐效率（1k 局）

| 指标 | 数值 |
|---|---:|
| 局数 | 1,000 |
| 决策数（每次决策一次 Rust search） | 510,880 |
| 训练样本（stride=4） | 127,723 |
| 数据采集 | **338.3 s**（**2.96 局/s**，1,510 决策/s，377 样本/s） |
| 训练（3 epochs，CUDA） | **6.9 s** |
| 端到端 | **362.3 s** |
| 平均每决策耗时 | **0.662 ms**（含 Rust search + Python eval 回调） |
| Rust 搜索核单次 search（stub eval，M1 实测） | sims=1 **0.058 ms** / sims=2 **0.084 ms** / sims=4 **0.106 ms** |
| eval 回调估算 | 2–3 次/决策（≤sims+1），约 **3.8k NN evals/s**，是当前瓶颈 |

结论：**Rust 搜索核本身很快（<0.1 ms/search）**；1k 局管线吞吐由 **Python/NN eval 回调**主导
（GIL + 单样本前向）。下一步应做 Rust 端批量叶子评估回调和/或多进程 worker。

## 3. 质量评估（1k 局单轮迭代）

| 指标 | 数值 |
|---|---|
| 训练 loss（policy CE + value CE） | 3.586 → **2.801** |
| value 与终局 rank 相关系数（2k 抽样） | **0.706** |
| policy top-1 与搜索 π 一致率 | **0.595** |
| 学习策略（search-off）100 局平均名次 | **7.99**（99 次第 8、1 次第 7） |
| 同策略 search-on（sims=4）20 局平均名次 | **8.00** |
| 引擎 heuristic 基线（100 局） | **4.53**（前四率 53%、胜率 9%） |
| 搜索 π 退化：argmax=EndTurn | 52,688 / 127,723（**41.3%**） |
| 搜索 π：argmax=Choose(选项) / Buy | 10.7% / 10.1% |
| π 最大概率 均值 / 中位 | 0.731 / 0.500 |
| π 熵 均值 | 0.373（接近 one-hot） |

**质量结论（如实）**：
1. **value 头学到了信号**（rank 相关 0.706）；训练管线（数据→policy/value CE→checkpoint→
   评测）完全可运行；
2. **policy 头退化**：随机初始化 + 仅 2 sims 的单轮搜索产生的 π 高度集中（41% EndTurn），
   策略模仿后变成“快速结束回合”，评测名次 8；search-on 也无法挽救（价值/策略都未收敛）；
3. 这是 **“从零单轮 AlphaZero”** 的预期现象，不是管线 bug：1k 局/单轮远不足以让随机
   策略产生有意义的搜索目标。需要更强 bootstrap（heuristic/BC 先验或 rollout 价值）、
   更多 sims、批量 eval 和多次迭代（M2/M3），而不是一次 1k 局就要求棋力。
4. 该结果也说明 **质量评估指标必须包含**：π 熵/argmax 分布、value-rank 相关、
   policy 与 π 一致率、完整对局名次 vs heuristic；只看 loss 会误判。

## 4. 产物与复现

- `runs/az_1k/{data.npz, model.pt, report.json}`（gitignore；远程已清理）；
- 代码：`hsbg/search/engine_mcts.py`（Python 对照）、`rust/crates/hsbg-engine/src/search.rs`
  （Rust 核）、`hsbg/policy/std_net.py`、`scripts/az_pipeline_smoke.py`；
- 详细设计：[AZ_MCTS_SELFPLAY_DESIGN.md](AZ_MCTS_SELFPLAY_DESIGN.md)；
- 下一轮（M2）建议：Rust 批量 eval、heuristic/BC 冷启动、sims 调度、200k–1M 局多轮迭代。

## 5. 已知限制

1. Rust 搜索期间持 GIL，单进程不能多线程并行 search（多进程可）；
2. 无批量/异步 eval；对手座位由引擎 bot 确定性推进（非显式 chance 节点）；
3. 本验证用 `sample-stride 4` 降采样、3 epochs、单轮 1k 局；
4. 远程 numpy/torch 环境差异：本次用 `hiermolgen` conda env（CUDA torch 2.6）；
5. 远程构建用 rustc 1.97.1（借用）并临时放宽 `rust-version`，正式环境需 ≥1.98。
