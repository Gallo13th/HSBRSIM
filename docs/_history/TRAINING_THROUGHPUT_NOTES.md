# 训练吞吐笔记：异步 C0 评测 + 多 GPU actor

> 目标：把 entity PPO 训练吞吐从 **~5.65k decisions/s** 拉回 **≥6.5k**。
> 手段：(a) 评测异步化（不再阻塞训练）；(b) 用空闲 GPU（4/5）扩 actor。
> 本文只记录当前代码实际行为和本机实测数字；命令均可在仓库根目录复现。

## 1. 现状（runs/az_entity_s5，2026-10-29 实测）

| 指标 | 数值 |
|---|---|
| 每 iteration 墙钟 | **~7.79 s**（collect 5.98 s + PPO ~1.8 s，pipeline 已重叠） |
| 每 iteration decisions | ~44,042（192 局 × ~229 决策） |
| 吞吐 | **~5.65k decisions/s** |
| 周期评测 | 每 5M decisions 一次 **512 局 C0**，同步阻塞 **~667 s（11.1 min）** |
| 100M 全程评测开销 | 20 次 × 667 s ≈ **3.7 h**（占 100M 预算的 ~17%） |
| 评测卡 | 旧命令 `--eval-device` 空 -> 跟随 `--device`（cuda:2，与 learner 同卡） |
| GPU 现状 | 0/1/3 = actor（各 ~2.4 GiB），2 = learner+eval（~8.3 GiB），**4/5/6/7 空闲** |

**为什么吞吐是 5.65k 而不是 6.5k+**：collect+PPO 的纯训练节奏其实对应
`44042 / 7.79 ≈ 5.65k`；再算上每 5M 一次的 667 s 阻塞，100M 全程平均只有
`100M / (100M/5.65k + 3.7h) ≈ 3.2k decisions/s`。所以两件事必须一起做：

1. 去掉评测对主循环的阻塞（这是 wall-clock 上最大的一块，**3.7 h -> 0**）；
2. 扩大 actor 并发（collect 5.98 s -> ~4.5 s），把纯训练节奏本身推到 ≥6.5k。

## 2. 异步评测（`--eval-async 1`，默认 0 = 旧同步行为）

### 2.1 用法

```bash
--eval-async 1 --eval-device cuda:4        # 默认 0；异步时 --eval-device 缺省 = cuda:4
--eval-every-decisions 5000000 --eval-games 512 --eval-seats 8 --eval-seed-base 420000
--eval-drain 0                             # 训练退出时是否等待在跑的评测（默认 0=终止）
--eval-stop-mean-rank 0                    # 可选早停阈值（0=关闭，见 2.4）
```

### 2.2 行为

- 到 `eval_every_decisions` 时：先原子落 `eval/ckpt_<decisions>.pt`（与旧路径同一格式），
  然后把 `scripts/c0_gate.py` 交给**独立子进程**（`--device` 用 `--eval-device`，
  `--smoke --bootstrap 1000` 等参数与旧路径逐项一致），主循环**不等待**；
- 子进程结束后，一个轻量 `threading.Thread`（不碰 torch/CUDA）把结果追加到
  `eval/history.json`（外层 `{"evals": [...]}`，完成记录字段与旧 schema 完全一致；
  按 `decisions` 排序），并在父日志打印
  `[eval-async] dec=... mean_rank=... top4=... win=...`；
- **并发上限 1**：到点时上一个评测还在跑 -> 不落新 ckpt、直接跳过，history 追加
  `{"decisions": ..., "skipped": true, "eval_skipped": true, "reason": "eval_in_flight"}`
  （无 `mean_rank`，绘图脚本自动忽略），父日志打印 `[eval-async] skipped dec=...`；
- **失败不崩**：子进程非 0 / 缺结果 JSON -> `error` 字段入 history，父日志打印
  `[eval-async] FAILED dec=... rc=... error=...` 并附 stderr 尾部（`c0_<tag>.err.log`）；
  注意 `c0_gate.py --smoke` 退出码**恒为 1**（smoke 不产生 `passed`），只要 JSON 能解析出
  `panels[0]` 就算成功，不算失败；
- 收尾：默认终止在跑子进程（不拖 wall，打印 `aborted ...`）；`--eval-drain 1` 才等待并
  把最后一个结果落 history；
- 早停/回滚：见 2.4。

### 2.3 实测（本机，GPU4=actor / GPU5=eval / GPU6=learner，不碰 s5 的 0/1/2/3）

配置：`--processes 2 --gpus 4 --games 96 --pipeline 1 --lockstep 1 --eval-games 32`。

| 模式 | iteration 时间戳 | 主循环 wall/iter | 评测 |
|---|---|---|---|
| 同步 `--eval-async 0` | 13:06:59 / 13:07:01 / **13:07:35** | 4.2 / 2.7 / **33.9** s | 31.4 s 阻塞在 iter 1 后 |
| 异步 `--eval-async 1` | 13:06:13 / :15 / :20 / :25 | 4.1 / 2.7 / 5.2 / 4.7 s | 31.6 s 评测期间 iteration 照常推进 |

- 同步 run：`elapsed=84 s / 3 iter`；异步 run：`elapsed=39 s / 4 iter`（含 31.6 s drain），
  纯训练段 4 iter ≈ 12 s。同步的 33.9 s 正是评测阻塞。
- 异步结果落盘校验：`eval/history.json` 里完成记录
  `{decisions, rc:1, seconds:31.6, mean_rank, bot_mean_rank, top4, win, mean_diff,
  ci_low, ci_high, illegal, truncated, passed}` 与同步路径逐字段一致；
  跳过的 2 次是 `eval_skipped` 记录且**没有**多写 61 MB ckpt。
- 另做了一次「评测在训练中完成 + 早停」验证（`--iterations 12 --games 64
  --eval-every-decisions 8000 --eval-games 16 --eval-stop-mean-rank 9`）：
  `[eval-async] dec=11799 ... (21.5s)` 在 iter 6 与 iter 7 之间打印，随后
  `[loop] eval stop requested ...; stop at iteration boundary`，
  `[done] iters=8`——**已跑完的 8 个 iteration 全部保留**（history/snapshot 均已落盘）。

### 2.4 早停 / 回滚

旧代码在评测后**没有**早停或回滚，只有「`mean_rank <= 3.0` 写
`TRIGGER_library.json`（镜像库里程碑）」。现在把这个后处理抽成同步/异步共用的
`_post_eval()`：无论结果来自阻塞调用还是 monitor 线程，都在**结果到达时**判定。

- `TRIGGER_library.json`：语义不变（评测成功且 `mean_rank <= 3.0` 时写，原子写）；
- 可选早停：新增 `--eval-stop-mean-rank X`（默认 0=关闭）。结果 `mean_rank <= X` 时
  置 `threading.Event`，主循环在**下一个 iteration 边界**检查并退出，不会丢掉已完成的
  iteration；异步时判定发生在 monitor 线程，主循环完全不受阻塞；
- 收尾时 `summary.json` 会带 `eval_async`（submitted/completed/failed/skipped/running）、
  `evals`（本次完成的记录）与 `evals_skipped`，以及 `eval_stop_reason`。

## 3. 多 GPU actor

`--gpus` 一直是**任意物理 GPU 列表**（`process_pool.ProcessActorPool` 按
`gpus[i % len(gpus)]` 轮转绑定 worker），不需要改代码；`--processes` 只需要 ≥ GPU 数。

### 3.1 推荐配置（对应 s5 的 12 workers / 3 GPU = 4 workers/GPU）

```bash
--gpus 1,3,0,4,5   --processes 20 --threads 8 --games 192
# 4 workers/GPU × 5 GPU；192 局 / 20 worker ≈ 9.6 局/worker，threads 8 足够
# 若想保持 s5 的 16 局/worker + threads 16：--games 320 --threads 16
```

启动时新增**邻居抢占检测**（`--gpu-free-check 1` 默认开，阈值 `--gpu-free-mib 1024`）：
用 `nvidia-smi --query-gpu=memory.used` 检查，已用 >1 GiB 的卡**从 actor 列表剔除并 warn**；
全部被占则报错退出（可用 `--gpu-free-check 0` 强制）。评测卡被占也会单独 warn。

`scripts/train_stage1.sh`（仓库里没有 `train_entity_stage*.sh`）本身已经满足任意列表：
`--gpus 0,5,6,7` 直接透传；`--lockstep 1` 时 `--processes = 4 × GPU 数`；`--pipeline 1` 时
自动把 learner 卡从 actor 列表剔除。异步评测可通过 `--` 透传：
`bash scripts/train_stage1.sh --gpus 1,3,0,4,5 -- --eval-async 1 --eval-device cuda:4`。

### 3.2 实测（不碰 s5）

- 8 workers / 2 GPU（`--gpus 2,4,5`，其中 cuda:2 已用 8292 MiB 被自动剔除）：
  `[warn] GPU 已被占用（>1024MiB，疑似邻居进程）：cuda:2=8292MiB -> 从 actor 列表剔除`，
  `[pool] processes=8 gpus=[4, 5] workers/gpu={4: 4, 5: 4}`；
- 96 局 collect（`profile.collect_s`）：8 workers/2 GPU = **2.13–2.37 s**，对比
  2 workers/1 GPU = 2.66–4.36 s。

### 3.3 预期收益（s5 同配置）

| 配置 | collect | 纯训练 iteration | 估算吞吐（无评测阻塞） |
|---|---|---|---|
| 12 workers / 3 GPU（现状） | 5.98 s | ~7.79 s | 5.65k dec/s |
| 20 workers / 5 GPU | ~4.5 s | ~4.9–5.5 s | **~8.0–9.0k dec/s** |

即使打个折（collect 只降到 5.0 s、PPO 略升），44,042 / 5.6 s ≈ **7.9k dec/s**，
仍高于 6.5k 目标；异步评测再把 3.7 h 的评测阻塞从关键路径上拿掉。

## 4. 风险与注意事项

1. **邻居抢占 GPU4/5**：启动时的检测只覆盖启动瞬间。邻居中途占卡 -> actor/评测可能
   OOM 或变慢；`ProcessActorPool` 有 worker 自愈（连续死亡 >2 次才报错），但吞吐会掉。
   重启前务必先 `nvidia-smi` 确认；刚杀掉上一进程时显存可能尚未释放（检测会误剔除），
   等 0 MiB 或加 `--gpu-free-check 0`。
2. **评测卡与 actor 同卡**：`--eval-device cuda:4` 且 4 也是 actor 卡时，评测会与 4 个
   actor 抢算力和显存（不阻塞主循环，但评测变慢、actor 抖动）。想完全隔离用
   `--eval-device cuda:6/7`（当前空闲）。
3. **显存**：每个 actor 进程 ~600 MiB（4 个/GPU ≈ 2.4 GiB）；评测子进程再占 ~1 GiB。
   24 GiB 卡安全，但不要和邻居的大任务叠在同一张卡。
4. **resume 的累计量会归零**：`cum_decisions` 每次启动从 0 计，所以
   `--stop-at-decisions` 与 `--seq-ramp-total-decisions` 都按**本次 run** 计；
   续训时要按剩余预算换算（见 §5.3）。
5. **评测 cadence 也按本次 run 计**：resume 后第一次评测在“再跑 N decisions”之后，
   不会对齐原来的 5M 绝对边界。
6. **快照间隔**：s5 的 `--snapshot-every 100 --keep-snapshots 4`，崩一次最多回退
   ~100 iter（约 4.4M decisions）；重启续训建议保持，或临时调小。

## 5. 复现命令

### 5.1 单测（无需 GPU）

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
PYTHONPATH=rust/python:. python -m pytest tests/test_async_eval.py -q
```

### 5.2 冒烟（异步 vs 同步；用 4/5/6 号空闲卡）

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
COMMON="--games 96 --processes 2 --gpus 4 --device cuda:6 --sims 0 --epochs 1 \
  --minibatch 1024 --grad-accum 8 --amp bf16 --threads 16 --batch-size 64 \
  --pipeline 1 --lockstep 1 --eval-every-decisions 12000 --eval-games 32 \
  --eval-seats 8 --eval-device cuda:5"

# 异步：主循环不被 31.6 s 评测阻塞
$P scripts/train_entity_sync.py $COMMON --iterations 4 --eval-async 1 \
  --eval-drain 1 --out /tmp/s5_async_test

# 回归：同步旧行为（iter 1 后阻塞 ~34 s）
$P scripts/train_entity_sync.py $COMMON --iterations 3 --eval-async 0 \
  --out /tmp/s5_sync_test
```

多 GPU + 邻居检测冒烟：

```bash
$P scripts/train_entity_sync.py --iterations 2 --games 96 --processes 8 \
  --gpus 2,4,5 --device cuda:6 --sims 0 --epochs 1 --minibatch 1024 \
  --grad-accum 8 --amp bf16 --threads 12 --batch-size 64 --pipeline 1 --lockstep 1 \
  --out /tmp/s5_multigpu
# 期望：[warn] cuda:2=... 剔除；[pool] processes=8 gpus=[4, 5] workers/gpu={4: 4, 5: 4}
```

### 5.3 给 runs/az_entity_s5 的「重启续训」命令（**未执行**）

先停掉旧进程（确认 PID 后 `kill`，**不要**用本文件里的命令去杀正在跑的 s5），
等 `nvidia-smi` 显示 0/1/3 释放后，从最新 snapshot 续训：

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
unset CUDA_VISIBLE_DEVICES
SNAP=$(python - <<'PY'
import json, os
m = json.load(open("runs/az_entity_s5/latest.json"))
print(os.path.dirname(m["model"]))
PY
)

$P scripts/train_entity_sync.py \
  --checkpoint "$SNAP/model.pt" --trainer-state "$SNAP/trainer.pt" \
  --arch entity --device cuda:2 \
  --processes 20 --gpus 1,3,0,4,5 --threads 8 --games 192 \
  --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16 \
  --lr 2e-6 --lr-min-ratio 0.5 --max-updates 3000 \
  --clip 0.2 --target-kl 0.02 --lam 0.995 --max-grad-norm 1.0 \
  --entropy-coef 0.001 --pi-coef 0.0 \
  --anchor-beta 0.1 --anchor-iterations 200 --anchor-beta-tail 0.02 \
  --pipeline 1 --lockstep 1 \
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.1 \
  --mirror-sample p75 --mirror-p-ramp "0.1@0,0.3@0.5" --mirror-seat-random 1 \
  --seq-coef 0.02 --seq-coef-ramp "0.02@0,0.05@0.5" \
  --seq-ramp-total-decisions 100000000 \
  --seed 7100 --eval-every-decisions 5000000 --eval-games 512 --eval-seats 8 \
  --eval-seed-base 420000 --eval-async 1 --eval-device cuda:4 \
  --iterations 5000 --stop-at-decisions 70000000 --minutes 960 \
  --snapshot-every 100 --keep-snapshots 4 --out runs/az_entity_s5
```

说明：

- `$SNAP` 由 `latest.json` 解析，重启时会自动取最新快照（示例为 `step_000601`）；
- `--stop-at-decisions 70000000`：续训后 `cum_decisions` 从 0 计，按“100M 总预算 - 已完成
  ~30M”折算；若到时已完成更多，按 `100M - 已完成` 调整；
- `--seq-ramp-total-decisions` 同理按剩余预算；如希望接着当前系数（~0.038）走，可改成
  `--seq-coef-ramp "0.038@0,0.05@0.5" --seq-ramp-total-decisions 70000000`；
- `--eval-device cuda:4` 与 actor 卡 4 共用；若 6/7 空闲，换成 `cuda:6` 可让评测完全隔离；
- 启动日志应出现 `[pool] processes=20 gpus=[...] workers/gpu={...: 4, ...}` 和
  `[eval-async] on：device=cuda:4 ...`；若出现 `[warn] GPU 已被占用`，说明有卡被邻居占用，
  程序会自动剔除剩余卡，必要时调整 `--gpus`。
