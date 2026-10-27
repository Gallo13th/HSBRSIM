# 多 GPU / 多 CPU 长训练计算计划

> 追加计划：允许 **4 张 GPU** 和更多 CPU；CPU 数量由服务器资源与吞吐瓶颈实测决定。
> 在确认网络结构、训练任务、训练目标后，先做 **6–12 小时**长训练预期。
> 本文是计划；当前代码仍是单 GPU 单进程 prototype。

## 0. 当前服务器实测资源

远程 `biocourse-glt`：

```text
GPU: 8 × RTX 4090（本计划只使用 4 张）
CPU: 128 vCPU（2 × Xeon Platinum 8362，64 core / 128 thread）
RAM: 503 GB
```

可用 4 张 GPU，`CUDA_VISIBLE_DEVICES=0,1,2,3` 或按实际空闲卡选择。

## 1. 先确认三件事，再开长训练

长训练前必须锁定：

### 1.1 网络结构

当前 `entity`：

- 49 token（含 global）；
- d=384 / 8 layers / 8 heads；
- 14,808,254 参数；
- AutoTavern 论文是 56+1 token / ~18M。

需要二选一：

- **A. 当前 14.8M/49**：直接长训练；优点是已知吞吐；
- **B. 对齐 56+1/18M**：先改 token/FF/head，再重新 benchmark；
- 不能混用两个结构的 checkpoint/吞吐结论。

### 1.2 训练任务

- C0：单 learner vs 7 bot，目标是过 C0 gate；
- C1：历史 checkpoint 池 / 4–8 成员联赛；
- C2：全自对弈 + 重搜；
- 任务不同，actor/数据/评测预算不同。

### 1.3 训练目标

- 只追求 C0 gate：短、便宜；
- 追求对 bot/league 的稳定强度：6–12h；
- 追求 paper 规模：4 GPU 也远不够，需要重新估算。

## 2. 4 GPU 拓扑选择

entity 只有 14.8M，**模型并行没有意义**；4 GPU 应用在数据/推理侧。

### 方案 A：1 learner + 3 inference（推荐先做）

```text
GPU0: learner（PPO update）
GPU1-3: inference servers（B=64/128 叶/决策）
CPU: actor processes -> inference queues
```

优点：

- learner 与 actor 解耦；
- inference 可独立扩 GPU；
- 适合当前 PPO 小模型/大 batch。

缺点：

- GPU0 空闲时浪费；
- 需要 actor/inference/learner 队列。

### 方案 B：4 个 data-parallel shard

```text
GPU0-3: 各自 actor group + local forward
每 N 步 all-reduce 梯度 / 同步权重
```

优点：

- 4 GPU 都参与训练；
- 易扩展到 8 GPU。

缺点：

- PPO on-policy 数据与同步复杂；
- 需要 DDP/AllReduce、版本一致；
- 当前代码没有。

### 方案 C：4 个独立 seed / 4 个 league 成员

```text
GPU0-3: 各自独立训练
```

优点：

- 实现最简单；
- 可做 seed variance/league 成员。

缺点：

- 不是单个模型加速；
- 4 个模型都要评测。

**建议**：先 A（1 learner + 3 inference），确认 actor/inference 吞吐；再决定是否 B。

## 3. CPU 数量如何定

### 3.1 关键事实

当前 `workers=64` 是 **1 个进程 64 个线程**，不是 64 actor 进程；  
MCTS 逐叶回调 + Python GIL，增加线程不会线性扩展。  
所以 **CPU 规划的前提是先做进程级 actor**，不是直接堆线程。

### 3.2 目标 actor 形态

```text
每 GPU 组: 4–8 actor processes
4 GPU:     16–32 actor processes
每个 actor: 8–32 局/多树
CPU: 2–4 core/actor（先按 4 估）
```

粗算：

- 16 actor × 4 core = 64 vCPU；
- 32 actor × 4 core = 128 vCPU；
- 不要超过 128，避免与 learner/inference/OS 争抢。

### 3.3 实测选点（必须做）

以 4 GPU 固定，扫：

```text
CPU/actor 配置: 32, 64, 96, 128 vCPU
每个配置跑 5–10 分钟 benchmark
```

记录：

- decisions/s；
- leaf/s；
- GPU util（持续采样）；
- queue wait p50/p95；
- CPU 利用率；
- 显存；
- 失败/超时。

选点规则：

1. 吞吐随 CPU 增加而增长；
2. GPU util 到 **70–85%** 后，再加 CPU 收益 <10% 就停；
3. 若 CPU 已 100% 但 GPU <50%，说明 actor/搜索是瓶颈，不是 GPU；
4. 最终 CPU 数写进 run config，不靠“感觉”。

### 3.4 当前单 GPU 参考

- sims=4，64 线程，50k decisions ≈ 203s ≈ 249 dec/s；
- sims=0，64 线程，1.26M decisions ≈ 910s ≈ 1,384 dec/s；
- 1M sims=4 的 1000 局 shard >21.5min（actor 限制）。

4 GPU 不能直接乘 4；先测。

## 4. 6–12 小时长训练预算

以下按 **4 GPU**、stage 内稳定吞吐估算；必须用 §3 实测替换。

### 4.1 三种情景

| 情景 | 4 GPU 吞吐 | 6h decisions | 12h decisions |
|---|---:|---:|---:|
| 悲观（只 1.5×） | ~375 dec/s | ~8.1M | ~16.2M |
| 中性（2.5×） | ~625 dec/s | ~13.5M | ~27M |
| 线性（4×） | ~1000 dec/s | ~21.6M | ~43M |

这些只是**采集上限**；PPO/评测/IO 另算。

### 4.2 6 小时方案（C0 优先）

```text
0:00–0:30  BC 500k / 或加载已有 BC
0:30–1:00  4 GPU + CPU 扫描，锁定配置
1:00–4:30  PPO vs bot（分片，KL anchor）
4:30–5:00  512 局 C0（单面板）
5:00–5:30  若过 gate -> 历史池；否则继续 bot
5:30–6:00  512×8 双封存 gate / 报告
```

### 4.3 12 小时方案（C0 + 联赛）

```text
0:00–0:30  BC / 加载
0:30–1:00  4 GPU benchmark + 配置锁定
1:00–4:00  C0 PPO vs bot
4:00–4:30  512 局 C0
4:30–8:00  历史 checkpoint 池 / 4–8 成员联赛
8:00–9:00  512 局 league 评测
9:00–11:30 继续训练 / 淘汰弱成员
11:30–12:00 双封存 gate + 完整报告
```

### 4.4 必须的 checkpoint/eval 节奏

- 每 250k–500k decisions：保存 trainer/model；
- 每 1M 或每 30–60 分钟：512 局评测（不是 64 局）；
- 每个 stage 结束：双封存 gate；
- 失败可回到上一版 manifest。

## 5. 资源调度建议

```bash
# 4 GPU，显式绑定
CUDA_VISIBLE_DEVICES=0,1,2,3 ...

# 限制 CPU（示例 64 vCPU）
taskset -c 0-63 ...

# 监控
nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv -l 5
```

不要把 learner、inference、32 actor 和评测同时塞满 4 GPU；  
评测应使用独立空闲卡或与训练错峰。

## 6. 当前代码差距

| 能力 | 状态 |
|---|---|
| 单 GPU entity PPO | ✅ |
| 持久 trainer / checkpoint | ✅ |
| BatchLeafServer | ✅（推理批） |
| 多线程采集 | ✅（1 进程） |
| **4 GPU learner/inference 分离** | ❌ |
| **进程级 actor pool** | ❌ |
| **CPU 自动扫描/选点** | ❌ |
| **跨 actor 版本/异步** | ❌ |
| **league/history pool** | ❌ |

因此 6–12h 长训练前，至少需要：

1. 进程级 actor + inference 队列；
2. 4 GPU 拓扑 A 或 B；
3. CPU/GPU 扫描报告；
4. 512 局评测和 checkpoint 恢复；
5. 确认 14.8M/49 还是 18M/56。

## 7. 决策请求

请确认：

1. 网络：**当前 14.8M/49**，还是先对齐 **18M/56+1**？
2. 任务：**C0 单 bot**，还是直接 **C0+历史池**？
3. 4 GPU 拓扑：**A（1 learner + 3 inference）**，还是 **B（4 shard DDP）**？
4. 长训练预算：**6h** 还是 **12h**？

确认后先做 **30–60 分钟 4 GPU + CPU 扫描**，再锁定 6–12h 预算；不会直接在没有吞吐数据的情况下承诺长训练结果。
