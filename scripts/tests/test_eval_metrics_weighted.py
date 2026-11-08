"""加权对局指标（对局长度 + 对局强度）纯函数测试。"""

from __future__ import annotations

import pytest

from hsbg.eval.metrics import (
    effective_sample_size,
    game_weights,
    percentile_ranks,
    weighted_eval_summary,
    weighted_mean,
)


def test_percentile_ranks_monotone_and_ties():
    p = percentile_ranks([10, 20, 20, 40])
    assert p[0] == 0.0
    assert p[3] == 1.0
    assert p[1] == p[2]  # 并列
    assert 0.0 < p[1] < 1.0


def test_percentile_ranks_single():
    assert percentile_ranks([7]) == [0.0]
    assert percentile_ranks([]) == []


def test_game_weights_mean_one_and_prefers_long_strong():
    turns = [8, 12, 16]
    strengths = [100, 200, 300]
    w = game_weights(turns, strengths)
    assert len(w) == 3
    assert abs(sum(w) / len(w) - 1.0) < 1e-9
    assert w[2] > w[1] > w[0]
    # floor/cap 是软边界：先归一化再 clip 再归一化，允许 ~0.05 的越界
    assert all(0.45 <= x <= 2.05 for x in w)


def test_game_weights_length_mismatch():
    with pytest.raises(ValueError):
        game_weights([1, 2], [1])


def test_weighted_mean_basic():
    assert weighted_mean([1, 3], [1, 1]) == 2.0
    assert weighted_mean([1, 3], [3, 1]) == 1.5
    assert weighted_mean([], []) != weighted_mean([], [])  # nan


def test_effective_sample_size():
    assert effective_sample_size([1, 1, 1, 1]) == 4.0
    assert effective_sample_size([2, 0, 0, 0]) == 1.0


def test_weighted_eval_summary_fields_and_direction():
    ranks = [1, 4, 8, 2]
    turns = [18, 10, 7, 15]
    strengths = [900, 400, 100, 700]
    out = weighted_eval_summary(ranks, turns, strengths)
    assert out["n"] == 4
    assert abs(sum(out["weights"]) / 4 - 1.0) < 1e-6
    assert out["unweighted"]["mean_rank"] == pytest.approx(3.75)
    # 长且强的局（rank1, turns18, strength900）权重大 -> 加权 rank 应低于 3.75
    assert out["weighted"]["mean_rank"] < out["unweighted"]["mean_rank"]
    assert out["n_eff"] > 0
