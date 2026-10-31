"""信用分配单测（§B.2 八条 + 动作条件 baseline 的 §B.3 toy 偏差测试）。

覆盖：
1. α→0：均匀核、``N_eff=L``；
2. ``N_eff`` 随 α 单调不增；α=1e3 退化为 one-step；
3. α→∞ 的**几何极限**：与最佳 λ* 的 KL/cosine；与 GAE(0.995) 明显不同；
4. 幂率核 vs 指数核的 cosine/KL 矩阵端点；
5. 估计器等价：``compute_credit(mode="gae")`` 与旧 ``compute_gae`` 逐元素相等；
   terminal/truncated/empty/all-done；归一化权重和=1；L=0 无 NaN；
6. 方差/ESS：``ess == 1/Σw̃²``、ESS 随 α 下降、δ 加常数只平移归一化 A；
7. timebase：turn 模式的未来 elapsed turn 折扣 ≠ decision 步数折扣；
8. baseline 偏差 toy：动作依赖 baseline 的 score 期望非零；中心化不修正；
   双采样修正均值≈0。

纯 numpy，不需要引擎 / GPU；跑法::

    python -m pytest tests/test_credit.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from hsbg.az.train.power_trace import (
    TIMEBASES,
    compact_diagnostics,
    compute_credit,
    effective_sample_size,
    geometric_raw_kernel,
    horizon_normalize,
    kernel_weights,
    power_raw_kernel,
    trace_weights,
)
from hsbg.az.train.ppo import compute_gae


# ══════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════
def _kernel(alpha: float, L: int = 64, kappa: float = 3.0) -> np.ndarray:
    """§B.2 的参考实现（不加 γ、horizon 归一化）。"""
    k = np.arange(L, dtype=np.float64)
    w = (1.0 + k / kappa) ** (-alpha)
    return w / w.sum()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / math.sqrt(float(np.dot(a, a) * np.dot(b, b))))


def _kl(p: np.ndarray, q: np.ndarray) -> float:
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    return float(np.sum(p * np.log(np.maximum(p, 1e-300) / np.maximum(q, 1e-300))))


# ══════════════════════════════════════════════════════════════════════════
# 1–4. 核的极限与几何近似
# ══════════════════════════════════════════════════════════════════════════
def test_alpha_zero_is_uniform_and_ess_equals_L():
    L, kappa = 64, 3.0
    w = _kernel(0.0, L, kappa)
    assert np.allclose(w, np.full(L, 1.0 / L), atol=1e-12)
    assert effective_sample_size(w) == pytest.approx(float(L), abs=1e-9)
    # 与模块参考实现一致
    w2 = kernel_weights(L, "power", alpha=0.0, kappa=kappa, normalize=True)
    assert np.allclose(w, w2, atol=1e-12)
    assert w2.sum() == pytest.approx(1.0, abs=1e-12)


def test_ess_monotone_nonincreasing_and_degenerate_one_step():
    alphas = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 64.0, 1e3]
    ess = [effective_sample_size(_kernel(a)) for a in alphas]
    assert np.all(np.diff(np.asarray(ess)) <= 1e-9)
    w = _kernel(1e3)
    assert effective_sample_size(w) < 1.01
    assert int(np.argmax(w)) == 0
    assert float(w[0]) > 0.999


def test_powerlaw_geometric_limit_matches_small_lambda_not_gae995():
    # §B.2 #3：α=8, κ=1, L=128 → 几何极限 λ*≈0.00424
    L, kappa, alpha = 128, 1.0, 8.0
    w = _kernel(alpha, L, kappa)
    k = np.arange(L, dtype=np.float64)
    lams = np.exp(np.linspace(math.log(1e-4), math.log(0.999), 4000))
    kls, coss = [], []
    for lam in lams:
        g = (1.0 - lam) * np.power(lam, k)
        kls.append(_kl(w, g))
        coss.append(_cosine(w, g))
    i = int(np.argmin(kls))
    lam_star = float(lams[i])
    assert lam_star < 0.01
    assert kls[i] < 1e-3
    assert coss[i] >= 0.999
    # 同一个 w 对 GAE(0.995) 完全不像：α 大 ≠ GAE(0.995)
    g995 = (1.0 - 0.995) * np.power(0.995, k)
    assert _kl(w, g995) > 1.0
    assert _cosine(w, g995) < 0.2


def test_power_vs_exponential_matrix_endpoints():
    # α=0 → uniform；α 很大 + λ→0 → one-step
    L = 64
    uniform = np.full(L, 1.0 / L)
    w0 = _kernel(0.0, L, 3.0)
    assert _cosine(w0, uniform) == pytest.approx(1.0, abs=1e-12)
    w_big = _kernel(64.0, L, 3.0)
    g_small = (1.0 - 1e-4) * np.power(1e-4, np.arange(L, dtype=np.float64))
    assert _cosine(w_big, g_small) > 0.9999
    # 矩阵只记录非单调，不断言：这里只验证输出形状/有限值
    alphas = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
    lams = [1e-4, 1e-3, 0.01, 0.1, 0.5, 0.9, 0.995]
    mat = np.zeros((len(alphas), len(lams)), dtype=np.float64)
    for i, a in enumerate(alphas):
        wa = _kernel(a, L, 3.0)
        for j, lam in enumerate(lams):
            mat[i, j] = _cosine(wa, (1.0 - lam) * np.power(lam, np.arange(L)))
    assert np.all(np.isfinite(mat))
    # α=0 的均匀核与自身 cosine=1；与 λ→0 的几何核也可以很接近（非负向量），
    # 因此这里不断言矩阵端点方向，只保留有限性（§B.2 #4 明确“非单调只记录”）。


def test_gamma_mixing_identity():
    """(1+x)^(−α) = 1/Γ(α) ∫_0^∞ u^{α−1} e^{−u(1+x)} du（数值积分验证）。"""
    from scipy.integrate import quad

    for alpha in (0.5, 1.0, 2.0, 4.0):
        for k in (0.0, 1.0, 7.0, 40.0):
            kappa = 3.0
            x = k / kappa
            integ, _err = quad(
                lambda u: np.power(u, alpha - 1.0) * math.exp(-u * (1.0 + x)),
                0.0, np.inf, limit=300)
            lhs = (1.0 + x) ** (-alpha)
            rhs = integ / math.gamma(alpha)
            assert rhs == pytest.approx(lhs, rel=1e-8, abs=1e-10)


# ══════════════════════════════════════════════════════════════════════════
# 5. 与旧 GAE 等价 / 边界
# ══════════════════════════════════════════════════════════════════════════
def test_compute_credit_gae_is_bitwise_equal_to_legacy():
    rng = np.random.default_rng(123)
    for _ in range(25):
        n = int(rng.integers(1, 40))
        rewards = rng.normal(0.0, 0.2, n)
        values = rng.normal(0.0, 0.5, n)
        dones = np.zeros(n, dtype=np.float64)
        if n > 1:
            dones[int(rng.integers(0, n - 1))] = 1.0
        dones[-1] = 1.0
        for gamma, lam in ((1.0, 0.995), (1.0, 0.95), (0.99, 0.9)):
            a_ref, r_ref = compute_gae(rewards, values, dones, gamma=gamma, lam=lam)
            a, r, diag = compute_credit(rewards, values, dones, mode="gae",
                                        gamma=gamma, lam=lam)
            assert np.array_equal(a, a_ref)
            assert np.array_equal(r, r_ref)
            assert diag["mode"] == "gae"
            assert np.all(np.isfinite(a))


def test_geom_unnormalized_equals_gae_and_power_alpha_zero_equals_uniform_mean():
    rewards = np.array([0.0, 0.0, 1.0, 0.0, 1.0])
    values = np.array([0.5, 0.2, 0.1, 0.3, 0.0])
    dones = np.array([0.0, 0.0, 1.0, 0.0, 1.0])
    a_ref, r_ref = compute_gae(rewards, values, dones, gamma=1.0, lam=0.995)
    a, r, _ = compute_credit(rewards, values, dones, mode="geom", lam=0.995,
                             normalize=False)
    assert np.allclose(a, a_ref, atol=1e-6)
    assert np.allclose(r, r_ref, atol=1e-6)
    # γ=1、λ=1 的 GAE = 未归一化均匀和；power α=0 归一化 = 均匀平均
    ag, _ = compute_gae(rewards, values, dones, gamma=1.0, lam=1.0)
    ap, _, _ = compute_credit(rewards, values, dones, mode="power", alpha=0.0,
                              kappa=3.0, normalize=False)
    assert np.array_equal(ag, ap)
    apn, _, _ = compute_credit(rewards, values, dones, mode="power", alpha=0.0,
                               kappa=3.0, normalize=True)
    # 每步按自己的未来 horizon 归一化：t0 除以 3、t1 除以 2、t2 除以 1
    assert np.allclose(apn[:3], np.array([0.5 / 3.0, 0.8 / 2.0, 0.9]),
                       atol=1e-6)
    assert np.allclose(apn[3:], np.array([-0.3 + 1.0, 1.0]) / np.array([2.0, 1.0]),
                       atol=1e-6)


def test_terminal_truncated_and_all_done_edges():
    # 两个 episode：第 1 段 done 在第 3 步（terminal），第 2 段到数组末尾（truncated）
    rewards = np.array([0.0, 0.5, 1.0, 0.0, 0.2])
    values = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    dones = np.array([0.0, 0.0, 1.0, 0.0, 0.0])  # 第二段无 done = truncated
    a_ref, r_ref = compute_gae(rewards, values, dones, gamma=1.0, lam=0.995)
    for mode, kw in (("gae", {}), ("geom", {"lam": 0.995, "normalize": False})):
        a, r, _ = compute_credit(rewards, values, dones, mode=mode, **kw)
        assert np.allclose(a, a_ref, atol=1e-6), mode
        assert np.allclose(r, r_ref, atol=1e-6), mode
    # all-done：每步独立 episode，horizon=1，power 任意 α 都退化为 δ_t
    dones_all = np.ones(4, dtype=np.float64)
    adv, _ret, diag = compute_credit(np.zeros(4), np.array([0.1, 0.2, 0.3, 0.4]),
                                     dones_all, mode="power", alpha=2.0, kappa=3.0)
    assert np.allclose(adv.astype(np.float64), -np.array([0.1, 0.2, 0.3, 0.4]),
                       atol=1e-6)
    assert diag["n_episodes"] == 4
    assert np.all(diag["ess"] == 1.0)


def test_empty_batch_no_nan_and_zero_length_kernel():
    for mode, kw in (("gae", {}), ("geom", {"lam": 0.9}),
                     ("power", {"alpha": 0.5, "kappa": 3.0})):
        adv, ret, diag = compute_credit([], [], [], mode=mode, **kw)
        assert adv.size == 0 and ret.size == 0
        assert diag["n"] == 0 and diag["n_episodes"] == 0
        assert not np.isnan(diag["adv_var"])
    w = kernel_weights(0, "power", alpha=0.5, kappa=3.0)
    assert w.size == 0
    assert effective_sample_size(w) == 0.0
    a, _r, _d = compute_credit([0.0], [0.5], [1.0], mode="power", alpha=0.0,
                               kappa=1e-6)
    assert np.isfinite(a).all()


# ══════════════════════════════════════════════════════════════════════════
# 6. ESS 定义 / 方差 / 平移不变
# ══════════════════════════════════════════════════════════════════════════
def test_ess_definition_and_alpha_monotonicity_on_episode():
    n = 16
    rewards = np.zeros(n)
    rewards[-1] = 1.0
    values = np.linspace(0.4, -0.4, n)
    dones = np.zeros(n)
    dones[-1] = 1.0
    ess = []
    for alpha in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0):
        adv, _ret, diag = compute_credit(rewards, values, dones, mode="power",
                                         alpha=alpha, kappa=3.0)
        w = kernel_weights(n, "power", alpha=alpha, kappa=3.0)
        w = horizon_normalize(w)
        assert diag["ess"][0] == pytest.approx(1.0 / float(np.dot(w, w)), rel=1e-9)
        assert diag["ess_mean"] <= n + 1e-9
        ess.append(diag["ess_mean"])
    assert np.all(np.diff(ess) <= 1e-9)
    # 所有 δ 加常数 c：归一化 A 只平移 c（γ=1）
    adv1, _r, _d = compute_credit(rewards, values, dones, mode="power",
                                  alpha=0.5, kappa=3.0)
    adv2, _r, _d = compute_credit(rewards + 0.7, values, dones, mode="power",
                                  alpha=0.5, kappa=3.0)
    assert np.allclose(adv2.astype(np.float64) - adv1.astype(np.float64), 0.7,
                       atol=2e-6)


def test_power_cutoff_and_gamma():
    n = 8
    rewards = np.zeros(n)
    rewards[-1] = 1.0
    values = np.linspace(0.5, -0.5, n)
    dones = np.zeros(n)
    dones[-1] = 1.0
    adv, _ret, diag = compute_credit(rewards, values, dones, mode="power",
                                     alpha=0.0, kappa=3.0, cutoff=2,
                                     normalize=True)
    assert diag["cutoff"] == 2
    assert np.isfinite(adv).all()
    # α=0 + cutoff=2：每个 t 只用最近 3 个 TD（lag 0,1,2）的未归一化平均
    deltas = np.zeros(n)
    for t in range(n):
        nxt = values[t + 1] if t + 1 < n else 0.0
        deltas[t] = rewards[t] + nxt - values[t]
    ref = np.array([np.mean(deltas[t:t + 3]) for t in range(n - 2)]
                   + [np.mean(deltas[n - 2:]), deltas[n - 1]])
    assert np.allclose(adv.astype(np.float64), ref, atol=1e-6)
    # γ<1 时只有折扣
    advg, _r, _d = compute_credit(rewards, values, dones, mode="power",
                                  alpha=0.0, kappa=3.0, gamma=0.9)
    assert np.isfinite(advg).all()
    assert not np.allclose(advg, adv)


# ══════════════════════════════════════════════════════════════════════════
# 7. timebase
# ══════════════════════════════════════════════════════════════════════════
def test_timebase_turn_uses_elapsed_turns_not_action_steps():
    turns = np.array([0, 0, 0, 1], dtype=np.int64)  # 同一 turn 3 个 action
    rewards = np.array([0.0, 0.0, 0.0, 1.0])
    values = np.array([0.9, 0.8, 0.7, 0.6])
    dones = np.array([0.0, 0.0, 0.0, 1.0])
    gamma = 0.9
    adv_d, _r, _d = compute_credit(rewards, values, dones, mode="power", alpha=0.0,
                                   kappa=3.0, gamma=gamma, timebase="decision")
    adv_t, _r, _d = compute_credit(rewards, values, dones, mode="power", alpha=0.0,
                                   kappa=3.0, gamma=gamma, timebase="turn",
                                   turns=turns)
    delta = np.array([-0.18, -0.17, -0.16, 0.4])
    # decision：lag=[0,1,2,3]；turn：lag=[0,0,0,1]
    ref_d = float(np.mean(delta * gamma ** np.arange(4.0)))
    ref_t = float(np.mean(delta * gamma ** np.array([0.0, 0.0, 0.0, 1.0])))
    assert adv_d[0] == pytest.approx(ref_d, abs=1e-9)
    assert adv_t[0] == pytest.approx(ref_t, abs=1e-9)
    assert abs(float(adv_d[0] - adv_t[0])) > 1e-4
    # duration 显式给（0,0,1,?）时与 turns 一致：0->1、1->2 同一 turn，2->3 过 1 turn
    adv_dur, _r, _d = compute_credit(rewards, values, dones, mode="power", alpha=0.0,
                                     kappa=3.0, gamma=gamma, timebase="turn",
                                     duration=np.array([0.0, 0.0, 1.0, 1.0]))
    assert adv_dur[0] == pytest.approx(ref_t, abs=1e-9)


# ══════════════════════════════════════════════════════════════════════════
# 8. baseline 偏差 toy（§B.3）
# ══════════════════════════════════════════════════════════════════════════
def _softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - np.max(z))
    return e / e.sum()


def test_action_dependent_baseline_is_biased_and_centering_does_not_fix_it():
    theta = np.array([0.2, -0.4, 0.1], dtype=np.float64)
    pi = _softmax(theta)
    b = np.array([1.0, 0.0, 0.0])  # b(a)=1[a=0]
    eye = np.eye(3)
    # score(a) = e_a − π；E[score · b] = Σ_a π_a (e_a − π) b_a
    scores = eye - pi[None, :]
    bias = np.sum(pi[:, None] * scores * b[:, None], axis=0)
    assert np.linalg.norm(bias) > 1e-3  # 动作依赖 baseline 有偏

    # 中心化 b̄(a)=b(a)−E_π[b]：score 期望仍等于同一偏差（中心化不修正）
    b_centered = b - float(np.dot(pi, b))
    bias_centered = np.sum(pi[:, None] * scores * b_centered[:, None], axis=0)
    assert np.allclose(bias_centered, bias, atol=1e-12)

    rng = np.random.default_rng(7)
    n = 1_000_000
    idx = rng.choice(3, size=n, p=pi)
    emp = scores[idx].mean(axis=0) * b[idx].reshape(-1, 1)
    emp = np.mean(scores[idx] * b[idx].reshape(-1, 1), axis=0)
    assert np.allclose(emp, bias, atol=3e-3)
    # 双采样：a 用于 score，独立 a' 用于 baseline → 无偏（≈0）
    idx2 = rng.choice(3, size=n, p=pi)
    emp_double = np.mean(scores[idx] * b[idx2].reshape(-1, 1), axis=0)
    assert np.linalg.norm(emp_double) < 3e-3
    # 中心化版本的蒙特卡洛仍≈偏差，不是≈0
    emp_centered = np.mean(scores[idx] * b_centered[idx].reshape(-1, 1), axis=0)
    assert np.allclose(emp_centered, bias, atol=3e-3)


# ══════════════════════════════════════════════════════════════════════════
# 9. 非法参数
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kwargs", [
    {"alpha": -0.1},
    {"kappa": 0.0},
    {"kappa": -1.0},
    {"alpha": float("nan")},
    {"gamma": 0.0},
    {"gamma": 1.5},
    {"lam": -0.1},
    {"lam": 1.1},
    {"mode": "fractional-lite"},
    {"timebase": "action-turn"},
    {"cutoff": -1},
])
def test_invalid_params_raise(kwargs):
    base = dict(mode="power", alpha=0.5, kappa=3.0, gamma=1.0, lam=0.995,
                cutoff=0, timebase="decision")
    base.update(kwargs)
    if base["mode"] == "gae" and base.get("cutoff", 0) > 0:
        pytest.skip("gae+cutoff 由专门用例覆盖")
    with pytest.raises(ValueError):
        compute_credit([0.0, 1.0], [0.5, 0.0], [0.0, 1.0], **base)


def test_gae_rejects_cutoff_and_normalize_and_turn_timebase():
    with pytest.raises(ValueError):
        compute_credit([0.0], [0.0], [1.0], mode="gae", cutoff=2)
    with pytest.raises(ValueError):
        compute_credit([0.0], [0.0], [1.0], mode="gae", normalize=True)
    with pytest.raises(ValueError):
        compute_credit([0.0], [0.0], [1.0], mode="gae", timebase="turn",
                       turns=[0])


def test_turn_timebase_requires_turns_and_monotone():
    with pytest.raises(ValueError):
        compute_credit([0.0], [0.0], [1.0], mode="power", timebase="turn")
    with pytest.raises(ValueError):
        compute_credit([0.0, 0.0, 1.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                       mode="power", timebase="turn", turns=[2, 1, 2])


def test_compact_diagnostics_has_no_arrays():
    diag = compute_credit([0.0, 1.0], [0.5, 0.0], [0.0, 1.0], mode="power",
                          alpha=0.5, kappa=3.0)[2]
    compact = compact_diagnostics(diag)
    assert compact["mode"] == "power"
    assert not any(isinstance(v, np.ndarray) for v in compact.values())
    assert "ess_p50" in compact and "terminal_share_p50" in compact


# ══════════════════════════════════════════════════════════════════════════
# 10. 模块常量
# ══════════════════════════════════════════════════════════════════════════
def test_mode_and_timebase_constants():
    assert set(TIMEBASES) == {"decision", "turn"}
    assert set(TIMEBASES).issubset({"decision", "turn"})
    # 后向资格迹：lag 权重 = 幂率核 × γ^k（不含归一化，也不是 advantage）
    w = trace_weights(6, alpha=0.5, kappa=3.0, gamma=0.9)
    lag = np.arange(6, dtype=np.float64)
    assert np.allclose(w, (1.0 + lag / 3.0) ** (-0.5) * 0.9 ** lag, atol=1e-12)
    assert not np.allclose(w, w / w.sum())  # 迹权重不归一化
    # 几何核的 γ 不重复计入（kernel_weights 的 γ^l 由调用方另乘）
    w2 = kernel_weights(5, "power", alpha=0.0, kappa=3.0, gamma=0.5,
                        normalize=False)
    assert np.allclose(w2, 0.5 ** np.arange(5.0))


# ══════════════════════════════════════════════════════════════════════════
# 11. PPO 接线：默认 gae 逐位等价 / power 只改 advantages
# ══════════════════════════════════════════════════════════════════════════
def _tiny_records() -> list:
    from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS

    rng = np.random.default_rng(11)
    recs = []
    for game_id, seats in ((0, (0, 1)), (1, (0,))):
        for seat in seats:
            n = 4
            rank = 1 + (game_id + seat) % 8
            for i in range(n):
                mask = np.zeros(N_ACTIONS, dtype=bool)
                mask[0] = True
                recs.append({
                    "features": np.zeros(OBS_FLOATS, dtype=np.float32),
                    "cards": np.zeros(OBS_CARDS, dtype=np.int32),
                    "mask": mask,
                    "action": 0,
                    "old_logprob": 0.0,
                    "value": float(rng.normal(0.0, 0.3)),
                    "seat": int(seat), "game_id": int(game_id),
                    "turn": int(i), "rank": int(rank),
                    "forced": False,
                })
    return recs


def test_build_batch_default_gae_is_bitwise_equal_and_power_only_changes_adv():
    from hsbg.az.train.ppo import build_batch_from_records

    recs = _tiny_records()
    base = build_batch_from_records(recs)
    exp = build_batch_from_records(recs, adv_estimator="gae")
    for name in ("features", "cards", "masks", "actions", "old_logprobs",
                 "values", "rewards", "dones", "advantages", "returns",
                 "seats", "game_ids", "ranks", "turns", "forced"):
        a = getattr(base, name)
        b = getattr(exp, name)
        assert np.array_equal(a, b), name
    assert "adv_estimator" not in base.meta
    assert "credit" not in base.meta

    pw = build_batch_from_records(
        recs, adv_estimator="power", power_alpha=0.25, power_kappa=10.0,
        power_normalize=False)
    assert pw.meta["adv_estimator"] == "power"
    assert pw.meta["credit"]["mode"] == "power"
    # 策略侧输入/动作/old_logp 逐位不变，只有 advantage/returns 变
    for name in ("features", "cards", "masks", "actions", "old_logprobs",
                 "values", "rewards", "dones", "seats", "game_ids", "ranks",
                 "turns", "forced"):
        assert np.array_equal(getattr(base, name), getattr(pw, name)), name
    assert not np.array_equal(base.advantages, pw.advantages)
    assert np.all(np.isfinite(pw.advantages))


def test_ppo_config_rejects_action_dependent_baseline_and_bad_credit():
    from hsbg.az.train.ppo import PPOConfig

    with pytest.raises(ValueError):
        PPOConfig(baseline_action_dependent=1)
    with pytest.raises(ValueError):
        PPOConfig(adv_estimator="fractional")
    with pytest.raises(ValueError):
        PPOConfig(adv_estimator="power", power_alpha=-0.1)
    with pytest.raises(ValueError):
        PPOConfig(adv_estimator="power", power_kappa=0.0)
    with pytest.raises(ValueError):
        PPOConfig(adv_estimator="gae", credit_timebase="turn")
    # 默认构造仍合法（逐位等价旧路径）
    cfg = PPOConfig()
    assert cfg.adv_estimator == "gae" and cfg.baseline_action_dependent == 0
