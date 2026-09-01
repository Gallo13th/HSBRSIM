"""批次 rally2 语义测试（作业单 2026-08-21，剩余 Rally 池随从 15 张
+ 2 张被 "Cast" 引用的法术）。

Rally 触发驱动: CombatScheduler(game,a,b)._execute_attack(attacker,
defender) 单次攻击（TEST_SOP 经验库——rally 在伤害前触发）; 数值期望
一律 CardDef.num() 计算。金色卡定义不携带关键词标志（batch_rally 已
报告数据缺口）→ 金色断言仅覆盖脚本行为。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.constants import BOARD_SIZE, GOLDEN_POOL_RETURN_COPIES, POOL_COPIES_BY_TIER
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY, bind_all
from hsrl2.scripts.batches.batch_rally2 import (
    CHEFS_CHOICE_ID,
    CHOOSE_ONE_MINION_IDS,
    CHOOSE_ONE_SPELL_IDS,
    CHROMADRAKE_IDS,
    FORAGING_BAT_ID,
    MIGHTY_DRAGONBREATH_ID,
    TASTY_LOBSTER_ID,
)
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
XML_PATH = ROOT / "hsdata" / "CardDefs.xml"

GEM_ID = "BG20_GEM"   # 血宝石基础值唯一来源（bloodgem.py 同源）

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


def dummy(hero: Hero, health: int = 100, atk: int = 0) -> Minion:
    return make_minion("Dummy", atk, health)


def gem_values(game: Game, hero: Hero) -> tuple[int, int]:
    d = get_db().get(GEM_ID)
    return (d.num(0) + hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0),
            d.num(1) + hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0))


def attack(game: Game, attacker: Minion, defender: Minion) -> None:
    """单次攻击驱动 Rally（TEST_SOP 经验库，绕过完整循环）。"""
    a, b = game.heroes[0], game.heroes[1]
    CombatScheduler(game, a, b)._execute_attack(attacker, defender)


class TestRoadboar(unittest.TestCase):
    """BG20_101 — Rally: Get a Blood Gem."""

    def test_rally_gets_blood_gem_into_hand(self):
        game = make_game(seed=200)
        a, b = game.heroes
        boar = put(game, "BG20_101", a)
        attack(game, boar, dummy(b))
        gems = [c for c in a.hand if c.card_id == GEM_ID]
        self.assertEqual(len(gems), 1)
        self.assertEqual(gems[0].zone, Zone.HAND)
        # 非池卡不占法术池
        self.assertEqual(game.spell_pool.available(GEM_ID), 0)

    def test_golden_rally_gets_two_gems(self):
        game = make_game(seed=201)
        a, b = game.heroes
        boar = put(game, "BG20_101", a, golden=True)
        self.assertEqual(boar.card_id, "BG20_101_G")
        attack(game, boar, dummy(b))
        self.assertEqual(
            len([c for c in a.hand if c.card_id == GEM_ID]), 2)


class TestBonker(unittest.TestCase):
    """BG20_104 — Windfury; Rally: This plays {0} Blood Gems on all your
    other minions."""

    def test_rally_plays_gems_on_other_minions(self):
        game = make_game(seed=202)
        a, b = game.heroes
        d = get_db().get("BG20_104")
        bonker = put(game, "BG20_104", a)
        m1, m2 = make_minion("M1", 1, 10), make_minion("M2", 1, 10)
        game.summon(a, m1)
        game.summon(a, m2)
        attack(game, bonker, dummy(b))
        g_atk, g_health = gem_values(game, a)
        for m in (m1, m2):
            self.assertEqual(m.atk, 1 + g_atk * d.num(0))
            self.assertEqual(m.max_health, 10 + g_health * d.num(0))
        # 自身排除（文本 "your other minions"）
        self.assertEqual(bonker.atk, d.atk)
        self.assertEqual(bonker.buffs, [])

    def test_rally_alone_no_effect(self):
        game = make_game(seed=203)
        a, b = game.heroes
        bonker = put(game, "BG20_104", a)
        attack(game, bonker, dummy(b))
        self.assertEqual(bonker.buffs, [])

    def test_golden_plays_two_gems_each(self):
        game = make_game(seed=204)
        a, b = game.heroes
        dg = get_db().get("BG20_104_G")
        self.assertEqual(dg.num(0), 2)
        bonker = put(game, "BG20_104", a, golden=True)
        m = make_minion("M", 1, 10)
        game.summon(a, m)
        attack(game, bonker, dummy(b))
        g_atk, g_health = gem_values(game, a)
        self.assertEqual(m.atk, 1 + g_atk * dg.num(0))
        self.assertEqual(m.max_health, 10 + g_health * dg.num(0))


class TestRazorfenVineweaver(unittest.TestCase):
    """BG33_883 — Rally: This plays 3 permanent Blood Gems on itself."""

    def test_recruit_path_persists_without_replay(self):
        game = make_game(seed=205)
        a, b = game.heroes
        d = get_db().get("BG33_883")
        vw = put(game, "BG33_883", a)
        game.run_script_hook(vw, "rally", ctx={"target": dummy(b)})
        g_atk, g_health = gem_values(game, a)
        self.assertEqual(vw.atk, d.atk + g_atk * 3)   # "3" 文本字面量
        self.assertEqual(vw.max_health, d.health + g_health * 3)
        self.assertEqual(game.deferred_actions, [])   # 无回滚无需重放

    def test_combat_path_replays_after_snapshot_revert(self):
        game = make_game(seed=206)
        a, b = game.heroes
        d = get_db().get("BG33_883")
        g_atk, g_health = gem_values(game, a)
        vw = put(game, "BG33_883", a)
        # 1 血 0 攻靶: 恰好一次攻击（宝石加成后必杀）→ 恰好 1 次 Rally
        game.summon(b, dummy(b, health=d.atk + g_atk * 3))
        game.run_combat(a, b)
        # 战斗内 buff 已被快照回滚，重放调度在场（3 颗 = 3 个调度）
        self.assertEqual(vw.atk, d.atk)
        self.assertEqual(len(game.deferred_actions), 3)
        # 下一招募回合开始重放 → "permanent" 净效果
        game._begin_recruit_for(a)
        self.assertEqual(vw.atk, d.atk + g_atk * 3)
        self.assertEqual(vw.max_health, d.health + g_health * 3)

    def test_golden_six_gems(self):
        game = make_game(seed=207)
        a, b = game.heroes
        d = get_db().get("BG33_883")
        g_atk, g_health = gem_values(game, a)
        vw = put(game, "BG33_883", a, golden=True)
        game.summon(b, dummy(b, health=d.atk * 2 + g_atk * 6))
        game.run_combat(a, b)
        self.assertEqual(len(game.deferred_actions), 6)   # "6" 金色文本
        game._begin_recruit_for(a)
        dg = get_db().get("BG33_883_G")
        self.assertEqual(vw.atk, dg.atk + g_atk * 6)
        self.assertEqual(vw.max_health, dg.health + g_health * 6)


class TestSanguineRefiner(unittest.TestCase):
    """BG33_885 — Rally: Your Blood Gems give an extra +{0}/+{1}
    this game."""

    def test_rally_improves_blood_gems_and_stacks(self):
        game = make_game(seed=208)
        a, b = game.heroes
        d = get_db().get("BG33_885")
        refiner = put(game, "BG33_885", a)
        attack(game, refiner, dummy(b))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), d.num(0))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH), d.num(1))
        attack(game, refiner, dummy(b))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), d.num(0) * 2)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH),
                         d.num(1) * 2)
        # 集成: 宝石数值随之增长
        g_atk, g_health = gem_values(game, a)
        self.assertEqual(g_atk, get_db().get(GEM_ID).num(0) + d.num(0) * 2)
        self.assertEqual(g_health,
                         get_db().get(GEM_ID).num(1) + d.num(1) * 2)

    def test_golden_uses_golden_values(self):
        game = make_game(seed=209)
        a, b = game.heroes
        dg = get_db().get("BG33_885_G")
        self.assertEqual((dg.num(0), dg.num(1)), (2, 2))
        refiner = put(game, "BG33_885", a, golden=True)
        attack(game, refiner, dummy(b))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), dg.num(0))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH), dg.num(1))


class TestHeroicUnderdog(unittest.TestCase):
    """BG34_604 — Stealth; Rally: Gain the target's Attack."""

    def test_rally_gains_target_attack_before_damage(self):
        game = make_game(seed=210)
        a, b = game.heroes
        d = get_db().get("BG34_604")
        underdog = put(game, "BG34_604", a)
        # 数据缺口（报告主线）: 生成器未导出 stealth 关键词——不作断言
        target = dummy(b, atk=6)
        attack(game, underdog, target)
        # rally 先于伤害: 伤害 = atk + 目标攻; 增益含在本次攻击中
        self.assertEqual(target.health, 100 - (d.atk + 6))
        self.assertEqual(underdog.atk, d.atk + 6)
        # 反伤: 10 血承受 6 点反击（Stealth 不免疫反伤）
        self.assertEqual(underdog.health, d.health - 6)

    def test_rally_zero_atk_target_no_gain(self):
        game = make_game(seed=211)
        a, b = game.heroes
        d = get_db().get("BG34_604")
        underdog = put(game, "BG34_604", a)
        target = dummy(b)                      # 0 攻
        attack(game, underdog, target)
        self.assertEqual(target.health, 100 - d.atk)
        self.assertEqual(underdog.atk, d.atk)
        self.assertEqual(underdog.buffs, [])   # 0 增益不产生 buff 实例

    def test_golden_gains_double(self):
        game = make_game(seed=212)
        a, b = game.heroes
        d = get_db().get("BG34_604")
        underdog = put(game, "BG34_604", a, golden=True)
        target = dummy(b, atk=6)
        attack(game, underdog, target)
        self.assertEqual(target.health, 100 - (d.atk * 2 + 6 * 2))
        self.assertEqual(underdog.atk, d.atk * 2 + 6 * 2)


class TestChefsChoiceSpell(unittest.TestCase):
    """BG28_518 — Choose a minion. Get a different minion of the same
    type.（[Targeted]+[Generate]，Recruiter 效果施法的本体）"""

    def _cast(self, game, hero, target):
        spell = game.create_spell(CHEFS_CHOICE_ID, controller=hero)
        game.run_script_hook(spell, "on_play", ctx={"target": target})
        spell.zone = Zone.REMOVED

    def test_murloc_target_gets_different_same_race_and_occupies_pool(self):
        game = make_game(seed=213)
        a, b = game.heroes
        murloc = make_minion("Murloc", 1, 5, race=Race.MURLOC)
        game.summon(a, murloc)
        self._cast(game, a, murloc)
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 1)
        self.assertNotEqual(gained[0].card_id, murloc.card_id)
        self.assertIn(gained[0].race, (Race.MURLOC, Race.ALL))
        tier = get_db().get(gained[0].card_id).tech_level
        self.assertEqual(game.minion_pool.available(gained[0].card_id),
                         POOL_COPIES_BY_TIER[tier] - 1)   # acquire 占池

    def test_all_target_never_gives_typeless(self):
        # 官方 Patch 28.6.0.193541 bugfix 语义
        game = make_game(seed=214)
        a, b = game.heroes
        amalgam = make_minion("Amal", 1, 5, race=Race.ALL)
        game.summon(a, amalgam)
        self._cast(game, a, amalgam)
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 1)
        self.assertNotEqual(gained[0].race, Race.NONE)

    def test_typeless_target_gets_typeless(self):
        game = make_game(seed=215)
        a, b = game.heroes
        typeless = make_minion("None", 1, 5, race=Race.NONE)
        game.summon(a, typeless)
        self._cast(game, a, typeless)
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 1)
        self.assertEqual(gained[0].race, Race.NONE)


class TestSeafloorRecruiter(unittest.TestCase):
    """BG34_925 — Rally: Cast Chef's Choice on the minion to the
    right."""

    def test_rally_casts_on_right_neighbor(self):
        game = make_game(seed=216)
        a, b = game.heroes
        recruiter = put(game, "BG34_925", a)
        murloc = make_minion("Murloc", 1, 5, race=Race.MURLOC)
        game.summon(a, murloc)                    # 右邻
        attack(game, recruiter, dummy(b))
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 1)
        self.assertIn(gained[0].race, (Race.MURLOC, Race.ALL))
        # 效果施法不做法术池操作 / 不产生手牌法术
        self.assertEqual([c for c in a.hand if not isinstance(c, Minion)],
                         [])

    def test_rally_rightmost_position_no_effect(self):
        game = make_game(seed=217)
        a, b = game.heroes
        game.summon(a, make_minion("M", 1, 5))    # 左侧占位
        recruiter = put(game, "BG34_925", a)      # 最右 → 无右邻
        attack(game, recruiter, dummy(b))
        self.assertEqual(a.hand, [])

    def test_golden_casts_twice(self):
        game = make_game(seed=218)
        a, b = game.heroes
        recruiter = put(game, "BG34_925", a, golden=True)
        murloc = make_minion("Murloc", 1, 5, race=Race.MURLOC)
        game.summon(a, murloc)
        attack(game, recruiter, dummy(b))
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 2)


class TestFlitteringBat(unittest.TestCase):
    """BG36_200 — Rally: Summon a {0}/{1} Beast."""

    def test_rally_summons_foraging_bat_token(self):
        game = make_game(seed=219)
        a, b = game.heroes
        d = get_db().get("BG36_200")
        bat = put(game, "BG36_200", a)
        attack(game, bat, dummy(b))
        tokens = [m for m in a.board if m.card_id == FORAGING_BAT_ID]
        self.assertEqual(len(tokens), 1)
        tdef = get_db().get(FORAGING_BAT_ID)
        self.assertEqual(tokens[0].atk, tdef.atk)         # token 定义权威
        self.assertEqual(tokens[0].max_health, tdef.health)
        self.assertEqual(tokens[0].race, Race.BEAST)
        self.assertEqual(d.num(0), tdef.atk)              # 显示参数一致
        self.assertEqual(d.num(1), tdef.health)

    def test_rally_full_board_no_summon(self):
        game = make_game(seed=220)
        a, b = game.heroes
        bat = put(game, "BG36_200", a)
        for i in range(BOARD_SIZE - 1):
            game.summon(a, make_minion(f"F{i}", 1, 1))
        self.assertTrue(a.board_full())
        attack(game, bat, dummy(b))
        self.assertEqual(len(a.board), BOARD_SIZE)
        self.assertNotIn(FORAGING_BAT_ID, [m.card_id for m in a.board])

    def test_golden_summons_two(self):
        game = make_game(seed=221)
        a, b = game.heroes
        bat = put(game, "BG36_200", a, golden=True)
        attack(game, bat, dummy(b))
        self.assertEqual(
            len([m for m in a.board if m.card_id == FORAGING_BAT_ID]), 2)


class TestHeadhunterGryphon(unittest.TestCase):
    """BG36_204 — Rally: Get a random Beast."""

    def test_rally_gets_random_beast_and_occupies_pool(self):
        game = make_game(seed=222)
        a, b = game.heroes
        gryphon = put(game, "BG36_204", a)
        attack(game, gryphon, dummy(b))
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 1)
        self.assertIn(gained[0].race, (Race.BEAST, Race.ALL))
        tier = get_db().get(gained[0].card_id).tech_level
        self.assertEqual(game.minion_pool.available(gained[0].card_id),
                         POOL_COPIES_BY_TIER[tier] - 1)

    def test_golden_gets_two(self):
        game = make_game(seed=223)
        a, b = game.heroes
        gryphon = put(game, "BG36_204", a, golden=True)
        attack(game, gryphon, dummy(b))
        self.assertEqual(
            len([c for c in a.hand if isinstance(c, Minion)]), 2)


class TestWolfPup(unittest.TestCase):
    """BG36_207 — Rally: Give your other minions +{0}/+{1}."""

    def test_rally_buffs_other_minions(self):
        game = make_game(seed=224)
        a, b = game.heroes
        d = get_db().get("BG36_207")
        pup = put(game, "BG36_207", a)
        m1, m2 = make_minion("M1", 1, 10), make_minion("M2", 2, 20)
        game.summon(a, m1)
        game.summon(a, m2)
        attack(game, pup, dummy(b))
        for m, base_a, base_h in ((m1, 1, 10), (m2, 2, 20)):
            self.assertEqual(m.atk, base_a + d.num(0))
            self.assertEqual(m.max_health, base_h + d.num(1))
        self.assertEqual(pup.atk, d.atk)
        self.assertEqual(pup.buffs, [])

    def test_rally_alone_no_effect(self):
        game = make_game(seed=225)
        a, b = game.heroes
        pup = put(game, "BG36_207", a)
        attack(game, pup, dummy(b))
        self.assertEqual(pup.buffs, [])

    def test_golden_uses_golden_values(self):
        game = make_game(seed=226)
        a, b = game.heroes
        dg = get_db().get("BG36_207_G")
        self.assertEqual((dg.num(0), dg.num(1)), (8, 2))
        pup = put(game, "BG36_207", a, golden=True)
        m = make_minion("M", 1, 10)
        game.summon(a, m)
        attack(game, pup, dummy(b))
        self.assertEqual(m.atk, 1 + dg.num(0))
        self.assertEqual(m.max_health, 10 + dg.num(1))


class TestDeathstrider(unittest.TestCase):
    """BG36_208 — After a friendly Rally minion attacks, trigger your
    left-most Deathrattle."""

    def test_friendly_rally_attack_triggers_leftmost_deathrattle(self):
        game = make_game(seed=227)
        a, b = game.heroes
        put(game, "BG36_208", a, position=0)
        boar = put(game, "BG20_101", a, position=1)   # Rally 随从
        put(game, "BG28_300", a, position=2)          # Harmless Bonehead DR
        before = len(a.board)
        attack(game, boar, dummy(b))
        # Bonehead 亡语: Summon two 1/1 Skeletons（无死亡触发）
        self.assertEqual(len(a.board), before + 2)
        self.assertEqual(
            len([c for c in a.hand if c.card_id == GEM_ID]), 1)  # boar rally

    def test_non_rally_attacker_does_not_trigger(self):
        game = make_game(seed=228)
        a, b = game.heroes
        put(game, "BG36_208", a, position=0)
        plain = make_minion("Plain", 3, 10)          # 无 Rally 的白板
        game.summon(a, plain)
        put(game, "BG28_300", a, position=2)
        before = len(a.board)
        attack(game, plain, dummy(b))
        self.assertEqual(len(a.board), before)

    def test_enemy_rally_attack_does_not_trigger(self):
        game = make_game(seed=229)
        a, b = game.heroes
        put(game, "BG36_208", a, position=0)
        put(game, "BG28_300", a, position=1)
        enemy_boar = put(game, "BG20_101", b)
        before = len(a.board)
        attack(game, enemy_boar, dummy(a))
        self.assertEqual(len(a.board), before)

    def test_no_deathrattle_bearer_no_effect(self):
        game = make_game(seed=230)
        a, b = game.heroes
        put(game, "BG36_208", a)
        boar = put(game, "BG20_101", a)
        attack(game, boar, dummy(b))
        self.assertEqual(len(a.board), 2)   # 无亡语触发不崩

    def test_golden_triggers_twice(self):
        game = make_game(seed=231)
        a, b = game.heroes
        put(game, "BG36_208", a, position=0, golden=True)
        boar = put(game, "BG20_101", a, position=1)
        put(game, "BG28_300", a, position=2)
        before = len(a.board)
        attack(game, boar, dummy(b))
        self.assertEqual(len(a.board), before + 4)   # 2 次 × 2 骷髅


class TestHoardingHyena(unittest.TestCase):
    """BG36_210 — Rally: Summon a Tasty Lobster."""

    def test_rally_summons_lobster_and_occupies_pool(self):
        game = make_game(seed=232)
        a, b = game.heroes
        hyena = put(game, "BG36_210", a)
        before = game.minion_pool.available(TASTY_LOBSTER_ID)
        self.assertGreater(before, 0)
        attack(game, hyena, dummy(b))
        lobsters = [m for m in a.board if m.card_id == TASTY_LOBSTER_ID]
        self.assertEqual(len(lobsters), 1)
        self.assertEqual(game.minion_pool.available(TASTY_LOBSTER_ID),
                         before - 1)

    def test_rally_pool_drained_no_summon(self):
        game = make_game(seed=233)
        a, b = game.heroes
        hyena = put(game, "BG36_210", a)
        while game.minion_pool.available(TASTY_LOBSTER_ID) > 0:
            self.assertTrue(game.minion_pool.acquire(TASTY_LOBSTER_ID))
        attack(game, hyena, dummy(b))
        self.assertNotIn(TASTY_LOBSTER_ID,
                         [m.card_id for m in a.board])

    def test_golden_summons_golden_lobster_costs_three_copies(self):
        game = make_game(seed=234)
        a, b = game.heroes
        hyena = put(game, "BG36_210", a, golden=True)
        before = game.minion_pool.available(TASTY_LOBSTER_ID)
        attack(game, hyena, dummy(b))
        lobsters = [m for m in a.board
                    if m.card_id == TASTY_LOBSTER_ID
                    or m.card_id == TASTY_LOBSTER_ID + "_G"]
        self.assertEqual(len(lobsters), 1)
        self.assertTrue(lobsters[0].is_golden)
        self.assertEqual(lobsters[0].card_id,
                         get_db().get(TASTY_LOBSTER_ID + "_G").id)
        self.assertEqual(game.minion_pool.available(TASTY_LOBSTER_ID),
                         before - GOLDEN_POOL_RETURN_COPIES)


class TestMightyDragonbreathSpell(unittest.TestCase):
    """BG36_246 — Give your minions +{0}/+{1}. Repeat for your Dragons.
    Repeat for your minions with Divine Shield.（Vindicator 效果施法本体）"""

    def _cast(self, game, hero):
        spell = game.create_spell(MIGHTY_DRAGONBREATH_ID, controller=hero)
        game.run_script_hook(spell, "on_play", ctx={})
        spell.zone = Zone.REMOVED

    def test_three_waves(self):
        game = make_game(seed=235)
        a, b = game.heroes
        d = get_db().get("BG36_246")
        vindicator = put(game, "BG36_241", a)     # 龙且带圣盾 → 3 波
        plain = make_minion("Plain", 1, 10)
        dragon = make_minion("Dragon", 2, 10, race=Race.DRAGON)
        game.summon(a, plain)
        game.summon(a, dragon)
        self._cast(game, a)
        # vindicator: wave1+2+3; plain: wave1; dragon: wave1+2
        self.assertEqual(vindicator.atk,
                         get_db().get("BG36_241").atk + d.num(0) * 3)
        self.assertEqual(vindicator.max_health,
                         get_db().get("BG36_241").health + d.num(1) * 3)
        self.assertEqual(plain.atk, 1 + d.num(0))
        self.assertEqual(plain.max_health, 10 + d.num(1))
        self.assertEqual(dragon.atk, 2 + d.num(0) * 2)
        self.assertEqual(dragon.max_health, 10 + d.num(1) * 2)

    def test_tavern_spell_extra_integration(self):
        game = make_game(seed=236)
        a, b = game.heroes
        d = get_db().get("BG36_246")
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 3)
        m = make_minion("M", 1, 10)
        game.summon(a, m)
        self._cast(game, a)
        self.assertEqual(m.atk, 1 + d.num(0))
        self.assertEqual(m.max_health, 10 + d.num(1) + 3)


class TestCrimsonVindicator(unittest.TestCase):
    """BG36_241 — Divine Shield; Rally: Cast Mighty Dragonbreath."""

    def test_rally_casts_dragonbreath(self):
        game = make_game(seed=237)
        a, b = game.heroes
        d = get_db().get("BG36_246")
        vindicator = put(game, "BG36_241", a)
        self.assertTrue(vindicator.has(GameTag.DIVINE_SHIELD))  # data
        plain = make_minion("Plain", 1, 10)
        game.summon(a, plain)
        attack(game, vindicator, dummy(b))
        # vindicator 自身 3 波 / plain 1 波
        self.assertEqual(vindicator.atk,
                         get_db().get("BG36_241").atk + d.num(0) * 3)
        self.assertEqual(plain.atk, 1 + d.num(0))

    def test_golden_casts_twice(self):
        game = make_game(seed=238)
        a, b = game.heroes
        d = get_db().get("BG36_246")
        vindicator = put(game, "BG36_241", a, golden=True)
        plain = make_minion("Plain", 1, 10)
        game.summon(a, plain)
        attack(game, vindicator, dummy(b))
        self.assertEqual(plain.atk, 1 + d.num(0) * 2)   # wave1 × 2 套


class TestBronzeTimewalker(unittest.TestCase):
    """BG36_242 — Rally: Get a random Chromadrake."""

    def test_rally_gets_chromadrake_without_pool(self):
        game = make_game(seed=239)
        a, b = game.heroes
        pool_before = game.minion_pool.total_remaining()
        walker = put(game, "BG36_242", a)
        attack(game, walker, dummy(b))
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 1)
        self.assertIn(gained[0].card_id, CHROMADRAKE_IDS)
        self.assertEqual(gained[0].race, Race.DRAGON)
        # 非池 token: 不占随从池
        self.assertEqual(game.minion_pool.total_remaining(), pool_before)

    def test_golden_gets_two(self):
        game = make_game(seed=240)
        a, b = game.heroes
        walker = put(game, "BG36_242", a, golden=True)
        attack(game, walker, dummy(b))
        self.assertEqual(
            len([c for c in a.hand if isinstance(c, Minion)]), 2)

    @unittest.skipUnless(XML_PATH.exists(), "hsdata CardDefs.xml absent")
    def test_chromadrake_ids_match_xml(self):
        """漂移守护: CHROMADRAKE_IDS == XML 名称以 Chromadrake 结尾的
        非金色 minion 全集。"""
        xml = XML_PATH.read_text(encoding="utf-8")
        found = set()
        for m in re.finditer(
                r'<Entity CardID="([^"]+)"[^>]*>(.*?)</Entity>', xml,
                re.S):
            cid, body = m.group(1), m.group(2)
            nm = re.search(r'name="CARDNAME".*?<enUS>([^<]*)</enUS>',
                           body, re.S)
            if not nm or not nm.group(1).endswith("Chromadrake"):
                continue
            if not re.search(r'name="CARDTYPE" type="Int" value="4"', body):
                continue
            if re.search(r'name="BACON_TRIPLED_BASE_MINION_ID"', body):
                continue   # 金色
            found.add(cid)
        self.assertEqual(found, set(CHROMADRAKE_IDS))


class TestSkyHatchRunaway(unittest.TestCase):
    """BG36_243 — Activate (1): Trigger a friendly minion's Rally.
    （[Targeted]——wiki tags 终裁，Kelp Keeper 同例）"""

    def test_activate_targets_rally_minion_and_triggers(self):
        game = make_game(seed=241)
        a, b = game.heroes
        runaway = put(game, "BG36_243", a)
        boar = put(game, "BG20_101", a)
        a.gold = 10
        ok = game.use_activate(a, runaway)
        self.assertTrue(ok)
        self.assertEqual(a.gold, 10 - get_db().get("BG36_243").num(0))
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "activate_target")
        self.assertIn(boar, choice.options)
        choice.choose(choice.options.index(boar))
        self.assertEqual(
            len([c for c in a.hand if c.card_id == GEM_ID]), 1)

    def test_activate_once_per_turn(self):
        game = make_game(seed=242)
        a, b = game.heroes
        runaway = put(game, "BG36_243", a)
        put(game, "BG20_101", a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, runaway))
        game.pending_choices.pop(0).choose(0)
        self.assertFalse(game.use_activate(a, runaway))   # 同回合第二次

    def test_activate_no_candidates_no_effect(self):
        game = make_game(seed=243)
        a, b = game.heroes
        runaway = put(game, "BG36_243", a)
        game.summon(a, make_minion("Plain", 1, 5))   # 无 Rally 白板
        a.gold = 10
        self.assertTrue(game.use_activate(a, runaway))    # 费用已扣
        self.assertEqual(a.gold, 10 - 1)
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(a.hand, [])

    def test_golden_triggers_twice(self):
        game = make_game(seed=244)
        a, b = game.heroes
        runaway = put(game, "BG36_243", a, golden=True)
        put(game, "BG20_101", a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, runaway))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(
            len([c for c in a.hand if c.card_id == GEM_ID]), 2)


class TestBrambleTunneler(unittest.TestCase):
    """BG36_331 — Rally: Get a random Choose One card."""

    def test_rally_gets_choose_one_card_and_occupies_pool(self):
        game = make_game(seed=245)
        a, b = game.heroes
        snap = {cid: game.spell_pool.available(cid)
                for cid in CHOOSE_ONE_SPELL_IDS}
        tunneler = put(game, "BG36_331", a)
        attack(game, tunneler, dummy(b))
        self.assertEqual(len(a.hand), 1)
        gained = a.hand[0]
        all_ids = CHOOSE_ONE_MINION_IDS | CHOOSE_ONE_SPELL_IDS
        self.assertIn(gained.card_id, all_ids)
        d = get_db().get(gained.card_id)
        if d.is_pool_spell:
            self.assertEqual(game.spell_pool.available(gained.card_id),
                             snap[gained.card_id] - 1)
        else:
            tier = d.tech_level
            self.assertEqual(game.minion_pool.available(gained.card_id),
                             POOL_COPIES_BY_TIER[tier] - 1)

    def test_rally_both_pools_drained_no_effect(self):
        game = make_game(seed=246)
        a, b = game.heroes
        for cid in CHOOSE_ONE_MINION_IDS:
            while game.minion_pool.available(cid) > 0:
                self.assertTrue(game.minion_pool.acquire(cid))
        for cid in CHOOSE_ONE_SPELL_IDS:
            while game.spell_pool.available(cid):   # 抽干（per-tier 副本）
                assert game.spell_pool.acquire(cid)
        tunneler = put(game, "BG36_331", a)
        attack(game, tunneler, dummy(b))
        self.assertEqual(a.hand, [])

    def test_golden_gets_two(self):
        game = make_game(seed=247)
        a, b = game.heroes
        tunneler = put(game, "BG36_331", a, golden=True)
        attack(game, tunneler, dummy(b))
        self.assertEqual(len(a.hand), 2)

    @unittest.skipUnless(XML_PATH.exists(), "hsdata CardDefs.xml absent")
    def test_choose_one_ids_match_xml(self):
        """漂移守护: Choose One id 集 == XML CHOOSE_ONE ∩ 池标志
        （minion: IS_BACON_POOL_MINION 非金色; spell: bg_pool_spells）。"""
        xml = XML_PATH.read_text(encoding="utf-8")
        minions, spells = set(), set()
        for m in re.finditer(
                r'<Entity CardID="([^"]+)"[^>]*>(.*?)</Entity>', xml,
                re.S):
            cid, body = m.group(1), m.group(2)
            if 'name="CHOOSE_ONE"' not in body:
                continue
            if re.search(
                    r'name="IS_BACON_POOL_MINION" type="Int" value="1"',
                    body) \
                    and not re.search(
                        r'name="BACON_TRIPLED_BASE_MINION_ID"', body) \
                    and re.search(
                        r'name="CARDTYPE" type="Int" value="4"', body):
                minions.add(cid)
        pool_spell_ids = {e["id"] for e in json.loads(
            (DATA_DIR / "bg_pool_spells.json").read_text(encoding="utf-8"))}
        for m in re.finditer(
                r'<Entity CardID="([^"]+)"[^>]*>(.*?)</Entity>', xml,
                re.S):
            cid, body = m.group(1), m.group(2)
            if 'name="CHOOSE_ONE"' in body and cid in pool_spell_ids:
                spells.add(cid)
        self.assertEqual(minions, set(CHOOSE_ONE_MINION_IDS))
        self.assertEqual(spells, set(CHOOSE_ONE_SPELL_IDS))


class TestRally2BatchRegistry(unittest.TestCase):
    """注册表健康度: 15 卡 + 金色链完整 + 2 法术 + DEFERRED 不注册。"""

    IMPLEMENTED = [
        "BG20_101", "BG20_104", "BG33_883", "BG33_885", "BG34_604",
        "BG34_925", "BG36_200", "BG36_204", "BG36_207", "BG36_208",
        "BG36_210", "BG36_241", "BG36_242", "BG36_243", "BG36_331",
    ]
    CAST_SPELLS = [CHEFS_CHOICE_ID, MIGHTY_DRAGONBREATH_ID]
    # BG36_351 Moat Custodian 已于 2026-08-21 解冻（ELEMENTAL_EXTRA_ATK
    # 1057 入册）——实现移册 batch_consume.py，本表不再锁定其 DEFERRED
    # BG36_333 Jailbird Juggernaut 已于 2026-08-22 由 batch_unfreeze
    # 解冻（execute_immediate_attack + GEMS_PLAYED_ON 原语）——同上
    DEFERRED: list[str] = []

    def test_registered_ids_exist_with_golden_chain(self):
        db = get_db()
        for cid in self.IMPLEMENTED:
            d = db.get(cid)
            self.assertIsNotNone(d, f"MISSING_DEF: {cid}")
            self.assertIn(cid, REGISTRY, f"MISSING_SCRIPT: {cid}")
            golden = db.golden_version(d)
            self.assertIsNotNone(golden, f"MISSING_GOLDEN: {cid}")
            self.assertIn(golden.id, REGISTRY,
                          f"MISSING_GOLDEN_SCRIPT: {cid}")
        for cid in self.CAST_SPELLS:
            self.assertIn(cid, REGISTRY)
        for cid in self.DEFERRED:
            self.assertNotIn(cid, REGISTRY, f"DEFERRED must not register")
        self.assertGreaterEqual(bind_all(db),
                                2 * len(self.IMPLEMENTED)
                                + len(self.CAST_SPELLS))


if __name__ == "__main__":
    unittest.main()
