"""差分驱动批 4 测试：8 张卡 + Chromadrake token 全家。

真实引擎路径：
  - EoT: 真实 TURN_END 广播（end_recruit_phase 同款 fire 点）；
  - 战吼: 真实 play_minion（battlecry 钩子）；
  - 亡语: 真实 destroy_minion 死亡链；
  - Rally / 受伤: 真实 CombatScheduler._execute_attack（伤害事件）；
  - 出售: 真实 sell_minion；
  - stats_gained: 真实 Buff Action（Entity.add_buff 生产点）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import BLOOD_GEM_VARIANTS, PlayBloodGems, _gem_values
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.events import TURN_END
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_diff_driven4 as B
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 401, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def dummy(hero: Hero, name: str = "Dummy", atk: int = 1,
          health: int = 5, race: Race | None = None) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, race)
    hero.board.append(m)
    game._update_positions(hero)
    return m


def play_from_hand(game: Game, hero: Hero, card_id: str,
                   golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.hand.append(m)
    assert game.play_minion(hero, m)
    return m


def fire_turn_end(game: Game) -> None:
    game.events.fire(game, TURN_END, turn=game.turn)


def attack(game: Game, attacker: Minion, defender: Minion) -> None:
    a = attacker.controller
    b = defender.controller
    game.in_combat = True
    game._active_combat = (a, b)
    try:
        CombatScheduler(game, a, b)._execute_attack(attacker, defender)
    finally:
        game.in_combat = False
        game._active_combat = None


# ══════════════════════════════════════════════════════════════════════
# BG33_820 Lost City Looter
# ══════════════════════════════════════════════════════════════════════


class TestLostCityLooter(unittest.TestCase):
    def _bounty_ids(self, game):
        return [d.id for d in game.db.pool_spells()
                if d.name.endswith("Bounty") and "pirate" in d.subsets]

    def test_eot_gets_random_bounty(self):
        game = make_game(seed=410)
        a = game.heroes[0]
        put(game, B.LOST_CITY_LOOTER, a)
        before = {sid: game.spell_pool.available(sid)
                  for sid in self._bounty_ids(game)}
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, self._bounty_ids(game))
        after = {sid: game.spell_pool.available(sid) for sid in before}
        self.assertEqual(sum(before.values()) - sum(after.values()), 1)

    def test_golden_gets_one(self):
        game = make_game(seed=411)
        a = game.heroes[0]
        put(game, B.LOST_CITY_LOOTER, a, golden=True)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 1)

    def test_no_bounty_no_crash(self):
        """无 Bounty 卡集（非海盗局）→ 落空不崩。"""
        from unittest import mock
        game = make_game(seed=412)
        a = game.heroes[0]
        put(game, B.LOST_CITY_LOOTER, a)
        with mock.patch.object(B, "_bounty_ids", lambda g: []):
            fire_turn_end(game)
        self.assertEqual(len(a.hand), 0)


# ══════════════════════════════════════════════════════════════════════
# BG24_009 Picky Eater
# ══════════════════════════════════════════════════════════════════════


class TestPickyEater(unittest.TestCase):
    def test_battlecry_consumes_random_tavern_minion(self):
        game = make_game(seed=420)
        a = game.heroes[0]
        victim = game.create_minion("BG20_100", controller=a)
        victim.zone = Zone.TAVERN
        a.tavern.append(victim)
        base_atk, base_hp = victim.atk, victim.max_health
        picky = play_from_hand(game, a, B.PICKY_EATER)
        self.assertNotIn(victim, a.tavern)
        self.assertEqual((picky.atk, picky.max_health),
                         (1 + base_atk, 1 + base_hp))

    def test_empty_tavern_no_crash(self):
        game = make_game(seed=421)
        a = game.heroes[0]
        picky = play_from_hand(game, a, B.PICKY_EATER)
        self.assertTrue(picky.zone == Zone.PLAY)


# ══════════════════════════════════════════════════════════════════════
# BG32_430 Glowgullet Warlord
# ══════════════════════════════════════════════════════════════════════


class TestGlowgulletWarlord(unittest.TestCase):
    def test_deathrattle_summons_two_tokens_with_gem(self):
        game = make_game(seed=430)
        a = game.heroes[0]
        ghoul = put(game, B.GLOWGULLET_WARLORD, a)
        game.destroy_minion(ghoul)
        tokens = [m for m in a.board if m.card_id == B.GLOWGULLET_SOLDIER]
        self.assertEqual(len(tokens), 2)
        gem_atk, gem_hp = _gem_values(game, BLOOD_GEM_VARIANTS[None], a)
        for token in tokens:
            self.assertTrue(token.has(GameTag.TAUNT))
            self.assertEqual((token.atk, token.max_health),
                             (1 + gem_atk, 1 + gem_hp))

    def test_golden_summons_two_two_with_two_gems(self):
        game = make_game(seed=431)
        a = game.heroes[0]
        ghoul = put(game, B.GLOWGULLET_WARLORD, a, golden=True)
        game.destroy_minion(ghoul)
        tokens = [m for m in a.board
                  if m.card_id == B.GLOWGULLET_SOLDIER_G]
        self.assertEqual(len(tokens), 2)
        gem_atk, gem_hp = _gem_values(game, BLOOD_GEM_VARIANTS[None], a)
        for token in tokens:
            self.assertEqual((token.atk, token.max_health),
                             (2 + 2 * gem_atk, 2 + 2 * gem_hp))


# ══════════════════════════════════════════════════════════════════════
# BG26_160 Prickly Piper
# ══════════════════════════════════════════════════════════════════════


class TestPricklyPiper(unittest.TestCase):
    def test_deathrattle_blood_gem_extra_attack(self):
        game = make_game(seed=440)
        a = game.heroes[0]
        piper = put(game, B.PRICKLY_PIPER, a)
        game.destroy_minion(piper)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 1)
        target = dummy(a, "Target", 1, 20)
        game.run_actions(PlayBloodGems(target, 1))
        gem_atk, gem_hp = _gem_values(game, BLOOD_GEM_VARIANTS[None], a)
        self.assertEqual((target.atk, target.max_health),
                         (1 + gem_atk, 20 + gem_hp))

    def test_golden_two_attack(self):
        game = make_game(seed=441)
        a = game.heroes[0]
        piper = put(game, B.PRICKLY_PIPER, a, golden=True)
        game.destroy_minion(piper)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 2)


# ══════════════════════════════════════════════════════════════════════
# BG33_920 Wrathscale Rogue
# ══════════════════════════════════════════════════════════════════════


class TestWrathscaleRogue(unittest.TestCase):
    def _prepare(self, game):
        a = game.heroes[0]
        rogue = put(game, B.WRATHSCALE_ROGUE, a)
        naga = dummy(a, "Naga", 2, 20, race=Race.NAGA)
        return a, rogue, naga

    def test_another_naga_gaining_health_gets_attack(self):
        game = make_game(seed=450)
        a, rogue, naga = self._prepare(game)
        game.run_actions(Buff(naga, health=3))
        self.assertEqual(naga.atk, 5)

    def test_non_naga_not_triggered(self):
        game = make_game(seed=451)
        a, rogue, naga = self._prepare(game)
        beast = dummy(a, "Beast", 2, 20, race=Race.BEAST)
        game.run_actions(Buff(beast, health=3))
        self.assertEqual(beast.atk, 2)

    def test_self_gaining_health_not_triggered(self):
        game = make_game(seed=452)
        a, rogue, naga = self._prepare(game)
        game.run_actions(Buff(rogue, health=3))
        self.assertEqual(rogue.atk, 3)

    def test_opponent_naga_not_triggered(self):
        game = make_game(seed=453)
        a, rogue, naga = self._prepare(game)
        enemy_naga = dummy(game.heroes[1], "ENaga", 2, 20, race=Race.NAGA)
        game.run_actions(Buff(enemy_naga, health=3))
        self.assertEqual(enemy_naga.atk, 2)


# ══════════════════════════════════════════════════════════════════════
# BG34_312 Hardy Orca
# ══════════════════════════════════════════════════════════════════════


class TestHardyOrca(unittest.TestCase):
    def test_damage_buffs_other_minions(self):
        game = make_game(seed=460)
        a, b = game.heroes
        orca = put(game, B.HARDY_ORCA, a)
        other = dummy(a, "Other", 1, 10)
        attacker = dummy(b, "Atk", 3, 10)
        attack(game, attacker, orca)
        self.assertEqual((other.atk, other.max_health), (2, 11))
        # 自身不在 "other minions" 内 → 不加属性
        self.assertEqual((orca.atk, orca.max_health), (1, 6))

    def test_golden_bonus_two_two(self):
        game = make_game(seed=461)
        a, b = game.heroes
        orca = put(game, B.HARDY_ORCA, a, golden=True)
        other = dummy(a, "Other", 1, 10)
        attacker = dummy(b, "Atk", 3, 10)
        attack(game, attacker, orca)
        self.assertEqual((other.atk, other.max_health), (3, 12))

    def test_no_damage_no_buff(self):
        game = make_game(seed=462)
        a = game.heroes[0]
        put(game, B.HARDY_ORCA, a)
        other = dummy(a, "Other", 1, 10)
        fire_turn_end(game)
        self.assertEqual((other.atk, other.max_health), (1, 10))


# ══════════════════════════════════════════════════════════════════════
# BGS_049 Freedealing Gambler
# ══════════════════════════════════════════════════════════════════════


class TestFreedealingGambler(unittest.TestCase):
    def test_sells_for_three(self):
        game = make_game(seed=470)
        a = game.heroes[0]
        gambler = put(game, B.FREEDEALING_GAMBLER, a)
        gold_before = a.gold
        self.assertTrue(game.sell_minion(a, gambler))
        self.assertEqual(a.gold - gold_before, 3)

    def test_normal_minion_sells_for_one(self):
        game = make_game(seed=471)
        a = game.heroes[0]
        m = put(game, "BG20_100", a)
        gold_before = a.gold
        game.sell_minion(a, m)
        self.assertEqual(a.gold - gold_before, 1)


# ══════════════════════════════════════════════════════════════════════
# BG31_175 Holo Rover
# ══════════════════════════════════════════════════════════════════════


def _magnetic_mech_ids(game):
    return [d.id for d in game.db.pool_minions()
            if "magnetic" in d.keywords
            and (Race.MECH in d.races or Race.ALL in d.races)]


class TestHoloRover(unittest.TestCase):
    def _attack(self, game):
        a, b = game.heroes
        rover = put(game, B.HOLO_ROVER, a)
        target = dummy(b, "T", 0, 50)
        before = sum(game.minion_pool.available(cid)
                     for cid in _magnetic_mech_ids(game))
        attack(game, rover, target)
        after = sum(game.minion_pool.available(cid)
                    for cid in _magnetic_mech_ids(game))
        return a, before, after

    def test_rally_gets_random_magnetic_mech(self):
        game = make_game(seed=480)
        a, before, after = self._attack(game)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, _magnetic_mech_ids(game))
        self.assertEqual(before - after, 1)

    def test_golden_gets_two(self):
        game = make_game(seed=481)
        a, b = game.heroes
        rover = put(game, B.HOLO_ROVER, a, golden=True)
        target = dummy(b, "T", 0, 50)
        attack(game, rover, target)
        self.assertEqual(len(a.hand), 2)
        for card in a.hand:
            self.assertIn(card.card_id, _magnetic_mech_ids(game))


# ══════════════════════════════════════════════════════════════════════
# Chromadrake token 全家
# ══════════════════════════════════════════════════════════════════════


class TestChromadrakes(unittest.TestCase):
    def test_tokens_registered(self):
        for cid in B.CHROMADRAKE_IDS + B.CHROMADRAKE_GOLDEN_IDS:
            self.assertIsNotNone(REGISTRY.get(cid), cid)

    def test_blue_gets_two_cost_tavern_spell(self):
        game = make_game(seed=490)
        a = game.heroes[0]
        play_from_hand(game, a, "BG34_634t")
        self.assertEqual(len(a.hand), 1)
        spell = a.hand[0]
        d = game.db.get(spell.card_id)
        self.assertEqual(getattr(d, "cost", None), 2)

    def test_blue_golden_gets_two_spells(self):
        game = make_game(seed=491)
        a = game.heroes[0]
        play_from_hand(game, a, "BG34_634t", golden=True)
        self.assertEqual(len(a.hand), 2)
        for spell in a.hand:
            self.assertEqual(getattr(game.db.get(spell.card_id), "cost", None),
                             2)

    def test_black_and_red_tavern_spell_bonus(self):
        game = make_game(seed=492)
        a = game.heroes[0]
        play_from_hand(game, a, "BG34_635t")
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), 1)
        play_from_hand(game, a, "BG34_638t")
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 1)

    def test_golden_black_doubles_via_engine_battlecry(self):
        game = make_game(seed=493)
        a = game.heroes[0]
        play_from_hand(game, a, "BG34_635t", golden=True)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), 2)

    def test_green_buffs_other_dragons(self):
        game = make_game(seed=494)
        a = game.heroes[0]
        dragon = dummy(a, "Dragon", 1, 10, race=Race.DRAGON)
        play_from_hand(game, a, "BG34_636t")
        self.assertEqual((dragon.atk, dragon.max_health), (2, 13))

    def test_bronze_golden_buffs_six_two(self):
        game = make_game(seed=495)
        a = game.heroes[0]
        dragon = dummy(a, "Dragon", 1, 10, race=Race.DRAGON)
        play_from_hand(game, a, "BG34_637t", golden=True)
        self.assertEqual((dragon.atk, dragon.max_health), (7, 12))


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


class TestRegistration(unittest.TestCase):
    def test_main_cards_registered(self):
        for cid in (B.LOST_CITY_LOOTER, B.LOST_CITY_LOOTER_G,
                    B.PICKY_EATER, B.PICKY_EATER_G,
                    B.GLOWGULLET_WARLORD, B.GLOWGULLET_WARLORD_G,
                    B.PRICKLY_PIPER, B.PRICKLY_PIPER_G,
                    B.WRATHSCALE_ROGUE, B.WRATHSCALE_ROGUE_G,
                    B.HARDY_ORCA, B.HARDY_ORCA_G,
                    B.FREEDEALING_GAMBLER,
                    B.HOLO_ROVER, B.HOLO_ROVER_G):
            self.assertIsNotNone(REGISTRY.get(cid), cid)


if __name__ == "__main__":
    unittest.main()
