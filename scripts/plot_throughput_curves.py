#!/usr/bin/env python3
"""资源/吞吐曲线：18M 前向、4GPU 推理、actor 扩展、训练采集超参。"""

from __future__ import annotations

import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main() -> int:
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))

    # 1) single GPU batch forward
    a = ax[0, 0]
    for name, p, color in [("entity 14.8M", "/tmp/bench_entity14.json", "#1f77b4"),
                           ("entity18m", "/tmp/bench_entity18.json", "#d62728")]:
        if not os.path.isfile(p):
            continue
        d = json.load(open(p))
        rows = [r for r in d["rows"] if r.get("mode") == "batch_server"]
        a.plot([r["batch"] for r in rows], [r["leafs_per_s"] for r in rows],
               "o-", label=name, color=color)
    a.set_xlabel("batch size")
    a.set_ylabel("leafs/s")
    a.set_title("Single-GPU leaf inference")
    a.grid(alpha=.3)
    a.legend(fontsize=8)

    # 2) 4 GPU aggregate
    a = ax[0, 1]
    agg = {64: 0, 128: 0, 256: 0}
    for p in glob.glob("/tmp/bench_4gpu_*.json"):
        d = json.load(open(p))
        for r in d["rows"]:
            if r["batch"] in agg:
                agg[r["batch"]] += r["leafs_per_s"]
    xs = sorted(agg)
    a.bar([str(x) for x in xs], [agg[x] for x in xs], color="#2ca02c")
    a.set_xlabel("per-GPU batch")
    a.set_ylabel("aggregate leafs/s")
    a.set_title("4-GPU inference (4 separate processes)")
    a.grid(alpha=.3, axis="y")

    # 3) actor eval scaling
    a = ax[1, 0]
    ws, ds, gpus = [], [], []
    for w in (8, 16, 32, 64):
        p = f"/tmp/actor18_w{w}.json"
        if os.path.isfile(p):
            d = json.load(open(p))
            ws.append(w); ds.append(d["decisions_per_s"])
            gpus.append(d.get("gpu_util_percent") or 0)
    a.plot(ws, ds, "o-", color="#9467bd", label="decisions/s")
    a.set_xlabel("Python worker threads")
    a.set_ylabel("decisions/s")
    a.set_title("Actor eval scaling (entity18m, GPU util <=32%)")
    a.grid(alpha=.3)
    a2 = a.twinx()
    a2.plot(ws, gpus, "s--", color="gray", label="GPU util %")
    a2.set_ylabel("GPU util %")
    a.legend(fontsize=8)

    # 4) training collect throughput
    a = ax[1, 1]
    for S, color in [(0, "#1f77b4"), (4, "#d62728")]:
        xs, ys = [], []
        for w in (8, 16, 32, 64):
            p = f"/tmp/thr_s{S}_w{w}/history.json"
            if os.path.isfile(p):
                h = json.load(open(p))["history"][0]["collect"]
                xs.append(w); ys.append(h["decisions"] / max(h["elapsed_s"], 1e-9))
        a.plot(xs, ys, "o-", color=color, label=f"sims={S}")
    a.set_xlabel("Python worker threads")
    a.set_ylabel("collect decisions/s")
    a.set_title("Training collection: sims=0 vs sims=4 (entity18m)")
    a.grid(alpha=.3)
    a.legend(fontsize=8)

    fig.suptitle("HSBRSIM resource / throughput curves (4x4090, 128 vCPU)", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = "runs/plots/compute_throughput.png"
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    fig.savefig(out, dpi=160)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
