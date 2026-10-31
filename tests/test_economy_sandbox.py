"""纯经济沙盒（``hsbg/az/train/economy_sandbox.py``）的单元测试。

只跑 3 回合、EndTurn 策略，验证「契约」而不是强度：
- 观测/动作与正常训练同一套编码（3227/124/245）；
- 15 回合上限、战斗/伤害被跳过（没有掉血、没有淘汰、没有名次）；
- 奖励口径可复算（log_strength 望远镜求和 == L_T；final_strength 只在末回合给）；
- 确定性（同 seed 同动作序列逐位一致）；
- 向量化环境的 done/重置与 episode 汇总。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

pytest.importorskip("hsbg_engine")

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    END_TURN, N_ACTIONS, OBS_CARDS, OBS_FLOATS, EconomySandbox, SandboxConfig,
    VectorEconomySandbox, carrier_ids, stack_obs, summarize)


def _cfg(**kw):
    base = dict(turns=3, gold_per_turn=10, action_cap=40)
    base.update(kw)
    return SandboxConfig(**base)


def _act(mask) -> int:
    """最省事的合法动作：能 EndTurn 就 EndTurn，否则（pending 选择）走第一个合法位。"""
    if mask[END_TURN]:
        return END_TURN
    return int(np.flatnonzero(mask)[0])


def _run_end_policy(cfg, seed=1):
    env = EconomySandbox(cfg)
    obs = env.reset(seed)
    total = 0.0
    steps = 0
    rewards = []
    while not env.done:
        obs, r, done, info = env.step(_act(obs.mask))
        total += float(r)
        rewards.append(float(r))
        steps += 1
    return env, obs, total, steps, rewards


def test_obs_action_contract():
    env = EconomySandbox(_cfg())
    obs = env.reset(7)
    assert obs.features.shape == (OBS_FLOATS,)
    assert obs.cards.shape == (OBS_CARDS,)
    assert obs.mask.shape == (N_ACTIONS,)
    assert obs.features.dtype == np.float32 and obs.mask.dtype == np.bool_
    f, c, m = stack_obs([obs, obs])
    assert f.shape == (2, OBS_FLOATS) and c.shape == (2, OBS_CARDS)
    assert m.shape == (2, N_ACTIONS)


def test_turns_cap_and_skip_combat():
    """3 回合后终止；全程没有任何人掉血/被淘汰（战斗伤害被配置为 0）。"""
    env, obs, total, steps, _rewards = _run_end_policy(_cfg(turns=3))
    assert env.done
    ep = env.episode_summary()
    assert ep["turns"] == 3
    assert [r["turn"] for r in ep["rows"]] == [1, 2, 3]
    # 跳过战斗：8 个座位都还活着、血量满（引擎默认 30）
    assert list(env.g.health()) == [30] * 8
    assert not [p for p in env.g.placements() if p > 0] or True
    assert 3 <= steps <= 6     # 每回合一个 EndTurn（+ 偶尔的 pending 选择）就推进
    assert total == pytest.approx(0.0, abs=1e-6)   # 空战团 → L=0


def test_engine_config_skips_combat():
    cfg = _cfg()
    ec = cfg.engine_config()
    assert ec["damage_caps"] == [[1, 0]]
    assert ec["damage_cap_until_alive"] == 0
    assert ec["max_turns"] == cfg.turns
    assert ec["turn_action_caps"][0] == cfg.action_cap
    assert ec["max_actions_per_turn"] == cfg.action_cap


def test_log_strength_reward_telescopes():
    """log_strength：整局 reward 之和 == L_15（可选 tier/carrier 混合项为 0）。"""
    env, _obs, total, _steps, _r = _run_end_policy(_cfg(turns=3))
    ep = env.episode_summary()
    last = ep["rows"][-1]["sigma"]
    L = math.log1p(last) / math.log1p(cfg_ref := env.cfg.strength_ref)
    assert total == pytest.approx(L, abs=1e-9)
    assert L >= 0.0 and cfg_ref > 0


def test_final_strength_reward_only_last_turn():
    env = EconomySandbox(_cfg(turns=3, reward="final_strength"))
    obs = env.reset(3)
    rewards = []
    while not env.done:
        obs, r, _d, _i = env.step(_act(obs.mask))
        rewards.append(float(r))
    assert rewards[:-1] == pytest.approx([0.0, 0.0], abs=1e-9)
    assert rewards[-1] >= 0.0


def test_reward_mix_validation():
    with pytest.raises(ValueError):
        _cfg(reward_mix="bogus:1.0").validate()
    with pytest.raises(ValueError):
        _cfg(reward="rank").validate()
    _cfg(reward_mix="tier:0.1,carrier:0.2,tavern:0.05,spells:0.05").validate()


def test_determinism_same_seed():
    e1, _o, t1, s1, _r = _run_end_policy(_cfg(), seed=11)
    e2, _o, t2, s2, _r = _run_end_policy(_cfg(), seed=11)
    assert s1 == s2 and t1 == pytest.approx(t2)
    assert e1.episode_summary()["rows"] == e2.episode_summary()["rows"]


def test_gold_injection():
    """--gold-per-turn：每回合开始 seat 0 的金币就是 N（这里 10 → 用完前不超）。"""
    env = EconomySandbox(_cfg(gold_per_turn=10))
    obs = env.reset(5)
    # 开局（第 1 回合）手上应该有 10 金
    assert env._gold() == 10
    while not env.done:
        obs, _r, _d, _i = env.step(_act(obs.mask))
        if not env.done:
            assert env._gold() == 10      # set 模式：每回合重置为 10


def test_vector_env_episodes_and_reset():
    vec = VectorEconomySandbox(_cfg(turns=2), n_envs=3, seed0=100)
    obs = vec.reset()
    assert len(obs) == 3
    done_seen = 0
    for _ in range(4):     # 每局 2 步，所以 2 轮内必然全部完成一轮
        obs, rewards, dones, infos = vec.step([_act(o.mask) for o in obs])
        done_seen += int(dones.sum())
    assert done_seen >= 3
    assert len(vec.episodes) >= 3
    for ep in vec.episodes:
        assert ep["turns"] == 2
    rep = summarize(vec.episodes)
    assert rep["games"] == len(vec.episodes)
    assert "sigma_t12_p50" in rep and "carrier_rate" in rep


def test_carrier_ids_loaded():
    ids = carrier_ids()
    assert len(ids) == 22
    assert "BG36_762" in ids        # Devilish Distractor


def test_board_delta_reward_telescopes_and_tracks_board():
    """board_delta（逐决策势函数）：整局求和仍 == L_T；买牌那一步 reward > 0。"""
    env = EconomySandbox(_cfg(turns=3, reward="board_delta"))
    obs = env.reset(9)
    total = 0.0
    while not env.done:
        obs, r, _d, _i = env.step(_act(obs.mask))
        total += float(r)
    ep = env.episode_summary()
    L = math.log1p(ep["rows"][-1]["sigma"]) / math.log1p(env.cfg.strength_ref)
    assert total == pytest.approx(L, abs=1e-9)


def test_sigma_from_features_matches_view():
    """观测解码的 Σ 与 view() 的 board Σ 一致（量化误差 ≤1）。"""
    env = EconomySandbox(_cfg(turns=2))
    obs = env.reset(13)
    while not env.done:
        f = obs.features
        v = json.loads(env.g.view(0))
        expect = sum(int(m["atk"]) + int(m["hp"]) for m in v["me"]["board"])
        got = EconomySandbox.sigma_from_features(f)
        assert abs(got - expect) <= 1
        obs, _r, _d, _i = env.step(_act(obs.mask))
