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

import hashlib
import json
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

from .common import N_PLAYERS, to_jsonable
from .behavior_mix import aggregate_behavior_mix
from .runlog import aggregate_injection
from .reward_shaping import aggregate_shaping
from .tier_target import aggregate_tier_target
from .move_guard import aggregate_move_guard
from .archetype_bias import aggregate_archetype_bias
from .ppo import (CollectConfig, PPOBatch, PPOSelfPlayPolicy, build_batch_from_arrays,
                  build_batch_from_records, pack_records_arrays)

# ---------------------------------------------------------------------------
# 子进程
# ---------------------------------------------------------------------------
#: 每个 worker 进程内的镜像库缓存（按路径）
_LIB_CACHE: Dict[str, Any] = {}
_TRAJ_CACHE: Dict[str, Any] = {}
_MIRROR_CACHE: Dict[Any, Any] = {}
_HUMAN_BOARD_CACHE: Dict[Any, Any] = {}
_OPP_CACHE: Dict[Any, Any] = {}
#: 搜索行为混合（μ=(1−ε)π+ε·π_search）的 InferSearcher 缓存（按配置/seed 复用；
#: 权重热加载是 in-place 的，searcher 自动看到新权重）。
_MIX_SEARCHERS: Dict[Any, Any] = {}


# ---------------------------------------------------------------------------
# records 数据通路：npz（disk）/ 共享内存（shm）+ 存储精度（fp32/fp16）
# ---------------------------------------------------------------------------
#: 只有这些「大块 float32」字段会在 ``--records-dtype fp16`` 时降精度存储。
#: ``cards`` 已是 int16（2 B/元素），转 fp16 既不省字节又丢索引精度，故不转。
_RECORDS_FP16_KEYS: Tuple[str, ...] = ("features",)
#: worker 侧 shm 段名前缀；清理只针对本前缀，不碰别人的 /dev/shm
_SHM_PREFIX = "hsb_az_rec_"
#: 每个 worker 的环形 slot 数：2 = 父进程读第 k 轮时 worker 可写第 k+1 轮
_SHM_SLOTS = 2
#: slot 容量向上取整粒度（32 MiB）
_SHM_ROUND = 32 << 20
#: shm 头部（JSON 元数据）预留字节数
_SHM_HEADER = 64 << 10
#: 清理「mtime 早于这么久」的残留段（秒）；崩溃进程留下的段不会永久占 /dev/shm
_SHM_STALE_S = 6 * 3600
#: worker 进程内的 shm 段缓存：{worker_index: {"slots": {slot: SharedMemory}, "seq": int}}
_SHM_STATE: Dict[int, Any] = {}
#: fp16 存储的上限（超过这个值 fp16 会变 inf；实测 features 已归一到 |x|<=2.3，
#: 这里只是防注入/扩展位带来的极端值，保证「宁可夹住也不出 inf」）
_FP16_MAX = 65504.0
#: 可选的 torch 快速转换（CPU fp32↔fp16：实测 18 ms vs numpy astype 1.25 s / 322 MB）
_TORCH: Any = None


def _torch() -> Any:
    """惰性导入 torch（没有 torch 时返回 None，回退 numpy astype）。"""
    global _TORCH
    if _TORCH is None:
        try:
            import torch as _t
            _TORCH = _t
        except BaseException:  # noqa: BLE001
            _TORCH = False
    return _TORCH or None


def _cast_fp16(a: np.ndarray) -> np.ndarray:
    """float32 → float16（先 clamp 到 ±65504；有 torch 时走向量化转换）。"""
    a = np.ascontiguousarray(a)
    t = _torch()
    if t is not None and a.dtype == np.float32:
        return t.from_numpy(a).clamp(-_FP16_MAX, _FP16_MAX).to(t.float16).numpy()
    return np.clip(a, -_FP16_MAX, _FP16_MAX).astype(np.float16)


def _cast_fp32(a: np.ndarray) -> np.ndarray:
    """float16 → float32（父进程读入后立刻还原；有 torch 时走向量化转换）。"""
    t = _torch()
    if t is not None and a.dtype == np.float16:
        return t.from_numpy(np.ascontiguousarray(a)).to(t.float32).numpy()
    return np.asarray(a).astype(np.float32)


def _batch_arrays(batch: Any) -> Dict[str, np.ndarray]:
    """``PPOBatch`` → 落盘用的数组字典（与旧 ``_save_built_batch`` 字段集合逐位一致）。

    ``episode_id`` 用全局唯一键 game_id*8+seat；可选字段（动作序列 / 教师 / 过程价值 /
    行为混合）只在非 None 时写，保证默认关闭时字段集合与旧版本一致。
    """
    arrays: Dict[str, np.ndarray] = {
        "features": batch.features, "cards": batch.cards, "masks": batch.masks,
        "actions": batch.actions, "old_logprobs": batch.old_logprobs,
        "values": batch.values, "rewards": batch.rewards, "dones": batch.dones,
        "advantages": batch.advantages, "returns": batch.returns,
        "seats": batch.seats, "game_ids": batch.game_ids, "ranks": batch.ranks,
        "turns": batch.turns, "forced": batch.forced, "has_pi": batch.has_pi,
        "episode_ids": (batch.game_ids * 8 + batch.seats).astype(np.int64),
        "target_pi": (batch.target_pi if batch.target_pi is not None
                      else np.zeros((len(batch.actions), 245), np.float32)),
    }
    if getattr(batch, "seq_target", None) is not None:
        arrays["seq_target"] = batch.seq_target
    if getattr(batch, "teacher_action", None) is not None:
        arrays["teacher_action"] = batch.teacher_action
    if getattr(batch, "process_target", None) is not None:
        arrays["process_target"] = batch.process_target
    if getattr(batch, "behavior_logprobs", None) is not None:
        arrays["behavior_logprobs"] = batch.behavior_logprobs
        if getattr(batch, "pi_logprobs", None) is not None:
            arrays["pi_logprobs"] = batch.pi_logprobs
    return arrays


def _cast_records_dtype(arrays: Dict[str, np.ndarray], dtype: str) -> Dict[str, Any]:
    """按 ``--records-dtype`` 降低存储精度（默认 fp32 = 原样返回同一个对象）。"""
    if str(dtype).strip().lower() != "fp16":
        return arrays
    out: Dict[str, Any] = dict(arrays)
    for k in _RECORDS_FP16_KEYS:
        v = out.get(k)
        if v is None:
            continue
        a = np.asarray(v)
        if a.dtype == np.float32:
            out[k] = _cast_fp16(a)
    return out


def _upcast_records(arrays: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """父进程读入后立刻把 fp16 还原成 fp32（下游只看到 fp32，与旧路径同 dtype）。

    ⚠️ 返回的非 fp16 字段是**原数组本身**（shm 情形下是段内视图）；父进程必须在
    ``np.concatenate``/``packed_all.clear()`` 之后才 close 段。
    """
    out: Dict[str, np.ndarray] = {}
    for k, v in arrays.items():
        a = np.asarray(v)
        out[k] = _cast_fp32(a) if a.dtype == np.float16 else a
    return out


def _save_built_batch(batch: Any, path: str, *, dtype: str = "fp32") -> None:
    """把已构建的 PPOBatch 写成 npz（兼容旧签名；``dtype`` 默认 fp32 = 逐位等价）。"""
    np.savez(path, **_cast_records_dtype(_batch_arrays(batch), dtype))


def _shm_close_slot(slots: Dict[int, Any], slot_idx: int) -> None:
    """关闭并 unlink 一个 slot；父进程仍 attach 时 unlink 也安全（Linux 语义）。"""
    seg = slots.pop(int(slot_idx), None)
    if seg is None:
        return
    try:
        seg.close()
    except BufferError:            # 还有 numpy 视图/内存视图在用：交给进程退出回收
        pass
    except BaseException:          # noqa: BLE001
        pass
    try:
        seg.unlink()
    except BaseException:          # noqa: BLE001 - 别的进程已 unlink / 不存在
        pass


def _shm_state_cleanup(index: int) -> None:
    """worker 退出（stop / 心跳失败）时释放自己所有 slot。"""
    st = _SHM_STATE.pop(int(index), None)
    if not st:
        return
    for slot in list((st.get("slots") or {}).keys()):
        _shm_close_slot(st["slots"], slot)


def _shm_put(arrays: Dict[str, np.ndarray], *, slots: Dict[int, Any], slot_idx: int,
             name: str) -> Dict[str, Any]:
    """把 ``arrays`` 写进 ``name`` 的 shm slot（按需创建/扩容），返回段元数据。

    布局：``[0, _SHM_HEADER)`` = JSON 头部（字段名/dtype/shape/offset/nbytes），
    ``[_SHM_HEADER, _SHM_HEADER+nbytes)`` = 各数组的原始字节（C 顺序）。
    父进程用 ``np.frombuffer`` 直接映射，**零拷贝**（不再走 npz 的 zip 读写）。
    """
    from multiprocessing import shared_memory

    items: List[Dict[str, Any]] = []
    contig: Dict[str, np.ndarray] = {}
    off = 0
    for k in sorted(arrays):
        a = np.ascontiguousarray(np.asarray(arrays[k]))
        if a.dtype == object:
            raise TypeError(f"shm 不支持 object 数组: {k}")
        items.append({"name": k, "dtype": a.dtype.str, "shape": list(a.shape),
                      "nbytes": int(a.nbytes), "offset": int(off)})
        contig[k] = a
        off += int(a.nbytes)
    header = json.dumps({"keys": items}).encode("utf-8")
    if len(header) > _SHM_HEADER:
        raise RuntimeError(f"shm 头部超限：{len(header)} > {_SHM_HEADER}")
    need = _SHM_HEADER + off
    size = max(_SHM_ROUND, int((need + _SHM_ROUND - 1) // _SHM_ROUND) * _SHM_ROUND)
    seg = slots.get(int(slot_idx))
    if seg is not None and int(seg.size) < size:
        _shm_close_slot(slots, int(slot_idx))
        seg = None
    if seg is None:
        seg = shared_memory.SharedMemory(name=name, create=True, size=size)
        slots[int(slot_idx)] = seg
    buf = seg.buf
    buf[:_SHM_HEADER] = bytes(_SHM_HEADER)      # 清掉上一轮 JSON 尾巴
    buf[:len(header)] = header
    for it in items:
        a = contig[it["name"]]
        n = int(a.size)
        if n:
            dst = np.frombuffer(buf, dtype=a.dtype, count=n,
                                offset=_SHM_HEADER + int(it["offset"]))
            dst[...] = a.reshape(-1)
    return {"name": name, "size": int(seg.size), "header": int(_SHM_HEADER),
            "nbytes": int(off), "n_arrays": int(len(items)),
            "dtype": str(items[0]["dtype"]) if items else ""}


def _shm_read(meta: Dict[str, Any]) -> Tuple[Dict[str, np.ndarray], Any]:
    """父进程 attach 一个 shm slot，返回 ``(数组字典, segment)``。

    返回的数组是 shm 的**视图**；调用方必须等 ``np.concatenate`` 之后才能 close，
    否则会抛 ``BufferError``（这是刻意的护栏，不是错误）。
    """
    from multiprocessing import shared_memory

    seg = shared_memory.SharedMemory(name=str(meta["name"]))
    buf = seg.buf
    hb = int(meta.get("header", _SHM_HEADER))
    raw = bytes(buf[:hb]).rstrip(b"\x00")
    if not raw:
        raise RuntimeError(f"shm 头部为空: {meta.get('name')}")
    header = json.loads(raw.decode("utf-8"))
    out: Dict[str, np.ndarray] = {}
    for it in header["keys"]:
        dt = np.dtype(it["dtype"])
        shape = tuple(int(x) for x in it["shape"])
        count = 1
        for x in shape:
            count *= x
        arr = np.frombuffer(buf, dtype=dt, count=count,
                            offset=hb + int(it["offset"]))
        out[str(it["name"])] = arr.reshape(shape) if shape else arr
    return out, seg


def _emit_records(arrays: Dict[str, np.ndarray], *, ipc_mode: str,
                  records_dtype: str, records_file: Optional[str] = None,
                  shm_name: Optional[str] = None,
                  slots: Optional[Dict[int, Any]] = None,
                  slot_idx: int = 0) -> Optional[Dict[str, Any]]:
    """统一的 records 出口：``ipc_mode=shm`` → 共享内存；否则 → npz 落盘。

    两条路径都先过 ``_cast_records_dtype``，保证 ``--records-dtype`` 对两种 IPC 同效。
    """
    arrays = _cast_records_dtype(arrays, records_dtype)
    if str(ipc_mode).strip().lower() == "shm":
        if not shm_name or slots is None:
            raise RuntimeError("ipc_mode=shm 需要 shm_name 与 slots")
        return _shm_put(arrays, slots=slots, slot_idx=slot_idx, name=shm_name)
    if not records_file:
        raise RuntimeError("ipc_mode=disk 需要 records_file")
    np.savez(records_file, **arrays)
    return None


def _shm_owner_path(tag: str) -> str:
    """pool 的「主人」标记文件：内容是父进程 pid（崩溃/被杀后靠它精确清理）。"""
    return os.path.join("/dev/shm", f"{_SHM_PREFIX}{tag}.owner")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _purge_stale_shm(max_age_s: float = _SHM_STALE_S) -> int:
    """清掉**主人已死**的 pool 的 shm 段；无 owner 的孤儿段按 mtime 兜底。

    只碰 ``_SHM_PREFIX`` 前缀。trainer 被 SIGTERM/SIGKILL 杀掉时 worker 不会 unlink，
    这里按 owner 文件里的 pid 存活与否判断，避免 6h 前一直占着 /dev/shm。
    """
    base = "/dev/shm"
    if not os.path.isdir(base):
        return 0
    now = time.time()
    removed = 0
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    # 1) owner 文件：主人已死 -> 整族删除（段名 = {prefix}{tag}_w{i}_s{slot}）
    for name in names:
        if not name.startswith(_SHM_PREFIX) or not name.endswith(".owner"):
            continue
        owner = os.path.join(base, name)
        tag = name[len(_SHM_PREFIX):-len(".owner")]
        try:
            with open(owner, "r", encoding="utf-8") as f:
                pid = int((f.read() or "0").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if _pid_alive(pid):
            continue
        for nm in names:
            if nm.startswith(f"{_SHM_PREFIX}{tag}_"):
                try:
                    os.unlink(os.path.join(base, nm))
                    removed += 1
                except OSError:
                    pass
        try:
            os.unlink(owner)
        except OSError:
            pass
    # 2) 没有 owner 的孤儿段：按 mtime 兜底（默认 6 小时）
    for name in os.listdir(base):
        if not name.startswith(_SHM_PREFIX) or name.endswith(".owner"):
            continue
        p = os.path.join(base, name)
        try:
            if now - os.path.getmtime(p) < float(max_age_s):
                continue
            os.unlink(p)
            removed += 1
        except OSError:
            pass
    return removed


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
    # records 数据通路（在 spawn payload 里钉死，采集任务不再逐个传）
    ipc_mode = str(payload.get("ipc_mode", "disk")).strip().lower()
    records_dtype = str(payload.get("records_dtype", "fp32"))
    shm_slots = max(1, int(payload.get("shm_slots", _SHM_SLOTS)))
    shm_tag = str(payload.get("shm_tag", "pool"))
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
            # ── 搜索作为行为策略（默认 eps=0 -> behavior_mix=None，零开销）──
            behavior_mix = None
            _bm_eps = float(getattr(cfg, "behavior_mix_eps", 0.0) or 0.0)
            if _bm_eps > 0.0:
                if not bool(task.get("lockstep", False)):
                    raise RuntimeError(
                        "--behavior-mix-eps>0 只支持 --lockstep 1 采集路径"
                        "（混合行为策略需要 lockstep 采集器在决策点调用搜索）")
                if str(getattr(cfg, "behavior", "net")).strip().lower() != "net":
                    raise RuntimeError(
                        "--behavior-mix-eps>0 需要 --behavior net（μ 的网络分量是 π）")
                from .infer_search import InferSearchConfig, InferSearcher
                from .behavior_mix import BehaviorMixConfig, BehaviorMixer
                _key = (int(task["seed"]), str(cfg.behavior_mix_when),
                        int(cfg.behavior_mix_topk), int(cfg.behavior_mix_turns),
                        int(cfg.behavior_mix_max_per_turn),
                        float(cfg.behavior_mix_max_ms),
                        int(getattr(cfg, "behavior_mix_exact", 1)))
                _searcher = _MIX_SEARCHERS.get(_key)
                if _searcher is None:
                    _scfg = InferSearchConfig(
                        enabled=1, turns=int(cfg.behavior_mix_turns),
                        max_searches_per_turn=int(cfg.behavior_mix_max_per_turn),
                        topk=int(cfg.behavior_mix_topk),
                        search_when=str(cfg.behavior_mix_when),
                        action="pi_argmax", pi_mode="advantage", adv_clip=30.0,
                        max_ms_per_search=float(cfg.behavior_mix_max_ms),
                        seed=int(task["seed"])).validate()
                    _searcher = InferSearcher(evaluator, _scfg, n_players=N_PLAYERS)
                    _MIX_SEARCHERS[_key] = _searcher
                behavior_mix = BehaviorMixer(
                    _searcher,
                    BehaviorMixConfig(
                        eps=_bm_eps, when=str(cfg.behavior_mix_when),
                        max_per_turn=int(cfg.behavior_mix_max_per_turn),
                        topk=int(cfg.behavior_mix_topk),
                        turns=int(cfg.behavior_mix_turns),
                        max_ms=float(cfg.behavior_mix_max_ms),
                        exact=int(getattr(cfg, "behavior_mix_exact", 1)),
                        seed=int(task["seed"])),
                    n_players=N_PLAYERS)
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
                    path = str(cfg.library_pool)
                    mtime = os.path.getmtime(path) if os.path.isfile(path) else 0.0
                    cached = _LIB_CACHE.get(path)
                    if cached is None or cached[0] != mtime:   # 热加载：文件更新即重读
                        lib = LibraryPool(path) if mtime else None
                        _LIB_CACHE[path] = (mtime, lib)
                        if lib is None or not lib.entries:
                            print(f"[warn] 镜像库为空/不存在: {path}", flush=True)
                    else:
                        lib = cached[1]
                    if lib is not None and not lib.entries:
                        lib = None
                if lib is None and str(getattr(cfg, "library_pool", "")) and \
                        float(getattr(cfg, "library_p", 0.0)) > 0.0:
                    print("[warn] library_pool 已设置但库为空/路径无效：本次将退回纯 bot 对手",
                          flush=True)
                tpool = None
                if str(getattr(cfg, "trajectory_pool", "")) and \
                        float(getattr(cfg, "trajectory_p", 0.0)) > 0.0:
                    from .trajectory_pool import TrajectoryPool
                    tdir = str(cfg.trajectory_pool)
                    if os.path.isdir(tdir):
                        files = [os.path.join(tdir, f) for f in os.listdir(tdir) if f.endswith(".json.gz")]
                        tkey = (len(files),
                                max((os.path.getmtime(f) for f in files), default=0.0))
                    else:
                        tkey = None
                    cached = _TRAJ_CACHE.get(tdir)
                    if cached is None or cached[0] != tkey:
                        tpool = TrajectoryPool(tdir) if tkey is not None else None
                        _TRAJ_CACHE[tdir] = (tkey, tpool)
                        if tpool is None or not tpool.items:
                            print(f"[warn] 轨迹库为空/不存在: {tdir}", flush=True)
                    else:
                        tpool = cached[1]
                    if tpool is not None and not tpool.items:
                        tpool = None
                # 回合末场面快照镜像库（--mirror-snaps/--mirror-p/--mirror-p-ramp；默认关闭）
                mpool = None
                if str(getattr(cfg, "mirror_snaps", "")) and (
                        float(getattr(cfg, "mirror_p", 0.0)) > 0.0 or
                        str(getattr(cfg, "mirror_p_ramp", "")).strip()):
                    from .mirror_snapshots import load_pool as _load_mirror
                    mdir = str(cfg.mirror_snaps)
                    msample = str(getattr(cfg, "mirror_sample", "p50") or "p50")
                    if os.path.isdir(mdir):
                        mfiles = [os.path.join(mdir, f) for f in os.listdir(mdir)
                                  if f.endswith(".json.gz")]
                        mkey = (len(mfiles),
                                max((os.path.getmtime(f) for f in mfiles), default=0.0))
                    else:
                        mkey = None
                    cache_key = (mdir, msample)
                    cached = _MIRROR_CACHE.get(cache_key)
                    if cached is None or cached[0] != mkey:
                        mpool = _load_mirror(mdir, sample=msample) if mkey is not None else None
                        _MIRROR_CACHE[cache_key] = (mkey, mpool)
                        if mpool is None:
                            print(f"[warn] 回合末快照库为空/不存在: {mdir}", flush=True)
                    else:
                        mpool = cached[1]
                # 人类战团（board-only）注入库（--human-boards/--human-board-p；默认关闭）。
                # 与镜像快照可同时开：同座位同回合镜像优先（引擎里镜像座位已 ended_turn）。
                hpool = None
                if str(getattr(cfg, "human_boards", "")) and \
                        float(getattr(cfg, "human_board_p", 0.0)) > 0.0:
                    from .human_board_pool import load_pool as _load_human
                    hpath = str(cfg.human_boards)
                    hsample = str(getattr(cfg, "human_board_sample", "auto") or "auto")
                    if os.path.isfile(hpath):
                        hkey = os.path.getmtime(hpath)
                    else:
                        hkey = None
                    hck = (hpath, hsample)
                    cached = _HUMAN_BOARD_CACHE.get(hck)
                    if cached is None or cached[0] != hkey:
                        hpool = _load_human(hpath, sample=hsample) if hkey is not None else None
                        _HUMAN_BOARD_CACHE[hck] = (hkey, hpool)
                        if hpool is None:
                            print(f"[warn] 人类战团库为空/不存在: {hpath}", flush=True)
                    else:
                        hpool = cached[1]
                opp_pol = None
                fck = str(getattr(cfg, "frozen_opponent", "") or "")
                if fck:
                    key = (fck, os.path.getmtime(fck) if os.path.isfile(fck) else 0.0)
                    cached_pol = _OPP_CACHE.get(key)
                    if cached_pol is None:
                        from .model import load_checkpoint as _load_ckpt
                        om, ometa = _load_ckpt(fck, device=device)
                        opp_pol = PPOSelfPlayPolicy(
                            om, device=device, config=cfg, search_fn=None,
                            search_config=None, eval_fn=evaluator,
                            engine_backend="auto", seed=int(task["seed"]) + 31,
                            norm_mean=ometa.get("norm_mean"),
                            norm_std=ometa.get("norm_std"), move_model=False)
                        _OPP_CACHE[key] = opp_pol
                    else:
                        opp_pol = cached_pol
                records, cmeta = collect_ppo_lockstep(
                    model, cfg, eval_fn=evaluator, device=device,
                    seed=int(task["seed"]), games=int(cfg.games),
                    gamemode=str(cfg.opponent), norm_mean=norm_mean,
                    norm_std=norm_std, library_pool=lib,
                    library_p=float(getattr(cfg, "library_p", 0.0)),
                    trajectory_pool=tpool,
                    trajectory_p=float(getattr(cfg, "trajectory_p", 0.0)),
                    mirror_pool=mpool,
                    mirror_seats_count=int(getattr(cfg, "mirror_seats", 0)),
                    mirror_p=float(getattr(cfg, "mirror_p", 0.0)),
                    mirror_p_ramp=str(getattr(cfg, "mirror_p_ramp", "")),
                    mirror_seat_random=bool(getattr(cfg, "mirror_seat_random", False)),
                    human_board_pool=hpool,
                    human_board_p=float(getattr(cfg, "human_board_p", 0.0)),
                    human_board_seats=int(getattr(cfg, "human_board_seats", 2)),
                    human_board_sample=str(getattr(cfg, "human_board_sample", "auto")),
                    human_board_set_tier=bool(getattr(cfg, "human_board_set_tier", True)),
                    human_board_fidelity=str(getattr(cfg, "human_board_fidelity", "board")),
                    human_board_fast_inject=bool(
                        getattr(cfg, "human_board_fast_inject", False)),
                    gamma=float(task.get("gamma", 1.0)),
                    opponent_policy=opp_pol,
                    behavior_mix=behavior_mix)
            else:
                if str(getattr(cfg, "library_pool", "")) and \
                        float(getattr(cfg, "library_p", 0.0)) > 0.0:
                    print("[warn] 镜像库目前只在 --lockstep 1 路径生效，本次请求被忽略",
                          flush=True)
                if str(getattr(cfg, "mirror_snaps", "")) and (
                        float(getattr(cfg, "mirror_p", 0.0)) > 0.0 or
                        str(getattr(cfg, "mirror_p_ramp", "")).strip()):
                    print("[warn] 回合末快照镜像只在 --lockstep 1 路径生效，本次请求被忽略",
                          flush=True)
                if str(getattr(cfg, "human_boards", "")) and \
                        float(getattr(cfg, "human_board_p", 0.0)) > 0.0:
                    print("[warn] 人类战团注入只在 --lockstep 1 路径生效，本次请求被忽略",
                          flush=True)
                records, cmeta = collect_ppo_records_parallel(
                    model, cfg, workers=int(task.get("threads", 4)),
                    search_fn=search_fn,
                    search_config=(_search_config(int(task["seed"])) if search_fn else None),
                    eval_fn=evaluator, device=device, seed=int(task["seed"]),
                    gamma=float(task.get("gamma", 1.0)),
                    norm_mean=norm_mean, norm_std=norm_std, progress=False)
            _collect_s = time.time() - t0
            records_file = None
            shm_meta = None
            n_records = int(len(records))
            _ipc = ipc_mode
            _dtype = records_dtype
            _slots_state = _SHM_STATE.setdefault(index, {"slots": {}, "seq": 0})
            if bool(task.get("return_records", True)):
                # L4：worker 内构建 batch（排序/过滤/GAE 并行化）；episode_id 用
                # (game_id*8+seat) 作为全局唯一键，父进程直接拼接、无需重编号
                if _ipc == "shm":
                    # 环形 slot：第 k 轮用 slot k%N，父进程读第 k 轮时 worker 可写第 k+1 轮
                    _n_slots = max(1, int(shm_slots))
                    _slot_idx = int(_slots_state["seq"]) % _n_slots
                    _slots_state["seq"] = int(_slots_state["seq"]) + 1
                    _shm_name = (f"{_SHM_PREFIX}{shm_tag}"
                                 f"_w{index}_s{_slot_idx}")
                else:
                    _slot_idx = 0
                    _shm_name = None
                    records_file = os.path.join(
                        task["tmpdir"], f"rec_{task_id}_w{index}.npz")
                if bool(task.get("rust_collector", False)) and search_fn is None:
                    _arrays = _batch_arrays(build_batch_from_arrays(
                        arr, gamma=float(task.get("gamma", 1.0)),
                        lam=float(task.get("lam", 0.95)),
                        adv_estimator=str(task.get("adv_estimator", "gae")),
                        power_alpha=float(task.get("power_alpha", 0.5)),
                        power_kappa=float(task.get("power_kappa", 3.0)),
                        power_normalize=bool(task.get("power_normalize", True)),
                        power_cutoff=int(task.get("power_cutoff", 0)),
                        credit_timebase=str(task.get("credit_timebase", "decision")),
                        rank_utility_coef=float(task.get("rank_utility_coef", 1.0)),
                        terminal_strength_coef=float(
                            task.get("terminal_strength_coef", 0.0))))
                else:
                    packed = pack_records_arrays(
                        records, seq_aux=bool(getattr(cfg, "seq_aux", False)))
                    try:
                        _arrays = _batch_arrays(build_batch_from_arrays(
                            packed, gamma=float(task.get("gamma", 1.0)),
                            lam=float(task.get("lam", 0.95)),
                            adv_estimator=str(task.get("adv_estimator", "gae")),
                            power_alpha=float(task.get("power_alpha", 0.5)),
                            power_kappa=float(task.get("power_kappa", 3.0)),
                            power_normalize=bool(task.get("power_normalize", True)),
                            power_cutoff=int(task.get("power_cutoff", 0)),
                            credit_timebase=str(task.get("credit_timebase", "decision")),
                            rank_utility_coef=float(task.get("rank_utility_coef", 1.0)),
                            terminal_strength_coef=float(
                                task.get("terminal_strength_coef", 0.0))))
                    except BaseException:  # noqa: BLE001 - 回退到父进程构建
                        _arrays = dict(packed)
                shm_meta = _emit_records(
                    _arrays, ipc_mode=_ipc, records_dtype=_dtype,
                    records_file=records_file, shm_name=_shm_name,
                    slots=_slots_state["slots"], slot_idx=_slot_idx)
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
                "records_file": records_file, "records_shm": shm_meta,
                "records_dtype": _dtype, "ipc_mode": _ipc,
                "records": n_records,
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
    # 释放本 worker 的 shm 段（父进程若还在读，unlink 不影响其已 attach 的映射）
    try:
        _shm_state_cleanup(index)
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
                 python: Optional[str] = None,
                 ipc_mode: Optional[str] = None,
                 records_dtype: Optional[str] = None,
                 shm_slots: int = 0,
                 collect_sha: bool = False) -> None:
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
        # 环境变量兜底：不（或还没）接 CLI 开关的调用方也能开；默认值 = 历史行为。
        _env_ipc = os.environ.get("HSBRSIM_IPC_MODE", "").strip().lower()
        _env_dtype = os.environ.get("HSBRSIM_RECORDS_DTYPE", "").strip().lower()
        _env_slots = os.environ.get("HSBRSIM_IPC_SHM_SLOTS", "").strip()
        #: records 数据通路：disk=npz 落盘（默认，历史路径）；shm=/dev/shm 环形 buff
        self.ipc_mode = str(ipc_mode or _env_ipc or "disk").strip().lower()
        if self.ipc_mode not in ("disk", "shm"):
            raise ValueError(f"ipc_mode 必须是 disk/shm，收到 {ipc_mode!r}")
        #: records 存储精度：fp32=原样（默认，逐位等价）；fp16=只把 features 降精度
        self.records_dtype = str(records_dtype or _env_dtype or "fp32").strip().lower()
        if self.records_dtype not in ("fp32", "fp16"):
            raise ValueError(f"records_dtype 必须是 fp32/fp16，收到 {records_dtype!r}")
        self.shm_slots = max(1, int(shm_slots or (int(_env_slots) if _env_slots else _SHM_SLOTS)))
        #: 1=把每个 iteration 采集批次的动作流 sha256 写进 collect meta（默认 0）
        self.collect_sha = bool(collect_sha) or \
            os.environ.get("HSBRSIM_COLLECT_SHA", "0").strip() == "1"
        if self.ipc_mode == "shm" and not os.path.isdir("/dev/shm"):
            raise RuntimeError("--ipc-mode shm 需要 /dev/shm（本机不存在）")
        self.tmpdir = str(tmpdir or os.path.join(
            os.path.dirname(os.path.abspath(checkpoint)) or ".", "_proc_pool"))
        os.makedirs(self.tmpdir, exist_ok=True)
        #: 本 pool 实例的 shm 段名后缀（多 pool/多 run 并存时互不覆盖）
        self.shm_tag = uuid.uuid4().hex[:8]
        #: 父进程见过/attach 过的 shm 段名（close 时兜底 unlink）
        self._shm_names: set = set()
        #: 父进程当前仍 attach 的 segment（拼接完才能 close）
        self._shm_open: List[Any] = []
        self.shm_purged = _purge_stale_shm() if self.ipc_mode == "shm" else 0
        if self.ipc_mode == "shm":
            try:
                with open(_shm_owner_path(self.shm_tag), "w", encoding="utf-8") as f:
                    f.write(str(os.getpid()))
            except OSError:
                pass
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
            "ipc_mode": self.ipc_mode, "records_dtype": self.records_dtype,
            "shm_slots": self.shm_slots, "shm_tag": self.shm_tag,
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

    def _close_shm(self) -> None:
        """释放父进程本轮 attach 的所有 shm 段（数组早已 concat 成独立内存）。"""
        while self._shm_open:
            seg = self._shm_open.pop()
            try:
                seg.close()
            except BufferError:          # 还有视图在用：交给进程退出/下一轮
                self._shm_open.append(seg)
                break
            except BaseException:        # noqa: BLE001
                pass

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
        self._close_shm()
        # 兜底：worker 正常退出会自己 unlink；崩溃/被 terminate 的由父进程按名字清理
        for name in list(self._shm_names):
            try:
                from multiprocessing import shared_memory
                shared_memory.SharedMemory(name=name).unlink()
            except BaseException:  # noqa: BLE001
                pass
        self._shm_names.clear()
        # 最后删 owner 标记（之后即使本进程被杀，也不会有人把它当成活 pool）
        try:
            os.unlink(_shm_owner_path(self.shm_tag))
        except OSError:
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
                adv_estimator: str = "gae",
                power_alpha: float = 0.5,
                power_kappa: float = 3.0,
                power_normalize: bool = True,
                power_cutoff: int = 0,
                credit_timebase: str = "decision",
                rank_utility_coef: float = 1.0,
                terminal_strength_coef: float = 0.0,
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
                "adv_estimator": str(adv_estimator),
                "power_alpha": float(power_alpha),
                "power_kappa": float(power_kappa),
                "power_normalize": bool(power_normalize),
                "power_cutoff": int(power_cutoff),
                "credit_timebase": str(credit_timebase),
                "rank_utility_coef": float(rank_utility_coef),
                "terminal_strength_coef": float(terminal_strength_coef),
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
        t_read = records_bytes = shm_slabs = 0.0
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
            shm = msg.get("records_shm")
            if shm:
                # shm 通路：attach + 零拷贝视图；读入后立刻 upcast 成 fp32（下游 dtype 不变）
                t_r0 = time.time()
                _arrs, _seg = _shm_read(shm)
                packed_all.append(_upcast_records(_arrs))
                self._shm_open.append(_seg)
                self._shm_names.add(str(shm.get("name")))
                t_read += time.time() - t_r0
                records_bytes += float(shm.get("nbytes", 0) or 0)
                shm_slabs += float(shm.get("size", 0) or 0)
            elif f:
                t_r0 = time.time()
                if f.endswith(".npz"):
                    with np.load(f) as z:
                        packed_all.append(_upcast_records({k: z[k] for k in z.files}))
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
            "ipc_mode": self.ipc_mode,
            "records_dtype": self.records_dtype,
            "shm_slots": int(self.shm_slots),
            "shm_slabs": int(shm_slabs),
            "workers": profiles,
            "worker_meta": to_jsonable(metas),
            "elapsed_s": wall,
        }
        # 注入计数（mirror_* / human_board_*）：worker meta 逐 shard 回传，父进程按
        # 「计数 sum / 开关 any / p mean」聚合到 collect 段顶层（history 可直接验证生效）。
        meta.update(aggregate_injection(metas))
        # 势函数塑形统计：worker meta（lockstep/逐局）逐 shard 回传，父进程汇总。
        meta.update(aggregate_shaping(metas, elapsed_s=wall))
        # 等级进度奖励统计：同样逐 shard 汇总（默认关闭 -> 空 dict，不新增键）。
        meta.update(aggregate_tier_target(metas))
        # 换位去抖守卫：逐 shard 汇总（默认关闭 -> 空 dict，不新增键）。
        meta.update(aggregate_move_guard(metas))
        meta.update(aggregate_archetype_bias(metas))
        # 搜索行为混合（默认关闭 -> 空 dict，不新增键）：worker meta 逐 shard 汇总。
        _bm_agg = aggregate_behavior_mix(metas)
        if _bm_agg:
            meta["behavior_mix"] = _bm_agg
        # 缩放课程 / 教师 / 过程价值（默认关闭 -> 不新增键）
        if any(str(m.get("curriculum_stage", "none")) != "none" for m in metas):
            meta["curriculum_stage"] = str(
                (metas[0] or {}).get("curriculum_stage", "none"))
            meta["curriculum_gold_mult"] = float(
                (metas[0] or {}).get("curriculum_gold_mult", 1.0))
            meta["curriculum_gold_turns"] = int(sum(
                int(m.get("curriculum_gold_turns", 0) or 0) for m in metas))
            meta["curriculum_gold_extra"] = int(sum(
                int(m.get("curriculum_gold_extra", 0) or 0) for m in metas))
        if any(bool(m.get("teacher_bc", False)) for m in metas):
            meta["teacher_bc"] = True
            meta["teacher_labels"] = int(sum(
                int(m.get("teacher_labels", 0) or 0) for m in metas))
        if any(bool(m.get("process_value", False)) for m in metas):
            meta["process_value"] = True
            meta["process_labels"] = int(sum(
                int(m.get("process_labels", 0) or 0) for m in metas))
        if not records and not packed_all:
            # 采集侧没有有效记录（全部截断/非法），保持与单进程一致的报错语义
            self._close_shm()
            raise RuntimeError(
                f"process pool 无有效轨迹（truncated={agg['truncated']}, "
                f"invalid={agg['invalid']}, decisions={agg['decisions']}）")
        timeline["t_read_done"] = time.monotonic()
        t_b0 = time.time()
        # 统一协议：任何 shard 回退成 raw SoA 时，父进程先把它补齐成 batch 再合并
        for i, p in enumerate(packed_all):
            if "advantages" not in p:
                lb = build_batch_from_arrays(
                    p, gamma=float(gamma), lam=float(lam),
                    adv_estimator=str(adv_estimator),
                    power_alpha=float(power_alpha),
                    power_kappa=float(power_kappa),
                    power_normalize=bool(power_normalize),
                    power_cutoff=int(power_cutoff),
                    credit_timebase=str(credit_timebase),
                    rank_utility_coef=float(rank_utility_coef),
                    terminal_strength_coef=float(terminal_strength_coef))
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
                if getattr(lb, "seq_target", None) is not None:
                    packed_all[i]["seq_target"] = lb.seq_target
                if getattr(lb, "teacher_action", None) is not None:
                    packed_all[i]["teacher_action"] = lb.teacher_action
                if getattr(lb, "process_target", None) is not None:
                    packed_all[i]["process_target"] = lb.process_target
                if getattr(lb, "behavior_logprobs", None) is not None:
                    packed_all[i]["behavior_logprobs"] = lb.behavior_logprobs
                    if getattr(lb, "pi_logprobs", None) is not None:
                        packed_all[i]["pi_logprobs"] = lb.pi_logprobs
        if packed_all and all("advantages" in p for p in packed_all):
            # L4：worker 已构建好 batch（episode_id 全局唯一）→ 父进程只拼接
            keys = ["features", "cards", "masks", "actions", "old_logprobs", "values",
                    "rewards", "dones", "advantages", "returns", "seats", "game_ids",
                    "ranks", "turns", "forced", "has_pi", "episode_ids", "target_pi"]
            # 可选字段：所有 shard 都带才拼接（动作序列 / 教师 / 过程价值 / 行为混合；
            # 默认关闭时全都没有）
            keys += [k for k in ("seq_target", "teacher_action", "process_target",
                                 "behavior_logprobs", "pi_logprobs")
                     if all(k in p for p in packed_all)]
            merged = {k: np.concatenate([p[k] for p in packed_all], axis=0) for k in keys}
            meta["episodes"] = int(len(np.unique(merged["episode_ids"])))
            meta["built_in"] = "worker"
            batch = PPOBatch(**merged, meta=meta)
        elif packed_all:
            merged = {k: np.concatenate([p[k] for p in packed_all if k in p], axis=0)
                      for k in packed_all[0]}
            batch = build_batch_from_arrays(
                merged, gamma=float(gamma), lam=float(lam), meta=meta,
                adv_estimator=str(adv_estimator),
                power_alpha=float(power_alpha),
                power_kappa=float(power_kappa),
                power_normalize=bool(power_normalize),
                power_cutoff=int(power_cutoff),
                credit_timebase=str(credit_timebase),
                rank_utility_coef=float(rank_utility_coef),
                terminal_strength_coef=float(terminal_strength_coef))
        else:
            batch = build_batch_from_records(
                records, gamma=float(gamma), lam=float(lam), meta=meta,
                adv_estimator=str(adv_estimator),
                power_alpha=float(power_alpha),
                power_kappa=float(power_kappa),
                power_normalize=bool(power_normalize),
                power_cutoff=int(power_cutoff),
                credit_timebase=str(credit_timebase),
                rank_utility_coef=float(rank_utility_coef),
                terminal_strength_coef=float(terminal_strength_coef))
        build_batch_s = time.time() - t_b0
        # 拼接/建批都是**拷贝**（np.concatenate / v[order]）；清掉 packed_all 里的 shm 视图
        # 之后再释放段，否则 numpy 视图还引用着 buf（close 会抛 BufferError）。
        packed_all.clear()
        self._close_shm()
        # 动作流 sha：默认关闭（history 字段与旧版一致）；开启后写进 collect meta
        if self.collect_sha:
            _h = hashlib.sha256()
            for _arr in (batch.actions, batch.turns, batch.game_ids, batch.seats):
                _h.update(np.ascontiguousarray(_arr).tobytes())
            meta["action_sha"] = _h.hexdigest()[:16]
        if str(adv_estimator).strip().lower() != "gae":
            # 默认 gae 不新增键；启用时记录核参数（逐 shard diagnostics 已在
            # worker build 时用 compact_diagnostics 摘要，这里只回传有效配置）。
            meta["adv_estimator"] = str(adv_estimator).strip().lower()
            meta["credit"] = {
                "alpha": float(power_alpha), "kappa": float(power_kappa),
                "normalize": bool(power_normalize), "cutoff": int(power_cutoff),
                "timebase": str(credit_timebase),
            }
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
                "ipc_mode": self.ipc_mode, "records_dtype": self.records_dtype,
                "shm_slots": int(self.shm_slots), "shm_tag": self.shm_tag,
                "shm_purged": int(self.shm_purged), "collect_sha": bool(self.collect_sha),
                "restarts": self.restarts, "workers": self._info}


__all__ = ["ProcessActorPool"]
