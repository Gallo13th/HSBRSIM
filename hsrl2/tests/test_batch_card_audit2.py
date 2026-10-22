"""卡牌审计第二轮测试：Bristleback Bully BG35_432/_G 亡语 Get token。"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts.batches.batch_card_audit2 import GEM_TAUNT

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 31600) -> Game:
    return Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
                get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False):
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert m is not None and game.summon(hero, m)
    return m


class TestBristlebackBully(unittest.TestCase):
    def test_deathrattle_gets_one_taunt_gem(self):
        g = make_game(seed=31600)
        a = g.heroes[0]
        bully = put(g, "BG35_432", a)
        g.destroy_minion(bully)
        self.assertEqual([c.card_id for c in a.hand], [GEM_TAUNT])

    def test_golden_gets_two_taunt_gems(self):
        g = make_game(seed=31601)
        a = g.heroes[0]
        bully = put(g, "BG35_432_G", a, golden=True)
        g.destroy_minion(bully)
        self.assertEqual([c.card_id for c in a.hand],
                         [GEM_TAUNT, GEM_TAUNT])

    def test_no_hand_copy_before_death(self):
        g = make_game(seed=31602)
        a = g.heroes[0]
        put(g, "BG35_432", a)
        self.assertEqual(a.hand, [])

    def test_token_is_registered_blood_gem_taunt(self):
        self.assertIsNotNone(get_db().get(GEM_TAUNT))


if __name__ == "__main__":
    unittest.main()
