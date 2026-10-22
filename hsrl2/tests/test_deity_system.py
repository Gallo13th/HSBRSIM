"""F-07: Deity（旧神）隐藏目标原语测试（引擎层）。

覆盖 `hsrl2/deity.py` + `Game` 原语:
  - 每英雄隐藏 Deity（C'Thun/Y'Shaarj）确定性选择（不消耗 rng 流）
  - `give_deity_stats` 累加
  - 战斗内友方 Aberration 死亡推进进度；阈值 = 官方 BG_OldGod NUM_1 (=4)
  - 达标后召唤 Deity token（属性 = 当前状态；最右空位）
  - 每场战斗重置；满场不召唤；非 Aberration/敌方死亡不推进
  - 本场 Aberration 死亡记录（Y'Shaarj 亡语数据源）

证据见 `hsrl2/deity.py` 模块 docstring / `docs/ENGINE_NOTES.md` F-07。
"""

from __future__ import annotations

import unittest
from pathlib import Path

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


def make_game(seed: int = 707) -> Game:
    return Game([Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")],
                get_db(), seed=seed)


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    game.in_combat = True
    game._active_combat = (a, b)
    game._reset_deity_combat()


def aberration_dummy(hero: Hero, name: str = "Ab", atk: int = 2,
                     health: int = 3) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    m.set(GameTag.RACE, int(Race.ABERRATION))
    hero.board.append(m)
    game._update_positions(hero)
    return m


def plain_dummy(hero: Hero, name: str = "D", atk: int = 1,
                health: int = 3, race: Race | None = None) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, int(race))
    hero.board.append(m)
    game._update_positions(hero)
    return m


def kill(game: Game, m: Minion) -> None:
    m.health = 0
    game._process_single_death(m)


class TestDeityBasics(unittest.TestCase):
    """隐藏 Deity 选择/属性通道。"""

    def test_hidden_deity_created_for_each_hero(self):
        game = make_game(seed=1)
        a, b = game.heroes
        sa = game.deity(a)
        sb = game.deity(b)
        self.assertIn(sa.card_id, ("BGFYM_000", "BGFYM_011"))
        self.assertIn(sb.card_id, ("BGFYM_000", "BGFYM_011"))
        self.assertEqual((sa.atk, sa.health), (1, 1))
        self.assertEqual((sa.progress, sa.awakened), (0, False))

    def test_choice_deterministic_from_seed_without_rng_shift(self):
        g1 = make_game(seed=42)
        g2 = make_game(seed=42)
        rng_state1 = g1.rng._rng.getstate()
        c1 = g1.deity(g1.heroes[0]).card_id
        c2 = g2.deity(g2.heroes[0]).card_id
        self.assertEqual(c1, c2)
        # 不消耗 rng 流（env 确定性/差分可复现契约）
        self.assertEqual(g1.rng._rng.getstate(), rng_state1)

    def test_seed_spreads_choice(self):
        choices = set()
        for seed in range(8):
            game = make_game(seed=seed)
            choices.add(game.deity(game.heroes[0]).card_id)
        self.assertEqual(choices, {"BGFYM_000", "BGFYM_011"})

    def test_give_stats_accumulates(self):
        game = make_game()
        a = game.heroes[0]
        game.give_deity_stats(a, 2, 3)
        game.give_deity_stats(a, 1, 1)
        state = game.deity(a)
        self.assertEqual((state.atk, state.health), (4, 5))

    def test_select_deity_overrides(self):
        game = make_game()
        a = game.heroes[0]
        game.select_deity(a, "BGFYM_011")
        self.assertEqual(game.deity(a).card_id, "BGFYM_011")
        with self.assertRaises(Exception):
            game.select_deity(a, "BG_OldGod")

    def test_threshold_from_data(self):
        game = make_game()
        self.assertEqual(game.deity_threshold(), 4)
        self.assertEqual(game.db.get("BG_OldGod").num(0), 4)


class TestDeityAwaken(unittest.TestCase):
    """Aberration 死亡进度 → awaken 召唤。"""

    def test_three_deaths_not_enough(self):
        game = make_game(seed=2)
        a, b = game.heroes
        enter_combat(game, a, b)
        for i in range(3):
            kill(game, aberration_dummy(a, f"Ab{i}"))
        self.assertEqual(len(a.board), 0)
        self.assertFalse(game.deity(a).awakened)

    def test_four_deaths_awaken_with_current_stats(self):
        game = make_game(seed=3)
        a, b = game.heroes
        game.select_deity(a, "BGFYM_000")
        game.give_deity_stats(a, 3, 2)     # 1/1 → 4/3
        enter_combat(game, a, b)
        for i in range(4):
            kill(game, aberration_dummy(a, f"Ab{i}"))
        state = game.deity(a)
        self.assertTrue(state.awakened)
        tokens = [m for m in a.board if m.card_id == "BGFYM_000"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual((tokens[0].atk, tokens[0].health), (4, 3))

    def test_non_aberration_deaths_do_not_progress(self):
        game = make_game(seed=4)
        a, b = game.heroes
        enter_combat(game, a, b)
        for i in range(4):
            kill(game, plain_dummy(a, f"D{i}", race=Race.BEAST))
        self.assertEqual(game.deity(a).progress, 0)
        self.assertFalse(game.deity(a).awakened)

    def test_enemy_aberration_deaths_go_to_enemy_state(self):
        game = make_game(seed=5)
        a, b = game.heroes
        enter_combat(game, a, b)
        for i in range(4):
            kill(game, aberration_dummy(b, f"Ab{i}"))
        self.assertEqual(game.deity(a).progress, 0)
        self.assertTrue(game.deity(b).awakened)

    def test_only_one_awaken_per_combat(self):
        game = make_game(seed=6)
        a, b = game.heroes
        enter_combat(game, a, b)
        for i in range(6):
            kill(game, aberration_dummy(a, f"Ab{i}"))
        tokens = [m for m in a.board if m.card_id in ("BGFYM_000", "BGFYM_011")]
        self.assertEqual(len(tokens), 1)

    def test_progress_resets_next_combat(self):
        game = make_game(seed=7)
        a, b = game.heroes
        enter_combat(game, a, b)
        for i in range(3):
            kill(game, aberration_dummy(a, f"Ab{i}"))
        self.assertEqual(game.deity(a).progress, 3)
        enter_combat(game, a, b)           # 下一场战斗重置
        self.assertEqual(game.deity(a).progress, 0)
        self.assertFalse(game.deity(a).awakened)

    def test_board_full_retries_after_space(self):
        game = make_game(seed=9)
        a, b = game.heroes
        enter_combat(game, a, b)
        for i in range(7):
            plain_dummy(a, f"F{i}", race=Race.BEAST)
        self.assertEqual(len(a.board), 7)
        state = game.deity(a)
        state.progress = 3
        game._deity_combat_deaths.setdefault(a, [])
        state.progress = 4                     # 第 4 次死亡进度
        self.assertFalse(game._maybe_awaken_deity(a))   # 满场 → 不召唤
        self.assertFalse(state.awakened)
        self.assertEqual(len(a.board), 7)
        a.board.pop()                          # 腾出一位
        self.assertTrue(game._maybe_awaken_deity(a))
        self.assertTrue(state.awakened)
        self.assertEqual(len(a.board), 7)

    def test_aberration_death_records_stats(self):
        game = make_game(seed=10)
        a, b = game.heroes
        enter_combat(game, a, b)
        kill(game, aberration_dummy(a, "Ab1", atk=5, health=7))
        records = game.deity_combat_deaths(a)
        self.assertEqual(records[0][0], "TEST_Ab1")
        self.assertEqual((records[0][1], records[0][2]), (5, 7))


if __name__ == "__main__":
    unittest.main()
