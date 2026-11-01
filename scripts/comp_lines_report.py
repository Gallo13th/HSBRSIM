#!/usr/bin/env python3
"""复利阵容 / 1M 小模型：把训练历史 + 沙盒上限 + 真实基线画成 PNG 并汇总 JSON。

产物（默认 ``runs/plots/``）

| 文件 | 内容 |
|---|---|
| ``comp_lines_growth.png`` | **成长曲线对比**：真实 10k+ p50、脚本上限、1M 小模型（各评测点）、随机基线（log Σ vs turn） |
| ``comp_lines_training.png`` | 训练曲线：t12/t15 Σ、``r12_15``、``exp_segment_rate``、核心牌/饰品命中率 vs 决策数 |
| ``comp_lines_comps.png`` | Firestone 27 套阵容的**真实终局面板** Σ（p50/max）与 top-10 MMR 名次 |
| ``comp_lines_reward.png`` | 奖励口径示意：线性 vs 复利在 ``exp_growth`` 下的累计奖励 |

用法::

    python scripts/comp_lines_report.py --runs runs/comp_lines \
        --out-dir runs/plots --json-out runs/comp_lines/summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 真实 10k+ MMR 库的战团 Σ p50（``runs/ceiling_probe/REPORT.md`` §1，1961 局）
REAL_P50 = {9: 547, 10: 1132, 11: 2211, 12: 4458, 13: 9446, 14: 20889, 15: 26516}


def _load(p: str) -> Any:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def read_history(d: str) -> Dict[str, List[Dict[str, Any]]]:
    """一次训练目录的 history.jsonl → {event: [records]}。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    p = os.path.join(d, "history.jsonl")
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.setdefault(str(r.get("event") or "?"), []).append(r)
    return out


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


# ── 图 1：成长曲线 ──────────────────────────────────────────────────────────


def plot_growth(arms: Dict[str, Dict[str, Any]], ceiling: Optional[Dict[str, Any]],
                out: str) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(9, 5.6), dpi=130)
    turns = sorted(REAL_P50)
    ax.plot(turns, [REAL_P50[t] for t in turns], "o-", lw=2.4, color="#111111",
            label="real 10k+ p50 (26,516 @ t15)")
    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]
    for i, (name, info) in enumerate(arms.items()):
        ev = info.get("evals") or []
        if not ev:
            continue
        pts: Dict[int, List[float]] = {}
        for r in ev:
            if str(r.get("mode")) != "sample":
                continue
            for t, key in ((12, "sigma_t12_p50"), (15, "sigma_t15_p50")):
                pts.setdefault(t, []).append(float(r.get(key) or 0))
        xs = sorted(pts)
        jit = (i - 0.5) * 0.12          # 两条臂的 t12/t15 点错开，避免完全重叠
        ax.plot([x + jit for x in xs], [max(pts[t]) for t in xs], "s--", lw=1.6, ms=6,
                color=colors[i % len(colors)],
                label=f"{name} (best t15={max(pts[15]) if 15 in pts else 0:.0f})")
    if ceiling:
        best = ceiling.get("best") or {}
        if best:
            ax.plot([12, 15], [float(best.get("sigma_t12_p50") or 0),
                               float(best.get("sigma_t15_p50") or 0)],
                    "^-", color="#ff7f0e", lw=1.6, ms=8,
                    label=f"scripted ceiling ({best.get('policy')}, "
                          f"cap={best.get('action_cap')})")
    ax.axhline(10000.0, color="#d62728", ls=":", lw=1.2)
    ax.set_yscale("log")
    ax.set_xlabel("turn")
    ax.set_ylabel("warband Σ (atk+hp), log scale")
    ax.set_title("Warband growth: real top-MMR vs sandbox scripted vs 1M tiny model "
                 "(dotted = 10k criterion)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# ── 图 2：训练曲线 ──────────────────────────────────────────────────────────


def plot_training(arms: Dict[str, Dict[str, Any]], out: str) -> None:
    plt = _plt()
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.4), dpi=130)
    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]
    for i, (name, info) in enumerate(arms.items()):
        ev = [r for r in (info.get("evals") or []) if str(r.get("mode")) == "sample"]
        if not ev:
            continue
        c = colors[i % len(colors)]
        x = [int(r.get("decisions") or 0) / 1e6 for r in ev]
        axes[0].plot(x, [float(r.get("sigma_t12_p50") or 0) for r in ev], "o-", color=c,
                     label=f"{name} t12")
        axes[0].plot(x, [float(r.get("sigma_t15_p50") or 0) for r in ev], "s--", color=c,
                     label=f"{name} t15")
        axes[1].plot(x, [float(r.get("growth_ratio_12_15_p50") or 0) for r in ev], "o-",
                     color=c, label=f"{name} Σ15/Σ12")
        axes[2].plot(x, [float(r.get("exp_segment_rate") or 0) for r in ev], "o-",
                     color=c, label=f"{name} exp-segment rate")
        if any("core_rate" in r for r in ev):
            axes[2].plot(x, [float(r.get("core_rate") or 0) for r in ev], "s:", color=c,
                         label=f"{name} core hit")
        if any("trinket_hit_rate" in r for r in ev):
            axes[2].plot(x, [float(r.get("trinket_hit_rate") or 0) for r in ev], "^:", color=c,
                         label=f"{name} trinket hit")
    axes[0].set_ylabel("Σ p50 (eval, sample T=1)")
    axes[0].set_title("t12 / t15 Σ vs decisions")
    axes[1].axhline(3.0, color="k", ls=":", lw=1)
    axes[1].set_ylabel("Σ15 / Σ12")
    axes[1].set_title("exponential segment (target ≥ 3×)")
    axes[2].set_ylabel("rate")
    axes[2].set_title("core / trinket hit rate & exp-segment rate")
    for ax in axes:
        ax.set_xlabel("decisions (M)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# ── 图 3：阵容真实面板 ─────────────────────────────────────────────────────


def plot_comps(comps: Dict[str, Any], out: str) -> None:
    plt = _plt()
    rows = []
    for c in comps.get("comps") or ():
        eb = c.get("example_boards") or {}
        if not eb.get("n"):
            continue
        rows.append((c.get("name") or c.get("archetype"), int(eb.get("sigma_p50") or 0),
                     int(eb.get("sigma_max") or 0)))
    if not rows:
        return
    rows.sort(key=lambda r: r[1])
    names = [r[0] for r in rows]
    p50 = [r[1] for r in rows]
    mx = [r[2] for r in rows]
    fig, ax = plt.subplots(figsize=(9.5, max(5.0, 0.28 * len(rows))), dpi=130)
    y = list(range(len(rows)))
    ax.barh(y, mx, color="#d9d9d9", label="example board Σ max")
    ax.barh(y, p50, color="#1f77b4", label="example board Σ p50")
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=7)
    ax.set_xscale("log")
    ax.set_xlabel("final board Σ (log scale)")
    ax.set_title("Firestone comps: real top-MMR example boards")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# ── 图 4：奖励口径 ─────────────────────────────────────────────────────────


def plot_reward(out: str) -> None:
    """线性铺场 vs 复利在 ``exp_growth`` 下的累计奖励（同一条公式，不依赖训练）。"""
    plt = _plt()
    base, w2 = 0.35, 0.2
    lin = [1000 + 1000 * (t - 1) for t in range(1, 16)]
    exp = [int(1000 * (1.55 ** (t - 1))) for t in range(1, 16)]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), dpi=130)
    for name, s, c in (("linear (+1000/turn)", lin, "#1f77b4"),
                       ("compounding (x1.55/turn)", exp, "#d62728")):
        ax[0].plot(range(1, 16), s, "o-", color=c, label=name, ms=4)
        prev_L, cum, r = 0.0, 0.0, []
        prev_sig = 0
        for t, v in enumerate(s, start=1):
            L = math.log1p(v) / math.log1p(30000.0)
            rew = 1.0 * (L - prev_L)
            if t >= 10:
                rew += w2 * max(0.0, math.log1p(v) - math.log1p(prev_sig) - base)
            prev_L, prev_sig = L, v
            cum += rew
            r.append(cum)
        ax[1].plot(range(1, 16), r, "o-", color=c, label=f"{name}  ΣR={cum:.2f}", ms=4)
    ax[0].set_yscale("log")
    ax[0].set_title("warband Σ")
    ax[0].set_xlabel("turn")
    ax[1].set_title("cumulative exp_growth reward (w1=1, w2=0.2, base=0.35)")
    ax[1].set_xlabel("turn")
    for a in ax:
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="复利阵容/小模型实验的图 + 汇总")
    ap.add_argument("--runs", default="runs/comp_lines")
    ap.add_argument("--out-dir", default="runs/plots")
    ap.add_argument("--json-out", default="runs/comp_lines/summary.json")
    ap.add_argument("--comps", default="data/scaling/comps_top.json")
    ap.add_argument("--arms", default="A,B,C",
                    help="训练臂目录名列表（runs/<runs>/tiny_<arm>*）")
    args = ap.parse_args(argv)

    runs = args.runs if os.path.isabs(args.runs) else os.path.join(ROOT, args.runs)
    outd = args.out_dir if os.path.isabs(args.out_dir) else os.path.join(ROOT, args.out_dir)
    os.makedirs(outd, exist_ok=True)

    arms: Dict[str, Dict[str, Any]] = {}
    for letter in [x.strip() for x in args.arms.split(",") if x.strip()]:
        cand = [d for d in sorted(os.listdir(runs)) if d.startswith(f"tiny_{letter}")]
        if not cand:
            continue
        d = os.path.join(runs, cand[-1])
        h = read_history(d)
        arms[f"tiny_{letter}"] = {
            "dir": os.path.relpath(d, ROOT),
            "evals": h.get("eval") or [],
            "updates": h.get("update") or [],
            "summary": (_load(os.path.join(d, "summary.json"))
                        if os.path.exists(os.path.join(d, "summary.json")) else {}),
        }

    ceiling = None
    cp = os.path.join(runs, "ceiling.json")
    if os.path.exists(cp):
        ceiling = _load(cp)
    cpath = os.path.join(ROOT, args.comps) if not os.path.isabs(args.comps) else args.comps
    comps = _load(cpath) if os.path.exists(cpath) else {}

    p1 = os.path.join(outd, "comp_lines_growth.png")
    plot_growth(arms, ceiling, p1)
    p2 = os.path.join(outd, "comp_lines_training.png")
    plot_training(arms, p2)
    p3 = os.path.join(outd, "comp_lines_comps.png")
    plot_comps(comps, p3)
    p4 = os.path.join(outd, "comp_lines_reward.png")
    plot_reward(p4)

    # ── 汇总（判据）──────────────────────────────────────────────────────
    def _last_eval(arm: Dict[str, Any]) -> Dict[str, Any]:
        ev = [r for r in (arm.get("evals") or []) if str(r.get("mode")) == "sample"]
        return ev[-1] if ev else {}

    verdict: Dict[str, Any] = {}
    for name, arm in arms.items():
        e = _last_eval(arm)
        t12 = float(e.get("sigma_t12_p50") or 0)
        t15 = float(e.get("sigma_t15_p50") or 0)
        ratio = float(e.get("growth_ratio_12_15_p50") or 0)
        verdict[name] = {
            "decisions": e.get("decisions"),
            "sigma_t12_p50": t12, "sigma_t15_p50": t15,
            "ratio_12_15": ratio,
            "slope_late": float(e.get("growth_slope_late_p50") or 0),
            "curv": float(e.get("growth_curv_p50") or 0),
            "exp_segment_rate": float(e.get("exp_segment_rate") or 0),
            "core_rate": float(e.get("core_rate") or 0),
            "trinket_hit_rate": float(e.get("trinket_hit_rate") or 0),
            "criterion_t15_ge_10000": bool(t15 >= 10000),
            "criterion_ratio_ge_3": bool(ratio >= 3.0),
            "criterion_core_or_trinket_ge_0.6": bool(
                max(float(e.get("core_rate") or 0),
                    float(e.get("trinket_hit_rate") or 0)) >= 0.6),
        }
    doc = {
        "meta": {"generated_by": "scripts/comp_lines_report.py",
                 "real_p50": REAL_P50,
                 "criterion": {"sigma_t15_p50": 10000, "ratio_12_15": 3.0,
                               "core_or_trinket_hit": 0.6}},
        "arms": {k: {"dir": v["dir"], "evals": len(v["evals"])} for k, v in arms.items()},
        "verdict": verdict,
        "ceiling_best": (ceiling or {}).get("best"),
        "comps_stats": (comps or {}).get("stats", {}),
        "plots": [os.path.relpath(p, ROOT) for p in (p1, p2, p3, p4)],
    }
    jo = args.json_out if os.path.isabs(args.json_out) else os.path.join(ROOT, args.json_out)
    os.makedirs(os.path.dirname(jo), exist_ok=True)
    with open(jo, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    for p in (p1, p2, p3, p4):
        print(f"[plot] {os.path.relpath(p, ROOT)}")
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    print(f"[report] → {os.path.relpath(jo, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
