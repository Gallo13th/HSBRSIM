"""F-16 C'Thun awaken split（真实 Power.log 证据）。

证据：`runs/powerlog_2214/Power.log`
  * 172605：C'Thun 191/138，N=2 个其它友方随从 → 每个 +95/+69
    （floor(191/2)=95、floor(138/2)=69，余数丢弃）；
  * 174028：C'Thun 33/33，N=3 → 每个 +11/+11；
  * 108099：C'Thun 1/1，N=1 → 目标 +1/+1。
本测试先红（旧引擎 DEFERRED 不施加 split），修复后绿。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
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


def make_game(seed: int = 31700) -> Game:
    return Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
                get_db(), seed=seed)


def add_minion(g: Game, hero, card_id: str = "BG25_013"):
    m = g.create_minion(card_id, controller=hero)
    assert m is not None and g.summon(hero, m)
    return m


class TestCThunSplit(unittest.TestCase):
    def _awaken(self, g, deity_atk: int, deity_health: int,
                others: int):
        a = g.heroes[0]
        bases = []
        for _ in range(others):
            m = add_minion(g, a)
            bases.append((m.atk, m.health))
        g.inject_deity_state(
            a, card_id="BGFYM_000", atk=deity_atk,
            health=deity_health, progress=4, awakened=False)
        self.assertTrue(g._maybe_awaken_deity(a))
        token = [m for m in a.board
                 if m.card_id in ("BGFYM_000", "BGFYM_000_G")]
        self.assertEqual(len(token), 1)
        return a, token[0], bases

    def test_split_two_targets_floor(self):
        g = make_game(seed=31700)
        a, token, bases = self._awaken(g, 191, 138, others=2)
        others = [m for m in a.board if m is not token]
        self.assertEqual(len(others), 2)
        for (base_atk, base_health), m in zip(bases, others):
            self.assertEqual((m.atk - base_atk, m.health - base_health),
                             (95, 69))

    def test_split_three_targets_floor(self):
        g = make_game(seed=31701)
        a, token, bases = self._awaken(g, 33, 33, others=3)
        others = [m for m in a.board if m is not token]
        self.assertEqual(len(others), 3)
        for (base_atk, base_health), m in zip(bases, others):
            self.assertEqual((m.atk - base_atk, m.health - base_health),
                             (11, 11))

    def test_split_one_target_gets_all(self):
        g = make_game(seed=31702)
        a, token, bases = self._awaken(g, 1, 1, others=1)
        others = [m for m in a.board if m is not token]
        base_atk, base_health = bases[0]
        self.assertEqual((others[0].atk - base_atk,
                          others[0].health - base_health), (1, 1))

    def test_no_other_minions_does_not_crash(self):
        g = make_game(seed=31703)
        a, token, _ = self._awaken(g, 33, 33, others=0)
        self.assertEqual(len([m for m in a.board if m is not token]), 0)


if __name__ == "__main__":
    unittest.main()
