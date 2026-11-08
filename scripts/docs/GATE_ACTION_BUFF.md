# 闸门 1+2：动作额度 ∝ 收入 + 酒馆永久 buff 可 farm（实现 + 上界验证 + 小模型）

> 上一阶段（`docs/COMPOUND_INCOME.md` §5）的结论：沙盒**机制齐全、但乘性链条无法被放大**。
> 缺口不是「钱」（39 倍金币只把 t15 Σ 推到 1.3–1.5k），而是两条**结构性**限制：
> **① 动作额度不随收入增长**（40 个动作最多花 ~120 金，growth 收入下 ~60% 金币是废的）、
> **② 酒馆永久 buff 攒不起来**（`tavern_buff_p50 = 8`，真实是「每回合 5–10 次施法 ×
> 每次 +1~+5 × 触发/金色翻倍」）。
>
> 本文件做四件事：**A** 加两个开关（默认关、逐位等价）+ 契约测试；
> **B** 用脚本策略做**上界验证**（4 组 + 7 组补充档 × 100 局，纯 CPU）；
> **C** 打开闸门后用 0.667M 小模型重跑 2M 决策（s14-BC 热启动）；
> **D** 给出「是否值得进 s20 / 主沙盒默认」的结论。

## 0. 结论先行

（待填：见 §3/§4 的表）

## 1. 两个开关的语义

### 1.1 闸门 1：`--action-cap-per-gold K`（默认 0 = 关）

每回合的**有效**动作上限：

```
cap_eff(t) = action_cap + floor(gold_start(t) / K)
```

即「**基础额度 + 金币/K 个额外动作**」（选了任务里给的两个候选中的后者：
`base_cap + floor(gold/K)`，而不是 `min(base_cap, ceil(gold/K))`——后者在
`gold > base_cap×K` 时反而**降低**额度，与「收入→动作」的方向相反）。
`K=3` 即每 3 金换 1 个额外动作：30 金/回合 → 40 → **50** 个动作；99 金 → 73 个动作。

实现要点（`hsbg/az/train/economy_sandbox.py`）：

| 层 | 做法 |
|---|---|
| 引擎 `RulesConfig.turn_action_caps` | **放宽**到「最高可能金币 / K」（`SandboxConfig.engine_cap()`）；引擎的额度表是按回合的常量、`Game` 建好后不能改，所以只能放宽 |
| 沙盒（learner 侧） | `_apply_action_cap()`：本回合自主动作数 ≥ `cap_eff` 时，把 mask 掩成**只剩 EndTurn** |
| 记账口径 | `actions` = 本回合的**自主**动作数；`pending`（饰品/发现/目标等强制选择）**不消耗额度**，也不能被掩掉（掩掉会卡死） |
| 其它座位 | 不受影响：沙盒里其余 7 席每回合立刻 EndTurn / 消化 pending，放宽的额度对它们没有意义 |

- 上限保护：`engine_cap` 的额外额度不超过 `ACTION_CAP_PER_GOLD_MAX_EXTRA = 600`，
  「最高回合开始金币」在 `--gold-cap 0`（不封顶）时按 `ACTION_CAP_PER_GOLD_GOLD_BOUND = 2000`
  估。⇒ 单回合最多 `action_cap + 600` 个动作。
- 只影响 learner：引擎的 `action_cap_of()` 对全部座位生效，但另外 7 席在沙盒里
  只做 EndTurn / 冲 pending，所以「引擎额度放宽」在本沙盒里**等价于**只对 learner 生效。

### 1.2 闸门 2：`--tavern-buff-scale S`（默认 1.0 = 引擎原样）

把「酒馆永久 buff 的**增量**」整体 ×S。语义等价于「每 1 点 `stats.tavern_atk/hp`
在酒馆随从身上算成 S 点」——也就是把「每回合买 N 张被永久 buff 过的随从 = N 份 buff
进战团」这条乘性链路放大 S 倍（`docs/COMPOUND_INCOME.md` §1.4）。

**实现方式：Python 侧包装（未改 Rust）**，原因与代价写在下面。

| 项 | 做法 |
|---|---|
| 注入点 | 引擎的 ``stats.tavern_atk/tavern_hp`` 是**计量器**（15 张卡往里加），它的消费者只有 ``recruit.rs::tavern_aura()``（给新随从）+ ``Ctx::buff_tavern()``（给已经在酒馆里的随从）两个。沙盒在**回合开始 `fill_shop` 之后**与**每次 Refresh 之后**，把当前每张酒馆随从的 buff 部分补到 ``S×``：``debug edit_minion`` 直接把 ``(S−1)×aura`` 加到它的 ``atk/hp`` 上 |
| aura 复算 | ``EconomySandbox.tavern_aura_of()`` 严格照抄引擎的合成顺序：``tavern_atk/hp`` + （元素随从）``tavern_elemental_atk/hp`` + ``tavern_race``（种族掩码命中） |
| 幂等 | 按酒馆槽的 ``sid`` 记账「这张已经补了多少」：冻结的随从不会被重复翻倍，同回合内 buff 变大只补增量 |
| 默认关 | ``S=1.0`` 时**不取 view、不写状态**（`rescale_tavern_shop()` 立刻 return 0）⇒ 逐位等价 |

**为什么没走「引擎侧加乘数」那条路（以及代价）**

- 引擎侧的正确做法是给 `RulesConfig` 加一个 `tavern_buff_scale`（默认 1.0），在
  `PlayerStats::tavern_atk/hp` 的 13 个写入点（`content/{spells,trinkets,trinkets_p3,
  demons,demons_p1,tw_demons,tw_spells,tw_quilboar_neutral,heroes_eco,darkmoon,tier7}.rs`
  + `heroes_eco.rs` 的扣除点）统一乘 S。**本次没做**：改 Rust 必须重建 Python 扩展
  （`rust/python/hsbg_engine/*.so`），而 s19 训练正在跑（cuda:3–6，`--processes 32`
  会起新进程），换 `.so` 有让在跑的训练吃到不同引擎/直接崩掉的风险。**这是 s20 该做的
  改动**（见 §5），Python 侧只是本次的上界验证工具。
- **近似性的三个已知偏差**（都在文档里按「下界」标注，不夸大结论）：
  1. **计量器本身仍是 1×**：`tavern_buff_p50`（`stats.tavern_atk+tavern_hp`）**不会**
     因为 S 而变大；汇报里另给 `tavern_buff_scaled_p50 = S × 计量器`（若 buff 真的按 S
     结算时的等价量）与 `tavern_extra`（本局实际注入的额外身材累计）。
  2. **同回合内的新 buff 只按 1× 计**：回合中再涨的 buff 要等下一次 Refresh / 下一回合
     开始才补到 S×（所以是**下界**；S 越大、buff 涨得越快，低估越多）。
  3. **每次 Refresh 都会重新补一遍**：`tavern_extra` 是「酒馆里的随从被补了多少次」
     的累计，**不是**「进战团的身材」——没被买走的随从也会计入，所以别拿它跟 Σ 直接比。
- 单调性：S 只加不减、且只加在「酒馆随从的永久 buff 部分」，不碰触发链/事件/计量器，
  所以 **`S1 < S2 ⇒ 任意动作序列下的 Σ 都不更小**（不会破坏单调性）。默认 1.0 时
  状态、动作流、奖励与改动前逐位一致。

### 1.3 CLI

```bash
# 沙盒 CLI
python -m hsbg.az.train.economy_sandbox --policy spell --games 20 \
    --gold-per-turn 30 --action-cap-per-gold 3 --tavern-buff-scale 3

# 训练（0.667M 小模型，growth 收入 + 两个闸门）
python scripts/train_economy_sandbox.py ... \
    --gold-mode growth --gold-growth-rate 0.15 --gold-per-carrier 2 \
    --action-cap 40 --action-cap-per-gold 3 --tavern-buff-scale 3
```

`scripts/train_economy_sandbox.py` / `scripts/eval_income_sandbox.py` /
`hsbg/az/train/economy_sandbox.py` 三个入口都有这两个参数；`cfg.replaced()`
（金币课程 / 动作额度课程切档重建环境）会**保留**它们。

## 2. 默认等价的证据

### 2.1 动作流 sha（同 seed 逐位）

改动前先记下 20 组（5 个脚本策略 × 3 seed + growth/cap120 档）的动作流 sha /
逐回合 Σ / 奖励，改完后逐项比对：**20/20 完全相同**（`/tmp/gate_equiv.py`）。
其中 4 组固化进单测 `tests/test_sandbox_gate_action_buff.py::FROZEN_SHA`：

| 档 | 动作 sha（前 12 位） | 动作数 |
|---|---|---|
| random / fixed30 / seed0 | `b2b94ce9b09e` | 289 |
| spell / fixed30 / seed1 | `8ea4c40a0dc2` | 293 |
| greedy / fixed30 / seed2 | `327bae9642d3` | 315 |
| teacher / fixed30 / seed0 | `993bc7bdb78e` | 322 |
| spell / growth15 / seed1 | `22639e648514` | 362 |

### 2.2 度量键

两个开关默认关时**不新增任何度量键**（`actions*` / `action_cap*` 只在 `K>0` 出现，
`tavern_extra*` / `tavern_buff_scaled*` 只在 `S>1` 出现），`engine_config()` 与改动前
逐字节相同（`turn_action_caps = [40]*16`、`max_actions_per_turn = 40`）。

### 2.3 契约测试

`tests/test_sandbox_gate_action_buff.py`（**18 项**，全绿）：

| # | 测试 | 覆盖 |
|---|---|---|
| 1–4 | `test_default_switch_off_keeps_bitwise_action_stream`（4 个策略） | 默认关的动作流 sha 与改动前一致 + 不新增度量键 |
| 5 | `test_default_growth_mode_sha_unchanged` | growth 收入档同样逐位等价 |
| 6 | `test_default_engine_config_unchanged` | `engine_config()` 逐字段不变 |
| 7 | `test_action_cap_per_gold_formula` | `cap = base + floor(gold/K)`；`K=0` → base；负金币不扣 |
| 8 | `test_engine_cap_relaxes_only_when_gate_on` | 引擎额度放宽与 600 上限 |
| 9 | `test_action_cap_per_gold_binds_the_mask` | 额度用尽 → mask 只剩 EndTurn；`K=0` 原对象返回 |
| 10 | `test_action_cap_per_gold_gets_more_actions_than_base_cap` | 同一策略下额度真的被用掉更多 |
| 11 | `test_action_cap_per_gold_tracks_gold_modes` | fixed/add/growth 三档的额度逐回合 = `base + gold_start//K` |
| 12 | `test_action_cap_per_gold_no_conflict_with_cap_ramp_and_trinkets` | × 饰品开关 × 动作额度课程（`replaced()` 重建环境） |
| 13 | `test_validate_rejects_bad_gate_args` | `K<0` / `S<1` 拒绝 |
| 14 | `test_tavern_aura_of_matches_engine_composition` | aura 复算（全体/元素/种族掩码） |
| 15 | `test_tavern_buff_scale_injects_exactly_s_minus_one_times_aura` | `S=3` 补 `2×aura`、按槽幂等 |
| 16 | `test_tavern_buff_scale_real_engine_trinket` | 真引擎路径（`give_trinket` 的 on_attach aura）+ `S=1` 不动 |
| 17 | `test_tavern_buff_scale_episode_metrics` | 整局度量（`tavern_extra` / `tavern_buff_scaled` / 汇总） |
| 18 | `test_both_gates_run_together` | 两个闸门 + growth + 饰品一起开 |

回归：`tests/test_economy_sandbox.py`、`test_sandbox_gold_modes.py`、
`test_sandbox_trinkets.py`、`test_sandbox_rollout.py`、`test_sandbox_search.py`
**49 项全绿**（合计 67 项）。

## 3. 上界验证（脚本策略，100 局/档，纯 CPU）

`python scripts/gate_probe.py --games 100 --workers 12`：策略 = `spell` 基线脚本 +
「金币 > 法术生成 > 法术放大」饰品偏好 + 解除刷新上限（`IncomeSandboxPolicies`，
见 `scripts/income_probe.py`），`--turns 15 --sandbox-trinkets 1`，seed 770000+
（13 档 × 100 局 = 1,300 局，923 s，纯 CPU）。机器可读结果
`runs/comp_lines/gate_probe.json`、日志 `runs/comp_lines/gate_probe.log`。

### 3.1 任务指定的 4 组

| 档 | 配置 | t12 Σ | **t15 Σ** | **Σ15/Σ12** | `tavern_buff` | `tavern_buff`×S | `goldens` | 施法 | 总金币 | **Σ15/金** | 动作/局 | 额度 | t15≥3k 占比 | 判据 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **G0** | 基线 fixed 30 / cap 40 / S=1 | 948 | **1,062** | **1.05** | 5 | 5 | 1 | 76 | 450 | **2.36** | ≤40/回合 | 40 | 4% | ✗ |
| **G1** | + `--action-cap-per-gold 3` | 806 | **921** | **1.03** | 5 | 5 | 1 | 77 | 450 | **2.05** | 264 总 | 50 | 7% | ✗ |
| **G2** | + `--tavern-buff-scale 3` | 1,218 | **1,382** | **1.12** | 5 | 15 | 1 | 81 | 450 | **3.07** | ≤40/回合 | 40 | 13% | ✗ |
| **G3** | 两者叠加 | 1,290 | **1,505** | **1.12** | 6 | 18 | 1 | 84 | 450 | **3.34** | 303 总 | 50 | 17% | ✗ |

**判据 ✗（4 组都没打开）**：最好的 G3 也只有 `Σ15/Σ12 = 1.12`（要 ≥2）、
`t15 Σ = 1,505`（要 ≥3,000，它是 50%）。但两个闸门的方向都对：
`t15 Σ` +42%（1,062 → 1,505）、`Σ15/金` +42%（2.36 → 3.34）。

**两个中间指标**：`tavern_buff_p50` 5→6（**没动**），`goldens_p50` = 1（**没动**）。
按任务的判据口径「这两个不动 = 形状不会动」，这正是形状没动的原因。

### 3.2 补充档：为什么 G0–G3 不够（闸门 1 只在「钱多」时才咬）

fixed 30 金/回合下，40 个动作本来就花不完 30 金（脚本实际只用到 ~18–21 动作/回合），
闸门 1 几乎没有发力点。所以补了 3 组 growth 收入（与 G15 同口径）与 3 组「钱极多」上界：

| 档 | 配置 | t12 Σ | **t15 Σ** | **Σ15/Σ12** | `tavern_buff` | `tavern_buff`×S | `tavern_extra` | `goldens` | 施法 | 总金币 | **Σ15/金** | 动作/局 | 实际额度 | 回合末剩金 | 额度咬住回合 | 判据 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **G0g** | growth 0.15 + 2/载体（= G15 口径） | 1,196 | **1,428** | **1.02** | 8 | 8 | 0 | 1 | 98 | 1,167 | 1.22 | ≤600 | 40 | 690 | 0 | ✗ |
| **G1g** | + K=3 | 1,459 | **1,590** | **1.00** | 8 | 8 | 0 | 2 | 114 | 1,172 | 1.36 | 836 | 66 | **336** | 1.54 | ✗ |
| **G3g** | + K=3 + S=3 | 1,985 | **2,204** | **1.00** | 8 | 24 | 47,748 | 2 | 127 | 1,172 | 1.87 | 838 | 66 | 339 | 1.94 | ✗ |
| G3gS6 | + K=3 + S=6 | 2,749 | **3,458** | **1.01** | 10 | 60 | 111,575 | 2 | 136 | 1,172 | 2.95 | 842 | 66 | 364 | 2.23 | ✗（Σ 过 3k） |
| G3gS12 | + K=3 + S=12 | 4,484 | **4,734** | **1.02** | 12 | 144 | 269,918 | 2 | 165 | 1,171 | 4.06 | 835 | 66 | 417 | 2.45 | ✗（Σ 过 3k） |
| G3gS24 | + K=3 + S=24 | 9,166 | **10,794** | **1.11** | 13 | 312 | 403,961 | 1 | 181 | 1,170 | **9.25** | 831 | 66 | 451 | 2.33 | ✗（Σ 过 3k） |
| Ub0 | growth 0.35 + 无金币上限 + 动作 120（= I4/G35u） | 1,202 | **1,206** | **1.00** | 8 | 8 | 0 | 2 | 94 | 7,804 | 0.15 | ≤1800 | 120 | 6,335 | 0 | ✗ |
| Ub1 | Ub0 + K=3 | 1,231 | **1,257** | **1.00** | 8 | 8 | 0 | 1 | 90 | 7,808 | 0.16 | 3,847 | 293 | 3,967 | 7.11 | ✗ |
| Ub2 | Ub0 + K=3 + S=12 | 6,438 | **6,672** | **1.00** | 11 | 132 | 3,939,975 | 1 | 142 | 7,812 | 0.85 | 3,905 | 293 | 3,970 | 7.37 | ✗（Σ 过 3k） |

三条读数：

1. **闸门 1 的作用是真金白银的「效率」而不是「形状」**：growth 收入下它把额度从 40 抬到
   66（每回合 ~56 个动作）、把**回合末浪费掉的金币从 693 砍到 372（−46%）**、
   把 `t15 Σ` 的**均值**抬 +48%（1,855 → 2,746，p50 只 +11%，见 §3.3 的配对检验）。
   但在**钱极多**的上界档（Ub0→Ub1，金币 7.8k、额度 293、动作 3,847）里 Σ 只 +4%
   （1,206 → 1,257）——因为脚本把多出来的动作花在**刷新**上（施法数 94 → 90 没涨、Σ 没涨），
   瓶颈变成「每回合只有 7 张酒馆牌 + 手牌 10 张」。
   ⇒ **「动作额度 ∝ 收入」必须配「每回合可买的牌也 ∝ 动作」才有用**（见 §5）。
2. **闸门 2 是**唯一**能把绝对 Σ 抬一个量级的杠杆，而且几乎是线性的**：
   S=3/6/12/24 → t15 Σ 2,204 / 3,458 / 4,734 / 10,794（`Σ15/金` 1.87 / 2.95 / 4.06 / **9.25**）。
   S=24 的 `Σ15/金 = 9.25` 已经接近真实 10k+ 的 **9.9**（`docs/COMPOUND_INCOME.md` §5.1）
   ⇒ **「每 1 金换多少身材」这个缺口可以被酒馆 buff 的放大补上**。
   但这**纯粹是「同样的 buff 计量器值更多钱」**：`tavern_buff_p50` 全程 5→13（S 不改计量器，
   见 §1.2 的近似性①），所以形状一点没动。
3. **`Σ15/Σ12` 在 13 个档里是 1.00–1.12，与 S、K、金币量级（450 → 7,812）都无关**。
   ⇒ **形状不是被这两条限制卡住的**：t12→t15 要涨 2 倍，需要的是「**t12 之后**才开始
   自我加速」的正反馈。S 只是把一个**随时间缓慢增长**的量（计量器 0→13）乘大，
   所以它放大的是**整条曲线**，不是**斜率**。

### 3.3 配对检验：闸门 1 到底值多少（100 对同 seed）

100 局 p50 在重尾分布下并不稳（`t15 Σ` 的 p90 是 p50 的 2–4 倍），所以对「同一批 seed、
只切一个闸门」做了配对检验（`/tmp/paired.py`，100 对，bootstrap 400 次）：

| 配对 | Σ15 均值 | Σ15 p50 | 均值差 | 中位差 | b 胜率 | 配对 bootstrap 95% CI | 回合末剩金（均值） |
|---|---|---|---|---|---|---|---|
| G0 → G1（fixed 30 加 K=3） | 1,228 → 1,364 | 1,062 → 921 | +11% | −13% | 0.45 | [−117, +439]（**跨 0**） | 203 → 203 |
| **G0g → G1g**（growth 收入加 K=3） | **1,855 → 2,746** | 1,428 → 1,590 | **+48%** | +11% | 0.55 | **[+334, +1,572]**（显著） | **693 → 372（−46%）** |

读数：

- **fixed 30 金下闸门 1 在噪声内**——这与它的机制一致：40 个动作本来就花不完 30 金
  （脚本实测只用到 ~18–21 动作/回合，额度只在 0.44 个回合里咬住）。
- **growth 收入（金币 2.6×）下它显著有效，而且效果集中在重尾**：均值 +48%、中位 +11%、
  胜率 55%、CI 不跨 0；同时**把回合末浪费掉的金币砍掉 46%**（693 → 372）——
  正是「~60% 金币是废的」那条诊断的直接反证：动作额度就是那 60% 的闸门。
- 但「钱极多」档（Ub0 → Ub1，金币 17×）只剩 +4%——瓶颈换成「每回合只有 7 张酒馆牌」。

⇒ 闸门 1 的正确用法：**只在收入 > 30 金/回合的档位开**，并且必须同时放宽「每回合可买的牌数」
（否则多出来的动作只能变成刷新）。

### 3.4 判据逐条

| 判据 | 门槛 | 最好的一档 | 判定 |
|---|---|---|---|
| `Σ15/Σ12`（形状） | ≥ 2 | **1.12**（G2/G3） | **✗**（差 1.8×） |
| `t15 Σ`（绝对量级） | ≥ 3,000 | **10,794**（G3gS24） | **✓**（S≥6 的 4 个档都过） |
| 两者同时 | — | — | **✗ ⇒ 形状闸门没打开** |
| `tavern_buff_p50`（中间指标） | 动起来 | 5 → 13（只跟收入/施法数走，**不跟 S 走**） | **✗** |
| `goldens_p50`（中间指标） | 动起来 | **1–2**（13 档全是 1–2） | **✗** |


## 4. 小模型重跑（0.667M，s14-BC 300k → PPO 2M）

（待填）

## 5. 结论：是否值得进 s20 / 主沙盒默认

（待填）
