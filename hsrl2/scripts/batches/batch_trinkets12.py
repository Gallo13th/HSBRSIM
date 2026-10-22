"""批次 trinkets12 — 饰品第十二批（作业单 2026-09-11，台账片 2）。

与 batch_trinkets1..11 的 id 集合互不相交；全部 id 都在
`CardDB.trinket_offer_pool()` 中（含两个带 `t`/`t2` 后缀但**无同名本体**
的独立商店饰品——见下）。数值一律 `CardDef.num(0/1)`（`CardDef` 无参数
而文本含字面量的 +N 类增量按 SOP §3 在各类 `Params:` 行声明为文本权威）。
随机一律 `game.rng`；全部状态写在 hero 作用域 / source 实体属性 / 监听
闭包（无 game 级 flag——SOP §12 item 9）。

关于 `t`/`t2` 后缀的两个 id（作业单要求先判断触发来源）:
  - `BG30_MagicItem_821t2` Fishy Sticker（Greater, school=12）与
    `BG30_MagicItem_821` Fish Portrait（Lesser, school=11）**名字与效果
    完全不同**（Fish Portrait = "Get a Fish of N'Zoth"；Fishy Sticker =
    SoC 召唤金色 Fish of N'Zoth），且 `CardDB.trinket_offer_pool()` 把它
    当作**独立商店本体**提供（`t2` 过滤只排除"有同名本体"的升级变体，
    821t2≠821 名字）。故它不是任何本批饰品的"升级目标"，但仍 DEFERRED
    ——原因见下（金色 Fish 无脚本）。
  - `BG30_MagicItem_843t` Horde Keychain（Greater）在 data 中**没有**
    `BG30_MagicItem_843` 本体（id 段 841→843t→847），是独立商店本体，
    按普通饰品实现。

实现（7 个 id / 7 张饰品）:
  BG30_MagicItem_546  Jar o' Gems        — 每场战斗每 2 个友方随从攻击:
                                           对所有己方野猪人施放鲜血宝石
                                           （计数触发后清零重来）
  BG30_MagicItem_555  Surprise Portrait  — Get Elemental of Surprise
                                           （池随从, 占池）
  BG30_MagicItem_702  Primalfin Portrait — Get Primalfin Lookout;
                                           发现随从后随机一张酒馆法术
  BG30_MagicItem_709  Electromagnetic Device — Discover 磁力机械;
                                           友方随从被磁力时 +3/+3
  BG30_MagicItem_801  Sinstone Sticker   — 每回合前 num(1) 次发现卡牌时
                                           额外获得一张副本
  BG30_MagicItem_821  Fish Portrait      — Get Fish of N'Zoth（token,
                                           其脚本已注册）
  BG30_MagicItem_843t Horde Keychain     — 己方 Tier ≤ 3 随从 +7/+5
                                           （R125 同构的持久化光环等价
                                           实现——见类 docstring 记档）

DEFERRED（本批逐张评估后放弃；每张附具体依赖 + 实现路径，禁止近似）:
  - BG30_MagicItem_548 Glowscale Portrait — "Get a Timewarped Glowscale.
    After you cast a Spellcraft spell, give your minions with Divine
    Shield +{0}/+{1}."。**载荷未就绪**（AGENTS §12 item 14 / SOP §10）:
    关联卡 `BG34_Giant_035` 无脚本，其 Spellcraft 法术
    `BG34_Giant_035t`（"Give a minion Divine Shield"）**亦无脚本**
    （REGISTRY 双缺口，36.2.2 数据核实）→ 交付的 Glowscale 法术塑造
    永远空转。本饰品自身的第二条效果（spellcraft_cast → 圣盾随从
    +3/+3）已可精确实现，但"Get a Timewarped Glowscale"条款交付的是
    一张半空转卡，整卡不满足 CORRECT。Dependency: 先迁
    `BG34_Giant_035t`（定向法术 needs_target + GainKeyword(DIVINE_
    SHIELD)）与 `BG34_Giant_035`（Taunt + on_summon →
    grant_spellcraft_spell）。注: batch_trinkets8 Bassgill Portrait
    授予未注册的 `BG26_350` 是同形先例——若主线裁定"Get X 只要求卡
    本体交付、X 的效果属另一迁移项"，本卡可解冻（脚本逻辑见本条目
    描述，实现路径已给出）。
  - BG30_MagicItem_701 The Eye of Sargeras — "Every fourth card you buy
    costs Health instead of Gold"。引擎只有 CardDef 静态 `health_cost`
    标志（Hasty Excavation），无"按购买次数切换支付方式"的运行时标记与
    消费点。Dependency: `hero._health_buy_counter` + `buy_from_tavern`
    支付分支（同 batch_trinkets8 台账，本批复核仍缺失）。
  - BG30_MagicItem_707 Tickatus Sticker — "Discover a Tier 3 Darkmoon
    Prize. At the start of every three turns, repeat this."。Darkmoon
    Prize 子系统在 `CardDB` 内**零卡池定义/零 tier 映射字段**（`BGS_
    Treasures_*` 34 张全部无脚本、非 `pool_spells`），且"发现一张 Prize
    法术并结算"无协议。Dependency: Prize 卡池 + 精确档位法术发现
    （同 batch_anomalies3:50 / batch_hero_remaining:110 台账）。
  - BG30_MagicItem_711 Marine Signet — "…get a random Tier {1} Tavern
    spell and **improve this**"。数据无升级本体（无 `711t`）、无升级
    tag，`@` 第二段文本（无计数）与 "improve" 的语义（改为可重复触发？
    {1} 递增？）均无权威（wiki 无 Notes；patch 34.2 仅把 "upgrade" 改成
    "improve"）。Dependency: "improve this" 的数值/文本升级协议。
  - BG30_MagicItem_777 Goose Portrait — ✅ 已迁出（2026-09-17，
    batch_goose_lucky_egg）: "Get a Silver Goose. After you summon 3
    Silver Fledglings, get a Lucky Egg."。载荷 `BG29_801` / `BG29_801_G`
    已由 batch_remaining2 注册（2026-09-16）; 次生载荷 `BG30_104`/`_G`
    Lucky Egg 由 batch_goose_lucky_egg 注册（战吼 = 池化发现金色 T3/T4
    后经引擎 `Transform` 变形自身）→ 饰品本体同批注册（计数阈值
    `num(0)=3` + Fledgling token 家族）。
  - BG30_MagicItem_803 Kaboom Bot Portrait — "Get a Kaboom Bot. Your
    Kaboom Bots' Deathrattles deal 10 extra damage."。载荷
    `BG_BOT_606` / `TB_BaconUps_028` Kaboom Bot 已由 batch_remaining2
    注册（2026-09-16，亡语逐实例 `Hit(num(0))`）。残余阻塞: (a) "deal
    10 extra damage" 需要 Kaboom Bot 脚本读取的家族级加成标记（生产
    消费点），引擎/脚本均无; (b) 金色 "twice" 下 10 点是每实例还是总额
    无权威。Dependency: 家族亡语伤害通道 + 金色口径裁定。
  - BG30_MagicItem_804 Ancient Wishbone — "Your Hero Power triggers
    twice"。`game.use_hero_power` 只有每回合次数（`hp_uses` 额度），无
    "效果结算翻倍"钩子（batch_trinkets8 已裁定）。Dependency: 英雄技能
    效果倍率钩子。
  - BG30_MagicItem_821t2 Fishy Sticker — "Start of Combat: Summon a
    Golden Fish of N'Zoth that copies Deathrattles."。金色本体
    `TB_BaconUps_307` **无脚本**（`TB_BaconShop_HP_105t` 已注册、金色
    版没有）→ 召唤出的金色鱼是白板，本饰品效果整体落空。
    Dependency: 先注册 TB_BaconUps_307（或 create_minion 增加金色→本体
    脚本回落——那是引擎改动）。
  - BG30_MagicItem_822 Twin Sky Lanterns — "When you have space, summon
    a copy of the first minion you summon each combat."。XML 无任何触发
    tag（仅 TRIGGER_VISUAL）、wiki 无 Notes；"when you have space" 的
    战斗内腾位触发协议缺失，`combat_summon_log` 只写不读（W3）。
    直译会在每次攻击后补位（SOP §13 item 3 教训: 同类文本曾被实现为
    AFTER_ATTACK 无限补位）。同族 BG30_MagicItem_440 Boom Controller
    亦 DEFERRED。Dependency: 战斗内"腾位"触发协议 + 本战斗首个召唤记录。
  - BG30_MagicItem_825 Smuggler Portrait — "…Set its stats to 12/12.
    **Your Whelp Smugglers are Dragons.**"。种族身份改写（BG21_013
    基础 `race=NONE`→DRAGON）无引擎原语（全仓脚本无 `GameTag.RACE`
    写点；`ApplyRaceAura` 是"对某种族加属性"不是身份改写）。
    ~~且被授予的 Whelp Smuggler 本体亦无脚本~~ **已解冻（2026-09-20）**:
    `stats_gained` 原语落地后 `BG21_013`/`_G` 本体已注册
    （`batch_stats_gained`）→ 本卡残余阻塞**只剩**单值种族身份改写协议
    （batch_trinkets8 Bronzebeard Portrait 同族裁定）。
  - BG30_MagicItem_828 Shaker Portrait — "Your Zesty Shakers give an
    extra copy of the spell."。`ZestyShakerScript`（已注册）把副本数写死
    为 1/金色 2（`num` 分支），无 hero 级"额外副本"读取点；在饰品侧
    重放该触发会绕过其"每回合一次"私有记账（读他脚本私有属性 = SOP
    §12 item 2 禁用）。Dependency: `hero.zesty_shaker_extra_copies` +
    ZestyShakerScript 消费点。
  - BG30_MagicItem_868 Rewinder Portrait — "Get a Soul Rewinder and a
    Wrath Weaver. Your Soul Rewinders also gain Attack."。**两处阻塞**:
    (a) 文本点名**两张**卡，而 `evolution_card_id` 数据链只指向一张
    （BG26_174 Soul Rewinder; 引擎 `trinket_related_card` 单卡协议无法
    表达"Get A and B"——Wrath Weaver 需第二条数据链或文本解析）;
    (b) "also gain Attack" 的加成**数值无数据字段**（文本无数值; XML
    `4185=2` 未被 CardDef 导出，且其语义为"生成卡数 = 2"——
    Bronzebeard Portrait 同为 2、Jewelry Box=1 佐证）; 等于 Health 增量
    （1/金色 2）只是候选读法，无权威。Dependency: 多关联卡数据链 +
    加成数值权威（或 wiki Notes 确认口径）。
  - BG30_MagicItem_869 Felblood Portrait — "Get a Slimy Felblood. Your
    Fiery and Slimy Felbloods give Attack and Health."。`BG29_873`
    Slimy / `BG29_877` Fiery Felblood **均无脚本**（被授予者无战吼/
    亡语），且"give Attack and Health"需要这两个脚本的 TavernBuff 出口
    读取 hero 级标记。Dependency: 先迁 BG29_873/877 + 共享 TavernBuff
    双属性标记。

协议: 饰品实体经 `_offer_trinkets` 购买 / `grant_trinket` 授予 →
`hero.trinkets`；脚本只挂 `on_bind` / `start_of_combat`（接线审计 W1
白名单；本批无 SoT/EoT/avenge）。事件名均为引擎真实 fire: `before_attack`
/ `summon` / `magnetized` / `card_discovered`（PendingChoice.choose 广播）。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff, Discover
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    AFTER_ATTACK,
    SUMMON,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import CardType, Race

# `PendingChoice.choose` 广播的"发现完成"事件（events.py 常量未入册——
# batch_quest_rewards / batch_unfreeze 同款本地常量）
CARD_DISCOVERED = "card_discovered"

# 磁力事件（game.attach_magnetic fire: host=, attached=）
MAGNETIZED = "magnetized"

# 含 All 型的匹配族（Amalgam 规则，RULES §6.4）
_QUILBOAR_RACES = (Race.QUILBOAR, Race.ALL)
_MECH_RACES = (Race.MECH, Race.ALL)

# Horde Keychain "minions from Tier 3 or lower"（文本字面量，无模板参数）
_HORDE_MAX_TIER = 3
# Horde Keychain "+7/+5"（文本字面量，无模板参数）
_HORDE_ATK = 7
_HORDE_HEALTH = 5

# Electromagnetic Device "give it +3/+3"（文本字面量; CardDef 无参数）
_ELECTRO_ATK = 3
_ELECTRO_HEALTH = 3


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


def _random_tavern_spell(game, hero, label: str) -> bool:
    """获得 1 张随机酒馆法术（池感知）。

    tier 口径: `tech_level <= hero.tavern_tier`（与 Holli'dae /
    Mystic Essence / `SpellPool.draw_tavern` 全仓统一，2026-09-02 Yogg
    修复后口径），并经 `Game.tavern_spell_candidates` 施加**存在档
    白名单**（异变 101/102 非存在档法术不可达）。占池 → create_spell →
    pending_hand_add；候选为空 → False（落空）。
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


def _is_minion_def(d) -> bool:
    return d.is_minion or d.card_type == CardType.MINION


def _is_card_def(d) -> bool:
    """`Discover a card` 的卡牌定义域（R129 同款）: 随从 + 法术。

    排除 `dark_gift` 的 card_type 5 非卡牌效果实体（BG36_MidGameEffect_*）
    与英雄技能等非卡实体（由调用方按 kind 排除 dark_gift）。
    """
    return (_is_minion_def(d)
            or d.is_pool_spell
            or d.card_type in (CardType.SPELL, CardType.BACON_SPELL))


# ══════════════════ BG30_MagicItem_546 Jar o' Gems ══════════════════


class JarOGemsScript:
    """
    Natural language: [x]After 2 friendly minions
    attack each combat, this
    plays a <b>Blood Gem</b> on all
    ____your Quilboar. <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: **AFTER_ATTACK**
         （attacker=, defender=）——combat.py 在**伤害与死亡结算之后**
         广播（C4）; 四语文本均为完成态 "After 2 friendly minions
         attack"（zhCN「在2个友方随从攻击后」/deDE "nachdem … angegriffen
         haben"/jaJP「攻撃した後」），同文本先例 Aranna
         `TB_BaconShop_HP_065`（batch_hero_econ3）亦用 AFTER_ATTACK。
         2026-09-02 对抗审查 MAJOR: 旧实现挂 BEFORE_ATTACK → 宝石在该次
         攻击的伤害前落地，实测使 1 血野猪人多打 1 点且本该阵亡却存活
         （翻转战斗结果）。
      2. 条件: `attacker.controller is 本人`、`game.in_combat`
         （"each combat"——招募期攻击不计，RULES §6.11 同族阶段守卫）。
         **不加 `attacker.dead` 守卫**: 攻击已发生必须计数，
         AFTER_ATTACK 对已死亡攻击者照常广播（实测）。
      3. 计数存 source 实体属性 `_jar_attacks`；达 num(0)=2 → 计数清零
         并对**全部己方存活野猪人**（race ∈ QUILBOAR/ALL）各执行
         `PlayBloodGems(m, count=1)`（vanilla 宝石；数值 = `BG20_GEM`
         CardDef.num(0/1) + hero 血宝石加成 tags——action 内权威读取）
      4. **计数触发后清零重来**（同一场战斗可多次触发）: Evidence =
         Blizzard 论坛实测 "it's not even Avenge, it's **attack 2**.
         Nothing even needs to die for it to **proc over and over**."
         （us.forums.blizzard.com/en/hearthstone/t/
         jar-of-gems-needs-tuning/135809）
      5. `start_of_combat` 每场战斗开始把计数归零（"each combat"）
      6. 空场/无野猪人 → 该次落空（计数照常清零——尝试已发生）；只作用
         于本人（对手/对手随从攻击不计数）

    Test: test_batch_trinkets12.py — 战斗内 2 次攻击后恰好己方野猪人
      各 +1/+1 且 GEMS_PLAYED_ON=1（对照无饰品不变）/ 非野猪人不变 /
      4 次攻击触发两次（累计 +2/+2）/ 1 次攻击不触发 / 招募期攻击不
      触发 / 对手攻击不计数 / SoC 钩子后计数重置可再次触发 / 无野猪人
      落空不报错

    Params: count=1（"a Blood Gem" 文本字面量——每次触发 1 颗）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        source._jar_attacks = 0

        def on_attack(g, attacker=None, defender=None, **kw):
            if attacker is None:
                return
            if attacker.controller is not h:
                return
            if not g.in_combat:
                return
            source._jar_attacks += 1
            if source._jar_attacks < threshold:
                return
            source._jar_attacks = 0
            quils = [m for m in _living(h) if m.race in _QUILBOAR_RACES]
            if not quils:
                return
            g.run_actions([PlayBloodGems(m, count=1, source=source)
                           for m in quils])

        game.events.register(Listener(event=AFTER_ATTACK, owner=source,
                                      callback=on_attack))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        source._jar_attacks = 0
        return None


# ══════════════════ BG30_MagicItem_555 Surprise Portrait ══════════════════


class SurprisePortraitScript:
    """
    Natural language: [x]Get an Elemental of
    Surprise. <i>(More appear
    when you least expect
    them...)</i>

    Formal spec:
      1. on_bind: Get an Elemental of Surprise——`game.
         grant_trinket_related_card(hero, 本饰品 id)`（RULES §7.4.6:
         `evolution_card_id`（dbf 101280）→ `db.by_dbf` → `BG26_175`，
         零硬编码卡 id）。36.2.2 数据核实 `is_pool_minion=True`
         （T6 池随从）→ `minion_pool.acquire` 占池（RULES §2.3），池耗尽
         → 落空（返回 False，RULES §2.4）; 出售时按 1 份回池，收支平衡
      2. `BG26_175` 的圣盾关键词与"可与任意元素三连"由引擎内建
         （create_minion 关键词 + 三连子系统），脚本无需介入
      3. 只进本人手牌（满手排队 RULES §3.3）

    Test: test_batch_trinkets12.py — 绑定入手 1 只 BG26_175 且该卡池
      恰好 -1（对照同 seed 无饰品不减少）/ 池耗尽（预取全部副本）时
      落空且不报错 / 对手手牌不变 / 数据链解析 == BG26_175 且
      is_pool_minion

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════════ BG30_MagicItem_702 Primalfin Portrait ══════════════════


class PrimalfinPortraitScript:
    """
    Natural language: [x]Get a Primalfin Lookout.
    After you <b>Discover</b> a
    minion, get a random
    Tavern spell.

    Formal spec:
      1. on_bind: Get a Primalfin Lookout——`game.
         grant_trinket_related_card(hero, 本饰品 id)`（RULES §7.4.6:
         `evolution_card_id`（dbf 60028）→ `db.by_dbf` → `BGS_020`，
         零硬编码卡 id）。36.2.2 数据核实 `is_pool_minion=True` →
         池内有余则占池（RULES §2.3），池耗尽落空
      2. on_bind 注册持久监听器（owner=饰品）: `card_discovered`
         （hero=, option=, kind=）——`PendingChoice.choose` 在 resolve
         回调之后广播（options 为 card_id 字符串时 option=pick）
      3. 条件: `hero is 本人` 且 `option` 是**随从**卡（`_is_minion_def`;
         `dark_gift` 的 card_type 5 效果实体排除）
      4. 触发: `_random_tavern_spell`（tier ≤ 酒馆等级、占法术池、
         create_spell + pending_hand_add）——"get a random Tavern spell"
      5. 法术池空/酒馆等级不足（无候选）→ 该次落空; 发现法术不触发;
         只作用于本人（对手发现不发放）

    Test: test_batch_trinkets12.py — 绑定入手 1 只 BGS_020 且随从池 -1 /
      真实 Discover 三选一选随从后恰好入手 1 张池法术且法术池 -1
      （对照无饰品不入手）/ 发现法术（card_discovered: option=法术 id）
      不发放（同测试内含随从发现正对照）/ 对手发现不发放 / 酒馆等级 0
      （无候选）时落空

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)

        def on_discovered(g, hero=None, option=None, kind=None,
                          golden=False, **kw):
            if hero is not h or not isinstance(option, str):
                return
            if kind == "dark_gift":
                return
            d = g.db.get(option)
            if d is None or not _is_minion_def(d):
                return
            _random_tavern_spell(g, h, "primalfin_portrait")

        game.events.register(Listener(event=CARD_DISCOVERED, owner=source,
                                      callback=on_discovered))
        return None


# ══════════════════ BG30_MagicItem_709 Electromagnetic Device ══════════════


class ElectromagneticDeviceScript:
    """
    Natural language: [x]<b>Discover</b> a <b>Magnetic</b>
    Mech. Whenever a friendly
    minion is <b>Magnetized</b>,
    give it +3/+3.

    Formal spec:
      1. on_bind: `Discover(hero, candidates=<池中磁力机械>)`——候选 =
         `_pool_candidates(race=MECH)`（池剩余量 > 0 / 本局禁用种族 /
         含 Amalgam ALL）再按 `CardDef.keywords` 含 "magnetic" 过滤
         （RULES §6.18 池约束）; 三选项预留语义由 `Discover` Action 处理
         （生成即 acquire、resolve 保留选中释放其余）
      2. on_bind 同时注册持久监听器（owner=饰品）: `magnetized`
         （host=, attached=）——`game.attach_magnetic` 在吸附结算后广播
      3. 条件: `host.controller is 本人`（"a friendly minion"）
      4. 触发: Buff(host, atk=3, health=3)——文本字面量（CardDef 无参数；
         金色升级版 `BG30_MagicItem_709t` 的 +4/+4 不在本批范围）
      5. 池内磁力机械耗尽 → Discover 落空（无选项）; 对手随从被磁力
         不授予; 磁力附着的本体属性并入由 `attach_magnetic` 独立结算

    Test: test_batch_trinkets12.py — 绑定产生 1 个 kind=discover_minion
      三选项发现、选项全为磁力机械且已预留占池（池 -3）/ resolve 后
      选中入手、其余回池（池净 -1）/ 真实 play_minion(magnetic_target=)
      后宿主攻击/生命各 +3/+3（对照无饰品只并入本体属性）/
      对手宿主不被授予（正对照: 本人宿主被授予）/ 磁力池耗尽不建选择

    Params: atk=3 health=3（文本字面量 "+3/+3"——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_magnetized(g, host=None, attached=None, **kw):
            if host is None or host.dead:
                return
            if host.controller is not h:
                return
            g.run_actions(Buff(host, atk=_ELECTRO_ATK,
                               health=_ELECTRO_HEALTH))

        game.events.register(Listener(event=MAGNETIZED, owner=source,
                                      callback=on_magnetized))
        cands = [cid for cid in _pool_candidates(game, Race.MECH)
                 if "magnetic" in game.db.get(cid).keywords]
        if not cands:
            return None
        return Discover(h, candidates=cands, kind="discover_minion")


# ══════════════════ BG30_MagicItem_801 Sinstone Sticker ══════════════════


class SinstoneStickerScript:
    """
    Natural language: [x]The first {1} times you
    <b>Discover</b> a card each turn,
    get an extra copy of it.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `card_discovered`
         （hero=, option=, kind=）
      2. 条件: `hero is 本人`、`option` 是卡牌（随从 / 法术——
         `_is_card_def`; `dark_gift` 的 card_type 5 效果实体排除）
      3. 每回合额度 = num(1)（主句 "The first {1} times"，与文本占位符
         一致; 数据 num(0)==num(1)==2），按 `game.turn` 惰性归零
         （跨回合恢复——"each turn"）
      4. 触发: 额外副本 `game.grant_card_copy_to_hand(hero, d)`（RULES
         §7.4.6 副本协议: 白板副本进手牌，池随从/池法术先 acquire 占池，
         池空则本次落空（RULES §2.4）；非池卡零池操作）+ 满手排队）
      5. 额度用尽/非卡实体（dark_gift）→ 不发放; 池空时副本落空但该次
         额度照常消耗（触发已发生）; 只作用于本人（对手发现不发放）

    Test: test_batch_trinkets12.py — 前 num(1) 次真实随从发现各得 2 张
      （发现本体 + 副本）且池恰好多 -1（副本占池）、第 num(1)+1 次只得
      1 张 / 法术发现也复制（副本是 Spell 且法术池 -1）/ dark_gift 事件
      不复制（同测试内含随从发现正对照）/ 真实推进回合后额度重置可再得
      副本 / 对手发现不得副本（正对照: 本人得）/ 无饰品对照只得 1 张 /
      池耗尽（预取该卡全部副本）时副本落空且不报错

    Params: {0}=2 {1}=2（BG30_MagicItem_801 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        limit = _num(game, source.card_id, 1)
        state = {"turn": None, "n": 0}

        def on_discovered(g, hero=None, option=None, kind=None,
                          golden=False, **kw):
            if hero is not h or not isinstance(option, str):
                return
            if kind == "dark_gift":
                return
            d = g.db.get(option)
            if d is None or not _is_card_def(d):
                return
            if state["turn"] != g.turn:
                state["turn"] = g.turn
                state["n"] = 0
            if state["n"] >= limit:
                return
            state["n"] += 1
            # 金色发现 → 副本同为金色（"an extra copy of it"；
            # 2026-09-02 对抗审查 MINOR: 旧实现恒发基础卡）
            g.grant_card_copy_to_hand(h, d, golden=bool(golden))

        game.events.register(Listener(event=CARD_DISCOVERED, owner=source,
                                      callback=on_discovered))
        return None


# ══════════════════ BG30_MagicItem_821 Fish Portrait ══════════════════


class FishPortraitScript:
    """
    Natural language: Get a Fish of N'Zoth.

    Formal spec:
      1. on_bind: Get a Fish of N'Zoth——`game.
         grant_trinket_related_card(hero, 本饰品 id)`（RULES §7.4.6:
         `evolution_card_id`（dbf 67213）→ `db.by_dbf` →
         `TB_BaconShop_HP_105t`，零硬编码卡 id）。36.2.2 数据核实
         `is_pool_minion=False`（N'Zoth 英雄技能 token）→ 零池操作，
         create_minion + pending_hand_add（满手排队 RULES §3.3）
      2. 该 token 的亡语复制效果由已注册的 `FishOfNZothScript` 提供，
         本饰品只负责授予（"Get a …" 单条款）
      3. 只进本人手牌

    Test: test_batch_trinkets12.py — 绑定入手 1 只 TB_BaconShop_HP_105t
      且随从池不变量不变（token 不占池）/ 对手手牌不变 / 无饰品对照
      不获取 / evolution 数据链解析出该 id

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════════ BG30_MagicItem_843t Horde Keychain ══════════════════


class HordeKeychainScript:
    """
    Natural language: Your minions from Tier 3 or lower have +7/+5.

    Formal spec:
      1. on_bind: `game.add_tier_aura(source, 3, 7, 5)` —— **tier 维度
         光环原语**（2026-09-02 主线补齐，RULES §6.19）。读取点
         `Entity._aura_atk/_aura_health`: 仅作用于本人**棋盘上**
         `tech_level <= 3` 的随从，对任何入板路径（summon / `Transform` /
         Jandice 直接换入）恒生效。
         旧实现（入场即永久 Buff + SUMMON 监听）漏掉非 summon 入板路径，
         已由对抗审查证伪（Transform/Jandice 实测拿不到 +7/+5）。
      2. 生命周期: 光环 source 仍属于该英雄（trinkets/奖励/棋盘）才生效
         → 饰品被替换/移除后自动失效（无需清理钩子）
      3. 数值 +7/+5 与 Tier 阈值 3 均为**文本字面量**（CardDef 无 {0}/{1}
         参数; XML `AURA=1` 无其它数值 tag）
      4. 只作用于本人棋盘（owner 隔离——对手随从不获得）

    Test: test_batch_trinkets12.py — 绑定后 T1/T2/T3 在场随从各 +7/+5、
      T4/T5 不变（对照无饰品全部不变）/ 绑定后新召唤 T2 随从立即
      +7/+5（打出路径真实 summon）/ 对手 T2 随从不变（正对照: 本人
      获得）/ 无饰品对照不变

    Params: atk=7 health=5（文本字面量 "+7/+5"——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # tier 维度光环: 本人棋盘上 tech_level <= 3 的随从恒 +7/+5
        game.add_tier_aura(source, _HORDE_MAX_TIER, _HORDE_ATK,
                           _HORDE_HEALTH)
        return None


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    """注册饰品第十二批 7 张（DEFERRED 台账见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_546", JarOGemsScript),
        ("BG30_MagicItem_555", SurprisePortraitScript),
        ("BG30_MagicItem_702", PrimalfinPortraitScript),
        ("BG30_MagicItem_709", ElectromagneticDeviceScript),
        ("BG30_MagicItem_801", SinstoneStickerScript),
        ("BG30_MagicItem_821", FishPortraitScript),
        ("BG30_MagicItem_843t", HordeKeychainScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
