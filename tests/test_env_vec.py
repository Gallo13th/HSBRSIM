"""``tests/test_env_vec.py`` —— 向量化环境（``hsbg/env/vec_env.py``）。

覆盖：
- ``SyncVecEnv``（单进程）reset/step/auto-reset/close；
- ``VecEnv`` 多进程（Windows spawn）冒烟；
- 同 seed 的向量化观测与单环境一致（确定性）。
"""

from __future__ import annotations

import pytest

from hsbg.env import BattlegroundsEnv
from hsbg.env.spec import PHASE_GAME_OVER, ActionKind
from hsbg.env.vec_env import SyncVecEnv, VecEnv


def _end_turn_index(obs) -> int:
    for i, c in enumerate(obs.candidates):
        if c.kind == ActionKind.END_TURN.value:
            return i
    return 0


def _run_to_done(vec, obs_list, max_steps=200):
    """反复对每个环境执行候选动作直到至少一个 done，返回 (obs, dones, infos)。"""
    dones = [False] * len(obs_list)
    infos = [{} for _ in obs_list]
    for _ in range(max_steps):
        actions = [_end_turn_index(obs) for obs in obs_list]
        obs_list, rewards, dones, infos = vec.step(actions)
        if any(dones):
            return obs_list, dones, infos
    raise AssertionError("vec env did not finish in max_steps")


def test_sync_vec_env_reset_step_close():
    vec = SyncVecEnv(2, env_kwargs={"num_players": 8, "opponent": "heuristic",
                                    "seed": 100}, seed=100)
    try:
        obs_list = vec.reset()
        assert len(obs_list) == 2
        assert all(o.turn >= 1 for o in obs_list)
        # 两个环境种子不同 → 英雄/候选可以不同，但都必须合法
        obs_list, rewards, dones, infos = vec.step(
            [_end_turn_index(o) for o in obs_list])
        assert len(rewards) == 2 and len(dones) == 2 and len(infos) == 2
        assert all(isinstance(r, float) for r in rewards)
        assert vec.dones == dones and vec.infos == infos
    finally:
        vec.close()


def test_sync_vec_env_auto_reset():
    vec = SyncVecEnv(2, env_kwargs={"num_players": 8, "max_turns": 1},
                     seed=200)
    try:
        obs_list = vec.reset()
        obs_list, dones, infos = _run_to_done(vec, obs_list, max_steps=100)
        assert any(dones)
        for i, done in enumerate(dones):
            if not done:
                continue
            assert infos[i].get("terminal") is True
            term_obs = infos[i].get("terminal_observation")
            assert term_obs is not None
            assert term_obs.phase == PHASE_GAME_OVER
            # auto-reset 后的 obs 已是新一局的首个观测
            assert obs_list[i].turn == 1
            assert obs_list[i].phase in ("recruit", "choice")
    finally:
        vec.close()


def test_sync_vec_env_determinism():
    kwargs = {"num_players": 8, "opponent": "heuristic", "seed": 300}
    v1 = SyncVecEnv(2, env_kwargs=kwargs, seed=300)
    v2 = SyncVecEnv(2, env_kwargs=kwargs, seed=300)
    try:
        a = v1.reset()
        b = v2.reset()
        for oa, ob in zip(a, b):
            assert oa.turn == ob.turn
            assert oa.candidates == ob.candidates
            assert oa.hero == ob.hero
            assert oa.lobby == ob.lobby
        # 与单环境同 seed 一致（第 0 个环境）
        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=300)
        single = env.reset(seed=300)
        assert single.candidates == a[0].candidates
        assert single.hero == a[0].hero
        env.close()
    finally:
        v1.close()
        v2.close()


def test_vec_env_multiprocess_smoke():
    """Windows spawn 冒烟：2 个 worker 进程 reset + step + close。"""
    vec = VecEnv(2, env_kwargs={"num_players": 8, "opponent": "heuristic"},
                 seed=400, multiprocess=True)
    try:
        obs_list = vec.reset()
        assert len(obs_list) == 2
        obs_list, rewards, dones, infos = vec.step(
            [_end_turn_index(o) for o in obs_list])
        assert len(obs_list) == 2
        assert all(isinstance(r, float) for r in rewards)
        assert all(isinstance(i, dict) for i in infos)
    finally:
        vec.close()
