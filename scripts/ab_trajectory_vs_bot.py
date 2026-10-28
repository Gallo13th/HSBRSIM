#!/usr/bin/env python3
"""离线对照 B vs C（PPAI 终审要求的决定性实验）：
同一批「中局入口状态」，learner 用同一个 checkpoint，
- B：对手全部由引擎 bot 继续（不回放）；
- C：对手优先回放轨迹里记录的动作（非法/缺记录 → bot 兜底）。

判据：同一入口、同一 learner、配对比较——C 若让 learner 的名次显著变差，
说明「轨迹回放」确实提供了更强的对手；否则这方案不值得投入。

用法::

  PYTHONPATH=rust/python:. python scripts/ab_trajectory_vs_bot.py \
      --checkpoint runs/champion_c0_2760.pt --device cuda:3 \
      --dir runs/library/traj_s3 --frames-per-traj 2 --seed 9001 \
      --out runs/library/ab_traj_vs_bot.json
"""

from __future__ import annotations

import argparse
import glob
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
from hsbg.az.train.trajectory_pool import ReplayScript  # noqa: E402


def _load_frames(root: str, per_traj: int):
    frames = []
    for path in sorted(glob.glob(os.path.join(root, "traj_*.json.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
        for fr in d["frames"][: int(per_traj)]:
            frames.append({"path": path, "traj": d, "frame": fr})
    return frames


def _play(fr, evaluator, rng, mode: str, learner_seat: int = 0, max_steps: int = 20000):
    import hsbg_engine as E
    g = E.Game.from_json(fr["frame"]["state"])
    if int(list(g.placements())[learner_seat]) != 0:
        return None
    script = ReplayScript(_TrajView(fr), learner_seat=learner_seat) if mode == "replay" else None
    steps = 0
    while not g.is_over() and steps < max_steps:
        acted = False
        for p in range(8):
            if not g.needs_action(p):
                continue
            acted = True
            if int(p) == learner_seat:
                f, c = obs_arrays(g.observe(p))
                mask = mask_from_bytes(g.legal_mask(p))
                logits, _v = evaluator.logits(f, c, mask)
                probs = masked_probs_np(logits[0], mask, 1.0)
                probs = probs / max(float(probs.sum()), 1e-12)
                a = int(rng.choice(probs.size, p=probs))
                g.step(int(p), int(a))
            else:
                done = False
                if script is not None:
                    a_rec = script.next_action(int(p), int(g.turn))
                    if a_rec is not None:
                        mq = mask_from_bytes(g.legal_mask(int(p)))
                        if 0 <= a_rec < 245 and bool(mq[a_rec]):
                            g.step(int(p), int(a_rec))
                            done = True
                if not done:
                    g.bot_play(int(p))
            steps += 1
            if g.is_over():
                break
        if not acted:
            break
    if not g.is_over():
        return None
    return int(list(g.placements())[learner_seat])


class _TrajView:
    """让 ReplayScript 能接受「单帧 + 全轨迹」的组合。"""

    def __init__(self, fr):
        self.frames = fr["traj"]["frames"]
        self.learner_seat = fr["traj"].get("learner_seat", 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--dir", default="runs/library/traj_s3")
    ap.add_argument("--frames-per-traj", type=int, default=2)
    ap.add_argument("--seed", type=int, default=9001)
    ap.add_argument("--max-frames", type=int, default=0, help="0=全部")
    ap.add_argument("--out", default="runs/library/ab_traj_vs_bot.json")
    args = ap.parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    evaluator = PPOEvaluator(model, device=args.device,
                             norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    frames = _load_frames(args.dir, args.frames_per_traj)
    if int(args.max_frames) > 0:
        frames = frames[: int(args.max_frames)]
    t0 = time.time()
    rows = []
    for i, fr in enumerate(frames):
        for mode in ("bot", "replay"):
            rng = np.random.default_rng(int(args.seed) + i)
            p = _play(fr, evaluator, rng, mode)
            rows.append({"frame": i, "mode": mode, "placement": p})
    bot = [r["placement"] for r in rows if r["mode"] == "bot" and r["placement"]]
    rep = [r["placement"] for r in rows if r["mode"] == "replay" and r["placement"]]
    pairs = {}
    for r in rows:
        if r["placement"]:
            pairs.setdefault(r["frame"], {})[r["mode"]] = r["placement"]
    diffs = [v["replay"] - v["bot"] for v in pairs.values() if "bot" in v and "replay" in v]
    rng = np.random.default_rng(0)
    boot = [float(np.mean(rng.choice(diffs, len(diffs)))) for _ in range(4000)] if diffs else []
    out = {
        "frames": len(frames), "games_bot": len(bot), "games_replay": len(rep),
        "bot_mean_rank": round(float(np.mean(bot)), 4) if bot else None,
        "replay_mean_rank": round(float(np.mean(rep)), 4) if rep else None,
        "bot_top4": round(float(np.mean([x <= 4 for x in bot])), 4) if bot else None,
        "replay_top4": round(float(np.mean([x <= 4 for x in rep])), 4) if rep else None,
        "paired_diff_replay_minus_bot": round(float(np.mean(diffs)), 4) if diffs else None,
        "paired_diff_ci95": [round(float(np.percentile(boot, 2.5)), 3),
                             round(float(np.percentile(boot, 97.5)), 3)] if boot else None,
        "elapsed_s": round(time.time() - t0, 1),
        "checkpoint": args.checkpoint, "dir": args.dir, "seed": int(args.seed),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": out, "rows": rows}, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
