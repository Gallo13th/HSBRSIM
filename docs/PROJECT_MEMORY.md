# PROJECT_MEMORY — HSBRSIM 项目记忆（跨间断开发的唯一事实底稿）

> 用途：任何新 agent / 新会话在 **30 分钟内**恢复到「知道目标、知道当前配方、知道什么已被证伪、
> 知道数字从哪来」的状态。**本文只记录已核对过的数字与结论，每条都带来源文件**；没有来源的
> 数字不得进入本文（见 §10 维护规则）。
>
> 快照时间：**2026-10-31 12:20 (+0800)** · 仓库：`/home/data/users/gaoletian/projects/HSBRSIM`
> · 代码版本：`8c61cb6 feat(archetype): soft human-archetype bias ...`（工作区有未提交改动，见 §9）
> · 数据/引擎基线：**37.0.0.255790**（`data/` + `data/p2/` + `rust/.../data/cards.json`）
>
> 配套文档：协作规范 [AGENT_TEAM.md](AGENT_TEAM.md) · 决策记录 [DECISIONS.md](DECISIONS.md) ·
> 实验台账 [EXPERIMENTS.md](EXPERIMENTS.md)。**读本文前不需要读其它 60 份 docs**。

---

## 0. 30 分钟恢复路径（按顺序做，别跳）

| 步 | 动作 | 期望产出 |
|---|---|---|
| 1 | 读本文 §1–§2 | 知道主指标是什么、当前在跑什么配方 |
| 2 | 读 [AGENT_TEAM.md](AGENT_TEAM.md) §4 交接清单 | 知道禁止事项，避免杀掉在跑的训练 |
| 3 | 读 [DECISIONS.md](DECISIONS.md) **最近 3 条** | 知道上一阶段为什么这么改 |
| 4 | `ps -eo pid,etime,cmd \| grep train_entity_sync \| grep -v grep` | 确认**实际**在跑的命令行（可能与本文不同） |
| 5 | `cat runs/az_entity_s14/latest.json` + 看 `history.jsonl` 末尾 | 确认预算完成度（version / decisions） |
| 6 | 核对 §5 的 3 个数字（s13 面板值 / exam 配对 Δ / 当前 tier p50） | 确认本文没被写旧 |

> ⚠️ 本文不是「现状」的权威，**`ps` 与 `runs/<run>/latest.json` 才是**。任何与本文冲突的
> 现场观测，先信现场，再回来改本文。

---

## 1. 目标与主指标

### 1.1 任务

在 AutoTavern 的 Rust 引擎 `hsbg_engine`（唯一机制/数值权威）上训练一个 **8 座酒馆战棋
（Battlegrounds）** 智能体；learner 占 1 席，其余 7 席是对手。目标不是「打过引擎 bot」，
而是**逼近真实 10k+ MMR 玩家**。训练栈只有 `hsbg/az`（PPO + 可选搜索），不要重新引入别的
引擎/搜索/训练路线（[AGENTS.md](../AGENTS.md)）。

### 1.2 主指标：human 面板（唯一主终点：human mean rank）

| 项 | 口径 | 来源 |
|---|---|---|
| 评测器 | `scripts/human_panel_eval.py::_panel` | [EVAL_PANELS.md](EVAL_PANELS.md) §2 |
| 对手 | **除 learner 外的全部 7 席、每回合开始、任何座位行动前**各注入一条真实 10k+ 战团（`source=human_board_approx`，board-only） | 同上 §2.3 |
| 数据 | `data/real_library/library_real_degraded.jsonl`（4,284 行，pool 实收 **4,275**） | 同上 §2.1 |
| 分位规则 | `--quantile auto`：**t≤8 → p50，t9–12 → p75，t≥13 → p90**（按 `strength=Σ(atk+hp)` 桶内最近秩分位） | 同上 §2.1 |
| 局数 | **512 局 = 8 seat × 64**（正式）；**256 局**用于训练内每 10M 的在线监控（s14 起）；`--smoke` 可 64 | 同上 §2.2 + s14 命令行 |
| learner 座位 | seat 0..7 轮换 | 同上 §2.2 |
| seed | **420000**（`--eval-seed-base 420000`） | [REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §4.1 |
| 指标 | mean rank（1 最好、8 最差）、top4、win；**win 在 human 面板恒为 0（从未第 1）** | [runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md) §4 |
| 硬约束 | 0 illegal / 0 truncated / 0 truncated_combats | [EVAL_PANELS.md](EVAL_PANELS.md) §2.2 |
| 注入自检 | `human_board_applied/attempt` ≈ **80%（512 局）/ 80%（256 局）**，拒绝原因 **100% `pending_choice`** | `runs/az_entity_s14/eval/human_010027241.json` |

**已停用的 bot 面板**（`scripts/c0_gate.py`，7 席全是引擎 bot）：

- bot 面板**已饱和**：历史最好 1.768（top4 97.1% / win 48.8%），s13 在 110M 仍是 1.764；
  再提升 1% 要多打几百万 decisions（[EVAL_PANELS.md](EVAL_PANELS.md) §1）。
- bot 强度天花板 ≈ tier 4；真实 10k+ 在 t9+ 的战团强度是 **bot 的 3–13 倍**；而我们自己的
  t15 p50 与真实差 **25.4×**（[HUMAN_BOARD_OPPONENT.md](HUMAN_BOARD_OPPONENT.md) §1）。
- **bot 面板降级为回归线**，不得再用它判「变强」（[EVAL_PANELS.md](EVAL_PANELS.md) §1）。

### 1.3 当前基线（human 面板，越小越好）

| run | 面板点（decisions → human mean rank） | 取哪个当「基线」 |
|---|---|---|
| s8b | 10M 6.493 / 20M 6.559 | 历史 |
| s9 / s9b / s9c | 10M 6.947 / 7.193 / 7.041 | 历史（Move 空转期） |
| **s9d** | 10M 6.461 → **20M 6.445** | **exam 的对照基线（6.445）** |
| **s10** | 10M 6.533 → 20M 6.523 → 30M 6.514 → **40M 6.402**（最佳）→ 50M 6.471 | 6.402 是**单点最佳**，6.471 是终值 |
| s11 | 无 human 面板记录（BC warm-start 实验，未并入主线） | — |
| **s12** | 10M 6.371 → **20M 6.344** → 30M 6.402 → 40M 6.441 | 6.344 |
| **s13** | 10M 6.344 → 20M 6.430 → 30M 6.387 → 40M 6.320 → 50M 6.266 → 60M 6.295 → 70M **6.260** → 80M 6.293 → 90M 6.314 → 100M 6.303 → **110M 6.307** | **区间 6.26–6.32**，不是单点 |
| **s14**（在跑） | **10M 6.328（256 局）** | 进行中 |

来源：`runs/az_entity_s{8b,9,9b,9c,9d,10,12,13,14}/eval/history.json`（逐点可复算）。

> **必须一起读的三条纠偏**（[REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §1）：
> ① s10 的最佳是 **6.402 不是 6.344**；② 同一个 512 局面板被反复查看，最小值有**选点偏差**；
> ③ s10/s12/s13 的剂量/保真配置不同，**不能**当作「同一算法三个种子的方差估计」。

### 1.4 独立 exam（比开发面板更硬的口径）

4 个**互不重叠**的 512 局面板（seed 730001/730513/731025/731537，**开发面板 420000 未参与**），
6 个冻结 checkpoint × 4 面板 = 12,288 局，n=**2,048 配对**，簇 bootstrap（panel,seat）：
（完整表 [runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md) §3）

| 候选 | exam mean rank | Δ vs s9d [95%CI] | 开发面板标注 |
|---|---|---|---|
| s9d | 6.4756 | — | 6.445 |
| s10 | 6.4180 | **−0.0576 [−0.1118, −0.0044]** | 6.471 |
| s10_40M | 6.4390 | −0.0366 [−0.0889, +0.0132] | 6.402 |
| s12_20M | 6.3862 | **−0.0894 [−0.1436, −0.0342]** | 6.344 |
| s13_10M | 6.3687 | **−0.1069 [−0.1660, −0.0459]** | 6.344 |
| s13_20M | 6.3721 | **−0.1035 [−0.1714, −0.0356]** | 6.430 |

**结论**：开发面板上「候选 vs s9d ≈ −0.10 名」在独立 exam 上**复现了方向与量级**；但
**细粒度排序不复现**（6 个 ckpt 的 Spearman ρ=+0.55；6.344 vs 6.430 的 0.086 差距在 exam 上是
+0.0034 [−0.0654, +0.0737]）。**只有配对差可比，exam 绝对值（s9d 6.476）与开发面板（6.445）不同**。

---

## 2. 当前训练配方（s14，在跑）

### 2.1 逐字命令行（2026-10-31 11:15 启动，PID 1687244）

```bash
/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s13/model.pt --arch entity --device cuda:6 \
  --processes 16 --gpus 3,4,5 --threads 8 --games 192 --sims 0 --epochs 1 \
  --minibatch 1024 --grad-accum 8 --amp bf16 --lr 1.2e-6 --lr-min-ratio 0.5 \
  --max-updates 3000 --clip 0.2 --target-kl 0.02 --lam 0.995 --max-grad-norm 1.0 \
  --entropy-coef 0.001 --pi-coef 0.0 --anchor-beta 0.1 --anchor-iterations 200 \
  --anchor-beta-tail 0.02 --compile-train 1 --anchor-amp 1 --pipeline 1 --lockstep 1 \
  --leaf-wait-ms 0 --human-board-fast-inject 1 --archetype-cache 0 \
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --archetype-bias-coef 0.5 --archetype-min-prob 0.6 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.2 \
  --mirror-sample p75 --mirror-seat-random 1 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-fidelity full --human-board-p 0.9 --human-board-seats 5 \
  --human-board-sample auto --human-board-set-tier 1 \
  --seq-coef 0.05 --bc-coef 0.004 --bc-type-weight 1.0 --bc-card-weight 0.5 \
  --bc-batch 128 --bc-every 4 --bc-compile 1 \
  --dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128 \
  --gpu-free-check 0 --seed 20100 \
  --eval-every-decisions 10000000 --eval-games 256 --eval-seats 8 \
  --eval-seed-base 420000 --eval-panel human --eval-human-quantile auto \
  --eval-async 1 --eval-device cuda:7 \
  --iterations 12000 --stop-at-decisions 120000000 --minutes 1800 \
  --snapshot-every 100 --keep-snapshots 4 \
  --out runs/az_entity_s14
```

### 2.2 配方解读（每一项「为什么在」）

| 组件 | 配置 | 为什么 | 依据 |
|---|---|---|---|
| 起点 | `runs/az_entity_s13/model.pt`（110M 的 s13 终值，human 6.307） | 从最强固定配置续训，不重新热身 | 本文 §1.3 |
| 对手 1：人类战团 | **准完整库 + `fidelity=full` + 5 席 × p0.9 + auto 分位 + set-tier** | 后期唯一可信的高强度对手；保真度每座位 ≈+1.36pp 压力 | [FIDELITY_INJECTION.md](FIDELITY_INJECTION.md) §4 |
| 对手 2：镜像快照 | 2 席 × p0.2 × p75 | 补「我们自己水平的对手」，让中前期不只有 bot | [MIRROR_SNAPSHOT_DESIGN.md](MIRROR_SNAPSHOT_DESIGN.md) |
| 奖励 | **rank-only**（`--shaping-coef 0`，`--pi-coef 0`=无 MCTS 目标，value 学 rank 分布） | 塑形两批复现无收益；搜索不进主环 | [REWARD_SHAPING.md](REWARD_SHAPING.md) §10.3 |
| 移动守卫 | `--move-guard 1 --move-cap 3 --move-repeat-limit 2`，**不开 `--move-head-split`** | 把「同动作连按/打满 40 动作」压掉，面板不劣化 | [MOVE_GUARD.md](MOVE_GUARD.md) §7.3 |
| DPO | `0.02 / every 1 / β0.1 / batch 128` | 修「该升不升」：t15 tier≥5 **+19.2pp** | [DPO_UPGRADE.md](DPO_UPGRADE.md) §6.5 |
| BC 辅助 | `0.004 / every 4 / type 1.0 / card 0.5` | 小权重人类动作正则；**不做 BC 预训练 warm-start** | [BC_AUX.md](BC_AUX.md) / [BC_PRETRAIN.md](BC_PRETRAIN.md) §9.4 |
| 动作序列 aux | `--seq-coef 0.05` | 回合动作序列辅助头 | [ACTION_SEQUENCE_AUX.md](ACTION_SEQUENCE_AUX.md) |
| 流派软偏置 | `--archetype-bias-coef 0.5 --archetype-min-prob 0.6` | 只加不减、不屏蔽、命中/应用率 24%/15%，三量具无退化 | [ARCHETYPE_BIAS.md](ARCHETYPE_BIAS.md) §7.4 |
| 预算 | `--stop-at-decisions 120000000`、`--minutes 1800`、`--iterations 12000` | 120M 决策硬顶（≈5h），先到先停 | 本文 §2.3 |
| 稳定性 | `--lr 1.2e-6`、`--clip 0.2`、`--target-kl 0.02`、`--anchor-beta 0.1→0.02`（200 iter）、`--lam 0.995` | KL anchor 是论文显式设计，防「越训越差」 | [AUTOTAVERN_PAPER_TRAINING.md](AUTOTAVERN_PAPER_TRAINING.md) §10 |
| 提速 | `--human-board-fast-inject 1 --leaf-wait-ms 0 --archetype-cache 0 --games 192` | 注入 1.41→0.43 ms/座位，dec/s **+19%**；`--games 256` 只会把瓶颈推给 PPO | [PERF_COLLECT.md](PERF_COLLECT.md) §0 |
| 评测 | 每 10M 一次 **256 局** human 面板，`--eval-async 1` 走 cuda:7 | 与环境（GPU 7 空闲窗口）折中；正式判定仍用 512 局 | 本文 §1.2 |

### 2.3 吞吐与预算（实测，不是估算）

| 指标 | 值 | 来源 |
|---|---|---|
| 端到端吞吐 | **≈6,400–6,600 dec/s**（截至 2026-10-31 12:20 的 805 iter：**22.60M** decisions / 3,436 s = **6,577 dec/s**；随训练推进会变） | `runs/az_entity_s14/history.jsonl`（求和）+ [PERF_COLLECT.md](PERF_COLLECT.md) §7（保守 6,400–6,800） |
| **10M decisions** | **≈25–26 分钟** | 同上（10e6/6577 = 25.3 min） |
| 120M decisions | ≈5.1 小时（`--minutes 1800` 不会先触发） | 同上 |
| 每 iter | 192 局 ≈ 28.0k decisions，wall ≈ **4.26 s**（collect 3.62 s + PPO 3.27 s 流水重叠） | `history.jsonl` 中位 |
| 采集侧 dec/s | 中位 **7,747**（fast-inject 已生效；优化前 6,089–6,921） | 同上 |
| 每 iter 注入 | 人类 attempt **11,762** / applied **7,499**（=39 座位·回合/局） | `history.jsonl` collect meta |
| 显存/机器 | learner cuda:6，collect 3/4/5，eval cuda:7；**GPU 0/1/2/7 有别的项目在跑** | `nvidia-smi` 2026-10-31 12:08 |

### 2.4 训练侧暴露（**配置级推算，未经 s14 审计**）

- 审计值（s10 配置：2 席 p0.3）：**4.59% / learner-turn**，每局 4.67 条
  （[PRESSURE_AUDIT.md](PRESSURE_AUDIT.md) §2.3）。
- s12/s13/s14 配置（同为 5 席 × p0.9，从 s12 起就跳到这里）：设计意图
  **≈(5/7)×0.9 = 64%**；s14 实测 applied/attempt **63.7%**（7,499/11,762，拒绝全是
  `pending_choice`）；按「每局 39 座位·回合 ÷ ~13 turn ÷ 7 席」折算 **≈41%/learner-turn**。
  **「≈60%」是配置级意图值，不是审计值**——若要写进结论，需按 `scripts/pressure_audit.py`
  用 s14 轨迹重跑一次。

### 2.5 配方演进（**改了什么 → 面板怎么动**，这才是"思路一致性"的骨架）

| run | 起点 | 与上一版的**主要差异**（多数不是单一变量，勿当 A/B 读） | 预算 | human 面板 |
|---|---|---|---|---|
| s8b | — | 镜像 3 席 p0.3 + 人类 2 席 p0.3；`bc 0.008`、`shaping 0.001`（塑形仍开） | 20M | 6.493 → 6.559 |
| **s9d** | s8b | move-guard 1 进主线；仍 `shaping 0.001`；无 DPO | 32.2M（上限 60M） | 6.461 → **6.445** |
| **s10** | s9d@801 | **塑形关（0.0）** + **DPO 0.02** + `bc 0.008→0.004` | 60M | 6.533 → **6.402**（50M 6.471） |
| s11（支线） | s10 | 人类 3 席 p0.5（BC warm-start 尝试的载体） | 17.2M（上限 60M） | —（无 human 面板，**未并入主线**） |
| **s12** | s10 | **剂量跳档：人类 2 席 p0.3 → 5 席 p0.9**；镜像 3 席 p0.3 → 2 席 p0.2 | 60M | 6.371 → **6.344** |
| **s13** | s10 | 数据换 **quasi_full + `fidelity=full`**；剂量同 s12（5×0.9） | **120M** | 6.344 → 6.260–6.307 |
| **s14**（在跑） | s13 | **+ archetype 0.5 + fast-inject/leaf-wait 0**；其余同 s13 | 120M | 10M 6.328 |

读法：**s12 的 −0.10 与「剂量跳档」同批发生**，s13 的保真度升级没有把面板再推一个台阶
（6.30 vs 6.34，CI 内）——这与 §4「暴露剂量才是主矛盾」的结论一致，但**因果未被单独 A/B 检验**
（s12 同时改了剂量与镜像席位，见 [DECISIONS.md](DECISIONS.md) D-20261031-01）。

---

## 3. 已证伪 / 已关闭的路线（**不要重开，除非有新证据**）

| 路线 | 一句话结论 | 关键证据 | 文档 / 位置 |
|---|---|---|---|
| **MCTS 主搜索** | 训练主环已彻底不用搜索（`--sims 0`）；论文侧唯一一次搜索尝试是「拷贝局面看到未来」，reseed 后增益 **−0.65±1.14pp** 消失；我们的 PIMC 属同类风险且经验上无增益 | `--sims 0`；论文 §8(i) | [AUTOTAVERN_PAPER_TRAINING.md](AUTOTAVERN_PAPER_TRAINING.md) §6、§10-4 |
| **自对弈** | 本项目**从未**把 8 座全自对弈作为主线（一直是「固定 bot + 镜像快照 + 人类战团」席位）；论文也没有用它，且其消融显示「校准对手库」才是最大单项收益（吃鸡率 20.9%→27.2%） | 论文 §6「Rather than self-play…」+ Table 3 | 同上 §3、§9 |
| **势函数塑形** | γ bug **已修**（commit `900911b`），但「γ 对齐的塑形」相对关闭**没有可测收益**（两批 human Δ 点估计 ≤0.21、CI 含 0，bot 两批符号相反）；λ=1e-3 的逐决策 \|F\| p50 是名次全距 7.5× | 两批 A/B：seed 15100 / 23200 | [REWARD_SHAPING.md](REWARD_SHAPING.md) §10.3 |
| **tier-target 回合惩罚** | 推荐参数（coef=1）在 1.6M decisions 尺度上**完全无效**（tier 曲线与对照一致）；coef=10 能抬 tier（t12 tier≥5 28%→50%）但 human 面板不升 → 不是「更早升级」的问题 | A/B 40 iter | [TIER_TARGET.md](TIER_TARGET.md) §7–§8 |
| **BC 预训练 warm-start** | 含 **Move 监督的 8 组配置全败**（判据 top4≥85% & 出局强度≥600 & tier≥5@t12≥45%）；最好 top4 41.7% / 强度 118。Move 概率质量压得住（20.9%→5.8%）但强度回不来 | 8 行判据表 | [BC_PRETRAIN.md](BC_PRETRAIN.md) §9.3–§9.4 |
| **Firestone 混池** | 混池**稀释 t14**（t14 p50 腰斩 −40%、t13/t14 p90 −11~17%）；A/B human Δ **+0.063/+0.068**（B 更差），已排除「改善 ≥0.10」→ **不作 s14 默认库** | 3,922 行混池 + 40 iter A/B | [FIRESTONE_MIX_AB.md](FIRESTONE_MIX_AB.md) §0、§3–§5 |
| **大样本 exam（65,536 局）** | 32,768 配对 / 65,536 局的预注册方案**运营上否决**：改用 4×512 独立面板 × 6 ckpt（n=2,048，墙钟 52 min），80% 功效 MDE **0.0898** ≈ 目标 0.101，已足以判定方向；再扩样本不改结论 | MDE/成本 | [REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §4.3 + [runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md) §9 |
| （附）换位双投影头 | `--move-head-split 1` 让 human 面板**显著劣化 +0.51**（随机初始化头 40 iter 训不动） | B vs A | [MOVE_GUARD.md](MOVE_GUARD.md) §7.3 |
| （附）动作回放/轨迹库 | 从 s6 起被 B-vs-C pilot 否决（无可测强度增益），整 `Player` 移植破坏 pool/eid 不变量 | commit `865b333`（`exp(trajectory): … drop the replay route`） | [LIBRARY_POOL_PLAN.md](LIBRARY_POOL_PLAN.md)、[MIRROR_SNAPSHOT_DESIGN.md](MIRROR_SNAPSHOT_DESIGN.md) §1 |
| （附）`--games 256` 提速 | 采集 +26% 但 PPO 时间翻倍，端到端不变 → 保持 192 | 瓶颈从 collect 转到 PPO | [PERF_COLLECT.md](PERF_COLLECT.md) §6.2 |

---

## 4. 已证实的机制（可以当「已知」用）

| 机制 | 结论 | 关键数字 | 来源 |
|---|---|---|---|
| **注入 → 压力链** | 成立且极大。条件在「人类战团落在学习者本回合对位座位」上 | 败率 21.0% → 84.8–93.6%（**+63.7…+72.5pp**，CI 不含 0）；承伤 3.16 → 18.5–19.0（+15.3…+15.8）；学习者剩余随从 3.02 → 0.12–0.31 | [PRESSURE_AUDIT.md](PRESSURE_AUDIT.md) §2.1 |
| **压力最大区间** | t9–t12（人类 p90 战团指数领先），注入后败率 97.9–100% | 逐 turn Δ败率 +87.3/+87.1/+89.0pp（t9/10/11） | 同上 §2.4 |
| **暴露剂量** | 审计值 s10 配置 **4.59%/learner-turn**（每局 4.67 条）；s14 配置级 ≈41–64%/turn（见 §2.4）；human 面板是 **100%/turn × 7 席**，**训练分布与主指标差一个数量级** | 4.48–11.89%/turn（三档） | 同上 §2.3 + §3.3 |
| **保真度缺口** | board-only 注入**系统性低估**压力（对手更弱） | counters 档 B2r−B0 = **+2.62pp** [1.75,3.53]（combat）/ **+1.36pp** [0.18,2.60]（pipeline）；完整真值 FULL 比 board-only **+5.12pp**（同帧）/ **+6.71pp**（管线） | [FIDELITY_INJECTION.md](FIDELITY_INJECTION.md) §4、[PRESSURE_AUDIT.md](PRESSURE_AUDIT.md) §2.7 |
| **信用分配未被 λ 压没** | λ=0.995 下早期决策仍有 ~1/3 的终局信用 | GAE 权重中位 **0.319**（t≤8）、t7 升本 **0.349**；**终端分量只占早期 \|A\| 的 14.6%**（阈值 10%，边界态） | [PRESSURE_AUDIT.md](PRESSURE_AUDIT.md) §2.5 |
| **移动守卫有效** | 行为分布约束生效，且面板不劣化 | 换位/换位回合 **19.91 → 2.31–2.35**（max 40→3）；空转率 **24.6% → 3.3–3.8%**；human Δ **−0.042 [−0.198, +0.115]**；bot 1.922 vs 2.031 | [MOVE_GUARD.md](MOVE_GUARD.md) §7.2–§7.3 |
| **DPO 0.02 有效** | 修 tier 进度且不牺牲面板 | t15 的 tier p50 **4→5**；tier≥5@t12 **+8.9pp**、**@t15 +19.2pp**；池上 picks_upgrade 69.05%→77.7%（+8.6pp ≈10σ）；human Δ −0.042、bot Δ −0.016 | [DPO_UPGRADE.md](DPO_UPGRADE.md) §6.5 |
| **流派软偏置可用但不必需** | coef=0.5 只改 6.1% 的 greedy 选择，三项量具无显著差异 | 命中 24.2% / 应用 14.7%；human 144 局 6.257→6.194 | [ARCHETYPE_BIAS.md](ARCHETYPE_BIAS.md) §7 |
| **提速不改变语义** | fast-inject/leaf-wait 开启后 **records sha 逐位相同** | 注入 1.41→0.43 ms/座位；wall −14.4%；117 单测通过 | [PERF_COLLECT.md](PERF_COLLECT.md) §7、§9 |

---

## 5. 关键数字表（复制粘贴用；**必须带来源与局数**）

### 5.1 tier 与强度（quality_monitor，96 局，**bot 对手**，seed 740000）

| 指标 | s9d | s13_10M | 真实 10k+ 参考 |
|---|---|---|---|
| mean rank（bot） | 1.8854 | 1.6250 | — |
| top4 / win | 0.9792 / 0.3750 | 0.9896 / 0.5625 | — |
| 出局回合 p50 | 15 | 15 | — |
| **出局时战团强度 mean** | **887.05** | **941.00** | t15 p50 **26,516** |
| **强度比 t9** | **0.3879** | **0.4135** | 1.0 |
| **强度比 t12** | **0.1269** | **0.1480** | 1.0 |
| **强度比 t15** | **0.0357** | **0.0361** | 1.0（≈3%，即「场面强度弱」） |
| tier≥5 比例 @t12 | 0.2234 | 0.2708 | t9+ 到 5–6 |
| 换位次数/回合 | 4.0586 | 4.6926 | — |
| 净盘面不变回合比 | 0.2306 | 0.2333 | — |

来源：[runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md) §11；真实参考 [HUMAN_BOARD_OPPONENT.md](HUMAN_BOARD_OPPONENT.md) §1
（t10 p50 1,128.5 / t12 4,458 / t15 26,516）。

> **口径警告**：强度比、tier 都是「本局 learner 的 p50 / 同时刻真实人类 p50」，**分母按 turn 匹配**；
> 不要用「出局时强度 800 ÷ 真实 t15 26,516」当强度比（[REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §5）。

### 5.2 tier p50 / tier≥5（同一批 96 局 quality 面板，**seed 740000，bot 对手，评测侧守卫关**）

| ckpt | tier p50 t9 / t12 / t15 | tier≥5 t9 / t12 / t15 | 来源 |
|---|---|---|---|
| s9d | 4 / 4 / 4.5 | 8.3% / **22.3%** / 50.0% | `runs/exam/quality_s9d.json` |
| s13_10M | 4 / 4 / 4 | 10.4% / **27.1%** / 40.0% | `runs/exam/quality_s13_10M.json` |
| s10_40M | 4 / 4 / 4 | 7.8% / 29.7% / 42.5% | `runs/quality/s10_40M.json` |

> **两个必须知道的坑**：
> ① **tier 的绝对数在 64–96 局上不稳定**：同一代权重换 panel（520000 vs 740000）能读出
> t15 tier≥5 = 50% 或 40%。所以「DPO 0.02 让 t15 tier≥5 **+19.2pp**」只在**同面板配对**
> （64 局 seed 520000，[DPO_UPGRADE.md](DPO_UPGRADE.md) §6.5）里成立，**不能**拿本文这张表去
> 复算或反驳。
> ② **守卫是采样期 mask，不是权重性质**：上面三份 quality 都是 `move_guard=False` 的部署口径，
> 所以「换位/换位回合」仍高达 19.4（s9d）/20.2（s13_10M）——这不是回归，见
> [MOVE_GUARD.md](MOVE_GUARD.md) §8。

### 5.3 人类战团参考强度（`data/real_library/strength_calibration.json`）

| turn | 真实 n | 真实 p50 | 真实 p90 | 我们 p50 | p50 比值 |
|---|---|---|---|---|---|
| 9 | 364 | 546.5 | 1,268 | 305 | 1.79× |
| 10 | 344 | 1,128.5 | 2,948 | 405 | **2.79×** |
| 12 | 230 | 4,458 | 13,288 | 669 | 6.66× |
| 15 | 40 | 26,516 | 170,585 | 1,045 | **25.37×** |

来源：[HUMAN_BOARD_OPPONENT.md](HUMAN_BOARD_OPPONENT.md) §1。

---

## 6. 数据资产清单

| 资产 | 路径 | 规模 | 字段覆盖 | 已知偏差 / 限制 | 用途 |
|---|---|---|---|---|---|
| **准完整人类库（默认训练库）** | `data/real_library/library_real_quasi_full.jsonl` | **1,961 行**（s14 meta `payload_rows=1958`） | golden **46.6%** 帧、关键词 **71.7%**、手牌 **59.2%**、tier **100%**；board 100% | **不可得**：gold、每随从 script counter/gems、attachments/亡语、玩家级 counters/英雄技能、shop、池差量（s14 meta 里 9 个字段每次注入都记 `unavailable`） | s14 训练（`fidelity=full`） |
| **board-only 人类库（评测用）** | `data/real_library/library_real_degraded.jsonl` | 4,284 行（pool 实收 **4,275**） | `turn`/`strength`/`board`/`hero`/`game_id`；`quality=degraded` | 无 tier/gold/hand/counters；**回合末战团被挪到回合初**（对手偏强一点）；`pool_copies=0`（池语义中立）；**混 build 250339/251952/253216/254477** | human 面板（唯一主指标） |
| 原始观测 | `data/real_library/obs/observations/*.jsonl`（376 文件） | **13,120 行**，其中真正的 EOT 帧 **4,498 行** | `perspective=self`，含 `known_hand` | 8,622 行是 `first_attack_after_start_effects`，**不是**回合末帧；多 build 混杂 | quasi_full 的来源 |
| Firestone 近期战团库 | `data/real_library/library_firestone_recent.jsonl` | **10,811 行**（10,806 可用，5 行 `stat_outlier`） | board/tier/hero_hp/main_placement **100%**、hero 97.4%、gold 56.6%、hand 55.2%、placement(self) 56.6%、keywords 75.4%；427/500 局有 `archetype` | feed 只有最近 5 天；**t13–15 样本量远大于准完整库（t14: 511 vs 41）→ 混池会稀释 t14 p50 −40%** | **不作默认库**；只在专门 A/B/N 里用 |
| 混合库（已否决） | `data/real_library/library_mixed.jsonl` | **3,922 行**（quasi 1,961 + firestone 1,177 + degraded 784） | payload 覆盖 **80.0%**（3,138/3,922） | 低信息重复 1,898 行（全来自 degraded）；强度 p50 t5/t10/t15 = 45/1,095/22,739 | 仅 A/B 证据 |
| Firestone 逐动作样本 | `data/firestone_bc/bc_samples.jsonl.gz` | **308,944 条**（MMR≥6000 的 upgrade 子集 3,050 条） | 动作类型/卡/回合；逐动作 | 状态分布 ≠ 自对弈分布（Move logits 量级不可迁移） | BC 辅助正则 / DPO 偏好池 |
| Firestone 原始动作流 | `data/firestone_replays/firestone_recent_actions.jsonl.gz` | **149,166 条**（500 局） | 逐动作 + 局级标签 | 同上 | 流派偏好表、BC 解析 |
| 自采镜像快照库 | `runs/library/snaps_champ` | 由 champion 对局采集 | 整座位状态（含隐藏真值） | **t10 之后偏弱**（t15 p50 只有真实 1/25） | 训练镜像 2 席 p0.2 |
| 强度参考 | `data/real_library/strength_calibration.json` | 按 turn 的真实分位 | p10/p50/p90 + 行数 | 真实 n 随 turn 衰减（t15 只有 40 行） | quality_monitor 分母 |

---

## 7. 待验证问题（open questions，按优先级）

1. **场面强度弱（强度比 ≈3%）**：t15 强度比 0.036 说明「活得久但空板」。是**经济/升本节奏**、
   **购买选择**、还是**对手压力导致的动作预算被换位吃光**？已知 DPO 只把 tier 推到 5，
   强度比几乎不动（0.0357→0.0361）→ tier 与强度**不是同一件事**。
   针对这一缺口的研究方案见 [RESEARCH_PLAN_V2.md](RESEARCH_PLAN_V2.md)（**设计/规格，不是已执行结论**）。

2. **信用分配**：terminal 分量仅 14.6%（边界态）。若改成回合级/分层回报（SMDP），
   **必须**先证明「独立 exam 已能分辨」再预注册 A/B，且不能把回合内优势简单求和
   （[REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §7 备选路线 A）。
3. **信念建模**：当前观测对手块信息有限；注入是「模板对手」不是「会反应的对手」。
   从未验证过 belief/对手建模是否带来收益。
4. **分层结构**（hierarchical policy：先选「升本/买/换位」再选具体）：BC 预训练的 10 类
   分层头在**回放状态**上可行、在**自对弈状态**上崩（[BC_PRETRAIN.md](BC_PRETRAIN.md) §9.4-2）
   → 若要重试，必须做「同分布（on-policy）分层目标」而不是回放 CE。
5. **archetype 硬护栏前提**：软偏置已验证「不退化」，但硬约束（改 mask/强制动作）的 5 条
   前置判据（[ARCHETYPE_BIAS.md](ARCHETYPE_BIAS.md) §10）**一条都没满足**；核心风险是
   「识别错就没有补救数据」。
6. **exam 隔离**：现有 exam 面板只是**新 seed**，源玩家/源对局**未按源组切分**，
   且旧库可能全部被训练看过 → 严格意义上它只能回答「固定旧库上的新 RNG 泛化」，
   **不能声称独立库泛化**（[REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §4.2）。
7. **训练的暴露剂量是否足够**：4.6%→(配置级)41–64% 的提升尚未做过「剂量→面板」的因果 A/B；
   [PRESSURE_AUDIT.md](PRESSURE_AUDIT.md) §3.3 的「先做剂量对齐」仍是建议而非结论。
8. **保真度上界**：真实人类隐藏字段（golden/keywords/counters/gems/attachments）不可得，
   board-only 只会低估压力；「完整状态训练臂」只能用我们自己的快照，**不能冒充真实人类**。

---

## 8. 复现命令（各一条最小命令）

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM
export PYTHONPATH=rust/python:.

# ① 起训练（s14 同配方的最小验证版：5M 决策、单卡、不抢 cuda:3-6）
$PY scripts/train_entity_sync.py --checkpoint runs/az_entity_s13/model.pt --arch entity \
  --device cuda:7 --processes 4 --gpus 7 --threads 8 --games 48 --sims 0 --epochs 1 \
  --minibatch 1024 --grad-accum 8 --amp bf16 --lr 1.2e-6 --clip 0.2 --target-kl 0.02 \
  --lam 0.995 --entropy-coef 0.001 --pi-coef 0.0 --anchor-beta 0.1 --anchor-iterations 200 \
  --anchor-beta-tail 0.02 --compile-train 1 --pipeline 1 --lockstep 1 --leaf-wait-ms 0 \
  --human-board-fast-inject 1 --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2 \
  --archetype-bias-coef 0.5 --archetype-min-prob 0.6 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.2 --mirror-sample p75 \
  --human-boards data/real_library/library_real_quasi_full.jsonl --human-board-fidelity full \
  --human-board-p 0.9 --human-board-seats 5 --human-board-sample auto --human-board-set-tier 1 \
  --seq-coef 0.05 --bc-coef 0.004 --bc-every 4 --bc-compile 1 \
  --dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128 \
  --seed 20100 --eval-every-decisions 5000000 --eval-games 64 --eval-seed-base 420000 \
  --eval-panel human --eval-async 1 --eval-device cuda:7 \
  --stop-at-decisions 5000000 --minutes 120 --out runs/smoke_mem
# ⚠️ 若 s14 在跑，不要再起第二个训练；用 --device cuda:7 且先看 nvidia-smi

# ② 跑评测（512 局 human 面板 = 开发/监控面板；只读 checkpoint，不碰训练状态）
$PY scripts/human_panel_eval.py --checkpoint runs/az_entity_s13/model.pt \
  --games 512 --seats 8 --seed-base 420000 --quantile auto --baseline-bot 0 \
  --device cuda:7 --out runs/eval/human_$(date +%s).json

# ③ 跑质量面板（tier p50 / 强度比 / 出局强度 / 换位）
$PY scripts/quality_monitor.py --checkpoint runs/az_entity_s13/model.pt \
  --games 96 --seed-base 520000 --device cuda:7 --move-guard 1 --move-cap 3 \
  --out runs/quality/quality_s13.json

# ④ 跑 A/B（两臂各 40 iter，同 seed；唯一变量 = 你要测的那一项）
for arm in A B; do
  $PY scripts/train_entity_sync.py --checkpoint runs/ab_firestone_mix/start_model.pt \
    --arch entity --device cuda:7 --processes 8 --gpus 7 --games 192 --sims 0 --epochs 1 \
    --lr 1.2e-6 --clip 0.2 --target-kl 0.02 --lam 0.995 --move-guard 1 \
    --human-boards data/real_library/library_real_quasi_full.jsonl --human-board-fidelity full \
    --human-board-p 0.9 --human-board-seats 5 --human-board-sample auto \
    --dpo-coef 0.02 --bc-coef 0.004 --seq-coef 0.05 --iterations 40 --seed 19100 \
    --out runs/ab_$(date +%m%d)_$arm
done
# 然后同 seed 配对评测两臂（Δmean_rank 的 95% bootstrap CI）
$PY scripts/human_panel_eval.py --checkpoint runs/ab_..._B/model.pt --games 512 \
  --seed-base 420000 --quantile auto --baseline-bot 0 --device cuda:7 --out runs/eval/ab_B.json

# ⑤（可选）独立 exam：4 个不重叠面板 × N ckpt，然后汇总
$PY scripts/exam_paired_eval.py --ckpt s9d=runs/exam/ckpts/s9d.pt \
  --ckpt cand=runs/exam/ckpts/s13_10M.pt --panel-seed-bases 730001,730513,731025,731537 \
  --games 512 --seats 8 --quantile auto --device cuda:7 --out-dir runs/exam
$PY scripts/exam_summary.py --dir runs/exam --out runs/exam/SUMMARY.md
```

---

## 9. 运行态快照（2026-10-31 12:20，**会过期**）

| 项 | 状态 |
|---|---|
| 主训练 | PID **1687244**，`runs/az_entity_s14`，11:15 启动；12:20 时 iter **805** / **22.60M** decisions / 6,577 dec/s（≈19% of 120M） |
| 评测子进程 | `human_panel_eval.py`（20M 点，cuda:7）当时在跑 |
| GPU | 0/1/2/7 有**别的用户**的任务；本项目的 collect 用 3/4/5，learner 用 6 |
| 工作区 | 有未提交改动（`parallel_collect.py`、`ppo.py`、`archetype_bias.py`、`human_obs_full.py`、`human_board_pool.py`、`process_pool.py`、`train_entity_sync.py` + 3 个新 bench 脚本 + 3 个新测试）→ 对应 [PERF_COLLECT.md](PERF_COLLECT.md) 的提速改动 |
| 结论 | **不要重启 s14、不要 kill 1687244 及其子进程**；要 A/B 用 cuda:7 且先 `nvidia-smi` |

---

## 10. 维护规则（谁在什么时候必须改本文）

1. **触发条件**（任一发生即更新）：主指标口径变化 / 新 run 的 human 面板点 / 配方改动并过门禁 /
   新数据资产 / 新证伪结论 / 一次 exam 结论。
2. **只写有来源的数字**：格式 `数字（单位，局数，口径）— 来源路径 §节`。没有来源的估算必须标
   「推算」或「配置级」，不得写成实测（本文 §2.4 就是范例）。
3. **不删历史**：证伪结论进 §3 表格并保留原文档链接；删掉就等于下一个人会重跑一遍。
4. **本文与其他文档冲突时**：现场（`ps`/`latest.json`/`history.jsonl`）> 本文 > 旧设计文档。
   旧设计文档（`AZ_MCTS_SELFPLAY_DESIGN.md`、`AZ_IMPERFECT_SEARCH_DESIGN.md` 等）是**历史设计**，
   不是现状（[AGENTS.md](../AGENTS.md) §5）。
5. 每次大阶段结束，把「本文哪几行改了」写进 [DECISIONS.md](DECISIONS.md) 对应条目。
