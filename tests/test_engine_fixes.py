"""引擎修复回归测试（与 docs/ENGINE_NOTES.md 对应）。

F-01: 战斗快照 `snapshot_state()` 不得 deepcopy 实体引用（GameTag.KILLER）。
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler  # noqa: F401  (确保模块可导入)
from hsrl2.db import CardDB
from hsrl2.entity import Buff, Entity
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import CardType, GameTag

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def make_game(seed: int = 1):
    db = CardDB.load(DATA_DIR)
    heroes = [Hero("BG20_HERO_101", "A"), Hero("BG20_HERO_102", "B")]
    game = Game(heroes, db, seed=seed)
    return game


class TestSnapshotNoEntityDeepcopy(unittest.TestCase):
    """F-01: KILLER 等实体引用不得进入快照。"""

    def test_killer_dropped_from_snapshot(self):
        m = Minion("TEST_A", "A", atk=2, health=3)
        killer = Entity("TEST_K", "K", card_type=CardType.MINION)
        m.set(GameTag.KILLER, killer)
        snap = m.snapshot_state()
        self.assertNotIn(GameTag.KILLER, snap["tags"],
                         "KILLER 是实体引用，快照必须丢弃（否则 deepcopy 整张 Game 图）")
        for value in snap["tags"].values():
            self.assertNotIsInstance(value, Entity)

    def test_snapshot_does_not_pull_game_graph(self):
        """构造一个带大对象图的击杀者，快照耗时/内容不受影响。"""
        game = make_game()
        m = Minion("TEST_A", "A", atk=2, health=3)
        killer = Minion("TEST_K", "K", atk=2, health=3)
        killer.game = game            # 引用 Game（内含 heroes/pools/events）
        killer.controller = game.heroes[0]
        killer._sentinel = [object() for _ in range(20000)]
        m.set(GameTag.KILLER, killer)
        t0 = time.perf_counter()
        snap = m.snapshot_state()
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.05,
                        f"快照耗时 {elapsed * 1000:.1f}ms，疑似仍在 deepcopy 实体图")
        self.assertNotIn(GameTag.KILLER, snap["tags"])

    def test_snapshot_preserves_stats_and_buffs(self):
        m = Minion("TEST_A", "A", atk=2, health=3)
        m.add_buff(Buff(atk=2, health=1, source_id="TEST_SRC"))
        m.set(GameTag.TAUNT, True)
        m.set(GameTag.DIVINE_SHIELD, True)
        snap = m.snapshot_state()
        self.assertEqual(snap["tags"].get(GameTag.BASE_ATK), 2)
        self.assertTrue(snap["tags"].get(GameTag.TAUNT))
        self.assertEqual(len(snap["buffs"]), 1)
        # 快照是副本: 修改原实体不影响快照
        m.set(GameTag.TAUNT, False)
        self.assertTrue(snap["tags"].get(GameTag.TAUNT))

    def test_snapshot_buffs_list_is_independent(self):
        m = Minion("TEST_A", "A", atk=2, health=3)
        m.add_buff(Buff(atk=1, health=1))
        snap = m.snapshot_state()
        m.add_buff(Buff(atk=1, health=1))
        self.assertEqual(len(snap["buffs"]), 1)
        self.assertEqual(len(m._buffs), 2)

    def test_restore_roundtrip(self):
        m = Minion("TEST_A", "A", atk=2, health=3)
        m.set(GameTag.KILLER, Minion("TEST_K", "K", atk=1, health=1))
        m.add_buff(Buff(atk=3, health=3))
        snap = m.snapshot_state()
        m.add_buff(Buff(atk=5, health=5))
        m.restore_state(snap)
        self.assertEqual(len(m._buffs), 1)
        self.assertNotIn(GameTag.KILLER, m.tags)


class TestCombatKillerHygiene(unittest.TestCase):
    """战斗结束后 KILLER 不应残留为克隆实体。"""

    def test_combat_leaves_no_killer_on_survivors(self):
        game = make_game(seed=3)
        a, b = game.heroes
        big = Minion("TEST_BIG", "Big", atk=5, health=30)
        small = Minion("TEST_SMALL", "Small", atk=1, health=2)
        a.board = [big]
        b.board = [small]
        game.run_combat(a, b)
        for m in a.board:
            if not m.dead:
                self.assertFalse(m.has(GameTag.KILLER),
                                 "战斗复原后 KILLER 应为空（快照不含实体引用）")

    def test_combat_result_repeatable(self):
        """同一 seed 的战斗结果在修复前后语义一致（确定性自检）。"""
        def run(seed):
            game = make_game(seed=seed)
            a, b = game.heroes
            a.board = [Minion("TEST_A", "A", atk=3, health=4)]
            b.board = [Minion("TEST_B", "B", atk=2, health=5)]
            result = game.run_combat(a, b)
            return (result.winner.name if result.winner else None,
                    result.damage_dealt)
        self.assertEqual(run(9), run(9))


if __name__ == "__main__":
    unittest.main()
