"""磁力批次（作业单 2026-08-21，8 张磁力/机械池随从 + 金色注册）。

实现状态: 6/8 OK，2 DEFERRED（引擎缺口，见下）; 无 AMBIGUOUS。

数据核实（2026-08-21，CardDB.load(data) 按 id 打印）:
  BG26_146 Lullabot          2/2 T1 magnetic; EoT "+1 Health"（文本字面量，
                             金色 BG26_146_G "+2 Health"）
  BG26_147 Accord-o-Tron     3/3 T3 magnetic; SoT "gain 1 Gold"（文本字面量，
                             金色 "gain 2 Gold"）
  BG26_149 Polarizing Beatboxer 5/10 T7; "it also Magnetizes to this"
                             （金色 "…twice"）
  BG29_503 Clunker Junker    3/4 T4 battlecry [Targeted]（wiki Wiki tags
                             确认）; 金色 "Discover 2 Mechs"
  BG31_177 Mechagnome Interpreter 3/1 T2; +{0}/+{1} = num 3/1（金色 6/2）
  BG32_172 Auto Assembler    2/2 T4 magnetic + DR; token 经
                             evolution_card_id=108432 → BG_TTN_401
                             Ancestral Automaton 3/4（金色 BG_TTN_401_G 6/8）
  BG36_851 Spark Snapper     5/5 T5; "{1}/{1} Satellite" = num(1)=2（金色 4）
  BG36_853 Glambot           4/4 T4; "{0}/{1} Satellite" = num 4/4

Satellite token 裁定（作业单要求 db 核实）: BG31_171t（6/6，wiki
"Related with" 列 Glambot）——token def 属性是**视觉快照**，实际属性由
生成卡 num 参数动态设定（Beetle 系先例: BG28_603t 2/2 + 召唤卡 {0}/{1}
覆盖）。6/6 = Spark Snapper 基础 2/2 + 2 次 improve，与 "improve this =
每次触发 +印面值"（Tasty Lobster / Baby Elekk / Burth 家族约定）互证。

引擎缺口（DEFERRED 依赖，已报告主线）:
  G1. attach_magnetic 按 CardDef 属性合并，官方语义是**实体当前属性**
      （含 buff）并入——动态尺寸 token（Satellite 2/2/4/4 vs def 6/6）
      与被 buff 过的磁力随从均无法表达 → BG36_851 / BG36_853 DEFERRED。
      （attach 后负 Buff 修正不可行: add_buff 仅对 health>0 抬当前血量，
      当前血/max 血会偏离官方。）
  G2. card_played（法术路径）/spellcraft_cast/tavern_spell_cast 均不携带
      target——"cast a spell on a Mech" 类监听无法实现 → BG36_853 依赖。
  G3. 金色卡定义 keywords 导出为空（bg_cards.json 金色条目无 magnetic/
      deathrattle 标志）→ 金色磁力随从 play_minion 吸附路径被
      has(MAGNETIC) 闸门拒绝、金色亡语附件不给宿主置 DEATHRATTLE 标签
      （亡语钩子本身不设门、仍触发）。测试侧 bootstrap 手工置 tag
      （Handless Forsaken REBORN 自举同款先例）; 根修在数据生成器
      （金色条目补 keywords）或 create_minion 金色路径回基础 def 补标。

Clunker Junker 候选裁定: Discover 选项 = 池内 **Magnetic** Mech（文本
"Discover a Mech to Magnetize to it"——非磁力机械无法被磁力吸附，选项
必须可执行）; 无 tier 上限（RULES §6.18 仅规定池约束 + 三选一，引擎
Discover 默认一致——主线若裁定 ≤ 酒馆等级，加 max_tier 即可）。选中走
minion_pool.acquire 占池（RULES §2.3）→ create_minion → attach_magnetic
（非入手——Discover.resolve 默认入手不适用，按 SOP 经验库 PendingChoice
自定义 resolve_callback 建模）。

Beatboxer 附加副本裁定: 副本为**生成**（copy 语义，不占池——同 Summon/
SummonPlainCopy; 非 "Get" 路径）; 金色附件复制为金色（经 triple_base_id
解析 + golden=True，金色=独立卡定义）。宿主被出售时引擎本就不回池磁力
附件，无池膨胀风险。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainGold
from hsrl2.actions.discover import _pool_candidates   # 池过滤唯一权威
from hsrl2.events import Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import Race, Zone

# Discover 三选一（RULES §6.18 "从随机三张卡牌中选择一张"——文本字面量 3）
_DISCOVER_OPTIONS = 3

# token id（数据核实见模块 docstring; batch_deathrattle 模块常量先例——
# 合并钩子中 source=宿主，无法经 source.card_id 解析数据链，金色版经
# create_minion(golden=True) → db.golden_version 解析 BG_TTN_401_G）
_TOKEN_ANCESTRAL_AUTOMATON = "BG_TTN_401"


def _magnetic_copy(game, attached: Minion, hero) -> Minion:
    """attached 的同版副本实体（金色附件 → 基础 id + golden=True，
    金色=独立卡定义; 普通附件 → 同 card_id）。不占池（生成语义）。"""
    md = game.db.get(attached.card_id)
    if md is not None and md.is_golden_def and md.triple_base_id is not None:
        base = game.db.by_dbf(md.triple_base_id)
        if base is not None:
            return game.create_minion(base.id, controller=hero, golden=True)
    return game.create_minion(attached.card_id, controller=hero)


# ══════════════════ BG26_146 Lullabot ══════════════════


class LullabotScript:
    """
    Natural language: [x]<b>Magnetic</b>
    At the end of your turn,
    gain +1 Health.

    Formal spec:
      1. end_of_turn 钩子（source=宿主——磁力效果合并: 宿主触发 EoT 时
         附件同钩子以宿主为 source 一并触发; 正常打出时 source=自身）:
         Buff(source, health=+1)——"gain" 主体即该随从（吸附后=宿主）
      2. 吸附时属性/关键词并入由引擎 attach_magnetic 处理，脚本不感知
      3. 金色注册类 +2（金色文本总额，EoT 单次触发非战吼×2 模型）

    Test: test_batch_magnetic.py — 吸附路径宿主 EoT +1 血（叠加吸附
    +2/+2 之后）; 正常打出路径自身 EoT +1; 金色 +2

    Params: 无模板参数（"+1 Health" 为文本字面量; 金色 "+2"）
    """

    health_gain = 1   # 文本字面量

    @classmethod
    def end_of_turn(cls, source, game, ctx):
        # classmethod: 合并路径 source=宿主（source.scripts 是宿主脚本类），
        # 经 cls 取本类数值（金色注册子类覆盖）
        return Buff(source, health=cls.health_gain)


class LullabotGoldenScript(LullabotScript):
    """
    Natural language: [x]<b>Magnetic</b>
    At the end of your turn,
    gain +2 Health.

    Formal spec:
      1. 同基础版，health_gain=2（金色文本字面量，EoT 单次触发总额）

    Test: 金色吸附后宿主 EoT +2 血

    Params: 无模板参数（"+2 Health" 为金色文本字面量）
    """

    health_gain = 2   # 金色文本字面量


# ══════════════════ BG26_147 Accord-o-Tron ══════════════════


class AccordOTronScript:
    """
    Natural language: [x]<b>Magnetic</b>
    At the start of your turn,
    gain 1 Gold.

    Formal spec:
      1. start_of_turn 钩子（source=宿主——效果合并，_begin_recruit_for
         对棋盘随从触发 SoT → 宿主触发 → 附件以宿主为 source 合并触发，
         吸附后不在棋盘也能触发; 正常打出时 source=自身）:
         GainGold(source.controller, 1)——金币归控制者英雄
      2. 金色注册类 2（金色文本 "gain 2 Gold" 总额）

    Test: 吸附路径宿主 SoT → 英雄金币 +1; 正常打出路径同效; 金色 +2

    Params: 无模板参数（"1 Gold" 为文本字面量; 金色 "2 Gold"）
    """

    gold_gain = 1   # 文本字面量

    @classmethod
    def start_of_turn(cls, source, game, ctx):
        # classmethod: 合并路径 source=宿主，经 cls 取本类数值
        hero = source.controller
        if hero is None:
            return None
        return GainGold(hero, cls.gold_gain)


class AccordOTronGoldenScript(AccordOTronScript):
    """
    Natural language: [x]<b>Magnetic</b>
    At the start of your turn,
    gain 2 Gold.

    Formal spec:
      1. 同基础版，gold_gain=2（金色文本字面量，SoT 单次触发总额）

    Test: 金色吸附后宿主 SoT → 英雄金币 +2

    Params: 无模板参数（"2 Gold" 为金色文本字面量）
    """

    gold_gain = 2   # 金色文本字面量


# ══════════════════ BG26_149 Polarizing Beatboxer ══════════════════


class PolarizingBeatboxerScript:
    """
    Natural language: Whenever you <b>Magnetize</b> to a different minion,
    it also <b>Magnetizes</b> to this.

    Formal spec:
      1. on_summon 注册 "magnetized"（事件 kwargs host=/attached=）持久
         监听器（owner=自身，离场/出售自动注销）
      2. 条件: host 不是自身（"different minion"）且 host.controller 是
         自身控制者（"you Magnetize"）——对 Beatboxer 自身的吸附不触发
         （无递归: 附加吸附 fire 的 magnetized host=自身 → 条件排除）
      3. 动作: 生成 attached 的同版副本（_magnetic_copy; 金色附件→金色
         副本; 不占池——生成语义）→ attach_magnetic(控制者, 副本, 自身)
      4. 金色注册类 copies=2（金色文本 "…Magnetizes to this twice" =
         两个独立副本，各自触发 magnetized 事件——host=自身均被条件排除）

    Test: 磁力吸附到其他友方机械 → Beatboxer +2/+2（BG26_146 副本）;
    吸附到 Beatboxer 自身无附加副本; 敌方英雄磁力化不触发; 金色两副本;
    池可用量不变（副本不占池）; 吸附的 Lullabot 副本 EoT 合并生效

    Params: 无模板参数（数量为文本字面量 1; 金色 "twice"=2）
    """

    copies = 1   # 文本字面量 "it also Magnetizes"

    @staticmethod
    def on_summon(source, game, ctx):
        beatboxer = source

        def condition(host=None, attached=None, **kw) -> bool:
            return (host is not None
                    and host is not beatboxer
                    and host.controller is beatboxer.controller)

        def on_magnetize(g, host=None, attached=None, **kw):
            hero = beatboxer.controller
            if hero is None or attached is None:
                return
            for _ in range(beatboxer.scripts.copies):
                copy = _magnetic_copy(g, attached, hero)
                g.attach_magnetic(hero, copy, beatboxer)

        game.events.register(Listener(
            event="magnetized", owner=source,
            condition=condition, callback=on_magnetize))
        return None


class PolarizingBeatboxerGoldenScript(PolarizingBeatboxerScript):
    """
    Natural language: Whenever you <b>Magnetize</b> to a different minion,
    it also <b>Magnetizes</b> to this twice.

    Formal spec:
      1. 同基础版，copies=2——两个独立副本先后吸附到自身（金色文本
         "twice"）

    Test: 金色 Beatboxer 场上磁力化 → 自身 +4/+4（BG26_146 ×2）

    Params: 无模板参数（数量为金色文本字面量 2）
    """

    copies = 2   # 金色文本字面量 "twice"


# ══════════════════ BG29_503 Clunker Junker ══════════════════


class ClunkerJunkerScript:
    """
    Natural language: <b>Battlecry:</b> Choose a friendly Mech.
    <b>Discover</b> a Mech to <b>Magnetize</b> to it.

    Formal spec:
      1. 双重定向: needs_target=True（wiki [Targeted] 确认玩家选择），
         target_candidates = 棋盘存活友方 Mech（含 ALL 种族; 自身入场
         在战吼前，自身也是合法目标）; 无候选 → 战吼落空随从照常入场
         （引擎行为）
      2. 战吼（ctx["target"] 给定）: 候选 = 池内 Magnetic Mech
         （_pool_candidates(race=MECH) 后按 keywords 过滤——非磁力机械
         无法被吸附; 池剩余量约束，RULES §6.18）; 无候选 → 落空
      3. rng.sample 抽 3 个不同 id → PendingChoice(kind="discover_minion")
         入队（队列化），自定义 resolve（Discover 默认 resolve 是入手，
         不适用）: minion_pool.acquire 占池（RULES §2.3）→ create_minion
         → attach_magnetic(控制者, 实体, 目标1)。目标此刻已离场/死亡 →
         落空（未占池直接返回）
      4. 金色 = 同一脚本类: 引擎对金色战吼触发 2 次 → 两次独立 Discover
         （金色文本 "Discover 2 Mechs"），目标同为 ctx["target"]

    Test: 打出（带目标）→ pending_choices 出现 discover_minion 且选项
    全为 magnetic Mech; choose(0) → 目标属性 += 选中卡 def 属性、池对应
    id 减 1; 金色两次选择; target_candidates 排除非机械

    Params: 无模板参数（Discover 三选一为 RULES §6.18 文本字面量 3）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in (Race.MECH, Race.ALL)]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        cands = [cid for cid in _pool_candidates(game, race=Race.MECH)
                 if "magnetic" in game.db.get(cid).keywords]
        if not cands:
            return None
        k = min(_DISCOVER_OPTIONS, len(cands))
        options = game.rng.sample(cands, k, label="clunker_junker_discover")

        def resolve(pick_id: str) -> None:
            if target.dead or target.zone != Zone.PLAY:
                return   # 目标离场 → 落空（未占池）
            if not game.minion_pool.acquire(pick_id):
                raise GameStateError(
                    f"Clunker Junker: pool acquire failed for {pick_id}")
            m = game.create_minion(pick_id, controller=hero)
            game.attach_magnetic(hero, m, target)

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_minion", resolve_callback=resolve))
        return None


# ══════════════════ BG31_177 Mechagnome Interpreter ══════════════════


class MechagnomeInterpreterScript:
    """
    Natural language: [x]Whenever you play or
    <b>Magnetize</b> a Mech,
    give it +{0}/+{1}.

    Formal spec:
      1. on_summon 注册两个持久监听器（owner=自身，离场注销; 战斗快照
         恢复语义——战斗战死不注销）:
         a) "card_played": 条件 isinstance(card, Minion) 且 card.race ∈
            (MECH, ALL) 且 card.controller 是自身控制者 且 card.zone ==
            PLAY——**zone 判别是关键**: 磁力吸附路径 play_minion 也会
            fire card_played（card=磁力随从，此时 zone 已 REMOVED），
            该情形由 b) 盖、a) 必须跳过（否则双份 buff）。动作:
            Buff(该随从, +num(0), +num(1))（"play a Mech" 含自身——
            打出 Interpreter 时监听器已注册，自身也获 buff，官方语义）
         b) "magnetized": 条件 host.controller 是自身控制者。动作:
            Buff(host, +num(0), +num(1))——"it" = 被磁力化的 Mech，
            已并入宿主 → buff 落宿主
      2. 数值 source.card_id 的 CardDef.num(0)/num(1)——金色注册同类，
         金色 def num 自然 6/2
      3. attached 恒为 Mech（Magnetic 关键词仅机械族），b) 不再验种族

    Test: 正常打出 Mech → +num(0)/+num(1); 磁力吸附路径宿主恰得一份
    （非两份）; 打出 Interpreter 自身也获 buff; 金色 6/2

    Params: {0}=3 {1}=1（36.2.2 基线，金色 6/2 经金色 CardDef 体现）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        interp = source

        def _buff(g, target):
            d = g.db.get(interp.card_id)
            g.run_actions(Buff(target, atk=d.num(0), health=d.num(1)))

        game.events.register(Listener(
            event="card_played", owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Minion)
                and not card.dead
                and card.zone == Zone.PLAY
                and card.controller is interp.controller
                and card.race in (Race.MECH, Race.ALL)),
            callback=lambda g, card=None, **kw: _buff(g, card)))
        game.events.register(Listener(
            event="magnetized", owner=source,
            condition=lambda host=None, attached=None, **kw: (
                host is not None
                and host.controller is interp.controller),
            callback=lambda g, host=None, **kw: _buff(g, host)))
        return None


# ══════════════════ BG32_172 Auto Assembler ══════════════════


class AutoAssemblerScript:
    """
    Natural language: [x]<b>Magnetic</b>
    <b>Deathrattle:</b> Summon an
    __Ancestral Automaton.

    Formal spec:
      1. deathrattle 钩子（source=宿主——效果合并; 正常打出时 source=
         自身），直调模式（batch_deathrattle 实测引擎约束: 亡语返回
         Action 会触发濒死随从二次处理）: 在宿主原位（亡语先于移除，
         zone_position 有效）召唤 1 个 Ancestral Automaton
      2. token = BG_TTN_401（3/4 T2 Mech; 数据链互证: 本卡
         evolution_card_id=108432 即其 dbf——合并钩子中 source=宿主，
         运行时无法经 source.card_id 解析，故用模块常量，金色注册类
         golden=True → BG_TTN_401_G）; 池卡但亡语召唤不占池——Summon
         语义，Eternal Knight 先例
      3. 吸附时 DEATHRATTLE 标签并入宿主由 attach_magnetic 处理

    Test: 吸附路径宿主死亡 → 宿主位出现 BG_TTN_401（3/4）; 正常打出
    路径同效; 金色 → BG_TTN_401_G 金色 6/8

    Params: 无模板参数（token 属性来自 BG_TTN_401 CardDef）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        m = game.create_minion(_TOKEN_ANCESTRAL_AUTOMATON, controller=hero)
        game.summon(hero, m, source.zone_position)
        return None


class AutoAssemblerGoldenScript(AutoAssemblerScript):
    """
    Natural language: [x]<b>Magnetic</b>
    <b>Deathrattle:</b> Summon a
    Golden Ancestral
    Automaton.

    Formal spec:
      1. 同基础版，但 create_minion(token, golden=True) → 金色卡定义
         BG_TTN_401_G（6/8）——非数值×2 近似

    Test: 金色吸附后宿主死亡 → BG_TTN_401_G（6/8，is_golden）

    Params: 无模板参数（金色 token 属性来自金色 CardDef BG_TTN_401_G）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        m = game.create_minion(_TOKEN_ANCESTRAL_AUTOMATON, controller=hero,
                               golden=True)
        game.summon(hero, m, source.zone_position)
        return None


# ══════════════════ BG36_851 Spark Snapper（DEFERRED）══════════════════


class SparkSnapperScript:
    """
    Natural language: [x]Whenever you play a Mech,
    <b>Magnetize</b> a {1}/{1}
    Satellite to it and
    improve this.

    语义核定（供解冻后实现）:
      - Satellite token = BG31_171t（wiki "Related with" 互证; 属性由
        生成卡参数动态覆盖，Beetle 先例）; 基础 {1}/{1} = num(1)=2，
        金色 num(1)=4
      - "improve this" = 每次触发 Satellite 尺寸 +印面值（+2/+2 基础、
        金色 +4/+4; Tasty Lobster/Baby Elekk/Burth 家族约定; token def
        6/6 = 基础 2/2 + 2 次 improve 互证）
      - "play a Mech" = 正常打出路径（card_played + zone==PLAY 判别，
        磁力化不触发——同 Interpreter a) 分支）

    Status: DEFERRED — requires attach_magnetic 支持实体属性/属性覆盖
    Dependency: G1（引擎 attach_magnetic 按 CardDef 属性合并; 官方磁力
    并入实体当前属性。动态尺寸 Satellite（2/2 起步 vs def 6/6）无法经
    attach 正确表达; 事后负 Buff 修正会令当前血量偏离——add_buff 仅对
    health>0 抬当前血）。解法: 主线将 attach_magnetic 改为读实体
    atk/max_health 快照（顺带修复被 buff 磁力随从合并失真），脚本侧
    create_minion(BG31_171t) + BASE 覆盖为 num(1)+improve×印面值后 attach
    """
    pass


# ══════════════════ BG36_853 Glambot（DEFERRED）══════════════════


class GlambotScript:
    """
    Natural language: [x]Whenever you cast a spell
    on a Mech, <b>Magnetize</b> a
    {0}/{1} Satellite to it.

    语义核定（供解冻后实现）:
      - {0}/{1} = num(0)/num(1) = 4/4（金色同值 + "twice" 两个）
      - Satellite token = BG31_171t，属性覆盖 4/4（Beetle 先例）
      - 事件: 法术施放且 target 为友方 Mech

    Status: DEFERRED — requires (a) 法术施放事件携带 target; (b) G1
    Dependency: G2（card_played/spellcraft_cast/tavern_spell_cast 均无
    target 参数——"cast a spell on a Mech" 无法监听）+ G1（4/4 Satellite
    vs token def 6/6，同 Spark Snapper）。解法: 主线在 _finish_play_spell
    的 card_played（或新 spell_cast 事件）附 target kwarg + G1 修复
    """
    pass


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    from hsrl2.scripts.registry import register as _register

    _register("BG26_146", LullabotScript)
    _register("BG26_146_G", LullabotGoldenScript)
    _register("BG26_147", AccordOTronScript)
    _register("BG26_147_G", AccordOTronGoldenScript)
    _register("BG26_149", PolarizingBeatboxerScript)
    _register("BG26_149_G", PolarizingBeatboxerGoldenScript)
    _register("BG29_503", ClunkerJunkerScript)
    _register("BG29_503_G", ClunkerJunkerScript)   # 金色=引擎战吼×2
    _register("BG31_177", MechagnomeInterpreterScript)
    _register("BG31_177_G", MechagnomeInterpreterScript)   # num 自然 6/2
    _register("BG32_172", AutoAssemblerScript)
    _register("BG32_172_G", AutoAssemblerGoldenScript)
    # BG36_851/BG36_853 已由 batch_consume 解冻实现（依赖修复后），
    # 本批 DEFERRED 占位注册已移除（主线清理 2026-08-21）

    return [
        "BG26_146", "BG26_146_G",
        "BG26_147", "BG26_147_G",
        "BG26_149", "BG26_149_G",
        "BG29_503", "BG29_503_G",
        "BG31_177", "BG31_177_G",
        "BG32_172", "BG32_172_G",
    ]
