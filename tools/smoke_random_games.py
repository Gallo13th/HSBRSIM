#!/usr/bin/env python
"""随机全对局压测 — 集成级冒烟（EFFECT_SCRIPT_SOP §13）。

四件套（pytest + 三个审计）只覆盖静态/单元层面；本工具跑随机 8 人对局，
覆盖真实调用链: 英雄技能 / Activate / Dark Gift / 买 / 打 / 卖 / 刷 /
升级 / 饰品与任务选择 / 异变 / 战斗编排 / 淘汰。

用法:
  python tools/smoke_random_games.py [--games N] [--seed BASE] [--players 8]
                                     [--turn-cap 50] [--no-anomaly]

退出码: 0=无崩溃（允许有未在 turn-cap 内结束的对局）, 1=有崩溃。
崩溃会打印异常类型 + 消息 + 截断 traceback，便于最小化复现。
"""

from __future__ import annotations

import argparse
import collections
import random
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB  # noqa: E402
from hsrl2.game import Game, GameStateError  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402
from hsrl2.minion import Minion  # noqa: E402
from hsrl2.scripts import REGISTRY  # noqa: E402
from hsrl2.spell import Spell  # noqa: E402
from hsrl2.tags import GameTag  # noqa: E402


def resolve_all(game: Game, rng: random.Random, cap: int = 400) -> None:
    """FIFO 解析全部 PendingChoice（自动化层逐步解析的等价物）。

    契约: `PendingChoice.choose` **只结算不出队**（TEST_SOP §8）——
    必须由上层 pop，否则同一选择会被反复结算（曾因此造成 18k 队列
    假死与效果重复施加）。
    """
    n = 0
    while game.pending_choices and n < cap:
        n += 1
        choice = game.pending_choices.pop(0)
        choice.choose(rng.randrange(len(choice.options)))


def play_one(db: CardDB, seed: int, players: int, turn_cap: int,
             anomaly: str | None) -> tuple[int, bool]:
    rng = random.Random(seed)
    hero_ids = [d.id for d in db._by_id.values()
                if d.card_type.name == "HERO"
                and d.id.startswith(("TB_BaconShop_HERO", "BG"))]
    heroes = [Hero(rng.choice(hero_ids), f"H{i}") for i in range(players)]
    game = Game(heroes, db, seed=seed, anomaly=anomaly)
    game.start_game()
    resolve_all(game, rng)
    steps = 0
    while not game.finished and game.turn < turn_cap and steps < 15000:
        steps += 1
        for hero in list(game.heroes):
            if not hero.is_alive:
                continue
            try:
                game.use_hero_power(hero)
            except GameStateError:
                pass
            resolve_all(game, rng)
            for m in list(hero.board):
                if m.has(GameTag.ACTIVATE):
                    try:
                        game.use_activate(hero, m)
                    except GameStateError:
                        pass
            resolve_all(game, rng)
            try:
                game.use_dark_gift(hero)
            except GameStateError:
                pass
            resolve_all(game, rng)
            for e in list(hero.tavern):
                if not hero.hand_full() and game.buy_from_tavern(hero, e):
                    break
            resolve_all(game, rng)
            for e in list(hero.hand):
                if isinstance(e, Minion):
                    try:
                        game.play_minion(hero, e)
                    except GameStateError:
                        pass
            resolve_all(game, rng)
            # 施放手牌法术（把手牌排空——否则满手会让"生成卡等待队列"
            # 无限增长，压测会假性挂死; RULES §3.3 等待语义本身正确）
            for e in list(hero.hand):
                if isinstance(e, Spell):
                    try:
                        game.play_spell(hero, e)
                    except GameStateError:
                        pass
            resolve_all(game, rng)
            if rng.random() < 0.4 and hero.gold >= hero.upgrade_cost:
                game.upgrade_tavern(hero)
            if rng.random() < 0.5:
                try:
                    game.refresh_tavern(hero)
                except GameStateError:
                    pass
            resolve_all(game, rng)
            if hero.board and rng.random() < 0.2:
                game.sell_minion(hero, rng.choice(hero.board))
        game.end_recruit_phase()
        resolve_all(game, rng)
    resolve_all(game, rng)
    return game.turn, game.finished


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--turn-cap", type=int, default=50)
    ap.add_argument("--no-anomaly", action="store_true")
    args = ap.parse_args()

    db = CardDB.load(ROOT / "data")
    # 异变池 = REGISTRY 中**card_type=BACON_ANOMALY**的卡（旧实现按 id 含
    # "Anomaly" 过滤 → 会把异变授予的**英雄技能**（如 BG35_Anomaly_007t）
    # 当异变传入，`Game(anomaly=...)` 的 `on_bind(game)` 签名不符崩溃）
    from hsrl2.tags import CardType as _CT
    anomalies = [] if args.no_anomaly else [
        k for k in REGISTRY
        if (db.get(k) is not None
            and db.get(k).card_type == _CT.BACON_ANOMALY)]

    errors: collections.Counter = collections.Counter()
    completed = incomplete = 0
    for i in range(args.games):
        seed = args.seed + i
        anomaly = anomalies[i % len(anomalies)] if (
            anomalies and i % 3 == 0) else None
        if i % 10 == 0:
            print(f"[{i}/{args.games}] seed={seed} anomaly={anomaly}",
                  flush=True)
        try:
            turn, finished = play_one(db, seed, args.players,
                                      args.turn_cap, anomaly)
            completed += 1 if finished else 0
            incomplete += 0 if finished else 1
            if not finished:
                print(f"  INCOMPLETE seed={seed} turn={turn}", flush=True)
        except Exception as e:                       # noqa: BLE001
            errors[f"{type(e).__name__}: {e}"] += 1
            print(f"CRASH seed={seed} anomaly={anomaly}: "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc(limit=4)

    print(f"\ngames={args.games} completed={completed} incomplete={incomplete} "
          f"crashes={sum(errors.values())}")
    for msg, n in errors.most_common(10):
        print(f"  {n} x {msg}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
