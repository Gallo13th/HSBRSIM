#!/usr/bin/env python3
"""资源采样器（只读，不占 GPU）：每 interval 采一次 GPU util/显存 + CPU 统计 + 磁盘 I/O。

用于给「训练时各资源到底有多闲」出时间序列，供 `plot_resource_profile.py` 画图。

用法：
  python scripts/resource_sampler.py --seconds 180 --interval 0.2 \
      --out runs/profile_resource/sample.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time


def _gpus():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"], text=True, timeout=5)
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for line in out.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 4:
            continue
        try:
            rows.append({"i": int(p[0]), "util": int(p[1]),
                         "mem": int(p[2]), "mem_total": int(p[3])})
        except ValueError:
            continue
    return rows


def _cpu():
    """返回 (busy_ratio, per_field)。/proc/stat 第一行是整机累计。"""
    fields = {}
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            parts = f.readline().split()[1:]
        vals = [int(x) for x in parts]
        names = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal"]
        fields = dict(zip(names, vals))
        total = sum(vals[:8])
        idle = fields.get("idle", 0) + fields.get("iowait", 0)
        fields["total"] = total
        fields["busy_ratio"] = 0.0 if total == 0 else 1.0 - idle / total
    except Exception:  # noqa: BLE001
        pass
    return fields


def _disk():
    """累计扇区（/proc/diskstats, sdb 等物理盘）；换算成 MB/s 由调用方做差分。"""
    out = {}
    try:
        with open("/proc/diskstats", encoding="utf-8") as f:
            for line in f:
                p = line.split()
                if len(p) < 14:
                    continue
                name = p[2]
                if not name.startswith(("sd", "nvme", "vd")):
                    continue
                if any(ch.isdigit() for ch in name):
                    continue
                out[name] = {"read_sectors": int(p[5]), "write_sectors": int(p[9])}
    except Exception:  # noqa: BLE001
        pass
    return out


def _loadavg():
    try:
        return float(open("/proc/loadavg", encoding="utf-8").read().split()[0])
    except Exception:  # noqa: BLE001
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--interval", type=float, default=0.2)
    ap.add_argument("--out", default="runs/profile_resource/sample.jsonl")
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    t_end = time.time() + args.seconds
    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        while time.time() < t_end:
            t0 = time.time()
            rec = {"t_wall": t0, "t_mono": time.monotonic(),
                   "gpus": _gpus(), "cpu": _cpu(), "disk": _disk(),
                   "load1": _loadavg()}
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            f.flush()
            n += 1
            time.sleep(max(0.0, args.interval - (time.time() - t0)))
    print(f"[sample] {n} samples -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
