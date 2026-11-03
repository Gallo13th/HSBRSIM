# CURRENT_STATE — 2026-11-04（Phase-2 起点）

> 本文件是**唯一现状来源**；历史过程与已被取代的方案见 `docs/_history/`。
> 每个数字都带口径；没有口径的数字一律不引用。

## 0. 一句话

- **引擎**：`rust/` 的 `hsbg_engine`（AutoTavern TavernGym fork），数据基线 **37.0.0.255790**；
  动作 0..244 与 AutoTavern 逐位一致，245..273 为 Python 侧声明、引擎未实现；观测 3227 floats + 124 cards。
- **训练栈**：`hsbg/az` + `scripts/train_entity_sync.py` —— entity transformer（384d/8L/8H，16,436,034 参数）、
  8 座自对弈、PPO（clip 0.2、GAE λ=0.995 γ=1.0、rank-utility value、anchor-KL 0.1、target-KL 0.02）。
  当前主线 **`--sims 0`（无 MCTS）**，对手为 bot + 3 席人类赢家盘面注入（p=0.9，board 保真）。
- **历史最优基线**：`runs/az_entity_s61/eval/ckpt_020026719.pt`
  （sha256 `a2bd7f0c58b0722c5d1fe4e662334bde9ce3d114a06d754aff441ec3c0f4478c`；
  与 `runs/az_entity_s61/model.pt` 逐张量相同；s61 块内 20,026,719 decisions，文档口径累计 30.07M）。
- **本次 Phase-2 Block-01**：`runs/az_entity_s73`，从上述 ckpt **精确续训** 20M decisions
  （`--checkpoint` + `--trainer-state`），clean recipe，`comp_fit=0`，seed 27301。
- **历史最优的评测**（`scripts/eval_panel.sh`：96 局、seed 520000、5 席 p0.9、full、p75）：
  mean_rank **6.083**、top4 14.6%、death_strength_p50 **323.5**、tier≥4 66.7%、survive12 11.5%。

## 1. 三个评测口径（不可混用）

| 口径 | 命令/位置 | 规模 | 库/席位 | seed | 用途 |
|---|---|---|---|---|---|
| 冻结面板（主口径） | `scripts/eval_panel.sh` → `runs/eval_panel/<tag>.json` | 96 局（可扩 512/1024） | `library_real_quasi_full.jsonl`，5 席，p0.9，full，p75 | 520000 | 与历史数字可比；发布结论只用它 |
| 训练内 dev 曲线 | `--eval-async 1 --eval-device cuda:1` | 96 局 | human 面板，8 席，quantile auto | 420000 | 只看趋势，**不可与冻结面板混算** |
| 独立 exam | `runs/exam/`、730xxx 四块面板 | 4×512 | 旧口径 | 730001+ | 历史显著性检验，本轮不再复用 |

**分辨率**（astra/REVIEW_PLATEAU）：96 局单模型 SE≈0.146，两 ckpt 未配对 MDE80≈0.58；
`|Δrank|<0.3` 记噪声、0.3–0.6 不可判、>0.6 才叫信号。单块 20M 的期望位移≈0.2，**不能用 96 局证明改善**。
主看 `death_strength_p50`（eval_panel 打印的 `strength`）、`by_turn[15].tier_ge5_ratio`、`survive_t12_ratio`。

## 2. 历史 run 可信度（s59–s73）

| run | 块内 decisions | 起点 | 冻结面板 | 判定 |
|---|---:|---|---|---|
| s59 5M/10M | 5.0M/10.0M | BC 冷启动 | 6.396 / 6.458 | 有效（早期点） |
| s60b 10M | 10.0M | s59 | 6.406 | 有效 |
| **s61 10M/20M** | 10.0M/20.0M | s60b | 6.292 / **6.083** | **有效；20M 为历史最优** |
| s62 | 5.98M（失败） | s61 | —（无 eval ckpt） | **作废**（训练被并发链/评测 skip 打断） |
| s63 | 88k（失败） | s61 | 与 s61_20m 逐字节相同 | **作废**（chain 复评旧 ckpt） |
| s64 | — | s61 | 空 JSON | **作废**（eval 被杀） |
| s65 / s72 | 各 ~10M | s61 | s72_10m 6.302 | **作废**（两条并行链抢 GPU；Lead 已停机） |
| **s73** | 20M（本轮） | s61（精确续训） | 见 `runs/az_entity_s73/REPORT.md` | 本轮结果 |

`runs/CHAIN_300M.csv` 的 60M/80M 两行是**复评旧 ckpt 的错账**，不得当曲线点使用。

## 3. 续训语义（本轮修复的核心）

- `--checkpoint`：只恢复 `model + meta(norm)`（`train_entity_sync.py:2821-2824`）。
- `--trainer-state`：额外恢复 optimizer/Adam、scheduler/updates、RNG（`ppo_trainer.py:412-437`）。
  **只有同时给两者才是精确续训**；只给 `--checkpoint` 会让每块从 lr 基准重启（3×20M ≠ 1×60M）。
- `anchor` 在恢复后重新 `set_anchor()` 到当前策略（`train_entity_sync.py:3203`），与旧块一致。
- `--eval-drain 1`：收尾等待末次评测落盘；`0` 会 kill 在跑评测（s61 的 20M 评测因此缺失）。
- `--gpu-free-check 1` 会把「已用显存 > 1GiB」的卡从 actor 列表剔除（共享卡慎用；本轮用 0）。

## 4. 本轮唯一变量与证据

相对 `runs/next_block.sh` 只改 5 处（其余 233 个 flag 逐字保留）：
`--out runs/az_entity_s73`、`--seed 27301`、`--eval-device cuda:1`、`--eval-drain 1`、`--gpu-free-check 1→0`，
并新增 `--trainer-state runs/az_entity_s61/trainer.pt`。**没有**开 comp_fit / shaping / 辅助头。
smoke（`runs/_smoke_p2b01`）已证明：`loaded updates=285 lr=1.114e-6`、`resume start_iter=285`、
history 从 iter 285 起、保存后 `updates=290`、optimizer `step=2575`（=2565+10）。

## 5. 未决与风险

1. **anchor-KL 支配**：s61 的 `β·anchor_kl` 与 policy 项同量级、`kl_early_stopped` 0/285 次触发、
   entropy 0.74–0.76 冻结 → 下一候选 A/B（2 臂 × 10M），本轮不动。
2. **固定阵容脚本**：`comp_fit` 已实测无效（T1 四臂 6.4688–6.5938，n=128 无法判）、且只在 t≤9 累计、
   候选实跑仅 2 套 ⇒ 本轮不开；脚本只作评测参照（合法率 1.000）。
3. **门禁**：pytest 有 6 个失败（5 fixture + 1 flaky，见 `docs/INTERFACE_AUDIT.md`），修复中。
4. **搜索**：主线是 sims=0 的 PPO 自对弈；AutoTavern 论文口径为 310M decisions/stage、24,576 局/评测点。
5. **PIMC/RNG**：`belief.py`/`infer_search.py` 用 `game.copy()` 时必须重播种 RNG（论文 +23.6 在 reseed 后为 −0.65±1.14）。

## 6. 运行态

- 训练：`runs/az_entity_s73`（GPU 3,4,5 actor / cuda:6 learner / cuda:1 eval，24 进程，shm pipeline）。
- 守护：`scripts/train_block_clean.sh`（并行拒绝、OUT 锁、结束自动 `eval_panel.sh`）。
- 停机/清理：历史链 `scripts/chain_300m.sh`、`scripts/auto_chain.py` 已停用；
  `auto_chain.py` 中的 rogue `/tmp/cleanup.sh` 调用已移除，`/tmp/cleanup.sh` 已禁用。
