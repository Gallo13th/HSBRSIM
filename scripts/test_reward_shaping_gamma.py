"""塑形折扣与训练 γ 对齐（P0 修复）单测。

覆盖：
1. γ_s == 训练 γ 时，整局 F 按训练折扣求和 == ``−c·Φ(s_0)``（望远镜，与策略无关）；
2. γ_s ≠ 训练 γ 时，累积偏差 == 解析式
   ``c·(γ_s−γ_t)·Σ_t γ_t^t Φ(s_{t+1})``，且 ``RewardShaper`` 的统计字段一致；
3. ``shaping_coef=0`` 逐位等价：不写 record、不产生 meta、不读/不校验 shaping_gamma；
4. ``shaping_gamma=None``（默认）严格跟随训练 γ（``cfg.gamma`` / ``gamma=`` 参数）。
"""

from __future__ import annotations

import pickle
import warnings

import numpy as np
import pytest

from hsbg.az.train.ppo import CollectConfig
from hsbg.az.train.reward_shaping import (SHAPING_GAMMA, RewardShaper,
                                          aggregate_shaping,
                                          shaping_bias_per_episode,
                                          shaping_gamma_warning,
                                          shaping_reward)

COEF = 1e-3


def _episode(phis, gamma: float) -> np.ndarray:
    """按 ``phis``（Φ(s_0..s_{T−1})，终局 Φ=0）算整局逐决策 F。"""
    out = []
    for i, phi in enumerate(phis):
        nxt = phis[i + 1] if i + 1 < len(phis) else 0.0
        out.append(shaping_reward(phi, nxt, COEF, gamma=gamma))
    return np.asarray(out, dtype=np.float64)


def _attach_episode(shaper: RewardShaper, phis, *, game_id: int = 7):
    recs = [{"game_id": int(game_id)} for _ in phis]
    for i, phi in enumerate(phis):
        nxt = phis[i + 1] if i + 1 < len(phis) else 0.0
        assert shaper.attach(recs, i, int(game_id), float(phi), float(nxt))
    return recs


# ── 1. γ 对齐：望远镜求和 == −c·Φ0 ─────────────────────────────────────
@pytest.mark.parametrize("gamma", [1.0, 0.97])
def test_aligned_gamma_telescopes_to_minus_c_phi0(gamma):
    phis = np.array([100.0, 40.0, 180.0, 520.0, 27000.0])
    fs = _episode(phis, gamma)
    disc = np.array([gamma ** t for t in range(len(phis))])
    assert float(np.sum(disc * fs)) == pytest.approx(-COEF * phis[0], abs=1e-9)

    # 接线路径：默认 shaping_gamma=None 跟随训练 γ，attach 写回的 F 同样望远镜。
    cfg = CollectConfig(shaping_coef=COEF)
    shaper = RewardShaper(cfg, gamma=gamma)
    assert shaper.gamma_aligned
    recs = _attach_episode(shaper, phis)
    got = np.array([r["reward"] for r in recs], dtype=np.float64)
    assert np.array_equal(got, fs)          # 与纯函数逐位一致
    assert float(np.sum(disc * got)) == pytest.approx(-COEF * phis[0], abs=1e-9)
    # 对齐时不应产生偏差项
    assert shaper.stats()["reward_shaping_bias_sum"] == 0.0


# ── 2. γ 不对齐：累积偏差 == 解析式 ────────────────────────────────────
def test_mismatch_bias_matches_analytic_formula():
    gamma_s, gamma_t = 0.995, 1.0
    phis = np.array([120.0, 300.0, 900.0, 27000.0])
    fs = _episode(phis, gamma_s)
    # 解析式：Σγ_t^t F_t = −cΦ0 + c(γ_s−γ_t)Σγ_t^t Φ(s_{t+1})，末项 Φ=0
    extra = sum(COEF * (gamma_s - gamma_t) * (gamma_t ** t) * phis[t + 1]
                for t in range(len(phis) - 1))
    assert float(np.sum(fs)) == pytest.approx(-COEF * phis[0] + extra, abs=1e-12)
    assert extra < 0.0                       # γ_s<γ_t → 长局被系统性惩罚

    cfg = CollectConfig(shaping_coef=COEF, shaping_gamma=gamma_s)
    with pytest.warns(UserWarning, match="不一致"):
        shaper = RewardShaper(cfg, gamma=gamma_t)
    recs = _attach_episode(shaper, phis)
    assert float(np.sum([r["reward"] for r in recs])) == pytest.approx(
        -COEF * phis[0] + extra, abs=1e-12)
    st = shaper.stats()
    assert st["shaping_gamma"] == pytest.approx(gamma_s)
    assert st["shaping_gamma_train"] == pytest.approx(gamma_t)
    assert st["shaping_gamma_aligned"] is False
    assert st["reward_shaping_bias_sum"] == pytest.approx(extra, abs=1e-15)
    agg = aggregate_shaping([st])
    assert agg["reward_shaping_bias_sum"] == pytest.approx(extra, abs=1e-15)
    assert agg["shaping_gamma_aligned"] is False

    # 启动期估算：常数轨迹时与解析式严格一致
    bias = shaping_bias_per_episode(COEF, gamma_s, gamma_t,
                                    decisions=4, mean_phi=500.0)
    assert bias == pytest.approx(COEF * (gamma_s - gamma_t) * 500.0 * 4)
    assert bias < 0.0
    msg = shaping_gamma_warning(COEF, gamma_s, gamma_t,
                                decisions=4, mean_phi=500.0)
    assert "不一致" in msg and "reward_shaping_bias_sum" in msg


# ── 3. coef=0 逐位等价 ─────────────────────────────────────────────────
def test_zero_coef_bitwise_equivalent_and_ignores_bad_gamma():
    recs = [{"game_id": 0, "reward": 0.25, "features": b"x"},
            {"game_id": 0}, {"game_id": 1, "rank": 3}]
    before = pickle.dumps(recs)
    # 即使 shaping_gamma 非法/不一致，coef=0 也不解析、不警告、不写 record
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        shaper = RewardShaper(
            CollectConfig(shaping_coef=0.0, shaping_gamma=0.5,
                          shaping_tier_bonus="not-a-number"),
            gamma=1.0)
    assert not caught
    assert shaper.enabled is False
    for i in range(len(recs)):
        assert shaper.attach(recs, i, int(recs[i].get("game_id", 0)),
                             10.0, 20.0) is False
    assert pickle.dumps(recs) == before       # 逐位不变（含已有 reward 字段）
    assert shaper.potential(None, 0) == 0.0
    assert shaper.stats() == {}
    assert aggregate_shaping([shaper.stats()]) == {}


# ── 4. 默认跟随训练 γ ──────────────────────────────────────────────────
def test_default_shaping_gamma_follows_training_gamma():
    for g in (1.0, 0.99):
        shaper = RewardShaper(CollectConfig(shaping_coef=COEF), gamma=g)
        assert shaper.gamma_explicit is False
        assert shaper.gamma == g
        assert shaper.gamma_train == g
        assert shaper.gamma_aligned
        assert shaper.stats()["shaping_gamma"] == pytest.approx(g)
        assert shaper.stats()["shaping_gamma_train"] == pytest.approx(g)
        assert shaper.stats()["reward_shaping_bias_sum"] == 0.0

    # 没有 gamma kwarg 时读 cfg.gamma（PPOConfig.gamma 的透传口径）
    cfg = CollectConfig(shaping_coef=COEF)
    cfg.gamma = 0.96                    # 采集配置上的训练 γ 透传
    shaper = RewardShaper(cfg)
    assert shaper.gamma == 0.96
    assert shaper.gamma_aligned
    # 纯函数默认值本身也必须与训练默认 γ 对齐（历史硬编码 0.995 的回归）
    assert SHAPING_GAMMA == 1.0

    # 显式一致 → 对齐、不警告
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        aligned = RewardShaper(
            CollectConfig(shaping_coef=COEF, shaping_gamma=1.0), gamma=1.0)
    assert aligned.gamma_aligned

    # 显式不一致 → 警告 + 统计字段标记
    with pytest.warns(UserWarning):
        bad = RewardShaper(
            CollectConfig(shaping_coef=COEF, shaping_gamma=0.995), gamma=1.0)
    assert bad.gamma == pytest.approx(0.995)
    assert bad.gamma_aligned is False
    assert bad.stats()["shaping_gamma_aligned"] is False
