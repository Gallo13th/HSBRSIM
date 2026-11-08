"""评测指标（纯函数，无引擎/torch 依赖）。"""

from hsbg.eval.metrics import (
    EvalResult,
    avg_rank_percentile,
    bootstrap_ci,
    format_summary,
    mean_rank,
    rank_distribution,
    top4_rate,
    win_rate,
)

__all__ = [
    "EvalResult",
    "mean_rank",
    "win_rate",
    "top4_rate",
    "avg_rank_percentile",
    "rank_distribution",
    "bootstrap_ci",
    "format_summary",
]
