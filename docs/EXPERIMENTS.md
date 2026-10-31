# EXPERIMENTS — 实验台账

> 规范见 [AGENT_TEAM.md](AGENT_TEAM.md) §3。**所有占过 GPU/CPU 的 run 都要有一行**（含失败、含 40 iter 的 A/B）。
> 「配方摘要」**只写差异**；完整命令行应落在 `runs/<run>/cmd.txt`（老的 run 没有，只能从 `summary.json.config`
> 或 `history.jsonl` 首行 `args` 反查）。
>
> 数字口径：`human` = human 面板 mean rank（**越小越好**；括号内是局数）；`tier` = t9/t12/t15 的 tier p50；
> `强度比` = t9/t12/t15，分母是同 turn 真实 10k+ p50。`—` = 该项**没有测过**，不是「测了是 0」。
>
> 最后更新：2026-10-31 12:20（s14 仍在跑，最后一行是活数据，会随训练推进变化）。

## 1. 主线训练 run

| run | 配方摘要（相对上一版） | 预算（实际） | human 面板 | tier (t9/t12/t15) | 强度比 (t9/t12/t15) | 结论 | 链接 |
|---|---|---|---|---|---|---|---|
| `az_entity_s8b` | 镜像 3 席 p0.3 + 人类 2 席 p0.3；`shaping 1e-3`；`bc 0.008`；无 DPO | 20M | 6.493(10M) → 6.559(20M) | — | — | 历史 | [PROJECT_MEMORY](PROJECT_MEMORY.md) §1.3 |
| `az_entity_s9d` | s8b + **move-guard 1**；仍 `shaping 1e-3`；无 DPO | **32.2M** / 1.56 h | 6.461(10M) → **6.445**(20M) | 4 / 4 / 4.5 | **.388 / .127 / .036** | **exam 对照基线** | [runs/az_entity_s9d](../runs/az_entity_s9d) + [runs/exam/SUMMARY](../runs/exam/SUMMARY.md) §11 |
| `az_entity_s10` | s9d@801 + **塑形关(0)** + **DPO 0.02/every1** + `bc 0.008→0.004` | **60.0M** / 2.87 h | 6.533 → 6.523 → 6.514 → **6.402**(40M) → 6.471(50M) | 4 / 4 / 4 | .381 / .136 / .034 | 采纳（塑形关 + DPO） | [REWARD_SHAPING](REWARD_SHAPING.md) §10.3、[DPO_UPGRADE](DPO_UPGRADE.md) §6.5 |
| `az_entity_s11`（支线） | s10 + 人类 3 席 p0.5（+镜像 3 席 p0.3） | 17.2M / 0.72 h | **—（无 human 面板）** | — | — | **未并入主线**（BC warm-start 尝试的载体） | [runs/az_entity_s11](../runs/az_entity_s11) |
| `az_entity_s12` | s10 + **剂量跳档 5 席 p0.9** + 镜像 3→2 席 p0.2 | **60.0M** / 2.80 h | 6.371 → **6.344**(20M) → 6.402(30M) → 6.441(40M) | — | — | exam 相对 s9d **−0.0894** | [DECISIONS](DECISIONS.md) D-20261031-01 |
| `az_entity_s13` | s10 + **quasi_full + fidelity=full**；剂量同 s12 | **120.0M** / 6.37 h | 6.344(10M) → 6.430(20M) → 6.260(70M) → 6.307(110M) | 4 / 4 / 4（10M ckpt） | .414 / .148 / .036（10M ckpt） | **当前最强固定配置** | [runs/az_entity_s13](../runs/az_entity_s13) |
| `az_entity_s14`（**在跑**） | s13 + **archetype 0.5** + **fast-inject/leaf-wait 0** | 目标 120M；已 **22.6M** / 0.95 h（12:20） | **6.328**(10M，256 局) | 待测 | 待测 | **进行中**（预算 ~19%） | [PROJECT_MEMORY](PROJECT_MEMORY.md) §2、[PERF_COLLECT](PERF_COLLECT.md) |

> **不要**把 s10 的 6.402（单点最佳）与 s13 的 6.260（单点最佳）直接相减当「进步 0.14」：
> ① 两者面板点数/预算不同；② 开发面板 420000 的最小值有选点偏差；③ 配置不是单变量。
> 可比的是 exam 的**配对差**（[runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md)）。

## 2. A/B 实验（单变量，40–60 iter 级）

| run | 臂与唯一变量 | 预算 | human 面板 / 配对 Δ | tier | 强度比 | 结论 | 链接 |
|---|---|---|---|---|---|---|---|
| `ab_move_guard` | A 全关 / B guard+split 头 / C 只 guard | 40 iter ≈1.2–1.4M/臂，seed 14100 | 96 局：6.833 / 7.344 / **6.792**；C−A **−0.042 [−0.198,+0.115]**、B−A **+0.510 [+0.229,+0.792]** | t9/t12 三臂均 5/6（不同 seed 面板） | — | **采纳 C**；否决 split 头 | [MOVE_GUARD](MOVE_GUARD.md) §7.3 |
| `dpo_ab` | A 0 / B 0.002 / C 0.005 / **D 0.02+e1** | 40–60 iter | D−A **−0.042**（96 局）；bot −0.016 | D：4 / 4 / **5**（A：4/4/4） | — | **采纳 D** | [DPO_UPGRADE](DPO_UPGRADE.md) §6.5 |
| `shaping_ab` | A 关 / B 开（γ 对齐），两批独立 seed | 60 iter ≈1.6M/臂 | Δ(B−A) **−0.208 [−0.427,+0.010]**（seed 15100）/ **−0.035 [−0.194,+0.125]**（seed 23200） | 两批 t15：A 5.0 / B 4.0 | — | **采纳关闭** | [REWARD_SHAPING](REWARD_SHAPING.md) §10.3 |
| `ab_tier` | A 0 / B coef1 / C coef10 | 40 iter ≈1.6M/臂 | B≈A（6.50 vs 6.48，48 局）；C 6.79（更差，噪声内） | B 未动；C t12 tier≥5 28→50% | — | **不启用** | [TIER_TARGET](TIER_TARGET.md) §7 |
| `ab_firestone_mix` | A quasi_full / B mixed（3,922 行） | 40 iter ≈1.1M/臂 | 144 局 6.2917/6.3542 Δ**+0.063**；512 局 6.3496/6.4180 Δ**+0.068 [-0.031,+0.172]** | — | t12 .1381→.1375；t15 .0363→**.0312** | **否决**（稀释 t14 −40%） | [FIRESTONE_MIX_AB](FIRESTONE_MIX_AB.md) §0 |
| `az_arch_ab`（archetype） | A coef0 / B 0.5 / C 1.5 | 40 iter ≈1.1M/臂，seed 同 s13 | 144 局 6.257 / **6.194** / 6.347（Δ 全在噪声内） | C 的 tier/强度最好，但 human top4 −4pp | — | **采纳 0.5，否决 1.5** | [ARCHETYPE_BIAS](ARCHETYPE_BIAS.md) §7 |
| `bc_moveA`…`bc_moveF` | BC 预训练 8 组（含 Move 监督 / anchor / lr 变体） | 20k 样本 × 200 步/臂 | 48 局 top4：29.2 / 20.8 / 14.6 / 33.3 / 47.9 / 41.7（判据 ≥85%） | 最好 F 4/5/5 | 最好 F .053/.008 | **全败 → 否决 warm-start** | [BC_PRETRAIN](BC_PRETRAIN.md) §9.3 |
| `ab_rare`、`ab_l*`、`ab_rc_*`、`ab_amp_*`、`ab_leaf_*`、`ab_wait*`、`ab_ls_*`、`ab_pipeline*`、`ab_serial*` | 吞吐/采集管线参数（lockstep、pipeline、leaf bf16、wait、amp、RSS） | 多为 1–10 iter 短跑 | —（不看面板） | — | — | 见 [THROUGHPUT_FINAL_REPORT](THROUGHPUT_FINAL_REPORT.md)、[PERF_COLLECT](PERF_COLLECT.md) | `runs/ab_*` |

## 3. 评测 / 审计（不训练，不占 GPU）

| 项 | 规模 | 结果 | 产物 |
|---|---|---|---|
| **独立 exam**（4 面板 × 6 ckpt） | 12,288 局，n=2,048 配对，簇 bootstrap | 候选 vs s9d：−0.058 ~ −0.107（CI 不含 0）；细粒度排序不复现（ρ=+0.55）；MDE 0.0898 | [runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md)、`runs/exam/MANIFEST.json`、`ckpts/SHA256SUMS.txt` |
| **压力审计**（冻结轨迹反事实） | 521 快照 × 64 配对战斗 × 3 配置 | 注入→败率 +63.7…+72.5pp；暴露 4.6%/turn；GAE 权重 0.319；终端分量 14.6% | [PRESSURE_AUDIT](PRESSURE_AUDIT.md)、`runs/audit/pressure_audit.json` |
| **保真度审计**（三档配对） | 460 帧可信 EOT × 3 容器 = 1,380 配对 | counters +2.62pp（combat）/+1.36pp（pipeline）；完整真值比 board-only +5.12/+6.71pp | [FIDELITY_INJECTION](FIDELITY_INJECTION.md)、`runs/audit/fidelity_injection.json` |
| **quality 面板**（tier/强度/出局/换位） | 64–96 局，bot 对手 | 见 [PROJECT_MEMORY](PROJECT_MEMORY.md) §5.1–§5.2 | `runs/quality/*.json`、`runs/exam/quality_*.json` |
| **采集侧吞吐 A/B** | 32 局 × 3 iter（CPU 锁步）+ s14 折算 | 注入 −69%；dec/s +19%；records **sha 逐位相同** | [PERF_COLLECT](PERF_COLLECT.md)、`runs/profile_collect/` |
| **数据构建** | quasi_full 1,961 行 / mixed 3,922 行 / firestone 10,811 行 + 149,166 动作 / bc 308,944 样本 | 字段覆盖见 [PROJECT_MEMORY](PROJECT_MEMORY.md) §6 | `data/real_library/*.jsonl`、`data/firestone_bc/` |

## 4. 新增一行时的检查清单

1. `run` 名与 `runs/<run>` 目录一致，且 `runs/<run>/cmd.txt` 存在（新 run 必须有）。
2. `human 面板` 列必须带**局数**；只有 64 局的不能写进「结论」列。
3. `结论` 只能是：采纳 / 否决 / 证据不足 / 进行中 / 历史。**不许写「看起来更好」**。
4. 若该行改变过默认配方 → 必须有一条 [DECISIONS](DECISIONS.md) 条目；两条要互相链接。
5. 失败行也要写「为什么失败」的机制（未知就写「机制未知」），否则半年后会被重跑。
