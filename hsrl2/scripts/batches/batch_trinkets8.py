"""批次 trinkets8 — 饰品第八批（作业单 2026-09-02）。

与 batch_trinkets1..7 的 id 集合互不相交；全部 id 均为
`CardDB.trinket_offer_pool()` 中的**商店本体**（无 `t`/`t2` 升级变体、
无纯 token）。数值一律取自 `data/bg_trinkets.json` 的
`CardDef.num(0/1)`；CardDef 无参数而文本含字面量的 +N 类增量在各类
`Params:` 行按 SOP §3 声明。

主题: **既有引擎原语可精确表达的单卡饰品**——每类效果落在已验证的
消费点上，零新引擎/零近似:
  - 事件监听: `minion_bought` / `card_played` / `summon` /
    `divine_shield_lost` / `before_attack` / `tavern_refresh`（全部
    引擎真实 fire）
  - 池感知获取: `_pool_candidates` + `minion_pool.acquire` +
    `pending_hand_add`（RULES §2.3/§2.4/§3.3），酒馆注入唯一入口
    `game.inject_tavern_minion`（RULES §2.5/§7）
  - 战吼重触发: `TriggerBattlecry`（TriggerBattlecry 自带 Brann 加倍 +
    COUNTER_BATTLECRIES 记账）
  - Avenge 协议: 非随从实体类属性 `avenge_threshold`（引擎对
    `hero.trinkets` 统一计数，仅战斗内——RULES §6.11）
  - 血宝石: `GetBloodGems(hero, n, variant=…)`（变体关键词仅在目标为
    Quilboar/ALL 时由 `BG20_GEM_*` 脚本授予）
  - 关联卡数据链: `CardDef.evolution_card_id` → `CardDB.by_dbf`
    （零硬编码卡 id）

实现（21 个 id / 21 张饰品）:
  BG30_MagicItem_982  Shaman Prayer Beads   — 买 num(0) 个战吼随从后:
                                              随机战吼随从
  BG30_MagicItem_545  Fridge Magnet         — Avenge(num(0)): 随机磁力随从
  BG35_MagicItem_851  Water Wheel           — 打出元素: 随机酒馆法术
                                              （每回合 num(0) 次）
  BG36_MagicItem_850  Cookie's Stirring Rod — 打出 num(0) 个鱼人: 2 张
                                              随机酒馆法术
  BG32_MagicItem_930  Archaic Scroll        — 施放 num(1) 个法术后:
                                              随机纳迦
  BG32_MagicItem_171  Divine Signet         — 友方失去圣盾: 随机酒馆法术
                                              （每场 num(1) 次）
  BG30_MagicItem_910  Mechagon Adapter      — 友方机械失去圣盾: 再给圣盾
                                              （每场 num(0) 次）
  BG32_MagicItem_363  Faerie Dragon Scale   — 友方龙攻击: 给圣盾
                                              （每场 num(1) 次）
  BG30_MagicItem_886  Reinforced Shield     — 召唤随从: 给圣盾
                                              （每场 num(1) 次）
  BG30_MagicItem_540  Slamma Sticker        — 战斗内召唤野兽: 攻击翻倍
  BG30_MagicItem_978  Blingtron's Sunglasses— 战斗内召唤机械: 随机友方
                                              机械获得圣盾
  BG32_MagicItem_301  Bassgill Portrait     — Get Bassgill; 战斗内召唤
                                              鱼人: 给圣盾
  BG32_MagicItem_306  Herald Sticker        — SoC: 触发全部友方亡语
  BG36_MagicItem_213  Lightfeather Sticker  — SoC: 友方 Rally 随从获得圣盾
  BG35_MagicItem_752  Young Murk-Eye Sticker— EoT: 触发最左/最右随从战吼
  BG30_MagicItem_406  Butcher's Sickle      — Get Butchering; 每回合再来
  BG32_MagicItem_831  Sellemental Portrait  — Get Sellemental; 每回合再来
  BG32_MagicItem_415  Battle Horn           — Discover 战吼随从;
                                              Avenge(2): 触发友方战吼
  BG30_MagicItem_973  Minion Bait           — 刷新时酒馆多 2 个 num(0) 种族
  BG35_MagicItem_862  Upstart Embers        — 刷新后: 酒馆最高生命随从
                                              属性翻倍
  BG35_MagicItem_434  Jewelry Box           — Get 1 颗随机变体血宝石
                                              （Taunt/DS/Reborn）; 每回合再来

DEFERRED（本批逐张评估后放弃；每张附具体引擎依赖，禁止近似）:
  - BG32_MagicItem_902 Statue of Hir'eek — "After 2 minions in the Tavern
    are consumed, get a random Tavern spell"。`minion_consumed` 事件
    在受害者**已被移出容器并 zone=REMOVED 之后**广播（actions/consume.py
    步骤 2→3），载荷只有 (demon, minion) —— 无来源区域字段，无法区分
    "酒馆中"与棋盘/手牌吞噬。Dependency: 事件携带 `zone=` 或
    `from_tavern=True`。
  - BG32_MagicItem_821 Pilgrimp Sticker / BG32_MagicItem_822 Bazaar
    Sticker / BG30_MagicItem_701 The Eye of Sargeras /
    BG35_MagicItem_152 Demonic Tapestry — "…costs Health instead of Gold
    to buy" 的**每回合限定次数/每第 N 张**协议。引擎只有 CardDef 静态
    `health_cost` 标志（Hasty Excavation），无运行时按次数/种族/分类
    切换支付方式的标记与消费点。Dependency: `hero._health_buy_*` 计数 +
    `buy_from_tavern` 消费。
  - BG32_MagicItem_901 Gold-plated Compass — "Make the next {0} you buy
    Golden"（{0}=num(0)=92=NAGA）+ 5 次免费刷新。免费刷新半场可用，但
    "下一次购买的纳迦金色化"需要购买路径上的 pending-golden 标记与
    池记账（GILDED_NOT_TRIPLED）协议。Dependency: 购买时金色化协议。
  - BG35_MagicItem_713 Trusty Crowbar — "Whenever you get a Pirate…"。
    引擎无 hero 级"获得卡牌"事件（`on_enter_hand` 是实体级脚本钩子，
    不能反查获得者/来源）。Dependency: hero 级 card_gained 事件。
  - BG32_MagicItem_891 Finley's Helmet / BG32_MagicItem_892 Vibrant
    Bubble / BG36_MagicItem_801 Consuming Claw — "Bonus Keyword" 的
    定义域无数据字段（RULES §9.6），且无"逐实体记录被授予 bonus 关键词"
    机制。Dependency: Bonus Keyword 集合 + per-entity 记账。
  - BG30_MagicItem_703 Mystery Cube / BG30_MagicItem_891 Trip Vouchers /
    BG35_MagicItem_816 Orb of the Unknown / BG36_MagicItem_305 Rune of
    Transmutation — 依赖**饰品替换/授予**协议（"replace this"/"Get a
    random Trinket"）。第九轮引擎已提供 `game.grant_trinket` /
    `grant_random_trinket` / `replace_trinket`（RULES §7.4.3），但该族
    由**兄弟批次 batch_trinkets9** 承接（本作业单范围外），故不在本批
    注册；台账理由 = 归属分工而非引擎缺口。
  - BG32_MagicItem_417 Tarecgosa Sticker — "Your left and right-most
    Dragons permanently keep Bonus Keywords and stats gained in combat"。
    引擎 PERSIST 是**单实体 tag**（Tarecgosa / Persistent Poet），无
    "按位置 + 种族持续授予"的光环。Dependency: 位置/种族 PERSIST 光环。
  - BG30_MagicItem_804 Ancient Wishbone — "Your Hero Power triggers
    twice"。`use_hero_power` 只有 `uses_per_turn` / `hp_uses`（多次
    **使用**），无"效果结算翻倍"钩子。Dependency: hero_power 效果倍率。
  - BG32_MagicItem_366 Guiding Candle — "Your first two Refreshes each
    turn contain only Tier 6 cards"。引擎只有 `_tavern_offer_tier_only`
    （= 与酒馆等级同档）与 `_tavern_min_tier` 下限，无"指定第 N 档"过滤，
    也无每回合前 N 次刷新计数协议。Dependency:
    `hero._tavern_offer_tier_exact` + 每回合刷新计数。
  - BG30_MagicItem_986 Peacebloom Candle / BG32_MagicItem_957 Grifter
    Portrait / BG36_MagicItem_202 Warcry Totem — "The first N <类> you
    buy each turn are free"。第九轮引擎已补 `FREE_SPELL_BUYS_THIS_TURN`
    + `FREE_MINION_BUY_RACE` / `FREE_MINION_BUY_KEYWORD` 限定协议
    （RULES §7.4.4），并由**兄弟批次 batch_trinkets10** 注册
    （Peacebloom Candle / Grifter Portrait / Warcry Totem），本批不再
    重复。
  - BG35_MagicItem_921 Cowrie Necklace — "Tavern spells that give stats
    cost (2) less"。第十轮已补**持久**折扣 `TAVERN_SPELL_COST_MOD`
    （RULES §7.4.5），但缺的是"法术**效果类别**（give stats）"的定义域
    ——引擎无按效果类型分类法术子集的字段/查询。Dependency: Tavern
    spell 效果类别标注。注: 同族的 TAVERN_SPELL_COST_MOD 消费点已由
    batch_discount_misc（Lubber Sticker）验证。
  - BG32_MagicItem_170 Spell-powered Wrench /
    BG36_MagicItem_812 Emergency Gearblade / BG35_MagicItem_925 Coral
    Spear / BG35_MagicItem_850 Pocket Cyclone — "cast <指定法术>" 家族。
    引擎无"按 card_id 直接施放"原语（`play_spell` 要求实体已在手牌），
    且 Repair Job/Easterly Winds 无生产调用点。Dependency:
    `game.cast_spell_by_id(hero, card_id, target=…)`。
  - BG35_MagicItem_740 Sky Golem Portrait / BG30_MagicItem_917 Rusty
    Trident / BG30_MagicItem_952 Jarred Frostling / BG35_MagicItem_714
    Powder Keg — 战斗内授予亡语只有 batch_hero_combat3 的私有
    `_grant_combat_deathrattle` + COMBAT_END 恢复协议（无共享引擎原语）；
    且部分需要 "random Spellcraft spell"/Sky Pirate token 集合定义。
    Dependency: 共享 grant_combat_deathrattle 原语。
  - BG30_MagicItem_418 Bronzebeard Portrait / BG30_MagicItem_971 Enforcer
    Portrait — "are both Murlocs and Dragons"/"have all minion types" 的
    **多/全种族身份改写**。实体 RACE 是单值 tag；Race.ALL 语义为
    "匹配一切"而非"显示为全类型"，无法精确表达双种族。Dependency:
    多值 RACE 支持。
  - BG32_MagicItem_280 Eclectic Shrine — 已在
    batch_trinkets7 台账 DEFERRED（improve 时机无权威 + All 型重复资格）。
    Status: 已由 batch_trinkets24 注册（两处历史 AMBIGUOUS 已由仓内既有先例裁定，2026-09-02 落地）

协议: 饰品实体经 `_offer_trinkets` 购买 → `hero.trinkets`；脚本只挂
`on_bind` / `start_of_turn` / `end_of_turn` / `start_of_combat` /
`avenge`（接线审计 W1 白名单）。全部状态写在 **hero 作用域**或
**source 实体属性**（非 game 级 flag——SOP §12 item 9）。
"""

from __future__ import annotations

from typing import Optional

from hsrl2.actions import (
    Buff,
    Discover,
    GainKeyword,
    GetRandomMinion,
    TriggerBattlecry,
)
from hsrl2.actions.bloodgem import BLOOD_GEM_VARIANTS, GetBloodGems
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    BEFORE_ATTACK,
    CARD_PLAYED,
    DIVINE_SHIELD_LOST,
    MINION_BOUGHT,
    SUMMON,
    TAVERN_REFRESH,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell as SpellType
from hsrl2.tags import CardType, GameTag, Race

# 含 All 型的匹配族（Amalgam 全种族，RULES §6.4 匹配规则的通用裁定）
_DRAGON_RACES = (Race.DRAGON, Race.ALL)
_MECH_RACES = (Race.MECH, Race.ALL)
_BEAST_RACES = (Race.BEAST, Race.ALL)
_MURLOC_RACES = (Race.MURLOC, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)

# 血宝石变体随机池（"Taunt, Divine Shield, or Reborn"——排序确保
# game.rng 抽样确定性; None=vanilla 不在此列）
_GEM_KEYWORD_VARIANTS = tuple(sorted(
    v for v in BLOOD_GEM_VARIANTS if v is not None))


def _hero(ctx):
    return ctx.get("hero") if ctx else None


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero):
    return [m for m in hero.board if not m.dead]


def _has_script_hook(entity, hook: str) -> bool:
    """实体脚本是否定义了某钩子（行为权威，含金色卡定义不带关键词的
    数据缺口——batch_rally2 已报告）。"""
    script = getattr(entity, "scripts", None)
    return script is not None and getattr(script, hook, None) is not None


def _has_battlecry_hook(game, m: Minion) -> bool:
    """随从是否有战吼（统一门禁 `Game.has_battlecry`）。

    2026-09-13（RULES §7.4.17）: 由脚本侧"tag 或钩子"双通道改为委托
    引擎 `has_battlecry`——多出**条件化战吼**通道（Selfless Portrait，
    `battlecry_flag` 生效才计入），且与引擎 `bc_first` 配额门禁
    单一事实源，避免两处双通道漂移。
    """
    return game.has_battlecry(m)


def _has_deathrattle_hook(game, m: Minion) -> bool:
    """随从是否有亡语（tag 或脚本钩子双通道）。"""
    return m.has(GameTag.DEATHRATTLE) or _has_script_hook(m, "deathrattle")


def _has_rally_hook(m: Minion) -> bool:
    """随从是否具有 Rally 效果（"Rally minion" 判定，batch_trinkets7
    同构双通道）。"""
    return m.has(GameTag.RALLY) or _has_script_hook(m, "rally")


def _random_pool_minion(game, hero, *, race=None, keyword=None,
                        min_tier=None, max_tier=None,
                        label="trinket_random_minion") -> bool:
    """从共享池随机获取 1 只过滤后的随从（池感知，RULES §2.3/§2.4）。

    候选过滤复用 `actions.discover._pool_candidates`（剩余量 > 0 /
    本局禁用种族 / tier / 种族），keyword 再按 CardDef.keywords 过滤;
    选中 `minion_pool.acquire` 占池 → create_minion → pending_hand_add。
    池耗尽 → 落空（官方语义），返回是否成功。
    """
    cands = _pool_candidates(game, race, min_tier, max_tier)
    if keyword is not None:
        cands = [cid for cid in cands
                 if keyword in game.db.get(cid).keywords]
    if not cands:
        return False
    pick = game.rng.choice(cands, label=label)
    if not game.minion_pool.acquire(pick):
        return False
    game.pending_hand_add(hero, game.create_minion(pick, controller=hero))
    return True


def _random_tavern_spell(game, hero, label: str) -> bool:
    """获得 1 张随机酒馆法术（池感知）。

    tier 口径: `tech_level <= hero.tavern_tier`（与 Holli'dae /
    Mystic Essence / SpellPool.draw_tavern 全仓统一，2026-09-02 Yogg
    修复后口径），并经 `Game.tavern_spell_candidates` 施加**存在档
    白名单**（异变 101/102 非存在档法术不可达）。占池 → create_spell →
    pending_hand_add。
    """
    cands = game.tavern_spell_candidates(min_tier=1,
                                         max_tier=hero.tavern_tier)
    if not cands:
        return False
    pick = game.rng.choice(cands, label=label)
    if not game.spell_pool.acquire(pick):
        return False
    game.pending_hand_add(hero, game.create_spell(pick, controller=hero))
    return True


def _evolution_card_id(game, source) -> str:
    """`evolution_card_id` 数据链解析关联卡（零硬编码卡 id）。"""
    d = game.db.get(source.card_id)
    if d is None or d.evolution_card_id is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    token = game.db.by_dbf(d.evolution_card_id)
    if token is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id "
            f"{d.evolution_card_id} not in db")
    return token.id


def _grant_card(game, hero, card_id: str) -> bool:
    """Get a <数据链解析出的卡>（随从**或**酒馆法术）。

    - **池随从**: 池仍有副本则 `minion_pool.acquire` 占池（RULES §2.3），
      池耗尽 → 落空（RULES §2.4）; 出售/淘汰时引擎按 1 份回池，收支平衡
    - **池法术**: `spell_pool.acquire` 占池（RULES §2.3——Butchering
      `BG28_604` 在 36.2.2 数据是 `card_type=42` 的**池法术**，
      `is_pool_spell=True`/`tech_level=5`; 旧实现只判 `is_pool_minion`
      就 `create_minion` → 把法术造成 0 血死随从实体且池永不扣减，
      2026-09-02 对抗审查 CRITICAL）
    - **非池卡**（token / 池外专属）: 零池操作
    - 进手牌走 `pending_hand_add`（满手排队 RULES §3.3）
    """
    d = game.db.get(card_id)
    if d is None:
        raise GameStateError(f"unknown card_id {card_id}")
    if d.card_type == CardType.MINION and d.is_pool_minion \
            and game.minion_pool.available(card_id) <= 0:
        return False
    if d.card_type in (CardType.SPELL, CardType.BACON_SPELL) \
            and d.is_pool_spell and game.spell_pool.available(card_id) <= 0:
        return False
    # 实体类型/池记账/白板/满手排队统一走引擎入口（RULES §7.4.6）
    game.grant_card_copy_to_hand(hero, d)
    return True


def _battlecry_candidates(game):
    """池中仍有副本的战吼随从 card_id（Battle Horn 的 Discover 候选）。

    与 actions.discover._pool_candidates 同口径: 池剩余量 > 0、本局禁用
    种族排除（NONE/ALL 永远可用）。
    """
    pool = game.minion_pool
    out = []
    for d in game.db.pool_minions():
        if "battlecry" not in d.keywords:
            continue
        if pool.available(d.id) <= 0:
            continue
        if (pool.active_races is not None
                and d.race not in (Race.NONE, Race.ALL)
                and d.race not in pool.active_races):
            continue
        out.append(d.id)
    return out


# ══════════════════ BG30_MagicItem_982 Shaman Prayer Beads ══════════════════

class ShamanPrayerBeadsScript:
    """
    Natural language: [x]After you buy 2 <b>Battlecry</b> minions, get a
    random <b>Battlecry</b> minion. <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: MINION_BOUGHT（minion=）
         ——引擎在 `buy_from_tavern` 成功入手后广播
      2. 条件: `minion.controller is 本人` 且该随从有战吼
         （`_has_battlecry_hook` 双通道: BATTLECRY tag 或脚本 battlecry
         钩子——金色卡定义不带关键词的数据缺口）
      3. 计数跨回合累积（文本无 "this turn"）; 达 num(0) → 清零并
         `_random_pool_minion(keyword="battlecry")`（池感知占池 + 满手
         排队 RULES §2.3/§3.3）
      4. 池内战吼随从耗尽 → 该次落空; 只作用于本人（对手购买不计数）

    Test: test_batch_trinkets8.py — 真实 buy_from_tavern 战吼随从:
      前 num(0)-1 个不发放、第 num(0) 个恰好入手 1 只战吼随从且池 -1 /
      非战吼购买不计数 / 对手购买不计数 / 无饰品对照不获取

    Params: {0}=2（BG30_MagicItem_982 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        state = {"n": 0}

        def on_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if not _has_battlecry_hook(g, minion):
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            _random_pool_minion(g, h, keyword="battlecry",
                                label="shaman_prayer_beads")

        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        return None


# ══════════════════ BG30_MagicItem_545 Fridge Magnet ══════════════════

class FridgeMagnetScript:
    """
    Natural language: [x]<b>Avenge ({0}):</b> Get a random
    <b>Magnetic</b> minion.

    Formal spec:
      1. Avenge 阈值 num(0)=3 = 类属性 `avenge_threshold`（引擎对
         `hero.trinkets` 统一计数、**仅战斗内**——RULES §6.11; 类属性
         无法在 import 期读 CardDef，测试钉死 == num(0)）
      2. avenge: `_random_pool_minion(keyword="magnetic")`——池感知占池
         （RULES §2.3）+ 满手排队（RULES §3.3）; 36.2.2 数据中磁力随从
         存在（Scraper Sticker 同集合）
      3. 每次达标各发放 1 只（计数由引擎清零）; 池耗尽 → 落空;
         只作用于本人

    Test: test_batch_trinkets8.py — 战斗内 num(0) 次友方死亡后恰好入手
      1 只磁力随从且该类池 -1 / 未达标（num(0)-1 次）不发放 / 招募期
      死亡不计数（阶段守卫）/ 对手死亡不计数

    Params: {0}=3（BG30_MagicItem_545 num(0)）; avenge_threshold=3
              （== num(0)，测试钉死）
    """

    avenge_threshold = 3   # == CardDef.num(0)（文本 "Avenge ({0})"）

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _random_pool_minion(game, h, keyword="magnetic",
                            label="fridge_magnet")
        return None


# ══════════════════ BG35_MagicItem_851 Water Wheel ══════════════════

class WaterWheelScript:
    """
    Natural language: After you play an Elemental, get a random Tavern
    spell. <i>(Twice per turn.)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: CARD_PLAYED（card=）——
         仅 `isinstance(card, Minion)` 且 `card.controller is 本人`
         且 race ∈ (ELEMENTAL, ALL)（Amalgam 规则）
      2. 每回合上限 num(0)=2（"Twice per turn"）——闭包按 `game.turn`
         归零; 达上限后本回合不再发放，下回合恢复
      3. 触发: `_random_tavern_spell`（tier ≤ 酒馆等级、占法术池、
         create_spell + pending_hand_add）
      4. 池空 → 落空（该次发放机会照常消耗——"after you play an
         Elemental, get" 的尝试已发生，文本无落空补偿语义）;
         只作用于本人

    Test: test_batch_trinkets8.py — 真实 play_minion 元素: 前 num(0) 次
      各入手 1 张池法术且法术池 -num(0)、第 num(0)+1 次不再发放 /
      非元素不触发 / 真实 end_recruit_phase 推进回合后额度重置 /
      对手打出元素不影响本人

    Params: {0}=2（BG35_MagicItem_851 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        limit = _num(game, source.card_id, 0)
        state = {"turn": None, "n": 0}

        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not h:
                return
            if card.race not in _ELEMENTAL_RACES:
                return
            if state["turn"] != g.turn:
                state["turn"] = g.turn
                state["n"] = 0
            if state["n"] >= limit:
                return
            state["n"] += 1
            _random_tavern_spell(g, h, "water_wheel")

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG36_MagicItem_850 Cookie's Stirring Rod ══════════════════

class CookiesStirringRodScript:
    """
    Natural language: After you play 5 Murlocs, get two random Tavern
    spells. <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: CARD_PLAYED（card=）——
         Minion + `controller is 本人` + race ∈ (MURLOC, ALL)
      2. 计数跨回合累积; 达 num(0)=5 → 清零并发放 **2** 张随机酒馆法术
         （"two" 为文本字面量，CardDef 无第二参数）——逐张走
         `_random_tavern_spell`（占池/满手排队）
      3. 池空 → 该张落空（发放张数可少于 2）; 只作用于本人

    Test: test_batch_trinkets8.py — 真实 play_minion 鱼人: 前 num(0)-1 只
      不发放 / 第 num(0) 只恰好入手 2 张池法术且法术池 -2 / 非法术的
      非鱼人不计数 / 对手打出不计数 / 无饰品对照不获取

    Params: {0}=5（BG36_MagicItem_850 num(0)）; spell_count=2（"two" 文本
              字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        state = {"n": 0}

        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not h:
                return
            if card.race not in _MURLOC_RACES:
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            for _ in range(2):
                _random_tavern_spell(g, h, "cookies_stirring_rod")

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG32_MagicItem_930 Archaic Scroll ══════════════════

class ArchaicScrollScript:
    """
    Natural language: [x]After you cast {1} spells, get a random Naga.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: **spell_resolving**
         （每次施放；双施按次计、效果施法同计）——
         `isinstance(card, Spell)` 且 `card.controller is 本人`（法术
         无论定向与否都广播; 文本 "cast spells" 无 target 限定）
      2. 计数跨回合累积; 达 num(1)=7（阈值占位符 {1}）→ 清零并
         `_random_pool_minion(race=Race.NAGA)`（池感知占池 + 满手排队）
      3. 池内纳迦耗尽 → 落空; 只作用于本人（对手施法不计数）

    Test: test_batch_trinkets8.py — 真实 play_spell: 前 num(1)-1 个不发放、
      第 num(1) 个恰好入手 1 只纳迦且纳迦池 -1、计数清零 / 对手施法不
      计数 / 无饰品对照不获取 / 阈值 == CardDef.num(1)

    Params: {0}=7 {1}=7（BG32_MagicItem_930 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 1)
        state = {"n": 0}

        def on_played(g, spell=None, card=None, **kw):
            # `spell_resolving` = **每次施放**（双施按 2 计、效果施法同样计入;
            # `card_played` 只在打出时广播一次 → 双施漏计。2026-09-02 对抗
            # 审查与 BG32_MagicItem_808 同族修复）
            # 事件载荷是 `spell=`（`spell_resolving`）——`card=` 仅为兼容
            card = spell if spell is not None else card
            if card is None or card.controller is not h:
                return
            if not isinstance(card, SpellType):
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            _random_pool_minion(g, h, race=Race.NAGA,
                                label="archaic_scroll")

        game.events.register(Listener(event="spell_resolving",
                                      owner=source, callback=on_played))
        return None


# ══════════════════ BG32_MagicItem_171 Divine Signet ══════════════════

class DivineSignetScript:
    """
    Natural language: [x]After a friendly minion loses <b>Divine
    Shield</b>, get a random Tavern spell.
    <i>({1} times per combat.)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: DIVINE_SHIELD_LOST
         （minion=）——`actions.stats.LoseKeyword` 在圣盾移除时广播
         （游戏内战斗伤害路径同样经该 Action）
      2. 条件: `minion.controller is 本人` 且 `game.in_combat`
         （wiki 分类 Combat-related; "(N times per combat)" 的额度只
         在战斗内存在——额度每场开始重置，见 3）
      3. 每场最多 num(1)=4 次: 计数器存 `source` 实体属性，饰品
         `start_of_combat` 钩子每场开战重置为 num(1)（SoC 在攻击循环前）
      4. 触发: `_random_tavern_spell`（占池 + 满手排队）; 池空 → 落空
         （额度照常消耗）; 只作用于本人

    Test: test_batch_trinkets8.py — 战斗内真实 LoseKeyword 移除友方圣盾:
      前 num(1) 次各入手 1 张池法术、第 num(1)+1 次不再发放 / 真实
      run_combat 后额度重置（下战斗首触发再度发放）/ 非战斗期移除不
      发放 / 对手失去圣盾不发放

    Params: {1}=4（BG32_MagicItem_171 num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        limit = _num(game, source.card_id, 1)
        source._signet_left = limit

        def on_lost(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if not g.in_combat:
                return
            if getattr(source, "_signet_left", 0) <= 0:
                return
            source._signet_left -= 1
            _random_tavern_spell(g, h, "divine_signet")

        game.events.register(Listener(event=DIVINE_SHIELD_LOST,
                                      owner=source, callback=on_lost))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        source._signet_left = _num(game, source.card_id, 1)
        return None


# ══════════════════ BG30_MagicItem_910 Mechagon Adapter ══════════════════

class MechagonAdapterScript:
    """
    Natural language: [x]After a friendly Mech loses <b>Divine Shield</b>,
    give it <b>Divine Shield</b>. <i>(3 times per combat.)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: DIVINE_SHIELD_LOST
         （minion=）
      2. 条件: `minion.controller is 本人`、race ∈ (MECH, ALL)、
         `game.in_combat`（Combat-related 裁定同 Divine Signet）
      3. 每场最多 num(0)=3 次（文本字面量 "(3 times per combat.)" 与
         num(0) 同源）: `source._adapter_left`，`start_of_combat` 重置
      4. 触发: GainKeyword(minion, DIVINE_SHIELD)——同一死亡窗口内
         重新授予不递归（keyword_gained 非 DIVINE_SHIELD_LOST）
      5. 非机械/对手/超额 → 不授予

    Test: test_batch_trinkets8.py — 战斗内真实 LoseKeyword: 移除机械圣盾
      后立即重新带圣盾（前 num(0) 次）/ 第 num(0)+1 次不再授予 / 非机械
      不授予 / 对手机械不授予 / 真实 run_combat 后额度重置

    Params: {0}=3（BG30_MagicItem_910 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._adapter_left = _num(game, source.card_id, 0)

        def on_lost(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if minion.race not in _MECH_RACES:
                return
            if not g.in_combat:
                return
            if getattr(source, "_adapter_left", 0) <= 0:
                return
            source._adapter_left -= 1
            g.run_actions(GainKeyword(minion, GameTag.DIVINE_SHIELD))

        game.events.register(Listener(event=DIVINE_SHIELD_LOST,
                                      owner=source, callback=on_lost))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        source._adapter_left = _num(game, source.card_id, 0)
        return None


# ══════════════════ BG32_MagicItem_363 Faerie Dragon Scale ══════════════════

class FaerieDragonScaleScript:
    """
    Natural language: [x]Whenever a friendly Dragon attacks, give it
    <b>Divine Shield</b>. <i>({1} times per combat.)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: BEFORE_ATTACK
         （attacker=, defender=）——combat.py 在**伤害结算前**广播
         （与 Rally 同时点），故圣盾可吸收本次反击伤害
         （Ceremonial Sword / batch_trinkets2 同事件先例）
      2. 条件: `attacker.controller is 本人`、`not attacker.dead`、
         race ∈ (DRAGON, ALL)、`game.in_combat`
      3. 每场最多 num(1)=3 次: `source._scale_left`，`start_of_combat`
         重置; 攻击者已有圣盾 → 不消耗额度（授予为 no-op）
      4. 触发: GainKeyword(attacker, DIVINE_SHIELD)

    Test: test_batch_trinkets8.py — 战斗内真实 execute_immediate_attack:
      BEFORE_ATTACK 探针在饰品监听器之后读到攻击者已带圣盾（对照无饰品
      为 False）/ 前 num(1) 次逐次授予、第 num(1)+1 次不再授予 /
      非龙不授予 / 对手龙不授予

    Params: {1}=3（BG32_MagicItem_363 num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._scale_left = _num(game, source.card_id, 1)

        def on_attack(g, attacker=None, defender=None, **kw):
            if attacker is None or attacker.dead:
                return
            if attacker.controller is not h:
                return
            if attacker.race not in _DRAGON_RACES:
                return
            if not g.in_combat:
                return
            if attacker.has(GameTag.DIVINE_SHIELD):
                return
            if getattr(source, "_scale_left", 0) <= 0:
                return
            source._scale_left -= 1
            g.run_actions(GainKeyword(attacker, GameTag.DIVINE_SHIELD))

        game.events.register(Listener(event=BEFORE_ATTACK, owner=source,
                                      callback=on_attack))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        source._scale_left = _num(game, source.card_id, 1)
        return None


# ══════════════════ BG30_MagicItem_886 Reinforced Shield ══════════════════

class ReinforcedShieldScript:
    """
    Natural language: [x]Whenever you summon a minion, give it <b>Divine
    Shield</b>. <i>({1} times per combat.)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: SUMMON（minion=）——
         引擎在 `game.summon` 入场后、`on_summon` 脚本钩子前广播
      2. 条件: `minion.controller is 本人`、`not minion.dead`、
         `game.in_combat`（wiki 分类 Combat-related; 每场额度协议与
         Divine Signet/Mechagon Adapter 同裁定）
      3. 每场最多 num(1)=5 次: `source._shield_left`，`start_of_combat`
         重置; 已带圣盾的召唤物不消耗额度
      4. 触发: GainKeyword(minion, DIVINE_SHIELD)

    Test: test_batch_trinkets8.py — 战斗内真实 game.summon: 前 num(1) 个
      召唤物各带圣盾、第 num(1)+1 个不带（对照无饰品全不带）/
      招募期召唤不授予 / 对手召唤不授予 / run_combat 后额度重置

    Params: {1}=5（BG30_MagicItem_886 num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._shield_left = _num(game, source.card_id, 1)

        def on_summoned(g, minion=None, **kw):
            if minion is None or minion.dead:
                return
            if minion.controller is not h:
                return
            if not g.in_combat:
                return
            if minion.has(GameTag.DIVINE_SHIELD):
                return
            if getattr(source, "_shield_left", 0) <= 0:
                return
            source._shield_left -= 1
            g.run_actions(GainKeyword(minion, GameTag.DIVINE_SHIELD))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summoned))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        source._shield_left = _num(game, source.card_id, 1)
        return None


# ══════════════════ BG30_MagicItem_540 Slamma Sticker ══════════════════

class SlammaStickerScript:
    """
    Natural language: [x]After you summon a Beast in combat, double its
    Attack.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: SUMMON（minion=）
      2. 条件: `game.in_combat`、`minion.controller is 本人`、
         `not minion.dead`、race ∈ (BEAST, ALL)
      3. 触发: Buff(minion, atk=minion.atk)——"double its Attack" = 当前
         攻击 ×2 → 增量 = 当前攻击; 快照时机 = SUMMON 事件当下（含召唤
         来源已施加的增益; BG26_802 Banana Slamma 同构先例）
      4. 战斗快照战后回滚（RULES §3.5）; 招募期召唤不触发（"in combat"）

    Test: test_batch_trinkets8.py — 战斗内召唤野兽攻击翻倍（对照无饰品
      不变）/ 招募期召唤不翻倍 / 非野兽不触发 / 对手召唤不触发 /
      0 攻野兽无变化

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_summoned(g, minion=None, **kw):
            if minion is None or minion.dead:
                return
            if not g.in_combat or minion.controller is not h:
                return
            if minion.race not in _BEAST_RACES:
                return
            if minion.atk <= 0:
                return
            g.run_actions(Buff(minion, atk=minion.atk))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summoned))
        return None


# ══════════════════ BG30_MagicItem_978 Blingtron's Sunglasses ══════════════════

class BlingtronsSunglassesScript:
    """
    Natural language: [x]After you summon a Mech in combat, give a
    friendly Mech <b>Divine Shield</b>.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: SUMMON（minion=）
      2. 条件: `game.in_combat`、`minion.controller is 本人`、
         `not minion.dead`、被召唤者 race ∈ (MECH, ALL)（"summon a
         Mech in combat"）
      3. 触发: 本人棋盘存活机械（race ∈ (MECH, ALL)，含被召唤者本身）
         随机 1 只（`game.rng.choice`）获得 GainKeyword(DIVINE_SHIELD)
         ——"a friendly Mech" 无 [Targeted] 标记 → 随机（SOP §8 判别法）
      4. 无友方机械 → 落空（被召唤者本身即机械，故至少 1 个）;
         只作用于本人棋盘

    Test: test_batch_trinkets8.py — 战斗内召唤机械后恰好 1 只友方机械带
      圣盾（对照无饰品 0 只）/ 招募期召唤不触发 / 召唤非机械不触发 /
      对手召唤机械不影响本人

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_summoned(g, minion=None, **kw):
            if minion is None or minion.dead:
                return
            if not g.in_combat or minion.controller is not h:
                return
            if minion.race not in _MECH_RACES:
                return
            mechs = [m for m in _living(h) if m.race in _MECH_RACES]
            if not mechs:
                return
            pick = g.rng.choice(mechs, label="blingtron_sunglasses")
            g.run_actions(GainKeyword(pick, GameTag.DIVINE_SHIELD))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summoned))
        return None


# ══════════════════ BG32_MagicItem_301 Bassgill Portrait ══════════════════

class BassgillPortraitScript:
    """
    Natural language: [x]Get a Bassgill.
    After you summon a Murloc in combat, give it <b>Divine Shield</b>.

    Formal spec:
      1. on_bind: Get a Bassgill——`evolution_card_id` 数据链解析
         （dbf 98926 → `BG26_350`，零硬编码卡 id）。36.2.2 数据核实
         `is_pool_minion=False`（token 语义）→ `_grant_card` 不占池，
         create_minion + pending_hand_add（满手排队 RULES §3.3）
      2. on_bind 注册持久监听器（owner=饰品）: SUMMON（minion=）——
         条件 `game.in_combat`、`minion.controller is 本人`、
         `not minion.dead`、race ∈ (MURLOC, ALL)
      3. 触发: GainKeyword(minion, DIVINE_SHIELD)（"it" = 被召唤的鱼人）
      4. 只作用于本人; 战斗快照战后回滚

    Test: test_batch_trinkets8.py — 绑定入手 1 只 BG26_350（池不变量
      不变——token）/ 战斗内召唤鱼人后该鱼人带圣盾（对照无饰品不带）/
      招募期召唤不授予 / 非鱼人不授予 / 对手召唤不授予

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_card(game, h, _evolution_card_id(game, source))

        def on_summoned(g, minion=None, **kw):
            if minion is None or minion.dead:
                return
            if not g.in_combat or minion.controller is not h:
                return
            if minion.race not in _MURLOC_RACES:
                return
            if minion.has(GameTag.DIVINE_SHIELD):
                return
            g.run_actions(GainKeyword(minion, GameTag.DIVINE_SHIELD))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summoned))
        return None


# ══════════════════ BG32_MagicItem_306 Herald Sticker ══════════════════

class HeraldStickerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Trigger all friendly
    <b>Deathrattles</b>.

    Formal spec:
      1. start_of_combat（饰品 SoC 钩子，在攻击循环前）: 对本人棋盘
         **快照**（list）中每个存活且持亡语的随从
         （`_has_deathrattle_hook` 双通道: DEATHRATTLE tag 或脚本
         deathrattle 钩子）各触发一次 `run_script_hook(m, "deathrattle")`
      2. **无死亡**触发（Wolfhead Flail / Deathstrider 同构先例）:
         不计入 COUNTER_DEATHRATTLES、不广播 deathrattle_trigger、不回池
      3. 快照语义: 亡语召唤出的新随从的亡语不在本次触发范围内
         （"trigger all ... Deathrattles" = 结算时在场的那些）
      4. 空场/无亡语 → 落空; 只作用于本人（对手亡语不触发）

    Test: test_batch_trinkets8.py — 战斗内 2 个亡语探针各触发 1 次、
      非亡语探针 0 次（对照无饰品全 0）/ 对手亡语探针不被本人饰品触发

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        for m in list(_living(h)):
            if _has_deathrattle_hook(game, m):
                # 统一亡语入口（RULES §6.20）: 应用 Titus/dr_first/dr_extra
                game.trigger_deathrattle(m, hero=h)
        return None


# ══════════════════ BG36_MagicItem_213 Lightfeather Sticker ══════════════════

class LightfeatherStickerScript:
    """
    Natural language: <b>Start of Combat:</b> Give your <b>Rally</b>
    minions <b>Divine Shield</b>.

    Formal spec:
      1. start_of_combat: 本人棋盘全部存活 Rally 随从
         （`_has_rally_hook` 双通道: RALLY tag 或脚本 rally 钩子）
         获得 GainKeyword(DIVINE_SHIELD)
      2. 已带圣盾者跳过（去重，避免重复 keyword_gained）
      3. 无 Rally 随从 → 落空; 战斗快照战后回滚（RULES §3.5）;
         只作用于本人

    Test: test_batch_trinkets8.py — SoC 探针（START_OF_COMBAT 事件在饰品
      SoC 之后广播）读到 Rally 探针带圣盾、非 Rally 探针不带（对照无
      饰品都不带）/ 对手 Rally 随从不被本人饰品授予

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return [GainKeyword(m, GameTag.DIVINE_SHIELD)
                for m in _living(h)
                if _has_rally_hook(m) and not m.has(GameTag.DIVINE_SHIELD)]


# ══════════════════ BG35_MagicItem_752 Young Murk-Eye Sticker ══════════════════

class YoungMurkEyeStickerScript:
    """
    Natural language: [x]At the end of your turn, trigger your left and
    right-most minions' <b>Battlecries</b>.

    Formal spec:
      1. end_of_turn（饰品 EoT 钩子）: 本人棋盘存活随从按顺序取最左
         与最右（仅 1 只时只取该只，去重避免重复触发）
      2. 每个目标若持战吼（`_has_battlecry_hook` 双通道）→
         `TriggerBattlecry(target)`（自带 Brann 加倍与
         COUNTER_BATTLECRIES 记账 + BATTLECRY_TRIGGER 广播）
      3. 无战吼/空场 → 落空; 只作用于本人棋盘

    Test: test_batch_trinkets8.py — 3 个战吼探针: 最左与最右各触发 1 次、
      中间 0 次 / 最左无战吼时不触发（对照无饰品全 0）/ 对手棋盘探针
      不被本人饰品触发

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = _living(h)
        if not living:
            return None
        targets = [living[0]]
        if living[-1] is not living[0]:
            targets.append(living[-1])
        actions = [TriggerBattlecry(m) for m in targets
                   if _has_battlecry_hook(game, m)]
        return actions or None


# ══════════════════ BG30_MagicItem_406 Butcher's Sickle ══════════════════

class ButchersSickleScript:
    """
    Natural language: [x]Get a Butchering.
    At the start of each turn, get another.

    Formal spec:
      1. on_bind: Get a Butchering——`evolution_card_id` 数据链解析
         （dbf 110412 → `BG28_604`）。36.2.2 数据核实 `BG28_604` 是
         **池酒馆法术**（`card_type=42`, `is_pool_spell=True`,
         `tech_level=5`）→ `spell_pool.acquire` 占池 + `create_spell`
         进手牌（2026-09-02 对抗审查修复: 旧实现把它造成 Minion 实体且
         池永不扣减，法术效果永不结算）
      2. start_of_turn（饰品 SoT 钩子）: 再入手 1 张——"At the start of
         each turn, get another"
      3. 只进本人手牌

    Test: test_batch_trinkets8.py — 绑定入手 1 只 BG28_604 且随从池不变量
      不变 / 真实 end_recruit_phase 后再入手 1 只 / 对手手牌不变 /
      无饰品对照不获取

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_card(game, h, _evolution_card_id(game, source))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_card(game, h, _evolution_card_id(game, source))
        return None


# ══════════════════ BG32_MagicItem_831 Sellemental Portrait ══════════════════

class SellementalPortraitScript:
    """
    Natural language: [x]Get a Sellemental.
    At the start of each turn, get another.

    Formal spec:
      1. on_bind: Get a Sellemental——`evolution_card_id` 数据链解析
         （dbf 64038 → `BGS_115`，零硬编码卡 id）。36.2.2 数据核实
         `is_pool_minion=True` → `_grant_card` 池内有余则
         `minion_pool.acquire` 占池（RULES §2.3），池耗尽落空
         （RULES §2.4）; 出售时按 1 份回池，收支平衡
      2. start_of_turn（饰品 SoT 钩子）: 同款再获取
      3. 只进本人手牌（满手排队 RULES §3.3）

    Test: test_batch_trinkets8.py — 绑定入手 1 只 BGS_115 且该卡池 -1 /
      真实 end_recruit_phase 后再入手 1 只且池再 -1 / 对手手牌不变 /
      数据链解析 == BGS_115 且 is_pool_minion

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_card(game, h, _evolution_card_id(game, source))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_card(game, h, _evolution_card_id(game, source))
        return None


# ══════════════════ BG32_MagicItem_415 Battle Horn ══════════════════

class BattleHornScript:
    """
    Natural language: [x]<b>Discover</b> a <b>Battlecry</b> minion.
    <b>Avenge (2):</b> Trigger a friendly <b>Battlecry</b>.

    Formal spec:
      1. on_bind: `Discover(hero, candidates=<池中战吼随从>)`——候选 =
         `pool_minions()` 中 keywords 含 "battlecry" 且
         `minion_pool.available > 0`（RULES §6.18 池约束）; 三选项预留
         语义由 `Discover` Action 处理（选项生成即 acquire，resolve 保留
         选中、释放其余）
      2. Avenge 阈值 2 = 类属性 `avenge_threshold`（文本 "Avenge (2)"
         字面量；data 仅标 avenge=true 无数值参数）
      3. avenge: 本人棋盘随机 1 只持战吼的存活随从
         （`_has_battlecry_hook`）→ `TriggerBattlecry`（Brann 加倍 +
         COUNTER_BATTLECRIES 记账由 Action 处理）; 无战吼随从 → 落空
      4. 仅战斗内计数（引擎 RULES §6.11 守卫）; 三选项由自动化层 resolve

    Test: test_batch_trinkets8.py — 绑定产生 1 个 kind=discover_minion
      三选项发现，选项全为战吼随从且已预留占池 / resolve 后选中入手、
      其余回池（池净 -1）/ 战斗内 num(0)=2 次友方死亡后战吼探针被触发
      1 次（对照无饰品 0 次）/ 对手死亡不触发 / avenge_threshold == 2

    Params: avenge_threshold=2（文本字面量 "Avenge (2)"——CardDef 无数值）
    """

    avenge_threshold = 2   # 文本字面量 "Avenge (2)"（data 仅标 avenge=true）

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        cands = _battlecry_candidates(game)
        if not cands:
            return None
        return Discover(h, candidates=cands, kind="discover_minion")

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        targets = [m for m in _living(h) if _has_battlecry_hook(game, m)]
        if not targets:
            return None
        pick = game.rng.choice(targets, label="battle_horn")
        return TriggerBattlecry(pick)


# ══════════════════ BG30_MagicItem_973 Minion Bait ══════════════════

class MinionBaitScript:
    """
    Natural language: The Tavern offers 2 extra {0} whenever it is
    <b>Refreshed</b>.

    Formal spec:
      1. `{0}` = num(0) = 92 = `Race.NAGA`（DBF 种族枚举，tags.py
         `DBF_RACE_TO_ENUM`）——文本 "2 extra {0}" 即"额外 2 个纳迦"
      2. on_bind 注册持久监听器（owner=饰品）: TAVERN_REFRESH
         （hero=, auto=）——引擎在酒馆**填充完成后**广播（手动与
         自动刷新都计入，与 Frigid Blossom 同口径）
      3. 过滤 `hero is 本人`; 每次刷新从共享池随机取 2 只纳迦
         （`_pool_candidates(race=NAGA)`，含 Amalgam ALL），逐个
         `minion_pool.acquire` 占池后经 `game.inject_tavern_minion`
         注入展示区（唯一入口——自动套用 The Golden Arena 与
         `hero.tavern_buffs` 持久面）
      4. 池内纳迦不足 → 少注入（落空不补偿）; 注入体占展示位、下次
         刷新未冻结时回池（池守恒）

    Test: test_batch_trinkets8.py — 真实 refresh_tavern 后本人酒馆的纳迦
      数比同 seed 无饰品对照恰好多 2（纳迦池 -2）/ 对手刷新不给本人注入 /
      注入体 race == NAGA（或 ALL）

    Params: {0}=92（BG30_MagicItem_973 num(0) = Race.NAGA）;
              extra_count=2（"2 extra" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        race = Race(int(_num(game, source.card_id, 0)))

        def on_refresh(g, hero=None, **kw):
            if hero is not h:
                return
            for _ in range(2):
                cands = _pool_candidates(g, race)
                if not cands:
                    break
                pick = g.rng.choice(cands, label="minion_bait")
                if not g.minion_pool.acquire(pick):
                    continue
                g.inject_tavern_minion(h, pick)

        game.events.register(Listener(event=TAVERN_REFRESH, owner=source,
                                      callback=on_refresh))
        return None


# ══════════════════ BG35_MagicItem_862 Upstart Embers ══════════════════

class UpstartEmbersScript:
    """
    Natural language: [x]After you <b>Refresh</b>, double the stats of
    the highest-Health minion in the Tavern.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: TAVERN_REFRESH（hero=）——
         填充完成后广播，在**新内容**上结算
      2. 过滤 `hero is 本人`; 候选 = 本人酒馆中的存活随从实体
         （法术不可被 buff）
      3. 目标 = 当前生命最高者（"Health" = 当前值，SOP §16 item 23;
         平手取更靠左者——稳定 tie-break）
      4. 触发: Buff(target, atk=target.atk, health=target.max_health)——
         "double the stats" = 攻/属性值各 +1 倍（max_health 为属性
         快照，SOP §3）
      5. 酒馆无随从 → 落空; 只作用于本人酒馆

    Test: test_batch_trinkets8.py — 真实 refresh_tavern: 指定入馆的高生命
      随从攻/血各翻倍、低生命随从不翻倍（对照无饰品不翻倍）/ 法术不被
      buff / 对手刷新不影响本人酒馆数值

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_refresh(g, hero=None, auto=False, **kw):
            # 只响应**玩家主动**刷新（"After you Refresh"）——引擎回合
            # 开始的自动刷新与买空自动刷新（auto=True）不计入
            # （RULES §7.4.2; 同文案先例 Frigid Blossom = batch_trinkets7）;
            # 2026-09-02 对抗审查: 旧实现忽略 auto → 每回合白送一次翻倍
            if hero is not h or auto:
                return
            minions = [m for m in h.tavern
                       if isinstance(m, Minion) and not m.dead]
            if not minions:
                return
            best = minions[0]
            for m in minions[1:]:
                if m.health > best.health:
                    best = m
            g.run_actions(Buff(best, atk=best.atk,
                               health=best.max_health))

        game.events.register(Listener(event=TAVERN_REFRESH, owner=source,
                                      callback=on_refresh))
        return None


# ══════════════════ BG35_MagicItem_434 Jewelry Box ══════════════════

class JewelryBoxScript:
    """
    Natural language: Get a <b>Blood Gem</b> that gives a Quilboar
    <b>Taunt</b>, <b>Divine Shield</b>, or <b>Reborn</b>. At the start of
    each turn, repeat this.

    Formal spec:
      1. on_bind: 从三种变体（`actions.bloodgem.BLOOD_GEM_VARIANTS` 的
         taunt/divine_shield/reborn，排序保证 rng 确定性）中
         `game.rng.choice` 取 1 种，`GetBloodGems(hero, 1, variant=…)`
         入手 1 颗（非池 token 不占法术池; 满手排队 RULES §3.3）
      2. start_of_turn（饰品 SoT 钩子）: 同款再取 1 颗——"At the start
         of each turn, repeat this"
      3. 变体关键词仅在**目标为 Quilboar/ALL** 时由 `BG20_GEM_*` 的
         on_play 脚本授予（与卡面 "gives a Quilboar …" 一致）
      4. 只进本人手牌

    Test: test_batch_trinkets8.py — 绑定入手 1 颗血宝石且其 card_id ∈
      三种变体 id / 真实 end_recruit_phase 后再入手 1 颗 / 对手手牌不变 /
      variant 覆盖三种之一（多次绑定采样落在变体集合内）

    Params: count=1（"a Blood Gem" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def _get(h, game):
        variant = game.rng.choice(list(_GEM_KEYWORD_VARIANTS),
                                  label="jewelry_box")
        return GetBloodGems(h, 1, variant=variant)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return JewelryBoxScript._get(h, game)

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return JewelryBoxScript._get(h, game)


# ══════════════════ 注册 ══════════════════

def register() -> list[str]:
    """注册饰品第八批 21 张（无 DEFERRED 注册项——台账见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_982", ShamanPrayerBeadsScript),
        ("BG30_MagicItem_545", FridgeMagnetScript),
        ("BG35_MagicItem_851", WaterWheelScript),
        ("BG36_MagicItem_850", CookiesStirringRodScript),
        ("BG32_MagicItem_930", ArchaicScrollScript),
        ("BG32_MagicItem_171", DivineSignetScript),
        ("BG30_MagicItem_910", MechagonAdapterScript),
        ("BG32_MagicItem_363", FaerieDragonScaleScript),
        ("BG30_MagicItem_886", ReinforcedShieldScript),
        ("BG30_MagicItem_540", SlammaStickerScript),
        ("BG30_MagicItem_978", BlingtronsSunglassesScript),
        ("BG32_MagicItem_301", BassgillPortraitScript),
        ("BG32_MagicItem_306", HeraldStickerScript),
        ("BG36_MagicItem_213", LightfeatherStickerScript),
        ("BG35_MagicItem_752", YoungMurkEyeStickerScript),
        ("BG30_MagicItem_406", ButchersSickleScript),
        ("BG32_MagicItem_831", SellementalPortraitScript),
        ("BG32_MagicItem_415", BattleHornScript),
        ("BG30_MagicItem_973", MinionBaitScript),
        ("BG35_MagicItem_862", UpstartEmbersScript),
        ("BG35_MagicItem_434", JewelryBoxScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
