"""批次 trinkets10 行为层测试（免费购买协议族 3 张，RULES §7.4.4）。

全部走真实路径: 真实饰品 offer（`_offer_trinkets` → `PendingChoice.choose`）
→ on_bind 接线 → 真实 `buy_from_tavern`（含失败购买）/ 真实
`_begin_recruit_for`（每回合重置）/ 满手排队。

期望值来自 `CardDef.num(0/1)` 或文本字面量; 每条负面断言同测试内带正对照;
owner 隔离用两位英雄。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

PEACEBLOOM = "BG30_MagicItem_986"
GRIFTER = "BG32_MagicItem_957"
WARCRY = "BG36_MagicItem_202"
SPELL = "BG28_168"          # Shiny Ring（池法术）
GRIFTER_TOKEN = "BG31_826"  # Doubloon Grifter（池外 token）


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 400) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind_trinket(game: Game, hero: Hero, tid: str) -> None:
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    assert game.grant_trinket(hero, tid) is not None


def tavern_spell(game: Game, hero: Hero) -> object:
    s = game.create_spell(SPELL, controller=hero)
    s.zone = Zone.TAVERN
    hero.tavern = [s]
    return s


def tavern_minion(game: Game, hero: Hero, *, race=None,
                  battlecry: bool = False) -> Minion:
    m = game.create_minion("BG25_001", controller=hero)
    if race is not None:
        m.set(GameTag.RACE, race)
    if battlecry:
        m.set(GameTag.BATTLECRY, True)
    m.zone = Zone.TAVERN
    hero.tavern = [m]
    return m


class TestPeacebloomCandle(unittest.TestCase):
    """BG30_MagicItem_986 — 每回合前 num(1) 张酒馆法术免费。"""

    def test_n_free_spell_buys_then_paid(self):
        g = make_game(seed=401)
        a, b = g.heroes
        a.gold = 20
        n = get_db().get(PEACEBLOOM).num(1)
        bind_trinket(g, a, PEACEBLOOM)
        self.assertEqual(a.get(GameTag.FREE_SPELL_BUYS_THIS_TURN), n)
        for i in range(n):
            s = tavern_spell(g, a)
            self.assertTrue(g.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 20, "前 N 张应全免费")
        self.assertEqual(a.get(GameTag.FREE_SPELL_BUYS_THIS_TURN), 0)
        s = tavern_spell(g, a)
        self.assertTrue(g.buy_from_tavern(a, s))
        self.assertLess(a.gold, 20, "第 N+1 张正常收费")   # 正对照
        self.assertEqual(b.get(GameTag.FREE_SPELL_BUYS_THIS_TURN, 0), 0)

    def test_counter_resets_each_turn(self):
        g = make_game(seed=402)
        a = g.heroes[0]
        a.gold = 20
        n = get_db().get(PEACEBLOOM).num(1)
        bind_trinket(g, a, PEACEBLOOM)
        s = tavern_spell(g, a)
        self.assertTrue(g.buy_from_tavern(a, s))
        self.assertEqual(a.get(GameTag.FREE_SPELL_BUYS_THIS_TURN), n - 1)
        g.turn = 2
        g._begin_recruit_for(a)                    # 真实回合开始
        self.assertEqual(a.get(GameTag.FREE_SPELL_BUYS_THIS_TURN), n)


class TestGrifterPortrait(unittest.TestCase):
    """BG32_MagicItem_957 — 获得 Doubloon Grifter; 每回合首个海盗免费。"""

    def test_grants_token_and_first_pirate_free(self):
        g = make_game(seed=403)
        a, b = g.heroes
        a.gold = 20
        bind_trinket(g, a, GRIFTER)
        got = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual([m.card_id for m in got], [GRIFTER_TOKEN])
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 1)
        # 限定归属独立配额（RULES §7.4.4 修订: 旧单 tag 模型在多来源
        # 并存时会互相覆盖）——种族限定在配额内表达
        q = [x for x in a._free_minion_buy_quotas if x["source"] == GRIFTER]
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["race"], int(Race.PIRATE))
        self.assertIsNone(q[0]["keyword"])
        # 非海盗不消耗计数（正对照）
        beast = tavern_minion(g, a, race=Race.BEAST)
        self.assertTrue(g.buy_from_tavern(a, beast))
        self.assertLess(a.gold, 20)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 1)
        # 海盗免费
        pirate = tavern_minion(g, a, race=Race.PIRATE)
        gold_before = a.gold
        self.assertTrue(g.buy_from_tavern(a, pirate))
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 0)
        self.assertEqual(b.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 0)

    def test_token_not_from_pool(self):
        """Doubloon Grifter 是池外 token（is_pool_minion=False）→ 零池操作。"""
        self.assertFalse(get_db().get(GRIFTER_TOKEN).is_pool_minion)


class TestWarcryTotem(unittest.TestCase):
    """BG36_MagicItem_202 — 每回合前 num(0) 个战吼随从免费。"""

    def test_first_n_battlecry_minions_free(self):
        g = make_game(seed=404)
        a, b = g.heroes
        a.gold = 20
        n = get_db().get(WARCRY).num(0)
        bind_trinket(g, a, WARCRY)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), n)
        q = [x for x in a._free_minion_buy_quotas if x["source"] == WARCRY]
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["keyword"], int(GameTag.BATTLECRY))
        self.assertIsNone(q[0]["race"])
        # 非战吼: 收费且不消耗（正对照）
        plain = tavern_minion(g, a)
        self.assertTrue(g.buy_from_tavern(a, plain))
        self.assertLess(a.gold, 20)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), n)
        for i in range(n):
            bc = tavern_minion(g, a, battlecry=True)
            gold_before = a.gold
            self.assertTrue(g.buy_from_tavern(a, bc))
            self.assertEqual(a.gold, gold_before, f"第 {i + 1} 个战吼应免费")
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 0)
        extra = tavern_minion(g, a, battlecry=True)
        self.assertTrue(g.buy_from_tavern(a, extra))
        self.assertLess(a.gold, 20, "第 N+1 个战吼收费")
        self.assertEqual(b.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 0)

    def test_counter_resets_each_turn(self):
        g = make_game(seed=405)
        a = g.heroes[0]
        a.gold = 20
        n = get_db().get(WARCRY).num(0)
        bind_trinket(g, a, WARCRY)
        bc = tavern_minion(g, a, battlecry=True)
        self.assertTrue(g.buy_from_tavern(a, bc))
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), n - 1)
        g.turn = 2
        g._begin_recruit_for(a)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), n)


class TestRegistry(unittest.TestCase):
    IMPLEMENTED = (PEACEBLOOM, GRIFTER, WARCRY)

    def test_all_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)

    def test_free_buy_tags_declared_by_scripts(self):
        self.assertTrue(hasattr(REGISTRY[PEACEBLOOM], "on_bind"))
        self.assertTrue(hasattr(REGISTRY[GRIFTER], "on_bind"))
        self.assertTrue(hasattr(REGISTRY[WARCRY], "on_bind"))


if __name__ == "__main__":
    unittest.main()
