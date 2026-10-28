#!/usr/bin/env python3
"""采集镜像对手库：用指定 checkpoint 打 N 局，按 turn 抓取「最终名次靠前」的座位完整状态。

与训练解耦：可以在训练跑着的时候另跑（用不同的空闲卡），产出的 JSONL 由
`hsbg/az/train/library_pool.LibraryPool` 读取，供 `--library-pool` 混入训练。

用法::

  PYTHONPATH=rust/python:. python scripts/capture_library.py \
      --checkpoint runs/az_entity_s3/model.pt --arch entity --device cuda:3 \
      --games 128 --turns 8,10,12,15,18 --max-placement 2 \
      --out runs/az_entity_s3/library/pool.jsonl
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
from hsbg.az.train.library_pool import (LibraryEntry, LibraryPool,  # noqa: E402
                                        board_strength)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, masked_probs_np  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=64)
    ap.add_argument("--seed", type=int, default=710000)
    ap.add_argument("--learner-seat", type=int, default=0)
    ap.add_argument("--turns", default="8,10,12,15,18")
    ap.add_argument("--max-placement", type=int, default=2,
                    help="被采集座位的最终名次上限")
    ap.add_argument("--min-learner-placement", type=int, default=0,
                    help="要求 learner 的最终名次 >= 该值（例如 5 = 只收「赢了我们」的对局）")
    ap.add_argument("--min-turn", type=int, default=8)
    ap.add_argument("--min-board", type=int, default=4)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="runs/library/pool.jsonl")
    args = ap.parse_args()

    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2
    import hsbg_engine as E

    turns = {int(t) for t in str(args.turns).split(",") if t.strip()}
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    evaluator = PPOEvaluator(model, device=args.device,
                             norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    rng = np.random.default_rng(int(args.seed))
    pool = LibraryPool(path=None, min_turn=args.min_turn,
                       max_placement=args.max_placement, min_board=args.min_board)
    pool.path = args.out
    n_games = 0
    n_captured = 0
    t0 = time.time()
    for gi in range(int(args.games)):
        game = E.Game(seed=int(args.seed) + gi)
        captured = {}   # (seat, turn) -> player json
        steps = 0
        while not game.is_over() and steps < int(args.max_steps):
            acted = False
            for p in range(8):
                if not game.needs_action(p):
                    continue
                acted = True
                if int(p) == int(args.learner_seat):
                    f, c = obs_arrays(game.observe(p))
                    mask = mask_from_bytes(game.legal_mask(p))
                    logits, _v = evaluator.logits(f, c, mask)
                    probs = masked_probs_np(logits[0], mask, float(args.temperature))
                    legal = np.flatnonzero(mask)
                    if legal.size == 0:
                        a = 0
                    else:
                        probs = probs / max(float(probs.sum()), 1e-12)
                        a = int(rng.choice(probs.size, p=probs))
                    game.step(int(p), int(a))
                else:
                    turn_now = int(game.turn)
                    if turn_now in turns and (int(p), turn_now) not in captured:
                        captured[(int(p), turn_now)] = game.player_json(int(p))
                    game.bot_play(int(p))
                steps += 1
                if game.is_over():
                    break
            if not acted:
                break
        n_games += 1
        if not game.is_over():
            continue
        placements = list(game.placements())
        if int(args.min_learner_placement) > 0 and \
                int(placements[int(args.learner_seat)]) < int(args.min_learner_placement):
            continue
        for (seat, turn), pj in captured.items():
            if int(placements[seat]) > int(args.max_placement):
                continue
            player = json.loads(pj)
            entry = LibraryEntry(player=player, turn=int(turn),
                                 placement=int(placements[seat]),
                                 strength=board_strength(player),
                                 checkpoint=str(args.checkpoint), source="capture",
                                 created_iter=gi, game_seed=int(args.seed) + gi, seat=int(seat))
            if pool.add(entry):
                n_captured += 1
    if n_captured:
        pool.save(args.out)
    print(json.dumps({"games": n_games, "captured": n_captured,
                      "elapsed_s": round(time.time() - t0, 1),
                      "pool": pool.stats(), "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
