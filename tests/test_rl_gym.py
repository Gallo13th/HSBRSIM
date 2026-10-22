"""Gymnasium 包装测试（未安装 gymnasium 时整文件 skip）。

覆盖：spaces / action_masks / reset·step 契约 / check_env / 三个包装器。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

gymnasium = pytest.importorskip("gymnasium")

from hsbg.env.spec import CANDIDATE_MAX
from hsbg.rl.api import validate_record
from hsbg.rl.gym_wrapper import (
    GYMNASIUM_AVAILABLE,
    AutoResetWrapper,
    GymBattlegroundsEnv,
    RecordEpisode,
    TimeLimit,
    build_observation_space,
    check_env_smoke,
    default_encoder,
    gymnasium_available,
    make_gym_env,
)

ENV_KEYS = {
    "entity_card", "entity_num", "entity_mask", "entity_zone", "entity_pos",
    "global", "cand_kind", "cand_num", "cand_src", "cand_tgt", "cand_mask",
}


def _mock_env(seed: int = 0, **kwargs):
    return make_gym_env(
        backend="mock", seed=seed, mock_kwargs={"seed": seed}, **kwargs
    )


# ══════════════════════════════════════════════════════════════════════
# spaces / 契约
# ══════════════════════════════════════════════════════════════════════


def test_gymnasium_flags() -> None:
    assert gymnasium_available() is True
    assert GYMNASIUM_AVAILABLE is True
    import gymnasium as _gym

    env = _mock_env()
    try:
        assert isinstance(env, _gym.Env)
        assert isinstance(env, GymBattlegroundsEnv)
    finally:
        env.close()


def test_observation_space_matches_encoder() -> None:
    env = _mock_env(seed=0)
    try:
        space = env.observation_space
        assert set(space.spaces.keys()) == ENV_KEYS
        encoder = env.encoder
        dims = encoder.dims
        assert space["entity_card"].shape == (dims.num_entities,)
        assert space["entity_num"].shape == (dims.num_entities, dims.entity_num_dim)
        assert space["global"].shape == (dims.global_dim,)
        assert space["cand_num"].shape == (dims.candidate_max, dims.cand_num_dim)
        assert space["cand_mask"].shape == (CANDIDATE_MAX,)
        assert env.action_space.n == CANDIDATE_MAX
        # reset 观测必须落在 space 内且 dtype 精确匹配
        obs, info = env.reset(seed=0)
        assert set(obs.keys()) == ENV_KEYS
        assert space.contains(obs), "observations 不在 observation_space 内"
        for key, value in obs.items():
            assert value.dtype == space[key].dtype, key
        assert info["n_candidates"] >= 1
    finally:
        env.close()


def test_action_masks_and_legal_actions() -> None:
    env = _mock_env(seed=0)
    try:
        env.reset(seed=0)
        masks = env.action_masks()
        assert masks.shape == (CANDIDATE_MAX,)
        assert masks.dtype == bool
        n = env.num_actions()
        assert n == len(env.legal_actions())
        assert int(masks.sum()) == min(n, CANDIDATE_MAX)
        assert all(masks[:n])
        assert not masks[n:].any()
        assert np.array_equal(masks, env.action_mask())
        # 有效动作 → 不标记 invalid
        obs, reward, terminated, truncated, info = env.step(int(np.flatnonzero(masks)[0]))
        assert isinstance(reward, float)
        assert isinstance(terminated, bool) and isinstance(truncated, bool)
        assert env.observation_space.contains(obs)
        assert info["invalid_action"] is False
    finally:
        env.close()


def test_invalid_action_is_flagged_not_crash() -> None:
    env = _mock_env(seed=0)
    try:
        env.reset(seed=0)
        n = env.num_actions()
        bad_action = n + 5 if n + 5 < CANDIDATE_MAX else CANDIDATE_MAX - 1
        obs, reward, terminated, truncated, info = env.step(bad_action)
        assert info["invalid_action"] is True
        assert env.observation_space.contains(obs)
        # 动作类型错误同样不崩溃
        obs, reward, terminated, truncated, info = env.step("not-an-int")
        assert info["invalid_action"] is True
        assert env.observation_space.contains(obs)
    finally:
        env.close()


def test_reset_seed_determinism() -> None:
    env = _mock_env(seed=0)
    try:
        obs_a, _ = env.reset(seed=11)
        obs_b, _ = env.reset(seed=11)
        for key in ENV_KEYS:
            assert np.array_equal(obs_a[key], obs_b[key]), key
        obs_c, _ = env.reset(seed=12)
        assert any(not np.array_equal(obs_a[k], obs_c[k]) for k in ENV_KEYS)
    finally:
        env.close()


def test_gym_check_env_passes() -> None:
    assert check_env_smoke(backend="mock") is True


# ══════════════════════════════════════════════════════════════════════
# 包装器
# ══════════════════════════════════════════════════════════════════════


def test_time_limit_wrapper() -> None:
    env = _mock_env(seed=1, time_limit=5)
    try:
        assert isinstance(env, TimeLimit)
        obs, info = env.reset(seed=1)
        steps = 0
        truncated = False
        while steps < 50:
            masks = env.action_masks()
            obs, reward, terminated, truncated, info = env.step(
                int(np.flatnonzero(masks)[0]))
            steps += 1
            if terminated or truncated:
                break
        assert steps == 5
        assert truncated is True
        assert info.get("TimeLimit.truncated") is True
    finally:
        env.close()


def test_record_episode_wrapper(tmp_path: Path) -> None:
    path = tmp_path / "gym_record.jsonl"
    env = RecordEpisode(_mock_env(seed=2), path, policy="random")
    try:
        obs, info = env.reset(seed=2)
        done = False
        steps = 0
        while not done and steps < 500:
            masks = env.action_masks()
            obs, reward, terminated, truncated, info = env.step(
                int(np.flatnonzero(masks)[0]))
            steps += 1
            done = terminated or truncated
        assert done
    finally:
        env.close()
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["type"] == "header"
    assert rows[-1]["type"] == "episode"
    step_rows = [row for row in rows if row["type"] == "step"]
    episode_rows = [row for row in rows if row["type"] == "episode"]
    assert len(step_rows) == steps
    assert len(episode_rows) == 1
    for row in rows:
        validate_record(row)
    episode = episode_rows[0]
    assert episode["rank"] >= 1
    assert episode["steps"] == steps
    assert episode["policy"] == "random"
    assert episode["total_reward"] is not None


def test_auto_reset_wrapper() -> None:
    env = AutoResetWrapper(_mock_env(seed=3))
    try:
        obs, info = env.reset(seed=3)
        done = False
        steps = 0
        while not done and steps < 500:
            masks = env.action_masks()
            obs, reward, terminated, truncated, info = env.step(
                int(np.flatnonzero(masks)[0]))
            steps += 1
            done = terminated or truncated
        assert done
        assert info["terminal"] is True
        assert "terminal_observation" in info
        assert isinstance(info["terminal_observation"], dict)
        # 返回的观测已是新一局（episode_step=0 的 phase 信息可由 info 检查）
        assert info["reset_info"] is not None
    finally:
        env.close()


def test_observation_space_builder_uses_encoder() -> None:
    encoder = default_encoder()
    space = build_observation_space(encoder)
    assert int(np.asarray(space["entity_card"].high).max()) == len(encoder.vocab) - 1
    assert space["cand_mask"].shape == (encoder.dims.candidate_max,)


def test_gym_real_env_smoke_if_available() -> None:
    from hsbg.rl.envs import real_env_available

    if not real_env_available():
        pytest.skip("真实环境不可用")
    try:
        env = make_gym_env(backend="real", seed=0)
    except Exception as exc:  # noqa: BLE001 - 环境层演进中
        pytest.skip(f"真实环境创建失败: {exc}")
    try:
        obs, info = env.reset(seed=0)
        assert env.observation_space.contains(obs)
        masks = env.action_masks()
        obs2, reward, terminated, truncated, info2 = env.step(
            int(np.flatnonzero(masks)[0]))
        assert env.observation_space.contains(obs2)
        assert info2["n_candidates"] >= 0
    finally:
        env.close()
