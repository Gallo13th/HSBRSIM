"""评测指标（纯函数，无引擎/环境依赖，便于单测与离线回放）。"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple


def mean_rank(ranks: Sequence[int]) -> float:
    """平均名次（越小越好；1 = 冠军）。"""
    return statistics.fmean(ranks) if ranks else float("nan")


def win_rate(ranks: Sequence[int]) -> float:
    return sum(1 for r in ranks if r == 1) / len(ranks) if ranks else float("nan")


def top4_rate(ranks: Sequence[int], num_players: int = 8) -> float:
    """前一半名次率（8 人局 = 前四）。"""
    cut = max(1, num_players // 2)
    return sum(1 for r in ranks if r <= cut) / len(ranks) if ranks else float("nan")


def avg_rank_percentile(ranks: Sequence[int], num_players: int = 8) -> float:
    """名次百分位（0=最差，1=最好），用于跨人数比较。"""
    if not ranks:
        return float("nan")
    return statistics.fmean(
        (num_players - r) / (num_players - 1) for r in ranks
    )


def percentile_ranks(values: Sequence[float]) -> List[float]:
    """平均秩百分位，0（最小）..1（最大）；并列取平均秩。"""
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: float(values[i]))
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and float(values[order[j + 1]]) == float(values[order[i]]):
            j += 1
        r = (i + j) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = r
        i = j + 1
    denom = float(n - 1) if n > 1 else 1.0
    return [r / denom for r in out]


def game_weights(turns: Sequence[float], strengths: Sequence[float], *,
                 alpha: float = 0.5, beta: float = 0.5,
                 floor: float = 0.5, cap: float = 2.0) -> List[float]:
    """按「对局长度 + 对局强度」给每局一个权重，均值归一到 1。

    - ``turns``：对局长度（回合数）；``strengths``：对局强度（如终局最强盘面 Σ(atk+hp)）。
    - 两者先在当前 cohort 内转成平均秩百分位（0..1），再 ``alpha*u + beta*v`` 混合。
    - 原始权重 = floor + (cap-floor) * 混合分，再归一化到均值 1（再 clip 到 [floor, cap]）。
    - 默认 alpha=beta=0.5：长且强的局权重最高，短且弱的局最低。
    """
    n = len(turns)
    if n == 0:
        return []
    if len(strengths) != n:
        raise ValueError("turns/strengths 长度不一致")
    u = percentile_ranks(turns)
    v = percentile_ranks(strengths)
    raw = [floor + (cap - floor) * (alpha * u[i] + beta * v[i]) for i in range(n)]
    m = statistics.fmean(raw)
    w = [x / m for x in raw]
    # 归一化后再 clip，最后再归一化一次（保持均值≈1）
    w = [min(cap, max(floor, x)) for x in w]
    m2 = statistics.fmean(w)
    return [x / m2 for x in w]


def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    if not values:
        return float("nan")
    if len(values) != len(weights):
        raise ValueError("values/weights 长度不一致")
    sw = sum(weights)
    if sw <= 0:
        return float("nan")
    return sum(float(v) * float(w) for v, w in zip(values, weights)) / sw


def effective_sample_size(weights: Sequence[float]) -> float:
    if not weights:
        return 0.0
    sw = sum(weights)
    sw2 = sum(w * w for w in weights)
    return (sw * sw / sw2) if sw2 > 0 else 0.0


def weighted_eval_summary(ranks: Sequence[int], turns: Sequence[float],
                          strengths: Sequence[float], *, alpha: float = 0.5,
                          beta: float = 0.5, num_players: int = 8) -> Dict[str, object]:
    """返回 unweighted / weighted 两套指标 + 权重统计（纯函数，便于评测 JSON 直接落盘）。"""
    n = len(ranks)
    if n != len(turns) or n != len(strengths):
        raise ValueError("ranks/turns/strengths 长度不一致")
    w = game_weights(turns, strengths, alpha=alpha, beta=beta)
    top4 = [1.0 if int(r) <= max(1, num_players // 2) else 0.0 for r in ranks]
    win = [1.0 if int(r) == 1 else 0.0 for r in ranks]
    out = {
        "n": int(n),
        "formula": {"alpha": float(alpha), "beta": float(beta),
                    "turns": "percentile_rank", "strength": "percentile_rank"},
        "weights": [round(float(x), 6) for x in w],
        "n_eff": float(effective_sample_size(w)),
        "unweighted": {
            "mean_rank": mean_rank(ranks),
            "top4": statistics.fmean(top4) if n else float("nan"),
            "win": statistics.fmean(win) if n else float("nan"),
            "mean_strength": statistics.fmean(strengths) if n else float("nan"),
            "mean_turns": statistics.fmean(turns) if n else float("nan"),
        },
        "weighted": {
            "mean_rank": weighted_mean(ranks, w),
            "top4": weighted_mean(top4, w),
            "win": weighted_mean(win, w),
            "mean_strength": weighted_mean(strengths, w),
            "mean_turns": weighted_mean(turns, w),
        },
        "weight_stats": {
            "min": min(w) if w else None,
            "max": max(w) if w else None,
            "mean": statistics.fmean(w) if w else None,
        },
    }
    return out


def long_strong_subset(ranks: Sequence[int], turns: Sequence[float],
                       strengths: Sequence[float], *, quantile: float = 0.75,
                       num_players: int = 8) -> Dict[str, object]:
    """「长且强」对局子集：turns 与 strengths 的平均秩百分位都 >= quantile。

    用户口径：只看**长度和终局强度都排在前 (1-quantile)** 的 bot 对局，用模型在这些
    局里的 rank/top4/win 判断「长且强的 bot 局」是否真能打；避免被大量短局稀释。
    纯函数；空输入或长度不一致时返回 n=0 的空结果（不抛异常，评测不因它失败）。
    """
    n = len(ranks)
    if n == 0 or len(turns) != n or len(strengths) != n:
        return {"n": 0, "quantile": float(quantile), "mean_rank": None,
                "top4": None, "win": None, "thresholds": None, "games": []}
    u = percentile_ranks(turns)
    v = percentile_ranks(strengths)
    idx = [i for i in range(n) if u[i] >= quantile and v[i] >= quantile]
    sel = [int(ranks[i]) for i in idx]
    cut = max(1, num_players // 2)
    thr = None
    if idx:
        thr = {"turns_min": min(float(turns[i]) for i in idx),
               "strength_min": min(float(strengths[i]) for i in idx)}
    return {
        "n": len(idx),
        "quantile": float(quantile),
        "mean_rank": mean_rank(sel) if sel else None,
        "top4": (sum(1 for r in sel if r <= cut) / len(sel)) if sel else None,
        "win": (sum(1 for r in sel if r == 1) / len(sel)) if sel else None,
        "thresholds": thr,
        "games": idx,
    }


def rank_distribution(ranks: Sequence[int],
                      num_players: int = 8) -> Dict[int, float]:
    dist = {r: 0.0 for r in range(1, num_players + 1)}
    if not ranks:
        return dist
    for r in ranks:
        dist[r] = dist.get(r, 0.0) + 1.0 / len(ranks)
    return dist


def bootstrap_ci(values: Sequence[float], *, n_boot: int = 2000,
                 alpha: float = 0.05, seed: int = 0) -> Tuple[float, float]:
    """均值的 bootstrap 置信区间（纯 Python，避免 numpy 依赖）。"""
    if not values:
        return (float("nan"), float("nan"))
    import random
    rng = random.Random(seed)
    n = len(values)
    means: List[float] = []
    for _ in range(n_boot):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo = means[max(0, int(alpha / 2 * n_boot) - 1)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return (lo, hi)


@dataclass
class EvalResult:
    """一组对局的评测结果。"""

    num_players: int = 8
    ranks: List[int] = field(default_factory=list)
    rewards: List[float] = field(default_factory=list)
    turns: List[int] = field(default_factory=list)
    steps: List[int] = field(default_factory=list)
    invalid_actions: int = 0
    truncated: int = 0
    #: 每局结束原因
    reasons: List[str] = field(default_factory=list)
    #: 评测总耗时（秒；由 runner 填写）
    wall_seconds: float = 0.0

    def add(self, *, rank: int, reward: float, turns: int, steps: int,
            invalid: int = 0, truncated: bool = False,
            reason: str = "") -> None:
        self.ranks.append(int(rank))
        self.rewards.append(float(reward))
        self.turns.append(int(turns))
        self.steps.append(int(steps))
        self.invalid_actions += int(invalid)
        self.truncated += int(truncated)
        self.reasons.append(reason)

    # ── 汇总 ──
    def summary(self) -> Dict[str, float]:
        ranks = self.ranks
        lo, hi = bootstrap_ci([float(r) for r in ranks])
        return {
            "episodes": float(len(ranks)),
            "mean_rank": mean_rank(ranks),
            "mean_rank_ci_low": lo,
            "mean_rank_ci_high": hi,
            "win_rate": win_rate(ranks),
            "top_half_rate": top4_rate(ranks, self.num_players),
            "rank_percentile": avg_rank_percentile(ranks, self.num_players),
            "mean_reward": statistics.fmean(self.rewards) if self.rewards
            else float("nan"),
            "mean_turns": statistics.fmean(self.turns) if self.turns
            else float("nan"),
            "mean_steps": statistics.fmean(self.steps) if self.steps
            else float("nan"),
            "invalid_actions": float(self.invalid_actions),
            "truncated": float(self.truncated),
        }

    def rank_distribution(self) -> Dict[int, float]:
        return rank_distribution(self.ranks, self.num_players)

    def to_dict(self) -> Dict[str, object]:
        return {
            "summary": self.summary(),
            "rank_distribution": {
                str(k): v for k, v in self.rank_distribution().items()},
            "ranks": self.ranks,
            "rewards": self.rewards,
            "turns": self.turns,
            "steps": self.steps,
            "reasons": self.reasons,
        }


def format_summary(result: EvalResult, name: str = "") -> str:
    """人类可读的评测摘要（控制台/报告用）。"""
    s = result.summary()
    dist = result.rank_distribution()
    lines = [
        f"== {name or 'policy'} ==",
        f"episodes={int(s['episodes'])}  mean_rank={s['mean_rank']:.3f} "
        f"[{s['mean_rank_ci_low']:.2f},{s['mean_rank_ci_high']:.2f}]  "
        f"win={s['win_rate']:.1%}  top_half={s['top_half_rate']:.1%}",
        "rank_dist: " + "  ".join(
            f"{r}:{dist.get(r, 0.0):.0%}" for r in range(1, result.num_players + 1)),
        f"mean_turns={s['mean_turns']:.1f} mean_steps={s['mean_steps']:.0f} "
        f"invalid={int(s['invalid_actions'])} truncated={int(s['truncated'])}",
    ]
    return "\n".join(lines)
