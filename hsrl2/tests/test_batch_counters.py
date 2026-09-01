"""批次 counters 语义测试（作业单 2026-08-22，15 张计数/光环/战斗触发随从）。

覆盖: 动态属性钩子 6（Abyssal Bruiser / Falling Sky Golem / Maritime
Extortionist / Eternal Knight / Rot Hide Gnoll / Ancestral Automaton）+
事件监听 7（Deflect-o-Bot / Blade Collector / Barrier Banshee / Snazzy
Phantom / Treasure Parrot / Devout Hellcaller / Warpwing）+ DEFERRED 2
（Wildfire Elemental / Magicfin Mycologist——断言未注册防静默桩）。

驱动手段: 计数 tag 直置（test_batch_deathrattle 先例）/ 真实死亡与
复生路径（in_combat 手动置位 try/finally——test_batch_soc 先例）/
CombatScheduler._execute_attack 单次攻击 / run_combat 全周期。
数值期望一律 CardDef.num() 计算。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff, Hit
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

GOLDEN_TOUCH_ID = "BG28_830"   # Treasure Parrot 奖励法术（batch 同源）

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


def dummy(hero: Hero, health: int = 30) -> Minion:
    return make_minion("Dummy", 0, health)


def kill(game: Game, m: Minion) -> None:
    m.health = 0
    game.check_deaths()


def num(card_id: str, index: int) -> int:
    v = get_db().get(card_id).num(index)
    assert v is not None, f"{card_id}.num({index}) missing"
    return v


class InCombat:
    """手动进入战斗态的上下文管理器（test_batch_soc 先例）。"""

    def __init__(self, game: Game):
        self.game = game

    def __enter__(self):
        self.game.in_combat = True
        return self.game

    def __exit__(self, *exc):
        self.game.in_combat = False
        return False


# ══════════════════ BG35_921 Abyssal Bruiser ══════════════════


class TestAbyssalBruiser(unittest.TestCase):
    CARD = "BG35_921"

    def test_counts_tavern_spells_cast(self):
        game = make_game(seed=1)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertEqual((m.atk, m.max_health), (d.atk, d.health))
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 3)
        self.assertEqual(m.atk, d.atk + 3 * d.num(0))
        self.assertEqual(m.max_health, d.health + 3 * d.num(1))

    def test_zero_count_falls_back(self):
        game = make_game(seed=2)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), 0)
        self.assertEqual((m.atk, m.max_health), (d.atk, d.health))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))   # data keywords

    def test_buffs_included_in_full_recompute(self):
        game = make_game(seed=3)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        game.run_actions(Buff(m, atk=1, health=1))
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 2)
        self.assertEqual(m.atk, d.atk + 1 + 2 * d.num(0))
        self.assertEqual(m.max_health, d.health + 1 + 2 * d.num(1))

    def test_golden_per_values(self):
        game = make_game(seed=4)
        a, _ = game.heroes
        g = get_db().get(self.CARD + "_G")
        m = put(game, self.CARD, a, golden=True)
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 1)
        self.assertEqual((m.atk, m.max_health),
                         (g.atk + g.num(0), g.health + g.num(1)))


# ══════════════════ BG35_342 Falling Sky Golem ══════════════════


class TestFallingSkyGolem(unittest.TestCase):
    CARD = "BG35_342"

    def test_counts_deathrattles_triggered(self):
        game = make_game(seed=5)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        a.set(GameTag.COUNTER_DEATHRATTLES, 2)
        self.assertEqual(m.atk, d.atk + 2 * d.num(0))
        self.assertEqual(m.max_health, d.health + 2 * d.num(1))
        self.assertEqual(a.get(GameTag.COUNTER_DEATHRATTLES, 0), 2)

    def test_zero_count_falls_back(self):
        game = make_game(seed=6)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertEqual((m.atk, m.max_health), (d.atk, d.health))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))

    def test_real_deathrattle_death_path(self):
        game = make_game(seed=7)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        dr = make_minion("DrMinion", 1, 1)
        dr.set(GameTag.DEATHRATTLE, True)
        game.summon(a, dr)
        with InCombat(game):
            kill(game, dr)
        self.assertEqual(a.get(GameTag.COUNTER_DEATHRATTLES, 0), 1)
        self.assertEqual(m.atk, d.atk + d.num(0))
        self.assertEqual(m.max_health, d.health + d.num(1))

    def test_golden_per_values(self):
        game = make_game(seed=8)
        a, _ = game.heroes
        g = get_db().get(self.CARD + "_G")
        m = put(game, self.CARD, a, golden=True)
        a.set(GameTag.COUNTER_DEATHRATTLES, 1)
        self.assertEqual((m.atk, m.max_health),
                         (g.atk + g.num(0), g.health + g.num(1)))


# ══════════════════ BG36_524 Maritime Extortionist ══════════════════


class TestMaritimeExtortionist(unittest.TestCase):
    CARD = "BG36_524"

    def test_counts_golden_minions_played(self):
        game = make_game(seed=9)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertEqual((m.atk, m.max_health), (d.atk, d.health))
        a.set(GameTag.GOLDEN_MINIONS_PLAYED, 1)
        self.assertEqual(m.atk, d.atk + d.num(0))
        self.assertEqual(m.max_health, d.health + d.num(1))

    def test_real_golden_play_path(self):
        game = make_game(seed=10)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a, position=0)
        g = game.create_minion("BG25_013", controller=a, golden=True)
        a.hand.append(g)
        g.zone = Zone.HAND
        self.assertTrue(game.play_minion(a, g))
        self.assertEqual(a.get(GameTag.GOLDEN_MINIONS_PLAYED), 1)
        self.assertEqual(m.atk, d.atk + d.num(0))
        self.assertEqual(m.max_health, d.health + d.num(1))

    def test_golden_per_values(self):
        game = make_game(seed=11)
        a, _ = game.heroes
        g = get_db().get(self.CARD + "_G")
        m = put(game, self.CARD, a, golden=True)
        a.set(GameTag.GOLDEN_MINIONS_PLAYED, 2)
        self.assertEqual((m.atk, m.max_health),
                         (g.atk + 2 * g.num(0), g.health + 2 * g.num(1)))


# ══════════════════ BG25_008 Eternal Knight ══════════════════


class TestEternalKnight(unittest.TestCase):
    CARD = "BG25_008"

    def test_counts_friendly_knight_deaths(self):
        game = make_game(seed=12)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        k1 = put(game, self.CARD, a)
        k2 = put(game, self.CARD, a)
        with InCombat(game):
            kill(game, k1)
            kill(game, k2)
        self.assertEqual(getattr(a, "deaths_by_card_id", {}).get(self.CARD),
                         2)
        self.assertEqual(m.atk, d.atk + 2 * d.num(0))
        self.assertEqual(m.max_health, d.health + 2 * d.num(1))

    def test_no_deaths_falls_back(self):
        game = make_game(seed=13)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertEqual((m.atk, m.max_health), (d.atk, d.health))

    def test_enemy_knight_deaths_not_counted(self):
        game = make_game(seed=14)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        enemy_k = put(game, self.CARD, b)
        with InCombat(game):
            kill(game, enemy_k)
        self.assertEqual(getattr(a, "deaths_by_card_id", {}).get(self.CARD),
                         None)
        self.assertEqual(m.atk, d.atk)

    def test_golden_knight_deaths_in_family(self):
        game = make_game(seed=15)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        gk = put(game, self.CARD, a, golden=True)
        self.assertEqual(gk.card_id, self.CARD + "_G")
        with InCombat(game):
            kill(game, gk)
        deaths = getattr(a, "deaths_by_card_id", {})
        self.assertEqual(deaths.get(self.CARD + "_G"), 1)
        self.assertEqual(m.atk, d.atk + d.num(0))
        self.assertEqual(m.max_health, d.health + d.num(1))


# ══════════════════ BG25_013 Rot Hide Gnoll ══════════════════


class TestRotHideGnoll(unittest.TestCase):
    CARD = "BG25_013"

    def test_grows_per_friendly_death_in_combat(self):
        game = make_game(seed=16)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        v1 = make_minion("V1", 1, 1)
        v2 = make_minion("V2", 1, 1)
        game.summon(a, v1)
        game.summon(a, v2)
        with InCombat(game):
            kill(game, v1)
            self.assertEqual(m.atk, d.atk + 1)
            kill(game, v2)
            self.assertEqual(m.atk, d.atk + 2)
            self.assertEqual(m.max_health, d.health)   # 生命不变

    def test_resets_out_of_combat(self):
        game = make_game(seed=17)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        v = make_minion("V", 1, 1)
        game.summon(a, v)
        with InCombat(game):
            kill(game, v)
            self.assertEqual(m.atk, d.atk + 1)
        self.assertEqual(m.atk, d.atk)   # 战后回落

    def test_enemy_deaths_not_counted(self):
        game = make_game(seed=18)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        e = dummy(b)
        game.summon(b, e)
        with InCombat(game):
            kill(game, e)
            self.assertEqual(m.atk, d.atk)

    def test_run_combat_full_cycle_resets(self):
        game = make_game(seed=19)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        v = make_minion("V", 1, 1)
        game.summon(a, v)
        game.summon(b, dummy(b))
        game.run_combat(a, b)
        self.assertFalse(game.in_combat)
        self.assertEqual(m.atk, d.atk)

    def test_golden_plus_two(self):
        game = make_game(seed=20)
        a, _ = game.heroes
        g = get_db().get(self.CARD + "_G")
        m = put(game, self.CARD, a, golden=True)
        v = make_minion("V", 1, 1)
        game.summon(a, v)
        with InCombat(game):
            kill(game, v)
            self.assertEqual(m.atk, g.atk + 2)


# ══════════════════ BG_TTN_401 Ancestral Automaton ══════════════════


class TestAncestralAutomaton(unittest.TestCase):
    CARD = "BG_TTN_401"

    def test_single_no_bonus(self):
        game = make_game(seed=21)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertEqual((m.atk, m.max_health), (d.atk, d.health))

    def test_two_each_plus_one_other(self):
        game = make_game(seed=22)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m1 = put(game, self.CARD, a)
        m2 = put(game, self.CARD, a)
        for m in (m1, m2):
            self.assertEqual(m.atk, d.atk + 3)
            self.assertEqual(m.max_health, d.health + 2)

    def test_three_each_plus_two_others(self):
        game = make_game(seed=23)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        ms = [put(game, self.CARD, a) for _ in range(3)]
        for m in ms:
            self.assertEqual(m.atk, d.atk + 6)
            self.assertEqual(m.max_health, d.health + 4)

    def test_hand_copy_counts_board_others(self):
        game = make_game(seed=24)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        put(game, self.CARD, a)
        in_hand = game.create_minion(self.CARD, controller=a)
        a.hand.append(in_hand)
        in_hand.zone = Zone.HAND
        self.assertEqual(in_hand.atk, d.atk + 3)
        self.assertEqual(in_hand.max_health, d.health + 2)

    def test_summon_count_persists_after_sell(self):
        game = make_game(seed=25)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m1 = put(game, self.CARD, a)
        game.sell_minion(a, m1)
        m2 = put(game, self.CARD, a)
        # 售出者仍算 "summoned this game" → m2 见 1 other
        self.assertEqual(m2.atk, d.atk + 3)
        self.assertEqual(m2.max_health, d.health + 2)

    def test_golden_per_values(self):
        game = make_game(seed=26)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        g = get_db().get(self.CARD + "_G")
        base = put(game, self.CARD, a)
        golden = put(game, self.CARD, a, golden=True)
        self.assertEqual(base.atk, d.atk + 3)         # 见金色 1 other
        self.assertEqual(golden.atk, g.atk + 6)       # 见基础 1 other
        self.assertEqual(golden.max_health, g.health + 4)


# ══════════════════ BGS_071 Deflect-o-Bot ══════════════════


class TestDeflectOBot(unittest.TestCase):
    CARD = "BGS_071"

    def test_combat_mech_summon_grants_atk_and_ds(self):
        game = make_game(seed=27)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        m.clear(GameTag.DIVINE_SHIELD)                # 验证 DS 重获
        mech = make_minion("Mech", 1, 1, race=Race.MECH)
        with InCombat(game):
            game.summon(a, mech)
            self.assertEqual(m.atk, d.atk + d.num(0))
            self.assertTrue(m.has(GameTag.DIVINE_SHIELD))

    def test_recruit_phase_summon_no_trigger(self):
        game = make_game(seed=28)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        mech = make_minion("Mech", 1, 1, race=Race.MECH)
        game.summon(a, mech)                          # 招募期
        self.assertEqual(m.atk, d.atk)

    def test_non_mech_and_enemy_no_trigger(self):
        game = make_game(seed=29)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        beast = make_minion("Beast", 1, 1, race=Race.BEAST)
        enemy_mech = make_minion("EMech", 1, 1, race=Race.MECH)
        with InCombat(game):
            game.summon(a, beast)
            game.summon(b, enemy_mech)
            self.assertEqual(m.atk, d.atk)

    def test_golden_plus_four(self):
        game = make_game(seed=30)
        a, _ = game.heroes
        g = get_db().get("TB_BaconUps_123")
        m = put(game, self.CARD, a, golden=True)
        mech = make_minion("Mech", 1, 1, race=Race.MECH)
        with InCombat(game):
            game.summon(a, mech)
            self.assertEqual(m.atk, g.atk + g.num(0))


# ══════════════════ BG26_817 Blade Collector ══════════════════


class TestBladeCollector(unittest.TestCase):
    CARD = "BG26_817"

    def test_cleave_tag_set_on_summon(self):
        game = make_game(seed=31)
        a, _ = game.heroes
        m = put(game, self.CARD, a)
        self.assertTrue(m.has(GameTag.CLEAVE))

    def test_attack_splashes_to_adjacent_defenders(self):
        game = make_game(seed=32)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        e0 = make_minion("E0", 1, 30)
        e1 = make_minion("E1", 1, 30)
        e2 = make_minion("E2", 1, 30)
        game.summon(b, e0)
        game.summon(b, e1)
        game.summon(b, e2)
        CombatScheduler(game, a, b)._execute_attack(m, e1)
        self.assertEqual(e1.health, 30 - d.atk)   # 主目标
        self.assertEqual(e0.health, 30 - d.atk)   # 左邻
        self.assertEqual(e2.health, 30 - d.atk)   # 右邻

    def test_normal_minion_no_splash(self):
        game = make_game(seed=33)
        a, b = game.heroes
        plain = make_minion("Plain", 2, 30)
        game.summon(a, plain)
        e0 = make_minion("E0", 1, 30)
        e1 = make_minion("E1", 1, 30)
        e2 = make_minion("E2", 1, 30)
        game.summon(b, e0)
        game.summon(b, e1)
        game.summon(b, e2)
        CombatScheduler(game, a, b)._execute_attack(plain, e1)
        self.assertEqual(e1.health, 28)
        self.assertEqual(e0.health, 30)
        self.assertEqual(e2.health, 30)


# ══════════════════ BG36_514 Barrier Banshee ══════════════════


class TestBarrierBanshee(unittest.TestCase):
    CARD = "BG36_514"

    def test_friendly_reborn_grants_ds_and_stats(self):
        game = make_game(seed=34)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))
        v = make_minion("Reborner", 2, 3)
        v.set(GameTag.REBORN, True)
        game.summon(a, v)
        with InCombat(game):
            kill(game, v)
            self.assertTrue(v.get(GameTag.HEALTH, 0) == 1)   # 复生回归
            self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
            self.assertEqual(m.atk, d.atk + d.num(0))
            self.assertEqual(m.max_health, d.health + d.num(1))

    def test_enemy_reborn_no_trigger(self):
        game = make_game(seed=35)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        ev = make_minion("EnemyReborner", 2, 3)
        ev.set(GameTag.REBORN, True)
        game.summon(b, ev)
        with InCombat(game):
            kill(game, ev)
            self.assertEqual((m.atk, m.max_health), (d.atk, d.health))
            self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_plain_death_without_reborn_no_trigger(self):
        game = make_game(seed=36)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        v = make_minion("PlainV", 1, 1)
        game.summon(a, v)
        with InCombat(game):
            kill(game, v)
            self.assertEqual((m.atk, m.max_health), (d.atk, d.health))

    def test_golden_values(self):
        game = make_game(seed=37)
        a, _ = game.heroes
        g = get_db().get(self.CARD + "_G")
        m = put(game, self.CARD, a, golden=True)
        v = make_minion("Reborner", 2, 3)
        v.set(GameTag.REBORN, True)
        game.summon(a, v)
        with InCombat(game):
            kill(game, v)
            self.assertEqual(m.atk, g.atk + g.num(0))
            self.assertEqual(m.max_health, g.health + g.num(1))


# ══════════════════ BG36_515 Snazzy Phantom ══════════════════


class TestSnazzyPhantom(unittest.TestCase):
    CARD = "BG36_515"

    def test_reborn_gives_stats_to_rightmost_undead(self):
        game = make_game(seed=38)
        a, _ = game.heroes
        phantom = put(game, self.CARD, a)             # pos 0, Undead
        v = make_minion("Reborner", 4, 3)             # 非 undead
        v.set(GameTag.REBORN, True)
        game.summon(a, v)                             # pos 1
        target = make_minion("UndeadTarget", 2, 3,
                             race=Race.UNDEAD)
        game.summon(a, target)                        # pos 2 最右
        with InCombat(game):
            kill(game, v)
            self.assertEqual(target.atk, 2 + 4)       # 复活体 4 攻
            self.assertEqual(target.max_health, 3 + 4)
            self.assertEqual(phantom.atk, get_db().get(self.CARD).atk)

    def test_enemy_reborn_no_trigger(self):
        game = make_game(seed=39)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        phantom = put(game, self.CARD, a)
        t = make_minion("UndeadTarget", 2, 3, race=Race.UNDEAD)
        game.summon(a, t)
        ev = make_minion("EnemyReborner", 4, 3)
        ev.set(GameTag.REBORN, True)
        game.summon(b, ev)
        with InCombat(game):
            kill(game, ev)
            self.assertEqual((t.atk, phantom.atk), (2, d.atk))

    def test_no_undead_no_effect(self):
        game = make_game(seed=40)
        a, _ = game.heroes
        d = get_db().get(self.CARD)
        put(game, self.CARD, a)
        phantom = make_minion("Phantom2", 6, 8)
        # 棋盘无存活 Undead: 复活体非 undead、卖掉 phantom 后触发
        v = make_minion("Reborner", 4, 3)
        v.set(GameTag.REBORN, True)
        game.summon(a, v)
        game.sell_minion(a, [m for m in a.board
                             if m.card_id == self.CARD][0])
        self.assertEqual(phantom.zone, Zone.INVALID)  # 未上场哨兵
        with InCombat(game):
            kill(game, v)                             # 无 Undead → 落空不崩
        self.assertEqual(v.get(GameTag.HEALTH, 0), 1)

    def test_golden_double(self):
        game = make_game(seed=41)
        a, _ = game.heroes
        g = get_db().get(self.CARD + "_G")
        put(game, self.CARD, a, golden=True)          # pos 0
        v = make_minion("Reborner", 4, 3)
        v.set(GameTag.REBORN, True)
        game.summon(a, v)                             # pos 1
        target = make_minion("UndeadTarget", 2, 3,
                             race=Race.UNDEAD)
        game.summon(a, target)                        # pos 2 最右
        with InCombat(game):
            kill(game, v)
            self.assertEqual(target.atk, 2 + 4 * 2)
            self.assertEqual(target.max_health, 3 + 4 * 2)
        self.assertEqual(g.atk, get_db().get(self.CARD + "_G").atk)


# ══════════════════ BG36_763 Treasure Parrot ══════════════════


class TestTreasureParrot(unittest.TestCase):
    CARD = "BG36_763"

    def _hand_count(self, hero) -> int:
        return sum(1 for c in hero.hand
                   if c.card_id == GOLDEN_TOUCH_ID)

    def test_threshold_reached_grants_golden_touch(self):
        game = make_game(seed=42)
        a, b = game.heroes
        threshold = num(self.CARD, 1)
        avail = game.spell_pool.available(GOLDEN_TOUCH_ID)
        m = put(game, self.CARD, a)
        victim = dummy(b, 200)
        game.summon(b, victim)
        Hit(victim, threshold - 1, source=m).do(game)
        self.assertEqual(self._hand_count(a), 0)
        Hit(victim, 1, source=m).do(game)             # 恰达阈值
        self.assertEqual(self._hand_count(a), 1)
        self.assertEqual(game.spell_pool.available(GOLDEN_TOUCH_ID),
                         avail - 1)

    def test_other_sources_damage_not_counted(self):
        game = make_game(seed=43)
        a, b = game.heroes
        m = put(game, self.CARD, a)
        other = make_minion("Other", 5, 5)
        game.summon(a, other)
        victim = dummy(b, 200)
        game.summon(b, victim)
        Hit(victim, num(self.CARD, 1) + 10, source=other).do(game)
        self.assertEqual(self._hand_count(a), 0)
        self.assertFalse(getattr(m, "_touch_done", False))

    def test_one_shot_no_second_grant(self):
        game = make_game(seed=44)
        a, b = game.heroes
        m = put(game, self.CARD, a)
        victim = dummy(b, 200)
        game.summon(b, victim)
        Hit(victim, num(self.CARD, 1), source=m).do(game)
        Hit(victim, 50, source=m).do(game)            # (Done!) 后不再发
        self.assertEqual(self._hand_count(a), 1)

    def test_golden_two_touches(self):
        game = make_game(seed=45)
        a, b = game.heroes
        m = put(game, self.CARD, a, golden=True)
        victim = dummy(b)
        game.summon(b, victim)
        Hit(victim, num(self.CARD, 1), source=m).do(game)
        self.assertEqual(self._hand_count(a), 2)      # 首份占池、次份净增


# ══════════════════ BG33_155 Devout Hellcaller ══════════════════


class TestDevoutHellcaller(unittest.TestCase):
    CARD = "BG33_155"

    def test_friendly_demon_damage_grants_permanent(self):
        game = make_game(seed=46)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        self.assertTrue(m.has(GameTag.PERSIST_COMBAT_CHANGES))
        demon = make_minion("Demon", 5, 5, race=Race.DEMON)
        game.summon(a, demon)
        victim = dummy(b)
        game.summon(b, victim)
        Hit(victim, 3, source=demon).do(game)
        self.assertEqual(m.atk, d.atk + d.num(0))
        self.assertEqual(m.max_health, d.health + d.num(1))

    def test_self_non_demon_enemy_no_trigger(self):
        game = make_game(seed=47)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)                   # 自身是 Demon
        beast = make_minion("Beast", 5, 5, race=Race.BEAST)
        game.summon(a, beast)
        enemy_demon = make_minion("EDemon", 5, 5, race=Race.DEMON)
        game.summon(b, enemy_demon)
        victim = dummy(b)
        game.summon(b, victim)
        Hit(victim, 3, source=m).do(game)             # 本体（虽是 Demon）
        Hit(victim, 3, source=beast).do(game)         # 友方非 Demon
        Hit(victim, 3, source=enemy_demon).do(game)   # 敌方 Demon
        self.assertEqual((m.atk, m.max_health), (d.atk, d.health))

    def test_gains_survive_combat_snapshot_restore(self):
        game = make_game(seed=48)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a, position=0)       # 2/2
        demon = make_minion("Demon", 10, 10, race=Race.DEMON)
        game.summon(a, demon)                         # 10 攻
        wall = make_minion("Wall", 0, 12)             # 0 攻: 不反击、必死
        game.summon(b, wall)
        game.run_combat(a, b)
        # Demon 恰造成一次伤害（12 血墙: 10+2 两击必杀、0 攻无反击）
        self.assertEqual(m.atk, d.atk + d.num(0))
        self.assertEqual(m.max_health, d.health + d.num(1))
        self.assertEqual(m.health, m.max_health)

    def test_golden_values(self):
        game = make_game(seed=49)
        a, b = game.heroes
        g = get_db().get(self.CARD + "_G")
        m = put(game, self.CARD, a, golden=True)
        demon = make_minion("Demon", 5, 5, race=Race.DEMON)
        game.summon(a, demon)
        victim = dummy(b)
        game.summon(b, victim)
        Hit(victim, 3, source=demon).do(game)
        self.assertEqual(m.atk, g.atk + g.num(0))
        self.assertEqual(m.max_health, g.health + g.num(1))


# ══════════════════ BG24_004 Warpwing ══════════════════


class TestWarpwing(unittest.TestCase):
    CARD = "BG24_004"

    def test_tag_set_on_summon(self):
        game = make_game(seed=50)
        a, _ = game.heroes
        m = put(game, self.CARD, a)
        self.assertTrue(m.has(GameTag.IMMUNE_WHILE_ATTACKING))

    def test_takes_no_counter_damage_while_attacking(self):
        game = make_game(seed=51)
        a, b = game.heroes
        d = get_db().get(self.CARD)
        m = put(game, self.CARD, a)
        defender = make_minion("Defender", 5, 30)
        game.summon(b, defender)
        CombatScheduler(game, a, b)._execute_attack(m, defender)
        self.assertEqual(m.health, d.health)          # 免疫: 0 反击
        self.assertEqual(defender.health, 30 - d.atk)

    def test_normal_attacker_takes_counter_damage(self):
        game = make_game(seed=52)
        a, b = game.heroes
        plain = make_minion("Plain", 2, 30)
        game.summon(a, plain)
        defender = make_minion("Defender", 5, 30)
        game.summon(b, defender)
        CombatScheduler(game, a, b)._execute_attack(plain, defender)
        self.assertEqual(plain.health, 30 - 5)        # 负例对照


# ══════════════════ DEFERRED 守卫 ══════════════════
# （2026-08-23 batch_final_unfreeze 解冻 BGS_126/BG33_891——占位守护
#  翻转为注册面守护，test_batch_bloodgem.py BG36_333 同款先例）


class TestDeferredNotRegistered(unittest.TestCase):
    """原 DEFERRED 卡解冻后必须注册——防静默空桩/漏注册
    （SOP §6/批次约定; batch_final_unfreeze 接管）。"""

    def test_wildfire_elemental_deferred(self):
        self.assertIn("BGS_126", REGISTRY)
        self.assertIn("TB_BaconUps_166", REGISTRY)

    def test_magicfin_mycologist_deferred(self):
        self.assertIn("BG33_891", REGISTRY)
        self.assertIn("BG33_891_G", REGISTRY)


if __name__ == "__main__":
    unittest.main()
