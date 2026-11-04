#!/usr/bin/env python3
"""Bot 对局加权评估：长度 + **bot 强度**（只用于面对 bot 的对局）。

输入是 ``scripts/bot_strength_curves.py`` 产出的 JSON（8 席：seat0=模型，1..7=bot）。
对每局：
  turns   = 局末最大回合数
  strength= 局末 bot 席（1..7，最后存活快照）最强盘面 Σ(atk+hp)
  w       = game_weights(turns, strength, alpha=beta=0.5)（均值 1）
报告：
  - 未加权 / 加权 的 mean_rank、top4、win；
  - 「长且强」子集（权重 top 25%）的 win / mean_rank；
  - 「强 bot」子集（bot 强度 top 25%）与「长局」子集（turns top 25%）的 win/rank。

用法：
  python scripts/bot_weighted_eval.py --json s73=runs/bot_curves/s73.json ... [--out ...]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hsbg.eval.metrics import game_weights  # noqa: E402


def last_alive(game):
    out = [None] * 8
    for row in game["turns"]:
        for s in range(8):
            if row["seats"][s]["alive"]:
                out[s] = row["seats"][s]
    return out


def rows_of(path):
    d = json.load(open(path))
    out = []
    for g in d["raw"]:
        if not g.get("ok"):
            continue
        la = last_alive(g)
        bots = [la[s]["strength"] for s in range(1, 8) if la[s] is not None]
        if la[0] is None or not bots:
            continue
        turns = max((int(x["turn"]) for x in g["turns"]), default=0)
        out.append({"rank": int(g["placements"][0]), "turns": turns,
                    "bot_strength": float(max(bots))})
    return out


def _mean(xs):
    return st.fmean(xs) if xs else float("nan")


def summary(rows, subset=None):
    rs = [r for r in rows if subset is None or subset(r)]
    ranks = [r["rank"] for r in rs]
    if not ranks:
        return {"n": 0, "win": None, "rank": None}
    return {"n": len(ranks), "win": sum(1 for x in ranks if x == 1) / len(ranks),
            "rank": _mean(ranks)}


def weighted_summary(rows):
    w = game_weights([r["turns"] for r in rows], [r["bot_strength"] for r in rows])
    sw = sum(w)
    ranks = [r["rank"] for r in rows]
    wins = [1.0 if r == 1 else 0.0 for r in ranks]
    top4 = [1.0 if r <= 4 else 0.0 for r in ranks]
    return {"win": sum(a * b for a, b in zip(wins, w)) / sw,
            "rank": sum(a * b for a, b in zip(ranks, w)) / sw,
            "top4": sum(a * b for a, b in zip(top4, w)) / sw,
            "n_eff": (sw * sw) / sum(x * x for x in w),
            "weight_min": min(w), "weight_max": max(w)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="append", required=True,
                    help="label=path（可重复）")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    print(f"{'ckpt':6s} {'n':4s} {'win':6s} {'rank':6s} "
          f"{'w_win':7s} {'w_rank':7s} {'w_n_eff':8s} "
          f"{'LS n':5s} {'LS win':7s} {'LS rank':8s} {'strongwin':10s} {'longwin':9s}")
    out = {}
    for item in args.json:
        label, path = item.split("=", 1)
        rows = rows_of(path)
        if not rows:
            continue
        base = summary(rows)
        w = weighted_summary(rows)
        # 长且强：turns / bot_strength 百分位之和 top 25%
        turns_sorted = sorted(r["turns"] for r in rows)
        str_sorted = sorted(r["bot_strength"] for r in rows)
        tcut = turns_sorted[int(0.75 * (len(turns_sorted) - 1))]
        scut = str_sorted[int(0.75 * (len(str_sorted) - 1))]
        ls = summary(rows, lambda r: r["turns"] >= tcut and r["bot_strength"] >= scut)
        strong = summary(rows, lambda r: r["bot_strength"] >= scut)
        long_ = summary(rows, lambda r: r["turns"] >= tcut)
        out[label] = {"n": len(rows), "base": base, "weighted": w,
                      "long_strong": ls, "strong_bot": strong, "long_turns": long_,
                      "cuts": {"turns": tcut, "bot_strength": scut}}
        print(f"{label:6s} {len(rows):4d} {base['win']:6.3f} {base['rank']:6.3f} "
              f"{w['win']:7.3f} {w['rank']:7.3f} {w['n_eff']:8.1f} "
              f"{ls['n']:5d} {ls['win'] if ls['win'] is not None else float('nan'):7.3f} "
              f"{ls['rank'] if ls['rank'] is not None else float('nan'):8.3f} "
              f"{strong['win']:10.3f} {long_['win']:9.3f}")
    if args.out:
        json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=1)
        print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
