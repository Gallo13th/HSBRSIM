#!/usr/bin/env python3
"""绘制 BC / C0 / PPO / 数据预算曲线（当前实验快照）。

输入默认是本次会话的路径；不存在则跳过对应面板。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _bc_points(paths: List[str]) -> List[Dict[str, Any]]:
    out = []
    for p in paths:
        if not os.path.isfile(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        ep = d.get("epochs") or []
        if not ep:
            continue
        out.append({"path": p, "samples": int(d.get("samples") or d.get("model_states") or 0),
                    "top1": float(ep[-1].get("top1", 0.0)),
                    "loss": float(ep[-1].get("loss", 0.0))})
    return sorted(out, key=lambda x: x["samples"])


def _ppo_steps(path: str) -> List[Dict[str, float]]:
    out = []
    if not os.path.isfile(path):
        return out
    pat = re.compile(r"\[ppo\] step (\d+) .*?policy=([-\d.]+) value=([-\d.]+) kl=([-\d.]+)")
    for line in open(path, encoding="utf-8", errors="ignore"):
        m = pat.search(line)
        if m:
            out.append({"step": int(m.group(1)), "policy": float(m.group(2)),
                        "value": float(m.group(3)), "kl": float(m.group(4))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/plots/training_curves.png")
    args = ap.parse_args()
    bc_paths = ["/tmp/entity_bc/report.json", "/tmp/entity_bc100k/report.json",
                "/tmp/entity_bc500k/report.json"]
    c0_paths = ["/tmp/c0_bc_smoke.json", "/tmp/c0_bc100k_smoke.json",
                "/tmp/c0_bc500k_smoke.json", "/tmp/c0_bcppo_smoke.json",
                "/tmp/c0_dagger_smoke.json", "/tmp/c0_bcppo2_smoke.json",
                "/tmp/c0_best_512.json"]
    logs = [("sims4 50k", "/tmp/e50ks4.log"),
            ("BC+PPO", "/tmp/bcppo.log"),
            ("seed2", "runs/az_entity_3seed/seed2.log")]
    bc = _bc_points(bc_paths)
    c0 = []
    for p in c0_paths:
        if not os.path.isfile(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        r = ((d.get("panels") or [{}])[0] if d.get("panels") else d.get("panel0") or {})
        if r.get("model_mean_rank") is None:
            continue
        c0.append({"path": p, "n": r.get("n"), "mean": r["model_mean_rank"],
                   "bot": r.get("bot_mean_rank"), "top4": r.get("model_top4"),
                   "lo": r.get("ci_low"), "hi": r.get("ci_high")})

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    ax = axes[0, 0]
    if bc:
        x = [b["samples"] for b in bc]
        y = [b["top1"] for b in bc]
        ax.plot(x, y, "o-", color="#1f77b4")
        for b in bc:
            ax.annotate(f"{b['samples']//1000}k", (b["samples"], b["top1"]),
                        textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
        ax.set_xscale("log")
        ax.set_xlabel("BC samples")
        ax.set_ylabel("top1 vs bot action")
        ax.set_title("BC cold start: samples vs top1")
        ax.grid(alpha=.3)

    ax = axes[0, 1]
    if c0:
        labels = [os.path.basename(c["path"]).replace("c0_", "").replace("_smoke.json", "") for c in c0]
        ys = [c["mean"] for c in c0]
        xs = np.arange(len(c0))
        ax.scatter(xs, ys, color="#d62728", zorder=3)
        for x, c in zip(xs, c0):
            ax.annotate(f"n={c.get('n')}", (x, c["mean"]), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=7)
        bot = np.mean([c["bot"] for c in c0 if c.get("bot")])
        ax.axhline(bot, ls="--", color="gray", label=f"bot≈{bot:.2f}")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        ax.invert_yaxis()
        ax.set_ylabel("mean rank (lower is better)")
        ax.set_title("C0 eval: mean rank (paired CI in docs)")
        ax.legend(fontsize=8)
        ax.grid(alpha=.3)

    ax = axes[1, 0]
    for name, path in logs:
        st = _ppo_steps(path)
        if st:
            ax.plot([s["step"] for s in st], [s["kl"] for s in st], label=name)
    ax.set_xlabel("PPO minibatch step")
    ax.set_ylabel("approx KL")
    ax.set_title("PPO stability (per-step KL)")
    ax.legend(fontsize=8)
    ax.grid(alpha=.3)

    ax = axes[1, 1]
    dec = np.array([1e5, 2.5e5, 5e5, 1e6, 5e6, 1e7, 1e8])
    sec = dec / 249.0
    ax.plot(dec, sec / 3600.0, "o-", color="#2ca02c")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("decisions")
    ax.set_ylabel("collection hours @249 dec/s")
    ax.set_title("Data budget (collection only, no PPO/eval)")
    for d, s in [(1e6, 1e6/249/3600), (1e7, 1e7/249/3600), (1e8, 1e8/249/3600)]:
        ax.annotate(f"{d/1e6:.0f}M≈{s:.1f}h", (d, s), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8)
    ax.grid(alpha=.3, which="both")

    fig.suptitle("HSBRSIM P0 curves & data budget (entity sims=4, vs bot)", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=160)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
