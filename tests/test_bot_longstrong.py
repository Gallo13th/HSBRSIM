"""「长且强 bot 局」子集指标单测（hsbg.eval.metrics.long_strong_subset）。

口径（docs/WEIGHTED_EVAL.md / B03_DESIGN.md §5.1）：turns 与 bot 终局强度的平均秩
百分位**都** >= quantile（默认 0.75）的对局组成子集，再看模型在这些局里的
rank/top4/win。纯函数，不依赖引擎。
"""

from __future__ import annotations

from hsbg.eval.metrics import long_strong_subset, weighted_eval_summary


def test_subset_takes_top_quartile_on_both_axes():
    turns = [3, 5, 8, 10, 12, 15, 16, 18]
    strengths = [100, 200, 300, 400, 500, 600, 700, 800]
    ranks = [1, 2, 3, 4, 5, 6, 7, 8]
    out = long_strong_subset(ranks, turns, strengths)
    # 8 局时 u=r/7；u>=0.75 与 v>=0.75 同时成立的只有最后两局。
    assert out["n"] == 2
    assert out["games"] == [6, 7]
    assert out["quantile"] == 0.75
    assert abs(out["mean_rank"] - 7.5) < 1e-9
    assert out["top4"] == 0.0
    assert out["win"] == 0.0
    assert out["thresholds"]["turns_min"] == 16.0
    assert out["thresholds"]["strength_min"] == 700.0


def test_long_but_weak_or_strong_but_short_excluded():
    # 前两局长但弱，后两局强但短：没有一局同时进两个前 25%。
    turns = [20, 19, 2, 1]
    strengths = [10, 20, 900, 800]
    out = long_strong_subset([1, 2, 3, 4], turns, strengths)
    assert out["n"] == 0
    assert out["games"] == []
    assert out["mean_rank"] is None
    assert out["top4"] is None
    assert out["win"] is None
    assert out["thresholds"] is None


def test_custom_quantile_widens_subset():
    turns = [10, 20, 30, 40]
    strengths = [1, 2, 3, 4]
    q75 = long_strong_subset([1, 2, 3, 4], turns, strengths, quantile=0.75)
    q50 = long_strong_subset([1, 2, 3, 4], turns, strengths, quantile=0.5)
    assert q75["n"] == 1          # 只有最后一局（40, 4）
    assert q50["n"] == 2          # 后两局都 >= 中位
    assert q75["n"] < q50["n"]


def test_empty_and_mismatched_inputs_are_safe():
    assert long_strong_subset([], [], [])["n"] == 0
    out = long_strong_subset([1, 2], [1.0, 2.0], [10.0])  # 长度不一致
    assert out["n"] == 0
    assert out["mean_rank"] is None


def test_weighted_summary_still_available():
    """同一 cohort 上加权指标与子集指标可以同时算（质量面板二者并联）。"""
    ranks = [1, 2, 3, 4, 5, 6, 7, 8]
    turns = [8, 9, 10, 11, 12, 13, 14, 15]
    strengths = [100, 150, 200, 250, 300, 350, 400, 450]
    w = weighted_eval_summary(ranks, turns, strengths)
    ls = long_strong_subset(ranks, turns, strengths)
    assert w["n"] == 8
    assert w["weighted"]["mean_rank"] > 1.0
    assert ls["n"] == 2
    assert ls["mean_rank"] == 7.5
