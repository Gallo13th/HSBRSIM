"""批次 deathrattle2 卡牌语义测试（作业单 2026-08-21，18 张池随从）。

覆盖: BG32_820 Firescale Hoarder / BG32_842 Glowing Cinder /
BG32_880 Friendly Geist / BG33_821 Shipwrecked Rascal /
BG34_633 Draconic Warden / BG34_690 Plaguerunner /
BG35_143 Deepwater Chieftain / BG35_604 Sewer Lord（含 token 链
BG19_010 Sewer Rat → BG19_010t Half-Shell）/ BG36_202 Tasty Lobster /
BG36_730 Trapped Clapper（基础版）/ BG36_731 Imp-lusionist /
BG36_760 Captain Cookie / BG36_854 Rescue Bot / BGS_121 Gentle
Djinni / BGS_018 Goldrinn（含金色）。
DEFERRED 卡: 占位守护测试（未注册即正确状态）。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）。金色战吼模型:
引擎触发 2 次 × 基础值 = 金色文本总额; 金色亡语单次触发 = 金色总额。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY, bind_all
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    """创建随从（create_minion 自动绑定 REGISTRY 脚本）→ 召唤。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def kill(game: Game, m: Minion) -> None:
    """公开死亡路径: 致死 → check_deaths（亡语先于移除, C6）。"""
    m.health = 0
    game.check_deaths()


def hand_ids(hero: Hero) -> list:
    return [c.card_id for c in hero.hand]


class TestFirescaleHoarder(unittest.TestCase):
    """BG32_820 Firescale Hoarder — BC&DR: Get a Shiny Ring."""

    def test_battlecry_gets_ring_from_pool(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        avail = game.spell_pool.available("BG28_168")
        m = game.create_minion("BG32_820", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(hand_ids(a), ["BG28_168"])          # Get = 进手牌
        self.assertEqual(game.spell_pool.available("BG28_168"),
                         avail - 1)                          # 占池

    def test_deathrattle_gets_ring(self):
        game = make_game(seed=43)
        a = game.heroes[0]
        avail = game.spell_pool.available("BG28_168")
        m = put(game, "BG32_820", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG28_168"])
        self.assertEqual(game.spell_pool.available("BG28_168"), avail - 1)

    def test_get_generates_when_pool_empty(self):
        game = make_game(seed=44)
        a = game.heroes[0]
        while game.spell_pool.available("BG28_168"):   # 抽干（模拟被购走）
            assert game.spell_pool.acquire("BG28_168")
        m = put(game, "BG32_820", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG28_168"])    # 池空生成不占池

    def test_golden_play_total_two_rings(self):
        game = make_game(seed=45)
        a = game.heroes[0]
        m = game.create_minion("BG32_820", controller=a, golden=True)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        # 金色战吼 ×2 → 总额 2（第一份占池、第二份池空生成）
        self.assertEqual(hand_ids(a), ["BG28_168", "BG28_168"])

    def test_golden_deathrattle_two_rings(self):
        game = make_game(seed=46)
        a = game.heroes[0]
        m = put(game, "BG32_820", a, golden=True)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG28_168", "BG28_168"])


class TestGlowingCinder(unittest.TestCase):
    """BG32_842 Glowing Cinder — DR: Elementals give extra +{0} Health."""

    def test_deathrattle_sets_elemental_extra_health(self):
        game = make_game(seed=47)
        a = game.heroes[0]
        d = get_db().get("BG32_842")
        m = put(game, "BG32_842", a)
        kill(game, m)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), d.num(0))

    def test_golden_uses_golden_value_and_stacks(self):
        game = make_game(seed=48)
        a = game.heroes[0]
        dg = get_db().get("BG32_842_G")
        m1 = put(game, "BG32_842", a, golden=True)
        kill(game, m1)
        m2 = put(game, "BG32_842", a, golden=True)
        kill(game, m2)
        # 多次触发叠加
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0),
                         dg.num(0) * 2)

    def test_negative_no_tavern_spell_atk_written(self):
        game = make_game(seed=49)
        a = game.heroes[0]
        m = put(game, "BG32_842", a)
        kill(game, m)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)


class TestFriendlyGeist(unittest.TestCase):
    """BG32_880 Friendly Geist — DR: Tavern spells give extra +{0} Attack."""

    def test_deathrattle_sets_tavern_spell_extra_atk(self):
        game = make_game(seed=50)
        a = game.heroes[0]
        d = get_db().get("BG32_880")
        m = put(game, "BG32_880", a)
        kill(game, m)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), d.num(0))

    def test_golden_value_and_stacking(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        dg = get_db().get("BG32_880_G")
        m1 = put(game, "BG32_880", a, golden=True)
        kill(game, m1)
        m2 = put(game, "BG32_880", a)               # 普通版叠加
        kill(game, m2)
        self.assertEqual(
            a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0),
            dg.num(0) + get_db().get("BG32_880").num(0))

    def test_negative_no_elemental_tag_written(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        m = put(game, "BG32_880", a)
        kill(game, m)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), 0)


class TestShipwreckedRascal(unittest.TestCase):
    """BG33_821 Shipwrecked Rascal — BC&DR: Get a random Bounty."""

    BOUNTIES = {"BG33_811", "BG33_812", "BG33_813", "BG33_814", "BG33_815"}

    def test_battlecry_gets_one_of_five_bounties(self):
        game = make_game(seed=53)
        a = game.heroes[0]
        m = game.create_minion("BG33_821", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, self.BOUNTIES)

    def test_deathrattle_gets_bounty(self):
        game = make_game(seed=54)
        a = game.heroes[0]
        m = put(game, "BG33_821", a)
        kill(game, m)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, self.BOUNTIES)

    def test_golden_deathrattle_two_distinct_bounties(self):
        game = make_game(seed=55)
        a = game.heroes[0]
        m = put(game, "BG33_821", a, golden=True)
        kill(game, m)
        self.assertEqual(len(a.hand), 2)
        ids = hand_ids(a)
        self.assertTrue(set(ids) <= self.BOUNTIES)
        self.assertNotEqual(ids[0], ids[1])     # 池唯一性 → 两张互异

    def test_negative_forests_bounty_not_in_set(self):
        # Forest's Bounty（BG31_886，T5 非海盗）不是 Bounty 卡集成员
        self.assertNotIn("BG31_886", self.BOUNTIES)


class TestDraconicWarden(unittest.TestCase):
    """BG34_633 Draconic Warden — BC&DR: Get a random Chromadrake."""

    DRAKES = {"BG34_634t", "BG34_635t", "BG34_636t", "BG34_637t",
              "BG34_638t"}

    def test_deathrattle_gets_chromadrake_no_pool_use(self):
        game = make_game(seed=56)
        a = game.heroes[0]
        # put() 直建未占池（测试 harness）; 招募期死亡会把 Warden 自身
        # 副本回池 → +1。chromadrake 获取（非池 token）不动池。
        pool_before = game.minion_pool.total_remaining()
        m = put(game, "BG34_633", a)
        kill(game, m)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, self.DRAKES)
        # 非池 token 不占池; +1 = Warden 自身招募期死亡回池（引擎正确）
        self.assertEqual(game.minion_pool.total_remaining(), pool_before + 1)

    def test_battlecry_and_golden_deathrattle_counts(self):
        game = make_game(seed=57)
        a = game.heroes[0]
        m = game.create_minion("BG34_633", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 1)
        g = put(game, "BG34_633", a, golden=True)
        kill(game, g)
        self.assertEqual(len(a.hand), 3)          # 1（BC）+ 2（金色 DR）
        for c in a.hand:
            self.assertIn(c.card_id, self.DRAKES)


class TestPlaguerunner(unittest.TestCase):
    """BG34_690 Plaguerunner — DR: Undead +{0} ATK (+{1} outside combat)."""

    def _undead(self, game):
        a = game.heroes[0]
        undead = make_minion("Undead", 3, 3, race=Race.UNDEAD)
        game.summon(a, undead)
        return undead

    def test_death_in_combat_applies_num0(self):
        game = make_game(seed=58)
        a = game.heroes[0]
        d = get_db().get("BG34_690")
        undead = self._undead(game)
        m = put(game, "BG34_690", a)
        game.in_combat = True
        kill(game, m)
        game.in_combat = False
        self.assertEqual(undead.atk, 3 + d.num(0))    # "wherever they are"

    def test_death_outside_combat_applies_num1(self):
        game = make_game(seed=59)
        a = game.heroes[0]
        d = get_db().get("BG34_690")
        undead = self._undead(game)
        m = put(game, "BG34_690", a)
        kill(game, m)                                 # 招募期死亡
        self.assertEqual(undead.atk, 3 + d.num(1))

    def test_negative_non_undead_unaffected(self):
        game = make_game(seed=60)
        a = game.heroes[0]
        beast = make_minion("Beast", 3, 3, race=Race.BEAST)
        game.summon(a, beast)
        m = put(game, "BG34_690", a)
        kill(game, m)
        self.assertEqual(beast.atk, 3)

    def test_golden_values(self):
        game = make_game(seed=61)
        a = game.heroes[0]
        dg = get_db().get("BG34_690_G")
        undead = self._undead(game)
        m = put(game, "BG34_690", a, golden=True)
        kill(game, m)
        self.assertEqual(undead.atk, 3 + dg.num(1))


class TestDeepwaterChieftain(unittest.TestCase):
    """BG35_143 Deepwater Chieftain — BC&DR: Get a Deepwater Clan."""

    def test_deathrattle_gets_clan_from_pool(self):
        game = make_game(seed=62)
        a = game.heroes[0]
        avail = game.spell_pool.available("BG35_149")
        m = put(game, "BG35_143", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG35_149"])
        self.assertEqual(game.spell_pool.available("BG35_149"), avail - 1)

    def test_battlecry_and_golden_deathrattle(self):
        game = make_game(seed=63)
        a = game.heroes[0]
        m = game.create_minion("BG35_143", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        g = put(game, "BG35_143", a, golden=True)
        kill(game, g)
        self.assertEqual(hand_ids(a).count("BG35_149"), 3)  # 1 + 2


class TestSewerLord(unittest.TestCase):
    """BG35_604 Sewer Lord — DR token 链: two Sewer Rats → Half-Shells."""

    def test_deathrattle_summons_two_rats(self):
        game = make_game(seed=64)
        a = game.heroes[0]
        d = get_db().get("BG19_010")
        m = put(game, "BG35_604", a)
        kill(game, m)
        rats = [x for x in a.board if x.card_id == "BG19_010"]
        self.assertEqual(len(rats), 2)
        for r in rats:
            self.assertEqual((r.atk, r.max_health), (d.atk, d.health))

    def test_rat_deathrattle_summons_taunt_turtle(self):
        game = make_game(seed=65)
        a = game.heroes[0]
        turtle_def = get_db().get("BG19_010t")
        rat = put(game, "BG19_010", a)             # token 直接入场
        kill(game, rat)
        shells = [x for x in a.board if x.card_id == "BG19_010t"]
        self.assertEqual(len(shells), 1)
        s = shells[0]
        self.assertEqual((s.atk, s.max_health),
                         (turtle_def.atk, turtle_def.health))   # 2/3
        self.assertTrue(s.has(GameTag.TAUNT))      # 引擎缺口自举

    def test_golden_lord_summons_golden_rats_and_turtles(self):
        game = make_game(seed=66)
        a = game.heroes[0]
        gd = get_db().get("BG19_010_G")
        gt = get_db().get("BG19_010_Gt")
        m = put(game, "BG35_604", a, golden=True)
        kill(game, m)
        rats = [x for x in a.board if x.card_id == "BG19_010_G"]
        self.assertEqual(len(rats), 2)
        for r in rats:
            self.assertEqual((r.atk, r.max_health), (gd.atk, gd.health))
            kill(game, r)                          # 金色 Rat 亡语 → 金色龟
        shells = [x for x in a.board if x.card_id == "BG19_010_Gt"]
        self.assertEqual(len(shells), 2)
        for s in shells:
            self.assertEqual((s.atk, s.max_health), (gt.atk, gt.health))
            self.assertTrue(s.has(GameTag.TAUNT))


class TestTastyLobster(unittest.TestCase):
    """BG36_202 Tasty Lobster — DR + Improve your future Tasty Lobsters."""

    def test_first_deathrattle_buffs_random_beast_base_value(self):
        game = make_game(seed=67)
        a = game.heroes[0]
        d = get_db().get("BG36_202")
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        m = put(game, "BG36_202", a)
        kill(game, m)
        self.assertEqual(beast.atk, 2 + d.num(0))
        self.assertEqual(beast.max_health, 2 + d.num(1))

    def test_second_lobster_improved(self):
        game = make_game(seed=68)
        a = game.heroes[0]
        d = get_db().get("BG36_202")
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        m1 = put(game, "BG36_202", a)
        kill(game, m1)
        m2 = put(game, "BG36_202", a)
        kill(game, m2)
        # 第二只 = 自身 num + 一次累积: 首只给 num(0)=1 后 improvement+1，
        # 第二只给 num+I = 1+1 = 2 → 累计 1+2 = 3 攻击（与脚本 spec 一致;
        # 原断言 2+num*2=4 与自身注释"1+1=2"的算术矛盾，已修正）
        self.assertEqual(beast.atk, 2 + d.num(0) + (d.num(0) + d.num(0)))
        self.assertEqual(beast.max_health, 2 + d.num(1) + (d.num(1) + d.num(1)))

    def test_negative_non_beast_not_buffed_and_improve_still_counts(self):
        game = make_game(seed=69)
        a = game.heroes[0]
        d = get_db().get("BG36_202")
        mech = make_minion("Mech", 2, 2, race=Race.MECH)
        game.summon(a, mech)
        m1 = put(game, "BG36_202", a)
        kill(game, m1)                       # 无 Beast → buff 落空
        self.assertEqual(mech.atk, 2)
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        m2 = put(game, "BG36_202", a)
        kill(game, m2)                       # Improve 无目标也累积
        self.assertEqual(beast.atk, 2 + d.num(0) * 2)

    def test_golden_gives_and_improves_double(self):
        game = make_game(seed=70)
        a = game.heroes[0]
        dg = get_db().get("BG36_202_G")
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        m = put(game, "BG36_202", a, golden=True)
        kill(game, m)
        self.assertEqual(beast.atk, 2 + dg.num(0))    # 金色值 + 0 累积
        self.assertEqual(getattr(a, "tasty_lobster_improvement", (0, 0)),
                         (dg.num(0), dg.num(1)))      # Improve += 金色 num

    def test_amalgam_counts_as_beast(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        d = get_db().get("BG36_202")
        amalgam = make_minion("Amal", 2, 2, race=Race.ALL)
        game.summon(a, amalgam)
        m = put(game, "BG36_202", a)
        kill(game, m)
        self.assertEqual(amalgam.atk, 2 + d.num(0))


class TestTrappedClapper(unittest.TestCase):
    """BG36_730 Trapped Clapper — DR: Fodder to next {0} Refreshes."""

    def _fodder_count(self, hero: Hero) -> int:
        return sum(1 for e in hero.tavern if e.card_id == "BG35_150t")

    def test_deathrattle_sets_pending(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        d = get_db().get("BG36_730")
        m = put(game, "BG36_730", a)
        kill(game, m)
        self.assertEqual(game._fodder_refresh_pending.get(a, (0, 0)),
                         (d.num(0), 1))

    def test_refreshes_consume_pending_one_fodder_each(self):
        game = make_game(seed=73)
        a = game.heroes[0]
        d = get_db().get("BG36_730")
        m = put(game, "BG36_730", a)
        kill(game, m)
        game.refresh_tavern(a, auto=True)
        self.assertEqual(self._fodder_count(a), 1)    # 本次刷新含 1 枚
        game.refresh_tavern(a, auto=True)
        # 每次刷新重置整个酒馆——上一枚 Fodder 随旧馆消失，当前馆仍是 1 枚
        # （"next 3 Refreshes" = 之后 3 次刷新各含 1 枚，非累积）
        self.assertEqual(self._fodder_count(a), 1)
        self.assertEqual(game._fodder_refresh_pending.get(a, (0, 0)),
                         (d.num(0) - 2, 1))

    def test_negative_no_fodder_without_deathrattle(self):
        game = make_game(seed=74)
        a = game.heroes[0]
        game.refresh_tavern(a, auto=True)
        self.assertEqual(self._fodder_count(a), 0)


class TestImpLusionist(unittest.TestCase):
    """BG36_731 Imp-lusionist — DR: Get {0} Methodical Madness."""

    def test_deathrattle_count_from_param(self):
        game = make_game(seed=75)
        a = game.heroes[0]
        d = get_db().get("BG36_731")
        avail = game.spell_pool.available("BG36_880")
        m = put(game, "BG36_731", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG36_880"] * d.num(0))
        self.assertEqual(game.spell_pool.available("BG36_880"),
                         avail - d.num(0))

    def test_golden_two_copies(self):
        game = make_game(seed=76)
        a = game.heroes[0]
        dg = get_db().get("BG36_731_G")
        m = put(game, "BG36_731", a, golden=True)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG36_880"] * dg.num(0))
        self.assertGreaterEqual(dg.num(0), 2)         # 金色 "Get {0} copies"


class TestCaptainCookie(unittest.TestCase):
    """BG36_760 Captain Cookie — DR: Get a Chef's Choice."""

    def test_deathrattle_gets_chefs_choice(self):
        game = make_game(seed=77)
        a = game.heroes[0]
        avail = game.spell_pool.available("BG28_518")
        m = put(game, "BG36_760", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG28_518"])
        self.assertEqual(game.spell_pool.available("BG28_518"), avail - 1)

    def test_golden_deathrattle_two(self):
        game = make_game(seed=78)
        a = game.heroes[0]
        m = put(game, "BG36_760", a, golden=True)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG28_518", "BG28_518"])


class TestRescueBot(unittest.TestCase):
    """BG36_854 Rescue Bot — Taunt + DR: Get a Repair Job."""

    def test_taunt_from_card_def(self):
        game = make_game(seed=79)
        a = game.heroes[0]
        m = put(game, "BG36_854", a)
        self.assertTrue(m.has(GameTag.TAUNT))

    def test_deathrattle_gets_repair_job(self):
        game = make_game(seed=80)
        a = game.heroes[0]
        avail = game.spell_pool.available("BG36_624")
        m = put(game, "BG36_854", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG36_624"])
        self.assertEqual(game.spell_pool.available("BG36_624"), avail - 1)

    def test_golden_deathrattle_two(self):
        game = make_game(seed=81)
        a = game.heroes[0]
        m = put(game, "BG36_854", a, golden=True)
        kill(game, m)
        self.assertEqual(hand_ids(a), ["BG36_624", "BG36_624"])


class TestGentleDjinni(unittest.TestCase):
    """BGS_121 Gentle Djinni — Taunt + BC&DR: Get a random Elemental."""

    def test_battlecry_gets_pool_elemental(self):
        game = make_game(seed=82)
        a = game.heroes[0]
        pool_before = game.minion_pool.total_remaining()
        m = game.create_minion("BGS_121", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(a.hand[0].race, Race.ELEMENTAL)
        self.assertEqual(game.minion_pool.total_remaining(), pool_before - 1)

    def test_deathrattle_gets_elemental(self):
        game = make_game(seed=83)
        a = game.heroes[0]
        m = put(game, "BGS_121", a)
        kill(game, m)
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(a.hand[0].race, Race.ELEMENTAL)

    def test_golden_deathrattle_two_elementals(self):
        game = make_game(seed=84)
        a = game.heroes[0]
        m = put(game, "BGS_121", a, golden=True)
        kill(game, m)
        self.assertEqual(len(a.hand), 2)
        for c in a.hand:
            self.assertEqual(c.race, Race.ELEMENTAL)

    def test_taunt_from_card_def(self):
        game = make_game(seed=85)
        a = game.heroes[0]
        m = put(game, "BGS_121", a)
        self.assertTrue(m.has(GameTag.TAUNT))


class TestGoldrinn(unittest.TestCase):
    """BGS_018 Goldrinn — DR: Your Beasts have +{0}/+{1} until next turn."""

    def test_deathrattle_buffs_all_beasts_not_others(self):
        game = make_game(seed=86)
        a = game.heroes[0]
        d = get_db().get("BGS_018")
        b1 = make_minion("B1", 1, 1, race=Race.BEAST)
        b2 = make_minion("B2", 2, 2, race=Race.BEAST)
        mech = make_minion("M", 3, 3, race=Race.MECH)
        for x in (b1, b2, mech):
            game.summon(a, x)
        m = put(game, "BGS_018", a)
        kill(game, m)
        self.assertEqual(b1.atk, 1 + d.num(0))
        self.assertEqual(b1.max_health, 1 + d.num(1))
        self.assertEqual(b2.atk, 2 + d.num(0))
        self.assertEqual(b2.max_health, 2 + d.num(1))
        self.assertEqual((mech.atk, mech.max_health), (3, 3))   # 非 Beast

    def test_golden_values(self):
        game = make_game(seed=87)
        a = game.heroes[0]
        dg = get_db().get("TB_BaconUps_085")
        beast = make_minion("Beast", 1, 1, race=Race.BEAST)
        game.summon(a, beast)
        m = put(game, "BGS_018", a, golden=True)
        kill(game, m)
        self.assertEqual(beast.atk, 1 + dg.num(0))
        self.assertEqual(beast.max_health, 1 + dg.num(1))

    def test_amalgam_counts_as_beast(self):
        game = make_game(seed=88)
        a = game.heroes[0]
        d = get_db().get("BGS_018")
        amalgam = make_minion("Amal", 1, 1, race=Race.ALL)
        game.summon(a, amalgam)
        m = put(game, "BGS_018", a)
        kill(game, m)
        self.assertEqual(amalgam.atk, 1 + d.num(0))


class TestDeferredCardsNotRegistered(unittest.TestCase):
    """DEFERRED 卡守护: 未注册 REGISTRY 即当前正确状态（见批次报告）。"""

    def test_unblocked_cards_now_registered(self):
        # 依赖修复后由 batch_misc 解冻: Waveling/Scorpid/Kangor;
        # TrappedClapperGolden 维持 DEFERRED（每刷新双 Fodder 协议缺口）
        for cid in ("BG34_856", "BG36_209", "BGS_012"):
            self.assertIn(cid, REGISTRY, cid)
        self.assertNotIn("BG36_730_G", REGISTRY)


class TestBatchRegistrationIntegrity(unittest.TestCase):
    """注册完整性: 本批全部 id 存在于 CardDB（bind_all 校验）。"""

    _IDS = [
        "BG32_820", "BG32_820_G", "BG32_842", "BG32_842_G", "BG32_880",
        "BG32_880_G", "BG33_821", "BG33_821_G", "BG34_633", "BG34_633_G",
        "BG34_690", "BG34_690_G", "BG35_143", "BG35_143_G", "BG35_604",
        "BG35_604_G", "BG19_010", "BG19_010_G", "BG36_202", "BG36_202_G",
        "BG36_730", "BG36_731", "BG36_731_G", "BG36_760", "BG36_760_G",
        "BG36_854", "BG36_854_G", "BGS_121", "TB_BaconUps_165", "BGS_018",
        "TB_BaconUps_085",
    ]

    def test_all_registered_and_known_to_db(self):
        for cid in self._IDS:
            self.assertIn(cid, REGISTRY, cid)
        bind_all(get_db())      # 未知卡 id 会 KeyError


if __name__ == "__main__":
    unittest.main()
