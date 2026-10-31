#!/usr/bin/env python3
"""叶子前向的**批大小成本曲线**（单卡短跑，默认 cuda:7 空闲卡；<1 分钟）。

回答 ``--games`` 该不该加大：lockstep 每个 worker 每轮把所有待决策局拼成一个 batch，
所以 ``batch ≈ games / processes``。这里直接测 ``BatchLeafServer.act_batch`` 在不同
batch 下的墙钟时间，换算成「每决策前向成本」，再按 s14 实测数据外推 dec/s。

用法：
  PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
  PYTHONPATH=rust/python:. $PY scripts/bench_leaf_batch.py --device cuda:7 --reps 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OBS_FLOATS, OBS_CARDS, N_ACTIONS = 3227, 124, 245


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--checkpoint", default="runs/profile_collect/ckpt_frozen.pt")
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--batch-sizes", default="1,2,4,8,12,16,24,32,48,64")
    ap.add_argument("--batch-size-max", type=int, default=64)
    ap.add_argument("--leaf-wait-ms", type=float, default=1.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import torch
    torch.set_num_threads(1)
    from hsbg.az.train.batch_eval import BatchLeafServer
    from hsbg.az.train.model import load_checkpoint

    dev = str(args.device)
    model, meta = load_checkpoint(args.checkpoint, device=dev)
    server = BatchLeafServer(model, device=dev, batch_size=int(args.batch_size_max),
                             max_wait_ms=float(args.leaf_wait_ms), queue_size=8192,
                             norm_mean=meta.get("norm_mean"),
                             norm_std=meta.get("norm_std"))
    rng = np.random.default_rng(0)
    sizes = [int(x) for x in str(args.batch_sizes).split(",") if x.strip()]
    # 用真实观测构造行（从一局里取），mask 用全合法近似
    import hsbg_engine as E
    from hsbg.az.train.common import mask_from_bytes, obs_arrays
    g = E.Game(seed=1)
    feats: List[np.ndarray] = []
    cards: List[np.ndarray] = []
    masks: List[np.ndarray] = []
    for _ in range(int(args.reps) * max(sizes) + 64):
        if g.is_over():
            break
        acted = False
        for p in range(int(g.num_players)):
            if g.needs_action(p):
                f, c = obs_arrays(g.observe(p))
                feats.append(np.asarray(f, dtype=np.float32))
                cards.append(np.asarray(c, dtype=np.int64))
                masks.append(mask_from_bytes(g.legal_mask(p)))
                g.bot_play(p)
                acted = True
                break
        if not acted:
            break
    if not feats:
        raise RuntimeError("没取到观测")
    while len(feats) < max(sizes) * 2:
        feats.append(feats[-1])
        cards.append(cards[-1])
        masks.append(masks[-1])
    F = np.stack(feats[: max(sizes)])
    C = np.stack(cards[: max(sizes)])
    M = np.stack(masks[: max(sizes)])

    # 预热（cuDNN/torch kernel 首次编译）
    for b in (1, 8):
        server.act_batch(F[:b], C[:b], M[:b], 1.0, 123)
    torch.cuda.synchronize() if dev.startswith("cuda") else None

    rows: List[Dict[str, Any]] = []
    for b in sizes:
        reps = max(5, int(args.reps))
        # 时间包含 submit + wait（单客户端下就是一次前向 + 队列往返）
        t0 = time.perf_counter()
        for i in range(reps):
            server.act_batch(F[:b], C[:b], M[:b], 1.0, 1000 + i)
        dt = (time.perf_counter() - t0) / reps
        rows.append({"batch": int(b), "ms_per_call": dt * 1e3,
                     "ms_per_row": dt * 1e3 / max(1, b),
                     "rows_per_s": b / dt})
        print(f"batch={b:3d}  {dt * 1e3:7.3f} ms/call  {dt * 1e3 / max(1, b):6.3f} ms/row"
              f"  {b / dt:9.0f} rows/s", flush=True)
    # 外推：s14 实测 forward_s / leafs = 0.82 ms/决策（batch≈8.2）
    print("\n[外推] 以 batch=8.2 的 ms/row 为基线，估 --games 变化后的前向成本：")
    base = next(r for r in rows if r["batch"] == 8)["ms_per_row"]
    for b in (8, 12, 16, 24, 32):
        hit = next((r for r in rows if r["batch"] == b), None)
        if hit:
            print(f"  batch≈{b:3d}（games≈{b * 16}）：{hit['ms_per_row'] / base:.2f}x "
                  f"前向成本/决策")
    out = {"device": dev, "rows": rows}
    if args.out:
        os.makedirs(os.path.dirname(str(args.out)) or ".", exist_ok=True)
        with open(str(args.out), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
