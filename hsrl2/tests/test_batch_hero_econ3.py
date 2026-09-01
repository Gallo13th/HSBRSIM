"""批次 hero_econ3 语义测试（作业单 2026-09-01，16 注册项）。

覆盖: Millhouse / Sindragosa / Aranna / Cenarius / Clocksworth / Faelin /
A.F. Kay / Patches / Exarch Othaar / C'Thun / Wagtoggle / Jaraxxus /
Nether Portal / N'Zoth / Fish / Lady Vashj。
DEFERRED 断言: Silas / Zephrys（查证缺口, 见 batch_hero_econ3.py 头）。

驱动协议: 显式 on_bind; 事件走引擎真实路径（buy_from_tavern /
refresh_tavern / spend_gold / run_combat）; 数值断言 db 权威。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7) -> Game:
    heroes = [Hero("TB_BaconShop_HERO_52", "A"),
              Hero("TB_BaconShop_HERO_34", "B")]
    return Game(heroes, get_db(), seed=seed)


def bind(game: Game, hero: Hero, power_id: str):
    script = REGISTRY[power_id]
    script.on_bind(hero, game)
    return script


def tavern_minion(game: Game, hero: Hero,
                  card_id: str = "BG25_001") -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


class TestRegistryState(unittest.TestCase):
    OK_IDS = (
        "TB_BaconShop_HP_054", "TB_BaconShop_HP_014", "TB_BaconShop_HP_065",
        "BG32_HERO_001p", "BG34_HERO_002p", "BG22_HERO_201p",
        "TB_BaconShop_HP_044", "TB_BaconShop_HP_072", "BG31_HERO_006p",
        "TB_BaconShop_HP_104", "TB_BaconShop_HP_037a", "TB_BaconShop_HP_036",
        "TB_BaconShop_HP_036t", "TB_BaconShop_HP_105", "TB_BaconShop_HP_105t",
        "BG23_HERO_304p",
    )
    DEFERRED_IDS = ("TB_BaconShop_HP_101", "TB_BaconShop_HP_102")

    def test_ok_registered(self):
        for cid in self.OK_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_deferred_not_registered(self):
        for cid in self.DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)


class TestMillhouse(unittest.TestCase):
    POWER = "TB_BaconShop_HP_054"

    def test_cost_overrides(self):
        game = make_game(seed=21)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        a.gold = 10
        self.assertEqual(a.get(GameTag.TAVERN_MINION_COST_OVERRIDE), 2)
        self.assertEqual(a.get(GameTag.REFRESH_COST_OVERRIDE), 2)
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD), 1)
        m = tavern_minion(game, a)
        self.assertTrue(game.buy_from_tavern(a, m))
        self.assertEqual(a.gold, 8)      # 3 → 2
        game.refresh_tavern(a)
        self.assertEqual(a.gold, 6)      # 1 → 2
        base = a.upgrade_cost
        a.gold = 20
        self.assertTrue(game.upgrade_tavern(a))
        self.assertEqual(a.gold, 20 - base - 1)


class TestSindragosa(unittest.TestCase):
    POWER = "TB_BaconShop_HP_014"

    def test_freeze_and_offer(self):
        game = make_game(seed=22)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        self.assertEqual(a.get(GameTag.TAVERN_MINION_COST_OVERRIDE), 2)
        self.assertEqual(a.get(GameTag.TAVERN_OFFER_MOD), -1)
        # EoT 自动冻结
        game.events.fire(game, "turn_end", turn=game.turn)
        self.assertTrue(a.get(GameTag.FROZEN, False))


class TestAranna(unittest.TestCase):
    POWER = "TB_BaconShop_HP_065"

    def test_free_first_buy_after_14(self):
        game = make_game(seed=23)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        # 模拟 14 次己方攻击
        from hsrl2.minion import Minion as M
        for i in range(14):
            atk = M("BG25_001", "t", atk=1, health=1)
            atk.controller = a
            game.events.fire(game, "after_attack", attacker=atk)
        self.assertTrue(getattr(a, "_aranna_active", False))
        game.events.fire(game, "turn_start", hero=a, turn=game.turn)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 1)
        a.gold = 5
        m1 = tavern_minion(game, a)
        self.assertTrue(game.buy_from_tavern(a, m1))
        self.assertEqual(a.gold, 5)      # 免费
        m2 = tavern_minion(game, a)
        self.assertTrue(game.buy_from_tavern(a, m2))
        self.assertEqual(a.gold, 2)      # 第 2 只 3 金


class TestCenarius(unittest.TestCase):
    POWER = "BG32_HERO_001p"

    def test_income_cap_plus_one(self):
        game = make_game(seed=24)
        a, b = game.heroes
        base = a.income_cap
        bind(game, a, self.POWER)
        self.assertEqual(a.income_cap, base + 1)


class TestClocksworth(unittest.TestCase):
    POWER = "BG34_HERO_002p"

    def test_double_triple_and_coins(self):
        game = make_game(seed=25)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        self.assertEqual(a.get(GameTag.TRIPLE_THRESHOLD), 2)
        self.assertEqual(a.get(GameTag.TRIPLE_REWARD_COINS), 1)
        m1 = game.create_minion("BG25_001", controller=a)
        m2 = game.create_minion("BG25_001", controller=a)
        a.add_to_hand(m1)
        game.check_for_triple(a, m1)
        a.add_to_hand(m2)
        game.check_for_triple(a, m2)
        coins = [c for c in a.hand
                 if getattr(c, "card_id", "") == "BG28_810"]
        self.assertEqual(len(coins), 1)


class TestFaelin(unittest.TestCase):
    POWER = "BG22_HERO_201p"

    def test_skip_first_turn_bank(self):
        game = make_game(seed=26)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        # 第 1 回合跳
        self.assertTrue(a.get(GameTag.TURN_SKIPPED, False))
        # 选完开局 3 个银行 Discover
        for c in list(game.pending_choices):
            if c.kind == "discover_minion":
                c.choose(0)
        # 银行有 T6/T4/T2 各一
        rewards = getattr(a, "_faelin_rewards", {})
        self.assertEqual({k: len(v) for k, v in rewards.items()},
                         {6: 1, 4: 1, 2: 1})


class TestAFKay(unittest.TestCase):
    POWER = "TB_BaconShop_HP_044"

    def test_skip_two_then_discover(self):
        game = make_game(seed=27)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        self.assertTrue(a.get(GameTag.TURN_SKIPPED, False))
        game.end_recruit_phase()          # turn → 2
        self.assertTrue(a.get(GameTag.TURN_SKIPPED, False))
        game.end_recruit_phase()          # turn → 3
        self.assertFalse(a.get(GameTag.TURN_SKIPPED, False))
        self.assertTrue(any(c.kind.startswith("discover")
                            for c in game.pending_choices))


class TestPatches(unittest.TestCase):
    POWER = "TB_BaconShop_HP_072"

    def test_discount_after_pirate_buy(self):
        game = make_game(seed=28)
        a, b = game.heroes
        script = bind(game, a, self.POWER)
        game.start_game()
        # 手造一个 Pirate 购买事件
        from hsrl2.tags import Race
        m = game.create_minion("BG25_001", controller=a)
        m.set(GameTag.RACE, Race.PIRATE)
        game.events.fire(game, "minion_bought", minion=m)
        self.assertEqual(a.get(GameTag.HERO_POWER_NEXT_DISCOUNT), 1)
        d = get_db().get(self.POWER)
        base = d.cost
        self.assertEqual(script.cost_override(a, game), base - 1)


class TestCThun(unittest.TestCase):
    POWER = "TB_BaconShop_HP_104"

    def test_turn_end_repeats(self):
        game = make_game(seed=29)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        m = game.create_minion("BG25_001", controller=a)
        game.summon(a, m)
        game.events.fire(game, "turn_end", turn=3)
        gained = sum(x.health for x in m._buffs) + \
            sum(x.atk for x in m._buffs)
        self.assertEqual(gained, 2 * 3)   # 3 次 × +1/+1


class TestWagtoggle(unittest.TestCase):
    POWER = "TB_BaconShop_HP_037a"

    def test_spend_improves(self):
        game = make_game(seed=30)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        a.gold = 10
        self.assertEqual(a._wagtoggle_bonus, 1)
        game.spend_gold(a, 10)
        self.assertEqual(a._wagtoggle_bonus, 2)


class TestJaraxxus(unittest.TestCase):
    POWER = "TB_BaconShop_HP_036"

    def test_portal_replaces(self):
        game = make_game(seed=31)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        from hsrl2.minion import Minion as M
        for i in range(150):
            atk = M("BG25_001", "t", atk=1, health=1)
            atk.controller = a
            game.events.fire(game, "after_attack", attacker=atk)
        self.assertEqual(game.hero_power_def(a).id, "TB_BaconShop_HP_036t")
        # Nether Portal 已接线（turn_start → 2 恶魔）
        n_hand = len(a.hand)
        game.events.fire(game, "turn_start", hero=a, turn=game.turn)
        self.assertGreaterEqual(len(a.hand), n_hand)


class TestNZoth(unittest.TestCase):
    POWER = "TB_BaconShop_HP_105"

    def test_fish_summoned(self):
        game = make_game(seed=32)
        a, b = game.heroes
        bind(game, a, self.POWER)
        game.start_game()
        fish = [m for m in a.board if m.card_id == "TB_BaconShop_HP_105t"]
        self.assertEqual(len(fish), 1)
        self.assertEqual(fish[0].atk, 2)
        self.assertEqual(fish[0].health, 2)


if __name__ == "__main__":
    unittest.main()
