"""``--gold-mode {fixed,add,growth}``（沙盒的「会复利的收入」）契约测试。

覆盖 ``docs/COMPOUND_INCOME.md`` §2：

1. **三档金币轨迹**：``fixed`` / ``add`` / ``growth`` 的 ``income_for_turn(t)`` 与
   实测 ``gold_income_hist`` / ``gold_start_hist`` 逐项正确（含引擎自然收入 3→10、
   ``gold_cap``、``income_scale``、``gold_per_carrier``）；
2. **默认逐位等价**：``fixed`` 与旧别名 ``set`` 的动作流 / Σ 轨迹 / 奖励完全相同，
   且默认每回合金币就是 ``gold_per_turn``（15×30 = 450）；
3. **与饰品开关组合无冲突**：``trinkets=None/True/False`` × 三档都能跑，
   饰品报价次数与金币口径互不影响（``fixed`` 会覆盖回合开始的金币，``add``/``growth`` 保留）；
4. **Σ/金币 汇总口径**：``summarize()`` 会给出 ``sigma12_per_gold_p50`` 等键。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("hsbg_engine")

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    END_TURN, EconomySandbox, SandboxConfig, summarize)

#: 引擎自然补币：``min(start_gold + gold_increment×(t−1), gold_refill_cap)`` = 3,4,...,10,10,...
NATURAL = [min(3 + (t - 1), 10) for t in range(1, 16)]


def _cfg(**kw):
    base = dict(turns=15, gold_per_turn=30, action_cap=40, trinkets=False)
    base.update(kw)
    return SandboxConfig(**base)


def _act(mask) -> int:
    if mask[END_TURN]:
        return END_TURN
    return int(np.flatnonzero(mask)[0])


def _run(cfg, seed: int = 1):
    env = EconomySandbox(cfg)
    obs = env.reset(seed)
    acts = []
    while not env.done:
        a = _act(obs.mask)
        acts.append(int(a))
        obs, _r, _d, _i = env.step(int(a))
    return env, acts


# ── 1. 三档轨迹 ─────────────────────────────────────────────────────────────


def test_fixed_gold_trajectory_is_legacy_set():
    """``fixed``：每回合金币 == gold_per_turn（15×30 = 450），与旧 ``set`` 一致。"""
    env, _ = _run(_cfg(gold_mode="fixed"))
    assert [env.income_for_turn(t) for t in (1, 8, 15)] == [30, 30, 30]
    ep = env.episode_summary()
    assert ep["gold_income_hist"] == [30] * 15
    assert ep["gold_start_hist"] == [30] * 15
    assert ep["gold_total_income"] == 450
    assert ep["gold_total_injected"] == 450


def test_add_gold_trajectory_is_linear_and_keeps_engine_income():
    """``add``：第 t 回合注入 ``30 + 5×(t−1)``，且**保留**引擎自然补币 → 两者相加。"""
    env, _ = _run(_cfg(gold_mode="add", gold_add=5))
    assert [env.income_for_turn(t) for t in (1, 2, 15)] == [30, 35, 100]
    ep = env.episode_summary()
    inc = [30 + 5 * (t - 1) for t in range(1, 16)]
    assert ep["gold_income_hist"] == inc
    # gold_start = min(cap, 引擎自然收入 + 注入)；默认 cap = 99
    assert ep["gold_start_hist"] == [min(99, n + i) for n, i in zip(NATURAL, inc)]
    assert ep["gold_total_income"] > 450


def test_growth_gold_trajectory_is_geometric():
    """``growth``：``gold_per_turn×(1+rate)^(t−1)``；``income_scale`` 整体缩放。"""
    env, _ = _run(_cfg(gold_mode="growth", gold_growth_rate=0.15))
    assert [env.income_for_turn(t) for t in (1, 2, 15)] == [30, 34, 212]
    ep = env.episode_summary()
    assert ep["gold_income_hist"] == [
        int(round(30 * 1.15 ** (t - 1))) for t in range(1, 16)]
    assert ep["gold_total_income"] > 450
    # 无上限时才可能超过 99（这里用 cap=0 的独立环境验证公式，不依赖对局结果）
    env2 = EconomySandbox(_cfg(gold_mode="growth", gold_growth_rate=0.15,
                              income_scale=2.0, gold_cap=0))
    assert env2.income_for_turn(1) == 60
    assert env2.income_for_turn(15) == int(round(2.0 * 30 * 1.15 ** 14))


def test_growth_per_carrier_term_uses_previous_turn_board():
    """``gold_per_carrier``：用**上回合**在场上载体数（第 1 回合为 0）。"""
    env = EconomySandbox(_cfg(gold_mode="growth", gold_growth_rate=0.0,
                              gold_per_carrier=2))
    assert env.income_for_turn(1) == 30          # 没有 turn_metrics → 0 载体
    env.turn_metrics = [{"carriers": 3}]
    assert env.income_for_turn(2) == 36          # 30 + 2×3
    env.turn_metrics = [{"carriers": 3}, {"carriers": 7}]
    assert env.income_for_turn(3) == 44          # 30 + 2×7


def test_gold_cap_and_scale():
    """``gold_cap``（默认 99）与 ``income_scale`` 的交互。"""
    ep = _run(_cfg(gold_mode="growth", gold_growth_rate=0.30))[0].episode_summary()
    assert max(ep["gold_start_hist"]) <= 99                       # 默认封顶
    ep2 = _run(_cfg(gold_mode="growth", gold_growth_rate=0.30, gold_cap=0))[0] \
        .episode_summary()
    assert max(ep2["gold_start_hist"]) > 99                       # 0 = 不封顶
    ep3 = _run(_cfg(gold_mode="fixed", income_scale=2.5))[0].episode_summary()
    assert ep3["gold_income_hist"] == [75] * 15


def test_validate_rejects_bad_gold_args():
    for kw in (dict(gold_mode="compound"), dict(gold_add=-1),
               dict(gold_growth_rate=-0.1), dict(gold_per_carrier=-1),
               dict(income_scale=-1.0), dict(gold_cap=-1)):
        with pytest.raises(ValueError):
            _cfg(**kw).validate()


# ── 1b. --gold-cap 语义（0 = 不封顶 / 99 = 默认硬顶 / 中间值）──────────────
# 契约见 docs/SANDBOX_ECON.md §3：**默认 99 不变**（逐位等价旧行为），
# 0 必须**显式**传（`--gold-cap 0`）才表示无上限。


def test_gold_cap_default_is_99_not_zero():
    """默认是 99（不是 0）：改默认会改变行为，所以 0 只能显式传。"""
    assert SandboxConfig().gold_cap == 99
    assert _cfg().gold_cap == 99


@pytest.mark.parametrize("cap", [0, 40, 99, 250])
@pytest.mark.parametrize("mode,kw", [
    ("fixed", {}),
    ("add", {"gold_add": 8}),
    ("growth", {"gold_growth_rate": 0.30}),
])
def test_gold_cap_clamps_injected_gold(cap, mode, kw):
    """三档收入 × {0=无上限, 40, 99, 250}：``gold_start`` 逐回合 = 注入项的封顶结果，
    ``0`` 表示不封顶（必须出现 > 99 的回合）。"""
    cfg = _cfg(gold_mode=mode, income_scale=4.0, gold_cap=cap, **kw)
    env, _ = _run(cfg)
    ep = env.episode_summary()
    injected = ep["gold_income_hist"]           # 不含引擎自然补币
    started = ep["gold_start_hist"]
    assert len(started) == 15
    for i, (n, got) in enumerate(zip(injected, started)):
        if mode == "fixed":
            # fixed **覆写**引擎收入：gold_start = clamp(cap, n)
            want = n if cap == 0 else min(cap, n)
        else:
            # add/growth **叠加**在引擎自然补币（3→10）之上
            want = NATURAL[i] + n if cap == 0 else min(cap, NATURAL[i] + n)
        assert got == want, f"{mode} cap={cap} t={i+1}: got {got}, want {want}"
    if cap == 0:
        assert max(started) > 99, f"cap=0 应不封顶，实际 max={max(started)}"
    else:
        assert max(started) <= cap


def test_gold_cap_zero_changes_behaviour_vs_default():
    """同一 seed：``gold_cap=0`` 的整局金币总和严格大于默认 99（证明 0 ≠ 默认）。"""
    base = dict(gold_mode="growth", gold_growth_rate=0.30, income_scale=3.0)
    ep99 = _run(_cfg(gold_cap=99, **base))[0].episode_summary()
    ep0 = _run(_cfg(gold_cap=0, **base))[0].episode_summary()
    assert ep0["gold_total_income"] > ep99["gold_total_income"]
    assert max(ep99["gold_start_hist"]) <= 99 < max(ep0["gold_start_hist"])


def test_gold_cap_zero_changes_behaviour_vs_default():
    """同一 seed：``gold_cap=0`` 的整局金币总和严格大于默认 99（证明 0 ≠ 默认）。"""
    base = dict(gold_mode="growth", gold_growth_rate=0.30, income_scale=3.0)
    ep99 = _run(_cfg(gold_cap=99, **base))[0].episode_summary()
    ep0 = _run(_cfg(gold_cap=0, **base))[0].episode_summary()
    assert ep0["gold_total_income"] > ep99["gold_total_income"]
    assert max(ep99["gold_start_hist"]) <= 99 < max(ep0["gold_start_hist"])


# ── 2. 默认逐位等价 ─────────────────────────────────────────────────────────


def test_default_equals_set_alias_and_zero_growth_is_add():
    """默认（fixed）与旧别名 ``set`` 逐位一致；``growth(rate=0, per_carrier=0)``
    与 ``add(gold_add=0)`` 逐位一致（两者都退化成「引擎收入 + 30」）。"""
    for seed in (0, 5):
        e1, a1 = _run(_cfg(), seed)
        e2, a2 = _run(_cfg(gold_mode="set"), seed)
        assert a1 == a2
        s1, s2 = e1.episode_summary(), e2.episode_summary()
        assert s1["sigma_by_turn"] == s2["sigma_by_turn"]
        assert s1["gold_income_hist"] == s2["gold_income_hist"] == [30] * 15

        e3, a3 = _run(_cfg(gold_mode="add", gold_add=0), seed)
        e4, a4 = _run(_cfg(gold_mode="growth", gold_growth_rate=0.0), seed)
        assert a3 == a4
        assert e3.episode_summary()["sigma_by_turn"] == \
            e4.episode_summary()["sigma_by_turn"]


# ── 3. 与饰品开关组合无冲突 ─────────────────────────────────────────────────


@pytest.mark.parametrize("trinkets", [None, True, False])
@pytest.mark.parametrize("mode,kw", [("fixed", {}), ("add", {"gold_add": 3}),
                                     ("growth", {"gold_growth_rate": 0.15})])
def test_gold_modes_with_trinket_switch(trinkets, mode, kw):
    """三档收入 × {默认/开/关}饰品：都能跑完、动作合法、饰品报价与金币互不影响。"""
    env, acts = _run(_cfg(gold_mode=mode, trinkets=trinkets, **kw), seed=2)
    ep = env.episode_summary()
    assert ep["turns"] == 15
    assert all(0 <= a < 245 for a in acts)
    if trinkets is False:
        assert ep["trinket_offers"] == 0
        assert ep["trinket_count"] == 0
    elif trinkets is True:
        assert ep["trinket_offers"] >= 1
    else:                                     # None = 引擎默认（不新增饰品键）
        assert "trinket_offers" not in ep
    # 金币口径不受饰品开关影响：
    if mode == "fixed":
        assert ep["gold_start_hist"] == [30] * 15      # 覆写：饰品回合开始收入被盖掉
    else:
        assert ep["gold_total_income"] > 450           # 保留：引擎收入 + 注入


# ── 4. Σ/金币 汇总口径 ─────────────────────────────────────────────────────


def test_summarize_reports_sigma_per_gold():
    eps = []
    for seed in (0, 1):
        env, _ = _run(_cfg(gold_mode="fixed"), seed=seed)
        ep = dict(env.episode_summary())
        ep["return"] = 0.0
        ep["decisions"] = 10
        eps.append(ep)
    rep = summarize(eps)
    assert rep["gold_total_income_p50"] == 450
    assert rep["sigma12_per_gold_p50"] == pytest.approx(
        float(np.percentile([e["sigma_t12"] / 450 for e in eps], 50)), abs=1e-9)
    assert rep["sigma15_per_gold_p50"] >= 0.0
