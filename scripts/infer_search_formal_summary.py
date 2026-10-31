#!/usr/bin/env python3
"""汇总正式协议 A/B + 调参表 + 叶值消融 → ``runs/infer_search_formal/SUMMARY.json``。

数据来源（全部由 ``scripts/human_panel_eval.py`` 产生）：

- 正式：``runs/infer_search_formal/human_<ck>_<off|t1>.json``
  （512 局 × 2 封存面板；``--confirmations 2``）；
- 调参：``runs/infer_search_formal/tune/<ck>_<name>.json``（256 局单面板，seed 830901）；
- 叶值消融：同上目录里 ``<ck>_h*`` / ``<ck>_tier*``。

配对统计全部走 ``scripts/infer_search_formal_ab.compare``（同一实现，避免口径漂移）。

用法::

    python scripts/infer_search_formal_summary.py \
        --dir runs/infer_search_formal --out runs/infer_search_formal/SUMMARY.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from infer_search_formal_ab import compare  # noqa: E402


def _load(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _panel_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    """单负载的跨面板聚合（mean rank / top4 / 搜索成本 / 墙钟）。"""
    pans = payload.get("panels") or []
    ranks: List[int] = []
    top4 = 0
    win = 0
    secs = 0.0
    calls = 0
    ms = 0.0
    games = 0
    for p in pans:
        d = p.get("details") or {}
        per = d.get("per_seat") or {}
        for name in per:
            seq = ((per[name].get("model") or {}).get("rank_sequence") or [])
            ranks.extend(int(r) for r in seq)
        g = int(p.get("n") or len(ranks))
        games += g
        top4 += int(round(float(p.get("model_top4") or 0.0) * g))
        win += int(round(float(p.get("model_win") or 0.0) * g))
        secs += float(p.get("model_seconds") or 0.0)
        s = p.get("search") or {}
        calls += int(s.get("search_calls") or 0)
        ms += float(s.get("search_ms_total") or 0.0)
    n = len(ranks)
    return {"games": n, "mean_rank": (sum(ranks) / n) if n else None,
            "top4": (top4 / n) if n else None, "win": (win / n) if n else None,
            "model_seconds": round(secs, 1),
            "search_calls": calls,
            "search_calls_per_game": round(calls / n, 2) if n else None,
            "mean_ms_per_call": round(ms / calls, 2) if calls else None,
            "search_ms_per_game": round(ms / n, 1) if n else None,
            "panels": [{"seed_base": (p.get("details") or {}).get("seed_base"),
                        "mean_rank": p.get("model_mean_rank"),
                        "top4": p.get("model_top4"),
                        "seconds": p.get("model_seconds"),
                        "search": {k: (p.get("search") or {}).get(k) for k in
                                   ("search_calls_per_game", "mean_ms_per_call",
                                    "search_ms_per_game", "switch_rate")}}
                       for p in pans]}


def _knobs(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = (payload.get("panels") or [{}])[0]
    s = p.get("search") or {}
    return {k: s.get(k) for k in ("enabled", "turns", "when", "action", "topk",
                                  "max_per_turn", "tier_bonus", "health_bonus",
                                  "max_ms_per_search")}


def main() -> int:
    ap = argparse.ArgumentParser(description="推理期搜索正式/调参/消融汇总")
    ap.add_argument("--dir", default="runs/infer_search_formal")
    ap.add_argument("--ckpts", default="s14,s16,s16b")
    ap.add_argument("--tune-ckpt", default="",
                    help="调参所用 checkpoint 标签（默认 = 正式 t1 名次最好的那个）")
    ap.add_argument("--out", default="")
    ap.add_argument("--bootstrap", type=int, default=20000)
    args = ap.parse_args()
    D = args.dir
    out: Dict[str, Any] = {"dir": D, "formal": {}, "tune": {}, "ablation": {}}

    # ── 正式：<ck> × {off, t1} ──────────────────────────────────────────────
    for ck in [x.strip() for x in args.ckpts.split(",") if x.strip()]:
        off = _load(os.path.join(D, f"human_{ck}_off.json"))
        on = _load(os.path.join(D, f"human_{ck}_t1.json"))
        row: Dict[str, Any] = {"off": None, "on": None, "ab": None}
        if off:
            row["off"] = {**_panel_summary(off),
                          "checkpoint_sha256": off.get("checkpoint_sha256"),
                          "knobs": _knobs(off)}
        if on:
            row["on"] = {**_panel_summary(on),
                         "checkpoint_sha256": on.get("checkpoint_sha256"),
                         "knobs": _knobs(on)}
        if off and on:
            ab = compare(off, on, boot=int(args.bootstrap))
            row["ab"] = {
                "protocol": ab["protocol"],
                "delta": ab["rank"]["delta"],
                "delta_stratified": ab["rank"]["delta_stratified"],
                "delta_panel_means": ab["rank"]["delta_panel_means"],
                "top4": ab["top4"],
                "win": ab["win"],
                "rank_hist": ab["rank_hist"],
                "strength": ab["strength"],
                "cost": ab["cost"],
                "criteria": ab["criteria"],
                "per_panel": [{"panel_idx": p["panel_idx"],
                               "seed_base": p["seed_base"],
                               "mean_rank_off": p["mean_rank_off"],
                               "mean_rank_on": p["mean_rank_on"],
                               "delta": p["delta"],
                               "seconds_off": p["model_seconds_off"],
                               "seconds_on": p["model_seconds_on"]}
                              for p in ab["per_panel"]],
            }
            txt = os.path.join(D, f"ab_{ck}_t1.json")
            with open(txt, "w", encoding="utf-8") as f:
                json.dump(ab, f, ensure_ascii=False, indent=2)
        out["formal"][ck] = row

    ranked = [(ck, r["on"]["mean_rank"]) for ck, r in out["formal"].items()
              if (r.get("on") or {}).get("mean_rank") is not None]
    ranked.sort(key=lambda x: float(x[1]))
    out["ranking_t1"] = [{"ckpt": ck, "mean_rank_t1": mr} for ck, mr in ranked]
    ranked_off = [(ck, r["off"]["mean_rank"]) for ck, r in out["formal"].items()
                  if (r.get("off") or {}).get("mean_rank") is not None]
    ranked_off.sort(key=lambda x: float(x[1]))
    out["ranking_off"] = [{"ckpt": ck, "mean_rank_off": mr} for ck, mr in ranked_off]
    tune_ck = args.tune_ckpt or (ranked[0][0] if ranked else "")

    # ── 调参：单面板 256 局，逐配置 vs 参考 t1 ─────────────────────────────
    tune_dir = os.path.join(D, "tune")
    trows: Dict[str, Any] = {}
    ref: Optional[Dict[str, Any]] = None
    ref_path = os.path.join(tune_dir, f"{tune_ck}_ref.json")
    if os.path.isfile(ref_path):
        ref = _load(ref_path)
        trows["ref"] = {"path": ref_path, **_panel_summary(ref), "knobs": _knobs(ref),
                        "delta_vs_ref": None}
    for path in sorted(glob.glob(os.path.join(tune_dir, f"{tune_ck}_*.json"))):
        name = os.path.basename(path)[len(tune_ck) + 1:-5]
        if name == "ref":
            continue
        payload = _load(path)
        if not payload:
            continue
        row = {"path": path, **_panel_summary(payload), "knobs": _knobs(payload)}
        if ref is not None:
            ab = compare(ref, payload, boot=int(args.bootstrap))
            row["delta_vs_ref"] = {
                "delta": ab["rank"]["delta"],
                "top4_delta": ab["top4"]["delta"],
                "criteria": ab["criteria"],
                "cost": {"on_search_calls_per_game":
                         ab["cost"]["on_search_calls_per_game"],
                         "on_mean_ms_per_call": ab["cost"]["on_mean_ms_per_call"],
                         "on_search_ms_per_game": ab["cost"]["on_search_ms_per_game"],
                         "on_switch_rate": ab["cost"]["on_switch_rate"]},
            }
            with open(os.path.join(D, f"ab_tune_{tune_ck}_{name}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(ab, f, ensure_ascii=False, indent=2)
        else:
            row["delta_vs_ref"] = None
        trows[name] = row
    out["tune"] = {"ckpt": tune_ck, "panel_seed_base": 830901, "games": 256,
                   "configs": trows}

    # ── 叶值消融：h*/tier* 已在调参目录里，单独列出 ────────────────────────
    abl: Dict[str, Any] = {}
    for name, row in trows.items():
        if name.startswith(("h0", "h_", "health", "tier", "t0")):
            abl[name] = {"knobs": row["knobs"], "mean_rank": row["mean_rank"],
                         "delta_vs_ref": (row.get("delta_vs_ref") or {}).get("delta")}
    out["ablation"] = abl

    txt = json.dumps(out, ensure_ascii=False, indent=2)
    outp = args.out or os.path.join(D, "SUMMARY.json")
    os.makedirs(os.path.dirname(os.path.abspath(outp)) or ".", exist_ok=True)
    with open(outp, "w", encoding="utf-8") as f:
        f.write(txt)
    # ── 控制台快照（人工核对用）────────────────────────────────────────────
    print(json.dumps({
        "formal": {ck: {"off": (r.get("off") or {}).get("mean_rank"),
                        "t1": (r.get("on") or {}).get("mean_rank"),
                        "delta": ((r.get("ab") or {}).get("delta") or {}).get("mean"),
                        "ci": [((r.get("ab") or {}).get("delta") or {}).get("ci_low"),
                               ((r.get("ab") or {}).get("delta") or {}).get("ci_high")]}
                   for ck, r in out["formal"].items()},
        "ranking_t1": out["ranking_t1"],
        "tune_ckpt": tune_ck,
        "tune": {k: {"rank": v["mean_rank"],
                     "d": ((v.get("delta_vs_ref") or {}).get("delta") or {}).get("mean"),
                     "ci_hi": ((v.get("delta_vs_ref") or {}).get("delta") or {}).get("ci_high"),
                     "knobs": v["knobs"]}
                 for k, v in trows.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
