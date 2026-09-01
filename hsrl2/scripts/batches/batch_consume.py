"""批次 consume — 吞噬家族 4 张 + 解冻 5 张（作业单 2026-08-21）。

A. consume 批: BG21_004 Insatiable Ur'zul / BG23_357 Mind Muck /
   BG28_633 Felboar / BG34_500 Flaming Enforcer（含金色 id）。
B. 解冻批（引擎依赖 Wave2 已修）: BG36_851 Spark Snapper /
   BG36_853 Glambot（attach_magnetic 实体属性 + card_played target
   kwarg）/ BG32_330 Flighty Scout（combat.py 3b 手牌 SoC 钩子）/
   BG36_620 Boom-in-a-Box（game._active_combat 战斗对暴露）/
   BG36_351 Moat Custodian（tags.py ELEMENTAL_EXTRA_ATK 1057 入册）。

实现状态: 9/9 OK（18 个注册 id）; 无 AMBIGUOUS，2 项 SPEC_GAP 见下。

语义核定（2026-08-21，hearthstone.wiki.gg 官方页 + 官方补丁说明）:
  - Mind Muck: Wiki tags [Targeted]+[Random]——友方恶魔玩家定向选择、
    馆内受害者随机（补丁 24.2 dev comment 原文 "The consumed minion
    is randomly chosen"）。
  - Felboar: Wiki tags 含 "Tavern spell-related"——计数对象为**酒馆
    法术**; 补丁 29.2.2.198608 "Fixed a bug where Felboar would consume
    a minion in the Tavern before the Tavern Spell takes effect"——
    吞噬必须晚于法术效果结算。引擎 tavern_spell_cast 在 on_play **之前**
    fire（game._finish_play_spell 顺序），直接挂载会复现该官方已修复
    bug → 本批改挂 card_played（法术效果结算后 fire）+ is_pool_spell
    过滤（与引擎 TAVERN_SPELLS_CAST_* 计数口径一致）。
  - 吞噬家族金色文本一律 "gain **double** its stats"（单次吞噬、双倍
    属性增益），非 "twice"（两次独立吞噬）——金色触发类效果由脚本
    mult=2 表达。
  - Spark Snapper/Glambot 金色: wiki 金色渲染文本陈旧（36.2.2 改动后
    未重生成），数值以 hsdata CardDefs.xml 导出为准（Snapper num(1)
    基础 2/金色 4; Glambot num 4/4 + "twice"）。

SPEC_GAP（报告主线，Breakout 先例同款）:
  1. Mind Muck 金色为"单次吞噬+双倍属性"总额型战吼，引擎对金色战吼
     恒触发 2 次 → 金色类以实体级守卫仅首次结算; Brann+金色 / 重触发
     金色不放大（官方应各为 2 次）。需引擎区分"金色总额型"战吼计数。
  2. 效果施法（"Cast X" 类，batch_rally2 统一裁定）不广播 card_played
     → Glambot / Felboar 对效果施法路径不触发。需"效果施法"专用事件。

注册冲突治理（batch_magnetic 遗留）:
  batch_magnetic 已注册 BG36_851/853 的 DEFERRED 空壳占位（该文件本
  作业禁改）。registry.register 对重复 id 抛 KeyError 且批次发现顺序
  无保证（pkgutil.iter_modules 不排序）→ 本模块 import 时对
  registry.register 安装窄域容错: 仅对这 4 个占位 id，"有钩子实现"
  的一方胜出（与注册顺序无关），其余 id 保持原 fail-loud 语义。
  主线后续应删除 batch_magnetic 的占位注册并移除本补丁。

引擎缺口报告（本批新增，主线处理）:
  1. tavern_spell_cast 时序先于法术 on_play 结算（见上 Felboar 依据）
     ——事件应后移或增加 spell_resolved 事件。
  2. elemental_buff()（元素 give-效果统一出口）暂置于本文件——主线
     入册 actions/racefx.py 后迁移（tavern_spell_buff 同构）; 消费方
     为 Sand Swirler BG32_841（batch_battlecry DEFERRED）等待解冻。
"""

from __future__ import annotations

import hsrl2.scripts.registry as _registry_mod
from hsrl2.actions import Buff, Hit
from hsrl2.actions.consume import ConsumeMinion, ConsumeRandomTavernMinion
from hsrl2.actions.stats import Buff as BuffAction
from hsrl2.events import CARD_PLAYED, Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

# ── 注册冲突治理（详见模块 docstring）──

_ORIG_REGISTER = _registry_mod.register
_STUB_REPLACE_IDS = frozenset({
    "BG36_851", "BG36_851_G", "BG36_853", "BG36_853_G",
})


def _implemented(cls) -> bool:
    """脚本类是否有任何已实现钩子（DEFERRED 空壳无属性）。"""
    return any(hasattr(cls, h) for h in _registry_mod.VALID_HOOKS)


def _tolerant_register(card_id: str, script_class) -> None:
    existing = _registry_mod.REGISTRY.get(card_id)
    if existing is None or card_id not in _STUB_REPLACE_IDS:
        _ORIG_REGISTER(card_id, script_class)   # 其余 id 保持 KeyError
        return
    if _implemented(script_class) and not _implemented(existing):
        _registry_mod.REGISTRY[card_id] = script_class


_registry_mod.register = _tolerant_register

# ── 通用帮助 ──

# Satellite token（wiki Glambot "Related with" 互证; 属性由生成卡参数
# 动态覆盖——Beetle 系先例，batch_magnetic docstring 核定）
SATELLITE_ID = "BG31_171t"

_DEMON_RACES = (Race.DEMON, Race.ALL)   # ALL 视为所有种族 (RULES §6.18)
_MECH_RACES = (Race.MECH, Race.ALL)


def _consume_random_tavern(game, demon: Minion, mult: int) -> None:
    """随机吞噬 demon 控制者酒馆一随从并按 mult 放大属性增益。

    经 ConsumeRandomTavernMinion（选择/池记账/事件唯一权威）同步执行;
    mult>1（金色 "gain double its stats"）以吞噬前后属性差值补
    (mult-1)×Buff——受害者属性快照的等价推导，不复制选择逻辑。
    空酒馆自然落空（Action 语义）。
    """
    before_atk = demon.atk
    before_hp = demon.max_health
    ConsumeRandomTavernMinion(demon).do(game)
    gain_atk = demon.atk - before_atk
    gain_hp = demon.max_health - before_hp
    if mult > 1 and (gain_atk or gain_hp):
        BuffAction(demon, atk=gain_atk * (mult - 1),
                   health=gain_hp * (mult - 1)).do(game)


def _make_satellite(game, hero, atk: int, health: int) -> Minion:
    """创建指定尺寸的 Satellite token（BASE 覆盖，Beetle 先例）。"""
    sat = game.create_minion(SATELLITE_ID, controller=hero)
    sat.set(GameTag.BASE_ATK, atk)
    sat.set(GameTag.BASE_HEALTH, health)
    sat.set(GameTag.HEALTH, health)
    return sat


def elemental_buff(target, atk: int, health: int) -> Buff:
    """元素 give-效果出口（本地帮助，主线入册 racefx 后迁移）:
    基值 + hero 的 ELEMENTAL_EXTRA_ATK(1057)/ELEMENTAL_EXTRA_HEALTH(1055)
    ——tavern_spell_buff 同构; 设置方为 Moat Custodian / Glowing Cinder /
    （解冻后的）Sand Swirler。"""
    hero = getattr(target, "controller", None)
    extra_atk = hero.get(GameTag.ELEMENTAL_EXTRA_ATK, 0) if hero else 0
    extra_health = (hero.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0)
                    if hero else 0)
    return Buff(target, atk=atk + extra_atk, health=health + extra_health)


# ══════════════════ BG21_004 Insatiable Ur'zul ══════════════════


class InsatiableUrZulScript:
    """
    Natural language: [x]<b>Taunt</b>. After you play a
    Demon, consume a random
    minion in the Tavern to gain
    its stats.

    Formal spec:
      1. on_summon 注册 card_played 持久监听器（owner=source，离场/出售
         自动注销; 战斗快照恢复语义）: 条件 isinstance(card, Minion) 且
         card.zone == PLAY 且 card.controller 友方 且 race ∈ (DEMON, ALL)
         → _consume_random_tavern(source, mult)。打出 Ur'zul 自身同样
         触发（自身是 Demon，Mechagnome Interpreter 官方语义同款）;
         磁力路径不适用（Demon 无磁力卡）
      2. Taunt 由 create_minion 关键词映射（CardDef 权威）
      3. 金色注册类 mult=2（金色文本 "gain double its stats"——单次
         吞噬双倍属性，非两次吞噬）
      4. 触发型效果（非战吼）——无引擎金色双触发问题，mult 直接表达

    Test: test_batch_consume.py — 打出 Demon 后吞噬馆内随从获得属性 /
    打出非 Demon 不触发 / 金色双倍 / 空酒馆落空

    Params: 无模板参数（吞噬增益 = 受害者运行时属性）
    """

    mult = 1   # 金色 "double" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            _consume_random_tavern(g, source, source.scripts.mult)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Minion)
                and not card.dead
                and card.zone == Zone.PLAY
                and card.controller is source.controller
                and card.race in _DEMON_RACES),
            callback=on_played,
        ))
        return None


class InsatiableUrZulGoldenScript(InsatiableUrZulScript):
    """
    Natural language: [x]<b>Taunt</b>. After you play a
    Demon, consume a random
    minion in the Tavern to gain
    double its stats.

    Formal spec: 同基础版，mult=2——单次吞噬、属性增益 ×2。

    Test: test_batch_consume.py — 金色吞噬增益 = 2× 受害者属性

    Params: 无模板参数（"double" 为金色文本字面量）
    """

    mult = 2


# ══════════════════ BG23_357 Mind Muck ══════════════════


class MindMuckScript:
    """
    Natural language: [x]<b>Battlecry:</b> Choose a friendly
    Demon. It consumes a
    minion in the Tavern
    to gain its stats.

    目标选择裁定（wiki Wiki tags 2026-08-21 核实）: [Targeted] +
    [Random]——友方恶魔由玩家定向选择（needs_target 协议），馆内受害者
    随机（补丁 24.2 dev comment "The consumed minion is randomly
    chosen"）。禁止双重定向近似。

    Formal spec:
      1. needs_target=True + target_candidates = 棋盘存活友方 Demon
         （含 ALL; 自身先入场也是合法目标——引擎打出顺序）; 无候选 →
         战吼落空随从照常入场（引擎行为）
      2. battlecry（ctx["target"] 给定）: _consume_random_tavern(target,
         1)——**目标恶魔**（非 source）获得吞噬增益
      3. 金色见 MindMuckGoldenScript

    Test: test_batch_consume.py — 选择后目标恶魔吞噬获得属性 / 候选
    排除非恶魔 / 空酒馆落空 / 金色单次吞噬双倍

    Params: 无模板参数（吞噬增益 = 受害者运行时属性）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in _DEMON_RACES]

    @staticmethod
    def battlecry(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None or target.dead or target.zone != Zone.PLAY:
            return None
        _consume_random_tavern(game, target, 1)
        return None


class MindMuckGoldenScript(MindMuckScript):
    """
    Natural language: [x]<b>Battlecry:</b> Choose a friendly
    Demon. It consumes a
    _minion in the Tavern
    ___to gain double its stats.

    Formal spec:
      1. 金色文本为"单次吞噬+双倍属性"总额型（非 twice）——引擎对金色
         战吼恒触发 2 次会得到 2 次吞噬（错误）。守卫: 每实体仅首次
         触发结算完整金色效果（mult=2），后续 no-op（实体级
         _muck_resolved 动态属性，Bilgewater Breakout 先例）
      2. SPEC_GAP（模块 docstring #1）: Brann+金色 / 重触发金色不放大
         （官方应各为 2 次独立吞噬）

    Test: test_batch_consume.py — 金色恰吞噬 1 只（馆内剩 1）且目标
    恶魔获 2× 受害者属性

    Params: 无模板参数（"double" 为金色文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        if getattr(source, "_muck_resolved", False):
            return None
        source._muck_resolved = True
        target = (ctx or {}).get("target")
        if target is None or target.dead or target.zone != Zone.PLAY:
            return None
        _consume_random_tavern(game, target, 2)
        return None


# ══════════════════ BG28_633 Felboar ══════════════════


class FelboarScript:
    """
    Natural language: [x]After you cast {1} spells,
    consume a minion in the
    Tavern to gain its stats.
    <i>({0} left!)</i>

    Formal spec:
      1. on_summon 注册 card_played 持久监听器（owner=source）:
         条件 isinstance(card, Spell) 且 card.controller 友方 且
         db(card).is_pool_spell——即**酒馆法术**（wiki tags
         "Tavern spell-related"; 与引擎 TAVERN_SPELLS_CAST_* 口径一致，
         血宝石/Spellcraft 不计）。**不挂 tavern_spell_cast**: 该事件
         先于法术 on_play 结算 fire，直接吞噬会复现官方 29.2.2 已修复
         的 bug（"consume ... before the Tavern Spell takes effect"）;
         card_played 在法术效果结算后 fire（时序正确）
      2. 计数 = source 实体级 _felboar_casts（入场后从 0 起数——"(3
         left!)" 卡面计数语义; 此前施放的法术不计、手牌期不计）。达到
         num(1) 阈值 → _consume_random_tavern(source, mult) 且计数减去
         阈值（滚动: 每 {1} 次触发一次）
      3. 金色注册类 mult=2（"gain double its stats"，触发型无引擎
         双触发问题）
      4. num(1) 缺失 → GameStateError（PARAM_MISSING，fail-loud）

    Test: test_batch_consume.py — 3 次酒馆法术后吞噬 / 2 次不触发 /
    血宝石不计 / 滚动计数 / 金色双倍

    Params: {1}=3（36.2.2 基线，金色同值; {0}=3 为剩余数显示参数）
    """

    mult = 1   # 金色 "double" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def _is_tavern_spell(card) -> bool:
            d = game.db.get(card.card_id)
            return d is not None and d.is_pool_spell

        def on_played(g, card=None, **kw):
            d = g.db.get(source.card_id)
            threshold = d.num(1)
            if threshold is None:
                raise GameStateError(
                    f"{source.card_id}: missing num(1) template param")
            source._felboar_casts = getattr(source, "_felboar_casts", 0) + 1
            if source._felboar_casts >= threshold:
                source._felboar_casts -= threshold
                _consume_random_tavern(g, source, source.scripts.mult)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Spell)
                and card.controller is source.controller
                and _is_tavern_spell(card)),
            callback=on_played,
        ))
        return None


class FelboarGoldenScript(FelboarScript):
    """
    Natural language: [x]After you cast {1} spells,
    consume a minion in the
    Tavern to gain double
    its stats. <i>({0} left!)</i>

    Formal spec: 同基础版，mult=2（金色文本 "double"）。阈值经金色
    CardDef num(1) 取值（36.2.2 基线 =3）。

    Test: test_batch_consume.py — 金色吞噬增益 = 2× 受害者属性

    Params: {1}=3（金色 CardDef，36.2.2 基线）
    """

    mult = 2


# ══════════════════ BG34_500 Flaming Enforcer ══════════════════


class FlamingEnforcerScript:
    """
    Natural language: [x]At the end of your turn,
    consume the highest-Health
    minion in the Tavern to
    gain its stats.

    Formal spec:
      1. end_of_turn: 候选 = 控制者酒馆全部 Minion（法术不可被吞噬）;
         取 max_health 最大者（属性快照纪律——SOP §3），并列
         rng.choice 任选（label 审计）; 无候选 → 落空
      2. ConsumeMinion(source, victim)（受害者属性快照于构造前取）;
         mult>1 时追加 (mult-1)×快照 Buff
      3. 金色注册类 mult=2（"gain double its stats"）

    Test: test_batch_consume.py — 吞噬最高血量馆内随从 / 空酒馆落空 /
    金色双倍

    Params: 无模板参数（吞噬增益 = 受害者运行时属性）
    """

    mult = 1   # 金色 "double" → 2（文本字面量）

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        candidates = [m for m in hero.tavern if isinstance(m, Minion)]
        if not candidates:
            return None
        top = max(m.max_health for m in candidates)
        tied = [m for m in candidates if m.max_health == top]
        victim = game.rng.choice(tied, label="flaming_enforcer_victim")
        victim_atk = victim.atk
        victim_hp = victim.max_health
        actions = [ConsumeMinion(source, victim)]
        if source.scripts.mult > 1 and (victim_atk or victim_hp):
            actions.append(BuffAction(
                source, atk=victim_atk * (source.scripts.mult - 1),
                health=victim_hp * (source.scripts.mult - 1)))
        return actions


class FlamingEnforcerGoldenScript(FlamingEnforcerScript):
    """
    Natural language: [x]At the end of your turn,
    consume the highest-Health
    minion in the Tavern to
    gain double its stats.

    Formal spec: 同基础版，mult=2。

    Test: test_batch_consume.py — 金色吞噬增益 = 2× 受害者属性

    Params: 无模板参数（"double" 为金色文本字面量）
    """

    mult = 2


# ══════════════════ BG36_851 Spark Snapper（解冻） ══════════════════


class SparkSnapperScript:
    """
    Natural language: [x]Whenever you play a Mech,
    <b>Magnetize</b> a {1}/{1}
    Satellite to it and
    improve this.

    语义核定（batch_magnetic DEFERRED docstring 移交，2026-08-21）:
      - Satellite token = BG31_171t（def 6/6 为视觉快照，实际属性由
        生成参数动态覆盖——Beetle 先例）
      - "play a Mech" = 正常打出路径（card_played + zone==PLAY 判别，
        磁力化不触发——文本无 "or Magnetize"，与 Interpreter
        "play **or** Magnetize" 对照）
      - "improve this" = 每次触发后 Satellite 尺寸 +印面值（第 k 次
        触发尺寸 = num(1)×k; token def 6/6 = 基础 2/2 + 2 次 improve
        互证）; 计数挂 source 实体属性（离场重入场归零——Improve 随
        在场累积，Fire-forged Evoker 同构）
      - 引擎依赖已修: attach_magnetic 按实体当前属性并入（Wave2 G1）

    Formal spec:
      1. on_summon 注册 card_played 持久监听器（owner=source）: 条件
         isinstance(card, Minion) 且 zone==PLAY 且友方 且 race ∈
         (MECH, ALL) → 第 (n+1) 次触发: _make_satellite(num(1)×(n+1))
         + attach_magnetic(吸附到该 Mech)，随后 n += 1
      2. 打出 Snapper 自身同样触发（Snapper 是 Mech，自身合法宿主）
      3. 同一脚本类注册两个 id——金色 num(1)=4 经金色 CardDef 自然
         体现（金色文本与基础同文）

    Test: test_batch_consume.py — 首只 Mech +num(1)/+num(1)、第二只
    +2×num(1)（improve）/ 非 Mech 不触发 / 磁力吸附路径不触发 /
    自身打出触发 / 金色 4/4、8/8

    Params: {1}=2（36.2.2 基线，金色 =4）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        snapper = source

        def on_played(g, card=None, **kw):
            hero = snapper.controller
            if hero is None:
                return
            d = g.db.get(snapper.card_id)
            step = d.num(1)
            if step is None:
                raise GameStateError(
                    f"{snapper.card_id}: missing num(1) template param")
            n = getattr(snapper, "_snapper_improve", 0)
            sat = _make_satellite(g, hero, step * (n + 1), step * (n + 1))
            g.attach_magnetic(hero, sat, card)
            snapper._snapper_improve = n + 1

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Minion)
                and not card.dead
                and card.zone == Zone.PLAY
                and card.controller is snapper.controller
                and card.race in _MECH_RACES),
            callback=on_played,
        ))
        return None


# ══════════════════ BG36_853 Glambot（解冻） ══════════════════


class GlambotScript:
    """
    Natural language: [x]Whenever you cast a spell
    on a Mech, <b>Magnetize</b> a
    {0}/{1} Satellite to it.

    语义核定（wiki Wiki tags 2026-08-21）: Spell-related（非
    "Tavern spell-related"）——**任意法术**（酒馆法术/血宝石/
    Spellcraft）以友方 Mech 为目标施放即触发。引擎依赖已修:
    card_played 法术路径携带 target kwarg（Wave2 G2）。

    Formal spec:
      1. on_summon 注册 card_played 持久监听器（owner=source）:
         条件 isinstance(card, Spell) 且 card.controller 友方; 回调内
         验 target——isinstance(target, Minion) 且存活、zone==PLAY、
         target.controller 友方、race ∈ (MECH, ALL)，否则落空
         （无目标法术/非 Mech 目标不触发）
      2. 触发: attaches 次 _make_satellite(num(0), num(1)) +
         attach_magnetic 吸附到该 Mech（每次独立 fire magnetized，
         Polarizing Beatboxer 类链式效果可观测）
      3. 金色注册类 attaches=2（金色文本 "twice"; 金色 num 4/4 经
        CardDef——wiki 金色渲染文本 "6/6" 陈旧，以 XML 导出为准）

    Test: test_batch_consume.py — 血宝石施放于 Mech → +num(0)/+num(1) /
    无目标法术不触发 / 目标非 Mech 不触发 / 金色两次（+2×num）

    Params: {0}=4 {1}=4（36.2.2 基线，金色同值）
    """

    attaches = 1   # 金色 "twice" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        bot = source

        def on_played(g, card=None, target=None, **kw):
            hero = bot.controller
            if hero is None or target is None:
                return
            if (not isinstance(target, Minion) or target.dead
                    or target.zone != Zone.PLAY
                    or target.controller is not hero
                    or target.race not in _MECH_RACES):
                return
            d = g.db.get(bot.card_id)
            sat_atk = d.num(0)
            sat_hp = d.num(1)
            if sat_atk is None or sat_hp is None:
                raise GameStateError(
                    f"{bot.card_id}: missing num(0)/num(1) template param")
            for _ in range(bot.scripts.attaches):
                sat = _make_satellite(g, hero, sat_atk, sat_hp)
                g.attach_magnetic(hero, sat, target)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source,
            condition=lambda card=None, **kw: (
                isinstance(card, Spell)
                and card.controller is bot.controller),
            callback=on_played,
        ))
        return None


class GlambotGoldenScript(GlambotScript):
    """
    Natural language: [x]Whenever you cast a spell
    on a Mech, <b>Magnetize</b> a
    {0}/{1} Satellite to it
    twice.

    Formal spec: 同基础版，attaches=2——两个独立 Satellite 先后吸附到
    同一 Mech。

    Test: test_batch_consume.py — 金色单次施放 +2×num(0)/+2×num(1)

    Params: {0}=4 {1}=4（金色 CardDef，36.2.2 基线）
    """

    attaches = 2


# ══════════════════ BG32_330 Flighty Scout（解冻） ══════════════════


class FlightyScoutScript:
    """
    Natural language: [x]<b>Start of Combat:</b> If this
    minion is in your hand,
    summon a copy of it.

    Formal spec:
      1. 脚本类声明 hand_soc=True（combat.py 3b 协议——手牌 SoC 钩子，
         ctx={"in_hand": True}）; 棋盘路径（无 in_hand）恒 no-op
      2. 手牌路径: create_minion(同 card_id, golden 同源) +
         restore_state(手牌实体快照)——"a copy of it" 含 buff 的完整
         复制（Diremuck Forager 同构）; **手牌原件保留**（"If this
         minion is in your hand" 只判位置，不动原件）
      3. game.summon 满血入场（HEALTH 重算为 max_health）; 满板落空
         （board_full 预检）; 副本不在战前 board_before 快照 → 战后随
         引擎 board 恢复消失（仅本场）; combat_summon_log 可观测
      4. 金色注册类 mult=2（"with double stats"——副本属性为原件
         2×: 复制后追加 (mult-1)×原件 atk/max_health Buff）

    Test: test_batch_consume.py — 手牌 SoC 召唤副本且原件保留 / 棋盘
    路径不触发 / 金色副本双倍属性

    Params: 无模板参数（金色 "double stats" 文本字面量）
    """

    hand_soc = True
    mult = 1   # 金色 "double stats" → 2（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        if not (ctx or {}).get("in_hand"):
            return None
        hero = source.controller
        if hero is None or hero.board_full():
            return None
        copy = game.create_minion(source.card_id, controller=hero,
                                  golden=source.is_golden)
        copy.restore_state(source.snapshot_state())
        game.summon(hero, copy)
        if source.scripts.mult > 1:
            BuffAction(copy, atk=source.atk * (source.scripts.mult - 1),
                       health=source.max_health
                       * (source.scripts.mult - 1)).do(game)
        return None


class FlightyScoutGoldenScript(FlightyScoutScript):
    """
    Natural language: [x]<b>Start of Combat:</b> If this
    minion is in your hand,
    summon a copy of it
    with double stats.

    Formal spec: 同基础版，mult=2——副本 atk/max_health = 原件 ×2
    （快照复制后追加等量 Buff）。

    Test: test_batch_consume.py — 金色手牌 SoC 副本属性 = 原件 2×

    Params: 无模板参数（"double stats" 为金色文本字面量）
    """

    mult = 2


# ══════════════════ BG36_620 Boom-in-a-Box（解冻） ══════════════════


class BoomInABoxScript:
    """
    Natural language: <b>Taunt</b>
    <b>Start of Combat:</b> Deal {0} damage to all other minions.

    Formal spec:
      1. SoC: 经 game._active_combat（引擎战斗对暴露，combat.py run 置
         位）定位对手 = 战斗对中非 source.controller 一方; "all other
         minions" = 对手棋盘全部存活 + 己方棋盘除 source 外全部存活
         （RULES §6.12 "对敌方造成伤害"; >2 人局不误伤非参战英雄——
         仅遍历战斗对）
      2. 每个 Hit(m, num(0), source)——圣盾/死亡波次由 Hit 内部
         check_deaths 处理; 战斗内伤害经快照恢复战后回滚（RULES §3.5，
         SoC 亡语照常触发）
      3. 结算顺序: 对手棋盘（board 序）→ 己方其他（board 序），逐个
         Hit; 金色 waves=2（"twice"——两轮独立伤害序列）
      4. num(0) 缺失 → GameStateError（PARAM_MISSING）; _active_combat
         缺失（非战斗上下文直调）→ 落空返回 None
      5. Taunt 由 create_minion 关键词映射（CardDef 权威）

    Test: test_batch_consume.py — 双方棋盘其他随从各受 num(0) 伤 /
    自身不受 / 第三方英雄棋盘隔离 / 金色两轮 / 手牌不触发（hand_soc
    未声明）

    Params: {0}=3（36.2.2 基线，金色同值 ×2 轮）
    """

    waves = 1   # 金色 "twice" → 2（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        pair = getattr(game, "_active_combat", None)
        if not pair:
            return None
        opponent = None
        if hero is pair[0]:
            opponent = pair[1]
        elif hero is pair[1]:
            opponent = pair[0]
        if opponent is None:
            return None
        d = game.db.get(source.card_id)
        damage = d.num(0)
        if damage is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0) template param")
        targets = [m for m in opponent.board if not m.dead]
        targets += [m for m in hero.board
                    if m is not source and not m.dead]
        return [Hit(m, damage, source)
                for _ in range(source.scripts.waves)
                for m in targets]


class BoomInABoxGoldenScript(BoomInABoxScript):
    """
    Natural language: <b>Taunt</b>
    <b>Start of Combat:</b> Deal {0} damage to all other minions twice.

    Formal spec: 同基础版，waves=2——同一目标序列两轮独立 Hit（第一轮
    致死者不再进入第二轮的存活过滤之后序 Hit 之间由 check_deaths 处理）。

    Test: test_batch_consume.py — 金色高血量随从承受 2×num(0)（两个
    damage 事件）

    Params: {0}=3（金色 CardDef，36.2.2 基线）
    """

    waves = 2


# ══════════════════ BG36_351 Moat Custodian（解冻） ══════════════════


class MoatCustodianScript:
    """
    Natural language: [x]<b>Rally:</b> Your Elementals
    give an extra +{0}/+{1}
    this game.

    Formal spec:
      1. rally（攻击宣告时、伤害前，RULES §6.16）: hero 的
         ELEMENTAL_EXTRA_ATK(1057) / ELEMENTAL_EXTRA_HEALTH(1055) 各
         叠加 num(0)/num(1)（"this game" 永久; hero tag 不在战斗快照
         内; 每次 Rally 触发各叠加一次——Sanguine Refiner 同构）
      2. 消费出口 = elemental_buff()（本文件帮助函数，主线入册
         racefx 后迁移）——与 Glowing Cinder（ELEMENTAL_EXTRA_HEALTH
         写入方）构成读写闭环
      3. 同一脚本类注册两个 id——金色 num=4/4 经金色 CardDef 自然体现
         （金色文本与基础同文）
      4. 引擎依赖已修: tags.py 1057 入册（batch_rally2 DEFERRED 依赖）

    Test: test_batch_consume.py — Rally 后双 tag == num(0)/num(1) /
    二次触发叠加 / 金色 4/4 / elemental_buff 集成（基值+tag）

    Params: {0}=2 {1}=2（36.2.2 基线，金色 =4/4）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk = d.num(0)
        health = d.num(1)
        if atk is None or health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template param")
        hero.set(GameTag.ELEMENTAL_EXTRA_ATK,
                 hero.get(GameTag.ELEMENTAL_EXTRA_ATK, 0) + atk)
        hero.set(GameTag.ELEMENTAL_EXTRA_HEALTH,
                 hero.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0) + health)
        return None


# ══════════════════ 注册 ══════════════════

# （含金色 id——金色=独立卡定义）
_REGISTRATIONS = [
    # A. consume 批
    ("BG21_004", InsatiableUrZulScript),
    ("BG21_004_G", InsatiableUrZulGoldenScript),     # "double its stats"
    ("BG23_357", MindMuckScript),
    ("BG23_357_G", MindMuckGoldenScript),            # 单次总额 + 守卫
    ("BG28_633", FelboarScript),
    ("BG28_633_G", FelboarGoldenScript),             # "double its stats"
    ("BG34_500", FlamingEnforcerScript),
    ("BG34_500_G", FlamingEnforcerGoldenScript),     # "double its stats"
    # B. 解冻批
    ("BG36_851", SparkSnapperScript),
    ("BG36_851_G", SparkSnapperScript),              # 金色 num(1)=4 自然体现
    ("BG36_853", GlambotScript),
    ("BG36_853_G", GlambotGoldenScript),             # "twice"
    ("BG32_330", FlightyScoutScript),
    ("BG32_330_G", FlightyScoutGoldenScript),        # "double stats"
    ("BG36_620", BoomInABoxScript),
    ("BG36_620_G", BoomInABoxGoldenScript),          # "twice"
    ("BG36_351", MoatCustodianScript),
    ("BG36_351_G", MoatCustodianScript),             # 金色 num=4/4 自然体现
]


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。

    经 _tolerant_register（模块 docstring 注册冲突治理）——
    BG36_851/853 系的 batch_magnetic DEFERRED 占位由本批实现替换。
    """
    registered: list[str] = []
    for card_id, script_cls in _REGISTRATIONS:
        _registry_mod.register(card_id, script_cls)
        registered.append(card_id)
    return registered
