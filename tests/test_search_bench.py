"""bench_search 阈值逻辑 + 可选 quick bench 回归（默认 skip，避免拖慢 CI）。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "bench_search.py"
CHECKPOINT = REPO_ROOT / "runs" / "bc" / "official_320" / "policy_bc.pt"


def _load_bench_module():
    spec = importlib.util.spec_from_file_location("bench_search", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _perf(clone_p50: float, clone_p90: float = 0.0) -> dict:
    p90 = clone_p90 if clone_p90 else clone_p50 + 0.5
    return {
        "clone_ms": {"p50": clone_p50, "p90": p90},
        "one_ply_clone_eval_ms": {"p50": 10.0},
        "clone_eval_1000_ms": 5000.0,
    }


def _search(ms: dict) -> dict:
    levels = {str(n): {"ms_per_decision": {"p50": ms[n], "p90": ms[n]}}
              for n in ms}
    return {
        "levels": levels,
        "legality": {"pi_valid": True, "macro_legal": True,
                     "oracle_used": False, "hidden_info_mode": "none"},
        "determinism": {"pi_equal": True, "visits_equal": True,
                        "best_equal": True},
    }


def test_thresholds_pass_and_fail() -> None:
    bench = _load_bench_module()
    perf = _perf(2.2, 3.2)
    search = _search({8: 200.0, 16: 200.0, 32: 220.0})
    ok = bench.evaluate_thresholds(perf, search)
    assert ok["passed"] is True
    assert all(ok["checks"].values())

    # clone 超限 → 失败（可用 --clone-p50-limit 放宽）
    bad = bench.evaluate_thresholds(_perf(4.0, 5.0), search)
    assert bad["passed"] is False
    assert bad["checks"]["clone_p50_le_limit"] is False
    relaxed = bench.evaluate_thresholds(
        _perf(4.0, 5.0), search,
        clone_p50_limit_ms=4.5, clone_p90_limit_ms=5.5)
    assert relaxed["passed"] is True

    # 搜索超限 → 失败
    slow = bench.evaluate_thresholds(_perf(2.2, 3.2),
                                     _search({8: 400.0, 16: 800.0, 32: 1300.0}))
    assert slow["passed"] is False
    assert slow["checks"]["N8_le_350ms"] is False
    assert slow["checks"]["N32_le_1200ms"] is False


def test_script_has_sys_path_bootstrap() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "_REPO_ROOT" in text and "sys.path.insert" in text


@pytest.mark.skipif(os.environ.get("HSBG_RUN_SEARCH_BENCH") != "1",
                    reason="慢（~13s）；设 HSBG_RUN_SEARCH_BENCH=1 运行")
def test_quick_bench_passes_with_relaxed_clone_limit(tmp_path) -> None:
    assert CHECKPOINT.exists(), "缺少 BC checkpoint"
    out = tmp_path / "phase1_bench_quick.json"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # 验证脚本自身 sys.path 引导
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--quick",
         "--clone-p50-limit", "7.5", "--clone-p90-limit", "10.0",
         "--checkpoint", str(CHECKPOINT),
         "--out", str(out)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["thresholds"]["passed"] is True
    assert report["perf"]["clone_ms"]["p50"] <= 7.5
    assert report["search"]["determinism"]["pi_equal"] is True
    assert report["search"]["legality"]["pi_valid"] is True
    assert report["search_vs_bc"]["n_snapshots"] >= 1
