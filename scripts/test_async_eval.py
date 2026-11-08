"""异步评测（``scripts/async_eval.py``）回归测试。

覆盖三件事（不需要 GPU / torch）：

1. 子进程结果按原 schema 追加进 ``eval/history.json``，并保留已有记录（续训场景）；
2. 并发上限 1：上一个评测未完成时再提交 -> 跳过并记 ``eval_skipped``；
3. 子进程失败 -> ``error`` 入 history、打印 stderr 尾部、训练侧不抛异常。

用假的 ``c0_gate.py``（只解析参数 + 写 JSON），通过环境变量控制 sleep / 失败。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from scripts.async_eval import AsyncEvalRunner, parse_c0_result


FAKE_GATE = r'''
import argparse
import json
import os
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--checkpoint", required=True)
ap.add_argument("--arch", default="tiny")
ap.add_argument("--device", default="cpu")
ap.add_argument("--games", type=int, default=8)
ap.add_argument("--seats", type=int, default=2)
ap.add_argument("--seed-base", type=int, default=1)
ap.add_argument("--bootstrap", type=int, default=1000)
ap.add_argument("--smoke", action="store_true")
ap.add_argument("--out", required=True)
a = ap.parse_args()
time.sleep(float(os.environ.get("FAKE_GATE_SLEEP", "0")))
if os.environ.get("FAKE_GATE_FAIL"):
    print("fake gate boom: simulated failure", file=sys.stderr)
    sys.exit(3)
panel = {"model_mean_rank": 2.5, "bot_mean_rank": 4.5, "model_top4": 0.9,
         "model_win": 0.3, "mean_diff": -2.0, "ci_low": -2.5, "ci_high": -1.5,
         "illegal": 0, "truncated": 0}
with open(a.out, "w", encoding="utf-8") as f:
    json.dump({"passed": False, "panels": [panel]}, f)
print("fake gate ok")
'''


def _fake_gate(tmp_path: Path) -> str:
    p = tmp_path / "fake_c0_gate.py"
    p.write_text(FAKE_GATE, encoding="utf-8")
    return str(p)


def _make_runner(tmp_path: Path, logs: list, gate: str) -> AsyncEvalRunner:
    return AsyncEvalRunner(
        out_dir=str(tmp_path / "run"), root=str(tmp_path), arch="tiny",
        device="cpu", games=8, seats=2, seed_base=1, gate_script=gate,
        python=sys.executable, log=logs.append)


def _ckpt(tmp_path: Path) -> str:
    p = tmp_path / "ckpt.pt"
    p.write_bytes(b"dummy")
    return str(p)


def _read_history(tmp_path: Path) -> list:
    path = tmp_path / "run" / "eval" / "history.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)["evals"]


def _wait(pred, timeout: float = 20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_history_append_keeps_schema_and_previous_records(tmp_path, monkeypatch):
    """结果落盘字段与同步路径一致；续训时已有 evals 不被覆盖。"""
    monkeypatch.setenv("FAKE_GATE_SLEEP", "0")
    gate = _fake_gate(tmp_path)
    eval_dir = tmp_path / "run" / "eval"
    eval_dir.mkdir(parents=True)
    prev = {"decisions": 100, "rc": 1, "seconds": 1.0,
            "mean_rank": 3.5, "bot_mean_rank": 4.0, "top4": 0.8, "win": 0.2,
            "mean_diff": -0.5, "ci_low": -1.0, "ci_high": 0.0,
            "illegal": 0, "truncated": 0, "passed": False}
    (eval_dir / "history.json").write_text(json.dumps({"evals": [prev]}),
                                           encoding="utf-8")

    logs: list = []
    got: list = []
    runner = _make_runner(tmp_path, logs, gate)
    runner.on_result = got.append
    try:
        assert runner.submit(2000, _ckpt(tmp_path)) is True
        assert _wait(lambda: runner.completed == 1)
    finally:
        runner.close()

    hist = _read_history(tmp_path)
    assert len(hist) == 2
    assert hist[0]["decisions"] == 100          # 旧记录保留
    rec = hist[1]
    assert rec["decisions"] == 2000
    assert rec["rc"] == 0
    assert rec["mean_rank"] == pytest.approx(2.5)
    assert rec["bot_mean_rank"] == pytest.approx(4.5)
    assert rec["top4"] == pytest.approx(0.9)
    assert rec["win"] == pytest.approx(0.3)
    assert rec["mean_diff"] == pytest.approx(-2.0)
    assert rec["ci_low"] == pytest.approx(-2.5)
    assert rec["ci_high"] == pytest.approx(-1.5)
    assert rec["illegal"] == 0 and rec["truncated"] == 0
    assert rec["passed"] is False
    assert "error" not in rec
    assert got and got[0]["decisions"] == 2000
    assert any("[eval-async] dec=2000" in m for m in logs)
    assert runner.stats()["completed"] == 1
    assert runner.stats()["failed"] == 0


def test_concurrent_submit_is_skipped(tmp_path, monkeypatch):
    """并发上限 1：第一个还在跑时，第二个直接跳过并写 eval_skipped。"""
    monkeypatch.setenv("FAKE_GATE_SLEEP", "0.8")
    gate = _fake_gate(tmp_path)
    logs: list = []
    runner = _make_runner(tmp_path, logs, gate)
    try:
        assert runner.submit(1000, _ckpt(tmp_path)) is True
        assert runner.running() is True
        assert runner.submit(2000, _ckpt(tmp_path)) is False
        hist = _read_history(tmp_path)          # 跳过记录已同步落盘
        assert len(hist) == 1
        assert hist[0]["decisions"] == 2000
        assert hist[0]["skipped"] is True
        assert hist[0]["eval_skipped"] is True
        assert hist[0]["reason"] == "eval_in_flight"
        assert "mean_rank" not in hist[0]
        assert runner.stats()["skipped"] == 1
        assert _wait(lambda: runner.completed == 1)
    finally:
        runner.close()
    hist = _read_history(tmp_path)
    assert [r["decisions"] for r in hist] == [1000, 2000]   # 按 decisions 排序
    assert hist[0]["mean_rank"] == pytest.approx(2.5)
    assert hist[1]["skipped"] is True
    assert runner.stats()["submitted"] == 1
    assert runner.stats()["completed"] == 1


def test_sequential_submit_after_completion(tmp_path, monkeypatch):
    """一个评测完成后必须能立刻提交下一个（_proc 被正确回收，上限 1 不粘住）。"""
    monkeypatch.setenv("FAKE_GATE_SLEEP", "0")
    gate = _fake_gate(tmp_path)
    logs: list = []
    runner = _make_runner(tmp_path, logs, gate)
    try:
        assert runner.submit(10, _ckpt(tmp_path)) is True
        assert _wait(lambda: runner.completed == 1)
        assert runner.submit(20, _ckpt(tmp_path)) is True
        assert _wait(lambda: runner.completed == 2)
    finally:
        runner.close()
    hist = _read_history(tmp_path)
    assert [r["decisions"] for r in hist] == [10, 20]
    assert all(r.get("mean_rank") == pytest.approx(2.5) for r in hist)
    assert runner.stats()["submitted"] == 2


def test_failure_is_recorded_not_raised(tmp_path, monkeypatch):
    """子进程非 0 / 无 JSON -> history 的 error 字段 + stderr 尾部；训练不崩。"""
    monkeypatch.setenv("FAKE_GATE_SLEEP", "0")
    monkeypatch.setenv("FAKE_GATE_FAIL", "1")
    gate = _fake_gate(tmp_path)
    logs: list = []
    runner = _make_runner(tmp_path, logs, gate)
    try:
        assert runner.submit(3000, _ckpt(tmp_path)) is True
        assert _wait(lambda: runner.failed == 1)
    finally:
        runner.close()
    rec = _read_history(tmp_path)[-1]
    assert rec["decisions"] == 3000
    assert rec["rc"] == 3
    assert "error" in rec and rec["error"]
    assert "mean_rank" not in rec
    text = "\n".join(logs)
    assert "[eval-async] FAILED dec=3000" in text
    assert "fake gate boom" in text          # stderr 尾部
    assert runner.stats()["failed"] == 1
    assert runner.stats()["completed"] == 1


def test_parse_c0_result_error_payload(tmp_path):
    """c0_gate 用 JSON 报错（argparse/引擎异常）时也要落 error。"""
    out = tmp_path / "c0.json"
    out.write_text(json.dumps({"passed": False, "error": "argparse: bad flag"}),
                   encoding="utf-8")
    rec = parse_c0_result(42, 2, 0.5, str(out))
    assert rec["decisions"] == 42 and rec["rc"] == 2
    assert rec["error"] == "argparse: bad flag"
    assert "mean_rank" not in rec
