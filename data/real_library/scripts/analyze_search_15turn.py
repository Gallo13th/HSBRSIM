"""Analyze search_15turn_bench results: config summary + paired deltas."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB


def load_bench():
    path = ROOT / "scripts" / "search_15turn_bench.py"
    spec = importlib.util.spec_from_file_location("search_15turn_bench", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ci95(vals: List[float]) -> List[float]:
    if len(vals) < 2:
        return [vals[0] if vals else 0.0, vals[0] if vals else 0.0]
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals)
    half = 1.96 * sd / math.sqrt(len(vals))
    return [mean - half, mean + half]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="runs/search_15turn_bench_full/results.json",
                    help="comma-separated results.json files")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    paths = [Path(x.strip()) for x in args.results.split(",") if x.strip()]
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    rows = []
    for p in paths:
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.extend(d["rows"])
    # 去重（同 config+seed 只保留一条）
    uniq = {}
    for r in rows:
        key = (r["width"], r["depth"], r["horizon"], r["seed"])
        uniq[key] = r
    rows = list(uniq.values())
    bench = load_bench()
    bench._pairwise(rows, CardDB.load("data"))
    base_key = "w1_d1_h0"
    by_seed = {}
    for row in rows:
        key = f"w{row['width']}_d{row['depth']}_h{row['horizon']}"
        by_seed.setdefault(key, {})[row["seed"]] = row
    base = by_seed.get(base_key, {})
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(
            f"w{row['width']}_d{row['depth']}_h{row['horizon']}", []).append(row)
    summary = []
    for key, rs in sorted(groups.items()):
        deltas = []
        for r in rs:
            b = base.get(r["seed"])
            if b is not None:
                deltas.append(r["board_value"] - b["board_value"])
        summary.append({
            "config": key,
            "n": len(rs),
            "mean_value": statistics.fmean(r["board_value"] for r in rs),
            "sd_value": statistics.stdev(r["board_value"] for r in rs)
            if len(rs) > 1 else 0.0,
            "mean_stats": statistics.fmean(r["board_stats"] for r in rs),
            "mean_tier": statistics.fmean(r["tier"] for r in rs),
            "mean_pair_winrate": statistics.fmean(r["pair_winrate_unique"] for r in rs),
            "mean_elapsed_s": statistics.fmean(r["elapsed_s"] for r in rs),
            "delta_vs_baseline_mean": statistics.fmean(deltas) if deltas else 0.0,
            "delta_vs_baseline_ci95": _ci95(deltas) if deltas else [0.0, 0.0],
            "n_pairs": len(deltas),
        })
    # unique boards
    keys = {json.dumps(r["final_board"], sort_keys=True, ensure_ascii=False)
            for r in rows}
    out = {
        "results": [str(p) for p in paths],
        "rows": len(rows),
        "unique_boards": len(keys),
        "seeds": sorted({r["seed"] for r in rows}),
        "summary": summary,
    }
    out_path = Path(args.out) if args.out else paths[0].parent / "analysis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    md = ["# 15-turn search benchmark analysis", "",
          f"- rows={len(rows)}, unique final boards={len(keys)}, "
          f"seeds={out['seeds']}",
          f"- baseline={base_key}", "",
          "| config | n | value mean±sd | Δ vs base [95% CI] | pair winrate | "
          "stats | tier | s/run |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in summary:
        lo, hi = s["delta_vs_baseline_ci95"]
        md.append(
            f"| {s['config']} | {s['n']} | {s['mean_value']:.2f}±{s['sd_value']:.2f} | "
            f"{s['delta_vs_baseline_mean']:+.2f} [{lo:+.2f},{hi:+.2f}] | "
            f"{s['mean_pair_winrate']:.3f} | {s['mean_stats']:.0f} | "
            f"{s['mean_tier']:.1f} | {s['mean_elapsed_s']:.1f} |")
    (out_path.parent / "ANALYSIS.md").write_text("\n".join(md) + "\n",
                                                 encoding="utf-8")
    print(json.dumps({"out": str(out_path), "summary": summary},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
