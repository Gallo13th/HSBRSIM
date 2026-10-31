#!/usr/bin/env python3
"""推理期搜索**多封存面板**正式 A/B：``--confirmations 2`` 的面板 JSON 配对分析。

与 ``scripts/infer_search_ab.py`` 的差别
--------------------------------------
``infer_search_ab.py`` 只看 ``panels[0]``（单面板 smoke 口径）。正式协议是
**512 局 × 2 个不重叠封存面板**（``--games 512 --seats 8 --confirmations 2``），
一个 JSON 里有 2 个 panel。本脚本：

- 逐面板校验配对键一致（同 (seat, 局序) = 同一局），**先按面板**再**合并**；
- 主统计：**合并 1024 局**的 ``Δrank = rank(on) − rank(off)`` 均值 + 95% bootstrap CI，
  外加**面板分层 bootstrap**（每个面板内独立重采样后取平均，对「面板间差异」更稳健）
  与**逐面板 Δ**（看两个封存面板是否同向）；
- top4 / 冠军率 / 分位直方图；
- 强度：t10/t12/t15 条件 p50 比值、t1–t17 生存率与无条件 E[Σ] 比值（逐面板后取中位）；
- 成本：搜索次数/单次 ms/每局 ms/墙钟；
- 判据：``Δ ≤ −0.10 且 CI 上界 < +0.05``。

用法::

    python scripts/infer_search_formal_ab.py \
        --off runs/infer_search_formal/human_s16b_off.json \
        --on  runs/infer_search_formal/human_s16b_t1.json \
        --out runs/infer_search_formal/ab_s16b_t1.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from infer_search_ab import _mean_ci, _paired_strength, _ranks  # noqa: E402


def _panel_ranks(panel: Dict[str, Any]) -> Tuple[List[int], List[Tuple[int, int]]]:
    """单个 panel 的 (rank 序列, (seat, 局序) 键)。"""
    return _ranks(panel)


def _search_meta(panel: Dict[str, Any]) -> Dict[str, Any]:
    s = panel.get("search") or {}
    return {k: s.get(k) for k in
            ("enabled", "turns", "when", "action", "topk", "max_per_turn",
             "search_calls", "mean_ms_per_call", "search_ms_per_game",
             "search_calls_per_game", "switch_rate", "leaf_steps_per_call",
             "search_errors", "search_timeouts", "rollout_truncated")}


def _strength_curve(panel: Dict[str, Any], n_games: int) -> Dict[str, Any]:
    """每回合末 Σ 的 p50 + 生存率 + 无条件 E[Σ]（同 ``infer_search_ab`` 口径）。"""
    end = (panel.get("strength") or {}).get("per_turn_end") or {}
    out: Dict[str, Any] = {}
    for t in range(1, 18):
        s = end.get(str(t)) or {}
        if not s.get("n"):
            out[str(t)] = {"n": 0}
            continue
        surv = int(s["n"]) / max(int(n_games), 1)
        out[str(t)] = {"n": int(s["n"]), "p50": s.get("p50"),
                       "mean": s.get("mean"), "survival": round(surv, 4),
                       "expected_sigma": round(surv * float(s.get("mean") or 0.0), 1)}
    return out


def _pooled_ci(d: np.ndarray, boot: int = 20000, seed: int = 20261101) -> Dict[str, Any]:
    return _mean_ci(d, boot=boot, seed=seed)


def _stratified_ci(groups: List[np.ndarray], boot: int = 20000,
                   seed: int = 20261102) -> Dict[str, Any]:
    """面板分层 bootstrap：每个面板内独立重采样（保持面板样本量），再合并求均值。"""
    gs = [np.asarray(g, dtype=np.float64) for g in groups if np.asarray(g).size]
    if not gs:
        return {"n": 0, "mean": None, "ci_low": None, "ci_high": None}
    rng = np.random.default_rng(int(seed))
    means = []
    for _ in range(int(boot)):
        parts = [g[rng.integers(0, g.size, size=g.size)] for g in gs]
        means.append(float(np.concatenate(parts).mean()))
    m = np.asarray(means)
    allv = np.concatenate(gs)
    return {"n": int(allv.size), "mean": float(allv.mean()),
            "ci_low": float(np.percentile(m, 2.5)),
            "ci_high": float(np.percentile(m, 97.5)),
            "n_panels": len(gs),
            "panel_means": [float(g.mean()) for g in gs]}


def compare(off: Dict[str, Any], on: Dict[str, Any], *, boot: int = 20000) -> Dict[str, Any]:
    po = off.get("panels") or []
    pn = on.get("panels") or []
    if not po or len(po) != len(pn):
        raise SystemExit(f"面板数不一致：off={len(po)} on={len(pn)}")
    same_ckpt = (off.get("checkpoint_sha256") == on.get("checkpoint_sha256"))
    co = off.get("config") or {}
    cn = on.get("config") or {}
    if co.get("seed_base") != cn.get("seed_base") or \
            co.get("games") != cn.get("games") or co.get("seats") != cn.get("seats"):
        raise SystemExit("两个负载的 seed_base/games/seats 不一致，无法配对")

    per_panel: List[Dict[str, Any]] = []
    d_groups: List[np.ndarray] = []
    top4_groups: List[np.ndarray] = []
    a_all: List[np.ndarray] = []
    b_all: List[np.ndarray] = []
    keys_ok = True
    for i, (qa, qb) in enumerate(zip(po, pn)):
        ra, ka = _panel_ranks(qa)
        rb, kb = _panel_ranks(qb)
        if ka != kb:
            keys_ok = False
            raise SystemExit(f"panel{i} 的 (seat, 局序) 键不一致")
        a = np.asarray(ra, dtype=np.float64)
        b = np.asarray(rb, dtype=np.float64)
        known = (a >= 1.0) & (b >= 1.0)
        d = (b - a)[known]
        t4 = ((b <= 4).astype(np.float64) - (a <= 4).astype(np.float64))[known]
        d_groups.append(d)
        top4_groups.append(t4)
        a_all.append(a)
        b_all.append(b)
        per_panel.append({
            "panel_idx": int(i),
            "seed_base": (qa.get("details") or {}).get("seed_base"),
            "games": int(a.size),
            "n_known": int(known.sum()),
            "mean_rank_off": float(a[known].mean()),
            "mean_rank_on": float(b[known].mean()),
            "delta": _pooled_ci(d, boot=boot, seed=20261101 + i),
            "top4_off": float((a[known] <= 4).mean()),
            "top4_on": float((b[known] <= 4).mean()),
            "win_off": int((a == 1).sum()), "win_on": int((b == 1).sum()),
            "model_seconds_off": qa.get("model_seconds"),
            "model_seconds_on": qb.get("model_seconds"),
            "search": {"off": _search_meta(qa), "on": _search_meta(qb)},
            "strength_off": _strength_curve(qa, a.size),
            "strength_on": _strength_curve(qb, b.size),
            "paired_strength": _paired_strength(qa, qb, turns=(12, 15), boot=boot),
        })

    a_cat = np.concatenate(a_all)
    b_cat = np.concatenate(b_all)
    known = (a_cat >= 1.0) & (b_cat >= 1.0)
    d_cat = (b_cat - a_cat)[known]
    t4_cat = ((b_cat <= 4).astype(np.float64) - (a_cat <= 4).astype(np.float64))[known]
    out: Dict[str, Any] = {
        "protocol": {
            "panels": int(len(po)),
            "games_per_panel": int(a_cat.size // len(po)),
            "games_total": int(a_cat.size),
            "paired_games": int(d_cat.size),
            "bootstrap": int(boot),
            "seed_base": co.get("seed_base"),
            "sealed_seed_base": co.get("sealed_seed_base"),
            "checkpoint": off.get("checkpoint"),
            "checkpoint_sha256": off.get("checkpoint_sha256"),
            "same_checkpoint": bool(same_ckpt),
            "off_search": _search_meta(po[0]),
            "on_search": _search_meta(pn[0]),
            "keys_aligned": bool(keys_ok),
        },
        "rank": {
            "off_mean": float(a_cat[known].mean()),
            "on_mean": float(b_cat[known].mean()),
            "delta": _pooled_ci(d_cat, boot=boot),
            "delta_stratified": _stratified_ci(d_groups, boot=boot),
            "delta_panel_means": [round(float(g.mean()), 6) for g in d_groups],
            "delta_median": float(np.median(d_cat)),
            "delta_sign_test_p": float(_sign_test_p(d_cat)),
        },
        "top4": {
            "off": float((a_cat[known] <= 4).mean()),
            "on": float((b_cat[known] <= 4).mean()),
            "delta": float(t4_cat.mean()),
            "delta_ci": _pooled_ci(t4_cat, boot=boot),
            "per_panel_delta": [round(float(g.mean()), 6) for g in top4_groups],
        },
        "win": {"off": int((a_cat == 1).sum()), "on": int((b_cat == 1).sum()),
                "n": int(known.sum())},
        "rank_hist": {str(k): {"off": int((a_cat == k).sum()),
                               "on": int((b_cat == k).sum())}
                      for k in range(1, 9)},
        "per_panel": per_panel,
    }
    # ── 强度：逐面板比值 → 报中位/两端，避免单面板噪声 ───────────────────
    def _ratio(key: str) -> Dict[str, Any]:
        vals = []
        for p in per_panel:
            so, sn = p["strength_off"], p["strength_on"]
            if int(so.get(key, {}).get("n") or 0) and int(sn.get(key, {}).get("n") or 0) \
                    and so[key].get("p50") and sn[key].get("p50"):
                vals.append(float(sn[key]["p50"]) / float(so[key]["p50"]))
        return {"per_panel": [round(v, 4) for v in vals],
                "median": round(float(np.median(vals)), 4) if vals else None}

    def _expected(key: str) -> Dict[str, Any]:
        vals = []
        for p in per_panel:
            eo = float(p["strength_off"].get(key, {}).get("expected_sigma") or 0.0)
            en = float(p["strength_on"].get(key, {}).get("expected_sigma") or 0.0)
            if eo > 0:
                vals.append(en / eo)
        return {"per_panel": [round(v, 4) for v in vals],
                "median": round(float(np.median(vals)), 4) if vals else None}

    def _survival(key: str) -> Dict[str, Any]:
        vals = []
        for p in per_panel:
            so = float(p["strength_off"].get(key, {}).get("survival") or 0.0)
            sn = float(p["strength_on"].get(key, {}).get("survival") or 0.0)
            vals.append((so, sn))
        return {"off": [round(x[0], 4) for x in vals],
                "on": [round(x[1], 4) for x in vals]}

    out["strength"] = {
        "conditional_p50_ratio": {f"t{t}": _ratio(str(t)) for t in (8, 10, 11, 12, 13, 15)},
        "expected_sigma_ratio": {f"t{t}": _expected(str(t)) for t in (9, 10, 11, 12)},
        "survival": {f"t{t}": _survival(str(t)) for t in (10, 11, 12)},
    }
    # 逐局配对强度（合并两个面板：按面板分别配对，再合并 diff）
    ps_parts: Dict[str, List[float]] = {}
    for p in per_panel:
        ps = (p.get("paired_strength") or {}).get("paired") or {}
        for k, v in ps.items():
            pd = (v or {}).get("paired_diff") or {}
            if pd.get("n"):
                ps_parts.setdefault(k, []).append(v)
    summary_ps: Dict[str, Any] = {}
    for k, vs in ps_parts.items():
        n = sum(int(v["paired_diff"]["n"]) for v in vs)
        summary_ps[k] = {
            "n_pairs": int(n),
            "off_p50": [v.get("off_p50") for v in vs],
            "on_p50": [v.get("on_p50") for v in vs],
            "p50_ratio_per_panel": [v.get("p50_ratio") for v in vs],
            "paired_diff_per_panel": [v["paired_diff"]["mean"] for v in vs],
        }
    out["strength_paired"] = summary_ps
    # ── 成本 ────────────────────────────────────────────────────────────
    on_s = [p["search"]["on"] for p in per_panel]
    off_s = [p["search"]["off"] for p in per_panel]
    out["cost"] = {
        "off_model_seconds_per_panel": [p["model_seconds_off"] for p in per_panel],
        "on_model_seconds_per_panel": [p["model_seconds_on"] for p in per_panel],
        "wall_ratio": round(sum(float(p["model_seconds_on"] or 0) for p in per_panel)
                            / max(sum(float(p["model_seconds_off"] or 0)
                                      for p in per_panel), 1e-9), 3),
        "on_search_calls_per_game": [s.get("search_calls_per_game") for s in on_s],
        "on_mean_ms_per_call": [s.get("mean_ms_per_call") for s in on_s],
        "on_search_ms_per_game": [s.get("search_ms_per_game") for s in on_s],
        "on_switch_rate": [s.get("switch_rate") for s in on_s],
        "off_search_calls": [s.get("search_calls") for s in off_s],
        "on_search_errors": sum(int(s.get("search_errors") or 0) for s in on_s),
        "on_search_timeouts": sum(int(s.get("search_timeouts") or 0) for s in on_s),
        "on_rollout_truncated": sum(int(s.get("rollout_truncated") or 0) for s in on_s),
    }
    # ── 判据（正式协议：两面板合并）──────────────────────────────────────
    dm = out["rank"]["delta"]["mean"]
    ci_hi = out["rank"]["delta"]["ci_high"]
    out["criteria"] = {
        "rank_delta_le_-0.10_and_ci_hi_lt_0.05": bool(
            dm is not None and ci_hi is not None and dm <= -0.10 and ci_hi < 0.05),
        "delta_mean": dm, "delta_ci_high": ci_hi,
        "both_panels_same_sign": bool(all(x < 0 for x in out["rank"]["delta_panel_means"])),
        "t12_conditional_p50_ratio_median": out["strength"]["conditional_p50_ratio"]["t12"]["median"],
        "t12_expected_sigma_ratio_median": out["strength"]["expected_sigma_ratio"]["t12"]["median"],
        "verdict": "",
    }
    v = out["criteria"]
    if v["rank_delta_le_-0.10_and_ci_hi_lt_0.05"]:
        v["verdict"] = ("名次达标" +
                        ("，两面板同向" if v["both_panels_same_sign"] else "，但两面板方向不一致"))
    else:
        v["verdict"] = ("名次未达标：Δ=%s，CI 上界=%s" % (dm, ci_hi))
    return out


def _sign_test_p(d: np.ndarray) -> float:
    """两臂配对符号检验（双侧正态近似；0 差不计入）。"""
    d = np.asarray(d, dtype=np.float64)
    pos = int((d > 0).sum())
    neg = int((d < 0).sum())
    n = pos + neg
    if n == 0:
        return 1.0
    z = abs(pos - neg) / np.sqrt(n)
    # 双侧 p（正态近似）
    return float(2.0 * (1.0 - 0.5 * (1.0 + _erf(z / np.sqrt(2.0)))))


def _erf(x: float) -> float:
    """Abramowitz-Stegun 7.1.26（|err| < 1.5e-7），避免依赖 scipy。"""
    t = 1.0 / (1.0 + 0.3275911 * abs(x))
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return float(np.sign(x) * y)


def main() -> int:
    ap = argparse.ArgumentParser(description="推理期搜索多封存面板正式 A/B")
    ap.add_argument("--off", required=True)
    ap.add_argument("--on", required=True)
    ap.add_argument("--bootstrap", type=int, default=20000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    off = json.load(open(args.off, encoding="utf-8"))
    on = json.load(open(args.on, encoding="utf-8"))
    rep = compare(off, on, boot=int(args.bootstrap))
    rep["inputs"] = {"off": args.off, "on": args.on,
                     "off_sha": off.get("checkpoint_sha256"),
                     "on_sha": on.get("checkpoint_sha256")}
    txt = json.dumps(rep, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(txt)
    r = rep["rank"]
    print(json.dumps({
        "protocol": rep["protocol"],
        "mean_rank": {"off": r["off_mean"], "on": r["on_mean"]},
        "delta": r["delta"], "delta_stratified": r["delta_stratified"],
        "delta_panel_means": r["delta_panel_means"],
        "top4": {"off": rep["top4"]["off"], "on": rep["top4"]["on"],
                 "delta": rep["top4"]["delta"], "ci": rep["top4"]["delta_ci"]},
        "win": rep["win"],
        "strength": rep["strength"],
        "cost": rep["cost"],
        "criteria": rep["criteria"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
