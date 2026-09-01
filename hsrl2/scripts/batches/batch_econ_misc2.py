"""批次 econ_misc2 — 15 张事件触发型池随从（作业单 2026-08-21）。

实现状态总览（详见各类 docstring）:
  OK:       BG34_950 Stone Age Slab / BG35_155 Twisted Wrathguard /
            BG36_211 Cage Gnawer / BG36_352 Unbound Tempest /
            BG36_523 Enterprising Escapee / BG36_622 Torrential Ruiner /
            BG36_640 Gatekeeper Amalgam / BG36_733 Eredar Escapist /
            BG36_762 Devilish Distractor / BG36_921 Fleeing Fugitive /
            BGS_004 Wrath Weaver / BGS_041 Kalecgos / BGS_127 Molten Rock /
            BGS_104 Nomi（含金色 id; 金色=独立卡定义）
  DEFERRED: BG35_342 Falling Sky Golem（动态 atk/health 脚本钩子未接线，
            详见该类 docstring——不注册 REGISTRY）

共性语义:
  - 持久监听器一律 on_summon 注册（owner=source，出售/招募期死亡自动
    注销; 战斗快照恢复使战死随从的监听器战后复活——引擎保证）。
    打出随从自身时 summon 先于 card_played fire → "After you play a
    <本卡所属种族>"（Wrath Weaver/Molten Rock/Unbound Tempest）含
    自身（官方语义）。
  - "Cast X spell"（Gatekeeper Amalgam / Eredar Escapist）统一裁定
    （batch_rally2 Seafloor Recruiter 先例）: create_spell + 运行其
    on_play 效果本体——不经手牌/不耗金币/不动法术池/不计
    TAVERN_SPELLS_CAST/不广播 card_played（事件语义为手牌打出）。
  - 效果数值一律 game.db.get(source.card_id).num()——金色注册类经
    金色 CardDef 自然取值; 行为差异（twice/double/triple）经注册类
    times/mult 属性体现（Felboar 先例）。
  - 计数器用 source 实体级动态属性（_xxx，作业单 setattr 模式;
    batch_consume _felboar_casts / batch_battlecry _breakout_resolved
    先例）——不新增 GameTag（tags.py 仅主线可改）。

引擎缺口（见作业返回清单）:
  1. Entity.atk/max_health 属性不查询脚本 "atk"/"health" 钩子
     （entity.py:94-127 只算 base+buffs+aura; 全库无 call_script
     ("atk"/"health") 调用点）→ BG35_342 Falling Sky Golem
     "Has +{0}/+{1} for each Deathrattle ... (wherever this is)"
     DEFERRED。COUNTER_DEATHRATTLES 计数本体已就绪（game.py 战斗+
     招募亡语触发均 +1），缺属性读点接线。
  2. "效果施法" 无专用事件（batch_rally2 已报，本批沿用裁定）。
"""

from __future__ import annotations

import hsrl2.scripts.registry as _registry
from hsrl2.actions import Buff
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, \
    TavernBuff
from hsrl2.constants import LOCKBOX_CARD_ID
from hsrl2.events import (
    AFTER_ATTACK,
    BATTLECRY_TRIGGER,
    CARD_PLAYED,
    GOLD_SPENT,
    HERO_DAMAGE_TAKEN,
    MINION_BOUGHT,
    MINION_SOLD,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import Race, Zone

# 身份标识常量（card id 非数值——CHEFS_CHOICE_ID 先例）
MISPLACED_TEA_SET_ID = "BG28_888"   # Misplaced Tea Set（Gatekeeper 施放）
SHINY_RING_ID = "BG28_168"          # Shiny Ring（Eredar Escapist 施放）

_BEAST_RACES = (Race.BEAST, Race.ALL)        # ALL 视为所有种族 (RULES §6.18)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_DEMON_RACES = (Race.DEMON, Race.ALL)
_DRAGON_RACES = (Race.DRAGON, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)


def _num(game, source, index: int, which: str) -> int:
    """CardDef.num 取值 + 缺参 fail-loud（Felboar 先例）。"""
    d = game.db.get(source.card_id)
    val = d.num(index)
    if val is None:
        raise GameStateError(
            f"{source.card_id}: missing num({index}) template param "
            f"({which})")
    return val


# ══════════════════ BG34_950 Stone Age Slab ══════════════════


class StoneAgeSlabScript:
    """
    Natural language: [x]After you buy a minion, give
    it +{0}/+{1} and double its
    stats. <i>(Once per turn.)</i>

    Formal spec:
      1. on_summon 注册 MINION_BOUGHT 持久监听器（owner=source）:
         条件 = 被购随从与 source 同控制者 + 本回合尚未触发过
         （source._slab_used_turn != game.turn——"Once per turn"）
      2. 触发（buy_from_tavern 在入牌后、三连检查前 fire，被购随从
         在手牌）: 先 Buff(被购, +num(0)/+num(1))，再一条
         Buff(atk=当前atk×(mult-1), health=当前max_health×(mult-1))
         ——"double its stats" = 属性×mult（mult=2 基础 / 3 金色
         "triple"）; 属性快照用 atk/max_health（SOP §3）
      3. buff 先于 check_for_triple 落地 → 三连合成保留（buff 并集）
      4. 无实体创建; 数值金色经金色 CardDef（20/20 同值）自然体现

    Test: test_batch_econ_misc2.py — 购买后 (base+num)×2 / 同回合第二
    次购买不触发 / 下一回合计数重置 / 金色 ×3 / 对手购买无效果

    Params: {0}=20 {1}=20（36.2.2 基线，金色同值）; mult=2 文本字面量
    "double"（金色 mult=3 "triple"）
    """

    stat_mult = 2   # 金色 "triple its stats" → 3（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not source.controller:
                return
            if getattr(source, "_slab_used_turn", None) == g.turn:
                return
            source._slab_used_turn = g.turn
            mult = source.scripts.stat_mult
            # 先结算 +num 再读当前属性——倍增增量必须在增益落地后取值
            g.run_actions(Buff(minion, atk=_num(g, source, 0, "buff atk"),
                               health=_num(g, source, 1, "buff health")))
            g.run_actions(Buff(minion, atk=minion.atk * (mult - 1),
                               health=minion.max_health * (mult - 1)))

        game.events.register(Listener(
            event=MINION_BOUGHT,
            owner=source,
            condition=lambda minion=None, **kw: (
                minion is not None
                and minion.controller is source.controller),
            callback=on_bought,
        ))
        return None


class StoneAgeSlabGoldenScript(StoneAgeSlabScript):
    """
    Natural language: [x]After you buy a minion, give
    it +{0}/+{1} and triple its
    stats. <i>(Once per turn.)</i>

    Formal spec: 同基础版，stat_mult=3——"triple its stats" = 属性×3
    （Buff 增量 = 2×当前值）; "Once per turn" 与数值（20/20，金色
    CardDef num）不变。

    Test: test_batch_econ_misc2.py — 金色购买后 (base+num)×3

    Params: {0}=20 {1}=20（金色 CardDef，36.2.2 基线）; mult=3 文本
    字面量 "triple"
    """

    stat_mult = 3


# ══════════════════ BG35_155 Twisted Wrathguard ══════════════════


class TwistedWrathguardScript:
    """
    Natural language: After you sell a minion, add a <b>Fodder</b> to your
    next <b>Refresh</b>.

    Formal spec:
      1. on_summon 注册 MINION_SOLD 持久监听器（owner=source）:
         条件 = 被售随从与 source 同控制者（minion_sold 在移除前
         fire，controller 仍有效——Meteorite Crasher 同构）
      2. 触发: game._fodder_refresh_pending[hero] += n（n=1）——
         Fodder 协议与 Demonology Dark Gift 同一（game.refresh_tavern
         每次刷新附加一枚 BG35_150t 并递减计数; 作业单明示经此字段，
         game.py:1873 dark gift 同款写法）
      3. 无实体创建（Fodder token 由 refresh_tavern 生成，非池卡）

    Test: test_batch_econ_misc2.py — 售出后 pending=1 / 刷新后酒馆含
    Fodder 且计数归零 / 对手售出无效果 / 金色 +2

    Params: 无模板参数（n=1 为文本字面量 "a Fodder"; 金色 n=2
    "two Fodders"）
    """

    fodder_count = 1   # 金色 "add two Fodders" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_sold(g, minion=None, **kw):
            if minion is None or minion.controller is not source.controller:
                return
            hero = source.controller
            # 协议 v2: (剩余刷新次数, 每次附加枚数)——"add N Fodders to
            # your next Refresh" = 下 1 次刷新附加 N 枚
            prev = g._fodder_refresh_pending.get(hero, (0, 0))
            g._fodder_refresh_pending[hero] = (
                prev[0] + 1,
                max(prev[1], source.scripts.fodder_count))

        game.events.register(Listener(
            event=MINION_SOLD,
            owner=source,
            condition=lambda minion=None, **kw: (
                minion is not None
                and minion.controller is source.controller),
            callback=on_sold,
        ))
        return None


class TwistedWrathguardGoldenScript(TwistedWrathguardScript):
    """
    Natural language: After you sell a minion, add two <b>Fodders</b> to
    your next <b>Refresh</b>.

    Formal spec: 同基础版，fodder_count=2——每次售出累加 2 枚待附加
    Fodder（refresh_tavern 每刷新消耗 1 枚，连续两次刷新各得一枚）。

    Test: test_batch_econ_misc2.py — 金色售出后 pending=2

    Params: 无模板参数（n=2 为金色文本字面量 "two Fodders"）
    """

    fodder_count = 2


# ══════════════════ BG36_211 Cage Gnawer ══════════════════


class CageGnawerScript:
    """
    Natural language: Whenever a friendly Beast attacks, give your
    Beasts +{0}/+{1}.

    Formal spec:
      1. on_summon 注册 AFTER_ATTACK 持久监听器（owner=source）:
         事件由战斗攻击（combat.py C4——伤害与死亡结算后）与招募期
         攻击（game.recruit_phase_attack）两路 fire，kwargs
         attacker=/defender=; 条件 = attacker 与 source 同控制者且
         race ∈ (BEAST, ALL)（"friendly Beast"——含 source 自身）
      2. 触发: source 控制者棋盘全部存活 Beast（含 ALL; 文本无
         "other" 含自身）各 +num(0)/+num(1)
      3. 战斗内触发 → 战后快照回滚（RULES §3.5——文本无 "this
         game"/permanent，Heroic Underdog 先例）; 招募期攻击路径
         无回滚自然持久
      4. 金色版文本同构（金色 num=4/2）→ 同一脚本类注册两个 id

    Test: test_batch_econ_misc2.py — 友方野兽攻击后全体野兽 +num /
    非野兽攻击不触发 / 敌方野兽攻击不触发 / 战斗后回滚 / 金色 4/2

    Params: {0}=2 {1}=1（36.2.2 基线，金色 =4/2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def after_attack(g, attacker=None, defender=None, **kw):
            if attacker is None:
                return
            d = g.db.get(source.card_id)
            g.run_actions([
                Buff(m, atk=d.num(0), health=d.num(1))
                for m in source.controller.board
                if not m.dead and m.race in _BEAST_RACES])

        game.events.register(Listener(
            event=AFTER_ATTACK,
            owner=source,
            condition=lambda attacker=None, **kw: (
                attacker is not None
                and attacker.controller is source.controller
                and attacker.race in _BEAST_RACES),
            callback=after_attack,
        ))
        return None


# ══════════════════ BG36_352 Unbound Tempest ══════════════════


class UnboundTempestScript:
    """
    Natural language: [x]After you play {1} Elementals,
    gain the stats of the highest-
    Health minion in the
    Tavern. <i>({0} left!)</i>

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         条件 = 打出的卡是 Minion、race ∈ (ELEMENTAL, ALL)、与
         source 同控制者。**含 source 自身**（其为 Elemental，summon
         先于 card_played fire，打出即计数 +1——官方 "After you
         play an Elemental" 含自）; 磁力吸附路径同样 fire card_played
         → 打出元素磁力卡亦计
      2. 计数 = source 实体级 _tempest_elementals（入场后从 0 起数，
         "(3 left!)" 卡面计数语义——此前打出的不计、手牌期不计，
         Felboar 先例）。达到 num(1) 阈值 → 触发并减去阈值（滚动:
         每 num(1) 次触发一次）
      3. 触发: 馆内（hero.tavern）最高 max_health 的 Minion（并列
         取首个; SOP §3 属性快照用 max_health）→ source 获得
         Buff(atk=该随从.atk×mult, health=该随从.max_health×mult)
         （mult=1 基础 / 2 金色 "double"）; 馆内无随从 → 效果落空
         但计数照减（触发已发生，Felboar 口径）
      4. num(1) 缺失 → GameStateError（PARAM_MISSING fail-loud）

    Test: test_batch_econ_misc2.py — 3 次元素获得馆内最高血随从攻/血 /
    2 次不触发 / 非元素不计 / 滚动计数 / 金色双倍

    Params: {1}=3（36.2.2 基线，金色同值; {0}=3 为剩余数显示参数）;
    mult=1（金色 mult=2 文本字面量 "double"）
    """

    stat_mult = 1   # 金色 "gain double the stats" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            threshold = _num(g, source, 1, "elemental count threshold")
            source._tempest_elementals = \
                getattr(source, "_tempest_elementals", 0) + 1
            if source._tempest_elementals < threshold:
                return
            source._tempest_elementals -= threshold
            hero = source.controller
            tavern_minions = [e for e in hero.tavern
                              if isinstance(e, Minion) and not e.dead]
            if not tavern_minions:
                return
            best = max(tavern_minions, key=lambda m: m.max_health)
            mult = source.scripts.stat_mult
            g.run_actions(Buff(source, atk=best.atk * mult,
                               health=best.max_health * mult))

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Minion)
                and card.race in _ELEMENTAL_RACES
                and card.controller is source.controller),
            callback=on_played,
        ))
        return None


class UnboundTempestGoldenScript(UnboundTempestScript):
    """
    Natural language: [x]After you play {1} Elementals,
    gain double the stats of the
    highest-Health minion in
    the Tavern. <i>({0} left!)</i>

    Formal spec: 同基础版，stat_mult=2——获得馆内最高血随从攻/血的
    两倍; 阈值/计数不变（金色 num(1)=3）。

    Test: test_batch_econ_misc2.py — 金色触发获得 2×(atk/max_health)

    Params: {1}=3（金色 CardDef）; mult=2 文本字面量 "double"
    """

    stat_mult = 2


# ══════════════════ BG36_523 Enterprising Escapee ══════════════════


class EnterprisingEscapeeScript:
    """
    Natural language: [x]After you spend {2} Gold, get
    a Lockbox. If you already have
    one, it opens {3} |4(turn, turns) sooner
    instead. <i>({0} Gold left!)</i>

    Formal spec:
      1. on_summon 注册 GOLD_SPENT 持久监听器（owner=source）:
         条件 = kw["hero"] is source.controller。spend_gold 对购买/
         刷新/升级/Activate/Dark Gift 全部支出 fire（amount=单次支出
         额）——官方 "After you spend X Gold" 累计口径
      2. 计数 = source 实体级 _escapee_gold_spent 累加 amount;
         while ≥ num(2) 阈值: 减去阈值并触发（单笔大额支出滚动多次，
         如升级一次 10 金 = 2 次）
      3. 触发 = Locked-up Mutineer/Bilgewater Breakout 同款双分支:
         分支 A（手牌已有 card_id == LOCKBOX_CARD_ID）:
         game.open_lockbox_early(hero, num(3))——已有 Lockbox 倒计时
         提前 num(3) 回合，归零即开（随机有种族金色随从，
         game._open_lockbox 保证）
         分支 B: create_spell(LOCKBOX_CARD_ID)（初始倒计时 = Lockbox
         CardDef num(0)=5，create_spell 保证）+ pending_hand_add
         （满手排队，RULES §3.3）
      4. num(2)/num(3) 缺失 → GameStateError（fail-loud）

    Test: test_batch_econ_misc2.py — 累计 5 金入手 Lockbox（倒计时=
    Lockbox num(0)）/ 4 金不触发 / 已有走 early 路径 -num(3) /
    对手支出不计 / 金色 -2 / 单笔 10 金触发两次

    Params: {2}=5 {3}=1（36.2.2 基线，金色 {3}=2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_gold_spent(g, hero=None, amount=0, **kw):
            if hero is not source.controller:
                return
            threshold = _num(g, source, 2, "gold threshold")
            sooner = _num(g, source, 3, "lockbox turns sooner")
            source._escapee_gold_spent = \
                getattr(source, "_escapee_gold_spent", 0) + amount
            while source._escapee_gold_spent >= threshold:
                source._escapee_gold_spent -= threshold
                if any(c.card_id == LOCKBOX_CARD_ID
                       for c in hero.hand):
                    g.open_lockbox_early(hero, sooner)
                else:
                    lockbox = g.create_spell(LOCKBOX_CARD_ID,
                                             controller=hero)
                    g.pending_hand_add(hero, lockbox)

        game.events.register(Listener(
            event=GOLD_SPENT,
            owner=source,
            condition=lambda hero=None, **kw: hero is source.controller,
            callback=on_gold_spent,
        ))
        return None


class EnterprisingEscapeeGoldenScript(EnterprisingEscapeeScript):
    """
    Natural language: [x]After you spend {2} Gold, get
    a Lockbox. If you already have
    one, it opens {3} |4(turn, turns) sooner
    instead. <i>({0} Gold left!)</i>（金色 num(3)=2）

    Formal spec: 同基础版——阈值 num(2)=5 不变，early 分支提前量经
    金色 CardDef num(3)=2 自然体现（单次总额 "-2"，非 twice 语义，
    Bilgewater Breakout Golden 同构）。同一脚本类复用亦可; 独立注册
    类保留金色文本审计锚点。

    Test: test_batch_econ_misc2.py — 金色已有 Lockbox 时倒计时 -2

    Params: {2}=5 {3}=2（金色 CardDef，36.2.2 基线）
    """

    pass


# ══════════════════ BG36_622 Torrential Ruiner ══════════════════


class TorrentialRuinerScript:
    """
    Natural language: Whenever you cast a spell on a Naga, give your
    minions +{0}/+{1}.

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         法术路径的 card_played 携带 target kwarg（game.py
         _finish_play_spell）。条件 = card 是 Spell、与 source 同
         控制者、target 是 Minion 且 race ∈ (NAGA, ALL)
         ——"cast a spell" 全口径: 酒馆法术/Spellcraft/血宝石均经
         play_spell fire（引擎计数分流不影响本事件）; Amalgam(ALL)
         视为 Naga（RULES §6.18）
      2. 触发: source 控制者棋盘全部存活随从（"your minions" 无
         other——含自身）各 +num(0)/num(1)
      3. 效果施法（"Cast X" 裁定）不广播 card_played → 不递归触发
      4. 金色版文本同构（金色 num=4/6）→ 同一脚本类注册两个 id

    Test: test_batch_econ_misc2.py — 对 Naga 施放血宝石后全体 +num /
    对非 Naga 施放不触发 / 对手施放不触发 / 金色 4/6

    Params: {0}=2 {1}=3（36.2.2 基线，金色 =4/6）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, target=None, **kw):
            d = g.db.get(source.card_id)
            g.run_actions([
                Buff(m, atk=d.num(0), health=d.num(1))
                for m in source.controller.board if not m.dead])

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, target=None, **kw: (
                isinstance(card, Spell)
                and card.controller is source.controller
                and isinstance(target, Minion)
                and target.race in _NAGA_RACES),
            callback=on_played,
        ))
        return None


# ══════════════════ BG36_640 Gatekeeper Amalgam ══════════════════


class GatekeeperAmalgamScript:
    """
    Natural language: Whenever you cast a spell on this, it casts
    Misplaced Tea Set.

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         条件 = card 是 Spell、与 source 同控制者、target is source
         （"on this"——含血宝石/Spellcraft 等一切经 play_spell 的
         定向施放）
      2. 触发 = 效果施法 Misplaced Tea Set（batch_rally2 统一裁定:
         create_spell(BG28_888) + 运行其 on_play 效果本体——不经
         手牌/不耗金币/不动法术池/不计 TAVERN_SPELLS_CAST/不广播
         card_played，防递归）; 施放后法术实体 zone=REMOVED。
         Tea Set 效果: 对棋盘每个唯一种族随机一只 +4/+4
         （tavern_spell_buff，TAVERN_SPELL_EXTRA 联动;
         MisplacedTeaSetScript 权威）
      3. times 次独立施放（金色 "twice"）
      4. source(race=ALL) 本身可被 Tea Set 选中（其自身构成 ALL 种族
         候选——Amalgam 匹配任何种族查询）

    Test: test_batch_econ_misc2.py — 对其施放血宝石 → Tea Set 效果
    落在本体（唯一 ALL 随从确定性断言）/ 对其他随从施放不触发 /
    金色两次 / 施放计数不增加（效果施法不计数）

    Params: 无模板参数（Tea Set 数值由其 CardDef 4/4 权威）;
    times=1（金色 times=2 文本字面量 "twice"）
    """

    times = 1   # 金色 "casts Misplaced Tea Set twice" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, target=None, **kw):
            hero = source.controller
            for _ in range(source.scripts.times):
                spell = g.create_spell(MISPLACED_TEA_SET_ID, controller=hero)
                g.run_script_hook(spell, "on_play", ctx=None)
                spell.zone = Zone.REMOVED

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, target=None, **kw: (
                isinstance(card, Spell)
                and card.controller is source.controller
                and target is source),
            callback=on_played,
        ))
        return None


class GatekeeperAmalgamGoldenScript(GatekeeperAmalgamScript):
    """
    Natural language: Whenever you cast a spell on this, it casts
    Misplaced Tea Set twice.

    Formal spec: 同基础版，times=2——同一次施放触发两次独立 Tea Set
    效果（各自随机选目标）。

    Test: test_batch_econ_misc2.py — 金色单体场景获得 2×Tea Set 数值

    Params: times=2 文本字面量 "twice"
    """

    times = 2


# ══════════════════ BG36_733 Eredar Escapist ══════════════════


class EredarEscapistScript:
    """
    Natural language: [x]After your hero takes {1}
    damage, cast Shiny Ring.
    <i>({0} left!)</i>

    Formal spec:
      1. on_summon 注册 HERO_DAMAGE_TAKEN 持久监听器（owner=source）:
         条件 = kw["hero"] is source.controller。Hero.take_damage 对
         护甲吸收也算受伤（Floating Watcher 语义，hero.py 保证）;
         战斗败方伤害在快照恢复后施加（Tichondrius 先例）→ 施放的
         buff 落在已复原棋盘并跨回合保留
      2. 计数 = source 实体级 _escapist_dmg_taken 累加 amount;
         while ≥ num(1) 阈值: 减去阈值并施放（大额伤害滚动多次）
      3. 施放 = 效果施法 Shiny Ring（batch_rally2 统一裁定:
         create_spell(BG28_168) + 运行其 on_play——"Give your
         minions +1/+1" 全体无目标，tavern_spell_buff 构造;
         不广播 card_played 防递归）; times 次独立施放（金色
         "twice"）; 施放后法术实体 zone=REMOVED
      4. num(1) 缺失 → GameStateError（fail-loud）

    Test: test_batch_econ_misc2.py — 累计 num(1) 伤害全体 +Shiny Ring
    值 / 差 1 点不触发 / 对手受伤不触发 / 滚动（6 伤两次施放）/
    金色两次

    Params: {1}=3（36.2.2 基线，金色同值; {0}=3 为剩余数显示参数）;
    times=1（金色 times=2 文本字面量 "twice"）
    """

    times = 1   # 金色 "cast Shiny Ring twice" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_hero_damaged(g, hero=None, amount=0, **kw):
            if hero is not source.controller:
                return
            threshold = _num(g, source, 1, "damage threshold")
            source._escapist_dmg_taken = \
                getattr(source, "_escapist_dmg_taken", 0) + amount
            while source._escapist_dmg_taken >= threshold:
                source._escapist_dmg_taken -= threshold
                for _ in range(source.scripts.times):
                    spell = g.create_spell(SHINY_RING_ID, controller=hero)
                    g.run_script_hook(spell, "on_play", ctx=None)
                    spell.zone = Zone.REMOVED

        game.events.register(Listener(
            event=HERO_DAMAGE_TAKEN,
            owner=source,
            condition=lambda hero=None, **kw: hero is source.controller,
            callback=on_hero_damaged,
        ))
        return None


class EredarEscapistGoldenScript(EredarEscapistScript):
    """
    Natural language: [x]After your hero takes {1}
    damage, cast Shiny Ring
    twice. <i>({0} left!)</i>

    Formal spec: 同基础版，times=2——每达阈值施放两次 Shiny Ring;
    阈值 num(1)=3 不变（金色 CardDef 同值）。

    Test: test_batch_econ_misc2.py — 金色 3 伤触发两次全体 +2×Shiny 值

    Params: {1}=3（金色 CardDef）; times=2 文本字面量 "twice"
    """

    times = 2


# ══════════════════ BG36_762 Devilish Distractor ══════════════════


class DevilishDistractorScript:
    """
    Natural language: Whenever you cast a spell on this, give minions
    in the Tavern +{0}/+{1} this game.

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         条件 = card 是 Spell、与 source 同控制者、target is source
      2. 触发 = Nomi/Staff of Enrichment 同款双件:
         a) ApplyTavernBuff(hero, TavernBuff(+num(0)/+num(1),
            source_id))——持久面: hero.tavern_buffs 登记，refresh_
            tavern 对新入馆随从自动应用（引擎已接线，game.py
            refresh_tavern）
         b) BuffCurrentTavern(hero, 同一 TavernBuff)——立即面对当前
            馆内全部随从施加（无种族过滤——"minions in the Tavern"
            全体）
      3. "this game" 持久——冻结保留项不重复应用（引擎保证）
      4. 金色版文本同构（金色 num=4/4）→ 同一脚本类注册两个 id

    Test: test_batch_econ_misc2.py — 对其施放后馆内随从 +num 且
    tavern_buffs 登记 / 刷新后新随从自动获得 / 对其他随从施放无效 /
    金色 4/4

    Params: {0}=2 {1}=2（36.2.2 基线，金色 =4/4）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, target=None, **kw):
            d = g.db.get(source.card_id)
            tb = TavernBuff(atk=d.num(0), health=d.num(1),
                            source_id=source.card_id)
            g.run_actions([ApplyTavernBuff(source.controller, tb),
                           BuffCurrentTavern(source.controller, tb)])

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, target=None, **kw: (
                isinstance(card, Spell)
                and card.controller is source.controller
                and target is source),
            callback=on_played,
        ))
        return None


# ══════════════════ BG36_921 Fleeing Fugitive ══════════════════


class FleeingFugitiveScript:
    """
    Natural language: Whenever you cast a spell on this, gain +{0}
    Health.

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         条件 = card 是 Spell、与 source 同控制者、target is source
      2. 触发: source 获得 +num(0) 生命（无攻击分量，Buff atk=0
         结构性占位）; 可叠层（多次施放多次获得）
      3. 金色版文本同构（金色 num(0)=2）→ 同一脚本类注册两个 id

    Test: test_batch_econ_misc2.py — 对其施放血宝石生命 +num(0)（另含
    血宝石自身 life 分量）/ 对其他随从施放不触发 / 金色 +2

    Params: {0}=1（36.2.2 基线，金色 =2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, target=None, **kw):
            g.run_actions(Buff(source, atk=0,
                               health=_num(g, source, 0, "health gain")))

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, target=None, **kw: (
                isinstance(card, Spell)
                and card.controller is source.controller
                and target is source),
            callback=on_played,
        ))
        return None


# ══════════════════ BGS_004 Wrath Weaver ══════════════════


class WrathWeaverScript:
    """
    Natural language: After you play a Demon, deal 1 damage to your
    hero and gain +{0}/+{1}.

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         条件 = 打出的卡是 Minion、race ∈ (DEMON, ALL)、与 source
         同控制者。**含自身**（Wrath Weaver 是 Demon，summon 先于
         card_played fire → 打出自身即触发——官方行为）; 磁力吸附
         路径同样 fire → 打出恶魔磁力卡亦触发
      2. 触发（times 次独立序列，"damage→gain" 为一个单元）:
         hero.take_damage(1)（文本字面量 1; 护甲吸收也算受伤并广播
         HERO_DAMAGE_TAKEN——Tichondrius 联动）→ Buff(source,
         +num(0)/+num(1))
      3. num(0)/num(1) 缺失 → GameStateError（fail-loud）

    Test: test_batch_econ_misc2.py — 打出恶魔英雄 -1 生命且自身
    +num / 打出非恶魔不触发 / 打出自身触发 / 对手打出不触发 /
    金色两次（-2 生命 +2×num）

    Params: {0}=2 {1}=2（36.2.2 基线，金色同值）; 伤害 1 为文本
    字面量 "deal 1 damage"; times=1（金色 times=2 文本字面量 "twice"）
    """

    times = 1   # 金色 "twice" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            hero = source.controller
            atk = _num(g, source, 0, "buff atk")
            health = _num(g, source, 1, "buff health")
            actions = []
            for _ in range(source.scripts.times):
                hero.take_damage(1)   # 文本字面量 "deal 1 damage"
                actions.append(Buff(source, atk=atk, health=health))
            g.run_actions(actions)

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Minion)
                and card.race in _DEMON_RACES
                and card.controller is source.controller),
            callback=on_played,
        ))
        return None


class WrathWeaverGoldenScript(WrathWeaverScript):
    """
    Natural language: After you play a Demon, deal 1 damage to your
    hero and gain +{0}/+{1}, twice.

    Formal spec: 同基础版，times=2——每次打出恶魔触发两个独立
    "damage→gain" 单元（2 点伤害分两次实例 + 2×num buff）。

    Test: test_batch_econ_misc2.py — 金色打出恶魔英雄 -2 且 +2×num

    Params: {0}=2 {1}=2（金色 CardDef）; times=2 文本字面量 "twice"
    """

    times = 2


# ══════════════════ BGS_041 Kalecgos, Arcane Aspect ══════════════════


class KalecgosScript:
    """
    Natural language: After you trigger a Battlecry, give your Dragons
    +{0}/+{1}.

    Formal spec:
      1. on_summon 注册 BATTLECRY_TRIGGER 持久监听器（owner=source）:
         事件由打出（金色/Brann 每次触发各 fire 一次）与
         TriggerBattlecry 重触发两路 fire（game.py 保证），kwargs
         minion=触发战吼的随从; 条件 = minion 与 source 同控制者
         （"you trigger"——友方战吼; 对手战吼不触发）
      2. 触发: source 控制者棋盘全部存活 Dragon（含 ALL; 文本无
         "other"——含 Kalecgos 自身）各 +num(0)/num(1)
      3. 金色版: 旧 wiki 数据曾为 4/4 之外值——36.2.2 CardDefs 权威
         金色 num=4/4（TB_BaconUps_109，数据核对 2026-08-21），文本
         同构 → 同一脚本类注册两个 id
      4. num(0)/num(1) 缺失 → GameStateError（fail-loud）

    Test: test_batch_econ_misc2.py — 触发战吼后全体龙 +num（含自身）/
    非战吼打出不触发 / 对手战吼不触发 / Brann 式多次触发多次 buff /
    金色 4/4

    Params: {0}=2 {1}=2（36.2.2 基线，金色 =4/4）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_battlecry(g, minion=None, **kw):
            if minion is None:
                return
            d = g.db.get(source.card_id)
            g.run_actions([
                Buff(m, atk=d.num(0), health=d.num(1))
                for m in source.controller.board
                if not m.dead and m.race in _DRAGON_RACES])

        game.events.register(Listener(
            event=BATTLECRY_TRIGGER,
            owner=source,
            condition=lambda minion=None, **kw: (
                minion is not None
                and minion.controller is source.controller),
            callback=on_battlecry,
        ))
        return None


# ══════════════════ BGS_127 Molten Rock ══════════════════


class MoltenRockScript:
    """
    Natural language: After you play an Elemental, gain +{1} Health.

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         条件 = 打出的卡是 Minion、race ∈ (ELEMENTAL, ALL)、与
         source 同控制者。**含自身**（Molten Rock 是 Elemental，
         summon 先于 card_played fire → 打出自身即 +num(1) 生命）
      2. 触发: times 次独立 Buff(source, atk=0, health=num(1))
         ——数据核对: 基础/金色 CardDef 均只有 num(1)=1（num(0)
         缺失 → 攻击分量恒 0，结构性占位）; 金色 "@"" 后缀变体
         文本 "+{0}/+{1}" 的 num(0) 亦缺失（金色文本显示态
         "+1 Health twice" 为准）
      3. num(1) 缺失 → GameStateError（fail-loud）

    Test: test_batch_econ_misc2.py — 打出元素生命 +num(1)（攻不变）/
    打出非元素不触发 / 打出自身触发 / 金色两次

    Params: {1}=1（36.2.2 基线，金色同值; num(0) 数据缺失 → atk=0）;
    times=1（金色 times=2 文本字面量 "twice"）
    """

    times = 1   # 金色 "+{1} Health twice" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            health = _num(g, source, 1, "health gain")
            g.run_actions([
                Buff(source, atk=0, health=health)
                for _ in range(source.scripts.times)])

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Minion)
                and card.race in _ELEMENTAL_RACES
                and card.controller is source.controller),
            callback=on_played,
        ))
        return None


class MoltenRockGoldenScript(MoltenRockScript):
    """
    Natural language: After you play an Elemental, gain +{1} Health
    twice.

    Formal spec: 同基础版，times=2——每次打出元素获得两个独立
    +num(1) 生命实例（金色 CardDef num(1)=1）。

    Test: test_batch_econ_misc2.py — 金色打出元素生命 +2×num(1)

    Params: {1}=1（金色 CardDef）; times=2 文本字面量 "twice"
    """

    times = 2


# ══════════════════ BGS_104 Nomi, Kitchen Nightmare ══════════════════


class NomiScript:
    """
    Natural language: After you play an Elemental, give Elementals in
    the Tavern +{0}/+{1} this game.

    Formal spec:
      1. on_summon 注册 CARD_PLAYED 持久监听器（owner=source）:
         条件 = 打出的卡是 Minion、race ∈ (ELEMENTAL, ALL)、与
         source 同控制者（Nomi 自身无种族——不自计; 磁力吸附路径
         fire card_played → 打出元素磁力卡亦计）
      2. 触发 = 双件（Devilish Distractor 同构，Staff of Enrichment
         先例）:
         a) ApplyTavernBuff(hero, TavernBuff(+num(0)/+num(1),
            race_filter=ELEMENTAL, source_id))——持久面:
            hero.tavern_buffs 登记，refresh_tavern 对新入馆随从
            自动应用（引擎已接线; race_filter 匹配 ELEMENTAL 或
            ALL——Amalgam 规则）
         b) BuffCurrentTavern(hero, 同一 TavernBuff)——立即面对当前
            馆内全部 Elemental 施加
      3. 金色版文本同构（金色 num=8/8）→ 同一脚本类注册两个 id

    Test: test_batch_econ_misc2.py — 打出元素后馆内元素 +num 而非
    元素不变 / tavern_buffs 登记且 race_filter=ELEMENTAL / 刷新后
    新入馆元素自动获得 / 打出非元素不触发 / 金色 8/8

    Params: {0}=4 {1}=4（36.2.2 基线，金色 =8/8）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            d = g.db.get(source.card_id)
            tb = TavernBuff(atk=d.num(0), health=d.num(1),
                            race_filter=Race.ELEMENTAL,
                            source_id=source.card_id)
            g.run_actions([ApplyTavernBuff(source.controller, tb),
                           BuffCurrentTavern(source.controller, tb)])

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Minion)
                and card.race in _ELEMENTAL_RACES
                and card.controller is source.controller),
            callback=on_played,
        ))
        return None


# ══════════════════ 以下 DEFERRED（不注册 REGISTRY） ══════════════════


class FallingSkyGolemScript:
    """
    Natural language: Divine Shield. Has +{0}/+{1} for each Deathrattle
    you've triggered this game <i>(wherever this is).</i>

    Status: DEFERRED — requires 动态 atk/health 脚本接线

    Dependency（引擎缺口，主线处理）:
      - Entity.atk / Entity.max_health（entity.py:94-127）只计算
        base + buffs + aura，**不查询** scripts 的 "atk"/"health"
        钩子（SOP §2 声明了该钩子但全库无 call_script("atk"/
        "health") 调用点——combat.py 攻击力快照读 attacker.atk
        属性同样不经过脚本）
      - "for each Deathrattle you've triggered this game (wherever
        this is)" = 全区域（手牌/棋盘/酒馆）动态属性: 当前值 =
        基础 + hero.COUNTER_DEATHRATTLES × num(0)/num(1)，计数本体
        已就绪（game.py 战斗+招募亡语触发均 +1，tags.py 1047）。
        Buff-监听器近似（deathrattle_trigger 逐次加 buff）不满足
        "(wherever this is)" 的手牌/酒馆静态读数与入场回溯
        （打出前已触发的亡语数应立即体现在属性上）→ 禁止近似实现
      - 需主线在 Entity.atk/max_health 读点接入
        call_script("atk"/"health")（返回 None 时回落现行为）

    Test: test_batch_econ_misc2.py — 守护测试: DEFERRED 不注册

    Params: {0}=4 {1}=2（36.2.2 基线，金色 =8/4）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        return None


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    """注册本批次全部 OK 脚本（含金色 id），返回注册的 card_id 列表。

    BG35_342 / BG35_342_G DEFERRED——不注册（audit_card_registry_v2
    将其计为缺口，属预期，见 FallingSkyGolemScript docstring）。
    """
    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _registry.register(card_id, script_cls)
        registered.append(card_id)

    _add("BG34_950", StoneAgeSlabScript)
    _add("BG34_950_G", StoneAgeSlabGoldenScript)
    _add("BG35_155", TwistedWrathguardScript)
    _add("BG35_155_G", TwistedWrathguardGoldenScript)
    _add("BG36_211", CageGnawerScript)
    _add("BG36_211_G", CageGnawerScript)          # 金色 num=4/2 自然体现
    _add("BG36_352", UnboundTempestScript)
    _add("BG36_352_G", UnboundTempestGoldenScript)
    _add("BG36_523", EnterprisingEscapeeScript)
    _add("BG36_523_G", EnterprisingEscapeeGoldenScript)  # num(3)=2 体现
    _add("BG36_622", TorrentialRuinerScript)
    _add("BG36_622_G", TorrentialRuinerScript)     # 金色 num=4/6 自然体现
    _add("BG36_640", GatekeeperAmalgamScript)
    _add("BG36_640_G", GatekeeperAmalgamGoldenScript)
    _add("BG36_733", EredarEscapistScript)
    _add("BG36_733_G", EredarEscapistGoldenScript)
    _add("BG36_762", DevilishDistractorScript)
    _add("BG36_762_G", DevilishDistractorScript)   # 金色 num=4/4 自然体现
    _add("BG36_921", FleeingFugitiveScript)
    _add("BG36_921_G", FleeingFugitiveScript)      # 金色 num(0)=2 自然体现
    _add("BGS_004", WrathWeaverScript)
    _add("TB_BaconUps_079", WrathWeaverGoldenScript)
    _add("BGS_041", KalecgosScript)
    _add("TB_BaconUps_109", KalecgosScript)        # 金色 num=4/4 自然体现
    _add("BGS_127", MoltenRockScript)
    _add("TB_Baconups_202", MoltenRockGoldenScript)
    _add("BGS_104", NomiScript)
    _add("TB_BaconUps_201", NomiScript)            # 金色 num=8/8 自然体现
    return registered
