"""截断局不得被当作终局写 value target（CPU / numpy-only，不依赖 GPU 与引擎）。

背景（``docs/BUG_AUDIT_SOL.md`` §5.4）：``max_steps`` 用尽 / 引擎未结束的对局是
**truncated**，其记录 rank=0。两条构建路径都必须把它们丢掉，不能：
1. 把 truncation 当 ``done``（会让 GAE 在截断处 bootstrap 失败/提前截断优势）；
2. 把 rank=0 的终局效用当成 ``u(0)``/``u(1)`` 写进 reward（会污染价值目标）。

覆盖：
- ``build_batch_from_records``（dict 记录路径，单进程采集）；
- ``build_batch_from_arrays``（SoA 路径，进程池/worker 的 packed 记录）。

两路径对同一批记录应给出**逐位一致**的 rewards/advantages/returns。
"""

from __future__ import annotations

import numpy as np

from hsbg.az.train.common import (
    N_ACTIONS,
    OBS_CARDS,
    OBS_FLOATS,
    utility_from_rank,
)
from hsbg.az.train.ppo import build_batch_from_arrays, build_batch_from_records

GAMMA = 1.0
LAM = 0.95


def _rec(game_id: int, seat: int, rank: int, turn: int, action: int = 0):
    """最小决策记录：零特征、全合法掩码；value=0 便于手算 GAE。"""
    return {
        "features": np.zeros(OBS_FLOATS, dtype=np.float32),
        "cards": np.zeros(OBS_CARDS, dtype=np.int16),
        "mask": np.ones(N_ACTIONS, dtype=bool),
        "action": int(action),
        "old_logprob": -np.log(N_ACTIONS),
        "value": 0.0,
        "rank": int(rank),
        "seat": int(seat),
        "game_id": int(game_id),
        "turn": int(turn),
    }


def _records():
    """1 局完整（rank=3，3 步）+ 1 局截断（rank=0，2 步）。"""
    return [
        _rec(0, 0, 3, 1), _rec(0, 0, 3, 2), _rec(0, 0, 3, 3),
        _rec(1, 0, 0, 1), _rec(1, 0, 0, 2),
    ]


#: dict 记录字段 -> SoA/packed 字段（``build_batch_from_arrays`` 的口径）
_REC2ARR = {
    "features": "features", "cards": "cards", "mask": "masks",
    "action": "actions", "old_logprob": "old_logprobs", "value": "values",
    "seat": "seats", "game_id": "game_ids", "rank": "ranks", "turn": "turns",
}


def _as_arrays(records):
    out = {}
    for rkey, akey in _REC2ARR.items():
        out[akey] = np.stack([np.asarray(r[rkey]) for r in records]).copy()
    out["forced"] = np.zeros(len(records), dtype=bool)
    return out


def test_truncated_records_are_dropped_not_treated_as_terminal():
    batch = build_batch_from_records(_records(), gamma=GAMMA, lam=LAM)
    u3 = float(utility_from_rank([3])[0])

    assert len(batch) == 3, "截断局的 2 条记录必须被丢弃"
    assert int(batch.meta.get("dropped_unknown_rank", -1)) == 2
    assert int(batch.meta.get("episodes", -1)) == 1

    # 每个 episode 恰好一个 done，且在末步（截断局不得贡献 done）
    assert float(np.asarray(batch.dones).sum()) == 1.0
    assert float(np.asarray(batch.dones)[-1]) == 1.0
    assert (np.asarray(batch.ranks) == 3).all()

    # 终局 reward 只能是 u(rank=3)，不是 u(0)/u(1)
    ret = np.asarray(batch.returns, dtype=np.float64)
    np.testing.assert_allclose(ret[-1], u3, atol=1e-6)
    # 非终局的递推：V=0、无中间 reward ⇒ ret[t] = (γλ)^(T-1-t) · u3
    np.testing.assert_allclose(ret[0], (GAMMA * LAM) ** 2 * u3, atol=1e-6)
    np.testing.assert_allclose(ret[1], (GAMMA * LAM) * u3, atol=1e-6)


def test_soa_path_matches_records_path_and_also_drops_truncated():
    records = _records()
    arr = _as_arrays(records)

    b_rec = build_batch_from_records(records, gamma=GAMMA, lam=LAM)
    b_arr = build_batch_from_arrays(arr, gamma=GAMMA, lam=LAM)

    assert len(b_arr) == len(b_rec) == 3
    assert int(b_arr.meta.get("dropped_unknown_rank", -1)) == 2
    assert int(b_arr.meta.get("episodes", -1)) == 1

    for name in ("features", "cards", "masks", "actions", "seats", "game_ids",
                 "ranks", "turns", "dones", "rewards", "advantages", "returns"):
        a = np.asarray(getattr(b_arr, name), dtype=np.float64)
        b = np.asarray(getattr(b_rec, name), dtype=np.float64)
        np.testing.assert_allclose(a, b, atol=1e-6, err_msg=f"字段 {name} 两路径不一致")

    # 截断局被丢弃后，GAE 不应在批内出现第二个 done
    assert float(np.asarray(b_arr.dones).sum()) == 1.0
