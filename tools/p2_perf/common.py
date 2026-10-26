"""P2 性能基准共享工具（硬件/统计/JSON 输出）。

所有数字都来自**可复现脚本**；结果写入 ``runs/p2_perf/``（gitignore）。
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "runs" / "p2_perf"


def ensure_runs_dir() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR


def save_json(name: str, payload: Dict[str, Any]) -> Path:
    path = ensure_runs_dir() / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def cpu_brand() -> str:
    try:
        out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                            capture_output=True, text=True, timeout=5)
        text = out.stdout.strip()
        if text:
            return text
    except Exception:                                     # noqa: BLE001
        pass
    return platform.processor() or "unknown"


def machine_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_brand": cpu_brand(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "cpu_count": _cpu_count(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        import taverngym
        info["taverngym_version"] = str(taverngym.version())
        info["taverngym_game_version"] = str(taverngym.game_version())
        info["taverngym_profile"] = str(taverngym.build_info().get("profile"))
        info["taverngym_source_hash"] = str(
            taverngym.build_info().get("source_hash"))
    except Exception as exc:                              # noqa: BLE001
        info["taverngym_error"] = f"{type(exc).__name__}: {exc}"
    return info


def _cpu_count() -> int:
    import os
    return int(os.cpu_count() or 0)


def summarize(values_us: Sequence[float]) -> Dict[str, float]:
    """微秒样本 → mean/median/p90/p99/min/max（µs）。"""
    sample = sorted(float(v) for v in values_us)
    if not sample:
        return {"n": 0}
    n = len(sample)

    def pct(p: float) -> float:
        index = min(n - 1, max(0, int(round(p * (n - 1)))))
        return sample[index]

    return {
        "n": n,
        "mean_us": round(statistics.fmean(sample), 3),
        "median_us": round(statistics.median(sample), 3),
        "p90_us": round(pct(0.90), 3),
        "p99_us": round(pct(0.99), 3),
        "min_us": round(sample[0], 3),
        "max_us": round(sample[-1], 3),
    }


class Timer:
    """累加型计时器（ns → µs），用于 step 内环节占比分解。"""

    def __init__(self) -> None:
        self.total_ns = 0
        self.count = 0

    def add(self, ns: int) -> None:
        self.total_ns += int(ns)
        self.count += 1

    def us(self) -> float:
        return self.total_ns / 1000.0

    def per_call_us(self) -> float:
        return self.us() / self.count if self.count else 0.0

    def per_step_us(self, steps: int) -> float:
        return self.us() / steps if steps else 0.0


def print_table(rows: List[Dict[str, Any]], columns: Sequence[str]) -> None:
    """打印 Markdown 表（控制台 + 文档复用）。"""
    print("| " + " | ".join(columns) + " |")
    print("|" + "|".join(["---"] * len(columns)) + "|")
    for row in rows:
        print("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
