"""从 06-t8 起点自举采样：温度 0.3/0.7 ×N，报 Σ15 分布 + t9 时伴生卡数。"""
from __future__ import annotations
import argparse, json, os, random, sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np

COMPANION = {"BG29_813": "poet", "BG36_245": "arcanist", "BG36_640": "amalgam"}


def main() -> int:
    from comp_state_ab import ModelPolicy, _play_segment
    import hsbg_engine as E

    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--states", default="/tmp/s22/chain_states.json")
    ap.add_argument("--source", default="671417_06_t8")
    ap.add_argument("--n", type=int, default=128)
    ap.add_argument("--temps", default="0.3,0.7")
    ap.add_argument("--device", default="cuda:3")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cid2id = {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}
    rows = json.load(open(args.states, encoding="utf-8"))
    state = next(r for r in rows if str(r.get("source")) == args.source)
    start_turn = int(state["turn"])
    mp = ModelPolicy(args.checkpoint, args.device)
    report = {}
    for temp in [float(x) for x in args.temps.split(",")]:
        mp.cfg.temperature = temp
        vals, comp_counts, comp_boards = [], [], []
        for i in range(int(args.n)):
            g = E.Game.from_json(state["state"])
            rng = random.Random(i * 1000003 + 17)
            q = {"max_steps": 20000, "human_board_pool": None, "human_board_p": 0.0,
                 "rng": rng, "strength": {}, "tiers": {}}
            mp.reset()
            r = _play_segment(g, mp, q, gate_turn=9)   # 到 t9 开始
            pj = json.loads(g.player_json(0))
            board = [cid2id.get(int(m.get("card") or -1), "") for m in (pj.get("board") or [])]
            comp = [c for c in board if (c[:-2] if c.endswith("_G") else c) in COMPANION]
            _play_segment(g, mp, q)                    # 打到终局
            stg = q.get("strength") or {}              # 注意：第二段会替换 q["strength"]
            s15 = int(stg.get(15) or (max(stg.values()) if stg else 0))
            vals.append(s15)
            comp_counts.append(len(comp))
            comp_boards.append(board)
        arr = np.asarray(vals, dtype=np.float64)
        report[str(temp)] = {
            "n": len(vals), "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)), "max": float(arr.max()),
            "success_ge_20k": float((arr >= 20000).mean()),
            "comp_p50": float(np.percentile(comp_counts, 50)),
            "comp_mean": float(np.mean(comp_counts)),
            "comp_hist": {str(k): int(comp_counts.count(k)) for k in sorted(set(comp_counts))},
            "top8": sorted(
                [{"s15": int(v), "comp": int(c), "board": b}
                 for v, c, b in zip(vals, comp_counts, comp_boards)],
                key=lambda x: -x["s15"])[:8],
        }
        print(f"[bon] temp={temp}: p50={report[str(temp)]['p50']:.0f} "
              f"p90={report[str(temp)]['p90']:.0f} max={report[str(temp)]['max']:.0f} "
              f"success={report[str(temp)]['success_ge_20k']:.1%} "
              f"comp_p50={report[str(temp)]['comp_p50']:.0f}", flush=True)
    if args.out:
        json.dump({"start": args.source, "start_turn": start_turn, "by_temp": report},
                  open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
