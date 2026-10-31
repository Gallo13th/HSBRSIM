#!/usr/bin/env python3
"""t6（max_per_turn=6）在**正式封存面板**上的确认跑：与默认 t1 的同面板配对。

输入：
- ``runs/infer_search_formal/human_s14_t1.json``（正式 512×2 面板，默认 t1）；
- ``runs/infer_search_formal/confirm/s14_t6_panel{A,B}.json``（单面板 512 局，t6）。

做法：把 t6 的单面板负载与正式负载里**同 seed_base 的那个 panel** 配成一对，
再复用 ``infer_search_formal_ab.compare`` 的口径（逐局配对 Δrank + bootstrap CI）。

用法::

    python scripts/infer_search_confirm_ab.py \
        --base runs/infer_search_formal/human_s14_t1.json \
        --arm  runs/infer_search_formal/confirm/s14_t6_panelA.json \
        --arm  runs/infer_search_formal/confirm/s14_t6_panelB.json \
        --out  runs/infer_search_formal/ab_s14_t6_confirm.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from infer_search_formal_ab import compare  # noqa: E402


def _panel_key(p: Dict[str, Any]) -> int:
    return int((p.get("details") or {}).get("seed_base") or -1)


def _merge(base: Dict[str, Any], arms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按 seed_base 把每个 arm 的单面板拼成与 base 同构的多面板负载。"""
    by_seed = {}
    for a in arms:
        p = (a.get("panels") or [None])[0]
        if p is None:
            raise SystemExit("arm 负载没有 panel")
        by_seed[_panel_key(p)] = p
    out = copy.deepcopy(base)
    panels = []
    for p in base.get("panels") or []:
        k = _panel_key(p)
        if k not in by_seed:
            raise SystemExit(f"缺少 seed_base={k} 的确认面板")
        panels.append(by_seed[k])
    out["panels"] = panels
    out["checkpoint_sha256"] = base.get("checkpoint_sha256")
    out["config"] = dict(base.get("config") or {})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="t6 正式面板确认跑配对分析")
    ap.add_argument("--base", required=True, help="默认 t1 的多面板负载")
    ap.add_argument("--arm", action="append", required=True, help="t6 的单面板负载（可多次）")
    ap.add_argument("--bootstrap", type=int, default=20000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    base = json.load(open(args.base, encoding="utf-8"))
    arms = [json.load(open(p, encoding="utf-8")) for p in args.arm]
    on = _merge(base, arms)
    rep = compare(base, on, boot=int(args.bootstrap))
    rep["inputs"] = {"base": args.base, "arms": args.arm}
    txt = json.dumps(rep, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(txt)
    d = rep["rank"]["delta"]
    print(json.dumps({
        "n_pairs": rep["protocol"]["paired_games"],
        "mean_rank": {"base_t1": rep["rank"]["off_mean"], "t6": rep["rank"]["on_mean"]},
        "delta": d,
        "delta_panel_means": rep["rank"]["delta_panel_means"],
        "delta_stratified": rep["rank"]["delta_stratified"],
        "top4": rep["top4"],
        "strength": rep["strength"],
        "cost": rep["cost"],
        "criteria": rep["criteria"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
