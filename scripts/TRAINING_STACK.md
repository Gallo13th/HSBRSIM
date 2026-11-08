# 训练栈取证与干净训练配置（2026-11-04）

> 范围：s59–s72 这 14 个 run、两条失控链（`scripts/chain_300m.sh`、`scripts/auto_chain.py`）、
> 以及 `scripts/train_entity_sync.py`（4289 行）的训练/评测/resume 语义。
> 所有数字均来自远端 `/home/data/users/gaoletian/projects/HSBRSIM` 的实测（命令见文末附录）。
> 唯一评测口径：`scripts/eval_panel.sh`（真实库 5 席 p0.9 / full fidelity / p75 / 96 局 / seed 520000）。

## 0. 结论（TL;DR）

1. **权威基线 checkpoint = `runs/az_entity_s61/eval/ckpt_020026719.pt`**
   `sha256 a2bd7f0c58b0722c5d1fe4e662334bde9ce3d114a06d754aff441ec3c0f4478c`（67,864,699 B）。
   权重与 `runs/az_entity_s61/model.pt` **逐张量完全相同**（max_abs_diff=0.0），
   entity 384d/8L/8H、**16,436,034 参数**；s61 本块跑满 **20,026,719** decisions（stop-at-decisions 命中），
   按文档口径累计 ≈ **30.07M**（s59 的 10.04M + 20.03M；若含 s58 的 2.03M 则链上真实累计 32.10M）。
2. **s62_final / s63_final 是 chain 复评旧 ckpt，不是新数据点**：三者 eval JSON md5 全为
   `52ddb7e3cf665fe2cd5afd9d3241a2e4`，逐字节相同（见 §1.2）。s62/s63 目录**没有 `eval/` 子目录**，
   即根本没产出可评 checkpoint；CSV 里 60M/80M 两行（323.5 / 6.083）必须从曲线删除。
3. 96 局口径的 rank 标准误约 0.2（名次 SD≈2），**323.5 vs 323.0、6.083 vs 6.292 都在噪声内**；
   「s61@30M 历史最优」只能表述为「已评测点中唯一 mean_rank < 6.29 的点」，A/B 结论需 ≥288–384 局复评。
4. 两条链**不是串行续训**：两个 watcher 各起一个 `chain_300m.sh`，同一 `--out` 目录双写导致权重目录竞争、
   CUDA OOM、以及 3 个 trainer 同抢 GPU 3,4,5（s65 51 分钟只跑 8 iteration，s61 是 285 iter/44min）。
5. 干净单块 = `scripts/train_block_clean.sh`：`next_block.sh` 逐字基线 + `--checkpoint`+`--trainer-state`
   精确续训（恢复 optimizer/updates/LR/RNG），默认 `OUT=runs/az_entity_s73 SEED=27301 STOP=20M`，
   actors 3,4,5 / learner cuda:6 / eval cuda:1，comp-fit 三开关默认 0，结束自动 `eval_panel.sh ... ${TAG}_panel 96`。

## 1. 基线取证表（s59–s72）

口径说明：
- 「本块」= 该 run 进程内累计的 decisions（`--stop-at-decisions` 是**进程内**口径，不是全局累计）；
- 「累计(文档)」= 以 s59 的 10.04M 记为 10M 的链条口径（`docs/TRAINING_CURVE_300M.md` 用的就是它）；
- 产出 ckpt 的 sha256 均取前 16 位；未产出 = 目录里没有 `eval/ckpt_*.pt`；
- 可信度：**高** = canonical 口径 + ckpt 真实产出；**中** = ckpt 有效但块被外部终止；
  **作废** = 无 ckpt / 复评旧 ckpt / 空 JSON。

| run | 起点 ckpt (sha256/16) | 本块 decisions | 累计(文档) | 产出 eval ckpt (sha256/16) | strength | mean_rank | top4 | tier≥4 | survive12 | 可信度 |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|
| s59@5M | s58 `ckpt_002031511` (67446e38) | 5,023,475 | 5.02M | `ckpt_005023475` (645f6cd9) | 265.0 | 6.396 | 7.29% | 71.88% | 13.54% | 高 |
| s59@10M | 同上 | 10,042,271 | 10.04M | `ckpt_010042271` (a3639f58) | 323.0 | 6.458 | 7.29% | 68.75% | 8.33% | 高 |
| s60 | s59 `ckpt_010042271` (a3639f58) | 0 | — | 无 | — | — | — | — | — | 作废（仅 header） |
| s60b@10M | s59 `ckpt_010042271` | 10,026,104（该 run 实跑 13,924,441 后停止，未达 20M） | 20.03M | `ckpt_010026104` (21a7b625) | 259.5 | 6.406 | 12.50% | 68.75% | 12.50% | 中 |
| s61@10M | s59 `ckpt_010042271` | 10,017,876（该 run 共 20,026,719，跑满 20M） | 20.02M | `ckpt_010017876` (aa61d189) | 259.0 | 6.292 | 15.63% | 63.54% | 14.58% | 高 |
| **s61@20M** | 同上 | 20,026,719（stop-at-decisions 命中） | **30.07M** | **`ckpt_020026719` (a2bd7f0c)** | **323.5** | **6.083** | 14.58% | 66.67% | 11.46% | **高（基线）** |
| s62_final | s61 `ckpt_020026719` | 5,975,469（被杀） | — | 无（无 eval/ 目录） | 323.5* | 6.083* | 14.58%* | 66.67%* | 11.46%* | **作废（复评 s61）** |
| s63_final | s61 `ckpt_020026719` | 88,066（1 iter 后被杀） | — | 无（无 eval/ 目录） | 323.5* | 6.083* | 14.58%* | 66.67%* | 11.46%* | **作废（复评 s61）** |
| s64_final | s61 `ckpt_020026719` | 0（CUDA OOM） | — | 无 | — | — | — | — | — | 作废（JSON 0 字节） |
| s65 | s61 `ckpt_020026719` | 702,629（8 iter / 51 min） | — | 无 | — | — | — | — | — | 作废 |
| s70 | s61 `ckpt_010017876` (aa61d189) | 0（22:59 被 cleanup 杀） | — | 无 | — | — | — | — | — | 作废 |
| s72@10M | s61 `ckpt_020026719` | 15,676,321（220 iter，`--minutes 120` 到点） | 40.11M | `ckpt_010035968` (a2a187a5) | 277.5 | 6.302 | 12.50% | 60.42% | 17.71% | 高 |

\* 号数值即 s61_20m 的重复行（见 §1.2），不是新数据。
注：s72 的 `model.pt`（15.68M decisions）**没有** canonical 评测，上表是它 10.04M 处的 eval ckpt。

### 1.1 评测原始值（eval_panel JSON）

| tag | md5 | rank | top4 | strength | tier4+ | survive12 |
|---|---|---:|---:|---:|---:|---:|
| s59_5m | 844e335c22c0d16184abe14a2e9bafc0 | 6.396 | 7.29% | 265.0 | 71.88% | 13.54% |
| s59_10m | 19255821bdd8f3aadb3a91a7a1fb738f | 6.458 | 7.29% | 323.0 | 68.75% | 8.33% |
| s60b_10m | 3ca14557dc9316265f660cfe699c2487 | 6.406 | 12.50% | 259.5 | 68.75% | 12.50% |
| s61_10m | f30b70c9995785ba8f87d63f7b928461 | 6.292 | 15.63% | 259.0 | 63.54% | 14.58% |
| s61_20m | 52ddb7e3cf665fe2cd5afd9d3241a2e4 | 6.083 | 14.58% | 323.5 | 66.67% | 11.46% |
| s62_final | 52ddb7e3cf665fe2cd5afd9d3241a2e4 | 同 s61_20m | | | | |
| s63_final | 52ddb7e3cf665fe2cd5afd9d3241a2e4 | 同 s61_20m | | | | |
| s64_final | d41d8cd98f00b204e9800998ecf8427e（空文件） | — | — | — | — | — |
| s72_10m | d043dac8575a9599319e043bf0dee019 | 6.302 | 12.50% | 277.5 | 60.42% | 17.71% |

### 1.2 「s62/s63 = 复评旧 ckpt」的证据链

1. `md5sum runs/eval_panel/s61_20m.json runs/eval_panel/s62_final.json runs/eval_panel/s63_final.json`
   → 三个 `52ddb7e3cf665fe2cd5afd9d3241a2e4`；`diff` 逐字节相同。
2. `ls runs/az_entity_s62 runs/az_entity_s63` → **没有 `eval/` 子目录**，即训练从未落 eval ckpt。
3. `chain_300m.sh:12-13` 起点 `CK` 固定；`:38-39` `NEW=$(ls -t $OUT/eval/ckpt_*.pt | head -1)`，
   取不到就 `CK` 保持旧值；`:41-50` 仍用旧 `CK` 调 `eval_panel.sh`。
4. `eval_panel.sh:14` 固定 `--seed-base 520000 --games 96`，输出 JSON 无时间戳/无 ckpt 字段 ⇒
   **同 ckpt + 同 seed 逐字节确定性复现**。
5. 因此：s62/s63 的 323.5/6.083 是 s61 的重复测量，不是 60M/80M 的新点。

## 2. 训练栈解剖（`scripts/train_entity_sync.py`）

### 2.1 模型
- `arch=entity`：entity Transformer，`d_model=384`、`n_layers=8`、`n_heads=8`，**16,436,034 参数**
  （`build_net` / s61 checkpoint meta 实测）。
- 输入：obs 3227 floats + 124 cards；动作 245 维（0..244 合法，扩展 29 维仅 Python 侧声明，引擎 `legal_mask` 固定 245）。
- 输出：policy logits（masked softmax）+ `rank_head`（8 名次分布，3,080 参数；value = Σ p·u(rank)）。
  名次效用 `u(r)=1−2(r−1)/7`：`[+1,+0.714,+0.429,+0.143,−0.143,−0.429,−0.714,−1]`（`common.py:49-53`）。

### 2.2 PPO（s61/next_block 实测配置）
- 目标：`-min(r·A, clip(r,1±ε)·A)`，ε=0.2；终端奖励 = `rank_utility_coef(1.0)·u(final_rank)`
  （`terminal_strength_coef=0`，`ppo.py:1708-1716`）。
- GAE：γ=1.0、λ=0.995（`--lam`）；1 epoch，minibatch 1024 × grad_accum 8 = **有效 8192**；
  grad clip 1.0；entropy 0.001；`pi_coef=0`。
- LR：`1.17e-6` 线性衰减到 `lr_min_ratio=0.5`，`max_updates=3000`
  （`ppo_trainer.py:65-66`：`lr·(1−(1−ratio)·step/max_updates)`）；实测 step 285 时 lr=1.114e-6。
- KL 早停：`target_kl=0.02`，`kl_early_stop=True`，当 `approx_kl > 1.5×target_kl` 提前结束该 epoch（`ppo.py:3087`）。
- KL anchor：`anchor_beta=0.1`，anchor = **本块起点策略** 的冻结副本，前 `anchor_iterations=100000` iter
  加 `β·KL(π_θ‖π_anchor)`，之后 `anchor_beta_tail=0.1`（等于全程 0.1）；`anchor_amp=1` 走 bf16 参考前向。
- critic 预热：`value_warmup_iters=5`，每 100 iter 一次（冻结 trunk 只训 `rank_head`，rank_ce，lr 1e-3）。

### 2.3 对手与人类战团注入
- 8 座自对弈；`opponent=bot`、`behavior=net`（sims=0，纯策略 rollout）。
- 人类战团：`--human-boards data/real_library/winner_library.jsonl`，
  **3 席 × p=0.9**，`fidelity=board`，`sample=auto`，`set-tier=1`；`--library-p 0.0`、`--mirror-seats 0`。
- **只在 `--lockstep 1` 采集路径生效**（`train_entity_sync.py:2464` 的 warn；非 lockstep 会被静默忽略）。

### 2.4 采集
- `process_pool`：24 进程 × 3 线程，`gpus=3,4,5`（8 进程/卡），384 局/iteration，`sims=0`（无 MCTS）。
- IPC：`shm`（slots=2）、`records-dtype=fp32`、bf16 推理；`pipeline=1`（collect(k+1) 与 update(k) 重叠，
  batch 版本钉死 lag≤1）；`lockstep=1`；实测 ~11.5–12.2k decisions/s、单 iter ~6 s 采集 + ~6 s 更新，
  s61 跑 20.03M decisions 用了 285 iter / 2497 s。

### 2.5 评测（两套口径，不能混用）
| | canonical `eval_panel.sh` | in-training 异步 human panel |
|---|---|---|
| 脚本 | `quality_monitor.py` | `human_panel_eval.py`（`scripts/async_eval.py` 调度） |
| 局数/席数 | 96 / 5 席 | 96 / 8 席 |
| seed | **520000** | **420000** |
| 人类库 | `library_real_quasi_full.jsonl` | `library_real_degraded.jsonl`（默认 `eval_human_boards`） |
| 分位/保真度 | p75 / full | auto / 默认 |
| 用途 | 唯一对外指标（曲线/AB） | 仅监控；**不能**与 canonical 数字比较 |

`eval_async` 细节：并发上限 1；上一个评测未完成时**不落 ckpt**，只记 `eval_skipped`
（`train_entity_sync.py:3450-3454`）；训练收尾 `eval_runner.close(drain=bool(args.eval_drain))`，
`drain=0` 会**终止**在跑评测（本次事故里 s61 的 20M 评测就是这样丢的，`human_020026719.log` 0 字节）。

### 2.6 checkpoint / resume 语义
- `--checkpoint`：只 `load_checkpoint` → 模型权重 + norm_mean/norm_std；`PPOTrainer` **新建**，
  optimizer/updates/LR schedule **全部重置**；arch/尺寸以 checkpoint meta 为准（`--d-model 0` 表示不覆盖）。
- `--trainer-state`：`PPOTrainer.load` 恢复 **updates、optimizer(Adam step)、scheduler(LR)、RNG、history**；
  需同一架构（next_block 传 `--d-model 0` 等即用默认 384/8/8，与 s61 一致）。
- 两者同时给（今晚配置）：先用 ckpt 建网，再载 trainer state；anchor 在恢复后 `set_anchor()` 到**当前策略**，
  与旧块"同一起点"一致。smoke 实测：`[resume] start_iter=285 updates=285`、
  `[trainer] loaded updates=285 lr=1.11e-06`、history 首条 `iter=285`、保存后 `trainer.pt updates=290`、
  optimizer `step=2575`（= s61 的 285×9=2565 + smoke 10 步）⇒ 不是重置。
- `cum_decisions` **每次进程启动从 0 计** ⇒ `--stop-at-decisions` 是块内口径；`--minutes` 也从进程启动计时，
  且 `remaining < last iteration` 会提前停（`train_entity_sync.py:3767`）。
- checkpoint 落盘：`--snapshot-every 100` iter → `snapshots/step_XXXXXX/{trainer,model}.pt` +
  扁平 `model.pt`/`trainer.pt` + `latest.json`；`--keep-snapshots 4` 按名字裁旧。
  结束时 `finally` 一定再存一次 `model.pt`+`trainer.pt`（`:4214-4231`）。
- eval ckpt：`eval/ckpt_{decisions:09d}.pt`（`_save_eval_ckpt`，`:3243-3250`）。

## 3. 两套失控链的 bug（含证据）

### 3.1 `chain_300m.sh`（本次实际执行的链）
1. **无单实例保护**：`watch_s61_then_chain.sh:2` 用 `pgrep -f "az_entity_s6[1]"` 等待，两个 watcher 各触发一次
   → `runs/CHAIN_300M.log:1-2` 两行 `[watcher] s61 done`、`:3` 与 `:12` 两行 `[chain] start s62 cum=40M`。
   同一 `--out runs/az_entity_s62` 被两个进程写 header/`_weights/`，`worker8 采集失败: weights reload failed:
   FileNotFoundError .../_weights/w_000001.pt`（log:150）。
2. **CK 不更新仍继续评**：`:38-39` 取不到新 eval ckpt 时 `CK` 保持旧值，`:41-50` 照样 eval → s62/s63 复评 s61
   （§1.2）。`s62/s63` 目录无 `eval/` 可证。
3. **累计 M 无条件 +BLOCK**：`:53` `CUM=$((CUM+BLOCK_M))` 不看本块是否真的产出/失败 ⇒ CSV 的 60M/80M 是伪造进度
   （log:164、:284 写入 323.5/6.083；现存 CSV 只剩 80/100 两行，100 行为空）。
4. **起点/口径错位**：`START_M=40`，但 s61 实际是 30.07M 累计（且忽略 s58 的 2.03M）⇒ 所有 cum 标签偏 10M 以上。
5. **解析 stdout 而非 JSON**：`:44-49` `tail -1` + `sed` 抓 strength/rank；eval 被 kill/输出 0 字节（s64_final.json=0）
   时照样 append 空行 `100,,,,,,s64_final`；`eval_panel.sh` 非零退出也不会中止链。
6. **`--minutes 400` 与 20M 不匹配**：s65 因与 s72 抢卡 51 分钟只跑 8 iter，仍被算作一个块；
   `:21-37` 无 `--out` 复用检查，续跑会往旧目录追加。
7. **eval 卡 `cuda:7`**：当晚 GPU7 被他人 96–98% 占用（Lead 快照 `gpu_before.txt`），评测严重变慢。

### 3.2 `auto_chain.py`（第三套链，23:42 启动后卡在等待，未真正开跑）
1. `:51-52` 只在**启动时**等一次 `running()>0`；之后无锁 → 与刚启动的 chain 直接竞争。
2. `:55-59` 用"最新 sNNN +1"猜 step，与 `chain_300m.sh` 的 `step=62` 计数器必然撞目录（都写 s6x）。
3. `:93-97` 失败时 `continue` 但不 `cum += BLOCK` ⇒ 可能无限重试；`:94` 的 abspath 过滤恒真（形同虚设），
   复用的 out 目录里旧 ckpt 会被当成本块产物。
4. `:60-62` 从上一个 run 的 `history.jsonl` 首行继承 args（`hist_args`）⇒ 任何历史开关（如 `--eval-device cuda:7`）
   会被静默带到新块，且只保留首行里出现过的参数。
5. `:71` 每轮调用 `/tmp/cleanup.sh`：该脚本 `pgrep -u gaoletian -f train_entity_sync | kill -9` +
   杀所有 cwd 在 HSBRSIM 的 GPU 进程 ⇒ **会杀掉同机任何其他训练**（22:59 s63/s64/s70 同时死亡、23:00 重启即此模式）。
6. `:98` tag 用 `sNNN_mid/sNNN_end`，与 chain 的 `sNNN_final` 混在同一个 `runs/eval_panel/` 目录，命名不可区分。

### 3.3 时间线（`runs/_lead/status_20261103/procs_before.txt`）
- 22:21 s61 结束；22:3x 两个 chain 实例各起 s62（日志双 `start s62` 行；s62 目录 22:35 创建）。
- 22:35 s72 第一次启动；22:42 s63 起（此时 s62 仍在跑）→ 3 个 trainer 并存。
- 22:50 s63 停；22:59 s64(CUDA OOM) 与 s70 都在 22:59:1x 死亡（疑似 cleanup 型批量杀）；23:00 s65 与 s72 重启，同抢 3,4,5。
- 23:54 Lead 停机：可见 `chain_300m.sh`(297675)、其子 trainer(353043)、独立 s72 trainer(353544)、`auto_chain.py`(410288)。
- 结果：205GB/277 个 runs 目录里，当晚真正有效的只有 s72 的 10M eval 和 s61 的既有结果。

## 4. 下一步推荐配置（今晚）

**单块、单进程、精确续训**（`scripts/train_block_clean.sh` 默认值即此配置）：

```
CK=runs/az_entity_s61/eval/ckpt_020026719.pt
TS=runs/az_entity_s61/trainer.pt
OUT=runs/az_entity_s73  SEED=27301
STOP_DECISIONS=20000000  GAMES=384  PROCESSES=24  GPUS=3,4,5
DEVICE=cuda:6  EVAL_DEVICE=cuda:1
COMP_FIT_COEF=0  COMP_FIT_T9_BONUS=0  COMP_TRINKET_COEF=0
其余开关 = runs/next_block.sh 逐字（--minutes 400 --iterations 8000 --eval-every-decisions 10000000 --eval-games 96）
```

- 唯一改动是**恢复语义**（`--checkpoint`+`--trainer-state`）：恢复 optimizer/updates/LR/RNG，anchor 在恢复后
  重新 `set_anchor()` 到当前策略。Comp-fit 三项保持 0（comp-audit/astra 均否决）。
- 开跑前：`pgrep -u gaoletian -f train_entity_sync.py` 必须为空（脚本默认拒绝并行；`ALLOW_RUNNING=1` 才能强跑）；
  确认 GPU 6/1 上没有他人进程（00:07 实测 GPU6 有 l00-score 5.2–6.5GB、GPU1 有 1.7GB）。
- 结束时自动 `EVAL_DEVICE=cuda:1 bash scripts/eval_panel.sh $OUT/model.pt ${TAG}_panel 96`。
- A/B 规则：同起点 ckpt、同 seed、只改一个变量（comp_fit 若启用，建议 0.05 起）；
  96 局只做筛选，rank 差 <0.3 时用 288–384 局复评再下结论。
- 不要再用 `chain_300m.sh` / `auto_chain.py`（尤其 `auto_chain.py:71` 的 kill-all cleanup）。

## 5. 会改训练语义的开关清单（改任何一个都应视为新实验）

| 类别 | 开关 | clean 值 | 影响 |
|---|---|---|---|
| 目标函数 | `--rank-utility-coef` / `--terminal-strength-coef` | 1.0 / 0.0 | 终端奖励 = u(rank) [+强度] |
| 新增奖励 | `--comp-fit-coef` / `--comp-fit-t9-bonus` / `--comp-trinket-coef` | 0 / 0 / 0 | 复利结构/饰品奖励项 |
| 旧奖励 | `--tier-bonus --upgrade-reward --win-only-reward --strength-reward-coef --shaping-coef --seq-coef --bc-coef --dpo-coef` | 0 | 全部关 |
| 优化器 | `--lr --lr-min-ratio --max-updates --clip --target-kl --lam --gamma --entropy-coef --pi-coef --grad-accum --minibatch --epochs` | 1.17e-6 / 0.5 / 3000 / 0.2 / 0.02 / 0.995 / 1.0 / 0.001 / 0 / 8 / 1024 / 1 | 更新幅度与 KL |
| anchor | `--anchor-beta --anchor-iterations --anchor-beta-tail --anchor-amp` | 0.1 / 100000 / 0.1 / 1 | 对起点策略的 KL 约束 |
| critic | `--value-warmup-iters --value-warmup-every` | 5 / 100 | critic 初始化 |
| 对手分布 | `--human-board-p --human-board-seats --human-board-fidelity --human-board-sample --human-boards --library-p --mirror-seats` | 0.9 / 3 / board / auto / winner_library / 0 / 0 | 对手强度与构成 |
| 采集机制 | `--lockstep` / `--pipeline` / `--processes` / `--gpus` / `--games` / `--sims` / `--determinizations` / `--behavior` / `--opponent` | 1 / 1 / 24 / 3,4,5 / 384 / 0 / 1 / net / bot | lockstep=0 会静默关闭人类注入 |
| 数值 | `--amp` / `--compile-train` / `--leaf-amp` / `--records-dtype` / `--ipc-mode` | bf16 / 1 / off / fp32 / shm | 可能改变轨迹（非严格逐位） |
| 动作空间 | `--move-guard --move-cap --move-repeat-limit` | 1 / 3 / 2 | 采样前 mask，改变行为策略 |
| 课程 | `--curriculum-stage --gold-curriculum --ramp-mode/… --dyn-curriculum` | none / 0 / step 默认关 / 0 | 对手/金币课程 |
| 纯监控（不改学习） | `--eval-*`（除 `--eval-stop-mean-rank`）/ `--snapshot-*` / `--log-every` | 见基线 | 只影响记录与提前停止 |

## 附录：取证命令（可复现）

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
md5sum runs/eval_panel/*.json
sha256sum runs/az_entity_s61/eval/ckpt_020026719.pt runs/az_entity_s61/model.pt
diff runs/eval_panel/s61_20m.json runs/eval_panel/s62_final.json   # 无输出
ls runs/az_entity_s62 runs/az_entity_s63                            # 无 eval/ 子目录
grep -nE '^\[chain\]|^\[watcher\]' runs/CHAIN_300M.log
cat runs/eval_panel/s61_20m.json        # 权威基线 96 局原始指标
# 权重等价 / resume 核对：本次取证用的临时脚本已删除；关键命令即上面 sha256sum/md5sum/ls/grep，
# 以及 torch.load(runs/az_entity_s61/trainer.pt) 读 updates=285、optimizer step=2565。
```

相关文件：`scripts/train_block_clean.sh`（新）、`scripts/chain_300m.sh`、`scripts/auto_chain.py`、
`scripts/watch_s61_then_chain.sh`、`scripts/eval_panel.sh`、`scripts/async_eval.py`、
`runs/next_block.sh`、`runs/CHAIN_300M.log`、`runs/CHAIN_300M.csv`、`runs/_lead/status_20261103/`。
