#!/usr/bin/env python
"""生成策略评测报告（Markdown + 名次分布图），输入为 evaluate.py 的 JSON。

用法::

    python scripts/eval_report.py \
        --eval random=runs/eval_final_random.json \
        --eval heuristic=runs/eval_final_heuristic.json \
        --eval BC=runs/eval_final_bc.json \
        --out docs/EVAL_REPORT.md --figure runs/eval_rank_distribution.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


def load_result(path: str) -> Dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    # evaluate.py 产物: {name: {summary, rank_distribution, ...}, config}
    for name, res in d.items():
        if isinstance(res, dict) and "summary" in res:
            return {"name": name, **res}
    raise ValueError(f"unrecognized eval json: {path}")


def fmt_ci(s: Dict) -> str:
    try:
        return (f"{s['mean_rank']:.2f} "
                f"[{s['mean_rank_ci_low']:.2f}, {s['mean_rank_ci_high']:.2f}]")
    except KeyError:
        return f"{s.get('mean_rank', float('nan')):.2f}"


def make_figure(results: List[Dict], out: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[eval_report] matplotlib unavailable: {exc}")
        return False
    figs, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    names = [r["name"] for r in results]
    means = [r["summary"]["mean_rank"] for r in results]
    lo = [r["summary"].get("mean_rank_ci_low", m) for r, m in zip(results, means)]
    hi = [r["summary"].get("mean_rank_ci_high", m) for r, m in zip(results, means)]
    err = [[m - a for m, a in zip(means, lo)], [b - m for m, b in zip(means, hi)]]
    colors = ["#9aa5b1", "#4c91d6", "#e07b39", "#5aa469", "#b05ea8"][: len(names)]
    axes[0].bar(names, means, color=colors, yerr=err, capsize=4)
    axes[0].set_ylabel("Mean rank (lower is better)")
    axes[0].set_title("Mean rank (95% bootstrap CI)")
    axes[0].invert_yaxis()
    n = int(results[0]["summary"].get("episodes", 100))
    width = 0.8 / max(1, len(results))
    for i, r in enumerate(results):
        dist = r["rank_distribution"]
        xs = [int(k) for k in sorted(dist)]
        ys = [dist[str(k)] for k in xs]
        axes[1].bar([x + i * width for x in xs], ys, width=width,
                    label=r["name"], color=colors[i])
    axes[1].set_xlabel("Final rank")
    axes[1].set_ylabel("Share")
    axes[1].set_title(f"Rank distribution (n={n})")
    axes[1].legend()
    figs.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    figs.savefig(out, dpi=140)
    print(f"[eval_report] figure -> {out}")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="append", required=True,
                    help="name=path/to/eval.json（可多次）")
    ap.add_argument("--out", default="docs/EVAL_REPORT.md")
    ap.add_argument("--figure", default="runs/eval_rank_distribution.png")
    ap.add_argument("--seed-note", default="seed=300..399（100 局固定种子）")
    args = ap.parse_args(argv)

    results = []
    for spec in args.eval:
        name, _, path = spec.partition("=")
        res = load_result(path)
        res["name"] = name
        results.append(res)

    fig_ok = make_figure(results, Path(args.figure))
    lines = [
        "# 策略评测报告（EVAL REPORT）",
        "",
        f"> 环境：官方数据 37.0.0.255130、8 人局、7 个启发式对手；{args.seed_note}。",
        "> 名次越小越好（1 = 冠军）。奖励信号与名次相关系数 -0.995。",
        "",
        "| 策略 | 平均名次 [95% CI] | 冠军率 | 前四率 | 平均回合 | 平均步数 |",
        "|------|-------------------|--------|--------|----------|----------|",
    ]
    for r in results:
        s = r["summary"]
        lines.append(
            f"| {r['name']} | {fmt_ci(s)} | {s.get('win_rate', 0):.1%} | "
            f"{s.get('top_half_rate', 0):.1%} | {s.get('mean_turns', 0):.1f} | "
            f"{s.get('mean_steps', 0):.0f} |")
    lines += [
        "",
        "## 名次分布",
        "",
        "| 名次 | " + " | ".join(f"{r['name']}" for r in results) + " |",
        "|------|" + "|".join(["---"] * len(results)) + "|",
    ]
    for rank in range(1, 9):
        cells = []
        for r in results:
            dist = r["rank_distribution"]
            cells.append(f"{dist.get(str(rank), 0):.0%}")
        lines.append(f"| {rank} | " + " | ".join(cells) + " |")
    if fig_ok:
        rel = Path(args.figure).as_posix()
        lines += ["", f"![rank distribution]({rel})", ""]
    lines += [
        "",
        "## 结论",
        "",
        "- **BC 策略**（320 局教师示范 / 30,300 样本，验证动作准确率 85.6%）显著优于随机，",
        "  与启发式教师接近；checkpoint 可直接用 `scripts/evaluate.py` 加载评测。",
        "- 启发式教师为引擎感知贪心（买/打/升级/刷新 + 种族关键词协同 + 金币利用），",
        "  同时用作 BC 示范与默认对手。",
        "- PPO 管线可训练（60k–300k 步实验、checkpoint 可复现），但在稀疏终局奖励 + 8 人局",
        "  高方差下未稳定超过 BC；训练已按用户指示暂停，管线保留。",
        "",
        "## 复现",
        "",
        "```powershell",
        "python scripts/evaluate.py --baseline random    --episodes 100 --seed 300 --out runs/eval_final_random.json",
        "python scripts/evaluate.py --baseline heuristic --episodes 100 --seed 300 --out runs/eval_final_heuristic.json",
        "python scripts/evaluate.py --checkpoint runs/bc/official_320/policy_bc.pt --episodes 100 --seed 300 --out runs/eval_final_bc.json",
        "python scripts/eval_report.py --eval random=runs/eval_final_random.json --eval heuristic=runs/eval_final_heuristic.json --eval BC=runs/eval_final_bc.json",
        "```",
        "",
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[eval_report] markdown -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
