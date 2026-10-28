#!/usr/bin/env python3
"""单 iteration 运行时间轴（Gantt）+ 并行的限速分析。

读 `runs/<run>/history.json` 里某一 iteration 的 `profile.timeline` 与
`collect.collect.timeline`（均为 time.monotonic() 绝对时刻，同一台机器可比），画三张图：

(a) **现状**：8 个 actor 进程、父进程各阶段、learner（PPO）各自占用哪段时间，谁在等谁；
(b) **优化后**：double-buffer 流水线（collect(k+1) 与 update(k) 重叠）+ bf16 + 动态分片 +
    history jsonl 的预期时间轴；
(c) **资源利用率对比**：actor / learner GPU / 父进程单核。

用法：
  python scripts/plot_iteration_timeline.py --run runs/timeline_iter5 --iter 3 \
      --out runs/profile_timeline/iteration_timeline.png
"""

from __future__ import annotations

import argparse
import json
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as _fm  # noqa: E402

# 中文字体（服务器自带 Noto Sans CJK；.ttc 需要显式 addfont 才会进 fontManager）
import glob as _glob  # noqa: E402
for _p in _glob.glob("/usr/share/fonts/google-noto-cjk/NotoSansCJK-*.ttc"):
    try:
        _fm.fontManager.addfont(_p)
    except Exception:  # noqa: BLE001
        pass
for _name in ("Noto Sans CJK JP", "Noto Sans CJK SC", "Noto Sans CJK TC",
              "WenQuanYi Zen Hei"):
    if any(f.name == _name for f in _fm.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [_name, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        break
from matplotlib.patches import Patch  # noqa: E402

# 实测常数（来自 docs/THROUGHPUT_PLAN.md；只在 history 缺字段时兜底）
BF16_SPEEDUP = 2.03


def _load(path: str, retries: int = 5):
    for _ in range(retries):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
    return None


def _pick_iter(hist, idx: int):
    rows = [r for r in hist if r.get("profile", {}).get("timeline")]
    if not rows:
        raise SystemExit("history 里没有 profile.timeline（用打过时间戳的 run）")
    return rows[min(idx, len(rows) - 1)]


def _phases(rec):
    tl = rec["profile"]["timeline"]
    t0 = tl["t_iter_start"]
    ct = (rec.get("collect", {}) or {}).get("collect", {}).get("timeline") or {}
    def off(x):
        return None if x is None else float(x - t0)
    return {
        "t0": t0,
        "reload": (0.0, off(tl["t_reload_done"])),
        "workers": [(int(i), off(ct["t_issue"][i]), off(ct.get("t_recv", {}).get(i)))
                    for i in sorted(ct.get("t_issue", {}), key=int)] if ct else [],
        "read": (off(ct.get("t_read_start")), off(ct.get("t_read_done"))) if ct else (None, None),
        "build": (off(ct.get("t_read_done")), off(ct.get("t_build_done"))) if ct else (None, None),
        "ppo": (off(tl.get("t_ppo_start")), off(tl.get("t_ppo_done"))),
        "history": (off(tl.get("t_ppo_done")), off(tl.get("t_history_done"))),
        "total": off(tl.get("t_history_done")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/timeline_iter5")
    ap.add_argument("--iter", type=int, default=3, help="取第几个带 timeline 的 iteration")
    ap.add_argument("--out", default="runs/profile_timeline/iteration_timeline.png")
    args = ap.parse_args()

    hist = (_load(os.path.join(args.run, "history.json")) or {}).get("history", [])
    rec = _pick_iter(hist, args.iter)
    ph = _phases(rec)
    total = ph["total"]
    nw = max(len(ph["workers"]), 8)

    # ---------- 现状 ----------
    fig = plt.figure(figsize=(14, 8.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.55, 1.0], hspace=0.32, wspace=0.18)
    ax = fig.add_subplot(gs[0, 0:2])

    y = 0
    rows = []
    # learner（PPO）在最上面，表示 GPU 占用
    ax.barh(y, ph["ppo"][1] - ph["ppo"][0], left=ph["ppo"][0], height=0.62,
            color="#d1495b", alpha=0.9)
    ax.text(ph["ppo"][0] + 0.05, y, f"PPO update (learner GPU) {ph['ppo'][1]-ph['ppo'][0]:.2f}s",
            va="center", fontsize=9, color="white", weight="bold")
    rows.append("learner GPU")
    y += 1
    for wid, a, b in ph["workers"]:
        ax.barh(y, b - a, left=a, height=0.62, color="#2e86ab", alpha=0.85)
        ax.text(a + 0.03, y, f"actor {wid} {b-a:.2f}s", va="center", fontsize=8, color="white")
        rows.append(f"actor {wid}")
        y += 1
    for i in range(len(ph["workers"]), nw):
        rows.append(f"actor {i}")
        y += 1
    parent_c = "#7f8c8d"
    ax.barh(y, ph["reload"][1] - ph["reload"][0], left=0.0, height=0.62,
            color=parent_c, alpha=0.9)
    ax.text(ph["reload"][1] + 0.05, y, f"push weights {ph['reload'][1]:.2f}s",
            va="center", fontsize=8, color="#2c3e50")
    rows.append("parent (1 core)")
    y += 1
    if ph["read"][0] is not None:
        ax.barh(y, ph["read"][1] - ph["read"][0], left=ph["read"][0], height=0.62,
                color="#f4a261", alpha=0.95)
        ax.text(ph["read"][0] + 0.02, y, f"read 431MB {ph['read'][1]-ph['read'][0]:.2f}s",
                va="center", fontsize=8)
        rows.append("parent read")
        y += 1
        ax.barh(y, ph["build"][1] - ph["build"][0], left=ph["build"][0], height=0.62,
                color="#e9c46a", alpha=0.95)
        ax.text(ph["build"][0] + 0.02, y, f"build batch {ph['build'][1]-ph['build'][0]:.2f}s",
                va="center", fontsize=8)
        rows.append("parent build")
        y += 1
    # 空闲/等待阴影：collect 期间 learner 空闲、PPO 期间 actor 空闲
    ax.axvspan(ph["reload"][1], ph["ppo"][0], color="#d1495b", alpha=0.06)
    ax.axvspan(ph["ppo"][0], ph["ppo"][1], color="#2e86ab", alpha=0.06)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, total * 1.02)
    ax.set_xlabel("秒（同一 iteration 内，monotonic 时钟）")
    ax.set_title(
        f"现状：单 iteration {total:.2f}s（{args.run} iter#{rec['iter']}）\n"
        f"红底=只有 learner 在跑（8 个 actor 空闲 {ph['ppo'][1]-ph['ppo'][0]:.1f}s）；"
        f"蓝底=只有 actor 在跑（GPU 只做零散前向）", fontsize=10, loc="left")
    ax.grid(axis="x", alpha=0.3)

    # ---------- 优化后（double-buffer） ----------
    ax2 = fig.add_subplot(gs[1, 0])
    collect_wall = max(b for _, _, b in ph["workers"])   # 最慢 actor
    ppo_now = ph["ppo"][1] - ph["ppo"][0]
    ppo_bf16 = ppo_now / BF16_SPEEDUP
    # 动态分片：把 straggler 的尾巴削掉（实测 tail ≈ max-mean ≈ 13%）
    mean_w = sum(b - a for _, a, b in ph["workers"]) / max(len(ph["workers"]), 1)
    collect_dyn = max(mean_w * 1.04, collect_wall * 0.88)
    merge = (ph["read"][1] - ph["read"][0]) + (ph["build"][1] - ph["build"][0])
    step = max(collect_dyn, ppo_bf16) + 0.25   # 流水线 + 握手/版本切换
    for k in range(3):
        base = k * step
        ax2.barh(2, collect_dyn, left=base + 0.1, height=0.5, color="#2e86ab", alpha=0.85)
        ax2.text(base + 0.15, 2, "collect k+%d" % (k + 1), va="center", fontsize=8, color="white")
        ax2.barh(0, ppo_bf16, left=base + 0.1 + collect_dyn * 0.0, height=0.5,
                 color="#d1495b", alpha=0.85)
        ax2.text(base + 0.15, 0, "update k+%d (bf16)" % k, va="center", fontsize=8, color="white")
        ax2.barh(4, merge, left=base + 0.1 + collect_dyn, height=0.35,
                 color="#f4a261", alpha=0.9)
    ax2.set_yticks([0, 2, 4])
    ax2.set_yticklabels(["learner GPU", "8 actors", "parent"], fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlim(0, step * 3 + 0.2)
    ax2.set_xlabel("秒（示意：三个 iteration 流水线）")
    ax2.set_title(f"优化后：double-buffer 流水线 → {step:.2f}s/iter\n"
                  f"（bf16 {ppo_now:.2f}→{ppo_bf16:.2f}s，动态分片 {collect_wall:.2f}→{collect_dyn:.2f}s，"
                  f"merge 移出关键路径）", fontsize=9, loc="left")
    ax2.grid(axis="x", alpha=0.3)

    # ---------- 利用率对比 ----------
    ax3 = fig.add_subplot(gs[1, 1])
    actor_now = mean_w / total
    gpu_now = ppo_now / total
    parent_now = (ph["reload"][1] + merge + (ph["history"][1] - ph["history"][0])) / total
    actor_new = collect_dyn / step
    gpu_new = ppo_bf16 / step
    parent_new = 0.08
    labels = ["actor 进程（单个）", "learner GPU", "父进程 1 核"]
    x = range(len(labels))
    ax3.bar([i - 0.18 for i in x], [actor_now, gpu_now, parent_now], width=0.36,
            label="现状", color="#7f8c8d")
    ax3.bar([i + 0.18 for i in x], [actor_new, gpu_new, parent_new], width=0.36,
            label="流水线+bf16", color="#2e86ab")
    for i, (a, b) in enumerate([(actor_now, actor_new), (gpu_now, gpu_new),
                                (parent_now, parent_new)]):
        ax3.text(i - 0.18, a + 0.02, f"{a*100:.0f}%", ha="center", fontsize=8)
        ax3.text(i + 0.18, b + 0.02, f"{b*100:.0f}%", ha="center", fontsize=8)
    ax3.set_xticks(list(x))
    ax3.set_xticklabels(labels, fontsize=9)
    ax3.set_ylim(0, 1.12)
    ax3.set_ylabel("占 iteration 时间的比例")
    ax3.set_title("资源利用率：现在是相控阵（phase-serial），不是流水线", fontsize=9, loc="left")
    ax3.legend(fontsize=8)
    ax3.grid(axis="y", alpha=0.3)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=135, bbox_inches="tight")
    print(f"[plot] {args.out}")

    # 文本结论
    slowest = max(ph["workers"], key=lambda w: w[2] - w[1])
    fastest = min(ph["workers"], key=lambda w: w[2] - w[1])
    print("\n== 关键数（iter #%d）==" % rec["iter"])
    print(f"iteration 总长      {total:.2f}s")
    print(f"push weights       {ph['reload'][1]:.2f}s（串行）")
    print(f"actor 最慢/最快     {slowest[2]-slowest[1]:.2f}s / {fastest[2]-fastest[1]:.2f}s"
          f"（静态分片 tail 损失 {slowest[2]-slowest[1]-(slowest[2]-slowest[1])*0+0:.2f}s 口径：max-mean={slowest[2]-slowest[1]-mean_w:.2f}s）")
    print(f"parent read+build  {merge:.2f}s（单核，8 actor 此时全空闲）")
    print(f"PPO                {ppo_now:.2f}s（GPU 忙，8 actor 全空闲）")
    print(f"history            {ph['history'][1]-ph['history'][0]:.2f}s")
    print(f"actor 单进程利用率  {actor_now*100:.0f}%   learner GPU 利用率 {gpu_now*100:.0f}%"
          f"   父进程单核 {parent_now*100:.0f}%")
    print(f"\n推演：bf16 → PPO {ppo_bf16:.2f}s；动态分片 → collect {collect_dyn:.2f}s；"
          f"double-buffer → {step:.2f}s/iter（≈{31000/step:.0f} dec/s 端到端）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
