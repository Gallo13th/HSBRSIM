"""搜索叶评估器（统一签名 ``evaluator(features, cards, mask, seat) -> (prior, value)``）。

- ``uniform``：合法动作均匀先验 + value 0（无信息基线）；
- ``heuristic``：脚本启发式先验 + value 0（冷启动先验；不是学习策略）；
- ``net``：``hsbg.az.train.model.TinyAZNet`` 的策略/名次价值输出（AlphaZero 口径）；
- ``make_rust_eval_fn``：ndarray 协议 -> Rust ``mcts_search`` 的 bytes 回调。

隐藏信息约束：所有评估器只接收该座位的 ``observe(seat)``（3227+124）与 245 掩码，
不使用 ``Game.view`` / ``state_json`` 等特权接口（设计 §2.7 D3）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import numpy as np

from .common import N_ACTIONS, group_of, masked_normalize, uniform_mask_policy

Evaluator = Callable[[np.ndarray, np.ndarray, np.ndarray, int], tuple[np.ndarray, float]]

#: 启发式先验的组优先级（与 HeuristicPolicy.PRIORITY 保持一致口径）
_HEUR_PRIORITY = ("choose", "play", "magnetize", "buy", "upgrade", "dark_gift",
                  "hero_power", "activate", "refresh", "end_turn")


def uniform_evaluator(features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                      seat: int = 0) -> tuple[np.ndarray, float]:
    """无信息先验：合法动作均匀 + value 0。"""
    return uniform_mask_policy(mask), 0.0


class HeuristicEvaluator:
    """脚本启发式先验 + value 0（冷启动/对照用；不含学习成分）。

    ``alpha``：先验里启发式动作的权重；剩余质量 ``1-alpha`` 均摊到所有合法动作
    （保证搜索有探索空间，不会退化成 one-hot）。
    """

    def __init__(self, alpha: float = 0.7) -> None:
        self.alpha = float(alpha)

    def __call__(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                 seat: int = 0) -> tuple[np.ndarray, float]:
        m = np.asarray(mask, dtype=bool).reshape(-1)
        legal = np.flatnonzero(m)
        if legal.size == 0:
            return np.zeros(N_ACTIONS, dtype=np.float32), 0.0
        by_group: Dict[str, list[int]] = {}
        for a in legal:
            by_group.setdefault(group_of(int(a)), []).append(int(a))
        best = int(legal[0])
        for name in _HEUR_PRIORITY:
            idx = by_group.get(name)
            if idx:
                best = idx[0]
                break
        prior = uniform_mask_policy(m).astype(np.float32) * (1.0 - self.alpha)
        prior[best] += self.alpha
        return masked_normalize(prior, m), 0.0


def make_evaluator(kind: str = "uniform", **kwargs: Any) -> Evaluator:
    """构造评估器：``uniform`` / ``heuristic`` / ``net``（``net`` 需 model 或 checkpoint）。"""
    key = str(kind).strip().lower()
    if key in ("uniform", "none"):
        return uniform_evaluator
    if key in ("heuristic", "heur"):
        return HeuristicEvaluator(alpha=float(kwargs.get("alpha", 0.7)))
    if key in ("net", "network", "nn"):
        from .model import NetEvaluator, load_checkpoint  # 惰性：torch 可选

        if "evaluator" in kwargs and kwargs["evaluator"] is not None:
            return kwargs["evaluator"]
        if "model" in kwargs and kwargs["model"] is not None:
            return NetEvaluator(kwargs["model"], device=str(kwargs.get("device", "cpu")))
        ckpt = kwargs.get("checkpoint")
        if not ckpt:
            raise ValueError("net 评估器需要 model=... 或 checkpoint=...")
        net, meta = load_checkpoint(str(ckpt), device=str(kwargs.get("device", "cpu")))
        return NetEvaluator(net, device=str(kwargs.get("device", "cpu")),
                            norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    raise ValueError(f"未知评估器类型: {kind!r}")


def make_rust_eval_fn(evaluator: Evaluator):
    """ndarray 评估器 -> ``hsbg_engine.mcts_search`` 的 bytes 回调。

    Rust 侧回调签名为 ``eval_fn(features_bytes, cards_bytes, mask_bytes, seat) ->
    (policy_bytes, value)``（见 docs/RUST_ENGINE.md §10.5）。
    """

    def eval_fn(features_bytes, cards_bytes, mask_bytes, seat):
        f = np.frombuffer(features_bytes, dtype="<f4")
        c = np.frombuffer(cards_bytes, dtype="<i4")
        m = np.frombuffer(mask_bytes, dtype=np.uint8).astype(bool)
        prior, value = evaluator(f, c, m, int(seat))
        return np.asarray(prior, dtype=np.float32).tobytes(), float(value)

    return eval_fn


__all__ = [
    "Evaluator",
    "uniform_evaluator",
    "HeuristicEvaluator",
    "make_evaluator",
    "make_rust_eval_fn",
]
