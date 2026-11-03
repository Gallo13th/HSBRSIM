"""用 lookahead 策略评测状态：Σ15、耗时、Δp 统计。"""
from __future__ import annotations
import argparse, json, os, random, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np


def main() -> int:
    from comp_state_ab import ModelPolicy, _play_segment
    from policy_lookahead import LookaheadPolicy
    import hsbg_engine as E

    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--states", default="/tmp/s22/demo_states12.json")
    ap.add_argument("--sources", default="")
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--turn", type=int, default=-1)
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--temp", type=float, default=1e-6)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--min-turn", type=int, default=7)
    ap.add_argument("--device", default="cuda:3")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    rows = json.load(open(args.states, encoding="utf-8"))
    if args.sources:
        srcs = set(args.sources.split(","))
        rows = [r for r in rows if r.get("source") in srcs]
    if args.seed >= 0:
        rows = [r for r in rows if int(r.get("seed")) == args.seed]
    if args.turn >= 0:
        rows = [r for r in rows if int(r.get("turn")) == args.turn]
    if not rows:
        print("[la] no states matched", flush=True)
    res = []
    for state in rows:
        mp = ModelPolicy(args.checkpoint, args.device)
        mp.cfg.temperature = float(args.temp)
        pol = LookaheadPolicy(mp, k=args.k, min_turn=args.min_turn)
        vals = []
        for i in range(int(args.n)):
            g = E.Game.from_json(state["state"])
            q = {"max_steps": 20000, "human_board_pool": None, "human_board_p": 0.0,
                 "rng": random.Random(i * 1000003 + 17), "strength": {}, "tiers": {}}
            pol.reset()
            _play_segment(g, pol, q)
            stg = q.get("strength") or {}
            vals.append(int(stg.get(15) or (max(stg.values()) if stg else 0)))
        st = pol.stats
        ms_per = st["ms"] / max(1, st["lookahead"])
        res.append({"source": state.get("source"), "turn": state.get("turn"),
                    "p50": float(np.percentile(vals, 50)), "max": float(max(vals)),
                    "decisions": st["decisions"], "lookahead": st["lookahead"],
                    "dp_positive_rate": st["dp_positive"] / max(1, st["lookahead"]),
                    "ms_per_lookahead": round(ms_per, 2)})
        print(f"[la] {state.get('source')} t{state.get('turn')}: p50={res[-1]['p50']:.0f} "
              f"max={res[-1]['max']:.0f} lookahead={st['lookahead']} "
              f"dp+={res[-1]['dp_positive_rate']:.1%} {ms_per:.2f}ms", flush=True)
    if args.out:
        json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
