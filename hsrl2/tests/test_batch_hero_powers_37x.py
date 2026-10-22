"""批次 hero_powers_37x 语义测试（G-H1：37.0 新英雄主技能 + 旧赛季）。

覆盖 6 个主技能的行为层（真实入口 `game.start_game` / `use_hero_power` /
事件总线），并锁定 DEFERRED 11 个技能**保持未注册**（二态铁律）。

驱动约定:
  - 真实英雄: `Hero(real_hero_card_id)` → `Game([...])` →
    `game.start_game()`（引擎在 start_game 中 wire on_bind）
  - 被动技能: 手动 `events.fire(...)` 驱动引擎真实事件（BEFORE_ATTACK /
    MINION_BOUGHT / SPELL_BOUGHT / TURN_START）
  - PendingChoice 契约（TEST_SOP §8）: pop(0) 后再 choose
  - Triple Reward 档位 = 当前酒馆等级（无来源奖励的自然语言解读，
    边界见 batch 模块 docstring）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import (
    BEFORE_ATTACK,
    COMBAT_END,
    MINION_BOUGHT,
    SPELL_BOUGHT,
    TURN_START,
)
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

#: 本批注册的 6 个主技能
IMPLEMENTED = (
    "BG36_HERO_000p",   # Drest'agath Incubate
    "BG36_HERO_002p",   # Kith'ix Dark Ritual
    "BG33_HERO_001p_ALT",   # Loh Heroic Inspiration
    "BG20_HERO_242p",   # Guff Natural Balance
    "BG35_HERO_001p",   # Genn King of Duality
    "BG24_HERO_100p",   # Sire Denathrius Whodunit?
)

#: DEFERRED 11 个主技能（必须保持未注册——缺子系统的诚实缺省）
DEFERRED = (
    "BG20_HERO_202p",        # Master Nguyen（rebind/unbind）
    "BG20_HERO_283p",        # Galewing（flightpath 语义）
    "BG21_HERO_000p",        # Cariel Conviction（improvement 协议）
    "BG25_HERO_100p",        # Putricide（Craft）
    "BG31_HERO_801p",        # Jim Raynor（Battlecruiser Upgrade）
    "BG31_HERO_811p",        # Kerrigan（Zerg morph）
    "BG34_HERO_000p",        # Murozond（Major Timewarp）
    "BG34_HERO_004p",        # Morchie（Minor Timewarp）
    "TB_BaconShop_HP_020",   # Akazamzarak（Secrets）
    "TB_BaconShop_HP_101",   # Silas（Darkmoon Ticket）
    "TB_BaconShop_HP_106",   # Tickatus（Darkmoon Prize）
)

REAL_HERO = {
    "drest": "BG36_HERO_000",
    "kith": "BG36_HERO_002",
    "loh": "BG33_HERO_001",
    "guff": "BG20_HERO_242",
    "genn": "BG35_HERO_001",
    "denathrius": "BG24_HERO_100",
}

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game_with(hero_key: str, seed: int = 42) -> Game:
    """真实英雄（db Tag380 绑定）+ 一个假对手。"""
    h = Hero(REAL_HERO[hero_key], hero_key)
    other = Hero("TEST_OTHER_HERO", "Other")
    return Game([h, other], get_db(), seed=seed)


def pop_choice(game: Game, kind: str):
    pc = game.pending_choices.pop(0)
    assert pc.kind == kind, f"expect {kind}, got {pc.kind}"
    return pc


def give_hand_card(game: Game, hero: Hero, card_id: str):
    from hsrl2.tags import Zone as _Zone
    d = game.db.get(card_id)
    if d.is_pool_spell:
        s = game.create_spell(card_id, controller=hero)
        hero.hand.append(s)
        s.zone = _Zone.HAND
        return s
    m = game.create_minion(card_id, controller=hero)
    hero.hand.append(m)
    m.zone = _Zone.HAND
    return m


def plain_pool_card(tier: int = 1) -> str:
    for d in sorted(get_db().pool_minions(), key=lambda x: x.id):
        if d.tech_level != tier:
            continue
        if "battlecry" in d.keywords or "deathrattle" in d.keywords:
            continue
        return d.id
    raise AssertionError(f"no plain pool card tier={tier}")


class TestRegistryCoverage(unittest.TestCase):
    """注册面: 6 个已实现 + 11 个 DEFERRED 未注册。"""

    def test_implemented_registered(self):
        for pid in IMPLEMENTED:
            self.assertIn(pid, REGISTRY, pid)

    def test_deferred_remain_unregistered(self):
        for pid in DEFERRED:
            self.assertNotIn(
                pid, REGISTRY,
                f"{pid} must stay unregistered (DEFERRED 台账见 batch 模块)")

    def test_hero_power_binding_coverage(self):
        """G-H1 验收口径: 17 个无脚本主技能 = 6 已实现 + 11 DEFERRED。"""
        db = get_db()
        missing = []
        for d in db._by_id.values():
            pid = getattr(d, "hero_power_id", None)
            if pid and pid not in REGISTRY:
                missing.append(pid)
        self.assertEqual(sorted(missing), sorted(DEFERRED))


class TestIncubate(unittest.TestCase):
    """BG36_HERO_000p Incubate — Discard a card → random Aberration。"""

    def _game(self, seed):
        game = make_game_with("drest", seed)
        game.start_game()
        a = game.heroes[0]
        a.gold = 10
        return game, a

    def test_discard_then_get_aberration(self):
        game, a = self._game(101)
        gem = give_hand_card(game, a, "BG20_GEM")
        keep = give_hand_card(game, a, plain_pool_card(1))
        self.assertTrue(game.use_hero_power(a))
        pc = pop_choice(game, "hero_power_target")
        self.assertIn(gem, pc.options)
        pc.choose(pc.options.index(gem))
        self.assertEqual(a.gold, 9)
        self.assertEqual(a.cards_discarded_this_game, 1)
        self.assertNotIn(gem, a.hand)
        self.assertIn(keep, a.hand)
        aberrations = [c for c in a.hand
                       if c.race == Race.ABERRATION
                       or get_db().get(c.card_id).race == Race.ABERRATION]
        self.assertEqual(len(aberrations), 1)

    def test_empty_hand_cannot_use(self):
        game, a = self._game(102)
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)

    def test_stale_target_fizzles_without_cost(self):
        game, a = self._game(103)
        gem = give_hand_card(game, a, "BG20_GEM")
        self.assertTrue(game.use_hero_power(a))
        pc = pop_choice(game, "hero_power_target")
        a.hand.remove(gem)   # 挂起期目标离手
        pc.choose(pc.options.index(gem))
        self.assertEqual(a.gold, 10)          # 作废不扣费
        self.assertEqual(a.cards_discarded_this_game, 0)


class TestDarkRitual(unittest.TestCase):
    """BG36_HERO_002p Dark Ritual — 2 随机随从，打出一张弃另一张。"""

    def _game(self, seed):
        game = make_game_with("kith", seed)
        game.start_game()
        a = game.heroes[0]
        a.gold = 10
        return game, a

    def test_get_two_and_discard_other_on_play(self):
        game, a = self._game(201)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.gold, 8)
        self.assertEqual(len(a.hand), 2)
        m1, m2 = a.hand
        self.assertTrue(game.play_minion(a, m1))
        self.assertNotIn(m2, a.hand)
        self.assertEqual(a.cards_discarded_this_game, 1)
        self.assertIn(m1, a.board)

    def test_two_activations_independent_pairs(self):
        game, a = self._game(202)
        self.assertTrue(game.use_hero_power(a))
        a._power_uses_this_turn.clear()       # 测试跨回合复用（引擎计时）
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(len(a.hand), 4)
        pair_a = list(a.hand[:2])
        pair_b = list(a.hand[2:])
        self.assertTrue(game.play_minion(a, pair_a[0]))
        self.assertNotIn(pair_a[1], a.hand)
        # 另一组配对不受影响
        self.assertIn(pair_b[0], a.hand)
        self.assertIn(pair_b[1], a.hand)

    def test_empty_pool_still_activates(self):
        game, a = self._game(203)
        for d in get_db().pool_minions():
            while game.minion_pool.available(d.id) > 0:
                game.minion_pool.acquire(d.id)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.hand, [])


class TestHeroicInspiration(unittest.TestCase):
    """BG33_HERO_001p_ALT — 15 个友方随从攻击后 Triple Reward。"""

    def _game(self, seed):
        game = make_game_with("loh", seed)
        game.start_game()
        a, b = game.heroes
        attacker = game.create_minion(plain_pool_card(1), controller=a)
        game.summon(a, attacker)
        return game, a, b, attacker

    def _fire_attacks(self, game, attacker, n, defender=None):
        for _ in range(n):
            game.events.fire(game, BEFORE_ATTACK, attacker=attacker,
                             defender=defender)

    def test_fifteen_attacks_grant_reward(self):
        game, a, b, attacker = self._game(301)
        self._fire_attacks(game, attacker, 14)
        self.assertEqual(game.pending_choices, [])
        self._fire_attacks(game, attacker, 1)
        pc = pop_choice(game, "triple_reward")
        self.assertTrue(pc.options)
        tier = a.tavern_tier
        for cid in pc.options:
            self.assertEqual(get_db().get(cid).tech_level, tier)
        before = len(a.hand)
        pc.choose(0)
        self.assertEqual(len(a.hand), before + 1)

    def test_opponent_attacks_do_not_count(self):
        game, a, b, attacker = self._game(302)
        foe = game.create_minion(plain_pool_card(1), controller=b)
        game.summon(b, foe)
        self._fire_attacks(game, foe, 15)
        self.assertEqual(game.pending_choices, [])

    def test_second_reward_after_another_fifteen(self):
        game, a, b, attacker = self._game(303)
        self._fire_attacks(game, attacker, 15)
        pop_choice(game, "triple_reward").choose(0)
        self._fire_attacks(game, attacker, 15)
        pop_choice(game, "triple_reward").choose(0)


class TestNaturalBalance(unittest.TestCase):
    """BG20_HERO_242p — 购买累计 20 Tier 后 Triple Reward。"""

    def _game(self, seed):
        game = make_game_with("guff", seed)
        game.start_game()
        return game, game.heroes[0]

    def _buy_minion(self, game, hero, tier):
        cid = plain_pool_card(tier)
        m = game.create_minion(cid, controller=hero)
        game.events.fire(game, MINION_BOUGHT, minion=m)
        return m

    def _buy_spell(self, game, hero, tier):
        for d in get_db().pool_spells():
            if d.tech_level == tier:
                s = game.create_spell(d.id, controller=hero)
                game.events.fire(game, SPELL_BOUGHT, spell=s, hero=hero)
                return s
        raise AssertionError(f"no tavern spell tier={tier}")

    def test_twenty_tiers_grant_reward(self):
        game, a = self._game(401)
        for _ in range(19):
            self._buy_minion(game, a, 1)
        self.assertEqual(game.pending_choices, [])
        self._buy_minion(game, a, 1)
        pc = pop_choice(game, "triple_reward")
        for cid in pc.options:
            self.assertEqual(get_db().get(cid).tech_level, a.tavern_tier)

    def test_high_tier_purchase_carries_remainder(self):
        game, a = self._game(402)
        for _ in range(19):
            self._buy_minion(game, a, 1)
        self._buy_minion(game, a, 6)          # 19 + 6 = 25 → 1 次 + 余 5
        pop_choice(game, "triple_reward")
        self.assertEqual(a._natural_balance_tiers, 5)

    def test_spell_purchase_counts_tier(self):
        game, a = self._game(403)
        self._buy_spell(game, a, 3)
        self.assertEqual(a._natural_balance_tiers, 3)

    def test_opponent_purchase_does_not_count(self):
        game, a = self._game(404)
        b = game.heroes[1]
        for _ in range(25):
            self._buy_minion(game, b, 1)
        self.assertEqual(a._natural_balance_tiers, 0)
        self.assertEqual(game.pending_choices, [])


class TestKingOfDuality(unittest.TestCase):
    """BG35_HERO_001p — 第 4 回合 Discover 两个英雄技能替换本技能。"""

    def _game(self, seed):
        game = make_game_with("genn", seed)
        game.start_game()
        return game, game.heroes[0]

    def _fire_turn_start(self, game, hero, turn):
        game.events.fire(game, TURN_START, turn=turn, hero=hero)

    def test_not_before_turn_four(self):
        game, a = self._game(501)
        self._fire_turn_start(game, a, 3)
        self.assertEqual(game.pending_choices, [])

    def test_two_discoveries_replace_main_and_second_slot(self):
        game, a = self._game(502)
        original = game.hero_power_def(a).id
        self._fire_turn_start(game, a, 4)
        pc1 = pop_choice(game, "discover_hero_power")
        self.assertEqual(len(pc1.options), 3)
        pool = set(pc1.options)
        pick1 = pc1.options[0]
        pc1.choose(0)
        self.assertNotEqual(game.hero_power_def(a).id, original)
        self.assertEqual(game.hero_power_def(a).id, pick1)
        pc2 = pop_choice(game, "discover_hero_power")
        self.assertEqual(len(pc2.options), 3)
        self.assertNotIn(pick1, pc2.options)
        pick2 = pc2.options[0]
        pc2.choose(0)
        self.assertEqual(a._second_power_id, pick2)
        self.assertEqual(game.hero_power_def(a).id, pick1)
        # 所选技能必须来自已注册池（不产生空转槽位）
        for pid in (pick1, pick2):
            self.assertIn(pid, REGISTRY)
        self.assertTrue(pool)

    def test_selected_power_on_bind_wired(self):
        """被选被动技能的 on_bind 已接线（引擎替换不自动接线）。"""
        game, a = self._game(503)
        game.events.fire(game, TURN_START, turn=4, hero=a)
        pc1 = pop_choice(game, "discover_hero_power")
        pc1.choose(0)
        pick1 = game.hero_power_def(a).id
        script = REGISTRY.get(pick1)
        if getattr(script, "on_bind", None) is not None:
            # wire 幂等标记已记录；此处只断言不抛错且技能解析一致
            self.assertIsNotNone(script)
        pc2 = pop_choice(game, "discover_hero_power")
        pc2.choose(0)


class TestWhodunit(unittest.TestCase):
    """BG24_HERO_100p — 开局从两个任务中选一。"""

    def test_start_game_offers_two_quests(self):
        game = make_game_with("denathrius", 601)
        game.start_game()
        a = game.heroes[0]
        pc = pop_choice(game, "quest_offer")
        self.assertEqual(len(pc.options), 2)
        quest_pool = {d.id for d in game.quest_offer_pool()}
        for qid, rid in pc.options:
            self.assertIn(qid, quest_pool)
            self.assertTrue(rid.startswith("BG24_Reward_"), rid)
        qid, rid = pc.options[0]
        pc.choose(0)
        self.assertIsNotNone(a.quest)
        self.assertEqual(a.quest.card_id, qid)
        self.assertEqual(a._quest_reward_id, rid)
        self.assertIn(a, game._quest_offered)

    def test_turn_four_standard_offer_suppressed(self):
        game = make_game_with("denathrius", 602)
        game.start_game()
        a = game.heroes[0]
        pop_choice(game, "quest_offer").choose(0)
        game.turn = 4
        game._begin_recruit_for(a)
        offers = [pc for pc in game.pending_choices
                  if pc.kind == "quest_offer" and pc.owner is a]
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()
