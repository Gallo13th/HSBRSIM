"""差分驱动批 2 测试：TOP 缺脚本卡（5 张 × 普/金 + 1 法术）。

全部走真实引擎路径：
  - EoT: 真实 TURN_END 全局广播（end_recruit_phase 同款 fire 点）；
  - 磁力: 真实 `game.play_minion(..., magnetic_target=host)` 的
    `attach_magnetic` → `magnetized` 事件；
  - 施法: 真实 `game.play_spell` → `spell_resolved` 后置施法时点；
  - 亡语: 真实 `game.destroy_minion` 死亡链；
  - Spellcraft: 真实 `play_minion`（on_summon 自举 + 立即给法术）。

每张卡均有正/负对照与落空分支。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import TURN_END, TURN_START
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_diff_driven2 as B
from hsrl2.tags import CardType, GameTag, Race, Zone

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


def make_game(seed: int = 201, heroes: list | None = None) -> Game:
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


def fire_turn_end(game: Game) -> None:
    game.events.fire(game, TURN_END, turn=game.turn)


def fire_turn_start(game: Game, hero: Hero) -> None:
    game.events.fire(game, TURN_START, turn=game.turn, hero=hero)


def make_spell(game: Game, hero: Hero, card_id: str):
    """手牌中的法术（create_spell 不绑 REGISTRY → 手动补绑，测试口径）。"""
    spell = game.create_spell(card_id, controller=hero)
    spell.scripts = REGISTRY.get(card_id)
    hero.add_to_hand(spell)
    return spell


# ══════════════════════════════════════════════════════════════════════
# BG26_529 Upbeat Frontdrake
# ══════════════════════════════════════════════════════════════════════


class TestUpbeatFrontdrake(unittest.TestCase):
    def test_third_end_of_turn_gets_one_random_dragon(self):
        game = make_game(seed=210)
        a = game.heroes[0]
        put(game, B.UPBEAT_FRONT_DRAKE, a)
        fire_turn_end(game)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 0, "前 2 个 EoT 不应触发")
        before = sum(game.minion_pool.available(c.id)
                     for c in game.db.pool_minions()
                     if Race.DRAGON in c.races or Race.ALL in c.races)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 1)
        got = a.hand[0]
        self.assertIsInstance(got, Minion)
        self.assertIn(Race.DRAGON, got.races, "必须是 Dragon（含 ALL 身份）")
        after = sum(game.minion_pool.available(c.id)
                    for c in game.db.pool_minions()
                    if Race.DRAGON in c.races or Race.ALL in c.races)
        self.assertEqual(after, before - 1, "随机获取占池 1 份")

    def test_golden_gets_two_dragons(self):
        game = make_game(seed=211)
        a = game.heroes[0]
        put(game, B.UPBEAT_FRONT_DRAKE, a, golden=True)
        fire_turn_end(game)
        fire_turn_end(game)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 2)
        for got in a.hand:
            self.assertIn(Race.DRAGON, got.races)

    def test_counter_resets_after_trigger(self):
        game = make_game(seed=212)
        a = game.heroes[0]
        drake = put(game, B.UPBEAT_FRONT_DRAKE, a)
        for _ in range(3):
            fire_turn_end(game)
        self.assertEqual(len(a.hand), 1)
        fire_turn_end(game)
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 1, "重置后需再等 3 个 EoT")
        fire_turn_end(game)
        self.assertEqual(len(a.hand), 2)

    def test_pool_empty_does_not_crash(self):
        game = make_game(seed=213)
        a = game.heroes[0]
        put(game, B.UPBEAT_FRONT_DRAKE, a)
        game.max_tavern_tier = 0     # 无合法 Dragon 候选
        for _ in range(3):
            fire_turn_end(game)
        self.assertEqual(len(a.hand), 0)


# ══════════════════════════════════════════════════════════════════════
# BG34_175 Junk Jouster
# ══════════════════════════════════════════════════════════════════════


class TestJunkJouster(unittest.TestCase):
    MAGNETIC = "BG26_146"        # Lullabot（T1 磁力）

    def _play_magnetic(self, game: Game, hero: Hero,
                       host: Minion):
        mag = game.create_minion(self.MAGNETIC, controller=hero)
        hero.hand.append(mag)
        stats = (mag.atk, mag.max_health)
        ok = game.play_minion(hero, mag, magnetic_target=host)
        return ok, stats

    def test_magnetize_buffs_all_friendly(self):
        game = make_game(seed=220)
        a = game.heroes[0]
        jouster = put(game, B.JUNK_JOUSTER, a)
        host = dummy(a, "Host", 3, 40, race=Race.MECH)
        ok, mag_stats = self._play_magnetic(game, a, host)
        self.assertTrue(ok)
        # 磁力本体属性并入宿主（attach_magnetic），再吃 +5/+5
        self.assertEqual(
            (host.atk, host.max_health),
            (3 + mag_stats[0] + 5, 40 + mag_stats[1] + 5))
        self.assertEqual((jouster.atk, jouster.max_health), (13, 12))

    def test_golden_buffs_ten_ten(self):
        game = make_game(seed=221)
        a = game.heroes[0]
        jouster = put(game, B.JUNK_JOUSTER, a, golden=True)
        host = dummy(a, "Host", 3, 40, race=Race.MECH)
        ok, mag_stats = self._play_magnetic(game, a, host)
        self.assertTrue(ok)
        self.assertEqual(
            (host.atk, host.max_health),
            (3 + mag_stats[0] + 10, 40 + mag_stats[1] + 10))
        self.assertEqual((jouster.atk, jouster.max_health), (26, 24))

    def test_non_magnetic_play_does_not_trigger(self):
        game = make_game(seed=222)
        a = game.heroes[0]
        jouster = put(game, B.JUNK_JOUSTER, a)
        m = game.create_minion("BG20_100", controller=a)
        a.hand.append(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual((jouster.atk, jouster.max_health), (8, 7))

    def test_opponent_magnetize_does_not_trigger(self):
        game = make_game(seed=223)
        a, b = game.heroes
        jouster = put(game, B.JUNK_JOUSTER, a)
        host = dummy(b, "OHost", 3, 40, race=Race.MECH)
        mag = game.create_minion(self.MAGNETIC, controller=b)
        b.hand.append(mag)
        self.assertTrue(game.play_minion(b, mag, magnetic_target=host))
        self.assertEqual((jouster.atk, jouster.max_health), (8, 7))


# ══════════════════════════════════════════════════════════════════════
# BG33_923 Sundered Matriarch
# ══════════════════════════════════════════════════════════════════════


class TestSunderedMatriarch(unittest.TestCase):
    def test_spell_cast_gives_three_health(self):
        game = make_game(seed=230)
        a = game.heroes[0]
        queen = put(game, B.SUNDERED_MATRIARCH, a)
        other = dummy(a, "Other", 2, 20)
        # Shiny Ring 自带全体 +1/+1；本卡再 +3 Health
        spell = make_spell(game, a, "BG28_168")
        self.assertTrue(game.play_spell(a, spell))
        self.assertEqual((queen.atk, queen.max_health), (8, 8))
        self.assertEqual((other.atk, other.max_health), (3, 24))

    def test_golden_gives_six_health(self):
        game = make_game(seed=231)
        a = game.heroes[0]
        queen = put(game, B.SUNDERED_MATRIARCH, a, golden=True)
        spell = make_spell(game, a, "BG28_168")
        game.play_spell(a, spell)
        self.assertEqual((queen.atk, queen.max_health), (15, 15))

    def test_opponent_cast_does_not_trigger(self):
        game = make_game(seed=232)
        a, b = game.heroes
        queen = put(game, B.SUNDERED_MATRIARCH, a)
        spell = make_spell(game, b, "BG28_168")
        game.play_spell(b, spell)
        self.assertEqual((queen.atk, queen.max_health), (7, 4))


# ══════════════════════════════════════════════════════════════════════
# BG35_340 Alert Alarmist
# ══════════════════════════════════════════════════════════════════════


class TestAlertAlarmist(unittest.TestCase):
    def test_deathrattle_discounts_next_tavern_spell(self):
        game = make_game(seed=240)
        a = game.heroes[0]
        alarmist = put(game, B.ALERT_ALARMIST, a)
        game.destroy_minion(alarmist)
        self.assertEqual(
            a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 1)

    def test_golden_discounts_two(self):
        game = make_game(seed=241)
        a = game.heroes[0]
        alarmist = put(game, B.ALERT_ALARMIST, a, golden=True)
        game.destroy_minion(alarmist)
        self.assertEqual(
            a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 2)

    def test_stacks_with_existing_discount(self):
        game = make_game(seed=242)
        a = game.heroes[0]
        alarmist = put(game, B.ALERT_ALARMIST, a)
        a.set(GameTag.NEXT_SPELL_COST_REDUCTION, 2)
        game.destroy_minion(alarmist)
        self.assertEqual(
            a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 3)


# ══════════════════════════════════════════════════════════════════════
# BG26_501 Reef Riffer（Spellcraft 随从 + Sick Riffs 法术）
# ══════════════════════════════════════════════════════════════════════


class TestReefRiffer(unittest.TestCase):
    def _play_riffer(self, game: Game, hero: Hero,
                     golden: bool = False) -> Minion:
        m = game.create_minion(B.REEF_RIFFER, controller=hero, golden=golden)
        hero.hand.append(m)
        self.assertTrue(game.play_minion(hero, m))
        return m

    def test_play_grants_sick_riffs(self):
        game = make_game(seed=250)
        a = game.heroes[0]
        self._play_riffer(game, a)
        self.assertIn(B.SICK_RIFFS, [c.card_id for c in a.hand])
        self.assertTrue(any(m.has(GameTag.SPELLCRAFT) for m in a.board))

    def test_golden_play_grants_golden_sick_riffs(self):
        game = make_game(seed=251)
        a = game.heroes[0]
        self._play_riffer(game, a, golden=True)
        self.assertIn(B.SICK_RIFFS_G, [c.card_id for c in a.hand])

    def test_sick_riffs_gives_tier_stats(self):
        game = make_game(seed=252)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 4)
        target = dummy(a, "Target", 1, 10)
        spell = make_spell(game, a, B.SICK_RIFFS)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.max_health), (5, 14))

    def test_golden_sick_riffs_gives_double_tier(self):
        game = make_game(seed=253)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 4)
        target = dummy(a, "Target", 1, 10)
        spell = make_spell(game, a, B.SICK_RIFFS_G)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.max_health), (9, 18))

    def test_sick_riffs_expires_at_next_turn(self):
        game = make_game(seed=254)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 3)
        target = dummy(a, "Target", 1, 10)
        spell = make_spell(game, a, B.SICK_RIFFS)
        game.play_spell(a, spell, target=target)
        self.assertEqual((target.atk, target.max_health), (4, 13))
        fire_turn_start(game, a)
        self.assertEqual((target.atk, target.max_health), (1, 10))

    def test_sick_riffs_no_target_does_not_crash(self):
        game = make_game(seed=255)
        a = game.heroes[0]
        spell = make_spell(game, a, B.SICK_RIFFS)
        self.assertTrue(game.play_spell(a, spell, target=None))


# ══════════════════════════════════════════════════════════════════════
# 注册表
# ══════════════════════════════════════════════════════════════════════


class TestRegistration(unittest.TestCase):
    def test_all_cards_registered(self):
        expected = [
            B.UPBEAT_FRONT_DRAKE, B.UPBEAT_FRONT_DRAKE_G,
            B.JUNK_JOUSTER, B.JUNK_JOUSTER_G,
            B.SUNDERED_MATRIARCH, B.SUNDERED_MATRIARCH_G,
            B.ALERT_ALARMIST, B.ALERT_ALARMIST_G,
            B.REEF_RIFFER, B.REEF_RIFFER_G,
            B.SICK_RIFFS, B.SICK_RIFFS_G,
        ]
        for cid in expected:
            self.assertIsNotNone(REGISTRY.get(cid), cid)


if __name__ == "__main__":
    unittest.main()
