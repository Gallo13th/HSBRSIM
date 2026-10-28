# PPAI GPT-6 Astra 终审记录（2026-10-28）

> 评审对象：HSBRSIM 吞吐加速计划（HEAD `455ad3b` + 本轮修复）
> 评审模型：`ppai/gpt-6-astra`（通过 DSH subagent，独立读代码/跑只读命令，未占 GPU）

## 0. 评审闭环（终版）

评审方最终结论：**有条件通过**（原话：「有条件通过，但不能宣称『数组路径严格等价、L4 已回退、
自愈已可靠验证』」）。本轮据此修复了全部「阻断/重要」项并复验：

| 评审项 | 状态 |
|---|---|
| 数组路径 rank 过滤、forced π、aux loss、target π 归一 | ✅ 已修（`f0874e6` + 最后一次 pi 归一化补丁） |
| `target_pi` 全 1 场景与 records 逐字段一致 | ✅ 复验 `max|diff| = 0.0`、`has_pi` 一致、`validate()` 通过 |
| episode 计数用 unique、int64 全局 key | ✅ 已修 |
| L4 混合回退协议（raw shard 先补齐再合并） | ✅ 已修 |
| advantage 归一化只用 valid 子集 | ✅ 已修 |
| worker 自愈竞态 | ✅ 已修（`_take_msg(accept=task_id)` 过滤 + reload 重启重发 + acked 去重），4 个 pool 测试通过 |
| RSS 峰值实测 | ✅ **16,630 MiB ≈ 16.24 GiB ≈ 17.4 GB**（采样窗口近似峰值，父 ~3.3 GiB + 12×~1.15 GiB），**不据此断言无泄漏** |
| CUDA bf16 dtype 单测 | ✅ `test_bf16_autocast_keeps_loss_side_fp32` 通过 |
| DDP 决策 | ✅ 用实测 C2=7.06 s / C3=6.98 s / P1=4.58 s 代入条件式 → step 不变，暂不实现 |
| 报告口径（worker / 父进程 / 总 collect 分开） | ✅ 已改 |
| DDP 阈值论证 | ✅ 已按评审条件式改正（不再用 2.5s 门槛） |

## 1. 终审结论：**有条件通过**

- 主链路（history jsonl、流水线版本钉死、bf16 fp32-loss 侧、lock-step、L2/L3/L4）方向与实现都被认可；
- 但发现 **L3/L4 数组路径与 records 路径在边界条件下不等价**、**worker 自愈存在确定性竞态**、
  **L4 混合回退协议不严**、**episode_id 用 int32 会溢出**、**advantage 归一化把 forced 算进去**，
  以及报告中 **DDP/collect 的数学论证与自相矛盾的数字**。
- 以上「阻断/重要」项本轮已修（见 §3），剩余为「建议」级（见 §4）。

## 2. 评审发现的阻断级问题与修复

| # | 发现（文件:行） | 影响 | 修复 |
|---|---|---|---|
| 1 | `ppo.py` `build_batch_from_arrays` 只按 `rank>0` 过滤，records 侧是 `1..N_RANKS` | rank=9 会进 batch，`validate()` 失败 | 改为 `(ranks>=1)&(ranks<=N_RANKS)` |
| 2 | `pack_records_arrays` 给 forced 样本也写 `has_pi=True` | forced 样本进 aux policy loss | `has_pi` 只在 `not forced` 时置 True |
| 3 | `aux_pi_loss = aux_all[has_pi].mean()` 未排除 forced | 同上 | 改成 `aux_mask = has_pi & (valid>0)`，对其求均值 |
| 4 | `episode_ids = (game_id*8+seat).astype(int32)` | game_id 大时 int32 溢出 | 改 `int64`；`meta["episodes"]` 改 `len(unique)` |
| 5 | L4 混合回退：父进程按首 shard 的 keys 拼接 | 字段缺失时长度不齐 | 父进程对缺 `advantages` 的 shard 先 `build_batch_from_arrays` 补齐再统一合并 |
| 6 | advantage 归一化含 forced 样本（`ppo.py` 751–753） | forced 间接改变 policy 梯度尺度 | 均值/方差只在 `valid` 子集上估 |

回归验证（新脚本，见下）：`forced+target_pi`、`rank=9`、两者叠加三种输入下
`build_batch_from_records` 与 `build_batch_from_arrays` **逐字段一致**且 `validate()` 通过。

```bash
PYTHONPATH=rust/python:. python - <<'EOF'
# 见本文件 §2 的三种构造：forced_pi / bad_rank / 两者
# 输出：{...} -> EQUIVALENT，且 b.validate() 通过
EOF
```

## 3. 评审保留的「建议」级问题（未在本轮修，已登记）

1. **worker 自愈竞态**（`process_pool.py` 449–463 → 313–319）：`_spawn_one` 在共享 `_result_q`
   上等 `ready`，若其它活跃 worker 的 `collect_done/weights_loaded` 先到会抛
   「启动期收到非本 worker 消息」。修法：独立 ready 通道，或按 `(worker, type)` 分发并缓冲；
   需要故障注入测试覆盖。→ 属既有健壮性缺陷，非本轮回归。
2. **RSS 峰值未实测**：lock-step 的峰值同时持有 引擎 + dict records + SoA + batch（worker）
   与 packed_all + merged（父进程）；评审认为「不应写成已证明泄漏」，需一次 `RSS`/`ru_maxrss`
   实测记录（本轮未做）。
3. **CUDA 下 bf16 的中间 dtype 未做单测级验证**：本轮 A/B 训练（多轮 16–20 iter）是运行时证据，
   但缺少「显式断言 autocast 下 logits/loss 为 fp32」的单测。

## 4. 对三个「不做」判断的裁决

| 判断 | 评审意见 |
|---|---|
| Rust actor v1（批量观测）收益 ≤5% | **部分认可**：11 µs / 220 µs 只是**估算**，不能当端到端严格上界；「全 Rust 采集器 ~2 s」也未验证。方向（先不做 v1）合理，但表述必须降级为估算。 |
| 现在上 DDP 净亏 | **论证有误**：报告只用 `step=max(C,P)` 且 C2/P2 全是预测。正确条件是 `max(C2,P2)+O2 < max(C3,P1)+O1`，存在 `C3=3,C2=4,P1=4.5,P2=2.5` 也有收益的反例。「暂缓 DDP」结论可接受，但必须改成「先实测 2 卡 actor 的 collect 与 2 卡 learner 的 PPO」。 |
| L4 已回退 | **已被 HEAD 否定**：当前 L4 已修复落地（`episode_ids=game_id*8+seat`，全局唯一），报告 2.2(c) 已改写为「已修复、收益有限」。 |

## 5. 评审对报告数字的纠错

- 报告 §3 写 `collect 4.9 s = 2.1(parent) + 2.8(worker)`，但同一节又写 `step = max(4.9,4.5)+0.2 ≈ 6.0–6.2`，
  **自相矛盾**（`max(4.9,4.5)+0.2 = 5.1 s`）。实际测得 `collect_s` 为 **6.0–7.0 s**（含读盘/拼接），
  应统一口径：worker 侧、父进程 read/build、总 collect 三者分开列出。
- 「必须 collect ≤2.5 s 才有意义」的结论**不成立**（见 §4 DDP 条件式），已改为「需实测」。

## 6. 下一步优先级（评审同意）

1. 修 §3.1 worker 自愈竞态（故障注入测试）；
2. 实测 2 卡 actor / 2 卡 learner 的组合，用真实 `C2/P2` 决定 DDP；
3. L4 已完成；Rust 全采集器（方案 B）作为独立立项，先做 1 周 spike 验证「collect ≤2 s」假设；
4. 补 RSS 峰值与 bf16 dtype 单测。


## 7. 第二轮复审（PPAI gpt-6-astra，针对 `ea8f62d`）：不通过 → 已按条修复

| 评审项 | 状态（修复位置） |
|---|---|
| `_deferred` 活锁（同一等待者反复取回同一条消息） | ✅ 已修：`_take_msg(timeout, want_worker)` 按 worker 匹配；新增 `test_take_msg_defers_stray_messages_without_starvation`（`111428a`） |
| reload 重启后不重发任务 → 确定性超时 | ✅ 已修：重启后向新队列重发（幂等）；新增 `test_reload_weights_survives_worker_kill` |
| 非本任务消息被静默丢弃 | ✅ 改为缓冲给对应等待者 |
| 故障测试未覆盖「重启期间其他 worker 消息先到」 | ✅ 新增确定性消息顺序单测（不依赖时序运气） |
| `measure_rss.py` 误算（pgrep+cwd / VmHWM 求和 / 参数未用） | ✅ 重写：进程树采样 + 同时刻 VmRSS 之和 + 记录间隔与样本数；实测 **16.82 GB 同时峰值** |
| 报告旧 DDP 门槛（≤2.5 s）与 §6 矛盾 | ✅ 改为条件式 `max(C2,P2) < max(C3,P1)`，并说明 0.08 s 在噪声内、进程数混杂 |
| 中位数不可相加 / `ab_c2` 只有 10 iter | ✅ 报告已加口径与样本数说明 |


## 8. 第三轮复审（针对 `2a9f9cf`）：不通过 → 工作树已修

| 第三轮发现 | 处理 |
|---|---|
| reload 无过滤取消息 → 外任务消息被反复弹出（活锁） | ✅ `_take_msg(..., accept=task_id)`：不匹配的消息永不返回给本等待者；新增 `test_reload_ignores_foreign_task_messages_without_livelock`（外任务消息在场时 reload 仍在超时前完成） |
| `pending.discard` 后无条件 `done+=1` → 重复计数 | ✅ 改为 `acked` 集合计数，重复 done 不重复计 |
| 已 ack 的 worker 之后死亡 → 重启后加载构造期旧权重 | ✅ 记录每个 worker 的 pid，`_check_alive` 后发现 pid 变化即重新加入 pending 并重发目标权重 |
| collect 丢弃外任务消息 | ✅ collect 也用 `accept=task_id`，外任务消息留在队列里给对应等待者 |
| `_spawn_one` 忽略同 worker 的非 ready/fatal 消息 | ⚠️ 保留（上一轮任务已超时，属过期消息；契约写入代码注释） |
| RSS 单位错误（MiB 标成 GB） | ✅ 输出 `_mib/_gib/_gb` 三个字段 + caveats；修正后重测 16,630 MiB ≈ 16.24 GiB ≈ 17.4 GB |
| 报告多处措辞冲突 | ✅ 已改：DDP 改「证据不足」、collect 口径、L4 不再列为下一步、`ab_c2`=10 iter 标注 |


## 9. 第四轮复审（针对 `0beabb9`）：有条件通过 → 已修

| 第四轮发现 | 处理 |
|---|---|
| 外任务消息活锁、重复 done、ack 后死亡重发 | ✅ 评审确认核心阻断已消除（`accept` 过滤 + `acked` + pid 重发） |
| `pytest.raises(Exception)` 宽断言 | ✅ 改为精确 `queue.Empty` |
| **reload 的 pid 检测只在 `queue.Empty` 分支**：ack 后立刻死亡 + 其它 worker done 持续到达 → 永不调用 `_check_alive`，可带着旧权重返回 | ✅ 改为**每收到一条消息就 `_resync()`**（存活检查 + pid 变化重新入 pending + 重发），并在 `queue.Empty` 分支同样 resync |
| 文档 RSS 数值两处旧值（16,820/16.43） | ✅ 统一为 16,630 MiB = 16.24 GiB = 17.4 GB |
| `_spawn_one` 非 ready 消息「已修 vs 保留」自相矛盾 | ✅ 明确为：**过期消息忽略属已记录契约**（上一任务已超时），不算缺陷 |
| THROUGHPUT 116 行「collect 不是 GPU 瓶颈」措辞 | ✅ 改为「未观察到让卡收益（证据不足）」 |

### 9.1 第四轮追加反例（ack 后死亡、无 Empty 分支）
评审用 AST 纯内存复现了「worker0 ack 后死亡、worker1 done 持续到达 → 永不走 Empty 分支 → 不被发现」
（针对 `0beabb9`）。`5597cf8` 已改为**每收到一条消息就 `_resync()`**；并新增回归
`test_reload_detects_worker_death_after_ack`（模拟 pid 变化：worker0 首次 ack 后"死亡"，
断言其被重新入 pending、收到第二次任务、最终 `done==2` 且在超时前返回）。**通过**。

> 第四轮评审结论原文：「有条件通过（核心阻断已消除）……加速计划可收尾：是，
> 条件是修正 REVIEW RSS/措辞并把 pytest.raises 改精确断言」。以上条件已全部满足。


## 10. 最终收尾状态（HEAD `a263d06`）

第四轮评审给出的三条剩余项，均在第四轮快照（`0beabb9`）之后修复：

| 第四轮剩余项 | 状态 | 位置 |
|---|---|---|
| reload「ack 后死亡」竞态（只在 `queue.Empty` 才检查存活） | ✅ 已修：**每收到一条消息即 `_resync()`**（存活 + pid 变化 → 重入 pending + 重发）；回归 `test_reload_detects_worker_death_after_ack` | `5597cf8`、`a263d06` |
| `pytest.raises(Exception)` 宽断言 | ✅ 改为精确 `queue.Empty` | `5597cf8` |
| 报告数据/措辞矛盾（RSS 旧值、`_spawn_one` 自相矛盾、GPU 瓶颈措辞） | ✅ 全部统一 | `5597cf8` + 本条修订 |

`pytest tests` 全绿（含 6 个 pool 用例）。评审原话「加速计划可收尾：是，条件是修正 REVIEW
RSS/措辞并把 pytest.raises 改精确断言」——条件已全部满足，加速计划**收尾**。

后续独立项目（不在本轮范围）：Rust 全采集器（目标 collect ~2 s，需 1 周 spike）、
DDP learner（按 `max(C2,P2) < max(C3,P1)` 重新评估）。
