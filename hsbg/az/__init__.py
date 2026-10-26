"""hsbg.az — AlphaZero 风格**不完全信息**搜索原型（PIMC / determinization + PUCT）。

本包只依赖 numpy 与可选 `hsbg_engine`；不修改 `hsbg.env/backends/rl/train` 既有接口。

最小用法::

    from hsbg.az import search, SearchConfig
    res = search(game, seat=0, config=SearchConfig(simulations=16, determinizations=4,
                                                   seed=0))
    res.pi          # f32[245] 根 visit 分布（合法动作外为 0，和=1）
    res.action      # 采样动作
    res.root_value  # 根平均 utility（seat 视角）
    res.info        # 引擎后端/世界信息/耗时/回退原因/n_evals...

训练侧回调（与 Rust `mcts_search` 的 eval 回调一致）::

    def eval_fn(features, cards, mask, seat) -> (policy[245], value): ...

文档：`docs/AZ_IMPERFECT_SEARCH_DESIGN.md`；测试：`tests/test_az_search.py`。
"""

from __future__ import annotations

from .belief import (BeliefSampler, CallableSampler, CloneSampler, DeterminizeInfo,
                     EnginePublicPriorSampler, PassthroughSampler, default_sampler)
from .env_api import (ObsView, PublicInfo, decode_public, observe, placement_utility)
from .policy import (Agent, BotAgent, BotPriorEvaluator, HeuristicAgent,
                     HeuristicEvaluator, RandomAgent, RolloutEvaluator,
                     SearchAgent, UniformEvaluator, heuristic_prior,
                     heuristic_value, make_evaluator)
from .puct import Node, visit_distribution
from .search import SearchConfig, SearchResult, az_search, search, search_engine_style

__all__ = [
    "Agent", "BeliefSampler", "BotAgent", "BotPriorEvaluator", "CallableSampler",
    "CloneSampler", "DeterminizeInfo", "EnginePublicPriorSampler",
    "HeuristicAgent", "HeuristicEvaluator", "Node", "ObsView",
    "PassthroughSampler", "PublicInfo", "RandomAgent", "RolloutEvaluator",
    "SearchAgent", "SearchConfig", "SearchResult", "UniformEvaluator",
    "az_search", "decode_public", "default_sampler", "heuristic_prior",
    "heuristic_value", "make_evaluator", "observe", "placement_utility",
    "search", "search_engine_style", "visit_distribution",
]
