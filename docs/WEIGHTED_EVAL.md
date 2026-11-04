# 对局加权的评估（仅用于「面对 bot」的对局，2026-11-04）

> 用户澄清：加权只针对**bot 对局**——希望在「存在长且强的 bot」的对局里，模型依旧能赢；
> **不**把加权口径用于 human-board 高强度面板。本实现已按此收口：
> canonical（5 席人类盘面）**不加权**；加权只出现在纯 bot 面板与
> `scripts/bot_weighted_eval.py` 的 bot 对局分析里。

## 1. 权重定义（bot 对局）

对同一 cohort（一个 bot 面板 / 一个 collect batch）内每局：

- `turns`：对局长度（局末最大回合数）。
- `strength`：**局末 bot 席（seat 1..7）最强盘面 Σ(atk+hp)**；排除 learner（seat 0），
  这样加权衡量的是「bot 有多强」，而不是模型自己滚多大。
- 两者在 cohort 内转成平均秩百分位 `u,v`，`raw = 0.5 + 1.5*(αu + βv)`（默认 α=β=0.5），
  归一化到均值 1（软 floor/cap 0.5–2.0）。
- 指标：加权 mean_rank / top4 / win + `n_eff`；另报「长且强」子集
  （turns 与 bot 强度都在 top 25%）的 win / mean_rank。

## 2. 实现

- 纯函数：`hsbg/eval/metrics.py`（`percentile_ranks / game_weights / weighted_mean /
  effective_sample_size / weighted_eval_summary`），单测
  `tests/test_eval_metrics_weighted.py`。
- `scripts/quality_monitor.py`：每局记录 `game_turns` 与 `final_max_bot_strength`；
  **仅当未开人类盘面注入时**输出 `weighted`（`weighted` / `weight_n_eff` /
  `weight_stats`）；`--weight-alpha/--weight-beta`。
- `scripts/bot_weighted_eval.py`：读 `bot_strength_curves` JSON，按最终名次/每局
  turns+bot 强度计算加权指标与「长且强」子集。
- canonical/human 面板：**不加权**，stage monitor 也移除了加权列与曲线叠加。

## 3. 32 局 bot 面板结果（seed 830000）

| ckpt | win | mean_rank | 加权 win | 加权 rank | 长且强 n | 长且强 win | 长且强 rank | 强 bot 子集 win |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| s73 | 46.9% | 2.094 | 40.4% | 2.233 | 4 | 25.0% | 3.00 | 11.1% |
| stage 40M | 46.9% | 1.906 | 38.3% | 2.064 | 5 | **0.0%** | 2.80 | 0.0% |
| stage 80M | 21.9% | 2.094 | 22.7% | 2.046 | 4 | 25.0% | 1.75 | 22.2% |
| stage 90M | 40.6% | 1.875 | 33.7% | 1.972 | 4 | **0.0%** | 2.25 | 11.1% |
| stage 140M | 37.5% | 2.062 | 29.7% | 2.166 | 2 | **0.0%** | 2.00 | 0.0% |

- 加权后 win 从 37–47% 降到 30–40%；**长且强 bot 局 win 只有 0–25%**，强 bot 子集 win
  0–22%。即：**模型目前还做不到在长且强的 bot 局里稳定取胜**。
- 140M 的「长且强」只有 2 局（32 局里），样本太小；正式判定建议 128 局 bot 面板。
- 80M 的「长且强 rank 1.75」来自 4 局样本，不可当结论。

## 4. 用法

- 看 bot 强度/长局表现：`python scripts/bot_weighted_eval.py --json 90M=runs/bot_curves/ckpt90m.json`
  （或对 `runs/az_stage300m_b01/eval/ckpt_*.pt` 跑 `bot_strength_curves.py` 生成 JSON）。
- 训练侧（下一 stage，opt-in）：batch 已有 `game_ids/episode_ids/turns/ranks`；
  collector 补每局 `final_max_bot_strength`，用同一 `game_weights` 做 per-episode PPO loss
  权重（`--game-weight-mode {off,loss}`，默认 off）。当前 300M stage 不改。
- 结论：**暂不给 bot 加强化倍数**（k=1）；先让模型在长且强 bot 局里的 win 稳定 >50%，
  再按 `k ≈ 目标难度` 逐步加。
