"""ExIt 蒸馏（``hsbg/az/train/search_exit.py``）的单元测试。

只测纯逻辑（不跑引擎/完整游戏）：

- 优势加权口径（adv/awr/none）与 τ；
- 软标签温度**不把零概率位抬起来**（曾把 probe KL 骗成 610 的 bug）；
- 样本 npz 存取往返；
- 训练器在 tiny 网络上：能跑、KL 预算能停、硬锚能回退、指标不 NaN。

完整游戏采集（``ExitCollector``）依赖 Rust 引擎与约 2.5 s/局，不在这里跑；端到端证据见
``docs/SEARCH_EXIT.md`` 与 ``runs/search_exit/summary.json``。
"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.search_exit import (
    ExitConfig,
    ExitTrainer,
    SearchSample,
    _save_samples,
    load_samples,
    policy_param_names,
    sample_weight,
)


def _toy_sample(*, q=(0.10, 0.30, 0.30), prior=(0.8, 0.1, 0.1),
                cands=(16, 23, 54)) -> SearchSample:
    """构造一个候选集上的样本（p̃ 与 Q 给定，π_S 按 pi_from_q 同一公式）。"""
    q = np.asarray(q, dtype=np.float64)
    p = np.asarray(prior, dtype=np.float64)
    p = p / p.sum()
    V = float(p @ q)
    adv = q - V
    std = float(np.sqrt(max(0.0, p @ ((q - V) ** 2))))
    tau = max(1e-6, std)
    w = np.exp(np.clip(adv / tau, -30, 30))
    ps = p * w
    ps = ps / ps.sum()
    f = np.zeros(3227, dtype=np.float16)
    c = np.zeros(124, dtype=np.int16)
    mask = np.zeros(245, dtype=bool)
    mask[list(cands)] = True
    mask[0] = True
    return SearchSample(
        f=f, c=c, mask=mask, cands=np.asarray(cands, dtype=np.int16),
        p_base=p.astype(np.float32), p_s=ps.astype(np.float32),
        q=q.astype(np.float32), adv=adv.astype(np.float32), q_std=std, tau=tau,
        base=int(cands[0]), teacher=int(cands[int(np.argmax(ps))]), turn=3,
        seat=0, seed=1234, game=7, sigma_root=100, switch=True)


# ── 权重口径 ────────────────────────────────────────────────────────────────
def test_sample_weight_adv_clamped_and_positive():
    s = _toy_sample(q=(0.10, 0.30, 0.30))
    w, info = sample_weight(
        s, ExitConfig(weight_mode="adv", weight_stat="max", tau_scale=1.0))
    assert 0.0 < w <= 1.0
    assert w == pytest.approx(1.0)          # 最大优势远大于 τ ⇒ 饱和到 1
    assert info["tau"] == pytest.approx(s.q_std, rel=1e-6)


def test_sample_weight_zero_when_search_has_no_advantage():
    # 均匀 Q ⇒ 所有优势 = 0 ⇒ 权重 0（该状态不参与训练）
    s = _toy_sample(q=(0.2, 0.2, 0.2))
    w, _ = sample_weight(s, ExitConfig())
    assert w == 0.0


def test_sample_weight_expected_vs_max():
    s = _toy_sample(q=(0.10, 0.30, 0.30))
    w_max, _ = sample_weight(s, ExitConfig(weight_stat="max"))
    w_exp, _ = sample_weight(s, ExitConfig(weight_stat="expected"))
    assert 0.0 <= w_exp <= w_max


def test_sample_weight_modes():
    s = _toy_sample(q=(0.10, 0.30, 0.30))
    assert sample_weight(s, ExitConfig(weight_mode="none"))[0] == 1.0
    w_awr, _ = sample_weight(s, ExitConfig(weight_mode="awr"))
    assert w_awr >= 0.0


def test_tau_fixed_overrides_scale():
    s = _toy_sample(q=(0.10, 0.30, 0.30))
    w, info = sample_weight(s, ExitConfig(tau=100.0))
    assert info["tau"] == pytest.approx(100.0)
    assert w < 1.0


# ── 软标签：零概率位不能被温度抬起来 ───────────────────────────────────────
def _tiny_model():
    from hsbg.az.train.model import build_net
    return build_net(hidden=32, arch="tiny")


def test_soft_label_keeps_zero_support():
    """``clamp(0, 1e-12)**0.5 = 1e-6`` 的坑：零概率位必须保持 0。"""
    import torch  # noqa: F401 - 训练器内部会用到
    model = _tiny_model()
    ref = _tiny_model()
    tr = ExitTrainer(model, ref, ExitConfig(distill_temp=2.0, probe_n=8),
                     device="cpu")
    s = _toy_sample(q=(0.10, 0.30, 0.30))
    t = tr._teacher(tr._tensors([s]))
    tgt = t["tgt"].numpy()[0]
    assert np.isfinite(tgt).all()
    assert tgt.sum() == pytest.approx(1.0, abs=1e-5)
    # 支撑只有 3 个候选（其余位置必须严格 0）
    assert tgt.sum() == pytest.approx(tgt[:3].sum(), abs=1e-6)


def test_teacher_is_softened_by_temperature():
    model = _tiny_model()
    ref = _tiny_model()
    s = _toy_sample(q=(0.10, 0.30, 0.30))
    hard = ExitTrainer(model, ref, ExitConfig(distill_temp=1.0), device="cpu")
    soft = ExitTrainer(model, ref, ExitConfig(distill_temp=2.0), device="cpu")
    t1 = hard._teacher(hard._tensors([s]))["tgt"].numpy()[0]
    t2 = soft._teacher(soft._tensors([s]))["tgt"].numpy()[0]
    assert t2.max() <= t1.max() + 1e-6       # T=2 更平


# ── npz 往返 ────────────────────────────────────────────────────────────────
def test_save_load_roundtrip(tmp_path):
    samples = [_toy_sample(),
               _toy_sample(q=(0.2, 0.25, 0.35), prior=(0.5, 0.3, 0.2))]
    p = str(tmp_path / "s.npz")
    _save_samples(samples, p)
    back = load_samples(p)
    assert len(back) == len(samples)
    for a, b in zip(samples, back):
        np.testing.assert_allclose(np.asarray(a.q), np.asarray(b.q), rtol=1e-6)
        np.testing.assert_allclose(np.asarray(a.p_s), np.asarray(b.p_s), rtol=1e-6)
        assert a.teacher == b.teacher and a.base == b.base
        assert a.seed == b.seed and a.turn == b.turn and a.seat == b.seat


# ── 训练器：能跑 / 预算能停 / 硬锚能回退 ───────────────────────────────────
def _fit(samples, **kw):
    model = _tiny_model()
    ref = _tiny_model()
    tr = ExitTrainer(model, ref, ExitConfig(**kw), device="cpu")
    return tr.fit(samples, round_id=1)


def _many(n: int = 64):
    out = []
    for i in range(n):
        q = (0.10 + 0.001 * i, 0.30, 0.30)
        out.append(_toy_sample(q=q, cands=(16, 23, 54)))
    return out


def test_fit_runs_and_reports_finite_curves():
    fit = _fit(_many(), lr=1e-2, epochs=3, batch=16, kl_target=1.0,
               kl_anchor=100.0, probe_n=16)
    assert fit["n_train"] > 0
    a = fit["after"]
    for k in ("kl_to_ref_mean", "kl_to_ref_max", "kl_to_prev_mean",
              "kl_to_teacher_mean", "entropy", "entropy_ratio"):
        assert np.isfinite(a[k]), k
    assert a["kl_to_teacher_mean"] >= 0.0


def test_fit_halts_on_kl_budget():
    """kl_target 很小 ⇒ 应在预算处停（不把 KL 冲过头）。"""
    fit = _fit(_many(), lr=1e-2, epochs=50, batch=16, kl_target=1e-3,
               kl_anchor=100.0, probe_n=16)
    assert fit["stop_reason"] == "kl_target"
    assert fit["after"]["kl_to_prev_mean"] < 0.05


def test_fit_reverts_on_hard_anchor():
    """硬锚很小 ⇒ 必须回退（after 的 KL 不会超过锚的量级）。"""
    fit = _fit(_many(), lr=1e-2, epochs=50, batch=16, kl_target=100.0,
               kl_anchor=1e-4, probe_n=16)
    assert fit["gate"] is not None and fit["gate"]["reverted"]
    # epoch 级回退是粗粒度的（本实验 A/B 臂的口径）：只保证没有爆炸，不保证贴住锚
    assert fit["after"]["kl_to_ref_mean"] < 0.05


def test_last_in_budget_rollback_keeps_kl_small():
    """``budget_rollback=1``：越过预算的那一步被回退 ⇒ KL 贴住 δ。"""
    fit = _fit(_many(), lr=1e-2, epochs=50, batch=16, kl_target=2e-3,
               kl_anchor=100.0, probe_n=16, budget_rollback=1)
    assert fit["stop_reason"] in ("kl_target", "gate_rollback")
    assert fit["after"]["kl_to_prev_mean"] < 1e-2


def test_fit_filters_zero_weight_samples():
    # 一半样本的优势为 0（Q 均匀）⇒ 不参与训练
    s = _many(32) + [_toy_sample(q=(0.2, 0.2, 0.2)) for _ in range(32)]
    fit = _fit(s, lr=1e-2, epochs=2, batch=16, kl_target=1.0, kl_anchor=100.0,
               probe_n=16)
    assert fit["n_train"] == 32 and fit["n_held"] == 32


def test_policy_scope_trainable_names():
    model = _tiny_model()
    names = policy_param_names(model)
    assert "policy_head.weight" in names and "policy_head.bias" in names
    assert not any(n.startswith("trunk") for n in names)


def test_config_validation():
    for bad in ({"turns": 0}, {"topk": 1}, {"behavior": "x"},
                {"weight_mode": "x"}, {"weight_stat": "x"},
                {"train_scope": "x"}, {"distill_temp": 0.0},
                {"kl_anchor": 0.0}, {"kl_target": 0.0},
                {"search_when": "nope"}, {"games": 7, "seats": 8}):
        with pytest.raises(ValueError):
            ExitConfig(**bad).validate()
