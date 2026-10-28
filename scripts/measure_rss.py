#!/usr/bin/env python3
"""RSS 峰值实测：跑一次短训练，轮询所有相关进程的 VmHWM，输出峰值驻留。

用法：
  python scripts/measure_rss.py --iters 4 --out runs/profile_resource/rss.json -- <train args>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time


def _vmhwm_kb(pid: int):
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--out", default="runs/profile_resource/rss.json")
    ap.add_argument("--rss-kb", type=int, default=400000)
    ap.add_argument("--vsz-kb", type=int, default=12000000)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = [c for c in args.cmd if c != "--"]
    if not cmd:
        print("需要 -- 之后的训练命令", file=sys.stderr)
        return 2

    peaks: dict = {}
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            pids = []
            for pat in ("train_entity_sync", "multiprocessing.spawn", "spawn_main"):
                try:
                    pids.extend(subprocess.check_output(["pgrep", "-f", pat],
                                                        text=True).split())
                except subprocess.CalledProcessError:
                    pass
            # 只看本仓库的进程（按 cwd 过滤），避免把别的作业算进来
            keep = []
            for p in set(pids):
                try:
                    if os.path.realpath(f"/proc/{p}/cwd") == os.getcwd():
                        keep.append(p)
                except OSError:
                    pass
            pids = keep
            for p in pids:
                kb = _vmhwm_kb(int(p))
                if kb:
                    peaks[int(p)] = max(peaks.get(int(p), 0), kb)
            time.sleep(0.25)

    t = threading.Thread(target=poll, daemon=True)
    t.start()
    t0 = time.time()
    rc = subprocess.call(cmd)
    stop.set()
    t.join(timeout=2.0)
    total_mb = sum(peaks.values()) / 1024.0
    out = {"rc": int(rc), "elapsed_s": round(time.time() - t0, 1),
           "n_procs": len(peaks),
           "per_proc_peak_mb": sorted((round(v / 1024.0, 1) for v in peaks.values()),
                                      reverse=True),
           "total_peak_mb": round(total_mb, 1),
           "max_proc_peak_mb": round(max(peaks.values()) / 1024.0, 1) if peaks else 0.0}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
