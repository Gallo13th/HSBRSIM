"""原语测试（F-12）:
  - `Game.minion_gained(hero, minion)` 统一入手事件（单点，防重复）；
  - `Game.combat_spell_extra_casts(hero)` + `cast_spell_effect` 战斗内
    额外施放（默认 0 → 逐位不变）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
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
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    return g


def make_minion(game: Game, hero: Hero, card_id: str = "BG25_013"):
    m = game.create_minion(card_id, controller=hero)
    assert m is not None
    return m


class TestMinionGainedEvent(unittest.TestCase):
    def _record(self, game: Game, hero: Hero):
        events = []

        def cb(g, hero=None, minion=None, **kw):
            events.append((hero, minion))

        game.events.register(Listener(event="minion_gained", owner=hero,
                                      callback=cb))
        return events

    def test_pending_hand_add_fires_once(self):
        g = make_game(seed=901)
        a = g.heroes[0]
        events = self._record(g, a)
        m = make_minion(g, a)
        self.assertTrue(g.pending_hand_add(a, m))
        self.assertEqual(len(events), 1)
        self.assertIs(events[0][0], a)
        self.assertIs(events[0][1], m)
        self.assertIs(m.zone, Zone.HAND)

    def test_buy_from_tavern_fires_once(self):
        g = make_game(seed=902)
        a = g.heroes[0]
        events = self._record(g, a)
        m = make_minion(g, a)
        a.tavern.append(m)
        a.set(GameTag.GOLD, 10)
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertEqual(len(events), 1)
        self.assertIs(events[0][1], m)

    def test_spell_gain_does_not_fire(self):
        g = make_game(seed=903)
        a = g.heroes[0]
        events = self._record(g, a)
        spell = g.create_spell("BG20_GEM", controller=a)
        self.assertTrue(g.pending_hand_add(a, spell))
        self.assertEqual(events, [])

    def test_full_hand_deferred_does_not_fire(self):
        g = make_game(seed=904)
        a = g.heroes[0]
        events = self._record(g, a)
        for _ in range(10):
            filler = g.create_spell("BG20_GEM", controller=a)
            filler.zone = Zone.HAND
            a.hand.append(filler)
        m = make_minion(g, a)
        self.assertFalse(g.pending_hand_add(a, m))
        self.assertEqual(events, [])
        self.assertEqual(len(g.pending_hand_queue), 1)

    def test_direct_add_to_hand_fires_once(self):
        g = make_game(seed=905)
        a = g.heroes[0]
        events = self._record(g, a)
        m = make_minion(g, a)
        self.assertTrue(a.add_to_hand(m))
        self.assertEqual(len(events), 1)


class TestCombatSpellExtraCasts(unittest.TestCase):
    def test_default_zero(self):
        g = make_game(seed=906)
        self.assertEqual(g.combat_spell_extra_casts(g.heroes[0]), 0)

    def test_default_cast_effect_unchanged_in_combat(self):
        g = make_game(seed=907)
        a = g.heroes[0]
        m = make_minion(g, a)
        assert g.summon(a, m)
        g.in_combat = True
        base = (m.atk, m.max_health)
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=m))
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 1, base[1] + 1))

    def test_extra_casts_repeat_effect_in_combat(self):
        g = make_game(seed=908)
        a = g.heroes[0]
        m = make_minion(g, a)
        assert g.summon(a, m)
        g.in_combat = True
        a._combat_spell_extra_casts = 2
        base = (m.atk, m.max_health)
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=m))
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 3, base[1] + 3))

    def test_extra_casts_ignored_outside_combat(self):
        g = make_game(seed=909)
        a = g.heroes[0]
        m = make_minion(g, a)
        assert g.summon(a, m)
        a._combat_spell_extra_casts = 2
        base = (m.atk, m.max_health)
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=m))
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 1, base[1] + 1))

    def test_cast_no_increments_per_extra_cast(self):
        g = make_game(seed=910)
        a = g.heroes[0]
        m = make_minion(g, a)
        assert g.summon(a, m)
        g.in_combat = True
        a._combat_spell_extra_casts = 1
        seen = []

        def on_resolving(game, spell=None, cast_no=None, **kw):
            seen.append(cast_no)

        g.events.register(Listener(event="spell_resolving", owner=a,
                                   callback=on_resolving))
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=m))
        self.assertEqual(seen, [1, 2])

    def test_negative_value_clamped(self):
        g = make_game(seed=911)
        a = g.heroes[0]
        a._combat_spell_extra_casts = -3
        self.assertEqual(g.combat_spell_extra_casts(a), 0)


if __name__ == "__main__":
    unittest.main()
