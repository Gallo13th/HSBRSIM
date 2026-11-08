"""小模型专家 → 大模型蒸馏的单元测试。

覆盖三件事（不需要 GPU / 不需要真实 checkpoint）：

1. ``_topk_union``：候选 = 大小模型 top-k 并集、剔除 Move 段、按大模型先验降序；
2. ``make_samples``：教师分布来自小模型、先验来自大模型、样本字段与 ``SearchSample``
   契约一致（p_s/p_base 归一、teacher/base/switch 正确）；
3. ``paired_stats``：配对 Δ 与 bootstrap CI 的符号/区间自洽。
"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.sandbox_rollout import MOVE_HI, MOVE_LO
from hsbg.az.train.small_expert_distill import (DistillConfig, _topk_union,
                                                make_samples, paired_stats)


class _FakeEval:
    """固定 logits 的“网络”：``logits(f,c,m) -> (logits, zeros)``。"""

    def __init__(self, logits: np.ndarray) -> None:
        self.base = np.asarray(logits, dtype=np.float32)

    def logits(self, feats, cards=None, mask=None):
        m = np.atleast_2d(np.asarray(mask, dtype=bool))
        lg = np.tile(self.base, (m.shape[0], 1)).astype(np.float32)
        lg[~m] = -1e9
        return lg, np.zeros((m.shape[0], 8), dtype=np.float32)


def _record(feats: np.ndarray, mask: np.ndarray, turn: int = 3) -> dict:
    return {"features": feats, "cards": np.zeros(124, dtype=np.int32),
            "mask": mask, "turn": turn, "seat": 0, "game_id": 7}


def test_topk_union_excludes_move_and_orders_by_big():
    mask = np.zeros(245, dtype=bool)
    legal = [0, 5, 6, MOVE_LO, MOVE_LO + 3]
    mask[legal] = True
    pi_big = np.zeros(245)
    pi_small = np.zeros(245)
    pi_big[[5, 6]] = [0.6, 0.3]
    pi_small[[0, 6, MOVE_LO + 3]] = [0.5, 0.2, 0.2]
    cands = _topk_union(pi_big, pi_small, mask, 3)
    assert int(MOVE_LO) not in cands.tolist()
    assert int(MOVE_LO + 3) not in cands.tolist()
    # 大模型先验最高（5）在最前；并集包含小模型 top-1（0）与大模型 top-2（6）
    assert cands[0] == 5
    assert set(cands.tolist()) == {0, 5, 6}


def test_make_samples_contract():
    mask = np.zeros(245, dtype=bool)
    mask[[0, 3, 4]] = True
    feats = np.zeros(3227, dtype=np.float32)
    rec = _record(feats, mask)
    lg_big = np.full(245, -1e9, dtype=np.float32)
    lg_big[[0, 3, 4]] = [0.1, 2.0, 0.0]      # 大模型偏好 3
    lg_small = np.full(245, -1e9, dtype=np.float32)
    lg_small[[0, 3, 4]] = [3.0, 0.0, 0.5]    # 小专家偏好 0
    samples, stats = make_samples([rec], _FakeEval(lg_big), _FakeEval(lg_small),
                                  DistillConfig(topk=2))
    assert stats["n_states"] == 1 and stats["n_records"] == 1
    s = samples[0]
    assert s.base == 3 and s.teacher == 0 and s.switch is True
    assert abs(float(np.sum(s.p_s)) - 1.0) < 1e-6
    assert abs(float(np.sum(s.p_base)) - 1.0) < 1e-6
    # 教师概率最大值在动作 0；先验最大值在动作 3
    assert int(s.cands[int(np.argmax(s.p_s))]) == 0
    assert int(s.cands[int(np.argmax(s.p_base))]) == 3
    assert s.f.shape == (3227,) and s.c.shape == (124,) and s.mask.shape == (245,)
    assert s.q.shape == s.cands.shape and np.all(s.q == 0.0)


def test_make_samples_key_filter_and_degenerate_mask():
    mask = np.zeros(245, dtype=bool)
    mask[[0]] = True                          # 只有 1 个合法动作 -> 丢弃
    rec = _record(np.zeros(3227, dtype=np.float32), mask)
    samples, stats = make_samples([rec], _FakeEval(np.zeros(245)),
                                  _FakeEval(np.zeros(245)), DistillConfig())
    assert samples == [] and stats["n_bad"] == 1


def test_paired_stats_sign_and_ci():
    before = [6] * 100
    after = [5] * 100
    st = paired_stats(after, before, n_boot=2000, seed=0)
    assert st["n"] == 100 and st["mean"] == pytest.approx(-1.0)
    assert st["ci_low"] <= st["mean"] <= st["ci_high"]
    # 全负且无方差：CI 就是点估计（判定「上界 < 0」）
    assert st["ci_high"] == pytest.approx(-1.0)
    mix = paired_stats([6] * 50 + [4] * 50, [6] * 100, n_boot=2000, seed=0)
    assert mix["mean"] == pytest.approx(-1.0)
    assert mix["frac_improved"] == pytest.approx(0.5)
