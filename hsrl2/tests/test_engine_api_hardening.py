"""引擎 API 硬化契约测试（WS3 阶段 A，F-22 起）。

覆盖 `docs/ENGINE_RL_READINESS.md` 的 D 清单（本阶段只做仍未闭环项）：

- **D-9** `sell_minion` 类型校验：Spell 传入返回 False，且不污染状态
  （不移出手牌、不加金币、zone 不变）。
- **D-2** 解冻 API：`Game.unfreeze_tavern(hero)` + `tavern_frozen` /
  `tavern_unfrozen` 事件；默认 `freeze_tavern` 行为不变。
- **D-5** 名次 API：`Game.elimination_order` / `rank_of` / `final_ranking`
  由 `_process_eliminations` 维护（含真实 `end_recruit_phase` 路径）。
- **D-14** `Game.phase` 属性：recruit / combat / choice / game_over，
  与 `hsbg/env` 状态机同口径（finished > in_combat > pending_choices）。
- **D-3** 只读查询 API：`quote_buy_cost` / `can_buy` / `can_use_hero_power`
  / `next_tavern_tier` / `magnetic_targets` / `can_refresh`，以及与真实动作
  的**对拍**（报价 == 实际扣款；可用性 == 实调用返回值；peek 不消费）。
- **D-8** `CardDB.defs()` / `iter_defs()` / `hero_defs()` 公开迭代器。
- **D-15** `stats_gained` 抑制深度改 contextvars：嵌套/异常复原/线程隔离，
  且默认（单上下文）行为不变。
- **D-6** `GameRNG(seed, audit=False)` / `clear_decisions()`：默认审计行为
  不变，关闭审计不改变随机流。

约定：这些测试在**实现前应失败**（先红后绿）；实现后默认行为逐位不变。
"""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest import mock

from hsrl2 import constants as C
from hsrl2.db import CardDB
from hsrl2.defs import CardDef
from hsrl2.entity import Buff, _stats_gained_suppressed, suppress_stats_gained
from hsrl2.events import Listener
from hsrl2.game import Game, GameStateError, PendingChoice
from hsrl2.hero import Hero
from hsrl2.rng import GameRNG
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType, GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7, n: int = 2, hero_ids=None) -> Game:
    """构造最小对局（不 start_game；只装配实体/查询 API 所需状态）。"""
    import hsrl2.scripts  # noqa: F401  注册脚本（create_minion 绑定脚本用）
    if hero_ids is None:
        hero_ids = [f"TEST_HERO_{i}" for i in range(n)]
    heroes = [Hero(cid, f"P{i}") for i, cid in enumerate(hero_ids)]
    return Game(heroes, get_db(), seed=seed)


def shop_minion(game: Game, hero: Hero, card_id: str = "BG33_140"):
    """向酒馆注入一只随从（注入路径不占池；买入后不触发池释放逻辑）。"""
    return game.inject_tavern_minion(hero, card_id)


def shop_spell(game: Game, hero: Hero, card_id: str = "BG28_168"):
    """向酒馆注入一个酒馆法术。"""
    s = game.create_spell(card_id, controller=hero)
    return game.add_tavern_entity(hero, s)


def board_minion(game: Game, hero: Hero, card_id: str = "BG33_140"):
    m = game.create_minion(card_id, controller=hero)
    game.summon(hero, m)
    return m


# ══════════════════════════════════════════════════════════════════
# D-9 sell_minion 类型校验
# ══════════════════════════════════════════════════════════════════

class TestSellMinionTypeCheck(unittest.TestCase):
    """D-9：非 Minion 实体（Spell/None）必须返回 False 且状态零变化。"""

    def setUp(self):
        self.game = make_game(seed=11)
        self.hero = self.game.heroes[0]

    def test_spell_returns_false_without_state_pollution(self):
        spell = self.game.create_spell("BG28_168", controller=self.hero)
        self.hero.add_to_hand(spell)
        gold_before = self.hero.gold
        hand_before = list(self.hero.hand)
        zone_before = spell.zone

        ok = self.game.sell_minion(self.hero, spell)

        self.assertIs(ok, False)
        self.assertEqual(self.hero.gold, gold_before,
                         "Spell 出售失败不得加金币")
        self.assertEqual(self.hero.hand, hand_before,
                         "Spell 出售失败不得移出手牌")
        self.assertEqual(spell.zone, zone_before)
        self.assertNotIn(GameTag.MINIONS_SOLD_THIS_TURN, self.hero.tags,
                         "失败出售不得计数")

    def test_none_returns_false(self):
        self.assertIs(self.game.sell_minion(self.hero, None), False)

    def test_entity_returns_false(self):
        e = self.game.create_entity("BG28_168", controller=self.hero)
        self.hero.hand.append(e)
        gold_before = self.hero.gold
        self.assertIs(self.game.sell_minion(self.hero, e), False)
        self.assertEqual(self.hero.gold, gold_before)
        self.assertIn(e, self.hero.hand)

    def test_normal_minion_sell_unchanged(self):
        m = board_minion(self.game, self.hero)
        gold_before = self.hero.gold
        self.assertIs(self.game.sell_minion(self.hero, m), True)
        self.assertEqual(self.hero.gold, gold_before + C.MINION_SELL_VALUE)
        self.assertNotIn(m, self.hero.board)


# ══════════════════════════════════════════════════════════════════
# D-2 解冻 API
# ══════════════════════════════════════════════════════════════════

class TestUnfreezeTavern(unittest.TestCase):
    """D-2：解冻 API + 双向事件；freeze 默认行为不变。"""

    def setUp(self):
        self.game = make_game(seed=13)
        self.hero = self.game.heroes[0]
        self.frozen_events = []
        self.unfrozen_events = []
        self.game.events.register(Listener(
            event="tavern_frozen", owner=self.hero,
            callback=lambda game, **kw: self.frozen_events.append(kw["hero"])))
        self.game.events.register(Listener(
            event="tavern_unfrozen", owner=self.hero,
            callback=lambda game, **kw: self.unfrozen_events.append(kw["hero"])))

    def test_freeze_unfreeze_roundtrip(self):
        self.assertIs(self.game.freeze_tavern(self.hero), None)
        self.assertTrue(self.hero.frozen_tavern)
        self.assertEqual(self.frozen_events, [self.hero])

        gold_before = self.hero.gold
        tavern_before = list(self.hero.tavern)
        self.assertIs(self.game.unfreeze_tavern(self.hero), True)
        self.assertFalse(self.hero.frozen_tavern)
        self.assertEqual(self.unfrozen_events, [self.hero])
        self.assertEqual(self.hero.gold, gold_before, "解冻不产生费用")
        self.assertEqual(self.hero.tavern, tavern_before, "解冻不刷新酒馆")

    def test_unfreeze_when_not_frozen_returns_false_no_event(self):
        self.assertIs(self.game.unfreeze_tavern(self.hero), False)
        self.assertEqual(self.unfrozen_events, [])

    def test_freeze_idempotent_no_duplicate_event(self):
        self.game.freeze_tavern(self.hero)
        self.game.freeze_tavern(self.hero)
        self.assertEqual(self.frozen_events, [self.hero])

    def test_unfreeze_clears_whole_tavern_freeze_only(self):
        """只清整馆冻结（hero.FROZEN）；单卡冻结由刷新消费，不被本 API 触碰。"""
        single = shop_minion(self.game, self.hero)
        single.set(GameTag.FROZEN, True)
        self.game.freeze_tavern(self.hero)
        self.game.unfreeze_tavern(self.hero)
        self.assertFalse(self.hero.frozen_tavern)
        self.assertTrue(single.has(GameTag.FROZEN),
                        "单卡冻结语义由刷新窗口消费，解冻 API 只清整馆 tag")


# ══════════════════════════════════════════════════════════════════
# D-5 名次 API
# ══════════════════════════════════════════════════════════════════

class TestRankApi(unittest.TestCase):
    """D-5：elimination_order / rank_of / final_ranking。"""

    def _four_player_game(self):
        game = make_game(seed=17, n=4)
        return game, list(game.heroes)

    def test_initial_state(self):
        game, heroes = self._four_player_game()
        self.assertEqual(game.elimination_order, [])
        self.assertEqual(game.rank_of(heroes[0]), 1,
                         "存活英雄的当前名次 = 1（未被淘汰）")

    def test_elimination_order_and_rank(self):
        game, (a, b, c, d) = self._four_player_game()
        a, b, c, d = heroes = (game.heroes[0], game.heroes[1],
                               game.heroes[2], game.heroes[3])
        c.health = 0
        game._process_eliminations()
        self.assertEqual(game.elimination_order, [c])
        self.assertEqual(game.rank_of(c), 4, "第一个被淘汰 = 第 N 名")
        self.assertEqual(game.rank_of(a), 1)

        d.health = 0
        game._process_eliminations()
        self.assertEqual(game.elimination_order, [c, d])
        self.assertEqual(game.rank_of(d), 3)
        self.assertEqual(game.rank_of(c), 4)

    def test_rank_of_unknown_hero_raises(self):
        game, _heroes = self._four_player_game()
        with self.assertRaises(ValueError):
            game.rank_of(Hero("TEST_HERO_X", "X"))

    def test_final_ranking_requires_finished(self):
        game, _heroes = self._four_player_game()
        with self.assertRaises(GameStateError):
            game.final_ranking()

    def test_final_ranking_order(self):
        game, _heroes = self._four_player_game()
        a, b, c, d = game.heroes
        c.health = 0
        game._process_eliminations()
        b.health = 0
        game._process_eliminations()
        d.health = 0
        game._process_eliminations()
        self.assertEqual(len(game.heroes), 1)
        game.finished = True
        ranking = game.final_ranking()
        self.assertEqual(ranking, [a, d, b, c],
                         "第 1 名在前；淘汰顺序反序（最后死的 = 第 2 名）")

    def test_end_recruit_phase_maintains_elimination_order(self):
        """真实推进路径（`_process_eliminations` 在 ERP 内被调用）。"""
        game = make_game(seed=19)
        game.start_game()
        a, b = game.heroes
        b.health = 0
        game.end_recruit_phase()
        self.assertTrue(game.finished)
        self.assertEqual(game.elimination_order, [b])
        self.assertEqual(game.rank_of(a), 1)
        self.assertEqual(game.rank_of(b), 2)
        self.assertEqual(game.final_ranking(), [a, b])
        # 与 `hero_eliminated` 事件顺序同源（环境层 RankTracker 兼容）
        self.assertIsNot(b, a)


# ══════════════════════════════════════════════════════════════════
# D-14 Game.phase
# ══════════════════════════════════════════════════════════════════

class TestGamePhase(unittest.TestCase):
    """D-14：phase 语义 = finished > in_combat > pending_choices > recruit。"""

    def test_phases(self):
        game = make_game(seed=23)
        self.assertEqual(game.phase, "recruit")
        game.start_game()
        self.assertEqual(game.phase, "recruit")
        game.pending_choices.append(
            PendingChoice(game.heroes[0], ["a", "b"], "test_choice"))
        self.assertEqual(game.phase, "choice")
        game.pending_choices.clear()
        game.finished = True
        self.assertEqual(game.phase, "game_over")

    def test_combat_priority_over_choice(self):
        game = make_game(seed=29)
        game.in_combat = True
        game.pending_choices.append(
            PendingChoice(game.heroes[0], ["a"], "test_choice"))
        self.assertEqual(game.phase, "combat")
        game.finished = True
        self.assertEqual(game.phase, "game_over", "终局优先级最高")

    def test_phase_inside_real_combat(self):
        game = make_game(seed=31)
        a, b = game.heroes
        board_minion(game, a)
        board_minion(game, b)
        seen = []
        game.events.register(Listener(
            event="before_attack", owner=a,
            callback=lambda g, **kw: seen.append(g.phase)))
        game.run_combat(a, b)
        self.assertTrue(seen, "战斗内应触发 before_attack")
        self.assertTrue(all(p == "combat" for p in seen))
        self.assertEqual(game.phase, "recruit")


# ══════════════════════════════════════════════════════════════════
# D-3 只读查询 API
# ══════════════════════════════════════════════════════════════════

class TestNextTavernTier(unittest.TestCase):
    """D-3：next_tavern_tier 与 upgrade_tavern 落点对拍。"""

    def test_standard_ladder_matches_upgrade(self):
        game = make_game(seed=37)
        hero = game.heroes[0]
        for _ in range(game.max_tavern_tier - 1):
            hero.gold = 50
            nxt = game.next_tavern_tier(hero)
            self.assertEqual(nxt, hero.tavern_tier + 1)
            self.assertIs(game.upgrade_tavern(hero), True)
            self.assertEqual(hero.tavern_tier, nxt)
        self.assertIsNone(game.next_tavern_tier(hero))
        hero.gold = 50
        self.assertIs(game.upgrade_tavern(hero), False, "无下一档时升级失败")

    def test_anomaly_ladder(self):
        game = make_game(seed=41)
        hero = game.heroes[0]
        game._tavern_tier_ladder = (1, 3, 5)
        hero.set(GameTag.TAVERN_TIER, 1)
        hero.gold = 50
        self.assertEqual(game.next_tavern_tier(hero), 3)
        self.assertIs(game.upgrade_tavern(hero), True)
        self.assertEqual(hero.tavern_tier, 3)
        self.assertEqual(game.next_tavern_tier(hero), 5)
        hero.gold = 50
        self.assertIs(game.upgrade_tavern(hero), True)
        self.assertEqual(hero.tavern_tier, 5)
        self.assertIsNone(game.next_tavern_tier(hero))


class TestQuoteBuyCost(unittest.TestCase):
    """D-3：买价只读报价 == 真实扣款；peek 不消费免费额度/折扣。"""

    def setUp(self):
        self.game = make_game(seed=43)
        self.hero = self.game.heroes[0]
        self.hero.gold = 10

    def test_minion_quote_matches_actual_charge(self):
        m = shop_minion(self.game, self.hero)
        quote = self.game.quote_buy_cost(self.hero, m)
        self.assertEqual(quote, m.get(GameTag.COST, C.MINION_BUY_COST))
        gold_before = self.hero.gold
        self.assertIs(self.game.buy_from_tavern(self.hero, m), True)
        self.assertEqual(self.hero.gold, gold_before - quote)

    def test_spell_quote_matches_actual_charge_and_discount(self):
        s = shop_spell(self.game, self.hero)
        base = s.get(GameTag.COST, C.MINION_BUY_COST)
        self.assertEqual(self.game.quote_buy_cost(self.hero, s), base)
        self.hero.set(GameTag.NEXT_SPELL_COST_REDUCTION, 1)
        quote = self.game.quote_buy_cost(self.hero, s)
        self.assertEqual(quote, max(0, base - 1))
        gold_before = self.hero.gold
        self.assertIs(self.game.buy_from_tavern(self.hero, s), True)
        self.assertEqual(self.hero.gold, gold_before - quote)
        self.assertEqual(self.hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 0,
                         "成交后才消费折扣（报价不消费）")

    def test_minion_cost_override(self):
        m = shop_minion(self.game, self.hero)
        self.hero.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 1)
        self.assertEqual(self.game.quote_buy_cost(self.hero, m), 1)
        gold_before = self.hero.gold
        self.assertIs(self.game.buy_from_tavern(self.hero, m), True)
        self.assertEqual(self.hero.gold, gold_before - 1)

    def test_conditional_cost_rules(self):
        m = shop_minion(self.game, self.hero)
        self.hero._tavern_cost_rules = [(None, lambda e: True, 2)]
        self.assertEqual(self.game.quote_buy_cost(self.hero, m), 2)
        gold_before = self.hero.gold
        self.assertIs(self.game.buy_from_tavern(self.hero, m), True)
        self.assertEqual(self.hero.gold, gold_before - 2)

    def test_free_quota_peek_does_not_consume(self):
        m = shop_minion(self.game, self.hero)
        self.game.set_free_minion_buys(self.hero, 1, source="test_free")
        self.assertEqual(self.game.free_minion_buys_left(self.hero), 1)
        for _ in range(3):
            self.assertEqual(self.game.quote_buy_cost(self.hero, m), 0)
        self.assertIs(self.game.can_buy(self.hero, m), True)
        self.assertEqual(self.game.free_minion_buys_left(self.hero), 1,
                         "报价/可行性查询不得消费免费额度")
        self.assertNotIn(m, self.hero.hand, "查询不得移动实体")
        self.assertIn(m, self.hero.tavern, "查询不得移动实体")
        # peek 后真实购买仍然免费（结果不受 peek 影响），且消费额度
        gold_before = self.hero.gold
        self.assertIs(self.game.buy_from_tavern(self.hero, m), True)
        self.assertEqual(self.hero.gold, gold_before)
        self.assertEqual(self.game.free_minion_buys_left(self.hero), 0)
        self.assertIn(m, self.hero.hand, "购买结果不受 peek 影响")
        self.assertNotIn(m, self.hero.tavern)

    def test_quote_after_failed_buy_unchanged(self):
        m = shop_minion(self.game, self.hero)
        self.hero.gold = 1
        quote = self.game.quote_buy_cost(self.hero, m)
        self.assertGreater(quote, 1)
        self.assertIs(self.game.can_buy(self.hero, m), False)
        self.assertIs(self.game.buy_from_tavern(self.hero, m), False)
        self.assertEqual(self.hero.gold, 1)
        self.assertEqual(self.game.quote_buy_cost(self.hero, m), quote)

    def test_can_buy_rejects_entity_not_in_tavern(self):
        m = board_minion(self.game, self.hero)
        self.assertIs(self.game.can_buy(self.hero, m), False)

    def test_health_buy_affordability_and_payment(self):
        m = shop_minion(self.game, self.hero)
        m.set(GameTag.HEALTH_BUY, True)
        cost = self.game.quote_buy_cost(self.hero, m)
        self.hero.gold = 0
        self.hero.health = 30
        self.hero.armor = 0
        self.assertIs(self.game.can_buy(self.hero, m), True,
                      "强制以生命支付时金币无关")
        gold_before = self.hero.gold
        health_before = self.hero.health
        self.assertIs(self.game.buy_from_tavern(self.hero, m), True)
        self.assertEqual(self.hero.gold, gold_before)
        self.assertEqual(self.hero.health, health_before - cost,
                         "生命支付扣血量 == 报价")

    def test_health_buy_insufficient_health(self):
        m = shop_minion(self.game, self.hero)
        m.set(GameTag.HEALTH_BUY, True)
        self.hero.gold = 10
        self.hero.health = 1
        self.hero.armor = 0
        self.assertIs(self.game.can_buy(self.hero, m), False)
        gold_before = self.hero.gold
        self.assertIs(self.game.buy_from_tavern(self.hero, m), False)
        self.assertEqual(self.hero.gold, gold_before)
        self.assertEqual(self.hero.health, 1)


class _FakePower:
    """测试用合成英雄技能脚本（通过 REGISTRY patch 注入）。"""

    passive = False
    needs_target = False
    uses_per_turn = 1
    uses_per_game = None
    cost = 2

    def __init__(self):
        self.calls = 0

    def cost_override(self, hero, game):
        return self.cost

    def available(self, hero, game):
        return True

    def hero_power(self, hero, game, ctx=None):
        self.calls += 1
        return None


class TestCanUseHeroPower(unittest.TestCase):
    """D-3：can_use_hero_power == use_hero_power 的返回结果（对拍）。"""

    def setUp(self):
        self.game = make_game(seed=47, hero_ids=["BG21_HERO_010", "TEST_HERO_1"])
        self.hero = self.game.heroes[0]
        self.pid = self.game.hero_power_ids(self.hero)[0]
        self.assertIsNotNone(self.pid)

    def _patch(self, script):
        return mock.patch.dict(REGISTRY, {self.pid: script})

    def test_gold_gate_matches_actual(self):
        fake = _FakePower()
        with self._patch(fake):
            self.hero.gold = 1
            self.assertIs(self.game.can_use_hero_power(self.hero, self.pid),
                          False)
            self.assertIs(self.game.use_hero_power(self.hero,
                                                   power_id=self.pid), False)
            self.assertEqual(fake.calls, 0)

            self.hero.gold = 2
            self.assertIs(self.game.can_use_hero_power(self.hero, self.pid),
                          True)
            self.assertIs(self.game.use_hero_power(self.hero,
                                                   power_id=self.pid), True)
            self.assertEqual(fake.calls, 1)
            self.assertEqual(self.hero.gold, 0)
            # 次数用尽：查询与实际一致
            self.assertIs(self.game.can_use_hero_power(self.hero, self.pid),
                          False)
            self.assertIs(self.game.use_hero_power(self.hero,
                                                   power_id=self.pid), False)

    def test_unknown_power(self):
        self.assertIs(self.game.can_use_hero_power(self.hero, "NOT_A_POWER"),
                      False)

    def test_passive(self):
        fake = _FakePower()
        fake.passive = True
        with self._patch(fake):
            self.assertIs(self.game.can_use_hero_power(self.hero, self.pid),
                          False)
            self.assertIs(self.game.use_hero_power(self.hero,
                                                   power_id=self.pid), False)

    def test_available_false(self):
        fake = _FakePower()
        fake.available = staticmethod(lambda hero, game: False)
        with self._patch(fake):
            self.assertIs(self.game.can_use_hero_power(self.hero, self.pid),
                          False)
            self.assertIs(self.game.use_hero_power(self.hero,
                                                   power_id=self.pid), False)

    def test_target_power(self):
        class _TargetPower(_FakePower):
            needs_target = True
            target_candidates = staticmethod(lambda hero, game: [])

        fake = _TargetPower()
        with self._patch(fake):
            self.hero.gold = 10
            self.assertIs(self.game.can_use_hero_power(self.hero, self.pid),
                          False, "候选不足不可用")
            self.assertIs(self.game.use_hero_power(self.hero,
                                                   power_id=self.pid), False)
            self.assertEqual(fake.calls, 0)

            target = board_minion(self.game, self.hero)
            _TargetPower.target_candidates = staticmethod(
                lambda hero, game: [m for m in hero.board if not m.dead])
            self.assertIs(self.game.can_use_hero_power(self.hero, self.pid),
                          True)
            self.assertIs(self.game.use_hero_power(self.hero,
                                                   power_id=self.pid), True)
            self.assertEqual(len(self.game.pending_choices), 1,
                             "定向技能挂起目标选择")
            self.assertIs(target, self.game.pending_choices[0].options[0])


class TestMagneticTargets(unittest.TestCase):
    """D-3：magnetic_targets 与 play_minion(magnetic_target=) 对拍。"""

    MAGNETIC_ID = "BG26_146"        # Lullabot：Mech + Magnetic
    MECH_HOST_ID = "BG26_149"       # Polarizing Beatboxer：Mech 白板
    NON_MECH_HOST_ID = "BG20_100"   # Razorfen Geomancer：Quilboar

    def setUp(self):
        self.game = make_game(seed=53)
        self.hero = self.game.heroes[0]
        self.magnetic = self.game.create_minion(self.MAGNETIC_ID,
                                                controller=self.hero)
        self.hero.add_to_hand(self.magnetic)
        self.mech = board_minion(self.game, self.hero, self.MECH_HOST_ID)
        self.non_mech = board_minion(self.game, self.hero,
                                     self.NON_MECH_HOST_ID)

    def test_only_valid_hosts(self):
        targets = self.game.magnetic_targets(self.hero, self.magnetic)
        self.assertEqual(targets, [self.mech])

    def test_non_magnetic_minion_has_no_targets(self):
        self.assertEqual(self.game.magnetic_targets(self.hero, self.non_mech),
                         [])

    def test_dead_host_excluded(self):
        self.mech.set(GameTag.HEALTH, 0)
        self.assertEqual(self.game.magnetic_targets(self.hero, self.magnetic),
                         [])

    def test_query_result_is_accepted_by_real_action(self):
        targets = self.game.magnetic_targets(self.hero, self.magnetic)
        self.assertTrue(targets)
        host = targets[0]
        atk_before = host.atk
        self.assertIs(self.game.play_minion(self.hero, self.magnetic,
                                            magnetic_target=host), True)
        self.assertEqual(host.atk, atk_before + self.magnetic.atk,
                         "查询结果被真实吸附接受且属性并入")
        self.assertNotIn(self.magnetic, self.hero.hand)

    def test_invalid_host_rejected_by_real_action(self):
        self.assertIs(self.game.play_minion(self.hero, self.magnetic,
                                            magnetic_target=self.non_mech),
                      False)
        self.assertIn(self.magnetic, self.hero.hand)

    def test_data_exception_magnetic_targets(self):
        """数据例外（Prosthetic Hand 可吸亡灵）由 _magnetic_valid 承接。"""
        undead_host = board_minion(self.game, self.hero)
        undead_host.set(GameTag.RACES, None)   # 清空类型身份后按单类型设置
        undead_host.set(GameTag.RACE, Race.UNDEAD)
        prost = self.game.create_minion("BG_DEEP_015", controller=self.hero)
        self.hero.add_to_hand(prost)
        self.assertIn(undead_host,
                      self.game.magnetic_targets(self.hero, prost))


class TestCanRefresh(unittest.TestCase):
    """D-3：can_refresh 镜像 == 真实 refresh_tavern 是否抛异常/扣费。"""

    def setUp(self):
        self.game = make_game(seed=59)
        self.hero = self.game.heroes[0]
        for tag in (GameTag.FREE_REFRESH_REMAINING,
                    GameTag.HEALTH_REFRESHES_LEFT,
                    GameTag.TURN_SKIPPED):
            self.hero.clear(tag)
        self.hero.health = 30
        self.hero.armor = 0

    def test_no_gold(self):
        self.hero.gold = 0
        self.assertIs(self.game.can_refresh(self.hero), False)
        with self.assertRaises(GameStateError):
            self.game.refresh_tavern(self.hero)
        self.assertEqual(self.hero.gold, 0)

    def test_gold_and_charge_match(self):
        self.hero.gold = 5
        for _ in range(5):
            self.assertIs(self.game.can_refresh(self.hero), True)
            gold_before = self.hero.gold
            self.assertIsNone(self.game.refresh_tavern(self.hero))
            self.assertEqual(self.hero.gold, gold_before - C.REFRESH_COST)
        self.assertIs(self.game.can_refresh(self.hero), False)

    def test_free_refresh(self):
        self.hero.gold = 0
        self.hero.set(GameTag.FREE_REFRESH_REMAINING, 1)
        self.assertIs(self.game.can_refresh(self.hero), True)
        self.game.refresh_tavern(self.hero)
        self.assertEqual(self.hero.gold, 0)
        self.assertEqual(self.hero.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)

    def test_health_refresh(self):
        self.hero.gold = 0
        self.hero.set(GameTag.HEALTH_REFRESHES_LEFT, 1)
        self.assertIs(self.game.can_refresh(self.hero), True)
        self.game.refresh_tavern(self.hero)
        self.assertEqual(self.hero.gold, 0)
        self.assertEqual(self.hero.health, 30 - C.REFRESH_COST)
        self.assertEqual(self.hero.get(GameTag.HEALTH_REFRESHES_LEFT, 0), 0)

    def test_health_refresh_insufficient_falls_back_to_gold(self):
        self.hero.gold = 0
        self.hero.health = 1
        self.hero.set(GameTag.HEALTH_REFRESHES_LEFT, 1)
        self.assertIs(self.game.can_refresh(self.hero), False)
        with self.assertRaises(GameStateError):
            self.game.refresh_tavern(self.hero)
        self.assertEqual(self.hero.health, 1)

    def test_turn_skipped_and_blocked(self):
        self.hero.gold = 5
        self.hero.set(GameTag.TURN_SKIPPED, True)
        self.assertIs(self.game.can_refresh(self.hero), False)
        self.assertIsNone(self.game.refresh_tavern(self.hero))
        self.assertEqual(self.hero.gold, 5)
        self.hero.clear(GameTag.TURN_SKIPPED)
        self.game._block_manual_refresh = True
        self.assertIs(self.game.can_refresh(self.hero), False)


# ══════════════════════════════════════════════════════════════════
# D-8 CardDB 公开迭代器
# ══════════════════════════════════════════════════════════════════

class TestCardDBIterators(unittest.TestCase):
    def test_defs_covers_all(self):
        db = get_db()
        defs = list(db.defs())
        self.assertEqual(len(defs), len(db))
        self.assertTrue(all(isinstance(d, CardDef) for d in defs))
        self.assertTrue(all(db.get(d.id) is d for d in defs))

    def test_defs_returns_independent_list(self):
        db = get_db()
        first = db.defs()
        first.clear()
        self.assertEqual(len(db.defs()), len(db))

    def test_iter_defs(self):
        db = get_db()
        ids = [d.id for d in db.iter_defs()]
        self.assertEqual(len(ids), len(db))
        self.assertEqual(len(set(ids)), len(db))

    def test_hero_defs(self):
        db = get_db()
        heroes = db.hero_defs()
        self.assertTrue(heroes)
        self.assertTrue(all(d.card_type == CardType.HERO for d in heroes))
        expected = [d for d in db.defs() if d.card_type == CardType.HERO]
        self.assertEqual({d.id for d in heroes}, {d.id for d in expected})


# ══════════════════════════════════════════════════════════════════
# D-15 stats_gained 抑制上下文（contextvars）
# ══════════════════════════════════════════════════════════════════

class TestStatsSuppressedContextLocal(unittest.TestCase):
    def test_default_not_suppressed(self):
        self.assertIs(_stats_gained_suppressed(), False)

    def test_nested_and_restore(self):
        self.assertIs(_stats_gained_suppressed(), False)
        with suppress_stats_gained():
            self.assertIs(_stats_gained_suppressed(), True)
            with suppress_stats_gained():
                self.assertIs(_stats_gained_suppressed(), True)
            self.assertIs(_stats_gained_suppressed(), True)
        self.assertIs(_stats_gained_suppressed(), False)

    def test_exception_restores(self):
        with self.assertRaises(RuntimeError):
            with suppress_stats_gained():
                raise RuntimeError("boom")
        self.assertIs(_stats_gained_suppressed(), False)

    def test_thread_isolation(self):
        """线程 A 的抑制窗口不得静默线程 B 的 stats_gained 广播。"""
        entered = threading.Event()
        release = threading.Event()
        seen = {}

        def worker():
            with suppress_stats_gained():
                seen["worker_in"] = _stats_gained_suppressed()
                entered.set()
                release.wait(5)
                seen["worker_after"] = _stats_gained_suppressed()

        t = threading.Thread(target=worker)
        t.start()
        try:
            self.assertTrue(entered.wait(5), "worker 未进入抑制窗口")
            seen["main_in"] = _stats_gained_suppressed()
            # 主线程 add_buff 仍应广播 stats_gained（未被 worker 抑制）
            game = make_game(seed=61)
            hero = game.heroes[0]
            fired = []
            game.events.register(Listener(
                event="stats_gained", owner=hero,
                callback=lambda g, **kw: fired.append(kw)))
            m = board_minion(game, hero)
            m.add_buff(Buff(atk=1, health=1))
            seen["broadcast"] = len(fired)
        finally:
            release.set()
            t.join(5)
        self.assertIs(seen["worker_in"], True)
        self.assertIs(seen["worker_after"], True)
        self.assertIs(seen["main_in"], False)
        self.assertEqual(seen["broadcast"], 1)


# ══════════════════════════════════════════════════════════════════
# D-6 GameRNG 审计开关 / 清理
# ══════════════════════════════════════════════════════════════════

class TestGameRNGAudit(unittest.TestCase):
    def test_default_audit_unchanged(self):
        rng = GameRNG(71)
        picks = [rng.choice(range(100), label="pick") for _ in range(5)]
        self.assertEqual(len(rng.decisions), 5)
        ref = GameRNG(71)
        ref_picks = [ref.choice(range(100), label="pick") for _ in range(5)]
        self.assertEqual(picks, ref_picks)
        self.assertEqual(len(ref.decisions), 5)

    def test_audit_false_keeps_stream_identical(self):
        off = GameRNG(73, audit=False)
        on = GameRNG(73)
        self.assertEqual(
            [off.choice(range(100), label="pick") for _ in range(5)],
            [on.choice(range(100), label="pick") for _ in range(5)])
        self.assertEqual(off.decisions, [])
        off.sample(range(100), 3, label="sample")
        off.shuffle(list(range(10)), label="shuffle")
        self.assertEqual(off.decisions, [])

    def test_clear_decisions_preserves_stream(self):
        a = GameRNG(79)
        b = GameRNG(79)
        for _ in range(4):
            a.choice(range(50), label="q")
            b.choice(range(50), label="q")
        a.clear_decisions()
        self.assertEqual(a.decisions, [])
        self.assertEqual(a.choice(range(50)), b.choice(range(50)))

    def test_game_uses_auditing_rng_by_default(self):
        game = make_game(seed=83)
        self.assertIs(game.rng.audit, True)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
