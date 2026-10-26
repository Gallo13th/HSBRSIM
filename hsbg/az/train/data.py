"""AZ 训练数据容器与质量指标。

样本 schema（对齐 docs/AZ_MCTS_SELFPLAY_DESIGN.md §8.1，初期 smoke 用 numpy 数组）：

```text
features f32[N,3227]  cards i16[N,124]  masks u8[N,245]
pi       f16[N,245]   （搜索 visit 分布；非搜索策略为 one-hot）
actions  u16[N]       ranks u8[N]（1..8，0=未知/截断）
utility  f32[N]       seat u8[N]  turn i16[N]  game_id i64[N]  source u8[N]
```

``source``：0 = 纯策略 one-hot（BC 目标），1 = 搜索 visit 分布（AZ 目标）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from .common import (
    N_ACTIONS,
    N_PLAYERS,
    OBS_CARDS,
    OBS_FLOATS,
    group_of,
    one_hot_policy,
    policy_entropy,
    to_jsonable,
    utility_from_rank,
)

#: 数据集字段 -> (dtype, 每行形状)
FIELDS: Dict[str, tuple[str, tuple[int, ...]]] = {
    "features": ("float32", (OBS_FLOATS,)),
    "cards": ("int16", (OBS_CARDS,)),
    "masks": ("uint8", (N_ACTIONS,)),
    "pi": ("float16", (N_ACTIONS,)),
    "actions": ("uint16", ()),
    "ranks": ("uint8", ()),
    "utility": ("float32", ()),
    "seat": ("uint8", ()),
    "turn": ("int16", ()),
    "game_id": ("int64", ()),
    "source": ("uint8", ()),
}


def _sample_to_row(sample: Dict[str, Any]) -> Dict[str, np.ndarray]:
    mask = np.asarray(sample["mask"], dtype=bool).reshape(-1)
    action = int(sample["action"])
    pi = sample.get("pi")
    if pi is None:
        pi = one_hot_policy(action, mask)
    pi = np.asarray(pi, dtype=np.float32).reshape(-1)
    # 兜底：掩码外清零 + 归一（搜索原型可能返回未归一/含非法质量）
    pi = np.where(mask, pi, 0.0)
    s = float(pi.sum())
    if s > 1e-8:
        pi = pi / s
    else:
        pi = one_hot_policy(action, mask)
    rank = int(sample.get("rank", 0) or 0)
    return {
        "features": np.asarray(sample["features"], dtype=np.float32),
        "cards": np.asarray(sample["cards"], dtype=np.int16),
        "masks": np.asarray(mask, dtype=np.uint8),
        "pi": pi.astype(np.float16),
        "actions": np.asarray(action, dtype=np.uint16),
        "ranks": np.asarray(rank, dtype=np.uint8),
        "utility": np.asarray(utility_from_rank(rank), dtype=np.float32),
        "seat": np.asarray(int(sample.get("seat", 0)), dtype=np.uint8),
        "turn": np.asarray(int(sample.get("turn", -1)), dtype=np.int16),
        "game_id": np.asarray(int(sample.get("game_id", -1)), dtype=np.int64),
        "source": np.asarray(int(sample.get("source", 0)), dtype=np.uint8),
    }


@dataclass
class AZDataset:
    """(features, cards, masks, pi, action, rank/z) 轨迹数据集。"""

    arrays: Dict[str, np.ndarray] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.arrays:
            for name, (dtype, shape) in FIELDS.items():
                self.arrays[name] = np.zeros((0, *shape), dtype=dtype)

    # ── 构造 ──
    @classmethod
    def from_samples(cls, samples: Iterable[Dict[str, Any]],
                     meta: Optional[Dict[str, Any]] = None) -> "AZDataset":
        rows: Dict[str, List[np.ndarray]] = {k: [] for k in FIELDS}
        n = 0
        for sample in samples:
            row = _sample_to_row(sample)
            for k in FIELDS:
                rows[k].append(row[k])
            n += 1
        arrays: Dict[str, np.ndarray] = {}
        for k, (_dtype, shape) in FIELDS.items():
            dtype = FIELDS[k][0]
            if rows[k]:
                arrays[k] = np.stack([np.asarray(r, dtype=dtype) for r in rows[k]])
            else:
                arrays[k] = np.zeros((0, *shape), dtype=dtype)
        return cls(arrays=arrays, meta=dict(meta or {}))

    @classmethod
    def concat(cls, datasets: Iterable["AZDataset"]) -> "AZDataset":
        items = [d for d in datasets if len(d) > 0]
        if not items:
            return cls(meta={"games": 0})
        arrays = {k: np.concatenate([d.arrays[k] for d in items], axis=0) for k in FIELDS}
        merged_meta: Dict[str, Any] = {}
        for d in items:
            for k, v in d.meta.items():
                if isinstance(v, (int, float)):
                    if k in ("games", "samples", "decisions", "illegal_actions"):
                        merged_meta[k] = int(merged_meta.get(k, 0)) + int(v)
                    else:
                        merged_meta.setdefault(k, v)
        merged_meta["samples"] = int(sum(len(d) for d in items))
        return cls(arrays=arrays, meta=merged_meta)

    # ── 基本属性 ──
    def __len__(self) -> int:
        return int(self.arrays["features"].shape[0])

    def __getitem__(self, idx) -> "AZDataset":
        idx = np.asarray(idx)
        if idx.dtype == bool:
            idx = np.flatnonzero(idx)
        return AZDataset(arrays={k: v[idx] for k, v in self.arrays.items()}, meta=dict(self.meta))

    @property
    def n_games(self) -> int:
        gid = self.arrays["game_id"]
        return int(np.unique(gid[gid >= 0]).size)

    def subset(self, idx) -> "AZDataset":
        return self[idx]

    # ── 存储（npz 压缩 + meta json 内嵌）──
    def save(self, path: str) -> str:
        path = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        payload = {f"arr_{k}": v for k, v in self.arrays.items()}
        payload["meta_json"] = np.asarray(json.dumps(to_jsonable(self.meta),
                                                    ensure_ascii=False))
        np.savez_compressed(path, **payload)
        return path

    @classmethod
    def load(cls, path: str) -> "AZDataset":
        with np.load(str(path), allow_pickle=False) as z:
            arrays = {k: np.asarray(z[f"arr_{k}"]) for k in FIELDS if f"arr_{k}" in z}
            meta = json.loads(str(z["meta_json"])) if "meta_json" in z else {}
        ds = cls(arrays={**{k: np.zeros((0, *FIELDS[k][1]), dtype=FIELDS[k][0])
                            for k in FIELDS}, **arrays}, meta=meta)
        return ds

    # ── 质量指标 ──
    def quality_metrics(self, sample_limit: int = 20000) -> Dict[str, Any]:
        n = len(self)
        if n == 0:
            return {"samples": 0, "games": 0}
        m = self.arrays["masks"].astype(bool)
        a = self.arrays["actions"].astype(np.int64)
        pi = self.arrays["pi"].astype(np.float32)
        rows = np.arange(n)
        legal_ok = m[rows, np.clip(a, 0, N_ACTIONS - 1)]
        pi_sum = pi.sum(axis=1)
        pi_out = (pi * (~m)).sum(axis=1)
        ents = np.array([policy_entropy(pi[i]) for i in range(min(n, sample_limit))])
        argmax = pi.argmax(axis=1)
        argmax_groups: Dict[str, int] = {}
        for g in argmax:
            name = group_of(int(g))
            argmax_groups[name] = argmax_groups.get(name, 0) + 1
        ranks = self.arrays["ranks"].astype(np.int64)
        known = ranks[(ranks >= 1) & (ranks <= N_PLAYERS)]
        util = self.arrays["utility"]
        return {
            "samples": int(n),
            "games": int(self.n_games),
            "seats_covered": int(np.unique(self.arrays["seat"]).size),
            "decisions_per_game": float(n / max(self.n_games, 1)),
            "legal_action_rate": float(legal_ok.mean()),
            "pi_sum_error_mean": float(np.abs(pi_sum - 1.0).mean()),
            "pi_out_of_mask_mass_mean": float(pi_out.mean()),
            "pi_entropy_mean": float(ents.mean()),
            "pi_argmax_group_counts": {k: int(v) for k, v in
                                       sorted(argmax_groups.items(), key=lambda kv: -kv[1])},
            "search_target_rate": float((self.arrays["source"] == 1).mean()),
            "ranks_known": int(known.size),
            "rank_mean": float(known.mean()) if known.size else None,
            "rank_counts": {int(k): int(v) for k, v in
                            zip(*np.unique(known, return_counts=True))} if known.size else {},
            "utility_mean": float(util.mean()),
            "turn_min": int(self.arrays["turn"].min()),
            "turn_max": int(self.arrays["turn"].max()),
        }

    def validate(self) -> List[str]:
        """形状/合法性自检；返回问题字符串列表（空 = 通过）。"""
        errs: List[str] = []
        n = len(self)
        for name, (dtype, shape) in FIELDS.items():
            arr = self.arrays.get(name)
            if arr is None:
                errs.append(f"missing field {name}")
                continue
            want = (n, *shape)
            if arr.shape != want:
                errs.append(f"{name}: shape {arr.shape} != {want}")
        if n == 0:
            return errs
        m = self.arrays["masks"].astype(bool)
        a = self.arrays["actions"].astype(np.int64)
        rows = np.arange(n)
        bad = ~m[rows, np.clip(a, 0, N_ACTIONS - 1)]
        if bad.any():
            errs.append(f"{int(bad.sum())} 个动作不在合法掩码内")
        pi = self.arrays["pi"].astype(np.float32)
        if not np.isfinite(pi).all():
            errs.append("pi 含 NaN/Inf")
        sums = pi.sum(axis=1)
        if n and (np.abs(sums - 1.0) > 5e-2).any():
            errs.append(f"pi 归一化误差过大: max={float(np.abs(sums - 1.0).max()):.4f}")
        ranks = self.arrays["ranks"].astype(np.int64)
        if ((ranks < 0) | (ranks > N_PLAYERS)).any():
            errs.append("ranks 越界")
        return errs


__all__ = ["FIELDS", "AZDataset"]
