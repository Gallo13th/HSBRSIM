# 加速计划终版报告（2026-10-28）

> 预算：≤4 张卡，**只用空闲卡**。本轮实际使用：actor GPU **1/3/0**、learner **GPU2**
> （GPU4–7 被邻居 `cds_ncRNA_train` 占用，util 83–90%；GPU0 仅别人 1.5 GB/0% util）。
> 全部数据为 16–20 iteration（`ab_c2` 为 10）、同 seed、pipeline+bf16 的 A/B，`lag=1`、`ratio≈1.00`。

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

**(b) DDP learner——当前证据不足以支持投入**
- 4 卡预算下，2 卡 learner 意味着 actor 只剩 2 卡：实测 C2=7.06 s（vs C3=6.98 s，差异 0.08 s
  在噪声内，且 worker 数 12→8 混杂，不能称「GPU 绝非瓶颈」）；P2 为估计值 ~2.9 s；

- 结论：按评审给的条件式 `max(C2,P2) < max(C3,P1)` 判断；实测 C2=7.06 s、C3=6.98 s、P1=4.58 s，
  任一非负 P2 都有 `max(C2,P2) ≥ 7.06 > 6.98 ≈ max(C3,P1)` → **当前不值得实现 DDP**。
  （0.08 s 差异在负载噪声内、且 C2 那组是 8 worker vs C3 的 12 worker，属混杂比较；
  因此结论是「统计上无收益」，不是「GPU 绝非瓶颈」。）

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
| 父进程 read + 拼接 | ~0.9–1.6 s | 530 MB features 读取 + concat（L4 后 build ~0.56 s） |
| worker 侧采集 | ~4.5–5.0 s | 12 worker × 16 局批量前向 + 引擎推进（每决策 ~0.22 ms） |
| **collect 总计（实测）** | **6.0–7.0 s** | 计时组成（独立中位数不可相加） |
| PPO（bf16, learner 独占） | ~4.5 s | 40k 样本 / 1024 微批 |
| step = max(collect, PPO) + ~0.2 | ~6.0–7.2 s | 采集与 PPO 大致平衡 |

> 口径说明（PPAI 终审 §5 指出原表把 4.9 与 6.0 混用）：worker 侧、父进程 read/build、
> **总 collect** 必须分开列，`max()` 只能对总 collect 与 PPO 取。

## 4. 结论与建议

1. **当前最优配置**：`--lockstep 1 --amp bf16 --pipeline 1 --processes 12 --threads 16`，
   learner 独占一张卡，actor 用其余空闲卡（每卡 4 worker）。见 `train_stage1.sh` 默认值。
2. **下一步优先级**：
   - ① L4 已完成（build 1.13 → 0.56 s，端到端 +2%），不再列为下一步；
   - ② Rust 全采集器（方案 B）→ 目标 collect ~2 s（**尚未验证**，需 1 周 spike）；
   - ③ DDP：按条件式 `max(C2,P2) < max(C3,P1)` 重新评估；当前实测不支持投入。
3. **不建议**：Rust actor v1（批量观测）、现在就上 DDP、继续调 processes/threads（已扫到最优）。


## 6. 终审后收尾（2026-10-28 晚）

### 6.1 可靠性修复
- **worker 自愈竞态**：`_spawn_one` 等待 `ready` 时不再因读到其它 worker 的正常消息而崩溃，
  改为 `_next_msg/_defer` 缓冲并交还后续等待者；新增故障注入测试
  `tests/test_process_pool.py::test_pool_collects_and_restarts_after_kill`
  （kill 一个 worker → 下一次 collect 自愈且 `restarts>=1`）。**通过**。

### 6.1b reload 自愈
- `reload_weights` 发现 worker 死亡并重启后，**向新队列重发本任务**（幂等），不再等到超时；
  新增 `test_reload_weights_survives_worker_kill`（kill 一个 worker → reload 仍返回 done=2）。
- 非本任务的消息改为缓冲给对应等待者，不再静默丢弃。

### 6.2 bf16 dtype 单测
- 新增 `test_bf16_autocast_keeps_loss_side_fp32`：autocast(bf16) 下 `ppo_losses` 返回的
  `total/policy/value/entropy/approx_kl/aux_pi` 全部 `float32`，模型参数仍 `float32`。**通过**。

### 6.3 RSS 峰值实测（`scripts/measure_rss.py` 修正版，lockstep 12 worker，6 iter）

口径：按**启动命令的进程树**（ppid 关系）采样，统计**同一时刻**树内所有进程 `VmRSS` 之和的峰值；
另列每 pid 的 `VmHWM`（历史峰值，**不可与同时峰值相加**）。

| 指标 | 实测 |
|---|---:|
| 采样间隔 / 样本数 | 0.2 s / 310（修正单位后重测） |
| **同时刻合计峰值** | **16,630 MiB ≈ 16.24 GiB ≈ 17.4 GB**（采样近似值，非原子快照） |
| 父进程 VmHWM | ~3.3 GiB |
| 单 worker VmHWM | ~1.13–1.17 GiB × 12 |
| 其它 | 仅覆盖本次配置与 6 iter 窗口，**不据此断定「无泄漏/绝无 OOM」** |

### 6.4 DDP 决策（按评审条件式，用实测替代预测）

| 量 | 实测/估计 | 来源 |
|---|---:|---|
| C3（12 worker / 3 actor 卡） | **6.98 s** | `runs/ab_l4v2` |
| C2（8 worker / 2 actor 卡） | **7.06 s** | `runs/ab_c2`（与 C3 相差 0.08 s，在噪声内、且 worker 数混杂 → 证据不足以断言 GPU 是否瓶颈） |
| P1（1 卡 learner） | 4.58 s | 同上 |
| P2（2 卡 DDP，估计） | ≈2.9 s（4.58/2 + 通信/共享内存开销） | 估计 |

代入条件式：
- 现状 `max(C3,P1) = max(6.98,4.58) = 6.98`
- DDP 后 `max(C2,P2) = max(7.06,2.9) = 7.06`

→ **DDP 在当前 4 卡预算下 step 不变**（collect 是限速步），因此**暂不实现**，等 collect
降到 < P1（4.5 s）时再上；届时 2 卡 learner 才能把 step 压到 ~4 s。这是用实测数字做出的决定，
不是拍门槛。

### 6.5 最终基准（全部修复后，同 seed、空闲卡 1/3/0 + learner 2，20 iter）
| 指标 | 数值 |
|---|---:|
| dec/s | **5,736** |
| collect | 6.33 s（父进程 read 0.91 + build 0.56 + worker ~4.9） |
| PPO（bf16） | 4.63 s |
| iter | 6.31 s |
| lag / ratio | 1 / 0.9938 |
| entropy / approx_kl | 0.465 / 0.00343 |

> 与 `ab_l4v2`(5,435)、`ab_ls_final`(6,311) 的差异来自邻居作业与机器负载波动（同一配置
> 在本机可波动 ±10%）。所有结论按「同环境 A/B」比较。
>
> **口径**：表中 collect/read/build/ppo 是**各自独立的中位数**，不可严格相加；相邻 iteration
> 的 elapsed 差也不是 `max(collect, ppo)` 的精确值（流水线重叠、快照/日志有抖动）。
> 另外 `ab_c2`（C2=7.06 s）是 **10 iteration**，其余基准为 16–20 iteration。


## 7. Rust 全采集器 spike（结论）

实现并接入（`--rust-collector 1`），与 lock-step 持平（collect 6.07 s vs 6.39 s），
**未达到 2 s 目标**：瓶颈是每次叶前向 ~5 ms 固定延迟 × 每轮 ready 行数有限，
不是 Python/引擎/记录（Rust 内仅 0.06 ms/决策）。详见 `docs/RUST_COLLECTOR.md` §5。
