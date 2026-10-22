"""卡牌审计第二轮测试：Moonsteel Juggernaut EoT 卫星（BG31_171/_G）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import TURN_END
from hsrl2.game import Game
from hsrl2.hero import Hero

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 31800) -> Game:
    return Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
                get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False):
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert m is not None and game.summon(hero, m)
    return m


def fire_turn_end(game: Game) -> None:
    game.events.fire(game, TURN_END, turn=game.turn)


class TestMoonsteelJuggernaut(unittest.TestCase):
    def test_normal_two_turns(self):
        g = make_game(seed=31800)
        a = g.heroes[0]
        m = put(g, "BG31_171", a)
        fire_turn_end(g)
        self.assertEqual([(c.card_id, c.atk, c.health) for c in a.hand],
                         [("BG31_171t", 6, 6), ("BG31_171t", 6, 6)])
        fire_turn_end(g)
        self.assertEqual([(c.atk, c.health) for c in a.hand],
                         [(6, 6), (6, 6), (12, 12), (12, 12)])
        self.assertEqual((m.atk, m.health), (8, 8),
                         "Moonsteel 本体不应被脚本改属性")

    def test_golden_two_turns(self):
        g = make_game(seed=31801)
        a = g.heroes[0]
        put(g, "BG31_171_G", a, golden=True)
        fire_turn_end(g)
        self.assertEqual([(c.card_id, c.atk, c.health) for c in a.hand],
                         [("BG31_171_Gt", 12, 12),
                          ("BG31_171_Gt", 12, 12)])
        fire_turn_end(g)
        self.assertEqual([(c.atk, c.health) for c in a.hand],
                         [(12, 12), (12, 12), (24, 24), (24, 24)])

    def test_sold_source_stops(self):
        g = make_game(seed=31802)
        a = g.heroes[0]
        m = put(g, "BG31_171", a)
        g.destroy_minion(m)
        fire_turn_end(g)
        self.assertEqual(a.hand, [])


if __name__ == "__main__":
    unittest.main()
