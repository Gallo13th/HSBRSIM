#!/usr/bin/env python
"""全量验收一键执行：引擎/项目测试 + 冒烟 + 环境验收 + 基准 + 官方一致性门禁 + 版本检测。

用法::

    python scripts/verify_all.py            # 全跑（约 4-5 分钟）
    python scripts/verify_all.py --fast     # 跳过一致性/基准（约 1.5 分钟）
    python scripts/verify_all.py --json runs/verify_all.json

退出码：0 = 全绿；1 = 有失败（逐项打印失败命令与尾部输出）。

``official_consistency`` gate = ``scripts/audit_official_consistency.py``
（硬门禁：DATA_GAP=0 / behavior_mismatch=0 / 干净子集 100%；
无官方语料机器上自动 SKIP 不误红；定义见 docs/DIFF_HARNESS.md §8）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent


def run(name: str, cmd: List[str], *, timeout: int = 900) -> Dict:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
        rc = proc.returncode
        out = (proc.stdout or "") + (proc.stderr or "")
        lines = [l for l in out.strip().splitlines() if l.strip()]
        tail = "\n".join(lines[-6:])
    except subprocess.TimeoutExpired:
        rc = -1
        tail = f"TIMEOUT after {timeout}s"
    elapsed = time.perf_counter() - t0
    ok = rc == 0
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}  ({elapsed:.1f}s)  rc={rc}")
    if not ok:
        for line in tail.splitlines():
            print(f"       {line}")
    return {"name": name, "cmd": cmd, "rc": rc, "ok": ok,
            "seconds": round(elapsed, 1), "tail": tail}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--json", type=str, default="runs/verify_all.json")
    args = ap.parse_args(argv)

    py = sys.executable
    gates: List[Tuple[str, List[str], int]] = [
        ("engine_tests", [py, "-m", "pytest", "hsrl2/tests", "-q",
                          "-o", "addopts=", "-p", "no:cacheprovider"], 600),
        ("project_tests", [py, "-m", "pytest", "tests", "-q",
                           "-o", "addopts=", "-p", "no:cacheprovider"], 600),
        ("smoke_8p", [py, "tools/smoke_random_games.py", "--games", "8",
                      "--seed", "2000"], 300),
        ("env_validation", [py, "scripts/validate_env.py", "--games", "20",
                            "--json", "runs/env_validation.json"], 300),
        ("env_bench", [py, "scripts/bench_env.py", "--seeds", "20"], 300),
        ("official_consistency", [py, "scripts/audit_official_consistency.py",
                                  "--quiet"], 420),
        ("version_check", [py, "tools/version_sync.py", "--check"], 120),
    ]
    if args.fast:
        gates = [g for g in gates if g[0] in (
            "engine_tests", "project_tests", "env_validation", "version_check")]

    results = []
    t0 = time.perf_counter()
    for name, cmd, timeout in gates:
        results.append(run(name, cmd, timeout=timeout))
    total = time.perf_counter() - t0

    failed = [r for r in results if not r["ok"]]
    summary = {
        "ok": not failed,
        "total_seconds": round(total, 1),
        "gates": results,
        "failed": [r["name"] for r in failed],
    }
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"\n{'=' * 60}")
    print(f"verify_all: {len(results) - len(failed)}/{len(results)} gates passed "
          f"in {total:.1f}s")
    if failed:
        print("FAILED: " + ", ".join(r["name"] for r in failed))
    sys.path.insert(0, str(ROOT))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
