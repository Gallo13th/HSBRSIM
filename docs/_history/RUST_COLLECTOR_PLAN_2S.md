# 追 2 s：方案与实测结论（PPAI GPT-6 Astra 设计 + 本轮落地）

> 设计方：`ppai/gpt-6-astra`（只读代码 + runs 记录）。落地/实测：本仓库 `runs/ab_*`。
> 结论：**这一次仍没到 2 s**；按用户要求「追不到就算了」，本文件同时记录可复现的证据与后续若重启
> 该项目的唯一高价值路径。

## 1. Astra 的核心判断（原文要点）

- **2 s 不能承诺，只能"有条件可达"**。算术：`wall ≥ R × L(B)`，R 是「最长局的串行决策深度」（每局
  一轮一步），L(B) 是每轮前向延迟；**加 GPU 不消灭 R × L(B)**，只分摊每个 GPU 上的局数。
- 现状：P12 ≈6.07 s；若按 40k 决策、单卡 5.2–6.1k dec/s，2 s 需要 ≥10.5k dec/s ⇒ **至少 2 卡、
  工程上 3–4 卡**；4 卡线性理想 ≈1.52 s 但「跨卡同步/启动/落盘/尾延迟」未验证。
- **只做一件事**：把推理改成「跨 collector 的 ready-row 合批 + 常驻 GPU buffer」，因为现有
  `ab_ls_final` 的 `batch_max=1`、`batch_fill=0.133`，每轮批量潜力最大。
- 其他 P0：Rust `pending/record` 复用分配与 bytes 边界；**禁止 logits D2H 后再 H2D**（应 fused）；
  固定 bucket 的 CUDA graph/compile 需 warmup 并严格 A/B（首次编译成本要排除）。
- P1：2–4 GPU 分片 + 服务端动态批 + backpressure；P2：投机 macro-action（默认改变 on-policy，
  不可直接用于 PPO）。
- A/B 协议：固定 pt/commit/cfg/seed + warmup；≥10 iteration，报 p50/p95 的 wall、rounds、
  ready rows、forward batch、GPU/CPU 占用、copy 字节、records/s、illegal/truncated、bitwise seed；
  判据 `p95 collect ≤2.2 s` 且语义无损失（0 illegal、lag ≤1）。

## 2. 本轮实际尝试与结果

| 尝试 | 结果 |
|---|---|
| 常驻 device 张量（预分配 + copy_ 复用）替代每次 `to(device)` | B=64: 6.92→5.69 ms（**-18%**）；B=128/192 无变化（9.70 vs 9.55 / 12.87 vs 12.97）→ 固定延迟来自前向本身 |
| `torch.compile(mode="reduce-overhead")` + 固定桶 padding（32/64/128/256/512） | **不可用**：动态形状导致 CUDA graph 数量爆炸（51 个），真实采集里 forward 2.98 s → **20.15 s**（B=96）或 60 s（未 padding 时）；已回退为 opt-in 且默认关 |
| `--leaf-wait-ms 0.1`（缩小聚批窗口） | 反而更慢：P12 collect 6.07 → 8.87 s、P6 8.80 → 9.32 s（噪声 + 邻居作业占 GPU4–7 时 CPU 竞争） |
| 跨 shard 合并一次前向（`collect_ppo_rust_multi`） | 同 192 局下无显著收益（4×48=3,277 / 8×24=3,197 / 12×16=3,175 dec/s vs single 3,109）——因为**总 ready 行数不变**，只是换了个分组方式 |
| 整批 torch 采样（已落地，非本轮） | 真实收益：单卡 192 局 3,109 → 6,063 dec/s |

### 为什么"跨 collector 合批"没有带来预期收益
Astra 的假设是「多个 collector 的行可以合成一个大前向」。但实测：**同一进程内多个 collector 的
ready 行总和 ≈ 单 collector（同样的局数）的 ready 行**，因为 ready 行数由「总游戏数」决定，
而不是由 collector 个数决定。要真正提高每轮行数，必须**在同一 GPU 上放更多局**（例如 192 局/卡），
而这已经是最优形态（0.15 ms/行）。跨进程共享推理服务能让多进程的行合并，但每个 worker 已经在
自己 GPU 上跑 16–64 局，合并后每个 GPU 的行数不变——除非让 1 个进程服务多张卡的采集，
即「集中式推理服务」，这与当前 per-worker 私有 server 的拓扑冲突，属于新架构。

## 3. 结论

- **本轮 2 s 未达成**（最好 6.07 s，与 lock-step 6.39 s 持平）；按用户要求终止追击。
- 若要重启，唯一高价值路径（按 Astra + 实测）：
  1. **集中式推理服务**：1 个进程持有模型、服务多张卡上的 collector（IPC/RPC），
     把所有行合成 192–512 行/次前向；同时把 collector 拆成「只做引擎」的轻进程（Rust 已有）。
  2. **常驻 pinned + device 输入缓冲 + 融合采样**（本轮已验证 B=64 -18%，需配合大 batch）。
  3. **CUDA graph 需要固定 shape + 预分配输出**，不能靠 `torch.compile` 自动动态图。
  4. 若允许改任务：观测降维（3227 → ~1k）是唯一能把 R × L(B) 同时压下来的结构性手段。
- 计量教训：`batch_sizes` 记请求数不是行数；`sum(forward_s)` 不是 wall；比较必须在同一
  commit/seed/checkpoint 下进行（本轮 `ab_rc_rust` 的 6.52 s 与 `docs` 里 6.07 s 不是同一测次）。
