"""对多个起点状态做 greedy / 温度 0.3 采样，报 p50/max/成功率 + 链卡在场数。"""
from __future__ import annotations
import argparse, json, os, random, sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np

CHAIN = {"BG21_015", "BG29_813", "BG36_245", "BG36_640"}


def main() -> int:
    from comp_state_ab import ModelPolicy, _play_segment
    import hsbg_engine as E

    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--states", default="/tmp/s22/user_states/user_states.json")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--device", default="cuda:3")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = json.load(open(args.states, encoding="utf-8"))
    mp = ModelPolicy(args.checkpoint, args.device)
    report: List[Dict[str, Any]] = []
    for state in rows:
        start_turn = int(state["turn"])
        # 起点链卡（从 state 的 learner 盘面）
        g0 = E.Game.from_json(state["state"])
        pj = json.loads(g0.player_json(0))
        board = [str((m or {}).get("id") or "") for m in (pj.get("board") or [])]
        chain_n = sum(1 for c in board if (c[:-2] if c.endswith("_G") else c) in CHAIN)
        for temp, tag in ((1e-6, "greedy"), (0.3, "t0.3")):
            mp.cfg.temperature = float(temp)
            vals = []
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
                vals.append((s_start, s_end))
            arr = np.asarray([v[1] for v in vals], dtype=np.float64)
            s0 = vals[0][0]
            report.append({
                "state": f"{state.get('source')}_t{start_turn}", "seed": state["seed"],
                "start_turn": start_turn, "s_start": s0, "chain_cards": chain_n,
                "temp": tag,
                "p50": float(np.percentile(arr, 50)), "max": float(arr.max()),
                "success_ge_20k": float((arr >= 20000).mean()),
                "multiple_p50": float((np.percentile(arr, 50) / s0) if s0 > 0 else 0),
                "multiple_max": float((arr.max() / s0) if s0 > 0 else 0),
            })
        print(f"[bon] {state.get('source')}_t{start_turn} s_start={report[-2]['s_start']} "
              f"chain={chain_n} greedy_p50={report[-2]['p50']:.0f} "
              f"t0.3_p50={report[-1]['p50']:.0f}", flush=True)
    if args.out:
        json.dump(report, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n| 起点 | s_start | 链卡 | greedy p50/max/成功 | 0.3 p50/max/成功 | 倍数(0.3 p50) |")
    for r in report:
        if r["temp"] != "greedy":
            g = [x for x in report if x["state"] == r["state"] and x["temp"] == "greedy"][0]
            print(f"| {r['state']} | {r['s_start']} | {r['chain_cards']} | "
                  f"{g['p50']:.0f}/{g['max']:.0f}/{g['success_ge_20k']:.0%} | "
                  f"{r['p50']:.0f}/{r['max']:.0f}/{r['success_ge_20k']:.0%} | {r['multiple_p50']:.1f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
