"""批次 quest_rewards6 语义测试（作业单 2026-09-15）——两个新读取点。

覆盖 2 个注册任务奖励（真实引擎路径: `Game(...)` + `start_game()` +
`hero._quest_reward_id` + `game.complete_quest(hero)`）:
  - BG27_Reward_812 Scepter of Guidance（每次刷新保证 2 个纳迦展示位）
  - BG28_Reward_501 Temporal Tampering（酒馆法术多结算 1 次）

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都配**正对照**;
数值期望从 `CardDef.num(i)` 计算; 种子固定以钉住池抽取; owner 隔离用
2 英雄（只有被绑定的英雄获得效果）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

HERO_A = "BG20_HERO_103"
SCEPTER = "BG27_Reward_812"
TEMPORAL = "BG28_Reward_501"
BANANA = "BG28_897"          # 定向酒馆法术 +{0}/+{1}
LANTERN = "BG28_885"         # 生成 token 法术（非池）


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 40) -> Game:
    heroes = [Hero(HERO_A, "A"), Hero(HERO_A, "B")]
    g = Game(heroes, get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero, reward_id: str) -> None:
    hero._quest_reward_id = reward_id
    game.complete_quest(hero)


def play_pool_spell(game: Game, hero, target: Minion) -> None:
    spell = game.create_spell(BANANA, controller=hero)
    hero.hand.append(spell)
    spell.zone = Zone.HAND
    game.play_spell(hero, spell, target=target)


def naga_eligible(m: Minion) -> bool:
    # 类型身份集合（AC-3）: 双类型纳迦（如 BG32_820 DRAGON+NAGA）也是纳迦
    # ——wiki `Multi-type minion` revid 855346。
    return m.has_race(Race.NAGA)


class TestScepterOfGuidance(unittest.TestCase):
    """BG27_Reward_812 — 每次刷新前 2 个随从位保证为纳迦。"""

    def test_binding_sets_hero_race_guarantee(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(SCEPTER)
        self.assertIsNone(getattr(a, "_tavern_race_guarantee", None))
        bind(game, a, SCEPTER)
        self.assertIn(SCEPTER, REGISTRY)
        self.assertEqual(getattr(a, "_tavern_race_guarantee", None),
                         (Race(d.num(0)), 2))

    def test_first_two_slots_are_naga(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        bind(game, a, SCEPTER)
        game.refresh_tavern(a, free=True)
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertGreaterEqual(len(minions), 2)
        self.assertTrue(naga_eligible(minions[0]))
        self.assertTrue(naga_eligible(minions[1]))

    def test_guarantee_is_permanent_across_refreshes(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        bind(game, a, SCEPTER)
        for _ in range(2):
            game.refresh_tavern(a, free=True)
            minions = [e for e in a.tavern if isinstance(e, Minion)]
            self.assertTrue(naga_eligible(minions[0]))
            self.assertTrue(naga_eligible(minions[1]))

    def test_owner_isolation_opponent_unaffected(self):
        game = make_game(seed=53)
        a, b = game.heroes
        for h in (a, b):
            h.set(GameTag.TAVERN_TIER, 6)
        bind(game, a, SCEPTER)
        self.assertIsNone(getattr(b, "_tavern_race_guarantee", None))
        game.refresh_tavern(b, free=True)
        minions = [e for e in b.tavern if isinstance(e, Minion)]
        # 固定种子: 对手前 2 位至少 1 个非纳迦（无保证）
        self.assertTrue(any(not naga_eligible(m) for m in minions[:2]))

    def test_pool_exhaustion_falls_back_without_injection(self):
        game = make_game(seed=54)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        bind(game, a, SCEPTER)
        # 人为抽干纳迦池 → 保证位无候选。用 `purge`（**永久**移除，
        # 刷新的"旧内容回池"不会复原）——否则被删的纳迦副本会被
        # `refresh_tavern` 回池（2026-09-21: 多类型身份使"纳迦"集合
        # 变大，旧 `del _available` 的候选集随 rng 漂移而不再真正抽干）。
        for cid in list(game.minion_pool._available):
            d = get_db().get(cid)
            if d is not None and Race.NAGA in d.races:
                game.minion_pool.purge(cid)
        game.refresh_tavern(a, free=True)
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        from hsrl2 import constants as C
        self.assertEqual(len(minions), C.TAVERN_OFFERS.get(6, 6))
        # 池已抽干 → 不注入: 无任何纳迦出现，但总位数不变
        self.assertFalse(any(m.has_race(Race.NAGA) for m in minions))


class TestTemporalTampering(unittest.TestCase):
    """BG28_Reward_501 — 酒馆法术多结算 1 次（永久; 非池法术不受影响）。"""

    def test_pool_spell_is_doubled(self):
        game = make_game(seed=61)
        a = game.heroes[0]
        d = get_db().get(BANANA)
        bind(game, a, TEMPORAL)
        target = game.create_minion("BG25_001", controller=a)
        game.summon(a, target)
        base_atk, base_hp = target.atk, target.max_health
        play_pool_spell(game, a, target)
        self.assertEqual(target.atk, base_atk + d.num(0) * 2)
        self.assertEqual(target.max_health, base_hp + d.num(1) * 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 2)

    def test_non_pool_spell_single_cast(self):
        game = make_game(seed=62)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        bind(game, a, TEMPORAL)
        target = game.create_minion("BG25_001", controller=a)
        game.summon(a, target)
        base_atk = target.atk
        spell = game.create_spell(LANTERN, controller=a)
        a.hand.append(spell)
        spell.zone = Zone.HAND
        game.play_spell(a, spell, target=target)
        self.assertEqual(target.atk, base_atk + 6)      # 单次（+tier）
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), 0)

    def test_second_spell_same_turn_still_doubled(self):
        game = make_game(seed=63)
        a = game.heroes[0]
        d = get_db().get(BANANA)
        bind(game, a, TEMPORAL)
        for _ in range(2):
            t = game.create_minion("BG25_001", controller=a)
            game.summon(a, t)
            base = t.atk
            play_pool_spell(game, a, t)
            self.assertEqual(t.atk, base + d.num(0) * 2)

    def test_owner_isolation_opponent_single(self):
        game = make_game(seed=64)
        a, b = game.heroes
        d = get_db().get(BANANA)
        bind(game, a, TEMPORAL)
        t = game.create_minion("BG25_001", controller=b)
        game.summon(b, t)
        base = t.atk
        play_pool_spell(game, b, t)
        self.assertEqual(t.atk, base + d.num(0))        # 对手无奖励 → 单次

    def test_stacks_with_spell_first(self):
        game = make_game(seed=65)
        a = game.heroes[0]
        d = get_db().get(BANANA)
        bind(game, a, TEMPORAL)
        a.extra_triggers["spell_first"] = 1
        t = game.create_minion("BG25_001", controller=a)
        game.summon(a, t)
        base = t.atk
        play_pool_spell(game, a, t)
        self.assertEqual(t.atk, base + d.num(0) * 3)

    def test_second_copy_accumulates(self):
        """多来源叠加（idempotent-free accumulate）。"""
        game = make_game(seed=66)
        a = game.heroes[0]
        bind(game, a, TEMPORAL)
        bind(game, a, TEMPORAL)
        self.assertEqual(a.extra_trigger("tavern_spell_extra_cast"), 2)


if __name__ == "__main__":
    unittest.main()
