# 纯搜索（bot-rollout）能力测试

> 用户选择 B 方案：Rust MCTS + bot-rollout 叶价值（不接 NN），测量纯搜索的强度/吞吐。
> 实验：seat0 纯搜索 vs 7 个引擎 bot；同 seed heuristic 基线。远程 `hiermolgen`（CUDA torch
> 仅用于环境，搜索不调用 NN）。

## 1. 实现

- `rust/crates/hsbg-engine/src/search.rs`：`SearchConfig.rollout`（默认 false）；
  `rollout=true` 时叶节点不调 `eval`，先验=合法动作均匀，value=`bot_rollout_value`
  （clone Game → 所有 `needs_action` 座位 `bot::play_turn` 打到终局 → placement utility）；
  PyO3 `mcts_search(..., rollout=True, eval_fn=None)`；rollout 模式释放 GIL。
- `scripts/az_pure_search_test.py`：seat0 控制，其余 bot；同 seed heuristic 基线；
  sims 扫描；报告 mean rank/top4/胜率/耗时/决策数。

## 2. 结果

### 2.1 低 sims（1000 局/配置）

| 配置 | 局数 | 总耗时 | 局/s | mean rank | top4 | 胜率 | seat0 决策/局 | search/局 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| heuristic 基线 | 1000 | 5.42 s | **184.5** | **4.507** | 50.9% | 12.6% | 135.2 | 0 |
| rollout sims=1 | 1000 | 20.84 s | 48.0 | **7.987** | 0% | 0% | 9.7 | 8.1 |
| rollout sims=2 | 1000 | 37.55 s | 26.6 | **7.982** | 0% | 0% | 12.3 | 8.2 |
| rollout sims=4 | 1000 | 73.76 s | 13.6 | **7.988** | 0% | 0% | 14.0 | 8.2 |

### 2.2 高 sims（200 局/配置；128/256 为 30 局）

| 配置 | 局/s | mean rank | top4 | seat0 决策/局 | 12h 容量（外推） |
|---|---:|---:|---:|---:|---:|
| sims=16 | 3.13 | 7.985 | 0% | 15.8 | ≈135k 局 |
| sims=32 | 1.50 | 7.980 | 0% | 16.4 | ≈65k 局 |
| sims=64 | 0.71 | 7.970 | 0% | 16.5 | ≈31k 局 |
| sims=128 | 0.36 | 8.000 | 0% | 17.2 | ≈16k 局 |
| sims=256 | 0.18 | 7.967 | 0% | 17.2 | ≈8k 局 |

**现象**：所有 sims 下纯搜索都约 **1 次决策/回合**（决策数 10–17，而 heuristic 为 135/局），
基本直接 EndTurn/移动，从不买/打/升级；名次接近垫底。

## 3. 结论与原因分析（关键）

1. **这不是“MCTS 不行”的证据，而是本次 B 实现的评估口径不成立**：
   `bot_rollout_value` 从当前状态用**引擎 bot 策略**模拟所有座位（包括 seat0 的后续回合），
   得到终局 utility；但实际继续游戏时 seat0 由**搜索策略**控制。即：
   $$
   Q_{\text{rollout}}(s,a)=\mathbb{E}_{\text{bot policy}}[u]
   \neq
   \mathbb{E}_{\text{search policy}}[u].
   $$
   搜索会认为“EndTurn 后 bot 能把局面打回中游”，但实际自己下一回合仍会 EndTurn，
   于是每回合直接结束 → 名次 8。这是 **off-policy rollout 不匹配**，不是价值/搜索代码 bug。
2. 另外：`bot_rollout_value` 在 clone 的同一 RNG 状态下重复执行是**确定性的**，
   单次 rollout 无方差但有系统偏差；uniform 先验 + 低 sims 进一步放大。
3. 当前搜索每回合只做约 1 次决策（因为选了 EndTurn/无进展动作），所以“局/s”看起来高，
   不代表有效搜索吞吐；不能用来估算有意义的纯搜索能力。

## 4. 下一步（按有效性排序）

| 方案 | 说明 | 成本 |
|---|---|---|
| **A. 成对胜负矩阵（推荐）** | 叶/回合末 K 个候选战团两两精确战斗 → 相对名次价值；无策略不匹配问题 | K=8/M=4 ≈0.3ms/次评估 |
| **B'. 自洽 rollout** | rollout 时 seat0 也用**同一 MCTS 策略**（递归搜索）而非 bot；价值与行为一致 | 很贵（rollout 内再搜索） |
| **B''. 截断 rollout + 价值近似** | 只 rollout 到回合末，再用启发式/价值模型估计后续 | 中等，需定义近似 |
| **C. 先验/候选聚焦** | 用 bot/启发式先验或只搜关键动作，避免低 sims 探索 245 个动作 | 低，但会引入启发式 |

**建议**：纯搜索能力测试改用 **A（成对矩阵）**，或先做 **B'' 截断 rollout + heuristic 后续**；
直接用 bot-full-rollout 作为 leaf 价值在 8 人局中不成立。

## 5. 复现

```bash
PYTHONPATH=$HOME/projects/HSBRSIM/rust/python ~/.conda/envs/hiermolgen/bin/python \
  scripts/az_pure_search_test.py --games 1000 --sims 1,2,4 --out runs/pure_search --seed 70000
# 高 sims：--games 200 --sims 16,32,64；128/256 用 --games 30
```
产物 `runs/pure_search*/report.json`（gitignore；远程已清理）。
