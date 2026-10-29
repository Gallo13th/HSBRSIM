#!/usr/bin/env python3
"""镜像快照难度探针：learner=指定 checkpoint（seat0），对手席位按 arm 注入
「我们自采的 EOT 快照」或保持引擎 bot，比较 learner 名次。

arm 0 : 全 bot
arm N : seat1..N 每回合开始注入 snapshot（来自 --snap-dir），其余 bot

用法::

  PYTHONPATH=rust/python:. python scripts/probe_mirror_strength.py \
      --checkpoint runs/champion_c0_2279.pt --device cuda:3 \
      --snap-dir runs/library/snaps_champ --games 60 --arms 0,2,3 \
      --seed 92001 --out runs/library/probe_mirror.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available  # noqa: E402
from hsbg.az.train.mirror_snapshots import (MirrorStats, inject_turn, load_pool,  # noqa: E402
                                            mirror_seats)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402


def _play(arm: int, game_seed: int, learner, pool, temperature: float, max_steps: int):
    import hsbg_engine as E
    game = E.Game(seed=int(game_seed))
    rng = random.Random(int(game_seed) + 13)
    stats = MirrorStats()
    seats = mirror_seats(arm) if (pool is not None and arm > 0) else []
    last_turn = -1
    steps = 0
    while not game.is_over() and steps < int(max_steps):
        if int(game.turn) != last_turn:
            last_turn = int(game.turn)
            if seats:
                inject_turn(game, pool, last_turn, seats=seats, p=1.0, rng=rng, stats=stats)
                if game.is_over():
                    break
        acted = False
        for p in range(8):
            if game.is_over() or not game.needs_action(p):
                continue
            acted = True
            if p == 0:
                game.step(0, int(learner.decide(game, 0).action))
            else:
                game.bot_play(int(p))
            steps += 1
            if game.is_over() or int(game.turn) != last_turn:
                break   # 回合已推进：先回到回合起点注入，再让剩余座位行动
        if not acted:
            break
    rank = int(list(game.placements())[0]) if game.is_over() else None
    return rank, steps, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/champion_c0_2279.pt")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--snap-dir", default="runs/library/snaps_champ")
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--arms", default="0,2,3")
    ap.add_argument("--seed", type=int, default=92001)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="runs/library/probe_mirror.json")
    args = ap.parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    evaluator = PPOEvaluator(model, device=args.device,
                             norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(args.seed), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps), temperature=float(args.temperature))
    learner = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=evaluator,
                                seed=int(args.seed), move_model=False)
    pool = load_pool(args.snap_dir)
    print(f"[probe] pool={args.snap_dir} frames={0 if pool is None else pool.frames}", flush=True)
    rows = []
    t0 = time.time()
    for arm in [int(x) for x in str(args.arms).split(",") if x.strip()]:
        ranks, steps_all = [], []
        agg = MirrorStats()
        for g in range(int(args.games)):
            learner.reset()
            r, st, ms = _play(arm, int(args.seed) + g, learner, pool,
                              float(args.temperature), int(args.max_steps))
            if r is not None:
                ranks.append(r)
            steps_all.append(st)
            for k in ("attempt", "applied", "rejected", "missing", "errors",
                      "pool_unbalanced", "pool_species_unbalanced"):
                setattr(agg, k, getattr(agg, k) + getattr(ms, k))
        row = {"arm": arm, "games": len(ranks)}
        if ranks:
            row.update({
                "mean_rank": round(float(np.mean(ranks)), 4),
                "top4": round(float(np.mean([x <= 4 for x in ranks])), 4),
                "win": round(float(np.mean([x == 1 for x in ranks])), 4),
                "mean_steps": round(float(np.mean(steps_all)), 1),
                "placements": ranks,
            })
        row["mirror"] = {k: getattr(agg, k) for k in
                         ("attempt", "applied", "rejected", "missing", "errors",
                          "pool_unbalanced", "pool_species_unbalanced")}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False)[:400], flush=True)
    base = next((r for r in rows if r["arm"] == 0 and r.get("games")), None)
    out = {"checkpoint": args.checkpoint, "snap_dir": args.snap_dir,
           "pool_frames": 0 if pool is None else int(pool.frames),
           "games_per_arm": int(args.games), "seed_base": int(args.seed),
           "elapsed_s": round(time.time() - t0, 1), "arms": rows,
           "delta_vs_arm0": {str(r["arm"]): (round(r["mean_rank"] - base["mean_rank"], 4)
                                            if base and r.get("games") else None)
                              for r in rows}}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"delta_vs_arm0": out["delta_vs_arm0"], "elapsed_s": out["elapsed_s"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
