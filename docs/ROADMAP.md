# ROADMAP — Phase-2：从历史最优基线到可复现的强模型

> 制定日期 2026-11-04。所有阶段以 `docs/CURRENT_STATE.md` 的现状与评测口径为准；
> 每阶段必须预注册判据、唯一变量、回退方式，否则不合并进主线。

## 0. 总目标

在 AutoTavern 的 `hsbg_engine` 上，用「不完全信息自对弈 + 策略/价值学习」训练一个**实时可更新、
可复现、可量化**的酒馆战棋智能体，并以冻结人类面板为唯一主终点持续提升。

**当前定位**：历史最优 `s61/ckpt_020026719`（rank 6.083、strength 323.5、top4 14.6%）。
**本轮（B01）**：`runs/az_entity_s73` —— 精确续训 20M，先验证「续训语义修复」本身，再谈算法改动。

## P0（当前最高优先）· 模型 vs engine bot 稳定性门禁

> 用户指令（2026-11-04）："模型连稳定追到 engine bot 都做不到的话不考虑其他。"
> 因此任何新特性（脚本对手、新奖励、搜索、架构改动）都排在**这个门禁之后**。

- **口径**：`quality_monitor.py`（8 席全是引擎 bot，无人类盘面注入），256+ 局，固定 seed；
  报告 `mean_rank / top4 / win`，同时 `illegal=0 / truncated=0`。
- **门禁**：8 bot 面板 `mean_rank ≤ 2.0`、`top4 ≥ 95%`、`win ≥ 50%`（256 局）。不达标 → 只做
  「让它稳定压过 bot」的训练/数据工作，不做其它方向。
- **当前状态**：见 `docs/CURRENT_STATE.md` §9（2026-11-04 12:0x 实测）。


## P1（已完成 2026-11-04 01:15）· B01 判定

- **做什么**：s73 vs s61 在**新 seed**（740000）上做 512 对同口径评测；同时报告
  `death_strength_p50`、`tier_ge5_t15`、`survive_t12_ratio`、`tier≥4`、top4。
- **结果**：96 局 rank 6.208 vs 6.083（Δ+0.125）；512 局 rank 6.275 vs 6.385（Δ−0.109）；
  两个 seed 的 |Δ|<0.3 且方向相反 ⇒ **噪声、不可判**。描述性正向：strength +24/+41、512 top4 +2.7pp、
  tier≥5@t15 +0.9pp；描述性负向：tier≥4 −6.3/−3.9pp。**没有证明变强，也没有证明退化。**
- **产出**：`runs/az_entity_s73/REPORT.md`、`docs/CURRENT_STATE.md` §7、`DECISIONS` D-20261104-05。
- **结论**：s73 `model.pt`（sha256 `9c3969…`）可作为下一块起点；`s61` 仍是「已评测点中的最佳」。


## P2 · 破解 plateau 的第一候选：anchor-KL 支配与 entropy 冻结

- **证据**（astra，`docs/ASTRA_REVIEW_2026-11.md` §4）：s61 的 `β·anchor_kl` 与 policy 项同量级
  （约 58%），`kl_early_stopped` 0/285 次触发，entropy 0.743–0.763 几乎不变；信任域实际由 anchor 决定。
- **实验**：2 臂 × 10M（A 保持 β=0.1 / B 降 β 或缩短 anchor_iterations），同起点同 seed、其余逐字相同。
- **判据**：机制门 = `kl_early_stopped` 出现 >0 且 entropy 有下降；止损 = entropy<0.65 或 value_loss>1.75 连续 10 iter；
  效果门 = 1024 对配对评测 Δrank CI 上界 <0 或强度指标 +20% 且 CI 下界 >0。
- **成本**：~2×20-25 min 训练 + 1h 评测（GPU 3,4,5/6 + eval cuda:1）。

## P3 · 固定阵容脚本（**已取消作为训练对手**，只保留评测/探针）

- **已实现**：注册表 15→28、V2 决策树、探针（D-20261104-06）；训练侧 `--script-seats`
  可用（D-20261104-07）。
- **取消（D-20261104-09）**：用户否决作为 PPO 对手——脚本席使采集 3.3× 变慢
  （10,260→3,090 dec/s），而 pilot A/B 的 rank 变化在噪声内；8 席对弈显示脚本强度≈bot、
  尾部更紧，但**没有强到值得付吞吐代价**。
- **现状**：`--script-seats 0` 为默认；脚本只用于 `scripts/comp_full_probe.py`、
  `scripts/eight_script_bots.py`、eval 参照等离线用途。
- **重新评估条件**：只有在 P0 门禁通过、且出现「脚本席几乎零开销」的实现（≤1.1×）时，
  才考虑重新开启。




## P4 · 实时更新模拟环境（版本跟随）

- **现状**：数据链路 raw → `data/p2/MANIFEST` → `cards_37.json` → rust `cards.json` 已 byte-identical；
  `tools/p2_data/gen_carddb_37.py --check` 幂等；但 `verify_all --fast` 的 data_check 默认静默 SKIP（缺 `../AutoTavern`）。
- **目标**：新补丁（37.x → 38.x）落地流程化：更新 raw → 生成 MANIFEST/cards → rust 数据 → 契约测试 → 金标面板重跑；
  明确**卡牌下标跨版本不可复用**，旧 ckpt 必须做映射或重训。
- **验收**：数据版本三处一致 + `cargo test` + `pytest` 全绿 + `gen --check` 幂等；给出一键脚本与回滚。

## P5 · 搜索/AlphaZero 对齐（大工程，非今晚）

- **现状**：主线 `--sims 0`（无 MCTS），与 AGENTS.md 的 AZ 目标存在差距；AutoTavern 论文口径 310M decisions/stage。
- **风险先验**：PIMC 的 `game.copy()` 必须重播种 RNG（论文 +23.6 在 reseed 后为 −0.65±1.14）；
  我们的 `belief.py`/`infer_search.py` 是同一模式，做搜索前必须先过 reseed A/B。
- **进入条件**：P2/P3 至少一个给出正信号，或 P1 判定当前 PPO 路线在同等预算下无进展（按 REVIEW_PLATEAU §7 止损条款）。

## 工程护栏（长期）

- 门禁：`cargo test -p hsbg-engine` + `pytest tests` + `tavernbench --check` + `verify_all --fast` 全绿；
  当前 pytest 6 失败正在修（T11）。
- 训练：只用 `scripts/train_block_clean.sh`（并行拒绝 / OUT 锁 / 精确续训 / 结束自动评测）；
  禁止再出现 parallel chain / 手写 `ls -t eval/ckpt_*` 选起点。
- 评测：每个结论必须带「库 + 席位 + quantile + 局数 + seed」；开发面板（420000）不得混入主曲线。
- 文档：`CURRENT_STATE.md` 是唯一现状来源；历史报告进 `docs/_history/`；决策进 `docs/DECISIONS.md`。
