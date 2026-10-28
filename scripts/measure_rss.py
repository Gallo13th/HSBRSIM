#!/usr/bin/env python3
"""RSS 峰值实测（修正版）：按**进程树**采样，统计**同一时刻**所有相关进程 VmRSS 之和的峰值。

用法：
  python scripts/measure_rss.py --interval 0.2 --out runs/profile_resource/rss.json \
      -- <训练命令...>

说明：
- 进程树 = 启动命令的 pid + 其所有后代（按 /proc/<pid>/stat 的 ppid 关系），
  不会混入同仓库的其它作业；
- `simultaneous_peak_mb` 是各采样时刻「树内所有进程 VmRSS 之和」的最大值；
- `per_pid_max_hwm_mb` 另列每个 pid 的 VmHWM（历史峰值），两者不可相加；
- 记录采样间隔与实际样本数，结论只覆盖本次命令与时间窗口。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time


def _stat_fields(pid: int):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            parts = f.read().rsplit(") ", 1)[1].split()
        return parts  # [state, ppid, ...]
    except (OSError, IndexError):
        return None


def _children_map():
    kids: dict = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        st = _stat_fields(pid)
        if not st:
            continue
        try:
            ppid = int(st[1])
        except (IndexError, ValueError):
            continue
        kids.setdefault(ppid, []).append(pid)
    return kids


def _tree(root: int):
    kids = _children_map()
    out, stack = [], [root]
    while stack:
        p = stack.pop()
        out.append(p)
        stack.extend(kids.get(p, []))
    return out


def _vm(pid: int):
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            rss = hwm = 0
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                elif line.startswith("VmHWM:"):
                    hwm = int(line.split()[1])
        return rss, hwm
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=0.2)
    ap.add_argument("--out", default="runs/profile_resource/rss.json")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = [c for c in args.cmd if c != "--"]
    if not cmd:
        print("需要 -- 之后的训练命令", file=sys.stderr)
        return 2

    proc = subprocess.Popen(cmd)
    t0 = time.time()
    peak_sum_kb = 0
    peak_at = 0.0
    peak_procs = 0
    hwm: dict = {}
    samples = 0
    while proc.poll() is None:
        tree = _tree(proc.pid)
        total = 0
        for p in tree:
            v = _vm(p)
            if v is None:
                continue
            rss, h = v
            total += rss
            hwm[p] = max(hwm.get(p, 0), h)
        samples += 1
        if total > peak_sum_kb:
            peak_sum_kb, peak_at, peak_procs = total, time.time() - t0, len(tree)
        time.sleep(max(0.02, args.interval))
    rc = proc.wait()
    out = {
        "rc": int(rc),
        "elapsed_s": round(time.time() - t0, 1),
        "interval_s": args.interval,
        "samples": samples,
        "simultaneous_peak_mb": round(peak_sum_kb / 1024.0, 1),
        "simultaneous_peak_at_s": round(peak_at, 1),
        "procs_at_peak": peak_procs,
        "n_pids_seen": len(hwm),
        "per_pid_max_hwm_mb": sorted((round(v / 1024.0, 1) for v in hwm.values()),
                                     reverse=True)[:20],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
