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

## 6. 运行计划（2026-11-06 18:45 定稿）

### 6.1 起点与预算

- 起点：**B05 300M 权重** `runs/az_stage300m_b05/model.pt`，`TS=""`（fresh optimizer）
- 预算：300M decisions，8 卡里用 4 张 actor（3,4,5,6）+ learner 0 + dev eval 1 + canonical eval 7
- 吞吐：与 B05 同配置（8.3k dec/s）⇒ **≈10h**（若 20:00 起跑，次日 06:00 左右到 300M）

### 6.2 唯一变量

`--game-weight-mode adv --game-weight-alpha 0.5 --game-weight-beta 0.5 --game-weight-floor 0.5
--game-weight-cap 2.0`；其余与 B05 逐字一致（lr 3e-6 / mb 1024 / accum 2 / max_updates 4300 /
entropy 0.001 / clip 0.2 / target-kl 0.02 / 同一课程 ramp / 无冻结席）。

### 6.3 判据（基线换成 B05@250M）

| 指标 | B05@250M（384 局） | B06 目标 |
|---|---:|---|
| bot rank | 1.578 | ≤1.55 |
| bot win | 55.2% | ≥57% |
| **长强子集 win（n≥24）** | **40.0%**（n=25） | ≥45% |
| 长强 rank | 1.640 | ≤1.55 |
| tier5@t15 | 28.0% | ≥32% |
| human 96 局 | 5.906（200M）/ 5.948（230M） | 不劣化 >0.10 |

> 注：B06 的原始动机是修 B05@150M 的 11.1% 长强缺口；B05 后半段已自然补到 40.0%，
> 所以 B06 的定位变成「在长局上继续加码」，判据相应上调。

### 6.4 步骤（含 pilot）

1. **Pilot（5 分钟）**：`MINUTES=5 STOP=200000000 OUT=runs/az_stage300m_b06_pilot bash scripts/run_stage300m_b06.sh`
   - 检查：`history.jsonl` 的 `meta.game_weight` 出现且 `w_mean≈1`、`strength_p50>0`、`strength_all_zero=false`
   - 检查：吞吐下降 ≤10%（每局多 7 次 `player_json`）；`illegal/truncated` 不变；entropy/KL 正常
2. **正式跑**：`bash scripts/run_stage300m_b06.sh`（300M）
3. **监护三件套**：
   - `tools/relabel_b06.sh <DONE> <SINCE>`：local ckpt → global 名硬链接（续训后 DONE 由 watchdog 给出）
   - `stage_monitor.py --cum-offset <Σhistory−DONE> --retry-skipped 1 --retry-min-decisions <DONE>`
   - `tools/watchdog_b06.py`：崩溃后自动续训 + 自动重算 offset + 重启 monitor/relabeler
4. **判读面板**：`tools/eval_b06_panels.sh`（150/250/300M 各 384 局）；300M 后补 768 局
5. **收尾**：300M 后跑 768 局 bot 面板 + human 96 局 + `scripts/tier_probe.py`，与 B05/B03 同口径对比

### 6.5 风险与止损

| 风险 | 处理 |
|---|---|
| `game_bot_strength` 采集开销过大（>10%） | pilot 测出的吞吐 <7.5k dec/s 就把权重上限从 cap=2.0 降到 1.5（减少极端权重），或改用在 collector 里缓存 `player_json` 的最简字段 |
| 加权把 entropy 推高/推低 | 盯 entropy 近 20 均值；<0.66 加 `entropy-coef 0.003`，>0.82 降到 0 |
| 长强 win 反而下降 | 150M 时若 <30%（低于 B05@250M 的 40%）且 rank >1.65 → 停，改用 α=0.3/β=0.7（更偏强度）或 cap 1.5 |
| 崩溃 | watchdog 自动续训（已泛化：会同步 monitor 的 `--cum-offset`，避免 B05 那种计点全断） |

## 7. 事后更正（2026-11-07）：B06 也没有课程 ramp

与 B05 相同，B06 的完整命令行里没有 `--human-board-ramp` / `--human-board-quantile-ramp`：
实际场地是「固定 3 席 p0.90 + `sample=auto`（按回合难度曲线）+ `fidelity=board`」。
因此 B06 vs B05 的唯一差异**确实**只有 `--game-weight-mode adv`（这一点成立）；
但两轮都不是文档里描述的"p50→p75→p90 分档课程"。
