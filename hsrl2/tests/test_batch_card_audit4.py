"""卡牌审计第二轮补充测试：FireForged F-19 / Wrath / Devout base。

F-19 公式依据（HDT trace 20/20；raw Power.log 0 样本）：
  count = 本局酒馆法术数；
  BG32_822 base: atk +2+2c、health +2+c；golden: atk +4+2c、health +4+c。
本文件同时锁定 Wrath Weaver（raw +2/+2）与 Devout Hellcaller base
（raw +2/+2）的现有正确实现，防回归。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 31900) -> Game:
    return Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
                get_db(), seed=seed)


def put(g: Game, card_id: str, hero, golden: bool = False):
    m = g.create_minion(card_id, controller=hero, golden=golden)
    assert m is not None and g.summon(hero, m)
    return m


def spell(g: Game, hero, card_id: str = "BG28_805"):
    s = g.create_spell(card_id, controller=hero)
    hero.add_to_hand(s)
    assert g.play_spell(hero, s)
    return s


class TestFireForgedFormula(unittest.TestCase):
    def test_base_one_cast(self):
        g = make_game(seed=31900)
        a, b = g.heroes
        d = get_db().get("BG32_822")
        evoker = put(g, "BG32_822", a)
        spell(g, a)
        CombatScheduler(g, a, b)._start_of_combat_phase()
        self.assertEqual(evoker.atk, d.atk + d.num(0) + 2)
        self.assertEqual(evoker.max_health, d.health + d.num(1) + 1)

    def test_golden_one_cast(self):
        g = make_game(seed=31901)
        a, b = g.heroes
        dg = get_db().get("BG32_822_G")
        evoker = put(g, "BG32_822_G", a, golden=True)
        spell(g, a)
        CombatScheduler(g, a, b)._start_of_combat_phase()
        self.assertEqual(evoker.atk, dg.atk + dg.num(0) + 2)
        self.assertEqual(evoker.max_health, dg.health + dg.num(1) + 1)


class TestWrathWeaverRaw(unittest.TestCase):
    def test_play_demon_is_plus_two_two(self):
        g = make_game(seed=31902)
        a = g.heroes[0]
        weaver = put(g, "BGS_004", a)
        hp = a.health
        demon = Minion("TEST_DEMON", "Demon", atk=1, health=1)
        demon.game = g
        demon.controller = a
        demon.zone = Zone.HAND
        demon.set(GameTag.RACE, Race.DEMON)
        a.hand.append(demon)
        a.gold = 0
        self.assertTrue(g.play_minion(a, demon))
        self.assertEqual(weaver.atk, 1 + 2)
        self.assertEqual(weaver.max_health, 3 + 2)
        self.assertEqual(a.health, hp - 1)


class TestDevoutBase(unittest.TestCase):
    def test_friendly_demon_damage_gives_two_two(self):
        g = make_game(seed=31903)
        a = g.heroes[0]
        devout = put(g, "BG33_155", a)
        demon = Minion("TEST_DEMON", "Demon", atk=2, health=5)
        demon.game = g
        demon.controller = a
        demon.zone = Zone.PLAY
        demon.set(GameTag.RACE, Race.DEMON)
        a.board.append(demon)
        g._update_positions(a)
        # 真实 Hurt 路径：友方 Demon 造成伤害
        g.events.fire(g, "damage", minion=demon, amount=2,
                      source=demon)
        self.assertEqual(devout.atk, 4 + 2)
        self.assertEqual(devout.max_health, 4 + 2)


if __name__ == "__main__":
    unittest.main()
