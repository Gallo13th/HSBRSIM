"""差分驱动批 3 测试：Incubation Researcher + Deep Blue Crooner。

真实引擎路径：
  - Avenge: 真实战斗内友方死亡（`game.in_combat` + `_active_combat` +
    `_process_single_death`）；
  - Spellcraft: 真实 `play_minion`（on_summon 自举 + 立即给法术）、
    `play_spell`（on_play）、`_expire_at_next_turn`（TURN_START）。

BG31_171 已由审计第二轮 F-18 注册（见 `test_batch_card_audit3.py`）；
BG34_922/BG32_234 已由 batch_37x_gapfill 收口注册。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import TURN_START
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_diff_driven3 as B
from hsrl2.scripts.batches.batch_rally2 import CHROMADRAKE_IDS
from hsrl2.tags import GameTag, Zone

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


def make_game(seed: int = 301, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def dummy(hero: Hero, name: str = "Dummy", atk: int = 1,
          health: int = 5) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    hero.board.append(m)
    game._update_positions(hero)
    return m


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    game.in_combat = True
    game._active_combat = (a, b)


def leave_combat(game: Game) -> None:
    game.in_combat = False
    game._active_combat = None


def kill(game: Game, m: Minion) -> None:
    m.health = 0
    game._process_single_death(m)


def fire_turn_start(game: Game, hero: Hero) -> None:
    game.events.fire(game, TURN_START, turn=game.turn, hero=hero)


def hand_spell(hero: Hero, card_id: str):
    for c in hero.hand:
        if getattr(c, "card_id", None) == card_id:
            return c
    return None


# ══════════════════════════════════════════════════════════════════════
# BG34_632 Incubation Researcher
# ══════════════════════════════════════════════════════════════════════


class TestIncubationResearcher(unittest.TestCase):
    def _prepare(self, game, golden=False):
        a, b = game.heroes
        researcher = put(game, B.INCUBATION_RESEARCHER, a, golden=golden)
        enter_combat(game, a, b)
        return a, b, researcher

    def test_avenge_three_deaths_gets_random_chromadrake(self):
        game = make_game(seed=310)
        a, b, researcher = self._prepare(game)
        try:
            for i in range(3):
                kill(game, dummy(a, f"V{i}"))
        finally:
            leave_combat(game)
        self.assertEqual(len(a.hand), 1)
        got = a.hand[0]
        self.assertIn(got.card_id, CHROMADRAKE_IDS)
        self.assertFalse(get_db().get(got.card_id).is_pool_minion,
                         "Chromadrake 是非池 token")

    def test_two_deaths_no_trigger(self):
        game = make_game(seed=311)
        a, b, researcher = self._prepare(game)
        try:
            for i in range(2):
                kill(game, dummy(a, f"V{i}"))
        finally:
            leave_combat(game)
        self.assertEqual(a.hand, [])

    def test_golden_gets_two_chromadrakes(self):
        game = make_game(seed=312)
        a, b, researcher = self._prepare(game, golden=True)
        try:
            for i in range(3):
                kill(game, dummy(a, f"V{i}"))
        finally:
            leave_combat(game)
        self.assertEqual(len(a.hand), 2)
        for got in a.hand:
            self.assertIn(got.card_id, CHROMADRAKE_IDS)

    def test_avenge_threshold_carddef(self):
        db = get_db()
        self.assertEqual(db.get(B.INCUBATION_RESEARCHER).avenge_target, 3)
        self.assertEqual(db.get(B.INCUBATION_RESEARCHER_G).avenge_target, 3)


# ══════════════════════════════════════════════════════════════════════
# BG26_502 Deep Blue Crooner
# ══════════════════════════════════════════════════════════════════════


class TestDeepBlueCrooner(unittest.TestCase):
    def _play_crooner(self, game: Game, hero: Hero,
                      golden: bool = False) -> Minion:
        m = game.create_minion(B.DEEP_BLUE_CROONER, controller=hero,
                               golden=golden)
        hero.hand.append(m)
        self.assertTrue(game.play_minion(hero, m))
        return m

    def test_play_grants_deep_blues(self):
        game = make_game(seed=320)
        a = game.heroes[0]
        self._play_crooner(game, a)
        self.assertIsNotNone(hand_spell(a, B.DEEP_BLUES))
        self.assertTrue(any(m.has(GameTag.SPELLCRAFT) for m in a.board))

    def test_golden_play_grants_golden_spell(self):
        game = make_game(seed=321)
        a = game.heroes[0]
        self._play_crooner(game, a, golden=True)
        self.assertIsNotNone(hand_spell(a, B.DEEP_BLUES_G))

    def test_cast_buffs_and_improves_future(self):
        game = make_game(seed=322)
        a = game.heroes[0]
        crooner = self._play_crooner(game, a)
        target = dummy(a, "Target", 1, 10)
        spell = hand_spell(a, B.DEEP_BLUES)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.max_health), (3, 12))
        # 改善未来：来源通道 NUM_1/2 由 2/2 → 4/4
        self.assertEqual(crooner.get_script_data(1), 4)
        self.assertEqual(crooner.get_script_data(2), 4)
        # 下一张 Deep Blues 用新值
        from hsrl2.spellcraft import grant_spellcraft_spell
        grant_spellcraft_spell(crooner, game)
        spell2 = hand_spell(a, B.DEEP_BLUES)
        self.assertIsNotNone(spell2)
        self.assertTrue(game.play_spell(a, spell2, target=target))
        self.assertEqual((target.atk, target.max_health), (7, 16))

    def test_golden_starts_four_and_improves_by_four(self):
        game = make_game(seed=323)
        a = game.heroes[0]
        crooner = self._play_crooner(game, a, golden=True)
        target = dummy(a, "Target", 1, 10)
        spell = hand_spell(a, B.DEEP_BLUES_G)
        game.play_spell(a, spell, target=target)
        self.assertEqual((target.atk, target.max_health), (5, 14))
        self.assertEqual(crooner.get_script_data(1), 8)
        self.assertEqual(crooner.get_script_data(2), 8)

    def test_injected_official_values_are_consumed(self):
        """官方 ScriptDataNum 注入值（28/28）→ 法术即用 28/28 并继续改善。"""
        game = make_game(seed=324)
        a = game.heroes[0]
        m = game.create_minion(B.DEEP_BLUE_CROONER, controller=a)
        m.set_script_data(1, 28)     # 模拟 harness 官方注入
        m.set_script_data(2, 28)
        a.hand.append(m)
        self.assertTrue(game.play_minion(a, m))
        target = dummy(a, "Target", 1, 10)
        spell = hand_spell(a, B.DEEP_BLUES)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.max_health), (29, 38))
        self.assertEqual(m.get_script_data(1), 30)
        self.assertEqual(m.get_script_data(2), 30)

    def test_buff_expires_at_next_turn(self):
        game = make_game(seed=325)
        a = game.heroes[0]
        self._play_crooner(game, a)
        target = dummy(a, "Target", 1, 10)
        spell = hand_spell(a, B.DEEP_BLUES)
        game.play_spell(a, spell, target=target)
        self.assertEqual((target.atk, target.max_health), (3, 12))
        fire_turn_start(game, a)
        self.assertEqual((target.atk, target.max_health), (1, 10))

    def test_origin_left_board_falls_back_to_card_values(self):
        game = make_game(seed=326)
        a = game.heroes[0]
        crooner = self._play_crooner(game, a)
        spell = hand_spell(a, B.DEEP_BLUES)
        # 来源离场（模拟出售/死亡），法术仍在手
        game.sell_minion(a, crooner)
        target = dummy(a, "Target", 1, 10)
        game.play_spell(a, spell, target=target)
        self.assertEqual((target.atk, target.max_health), (3, 12))


# ══════════════════════════════════════════════════════════════════════
# 注册表 / DEFERRED
# ══════════════════════════════════════════════════════════════════════


class TestRegistration(unittest.TestCase):
    def test_all_batch_ids_registered(self):
        for cid in (B.INCUBATION_RESEARCHER, B.INCUBATION_RESEARCHER_G,
                    B.DEEP_BLUE_CROONER, B.DEEP_BLUE_CROONER_G,
                    B.DEEP_BLUES, B.DEEP_BLUES_G):
            self.assertIsNotNone(REGISTRY.get(cid), cid)

    def test_cards_registered_after_audit(self):
        # BG31_171 Moonsteel 已由审计第二轮 F-18 注册（配对证据）；
        # BG34_922 Maelstrom / BG32_234 Dastardly Drust 由 batch_37x_gapfill
        # 收口注册。
        for cid in ("BG31_171", "BG31_171_G",
                    "BG34_922", "BG34_922_G",
                    "BG32_234", "BG32_234_G"):
            self.assertIsNotNone(REGISTRY.get(cid), cid)


if __name__ == "__main__":
    unittest.main()
