# 卡牌审计第二轮（不确定卡 → 伪代码 → 正式实现）

> 日期：2026-10-19 ｜ 权威数据：CardDefs 37.0.0.255130（`data/` 已由
> data-upgrade 复算，本轮 42 卡字段 0 差异） ｜ 引擎：`hsrl2`
> 旧录入规范：`docs/reference_old/CARD_REGISTRATION_GUIDE.md`
> **BobsBuddy 只作第三方参照，不是官方实现证据**；只有官方 CardDef 文本/
> 参数、真实 `Power.log` 事件、官方 Notes 可作为实现依据。

## 0. 结论摘要

| 项 | 数量 |
|---|---|
| 机械候选（脚本标记 ∪ 差分 gap ∪ 显式清单，去重） | **431** 个 card_id（脚本标记 295 类/170 id；diff gap 263 id；显式 20 id） |
| 本轮逐卡审计 | **18 个卡簇 / 32 个 card_id**（含普/金） |
| 确认并修复 | **4 项**：`BG35_432/_G` 缺脚本、`BG31_171/_G` 缺脚本、C'Thun awaken split、`BG32_822` Fire-forged 公式 |
| 确认一致 / 无需改 | 8 个卡簇（见 §3） |
| DEFERRED（证据不足） | 7 个卡簇 + 2 个数据/机制缺口（Activate cost、占位符） |

**重要边界**：HDT trace 的 `ScriptDataNum*` 与 Power.log 的
`TAG_SCRIPT_DATA_NUM_*` **槽位不一致**（Wrath 2↔1、Devout 2↔1、
Soul 2↔3）。本轮实现/注入一律以 CardDef 静态 NUM 或 raw Power.log
槽位为准；不把 HDT 槽位直接当官方输入。

## 1. 机械候选清单（可复现）

### 1.1 来源与数量

| 来源 | 机械结果 |
|---|---|
| 脚本 docstring 含 `DEFERRED/假设/推断/无权威/裁定依据/存疑/TODO` | 295 个类，映射 **170** 个已注册 card_id |
| `runs/diff_after_f14.json` 的 `no_script` / `dynamic_script_data` / `dynamic_stat_script` / `adapter_skip` | **263** 个 card_id |
| 显式清单（deferred_primitives、dynamic_gap_audit、Moonsteel、Geomagus、BG34_320、Minor Hymn 等） | **20** 个 card_id |
| 数据 `implemented=true` 但无测试字面覆盖（代理指标） | registry **1,458** id 中 **201** 个未在任何测试文件出现 |
| **去重并集** | **431** 个 card_id |

### 1.2 差分 TOP 卡（`runs/diff_bulk_bb_after_f15b`，第三方 BB）

| 卡 | n | mean TVD | max TVD | 本轮处置 |
|---|---|---|---|---|
| `BG36_300` / `BG36_318` / `BG36_523` / `BG36_320_G` / `BG36_106_G` | 2–4 | .766 | .984 | Deity 状态（F-15）/C'Thun split（F-16）已处理；卡脚本本体重审 |
| `BG34_694` | 4 | .493 | .809 | 文本/参数/token 一致；无官方事件证据 → 维持观察 |
| `BG35_432` | 3 | .493 | .688 | **缺脚本 → F-17 已修** |
| `BG32_835` | 6 | .403 | .809 | 文本/参数/法术脚本一致；TVD 受外部状态影响 |
| `BG34_320` | 2 | .492 | .984 | 仅 partial evidence，维持观察（不猜） |

> 机械并集完整 card_id 清单由同一脚本可重跑：
> 扫描 `hsrl2/scripts/batches/*.py` 类 docstring 标记 + 映射
> `REGISTRY`，再并入 `diff_after_f14.json` 的 gap card id；本报告 §3
> 列出优先级审计集，其余 399 个候选不进本轮修复队列。

## 2. 逐卡审计（优先级：差分 TOP / 用户可感知池内卡）

### 2.1 `BG34_694` Wintergrasp Ghoul（普 5/3，金 10/6；Deathrattle）

- **官方文本/参数**（CardDefs 255130）：`Deathrattle: Get a Tomb Turning.`
  金色 `Get 2 Tomb Turnings.`；无 ScriptDataNum。
- **伪代码**
  ```
  deathrattle(source):
      n = 2 if source.golden else 1
      for i in 1..n: GetSpellToHand(controller, TOMB_TURNING)
  ```
- **正式实现**：`WintergraspGhoulScript` / `WintergraspGhoulGoldenScript`
  （`batch_diff_driven1.py`）：`copies=1/2`，走
  `game.grant_card_copy_to_hand`（池记账 + 满手排队）。
  Token `BG34_888` 存在；测试 `test_batch_diff_driven1.py` 覆盖 1/2 张、
  未死不入手的负例。
- **证据状态**：官方文本/参数 ✅；真实 Power.log 事件 ❌；BB 差分仅参照。
- **结论**：**一致**，无需改。

### 2.2 `BG35_432` Bristleback Bully（普 3/2，金 6/4；Taunt+Deathrattle）

- **官方文本**：`Taunt. Deathrattle: Get a Blood Gem that also gives a
  Quilboar Taunt.` 金色 `Get 2 Blood Gems ...`。
- **伪代码**
  ```
  deathrattle(source):
      n = 2 if source.golden else 1
      for i in 1..n: GetSpellToHand(controller, BG20_GEM_Taunt)
  ```
  宝石本身“目标是野猪人则也给 Taunt”由既有 `BloodGemTauntScript` 负责。
- **正式实现（F-17，新增）**：`hsrl2/scripts/batches/batch_card_audit2.py`
  `BristlebackBullyScript` / `BristlebackBullyGoldenScript`；走
  `game.grant_card_copy_to_hand`；测试 `test_batch_card_audit2.py` 4 例
  （1 张 / 金色 2 张 / 未死不入 / token 注册）。
- **证据状态**：官方 CardDef 文本 + token 定义 ✅；真实 Power.log 事件 ❌
  （本轮无该卡 raw）；BB 差分方向支持但只作参照。
- **结论**：**已修复**（旧状态 REGISTRY 无 `BG35_432/_G`，亡语不触发）。
  BB 批量 TVD 未因该修复明显下降（测试集/状态不同），不把 BB 追平当目标。

### 2.3 `BG32_835` Tranquil Meditative（普 3/8，金 6/16；Spellcraft）

- **官方文本/参数**：`Spellcraft: Your Tavern spells give an extra
  +{0}/+{1} this game.` 普 NUM_1/2=1/1；金 2/2。
- **伪代码**：
  ```
  on_summon: GetSpellToHand(hero, BG32_835t or _Gt)
  spell.on_play: hero.TAVERN_SPELL_EXTRA_ATK += num(0)
                hero.TAVERN_SPELL_EXTRA_HEALTH += num(1)
  ```
- **正式实现**：`TranquilMeditativeScript` 继承 `_SpellcraftMinionBase`
  给普/金法术；`MeditationSpellScript` 写 tags 1053/1054；测试
  `test_batch_misc.py` 覆盖普/金。
- **证据状态**：官方文本/参数 ✅；真实事件 ❌；BB 差分仅参照。
- **结论**：**一致**，无需改。

### 2.4 Deity 聚类 `BG36_300 / 318 / 523 / 320_G / 106_G`

- **官方文本**（CardDefs）：
  - `BG36_300` N'raqi Frostcaller：`Activate ({2}): Discard a card for
    your Tavern spells to give an extra +{0}/+{1} this game.` 普 NUM1/2=1/1；
    金 2/2；`{2}` 无静态 NUM。
  - `BG36_318` Faceless Converter：`Deathrattle: Give your Deity
    +{0}/+{1}. (Improved by each Tavern spell you've cast this game!)`
    普 2/1，金 4/2；脚本按 `TAVERN_SPELLS_CAST_THIS_GAME` 倍率。
  - `BG36_523` Enterprising Escapee：花费金 → Lockbox/提前开；NUM0=6、
    NUM2=6、NUM3=1（金 NUM3=2）。
  - `BG36_320_G` / `BG36_106_G`：EoT 弃法术加属性 / 弃牌给自身+Deity。
- **伪代码/正式实现**：
  - `BG36_300`：`activate` 检查/弃牌后 `TAVERN_SPELL_EXTRA_ATK/HEALTH +=
    num(0/1)`（`NraqiFrostcallerScript`）；`{2}` 成本缺失见 §4A。
  - `BG36_318`：`mult=1+casts`，`game.give_deity_stats(num0*mult,
    num1*mult)`（`FacelessConverterScript`）；Deity 注入/F-15 已接。
  - `BG36_523`：`on_summon` 监听 `GOLD_SPENT`，累计阈值（`num(2)`），
    有 Lockbox 走 early-open（`num(3)`），否则 `create_spell(Lockbox)`；
    `EnterprisingEscapeeScript`。
  - `BG36_320_G` / `106_G`：EoT/弃牌监听，按 `num(0/1)` Buff 自身/Deity
    （`MysteriousKThirScript` / `CutthroatKThirScript`）。
- **证据状态**：官方文本/参数 ✅；F-07/F-15 Deity 状态机制 ✅（注入原语）；
  **C'Thun awaken split** 原 DEFERRED，本轮有 raw Power.log → F-16 修复；
  其余卡真实事件 ❌。
- **结论**：**卡脚本一致**；聚类 TVD 的剩余部分归因
  **F-16 C'Thun split（已修，待 diff-harness 复跑）** 与外部状态，
  不是这些卡脚本 bug。`BG36_300` 的 Activate cost 见 §4A（证据不足）。

### 2.5 `BG34_320` The Last One Standing（普 15/15，金 30/30；Rally）

- **官方文本**：`Rally: Give a friendly minion of each type +{0}/+{1}
  permanently.` NUM0/NUM1=15/15。
- **伪代码（官方确定部分）**：Rally 时对当前存在的每个“类型”选一个
  友方随从，各 Buff(+15/+15)，permanent。
- **正式实现**：`TheLastOneStandingScript` 遍历 10 个标准种族；候选
  `race ∈ (race, ALL)`，**排除自身**；同一 ALL 可被多个种族各选一次；
  战斗内额外 `ScheduleNextTurn` 实现 permanent。
- **证据状态**：官方文本 ✅；raw `Power.log:159706` partial：
  `TargetCount=3`，目标含两张 ALL（`BG32_111` 与自身 `BG34_320`）+
  一张 ABERRATION；两个 ALL 都拿到 +15/+15。**这证明当前“排除自身”
  与官方样本不一致，但随机/单张 ALL 重复选取仍无样本**。
- **结论**：**DEFERRED（partial evidence）**。不按单一样本改逻辑；
  等更多官方 EoT/Rally 序列（尤其 ALL 重复、无 ABERRATION 单 ALL）。

### 2.6 `BG26_HERO_102p2` Minor Hymn（英雄技能）

- **官方文本**：`Twice per turn, give a minion Health equal to your Tier.
  (Swaps to Attack next turn!)`；37.0 与 zhCN 同步；无静态 NUM。
- **伪代码**：每回合 2 次、目标友方随从、`+tier Health`；与 Major Hymn
  交替（turn 奇偶）。
- **正式实现**：`BG26_HERO_102p` 注册 `IngeScript`（按 `game.turn % 2`
  在 Attack/Health 间交替，`uses=2`）；`p2` **未注册**，测试
  `test_batch_hero_remaining2.py` 明确列为“变体/token 不注册”。
- **证据状态**：CardDef 文本/参数 ✅；无真实英雄技能日志；p2 是否实际作为
  独立 hero_power id 出现未证实。
- **结论**：**DEFERRED（无数据/日志证据）**；不新增 p2 脚本，避免双实现。

## 3. legacy C 类（证据不足 → 维持 DEFERRED）

| 卡 | 官方参数 | 当前实现 | 缺什么证据 / 结论 |
|---|---|---|---|
| `BGS_004` Wrath Weaver | NUM1/2=2/2 | `WrathWeaverScript` 读 `num(0/1)`=2/2，每次触发 +2/+2，金色两次 | raw Power.log 96451/96503 已证 **+2/+2**；现有脚本正确 → **一致**（HDT SCN2=1 不采信） |
| `BG31_035` Groundbreaker | NUM1=3（每3法术）、NUM2=1（金2） | 监听 Naga，`mult=1+casts//num0`，Buff `num1*mult` | raw Power.log 0 行；HDT SCN槽位不对齐；**DEFERRED：缺逐次 Naga/施法序列 + 官方 {2} 槽位语义** |
| `BG26_174` Soul Rewinder | NUM2=2（金4） | 受伤回退快照 + Buff health num2 | 官方 raw 创建槽位 SCN3=2/4，HDT 记 SCN2 偏移；**DEFERRED：缺 raw 逐事件槽位** |
| `BG35_701` Brazen Buccaneer | NUM0/1=2/3（金4/6） | EoT 最左 Pirate，重复 `1+本回合打出卡数` | SCN1/2=CardDef 一致；**SCN3 13–21 语义未定**（是否=打牌数/含法术）→ **DEFERRED SCN3** |
| `BG32_822` Fire-forged Evoker | NUM1/2=2/2（金4/4） | SoC 龙 Buff；F-19 按 HDT trace 关系改为 `atk=num0+2c`、`health=num1+c` | raw 0 行；但 20/20 HDT SCN 关系与 CardDef 初值一致；**已修 F-19**（测试先红：旧 `num1*(1+c)` 在 c=1 期望 +4/+2 而旧为 +4/+4） |
| `BG33_155` Devout Hellcaller | NUM0/1=2/2（金4/4） | 友方 Demon 造伤 → Buff 2/2，PERSIST 通道 | raw base 创建 + 8/8→10/10→12/12 已证 +2/+2；**金色无 raw 样本 → 金色 DEFERRED**；base **一致** |

## 4. 数据/机制缺口（与 data-upgrade 对齐）

### 4A. Activate 成本缺失（无权威证据 → 不猜）

- 官方 255130 CardDefs 中 10 条真实 Activate 卡有
  `INTERACTABLE_OBJECT(4089)=1`，但**无 `INTERACTABLE_OBJECT_COST(4090)`**；
  `data/` 保持 `activate=true, activate_cost=None`。
- 池内本体 5 张：`BG28_582/_G`、`BG36_099/_G`、`BG36_300/_G`、
  `BG36_311/_G`、`BG36_312/_G`（含金色；`BG36_300` 为差分 TOP）。
- **裁定**：**不**从文本 `Activate (N)` 解析成静态成本（占位符不是权威
  tag）；不臆造 data 值。当前引擎以 cost 判定 `is_activate_minion`，
  这些卡会被当非 Activate——这是**已知数据/引擎缺口**，不是本轮可修
  卡牌；建议 diff-harness/审计脚本单列 `activate_cost_missing` 告警，
  等官方 tag/Notes 再补。`BG36_300` 的 TOP TVD 不能据此特判。
- 本轮未改 `data/`、未改 `is_activate_minion` 判定（无官方证据）。

### 4B. 占位符无静态 ScriptDataNum

`BG31_035 {2}`、`BG35_701 {2}`、`BG36_300 {2}` 只给动态进度/费用显示，
CardDef 无静态值。**裁定**：data 不补 0；脚本按事件计数（现有实现即
如此），不把 `{2}` 当静态 NUM。`BG31_035` 的 `NUM_1=3` 与文本 `{0}`
无直接绑定，仍按 `every 3` 读 `num(0)`。

### 4C. raw 槽位映射（实现/注入警告）

| 卡 | 官方 raw | HDT trace | 采用 |
|---|---|---|---|
| Wrath Weaver | NUM1=2, NUM2=2 | 常记 SCN2=1 | 用 CardDef raw 2/2；HDT 槽位不直读 |
| Devout Hellcaller | NUM1=2, NUM2=2 | SCN2 偏移 | 用 CardDef 2/2 |
| Soul Rewinder | NUM3=2/4 | 常记 SCN2=2/4 | 用 raw NUM3；需显式 2↔3 映射 |
| Fire-forged | raw 0 样本 | SCN1/2/3 关系 | 不把 HDT 槽位当官方；维持 DEFERRED |

## 5. 本轮修复（失败测试 → 修 → 回归）

### F-16 C'Thun awaken split（`game.py::_maybe_awaken_deity`）

- 证据：`runs/powerlog_2214/Power.log:172605`（191/138→N=2 各 95/69）、
  `:174028`（33/33→N=3 各 11/11）、`:108099`（1/1→1/1）；floor、余数丢弃。
- 修复：C'Thun awaken 后对**其它**存活友方随从各加
  `floor(state.atk/N)/floor(state.health/N)`；N=0 不施加（边界 DEFERRED）。
- 测试：`hsrl2/tests/test_deity_cthun_split.py` 4 例（实际先红后绿，
  N=2/3/1/0）。
  未改 `BGFYM_011` Y'Shaarj 亡语；未改卡脚本。

### F-17 Bristleback Bully 缺脚本

- `batch_card_audit2.py` + `test_batch_card_audit2.py` 4 例；
- 只补官方文本直接给出的“亡语 Get 1/2 张 BG20_GEM_Taunt”，不动宝石
  Taunt 逻辑（既有 `BloodGemTauntScript`）。

### F-18 Moonsteel Juggernaut 缺脚本

- 证据：bridge `evidence_round2.json` HDT 配对：普通 SCN1=当前卫星、
  SCN2=+6；金色 +12（258fe/652075/0311764c）。Power.log 无 raw EoT
  序列，故只实现 trace 能直接支持的“EoT 发两张当前档，再把未来档
  +6/+12”，不读 SCN 槽位。
- `batch_card_audit3.py` + `test_batch_card_audit3.py` 3 例（普通两轮
  6→12、金色 12→24、本体属性不变、死亡停止）。
- 证据边界：SCN2 的其它 improve 来源/饰品叠加未测；不猜。

### F-19 Fire-forged Evoker 公式

- 证据：bridge `evidence_round2.json` 20/20 HDT trace 关系：
  `SCN3=本局酒馆法术数`，base `SCN1=2*SCN3+2`、`SCN2=SCN3+1`；
  golden `+4/+2` 基值。CardDef 初始 `+2/+2`（金 +4/+4）与该关系
  在 c=0 对齐；raw Power.log 仍为 0 样本，属“HDT trace 关系”级证据。
- 修复：`FireForgedEvokerScript.start_of_combat` 由旧
  `num0*(1+c)/num1*(1+c)` 改为
  `atk=num0+2c`、`health=num1+c`（普通 c=1：+4/+3；金 +6/+5）。
- 测试：`test_batch_card_audit4.py` 锁定新公式（旧 `num1*(1+c)` 在
  c=1 会给 +4，与期望 +3 不符）；`test_batch_soc.py` 旧期望同步更新。
- 证据边界：HDT 槽位与 raw 槽位不一致警告仍有效；本公式只作为
  “trace 关系 + CardDef 初值”证据，不把 BB 当官方。

### 事件级 before/after 对照（bridge 真实 trace）

| 卡 | trace | before（旧引擎/台账） | after（本轮） |
|---|---|---|---|
| Moonsteel | 258fe84214186d8a | 无脚本，EoT 不产卫星 | EoT 两张 6/6，下一档 12/12（SCN1/SCN2 关系） |
| Moonsteel 金 | 0311764c97bfa869 | 无脚本 | EoT 两张 12/12，下一档 24/24（+12） |
| C'Thun | powerlog_2214:172605 | awaken split 不施加（191/138 目标 0） | N=2 各 +95/+69（floor） |
| C'Thun | powerlog_2214:174028 | 不施加 | N=3 各 +11/+11 |
| Bristleback | 无 raw trace | REGISTRY 无脚本，亡语不给宝石 | 亡语给 1/2 张 BG20_GEM_Taunt |
| Wrath Weaver | powerlog_2240:96451 | 现有脚本已 +2/+2（raw 证据一致） | 无需改；测试锁定 |
| Devout Hellcaller base | fix3_real:26076/27762 | 现有 base +2/+2（raw 一致） | 无需改；金色仍 DEFERRED |
| Fire-forged | HDT 46 trace（无 raw） | c=1 health +4（旧 ×2） | c=1 health +3（+1/c） |

## 7. diff-harness 复跑与证据对照（2026-10-19）

diff-harness 已按 F-16 将 state23/268 从 `known_context_gap` 移出并复跑：

- **300 状态全 evaluated**：state23 TVD **.8438→.7344**（engine
  win .3125 / tie .4219 / loss .2656；BB loss 1.0；未到 loss 1.0 未强求）；
  state268 **0.0**；全 300 **agree 260/300 = 86.7%**、mean TVD **.0644**。
- **F-17** `BG35_432` 3 状态 mean TVD .4925→.4935（无显著变化；
  该卡是招募/亡语，战斗边界不触发，属预期）。
- **F-18** `BG31_171` 该 300 无出现；679 复跑中从 suspect（20 divergent）
  消失，679 总 match 400→399、div 153→144。
- **F-19** `BG32_822` 2 状态 TVD 0→0。
- 剩余 evaluated TOP：`BG34_694` .499、`BG35_432` .497、`BG32_835`
  .404、`BG36_300/318/523/320_G/106_G` .367（state23 .734 已无 known
  gap，单列观察）。
- **Activate cost**：diff-harness 报告单列 `activate_cost_gap` 7 状态
  （含 state23/268），TVD 仅参考、不进 agree 分母、不猜 cost、不改 data。
- **raw 槽位**：bulk runner 已加显式映射（HDT 来源 Wrath 1→2、
  Devout 1→2、Soul 2→3；Power raw 原样）；文档 §10.6 记录。

产物：`runs/diff_bulk_bb_after_f16_f19.{jsonl,md}`、
`runs/diff_report_after_f19b.{json,md}`；diff tests 73 passed / 1 skipped，
门禁 PASS。

## 8. 回归收尾

- `pytest hsrl2/tests -q`：**4,718 passed / 2 skipped / 14 subtests**。
- `pytest hsrl2/tests tests -q`：**5,241 passed / 5 skipped / 14 subtests
  / 0 failed**（重跑通过；此前一次 `tests/test_search_bench.py` 失败
  为顺序相关的搜索基准抖动，单跑通过，未改 policy/search 代码）。
- 审计三件套 PASS；smoke 8 局 crashes=0。


### 后续

- diff-harness 已复跑（见 §7）；F-16 known gap 已解除。
- 仍 DEFERRED 清单：`BG31_035`、`BG26_174`、`BG33_155_G`、
  `BG34_320`（partial）、`BG26_HERO_102p2`、`BG28_583`、Activate cost
  5 张池内卡、`BG35_701` SCN3。C'Thun split 已有证据并 F-16 实现，
  不再属 known gap；state23/268 的剩余 TVD 由其它 Deity/外部状态解释。
