# Rust actor / GIL 问题分析

> 问题：当前训练 actor 受 Python 线程/GIL 限制，换成 Rust 能否解决？

## 1. 结论先行

**能解决“GIL/线程扩展”这一层，但不是“把 Python 循环改写成 Rust”就自动解决。**

关键区别：

- 如果 Rust actor 仍然**每个叶节点回调 Python 推理**，GIL 还在，只是把循环搬到 Rust；
- 必须把 **搜索/引擎/actor 调度**和 **NN 推理**解耦成批请求，才能让 Rust 真正并行；
- 最彻底是把 14.8M 模型推理也放进 Rust（tch/ORT），但工作量最大。

## 2. 当前代码的真实瓶颈

`rust/crates/hsbg-engine-py/src/lib.rs::mcts_search` 注释明确写：

```text
注意：搜索期间持有 GIL（回调是 Python/NN 推理）；批量评估/异步待 P4 后续。
```

实际路径：

```text
Python thread
  -> mcts_search (PyO3)
     -> rust_search (Rust tree)
        -> call_eval_fn(py, cb, ...)  # 每个新叶一次 Python 回调
           -> BatchPPOEvaluator / PPOEvaluator
        -> 摘要/回填
```

所以：

- `mcts_search` 在 NN eval 模式下**持有 GIL**；
- `call_eval_fn` 是**逐叶**的 Python 调用；
- BatchLeafServer 只能把同一进程内提交的请求聚批，不能消除 GIL；
- `rollout && eval_fn.is_none()` 才 `py.detach` 释放 GIL——但没有 NN，不是训练。

这解释了：

- 64 线程 GPU util 只有 25–32%；
- sims=4 从 8→64 workers 只 115→191 decisions/s；
- 4 GPU 推理很好，但训练 actor 不扩展。

## 3. Rust 能解决什么

| 问题 | 纯 Rust actor + Python eval | Rust actor + batch eval | Rust actor + Rust 推理 |
|---|---|---|---|
| Python GIL | 仍受逐叶回调影响 | **基本消除** | **消除** |
| 多核 actor | 可以真正并行树/引擎 | 可以 | 可以 |
| GPU 批推理 | 需要 Python 服务 | 需要 batch 协议 | Rust 内部批量 |
| 工作量 | 中 | 中高 | 高 |
| 风险 | 回调仍是瓶颈 | 协议/队列复杂 | 模型移植/精度 |

**推荐路径：Rust actor + batch eval（中间列）。**

## 4. 目标架构（Rust actor + batch eval）

```text
Rust ActorPool (4–8 threads/processes)
  - 每个 actor: Game + MCTS tree
  - 搜索中需要 NN 时，不再直接回调 Python
  - 生成 EvalRequest {features,cards,mask,seat,request_id}
        │
        ▼
  EvalBatcher (Rust or Python inference server)
  - 收集 B=64/128
  - 一次 GPU forward
  - 回填 prior/value
        │
        ▼
  Rust actor 继续搜索
        │
        ▼
  Trajectory / records -> learner (Python/GPU)
```

实现要点：

1. `mcts_search` 改为 **可挂起**：
   - `search_step` 返回 `NeedEval` 或 `Done`；
   - 或 Rust 内部 channel：actor 提交请求后等待回填；
2. 回调从“每叶一次 Python”变成“每 batch 一次”；
3. Rust 树遍历期间 `py.detach`，不持 GIL；
4. learner 只接收轨迹，不参与 actor 循环；
5. 引擎 `Game` 每节点 clone 成本要测；必要时改 `Arc/COW` 或状态池；
6. actor 版本/权重固定到 episode/segment。

## 5. 三个可选方案

### A. 进程级 actor（最快落地）

- 每个进程独立 Python + Rust engine + model；
- 避开 GIL（多进程）；
- 当前 `ProcessActorPool` 已实现，但 30min 扫描出现 BrokenPipe，需要修；
- 优点：不改 Rust search API；
- 缺点：每进程重复模型/显存；4 GPU 各 1–2 进程。

### B. Rust actor + Python batch inference（推荐）

- Rust actor 多线程/多进程；
- 叶请求批量送 Python inference server；
- 需要改 `mcts_search` 为异步/可挂起；
- 可接 4 GPU inference；
- 工作量中等偏高。

### C. Rust actor + Rust 模型推理

- tch/ORT 在 Rust 内跑 entity18m；
- 完全消除 Python/GIL；
- 需要模型移植、batching、CUDA 内存、精度校验；
- 工作量最高，不建议作为第一步。

## 6. 还需要注意

即使 Rust 解决 GIL，也不保证 4 GPU 训练线性扩展：

- 叶请求/回填通信；
- 引擎 `Game` clone；
- 树选择/备份 CPU；
- GPU 推理 batch fill；
- learner PPO 与 actor 的同步；
- 4 GPU 拓扑 A 的 learner 可能成为瓶颈。

必须用 benchmark 证明：

```text
decisions/s, leaf/s, GPU util, queue p95, actor CPU%, 显存, 失败率
```

## 7. 建议

短期：

1. 先修进程级 actor pool（方案 A）——最快验证 4 GPU 多进程；
2. 同时设计 Rust search 的 `NeedEval`/batch API（方案 B）；
3. 只有在 A 仍受单进程 GIL/模型重复限制时，才上 B；
4. C 作为长期选项，不作为 6–12h 长训练前置。

当前结论：**Rust 是正确方向，但必须改“逐叶 Python 回调”为“批式/异步推理”，否则只是把 GIL 换个地方。**
