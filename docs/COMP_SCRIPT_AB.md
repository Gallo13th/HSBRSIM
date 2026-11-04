# 固定阵容脚本席 A/B（pilot，2026-11-04）

> 目的：验证「固定阵容脚本」以**对手席**接入训练后，是否改变学习结果；同时给出接入的
> 工程代价。唯一变量 `--script-seats 0 → 2`，其余完全一致。代码冻结于 commit `31d61bf`。
> 结论先行：**接入正确、无非法动作、没有退化；rank 方向性偏好但两个面板都在噪声内，
> 且脚本席使采集慢 3.3×**——因此默认关闭（opt-in），需要更大样本/更便宜实现再评估。

## 1. 预注册（执行前写定）

| 项 | control | treatment |
|---|---|---|
| 起点 | `runs/az_entity_s73/model.pt` + `trainer.pt`（精确续训） | 同左 |
| 唯一变量 | `--script-seats 0` | `--script-seats 2 --script-comps D,H` |
| 预算 | 10,000,000 decisions | 10,000,000 decisions |
| seed | 27401 | 27401 |
| 计算 | actors 3,4,5 × 24 procs / learner cuda:0 / eval cuda:1 | 同左 |
| 主判据 | 新 seed **741024 / 512 局** mean_rank；起点 s73 同 seed 复评 | 同左 |
| 次判据 | top4 / death_strength_p50 / tier_ge4_ratio / survive_t12_ratio / tier≥5@t15；canonical 96 局（520000） | 同左 |
| 判定 | `Δrank≤-0.3` 且 top4 不降 → 候选改善；`\|Δ\|<0.3` → 噪声；`Δ≥+0.3` → 回退 | — |

D/H = Elemental Azerite / Murloc End of Turn，是探针里 hybrid t15 Σ 最高的两套（314/313）。

## 2. 训练结果（决定性：两臂都跑满 10M）

| 臂 | iters | decisions | collect s | dec/s | frozen decisions | illegal | truncated |
|---|---:|---:|---:|---:|---:|---:|---:|
| control | 139 | 10,003,706 | 975.0 | **10,260** | 0 | 0 | 0 |
| treatment | 137 | 10,011,678 | 3,239.7 | **3,090** | **8,228,142** | 0 | 0 |

- 脚本席确实上场：8.23M 次脚本决策（≈0.82/learner decision），header
  `frozen_opponent="comp:D,H"`、`frozen_seats=2`；非法动作 0。
- **代价**：采集 10,260 → 3,090 dec/s（**3.3× 慢**），原因是每次脚本决策都要
  `game.view(seat)` 的 JSON 解码 + CompPolicy 前向（见 §5）。

## 3. 评测（两把尺子）

### 3.1 新 seed 741024 / 512 局（主判据）

| 模型 | rank | top4 | strength_p50 | tier≥4 | survive12 | tier≥5@t15 |
|---|---:|---:|---:|---:|---:|---:|
| s73（起点） | **6.232** | 12.70% | 322.0 | 57.81% | 14.84% | 7.08% |
| control（10M） | 6.324 | 12.89% | 315.5 | 48.63% | 14.65% | 5.71% |
| treatment（10M） | 6.258 | 10.74% | 322.0 | 49.80% | 15.04% | 4.80% |

Δ（treatment − control）：**rank −0.066**、top4 −2.15pp、strength +6.5、tier≥4 +1.17pp、
survive12 +0.39pp、tier≥5@t15 −0.91pp。
（512 局单模型 SE≈0.08–0.09，diff SE≈0.12 ⇒ Δrank≈0.55σ，**噪声**。）

### 3.2 canonical 96 局 / seed 520000

| 模型 | rank | top4 | strength_p50 | tier≥4 | survive12 | tier≥5@t15 |
|---|---:|---:|---:|---:|---:|---:|
| s73 | 6.208 | 14.58% | 347.5 | 60.42% | 11.46% | 4.41% |
| control | 6.375 | 8.33% | 300.5 | 51.04% | 10.42% | 3.45% |
| treatment | **6.135** | 14.58% | **362.0** | 59.38% | 15.62% | 6.94% |

Δ（treatment − control）：**rank −0.240**、top4 +6.25pp、strength +61.5、tier≥4 +8.3pp、
survive12 +5.2pp、tier≥5@t15 +3.5pp。按 astra 协议 |Δ|<0.3 ⇒ **不可判**（方向性偏好）。

## 4. 裁决

- **接入正确性成立**：脚本席真实上场（8.23M 决策）、legal 率 1.0、两臂同预算同 seed、
  除 `--script-seats` 外无其它变量；训练过程无异常。
- **效果**：两个面板方向一致（treatment rank 更好），但都在噪声带内；且 512 面板的
  top4/tier≥5 反向 ⇒ **不能宣称改善**。也不存在退化信号（512 局 Δrank +0.025 vs 起点）。
- **成本**：采集 3.3× 慢，这是当前实现（逐决策 view JSON）的工程代价，不适合默认开。
- **默认**：`--script-seats 0` 保持 opt-in；下一轮要么优化脚本席决策路径（缓存视图 /
  仅在招募关键决策调用），要么把脚本作为**评测/探针**使用（已完成）。

## 5. 已知限制与下一步

1. 脚本是招募期策略（hybrid 的经济/升本/站位仍由引擎 bot 兜底），强度≈bot 量级；
   把它当对手是在增加**阵容多样性**，不是增加强度。
2. 10M/臂是 pilot；要判 `≤-0.3` 的改善需 ≥1024 对同 seed 复评，或先做 5 对训练种子。
3. 逐决策 `view_of` 的 CPU 代价可优化：同一回合缓存 `view`（按 `(turn, seat, shop/shop_mask)`
   失效）、只在 `Buy/Play/Choose/Upgrade` 关键决策调用脚本、或把脚本动作离线成查表。
4. 与 comp_fit（奖励 shaping）的关系：本接入**不改变奖励**；comp_fit 仍按 DECISIONS
   D-20261104-02 保持关闭（T1 四臂 + 非 PBRS + 2 套可达）。
