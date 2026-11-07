#!/usr/bin/env python3
"""双模型对战评测（head-to-head）：A、B 各占一个座位，其余 6 席引擎 bot。

口径：
- 8 席对局；A/B 座位**按 seed 奇偶对调**（A=0,B=1 或 A=1,B=0），抵消座位/先手偏差；
- 其余 6 席 `bot_play`；`game_config_json()` 与训练/评测一致（因此
  `HSBRSIM_BAN_TRINKETS` 若已设置则自动生效，例如禁用「加重护手」）；
- 指标：各自 mean rank / top4 / 吃鸡率、**同局配对**的胜负（谁的名次更靠前）、
  配对名次差及其标准误、胜率二项检验，以及终局盘面强度/tavern tier。

用法：
  HSBRSIM_BAN_TRINKETS=BG36_MagicItem_414 PYTHONPATH=rust/python:. \
  python scripts/h2h_eval.py \
    --ckpt-a runs/az_stage300m_b07/eval/ckpt_250026300.pt \
    --ckpt-b runs/external/collab_model.pt \
    --games 128 --device cuda:7 --out runs/h2h/b07_250m_vs_collab
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

import hsbg_engine as E  # noqa: E402

from hsbg.az.train.game_rules import game_config_json  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402


def _build(ckpt: str, device: str, seed: int):
    model, meta = load_checkpoint(ckpt, device=device)
    ev = PPOEvaluator(model, device=device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(seed), opponent="bot", behavior="net",
                        max_steps=20000, move_guard=True, move_cap=3, move_repeat_limit=2)
    pol = PPOSelfPlayPolicy(model, device=device, config=cfg, eval_fn=ev,
                            seed=int(seed), move_model=False)
    return pol, meta


def _summ(pj: dict) -> dict:
    board = pj.get("board") or []
    return {
        "tier": int(pj.get("tier") or 0),
        "health": int(pj.get("health") or 0),
        "strength": sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in board),
        "units": len(board),
        "trinkets": [int(x) for x in (pj.get("trinkets") or [])],
    }


def play_one(seed: int, pol_a, pol_b, max_steps: int = 20000) -> dict:
    game = E.Game(int(seed), game_config_json())
    pol_a.reset()
    pol_b.reset()
    # 按 seed 奇偶交换座位，抵消座位偏差
    if int(seed) % 2 == 0:
        seat_a, seat_b = 0, 1
    else:
        seat_a, seat_b = 1, 0
    steps = 0
    while not game.is_over() and steps < max_steps:
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == seat_a:
                game.step(p, int(pol_a.decide(game, p).action))
            elif p == seat_b:
                game.step(p, int(pol_b.decide(game, p).action))
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    placements = [int(x) for x in game.placements()]
    return {
        "seed": int(seed),
        "ok": bool(game.is_over()),
        "turn": int(game.turn),
        "seat_a": int(seat_a),
        "seat_b": int(seat_b),
        "rank_a": int(placements[seat_a]),
        "rank_b": int(placements[seat_b]),
        "a": _summ(json.loads(game.player_json(seat_a))),
        "b": _summ(json.loads(game.player_json(seat_b))),
        "placements": placements,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt-a", required=True)
    ap.add_argument("--ckpt-b", required=True)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--games", type=int, default=128)
    ap.add_argument("--seed-base", type=int, default=900000)
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="runs/h2h/match")
    args = ap.parse_args(argv)

    pol_a, meta_a = _build(args.ckpt_a, args.device, args.seed_base)
    pol_b, meta_b = _build(args.ckpt_b, args.device, args.seed_base + 1)

    games = []
    for i in range(int(args.games)):
        games.append(play_one(int(args.seed_base) + i, pol_a, pol_b,
                              max_steps=int(args.max_steps)))
        if (i + 1) % 16 == 0:
            ra = [g["rank_a"] for g in games]
            rb = [g["rank_b"] for g in games]
            print(f"[h2h] {i + 1}/{args.games}  mean_rank A={st.mean(ra):.3f} "
                  f"B={st.mean(rb):.3f}", flush=True)

    ok = [g for g in games if g["ok"]]
    ra = [g["rank_a"] for g in ok]
    rb = [g["rank_b"] for g in ok]
    diffs = [g["rank_a"] - g["rank_b"] for g in ok]      # <0 = A 更好
    wins_a = sum(1 for d in diffs if d < 0)
    ties = sum(1 for d in diffs if d == 0)
    n = max(1, len(ok))
    se_diff = st.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else float("nan")
    # 二项检验（对半胜率，忽略平局）
    m = wins_a + (len(diffs) - wins_a - ties)
    z = ((wins_a - m / 2) / math.sqrt(m / 4)) if m > 0 else float("nan")
    res = {
        "ckpt_a": args.ckpt_a, "ckpt_b": args.ckpt_b,
        "label_a": args.label_a, "label_b": args.label_b,
        "games": int(args.games), "ok": len(ok),
        "ban_env": (os.environ.get("HSBRSIM_BAN_TRINKETS", "") or "").strip(),
        "meta_a_trainer_updates": (meta_a or {}).get("trainer_updates"),
        "meta_b_trainer_updates": (meta_b or {}).get("trainer_updates"),
        "a": {
            "mean_rank": st.mean(ra),
            "top4": sum(1 for r in ra if r <= 4) / n,
            "win": sum(1 for r in ra if r == 1) / n,
            "placement_counts": {str(k): ra.count(k) for k in range(1, 9)},
            "median_strength": st.median([g["a"]["strength"] for g in ok]),
            "median_tier": st.median([g["a"]["tier"] for g in ok]),
        },
        "b": {
            "mean_rank": st.mean(rb),
            "top4": sum(1 for r in rb if r <= 4) / n,
            "win": sum(1 for r in rb if r == 1) / n,
            "placement_counts": {str(k): rb.count(k) for k in range(1, 9)},
            "median_strength": st.median([g["b"]["strength"] for g in ok]),
            "median_tier": st.median([g["b"]["tier"] for g in ok]),
        },
        "head_to_head": {
            "a_better": wins_a, "b_better": len(diffs) - wins_a - ties, "ties": ties,
            "a_win_rate": wins_a / max(1, m),
            "mean_rank_diff_ab": st.mean(diffs),
            "se_rank_diff": se_diff,
            "z_binom": z,
            "p_two_sided_approx": (2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
                                   if not math.isnan(z) else None),
        },
        "raw": games,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(res, open(args.out + ".json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    A, B, H = res["a"], res["b"], res["head_to_head"]
    print(f"\n=== {args.label_a} vs {args.label_b}（{len(ok)}/{args.games} 局，"
          f"ban={res['ban_env'] or '无'}）===")
    print(f"{args.label_a}: mean_rank={A['mean_rank']:.3f} top4={100*A['top4']:.0f}% "
          f"1st={100*A['win']:.0f}%  强度中位={A['median_strength']:.0f} tier中位={A['median_tier']:.0f}")
    print(f"{args.label_b}: mean_rank={B['mean_rank']:.3f} top4={100*B['top4']:.0f}% "
          f"1st={100*B['win']:.0f}%  强度中位={B['median_strength']:.0f} tier中位={B['median_tier']:.0f}")
    print(f"同局配对: {args.label_a} 更好 {H['a_better']} 局 / {args.label_b} 更好 "
          f"{H['b_better']} 局 / 平 {H['ties']}  ⇒ {args.label_a} 胜率 {100*H['a_win_rate']:.1f}% "
          f"(z={H['z_binom']:.2f}, p≈{H['p_two_sided_approx']:.3f})")
    print(f"配对名次差 (A−B) = {H['mean_rank_diff_ab']:+.3f} ± {H['se_rank_diff']:.3f} (SE)")
    print(f"[out] {args.out}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
