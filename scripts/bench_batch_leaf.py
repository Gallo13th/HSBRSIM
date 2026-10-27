#!/usr/bin/env python3
"""批量叶推理 benchmark：B=1/64/128/256，tiny/entity，单 GPU。

指标：leafs/s、mean/max batch、requests/batches、forward seconds、GPU 显存峰值。
用于 P0 吞吐验收；不代表端到端 MCTS decisions/s（Rust 逐叶回调仍未接）。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.batch_eval import BatchLeafServer  # noqa: E402
from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS  # noqa: E402
from hsbg.az.train.model import build_net  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator  # noqa: E402


def _sample(rng, n):
    f = rng.normal(size=(n, OBS_FLOATS)).astype(np.float32)
    c = np.zeros((n, OBS_CARDS), dtype=np.int64)
    m = np.zeros((n, N_ACTIONS), dtype=bool)
    for i in range(n):
        legal = rng.choice(N_ACTIONS, size=8, replace=False)
        m[i, legal] = True
    return f, c, m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--leafs", type=int, default=1024)
    ap.add_argument("--batches", default="1,64,128,256")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    import torch
    model = build_net(arch=args.arch)
    model.to(torch.device(args.device))
    model.eval()
    rng = np.random.default_rng(0)
    f, c, m = _sample(rng, int(args.leafs))
    rows: List[Dict[str, Any]] = []
    # direct B=1
    direct = PPOEvaluator(model, device=args.device)
    for _ in range(8):
        direct(f[0], c[0], m[0])
    t0 = time.time()
    for i in range(len(f)):
        direct(f[i], c[i], m[i])
    dt = max(time.time() - t0, 1e-9)
    rows.append({"mode": "direct", "batch": 1, "leafs": len(f),
                 "seconds": dt, "leafs_per_s": len(f) / dt,
                 "max_batch": 1, "batches": len(f)})
    for b in [int(x) for x in str(args.batches).split(",") if x.strip()]:
        server = BatchLeafServer(model, device=args.device, batch_size=b,
                                 max_wait_ms=2.0, queue_size=max(4096, len(f)))
        try:
            for _ in range(min(8, len(f))):
                server.call(f[0], c[0], m[0])
            t0 = time.time()
            # 先全部 submit，再等待：单线程也能形成 batch
            server.call_many(f, c, m)
            dt = max(time.time() - t0, 1e-9)
            st = dict(server.stats)
            rows.append({"mode": "batch_server", "batch": b, "leafs": len(f),
                         "seconds": dt, "leafs_per_s": len(f) / dt,
                         "max_batch": st["max_batch"], "batches": st["batches"],
                         "requests": st["requests"], "wait_s": st["wait_s"]})
        finally:
            server.close()
    peak = None
    try:
        peak = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    except Exception:
        pass
    payload = {"arch": args.arch, "device": args.device, "leafs": len(f),
               "rows": rows, "gpu_peak_bytes": peak}
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
