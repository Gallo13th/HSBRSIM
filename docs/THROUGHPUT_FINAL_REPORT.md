# 加速计划终版报告（2026-10-28）

> 预算：≤4 张卡，**只用空闲卡**。本轮实际使用：actor GPU **1/3/0**、learner **GPU2**
> （GPU4–7 被邻居 `cds_ncRNA_train` 占用，util 83–90%；GPU0 仅别人 1.5 GB/0% util）。
> 全部数据为 16–20 iteration、同 seed、pipeline+bf16 的 A/B，`lag=1`、`ratio≈1.00`。

## 1. 成绩单（端到端）

| 阶段 | dec/s | collect | ppo | 相对起点 |
|---|---:|---:|---:|---:|
| stage-1 原始（串行 fp32 + history 重写 + 阻塞评测） | 1,577 | — | — | 1.0× |
| + history jsonl（O1）+ 流水线（S2）+ learner 独占卡 | 3,100 | 6.7 s | 8.9 s | 1.97× |
| + bf16（O2） | 4,392 | 6.7 s | 5.5 s | 2.8× |
| + L2 worker 侧采样（`--fast-act`） | 4,407 | 6.7 s | 5.5 s | 2.8× |
| + **lock-step 批量 actor（L1）** | **5,921 → 6,311** | **6.1 → 6.0 s** | 4.5 s | **3.8–4.0×** |
| 当前空闲卡复核（actor 1/3/0 + learner 2） | 5,331 | 6.99 s | 4.80 s | — |

结论：**1,577 → 6,311 dec/s（≈4.0×）**；30M 训练从 5h18m 降到 **≈1.4 h + 评测**。

## 2. 本轮新增（lock-step 之后的收尾工作）

### 2.1 已落地

| 项 | 内容 | 证据 |
|---|---|---|
| L1 lock-step | `collect_ppo_lockstep`：每 worker 内 N 局同步推进，一轮一次批量前向；turn 守卫键 `(game_id, seat, turn)`；`--lockstep` + `train_stage1.sh` 默认开 | `fc49fc0`、`9ef10c1`；`test_lockstep_collects_legal_ranked_records` |
| 空闲卡纪律 | 所有测量只用 1/3/0+2；邻居卡零占用 | `nvidia-smi` 对照记录 |

### 2.2 评估后**不做**的项（附数据）

**(a) Rust actor v1（批量观测接口）——收益不足**
- `Game.observe()` 已经返回 **原始字节**（f32 LE / i32），Python 侧只是 `np.frombuffer().copy()`；
  实测单决策「engine step + observe + mask + bot_action」合计仅 **11 µs**；
- lock-step 后每决策 ~0.22 ms 中，~~obs 解码~~ 只占 3%，大頭是 **引擎自身的 7 个 bot 座位推进**
  （57 µs）与 record 打包/Python 记账；
- 因此「Rust 批量观测」最多省 ~5%，**不值得**。真正的 Rust 收益需要把**整个采集循环**
  （引擎推进 + 记录打包 + 批量推理回调）搬进 Rust，即 `docs/ACTOR_RUST_OPTIONS.md` 方案 B，
  是 1–2 周量级的独立工程。

**(b) DDP learner——现在上会适得其反**
- 4 卡预算下，2 卡 learner 意味着 actor 只剩 2 卡：collect 6.0 s → **~8 s**；
  DDP 把 PPO 4.5 → ~2.5 s，但 step = max(8, 2.5) = **8 s > 当前 6.2 s**，净亏；
- 结论：**先把 collect 压到 ≤2.5 s（Rust 全采集器），DDP 才有意义**。届时 2 卡 learner +
  2 卡 actor 可把 step 压到 ~3 s。

**(c) worker 内建 batch（L4）——已修复并落地（收益有限）**
- 目标：把父进程 `parent_read 0.96 s + build_batch 1.13 s`（占 collect **30%**）并行到 worker；
- 第一版失败（`episode N 的 done 数 != 1`），原因是父进程对过滤后的局部 episode 重编号；
- 修复：worker 直接把 `episode_ids` 写成 **全局唯一键 `game_id*8 + seat`**，父进程只拼接不再重编号；
- 实测（16 iter，同卡同 seed）：`build_batch 1.13 → 0.75 s`，dec/s 5,331 → **5,435**，
  collect 6.99 → 6.98 s（几乎不变）——**瓶颈已变成 530 MB features 的磁盘读取与内存拼接**，
  不是排序/GAE。结论：L4 保留（正确、低风险、略快），但**别再指望它提速**。

## 3. 当前限速步

| 项目 | 每 iteration | 说明 |
|---|---:|---|
| 父进程 read + 拼接 | ~1.0–1.6 s | 530 MB features 读取 + concat（L4 后 build 0.75 s） |
| worker 侧采集 | ~4.5–5.0 s | 12 worker × 16 局批量前向 + 引擎推进（每决策 ~0.22 ms） |
| **collect 总计（实测）** | **6.0–7.0 s** | 三者之和，父进程读盘不可忽略 |
| PPO（bf16, learner 独占） | ~4.5 s | 40k 样本 / 1024 微批 |
| step = max(collect, PPO) + ~0.2 | ~6.0–7.2 s | 采集与 PPO 大致平衡 |

> 口径说明（PPAI 终审 §5 指出原表把 4.9 与 6.0 混用）：worker 侧、父进程 read/build、
> **总 collect** 必须分开列，`max()` 只能对总 collect 与 PPO 取。

## 4. 结论与建议

1. **当前最优配置**：`--lockstep 1 --amp bf16 --pipeline 1 --processes 12 --threads 16`，
   learner 独占一张卡，actor 用其余空闲卡（每卡 4 worker）。见 `train_stage1.sh` 默认值。
2. **下一步优先级**：
   - ① L4 正确实现（全局 episode id）→ collect −1 s（约 −15%）；
   - ② Rust 全采集器（方案 B）→ collect 可到 ~2 s；
   - ③ 之后才上 DDP learner（2 卡）把 PPO 压到 ~2.5 s，最终 step ≈ 2.5–3 s（≈12–15k dec/s）。
3. **不建议**：Rust actor v1（批量观测）、现在就上 DDP、继续调 processes/threads（已扫到最优）。
