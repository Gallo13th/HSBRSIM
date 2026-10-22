"""批次 37x_discard — F-08 Discard 子系统 + 剩余 12 张池内卡。

背景
═══════════════════════════════════════════════════════════════════════
37.0 Aberration 种族以"弃牌（Discard）"为核心资源；此前引擎无 Discard
action/事件，9 张池内 discard 族 + 3 张 Deity discard 卡全部 DEFERRED。
本批先落 **F-08 引擎原语**（`Game.discard_card` + `card_discarded` 事件 +
`on_discard` 钩子 + `Hero.cards_discarded_this_game` 计数 + 数据 cost=0
的 Activate 标记修正，见 `docs/ENGINE_NOTES.md` F-08），再注册 12 张卡。

本批卡（12 张 ×基础/金 = 24 id）
═══════════════════════════════════════════════════════════════════════
  BG28_582 / _G  Mangled Bandit：Activate (0): Discard a card to get
      {0} Blood Gems.（3/6）
  BG36_097 / _G  Mindbender Ghur'sha：Whenever you discard a card,
      give your other minions +{0}/+{1}.（4/4；金 8/8）
  BG36_100 / _G  Wandering Willbreaker：When you sell this, get 2 random
      Tavern spells. When you play one, discard the other.
      （金 4 张 + 打出 2 张后弃其余）
  BG36_114 / _G  Parasitic Fleshling：EoT give your left-most minion
      +{0}/+{1} (Improved by each card you've discarded this game!)
      （2/2；金 4/4）
  BG36_300 / _G  N'raqi Frostcaller：Activate (0): Discard a card for
      your Tavern spells to give an extra +{0}/+{1} this game.（1/1; 金 2/2）
  BG36_308 / _G  Faceless Operative：When you sell this, get 2 random
      Aberrations. When you play one, discard the other.
      （金 4 张 + 打出 2 张后弃其余）
  BG36_311 / _G  Abyssal Envoy：Activate (0): Discard a card to get a
      random Tavern spell.（金 2 张）
  BG36_312 / _G  Mindbending Recruiter：Activate (0): Discard a card to
      get a random Aberration.（金 2 张）
  BG36_320 / _G  Mysterious K'Thir：EoT discard your {2} left-most Tavern
      spells. Gain +{0}/+{1} for each discarded.（7/7，3 张；金 6 张）
  BG36_099 / _G  Brain Rotter：Activate (0): Discard a card to give your
      Deity +{0}/+{1}.（2/2；金 4/4）
  BG36_106 / _G  Cutthroat K'Thir：Whenever you discard a card, give this
      and your Deity +{0}/+{1}.（4/4；金 8/8）
  BGFYM_005 / _G Harbinger Aph'lass：Whenever you discard a card, give
      your Deity +{0}/+{1} and improve this.（2/1；金 4/2）

载荷回补（本批同时接线）
═══════════════════════════════════════════════════════════════════════
  `batch_37x_payloadgap1.SludgeCorrosionScript.on_discard` 与
  `batch_37x_deity.EnergizingChamberScript.on_discard`：实现
  "If you discard this, cast it twice"（`Game.discard_card` 分发
  `on_discard` 钩子；F-08）。

证据/语义
═══════════════════════════════════════════════════════════════════════
- 数值一律 `CardDef.num(i)`；金色独立 CardDef。
- "Discard a card" = 从**手牌**选择一张（PendingChoice kind=
  "discard_card"，options=当前手牌）；手牌为空 → Activate 结算但效果落空
  （费用已扣；官方无合法弃牌目标语义）。
- "Whenever you discard a card" = 监听引擎 `card_discarded` 事件；
  弃置来源不区分（Activate/左右成对/自身弃置均触发）。
- "Improved by each card you've discarded this game" = hero 级计数
  `cards_discarded_this_game`；倍率 = 1 + 计数（Improve 家族口径）。
- 成对弃置（Willbreaker/Operative）：售出时生成 N 张并记住该组；
  打出该组 **N/2** 张后弃掉组内其余（"When you play one/two, discard
  the other(s)"）。"or Pass" 属 Duos 语义，本引擎无 Pass（边界记档）。
- 弃置不回池、不触发 on_play/on_sell；池副本视为消耗（证据不足，
  F-08 记档）。"If you discard this" 由 `on_discard` 钩子处理。
- 数据导出在 Activate 费用为 0 时省略 `activate_cost`：
  引擎 F-08 修正为以 `activate` 关键词为权威、缺省 cost=0（否则
  Mangled Bandit / Brain Rotter / Abyssal Envoy / Mindbending
  Recruiter / N'raqi Frostcaller 永远不可 Activate）。
- 随机一律 `game.rng`；池约束走 `game.spell_pool` /
  `game.minion_pool.acquire`（RULES §2.3/§6.18）。

DEFERRED
═══════════════════════════════════════════════════════════════════════
  BG28_583 Geomagus Roogug：单只可精确实现，但两只互触发无官方触发链
  上限（引擎 ActionQueue 20000 会抛 CombatLoopError）→ 维持 DEFERRED，
  待触发链配额裁定（F-08 后池内缺口仅此 1 张）。

Test: `hsrl2/tests/test_batch_37x_discard.py`（真实 `use_activate` /
`discard_card` / `play_spell` / `play_minion` / `sell_minion` /
`end_recruit_phase` EoT / 真实事件监听；正负对照 + 金色数值）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import GetBloodGems
from hsrl2.events import TAVERN_SPELL_CAST, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 卡 id ──
MANGLED_BANDIT = "BG28_582"
MANGLED_BANDIT_G = "BG28_582_G"
MINDBENDER_GHURSHA = "BG36_097"
MINDBENDER_GHURSHA_G = "BG36_097_G"
WANDERING_WILLBREAKER = "BG36_100"
WANDERING_WILLBREAKER_G = "BG36_100_G"
PARASITIC_FLESHLING = "BG36_114"
PARASITIC_FLESHLING_G = "BG36_114_G"
NRAQI_FROSTCALLER = "BG36_300"
NRAQI_FROSTCALLER_G = "BG36_300_G"
FACELESS_OPERATIVE = "BG36_308"
FACELESS_OPERATIVE_G = "BG36_308_G"
ABYSSAL_ENVOY = "BG36_311"
ABYSSAL_ENVOY_G = "BG36_311_G"
MINDBENDING_RECRUITER = "BG36_312"
MINDBENDING_RECRUITER_G = "BG36_312_G"
MYSTERIOUS_KTHIR = "BG36_320"
MYSTERIOUS_KTHIR_G = "BG36_320_G"
BRAIN_ROTTER = "BG36_099"
BRAIN_ROTTER_G = "BG36_099_G"
CUTTHROAT_KTHIR = "BG36_106"
CUTTHROAT_KTHIR_G = "BG36_106_G"
HARBINGER_APHLASS = "BGFYM_005"
HARBINGER_APHLASS_G = "BGFYM_005_G"

_DISCARD_CARDS = (
    MANGLED_BANDIT, MANGLED_BANDIT_G,
    MINDBENDER_GHURSHA, MINDBENDER_GHURSHA_G,
    WANDERING_WILLBREAKER, WANDERING_WILLBREAKER_G,
    PARASITIC_FLESHLING, PARASITIC_FLESHLING_G,
    NRAQI_FROSTCALLER, NRAQI_FROSTCALLER_G,
    FACELESS_OPERATIVE, FACELESS_OPERATIVE_G,
    ABYSSAL_ENVOY, ABYSSAL_ENVOY_G,
    MINDBENDING_RECRUITER, MINDBENDING_RECRUITER_G,
    MYSTERIOUS_KTHIR, MYSTERIOUS_KTHIR_G,
    BRAIN_ROTTER, BRAIN_ROTTER_G,
    CUTTHROAT_KTHIR, CUTTHROAT_KTHIR_G,
    HARBINGER_APHLASS, HARBINGER_APHLASS_G,
)


def _num(game: "Game", card_id: str, index: int) -> int:
    """`CardDef.num(index)` 权威取值; 缺失 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return int(value)


# ══════════════════════════════════════════════════════════════════════
# F-08 公共工具
# ══════════════════════════════════════════════════════════════════════


def _discard_choice(game: "Game", hero: "Hero", then) -> bool:
    """"Discard a card" 交互: PendingChoice(kind="discard_card") → 弃置 →
    续结算 `then()`。手牌为空 → 返回 False（效果落空，费用已扣）。"""
    candidates = list(hero.hand)
    if not candidates:
        return False

    def resolve(pick):
        game.discard_card(hero, pick)
        then()

    game.pending_choices.append(PendingChoice(
        hero, candidates, "discard_card", resolve_callback=resolve))
    return True


def _gain_random_tavern_spells(game: "Game", hero: "Hero",
                               count: int) -> int:
    """随机获取 count 张池内酒馆法术进手牌（占池/满手排队）。"""
    gained = 0
    while gained < count:
        cands = game.tavern_spell_candidates()
        if not cands:
            break
        cid = game.rng.choice(cands, label="discard_random_tavern_spell")
        if not game.spell_pool.acquire(cid):
            break
        spell = game.create_spell(cid, controller=hero)
        if spell is None:
            break
        game.pending_hand_add(hero, spell)
        gained += 1
    return gained


def _aberrant_pool_ids(game: "Game") -> list:
    return [d.id for d in game.db.pool_minions()
            if Race.ABERRATION in d.races and game.minion_pool.available(d.id)]


def _gain_random_aberrations(game: "Game", hero: "Hero",
                             count: int) -> int:
    """随机获取 count 张池内 Aberration 随从进手牌（占池/满手排队）。"""
    gained = 0
    while gained < count:
        cands = _aberrant_pool_ids(game)
        if not cands:
            break
        cid = game.rng.choice(cands, label="discard_random_aberration")
        if not game.minion_pool.acquire(cid):
            break
        m = game.create_minion(cid, controller=hero)
        if m is None:
            break
        game.pending_hand_add(hero, m)
        gained += 1
    return gained


def _register_pair_discard(game: "Game", hero: "Hero", cards: list,
                           play_threshold: int) -> None:
    """成对弃置组: 打出 play_threshold 张后弃掉组内其余（F-08）。"""
    state = {"cards": list(cards), "played": 0,
             "threshold": max(1, int(play_threshold))}
    pairs = getattr(hero, "discard_pairs", None)
    if pairs is None:
        pairs = []
        hero.discard_pairs = pairs
    pairs.append(state)

    def on_played(g, card=None, **kw):
        if card not in state["cards"]:
            return
        state["played"] += 1
        if state["played"] < state["threshold"]:
            return
        for other in list(state["cards"]):
            if other is card:
                continue
            if other in hero.hand:
                g.discard_card(hero, other)
        if state in pairs:
            pairs.remove(state)

    game.events.register(Listener(
        event="card_played", owner=hero, callback=on_played))


class MangledBanditScript:
    """
    Natural language: <b>Activate ({1}):</b> Discard a card to get {0}
    <b>Blood Gems</b>.

    依据: CardDefs 37.0 BG28_582（T3 3/3 Quilboar，ACTIVATE；
    NUM_1=3=血宝石数；NUM_2=Activate 费用，数据 cost=0（F-08 修正））；
    金色 BG28_582_G（NUM_1=6）。

    Formal spec:
      1. activate（引擎扣费/计次）: `PendingChoice(kind="discard_card")`
         → 弃 1 张手牌 → `GetBloodGems(hero, NUM_1)`（血宝石非池 token，
         满手排队）。
      2. 手牌为空 → 效果落空（Activate 仍消耗）。
      3. 金色 NUM_1=6 由金色 CardDef 体现。

    Test: test_batch_37x_discard.py — 真实 use_activate: 扣 0 金 + 挂起
    discard_card / 选牌后手牌出现 NUM_1 颗 BG20_GEM / 空手牌落空不崩 /
    金色 6 颗 / 每回合一次。

    Params: {0}=3 {1}=0（金色 {0}=6）
    """

    @staticmethod
    def activate(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = _num(game, source.card_id, 0)

        def then():
            game.run_actions([GetBloodGems(hero, count)])

        _discard_choice(game, hero, then)
        return None


class BrainRotterScript:
    """
    Natural language: <b>Activate ({2}):</b> Discard a card to give your
    <b>Deity</b> +{0}/+{1}.

    依据: CardDefs 37.0 BG36_099（T2 3/4 Aberration，ACTIVATE，
    NUM_1=NUM_2=2，cost=0）；金色 BG36_099_G（4/4）。

    Formal spec: activate → Discard 1 张手牌 → `Game.give_deity_stats`
    (NUM_1, NUM_2)；空手牌落空。金色数值由金色 CardDef 体现。

    Test: test_batch_37x_discard.py — 弃牌后 Deity +2/+2 / 金 +4/+4 /
    空手牌落空。

    Params: {0}=2 {1}=2 {2}=0（金 4/4）
    """

    @staticmethod
    def activate(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)
        _discard_choice(
            game, hero, lambda: game.give_deity_stats(hero, atk, health))
        return None


class AbyssalEnvoyScript:
    """
    Natural language: [x]<b>Activate ({0}):</b> Discard a card to get a
    random Tavern spell.

    依据: CardDefs 37.0 BG36_311（T3 2/2 Aberration，ACTIVATE，cost=0）；
    金色 BG36_311_G 文本 "get 2 random Tavern spells"。

    Formal spec: activate → Discard 1 张手牌 → 随机 1 张池内酒馆法术
    （spell_pool.acquire + pending_hand_add）；金色 2 张；空手牌落空。

    Test: test_batch_37x_discard.py — 弃牌后入手 1 张池法术（cost 任意）/
    金色 2 张 / 空手牌落空。

    Params: {0}=0；金色张数=2（文本字面量）
    """

    @staticmethod
    def activate(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        _discard_choice(
            game, hero,
            lambda: _gain_random_tavern_spells(game, hero, count))
        return None


class MindbendingRecruiterScript:
    """
    Natural language: <b>Activate ({0}):</b> Discard a card to get a
    random Aberration.

    依据: CardDefs 37.0 BG36_312（T4 6/2 Aberration，ACTIVATE，cost=0）；
    金色 BG36_312_G 文本 "get 2 random Aberrations"。

    Formal spec: activate → Discard 1 张 → 随机 1 只池内 Aberration
    （minion_pool.acquire + pending_hand_add）；金色 2 只；空手牌落空。

    Test: test_batch_37x_discard.py — 弃牌后入手 1 只 Aberration（race）/
    金色 2 只 / 池记账 / 空手牌落空。

    Params: {0}=0；金色张数=2（文本字面量）
    """

    @staticmethod
    def activate(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        _discard_choice(
            game, hero,
            lambda: _gain_random_aberrations(game, hero, count))
        return None


class NraqiFrostcallerScript:
    """
    Natural language: [x]<b>Activate ({2}):</b> Discard a card for your
    Tavern spells to give an extra +{0}/+{1} this game.

    依据: CardDefs 37.0 BG36_300（T5 6/3 Aberration，ACTIVATE，
    NUM_1=NUM_2=1，cost=0）；金色 BG36_300_G（2/2）。

    Formal spec: activate → Discard 1 张 →
    `hero.TAVERN_SPELL_EXTRA_ATK += NUM_1`、`..._HEALTH += NUM_2`
    （全酒馆法术增幅，消费点 `tavern_spell_buff`）；金色 2/2。

    Test: test_batch_37x_discard.py — 弃牌后 tag 各 +1 / 金色 +2 /
    之后 Seafood Stew 实际多给 / 空手牌落空。

    Params: {0}=1 {1}=1 {2}=0（金 2/2）
    """

    @staticmethod
    def activate(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def then():
            hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                     hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + atk)
            hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                     hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + health)

        _discard_choice(game, hero, then)
        return None


class MindbenderGhurshaScript:
    """
    Natural language: Whenever you discard a card, give your other
    minions +{0}/+{1}.

    依据: CardDefs 37.0 BG36_097（T5 3/9 Aberration，NUM_1=NUM_2=4）；
    金色 BG36_097_G（8/8）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件
         `card_discarded`(hero=, card=)。
      2. 条件 hero is source.controller → 己方棋盘**除本体外**存活随从
         `Buff(+NUM_1/+NUM_2)`（"other minions"）。
      3. 金色数值由金色 CardDef 体现。

    Test: test_batch_37x_discard.py — 弃 1 张后其他随从 +4/+4、本体不变、
    对手不变 / 金色 +8/+8。

    Params: {0}=4 {1}=4（金 8/8）
    """

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_discard(g, hero=None, card=None, **kw):
            if hero is not source.controller:
                return
            d = g.db.get(source.card_id)
            g.run_actions([Buff(m, atk=int(d.num(0)), health=int(d.num(1)))
                           for m in list(source.controller.board)
                           if m is not source and not m.dead])

        game.events.register(Listener(
            event="card_discarded", owner=source, callback=on_discard))
        return None

    on_transform = on_summon


class CutthroatKThirScript:
    """
    Natural language: Whenever you discard a card, give this and your
    <b>Deity</b> +{0}/+{1}.

    依据: CardDefs 37.0 BG36_106（T4 4/4 Aberration，NUM_1=NUM_2=4）；
    金色 BG36_106_G（8/8）。

    Formal spec: 监听 `card_discarded`（owner=source，条件己方）→
    本体 `Buff(+NUM_1/+NUM_2)` + `give_deity_stats` 同额；金色 8/8。

    Test: test_batch_37x_discard.py — 弃牌后本体/Deity 同步 +4/+4 /
    金色 8/8 / 对手弃牌不触发。

    Params: {0}=4 {1}=4（金 8/8）
    """

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_discard(g, hero=None, card=None, **kw):
            if hero is not source.controller:
                return
            d = g.db.get(source.card_id)
            atk, health = int(d.num(0)), int(d.num(1))
            g.give_deity_stats(hero, atk, health)
            g.run_actions([Buff(source, atk=atk, health=health)])

        game.events.register(Listener(
            event="card_discarded", owner=source, callback=on_discard))
        return None

    on_transform = on_summon


class HarbingerAphlassScript:
    """
    Natural language: Whenever you discard a card, give your Deity
    +{0}/+{1} and improve this.

    依据: CardDefs 37.0 BGFYM_005（T6 3/6 Aberration，NUM_1=2 NUM_2=1）；
    金色 BGFYM_005_G（4/2）。

    Formal spec:
      1. 监听 `card_discarded`（owner=source，条件己方）。
      2. "improve this" = Improve 家族口径: 每次弃牌后本卡后续触发量
         按印面值递增（count += 1）；本次给 Deity 的量 =
         NUM_1×(1+count) / NUM_2×(1+count)，count 再 +1。
         count 存实体属性 `_aphlass_improves`（离场重置）。
      3. 金色数值由金色 CardDef 体现。

    Test: test_batch_37x_discard.py — 第 1 次 +2/+1、第 2 次 +4/+2、
    第 3 次 +6/+3 / 金色 4/2 起步。

    Params: {0}=2 {1}=1（金 4/2；Improve 增量 = 印面值）
    """

    improves_attr = "_aphlass_improves"

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_discard(g, hero=None, card=None, **kw):
            if hero is not source.controller:
                return
            d = g.db.get(source.card_id)
            count = getattr(source, HarbingerAphlassScript.improves_attr, 0)
            mult = 1 + count
            g.give_deity_stats(hero, int(d.num(0)) * mult,
                               int(d.num(1)) * mult)
            setattr(source, HarbingerAphlassScript.improves_attr, count + 1)

        game.events.register(Listener(
            event="card_discarded", owner=source, callback=on_discard))
        return None

    on_transform = on_summon


class ParasiticFleshlingScript:
    """
    Natural language: [x]At the end of your turn, give your left-most
    minion +{0}/+{1}. <i>(Improved by each card you've discarded this
    game!)</i>

    依据: CardDefs 37.0 BG36_114（T4 4/6 Aberration，NUM_1=NUM_2=2）；
    金色 BG36_114_G（4/4）。

    Formal spec: end_of_turn → 最左存活随从 `Buff(NUM_1×M, NUM_2×M)`，
    M = 1 + `hero.cards_discarded_this_game`（Improve 家族口径）；金色
    数值由金色 CardDef 体现；无随从 → 落空。

    Test: test_batch_37x_discard.py — 0 弃牌 +2/+2 / 弃 2 张后 +6/+6 /
    金色 +12/+12 / 无随从落空。

    Params: {0}=2 {1}=2（金 4/4；Improve 增量 = 印面值）
    """

    @staticmethod
    def end_of_turn(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        living = [m for m in hero.board if not m.dead]
        if not living:
            return None
        target = living[0]
        d = game.db.get(source.card_id)
        mult = 1 + int(getattr(hero, "cards_discarded_this_game", 0))
        return [Buff(target, atk=int(d.num(0)) * mult,
                     health=int(d.num(1)) * mult)]


class MysteriousKThirScript:
    """
    Natural language: [x]At the end of your turn, discard your {2}
    left-most Tavern spells. Gain +{0}/+{1} for each discarded.

    依据: CardDefs 37.0 BG36_320（T5 7/7 Aberration，NUM_1=NUM_2=7，
    NUM_3=3）；金色 BG36_320_G（7/7，NUM_3=6）。

    Formal spec: end_of_turn → 从**手牌**按顺序取前 NUM_3 张
    `CardDef.is_pool_spell` 卡，逐张 `Game.discard_card`（触发
    on_discard/card_discarded 事件链）；按实际弃置数 n 给本体
    `Buff(NUM_1×n, NUM_2×n)`；手牌无酒馆法术 → 落空。

    Test: test_batch_37x_discard.py — 3 张酒馆法术 + 1 张随从 → 弃前 3
    张、本体 +21/+21 / 金色弃 6 张 +42/+42 / 不足 n 张按实际数。

    Params: {0}=7 {1}=7 {2}=3（金 {2}=6）
    """

    @staticmethod
    def end_of_turn(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        limit = _num(game, source.card_id, 2)
        discarded = 0
        for card in list(hero.hand):
            if discarded >= limit:
                break
            d = getattr(card, "card_def", None)
            if d is None:
                d = game.db.get(getattr(card, "card_id", ""))
            if d is None or not d.is_pool_spell:
                continue
            if game.discard_card(hero, card):
                discarded += 1
        if not discarded:
            return None
        d = game.db.get(source.card_id)
        return [Buff(source, atk=int(d.num(0)) * discarded,
                     health=int(d.num(1)) * discarded)]


class WanderingWillbreakerScript:
    """
    Natural language: When you sell this, get 2 random Tavern spells.
    When you play one, discard the other.

    依据: CardDefs 37.0 BG36_100（T2 1/3 Aberration）；金色
    BG36_100_G 文本 "get 4 random Tavern spells. When you play two,
    discard the others."。

    Formal spec:
      1. on_sell（真实售出钩子）: 生成 2（金 4）张随机池内酒馆法术进
         手牌（spell_pool.acquire + pending_hand_add）。
      2. 成对弃置（F-08 `_register_pair_discard`）: 监听 `card_played`；
         打出该组 1 张（金 2 张）后弃掉组内其余手牌
         （`Game.discard_card`）。
      3. "or Pass" 属 Duos 语义（本引擎无 Pass，边界记档）。

    Test: test_batch_37x_discard.py — 售出后入手 2 张池法术 / 打其中 1
    张后另 1 张被弃（hand 移除、弃牌计数 +1）/ 金色 4 张、打 2 张后弃
    其余 2 张。

    Params: 无数值参数（2/4 与 1/2 为文本字面量，金卡分支）
    """

    @staticmethod
    def on_sell(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 4 if source.is_golden else 2
        before = set(hero.hand)
        _gain_random_tavern_spells(game, hero, count)
        new_cards = [c for c in hero.hand if c not in before]
        if new_cards:
            _register_pair_discard(game, hero, new_cards,
                                   len(new_cards) // 2)
        return None


class FacelessOperativeScript:
    """
    Natural language: [x]When you sell this, get 2 random Aberrations.
    When you play one, discard the other.

    依据: CardDefs 37.0 BG36_308（T4 4/2 Aberration）；金色
    BG36_308_G 文本 "get 4 random Aberrations. When you play two,
    discard the others."。

    Formal spec:
      1. on_sell: 生成 2（金 4）只随机池内 Aberration 进手牌
         （minion_pool.acquire + pending_hand_add）。
      2. 成对弃置同 Wandering Willbreaker（打出 1/2 张后弃其余）。
      3. "or Pass" 属 Duos（边界记档）。

    Test: test_batch_37x_discard.py — 售出后入手 2 只 Aberration / 打
    其中 1 只后另 1 只被弃 / 金色 4 只、打 2 只后弃其余。

    Params: 无数值参数（2/4 与 1/2 为文本字面量）
    """

    @staticmethod
    def on_sell(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 4 if source.is_golden else 2
        before = set(hero.hand)
        _gain_random_aberrations(game, hero, count)
        new_cards = [c for c in hero.hand if c not in before]
        if new_cards:
            _register_pair_discard(game, hero, new_cards,
                                   len(new_cards) // 2)
        return None


def register() -> list[str]:
    """注册 24 id（12 张池内 discard 族/Deity-discard 卡 ×基础/金色）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (MANGLED_BANDIT, MangledBanditScript),
        (MANGLED_BANDIT_G, MangledBanditScript),
        (MINDBENDER_GHURSHA, MindbenderGhurshaScript),
        (MINDBENDER_GHURSHA_G, MindbenderGhurshaScript),
        (WANDERING_WILLBREAKER, WanderingWillbreakerScript),
        (WANDERING_WILLBREAKER_G, WanderingWillbreakerScript),
        (PARASITIC_FLESHLING, ParasiticFleshlingScript),
        (PARASITIC_FLESHLING_G, ParasiticFleshlingScript),
        (NRAQI_FROSTCALLER, NraqiFrostcallerScript),
        (NRAQI_FROSTCALLER_G, NraqiFrostcallerScript),
        (FACELESS_OPERATIVE, FacelessOperativeScript),
        (FACELESS_OPERATIVE_G, FacelessOperativeScript),
        (ABYSSAL_ENVOY, AbyssalEnvoyScript),
        (ABYSSAL_ENVOY_G, AbyssalEnvoyScript),
        (MINDBENDING_RECRUITER, MindbendingRecruiterScript),
        (MINDBENDING_RECRUITER_G, MindbendingRecruiterScript),
        (MYSTERIOUS_KTHIR, MysteriousKThirScript),
        (MYSTERIOUS_KTHIR_G, MysteriousKThirScript),
        (BRAIN_ROTTER, BrainRotterScript),
        (BRAIN_ROTTER_G, BrainRotterScript),
        (CUTTHROAT_KTHIR, CutthroatKThirScript),
        (CUTTHROAT_KTHIR_G, CutthroatKThirScript),
        (HARBINGER_APHLASS, HarbingerAphlassScript),
        (HARBINGER_APHLASS_G, HarbingerAphlassScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
