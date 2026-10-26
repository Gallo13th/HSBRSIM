"""PUCT 树节点 / 选择 / Dirichlet 根噪声 / visit 分布（纯 NumPy，实现与公式对应）。

公式（docs/AZ_MCTS_SELFPLAY_DESIGN.md §3.2/§3.5）::

    PUCT(a) = Q(a) + c_puct * P(a) * sqrt(sum_b N_b) / (1 + N_a)
    Q(a)    = W(a) / N(a)            (N=0 -> 0)
    P_root  = (1-eps) * P + eps * Dir(alpha)
    pi(a)   = N(a)^(1/tau) / sum_b N(b)^(1/tau)     (tau<=0 -> one-hot)

8 人常和但非两人零和：**备份不做符号翻转**（utility 始终是 seat 视角的 u(r)）。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


def masked_prior(raw: Any, mask: np.ndarray) -> np.ndarray:
    """把原始先验按合法 mask 清零并归一化；全零 → 合法动作均匀。

    防御 NaN/负值/Inf：非法动作置 0；和不为正时回退均匀。
    """
    m = np.asarray(mask, dtype=bool)
    p = np.asarray(raw, dtype=np.float32)
    if p.shape[0] != m.shape[0]:
        raise ValueError(f"prior 维度 {p.shape} 与 mask {m.shape} 不一致")
    p = np.where(np.isfinite(p) & (p > 0), p, 0.0).astype(np.float32)
    p = np.where(m, p, 0.0).astype(np.float32)
    s = float(p.sum())
    if not np.isfinite(s) or s <= 0.0:
        n = int(m.sum())
        if n == 0:
            return np.zeros_like(p)
        return (m.astype(np.float32) / float(n))
    return (p / s).astype(np.float32)


def dirichlet_legal(prior: np.ndarray, mask: np.ndarray, alpha: float,
                    epsilon: float, rng: random.Random) -> np.ndarray:
    """根 Dirichlet 噪声混合（只在合法动作上重新分配质量）。"""
    if alpha <= 0.0 or epsilon <= 0.0:
        return prior
    eps = float(np.clip(epsilon, 0.0, 1.0))
    legal = np.flatnonzero(np.asarray(mask, dtype=bool))
    if legal.size == 0:
        return prior
    draws = np.array([rng.gammavariate(float(alpha), 1.0) for _ in range(legal.size)],
                     dtype=np.float32)
    s = float(draws.sum())
    if not np.isfinite(s) or s <= 0.0:
        return prior
    noise = draws / s
    out = np.array(prior, dtype=np.float32, copy=True)
    out[legal] = (1.0 - eps) * out[legal] + eps * noise
    return masked_prior(out, mask)


def visit_distribution(counts: np.ndarray, temperature: float,
                       mask: Optional[np.ndarray] = None) -> np.ndarray:
    """π ∝ counts^(1/τ)；τ<=0 → one-hot(argmax count)；无访问 → 全 0（或 mask 均匀）。"""
    c = np.asarray(counts, dtype=np.float64)
    if mask is not None:
        c = np.where(np.asarray(mask, dtype=bool), c, 0.0)
    if c.size == 0 or float(c.sum()) <= 0.0:
        if mask is not None and np.asarray(mask).any():
            return (np.asarray(mask, dtype=np.float32) / float(np.asarray(mask).sum()))
        return np.zeros_like(c, dtype=np.float32)
    if temperature is None or temperature <= 0.0:
        out = np.zeros_like(c, dtype=np.float32)
        out[int(np.argmax(c))] = 1.0
        return out
    inv_t = 1.0 / float(temperature)
    p = np.power(np.maximum(c, 0.0), inv_t)
    s = float(p.sum())
    if not np.isfinite(s) or s <= 0.0:  # pragma: no cover - 数值兜底
        out = np.zeros_like(c, dtype=np.float32)
        out[int(np.argmax(c))] = 1.0
        return out
    return (p / s).astype(np.float32)


class Node:
    """MCTS 节点：持有一个世界里的 env 状态（每个节点一个 copy）。

    `counts/wins/prior` 长度 = env 动作数（engine 245）。`terminal_value` 非 None 表示终局。
    """

    __slots__ = ("game", "seat", "depth", "counts", "wins", "prior", "children",
                 "terminal_value", "expanded", "mask", "value")

    def __init__(self, game: Any, seat: int, *, depth: int = 0,
                 terminal_value: Optional[float] = None):
        n = game.num_actions if hasattr(game, "num_actions") else None
        if n is None:
            from .env_api import num_actions
            n = num_actions(game)
        self.game = game
        self.seat = int(seat)
        self.depth = int(depth)
        self.counts = np.zeros(int(n), dtype=np.int32)
        self.wins = np.zeros(int(n), dtype=np.float32)
        self.prior = np.zeros(int(n), dtype=np.float32)
        self.children: Dict[int, "Node"] = {}
        self.terminal_value = terminal_value
        self.expanded = False
        self.mask = np.zeros(int(n), dtype=bool)
        self.value = 0.0

    # -- 统计 ---------------------------------------------------------------
    @property
    def total_visits(self) -> int:
        return int(self.counts.sum())

    def q(self) -> np.ndarray:
        c = self.counts.astype(np.float32)
        return np.where(c > 0, self.wins / np.maximum(c, 1.0), 0.0)

    def expand(self, prior: np.ndarray, mask: np.ndarray, value: float) -> None:
        self.prior = masked_prior(prior, mask)
        self.mask = np.asarray(mask, dtype=bool)
        self.value = float(value)
        self.expanded = True

    def backup(self, action: int, value: float) -> None:
        self.counts[int(action)] += 1
        self.wins[int(action)] += float(value)

    def __repr__(self) -> str:  # pragma: no cover - 诊断
        return (f"Node(depth={self.depth}, visits={self.total_visits}, "
                f"expanded={self.expanded}, terminal={self.terminal_value is not None})")


def puct_select(node: Node, mask: np.ndarray, c_puct: float) -> int:
    """PUCT 选择；只在 mask 内选。未访问动作 Q=0，探索项按先验。"""
    legal = np.flatnonzero(np.asarray(mask, dtype=bool))
    if legal.size == 0:
        raise ValueError("puct_select: 没有合法动作")
    total = float(node.counts.sum())
    sqrt_total = math.sqrt(total) if total > 0.0 else 1.0
    n = node.counts[legal].astype(np.float32)
    q = np.where(n > 0, node.wins[legal] / np.maximum(n, 1.0), 0.0)
    p = node.prior[legal]
    explore = c_puct * p * sqrt_total / (1.0 + n)
    scores = q + explore
    # np.argmax 取第一个最大值：确定性（同 seed 同轨迹）
    return int(legal[int(np.argmax(scores))])


def sample_action(pi: np.ndarray, rng: random.Random) -> int:
    """按 π 采样动作（确定性由 rng 与 π 顺序决定）。"""
    p = np.asarray(pi, dtype=np.float64)
    s = float(p.sum())
    if not np.isfinite(s) or s <= 0.0:
        nz = np.flatnonzero(p > 0)
        return int(nz[0]) if nz.size else 0
    u = rng.random() * s
    cum = 0.0
    last = int(np.flatnonzero(p > 0)[0])
    for i in np.flatnonzero(p > 0):
        cum += float(p[i])
        last = int(i)
        if u <= cum:
            return int(i)
    return last


__all__ = [
    "Node", "dirichlet_legal", "masked_prior", "puct_select",
    "sample_action", "visit_distribution",
]
