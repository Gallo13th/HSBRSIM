#!/usr/bin/env python3
"""进程级 actor pool 资源扫描（4 GPU 原型）。

示例：
  CUDA_VISIBLE_DEVICES=0,1,2,3 python scripts/bench_process_pool.py \
    --checkpoint /tmp/entity_bc500k/model.pt --processes 4 --gpus 0,1,2,3 \
    --games 64 --sims 4 --minutes 30 --out runs/bench/process_4gpu_30min.json

注意：每轮 pool 会 spawn 进程并重新加载 checkpoint；这是资源扫描，不是长训练。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.ppo import CollectConfig  # noqa: E402
from hsbg.az.train.process_pool import ProcessActorPool  # noqa: E402


def _gpu_stats() -> List[Dict[str, int]]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"], text=True, timeout=5)
        rows = []
        for line in out.strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            rows.append({"index": int(p[0]), "util": int(p[1]), "mem_mb": int(p[2])})
        return rows
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--processes", type=int, default=4)
    ap.add_argument("--gpus", default="0,1,2,3")
    ap.add_argument("--games", type=int, default=64, help="每轮总 games")
    ap.add_argument("--sims", type=int, default=4)
    ap.add_argument("--determinizations", type=int, default=1)
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--max-steps", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs/bench/process_pool.json")
    args = ap.parse_args()
    gpus = [int(x) for x in str(args.gpus).split(",") if x.strip()]
    pool = ProcessActorPool(int(args.processes), gpus, args.checkpoint,
                            sims=int(args.sims),
                            determinizations=int(args.determinizations),
                            seed=int(args.seed))
    t0 = time.time()
    deadline = t0 + float(args.minutes) * 60.0
    rounds: List[Dict[str, Any]] = []
    while time.time() < deadline:
        r0 = time.time()
        try:
            batch, meta = pool.collect(
                CollectConfig(games=int(args.games), opponent="bot",
                              max_steps=int(args.max_steps)),
                games=int(args.games), progress=False)
        except Exception as exc:  # noqa: BLE001
            rounds.append({"error": repr(exc), "seconds": time.time() - r0})
            time.sleep(2)
            continue
        dt = max(time.time() - r0, 1e-9)
        gpu = _gpu_stats()
        rec = {"round": len(rounds), "seconds": dt,
               "decisions": int(meta.get("decisions", 0)),
               "records": int(meta.get("records", 0)),
               "decisions_per_s": int(meta.get("decisions", 0)) / dt,
               "samples": len(batch),
               "illegal": int(meta.get("illegal_actions", 0)),
               "truncated": int(meta.get("truncated_games", 0)),
               "gpu": gpu}
        rounds.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"args": vars(args), "elapsed_s": time.time() - t0,
                       "rounds": rounds}, f, ensure_ascii=False, indent=2)
    print("done", len(rounds), "rounds", time.time() - t0, "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
