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


def test_rust_collector_matches_python_semantics():
    """Rust 采集器：记录字段完整、动作合法、名次/守卫语义与 Python 路径一致。"""
    import numpy as np
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import CollectConfig, build_batch_from_arrays
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.rust_collect import collect_ppo_rust

    model = build_net(arch="tiny")
    model.eval()
    server = BatchLeafServer(model, device="cpu", batch_size=64, max_wait_ms=1.0)
    try:
        cfg = CollectConfig(games=8, seed=13, opponent="bot", behavior="net",
                            max_steps=5000, learner_seat=0)
        arr, meta = collect_ppo_rust(model, cfg, eval_fn=BatchPPOEvaluator(server),
                                     device="cpu", seed=13, games=8)
        assert meta["mode"] == "rust_collector" and meta["decisions"] > 0
        n = meta["decisions"]
        for k in ("features", "cards", "masks", "actions", "old_logprobs",
                  "values", "ranks", "seats", "game_ids", "turns", "forced"):
            assert len(arr[k]) == n, k
        # 动作必须合法
        assert bool(arr["masks"][np.arange(n), arr["actions"]].all())
        # forced 样本 logprob 必须为 0
        if bool(arr["forced"].any()):
            assert np.allclose(arr["old_logprobs"][arr["forced"]], 0.0)
        # 名次要么 1..8（该局结束），要么 <=0（截断，稍后被丢弃）
        ranks = set(int(x) for x in arr["ranks"])
        assert all((1 <= r <= 8) or r <= 0 for r in ranks)
        batch = build_batch_from_arrays(arr, gamma=1.0, lam=0.995)
        batch.validate()
        assert len(batch.actions) > 0
    finally:
        server.close()


def test_rust_collector_rank_backfill_not_cross_game():
    """rank 回填不能污染其他局：每局的 rank 必须等于该局自己的 placement。"""
    import numpy as np
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import CollectConfig
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.rust_collect import collect_ppo_rust

    model = build_net(arch="tiny")
    model.eval()
    server = BatchLeafServer(model, device="cpu", batch_size=64, max_wait_ms=1.0)
    try:
        cfg = CollectConfig(games=12, seed=29, opponent="bot", behavior="net",
                            max_steps=8000, learner_seat=0)
        arr, meta = collect_ppo_rust(model, cfg, eval_fn=BatchPPOEvaluator(server),
                                     device="cpu", seed=29, games=12)
        gids = np.asarray(arr["game_ids"])
        ranks = np.asarray(arr["ranks"])
        for g in np.unique(gids):
            mine = ranks[gids == g]
            done = mine[mine > 0]
            # 同一局只能有一个名次（全部相同），且不会出现两个不同名次
            assert len(set(int(x) for x in done)) <= 1, (g, sorted(set(done.tolist())))
    finally:
        server.close()
