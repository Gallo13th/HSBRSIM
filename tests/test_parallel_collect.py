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
