#!/usr/bin/env python3
"""1M PPO checkpoint scaling 曲线（每 125k 一次 64 局 C0 smoke）。"""

from __future__ import annotations

import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main() -> int:
    rows = []
    for p in sorted(glob.glob("/tmp/c0_step_*.json")):
        k = int(os.path.basename(p).split("_")[-1].split(".")[0])
        d = json.load(open(p, encoding="utf-8"))
        r = ((d.get("panels") or [{}])[0] if d.get("panels") else d.get("panel0") or {})
        rows.append({"step": k, "decisions": k * 125944.7,
                     "mean": r.get("model_mean_rank"), "bot": r.get("bot_mean_rank"),
                     "top4": r.get("model_top4")})
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    x = [r["decisions"] / 1e6 for r in rows]
    ax[0].plot(x, [r["mean"] for r in rows], "o-", color="#d62728")
    bot = rows[0]["bot"] if rows else None
    if bot:
        ax[0].axhline(bot, ls="--", color="gray", label=f"bot≈{bot:.2f}")
    ax[0].set_xlabel("decisions (M)")
    ax[0].set_ylabel("mean rank")
    ax[0].set_title("C0 smoke mean rank during 1M PPO (sims=0)")
    ax[0].invert_yaxis()
    ax[0].grid(alpha=.3)
    ax[0].legend(fontsize=8)
    ax[1].plot(x, [r["top4"] for r in rows], "o-", color="#1f77b4")
    ax[1].set_xlabel("decisions (M)")
    ax[1].set_ylabel("top4 rate")
    ax[1].set_title("C0 smoke top4 during 1M PPO")
    ax[1].grid(alpha=.3)
    fig.suptitle("1M PPO checkpoint scaling (64 games per point; high variance)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = "runs/plots/scaling_1m_steps.png"
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    fig.savefig(out, dpi=160)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
