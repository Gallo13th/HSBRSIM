"""F-14: Reborn 复活体重置为**卡面基础关键词**（Divine Shield 等）。

官方 Power.log（a07dc079cf3bd8d9）：青铜守卫 BGS_034（Divine Shield +
Reborn）第一次死亡时 DS 已破；Reborn 新实体（eid 1487）的 FULL_ENTITY
创建 tag 明确 `DIVINE_SHIELD value=1`，随后 `REBORN value=0`。旧引擎
rebirth 只保留死亡瞬间的 tag（DS 已清）→ 复生体无圣盾，被 4 攻随从
立即击杀，导致本应 win 的战斗被判 tie。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Hit
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


def make_game(seed: int = 31400) -> Game:
    return Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
                get_db(), seed=seed)


class TestRebornRestoresBaseKeywords(unittest.TestCase):
    def test_divine_shield_restored_on_reborn(self):
        g = make_game()
        a, b = g.heroes
        g.in_combat = True
        g._active_combat = (a, b)
        m = g.create_minion("BGS_034", controller=a)
        assert m is not None
        assert g.summon(a, m)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(m.reborn)
        # 第一次伤害被 DS 抵消，DS 消失
        g.run_actions(Hit(m, 1))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(m.dead)
        # 第二次致死 → Reborn；复生体应有卡面基础 Divine Shield
        g.run_actions(Hit(m, 99))
        self.assertFalse(m.dead)
        self.assertEqual(m.health, 1)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD),
                        "Reborn 复生体应恢复卡面基础 Divine Shield")
        self.assertFalse(m.reborn, "复生关键词应被消耗")
        self.assertIn(m, a.board)

    def test_plain_minion_reborn_still_has_no_extra_keywords(self):
        g = make_game(seed=31401)
        a, b = g.heroes
        g.in_combat = True
        g._active_combat = (a, b)
        m = g.create_minion("BG25_013", controller=a)  # Rot Hide Gnoll
        assert m is not None
        assert g.summon(a, m)
        m.set(GameTag.REBORN, True)
        g.run_actions(Hit(m, 999))
        self.assertFalse(m.dead)
        self.assertEqual(m.health, 1)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(m.reborn)


if __name__ == "__main__":
    unittest.main()
