"""轻量 profiling：持续 GPU util/显存采样 + 进程 IO 计数。"""

from __future__ import annotations

import os
import statistics
import threading
import time
from typing import Any, Dict, List


class GPUSampler:
    def __init__(self, interval_s: float = 0.1):
        self.interval_s = max(0.02, float(interval_s))
        self._stop = threading.Event()
        self._samples: List[float] = []
        self._mem: List[int] = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            import torch
        except Exception:
            return
        while not self._stop.is_set():
            try:
                if torch.cuda.is_available():
                    self._samples.append(float(torch.cuda.utilization()))
                    self._mem.append(int(torch.cuda.memory_allocated()))
            except Exception:
                pass
            self._stop.wait(self.interval_s)

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        self._thread.join(timeout=2.0)
        xs = sorted(self._samples)
        if not xs:
            return {"gpu_util_mean": None, "gpu_util_p95": None, "gpu_peak_bytes": None,
                    "gpu_samples": 0}
        return {
            "gpu_util_mean": float(statistics.fmean(xs)),
            "gpu_util_p95": float(xs[min(len(xs) - 1, int(0.95 * (len(xs) - 1)))]),
            "gpu_peak_bytes": int(max(self._mem) if self._mem else 0),
            "gpu_samples": len(xs),
        }


def io_counters() -> Dict[str, int]:
    """Linux /proc/self/io；其他平台返回 0。"""
    out = {"read_bytes": 0, "write_bytes": 0}
    try:
        with open("/proc/self/io", encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("read_bytes", "write_bytes"):
                    out[k] = int(v.strip())
    except Exception:
        pass
    return out


__all__ = ["GPUSampler", "io_counters"]
