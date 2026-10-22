"""差分驱动批 1 测试：TOP 缺脚本卡（5 张 × 普/金）。

全部走**真实引擎路径**：
  - 战吼: 真实 `game.play_minion`（手牌 → 入场 → battlecry 钩子）；
  - 亡语: 真实 `game.destroy_minion` → `check_deaths` 死亡链；
  - Rally: 真实 `CombatScheduler._execute_attack`（攻击宣告后、伤害快照前）；
  - EoT: 真实 `TURN_END` 全局广播（`end_recruit_phase` 同款 fire 点）
    以及一条真实 `game.end_recruit_phase()` 全回合路径；
  - 溢出: 真实 `game.summon` 在 `hero.board_full()` 后广播
    `minion_overflow`。

每张卡都有正/负对照（金色/非金色、匹配/不匹配条件、落空）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.events import TURN_END
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_diff_driven1 as B
from hsrl2.tags import GameTag, Race, Zone

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


def make_game(seed: int = 101, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def dummy(hero: Hero, name: str = "Dummy", atk: int = 1,
          health: int = 50, race: Race | None = None) -> Minion:
    """合成白板随从（无卡脚本；用于构造场景/填板）。"""
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, race)
    hero.board.append(m)
    game._update_positions(hero)
    return m


def buff(game: Game, minion: Minion, atk: int, health: int) -> None:
    game.run_actions(Buff(minion, atk=atk, health=health))


def fire_turn_end(game: Game) -> None:
    """真实 TURN_END 广播（与 `end_recruit_phase` 的 fire 点同参）。"""
    game.events.fire(game, TURN_END, turn=game.turn)


# ══════════════════════════════════════════════════════════════════════
# BG30_129 Catacomb Crasher
# ══════════════════════════════════════════════════════════════════════


class TestCatacombCrasher(unittest.TestCase):
    def _fill_board(self, game: Game, hero: Hero,
                    count: int = 6) -> list[Minion]:
        return [dummy(hero, f"Fill{i}", 1, 10) for i in range(count)]

    def test_overflow_buffs_all_friendly_including_self(self):
        game = make_game(seed=110)
        a = game.heroes[0]
        crasher = put(game, B.CATACOMB_CRASHER, a)
        board = self._fill_board(game, a)      # 1 + 6 = 7（满）
        # 满板第 8 只 → summon 返回 False + minion_overflow
        extra = game.create_minion("BG20_100", controller=a)
        self.assertFalse(game.summon(a, extra))
        for m in board:
            self.assertEqual((m.atk, m.max_health), (3, 12))
        self.assertEqual((crasher.atk, crasher.max_health), (6, 12))

    def test_golden_buffs_four_four(self):
        game = make_game(seed=111)
        a = game.heroes[0]
        crasher = put(game, B.CATACOMB_CRASHER, a, golden=True)
        board = self._fill_board(game, a)
        game.summon(a, game.create_minion("BG20_100", controller=a))
        for m in board:
            self.assertEqual((m.atk, m.max_health), (5, 14))
        self.assertEqual((crasher.atk, crasher.max_health), (12, 24))

    def test_no_overflow_no_buff(self):
        game = make_game(seed=112)
        a = game.heroes[0]
        put(game, B.CATACOMB_CRASHER, a)
        board = self._fill_board(game, a, count=2)   # 1 + 2 = 3（未满）
        self.assertTrue(game.summon(a, game.create_minion("BG20_100",
                                                         controller=a)))
        for m in board:
            self.assertEqual((m.atk, m.max_health), (1, 10))

    def test_opponent_overflow_does_not_buff(self):
        game = make_game(seed=113)
        a, b = game.heroes
        crasher = put(game, B.CATACOMB_CRASHER, a)
        mine = dummy(a, "Mine", 2, 20)
        for i in range(7):
            dummy(b, f"OFill{i}", 1, 10)
        game.summon(b, game.create_minion("BG20_100", controller=b))
        self.assertEqual((mine.atk, mine.max_health), (2, 20))
        self.assertEqual((crasher.atk, crasher.max_health), (4, 10))


# ══════════════════════════════════════════════════════════════════════
# BG26_199 Upbeat Duo
# ══════════════════════════════════════════════════════════════════════


class TestUpbeatDuo(unittest.TestCase):
    def test_two_end_of_turns_copy_left_neighbor(self):
        game = make_game(seed=120)
        a = game.heroes[0]
        left = put(game, "BG20_100", a)     # Razorfen Geomancer 2/1
        duo = put(game, B.UPBEAT_DUO, a)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 0, "第 1 个 EoT 不应触发")
        self.assertEqual(getattr(duo, "_upbeat_duo_left", None), 1)
        buff(game, left, 5, 5)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 1)
        copy = a.hand[0]
        self.assertEqual(copy.card_id, "BG20_100")
        self.assertFalse(copy.is_golden)
        self.assertEqual((copy.atk, copy.max_health), (2, 1),
                         "plain copy 不继承 buff")

    def test_golden_copies_both_adjacent(self):
        game = make_game(seed=121)
        a = game.heroes[0]
        put(game, "BG20_100", a)
        put(game, B.UPBEAT_DUO, a, golden=True)
        put(game, "BG20_101", a)
        fire_turn_end(game)
        fire_turn_end(game)
        ids = sorted(c.card_id for c in a.hand)
        self.assertEqual(ids, ["BG20_100", "BG20_101"])

    def test_no_left_neighbor_is_empty(self):
        game = make_game(seed=122)
        a = game.heroes[0]
        put(game, B.UPBEAT_DUO, a)          # 本体在最左，无左侧
        put(game, "BG20_100", a)
        fire_turn_end(game)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 0)

    def test_real_end_recruit_phase_path(self):
        """真实 `end_recruit_phase()`（含配对/战斗编排）驱动 EoT 计数。"""
        game = make_game(seed=123)
        a = game.heroes[0]
        put(game, "BG20_100", a)
        put(game, B.UPBEAT_DUO, a)
        game.end_recruit_phase()
        self.assertEqual(len(a.hand), 0)
        game.end_recruit_phase()
        self.assertEqual(len([c for c in a.hand
                              if c.card_id == "BG20_100"]), 1)


# ══════════════════════════════════════════════════════════════════════
# BG35_701 Brazen Buccaneer
# ══════════════════════════════════════════════════════════════════════


class TestBrazenBuccaneer(unittest.TestCase):
    def test_buffs_left_most_pirate_once_with_no_cards_played(self):
        game = make_game(seed=130)
        a = game.heroes[0]
        pirate = dummy(a, "P", 1, 10, race=Race.PIRATE)
        buccaneer = put(game, B.BRAZEN_BUCCANEER, a)
        fire_turn_end(game)
        # 最左 Pirate = 先入场的 pirate（Buccaneer 自身也是 Pirate）
        self.assertEqual((pirate.atk, pirate.max_health), (3, 13))
        self.assertEqual((buccaneer.atk, buccaneer.max_health), (5, 6))

    def test_repeats_for_each_card_played_this_turn(self):
        game = make_game(seed=131)
        a = game.heroes[0]
        pirate = dummy(a, "P", 1, 10, race=Race.PIRATE)
        put(game, B.BRAZEN_BUCCANEER, a)
        a.set(GameTag.CARDS_PLAYED_THIS_TURN, 2)
        fire_turn_end(game)
        self.assertEqual((pirate.atk, pirate.max_health), (7, 19))

    def test_counts_tavern_spells_too(self):
        game = make_game(seed=132)
        a = game.heroes[0]
        pirate = dummy(a, "P", 1, 10, race=Race.PIRATE)
        put(game, B.BRAZEN_BUCCANEER, a)
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 1)
        fire_turn_end(game)
        self.assertEqual((pirate.atk, pirate.max_health), (5, 16))

    def test_only_pirate_is_itself(self):
        """无其它 Pirate 时，"最左 Pirate"= Buccaneer 自身（它是 Pirate）。"""
        game = make_game(seed=133)
        a = game.heroes[0]
        buccaneer = put(game, B.BRAZEN_BUCCANEER, a)
        fire_turn_end(game)
        self.assertEqual((buccaneer.atk, buccaneer.max_health), (7, 9))

    def test_golden_buffs_four_six_per_repeat(self):
        game = make_game(seed=134)
        a = game.heroes[0]
        pirate = dummy(a, "P", 1, 10, race=Race.PIRATE)
        put(game, B.BRAZEN_BUCCANEER, a, golden=True)
        fire_turn_end(game)
        self.assertEqual((pirate.atk, pirate.max_health), (5, 16))


# ══════════════════════════════════════════════════════════════════════
# BG34_926 Ruthless Queensguard
# ══════════════════════════════════════════════════════════════════════


class TestRuthlessQueensguard(unittest.TestCase):
    def _play(self, game: Game, hero: Hero, card_id: str,
              golden: bool = False) -> Minion:
        m = game.create_minion(card_id, controller=hero, golden=golden)
        hero.hand.append(m)
        self.assertTrue(game.play_minion(hero, m))
        return m

    def test_battlecry_buffs_minions_and_naga_extra(self):
        game = make_game(seed=140)
        a = game.heroes[0]
        plain = dummy(a, "Plain", 1, 50)
        naga = dummy(a, "Naga", 1, 50, race=Race.NAGA)
        self._play(game, a, B.RUTHLESS_QUEENSGUARD)
        self.assertEqual((plain.atk, plain.max_health), (3, 52))
        self.assertEqual((naga.atk, naga.max_health), (5, 54))

    def test_golden_battlecry_casts_twice(self):
        game = make_game(seed=141)
        a = game.heroes[0]
        plain = dummy(a, "Plain", 1, 50)
        naga = dummy(a, "Naga", 1, 50, race=Race.NAGA)
        self._play(game, a, B.RUTHLESS_QUEENSGUARD, golden=True)
        self.assertEqual((plain.atk, plain.max_health), (5, 54))
        self.assertEqual((naga.atk, naga.max_health), (9, 58))

    def test_deathrattle_buffs_remaining_minions(self):
        game = make_game(seed=142)
        a = game.heroes[0]
        q = put(game, B.RUTHLESS_QUEENSGUARD, a)
        survivor = dummy(a, "Survivor", 1, 50)
        game.destroy_minion(q)
        self.assertEqual((survivor.atk, survivor.max_health), (3, 52))

    def test_rally_buffs_before_damage_snapshot(self):
        game = make_game(seed=143)
        a, b = game.heroes
        q = put(game, B.RUTHLESS_QUEENSGUARD, a)
        target = dummy(b, "Target", 0, 100)
        game.in_combat = True
        game._active_combat = (a, b)
        try:
            CombatScheduler(game, a, b)._execute_attack(q, target)
        finally:
            game.in_combat = False
            game._active_combat = None
        # 3/3 + 一次 Queen's Command（自身 Naga → 共 +4/+4）→ 本次攻击 7 点
        self.assertEqual(target.health, 93)

    def test_empty_board_battlecry_does_not_crash(self):
        game = make_game(seed=144)
        a = game.heroes[0]
        self._play(game, a, B.RUTHLESS_QUEENSGUARD)
        self.assertEqual(len([m for m in a.board if not m.dead]), 1)


# ══════════════════════════════════════════════════════════════════════
# BG34_694 Wintergrasp Ghoul
# ══════════════════════════════════════════════════════════════════════


class TestWintergraspGhoul(unittest.TestCase):
    def test_deathrattle_gets_tomb_turning(self):
        game = make_game(seed=150)
        a = game.heroes[0]
        ghoul = put(game, B.WINTERGRASP_GHOUL, a)
        game.destroy_minion(ghoul)
        self.assertEqual([c.card_id for c in a.hand], [B.TOMB_TURNING])

    def test_golden_gets_two(self):
        game = make_game(seed=151)
        a = game.heroes[0]
        ghoul = put(game, B.WINTERGRASP_GHOUL, a, golden=True)
        game.destroy_minion(ghoul)
        self.assertEqual([c.card_id for c in a.hand],
                         [B.TOMB_TURNING, B.TOMB_TURNING])

    def test_no_copy_before_death(self):
        game = make_game(seed=152)
        a = game.heroes[0]
        put(game, B.WINTERGRASP_GHOUL, a)
        self.assertEqual(len(a.hand), 0)


# ══════════════════════════════════════════════════════════════════════
# 注册表
# ══════════════════════════════════════════════════════════════════════


class TestRegistration(unittest.TestCase):
    def test_all_cards_registered(self):
        expected = [
            B.CATACOMB_CRASHER, B.CATACOMB_CRASHER_G,
            B.UPBEAT_DUO, B.UPBEAT_DUO_G,
            B.BRAZEN_BUCCANEER, B.BRAZEN_BUCCANEER_G,
            B.RUTHLESS_QUEENSGUARD, B.RUTHLESS_QUEENSGUARD_G,
            B.WINTERGRASP_GHOUL, B.WINTERGRASP_GHOUL_G,
        ]
        for cid in expected:
            self.assertIsNotNone(REGISTRY.get(cid), cid)


if __name__ == "__main__":
    unittest.main()
