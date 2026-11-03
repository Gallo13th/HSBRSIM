"""从给定状态起点做 best-of-N 采样，报告 Σ15 分布（上限估计）。

用法：python scripts/best_of_n.py --checkpoint runs/az_entity_s44/model.pt \
    --states /tmp/s22/user_states/user_states.json --seed 671417 --turn 10 \
    --n 64 --temperature 1.0 --device cuda:3 --out /tmp/s22/bon64.json
"""
from __future__ import annotations
import argparse, json, os, random, sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np


def main() -> int:
    from comp_state_ab import ModelPolicy, _play_segment
    import hsbg_engine as E

    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--states", default="/tmp/s22/user_states/user_states.json")
    ap.add_argument("--seed", type=int, default=671417)
    ap.add_argument("--turn", type=int, default=10)
    ap.add_argument("--t8-sigma-min", type=float, default=-1.0,
                    help="只选 t8_sigma >= 该值的状态（区分同 seed 的多局）")
    ap.add_argument("--n", type=int, default=64)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--device", default="cuda:3")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = json.load(open(args.states, encoding="utf-8"))
    st = [r for r in rows if int(r.get("seed")) == args.seed
          and int(r.get("turn")) == args.turn
          and (float(r.get("t8_sigma") or 0) >= float(args.t8_sigma_min))]
    if not st:
        print("state not found", flush=True); return 2
    state = st[0]
    start_turn = int(state["turn"])
    mp = ModelPolicy(args.checkpoint, args.device)
    mp.cfg.temperature = float(args.temperature)
    out: List[Dict[str, Any]] = []
    for i in range(int(args.n)):
        g = E.Game.from_json(state["state"])
        rng = random.Random(i * 1000003 + 17)
        q = {"max_steps": 20000, "human_board_pool": None, "human_board_p": 0.0,
             "rng": rng, "strength": {}, "tiers": {}}
        mp.reset()
        r = _play_segment(g, mp, q)
        stg = r.get("strength") or {}
        s_start = int(stg.get(start_turn) or 0)
        s_end = int(stg.get(15) or (max(stg.values()) if stg else 0))
        fb = []
        try:
            v = json.loads(g.view(0))
            fb = [str((m or {}).get("id") or "") for m in ((v.get("me") or {}).get("board") or [])]
        except BaseException:  # noqa: BLE001
            pass
        out.append({"i": i, "s_start": s_start, "s_end": s_end,
                    "multiple": (s_end / s_start) if s_start > 0 else None,
                    "turns": max(stg) if stg else 0, "board": fb})
        if (i + 1) % 16 == 0:
            print(f"[bon] {i+1}/{args.n}", flush=True)
    arr = np.asarray([x["s_end"] for x in out], dtype=np.float64)
    res = {"n": len(out), "start_sigma": out[0]["s_start"],
           "s15_p50": float(np.percentile(arr, 50)), "s15_p90": float(np.percentile(arr, 90)),
           "s15_max": float(arr.max()), "s15_mean": float(arr.mean()),
           "success_ge_20k": float((arr >= 20000).mean()),
           "multiple_p50": float(np.percentile([x["multiple"] or 0 for x in out], 50)),
           "multiple_max": float(max((x["multiple"] or 0) for x in out)),
           "samples": sorted(out, key=lambda x: -x["s_end"])[:8]}
    print(json.dumps({k: v for k, v in res.items() if k != "samples"}, ensure_ascii=False), flush=True)
    if args.out:
        json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
