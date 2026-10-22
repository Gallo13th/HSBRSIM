"""PendingChoice 契约加固（G-P1）回归测试。

覆盖 `docs/AUDIT_ENGINE_MECHANICS.md` G-P1：
  - `choose()` 只结算不出队（队列长度不变）；
  - 重复 choose 抛 `GameStateError` 且**不重复结算**（幂等）；
  - resolve 回调抛错 → `failed=True` + `resolution_error` 回滚标记（终态，
    不可重试；异常原样上抛），队列不丢；
  - 重入 choose 被拒；越界/未开始结算的错误不消费选择；
  - `Game.take_choice()` 原子 pop+choose；owner 不符不 pop；
  - 真实路径：trinket_offer / dark_gift 重复 choose 只结算一次。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game, GameStateError, PendingChoice
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str) -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, n: int = 2) -> Game:
    heroes = [make_hero(chr(ord("A") + i)) for i in range(n)]
    import hsrl2.scripts  # noqa: F401  注册脚本
    return Game(heroes, get_db(), seed=seed)


def narrow_offer_pool(case: unittest.TestCase, game: Game, defs) -> None:
    """收窄本局饰品候选池（实例影子方法；Cleanup 恢复共享 CardDB）。"""
    game.db.trinket_offer_pool = lambda: list(defs)
    case.addCleanup(lambda: game.db.__dict__.pop("trinket_offer_pool", None))


class TestPendingChoiceContract(unittest.TestCase):
    def setUp(self):
        self.game = make_game(seed=201)
        self.hero = self.game.heroes[0]
        self.calls = []

    def _mk(self, callback=None, *, options=("a", "b"), kind="demo",
            enqueue=True) -> PendingChoice:
        cb = callback
        if cb is None:
            cb = lambda pick: self.calls.append(pick)
        pc = PendingChoice(self.hero, list(options), kind,
                           resolve_callback=cb)
        if enqueue:
            self.game.pending_choices.append(pc)
        return pc

    def test_choose_does_not_dequeue_and_marks_resolved(self):
        pc = self._mk()
        n = len(self.game.pending_choices)
        pc.choose(1)
        self.assertEqual(self.calls, ["b"])
        # 契约：choose 只结算不出队
        self.assertEqual(len(self.game.pending_choices), n)
        self.assertIs(self.game.pending_choices[0], pc)
        self.assertTrue(pc.resolved)
        self.assertFalse(pc.failed)
        self.assertTrue(pc.is_settled)

    def test_duplicate_choose_refused_settles_once(self):
        pc = self._mk()
        pc.choose(0)
        with self.assertRaises(GameStateError) as ctx:
            pc.choose(1)
        self.assertIn("already resolved", str(ctx.exception))
        self.assertEqual(self.calls, ["a"])       # 未重复结算
        self.assertTrue(pc.resolved)

    def test_out_of_range_does_not_consume_choice(self):
        pc = self._mk()
        with self.assertRaises(GameStateError):
            pc.choose(2)
        with self.assertRaises(GameStateError):
            pc.choose(-1)
        # 未开始结算 → 状态未消费，可正常再选
        self.assertFalse(pc.resolved)
        self.assertFalse(pc.failed)
        pc.choose(0)
        self.assertEqual(self.calls, ["a"])
        self.assertTrue(pc.resolved)

    def test_resolution_error_marks_failed_and_is_final(self):
        def boom(pick):
            self.calls.append(pick)
            raise RuntimeError("boom-resolution")

        pc = self._mk(boom)
        with self.assertRaises(RuntimeError) as ctx:
            pc.choose(0)
        self.assertIn("boom-resolution", str(ctx.exception))
        # 回滚标记：已消费但终态失败（不可重试，避免半应用二次施加）
        self.assertTrue(pc.failed)
        self.assertFalse(pc.resolved)
        self.assertTrue(pc.is_settled)
        self.assertIsInstance(pc.resolution_error, RuntimeError)
        self.assertIn("boom-resolution", str(pc.resolution_error))
        with self.assertRaises(GameStateError) as ctx2:
            pc.choose(0)
        self.assertIn("previously failed", str(ctx2.exception))
        self.assertEqual(self.calls, ["a"])       # 回调只跑一次

    def test_reentrant_choose_refused(self):
        holder = {}

        def reenter(pick):
            holder["pc"].choose(0)                # 回调内再次 choose 同一选择

        pc = self._mk(reenter)
        holder["pc"] = pc
        with self.assertRaises(GameStateError) as ctx:
            pc.choose(0)
        self.assertIn("re-entrant", str(ctx.exception))
        self.assertTrue(pc.failed)                # 外层失败 = 终态
        self.assertFalse(pc.resolved)

    def test_card_discovered_fires_once(self):
        seen = []
        self.game.events.register(Listener(
            event="card_discovered", owner=self.hero,
            callback=lambda g, **kw: seen.append(kw)))
        pc = self._mk(options=("X",), kind="discover_minion")
        pc.choose(0)
        self.assertEqual(len(seen), 1)
        with self.assertRaises(GameStateError):
            pc.choose(0)
        self.assertEqual(len(seen), 1)            # 事件不重复广播

    def test_take_choice_pops_and_resolves(self):
        pc = self._mk()
        returned = self.game.take_choice(1)
        self.assertIs(returned, pc)
        self.assertEqual(self.game.pending_choices, [])
        self.assertEqual(self.calls, ["b"])
        self.assertTrue(pc.resolved)

    def test_take_choice_wrong_owner_does_not_pop(self):
        pc = self._mk()
        with self.assertRaises(GameStateError):
            self.game.take_choice(0, owner=self.game.heroes[1])
        self.assertEqual(len(self.game.pending_choices), 1)
        self.assertFalse(pc.resolved)

    def test_take_choice_empty_queue_raises(self):
        with self.assertRaises(GameStateError) as ctx:
            self.game.take_choice(0)
        self.assertIn("no pending choice", str(ctx.exception))

    def test_take_choice_failure_pops_and_marks_failed(self):
        def boom(pick):
            raise RuntimeError("take-choice-boom")

        pc = self._mk(boom)
        with self.assertRaises(RuntimeError):
            self.game.take_choice(0)
        self.assertEqual(self.game.pending_choices, [])   # 已 pop（env 契约）
        self.assertTrue(pc.failed)
        self.assertIsInstance(pc.resolution_error, RuntimeError)


class TestPendingChoiceIntegration(unittest.TestCase):
    """真实结算路径：重复 choose 不得二次施加效果。"""

    TRINKET = "BG30_MagicItem_984"        # Charging Staff（已注册，无 on_bind）

    def test_trinket_offer_duplicate_choose_debits_once(self):
        game = make_game(seed=211)
        hero = game.heroes[0]
        target = get_db().get(self.TRINKET)
        self.assertIsNotNone(REGISTRY.get(self.TRINKET))
        narrow_offer_pool(self, game, [target])
        hero.gold = 50
        game._offer_trinkets(hero, "lesser")
        choice = game.pending_choices[0]
        self.assertEqual(choice.kind, "trinket_offer")
        game.pending_choices.pop(0)               # 环境契约：先 pop 再 choose

        choice.choose(0)
        gold_after = hero.gold
        trinkets_after = [t.card_id for t in hero.trinkets]
        self.assertEqual(trinkets_after, [self.TRINKET])
        self.assertEqual(gold_after, 50 - (target.cost or 0))

        with self.assertRaises(GameStateError):
            choice.choose(0)                      # 重复 choose 被拒
        self.assertEqual(hero.gold, gold_after)   # 不重复扣金
        self.assertEqual([t.card_id for t in hero.trinkets], trinkets_after)
        self.assertTrue(choice.resolved)

    def test_dark_gift_duplicate_choose_grants_once(self):
        game = make_game(seed=212)
        hero = game.heroes[0]
        game.turn = 3
        hero.gold = 10
        self.assertTrue(game.use_dark_gift(hero))
        choice = game.pending_choices[0]
        self.assertEqual(choice.kind, "dark_gift")
        game.pending_choices.pop(0)               # 环境契约：先 pop 再 choose

        hand_before = len(hero.hand)
        choice.choose(0)
        hand_after = len(hero.hand)
        self.assertGreater(hand_after, hand_before)   # 随从（+可能附加副本）入手
        with self.assertRaises(GameStateError):
            choice.choose(0)
        self.assertEqual(len(hero.hand), hand_after)  # 不重复发随从
        self.assertTrue(choice.resolved)


if __name__ == "__main__":
    unittest.main()
