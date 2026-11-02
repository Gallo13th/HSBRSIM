"""「酒馆 buff × 动作额度」二维探针（复利形状的关键实验）。

矩阵：`tavern_buff_scale ∈ {1,3,5}` × `action_cap ∈ {40,80,120}`（9 格），其余固定
= 会复利的收入（`growth 0.15 + 2/载体 + gold_cap 0`），教师 = `CompoundPolicy`，
饰品开启；每格 24 局、同 seed（880000+i，便于跨格配对）。

每格报告：t15 Σ p50、**Σ/N**（N = t15 场上随从数）、r12_15、tavern_buff p50、
施法/局、金币花费率（spent/income）、形状（logΣ 对 turn 的斜率/曲率）。

判据（Lead 指定）：某格 `r12_15 ≥ 3` 且 `Σ/N ≥ 3,788`（真实 26,516/7）⇒
「buff × N × 动作」就是复利核心；若 9 格 r12 全 ≤1.5 ⇒ 还需要金色/放大器的触发数值放大。

用法：
    python scripts/buff_action_2d_probe.py --games-per-cell 24 --workers 12 \
        --json-out runs/sandbox_econ/buff_action_2d.json \
        --png runs/plots/buff_action_2d.png
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hsbg.az.train.economy_sandbox import EconomySandbox, SandboxConfig  # noqa: E402
from compound_script import CompoundPolicy  # noqa: E402

BUFFS = (1.0, 3.0, 5.0)
CAPS = (40, 80, 120)


def _cfg(buff: float, cap: int) -> SandboxConfig:
    return SandboxConfig(
        turns=15, gold_mode="growth", gold_per_turn=30, gold_growth_rate=0.15,
        gold_per_carrier=2, gold_cap=0, action_cap=int(cap),
        action_cap_per_gold=0, tavern_buff_scale=float(buff),
        num_players=8, trinkets=True, lobby_types=())


def _run_shard(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = payload["cfg"]
    games = int(payload["games"])
    seed0 = int(payload["seed0"])
    out: List[Dict[str, Any]] = []
    for gi in range(games):
        seed = seed0 + int(payload["offset"]) + gi
        env = EconomySandbox(cfg)
        obs = env.reset(seed)
        pol = CompoundPolicy(seed=seed)
        turns: Dict[int, Dict[str, Any]] = {}
        while not env.done:
            v = json.loads(env.g.view(0))
            a = int(pol.act(v, obs.mask))
            obs, _r, _d, info = env.step(a)
            met = info.get("turn_metrics")
            if met:
                turns[int(met["turn"])] = met
        ep = env.episode_summary()
        p = json.loads(env.g.player_json(0))
        st = p.get("stats") or {}
        s12 = int(ep.get("sigma_t12") or 0)
        s15 = int(ep.get("sigma_t15") or 0)
        n15 = int((turns.get(15) or {}).get("board_len") or 0)
        income = int(ep.get("gold_total_income") or 0)
        spent = int(st.get("gold_spent_total") or 0)
        out.append({
            "seed": seed, "sigma_t12": s12, "sigma_t15": s15,
            "n15": n15, "sigma_per_n": (s15 / n15 if n15 > 0 else 0.0),
            "r12_15": s15 / max(1, s12),
            "tavern_buff_t15": int((turns.get(15) or {}).get("tavern_buff") or 0),
            "spells_t15": int((turns.get(15) or {}).get("spells") or 0),
            "gold_total_income": income, "gold_spent_total": spent,
            "spend_rate": (spent / income if income > 0 else 0.0),
            "tier_t15": int((turns.get(15) or {}).get("tier") or 0),
            "growth_slope_all": float(ep.get("growth_slope_all") or 0.0),
            "growth_curv": float(ep.get("growth_curv") or 0.0),
            "growth_ratio_12_15": float(ep.get("growth_ratio_12_15") or 0.0),
        })
    return out


def _pct(vals: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(vals, dtype=np.float64), q)) if vals else 0.0


def _summarize(eps: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    def col(k: str) -> List[float]:
        return [float(e.get(k) or 0) for e in eps]

    return {
        "games": len(eps),
        "sigma_t15_p50": _pct(col("sigma_t15"), 50),
        "sigma_t15_p90": _pct(col("sigma_t15"), 90),
        "sigma_t15_max": max(col("sigma_t15"), default=0),
        "sigma_t12_p50": _pct(col("sigma_t12"), 50),
        "N15_p50": _pct(col("n15"), 50),
        "sigma_per_N_p50": _pct(col("sigma_per_n"), 50),
        "sigma_per_N_p90": _pct(col("sigma_per_n"), 90),
        "r12_15_p50": _pct(col("r12_15"), 50),
        "r12_15_p90": _pct(col("r12_15"), 90),
        "tavern_buff_t15_p50": _pct(col("tavern_buff_t15"), 50),
        "spells_t15_p50": _pct(col("spells_t15"), 50),
        "gold_income_p50": _pct(col("gold_total_income"), 50),
        "spend_rate_mean": float(statistics.mean(col("spend_rate"))) if eps else 0.0,
        "growth_slope_all_p50": _pct(col("growth_slope_all"), 50),
        "growth_curv_p50": _pct(col("growth_curv"), 50),
        "growth_ratio_12_15_p50": _pct(col("growth_ratio_12_15"), 50),
        "tier_t15_p50": _pct(col("tier_t15"), 50),
    }


def _plot(cells: Dict[str, Dict[str, Any]], png: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r12 = np.zeros((len(BUFFS), len(CAPS)))
    spn = np.zeros_like(r12)
    for i, b in enumerate(BUFFS):
        for j, c in enumerate(CAPS):
            cell = cells[f"buff{b:g}_cap{c}"]
            r12[i, j] = cell["r12_15_p50"]
            spn[i, j] = cell["sigma_per_N_p50"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, mat, title, fmt, vmax in (
            (axes[0], r12, "r12_15 p50 (>=3 = exponential)", "{:.2f}", 3.0),
            (axes[1], spn, "Sigma/N p50 (>=3788 = real)", "{:.0f}", 3788.0)):
        im = ax.imshow(mat, cmap="viridis", aspect="auto", vmin=0,
                       vmax=max(vmax, float(np.nanmax(mat))))
        ax.set_xticks(range(len(CAPS)))
        ax.set_xticklabels([f"cap={c}" for c in CAPS])
        ax.set_yticks(range(len(BUFFS)))
        ax.set_yticklabels([f"buff x{b:g}" for b in BUFFS])
        ax.set_title(title, fontsize=9)
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                ax.text(j, i, fmt.format(mat[i, j]), ha="center", va="center",
                        color="white", fontsize=9)
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle("Sandbox: tavern-buff x action-cap (CompoundPolicy, growth0.15+2/carrier, gold-cap 0)",
                 fontsize=9)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(png)) or ".", exist_ok=True)
    fig.savefig(png, dpi=140)
    print(f"WROTE {png}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tavern-buff × action-cap 2D probe")
    ap.add_argument("--games-per-cell", type=int, default=24)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "sandbox_econ",
                                                       "buff_action_2d.json"))
    ap.add_argument("--png", default=os.path.join(ROOT, "runs", "plots",
                                                  "buff_action_2d.png"))
    args = ap.parse_args(argv)
    import multiprocessing as mp

    games = int(args.games_per_cell)
    workers = max(1, int(args.workers))
    payloads: List[Dict[str, Any]] = []
    for buff in BUFFS:
        for cap in CAPS:
            # 每格切成若干分片；分片大小让总任务数 ≈ 2×workers
            n_shards = max(1, min(games, 2 * workers // (len(BUFFS) * len(CAPS)) + 1))
            per = max(1, games // n_shards)
            off = 0
            while off < games:
                take = min(per, games - off)
                payloads.append({"cfg": _cfg(buff, cap), "games": take,
                                 "seed0": int(args.seed0), "offset": off,
                                 "buff": buff, "cap": cap})
                off += take
    t0 = __import__("time").time()
    with mp.get_context("fork").Pool(workers) as pool:
        results = pool.map(_run_shard, payloads)
    eps_by_cell: Dict[str, List[Dict[str, Any]]] = {}
    for payload, eps in zip(payloads, results):
        key = f"buff{payload['buff']:g}_cap{payload['cap']}"
        eps_by_cell.setdefault(key, []).extend(eps)
    cells = {k: _summarize(v) for k, v in sorted(eps_by_cell.items())}
    out: Dict[str, Any] = {
        "matrix": {"tavern_buff_scale": list(BUFFS), "action_cap": list(CAPS)},
        "config": {"gold_mode": "growth", "gold_growth_rate": 0.15,
                   "gold_per_carrier": 2, "gold_per_turn": 30, "gold_cap": 0,
                   "action_cap_per_gold": 0, "trinkets": True,
                   "teacher": "CompoundPolicy", "games_per_cell": games,
                   "seed0": int(args.seed0),
                   "real_sigma_t15_p50": 26516, "real_sigma_per_N": 3788.0},
        "criteria": {"r12_15_ge_3": [], "sigma_per_N_ge_3788": [],
                     "pass": []},
        "cells": cells,
        "elapsed_s": round(__import__("time").time() - t0, 1),
    }
    for k, c in cells.items():
        if c["r12_15_p50"] >= 3.0:
            out["criteria"]["r12_15_ge_3"].append(k)
        if c["sigma_per_N_p50"] >= 3788.0:
            out["criteria"]["sigma_per_N_ge_3788"].append(k)
        if c["r12_15_p50"] >= 3.0 and c["sigma_per_N_p50"] >= 3788.0:
            out["criteria"]["pass"].append(k)
    out["verdict"] = ("buff x N x actions is the compounding core"
                      if out["criteria"]["pass"]
                      else ("all r12_15 <= 1.5 -> need trigger-value amplification (golden/amp)"
                            if all(c["r12_15_p50"] <= 1.5 for c in cells.values())
                            else "partial: r12_15 between 1.5 and 3"))
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: {kk: vv for kk, vv in v.items()
                          if kk in ("sigma_t15_p50", "N15_p50", "sigma_per_N_p50",
                                    "r12_15_p50", "tavern_buff_t15_p50",
                                    "spells_t15_p50", "spend_rate_mean",
                                    "growth_slope_all_p50", "growth_curv_p50")}
                      for k, v in cells.items()}, ensure_ascii=False, indent=1))
    print("VERDICT:", out["verdict"], "| pass:", out["criteria"]["pass"],
          "| elapsed_s:", out["elapsed_s"])
    _plot(cells, args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
