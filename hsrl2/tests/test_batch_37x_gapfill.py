"""BG32_234 Dastardly Drust + BG34_922 Maelstrom Emergent 收口测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Hit
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts.batches.batch_37x_gapfill import MaelstromEmergentScript
from hsrl2.tags import GameTag, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
_db = None
DRUST = "BG32_234"
DRUST_G = "BG32_234_G"
MAELSTROM = "BG34_922"
MAELSTROM_G = "BG34_922_G"
PIRATE = "BG35_701"          # Brazen Buccaneer (Pirate)
NON_PIRATE = "BG25_013"      # Rot Hide Gnoll (Undead)


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 2400) -> Game:
    return Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
                get_db(), seed=seed)


def put(game: Game, hero: Hero, card_id: str, *,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert m is not None
    assert game.summon(hero, m)
    return m


def gain(game: Game, hero: Hero, card_id: str, *,
         golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert m is not None
    assert game.pending_hand_add(hero, m)
    return m


class TestDastardlyDrust(unittest.TestCase):
    def _setup(self, *, golden_drust=False):
        g = make_game(seed=2401)
        a = g.heroes[0]
        drust = put(g, a, DRUST_G if golden_drust else DRUST)
        ally = put(g, a, NON_PIRATE)
        return g, a, drust, ally

    def test_normal_pirate_buffs_all_friendly(self):
        g, a, drust, ally = self._setup()
        base = (drust.atk, drust.max_health, ally.atk, ally.max_health)
        gain(g, a, PIRATE)
        self.assertEqual((drust.atk, drust.max_health),
                         (base[0] + 2, base[1] + 2))
        self.assertEqual((ally.atk, ally.max_health),
                         (base[2] + 2, base[3] + 2))

    def test_golden_pirate_uses_golden_nums(self):
        g, a, drust, ally = self._setup()
        base = (drust.atk, drust.max_health)
        gain(g, a, PIRATE, golden=True)
        self.assertEqual((drust.atk, drust.max_health),
                         (base[0] + 6, base[1] + 6))

    def test_golden_drust_nums(self):
        g, a, drust, ally = self._setup(golden_drust=True)
        base = (drust.atk, drust.max_health)
        gain(g, a, PIRATE)
        self.assertEqual((drust.atk, drust.max_health),
                         (base[0] + 4, base[1] + 4))
        gain(g, a, PIRATE, golden=True)
        self.assertEqual((drust.atk, drust.max_health),
                         (base[0] + 4 + 12, base[1] + 4 + 12))

    def test_non_pirate_no_trigger(self):
        g, a, drust, ally = self._setup()
        base = (drust.atk, drust.max_health)
        gain(g, a, NON_PIRATE)
        self.assertEqual((drust.atk, drust.max_health), base)

    def test_enemy_gain_no_trigger(self):
        g, a, drust, ally = self._setup()
        b = g.heroes[1]
        base = (drust.atk, drust.max_health)
        gain(g, b, PIRATE)
        self.assertEqual((drust.atk, drust.max_health), base)

    def test_real_buy_path_triggers(self):
        g, a, drust, ally = self._setup()
        base = (drust.atk, drust.max_health)
        pirate = g.create_minion(PIRATE, controller=a)
        a.tavern.append(pirate)
        a.set(GameTag.GOLD, 10)
        self.assertTrue(g.buy_from_tavern(a, pirate))
        self.assertEqual((drust.atk, drust.max_health),
                         (base[0] + 2, base[1] + 2))

    def test_full_hand_deferred_no_trigger(self):
        g, a, drust, ally = self._setup()
        base = (drust.atk, drust.max_health)
        for _ in range(10):
            filler = g.create_spell("BG20_GEM", controller=a)
            filler.zone = Zone.HAND
            a.hand.append(filler)
        pirate = g.create_minion(PIRATE, controller=a)
        self.assertFalse(g.pending_hand_add(a, pirate))
        self.assertEqual((drust.atk, drust.max_health), base)


class TestMaelstromEmergent(unittest.TestCase):
    def _setup(self, golden=False):
        g = make_game(seed=2402)
        a = g.heroes[0]
        m = put(g, a, MAELSTROM, golden=golden)
        target = put(g, a, NON_PIRATE)
        return g, a, m, target

    def test_normal_extra_cast_in_combat(self):
        g, a, m, target = self._setup()
        MaelstromEmergentScript.start_of_combat(m, g, {})
        g.in_combat = True
        self.assertEqual(g.combat_spell_extra_casts(a), 1)
        base = (target.atk, target.max_health)
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=target))
        self.assertEqual((target.atk, target.max_health),
                         (base[0] + 2, base[1] + 2))

    def test_golden_extra_casts_two(self):
        g, a, m, target = self._setup(golden=True)
        MaelstromEmergentScript.start_of_combat(m, g, {})
        g.in_combat = True
        self.assertEqual(g.combat_spell_extra_casts(a), 2)
        base = (target.atk, target.max_health)
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=target))
        self.assertEqual((target.atk, target.max_health),
                         (base[0] + 3, base[1] + 3))

    def test_recruit_phase_not_applied(self):
        g, a, m, target = self._setup()
        MaelstromEmergentScript.start_of_combat(m, g, {})
        # 不在战斗内: 即使 attr 已设也不消费
        target_base = (target.atk, target.max_health)
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=target))
        self.assertEqual((target.atk, target.max_health),
                         (target_base[0] + 1, target_base[1] + 1))

    def test_death_clears_channel(self):
        g, a, m, target = self._setup()
        MaelstromEmergentScript.start_of_combat(m, g, {})
        g.in_combat = True
        self.assertEqual(g.combat_spell_extra_casts(a), 1)
        g.run_actions(Hit(m, m.health))
        self.assertTrue(m.dead)
        self.assertEqual(g.combat_spell_extra_casts(a), 0)

    def test_sell_clears_channel(self):
        g, a, m, target = self._setup()
        MaelstromEmergentScript.start_of_combat(m, g, {})
        self.assertEqual(g.combat_spell_extra_casts(a), 1)
        self.assertTrue(g.sell_minion(a, m))
        self.assertEqual(g.combat_spell_extra_casts(a), 0)

    def test_no_maelstrom_default(self):
        g = make_game(seed=2403)
        a = g.heroes[0]
        target = put(g, a, NON_PIRATE)
        self.assertEqual(g.combat_spell_extra_casts(a), 0)
        g.in_combat = True
        base = (target.atk, target.max_health)
        self.assertTrue(g.cast_spell_effect(a, "BG20_GEM", target=target))
        self.assertEqual((target.atk, target.max_health),
                         (base[0] + 1, base[1] + 1))


if __name__ == "__main__":
    unittest.main()
