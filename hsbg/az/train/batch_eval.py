"""批量叶推理服务（P0 吞吐组件）。

`PPOEvaluator.__call__` 是逐叶同步前向；MCTS/策略在多个线程里调用时无法形成 batch。
本模块提供 `BatchLeafServer`：

- 多个调用线程 `submit()` 叶请求，后台单 worker 收集到 B 或等待 max_wait_ms 后
  **一次 GPU 前向**；
- 返回与 `PPOEvaluator.__call__` 相同的 `(prior[245], value)`；
- 记录 requests/batches/mean_batch/leafs，供 profiling；
- `BatchPPOEvaluator` 可直接替换 `PPOEvaluator` 传给现有策略/MCTS。

限制（必须在报告中说明）：它解决“推理 batch”，不自动让 Rust 逐叶回调变成批回调；
真正端到端 actor 仍需多局/多树并发提交。当前 P0 先做可测的 batch server + benchmark。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .common import OBS_CARDS
from .ppo import (PPOEvaluator, masked_probs_np, value_from_rank_logits_np)


@dataclass
class LeafRequest:
    rid: int
    features: np.ndarray
    cards: np.ndarray
    mask: np.ndarray
    event: threading.Event = field(default_factory=threading.Event)
    prior: Optional[np.ndarray] = None
    value: Optional[float] = None
    error: Optional[BaseException] = None


class BatchLeafServer:
    """后台批量叶评估器；线程安全 submit。"""

    def __init__(self, model: Any, device: str = "cpu", *,
                 batch_size: int = 64, max_wait_ms: float = 2.0,
                 temperature: float = 1.0,
                 norm_mean: Optional[np.ndarray] = None,
                 norm_std: Optional[np.ndarray] = None,
                 queue_size: int = 4096) -> None:
        self.evaluator = PPOEvaluator(model, device=device, temperature=temperature,
                                      norm_mean=norm_mean, norm_std=norm_std)
        self.batch_size = max(1, int(batch_size))
        self.max_wait_s = max(0.0, float(max_wait_ms) / 1000.0)
        self.temperature = float(temperature)
        self._q: "queue.Queue[LeafRequest]" = queue.Queue(maxsize=int(queue_size))
        self._stop = threading.Event()
        self._state = "open"  # open | closing | closed
        self._state_lock = threading.Lock()
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self.stats: Dict[str, Any] = {
            "requests": 0, "batches": 0, "leafs": 0, "max_batch": 0,
            "queue_wait_s": 0.0, "batch_wait_s": 0.0, "forward_s": 0.0,
            "enqueue_failures": 0, "errors": 0,
            "batch_sizes": [], "queue_waits": [],
        }
        self._thread = threading.Thread(target=self._worker, name="batch-leaf",
                                        daemon=True)
        self._thread.start()

    def _new_id(self) -> int:
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    @staticmethod
    def _pack(x: Any, dtype: Any) -> np.ndarray:
        """零拷贝打包：dtype/连续已满足时直接复用原数组（调用方不得再改它）。

        采集侧每次决策都会新建 features/cards/mask（obs_arrays / mask_from_bytes），
        因此复用安全；MCTS 路径若复用缓冲区，请显式传拷贝。
        """
        a = np.asarray(x, dtype=dtype)
        return a if a.flags.c_contiguous else np.ascontiguousarray(a)

    def submit(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
               timeout: float = 0.5, copy: bool = False) -> LeafRequest:
        with self._state_lock:
            if self._state != "open":
                raise RuntimeError(f"BatchLeafServer is {self._state}")
            if copy:
                req = LeafRequest(self._new_id(),
                                  np.array(features, dtype=np.float32, copy=True),
                                  np.array(cards, dtype=np.int64, copy=True),
                                  np.array(mask, dtype=bool, copy=True))
            else:
                req = LeafRequest(self._new_id(),
                                  self._pack(features, np.float32),
                                  self._pack(cards, np.int64),
                                  self._pack(mask, bool))
            req.submit_t = time.monotonic()
            try:
                self._q.put(req, timeout=float(timeout))
            except queue.Full as exc:
                with self._stats_lock:
                    self.stats["enqueue_failures"] += 1
                raise TimeoutError("batch leaf enqueue timeout") from exc
            with self._stats_lock:
                self.stats["requests"] += 1
        return req

    def reset_stats(self) -> None:
        with self._stats_lock:
            for k in ("requests", "batches", "leafs", "max_batch", "queue_wait_s",
                      "batch_wait_s", "forward_s", "enqueue_failures", "errors"):
                self.stats[k] = 0.0 if k.endswith("_s") else 0
            self.stats["batch_sizes"] = []
            self.stats["queue_waits"] = []

    def call(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
             seat: int = 0, timeout: float = 30.0) -> Tuple[np.ndarray, float]:
        req = self.submit(features, cards, mask)
        if not req.event.wait(timeout=timeout):
            raise TimeoutError("batch leaf timeout")
        if req.error is not None:
            raise req.error
        assert req.prior is not None
        return req.prior, float(req.value)  # type: ignore[arg-type]

    def call_many(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                  timeout: float = 60.0) -> List[Tuple[np.ndarray, float]]:
        """先全部 submit 再等待；这样单线程也能让 worker 聚批。"""
        f = np.asarray(features); c = np.asarray(cards); m = np.asarray(mask)
        reqs = [self.submit(f[i], c[i], m[i]) for i in range(len(f))]
        out: List[Tuple[np.ndarray, float]] = []
        for r in reqs:
            if not r.event.wait(timeout=timeout):
                raise TimeoutError("batch leaf timeout")
            if r.error is not None:
                raise r.error
            assert r.prior is not None
            out.append((r.prior, float(r.value)))  # type: ignore[arg-type]
        return out

    def _take_batch(self) -> List[LeafRequest]:
        first = self._q.get()
        batch = [first]
        t0 = time.time()
        while len(batch) < self.batch_size:
            remaining = self.max_wait_s - (time.time() - t0)
            if remaining <= 0:
                break
            try:
                batch.append(self._q.get(timeout=remaining))
            except queue.Empty:
                break
        return batch

    def _worker(self) -> None:
        while True:
            try:
                first = self._q.get(timeout=0.1)
            except queue.Empty:
                if self._stop.is_set():
                    break
                continue
            if first is None:  # sentinel
                break
            batch = [first]
            t_start = time.monotonic()
            # 固定等待窗口聚批；不再阻塞到无限
            deadline = t_start + self.max_wait_s
            while len(batch) < self.batch_size:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                try:
                    nxt = self._q.get(timeout=rem)
                except queue.Empty:
                    break
                if nxt is None:
                    self._stop.set()
                    break
                batch.append(nxt)
            try:
                f = np.stack([r.features.reshape(-1) for r in batch], axis=0)
                c = np.stack([r.cards.reshape(-1) for r in batch], axis=0)
                m = np.stack([r.mask.reshape(-1) for r in batch], axis=0)
                t0 = time.monotonic()
                plog, rlog = self.evaluator.logits(f, c, m)
                fwd = time.monotonic() - t0
                for i, r in enumerate(batch):
                    p = masked_probs_np(plog[i], m[i], self.temperature)
                    p = p / max(float(p.sum()), 1e-12)
                    r.prior = p.astype(np.float32)
                    r.value = float(value_from_rank_logits_np(rlog[i])[0])
                    r.event.set()
                with self._stats_lock:
                    self.stats["batches"] += 1
                    self.stats["leafs"] += len(batch)
                    self.stats["max_batch"] = max(self.stats["max_batch"], len(batch))
                    self.stats["forward_s"] += fwd
                    qw = [max(0.0, t_start - getattr(r, "submit_t", t_start)) for r in batch]
                    self.stats["batch_wait_s"] += max(0.0, t0 - t_start)
                    self.stats["queue_wait_s"] += sum(qw)
                    self.stats["batch_sizes"].append(len(batch))
                    self.stats["queue_waits"].extend(qw)
            except BaseException as exc:  # 线程内异常必须回传
                for r in batch:
                    if not r.event.is_set():
                        r.error = exc
                        r.event.set()
                with self._stats_lock:
                    self.stats["errors"] += len(batch)
        # 退出一律失败未完成请求
        while True:
            try:
                r = self._q.get_nowait()
            except queue.Empty:
                break
            if r is not None and not r.event.is_set():
                r.error = RuntimeError("BatchLeafServer closed")
                r.event.set()

    @staticmethod
    def _pct(xs, q: float) -> float:
        if not xs:
            return 0.0
        ys = sorted(float(x) for x in xs)
        i = min(len(ys) - 1, max(0, int(round(q * (len(ys) - 1)))))
        return float(ys[i])

    def profile(self) -> Dict[str, Any]:
        with self._stats_lock:
            bs = list(self.stats.get("batch_sizes", []))
            qw = list(self.stats.get("queue_waits", []))
        return {
            "batch_p50": self._pct(bs, 0.5), "batch_p95": self._pct(bs, 0.95),
            "batch_max": (max(bs) if bs else 0),
            "queue_wait_ms_p50": 1000.0 * self._pct(qw, 0.5),
            "queue_wait_ms_p95": 1000.0 * self._pct(qw, 0.95),
        }

    def close(self) -> None:
        with self._state_lock:
            if self._state == "closed":
                return
            self._state = "closing"
            self._stop.set()
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
        self._thread.join(timeout=5.0)
        with self._state_lock:
            self._state = "closed"

    def __enter__(self) -> "BatchLeafServer":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class BatchPPOEvaluator:
    """与 `PPOEvaluator.__call__` 同接口，但走 BatchLeafServer。"""

    name = "ppo_net_batch"
    accepts_game = False

    def __init__(self, server: BatchLeafServer) -> None:
        self.server = server
        self.model = server.evaluator.model
        self.device = server.evaluator.device

    def __call__(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                 seat: int = 0) -> Tuple[np.ndarray, float]:
        return self.server.call(features, cards, mask, seat)


__all__ = ["LeafRequest", "BatchLeafServer", "BatchPPOEvaluator"]
