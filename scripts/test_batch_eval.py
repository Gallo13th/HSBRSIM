"""BatchLeafServer 单测（torch，不需要引擎）。"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.model import build_net
from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
from hsbg.az.train.ppo import PPOEvaluator


def _needs_torch():
    return pytest.importorskip("torch")


def _sample(rng, n=4):
    f = rng.normal(size=(n, OBS_FLOATS)).astype(np.float32)
    c = np.zeros((n, OBS_CARDS), dtype=np.int64)
    m = np.zeros((n, N_ACTIONS), dtype=bool)
    for i in range(n):
        legal = rng.choice(N_ACTIONS, size=5, replace=False)
        m[i, legal] = True
    return f, c, m


def test_batch_server_matches_direct():
    _needs_torch()
    rng = np.random.default_rng(0)
    model = build_net(16)
    direct = PPOEvaluator(model, device="cpu")
    server = BatchLeafServer(model, device="cpu", batch_size=8, max_wait_ms=20)
    try:
        f, c, m = _sample(rng)
        for i in range(len(f)):
            p_ref, v_ref = direct(f[i], c[i], m[i])
            p, v = server.call(f[i], c[i], m[i])
            assert np.allclose(p, p_ref, atol=1e-6)
            assert abs(v - v_ref) < 1e-6
            assert float(p.sum()) == pytest.approx(1.0, abs=1e-6)
            assert np.all(p[~m[i]] == 0.0)
        assert server.stats["requests"] == 4
        assert server.stats["leafs"] == 4
    finally:
        server.close()


def test_batch_server_concurrent_forms_batches():
    _needs_torch()
    rng = np.random.default_rng(1)
    model = build_net(16)
    server = BatchLeafServer(model, device="cpu", batch_size=16, max_wait_ms=30)
    f, c, m = _sample(rng, n=32)
    out = [None] * len(f)
    errors = []

    def work(i):
        try:
            out[i] = server.call(f[i], c[i], m[i], timeout=10)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        threads = [threading.Thread(target=work, args=(i,)) for i in range(len(f))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert all(x is not None for x in out)
        assert server.stats["leafs"] == len(f)
        assert server.stats["batches"] <= len(f)
        assert server.stats["max_batch"] >= 2
        evaluator = BatchPPOEvaluator(server)
        p, v = evaluator(f[0], c[0], m[0])
        assert p.shape == (N_ACTIONS,)
        assert np.isfinite(v)
    finally:
        server.close()


def test_batch_server_close_rejects_and_fails_pending():
    _needs_torch()
    model = build_net(16)
    server = BatchLeafServer(model, device="cpu", batch_size=8, max_wait_ms=20)
    rng = np.random.default_rng(2)
    f, c, m = _sample(rng, n=4)
    server.close()
    with pytest.raises(RuntimeError):
        server.submit(f[0], c[0], m[0])
    with pytest.raises(RuntimeError):
        server.call(f[0], c[0], m[0])
    server.close()  # idempotent


def test_act_is_deterministic_and_legal(_tiny_model_factory=None):
    """worker 侧采样：同 seed → 同动作；动作合法；logprob 与 prior 一致。"""
    import numpy as np
    from hsbg.az.train.batch_eval import BatchLeafServer
    from hsbg.az.train.model import build_net

    model = build_net(arch="tiny")
    server = BatchLeafServer(model, device="cpu", batch_size=8, max_wait_ms=1.0)
    try:
        rng = np.random.default_rng(0)
        f = rng.normal(size=(3227,)).astype(np.float32)
        c = np.zeros(124, dtype=np.int64)
        m = np.zeros(245, dtype=bool)
        m[rng.integers(0, 245, 8)] = True
        m[0] = True
        a1, lp1, v1 = server.act(f, c, m, 1.0, seed=123)
        a2, lp2, v2 = server.act(f, c, m, 1.0, seed=123)
        a3, _, _ = server.act(f, c, m, 1.0, seed=124)
        assert a1 == a2 and abs(lp1 - lp2) < 1e-9 and abs(v1 - v2) < 1e-9
        assert bool(m[a1]) and bool(m[a3])
        prior, value = server.call(f, c, m)
        assert abs(float(np.log(max(prior[a1], 1e-12))) - lp1) < 1e-5
        assert abs(float(value) - float(v1)) < 1e-5
    finally:
        server.close()
