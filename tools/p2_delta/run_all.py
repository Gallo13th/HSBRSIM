#!/usr/bin/env python3
"""P2-C 一键复现：AT content 抽取 → 37 覆盖矩阵 → 操作缺口探针。

依次运行三个只读脚本，产物写入 `runs/p2_delta/`（gitignore）::

    python3 tools/p2_delta/run_all.py
    # 或分步：
    python3 tools/p2_delta/extract_at_content.py
    python3 tools/p2_delta/compare_37.py
    python3 tools/p2_delta/probe_ops.py

返回码 0 = 三步全部成功。全程不写仓库源码（仅 runs/ 产物）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent.parent


def run(script: str) -> int:
    print(f"\n════════ {script} ════════", flush=True)
    proc = subprocess.run(
        [sys.executable, str(TOOLS / script)],
        cwd=str(REPO_ROOT),
        text=True,
    )
    return proc.returncode


def main() -> int:
    codes = [run("extract_at_content.py"), run("compare_37.py"), run("probe_ops.py")]
    ok = all(c == 0 for c in codes)
    print("\n════════ 汇总 ════════")
    print(f"返回码: {codes} -> {'OK' if ok else 'FAILED'}")
    print(f"产物目录: {REPO_ROOT / 'runs' / 'p2_delta'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
