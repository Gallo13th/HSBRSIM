"""按 t15 tier 分组统计 Σ：给 s57 的"升本是否伤强度"诊断用。"""
from __future__ import annotations
import argparse, json, os, random, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np


def main() -> int:
    from comp_state_ab import ModelPolicy, _play_segment, _pool
    import hsbg_engine as E

    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--human-boards", default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-p", type=float, default=0.9)
    ap.add_argument("--human-seats", type=int, default=5)
    ap.add_argument("--games", type=int, default=96)
    ap.add_argument("--seed-base", type=int, default=520000)
    ap.add_argument("--device", default="cuda:3")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    pol = ModelPolicy(args.checkpoint, args.device)
    try:
        pol.cfg.temperature = 1e-6
    except BaseException:  # noqa: BLE001
        pass
    hpool = _pool(args.human_boards)
    rows = []
    for i in range(int(args.games)):
        g = E.Game(seed=int(args.seed_base) + i)
        q = {"max_steps": 20000, "human_board_pool": hpool, "human_board_p": args.human_p,
             "human_board_seats": args.human_seats, "human_board_fidelity": "board",
             "rng": random.Random((int(args.seed_base) + i) * 1000003 + 17),
             "strength": {}, "tiers": {}}
        pol.reset()
        _play_segment(g, pol, q)
        st = q.get("strength") or {}
        tiers = q.get("tiers") or {}
        t15 = int(st.get(15) or (max(st.values()) if st else 0))
        tier15 = int(tiers.get(15) or (tiers.get(max(tiers)) if tiers else 0))
        rows.append({"seed": int(args.seed_base) + i, "t15": t15, "tier15": tier15})
    hi = [r["t15"] for r in rows if r["tier15"] >= 5]
    lo = [r["t15"] for r in rows if r["tier15"] <= 4]
    out = {"n": len(rows),
           "tier_ge5_n": len(hi), "tier_ge5_sig_p50": float(np.percentile(hi, 50)) if hi else None,
           "tier_ge5_sig_mean": float(np.mean(hi)) if hi else None,
           "tier_le4_n": len(lo), "tier_le4_sig_p50": float(np.percentile(lo, 50)) if lo else None,
           "tier_le4_sig_mean": float(np.mean(lo)) if lo else None,
           "all_sig_p50": float(np.percentile([r["t15"] for r in rows], 50)),
           "tier_ge5_ratio": len(hi) / max(1, len(rows))}
    print(json.dumps(out, ensure_ascii=False))
    if args.out:
        json.dump({"summary": out, "rows": rows}, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
