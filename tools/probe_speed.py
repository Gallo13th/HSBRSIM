#!/usr/bin/env python
"""Engine RL-readiness benchmark: action / turn / full-game latency + memory.

Data source for `docs/ENGINE_RL_READINESS.md`.

Usage:
  python tools/probe_speed.py --games 20
  python tools/probe_speed.py --games 5 --no-anomaly
  python tools/probe_speed.py --games 20 --json runs/probe_speed.json
  python tools/probe_speed.py --games 20 --strip-entity-tags   # diagnostic

Definitions
-----------
* **action step** = one public engine API call (buy/sell/play/refresh/
  upgrade/freeze/hero_power/activate/dark_gift/spend_gold/...). The driving
  policy is a random policy; `random.Random(seed)` is used ONLY for driver
  decisions, every engine random decision goes through `game.rng`.
* **choice step** = settling one `PendingChoice` (`pop(0)` + `choose(i)`).
* **end_recruit_phase** = one full end-of-recruit pipeline (EoT effects ->
  pairing -> combats -> ghost combat -> eliminations -> next-turn start
  effects, including the next Tavern refresh).
* **full game** = one `Game(...)` construction until `game.finished` or the
  turn cap.

Latency is wall clock (`time.perf_counter`), reported as mean/p50/p90/p99/max.
Memory is sampled in a separate pass with `tracemalloc` (tracemalloc slows the
run down substantially, so it is excluded from latency numbers).

Diagnostic flag
---------------
`--strip-entity-tags` clears Entity-valued tags (`GameTag.KILLER` is the only
one) on both boards right before each `run_combat`. This measures the ceiling
without the known `Minion.snapshot_state()` deepcopy defect (deepcopy of a tag
holding an Entity walks the whole Game object graph). It is a *measurement*
workaround only; it does not modify any engine file.

Exit code: 0 = finished (games may legitimately end incomplete at turn cap),
1 = a crash was observed.
"""

from __future__ import annotations

import argparse
import collections
import json
import platform
import random
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2 import constants as C  # noqa: E402
from hsrl2.db import CardDB  # noqa: E402
from hsrl2.entity import Entity  # noqa: E402
from hsrl2.game import Game, GameStateError  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402
from hsrl2.minion import Minion  # noqa: E402
from hsrl2.scripts import REGISTRY  # noqa: E402
from hsrl2.spell import Spell  # noqa: E402
from hsrl2.tags import CardType, GameTag  # noqa: E402

DATA_DIR = ROOT / "data"


# ---------------------------------------------------------------- statistics


def pct(values, q: float) -> float:
    """Percentile (0-100, linear interpolation; 0.0 for empty input)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * (q / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def summarize(values) -> dict:
    if not values:
        return {"n": 0, "mean": 0.0, "p50": 0.0, "p90": 0.0,
                "p99": 0.0, "max": 0.0, "sum": 0.0}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "p50": pct(values, 50),
        "p90": pct(values, 90),
        "p99": pct(values, 99),
        "max": max(values),
        "sum": sum(values),
    }


class Timer:
    """Collect latency samples (milliseconds) grouped by key."""

    def __init__(self) -> None:
        self.samples: dict = collections.defaultdict(list)

    def add(self, key: str, ms: float) -> None:
        self.samples[key].append(ms)

    def summary(self) -> dict:
        return {k: summarize(v) for k, v in self.samples.items()}

    def combined(self, prefix_exclude: tuple) -> dict:
        flat = []
        for key, values in self.samples.items():
            if key.startswith(prefix_exclude):
                continue
            flat.extend(values)
        return summarize(flat)


# ------------------------------------------------------------------- driver


def resolve_all(game: Game, rng: random.Random, timer: Timer,
                cap: int = 400) -> int:
    """FIFO-settle every PendingChoice (`choose` settles but does NOT dequeue).

    Returns the number of settled choices. Contract: docs/ENGINE_API.md 搂5.
    """
    n = 0
    while game.pending_choices and n < cap:
        n += 1
        choice = game.pending_choices.pop(0)
        t0 = time.perf_counter()
        choice.choose(rng.randrange(len(choice.options)))
        timer.add(f"choice:{choice.kind}",
                  (time.perf_counter() - t0) * 1e3)
    return n


def _act(timer: Timer, key: str, fn, *args, **kwargs):
    """Run one engine API call and time it (exceptions are caller's job)."""
    t0 = time.perf_counter()
    try:
        return fn(*args, **kwargs)
    finally:
        timer.add(key, (time.perf_counter() - t0) * 1e3)


def instrument_combat(game: Game, strip_entity_tags: bool,
                      timer: Timer | None = None) -> dict:
    """Wrap `game.run_combat` (instance attribute) for diagnostics.

    Returns a mutable counter: combats seen, combats where a board minion
    carried an Entity-valued tag at combat start (the snapshot_state hazard).
    """
    stats = collections.Counter()
    original = game.run_combat

    def wrapper(hero_a, hero_b, alive_count=None):
        polluted = 0
        for hero in (hero_a, hero_b):
            for m in hero.board:
                for value in m.tags.values():
                    if isinstance(value, Entity):
                        polluted += 1
                        if strip_entity_tags:
                            # diagnostic only: drop the reference before the
                            # engine snapshots the board
                            for tag, val in list(m.tags.items()):
                                if isinstance(val, Entity):
                                    del m.tags[tag]
                        break
        stats["combats"] += 1
        if polluted:
            stats["combats_with_entity_tags"] += 1
            stats["entity_tags"] += polluted
        t0 = time.perf_counter()
        try:
            return original(hero_a, hero_b, alive_count=alive_count)
        finally:
            if timer is not None:
                timer.add("run_combat", (time.perf_counter() - t0) * 1e3)

    game.run_combat = wrapper          # bound-method shadow (instance level)
    return stats


def recruit_one_turn(game: Game, rng: random.Random, timer: Timer,
                     max_ops: int = 200) -> dict:
    """Randomly drive every living hero through one recruit phase.

    Returns per-kind action counters (choices included as "choice").
    """
    counts = collections.Counter()
    for hero in list(game.heroes):
        if not hero.is_alive:
            continue
        ops = 0
        for kind, fn in (
            ("hero_power", lambda: game.use_hero_power(hero)),
            ("dark_gift", lambda: game.use_dark_gift(hero)),
        ):
            try:
                _act(timer, kind, fn)
            except GameStateError:
                pass
            counts[kind] += 1
            counts["choice"] += resolve_all(game, rng, timer)
        for m in list(hero.board):
            if m.has(GameTag.ACTIVATE):
                try:
                    _act(timer, "activate", game.use_activate, hero, m)
                except GameStateError:
                    pass
                counts["activate"] += 1
                counts["choice"] += resolve_all(game, rng, timer)
        for e in list(hero.tavern):
            if ops > max_ops:
                break
            ops += 1
            try:
                ok = _act(timer, "buy", game.buy_from_tavern, hero, e)
            except GameStateError:
                ok = False
            if ok:
                counts["buy"] += 1
            counts["choice"] += resolve_all(game, rng, timer)
        for e in list(hero.hand):
            if ops > max_ops:
                break
            ops += 1
            try:
                if isinstance(e, Minion):
                    _act(timer, "play_minion", game.play_minion, hero, e)
                    counts["play_minion"] += 1
                elif isinstance(e, Spell):
                    _act(timer, "play_spell", game.play_spell, hero, e)
                    counts["play_spell"] += 1
            except GameStateError:
                pass
            counts["choice"] += resolve_all(game, rng, timer)
        if hero.gold >= hero.upgrade_cost:
            try:
                _act(timer, "upgrade", game.upgrade_tavern, hero)
                counts["upgrade"] += 1
            except GameStateError:
                pass
        try:
            _act(timer, "refresh", game.refresh_tavern, hero)
            counts["refresh"] += 1
        except GameStateError:
            pass
        counts["choice"] += resolve_all(game, rng, timer)
        if hero.board and rng.random() < 0.3:
            try:
                _act(timer, "sell", game.sell_minion, hero,
                     rng.choice(hero.board))
                counts["sell"] += 1
            except GameStateError:
                pass
        counts["choice"] += resolve_all(game, rng, timer)
    return dict(counts)


def play_one(db: CardDB, seed: int, players: int, turn_cap: int,
             anomaly: str | None, timer: Timer, max_ops: int,
             strip_entity_tags: bool = False) -> dict:
    """Run one random game (all seats) and return statistics."""
    t_game0 = time.perf_counter()
    rng = random.Random(seed)
    hero_ids = [d.id for d in db._by_id.values()
                if d.card_type == CardType.HERO]
    heroes = [Hero(rng.choice(hero_ids), f"H{i}") for i in range(players)]
    t0 = time.perf_counter()
    game = Game(heroes, db, seed=seed, anomaly=anomaly)
    timer.add("game_init", (time.perf_counter() - t0) * 1e3)
    combat_stats = instrument_combat(game, strip_entity_tags, timer)
    t0 = time.perf_counter()
    game.start_game()
    timer.add("start_game", (time.perf_counter() - t0) * 1e3)
    actions = collections.Counter()
    choices = resolve_all(game, rng, timer)
    erp_ms = []

    while not game.finished and game.turn <= turn_cap:
        counts = recruit_one_turn(game, rng, timer, max_ops=max_ops)
        actions.update(counts)
        choices += counts.get("choice", 0)
        t0 = time.perf_counter()
        game.end_recruit_phase()
        dt = (time.perf_counter() - t0) * 1e3
        erp_ms.append(dt)
        timer.add("end_recruit_phase", dt)
        actions["end_recruit_phase"] += 1
        choices += resolve_all(game, rng, timer)

    total = time.perf_counter() - t_game0
    steps = sum(v for k, v in actions.items()
                if k not in ("choice", "end_recruit_phase"))
    steps += actions["end_recruit_phase"] + choices
    return {
        "seed": seed,
        "turn": game.turn,
        "finished": game.finished,
        "heroes_left": len(game.heroes),
        "ghost_records": len(game.ghost_records),
        "actions": dict(actions),
        "choices": choices,
        "steps": steps,
        "elapsed_ms": total * 1e3,
        "erp_ms": erp_ms,
        "rng_decisions": len(game.rng.decisions),
        "pending_hand_queue": len(game.pending_hand_queue),
        "combats": combat_stats.get("combats", 0),
        "combats_with_entity_tags":
            combat_stats.get("combats_with_entity_tags", 0),
    }


# ------------------------------------------------------------------- memory


def memory_probe(db: CardDB, seed: int, players: int, turn_cap: int,
                 anomaly: str | None, strip_entity_tags: bool = False) -> dict:
    """tracemalloc peak for one game (run in its own pass)."""
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        rng = random.Random(seed)
        hero_ids = [d.id for d in db._by_id.values()
                    if d.card_type == CardType.HERO]
        heroes = [Hero(rng.choice(hero_ids), f"H{i}") for i in range(players)]
        game = Game(heroes, db, seed=seed, anomaly=anomaly)
        if strip_entity_tags:
            instrument_combat(game, strip_entity_tags=True)
        game.start_game()
        resolve_all(game, rng, Timer())
        peak_after_start = tracemalloc.get_traced_memory()[1] - base
        while not game.finished and game.turn <= turn_cap:
            recruit_one_turn(game, rng, Timer(), max_ops=8)
            game.end_recruit_phase()
            resolve_all(game, rng, Timer())
        peak = tracemalloc.get_traced_memory()[1] - base
        current = tracemalloc.get_traced_memory()[0] - base
        return {
            "seed": seed,
            "peak_after_start_mb": peak_after_start / 2**20,
            "peak_mb": peak / 2**20,
            "current_mb": current / 2**20,
            "turn": game.turn,
            "rng_decisions": len(game.rng.decisions),
        }
    finally:
        tracemalloc.stop()


# ------------------------------------------------------------------- output


def fmt_ms(label: str, s: dict, unit: str = "ms") -> str:
    if s["n"] == 0:
        return f"  {label:32s} n=0"
    return (f"  {label:32s} n={s['n']:6d}  mean={s['mean']:8.3f}  "
            f"p50={s['p50']:8.3f}  p90={s['p90']:8.3f}  "
            f"p99={s['p99']:8.3f}  max={s['max']:8.3f}  ({unit})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--turn-cap", type=int, default=50)
    ap.add_argument("--no-anomaly", action="store_true",
                    help="never inject an anomaly (default: 1/3 of games)")
    ap.add_argument("--mem-games", type=int, default=3,
                    help="tracemalloc memory samples (0 = skip)")
    ap.add_argument("--strip-entity-tags", action="store_true",
                    help="diagnostic: clear Entity-valued tags before each "
                         "combat (works around the Minion.snapshot_state "
                         "deepcopy defect; measurement only)")
    ap.add_argument("--json", type=str, default=None,
                    help="write the summary JSON to this path")
    args = ap.parse_args()

    t_load0 = time.perf_counter()
    db = CardDB.load(DATA_DIR)
    load_ms = (time.perf_counter() - t_load0) * 1e3

    anomalies: list = []
    if not args.no_anomaly:
        anomalies = [k for k in REGISTRY
                     if db.get(k) is not None
                     and db.get(k).card_type == CardType.BACON_ANOMALY]

    timer = Timer()
    game_stats = []
    errors = collections.Counter()
    completed = incomplete = 0

    print(f"# probe_speed  python={platform.python_version()} "
          f"platform={platform.platform()}")
    print(f"# players={args.players} games={args.games} seed={args.seed} "
          f"turn_cap={args.turn_cap} anomaly={not args.no_anomaly} "
          f"strip_entity_tags={args.strip_entity_tags}")
    print(f"# CardDB: {len(db)} defs, pool_minions={len(db.pool_minions())}, "
          f"pool_spells={len(db.pool_spells())}, load={load_ms:.1f} ms, "
          f"anomaly_pool={len(anomalies)}")
    print(f"# constants: gold income turn1..10="
          f"{[C.gold_base_income(t) for t in range(1, 11)]}, "
          f"refresh={C.REFRESH_COST}, buy={C.MINION_BUY_COST}, "
          f"tavern_offers={C.TAVERN_OFFERS}")

    for i in range(args.games):
        seed = args.seed + i
        anomaly = (anomalies[i % len(anomalies)]
                   if (anomalies and i % 3 == 0) else None)
        try:
            stats = play_one(db, seed, args.players, args.turn_cap,
                             anomaly, timer, max_ops=12,
                             strip_entity_tags=args.strip_entity_tags)
            game_stats.append(stats)
            completed += 1 if stats["finished"] else 0
            incomplete += 0 if stats["finished"] else 1
            print(f"[{i + 1}/{args.games}] seed={seed} "
                  f"turn={stats['turn']} finished={stats['finished']} "
                  f"heroes_left={stats['heroes_left']} "
                  f"actions={sum(v for k, v in stats['actions'].items() if k != 'end_recruit_phase')} "
                  f"choices={stats['choices']} "
                  f"combats={stats['combats']} "
                  f"stale_tag_combats={stats['combats_with_entity_tags']} "
                  f"{stats['elapsed_ms']:.0f} ms", flush=True)
        except Exception as e:                       # noqa: BLE001
            errors[f"{type(e).__name__}: {e}"] += 1
            print(f"CRASH seed={seed} anomaly={anomaly}: "
                  f"{type(e).__name__}: {e}", flush=True)

    # ---- latency summary ----
    summary = timer.summary()
    print("\n== per engine call (ms) ==")
    for key in sorted(summary):
        print(fmt_ms(key, summary[key]))

    print("\n== aggregated action step (all public API calls, "
          "excl. choice/ERP/combat/init) ==")
    action_exclude = ("choice:", "end_recruit_phase", "run_combat",
                      "game_init", "start_game")
    print(fmt_ms("action_step", timer.combined(action_exclude)))

    game_ms = [g["elapsed_ms"] for g in game_stats]
    turns = [g["turn"] for g in game_stats]
    steps = [g["steps"] for g in game_stats]
    erp_all = [d for g in game_stats for d in g["erp_ms"]]
    print("\n== per game ==")
    print(fmt_ms("full_game", summarize(game_ms)))
    print(fmt_ms("end_recruit_phase (all turns)", summarize(erp_all)))
    print(fmt_ms("decision_steps", summarize([float(s) for s in steps]),
                 unit="count"))
    print(fmt_ms("actions_per_game", summarize(
        [float(sum(v for k, v in g["actions"].items()
                 if k != "end_recruit_phase")) for g in game_stats]),
        unit="count"))
    print(f"  turns: n={len(turns)} mean={statistics.fmean(turns):.2f} "
          f"p50={pct([float(t) for t in turns], 50):.0f} "
          f"p90={pct([float(t) for t in turns], 90):.0f} max={max(turns)}")

    if game_stats:
        rng_dec = [g["rng_decisions"] for g in game_stats]
        phq = [g["pending_hand_queue"] for g in game_stats]
        whole = [g["combats"] - g["combats_with_entity_tags"]
                 for g in game_stats]
        print(f"# rng.decisions per game: mean={statistics.fmean(rng_dec):.0f}"
              f" max={max(rng_dec)}")
        print(f"# pending_hand_queue left at end: max={max(phq)}")
        print(f"# combats: total={sum(g['combats'] for g in game_stats)} "
              f"contaminated_by_entity_tags="
              f"{sum(g['combats_with_entity_tags'] for g in game_stats)} "
              f"(clean={sum(whole)})")
        totals = collections.Counter()
        for g in game_stats:
            for k, v in g["actions"].items():
                totals[k] += v
        print("# action totals: " + ", ".join(
            f"{k}={v}" for k, v in totals.most_common()))
        print(f"# games: completed={completed} incomplete={incomplete} "
              f"crashes={sum(errors.values())}")

    # ---- memory ----
    mem_stats = []
    if args.mem_games > 0:
        print("\n== memory (tracemalloc, separate pass) ==")
        for i in range(min(args.mem_games, max(1, args.games))):
            seed = args.seed + i
            anomaly = (anomalies[i % len(anomalies)]
                       if (anomalies and i % 3 == 0) else None)
            try:
                mem = memory_probe(db, seed, args.players, args.turn_cap,
                                   anomaly,
                                   strip_entity_tags=args.strip_entity_tags)
                mem_stats.append(mem)
                print(f"  seed={seed} turn={mem['turn']} "
                      f"peak={mem['peak_mb']:.1f} MB "
                      f"current={mem['current_mb']:.1f} MB "
                      f"rng_decisions={mem['rng_decisions']}")
            except Exception as e:                   # noqa: BLE001
                print(f"  MEM CRASH seed={seed}: {type(e).__name__}: {e}")

    result = {
        "config": vars(args),
        "db": {"defs": len(db), "load_ms": load_ms,
               "pool_minions": len(db.pool_minions()),
               "pool_spells": len(db.pool_spells()),
               "anomaly_pool": len(anomalies)},
        "engine_calls_ms": summary,
        "action_step_ms": timer.combined(("choice:", "end_recruit_phase", "run_combat", "game_init", "start_game")),
        "games": game_stats,
        "full_game_ms": summarize(game_ms),
        "erp_ms": summarize(erp_all),
        "steps": summarize([float(s) for s in steps]),
        "turns": summarize([float(t) for t in turns]),
        "counts": {"completed": completed, "incomplete": incomplete,
                   "crashes": sum(errors.values())},
        "errors": dict(errors),
        "memory": mem_stats,
    }
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"\n# JSON -> {path}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

