"""ProcessActorPool 可靠性：worker 崩溃后自愈（故障注入）。

在 CPU 上跑（测试内隐藏 GPU），不依赖 CUDA。
"""

from __future__ import annotations

import os
import signal
import time

import numpy as np
import pytest


def _tiny_ckpt(tmp_path):
    from hsbg.az.train.model import build_net, save_checkpoint
    model = build_net(arch="tiny")
    path = str(tmp_path / "tiny.pt")
    save_checkpoint(model, path, meta={"arch": "tiny"})
    return path


def test_pool_collects_and_restarts_after_kill(tmp_path, monkeypatch):
    """杀掉一个 actor 进程后，下一次 collect 必须能自愈并成功返回批次。"""
    pytest.importorskip("torch")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")  # 强制 CPU，避免占卡

    from hsbg.az.train.common import engine_available
    if not engine_available():
        pytest.skip("hsbg_engine 不可用")

    from hsbg.az.train.ppo import CollectConfig
    from hsbg.az.train.process_pool import ProcessActorPool

    ckpt = _tiny_ckpt(tmp_path)
    pool = ProcessActorPool(
        2, [0, 1], ckpt, arch="tiny", sims=0, determinizations=1,
        seed=3, threads=1, batch_size=16,
        tmpdir=str(tmp_path / "proc"))
    try:
        cfg = CollectConfig(games=2, seed=3, opponent="bot", behavior="net",
                            max_steps=3000, fast_act=True, lockstep=True)
        batch, meta = pool.collect(cfg, 2, gamma=1.0, lam=0.995,
                                   seed=3, weights_version=0, weights_path=ckpt)
        assert len(batch.actions) > 0 and meta["decisions"] > 0
        assert meta["restarts"] == 0

        # 故障注入：杀掉第一个 worker，等它彻底退出
        victim = pool._procs[0]
        os.kill(victim.pid, signal.SIGKILL)
        for _ in range(100):
            if not victim.is_alive():
                break
            time.sleep(0.05)
        assert not victim.is_alive()

        # 第二次 collect：应检测死亡、重启、并成功返回
        batch2, meta2 = pool.collect(cfg, 2, gamma=1.0, lam=0.995,
                                     seed=4, weights_version=0, weights_path=ckpt)
        assert len(batch2.actions) > 0
        assert meta2["restarts"] >= 1
        assert np.isfinite(np.asarray(batch2.advantages, dtype=np.float64)).all()
    finally:
        pool.close()


def test_take_msg_defers_stray_messages_without_starvation(tmp_path, monkeypatch):
    """竞态回归：别的 worker 的消息被暂存后，等待者不能把它取回来忙等。

    构造两个 worker 的消息交错：等待 worker0 时先读到 worker1 的两条消息，
    必须仍能在超时前拿到 worker0 的 ready，且 worker1 的消息保留在缓冲里、
    之后能被 want_worker=1 的等待者取到（不丢、不饿死）。
    """
    pytest.importorskip("torch")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")

    from hsbg.az.train.process_pool import ProcessActorPool

    pool = ProcessActorPool.__new__(ProcessActorPool)   # 不启动进程，只测消息分发
    import queue as _q
    pool.ctx = None
    pool._result_q = _q.Queue()
    pool._deferred = []

    pool._result_q.put({"worker": 1, "type": "collect_done", "task_id": "a"})
    pool._result_q.put({"worker": 1, "type": "weights_loaded"})
    pool._result_q.put({"worker": 0, "type": "ready", "gpu": 0, "pid": 1})

    m0 = pool._take_msg(2.0, want_worker=0)
    assert m0["type"] == "ready" and m0["worker"] == 0
    assert len(pool._deferred) == 2          # worker1 的两条被暂存
    m1 = pool._take_msg(0.1, want_worker=1)  # 从缓冲里按 worker 取
    assert m1["type"] == "collect_done"
    m2 = pool._take_msg(0.1)                 # 不限 worker：取剩余
    assert m2["type"] == "weights_loaded"
    assert pool._deferred == []
    with pytest.raises(Exception):
        pool._take_msg(0.05, want_worker=0)  # 没有消息 → 超时而不是死等
