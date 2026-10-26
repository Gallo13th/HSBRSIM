"""P3 验收门禁：构建 / 测试 / 冒烟 / 确定性 / Python 绑定 / worker 测试复核。

每项返回 `{name, cmd, exit_code, elapsed_s, passed, evidence...}`；
不抛异常（除系统级错误），失败也进报告，供 `docs/P3_VERIFICATION.md` 引用。

运行::

    python3 -m tools.p3_verify.gates            # 全部（含 pip install -e . 重建）
    python3 -m tools.p3_verify.gates --skip-rebuild   # 不重建，仅跑只读门禁
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import common

#: P3 三批 worker 测试文件 -> 负责的 P1 卡
WORKER_TESTS = {
    "p3_cards_a": common.P1_BATCH["engine-fixer"],
    "p3_cards_b": common.P1_BATCH["content-delta-analyst"],
    "p3_systems": common.P1_BATCH["rust-engine-forker"],
}

_CARD_ID_RE = re.compile(r"\b(BG[A-Za-z0-9_]+|TB_BaconShop_[A-Za-z0-9_]+|"
                         r"BGS_[A-Za-z0-9_]+|BGDUO_[A-Za-z0-9_]+)\b")
_TEST_FN_RE = re.compile(r"#\[test\]\s*(?:#\[[^\]]*\]\s*)*fn\s+([a-z0-9_]+)")


def _result(name: str, res: Dict[str, Any], *, passed: bool,
            notes: Optional[List[str]] = None) -> Dict[str, Any]:
    out = {"name": name, "passed": bool(passed),
           "elapsed_s": res.get("elapsed_s"),
           "cmd": res.get("cmd"),
           "exit_code": res.get("exit_code"),
           "stdout_tail": res.get("stdout_tail"),
           "stderr_tail": res.get("stderr_tail")}
    if res.get("error"):
        out["error"] = res["error"]
    if notes:
        out["notes"] = notes
    return out


# ══════════════════════════════════════════════════════════════════════
# 构建 / 测试
# ══════════════════════════════════════════════════════════════════════

def gate_cargo_build() -> Dict[str, Any]:
    res = common.run(
        ["cargo", "build", "--release", "-p", "hsbg-engine"], cwd=common.RUST)
    return _result("cargo_build_release", res,
                   passed=res.get("exit_code") == 0)


def gate_cargo_test(test: Optional[str] = None) -> Dict[str, Any]:
    cmd = ["cargo", "test", "--release", "-p", "hsbg-engine"]
    if not test:
        # 全量门禁要拿到**全部**失败清单（默认 fail-fast 只报第一个 suite）
        cmd.append("--no-fail-fast")
    else:
        cmd += ["--test", test]
    res = common.run(cmd, cwd=common.RUST, timeout=1800,
                     tail_limit=400000)
    text = (res.get("stdout_tail") or "") + (res.get("stderr_tail") or "")
    failed = 0
    m = re.search(r"(\d+) failed", text)
    if m:
        failed = int(m.group(1))
    elif res.get("exit_code") != 0:
        failed = -1
    # 汇总所有 suite（lib + integration）：`test result: ok. N passed; M failed`
    suite_rows = re.findall(
        r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed", text)
    passed_n = sum(int(r[1]) for r in suite_rows)
    failed_n = sum(int(r[2]) for r in suite_rows)
    if suite_rows:
        failed = failed_n
    suites = len(suite_rows)
    # 失败 suite/用例名单（--no-fail-fast 时是完整清单）
    failed_suites = sorted(set(re.findall(r"Running tests/([a-z0-9_]+)\.rs", text)))
    failed_tests = re.findall(r"---- ([a-z0-9_:]+) stdout ----", text)
    return _result(f"cargo_test_{test or 'all'}", res,
                   passed=(res.get("exit_code") == 0 and failed == 0),
                   notes=[f"passed={passed_n}", f"failed={failed}",
                          f"suites={suites}", f"failed_tests={failed_tests[:20]}"])


def gate_python_rebuild() -> Dict[str, Any]:
    """重建并 editable 安装 PyO3 扩展（content/data 改动后运行时真值才更新）。"""
    res = common.run([sys.executable, "-m", "pip", "install", "-e", "."],
                     cwd=common.RUST, timeout=1800)
    return _result("python_pip_install_e", res,
                   passed=res.get("exit_code") == 0)


def gate_pytest_rust_engine() -> Dict[str, Any]:
    res = common.run([sys.executable, "-m", "pytest",
                      "tests/test_rust_engine.py", "-q"],
                     cwd=common.ROOT, timeout=600)
    text = (res.get("stdout_tail") or "") + (res.get("stderr_tail") or "")
    return _result("pytest_test_rust_engine", res,
                   passed=res.get("exit_code") == 0,
                   notes=[text.strip().split("\n")[-1][:200]] if text else None)


# ══════════════════════════════════════════════════════════════════════
# 冒烟 / 确定性（hsbg_engine Python 绑定）
# ══════════════════════════════════════════════════════════════════════

def gate_smoke(seeds: int = 20, base_seed: int = 5000) -> Dict[str, Any]:
    """8 人 bot 冒烟 ×N seeds；任何异常/panic 记 crash。"""
    t0 = time.time()
    result: Dict[str, Any] = {"name": "bot_smoke", "seeds": seeds,
                              "turns": [], "crashes": []}
    try:
        import hsbg_engine  # type: ignore
        for i in range(seeds):
            seed = base_seed + i
            try:
                turns = hsbg_engine.run_bot_games(1, seed)
                result["turns"].append(int(turns[0]) if turns else None)
            except Exception as exc:  # noqa: BLE001
                result["crashes"].append({"seed": seed,
                                          "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:  # noqa: BLE001
        result["crashes"].append({"seed": None,
                                  "error": f"import/run: {type(exc).__name__}: {exc}"})
    result["elapsed_s"] = round(time.time() - t0, 2)
    result["passed"] = not result["crashes"]
    result["turn_min"] = min([t for t in result["turns"] if t is not None],
                             default=None)
    result["turn_max"] = max([t for t in result["turns"] if t is not None],
                             default=None)
    return result


def gate_determinism(seeds: int = 3, base_seed: int = 7000) -> Dict[str, Any]:
    """同 seed 双跑：run_bot_games 终局回合 + 全 bot Game state_json 指纹一致。"""
    t0 = time.time()
    out: Dict[str, Any] = {"name": "determinism", "checks": [], "passed": True}
    try:
        import hsbg_engine  # type: ignore
        for i in range(seeds):
            seed = base_seed + i
            a = hsbg_engine.run_bot_games(2, seed)
            b = hsbg_engine.run_bot_games(2, seed)
            ok = list(a) == list(b)
            out["checks"].append({"kind": "run_bot_games", "seed": seed,
                                  "run_a": list(a), "run_b": list(b),
                                  "same": ok})
            out["passed"] &= ok
        # Game 级：同 seed 两局全 bot 驱动后 state_json 相等
        g1 = _play_bot_game(seed=base_seed)
        g2 = _play_bot_game(seed=base_seed)
        same = g1 == g2
        out["checks"].append({"kind": "game_state_json", "seed": base_seed,
                              "same": same,
                              "bytes": len(g1.encode()) if g1 else 0})
        out["passed"] &= same
    except Exception as exc:  # noqa: BLE001
        out["passed"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["elapsed_s"] = round(time.time() - t0, 2)
    return out


def _play_bot_game(seed: int) -> Optional[str]:
    """用 8 个 bot 座位打到终局，返回 state_json（确定性指纹载体）。"""
    import hsbg_engine  # type: ignore
    g = hsbg_engine.Game(seed)
    # 英雄选择：与 tests/test_rust_engine.py 同款（每个座位选第 0 个 offer）
    for p in range(g.num_players):
        view = json.loads(g.view(p))
        g.step(p, view["actions"]["CHOOSE"])
    for _ in range(6000):
        if g.is_over():
            break
        progressed = False
        for p in range(g.num_players):
            if g.needs_action(p):
                g.bot_play(p)
                progressed = True
        if not progressed:
            break
    return g.state_json() if g.is_over() else None


# ══════════════════════════════════════════════════════════════════════
# worker 测试复核（存在性 / 用例数 / 卡覆盖 / 断言强度初筛）
# ══════════════════════════════════════════════════════════════════════

def review_worker_tests() -> Dict[str, Any]:
    tests_dir = common.ENGINE_CRATE / "tests"
    out: Dict[str, Any] = {"files": {}, "missing_files": []}
    for test_name, expected_cards in WORKER_TESTS.items():
        path = tests_dir / f"{test_name}.rs"
        if not path.exists():
            out["missing_files"].append(str(path))
            out["files"][test_name] = {"exists": False,
                                       "expected_cards": expected_cards}
            continue
        text = path.read_text(encoding="utf-8")
        fns = _TEST_FN_RE.findall(text)
        # 常量映射：`const AMBITION: &str = "BG22_HERO_007p";`——测试体里常以
        # 常量名引用卡 id，静态扫描文本时按名字补映射（避免误报缺口）。
        const_map = dict(re.findall(r'const\s+([A-Z][A-Z0-9_]*)\s*:\s*&str\s*=\s*"([^"]+)"', text))
        # 按函数体切分，统计每个用例提到的卡 id / 断言
        spans = []
        matches = list(_TEST_FN_RE.finditer(text))
        for idx, m in enumerate(matches):
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            body = text[start:end]
            cards = set(_CARD_ID_RE.findall(body))
            for name in re.findall(r"\b([A-Z][A-Z0-9_]+)\b", body):
                if name in const_map:
                    cards.add(const_map[name])
            spans.append({
                "fn": m.group(1),
                "cards": sorted(cards),
                "asserts": len(re.findall(r"\bassert", body)),
                "lines": body.count("\n"),
            })
        all_cards = sorted({c for s in spans for c in s["cards"]})
        covered = [c for c in expected_cards if c in all_cards]
        weak = [s["fn"] for s in spans if s["asserts"] == 0]
        out["files"][test_name] = {
            "exists": True,
            "path": str(path.relative_to(common.ROOT)),
            "test_count": len(fns),
            "tests": spans,
            "cards_mentioned": all_cards,
            "expected_cards": expected_cards,
            "expected_covered": covered,
            "expected_missing": [c for c in expected_cards
                                 if c not in all_cards],
            "tests_without_assert": weak,
        }
    return out


def gate_worker_tests() -> List[Dict[str, Any]]:
    results = []
    for test_name in WORKER_TESTS:
        path = common.ENGINE_CRATE / "tests" / f"{test_name}.rs"
        if path.exists():
            results.append(gate_cargo_test(test_name))
    return results


# ══════════════════════════════════════════════════════════════════════
# 编排
# ══════════════════════════════════════════════════════════════════════

def run_all(*, rebuild: bool = True, include_full_test: bool = True,
            verify_all: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    report: Dict[str, Any] = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "gates": []}
    if rebuild:
        report["gates"].append(gate_python_rebuild())
    report["gates"].append(gate_cargo_build())
    report["gates"].extend(gate_worker_tests())
    if include_full_test:
        report["gates"].append(gate_cargo_test())
    report["gates"].append(gate_pytest_rust_engine())
    report["smoke"] = gate_smoke()
    report["determinism"] = gate_determinism()
    report["worker_tests_review"] = review_worker_tests()
    if verify_all:
        res = common.run([sys.executable, "scripts/verify_all.py", "--fast"],
                         cwd=common.ROOT, timeout=1800)
        report["gates"].append(_result("verify_all_fast", res,
                                       passed=res.get("exit_code") == 0))
    failed = [g for g in report["gates"] if not g.get("passed")]
    if not report["smoke"].get("passed"):
        failed.append({"name": "bot_smoke"})
    if not report["determinism"].get("passed"):
        failed.append({"name": "determinism"})
    report["gate_summary"] = {
        "total": len(report["gates"]) + 2,
        "failed": [f["name"] for f in failed],
        "pass": not failed,
        "elapsed_s": round(time.time() - t0, 2),
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="P3 验收门禁")
    ap.add_argument("--skip-rebuild", action="store_true")
    ap.add_argument("--skip-full-test", action="store_true")
    ap.add_argument("--verify-all", action="store_true")
    ap.add_argument("--out", default="gates.json")
    args = ap.parse_args(argv)
    report = run_all(rebuild=not args.skip_rebuild,
                     include_full_test=not args.skip_full_test,
                     verify_all=args.verify_all)
    common.write_json(args.out, report)
    for gate in report["gates"]:
        status = "PASS" if gate.get("passed") else "FAIL"
        print(f"[{status}] {gate['name']:<28} "
              f"{gate.get('elapsed_s')}s")
    smoke = report["smoke"]
    print(f"[{'PASS' if smoke['passed'] else 'FAIL'}] bot_smoke"
          f"(seeds={smoke['seeds']}) crashes={len(smoke['crashes'])}")
    det = report["determinism"]
    print(f"[{'PASS' if det['passed'] else 'FAIL'}] determinism "
          f"checks={len(det.get('checks') or [])}")
    review = report["worker_tests_review"]
    print("worker tests:", {k: (v.get("test_count"), v.get("expected_missing"))
                            for k, v in review["files"].items()})
    print(f"gate pass={report['gate_summary']['pass']} "
          f"-> runs/p3_verify/{args.out}")
    return 0 if report["gate_summary"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
