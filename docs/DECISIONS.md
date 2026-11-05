# DECISIONS — 配方决策流水

> 规范见 [AGENT_TEAM.md](AGENT_TEAM.md) §2。**一改一记**：任何改变训练语义的动作（奖励、对手分布、
> aux loss、动作 mask、评测口径、默认库/默认 checkpoint）都必须在这里留一条。
>
> 说明：D-20261028 ～ D-20261031-06 是**回填条目**（2026-10-31 依据 `docs/*.md`、`runs/*/summary.json`、
> `git log` 重建），字段按规范补齐，但「预注册判据」是**事后如实标注**（当时是否预注册已在条目里写明）。
> 新条目请用同一格式，并在 `状态` 里写 生效 / 已回退 / 观察中 / 不采纳。

---

## D-20261028-01 · 对手分布从「纯引擎 bot」改为「镜像快照 + 人类战团注入」

- **日期**：2026-10-28（commit `62613ca` 人类战团注入 + `5884f1a` 镜像注入）
- **状态**：生效（后续所有 run 的默认）
- **动机**：7 席全是同一个脚本 bot → advantage 近似零均值噪声；bot 在 t9 之后强度锁在 tier≈4，
  真实 10k+ 是它的 3–13 倍。论文侧也指出「校准对手库是最大单项收益」。
- **改动**：训练大厅由「learner + 7 bot」改为「learner + 2–3 席镜像快照 + 2–3 席人类战团 + 其余 bot」；
  新增 CLI `--mirror-seats/--mirror-p/--mirror-sample`、`--human-board-seats/-p/-sample/-set-tier`。
- **A/B**：无（属于训练世界重构，不是单变量实验）；对照是 s5/s6 的 bot-only 曲线。
- **数字**：bot 面板从 C0 2.279（s4 末）→ 1.768（s6 末，top4 97.1%）；human 面板当时尚无（后补）。
- **结论**：采纳。**但这次改动没有单变量证据**，后续所有「变强」都混着对手分布变化，写报告时必须声明。
- **是否回退**：不回退。回退方式 = `--mirror-seats 0 --human-board-seats 0`（等价纯 bot）。
- **链接**：[HUMAN_BOARD_OPPONENT.md](HUMAN_BOARD_OPPONENT.md) §1–§2、[MIRROR_SNAPSHOT_DESIGN.md](MIRROR_SNAPSHOT_DESIGN.md)、[STAGE6_REPORT.md](STAGE6_REPORT.md)

---

## D-20261030-01 · 关闭势函数奖励塑形（`--shaping-coef 0`）

- **日期**：2026-10-30（文档 20:07，commit `900911b` 修 γ bug + `5028642` 第二批 A/B）
- **状态**：生效（s10 起 `shaping_coef=0.0`）
- **动机**：s8b/s9d 训练时 `shaping_coef=1e-3`，但塑形项逐决策 |F| 的 p50 是名次效用全距的
  **7.5×**，截断局尖峰可达 10³；同时怀疑「塑形把 value 目标换掉了」。先修 γ 不一致的 P0 数学 bug。
- **改动**：`--shaping-coef 1e-3 → 0`；修 `reward_shaping` 的折扣，使其与训练 γ 对齐（`bias_sum=0`）。
- **A/B**：两批，各 60 iter（≈1.6M decisions），同起点同 seed 面板，唯一变量 = 塑形开关；
  第一批 seed 15100，第二批独立 seed 23200。
- **数字**：human 配对 Δ(B−A) = **−0.208 [−0.427, +0.010]**（批 1）/ **−0.035 [−0.194, +0.125]**（批 2）；
  bot Δ **+0.094** / **−0.016**（符号相反）；adv_std 0.27 → 0.85 / 1.90；两批 t15 tier p50 都是 A 更高。
- **结论**：**采纳关闭**。γ 对齐修复本身成立（整局偏置 29%→0），但「γ 对齐的塑形」相对关闭
  **没有可测收益**；λ=1e-3 的量级不可接受。
- **是否回退**：不回退（若要保留稠密信号，λ 必须降到 2e-5~5e-5，见文档 §10.2）。
- **链接**：[REWARD_SHAPING.md](REWARD_SHAPING.md) §10.3

---

## D-20261030-02 · 启用换位去抖守卫，**不**启用换位双投影头

- **日期**：2026-10-30（commit `e45f84e`）
- **状态**：生效（`--move-guard 1 --move-cap 3 --move-repeat-limit 2 --move-head-split 0`）
- **动机**：换位动作被连按，打满每回合 40 动作上限；24.6% 的换位回合**净盘面不变**（纯空转），
  白白消耗决策预算并反复强化 Move 的 logprob。
- **改动**：采样前改写动作 mask（逆换位屏蔽 / 同 `(from,to)` 重复上限 / 每回合 cap），
  只动 196..244 段；默认关闭，关闭时逐位等价。同时测了 `--move-head-split 1`（有向双投影）。
- **A/B**：三臂 A(全关) / B(guard+split) / C(只 guard)，各 40 iter ≈1.1–1.4M decisions，
  从 s9 起、同 seed 14100；human 96 局 + bot 64 局配对。
- **数字**：C−A human **−0.042 [−0.198, +0.115]**、bot −0.109 [−0.453, +0.234]；
  B−A human **+0.510 [+0.229, +0.792]**、bot +0.891（显著劣化，归因是随机初始化的 split 头 entropy 1.06 未训够）；
  guard=1 评测下换位/换位回合 19.91→2.31、空转 24.6%→3.8%。
- **结论**：采纳 **C**（只开守卫）。**明确否决 `--move-head-split`**。
- **是否回退**：不回退；`--move-guard 0` 即逐位回到旧行为。
- **链接**：[MOVE_GUARD.md](MOVE_GUARD.md) §7.3–§8

---

## D-20261030-03 · tier-target 奖励**不启用**（保持默认 0）

- **日期**：2026-10-30（commit `7dcc41c`）
- **状态**：不采纳（默认关闭保留）
- **动机**：`quality_monitor` 显示 turn≥9 的 learner tier p50 恒为 4，真实 10k+ 会到 5–6；
  想用「定向目标曲线」把升本节奏注入策略（势函数塑形按设计改不了最优策略）。
- **改动**：实现 `--tier-target-coef`（默认 0），惩罚/奖励加在「回合第一条 decision」。
- **A/B**：A(0) / B(推荐 coef=1) / C(敏感性 coef=10)，各 40 iter ≈1.6M decisions。
- **数字**：B 与 A **完全一致**（t9/t12 tier p50 都是 4，tier≥5 25.8% vs 28.1%，训练内通过率 40 iter 持平 ≈5%）；
  C 证明通路有效（t12 tier≥5 28%→50%、t15 55%→79%）但 human 面板无改善（6.79 vs 6.48，噪声内）。
- **结论**：不采纳。**通路通、收益无**；短板是信用分配（惩罚加在错误的 decision 上），不是系数。
- **是否回退**：不适用（从未进主线）。若重试：改到回合末/分摊到全回合，或直接给 upgrade 正奖励，
  且预算 ≥300 iter。
- **链接**：[TIER_TARGET.md](TIER_TARGET.md) §7–§8

---

## D-20261030-04 · 把 upgrade 子集 DPO（0.02 / every 1）并入主线

- **日期**：2026-10-30（commit `9eb7cf3`）
- **状态**：生效（s10 起 `--dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128`）
- **动机**：离线诊断显示「该升不升」集中在 t9/t12（tier4 且应升本时选 upgrade 只有 25%/13%）；
  但纯 DPO 30 步就饱和到 99.9% → 必须小系数。
- **改动**：把 upgrade 子集 one-sided DPO 接进 PPO step；默认 `coef=0` 逐位等价。
- **A/B**：A(0) / B(0.002,every4) / C(0.005,every4) / **D(0.02,every1)**，40–60 iter；
  池上 probe（3,050 条）+ 64 局 quality + 96 局 human 配对。
- **数字**：B/C 是**噪声平台**（picks_upgrade −0.9pp/+0.5pp，1σ≈0.84pp，不单调）；
  **D**：picks_upgrade 69.05%→**77.7%**（+8.6pp≈10σ）、t9/t12 should 组 +15.1/+13.1pp、
  tier≥5@t12 **+8.9pp**、**@t15 +19.2pp**、t15 tier p50 4→5；human Δ −0.042、bot Δ −0.016（容差 +0.15 内）。
- **结论**：采纳 D。**t9 的 tier≥5 没升是滞后指标**（t9 的 tier 由 t7/t8 决定），
  判据要按「下游 turn」读。
- **是否回退**：回退 = `--dpo-coef 0`。失效判据：t12/t15 tier≥5 不升 / human Δ>+0.15 /
  bot Δ>+0.15 / picks_upgrade>90% / accept_rate<10% / loss 20 步不动。
- **链接**：[DPO_UPGRADE.md](DPO_UPGRADE.md) §6.5–§7.2

---

## D-20261030-05 · **否决** BC 预训练 warm-start（含 Move 族监督）

- **日期**：2026-10-30（commit `7fd33b1`）
- **状态**：不采纳（s11 未采用；主线只保留 `bc_coef=0.004` 辅助正则）
- **动机**：BC 能把 tier 修好（t12 tier≥5 25%→58%）但强度/胜率崩；怀疑根因是 Move(196..244)
  完全不在分层 BC 监督范围内（moves/turn 2.4→17.3）。
- **改动**：把 `reposition` 做成第 10 类 + 可选 Move 段 MSE 锚定（默认关闭）。
- **A/B**：8 个配置（s8b 原权重 / A 9 类 / B +reposition / C +anchor 0.1 / D lr2e-5 /
  E D+anchor0.01 / F B+anchor0.01 / 参考 9 类@lr2e-5），各 20k 样本 200 步，48 局质量面板。
- **数字**：判据（top4≥85% & 出局强度≥600 & tier≥5@t12≥45%）**8 行全部不满足**；
  最好 F 只有 top4 **41.7%** / 强度 **118**；C 把 moves 压到 5.3 但 tier≥5@t12 掉到 8.9%、强度 22。
  Move 概率质量确实压得住（20.9%→5.8%），但**回放状态分布 ≠ 自对弈分布**。
- **结论**：不采纳。BC 只能当**小权重辅助正则**（0.004/every4），不能做 warm-start 起点。
- **是否回退**：不适用。重试前提：在 on-policy 状态上做 Move 正则 / 冻结 board-token 参数 / 先归一化 logits 尺度。
- **链接**：[BC_PRETRAIN.md](BC_PRETRAIN.md) §9.3–§9.4

---

## D-20261031-01 · 人类战团**剂量跳档**（2 席 p0.3 → 5 席 p0.9）+ 镜像减席（s12）

- **日期**：2026-10-31（s12 启动，`seed 18100`）
- **状态**：生效（s12/s13/s14 同剂量）
- **动机**：压力审计证明「注入→压力」极强（+63.7…+72.5pp），但**暴露只有 4.59%/learner-turn**
  （每局 4.67 条），而 human 面板是 100%/turn × 7 席 → 训练分布与主指标差一个数量级。
- **改动**：`--human-board-seats 2→5`、`--human-board-p 0.3→0.9`、`--mirror-seats 3→2`、
  `--mirror-p 0.3→0.2`；库仍是 `library_real_degraded.jsonl`（board-only）。
- **A/B**：**不是**单变量 A/B——s12 相对 s10 同时改了剂量与镜像席位（诚实标注）。
  可用的近似对照：s10@40M 6.402 / s10@50M 6.471 vs s12@20M 6.344；独立 exam n=2048：
  s12_20M Δ vs s9d **−0.0894 [−0.1436, −0.0342]**。
- **数字**：配置级暴露 ≈(5/7)×0.9 = **64%**（扣除 `pending_choice` 拒绝后 ≈41%）；human −0.09。
- **结论**：采纳（s12/s13/s14 沿用）。**但「剂量 → 面板」的因果仍未被单独检验**——
  这是 [PROJECT_MEMORY.md](PROJECT_MEMORY.md) §7-7 的 open question。
- **是否回退**：不回退。回退 = `--human-board-seats 2 --human-board-p 0.3`。
- **链接**：[PRESSURE_AUDIT.md](PRESSURE_AUDIT.md) §3.4、[runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md) §3

---

## D-20261031-02 · 换用准完整库 + `--human-board-fidelity full`（s13）

- **日期**：2026-10-31（s13 启动，`seed 19100`；依据文档 03:27）
- **状态**：生效（s13/s14）
- **动机**：board-only 注入**系统性低估**压力（对手更弱）。FIDELITY 审计在 460 帧可信完整快照上
  量化了缺口，并确认「准完整可得字段」能补回一部分（counters 档 +2.62pp combat / +1.36pp pipeline）。
- **改动**：`--human-boards data/real_library/library_real_quasi_full.jsonl` + `--human-board-fidelity full`
  （= board + hand + 真实可得 counters + tier；gold/gems/attachments/player counters/shop 仍不可得）。
- **A/B**：**无训练 A/B**（保真度差异是在固定快照上做的配对反事实审计，不是训练臂）。
- **数字**：s13@10M 6.344 → 后续 6.26–6.31；与 s12（board-only）**在 CI 内不可区分**
  （exam：s12_20M −0.0894 vs s13_10M −0.1069，两者相差 −0.0176 [−0.0752, +0.0410]）。
- **结论**：采纳（机制正确、代价可忽略 ≈0.62 ms/座位）。**但要如实写**：fidelity=full **不是**
  真实完整状态，收益是「把下界抬高 1–2pp」，不是 rank 收益。
- **是否回退**：回退 = `--human-board-fidelity board` + 换回 degraded 库。
- **链接**：[FIDELITY_INJECTION.md](FIDELITY_INJECTION.md) §4、[PRESSURE_AUDIT.md](PRESSURE_AUDIT.md) §2.7

---

## D-20261031-03 · **否决** Firestone 混池作为默认训练库

- **日期**：2026-10-31（文档 08:13）
- **状态**：不采纳（s14 继续用 quasi_full）
- **动机**：Firestone 近期库 t13–15 样本量远大于准完整库（t14: 511 vs 41），想补后期强度分布。
- **改动**：新增 `data/real_library/library_mixed.jsonl`（quasi 1,961 + firestone 1,177 + degraded 784 = 3,922 行，
  payload 覆盖 80.0%）+ `scripts/mix_human_libraries.py`；A/B 唯一变量 = `--human-boards`。
- **A/B**：A(quasi_full) / B(mixed)，各 40 iter ≈1.1M decisions，同起点 s13 冻结副本
  （sha `c9438767…cc160`）、同 seed 19100；human 144 局（主）+ 512 局（补充）+ bot 128 局 + quality 64 局。
- **数字**：human Δ(B−A) = **+0.0625 [−0.132, +0.236]**（144）/ **+0.0684 [−0.031, +0.172]**（512）；
  bot +0.0703；t12 强度比 −0.0006、t15 **−0.0051**；**t14 p50 腰斩 −40%**、t13/t14 p90 −11~17%。
- **结论**：不采纳。混池**稀释 t14**，且 512 局 CI 下界 −0.031 已排除「改善 ≥0.10」。
- **是否回退**：不适用。若再试：只在「高回合上限补充」小权重（<0.1）下另开预算足够的 A/B。
- **链接**：[FIRESTONE_MIX_AB.md](FIRESTONE_MIX_AB.md) §0、§3–§5

---

## D-20261031-04 · 大样本 exam（32,768 配对 / 65,536 局）降级为「4×512 独立面板 n=2,048」

- **日期**：2026-10-31（`runs/exam/` 06:13 完成；预注册文档 05:01）
- **状态**：生效（exam 结论已作为 s14 的决策依据）
- **动机**：6.344 vs 6.445 的 0.101 差异小于单模型 SE，无法区分「真改善 / 选点偏差 / 噪声」。
  预注册文档给出 32,768 配对（65,536 局）的正式方案。
- **改动**：实际执行 **6 个冻结 ckpt × 4 个不重叠 512 局面板（730001/730513/731025/731537）
  = 12,288 局 / n=2,048 配对**，簇 bootstrap（panel,seat）；**开发面板 420000 不参与**。
- **A/B**：这是评测协议实验，不是配方 A/B；主比较 = 冻结候选 vs s9d。
- **数字**：s10 −0.0576 [−0.1118,−0.0044]、s12_20M −0.0894 [−0.1436,−0.0342]、
  s13_10M −0.1069 [−0.1660,−0.0459]、s13_20M −0.1035 [−0.1714,−0.0356]；
  但 6.344 vs 6.430 的差距在 exam 上是 **+0.0034 [−0.0654,+0.0737]**；6 ckpt Spearman ρ=+0.55。
  n=2,048 的 80% 功效 MDE = **0.0898** ≈ 目标 0.101。
- **结论**：**采纳降级**——用 2,048 配对（52 min 墙钟）而不是 65,536 局；理由是 MDE 已≈目标效应，
  再扩样本只会在「0.1 名次」量级上继续买精度，运营成本（数 GPU·小时）不划算。
  **同时确认：开发面板的细粒度排序不可复现，只有配对差可复现。**
- **是否回退**：不回退。若要把「≥0.10 改善」写进结论，仍需按 [REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §4.3 扩容。
- **链接**：[REVIEW_PLATEAU.md](REVIEW_PLATEAU.md) §4、[runs/exam/SUMMARY.md](../runs/exam/SUMMARY.md) §9

---

## D-20261031-05 · archetype 软偏置 0.5 进 s14 主线（默认仍关闭）

- **日期**：2026-10-31（commit `8c61cb6`）
- **状态**：生效（s14 用 `--archetype-bias-coef 0.5 --archetype-min-prob 0.6`）
- **动机**：用户诉求「遇到固定流派时按该流派人类范式打」；硬约束风险大（识别错没有补救数据），
  先做「只加不减、不屏蔽」的 logit 偏置。
- **改动**：两段式分类器（流派 / 种族族回退）+ 运行时 `logits += bias`（bias≥0，min_prob 门控）；
  默认 `coef=0` 时零键零开销、逐位等价。
- **A/B**：三臂 A(0) / B(0.5) / C(1.5)，各 40 iter ≈1.1M decisions，同起点 s13、同 seed、评测关偏置；
  human 144 / bot 128 / quality 64 三个量具。
- **数字**：命中 24.2% / 应用 14.7%，coef=0.5 只在 **6.1%** 的被偏置决策上改变 greedy；
  B：human 6.257→**6.194**（top4 10.4→11.1%）、c0 1.953→**1.852**、quality 1.984（略差）；
  C：quality tier/强度最好但 human top4 6.2%（−4pp，1.6σ，不显著）。
- **结论**：采纳 **0.5**（保守、可随时关、与其他 shaping 正交）；**不采纳 1.5**（需 ≥300 iter 才能判）。
  **硬护栏不做**（5 条前置判据一条未满足）。
- **是否回退**：回退 = `--archetype-bias-coef 0`。
- **链接**：[ARCHETYPE_BIAS.md](ARCHETYPE_BIAS.md) §7–§8

---

## D-20261031-06 · 采集侧提速（`--human-board-fast-inject 1 --leaf-wait-ms 0`）进 s14

- **日期**：2026-10-31（文档 11:10；s14 11:15 重启时启用）
- **状态**：生效
- **动机**：注入占采集侧 Python 时间的 58%（2.57 s / 4.46 s），其中 JSON 编解码占 81%；
  `leaf-wait-ms 1.0` 在 lockstep 单客户端下是纯等待。
- **改动**：注入视图缓存 + orjson + `ended_turn` 位替换；`--leaf-wait-ms 1.0→0`；
  `--archetype-cache` **保持 0**（实测命中率 0%）；`--games` **保持 192**（见下）。
- **A/B**：CPU 单进程锁步 A/B（32 局 × 3 iter，冻结 ckpt）+ 真实 s14 折算；
  **并做逐位校验：A/B/C 三配置 records sha 相同**。
- **数字**：注入 1.41→0.43 ms/座位（−69%）；wall −14.4%；collect Python 侧 −42%；
  dec/s +19%（CPU 场景）；s14 实测从 6,528 → **7,747 dec/s**（collect 中位），端到端 6,580。
- **结论**：采纳两项。**`--games 256` 不采纳**（采集 +26% 但 PPO 翻倍，端到端不变，且改训练语义）。
- **是否回退**：回退 = `--human-board-fast-inject 0 --leaf-wait-ms 1.0`（零代码改动）。
- **链接**：[PERF_COLLECT.md](PERF_COLLECT.md) §0、§7、§9

---

## D-20261104-01 · Phase-2 续训标准：`--checkpoint` + `--trainer-state`（精确续训）

- **日期**：2026-11-04（本轮 B01 启动，`runs/az_entity_s73`）
- **状态**：生效（Phase-2 起）
- **动机**：历史链 `chain_300m.sh` 只传 `--checkpoint`，而该参数仅恢复 `model + meta(norm)`
  （`scripts/train_entity_sync.py:2821-2824`）；optimizer/Adam、scheduler/updates、RNG 全部重置
  ⇒ 每个 20M 块都从 lr 基准重启，`3×20M ≠ 1×60M`。s62–s64 的「失败/复评旧 ckpt」也有选起点 bug 叠加。
- **改动**：`scripts/train_block_clean.sh` 固定同时传
  `--checkpoint runs/az_entity_s61/eval/ckpt_020026719.pt --trainer-state runs/az_entity_s61/trainer.pt`；
  `--eval-drain 1`；`--eval-device cuda:1`；`--gpu-free-check 0`（共享卡上 1 会误剔除有 5GB 邻居的 GPU3）。
- **A/B**：无（这是语义修复，不是算法实验）。smoke `runs/_smoke_p2b01`（64 局 × 5 iter）
  验证：`start_iter=285`、`lr=1.11423e-6`、history 从 iter 285 起、保存后 `updates=290`、
  optimizer `step=2575`（=2565+10）、无异常。
- **数字**：s73 实测 ~9.5–10.8k dec/s（24 进程 / GPU 3,4,5），20M 预计 ~50–60 min。
- **结论**：采纳。**今后任何块间续训必须带 `--trainer-state`**；只给 `--checkpoint` 的 run 只能标「热启动」。
- **是否回退**：不回退；回退 = 去掉 `--trainer-state`（等价旧语义，但结论只能按「热启动」写）。
- **链接**：[TRAINING_STACK.md](TRAINING_STACK.md) §2、[CURRENT_STATE.md](CURRENT_STATE.md) §3、`tests/test_resume_contract.py`

---

## D-20261104-02 · 固定阵容脚本：**不启用** `comp_fit`，只作评测参照

- **日期**：2026-11-04
- **状态**：不采纳（三开关保持 0；脚本只做评测/探针）
- **动机**：①T1 已有四臂实测（从 s27d 起）：t1(0.5/1.0/0.25) 6.5547、对照 t1p 6.5938、
  t1iso(8/10/2) 6.4688、t1iso2 6.4766（human128 面板，n=128；MDE80≈0.5）⇒ Δ 在噪声内；
  ②实现只在 `turn<=9` 累计 `ΔΦ`，终局 `Φ≠0`，整局和 = `c·Φ@t9`，**不是 policy-invariant PBRS**；
  ③候选集实跑只有 2 套（`implementable ∩ supply.reachable`），help 文本「26 套」不成立；
  ④模型 96 局实测：`Φ(t9)` 与 t15 强度 Pearson −0.079 / Spearman −0.196（n=84）⇒ Φ 高 ≠ 强；
  脚本 M 的 Φ(t9) 与模型相当但 t15 Σ 只有 131（模型 425）。
- **改动**：无（`--comp-fit-coef 0 --comp-fit-t9-bonus 0 --comp-trinket-coef 0`）。
- **A/B**：无新 A/B；引用 T1 四臂与 comp-audit 30 局探针（4 套、非法 0、合法率 1.000）。
- **数字**：若未来重试，只允许真 PBRS（全程 ΔΦ + 终局 −Φ）、`c ≤ 0.05`、≥384 对面板；
  8M 时 Φ↑ 但 strength_t15 不↑ 即停。
- **结论**：不采纳。**脚本的价值是「不随训练漂移的尺子」**，不是教师/势函数。
- **是否回退**：不适用（从未进主线）。重试前提见 ROADMAP P3。
- **链接**：[COMP_SCRIPTS_TRAINING.md](COMP_SCRIPTS_TRAINING.md)、[ASTRA_REVIEW_2026-11.md](ASTRA_REVIEW_2026-11.md) §2、[COMP_SCRIPTS.md](COMP_SCRIPTS.md) §0

---

## D-20261104-03 · 退役失控链，单一训练入口 `scripts/train_block_clean.sh`

- **日期**：2026-11-04
- **状态**：生效
- **动机**：`chain_300m.sh` 与 `auto_chain.py` 同时存活（两个 watcher 各拉一遍）；都用
  `ls -t eval/ckpt_*.pt | head -1` 选下一块起点，而 `_submit_eval` 在评测忙时不落 ckpt
  ⇒ 静默丢 10M 且 CSV 照记 +20M。工作区版 `auto_chain.py` 还多了一行调用
  `/tmp/cleanup.sh`（会 kill 所有 HSBRSIM 窗口的 GPU 进程与全部 `train_entity_sync`）。
- **改动**：两条链脚本移入 `runs/_archive/chaos_20261103/`；`auto_chain.py` 回到 HEAD；
  `/tmp/cleanup.sh` 改名为 `.disabled_20261104`；新入口 `scripts/train_block_clean.sh`
  （并行拒绝 / OUT flock / 精确续训 / 结束自动 `eval_panel.sh`）。
- **A/B**：无。
- **数字**：s73 单块稳定 ~10k dec/s，无重启、无 illegal、无 truncated。
- **结论**：采纳。**禁止再用 `ls -t eval/ckpt_*` 选起点**；块间只从 `$OUT/model.pt` 或显式 ckpt 续训。
- **是否回退**：不回退。
- **链接**：[CLEANUP_PLAN.md](CLEANUP_PLAN.md)、[CURRENT_STATE.md](CURRENT_STATE.md) §6

---

## D-20261104-04 · 历史最优基线锁定 s61，s62–s64/s72 作废

- **日期**：2026-11-04
- **状态**：生效（Phase-2 起点）
- **动机**：`runs/eval_panel/s62_final.json`、`s63_final.json` 与 `s61_20m.json` **md5 全同**
  （`52ddb7e3…`），且 s62/s63 无 `eval/` 目录 ⇒ chain 在训练失败后复评旧 ckpt；
  s64_final 为 0 字节；s65/s72 是同起点的两条并行链（Lead 已停机）。
- **改动**：基线登记为 `runs/az_entity_s61/eval/ckpt_020026719.pt`
  （sha256 `a2bd7f0c…`，块内 20,026,719 decisions，文档口径累计 30.07M）；
  `runs/CHAIN_300M.csv` 的 60M/80M 两行标记错账（待清理时删除）。
- **A/B**：无。
- **数字**：冻结面板（96 局/seed 520000/5 席 p0.9/full/p75）：rank 6.083、top4 14.6%、
  strength 323.5、tier≥4 66.7%、survive12 11.5%。
- **结论**：采纳。历史报告/曲线中引用 s62/s63 的结论一律作废。
- **是否回退**：不适用（事实修正）。
- **链接**：[TRAINING_STACK.md](TRAINING_STACK.md) §1、[TRAINING_CURVE_300M.md](TRAINING_CURVE_300M.md)

---

## D-20261104-05 · B01（s73，精确续训 20M）结果：rank 不可判，强度描述性 +7~14%

- **日期**：2026-11-04（训练 00:13–01:01，评测至 01:15）
- **状态**：观察中（s73 作为下一块起点；是否变强未证实）
- **动机**：验证 D-20261104-01 的精确续训路径在真实 20M 块上可用，并给出 B01 相对 s61 基线的同口径读数。
- **改动**：唯一变量 = 恢复语义（`--checkpoint` + `--trainer-state`）；其余 233 个 flag 逐字保留；
  `comp_fit=0`、`shaping=0`、辅助头全关。`--gpu-free-check 0`（GPU3 有邻居 5.3GB，1 会误剔除）。
- **A/B**：单臂对照 s61 冻结 ckpt；96 局（seed 520000）+ 512 局（新 seed 740000）双面板。
- **数字**：
  - 96 局：rank 6.083→**6.208**（Δ+0.125）；top4 14.6%→14.6%；strength 323.5→**347.5**（+24）；
    tier≥4 66.7%→60.4%；survive12 11.46%→11.46%；tier≥5@t15 6.06%→4.41%。
  - 512 局（seed 740000）：rank 6.385→**6.275**（Δ−0.109）；top4 9.8%→**12.5%**；strength 293→**334**（+41）；
    tier≥4 61.3%→57.4%；survive12 13.67%→13.28%；tier≥5@t15 9.59%→10.53%。
  - 训练：20,016,527 decisions / updates 566 / 2743s；dec/s p50 10,628；KL p50 0.0025、max 0.0152；
    entropy 0.755→0.744；illegal/truncated/restart/OOM 全 0。
- **结论**：**采纳「精确续训可稳定跑完且不退化」**；rank 的 |Δ| 在两个 seed 上均 <0.3 且方向相反 ⇒
  噪声、不可判。强度/top4/tier≥5 为描述性正向，**不构成「变强」的证据**（96 局 SE 0.146；512 局 diff SE≈0.13）。
- **是否回退**：不回退。下一块从 `runs/az_entity_s73/model.pt` 精确续训或先做 P2 anchor A/B（ROADMAP）。
- **链接**：[CURRENT_STATE.md](CURRENT_STATE.md) §7、[TRAINING_CURVE_300M.md](TRAINING_CURVE_300M.md)、
  `runs/az_entity_s73/REPORT.md`

---

## D-20261104-06 · 固定阵容脚本完整实现（28 套 + V2 决策树）

- **日期**：2026-11-04（commit `5d54814`）
- **状态**：生效
- **动机**：用户要求「固定阵容脚本应该完整实现」；此前 `COMPS` 只有 15 套、V2 决策树只对
  f_dragon 生效、roles.json 的 26 套 implementable 有 13 套未注册。
- **改动**：`scripts/comp_scripts.py` —— 注册表 15→28（新增 `undead_apm/murloc_scam/
  aberration_discard/dragon_shield/undead_butcher/quilboar_choose_one/beast_lobster/
  aberration_deathrattle/pirate_discover/demon_self_damage/elemental_tempest/dragon_kalecgos/
  pirate_bounty`，core/enabler/trinkets 取 roles.json）；V2 决策树推广到所有套；新增
  `view_of/comp_keys/reset`；`comp_full_probe.py` 双模式探针。
- **A/B**：无（实现类改动）。探针：28×2×10 局 = 43,078 决策、非法 0、确定性 28/28；
  hybrid t15 Σ 62–314、pure 49–86。
- **数字**：`pytest tests/test_comp_scripts_full.py` 35 passed（22 s）。
- **结论**：采纳。已知边界：13 套新阵容的成长在战斗内，脚本只实现招募期可执行部分；
  hybrid 的强度主要来自 bot 兜底。
- **是否回退**：不回退（旧 15 套语义保留，V2 门槛可用 `exit_on_miss=False` 关闭）。
- **链接**：[COMP_SCRIPTS_FULL.md](COMP_SCRIPTS_FULL.md)、[COMP_SCRIPTS_V2.md](COMP_SCRIPTS_V2.md)

---

## D-20261104-07 · 固定阵容脚本接入训练：脚本席（对手分布），pilot 无显著差异、默认关闭

- **日期**：2026-11-04（commit `31d61bf`；A/B 结果见 `docs/COMP_SCRIPT_AB.md`）
- **状态**：生效但**默认关闭**（`--script-seats 0`，opt-in）
- **动机**：用户要求「正确接入」训练，而不是只做评测参照。选择**对手席**而不是奖励 shaping：
  comp_fit 已被 D-20261104-02 否决（非 PBRS、2 套可达、T1 无收益），改对手分布不动奖励与
  PPO 数学，语义最干净。
- **改动**：`CompOpponentPolicy`（每 seat 独立固定阵容 + hybrid：compx_action→bot fallback）；
  `--script-seats 0..3 --script-comps auto|D,H`；`frozen_opponent="comp:..."` 走脚本分支；
  人类战团/镜像/轨迹注入排除脚本席；history 增加 `frozen_decisions`。
- **A/B**：control vs treatment（2 席 D,H），s73 精确续训，各 10M，seed 27401，同 GPU；
  512 局新 seed 741024 + 96 局 520000。
- **数字**：treatment−control：512 局 rank **−0.066**、strength +6.5、top4 −2.15pp；
  96 局 rank **−0.240**、strength +61.5、survive12 +5.2pp；非法 0。
  脚本席采集 dec/s 10,260→3,090（**3.3× 慢**，8.23M 脚本决策）。
- **结论**：接入正确、无退化；方向偏好但两面板均 |Δrank|<0.3 ⇒ **证据不足，不设默认**。
  先优化逐决策 `view_of` 的成本，再做 ≥1024 对配对 A/B；否则只保留 opt-in。
- **是否回退**：不启用即零影响（`--script-seats 0` 与旧路径逐位等价）。
- **链接**：[COMP_SCRIPT_SEATS.md](COMP_SCRIPT_SEATS.md)、[COMP_SCRIPT_AB.md](COMP_SCRIPT_AB.md)、
  [COMP_SCRIPTS_FULL.md](COMP_SCRIPTS_FULL.md)

---

## D-20261104-08 · Stage-300M：单进程连续 300M PPO（吞吐配置 C；配方只改预算）

- **日期**：2026-11-04 10:05 启动（`runs/az_stage300m_b01`）
- **状态**：生效（长跑中）
- **动机**：用户要求「优化吞吐之后再次开始 300M/stage 预期的大规模 PPO 训练，每 10M 计点绘图」。
  此前所有 run 都是 20M 小块串行（且复评/记账有 bug）；需要一个连续 stage 检验缩放。
- **改动**：
  - 吞吐：4 臂基准（`docs/THROUGHPUT_300M.md`）选 **C**：32 procs / threads 2 / minibatch 2048 /
    grad-accum 4（有效 batch 8192），端到端 +18% vs 24/3/1024×8；瓶颈已转 update。
  - 预算：`--stop-at-decisions 300,000,000`，单进程连续；`--minutes 1500` 兜底；`--snapshot-every 100`
    保留 8 份（崩溃可精确续训，`scripts/resume_stage300m.sh`）。
  - 其余与 clean recipe 逐字相同（anchor 0.1 常数、max-updates 3000、lr-min 0.5、无 shaping/辅助头）。
  - 监控：`scripts/stage_monitor.py` 每 10M 用 `eval_panel.sh`（96 局/seed 520000/5 席 p0.9/full）
    打 canonical 点 + 16 面板 `curves.png` + `dashboard.md` + 60s 系统指标 + 告警。
- **A/B**：无（用户明确当前不再做 A/B；本轮只改预算与吞吐参数，不改算法/奖励）。
- **数字**：实测稳态 9.5–10.1k dec/s；300M ≈ 8.3–9.5 h（含每 10M 评测）。基准 C 8.9k dec/s。
- **结论**：采纳。**已知限制**：anchor β=0.1 在整段保持（`anchor_iterations=100000`），
  astra 认为 anchor 可能支配梯度；本轮不做 A/B，监控 `anchor_kl/entropy`，若出现平台/坍缩则
  下一 stage 用 snapshot 回滚并改调度。
- **是否回退**：回滚到 s73（`runs/az_entity_s73/model.pt`）；停跑 `pkill -f train_entity_sync`（需 Lead 批准）。
- **链接**：[STAGE300M_RUN.md](STAGE300M_RUN.md)、[THROUGHPUT_300M.md](THROUGHPUT_300M.md)、
  [STAGE300M_MONITOR.md](STAGE300M_MONITOR.md)

---

## D-20261104-09 · 固定阵容脚本作为 PPO 对手 —— **已取消（2026-11-04 12:00）**

- **日期**：2026-11-04
- **状态**：**已取消**（用户否决：吞吐下降 3.3×、强度无显著变化；脚本退回评测/探针用途）
- **动机（原始）**：8 席全脚本 50 局的冠军终局强度 p50 1268、p90 1960、max 2558，
  对比 8 引擎 bot p50 1311、p90 3876、max 14576 ⇒ 中位相当、脚本尾部更紧。
- **改动/计划（已撤销）**：原计划下一 stage 默认 `--script-seats 2 --script-comps auto`；
  现**不启用**（`--script-seats 0` 保持默认），脚本只用于 `comp_full_probe.py` / 8 席对弈等评测。
- **取消理由**：① 脚本席逐决策 `view_of` 使采集 10,260 → 3,090 dec/s（3.3× 慢），
  会把 300M 的 ETA 从 ~9h 拉到 ~30h；② pilot A/B（96/512 面板）rank 变化在噪声内
  （−0.240 / −0.066），强度只有描述性 +6.5~+61.5，**不足以抵消吞吐代价**。
- **A/B**：既有 pilot A/B 保留为记录（无新 A/B）。
- **结论**：不采纳。当前 300M stage 与后续训练均保持纯引擎 bot + 人类盘面注入的对手分布。
- **是否回退**：已回退到 `--script-seats 0`（零影响；代码与 CLI 保留供以后评测/再评估）。
- **链接**：[EIGHT_SCRIPT_BOTS.md](EIGHT_SCRIPT_BOTS.md)、[COMP_SCRIPT_SEATS.md](COMP_SCRIPT_SEATS.md)、
  [COMP_SCRIPT_AB.md](COMP_SCRIPT_AB.md)

---

## D-20261105-01 · B03（fresh optimizer + 三步 human-board 课程，完整 300M）判定：未达判据、无效但无回归

- **日期**：2026-11-05
- **状态**：已结束（300M 跑满，不采纳为基线；权重保留作后续起点）
- **动机**：B02 因 floor-lr 空转被提前停止（STAGE300M_REPORT §5）。B03 用 fresh optimizer +
  `max_updates=4500` + 三步 human-board 课程（1→2→3 席，p 0.30→0.50→0.70→0.90；p50→p75→p90）重跑完整 300M。
- **改动**：`scripts/run_stage300m_b03.sh`（e9aa665）；引擎 `sell_minion` 越界修复（0b8ef83）；
  新增 `scripts/eval_bot_panel.sh`（8 席 bot 面板、局数可调）。
- **数字**（**768 局**同口径，seed 620000、guard=1、37.0.2；评测确定性已验证）：
  - rank 1.853 → **1.810**（Δ −0.043 ± 0.036，1.2σ 不显著）
  - top4 97.4% → 98.2%；win 41.8% → **45.3%**（+3.5pp，1.9σ 边缘）
  - 加权 rank/win 1.936/35.4% → 1.890/38.8%
  - 长强子集 n=50/51：win 20.0% → **15.7%**（−4.3pp，0.8σ）；rank 2.140 → 2.059
  - human 96 局（37.0.2 同版本）：B01 6.385 / 9.4% / 328.5 / survive12 8.3% → B03 6.125 / 10.4% / 377.5 / survive12 15.6%
    ⇒ human 面 **rank −0.26、survive12 +7.3pp**，有可测改善
- **结论**：按 §5.2 的 bot 判据未达（rank −0.15 / 长强 +10pp）⇒ **bot 面「无效但无回归」，human 面「有效」**。
  不能再用 96/384 局面板判 Δ<0.1：96 局 SE≈0.10、384 局两块差 0.08、768 局 SE≈0.036。
- **是否回退**：不回退（无回归；bot 排名以 B03 300M 为当前最好点估计）。
- **链接**：[STAGE300M_REPORT.md](STAGE300M_REPORT.md) §6、[B03_DESIGN.md](B03_DESIGN.md)、`runs/az_stage300m_b03/`

---

## D-20261105-02 · B04 = 冻结对手席（联赛/自对弈廉价版）：2 席冻结 net + 5 席引擎 bot

- **日期**：2026-11-05（11-05 23:54 开跑）
- **状态**：生效（`runs/az_stage300m_b04`，300M，起点 B03 300M，seed 27603）
- **动机**：B03 判定见 D-20261105-01。bot 面板已饱和（top4 97–98%），唯一还有空间的判别轴是**长局**：
  长且强子集 win 仅 15.7–20.0%（vs 非长强 45–50%），输局我方死亡盘面 Σ p50 757、同期 bot 最强盘面 ≈3139（≈4×）。
  `ECONOMY_CEILING.md` 证明「人类级强度」不可达，但**引擎 bot 自己能到 3000+** ⇒ 缺的是训练分布里
  「不会被早期打死、能滚雪球」的对手。用户选定方向：自对弈/对手池。
- **改动**：`--frozen-seats 2 --frozen-opponent runs/az_stage300m_b03/model.pt`（8 席 = 1 learner + 2 冻结 net + 5 引擎 bot，
  其中 3 席照旧 human-board 注入）。其余配方与 B03 逐字一致（单变量）。
  `train_block_clean.sh` / `run_stage300m.sh` 新增 `FROZEN_SEATS` / `FROZEN_OPPONENT` 环境变量（空=旧行为逐位一致）。
- **A/B**：无并行双臂；与 B03（同 300M 预算、同课程、同评测口径）作历史对照，判据 ≥768 局。
- **数字**：吞吐（5 分钟 pilot，见 THROUGHPUT_300M.md §5）：3 卡 **5288 dec/s / 13.2 s/iter**；
  **4 卡（3,4,5,6）6366 dec/s / 11.0 s/iter（+20%，采纳）**；`--leaf-wait-ms 3`（5154）与 `--processes 48`（5220）均负收益。
  ETA ≈13–14h；
  判据：长强 win ≥26.7%（n≥24）、bot rank ≤1.75、human 不劣化 >0.10。
- **为什么不 `--opponent self`**：7 席全冻结 ≈ **慢 25×**（每席位每决策一次 net forward），300M 不可行。
- **结论**：进行中；若 200M 仍无长强改善，下一步 `FROZEN_SEATS=3` 或改「每 75M 一阶梯刷新冻结 ckpt」。
- **是否回退**：回退 = `FROZEN_SEATS=0`（旧配方，逐位等价）。
- **链接**：[B04_DESIGN.md](B04_DESIGN.md)、[STAGE300M_REPORT.md](STAGE300M_REPORT.md) §6

---

## 模板（复制这一段新增）

```markdown
## D-YYYYMMDD-NN · <一句话标题>

- **日期**：
- **状态**：生效 / 已回退 / 观察中 / 不采纳
- **动机**：（具体现象 + 数字 + 来源文档）
- **改动**：（文件/CLI；旧值 → 新值；默认开/关）
- **A/B**：（臂数、预算 iter×games≈decisions、起点 ckpt+sha、seed、唯一变量；若无 A/B 写「无」并说明）
- **数字**：（主指标 Δ[95%CI]、次要指标、硬约束、吞吐）
- **结论**：采纳 / 不采纳 / 证据不足 + 一句为什么
- **是否回退**：（回退命令，或「不回退 + 原因」）
- **链接**：（docs §节 + runs/<run>/）
```
