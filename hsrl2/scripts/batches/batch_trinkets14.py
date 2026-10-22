"""批次 trinkets14 — 饰品第十四批: 片 2/3 交界 20 张（作业单 2026-09-12）。

与 batch_trinkets1..13 / 16 的 id 集合互不相交（台账片 2 尾 + 片 3 头:
BG32_MagicItem_179 … BG32_MagicItem_416）。全部 id 均为
`CardDB.trinket_offer_pool()` 中的**商店本体**（运行核验 20/20; 无
`t`/`t2` 升级变体、无纯 token）。数值一律 `CardDef.num(0/1/2)`
（`CardDef` 无参数而文本含字面量的 +N 类增量按 SOP §3 在各类
`Params:` 行声明为文本权威）; 关联卡一律走数据链
`CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6，零硬编码
卡 id）; 随机一律 `game.rng`; 全部状态写在 hero 作用域 / source 实体
属性 / 监听闭包（无 game 级 flag——SOP §12 item 9）。

实现 9 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG32_MagicItem_200  All-Purpose Kibble   — 友方野兽攻击时 +num(0) 攻击，
                                             每次触发后永久 improve
                                             （增量 = 印面值 num(0)）
  BG32_MagicItem_230  Extravagant Scale    — 累计花掉 num(0)=20 金时
                                             友方全员攻击翻倍; 每局
                                             num(2)=2 次
  BG32_MagicItem_232  Shark Cannon         — 累计花掉 num(0)=10 金时
                                             海盗 +num(2)/+num(2) 并
                                             永久 improve（滚动计数）
  BG32_MagicItem_278  Reusable Batteries   — 每回合首次购买随从时获得
                                             一张属性等于该随从的
                                             Magnetic Satellite
  BG32_MagicItem_279  Tough Tusk Sticker   — **从手牌打出**的血宝石使
                                             目标获得圣盾直到下回合
  BG32_MagicItem_282  Turbocharged Drill   — Get num(0)=5 张互异的
                                             Magnetic Mech（任意档位）
  BG32_MagicItem_361  Portable Factory     — Discover 一张带类型的 T4
                                             随从; 每回合开始再获得一张
                                             同卡副本
  BG32_MagicItem_362  Innkeeper's Hearth   — Discover 一张本档随从并
                                             把属性设为 12/12
  BG32_MagicItem_364  Poet Portrait        — Get a Timewarped Poet

DEFERRED 11 张（逐张评估后放弃；不注册，附具体缺失依赖 + 实现路径）
═══════════════════════════════════════════════════════════════════════
  - BG32_MagicItem_179 Drakkari Portrait — "Get a Drakkani Enchanter.
    Your Drakkari Enchanters are both Mechs and Elementals."
    **阻塞后半句**: 多/双种族**身份改写**无引擎原语。`GameTag.RACE`
    是单值 tag；`Race.ALL` 语义是"匹配一切种族查询"而非"同时是机械与
    元素"（会把全部种族查询一并匹配 = 近似，SOP §6b 禁止）。同缺口已由
    batch_trinkets8 / batch_trinkets11 / batch_trinkets13（Bronzebeard
    Portrait / Enforcer Portrait）备案。实现路径: 新增多值种族集合
    （`RACES` set tag 或位掩码）+ 全部 `race` 查询读取点统一改造后，
    在 on_bind 为本人的 Drakkari Enchanter 实例追加 MECH/ELEMENTAL。
    在此之前整卡 DEFERRED（"Get a Drakkari Enchanter" 单独可交付，但
    半实现 = 第三态）。
  - BG32_MagicItem_204 Kel'Thuzad Portrait — "Get an Archlich
    Kel'Thuzad. After you destroy a minion outside combat, give your
    minions +2/+2."
    **阻塞触发条款**: 引擎无"摧毁（Destroy）"事件——`game.events` 只有
    `death`（载荷仅 `minion=`，无来源方/无摧毁标记）; 招募期真实死亡
    来源不止 Destroy（自伤技能 / 伤害类 AoE 也会 death），且无法判定
    "you destroy"（施动者）。用 `death` + `not game.in_combat` 近似会把
    非 Destroy 死亡一并计入（SOP §6b 禁止）（2026-09-02 已落地）。实现路径: 摧毁路径统一走
    `game.destroy_minion(hero, target)` 并 fire
    `minion_destroyed(hero=, minion=, in_combat=)` → 本卡监听该事件。
    关联卡 `BG28_308` Archlich Kel'Thuzad 本身也未注册（非池卡）——
    但触发条款是独立的第一阻塞，先修触发协议再评估。
    Status: 已由 batch_trinkets24 注册（minion_destroyed/destroy_minion 原语已于 2026-09-02 落地）
  - BG32_MagicItem_205 Maw Caster Portrait — "Get a Maw Caster.
    Whenever you destroy a minion outside combat, gain {0} Gold."
    同 204 的 `minion_destroyed` 缺口（数值 {0}=num(0)=2 已就绪）（2026-09-02 已落地）。
    实现路径: 同 204; 触发后 `GainGold(hero, num(0))`。
    Status: 已由 batch_trinkets24 注册（minion_destroyed/destroy_minion 原语已于 2026-09-02 落地）
  - BG32_MagicItem_274 Bristlebach Portrait — "Get a Bristlebach.
    Your Bristlebachs play Blood Gems on all friendly minions."
    **载荷未就绪**（SOP §12 item 14）: 关联卡 `BG26_157` Bristlebach
    **未注册**（REGISTRY 无此 id），其本体 "Avenge (2): This plays 2
    Blood Gems on all your Quilboar" 无脚本 → 授予的 Bristlebach 永不
    触发 Avenge，本饰品"改为作用于全体友方"的改写对象不存在。
    实现路径: (a) 先迁 `BG26_157`（Avenge 阈值 2 + `PlayBloodGems`）;
    (b) 让该脚本读取 hero 级"目标范围改为全体友方"标记（需引擎侧存在
    读取点以满足 W3）并按标记选择目标集合。RULES §7.4.6 例外条款
    （本卡效果依赖被授予卡的行为）→ 整卡维持 DEFERRED。
  - BG32_MagicItem_280 Eclectic Shrine — "Start of Combat: Give a
    friendly minion of each different type +{0}/{1}. Improve this
    permanently."
    **两处无权威读法**（batch_trinkets7 / batch_trinkets8 台账已备案，
    本批复核维持）: (a) All 型（Amalgam）随从是否可对每个类型各获得
    一次同一 buff（"each different type" 的资格集口径）; (b) "improve
    this permanently" 的递增发生在首次触发**前**还是**后**（{0}/{1}=
    3/2 是唯一数值字段）。两条均无 wiki Notes / 官方说明。实现路径:
    官方实测或 wiki 裁定后，SoC 钩子按类型取随机一只 + 永久计数器递增。
    Status: 已由 batch_trinkets24 注册（两处历史 AMBIGUOUS 已由仓内既有先例裁定，2026-09-02 落地）
  - BG32_MagicItem_283 Czarina Portrait — "Get a Charging Czarina.
    Your Charging Czarinas also give Health."
    **阻塞一（载荷行为不可扩展）**: 关联卡 `BG28_741` 已注册，其
    `ChargingCzarinaScript.on_summon` 在 `TAVERN_SPELL_CAST` 时对带圣盾
    随从各 `Buff(atk=d.num(0))`——只给 Attack，且不读取任何 hero 级
    加成通道。饰品无法在不改兄弟批次脚本的前提下让该随从"也给 Health"
    （在饰品侧另注册监听 = 与"由 Charging Czarina 给"的归属不符，且
    Czarina 被出售后仍生效 = 近似）。
    **阻塞二（数值无权威）**: "also give Health" 的 Health 增量在本饰品
    CardDef 中无任何模板参数（num 全 None），wiki 无 Notes。
    实现路径: (a) `BG28_741` 脚本增读 `hero._czarina_bonus_health`
    （引擎/该脚本的读取点）并在 Buff 时一并给 Health; (b) 补 Health 增量
    的数据权威（实测/官方）。在此之前整卡 DEFERRED。
  - BG32_MagicItem_286 Lavish Cape — "Cast a random Tavern spell for
    each different friendly minion type. At the start of each turn,
    repeat this."
    **已解锁（2026-09-02）**: 由 `batch_trinkets21.LavishCapeScript` 注册
    ——`Game.cast_spell_effect`（RULES §7.4.7b）+ 只读候选
    `game.tavern_spell_candidates(min_tier=1, max_tier=hero.tavern_tier,
    pool_aware=False)`（含存在档白名单）
    + 按"不同友方 race 数"决定施放次数。

  - BG32_MagicItem_300 Putricide Sticker — "Craft a custom Undead."
    **子系统缺失**: "Craft" 是 Putricide 的多步部件合成选择链（种族 +
    关键词 + 属性逐项选择，产出 `BG25_HERO_100pt` Putricide's Creation
    类 token）——全仓无 Craft 选择链实现（无多步 PendingChoice 链协议、
    无部件数据表、无产物模板）。实现路径: 需先定义 Craft 步骤数据
    （种族集/关键词集/属性档）+ 引擎支持"连续 N 次选择后合成"的
    PendingChoice 链（可参考 `target_count=2` 的链式选择实现模式）。
    实现前整卡 DEFERRED（详见类 docstring）。

  - BG32_MagicItem_350 Splinter of Aurum — "After you gain Gold, gain
    {0} more." **阻塞**: 引擎只有 `gold_spent`（支出）观察点，**收入
    路径不广播事件**（回合基础收入 / 售卖 / 卡牌给金都无 `gold_gained`）。
    实现路径: `spend_gold` 的对称入口（`gain_gold`/`GainGold` action +
    `gold_gained` 事件）落地后监听之。实现前整卡 DEFERRED。
  - BG32_MagicItem_366 Guiding Candle — 需"某个额外展示位**恰好**从
    tier+1 抽取"的精确档位协议（`hero._tavern_offer_tier_exact`）:
    `TAVERN_OFFER_MOD` 只加通用位、`refresh_tavern` 抽取上界恒为
    `hero.tavern_tier`。与 innkeeper's Stein `BG30_MagicItem_423` 同缺口
    （RULES §7.4.2 / ENGINE_BACKLOG §A7）。实现前整卡 DEFERRED。
  - BG32_MagicItem_416 War Drum — 36.2.2 权威文本: "One Battlecry each
    turn triggers **two** extra times. ({0} left!)"（num(0)=1 / num(1)=2）。
    **已解锁（2026-09-02）**: 引擎新增 `bc_first`（每回合前 N 个战吼）+
    `bc_first_times`（每次额外触发几次，RULES §6.20）→ 由
    `batch_trinkets21.WarDrumScript` 注册（`bc_times` 为永久全量，
    不得复用）。

关联卡台账（RULES §7.4.6 "Get a X" 裁定）
═══════════════════════════════════════════════════════════════════════
  - BG32_MagicItem_364 Poet Portrait → `BG34_Giant_314` Timewarped Poet
    （dbf 127441）: **关联卡未迁移**（REGISTRY 无此 id，非池卡
    `is_pool_minion=False`）。本饰品只负责交付白板副本（零池操作），
    不依赖该卡的行为（其 "All your Dragons keep Bonus Keywords and
    stats gained in combat" 是那张卡的迁移项）→ 按 §7.4.6 裁定
    **CORRECT**（先例: Bassgill Portrait BG32_MagicItem_301）。
  - BG32_MagicItem_205 Maw Caster Portrait → `BG32_340` Maw Caster
    （已注册）; BG32_MagicItem_274 → `BG26_157`（**已注册**——batch_trinkets34 迁本卡）;
    BG32_MagicItem_283 → `BG28_741`（已注册）; BG32_MagicItem_179 →
    `BG26_ICC_901`（已注册）; BG32_MagicItem_204 → `BG28_308`（未注册，
    非池卡）。以上 5 张因本卡自身触发/改写条款阻塞而整卡 DEFERRED
    （见上），与关联卡迁移状态无关。
    Status: BG32_MagicItem_204 / BG32_MagicItem_205 已由 batch_trinkets24 注册（minion_destroyed/destroy_minion 原语已于 2026-09-02 落地）

接线审计读取点（W1/W2/W3 核对）: 饰品仅分发 `on_bind` /
`start_of_turn`（W1 白名单）; 监听事件名均为引擎真实 fire:
`before_attack`（combat.py L264）、`gold_spent`（game.py spend_gold）、
`minion_bought`（buy_from_tavern）、`spell_resolving`
（_finish_play_spell）、`card_discovered`（PendingChoice.choose）、
`turn_start`（_begin_recruit_for）。无 game 级私有标记（SOP §12 item 9）。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff, Discover, GainKeyword, LoseKeyword
from hsrl2.actions.bloodgem import BLOOD_GEM_VARIANTS
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    BEFORE_ATTACK,
    GOLD_SPENT,
    MINION_BOUGHT,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# ── 常量（卡 id 身份标识 / 文本字面量，非数值权威）──

# Satellite token 裁定（batch_magnetic / batch_consume 已核定）:
# BG31_171t def 6/6 是**视觉快照**，实际属性由生成卡参数动态覆盖
# （Beetle 系先例）。Reusable Batteries "with its stats" 即覆盖其属性。
SATELLITE_ID = "BG31_171t"

# 文本字面量（CardDef 无对应模板参数，SOP §3 允许并在此声明）
INNKEEPERS_HEARTH_STAT = 12      # "Set its stats to 12/12"
PORTABLE_FACTORY_TIER = 4        # "Discover a Tier 4 minion"

# 含 All 型的匹配族（Amalgam 规则，RULES §6.8 匹配语义）
_BEAST_RACES = (Race.BEAST, Race.ALL)
_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_MECH_RACES = (Race.MECH, Race.ALL)

# 血宝石法术 id 集合（"played from your hand" 判别; bloodgem 权威）
_BLOOD_GEM_IDS = frozenset(BLOOD_GEM_VARIANTS.values())

# `PendingChoice.choose` 广播的"发现完成"事件（events.py 未入册常量，
# batch_trinkets12 / batch_quest_rewards 同款本地常量）
_CARD_DISCOVERED = "card_discovered"

# 本批自定义发现 kind（须以 "discover" 前缀走引擎 card_discovered 广播）
PORTABLE_FACTORY_KIND = "discover_portable_factory"
INNKEEPERS_HEARTH_KIND = "discover_innkeepers_hearth"


def _hero(ctx):
    return ctx.get("hero") if ctx else None


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _grant_related(game, hero, source, count: int = 1) -> bool:
    """`game.trinket_related_card` 数据链 ×count 进手牌（"Get a <卡>"）。

    RULES §7.4.6: `evolution_card_id` → `db.by_dbf`; 池记账与满手排队由
    `grant_card_copy_to_hand` 统一负责。返回是否至少授予 1 张。
    """
    granted = False
    for _ in range(count):
        if game.grant_trinket_related_card(hero, source.card_id):
            granted = True
    return granted


def _set_stats(target: Minion, atk: int, health: int) -> None:
    """覆盖式设定属性（"Set its stats to X/Y" 家族，batch_spells2 先例）:
    附魔全部剥离、BASE_ATK/BASE_HEALTH 覆盖、当前 HEALTH 同步。"""
    for b in list(target.buffs):
        target.remove_buff(b)
    target.set(GameTag.BASE_ATK, atk)
    target.set(GameTag.BASE_HEALTH, health)
    target.set(GameTag.HEALTH, health)


def _grant_keyword_until_next_turn(game, target: Minion, tag: GameTag) -> None:
    """授予关键词并在目标控制者的下一个招募阶段开始回收。

    对齐 `scripts/spells.py::_expire_at_next_turn`（"until next turn" =
    下一个招募阶段开始，RULES §6.13）。**仅在目标此前未持有时调用**
    （"give" 对已持有者无净变化，也不得回收目标自带的永久关键词）。
    owner=target（离场自动注销），once=True + 控制者条件（其他英雄的
    turn_start 不消耗 once）。
    """
    def _on_turn_start(g, hero=None, **kw):
        g.run_actions(LoseKeyword(target, tag))

    game.events.register(Listener(
        event=TURN_START, owner=target, once=True,
        condition=lambda hero=None, **kw: hero is target.controller,
        callback=_on_turn_start,
    ))


# ══════════════ BG32_MagicItem_200 All-Purpose Kibble ══════════════

class AllPurposeKibbleScript:
    """
    Natural Language: [x]Whenever a friendly Beast
    attacks, give it +{0} Attack
    and permanently improve
    this.

    Formal Spec:
      1. on_bind 注册持久 BEFORE_ATTACK 监听器（owner=饰品）: 引擎在
         攻击宣告、伤害结算**前**广播（combat.py L264，载荷
         attacker=, defender=——Jar o' Gems 同款判别点）
      2. 条件: `attacker.controller is 本人` ∧ `not attacker.dead` ∧
         `attacker.race ∈ (BEAST, ALL)`（"friendly Beast"; Amalgam
         规则）; 文本无 "each combat" → **不设 in_combat 守卫**
         （招募期攻击 Fishbait 路径同样计入"attacks"，与 Roaring
         Recruiter AFTER_ATTACK 家族同口径）
      3. 触发: `Buff(attacker, atk=bonus)`（仅攻击，无生命）; 随后
         `bonus += num(0)`——"permanently improve this" = 每次触发后
         数值永久递增，增量 = 印面值（"Improve" 家族口径: Tumbling
         Disaster / Lurking Leviathan 先例）。跨回合/跨战斗累积
         （状态在饰品闭包，未随战斗快照回滚）
      4. 只作用于本人（对手野兽攻击不触发）
      5. 无友方野兽攻击 → 无任何状态变化（正对照）

    Test: test_batch_trinkets14.py — 首次攻击 +num(0)、第二次增量
      +2×num(0)（累计 +3×num(0)，improve 正对照）/ 非野兽不触发 /
      对手野兽攻击不触发且本人 bonus 不推进

    Params: {0}=num(0)（36.2.2 基线 2）; improve_step=num(0)
            （"improve this" 无独立参数 → 增量 = 印面值）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        step = _num(game, source.card_id, 0)
        state = {"bonus": step}

        def on_attack(g, attacker=None, defender=None, _h=h, _src=source,
                      **kw):
            if attacker is None or attacker.dead:
                return
            if attacker.controller is not _h:
                return
            if _src not in _h.trinkets:
                return
            if attacker.race not in _BEAST_RACES:
                return
            g.run_actions(Buff(attacker, atk=state["bonus"]))
            state["bonus"] += step

        game.events.register(Listener(event=BEFORE_ATTACK, owner=source,
                                      callback=on_attack))
        return None


# ══════════════ BG32_MagicItem_230 Extravagant Scale ══════════════

class ExtravagantScaleScript:
    """
    Natural Language: [x]When you spend 20 Gold,
    double your minions'
    Attack. <i>(Twice per game.)</i>

    Formal Spec:
      1. on_bind 注册持久 GOLD_SPENT 监听器（owner=饰品）: 引擎
         `spend_gold` 每次支出广播（载荷 amount=, hero=）
      2. 阈值 = num(0)=20（文本 "{0}" 显示值同源; XML NUM_1=20）;
         次数上限 = num(2)=2（"Twice per game."; XML
         `TAG_SCRIPT_DATA_NUM_3`=2，CardDef.num(2) 权威）
      3. 累计器 `p` 跨回合累积（"counts all gold towards its
         activation"——Shark Cannon 官方 bugfix 同口径）;
         `while p >= 阈值 and used < 上限:` `p -= 阈值` → `used += 1`
         → 本人棋盘全部存活随从 `Buff(atk=m.atk)`（"double" = 当前
         攻击翻倍，增量 = 快照当下当前攻击）; 快照先取列表再逐个施
         （避免遍历中队列解析改动棋盘）
      4. 达上限后不再累计/触发（"Twice per game" 是硬上限）; 只对本人
         支出生效（对手支出不计数）
      5. 招募期内属性增益永久（非战斗 buff）

    Test: test_batch_trinkets14.py — 累计 num(0)-1 金不触发 / 第
      num(0) 金全员攻击翻倍 / 第二次翻倍后再花满触发第三次（正对照）
      却被 num(2) 上限拦住 / 对手支出不触发 / 空场落空不报错

    Params: {0}=num(0)=20 {2}=num(2)=2（BG32_MagicItem_230）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        uses_max = _num(game, source.card_id, 2)
        state = {"p": 0, "used": 0}

        def on_spent(g, hero=None, amount=0, _h=h, _src=source, **kw):
            if hero is not _h or amount <= 0:
                return
            if _src not in _h.trinkets:
                return
            if state["used"] >= uses_max:
                return
            state["p"] += amount
            while state["p"] >= threshold and state["used"] < uses_max:
                state["p"] -= threshold
                state["used"] += 1
                board = _living(_h)
                g.run_actions([Buff(m, atk=m.atk) for m in board])

        game.events.register(Listener(event=GOLD_SPENT, owner=source,
                                      callback=on_spent))
        return None


# ══════════════ BG32_MagicItem_232 Shark Cannon ══════════════

class SharkCannonScript:
    """
    Natural Language: [x]After you spend {4} Gold,
    give your Pirates
    +{2}/+{2} and improve
    this. <i>({0} Gold left!)</i>

    Formal Spec:
      1. 数值（36.2.2 数据核实）: 阈值 = num(0)=10（文本 `{0}` 计数器
         与 `{4}` 门槛同值——XML `TAG_SCRIPT_DATA_NUM_1=10` /
         `_NUM_5=10`; CardDef 只导出 num(0..3)，故取 num(0) 作门槛，
         与 wiki 卡面 "After you spend 10 Gold ... (10 Gold left!)"
         一致）; 单次增益 = num(2)=1（`{2}/{2}`）
      2. on_bind 注册持久 GOLD_SPENT 监听器（owner=饰品）: 累计器
         `p` 跨回合累积（官方 "Shark Cannon now correctly counts all
         gold towards its activation"——2025-05-16 bugfix）;
         `while p >= 阈值:` `p -= 阈值` → 全体本人海盗
         （race ∈ (PIRATE, ALL)）`Buff(atk=bonus, health=bonus)` →
         `bonus += num(2)`（"improve this" 增量 = 印面值）
      3. 滚动清零（"({0} Gold left!)" 每轮从阈值重新倒数）+ 单次大额
         支出可跨多边界（Fancy Spellbook / Gunpowder Courier 同款
         取模口径）
      4. 无海盗 → 该轮落空但**计数照常推进**（尝试已发生，improve 仍
         生效——"improve this" 绑定的是支出行为而非命中）
      5. 只对本人支出生效

    Test: test_batch_trinkets14.py — 累计 num(0)-1 金不触发 / 第
      num(0) 金海盗 +num(2)/+num(2)（非海盗不变）/ 第二个 num(0)
      金 +2×num(2)（improve 正对照）/ 一次 2×num(0) 金连触发两轮 /
      无海盗仍 improve（对照: 之后有海盗时吃 2×num(2)）/ 对手支出不触发

    Params: {0}=num(0)=10 {2}=num(2)=1（BG32_MagicItem_232）;
            improve_step=num(2)
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        step = _num(game, source.card_id, 2)
        state = {"p": 0, "bonus": step}

        def on_spent(g, hero=None, amount=0, _h=h, _src=source, **kw):
            if hero is not _h or amount <= 0:
                return
            if _src not in _h.trinkets:
                return
            state["p"] += amount
            while state["p"] >= threshold:
                state["p"] -= threshold
                bonus = state["bonus"]
                g.run_actions([
                    Buff(m, atk=bonus, health=bonus)
                    for m in _living(_h) if m.race in _PIRATE_RACES])
                state["bonus"] += step

        game.events.register(Listener(event=GOLD_SPENT, owner=source,
                                      callback=on_spent))
        return None


# ══════════════ BG32_MagicItem_278 Reusable Batteries ══════════════

class ReusableBatteriesScript:
    """
    Natural Language: [x]The first time you buy a
    minion each turn, get a
    <b>Magnetic</b> Satellite with
    its stats.

    Formal Spec:
      1. on_bind 注册持久 MINION_BOUGHT 监听器（owner=饰品）: 引擎在
         `buy_from_tavern` 成交并入 `hero.add_to_hand` 之后广播
         （载荷 minion=; `entity.controller` = 购买者）
      2. 每回合仅第一次: 闭包标记 `state["done"]`，由 `start_of_turn`
         （饰品 SoT 钩子，`_begin_recruit_for` 每回合分发）清零——
         与引擎 `FREE_*_BUYS_THIS_TURN` 的"每回合配额由脚本在
         on_bind/start_of_turn 写入"口径一致（RULES §7.4.4）
      3. 触发: 创建 `BG31_171t` Satellite（token，非池卡 → **零池
         操作**），属性覆盖为**被购随从的属性**（BASE/当前同步:
         atk=bought.atk、health=bought.max_health——"with its stats"，
         复制属性口径按 max_health）+ `pending_hand_add` 入手
         （满手排队 RULES §3.3）
      4. 只对本人购买生效（对手购买不计入、不授予）
      5. Satellite 本体无脚本（纯 Magnetic 关键词），属性来自生成参数
         （Beetle 系先例）

    Test: test_batch_trinkets14.py — 首次购买后手牌多 1 张 Satellite
      且属性 == 被购随从 / 同回合第二次购买**不再**授予（一次性正
      对照）/ 真实 `_begin_recruit_for` 后再次授予 / 对手购买不授予 /
      池可用量不变（token 零池）

    Params: satellite_id=BG31_171t（token 身份，batch_magnetic 裁定）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        state = {"done": False}

        def on_bought(g, minion=None, _h=h, _src=source, **kw):
            if minion is None or minion.controller is not _h:
                return
            if _src not in _h.trinkets:
                return
            if state["done"]:
                return
            if g.db.get(SATELLITE_ID) is None:
                return
            state["done"] = True
            atk = minion.atk
            health = minion.max_health
            sat = g.create_minion(SATELLITE_ID, controller=_h)
            sat.set(GameTag.BASE_ATK, atk)
            sat.set(GameTag.BASE_HEALTH, health)
            sat.set(GameTag.HEALTH, health)
            g.pending_hand_add(_h, sat)

        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        source._reusable_batteries_state = state
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        state = getattr(source, "_reusable_batteries_state", None)
        if state is not None:
            state["done"] = False
        return None


# ══════════════ BG32_MagicItem_279 Tough Tusk Sticker ══════════════

class ToughTuskStickerScript:
    """
    Natural Language: <b>Blood Gems</b> played
    from your hand give minions
    <b>Divine Shield</b> until
    next turn.

    Formal Spec:
      1. on_bind 注册持久 `spell_resolving` 监听器（owner=饰品）:
         该事件在**手牌施放路径**每 cast 一次广播
         （`_finish_play_spell`，携带 spell=, target=, cast_no=），
         而 `PlayBloodGems` 直施路径**不** fire —— 正是 "played
         **from your hand**" 的精确判别点（Surveyor Portrait
         BG30_MagicItem_943 同款协议）
      2. 条件: `spell.card_id ∈ BLOOD_GEM_VARIANTS.values()`（vanilla +
         DS/Reborn/Taunt 三个变体共 4 张）∧ `spell.controller is 本人`
         ∧ `target` 是存活 Minion
      3. 触发: 目标获得 `DIVINE_SHIELD`（已持有则不改动、也**不**注册
         过期——"give" 对已持有者无净变化）; 该关键词在目标控制者的
         **下一个招募阶段开始**回收（"until next turn"，RULES §6.13，
         `_grant_keyword_until_next_turn`）
      4. 每颗手牌宝石各结算一次（同回合连打两颗：第一颗注册过期，
         第二颗见已持有不重复注册，过期仍恰在下一回合开始）
      5. 只作用于本人手牌宝石（对手手牌宝石不触发）

    Test: test_batch_trinkets14.py — 手牌 play_spell 血宝石后目标带
      圣盾（对照无饰品不带）/ 直施 `PlayBloodGems` **不**给圣盾
      （"from your hand" 判别，正对照: 同局面手牌路径确实给）/
      下一回合开始（`_begin_recruit_for`）圣盾消失 / 自带圣盾目标
      过期后仍保留（不误删永久关键词）/ 对手手牌宝石不影响本人随从

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_resolving(g, spell=None, target=None, _h=h, _src=source,
                         **kw):
            if spell is None or spell.controller is not _h:
                return
            if spell.card_id not in _BLOOD_GEM_IDS:
                return
            if not isinstance(target, Minion) or target.dead:
                return
            had = target.has(GameTag.DIVINE_SHIELD)
            if had:
                return
            g.run_actions(GainKeyword(target, GameTag.DIVINE_SHIELD))
            _grant_keyword_until_next_turn(
                g, target, GameTag.DIVINE_SHIELD)

        game.events.register(Listener(event="spell_resolving", owner=source,
                                      callback=on_resolving))
        return None


# ══════════════ BG32_MagicItem_282 Turbocharged Drill ══════════════

class TurbochargedDrillScript:
    """
    Natural Language: Get {0} different
    <b>Magnetic</b> Mechs of ANY Tier.

    Formal Spec:
      1. on_bind: 候选 = `CardDB.pool_minions()` 中带 `magnetic` 关键词
         ∧ race ∈ (MECH, ALL) ∧ `minion_pool.available > 0` ∧ 未被
         本局禁用种族（与 Scrap Scraper `GetRandomMagneticMechs` 同一
         口径 + `_pool_candidates` 的 active_races 语义）;
         `tech_level <= game.max_tavern_tier`（"ANY Tier" = 不受酒馆
         等级限制的**池内全档位**; 标准局上限 6 与引擎
         `_pool_candidates` 缺省一致——36.2.2 池内 magnetic mech 全部
         ≤ T4，故该上限不影响结果）
      2. "different" = `game.rng.sample` 无放回取 num(0)=5 张互异
         （不足则全给）; 逐张 `grant_card_copy_to_hand`（池随从先
         `acquire` 占池、池空落空; 满手排队）
      3. 返回授予张数（落空不补偿）; 只作用于本人
      4. 零硬编码卡 id（关键词 + 种族过滤，数据驱动）

    Test: test_batch_trinkets14.py — 手牌恰多 num(0) 张且互异、全部
      magnetic + MECH/ALL / 池可用量对应减少（占池）/ 对手手牌不变 /
      无候选（本局禁用机械）时无操作 + 正对照（恢复后 duplicate 授予）

    Params: {0}=num(0)=5（BG32_MagicItem_282）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        count = _num(game, source.card_id, 0)
        cands = _magnetic_mech_candidates(game)
        if not cands:
            return None
        picks = game.rng.sample(cands, min(count, len(cands)),
                                label="turbocharged_drill")
        for cid in picks:
            game.grant_card_copy_to_hand(h, game.db.get(cid))
        return None


def _magnetic_mech_candidates(game) -> List[str]:
    """池内可获取的 Magnetic Mech card_id（数据驱动，按 id 排序）。"""
    pool = game.minion_pool
    max_tier = game.max_tavern_tier
    out = []
    for d in game.db.pool_minions():
        if "magnetic" not in d.keywords:
            continue
        if d.race not in _MECH_RACES:
            continue
        if d.tech_level > max_tier:
            continue
        if pool.available(d.id) <= 0:
            continue
        if (pool.active_races is not None
                and d.race not in (Race.NONE, Race.ALL)
                and d.race not in pool.active_races):
            continue
        out.append(d.id)
    return sorted(out)


# ══════════════ BG32_MagicItem_361 Portable Factory ══════════════

class PortableFactoryScript:
    """
    Natural Language: [x]<b>Discover</b> a Tier 4 minion
    with a type. At the start
    of each turn, get another
    copy of it.

    Formal Spec:
      1. on_bind 注册持久 `card_discovered` 监听器（owner=饰品;
         `PendingChoice.choose` 在 resolve 后广播，携带 kind=, hero=,
         option=被选 card_id——引擎唯一"发现完成"事件）: 过滤
         `kind == f"{PORTABLE_FACTORY_KIND}:{source.uuid}"` ∧ `hero is 本人`
         → 记入 `source._portable_factory_pick`（**实例级 kind**:
         两份副本各自只认自己开出的发现——同 kind 会让两份 pick 互相覆盖，
         2026-09-02 对抗审查 MAJOR）
      2. on_bind 立即 `Discover(本人, candidates=…)`——候选 =
         `_pool_candidates(min_tier=4, max_tier=4)` ∩ race ≠ NONE
         （"with a type": 无类型随从排除; Amalgam(Race.ALL) 视为有
         类型）; 引擎负责预留/释放池记账（RULES §6.18）与 kind 广播
      3. start_of_turn（饰品 SoT 钩子，每回合开始）: 已有选中卡时
         `grant_card_copy_to_hand`（池随从 acquire 占池、池空落空、
         满手排队）——"get another copy of it"（白板副本）
      4. 尚未完成发现（pick 未记）→ SoT 无操作（正对照落空）
      5. 只作用于本人发现

    Test: test_batch_trinkets14.py — 绑定后产生 Discover 且选项全为
      带类型 T4 / 选定后本人手牌含该卡 / 下回合开始再得一张同卡
      （池可用量对应减少）/ 对手回合开始不授予 / 未选定时 SoT 无操作
      （落空） + 选定后正对照

    Params: tier=4（"Tier 4"，文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        # **实例级 kind**（2026-09-02 对抗审查 MAJOR）: 同一英雄可同时持有
        # 两份 Portable Factory（Crystal Ball 副本条款 / duplicate 授予）——
        # 若两份监听器共用同一个 `kind`，每次发现都会把两份的 pick 一起改写
        # 成"最后一次 resolve 的值"（实测: 两份副本都发 pickB → 手牌三张同名
        # 误合成金色、pickA 永不授予）。kind 后缀 = 本饰品实体 uuid → 各副本
        # 只认自己开出的那次发现。
        my_kind = f"{PORTABLE_FACTORY_KIND}:{source.uuid}"

        def on_discovered(g, kind=None, hero=None, option=None,
                          _h=h, _src=source, _kind=my_kind, **kw):
            if kind != _kind or hero is not _h:
                return
            if option is None:
                return
            _src._portable_factory_pick = option

        game.events.register(Listener(event=_CARD_DISCOVERED, owner=source,
                                      callback=on_discovered))
        cands = [cid for cid in _pool_candidates(
            game, min_tier=PORTABLE_FACTORY_TIER,
            max_tier=PORTABLE_FACTORY_TIER)
            if game.db.get(cid).race != Race.NONE]
        game.run_actions(Discover(
            h, candidates=cands, kind=my_kind,
            min_tier=PORTABLE_FACTORY_TIER))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        pick = getattr(source, "_portable_factory_pick", None)
        if pick is None:
            return None
        copy_def = game.db.get(pick)
        if copy_def is None:
            return None
        game.grant_card_copy_to_hand(h, copy_def)
        return None


# ══════════════ BG32_MagicItem_362 Innkeeper's Hearth ══════════════

class InnkeepersHearthScript:
    """
    Natural Language: [x]<b>Discover</b> a minion of
    your Tier. Set its stats
    to 12/12.

    Formal Spec:
      1. on_bind: 候选 = `_pool_candidates(min_tier=本人酒馆等级,
         max_tier=本人酒馆等级)`（"a minion of your Tier"——档位 = 发现
         当下 `hero.tavern_tier`）
      2. 预留语义（RULES §6.18 / 2026-09-01 压测协议）: 选项生成即
         `minion_pool.acquire`，`rng.sample` 取 min(3, len) 个互异项;
         resolve 保留选中、释放其余——与 `actions.Discover` 完全同构，
         因本卡需要在**授予前**改写属性故自建 PendingChoice（引擎
         `Discover` 的 resolve 无 post-hook）
      3. resolve(pick): 释放未选项 → `create_minion` → `_set_stats`
         覆盖为 12/12（"Set its stats to 12/12"：剥离全部附魔、
         BASE_ATK/BASE_HEALTH/HEALTH 置 12——batch_spells2 SetStats
         裁定）→ `pending_hand_add` 入手（满手排队）
      4. 无候选（该档池空）→ 不产生 PendingChoice，整卡落空（不报错）
      5. 只作用于本人; 12/12 为文本字面量（CardDef num 全 None，
         SOP §3 允许并在此声明）

    Test: test_batch_trinkets14.py — 绑定后产生 PendingChoice 且选项
      全为本档 / 选定后手牌该卡属性恰 12/12 且附魔为空（覆盖式设定）/
      选中项池副本被消耗、未选项回池（available 复原）/ 对手手牌不变 /
      该档池空时不产生选择且不报错（正对照: 池非空时确有选择）

    Params: stat=12（"Set its stats to 12/12"，文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        tier = h.tavern_tier
        cands = _pool_candidates(game, min_tier=tier, max_tier=tier)
        if not cands:
            return None
        k = min(3, len(cands))
        drawn = (game.rng.sample(cands, k, label="innkeepers_hearth")
                 if k < len(cands) else list(cands))
        options = [cid for cid in drawn if game.minion_pool.acquire(cid)]
        if not options:
            return None

        def resolve(pick_id):
            if pick_id not in options:
                raise GameStateError(
                    f"Innkeeper's Hearth: pick {pick_id} 不在提供选项中 "
                    f"{options}")
            for cid in options:
                if cid != pick_id:
                    game.minion_pool.release(cid, 1)
            m = game.create_minion(pick_id, controller=h)
            _set_stats(m, INNKEEPERS_HEARTH_STAT, INNKEEPERS_HEARTH_STAT)
            game.pending_hand_add(h, m)

        game.pending_choices.append(PendingChoice(
            h, list(options), INNKEEPERS_HEARTH_KIND,
            resolve_callback=resolve))
        return None


# ══════════════ BG32_MagicItem_364 Poet Portrait ══════════════

class PoetPortraitScript:
    """
    Natural Language: Get a Timewarped Poet.

    Formal Spec:
      1. on_bind: `_grant_related(本人, source)` —— 数据链
         `evolution_card_id`（dbf 127441 → BG34_Giant_314 Timewarped
         Poet）授予 1 张**白板副本**进手牌（满手排队 RULES §3.3）
      2. BG34_Giant_314 `is_pool_minion=False`（36.2.2 数据核实）→
         零池操作; 其本体 "All your Dragons keep Bonus Keywords and
         stats gained in combat" 是**那张卡**的迁移项（RULES §7.4.6:
         "Get a X" 只要求交付路径正确，关联卡脚本状态不阻塞本卡）
      3. 只进本人手牌

    Test: test_batch_trinkets14.py — 绑定后本人手牌恰 1 张
      BG34_Giant_314、池可用量不变（非池卡零池）/ 对手手牌为空 /
      下回合不重复授予（无 "each turn"）

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        return None


# ══════════════ DEFERRED（不注册 REGISTRY） ══════════════


class DrakkariPortraitScript:
    """
    Natural Language: [x]Get a Drakkari Enchanter.
    Your Drakkari Enchanters
    are both Mechs and
    Elementals.

    Status: DEFERRED — requires 多/双种族身份改写原语

    Dependency:
      1. `GameTag.RACE` 是**单值** tag；`Race.ALL` 语义是"匹配一切种族
         查询"而非"同时属于机械与元素"（会把全部种族查询一并匹配 =
         近似实现，SOP §6b 禁止）。
      2. 同缺口已由 batch_trinkets8 / batch_trinkets11 /
         batch_trinkets13（Bronzebeard Portrait BG30_MagicItem_418 /
         Enforcer Portrait BG30_MagicItem_971）备案。实现路径: 新增多值
         种族集合（`RACES` set tag 或位掩码）
         + 全部 `race` 查询/种族光环读取点统一改造后，在 on_bind 为
         本人的 Drakkari Enchanter 实例追加 MECH/ELEMENTAL。
      3. "Get a Drakkari Enchanter" 半场已可交付（关联卡
         BG26_ICC_901 已注册、池随从占池），但半实现 = 第三态。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class KelThuzadPortraitScript:
    """
    Status: 已由 batch_trinkets24 注册（minion_destroyed/destroy_minion 原语已于 2026-09-02 落地）

    Natural Language: [x]Get an Archlich Kel'Thuzad.
    After you destroy a minion
    outside combat, give
    your minions +2/+2.

    Status: DEFERRED — requires `minion_destroyed` 事件（摧毁协议）

    Dependency:
      1. 引擎无"摧毁（Destroy）"事件: `events.py` 只有 `death`
         （载荷 `minion=`，无施动者/无摧毁标记）; 招募期真实死亡来源
         不止 Destroy（自伤技能 / 伤害类 AoE 也会 death），且无法判定
         "you destroy"。用 `death` + `not game.in_combat` 近似会把非
         Destroy 死亡计入（SOP §6b 禁止）（2026-09-02 已落地）。
      2. 实现路径: 摧毁路径统一走 `game.destroy_minion(hero, target)`
         并 fire `minion_destroyed(hero=, minion=, in_combat=)` → 本卡
         监听该事件、`in_combat is False` 时 `Buff` 全体己方存活随从
         +2/+2（文本字面量，CardDef num 全 None → 按 SOP §3 声明）。
      3. 关联卡 BG28_308 Archlich Kel'Thuzad 自身也未注册（非池卡），
         但触发条款是第一阻塞，先修协议再评估载荷。

    Params: buff=2（"give your minions +2/+2"，文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class MawCasterPortraitScript:
    """
    Status: 已由 batch_trinkets24 注册（minion_destroyed/destroy_minion 原语已于 2026-09-02 落地）

    Natural Language: [x]Get a Maw Caster.
    Whenever you destroy a
    minion outside combat,
    gain {0} Gold.

    Status: DEFERRED — requires `minion_destroyed` 事件（摧毁协议）

    Dependency: 同 Kel'Thuzad Portrait（`minion_destroyed` 缺失; 无法
      区分 Destroy 与其它招募期死亡）（2026-09-02 已落地）。数值 {0}=num(0)=2 已就绪。
      实现路径: 摧毁事件落地后 `GainGold(hero, num(0))`。

    Params: {0}=num(0)=2（BG32_MagicItem_205）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BristlebachPortraitScript:
    """
    Natural Language: [x]Get a Bristlebach.
    Your Bristlebachs play
    <b>Blood Gems</b> on all
    friendly minions.

    Status: 已迁出 → batch_trinkets34（2026-09-13，RULES §7.4.16 家族行为开关通道 `hero.family_flags`）; 原阻塞: requires 载荷 Bristlebach 脚本（SOP §12 item 14）

    Dependency:
      1. 关联卡 `BG26_157` Bristlebach **未注册**（REGISTRY 无此 id），
         其本体 "Avenge (2): This plays 2 Blood Gems on all your
         Quilboar" 无脚本 → 授予的 Bristlebach 永不触发 Avenge，本饰品
         "把目标范围改为全体友方"的改写对象不存在（"引擎机制就绪" ≠
         "效果可兑现"）。
      2. RULES §7.4.6 例外条款（本卡效果**依赖**被授予卡的行为）→
         整卡维持 DEFERRED。
      3. 实现路径: (a) 先迁 BG26_157（Avenge 阈值 2 + `PlayBloodGems`）;
         (b) 该脚本读取 hero 级"目标范围 = 全体友方"标记（引擎侧需有
         读取点以满足 W3）并据此选目标集合。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class EclecticShrineScript:
    """
    Status: 已由 batch_trinkets24 注册（两处历史 AMBIGUOUS 已由仓内既有先例裁定，2026-09-02 落地）

    Natural Language: [x]<b>Start of Combat:</b> Give a
    friendly minion of each
    different type +{0}/{1}.
    Improve this permanently.

    Status: DEFERRED — 两处无权威读法（本批查证后维持兄弟批次裁定）

    Dependency:
      1. (a) All 型（Amalgam）随从是否可对每个不同类型各获得一次同一
         buff（"a friendly minion of each different type" 的资格集是
         按类型逐个选还是每只随从只选一次;
         batch_trinkets7 / batch_trinkets8 台账已备案）;
         (b) "improve this permanently" 的永久递增发生在首次触发
         **前**还是**后**。两条均无 wiki Notes / 官方说明
         （SOP §6b 第 4 步: 查无证据 → DEFERRED 撤注册）。
      2. 数值已就绪: {0}=num(0)=3 {1}=num(1)=2。
      3. 实现路径: 官方实测或 wiki 裁定后，SoC 钩子按不同类型取随机
         一只 + 永久计数器（存 source 实体）递增后叠加数值。

    Params: {0}=num(0)=3 {1}=num(1)=2（BG32_MagicItem_280）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class CzarinaPortraitScript:
    """
    Natural Language: Get a Charging Czarina.
    Your Charging Czarinas
    also give Health.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — requires 载荷读取通道 + Health 增量权威

    Dependency:
      1. 载荷行为不可扩展: `BG28_741` `ChargingCzarinaScript` 在
         `tavern_spell_cast` 时对带圣盾随从各 `Buff(atk=num(0))`，
         只给 Attack，且不读取任何 hero 级加成通道。饰品在不改兄弟
         批次脚本的前提下无法让该随从"也给 Health"; 在饰品侧另注册
         监听 = 与"由 Charging Czarina 给"的归属不符（Czarina 被出售
         后仍生效）→ 近似，SOP §6b 禁止。
      2. 数值无权威: "also give Health" 的 Health 增量在本饰品 CardDef
         无任何模板参数（num 全 None），wiki 卡页无 Notes。
      3. 实现路径: (a) `BG28_741` 脚本增读 `hero._czarina_bonus_health`
         （引擎/该脚本的读取点）并在 Buff 时一并给 Health;
         (b) 补 Health 增量的数据/官方权威。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class LavishCapeScript:
    """
    Natural Language: Cast a random Tavern spell
    for each different friendly
    minion type. At the start
    of each turn, repeat this.

    Status: DEFERRED — requires `game.cast_spell_by_id` 直施原语

    Dependency:
      1. 引擎无"按 card_id 直接施放"入口（`play_spell` 要求实体已在
         手牌）; batch_trinkets8 / batch_activate（Cagey Conjurer
         BG36_508）台账同缺口。
      2. 池法术 72/75 已有 on_play 脚本，但"随机施放"还需
         needs_target 法术的随机目标解析（SOP §16 item 15: 无合法目标
         须落空并回滚池记账）与直施语义收口（不计入
         `TAVERN_SPELLS_CAST_*`、不广播 `tavern_spell_cast`）。
      3. 实现路径: 引擎提供 `cast_spell_by_id(hero, card_id, target=…)`
         → 本卡 on_bind + start_of_turn 按不同友方类型数
         （`{race != NONE/ALL}` 去重）调用 N 次随机池法术。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class PutricideStickerScript:
    """
    Natural Language: [x]Craft a custom Undead.
    At the start of every 2 turns,
    repeat this. <i>({0} |4(turn, turns) left!)</i>

    Status: DEFERRED — requires "Craft a custom Undead" 合成子系统

    Dependency:
      1. "Craft a custom Undead" 是 Putricide 的多步部件合成链（种族 +
         关键词 + 属性选择，产出 `BG25_HERO_100pt` Putricide's
         Creation token）; 全仓无 `craft` 实现，
         `BG25_HERO_100p` Build-An-Undead 英雄技能亦因此 DEFERRED
         （batch_hero_remaining / batch_hero_remaining2 台账）。
      2. 数值 {0}=num(0)=2（"every 2 turns"）已就绪。
      3. 实现路径: 建立合成选择链协议（多步 PendingChoice + 部件卡片
         池 + 参数落点）后，本卡 on_bind / 每 2 回合 start_of_turn
         各触发一次。

    Params: {0}=num(0)=2（BG32_MagicItem_300）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class SplinterOfAurumScript:
    """
    Natural Language: [x]When you have {1} Gold,
    get a random Golden
    Tier 5 minion.
    <i>(Once per game.)</i>

    Status: DEFERRED — requires 金币增加事件 / gold 观察点

    Dependency:
      1. 引擎无金币变化事件: `events.py` 只有 `gold_spent`（支出）;
         收入路径（`hero.gold` setter / `GainGold` action /
         `_begin_recruit_for` 基础收入）**不 fire 任何事件**。
         回合收入在饰品 `start_of_turn` 钩子之前结算（game.py
         `_begin_recruit_for` L222 vs L253），故 start_of_turn 检查只
         覆盖回合收入、漏掉回合内收入（出售 / 海盗 / 法术给金）→
         近似，SOP §6b 禁止。
      2. 交付侧已就绪: 随机金色 T5 + `Discover(golden=True)` 的池记账
         协议（`GILDED_NOT_TRIPLED`）; 数值 {1}=num(1)=15。实现路径:
         引擎在金币增加点 fire `gold_gained(hero=, amount=)`（或提供
         `hero.gold` 变更回调）→ 本卡监听并判定
         `hero.gold >= num(1)`（once per game 记在 source 实体）。

    Params: {1}=num(1)=15（BG32_MagicItem_350）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class GuidingCandleScript:
    """
    Natural Language: [x]Your first two <b>Refreshes</b>
    each turn contain only
    Tier 6 cards. <i>({0} left!)</i>

    Status: DEFERRED — requires 精确档位刷新过滤 `_tavern_offer_tier_exact`

    Dependency:
      1. 引擎 `refresh_tavern` 只有 `hero._tavern_offer_tier_only`
         （= 与**本人酒馆等级**同档，Elven Elite）与 `_tavern_min_tier`
         下限，无"指定第 N 档"的精确过滤（batch_trinkets7 /
         batch_trinkets8 台账同缺口）; 本卡需要 Tier 6 固定档
         （T9 购买时本人等级通常 < 6，`_tavern_offer_tier_only` 无法
         表达）。
      2. 还需"每回合前 num(0)=2 次刷新"的计数与自动刷新
         （`auto=True`）排除（同 Dalaran Cheese Wheel
         BG30_MagicItem_879 的 "you Refresh" 口径）。
      3. 实现路径: 引擎增 `hero._tavern_offer_tier_exact = N` 读取点
         （`refresh_tavern` 内 `min_tier = max_tier = N`）+ 脚本侧
         每回合计数。

    Params: {0}=num(0)=2（BG32_MagicItem_366）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class WarDrumScript:
    """
    Natural Language: [x]One <b>Battlecry</b> each turn
    triggers two extra times.
    <i>({0} left!)</i>

    Status: DEFERRED — requires 每回合限定的战吼额外触发配额

    Dependency:
      1. `hero.extra_triggers["bc_times"]` 是**永久全量**额度（每个己方
         战吼都 +N，RULES §6.20），没有"每回合仅前 1 个战吼"的限定
         key（对照 `soc_first` / `dr_first` / `spell_first` 均有
         per-turn "前 N 次"语义，`bc_times` 没有）。
      2. 脚本侧"开局置 bc_times=2、首个 `battlecry_trigger` 后清零"会
         **覆盖** Gilnean War Horn 等其它来源写在同一 key 的永久额度
         （共享 key 冲突 = 错误）; SOP §6.20 亦明令禁止卡脚本自行写
         计数器重放效果。
      3. 数值 {1}=num(1)=2（"two extra times"）已就绪; `{0}`=num(0)=1
         为剩余次数显示。
      4. 实现路径: 引擎增 `bc_first`（每回合前 N 个战吼各额外触发 1 次）
         额度 + `_begin_recruit_for` 每回合重置 + `_run_play_effects`
         消费点 → 本卡声明额度。

    Params: {0}=num(0)=1 {1}=num(1)=2（BG32_MagicItem_416）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ 注册 ══════════════

def register() -> list[str]:
    """注册本批 9 张 CORRECT 饰品（11 张 DEFERRED 见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_MagicItem_200", AllPurposeKibbleScript),
        ("BG32_MagicItem_230", ExtravagantScaleScript),
        ("BG32_MagicItem_232", SharkCannonScript),
        ("BG32_MagicItem_278", ReusableBatteriesScript),
        ("BG32_MagicItem_279", ToughTuskStickerScript),
        ("BG32_MagicItem_282", TurbochargedDrillScript),
        ("BG32_MagicItem_361", PortableFactoryScript),
        ("BG32_MagicItem_362", InnkeepersHearthScript),
        ("BG32_MagicItem_364", PoetPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
