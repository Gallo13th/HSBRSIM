"""RL 接口层测试：协议适配 / 动作解析 / 单局驱动 / JSONL 记录 / policy 注册表。"""

from __future__ import annotations

import json
import pickle
import random

import numpy as np
import pytest

from hsbg.env.spec import CandidateAction, EntityToken, Observation, PendingChoice
from hsbg.rl.api import (
    API_VERSION,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    EpisodeRecord,
    EnvLike,
    Policy,
    Transition,
    candidate_index,
    error_record,
    fallback_index,
    header_record,
    obs_digest,
    obs_summary,
    resolve_action,
    run_episode,
    validate_record,
)
from hsbg.rl.envs import (
    MockBattlegroundsEnv,
    env_backend_name,
    make_env,
    real_env_available,
)
from hsbg.rl.policies import (
    BUILTIN_NAMES,
    CallableAdapter,
    CheckpointPolicy,
    EndTurnPolicy,
    FirstLegalPolicy,
    HeuristicPolicy,
    PolicyAdapter,
    RandomPolicy,
    TeacherPolicy,
    as_policy,
    describe_policy,
    ensure_picklable,
    heuristic_score,
    is_picklable,
    make_policy,
    policy_requires_engine,
)

# ══════════════════════════════════════════════════════════════════════
# 模块级策略（多进程 pickle 需要模块级对象）
# ══════════════════════════════════════════════════════════════════════


def pick_first(obs):
    return 0


def pick_random_with_rng(obs, rng):
    if not obs.candidates:
        return 0
    return rng.randrange(len(obs.candidates))


class ActOnlyPolicy:
    """只有 act 策略（用于测试 PolicyAdapter）。"""

    def act(self, obs, *, deterministic=False, rng=None):
        return min(1, max(len(obs.candidates) - 1, 0))


class _Context:
    """上下文管理器式地创建/关闭 mock env。"""

    def __init__(self, seed: int = 0, **kwargs):
        self.env = MockBattlegroundsEnv(seed=seed, **kwargs)

    def __enter__(self):
        return self.env

    def __exit__(self, *exc):
        self.env.close()


# ══════════════════════════════════════════════════════════════════════
# 协议 / 类型
# ══════════════════════════════════════════════════════════════════════


def test_policy_protocol() -> None:
    for policy in (RandomPolicy(0), HeuristicPolicy(0), FirstLegalPolicy(),
                   EndTurnPolicy(), TeacherPolicy(), CallableAdapter(pick_first),
                   as_policy(pick_random_with_rng)):
        assert isinstance(policy, Policy)
        assert isinstance(policy.name, str) and policy.name
        policy.reset()
    assert set(BUILTIN_NAMES) == {
        "random", "heuristic", "first", "end_turn", "teacher",
    }


def test_envlike_protocol(monkeypatch=None) -> None:
    env = MockBattlegroundsEnv(seed=0)
    try:
        assert isinstance(env, EnvLike)
        obs = env.reset(seed=0)
        assert isinstance(obs, Observation)
        out = env.step(obs.candidates[0])
        assert isinstance(out, tuple) and len(out) == 5
    finally:
        env.close()


def test_version_constants() -> None:
    assert SCHEMA_VERSION >= 1
    assert API_VERSION >= 1
    for kind in ("header", "step", "episode", "error"):
        assert kind in REQUIRED_FIELDS


def test_transition_and_record_dataclasses() -> None:
    tr = Transition(obs=Observation(turn=1), action=2, action_kind="buy",
                    reward=0.5, terminated=False, truncated=False, step=0)
    assert tr.step == 0 and tr.rank == -1 and tr.invalid is False
    rec = EpisodeRecord(episode_id=3, seed=103, rank=2, total_reward=1.5,
                        steps=1, transitions=[tr])
    assert len(rec) == 1
    assert rec.episode_key == (3, 103)
    assert rec.action_kinds() == {"buy": 1}
    assert rec.observations() == [tr.obs]


# ══════════════════════════════════════════════════════════════════════
# 动作解析 / 观测摘要
# ══════════════════════════════════════════════════════════════════════


def test_candidate_index_and_resolve_action() -> None:
    obs = Observation(turn=2)
    obs.candidates = (
        CandidateAction(kind="buy", src_zone="tavern", src_slot=0),
        CandidateAction(kind="end_turn"),
    )
    assert candidate_index(0, obs) == 0
    assert candidate_index(1, obs) == 1
    assert candidate_index(5, obs) is None
    assert candidate_index(-1, obs) is None
    assert candidate_index(None, obs) is None
    assert candidate_index(True, obs) is None
    assert candidate_index(np.int64(1), obs) == 1
    assert candidate_index(obs.candidates[0], obs) == 0
    # 非法动作 → 回退 end_turn
    idx, cand, invalid = resolve_action(999, obs)
    assert (idx, invalid) == (1, True)
    assert cand.kind == "end_turn"
    # 无候选
    empty = Observation(turn=1)
    idx2, cand2, invalid2 = resolve_action(0, empty)
    assert idx2 == 0 and cand2 is None and invalid2 is True


def test_fallback_index_prefers_end_turn() -> None:
    obs = Observation(turn=1)
    obs.candidates = (CandidateAction(kind="buy"), CandidateAction(kind="end_turn"))
    assert fallback_index(obs) == 1
    obs2 = Observation(turn=1)
    obs2.candidates = (CandidateAction(kind="buy"), CandidateAction(kind="sell"))
    assert fallback_index(obs2) == 1
    empty = Observation(turn=1)
    assert fallback_index(empty) == 0


def test_obs_summary_jsonable_and_digest() -> None:
    env = MockBattlegroundsEnv(seed=1)
    try:
        obs = env.reset(seed=1)
        summary = obs_summary(obs)
        json.dumps(summary)  # 必须可 JSON 序列化
        assert summary["turn"] == 1
        assert summary["n_candidates"] == len(obs.candidates)
        assert len(summary["candidate_kinds"]) == len(obs.candidates)
        assert "board" in summary
        lean = obs_summary(obs, include_board=False)
        assert "board" not in lean
        digest = obs_digest(obs)
        assert isinstance(digest, str) and len(digest) == 16
        assert obs_digest(obs) == digest  # 稳定
    finally:
        env.close()


def test_obs_summary_extra_whitelist() -> None:
    """ENV_SPEC v2 的 Observation.extra：默认不落盘，显式开启时只带白名单。"""
    from hsbg.rl.api import SUMMARY_EXTRA_KEYS

    obs = Observation(turn=5, extra={
        "frozen_tavern": True,
        "gold_spent_this_turn": 7,
        "quest_progress": 2,
        "big_internal": {"x": list(range(1000))},
        "frozen_tavern_text": "not whitelisted",
    })
    default = obs_summary(obs)
    assert "extra" not in default
    with_extra = obs_summary(obs, include_extra=True)
    assert with_extra["extra"] == {
        "frozen_tavern": True,
        "gold_spent_this_turn": 7,
        "quest_progress": 2,
    }
    assert "big_internal" not in with_extra["extra"]
    assert "frozen_tavern_text" not in with_extra["extra"]
    assert len(json.dumps(with_extra)) < 2000
    assert all(key in SUMMARY_EXTRA_KEYS for key in with_extra["extra"])
    # Transition 也支持 include_extra
    tr = Transition(obs=obs, action=0, action_kind="end_turn")
    assert "extra" not in tr.to_dict()["obs"]
    assert tr.to_dict(include_extra=True)["obs"]["extra"]["frozen_tavern"] is True


# ══════════════════════════════════════════════════════════════════════
# run_episode
# ══════════════════════════════════════════════════════════════════════


def test_run_episode_record_fields() -> None:
    with _Context(seed=0) as env:
        record = run_episode(env, RandomPolicy(0), seed=7, episode_id=5,
                             max_steps=500)
    assert record.episode_id == 5 and record.seed == 7
    assert record.steps == len(record.transitions) > 0
    assert record.turns >= 1
    assert 1 <= record.rank <= record.num_players
    assert record.terminated or record.truncated
    assert record.reason
    assert record.policy == "random"
    total = sum(tr.reward for tr in record.transitions)
    assert record.total_reward == pytest.approx(total)
    assert record.transitions[0].step == 0
    assert record.transitions[-1].step == record.steps - 1
    for tr in record.transitions:
        assert isinstance(tr.obs, Observation)
        assert tr.episode_id == 5 and tr.seed == 7
        assert 0 <= tr.action < max(len(tr.obs.candidates), 1)
        assert tr.action_kind


def test_run_episode_deterministic_same_seed() -> None:
    def rollout() -> list:
        env = MockBattlegroundsEnv(seed=3)
        try:
            rec = run_episode(env, RandomPolicy(0), seed=3, episode_id=0,
                              max_steps=500)
            return [(tr.action, tr.action_kind, round(tr.reward, 6),
                     tr.terminated, tr.truncated) for tr in rec.transitions]
        finally:
            env.close()

    assert rollout() == rollout()


def test_run_episode_invalid_action_fallback() -> None:
    with _Context(seed=0) as env:
        record = run_episode(env, lambda obs: 10 ** 6, seed=0, episode_id=0,
                             max_steps=300)
    assert record.invalid_actions > 0
    assert record.steps > 0
    assert record.terminated or record.truncated
    for tr in record.transitions:
        assert tr.invalid is True
        # 兜底：招募阶段选 end_turn；choice 阶段没有 end_turn 则选最后一个候选
        assert tr.action_kind in ("end_turn", "choose")


def test_run_episode_without_transitions_is_lightweight() -> None:
    with _Context(seed=0) as env:
        record = run_episode(env, "heuristic", seed=0, episode_id=0,
                             max_steps=500, collect_transitions=False)
    assert record.transitions == []
    assert record.steps > 0
    assert 1 <= record.rank <= record.num_players


def test_run_episode_with_heuristic_policy_terminates() -> None:
    with _Context(seed=2) as env:
        record = run_episode(env, HeuristicPolicy(0), seed=2, episode_id=0,
                             max_steps=800)
    assert record.steps < 800  # 不会被 step_cap 截断
    assert record.terminated or record.reason in ("max_turns", "max_steps")


# ══════════════════════════════════════════════════════════════════════
# JSONL 记录
# ══════════════════════════════════════════════════════════════════════


def test_jsonl_record_schema() -> None:
    with _Context(seed=0) as env:
        record = run_episode(env, RandomPolicy(0), seed=0, episode_id=0,
                             max_steps=500)
    lines = list(record.to_jsonl_lines())
    assert lines[-1]["type"] == "episode"
    assert len([r for r in lines if r["type"] == "step"]) == record.steps
    for row in lines:
        validate_record(row)  # 不抛异常
        json.dumps(row)  # 可 JSON 序列化
    # 瘦身模式不含棋盘 id
    lean = list(record.to_jsonl_lines(per_step=True, include_board=False))
    assert all("board" not in row["obs"] for row in lean if row["type"] == "step")
    # 只保留每局一行
    compact = list(record.to_jsonl_lines(per_step=False))
    assert len(compact) == 1 and compact[0]["type"] == "episode"


def test_jsonl_info_is_compact_by_default() -> None:
    """真实环境 info 可能含巨大 obs_extra；JSONL 默认只写白名单字段。"""
    big = {"turn": 3, "rank": 2, "obs_extra": {"x": list(range(2000))},
           "terminated_reason": "eliminated", "custom_debug": "y" * 5000}
    tr = Transition(obs=Observation(turn=3), action=0, action_kind="end_turn",
                    info=big)
    row = tr.to_dict()
    assert row["info"]["turn"] == 3
    assert "obs_extra" not in row["info"]
    assert "custom_debug" not in row["info"]
    assert len(json.dumps(row)) < 4000
    full = tr.to_dict(info_keys=None)
    assert "obs_extra" in full["info"]
    none = tr.to_dict(info_keys=())
    assert not none.get("info")


def test_header_and_error_record() -> None:
    header = header_record(policy="random", seed=3, nested={"a": [1, 2]})
    validate_record(header)
    json.dumps(header)
    assert header["type"] == "header" and header["policy"] == "random"
    err = error_record(episode_id=1, seed=4, error="boom", worker=2)
    validate_record(err)
    with pytest.raises(ValueError):
        validate_record({"type": "unknown"})
    with pytest.raises(ValueError):
        validate_record({"type": "step", "v": 1})


# ══════════════════════════════════════════════════════════════════════
# policy 注册表 / 适配器
# ══════════════════════════════════════════════════════════════════════


def test_make_policy_builtins() -> None:
    for name in BUILTIN_NAMES:
        policy = make_policy(name, seed=1)
        assert isinstance(policy, Policy)
        assert describe_policy(policy) == name
    with pytest.raises(ValueError):
        make_policy("no-such-policy")
    assert isinstance(make_policy("RANDOM"), RandomPolicy)
    with pytest.raises(ValueError):
        make_policy("runs/does_not_exist.pt")


def test_make_policy_adapters() -> None:
    # callable 1 参数
    p1 = make_policy(pick_first)
    assert isinstance(p1, CallableAdapter)
    obs = Observation(turn=1)
    obs.candidates = (CandidateAction(kind="end_turn"),)
    assert p1.act(obs) == 0
    # callable 带 rng
    p2 = make_policy(pick_random_with_rng)
    assert p2.act(obs, rng=random.Random(0)) == 0
    # 只有 act 的对象
    p3 = as_policy(ActOnlyPolicy())
    assert isinstance(p3, PolicyAdapter)
    assert p3.act(obs) == 0
    # 已满足协议的对象原样返回
    base = RandomPolicy(0)
    assert as_policy(base) is base
    with pytest.raises(TypeError):
        as_policy(12345)


def test_heuristic_score_prefers_buy() -> None:
    obs = Observation(turn=3)
    obs.tavern = (EntityToken(card_id="BG19_010", zone="tavern", slot=0,
                              atk=5, health=5, tier=2, cost=3),)
    buy = CandidateAction(kind="buy", src_zone="tavern", src_slot=0, cost=3)
    freeze = CandidateAction(kind="freeze")
    assert heuristic_score(obs, buy) > heuristic_score(obs, freeze)


def test_picklable_helpers() -> None:
    assert is_picklable(pick_first) is True
    assert is_picklable("heuristic") is True
    assert is_picklable(lambda obs: 0) is False
    ensure_picklable(pick_first)
    with pytest.raises(ValueError):
        ensure_picklable(lambda obs: 0)


# ══════════════════════════════════════════════════════════════════════
# 引擎感知教师（teacher）
# ══════════════════════════════════════════════════════════════════════


def test_teacher_builtin_and_requires_engine() -> None:
    policy = make_policy("teacher")
    assert isinstance(policy, TeacherPolicy)
    assert isinstance(policy, Policy)
    assert policy.name == "teacher"
    assert policy.requires_engine is True
    assert describe_policy(policy) == "teacher"
    assert policy_requires_engine("teacher") is True
    assert policy_requires_engine("TEACHER") is True
    assert policy_requires_engine(policy) is True
    assert policy_requires_engine("heuristic") is False
    assert policy_requires_engine(RandomPolicy(0)) is False
    # 引擎教师参数透传 / 未知参数报错
    tuned = make_policy("teacher", max_rerolls=1, upgrade_turns=4)
    assert tuned._engine_kwargs["max_rerolls"] == 1
    with pytest.raises(TypeError):
        make_policy("teacher", no_such_option=1)


def test_teacher_requires_binding_and_real_env() -> None:
    policy = TeacherPolicy()
    obs = Observation(turn=1)
    obs.candidates = (CandidateAction(kind="end_turn"),)
    with pytest.raises(RuntimeError, match="bind_env"):
        policy.act(obs)
    # mock 环境没有 env.game/env.agent_hero → bind 时明确报错
    env = MockBattlegroundsEnv(seed=0)
    try:
        env.reset(seed=0)
        with pytest.raises(RuntimeError, match="真实环境"):
            policy.bind_env(env)
    finally:
        env.close()


def test_teacher_pickle_rebuild() -> None:
    policy = make_policy("teacher", max_rerolls=2)
    blob = pickle.dumps(policy)
    restored = pickle.loads(blob)
    assert isinstance(restored, TeacherPolicy)
    assert restored.name == "teacher"
    assert restored._engine_kwargs["max_rerolls"] == 2
    assert restored._env is None
    assert policy_requires_engine(restored) is True


def test_teacher_choice_phase_option_index() -> None:
    """choice 阶段用教师 choose_option_index，无需引擎动作枚举。"""
    options = tuple(
        EntityToken(card_id=f"FAKE_MINION_{i:03d}", card_type="minion",
                    zone="choice", slot=i, atk=i * 2, health=i * 2 + 1, tier=2)
        for i in range(3)
    )
    obs = Observation(turn=4, phase="choice",
                      pending_choice=PendingChoice(kind="discover",
                                                   options=options))
    obs.candidates = tuple(
        CandidateAction(kind="choose", option=i) for i in range(3)
    )
    policy = TeacherPolicy()
    # bind 一个只有 game/agent_hero 属性的哑环境（choice 分支不访问它们）
    dummy = type("DummyEnv", (), {"game": None, "agent_hero": None})()
    policy.bind_env(dummy)
    idx = policy.act(obs)
    assert 0 <= idx < 3
    assert policy.fallbacks == 0


def test_teacher_matches_engine_and_autobinds_on_real_env() -> None:
    if not real_env_available():
        pytest.skip("真实环境不可用")
    try:
        env = make_env(backend="real", seed=0)
    except Exception as exc:  # noqa: BLE001 - 环境层演进中
        pytest.skip(f"真实环境创建失败: {exc}")
    try:
        obs = env.reset(seed=0)
        policy = TeacherPolicy()
        policy.bind_env(env)
        policy.reset()
        from hsbg.agents.heuristic import HeuristicPolicy as EngineHeuristic

        engine = EngineHeuristic()
        matched = 0
        compared = 0
        for _ in range(12):
            if str(obs.phase) == "choice":
                idx = policy.act(obs)
                assert 0 <= idx < len(obs.candidates)
            else:
                idx = policy.act(obs)
                assert 0 <= idx < len(obs.candidates)
                desc = engine.choose(env.game, env.agent_hero)
                if desc is None:
                    target = CandidateAction(kind="end_turn")
                else:
                    target = desc.to_candidate()
                sig = target.signature()
                direct = next((i for i, c in enumerate(obs.candidates)
                               if c.signature() == sig), None)
                if direct is not None:
                    compared += 1
                    matched += int(direct == idx)
            obs, reward, terminated, truncated, info = env.step(
                obs.candidates[idx])
            if terminated or truncated:
                break
        assert compared >= 5
        assert matched >= compared - 1  # 允许 1 次边界差异
        assert policy.fallbacks <= 1
    finally:
        env.close()


def test_run_episode_binds_env_automatically_for_teacher() -> None:
    if not real_env_available():
        pytest.skip("真实环境不可用")
    try:
        env = make_env(backend="real", seed=0)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"真实环境创建失败: {exc}")
    try:
        record = run_episode(env, "teacher", seed=0, episode_id=0,
                             max_steps=1200)
        assert record.steps > 0
        assert 1 <= record.rank <= 8
        assert record.invalid_actions == 0
        assert record.policy == "teacher"
    finally:
        env.close()


def test_checkpoint_policy_inference(tmp_path) -> None:
    torch = pytest.importorskip("torch")
    from hsbg.policy.encoder import CardVocab, ObservationEncoder
    from hsbg.policy.model import PolicyConfig, build_policy

    encoder = ObservationEncoder(CardVocab.from_data_dir())
    torch.manual_seed(0)
    cfg = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    policy = build_policy(encoder, config=cfg)
    ckpt = tmp_path / "tiny_policy.pt"
    policy.save(ckpt, meta={"note": "rl-test"})

    wrapped = make_policy(str(ckpt), device="cpu")
    assert isinstance(wrapped, CheckpointPolicy)
    assert wrapped.name.startswith("checkpoint:")
    env = MockBattlegroundsEnv(seed=0)
    try:
        obs = env.reset(seed=0)
        idx1 = wrapped.act(obs, deterministic=True)
        idx2 = wrapped.act(obs, deterministic=True)
        assert idx1 == idx2
        assert 0 <= idx1 < len(obs.candidates)
        assert describe_policy(wrapped) == wrapped.name
    finally:
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 环境工厂
# ══════════════════════════════════════════════════════════════════════


def test_env_factory_mock() -> None:
    env = make_env(backend="mock", seed=4, num_players=8)
    try:
        assert isinstance(env, MockBattlegroundsEnv)
        obs = env.reset(seed=4)
        assert obs.turn == 1
        assert env.num_players == 8
        assert env.action_mask() == tuple(True for _ in env.legal_actions())
        assert env.current_observation is not None
    finally:
        env.close()
    with pytest.raises(ValueError):
        make_env(backend="nope")
    # real 后端不可用时必须明确报错而不是静默回退
    if not real_env_available():
        with pytest.raises(RuntimeError):
            make_env(backend="real")
    assert "mock" in env_backend_name(MockBattlegroundsEnv())


def test_mock_env_action_mask_and_types() -> None:
    env = MockBattlegroundsEnv(seed=0)
    try:
        obs = env.reset(seed=0)
        assert obs.phase == "recruit"
        assert isinstance(obs.candidates, tuple)
        assert all(isinstance(c, CandidateAction) for c in obs.candidates)
        kinds = {str(c.kind) for c in obs.candidates}
        assert "end_turn" in kinds
    finally:
        env.close()


def test_real_env_smoke_if_available() -> None:
    if not real_env_available():
        pytest.skip("真实环境不可用（仅 mock 后端）")
    try:
        env = make_env(backend="real", seed=0)
    except Exception as exc:  # noqa: BLE001 - 环境层仍在演进，失败跳过集成冒烟
        pytest.skip(f"真实环境创建失败: {exc}")
    try:
        record = run_episode(env, RandomPolicy(0), seed=0, episode_id=0,
                             max_steps=600)
        assert record.steps > 0
        assert 1 <= record.rank <= 8
    finally:
        env.close()
