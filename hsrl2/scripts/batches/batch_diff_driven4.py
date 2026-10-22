"""差分驱动批 4：非池/历史缺脚本卡 + Chromadrake token 全家。

来源：`runs/diff_report.json` 的 no_script 缺口频次（2026-10-18，batch 3 后）。
本批 8 张 + 10 个 Chromadrake token，全部有 CardDefs 37.0 权威 + 既有原语，
**无引擎改动**：

1. ``BG33_820`` Lost City Looter — EoT: Get a random Bounty
   （Bounty 卡集复用 `batch_deathrattle2._bounty_ids`）
2. ``BG24_009`` Picky Eater — Battlecry: Consume a random minion in the
   Tavern（复用 `ConsumeRandomTavernMinion` 原语）
3. ``BG32_430`` Glowgullet Warlord — Deathrattle: 召唤 2 只 QuiLboar
   Taunt token，并对它们施放 Blood Gem（金色 2 颗/只）
4. ``BG26_160`` Prickly Piper — Deathrattle: 本局血宝石额外 +1 Attack
   （金色 +2；hero `BLOOD_GEM_BONUS_ATK` 唯一消费点 = `_gem_values`）
5. ``BG33_920`` Wrathscale Rogue — After another friendly Naga gains
   Health, give it that much Attack（`STATS_GAINED` 事件）
6. ``BG34_312`` Hardy Orca — Whenever this takes damage, give your other
   minions +{0}/+{1}（`damage` 事件）
7. ``BGS_049`` Freedealing Gambler — This minion sells for 3 Gold
   （`SELL_VALUE` tag）
8. ``BG31_175`` Holo Rover — Rally: Get a random Magnetic Mech（金色 2 只；
   pool-aware：池内 MECH + magnetic 且 available>0）

9. **Chromadrake token 全家**（``BG34_634t..638t`` + 金色 ``_Gt``）：
   Blue（随机 {0}-Cost 酒馆法术）/ Black（酒馆法术额外 +{0} Health）/
   Green・Bronze（给其他龙 +{0}/+{1}）/ Red（酒馆法术额外 +{0} Attack）。
   金色 token 的战吼由引擎双触发实现总额（脚本按**基础 token**
   CardDef 数值每次触发，避免金色数值再翻倍 → 双计）。

DEFERRED：无（本批全部可立即实现）。下一阶段需求见
`reversed/rea/deferred_primitives.md`（`minion_gained` 统一入手事件、
`combat_spell_extra_casts` 等）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.consume import ConsumeRandomTavernMinion
from hsrl2.events import STATS_GAINED, Listener
from hsrl2.scripts.batches.batch_deathrattle2 import (
    _bounty_ids,
    _get_pool_spell,
)
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ══════════════════════════════════════════════════════════════════════
# 卡 id
# ══════════════════════════════════════════════════════════════════════

LOST_CITY_LOOTER = "BG33_820"
LOST_CITY_LOOTER_G = "BG33_820_G"
PICKY_EATER = "BG24_009"
PICKY_EATER_G = "BG24_009_G"
GLOWGULLET_WARLORD = "BG32_430"
GLOWGULLET_WARLORD_G = "BG32_430_G"
GLOWGULLET_SOLDIER = "BG32_430t"
GLOWGULLET_SOLDIER_G = "BG32_430t_G"
PRICKLY_PIPER = "BG26_160"
PRICKLY_PIPER_G = "BG26_160_G"
WRATHSCALE_ROGUE = "BG33_920"
WRATHSCALE_ROGUE_G = "BG33_920_G"
HARDY_ORCA = "BG34_312"
HARDY_ORCA_G = "BG34_312_G"
FREEDEALING_GAMBLER = "BGS_049"
HOLO_ROVER = "BG31_175"
HOLO_ROVER_G = "BG31_175_G"

CHROMADRAKE_IDS = (
    "BG34_634t", "BG34_635t", "BG34_636t", "BG34_637t", "BG34_638t",
)
CHROMADRAKE_GOLDEN_IDS = (
    "BG34_634_Gt", "BG34_635_Gt", "BG34_636_Gt", "BG34_637_Gt",
    "BG34_638_Gt",
)


def _hero_of(source) -> Optional["Hero"]:
    return getattr(source, "controller", None)


def _living(board) -> list:
    return [m for m in board if not m.dead]


def _card_num(game: "Game", source, index: int):
    d = game.db.get(source.card_id)
    return d.num(index) if d is not None else None


def _base_card(game: "Game", source):
    """金色定义 → 基础卡 CardDef（无三连基准则回落自身）。

    金色 token 的数值是基础值的 2 倍，但**战吼由引擎双触发**（引擎
    `play_minion` 对金卡 times*=2）→ 脚本每触发一次应使用**基础卡**
    数值，总额才等于金色文本（避免 4× 双计）。
    """
    if getattr(source, "is_golden", False):
        base_id = source.get(GameTag.TRIPLE_BASE_CARD_ID, None)
        if base_id:
            d = game.db.get(base_id)
            if d is not None:
                return d
    return game.db.get(source.card_id)


# ══════════════════════════════════════════════════════════════════════
# BG33_820 Lost City Looter
# ══════════════════════════════════════════════════════════════════════


class LostCityLooterScript:
    """
    Natural language: <b>Taunt</b> At the end of your turn, get a random
    <b>Bounty</b>.

    依据: CardDefs 37.0 ``BG33_820``（T3 1/1 Pirate Taunt）；金色
    ``BG33_820_G`` 文本同（无数值参数，金色无额外次数）。

    Formal spec:
      1. on_summon 注册 ``turn_end`` 监听（owner=source，离场自动注销）。
      2. 触发: Bounty 卡集 = `_bounty_ids(game)`（5 张 T3 海盗酒馆法术，
         wiki/Bounty 权威；batch_deathrattle2 同源），随机取 1 张 →
         `_get_pool_spell`（池内 acquire 占池 / 池空生成不占池）→
         进手牌（满手排队）。无 Bounty 定义 → 落空。
      3. 金色同文本 → 同样 1 张（不翻倍）。

    Test: test_batch_diff_driven4.py — 真实 TURN_END 后手牌 +1 张
    Bounty 卡集内法术 / 池占用 1 / 金色同样 1 张 / 无 Bounty（非海盗局）
    不崩。
    """

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None

        def on_turn_end(g, turn=None, **kw):
            if source.dead or source.zone != Zone.PLAY:
                return
            cands = _bounty_ids(g)
            if not cands:
                return
            sid = g.rng.choice(cands, label="lost_city_looter_bounty")
            _get_pool_spell(g, hero, sid, 1)

        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_turn_end))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG24_009 Picky Eater
# ══════════════════════════════════════════════════════════════════════


class PickyEaterScript:
    """
    Natural language: <b>Battlecry:</b> Consume a random minion in the
    Tavern to gain its stats.

    依据: CardDefs 37.0 ``BG24_009``（T1 1/1 Beast）；金色
    ``BG24_009_G`` 文本同（战吼双触发由引擎实现 → 吞噬两次）。

    Formal spec:
      1. battlecry: `ConsumeRandomTavernMinion(source)` —— 候选 =
         controller 酒馆内 Minion（法师不可被吞），目标由
         `Game.pick_consume_victim` 选择（默认均匀随机；Implicator
         Portrait 时最高生命——引擎既定读取点，本卡不另写随机）。
      2. 吞噬 = 恶魔获得受害者 atk/max_health 永久 Buff；受害者从酒馆
         移除 + 回池（`ConsumeMinion` 权威）。
      3. 空酒馆 → 落空（不抛错）。

    Test: test_batch_diff_driven4.py — 战吼后属性 += 受害者 atk/max_health
    / 受害者离开酒馆且回池 / 空酒馆不崩 / 金色双触发（引擎）。
    """

    @staticmethod
    def battlecry(source, game: "Game", ctx=None):
        if _hero_of(source) is None:
            return None
        return ConsumeRandomTavernMinion(source)


# ══════════════════════════════════════════════════════════════════════
# BG32_430 Glowgullet Warlord
# ══════════════════════════════════════════════════════════════════════


class GlowgulletWarlordScript:
    """
    Natural language: <b>Deathrattle:</b> Summon two 1/1 Quilboar with
    <b>Taunt</b>. This plays a Blood Gem on them.

    依据: CardDefs 37.0 ``BG32_430``（T2 2/2 Quilboar）；token
    ``BG32_430t`` Glowgullet Soldier（1/1 Taunt）。金色
    ``BG32_430_G``（4/4）文本：召唤 two **2/2** Quilboar，并各放 **2**
    颗 Blood Gem（token = ``BG32_430t_G`` 2/2 Taunt）。

    Formal spec:
      1. deathrattle: 召唤 2 只 token（基础 1/1 / 金色 2/2，直接按数据链
         取 `BG32_430t` 的 `golden_version`）；满场由 `game.summon` 落空。
      2. 每只 token 施放 Blood Gem：基础 1 颗 / 金色 2 颗
         （`PlayBloodGems(token, count, source=source)`；数值 = vanilla
         宝石 + hero BLOOD_GEM_BONUS_*，与既有唯一消费点一致）。
      3. 亡语在战斗/招募期同样结算；召唤位置按引擎默认（append）。

    Test: test_batch_diff_driven4.py — 真实 destroy_minion 后棋盘 +2 只
    1/1 Taunt token 且各获得血宝石属性 / 金色 2/2 token + 2 颗宝石 /
    满场时召唤落空不崩。
    """

    @staticmethod
    def deathrattle(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        token_id = (GLOWGULLET_SOLDIER_G if source.is_golden
                    else GLOWGULLET_SOLDIER)
        gems = 2 if source.is_golden else 1
        for _ in range(2):
            token = game.create_minion(token_id, controller=hero)
            if token is None:
                continue
            if not game.summon(hero, token):
                break
            for _ in range(gems):
                game.run_actions(PlayBloodGems(token, 1, source=source))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG26_160 Prickly Piper
# ══════════════════════════════════════════════════════════════════════


class PricklyPiperScript:
    """
    Natural language: <b>Deathrattle:</b> Your <b>Blood Gems</b> give an
    extra +1 Attack this game.

    依据: CardDefs 37.0 ``BG26_160``（T3 5/1 Quilboar）；金色
    ``BG26_160_G`` 文本 "+2 Attack"。

    Formal spec:
      1. deathrattle: hero `BLOOD_GEM_BONUS_ATK` += 1（金色 +2）。
         该 tag 是 `_gem_values`（actions/bloodgem.py）的唯一读取点——
         "this game" 永久（hero tag 不在战斗快照回滚范围内，Sanguine
         Refiner 先例）。
      2. 多次死亡可叠加（多张 Piper 各自 +1/+2）。

    Test: test_batch_diff_driven4.py — 真实 destroy_minion 后
    BLOOD_GEM_BONUS_ATK +1 / 金色 +2 / 之后 PlayBloodGems 实际多给
    1 点攻击（正对照）。
    """

    @staticmethod
    def deathrattle(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        gain = 2 if source.is_golden else 1
        hero.set(GameTag.BLOOD_GEM_BONUS_ATK,
                 hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0) + gain)
        return None


# ══════════════════════════════════════════════════════════════════════
# BG33_920 Wrathscale Rogue
# ══════════════════════════════════════════════════════════════════════


class WrathscaleRogueScript:
    """
    Natural language: After another friendly Naga gains Health, give it
    that much Attack.

    依据: CardDefs 37.0 ``BG33_920``（T6 3/6 Naga）；金色
    ``BG33_920_G`` 文本同（无数值参数）。

    Formal spec:
      1. on_summon 注册 **`stats_gained`** 持久监听（owner=source；引擎
         唯一"获得属性"观察点，`Entity.add_buff` 生产。
         载荷: minion/atk/health/permanent/source）。
      2. 条件: `health > 0`（"gains Health"）、`minion is not source`
         （"**another**"）、`minion.controller is 本人`（friendly）、
         `minion.has_race(NAGA)`（Naga / ALL 身份）。
      3. 效果: 给该随从 `Buff(atk=health增量)`——"give it that much
         Attack"；不复制 health。递归保护：本 Buff 的 atk>0/health=0，
         不满足 health>0 → 不会再次触发。
      4. 生命增加来源不限（战吼/亡语/法术/战斗内 buff 均经 add_buff）。

    Test: test_batch_diff_driven4.py — 真实 Buff 给另一 Naga +1 Health
    后其攻击 +1 / 非 Naga 不触发 / 自己获得生命不触发 / 对手 Naga 不触发
    / 战斗内同样触发。
    """

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None

        def on_stats_gained(g, minion=None, atk=0, health=0,
                            source=None, **kw):
            if minion is None or minion is source_minion or health <= 0:
                return
            if getattr(minion, "controller", None) is not hero:
                return
            if not minion.has_race(Race.NAGA):
                return
            g.run_actions(Buff(minion, atk=int(health)))

        source_minion = source
        game.events.register(Listener(event=STATS_GAINED, owner=source,
                                      callback=on_stats_gained))
        return None


# ══════════════════════════════════════════════════════════════════════
# BG34_312 Hardy Orca
# ══════════════════════════════════════════════════════════════════════


class HardyOrcaScript:
    """
    Natural language: <b>Taunt</b> Whenever this takes damage, give your
    other minions +{0}/+{1}.

    依据: CardDefs 37.0 ``BG34_312``（T3 1/6 Beast Taunt；NUM_1=NUM_2=1）；
    金色 ``BG34_312_G``（2/12；NUM_1=NUM_2=2）。

    Formal spec:
      1. on_summon 注册持久 ``damage(minion=, amount=, source=)`` 监听
         （owner=source；引擎攻击/反击/效果伤害统一广播点）。
      2. 条件: `minion is source` 且 `amount > 0`（"this takes damage"；
         圣盾抵消不触发——实际伤害 0 不广播）。
      3. 效果: 本人棋盘**其他**存活随从各 `Buff(+num(0), +num(1))`
         （"your **other** minions" 排除自身；金色数值 2/2 由金色
         CardDef 自然体现）。
      4. 战斗内触发 → 战斗快照回滚（RULES §3.5）；招募期伤害同样触发。

    Test: test_batch_diff_driven4.py — 真实 take_damage 后其他随从
    +1/+1（自身不加）/ 金色 +2/+2 / 未被伤害不触发 / 圣盾抵消不触发。
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

        def on_damage(g, minion=None, amount=None, source=None, **kw):
            if minion is not source_minion:
                return
            if not amount or amount <= 0:
                return
            for m in _living(hero.board):
                if m is source_minion:
                    continue
                g.run_actions(Buff(m, atk=atk, health=health))

        source_minion = source
        game.events.register(Listener(event="damage", owner=source,
                                      callback=on_damage))
        return None


# ══════════════════════════════════════════════════════════════════════
# BGS_049 Freedealing Gambler
# ══════════════════════════════════════════════════════════════════════


class FreedealingGamblerScript:
    """
    Natural language: This minion sells for 3 Gold.

    依据: CardDefs 37.0 ``BGS_049``（T2 3/3 Pirate；无金色独立定义）。

    Formal spec:
      1. on_summon: 自身 `SELL_VALUE = 3`（引擎 `sell_minion` 以 tag
         **存在性**判定覆写价——`0` 也是合法覆写，故必须 set 而非依赖
         真值；值 = 文本字面量 3）。
      2. 出售时只影响本人（不写 hero 级 SELL_VALUE_OVERRIDE）。
      3. 无金色版本（数据无 ``BGS_049_G``）。

    Test: test_batch_diff_driven4.py — 真实 sell_minion 得 3 金 /
    普通随从仍 1 金（负对照）。
    """

    sell_price = 3

    @staticmethod
    def on_summon(source, game: "Game", ctx=None):
        source.set(GameTag.SELL_VALUE, FreedealingGamblerScript.sell_price)
        return None


# ══════════════════════════════════════════════════════════════════════
# BG31_175 Holo Rover
# ══════════════════════════════════════════════════════════════════════


class HoloRoverScript:
    """
    Natural language: <b>Divine Shield</b> <b>Rally:</b> Get a random
    <b>Magnetic</b> Mech.

    依据: CardDefs 37.0 ``BG31_175``（T5 4/6 Mech，DIVINE_SHIELD+RALLY）；
    金色 ``BG31_175_G``（8/12）文本 "Get **2** random Magnetic Mechs"。

    Formal spec:
      1. rally（攻击宣告时、伤害前；引擎 `run_rally` 分发）: 获取
         `picks` 只随机磁性机械入手（基础 1 / 金色 2——金色文本
         "2 random" 为字面量，Rally 引擎不双触发）。
      2. "random Magnetic Mech" = **池感知**随机: 候选 = 池内
         `minion_pool.available > 0`、race 身份含 MECH（含 ALL）、
         `magnetic` 关键词、tier ≤ 当前酒馆等级（存在档白名单同
         Ghastcoiler 先例）、本局禁用种族过滤；逐只
         `rng.choice` → `acquire` 占池 → `create_minion` →
         `pending_hand_add`（满手排队）。
      3. 池内无候选 → 落空（不臆造）。

    Test: test_batch_diff_driven4.py — 真实 `_execute_attack` 触发 Rally
    入手 1 只磁性机械（池 -1）/ 金色 2 只 / 池空落空 / 非磁力机械不在
    候选（数据指纹）。
    """

    picks = 1

    @staticmethod
    def rally(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        pool = game.minion_pool
        ladder = getattr(game, "_tavern_tier_ladder", None)
        max_tier = getattr(game, "max_tavern_tier", 6)

        def candidates() -> list:
            out = []
            for cdef in game.db.pool_minions():
                if "magnetic" not in cdef.keywords:
                    continue
                races = getattr(cdef, "races", None) or frozenset({cdef.race})
                if Race.MECH not in races and Race.ALL not in races:
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

        for _ in range(source.scripts.picks):
            cands = candidates()
            if not cands:
                break
            cid = game.rng.choice(cands, label="holo_rover_pick")
            if not pool.acquire(cid):
                break
            m = game.create_minion(cid, controller=hero)
            if m is None:
                pool.release(cid)
                break
            game.pending_hand_add(hero, m)
        return None


class HoloRoverGoldenScript(HoloRoverScript):
    """金色 Holo Rover：Rally 获取 2 只随机磁性机械。"""

    picks = 2


# ══════════════════════════════════════════════════════════════════════
# Chromadrake token 全家（非池 token；金色 _Gt）
# ══════════════════════════════════════════════════════════════════════


class ChromadrakeBlueScript:
    """
    Natural language: <b>Battlecry:</b> Get a random {0}-Cost Tavern spell.

    依据: ``BG34_634t``（Blue Chromadrake 4/4，NUM_1=2）；金色
    ``BG34_634_Gt``（8/8）文本 "Get **two** random {0}-Cost"。

    Formal spec:
      1. battlecry（每次触发 1 张；金色引擎双触发 → 总额 2，与金色
         文本一致）：候选 = 池内 `spell_pool.available>0` 且
         `CardDef.cost == num(0)`（=2 金）的酒馆法术；随机 →
         acquire 占池 → create_spell → 进手牌（满手排队）。
      2. 金色用**基础 token** 的 num(0)=2（同一 cost），避免金色数值
         双计（数值本来就相同）。
      3. 无候选 → 落空。

    Test: test_batch_diff_driven4.py — 战吼后手牌 +1 张 Cost=2 池法术
    / 金色 +2 张 / 池空落空不崩。
    """

    per_trigger = 1

    @staticmethod
    def battlecry(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        d = _base_card(game, source)
        cost = d.num(0) if d is not None else None
        if cost is None:
            return None
        cands = [sd.id for sd in game.db.pool_spells()
                 if getattr(sd, "cost", None) == int(cost)
                 and game.spell_pool.available(sd.id) > 0]
        if not cands:
            return None
        for _ in range(ChromadrakeBlueScript.per_trigger):
            sid = game.rng.choice(cands, label="chromadrake_blue_spell")
            if not game.spell_pool.acquire(sid):
                break
            game.pending_hand_add(hero,
                                  game.create_spell(sid, controller=hero))
        return None


class ChromadrakeBlackScript:
    """
    Natural language: <b>Battlecry:</b> Your Tavern spells give an extra
    +{0} Health this game.

    依据: ``BG34_635t``（Black Chromadrake 4/6，NUM_1=1）；金色
    ``BG34_635_Gt``（8/12）文本 "+{0} Health" with NUM_1=2。

    Formal spec: battlecry → hero `TAVERN_SPELL_EXTRA_HEALTH +=
    base_num(0)`（基础卡 1；金色引擎双触发 × 基础 1 = 2 = 金色文本）。
    消费点 = `actions/racefx.tavern_spell_buff`（"Your Tavern spells
    give an extra +X" 家族唯一出口）。
    """

    @staticmethod
    def battlecry(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        d = _base_card(game, source)
        gain = d.num(0) if d is not None else None
        if gain is None:
            return None
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + int(gain))
        return None


class ChromadrakeRedScript:
    """
    Natural language: <b>Battlecry:</b> Your Tavern spells give an extra
    +{0} Attack this game.

    依据: ``BG34_638t``（Red Chromadrake 6/4，NUM_1=1）；金色
    ``BG34_638_Gt``（12/8）NUM_1=2。同 Black，写 `TAVERN_SPELL_EXTRA_ATK`。
    """

    @staticmethod
    def battlecry(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        d = _base_card(game, source)
        gain = d.num(0) if d is not None else None
        if gain is None:
            return None
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + int(gain))
        return None


class ChromadrakeGreenScript:
    """
    Natural language: <b>Battlecry:</b> Give your other Dragons +{0}/+{1}.

    依据: ``BG34_636t``（3/5，NUM_1=1 NUM_2=3）；金色 ``BG34_636_Gt``
    （6/10）NUM_1=2 NUM_2=6。

    Formal spec: battlecry → 本人棋盘**其他**存活 Dragon（含 ALL 身份）
    各 +base_num(0)/+base_num(1)（基础 1/3；金色引擎双触发 × 基础 =
    2/6 = 金色文本）。
    """

    @staticmethod
    def battlecry(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        d = _base_card(game, source)
        if d is None:
            return None
        atk, health = d.num(0), d.num(1)
        if atk is None or health is None:
            return None
        for m in _living(hero.board):
            if m is source or not m.has_race(Race.DRAGON):
                continue
            game.run_actions(Buff(m, atk=int(atk), health=int(health)))
        return None


class ChromadrakeBronzeScript:
    """
    Natural language: <b>Battlecry:</b> Give your other Dragons +{0}/+{1}.

    依据: ``BG34_637t``（5/3，NUM_1=3 NUM_2=1）；金色 ``BG34_637_Gt``
    （10/6）NUM_1=6 NUM_2=2。同 Green，数值由基础卡定义驱动。
    """

    @staticmethod
    def battlecry(source, game: "Game", ctx=None):
        return ChromadrakeGreenScript.battlecry(source, game, ctx)


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册本批 8 张卡（14 id）+ 10 个 Chromadrake token id。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (LOST_CITY_LOOTER, LostCityLooterScript),
        (LOST_CITY_LOOTER_G, LostCityLooterScript),
        (PICKY_EATER, PickyEaterScript),
        (PICKY_EATER_G, PickyEaterScript),
        (GLOWGULLET_WARLORD, GlowgulletWarlordScript),
        (GLOWGULLET_WARLORD_G, GlowgulletWarlordScript),
        (PRICKLY_PIPER, PricklyPiperScript),
        (PRICKLY_PIPER_G, PricklyPiperScript),
        (WRATHSCALE_ROGUE, WrathscaleRogueScript),
        (WRATHSCALE_ROGUE_G, WrathscaleRogueScript),
        (HARDY_ORCA, HardyOrcaScript),
        (HARDY_ORCA_G, HardyOrcaScript),
        (FREEDEALING_GAMBLER, FreedealingGamblerScript),
        (HOLO_ROVER, HoloRoverScript),
        (HOLO_ROVER_G, HoloRoverGoldenScript),
    ]
    # Chromadrake token 全家（非池 token；金色独立卡定义 → 同脚本类，
    # 数值按基础卡读，避免金色双计）。
    token_pairs = [
        ("BG34_634t", ChromadrakeBlueScript),
        ("BG34_635t", ChromadrakeBlackScript),
        ("BG34_636t", ChromadrakeGreenScript),
        ("BG34_637t", ChromadrakeBronzeScript),
        ("BG34_638t", ChromadrakeRedScript),
    ]
    golden_map = {
        "BG34_634_Gt": ChromadrakeBlueScript,
        "BG34_635_Gt": ChromadrakeBlackScript,
        "BG34_636_Gt": ChromadrakeGreenScript,
        "BG34_637_Gt": ChromadrakeBronzeScript,
        "BG34_638_Gt": ChromadrakeRedScript,
    }
    pairs += token_pairs + list(golden_map.items())

    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
