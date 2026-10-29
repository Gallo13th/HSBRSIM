"""Per-turn total decision time for turn-search (states=16, pairwise).

Runs a few games with a timing wrapper around TurnSearchPolicy; records each
decision's wall time and turn, then aggregates **per turn** (sum of all decision
times within that turn in each game), not a cross-turn average.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class TimedPolicy:
    def __init__(self, inner: Any, records: List[Dict[str, Any]]) -> None:
        self.inner = inner
        self.records = records

    def bind_env(self, env: Any) -> None:
        self.inner.bind_env(env)

    def reset(self) -> None:
        if hasattr(self.inner, "reset"):
            self.inner.reset()

    def set_episode_seed(self, seed: int) -> None:
        if hasattr(self.inner, "set_episode_seed"):
            self.inner.set_episode_seed(seed)

    def act(self, obs: Any, **kwargs: Any) -> int:
        t0 = time.perf_counter()
        idx = self.inner.act(obs, **kwargs)
        dt = time.perf_counter() - t0
        self.records.append({
            "turn": int(getattr(obs, "turn", -1) or 0),
            "phase": str(getattr(obs, "phase", "")),
            "elapsed_s": dt,
        })
        return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=5)
    ap.add_argument("--states", type=int, default=16)
    ap.add_argument("--seed-start", type=int, default=300)
    ap.add_argument("--out", default="runs/search/turn_timing_s16.json")
    args = ap.parse_args()

    from hsbg.env import BattlegroundsEnv
    from hsbg.rl.api import run_episode
    from hsbg.search.policy import TurnSearchPolicy, TurnSearchPolicyConfig

    all_games: List[Dict[str, Any]] = []
    for g in range(args.games):
        seed = args.seed_start + g
        recs: List[Dict[str, Any]] = []
        cfg = TurnSearchPolicyConfig(states_budget=args.states)
        policy = TimedPolicy(TurnSearchPolicy(cfg), recs)
        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
        t0 = time.perf_counter()
        rec = run_episode(env, policy, seed=seed, collect_transitions=False,
                          num_players=8)
        wall = time.perf_counter() - t0
        try:
            env.close()
        except Exception:
            pass
        by_turn: Dict[int, List[float]] = {}
        for r in recs:
            by_turn.setdefault(r["turn"], []).append(r["elapsed_s"])
        turns = []
        for t in sorted(by_turn):
            times = by_turn[t]
            turns.append({
                "turn": t,
                "n_decisions": len(times),
                "total_s": sum(times),
                "mean_s": statistics.mean(times),
                "max_s": max(times),
            })
        all_games.append({
            "seed": seed,
            "rank": int(getattr(rec, "rank", -1) or -1),
            "wall_s": wall,
            "total_decisions": len(recs),
            "decision_s_sum": sum(r["elapsed_s"] for r in recs),
            "turns": turns,
        })
        print(f"game seed={seed} rank={getattr(rec,'rank',None)} decisions={len(recs)} "
              f"decision_sum={sum(r['elapsed_s'] for r in recs):.1f}s wall={wall:.1f}s")

    # Aggregate per turn across games: per-game turn total -> distribution.
    agg: Dict[int, List[float]] = {}
    decisions_per_turn: Dict[int, List[int]] = {}
    for game in all_games:
        for t in game["turns"]:
            agg.setdefault(t["turn"], []).append(t["total_s"])
            decisions_per_turn.setdefault(t["turn"], []).append(t["n_decisions"])

    def pct(xs: List[float], p: float) -> float:
        if not xs:
            return 0.0
        ys = sorted(xs)
        k = max(0, min(len(ys) - 1, int(round(p * (len(ys) - 1)))))
        return ys[k]

    rows = []
    for t in sorted(agg):
        xs = agg[t]
        rows.append({
            "turn": t,
            "n_games": len(xs),
            "mean_total_s": statistics.mean(xs),
            "median_total_s": statistics.median(xs),
            "p90_total_s": pct(xs, 0.9),
            "max_total_s": max(xs),
            "mean_decisions": statistics.mean(decisions_per_turn[t]),
            "mean_decision_s": statistics.mean(xs) / statistics.mean(decisions_per_turn[t]),
        })

    payload = {"config": vars(args), "games": all_games, "per_turn": rows}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n| turn | games | mean total(s) | median | p90 | max | decisions | mean/decision(s) |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        print(f"| {r['turn']} | {r['n_games']} | {r['mean_total_s']:.2f} | "
              f"{r['median_total_s']:.2f} | {r['p90_total_s']:.2f} | "
              f"{r['max_total_s']:.2f} | {r['mean_decisions']:.1f} | "
              f"{r['mean_decision_s']:.3f} |")
    print(f"\nsaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
