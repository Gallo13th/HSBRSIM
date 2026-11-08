# 训练栈 bug 审计（sol / task-6）

- 审计对象：`scripts/train_entity_sync.py`（4289 行）+ `hsbg/az/train/{ppo,ppo_trainer,process_pool,parallel_collect,human_board_pool,runlog}.py` + 链路脚本 `scripts/{chain_300m.sh,eval_panel.sh,auto_chain.py,watch_s61_then_chain.sh,async_eval.py}`
- 目标场景：从 `runs/az_entity_s61/eval/ckpt_020026719.pt` 续训 20M decisions（bf16 + compile + pipeline lag=1 + eval-async + human-board 注入 + move-guard）
- 纪律：只读审计，未改任何代码，未启动训练。行号为 read/python 口径（该文件 4289 行）。`runs/ data/` 未同步到本地，凡涉及运行产物的结论均标注「需远端确认」。

## 1. 结论：今晚是否有 P0

**单块 20M、从 ckpt_020026719 起 → 未发现会污染权重的确定性 P0。** 但有 2 个「取决于怎么起」的条件性 P0，以及 7 条会让今晚结论失真/白跑的 P1，必须先落到命令行上：

| # | 结论 |
|---|---|
| 条件性 P0-1 | 若今晚实际执行的是 `scripts/chain_300m.sh`（或残留 watcher 自动拉起它），起点 ckpt 可能静默回退（评测 skip 时不落 ckpt），且 CSV 照记 +20M。单块手起不受影响。 |
| 条件性 P0-2 | 必须先 `pgrep` 确认无残留 `watch_s61_then_chain.sh` / `auto_chain.py` / `quality_monitor`：前者 s61 结束即自动起 chain，会和今晚训练抢 GPU 且共用 `runs/az_entity_s61/eval/ckpt_*`。 |
| P1-1 | 用 `--checkpoint` 续训 ≠ 精确续训：optimizer/step/LR/RNG/history 全重置。**不得把「3×20M」写成「1×60M」**。 |
| P1-2 | 评测链：async 评测在跑时**不落评测 ckpt**；`--eval-drain 0` 又在退出时 kill 在跑的评测 → 最后一点的评测结果拿不到、链式续训可能少 10M。 |
| P1-3 | comp_fit 若今晚打开且 `runs/comp_scripts/roles.json`/`supply.json` 缺失/损坏 → 奖励恒 0，日志仍显示系数，训练「看着正常」。 |
| P1-7 | `winner_library.jsonl` 全仓只被 chain_300m.sh 引用（无生成脚本）：文件不在 → 块瞬间 `return 2`，但 chain 照记 +20M；另训练库(winner/board)与评测库(quasi_full p75)不同 × 训练内 eval 用 degraded → 评测数不可直接比。 |

权重安全性的正面证据（已逐条核对，见 §5）：截断局**不会**被当终局写 value target；forced 样本只进 critic；rank utility 与 value 头口径一致（默认系数下）。

## 2. P0（条件性，仅链式场景）

### P0-1 评测 skip → 评测 ckpt 缺失 → 下一块从旧 ckpt 续训（静默丢 10M decisions）
- 位置：`scripts/train_entity_sync.py:3445-3454`（`_submit_eval`：`if eval_runner.running(): submit(decisions, "")` 直接返回，**不写 ckpt**）；`scripts/chain_300m.sh:38-39`（`NEW=$(ls -t $OUT/eval/ckpt_*.pt|head -1)` 作为下一块起点）；`scripts/chain_300m.sh:50-53`（`CUM+=BLOCK_M` 无条件记账）。
- 触发：`--eval-every-decisions 10M` + 20M 块；10M 的 human 面板（96 局×8 席 full fidelity）在 cum 到 20M 时仍在跑。
- 影响：本块最终 ckpt 只有 10M 那个 → 下一块实际从 10M 起，**丢 ~10M decisions**；CSV/日志仍记 20M。这正是「s62-s64 疑似训练失败但 chain 复评旧 ckpt」的机制（失败块没有新 ckpt 时 `NEW` 为空 → `CK` 保持上一次，`CUM` 照加）。
- 最小修复：`_submit_eval` 无论 runner 是否在跑都 `_save_eval_ckpt()`（61MB，~0.3s），runner 只记 skipped；`chain_300m.sh` 在 38 行后断言「新 run 目录存在 ≥1 个 ckpt 且其 decisions tag ≥ 上一块 tag + 9.9M」，否则 `CUM` 不增。
- 立即改？单块不必要；**一旦要跑 chain 必须改**（或至少人工核对每块 ckpt tag）。

### P0-2 残留 watcher / auto-chain 并发起训
- 位置：`scripts/watch_s61_then_chain.sh:3-5`（`while pgrep -f "az_entity_s6[1]"; do sleep 60`，s61 结束即 `bash scripts/chain_300m.sh`）；`scripts/auto_chain.py:51-52,70-103`（等当前 trainer 退出后自动接续，且 `build_cmd` 会从上一 run 的 `history.jsonl` header 复用参数，`skip` 白名单里**没有** `trainer_state`）。
- 触发：历史上起过 watcher 后从未清理；今晚启动前 s61 进程不再存在。
- 影响：训练开始后 watcher 立刻拉起 `chain_300m.sh`（`--device cuda:6 --gpus 3,4,5`）→ 双训练抢卡/互相 OOM；`auto_chain` 若复用带 `--trainer-state` 的 args，会去加载**旧 run** 的 trainer.pt（`train_entity_sync.py:2869-2884` 的 elif 分支），与 `--checkpoint` 互相覆盖。
- 最小修复：启动前 `pgrep -af 'watch_s61|auto_chain|quality_monitor|quality_watch|train_entity_sync'`；并把 `trainer_state` 加入 `auto_chain.build_cmd` 的 `skip` 集合。
- 立即改？**是（启动前 1 分钟的操作检查）**。

## 3. P1

### P1-1 `--checkpoint` 只恢复权重，不是「续训」
- 位置：`scripts/train_entity_sync.py:2820-2837`（只 `load_checkpoint` 取 model+meta+`norm_mean/std`）；`:3140-3145`（只有 `--trainer-state` 才 `PPOTrainer.load`）；`:3185-3189`（`history.jsonl` 只在带 `--trainer-state` 时读回）。
- 精确续训的实现是 `hsbg/az/train/ppo_trainer.py:397-437`：optimizer/scheduler/rng/updates/extra 全部落盘恢复。
- 触发：`scripts/chain_300m.sh:21` 用的正是 `--checkpoint "$CK"`；任何「clean recipe」若只给 ckpt 也如此。
- 影响（未污染权重，但语义变了，且会写进结论）：
  1. Adam 一阶/二阶矩清零 → 每个块开头若干 update 的有效步长偏大（bias correction 重启）；
  2. LR 从 CLI `--lr 1.15e-6` 重新起算（`ppo_trainer.py:60-67`），20M 块约 300~500 update（按 ~50k~70k decisions/iteration 估），`--max-updates 3000` 下衰减只到 ~92-95% ⇒ 实际近似恒定 1.1e-6；
  3. `trainer.updates` 归零 ⇒ `start_i=0`（`:3198`）、snapshot/eval 命名、`--value-warmup-every`/ramp 的 `i` 口径全部重来；
  4. `--anchor-beta 0.1 --anchor-iterations 100000` 每次启动 `set_anchor()`（`:3202-3206`）⇒ anchor 变成「每块起点」，而非 60M 一次训练的原始起点；
  5. `history.jsonl` 不延续（绘图/曲线会被分块截断）。
- 最小修复：今晚若要「等价续训」，用 `--trainer-state runs/az_entity_s61/trainer.pt`（并显式给 `--arch entity --d-model/--n-layers/--n-heads` 与 state 一致）；若只能给 eval ckpt，则报告里明确写「分块热启动，非等价 60M」。次选：在 `--checkpoint` 分支打印一行醒目 warn（`[resume] model-only：optimizer/lr/step 已重置`）。
- 立即改？**是（二选一：改命令行，或在结论里降级表述）**。注意 `--trainer-state` 路径的既有坑：`:2879-2881` 忽略 `--move-head-split`；`:2900-2918` 若 state 无 `process_head` 会静默把 `process_value_coef` 关 0。

### P1-2 最后一点的评测/评测 ckpt 与训练收尾竞态
- 位置：`scripts/train_entity_sync.py:4190-4195`（cum 达到阈值 → 提交评测）→ `:3763-3766`（下一轮循环顶部因 stop-at-decisions 立刻 break）→ `:4221-4223`（`finally` 里 `eval_runner.close(drain=eval_drain)`，默认 0 = 直接 kill）；`scripts/async_eval.py:454-496`。
- 触发：`--stop-at-decisions 20M` 与 `--eval-every-decisions 10M` 同用（chain/clean recipe 都是）。
- 影响：20M 这一点的评测**必然**在训练退出时被 kill（日志 `aborted ... trainer shutdown`，不入 history）⇒ 今晚「最后一块的评测结论」拿不到；只能另跑 `scripts/eval_panel.sh`。评测 ckpt 本身已先落盘（`_save_eval_ckpt`），链式续训不受影响（除非撞上 P0-1）。
- 最小修复：`--eval-drain 1`（多等 ~10-20 min），或接受「最后一点另评」。报告里写清用了哪个。
- 立即改？否（用 `--eval-drain 1` 或另评即可）。

### P1-3 comp_fit / 可选奖励失败被静默吞掉
- 位置：`scripts/train_entity_sync.py:742-813`（comp_fit 整段 `try/except BaseException: pass`）；依赖 `runs/comp_scripts/roles.json`（`:328-332`，缺失 ⇒ `comps=[]` ⇒ `_fit` 全 0）与 `runs/comp_scripts/supply.json`（`:334-343`，解析失败被 `pass`）；`_comp_fit_tables` 内部导入/数据失败同样被 `:812` 吞。
- 触发：今晚开 `--comp-fit-coef/--comp-fit-t9-bonus/--comp-trinket-coef` 但 `runs/comp_scripts/*` 被清理（`auto_chain.py:71` 每次块前跑 `/tmp/cleanup.sh`）或数据缺失。
- 影响：奖励恒 0、`custom_rewards` 里 comp_fit 计数为 0 但**日志照常打印系数**；训练「看着正常」，实际配置未生效 ⇒ 该实验结论无效（不污染权重，但污染实验判断）。
- 同类：`:594,619,645,665,703,736,912,953,1070,1098,1208,1232,1311,1354,1382,1483` 共 18 个可选奖励块，每个块独立 `except BaseException: pass`；默认全 0 时不执行（无害），**一旦开某项就变成「可能静默不生效」**。
- 最小修复：在 `_apply_custom_rewards` 开头加一次性断言——凡系数>0 的项，其依赖表必须非空（`len(T["comps"])>0`）、`cards_37.json` 可读；断言失败 `raise SystemExit(2)` 而不是 pass；或把 pass 改成 `print(f"[reward][warn] {name} 失败: {exc!r}")` 并累计 `n_failed`，进 history。
- 立即改？**今晚若开 comp_fit：是**（1 行断言）；不开则否。

### P1-4 pipeline `policy_version` 报的是「请求版本」而非「实际加载版本」
- 位置：`hsbg/az/train/process_pool.py:1351`（`"policy_version": weights_version`，即 `collect()` 入参）；worker 侧 `:468-489` 懒加载、`:533-539` 把 `_maybe_reload` 的异常 `except BaseException` 吞掉后**继续用旧权重采集**；`scripts/train_entity_sync.py:3914-3921` 用它做 `lag` 断言。
- 触发：权重文件读取失败（被裁剪/损坏/磁盘错误）、worker 重启后未 reload、`keep_versions` 配置过小。
- 影响：records 来自旧策略却标记为新版本 ⇒ `lag<=1` 断言失效、`pre_ratio`（`:3930-3937`）变成「新旧策略 diff」被误当异常。默认配置（`os.replace` 原子发布 + `--keep-versions 3`）几乎不触发，但**一旦触发是静默的**。
- 最小修复：worker 把实际 `weights_version` 放进 meta 回传，父进程 `policy_version = min(各 shard 实际版本)`，不一致就 abort；或 `_maybe_reload` 失败改成 `raise`（父进程已有失败重试语义）。
- 立即改？否（今晚可用 history 里的 `restarts`/`reload_s`/`fatal` 事件旁证）。建议今晚盯 `[pool] ... restarts` 与 stderr `weights reload failed`。

### P1-5 `--stop-at-decisions` 边界 + `--minutes` 早停：块可能「少训」但正常退出
- 位置：`scripts/train_entity_sync.py:3760-3769`（deadline 与 `remaining < last iteration` 都直接 break → 走 `finally` → 写 summary/返回 0）；`:4190`（cum 在整轮 collect 之后累加，`stop` 检查在**下一轮开头**，故必然 overshoot 一个 iteration，实测 s61 是 20.026M）。
- 触发：`--minutes 400` 先到（20M 未跑完）；或 `--iterations 8000` 先耗尽。
- 影响：退出码 0、`[done]` 正常打印 ⇒ 看起来「成功」，但 summary 的 `cum` 只到 15M；若 chain 记账即 P0-1 前半段。今晚单块要人工核对 `summary.json`/最后一行的 `decisions`。
- 最小修复：收尾时比较 `cum_decisions` 与 `--stop-at-decisions`，差额 > 2% 打印 `[warn] short block` 并以非 0 退出；或把 deadline 判断改成「剩余时间 < 1.2×本轮耗时再停」。
- 立即改？否（人工核对 summary 即可）。

### P1-6 评测卡与 actor/邻居抢卡（今晚硬约束）
- 位置：`scripts/chain_300m.sh:33-35`（`--gpu-free-check 0`、`--gpus 3,4,5`、`--device cuda:6`、`--eval-device cuda:7`）；`scripts/eval_panel.sh:14`（默认 `EVAL_DEVICE=cuda:7`）；`:3434-3443` 只在 `--gpu-free-check 1` 时告警，`:3516-3524` 只在评测卡∈actor 卡时告警。
- 触发：GPU 0,1,2,7 已被他人占用（本次环境事实）。
- 影响：eval 子进程在 cuda:7 上 OOM/被挤 → 今晚所有周期评测 FAILED（`async_eval.py:425-435` 记 failed，不入曲线）；**不影响训练权重**，但今晚「评测结论」为空。actor/learner 在 3,4,5/6 上可跑。
- 最小修复：`--eval-device cuda:3`（与 actor 同卡、接受变慢）或 `--eval-device cpu`/关闭 `--eval-async`，并把 `--gpu-free-check 1` 打开。
- 立即改？**是（命令行）**。

### P1-7 训练对手库 / 两个评测口径 / 「winner 库」文件来源（评测结论能否对比）
- 位置：训练 `scripts/chain_300m.sh:31-32`（`--human-boards data/real_library/winner_library.jsonl --human-board-fidelity board --human-board-p 0.9 --human-board-seats 3`）；训练内周期评测默认 `train_entity_sync.py:3230-3231`（`library_real_degraded.jsonl`，quantile auto）；链末尾/独立评测 `scripts/eval_panel.sh:15-17`（`library_real_quasi_full.jsonl`，p75，5 席，full fidelity，seed 520000；训练 seed=27060+step）。
- 触发/事实：① `winner_library.jsonl` 在**整个仓库里只被 chain_300m.sh 引用一次**（无生成脚本、无 docs 记载）；若远端不存在，`train_entity_sync.py:2443-2445` 直接 `return 2`——块会瞬间失败但 chain 仍 `CUM+=20M`（与 P0-1 叠加，正是 s62-s64 那种「看着有进度、其实没训」的形态）。② 训练对手是 winner 库（强），`eval_panel.sh` 是 quasi_full 的 **p75**（弱一档）⇒ 同口径下的 mean_rank/top4 会**系统性偏好**，不能当作「对训练分布变强」。③ 训练内 eval-async 用 degraded 库、链用 quasi_full 库 ⇒ 两条曲线**不可直接对比**。④ 三处 seed 互不相同，无「同 seed 复用同一行」的直接泄漏。
- 影响：今晚训练本身不受影响；**今晚/链上的评测结论会被高估**，且跨库比较（degraded vs quasi_full、p75 vs training p0.9 3 席）容易得出错误趋势。
- 最小修复：启动前 `ls -la data/real_library/winner_library.jsonl`；统一「训练对手库」与「评测库」的取值（或至少在报告里标注 panel 名 + 库名 + quantile 三元组）；`docs/TRAINING_CURVE_300M.md` 的 `cum_m` 列口径要跟 ckpt tag 一起记录。
- 立即改？**文件存在性必须启动前确认（1 条命令）**；口径统一属报告规范，今晚可先标注不改。

## 4. P2

### P2-0 chain CSV 的 `cum_m` 与 ckpt tag 不是同一口径
- 位置：`scripts/chain_300m.sh:41-52`（`mid -> CUM+10`、`final -> CUM+BLOCK_M`，与实际 ckpt 的 `ckpt_<decisions>.pt` tag 无关）；`scripts/auto_chain.py:98`（同样硬编码 `cum+10/cum+BLOCK`）。
- 影响：`runs/CHAIN_300M.csv` 与 `docs/TRAINING_CURVE_300M.md` 的「累计 M」是记账值，不是训练 decisions；出现「30M 对应 ckpt_020026719」这种错位，容易被读成「多训了 10M」。
- 最小修复：CSV 增列 ckpt tag（从文件名解析 decisions）与 `trainer.updates`。
- 立即改？否。

### P2-1 `human_board_rejected_by_reason` 未进日志白名单 → 39% 拒绝率的归因不可见
- 位置：`hsbg/az/train/human_board_pool.py:588-596`（`to_meta()` 输出 `human_board_rejected_by_reason: {"pending_choice": N, ...}`）；`hsbg/az/train/runlog.py:26-41`（`INJECTION_KEYS` **不含**该键）→ `:151-173 slim_collect` 随后删 `worker_meta` ⇒ history.jsonl 只剩 `human_board_rejected` 总数。
- 影响：能看出「拒绝多」，看不出「为什么多（pending_choice / not_alive / dying）」，事后无法判断注入是否系统性偏向某些回合。
- 最小修复：把键加进 `INJECTION_KEYS` + `INJECTION_DICT_KEYS`；或 worker 侧直接展平为 `human_board_rejected_pending_choice` 等计数键。
- 立即改？否。

### P2-2 注入失败为 fail-closed（设计如此），但配置的 p 与实际生效比例不同
- 位置：`hsbg/az/train/human_board_pool.py:624-765`（`inject_turn`：座位被 `pending_choice`/`not_alive`/`dying` 拒绝时该座位**保持 bot**，只计数）；`:667-675`（每座位独立掷 p）。
- 影响：`--human-board-p 0.9 --human-board-seats 3` 名义 2.7 席/回合人类战团，实际约 61%（若 39% 拒绝）⇒ 课程强度被系统性低估；对「对手强度」结论有影响，对 PPO 正确性无影响。
- 最小修复：无代码 bug 可修；建议在 `[iter]` 行加 `hb_applied/attempt` 比率，或按「实际 applied 比例」反推 p。
- 立即改？否。

### P2-3 自定义奖励改写后没有重新 validate（NaN/Inf 门禁缺口）
- 位置：`scripts/train_entity_sync.py:3792-3796`（`batch.validate()` 在奖励改写**之前**）；`:3798-3912`（`_apply_custom_rewards` 直接改 `batch.rewards/advantages/returns`）；`hsbg/az/train/ppo.py:1504-1510`（validate 会检查 rewards/values finite）。
- 触发：任一可选奖励块算出 inf/NaN（数据索引越界、除零、shape 错配）。
- 影响：NaN 进 PPO → loss/grad NaN → `clip_grad_norm_`（`ppo.py:3071`）后权重 NaN，**没有 isfinite 断言**；下次采集才可能以「动作异常/NaN logprob」暴露，表现可能是策略塌缩而日志「正常」。
- 最小修复：`_apply_custom_rewards` 返回非 None 后再调一次 `batch.validate()`（或 `np.isfinite` 三连断言）+ 在 `train_ppo` 每个 update 后断言 `stats['total']` finite。
- 立即改？否（默认全 0 时不会走到）；若今晚开密集奖励，建议加。

### P2-4 `--value-head-coef>0` 或 rank 系数≠1 时，critic 目标与 GAE 基线口径不一致
- 位置：`hsbg/az/train/common.py:49-53`（`u(r)=1-2(r-1)/7`，u∈[-1,1]）；`hsbg/az/train/ppo.py:1707-1717`（终局奖励 = `rank_utility_coef*u` + `terminal_strength_coef*L(Σ)`）；`:2547-2550`（value 头损失永远是 `rank CE`；GAE 基线是 `E[u]`）。
- 影响：当 `rank_utility_coef≠1` 或 `terminal_strength_coef>0` 时，returns 的目标尺度变了，而 critic 仍只拟合名次 CE ⇒ advantage 基线系统性偏移。今晚默认 `rank_utility_coef=1 / terminal_strength_coef=0`，**无影响**。
- 最小修复：启动期断言 `terminal_strength_coef==0 or value_loss!='rank'`；或把 `rank_utility_coef` 真正作用到 critic 目标（`u` 乘系数）。
- 立即改？否。

### P2-5 `--lr` 在 `--trainer-state` 续训时静默失效
- 位置：`hsbg/az/train/ppo_trainer.py:412-428`（`optimizer.load_state_dict` + `scheduler.load_state_dict` + 显式把 param_group.lr 设为 `get_last_lr()`）。
- 影响：想「续训但降 lr」时改了 CLI 也不会生效（实际 lr 来自 state），容易得出「降 lr 没用」的错误结论；`--max-updates` 同理以 state 为准（这是刻意的，见 `:415-417` 注释）。
- 最小修复：恢复到 `--lr` 时打印 `[warn] trainer-state 覆盖 --lr=X -> 实际 Y`；或在 load 后用 `--lr` 重设 base_lrs + `last_epoch=0`（需显式开关）。
- 立即改？否（但若今晚想降 lr，必须走 `--checkpoint` 或改 state）。

## 5. 五项特别核对（逐条结论）

1. **resume 语义**：`--checkpoint` = model + meta + norm_mean/std（`train_entity_sync.py:2821-2824`），**不**恢复 optimizer/step/LR/RNG/history/anchor；`--trainer-state` = 精确续训（`ppo_trainer.py:397-437`，含 optimizer、scheduler+`max_updates`、4 个 RNG、updates、extra）。GAE 无跨批状态（每批现算，`ppo.py:1721`），故不需要恢复。**多次 20M ≠ 一次 60M**：Adam 矩重置、LR schedule 每块重启、anchor 每块重设、ramp/value-warmup 的 `i`/`cum_decisions` 口径重来（另见 P1-1）。
2. **静默 except**：本脚本共 23 处 `except BaseException`，其中 19 处体为 `pass`（`:342,594,619,645,665,703,736,812,912,953,1070,1098,1208,1232,1311,1354,1382,1483,3310`），4 处有打印/回退（`:191,2452,3280,3816`）。默认全 0 系数时这些块不执行 ⇒ 无害；**今晚若开 comp_fit / 任一密集奖励，失败会静默变成 0**（P1-3），训练「看着正常」但语义已变。真正 P0 级的静默是 P1-4（worker 旧权重）与 `:4232` 收尾保存失败只 warn（少 `model.pt`/`trainer.pt`）。
3. **采集/竞态**：`policy_version` 错配见 P1-4。stop-at-decisions 必然 overshoot 一个 iteration（`:3763 vs :4190`），且 `--minutes` 到点会「正常退出但少训」（P1-5）。eval 与 train 抢卡见 P1-6（今晚 cuda:7 被占）。pipeline 本身顺序正确：批次版本在提交时钉死、更新后发布新版本、`lag∈{0,1}` 断言在 `:3918`；`_publish_weights`（`:3542-3563`）按 mtime 裁剪且不删刚发布文件，避免「续训版本号回落被误删」——这段实现是对的。
4. **奖励/值目标**：截断局（`max_steps` 用尽 / 引擎未结束）**不会**被当终止——单进程 `ppo.py:4472-4479` 与逐局并行 `parallel_collect.py:144-157` 直接丢弃 truncated 局；**lockstep 路径**（今晚在用）保留记录但不给 rank（`parallel_collect.py:791-794`：`rank=0`），随后被 `build_batch_from_records:1650` / `build_batch_from_arrays:4174-4177` 的 `rank∈[1,8]` 过滤掉。`dones` 只在每 episode 末步置 1（`ppo.py:1701-1719`、`:4203-4224`），因此截断局既不贡献终局 value target 也不贡献 advantage。forced（move-guard 清空 + 动作数上限）样本 `forced=True`，只进 value/critic、不进 policy/aux（`ppo.py:2497-2506`）。rank utility 目标 = 终局 `u(rank)`，值头 = 名次 CE + GAE 基线 `E[u]`，默认系数下口径一致（P2-4 是唯一例外）。
5. **回归测试**：见 §7。

## 6. 今晚启动前 checklist（可直接复制）

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM && export PYTHONPATH=rust/python:.
pgrep -af 'watch_s61|auto_chain|chain_300m|quality_monitor|quality_watch|train_entity_sync'   # 必须为空（P0-2）
ls -la runs/az_entity_s61/eval/ckpt_020026719.pt runs/az_entity_s61/trainer.pt                # 起点存在（P1-1）
ls -t runs/az_entity_s61/eval/ckpt_*.pt | head -3                                            # 起点不是被 skip 的旧 tag
jq '[.evals[]|select(.eval_skipped)]|length' runs/az_entity_s61/eval/history.json 2>/dev/null  # 是否已发生 eval_skipped（P0-1）
ls -la data/real_library/winner_library.jsonl data/real_library/library_real_degraded.jsonl  # 训练库 + 默认评测库
ls -la runs/comp_scripts/roles.json runs/comp_scripts/supply.json                           # 只在开 comp_fit 时需要
nvidia-smi --query-gpu=index,memory.used --format=csv                                        # 选 cuda:6 学习器 / 3,4,5 actor / 空闲卡评测
```
启动后 30 秒内应看到：`[net] checkpoint=... arch=entity`、`[resume] start_iter=...`、`[pool] processes=24 gpus=[...]`、`[pipeline] on`、`[eval-async] on`、`[anchor] beta=0.1`。跑 2 个 iteration 后核对：`history.jsonl` 里 `pipeline.lag∈{0,1}`、`collect.human_board_applied/attempt`、`ppo.lr` 是否等于期望起点（若用 ckpt 续训应≈1.15e-6 而不是上一块末值）。

## 7. 已落地的回归测试（本次新增，不依赖 GPU/引擎/训练）

- `tests/test_resume_contract.py`（**4 passed in 4.5s**）：
  ① `--checkpoint` 落盘只有 state_dict+meta(+norm)，断言不含 optimizer/scheduler/updates/rng；model-only 起 trainer ⇒ `updates==0`、lr=CLI（热启动，不是续训）；
  ② `PPOTrainer.save/load` 恢复 `updates`、Adam 矩（逐位 `torch.equal`）、scheduler 位置；续训时 CLI `--lr=9e-6` **不生效**（实际 1.114425e-6，锁住 P2-5）；
  ③ `AsyncEvalRunner` 在 `running()` 时 `submit→False` 且只记 `eval_skipped`、**不产生 ckpt**（P0-1 成因）；
  ④ 复现 chain 选择形态：只有 10M ckpt 时 `ls -t|head -1` 取 10M，而 `CUM` 已 +20M（含建议守卫断言）。
- `tests/test_truncation_not_terminal.py`（**2 passed in 0.16s**）：1 完整局(rank=3)+1 截断局(rank=0) ⇒ 截断行被丢（`dropped_unknown_rank==2`）、每 episode 恰一个 `done` 且在末步、`returns[-1]==u(3)`、`ret[t]==(γλ)^(T-1-t)·u3`；SoA `build_batch_from_arrays` 与 dict `build_batch_from_records` 逐字段一致。
- 运行（远端 CPU）：`PYTHONPATH=rust/python:. python -m pytest tests/test_resume_contract.py tests/test_truncation_not_terminal.py -v` ⇒ **6 passed in 3.24s**。注意 `pyproject.toml` 已有 `addopts=-q`，再叠 `-q` 会连 summary 一起吞掉，看结果用 `-v`。
- 后续可选：`tests/test_injection_meta.py` 加 `human_board_rejected_by_reason`（当前会被 `slim_collect` 丢掉，正好把 P2-1 变可追踪）。

## 8. 补充工作记录（Lead 追加：smoke 复核 + 正式跑观测）

### A-1 精确续训 smoke（`/tmp/smoke_p2b01.out`，exit=0，34s，290 updates，2×GPU）
- resume：`[trainer] loaded updates=285 lr=1.11e-06` / `[resume] start_iter=285` / history 首行 `[iter 285]` ✅
- lr：s61 state `base_lrs=[1.17e-6] last_epoch=285 max_updates=3000 lr_min_ratio=0.5` → 期望 1.114425e-6，实测 1.11423e-6 → 1.11345e-6（每 update 递减）✅
  注：本次 smoke 的 CLI `--lr` 与 s61 state 的 `config.lr` 同为 1.17e-6，**不能区分 CLI 是否被覆盖**；P2-5 由 §7 ② 用 9e-6 反向断言钉死。
- trainer.pt 收尾：`updates=290`、`last_epoch=290`、`_last_lr=1.11345e-6`、`optimizer.state` 131 项 ✅
- pipeline：lag 0,1,1,1,1；pre_ratio 1.000/0.9994/0.999/0.9982/0.9998 ✅；无 silent exception（仅 `enable_nested_tensor` UserWarning，无 Traceback/failed/skipped）✅
- human-board：每 iter attempt≈2600-2716 / applied≈1568-1654 / rejected≈983-1062 ⇒ **拒绝率 39.0%±0.5%**（与已知 ~39% 吻合）；history 里 `human_board_rejected_by_reason` 计数为 0 ⇒ **P2-1 实证**（只有总数无归因）。
- stop 溢出：58011 vs 50000 = +16%（smoke iteration≈11.5k）；正式跑 iteration≈71k，20M 处仅 +0.35%。

### A-2 正式跑 `runs/az_entity_s73`（首启 00:10:05，Lead 于 00:13:29 重启）
- 首启（`--gpu-free-check 1`）：GPU3 已被占 5276MiB → 自动剔除，actor 仅 [4,5]（12 进程/卡）；iter 285-287 实测 lag 0→1→1、ratio 1.000/0.9992/0.9979、trunc=0、illegal=0、forced 98-117/iter、hb reject 39.2%、total 0.53/0.87/0.87（无 NaN），稳态 11-14s/iter（≈71k decisions）≈5.0-6.4k dec/s。
- 重启（00:13:29，`GPU_FREE_CHECK=0`）：仅此一项变化（gpus=[3,4,5]，8 进程/卡）；`--trainer-state`+`--checkpoint`、`--eval-drain 1`、`--eval-device cuda:1`、comp_fit=0 均与 §6 建议一致；启动行同上（`[resume] start_iter=285`、`lr=1.11e-06`）。00:16:56 复核：history 已到 iter 291（7 个 iter），lag=1、ratio 0.998-1.001、~71k samples/iter、迭代间隔 ~11s ⇒ **~6.4k dec/s，20M≈50-60min**；无 Traceback/OOM。GPU3/5 各 10.2GB、GPU4 5.0GB、GPU6（learner+邻居）14.5GB / 24GB。
- 环境 warn（非代码 bug）：`评测卡 cuda:1 已被占用 1711MiB`；learner 在 cuda:6 与邻居共存（24GB 卡）。20M 估约 0.7-1h，远低于 `--minutes 400`。

### A-3 测试暴露的小 bug（新增 P2，未修复）
`save_checkpoint` 不落 `hidden`、`load_checkpoint` 对 tiny 固定 `hidden=int(meta.get("hidden", 256))`（`hsbg/az/train/model.py:308/:358`）⇒ 任何 `build_net(hidden≠256)` 的 ckpt 无法回读（size mismatch）。CLI 不可达（`--arch tiny` 固定 256），脚本/沙盒/测试会踩；建议 `payload["meta"].setdefault("hidden", int(getattr(model, "hidden", 256)))`。

### A-4 仍未验证
- s61 `eval/history.json` 是否已有 `eval_skipped`：`jq '[.evals[]|select(.eval_skipped)]|length' runs/az_entity_s61/eval/history.json`。
- `runs/comp_scripts/{roles.json,supply.json}`（今晚 comp_fit=0，不影响）；`winner_library.jsonl` 存在性已被 s73 实证存在（否则 `:2443-2445` 直接 return 2）。

## 9. task-11：门禁 pytest 修复记录（6 failed → 0 failed；tests/ + 1 处最小生产修复）

- `tests/test_az_replication_bc.py`：fixture 补 `features(3227)`/`turns`（生产 `_attach_replication_bc_labels` 在 `scripts/train_entity_sync.py:242-243` **无条件**读取；真实 `PPOBatch` 两者都有）⇒ 5 项恢复；另新增 `test_upgrade_curve_labels_from_features` 覆盖 `want_upgrade=True` 的 tier/gold/price/turns 分支（此前无覆盖）。
- `tests/test_process_pool.py::test_reload_detects_worker_death_after_ack`：断言未削弱（`w0_acks>=2` / `done==2` / `elapsed<9.5` 原样保留），只把消息交错改成确定性（worker1 的 ack 排在 worker0 第二次 ack 之后）⇒ 5 次文件级复跑 0 失败。
- **附录 B：生产缺陷（P2）已按 Lead 批准最小修复** —— `reload_weights`（`hsbg/az/train/process_pool.py:1076-1139`）原先只按 `task_id` 接受 ack：worker ack 后被杀 → `_resync` 检测 pid 变化并重发，但**重启前遗留的 ack** 若在重发之后被消费，会提前满足 pending ⇒ 返回成功时重启 worker 尚未加载新权重（确定性复现：`done=2, w0_acks=1`）。修复：worker 的 `reload_done/reload_error` 增加 `pid=os.getpid()`；父进程忽略 `pid != _info[w]["pid"]` 的陈旧 ack（**向后兼容**：无 `pid` 字段的旧消息仍按原逻辑接受）。未触碰 `collect()` 语义：`test_reload_weights_survives_worker_kill`（真实 worker 被杀 + 真 ack）与全部 collect 用例通过。回归用例 `test_reload_stale_ack_after_restart_is_not_counted` 现为**正常断言**（非 xfail）。
- 门禁（远端 CPU，`CUDA_VISIBLE_DEVICES=''`，pytest 无 timeout 插件故未传 `--timeout`）：`python -m pytest tests -v` ⇒ **950 passed / 11 skipped / 0 failed / 313.26s**（修复前基线 949 passed / 11 skipped；+1 为新增回归用例）。
