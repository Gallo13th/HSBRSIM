"""按阶段对比"战团强度 vs 真实 10k+"曲线，并输出表格与图。

用法:
  python scripts/plot_strength_stages.py --out runs/plots/strength_stages.png
默认读取 runs/quality/ 下带 by_turn 的阶段 JSON（由 quality_monitor.py 产出）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

STAGES = [
    ("champion_1746", "runs/quality/champ_1746_96.json"),
    ("s8", "runs/quality/s8_27M32.json"),
    ("s8b", "runs/quality/s8b_g48.json"),
    ("s10@40M", "runs/quality/s10_40M.json"),
    ("s12@10M", "runs/quality/s12_10M.json"),
    ("s13@10M", "runs/exam/quality_s13_10M.json"),
    ("s14@70M", "runs/quality/s14_70M.json"),
]
TURNS = [5, 7, 9, 10, 12, 13, 14, 15]


def load(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def series(data, key):
    out = {}
    for row in data.get("by_turn") or []:
        out[int(row["turn"])] = row.get(key)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/plots/strength_stages.png")
    ap.add_argument("--table", default="runs/plots/strength_stages.md")
    args = ap.parse_args()

    loaded = [(n, load(p)) for n, p in STAGES]
    loaded = [(n, d) for n, d in loaded if d]
    if not loaded:
        print("no quality json found")
        return 1

    real_p50 = series(loaded[-1][1], "real_p50")
    real_p90 = series(loaded[-1][1], "real_p90")

    fig, axes = plt.subplots(1, 3, figsize=(19, 5.4))
    ax = axes[0]
    for name, data in loaded:
        s = series(data, "ours_p50")
        xs = [t for t in sorted(s) if s[t] is not None]
        ys = [max(s[t], 1e-3) for t in xs]
        ax.plot(xs, ys, marker="o", ms=3, lw=1.4, label=name)
    rx = [t for t in sorted(real_p50) if real_p50[t]]
    ax.plot(rx, [real_p50[t] for t in rx], "k-", lw=2.4, label="真实 10k+ p50")
    ry = [t for t in sorted(real_p90) if real_p90[t]]
    ax.plot(ry, [real_p90[t] for t in ry], "k--", lw=1.6, label="真实 10k+ p90")
    ax.set_yscale("log")
    ax.set_xlabel("turn")
    ax.set_ylabel("warband Σ(atk+hp), p50")
    ax.set_title("各阶段战团强度曲线 vs 真实人类")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)

    ax = axes[1]
    for name, data in loaded:
        s = series(data, "ratio_p50")
        xs = [t for t in sorted(s) if s[t] is not None]
        ys = [s[t] for t in xs]
        ax.plot(xs, ys, marker="o", ms=3, lw=1.4, label=name)
    ax.set_xlabel("turn")
    ax.set_ylabel("我方 p50 / 真实 p50")
    ax.set_title("强度比（越高越接近真实）")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)

    ax = axes[2]
    for name, data in loaded:
        s = series(data, "tier_p50")
        xs = [t for t in sorted(s) if s[t] is not None]
        ax.plot(xs, [s[t] for t in xs], marker="o", ms=3, lw=1.4, label=name)
    ax.set_xlabel("turn")
    ax.set_ylabel("tavern tier p50")
    ax.set_title("酒馆等级曲线")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)

    fig.suptitle("HSBRSIM 战团强度阶段对比（quality_monitor 抽样）")
    fig.tight_layout()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=140)
    print("saved", args.out)

    rows = []
    header = "| 阶段 | " + " | ".join(f"t{t}" for t in TURNS) + " |"
    rows.append(header)
    rows.append("|---|" + "---|" * len(TURNS))
    rows.append("| 真实 10k+ p50 | " + " | ".join(f"{int(real_p50.get(t) or 0):,}" for t in TURNS) + " |")
    for name, data in loaded:
        s = series(data, "ours_p50")
        rows.append(f"| {name} | " + " | ".join(f"{int(s.get(t) or 0):,}" for t in TURNS) + " |")
    rows.append("")
    rows.append("| 阶段 | " + " | ".join(f"t{t}" for t in TURNS) + " |")
    rows.append("|---|" + "---|" * len(TURNS))
    for name, data in loaded:
        s = series(data, "ratio_p50")
        rows.append(f"| {name} 比值 | " + " | ".join(f"{(s.get(t) or 0):.3f}" for t in TURNS) + " |")
    os.makedirs(os.path.dirname(args.table), exist_ok=True)
    with open(args.table, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    print("saved", args.table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
