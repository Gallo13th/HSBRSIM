"""批次 37x_deity 行为层测试（7 张池内 Deity 卡 + Energizing Chamber +
Y'Shaarj Deity token）。

全部真实引擎路径:
  - play_minion / play_spell / destroy_minion / card_gained 事件
  - 真实战斗死亡（`_process_single_death`，F-07 进度/awaken/记录）
  - "give your Deity" 经 `Game.give_deity_stats`
  - 金色独立 CardDef（战吼总额用 `_per_trigger_def`）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_37x_deity as B
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 810) -> Game:
    return Game([Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")],
                get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def hand_minion(game: Game, hero: Hero, card_id: str,
                golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def dummy(hero: Hero, name: str = "D", atk: int = 1,
          health: int = 10, race: Race | None = None) -> Minion:
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


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    game.in_combat = True
    game._active_combat = (a, b)
    game._reset_deity_combat()


def aberration_dummy(hero: Hero, name: str = "Ab", atk: int = 2,
                     health: int = 3) -> Minion:
    return dummy(hero, name, atk, health, Race.ABERRATION)


def kill(game: Game, m: Minion) -> None:
    m.health = 0
    game._process_single_death(m)


def deity_stats(game: Game, hero: Hero) -> tuple:
    state = game.deity(hero)
    return (state.atk, state.health)


def play_spell(game: Game, hero: Hero, card_id: str) -> bool:
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return game.play_spell(hero, s)


def put_aberration(game: Game, hero: Hero, card_id: str,
                   atk: int, health: int) -> Minion:
    """真实 Aberration 卡 id + 自定义属性（用于 Y'Shaarj 复活断言）。"""
    m = game.create_minion(card_id, controller=hero)
    m.set(GameTag.BASE_ATK, atk)
    m.set(GameTag.BASE_HEALTH, health)
    m.set(GameTag.HEALTH, health)
    assert game.summon(hero, m)
    return m


# ══════════════════════════════════════════════════════════════════════
# 结构性
# ══════════════════════════════════════════════════════════════════════


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 17 id 注册 / 数值 / DEFERRED 守卫。"""

    def test_registered(self):
        self.assertEqual(len(B._DEITY_CARDS), 17)
        for cid in B._DEITY_CARDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_template_numbers(self):
        db = get_db()
        self.assertEqual((db.get(B.JOYOUS).num(0),
                          db.get(B.JOYOUS).num(1)), (2, 1))
        self.assertEqual((db.get(B.JOYOUS_G).num(0),
                          db.get(B.JOYOUS_G).num(1)), (4, 2))
        self.assertEqual(db.get(B.SHADOW_OF_DOUBT).num(0), 4)
        self.assertEqual(db.get(B.SHADOW_OF_DOUBT).num(1), 5)
        self.assertEqual(db.get(B.SHA_OF_FEAR).num(0), 3)
        self.assertEqual(db.get(B.VICIOUS_MINDSLASHER).num(1), 2)
        self.assertEqual(db.get(B.FACELESS_CONVERTER).num(0), 2)
        self.assertEqual(db.get(B.ENERGIZING_CHAMBER).num(0), 7)
        self.assertEqual(db.get(B.YSHAARJ).num(0), 2)
        self.assertEqual(db.get(B.YSHAARJ_G).num(0), 4)

    def test_deferred_not_registered(self):
        """C'Thun token 不注册（split 特效证据不足，F-07b 待补）。

        BG36_099/106、BGFYM_005 已由 F-08 Discard 批注册（弃牌触发）→
        移出本守卫。
        """
        for cid in ("BGFYM_000", "BGFYM_000_G"):
            self.assertNotIn(cid, REGISTRY, cid)


# ══════════════════════════════════════════════════════════════════════
# BG36_110 Joyous
# ══════════════════════════════════════════════════════════════════════


class TestJoyous(unittest.TestCase):
    def test_battlecry_gives_deity(self):
        game = make_game(seed=811)
        a = game.heroes[0]
        m = hand_minion(game, a, B.JOYOUS)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(deity_stats(game, a), (3, 2))   # 1/1 + 2/1

    def test_golden_total_is_four_two(self):
        game = make_game(seed=812)
        a = game.heroes[0]
        m = hand_minion(game, a, B.JOYOUS, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(deity_stats(game, a), (5, 3))   # 1/1 + 4/2

    def test_repeat_accumulates(self):
        game = make_game(seed=813)
        a = game.heroes[0]
        for _ in range(2):
            m = hand_minion(game, a, B.JOYOUS)
            self.assertTrue(game.play_minion(a, m))
        self.assertEqual(deity_stats(game, a), (5, 3))

    def test_enemy_deity_unaffected(self):
        game = make_game(seed=814)
        a, b = game.heroes
        m = hand_minion(game, a, B.JOYOUS)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(deity_stats(game, b), (1, 1))


# ══════════════════════════════════════════════════════════════════════
# BG36_108 Vicious Mindslasher
# ══════════════════════════════════════════════════════════════════════


class TestViciousMindslasher(unittest.TestCase):
    def test_tavern_spell_gives_self_and_deity(self):
        game = make_game(seed=820)
        a = game.heroes[0]
        v = put(game, B.VICIOUS_MINDSLASHER, a)
        self.assertTrue(play_spell(game, a, "BG28_810"))
        self.assertEqual((v.atk, v.health), (2, 4))
        self.assertEqual(deity_stats(game, a), (2, 3))

    def test_golden_values(self):
        game = make_game(seed=821)
        a = game.heroes[0]
        put(game, B.VICIOUS_MINDSLASHER, a, golden=True)
        self.assertTrue(play_spell(game, a, "BG28_810"))
        self.assertEqual(deity_stats(game, a), (3, 5))   # 1/1 + 2/4

    def test_opponent_cast_does_not_trigger(self):
        game = make_game(seed=822)
        a, b = game.heroes
        put(game, B.VICIOUS_MINDSLASHER, a)
        self.assertTrue(play_spell(game, b, "BG28_810"))
        self.assertEqual(deity_stats(game, a), (1, 1))

    def test_non_pool_spell_does_not_trigger(self):
        game = make_game(seed=823)
        a = game.heroes[0]
        put(game, B.VICIOUS_MINDSLASHER, a)
        self.assertTrue(play_spell(game, a, "BG23_000t"))
        self.assertEqual(deity_stats(game, a), (1, 1))


# ══════════════════════════════════════════════════════════════════════
# BG36_109 The Shadow of Doubt
# ══════════════════════════════════════════════════════════════════════


class TestShadowOfDoubt(unittest.TestCase):
    def test_card_gained_gives_deity(self):
        game = make_game(seed=830)
        a = game.heroes[0]
        put(game, B.SHADOW_OF_DOUBT, a)
        game.pending_hand_add(a, game.create_spell("BG28_810", controller=a))
        self.assertEqual(deity_stats(game, a), (5, 6))   # 1/1 + 4/5

    def test_bought_minion_triggers(self):
        game = make_game(seed=831)
        a = game.heroes[0]
        put(game, B.SHADOW_OF_DOUBT, a)
        a.tavern.clear()
        m = game.create_minion("BG25_008", controller=a)
        game.add_tavern_entity(a, m)
        a.gold = 10
        self.assertTrue(game.buy_from_tavern(a, m))
        self.assertEqual(deity_stats(game, a), (5, 6))

    def test_golden_values(self):
        game = make_game(seed=832)
        a = game.heroes[0]
        put(game, B.SHADOW_OF_DOUBT, a, golden=True)
        game.pending_hand_add(a, game.create_spell("BG28_810", controller=a))
        self.assertEqual(deity_stats(game, a), (9, 11))  # 1/1 + 8/10

    def test_opponent_card_gain_does_not_trigger(self):
        game = make_game(seed=833)
        a, b = game.heroes
        put(game, B.SHADOW_OF_DOUBT, a)
        game.pending_hand_add(b, game.create_spell("BG28_810", controller=b))
        self.assertEqual(deity_stats(game, a), (1, 1))


# ══════════════════════════════════════════════════════════════════════
# BG36_111 Sha of Fear
# ══════════════════════════════════════════════════════════════════════


class TestShaOfFear(unittest.TestCase):
    def test_tavern_spell_buffs_all_and_deity(self):
        game = make_game(seed=840)
        a = game.heroes[0]
        put(game, B.SHA_OF_FEAR, a)
        ally = dummy(a, "Ally", 1, 20)
        self.assertTrue(play_spell(game, a, "BG28_810"))
        self.assertEqual((ally.atk, ally.health), (4, 23))
        self.assertEqual(deity_stats(game, a), (4, 4))

    def test_golden_values(self):
        game = make_game(seed=841)
        a = game.heroes[0]
        put(game, B.SHA_OF_FEAR, a, golden=True)
        ally = dummy(a, "Ally", 1, 20)
        self.assertTrue(play_spell(game, a, "BG28_810"))
        self.assertEqual((ally.atk, ally.health), (7, 26))
        self.assertEqual(deity_stats(game, a), (7, 7))

    def test_opponent_cast_does_not_trigger(self):
        game = make_game(seed=842)
        a, b = game.heroes
        put(game, B.SHA_OF_FEAR, a)
        ally = dummy(a, "Ally", 1, 20)
        self.assertTrue(play_spell(game, b, "BG28_810"))
        self.assertEqual((ally.atk, ally.health), (1, 20))
        self.assertEqual(deity_stats(game, a), (1, 1))


# ══════════════════════════════════════════════════════════════════════
# BG36_113 Drifting Sacrifice
# ══════════════════════════════════════════════════════════════════════


class TestDriftingSacrifice(unittest.TestCase):
    def test_deathrattle_gives_deity(self):
        game = make_game(seed=850)
        a = game.heroes[0]
        m = put(game, B.DRIFTING_SACRIFICE, a)
        game.destroy_minion(m)
        self.assertEqual(deity_stats(game, a), (3, 2))   # 1/1 + 2/1

    def test_reborn_death_triggers_again(self):
        game = make_game(seed=851)
        a = game.heroes[0]
        m = put(game, B.DRIFTING_SACRIFICE, a)
        game.destroy_minion(m)
        reborn = [x for x in a.board if x.card_id == B.DRIFTING_SACRIFICE]
        self.assertEqual(len(reborn), 1)
        self.assertTrue(reborn[0].has(GameTag.REBORN) is False)
        game.destroy_minion(reborn[0])
        self.assertEqual(deity_stats(game, a), (5, 3))

    def test_golden_values(self):
        game = make_game(seed=852)
        a = game.heroes[0]
        m = put(game, B.DRIFTING_SACRIFICE, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual(deity_stats(game, a), (5, 3))   # 1/1 + 4/2


# ══════════════════════════════════════════════════════════════════════
# BG36_318 Faceless Converter
# ══════════════════════════════════════════════════════════════════════


class TestFacelessConverter(unittest.TestCase):
    def test_base_without_spells(self):
        game = make_game(seed=860)
        a = game.heroes[0]
        m = put(game, B.FACELESS_CONVERTER, a)
        game.destroy_minion(m)
        self.assertEqual(deity_stats(game, a), (3, 2))

    def test_improved_by_tavern_spells_cast(self):
        game = make_game(seed=861)
        a = game.heroes[0]
        for _ in range(2):
            self.assertTrue(play_spell(game, a, "BG28_810"))
        m = put(game, B.FACELESS_CONVERTER, a)
        game.destroy_minion(m)
        # 倍率 1+2：2*3=6 / 1*3=3 → 1/1 → 7/4
        self.assertEqual(deity_stats(game, a), (7, 4))

    def test_golden_values(self):
        game = make_game(seed=862)
        a = game.heroes[0]
        m = put(game, B.FACELESS_CONVERTER, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual(deity_stats(game, a), (5, 3))   # 1/1 + 4/2

    def test_non_pool_spell_not_counted(self):
        game = make_game(seed=863)
        a = game.heroes[0]
        self.assertTrue(play_spell(game, a, "BG23_000t"))
        m = put(game, B.FACELESS_CONVERTER, a)
        game.destroy_minion(m)
        self.assertEqual(deity_stats(game, a), (3, 2))


# ══════════════════════════════════════════════════════════════════════
# BG36_371 Energizing Chamber / BG36_103 N'raqi Sapper
# ══════════════════════════════════════════════════════════════════════


class TestEnergizingChamber(unittest.TestCase):
    def test_play_gives_deity_seven(self):
        game = make_game(seed=870)
        a = game.heroes[0]
        self.assertTrue(play_spell(game, a, B.ENERGIZING_CHAMBER))
        self.assertEqual(deity_stats(game, a), (8, 8))   # 1/1 + 7/7

    def test_discarded_casts_twice(self):
        """F-08: 被弃置时 Deity 增益结算 2 次（+7/+7 → +14/+14）。"""
        game = make_game(seed=871)
        a = game.heroes[0]
        s = game.create_spell(B.ENERGIZING_CHAMBER, controller=a)
        a.hand.append(s)
        s.zone = Zone.HAND
        self.assertTrue(game.discard_card(a, s))
        self.assertEqual(deity_stats(game, a), (15, 15))


class TestNraqiSapper(unittest.TestCase):
    def test_battlecry_gets_chamber(self):
        game = make_game(seed=880)
        a = game.heroes[0]
        m = hand_minion(game, a, B.NRAQI_SAPPER)
        before = game.spell_pool.available(B.ENERGIZING_CHAMBER)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([s.card_id for s in a.hand], [B.ENERGIZING_CHAMBER])
        self.assertEqual(game.spell_pool.available(B.ENERGIZING_CHAMBER),
                         before - 1)

    def test_golden_battlecry_two(self):
        game = make_game(seed=881)
        a = game.heroes[0]
        m = hand_minion(game, a, B.NRAQI_SAPPER, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 2)

    def test_deathrattle_one(self):
        game = make_game(seed=882)
        a = game.heroes[0]
        m = put(game, B.NRAQI_SAPPER, a)
        game.destroy_minion(m)
        self.assertEqual([s.card_id for s in a.hand], [B.ENERGIZING_CHAMBER])

    def test_golden_deathrattle_two(self):
        game = make_game(seed=883)
        a = game.heroes[0]
        m = put(game, B.NRAQI_SAPPER, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 2)


# ══════════════════════════════════════════════════════════════════════
# Deity awaken 集成 / Y'Shaarj token
# ══════════════════════════════════════════════════════════════════════


class TestDeityAwakenIntegration(unittest.TestCase):
    def test_buffed_deity_awakens_with_stats(self):
        game = make_game(seed=890)
        a, b = game.heroes
        game.select_deity(a, "BGFYM_000")
        m = hand_minion(game, a, B.JOYOUS)          # Deity +2/+1
        self.assertTrue(game.play_minion(a, m))
        enter_combat(game, a, b)
        for i in range(4):
            kill(game, aberration_dummy(a, f"Ab{i}"))
        tokens = [x for x in a.board if x.card_id == "BGFYM_000"]
        self.assertEqual(len(tokens), 1)
        self.assertEqual((tokens[0].atk, tokens[0].health), (3, 2))

    def test_yshaarj_resurrects_first_two_with_max_stats(self):
        game = make_game(seed=891)
        a, b = game.heroes
        game.select_deity(a, "BGFYM_011")
        enter_combat(game, a, b)
        # 记录 2 只 Aberration 死亡（真实卡 id + 自定义最大属性），
        # 再 2 只凑够阈值
        put_aberration(game, a, "BGFYM_002t", 5, 7)
        put_aberration(game, a, "BGFYM_002t", 9, 9)
        kill(game, a.board[-2])
        kill(game, a.board[-1])
        kill(game, aberration_dummy(a, "Ab3", atk=1, health=1))
        kill(game, aberration_dummy(a, "Ab4", atk=1, health=1))
        token = [x for x in a.board if x.card_id == "BGFYM_011"]
        self.assertEqual(len(token), 1)
        # 杀 Y'Shaarj → 亡语复活前 2 只（真实卡 id + 记录属性）
        game.destroy_minion(token[0])
        revived = [x for x in a.board if x.card_id == "BGFYM_002t"]
        self.assertEqual(len(revived), 2)
        self.assertEqual(sorted((x.atk, x.health) for x in revived),
                         [(5, 7), (9, 9)])

    def test_yshaarj_golden_resurrects_four(self):
        game = make_game(seed=892)
        a, b = game.heroes
        state = game.select_deity(a, "BGFYM_011")
        state.golden = True
        enter_combat(game, a, b)
        for i in range(4):
            put_aberration(game, a, "BGFYM_002t", 2, 2)
            kill(game, a.board[-1])
        token = [x for x in a.board if x.card_id == B.YSHAARJ_G]
        self.assertEqual(len(token), 1)
        game.destroy_minion(token[0])
        revived = [x for x in a.board if x.card_id == "BGFYM_002t"]
        self.assertEqual(len(revived), 4)

    def test_yshaarj_excludes_deities(self):
        game = make_game(seed=893)
        a, b = game.heroes
        game.select_deity(a, "BGFYM_011")
        enter_combat(game, a, b)
        game._deity_combat_deaths[a] = [
            ("BGFYM_000", 9, 9), ("BGFYM_002t", 3, 4)]
        self.assertFalse(game._maybe_awaken_deity(a))   # 进度不足
        game.deity(a).progress = 4
        self.assertTrue(game._maybe_awaken_deity(a))
        ys = [x for x in a.board if x.card_id == "BGFYM_011"][0]
        ys.health = 1
        game.destroy_minion(ys)                         # 亡语只复活非 Deity
        revived = [x for x in a.board if x.card_id == "BGFYM_002t"]
        self.assertEqual(len(revived), 1)
        self.assertFalse(any(x.card_id == "BGFYM_000" for x in a.board))


if __name__ == "__main__":
    unittest.main()
