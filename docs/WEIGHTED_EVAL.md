# 对局加权的评估（长度 + 强度，2026-11-04）

> 用户需求：按「对局结束后的回合数长度 + 对局强度」给每局加权，用于精选 batch 或加权打分。
> 本轮实现**加权打分**（评测侧，不改变训练）；同一个 `game_weights` 可直接接到 PPO 的
> per-episode loss 权重（见 §5，作为下一 stage 的 opt-in）。

## 1. 权重定义

对同一 cohort（一个评测 panel / 一个 collect batch）内的每局：

- `turns`：对局长度（局末最大回合数）。
- `strength`：对局强度（**局末全桌最强盘面 Σ(atk+hp)**；canonical 面板含人类盘面，
  所以数值会是数万，这是「全桌最强」而不是模型自己的身材）。
- 先转成 cohort 内的**平均秩百分位** `u,v ∈ [0,1]`（并列取平均），
  `raw = floor + (cap-floor) * (alpha*u + beta*v)`，再归一化到均值 1。
- 默认 `alpha=beta=0.5`、`floor=0.5`、`cap=2.0`：长且强的局权重最高，短且弱的局最低。
- 加权指标：`w_mean_rank / w_top4 / w_win / w_mean_strength / w_mean_turns`；
  同时给 `n_eff = (Σw)² / Σw²`（有效样本量，权重越集中越小）。

## 2. 评测侧实现

- 纯函数：`hsbg/eval/metrics.py` 的 `percentile_ranks / game_weights / weighted_mean /
  effective_sample_size / weighted_eval_summary`（带单测 `tests/test_eval_metrics_weighted.py`）。
- `scripts/quality_monitor.py`：每局记录 `game_turns` 与 `final_max_strength`；panel JSON 增加
  - `weighted`：加权指标（与未加权并列）；
  - `weight_n_eff` / `weight_stats`（min/max/mean）。
  - 新参数 `--weight-alpha/--weight-beta`（默认 0.5/0.5）。
- `scripts/stage_monitor.py`：canonical 点记录 `w_rank/w_top4/w_win/w_strength/w_n_eff`；
  仪表盘新增「加权点表」；曲线面板 1/2/3 叠加 `w_rank/w_top4/w_strength` 虚线。
  `points.jsonl` 自动带这些字段（从下一个 10M 点开始）。

## 3. 130M 样本（96 局 canonical，seed 520000，5 席人类盘面）

| 指标 | 未加权 | 加权（长度+强度） |
|---|---:|---:|
| mean_rank | 6.177 | **6.167** |
| top4 | 13.54% | **12.32%** |
| mean_turns | — | 15.60 |
| n_eff | 96 | **89.6** |

⇒ 这个 checkpoint 上加权/未加权几乎一致（rank −0.01，top4 −1.2pp），说明模型在
「长且强」的局里没有明显更好或更差；8 局 bot 小样本里加权 rank 1.786 vs 未加权 1.625
（长/强局更差），样本太小不做结论。两个口径都保留，避免只挑好看的。

## 4. 结论/用法

- **评估**：默认同时报未加权 + 加权；加权 rank/top4 只作为**补充口径**，不单独用于
  early-stop（n_eff 会随权重集中而下降）。
- **训练（下一 stage，opt-in）**：batch 已带 `game_ids/episode_ids/turns/ranks`，
  只需在 collector 里补每局 `final_max_strength` 并换算 `game_weights`，在 PPO loss 里
  按 episode 权重乘 policy/value loss（归一化到均值 1）。`--game-weight-mode {off,loss}`
  默认 off，不影响当前 300M stage。
- **风险**：强度含人类盘面时是「全桌最强」，不是模型强度；权重会让长/强局占更大比重，
  需同时看 `n_eff` 与未加权值，防止评测口径漂移。
