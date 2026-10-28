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
  也可以先用 **1 个 worker 独占 1 张卡 + 96–192 局**（batch 96–192 行）验证「大 batch 能否到 2 s」，
  这是最便宜的验证（无需新组件）。

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
