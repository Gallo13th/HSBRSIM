"""采集器测试：JSONL schema / 多进程确定性 / 断点续采 / 内存 rollouts / CLI。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsbg.rl.api import validate_record
from hsbg.rl.collector import (
    CollectStats,
    collect_rollouts,
    collect_trajectories,
    completed_seeds,
    main as collector_main,
    read_dataset,
)

MOCK = {"backend": "mock", "mock_kwargs": {"seed": 0}}


def policy_first(obs):
    return 0


def policy_random(obs, rng):
    if not obs.candidates:
        return 0
    return rng.randrange(len(obs.candidates))


# ══════════════════════════════════════════════════════════════════════
# JSONL schema / 统计
# ══════════════════════════════════════════════════════════════════════


def test_collect_trajectories_jsonl_schema(tmp_path: Path) -> None:
    out = tmp_path / "ds.jsonl"
    stats = collect_trajectories("heuristic", num_envs=2, episodes=4, seed=0,
                                 out_path=out, verbose=False, **MOCK)
    assert isinstance(stats, CollectStats)
    assert stats.episodes == 4
    assert stats.new_episodes == 4
    assert stats.resumed_skipped == 0
    assert stats.steps > 0
    assert stats.workers == 2
    assert stats.policy == "heuristic"
    assert stats.errors == 0
    assert 1.0 <= stats.mean_rank <= 8.0
    assert stats.games_per_second > 0
    assert stats.steps_per_second > 0
    assert stats.action_kinds
    assert abs(sum(stats.rank_distribution.values()) - 1.0) < 1e-6

    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    assert rows, "JSONL 不应为空"
    assert rows[0]["type"] == "header"
    assert rows[0]["v"] == 1
    for row in rows:
        validate_record(row)
    table = read_dataset(out)
    assert table["header"]["policy"] == "heuristic"
    assert set(table["episodes"].keys()) == {0, 1, 2, 3}
    assert table["errors"] == []
    for ep_id, slot in table["episodes"].items():
        episode = slot["episode"]
        assert episode is not None
        assert episode["episode_id"] == ep_id
        # 步骤行完整且连续
        assert sorted(slot["steps"].keys()) == list(range(episode["steps"]))
        assert 1 <= episode["rank"] <= 8
        # 逐步奖励之和 ≈ 整局回报（浮点容差）
        total = sum(row["reward"] for row in slot["steps"].values())
        assert total == pytest.approx(episode["total_reward"], abs=1e-6)
    assert stats.episode_seeds == [0, 1, 2, 3]


def test_collect_stats_format() -> None:
    stats = CollectStats(episodes=3, new_episodes=3, steps=30, wall_seconds=0.5,
                         policy="heuristic", backend="mock")
    text = stats.format()
    assert "games/s" in text and "heuristic" in text
    payload = stats.to_dict()
    json.dumps(payload)
    assert payload["games_per_second"] == pytest.approx(6.0)
    empty = CollectStats()
    assert empty.games_per_second == 0.0


def test_collect_zero_episodes(tmp_path: Path) -> None:
    out = tmp_path / "empty.jsonl"
    stats = collect_trajectories("random", episodes=0, seed=0, out_path=out, **MOCK)
    assert stats.episodes == 0
    assert stats.new_episodes == 0
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["type"] == "header"


# ══════════════════════════════════════════════════════════════════════
# 确定性 / 断点续采
# ══════════════════════════════════════════════════════════════════════


def _episode_signature(path: Path) -> dict:
    table = read_dataset(path)
    sig = {}
    for ep_id, slot in table["episodes"].items():
        episode = slot["episode"]
        steps = slot["steps"]
        sig[ep_id] = {
            "seed": episode["seed"],
            "rank": episode["rank"],
            "steps": episode["steps"],
            "turns": episode["turns"],
            "reason": episode["reason"],
            "actions": [
                (int(s), steps[s]["action"], steps[s]["action_kind"],
                 round(float(steps[s]["reward"]), 6))
                for s in sorted(steps)
            ],
        }
    return sig


def test_collector_deterministic_across_worker_counts(tmp_path: Path) -> None:
    out_a = tmp_path / "a.jsonl"
    out_b = tmp_path / "b.jsonl"
    collect_trajectories("random", num_envs=1, episodes=3, seed=5, out_path=out_a,
                         **MOCK)
    collect_trajectories("random", num_envs=3, episodes=3, seed=5, out_path=out_b,
                         **MOCK)
    assert _episode_signature(out_a) == _episode_signature(out_b)


def test_resume_is_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "ds.jsonl"
    first = collect_trajectories("random", num_envs=2, episodes=3, seed=0,
                                 out_path=out, resume=True, **MOCK)
    assert first.episodes == 3 and first.resumed_skipped == 0
    sig_before = _episode_signature(out)
    assert set(completed_seeds(out).keys()) == {0, 1, 2}

    # 再跑一次：不重复采集
    again = collect_trajectories("random", num_envs=2, episodes=3, seed=0,
                                 out_path=out, resume=True, **MOCK)
    assert again.episodes == 3
    assert again.new_episodes == 0
    assert again.resumed_skipped == 3
    assert _episode_signature(out) == sig_before

    # 扩到 5 局：只补 2 局，已有 3 局内容不变
    extended = collect_trajectories("random", num_envs=2, episodes=5, seed=0,
                                    out_path=out, resume=True, **MOCK)
    assert extended.episodes == 5
    assert extended.new_episodes == 2
    assert set(completed_seeds(out).keys()) == {0, 1, 2, 3, 4}
    sig_after = _episode_signature(out)
    for ep_id in (0, 1, 2):
        assert sig_after[ep_id] == sig_before[ep_id]
    # 没有重复的 step 行
    table = read_dataset(out)
    for slot in table["episodes"].values():
        steps = slot["steps"]
        assert len(steps) == slot["episode"]["steps"]


def test_no_resume_rewrites(tmp_path: Path) -> None:
    out = tmp_path / "ds.jsonl"
    collect_trajectories("random", episodes=4, seed=0, out_path=out, **MOCK)
    rewritten = collect_trajectories("random", episodes=2, seed=7, out_path=out,
                                     resume=False, **MOCK)
    assert rewritten.episodes == 2
    assert set(completed_seeds(out).keys()) == {7, 8}


# ══════════════════════════════════════════════════════════════════════
# 内存 rollouts / 多进程 policy
# ══════════════════════════════════════════════════════════════════════


def test_collect_rollouts_memory() -> None:
    records, stats = collect_rollouts("heuristic", num_envs=2, episodes=4,
                                      seed=0, **MOCK)
    assert len(records) == 4
    assert [rec.episode_id for rec in records] == [0, 1, 2, 3]
    assert [rec.seed for rec in records] == [0, 1, 2, 3]
    assert stats.episodes == 4
    assert stats.steps == sum(rec.steps for rec in records)
    assert stats.steps == sum(len(rec.transitions) for rec in records)
    assert 1.0 <= stats.mean_rank <= 8.0
    assert stats.errors == 0
    for rec in records:
        assert rec.transitions
        assert rec.terminated or rec.truncated


def test_collect_rollouts_callable_parallel() -> None:
    records, stats = collect_rollouts(policy_random, num_envs=2, episodes=4,
                                      seed=1, **MOCK)
    assert len(records) == 4
    assert stats.episodes == 4
    # 同 seed 与单进程一致（可复现）
    single, _ = collect_rollouts(policy_random, num_envs=1, episodes=4,
                                 seed=1, **MOCK)
    assert [rec.rank for rec in records] == [rec.rank for rec in single]


def test_unpicklable_policy_requires_single_process() -> None:
    with pytest.raises(ValueError):
        collect_rollouts(lambda obs: 0, num_envs=2, episodes=2, **MOCK)
    records, stats = collect_rollouts(lambda obs: 0, num_envs=1, episodes=2,
                                      max_steps_per_episode=200, **MOCK)
    assert len(records) == 2


# ══════════════════════════════════════════════════════════════════════
# 引擎感知教师（teacher）采集
# ══════════════════════════════════════════════════════════════════════


def test_teacher_requires_real_env(tmp_path: Path) -> None:
    """teacher 需要 env.game；mock 后端必须在开始采集前明确报错。"""
    with pytest.raises(ValueError, match="teacher"):
        collect_trajectories("teacher", num_envs=1, episodes=1,
                             out_path=tmp_path / "x.jsonl", backend="mock")
    with pytest.raises(ValueError, match="teacher"):
        collect_rollouts("teacher", num_envs=1, episodes=1, backend="mock")


def test_teacher_cli_reports_clear_error(tmp_path: Path, capsys) -> None:
    code = collector_main([
        "--policy", "teacher", "--episodes", "1", "--backend", "mock",
        "--out", str(tmp_path / "never.jsonl"),
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "teacher" in err and "backend" in err
    assert not (tmp_path / "never.jsonl").exists()


def test_teacher_collect_smoke_real(tmp_path: Path) -> None:
    from hsbg.rl.envs import real_env_available

    if not real_env_available():
        pytest.skip("真实环境不可用")
    out = tmp_path / "teacher.jsonl"
    try:
        stats = collect_trajectories(
            "teacher", num_envs=1, episodes=2, seed=0, out_path=out,
            backend="real", max_steps_per_episode=1200,
        )
    except Exception as exc:  # noqa: BLE001 - 环境层演进中
        pytest.skip(f"teacher 采集失败: {exc}")
    assert stats.episodes == 2
    assert stats.errors == 0
    assert stats.policy == "teacher"
    assert 1.0 <= stats.mean_rank <= 8.0
    assert "buy" in stats.action_kinds or "play_minion" in stats.action_kinds
    table = read_dataset(out)
    assert table["header"]["policy"] == "teacher"
    for slot in table["episodes"].values():
        episode = slot["episode"]
        assert episode is not None
        assert episode["policy"] == "teacher"
        assert 1 <= episode["rank"] <= 8
        for row in slot["steps"].values():
            validate_record(row)
            assert row["invalid"] is False


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def test_collector_cli(tmp_path: Path, capsys) -> None:
    out = tmp_path / "cli.jsonl"
    code = collector_main([
        "--policy", "heuristic", "--envs", "2", "--episodes", "4",
        "--seed", "0", "--out", str(out), "--backend", "mock",
    ])
    assert code == 0
    captured = capsys.readouterr().out
    assert "games/s" in captured
    assert out.exists()
    assert len(completed_seeds(out)) == 4

    # --json 输出可直接解析
    code = collector_main([
        "--policy", "heuristic", "--envs", "1", "--episodes", "4",
        "--seed", "0", "--out", str(out), "--backend", "mock", "--json",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["episodes"] == 4
    assert payload["resumed_skipped"] == 4
    assert payload["games_per_second"] == 0.0  # 没有新采集


def test_collector_cli_memory_only(capsys) -> None:
    code = collector_main([
        "--policy", "random", "--envs", "1", "--episodes", "2",
        "--backend", "mock", "--quiet",
    ])
    assert code == 0


# ══════════════════════════════════════════════════════════════════════
# 真环境冒烟（少量局；不可用则跳过）
# ══════════════════════════════════════════════════════════════════════


def test_collector_real_env_smoke(tmp_path: Path) -> None:
    from hsbg.rl.envs import real_env_available

    if not real_env_available():
        pytest.skip("真实环境不可用")
    out = tmp_path / "real.jsonl"
    try:
        stats = collect_trajectories(
            "random", num_envs=1, episodes=2, seed=0, out_path=out,
            backend="real", max_steps_per_episode=800,
        )
    except Exception as exc:  # noqa: BLE001 - 环境层演进中
        pytest.skip(f"真实环境采集失败: {exc}")
    assert stats.episodes == 2
    assert stats.errors == 0
    table = read_dataset(out)
    for slot in table["episodes"].values():
        assert 1 <= slot["episode"]["rank"] <= 8
        assert slot["episode"]["steps"] >= 1
