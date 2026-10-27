# 18M/56+1 模型与 4 GPU / 多 CPU 资源基准

> 目的：在启动 6–12h 长训练前，先记录模型结构、资源占用和吞吐/超参曲线。
> 本文件记录实测；长训练尚未启动。

![compute throughput](assets/compute_throughput.png)

## 1. 网络对齐：entity18m

新增 `arch=entity18m`：

| 项目 | entity（旧） | entity18m（新） |
|---|---:|---:|
| 参数 | 14,808,254 | **17,982,654** |
| token | 49（含 global） | **57（1 global + 56 entity）** |
| 组成 | 7 board + 10 hand + 8 shop + 16 choices + 7 opp | 同上 + **8 pending-context** |
| d_model | 384 | 384 |
| layers / heads | 8 / 8 | 8 / 8 |
| FF | 1536 | **2048** |
| pos_emb | 16 | **24** |
| type_emb | 6 | 7 |

**注意**：当前 observation 只有 16 个 choices；`entity18m` 的 8 个 pending-context token
是从 `global + pending one-hot` 派生的**结构补位**，不是新增 8 个真实观测槽位。
所以它是“18M/57 token 结构对齐”，不是“AutoTavern 原始数据布局逐位复刻”。

测试：`tests/test_entity18m.py`（参数、token、forward、checkpoint roundtrip）。

## 2. 单 GPU 前向吞吐

1024 leaves，BatchLeafServer：

| batch | entity 14.8M leaf/s | entity18m leaf/s | 18M 相对 |
|---:|---:|---:|---:|
| 64 | 3,819 | 3,522 | -7.8% |
| 128 | 7,812 | 5,947 | -23.9% |
| 256 | 8,174 | 6,791 | -16.9% |

- entity18m 前向比 14.8M 慢约 **8–24%**；
- 显存峰值：14.8M ≈ 282MB，18M ≈ **355MB**（forward benchmark）；
- 18M 仍远小于 24GB，显存不是瓶颈。

## 3. 4 GPU 推理

4 个独立进程，每个 `CUDA_VISIBLE_DEVICES=i`，entity18m：

| per-GPU batch | 4 GPU aggregate leaf/s |
|---:|---:|
| 128 | 17,499 |
| 256 | **27,371** |

结论：

- 4 GPU 推理接近线性扩展（B256: 4 × ~6.8k ≈ 27.2k）；
- 但这是**推理**，不是训练 actor；
- 需要拓扑 A（1 learner + 3 inference）才能把这部分利用起来。

## 4. Actor/worker 扩展

`bench_actor_batch.py`，entity18m，128 games，batch64：

| worker threads | decisions/s | GPU util mean | max_batch |
|---:|---:|---:|---:|
| 8 | 774 | 19.6% | 8 |
| 16 | 1,164 | 21.2% | 16 |
| 32 | 2,021 | 25.6% | 32 |
| 64 | 2,382 | 24.8% | 64 |

观察：

- 8→64 线程只提升 **3.1×**，不是 8×；
- GPU util 始终 **<32%**；
- 瓶颈是 Python GIL + MCTS 逐叶回调，不是 GPU；
- 64 线程不是 64 actor；CPU 128 核不会被有效使用。

## 5. 训练采集超参曲线

`train_entity_sync.py`，entity18m，64 games，sims 0/4，max_steps 3000：

| workers | sims=0 dec/s | sims=4 dec/s |
|---:|---:|---:|
| 8 | 786 | 115 |
| 16 | 1,120 | 152 |
| 32 | 1,231 | 170 |
| 64 | **1,486** | **191** |

观察：

- sims=4 比 sims=0 慢约 **7.8×**；
- workers 8→64 的 sims=4 只从 115→191（1.66×）；
- 训练采集吞吐远低于推理 leaf/s：**leaf 批处理不是端到端 actor**。

## 6. CPU 数量的结论

- 当前 64 线程已经明显受限；
- 直接加到 128 线程预计收益很小；
- 应先做**进程级 actor pool**（4–16 进程/GPU），再扫描 32/64/96/128 vCPU；
- 选点标准：GPU util 70–85%、queue p95、decisions/s 边际收益；
- 在 actor 重构前，不建议承诺“128 CPU 线性扩展”。

## 7. 长训练预算（待最终确认）

按当前 entity18m、sims=4、单 GPU 采集约 191 dec/s 估算：

| 配置 | 6h 采集 | 12h 采集 |
|---|---:|---:|
| 单进程/单 GPU | ~4.1M | ~8.2M |
| 4 个独立训练分片 | ~16.5M | ~33M |

这是**采集上限**，不含 PPO/评测/IO；4 GPU 拓扑 A 的 learner 可能成为新瓶颈。
必须在 30–60 分钟 4 GPU/CPU 扫描后，重写这一表。

## 8. 命令

```bash
P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python

# 单 GPU 前向
$P scripts/bench_batch_leaf.py --arch entity18m --device cuda \
  --leafs 1024 --batches 64,128,256

# 4 GPU 推理（每个进程一张卡）
for i in 0 1 2 3; do
  CUDA_VISIBLE_DEVICES=$i $P scripts/bench_batch_leaf.py --arch entity18m \
    --device cuda --leafs 1024 --batches 128,256 --out /tmp/bench_4gpu_$i.json &
done; wait

# actor 扩展
$P scripts/bench_actor_batch.py --arch entity18m --device cuda \
  --games 128 --parallel 64 --batch 64

# 训练超参（sims/workers）
$P scripts/train_entity_sync.py --iterations 1 --games 64 --workers 64 \
  --arch entity18m --device cuda --sims 4 --opponent bot \
  --epochs 1 --minibatch 256 --max-steps 3000 --out /tmp/thr
```

## 9. 当前结论

- 18M/57 token 结构已实现，参数量 17.98M；
- 18M 前向仅慢 8–24%，显存 355MB；
- 4 GPU 推理可扩展；
- 训练 actor 仍受 Python 线程/GIL 限制，GPU util <32%；
- **长训练不应在 actor 重构前启动**；
- 等用户明确通知后，先做 30–60 分钟 4 GPU + CPU 扫描，再跑 6–12h。

## 10. 进程级 actor pool 扫描状态（数据被污染，结论未成立）

`ProcessActorPool` + `bench_process_pool.py` 已实现：

- multiprocessing spawn，每进程绑定 GPU；
- 每进程独立 model/evaluator/Game；
- 返回 records 给 learner；
- 4 GPU / sims=4 / 8 games per round 扫描尝试。

**当前状态（2026-10-27 修正）**：`runs/bench/process_4gpu_30min.json` **确实存在**，但只有
3 轮、总时长 106.4s、5,616 decisions、**50.9–56.0 decisions/s**，远未跑满 30min。同一次尝试
的日志里出现：

```text
BrokenPipeError: [Errno 32] Broken pipe
SpawnPoolWorker ... multiprocessing/pool.py ... put(...)
```

（一次性 `multiprocessing.Pool` 的 worker 生命周期/结果传输问题，截至本文写作时仍未修。）  
更关键的是**采样环境被污染**：该 JSON 记录的显存是 GPU0 626 MB、GPU1 22,873 MB、
GPU2 14,455 MB、GPU3 14,473 MB，第 3 轮 GPU1–3 的 util 冲到 96%；这些都不是本扫描的负载，
而是**同一用户另一个项目（HierMolGen `mt3_train`）当时占用 GPU1–3**（2026-10-27 20:08 复查，
GPU1–4 仍被该任务 4 个进程占用 78–82%，只有 GPU 0/5/6/7 空闲）。

因此：

- 这份数据**不能**作为「4 GPU 进程级 actor 吞吐」的结论，也不能用来反推 6–12h 预算；
- 已有可用的 4 GPU **推理**基准（§3）与单进程线程 actor 基准（§4），但都不能替代进程级
  actor 扫描（§3/§4 当时是否同样共享卡，**待确认**，复核吞吐时一并重测）。

### 下一步修法

1. 用 `concurrent.futures.ProcessPoolExecutor` 或显式 `Process` + `Queue` 替代反复 `Pool`；
2. 每轮 worker 结果用文件/共享队列，失败 worker 可重启；
3. 先跑 2–5 分钟短测，确认无 BrokenPipe，再跑 30min；
4. 记录每轮 decisions/s、GPU util、显存、失败/重启次数；
5. 扫描前后各记录一次 `nvidia-smi` 全卡占用，确保 4 张卡上没有其它任务（有则换卡重跑）。

> 正在 **GPU 0 / 5 / 6 / 7（当前空闲卡）** 上用持久化 worker（显式 `Process` + 队列，替代
> 反复 `Pool`）重跑 30min 扫描；结果追加到本节末尾。

<!-- LEAD-APPEND: clean-scan-results -->
