# 任务卡（Quest）实现规格 + 数值权威审计（2026-09-18 第四十九轮）

> **状态: 已落地**。19 张任务卡注册（`hsrl2/scripts/batches/batch_quests.py`），
> 1 张保持 DEFERRED（`BG24_Quest_328`），2 张公告 token 由
> `Game.quest_defs()` 显式排除。
>
> 本文档取代 2026-09-13 第二十一轮的「整族 DEFERRED」结论。旧结论的依据
> 是「进度 = 任务基础值 × 任务种族修正 × 奖励基础值 × 奖励种族修正 ×
> 护甲等级」四因子公式，而四因子表在 XML 与 wiki 均无数据源。**项目所有者
> 于 2026-09-18 直接裁定权威序**（见 §0）后，wiki 各卡页 "Patch changes"
> 段的 **"baseline requirement" 当前值** 构成权威目标值，四因子不再是
> 阻塞。

## 0. 权威序（项目所有者 2026-09-18 直接裁定）

1. **wiki 有详细说明处 → wiki 权威**（记 URL + oldid + 逐字引文）。
2. **wiki 无详细说明处 → 卡面文字的自然语言解读**（解读与其边界写进脚本
   docstring）。
3. **铁律不变**: 禁止"注册但空转"、禁止静默第三态、卡面明确处禁止简化
   实现、真实路径测试 + 变异敏感负对照 + 三段式 docstring、文档只记录
   现实（本政策本身只能作为"项目所有者裁定"记录，不得用来洗白别的近似）。

同款记录见 `docs/agents/EFFECT_SCRIPT_SOP.md`（新增小节）。

## 1. 逐卡目标值（2026-09-18 核实）

数值三源一致: **wiki 各卡页 "Patch changes" 当前值**（权威）=
**`hsdata/CardDefs.xml` tag `QUEST_PROGRESS_TOTAL`（enumID 535）** =
`data/bg_cards.json` 的 `quest_progress_total`（生成器导出，见 §4）。
hub 页 `Battlegrounds/Quest`（oldid 916067）的 "Baseline requirements for all
Quests" 列表**陈旧**（Crack the Case 15 vs 实际 9、Cry for Help 3 vs 4、
Dust for Prints 22 vs 23、Pressure 35 vs 28、Unlikely Duo "Play 5" vs
"Buy 4"）→ **不以 hub 列表为准**。

| id | 名称 | 目标值 | 卡页 URL（oldid） | 数值依据（逐字引文） |
|----|------|--------|-------------------|---------------------|
| `BG24_Quest_112` | Track the Footprints | 8 | [Track_the_Footprints](https://hearthstone.wiki.gg/wiki/Battlegrounds/Track_the_Footprints) (885653) | "Patch 27.0.3.182995 (2023-08-08): Now easier to complete. **New baseline requirement: 8** (previously: 9)." |
| `BG24_Quest_114` | Assemble a Lineup | 16 | [Assemble_a_Lineup](https://hearthstone.wiki.gg/wiki/Battlegrounds/Assemble_a_Lineup) (904752) | "**baseline requirement: 16** (previously: 17)" |
| `BG24_Quest_120` | Unmask the Culprit | 3 | [Unmask_the_Culprit](https://hearthstone.wiki.gg/wiki/Battlegrounds/Unmask_the_Culprit) (866634) | 卡页**无 baseline 行**（仅 "Added." / "Removed from the pool"）→ **自然语言解读**: "Lose or tie {0} combats" = {0} 场未获胜的战斗; 数值 3 取自 CardDefs tag 535 |
| `BG24_Quest_123` | Find the Murder Weapon | 14 | [Find_the_Murder_Weapon](https://hearthstone.wiki.gg/wiki/Battlegrounds/Find_the_Murder_Weapon) (805529) | "**baseline requirement: 14** (previously: 15)" |
| `BG24_Quest_124` | Reenact the Murder | 17 | [Reenact_the_Murder](https://hearthstone.wiki.gg/wiki/Battlegrounds/Reenact_the_Murder) (885660) | "**New baseline requirement: 17** (previously: 18)" |
| `BG24_Quest_125` | Sort It All Out | 4 | [Sort_It_All_Out](https://hearthstone.wiki.gg/wiki/Battlegrounds/Sort_It_All_Out) (891593) | 卡页**无 baseline 行、无 Notes** → **自然语言解读**: "Order your minions from lowest to highest Attack for {0} combats" = 每场战斗开始时棋盘攻击力非递减; 数值 4 取自 CardDefs tag 535 |
| `BG24_Quest_126` | Follow the Money | 27 | [Follow_the_Money](https://hearthstone.wiki.gg/wiki/Battlegrounds/Follow_the_Money) (885654) | "Patch 33.2.2.226642 (2025-08-19): Now easier to complete. **New baseline requirement: 27** (previously: 30)." |
| `BG24_Quest_151` | Unlikely Duo | 4 | [Unlikely_Duo](https://hearthstone.wiki.gg/wiki/Battlegrounds/Unlikely_Duo) (885662) | "Patch 33.4.2.228373 (2025-09-17): Now easier to complete. **New baseline requirement: 4** (previously: 5). **Now reads: " Quest: Buy {0} {2} or {3}. "** (previously: " Quest: Play {0} {2} or {3}. ")" |
| `BG24_Quest_311` | Cry for Help | 4 | [Cry_for_Help](https://hearthstone.wiki.gg/wiki/Battlegrounds/Cry_for_Help) (921080) | "Patch 33.4.2.228373 (2025-09-17): Now harder to complete. **New baseline requirement: 4** (previously: 3). Removed from the pool…" |
| `BG24_Quest_313` | Invite the Guests | 6 | [Invite_the_Guests](https://hearthstone.wiki.gg/wiki/Battlegrounds/Invite_the_Guests) (885659) | "**baseline requirement: 6** (previously: 7)" |
| `BG24_Quest_314` | Dust for Prints | 23 | [Dust_for_Prints](https://hearthstone.wiki.gg/wiki/Battlegrounds/Dust_for_Prints) (885655) | "Patch 33.4.2.228373 (2025-09-17): Now harder to complete. **New baseline requirement: 23** (previously: 22)." |
| `BG24_Quest_318` | Witness Protection | 7 | [Witness_Protection](https://hearthstone.wiki.gg/wiki/Battlegrounds/Witness_Protection) (888017) | "**New baseline requirement: 7** (previously: 8)" |
| `BG24_Quest_320` | Exhume the Bones | 6 | [Exhume_the_Bones](https://hearthstone.wiki.gg/wiki/Battlegrounds/Exhume_the_Bones) (885664) | "Patch 28.6.2.194648 (2024-02-22): Now easier to complete. **New baseline requirement: 6** (previously: 7)." |
| `BG24_Quest_328` | Close the Case | 1（数据值; 未注册） | [Close_the_Case](https://hearthstone.wiki.gg/wiki/Battlegrounds/Close_the_Case) (805512) | **DEFERRED**（§3.2）——卡数据 `quest_progress_total=1`; 阻塞 = "Win the game." 胜义无权威（**不是**缺目标值） |
| `BG24_Quest_351` | Hire an Investigator | 3 | [Hire_an_Investigator](https://hearthstone.wiki.gg/wiki/Battlegrounds/Hire_an_Investigator) (885665) | 卡页**无 baseline 行**（仅 "2024-02-16: Now harder to complete." / "Added." / "Removed"）→ **自然语言解读**: "End your turn with unspent Gold {0} times" = 每个自己的回合结束时金币 > 0 则计 1; 数值 3 取自 CardDefs tag 535 |
| `BG24_Quest_352` | Crack the Case | 9 | [Crack_the_Case](https://hearthstone.wiki.gg/wiki/Battlegrounds/Crack_the_Case) (885656) | "Patch 33.4.2.228373 (2025-09-17): Now easier to complete. **New baseline requirement: 9** (previously: 10)." |
| `BG27_Quest_800` | Burn the Evidence | 6 | [Burn_the_Evidence](https://hearthstone.wiki.gg/wiki/Battlegrounds/Burn_the_Evidence) (904024) | "Patch 27.0.3.182995 (2023-08-08): Now easier to complete. **New baseline requirement: 6** (previously: 7)." |
| `BG27_Quest_801` | Pressure the Authorities | 28 | [Pressure_the_Authorities](https://hearthstone.wiki.gg/wiki/Battlegrounds/Pressure_the_Authorities) (885658) | "Patch 33.4.2.228373 (2025-09-17): Now easier to complete. **New baseline requirement: 28** (previously: 32)." |
| `BG27_Quest_802` | Round Up the Suspects | 17 | [Round_Up_the_Suspects](https://hearthstone.wiki.gg/wiki/Battlegrounds/Round_Up_the_Suspects) (892002) | "**baseline requirement: 17** (previously: 18)" |
| `BG28_Quest_500` | Fill the Cauldron | 11 | [Fill_the_Cauldron](https://hearthstone.wiki.gg/wiki/Battlegrounds/Fill_the_Cauldron) (805528) | "**baseline requirement: 11** (previously: 12)" |

### 1.1 "baseline requirement" 的语义（旧阻塞的解除依据）

wiki 原句（hub 页 oldid 916067, Functionality 段）:

> "The requirements to complete a Quest **may change to be harder or easier to
> complete, depending on the player's hero or the strength of the Reward**."

各卡页的 "New baseline requirement: N" 是**该卡当前基线**——即四因子缩放
所围绕的基准值。项目所有者的裁定把 N 定为模拟器目标值；**已知近似**: 本
模拟器不做逐局 ±修正（该表无数据源）。此近似**记录在案**（§3.1），不再
按"简化实现"另行判罚。

### 1.2 wiki 机制说明的可得性（全族）

2026-09-18 逐页核实（渲染页 + `?action=raw`）: **21 张任务卡页无一有
`article_notes=` 参数或 Notes 段**；`Unmask the Culprit` / `Dust for Prints`
有 `article_trivia=` 但只讲原画。唯一的机制相关 patch 行是
`Pressure the Authorities` 的 "Fixed a bug where the Pressure the
Authorities Quest could sometimes be completed with less Attack than
required."。→ **所有进度判定口径都走权威序第 2 条（自然语言解读）**，
逐条记在 §2。

## 2. 逐卡条件口径（引擎生产点 → 判定）

| id | 引擎事件（生产点） | 判定 | 脚本 |
|----|-------------------|------|------|
| 112 | `tavern_refresh(hero=, auto=)`（`game.refresh_tavern`，手动/自动同点） | `hero is holder` | `TrackTheFootprintsScript` |
| 114 | `summon(minion=)`（`game.summon`） | `minion.controller is holder` | `AssembleALineupScript` |
| 120 | `combat_end(hero_a=, hero_b=, result=)`（真实配对 + 幽灵战） | 参与本场 ∧ `holder._last_combat_result ∈ {"loss","draw"}` | `UnmaskTheCulpritScript` |
| 123 | `buff_applied(target=, buff=)`（`Entity.add_buff`） | 友方 ∧ `not buff.temporary`；**一次附魔 = 1 次** | `FindTheMurderWeaponScript` |
| 124 | `death(minion=)`（`_process_death_inner`，离场前） | `minion.controller is holder` | `ReenactTheMurderScript` |
| 125 | `start_of_combat(hero=)`（`combat.py` 每英雄一次） | `hero is holder` ∧ 棋盘攻击力非递减（平局允许; <2 随从平凡成立） | `SortItAllOutScript` |
| 126 | `gold_spent(amount=, hero=)`（`game.spend_gold`） | `hero is holder`；进度 += `amount` | `FollowTheMoneyScript` |
| 151 | `minion_bought(minion=)`（`game.buy_from_tavern`） | 友方 ∧ `minion.race ∈ {MURLOC, BEAST}`（CardDef `num(0)`/`num(1)`）或 `Race.ALL` | `UnlikelyDuoScript` |
| 311 | `card_played(card=)`（随从打出；定向战吼会先返回 `PendingChoice`） | `isinstance(card, Minion)` ∧ 友方 ∧ `card.has(BATTLECRY)` | `CryForHelpScript` |
| 313 | `minion_bought(minion=)` | `minion.controller is holder` | `InviteTheGuestsScript` |
| 314 | `card_gained(hero=, card=)`（`Hero.add_to_hand` 唯一入口） | `hero is holder` | `DustForPrintsScript` |
| 318 | `after_attacked(defender=)`（`combat.py`，伤害/死亡结算后） | 友方 ∧ `defender.has(TAUNT)` | `WitnessProtectionScript` |
| 320 | `deathrattle_trigger(minion=)`（每个亡语独立广播） | `minion.controller is holder` | `ExhumeTheBonesScript` |
| 351 | `turn_end(turn=)`（`end_recruit_phase` 开头；金币尚未重置） | 存活 ∧ `holder.gold > 0` | `HireAnInvestigatorScript` |
| 352 | `after_attack(attacker=, defender=)`（战斗 + 招募期同名事件） | `attacker.controller is holder` | `CrackTheCaseScript` |
| 800 | `minion_sold(minion=)`（`game.sell_minion`） | `minion.controller is holder` | `BurnTheEvidenceScript` |
| 801 | `buff_applied` / `summon` / `card_played` → **阈值式重算** | `set_quest_progress(holder, Σ 棋盘 atk)`；达 28 完成 | `PressureTheAuthoritiesScript` |
| 802 | `minion_destroyed(hero=, minion=, …)`（`game.destroy_minion`） | `hero is holder` ∧ `minion.controller` 是**对手** | `RoundUpTheSuspectsScript` |
| 500 | `spell_resolved(spell=, …)`（手牌 + 效果施法唯一共同生产点） | `spell.controller is holder` | `FillTheCauldronScript` |

**引擎原语**（`hsrl2/game.py`）: `quest_defs()` / `quest_offer_pool()` /
`quest_script(hero)` / `quest_target(hero)` / `advance_quest_progress(hero, n)`
（唯一计数写入点）/ `set_quest_progress(hero, value)`（阈值式，只升不降）/
`complete_quest(hero)`（唯一发奖入口）。`Hero._quest_completed` 是二次计分闸;
`_offer_quests` 先暂存奖励再 `on_bind`（阈值式任务可能在 `on_bind` 当场达标）。

## 3. 边界与台账

### 3.1 已知近似（记录在案，不再另行判罚）

1. **四因子缩放未模拟**（§1.1）——目标值 = wiki baseline 当前值，无逐局
   ±修正。
2. **`BG24_Quest_123` 计数粒度** = 每次永久附魔事件 1 次（一次 `+2/+2`
   记 1，不按点数拆分）; `temporary` 附魔不计。**边界**: `copy_buffs_to`
   （副本/三连合成）与战斗快照重放也经 `add_buff` → 会一并计入。引擎当前
   无"获得属性"语义事件（`ENGINE_BACKLOG` §E 的 `stats_gained` 触发域裁定
   仍开放）; 该原语落地后本卡应迁移。（旧 `QUEST_DEFERRED_SPEC` §2.4 的
   AMBIGUOUS 条目以此收口。）
3. **`BG24_Quest_125` 排序判定** = 每场战斗 `start_of_combat` 时本人棋盘
   攻击力非递减; <2 随从平凡成立; 只按战前面板攻击力（含光环），不看手牌/
   酒馆。
4. **`BG24_Quest_151` 两族** = 卡数据 `TAG_SCRIPT_DATA_NUM_1=14 (MURLOC)` /
   `NUM_2=20 (BEAST)`（页 own tags 定值; hub 的 "random minion type" 是
   `{{2}}/{{3}}` 未渲染的显示产物）; 计数合并（文本只有一个 `{0}`）。
5. **`BG24_Quest_120`** 计幽灵战（与真实配对同一 `combat_end` 事件）。
6. **`BG27_Quest_801`** 只算棋盘（"warband"），用实时 `atk`（含光环）。
7. **每英雄单任务**: 沿用引擎既有裁定（`hero.quest` 单槽 + `_quest_offered`
   抑制）; `BG24_HERO_100p` Whodunit? 与第 4 回合 offer 的互斥接线未实现
   （该英雄技能仍 DEFERRED，理由 = 接线工作项，见 §4）。

### 3.2 DEFERRED（1 张）

- **`BG24_Quest_328` Close the Case** — 卡面 "**Quest:** Win the game."
  - **数据有目标值**: `quest_progress_total=1`（`data/bg_cards.json` 的
    `BG24_Quest_328`，2026-09-18 实测 = CardDefs tag 535）。故此前
    任何"无 baseline / 无 target"的表述**为假**——数值缺口不存在。
  - wiki 卡页（oldid 805512）只有 "Patch 24.2.0.148211: Added."——**无
    baseline 行、无 Notes**（2026-09-18 核实）。这只说明 wiki 未印出
    数值，不说明数据无值。
  - 无 `QUEST` tag（从未入池）。
  - **真正阻塞 = "Win the game" 的胜义无权威**: 第 1 名 / 前 4 名 /
    单场战斗胜利三者皆可读，自然语言解读无法消歧 → 二态铁律下保持
    DEFERRED。这是**语义权威缺口**（不是近似实现、不是"无进度脚本"、
    也不是"缺目标值"）。

### 3.3 公告 token（非任务卡本体; 不得注册）

- **`BG24_Quest_Bob`** / **`BG33_Anomaly_008_Quest`** "An Investigation!"
  （"In 3 turns, choose one of three Quests!"）: 带
  `QUEST_PROGRESS_TOTAL=3` 但**无进度条件**; 语义已由
  `Game._offer_quests`（T4 三选一）实现。注册 = "注册但空转"的第三态
  → `Game.quest_defs()` 用 `_QUEST_ANNOUNCE_TOKENS` 显式排除。

## 4. 数据链

- `tools/generate_bg_data.py` 新增导出: `TAG["QUEST"] = 2466` →
  `info["quest"]`、`TAG["QUEST_PROGRESS_TOTAL"] = 535` →
  `info["quest_progress_total"]`。
- `hsrl2/defs.py::CardDef` 新增字段 `quest: bool` /
  `quest_progress_total: Optional[int]`（`from_json` 读取）。
- **真实计数（2026-09-18 实测 `data/bg_cards.json`）**:
  - `quest=True`: **11** 张（旧注"仅 10 张当前可选"为假）。
  - `quest_progress_total` 非空: **42** 张（card_type 横跨
    SPELL(5)/BACON_QUEST_REWARD(40)/BACON_SPELL(42)/BACON_ANOMALY(43)/
    BACON_TRINKET(44)）。
  - 其中满足 `Game.quest_defs()` 三条谓词（SPELL + id 含 "quest" +
    tag 535）的: **22** 张；排除两张公告 token 后 **20** 张。
- **公告 token 的真实归属**: `BG24_Quest_Bob` / `BG33_Anomaly_008_Quest`
  实测 `card_type=SPELL`(**5**)、`quest_progress_total=3`、`quest=False`。
  它们**通过** card-type 与 tag 535 过滤，只由
  `hsrl2/game.py::_QUEST_ANNOUNCE_TOKENS` 显式排除——旧文"无此标志/由
  card-type 过滤"把排除机制写错。
- **`CardDef.quest` 标志当前不被引擎逻辑读取**（`quest_defs()` 用
  `is_quest_card` 的三条谓词，不看该标志；`hero.quest` 是另一回事——
  当前任务**实体**）。它只被 `test_batch_quests.py` 断言，保留为数据
  忠实导出；任何"用 quest 标志筛任务卡"的写法都是错的。
- 生成器幂等（改动前跑一次零 diff; 2026-09-18 实测）。
- `CardDef.quest_progress_total` 是 `Game.quest_script().target` 的**交叉
  校验源**（`test_batch_quests.py::test_every_script_target_matches_carddef`），
  **不是**运行期缩放因子。

## 5. 测试

`hsrl2/tests/test_batch_quests.py`（66 项）: 注册闸 / 池门禁 / 脚本 target
× CardDefs 交叉校验 / 19 张任务各自的**真实路径**推进与完成 / 奖励发放 /
持有者隔离与阈值负对照 / `PendingChoice` 真实发放路径 / 唯一发奖入口与
二次计分闸 / **阈值式 `set_quest_progress` 只升不降**（`TestQuest801::
test_progress_never_decreases`）。奖励载荷测试见
`hsrl2/tests/test_batch_quest_rewards8.py`（18 项，含 Zerus **自身变形**
与**不占池**负对照）。变异探针: 改 `quest_target` 阈值、去掉 `_matches`
持有者判定、把 `_amount` 改成常量 1、**去掉 `set_quest_progress` 单调闸**、
**从 Zerus 候选中去掉 `BGS_029`** 均会使对应测试失败（见 §5.1）。

### 5.1 变异结果（2026-09-18 实测，逐条 apply → 跑测试 → 还原）

| 变异 | 实测 |
|------|------|
| `Game.advance_quest_progress` 的 `if progress >= target` → `if False` | **16 failed**（全部完成类 + 二次计分闸） |
| `FollowTheMoneyScript._amount` → 常量 `1` | **1 failed**（`TestQuest126FollowTheMoney::test_gold_amount_accumulates`） |
| `TrackTheFootprintsScript._matches` → `True` | **1 failed**（`TestQuest112…test_opponent_refresh_does_not_count`） |
| `PressureTheAuthoritiesScript.target` 28 → 27 | **2 failed**（`test_every_script_target_matches_carddef` + `…test_below_threshold_not_completed`） |
| 删除 `Entity.add_buff` 的 `buff_applied` 广播 | **4 failed**（`TestQuest123` ×2 + `TestQuest801` ×2） |
| **删除 `set_quest_progress` 的 `if value <= hero._quest_progress: return False` 单调闸** | **1 failed**（`TestQuest801::test_progress_never_decreases`，实测 `AssertionError: 6 != 25`） |
| **从 `_random_minion_id` 候选中去掉 `BGS_029` 自身**（还原旧行为） | **1 failed**（`TestHandTransform::test_self_transform_is_possible`，`_force_pick` 抛 `AssertionError`） |
| 删除 `on_sot` 的"在手判定"（Zerus） | **3 failed**（棋盘/离手/常规变形） |
| 删除 `_transform_in_hand` 的 `_buffs` 转移（Zerus 保留附魔） | **1 failed**（`test_keeps_enchantments`） |
| 删除 `on_sot` 的 `hero is holder` 隔离（Zerus） | **1 failed**（`test_opponent_turn_does_not_transform`） |

全部变异均**被杀**（还原后套件恢复全绿）。`TestPendingChoiceOfferRealPath`
额外加了"resolve 后事件总线上确有任务实体拥有的监听器"断言，以满足
`audit_vacuous_tests --strict` 的类级非空转判据。

## 6. 任务奖励（4 张阻塞项）—— 2026-09-18 逐条裁定

| id | 名称 | 结论 | 依据 |
|----|------|------|------|
| `BG24_Reward_362` | Essence of Zerus | ✅ **已实现**（`batch_quest_rewards8`） | 奖励页 [Essence_of_Zerus](https://hearthstone.wiki.gg/wiki/Battlegrounds/Essence_of_Zerus) oldid=805429（`derived_relatedCardDbfIds=57742` → `BGS_029`）; [Shifter_Zerus](https://hearthstone.wiki.gg/wiki/Battlegrounds/Shifter_Zerus) oldid=891260（"Card id: `BGS_029`" / "It keeps enchantments."）; [Battlegrounds](https://hearthstone.wiki.gg/wiki/Battlegrounds) oldid=902245（"transform into any Battlegrounds minion, including Shifter Zerus. It doesn't pull from the shared pool."）; [Shifter_Zerus(构造版)](https://hearthstone.wiki.gg/wiki/Shifter_Zerus) oldid=810477（"only at the start of the possessing player's turn" / Start of Turn Phase）; [Patch 27.6.0.187190](https://hearthstone.wiki.gg/wiki/Patch_27.6.0.187190) oldid=868288（"carry over enchantments when it transforms in hand"）。**载荷 `BGS_029` 一并注册**。 |
| `BG24_Reward_135` | Yogg-tastic Tasties | ❌ **DEFERRED** | 奖励页 oldid=805475 wikitext 仅 89 字节、无 `article_notes=`；wiki **无 Wheel of Yogg-Saron 页**（`titles=` 三候选 missing、`intitle:` 全 0）；`BG24_Reward_135t` 在 wiki/hearthstonejson 均不存在；6 结果 + 5%/19% 只记在 **别的卡** 页（`Acolyte_of_Yogg-Saron` oldid=898529 / `Yogg-Tastic_Pastry` oldid=921146）且 wiki 未声明本奖励共用；该表与 `Patch 31.2.0.212197`（dbf 80436 移出游戏）+ 现行 `t7`(93390)/`t8`(93391) 冲突 → **现行结果集与概率无权威**，且 3 个结果自身欠定义（Darkmoon Prize 池 / Pyrobuff 目标口径 / "another friendly minion" 口径）。 |
| `BG24_Reward_313` | Wondrous Wisdomball | ❌ **DEFERRED** | 奖励页 [Wondrous_Wisdomball](https://hearthstone.wiki.gg/wiki/Battlegrounds/Wondrous_Wisdomball) oldid=898013 wikitext 145 字节、无 `article_notes=`；全 wiki `insource:"helpful Refresh"` **0 命中**（无机制页）；仅 `Patch 24.6.2.155409` oldid=253820 提到 "one of Wondrous Wisdomball's lucky rolls"、`Patch 33.6.2.229543` oldid=874442 提到 'Tier 7' roll 的时点限制 → **"helpful Refresh" 效果全集不存在、频率无数字**。 |
| `BG27_Anomaly_555t` | No Place Like Holmes | ❌ **DEFERRED** | token `BG27_Anomaly_555t`（dbf 106440）**在 wiki 上不存在**（`insource:"106440"`=0，方法自检 `insource:"106438"`=1）；异变本体 [No_Place_Like_Holmes](https://hearthstone.wiki.gg/wiki/Battlegrounds/No_Place_Like_Holmes) oldid=901629 无 Notes；猜谜 UI、猜错后果、"next opponent"/"last combat" 的指代、Coin 数量全缺（token 文本甚至不含 "for a Coin"）→ 无法精确实现。 |

**统计**: 任务奖励 70/73 注册（+362）; 3 张 DEFERRED（135/313/555t）。
台账同记于 `batch_hero_rewards_final.py` 文末与 `batch_quest_rewards.py`
模块 docstring，以及 `ENGINE_BACKLOG` #11（Wheel）。

## 7. 压测观察（2026-09-18；同日对抗审查重测 + 修复）

`tools/smoke_random_games.py --games 150 --seed 909090` 的输出为
**`games=150 completed=149 incomplete=1 crashes=0`**。不完整的那局是
**seed 909199, turn=50**（已逐 seed 定位）。

**订正（2026-09-18 对抗审查实测，取代旧"双方冻结"结论）**: 只有**一名**
英雄被冻结。逐项实测（修复前，`turn_cap=50`）:
- `H7`: hp=22 / armor=0、`_rewind_snapshot=(28, 0)`（被冻结）。
- `H2`: hp=16 / armor=5、`_rewind_snapshot=None`（**未冻结**——其血/甲从
  T50 到 T200 不变，且无 rewind 监听器指向它; 即伤害未被回退，只是它
  屡胜不吃伤害）。
- 事件总线上恰有 **1 个** `HERO_DAMAGE_TAKEN` 监听器，owner =
  `BG26_174` Soul Rewinder，`zone=TAVERN(3)`，且**不在任何**
  board/hand/tavern/quest_rewards/trinkets 列表内。

**根因（实测）**: 该 `BG26_174` 实体是**已离场但监听器未注销**的泄漏体。
逐事件时间线: 实体经 Dark Gift resolve 创建（`game.py` resolve →
`create_minion`）→ 被打出上板（`on_summon` 注册 `HERO_DAMAGE_TAKEN`
回退监听）→ 多次战斗死亡/复原 → 被 **Jandice `TB_BaconShop_HP_084`
"Swap, Lock, & Shop It"** 从棋盘换入酒馆（
`batch_hero_actives.py` 的 `target.zone = Zone.TAVERN`）时**没有调用
`game.events.unregister_owner(target)`** → 监听器随实体留在酒馆; 该实体
后来被酒馆刷新丢弃（不在任何列表），监听器却仍存活，每场战斗都把 H7 的
战败伤害回退到伤害前值 → H7 永不死。

**验证（实测）**:
- 手动删除那**唯一**监听器（不改其它状态）→ `seed 909199` 在
  `turn=13 finished=True`。（旧文"不是死循环、120 回合会截断"的口径
  据此更正: 监听器在，`turn_cap=200` 仍是 `turn=200 finished=False`;
  它确实不是 hang，但也不是"合法僵局"，而是**监听器泄漏导致的伪僵局**。）
- **修复（本轮，small + precedented）**: `JandiceScript.hero_power` 在
  `target.zone = Zone.TAVERN` 后补 `game.events.unregister_owner(target)`
  （与 `sell_minion` / 三连合并的既有离场注销同一口径）。修复后
  `seed 909199` → `turn=13 finished=True`;
  `--games 150 --seed 909090` → **`games=150 completed=150 incomplete=0
  crashes=0`**。
- 真实路径测试 + 变异探针:
  `test_batch_hero_actives.py::TestJandice::test_swap_unregisters_swapped_minion_listeners`
  （去掉 `unregister_owner` 该测试失败——监听器残留且英雄伤害被回退）。

**A/B 归因（保留，仍成立）**: RNG 流未被 `_offer_quests` 的候选池大小
改变; `batch_quests.register()` 返回 `[]`（任务全 no-op）时该 seed 回到
干净树的 `turn=15 finished=True`。差异**仅**来自任务奖励真的会发放
（`Rune of Transmutation`/`Cooked Book` … 改变后续对手与胜负），从而
**撞上**这条既有泄漏配置。任务代码不是缺陷来源; 泄漏是**引擎层既有**
问题（见 `ENGINE_BACKLOG` 监听器泄漏条目——离场实体的 `on_summon`
监听器未注销）。

