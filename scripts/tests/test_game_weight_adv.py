"""长强局 per-episode 加权（--game-weight-mode）单测。

判据：
1. ``mode="none"`` 与不传新字段的旧路径 **逐位一致**（advantage 相同、meta 不含 game_weight）。
2. ``mode="adv"`` 时每局 advantage 被整体乘以 ``game_weights`` 给出的权重（均值归一 1）。
3. records 路径与 pack→arrays 路径结果一致（训练实际走 arrays 路径）。
"""
from __future__ import annotations

import numpy as np

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.ppo import (build_batch_from_arrays, build_batch_from_records,
                               pack_records_arrays)
from hsbg.eval.metrics import game_weights


def _rec(game_id: int, seat: int, turn: int, rank: int, gs: float) -> dict:
    f = np.zeros(OBS_FLOATS, dtype=np.float32)
    f[0] = float(turn) / 20.0
    m = np.zeros(N_ACTIONS, dtype=bool)
    m[0] = True
    return {
        "features": f,
        "cards": np.zeros(OBS_CARDS, dtype=np.int16),
        "mask": m,
        "action": 0,
        "old_logprob": -0.7,
        "value": 0.0,
        "rank": int(rank),
        "seat": int(seat),
        "game_id": int(game_id),
        "turn": int(turn),
        "game_bot_strength": float(gs),
    }


def _records() -> list:
    recs = []
    # 局 A：长（20 决策）且对手强（5000）
    for t in range(1, 21):
        recs.append(_rec(1, 0, t, 1, 5000.0))
    # 局 B：短（5 决策）且对手弱（100）
    for t in range(1, 6):
        recs.append(_rec(2, 0, t, 8, 100.0))
    return recs


def test_mode_none_is_bit_identical() -> None:
    recs = _records()
    base = build_batch_from_records(recs)
    off = build_batch_from_records(recs, game_weight_mode="none")
    assert np.array_equal(base.advantages, off.advantages)
    assert np.array_equal(base.returns, off.returns)
    assert "game_weight" not in off.meta


def test_adv_mode_scales_by_expected_ratio() -> None:
    recs = _records()
    base = build_batch_from_records(recs, game_weight_mode="none")
    wgt = build_batch_from_records(recs, game_weight_mode="adv")
    w = game_weights([20.0, 5.0], [5000.0, 100.0],
                     alpha=0.5, beta=0.5, floor=0.5, cap=2.0)
    assert np.allclose(wgt.advantages[:20], base.advantages[:20] * w[0], atol=1e-6)
    assert np.allclose(wgt.advantages[20:], base.advantages[20:] * w[1], atol=1e-6)
    stats = wgt.meta["game_weight"]
    assert stats["n_episodes"] == 2
    assert stats["w_mean"] > 0.0
    assert stats["strength_all_zero"] is False


def test_arrays_path_matches_records_path() -> None:
    recs = _records()
    rec = build_batch_from_records(recs, game_weight_mode="adv")
    arr = build_batch_from_arrays(pack_records_arrays(recs), game_weight_mode="adv")
    assert np.allclose(rec.advantages, arr.advantages, atol=1e-6)
    assert arr.meta["game_weight"]["n_episodes"] == 2


def test_missing_strength_degrades_to_length_only() -> None:
    recs = _records()
    for r in recs:
        r.pop("game_bot_strength", None)
    b = build_batch_from_records(recs, game_weight_mode="adv")
    assert b.meta["game_weight"]["strength_all_zero"] is True
    # 仍应按长度区分（长局权重更高）
    assert float(np.abs(b.advantages[:20]).mean()) > float(np.abs(b.advantages[20:]).mean())
