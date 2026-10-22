"""评测器测试：固定种子 / 多进程一致性 / 指标正确性 / CLI。"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import pytest

from hsbg.rl.evaluate import (
    EvalSummary,
    build_arg_parser,
    comparison_table,
    evaluate,
    evaluate_many,
    main as evaluate_main,
)

MOCK = {"backend": "mock", "mock_kwargs": {"seed": 0}}


# ══════════════════════════════════════════════════════════════════════
# 指标
# ══════════════════════════════════════════════════════════════════════


def test_evaluate_basic_metrics() -> None:
    summary = evaluate("random", episodes=6, seed=3, **MOCK)
    assert isinstance(summary, EvalSummary)
    assert summary.name == "random"
    assert summary.workers == 1
    s = summary.summary()
    assert int(s["episodes"]) == 6
    assert len(summary.result.ranks) == 6
    assert all(1 <= r <= 8 for r in summary.result.ranks)
    assert 1.0 <= s["mean_rank"] <= 8.0
    assert s["mean_rank"] == pytest.approx(statistics.fmean(summary.result.ranks))
    assert s["mean_rank_ci_low"] <= s["mean_rank_ci_high"]
    assert 0.0 <= s["win_rate"] <= 1.0
    assert 0.0 <= s["top_half_rate"] <= 1.0
    assert s["games_per_second"] > 0
    assert s["steps_per_second"] > 0
    assert s["wall_seconds"] >= 0
    dist = summary.rank_distribution()
    assert abs(sum(dist.values()) - 1.0) < 1e-6
    for rank in range(1, 9):
        assert rank in dist
    assert summary.episode_seeds == [3, 4, 5, 6, 7, 8]
    assert "by_rank" in summary.detailed()


def test_evaluate_deterministic_same_seed() -> None:
    a = evaluate("random", episodes=5, seed=11, **MOCK)
    b = evaluate("random", episodes=5, seed=11, **MOCK)
    assert a.result.ranks == b.result.ranks
    assert a.episode_seeds == b.episode_seeds
    assert a.result.rewards == pytest.approx(b.result.rewards)


def test_evaluate_workers_consistent() -> None:
    single = evaluate("random", episodes=6, seed=2, workers=1, **MOCK)
    parallel = evaluate("random", episodes=6, seed=2, workers=3, **MOCK)
    assert single.episode_seeds == parallel.episode_seeds
    assert single.result.ranks == parallel.result.ranks


def test_evaluate_explicit_seeds_override() -> None:
    summary = evaluate("heuristic", episodes=999, seed=0, seeds=[5, 9, 42], **MOCK)
    assert summary.episode_seeds == [5, 9, 42]
    assert len(summary.result.ranks) == 3


def test_evaluate_heuristic_and_comparison() -> None:
    summaries = evaluate_many(["random", "heuristic"], episodes=4, seed=1,
                              num_players=8, **MOCK)
    assert len(summaries) == 2
    table = comparison_table(summaries)
    assert "random" in table and "heuristic" in table
    assert "mean_rank" in table
    for summary in summaries:
        assert int(summary.summary()["episodes"]) == 4


def test_eval_summary_to_dict_and_save(tmp_path: Path) -> None:
    summary = evaluate("random", episodes=3, seed=0, **MOCK)
    payload = summary.to_dict()
    text = json.dumps(payload)
    assert len(text) > 100
    assert payload["episode_seeds"] == [0, 1, 2]
    assert set(payload["summary"]) >= {"mean_rank", "win_rate", "top_half_rate"}
    # 配置 + per-episode rank（回归对比用）
    assert payload["config"]["seed"] == 0
    assert payload["config"]["episodes"] == 3
    assert payload["config"]["policy"] == "random"
    assert len(payload["episodes"]) == 3
    assert [item["rank"] for item in payload["episodes"]] == payload["ranks"]
    assert [item["seed"] for item in payload["episodes"]] == [0, 1, 2]
    for item in payload["episodes"]:
        assert set(item) >= {"episode_id", "seed", "rank", "reward", "steps",
                             "turns", "reason"}
    out = summary.save(tmp_path / "eval.json")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["summary"]["mean_rank"] == pytest.approx(
        payload["summary"]["mean_rank"])
    assert loaded["rank_distribution"].keys() == payload["rank_distribution"].keys()
    assert loaded["config"]["episodes"] == 3


def test_eval_summary_format() -> None:
    summary = evaluate("random", episodes=3, seed=0, **MOCK)
    text = summary.format()
    assert "mean_rank" in text
    assert "rank_dist" in text
    assert "games/s" in text


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def test_evaluate_cli(capsys) -> None:
    code = evaluate_main([
        "--policy", "random", "--episodes", "4", "--seed", "0",
        "--backend", "mock", "--workers", "1",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "mean_rank" in out
    assert "games/s" in out
    assert "rank_dist" in out


def test_evaluate_cli_multi_policy_and_json(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "eval.json"
    code = evaluate_main([
        "--policy", "random", "--policy", "heuristic",
        "--episodes", "4", "--seed", "1", "--backend", "mock",
        "--workers", "1", "--out", str(out_path), "--json",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "hsbg.rl.evaluate/v1"
    assert set(payload["config"]) >= {"policy", "episodes", "seed", "backend"}
    assert len(payload["results"]) == 2
    assert {item["name"] for item in payload["results"]} == {"random", "heuristic"}
    for item in payload["results"]:
        assert item["config"]["episodes"] == 4
        assert len(item["episodes"]) == 4
        assert [e["rank"] for e in item["episodes"]] == item["ranks"]
    # --out 与 --json 内容一致
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["schema"] == payload["schema"]
    assert len(saved["results"]) == 2


def test_evaluate_out_json_without_json_flag(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "eval_single.json"
    code = evaluate_main([
        "--policy", "heuristic", "--episodes", "3", "--seed", "2",
        "--backend", "mock", "--workers", "1", "--out", str(out_path),
    ])
    assert code == 0
    assert "results ->" in capsys.readouterr().out
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["schema"] == "hsbg.rl.evaluate/v1"
    assert len(saved["results"]) == 1
    result = saved["results"][0]
    assert len(result["episodes"]) == 3
    assert result["config"]["seed"] == 2


def test_evaluate_cli_worker_and_seeds_args() -> None:
    parser = build_arg_parser()
    args = parser.parse_args([
        "--policy", "random", "--workers", "2", "--seeds", "1,2,3",
        "--backend", "mock",
    ])
    assert args.workers == 2 and args.seeds == "1,2,3"
    assert args.policy == ["random"]


# ══════════════════════════════════════════════════════════════════════
# 真环境冒烟（少量局；不可用则跳过）
# ══════════════════════════════════════════════════════════════════════


def test_evaluate_real_env_smoke() -> None:
    from hsbg.rl.envs import real_env_available

    if not real_env_available():
        pytest.skip("真实环境不可用")
    try:
        summary = evaluate("random", episodes=2, seed=0, backend="real",
                           max_steps_per_episode=800)
    except Exception as exc:  # noqa: BLE001 - 环境层演进中
        pytest.skip(f"真实环境评测失败: {exc}")
    assert int(summary.summary()["episodes"]) == 2
    assert all(1 <= r <= 8 for r in summary.result.ranks)
    assert math.isfinite(summary.summary()["mean_rank"])


# ══════════════════════════════════════════════════════════════════════
# 引擎感知教师（teacher）评测
# ══════════════════════════════════════════════════════════════════════


def test_teacher_evaluate_requires_real_env() -> None:
    with pytest.raises(ValueError, match="teacher"):
        evaluate("teacher", episodes=1, backend="mock")


def test_teacher_evaluate_cli_reports_clear_error(capsys) -> None:
    code = evaluate_main([
        "--policy", "teacher", "--episodes", "1", "--backend", "mock",
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "teacher" in err


def test_teacher_evaluate_real_smoke() -> None:
    from hsbg.rl.envs import real_env_available

    if not real_env_available():
        pytest.skip("真实环境不可用")
    try:
        summary = evaluate("teacher", episodes=2, seed=0, backend="real",
                           max_steps_per_episode=1200)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"teacher 评测失败: {exc}")
    assert int(summary.summary()["episodes"]) == 2
    assert all(1 <= r <= 8 for r in summary.result.ranks)
    assert summary.config["policy"] == "teacher"
    assert summary.errors == 0
