"""批次 trinkets10 — 免费购买协议族 3 张（RULES §7.4.4，2026-09-02）。

引擎原语（本批依赖，均已在主线落地）:
  - `GameTag.FREE_SPELL_BUYS_THIS_TURN`（免费酒馆法术购买计数）
  - `GameTag.FREE_MINION_BUYS_THIS_TURN` + `FREE_MINION_BUY_RACE` /
    `FREE_MINION_BUY_KEYWORD`（种族/关键词限定的免费随从购买）
  - 消费点 = `game.buy_from_tavern`（**仅在成交且限定匹配时**消费;
    失败购买不烧次数）

实现状态: 3 张全部 CORRECT。

  BG30_MagicItem_986  Peacebloom Candle  — 每回合前 num(1) 张酒馆法术免费
  BG32_MagicItem_957  Grifter Portrait   — 获得 Doubloon Grifter;
                                            每回合首个海盗免费
  BG36_MagicItem_202  Warcry Totem       — 每回合前 num(0) 个战吼随从免费

DEFERRED: 无（本批范围内）。

机制口径:
  - "each turn" = `on_bind`（绑定当回合）+ `start_of_turn`（之后每回合）
    都**覆盖式**写入计数 → 上回合未用完的次数不累积（"the first N each
    turn" 的逐一回合语义）。
  - 免费购买**不改变**池记账（`buy_from_tavern` 只在扣费分支短路；
    随从/法术照常入手与占池/回池）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.events import TURN_START, Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


def _hero(ctx):
    return (ctx or {}).get("hero")


def _per_turn_counter(source, game, hero, tag: int, value: int,
                      extra: dict | None = None) -> None:
    """每回合覆盖式写入免费购买计数（on_bind + 每回合 start_of_turn）。

    `FREE_MINION_BUYS_THIS_TURN` 走 `game.set_free_minion_buys` 的
    **每来源独立配额**（RULES §7.4.4）——同一英雄同时持有 Grifter
    Portrait 与 Warcry Totem 时两份额度互不覆盖（旧单 tag 模型会让
    "海盗免费"与"战吼免费"退化成"海盗战吼才免费"）。
    其余 tag（如 `FREE_SPELL_BUYS_THIS_TURN`）仍为单 tag 覆盖式。
    """
    extra = dict(extra or {})

    def _apply(h, g):
        if tag == GameTag.FREE_MINION_BUYS_THIS_TURN:
            g.set_free_minion_buys(
                h, value, source=source.card_id,
                race=extra.get(GameTag.FREE_MINION_BUY_RACE),
                keyword=extra.get(GameTag.FREE_MINION_BUY_KEYWORD))
            return
        h.set(tag, value)
        for k, v in extra.items():
            h.set(k, v)

    _apply(hero, game)

    def on_sot(g, hero=None, _h=hero, **kw):
        if hero is not _h:
            return
        _apply(_h, g)

    game.events.register(Listener(event=TURN_START, owner=source,
                                  callback=on_sot))


# ══════════════════ BG30_MagicItem_986 Peacebloom Candle ══════════════════


class PeacebloomCandleScript:
    """
    Natural language: The first {1} Tavern spells you buy each turn are
    free. <i>({0} left!)</i>

    Formal spec:
      1. on_bind / 每回合 start_of_turn: `FREE_SPELL_BUYS_THIS_TURN =
         num(1)`（{1} 是主句里的张数; 数据 num(0)==num(1)==3，故取
         num(1) 与文本占位符一致）
      2. 消费在 `game.buy_from_tavern`（仅 `is_pool_spell` 且成交时递减;
         免费时 cost=0，优先于 NEXT_SPELL_COST_REDUCTION）
      3. "each turn" = 覆盖式写入（未用完不累积）

    Test: test_batch_trinkets10.py — 绑定当回合 3 张免费（金币不动）/
      第 4 张正常收费 / 下一回合计数重置为 3 / 对手不受影响

    Params: {1}=3（主句张数; num(0)==3 为计数器显示）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        n = d.num(1, d.num(0, 1)) if d is not None else 1
        _per_turn_counter(source, game, hero,
                          GameTag.FREE_SPELL_BUYS_THIS_TURN, n)
        return None


# ══════════════════ BG32_MagicItem_957 Grifter Portrait ══════════════════


class GrifterPortraitScript:
    """
    Natural language: Get a Doubloon Grifter. The first Pirate you buy
    each turn is free.

    Formal spec:
      1. on_bind: 授予 Doubloon Grifter（`evolution_card_id` dbf 116035 →
         BG31_826; 数据实测 `is_pool_minion=False` → 池外 token，
         **零池操作**，与其它 token 授予同口径）入手（满手排队）
      2. on_bind / 每回合 start_of_turn: `FREE_MINION_BUYS_THIS_TURN = 1`
         + `FREE_MINION_BUY_RACE = Race.PIRATE`（"the first Pirate";
         种族匹配含 ALL——引擎 `_free_minion_buy_matches`）
      3. 消费在 `buy_from_tavern`（仅在成交且种族匹配时递减）

    Test: test_batch_trinkets10.py — 绑定后 Doubloon Grifter 入手且不占池 /
      首个海盗免费（金币不动）第二只收费 / 非海盗不消耗计数（正对照）/
      每回合重置 / 对手不受影响

    Params: count=1（"The first Pirate" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        token_id = None
        if d is not None and d.evolution_card_id is not None:
            td = game.db.by_dbf(d.evolution_card_id)
            if td is not None:
                token_id = td.id
        if token_id is not None:
            m = game.create_minion(token_id, controller=hero)
            game.pending_hand_add(hero, m)
        _per_turn_counter(source, game, hero,
                          GameTag.FREE_MINION_BUYS_THIS_TURN, 1,
                          {GameTag.FREE_MINION_BUY_RACE: int(Race.PIRATE)})
        return None


# ══════════════════ BG36_MagicItem_202 Warcry Totem ══════════════════


class WarcryTotemScript:
    """
    Natural language: The first two <b>Battlecry</b> minions you buy each
    turn are free. <i>({0} left!)</i>

    Formal spec:
      1. on_bind / 每回合 start_of_turn: `FREE_MINION_BUYS_THIS_TURN =
         num(0)`（=2）+ `FREE_MINION_BUY_KEYWORD = GameTag.BATTLECRY`
      2. 消费在 `buy_from_tavern`（仅在成交且随从带 BATTLECRY 时递减;
         不带战吼的随从照常收费且不消耗计数——正对照）
      3. "each turn" = 覆盖式写入（未用完不累积）

    Test: test_batch_trinkets10.py — 前两个战吼随从免费 / 非战吼随从收费
      且计数不变 / 第三个战吼收费 / 每回合重置

    Params: {0}=2（num(0)，"The first two"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        n = d.num(0, 2) if d is not None else 2
        _per_turn_counter(
            source, game, hero, GameTag.FREE_MINION_BUYS_THIS_TURN, n,
            {GameTag.FREE_MINION_BUY_KEYWORD: int(GameTag.BATTLECRY)})
        return None


def register() -> list[str]:
    """注册免费购买族 3 张。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_986", PeacebloomCandleScript),
        ("BG32_MagicItem_957", GrifterPortraitScript),
        ("BG36_MagicItem_202", WarcryTotemScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
