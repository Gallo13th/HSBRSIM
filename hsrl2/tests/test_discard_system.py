"""F-08: Discard 子系统引擎原语测试（`Game.discard_card` 等）。

覆盖:
  - 手牌移除 → GRAVEYARD；`hero.cards_discarded_this_game` 计数
  - `card_discarded` 事件广播
  - `on_discard` 钩子分发（用已注册的 Sludge Corrosion）
  - 非手牌/None 不弃
  - Activate cost=0 数据缺省修正（`activate` 关键词权威）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900) -> Game:
    return Game([Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")],
                get_db(), seed=seed)


def dummy(hero: Hero, name: str = "D", atk: int = 1,
          health: int = 20) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    hero.board.append(m)
    game._update_positions(hero)
    return m


def hand_spell(game: Game, hero: Hero, card_id: str):
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


class TestDiscardPrimitive(unittest.TestCase):
    def test_discard_removes_from_hand_and_counts(self):
        game = make_game()
        a = game.heroes[0]
        spell = hand_spell(game, a, "BG28_810")
        self.assertEqual(a.cards_discarded_this_game, 0)
        self.assertTrue(game.discard_card(a, spell))
        self.assertNotIn(spell, a.hand)
        self.assertEqual(spell.zone, Zone.GRAVEYARD)
        self.assertEqual(a.cards_discarded_this_game, 1)

    def test_discard_fires_event(self):
        game = make_game()
        a = game.heroes[0]
        events = []
        game.events.register(Listener(
            event="card_discarded", owner=a,
            callback=lambda g, card=None, **kw: events.append(card)))
        spell = hand_spell(game, a, "BG28_810")
        game.discard_card(a, spell)
        self.assertEqual(events, [spell])

    def test_discard_runs_on_discard_hook(self):
        """Sludge Corrosion 已注册 on_discard → 全板 +2/+2（1/1 两次）。"""
        game = make_game()
        a = game.heroes[0]
        ally = dummy(a, "Ally", 1, 20)
        spell = hand_spell(game, a, "BG36_301t")
        self.assertTrue(game.discard_card(a, spell))
        self.assertEqual((ally.atk, ally.health), (3, 22))

    def test_discard_non_hand_card_fails(self):
        game = make_game()
        a = game.heroes[0]
        m = Minion("TEST_X", "X", atk=1, health=1)
        m.game = game
        m.controller = a
        m.zone = Zone.PLAY
        a.board.append(m)
        self.assertFalse(game.discard_card(a, m))
        self.assertFalse(game.discard_card(a, None))
        self.assertEqual(a.cards_discarded_this_game, 0)

    def test_discard_does_not_trigger_play_hooks(self):
        game = make_game()
        a = game.heroes[0]
        played = []
        game.events.register(Listener(
            event="card_played", owner=a,
            callback=lambda g, card=None, **kw: played.append(card)))
        spell = hand_spell(game, a, "BG28_810")
        game.discard_card(a, spell)
        self.assertEqual(played, [])

    def test_counter_accumulates(self):
        game = make_game()
        a = game.heroes[0]
        for _ in range(3):
            game.discard_card(a, hand_spell(game, a, "BG28_810"))
        self.assertEqual(a.cards_discarded_this_game, 3)


class TestActivateCostZero(unittest.TestCase):
    """F-08: 数据在 Activate cost=0 时省略 activate_cost → 以关键词为准。"""

    def test_activate_zero_cost_tagged(self):
        game = make_game()
        a = game.heroes[0]
        m = game.create_minion("BG36_099", controller=a)   # Brain Rotter
        self.assertTrue(m.has(GameTag.ACTIVATE))
        self.assertEqual(m.get(GameTag.ACTIVATE_COST), 0)

    def test_use_activate_zero_cost(self):
        game = make_game()
        a = game.heroes[0]
        m = game.create_minion("BG36_099", controller=a)
        game.summon(a, m)
        a.gold = 0
        self.assertTrue(game.use_activate(a, m))
        self.assertEqual(a.gold, 0)
        self.assertFalse(game.use_activate(a, m))       # 每回合一次


if __name__ == "__main__":
    unittest.main()
