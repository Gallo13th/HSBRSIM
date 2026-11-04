#!/usr/bin/env python3
"""Bot 对战局的强度曲线：模型（seat 0）vs 7 个引擎 bot，按**最终名次**分组。

用途：判断是否需要/如何给 bot 一个强度倍数（atk/hp 缩放），以及倍数取多少。

口径（训练配置）：
  - 8 席，seat 0 = 模型（PPOSelfPlayPolicy，`opponent="bot"`、`behavior="net"`），
    seat 1..7 = 引擎 bot；`game_config_json()` 与训练采集一致；无人类盘面注入。
  - 每个 turn 开始时记录每席盘面 Σ(atk+hp)、只数、tier、health、alive；
    局末记录 placement（1=冠军）。
输出：
  - JSON（每局每回合原始曲线 + 聚合）与 PNG（左：各名次 bot 曲线 + 模型曲线；
    右：模型/各名次 bot 的强度比与建议倍数）。

用法：
  PYTHONPATH=rust/python:. python scripts/bot_strength_curves.py \
    --checkpoint runs/az_stage300m_b01/eval/ckpt_080056141.pt \
    --device cuda:1 --games 32 --out runs/bot_curves/ckpt80m
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

import hsbg_engine as E  # noqa: E402

from hsbg.az.train.game_rules import game_config_json  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402

MODEL_SEAT = 0


def _strength(board) -> int:
    return sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in (board or []))


def _seat_snap(game, p: int) -> dict:
    pj = json.loads(game.player_json(int(p)))
    board = pj.get("board") or []
    return {
        "strength": _strength(board),
        "count": len(board),
        "tier": int(pj.get("tier") or 0),
        "health": int(pj.get("health") or 0),
        "alive": bool(pj.get("alive", True)),
    }


def play_one(seed: int, policy) -> dict:
    game = E.Game(int(seed), game_config_json())
    policy.reset()
    turns = []          # [{turn, seats:[snap]*8}]
    last_turn = -1
    steps = 0
    max_steps = 20000
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            turns.append({"turn": t, "seats": [_seat_snap(game, p) for p in range(8)]})
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == MODEL_SEAT:
                a = int(policy.decide(game, MODEL_SEAT).action)
                game.step(MODEL_SEAT, a)
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    placements = [int(x) for x in game.placements()]  # placements[seat] = rank
    # 局末再补一条（战斗后/终局的盘面）
    if game.is_over():
        turns.append({"turn": int(game.turn), "seats": [_seat_snap(game, p) for p in range(8)]})
    return {"seed": int(seed), "ok": bool(game.is_over()), "steps": steps,
            "placements": placements, "turns": turns}


def _median(vals):
    return float(st.median(vals)) if vals else None


def aggregate(games):
    ok = [g for g in games if g.get("ok")]
    # 按最终名次分组（只取 bot；排除模型 seat）
    by_rank = {r: [] for r in range(1, 9)}   # rank -> [(turn -> strength) per game]
    for g in ok:
        pl = g["placements"]
        for s in range(8):
            if s == MODEL_SEAT:
                continue
            r = pl[s]
            series = {}
            for row in g["turns"]:
                snap = row["seats"][s]
                if snap["alive"]:
                    series[int(row["turn"])] = snap["strength"]
            by_rank[r].append(series)
    model = []
    for g in ok:
        series = {}
        for row in g["turns"]:
            snap = row["seats"][MODEL_SEAT]
            if snap["alive"]:
                series[int(row["turn"])] = snap["strength"]
        model.append({"rank": g["placements"][MODEL_SEAT], "series": series})

    def curve(series_list, tmax=20):
        out = {}
        for t in range(0, tmax + 1):
            vals = [s.get(t) for s in series_list if t in s]
            if vals:
                out[t] = {"median": _median(vals), "mean": float(st.mean(vals)),
                          "n": len(vals)}
        return out

    bot_curves = {r: curve(v) for r, v in by_rank.items()}
    model_curve = curve([m["series"] for m in model])
    ratio = {}
    for t in range(0, 21):
        m = model_curve.get(t, {}).get("median")
        b1 = bot_curves[1].get(t, {}).get("median")
        b4 = bot_curves[4].get(t, {}).get("median")
        b8 = bot_curves[8].get(t, {}).get("median")
        ratio[t] = {
            "model_over_rank1": (m / b1) if (m and b1) else None,
            "model_over_rank4": (m / b4) if (m and b4) else None,
            "model_over_rank8": (m / b8) if (m and b8) else None,
        }
    return {"ok": len(ok), "bot_curves": bot_curves, "model_curve": model_curve,
            "ratio": ratio, "model_rank_counts": _counts([m["rank"] for m in model]),
            "bot_rank_counts": _counts([r for r in range(1, 9) for _ in by_rank[r]])}


def _counts(xs):
    d = {}
    for x in xs:
        d[int(x)] = d.get(int(x), 0) + 1
    return dict(sorted(d.items()))


def plot(agg, out_png, checkpoint):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 图内文字用英文，显式用 DejaVu Sans，避免缺中文字体刷 findfont 警告。
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))
    ax = axes[0]
    cmap = plt.get_cmap("viridis")
    for r in range(1, 9):
        c = agg["bot_curves"][r]
        xs = sorted(c)
        ys = [c[t]["median"] for t in xs]
        ax.plot(xs, ys, "-", lw=1.2, alpha=0.85, color=cmap((r - 1) / 7.0),
                label=f"bot rank {r}")
    mc = agg["model_curve"]
    xs = sorted(mc)
    ax.plot(xs, [mc[t]["median"] for t in xs], "-", lw=3.0, color="tab:red",
            label="model (seat 0)")
    ax.set_xlabel("turn")
    ax.set_ylabel("board strength  Σ(atk+hp)")
    ax.set_title("Bot strength by final placement vs model")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, ncol=2)

    ax = axes[1]
    rs = sorted(agg["ratio"])
    for key, lab in (("model_over_rank1", "model / bot-rank1"),
                     ("model_over_rank4", "model / bot-rank4"),
                     ("model_over_rank8", "model / bot-rank8")):
        ax.plot(rs, [agg["ratio"][t][key] for t in rs], "-o", ms=2.5, lw=1.4, label=lab)
    ax.axhline(1.5, color="gray", ls=":", lw=1)
    ax.axhline(2.0, color="gray", ls="--", lw=1)
    ax.axhline(3.0, color="gray", ls="-.", lw=1)
    ax.set_xlabel("turn")
    ax.set_ylabel("strength ratio")
    ax.set_title("Model / bot strength ratio (suggested multiplier k)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)

    fig.suptitle(f"bot-match strength curves — {os.path.basename(os.path.dirname(checkpoint))}"
                 f"/{os.path.basename(checkpoint)}  games={agg['ok']}", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    os.makedirs(os.path.dirname(os.path.abspath(out_png)) or ".", exist_ok=True)
    fig.savefig(out_png, dpi=140)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--games", type=int, default=32)
    ap.add_argument("--seed-base", type=int, default=830000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="runs/bot_curves/ckpt")
    args = ap.parse_args(argv)

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps), move_guard=True,
                        move_cap=3, move_repeat_limit=2)
    policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                               seed=int(args.seed_base), move_model=False)

    games = []
    for i in range(int(args.games)):
        games.append(play_one(int(args.seed_base) + i, policy))
        if (i + 1) % 8 == 0:
            print(f"[bot-curves] {i + 1}/{args.games}", flush=True)

    agg = aggregate(games)
    out_json = args.out + ".json"
    out_png = args.out + ".png"
    os.makedirs(os.path.dirname(os.path.abspath(out_json)) or ".", exist_ok=True)
    json.dump({"checkpoint": args.checkpoint, "games": args.games, "agg": agg,
               "raw": games}, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    plot(agg, out_png, args.checkpoint)

    print(f"\n[bot-curves] games={agg['ok']} model_rank_counts={agg['model_rank_counts']}")
    print("turn | " + " | ".join(f"bot{r}" for r in range(1, 9)) + " | model | k(model/r1)")
    for t in (6, 8, 10, 12, 15):
        row = [agg["bot_curves"][r].get(t, {}).get("median") for r in range(1, 9)]
        m = agg["model_curve"].get(t, {}).get("median")
        k = agg["ratio"].get(t, {}).get("model_over_rank1")
        print(f"{t:4d} | " + " | ".join("—" if v is None else f"{v:6.0f}" for v in row)
              + f" | {('—' if m is None else f'{m:6.0f}')} | {('—' if k is None else f'{k:4.2f}')}")
    print(f"[out] {out_json}\n[out] {out_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
