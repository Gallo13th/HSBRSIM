#!/usr/bin/env python3
"""阶段 1a 难度探针：冻结对手模型到底是不是更强？

learner = 指定 checkpoint（默认新冠军），seat0；其余座位按 arm 配置：
  arm 0 : 7 个引擎 bot
  arm N : seat1..N 由**冻结的同一 checkpoint** 驱动，其余 bot
同一批 game seed、同一采样温度；统计 learner 的最终名次/前四/吃鸡/每组决策数。

用法::

  PYTHONPATH=rust/python:. python scripts/probe_frozen_strength.py \
      --checkpoint runs/champion_c0_2279.pt --device cuda:2 \
      --games 60 --arms 0,1,2 --seed 91001 --out runs/library/probe_frozen.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, mask_from_bytes, obs_arrays  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import (CollectConfig, PPOEvaluator, PPOSelfPlayPolicy,  # noqa: E402
                               masked_probs_np)


def _play(arm: int, game_seed: int, learner, frozen, temperature: float, max_steps: int):
    import hsbg_engine as E
    game = E.Game(seed=int(game_seed))
    steps = 0
    while not game.is_over() and steps < int(max_steps):
        acted = False
        for p in range(8):
            if not game.needs_action(p):
                continue
            acted = True
            if p == 0:
                a = int(learner.decide(game, 0).action)
                game.step(0, a)
            elif frozen is not None and p <= arm:
                a = int(frozen.decide(game, int(p)).action)
                mq = mask_from_bytes(game.legal_mask(int(p)))
                if not (0 <= a < 245 and bool(mq[a])):
                    game.bot_play(int(p))
                else:
                    game.step(int(p), a)
            else:
                game.bot_play(int(p))
            steps += 1
            if game.is_over():
                break
        if not acted:
            break
    if not game.is_over():
        return None, steps
    return int(list(game.placements())[0]), steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/champion_c0_2279.pt")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--arms", default="0,1,2")
    ap.add_argument("--seed", type=int, default=91001)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="runs/library/probe_frozen.json")
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
    frozen = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=evaluator,
                               seed=int(args.seed) + 7, move_model=False)
    arms = [int(x) for x in str(args.arms).split(",") if x.strip()]
    rows = []
    t0 = time.time()
    for arm in arms:
        ranks, steps_all = [], []
        for g in range(int(args.games)):
            learner.reset()
            frozen.reset()
            r, st = _play(arm, int(args.seed) + g, learner, frozen if arm > 0 else None,
                          float(args.temperature), int(args.max_steps))
            if r is not None:
                ranks.append(r)
            steps_all.append(st)
        if not ranks:
            rows.append({"arm": arm, "games": 0, "error": "no completed games"})
            continue
        rows.append({
            "arm": arm, "games": len(ranks),
            "mean_rank": round(float(np.mean(ranks)), 4),
            "top4": round(float(np.mean([x <= 4 for x in ranks])), 4),
            "win": round(float(np.mean([x == 1 for x in ranks])), 4),
            "mean_steps": round(float(np.mean(steps_all)), 1),
            "placements": ranks,
        })
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    base = next((r for r in rows if r["arm"] == 0 and r.get("games")), None)
    out = {"checkpoint": args.checkpoint, "games_per_arm": int(args.games),
           "seed_base": int(args.seed), "temperature": float(args.temperature),
           "elapsed_s": round(time.time() - t0, 1), "arms": rows,
           "delta_vs_arm0": {str(r["arm"]): (round(r["mean_rank"] - base["mean_rank"], 4)
                                            if base and r.get("games") else None)
                              for r in rows}}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: out[k] for k in ("delta_vs_arm0", "elapsed_s")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
