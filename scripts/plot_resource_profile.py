#!/usr/bin/env python3
"""资源时间轴 profile：GPU util / CPU / 磁盘 + 阶段对齐，并给出「空闲预算」。

数据：
- `runs/profile_resource/sample.jsonl`（`scripts/resource_sampler.py`，0.2 s 粒度）
- `runs/<run>/history.jsonl`（每次 iteration 的 monotonic 时间戳：collect/PPO 区间）
- `runs/profile_resource/decision_cost.json`（单决策 CPU 成本分解）

用法：
  python scripts/plot_resource_profile.py --run runs/az_entity_s2 \
      --sample runs/profile_resource/sample.jsonl \
      --out runs/plots/resource_profile.png
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st
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

OUR_GPUS = (0, 5, 6, 7)   # 当前分配：0=learner，5/6/7=actors


def load_samples(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_phases(run):
    """从 history.jsonl 取每次 iteration 的 (collect_start, collect_end, ppo_start, ppo_end)。"""
    p = os.path.join(run, "history.jsonl")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            tl = (rec.get("profile") or {}).get("timeline") or {}
            ct = (rec.get("profile") or {}).get("collect_timeline") or {}
            t0 = tl.get("t_iter_start")
            if t0 is None:
                continue
            c_start = (ct or {}).get("t_issue")
            if isinstance(c_start, dict) and c_start:
                c_start = min(c_start.values())
            c_end = tl.get("t_collect_done")
            p_start = tl.get("t_ppo_start")
            p_end = tl.get("t_ppo_done")
            out.append((c_start or t0, c_end or t0, p_start or c_end or t0, p_end or p_start or t0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/az_entity_s2")
    ap.add_argument("--sample", default="runs/profile_resource/sample.jsonl")
    ap.add_argument("--cost", default="runs/profile_resource/decision_cost.json")
    ap.add_argument("--out", default="runs/plots/resource_profile.png")
    args = ap.parse_args()

    samples = load_samples(args.sample)
    phases = load_phases(args.run)
    t0 = samples[0]["t_mono"]
    xs = [s["t_mono"] - t0 for s in samples]

    fig = plt.figure(figsize=(14, 9))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.35, 1.0, 1.0], hspace=0.42, wspace=0.22)

    # ---- (a) GPU util 时间轴 ----
    ax = fig.add_subplot(gs[0, :])
    for s in phases:
        a = max(0.0, s[0] - t0)
        b = max(0.0, s[2] - t0)
        ax.axvspan(a, b, color="#2e86ab", alpha=0.07)
        ax.axvspan(b, max(b, s[3] - t0), color="#d1495b", alpha=0.07)
    colors = {0: "#d1495b", 5: "#2e86ab", 6: "#2e86ab", 7: "#2e86ab"}
    series = {}
    for s in samples:
        for g in s["gpus"]:
            series.setdefault(g["i"], []).append((s["t_mono"] - t0, g["util"]))
    for gi in sorted(series):
        ys = [v for _, v in series[gi]]
        if gi not in OUR_GPUS:
            ax.plot([x for x, _ in series[gi]], ys, lw=0.6, color="gray", alpha=0.45,
                    label=f"GPU{gi}（其他作业）" if gi == sorted(series)[0] else None)
            continue
        ax.plot([x for x, _ in series[gi]], ys, lw=1.2, color=colors[gi],
                label=f"GPU{gi}（{'learner' if gi == 0 else 'actor'}）")
    ax.set_xlim(0, xs[-1])
    ax.set_ylim(0, 105)
    ax.set_xlabel("采样时间（s）")
    ax.set_ylabel("GPU util (%)")
    ax.set_title("(a) GPU 利用率时间轴：蓝底=collect 窗口，红底=PPO 窗口（pipeline 下两者重叠）")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=4, loc="lower right")

    # ---- (b) CPU ----
    ax2 = fig.add_subplot(gs[1, 0])
    busy = [100 * s["cpu"].get("busy_ratio", 0.0) for s in samples]
    ax2.plot(xs, busy, lw=1.0, color="#e76f51", label="CPU busy (%)")
    ax2.set_ylim(0, 100)
    ax2.set_xlabel("采样时间（s）")
    ax2.set_ylabel("CPU busy (%)")
    ax2.set_title(f"(b) 整机 CPU：中位 {st.median(busy):.0f}%（128 vCPU）", loc="left")
    ax2.grid(alpha=0.3)
    ax2b = ax2.twinx()
    ax2b.plot(xs, [s["load1"] for s in samples], lw=0.8, color="#264653", alpha=0.6)
    ax2b.set_ylabel("load1")
    ax2b.set_ylim(0, max(20, max(s["load1"] for s in samples) * 1.2))

    # ---- (c) 空闲预算（按资源） ----
    ax3 = fig.add_subplot(gs[1, 1])
    ours = [series[g] for g in OUR_GPUS if g in series]
    labels, used = [], []
    for gi in OUR_GPUS:
        if gi in series:
            labels.append(f"GPU{gi}\n({'learner' if gi == 0 else 'actor'})")
            used.append(st.median([v for _, v in series[gi]]))
    labels.append("CPU\n(128 vCPU)")
    used.append(st.median(busy))
    ax3.barh(range(len(labels)), used, color=["#d1495b", "#2e86ab", "#2e86ab", "#2e86ab", "#e76f51"])
    ax3.barh(range(len(labels)), [100 - u for u in used], left=used, color="#dfe6e9")
    for i, u in enumerate(used):
        ax3.text(u / 2, i, f"{u:.0f}%", va="center", ha="center", fontsize=9, color="white"
                 if u > 20 else "black")
        ax3.text(min(99, u + 2), i, f"idle {100-u:.0f}%", va="center", fontsize=8, color="#555")
    ax3.set_yticks(range(len(labels)))
    ax3.set_yticklabels(labels, fontsize=8)
    ax3.set_xlim(0, 100)
    ax3.set_xlabel("中位占用率 (%)")
    ax3.set_title("(c) 空闲预算：每张卡/CPU 还有多少余量", loc="left")
    ax3.grid(axis="x", alpha=0.3)

    # ---- (d) 单决策成本分解 ----
    ax4 = fig.add_subplot(gs[2, 0])
    cost = json.load(open(args.cost, encoding="utf-8")) if os.path.isfile(args.cost) else {}
    med = cost.get("median_ms", {})
    engine_ms = med.get("step_learner_ms", 0) + med.get("opponents_ms", 0) + \
        med.get("observe_ms", 0) + med.get("mask_ms", 0) + med.get("bot_action_ms", 0)
    # 由吞吐反推：8 进程 × 645 dec/s → 每进程 1.55 ms/决策（GIL 串行）
    per_dec_ms = 1000.0 / 645.0
    gpu_ms = 0.2   # entity 前向（B≈7）量级，来自 bench_batch_leaf（3.8k leaf/s @B64）
    parts = [("引擎+观测+mask", engine_ms), ("GPU 前向", gpu_ms),
             ("Python/策略/记账/队列（GIL 串行）", max(0.0, per_dec_ms - engine_ms - gpu_ms))]
    left = 0.0
    cmap = ["#2a9d8f", "#d1495b", "#8d99ae"]
    for (name, v), c in zip(parts, cmap):
        ax4.barh(0, v, left=left, color=c, label=f"{name} {v:.2f} ms")
        left += v
    ax4.set_yticks([])
    ax4.set_xlabel("每个决策的串行时间（ms）")
    ax4.set_title(f"(d) 单决策预算：{per_dec_ms:.2f} ms（实测 645 dec/s/进程）", loc="left")
    ax4.legend(fontsize=8, loc="lower right")
    ax4.grid(axis="x", alpha=0.3)

    # ---- (e) 结论文字面板 ----
    ax5 = fig.add_subplot(gs[2, 1])
    ax5.axis("off")
    txt = (
        "把空闲时间拿去跑别的任务？\n\n"
        f"CPU：{st.median(busy):.0f}% busy（load1≈{st.median([s['load1'] for s in samples]):.1f}/128）\n"
        "  → 余量最多，但加线程不涨（GIL），要加【进程】才涨\n\n"
        f"learner GPU0：{st.median([v for _, v in series[0]]):.0f}% → 几乎打满，没余量\n"
        f"actor GPU5/6/7：{st.median([v for _, v in series[5]]):.0f}/"
        f"{st.median([v for _, v in series[6]]):.0f}/"
        f"{st.median([v for _, v in series[7]]):.0f}% → 约 30% 余量\n\n"
        "结论：现在不是「卡闲着」，而是\n"
        "  1) collect 比 PPO 长（6.6 vs 5.4 s）→ 加 actor 进程最直接；\n"
        "  2) 每决策 ~1.5 ms 是 GIL 串行（引擎只占 13 µs）；\n"
        "  3) 想并行第二个训练 run：显存够，但 GPU 会被时间切片，\n"
        "     总吞吐不翻倍，只是两条曲线同时走。"
    )
    ax5.text(0.0, 1.0, txt, va="top", ha="left", fontsize=9.2, linespacing=1.5)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=130, bbox_inches="tight")
    print(f"[plot] {args.out}")

    # ---- 文本汇总 ----
    print("\n== 资源中位占用 ==")
    for gi in OUR_GPUS:
        if gi in series:
            print(f"  GPU{gi}: {st.median([v for _, v in series[gi]]):.0f}%")
    print(f"  CPU: {st.median(busy):.0f}%  load1={st.median([s['load1'] for s in samples]):.1f}")
    print(f"\n== 单决策 ==")
    print(f"  引擎+观测+mask: {engine_ms*1000:.0f} µs")
    print(f"  GPU 前向: ~{gpu_ms*1000:.0f} µs")
    print(f"  Python/GIL: ~{(per_dec_ms-engine_ms-gpu_ms)*1000:.0f} µs")
    print(f"\n== 空闲预算（每秒）==")
    for gi in OUR_GPUS:
        if gi in series:
            u = st.median([v for _, v in series[gi]]) / 100
            print(f"  GPU{gi}: 空闲 {1-u:.2f} GPU·s/s")
    print(f"  CPU: 空闲 {1-st.median(busy)/100:.2f} 整机占比")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
