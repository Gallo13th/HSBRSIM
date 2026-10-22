"""Phase 1 搜索模块（不训练）。

对应 ``docs/ALGORITHM_RESEARCH.md`` §6：
- ``hsbg.planning``（env-builder v1）提供 clone / legal_actions / apply / rng fork；
- 本包提供 macro 树 PUCT、BC evaluator、macro rollout、简化 determinization。

对外 API::

    from hsbg.search import EngineForwardModel, PolicyEvaluator, SearchConfig, run_search
    model = EngineForwardModel.from_env(env, clone=True)
    ev = PolicyEvaluator()
    res = run_search(model, ev, SearchConfig(simulations=8))
"""

from hsbg.search.determinize import (  # noqa: F401
    DeterminizeInfo,
    WarbandBank,
    WarbandSample,
    determinize,
)
from hsbg.search.evaluator import PolicyEvaluator  # noqa: F401
from hsbg.search.forward import EngineForwardModel  # noqa: F401
from hsbg.search.mcts import MCTS, run_search  # noqa: F401
from hsbg.search.rollout import RolloutStats, generate_macros  # noqa: F401
from hsbg.search.types import (  # noqa: F401
    MacroAction,
    Node,
    SearchConfig,
    SearchResult,
    StateEval,
    placement_utility,
    prior_softmax,
)

__all__ = [
    "EngineForwardModel",
    "PolicyEvaluator",
    "SearchConfig",
    "SearchResult",
    "StateEval",
    "MacroAction",
    "Node",
    "MCTS",
    "run_search",
    "generate_macros",
    "RolloutStats",
    "WarbandBank",
    "WarbandSample",
    "DeterminizeInfo",
    "determinize",
    "placement_utility",
    "prior_softmax",
]
