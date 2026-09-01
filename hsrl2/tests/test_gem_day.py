"""BG31_893 Gem Day — Choose One 血宝石加成法术（补注册回归）。"""

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed=7):
    import hsrl2.scripts  # noqa
    return Game([Hero("A", "A"), Hero("B", "B")], get_db(), seed=seed)


class TestGemDay(unittest.TestCase):
    def _cast(self, game, hero, choose_idx):
        """施放 Gem Day 并选择分支（引擎 Choose One 协议弹框）。"""
        from hsrl2.tags import Zone
        s = game.create_spell("BG31_893", controller=hero)
        hero.hand.append(s)
        s.zone = Zone.HAND
        self.assertTrue(game.play_spell(hero, s))
        self.assertEqual(len(game.pending_choices), 1)
        game.pending_choices.pop(0).choose(choose_idx)

    def test_atk_branch(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        self._cast(game, a, 0)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH), 0)
        m = Minion("TEST_M", "M", atk=1, health=10)
        game.summon(a, m)
        game.run_actions(PlayBloodGems(m, 1))
        self.assertEqual(m.atk, 3)      # 1 base + 宝石(1+bonus1)
        self.assertEqual(m.max_health, 11)  # 10 + 宝石健康(1+bonus0)

    def test_health_branch(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        self._cast(game, a, 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), 0)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH), 1)

    def test_choose_both_aura_gives_both(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        aura = Minion("TEST_TB", "TB", atk=1, health=1)
        aura.set(GameTag.CHOOSE_BOTH, True)
        game.summon(a, aura)
        s = game.create_spell("BG31_893", controller=a)
        a.hand.append(s)
        from hsrl2.tags import Zone
        s.zone = Zone.HAND
        self.assertTrue(game.play_spell(hero := a, s))
        self.assertEqual(len(game.pending_choices), 0)   # 跳过选择
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH), 1)


if __name__ == "__main__":
    unittest.main()
