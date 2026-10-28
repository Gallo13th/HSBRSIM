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
        "game_ids": np.frombuffer(d["game_ids"], dtype="<i8").copy(),
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
