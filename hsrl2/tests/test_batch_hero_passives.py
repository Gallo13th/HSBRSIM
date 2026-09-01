"""批次 hero_passives 语义测试（作业单 2026-08-22，16 张被动英雄技能）。

覆盖 15 OK: Hoggarr / Nozdormu / Omu / Flurgl / Kael'thas / Gallywix /
Dinotamer Brann / Ini Stormcoil / Al'Akir / Y'Shaarj / Deathwing /
Ysera / Rokara / The Curator / Patchwerk; DEFERRED 1: Ragnaros
（断言未注册）。

被动协议驱动: 测试显式调 ``REGISTRY[hero_power_def(hero).id].
on_bind(hero, game)``（主线在 start_game 接线前的人工等价物——接线后
本测试不动）。被动不可主动使用: use_hero_power 恒 False。
数值断言一律 CardDef.num()/db 属性计算（TEST_SOP §4）。
SoC 驱动: CombatScheduler._start_of_combat_phase（soc）; 战斗回滚/
永久重放: game.run_combat + 手动 fire combat_end（引擎在
end_recruit_phase 中广播——单测等价驱动，语义同源）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(hero_ids: tuple[str, str] = ("TB_BaconShop_HERO_57",
                                           "TB_BaconShop_HERO_52"),
              seed: int = 42) -> Game:
    """双英雄对局; 默认 Nozdormu + Deathwing（互不干扰彼此断言）。"""
    heroes = [Hero(hero_ids[0], hero_ids[0]),
              Hero(hero_ids[1], hero_ids[1])]
    return Game(heroes, get_db(), seed=seed)


def bind(game: Game, hero: Hero):
    """被动接线（主线 start_game 一行的测试等价物）。"""
    power = game.hero_power_def(hero)
    assert power is not None, f"hero {hero.card_id} has no power def"
    script = REGISTRY[power.id]
    script.on_bind(hero, game)
    return script


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def summon_plain(game: Game, hero: Hero, m: Minion) -> Minion:
    game.summon(hero, m)
    return m


def buy_from_tavern(game: Game, hero: Hero, m: Minion,
                    gold: int = 10) -> bool:
    """把构造随从挂入酒馆展示区后购买（驱动 minion_bought 真实路径）。

    gold: 购买前设定英雄持有金币（默认 10，充足）。"""
    hero.gold = gold
    m.controller = hero
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return game.buy_from_tavern(hero, m)


def sell(game: Game, hero: Hero, m: Minion) -> bool:
    return game.sell_minion(hero, m)


def kill(game: Game, m: Minion, killer: Minion | None = None) -> None:
    """真实死亡路径: take_damage + check_deaths（驱动 death 事件）。"""
    m.take_damage(max(1, m.health), source=killer or make_minion("K", 0, 0))
    game.check_deaths()


def soc(game: Game, a: Hero, b: Hero) -> None:
    CombatScheduler(game, a, b)._start_of_combat_phase()


def attack(game: Game, attacker: Minion, defender: Minion) -> None:
    """单次攻击执行器（伤害+死亡+after_attack 全路径）。"""
    a, b = attacker.controller, defender.controller
    CombatScheduler(game, a, b)._execute_attack(attacker, defender)


def fire_combat_end(game: Game, a: Hero, b: Hero) -> None:
    game.events.fire(game, "combat_end", hero_a=a, hero_b=b, result=None)


class TestRegistryState(unittest.TestCase):
    """批次注册面: 15 被动 OK; Ragnaros DEFERRED 不注册。"""

    OK_IDS = (
        "BG26_HERO_101p", "TB_BaconShop_HP_063", "TB_BaconShop_HP_082",
        "TB_BaconShop_HP_056", "TB_BaconShop_HP_066", "TB_BaconShop_HP_008",
        "TB_BaconShop_HP_048", "BG22_HERO_200p", "TB_BaconShop_HP_086",
        "TB_BaconShop_HP_103", "TB_BaconShop_HP_061", "TB_BaconShop_HP_062",
        "BG20_HERO_100p", "TB_BaconShop_HP_033", "TB_BaconShop_HP_035",
    )

    def test_ok_powers_registered_and_passive(self):
        for cid in self.OK_IDS:
            self.assertIn(cid, REGISTRY)
            self.assertTrue(getattr(REGISTRY[cid], "passive", False))
            self.assertTrue(hasattr(REGISTRY[cid], "on_bind"))

    def test_ragnaros_unfrozen_by_passives2_batch(self):
        # 2026-08-23 引擎缺口修复（replace_hero_power + turn_end 广播）
        # 后由 batch_hero_passives2 解冻注册——本断言随解冻同步更新
        self.assertIn("TB_BaconShop_HP_087", REGISTRY)
        self.assertTrue(REGISTRY["TB_BaconShop_HP_087"].passive)


class TestPassiveNotActivelyUsable(unittest.TestCase):
    """被动技能 use_hero_power 恒 False（引擎 passive 协议）。"""

    def test_all_bound_passives_unusable(self):
        for hero_id, partner in (
            ("TB_BaconShop_HERO_57", "TB_BaconShop_HERO_52"),
            ("BG26_HERO_101", "TB_BaconShop_HERO_52"),
            ("TB_BaconShop_HERO_33", "TB_BaconShop_HERO_34"),
        ):
            game = make_game((hero_id, partner))
            a = game.heroes[0]
            bind(game, a)
            a.gold = 10
            self.assertFalse(game.use_hero_power(a))


class TestCapnHoggarr(unittest.TestCase):
    """BG26_HERO_101p — 买海盗 +1 金。"""

    def make(self):
        game = make_game(("BG26_HERO_101", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_buy_pirate_gains_gold(self):
        game, a, _ = self.make()
        self.assertTrue(buy_from_tavern(
            game, a, make_minion("P", 1, 1, race=Race.PIRATE)))
        self.assertEqual(a.gold, 10 - C.MINION_BUY_COST + 1)

    def test_buy_all_race_counts_as_pirate(self):
        game, a, _ = self.make()
        self.assertTrue(buy_from_tavern(
            game, a, make_minion("A", 1, 1, race=Race.ALL)))
        self.assertEqual(a.gold, 10 - C.MINION_BUY_COST + 1)

    def test_buy_non_pirate_no_gain(self):
        game, a, _ = self.make()
        self.assertTrue(buy_from_tavern(
            game, a, make_minion("B", 1, 1, race=Race.BEAST)))
        self.assertEqual(a.gold, 10 - C.MINION_BUY_COST)

    def test_enemy_buy_no_trigger(self):
        game, a, b = self.make()
        self.assertTrue(buy_from_tavern(
            game, b, make_minion("P", 1, 1, race=Race.PIRATE)))
        self.assertEqual(b.gold, 10 - C.MINION_BUY_COST)

    def test_gold_capped_at_99(self):
        game, a, _ = self.make()
        a.gold = C.GOLD_HOLD_CAP
        m = make_minion("P", 1, 1, race=Race.PIRATE)
        m.controller = a
        game.events.fire(game, "minion_bought", minion=m)
        self.assertEqual(a.gold, C.GOLD_HOLD_CAP)


class TestNozdormu(unittest.TestCase):
    """TB_BaconShop_HP_063 — 每回合开始 +1 免费刷新。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_57", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_turn_start_grants_free_refresh(self):
        game, a, _ = self.make()
        game.events.fire(game, "turn_start", turn=1, hero=a)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 1)

    def test_manual_refresh_consumes_free_before_gold(self):
        game, a, _ = self.make()
        game.events.fire(game, "turn_start", turn=1, hero=a)
        a.gold = 10
        game.refresh_tavern(a)                 # 手动刷新
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)
        self.assertEqual(a.gold, 10)           # 免费次数先于金币
        game.refresh_tavern(a)                 # 次数耗尽 → 扣金
        self.assertEqual(a.gold, 10 - C.REFRESH_COST)

    def test_enemy_turn_no_grant(self):
        game, a, b = self.make()
        game.events.fire(game, "turn_start", turn=1, hero=b)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)


class TestForestWardenOmu(unittest.TestCase):
    """TB_BaconShop_HP_082 — 升级酒馆 +2 金。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_74", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_upgrade_gains_two_gold(self):
        game, a, _ = self.make()
        a.gold = 10
        cost = a.upgrade_cost
        self.assertTrue(game.upgrade_tavern(a))
        self.assertEqual(a.gold, 10 - cost + 2)
        self.assertEqual(a.tavern_tier, 2)

    def test_cannot_afford_no_trigger(self):
        game, a, _ = self.make()
        a.gold = 0
        self.assertFalse(game.upgrade_tavern(a))
        self.assertEqual(a.gold, 0)

    def test_enemy_upgrade_no_trigger(self):
        game, a, b = self.make()
        b.gold = 10
        cost = b.upgrade_cost
        self.assertTrue(game.upgrade_tavern(b))
        self.assertEqual(b.gold, 10 - cost)


class TestFungalmancerFlurgl(unittest.TestCase):
    """TB_BaconShop_HP_056 — 每卖 5 只随从 → random Murloc。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_55", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def _sell_n(self, game, a, n):
        for _ in range(n):
            sell(game, a, summon_plain(game, a, make_minion(f"S", 1, 1)))

    def test_five_sells_grant_murloc_from_pool(self):
        game, a, _ = self.make()
        threshold = get_db().get("TB_BaconShop_HP_056").num(0)
        self._sell_n(game, a, threshold - 1)
        self.assertEqual([m for m in a.hand if isinstance(m, Minion)], [])
        self._sell_n(game, a, 1)
        got = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual(len(got), 1)
        self.assertIn(got[0].race, (Race.MURLOC, Race.ALL))

    def test_counter_resets_and_repeats(self):
        game, a, _ = self.make()
        threshold = get_db().get("TB_BaconShop_HP_056").num(0)
        self._sell_n(game, a, threshold)
        n1 = len([m for m in a.hand if isinstance(m, Minion)])
        self._sell_n(game, a, threshold)
        n2 = len([m for m in a.hand if isinstance(m, Minion)])
        self.assertEqual((n1, n2), (1, 2))     # 取模 repeat

    def test_enemy_sell_not_counted(self):
        game, a, b = self.make()
        threshold = get_db().get("TB_BaconShop_HP_056").num(0)
        for _ in range(threshold):
            sell(game, b, summon_plain(game, b, make_minion("S", 1, 1)))
        self.assertEqual([m for m in a.hand if isinstance(m, Minion)], [])


class TestKaeltas(unittest.TestCase):
    """TB_BaconShop_HP_066 — 每买 3 随从 → Tavern Coin。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_60", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_three_minion_buys_grant_coin(self):
        game, a, _ = self.make()
        for i in range(2):
            self.assertTrue(buy_from_tavern(
                game, a, make_minion(f"M{i}", 1, 1)))
        self.assertEqual(
            [c for c in a.hand if c.card_id == "BG28_810"], [])
        self.assertTrue(buy_from_tavern(
            game, a, make_minion("M2", 1, 1)))
        coins = [c for c in a.hand if c.card_id == "BG28_810"]
        self.assertEqual(len(coins), 1)

    def test_spell_buy_not_counted(self):
        game, a, _ = self.make()
        self.assertTrue(game.spell_pool.acquire("BG28_805"))
        s = game.create_spell("BG28_805", controller=a)   # Strike Oil T2
        s.zone = Zone.TAVERN
        a.gold = 10
        a.tavern.append(s)
        self.assertTrue(game.buy_from_tavern(a, s))
        coins = [c for c in a.hand if c.card_id == "BG28_810"]
        self.assertEqual(coins, [])

    def test_coin_generated_with_pool_accounting(self):
        game, a, _ = self.make()
        avail = game.spell_pool.available("BG28_810")
        for i in range(3):
            self.assertTrue(buy_from_tavern(
                game, a, make_minion(f"M{i}", 1, 1)))
        self.assertEqual(game.spell_pool.available("BG28_810"),
                         max(0, avail - 1))


class TestTradePrinceGallywix(unittest.TestCase):
    """TB_BaconShop_HP_008 — 卖随从 → 下回合 +1 金。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_10", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_sell_defers_gold_to_next_turn(self):
        game, a, _ = self.make()
        sell(game, a, summon_plain(game, a, make_minion("S", 1, 1)))
        self.assertEqual(len(game.deferred_actions), 1)
        game.turn = 2
        game._begin_recruit_for(a)
        self.assertEqual(
            a.gold, C.gold_base_income(2, a.income_cap) + 1)

    def test_multiple_sells_stack(self):
        game, a, _ = self.make()
        for _ in range(3):
            sell(game, a, summon_plain(game, a, make_minion("S", 1, 1)))
        self.assertEqual(len(game.deferred_actions), 3)
        game.turn = 2
        game._begin_recruit_for(a)
        self.assertEqual(
            a.gold, C.gold_base_income(2, a.income_cap) + 3)

    def test_enemy_sell_no_defer_for_us(self):
        game, a, b = self.make()
        sell(game, b, summon_plain(game, b, make_minion("S", 1, 1)))
        ours = [(h, act) for h, act in game.deferred_actions if h is a]
        self.assertEqual(ours, [])


class TestDinotamerBrann(unittest.TestCase):
    """TB_BaconShop_HP_048 — 买 4 战吼随从 → Brann（once per game）。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_43", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        d = get_db().get("TB_BaconShop_HP_048")
        brann_id = get_db().by_dbf(d.evolution_card_id).id
        return game, game.heroes[0], game.heroes[1], brann_id

    def _buy_battlecry(self, game, a):
        m = make_minion("BC", 1, 1)
        m.set(GameTag.BATTLECRY, True)
        self.assertTrue(buy_from_tavern(game, a, m))

    def test_four_battlecry_buys_grant_brann(self):
        game, a, _, brann_id = self.make()
        avail = game.minion_pool.available(brann_id)
        self.assertGreater(avail, 0)
        for _ in range(3):
            self._buy_battlecry(game, a)
        self.assertEqual(
            [m for m in a.hand if m.card_id == brann_id], [])
        self._buy_battlecry(game, a)
        got = [m for m in a.hand if m.card_id == brann_id]
        self.assertEqual(len(got), 1)
        self.assertEqual(game.minion_pool.available(brann_id), avail - 1)

    def test_once_per_game(self):
        game, a, _, brann_id = self.make()
        for _ in range(8):                     # 两轮阈值
            self._buy_battlecry(game, a)
        got = [m for m in a.hand if m.card_id == brann_id]
        self.assertEqual(len(got), 1)

    def test_non_battlecry_and_enemy_not_counted(self):
        game, a, b, brann_id = self.make()
        self.assertTrue(buy_from_tavern(
            game, a, make_minion("Plain", 1, 1)))          # 非战吼×4
        for _ in range(3):
            self._buy_battlecry(game, b)                    # 敌方×3
        self.assertEqual([m for m in a.hand if m.card_id == brann_id],
                         [])


class TestIniStormcoil(unittest.TestCase):
    """BG22_HERO_200p — 每 9 友方死亡 → random Mech。"""

    def make(self):
        game = make_game(("BG22_HERO_200", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def _kill_friendly(self, game, a):
        kill(game, summon_plain(game, a, make_minion("F", 1, 1)))

    def test_nine_deaths_grant_mech(self):
        game, a, _ = self.make()
        threshold = get_db().get("BG22_HERO_200p").num(0)
        for _ in range(threshold - 1):
            self._kill_friendly(game, a)
        self.assertEqual([m for m in a.hand if isinstance(m, Minion)], [])
        self._kill_friendly(game, a)
        got = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual(len(got), 1)
        self.assertIn(got[0].race, (Race.MECH, Race.ALL))

    def test_enemy_deaths_not_counted(self):
        game, a, b = self.make()
        threshold = get_db().get("BG22_HERO_200p").num(0)
        for _ in range(threshold):
            kill(game, summon_plain(game, b, make_minion("E", 1, 1)))
        self.assertEqual([m for m in a.hand if isinstance(m, Minion)], [])

    def test_modulo_repeat(self):
        game, a, _ = self.make()
        threshold = get_db().get("BG22_HERO_200p").num(0)
        for _ in range(2 * threshold):
            self._kill_friendly(game, a)
        self.assertEqual(len([m for m in a.hand if isinstance(m, Minion)]),
                         2)


class TestAlAkir(unittest.TestCase):
    """TB_BaconShop_HP_086 — SoC 最左随从获 Windfury/圣盾/嘲讽（本场）。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_76", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_soc_buffs_left_most_only(self):
        game, a, b = self.make()
        left = summon_plain(game, a, make_minion("L", 2, 2))
        right = summon_plain(game, a, make_minion("R", 2, 2))
        soc(game, a, b)
        for tag in (GameTag.WINDFURY, GameTag.DIVINE_SHIELD,
                    GameTag.TAUNT):
            self.assertTrue(left.has(tag))
            self.assertFalse(right.has(tag))

    def test_empty_board_safe(self):
        game, a, b = self.make()
        soc(game, a, b)                        # 空场不抛
        self.assertEqual(a.board, [])

    def test_keywords_rollback_after_combat(self):
        game, a, b = self.make()
        left = summon_plain(game, a, make_minion("L", 2, 2))
        summon_plain(game, b, make_minion("Foe", 0, 5))
        game.run_combat(a, b)
        for tag in (GameTag.WINDFURY, GameTag.DIVINE_SHIELD,
                    GameTag.TAUNT):
            self.assertFalse(left.has(tag))    # SoC 增益仅本场


class TestYshaarj(unittest.TestCase):
    """TB_BaconShop_HP_103 — SoC 召唤并获取本馆等级随从。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_92", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_soc_summons_and_gets_tier_minion(self):
        game, a, b = self.make()
        a.set(GameTag.TAVERN_TIER, 3)
        summon_plain(game, a, make_minion("Keeper", 1, 5))
        cands = [d.id for d in get_db().pool_minions()
                 if d.tech_level == 3 and game.minion_pool.available(d.id) > 0]
        avail_total = sum(game.minion_pool.available(c) for c in cands)
        soc(game, a, b)
        summoned = [m for m in a.board if m.card_id in cands]
        in_hand = [m for m in a.hand if isinstance(m, Minion)
                   and m.card_id in cands]
        self.assertEqual((len(summoned), len(in_hand)), (1, 1))
        self.assertEqual(summoned[0].card_id, in_hand[0].card_id)
        self.assertEqual(summoned[0].tech_level, 3)
        self.assertEqual(
            sum(game.minion_pool.available(c) for c in cands),
            avail_total - 1)                   # 恰占 1 份池

    def test_full_board_still_gets_in_hand(self):
        game, a, b = self.make()
        for _ in range(C.BOARD_SIZE):
            summon_plain(game, a, make_minion("X", 1, 1))
        soc(game, a, b)
        self.assertEqual(len(a.board), C.BOARD_SIZE)
        self.assertEqual(len([m for m in a.hand if isinstance(m, Minion)]),
                         1)


class TestDeathwing(unittest.TestCase):
    """TB_BaconShop_HP_061 — SoC 双方全体 +2 攻（永久）。"""

    _GAIN = 2   # "+2 Attack"（文本字面量——与脚本 _ATK_GAIN 同源标注）

    def make(self):
        game = make_game(("TB_BaconShop_HERO_52", "TB_BaconShop_HERO_57"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_soc_buffs_both_boards_immediately(self):
        game, a, b = self.make()
        da = summon_plain(game, a, make_minion("DA", 3, 3))
        db = summon_plain(game, b, make_minion("DB", 3, 3))
        game._active_combat = (a, b)           # run() 内协议（soc 驱动等价）
        try:
            soc(game, a, b)
        finally:
            game._active_combat = None
        self.assertEqual((da.atk, db.atk), (3 + self._GAIN,
                                            3 + self._GAIN))

    def test_permanent_replay_after_combat(self):
        game, a, b = self.make()
        da = summon_plain(game, a, make_minion("DA", 3, 3))
        db = summon_plain(game, b, make_minion("DB", 0, 5))
        game.run_combat(a, b)
        # 战斗内 buff 已被快照回滚; combat_end（引擎 end_recruit_phase
        # 广播点）重放 → 永久
        self.assertEqual(da.atk, 3)
        fire_combat_end(game, a, b)
        self.assertEqual((da.atk, db.atk), (3 + self._GAIN,
                                            0 + self._GAIN))

    def test_stacks_each_combat(self):
        game, a, b = self.make()
        da = summon_plain(game, a, make_minion("DA", 3, 3))
        summon_plain(game, b, make_minion("DB", 0, 5))
        for _ in range(2):
            game.run_combat(a, b)
            fire_combat_end(game, a, b)
        self.assertEqual(da.atk, 3 + 2 * self._GAIN)

    def test_unrelated_pair_no_replay(self):
        game, a, b = self.make()
        da = summon_plain(game, a, make_minion("DA", 3, 3))
        c = Hero("TB_BaconShop_HERO_57", "C")
        game.heroes.append(c)
        try:
            fire_combat_end(game, b, c)        # 不含 Deathwing 的配对
        finally:
            game.heroes.remove(c)
        self.assertEqual(da.atk, 3)


class TestYsera(unittest.TestCase):
    """TB_BaconShop_HP_062 — 每次刷新馆内额外 +1 Dragon。"""

    def make(self):
        game = make_game(("TB_BaconShop_HERO_53", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def _dragons(self, hero):
        return [e for e in hero.tavern
                if isinstance(e, Minion)
                and e.race in (Race.DRAGON, Race.ALL)]

    def test_extra_dragon_appended_each_refresh(self):
        # 额外 Dragon 由监听器在 refresh_tavern 返回前 append——
        # 恒为馆内**最后一个**展示位（确定性识别，规避常规抽取随机性）
        game, a, _ = self.make()
        a.set(GameTag.TAVERN_TIER, 2)
        for _ in range(3):
            game.refresh_tavern(a, free=True)
            last = a.tavern[-1]
            self.assertIsInstance(last, Minion)
            self.assertIn(last.race, (Race.DRAGON, Race.ALL))
            self.assertLessEqual(
                get_db().get(last.card_id).tech_level, a.tavern_tier)
            self.assertGreater(len(a.tavern), 1)   # 非仅有注入位

    def test_dragon_occupies_pool(self):
        game, a, _ = self.make()
        dragons = [d.id for d in get_db().pool_minions()
                   if d.race in (Race.DRAGON, Race.ALL)]
        before = sum(game.minion_pool.available(c) for c in dragons)
        game.refresh_tavern(a, free=True)
        # 常规抽取 + 额外 1 只: 池内龙总量净减 ≥ 1（注入占池）
        after = sum(game.minion_pool.available(c) for c in dragons)
        self.assertGreaterEqual(before - after, 1)

    def test_enemy_refresh_no_extra_dragon(self):
        game, a, b = self.make()
        game.refresh_tavern(b, free=True)
        # b 无 Ysera: 刷新末位为法术展示（TAVERN_SPELLS_PER_REFRESH=1，
        # 追加顺序随从→法术——无被动注入）
        self.assertNotIsInstance(b.tavern[-1], Minion)
        self.assertEqual(a.tavern, [])


class TestRokara(unittest.TestCase):
    """BG20_HERO_100p — 友方随从击杀敌方 → +1 攻（永久）。"""

    _GAIN = 1   # "+1 Attack"（文本字面量——与脚本 _ATK_GAIN 同源标注）

    def make(self):
        game = make_game(("BG20_HERO_100", "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1]

    def test_kill_in_attack_buffs_killer_immediately(self):
        game, a, b = self.make()
        killer = summon_plain(game, a, make_minion("K", 3, 3))
        victim = summon_plain(game, b, make_minion("V", 0, 2))
        attack(game, killer, victim)
        self.assertTrue(victim.dead)
        self.assertEqual(killer.atk, 3 + self._GAIN)   # 击杀即时 +1

    def test_friendly_death_no_trigger(self):
        game, a, b = self.make()
        friendly = summon_plain(game, a, make_minion("F", 3, 3))
        foe = summon_plain(game, b, make_minion("E", 5, 5))
        attack(game, foe, friendly)            # 敌方击杀友方
        self.assertTrue(friendly.dead)
        self.assertEqual(foe.atk, 5)           # foe 非友方击杀者

    def test_permanent_replay_after_full_combat(self):
        game, a, b = self.make()
        killer = summon_plain(game, a, make_minion("K", 3, 3))
        summon_plain(game, b, make_minion("V", 0, 2))
        game.run_combat(a, b)                  # 全流程: 击杀→回滚
        self.assertEqual(killer.atk, 3)        # 战斗内 buff 已回滚
        fire_combat_end(game, a, b)
        self.assertEqual(killer.atk, 3 + self._GAIN)   # 重放永久

    def test_multiple_kills_replay_compound(self):
        game, a, b = self.make()
        killer = summon_plain(game, a, make_minion("K", 9, 9))
        summon_plain(game, b, make_minion("V1", 0, 2))
        summon_plain(game, b, make_minion("V2", 0, 2))
        game.run_combat(a, b)
        self.assertEqual(killer.atk, 9)
        fire_combat_end(game, a, b)
        self.assertEqual(killer.atk, 9 + 2 * self._GAIN)


class TestTheCurator(unittest.TestCase):
    """TB_BaconShop_HP_033 — 开局 2/2 Amalgam（Venomous/全种族）。"""

    def test_starts_with_amalgam(self):
        game = make_game(("TB_BaconShop_HERO_33", "TB_BaconShop_HERO_34"))
        a = game.heroes[0]
        bind(game, a)
        amalgam_def = get_db().get("TB_BaconShop_HP_033t")
        self.assertEqual(len(a.board), 1)
        m = a.board[0]
        self.assertEqual(m.card_id, "TB_BaconShop_HP_033t")
        self.assertEqual((m.atk, m.health),
                         (amalgam_def.atk, amalgam_def.health))
        self.assertTrue(m.has(GameTag.VENOMOUS))
        self.assertEqual(m.race, Race.ALL)

    def test_amalgam_not_from_pool(self):
        game = make_game(("TB_BaconShop_HERO_33", "TB_BaconShop_HERO_34"))
        a = game.heroes[0]
        avail = game.minion_pool.available("TB_BaconShop_HP_033t")
        bind(game, a)
        self.assertEqual(game.minion_pool.available("TB_BaconShop_HP_033t"),
                         avail)                # token 不占池


class TestPatchwerk(unittest.TestCase):
    """TB_BaconShop_HP_035 — 开局 +30 生命。"""

    def test_extra_health(self):
        game = make_game(("TB_BaconShop_HERO_34", "TB_BaconShop_HERO_33"))
        a = game.heroes[0]
        self.assertEqual(a.health, C.HERO_BASE_HEALTH)
        self.assertEqual(a.armor,
                         get_db().get("TB_BaconShop_HERO_34").armor)
        bind(game, a)
        self.assertEqual(a.health, C.HERO_BASE_HEALTH + 30)
        self.assertEqual(a.armor,
                         get_db().get("TB_BaconShop_HERO_34").armor)


if __name__ == "__main__":
    unittest.main()
