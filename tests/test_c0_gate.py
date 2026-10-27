"""C0 gate 统计/判定单测（无引擎依赖）。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.eval.c0 import (C0GateConfig, bootstrap_ci, evaluate_gate,
                          paired_diffs)


def test_paired_diffs_drops_truncated():
    d, missing = paired_diffs([1, 2, 0, 5], [3, 2, 4, 4])
    assert missing == 1
    assert list(d) == [-2, 0, 1]


def test_paired_diffs_length_mismatch():
    with pytest.raises(ValueError):
        paired_diffs([1, 2], [1])


def test_bootstrap_ci_negative():
    diffs = [-1.0] * 50 + [0.0] * 50
    lo, hi = bootstrap_ci(diffs, n_boot=1000, seed=0)
    assert lo <= -0.5 <= hi < 0.0


def test_gate_passes_on_significant_improvement():
    rng = np.random.default_rng(0)
    model = rng.integers(1, 9, size=512).tolist()
    bot = (rng.integers(1, 9, size=512) + 1).clip(1, 8).tolist()
    # 强制模型更好
    model = [max(1, b - 1) for b in bot]
    res = evaluate_gate(model, bot, config=C0GateConfig(games=512, bootstrap=500))
    assert res.mean_diff < 0
    assert res.ci_high < 0
    assert res.passed


def test_gate_fails_on_truncation_or_no_improvement():
    model = [8] * 512
    bot = [4] * 512
    res = evaluate_gate(model, bot, config=C0GateConfig(games=512, bootstrap=500),
                        truncated=1)
    assert not res.passed
    assert any("CI" in r for r in res.reasons)
    assert any("truncated" in r for r in res.reasons)


def test_gate_fails_on_wrong_sample_count():
    model = [4] * 10
    bot = [5] * 10
    res = evaluate_gate(model, bot, config=C0GateConfig(games=512, bootstrap=100))
    assert not res.passed
    assert any("有效配对局数" in r for r in res.reasons)


def test_gate_rejects_out_of_range_rank():
    model = [4] * 512
    model[0] = 99
    bot = [5] * 512
    res = evaluate_gate(model, bot, config=C0GateConfig(games=512, bootstrap=100))
    assert not res.passed
    assert any("越界" in r for r in res.reasons)


def test_gate_rejects_non_integer_rank():
    model = [4.5] * 512
    bot = [5] * 512
    res = evaluate_gate(model, bot, config=C0GateConfig(games=512, bootstrap=100))
    assert not res.passed
    assert any("整数" in r for r in res.reasons)


def test_gate_rejects_missing_pair():
    model = [4] * 512
    bot = [5] * 512
    model[0] = 0
    res = evaluate_gate(model, bot, config=C0GateConfig(games=512, bootstrap=100))
    assert not res.passed
    assert any("截断" in r or "有效配对" in r for r in res.reasons)


def test_gate_rejects_truncated_combats():
    model = [4] * 512
    bot = [5] * 512
    res = evaluate_gate(model, bot, config=C0GateConfig(games=512, bootstrap=100),
                        truncated_combats=1)
    assert not res.passed
    assert any("truncated_combats" in r for r in res.reasons)


def test_smoke_mode_can_skip_protocol():
    res = evaluate_gate([4] * 8, [5] * 8,
                        config=C0GateConfig(games=8, seats=8, bootstrap=100,
                                            require_protocol=False))
    assert res.passed
