# 搜索蒸馏最小实验：learner-DAgger + 优势加权软 ExIt + KL 信赖域

> 状态：**实现 + 端到端跑通 + 关闭/开启搜索的 256 局配对验收**（结论：方向可行，但主判据按字面未通过）。
> 依据：`docs/SEARCH_DISTILL_THEORY.md`（§5 推荐方案）、`docs/INFERENCE_SEARCH.md`（搜索实现与 256 局 A/B）、`runs/infer_search_ab/AB_SUMMARY.json`（起点 checkpoint 的 before/search 两臂）、`runs/search_labels_v2/REPORT.md`（v2 硬 BC 失败口径）。
> 代码：`hsbg/az/train/search_exit.py`（采集 + 蒸馏库）、`scripts/train_search_exit.py`（驱动）。
> 产物：`runs/search_exit/`（`summary.json` / `curves.jsonl` / `samples_r*.npz` / `ckpt_r*.pt` / 面板 json / `run.sh`）。
> 只读主训练：起点是 `runs/infer_search_ab/ckpt_s16b_snapshot.pt`（s16b 冻结快照，sha256 `ce83599e…`），
> **没有**碰 `runs/az_entity_s16b` 的 PPO 循环、没有 kill/重启任何训练；GPU 只用 `cuda:7`（峰值约 2.6 GB）。

## 0. 结论摘要

1. **实现完成并跑通**：`hsbg/az/train/search_exit.py`（DAgger 采集器 + 优势加权软标签 + KL 信赖域训练器）
   + `scripts/train_search_exit.py`（逐轮 采集→搜索→蒸馏→关闭搜索验收），全流程一次跑完 384 局。
2. **主结果**：关闭搜索的 human 256 局配对面板 mean rank **6.375 → 6.258**，**Δ = −0.117**（点估计过 −0.10 线），
   **95% CI [−0.305, +0.066] 上界 > 0 ⇒ 按 §5.4 的硬判据未通过**（n=256 的配对 SE ≈ 0.096）。
   **capture ratio = 0.278**（95% CI [−0.167, +0.722]；阶段目标 0.5 未达）。
3. **四个正向信号**（说明不是「学不进去」，而是「预算/规模不够」）：
   - 优势权重不塌缩：`mean w = 0.57–0.59`，`w ≥ 1e-3` 的状态占 **85–87%**；
   - 熵不坍缩：蒸馏后熵是 ref 的 **1.07–1.17 倍**（v2 硬 BC 的失败模式没有复现）；
   - 搜索增量被保留：`after+search = 5.8906 / top4 17.6%`，**优于** `before+search = 5.9531 / 14.8%`；
   - **机制上学到了东西**：蒸馏目标正好落在 `carrier_or_spell` 决策上，quality 面板显示
     「对载体施法次数」**0.52 → 0.99（+90%）**、载体登场率 +7pp、t12/t15 Σ **+8.1% / +9.0%**，
     human 面板无条件局末 Σ **+9.1%**、t12 存活样本 33 → 42（§3.4）。
4. **两个阻塞原因**（按任务要求归因，见 §4）：
   - **KL 预算粒度**：目标每轮 0.01，但**单个 Adam 步**就能跨 0.01–0.12 的 KL，于是 δ_total=0.05 在
     **2 个有效轮**内被花完（第 3 轮硬锚触发回退并停机）；DAgger 只迭代了 2 次（文档要求 5–10 次）。
   - **规模**：55,856 个 learner 决策 / 6,364 个搜索标签 ≈ 文档 2M 预算的 **1/36**。
5. **能否接进 s17 主循环**：**能，但只能按 §5.2.5 的「10% 辅助蒸馏 batch、每 20 PPO iter 一次」接**，
   不能当独立主循环替代 PPO；接入前必须先补三件事：last-in-budget 回退、梯度累积/更小 lr、
   搜索覆盖率 11% → 25–30%。详见 §5。

## 1. 实现

### 1.1 采集：learner-DAgger（行为恒为 π_base，搜索不动动作）

| 口径 | 值 | 说明 |
|---|---|---|
| 状态来源 | **完整游戏**（Rust `hsbg_engine`），8 seat × 16 局/轮 × 3 轮 = 384 局 | π_base = 当前 learner 的 argmax（`PPOGreedyPolicy`，与 256 局面板同一策略类、同一 `max_actions_per_turn=40`） |
| 对手 | 人类战团注入（`data/real_library/library_real_degraded.jsonl`，`sample=auto`） | 与 `scripts/human_panel_eval.py` 的 256 局面板**同一注入路径**（`EvalConfig.human_board_pool`） |
| 采集 seed | 600000 + 1000·(轮−1) + 32·seat | 与评测面板（420000）**不重叠** |
| 搜索触发 | `--search-when carrier_or_spell`（`carrier_in_shop / carrier_in_hand / spell_in_hand`） | 与 AB 面板同口径；每回合最多 3 次 |
| 搜索 | `infer_search.InferSearcher`：1 回合叶值、top-k 8、非 Move 候选、`pi_mode=advantage`、`adv_clip=30` | **同一份代码**，与 AB 面板的 `--infer-search 1 --infer-search-turns 1` 完全同源 |
| 行为 | **恒为 π_base**（greedy），搜索结果只当标签 | DAgger：状态分布钉在学习者/部署分布上，标签不污染行为（v2 沙盒口径） |

每个被搜索决策记录：`features[3227]`（f16）、`cards[124]`、`legal_mask[245]`、候选动作集 $\mathcal C_k$、
$\pi_{base}$ 在候选上的归一先验 $\tilde p$、$\pi_S$、每个候选的叶分 $\hat Q=L(\Sigma_{end})=\log1p\Sigma/\log1p 30000$、
优势 $\hat A=\hat Q-\sum_b\tilde p(b)\hat Q(b)$、$\tau$、$\sigma_{\rm root}$、动作类型、回合/seat/seed。

### 1.2 损失：优势加权软标签 + KL 信赖域

$$
L(\theta)=\frac{\sum_i w_i\,\mathrm{KL}\!\left(\pi_S^{(1/T)}(a\mid s_i)\,\big\|\,\pi_\theta(a\mid s_i)\right)}{\sum_i w_i}
\quad\text{s.t.}\quad
\mathrm{KL}(\pi_{ref}\|\pi_\theta)\le\delta_{max},\ \ \mathrm{KL}(\pi_{old}\|\pi_\theta)\le\delta_{round}
$$

- **优势权重**（默认 `--weight-mode adv --weight-stat max`）：
  $w_i=\mathrm{clip}(\max_a\hat A(s_i,a)/\tau_A,0,1)$，$\tau_A=1.0\cdot\mathrm{std}_{\tilde p}(\hat Q)$（与 `pi_from_q` 同一 $\tau$）。
  $w_i<10^{-3}$ 的状态**不参与训练**（「搜索没找到更好动作」的决策只作 base 锚点，不产生梯度）——
  这是理论文档 §3.3「无优势加权」失败模式的直接对策。(AWR 口径 `--weight-mode awr` 也已实现：
  $w_a=\exp(\mathrm{clip}(\hat A_a/\tau_A,-2,2))$，损失内逐候选加权；本实验用 adv 口径。)
- **软标签**：$\pi_S^{(1/T)}\propto \pi_S^{1/T}$，$T=2$（§5.2.3 建议值），避免把 top-1 当 one-hot 真值
  （v2 的 `sell/refresh` 先验污染路径）。**注意实现细节**：零概率位必须先判零再取幂，否则
  `clamp(0,1e-12)**0.5 = 1e-6` 会在非法动作（logp≈−1e9）上放大成 ~1e3 的伪 KL（本实现踩过这个坑）。
- **KL 信赖域**：$\pi_{ref}$ = **起点权重**（硬上限 `--kl-anchor 0.05`，超限回退该 epoch 并停止后续蒸馏）；
  $\pi_{old}$ = **本轮起点权重**（每轮预算 `--kl-target 0.01`，每个 minibatch 检查、达到即停）。
  同时记录 `KL_max / p90 / p99`（逐状态最坏值）、熵、动作类型 top-1 份额。
- **训练范围**：`--train-scope policy` —— 只训策略头（`scalar_head / q_buy / q_board / *_bias / pos_play`，
  约 30 万参数），trunk 与价值/辅助头冻结。理由见 §4（全参数训练在 1 个 epoch 内把 KL 推到 0.07–2.7）。
- **优化**：Adam，`lr 1e-5`（与 §5.2.5 一致），batch 256，最多 300 epoch，KL 预算/收敛提前停；
  `--agg-rounds 2`（DAgger 历史标签聚合最近 2 轮）。
- **门禁（触发即回退该 epoch 并停止）**：`KL(π_ref‖π_θ) > 0.05`、`熵 < 0.90×π_ref 熵`、
  `sell/refresh` 的 top-1 份额单轮增幅 `>1.5×`（分母 ≥3% 且计数增量 ≥8 才判，避免 512 状态 probe 的
  计数噪声误触发——初版没有这两个阈值时，`sell` 从 7/512 到 11/512 就误判为 1.5× 门禁）。

### 1.3 记录量（每轮）

`n_states / searched_ratio / kept_ratio / mean_weight / 教师 KL(probe) / KL_to_ref(mean·p90·p99·max) /
KL_to_old / entropy_ratio / teacher_top1_agree / top-1 动作类型份额 / 每轮 128 局关闭搜索配对 Δ 与 capture`。

## 2. 评测协议

| 臂 | 口径 |
|---|---|
| **before（关闭搜索）** | `runs/infer_search_ab/human_base0.json`：起点 ckpt × 256 局（8 seat × 32，seed 420000），`sha256=ce83599e…` 与本实验起点**逐字节相同** |
| **before（开启搜索）** | `runs/infer_search_ab/human_t1.json`：同 ckpt / 同 seed，1 回合 top-8 `pi_argmax`；mean rank 5.953（配对 Δ=−0.422，CI [−0.602,−0.242]） |
| **after（关闭搜索）** | 本实验最终 ckpt，256 局，同 seed/seat，`--infer-search 0` |
| **after（开启搜索）** | 同 ckpt，`--infer-search 1 --infer-search-turns 1 --infer-search-topk 8 --infer-search-when carrier_or_spell --infer-search-action pi_argmax` |
| 每轮子面板 | 128 局 = seats 0–3 × 32 局，seed 420000；与主面板**前 4 个 seat 逐局相同**（自检：起点子面板 mean rank 6.3203 与 AB 面板前 128 局逐位一致，`determinism_vs_AB = True`） |
| 质量面板 | `scripts/quality_monitor.py --games 256 --seed-base 520000 --carrier-audit 1`（t12/t15 Σ、载体率） |

统计：配对 Δ = mean(after−before)，20000 次配对 bootstrap 95% CI。
capture ratio $=\dfrac{\text{rank}_{after}-\text{rank}_{before}}{\text{rank}_{search}-\text{rank}_{before}}$
（before/search 取自同一 ckpt 的 256 局 AB 面板；分子分母逐局配对求和，CI 用配对 bootstrap）。

## 3. 结果

### 3.1 逐步训练曲线（臂 A：δ_total=0.05 的原始口径）

起点 `runs/infer_search_ab/ckpt_s16b_snapshot.pt`（sha256 `ce83599e…`）。每轮采集 128 局（8 seat × 16），
采集 seed 600000+1000·(轮−1)，标签聚合最近 2 轮（`--agg-rounds 2`）。

| 轮 | 采集局 | 搜索状态 | 搜索覆盖率 | 参与训练 | mean w | 教师 KL(probe) 前→后 | KL_to_ref mean | KL_to_ref p99 | KL_max | KL_to_old | 熵比 | teacher agree | 本轮 epoch | 停因 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 128 | 2,065 | 12.0% | 1,746 / 2,065 (84.6%) | 0.570 | 3.700 → 3.431 | 0.0092 | 0.128 | 0.364 | 0.0092 | 1.073 | 0.521 → 0.521 | 2 | KL 预算 |
| 2 | 128 | 2,189 | 11.3% | 3,628 / 4,254 (85.3%) | 0.582 | 3.465 → 3.267 | **0.0360** | 0.445 | 2.407 | 0.0268 | 1.168 | 0.553 → 0.543 | 0（首步跨预算） | KL 预算 |
| 3 | 128 | 2,110 | 10.9% | 3,718 / 4,299 (86.5%) | 0.588 | 3.602 → 3.602 | 0.0335 | 0.440 | 1.226 | — | 1.146 | 0.517 → 0.517 | 0（回退） | **硬锚 0.05 触发** |

- 采集总量：**384 局 / 55,856 个 learner 决策 / 6,364 个被搜索决策**；搜索叶步 **659,017** 次
  （≈0.66M 次网络叶前向）。按决策当量算，这只到 `docs/SEARCH_DISTILL_THEORY.md` §5.2 的 2M 预算的
  **约 1/36**（55.9k / 2M）——本实验是**下界规模**的最小验证，不是完整预算的复现。
- 加权 CE 只在完整 epoch 结束时记录：第 1 轮 epoch0→epoch1 为 **4.722 → 4.609**；第 2/3 轮在 epoch
  中途按预算停下，没有完整的 epoch 行（因此用「教师 KL(probe) 前→后」当拟合进度指标：3.70 → 3.27）。
- **权重没有塌缩**：`mean w = 0.57–0.59`，`w ≥ 1e-3` 的状态占 **85–87%**，说明「搜索真的更优」的
  决策占多数（没有退化成 base 锚点）；同时 13–15% 的状态被正确置零。
- **标签不尖**（相对 v2）：软标签 T=2，被搜索决策上「π_S top-1 与 π_base top-1 不同」的比例约 45–48%
  （与 v2 的 54.7% 同量级）；但 `KL_max` 从 0.36 涨到 2.41，说明**极少数状态**的标签距离仍然很大
  （长尾没消失，见 §4）。
- **熵没有坍缩**：`entropy_ratio = 1.07–1.17`（蒸馏后比 ref 更平），与 v2「尖标签压低熵」相反。
- **KL 预算的执行粒度问题**：目标每轮 `KL(π_old‖π_θ) ≤ 0.01`。第 1 轮 2 个 epoch 走到 0.0092（正常）；
  第 2 轮没走完一个 epoch 就触到「预算已到」（KL 到 0.0268）；第 3 轮首段又把累计 KL 推到
  0.0509 > 0.05 → 硬锚回退整轮并停机。**即：0.05 的总预算在 2 个有效训练轮内就被花完，而不是被 5 轮
  均匀花完。** 两个机制叠加：(i) 新优化器第一步的 Adam bias-correction 让单步跨度特别大；
  (ii) 本版实现里「逐 minibatch 检查」用 512 状态子集、「报告」用 1024 状态子集，两个子集**不嵌套**，
  检查会低估真实 KL（已修：统一用同一个 probe 集合；并新增 `--budget-rollback 1` 把越界的那一步回退，
  见 §5/§6）。

### 3.2 每轮关闭搜索的 128 局配对面板（seats 0–3 × 32 局，seed 420000）

before 子面板 mean rank **6.3203**（与 AB 面板前 128 局逐位一致），开启搜索的 before 子面板 **5.9609**
（capture 分母 −0.3594）。

| 轮 | mean rank | Δ vs before | 95% CI | 配对捕获比例 capture |
|---|---|---|---|---|
| before | 6.3203 | — | — | — |
| 1 | 6.2031 | −0.1172 | [−0.3672, +0.1250] | 0.326 |
| 2 | 6.1641 | −0.1562 | [−0.3984, +0.0859] | 0.435 |
| 3 | 6.1641 | −0.1562 | [−0.3984, +0.0781] | 0.435 |

（第 3 轮硬锚回退，权重等于第 2 轮，故面板数字相同。）128 局的配对 SE ≈ 0.12，**单轮 Δ 的 CI 都跨 0**，
逐轮数字只能看趋势（0.33 → 0.44），不能当验收。

### 3.3 最终 256 局面板（8 seat × 32，seed 420000，逐局配对）——主判据

| 臂 | mean rank | top4 | Δ vs before（配对） | 95% CI | 说明 |
|---|---|---|---|---|---|
| before（关闭搜索） | 6.3750 | 10.16% | — | — | `runs/infer_search_ab/human_base0.json`（同 ckpt/sha256） |
| before（开启搜索，1 回合 top-8） | 5.9531 | 14.84% | −0.4219 | [−0.6016, −0.2422] | `runs/infer_search_ab/human_t1.json` |
| **after（关闭搜索）** | **6.2578** | 9.77% | **−0.1172** | **[−0.3047, +0.0664]** | 本实验最终 ckpt（= 第 2 轮权重） |
| after（开启搜索，1 回合 top-8） | 5.8906 | 17.58% | −0.3672（vs after 关闭搜索） | [−0.5391, −0.1953] | 同 ckpt，搜索仍继续加成 |

- **capture ratio = 0.278，95% CI [−0.167, +0.722]**（配对 bootstrap 20000；分母
  mean(rank_search−rank_before) = −0.4219 是**负数**，CI 由逐局配对重采样得到），
  即推理期搜索带来的 −0.422 名次改进里，策略**在关闭搜索时**学回了 **27.8%**（阶段目标 50% 未达；
  CI 宽是因为 n=256 时 rank 的配对方差大，capture 的分母只有 −0.42）。
- 关掉搜索的 Δ = **−0.117 ≤ −0.10**（点估计过线），但 **95% CI 上界 +0.066 > 0 ⇒ 主判据按字面未通过**
  （n=256、配对 SD≈1.53、SE≈0.096；要 CI 上界 < 0 需要 Δ ≲ −0.19）。逐局符号：36.3% 变好 / 32.0% 变差（其余持平）。
- **搜索增量没有被蒸馏吃掉**：after+search 5.8906 比 before+search 的 5.9531 还低 0.06，且
  within-policy 的 search−nosearch 增量（−0.367）与 before 的（−0.422）同量级 ⇒ 蒸馏学到的是
  「搜索优势里可被策略内化的那部分」，剩下的仍然要靠推理期搜索。after+search 的 top4 = **17.58%**
  （before+search 14.84%、before 10.16%），是本实验最强的配置。

### 3.4 强度/存活/载体（quality 面板与 human 面板的 Σ 轨迹）

**(a) human 256 局面板的 Σ 轨迹**（`trace_summary`，同一批 seed/seat；Σ = 战团 atk+hp 求和）

| 指标 | before（关搜索） | **after（关搜索）** | after（开搜索） |
|---|---|---|---|
| t12 存活样本 n | 33 | **42（+27%）** | 66 |
| t12 Σ start p50（条件） | 824 | 742 | 891 |
| t12 Σ end p50（条件） | 963 | 805 | 1,054.5 |
| t9 / t10 / t11 Σ end p50（**无条件**） | 349 / 482.5 / 625 | 363 / 508.5 / 653.5 | 431.5 / 602.5 / 810 |
| 局末 Σ p50（**无条件**） | 443.5 | **484（+9.1%）** | 660.5 |
| 局末 Σ mean（无条件） | 503.6 | 525（+4.2%） | 721.7 |
| t15 样本 n | 0 | **0** | 0 |

**(b) quality_monitor**（`--games 256 --seed-base 520000 --carrier-audit 1`，selfplay vs 引擎 bot；t12/t15 在这里**有样本**）

| 指标 | before | after | 变化 |
|---|---|---|---|
| mean_rank（vs bot） | 2.043 | **1.973** | −0.070 |
| top4 | 94.9% | 96.9% | +2.0pp |
| **t12 Σ p50** | 553 | **598** | **+8.1%** |
| **t15 Σ p50** | 779（n=172） | **849**（n=153） | **+9.0%** |
| survive_t12 | 97.3% | 96.9% | −0.4pp（噪声内） |
| learner_turn_p50 | 15 | 15 | 0 |
| 载体登场率（局级） | 48.4% | **55.5%** | +7.1pp |
| 载体 t9 / t12 上场率 | 28.5% / 37.1% | **33.6% / 43.4%** | +5.1 / +6.3pp |
| 载体在场回合数 mean | 1.95 | **2.37** | +21% |
| **对载体施法次数 mean** | 0.520 | **0.988** | **+90%** |
| r(载体回合数, Σ₁₂) | 0.086 [−0.033, 0.216] | −0.007 | 噪声内（CI 本就很宽） |
| 墙钟 | 526 s | 506 s | — |

两条结论：(i) 训练**没有**让强度/存活退化——human 面板的无条件局末 Σ +9.1%、t12 存活样本 +27%，
quality 面板 t12/t15 Σ +8.1%/+9.0%；(ii) **机制上确实学到东西了**：蒸馏目标正好落在
`carrier_or_spell` 决策上，而「对载体施法次数」几乎翻倍（0.52 → 0.99）、载体登场率 +7pp，
这就是 §3.3 里「搜索增量被部分内化」的物理来源。

口径提醒：**t15 在 256 局 human 面板上仍然 0 局**（before/after 都是 0 个样本），t15 只能由沙盒口径给出；
t12 的**条件**分位（只统计活到 t12 的局）在策略变强后会下降（存活者变多、把中位数拉低），所以主看
**无条件**指标：`last_turn_sigma`（局内最后一次决策的 Σ，不受存活条件限制）与 `per_turn_end` 的 t9–t11。

### 3.5 臂 B（把 δ 抬到 0.25 的负对照）：单步过大 ⇒ 策略退化

动机：本实验的 KL 是在**被搜索状态**（占全部决策 11–12%）上测的，等价到「整局所有决策」的平均 KL
只有 `0.036 × 0.115 ≈ 0.004`，比 `docs/SEARCH_DISTILL_THEORY.md` 的 δ=0.05 低一个量级。所以又跑了一个臂：
从第 2 轮 ckpt（KL 0.036）续训，硬锚抬到 0.25（整局等价 ≈0.029）、每轮预算 0.06，96 局/轮。

| 轮 | 搜索状态 | KL_to_ref | KL_max | 熵比 | 128 局 mean rank | Δ vs before | capture |
|---|---|---|---|---|---|---|---|
| 3 | 1,607 | **0.1561** | 4.56 | 1.389 | 6.4688 | **+0.1484** | **−0.413** |

**这不是「δ 越大越好」的反例，而是「预算粒度」的反例**：抬锚后第一个 Adam 步又把 KL 从 0.036 一步推到
0.156（远超每轮 0.06 的预算），策略熵升到 ref 的 1.39 倍，128 局 Δ 反而 +0.148（capture −0.41）。
即**在「一步就能跨 0.12 KL」的优化器粒度下放大 δ，等于关掉信赖域**；要用更大的 δ，必须先做 §4 的
「last-in-budget 回退 + 更小 lr/梯度累积」。

## 4. 归因：为什么 capture 只有 0.28、CI 跨 0

| 候选失败原因 | 本实验的证据 | 判定 |
|---|---|---|
| **权重塌缩**（搜索优势被稀释成均匀权重） | `mean w = 0.57–0.59`，`w≥1e-3` 占 85–87%，被置零的 13–15% 是「搜索没找到更好动作」 | **未发生** |
| **标签尖**（one-hot/高峰标签污染先验） | 软标签 T=2；`KL_max` 0.36→2.41、p99 0.13→0.44；`sell` 份额 1.8%→2.8%（1.56×ref，接近 1.5× 门限但未触发，计数太小） | **部分存在**：长尾状态（π_base 给教师动作 ~1e-4 概率）吃掉了大部分 KL 预算，却学不动 |
| **容量**（策略头/trunk 装不下条件化的搜索偏好） | 只训策略头（30 万参数）；`train_scope=all` 时**一个 epoch** 把 KL 推到 0.07（lr 1e-5）/0.67（3e-5）/2.7（1e-4），trunk 对 2k 条标签过度敏感 | **未证伪**：要测容量必须先把步长做细，否则第一步就出域 |
| **KL 预算粒度**（本实验真正的主因） | 单步/单 epoch 片段跨 0.01–0.12 KL（第 2 轮 0.027、臂 B 0.12）；每轮 0.01 预算实际只够「一步」；δ_total=0.05 在 2 轮内耗尽 | **主因** |
| **规模/DAgger 轮数** | 55.9k 决策、2 个有效轮、6,364 个标签（文档：2–5M 决策、5–10 轮；规模 ≈1/36）；capture 从 0.33→0.44 只跨了 0.027 的 KL | **次因**（规模 ≈1/36，按文档预算应是 8 轮以上） |
| 前四率没有同步改善 | top4 9.77% vs 10.16%（−0.4pp，噪声内）；改善集中在「中游→中上游」 | 与「搜索优势主要是尾部救火」一致 |

## 5. 结论与下一步

**结论（一句话）**：learner-DAgger + 优势加权软 ExIt + KL 信赖域**能跑、不崩、方向对**，
在「2 个有效轮 + δ_searched=0.036（整局等价 0.004）」的极小预算下把搜索改进学回了 **27.8%**
（点估计 Δ=−0.117，CI 上界 +0.066），但**按 §5.4 的硬判据（CI 上界 < 0）未通过**；
阻塞点是 **KL 预算的执行粒度 + 规模**，不是权重塌缩、熵坍缩或标签尖。

**是否接进 s17 主循环**：**接，但按文档 §5.2.5 的「辅助蒸馏」形态**，不要用独立 ExIt 主循环替代 PPO：

1. `L = L_PPO + 0.25·L_AW-ExIt + 0.10·KL(π_old‖π_θ)`，蒸馏 batch 占 10%，每 20 个 PPO iter 一次，
   `lr ≤ 1e-5`，只训策略头（trunk 保持 PPO 的梯度来源，避免 2k 条标签污染表示）；
2. 每轮 δ_round = 0.01（**在被搜索状态上**测，等价整局 0.001–0.002），hard anchor 0.05；
3. 采集覆盖率 11% → 25–30%（`carrier_or_spell,tier4plus` 或每回合上限 5），按 80% base / 20% 搜索标签混合。

**必须先补的三件工程改动**（按优先级）：

1. **last-in-budget 回退**：在 `ExitTrainer.fit` 里只快照可训练参数（~1.2 MB），每步后用
   `KL(π_old‖π_θ)` 检查；超预算就把上一步回退掉再停。这样每轮 0.01 的预算能用 5–10 步花完，
   而不是 1 步跨过去（本版只在 epoch 级回退，是第 2/3 轮 overshoot 的直接原因）。
   **已实现**（`--budget-rollback 1`，默认 0 保持与本节数字一致），差的是「打开它 + 重跑 8 轮」的验证。
2. **梯度累积 + lr 3e-6**：把「一次 KL 台阶」从 0.01–0.12 压到 ~0.002，同时保持同样的数据量。
3. **频次门禁变强**：`sell/refresh` 的 top-1 份额按「每轮相对 π_old + 累计相对 π_ref」双口径报，
   计数 ≥8 且份额 ≥3% 才判（已实现）；round 3 的 `sell` 已到 1.56×ref，需要盯住。

**若要在离线里把 capture 推到 50%**：8 轮 × 128 局（≈46 min 采集）+ 细粒度预算（`δ_round=0.01`），
按本轮 capture 的 KL 斜率（+0.027 KL → +0.11 capture）外推，需要 **δ_searched ≈ 0.05–0.08**（整局等价
0.006–0.009，仍在文档 δ=0.05 之内，因为分母是 11% 覆盖率），即 5–8 轮。**这是下一步最省算力的路径**：
不改算法、不改标签，只改预算粒度 + 轮数。

## 6. 复现

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
# 臂 A（δ_total=0.05，3 轮 × 128 局；约 55 min，含 3 次 128 局面板 + 256 局收尾 + quality）
bash runs/search_exit/run.sh
# 臂 B（δ 抬到 0.25 的负对照，96 局/轮；从臂 A 的第 2 轮 ckpt 续训）
bash runs/search_exit_v2/run.sh
```

产物：`runs/search_exit/summary.json`（全部曲线/面板/门禁）、`curves.jsonl`（逐轮一行）、
`samples_r00{1,2,3}.npz`（6,364 条搜索标签，可直接重放不同 δ / 温度 / 权重口径而不必重跑搜索）、
`ckpt_r00{1,2,3}.pt`（每轮权重）、`eval_r00*_nosearch.json` / `final_nosearch.json` /
`final_search.json` / `quality_*.json`（面板原始数据）。

**版本说明（重要）**：上面的 A/B 两个臂是用 `search_exit.py` 的**初版**跑的（逐 minibatch 检查用
512 状态子集、只有 epoch 级回退）。之后代码做了两处修正但不影响已产出数字的解读：
(1) 检查与报告统一用同一个 probe 集合；(2) 新增 `--budget-rollback 1`（默认 0 = 初版行为）。
采集/标签/面板口径**没有变**，所以新版本可以直接用 `--rounds-done ... --resume-from ...` 或
在已保存的 `samples_r*.npz` 上重放（`ExitTrainer.fit(samples)`），不必重跑 2.7 s/局的搜索。

单测：`PYTHONPATH=rust/python:. python -m pytest tests/test_az_search_exit.py -q`（15 项全绿，覆盖
优势权重口径、软标签零支撑、npz 往返、KL 预算提前停、硬锚回退、last-in-budget 回退、样本过滤、配置校验）。
