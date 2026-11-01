#!/usr/bin/env python3
"""随机性感知搜索 K 表：读 ``panel_{off,k1,k1s,k2,k4}.json`` → 汇总 JSON + Markdown。

口径（与 ``docs/STOCHASTIC_SEARCH.md`` 一致）：

- 名次：每臂 128 局（4 seat × 32，seed 420000 起）的 mean rank / top4；
  与 ``off`` 逐局配对，20000 次 bootstrap 的 95% CI；
- 耗时：``model_seconds``（整臂墙钟，含搜索）/ 128 局、``mean_ms_per_call``；
- 方差：``mean_q_se``（每次决策候选叶值均值的标准误）与 ``q_se_ratio``
  （= mean_q_se / 候选间 Q 标准差）；K=1 greedy 为 0（确定性路径）。

用法::

    python scripts/stoch_search_summary.py --dir runs/stoch_search \
        --out runs/stoch_search/SUMMARY.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ARMS: Tuple[Tuple[str, str], ...] = (
    ("off", "关闭搜索（基线）"),
    ("k1", "K=1 greedy（旧路径）"),
    ("k1s", "K=1 sample（单样本 Monte-Carlo 对照）"),
    ("k2", "K=2 sample"),
    ("k4", "K=4 sample"),
)


def _ranks(panel: Dict[str, Any]) -> List[int]:
    ps = (panel.get("details") or {}).get("per_seat") or {}
    out: List[int] = []
    for k in sorted(ps, key=lambda x: int(str(x).split("_")[1])):
        seq = ((ps[k].get("model") or {}).get("rank_sequence") or [])
        out.extend(int(r) for r in seq)
    return out


def _paired(after: List[int], before: List[int], *, n_boot: int = 20000,
            seed: int = 0) -> Dict[str, Any]:
    a = np.asarray(after, dtype=np.float64)
    b = np.asarray(before, dtype=np.float64)
    if a.size != b.size or a.size == 0:
        return {"n": int(min(a.size, b.size)), "mean": None}
    d = a - b
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, d.size, size=(int(n_boot), d.size))
    boots = d[idx].mean(axis=1)
    return {"n": int(d.size), "mean": float(d.mean()),
            "ci_low": float(np.percentile(boots, 2.5)),
            "ci_high": float(np.percentile(boots, 97.5)),
            "frac_improved": float((d < 0).mean()),
            "after_mean": float(a.mean()), "before_mean": float(b.mean())}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="随机性感知搜索 K 表汇总")
    ap.add_argument("--dir", default="runs/stoch_search")
    ap.add_argument("--out", default="runs/stoch_search/SUMMARY.json")
    ap.add_argument("--bootstrap", type=int, default=20000)
    args = ap.parse_args(argv)
    rows: Dict[str, Any] = {}
    off_ranks: List[int] = []
    for key, desc in ARMS:
        path = os.path.join(args.dir, f"panel_{key}.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        panel = (payload.get("panels") or [{}])[0]
        ranks = _ranks(panel)
        s = panel.get("search") or {}
        row = {
            "desc": desc, "n": len(ranks),
            "mean_rank": float(np.mean(ranks)) if ranks else None,
            "top4": float(np.mean(np.asarray(ranks) <= 4)) if ranks else None,
            "win": float(np.mean(np.asarray(ranks) == 1)) if ranks else None,
            "seconds": panel.get("model_seconds"),
            "sec_per_game": (round(float(panel["model_seconds"]) / max(len(ranks), 1), 2)
                             if panel.get("model_seconds") else None),
            "search_calls": s.get("search_calls"),
            "ms_per_call": s.get("mean_ms_per_call"),
            "ms_per_game": s.get("search_ms_per_game"),
            "calls_per_game": s.get("search_calls_per_game"),
            "switch_rate": s.get("switch_rate"),
            "leaf_steps_per_call": s.get("leaf_steps_per_call"),
            "mean_q_se": s.get("mean_q_se"),
            "q_se_ratio": s.get("q_se_ratio"),
            "rollouts": s.get("rollouts"),
            "rollout_mode": s.get("rollout_mode"),
            "timeouts": s.get("search_timeouts"),
            "errors": s.get("search_errors"),
            "path": path,
        }
        rows[key] = row
        if key == "off":
            off_ranks = ranks
    for key in rows:
        if key != "off" and off_ranks and rows[key]["n"] == len(off_ranks):
            path = rows[key]["path"]
            with open(path, encoding="utf-8") as f:
                panel = (json.load(f).get("panels") or [{}])[0]
            rows[key]["paired_vs_off"] = _paired(_ranks(panel), off_ranks,
                                                n_boot=int(args.bootstrap), seed=7)
    summary = {"dir": os.path.abspath(args.dir), "arms": rows}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    # Markdown 表
    lines = ["| 臂 | K | rollout | mean rank | top4 | Δ vs off [95% CI] | "
             "s/局 | ms/call | q_se | q_se/spread |",
             "|---|---:|---|---:|---:|---|---:|---:|---:|---:|"]
    for key, _desc in ARMS:
        if key not in rows:
            continue
        r = rows[key]
        p = r.get("paired_vs_off") or {}
        d = ("—" if p.get("mean") is None else
             f"{p['mean']:+.3f} [{p['ci_low']:+.3f}, {p['ci_high']:+.3f}]")
        lines.append(
            f"| {key} | {r.get('rollouts')} | {r.get('rollout_mode')} | "
            f"{r['mean_rank']:.3f} | {r['top4']:.3f} | {d} | "
            f"{r.get('sec_per_game')} | {r.get('ms_per_call')} | "
            f"{r.get('mean_q_se')} | {r.get('q_se_ratio')} |")
    md = "\n".join(lines) + "\n"
    md_path = os.path.splitext(args.out)[0] + ".md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"[ok] {args.out} / {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
