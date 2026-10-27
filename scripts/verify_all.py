#!/usr/bin/env python3
"""AutoTavern-only 验收门禁。

门禁（硬标准：0 failed / 0 crash / 0 invalid）：
1. rust_tests        cargo test --release -p hsbg-engine（AutoTavern fork 全量）
2. python_tests      pytest tests（AZ/标准动作观测/数据/Rust 适配）
3. engine_smoke      8 局全 bot 对局（hsbg_engine）
4. tavernbench       vendored TavernBench 数据 + 评分复现（26/26）
5. data_check        37.0.0.255790 AutoTavern schema 与生成器一致（缺上游 checkout 时 SKIP）
6. az_smoke          MCTS 搜索 + 1 局自对弈 + 1 epoch（--fast 时 SKIP）

用法：
    python scripts/verify_all.py            # 全量（约 3–5 分钟）
    python scripts/verify_all.py --fast     # 跳过 AZ smoke
    python scripts/verify_all.py --json runs/verify_all.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent


def _cargo() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    candidate = Path.home() / ".cargo" / "bin" / "cargo"
    return str(candidate) if candidate.is_file() else None


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def run(name: str, cmd: List[str], *, timeout: int = 900,
        env: Dict[str, str] | None = None) -> Dict:
    t0 = time.perf_counter()
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env=merged)
        rc = proc.returncode
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc = -1
        out = f"TIMEOUT after {timeout}s"
    elapsed = time.perf_counter() - t0
    tail = "\n".join([line for line in out.strip().splitlines() if line.strip()][-4:])
    ok = rc == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  ({elapsed:.1f}s)  rc={rc}")
    if not ok:
        for line in tail.splitlines():
            print(f"       {line}")
    return {"name": name, "ok": ok, "seconds": round(elapsed, 1),
            "rc": rc, "tail": tail}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--json", default="runs/verify_all.json")
    args = ap.parse_args(argv)
    py = sys.executable
    cargo = _cargo()
    gates: List[Tuple[str, List[str], int, Dict[str, str] | None]] = []
    if cargo:
        gates.append(("rust_tests", [cargo, "test", "--release", "--manifest-path", "rust/Cargo.toml", "-p", "hsbg-engine"], 600, None))
    gates.append(("python_tests", [py, "-m", "pytest", "tests", "-q",
                                   "-o", "addopts=", "-p", "no:cacheprovider"], 600, None))
    gates.append(("engine_smoke", [py, "-c", (
        "import hsbg_engine as E;"
        "crashes=0;"
        "\nfor s in range(8):\n"
        " g=E.Game(seed=2000+s)\n"
        " while not g.is_over():\n"
        "  for p in range(g.num_players):\n"
        "   if g.needs_action(p): g.step(p, g.bot_action(p))\n"
        "print('ok')\n"
    )], 180, None))
    gates.append(("tavernbench", [py, "scripts/run_tavernbench.py", "--check"], 120, None))
    at_root = Path(os.environ.get("HSBRSIM_AT_ROOT", str(ROOT.parent / "AutoTavern")))
    if (at_root / "crates" / "taverngym" / "data" / "cards.json").is_file():
        gates.append(("data_check", [py, "tools/p2_data/gen_carddb_37.py", "--check"], 120,
                      {"HSBRSIM_AT_ROOT": str(at_root)}))
    else:
        print("[SKIP] data_check（缺 AutoTavern checkout；设 HSBRSIM_AT_ROOT 可启用）")
    if not args.fast:
        gates.append(("az_smoke", [py, "scripts/az_selfplay_smoke.py", "--games", "1",
                                   "--epochs", "1", "--arch", "tiny", "--eval-games", "1",
                                   "--out", "runs/verify_az_smoke"], 600, None))

    results: List[Dict] = []
    for name, cmd, timeout, env in gates:
        results.append(run(name, cmd, timeout=timeout, env=env))
    ok = all(r["ok"] for r in results)
    report = {"ok": ok, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "gates": results}
    out = ROOT / args.json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{'ALL PASS' if ok else 'FAILED'}  ({len(results)} gates)  -> {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
