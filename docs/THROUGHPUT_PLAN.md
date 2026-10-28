# 训练吞吐调研与优化计划（基于 stage-1 实测）

> 目标：把 `train_entity_sync` 的**端到端** decisions/s 从 1,577 提到 3,000+，让同样 30M 预算
> 从 5h18m 压到 ~2.5h，且**不改变学习曲线**（同一 seed 短对照验证）。
> 本文所有数字都来自本仓库实测，标注了文件/命令；计划里的命令可直接复制执行，
> 不依赖对话上下文。

## 0. 一句话结论

**瓶颈不是引擎、也不是梯度本身，而是三件可修的事**：
① 每个 iteration 把整份 history（97 MB）`json.dumps(indent=2)` 重写（≈3.6 s/iter）；
② PPO 更新用 fp32（6.6 s/iter），实测 **bf16 autocast 快 2.03×**；
③ records 每轮 **431 MB** pickle 落盘再读回（父进程 0.94 s + worker 侧写盘）；
外加评测阻塞（2.5 s/iter 摊薄）。

## 1. 实测基线（stage-1：`runs/az_entity_kl_30m`）

| 指标 | 实测 | 来源 |
|---|---:|---|
| 端到端 | **1,577 dec/s**（30.08M / 318 min） | `history.json` 最后一条 `seconds` |
| 采集瞬时（sims=0，8 进程 × 16 线程，192 games） | 6,879 dec/s | `runs/profile_iter15`：`collect.collect.decisions_per_s` |
| 采集瞬时（sims=4，同配置） | 685 dec/s | `runs/bench/process_4gpu_30min_clean.json` |
| 单 iteration 壁钟（早期 → 后期） | **14.6 s → 17.4 s** | 30M run `history` 的 `seconds` 差分 |
| PPO 更新（~31k samples，fp32） | **6.57 s** | `profile_iter15` 的 `profile.ppo_s` |
| collect 整段（含回传） | **5.83 s** | `profile_iter15` 的 `profile.collect_s` |
| ├ worker 侧采集 | 4.62 s | `collect.collect.wall_s` |
| ├ 父进程读 records | 0.51 s | `collect.collect.parent_read_s` |
| └ 父进程 build batch | 0.43 s | `collect.collect.build_batch_s` |
| records 体积 / iteration | **431 MB** | `collect.collect.records_bytes` |
| 权重回传（存 61 MB + 8 worker 加载） | **0.15 s** | `profile.reload_s`（远低于此前估算） |
| history 写盘（早期 1.4 MB → 后期 97 MB） | **0.03 s → 3.61 s** | 实测 `json.dumps` 97 MB |
| 512 局 C0 评测 | 400–490 s/次，摊薄 ≈2.5 s/iter | `eval/history.json` |

**对账**：后期 ≈ 6.57（PPO）+ 5.83（collect）+ 3.6（history）+ 2.5（评测摊薄）+ 0.15（权重）
+ 0.03 ≈ **18.7 s**，与实测 17.4 s 吻合（评测按 6 次摊到 1,029 iter）。

## 2. 归因（谁吃掉了 30M 的 5 小时 18 分）

| 阶段 | s/iter（后期） | 占比 | 性质 |
|---|---:|---:|---|
| PPO 更新（fp32） | 6.57 | 38% | **可 2×**（bf16） |
| 采集（8 进程，引擎+GIL） | 4.62 | 27% | 接近当前架构上限 |
| **history.json 全量重写** | **3.61** | **21%** | **纯浪费，可归零** |
| 512 局评测（阻塞） | 2.50 | 14% | 可与训练并行 |
| 父进程读 records + build batch | 0.94 | 5% | 可用共享内存/免 pickle |
| 权重回传 | 0.15 | <1% | 可忽略 |

补充实测（history 膨胀原因）：单条 history entry **94 KB**（indent=2）/ 43 KB（compact），
其中 `collect.worker_meta` 占 **40.6 KB**（192 局 × 每局 meta），`collect.workers` 2.3 KB，
`collect.collect` 3.1 KB；`worker_meta` 在训练中从未被使用。文件最终 **97.1 MB**，
`json.dumps(indent=2)` 实测 **3.61 s**，compact **0.45 s**，jsonl 追加 **~0 s**。

PPO 侧实测（micro-batch 1024，entity 14.8M，GPU0 独占）：

| 精度 | ms/micro-batch | 31k samples 推算 |
|---|---:|---:|
| fp32 | 202.9 | 6.1 s |
| **bf16 autocast** | **100.2** | **3.0 s**（**2.03×**） |
| 显存峰值 | 11.4 GB | 适合 4090 |

## 3. 优化计划（按性价比排序，逐项可验收）

### O1　history 改增量（预计 −3.5 s/iter，改动最小）

- `history.json` → **`history.jsonl`**（每 iter 追加一行 compact JSON）；只保留聚合字段，
  **删掉 `collect.worker_meta` 与 `collect.workers`**（需要时另存 `workers.jsonl`）；
- 验收：`history_append_s` < 0.01 s，与训练时长无关；`history.jsonl` 约 43 KB/iter（30M 全量 ≈ 44 MB）。

### O2　PPO 换 bf16（预计 −3.3 s/iter）

- 在 `train_ppo` 的前向/反向外套 `torch.autocast("cuda", dtype=torch.bfloat16)`，
  loss 与 KL/entropy 计算前 `.float()`；`torch.optim.Adam` 参数保持 fp32；
- 需要验证：与 fp32 同 seed 短对照（2M decisions）的 KL/entropy/value loss 走势一致；
- 验收：`ppo_s` ≤ 3.5 s；显存 < 16 GB；`pytest tests/test_az_ppo.py` 全绿。

### O3　评测并行（预计回收 ≈2.5 s/iter，即每 30M 省 ~40 min）

- 现有 `--eval-device` 已能把评测放到别的卡；改为**不阻塞**：训练继续采集，评测在
  独立进程/卡上跑，结果异步写 `eval/history.json`；评测期间把 actor 线程数降一档避免抢卡；
- 验收：训练 loop 的 `elapsed` 与「eval 秒数」解耦；`queue_wait_ms_p95` 不超过基线 1.5×。

### O4　records 免 pickle（预计 −0.9 s/iter + 磁盘 431 MB/iter）

- worker 侧直接把数组写成 **npy 头 + 原始 buffer**（或 `multiprocessing.shared_memory` slot），
  父进程 `np.memmap` 后拼接；`build_batch_from_records` 改成「从数组段直接拼 PPOBatch」；
- 验收：`parent_read_s + build_batch_s` ≤ 0.2 s；(最终一致性与 `batch.validate()` 不变)。

### O5　采集再提速（中长期，收益最大但工作量最大）

- 现采集瞬时 6,879 dec/s 已受 Python GIL / 逐叶回调限制；按
  `docs/ACTOR_RUST_OPTIONS.md` 的方案 B（Rust actor + 批式推理）把 leaf 回调从「每叶一次
  Python」变成「每 batch 一次」，目标 GPU util 从 32% → 60–80%；
- 验收：sims=0 采集瞬时 ≥ 12,000 dec/s；sims=4 ≥ 1,200 dec/s。

> 单 iteration 的时间轴（谁在等谁、限速步、并行方案）单独写在
> [`docs/THROUGHPUT_TIMELINE.md`](THROUGHPUT_TIMELINE.md)，含实测 Gantt 图与流水线契约。
> 下面的 O1–O5 是**串行排程**下的优化；若再叠上 double-buffer 流水线，上限可从
> ≈7.2 s/iter 降到 ≈4.6 s/iter（≈6,700 dec/s）。

## 4. 预期收益

| 阶段 | 方案 | s/iter | 端到端 dec/s | 30M 用时 |
|---|---|---:|---:|---:|
| 现状 | — | 17.4 | 1,577 | 5h18m |
| +O1 | history jsonl | 13.9 | ~2,000 | 4h10m |
| +O2 | bf16 PPO | 10.6 | ~2,600 | 3h12m |
| +O3 | 评测并行 | 8.1 | ~3,400 | 2h27m |
| +O4 | 免 pickle | 7.2 | ~3,800 | 2h12m |
| +O5 | Rust actor | 采集侧再翻倍 | ~5,000 | ~1h40m |

## 5. 执行命令（固化为可直接复制）

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM

# 0) 现状基线（本次调研用的 15-iteration 探针，含 profile 字段）
PYTHONPATH=rust/python:. env -u CUDA_VISIBLE_DEVICES $P scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_kl_30m/model_30m.pt --arch entity --device cuda:0 \
  --processes 8 --gpus 0,5,6,7 --threads 16 --games 192 --sims 0 --opponent bot --behavior net \
  --epochs 1 --minibatch 1024 --grad-accum 8 --lr 6e-6 --max-updates 200 \
  --clip 0.2 --target-kl 0.05 --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.002 --pi-coef 0.0 \
  --iterations 15 --minutes 20 --snapshot-every 1000 --eval-every-decisions 0 \
  --seed 1300 --out runs/profile_iter15

# 1) 吞吐探针（不改算法的外部测量）
PYTHONPATH=rust/python:. $P scripts/bench_process_pool.py \
  --checkpoint runs/az_entity_kl_30m/model_30m.pt --arch entity \
  --processes 8 --gpus 0,5,6,7 --threads 16 --games 192 --sims 0 \
  --warmup-rounds 0 --minutes 3 --out runs/bench/sims0_after_3min.json

# 2) 优化后的 2M 短对照（验证学习曲线没变：同 seed、同配置）
PYTHONPATH=rust/python:. env -u CUDA_VISIBLE_DEVICES $P scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_kl_30m/model_30m.pt --arch entity --device cuda:0 \
  --processes 8 --gpus 0,5,6,7 --threads 16 --games 192 --sims 0 --opponent bot --behavior net \
  --epochs 1 --minibatch 1024 --grad-accum 8 --lr 6e-6 --max-updates 80 \
  --clip 0.2 --target-kl 0.05 --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.002 --pi-coef 0.0 \
  --iterations 80 --minutes 30 --snapshot-every 40 --keep-snapshots 2 --eval-every-decisions 0 \
  --seed 1300 --out runs/az_entity_kl_2m_after

# 3) 曲线/吞吐汇总
PYTHONPATH=rust/python:. $P scripts/analyze_stage1.py --run runs/az_entity_kl_30m
```

**验收口径（每次改动都要报）**：
1. 端到端 dec/s（分母=训练 wall-clock，含 PPO/IO/评测）＋ 采集瞬时 dec/s；
2. `profile` 分解：`reload_s / collect_s / ppo_s / history_s / build_batch_s / parent_read_s`；
3. 512 局 C0（未见面板）+ 配对 CI，确认**斜率不变**；
4. GPU util、`queue_wait_ms_p95`（防止用饿死 actor 换吞吐）；
5. `python scripts/verify_all.py --fast` 与 `pytest tests -q` 全绿。

## 6. 风险与纪律

1. **O1 是纯工程改动**，风险最低、收益 3.6 s/iter，建议先做；
2. **O2 必须做数值对照**：bf16 可能轻微改变 KL/entropy，需要 2M 同 seed 对照；
3. **O3 并行评测**会与 actor 抢 GPU，必须限定独立卡并记录 queue p95 回归；
4. **O4 一致性**：共享内存/npy 必须带 version + 完整长度校验，读半截要丢弃重试；
5. 任何吞吐改动都**不得改变 PPO 语义**：GAE 仍按 (game_id, seat) 分组、有效 minibatch 仍 8192；
6. 先 2M 短对照，再上 30M；禁止直接拿「更快」当「更好」的证明。
