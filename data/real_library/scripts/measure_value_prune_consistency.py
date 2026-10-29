"""同一决策状态上 pairwise vs value-prune 的动作一致率/成本对比。"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel, PolicyEvaluator
from hsbg.search.turn_search import TurnSearch, TurnSearchConfig


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--decisions", type=int, default=20)
    p.add_argument("--states", type=int, default=16)
    p.add_argument("--prune-top-k", type=int, default=4)
    p.add_argument("--checkpoint", default="runs/bc/official_320/policy_bc.pt")
    p.add_argument("--out", default="runs/search/turn_search_value_prune_consistency.json")
    args = p.parse_args(argv)
    ev = PolicyEvaluator(args.checkpoint)
    base = dict(states_budget=args.states, samples_per_action=1,
                seed=7, completion_policy="heuristic")
    ts_pair = TurnSearch(TurnSearchConfig(state_scorer="pairwise", **base),
                         evaluator=ev)
    ts_prune = TurnSearch(TurnSearchConfig(
        state_scorer="value_prune_pairwise", prune_top_k=args.prune_top_k,
        **base), evaluator=ev)
    rows = []
    teacher = HeuristicPolicy()
    for game_seed in range(401, 409):
        if len(rows) >= args.decisions:
            break
        env = BattlegroundsEnv(seed=game_seed, opponent="teacher")
        obs = env.reset(seed=game_seed)
        step = 0
        while len(rows) < args.decisions and step < 600:
            if getattr(obs, "phase", "") == "choice":
                obs, *_ = env.step(0)
                step += 1
                continue
            try:
                m = EngineForwardModel.from_env(env, clone=False)
            except Exception:  # noqa: BLE001
                break
            t0 = time.perf_counter()
            a = ts_pair.decide(m)
            pair_ms = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            b = ts_prune.decide(m)
            prune_ms = (time.perf_counter() - t0) * 1000
            if a.action is not None and b.action is not None:
                rows.append({
                    "seed": game_seed, "turn": int(m.turn),
                    "n_states": a.n_states,
                    "same_action": bool(a.action.signature() == b.action.signature()),
                    "pairwise_action": a.action.signature(),
                    "prune_action": b.action.signature(),
                    "pairwise_combats": a.n_combats,
                    "prune_combats": b.n_combats,
                    "pairwise_ms": round(pair_ms, 1),
                    "prune_ms": round(prune_ms, 1),
                })
            try:
                d = teacher.choose(env.game, env._agent)
                sig = None if d is None else d.to_candidate().signature()
                idx = next((i for i, c in enumerate(obs.candidates)
                            if c.signature() == sig), 0)
            except Exception:  # noqa: BLE001
                idx = 0
            obs, *_ = env.step(idx)
            step += 1
        env.close()
    same = sum(1 for r in rows if r["same_action"])
    out = {
        "n_decisions": len(rows),
        "same_action_rate": same / max(1, len(rows)),
        "mean_pairwise_ms": statistics.fmean([r["pairwise_ms"] for r in rows])
        if rows else 0.0,
        "mean_prune_ms": statistics.fmean([r["prune_ms"] for r in rows])
        if rows else 0.0,
        "mean_pairwise_combats": statistics.fmean(
            [r["pairwise_combats"] for r in rows]) if rows else 0.0,
        "mean_prune_combats": statistics.fmean(
            [r["prune_combats"] for r in rows]) if rows else 0.0,
        "rows": rows,
        "checkpoint": args.checkpoint,
        "note": "同一状态/枚举下 pairwise vs value-prune 的动作一致率；仅诊断",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "n_decisions", "same_action_rate", "mean_pairwise_ms", "mean_prune_ms",
        "mean_pairwise_combats", "mean_prune_combats")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
