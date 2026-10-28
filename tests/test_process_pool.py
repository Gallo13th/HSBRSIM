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
    import queue as _queue
    with pytest.raises(_queue.Empty):
        pool._take_msg(0.05, want_worker=0)  # 没有消息 → 超时而不是死等


def test_reload_weights_survives_worker_kill(tmp_path, monkeypatch):
    """reload 期间 worker 死亡：重启后必须向新队列重发任务，不能等到超时。"""
    pytest.importorskip("torch")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")

    from hsbg.az.train.common import engine_available
    if not engine_available():
        pytest.skip("hsbg_engine 不可用")
    from hsbg.az.train.process_pool import ProcessActorPool

    ckpt = _tiny_ckpt(tmp_path)
    pool = ProcessActorPool(2, [0, 1], ckpt, arch="tiny", sims=0, determinizations=1,
                            seed=5, threads=1, batch_size=8, tmpdir=str(tmp_path / "p2"))
    try:
        victim = pool._procs[0]
        os.kill(victim.pid, signal.SIGKILL)
        for _ in range(100):
            if not victim.is_alive():
                break
            time.sleep(0.05)
        # 旧队列上的 reload 永远等不到 → 必须靠重启重发才能成功返回
        done = pool.reload_weights(ckpt, updates=1, timeout=120.0)
        assert done == 2
    finally:
        pool.close()


def test_reload_ignores_foreign_task_messages_without_livelock(tmp_path, monkeypatch):
    """外任务消息必须先留在缓冲、不能被本等待者反复弹出（否则活锁到超时）。"""
    pytest.importorskip("torch")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    from hsbg.az.train.process_pool import ProcessActorPool
    import queue as _q

    pool = ProcessActorPool.__new__(ProcessActorPool)
    pool._result_q = _q.Queue()
    pool._deferred = []
    pool._task_qs = [_q.Queue(), _q.Queue()]
    pool._info = [{"pid": 1}, {"pid": 2}]
    pool._procs = [None, None]
    pool._check_alive = lambda: None

    # 队列里先塞一条「别的任务」的消息，再塞本任务的 done
    pool._result_q.put({"worker": 1, "type": "collect_done", "task_id": "other"})
    # reload 会自己发任务；worker 侧按 task 号回 done
    import threading

    def fake_workers():
        for w, q in enumerate(pool._task_qs):
            task = q.get(timeout=5.0)
            pool._result_q.put({"worker": w, "type": "reload_done",
                                "task_id": task["task_id"]})

    th = threading.Thread(target=fake_workers, daemon=True)
    th.start()
    t0 = time.time()
    done = pool.reload_weights("ckpt.pt", updates=1, timeout=8.0)
    elapsed = time.time() - t0
    assert done == 2, done
    assert elapsed < 7.5, elapsed          # 没有活锁到超时
    # 外任务消息仍保留，可被它的等待者取到
    m = pool._take_msg(0.1, accept=lambda x: x.get("task_id") == "other")
    assert m["type"] == "collect_done"


def test_reload_detects_worker_death_after_ack(tmp_path, monkeypatch):
    """ack 后立刻死亡（无 queue.Empty 分支）：必须在收到后续消息时 resync 并重发。"""
    pytest.importorskip("torch")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    import queue as _q
    import threading

    from hsbg.az.train.process_pool import ProcessActorPool

    pool = ProcessActorPool.__new__(ProcessActorPool)
    pool._result_q = _q.Queue()
    pool._deferred = []
    pool._task_qs = [_q.Queue(), _q.Queue()]
    pool._info = [{"pid": 100}, {"pid": 200}]
    pool._procs = [None, None]

    state = {"w0_acks": 0}

    def fake_check_alive():
        # 模拟：worker0 在 ack 之后死亡并被重启（pid 变化）
        if state["w0_acks"] >= 1 and pool._info[0]["pid"] == 100:
            pool._info[0]["pid"] = 999
        return []

    pool._check_alive = fake_check_alive

    def worker(w, q):
        while True:
            task = q.get(timeout=5.0)
            if w == 0:
                state["w0_acks"] += 1
            pool._result_q.put({"worker": w, "type": "reload_done",
                                "task_id": task["task_id"]})
            if w == 1 and state["w0_acks"] >= 2:
                return

    ths = [threading.Thread(target=worker, args=(w, q), daemon=True)
           for w, q in enumerate(pool._task_qs)]
    [t.start() for t in ths]
    t0 = time.time()
    done = pool.reload_weights("ckpt.pt", updates=1, timeout=10.0)
    elapsed = time.time() - t0
    # worker0 收到两次任务（首次 ack 后死亡 → 重发 → 再 ack），最终成功数为 2
    assert state["w0_acks"] >= 2, state
    assert done == 2, done
    assert elapsed < 9.5, elapsed
