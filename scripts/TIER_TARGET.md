# 等级进度奖励（Tier-Target Reward）

> 状态：已实现，**默认关闭**（`--tier-target-coef 0`）。关闭时采集 records / 打包 /
> GAE 与旧路径**逐位一致**。
>
> 代码：`hsbg/az/train/tier_target.py`（纯函数 + 状态机）、
> `hsbg/az/train/parallel_collect.py`（lockstep 与逐局采集接线）、
> `hsbg/az/train/ppo.py`（串行采集接线 + `CollectConfig`）、
> `scripts/train_entity_sync.py`（CLI / history）；
> 测试：`tests/test_tier_target.py`。

## 1. 诊断证据：tier 锁死 4

`scripts/quality_monitor.py` 对 C0 champion 与 s8b@10M 的实测（两者一致）：

| 指标 | 实测 | 真实 10k+ MMR 参考 | 结论 |
|---|---|---|---|
| turn ≥9 的 learner tier p50 | **恒为 4**（t15 也是 4） | t9+ 会到 5–6 级 | 中后期从不升级 |
| 战团强度 p50（分 turn） | 真实的 **0.03–0.37** | — | 战团差 1 个数量级 |
| 升一级的即时成本 | **9–11 金币** + 一回合节奏 | — | 短期代价明确 |
| 现有势函数塑形（λ=1e-3，w_tier=1.0） | **tier 行为不变** | — | 势函数没提供「长期留在高 tier」的收益 |

为什么势函数塑形改不了 tier：`F_t = λ(γΦ(s_{t+1}) − Φ(s_t))` 在整局上**望远镜求和**为
`λ(γ^T Φ(terminal) − Φ(s_0))`，而实现里 `Φ(terminal)=0`，所以每局累计塑形奖励几乎与
中间是否升级无关（只与 `Φ(s_0)` 有关）。升级瞬间 Φ 跳高会得到一笔正 F，但**终局 Φ=0
又把这份收益收回去**；在 γ=1/0.995 下「先买怪升级、再打输」并不比「苟住不升级」更划算。
换句话说，potential-based 塑形按设计**不改变最优策略**，它无法把「应该更早升级」这个
人为先验注入策略。

因此这里改用**定向目标曲线**（不是势函数，不追求策略不变性）：直接告诉 learner
「第 7 回合应该有 4 级、第 9 回合 5 级、第 12 回合 6 级」，未达标扣分、首次达标发奖。

## 2. 公式

默认目标曲线：

```
TARGET_TIER = {7: 4, 9: 5, 12: 6}      # turn -> 期望 tier
```

在 learner 的**每个新回合开始**（该回合第一条 learner decision 之前）检查一次当前 tier
`τ`，记 `t` 为该回合号：

```
target = TARGET_TIER.get(t)
if target is None:                       Δ = 0
elif τ < target:                         Δ = −coef · tier_penalty        （miss）
elif t 未领取过:                          Δ = +coef · tier_bonus          （hit，一次性）
else:                                    Δ = 0                          （已领取，不重复）
record_first_decision_of_turn["reward"] += Δ
```

- `coef = --tier-target-coef`，**0 = 关闭**；
- `tier_penalty = --tier-penalty`（默认 0.02），`tier_bonus = --tier-bonus`（默认 0.15）；
- 「每个目标只发一次」：每个 tracker 用 `set` 记录已领取的 turn 档位（`claimed`），
  越过目标（例如 t7 直接 6 级）仍按档位发放，但同一档位绝不重复发；
- 同一 turn 只检查一次（`evaluated` 集合），回合内后续 decision 不再扣分/发奖；
- 增量加在**该回合第一条 learner decision** 的 `reward` 上（与势函数塑形的 Φ 回填顺序：
  先写 F，再叠加 tier 增量，互不覆盖）。

实现细节：

- 每局一个 `TierTargetTracker`（`evaluated` / `claimed` / `pending` 全部按局隔离；
  多线程/多进程采集天然隔离）；
- tier 读取走 `game.observe(seat)` 快路径（`global.tier = raw/6`，约 2–4 µs），失败退回
  `game.player_json`，再失败按 0（不阻断采集）；
- 只在**有新目标的 turn**读 tier；默认 3 个检查点/局，开销可忽略；
- 支持 `opponent=bot|weak`（单 learner seat）；`self`（8 座自对弈）与
  `--rust-collector` 启动期报错（Rust 采集器未接线）。

## 3. 为什么不用势函数

- 势函数塑形的最优策略不变性是**优点也是限制**：它无法表达「必须更早升级」的先验；
- 目标曲线是**有意的策略偏置**，会改变最优策略（这正是需求）；因此默认关闭、可回退，
  并用 A/B 验证「tier 上升且 human 面板不变差」；
- 不引入新的折扣/望远镜约束：奖励只加在单条 decision 上，GAE 直接消费。

## 4. 参数建议

名次效用 `u(rank)=1−2(r−1)/7`：rank1=+1.0，rank8=−1.0，**全距 2.0**；相邻名次差
≈0.286。

| 参数 | 默认 | 相对名次奖励的量级 | 建议 |
|---|---|---|---|
| `tier_bonus` | 0.15 | 全距的 7.5%，约半个名次 | 主训练 0.15；想更激进可用 0.3 |
| `tier_penalty` | 0.02 | 全距的 1%，约 1/14 个名次 | 0.02 起步；tier 不动再升到 0.05 |
| `coef` | 1.0（A/B 用） | 线性缩放 | 0=关闭；本轮 1.6M 尺度下 `coef=1` 无效，`≥5` 才见 tier 上移（§7） |

每局最多 3 个检查点，单局奖励绝对值上限 `3·coef·max(bonus, penalty)`（默认 0.45），
与终局名次奖励同量级，不会淹没 rank。

## 5. 如何关闭 / 观测

```bash
# 关闭（默认，零影响）
--tier-target-coef 0
```

`history.jsonl`：

- `ppo` 段固定记录 `tier_target_coef`、`tier_hits`、`tier_misses`、`tier_bonus_sum`；
- `collect` 段在开启时记录 `tier_target_table`、`tier_checks`、`tier_hits`、
  `tier_misses`、`tier_bonus_sum`、`tier_penalty_sum`、`tier_target_reward_sum`、
  `tier_hit_rate`、`tier_target_applied`、`tier_target_dropped`（关闭时**不新增键**）。

## 6. 失败判据与调参

A/B 观察窗 ≈ 1.8M learner decisions（40 iter × ~45k）：

1. **tier 仍不升**（`quality_monitor.py --games 32` 的 t9/t12 p50 仍 = 4）：
   - 先把 `--tier-penalty` 提到 0.05（惩罚「不升级」），再把 `--tier-bonus` 提到 0.3；
   - 仍不动则把曲线前移（如 `--tier-target-table "6:4,8:5,10:6"`）；
   - 同时看 `ppo.tier_misses`：若 miss 数远大于 hits，说明策略宁可吃惩罚也不升级
     → 惩罚量级不够或目标过高（先降到 `7:3,9:4,12:5` 验证通路）。
2. **tier 升了但 human 面板变差**（mean rank 上升 > 0.1 或 top4 下降 > 3pp）：
   - `--tier-target-coef 0.5`（减半）或 `--tier-penalty 0.01`；
   - 若只是 bonus 导致「抢升级亏节奏」，先降 bonus 到 0.1。
3. **tier 升、human 面板不变差、战团强度上升** → 正式启用（参数按 A/B 最优；
   本轮实测 `coef=1` 在 1.6M decisions 内不改变 tier，见 §7–8，故实际起步值应更高）。
4. **其它副作用**：`collect` 段 `tier_target_dropped > 0` 说明 record 索引/`game_id`
   对不上（不应发生）；`tier_hit_rate` 长期为 0 说明目标曲线过高。

## 7. A/B 方案（可复现）

从 `runs/az_entity_s8b/model.pt` 起、同 seed，跑两组各 ~40 iter（≈1.8M decisions）：

- **A**：现状（`--shaping-coef 1e-3 --shaping-w-str 1 --shaping-w-tier 1`，无 tier-target）；
- **B**：A + `--tier-target-coef 1.0 --tier-penalty 0.02 --tier-bonus 0.15`。

两组都用 `scripts/quality_monitor.py --games 32` 报告 t9/t12/t15 的 tier p50，并用
`scripts/human_panel_eval.py` 报告 human 面板 48 局 mean rank / top4 / win。

**A/B 结果（2026-10-30，cuda:7，seed 13100，40 iter / 组，各 ≈1.6M decisions）**：

起点 `runs/ab_tier/base_model.pt`（= `runs/az_entity_s8b/model.pt` 快照，md5
`9b5ad2b9…`）。tier 分布来自 `quality_monitor` 同 seed 32 局（`runs/ab_tier/tier_curve.json`），
human 面板为 `human_panel_eval.py --smoke --games 48 --seats 8`（`runs/ab_tier/human_*.json`）。

| 组 | coef | tier p50 t9 / t12 / t15 | t12 tier≥5 | t15 tier≥5 | bot 面板 mean rank | human 面板 mean rank | human top4 | human win |
|---|---|---|---|---|---|---|---|---|
| 起点 checkpoint | — | 4 / 4 / 5 | 28.1% | 54.5%（n=11） | 1.688 | 6.667 | 4.2% | 0 |
| **A**（无 tier-target） | 0 | 4 / 4 / 5 | 25.8% | 72.7%（n=11） | 2.031 | 6.479 | 8.3% | 0 |
| **B**（推荐参数） | 1 | 4 / 4 / 4.5 | 28.1% | 50.0%（n=14） | 1.375 | 6.500 | 10.4% | 0 |
| C（敏感性，仅验证通路） | 10 | 4 / 4.5 / 5 | 50.0% | 78.9%（n=19） | 1.656 | 6.792 | 4.2% | 0 |

训练内检查点通过率（`ppo.tier_hits / (hits+misses)`）：

| 组 | iter 0–7 | 8–15 | 16–23 | 24–31 | 32–39 |
|---|---|---|---|---|---|
| B（coef=1） | 4.9% | 5.1% | 5.1% | 5.0% | 5.0% |
| C（coef=10） | 5.7% | 6.5% | 8.4% | 10.3% | 10.3% |

- **B 没有改变 tier 行为**：t9/t12 的 tier p50 仍是 4，`tier_ge5` 与 A 相同（25.8–28.1%），
  训练内通过率 40 iter 内**完全持平**（≈5%）。human 面板与 A 相同（6.50 vs 6.48，
  48 局 rank 的标准误约 0.35，差异远小于噪声）；bot 面板数字（1.38 vs 2.03）在 32 局
  下同样在噪声内。**结论：推荐参数在 1.6M decisions 尺度上无效。**
- **C（coef=10）证明奖励通路有效**：t12 `tier≥5` 从 28% 升到 50%、t15 `tier≥5` 从
  55% 升到 79%、训练内通过率从 5.7% 单调升到 10.3%，且存活到 t15 的局数从 11 增到 19。
  但 human 面板没有改善（6.79 vs A 6.48），说明「单纯更早升级」并不自动变成对
  人类强度面板的胜率；提高 tier 会消耗节奏/经济，需要与战团强度一起改善。

## 8. 结论与推荐

1. **不建议在正式训练中启用默认参数**（`coef=1, penalty=0.02, bonus=0.15`）：
   40 iter / 1.6M decisions 内 tier 曲线与 A 完全一致、human 面板无改善，属于
   「花了奖励预算但没换来行为变化」。
2. **奖励通路本身是通的**：`coef=10` 时 tier 明显上移（t12 `tier≥5` 28%→50%）。
   若继续推进，建议从 `coef=5–10`（等价 `penalty 0.1–0.2`、`bonus 0.75–1.5`）起步，
   并把 A/B 拉长到 ≥300 iter（≥12M decisions）再用 human 面板做门禁。
3. **当前实现的主要短板是 credit assignment**：惩罚加在「回合第一条 decision」上，
   而真正该被惩罚的是「本回合没有选择升级/没有预留 9–11 金币」的那些动作。
   下一步优先级：
   - 把惩罚改到**回合末**（EndTurn 前仍低于目标时）或对该回合所有 decision 分摊；
   - 或对 `upgrade` 动作（动作段里的升级）给正向奖励，而不是对「没达标」给惩罚；
   - 或者把目标曲线换成「Δtier / 金币曲线」的稠密塑形（但要注意会改变最优策略）。
4. **副作用**：`coef=10` 时 bot 面板 mean rank 与起点持平（1.66 vs 1.69），human 面板
   略差（6.79 vs 6.67，噪声内），未观察到非法动作/截断/崩溃；`tier_target_dropped=0`。
5. **默认关闭是安全的**：`coef=0` 逐位等价（单测覆盖），history `collect` 段零键增量；
   打开后每局最多 3 次 `observe`，开销可忽略（40 iter 训练 wall time A 553s / B 552s，
   基本相同）。
