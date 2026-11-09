#!/usr/bin/env python3
"""把各观察点的"强度 / 阵容结构"指标画成趋势图（监控用）。

读取 `runs/point_reports/<run>/<M>M/` 下的 `curve.json`（强度曲线）与 `lineups.json`
（前二盘面），输出：
  左：强度中位数 @t12/@15/@18 随决策数变化
  右：放大器卡位占比、T5+ 卡位占比、第 1 名率

用法： python scripts/point_trend.py --run runs/az_stage300m_b12
"""
from __future__ import annotations
import argparse, collections, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
import hsbg_engine as E  # noqa: E402

for _p in ("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",):
    if os.path.exists(_p):
        fm.fontManager.addfont(_p)
        matplotlib.rcParams["font.sans-serif"] = [fm.FontProperties(fname=_p).get_name(), "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

AMPS = ("布莱恩·铜须", "达卡莱附魔师", "提图斯·瑞文戴尔")


def load_points(run: str):
    cat = {int(c["cid"]): c for c in json.loads(E.catalog_json())}
    nm = lambda cid: (cat.get(int(cid)) or {}).get("name_zh") or f"#{cid}"
    out = []
    for d in sorted(glob.glob(os.path.join(run, "*M")), key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)))):
        tag = os.path.basename(d)
        m = int(re.sub(r"\D", "", tag))
        cj = os.path.join(d, "curve.json")
        lj = os.path.join(d, "lineups.json")
        rec = {"M": m}
        if os.path.exists(cj):
            agg = json.load(open(cj, encoding="utf-8")).get("agg") or {}
            mc = {t: (v.get("median") if isinstance(v, dict) else None) for t, v in (agg.get("model_curve") or {}).items()}
            for t in ("12", "15", "18"):
                rec["s" + t] = mc.get(t)
            rc = agg.get("model_rank_counts") or {}
            n = sum(rc.values()) or 1
            rec["first"] = rc.get("1", 0) / n
            rec["top2"] = (rc.get("1", 0) + rc.get("2", 0)) / n
        if os.path.exists(lj):
            d2 = json.load(open(lj, encoding="utf-8"))
            games = [g for g in (d2.get("all") or []) if g.get("ok")
                     and 0 < int(((g.get("model") or {}).get("placement") or 0)) <= 2]
            slots = sum(len(g["model"].get("board") or []) for g in games)
            amp = t5 = 0
            for g in games:
                for u in (g["model"].get("board") or []):
                    cid = int(u["card"])
                    if nm(cid) in AMPS:
                        amp += 1
                    if int((cat.get(cid) or {}).get("tier") or 0) >= 5:
                        t5 += 1
            rec["boards"] = len(games)
            rec["amp"] = amp / max(1, slots)
            rec["t5"] = t5 / max(1, slots)
        out.append(rec)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/point_reports/az_stage300m_b12",
                    help="观察点报告目录（runs/point_reports/<run>）；也接受 runs/<run> 自动纠正")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    run = args.run
    if not glob.glob(os.path.join(run, "*M")):
        alt = os.path.join("runs", "point_reports", os.path.basename(run.rstrip("/")))
        if glob.glob(os.path.join(alt, "*M")):
            run = alt
    pts = [p for p in load_points(run) if p.get("s15") is not None]
    if not pts:
        print("[trend] 还没有可用点"); return 0
    xs = [p["M"] for p in pts]
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    for k, lab, c in (("s12", "强度 @t12", "#1f77b4"), ("s15", "强度 @t15", "#d62728"), ("s18", "强度 @t18", "#2ca02c")):
        ax[0].plot(xs, [p.get(k) for p in pts], "o-", label=lab, color=c, ms=3.5)
    ax[0].set_xlabel("累计 decisions (M)"); ax[0].set_ylabel("盘面强度中位数 Σ(atk+hp)")
    ax[0].set_title("强度监控（每个观察点 96 局）"); ax[0].grid(alpha=.3); ax[0].legend()
    ax2 = ax[1]
    ax2.plot(xs, [100 * (p.get("amp") or 0) for p in pts], "o-", color="#9467bd", label="放大器卡位占比 %")
    ax2.plot(xs, [100 * (p.get("t5") or 0) for p in pts], "s-", color="#ff7f0e", label="T5+ 卡位占比 %")
    ax2.plot(xs, [100 * (p.get("first") or 0) for p in pts], "^-", color="#17becf", label="第 1 名率 %")
    ax2.set_xlabel("累计 decisions (M)"); ax2.set_ylabel("%"); ax2.grid(alpha=.3); ax2.legend()
    ax2.set_title("阵容结构监控（前二盘面）")
    fig.suptitle("B12 观察点趋势 — 强度 / 复利结构")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = args.out or os.path.join(run, "trend.png")
    fig.savefig(out, dpi=140, bbox_inches="tight")
    print("[trend] ->", out)
    for p in pts:
        print("  %3dM | 强度 t12 %s t15 %s t18 %s | 放大器 %.2f%% T5+ %.1f%% 1st %.0f%% (盘面 %s)"
              % (p["M"], p.get("s12"), p.get("s15"), p.get("s18"),
                 100 * (p.get("amp") or 0), 100 * (p.get("t5") or 0),
                 100 * (p.get("first") or 0), p.get("boards", 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
