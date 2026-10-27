"""C0 冷启动 gate：单模型 vs 引擎 bot 的配对评测与统计判据。

主判据（GPT-6-Astra 终审修正）：
- 同 seed/seat 配对 Δ = rank_model - rank_bot；
- 512 局、8 seat 均衡；
- Δ 的 95% bootstrap CI **上界 < 0** 才算“击败 bot”；
- zero truncation / zero illegal；
- 未在封存集上重复确认前，不进入联赛。

本模块只做统计与判定，不依赖引擎；脚本 `scripts/c0_gate.py` 负责跑引擎。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np


@dataclass
class C0GateConfig:
    games: int = 512
    seats: int = 8
    bootstrap: int = 5000
    seed: int = 0
    alpha: float = 0.05
    require_zero_truncation: bool = True
    require_zero_illegal: bool = True
    require_protocol: bool = True
    require_zero_truncated_combats: bool = True
    #: 工程参考（非统计判据）
    mean_rank_max: float = 4.75
    top4_min: float = 0.55


@dataclass
class C0GateResult:
    passed: bool
    n: int
    mean_diff: float
    ci_low: float
    ci_high: float
    model_mean_rank: float
    bot_mean_rank: float
    model_top4: float
    bot_top4: float
    model_win: float
    illegal: int
    truncated: int
    truncated_combats: int
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "n": self.n,
            "mean_diff": self.mean_diff,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "model_mean_rank": self.model_mean_rank,
            "bot_mean_rank": self.bot_mean_rank,
            "model_top4": self.model_top4,
            "bot_top4": self.bot_top4,
            "model_win": self.model_win,
            "illegal": self.illegal,
            "truncated": self.truncated,
            "truncated_combats": self.truncated_combats,
            "reasons": list(self.reasons),
            "details": self.details,
        }


def paired_diffs(model_ranks: Sequence[int], bot_ranks: Sequence[int]) -> np.ndarray:
    """逐局配对差；长度必须一致，rank=0（截断）不参与均值。"""
    a = np.asarray(list(model_ranks), dtype=np.int64).reshape(-1)
    b = np.asarray(list(bot_ranks), dtype=np.int64).reshape(-1)
    if a.size != b.size:
        raise ValueError(f"配对长度不一致: model={a.size} bot={b.size}")
    if a.size == 0:
        raise ValueError("配对样本为空")
    mask = (a >= 1) & (b >= 1)
    return (a[mask] - b[mask]).astype(np.float64), int((~mask).sum())


def bootstrap_ci(diffs: Iterable[float], *, n_boot: int = 5000, alpha: float = 0.05,
                 seed: int = 0) -> tuple[float, float]:
    d = np.asarray(list(diffs), dtype=np.float64).reshape(-1)
    if d.size == 0:
        raise ValueError("diffs 为空")
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, d.size, size=(int(n_boot), d.size))
    means = d[idx].mean(axis=1)
    lo = float(np.quantile(means, alpha / 2.0))
    hi = float(np.quantile(means, 1.0 - alpha / 2.0))
    return lo, hi


def evaluate_gate(model_ranks: Sequence[int], bot_ranks: Sequence[int], *,
                  config: Optional[C0GateConfig] = None,
                  illegal: int = 0, truncated: int = 0,
                  truncated_combats: int = 0,
                  extra: Optional[Dict[str, object]] = None) -> C0GateResult:
    cfg = config or C0GateConfig()
    # 协议/rank 合法性（防 99、缺失、浮点截断后误通过）
    reasons: List[str] = []
    a = np.asarray(list(model_ranks), dtype=np.float64).reshape(-1)
    b = np.asarray(list(bot_ranks), dtype=np.float64).reshape(-1)
    if a.size != b.size:
        raise ValueError(f"配对长度不一致: model={a.size} bot={b.size}")
    if np.any(~np.isfinite(a)) or np.any(~np.isfinite(b)):
        reasons.append("rank 含 NaN/Inf")
    if np.any(a != np.round(a)) or np.any(b != np.round(b)):
        reasons.append("rank 必须是整数")
    ai = np.rint(a).astype(np.int64); bi = np.rint(b).astype(np.int64)
    bad = ((ai < 0) | (ai > 8) | (bi < 0) | (bi > 8))
    if bool(bad.any()):
        reasons.append(f"{int(bad.sum())} 个 rank 越界（只允许 0..8，0=截断）")
    if cfg.require_protocol and (int(cfg.games) != 512 or int(cfg.seats) != 8):
        reasons.append("正式 gate 必须 games=512 / seats=8")
    diffs, pair_missing = paired_diffs(ai, bi)
    if diffs.size == 0:
        raise ValueError("没有可配对的合法 rank（全为截断）")
    lo, hi = bootstrap_ci(diffs, n_boot=cfg.bootstrap, alpha=cfg.alpha, seed=cfg.seed)
    m = np.asarray([r for r in ai if r >= 1], dtype=np.float64)
    bm = np.asarray([r for r in bi if r >= 1], dtype=np.float64)
    if int(a.size) != int(cfg.games) or int(diffs.size) != int(cfg.games):
        reasons.append(f"有效配对局数 {diffs.size}/{a.size} != {cfg.games}")
    if int(pair_missing) != 0:
        reasons.append(f"{pair_missing} 对含截断 rank=0（零截断要求）")
    if hi >= 0.0:
        reasons.append(f"95% CI 上界 {hi:.4f} >= 0，不能证明击败 bot")
    if cfg.require_zero_truncation and int(truncated) != 0:
        reasons.append(f"truncated={truncated} != 0")
    if cfg.require_zero_illegal and int(illegal) != 0:
        reasons.append(f"illegal={illegal} != 0")
    if cfg.require_zero_truncated_combats and int(truncated_combats) != 0:
        reasons.append(f"truncated_combats={truncated_combats} != 0")
    passed = not reasons
    return C0GateResult(
        passed=passed,
        n=int(diffs.size),
        mean_diff=float(diffs.mean()),
        ci_low=lo,
        ci_high=hi,
        model_mean_rank=float(m.mean()) if m.size else float("nan"),
        bot_mean_rank=float(bm.mean()) if bm.size else float("nan"),
        model_top4=float((m <= 4).mean()) if m.size else float("nan"),
        bot_top4=float((bm <= 4).mean()) if bm.size else float("nan"),
        model_win=float((m == 1).mean()) if m.size else float("nan"),
        illegal=int(illegal),
        truncated=int(truncated),
        truncated_combats=int(truncated_combats),
        reasons=reasons,
        details={"pair_missing": int(pair_missing), **(extra or {})},
    )


__all__ = ["C0GateConfig", "C0GateResult", "paired_diffs", "bootstrap_ci",
           "evaluate_gate"]
