"""评测：基线策略、运行器、指标与报告。"""

from hsbg.eval.metrics import (EvalResult, avg_rank_percentile, bootstrap_ci,
                               format_summary, mean_rank, rank_distribution,
                               top4_rate, win_rate)
from hsbg.eval.runner import (evaluate_policy, print_result, save_result)

__all__ = [
    "EvalResult", "mean_rank", "win_rate", "top4_rate",
    "avg_rank_percentile", "rank_distribution", "bootstrap_ci",
    "format_summary", "evaluate_policy", "print_result", "save_result",
]
