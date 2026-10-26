"""TavernGym 后端（``hsbg.backends.taverngym_env``）回归测试。

覆盖范围（对应 ``docs/TAVERNGYM_BACKEND.md`` 的验收清单）：

1. ``EnvLike`` 协议 / ``Observation`` 契约；
2. 确定性（同 seed + 同动作序列 ⇒ 相同轨迹）；
3. 候选动作 == 245 维精确 mask（不丢/不多）；
4. mask 内每个动作都能被引擎接受（逐动作独立回放）；
5. 随机采样 50 个合法动作逐步执行不崩；
6. 非法动作（越界/非候选）不推进状态、不抛异常；
7. 终局 ``rank`` 与 ``placements()`` 对齐（淘汰路径 + 冠军路径）；
8. ``save_state()/load_state()`` 精确往返与续跑一致；
9. 两种观测源（features / view）交叉验证一致；
10. 与 ``hsbg.rl.api.run_episode`` / JSONL schema / 基准函数的兼容性；
11. 驱动逻辑与上游参照实现 ``taverngym.SoloEnv`` 逐步状态一致。

运行::

    python3 -m pytest tests/test_backend_taverngym.py -q
"""

from __future__ import annotations

import json
import random

import pytest

pytest.importorskip("taverngym")

from hsbg.backends import (  # noqa: E402
    BACKEND_NAME,
    TavernGymEnv,
    make_taverngym_env,
    taverngym_available,
)
from hsbg.env.spec import (  # noqa: E402
    CANDIDATE_MAX,
    PHASE_CHOICE,
    PHASE_GAME_OVER,
    PHASE_RECRUIT,
    ActionKind,
    CandidateAction,
    Observation,
)
from hsbg.rl.api import (  # noqa: E402
    EnvLike,
    obs_digest,
    obs_summary,
    run_episode,
    validate_record,
)
from hsbg.rl.policies import RandomPolicy  # noqa: E402

#: 测试用固定种子（TavernGym 完全由种子决定，可复现）
SEEDS = (0, 1, 7)


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def _env(seed: int = 0, **kwargs) -> TavernGymEnv:
    """创建并 reset 的环境。"""
    env = TavernGymEnv(seed=seed, **kwargs)
    env.reset(seed=seed)
    return env


def _new_candidate_indices(obs: Observation) -> list:
    return list(range(len(obs.candidates)))


def _placement_reward(rank: int, num_players: int) -> float:
    """与 ``hsbg.env.spec.RewardConfig`` 的 placement 口径一致。"""
    return 1.0 - 2.0 * (rank - 1) / (num_players - 1)


def _sample_trajectory(seed: int, steps: int, **env_kwargs):
    """确定性随机策略采样一条轨迹（返回逐步 (obs, reward, term, trunc, info)）。"""
    env = _env(seed, **env_kwargs)
    rng = random.Random(seed)
    obs = env.current_observation
    trace = []
    for _ in range(steps):
        if not obs.candidates or obs.phase == PHASE_GAME_OVER:
            break
        idx = rng.randrange(len(obs.candidates))
        obs, reward, term, trunc, info = env.step(idx)
        trace.append((obs, reward, term, trunc, info))
        if term or trunc:
            break
    env.close()
    return trace


def _bot_driven_game(seed: int, num_players: int = 8, max_steps: int = 1200):
    """用 TavernGym 自带 bot 当智能体，跑一整局（验证冠军/游戏结束路径）。

    返回 ``(env, steps, info, terminated)``；``info`` 是最后一步的 info。
    """
    env = TavernGymEnv(seed=seed, num_players=num_players)
    obs = env.reset(seed=seed)
    steps = 0
    info = {}
    while obs.candidates and not env._done and steps < max_steps:  # noqa: SLF001
        flat = int(env.game.bot_action(env.agent_index))
        idx = env.candidate_index_for_flat(flat)
        assert idx >= 0, f"bot 动作 {flat} 不在候选里（mask/候选不一致）"
        obs, _reward, term, trunc, info = env.step(idx)
        steps += 1
        if term or trunc:
            return env, steps, info, bool(term)
    return env, steps, info, bool(env._done)  # noqa: SLF001


# ══════════════════════════════════════════════════════════════════════
# 1. 协议 / 契约
# ══════════════════════════════════════════════════════════════════════


class TestProtocol:
    def test_import_and_factory(self):
        assert taverngym_available() is True
        env = make_taverngym_env(seed=0)
        try:
            assert isinstance(env, TavernGymEnv)
            assert env.backend == BACKEND_NAME == "taverngym"
            assert env.num_players == 8
            assert env.agent_index == 0
        finally:
            env.close()

    def test_envlike_protocol(self):
        env = _env(0)
        try:
            assert isinstance(env, EnvLike)
            assert hasattr(env, "reset") and hasattr(env, "step")
            assert hasattr(env, "close")
        finally:
            env.close()

    def test_reset_observation_contract(self):
        env = _env(0)
        try:
            obs = env.reset(seed=0)
            assert isinstance(obs, Observation)
            assert obs.version == Observation().version  # 沿用 spec 当前值
            assert obs.turn >= 1                      # spec 约定 1 起
            assert obs.phase in (PHASE_RECRUIT, PHASE_CHOICE, PHASE_GAME_OVER)
            assert obs.total_players == 8
            assert obs.hero is not None
            assert len(obs.lobby) == 8
            assert obs.hero.hero_id == ""            # 英雄选择阶段尚未选英雄
            assert len(obs.candidates) > 0
            assert obs.phase == PHASE_CHOICE          # 首步是英雄选择
            assert all(c.kind == ActionKind.CHOOSE.value for c in obs.candidates)
        finally:
            env.close()

    def test_compat_surface(self):
        env = _env(0)
        try:
            out = env.reset(seed=0)
            assert tuple(env.legal_actions()) == tuple(out.candidates)
            assert env.action_mask() == tuple(True for _ in out.candidates)
            assert env.num_actions() == len(out.candidates)
            assert env.current_observation is out
            assert env.observation_space["backend"] == BACKEND_NAME
            assert env.action_space is None
            assert isinstance(env.episode_steps, int)
            assert env.seed == 0
        finally:
            env.close()

    def test_constructor_validation(self):
        with pytest.raises(ValueError):
            TavernGymEnv(num_players=1)
        with pytest.raises(ValueError):
            TavernGymEnv(num_players=8, agent_index=8)
        with pytest.raises(ValueError):
            TavernGymEnv(obs_source="nope")
        with pytest.raises(ValueError):
            TavernGymEnv(max_steps=0)

    def test_missing_dependency_raises_install_hint(self, monkeypatch):
        """taverngym 未安装时：导入不炸，构造环境抛带安装步骤的 ImportError。"""
        from hsbg.backends import taverngym_env as module  # noqa: PLC0415

        monkeypatch.setattr(module, "_tg", None)
        with pytest.raises(ImportError, match="pip install"):
            module.TavernGymEnv()
        assert module.taverngym_available() is False

    def test_make_env_taverngym_backend(self):
        """``hsbg.rl.envs.make_env(backend="taverngym")`` 返回本后端（惰性导入）。"""
        from hsbg.rl.envs import (  # noqa: PLC0415
            BACKENDS,
            env_backend_name,
            make_env,
        )

        assert "taverngym" in BACKENDS and "hsrl2" in BACKENDS
        env = make_env(backend="taverngym", seed=1)
        try:
            assert isinstance(env, TavernGymEnv)
            assert env_backend_name(env).startswith("taverngym(")
            obs = env.reset(seed=1)
            assert obs.phase == PHASE_CHOICE
            assert len(obs.candidates) > 0
        finally:
            env.close()
        # env_kwargs 透传（观测源/人数）
        env = make_env(backend="taverngym", seed=1,
                       env_kwargs={"obs_source": "view", "num_players": 2})
        try:
            assert env.obs_source == "view" and env.num_players == 2
        finally:
            env.close()

    def test_make_env_default_and_hsrl2_alias_are_real_backend(self):
        """不传参（默认 hsrl2）与 ``backend="hsrl2"`` 都返回 hsrl2 真实环境。"""
        from hsbg.rl.envs import make_env, real_env_available  # noqa: PLC0415

        if not real_env_available():
            pytest.skip("真实环境不可用")
        from hsbg.env.game_env import BattlegroundsEnv  # noqa: PLC0415

        env = make_env(seed=2)
        try:
            assert isinstance(env, BattlegroundsEnv)
        finally:
            env.close()
        env = make_env(backend="hsrl2", seed=2)
        try:
            assert isinstance(env, BattlegroundsEnv)
        finally:
            env.close()

    @pytest.mark.parametrize("module_name", ["hsbg.rl.collector",
                                             "hsbg.rl.evaluate"])
    def test_teacher_rejected_on_taverngym(self, module_name: str):
        """teacher 依赖 hsrl2 引擎对象：taverngym 后端必须提前明确报错。"""
        import importlib  # noqa: PLC0415

        module = importlib.import_module(module_name)
        with pytest.raises(ValueError, match="teacher"):
            module._check_policy_backend("teacher", "taverngym")  # noqa: SLF001


# ══════════════════════════════════════════════════════════════════════
# 2. 确定性
# ══════════════════════════════════════════════════════════════════════


class TestDeterminism:
    def test_reset_is_deterministic(self):
        e1 = _env(42)
        o1 = e1.current_observation
        e2 = _env(42)
        o2 = e2.current_observation
        try:
            assert o1 == o2
            assert obs_digest(o1) == obs_digest(o2)
        finally:
            e1.close()
            e2.close()

    def test_trajectory_is_deterministic(self):
        trace1 = _sample_trajectory(42, steps=25)
        trace2 = _sample_trajectory(42, steps=25)
        assert len(trace1) == len(trace2) > 0
        for (o1, r1, t1, tr1, i1), (o2, r2, t2, tr2, i2) in zip(trace1, trace2):
            assert o1 == o2
            assert r1 == pytest.approx(r2)
            assert (t1, tr1) == (t2, tr2)
            assert i1["flat_action"] == i2["flat_action"]
            assert i1["rank"] == i2["rank"]

    def test_different_seed_differs(self):
        trace1 = _sample_trajectory(0, steps=10)
        trace2 = _sample_trajectory(1, steps=10)
        assert [obs_digest(t[0]) for t in trace1] != [obs_digest(t[0]) for t in trace2]


# ══════════════════════════════════════════════════════════════════════
# 3. 候选动作 == 精确 mask
# ══════════════════════════════════════════════════════════════════════


class TestActionMask:
    def test_candidates_equal_engine_mask(self):
        env = _env(3)
        try:
            for _ in range(6):
                obs = env.current_observation
                mask = env.fixed_action_mask()
                assert len(mask) == 245
                assert len(env.legal_action_indices()) == len(obs.candidates)
                assert list(env.legal_action_indices()) == sorted(
                    env.legal_action_indices())
                expected = [i for i, v in enumerate(mask) if v]
                assert list(env.legal_action_indices()) == expected
                assert len(obs.candidates) == len(expected)
                if not obs.candidates:
                    break
                env.step(0)
        finally:
            env.close()

    def test_candidate_flat_index_roundtrip(self):
        env = _env(5)
        try:
            obs = env.current_observation
            for i, cand in enumerate(obs.candidates):
                flat = env.legal_action_indices()[i]
                assert env.flat_index(cand) == flat
                assert env.flat_index(i) == flat
            assert env.flat_index(10 ** 6) == -1
        finally:
            env.close()

    def test_candidate_kinds_are_spec_or_documented(self):
        allowed = {k.value for k in ActionKind} | {"cancel"}  # cancel 为后端扩展
        env = _env(0)
        try:
            seen = set()
            for _ in range(80):
                obs = env.current_observation
                if not obs.candidates or obs.phase == PHASE_GAME_OVER:
                    break
                for cand in obs.candidates:
                    seen.add(cand.kind)
                    assert cand.kind in allowed
                env.step(random.Random(len(seen)).randrange(len(obs.candidates)))
            assert ActionKind.CHOOSE.value in seen     # 英雄选择
            assert ActionKind.END_TURN.value in seen   # 招募期
        finally:
            env.close()

    def test_candidate_count_may_exceed_spec_max_and_is_flagged(self):
        """TavernGym 245 维空间 → 候选可能 > CANDIDATE_MAX；extra 必须标注。"""
        env = _env(3)
        try:
            max_seen = 0
            for _ in range(60):
                obs = env.current_observation
                if not obs.candidates or obs.phase == PHASE_GAME_OVER:
                    break
                meta = obs.extra["taverngym"]
                max_seen = max(max_seen, len(obs.candidates))
                assert meta["n_candidates"] == len(obs.candidates)
                assert meta["n_actions"] == 245
                assert meta["candidate_max"] == CANDIDATE_MAX
                assert meta["candidates_over_spec_max"] == (
                    len(obs.candidates) > CANDIDATE_MAX)
                assert len(meta["flat_action_indices"]) == len(obs.candidates)
                env.step(0)
            assert max_seen >= 1
        finally:
            env.close()


# ══════════════════════════════════════════════════════════════════════
# 4. mask 内动作全部可执行
# ══════════════════════════════════════════════════════════════════════


class TestLegalActionsExecutable:
    @pytest.mark.parametrize("warm_steps", [0, 4])
    def test_every_masked_action_is_accepted(self, warm_steps: int):
        """在决策点存档，对**每个**候选动作独立恢复并执行——引擎都必须接受。"""
        env = _env(3)
        try:
            for _ in range(warm_steps):
                if not env.current_observation.candidates:
                    break
                env.step(0)
            state = env.save_state()
            flats = list(env.legal_action_indices())
            assert flats, "决策点至少应有 1 个候选"
            for idx, flat in enumerate(flats):
                clone = TavernGymEnv(seed=0)
                clone.load_state(state)
                try:
                    _obs, reward, term, trunc, info = clone.step(idx)
                    assert info["invalid"] is False, (
                        f"候选 #{idx}(flat={flat}) 被引擎拒绝：{info}")
                    assert info["flat_action"] == flat
                    assert clone.episode_steps == env.episode_steps + 1
                    assert not trunc
                    if term:
                        assert clone.current_observation.phase == PHASE_GAME_OVER
                finally:
                    clone.close()
        finally:
            env.close()

    def test_random_50_legal_actions(self):
        """随机采样 50 个 legal 动作逐步执行，全部被接受、不崩。"""
        env = _env(11)
        try:
            rng = random.Random(11)
            accepted = 0
            terminated = False
            for _ in range(50):
                obs = env.current_observation
                if not obs.candidates or obs.phase == PHASE_GAME_OVER:
                    terminated = True
                    break
                idx = rng.randrange(len(obs.candidates))
                flat = env.legal_action_indices()[idx]
                obs2, _reward, term, trunc, info = env.step(idx)
                assert info["invalid"] is False
                assert info["flat_action"] == flat
                assert obs2.phase in (PHASE_RECRUIT, PHASE_CHOICE, PHASE_GAME_OVER)
                assert env.episode_steps > 0
                accepted += 1
                if term or trunc:
                    terminated = True
                    break
            assert accepted > 0
            assert accepted == 50 or terminated  # 50 步内终局也算通过
        finally:
            env.close()


# ══════════════════════════════════════════════════════════════════════
# 5. 非法动作
# ══════════════════════════════════════════════════════════════════════


class TestInvalidActions:
    def test_out_of_range_int(self):
        env = _env(3)
        try:
            obs = env.current_observation
            before = (obs_digest(obs), env.episode_steps)
            out, reward, term, trunc, info = env.step(10 ** 6)
            assert info["invalid"] is True
            assert info["wrong_action"] is True
            assert reward == pytest.approx(-0.05)   # RewardConfig.invalid_action
            assert term is False and trunc is False
            assert (obs_digest(out), env.episode_steps) == before
        finally:
            env.close()

    def test_non_candidate_action(self):
        env = _env(3)
        try:
            bad = CandidateAction(kind=ActionKind.END_TURN.value,
                                  src_zone="tavern", src_slot=7)
            before = obs_digest(env.current_observation)
            _obs, reward, _term, _trunc, info = env.step(bad)
            assert info["invalid"] is True
            assert reward == pytest.approx(-0.05)
            assert obs_digest(env.current_observation) == before
        finally:
            env.close()

    def test_bool_and_none_and_negative(self):
        env = _env(3)
        try:
            for bad in (True, None, -1, 1.5):
                _obs, reward, _term, _trunc, info = env.step(bad)
                assert info["invalid"] is True
                assert reward == pytest.approx(-0.05)
        finally:
            env.close()

    def test_masked_out_flat_action_not_steppable(self):
        """把 mask 外的扁平动作包成 CandidateAction（kind 对但槽位错）→ invalid。"""
        env = _env(3)
        try:
            mask = env.fixed_action_mask()
            # 找第一个 mask=False 的 BUY 槽位
            from hsbg.backends.taverngym_env import _tg_layout  # noqa: PLC0415

            lay = _tg_layout()
            bad_flat = None
            for slot in range(lay.n_shop):
                flat = lay.a_buy + slot
                if not mask[flat]:
                    bad_flat = flat
                    break
            if bad_flat is None:
                pytest.skip("当前状态所有 BUY 槽位都合法")
            cand = CandidateAction(kind=ActionKind.BUY.value,
                                   src_zone="tavern",
                                   src_slot=bad_flat - lay.a_buy)
            _obs, reward, _term, _trunc, info = env.step(cand)
            assert info["invalid"] is True
            assert float(reward) == pytest.approx(-0.05)
        finally:
            env.close()


# ══════════════════════════════════════════════════════════════════════
# 6. 终局 rank 与 placements 对齐
# ══════════════════════════════════════════════════════════════════════


class TestTerminalRank:
    @pytest.mark.parametrize("seed", SEEDS)
    def test_eliminated_rank_matches_placements(self, seed: int):
        env = TavernGymEnv(seed=seed)
        obs = env.reset(seed=seed)
        rng = random.Random(seed)
        last = None
        for _ in range(500):
            if not obs.candidates:
                break
            last = env.step(rng.randrange(len(obs.candidates)))
            obs, _reward, term, trunc, info = last
            if term or trunc:
                break
        assert last is not None
        obs, reward, term, trunc, info = last
        placements = list(env.game.placements())
        try:
            assert term is True
            assert trunc is False
            assert info["rank"] == placements[env.agent_index] > 0
            assert 1 <= info["rank"] <= env.num_players
            assert obs.phase == PHASE_GAME_OVER
            assert obs.candidates == ()
            # 终局奖励 = placement 项（本适配器不发 health/combat shaping）
            expected = _placement_reward(info["rank"], env.num_players)
            assert reward == pytest.approx(expected)
            # 已淘汰玩家的 placement 是最终名次；存活玩家为 0
            assert placements[env.agent_index] == info["rank"]
        finally:
            env.close()

    def test_champion_path_full_game(self):
        """用引擎 bot 替智能体打完 8 人局：名次/奖励/完整名次排列都正确。"""
        env, steps, info, terminated = _bot_driven_game(seed=3)
        try:
            assert terminated is True
            assert env.game.is_over() is True
            placements = list(env.game.placements())
            assert sorted(placements) == list(range(1, env.num_players + 1))
            assert info["rank"] == placements[env.agent_index] == 1
            assert info["terminated_reason"] == "game_over"
            assert env.current_observation.phase == PHASE_GAME_OVER
            # 冠军奖励 = +1
            obs = env.current_observation
            assert obs.rank == 1
            assert steps > 0
        finally:
            env.close()

    def test_two_player_game_over(self):
        """2 人局：任何一方死亡即 game over，名次排列必为 [1,2]。"""
        for seed in (0, 1):
            env, _steps, info, terminated = _bot_driven_game(
                seed=seed, num_players=2)
            try:
                assert terminated is True
                placements = list(env.game.placements())
                assert sorted(placements) == [1, 2]
                assert info["rank"] == placements[env.agent_index]
                assert info["rank"] in (1, 2)
                assert info["terminated_reason"] == "game_over"
            finally:
                env.close()


# ══════════════════════════════════════════════════════════════════════
# 7. save/load
# ══════════════════════════════════════════════════════════════════════


class TestSaveLoad:
    def _warm_env(self, seed: int = 5, steps: int = 6) -> TavernGymEnv:
        env = _env(seed)
        rng = random.Random(1)
        for _ in range(steps):
            obs = env.current_observation
            if not obs.candidates:
                break
            env.step(rng.randrange(len(obs.candidates)))
        return env

    def test_roundtrip_byte_and_observation_identical(self):
        env = self._warm_env()
        try:
            state = env.save_state()
            assert isinstance(state, str) and state
            clone = TavernGymEnv(seed=0)
            try:
                clone.load_state(state)
                assert clone.current_observation == env.current_observation
                assert clone.episode_steps == env.episode_steps
                assert clone.seed == env.seed
                # save → load → save 字节级一致（精确存档）
                assert clone.save_state() == state
                # 底层引擎状态也逐字节一致
                assert clone.game.state_json() == env.game.state_json()
            finally:
                clone.close()
        finally:
            env.close()

    def test_continuation_matches(self):
        env = self._warm_env()
        try:
            state = env.save_state()
            clone = TavernGymEnv(seed=0)
            clone.load_state(state)
            rng_a = random.Random(77)
            rng_b = random.Random(77)
            for _ in range(15):
                obs_a = env.current_observation
                obs_b = clone.current_observation
                if not obs_a.candidates:
                    break
                ia = rng_a.randrange(len(obs_a.candidates))
                ib = rng_b.randrange(len(obs_b.candidates))
                assert ia == ib
                out_a = env.step(ia)
                out_b = clone.step(ib)
                assert out_a[0] == out_b[0]
                assert out_a[1] == pytest.approx(out_b[1])
                assert (out_a[2], out_a[3]) == (out_b[2], out_b[3])
                for key in ("flat_action", "invalid", "rank", "turn",
                            "episode_steps", "backend"):
                    assert out_a[4][key] == out_b[4][key], key
                if out_a[2] or out_a[3]:
                    break
        finally:
            env.close()

    def test_load_state_rejects_bad_format(self):
        env = _env(5)
        try:
            with pytest.raises(ValueError):
                env.load_state('{"format": "other"}')
            with pytest.raises(TypeError):
                env.load_state(12345)
            # 正常存档可被 dict 形式接受
            payload = json.loads(env.save_state())
            clone = TavernGymEnv(seed=0)
            try:
                clone.load_state(payload)
                assert clone.current_observation == env.current_observation
            finally:
                clone.close()
        finally:
            env.close()

    def test_save_before_reset_raises(self):
        env = TavernGymEnv(seed=0)
        with pytest.raises(RuntimeError):
            env.save_state()
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 8. 两种观测源交叉验证
# ══════════════════════════════════════════════════════════════════════


class TestObservationSources:
    def test_features_and_view_agree(self):
        """同一状态两种观测源应给出相同实体/标量（英雄选择期的对手信息除外）。"""
        envf = TavernGymEnv(seed=7, obs_source="features")
        envv = TavernGymEnv(seed=7, obs_source="view")
        of = envf.reset(seed=7)
        ov = envv.reset(seed=7)
        rng = random.Random(7)
        try:
            for step in range(25):
                self._assert_same(of, ov, envf, envv,
                                  check_lobby=(of.phase != PHASE_CHOICE
                                               or of.turn > 1))
                if not of.candidates or of.phase == PHASE_GAME_OVER:
                    break
                idx = rng.randrange(len(of.candidates))
                of = envf.step(idx)[0]
                ov = envv.step(idx)[0]
        finally:
            envf.close()
            envv.close()

    @staticmethod
    def _tokens_equal(a, b) -> bool:
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if (x.card_id, x.card_type, x.atk, x.health, x.tier, x.cost,
                    x.golden) != (y.card_id, y.card_type, y.atk, y.health,
                                  y.tier, y.cost, y.golden):
                return False
            if set(x.keywords) != set(y.keywords):
                return False
            if set(x.races) != set(y.races):
                return False
        return True

    def _assert_same(self, of: Observation, ov: Observation, envf, envv,
                     *, check_lobby: bool) -> None:
        assert (of.turn, of.phase, of.alive_count, of.rank) == (
            ov.turn, ov.phase, ov.alive_count, ov.rank)
        assert of.hero is not None and ov.hero is not None
        for field in ("hero_id", "health", "armor", "tier", "gold",
                      "upgrade_cost", "power_id", "power_usable"):
            assert getattr(of.hero, field) == getattr(ov.hero, field), field
        assert self._tokens_equal(of.board, ov.board)
        assert self._tokens_equal(of.hand, ov.hand)
        assert self._tokens_equal(of.tavern, ov.tavern)
        assert self._tokens_equal(of.opponent_board, ov.opponent_board)
        assert [c.kind for c in of.candidates] == [c.kind for c in ov.candidates]
        assert (envf.legal_action_indices()
                == envv.legal_action_indices())
        if check_lobby:
            assert len(of.lobby) == len(ov.lobby)
            for a, b in zip(of.lobby, ov.lobby):
                assert (a.health, a.armor, a.tier, a.alive, a.eliminated_rank,
                        a.is_agent) == (b.health, b.armor, b.tier, b.alive,
                                        b.eliminated_rank, b.is_agent)


# ══════════════════════════════════════════════════════════════════════
# 9. RL 接口层 / JSONL 兼容
# ══════════════════════════════════════════════════════════════════════


class TestRlInterface:
    def test_run_episode_with_random_policy(self):
        env = TavernGymEnv(seed=0)
        try:
            rec = run_episode(
                env, RandomPolicy(seed=0), seed=0, max_steps=1000)
            assert rec.steps > 0
            assert rec.rank == env.game.placements()[env.agent_index]
            assert 1 <= rec.rank <= 8
            assert rec.terminated or rec.truncated
            assert rec.invalid_actions == 0
            assert rec.error == ""
            # JSONL schema 兼容
            rows = list(rec.to_jsonl_lines())
            assert rows[-1]["type"] == "episode"
            for row in rows:
                validate_record(row)
            assert all(tr.info.get("backend") == BACKEND_NAME
                       for tr in rec.transitions)
        finally:
            env.close()

    def test_obs_summary_and_digest(self):
        env = _env(0)
        try:
            summary = obs_summary(env.current_observation, include_extra=True)
            assert summary["pending_choice"] == "hero"
            assert summary["n_candidates"] == 2
            assert summary["total"] == 8
            digest = obs_digest(env.current_observation)
            assert len(digest) == 16
        finally:
            env.close()

    def test_info_contract(self):
        env = _env(0)
        try:
            info = {}
            for _ in range(5):
                _obs, _reward, _term, _trunc, info = env.step(0)
            for key in ("turn", "rank", "health", "armor", "alive_count",
                        "combat", "wrong_action", "invalid",
                        "terminated_reason", "seed", "episode",
                        "episode_steps", "phase", "backend", "flat_action",
                        "action_mask", "n_candidates", "obs_source"):
                assert key in info, key
            assert info["backend"] == BACKEND_NAME
            assert len(info["action_mask"]) == 245
            assert info["invalid"] is False
            assert info["obs_source"] == "features"
            assert info["taverngym_game_version"].startswith("36.6")
        finally:
            env.close()

    def test_step_after_done_is_not_invalid(self):
        env, _steps, _info, _term = _bot_driven_game(seed=3, num_players=2)
        try:
            obs_before = env.current_observation
            obs, reward, term, trunc, info = env.step(0)
            assert term is True
            assert info["invalid"] is False
            assert info["episode_done"] is True
            assert reward == 0.0
            assert obs is obs_before
            # 玩家不能再被 step 推进
            assert env.episode_steps == _steps
        finally:
            env.close()

    def test_collector_cli_taverngym_jsonl(self, tmp_path):
        """collector CLI 用 taverngym 后端采 1 局，落盘 JSONL 且 schema 合法。"""
        from hsbg.rl.collector import main as collector_main  # noqa: PLC0415

        out = tmp_path / "tg_collect.jsonl"
        code = collector_main([
            "--policy", "random", "--envs", "1", "--episodes", "1",
            "--seed", "0", "--backend", "taverngym", "--out", str(out),
        ])
        assert code == 0
        assert out.exists()
        rows = [json.loads(line) for line in out.read_text(
            encoding="utf-8").splitlines() if line.strip()]
        header = rows[0]
        assert header["type"] == "header"
        assert header["backend"] == "taverngym"
        assert header["episodes"] == 1
        steps = [r for r in rows if r["type"] == "step"]
        episodes = [r for r in rows if r["type"] == "episode"]
        assert steps and len(episodes) == 1
        for row in steps + episodes:
            validate_record(row)
        rank = int(episodes[0]["rank"])
        assert 1 <= rank <= 8
        assert all(s["invalid"] is False for s in steps)

    def test_benchmark_smoke(self):
        from hsbg.backends.benchmark import (  # noqa: PLC0415
            bench_taverngym,
            bench_taverngym_engine,
            bench_taverngym_micro,
        )

        result = bench_taverngym(games=2, seed=0, obs_source="features")
        assert result["episodes"] == 2
        assert result["games_per_second"] > 0
        assert result["steps_total"] > 0
        engine = bench_taverngym_engine(games=10, seed=0)
        assert engine["games_per_second"] > 0
        micro = bench_taverngym_micro(steps=15, seed=1)
        assert micro["steps"] > 0
        assert micro["legal_mask_us"]["mean_us"] >= 0


# ══════════════════════════════════════════════════════════════════════
# 10. 与上游参照实现（SoloEnv）的驱动一致性
# ══════════════════════════════════════════════════════════════════════


class TestDriverReference:
    @pytest.mark.parametrize("seed", (0, 1))
    def test_matches_upstream_solo_env(self, seed: int):
        """同一 seed + 同一动作序列：适配器内部 Game 与 taverngym.SoloEnv 状态一致。"""
        import taverngym  # noqa: PLC0415

        env = _env(seed)
        try:
            solo = taverngym.SoloEnv(
                seed, json.dumps(env._config_overrides))  # noqa: SLF001
            assert env.game.state_json() == solo.state_json()
            rng = random.Random(seed)
            for step in range(20):
                obs = env.current_observation
                if not obs.candidates:
                    break
                idx = rng.randrange(len(obs.candidates))
                flat = env.legal_action_indices()[idx]
                env.step(idx)
                _reward, _done, illegal = solo.step(int(flat))
                assert illegal is None, f"step {step}: SoloEnv 拒绝 {flat}: {illegal}"
                assert env.game.state_json() == solo.state_json(), (
                    f"step {step}: 适配器与 SoloEnv 引擎状态不一致")
                if env.game.is_over() or int(env.game.placements()[0]) != 0:
                    assert solo.done() or env.game.is_over()
                    break
        finally:
            env.close()
