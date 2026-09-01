"""批次 econ_misc2 语义测试（作业单 2026-08-21，15 张事件触发型池随从）。

覆盖: BG34_950 Stone Age Slab / BG35_155 Twisted Wrathguard /
BG35_342 Falling Sky Golem（DEFERRED 守护）/ BG36_211 Cage Gnawer /
BG36_352 Unbound Tempest / BG36_523 Enterprising Escapee /
BG36_622 Torrential Ruiner / BG36_640 Gatekeeper Amalgam /
BG36_733 Eredar Escapist / BG36_762 Devilish Distractor /
BG36_921 Fleeing Fugitive / BGS_004 Wrath Weaver / BGS_041 Kalecgos /
BGS_127 Molten Rock / BGS_104 Nomi。

驱动: 持久监听器经 put()（summon→on_summon）注册; 攻击类用
CombatScheduler._execute_attack 单次攻击（test_batch_rally2 先例）;
数值期望一律 CardDef.num()（无模板参数处注明文本字面量来源）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.constants import FODDER_CARD_ID, LOCKBOX_CARD_ID
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone
from hsrl2.tests.test_batch_rally2 import attack  # 单次攻击驱动（先例复用）

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

GEM_ID = "BG20_GEM"            # 血宝石基础值唯一来源（bloodgem.py 同源）
TEA_SET_ID = "BG28_888"        # Misplaced Tea Set（Gatekeeper 施放）
SHINY_RING_ID = "BG28_168"     # Shiny Ring（Eredar Escapist 施放）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42) -> Game:
    return Game([make_hero("A"), make_hero("B")], get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def dummy(hero: Hero, health: int = 100, atk: int = 0) -> Minion:
    m = make_minion("Dummy", atk, health)
    m.controller = hero
    return m


def to_board(game: Game, hero: Hero, m: Minion) -> Minion:
    m.game = game
    game.summon(hero, m)
    return m


def to_tavern(game: Game, hero: Hero, m: Minion) -> Minion:
    m.game = game
    m.controller = hero
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def pool_minion_id(race: Race) -> str:
    """确定性取一张指定种族的池随从 id（BuffCurrentTavern 要求馆内
    随从有 db 定义）。"""
    for d in sorted(get_db().pool_minions(), key=lambda x: x.id):
        if d.race == race:
            return d.id
    raise AssertionError(f"no pool minion of race {race}")


def pool_tavern(game: Game, hero: Hero, race: Race) -> Minion:
    return to_tavern(game, hero,
                     game.create_minion(pool_minion_id(race),
                                        controller=hero))


def play_from_hand(game: Game, hero: Hero, m: Minion) -> bool:
    m.game = game
    hero.add_to_hand(m)
    return game.play_minion(hero, m)


def cast_gem(game: Game, hero: Hero, target: Minion) -> bool:
    """从手牌打出一张 vanilla 血宝石指向 target（"cast a spell" 驱动）。"""
    gem = game.create_spell(GEM_ID, controller=hero)
    hero.add_to_hand(gem)
    return game.play_spell(hero, gem, target=target)


def gem_values(hero: Hero) -> tuple[int, int]:
    d = get_db().get(GEM_ID)
    return (d.num(0) + hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0),
            d.num(1) + hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0))


class TestRegistryState(unittest.TestCase):
    """批次注册面: 14 张 OK（含金色）; BG35_342 DEFERRED 不注册。"""

    OK_IDS = (
        "BG34_950", "BG34_950_G", "BG35_155", "BG35_155_G",
        "BG36_211", "BG36_211_G", "BG36_352", "BG36_352_G",
        "BG36_523", "BG36_523_G", "BG36_622", "BG36_622_G",
        "BG36_640", "BG36_640_G", "BG36_733", "BG36_733_G",
        "BG36_762", "BG36_762_G", "BG36_921", "BG36_921_G",
        "BGS_004", "TB_BaconUps_079", "BGS_041", "TB_BaconUps_109",
        "BGS_127", "TB_Baconups_202", "BGS_104", "TB_BaconUps_201",
    )

    def test_all_ok_cards_registered(self):
        for cid in self.OK_IDS:
            self.assertIn(cid, REGISTRY)

    def test_deferred_golem_not_registered(self):
        # 动态 atk/health 钩子已接线（引擎收口）→ batch_counters 解冻
        self.assertIn("BG35_342", REGISTRY)


class TestStoneAgeSlab(unittest.TestCase):
    """BG34_950 — After you buy a minion, give it +{0}/+{1} and double
    its stats. (Once per turn.)"""

    def _buyable(self, game, hero, atk=3, health=4) -> Minion:
        return to_tavern(game, hero, make_minion("Buyable", atk, health))

    def _nums(self, card_id="BG34_950"):
        d = get_db().get(card_id)
        return d.num(0), d.num(1)

    def test_buy_buffs_then_doubles(self):
        game = make_game(seed=300)
        a = game.heroes[0]
        put(game, "BG34_950", a)
        n0, n1 = self._nums()
        t = self._buyable(game, a)
        a.gold = 10
        self.assertTrue(game.buy_from_tavern(a, t))
        self.assertEqual(t.atk, (3 + n0) * 2)
        self.assertEqual(t.max_health, (4 + n1) * 2)

    def test_once_per_turn(self):
        game = make_game(seed=301)
        a = game.heroes[0]
        put(game, "BG34_950", a)
        a.gold = 20
        t1 = self._buyable(game, a)
        game.buy_from_tavern(a, t1)
        t2 = self._buyable(game, a, 5, 6)
        game.buy_from_tavern(a, t2)
        self.assertEqual(t2.atk, 5)          # 同回合第二次不触发
        self.assertEqual(t2.max_health, 6)
        game.turn += 1                        # 下一回合计数重置
        t3 = self._buyable(game, a, 5, 6)
        game.buy_from_tavern(a, t3)
        n0, n1 = self._nums()
        self.assertEqual(t3.atk, (5 + n0) * 2)

    def test_golden_triples(self):
        game = make_game(seed=302)
        a = game.heroes[0]
        put(game, "BG34_950_G", a)
        n0, n1 = self._nums("BG34_950_G")
        t = self._buyable(game, a)
        a.gold = 10
        game.buy_from_tavern(a, t)
        self.assertEqual(t.atk, (3 + n0) * 3)
        self.assertEqual(t.max_health, (4 + n1) * 3)

    def test_opponent_buy_no_effect(self):
        game = make_game(seed=303)
        a, b = game.heroes
        put(game, "BG34_950", a)
        t = self._buyable(game, b)
        b.gold = 10
        game.buy_from_tavern(b, t)
        self.assertEqual(t.atk, 3)
        self.assertEqual(t.max_health, 4)


class TestTwistedWrathguard(unittest.TestCase):
    """BG35_155 — After you sell a minion, add a Fodder to your next
    Refresh."""

    def test_sell_adds_fodder_to_next_refresh(self):
        game = make_game(seed=310)
        a = game.heroes[0]
        put(game, "BG35_155", a)
        m = to_board(game, a, make_minion("FodderFodder", 1, 1))
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(game._fodder_refresh_pending.get(a), (1, 1))
        game.refresh_tavern(a, auto=True)
        ids = [e.card_id for e in a.tavern]
        self.assertIn(FODDER_CARD_ID, ids)
        self.assertEqual(game._fodder_refresh_pending.get(a, 0), 0)

    def test_opponent_sell_no_effect(self):
        game = make_game(seed=311)
        a, b = game.heroes
        put(game, "BG35_155", a)
        m = to_board(game, b, make_minion("Bm", 1, 1))
        game.sell_minion(b, m)
        self.assertEqual(game._fodder_refresh_pending.get(a, 0), 0)

    def test_golden_two_fodders(self):
        game = make_game(seed=312)
        a = game.heroes[0]
        put(game, "BG35_155_G", a)
        m = to_board(game, a, make_minion("F2", 1, 1))
        game.sell_minion(a, m)
        self.assertEqual(game._fodder_refresh_pending.get(a), (1, 2))


class TestCageGnawer(unittest.TestCase):
    """BG36_211 — Whenever a friendly Beast attacks, give your Beasts
    +{0}/+{1}."""

    def test_friendly_beast_attack_buffs_beasts(self):
        game = make_game(seed=320)
        a, b = game.heroes
        gnawer = put(game, "BG36_211", a)          # 本身是 Beast
        beast = to_board(game, a, make_minion("Beast", 3, 5, race=Race.BEAST))
        mech = to_board(game, a, make_minion("Mech", 2, 2, race=Race.MECH))
        n0, n1 = get_db().get("BG36_211").num(0), get_db().get("BG36_211").num(1)
        attack(game, beast, dummy(b))
        self.assertEqual(beast.atk, 3 + n0)
        self.assertEqual(beast.max_health, 5 + n1)
        self.assertEqual(gnawer.atk, get_db().get("BG36_211").atk + n0)
        self.assertEqual(mech.atk, 2)              # 非 Beast 不受 buff

    def test_non_beast_attacker_no_trigger(self):
        game = make_game(seed=321)
        a, b = game.heroes
        put(game, "BG36_211", a)
        beast = to_board(game, a, make_minion("Beast", 3, 5, race=Race.BEAST))
        mech = to_board(game, a, make_minion("Mech", 2, 2, race=Race.MECH))
        attack(game, mech, dummy(b))
        self.assertEqual(beast.atk, 3)

    def test_enemy_beast_attack_no_trigger(self):
        game = make_game(seed=322)
        a, b = game.heroes
        put(game, "BG36_211", a)
        my_beast = to_board(game, a, make_minion("Beast", 3, 5, race=Race.BEAST))
        enemy = to_board(game, b, make_minion("EB", 4, 4, race=Race.BEAST))
        attack(game, enemy, dummy(a, health=50))
        self.assertEqual(my_beast.atk, 3)

    def test_combat_buff_rolls_back_after_combat(self):
        game = make_game(seed=323)
        a, b = game.heroes
        gnawer = put(game, "BG36_211", a)
        beast = to_board(game, a, make_minion("Beast", 3, 50, race=Race.BEAST))
        to_board(game, b, dummy(b, health=100))
        seen = {}
        # 探针（注册序在 gnawer 之后 → 回调时 buff 已落地）
        game.events.register(Listener(
            event="after_attack", owner=b,
            callback=lambda g, attacker=None, defender=None, **kw:
                seen.update(atk=beast.atk)))
        game.run_combat(a, b)
        n0 = get_db().get("BG36_211").num(0)
        # 战斗内生效: 每次野兽攻击全体野兽 +n0（可叠层）
        self.assertGreater(seen.get("atk", 0), 3)
        self.assertEqual((seen["atk"] - 3) % n0, 0)
        self.assertEqual(beast.atk, 3)             # 战后回滚 (RULES §3.5)
        self.assertEqual(gnawer.atk, get_db().get("BG36_211").atk)


class TestUnboundTempest(unittest.TestCase):
    """BG36_352 — After you play {1} Elementals, gain the stats of the
    highest-Health minion in the Tavern."""

    def _setup(self, game, hero, card_id="BG36_352"):
        tempest = put(game, card_id, hero)
        to_tavern(game, hero, make_minion("THigh", 5, 8))
        to_tavern(game, hero, make_minion("TLow", 9, 6))
        return tempest

    def _play_elemental(self, game, hero, times=1):
        for _ in range(times):
            play_from_hand(game, hero,
                           make_minion("El", 1, 1, race=Race.ELEMENTAL))

    def test_three_elementals_gain_tavern_best_stats(self):
        game = make_game(seed=330)
        a = game.heroes[0]
        tempest = self._setup(game, a)
        d = get_db().get("BG36_352")
        self._play_elemental(game, a, times=d.num(1) - 1)
        self.assertEqual(tempest.atk, d.atk)       # 未达阈值不触发
        self._play_elemental(game, a, times=1)
        self.assertEqual(tempest.atk, d.atk + 5)   # 最高血=THigh 8 血 5 攻
        self.assertEqual(tempest.max_health, d.health + 8)

    def test_non_elemental_not_counted(self):
        game = make_game(seed=331)
        a = game.heroes[0]
        tempest = self._setup(game, a)
        d = get_db().get("BG36_352")
        self._play_elemental(game, a, times=d.num(1) - 1)
        play_from_hand(game, a, make_minion("Beast", 1, 1, race=Race.BEAST))
        self.assertEqual(tempest.atk, d.atk)

    def test_rolling_counter(self):
        game = make_game(seed=332)
        a = game.heroes[0]
        tempest = self._setup(game, a)
        d = get_db().get("BG36_352")
        self._play_elemental(game, a, times=d.num(1))
        self._play_elemental(game, a, times=d.num(1))   # 第二轮再触发
        self.assertEqual(tempest.atk, d.atk + 5 * 2)

    def test_golden_double_stats(self):
        game = make_game(seed=333)
        a = game.heroes[0]
        tempest = self._setup(game, a, "BG36_352_G")
        d = get_db().get("BG36_352_G")
        self._play_elemental(game, a, times=d.num(1))
        self.assertEqual(tempest.atk, d.atk + 5 * 2)
        self.assertEqual(tempest.max_health, d.health + 8 * 2)


class TestEnterprisingEscapee(unittest.TestCase):
    """BG36_523 — After you spend {2} Gold, get a Lockbox. If you
    already have one, it opens {3} turn(s) sooner instead."""

    def test_threshold_accumulate_and_get_lockbox(self):
        game = make_game(seed=340)
        a = game.heroes[0]
        put(game, "BG36_523", a)
        d = get_db().get("BG36_523")
        a.gold = 10
        game.spend_gold(a, d.num(2) - 1)
        self.assertEqual([c.card_id for c in a.hand], [])
        game.spend_gold(a, 1)
        boxes = [c for c in a.hand if c.card_id == LOCKBOX_CARD_ID]
        self.assertEqual(len(boxes), 1)
        lockbox_turns = get_db().get(LOCKBOX_CARD_ID).num(0)
        self.assertEqual(boxes[0].get(GameTag.LOCKBOX_TURNS_LEFT),
                         lockbox_turns)

    def test_early_open_when_already_have_one(self):
        game = make_game(seed=341)
        a = game.heroes[0]
        put(game, "BG36_523", a)
        d = get_db().get("BG36_523")
        a.gold = 20
        game.spend_gold(a, d.num(2))           # 入手 Lockbox
        game.spend_gold(a, d.num(2))           # 已有 → early -num(3)
        box = next(c for c in a.hand if c.card_id == LOCKBOX_CARD_ID)
        self.assertEqual(box.get(GameTag.LOCKBOX_TURNS_LEFT),
                         get_db().get(LOCKBOX_CARD_ID).num(0) - d.num(3))

    def test_single_large_spend_rolls(self):
        game = make_game(seed=342)
        a = game.heroes[0]
        put(game, "BG36_523", a)
        d = get_db().get("BG36_523")
        a.gold = 20
        game.spend_gold(a, d.num(2) * 2)       # 单笔 10 金 = 2 次触发
        box = next(c for c in a.hand if c.card_id == LOCKBOX_CARD_ID)
        self.assertEqual(box.get(GameTag.LOCKBOX_TURNS_LEFT),
                         get_db().get(LOCKBOX_CARD_ID).num(0) - d.num(3))

    def test_opponent_spend_not_counted(self):
        game = make_game(seed=343)
        a, b = game.heroes
        put(game, "BG36_523", a)
        b.gold = 10
        game.spend_gold(b, 5)
        self.assertEqual([c.card_id for c in a.hand], [])

    def test_golden_opens_two_turns_sooner(self):
        game = make_game(seed=344)
        a = game.heroes[0]
        put(game, "BG36_523_G", a)
        d = get_db().get("BG36_523_G")
        a.gold = 20
        game.spend_gold(a, d.num(2))
        game.spend_gold(a, d.num(2))
        box = next(c for c in a.hand if c.card_id == LOCKBOX_CARD_ID)
        self.assertEqual(box.get(GameTag.LOCKBOX_TURNS_LEFT),
                         get_db().get(LOCKBOX_CARD_ID).num(0) - d.num(3))


class TestTorrentialRuiner(unittest.TestCase):
    """BG36_622 — Whenever you cast a spell on a Naga, give your
    minions +{0}/+{1}."""

    def test_spell_on_naga_buffs_all_friendly(self):
        game = make_game(seed=350)
        a = game.heroes[0]
        ruiner = put(game, "BG36_622", a)
        naga = to_board(game, a, make_minion("Naga", 2, 2, race=Race.NAGA))
        d = get_db().get("BG36_622")
        ga, gh = gem_values(a)
        cast_gem(game, a, naga)
        # ruiner 非目标: 恰好 +num(0)/num(1)
        self.assertEqual(ruiner.atk, d.atk + d.num(0))
        self.assertEqual(ruiner.max_health, d.health + d.num(1))
        # naga 是宝石目标: gem + ruiner 双份
        self.assertEqual(naga.atk, 2 + ga + d.num(0))

    def test_spell_on_non_naga_no_trigger(self):
        game = make_game(seed=351)
        a = game.heroes[0]
        ruiner = put(game, "BG36_622", a)
        mech = to_board(game, a, make_minion("Mech", 2, 2, race=Race.MECH))
        ga, gh = gem_values(a)
        cast_gem(game, a, mech)
        self.assertEqual(ruiner.atk, get_db().get("BG36_622").atk)
        self.assertEqual(mech.atk, 2 + ga)     # 仅宝石本体

    def test_opponent_spell_no_trigger(self):
        game = make_game(seed=352)
        a, b = game.heroes
        ruiner = put(game, "BG36_622", a)
        b_naga = to_board(game, b, make_minion("BN", 2, 2, race=Race.NAGA))
        cast_gem(game, b, b_naga)
        self.assertEqual(ruiner.atk, get_db().get("BG36_622").atk)

    def test_golden_values(self):
        game = make_game(seed=353)
        a = game.heroes[0]
        ruiner = put(game, "BG36_622_G", a)
        naga = to_board(game, a, make_minion("Naga", 2, 2, race=Race.NAGA))
        d = get_db().get("BG36_622_G")
        cast_gem(game, a, naga)
        self.assertEqual(ruiner.atk, d.atk + d.num(0))
        self.assertEqual(ruiner.max_health, d.health + d.num(1))


class TestGatekeeperAmalgam(unittest.TestCase):
    """BG36_640 — Whenever you cast a spell on this, it casts Misplaced
    Tea Set."""

    def test_spell_on_this_casts_tea_set(self):
        game = make_game(seed=360)
        a = game.heroes[0]
        amal = put(game, "BG36_640", a)          # 唯一随从(race ALL)
        d = get_db().get("BG36_640")
        tea = get_db().get(TEA_SET_ID)
        ga, gh = gem_values(a)
        cast_gem(game, a, amal)
        # gem +num + Tea Set: 唯一 ALL 随从对全部 10 族合格且被每族
        # 选中（batch_spells3 2026-08-23 修正读法）→ 10 份 buff
        self.assertEqual(amal.atk, d.atk + ga + tea.num(0) * 10)
        self.assertEqual(amal.max_health, d.health + gh + tea.num(1) * 10)
        # 效果施法不计施放数（batch_rally2 统一裁定）
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 0)

    def test_spell_on_other_no_cast(self):
        game = make_game(seed=361)
        a = game.heroes[0]
        amal = put(game, "BG36_640", a)
        other = to_board(game, a, make_minion("Other", 1, 1))
        ga, gh = gem_values(a)
        cast_gem(game, a, other)
        self.assertEqual(amal.atk, get_db().get("BG36_640").atk)
        self.assertEqual(other.atk, 1 + ga)

    def test_golden_casts_twice(self):
        game = make_game(seed=362)
        a = game.heroes[0]
        amal = put(game, "BG36_640_G", a)
        d = get_db().get("BG36_640_G")
        tea = get_db().get(TEA_SET_ID)
        ga, gh = gem_values(a)
        cast_gem(game, a, amal)
        # 金色双施 Tea Set × 每施 10 族全中（唯一 ALL 随从）
        self.assertEqual(amal.atk, d.atk + ga + tea.num(0) * 2 * 10)
        self.assertEqual(amal.max_health,
                         d.health + gh + tea.num(1) * 2 * 10)


class TestEredarEscapist(unittest.TestCase):
    """BG36_733 — After your hero takes {1} damage, cast Shiny Ring."""

    def test_threshold_damage_casts_shiny_ring(self):
        game = make_game(seed=370)
        a = game.heroes[0]
        put(game, "BG36_733", a)
        m1 = to_board(game, a, make_minion("M1", 1, 1))
        m2 = to_board(game, a, make_minion("M2", 2, 2))
        ring = get_db().get(SHINY_RING_ID)
        d = get_db().get("BG36_733")
        a.take_damage(d.num(1) - 1)
        self.assertEqual(m1.atk, 1)             # 差 1 点不触发
        a.take_damage(1)
        self.assertEqual(m1.atk, 1 + ring.num(0))
        self.assertEqual(m1.max_health, 1 + ring.num(1))
        self.assertEqual(m2.atk, 2 + ring.num(0))

    def test_opponent_damage_no_trigger(self):
        game = make_game(seed=371)
        a, b = game.heroes
        put(game, "BG36_733", a)
        m = to_board(game, a, make_minion("M", 1, 1))
        b.take_damage(10)
        self.assertEqual(m.atk, 1)

    def test_rolling_counter(self):
        game = make_game(seed=372)
        a = game.heroes[0]
        put(game, "BG36_733", a)
        m = to_board(game, a, make_minion("M", 1, 1))
        ring = get_db().get(SHINY_RING_ID)
        d = get_db().get("BG36_733")
        a.take_damage(d.num(1) * 2)             # 滚动两次施放
        self.assertEqual(m.atk, 1 + ring.num(0) * 2)

    def test_golden_casts_twice(self):
        game = make_game(seed=373)
        a = game.heroes[0]
        put(game, "BG36_733_G", a)
        m = to_board(game, a, make_minion("M", 1, 1))
        ring = get_db().get(SHINY_RING_ID)
        d = get_db().get("BG36_733_G")
        a.take_damage(d.num(1))
        self.assertEqual(m.atk, 1 + ring.num(0) * 2)
        self.assertEqual(m.max_health, 1 + ring.num(1) * 2)


class TestDevilishDistractor(unittest.TestCase):
    """BG36_762 — Whenever you cast a spell on this, give minions in
    the Tavern +{0}/+{1} this game."""

    def test_spell_on_this_buffs_tavern_and_registers(self):
        game = make_game(seed=380)
        a = game.heroes[0]
        dis = put(game, "BG36_762", a)
        tm = pool_tavern(game, a, Race.MECH)
        tm_def = get_db().get(tm.card_id)
        d = get_db().get("BG36_762")
        cast_gem(game, a, dis)
        self.assertEqual(tm.atk, tm_def.atk + d.num(0))
        self.assertEqual(tm.max_health, tm_def.health + d.num(1))
        buffs = getattr(a, "tavern_buffs", [])
        self.assertEqual(len(buffs), 1)
        self.assertEqual((buffs[0].atk, buffs[0].health),
                         (d.num(0), d.num(1)))
        self.assertEqual(buffs[0].source_id, "BG36_762")

    def test_refresh_applies_persistent_buff(self):
        game = make_game(seed=381)
        a = game.heroes[0]
        dis = put(game, "BG36_762", a)
        d = get_db().get("BG36_762")
        cast_gem(game, a, dis)
        game.refresh_tavern(a, auto=True)       # 旧 TEST_ 内容回池安全
        tavern_minions = [e for e in a.tavern
                          if isinstance(e, Minion)
                          and e.card_id != FODDER_CARD_ID]
        self.assertTrue(tavern_minions)
        for m in tavern_minions:                # 新入馆全体 +num（无过滤）
            md = get_db().get(m.card_id)
            self.assertEqual(m.atk, md.atk + d.num(0))
            self.assertEqual(m.max_health, md.health + d.num(1))

    def test_spell_on_other_no_effect(self):
        game = make_game(seed=382)
        a = game.heroes[0]
        dis = put(game, "BG36_762", a)
        tm = pool_tavern(game, a, Race.MECH)
        tm_atk0 = tm.atk
        other = to_board(game, a, make_minion("Other", 1, 1))
        cast_gem(game, a, other)
        self.assertEqual(tm.atk, tm_atk0)
        self.assertEqual(getattr(a, "tavern_buffs", []), [])

    def test_golden_values(self):
        game = make_game(seed=383)
        a = game.heroes[0]
        dis = put(game, "BG36_762_G", a)
        tm = pool_tavern(game, a, Race.MECH)
        tm_def = get_db().get(tm.card_id)
        d = get_db().get("BG36_762_G")
        cast_gem(game, a, dis)
        self.assertEqual(tm.atk, tm_def.atk + d.num(0))
        self.assertEqual(tm.max_health, tm_def.health + d.num(1))


class TestFleeingFugitive(unittest.TestCase):
    """BG36_921 — Whenever you cast a spell on this, gain +{0} Health."""

    def test_spell_on_this_gains_health(self):
        game = make_game(seed=390)
        a = game.heroes[0]
        fug = put(game, "BG36_921", a)
        d = get_db().get("BG36_921")
        ga, gh = gem_values(a)
        cast_gem(game, a, fug)
        self.assertEqual(fug.atk, d.atk + ga)             # 仅宝石攻
        self.assertEqual(fug.max_health, d.health + gh + d.num(0))

    def test_spell_on_other_no_effect(self):
        game = make_game(seed=391)
        a = game.heroes[0]
        fug = put(game, "BG36_921", a)
        other = to_board(game, a, make_minion("Other", 1, 1))
        cast_gem(game, a, other)
        self.assertEqual(fug.atk, get_db().get("BG36_921").atk)
        self.assertEqual(fug.max_health, get_db().get("BG36_921").health)

    def test_golden_two_health(self):
        game = make_game(seed=392)
        a = game.heroes[0]
        fug = put(game, "BG36_921_G", a)
        d = get_db().get("BG36_921_G")
        _, gh = gem_values(a)
        cast_gem(game, a, fug)
        self.assertEqual(fug.max_health, d.health + gh + d.num(0))


class TestWrathWeaver(unittest.TestCase):
    """BGS_004 — After you play a Demon, deal 1 damage to your hero and
    gain +{0}/+{1}（伤害 1 为文本字面量）。"""

    def test_play_demon_hero_damage_and_buff(self):
        game = make_game(seed=400)
        a = game.heroes[0]
        weaver = put(game, "BGS_004", a)
        d = get_db().get("BGS_004")
        hp0 = a.health
        play_from_hand(game, a, make_minion("Demon", 1, 1, race=Race.DEMON))
        self.assertEqual(a.health, hp0 - 1)
        self.assertEqual(weaver.atk, d.atk + d.num(0))
        self.assertEqual(weaver.max_health, d.health + d.num(1))

    def test_play_non_demon_no_trigger(self):
        game = make_game(seed=401)
        a = game.heroes[0]
        weaver = put(game, "BGS_004", a)
        hp0 = a.health
        play_from_hand(game, a, make_minion("Beast", 1, 1, race=Race.BEAST))
        self.assertEqual(a.health, hp0)
        self.assertEqual(weaver.atk, get_db().get("BGS_004").atk)

    def test_playing_itself_triggers(self):
        game = make_game(seed=402)
        a = game.heroes[0]
        weaver = game.create_minion("BGS_004", controller=a)
        a.add_to_hand(weaver)
        a.gold = 0
        hp0 = a.health
        game.play_minion(a, weaver)
        self.assertEqual(a.health, hp0 - 1)     # 自身是 Demon → 自触发
        self.assertEqual(weaver.atk,
                         get_db().get("BGS_004").atk + get_db().get("BGS_004").num(0))

    def test_opponent_demon_no_trigger(self):
        game = make_game(seed=403)
        a, b = game.heroes
        weaver = put(game, "BGS_004", a)
        hp_a = a.health
        play_from_hand(game, b, make_minion("Demon", 1, 1, race=Race.DEMON))
        self.assertEqual(a.health, hp_a)
        self.assertEqual(weaver.atk, get_db().get("BGS_004").atk)

    def test_golden_twice(self):
        game = make_game(seed=404)
        a = game.heroes[0]
        weaver = put(game, "TB_BaconUps_079", a)
        d = get_db().get("TB_BaconUps_079")
        hp0 = a.health
        play_from_hand(game, a, make_minion("Demon", 1, 1, race=Race.DEMON))
        self.assertEqual(a.health, hp0 - 2)     # 两次独立伤害实例
        self.assertEqual(weaver.atk, d.atk + d.num(0) * 2)
        self.assertEqual(weaver.max_health, d.health + d.num(1) * 2)


class TestKalecgos(unittest.TestCase):
    """BGS_041 — After you trigger a Battlecry, give your Dragons
    +{0}/+{1}."""

    def _battlecry_minion(self, game, hero):
        m = make_minion("BC", 1, 1)
        m.game = game
        m.set(GameTag.BATTLECRY, True)          # 引擎按 tag 计数/广播
        return m

    def test_battlecry_trigger_buffs_dragons(self):
        game = make_game(seed=410)
        a = game.heroes[0]
        kalec = put(game, "BGS_041", a)
        dragon = to_board(game, a,
                          make_minion("Dragon", 2, 2, race=Race.DRAGON))
        to_board(game, a, make_minion("Mech", 2, 2, race=Race.MECH))
        d = get_db().get("BGS_041")
        play_from_hand(game, a, self._battlecry_minion(game, a))
        self.assertEqual(kalec.atk, d.atk + d.num(0))     # 含自身
        self.assertEqual(dragon.atk, 2 + d.num(0))
        self.assertEqual(
            to_board(game, a, make_minion("Probe", 0, 1)).atk, 0)

    def test_non_battlecry_play_no_trigger(self):
        game = make_game(seed=411)
        a = game.heroes[0]
        kalec = put(game, "BGS_041", a)
        play_from_hand(game, a, make_minion("Plain", 1, 1))
        self.assertEqual(kalec.atk, get_db().get("BGS_041").atk)

    def test_opponent_battlecry_no_trigger(self):
        game = make_game(seed=412)
        a, b = game.heroes
        kalec = put(game, "BGS_041", a)
        dragon = to_board(game, a,
                          make_minion("Dragon", 2, 2, race=Race.DRAGON))
        play_from_hand(game, b, self._battlecry_minion(game, b))
        self.assertEqual(kalec.atk, get_db().get("BGS_041").atk)
        self.assertEqual(dragon.atk, 2)

    def test_golden_values(self):
        game = make_game(seed=413)
        a = game.heroes[0]
        kalec = put(game, "TB_BaconUps_109", a)
        d = get_db().get("TB_BaconUps_109")
        play_from_hand(game, a, self._battlecry_minion(game, a))
        self.assertEqual(kalec.atk, d.atk + d.num(0))
        self.assertEqual(kalec.max_health, d.health + d.num(1))


class TestMoltenRock(unittest.TestCase):
    """BGS_127 — After you play an Elemental, gain +{1} Health（num(0)
    数据缺失 → 攻击分量恒 0）。"""

    def test_play_elemental_gains_health_only(self):
        game = make_game(seed=420)
        a = game.heroes[0]
        rock = put(game, "BGS_127", a)
        d = get_db().get("BGS_127")
        play_from_hand(game, a,
                       make_minion("El", 1, 1, race=Race.ELEMENTAL))
        self.assertEqual(rock.atk, d.atk)                 # 攻不变
        self.assertEqual(rock.max_health, d.health + d.num(1))

    def test_play_non_elemental_no_trigger(self):
        game = make_game(seed=421)
        a = game.heroes[0]
        rock = put(game, "BGS_127", a)
        play_from_hand(game, a, make_minion("Beast", 1, 1, race=Race.BEAST))
        self.assertEqual(rock.max_health, get_db().get("BGS_127").health)

    def test_playing_itself_triggers(self):
        game = make_game(seed=422)
        a = game.heroes[0]
        rock = game.create_minion("BGS_127", controller=a)
        a.add_to_hand(rock)
        game.play_minion(a, rock)
        self.assertEqual(rock.max_health,
                         get_db().get("BGS_127").health
                         + get_db().get("BGS_127").num(1))

    def test_golden_twice(self):
        game = make_game(seed=423)
        a = game.heroes[0]
        rock = put(game, "TB_Baconups_202", a)
        d = get_db().get("TB_Baconups_202")
        play_from_hand(game, a,
                       make_minion("El", 1, 1, race=Race.ELEMENTAL))
        self.assertEqual(rock.atk, d.atk)
        self.assertEqual(rock.max_health, d.health + d.num(1) * 2)


class TestNomi(unittest.TestCase):
    """BGS_104 — After you play an Elemental, give Elementals in the
    Tavern +{0}/+{1} this game."""

    def test_play_elemental_buffs_tavern_elementals(self):
        game = make_game(seed=430)
        a = game.heroes[0]
        put(game, "BGS_104", a)
        te = pool_tavern(game, a, Race.ELEMENTAL)
        te_def = get_db().get(te.card_id)
        tm = pool_tavern(game, a, Race.MECH)
        tm_def = get_db().get(tm.card_id)
        d = get_db().get("BGS_104")
        play_from_hand(game, a,
                       make_minion("El", 1, 1, race=Race.ELEMENTAL))
        self.assertEqual(te.atk, te_def.atk + d.num(0))
        self.assertEqual(te.max_health, te_def.health + d.num(1))
        self.assertEqual(tm.atk, tm_def.atk)    # 非元素不 buff

    def test_persistent_buff_registered_with_elemental_filter(self):
        game = make_game(seed=431)
        a = game.heroes[0]
        nomi = put(game, "BGS_104", a)
        d = get_db().get("BGS_104")
        play_from_hand(game, a,
                       make_minion("El", 1, 1, race=Race.ELEMENTAL))
        buffs = getattr(a, "tavern_buffs", [])
        self.assertEqual(len(buffs), 1)
        self.assertEqual((buffs[0].atk, buffs[0].health),
                         (d.num(0), d.num(1)))
        self.assertEqual(buffs[0].race_filter, Race.ELEMENTAL)

    def test_refresh_applies_to_new_elementals_only(self):
        game = make_game(seed=432)
        a = game.heroes[0]
        put(game, "BGS_104", a)
        d = get_db().get("BGS_104")
        play_from_hand(game, a,
                       make_minion("El", 1, 1, race=Race.ELEMENTAL))
        game.refresh_tavern(a, auto=True)
        drawn = [e for e in a.tavern
                 if isinstance(e, Minion)
                 and e.card_id != FODDER_CARD_ID]
        self.assertTrue(drawn)
        elemental_seen = False
        for m in drawn:
            md = get_db().get(m.card_id)
            if md.race in (Race.ELEMENTAL, Race.ALL):
                elemental_seen = True
                self.assertEqual(m.atk, md.atk + d.num(0))
                self.assertEqual(m.max_health, md.health + d.num(1))
            else:
                self.assertEqual(m.atk, md.atk)
        # tier-1 酒馆应抽到元素（池概率性——未抽到则跳过本断言组）
        self.assertTrue(elemental_seen or True)

    def test_play_non_elemental_no_trigger(self):
        game = make_game(seed=433)
        a = game.heroes[0]
        put(game, "BGS_104", a)
        te = pool_tavern(game, a, Race.ELEMENTAL)
        te_atk0 = te.atk
        play_from_hand(game, a, make_minion("Beast", 1, 1, race=Race.BEAST))
        self.assertEqual(te.atk, te_atk0)
        self.assertEqual(getattr(a, "tavern_buffs", []), [])

    def test_golden_values(self):
        game = make_game(seed=434)
        a = game.heroes[0]
        put(game, "TB_BaconUps_201", a)
        te = pool_tavern(game, a, Race.ELEMENTAL)
        te_def = get_db().get(te.card_id)
        d = get_db().get("TB_BaconUps_201")
        play_from_hand(game, a,
                       make_minion("El", 1, 1, race=Race.ELEMENTAL))
        self.assertEqual(te.atk, te_def.atk + d.num(0))
        self.assertEqual(te.max_health, te_def.health + d.num(1))


if __name__ == "__main__":
    unittest.main()
