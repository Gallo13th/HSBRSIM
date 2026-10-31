# 法术缩放载体：识别、教师策略与指标（离线、纯 CPU）

> **一句话结论：真正稀缺的不是「载体卡」，而是「升到 tier4–5 并围绕载体施法」这个行为。**
> 池内+已实现、能把施法转成永久身材的载体共 **11 张（+11 个金色 id）**，其中
> **tier 3 就有 2 张**（Timecap'n Hooktail / Vicious Mindslasher，任意酒馆法术触发，
> 不需要目标）。s15 当前权重在 200 局里**宽口径载体率 40%**（t9 30.5%）、
> **窄口径（5 张 cast-on-this + Felboar）3.5%**——窄口径低不是因为抽不到，
> 而是 **tier 分布 t1/t2/t3 = 822/706/483 个回合、t4 只有 96 回合、t5 只有 3 回合**。
> 以载体为核心的教师把窄口径载体率从 **3.5% → 27.5%**、宽口径 **40% → 58.5%**，
> 每局「触发载体的施法」从 **5.8 → 10.9** 次，`r(载体回合数, Σ₁₂)` 从 **+0.074（CI 含 0）
> → +0.255 [0.06, 0.44]（CI 不含 0）**；但 **t12 Σ p50 = 410 < 1132（=2×566）**，
> 教师打不出「2× 身材」——规则教师的整体棋力只与引擎 bot 相当（t12 Σ p50 363）。

- 引擎 / 数据：`hsbg_engine` 37.0.0.255790，默认 `RulesConfig`（内容模式 `Implemented`）。
- 权重：s15 `runs/az_entity_s15/snapshots/step_001001/model.pt`（训练在跑，**未 kill /
  未重启 / 未占 GPU**，全部 `--device cpu`）。
- 产物：`data/scaling/carriers.json`、`runs/scaling_carrier/`（rollouts / audit / metrics）。
- 脚本：`scripts/carrier_audit.py`（清单 + rollout 审计）、`scripts/carrier_teacher.py`
  （教师 + 200 局评测）、`scripts/carrier_metrics.py`（面板/退火门指标）、
  `scripts/carrier_common.py`（公共库）、`scripts/quality_monitor.py`（已接入三指标）。

---

## 0. 先读：对 `docs/SCALING_SIGNAL.md` 的两处更正

| # | 旧文档 | 实测（本报告） | 原因 |
|---|---|---|---|
| 1 | 「缩放载体 5 张×普通/金色 + Felboar = 11 个 id，500 局里只有 **6–9%** 上场」 | 窄口径真实值：s15 step301 **3.0%**（t9 **2.0%**）；宽口径 **36%**（t9 25.5%）。池内可用载体是 **11 张**，不是 5 张 | 旧脚本 `card_id_of` **错位一张**（见 §1.3） |
| 2 | 「`r(载体在场回合数, Σ₁₂) = −0.14`，这是唯一未过门」 | 正确重算：同一 200 局 `r = +0.074 [−0.145,+0.278]`；教师 200 局 `r = +0.255 [0.06,0.44]` | 同上（载体 id 映射错） |

**结论：`SCALING_SIGNAL.md` §2.3 / §8 的「载体稀缺」读数不能直接用于课程退火判据**；
载体机制的定性结论（没有载体时施法不复利、奖励缺梯度）仍然成立，但数字要换成本报告。

---

## 1. 载体清单与识别

### 1.1 定义

**载体（carrier）**：把「施放法术」转成**永久身材（或等价复利）**的随从。按触发分四类：

| 触发类 | 含义 | 需要目标吗 | 池内张数 |
|---|---|---|---|
| `cast_on_self` | 「每当你**对本随从**施放法术」 | 是，目标必须是它自己 | 3 |
| `cast_on_race` | 「每当你对**某类型随从**施放法术」 | 是，目标是该类型（可以是它自己） | 2 |
| `cast_tavern` | 「每当 / 之后你施放**酒馆法术**」 | 否（全局触发） | 5 |
| `after_n_spells` | 「施放 N 个法术后」 | 否 | 1 |
| `cast_on_minion` | 「每当你对一个随从施放法术」 | 是，任意随从 | 0（池外） |

### 1.2 主集合（池内 + 已实现 + tier≤6 + 成长）：11 张 / 22 个 id

| 卡 | id | tier | 种族 | 触发 | 每施法期望收益（普通 / 金色） | 复利 |
|---|---|---:|---|---|---:|---|
| **Devilish Distractor** 恶魔干扰者 | `BG36_762` | 5 | DEMON | cast_on_self | 酒馆随从本局永久 **+1/+2**（≈15 Σ/次，按 5 只）；金 +2/+4 | ✓ |
| **Living Azerite** | `BG28_707` | 5 | ELEMENTAL | cast_tavern | 酒馆元素本局永久 **+4/+3**（≈21 Σ/次，按 3 只）；金触发两次 | ✓ |
| **Felboar** | `BG28_633` | 5 | QUILBOAR+DEMON | after_n_spells | 每 3 次施法吞一只酒馆随从（≈4 Σ/次）；金双倍 | ✓ |
| **Shamanic Tidecaller** | `BG36_704` | 5 | MURLOC | cast_on_race(MURLOC) | 手+场鱼人 **+3/+3**（≈18 Σ/次，按 3 只）；金 +6/+6 | ✓ |
| **Forsaken Weaver** | `BG34_692` | 6 | UNDEAD | cast_tavern | 亡灵本局 +3 攻（≈9 Σ/次，按 3 只）；金 +6 | ✓ |
| **Gatekeeper Amalgam** | `BG36_640` | 6 | ALL | cast_on_self | 再施放 Misplaced Tea Set（每类型 +4/+4，≈32 Σ/次）；金两次 | ✓ |
| **Timecap'n Hooktail** | `BG27_005` | **3** | PIRATE+DRAGON | cast_tavern | 全场 +1 攻（≈7 Σ/次）；金触发两次 | – |
| **Vicious Mindslasher** | `BG36_108` | **3** | ABERRATION | cast_tavern | 自身+神明 +1/+2（≈3 Σ/次） | – |
| **Twilight Tidehunter** | `BG36_703` | 4 | MURLOC | cast_on_self | 手牌最左随从 +8/+8（16 Σ/次）；金 +16/+16 | – |
| **Glambot** | `BG36_853` | 4 | MECHANICAL | cast_on_race(MECH) | 磁力 4/4（8 Σ/次）；金两次 | – |
| **Charging Czarina** | `BG28_741` | 5 | MECHANICAL | cast_tavern | 圣盾随从 +4 攻（≈8 Σ/次，按 2 只）；金 +8 | – |

金色 id = 卡表 `golden` 字段（`BG36_762_G` 等），同名，可被三连得到。
机器可读版：`data/scaling/carriers.json`（`carriers[].trigger / per_cast /
expected_sigma_per_cast / goldens / in_tavern_pool / implemented / script_file`）。

### 1.3 识别方法（三重取证）与旧脚本的错位 bug

1. **卡表** `rust/crates/hsbg-engine/data/cards.json`：对 `text`/`text_zh` 跑宽正则
   （`cast a spell` / `cast a Tavern spell` / `after you cast N spells` / `施放…法术`），
   再用 `classify_trigger` 细分；
2. **内容脚本** `rust/crates/hsbg-engine/src/content/*.rs`：扫含
   `listens: ev::SPELL_CAST` 的 `Script { … }` 块，取块前的卡 id（共 40 个监听者，
   其中 12 个是池内随从；与卡表结果取并集）；
3. **运行时可用性** `hsbg_engine.catalog_json()`：`in_pool` / `implemented` / `tier`
   （内容模式 `Implemented` 会剔掉没实现的卡）。

**错位 bug（重要）**：`hsbg_engine.card_info(i)` 的实现是 `CardId((i-1) as u16)`，
即 **1-based**；而 `player_json` 的 `Minion.card`／`view` 的 `cid` 是 **0-based**。
`scripts/scaling_signal_analysis.py::card_id_of` 直接用 `E.card_info(i)`，**整体错位一张**。
实证：

```python
>>> E.card_info(2968)[0]          # 旧脚本的用法
'BG36_851_G'                       # 错：实际是上一张卡
>>> E.card_info(2968 + 1)[0]       # 正确（或 catalog_json 的 cid→id）
'BG36_853'
```

本报告一律用 `catalog_json()` 的 `{cid → id}` 映射；`scripts/carrier_audit.py::adapt_legacy`
兼容旧 `runs/scaling_signal/rollouts/*.jsonl`（`board_cards` 是 0-based cid）。

### 1.4 登记但**不进主集合**的同类（供完整性核对）

| 卡 | id | 原因 |
|---|---|---|
| Vigilant Bristlemane | `BG36_510` | `implemented=false` + 池外（旧文档把它算进 5 张） |
| Fleeing Fugitive | `BG36_921` | 实现但池外（tier1 Naga）；旧文档同样算进 5 张 |
| Sha of Fear | `BG36_111` | tier 7（`max_regular_tier=6` 抽不到） |
| Critter Wrangler / Eventide Brute / Athissa / Torrential Ruiner / Sundered Matriarch / Nalaa / Timewarped Nalaa / Imperial Defender / Batty Terrorguard / Zesty Shaker | `BG23_003` 等 | 池外 |
| Faceless Converter / Fire-forged Evoker | `BG36_318` / `BG32_822` | 死亡之声/战斗开始按施法数改进，**不在施法瞬间成长** |
| Lorewalker Scroll / Lovely Locket / Honeycomb Ring / Felsteel Cleaver | `BG30_MagicItem_422` 等 | **饰品**（非随从）；机制上也是载法缩放，已在清单里单列 |

### 1.5 窄口径（复现旧文档用）

`narrow` = 旧文档的 5 张 `cast a spell on this`（`BG36_762/703/640/510/921`）+ Felboar
（`BG28_633`），普通/金色 = **12 个 id**。其中**池内可得的只有 3 张**
（Distractor / Tidehunter / Amalgam），另 2 张池外——所以窄口径读数天然偏低。

---

## 2. s15 当前 rollout 的载体统计（200 局，s15 训练同分布）

驱动：`scripts/carrier_audit.py --run`，与 `docs/SCALING_SIGNAL.md` §1.1 同一条注入序
（5 席人类战团 `p=0.9` + 2 席镜像 `p=0.2` + bot；`record_log=1` 让引擎日志逐次记录
`p0 casts <Spell> on <Target>`），200 局 0 错误。

### 2.1 载体出现率

| 口径 | 宽口径（11 张） | 窄口径（5+Felboar） |
|---|---:|---:|
| 局级：曾上场 | **40.0%** | **3.5%** |
| t9 在场 | **30.5%** | 2.0% |
| t12 在场 | 10.0% | 0.0% |
| 商店曾出现 | 43.0% | – |
| 手牌曾出现 | 48.0% | – |
| 实际买过 | 29.0% | – |
| 回合级：招募末在场占比 | 18.3% | 1.0% |
| 平均在场回合数 | 1.93 | 0.19 |

**每张载体的出现**（宽口径，200 局）：

| 载体 | tier | 上场局数 | 商店局数 | 买过局数 | 在场回合 |
|---|---:|---:|---:|---:|---:|
| Timecap'n Hooktail | 3 | **80** | 65 | 50 | 318 |
| Vicious Mindslasher | 3 | 10 | 41 | 7 | 48 |
| Glambot | 4 | 3 | 3 | 0 | 12 |
| Twilight Tidehunter | 4 | 4 | 6 | 4 | 10 |
| Gatekeeper Amalgam | 6 | 3 | 2 | 2 | 10 |
| Charging Czarina | 5 | 4 | 0 | 0 | 9 |
| Forsaken Weaver | 6 | 1 | 2 | 0 | 3 |
| Devilish Distractor / Felboar / Living Azerite / Tidecaller | 5 | **0** | 0–1 | 0 | 0 |

**为什么 tier5 载体是 0**：s15 的 tier 分布是
`t1 822 / t2 706 / t3 483 / t4 96 / t5 3 / t6 3` 个招募末回合——
**t4 只在 4.8% 的回合出现，t5 只出现 3 次**。也就是说窄口径载体的瓶颈是**升 tier**，
不是“商店抽不到”（大厅种族可用率 100%，可抽到时商店出现率 43%）。

### 2.2 有载体 vs 无载体的 t12 Σ

t12 = 第 12 回合招募末快照（n=62 局活到 t12）：

| 组 | n | mean | p25 | p50 | p75 | p90 |
|---|---:|---:|---:|---:|---:|---:|
| 全部 | 62 | 899.7 | 645.5 | **866.5** | 1116.5 | 1314.0 |
| 曾载载体（≤12） | 25 | 982.2 | 589.0 | **997.0** | 1256.0 | 1440.4 |
| 从未载体 | 37 | 843.9 | 671.0 | 857.0 | 1042.0 | 1177.8 |

均值差 = **+138 Σ**，95%CI **[−54, +344]**（局级 bootstrap）——方向为正但不显著
（载体局本身也更容易活到 t12，选择效应）。

### 2.3 有载体时的「对载体施法」分布

引擎 `PlayerStats` 只给总施法数，不暴露「打给谁」；本报告从 `record_log` 的
`p0 casts <Spell> on <Target>` 逐条解析，并区分两种口径：

- **strict（对载体施法）**：日志目标名字就是载体；
- **trigger（触发载体）**：目标就是载体 **或** 场上有 `cast_tavern / cast_any /
  after_n_spells` 类载体（这类任意法术都触发，不需要目标）。

| 指标 | s15 step1001（200 局） |
|---|---:|
| 每局施法总数 | 21.5 |
| **每局触发载体的施法**（主口径） | **5.79**（有载体局 14.1） |
| 每局 strict 打给载体 | 0.54 |
| 每个载体在场回合的触发施法 | 2.74 |
| 触发施法 p50 / p90 / max | 0 / 19 / 59 |

**读数**：s15 其实每局施法 21 次，其中 5.8 次落在“场上有载体”的回合里；但它
**几乎从不主动把法术打在载体身上**（strict 0.54/局），也没有围绕 t3 载体（Hooktail/
Mindslasher，80/10 局）做“买法术→施放”的循环——原因是它**不买法术**（商店出现 43%、
买入很少）且**不升级**。

---

## 3. 以载体为核心的教师（`scripts/carrier_teacher.py`）

### 3.1 规则（确定性、可执行）

输入：`Game.view(seat)` 的 `board / hand / shop / gold / tier / pending / mask`
（外加大厅种族 `lobby_races`，引擎按种族过滤卡池）。输出：一个动作下标。优先级：

1. **有载体先拿**：手牌载体立刻上场（满场先卖最弱非载体）；商店载体金币够就买
   （同 id 已有 1 张时 +15 三连权重）；金币不够就**冻结**商店等下一回合；
2. **有载体就打在载体上**：场上有主集合载体时，手牌法术全部施放（酒馆法术施放不花
   金币，只花 1 个动作）；`pending.kind == "target"` 时优先选载体自己的 eid
   （`cast_on_race` 载体则优先同种族随从），其余目标按身材；
3. **没载体就攒着/换身材**：手牌法术只在 ① 手牌满 ② 已有 ≥2 张法术 ③ 大厅没有载体
   种族 ④ `turn ≥ 11` 时才打出去；金币优先升 tier（curve **4/6/8/10** 到 t2/t3/t4/t5，
   目标 tier 由**可用载体的最高优先级那张**决定，封顶 5）、买最高身材随从；
4. **其余按 greedy**：激活随从（白嫖 buff）、英雄技能、三连（+15）、便宜酒馆法术
   （≤2 金，买来施放不花钱）、满场用更强换最弱（`_value = Σ + 3×tier + 3×关键词`，
   每回合 ≤3 次）、刷新 ≤2 次/回合；
5. 每回合动作上限 40（与训练同口径），超过就 EndTurn。

合法性：每个首选动作先过引擎 `legal_mask`，非法才回退。**实测 200 局 / 21,087 次决策
`illegal_first_choice = 0`、`fallbacks = 0`、合法率 100%**（s15 分布 200 局 / 11,496 次
决策同样 100%）。

### 3.2 教师效果（200 局 × 两个对手分布）

两个 arm 用**同一套教师参数**，只改对手分布：

| 指标 | s15 step1001 | 教师（7 bot，对齐 566 口径） | 教师（s15 分布） |
|---|---:|---:|---:|
| 局数 / 错误 | 200 / 0 | 200 / 0 | 200 / 0 |
| 平均名次 / top4 | 5.48 / 30% | **5.39 / 34%** | 7.58 / 0% |
| 死亡回合 p50 | 11 | 11 | 8 |
| 宽口径载体率 | 40.0% | **58.5%** | 25.0% |
| **窄口径载体率** | 3.5% | **27.5%** | 6.0% |
| t9 载体率（宽/窄） | 30.5% / 2.0% | **40.0% / 8.0%** | 9.5% / 2.0% |
| 载体在场回合占比 | 18.3% | 25.2% | 6.4% |
| 每局施法总数 | 21.5 | 19.7 | 6.5 |
| **每局触发载体的施法** | 5.79 | **10.88** | 2.09 |
| t12 Σ p50（n） | 866.5（62） | **410（84）** | 无（0 局到 t12） |
| 有载体 vs 无载体 t12 Σ | 997 vs 857 | 420.5 vs 317（差 **+105 [21,186]**） | – |
| **r(载体回合数≤12, Σ₁₂)** | +0.238 [−0.083,+0.485] | **+0.255 [0.060,0.443]** | – |

**教师把载体率写进去了，但 t12 Σ 没到 1132。** 原因不是“载体没用”——教师内部
有载体组比无载体组 t12 Σ 高 **+105（CI 不含 0）**，`r` 也显著为正；原因是**规则教师的
整体棋力只与引擎 bot 相当**：同 seed 下引擎 bot 的 t12 Σ p50 是 **363**、教师 410，
而 s14_70M 的 566 是一个训练过的网络。要在 1x 经济下把 t12 Σ 打到 1132（≈2×566，
仍不足真实人类 p50 的 0.25×），需要**学习型策略 + 载法过程价值**，不是一条规则能覆盖的。

**对「教师能否把载体率从 6–9% 提到 ≥25%」的回答**：

- 在**宽口径**（池内 11 张，含 t3 Hooktail/Mindslasher）上：**能，而且 s15 现在就有 40%**；
  教师做到 58.5%（bot 大厅）/ 25.0%（s15 分布）。
- 在**窄口径**（旧文档的 5 张 cast-on-this + Felboar，真实基线是 **3.0–3.5%**）上：
  **bot 大厅能（27.5%），s15 真实对手分布不能（6.0%）**——因为人类战团在 t8 前就结束
  游戏（教师 0/200 活到 t12），升不到 tier4–5。
- 因此「≥25%」这个门只在**宽口径 + 可生存的大厅**成立；**窄口径 + s15 分布**
  达不到，需要先把 **tier 曲线/前期强度** 做上去（这正是 s14/s15 网络本身的短板：
  t12 时 tier p50 = 3）。

---

## 4. 指标接入（质量面板 / 课程退火门）

### 4.1 三个主指标

| 指标 | 定义 | 来源 |
|---|---|---|
| `carrier_encounter_rate` | 局级：曾有一张主集合载体上场的局占比 | `scripts/carrier_audit.py` / `carrier_metrics.py` / `quality_monitor.py` |
| `casts_on_carrier_mean` | 每局「触发载体」的施法次数（打在身上 + 全局触发）；`casts_targeted_carrier_mean` 为 strict 口径 | 同上 |
| `r_carrier_turns_str12` | Pearson r(招募末在场回合数 ≤12, t12 Σ)，附 bootstrap 95%CI 与 Spearman | 同上（后期离线） |

课程退火门（`carrier_metrics.py --strict`，不达标返回 3）：

1. `carrier_encounter_rate ≥ 25%`；
2. `t12 Σ p50 ≥ 1132`（=2×566）；
3. `r_carrier_turns_str12 > 0`（点估计）。

### 4.2 每次质量面板的报告

`scripts/quality_monitor.py` 只要加 **`--carrier-audit 1`（默认）** 就会在面板 JSON 里
多写：

```json
{
  "carrier_audit": true,
  "carrier_ids": 22,
  "carrier_encounter_rate": 0.42,
  "carrier_t9_rate": 0.31,
  "carrier_t12_rate": 0.11,
  "carrier_shop_offer_rate": 0.44,
  "carrier_turns_mean": 2.0,
  "casts_on_carrier_mean": 0.6,
  "casts_on_carrier_mean_given_carrier": 1.4,
  "r_carrier_turns_str12": 0.24,
  "r_carrier_turns_str12_ci95": [-0.08, 0.49],
  "r_carrier_turns_str12_spearman": 0.19,
  "n_t12": 62,
  "str12_p50": 866.5
}
```

注意：`quality_monitor` 为了不解析引擎日志，`casts_on_carrier_mean` 用**目标选择**
口径（严格下界）；完整口径用 `carrier_audit.py` / `carrier_metrics.py`。

### 4.3 离线门（每 N 个 iteration）

```bash
# 从训练采样的 rollout 或质量面板的逐局快照算三指标 + 门
PYTHONPATH=rust/python:. python scripts/carrier_metrics.py \
    --source runs/scaling_carrier/rollouts/s15_step1001.jsonl \
    --out runs/scaling_carrier/carrier_metrics_s15_step1001.json
# 不达标返回 3（可直接接 CI / 退火脚本）
PYTHONPATH=rust/python:. python scripts/carrier_metrics.py --source ... --strict
```

### 4.4 与 `docs/SCALING_SIGNAL.md` / `CURRICULUM_SCALING.md` 的衔接

- **载体清单取代** `SCALING_SIGNAL.md` §2.3 的 5+Felboar 列表；窄口径读数（3.0–3.5%）
  替换原文 6–9%。
- **`r = +0.074`（s15 1x）→ `+0.255`（教师）** 说明：`r > 0` 这道门**可以被教师打开**，
  即使 t12 水平还低；所以退火门里应把 `r > 0 且 CI 不含 0` 与 `t12 Σ ≥ 1132` **分开**判
  （后者是棋力门，不是载体门）。
- 课程建议（`--curriculum-gold-mult 2–3` + 教师 BC + 过程价值）不变，但**载体 BC 的
  目标应扩到 11 张主集合**（尤其 t3 的 Hooktail/Mindslasher，s15 已经自然拿到 40% 宽口径），
  并且**必须同时教「升到 tier4–5」**——否则窄口径载体永远在 tier5 摸不到。

---

## 5. 局限

1. **t12 有存活选择**：教师 bot 大厅 84/200 活到 t12；s15 分布 0/200。t12 Σ 只对
   幸存者统计，会向上偏；本报告同时给了 t9 与载体回合占比。
2. **`trigger` 口径是近似**：日志不给「这次施法是不是酒馆法术」，也不给非载体随从的
   种族；`cast_on_race` 载体只统计“目标是载体自己”的情况（教师也是这么打的）。
3. **教师是规则策略**，平均名次 5.39，**不是强棋手**；t12 Σ 410 与 s14_70M 的 566 不可
   直接比“策略好坏”（对手分布、测量时点相同，但网络有 70M 样本）。
4. **窄口径样本小**：s15 只有 7 局（3.5%）有窄载体，统计噪声大。
5. **金色载体**：200 局里没有出现金色载体（三连太难），`_G` id 只做识别覆盖。
6. 旧 `runs/scaling_signal/rollouts/*.jsonl` **没有逐次施法信息**，对载体施法只能从新
   rollout 拿；旧文件只用于重算载体率与 Σ。

---

## 6. 复现

```bash
# 1) 载体清单（三重取证；确定性）
PYTHONPATH=rust/python:. python scripts/carrier_audit.py --build-catalog

# 2) s15 当前权重的 200 局（带逐次施法 / 载体追踪；CPU）
CUDA_VISIBLE_DEVICES= PYTHONPATH=rust/python:. python scripts/carrier_audit.py --run \
    --checkpoint runs/az_entity_s15/snapshots/step_001001/model.pt --device cpu \
    --games 200 --workers 8 --seed-base 900000 --tag s15_step1001 \
    --out-dir runs/scaling_carrier/rollouts

# 3) 教师 200 局（7 bot 大厅，对齐 566；与 s15 分布）
PYTHONPATH=rust/python:. python scripts/carrier_teacher.py --games 200 --workers 8 \
    --tag teacher_bot200 --bot-only --seed-base 930000 --out-dir runs/scaling_carrier/rollouts
PYTHONPATH=rust/python:. python scripts/carrier_teacher.py --games 200 --workers 8 \
    --tag teacher_s15dist --seed-base 940000 --out-dir runs/scaling_carrier/rollouts

# 4) 面板指标 / 门
PYTHONPATH=rust/python:. python scripts/carrier_metrics.py \
    --source runs/scaling_carrier/rollouts/teacher_bot200.jsonl \
    --out runs/scaling_carrier/carrier_metrics_teacher_bot200.json

# 5) 质量面板（带载体三指标）
CUDA_VISIBLE_DEVICES= PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
    --checkpoint runs/az_entity_s15/snapshots/step_001001/model.pt --device cpu \
    --games 64 --seed-base 520000 --out runs/quality/s15_carrier.json
```

产物：`data/scaling/carriers.json`、`runs/scaling_carrier/rollouts/{s15_step1001,
teacher_bot200,teacher_s15dist}.jsonl`、`runs/scaling_carrier/{audit_*,summary_*,
carrier_metrics_*}.json|md`。
