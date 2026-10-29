#!/usr/bin/env python3
"""采集「对手场面轨迹」镜像库：8 个座位全部由指定 checkpoint（或引擎 bot）驱动，
按 turn 记录**整局状态**与**每个座位的动作**，供训练时把强对手轨迹注入对局。

为什么记录整局状态而不是单座位状态：`Game.from_json(state)` 能精确恢复整局
（pool / eid / lobby_races 随状态一起回来），避免逐座位移植破坏引擎不变量。

两条产物：

1. **整局轨迹**（默认）：``traj_*.json.gz``，训练侧 ``--trajectory-pool/--trajectory-p``
   用它做「整局状态恢复 + 逐动作回放」；
2. **回合末场面快照**（``--emit-snapshots``）：``snap_*.json.gz``，训练侧
   ``--mirror-snaps/--mirror-seats/--mirror-p`` 用它做「回合末场面镜像对手」：
   每回合结束（EOT 完成、combat 之前）记录 ``(turn, seat, player_json, held_pool_parts)``，
   注入走引擎 ``Game.apply_turn_snapshots``（设计见 ``docs/MIRROR_SNAPSHOT_DESIGN.md``，
   文件 schema 见 ``hsbg/az/train/mirror_snapshots.py``）。

产物格式（每局一个 gzip JSON）::

    {"seed": 123, "learner_seat": 0, "placements": [...],
     "frames": [{"turn": 8, "state": "<state_json>",
                 "actions": [[seat, action], ...]}, ...],
     "meta": {"checkpoint": "...", "temperature": 0.5, "rounds": ...}}

用法::

  # checkpoint 驱动（需要 torch）
  PYTHONPATH=rust/python:. python scripts/capture_trajectory.py \
      --checkpoint runs/champion_c0_2760.pt --arch entity --device cuda:3 \
      --games 32 --from-turn 6 --out runs/library/traj

  # 引擎 bot 驱动 + 采集回合末快照（CPU、无 torch，用于 schema 冒烟/冷启动）
  PYTHONPATH=rust/python:. python scripts/capture_trajectory.py \
      --driver bot --games 1 --from-turn 1 --emit-snapshots 1 \
      --out runs/library/traj_smoke
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
from hsbg.az.train.mirror_snapshots import (capture_eot, engine_stamp,  # noqa: E402
                                            write_snapshot_file)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", default="model", choices=["model", "bot"],
                    help="model=checkpoint 驱动（需要 torch）；bot=引擎 bot 驱动（CPU，"
                         "无 torch；决策确定性、仅用于冒烟/冷启动数据）")
    ap.add_argument("--checkpoint", default="", help="（driver=model 必填）checkpoint 路径")
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
    ap.add_argument("--emit-snapshots", type=int, default=0,
                    help="1=额外采集回合末场面快照 snap_*.json.gz（默认关）")
    ap.add_argument("--snap-dir", default="",
                    help="快照目录（默认 <out>/snapshots）")
    ap.add_argument("--snap-from-turn", type=int, default=-1,
                    help="从第几回合开始采快照（-1 跟随 --from-turn）")
    ap.add_argument("--snap-min-board", type=int, default=1,
                    help="牌面至少几只随从才记录快照（1=空场面不记）")
    ap.add_argument("--out", default="runs/library/traj")
    args = ap.parse_args()

    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2
    import hsbg_engine as E

    driver = str(args.driver)
    emit = bool(int(args.emit_snapshots))
    snap_from = int(args.snap_from_turn) if int(args.snap_from_turn) >= 0 else int(args.from_turn)
    snap_dir = str(args.snap_dir) or os.path.join(str(args.out), "snapshots")
    os.makedirs(args.out, exist_ok=True)
    if emit:
        os.makedirs(snap_dir, exist_ok=True)

    evaluator = None
    model = None
    meta: dict = {}
    if driver == "model":
        if not str(args.checkpoint):
            print("[error] --driver model 需要 --checkpoint", file=sys.stderr)
            return 2
        from hsbg.az.train.model import load_checkpoint
        from hsbg.az.train.ppo import PPOEvaluator, masked_probs_np

        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        evaluator = PPOEvaluator(model, device=args.device,
                                 norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))

    rng = np.random.default_rng(int(args.seed))
    t0 = time.time()
    kept = 0
    snap_files = snap_frames = snap_skipped = 0
    for gi in range(int(args.games)):
        seed_i = int(args.seed) + gi
        game = E.Game(seed=seed_i)
        frames, pending_actions = [], []
        snaps = []
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
                mask = mask_from_bytes(game.legal_mask(p))
                if driver == "model":
                    f, c = obs_arrays(game.observe(p))
                    logits, _v = evaluator.logits(f, c, mask)
                    probs = masked_probs_np(logits[0], mask, float(args.temperature))
                    legal = np.flatnonzero(mask)
                    if legal.size == 0:
                        a = 0
                    else:
                        probs = probs / max(float(probs.sum()), 1e-12)
                        a = int(rng.choice(probs.size, p=probs))
                else:
                    a = int(game.bot_action(p))
                key = (int(p), int(game.turn))
                turn_counts[key] = turn_counts.get(key, 0) + 1
                limit = int(args.max_actions_per_turn)
                end_turn = bool(mask[0]) and int(a) == 0
                if limit > 0 and turn_counts[key] > limit and bool(mask[0]):
                    a = 0
                    end_turn = True
                # 回合末场面快照：本座位 EndTurn 之后、combat 之前（clone 内阻止推进）。
                if emit and end_turn and int(game.turn) >= snap_from:
                    fr = capture_eot(game, int(p), action=0)
                    if fr is None or len(fr["player"].get("board") or []) < int(args.snap_min_board):
                        snap_skipped += 1
                    else:
                        fr["source_game_seed"] = int(seed_i)
                        snaps.append(fr)
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
        if emit and snaps:
            path = os.path.join(snap_dir, f"snap_{seed_i:08d}.json.gz")
            write_snapshot_file(
                path, snaps, seed=seed_i, learner_seat=0,
                engine=engine_stamp(),
                meta={"checkpoint": str(args.checkpoint), "driver": driver,
                      "temperature": float(args.temperature), "from_turn": int(snap_from),
                      "min_board": int(args.snap_min_board), "games": int(args.games),
                      "turns": sorted({int(fr["turn"]) for fr in snaps})})
            snap_files += 1
            snap_frames += len(snaps)
        frames = [fr for fr in frames if int(fr["turn"]) >= int(args.from_turn)]
        over = bool(game.is_over())
        if len(frames) < int(args.min_frames):
            if os.environ.get("CAPTURE_DEBUG"):
                print(f"[dbg] seed={args.seed+gi} over={over} steps={steps} "
                      f"frames={len(frames)}", flush=True)
            continue
        rec = {"seed": int(args.seed) + gi, "learner_seat": 0,
               "placements": list(game.placements()), "frames": frames,
               "meta": {"checkpoint": str(args.checkpoint), "driver": driver,
                        "temperature": float(args.temperature), "steps": int(steps),
                        "truncated": bool(not over),
                        "snapshots": int(len(snaps)) if emit else 0}}
        path = os.path.join(args.out, f"traj_{int(args.seed) + gi:08d}.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        kept += 1
    out = {"games": int(args.games), "kept": kept, "driver": driver,
           "elapsed_s": round(time.time() - t0, 1), "out": args.out}
    if emit:
        out.update({"emit_snapshots": 1, "snap_dir": snap_dir,
                    "snap_files": int(snap_files), "snap_frames": int(snap_frames),
                    "snap_skipped": int(snap_skipped)})
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
