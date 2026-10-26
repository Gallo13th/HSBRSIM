"""AC-02 / AC-03 规则常量修正（F-32 / F-33，2026-10-26 跨引擎一致性审计）。

**证据（官方 + 参照双源）**
- 官方 wiki.gg `/wiki/Battlegrounds`（2026-10-26 抓取）:
  * 每张随从池副本数：T1=15, T2=15, T3=13, T4=11, T5=9, T6=7, T7=5；
  * 升级 Base Cost：T2=5, T3=7, T4=8, **T5=11, T6=11**（T7=10）。
- AutoTavern（参照引擎 36.6.3）`crates/taverngym/src/config.rs`:
  * `pool_copies_by_tier: [15, 15, 13, 11, 9, 7, 5]`（L245，36.6.0 wiki data）；
  * `upgrade_costs: [5, 7, 8, 11, 11, 10]`（L237，索引 = 目标档位-2）。
- 旧值出处：`docs/reference_old/BATTLEGROUNDS_RULES.md`（Patch 35.x 遗留文档）
  写 T1=16、T5=9、T6=10 —— 已过时。
- 台账：`docs/CONFORMANCE_AUTOTAVERN.md` AC-02/AC-03（ENGINE_BUG → FIXED）。

本文件锁定常量与**行为级可观测**结果（真实升级动作扣费 / 真实池库存），
避免只测常量自引用。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import constants as C
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.tags import GameTag

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

# 官方 wiki（2026-10-26 抓取）+ AutoTavern config.rs 对齐值
OFFICIAL_POOL_COPIES = {1: 15, 2: 15, 3: 13, 4: 11, 5: 9, 6: 7, 7: 5}
OFFICIAL_UPGRADE_COSTS = {2: 5, 3: 7, 4: 8, 5: 11, 6: 11, 7: 10}

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7) -> Game:
    import hsrl2.scripts  # noqa: F401
    return Game([Hero("TEST_AC_HERO_A", "A"), Hero("TEST_AC_HERO_B", "B")],
                get_db(), seed=seed)


class TestPoolCopiesAC02(unittest.TestCase):
    """AC-02：T1 池份数 16 → 15（官方 wiki + AT 双源）。"""

    def test_constants_match_official(self):
        self.assertEqual(C.POOL_COPIES_BY_TIER, OFFICIAL_POOL_COPIES)

    def test_t1_minion_pool_stock_is_15(self):
        game = make_game(seed=11)
        d = next(x for x in get_db().pool_minions() if x.tech_level == 1)
        self.assertEqual(game.minion_pool.available(d.id), 15,
                         "T1 每张随从池库存应为 15（旧值 16）")

    def test_total_pool_size_matches_tier_counts(self):
        game = make_game(seed=13)
        expected = sum(OFFICIAL_POOL_COPIES[d.tech_level]
                       for d in get_db().pool_minions())
        actual = sum(game.minion_pool.available(d.id)
                     for d in get_db().pool_minions())
        self.assertEqual(actual, expected)


class TestUpgradeCostsAC03(unittest.TestCase):
    """AC-03：升级 Base Cost T5/T6 = 11/11（官方 wiki + AT 双源）。"""

    def test_constants_match_official(self):
        self.assertEqual(C.BASE_UPGRADE_COSTS, OFFICIAL_UPGRADE_COSTS)

    def test_real_upgrade_charges_official_cost(self):
        """真实 upgrade_tavern 动作：升到各档的扣费 == 官方 Base Cost。"""
        for target_tier in (2, 3, 4, 5, 6, 7):
            game = make_game(seed=20 + target_tier)
            hero = game.heroes[0]
            game.max_tavern_tier = 7          # 覆盖 T7 可达性（特殊档）
            hero.set(GameTag.TAVERN_TIER, target_tier - 1)
            hero.set(GameTag.UPGRADE_COST,
                     OFFICIAL_UPGRADE_COSTS[target_tier])
            hero.gold = 30
            gold_before = hero.gold
            ok = game.upgrade_tavern(hero)
            self.assertIs(ok, True, f"升到 T{target_tier} 应成功")
            self.assertEqual(hero.tavern_tier, target_tier)
            self.assertEqual(
                gold_before - hero.gold, OFFICIAL_UPGRADE_COSTS[target_tier],
                f"升到 T{target_tier} 实际扣费应为 "
                f"{OFFICIAL_UPGRADE_COSTS[target_tier]}")

    def test_next_cost_after_upgrade_matches_key_semantics(self):
        """`BASE_UPGRADE_COSTS[new_tier]` = 升到 new_tier 的费用（键=目标档）。"""
        game = make_game(seed=31)
        hero = game.heroes[0]
        hero.set(GameTag.TAVERN_TIER, 3)
        hero.set(GameTag.UPGRADE_COST, OFFICIAL_UPGRADE_COSTS[4])
        hero.gold = 30
        self.assertIs(game.upgrade_tavern(hero), True)   # T3 → T4 扣 8
        self.assertEqual(hero.upgrade_cost, OFFICIAL_UPGRADE_COSTS[5],
                         "升到 T4 后，下一次（T5）基价应为 11")
        hero.gold = 30
        self.assertIs(game.upgrade_tavern(hero), True)   # T4 → T5 扣 11
        self.assertEqual(hero.upgrade_cost, OFFICIAL_UPGRADE_COSTS[6],
                         "升到 T5 后，下一次（T6）基价应为 11")
        hero.gold = 30
        self.assertIs(game.upgrade_tavern(hero), True)   # T5 → T6 扣 11
        self.assertEqual(hero.upgrade_cost, OFFICIAL_UPGRADE_COSTS[7],
                         "升到 T6 后，下一次（T7）基价应为 10")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
