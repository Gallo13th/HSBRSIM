"""Rust 全采集器的 Python 胶水：引擎/观测/记录/step 全在 Rust，Python 只做批量前向。

```python
arrays, meta = collect_ppo_rust(model, cfg, eval_fn=evaluator, seed=0, games=192)
```
返回的 SoA 字段与 `pack_records_arrays` 一致，可直接 `build_batch_from_arrays`。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .ppo import CollectConfig

N_OBS = 3227
N_CARDS = 124
N_ACTIONS = 245


def collect_ppo_rust(model: Any, cfg: CollectConfig, *, eval_fn: Any,
                     device: str = "cpu", seed: int = 0,
                     games: Optional[int] = None, threads: int = 1,
                     gamemode: str = "bot",
                     norm_mean: Any = None, norm_std: Any = None
                     ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """用 Rust `RustCollector` 采一批（N 局，每局一个学习座位）。"""
    from hsbg_engine import _core

    if str(gamemode) != "bot":
        raise ValueError(f"rust collector 只支持 bot 对手，收到 {gamemode!r}")
    if not hasattr(eval_fn, "act_batch"):
        raise RuntimeError("collect_ppo_rust 需要支持 act_batch 的 evaluator")

    t0 = time.time()
    n = int(games if games is not None else cfg.games)
    seat = int(cfg.learner_seat)
    limit = int(getattr(cfg, "max_actions_per_turn", 0) or 0)
    col = _core.RustCollector(n, seed=int(cfg.seed) + int(seed), seat=seat,
                              limit=limit, max_steps=int(cfg.max_steps),
                              threads=int(threads))
    temperature = float(getattr(cfg, "temperature", 1.0))
    rounds = 0
    while True:
        f_b, c_b, m_b, t_b, s_b = col.pending()
        k = len(s_b) // 8
        if k == 0:
            break
        f = np.frombuffer(f_b, dtype="<f4").reshape(k, N_OBS)
        c = np.frombuffer(c_b, dtype="<i4").reshape(k, N_CARDS)
        m = np.frombuffer(m_b, dtype=np.uint8).reshape(k, N_ACTIONS).astype(bool)
        a, lp, v = eval_fn.act_batch(f, c, m, temperature, seed=int(seed) + rounds)
        col.record_actions(np.ascontiguousarray(a, dtype="<i8").tobytes(),
                           np.ascontiguousarray(lp, dtype="<f4").tobytes(),
                           np.ascontiguousarray(v, dtype="<f4").tobytes())
        rounds += 1
        if col.all_finished():
            break

    d = col.finish()
    cnt = int(d["count"])
    arr = {
        "features": np.frombuffer(d["features"], dtype="<f4").reshape(-1, N_OBS).copy(),
        "cards": np.frombuffer(d["cards"], dtype="<i4").reshape(-1, N_CARDS).astype(np.int16),
        "masks": np.frombuffer(d["masks"], dtype=np.uint8).reshape(-1, N_ACTIONS).astype(bool),
        "actions": np.frombuffer(d["actions"], dtype="<i8").copy(),
        "old_logprobs": np.frombuffer(d["old_logprobs"], dtype="<f4").copy(),
        "values": np.frombuffer(d["values"], dtype="<f4").copy(),
        "ranks": np.frombuffer(d["ranks"], dtype="<i8").copy(),
        "seats": np.frombuffer(d["seats"], dtype="<i4").copy(),
        "game_ids": np.frombuffer(d["game_ids"], dtype="<i8").copy()
                     + int(cfg.game_id_offset),
        "turns": np.frombuffer(d["turns"], dtype="<i4").copy(),
        "forced": np.frombuffer(d["forced"], dtype=np.uint8).astype(bool),
        "has_pi": np.zeros(cnt, dtype=bool),
        "target_pi": np.zeros((0,), dtype=np.float32),
    }
    for k in ("features", "actions", "ranks", "seats", "game_ids", "turns", "forced"):
        arr[k] = arr[k][:cnt]
    meta = {
        "mode": "rust_collector",
        "games": n,
        "decisions": int(cnt),
        "rounds": int(d["rounds"]),
        "illegal_actions": int(d["illegal"]),
        "truncated_games": int((arr["ranks"] <= 0).sum() > 0),
        "forced_end_turns": int(arr["forced"].sum()),
        "wall_s": time.time() - t0,
    }
    return arr, meta


def collect_ppo_rust_multi(model: Any, cfg: CollectConfig, *, eval_fn: Any,
                           device: str = "cpu", seed: int = 0,
                           games: Optional[int] = None, shards: int = 4,
                           threads: int = 1, gamemode: str = "bot",
                           norm_mean: Any = None, norm_std: Any = None
                           ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """单进程内多个 RustCollector 共享一个前向服务（每个 shard 16 局左右）。

    多个 shard 各自 `pending()` 后由调用方合并成一个大 batch 一次前向，
    这样 batch = shards × games_per_shard 行（如 4×16=64），把每次前向 ~5 ms 的
    固定开销摊薄；引擎推进仍按 shard 独立。
    """
    from hsbg_engine import _core

    if str(gamemode) != "bot":
        raise ValueError(f"rust collector 只支持 bot 对手，收到 {gamemode!r}")
    if not hasattr(eval_fn, "act_batch"):
        raise RuntimeError("collect_ppo_rust_multi 需要支持 act_batch 的 evaluator")
    t0 = time.time()
    n = int(games if games is not None else cfg.games)
    shards = max(1, min(int(shards), n))
    base = n // shards
    counts = [base] * shards
    counts[-1] += n - base * shards
    seat = int(cfg.learner_seat)
    limit = int(getattr(cfg, "max_actions_per_turn", 0) or 0)
    cols = []
    offset = int(cfg.game_id_offset)
    for s, k in enumerate(counts):
        cols.append((_core.RustCollector(k, seed=int(cfg.seed) + int(seed) + s * 100003,
                                         seat=seat, limit=limit,
                                         max_steps=int(cfg.max_steps), threads=int(threads)),
                     offset, k))
        offset += k
    temperature = float(getattr(cfg, "temperature", 1.0))
    rounds = 0
    while True:
        parts = []
        for ci, (col, off, k) in enumerate(cols):
            f_b, c_b, m_b, t_b, s_b = col.pending()
            rows = len(s_b) // 8
            if rows == 0:
                continue
            parts.append((ci, rows,
                          np.frombuffer(f_b, dtype="<f4").reshape(rows, N_OBS),
                          np.frombuffer(c_b, dtype="<i4").reshape(rows, N_CARDS),
                          np.frombuffer(m_b, dtype=np.uint8).reshape(rows, N_ACTIONS)))
        if not parts:
            break
        F = np.concatenate([p[2] for p in parts], axis=0)
        C = np.concatenate([p[3] for p in parts], axis=0)
        M = np.concatenate([p[4] for p in parts], axis=0).astype(bool)
        a, lp, v = eval_fn.act_batch(F, C, M, temperature, seed=int(seed) + rounds)
        i = 0
        for ci, rows, *_ in parts:
            col = cols[ci][0]
            col.record_actions(np.ascontiguousarray(a[i:i + rows], dtype="<i8").tobytes(),
                               np.ascontiguousarray(lp[i:i + rows], dtype="<f4").tobytes(),
                               np.ascontiguousarray(v[i:i + rows], dtype="<f4").tobytes())
            i += rows
        rounds += 1
        if all(col.all_finished() for col, _, _ in cols):
            break

    arrs = []
    for ci, (col, off, k) in enumerate(cols):
        d = col.finish()
        cnt = int(d["count"])
        if cnt == 0:
            continue
        arrs.append({
            "features": np.frombuffer(d["features"], dtype="<f4").reshape(cnt, N_OBS).copy(),
            "cards": np.frombuffer(d["cards"], dtype="<i4").reshape(cnt, N_CARDS).astype(np.int16),
            "masks": np.frombuffer(d["masks"], dtype=np.uint8).reshape(cnt, N_ACTIONS).astype(bool),
            "actions": np.frombuffer(d["actions"], dtype="<i8").copy(),
            "old_logprobs": np.frombuffer(d["old_logprobs"], dtype="<f4").copy(),
            "values": np.frombuffer(d["values"], dtype="<f4").copy(),
            "ranks": np.frombuffer(d["ranks"], dtype="<i8").copy(),
            "seats": np.frombuffer(d["seats"], dtype="<i4").copy(),
            "game_ids": np.frombuffer(d["game_ids"], dtype="<i8").copy() + off,
            "turns": np.frombuffer(d["turns"], dtype="<i4").copy(),
            "forced": np.frombuffer(d["forced"], dtype=np.uint8).astype(bool),
        })
    keys = list(arrs[0])
    merged = {k: np.concatenate([x[k] for x in arrs], axis=0) for k in keys}
    cnt = len(merged["actions"])
    merged["has_pi"] = np.zeros(cnt, dtype=bool)
    merged["target_pi"] = np.zeros((0,), dtype=np.float32)
    meta = {
        "mode": "rust_collector_multi", "games": n, "shards": shards,
        "decisions": int(cnt), "rounds": int(rounds),
        "illegal_actions": int(sum(c.illegal() for c, _, _ in cols)),
        "truncated_games": int((merged["ranks"] <= 0).sum() > 0),
        "forced_end_turns": int(merged["forced"].sum()),
        "wall_s": time.time() - t0,
    }
    return merged, meta
