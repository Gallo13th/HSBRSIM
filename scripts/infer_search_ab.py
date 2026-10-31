#!/usr/bin/env python3
"""推理期搜索 A/B：同一 checkpoint / 同一 seed 面板，``--infer-search 0`` vs ``1``。

配对口径
--------
两个面板 JSON 都由 ``scripts/human_panel_eval.py --games 256 --smoke --seed-base S``
产生：8 seat × 32 局，seat ``s`` 的种子是 ``S + s*32 .. S + s*32 + 31``。
同 seed/seat 的两局是**同一局**（同对手注入、同引擎 seed）⇒ 逐局配对差分：

- 主统计：``Δrank = rank(search) − rank(off)`` 的均值 + 95% bootstrap CI
  （对局重采样；负值 = 名次变好）；
- top4 / 冠军率：配对差值（同一批局的比例差）；
- 强度：每回合末盘面 Σ（``strength.per_turn_end[t].p50``）的比值，重点 t12/t15；
- 成本：``search_calls / mean_ms_per_call / search_ms_per_game`` 与总墙钟。

判据（任务口径）
----------------
``Δhuman ≤ −0.10``（CI 上界 < +0.05）**且** t12 强度比 ≥ +10% ⇒ 值得作为部署默认；
若只有强度比涨而名次不动 ⇒ 报「推理搜索对名次无收益」。

用法::

    python scripts/infer_search_ab.py \
        --off runs/infer_search_ab/human_base0.json \
        --on  runs/infer_search_ab/human_t1.json \
        --out runs/infer_search_ab/ab_t1.json
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


def _ranks(panel: Dict[str, Any]) -> Tuple[List[int], List[Tuple[int, int]]]:
    """按 (seat, 局序) 展平 rank_sequence，并返回配对键。"""
    per = (panel.get("details") or {}).get("per_seat") or {}
    ranks: List[int] = []
    keys: List[Tuple[int, int]] = []
    for name in sorted(per, key=lambda x: int(str(x).split("_")[-1])):
        seat = int(str(name).split("_")[-1])
        seq = ((per[name].get("model") or {}).get("rank_sequence") or [])
        for i, r in enumerate(seq):
            ranks.append(int(r))
            keys.append((seat, int(i)))
    return ranks, keys


def _mean_ci(x: np.ndarray, boot: int = 20000, seed: int = 20261101,
             alpha: float = 0.05) -> Dict[str, Any]:
    x = np.asarray(x, dtype=np.float64)
    n = int(x.size)
    if n == 0:
        return {"n": 0, "mean": None, "ci_low": None, "ci_high": None}
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, n, size=(int(boot), n))
    means = x[idx].mean(axis=1)
    return {"n": n, "mean": float(x.mean()),
            "ci_low": float(np.percentile(means, 100 * alpha / 2)),
            "ci_high": float(np.percentile(means, 100 * (1 - alpha / 2))),
            "se": float(x.std(ddof=1) / np.sqrt(n)) if n > 1 else None,
            "frac_improved": float((x < 0).mean()), "frac_worse": float((x > 0).mean())}


def _strength(panel: Dict[str, Any], t: int) -> Dict[str, Any]:
    st = ((panel.get("strength") or {}).get("strength") or {}).get(str(int(t))) or {}
    return {"n": st.get("n"), "sigma_start_p50": st.get("sigma_start_p50"),
            "sigma_end_p50": st.get("sigma_end_p50"),
            "sigma_end_mean": st.get("sigma_end_mean")}


def _rows(panel: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(((panel.get("strength") or {}).get("rows")) or [])


def _paired_strength(off: Dict[str, Any], on: Dict[str, Any],
                     turns=(12, 15), boot: int = 20000) -> Dict[str, Any]:
    """逐局配对强度：同一 (seat, 局序) 的 Σ(turn) 差与比值。

    - ``sigma_end`` 取该回合最后一个 learner 决策时的盘面 Σ；
    - 只在**两臂都到达该回合**的局上配对（否则无法比较），同时报 n；
    - ``last_turn``：每局最后一个决策时的 Σ（不受「活到 t12」条件限制）。
    """
    a = _rows(off)
    b = _rows(on)
    out: Dict[str, Any] = {"n_rows_off": len(a), "n_rows_on": len(b)}
    if len(a) != len(b):
        out["error"] = "逐局行数不一致，无法配对"
        return out
    key = [f"t{int(t)}" for t in turns] + ["last_turn"]
    acc: Dict[str, Dict[str, List[float]]] = {k: {"off": [], "on": [], "diff": [],
                                                  "ratio": []} for k in key}
    for ra, rb in zip(a, b):
        if ra["seat"] != rb["seat"] or ra["seed"] != rb["seed"]:
            return {"error": "逐局 (seat, seed) 不一致"}
        ea, eb = ra.get("sigma_end_by_turn") or {}, rb.get("sigma_end_by_turn") or {}
        for t in turns:
            va, vb = ea.get(str(int(t))), eb.get(str(int(t)))
            if va is None or vb is None:
                continue
            acc[f"t{int(t)}"]["off"].append(float(va))
            acc[f"t{int(t)}"]["on"].append(float(vb))
            acc[f"t{int(t)}"]["diff"].append(float(vb) - float(va))
            if float(va) > 0:
                acc[f"t{int(t)}"]["ratio"].append(float(vb) / float(va))
        # 局末（最后一个决策时）
        if ea and eb:
            mta = max(int(k) for k in ea)
            mtb = max(int(k) for k in eb)
            va, vb = float(ea[str(mta)]), float(eb[str(mtb)])
            acc["last_turn"]["off"].append(va)
            acc["last_turn"]["on"].append(vb)
            acc["last_turn"]["diff"].append(vb - va)
            if va > 0:
                acc["last_turn"]["ratio"].append(vb / va)
    res: Dict[str, Any] = {}
    for k, v in acc.items():
        d = np.asarray(v["diff"], dtype=np.float64)
        r = np.asarray(v["ratio"], dtype=np.float64)
        res[k] = {
            "n_pairs": int(d.size),
            "off_p50": (round(float(np.percentile(v["off"], 50)), 1)
                        if v["off"] else None),
            "on_p50": (round(float(np.percentile(v["on"], 50)), 1)
                       if v["on"] else None),
            "p50_ratio": (round(float(np.percentile(v["on"], 50))
                                / float(np.percentile(v["off"], 50)), 4)
                          if v["off"] and float(np.percentile(v["off"], 50)) > 0
                          else None),
            "paired_diff": _mean_ci(d, boot=boot) if d.size else {"n": 0},
            "paired_ratio_mean": (round(float(r.mean()), 4) if r.size else None),
            "paired_ratio_p50": (round(float(np.percentile(r, 50)), 4) if r.size else None),
        }
    out["paired"] = res
    return out


def _cost(panel: Dict[str, Any]) -> Dict[str, Any]:
    s = panel.get("search") or {}
    games = int((s.get("per_seat") or [{}])[0].get("games") or 0) or None
    return {"search_enabled": s.get("enabled"), "turns": s.get("turns"),
            "when": s.get("when"), "action": s.get("action"),
            "search_calls": s.get("search_calls"),
            "mean_ms_per_call": s.get("mean_ms_per_call"),
            "search_ms_per_game": s.get("search_ms_per_game"),
            "search_calls_per_game": s.get("search_calls_per_game"),
            "switch_rate": s.get("switch_rate"),
            "leaf_steps_per_call": s.get("leaf_steps_per_call"),
            "search_errors": s.get("search_errors"),
            "rollout_truncated": s.get("rollout_truncated"),
            "model_seconds": panel.get("model_seconds"),
            "model_decisions": panel.get("model_decisions"),
            "model_decisions_per_game": panel.get("model_decisions_per_game")}


def compare(off: Dict[str, Any], on: Dict[str, Any], *, boot: int = 20000) -> Dict[str, Any]:
    p_off = (off.get("panels") or [{}])[0]
    p_on = (on.get("panels") or [{}])[0]
    r_off, k_off = _ranks(p_off)
    r_on, k_on = _ranks(p_on)
    if k_off != k_on:
        raise SystemExit("两个面板的 (seat, 局序) 键不一致，无法配对")
    a = np.asarray(r_off, dtype=np.float64)
    b = np.asarray(r_on, dtype=np.float64)
    known = (a >= 1.0) & (b >= 1.0)
    d_all = b - a
    d = d_all[known]
    out: Dict[str, Any] = {
        "protocol": {"games": int(a.size), "paired_games": int(d.size),
                     "bootstrap": int(boot), "seed_base": off.get("config", {}).get("seed_base")},
        "rank": {
            "off_mean": float(a[known].mean()) if known.any() else None,
            "on_mean": float(b[known].mean()) if known.any() else None,
            "delta": _mean_ci(d, boot=boot),
            "delta_median": float(np.median(d)) if d.size else None,
        },
        "top4": {
            "off": float((a[known] <= 4).mean()) if known.any() else None,
            "on": float((b[known] <= 4).mean()) if known.any() else None,
            "delta": (float((b[known] <= 4).mean() - (a[known] <= 4).mean())
                      if known.any() else None),
            "delta_ci": _mean_ci(((b <= 4).astype(float) - (a <= 4).astype(float))[known],
                                 boot=boot) if known.any() else None,
        },
        "win": {
            "off": float((a[known] == 1).mean()) if known.any() else None,
            "on": float((b[known] == 1).mean()) if known.any() else None,
            "count_off": int((a == 1).sum()), "count_on": int((b == 1).sum()),
        },
        "rank_hist": {str(k): {"off": int((a == k).sum()), "on": int((b == k).sum())}
                      for k in range(1, 9)},
        "strength": {}, "cost": {"off": _cost(p_off), "on": _cost(p_on)},
    }
    for t in (10, 12, 15):
        s_off = _strength(p_off, t)
        s_on = _strength(p_on, t)
        ratio = None
        if s_off.get("sigma_end_p50") and s_on.get("sigma_end_p50"):
            ratio = float(s_on["sigma_end_p50"]) / float(s_off["sigma_end_p50"])
        ratio_s = None
        if s_off.get("sigma_start_p50") and s_on.get("sigma_start_p50"):
            ratio_s = float(s_on["sigma_start_p50"]) / float(s_off["sigma_start_p50"])
        out["strength"][f"t{t}"] = {"off": s_off, "on": s_on,
                                    "ratio_end_p50": ratio,
                                    "ratio_start_p50": ratio_s,
                                    "delta_ratio": (ratio - 1.0) if ratio else None}
    # 每回合末 Σ：p50 曲线 + 「活到该回合」的生存率 + 全 256 局无条件期望
    # E[Σ_t] = P(alive at t) × E[Σ_t | alive]（死亡局记 0）——这一项才与名次可直接对应，
    # 因为 human 面板上 learner 大多活不到 t12，条件 p50 有严重生存者偏差。
    n_games = int(a.size) if a.size else 1
    curve: Dict[str, Any] = {}
    for t in range(1, 18):
        a_s = (((p_off.get("strength") or {}).get("per_turn_end") or {})
               .get(str(t)) or {})
        b_s = (((p_on.get("strength") or {}).get("per_turn_end") or {})
               .get(str(t)) or {})
        ca: Dict[str, Any] = {"off_p50": a_s.get("p50"), "on_p50": b_s.get("p50"),
                              "n_off": a_s.get("n"), "n_on": b_s.get("n")}
        if a_s.get("n") and b_s.get("n"):
            ca["off_survival"] = round(int(a_s["n"]) / n_games, 4)
            ca["on_survival"] = round(int(b_s["n"]) / n_games, 4)
            ca["survival_ratio"] = round(ca["on_survival"] / ca["off_survival"], 4)
            e_off = ca["off_survival"] * float(a_s.get("mean") or 0.0)
            e_on = ca["on_survival"] * float(b_s.get("mean") or 0.0)
            ca["off_expected_sigma"] = round(e_off, 1)
            ca["on_expected_sigma"] = round(e_on, 1)
            ca["expected_ratio"] = (round(e_on / e_off, 4) if e_off > 0 else None)
        curve[str(t)] = ca
    out["strength_curve"] = curve
    out["strength_paired"] = _paired_strength(p_off, p_on, turns=(12, 15), boot=boot)
    # ── 判据 ────────────────────────────────────────────────────────────
    dm = out["rank"]["delta"]["mean"]
    ci_hi = out["rank"]["delta"]["ci_high"]
    t12 = out["strength"]["t12"]["ratio_end_p50"]
    t15 = out["strength"]["t15"]["ratio_end_p50"]
    c12 = curve.get("12") or {}
    crit_rank = bool(dm is not None and ci_hi is not None
                     and dm <= -0.10 and ci_hi < 0.05)
    crit_strength = bool(t12 is not None and t12 >= 1.10)
    verdict = ("值得作为部署默认（名次达标 + t12 强度达标）" if (crit_rank and crit_strength)
               else ("只有强度比涨、名次无收益" if (crit_strength and not crit_rank)
                     else ("名次达标，t12 条件强度比不达标（注意生存者偏差："
                           "报告无条件强度曲线 t6–t11 与 survival_ratio）"
                           if crit_rank else "两者都不达标")))
    out["criteria"] = {
        "rank_delta_le_-0.10_and_ci_hi_lt_0.05": crit_rank,
        "t12_ratio_ge_1.10": crit_strength,
        "t12_conditional_p50_ratio": t12,
        "t12_survival_ratio": c12.get("survival_ratio"),
        "t12_expected_sigma_ratio": c12.get("expected_ratio"),
        "t11_conditional_p50_ratio": (curve.get("11") or {}).get("off_p50")
        and round(float((curve.get("11") or {}).get("on_p50") or 0)
                  / float((curve.get("11") or {}).get("off_p50") or 1), 4),
        "t15_ratio": t15, "verdict": verdict}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="推理期搜索 A/B（同 checkpoint 同 seed 面板配对）")
    ap.add_argument("--off", required=True, help="--infer-search 0 的面板 JSON")
    ap.add_argument("--on", required=True, help="--infer-search 1 的面板 JSON")
    ap.add_argument("--bootstrap", type=int, default=20000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    off = json.load(open(args.off, encoding="utf-8"))
    on = json.load(open(args.on, encoding="utf-8"))
    rep = compare(off, on, boot=int(args.bootstrap))
    rep["inputs"] = {"off": args.off, "on": args.on,
                     "off_sha": off.get("checkpoint_sha256"),
                     "on_sha": on.get("checkpoint_sha256"),
                     "same_checkpoint": (off.get("checkpoint_sha256")
                                         == on.get("checkpoint_sha256"))}
    txt = json.dumps(rep, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(txt)
    d = rep["rank"]["delta"]
    print(json.dumps({
        "paired_games": rep["protocol"]["paired_games"],
        "mean_rank": {"off": rep["rank"]["off_mean"], "on": rep["rank"]["on_mean"]},
        "delta": d,
        "top4": rep["top4"],
        "win": rep["win"],
        "t12": rep["strength"]["t12"],
        "t15": rep["strength"]["t15"],
        "strength_paired": (rep.get("strength_paired") or {}).get("paired"),
        "cost": rep["cost"],
        "criteria": rep["criteria"],
        "same_checkpoint": rep["inputs"]["same_checkpoint"],
    }, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
