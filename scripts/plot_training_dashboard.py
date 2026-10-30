#!/usr/bin/env python3
"""综合训练仪表盘：把 history.jsonl / eval 历史 / 质量监控 JSON 画成一张多面板图。

面板：
1) bot / human 两面板 mean rank（越小越好）
2) 两面板 top4 / win
3) 战团强度：我方每 turn p50/p90 vs 真实 10k+ p50/p90（log）+ 强度比
4) 经济：tier / gold
5) 奖励与学习：reward_shaping_mean / value loss / entropy / approx_kl
6) pipeline：collect_s vs ppo_s + dec/s

用法::

  python scripts/plot_training_dashboard.py --run runs/az_entity_s8 \
      --quality runs/quality/s8_*.json --out runs/plots/s8_dashboard.png
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402

for _p in glob.glob("/usr/share/fonts/google-noto-cjk/NotoSansCJK-*.ttc"):
    try:
        fm.fontManager.addfont(_p)
    except Exception:
        pass
for _n in ("Noto Sans CJK JP", "Noto Sans CJK SC"):
    if any(f.name == _n for f in fm.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [_n, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        break


def _load_history(run: str):
    from hsbg.az.train.runlog import read_run

    path = os.path.join(run, "history.jsonl")
    if not os.path.isfile(path):
        return [], []
    _h, rows = read_run(path)
    cum, ppo, coll, decs = [], [], [], []
    tot = 0
    for x in rows:
        tot += int((x.get("collect") or {}).get("decisions") or 0)
        cum.append(tot / 1e6)
        p = x.get("profile") or {}
        ppo.append(float(p.get("ppo_s") or 0.0))
        coll.append(float(p.get("collect_s") or 0.0))
        decs.append(int((x.get("collect") or {}).get("decisions") or 0))
    return rows, {"cum": cum, "ppo": ppo, "collect": coll, "decisions": decs}


def _load_evals(run: str):
    path = os.path.join(run, "eval", "history.json")
    if not os.path.isfile(path):
        return []
    return [e for e in json.load(open(path)).get("evals") or []]


def _load_quality(patterns):
    out = []
    for pat in patterns or []:
        for p in glob.glob(pat):
            try:
                out.append(json.load(open(p)))
            except Exception:
                continue
    return out


def _panel_series(evals, key):
    xs, ys, t4, win = [], [], [], []
    for e in evals:
        v = e.get(key)
        if v is None:
            continue
        xs.append(e.get("decisions", 0) / 1e6)
        ys.append(v)
        t4.append(e.get("top4"))
        win.append(e.get("win"))
    return xs, ys, t4, win


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/az_entity_s8")
    ap.add_argument("--quality", nargs="*", default=[])
    ap.add_argument("--out", default="runs/plots/s8_dashboard.png")
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    rows, hist = _load_history(args.run)
    evals = _load_evals(args.run)
    q = _load_quality(args.quality)
    fig, ax = plt.subplots(3, 3, figsize=(21, 15))

    # 1) rank
    for key, label, color in (("mean_rank", "bot 面板", "tab:blue"),
                              ("human_mean_rank", "human 面板", "tab:red")):
        xs, ys, _, _ = _panel_series(evals, key)
        if xs:
            ax[0, 0].plot(xs, ys, "o-", color=color, label=label)
    ax[0, 0].set_xlabel("累计 decisions (M)")
    ax[0, 0].set_ylabel("mean rank（越小越好）")
    ax[0, 0].set_title("评测名次")
    ax[0, 0].grid(alpha=.3)
    ax[0, 0].legend(fontsize=8)

    # 2) top4 / win
    for key, panel, color in (("mean_rank", "bot", "tab:blue"),
                              ("human_mean_rank", "human", "tab:red")):
        xs, _, t4, win = _panel_series(evals, key)
        if xs:
            t4p = [(x, v * 100) for x, v in zip(xs, t4) if v is not None]
            winp = [(x, v * 100) for x, v in zip(xs, win) if v is not None]
            if t4p:
                ax[0, 1].plot([a for a, _ in t4p], [b for _, b in t4p], "o-", color=color,
                              label=f"{panel} top4%")
            if winp:
                ax[0, 1].plot([a for a, _ in winp], [b for _, b in winp], "s--", color=color,
                              alpha=.6, label=f"{panel} win%")
    ax[0, 1].set_xlabel("累计 decisions (M)")
    ax[0, 1].set_ylabel("%")
    ax[0, 1].set_title("top4 / 吃鸡率")
    ax[0, 1].grid(alpha=.3)
    ax[0, 1].legend(fontsize=7)

    # 3) board strength vs real
    if q:
        qq = q[-1]
        by = [r for r in qq.get("by_turn") or [] if r.get("real_p50")]
        if by:
            t = [r["turn"] for r in by]
            ax[0, 2].plot(t, [r["real_p50"] for r in by], "o-", color="tab:blue", label="real p50")
            ax[0, 2].plot(t, [r["real_p90"] for r in by], "o--", color="tab:blue", alpha=.5, label="real p90")
            ax[0, 2].plot(t, [r["ours_p50"] for r in by], "s-", color="tab:red", label="ours p50")
            ax[0, 2].plot(t, [r["ours_p90"] for r in by], "s--", color="tab:red", alpha=.5, label="ours p90")
            ax[0, 2].set_yscale("log")
            ax[0, 2].set_xlabel("turn")
            ax[0, 2].set_ylabel("战团强度 Σ(atk+hp)")
            ax[0, 2].set_title(f"战团强度 vs 真实 10k+（{qq.get('games')} 局）")
            ax[0, 2].grid(alpha=.3)
            ax[0, 2].legend(fontsize=8)
            ax[1, 0].plot(t, [r["ratio_p50"] for r in by], "o-", color="tab:purple")
            ax[1, 0].axhline(1.0, color="gray", ls=":", lw=1)
            ax[1, 0].set_xlabel("turn")
            ax[1, 0].set_ylabel("ours p50 / real p50")
            ax[1, 0].set_title("强度比（<1 更弱）")
            ax[1, 0].grid(alpha=.3)
            ax[1, 1].plot(t, [r["tier_p50"] for r in by], "o-", color="tab:green", label="tier p50")
            ax2 = ax[1, 1].twinx()
            ax2.plot(t, [r["gold_p50"] for r in by], "s--", color="tab:brown", label="gold p50")
            ax[1, 1].set_xlabel("turn")
            ax[1, 1].set_ylabel("tier")
            ax2.set_ylabel("gold")
            ax[1, 1].set_title("经济：tier / 金币")
            ax[1, 1].grid(alpha=.3)
            ax[1, 1].legend(fontsize=8)
            ax2.legend(fontsize=8)
        # death distribution
        h = qq.get("death_turn_hist") or {}
        if h:
            ks = sorted(int(k) for k in h)
            ax[1, 2].bar(ks, [h[str(k)] for k in ks], color="tab:orange")
            ax[1, 2].set_xlabel("出局回合")
            ax[1, 2].set_ylabel("games")
            ax[1, 2].set_title(f"出局回合（p50={qq.get('death_turn_p50')}, "
                               f"出局强度 p50={qq.get('death_strength_p50')}）")
            ax[1, 2].grid(alpha=.3)

    # 5) learning signals
    if rows:
        xs = [c for c in hist["cum"]]
        ent = [((r.get("ppo") or {}).get("epochs") or [{}])[0].get("entropy") for r in rows]
        kl = [((r.get("ppo") or {}).get("epochs") or [{}])[0].get("approx_kl") for r in rows]
        vl = [((r.get("ppo") or {}).get("epochs") or [{}])[0].get("value") for r in rows]
        sh = [(r.get("ppo") or {}).get("reward_shaping_mean") for r in rows]
        if any(v is not None for v in ent):
            ax[2, 0].plot(xs, ent, lw=.8, color="tab:green", label="entropy")
            ax[2, 0].set_xlabel("累计 decisions (M)")
            ax[2, 0].set_ylabel("entropy")
            ax[2, 0].set_title("策略熵")
            ax[2, 0].grid(alpha=.3)
        if any(v is not None for v in kl):
            ax[2, 1].plot(xs, kl, lw=.8, color="tab:olive", label="approx_kl")
            ax[2, 1].set_xlabel("累计 decisions (M)")
            ax[2, 1].set_ylabel("approx_kl")
            ax[2, 1].set_title("KL / 损失")
            ax[2, 1].grid(alpha=.3)
            if any(v is not None for v in vl):
                ax2 = ax[2, 1].twinx()
                ax2.plot(xs, vl, lw=.8, color="tab:cyan", alpha=.6, label="value loss")
                ax2.set_ylabel("value loss")
        if any(v is not None for v in sh):
            ax[2, 2].plot(xs, sh, lw=.8, color="tab:red", label="reward_shaping_mean")
            ax[2, 2].set_xlabel("累计 decisions (M)")
            ax[2, 2].set_ylabel("塑形奖励均值")
            ax[2, 2].set_title("稠密奖励（势函数塑形）")
            ax[2, 2].grid(alpha=.3)
        # pipeline gap
        n = max(20, min(60, len(rows) // 5 or 20))
        if len(rows) > n:
            cs = [st.median(hist["collect"][i - n:i]) for i in range(n, len(rows))]
            ps = [st.median(hist["ppo"][i - n:i]) for i in range(n, len(rows))]
            ax[0, 0].figure  # keep
        # put gap into the learning panel if empty
        if not any(v is not None for v in sh):
            ax[2, 2].plot(hist["cum"], hist["collect"], lw=.6, color="tab:blue", alpha=.5)
            ax[2, 2].plot(hist["cum"], hist["ppo"], lw=.6, color="tab:orange", alpha=.5)
            ax[2, 2].set_title("collect_s vs ppo_s")
            ax[2, 2].grid(alpha=.3)

    fig.suptitle(args.title or f"训练仪表盘：{args.run}", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=120)
    print("saved", args.out, "evals", len(evals), "iters", len(rows), "quality", len(q))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
