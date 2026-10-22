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
