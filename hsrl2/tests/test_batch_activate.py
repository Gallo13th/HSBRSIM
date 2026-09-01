"""批次 activate 语义测试（作业单 2026-08-21，S14 Activate 池随从 14 张）。

驱动: game.use_activate(hero, minion)（扣费/每回合 1 次引擎保证）;
PendingChoice 断言 kind 与 resolve 语义; 数值期望一律 CardDef.num() /
activate_cost 计算。AMBIGUOUS/DEFERRED 卡断言**不在 REGISTRY**（防
误注册——语义未裁决前注册即违反二态纪律）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff as EntityBuff
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.pools import SpellPool
from hsrl2.scripts import REGISTRY, bind_all
from hsrl2.scripts.batches.batch_rally2 import CHROMADRAKE_IDS
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

BANANA_ID = "BG28_897"    # Tavern Dish Banana（evolution 数据链目标）
FISHBAIT_ID = "BG36_205"
FISHBAIT_GOLDEN_ID = "BG36_205_G"

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
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def stock_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    """往 hero 酒馆展示区放一张池随从（模拟 draw_tavern 结果）。"""
    assert game.minion_pool.acquire(card_id), f"pool empty for {card_id}"
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def stock_spell(game: Game, hero: Hero, card_id: str) -> Spell:
    """往 hero 酒馆展示区放一张池法术（模拟 draw_tavern 结果）。"""
    assert game.spell_pool.acquire(card_id), f"spell pool empty for {card_id}"
    s = game.create_spell(card_id, controller=hero)
    s.zone = Zone.TAVERN
    hero.tavern.append(s)
    return s


def activate(game: Game, hero: Hero, minion: Minion) -> bool:
    """付费激活并断言扣费正确（activate_cost 是 data 权威——本批
    存在 {0}/{1}/{2} 混排，费用索引逐卡不同，禁用 num(0) 惯例）。"""
    d = get_db().get(minion.card_id)
    gold_before = hero.gold
    ok = game.use_activate(hero, minion)
    assert ok, "use_activate should succeed"
    assert hero.gold == gold_before - d.activate_cost, (
        f"gold {hero.gold} != {gold_before} - {d.activate_cost}")
    return True


class TestLivingPrison(unittest.TestCase):
    """BG36_180 — Activate (1): Gain the stats of the next minion you
    buy this turn."""

    def test_activate_then_buy_gains_stats(self):
        game = make_game(seed=300)
        a, _ = game.heroes
        prison = put(game, "BG36_180", a)
        a.gold = 10
        activate(game, a, prison)
        self.assertEqual(prison.atk, 4)          # 未购买前无效果
        prey = stock_minion(game, a, "BG36_210")  # Hoarding Hyena
        prey_stats = (prey.atk, prey.max_health)
        self.assertTrue(game.buy_from_tavern(a, prey))
        self.assertEqual(prison.atk, 4 + prey_stats[0])
        self.assertEqual(prison.max_health, 5 + prey_stats[1])
        # 一次性: 再买不触发
        prey2 = stock_minion(game, a, "BG36_210")
        game.buy_from_tavern(a, prey2)
        self.assertEqual(prison.atk, 4 + prey_stats[0])

    def test_pending_expires_across_turns(self):
        game = make_game(seed=301)
        a, _ = game.heroes
        prison = put(game, "BG36_180", a)
        a.gold = 10
        activate(game, a, prison)
        game.turn += 1                            # "this turn" 过期
        prey = stock_minion(game, a, "BG36_210")
        game.buy_from_tavern(a, prey)
        self.assertEqual(prison.atk, 4)
        self.assertEqual(prison.max_health, 5)

    def test_buy_without_activate_no_effect(self):
        game = make_game(seed=302)
        a, _ = game.heroes
        prison = put(game, "BG36_180", a)
        a.gold = 10
        prey = stock_minion(game, a, "BG36_210")
        game.buy_from_tavern(a, prey)
        self.assertEqual(prison.atk, 4)
        self.assertEqual(prison.max_health, 5)

    def test_buying_spell_does_not_consume(self):
        game = make_game(seed=303)
        a, _ = game.heroes
        prison = put(game, "BG36_180", a)
        a.gold = 10
        activate(game, a, prison)
        s = stock_spell(game, a, "BG28_168")      # Shiny Ring
        game.buy_from_tavern(a, s)
        self.assertEqual(prison.atk, 4)           # "the next minion"

    def test_golden_gains_double(self):
        game = make_game(seed=304)
        a, _ = game.heroes
        prison = put(game, "BG36_180", a, golden=True)
        self.assertEqual(prison.card_id, "BG36_180_G")
        a.gold = 10
        activate(game, a, prison)
        prey = stock_minion(game, a, "BG36_210")
        game.buy_from_tavern(a, prey)
        d = get_db().get("BG36_210")
        self.assertEqual(prison.atk, 8 + 2 * d.atk)
        self.assertEqual(prison.max_health, 10 + 2 * d.health)


class TestLurkingLionfish(unittest.TestCase):
    """BG36_201 — Activate (2): Choose a card in the Tavern. Replace it
    with a Fishbait for your left-most Beast to attack."""

    def test_replace_minion_and_leftmost_beast_attacks(self):
        game = make_game(seed=310)
        a, _ = game.heroes
        # 棋盘: 另一野兽在左、Lionfish 在右——最左野兽≠Lionfish
        beast = make_minion("Beast", 2, 5, race=Race.BEAST)
        game.summon(a, beast)
        lionfish = put(game, "BG36_201", a)
        a.gold = 10
        pool_before = game.minion_pool.available("BG36_210")
        prey = stock_minion(game, a, "BG36_210")
        activate(game, a, lionfish)
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "tavern_pick")
        self.assertIn(prey, choice.options)
        choice.choose(choice.options.index(prey))
        # 被替换者回池（stock 占用 -1 → 释放 +1，净回到 stock 后水平）
        self.assertEqual(game.minion_pool.available("BG36_210"),
                         pool_before)
        self.assertNotIn(prey, a.tavern)
        # Fishbait 0/1 被 beast(2 攻) 击杀并从酒馆移除（不回池——token）
        self.assertEqual([m for m in a.tavern
                          if m.card_id == FISHBAIT_ID], [])
        self.assertEqual(beast.health, 5)         # Fishbait 0 攻无反伤
        self.assertEqual(beast.atk, 2)             # 攻击不改变自身属性

    def test_replace_spell_uses_spell_pool(self):
        game = make_game(seed=311)
        a, _ = game.heroes
        lionfish = put(game, "BG36_201", a)       # 自身即最左 Beast
        a.gold = 10
        s = stock_spell(game, a, "BG28_168")
        avail = game.spell_pool.available("BG28_168")   # 占 1 份后余量
        activate(game, a, lionfish)
        choice = game.pending_choices.pop(0)
        choice.choose(choice.options.index(s))
        self.assertEqual(game.spell_pool.available("BG28_168"),
                         avail + 1)               # 被替换法术回池
        self.assertEqual([m for m in a.tavern
                          if m.card_id == FISHBAIT_ID], [])  # 3 攻击杀 0/1

    def test_golden_replaces_with_golden_fishbait(self):
        game = make_game(seed=312)
        a, _ = game.heroes
        lionfish = put(game, "BG36_201", a, golden=True)
        a.gold = 10
        prey = stock_minion(game, a, "BG36_210")
        activate(game, a, lionfish)
        choice = game.pending_choices.pop(0)
        choice.choose(choice.options.index(prey))
        # 金色 Fishbait 0/2: 6 攻击杀; 金色 token 不回池（available 不变）
        self.assertEqual([m for m in a.tavern
                          if m.card_id == FISHBAIT_GOLDEN_ID], [])

    def test_empty_tavern_no_effect(self):
        game = make_game(seed=313)
        a, _ = game.heroes
        lionfish = put(game, "BG36_201", a)
        a.gold = 10
        gold_before = a.gold
        self.assertTrue(game.use_activate(a, lionfish))  # 费用已扣
        self.assertEqual(a.gold, gold_before - 2)
        self.assertEqual(game.pending_choices, [])


class TestHiredMount(unittest.TestCase):
    """BG36_240 — Activate (2): Get a random Chromadrake."""

    def test_activate_gets_one_chromadrake(self):
        game = make_game(seed=320)
        a, _ = game.heroes
        mount = put(game, "BG36_240", a)
        a.gold = 10
        activate(game, a, mount)
        got = [c for c in a.hand if c.card_id in CHROMADRAKE_IDS]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].zone, Zone.HAND)

    def test_golden_gets_two(self):
        game = make_game(seed=321)
        a, _ = game.heroes
        mount = put(game, "BG36_240", a, golden=True)
        a.gold = 10
        activate(game, a, mount)
        self.assertEqual(
            len([c for c in a.hand if c.card_id in CHROMADRAKE_IDS]), 2)


class TestCleverCastaway(unittest.TestCase):
    """BG36_342 — Activate (2): Discover a Tavern spell."""

    def test_activate_discovers_tavern_spell(self):
        game = make_game(seed=330)
        a, _ = game.heroes
        castaway = put(game, "BG36_342", a)
        a.gold = 10
        activate(game, a, castaway)
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "discover_spell")
        pool_ids = {d.id for d in get_db().pool_spells()}
        self.assertTrue(set(choice.options) <= pool_ids)
        for opt in choice.options:
            tier = get_db().get(opt).tech_level
            self.assertEqual(game.spell_pool.available(opt),
                             SpellPool.POOL_COPIES_BY_TIER[tier])  # 未选不占
        pick_id = choice.options[0]
        avail_pick = game.spell_pool.available(pick_id)
        choice.choose(0)
        self.assertEqual(game.spell_pool.available(pick_id),
                         avail_pick - 1)  # 占池
        self.assertEqual(
            [c.card_id for c in a.hand if c.card_id == pick_id], [pick_id])

    def test_golden_discovers_two_queued(self):
        game = make_game(seed=331)
        a, _ = game.heroes
        castaway = put(game, "BG36_342", a, golden=True)
        a.gold = 10
        activate(game, a, castaway)
        self.assertEqual(len(game.pending_choices), 2)   # 队列化
        c1 = game.pending_choices.pop(0)
        c2 = game.pending_choices.pop(0)
        self.assertEqual(c1.kind, c2.kind, "discover_spell")
        c1.choose(0)
        c2.choose(0)
        self.assertEqual(len(a.hand), 2)

    def test_spell_pool_exhausted_no_choice(self):
        game = make_game(seed=332)
        a, _ = game.heroes
        castaway = put(game, "BG36_342", a)
        for d in get_db().pool_spells():
            while game.spell_pool.available(d.id):   # 抽干（per-tier 副本）
                assert game.spell_pool.acquire(d.id)
        a.gold = 10
        self.assertTrue(game.use_activate(a, castaway))  # 费用已扣
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(a.hand, [])


class TestFruitVendor(unittest.TestCase):
    """BG36_346 — Activate (1): Get {1} Tavern Dish Bananas."""

    def test_activate_gets_bananas(self):
        game = make_game(seed=340)
        a, _ = game.heroes
        vendor = put(game, "BG36_346", a)
        d = get_db().get("BG36_346")
        a.gold = 10
        avail = game.spell_pool.available(BANANA_ID)
        activate(game, a, vendor)
        bananas = [c for c in a.hand if c.card_id == BANANA_ID]
        self.assertEqual(len(bananas), d.num(1))
        self.assertEqual(game.spell_pool.available(BANANA_ID),
                         avail - d.num(1))      # 每份占 1 份池
        self.assertEqual(bananas[0].zone, Zone.HAND)

    def test_golden_gets_four(self):
        game = make_game(seed=341)
        a, _ = game.heroes
        vendor = put(game, "BG36_346", a, golden=True)
        d = get_db().get("BG36_346_G")
        self.assertEqual(d.num(1), 4)
        a.gold = 10
        activate(game, a, vendor)
        self.assertEqual(
            len([c for c in a.hand if c.card_id == BANANA_ID]), 4)

    def test_banana_pool_exhausted_still_grants(self):
        """池已抽干 → 余份生成为净增（Mystic Essence 先例，
        官方 "Get {1}" 恒给满）。"""
        game = make_game(seed=342)
        a = game.heroes[0]
        vendor = put(game, "BG36_346", a)
        while game.spell_pool.available(BANANA_ID):   # 抽干香蕉池
            assert game.spell_pool.acquire(BANANA_ID)
        a.gold = 10
        self.assertTrue(game.use_activate(a, vendor))
        self.assertEqual(
            len([c for c in a.hand if c.card_id == BANANA_ID]),
            get_db().get("BG36_346").num(1))


class TestDecoyConjurer(unittest.TestCase):
    """BG36_354 — Activate (2): Steal the highest-Attack minion in the
    Tavern."""

    def test_steals_highest_attack_entity_transfer(self):
        game = make_game(seed=350)
        a, _ = game.heroes
        conjurer = put(game, "BG36_354", a)
        a.gold = 10
        low = make_minion("Low", 1, 5)
        low.zone = Zone.TAVERN
        a.tavern.append(low)
        high = make_minion("High", 5, 5)
        high.zone = Zone.TAVERN
        a.tavern.append(high)
        mid = make_minion("Mid", 3, 5)
        mid.zone = Zone.TAVERN
        a.tavern.append(mid)
        activate(game, a, conjurer)
        self.assertEqual(len(a.hand), 1)
        self.assertIs(a.hand[0], high)          # 实体转移（同一对象）
        self.assertNotIn(high, a.tavern)
        self.assertEqual(a.tavern, [low, mid])

    def test_golden_steals_top_two(self):
        game = make_game(seed=351)
        a, _ = game.heroes
        conjurer = put(game, "BG36_354", a, golden=True)
        a.gold = 10
        low = make_minion("Low", 1, 5)
        mid = make_minion("Mid", 3, 5)
        high = make_minion("High", 5, 5)
        for m in (low, mid, high):
            m.zone = Zone.TAVERN
            a.tavern.append(m)
        activate(game, a, conjurer)
        self.assertEqual(len(a.hand), 2)
        self.assertIn(high, a.hand)
        self.assertIn(mid, a.hand)
        self.assertEqual(a.tavern, [low])

    def test_no_minions_in_tavern_no_effect(self):
        game = make_game(seed=352)
        a, _ = game.heroes
        conjurer = put(game, "BG36_354", a)
        a.gold = 10
        stock_spell(game, a, "BG28_168")        # 法术不可偷
        self.assertTrue(game.use_activate(a, conjurer))
        self.assertEqual(a.hand, [])
        self.assertEqual(len(a.tavern), 1)


class TestSoulkeepingJailer(unittest.TestCase):
    """BG36_503 — Activate (2): Your Demons each consume a random minion
    in the Tavern to gain its stats."""

    def _setup(self, seed):
        game = make_game(seed=seed)
        a, _ = game.heroes
        jailer = put(game, "BG36_503", a)       # 3/5 Demon——含自身
        demon = make_minion("Demon", 1, 1, race=Race.DEMON)
        game.summon(a, demon)
        t1 = stock_minion(game, a, "BG36_210")  # 2/3
        t2 = stock_minion(game, a, "BG36_210")
        return game, a, jailer, demon, [t1, t2]

    def test_each_demon_consumes_one(self):
        game, a, jailer, demon, victims = self._setup(360)
        pool_before = game.minion_pool.available("BG36_210")
        a.gold = 10
        activate(game, a, jailer)
        d = get_db().get("BG36_210")
        # 两个 Demon（Jailer 自身 + 手下）各吞 1: 各 +2/+3
        self.assertEqual(jailer.atk, 3 + d.atk)
        self.assertEqual(jailer.max_health, 5 + d.health)
        self.assertEqual(demon.atk, 1 + d.atk)
        self.assertEqual(demon.max_health, 1 + d.health)
        self.assertEqual(a.tavern, [])           # 受害者移除
        # 池记账: stock 抽取占池 -2 → 消耗回池 +2 = 净回到 stock 前水平
        self.assertEqual(game.minion_pool.available("BG36_210"),
                         pool_before + 2)
        self.assertEqual(a.hand, [])             # 吞噬≠获取

    def test_golden_double_stats(self):
        game, a, jailer, demon, victims = self._setup(361)
        golden = put(game, "BG36_503", a, golden=True)
        game.sell_minion(a, jailer)              # 保持恶魔数=2
        a.gold = 10
        activate(game, a, golden)
        d = get_db().get("BG36_210")
        self.assertEqual(golden.atk, 6 + 2 * d.atk)
        self.assertEqual(golden.max_health, 10 + 2 * d.health)
        self.assertEqual(a.tavern, [])

    def test_empty_tavern_no_effect(self):
        game = make_game(seed=362)
        a, _ = game.heroes
        jailer = put(game, "BG36_503", a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, jailer))
        self.assertEqual(jailer.atk, 3)
        self.assertEqual(a.tavern, [])


class TestDroneDuplicator(unittest.TestCase):
    """BG36_506 — Divine Shield; Activate (1): The next Magnetization to
    this minion this turn is doubled."""

    MAG_A = "BG26_147"   # Accord-o-Tron 3/3 磁力机械（data 权威）
    MAG_B = "BG26_146"   # Lullabot 2/2 磁力机械

    def _magnetize(self, game, hero, card_id):
        m = game.create_minion(card_id, controller=hero)
        hero.hand.append(m)
        return m

    def test_activate_doubles_next_magnetization(self):
        game = make_game(seed=370)
        a, _ = game.heroes
        drone = put(game, "BG36_506", a)
        a.gold = 10
        activate(game, a, drone)
        mag = self._magnetize(game, a, self.MAG_A)     # 3/3
        self.assertTrue(game.play_minion(a, mag, magnetic_target=drone))
        # 5/2 基础 + 3/3 并入 + 3/3 追加 = 11/8
        self.assertEqual(drone.atk, 5 + 3 * 2)
        self.assertEqual(drone.max_health, 2 + 3 * 2)

    def test_without_activate_single(self):
        game = make_game(seed=371)
        a, _ = game.heroes
        drone = put(game, "BG36_506", a)
        mag = self._magnetize(game, a, self.MAG_A)
        game.play_minion(a, mag, magnetic_target=drone)
        self.assertEqual(drone.atk, 5 + 3)
        self.assertEqual(drone.max_health, 2 + 3)

    def test_doubling_is_once_per_activation(self):
        game = make_game(seed=372)
        a, _ = game.heroes
        drone = put(game, "BG36_506", a)
        a.gold = 10
        activate(game, a, drone)
        mag1 = self._magnetize(game, a, self.MAG_A)    # 3/3 → ×2
        game.play_minion(a, mag1, magnetic_target=drone)
        mag2 = self._magnetize(game, a, self.MAG_B)    # 2/2 → 不翻倍
        game.play_minion(a, mag2, magnetic_target=drone)
        self.assertEqual(drone.atk, 5 + 3 * 2 + 2)
        self.assertEqual(drone.max_health, 2 + 3 * 2 + 2)

    def test_doubling_expires_next_turn(self):
        game = make_game(seed=373)
        a, _ = game.heroes
        drone = put(game, "BG36_506", a)
        a.gold = 10
        activate(game, a, drone)
        game.turn += 1                            # "this turn" 过期
        mag = self._magnetize(game, a, self.MAG_A)
        game.play_minion(a, mag, magnetic_target=drone)
        self.assertEqual(drone.atk, 5 + 3)

    def test_golden_triples(self):
        game = make_game(seed=374)
        a, _ = game.heroes
        drone = put(game, "BG36_506", a, golden=True)
        a.gold = 10
        activate(game, a, drone)
        mag = self._magnetize(game, a, self.MAG_A)     # 3/3
        game.play_minion(a, mag, magnetic_target=drone)
        self.assertEqual(drone.atk, 10 + 3 * 3)
        self.assertEqual(drone.max_health, 4 + 3 * 3)


class TestBreakoutMastermind(unittest.TestCase):
    """BG36_507 — Activate (2): Get a random Murloc."""

    def test_activate_gets_random_murloc(self):
        game = make_game(seed=380)
        a, _ = game.heroes
        mind = put(game, "BG36_507", a)
        a.gold = 10
        murloc_ids = {d.id for d in get_db().pool_minions()
                      if d.race in (Race.MURLOC, Race.ALL)}
        activate(game, a, mind)
        self.assertEqual(len(a.hand), 1)
        got = a.hand[0]
        self.assertIn(got.card_id, murloc_ids)
        self.assertEqual(got.zone, Zone.HAND)

    def test_golden_gets_two(self):
        game = make_game(seed=381)
        a, _ = game.heroes
        mind = put(game, "BG36_507", a, golden=True)
        a.gold = 10
        activate(game, a, mind)
        self.assertEqual(len(a.hand), 2)
        for c in a.hand:
            self.assertIn(
                c.card_id,
                {d.id for d in get_db().pool_minions()
                 if d.race in (Race.MURLOC, Race.ALL)})


class TestDeadBellringer(unittest.TestCase):
    """BG36_511 — Activate (1): Give a different friendly Undead Reborn.
    Then destroy it to gain +{1}/+{2}."""

    def test_gives_reborn_destroys_and_reborn_revives(self):
        game = make_game(seed=390)
        a, _ = game.heroes
        bell = put(game, "BG36_511", a)
        undead = make_minion("Undead", 2, 5, race=Race.UNDEAD)
        undead.add_buff(EntityBuff(atk=1, health=1))  # 带 buff 验证复生保留
        game.summon(a, undead)
        a.gold = 10
        d = get_db().get("BG36_511")
        activate(game, a, bell)
        # Bellringer +4/+4
        self.assertEqual(bell.atk, 3 + d.num(1))
        self.assertEqual(bell.max_health, 6 + d.num(2))
        # 目标: 死亡→复生（1 血、原位、保留 buff、Reborn 已耗）
        self.assertIn(undead, a.board)
        self.assertFalse(undead.has(GameTag.REBORN))
        self.assertEqual(undead.health, 1)
        self.assertEqual(undead.atk, 3)           # 2+1 buff 保留
        self.assertEqual(undead.max_health, 6)

    def test_no_other_undead_no_effect(self):
        game = make_game(seed=391)
        a, _ = game.heroes
        bell = put(game, "BG36_511", a)           # 自身是 Undead 但须 different
        mech = make_minion("Mech", 2, 5, race=Race.MECH)
        game.summon(a, mech)
        a.gold = 10
        self.assertTrue(game.use_activate(a, bell))
        self.assertEqual(bell.atk, 3)
        self.assertEqual(bell.max_health, 6)
        self.assertFalse(mech.has(GameTag.REBORN))

    def test_golden_gains_8_8(self):
        game = make_game(seed=392)
        a, _ = game.heroes
        bell = put(game, "BG36_511", a, golden=True)
        undead = make_minion("Undead", 2, 5, race=Race.UNDEAD)
        game.summon(a, undead)
        a.gold = 10
        activate(game, a, bell)
        d = get_db().get("BG36_511_G")
        self.assertEqual(bell.atk, 6 + d.num(1))
        self.assertEqual(bell.max_health, 12 + d.num(2))
        self.assertIn(undead, a.board)
        self.assertEqual(undead.health, 1)


class TestAmbiguousAndDeferred(unittest.TestCase):
    """AMBIGUOUS/DEFERRED 卡禁止注册——语义裁决前注册违反二态纪律。"""

    def test_ambiguous_cards_resolved_and_registered(self):
        # 2026-08-21 主线/后续批次裁决与解冻:
        # Prisonguard wiki [Targeted]（主线查证）; Tyrael/Deft Deserter
        # 由 batch_misc 查 wiki 裁决后实现——已注册
        for cid in ("BG36_345", "BG36_356", "BG36_621"):
            self.assertIn(cid, REGISTRY)

    def test_cagey_conjurer_unfrozen(self):
        # 2026-08-22 batch_unfreeze 解冻: BG36_508 Cagey Conjurer
        # （spell_resolving 直施原语 + 注册法术 49/75 ≥20 阈值）
        for cid in ("BG36_508", "BG36_508_G"):
            self.assertIn(cid, REGISTRY)
            self.assertTrue(hasattr(REGISTRY[cid], "activate"))

    def test_registered_cards_have_activate_hook(self):
        for cid in ("BG36_180", "BG36_180_G", "BG36_201", "BG36_201_G",
                    "BG36_240", "BG36_240_G", "BG36_342", "BG36_342_G",
                    "BG36_346", "BG36_346_G", "BG36_354", "BG36_354_G",
                    "BG36_503", "BG36_503_G", "BG36_506", "BG36_506_G",
                    "BG36_507", "BG36_507_G", "BG36_511", "BG36_511_G"):
            self.assertIn(cid, REGISTRY, f"{cid} should be registered")
            self.assertTrue(hasattr(REGISTRY[cid], "activate"))
            # data 契约: 注册卡全部带 activate 标志
            self.assertIsNotNone(get_db().get(cid).activate_cost)


class TestParamIntegrity(unittest.TestCase):
    """数值索引逐卡打印核对（作业单红线: 本批 {0}/{1}/{2} 混排）。"""

    def test_placeholder_mapping_matches_data(self):
        db = get_db()
        # Activate ({N}) 占位符值必须与 activate_cost 一致
        for cid, cost_idx in (("BG36_180", 0), ("BG36_201", 0),
                              ("BG36_240", 0), ("BG36_342", 0),
                              ("BG36_346", 0), ("BG36_354", 0),
                              ("BG36_356", 0), ("BG36_503", 0),
                              ("BG36_506", 0), ("BG36_507", 0),
                              ("BG36_508", 0), ("BG36_511", 0),
                              ("BG36_621", 0), ("BG36_345", 2)):
            d = db.get(cid)
            self.assertEqual(
                d.num(cost_idx), d.activate_cost,
                f"{cid}: placeholder {{{cost_idx}}}={d.num(cost_idx)} "
                f"!= activate_cost {d.activate_cost}")
        # 混排特例逐卡断言（36.2.2 基线）
        self.assertEqual((db.get("BG36_345").num(0),
                          db.get("BG36_345").num(1)), (3, 3))
        self.assertEqual((db.get("BG36_356").num(1),
                          db.get("BG36_356").num(2)), (50, 50))
        self.assertEqual((db.get("BG36_511").num(1),
                          db.get("BG36_511").num(2)), (4, 4))
        self.assertEqual((db.get("BG36_621").num(1),
                          db.get("BG36_621").num(2)), (8, 8))
        self.assertEqual(db.get("BG36_346").num(1), 2)
        self.assertEqual(db.get("BG36_508").num(1), 2)


if __name__ == "__main__":
    bind_all(get_db())
    unittest.main()
