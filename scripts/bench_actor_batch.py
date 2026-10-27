#!/usr/bin/env python3
"""多局 actor 批量叶 benchmark（P0 吞吐）。

每线程一个独立 Game + PPOGreedyPolicy，共享 BatchLeafServer；因此多个决策同时
submit 叶请求，能形成 B=64/128 batch。当前不是 MCTS 训练 actor，而是**推理吞吐**
基线：先证明多局并发 + batch server 能提高 decisions/s；MCTS 训练 actor 仍需把
Rust 逐叶回调替换为可挂起请求。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator  # noqa: E402
from hsbg.az.train.evaluate import EvalConfig, evaluate_policy  # noqa: E402
from hsbg.az.train.model import build_net  # noqa: E402
from hsbg.az.train.ppo import PPOGreedyPolicy  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=64, help="总对局数")
    ap.add_argument("--parallel", type=int, default=8, help="并发 actor 数")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--seed", type=int, default=90000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    import torch
    model = build_net(arch=args.arch)
    model.to(torch.device(args.device))
    model.eval()
    server = BatchLeafServer(model, device=args.device, batch_size=args.batch,
                             max_wait_ms=2.0, queue_size=max(4096, args.games))
    evaluator = BatchPPOEvaluator(server)
    per = max(1, args.games // max(1, args.parallel))
    games = per * max(1, args.parallel)
    results: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def work(actor: int) -> None:
        policy = PPOGreedyPolicy(evaluator,
                                 max_actions_per_turn=args.max_actions_per_turn)
        cfg = EvalConfig(games=per, seed=int(args.seed) + actor * per,
                         policy_seat=0, max_steps=50000)
        r = evaluate_policy(policy, cfg)
        with lock:
            results.append(r)

    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=int(args.parallel)) as ex:
            list(ex.map(work, range(int(args.parallel))))
    finally:
        total_s = time.time() - t0
        st = dict(server.stats)
        server.close()
    decisions = sum(int(r.get("decisions", 0)) for r in results)
    games_done = sum(int(r.get("games", 0)) for r in results)
    secs = [float(r.get("seconds", 0.0)) for r in results if r.get("seconds")]
    secs_sorted = sorted(secs)
    p95 = secs_sorted[min(len(secs_sorted) - 1, int(0.95 * len(secs_sorted)))] if secs_sorted else None
    gpu_util = None
    gpu_peak = None
    try:
        if torch.cuda.is_available():
            gpu_util = float(torch.cuda.utilization())
            gpu_peak = int(torch.cuda.max_memory_allocated())
    except Exception:
        pass
    payload = {
        "arch": args.arch, "device": args.device,
        "actors": int(args.parallel), "games": games_done,
        "decisions": decisions, "wall_seconds": total_s,
        "games_per_s": games_done / max(total_s, 1e-9),
        "decisions_per_s": decisions / max(total_s, 1e-9),
        "batch": st, "actor_seconds_median": statistics.median(secs) if secs else None,
        "actor_seconds_p95": p95, "gpu_util_percent": gpu_util,
        "gpu_peak_bytes": gpu_peak,
        "mean_rank": (sum(float(r.get("mean_rank", 0)) for r in results) / max(len(results), 1)),
        "illegal": sum(int(r.get("illegal_actions", 0)) for r in results),
        "truncated": sum(int(r.get("truncated_games", 0)) for r in results),
    }
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
