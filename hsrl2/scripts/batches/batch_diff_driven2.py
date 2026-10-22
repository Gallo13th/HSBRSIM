"""差分驱动批 2：TOP 缺脚本卡（679 场官方轨迹分歧频次驱动）。

来源：`runs/diff_report.json.suspect_cards`（batch 1 之后，2026-10-18）。
本批 5 张，均有 CardDefs 37.0 文本/数值权威与既有引擎原语，无新引擎改动：

1. ``BG26_529`` Upbeat Frontdrake（14 条分歧）— 每 3 回合 EoT 获取随机
   Dragon（池感知；金色 2 条）
2. ``BG34_175`` Junk Jouster（14）— 磁力吸附后全体友方 +5/+5
   （金色 +10/+10；MAGNETIZED 事件）
3. ``BG33_923`` Sundered Matriarch（14）— 每次施放法术后全体友方
   +3 Health（金色 +6；`spell_resolved` 后置施法时点）
4. ``BG35_340`` Alert Alarmist（13）— 亡语使下一张酒馆法术便宜 (1)
   （金色 (2)；`NEXT_SPELL_COST_REDUCTION` 既有引擎读点）
5. ``BG26_501`` Reef Riffer（13）— Spellcraft 随从（法术 Sick Riffs：
   给一个随从等于你酒馆等级的属性，直到下回合；金色 ×2）+ 法术脚本

DEFERRED（本批 0）：5 张语义均有 CardDef 权威 + 既有原语，无阻塞。

规则依据（项目权威序）：CardDefs 37.0 文本 + `CardDef.num()`；金色独立
CardDef 数值/文本差异由数据体现；本批未改引擎核心。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.actions import Buff
from hsrl2.events import Listener
from hsrl2.minion import Minion
from hsrl2.scripts.minions import _SpellcraftMinionMixin
from hsrl2.scripts.spells import _expire_at_next_turn
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ══════════════════════════════════════════════════════════════════════
# 卡 id
# ══════════════════════════════════════════════════════════════════════

UPBEAT_FRONT_DRAKE = "BG26_529"
UPBEAT_FRONT_DRAKE_G = "BG26_529_G"
JUNK_JOUSTER = "BG34_175"
JUNK_JOUSTER_G = "BG34_175_G"
SUNDERED_MATRIARCH = "BG33_923"
SUNDERED_MATRIARCH_G = "BG33_923_G"
ALERT_ALARMIST = "BG35_340"
ALERT_ALARMIST_G = "BG35_340_G"
REEF_RIFFER = "BG26_501"
REEF_RIFFER_G = "BG26_501_G"
SICK_RIFFS = "BG26_501t"
SICK_RIFFS_G = "BG26_501_Gt"


def _hero_of(source) -> "Hero | None":
    return getattr(source, "controller", None)


def _living(board) -> list:
    return [m for m in board if not m.dead]


def _card_num(game: "Game", source, index: int):
    d = game.db.get(source.card_id)
    return d.num(index) if d is not None else None


# ══════════════════════════════════════════════════════════════════════
# BG26_529 Upbeat Frontdrake
# ══════════════════════════════════════════════════════════════════════


class UpbeatFrontdrakeScript:
    """
    Natural language: At the end of every 3 turns, get a random Dragon.
    (X turns left!)

    依据: CardDefs 37.0 ``BG26_529``（T1 1/1 Dragon；NUM_1=3 = 间隔）；
    金色 ``BG26_529_G``（2/2）文本 "get **2** random Dragons"。

    Formal spec:
      1. on_summon 初始化 ``_upbeat_frontdrake_left = num(0)``（=3），
         注册 ``turn_end`` listener（owner=source，离场自动注销）。
      2. 每次 EoT 计数 -1；到 0 时触发并重置为 num(0)（与 Upbeat Duo
         同款 "X turns left" 口径：第 3 个 EoT 首触发）。
      3. 触发: 获取 ``count`` 条随机 Dragon（基础 1 / 金色 2）入**手牌**：
         候选 = 池内 ``Race.DRAGON`` 身份（含 Amalgam/多类型；`cdef.races`
         含 DRAGON 或 ALL）、``minion_pool.available > 0``、tier ≤
         `game.max_tavern_tier`（异变存在档白名单同 Ghastcoiler 先例）、
         本局禁用种族过滤后，逐条 `game.rng.choice` → `minion_pool.acquire`
         → `create_minion` → `game.pending_hand_add`（满手排队）。
      4. 池空/无候选 → 该条落空（不臆造），不抛错。
      5. 计数为实体 Python 属性：跨回合保留，离场再入场重置为 num(0)。
      6. **B 类迁移（2026-10-18）**: 官方 `TAG_SCRIPT_DATA_NUM_1` 注入
         = 当前 "X turns left"（1..interval）；注入存在时以该值为回放
         窗口前剩余回合基线，无注入 → num(0)（旧行为逐位不变）。

    Test: test_batch_diff_driven2.py — 第 3 个 EoT 才入手 1 条 Dragon /
    金色 2 条 / 池副本按获取数 -1 / 无候选（max_tier=0）不崩 / 两次
    触发后计数重置；test_dynamic_state_migration.py — NUM_1=1 → 下一
    个 EoT 即触发（默认仍需 3 个）。
    """

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        interval = _card_num(game, source, 0)
        if not interval or interval <= 0:
            return None
        injected = (source.get_script_data(1)
                    if source.is_script_data_injected(1) else None)
        left = int(interval) if injected is None else max(
            1, min(int(injected), int(interval)))
        setattr(source, "_upbeat_frontdrake_left", left)
        count = 2 if source.is_golden else 1
        # 触发次数按**召唤时**的卡实例定型（on_summon 里读取金色状态）。
        setattr(source, "_upbeat_frontdrake_count", count)

        def on_turn_end(g, turn=None, **kw):
            if source.dead or source.zone != Zone.PLAY:
                return
            left = int(getattr(source, "_upbeat_frontdrake_left",
                               int(interval))) - 1
            if left > 0:
                setattr(source, "_upbeat_frontdrake_left", left)
                return
            setattr(source, "_upbeat_frontdrake_left", int(interval))
            UpbeatFrontdrakeScript._grant_dragons(source, g, count)

        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_turn_end))
        return None

    @staticmethod
    def _grant_dragons(source, game: "Game", count: int) -> None:
        hero = _hero_of(source)
        if hero is None:
            return
        pool = game.minion_pool
        ladder = getattr(game, "_tavern_tier_ladder", None)
        max_tier = getattr(game, "max_tavern_tier", 6)

        def candidates() -> list:
            out = []
            for cdef in game.db.pool_minions():
                races = getattr(cdef, "races", None) or frozenset({cdef.race})
                if Race.DRAGON not in races and Race.ALL not in races:
                    continue
                if pool.available(cdef.id) <= 0:
                    continue
                if cdef.tech_level > max_tier:
                    continue
                if ladder is not None and cdef.tech_level not in ladder:
                    continue
                if pool.active_races is not None \
                        and cdef.race not in (Race.NONE, Race.ALL) \
                        and not (cdef.races & set(pool.active_races)):
                    continue
                out.append(cdef.id)
            return out

        for _ in range(int(count)):
            cands = candidates()
            if not cands:
                break
            cid = game.rng.choice(cands, label="upbeat_frontdrake_dragon")
            if not pool.acquire(cid):
                break
            m = game.create_minion(cid, controller=hero)
            if m is None:
                pool.release(cid)
                break
            game.pending_hand_add(hero, m)


# ══════════════════════════════════════════════════════════════════════
# BG34_175 Junk Jouster
# ══════════════════════════════════════════════════════════════════════


class JunkJousterScript:
    """
    Natural language: After you <b>Magnetize</b> a minion, give your
    minions +{0}/+{1}.

    依据: CardDefs 37.0 ``BG34_175``（T6 8/7；NUM_1=5 NUM_2=5）；
    金色 ``BG34_175_G``（16/14；NUM_1=10 NUM_2=10）。

    Formal spec:
      1. on_summon 注册持久监听器 ``magnetized(host=, attached=)``
         （引擎在 ``Game.attach_magnetic`` 完成攻击/生命并入、关键词
         并入、亡语栈叠后**无条件**广播一次/次吸附）。
      2. 条件: ``attached.controller is 本人``（"**you** Magnetize"——
         吸附是己方动作；对手吸附不触发）。
      3. 效果: 本人棋盘全部存活随从各 +num(0)/+num(1)（"your
         minions" 无 other/random → 含自身，确定性；金色数值已翻倍）。
         招募期吸附 → 持久 buff；战斗内吸附 → 随战斗快照回滚
         （RULES §3.5）。
      4. 每次磁力吸附各触发一次（含同一宿主多次吸附、磁力打出路径）。

    Test: test_batch_diff_driven2.py — 打出磁力随从触发全体 +5/+5 /
    金色 +10/+10 / 对手磁力不触发 / 非磁力打出不触发。
    """

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        atk = _card_num(game, source, 0)
        health = _card_num(game, source, 1)
        if atk is None or health is None:
            return None

        def on_magnetized(g, host=None, attached=None, **kw):
            if source.dead or attached is None:
                return
            if getattr(attached, "controller", None) is not hero:
                return
            for m in _living(hero.board):
                g.run_actions(Buff(m, atk=atk, health=health, source=source))

        game.events.register(Listener(event="magnetized", owner=source,
                                      callback=on_magnetized))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG33_923 Sundered Matriarch
# ══════════════════════════════════════════════════════════════════════


class SunderedMatriarchScript:
    """
    Natural language: Whenever you cast a spell, give your minions +{0}
    Health.

    依据: CardDefs 37.0 ``BG33_923``（T6 7/4 Naga；NUM_1=3）；
    金色 ``BG33_923_G``（14/8；NUM_1=6）。

    Formal spec:
      1. on_summon 注册持久 ``spell_resolved(spell=, target=, cast_no=)``
         监听（引擎 ``Game._finish_play_spell`` 与 ``cast_spell_effect``
         两个**后置**施法点各广播一次——含手牌酒馆法术与 Spellcraft
         法术；RULES §7.4.12）。
      2. 条件: ``spell.controller is 本人``（"**you** cast"；对手施法
         不触发）。
      3. 效果: 本人棋盘全部存活随从各 +num(0) Health（"your minions"
         含自身；永久健康 buff——增量为当前生命与上限，不治疗受损
         部分? 项目口径: `Buff(health=N)` 同时抬 max_health 与 health，
         与"give Health"族一致）。
      4. 招募期法术 → 持久；战斗内效果施法 → 随战斗快照回滚。

    Test: test_batch_diff_driven2.py — 真实 `play_spell` 后全体 +3 Health /
    金色 +6 / 对手施法不触发 / 非法术事件不触发 / 空板不崩。
    """

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        health = _card_num(game, source, 0)
        if health is None:
            return None

        def on_spell(g, spell=None, **kw):
            if source.dead or spell is None:
                return
            if getattr(spell, "controller", None) is not hero:
                return
            for m in _living(hero.board):
                g.run_actions(Buff(m, health=health, source=source))

        game.events.register(Listener(event="spell_resolved", owner=source,
                                      callback=on_spell))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG35_340 Alert Alarmist
# ══════════════════════════════════════════════════════════════════════


class AlertAlarmistScript:
    """
    Natural language: <b>Taunt</b> <b>Deathrattle:</b> The next Tavern
    spell you buy costs ({0}) less.

    依据: CardDefs 37.0 ``BG35_340``（T2 2/2 Pirate, DEATHRATTLE+TAUNT；
    NUM_1=1）；金色 ``BG35_340_G``（4/4；NUM_1=2）。

    Formal spec:
      1. deathrattle: 本人 controller 的 ``NEXT_SPELL_COST_REDUCTION``
         **叠加** +num(0)（引擎读点 = `Game.buy_from_tavern`，成交首个
         池法术时消费并清零；既有来源同 tag 叠加语义——batch_battlecry
         先例 "The next Tavern spell you buy costs (1) less"）。
      2. Taunt 由 CardDef 关键词 tag 表达（数据已含），脚本不重复设置。
      3. 战斗内亡语触发同样生效（折扣进下一次购买；不改变本场战斗
         结算）。

    Test: test_batch_diff_driven2.py — 真实 `destroy_minion` 亡语后
    `NEXT_SPELL_COST_REDUCTION` +1 / 金色 +2 / 与既有折扣叠加 /
    非亡语不触发。
    """

    @staticmethod
    def deathrattle(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        num = _card_num(game, source, 0)
        if num is None:
            return None
        hero.set(GameTag.NEXT_SPELL_COST_REDUCTION,
                 hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0) + int(num))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG26_501 Reef Riffer（Spellcraft 随从 + 法术 Sick Riffs）
# ══════════════════════════════════════════════════════════════════════


class ReefRifferScript(_SpellcraftMinionMixin):
    """
    Natural language: <b>Spellcraft:</b> Give a minion stats equal to
    your Tier until next turn.（金色 = 两倍 Tier）

    依据: CardDefs 37.0 ``BG26_501``（T2 3/2 Naga，spellcraft_id →
    ``BG26_501t`` Sick Riffs "Give a minion stats equal to your Tier
    until next turn."）；金色 ``BG26_501_G`` spellcraft_id →
    ``BG26_501_Gt`` "equal to **twice** your Tier"。

    Formal spec:
      1. on_summon（继承 `_SpellcraftMinionMixin`）: SPELLCRAFT tag
         自举 + 立即获得本随从 spellcraft_id 对应法术（金色独立定义
         指向金色法术）。
      2. 后续每招募阶段开始由 `spellcraft.generate_for_hero` 生成。
      3. 法术本体见 `ReefRifferSpellScript`（temporary buff + 下回合
         开始精确移除）。

    Test: test_batch_diff_driven2.py — 打出立即获得 Sick Riffs（金卡 →
    金法术）/ 法术对目标加 2×Tier 属性 / 下回合开始回落。
    """


class ReefRifferSpellScript:
    """
    Natural language: Give a minion stats equal to your Tier until next
    turn.

    Formal spec:
      1. on_play（ctx["target"]）: 目标获得 temporary 属性 buff
         （atk = health = 施放者酒馆等级 × mult；金色法术 mult=2——金色
         法术是独立 CardDef，由本类 `mult` 体现）。
      2. 过期: 目标控制者的下一个招募阶段开始时**精确**移除该 buff
         （`scripts/spells._expire_at_next_turn`，RULES §6.13）。
      3. target=None → 落空（法术仍被消耗）。

    Test: test_batch_diff_driven2.py — +Tier/+Tier 立即生效 / 金法术
    +2×Tier / 下回合开始回落 / 无目标不崩。
    """

    mult = 1

    @staticmethod
    def on_play(source, game: "Game", ctx):
        target = (ctx or {}).get("target")
        if not isinstance(target, Minion):
            return None
        hero = getattr(source, "controller", None)
        tier = int(getattr(hero, "tavern_tier", 1) or 1)
        # 法术实体没有 is_golden（Spell 非 Minion）；金色法术是独立
        # CardDef（id 以 _Gt 结尾，如 BG26_501_Gt），按卡 id 判定。
        is_golden = str(source.card_id).endswith("_Gt")
        mult = (ReefRifferGoldenSpellScript.mult
                if is_golden else ReefRifferSpellScript.mult)
        gain = tier * mult
        if gain <= 0:
            return None
        buff = entity.Buff(atk=gain, health=gain, temporary=True,
                           source_id=source.card_id)
        target.add_buff(buff)
        _expire_at_next_turn(game, source, target, buffs=[buff])
        return None


class ReefRifferGoldenSpellScript(ReefRifferSpellScript):
    """金色 Sick Riffs：属性 = 2 × 酒馆等级（金色独立 CardDef）。"""

    mult = 2


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册本批 12 个 card_id（5 张卡 × 普/金 + 2 个 Spellcraft 法术）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (UPBEAT_FRONT_DRAKE, UpbeatFrontdrakeScript),
        (UPBEAT_FRONT_DRAKE_G, UpbeatFrontdrakeScript),
        (JUNK_JOUSTER, JunkJousterScript),
        (JUNK_JOUSTER_G, JunkJousterScript),
        (SUNDERED_MATRIARCH, SunderedMatriarchScript),
        (SUNDERED_MATRIARCH_G, SunderedMatriarchScript),
        (ALERT_ALARMIST, AlertAlarmistScript),
        (ALERT_ALARMIST_G, AlertAlarmistScript),
        (REEF_RIFFER, ReefRifferScript),
        (REEF_RIFFER_G, ReefRifferScript),
        (SICK_RIFFS, ReefRifferSpellScript),
        (SICK_RIFFS_G, ReefRifferGoldenSpellScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
