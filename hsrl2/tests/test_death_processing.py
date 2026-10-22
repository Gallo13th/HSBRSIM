"""P0 死亡处理缺陷回归: 重入双亡语 + 满场亡语召唤 + 亡语召唤占死者位。

官方死亡语义 (RULES §6.9 + Hearthstone 通用):
  - 死亡随从先离场（让出板位），亡语随后触发
  - 亡语召唤物填入死者让出的板位（满 7/7 场亡语召唤依然成立）
  - 一次死亡只触发一次亡语（亡语期间的嵌套 check_deaths 不得重复收集）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed=42):
    heroes = [Hero("A", "A"), Hero("B", "B")]
    import hsrl2.scripts  # noqa
    return Game(heroes, get_db(), seed=seed)


class TestDeathProcessingOrder(unittest.TestCase):
    def test_no_double_deathrattle_on_nested_check(self):
        """亡语动作内的 check_deaths 不得重复触发同一死亡。

        场景: 亡语为 Hit(另一随从) —— Hit.do 内部调 check_deaths，
        嵌套扫描不得把正在处理中的死者再次收集（双亡语根因）。
        """
        game = make_game(seed=1)
        a, b = game.heroes
        triggers = []
        bystander = Minion("TEST_BY", "By", atk=1, health=5)
        game.summon(a, bystander)
        victim = Minion("TEST_V", "V", atk=1, health=1)

        def dr(source, g, ctx):
            triggers.append(1)
            from hsrl2.actions.damage import Hit
            return [Hit(bystander, 2, source)]   # 触发嵌套 check_deaths

        victim.scripts = type("S", (), {
            "deathrattle": staticmethod(dr)})
        game.summon(a, victim)
        victim.health = 0
        game.check_deaths()
        self.assertEqual(len(triggers), 1)   # 恰好一次（SA 复现的双亡语）
        self.assertEqual(bystander.health, 3)

    def test_deathrattle_summons_into_freed_slot(self):
        """死亡先离场: 亡语召唤填入死者板位（非最右）。"""
        game = make_game(seed=2)
        a = game.heroes[0]
        left = Minion("TEST_L", "L", atk=1, health=1)
        mid = Minion("TEST_M", "M", atk=1, health=1)
        right = Minion("TEST_R", "R", atk=1, health=1)
        summoned = []

        def dr(s, g, c):
            token = Minion("TEST_T", "T", atk=1, health=1)
            summoned.append(token)
            game.summon(s.controller, token,
                        c.get("position", s.get(GameTag.ZONE_POSITION, 0)))

        mid.scripts = type("S", (), {"deathrattle": staticmethod(dr)})
        game.summon(a, left)
        game.summon(a, mid)
        game.summon(a, right)
        mid.health = 0
        game.check_deaths()
        self.assertEqual([m.name for m in a.board],
                         ["L", "T", "R"])   # token 占据死者原位

    def test_full_board_deathrattle_still_summons(self):
        """7/7 满场: 死者离场后亡语召唤成立（MINION_OVERFLOW 不触发）。"""
        game = make_game(seed=3)
        a = game.heroes[0]
        overflows = []
        game.events.register(__import__("hsrl2.events", fromlist=["Listener"])
                             .Listener(
                                 "minion_overflow", owner=a,
                                 callback=lambda g, **kw: overflows.append(1)))
        token_holder = Minion("TEST_H", "H", atk=1, health=1)

        def dr2(s, g, c):
            game.summon(s.controller,
                        Minion("TEST_T2", "T2", atk=1, health=1),
                        c.get("position", 0))

        token_holder.scripts = type("S", (), {
            "deathrattle": staticmethod(dr2)})
        game.summon(a, token_holder)
        for i in range(6):
            game.summon(a, Minion(f"TEST_F{i}", f"F{i}", atk=1, health=1))
        self.assertEqual(len(a.board), 7)
        token_holder.health = 0
        game.check_deaths()
        self.assertEqual(len(a.board), 7)      # 死一召一仍满
        self.assertEqual(overflows, [])        # 无溢出
        self.assertIn("T2", [m.name for m in a.board])

    def test_reborn_returns_to_original_slot(self):
        """复生: 离场 → 亡语 → 原位 1 血回归。"""
        game = make_game(seed=4)
        a = game.heroes[0]
        reb = Minion("TEST_REB", "Reb", atk=2, health=3)
        reb.set(GameTag.REBORN, True)
        reb.add_buff(Buff(atk=4, health=4))
        left = Minion("TEST_L2", "L2", atk=1, health=1)
        game.summon(a, left)
        game.summon(a, reb)
        reb.health = 0
        game.check_deaths()
        self.assertEqual([m.name for m in a.board], ["L2", "Reb"])  # 原位
        self.assertEqual(reb.health, 1)
        self.assertFalse(reb.reborn)
        self.assertEqual(reb.atk, 2 + 4)       # buff 保留

    def test_recruit_death_pool_release_once(self):
        """招募期死亡只回池一份（双处理会回两份）。"""
        game = make_game(seed=5)
        a = game.heroes[0]
        pool_card = game.minion_pool.candidates(6)[0]
        m = game.create_minion(pool_card, controller=a)
        game.summon(a, m)
        m.scripts = None
        before = game.minion_pool.available(pool_card)
        m.health = 0
        game.check_deaths()
        self.assertEqual(game.minion_pool.available(pool_card), before + 1)


if __name__ == "__main__":
    unittest.main()
