"""进程级 actor pool（持久 worker 版，P0 吞吐组件）。

## 为什么要重写

2026-10-27 18:23 的 4 GPU 扫描用旧实现（每轮新建 ``mp.Pool("spawn")``）跑到约
2 分钟就 ``BrokenPipeError: [Errno 32] Broken pipe``，30 分钟扫描无法完成。根因是
三件事叠在一起：

1. 每轮重新 spawn 全部 worker（spawn 启动 + CUDA context + 17M 模型加载），
   单轮固定开销极大；
2. 每轮把 ``records``（数万条 × 3227 floats 的 dict 列表）直接经 Pool 的管道回传，
   单轮几十 MB，父进程一旦来不及读就断管道；
3. ``with Pool(...)`` 退出即 terminate，worker 的 feeder 线程还在 ``put``。

## 本实现

- **worker 常驻**：spawn 一次，每个进程绑定一张 GPU，模型只加载一次；
- **权重热加载**：PPO 更新后 ``reload_weights(path)``，不重建进程；
- **结果落盘**：records 写临时文件，队列只传路径 + 统计，避免大 pickle 堵管道；
- **自愈**：worker 死亡可检测，自动重启并重试该 shard（记录 restart 次数）；
- **指标完整**：每个 worker 内部用 ``collect_ppo_batch_parallel``（多局线程 + 共享
  ``BatchLeafServer``），因此能同时报 decisions/s、leaf/s、batch fill 与
  queue wait p50/p95。

## 边界（必须如实写进报告）

- 这不是 topology A：没有跨进程共享 inference server，每个进程一份模型副本；
- Rust ``mcts_search`` 仍逐叶回调 Python；本方案靠**多进程**绕开单进程 GIL，
  进程内仍受 GIL 限制（所以进程内线程数不是越大越好）；
- 各 worker 权重固定到一次 ``collect``，同步模式（P0），没有异步 stale policy。
"""

from __future__ import annotations

import multiprocessing as mp
import os
import pickle
import queue
import time
import traceback
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .common import to_jsonable
from .ppo import (CollectConfig, PPOBatch, build_batch_from_arrays,
                  build_batch_from_records, pack_records_arrays)


# ---------------------------------------------------------------------------
# 子进程
# ---------------------------------------------------------------------------
#: 每个 worker 进程内的镜像库缓存（按路径）
_LIB_CACHE: Dict[str, Any] = {}


def _save_built_batch(batch: Any, path: str) -> None:
    """把已构建的 PPOBatch 写成 npz（episode_id 用全局唯一键 game_id*8+seat）。"""
    np.savez(path, features=batch.features, cards=batch.cards, masks=batch.masks,
             actions=batch.actions, old_logprobs=batch.old_logprobs,
             values=batch.values, rewards=batch.rewards, dones=batch.dones,
             advantages=batch.advantages, returns=batch.returns,
             seats=batch.seats, game_ids=batch.game_ids, ranks=batch.ranks,
             turns=batch.turns, forced=batch.forced, has_pi=batch.has_pi,
             episode_ids=(batch.game_ids * 8 + batch.seats).astype(np.int64),
             target_pi=(batch.target_pi if batch.target_pi is not None
                        else np.zeros((len(batch.actions), 245), np.float32)))


def _worker_main(payload: Dict[str, Any], task_q: Any, result_q: Any) -> None:
    """常驻 worker：load checkpoint -> 循环收任务 -> 采集/热加载 -> 回传路径与统计。"""
    import torch
    from .model import load_checkpoint
    from .batch_eval import BatchLeafServer, BatchPPOEvaluator
    from .parallel_collect import collect_ppo_lockstep, collect_ppo_records_parallel
    from .rust_collect import collect_ppo_rust

    # 进程内不需要 torch 的 CPU 线程池（GPU 前向 + 多线程采集已经够并行）
    torch.set_num_threads(1)

    index = int(payload["index"])
    gpu = int(payload["gpu"])
    cuda = bool(torch.cuda.is_available())
    device = f"cuda:{gpu}" if cuda else "cpu"
    if cuda:
        torch.cuda.set_device(gpu)

    def _report(msg: Dict[str, Any]) -> None:
        msg.setdefault("worker", index)
        msg.setdefault("gpu", gpu)
        result_q.put(msg)

    try:
        model, meta = load_checkpoint(payload["checkpoint"], device=device)
    except BaseException as exc:  # noqa: BLE001
        _report({"type": "fatal", "error": f"load checkpoint failed: {exc!r}",
                 "traceback": traceback.format_exc()})
        return

    norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
    server = BatchLeafServer(
        model, device=device,
        batch_size=int(payload.get("batch_size", 64)),
        max_wait_ms=float(payload.get("max_wait_ms", 2.0)),
        queue_size=int(payload.get("queue_size", 8192)),
        norm_mean=norm_mean, norm_std=norm_std)
    evaluator = BatchPPOEvaluator(server)

    sims = int(payload.get("sims", 0))
    det = int(payload.get("determinizations", 1))
    search_fn = None
    def _search_config(seed: int) -> Any:
        from hsbg.az import SearchConfig
        return SearchConfig(simulations=sims, determinizations=max(1, det), seed=int(seed))

    if sims > 0:
        try:
            from hsbg.az import search as az_search
        except BaseException as exc:  # noqa: BLE001
            _report({"type": "fatal", "error": f"search unavailable: {exc!r}",
                     "traceback": traceback.format_exc()})
            return
        search_fn = az_search

    weights_version = int(payload.get("checkpoint_version", 0))
    weights_path = str(payload["checkpoint"])

    def _maybe_reload(version: Any, path: Any) -> None:
        """按版本号懒加载权重（流水线用；不经过结果队列，避免与 collect 抢消息）。"""
        nonlocal model, norm_mean, norm_std, weights_version, weights_path
        if version is None:
            return
        v = int(version)
        p = str(path or weights_path)
        if v == weights_version and p == weights_path:
            return
        payload_ckpt = torch.load(p, map_location=device, weights_only=True)
        model.load_state_dict(payload_ckpt["state_dict"])
        model.to(torch.device(device))
        model.eval()
        server.evaluator.model = model
        if "norm_mean" in payload_ckpt:
            norm_mean = np.asarray(payload_ckpt["norm_mean"], dtype=np.float32)
            server.evaluator.mean = norm_mean
        if "norm_std" in payload_ckpt:
            norm_std = np.asarray(payload_ckpt["norm_std"], dtype=np.float32)
            server.evaluator.std = norm_std
        weights_version, weights_path = v, p
        _report({"type": "weights_loaded", "version": v, "path": p})

    _report({"type": "ready", "pid": os.getpid(), "arch": meta.get("arch"),
             "params": int(sum(p.numel() for p in model.parameters())),
             "cuda": cuda, "device": device})

    while True:
        try:
            task = task_q.get()
        except (EOFError, OSError):
            break
        if task is None:
            break
        kind = str(task.get("kind", "collect"))
        task_id = task.get("task_id")

        if kind == "stop":
            break

        if kind == "reload":
            try:
                # 只换权重 + 标准化统计，保住进程与 CUDA context
                payload_ckpt = torch.load(task["checkpoint"], map_location=device,
                                          weights_only=True)
                model.load_state_dict(payload_ckpt["state_dict"])
                model.to(torch.device(device))
                model.eval()
                server.evaluator.model = model
                if "norm_mean" in payload_ckpt:
                    server.evaluator.mean = np.asarray(
                        payload_ckpt["norm_mean"], dtype=np.float32)
                if "norm_std" in payload_ckpt:
                    server.evaluator.std = np.asarray(
                        payload_ckpt["norm_std"], dtype=np.float32)
                _report({"type": "reload_done", "task_id": task_id,
                         "updates": int(task.get("updates", -1))})
            except BaseException as exc:  # noqa: BLE001
                _report({"type": "reload_error", "task_id": task_id,
                         "error": repr(exc), "traceback": traceback.format_exc()})
            continue

        # ---- collect ----
        _t_reload0 = time.time()
        try:
            _maybe_reload(task.get("weights_version"), task.get("weights_path"))
        except BaseException as exc:  # noqa: BLE001
            _report({"type": "collect_error", "task_id": task_id,
                     "error": f"weights reload failed: {exc!r}",
                     "traceback": traceback.format_exc(), "seconds": 0.0})
            continue
        _reload_s = time.time() - _t_reload0
        _t_start = time.monotonic()
        t0 = time.time()
        try:
            cfg = CollectConfig(**task["cfg"])
            try:
                server.evaluator.amp = str(cfg.leaf_amp)
                if bool(getattr(cfg, "leaf_compile", False)):
                    server.evaluator.enable_compile()
            except Exception:  # noqa: BLE001
                pass
            server.reset_stats()
            if bool(task.get("rust_collector", False)) and search_fn is None:
                arr, cmeta = collect_ppo_rust(
                    model, cfg, eval_fn=evaluator, device=device,
                    seed=int(task["seed"]), games=int(cfg.games),
                    gamemode=str(cfg.opponent), threads=int(task.get("rc_threads", 1)))
                records = []
            elif bool(task.get("lockstep", False)) and search_fn is None:
                # lock-step：每 worker 内 N 局同步推进，每轮一次批量前向
                lib = None
                if str(getattr(cfg, "library_pool", "")) and \
                        float(getattr(cfg, "library_p", 0.0)) > 0.0:
                    from .library_pool import LibraryPool
                    lib = _LIB_CACHE.get(cfg.library_pool) or LibraryPool(cfg.library_pool)
                    if not lib.entries:
                        print(f"[warn] 镜像库为空/不存在: {cfg.library_pool}", flush=True)
                        lib = None
                    _LIB_CACHE[cfg.library_pool] = lib
                records, cmeta = collect_ppo_lockstep(
                    model, cfg, eval_fn=evaluator, device=device,
                    seed=int(task["seed"]), games=int(cfg.games),
                    gamemode=str(cfg.opponent), norm_mean=norm_mean,
                    norm_std=norm_std, library_pool=lib,
                    library_p=float(getattr(cfg, "library_p", 0.0)))
            else:
                records, cmeta = collect_ppo_records_parallel(
                    model, cfg, workers=int(task.get("threads", 4)),
                    search_fn=search_fn,
                    search_config=(_search_config(int(task["seed"])) if search_fn else None),
                    eval_fn=evaluator, device=device, seed=int(task["seed"]),
                    norm_mean=norm_mean, norm_std=norm_std, progress=False)
            _collect_s = time.time() - t0
            records_file = None
            n_records = int(len(records))
            if bool(task.get("return_records", True)):
                # L4：worker 内构建 batch（排序/过滤/GAE 并行化）；episode_id 用
                # (game_id*8+seat) 作为全局唯一键，父进程直接拼接、无需重编号
                records_file = os.path.join(
                    task["tmpdir"], f"rec_{task_id}_w{index}.npz")
                if bool(task.get("rust_collector", False)) and search_fn is None:
                    _save_built_batch(
                        build_batch_from_arrays(arr, gamma=float(task.get("gamma", 1.0)),
                                                lam=float(task.get("lam", 0.95))),
                        records_file)
                else:
                    packed = pack_records_arrays(records)
                    try:
                        _save_built_batch(
                            build_batch_from_arrays(
                                packed, gamma=float(task.get("gamma", 1.0)),
                                lam=float(task.get("lam", 0.95))),
                            records_file)
                    except BaseException:  # noqa: BLE001 - 回退到父进程构建
                        np.savez(records_file, **packed)
            _save_s = time.time() - t0 - _collect_s
            profile = dict(server.profile())
            profile.update({"reload_s": float(_reload_s),
                            "collect_s": float(_collect_s),
                            "save_s": float(_save_s)})
            stats = server.stats
            _report({
                "type": "collect_done", "task_id": task_id,
                "seconds": time.time() - t0,
                "reload_s": float(_reload_s), "collect_s": float(_collect_s),
                "save_s": float(_save_s),
                "t_start": _t_start, "t_end": time.monotonic(),
                "records_file": records_file, "records": n_records,
                "meta": to_jsonable(cmeta),
                "profile": to_jsonable(profile),
                "leafs": int(stats.get("leafs", 0)),
                "batches": int(stats.get("batches", 0)),
                "batch_max": int(stats.get("max_batch", 0)),
                "forward_s": float(stats.get("forward_s", 0.0)),
                "batch_wait_s": float(stats.get("batch_wait_s", 0.0)),
                "errors": int(stats.get("errors", 0)),
            })
        except BaseException as exc:  # noqa: BLE001
            _report({"type": "collect_error", "task_id": task_id,
                     "error": repr(exc), "traceback": traceback.format_exc(),
                     "seconds": time.time() - t0})
    try:
        server.close()
    except BaseException:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 父进程
# ---------------------------------------------------------------------------
class ProcessActorPool:
    """常驻多进程 actor pool（每个 worker 一张 GPU，同步模式）。"""

    def __init__(self, processes: int, gpus: List[int], checkpoint: str, *,
                 arch: str = "entity", sims: int = 0,
                 determinizations: int = 1, seed: int = 0,
                 threads: int = 8, batch_size: int = 64,
                 max_wait_ms: float = 2.0, queue_size: int = 8192,
                 tmpdir: Optional[str] = None,
                 python: Optional[str] = None) -> None:
        self.processes = max(1, int(processes))
        self.gpus = [int(g) for g in (gpus or [0])]
        self.checkpoint = str(checkpoint)
        self.arch = str(arch)
        self.sims = int(sims)
        self.determinizations = max(1, int(determinizations))
        self.seed = int(seed)
        self.threads = max(1, int(threads))
        self.batch_size = max(1, int(batch_size))
        self.max_wait_ms = float(max_wait_ms)
        self.queue_size = int(queue_size)
        self.tmpdir = str(tmpdir or os.path.join(
            os.path.dirname(os.path.abspath(checkpoint)) or ".", "_proc_pool"))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.ctx = mp.get_context("spawn")
        self.restarts = 0
        self._procs: List[Any] = []
        self._task_qs: List[Any] = []
        self._result_q = self.ctx.Queue()
        #: 启动/重载期间可能读到不属于当前等待者的消息，先缓冲、由后续等待者再取
        self._deferred: List[Dict[str, Any]] = []
        self._info: List[Dict[str, Any]] = []
        self._spawn_all()

    # -- lifecycle ---------------------------------------------------------
    def _spawn_all(self) -> None:
        for i in range(self.processes):
            self._spawn_one(i)

    def _take_msg(self, timeout: float, want_worker: Optional[int] = None,
                  accept: Optional[Any] = None) -> Dict[str, Any]:
        """取一条消息；不匹配 ``want_worker`` 的暂存到 ``_deferred`` 并继续等。

        关键：暂存的消息**不能被同一个等待者再次取出**（否则会忙等到超时）。
        先扫缓冲里是否有本等待者需要的消息，再从共享队列读。
        """
        def _ok(m: Dict[str, Any]) -> bool:
            if want_worker is not None and m.get("worker") != want_worker:
                return False
            return True if accept is None else bool(accept(m))

        for idx, m in enumerate(self._deferred):
            if _ok(m):
                return self._deferred.pop(idx)
        deadline = time.time() + float(timeout)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise queue.Empty
            msg = self._result_q.get(timeout=remaining)
            if _ok(msg):
                return msg
            self._deferred.append(msg)   # 匹配不上：留给对应等待者，不再被自己取出

    def _spawn_one(self, i: int) -> None:
        q = self.ctx.Queue()
        payload = {
            "index": i, "gpu": self.gpus[i % len(self.gpus)],
            "checkpoint": self.checkpoint, "arch": self.arch,
            "sims": self.sims, "determinizations": self.determinizations,
            "seed": self.seed, "threads": self.threads,
            "batch_size": self.batch_size, "max_wait_ms": self.max_wait_ms,
            "queue_size": self.queue_size,
        }
        p = self.ctx.Process(target=_worker_main, args=(payload, q, self._result_q),
                             name=f"actor-{i}", daemon=True)
        p.start()
        if i < len(self._procs):
            self._procs[i] = p
            self._task_qs[i] = q
        else:
            self._procs.append(p)
            self._task_qs.append(q)
        # 等 ready / fatal
        deadline = time.time() + 180.0
        while time.time() < deadline:
            try:
                msg = self._take_msg(5.0, want_worker=i)
            except queue.Empty:
                if not p.is_alive():
                    raise RuntimeError(f"actor-{i} 启动即退出（exit={p.exitcode}）")
                continue
            if msg["type"] == "ready":
                info = {"index": i, "gpu": msg["gpu"], "pid": msg["pid"],
                        "arch": msg.get("arch"), "params": msg.get("params"),
                        "device": msg.get("device")}
                if i < len(self._info):
                    self._info[i] = info
                else:
                    self._info.append(info)
                return
            if msg["type"] == "fatal":
                raise RuntimeError(f"actor-{i} 初始化失败: {msg.get('error')}\n"
                                   f"{msg.get('traceback', '')}")
            # 其它（如上一轮遗留）忽略
        raise TimeoutError(f"actor-{i} 初始化超时")

    def _check_alive(self) -> List[int]:
        dead = [i for i, p in enumerate(self._procs) if not p.is_alive()]
        for i in dead:
            self.restarts += 1
            try:
                self._procs[i].join(timeout=1.0)
            except BaseException:  # noqa: BLE001
                pass
            self._spawn_one(i)
        return dead

    def close(self) -> None:
        for q in self._task_qs:
            try:
                q.put_nowait({"kind": "stop"})
            except BaseException:  # noqa: BLE001
                pass
        for p in self._procs:
            p.join(timeout=10.0)
            if p.is_alive():
                p.terminate()
        for p in self._procs:
            try:
                p.join(timeout=2.0)
            except BaseException:  # noqa: BLE001
                pass

    def __enter__(self) -> "ProcessActorPool":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- control -----------------------------------------------------------
    def reload_weights(self, checkpoint: str, *, updates: int = -1,
                       timeout: float = 300.0) -> int:
        """把新 checkpoint 推到所有 worker（不重建进程）。返回成功 worker 数。

        可靠性：
        - 只接受本任务的消息（`accept`），别的任务消息留在缓冲里给它的等待者；
        - worker 死亡被 `_check_alive` 重启后，**重新加入 pending 并向新队列重发**，
          避免「旧队列任务发给死进程 → 永远等不到」和「重启后仍跑构造时旧权重」；
        - 成功数按 worker 集合计，重复 done 不重复计数。
        """
        task_id = uuid.uuid4().hex[:12]
        payload = {"kind": "reload", "task_id": task_id,
                   "checkpoint": checkpoint, "updates": int(updates)}
        pending = set(range(len(self._task_qs)))
        acked: set = set()
        errors: List[str] = []
        pids = {i: (self._info[i] or {}).get("pid") for i in range(len(self._task_qs))}
        deadline = time.time() + float(timeout)

        def _resend() -> None:
            for i in sorted(pending):
                if i < len(self._task_qs):
                    self._task_qs[i].put(dict(payload))

        def _resync() -> bool:
            """检查存活/重启；被重启（pid 变化）的 worker 重新加入 pending。"""
            self._check_alive()
            changed = False
            for i in range(len(self._task_qs)):
                pid = (self._info[i] or {}).get("pid")
                if pid is not None and pid != pids.get(i):
                    pids[i] = pid
                    pending.add(i)
                    changed = True
            return changed

        _resend()
        while pending:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"reload_weights 超时: pending={sorted(pending)} "
                                   f"errors={errors}")
            try:
                msg = self._take_msg(min(5.0, remaining),
                                     accept=lambda m: m.get("task_id") == task_id)
            except queue.Empty:
                if _resync():
                    _resend()
                continue
            w = int(msg.get("worker", -1))
            if msg["type"] == "reload_done":
                if w in pending:
                    pending.discard(w)
                    acked.add(w)
            elif msg["type"] == "reload_error":
                if w in pending:
                    pending.discard(w)
                    errors.append(f"worker{w}: {msg.get('error')}")
            # 收到任何消息后都检查：ack 之后立刻死亡的 worker 必须重启并重发目标权重
            if _resync():
                _resend()
        if errors:
            raise RuntimeError(f"reload_weights 失败: {errors}")
        return len(acked)

    # -- collect -----------------------------------------------------------
    def collect(self, cfg: CollectConfig, games: int, *,
                return_records: bool = True, timeout: float = 3600.0,
                progress: bool = False,
                seed: Optional[int] = None,
                gamma: float = 1.0, lam: float = 0.95,
                weights_version: Optional[int] = None,
                weights_path: Optional[str] = None) -> Tuple[PPOBatch, Dict[str, Any]]:
        n = max(1, int(games))
        per = (n + self.processes - 1) // self.processes
        shards: List[Dict[str, Any]] = []
        for i in range(self.processes):
            g0 = i * per
            gcount = max(0, min(per, n - g0))
            if gcount <= 0:
                continue
            shards.append({"worker": i, "offset": g0, "games": gcount})
        self._check_alive()
        task_id = uuid.uuid4().hex
        reqs: Dict[int, Dict[str, Any]] = {}
        for sh in shards:
            i, g0, gcount = sh["worker"], sh["offset"], sh["games"]
            seed_i = (self.seed if seed is None else int(seed)) + g0
            payload = {
                "kind": "collect", "task_id": task_id,
                "seed": seed_i, "threads": self.threads,
                "return_records": bool(return_records),
                "tmpdir": self.tmpdir, "gamma": float(gamma), "lam": float(lam),
                "weights_version": weights_version, "weights_path": weights_path,
                "lockstep": bool(getattr(cfg, "lockstep", False)),
                "cfg": {**asdict(cfg), "games": gcount,
                        "seed": seed_i, "game_id_offset": g0},
            }
            reqs[i] = payload
            self._task_qs[i].put(payload)

        timeline: Dict[str, Any] = {"t_issue": {i: time.monotonic() for i in reqs},
                                    "t_dispatch_done": None}
        results: Dict[int, Dict[str, Any]] = {}
        attempts: Dict[int, int] = {i: 0 for i in reqs}
        deadline = time.time() + float(timeout)
        t_start = time.time()
        while len(results) < len(reqs):
            remaining = deadline - time.time()
            if remaining <= 0:
                missing = sorted(set(reqs) - set(results))
                raise TimeoutError(f"collect 超时 {timeout:.0f}s，缺失 worker {missing}")
            try:
                msg = self._take_msg(min(5.0, remaining),
                                     accept=lambda m: m.get("task_id") == task_id)
            except queue.Empty:
                # 检查是否有人死了；死了就重启 + 重发该 shard（最多 2 次）
                for i, p in enumerate(self._procs):
                    if i in results or i not in reqs:
                        continue
                    if p.is_alive():
                        continue
                    attempts[i] += 1
                    self.restarts += 1
                    self._spawn_one(i)
                    if attempts[i] > 2:
                        raise RuntimeError(
                            f"worker{i} 连续死亡 >2 次（gpu={self.gpus[i % len(self.gpus)]}）")
                    if progress:
                        print(f"[pool] worker{i} died -> restarted "
                              f"(attempt {attempts[i]})", flush=True)
                    self._task_qs[i].put(reqs[i])
                continue
            if msg.get("task_id") != task_id:
                # 旧任务/控制消息：丢弃
                continue
            i = int(msg.get("worker", -1))
            if msg["type"] == "collect_error":
                raise RuntimeError(
                    f"worker{i} 采集失败: {msg.get('error')}\n{msg.get('traceback', '')}")
            if msg["type"] == "collect_done":
                timeline.setdefault("t_recv", {})[i] = time.monotonic()
                results[i] = msg
                if progress:
                    print(f"[pool] worker{i} gpu{msg.get('gpu')} "
                          f"decisions={msg.get('meta', {}).get('decisions')} "
                          f"{msg.get('seconds', 0):.1f}s", flush=True)

        timeline["t_dispatch_done"] = time.monotonic()
        wall = time.time() - t_start
        records: List[Dict[str, Any]] = []
        packed_all: List[Dict[str, np.ndarray]] = []
        metas: List[Dict[str, Any]] = []
        profiles: List[Dict[str, Any]] = []
        agg = {k: 0 for k in ("decisions", "records", "leafs", "batches",
                              "batch_max", "illegal", "truncated", "invalid",
                              "dropped", "search_calls", "search_failures",
                              "forced", "errors")}
        agg.update({"reload_s": 0.0, "collect_s": 0.0, "save_s": 0.0})
        forward_s = batch_wait_s = 0.0
        t_read = records_bytes = 0.0
        timeline["t_read_start"] = time.monotonic()
        for i in sorted(results):
            msg = results[i]
            m = dict(msg.get("meta") or {})
            metas.append(m)
            profiles.append({"worker": i, "gpu": msg.get("gpu"),
                             "seconds": round(float(msg.get("seconds", 0.0)), 3),
                             **{k: msg.get(k) for k in
                                ("records", "leafs", "batches", "batch_max",
                                 "forward_s", "batch_wait_s", "errors")},
                             **(msg.get("profile") or {})})
            agg["decisions"] += int(m.get("decisions", 0))
            agg["records"] += int(msg.get("records", 0))
            agg["leafs"] += int(msg.get("leafs", 0))
            agg["batches"] += int(msg.get("batches", 0))
            agg["batch_max"] = max(agg["batch_max"], int(msg.get("batch_max", 0)))
            agg["illegal"] += int(m.get("illegal_actions", 0))
            agg["truncated"] += int(m.get("truncated_games", 0))
            agg["invalid"] += int(m.get("invalid_games", 0))
            agg["dropped"] += int(m.get("dropped_decisions", 0))
            agg["search_calls"] += int(m.get("search_calls", 0))
            agg["search_failures"] += int(m.get("search_failures", 0))
            agg["forced"] += int(m.get("forced_end_turns", 0))
            agg["errors"] += int(msg.get("errors", 0))
            agg["reload_s"] += float(msg.get("reload_s", 0.0))
            agg["collect_s"] += float(msg.get("collect_s", 0.0))
            agg["save_s"] += float(msg.get("save_s", 0.0))
            forward_s += float(msg.get("forward_s", 0.0))
            batch_wait_s += float(msg.get("batch_wait_s", 0.0))
            f = msg.get("records_file")
            if f:
                t_r0 = time.time()
                if f.endswith(".npz"):
                    with np.load(f) as z:
                        packed_all.append({k: z[k] for k in z.files})
                else:
                    with open(f, "rb") as fh:
                        records.extend(pickle.load(fh))
                t_read += time.time() - t_r0
                try:
                    records_bytes += os.path.getsize(f)
                except OSError:
                    pass
                try:
                    os.remove(f)
                except OSError:
                    pass

        meta: Dict[str, Any] = {
            "mode": "process_pool",
            "processes": self.processes,
            "gpus": self.gpus,
            "threads_per_process": self.threads,
            "games": len(metas) and sum(int(m.get("games", 0)) for m in metas),
            "requested_games": n,
            "decisions": agg["decisions"],
            "records": agg["records"],
            "illegal_actions": agg["illegal"],
            "truncated_games": agg["truncated"],
            "invalid_games": agg["invalid"],
            "dropped_decisions": agg["dropped"],
            "search_calls": agg["search_calls"],
            "search_failures": agg["search_failures"],
            "forced_end_turns": agg["forced"],
            "sims": self.sims,
            "determinizations": self.determinizations,
            "wall_s": wall,
            "decisions_per_s": agg["decisions"] / wall if wall > 0 else 0.0,
            "leafs": agg["leafs"],
            "leaf_per_s": agg["leafs"] / wall if wall > 0 else 0.0,
            "batches": agg["batches"],
            "batch_max": agg["batch_max"],
            "batch_fill": (agg["leafs"] / (agg["batches"] * self.batch_size)
                           if agg["batches"] else 0.0),
            "queue_wait_ms_p50": float(np.median(
                [p.get("queue_wait_ms_p50", 0.0) for p in profiles])) if profiles else 0.0,
            "queue_wait_ms_p95": max(
                [float(p.get("queue_wait_ms_p95", 0.0)) for p in profiles]) if profiles else 0.0,
            "batch_p50": float(np.median(
                [p.get("batch_p50", 0.0) for p in profiles])) if profiles else 0.0,
            "batch_p95": max([float(p.get("batch_p95", 0.0)) for p in profiles]) if profiles else 0.0,
            "forward_s": forward_s,
            "batch_wait_s": batch_wait_s,
            "restarts": self.restarts,
            "policy_version": weights_version,
            "workers": profiles,
            "worker_meta": to_jsonable(metas),
            "elapsed_s": wall,
        }
        if not records and not packed_all:
            # 采集侧没有有效记录（全部截断/非法），保持与单进程一致的报错语义
            raise RuntimeError(
                f"process pool 无有效轨迹（truncated={agg['truncated']}, "
                f"invalid={agg['invalid']}, decisions={agg['decisions']}）")
        timeline["t_read_done"] = time.monotonic()
        t_b0 = time.time()
        # 统一协议：任何 shard 回退成 raw SoA 时，父进程先把它补齐成 batch 再合并
        for i, p in enumerate(packed_all):
            if "advantages" not in p:
                lb = build_batch_from_arrays(p, gamma=float(gamma), lam=float(lam))
                packed_all[i] = {
                    "features": lb.features, "cards": lb.cards, "masks": lb.masks,
                    "actions": lb.actions, "old_logprobs": lb.old_logprobs,
                    "values": lb.values, "rewards": lb.rewards, "dones": lb.dones,
                    "advantages": lb.advantages, "returns": lb.returns,
                    "seats": lb.seats, "game_ids": lb.game_ids, "ranks": lb.ranks,
                    "turns": lb.turns, "forced": lb.forced, "has_pi": lb.has_pi,
                    "episode_ids": (lb.game_ids * 8 + lb.seats).astype(np.int64),
                    "target_pi": (lb.target_pi if lb.target_pi is not None
                                  else np.zeros((len(lb.actions), 245), np.float32)),
                }
        if packed_all and all("advantages" in p for p in packed_all):
            # L4：worker 已构建好 batch（episode_id 全局唯一）→ 父进程只拼接
            keys = ["features", "cards", "masks", "actions", "old_logprobs", "values",
                    "rewards", "dones", "advantages", "returns", "seats", "game_ids",
                    "ranks", "turns", "forced", "has_pi", "episode_ids", "target_pi"]
            merged = {k: np.concatenate([p[k] for p in packed_all], axis=0) for k in keys}
            meta["episodes"] = int(len(np.unique(merged["episode_ids"])))
            meta["built_in"] = "worker"
            batch = PPOBatch(**merged, meta=meta)
        elif packed_all:
            merged = {k: np.concatenate([p[k] for p in packed_all if k in p], axis=0)
                      for k in packed_all[0]}
            batch = build_batch_from_arrays(merged, gamma=float(gamma),
                                            lam=float(lam), meta=meta)
        else:
            batch = build_batch_from_records(records, gamma=float(gamma),
                                             lam=float(lam), meta=meta)
        build_batch_s = time.time() - t_b0
        meta["parent_read_s"] = float(t_read)
        meta["records_bytes"] = int(records_bytes)
        meta["build_batch_s"] = float(build_batch_s)
        timeline["t_build_done"] = time.monotonic()
        meta["timeline"] = timeline
        batch.meta.update({"collect_seconds": wall,
                           "collect": {k: v for k, v in meta.items()
                                       if k != "worker_meta"}})
        return batch, batch.meta

    # -- misc --------------------------------------------------------------
    def describe(self) -> Dict[str, Any]:
        return {"processes": self.processes, "gpus": self.gpus,
                "threads_per_process": self.threads, "sims": self.sims,
                "determinizations": self.determinizations,
                "checkpoint": self.checkpoint, "tmpdir": self.tmpdir,
                "restarts": self.restarts, "workers": self._info}


__all__ = ["ProcessActorPool"]
