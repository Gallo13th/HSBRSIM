#!/usr/bin/env python
"""全量验收一键执行：引擎/项目测试 + 冒烟 + 环境验收 + 基准 + 官方一致性门禁 + 版本检测
+ AutoTavern 借鉴升级新增门禁（跨引擎一致性 / TavernBench 评分复现）。

用法::

    python scripts/verify_all.py            # 全跑（约 4-6 分钟）
    python scripts/verify_all.py --fast     # 跳过一致性/基准（约 1.5 分钟）
    python scripts/verify_all.py --json runs/verify_all.json

退出码：0 = 全绿；1 = 有失败（逐项打印失败命令与尾部输出）。

``official_consistency`` gate = ``scripts/audit_official_consistency.py``
（硬门禁：DATA_GAP=0 / behavior_mismatch=0 / 干净子集 100%；
无官方语料机器上自动 SKIP 不误红；定义见 docs/DIFF_HARNESS.md §8）。

AutoTavern 借鉴升级新增（2026-10-26，见 docs/AUTOTAVERN_UPGRADE.md）::

* ``taverngym_conformance``：``tests/conformance``（跨引擎对拍 57 场景）。
  需要可选依赖 ``taverngym``；未安装时 **SKIP**（不算失败，Windows 默认
  环境不装 Rust 也能全绿）。
* ``tavernbench_check``：``scripts/run_tavernbench.py --check``（vendored
  TavernBench 数据完整性 + 已发布答案评分复现；纯标准库、无网络/模型依赖）。
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

#: 需要可选依赖的 gate → 依赖模块名（缺失时 SKIP 而非失败）
OPTIONAL_GATES: Dict[str, str] = {
    "taverngym_conformance": "taverngym",
    "tavernbench_check": None,  # 纯标准库，无额外依赖
}


def _module_available(name: str) -> bool:
    """可选依赖探测（不 import 目标模块，避免副作用/慢导入）。"""
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - 防御异常命名空间
        return False


def _cargo_path() -> str | None:
    """定位 cargo：PATH 优先，其次 rustup 默认安装位置（~/.cargo/bin/cargo）。

    GUI/IDE 或非交互 shell 里 PATH 可能不含 ~/.cargo/bin；Rust 主引擎门禁
    （rust_engine_build）要能在这种环境跑起来，而不是误 SKIP。
    """
    import shutil

    found = shutil.which("cargo")
    if found:
        return found
    cand = Path.home() / ".cargo" / "bin" / "cargo"
    return str(cand) if cand.is_file() else None


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
                            "--check-invariants",
                            "--json", "runs/env_validation.json"], 300),
        ("env_bench", [py, "scripts/bench_env.py", "--seeds", "20"], 300),
        ("hashseed_determinism", [py, "-m", "pytest",
                                  "tests/test_env_determinism_hashseed.py", "-q",
                                  "-o", "addopts=", "-p", "no:cacheprovider"], 180),
        ("official_consistency", [py, "scripts/audit_official_consistency.py",
                                  "--quiet"], 420),
        ("version_check", [py, "tools/version_sync.py", "--check"], 120),
    ]
    if args.fast:
        # --fast 不跑重型基准/一致性；TavernBench 评分复现很便宜（~1s），纳入。
        gates = [g for g in gates if g[0] in (
            "engine_tests", "project_tests", "env_validation", "version_check",
            "hashseed_determinism")]
    # AutoTavern 借鉴升级门禁（独立于项目测试再跑一次 conformance 作为显式
    # 证据项；tests/conformance 同时会被 project_tests 收集，但本机未装
    # taverngym 时这里给 SKIP 而不是 collection error 的红）。
    gates.append(("taverngym_conformance",
                  [py, "-m", "pytest", "tests/conformance", "-q",
                   "-o", "addopts=", "-p", "no:cacheprovider"], 300))
    gates.append(("tavernbench_check",
                  [py, "scripts/run_tavernbench.py", "--check"], 120))
    if args.fast:
        gates = [g for g in gates if g[0] != "taverngym_conformance"] + [
            g for g in gates if g[0] == "taverngym_conformance"]
    else:
        # P2/P3：Rust 主引擎（fork 自 AutoTavern）构建 + 测试门禁；
        # 无 cargo 或无 rust/ 时 SKIP。
        gates.insert(0, ("rust_engine_build",
                         ["cargo", "build", "--release",
                          "--manifest-path", "rust/Cargo.toml",
                          "-p", "hsbg-engine"], 900))
        gates.insert(1, ("rust_engine_test",
                         ["cargo", "test", "--release",
                          "--manifest-path", "rust/Cargo.toml",
                          "-p", "hsbg-engine"], 900))

    results = []
    t0 = time.perf_counter()
    for name, cmd, timeout in gates:
        dep = OPTIONAL_GATES.get(name)
        if dep is not None and not _module_available(dep):
            print(f"[SKIP] {name}  (可选依赖 {dep} 未安装)")
            results.append({"name": name, "cmd": cmd, "rc": 0, "ok": True,
                            "skip": True, "seconds": 0.0,
                            "tail": f"SKIPPED: optional dependency {dep} missing"})
            continue
        if name in ("rust_engine_build", "rust_engine_test"):
            cargo = _cargo_path()
            if cargo is None or not (ROOT / "rust" / "Cargo.toml").exists():
                print(f"[SKIP] {name}  (无 cargo 或无 rust/Cargo.toml)")
                results.append({"name": name, "cmd": cmd, "rc": 0, "ok": True,
                                "skip": True, "seconds": 0.0,
                                "tail": "SKIPPED: cargo or rust/ missing"})
                continue
            cmd = [cargo, *cmd[1:]]
        if not Path(ROOT / cmd[1]).exists() and name == "tavernbench_check":
            print(f"[SKIP] {name}  (scripts/run_tavernbench.py 不存在)")
            results.append({"name": name, "cmd": cmd, "rc": 0, "ok": True,
                            "skip": True, "seconds": 0.0,
                            "tail": "SKIPPED: runner missing"})
            continue
        results.append(run(name, cmd, timeout=timeout))
    total = time.perf_counter() - t0

    failed = [r for r in results if not r["ok"]]
    skipped = [r for r in results if r.get("skip")]
    summary = {
        "ok": not failed,
        "total_seconds": round(total, 1),
        "gates": results,
        "failed": [r["name"] for r in failed],
        "skipped": [r["name"] for r in skipped],
    }
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"\n{'=' * 60}")
    passed = len(results) - len(failed) - len(skipped)
    skip_note = f"（SKIP {len(skipped)}）" if skipped else ""
    print(f"verify_all: {passed}/{len(results) - len(skipped)} gates passed, "
          f"{len(skipped)} skipped{skip_note} in {total:.1f}s")
    if failed:
        print("FAILED: " + ", ".join(r["name"] for r in failed))
    sys.path.insert(0, str(ROOT))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
