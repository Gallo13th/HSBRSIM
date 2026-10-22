"""scripts/ 入口冒烟测试：训练脚本可跑通、产物可被评测脚本加载。

用 ``--env mock`` 保证快且确定；真环境由 Lead 集成时单独冒烟。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parent.parent


def _load_script(relpath: str, name: str):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_train_ppo_script_mock(tmp_path) -> None:
    script = _load_script("scripts/train_ppo.py", "hsbg_script_train_ppo")
    out = tmp_path / "ppo"
    code = script.main([
        "--total-steps", "128",
        "--num-envs", "2",
        "--n-steps", "32",
        "--epochs", "2",
        "--minibatch-size", "32",
        "--device", "cpu",
        "--env", "mock",
        "--out", str(out),
        "--eval-every", "64",
        "--eval-games", "2",
        "--save-every", "64",
        "--quiet",
    ])
    assert code == 0
    assert (out / "policy_final.pt").exists()
    assert (out / "train_log.csv").exists()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["steps"] >= 128
    assert summary["params"] > 0
    assert len(summary["history"]) >= 1
    # 训练日志里 loss 确实在变
    losses = {row["policy_loss"] for row in summary["history"]}
    assert len(losses) >= 1
    # 评测日志（启用 --eval-every）
    assert (out / "eval_log.csv").exists()
    # 续训：--init-from 复用 checkpoint
    out2 = tmp_path / "ppo_resume"
    code = script.main([
        "--total-steps", "64", "--num-envs", "2", "--n-steps", "16",
        "--epochs", "1", "--device", "cpu", "--env", "mock",
        "--out", str(out2), "--init-from", str(out / "policy_final.pt"), "--quiet",
    ])
    assert code == 0
    assert (out2 / "policy_final.pt").exists()


def test_train_bc_script_mock(tmp_path) -> None:
    script = _load_script("scripts/train_bc.py", "hsbg_script_train_bc")
    out = tmp_path / "bc"
    code = script.main([
        "--episodes", "4",
        "--num-envs", "2",
        "--epochs", "4",
        "--batch-size", "32",
        "--device", "cpu",
        "--env", "mock",
        "--out", str(out),
        "--quiet",
    ])
    assert code == 0
    assert (out / "policy_bc.pt").exists()
    assert (out / "bc_dataset.pkl").exists()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["dataset_samples"] > 0
    assert 0.0 <= summary["val_accuracy"] <= 1.0


def test_evaluate_script_mock(tmp_path) -> None:
    train = _load_script("scripts/train_ppo.py", "hsbg_script_train_ppo_eval")
    out = tmp_path / "ppo"
    assert train.main([
        "--total-steps", "64", "--num-envs", "2", "--n-steps", "32",
        "--epochs", "1", "--device", "cpu", "--env", "mock",
        "--out", str(out), "--quiet",
    ]) == 0
    evaluate = _load_script("scripts/evaluate_policy.py", "hsbg_script_evaluate")
    eval_out = tmp_path / "eval"
    code = evaluate.main([
        "--checkpoint", str(out / "policy_final.pt"),
        "--games", "2",
        "--baseline", "random",
        "--num-envs", "2",
        "--device", "cpu",
        "--env", "mock",
        "--out", str(eval_out),
    ])
    assert code == 0
    results = json.loads((eval_out / "eval_results.json").read_text(encoding="utf-8"))
    assert {row["agent"] for row in results["results"]} == {"policy", "random"}
    for row in results["results"]:
        assert row["games"] >= 1
        assert 1.0 <= row["mean_rank"] <= 8.0
