"""批次 trinkets15 — 饰品第十五批（作业单 2026-09-11，台账片 3/片 4）。

与 batch_trinkets1..14 的 id 集合互不相交；任务清单 = `TRINKET_LEDGER.md`
明细 #50–#69（片 3 尾部 + 片 4 头部）。全部 id 均为
`CardDB.trinket_offer_pool()` 中的**商店本体**；数值一律 `CardDef.num(i)`
（无模板参数而文本含字面量者按 SOP §3 在各类 `Params:` 行声明文本权威）；
随机一律 `game.rng`；状态写在 hero 作用域 / source 实体属性 / 监听闭包
（无 game 级 flag——SOP §12 item 9）。

本批用到的引擎原语（均为已落地公开 API）:
  - `game.trinket_related_card(trinket_id)` / `grant_trinket_related_card`
    / `grant_card_copy_to_hand(hero, def, golden=)`（RULES §7.4.6 关联卡
    协议——金色副本走 `golden=True`）
  - `GameTag.HEALTH_MINION_BUYS_THIS_TURN` / `HEALTH_BUY_RACE` /
    `HEALTH_SPELL_BUYS_THIS_TURN`（RULES §7.4.7 "以生命代金"协议）
  - `GameTag.TAVERN_SPELL_EXTRA_ATK/HEALTH` + `tavern_spell_buff` 消费点
    （batch_trinkets7 `BG32_MagicItem_700` Marvelous Mushroom 同族先例）
  - `PlayBloodGems`（actions/bloodgem.py）
  - `TAVERN_SPELL_CAST`（仅 `is_pool_spell` 法术——"Tavern spell" 语义）/
    `spell_resolving`（每次施放一次，含 Spellcraft / 手牌血宝石 /
    效果施法——"cast a spell" 语义）/ `MINION_SOLD`
  - `game.check_for_triple`（偷取随从入手后的三连检查——购买路径同口径）

注册 9 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG32_MagicItem_428  Worn Treasure Map   — 两个回合后获得 10 金
                                            （每局一次）
  BG32_MagicItem_801  Heart of the Forest — 酒馆法术额外 +num(1)/+num(2);
                                            每施放 num(0) 个酒馆法术再
                                            提升同额（滚动计数）
  BG32_MagicItem_807  Curator Sticker     — 获得金色 Mishmash +
                                            num(0)/num(0) Venomous Amalgam
                                            （Greater 饰品, school=12）
  BG32_MagicItem_808  Bloodbound Earrings — 每施放 num(1) 个法术后对所有
                                            己方随从施放 1 颗血宝石
                                            （滚动计数）
  BG32_MagicItem_817  Rendle Sticker      — 偷取馆内最高档卡牌; 每回合结束
                                            重复
  BG32_MagicItem_821  Pilgrimp Sticker    — 每回合 1 个恶魔以生命代金购买
  BG32_MagicItem_822  Bazaar Sticker      — 每回合 1 个酒馆法术以生命代金
                                            购买
  BG32_MagicItem_832  Windfall Portrait   — EoT: 获得 Windfall Tornado 并
                                            按本回合已售随从数递增
                                            +num(0)/+num(0)
  BG32_MagicItem_844  Sacrificial Altar   — 移除所有己方随从, 每移除 1 个
                                            获得 3 金

DEFERRED 11 张（**不注册**；逐张给出依赖 + 实现路径——SOP §6b 二态铁律）
════════════════════════════════════════════════════════════════════
  - BG32_MagicItem_419 Yu'lon Sticker — "**Start of Combat:** Make your
    highest-Tier Dragon Golden."
    效果本身可表达（`_goldenize` 金色化 + 最高档选取），**阻塞点是
    战斗→招募的持久化**：官方 Yu'lon 的金色化在下一招募阶段**仍然
    金色**（Blizzard 论坛 Bug Report "Persistent Poet does not keep
    Dragons golden after combat"（2025-07-12, 多玩家确认; Yeghue:
    "I just tried Yu'lon sticker with multiple minions, but none
    remained golden" 且未涉及 Poet）→ 官方预期 = 永久金色）。而引擎
    `run_combat` 的 finally 会 `hero.board = list(board_before[hero])`
    ——SoC 期间 `Transform` 出的金色实体不在战前列表中，被整体丢弃
    （实测: SoC 时 BG24_004_G/GOLDEN=True，战后复原为非金色）。
    Dependency: **战斗→招募持久化 Transform 原语**（SoC 金色化必须跨
    战斗快照保留）——例如 `GameTag.PERSIST_TRANSFORM` 白名单 + restore
    阶段对"战前实体已被 Transform"的情形保留新实体（含 GOLDEN/
    TRIPLE_BASE_CARD_ID/`GILDED_NOT_TRIPLED`）。
    实现路径（引擎补齐后）: on_bind 无需状态; `start_of_combat` 取
    本人棋盘存活、race ∈ {DRAGON, ALL}、非金色、`golden_version`
    存在的最高 `tech_level` 者（并列取最左——R508 裁定）→
    `batch_battlecry._goldenize`。被阻塞卡: 419（同族 SoC 金色化卡）。
    脚本侧替代方案（**未采用**——属近似: 依赖 COMBAT_END 二次金色化，
    与"同一实体持续金色"的官方身份语义不完全等价）: on_bind 注册
    COMBAT_END 常驻监听 + SoC 记录目标 → 战后再 `_goldenize`。
  - BG32_MagicItem_417 Tarecgosa Sticker —
    "Your left and right-most Dragons permanently keep **Bonus
    Keywords** and stats gained in combat."
    双重阻塞: (a) "Bonus Keyword" 定义域无任何数据字段（RULES §9.6
    2026-09-02 主线段裁定——与 Finley's Helmet 891 / Vibrant Bubble 892 /
    Consuming Claw BG36_MagicItem_801 同族）; (b) 引擎 PERSIST 是**单实体
    tag**（`PERSIST_COMBAT_CHANGES`，Tarecgosa / Persistent Poet），无
    "按位置（最左/最右）+ 种族持续授予"的光环原语。
    Dependency: `BONUS_KEYWORD_SET` 权威 + 逐实体 `BONUS_KEYWORDS_GRANTED`
    记录 + 位置/种族 PERSIST 光环。
    实现路径: 见 RULES §9.6 与 batch_trinkets7 DEFERRED 台账（本卡维持
    DEFERRED，无新证据）。
  - BG32_MagicItem_802 Fountain Pen —
    "Your Elementals that give stats grant an extra +2/+1."
    数据链已有 `ELEMENTAL_EXTRA_ATK(1057)`/`ELEMENTAL_EXTRA_HEALTH(1055)`
    两个 player tag，但唯一读取方 `batch_consume.elemental_buff()` 在
    全仓**零生产调用点**（`grep -rn "elemental_buff(" hsrl2/` 只命中定义
    与 docstring；Moat Custodian / Glowing Cinder 等元素 give-stats 脚本
    均未调用它）→ 写 tag 是假接线（SOP §14 item 1 / AGENTS 第二轮裁定:
    本卡曾因此撤注册）（2026-09-02 已落地）。
    Dependency: 元素 give-stats 统一出口 `elemental_buff` 接入实际元素
    脚本调用链（Moat Custodian / Sellemental / Felemental 等），或引擎在
    `Buff` 应用路径对元素来源统一叠加该 tag。
    实现路径: 读取方可达后 `on_bind` 写 `+2/+1`（本卡 num(0)/num(1) 均为
    None → 文本字面量; 金色本体 BG32_MagicItem_802t 为 +4/+2，属升级变体
    不在本批范围）。被阻塞卡: 802 + BG32_841 Sand Swirler（同 tag 家族）。
    Status: 已由 batch_trinkets24 注册（元素 give-stats 统一消费点已于 2026-09-02 落地）
  - BG32_MagicItem_803 Macaw Portrait — "Get a Monstrous Macaw. Your
    Monstrous Macaws also trigger your left-most **Battlecry**."
    关联卡 `BGS_078` Monstrous Macaw **已注册**（`batch_payload_minions`，
    Rally → 最左亡语; 金色 `TB_BaconUps_135`）; "also trigger your
    left-most Battlecry"由同一家族开关通道消费（旧台账"未注册 + 无
    读取通道"记载已过期）。
    Dependency: BGS_078（含金色）已就绪 + 共享
    `FLAG_MACAW_EXTRA_BATTLECRY` 读取点（2026-09-13 落地）。
    Status: 已迁出 → batch_trinkets36（2026-09-13，RULES §7.4.17 条件化
    战吼第二消费者）; 原阻塞（"最左战吼"资格集权威）已消除: 论坛 32.2
    复现串 `M G x B y z`（跳过非战吼 x）→ 资格集 = 带战吼者。
  - BG32_MagicItem_804 Selfless Portrait — "Get a Selfless Hero. Your
    Selfless Heroes also trigger on **Battlecry**."
    关联卡 `BG_OG_221` **已注册**（`batch_payload_minions`，亡语给随机
    友方圣盾）; "also trigger on Battlecry"需要把亡语效果接到战吼触发
    点 + 读取 hero 级标记（旧台账"未注册"记载已过期）。
    Dependency: 先迁 BG_OG_221（含金色 TB_BaconUps_014）+ 共享标记。
    Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
    条件化战吼协议）; 原阻塞: 载荷无 battlecry 附加读取点。
  - BG32_MagicItem_806 Battlecruiser Portrait — "Get an 12/12
    Battlecruiser. Whenever the Tavern is **Refreshed**, add a
    Battlecruiser Upgrade to it."
    关联卡 `BG31_HERO_801pt` **未注册**（无脚本、白板）; "Battlecruiser
    Upgrade"是独立的馆内卡子系统（升级部件累计/合并），db 中无该 token
    的数据链（`evolution_card_id` 只指向 Battlecruiser 本体），
    `inject_tavern_minion` 无法表达"馆内已有卡的升级部件追加"。
    Dependency: Battlecruiser 脚本 + Upgrade token 数据链/池定义 +
    部件追加协议。
  - BG32_MagicItem_809 Gem Donation — "The first minion you sell each turn
    plays its **Blood Gems** on the 3 highest-Tier minions in the Tavern."
    **语义未证实**: "plays its Blood Gems"的宝石**枚数/来源**无权威读法——
    (a) 按 `GEMS_PLAYED_ON` 枚数、每颗对 3 个目标各施放一次
    （3×N 颗）; (b) 共 N 颗轮转分配到 3 个目标; (c) 每目标固定 1 颗
    （共 3 颗）。三种读法在野猪人高宝石局面数值差异巨大。已查
    hearthstone.wiki.gg 卡片页（仅 refTags "Blood Gem-related /
    Tavern Tier-related / Selling-related"，无 Notes）、36.2.2 patch
    notes、中文卡库镜像，均无裁定。
    Dependency: 官方 Notes / 实测录像。裁定后可复用 `GEMS_PLAYED_ON` +
    `PlayBloodGems` + `MINION_SOLD` 监听实现（分钟级）。
  - BG32_MagicItem_820 Impulsive Portrait — "Get a 6/6 Impulsive
    Trickster. Your Impulsive Tricksters' **Deathrattles** target
    adjacent minions."
    关联卡 `BG21_006`/`BG21_006_G` **已注册**（batch_payload_minions,
    2026-09-16——原"未注册"记载陈旧）; 目标集合改写机制已有
    （RULES §7.4.16 `hero.family_flags`，Bristlebach Portrait 先例）,
    载荷侧消费点为实现工作。**唯一真阻塞 = 数额语义无权威**:
    "target adjacent minions" 相邻位 2 个时每目标各得全额 max Health
    还是均分，CardDef/XML/wiki Notes 均无裁定（SOP §6b 第 4 步）。
    "6/6" 是本体属性覆盖（`SetStats` 语义，非阻塞项）。
    Dependency: 官方/实测裁定 both-vs-split; 之后饰品交付 6/6 本体 +
    写家族开关（分钟级）。
  - BG32_MagicItem_823 Wax Imprinter — "Gain 2 Gold and take 2 damage.
    At the start of each turn, repeat this (if possible)."
    `(if possible)` 限定对象无权威读法（金币上限 / 生命不足 / 仅未阵亡），
    不同读法在多回合残血场景结果不同。batch_trinkets1 `T823` 与
    batch_trinkets7 均已按 SOP §6b 第 4 步裁定 DEFERRED；本批复核（wiki
    卡片页无 Notes、36.2.2 patch notes、中文卡库）**无新证据** → 维持
    DEFERRED。Dependency: 官方裁定或实测（非引擎缺口）。
    另注: 本卡无 Greater 升级本体（data 无 `BG32_MagicItem_823t`）。
  - BG32_MagicItem_824 Implicator Portrait — "Get 2 False Implicators.
    Your Demons always consume the highest-Health minion in the Tavern."
    关联卡 `BG29_140` **未注册**（EoT 吞噬馆内随从的效果不存在）;
    "always consume the highest-Health"是 `ConsumeRandomTavernMinion`
    的选择策略改写（当前只有 Flaming Enforcer 等脚本层自行选最高生命），
    需要引擎级选择策略覆写或 False Implicator 脚本读取 hero 标记。
    Dependency: 先迁 BG29_140（+金色 BG29_140_G）+ 吞噬目标策略协议。
  - BG32_MagicItem_830 Felemental Portrait — "Get a Felemental. Your
    Felementals give an extra +num(0)/+num(1)."
    关联卡 `BG25_041` **未注册**（战吼"给酒馆随从 +X/+Y this game"不
    存在）; "give an extra"需要 Felemental 的 TavernBuff 出口读取 hero
    级标记，且该标记需要生产消费点（同 Fountain Pen 的假接线风险）。
    Dependency: 先迁 BG25_041（+金色 BG25_041_G）+ Felemental 战吼读取
    `hero.felementary_extra_*`。

关联卡台账（RULES §7.4.6: "Get a X" 交付正确即 CORRECT；被交付卡自身的
脚本迁移状态不阻塞，但若本卡效果**依赖**其行为则整卡 DEFERRED）
══════════════════════════════════════════════════════════════════════
  已注册卡引用的被交付卡（数据链 `evolution_card_id` → `db.by_dbf`）:
  - BG32_MagicItem_807 → `TB_BaconShop_HERO_33_Buddy_G`（金色 Mishmash,
    dbf 77838，**未注册**）: 本卡只交付、不依赖其行为 → 不阻塞。
    第二张 `TB_BaconShop_HP_033t`（Venomous Amalgam, 数据链无字段;
    wiki.gg/Battlegrounds/Curator_Sticker "Related cards" 明示生成该
    token）→ 本脚本按常量创建并覆盖属性为 num(0)/num(0)。
  - BG32_MagicItem_832 → `BG31_817` Windfall Tornado（dbf 116738，
    **未注册**）: 本卡只交付 + 加 buff、不依赖其"出售时发现元素"行为
    → 不阻塞。
  其余 7 张（428/801/808/817/821/822/844）无关联卡。

接线: 本批脚本只挂 `on_bind` / `start_of_turn` / `end_of_turn` /
`start_of_combat`（饰品钩子白名单，audit_script_wiring W1）。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff, GainGold
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.events import (
    MINION_SOLD,
    TAVERN_SPELL_CAST,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

# 跨批常量（数据/文本权威，非模板参数）
# Worn Treasure Map "gain 10 Gold"（CardDef 无模板参数; XML 无数值 tag）
_WORN_MAP_GOLD = 10
# Sacrificial Altar "Gain 3 Gold for each removed"（文本字面量）
_ALTAR_GOLD_PER_MINION = 3
# Curator Sticker 第二条款的 Amalgam token: wiki.gg Battlegrounds/
# Curator_Sticker "Related cards" 明示生成 TB_BaconShop_HP_033t（全类型
# Venomous 融合体）; 该卡的属性由本饰品以 num(0) 覆盖（数据链
# BACON_EVOLUTION_CARD_ID 只指向金色 Mishmash，单关联卡协议）。
_CURATOR_AMALGAM = "TB_BaconShop_HP_033t"


def _hero(ctx):
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _card_tier(game, entity) -> int:
    """馆内实体的档位（CardDef.tech_level 权威）。

    酒馆 `Spell` 实体不携带 `tech_level` 属性（只有 CardDef 有）——
    统一按 card_id 回查 CardDef，随从/法术同口径（金色化的馆内实体
    card_id 为金卡定义，tech_level 与基础一致）。
    """
    d = game.db.get(entity.card_id)
    if d is not None:
        return d.tech_level
    return getattr(entity, "tech_level", 0) or 0


# ══════════════════ BG32_MagicItem_428 Worn Treasure Map ══════════════════


class WornTreasureMapScript:
    """
    Natural language: [x]In two turns,
    gain 10 Gold.
    <i>(Once per game.)</i>

    Formal spec:
      1. on_bind 初始化 `source._worn_map_left = num(0)`（=2）与
         `source._worn_map_done = False`——绑定发生在 T6 商店结算时，
         故首次计数从下一个招募回合开始（卡面 "{0} turns left!" 口径，
         与 batch_trinkets5 Azeroth Model Globe "start of every two turns"
         的 on_bind 计数 0 先例同构）
      2. `start_of_turn`（饰品 SoT 钩子）: 未完成时 left -= 1; left 归零
         → `GainGold(hero, 10)`（= `_WORN_MAP_GOLD`，文本字面量——
         CardDef 无模板参数 / XML 无数值 tag）并置 done=True
      3. **Once per game**: 置 done 后永不再触发（即使 left 复位也不会
         重新计数）; 一次性语义由 source 实体属性承载，随饰品实体存续
      4. 只作用于本人（source.controller）; 对手金币不变
      5. 金币 +10 走 `hero.gold` setter（含 99 上限，RULES §1.4）

    Test: test_batch_trinkets15.py — 绑定后第 1 次 SoT 不加金 / 第 num(0)
      次 SoT 恰 +10 且只加一次 / 第 3 次 SoT 不再加（once per game）/
      对手金币不变 / 绑定当回合立即 SoT（真实 end_recruit_phase 路径）
      的完整两回合曲线

    Params: gold=10（"gain 10 Gold" 文本字面量——无 {0} 占位符）
            {0}=2（num(0)，"In two turns" 的回合数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._worn_map_left = _num(game, source.card_id, 0)
        source._worn_map_done = False
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        if getattr(source, "_worn_map_done", False):
            return None
        left = getattr(source, "_worn_map_left", None)
        if left is None:
            return None
        left -= 1
        if left > 0:
            source._worn_map_left = left
            return None
        source._worn_map_left = 0
        source._worn_map_done = True
        return GainGold(h, _WORN_MAP_GOLD)


# ══════════════════ BG32_MagicItem_801 Heart of the Forest ══════════════


class HeartOfTheForestScript:
    """
    Natural language: Your Tavern spells give an extra +{1}/+{2}.
    After you cast 5 Tavern spells, improve this. <i>({0} left!)</i>

    Formal spec:
      1. on_bind: 本人 `TAVERN_SPELL_EXTRA_ATK += num(1)`、
         `TAVERN_SPELL_EXTRA_HEALTH += num(2)`——消费点 =
         `actions.racefx.tavern_spell_buff`（所有 give-stats 酒馆法术的
         统一出口，"Your Tavern spells give an extra +X" 家族;
         batch_trinkets7 BG32_MagicItem_700 同款）
      2. on_bind 注册持久监听器（owner=饰品）: `TAVERN_SPELL_CAST`
         （spell=）——引擎只对 `is_pool_spell` 法术广播（game.py），正是
         "Tavern spell" 语义; `spell.controller is 本人` owner 隔离
      3. 计数 = 闭包 dict（跨回合累积——文本无 "this turn"）; 达 num(0)=5
         → 清零并对**同额** num(1)/num(2) 再叠加一次（"improve this"
         的增量 = 基础额——同族 BG32_MagicItem_700 "At the start of each
         turn, improve this" 同样按基础 num(0)/num(1) 递增; 本卡 XML 隐藏
         参数 TAG_SCRIPT_DATA_NUM_3=1 与 num(1)/num(2) 相等佐证，但该字段
         未导出到 CardDef，故运行时以 num(1)/num(2) 为权威）
      4. **滚动**: 每次达阈值清零重来（卡面 "({0} left!)"），可持续提升;
         同一回合多次触发按次数累加
      5. 只作用于本人（hero 作用域 tag），对手施法与对手酒馆不受影响
      6. 重复副本（copy_trinket）各自注册监听 → 效果叠加（RULES §7.4.3）

    Test: test_batch_trinkets15.py — 绑定后 tag == num(1)/num(2) /
      真实 play_spell(酒馆法术) 使目标 +（基础 + 额外）/
      num(0)-1 个酒馆法术不提升 / 第 num(0) 个使 tag 再 +num(1)/num(2)
      （滚动: 再满 num(0) 个再提升）/ 对手施法不计数不加成 /
      非池法术（Spellcraft/血宝石）不计数

    Params: {0}=5 {1}=1 {2}=1（BG32_MagicItem_801 num(0/1/2)）
    """

    @staticmethod
    def _improve(hero, game, source) -> None:
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0)
                 + _num(game, source.card_id, 1))
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
                 + _num(game, source.card_id, 2))

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        HeartOfTheForestScript._improve(h, game, source)
        state = {"n": 0}

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            HeartOfTheForestScript._improve(h, g, source)

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        return None


# ══════════════════ BG32_MagicItem_807 Curator Sticker ══════════════════


class CuratorStickerScript:
    """
    Natural language: Get a Golden Mishmash and a {0}/{0} Amalgam with
    <b>Venomous</b>.

    Formal spec:
      1. 第一条款（数据链）: `game.trinket_related_card(本饰品 id)` →
         `evolution_card_id`(77838) → `db.by_dbf` → 金色 Mishmash
         `TB_BaconShop_HERO_33_Buddy_G`（零硬编码卡 id）。**金色实体**经
         `game.grant_card_copy_to_hand(hero, 金色 def, golden=True)` 交付
         ——统一入口（`create_minion(base, golden=True)` + `GOLDEN`/
         `TRIPLE_BASE_CARD_ID` + `GILDED_NOT_TRIPLED` 1 份回池口径 +
         满手排队；RULES §7.4.6）
      2. 第二条款（wiki 数据链缺失）: 常量 `_CURATOR_AMALGAM` =
         `TB_BaconShop_HP_033t`（wiki.gg Battlegrounds/Curator_Sticker
         "Related cards" 明示生成物; 全类型 + Venomous 关键词来自
         CardDef）→ `create_minion` 后覆盖 BASE_ATK/BASE_HEALTH/HEALTH =
         num(0)=10（"a {0}/{0} Amalgam"——覆盖式设属性，Beetle/SetStats
         先例）→ `pending_hand_add`
      3. **池记账**: 两张均为 token（`is_pool_minion=False`，36.2.2 数据
         核实）→ 零池操作（RULES §7.4.6）
      4. 只进本人手牌; 满手时两张各自排队等待（RULES §7.4.2 饰品生成卡
         等待条款）
      5. 两条中任一条无法解析（`trinket_related_card` 返回 None）→ 该条
         落空，另一条照常交付（不整卡静默）

    Test: test_batch_trinkets15.py — 绑定后手牌恰多 2 张: 金色 Mishmash
      （GOLDEN tag + TRIPLE_BASE_CARD_ID=基础 id + 属性 = 金色 CardDef）与
      10/10 Venomous 全类型 Amalgam（属性 == num(0)/num(0) + VENOMOUS
      tag）/ 随从池剩余不变量不变（token 不占池）/ 对手手牌不变 /
      满手时两张都排队（pending_hand_add 路径）/ evolution 数据链解析
      == 77838

    Params: {0}=10（BG32_MagicItem_807 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # ── 第一条: 金色 Mishmash（数据链 + 金色实体，统一入口） ──
        gd = game.trinket_related_card(source.card_id)
        if gd is not None:
            game.grant_card_copy_to_hand(h, gd, golden=True)
        # ── 第二条: num(0)/num(0) Venomous Amalgam（wiki 明示 token） ──
        size = _num(game, source.card_id, 0)
        am = game.create_minion(_CURATOR_AMALGAM, controller=h)
        if am is not None:
            am.set(GameTag.BASE_ATK, size)
            am.set(GameTag.BASE_HEALTH, size)
            am.set(GameTag.HEALTH, size)
            game.pending_hand_add(h, am)
        return None


# ══════════════════ BG32_MagicItem_808 Bloodbound Earrings ══════════════


class BloodboundEarringsScript:
    """
    Natural language: [x]After you cast {1} spells,
    this plays a <b>Blood Gem</b> on
    all your minions.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `spell_resolving`
         （spell=, target=, cast_no=）——引擎在**每次施放**时 fire
         （`_finish_play_spell` 的 cast 循环内 + 效果施法入口
         `cast_spell_effect`），条件 `spell.controller is 本人`。
         文本 "spells"（非 "Tavern spells"）→ 全法术域: 酒馆法术 /
         Spellcraft / 手牌血宝石 / 效果施法。**必须按 cast 计**（旧实现
         用 `card_played`，它在双施时每次打出只广播一次 → 双施的第二次
         漏计; 实测 2 个双施 = 4 次施放时 `GEMS_PLAYED_ON=0`，应 1）。
         `PlayBloodGems` 直施路径不广播 `spell_resolving`——"plays N
         Blood Gems" 不是 "cast"，天然不计数。同族在别批用 `card_played`
         阈值计数者（batch_trinkets8 `BG32_MagicItem_930` /
         `BG28_633 Felboar`）建议主线统一裁决。
      2. 计数 = 闭包 dict（跨回合累积——文本无 "this turn"）; 达
         num(1)=4 → 清零并对**全部己方存活随从**各执行
         `PlayBloodGems(m, count=1)`（vanilla 宝石; 数值 =
         BG20_GEM.num(0/1) + hero 的 BLOOD_GEM_BONUS_* tags——action 内
         权威读取; `GEMS_PLAYED_ON` 记账 + `blood_gem_played` 广播由
         action 统一处理）
      3. **滚动**: 达阈值清零重来（卡面 "({0} left!)"）; 无色/无随从时
         仍清零（触发已发生，落空不退回计数）
      4. 金色/升级本体 `BG32_MagicItem_808t`（"plays **two** Blood Gems"，
         num(1)=5）不在本批范围（升级变体不入商店池）
      5. 只作用于本人（对手施法不计数、对手随从不得宝石）

    Test: test_batch_trinkets15.py — 真实 play_spell 酒馆法术: 前
      num(1)-1 个不给宝石 / 第 num(1) 个使全部己方随从各 +1/+1 且
      GEMS_PLAYED_ON=1（对照无饰品不变）/ 再满 num(1) 个再次触发（滚动）/
      Spellcraft 法术也计数（真实 play_spell 带 SPELLCRAFT tag 的法术）/
      **双施按 cast 计**（SPELL_DOUBLER 在场: 2 次打出 × 双施 = 4 次
      施放 → 1 颗宝石; 旧 card_played 实现为 0——该断言即证伪旧实现）/
      PlayBloodGems 直施不计数 / 对手施法不计数 / 无随从时落空不报错 /
      计数 == CardDef.num(1)

    Params: {0}=4 {1}=4（BG32_MagicItem_808 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 1)
        state = {"n": 0}

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            if not isinstance(spell, Spell):
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            targets = _living(h)
            if not targets:
                return
            g.run_actions([PlayBloodGems(m, count=1, source=source)
                           for m in targets])

        game.events.register(Listener(event="spell_resolving", owner=source,
                                      callback=on_cast))
        return None


# ══════════════════ BG32_MagicItem_817 Rendle Sticker ══════════════════


class RendleStickerScript:
    """
    Natural language: [x]Steal the highest-Tier
    card from the Tavern.
    At the end of each turn,
    repeat this.

    Formal spec:
      1. `_steal`: 候选 = `hero.tavern` 全部实体（**随从与酒馆法术**——
         文本 "card" 无 minion 限定）; 目标 = 档位最高者（档位一律按
         `_card_tier` 回查 CardDef.tech_level——酒馆 `Spell` 实体不携带
         `tech_level` 属性）, 并列取**最靠左**（酒馆展示顺序——
         batch_quest_rewards R508 / batch_trinkets13 Burgling Claw
         "highest-Tier" 同裁定）
      2. "Steal"（wiki.gg custom_mechanicTags "Put into hand"）= 免费移出
         展示区进手牌: `hero.tavern.remove` → `hero.add_to_hand`
         （zone=HAND + `on_enter_hand` 钩子; 不走金币/生命支付）; 随从入手
         后照常 `check_for_triple`（与购买路径同口径——偷到手即可凑三连）。
         **池记账**: 该实体在 `refresh_tavern` 抽取时已 acquire，移入手牌
         后不再回池（与购买同口径; 未来出售时按基础卡回池 1 份）
      3. 触发: on_bind 立即偷 1 张; `end_of_turn`（饰品 EoT 钩子）每回合
         结束重复 1 张（文本 "At the end of each turn"）
      4. 满手 / 空馆 → 该次落空（不偷、不报错; 满手时馆内卡不被动）
      5. 只作用于本人酒馆（对手的馆不被偷）

    Test: test_batch_trinkets15.py — 绑定后手牌恰多 1 张 == 馆内最高档卡
      （低档对照不入）/ 馆内该卡消失且随从池不变量不变（不重复占池）/
      真实 end_recruit_phase 推进一回合后再偷 1 张（EoT 重复）/
      同档并列取最左 / 空馆落空 / 满手落空且馆内卡保留 / 对手馆不变 /
      馆内法术也可被偷（tech_level 比较）

    Params: 无模板参数（"highest-Tier" 为运行时聚合）
    """

    @staticmethod
    def _steal(game, h) -> bool:
        if not h.tavern or h.hand_full():
            return False
        best = max(h.tavern, key=lambda e: _card_tier(game, e))
        h.tavern.remove(best)
        if not h.add_to_hand(best):
            return False
        if isinstance(best, Minion):
            game.check_for_triple(h, best)
        return True

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        RendleStickerScript._steal(game, h)
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        RendleStickerScript._steal(game, h)
        return None


# ══════════════════ BG32_MagicItem_821 Pilgrimp Sticker ══════════════


class PilgrimpStickerScript:
    """
    Natural language: [x]One Demon each turn
    costs Health instead of
    Gold to buy. <i>({0} left!)</i>

    Formal spec:
      1. on_bind / start_of_turn: `hero.set(HEALTH_MINION_BUYS_THIS_TURN,
         num(0))`（num(0)=1）+ `hero.set(HEALTH_BUY_RACE, Race.DEMON)`——
         RULES §7.4.7 英雄级本回合配额（引擎在 `buy_from_tavern` 统一
         判定; 全种族随从视为匹配 Demon，RULES §8）
      2. 配额**只在成交时消费**（生命/护甲不足则购买失败且不消费——
         引擎 `buy_from_tavern` 保证）; 免费购买（cost=0）不消费
      3. **每回合重置**: on_bind（绑定当回合可用）+ 每个 SoT 重置为
         num(0)（引擎不自行重置，脚本负责——RULES §7.4.4/§7.4.7 口径）
      4. 只作用于本人（hero 作用域 tag），对手购买不受影响
      5. 支付语义: 以该恶魔的**金币价**支付等量生命（护甲先扣; 强制替换
         不提供金币选项——与 Hasty Excavation 同口径）

    Test: test_batch_trinkets15.py — 绑定后配额 tag == num(0)、race tag ==
      DEMON / 买入恶魔扣 3 生命(价 = COST)不加 0 金、配额归零 / 第二次买
      恶魔回到金币路径（配额已用尽）/ 跨回合真实 end_recruit_phase 后配额
      重置 / 买非恶魔走金币且不消费配额 / 对手买恶魔不受影响 /
      生命不足以支付时购买失败且配额保留

    Params: {0}=1（BG32_MagicItem_821 num(0)）
    """

    @staticmethod
    def _arm(hero, game, source) -> None:
        hero.set(GameTag.HEALTH_MINION_BUYS_THIS_TURN,
                 _num(game, source.card_id, 0))
        hero.set(GameTag.HEALTH_BUY_RACE, Race.DEMON)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        PilgrimpStickerScript._arm(h, game, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        PilgrimpStickerScript._arm(h, game, source)
        return None


# ══════════════════ BG32_MagicItem_822 Bazaar Sticker ══════════════


class BazaarStickerScript:
    """
    Natural language: [x]One Tavern spell each turn
    costs Health instead of
    Gold to buy. <i>({0} left!)</i>

    Formal spec:
      1. on_bind / start_of_turn: `hero.set(HEALTH_SPELL_BUYS_THIS_TURN,
         num(0))`（num(0)=1）——RULES §7.4.7 英雄级本回合配额（引擎在
         `buy_from_tavern` 对 `isinstance(entity, Spell)` 判定）
      2. 配额只在成交时消费（同 Pilgrimp Sticker / 引擎保证）
      3. 每回合重置: on_bind + 每个 SoT 写 num(0)
      4. 只作用于本人; 支付 = 该法术金币价等量生命（护甲先扣; 生命
         不足则失败且不消费配额）

    Test: test_batch_trinkets15.py — 绑定后配额 tag == num(0) / 买酒馆法术
      扣生命（= 法术 COST）且配额归零 / 第二个法术回到金币路径 /
      跨回合重置 / 买随从不消费法术配额（正对照: 法术配额仍在）/
      对手买法术走金币 / 生命不足时失败且配额保留

    Params: {0}=1（BG32_MagicItem_822 num(0)）
    """

    @staticmethod
    def _arm(hero, game, source) -> None:
        hero.set(GameTag.HEALTH_SPELL_BUYS_THIS_TURN,
                 _num(game, source.card_id, 0))

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        BazaarStickerScript._arm(h, game, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        BazaarStickerScript._arm(h, game, source)
        return None


# ══════════════════ BG32_MagicItem_832 Windfall Portrait ══════════════


class WindfallPortraitScript:
    """
    Natural language: [x]At the end of each turn, get a
    Windfall Tornado and give it
    +{0}/{0}. <i>(Improved by each
    minion you've sold this turn!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `MINION_SOLD`（minion=）——
         `sell_minion` 在移出棋盘**前**广播，`minion.controller` 可用;
         条件 `minion.controller is 本人`
      2. 计数按 `game.turn` 惰性归零（`state = {"turn": None, "n": 0}`）
         ——"minion you've sold **this turn**"（引擎无现成的 per-turn
         售出计数 tag，Sinstone Sticker 同款 turn 键闭包）
      3. `end_of_turn`（饰品 EoT 钩子）: 关联卡 = `game.trinket_related_card
         (本饰品 id)`（`evolution_card_id`(116738) → `db.by_dbf` →
         `BG31_817` Windfall Tornado，零硬编码卡 id）; 该卡
         `is_pool_minion=False`（token，36.2.2 数据核实）→ 零池操作
      4. 交付 = `create_minion` + 覆盖 buff 后 `pending_hand_add`
         （满手排队 RULES §3.3）; 增益额度 = num(0) × (1 + 本回合已售
         随从数)——文本 "give it +{0}/{0}. (Improved by each minion
         you've sold this turn!)" = 基础 num(0)/num(0) 加每售 1 个再
         num(0)/num(0)（num(0)=1; 升级本体 BG32_MagicItem_832t num(0)=2）
      5. 计数跨 EoT 归属: 每回合结束结算后该回合的计数在下个回合首次
         事件/EoT 读到时自动归零（turn 键），不会跨回合累积
      6. 只进本人手牌; 对手售出/对手 EoT 不影响本人计数
      7. **已知口径缺口（AMBIGUOUS，待引擎读取点）**: 计数闭包从
         `on_bind` 起算 → **同回合在购买本饰品之前**的出售不计
         （文本 "each minion you've sold **this turn**" 应为全回合）。
         引擎当前**无** hero 级"本回合已售随从数" tag/字段（`grep`
         `MINIONS_SOLD` / `COUNTER_*SOLD` / `*_SOLD_THIS_TURN` 全仓
         无命中; `minion_sold` 事件只在售出当下广播、无历史查询点），
         故无法在 on_bind 精确回填（SOP §6b: 不采用近似）。
         Dependency（引擎侧）: `sell_minion` 成交后
         `hero.set(GameTag.MINIONS_SOLD_THIS_TURN, n+1)` 且每回合
         `Hero.clear` 归零 → 脚本 `on_bind` 读该 tag 即得全回合精确值。

    Test: test_batch_trinkets15.py — 绑定后真实 EoT: 入手 1 只 BG31_817
      且属性 == 基础 + num(0)/num(0)（本回合未售）/ 本回合真实
      sell_minion 2 次后 EoT 属性 == 基础 + 3×num(0)/3×num(0) /
      下回合售 0 次时恢复基础档（turn 归零）/ 对手售出不计数（正对照:
      本人售出计数）/ 随从池不变量不变（token 不占池）/ 对手手牌不变 /
      关联卡数据链解析 == BG31_817

    Params: {0}=1（BG32_MagicItem_832 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        state = {"turn": None, "n": 0}

        def on_sold(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if state["turn"] != g.turn:
                state["turn"] = g.turn
                state["n"] = 0
            state["n"] += 1

        game.events.register(Listener(event=MINION_SOLD, owner=source,
                                      callback=on_sold))

        def sold_this_turn(g) -> int:
            if state["turn"] != g.turn:
                return 0
            return state["n"]

        source._windfall_sold = sold_this_turn
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        d = game.trinket_related_card(source.card_id)
        if d is None:
            return None
        counter = getattr(source, "_windfall_sold", None)
        sold = counter(game) if counter is not None else 0
        per = _num(game, source.card_id, 0)
        total = per * (1 + sold)
        m = game.create_minion(d.id, controller=h)
        if m is None:
            return None
        if total:
            game.run_actions(Buff(m, atk=total, health=total))
        game.pending_hand_add(h, m)
        return None


# ══════════════════ BG32_MagicItem_844 Sacrificial Altar ══════════════


class SacrificialAltarScript:
    """
    Natural language: Remove all your minions. Gain 3 Gold for each
    removed.

    Formal spec:
      1. on_bind（购买/授予即结算）: 快照 `list(hero.board)`, 逐个
         `hero.board.remove` + `zone = Zone.REMOVED` +
         `events.unregister_owner`（注销监听器）——"Remove"（wiki
         mechanicsTags "Remove from game"）**非 Destroy**:
         不触发死亡/亡语/Avenge、不进 graveyard; **不回池**
         （Hooktusk `Remove from game` 先例 + SOP §4.12 "友方不回池"）
      2. 移除完毕后 `_update_positions` 重排 ZONE_POSITION
      3. `GainGold(hero, 3 × 移除数)`——3 = 文本字面量
         `_ALTAR_GOLD_PER_MINION`（CardDef 无模板参数 / XML 无数值 tag）
      4. 空板 → 移除 0 个、不加金（落空不报错）
      5. 只作用于本人棋盘（对手随从不变）; 不含手牌（"your minions" =
         战场）
      6. 金色随从同样被移除（不返还 3 份——非出售）; 移除后其磁力栈实体
         随宿主一并离场（引擎 `_magnetic_stack` 语义与 Hooktusk 同）

    Test: test_batch_trinkets15.py — 绑定后棋盘清空、每个被移除者
      zone=Zone.REMOVED 且金币恰 +3×数量 / 亡语不触发（带亡语的池随从
      不移入 graveyard、不产生 token）/ Avenge 计数不增加 / 随从池副本数
      不变（不回池，与 sell_minion 对照）/ 空板绑定不加金不崩 /
      对手棋盘不变

    Params: gold_per_minion=3（"Gain 3 Gold for each removed" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        removed = list(h.board)
        for m in removed:
            h.board.remove(m)
            m.zone = Zone.REMOVED
            game.events.unregister_owner(m)
        if removed:
            game._update_positions(h)
        if not removed:
            return None
        return GainGold(h, _ALTAR_GOLD_PER_MINION * len(removed))


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    """注册饰品第十五批 9 张（DEFERRED 台账见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_MagicItem_428", WornTreasureMapScript),
        ("BG32_MagicItem_801", HeartOfTheForestScript),
        ("BG32_MagicItem_807", CuratorStickerScript),
        ("BG32_MagicItem_808", BloodboundEarringsScript),
        ("BG32_MagicItem_817", RendleStickerScript),
        ("BG32_MagicItem_821", PilgrimpStickerScript),
        ("BG32_MagicItem_822", BazaarStickerScript),
        ("BG32_MagicItem_832", WindfallPortraitScript),
        ("BG32_MagicItem_844", SacrificialAltarScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
