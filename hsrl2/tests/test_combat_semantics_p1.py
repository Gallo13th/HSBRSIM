"""P1 战斗语义修复的失败测试（官方关键词文本 + BobsBuddy 双源证据）。

证据（`reversed/rea/combat_rule_evidence.md` §2.2/§2.3）：

* 剧毒/烈毒：官方文本 "Destroy any minion damaged by this minion"
  / "…destroy the first minion damaged by this minion"（GLOBAL.txt:1021/1231）
  ——**不要求来源存活**；BobsBuddy 在扣血阶段直接 `baseHealth=-10000`
  （`BB:7533-7548`）。引擎旧实现要求 `not attacker.dead` 且在死亡结算
  **之后**判定 → 同时伤害下"互杀同归于尽"的一方没有被毒杀。
* 顺劈：官方卡面 "Also damages the minions next to whomever it attacks."
  （同时伤害），BobsBuddy 顺劈与主目标/反击同一伤害组（`BB:6552-6581`）；
  引擎旧实现 `if attacker.cleave and not attacker.dead` 会在攻击者被
  反击打死时取消相邻伤害。

本文件是**修复前应失败**的回归测试（修复后全绿）。死亡波次/复生时序
保持引擎原有确定性顺序（官方无逐事件证据，不照抄 BobsBuddy）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
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


def make_game(seed: int = 7):
    db = get_db()
    g = Game([Hero("TEST_P", "P"), Hero("TEST_O", "O")], db, seed=seed)
    return g, g.heroes[0], g.heroes[1]


def put(game: Game, hero: Hero, card_id: str = "BG33_140",
        atk: int | None = None, health: int | None = None,
        tags: tuple = ()):
    """召唤一只指定数值/关键词的随从（BG33_140 = River Skipper 1/1 白板）。"""
    m = game.create_minion(card_id, controller=hero)
    if atk is not None:
        m.set(GameTag.BASE_ATK, atk)
        m.set(GameTag.ATK, atk)
    if health is not None:
        m.set(GameTag.BASE_HEALTH, health)
        m.set(GameTag.HEALTH, health)
    for tag in tags:
        m.set(tag, True)
    game.summon(hero, m)
    return m


class _CombatContext:
    """直连 `_execute_attack` 的最小战斗上下文（测试用）。"""

    def __init__(self, game, a, b):
        self.game = game

    def __enter__(self):
        self.game.in_combat = True
        self.game._active_combat = (self.game.heroes[0], self.game.heroes[1])
        return self

    def __exit__(self, *exc):
        self.game.in_combat = False
        self.game._active_combat = None
        return False


class TestVenomousSemantics(unittest.TestCase):
    def test_venomous_kills_when_attacker_dies_simultaneously(self):
        """1/1 烈毒 vs 5/5：互杀同归于尽，毒杀仍要生效（同一次死亡结算）。"""
        game, a, b = make_game()
        attacker = put(game, a, atk=1, health=1, tags=(GameTag.VENOMOUS,))
        defender = put(game, b, atk=5, health=5)
        calls = []
        original = game.check_deaths

        def spy(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        game.check_deaths = spy
        with _CombatContext(game, a, b):
            CombatScheduler(game, a, b)._execute_attack(attacker, defender)
        # 双方死亡（攻击者反击致死 + 防御者被毒杀）
        self.assertTrue(attacker.dead, "攻击者应被反击打死")
        self.assertTrue(defender.dead, "1/1 烈毒仍应毒杀 5/5（不要求来源存活）")
        # 同一次死亡结算（旧实现：先 check_deaths 结攻击者/再毒杀/再 check）
        self.assertEqual(len(calls), 1, f"应只有一次死亡结算，实际 {len(calls)}")

    def test_venomous_consumed_once_even_if_attacker_dies(self):
        game, a, b = make_game()
        attacker = put(game, a, atk=1, health=1, tags=(GameTag.VENOMOUS,))
        defender = put(game, b, atk=5, health=5)
        with _CombatContext(game, a, b):
            CombatScheduler(game, a, b)._execute_attack(attacker, defender)
        self.assertTrue(attacker.dead)
        self.assertTrue(defender.dead)
        self.assertTrue(attacker.has(GameTag.VENOMOUS_CONSUMED))

    def test_venomous_no_trigger_when_damage_absorbed_by_divine_shield(self):
        """圣盾抵消伤害 → 没有"受到其伤害" → 不触发剧毒/烈毒。"""
        game, a, b = make_game()
        attacker = put(game, a, atk=1, health=1, tags=(GameTag.VENOMOUS,))
        defender = put(game, b, atk=5, health=5,
                       tags=(GameTag.DIVINE_SHIELD,))
        with _CombatContext(game, a, b):
            CombatScheduler(game, a, b)._execute_attack(attacker, defender)
        self.assertFalse(defender.dead, "圣盾吸收 1 点伤害，烈毒不应触发")
        self.assertFalse(defender.has(GameTag.DIVINE_SHIELD))

    def test_run_combat_venomous_simultaneous_death_is_tie(self):
        """整场战斗：1/1 烈毒 vs 5/5 应平局（双方同时死亡）。"""
        game, a, b = make_game(seed=11)
        put(game, a, atk=1, health=1, tags=(GameTag.VENOMOUS,))
        put(game, b, atk=5, health=5)
        result = game.run_combat(a, b)
        self.assertIsNone(result.winner, "官方语义：双方同时死亡 = 平局")


class TestCleaveSemantics(unittest.TestCase):
    def _setup(self):
        game, a, b = make_game()
        # 攻击方：1/2 + CLEAVE（会被 5/5 反击打死）
        attacker = put(game, a, atk=1, health=2, tags=(GameTag.CLEAVE,))
        # 防守方：左 1/1、中 5/5（主目标）、右 1/1
        left = put(game, b, atk=1, health=1)
        main = put(game, b, atk=5, health=5)
        right = put(game, b, atk=1, health=1)
        return game, a, b, attacker, left, main, right

    def test_cleave_splash_still_applies_when_attacker_dies(self):
        """攻击者被反击致死时，相邻伤害（同时伤害）仍要结算。"""
        game, a, b, attacker, left, main, right = self._setup()
        with _CombatContext(game, a, b):
            CombatScheduler(game, a, b)._execute_attack(attacker, main)
        self.assertTrue(attacker.dead, "1/2 受到 5 点反击应死亡")
        self.assertEqual(main.health, 4)          # 主目标受到 1 点
        self.assertTrue(left.dead, "左邻应受到顺劈 1 点伤害并死亡")
        self.assertTrue(right.dead, "右邻应受到顺劈 1 点伤害并死亡")

    def test_cleave_adjacent_damage_events_fire_even_if_attacker_dies(self):
        game, a, b, attacker, left, main, right = self._setup()
        damaged = []
        game.events.register(
            __import__("hsrl2.events", fromlist=["Listener"]).Listener(
                event="damage", owner=None,
                callback=lambda g, minion=None, amount=None, **kw:
                damaged.append((minion, amount))))
        with _CombatContext(game, a, b):
            CombatScheduler(game, a, b)._execute_attack(attacker, main)
        targets = {id(m) for m, _ in damaged}
        self.assertIn(id(left), targets)
        self.assertIn(id(right), targets)

    def test_cleave_with_reborn_does_not_break_death_wave(self):
        """顺劈 + 复生：相邻 1 血复生随从正常复生，不因攻击者死亡被跳过。"""
        game, a, b = make_game()
        attacker = put(game, a, atk=1, health=2, tags=(GameTag.CLEAVE,))
        left = put(game, b, card_id="BG25_001", atk=1, health=1,  # Reborn
                   tags=(GameTag.TAUNT, GameTag.REBORN))
        main = put(game, b, atk=5, health=10)     # 反击 5 → 攻击者 1/2 死亡
        right = put(game, b, card_id="BG25_001", atk=1, health=1,
                    tags=(GameTag.TAUNT, GameTag.REBORN))
        with _CombatContext(game, a, b):
            CombatScheduler(game, a, b)._execute_attack(attacker, main)
        self.assertTrue(attacker.dead)
        self.assertFalse(left.dead, "复生后应存活（1 血）")
        self.assertFalse(right.dead, "复生后应存活（1 血）")
        self.assertEqual(left.health, 1)

    def test_cleave_run_combat_kills_adjacent_1hp(self):
        game, a, b = make_game(seed=13)
        put(game, a, atk=1, health=2, tags=(GameTag.CLEAVE,))
        put(game, b, atk=1, health=1)
        # 主目标带嘲讽 → 强制先打它（避免随机选到 1/1 导致用例不稳定）
        put(game, b, atk=5, health=5, tags=(GameTag.TAUNT,))
        put(game, b, atk=1, health=1)
        game.run_combat(a, b)
        # 主目标 5/5 只掉 1 血；两只 1/1 应被顺劈带走（death log 可查）
        deaths = {m.uuid for m in game.combat_death_log}
        self.assertEqual(len(deaths), 3,
                         "攻击者 + 两只相邻 1/1 都应死亡（顺劈不因攻击者死取消）")


if __name__ == "__main__":
    unittest.main()
