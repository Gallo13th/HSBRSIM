"""并行采集与串行采集的固定 seed 等价回归（需要引擎 + torch）。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS
from hsbg.az.train.model import build_net
from hsbg.az.train.parallel_collect import collect_ppo_batch_parallel
from hsbg.az.train.ppo import CollectConfig, collect_ppo_batch


def test_parallel_matches_serial_bot():
    pytest.importorskip("torch")
    pytest.importorskip("hsbg_engine")
    model = build_net(16)
    model.eval()
    cfg = CollectConfig(games=2, opponent="bot", behavior="net", seed=123,
                        max_actions_per_turn=40)
    b1, _ = collect_ppo_batch(model, cfg, device="cpu", seed=123, progress=False)
    b2, _ = collect_ppo_batch_parallel(model, cfg, workers=2, device="cpu",
                                       seed=123, progress=False)
    assert len(b1) == len(b2)
    # 同 seed/同局 => 动作、rank、old logprob、特征应逐位一致
    assert np.array_equal(b1.actions, b2.actions)
    assert np.array_equal(b1.ranks, b2.ranks)
    assert np.array_equal(b1.game_ids, b2.game_ids)
    assert np.allclose(b1.old_logprobs, b2.old_logprobs, atol=1e-6)
    assert np.allclose(b1.features, b2.features, atol=1e-5)
    assert np.allclose(b1.returns, b2.returns, atol=1e-6)
    assert np.all(b1.masks == b2.masks)
    assert b1.validate() == [] and b2.validate() == []


def test_lockstep_collects_legal_ranked_records():
    """lock-step：多局同步推进，记录带名次、动作合法、可构 batch（CPU tiny）。"""
    import numpy as np
    import hsbg_engine as E  # noqa: F401  (确保引擎可用)
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import CollectConfig, build_batch_from_records
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep

    model = build_net(arch="tiny")
    model.eval()
    server = BatchLeafServer(model, device="cpu", batch_size=32, max_wait_ms=1.0)
    try:
        cfg = CollectConfig(games=6, seed=5, opponent="bot", behavior="net",
                            max_steps=5000, lockstep=True, fast_act=True)
        records, meta = collect_ppo_lockstep(model, cfg, eval_fn=BatchPPOEvaluator(server),
                                             device="cpu", seed=5, games=6)
        assert meta["mode"] == "lockstep" and meta["games"] == 6
        assert meta["decisions"] == len(records) > 0
        assert meta["illegal_actions"] == 0
        assert all(1 <= int(r["rank"]) <= 8 for r in records)
        assert all(bool(r["mask"][int(r["action"])]) for r in records)
        batch = build_batch_from_records(records, gamma=1.0, lam=0.995)
        assert len(batch.actions) == len(records)
        assert np.isfinite(batch.advantages).all()
    finally:
        server.close()
