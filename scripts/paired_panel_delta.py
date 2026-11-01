#!/usr/bin/env python3
"""同 seed/同 seat 的两个人类战团面板 → 配对 rank Δ 与 bootstrap 95% CI。

``scripts/human_panel_eval.py --smoke --games N`` 的产物里有
``panels[0].details.per_seat.seat_k.model.rank_sequence``（逐局名次，顺序 = 该 seat 的
seed 递增）。本脚本按 ``(seat, 局序)`` 严格配对，报：

- ``mean_rank_before / mean_rank_after``、配对 ``delta = after − before``（名次越小越好，
  所以负值 = 变强）；
- 配对 bootstrap（默认 5000 次）95% CI、SE；
- 变好/变差局数、top4 率变化、非法/截断计数校验。

用法::

    python scripts/paired_panel_delta.py \
        --before runs/az_entity_s19/eval/human_baseline_s17_128.json \
        --after  runs/az_entity_s19/eval/human_005000000.json \
        --out    runs/az_entity_s19/eval/paired_5M.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not d.get("panels"):
        raise SystemExit(f"{path}: 没有 panels 段（面板失败？）")
    p = d["panels"][0]
    det = p.get("details") or {}
    per_seat = det.get("per_seat") or {}
    ranks = []
    seats = []
    for name in sorted(per_seat, key=lambda s: int(str(s).split("_")[-1])):
        row = per_seat[name]
        m = (row.get("model") or {})
        seq = m.get("rank_sequence")
        if seq is None:
            raise SystemExit(f"{path}: {name} 缺 rank_sequence")
        ranks.extend(int(r) for r in seq)
        seats.extend([int(str(name).split("_")[-1])] * len(seq))
    if not ranks:
        raise SystemExit(f"{path}: 逐局面板为空")
    return {"path": os.path.abspath(path), "ranks": np.asarray(ranks, np.int64),
            "seats": np.asarray(seats, np.int64),
            "mean_rank": float(np.mean(ranks)),
            "top4": float(np.mean(np.asarray(ranks) <= 4)),
            "n": int(len(ranks)),
            "checkpoint": d.get("checkpoint"),
            "sha256": d.get("checkpoint_sha256"),
            "config": d.get("config") or {},
            "illegal": int(p.get("illegal") or 0),
            "truncated": int(p.get("truncated") or 0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20261101)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    a = _load(args.before)
    b = _load(args.after)
    if a["n"] != b["n"]:
        raise SystemExit(f"样本数不一致: before={a['n']} after={b['n']}")
    if not np.array_equal(a["seats"], b["seats"]):
        raise SystemExit("seat 顺序不一致：不是同一配对面板")
    diff = (b["ranks"] - a["ranks"]).astype(np.float64)
    rng = np.random.default_rng(int(args.seed))
    n = diff.size
    idx = rng.integers(0, n, size=(int(args.bootstrap), n))
    boot = diff[idx].mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    out = {
        "before": a["path"], "after": b["path"],
        "before_checkpoint": a["checkpoint"], "after_checkpoint": b["checkpoint"],
        "before_sha256": a["sha256"], "after_sha256": b["sha256"],
        "n": int(n), "bootstrap": int(args.bootstrap),
        "mean_rank_before": round(float(a["mean_rank"]), 6),
        "mean_rank_after": round(float(b["mean_rank"]), 6),
        "delta": round(float(diff.mean()), 6),
        "se_bootstrap": round(float(boot.std(ddof=1)), 6),
        "ci_low": round(float(lo), 6), "ci_high": round(float(hi), 6),
        "better_games": int((diff < 0).sum()),
        "worse_games": int((diff > 0).sum()),
        "tie_games": int((diff == 0).sum()),
        "top4_before": round(float(a["top4"]), 6),
        "top4_after": round(float(b["top4"]), 6),
        "top4_delta": round(float(b["top4"] - a["top4"]), 6),
        "illegal_before": a["illegal"], "illegal_after": b["illegal"],
        "truncated_before": a["truncated"], "truncated_after": b["truncated"],
        "passed_hard_criterion": bool(diff.mean() <= -0.10 and hi < 0.0),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
