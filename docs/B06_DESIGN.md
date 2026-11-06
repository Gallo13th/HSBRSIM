# B06 设计：长强局加权（per-episode advantage weighting）

> 起点：B05 300M 权重（`runs/az_stage300m_b05/model.pt`）。唯一新增因子：
> `--game-weight-mode adv`。其余配方（优化器强度、对手、课程、奖励）与 B05 逐字一致。

## 1. 动机（B05@150M 的实测取舍）

| 指标（384 局，同 seed 620000） | B03@150M | **B05@150M** | Δ |
|---|---:|---:|---:|
| bot rank | 1.784 | **1.599** | **−0.185** |
| bot win | 47.9% | **52.6%** | +4.7pp |
| 长强子集 win（n=22/27） | 18.2% | **11.1%** | **−7.1pp** |
| tier5@t15 | 37.6% | 32.2% | −5.4pp |
| human 96 局 强度 p50 | 314.5 | **409.5** | +30% |

结论：B05 用「节奏」换了「经济」——总名次大幅改善，但**长局滚雪球退化**。
B04 的长强加权之所以无效，是因为当时策略根本不动（300M 位移 1.5%）；
B05 把位移拉到 ~2.4%、行为真的变了，加权才有落点。

## 2. 机制（实现）

- 采集端（`parallel_collect.collect_ppo_lockstep`）局末给该局所有记录挂
  `game_turns`（= 该局最大 turn）与 `game_bot_strength`（各 bot 席终局盘面 Σ 的最大值）。
  只在 `game_weight_mode != none` 时计算（多 7 次 `player_json`/局，384 局/iter 开销可忽略）。
- 打包/建批（`ppo.pack_records_arrays` → `build_batch_from_arrays`，以及 records 路径）：
  GAE 之后按 episode（`game_id, seat`）对 **advantage** 乘以权重：
  `w = game_weights(turns, bot_strength, alpha=0.5, beta=0.5, floor=0.5, cap=2.0)`（均值归一 1）。
  **不动 value 目标**（避免 value 头学到不一致的尺度）。
- 权重规则复用评测口径 `hsbg/eval/metrics.py::game_weights`，训练/评测一致。
- 观测：`history.jsonl` 的 `meta.game_weight` 里落 `n_episodes / w_mean / w_min / w_max /
  turns_p50 / strength_p50 / strength_all_zero`。

## 3. 保真性（默认关闭 = 旧路径逐位等价）

- `--game-weight-mode none`（默认）：不加任何参数、不算对手强度、不产权重数组；
  单测 `tests/test_game_weight_adv.py::test_mode_none_is_bit_identical` 断言
  advantage/returns 与旧路径**逐位一致**。
- 另三条单测：缩放比例与 `game_weights` 一致、records 与 arrays 路径一致、
  缺强度字段时退化为「仅长度」（`strength_all_zero=True`）。

## 4. 判据（≥384 局；终评 768 局）

| 指标 | 目标 |
|---|---|
| 长强子集 win（n≥24） | **≥26.7%**（B01 的 20% + 10pp；B05 是 11.1%） |
| bot rank（384/768 局） | ≤1.65（B05@150M 1.599 的档位保持） |
| tier5@t15 | ≥35%（B05 32.2%，B03 37.6%） |
| human 96 局 | 不劣化 >0.10（B05 6.146 / 强度 409.5） |

早停：150M 时若长强 win <13% 且 bot rank >1.75 → 停（说明加权没修到长局，改查价值头/搜索）。

## 5. 复现

```bash
bash scripts/run_stage300m_b06.sh                     # 300M（B05 300M 权重起）
DRY_RUN=1 OUT=/tmp/dry bash scripts/train_block_clean.sh ...   # 只打印命令
pytest tests/test_game_weight_adv.py -q               # 4 条单测
```
