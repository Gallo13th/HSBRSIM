"""官方伤害上限外部注入测试（2026-10-18，官方一致性 P1）。

背景：官方伤害上限来自服务端 GameEntity tag
``BACON_COMBAT_DAMAGE_CAP``(2089) / ``BACON_COMBAT_DAMAGE_CAP_ENABLED``
(3403)；引擎 turn 表（``C.damage_cap``）只是近似。本批新增：

* ``Game(..., damage_cap_override=N)`` 构造注入；
* ``Game.set_damage_cap(value, enabled=True)`` / ``clear_damage_cap()``；
* ``run_combat`` 里注入优先，**默认 None = 原 turn 表行为完全不变**。

覆盖：默认回归不变 / 注入值生效 / enabled=False 无上限 / 清除回默认 /
构造参数生效 / 原始伤害不计上限。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.tags import GameTag

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(*, heroes: int = 8, seed: int = 7,
              damage_cap_override=None) -> Game:
    roster = [Hero(f"TEST_HERO_{i}", f"H{i}") for i in range(heroes)]
    return Game(roster, get_db(), seed=seed,
                damage_cap_override=damage_cap_override)


def put_winner(game: Game, hero: Hero):
    """给 hero 一只高 tier 大随从（原始伤害 = 酒馆等级 + tier ≥ 5）。"""
    d = next(d for d in get_db().pool_minions() if d.tech_level >= 5)
    m = game.create_minion(d.id, controller=hero)
    m.set(GameTag.BASE_ATK, 100)
    m.set(GameTag.ATK, 100)
    m.set(GameTag.BASE_HEALTH, 100)
    m.set(GameTag.HEALTH, 100)
    game.summon(hero, m)
    return m


def fight(game: Game):
    """hero0（有大随从）vs hero1（空场）：固定胜方，返回 CombatResult。"""
    a, b = game.heroes[0], game.heroes[1]
    put_winner(game, a)
    return game.run_combat(a, b)


class TestDamageCapDefaultUnchanged(unittest.TestCase):
    def test_default_turn_table_unchanged(self):
        """默认（未注入）使用原 turn 表；本批不改 constants。"""
        self.assertEqual(C.damage_cap(1, 8), 5)
        self.assertEqual(C.damage_cap(5, 8), 10)
        self.assertEqual(C.damage_cap(8, 8), 15)
        self.assertIsNone(C.damage_cap(8, 3))       # ≤4 人无上限
        # 构造默认值
        game = make_game()
        self.assertIsNone(game.damage_cap_override)
        self.assertFalse(game.damage_cap_disabled)

    def test_default_combat_still_capped_by_turn_table(self):
        game = make_game()
        game.turn = 1                               # 8 人存活 → cap 5
        result = fight(game)
        self.assertEqual(result.damage_dealt, 1 + 5)   # 酒馆等级1 + tier5
        self.assertEqual(result.capped_damage, 5)

    def test_default_is_repeatable(self):
        r1 = fight(make_game(seed=9))
        r2 = fight(make_game(seed=9))
        self.assertEqual((r1.damage_dealt, r1.capped_damage),
                         (r2.damage_dealt, r2.capped_damage))


class TestDamageCapInjection(unittest.TestCase):
    def test_injected_cap_applied(self):
        game = make_game()
        game.turn = 1
        game.set_damage_cap(3)
        result = fight(game)
        self.assertEqual(result.damage_dealt, 6)    # 原始伤害不变
        self.assertEqual(result.capped_damage, 3)

    def test_injected_cap_larger_than_damage(self):
        game = make_game()
        game.turn = 1
        game.set_damage_cap(99)
        result = fight(game)
        self.assertEqual(result.capped_damage, result.damage_dealt)

    def test_enabled_false_means_uncapped(self):
        """官方 _ENABLED=0：无上限。"""
        game = make_game()
        game.turn = 1
        game.set_damage_cap(None, enabled=False)
        self.assertTrue(game.damage_cap_disabled)
        result = fight(game)
        self.assertEqual(result.capped_damage, result.damage_dealt)

    def test_clear_restores_default(self):
        game = make_game()
        game.turn = 1
        game.set_damage_cap(2)
        game.clear_damage_cap()
        result = fight(game)
        self.assertEqual(result.capped_damage, 5)   # 回 turn 表

    def test_set_none_clears_override(self):
        game = make_game()
        game.turn = 1
        game.set_damage_cap(2)
        game.set_damage_cap(None)
        result = fight(game)
        self.assertEqual(result.capped_damage, 5)

    def test_constructor_override(self):
        game = make_game(damage_cap_override=2)
        game.turn = 1
        self.assertEqual(game.damage_cap_override, 2)
        result = fight(game)
        self.assertEqual(result.capped_damage, 2)

    def test_injection_does_not_change_turn_table(self):
        before = (C.damage_cap(1, 8), C.damage_cap(5, 8), C.damage_cap(8, 8))
        game = make_game()
        game.set_damage_cap(3)
        after = (C.damage_cap(1, 8), C.damage_cap(5, 8), C.damage_cap(8, 8))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
