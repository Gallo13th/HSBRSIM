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
        n_live = 0
        for p in tree:
            v = _vm(p)
            if v is None:
                continue
            rss, h = v
            total += rss
            n_live += 1
            hwm[p] = max(hwm.get(p, 0), h)
        samples += 1
        if total > peak_sum_kb:
            peak_sum_kb, peak_at, peak_procs = total, time.time() - t0, n_live
        time.sleep(max(0.02, args.interval))
    rc = proc.wait()
    peak_mib = peak_sum_kb / 1024.0
    out = {
        "rc": int(rc),
        "elapsed_s": round(time.time() - t0, 1),
        "interval_s": args.interval,
        "samples": samples,
        "unit": "MiB (KiB/1024)",
        "simultaneous_peak_mib": round(peak_mib, 1),
        "simultaneous_peak_gib": round(peak_mib / 1024.0, 2),
        "simultaneous_peak_gb": round(peak_mib * 1.048576 / 1000.0, 2),
        "simultaneous_peak_at_s": round(peak_at, 1),
        "procs_summed_at_peak": peak_procs,
        "n_pids_seen": len(hwm),
        "hwm_by_pid_top20": [
            {"pid": pid, "hwm_mib": round(kb / 1024.0, 1)}
            for pid, kb in sorted(hwm.items(), key=lambda kv: kv[1], reverse=True)[:20]],
        "caveats": [
            "sampled approximation: /proc reads are not an atomic snapshot",
            "ppid re-parenting / exited procs may be missed between samples",
            "only covers this command's process tree within the sampling window",
        ],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
