# Rust 全采集器（spike，进行中）

> 状态：**采集器已实现并接入训练**（`--rust-collector 1`），P=12 时与 lock-step 持平
> （collect 6.35 s vs 6.39 s）。目标 collect ≈2 s **尚未达成**，瓶颈已定位（见 §4）。

## 1. 设计

Rust 侧新增 `hsbg_engine._core.RustCollector`（`rust/crates/hsbg-engine-py/src/collector.rs`），
基于已有 `BatchEnv`（N 局、每局一个受控座位，对手由引擎 bot 驱动）：

| 步骤 | 位置 | 内容 |
|---|---|---|
| `pending()` | **Rust** | `BatchEnv.observe()` 取全部 slot 的 (features f32[n,3227], cards i32[n,124], masks u8[n,245], turns u32[n])，只返回「ready 且本局未结束」的行 |
| 前向 + 采样 | Python/GPU | `BatchPPOEvaluator.act_batch(F,C,M,temperature,seed)` → (action, logprob, value) |
| `record_actions(a,lp,v)` | **Rust** | 回合守卫（`(game_id,turn)` 计数 > limit 且 EndTurn 合法 → forced）、记录写入预分配 SoA、`BatchEnv.step`（引擎推进 + 7 个 bot 座位 + 名次回填） |
| `finish()` | **Rust** | 一次性返回 SoA 记录（features/cards/masks/actions/old_logprobs/values/ranks/seats/game_ids/turns/forced/count/rounds/illegal） |

Python 胶水：`hsbg/az/train/rust_collect.py::collect_ppo_rust`（约 100 行，只做 numpy 视图 + 调用）。
训练接入：`CollectConfig.rust_collector` / `--rust-collector 1` / `--rc-threads 8`，worker 内直接
`build_batch_from_arrays` → npz，父进程只拼接（沿用 L4 协议，episode_id = `game_id*8+seat`）。

## 2. 实测（空闲卡：actor 1/3/0、learner 2；`--games 192`；8–10 iteration）

| 配置 | dec/s | collect | PPO | iter |
|---|---:|---:|---:|---:|
| lock-step，P=12 | 5,788 | 6.39 s | 4.46 s | 6.06 s |
| **Rust 采集器，P=12（16 局/worker）** | 5,588 | **6.35 s** | 4.72 s | 6.28 s |
| Rust 采集器，P=6（32 局/worker） | 4,120 | 8.45 s | 4.51 s | 8.70 s |
| Rust 采集器，P=4（48 局/worker） | 3,456 | 10.50 s | 4.53 s | 10.47 s |
| Rust 采集器，P=3（64 局/worker） | 2,953 | 12.56 s | 4.44 s | 12.66 s |
| Rust 采集器，P=2（96 局/worker） | 2,172 | 17.41 s | 4.48 s | 16.99 s |

单 worker（16 局、cuda:1、entity）：3,330 decisions / 2.53 s = 1,317 dec/s，其中
**GPU 前向占 1.72 s（68%）**。

## 3. 关键发现：每次前向有 ~5 ms 固定开销

leaf forward 微基准（entity，cuda:1，`BatchLeafServer.logits`）：

| batch | ms/call | ms/row |
|---|---:|---:|
| 1 | 5.09 | 5.09 |
| 8 | 5.38 | 0.67 |
| 16 | 5.62 | 0.35 |
| 32 | 5.48 | 0.17 |
| 64 | 6.60 | 0.10 |
| 128 | 9.67 | 0.08 |
| 256 | 16.13 | 0.06 |

→ **每行成本主要由 batch 大小决定**，而不是引擎/记录（Rust 侧已很便宜）。

## 4. 为什么没到 2 s，以及下一步

- 每个 worker 有**私有** `BatchLeafServer`，一轮只能凑出 `games/processes` 行（P=12 → 16 行 →
  0.35 ms/行）。减少 worker 换更大 batch 反而更差：worker 少了，每 worker 要串行跑更多局，
  且 GPU 数没变（3 张卡被 3–4 个进程摊薄）。
- **缺的是「共享批量推理服务」**：多个采集进程把各自的 16 行请求汇给同一个 per-GPU server，
  凑成 128–256 行再前向（0.06–0.08 ms/行，比 16 行快 4–6×）。
  按 40k 决策/iter 估算：40k × 0.07 ms ≈ 2.8 s 的单 GPU 服务时间；3 张卡并行分摊 ≈ **1 s**，
  加引擎与拼装 ≈ **1.5–2 s** —— 这才是达到目标 collect ≈2 s 的路径。
- 实现方式（下一轮）：worker 侧 `BatchLeafServer` 改为「连接到常驻推理服务」（Unix socket 或
  共享内存 + 事件），服务端在每张 GPU 上一个进程，按 `max_wait_ms` 聚合多 worker 请求。
  **已排除**「单 worker 大 batch」这条路：P=2（96 局/worker）实测 collect **17.41 s**，
  P=3 12.56 s、P=4 10.50 s、P=6 8.45 s —— worker 越少越慢。说明每轮的固定成本
  （`pending()` 与 `record_actions()` 各自一次全量 `BatchEnv.observe()` + `step` 推进全部局，
  单 worker 内串行）远大于 forward 的均摊收益。
  因此下一轮必须做**共享推理服务 + 去掉重复 observe**（`record_actions` 复用 `pending()` 的
  mask/turn，避免第二次全量观测），而不是继续调 worker 数。

## 4b. 第二轮实测（cap 修复 + 多 shard）

- 预分配从 `n_games × 4096` 降到 `n_games × 192`（原来 96 局要 memset 3.4 GB）；
- 新增 `collect_ppo_rust_multi`（单进程多 shard 共享一次前向），实测单卡 192 局：
  single 3,109 dec/s、multi 4×48 3,277、8×24 3,197、12×16 3,175 → **多 shard 无显著收益**；
- 单进程 64 局（=P=3 的每 worker 负载）直接测：5.0–6.0 s / 13.5k 决策（2,255–2,691 dec/s），
  其中 forward 2.6–2.9 s（约 50%）；但在 **pool 里同样的负载要 10–13 s**（collect 13.08 s @P=3、
  8.57 s @P=6、7.19 s @P=12）——说明 pool 路径还有 **~2× 的额外开销**（尚未定位，
  候选：pipeline 下与 PPO 抢 CPU、每轮 `np.savez`/父进程读盘、或 3 个 CUDA context 的调度）。
- 结论：**目标 2 s 未达成**；当前 Rust 采集器最好成绩 = 与 lock-step 持平（6.35 s）。
  下一步优先级：① 定位 pool 路径的 2× 差距（用 `--pipeline 0` 且单 worker 复现对比）；
  ② 共享 per-GPU 推理服务（把 44 行/次提升到 128–256 行/次）。

## 5. 复现命令

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM
env -u CUDA_VISIBLE_DEVICES $P scripts/train_entity_sync.py \
  --checkpoint runs/champion_c0_3004.pt --arch entity --device cuda:2 \
  --processes 12 --gpus 1,3,0 --games 192 --sims 0 --epochs 1 --minibatch 1024 \
  --grad-accum 8 --amp bf16 --lr 6e-6 --clip 0.2 --target-kl 0.05 --lam 0.995 \
  --pipeline 1 --lockstep 0 --rust-collector 1 --rc-threads 8 \
  --iterations 10 --out runs/ab_rc_rust
```


## 4c. 第三轮：整批 torch 采样（真实提速）

**根因**：`BatchLeafServer` 的 batch 分支原来**逐行**做 `masked_probs_np` + `np.random.default_rng`
（每行新建 Generator）+ `value_from_rank_logits_np`，约 0.1–0.2 ms/行，比 forward 本身还贵。

**改法**：整批一次 torch（`batch_eval._act_batched`）：`masked_log_softmax_torch(logits/temp)` →
`torch.multinomial`（一个 Generator）→ `gather().log()`，value 用 `value_from_rank_logits_torch`。

**收益（单进程、单卡 cuda:1、entity、raw lock-step 采集）**：

| games/collector | 改前 dec/s | 改后 dec/s |
|---|---:|---:|
| 16 | 1,056 | 1,056 |
| 64 | 2,255–2,691 | **2,989** |
| 96 | — | **4,527** |
| 192 | 3,109 | **6,063** |

每决策成本 0.95 ms（16 局）→ 0.16 ms（192 局）。**但 pool 里同负载仍慢 ~2–3×**：
P=3（64 局/worker）collect 13.26 s，而 standalone 同负载 4.18–5.99 s；

pool 单 worker 实测（P=3）：`workers=10–13 s`，与 standalone(64 局)=4.18 s 矛盾
→ 待查：worker 侧 `_maybe_reload`（61 MB）、`torch.set_num_threads(1)`、batch_size=64/max_wait=2 ms。
已确认**不是** batch 采样（改后 pool 同负载几乎没变：P=12 6.35 → 6.07 s）。

> 目标 2 s：按单卡 6,063 dec/s（192 局）估算，**1 卡 40k 决策≈6.4 s**；3 卡各 192 局可到
> ~115k 决策/6.4 s。若每轮只需 40k 决策，则**单卡 192 局已是最优形态**（6.4 s），
> 要再快只能减少「每次前向 5 ms 固定延迟」——把 logits 计算改成常驻 GPU 张量、避免
> 每次 numpy→GPU 拷贝，或让多个 collector 共享一次大前向（128–256 行）。
