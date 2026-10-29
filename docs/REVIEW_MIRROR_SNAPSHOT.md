# PPAI GPT-6 Astra 终审：回合末快照镜像（实现）

> 审查快照 `5884f1a`（PPAI 只读）。**结论：不通过 —— 当前不允许混入正式训练。**

## 阻断
1. **注入晚于 learner 第一步**：`parallel_collect.py` 的 `while` 条件先判断 learner 是否可行动，
   若最后一个 bot 动作推进到新回合，循环立即退出、learner 先决策，注入要到下一轮外层循环才发生。
   → **已在 `5884f1a` 之后修复**：交给 learner 前无条件再 `_maybe_mirror` 一次并重判终局/待行动；
   探针脚本同样加「回合推进即 break 回回合起点」。
2. **跨版本无硬校验**：加载器只看 `schema_version`，不校验 engine/card hash/frame hash/stage，
   缺字段用默认值 → 跨版本 cid 语义漂移会静默注入。
3. **守恒失败不 fail-stop**：pool/invariant 失败只计数，污染记录仍进 PPO；正式路径应隔离整局并停批。

## 重要
- seat 选择固定 `1..N`（非随机、非完整 N 个对手）；默认采样取每 turn/seat 的**最大 Σ(atk+hp)**
  → 形成「跨局强度上包络」，不等于真实强度/MMR；须冻结并披露采样分布。
- `process_pool` 的 Rust collector 分支优先且**不检查 mirror 配置**（静默忽略）；其他分支只告警。
- 现有测试用手写 bot 循环，不是真实 `collect_ppo_lockstep`；p=0 等价性只对比新版本内部两路径。

## 混入前硬门（摘要）
p={0,.1,.25,.5,1} × seats={1,3,7}，≥1000 seeds/100k 注入，覆盖 pending/死亡/队列/缺帧；
零容忍：时序违规、重复 EID、守恒/invariant 错误、非预期拒绝、异常全为 0；拒绝前后 state 字节一致 100%；
按 turn×alive seat 报告有效覆盖；之后另行批准的受控训练（≥5 seeds、独立 holdout ≥2000 局/seed、
配对 CI：mean rank 恶化 <0.05、top4 下降 <1pp），失败立即回退 p=0。

## 真实 10k+ MMR 库边界
13,120 行全部 `library_ready=false` / `hidden_counters_complete=false`；8,622 行是
`first_attack_after_start_effects`（不能当 EOT）；来源 4 个旧 build（非 255790）。
**能**：按版本/阶段/回合分层的可见牌面强度校准、族群/等级分布比较、策略筛选、分布漂移分析。
**不能**：生成忠实的当前版完整 `player_json` 对手、恢复逐决策策略、补齐 hidden counters、
把开战后观测当 EOT 重跑。

## 附：我们自己的难度探针（`scripts/probe_mirror_strength.py`，自采 711 帧快照）
| arm | 完成局 | mean rank | top4 | 吃鸡 | applied/attempt |
|---|---:|---:|---:|---:|---:|
| 0（全 bot） | 40 | **2.00** | 97.5% | 37.5% | — |
| 2（seat1-2 注入） | 35 | **3.83** | 62.9% | 2.9% | 775/1208 |
| 3（seat1-3 注入） | 18 | 3.56 | 72.2% | 11.1% | 1111/1767 |

→ 机制**确实能把对手显著变强**（+1.8 名），但 ① 采样是强度上包络（Astra 警告），
② arm3 仅 18/40 局完成（需查为何未终局），③ 未过 Astra 硬门。**因此仍不得混入正式训练。**
