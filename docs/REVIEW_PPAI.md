# PPAI GPT-6 Astra 终审记录（2026-10-28）

> 评审对象：HSBRSIM 吞吐加速计划（HEAD `455ad3b` + 本轮修复）
> 评审模型：`ppai/gpt-6-astra`（通过 DSH subagent，独立读代码/跑只读命令，未占 GPU）

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
