#!/usr/bin/env python3
"""一个观察点的三图报告：训练曲线 + 前二名阵容 + 强度曲线。

用户要求（每一轮新观察点都要看）：训练曲线、对战阵容、强度曲线。

用法：
  python scripts/point_report.py --run runs/az_stage300m_b10 --ckpt runs/.../ckpt_0100xxx.pt \
      --tag 10M --device cuda:7 [--games 48] [--curve-games 96] [--skip-lineups]

产物（`runs/point_reports/<run 名>/<tag>/`）：
  - `training.png`   训练曲线（loss/KL/entropy + 96 局 rank/win 随决策数）
  - `lineups.png`    前二名阵容卡表（48 局）+ `comps.json` 复利指标
  - `strength.png`   强度曲线（模型 vs 基线 vs 人类胜者库）
  - `summary.md`     文字小结（关键数字）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402

#: 中文显示（有 CJK 字体就挂上，没有就退回 DejaVu，坐标轴仍是英文数字）
for _p in ("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
    if os.path.exists(_p):
        fm.fontManager.addfont(_p)
        matplotlib.rcParams["font.sans-serif"] = [fm.FontProperties(fname=_p).get_name(),
                                                  "DejaVu Sans"]
        break
matplotlib.rcParams["axes.unicode_minus"] = False

C_BASE = "#9467bd"
C_CUR = "#2ca02c"


# ── 数据读取 ────────────────────────────────────────────────────────────────
def _read_jsonl(p: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _ppo_metric(rec: Dict[str, Any], key: str) -> Optional[float]:
    ep = ((rec.get("ppo") or {}).get("epochs") or [{}])[0]
    v = ep.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def training_curves(run: str, out_png: str, *, baseline_label: str = "") -> Dict[str, Any]:
    hist = _read_jsonl(os.path.join(run, "history.jsonl"))
    pts = _read_jsonl(os.path.join(run, "points.jsonl"))
    dec = [int(r.get("cum_decisions") or 0) / 1e6 for r in hist]
    keys = {"total": "总损失", "value_loss": "价值损失", "entropy": "熵",
            "approx_kl": "approx_kl (x100)", "clip_frac": "clip 比例"}
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    ax = axes[0][0]
    for k, label in (("total", "总损失"), ("value_loss", "价值损失")):
        ys = [_ppo_metric(r, k) for r in hist]
        ax.plot(dec, [y for y in ys], lw=1.2, label=label)
    ax.set_xlabel("累计 decisions (M)"); ax.set_title("训练损失"); ax.grid(alpha=.3); ax.legend()
    ax = axes[0][1]
    for k, label, scale in (("approx_kl", "approx_kl", 100.0), ("clip_frac", "clip 比例", 100.0),
                            ("entropy", "熵", 1.0)):
        ys = [_ppo_metric(r, k) for r in hist]
        if any(y is not None for y in ys):
            ax.plot(dec, [None if y is None else y * scale for y in ys], lw=1.1, label=label)
    ax.set_xlabel("累计 decisions (M)"); ax.set_title("学习信号（KL×100 / clip×100 / 熵）")
    ax.grid(alpha=.3); ax.legend()
    ax = axes[1][0]
    pm = [int(p.get("point_decisions") or 0) / 1e6 for p in pts if p.get("status") == "ok"]
    for field, label in (("bot_rank", "bot 面板 rank"), ("rank", "human 面板 rank")):
        ys = [p.get(field) for p in pts if p.get("status") == "ok"]
        ys = [float(y) if isinstance(y, (int, float)) else None for y in ys]
        if any(y is not None for y in ys):
            ax.plot(pm, ys, "o-", ms=3, lw=1.2, label=label)
    ax.set_xlabel("累计 decisions (M)"); ax.set_title("面板名次（越小越好）"); ax.grid(alpha=.3); ax.legend()
    ax = axes[1][1]
    for field, label in (("bot_win", "bot 面板胜率"), ("tier_ge5_t15", "tier≥5@t15")):
        ys = [p.get(field) for p in pts if p.get("status") == "ok"]
        ys = [float(y) if isinstance(y, (int, float)) else None for y in ys]
        if any(y is not None for y in ys):
            ax.plot(pm, ys, "o-", ms=3, lw=1.2, label=label)
    ax.set_xlabel("累计 decisions (M)"); ax.set_title("胜率 / 升本率"); ax.grid(alpha=.3); ax.legend()
    fig.suptitle("训练曲线 — %s%s" % (os.path.basename(run.rstrip('/')),
                                      ("  |  " + baseline_label) if baseline_label else ""))
    fig.tight_layout(rect=[0, 0, 1, 0.955])
    fig.savefig(out_png, dpi=140, bbox_inches="tight")
    plt.close(fig)
    last = pts[-1] if pts else {}
    return {"points": len([p for p in pts if p.get("status") == "ok"]),
            "bot_rank": last.get("bot_rank"), "bot_win": last.get("bot_win"),
            "human_rank": last.get("rank"), "tier_ge5_t15": last.get("tier_ge5_t15")}


def _curve_medians(path: str) -> List[tuple]:
    d = json.load(open(path, encoding="utf-8"))
    agg = d.get("agg") or {}
    pts = []
    for t, rec in (agg.get("model_curve") or {}).items():
        if isinstance(rec, dict) and rec.get("median") is not None:
            pts.append((float(t), float(rec["median"])))
    pts.sort()
    rc = agg.get("model_rank_counts") or {}
    n = sum(rc.values()) or 1
    return pts, {"first": rc.get("1", 0) / n, "top2": (rc.get("1", 0) + rc.get("2", 0)) / n, "n": n}


def strength_curve(model_json: str, out_png: str, *, baseline_json: Optional[str],
                   label: str, baseline_label: str) -> Dict[str, Any]:
    fig, ax = plt.subplots(figsize=(9, 5.4))
    info: Dict[str, Any] = {}
    series = [(model_json, label, C_CUR)]
    if baseline_json and os.path.exists(baseline_json):
        series.append((baseline_json, baseline_label, C_BASE))
    for path, lab, color in series:
        if not os.path.exists(path):
            continue
        pts, st = _curve_medians(path)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "o-", ms=3.5, lw=1.8, color=color,
                label="%s（1st %.0f%%, top2 %.0f%%, n=%d）" % (lab, 100 * st["first"],
                                                              100 * st["top2"], st["n"]))
        info[lab] = {"medians": dict(pts), **st}
    ax.set_xlabel("turn"); ax.set_ylabel("盘面强度 median Σ(atk+hp)")
    ax.set_title("强度曲线（bot 场同口径）"); ax.grid(alpha=.3); ax.legend(fontsize=8); ax.set_xlim(0, 20)
    fig.tight_layout()
    fig.savefig(out_png, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return info


def run_cmd(cmd: List[str], log) -> int:
    log.write("$ " + " ".join(cmd) + "\n")
    log.flush()
    r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log.write(r.stdout)
    log.flush()
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=48, help="阵容表局数")
    ap.add_argument("--curve-games", type=int, default=96, help="强度曲线局数")
    ap.add_argument("--baseline-ckpt", default="runs/az_stage300m_b08/eval/ckpt_150028307.pt")
    ap.add_argument("--baseline-curve", default="runs/bot_curves/b08_150m_g96.json")
    ap.add_argument("--baseline-label", default="B08@150M(强制升本基线)")
    ap.add_argument("--skip-lineups", action="store_true")
    ap.add_argument("--skip-curve", action="store_true")
    args = ap.parse_args(argv)

    out_dir = os.path.join("runs", "point_reports", os.path.basename(args.run.rstrip("/")), args.tag)
    os.makedirs(out_dir, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", "rust/python:.")
    env["HSBRSIM_FORCE_UPGRADE"] = "1"
    env["HSBRSIM_FORCE_UPGRADE_MAX_TIER"] = "5"
    env["HSBRSIM_BAN_TRINKETS"] = "BG36_MagicItem_414"
    os.environ.update({k: env[k] for k in ("HSBRSIM_FORCE_UPGRADE",
                                           "HSBRSIM_FORCE_UPGRADE_MAX_TIER",
                                           "HSBRSIM_BAN_TRINKETS")})

    py = sys.executable
    summary: Dict[str, Any] = {"run": args.run, "ckpt": args.ckpt, "tag": args.tag}
    log_path = os.path.join(out_dir, "report.log")
    with open(log_path, "w", encoding="utf-8") as log:
        # 1) 训练曲线
        tr = training_curves(args.run, os.path.join(out_dir, "training.png"))
        summary["training"] = tr
        # 2) 阵容表 + 复利指标
        if not args.skip_lineups:
            lj = os.path.join(out_dir, "lineups.json")
            rc = run_cmd([py, "scripts/top2_lineups.py", "--checkpoint", args.ckpt,
                          "--device", args.device, "--games", str(args.games),
                          "--topk", "2", "--max-rows", "8", "--out", lj[:-5]], log)
            summary["lineups_rc"] = rc
            if rc == 0 and os.path.exists(lj):
                try:
                    os.replace(os.path.join(out_dir, "lineups.json"), lj)
                except OSError:
                    pass
                rc2 = run_cmd([py, "scripts/comp_metrics.py", lj], log)
                summary["comps_rc"] = rc2
        # 3) 强度曲线
        if not args.skip_curve:
            cjson = os.path.join(out_dir, "curve.json")
            rc = run_cmd([py, "scripts/bot_strength_curves.py", "--checkpoint", args.ckpt,
                          "--device", args.device, "--games", str(args.curve_games),
                          "--out", cjson[:-5]], log)
            summary["curve_rc"] = rc
            try:
                os.replace(cjson[:-5] + ".json", cjson)
            except OSError:
                pass
            summary["strength"] = strength_curve(
                cjson, os.path.join(out_dir, "strength.png"),
                baseline_json=args.baseline_curve,
                label="%s@%s" % (os.path.basename(args.run.rstrip("/")), args.tag),
                baseline_label=args.baseline_label)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print("[point-report] out=", out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
