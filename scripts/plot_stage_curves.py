#!/usr/bin/env python3
"""把多个 stage 的 C0 评测曲线画在一张图上（按累计 decisions 拼接）。

用法：
  python scripts/plot_stage_curves.py \
      --run runs/az_entity_kl_30m --run runs/az_entity_s2 \
      --out runs/plots/stage_curves.png
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as _fm  # noqa: E402

for _p in glob.glob("/usr/share/fonts/google-noto-cjk/NotoSansCJK-*.ttc"):
    try:
        _fm.fontManager.addfont(_p)
    except Exception:  # noqa: BLE001
        pass
for _name in ("Noto Sans CJK JP", "Noto Sans CJK SC"):
    if any(f.name == _name for f in _fm.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [_name, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        break


def load_evals(run: str):
    p = os.path.join(run, "eval", "history.json")
    if not os.path.isfile(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8")).get("evals", [])
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", default=[])
    ap.add_argument("--out", default="runs/plots/stage_curves.png")
    ap.add_argument("--baseline-rank", type=float, default=None,
                    help="起点基线 mean rank（默认从 0 决策点读）")
    args = ap.parse_args()

    fig, ax = plt.subplots(figsize=(10, 5.2))
    offset = 0
    all_rows = []
    for run in args.run:
        evs = [e for e in load_evals(run) if e.get("mean_rank") is not None]
        if not evs:
            continue
        xs = [offset + e["decisions"] / 1e6 for e in evs]
        ys = [e["mean_rank"] for e in evs]
        bot = [e.get("bot_mean_rank") for e in evs]
        label = os.path.basename(run.rstrip("/"))
        ax.plot(xs, ys, "o-", label=f"{label} model", lw=1.6, ms=5)
        ax.plot(xs, bot, "s--", label=f"{label} bot", lw=1.0, alpha=0.7, ms=4)
        all_rows.append((label, xs, ys))
        offset = xs[-1]

    if args.baseline_rank is not None:
        ax.axhline(args.baseline_rank, color="gray", ls=":", lw=1,
                   label=f"stage-1 start ({args.baseline_rank:.2f})")
    ax.axhline(3.0, color="tab:red", ls=":", lw=1, label="target 3.0")
    ax.set_xlabel("cumulative training decisions (M)")
    ax.set_ylabel("C0 mean rank (lower better)")
    ax.set_title("C0 512-game evals across stages")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=135)
    print(f"[plot] {args.out}")
    for label, xs, ys in all_rows:
        print(f"{label}: last {ys[-1]:.3f} @ {xs[-1]:.1f}M")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
