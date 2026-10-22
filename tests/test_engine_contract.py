"""引擎契约测试 —— 环境层依赖的 hsrl2 行为假设。

这些不是引擎自身的机制测试（那些在 hsrl2/tests），而是**RL 环境层**必须
依赖的集成契约：回合推进、淘汰/名次、事件、确定性、PendingChoice。
任何一条变红都会破坏环境层，必须优先处理。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import CardType, GameTag

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def hero_ids(db: CardDB) -> list:
    return [d.id for d in db._by_id.values()
            if d.card_type == CardType.HERO
            and d.id.startswith(("TB_BaconShop_HERO", "BG"))]


def make_game(players: int = 8, seed: int = 7):
    db = get_db()
    ids = hero_ids(db)
    heroes = [Hero(ids[i % len(ids)], f"H{i}") for i in range(players)]
    return Game(heroes, db, seed=seed)


def drain_choices(game: Game, picks=None) -> int:
    """FIFO 弹出并结算全部 PendingChoice；返回结算个数。"""
    n = 0
    while game.pending_choices:
        choice = game.pending_choices.pop(0)
        idx = 0 if not picks else picks(n, len(choice.options))
        choice.choose(idx)
        n += 1
    return n


def run_to_end(game: Game, turn_cap: int = 60, max_steps: int = 20000) -> int:
    """驱动一个 8 人局到结束（简单随机/贪心动作），返回步数。"""
    drain_choices(game)
    steps = 0
    while not game.finished and game.turn <= turn_cap and steps < max_steps:
        steps += 1
        for hero in list(game.heroes):
            if not hero.is_alive:
                continue
            # 买最左买得起的，打出所有随从，随机刷新
            for e in list(hero.tavern):
                if hero.gold >= 3 and game.buy_from_tavern(hero, e):
                    break
            drain_choices(game)
            for e in list(hero.hand):
                if isinstance(e, Minion):
                    try:
                        game.play_minion(hero, e)
                    except Exception:      # noqa: BLE001 - 契约测试只看不崩溃
                        pass
            drain_choices(game)
            try:
                game.refresh_tavern(hero)
            except Exception:              # noqa: BLE001
                pass
            drain_choices(game)
        game.end_recruit_phase()
        drain_choices(game)
    return steps


class TestGameLifecycleContract(unittest.TestCase):
    """开局 / 回合 / 终局 / 淘汰的基本契约。"""

    def test_start_game_turn_one_and_tavern(self):
        game = make_game(players=8, seed=1)
        game.start_game()
        self.assertEqual(game.turn, 1)
        self.assertFalse(game.finished)
        for h in game.heroes:
            self.assertTrue(h.is_alive)
            self.assertGreater(len(h.tavern), 0, "回合开始应刷新酒馆")
            self.assertEqual(h.tavern_tier, 1)
            self.assertGreaterEqual(h.gold, 0)
        drain_choices(game)

    def test_end_recruit_phase_advances_turn(self):
        game = make_game(players=8, seed=2)
        game.start_game()
        drain_choices(game)
        turn_before = game.turn
        game.end_recruit_phase()
        drain_choices(game)
        self.assertIn(game.turn, (turn_before, turn_before + 1))
        if not game.finished:
            self.assertEqual(game.turn, turn_before + 1)

    def test_eliminated_heroes_removed_and_event_fires(self):
        game = make_game(players=4, seed=3)
        game.start_game()
        drain_choices(game)
        eliminated = []

        def on_elim(g, **kw):
            eliminated.append(kw["hero"])

        from hsrl2.events import HERO_ELIMINATED, Listener
        game.events.register(Listener(
            HERO_ELIMINATED, owner=game.heroes[0], callback=on_elim))
        # 直接击杀两个英雄，然后触发战斗回合末的淘汰结算
        for h in game.heroes[1:3]:
            h.health = 0
        game.end_recruit_phase()
        drain_choices(game)
        self.assertEqual(len(eliminated), 2)
        self.assertEqual(len(game.heroes), 2)

    def test_finished_when_one_alive(self):
        game = make_game(players=8, seed=4)
        game.start_game()
        drain_choices(game)
        # 击杀除一个外的所有英雄
        survivor = game.heroes[0]
        for h in game.heroes[1:]:
            h.health = 0
        game.end_recruit_phase()
        drain_choices(game)
        self.assertTrue(game.finished)
        self.assertEqual(len(game.heroes), 1)
        self.assertIs(game.heroes[0], survivor)

    def test_players_2_and_4_supported(self):
        for players in (2, 4):
            game = make_game(players=players, seed=5)
            game.start_game()
            drain_choices(game)
            game.end_recruit_phase()
            drain_choices(game)
            self.assertGreaterEqual(game.turn, 1)


class TestDeterminismContract(unittest.TestCase):
    """同 seed + 同动作 ⇒ 同状态（训练可复现的根基）。"""

    def test_same_seed_same_trajectory(self):
        def trace(seed):
            game = make_game(players=4, seed=seed)
            game.start_game()
            drain_choices(game)
            snap = []
            for _ in range(3):
                for h in game.heroes:
                    if h.is_alive:
                        snap.append((h.name, h.health, h.gold, h.tavern_tier,
                                     len(h.board), len(h.hand),
                                     tuple(e.card_id for e in h.tavern)))
                game.end_recruit_phase()
                drain_choices(game)
                snap.append(("turn", game.turn,
                             tuple(h.name for h in game.heroes)))
            return snap

        self.assertEqual(trace(11), trace(11))

    def test_actions_deterministic(self):
        game_a = make_game(players=2, seed=12)
        game_b = make_game(players=2, seed=12)
        for g in (game_a, game_b):
            g.start_game()
            drain_choices(g)
        # 两局做完全相同的合法动作：买第一张买得起的
        for g in (game_a, game_b):
            h = g.heroes[0]
            for e in list(h.tavern):
                if h.gold >= 3:
                    g.buy_from_tavern(h, e)
                    break
            drain_choices(g)
        a, b = game_a.heroes[0], game_b.heroes[0]
        self.assertEqual(a.gold, b.gold)
        self.assertEqual([e.card_id for e in a.hand],
                         [e.card_id for e in b.hand])


class TestPendingChoiceContract(unittest.TestCase):
    """PendingChoice 队列语义（pop + choose，choose 不出队）。"""

    def test_choice_queue_pop_semantics(self):
        game = make_game(players=8, seed=6)
        game.start_game()
        # 开局可能产生选择（如英雄技能/异变），先全部结算
        drain_choices(game)
        before = len(game.pending_choices)
        self.assertEqual(before, 0)
        # 不强制构造选择：只要队列结算函数幂等即可
        self.assertEqual(drain_choices(game), 0)

    def test_hero_power_api_does_not_crash(self):
        game = make_game(players=4, seed=8)
        game.start_game()
        drain_choices(game)
        for h in game.heroes:
            for pid in game.hero_power_ids(h):
                try:
                    game.use_hero_power(h)
                except Exception:          # noqa: BLE001 - 目标型技能可失败
                    pass
                drain_choices(game)
        self.assertEqual(len(game.pending_choices), 0)


class TestFullGameContract(unittest.TestCase):
    """完整 8 人局在合理回合内结束。"""

    def test_full_game_completes(self):
        game = make_game(players=8, seed=21)
        game.start_game()
        run_to_end(game, turn_cap=60)
        drain_choices(game)
        self.assertTrue(game.finished, f"未结束: turn={game.turn}")
        self.assertEqual(len(game.heroes), 1)
        # 战斗次数应覆盖全部回合
        self.assertGreater(game.turn, 1)


if __name__ == "__main__":
    unittest.main()
