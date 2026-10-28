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
    #: True = 直接在 worker 里按 temperature 采样动作（不回传 245 维 prior）
    want_action: bool = False
    #: True = 该请求携带 2D 批（features[k,3227] ...），结果写入 actions/logprobs/values
    batch_mode: bool = False
    actions: Optional[np.ndarray] = None
    logprobs: Optional[np.ndarray] = None
    values: Optional[np.ndarray] = None
    temperature: float = 1.0
    seed: Optional[int] = None
    action: Optional[int] = None
    logprob: Optional[float] = None


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
               timeout: float = 0.5, copy: bool = False, *,
               want_action: bool = False, temperature: float = 1.0,
               seed: Optional[int] = None) -> LeafRequest:
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
            req.want_action = bool(want_action)
            req.temperature = float(temperature)
            req.seed = seed
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

    def act(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
            temperature: float = 1.0, seed: Optional[int] = None,
            timeout: float = 30.0) -> Tuple[int, float, float]:
        """worker 侧采样：返回 ``(action, logprob, value)``，不构造 245 维 prior。"""
        req = self.submit(features, cards, mask, want_action=True,
                          temperature=temperature, seed=seed)
        if not req.event.wait(timeout=timeout):
            raise TimeoutError("batch leaf timeout")
        if req.error is not None:
            raise req.error
        assert req.action is not None
        return int(req.action), float(req.logprob or 0.0), float(req.value or 0.0)

    def act_batch(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                  temperature: float = 1.0, seed: Optional[int] = None,
                  timeout: float = 60.0):
        """一次请求携带 2D 批：返回 (actions, logprobs, values)，批内每行独立 seed=seed+j。

        lock-step actor 的底层原语：N 局拼一个批、一次前向、一次 GIL 往返。
        """
        req = self.submit(np.atleast_2d(features), np.atleast_2d(cards),
                          np.atleast_2d(mask), want_action=True,
                          temperature=temperature, seed=seed)
        req.batch_mode = True
        if not req.event.wait(timeout=timeout):
            raise TimeoutError("batch leaf timeout")
        if req.error is not None:
            raise req.error
        return req.actions, req.logprobs, req.values

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
                f = np.concatenate([np.atleast_2d(r.features) for r in batch], axis=0)
                c = np.concatenate([np.atleast_2d(r.cards) for r in batch], axis=0)
                m = np.concatenate([np.atleast_2d(r.mask) for r in batch], axis=0)
                owner = []
                for ri, r in enumerate(batch):
                    k = int(np.atleast_2d(r.features).shape[0])
                    owner.extend([ri] * k)
                t0 = time.monotonic()
                plog, rlog = self.evaluator.logits(f, c, m)
                fwd = time.monotonic() - t0
                off = 0
                for i, r in enumerate(batch):
                    temp = float(r.temperature) if r.temperature else self.temperature
                    if r.batch_mode:
                        k = int(np.atleast_2d(r.features).shape[0])
                        acts = np.empty(k, dtype=np.int64)
                        lps = np.empty(k, dtype=np.float32)
                        vals = np.empty(k, dtype=np.float32)
                        for j in range(k):
                            p = masked_probs_np(plog[off + j], m[off + j], temp)
                            p = p / max(float(p.sum()), 1e-12)
                            seed = None if r.seed is None else int(r.seed) + j
                            rng = np.random.default_rng(seed if seed is not None else 0)
                            a = int(rng.choice(p.size, p=p))
                            acts[j] = a
                            lps[j] = float(np.log(max(float(p[a]), 1e-12)))
                            vals[j] = float(value_from_rank_logits_np(rlog[off + j])[0])
                        r.actions, r.logprobs, r.values = acts, lps, vals
                        off += k
                        r.event.set()
                        continue
                    if r.want_action:
                        # GPU/worker 侧采样：不回传 245 维 prior，直接用请求 seed 采样
                        p = masked_probs_np(plog[i], m[i], temp)
                        p = p / max(float(p.sum()), 1e-12)
                        rng = np.random.default_rng(int(r.seed) if r.seed is not None else 0)
                        a = int(rng.choice(p.size, p=p))
                        r.action = a
                        r.logprob = float(np.log(max(float(p[a]), 1e-12)))
                    else:
                        p = masked_probs_np(plog[i], m[i], temp)
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

    def act(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
            temperature: float = 1.0, seed: Optional[int] = None
            ) -> Tuple[int, float, float]:
        return self.server.act(features, cards, mask, temperature, seed)

    def act_batch(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                  temperature: float = 1.0, seed: Optional[int] = None):
        return self.server.act_batch(features, cards, mask, temperature, seed)


__all__ = ["LeafRequest", "BatchLeafServer", "BatchPPOEvaluator"]
