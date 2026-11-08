# Stage-300M 训练报告（2026-11-04）

## 0. 一句话

300M stage 从 s73 精确续训，实际跑到 **287.01M / 300M（95.7%）** 因「642 分钟时间护栏」
正常收尾（非崩溃）；final 模型对 bot 的面板为 **rank 1.734 / top4 96.9% / win 47.7%**，
但 **长且强 bot 局 win 仍为 0/6**；human 面板与 s73 基本持平（final 6.281，最佳单点 200M 6.000）。

## 1. 运行

- run：`runs/az_stage300m_b01`；起点 `s73`（model+trainer 精确续训）；seed 27502。
- 32 procs / threads 2 / minibatch 2048 / grad-accum 4；actor GPU 3,4,5，learner cuda:0。
- 配方不变：anchor 0.1 常数、max-updates 3000、lr-min 0.5、10M 周期评测。
- 中途 11:34 一次引擎 segfault（34.98M），从 step_001001 精确续训；其余无事故。
- 结束原因：`[loop] remaining time < last iteration; stop`（`--minutes 642`）。
  updates 4473，elapsed 38,490s（10.7h），`illegal=0 / truncated=0`。
- 产物：`model.pt` sha256 `e80d8d0d…`，`trainer.pt`，`summary.json`；
  final panel `runs/eval_panel/az_stage300m_b01_panel.json`。

## 2. human canonical 面板（96 局 / seed 520000 / 5 席 p0.9）

| 点 | 180M | 190M | 200M | 210M | 220M | 230M | 240M | 250M | 260M | 270M | 280M | final 287M |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rank | 6.198 | 6.250 | **6.000** | 6.292 | 6.208 | 6.198 | 6.156 | 6.240 | 6.135 | 6.104 | 6.542 | 6.281 |
| top4 | 13.5% | 15.6% | 16.7% | 12.5% | 10.4% | 10.4% | 10.4% | 12.5% | 11.5% | 16.7% | 7.3% | 9.4% |
| strength | 355.5 | 344 | 345 | 363.5 | 372.5 | 348.5 | 358.5 | 352 | 370 | 356 | 256.5 | 349 |
| tier≥4 | 47.9% | 56.3% | 59.4% | 53.1% | 58.3% | 53.1% | 57.3% | 59.4% | 54.2% | 53.1% | 44.8% | 52.1% |

- 全段 rank 6.0–6.54 震荡，**没有单调改善**；最佳单点 200M（6.000）。
- 280M 是一次明显低谷（6.542 / strength 256.5），final 287M 回到 6.281。
- 对比 s73（6.2 左右）与 s61（6.083）：**stage 没有超过起点**。

## 3. bot 面板（8 席全 bot；训练配置 move_guard=1）

**128 局 / seed 620000（与 training 一致）**

| 口径 | mean_rank | top4 | win |
|---|---:|---:|---:|
| 未加权 | **1.734** | 96.9% | **47.7%** |
| 加权（长度+bot 强度） | 1.835 | 96.3% | 40.6% |

- 128 局未加权 win 47.7%（8 人局随机 12.5%），rank 1.73，top4 96.9% —— **对 bot 的水平与
  s73/40M 同档或略好**，说明 300M stage 没有把 bot 能力练坏。
- 反例：同一 ckpt 若 **不加 move_guard**，win 掉到 22.7% —— bot 面板必须与训练配置
  一致（move_guard=1）才有可比性。
- `bot_strength_curves` 64 局（seed 830000，训练配置）：win 40.6%、rank 1.984；
  **长且强 bot 局 0/6 胜**、强 bot 子集 0/64 —— 即 **遇到 bot 滚雪球的长局仍打不过**。
  这与 s73/40M/90M/140M 的结论一致（长且强 win 0–25%）。

## 4. 结论（B01）

1. 300M stage 在 human 面板上没有可测提升（final 6.281 vs s73 ~6.2），最佳单点 200M 6.000；
   在 bot 面板上保持/略优于 s73（47.7% win / 1.73 rank），但 **长且强 bot 局仍 0 胜**。
2. **不给 bot 加强化倍数（k=1）**：模型在长且强 bot 局尚未稳定取胜，加 k 只会更难。
3. 下一阶段：
   - 默认打开 `--bot-panel-games 96`，每个 10M 点同时记录 bot rank/win + 加权 bot 指标；
   - 训练侧可 opt-in per-episode 权重（长度+bot 强度，loss 加权），当前不改；
   - human 面板继续保留作参考，但 bot 局 rank/长且强 win 作为主要判据；
   - 若下一段仍无提升，按 P2（anchor 调度）做单变量实验，不再混其它改动。

## 5. B02：floor-lr 空转，提前停止（2026-11-05）

- run：`runs/az_stage300m_b02`；起点 = B01 final（model + trainer）；seed 27503；STOP 300M；
  human-board 固定 3 席 / p0.9 / p75（与 B01 相同）。
- 00:41 启动 → 04:33 在 92.12M 崩溃（采集空 mask）→ 07:16 从 `step_005701` 精确续训
  → 07:59 人工停止，本 run **101.10M / 300M**（iter 5823）。
- 9 个 canonical 点（10–90M）human rank **6.010–6.448（均值 6.288）**，与 B01 final 6.281
  同档；bot 面板 rank 2.02–2.25 / top4 92–100% / win 23–35%，只有噪声、无趋势。
- 统一 **guard=1** 口径（96 局 / seed 620000）复核：

  | ckpt | rank | top4 | win |
  |---|---:|---:|---:|
  | B01 final | **1.823** | 97.9% | **41.7%** |
  | B02 10M | 1.917 | 96.9% | 41.7% |
  | B02 90M | 1.969 | 94.8% | 35.4% |

  ⇒ 多训 92M 没有提升（方向略差，约 1 SE）。
- **根因**：lr 排程在整个 B02 阶段钉在退火下限 5.85e-7。`ppo_trainer.py` 的 LambdaLR 为
  `lr = base * max(min_ratio, 1 - (1-min_ratio)*step/max_updates)`，`max_updates=3000`
  来自 `train_block_clean.sh`，而 `--trainer-state` 恢复了 B01 的 `updates≈4472`，于是
  `step > max_updates` → lr 恒为 5.85e-7。B01 也在 update 3000（≈192M decisions）触底，
  所以 **B01 尾段 + B02 全部约 190M decisions 都是 floor-lr 空转**；对应每步 policy
  KL≈0.0005、ratio≈1.0、clip≈0.3–0.9%，anchor_kl 从 0.0004 单调爬到 0.010（72M→92M），
  而 rank/value 指标完全不动。
- 处置：最佳起点仍为 **B01 final**（`runs/az_stage300m_b01/model.pt`）；最新权重
  `runs/az_stage300m_b02/snapshots/step_005801`；9 点数据保留作证据，明细见
  `runs/az_stage300m_b02/STOP.txt`。
- 另修：`stage_monitor.py` 的 bot 面板此前没传 `--move-guard`（JSON 里 `move_guard=false`），
  与 B01 final 的 guard=1 不可比；已加 `--bot-panel-guard`（默认 1）。
- 影响：B03 **不能沿用 `--trainer-state`**（否则同样 floor-lr）；新 stage 用 fresh optimizer
  + `LR/MAX_UPDATES` 重新退火（见 `docs/B03_DESIGN.md` §6.5）。

## 6. 后续（B03）

- B03 = 课程学习（human-board 席数/概率/分位 ramp，`docs/B03_DESIGN.md`）；
  起点 B01 final；seed 27503；300M。
- 与 B02 的唯一工程差异：**fresh optimizer + lr 重新退火**（`LR=1.17e-6`、
  `MAX_UPDATES=4500`），修复 §5 的 floor-lr；课程参数通过
  `HB_RAMP` / `HB_QUANTILE_RAMP` / `RAMP_MODE` 透传。
- 评测：每 10M human 96 + 8-bot 96（现在 bot 面板默认 `--move-guard 1`，并新增
  长且强子集 `bot_ls_n/rank/win`）。
- 判定与早停规则见 `docs/B03_DESIGN.md` §5。
