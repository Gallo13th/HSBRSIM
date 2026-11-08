"""饰品（Trinket）选择 + 指数成长奖励在**纯经济沙盒**里的契约测试。

覆盖（对应 ``docs/COMP_LINES_TINY.md`` §2/§3）：

1. ``--sandbox-trinkets 1``：每局至少出现一次饰品选择，且选择动作**合法**、
   编码落在 ``Choose(0..3)`` = 动作 30..33（引擎 ``Pending::Trinket``）；
2. 默认（``trinkets=None``）与「显式开启」在引擎配置上逐项相同（第 6/9 回合、
   4 选 1），所以默认路径与改动前**逐位一致**；``trinkets=False`` 时一个饰品都不出现；
3. ``exp_growth`` 奖励：``w_super=w_ratio=0`` 时整局求和严格等于 ``L_T``（望远镜），
   且对同一局「加速（凸）曲线」拿到的超线性奖励严格大于「线性（凹）曲线」；
4. ``growth_shape`` 能从真实人类基线（t12=4458 / t15=26516）判出指数段，
   而 15 回合线性成长判不出。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("hsbg_engine")

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    END_TURN, N_ACTIONS, EconomySandbox, SandboxConfig, growth_shape)

#: 引擎里「选择」动作段（``Pending::Trinket`` / Discover / ChooseOne 都用这一段）
CHOOSE_LO, CHOOSE_HI = 30, 46


def _cfg(**kw):
    base = dict(turns=15, gold_per_turn=30, action_cap=40, reward="exp_growth")
    base.update(kw)
    return SandboxConfig(**base)


def _act(mask) -> int:
    """有 Choose 段就先选第一个（饰品/发现），能 EndTurn 就 EndTurn。"""
    choose = [int(a) for a in np.flatnonzero(mask) if CHOOSE_LO <= a <= CHOOSE_HI]
    if choose:
        return choose[0]
    if mask[END_TURN]:
        return END_TURN
    return int(np.flatnonzero(mask)[0])


def _run(cfg, seed=1, act=_act):
    env = EconomySandbox(cfg)
    obs = env.reset(seed)
    log = []          # (turn, action, legal, pending_kind)
    while not env.done:
        a = int(act(obs.mask))
        kind = env._pending_kind() if CHOOSE_LO <= a <= CHOOSE_HI else ""
        log.append((int(obs.turn), a, bool(obs.mask[a]), kind))
        obs, _r, _d, _i = env.step(a)
    return env, log


# ── 1. 可得性 + 动作合法性 ──────────────────────────────────────────────────


def test_trinket_offers_each_game_and_actions_legal():
    """开启饰品后**每局**都至少出现一次饰品选择，且选的动作当时合法。"""
    for seed in (0, 1, 2, 3):
        env, log = _run(_cfg(trinkets=True), seed=seed)
        ep = env.episode_summary()
        assert ep["trinket_offers"] >= 1, f"seed={seed} 一局里没有任何饰品选择"
        # 引擎在 t6 给小饰品、t9 给大饰品 → 正常是 2 次
        assert ep["trinket_offers"] == 2, f"seed={seed} offers={ep['trinket_offers']}"
        assert ep["trinket_count"] >= 1
        # 每一次「饰品选择」的动作都必须在当时的 mask 里合法，并且落在 Choose 段
        trinket_steps = [(t, a, ok) for (t, a, ok, kind) in log
                         if kind == "trinket"]
        assert len(trinket_steps) == 2
        for t, a, ok in trinket_steps:
            assert ok, f"饰品选择动作 {a} 在当时不合法（turn {t}）"
            assert CHOOSE_LO <= a < CHOOSE_LO + 4, f"饰品选项编码越界: {a}"
            assert t in (6, 9), f"饰品选择发生在 turn {t}（应为 6/9）"


def test_trinket_offer_has_four_options():
    """饰品是「4 选 1」：出现待选时 mask 的 Choose 段恰好 4 个合法位。"""
    cfg = _cfg(trinkets=True)
    env = EconomySandbox(cfg)
    obs = env.reset(4)
    seen = 0
    while not env.done:
        if env._pending_kind() == "trinket":
            n = int(obs.mask[CHOOSE_LO:CHOOSE_LO + 12].sum())
            assert n == 4, f"饰品选项数 {n} != 4"
            seen += 1
            obs, _r, _d, _i = env.step(int(np.flatnonzero(
                obs.mask[CHOOSE_LO:CHOOSE_LO + 4])[0] + CHOOSE_LO))
            continue
        obs, _r, _d, _i = env.step(_act(obs.mask))
    assert seen == 2


# ── 2. 默认关/默认开 的等价性 ───────────────────────────────────────────────


def test_default_equals_explicit_trinkets_on():
    """``trinkets=None``（默认）与 ``trinkets=True`` 的引擎配置逐项相同 → 逐位一致。

    引擎默认 ``lesser_trinket_turn=6 / greater_trinket_turn=9 / trinket_choices=4``，
    所以「显式开启」只是把默认值写死，两边的每回合 Σ 必须完全相同。
    """
    a = _cfg(trinkets=None)
    b = _cfg(trinkets=True)
    ea, eb = a.engine_config(), b.engine_config()
    assert ea.get("lesser_trinket_turn") is None          # 默认不写这个键
    assert (eb["lesser_trinket_turn"], eb["greater_trinket_turn"],
            eb["trinket_choices"]) == (6, 9, 4)
    for seed in (0, 5):
        e1, _ = _run(a, seed=seed)
        e2, _ = _run(b, seed=seed)
        s1, s2 = e1.episode_summary(), e2.episode_summary()
        assert s1["sigma_by_turn"] == s2["sigma_by_turn"]
        # 默认路径不新增饰品键（旧度量逐位不变）
        assert "trinket_offers" not in s1 and "trinket_ids" not in s1
        assert "trinket_offers" in s2


def test_trinkets_off_removes_offers():
    """``trinkets=False``：一个饰品都不出现，且动作流里没有饰品待选。"""
    env, log = _run(_cfg(trinkets=False), seed=2)
    ep = env.episode_summary()
    assert ep["trinket_offers"] == 0
    assert ep["trinket_count"] == 0
    assert not [x for x in log if x[3] == "trinket"]
    ec = _cfg(trinkets=False).engine_config()
    assert ec["lesser_trinket_turn"] >= 900 and ec["greater_trinket_turn"] >= 900


# ── 3. exp_growth 奖励 ──────────────────────────────────────────────────────


def test_exp_growth_telescopes_without_extra_terms():
    """``w_super=0, w_ratio=0``：整局 reward 之和 == L_T（与 log_strength 同口径）。"""
    cfg = _cfg(trinkets=True, growth_w_super=0.0, growth_w_ratio=0.0)
    env = EconomySandbox(cfg)
    obs = env.reset(6)
    total = 0.0
    while not env.done:
        obs, r, _d, _i = env.step(_act(obs.mask))
        total += float(r)
    ep = env.episode_summary()
    L = math.log1p(int(ep["rows"][-1]["sigma"])) / math.log1p(env.cfg.strength_ref)
    assert total == pytest.approx(L, abs=1e-9)


def test_exp_growth_rewards_acceleration_not_linearity():
    """超线性项只奖励「ΔlnΣ 超过基线斜率」：凸（加速）曲线拿到的奖励更多。"""
    cfg = _cfg(growth_w_final=0.0, growth_w_super=1.0, growth_slope_base=0.35,
               growth_from=10, growth_w_ratio=0.0)

    def _bonus(sigmas):
        env = EconomySandbox(cfg)
        env.reset(0)
        env.turn_metrics = [{"turn": t, "sigma": s, "tier": 6, "carriers": 0,
                             "spells": 0, "tavern_buff": 0, "gold": 0}
                            for t, s in enumerate(sigmas, start=1)]
        env._prev_L, env._prev_sigma = 0.0, 0
        tot = 0.0
        for row in env.turn_metrics:
            tot += env._turn_reward(dict(row))
        return tot

    lin = [1000 + 1000 * (t - 1) for t in range(1, 16)]          # 线性：Σ 每回合 +1000
    exp = [int(1000 * (1.6 ** (t - 1))) for t in range(1, 16)]    # 复利：每回合 ×1.6
    b_lin, b_exp = _bonus(lin), _bonus(exp)
    # 线性铺场在 t10..t15 的 ΔlnΣ 是 ln(15/14)=0.069 < 基线 0.35 → 一分不给
    assert b_lin == pytest.approx(0.0, abs=1e-9)
    # 复利每回合 ΔlnΣ = ln(1.6) = 0.47 > 基线 0.35 → 6 个回合各拿 0.12
    assert b_exp == pytest.approx(6 * (math.log(1.6) - 0.35), rel=0.02)


# ── 4. 成长曲线判据 ─────────────────────────────────────────────────────────


def test_growth_shape_human_baseline_is_exponential():
    """真实 10k+ p50（t12=4458、t15=26516）判为有指数段；线性成长判为没有。"""
    human = {9: 547, 10: 1132, 11: 2211, 12: 4458, 13: 9446, 14: 20889, 15: 26516}
    h = growth_shape(human)
    assert h["growth_has_exp_segment"] is True
    assert h["growth_ratio_12_15"] == pytest.approx(26516 / 4458, rel=1e-3)
    # 每回合的对数斜率：t9→t14 基本翻倍（≈0.7 e/回合），远高于「线性铺场」
    assert h["growth_slope_late"] > 0.5

    linear = {t: 500 * t for t in range(1, 16)}
    l = growth_shape(linear)
    assert l["growth_has_exp_segment"] is False
    assert l["growth_slope_late"] < 0.1 < h["growth_slope_late"]
    # 注意口径：**lnΣ 的曲率**。纯指数（Σ 每回合 ×常数）在 lnΣ 上是一条**直线**
    # → curv ≈ 0；线性铺场是凹的 → curv < 0；只有「加速成长」（每回合倍数还在变大）
    # 才是 curv > 0。所以判据用 ratio/slope，curv 只作诊断。
    assert l["growth_curv"] < 0.0
    assert h["growth_curv"] > -0.01           # 真实曲线在 lnΣ 上接近直线（真指数）
    assert h["growth_curv"] > l["growth_curv"] - 5e-3


def test_growth_shape_edge_cases():
    assert growth_shape({})["growth_has_exp_segment"] is False
    # Σ12 = 0 时比值定义为 0（不抛 ZeroDivision / 不产生 inf）
    assert growth_shape({1: 0, 12: 0, 15: 100})["growth_ratio_12_15"] == 0.0
