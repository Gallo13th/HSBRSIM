"""进程级 actor pool（P0 原型）。

当前 `parallel_collect.py` 是单进程 64 线程；本模块用 multiprocessing spawn
在多个 GPU/进程上跑 actor，每个进程独立 model/evaluator/engine，返回 records
给 learner。它还不是完整 topology A（没有共享 inference server），但能验证：

- 进程级 actor 是否避开 GIL；
- 多 GPU 独立 actor 的 decisions/s；
- 4 GPU 资源扫描。

注意：每进程重复加载 model；跨进程不共享 BatchLeafServer；权重由 checkpoint 固定。
"""

from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .ppo import CollectConfig, PPOBatch, build_batch_from_records
from .parallel_collect import _one_game


def _worker(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """子进程：load checkpoint -> 采 assigned games -> 返回 records/meta。"""
    import torch
    from .model import load_checkpoint
    from .ppo import PPOEvaluator
    from .common import to_jsonable

    gpu = int(payload["gpu"])
    if torch.cuda.is_available():
        torch.cuda.set_device(gpu)
    device = f"cuda:{gpu}" if torch.cuda.is_available() else "cpu"
    model, meta = load_checkpoint(payload["checkpoint"], device=device)
    norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
    cfg = CollectConfig(**payload["cfg"])
    eval_fn = PPOEvaluator(model, device=device, norm_mean=norm_mean, norm_std=norm_std)
    search_fn = search_cfg = None
    if int(payload.get("sims", 0)) > 0:
        from hsbg.az import SearchConfig, search as az_search
        search_fn = az_search
        search_cfg = SearchConfig(simulations=int(payload["sims"]),
                                  determinizations=int(payload.get("determinizations", 1)),
                                  seed=int(payload["seed"]) + int(payload["game_offset"]))
    records: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    for local in range(int(payload["games"])):
        gi = int(payload["game_offset"]) + local
        recs, m = _one_game(model, cfg, gi, search_fn=search_fn,
                            search_config=search_cfg, eval_fn=eval_fn,
                            engine_backend="auto", device=device,
                            seed=int(payload["seed"]), gamemode=str(cfg.opponent),
                            norm_mean=norm_mean, norm_std=norm_std)
        records.extend(recs)
        metas.append(m)
    return records, to_jsonable(metas)


class ProcessActorPool:
    def __init__(self, processes: int, gpus: List[int], checkpoint: str, *,
                 arch: str = "entity18m", sims: int = 0,
                 determinizations: int = 1, seed: int = 0):
        self.processes = max(1, int(processes))
        self.gpus = list(gpus) or [0]
        self.checkpoint = checkpoint
        self.arch = arch
        self.sims = int(sims)
        self.determinizations = int(determinizations)
        self.seed = int(seed)
        self.ctx = mp.get_context("spawn")

    def collect(self, cfg: CollectConfig, games: int, *,
                progress: bool = False) -> Tuple[PPOBatch, Dict[str, Any]]:
        n = max(1, int(games))
        per = (n + self.processes - 1) // self.processes
        payloads = []
        for i in range(self.processes):
            g0 = i * per
            gcount = max(0, min(per, n - g0))
            if gcount <= 0:
                continue
            payloads.append({
                "gpu": self.gpus[i % len(self.gpus)],
                "checkpoint": self.checkpoint,
                "arch": self.arch,
                "sims": self.sims,
                "determinizations": self.determinizations,
                "seed": self.seed,
                "game_offset": g0,
                "games": gcount,
                "cfg": {**asdict(cfg), "games": gcount,
                        "seed": self.seed + g0,
                        "game_id_offset": g0},
            })
        with self.ctx.Pool(processes=len(payloads)) as pool:
            outs = pool.map(_worker, payloads)
        records: List[Dict[str, Any]] = []
        metas: List[Dict[str, Any]] = []
        for recs, ms in outs:
            records.extend(recs)
            metas.extend(ms)
        if not records:
            raise RuntimeError("process pool collected no records")
        meta: Dict[str, Any] = {
            "mode": "process_pool",
            "processes": self.processes,
            "gpus": self.gpus,
            "games": len(metas),
            "decisions": sum(int(m.get("decisions", 0)) for m in metas),
            "illegal_actions": sum(int(m.get("illegal_actions", 0)) for m in metas),
            "truncated_games": sum(int(m.get("truncated", 0)) for m in metas),
            "records": len(records),
            "sims": self.sims,
        }
        batch = build_batch_from_records(records, gamma=cfg.step_penalty if False else 1.0,
                                         lam=0.95, meta=meta)
        return batch, meta


__all__ = ["ProcessActorPool"]
