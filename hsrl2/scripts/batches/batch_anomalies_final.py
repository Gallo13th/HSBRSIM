"""批次 anomalies_final — 异变收口批（作业单 2026-09-11）。

范围: `REGISTRY ∖ CardType.BACON_ANOMALY` 自算的全部**未注册异变**
（36.2.2 `data/bg_anomalies.json`，43 张）。逐张二态裁决（SOP §6b）:
CORRECT 5 张异变 + 1 张随载荷（第二技能槽技能），其余 36 张 DEFERRED
（撤注册 + 台账 Status/Dependency/Implementation path，见文末; 原 38 张
中的 F 组 2 张已由 `batch_anomalies3` 注册——见 F 组）。

异变脚本签名 = `on_bind(game)`（引擎 `Game.__init__` 在英雄技能接线后、
首回合开始前分发）; 每英雄监听器一律默认参数绑定 `_h=h` 防闭包晚绑定
（SOP §12 经典缺陷）; 随机一律 `game.rng`; 数值一律 `CardDef.num(i)` /
文本字面量（逐处注明出处）。

注册 6 项（注册键 = 卡 id）
═══════════════════════════════════════════════════════════════════════
  - BG27_Anomaly_307 Oops, All EVIL! — "Only evil {0} are in the Tavern."
      `num(0)` = 种族 id（XML `TAG_SCRIPT_DATA_NUM_1=92` = `Race.NAGA`，
      经 XML 反查确认: 92 = 纳迦，如 BG23_000 族）→ 酒馆种族白名单
      `game._tavern_race`（引擎 `refresh_tavern` 读取; 与 BG27_Anomaly_
      104t 族 `OnlyRaceTavernAnomaly` 同一机制）。"{0}" 在所有语言中
      都是**小兵类型名**（deDE "böse {0}" / frFR "serviteurs du M.A.L.
      {0}" / zhCN "邪恶的{0}"），"evil" 是风味词，非额外限定。
  - BG27_Anomaly_800 Little League — "Only Tavern Tiers 1, 2, 3, and 4
    exist."
      enUS 枚举 1..4 + deDE "Gasthausstufen 5 und 6 gibt es nicht."
      （= 5/6 不存在）→ `game.max_tavern_tier = 4`（引擎在
      `upgrade_tavern` 封顶、`refresh_tavern` 抽取上限、`_grant_triple_
      reward` 奖励档上限、`Discover`/`_pool_candidates` 档位上限**四处**
      读取; 与反向的 Big League `_tavern_min_tier=3` 对称）。
  - BG27_Anomaly_803 Anomalous Evidence — "At the start of each turn,
    choose from 2 new Quest Rewards. (Unlocks on Turn 4.)"
      1. 每英雄 `TURN_START` 常驻监听（owner=hero）; `turn >= 4`
         （"Unlocks on Turn 4" + XML `BACON_TURNS_TILL_ACTIVE=3` 同义）
      2. 候选 = 任务奖励实体池（与引擎 `_offer_quests` **同一口径**
         `BG24_Reward_*`）减去本人 `hero.quest_rewards` 已有项
         （"new" = 未持有; 5 张未迁移奖励见台账 B 组）
      3. `rng.sample` 取 `num` 张（文本字面量 2）→ PendingChoice
         (kind="quest_reward_choice") → resolve: `create_entity` +
         `hero.quest_rewards.append` + 接线其 `on_bind`（与
         `game.complete_quest` 同一发放路径——奖励实体的 SoC/EoT/SoT
         钩子由引擎扫描 `hero.quest_rewards` 分发）
  - BG27_Anomaly_805 Match Fixing — "Guess which player will win your
    next combat. If you're correct, get 3 Gold Coins."
      + 载荷技能 BG27_Anomaly_805t Match Fixing（Hero Power, cost=0）
      1. on_bind: 逐英雄经**数据链**解析载荷（`game.anomaly + "t"` →
         `db.get` 校验 `CardType.HERO_POWER` + REGISTRY 已注册; 解析/
         校验失败 → 整卡落空）→ `game.set_second_hero_power`（RULES
         §9.5; 第二槽已占用 → 跳过该英雄）
      2. 技能脚本 = 与 Barov `TB_BaconShop_HP_081` Friendly Wager
         **同一机制**（同名 CHOICE_NAME_DISPLAY_TYPE=1 /
         CHOICE_ACTOR_TYPE=2 tag; 二选一 "本人/对手" → COMBAT_END 判定
         严格 win）→ 直接委托已验证实现 `BarovScript.hero_power`
      3. "3 Gold Coins" = 3 张 **Tavern Coin** 卡（`BG28_810`，EN 文本
         "Gain 1 Gold."，zhCN 名"酒馆币"/正文"获得1枚铸币"）——zhCN
         805 正文"获取3张铸币**牌**"（卡片而非金币本身）+ Barov 同族
         先例（其正文即 "3 Tavern Coins"）双证
  - BG35_Anomaly_006 Anomalous Expedition — "At the start of the game,
    Discover minions from Tiers 6, 4, and 2 to get at those Tiers."
      1. on_bind: 逐英雄开局 3 个真实 Discover（tier 6/4/2，各 3 选 1
         ——池感知 + 预留语义，与 `Discover` Action 同契约）; 选中项以
         `hero._expedition_pending[tier]` 持有（副本已在选项生成时
         `minion_pool.acquire` 预留，RULES §2.3/§6.18）
      2. 到达对应酒馆等级时发放: `tavern_upgraded`(hero=, tier=) →
         `pending.pop(tier)` → `create_minion` + `pending_hand_add`
         （"get at those Tiers"——esES/jaJP/koKR 均作"到达该等级时获得"）
      3. 英雄淘汰 (`hero_eliminated`) → 释放未兑现的预留（防池泄漏）
      4. 只作用于本局所有英雄（异变全局）; 对手的 pending 互不可见

DEFERRED 台账（36 张; 逐条 Status / Dependency / Implementation path）
═══════════════════════════════════════════════════════════════════════
A. Buddy（同伴）子系统 — 8 张
   BG27_Anomaly_810 Bring in the Buddies / BG27_Anomaly_Buddies Buddies /
   BG33_Anomaly_001 Summoning Pact / BG33_Anomaly_002 Spirit of Friendship /
   BG33_Anomaly_003 Third Nature / BG33_Anomaly_005 Colorful Camaraderie /
   BG33_Anomaly_008 Partner in Crime /
   BG33_Anomaly_009 Amicable Amendment（BG33_004/006/007 不在
   `bg_anomalies.json`）
   Status: DEFERRED
   Dependency: `companion_id` 数据链齐全（109 位英雄），XML 有
     `BACON_BUDDY_ENABLED`/`BACON_BUDDY` 标记，但**按钮初始费用无任何
     数据文件**（`hsdata/CardDefs.xml` + `data/*.json` 已逐项 grep:
     无 COST / SCRIPT_DATA_NUM 项——RULES §9.4）。
   Implementation path: 生成器导出 buddy 按钮初值 tag → 引擎
     `game.press_buddy_button(hero)`（费用/每局次数/金色档）+ `hero.buddies`
     扫描域 → 本批按 `_RACE_BY_ID` 式逐个注册。

B. Bonus Keyword 定义域 — 0 张（4 张同族饰品，已在 trinkets 台账）
   记录于此以免重复派发: "Bonus Keyword" 无定义域数据字段 + 需"逐实体
   记录被授予 bonus 关键词"机制（RULES §9.6）。

C. 第二技能槽载荷未迁移 — 3 张
   BG27_Anomaly_822 Denathrius' Anima Reserves（第二技能 'Whodunit?'
     `BG24_HERO_100p`）/ BG35_Anomaly_004 Anomalous Conflux
     （'Warped Conflux' `BG34_HERO_004p`）/ BG35_Anomaly_005 Anomalous
     Timeline（'Alternate Timeline' `BG34_HERO_000p`）
   Status: DEFERRED（**槽位机制已就绪**——`set_second_hero_power`
     RULES §9.5; 阻塞在载荷本身）
   Dependency: 三张技能脚本均未注册（`REGISTRY` 无）→ 授予即空转技能
     （SOP §12 item 14）。Whodunit? 依赖 17 张任务卡的难度权威
     （RULES §11.6）; 另两张是 Timewarp 档（见 D 组）。
   Implementation path: 载荷技能迁入后本批改为 `on_bind` 授予
     （`_grant_second_power` 已就位，与 BG27_Anomaly_805 同构）。

D. Timewarp / Chronum 子系统 — 7 张
   BG34_Anomaly_800 Major Goldthorn Potion / BG34_Anomaly_800t Minor
   Goldthorn Potion / BG34_Anomaly_801 Boon of Chronum /
   BG34_Anomaly_802 Major Waygate / BG34_Anomaly_804 Twisting Hourglass /
   BG34_Anomaly_805 Oathstone's Summoning / BG34_Anomaly_809 Unforeseen
   Portal
   Status: DEFERRED
   Dependency: `data/` 无 Minor/Major Timewarp 成员集与 Chronum 账本
     （`bg_cards.json` 零 timewarp 字段）; 引擎无 Timewarp 商店/回合钩子
     （trinkets26 同缺口台账）。
   Implementation path: 生成器导出 Timewarp 成员标记 + Chronum 计数 →
     引擎 `game.visit_timewarp(hero, kind)`（T5 Minor / T8-9 Major）→
     注册 7 张。

E. Darkmoon Prize（暗月奖品）子系统 — 3 张
   BG27_Anomaly_716 Up-Prizing / BG27_Anomaly_755 A Faire Reward /
   BG27_Anomaly_Prizes2 Darkmoon Faire Prizes
   Status: DEFERRED
   Dependency: `data/` 无 prize 卡池与 tier 映射字段（无法确定
     "Tier N Darkmoon Prize" 的候选集）; 755 另需三连奖励池覆写原语
     （`_grant_triple_reward` 固定 tier+1 发现）。
   Implementation path: 导出 prize 卡池 + tier → 引擎
     `DiscoverDarkmoonPrize(hero, tier)` + `_triple_reward_override`
     → 本批注册 3 张。

F. 酒馆等级阶梯 / 三连奖励档位覆写 — 2 张（**已解冻（2026-09-20）**）
   ~~BG27_Anomaly_101 What Are the Odds?~~（只存在 T1/3/5）/
   ~~BG27_Anomaly_102 How to Even??~~（只存在 T2/4/6）
   Status: 已由 `batch_anomalies3` 注册（`WhatAreTheOddsAnomaly` /
     `HowToEvenAnomaly`）——本批 DEFERRED 台账撤出这 2 张。
   Dependency（原文，已闭环）: 引擎 `upgrade_tavern` 固定 `tier+1` 且
     `refresh_tavern` 抽取区间连续 `[min_tier, hero.tavern_tier]`——
     无"档位阶梯"覆写; `_grant_triple_reward` 固定 `min(tier+1, max)`，
     无"奖励=本人档位"覆写。
   Implementation path（已按此落地）: 引擎 `game._tavern_tier_ladder`
     （升级落点/抽取白名单/发现候选）+ `game._triple_reward_of_own_tier`
     （"Discover a minion of your Tier"）; 逐问裁定见
     `docs/ANOMALY_101_102_EVIDENCE.md`「最终裁定」节。

G. 玩家主动/跨玩家协议缺失 — 2 张（117 已解冻）
   BG27_Anomaly_580 Audience's Choice / BG27_Anomaly_723 Summoning of
   Champions
   Status: DEFERRED
   Dependency:
     - ~~117~~ **已闭环（2026-09-13）**: `MinionPool.purge(card_id)` /
       `is_purged` 已落地（`available`/`candidates`/`acquire`/`release`/
       `ensure_available` 六路全查永久移除集）→ 异变 + 载荷技能
       `BG31_Anomaly_117t` 由 `batch_anomalies7` 注册。
     - 580: "one player chooses a card for ALL players" 的候选卡池未定义
       （`num(1)=3` = 选项数，无对应卡集）+ 需跨玩家共享选择协议。
     - 723: "all players Discover a Tier 6 minion from the **same**
       choices" 需"一次抽选项、多英雄共享、各自 resolve 占池"协议
       （现 `Discover` 预留语义要求每个选项独占一份池副本; 8 英雄 × 3 选项
       超过 T6 单卡副本数）。
   Implementation path:
     - 580/723: 引擎 `game.shared_discover(heroes, candidates, kind)`
       （选项只 `acquire` 一次，各英雄 resolve 时按需追加占池/预留）。

H. 载荷（授予物）本身未迁移 — 4 张
   BG27_Anomaly_577 No Face, No Case（授予 `BG_EX1_564` Faceless
     Manipulator）/ BG31_Anomaly_102 Continuing Education（`BG31_Anomaly_
     102t` Evolving Scroll）/ BG31_Anomaly_115 Magic Shop（Spell Ticket）/
   BG35_Anomaly_001 Fly the Flag（`BG35_Anomaly_001t`）
   Status: DEFERRED
   Dependency:
     - 577: 载荷卡"Battlecry: Choose a minion and become a copy of it"无
       脚本（非池卡）; "become a copy"是否复制附魔/金色态无权威定义。
     - 102: 载荷 `BG31_Anomaly_102t` 无脚本; 手牌实体 `start_of_turn`
       分发点**已就绪**（`_begin_recruit_for` 对手牌实体统一分发;
       接线审计 spell 白名单已含 `start_of_turn`），阻塞在 "transform it
       into a random Tavern spell of a **higher** Tier" 的起点/链条
       （严格更高 vs 恰好 +1）无信源。
     - 115: "Spell Tickets are in the Tavern!" 的 Spell Ticket 卡在
       `data/` 中**不存在**（全库按名/按 dbf 检索无果）。
     - 001: 载荷法术 "Choose a minion from Tier 6 or below. Add plain
       copies of it to YOUR minion pool." 的**副本张数**无数据
       （`CardDef.num` 全空）+ 目标域（酒馆/棋盘/双方）无权威。
   Implementation path: 逐张迁移载荷卡脚本后，异变本体即可注册
     （发放路径 `pending_hand_add` / `create_spell` 均已就位）。

I. 子系统整体缺失 / 身份替换 / 基线等价 — 5 张
   BG27_Anomaly_503 The Yogg-iseum / BG27_Anomaly_562 Anomalous
     Wisdomball / BG27_Anomaly_720 Nguyen's Shifting Disks /
   BG31_Anomaly_106 Marin's Treasure Box / BG27_Anomaly_Quests
   Status: DEFERRED
   Dependency:
     - 503: "spin the SAME Wheel of Yogg-Saron" 的轮盘效果卡池/共享结果
       协议在 `data/` 与 `hsrl2/` 均不存在。
     - 562: "You occasionally get helpful Refreshes! (Unlocks on Turn
       5.)" 的触发概率无数据权威; "helpful Refresh" 类别表亦无实现
       （`BG30_802` Knockoff Wisdomball 是空转 token，无脚本；
       `BG24_Reward_313` Wondrous Wisdomball 同因 DEFERRED）。
     - 720: "All heroes are Master Nguyen." 需**英雄身份替换**
       （hero 卡 id / 技能链 / 起始护甲）——引擎无该协议。
     - 106: "All heroes are Marin the Manager. Make 'Growing Collection'
       your second Hero Power." 的前半句同样需身份替换
       （`BG30_HERO_304`）; 后半句载荷 `BG32_HERO_002p` **已注册**
       （slot 机制亦就绪）——仅剩身份替换一处阻塞，不得只做半张。
     - Quests: `BACON_QUESTS_ACTIVE=1` 是模式开关，而引擎基线**已**
       无条件启用任务（`_begin_recruit_for` 于 T4 调 `_offer_quests`）→
       注册脚本与基线不可区分（无法写出非空转断言）; 且 17 张任务卡因
       难度数值无数据权威全部 DEFERRED（RULES §11.6）。
   Implementation path:
     - 503: 导出 Wheel 效果表 + 引擎共享结果广播。
     - 562: 官方概率/类别表落档后复用同一"helpful refresh"原语。
     - 720/106: 引擎 `game.replace_hero_identity(hero, hero_card_id)`
       （含起始护甲/技能链重接）→ 106 再补
       `set_second_hero_power(hero, "BG32_HERO_002p")`。
     - Quests: 引擎把 `_offer_quests` 改为 `game._quests_enabled` 门禁，
       本异变置 True（任务卡权威落地后）。

J. 语义/数据二义或已归档 — 2 张
   BG27_Anomaly_302 Bring Home the Bacon / BG27_Anomaly_556 Valuation
   Inflation
   Status: DEFERRED（宁可 DEFERRED 也不要近似）
   Dependency:
     - 302: 载荷 `BG27_Anomaly_302t` Piggy Bank **存在**且
       `num(0)=1`（基础金币）; 阻塞在 "(Improves each turn!)" 的**步长与
       起始相位**无权威（持有当回合是否已 +1 / "two upgrading" 是否同步
       升级）——无从断言 `@` 的取值。
     - 556: "Tavern Tier 1 does not exist. Minions cost Gold equal to
       their Tier." 的两处引擎钩子均已存在（`_minion_cost_is_tier` 读点
       = 随从价=本卡 tier; `_tavern_min_tier` = T1 不出现在酒馆），但
       首句有两种读法（英雄**起始 T2**、还是起始 T1 但 T1 无随从）无权威
       （wiki 页面无 Notes，且 31.6.0 已从异变池移除，无实战观察）;
       与 `batch_anomalies` 既有 DEFERRED 裁定保持一致。
   Implementation path:
     - 302: 官方/实战确认递增口径 → 载荷脚本（手牌 `start_of_turn`
       递增 + `on_play` 取现）与异变本体同批注册。
     - 556: 权威裁定起始档位 → `_tavern_min_tier=2` +
       `_minion_cost_is_tier=True` + 起始 `TAVERN_TIER/UPGRADE_COST`
       （Big League 同构）。

K. "temporary" 手牌法术协议 — 1 张
   BG27_Anomaly_820 Deep Blue Sooner
   Status: DEFERRED
   Dependency: "At the start of your turn, get 2 temporary Deep Blues.
     They give a minion more stats each time!" 的载荷 `BG26_502t`
     "Deep Blues"（Spellcraft 家族法术）**未注册**; "temporary"（本回合
     末销毁）对手牌法术无引擎分发点（EoT 只广播棋盘/饰品/奖励实体，
     手牌实体只有 `start_of_turn`）; "Improve your future Deep Blues"
     的逐局递增计数亦无实现（`BG26_502` Deep Blue Crooner 同族）。
   Implementation path: 迁移 `BG26_502t`（含 per-game 递增计数）→ 引擎
     手牌法术到期销毁/`end_of_turn` 分发 → 本批注册（发放走
     `game.cast_spell_effect`/`grant_card_copy_to_hand` 既有入口）。

未在候选清单内的其它异变不在本作业单范围（已注册的 65 张见
batch_anomalies / _2 / _3 / _4 / _5 / _6）。
"""

from __future__ import annotations

from hsrl2.events import HERO_ELIMINATED, TURN_START, Listener
from hsrl2.game import PendingChoice
from hsrl2.tags import CardType, Race

# ── 文本/数据字面量（逐处注明出处） ────────────────────────────────

# Little League: "Only Tavern Tiers 1, 2, 3, and 4 exist."
# （enUS 枚举 1..4; deDE "Gasthausstufen 5 und 6 gibt es nicht." = 5/6 不存在）
_LITTLE_LEAGUE_MAX_TIER = 4

# Anomalous Evidence: "(Unlocks on Turn 4.)"（文本字面量; XML
# `BACON_TURNS_TILL_ACTIVE=3` 同义 = 第 4 回合起生效）
_EVIDENCE_UNLOCK_TURN = 4
# "choose from 2 new Quest Rewards"（文本字面量）
_EVIDENCE_CHOICES = 2

# Anomalous Expedition: "Discover minions from Tiers 6, 4, and 2"
_EXPEDITION_TIERS = (6, 4, 2)
# Discover 默认展示数（引擎 `Discover` Action 默认 count=3）
_EXPEDITION_CHOICES = 3

# 任务奖励实体池前缀（与引擎 `Game._offer_quests` 同一口径）
_REWARD_PREFIX = "BG24_Reward_"

# Match Fixing "3 Gold Coins" 的兑现物 = Tavern Coin（`BG28_810`
# "Gain 1 Gold."，T1 池法术，已注册）——由 `MatchFixingPower` 委托的
# `BarovScript` 发放（见模块 docstring）

CORRECT_IDS = (
    "BG27_Anomaly_307",
    "BG27_Anomaly_800",
    "BG27_Anomaly_803",
    "BG27_Anomaly_805",
    "BG27_Anomaly_805t",
    "BG35_Anomaly_006",
)

# DEFERRED（台账见模块 docstring; 撤注册不得出现在 REGISTRY）
DEFERRED_IDS = (
    "BG27_Anomaly_302",
    "BG27_Anomaly_503",
    "BG27_Anomaly_556",
    "BG27_Anomaly_562",
    "BG27_Anomaly_577",
    "BG27_Anomaly_580",
    "BG27_Anomaly_716",
    "BG27_Anomaly_720",
    "BG27_Anomaly_723",
    "BG27_Anomaly_755",
    "BG27_Anomaly_810",
    "BG27_Anomaly_820",
    "BG27_Anomaly_822",
    "BG27_Anomaly_Buddies",
    "BG27_Anomaly_Prizes2",
    "BG27_Anomaly_Quests",
    "BG31_Anomaly_102",
    "BG31_Anomaly_106",
    "BG31_Anomaly_115",
    "BG33_Anomaly_001",
    "BG33_Anomaly_002",
    "BG33_Anomaly_003",
    "BG33_Anomaly_005",
    "BG33_Anomaly_008",
    "BG33_Anomaly_009",
    "BG34_Anomaly_800",
    "BG34_Anomaly_800t",
    "BG34_Anomaly_801",
    "BG34_Anomaly_802",
    "BG34_Anomaly_804",
    "BG34_Anomaly_805",
    "BG34_Anomaly_809",
    "BG35_Anomaly_001",
    "BG35_Anomaly_004",
    "BG35_Anomaly_005",
)


# ══════════════ BG27_Anomaly_307 Oops, All EVIL! ══════════════


class OopsAllEvilAnomaly:
    """
    Natural language: Only evil {0} are in the Tavern.

    Evidence: `data/bg_anomalies.json BG27_Anomaly_307` —
    `script_data_num_1=92`（XML `TAG_SCRIPT_DATA_NUM_1=92`）;
    `hsrl2.tags.Race.NAGA == 92`，并用 XML 反查确认 92 号种族即纳迦
    （BG23_000 族等 334 张卡 `CARDRACE=92`）。"{0}" 在所有语言中都是
    **小兵类型名**（deDE "böse {0}" / frFR "serviteurs du M.A.L. {0}" /
    ruRU "приспешники ЗЛА: {0}" / zhCN "邪恶的{0}"）→ "evil" 是风味词，
    机制与 BG27_Anomaly_104t 族（"Only <race> are in the Tavern."）同构。

    Formal spec:
      1. on_bind(game): 读本局异变 CardDef 的 `num(0)`（禁止硬编码 92）
      2. `Race(int(num(0)))` 合法且非 `NONE`/`ALL` → `game._tavern_race`
         （引擎 `refresh_tavern` 的唯一读取点; 与
         `batch_anomalies.OnlyRaceTavernAnomaly` 同一机制）
      3. `num(0)` 缺失 / 非法种族 id / 退化值 → 整卡落空（不猜）
      4. 全局作用域: 异变对**全体英雄**生效（同一局共享一个酒馆池）

    Test: test_batch_anomalies_final.py — `start_game(anomaly=...)` 后
      首个自动刷新的酒馆**只含纳迦/全种族**且确有纳迦（正对照: 无异常
      同 seed 出现非纳迦）; 手动刷新后仍只有纳迦; 种族 id 非 92 的
      同族异变（BG27_Anomaly_104t7 已注册）走各自 CardDef

    Params: `num(0)` = 种族 id（92 = NAGA，数据权威）
    """

    @staticmethod
    def on_bind(game):
        d = game.db.get(game.anomaly) if game.anomaly else None
        if d is None:
            return None
        raw = d.num(0)
        if raw is None:
            return None
        try:
            race = Race(int(raw))
        except ValueError:
            return None
        if race in (Race.NONE, Race.ALL):
            return None
        game._tavern_race = race
        return None


# ══════════════ BG27_Anomaly_800 Little League ══════════════


class LittleLeagueAnomaly:
    """
    Natural language: Only Tavern Tiers 1, 2, 3, and 4 exist.

    Evidence: `data/bg_anomalies.json BG27_Anomaly_800`（无模板参数）;
    enUS 枚举 1..4，deDE "Gasthausstufen 5 und 6 gibt es nicht."
    （= 酒馆等级 5 与 6 不存在）→ 上限恰好 4（引擎标准
    `C.TAVERN_MAX_TIER=6`，需覆写）。与反向的 Big League
    （`BG27_Anomaly_100`，`game._tavern_min_tier=3`）对称。

    Formal spec:
      1. on_bind: `game.max_tavern_tier = 4`——引擎四处读取:
         `upgrade_tavern`/`upgrade_tavern_free`（`next_tier >` 则拒绝）、
         `refresh_tavern`（`max_tier = hero.tavern_tier` 永不超过上限）、
         `_grant_triple_reward`（`min(tier+1, max_tavern_tier)`）、
         `Discover`/`_pool_candidates`（未显式给 max_tier 时的档位上限）
      2. 全局作用域（全体英雄同一上限）
      3. 起始档位仍为 1（文本未说"起始 T4"，与 Big League 显式起始 T3
         不同）——升级链路 1→2→3→4 正常，4→5 被拒

    Test: test_batch_anomalies_final.py — `max_tavern_tier == 4`;
      1→2→3→4 升级成功、第 5 次升级返回 False 且金币不变（同方法内
      正/负对照: 无异常局同 setup 可升到 5）; 反复刷新的酒馆随从
      `tech_level <= 4`; 三连奖励不越档（`_grant_triple_reward` 的
      Discover 选项 tier <= 4）

    Params: 无模板参数; max tier = 4（enUS 枚举 + deDE 反证字面量）
    """

    @staticmethod
    def on_bind(game):
        game.max_tavern_tier = _LITTLE_LEAGUE_MAX_TIER
        return None


# ══════════════ BG27_Anomaly_803 Anomalous Evidence ══════════════


def _evidence_candidates(game, hero) -> list:
    """"2 **new** Quest Rewards" 的候选集。

    与引擎 `Game._offer_quests` 同一实体池口径（`BG24_Reward_*`），
    减去本人已持有（`hero.quest_rewards`）——"new" = 未持有
    （每回合选 1 张 → 候选逐回合收缩，永不重复发放）。
    """
    out = []
    for d in game.db._by_id.values():
        if not d.id.startswith(_REWARD_PREFIX):
            continue
        if any(e.card_id == d.id for e in hero.quest_rewards):
            continue
        out.append(d.id)
    return sorted(out)


def _offer_evidence_reward(game, hero) -> bool:
    """开局/回合开始: 2 选 1 任务奖励（真实 PendingChoice）。

    返回 True = 已入队。发放路径与 `game.complete_quest` 一致:
    `create_entity` → `hero.quest_rewards.append` → 接线 `on_bind`
    （奖励实体的 SoC/EoT/SoT 钩子由引擎扫描 `hero.quest_rewards` 分发）。
    """
    cands = _evidence_candidates(game, hero)
    if not cands:
        return False
    options = game.rng.sample(cands, min(_EVIDENCE_CHOICES, len(cands)),
                              label="anomalous_evidence")

    def resolve(rid):
        if rid not in options:
            return                      # 陈旧/非法选择 → 落空
        reward = game.create_entity(rid, controller=hero)
        if reward is None:
            return
        hero.quest_rewards.append(reward)
        game.run_on_bind(reward, ctx={"hero": hero})

    game.pending_choices.append(PendingChoice(
        hero, list(options), "quest_reward_choice", resolve_callback=resolve))
    return True


class AnomalousEvidenceAnomaly:
    """
    Natural language: At the start of each turn, choose from 2 new Quest
    Rewards. <i>(Unlocks on Turn 4.)</i>

    Evidence: `data/bg_anomalies.json BG27_Anomaly_803`（无模板参数）;
    XML `BACON_TURNS_TILL_ACTIVE=3` 与文本 "(Unlocks on Turn 4.)" 同义;
    载荷说明卡 `BG27_Anomaly_803t`（[DNT] spell "Trigger Anomalous
    Evidence - Choose from 2 Quest Rewards."）确认语义 = 逐回合二选一。
    "2" = 文本字面量。

    Formal spec:
      1. on_bind: 每英雄注册 `TURN_START` 常驻监听（owner=hero，
         condition/guard 锁 `hero is _h`——防闭包晚绑定 SOP §12）
      2. `turn >= 4`（解锁回合）→ `_offer_evidence_reward`
         （候选 = `BG24_Reward_*` 减去本人已持有; `rng.sample` 取 2）
      3. resolve: 入 `hero.quest_rewards` 并接线其 `on_bind`
         （`game.complete_quest` 同款路径）
      4. 每英雄独立（owner 隔离）; 候选耗尽 → 落空（不建空选择）

    Test: test_batch_anomalies_final.py — 第 3 回合无选择 / 第 4 回合
      每英雄恰 1 份 2 选 1 且选项互异、均为 `BG24_Reward_*`、均未持有;
      选中后 `quest_rewards` +1 且 `run_script_hook(..., "on_bind")`
      被调用（on_bind 活性证据）; 下回合候选不再包含已选 id（"new"）;
      对手选项独立（owner 隔离）; 同 seed 确定性

    Params: 解锁回合 = 4（文本 + XML）; choices = 2（文本字面量）
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is not _h:
                    return
                t = g.turn if turn is None else turn
                if t < _EVIDENCE_UNLOCK_TURN:
                    return
                _offer_evidence_reward(g, _h)

            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))
        return None


# ══════════════ BG27_Anomaly_805 Match Fixing ══════════════


def match_fixing_power_id(game):
    """按数据约定解析本异变的载荷技能 id（`<anomaly_id>t`）。

    数据核实: `data/bg_hero_powers.json BG27_Anomaly_805t` Match Fixing
    （card_type=10, cost=0）; 同约定在异变族通用（`BG27_Anomaly_302t`
    Piggy Bank / `BG35_Anomaly_001t` Fly the Flag / `BG31_Anomaly_102t`
    Evolving Scroll 等同名 `t` 后缀载荷）。解析结果必须**同时**满足
    CardDB 存在 + `CardType.HERO_POWER` + 脚本已注册（REGISTRY），
    否则视为载荷未就绪 → 调用方整卡落空（不授予空转按钮）。
    """
    if not game.anomaly:
        return None
    d = game.db.get(f"{game.anomaly}t")
    if d is None or d.card_type != CardType.HERO_POWER:
        return None
    from hsrl2.scripts import REGISTRY
    if d.id not in REGISTRY:
        return None
    return d.id


def _grant_second_power(game, power_id: str) -> None:
    """逐英雄授予第二技能槽（已占用 → 跳过，RULES §9.5 单槽）。"""
    for h in game.heroes:
        if getattr(h, "_second_power_id", None) is not None:
            continue
        game.set_second_hero_power(h, power_id)


class MatchFixingAnomaly:
    """
    Natural language: Guess which player will win your next combat. If
    you're correct, get 3 Gold Coins.

    Evidence: `data/bg_anomalies.json BG27_Anomaly_805`（无模板参数）;
    载荷 `BG27_Anomaly_805t`（Hero Power, cost=0, XML
    `CHOICE_NAME_DISPLAY_TYPE=1` / `CHOICE_ACTOR_TYPE=2` = 玩家二选一）
    与 Barov `TB_BaconShop_HP_081` Friendly Wager 同 tag 同机制
    （后者文本 "Guess which player will win their next combat. If you're
    correct, get 3 Tavern Coins."——已验证实现）。"3 Gold Coins" 的兑现
    物 = 3 张 Tavern Coin（`BG28_810` "Gain 1 Gold."）: zhCN 805 正文
    "获取3张铸币**牌**"（卡片）+ Barov 同族先例双证。

    Formal spec:
      1. on_bind: `match_fixing_power_id(game)` 数据约定解析; 失败
         （缺失/非 HERO_POWER/未注册）→ 整卡落空，不授予空转按钮
      2. 逐英雄 `game.set_second_hero_power(hero, power_id)`（RULES
         §9.5: 写第二槽 + 幂等接线 on_bind; 已占用 → 跳过该英雄）
      3. 技能脚本 `MatchFixingPower`（cost=0 由 CardDef 决定; 1 次/回合
         由引擎默认）: 二选一 "me"/"opponent" → 下次本人参战的
         COMBAT_END 判定严格 win → 3× Tavern Coin
      4. 全局作用域: 异变给**全体英雄**同一个 0 费按钮; 兑现只归使用者

    Test: test_batch_anomalies_final.py — 两英雄第二槽均 = 805t 且
      `hero_power_ids` 含它; `use_hero_power(..., power_id=)` 免费
      （金币不变）→ PendingChoice kinds/选项; 猜中本人胜利 → 手牌 3 张
      Tavern Coin; 猜错/平局 → 无（同方法内正/负对照）; 未使用按钮的
      对手不受影响（owner 隔离）; 无异常局同 power_id 不可用（负对照）;
      第二槽已占用 → 不覆盖

    Params: 无模板参数; coins = 3（文本字面量）
    """

    @staticmethod
    def on_bind(game):
        power_id = match_fixing_power_id(game)
        if power_id is None:
            return None
        _grant_second_power(game, power_id)
        return None


class MatchFixingPower:
    """
    Natural language: Guess which player will win your next combat.

    Evidence: `data/bg_hero_powers.json BG27_Anomaly_805t`（card_type=10,
    cost=0, 无 {0}/{1} 占位符）。与 Barov `TB_BaconShop_HP_081`
    Friendly Wager 同 tag（CHOICE_NAME_DISPLAY_TYPE=1 /
    CHOICE_ACTOR_TYPE=2）同文本机制——Barov 版已验证（
    `batch_hero_actives2.BarovScript`），本卡是**异变授予的 0 费副本**，
    故直接委托同一实现（避免第二份近似实现; 费用由 CardDef.cost 决定:
    Barov=1 / 本卡=0）。

    Formal spec:
      1. `hero_power(hero, game, ctx)`: PendingChoice(kind="friendly_wager",
         options=["me","opponent"]) → resolve 记录本局赌注 token +
         注册一次 COMBAT_END 监听（owner=hero, condition 本人参战）
      2. 结算: `result.winner is hero`（猜 me）/ `is 对手`（猜 opponent）
         → 3× Tavern Coin（`BG28_810` 池法术入手，满手排队）;
         平局/错判/未参战 → 无
      3. 再次使用会替换 token（旧赌局失能）; 引擎负责次数/费用

    Test: test_batch_anomalies_final.py — 见 `MatchFixingAnomaly`
      （本类经异变授予后走真实 `use_hero_power` 路径）

    Params: 无模板参数（费用/数值由 CardDef 与引擎决定）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        from hsrl2.scripts.batches.batch_hero_actives2 import BarovScript
        return BarovScript.hero_power(hero, game, ctx)


# ══════════════ BG35_Anomaly_006 Anomalous Expedition ══════════════


def _offer_expedition_discover(game, hero, tier: int) -> bool:
    """开局 Discover 一个恰好 `tier` 的随从并**预留**（池语义同 Discover）。

    选项在生成时即 `minion_pool.acquire`（RULES §2.3/§6.18 预留语义），
    选中项以 card_id 存入 `hero._expedition_pending[tier]` 待到达该
    酒馆等级时发放; 未选选项立即 `release` 回池。
    """
    from hsrl2.actions.discover import _pool_candidates
    cands = _pool_candidates(game, None, tier, tier)
    if not cands:
        return False
    drawn = game.rng.sample(cands, min(_EXPEDITION_CHOICES, len(cands)),
                            label="expedition_discover")
    options = [cid for cid in drawn if game.minion_pool.acquire(cid)]
    if not options:
        return False

    def resolve(picked):
        for cid in options:
            if cid != picked:
                game.minion_pool.release(cid, 1)
        if picked not in options:
            return                      # 非法/陈旧选择 → 落空（已全部回池）
        pending = getattr(hero, "_expedition_pending", None)
        if pending is None:
            pending = {}
            hero._expedition_pending = pending
        pending[tier] = picked

    # kind 以 "discover" 开头 → 引擎 `PendingChoice.choose` 正常广播
    # `card_discovered`（"After you Discover a card" 类效果）
    game.pending_choices.append(PendingChoice(
        hero, list(options), "discover_expedition", resolve_callback=resolve))
    return True


class AnomalousExpeditionAnomaly:
    """
    Natural language: At the start of the game, Discover minions from
    Tiers 6, 4, and 2 to get at those Tiers.

    Evidence: `data/bg_anomalies.json BG35_Anomaly_006`（无模板参数）;
    多语言一致: esES "esbirros de los niveles 6, 4 y 2 que obtendrás al
    llegar a esos niveles" / jaJP "グレード6、4、2のミニオンを1体ずつ発見し
    それぞれのグレード到達時にそれらを獲得する" / koKR "6, 4, 2단계
    하수인을 발견하고 그 선술집 단계에 도달하면 해당 하수인을 얻습니다"
    → 开局三选一（每档一次），到达该档时入手。档位 6/4/2 = 文本字面量。

    Formal spec:
      1. on_bind: 逐英雄初始化 `hero._expedition_pending = {}` 并对
         `(6, 4, 2)` 各开一个真实 Discover（tier 恰好 6/4/2，3 选 1，
         池感知 + 预留）
      2. 注册 `tavern_upgraded`(hero=, tier=) 常驻监听: 本人到达 tier 时
         `pending.pop(tier)` → `create_minion` + `pending_hand_add`
         （满手排队 RULES §3.3）; 非对应档位不动 pending（负对照）
      3. 注册 `hero_eliminated` 监听: 淘汰时释放未兑现预留（防池泄漏）
      4. 全局作用域（所有英雄各自三选一）; 对手 pending 互不可见

    Test: test_batch_anomalies_final.py — 开局每英雄恰 3 个
      `discover_expedition` 且选项 tier 分别全等于 6/4/2; 选中 T2 项 →
      池剩余 -1 且 `pending[2]` 记录; 升到 T2 → 该随从入手（同方法内
      负对照: T4 项此时**未**发放）; 升到 T4 → T4 项发放; 对手不受影响;
      淘汰未兑现预留释放回池; 无异常局无任何 pending 选择; 同 seed
      确定性

    Params: tiers = (6, 4, 2)（文本字面量）; choices = 3（Discover 默认）
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h._expedition_pending = {}

            def on_up(g, hero=None, tier=None, _h=h, **kw):
                if hero is not _h or tier is None:
                    return
                pending = getattr(_h, "_expedition_pending", None)
                if not pending:
                    return
                cid = pending.pop(tier, None)
                if cid is None:
                    return
                m = g.create_minion(cid, controller=_h)
                if m is not None:
                    g.pending_hand_add(_h, m)

            def on_out(g, hero=None, _h=h, **kw):
                if hero is not _h:
                    return
                pending = getattr(_h, "_expedition_pending", None)
                if not pending:
                    return
                for cid in pending.values():
                    g.minion_pool.release(cid, 1)
                pending.clear()

            game.events.register(Listener(event="tavern_upgraded", owner=h,
                                          callback=on_up))
            game.events.register(Listener(event=HERO_ELIMINATED, owner=h,
                                          callback=on_out))
            for tier in _EXPEDITION_TIERS:
                _offer_expedition_discover(game, h, tier)
        return None


_SCRIPTS = {
    "BG27_Anomaly_307": OopsAllEvilAnomaly,
    "BG27_Anomaly_800": LittleLeagueAnomaly,
    "BG27_Anomaly_803": AnomalousEvidenceAnomaly,
    "BG27_Anomaly_805": MatchFixingAnomaly,
    "BG27_Anomaly_805t": MatchFixingPower,
    "BG35_Anomaly_006": AnomalousExpeditionAnomaly,
}


def register() -> list[str]:
    """注册 5 张异变 + 1 张载荷技能（DEFERRED 38 张见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    for cid in CORRECT_IDS:
        reg(cid, _SCRIPTS[cid])
    return list(CORRECT_IDS)
