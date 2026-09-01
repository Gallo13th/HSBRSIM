"""批次 spells4 池法术语义测试（作业单 2026-08-21，13 张）。

覆盖: BG31_881 Time Management / BG31_886 Forest's Bounty /
BG31_889 Sharing is Caring / BG31_890 Boundless Potential /
BG31_892 Fandral's Fortune（DEFERRED 断言）/ BG31_896 Hallowed
Ritual / BG32_815 Shifting Tide / BG33_101 A New Sprout /
BG33_811 Healthy Bounty / BG33_812 Hostile Bounty / BG33_813
Selfish Bounty / BG33_814 Friendly Bounty / BG33_815 Wealthy Bounty。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）。Choose One 法术
测两级 PendingChoice 流（spell_target → choose_one，或 choose_one →
discover）。施放走 game.play_spell（占池 → 入手 → 打出 → 回池）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

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


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def summon_plain(game: Game, hero: Hero, m: Minion,
                 position: int | None = None) -> Minion:
    game.summon(hero, m, position)
    return m


def cast(game: Game, hero: Hero, card_id: str,
         target=None) -> bool:
    """施放一张池法术（占池 → 入手 → play_spell）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return game.play_spell(hero, s, target=target)


def pop_choice(game: Game, kind: str):
    """取队首 PendingChoice 并断言 kind。"""
    pc = game.pending_choices.pop(0)
    assert pc.kind == kind, f"expect {kind}, got {pc.kind}"
    return pc


class TestRegistryState(unittest.TestCase):
    """批次注册面: 12 卡 OK; Fandral's Fortune DEFERRED 不注册。"""

    def test_all_cards_registered(self):
        for cid in ("BG31_881", "BG31_886", "BG31_889", "BG31_890",
                    "BG31_896", "BG32_815", "BG33_101", "BG33_811",
                    "BG33_812", "BG33_813", "BG33_814", "BG33_815"):
            self.assertIn(cid, REGISTRY)

    def test_fandral_unfrozen_by_batch_unfreeze(self):
        # 2026-08-22 batch_unfreeze 解冻: CHOOSE_BOTH 实体 tag +
        # per-entity 双效 override 管道（引擎 play_minion 消费实体级
        # tag; 法术侧由代理+override 抽干自队选择）
        self.assertIn("BG31_892", REGISTRY)
        game = make_game()
        s = game.create_spell("BG31_892", controller=game.heroes[0])
        self.assertIs(s.scripts, REGISTRY["BG31_892"])
        # 旧占位类（batch_spells4）仍为 no-op——保留作历史台账
        from hsrl2.scripts.batches.batch_spells4 import FandralsFortuneScript
        self.assertIsNone(
            FandralsFortuneScript.on_play(s, game, {}))


class TestTimeManagement(unittest.TestCase):
    """BG31_881 — Choose One: 立即全体 +{0}/+{1}; 或下回合开始 ×2。"""

    def test_choose_now_buffs_all(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        m1 = summon_plain(game, a, make_minion("M1", 3, 4))
        m2 = summon_plain(game, a, make_minion("M2", 5, 6))
        d = get_db().get("BG31_881")
        self.assertTrue(cast(game, a, "BG31_881"))
        pc = pop_choice(game, "choose_one")
        self.assertEqual(pc.options, ["now", "later"])
        pc.choose(0)
        self.assertEqual(m1.atk, 3 + d.num(0))
        self.assertEqual(m1.max_health, 4 + d.num(1))
        self.assertEqual(m2.atk, 5 + d.num(0))
        self.assertEqual(m2.max_health, 6 + d.num(1))

    def test_choose_later_buffs_next_turn_twice(self):
        game = make_game(seed=2)
        game.start_game()
        a = game.heroes[0]
        m1 = summon_plain(game, a, make_minion("M1", 3, 4))
        d = get_db().get("BG31_881")
        self.assertTrue(cast(game, a, "BG31_881"))
        pc = pop_choice(game, "choose_one")
        pc.choose(1)
        # 当回合不生效
        self.assertEqual(m1.atk, 3)
        self.assertEqual(m1.max_health, 4)
        # 施放后、回合结束前新买入的随从同样获益（目标延迟求值）
        m2 = summon_plain(game, a, make_minion("M2", 1, 1))
        game.end_recruit_phase()     # 战斗（空对空无伤）→ 下回合开始
        self.assertEqual(game.turn, 2)
        self.assertEqual(m1.atk, 3 + 2 * d.num(0))
        self.assertEqual(m1.max_health, 4 + 2 * d.num(1))
        self.assertEqual(m2.atk, 1 + 2 * d.num(0))
        self.assertEqual(m2.max_health, 1 + 2 * d.num(1))


class TestForestsBounty(unittest.TestCase):
    """BG31_886 — Choose One 定向: 单体 ×2 或全体 +{2}/{3}。"""

    def test_single_branch_two_applications(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        tgt = summon_plain(game, a, make_minion("T", 2, 3))
        other = summon_plain(game, a, make_minion("O", 7, 8))
        d = get_db().get("BG31_886")
        self.assertTrue(cast(game, a, "BG31_886"))
        # 第一级: spell_target
        pc = pop_choice(game, "spell_target")
        self.assertIn(tgt, pc.options)
        pc.choose(pc.options.index(tgt))
        # 第二级: choose_one
        pc = pop_choice(game, "choose_one")
        self.assertEqual(pc.options, ["single", "all"])
        pc.choose(0)
        self.assertEqual(tgt.atk, 2 + 2 * d.num(0))
        self.assertEqual(tgt.max_health, 3 + 2 * d.num(1))
        self.assertEqual(other.atk, 7)
        self.assertEqual(other.max_health, 8)

    def test_all_branch_buffs_board(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        m1 = summon_plain(game, a, make_minion("M1", 2, 3))
        m2 = summon_plain(game, a, make_minion("M2", 4, 5))
        d = get_db().get("BG31_886")
        self.assertTrue(cast(game, a, "BG31_886"))
        pop_choice(game, "spell_target").choose(0)
        pop_choice(game, "choose_one").choose(1)
        self.assertEqual(m1.atk, 2 + d.num(2))
        self.assertEqual(m1.max_health, 3 + d.num(3))
        self.assertEqual(m2.atk, 4 + d.num(2))
        self.assertEqual(m2.max_health, 5 + d.num(3))

    def test_empty_board_single_fizzles(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG31_886"))
        # 无目标候选 → 不产生 spell_target 选择，直接 choose_one
        pc = pop_choice(game, "choose_one")
        pc.choose(0)      # single 无 target → 落空，不抛异常
        self.assertEqual(game.pending_choices, [])


class TestSharingIsCaring(unittest.TestCase):
    """BG31_889 — 持久 SoC: 最左随从获得对位敌方属性。"""

    def _fire_soc(self, game, caster):
        game.events.fire(game, "start_of_combat", hero=caster)

    def test_leftmost_gains_nearest_enemy_stats(self):
        game = make_game(seed=1)
        a, b = game.heroes
        left = summon_plain(game, a, make_minion("L", 2, 3))
        right = summon_plain(game, a, make_minion("R", 9, 9))
        foe = summon_plain(game, b, make_minion("F", 5, 7))
        self.assertTrue(cast(game, a, "BG31_889"))
        game._active_combat = (a, b)
        try:
            self._fire_soc(game, a)
        finally:
            game._active_combat = None
        # 最左获得 +对位 atk/max_health; 次左不动
        self.assertEqual(left.atk, 2 + 5)
        self.assertEqual(left.max_health, 3 + 7)
        self.assertEqual(right.atk, 9)
        self.assertEqual(right.max_health, 9)
        # 敌方不受影响
        self.assertEqual(foe.atk, 5)

    def test_empty_opponent_board_fizzles(self):
        game = make_game(seed=2)
        a, b = game.heroes
        left = summon_plain(game, a, make_minion("L", 2, 3))
        self.assertTrue(cast(game, a, "BG31_889"))
        game._active_combat = (a, b)
        try:
            self._fire_soc(game, a)
        finally:
            game._active_combat = None
        self.assertEqual(left.atk, 2)
        self.assertEqual(left.max_health, 3)

    def test_not_fired_for_opponents_combat_slot(self):
        game = make_game(seed=3)
        a, b = game.heroes
        left = summon_plain(game, a, make_minion("L", 2, 3))
        foe = summon_plain(game, b, make_minion("F", 5, 7))
        self.assertTrue(cast(game, a, "BG31_889"))
        game._active_combat = (a, b)
        try:
            self._fire_soc(game, b)   # b 的英雄技能段——不触发 a 的监听
        finally:
            game._active_combat = None
        self.assertEqual(left.atk, 2)

    def test_full_cycle_reapplies_each_combat(self):
        """完整回合流: 战斗内生效、战后回滚、下场再触发。"""
        game = make_game(seed=4)
        game.start_game()
        a, b = game.heroes
        left = summon_plain(game, a, make_minion("L", 2, 3))
        foe = summon_plain(game, b, make_minion("F", 5, 7))
        self.assertTrue(cast(game, a, "BG31_889"))
        game.end_recruit_phase()
        # 战斗结束快照恢复 → SoC 战斗内 buff 回滚（每场重新给）
        self.assertEqual(left.atk, 2)
        self.assertEqual(left.max_health, 3)
        self.assertEqual(foe.atk, 5)
        # 再战一场（监听器持久）
        game._active_combat = (a, b)
        try:
            self._fire_soc(game, a)
        finally:
            game._active_combat = None
        self.assertEqual(left.atk, 2 + 5)
        self.assertEqual(left.max_health, 3 + 7)


class TestBoundlessPotential(unittest.TestCase):
    """BG31_890 — Choose One 双发现: 本级随从 或 本级酒馆法术。"""

    def test_minion_branch_discovers_own_tier(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 2)
        self.assertTrue(cast(game, a, "BG31_890"))
        pop_choice(game, "choose_one").choose(0)
        pc = pop_choice(game, "discover_minion")
        self.assertTrue(pc.options)
        for opt in pc.options:
            self.assertEqual(get_db().get(opt).tech_level, 2)
        pool_left = game.minion_pool.available(pc.options[0])
        pc.choose(0)
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(a.hand[0].card_id, pc.options[0])
        self.assertEqual(game.minion_pool.available(pc.options[0]),
                         pool_left - 1)

    def test_spell_branch_discovers_own_tier_spell(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 3)
        self.assertTrue(cast(game, a, "BG31_890"))
        pop_choice(game, "choose_one").choose(1)
        pc = pop_choice(game, "discover_tavern_spell")
        self.assertTrue(pc.options)
        for opt in pc.options:
            d = get_db().get(opt)
            self.assertTrue(d.is_pool_spell)
            self.assertEqual(d.tech_level, 3)
        pool_left = game.spell_pool.available(pc.options[0])
        pc.choose(0)
        picked = pc.options[0]
        self.assertEqual(len(a.hand), 1)
        self.assertIsInstance(a.hand[0], Spell)
        self.assertEqual(a.hand[0].card_id, picked)
        # 选中即占法术池 1 份
        self.assertEqual(game.spell_pool.available(picked), pool_left - 1)


class TestHallowedRitual(unittest.TestCase):
    """BG31_896 — Discover a Tier 7 minion。"""

    def test_discovers_tier7(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG31_896"))
        pc = pop_choice(game, "discover_minion")
        self.assertTrue(pc.options)
        for opt in pc.options:
            self.assertEqual(get_db().get(opt).tech_level, 7)
        pc.choose(0)
        self.assertEqual(a.hand[0].card_id, pc.options[0])
        self.assertEqual(game.minion_pool.available(pc.options[0]),
                         C.POOL_COPIES_BY_TIER[7] - 1)


class TestShiftingTide(unittest.TestCase):
    """BG32_815 — 定向 +{0}/+{1} ×2; Naga 目标整套重复（×4）。"""

    def test_non_naga_gets_two(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        tgt = summon_plain(game, a, make_minion("T", 2, 3, race=Race.MECH))
        d = get_db().get("BG32_815")
        self.assertTrue(cast(game, a, "BG32_815", target=tgt))
        self.assertEqual(game.pending_choices, [])   # 直接定向结算
        self.assertEqual(tgt.atk, 2 + 2 * d.num(0))
        self.assertEqual(tgt.max_health, 3 + 2 * d.num(1))

    def test_naga_gets_four(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        tgt = summon_plain(game, a, make_minion("N", 2, 3, race=Race.NAGA))
        d = get_db().get("BG32_815")
        self.assertTrue(cast(game, a, "BG32_815", target=tgt))
        self.assertEqual(tgt.atk, 2 + 4 * d.num(0))
        self.assertEqual(tgt.max_health, 3 + 4 * d.num(1))

    def test_amalgam_counts_as_naga(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        tgt = summon_plain(game, a, make_minion("A", 2, 3, race=Race.ALL))
        d = get_db().get("BG32_815")
        self.assertTrue(cast(game, a, "BG32_815", target=tgt))
        self.assertEqual(tgt.atk, 2 + 4 * d.num(0))

    def test_no_target_fizzles(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG32_815"))   # 空棋盘: 落空但消耗
        self.assertEqual(game.pending_choices, [])


class TestANewSprout(unittest.TestCase):
    """BG33_101 — Discover a Tier 1 minion。"""

    def test_discovers_tier1(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG33_101"))
        pc = pop_choice(game, "discover_minion")
        self.assertTrue(pc.options)
        for opt in pc.options:
            self.assertEqual(get_db().get(opt).tech_level, 1)
        pc.choose(0)
        self.assertEqual(a.hand[0].card_id, pc.options[0])
        self.assertEqual(game.minion_pool.available(pc.options[0]),
                         C.POOL_COPIES_BY_TIER[1] - 1)


class TestBountyFamily(unittest.TestCase):
    """BG33_811/812/813 — 海盗三连 bounty。"""

    def test_healthy_bounty_four_get_health(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        minions = [summon_plain(game, a, make_minion(f"M{i}", 1, 1))
                   for i in range(5)]
        d = get_db().get("BG33_811")
        self.assertTrue(cast(game, a, "BG33_811"))
        buffed = [m for m in minions if m.max_health == 1 + d.num(1)]
        self.assertEqual(len(buffed), 4)
        for m in minions:                     # 攻击不变（基础版无 {0}）
            self.assertEqual(m.atk, 1)

    def test_healthy_bounty_empty_board_fizzles(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG33_811"))
        self.assertEqual(a.hand, [])

    def test_hostile_bounty_four_get_attack(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        minions = [summon_plain(game, a, make_minion(f"M{i}", 1, 1))
                   for i in range(5)]
        d = get_db().get("BG33_812")
        self.assertTrue(cast(game, a, "BG33_812"))
        buffed = [m for m in minions if m.atk == 1 + d.num(0)]
        self.assertEqual(len(buffed), 4)
        for m in minions:                     # 生命不变（基础版无 {1}）
            self.assertEqual(m.max_health, 1)

    def test_selfish_bounty_leftmost_only(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        left = summon_plain(game, a, make_minion("L", 2, 3))
        right = summon_plain(game, a, make_minion("R", 4, 5))
        d = get_db().get("BG33_813")
        self.assertTrue(cast(game, a, "BG33_813"))
        self.assertEqual(left.atk, 2 + d.num(0))
        self.assertEqual(left.max_health, 3 + d.num(1))
        self.assertEqual(right.atk, 4)
        self.assertEqual(right.max_health, 5)


class TestFriendlyBounty(unittest.TestCase):
    """BG33_814 — Get a random minion of your most common type。"""

    def test_most_common_type(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        for _ in range(2):
            summon_plain(game, a, make_minion("B", 1, 1, race=Race.BEAST))
        summon_plain(game, a, make_minion("M", 1, 1, race=Race.MURLOC))
        self.assertTrue(cast(game, a, "BG33_814"))
        self.assertEqual(len(a.hand), 1)
        gained = a.hand[0]
        self.assertIn(get_db().get(gained.card_id).race,
                      (Race.BEAST, Race.ALL))
        self.assertEqual(game.minion_pool.available(gained.card_id),
                         C.POOL_COPIES_BY_TIER[
                             min(max(get_db().get(gained.card_id).tech_level,
                                     1), 7)] - 1)

    def test_no_typed_minions_unrestricted(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        summon_plain(game, a, make_minion("N", 1, 1))            # NONE
        summon_plain(game, a, make_minion("A", 1, 1, race=Race.ALL))
        self.assertTrue(cast(game, a, "BG33_814"))
        self.assertEqual(len(a.hand), 1)     # 不限族随从入手

    def test_empty_board_unrestricted(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG33_814"))
        self.assertEqual(len(a.hand), 1)


class TestWealthyBounty(unittest.TestCase):
    """BG33_815 — Gain 2 Gold（文本字面量）。"""

    def test_gains_two_gold(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        a.gold = 5
        self.assertTrue(cast(game, a, "BG33_815"))
        self.assertEqual(a.gold, 7)

    def test_capped_at_99(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        a.gold = 98
        self.assertTrue(cast(game, a, "BG33_815"))
        self.assertEqual(a.gold, C.GOLD_HOLD_CAP)


if __name__ == "__main__":
    unittest.main()
