# 训练吞吐优化计划（基于 stage-1 实测）

> 由来：stage-1（`runs/az_entity_kl_30m`，sims=0，30.08M decisions）**端到端只有 1,577 decisions/s**，
> 而采集瞬时能到 6,300–7,000 decisions/s。**≈60% 的时间花在数据搬运，而不是引擎或梯度**。
> 本文把实测拆解固化成优化计划；命令逐条给出，供后续会话直接执行（不必依赖对话上下文）。
> 基线数据：`runs/az_entity_kl_30m/history.json`、`runs/bench/process_4gpu_30min_clean.json`、
> `runs/bench/process_4gpu_sims0_3min.json`。

## 1. 实测基线（先记住这些数，优化后逐项对照）

| 指标 | 实测值 | 来源 |
|---|---:|---|
| 端到端（含 PPO/IO，30.08M / 318 min） | **1,577 dec/s** | stage-1 history |
| 采集瞬时（sims=0，8 进程 × 16 线程，192 games/轮） | **6,300–7,000 dec/s** | history `collect.decisions_per_s` |
| 采集瞬时（sims=4，同配置） | 685 dec/s | `process_4gpu_30min_clean.json` |
| PPO 更新（有效 minibatch 8192、1 epoch、~30k samples） | **6.2–6.7 s/iter** | history `ppo.seconds` |
| 每 iteration 壁钟 | **~18–30 s**（collect 4.5–5.1 s + PPO 6.2–6.7 s + 其余 10–18 s） | history 差值 |
| 512 局 C0 评测 | 400–490 s/次 | `eval/history.json` |
| 单轮 records 落盘体积 | ≈300–400 MB（30k 条 × ~13 KB） | 推算（pickle） |
| 每 iteration 权重回传 | 61 MB × 8 worker | `_pool_weights.pt` 大小 |

**结论**：collect 与 PPO 加起来只占 ~11 s，还有 **10–18 s/iter 不明开销**；30M 里约
**1.9 小时**耗在这部分。

## 2. 开销归因（按贡献排序，可逐项测量验证）

| # | 来源 | 机制 | 每 iter 估算 |
|---|---|---|---:|
| A | **records 落盘再读回** | worker `pickle.dump` 30k 条（≈300–400 MB）→ 父进程 `pickle.load` → `np.stack` | 8–14 s |
| B | **权重回传** | 父进程 `save_checkpoint` 61 MB → 8 个 worker 各自 `torch.load` + `load_state_dict` | 2–4 s |
| C | **history.json 全量重写** | 每 iter 把整个 history（含 192 条 games_meta/iter）重新 dump，文件随训练线性增长 | 0.5–2 s（后期更慢） |
| D | **快照写盘** | 每 100 iter 写 `model.pt` 61 MB + `trainer.pt` 180 MB | 分摊 ~0.6 s/iter |
| E | 采样/构 batch 的 numpy 拷贝 | `build_batch_from_records` 对 30k×3227 float32 做 `np.stack`（≈390 MB） | 1–2 s |
| F | 评测阻塞 | 每 5M decisions 停 400–490 s | 分摊 ~2.6 s/iter |

## 3. 优化方案（按性价比排序，每步都可独立验证）

### P1：records 走共享内存（收益最大，预计 −8…−12 s/iter）

- 用 `multiprocessing.shared_memory` 预分配一个 slot 池（例如 4 个 slot × 600 MB），
  worker 把 `features/cards/masks/actions/old_logprobs/values/target_pi/…` 直接写成
  **npy 头 + 原始数组**（不 pickle 30 万个 Python dict），父进程 mmap 读取后 `np.concatenate`；
- 或者更彻底：**worker 内直接 `build_batch_from_records`**，把 `PPOBatch` 的数组段写盘，
  父进程只做段拼接（省掉 records→batch 的二次堆叠）；
- 验收指标：单轮 `collect wall_s` 对 `decisions_per_s` 的比值恢复到 ≈ 采集瞬时值，
  端到端 ≥ 2,300 dec/s。

### P2：权重按版本懒加载（预计 −2…−3 s/iter）

- 现在每个 iteration 都 `save_checkpoint` + 8 个 worker `torch.load`。改为：
  - 父进程把 state_dict 写到**同一路径的 ring buffer**（`_pool_weights_%d.pt`，只保留 2 个版本）；
  - worker 只在 `update_version` 变化时加载；
  - 或者用 `torch.distributed` 的 `broadcast`/共享内存传 tensor（省掉磁盘往返）。
- 验收：`reload_weights` 段耗时 < 1 s/iter。

### P3：history 增量写（预计 −0.5…−2 s/iter）

- `history.json` 改成 **jsonl 追加**（每 iter 一行），或只在每 N iter 全量重写一次；
- 同时把 `games_meta` 只在失败/抽样时保留（现在每轮 192 条全存）。
- 验收：文件大小线性增长但写盘时间恒定。

### P4：评测与训练错峰（预计回收 ~15 min/30M）

- 现在评测会**阻塞**训练 400–490 s。改为：
  - 用**独立 GPU**（当前 `--eval-device` 已支持）并行跑，训练不停；
  - 或改成 256 局快速筛选 + 每 10M 一次 512 局正式点；
- 验收：训练 loop 的 `elapsed` 扣掉评测时间后仍 ≥ 2,300 dec/s。

### P5：actor 侧再提速（中长期）

- 采集瞬时已 6,300–7,000 dec/s，受 CPU/GIL 限制；进一步靠
  **Rust `NeedEval` 批式回调**（见 `docs/ACTOR_RUST_OPTIONS.md`）把 leaf 回调从「每叶一次 Python」
  改为「每 batch 一次」，目标是 GPU util 从 32% 抬到 60–80%。

## 4. 每步的执行命令（固化为可直接复制的命令）

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM

# 0) 复现基线：sims=0 吞吐（3 分钟，占 4 张卡）
PYTHONPATH=rust/python:. $P scripts/bench_process_pool.py \
  --checkpoint runs/az_entity_kl_30m/model_30m.pt --arch entity \
  --processes 8 --gpus 0,5,6,7 --threads 16 --games 192 --sims 0 \
  --warmup-rounds 0 --minutes 3 --out runs/bench/sims0_baseline_3min.json

# 1) 优化后同一命令再跑一次，直接比 decisions_per_s / queue p95 / GPU util
PYTHONPATH=rust/python:. $P scripts/bench_process_pool.py \
  --checkpoint runs/az_entity_kl_30m/model_30m.pt --arch entity \
  --processes 8 --gpus 0,5,6,7 --threads 16 --games 192 --sims 0 \
  --warmup-rounds 0 --minutes 3 --out runs/bench/sims0_after_3min.json

# 2) 短训练对照（2M decisions，验证端到端与稳定性）
PYTHONPATH=rust/python:. $P scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_kl_30m/model_30m.pt --arch entity --device cuda:0 \
  --processes 8 --gpus 0,5,6,7 --threads 16 --games 192 --sims 0 --opponent bot --behavior net \
  --epochs 1 --minibatch 1024 --grad-accum 8 --lr 6e-6 --lr-min-ratio 0.833 --max-updates 80 \
  --clip 0.2 --target-kl 0.05 --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.002 --pi-coef 0.0 \
  --iterations 80 --minutes 30 --snapshot-every 40 --keep-snapshots 2 --eval-every-decisions 0 \
  --seed 1200 --out runs/az_entity_kl_2m_after

# 3) 分析（曲线 + 吞吐/ KL）
PYTHONPATH=rust/python:. $P scripts/analyze_stage1.py --run runs/az_entity_kl_30m
```

**验收口径**（写进 PR/报告时必须同时给）：
- 端到端 decisions/s（分母=训练 wall-clock，含 PPO/IO/评测）；
- 采集瞬时 decisions/s、PPO s/iter、`reload_weights` s/iter、history 写盘 s/iter；
- 512 局 C0（未见面板）+ 配对 CI，确认吞吐优化**没有改变学习曲线斜率**；
- 任何「变快」都必须同时报 GPU util 与 queue p95（防止用饿死 actor 换吞吐）。

## 5. 风险与注意

1. **共享内存/ring buffer 会引入一致性风险**：必须带 version tag，读到不完整 slot 要丢弃重试；
2. **PPO 语义不能变**：GAE 仍按 (game_id, seat) 分组，梯度累积的有效 minibatch 仍 8192；
3. **评测并行**会与 actor 抢 GPU，必须限定在独立卡并记录 queue p95 回归；
4. 吞吐优化后**先跑 2M 短对照**再上 30M，避免「更快但学歪」；
5. 所有改动都要过 `python scripts/verify_all.py --fast` 与 `pytest tests -q`。
