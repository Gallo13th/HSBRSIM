"""P2 性能基准一键复跑：引擎吞吐 + 端到端分解 + C 加速可行性。

用法::

    cd /Users/letiangao/HSAgent/HSBRSIM
    PYTHONPATH=. python3 tools/p2_perf/run_all.py
    # JSON 写入 runs/p2_perf/；同时打印 Markdown 汇总表
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
RUNS = ROOT / "runs" / "p2_perf"


def run(script: str, *args: str) -> None:
    cmd = [sys.executable, str(TOOL_DIR / script), *args]
    print(f"\n$ {' '.join(cmd)}")
    out = subprocess.run(cmd, cwd=str(ROOT), text=True)
    if out.returncode != 0:
        raise SystemExit(f"{script} failed: exit {out.returncode}")


def main() -> int:
    RUNS.mkdir(parents=True, exist_ok=True)
    run("bench_engine.py", "--hsrl2-games", "8", "--engine-games", "500")
    run("bench_e2e.py", "--steps", "300")
    run("bench_c_accel.py", "--iters", "1000", "--clone-iters", "1000")
    print("\n[done] 三份 JSON 见 runs/p2_perf/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
