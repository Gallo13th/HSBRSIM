#!/usr/bin/env python3
"""采集「对手场面轨迹」镜像库：8 个座位全部由指定 checkpoint 驱动（自对弈），
按 turn 记录**整局状态**与**每个座位的动作**，供训练时把强对手轨迹注入对局。

为什么记录整局状态而不是单座位状态：`Game.from_json(state)` 能精确恢复整局
（pool / eid / lobby_races 随状态一起回来），避免逐座位移植破坏引擎不变量。

产物格式（每局一个 gzip JSON）::

    {"seed": 123, "learner_seat": 0, "placements": [...],
     "frames": [{"turn": 8, "state": "<state_json>",
                 "actions": [[seat, action], ...]}, ...],
     "meta": {"checkpoint": "...", "temperature": 0.5, "rounds": ...}}

用法::

  PYTHONPATH=rust/python:. python scripts/capture_trajectory.py \
      --checkpoint runs/champion_c0_2760.pt --arch entity --device cuda:3 \
      --games 32 --from-turn 6 --out runs/library/traj
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, mask_from_bytes, obs_arrays  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, masked_probs_np  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--seed", type=int, default=810000)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--from-turn", type=int, default=6, help="从第几回合开始记录状态帧")
    ap.add_argument("--min-frames", type=int, default=2,
                    help="至少多少帧才保留这条轨迹")
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--max-actions-per-turn", type=int, default=40,
                    help="单座位单回合决策上限，超限强制 EndTurn（与训练一致，防 Play/Cancel 循环）")
    ap.add_argument("--out", default="runs/library/traj")
    args = ap.parse_args()

    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2
    import hsbg_engine as E

    os.makedirs(args.out, exist_ok=True)
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    evaluator = PPOEvaluator(model, device=args.device,
                             norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    rng = np.random.default_rng(int(args.seed))
    t0 = time.time()
    kept = 0
    for gi in range(int(args.games)):
        game = E.Game(seed=int(args.seed) + gi)
        frames, pending_actions = [], []
        cur_turn = int(game.turn)
        cur_state = game.state_json()          # 本回合「开始时刻」的状态
        turn_counts = {}
        steps = 0
        while not game.is_over() and steps < int(args.max_steps):
            acted = False
            for p in range(8):
                if not game.needs_action(p):
                    continue
                acted = True
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
                key = (int(p), int(game.turn))
                turn_counts[key] = turn_counts.get(key, 0) + 1
                limit = int(args.max_actions_per_turn)
                if limit > 0 and turn_counts[key] > limit and bool(mask[0]):
                    a = 0
                game.step(int(p), int(a))
                pending_actions.append([int(p), int(a)])
                steps += 1
                if game.is_over():
                    break
                now = int(game.turn)
                if now != cur_turn:
                    # 本回合结束：状态 = 本回合开始时刻，动作 = 本回合动作（严格配对）
                    frames.append({"turn": cur_turn, "state": cur_state,
                                   "actions": list(pending_actions)})
                    cur_turn, cur_state, pending_actions = now, game.state_json(), []
            if not acted:
                break
        if pending_actions:
            frames.append({"turn": cur_turn, "state": cur_state,
                           "actions": list(pending_actions)})
        frames = [fr for fr in frames if int(fr["turn"]) >= int(args.from_turn)]
        over = bool(game.is_over())
        if len(frames) < int(args.min_frames):
            if os.environ.get("CAPTURE_DEBUG"):
                print(f"[dbg] seed={args.seed+gi} over={over} steps={steps} "
                      f"frames={len(frames)}", flush=True)
            continue
        rec = {"seed": int(args.seed) + gi, "learner_seat": 0,
               "placements": list(game.placements()), "frames": frames,
               "meta": {"checkpoint": str(args.checkpoint),
                        "temperature": float(args.temperature), "steps": int(steps),
                        "truncated": bool(not over)}}
        path = os.path.join(args.out, f"traj_{int(args.seed) + gi:08d}.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        kept += 1
    print(json.dumps({"games": int(args.games), "kept": kept,
                      "elapsed_s": round(time.time() - t0, 1), "out": args.out},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
