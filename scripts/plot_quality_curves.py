#!/usr/bin/env python3
"""质量曲线：bot 面板 vs human 面板（新主指标）+ 训练吞吐（ppo_s / collect_s）。

同时画（``docs/EVAL_PANELS.md``）：

- **平均名次**：bot 面板 ``mean_rank``（已饱和）与 human 面板 ``human_mean_rank``
  （10k+ 人类战团分位对手，新主指标），越低越好；
- **top4 / win**：两个面板各自的前四率与冠军率；
- **训练吞吐**：``history.jsonl`` 每次 iteration 的 ``profile.ppo_s`` / ``profile.collect_s``
  （"tag" 即该 run 的逐 iteration 记录），横轴=累计 decisions。

输入：
  - ``runs/<run>/eval/history.json``：``{"evals": [...]}``，记录用 ``panel`` 区分；
    没有 ``panel`` 的旧记录视为 bot 面板；
  - ``runs/<run>/history.jsonl``：逐 iteration 记录（``collect`` / ``profile``）。

用法::

    python scripts/plot_quality_curves.py --run runs/az_entity_s3 --out quality_curves.png
    # 多 run 对比
    python scripts/plot_quality_curves.py --run runs/a --run runs/b --out compare.png

输出默认写到 ``runs/plots/<out>.png``（``--out`` 含目录时按给定路径）。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as _fm  # noqa: E402

from hsbg.az.train.runlog import read_run  # noqa: E402

#: CJK 字体（与其它绘图脚本一致；找不到就退回 DejaVu）。
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

#: 每条曲线：颜色/线型（bot 实线、human 虚线；语义稳定便于跨 run 对比）。
_STYLE = {
    "bot_rank": dict(color="#1f77b4", ls="-", marker="o"),
    "human_rank": dict(color="#d62728", ls="--", marker="s"),
    "bot_top4": dict(color="#1f77b4", ls="-", marker="o"),
    "human_top4": dict(color="#d62728", ls="--", marker="s"),
    "bot_win": dict(color="#17becf", ls="-", marker="^"),
    "human_win": dict(color="#ff7f0e", ls="--", marker="v"),
}


def load_eval_history(run: str) -> List[Dict[str, Any]]:
    """读 ``eval/history.json``；缺失/损坏返回 []。"""
    path = os.path.join(run, "eval", "history.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("evals") or []) if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001
        return []


def split_panels(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按 ``panel`` 拆分；旧记录（无 panel）归入 bot 面板。"""
    out: Dict[str, List[Dict[str, Any]]] = {"bot": [], "human": []}
    for r in records:
        panel = str(r.get("panel") or "bot")
        if panel not in out:
            out[panel] = []
        out[panel].append(r)
    for rows in out.values():
        rows.sort(key=lambda r: int(r.get("decisions") or 0))
    return out


def _points(rows: List[Dict[str, Any]], key: str) -> Tuple[List[float], List[float]]:
    xs, ys = [], []
    for r in rows:
        v = r.get(key)
        if v is None:
            continue
        xs.append(float(r.get("decisions") or 0) / 1e6)
        ys.append(float(v))
    return xs, ys


def load_train_profile(run: str) -> Dict[str, List[float]]:
    """从 ``history.jsonl`` 取累计 decisions 与 ppo_s / collect_s（缺失返回空）。

    兼容旧 ``history.json``（``{"history": [...]}``，``read_run`` 自动识别）。
    """
    path = os.path.join(run, "history.jsonl")
    if not os.path.isfile(path):
        path = os.path.join(run, "history.json")
    if not os.path.isfile(path):
        return {"decisions_m": [], "ppo_s": [], "collect_s": []}
    try:
        _header, records = read_run(path)
    except Exception:  # noqa: BLE001
        return {"decisions_m": [], "ppo_s": [], "collect_s": []}
    dec_m: List[float] = []
    ppo_s: List[float] = []
    collect_s: List[float] = []
    acc = 0.0
    for r in records:
        collect = r.get("collect") or {}
        prof = r.get("profile") or {}
        if "collect_s" not in prof and "ppo_s" not in prof:
            continue        # 旧 history.json 没有 profile：不画假的 0 值
        try:
            acc += float(collect.get("decisions") or 0)
        except (TypeError, ValueError):
            continue
        dec_m.append(acc / 1e6)
        ppo_s.append(float(prof.get("ppo_s") or 0.0))
        collect_s.append(float(prof.get("collect_s") or 0.0))
    return {"decisions_m": dec_m, "ppo_s": ppo_s, "collect_s": collect_s}


def _legend(ax: Any, **kw: Any) -> None:
    """只在其有带 label 的 artist 时画图例（空数据不告警）。"""
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(**kw)


def main() -> int:
    ap = argparse.ArgumentParser(description="质量曲线：bot/human 面板 + 训练吞吐")
    ap.add_argument("--run", action="append", default=[],
                    help="run 目录（可重复）；默认 runs/az_entity_sync")
    ap.add_argument("--out", default="quality_curves.png",
                    help="输出文件名；相对路径写到 runs/plots/<out>")
    ap.add_argument("--title", default="", help="图标题（空=自动）")
    args = ap.parse_args()
    runs = list(args.run) or [os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "runs", "az_entity_sync")]
    out = str(args.out)
    if not os.path.dirname(out):
        out = os.path.join("runs", "plots", out)
    if not out.lower().endswith((".png", ".pdf", ".svg")):
        out += ".png"
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(16.5, 4.8))
    ax_rank, ax_rate, ax_prof = axes
    plotted = 0
    n_panels = 0
    for run in runs:
        name = os.path.basename(os.path.abspath(run).rstrip("/")) or run
        panels = split_panels(load_eval_history(run))
        bot_rows = [r for r in panels.get("bot", [])
                    if r.get("mean_rank") is not None and not r.get("skipped")]
        human_rows = [r for r in panels.get("human", [])
                      if r.get("human_mean_rank") is not None and not r.get("skipped")]
        if bot_rows:
            n_panels += 1
            xs, ys = _points(bot_rows, "mean_rank")
            ax_rank.plot(xs, ys, label=f"{name} bot", lw=1.6, ms=5,
                         **_STYLE["bot_rank"])
            xs, ys = _points(bot_rows, "top4")
            if xs:
                ax_rate.plot(xs, ys, label=f"{name} bot top4", lw=1.3, ms=4,
                             **_STYLE["bot_top4"])
            xs, ys = _points(bot_rows, "win")
            if xs:
                ax_rate.plot(xs, ys, label=f"{name} bot win", lw=1.3, ms=4,
                             **_STYLE["bot_win"])
            plotted += 1
        if human_rows:
            n_panels += 1
            xs, ys = _points(human_rows, "human_mean_rank")
            ax_rank.plot(xs, ys, label=f"{name} human", lw=1.6, ms=5,
                         **_STYLE["human_rank"])
            xs, ys = _points(human_rows, "human_top4")
            if xs:
                ax_rate.plot(xs, ys, label=f"{name} human top4", lw=1.3, ms=4,
                             **_STYLE["human_top4"])
            xs, ys = _points(human_rows, "human_win")
            if xs:
                ax_rate.plot(xs, ys, label=f"{name} human win", lw=1.3, ms=4,
                             **_STYLE["human_win"])
            plotted += 1
        prof = load_train_profile(run)
        if prof["decisions_m"]:
            ax_prof.plot(prof["decisions_m"], prof["collect_s"], lw=1.2,
                         color="#2ca02c", label=f"{name} collect_s")
            ax_prof.plot(prof["decisions_m"], prof["ppo_s"], lw=1.2,
                         color="#9467bd", label=f"{name} ppo_s")
            plotted += 1

    if plotted == 0:
        print(f"[plot] 没有可画的数据（检查 {runs} 下的 eval/history.json 与 "
              f"history.jsonl）", file=sys.stderr)
        return 1

    ax_rank.set_xlabel("cumulative training decisions (M)")
    ax_rank.set_ylabel("mean rank (lower better)")
    ax_rank.set_title("Eval mean rank: bot panel vs human panel")
    ax_rank.axhline(3.0, color="tab:red", ls=":", lw=1, label="target 3.0")
    ax_rank.invert_yaxis()
    ax_rank.grid(alpha=0.3)
    _legend(ax_rank, fontsize=8)

    ax_rate.set_xlabel("cumulative training decisions (M)")
    ax_rate.set_ylabel("rate")
    ax_rate.set_ylim(0.0, 1.02)
    ax_rate.set_title("top4 / win: bot panel vs human panel")
    ax_rate.grid(alpha=0.3)
    _legend(ax_rate, fontsize=7, ncol=2)

    ax_prof.set_xlabel("cumulative training decisions (M)")
    ax_prof.set_ylabel("seconds per iteration")
    ax_prof.set_title("training profile: collect_s / ppo_s")
    ax_prof.set_yscale("log")
    ax_prof.grid(alpha=0.3, which="both")
    _legend(ax_prof, fontsize=8)

    title = str(args.title) or ("质量曲线：" + ", ".join(
        os.path.basename(os.path.abspath(r).rstrip("/")) for r in runs))
    fig.suptitle(title, fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out, dpi=160)
    print(f"[plot] {out} (panels={n_panels}, runs={len(runs)})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
