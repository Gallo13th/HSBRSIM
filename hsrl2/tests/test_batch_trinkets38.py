"""`batch_trinkets38` — Tide Raiser Portrait（`BG35_MagicItem_922`）回归测试。

真实路径: 饰品商店 `_offer_trinkets` → `PendingChoice` → `choose` →
`on_bind`（交付 `BG34_920` + 注册监听）→ 真实死亡路径
`game._process_single_death`（`TideRaiserScript` 亡语战斗内
`cast_spell_effect`）→ `spell_resolved` → plain 法术副本入手。

负对照: 无饰品 / 招募期施法（`in_combat=False`）/ 对手施法 /
每场额度 3 次用尽 / 饰品监听注销后。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.tags import Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

TIDE_RAISER_PORTRAIT = "BG35_MagicItem_922"
TIDE_RAISER = "BG34_920"          # 关联卡（非池随从，亡语效果施法）
SHIFTING_TIDE = "BG32_815"        # 池法术 T4（效果施法/副本都不动池）
ALLY_NAME = "ALLY"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 922) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def offer_and_buy(game: Game, hero: Hero, tid: str, kind: str = "lesser"):
    """真实饰品商店路径: `_offer_trinkets` → PendingChoice → resolve。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


def put(game: Game, hero: Hero, card_id: str) -> "object":
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def slay(game: Game, m) -> None:
    """真实死亡路径（亡语/复生顺序）。"""
    m.health = 0
    game._process_single_death(m)


class CombatContext:
    """真实战斗上下文闸门（`game.in_combat`，见 Stalwart Kodo 先例）。"""

    def __init__(self, game: Game, flag: bool = True):
        self.game = game
        self.flag = flag

    def __enter__(self):
        self.prev = self.game.in_combat
        self.game.in_combat = self.flag
        return self.game

    def __exit__(self, *exc):
        self.game.in_combat = self.prev
        return False


class TestRegistryState(unittest.TestCase):
    def test_registered_with_on_bind(self):
        cls = REGISTRY.get(TIDE_RAISER_PORTRAIT)
        self.assertIsNotNone(cls)
        self.assertTrue(hasattr(cls, "on_bind"))

    def test_in_offer_pool_as_lesser(self):
        d = get_db().get(TIDE_RAISER_PORTRAIT)
        self.assertIn(d, get_db().trinket_offer_pool())
        self.assertEqual(d.spell_school, 11)      # Lesser
        self.assertEqual(d.cost, 4)

    def test_evolution_data_chain(self):
        d = get_db().get(TIDE_RAISER_PORTRAIT)
        related = get_db().by_dbf(d.evolution_card_id)
        self.assertIsNotNone(related)
        self.assertEqual(related.id, TIDE_RAISER)
        self.assertFalse(related.is_pool_minion)

    def test_num_params_pin_text(self):
        d = get_db().get(TIDE_RAISER_PORTRAIT)
        # {0} = "left!" 显示值, {1} = 每场次数上限——两者均 3
        self.assertEqual((d.num(0), d.num(1)), (3, 3))

    def test_payload_and_spell_registered(self):
        self.assertIsNotNone(REGISTRY.get(TIDE_RAISER))
        self.assertIsNotNone(REGISTRY.get(SHIFTING_TIDE))

    def test_removed_from_other_batches_deferred_ledgers(self):
        from hsrl2.scripts.batches import batch_trinkets31 as B31
        import hsrl2.tests.test_batch_trinkets19 as T19
        import hsrl2.tests.test_batch_trinkets26 as T26
        self.assertNotIn(TIDE_RAISER_PORTRAIT, B31._DEFERRED_IDS)
        self.assertNotIn(TIDE_RAISER_PORTRAIT, T19.DEFERRED_IDS)
        self.assertNotIn(TIDE_RAISER_PORTRAIT, T26.DEFERRED_IDS)
        self.assertIn(TIDE_RAISER_PORTRAIT, T26.MIGRATED_IDS)


class TestTideRaiserPortrait(unittest.TestCase):
    def test_bind_grants_tide_raiser(self):
        game = make_game()
        a, _b = game.heroes
        offer_and_buy(game, a, TIDE_RAISER_PORTRAIT)
        self.assertEqual(hand_ids(a).count(TIDE_RAISER), 1)

    def test_combat_deathrattle_cast_grants_spell_copy(self):
        game = make_game(seed=901)
        a, _b = game.heroes
        offer_and_buy(game, a, TIDE_RAISER_PORTRAIT)
        raiser = put(game, a, TIDE_RAISER)
        ally = put(game, a, "BG31_803")     # 1/1 T1 野兽（非纳迦目标）
        pool_before = game.spell_pool.available(SHIFTING_TIDE)
        base_atk = ally.atk
        with CombatContext(game):
            slay(game, raiser)              # 真实亡语 → cast_spell_effect
        # 正效果: 亡语照常结算 + 副本入手
        self.assertEqual(ally.atk, base_atk + 2)
        self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 1)
        self.assertEqual(game.spell_pool.available(SHIFTING_TIDE),
                         pool_before)       # 效果施法 + 副本都不动池

    def test_recruit_period_cast_does_not_trigger(self):
        game = make_game(seed=902)
        a, _b = game.heroes
        offer_and_buy(game, a, TIDE_RAISER_PORTRAIT)
        ally = put(game, a, "BG31_803")
        with CombatContext(game, flag=False):
            game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)
        self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 0)
        self.assertEqual(ally.atk, 3)       # 法术本身照常结算

    def test_opponent_combat_cast_does_not_trigger(self):
        game = make_game(seed=903)
        a, b = game.heroes
        offer_and_buy(game, a, TIDE_RAISER_PORTRAIT)
        foe = put(game, b, "BG31_803")
        with CombatContext(game):
            game.cast_spell_effect(b, SHIFTING_TIDE, target=foe)
        self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 0)
        self.assertEqual(foe.atk, 3)

    def test_quota_three_per_combat_then_reset(self):
        game = make_game(seed=904)
        a, _b = game.heroes
        offer_and_buy(game, a, TIDE_RAISER_PORTRAIT)
        ally = put(game, a, "BG31_803")
        with CombatContext(game):
            for _ in range(3):
                game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)
            self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 3)
            game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)   # 第 4 次
            self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 3)   # 额度用尽
            # 下一场战斗重置（重置值必须取 num(1)=3, 而非硬编码 1:
            # 重置后需能连续 3 次, 第 4 次再次用尽）
            game.events.fire(game, "start_of_combat", hero=a)
            for _ in range(3):
                game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)
            self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 6)
            game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)
            self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 6)

    def test_copy_granted_after_spell_resolves(self):
        """事件时机钉死: "After you cast" → 副本在 `spell_resolved`
        （法术结算完成）时才入手, `spell_resolving` 时刻尚未入手
        （若监听 `spell_resolving`, 探针会先看到副本 → 断言失败）。"""
        from hsrl2.events import Listener
        game = make_game(seed=907)
        a, _b = game.heroes
        offer_and_buy(game, a, TIDE_RAISER_PORTRAIT)
        ally = put(game, a, "BG31_803")
        during = []
        game.events.register(Listener(
            event="spell_resolving", owner=None,
            callback=lambda g, **kw: during.append(
                hand_ids(a).count(SHIFTING_TIDE))))
        with CombatContext(game):
            game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)
        self.assertEqual(during, [0],
                         "spell_resolving 时副本已入手（事件时机错误）")
        self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 1)

    def test_no_trinket_no_copy(self):
        game = make_game(seed=905)
        a, _b = game.heroes
        ally = put(game, a, "BG31_803")
        with CombatContext(game):
            game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)
        self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 0)

    def test_listeners_stop_after_trinket_removed(self):
        game = make_game(seed=906)
        a, _b = game.heroes
        trinket = offer_and_buy(game, a, TIDE_RAISER_PORTRAIT)
        ally = put(game, a, "BG31_803")
        game.events.unregister_owner(trinket)
        with CombatContext(game):
            game.cast_spell_effect(a, SHIFTING_TIDE, target=ally)
        self.assertEqual(hand_ids(a).count(SHIFTING_TIDE), 0)


if __name__ == "__main__":
    unittest.main()
