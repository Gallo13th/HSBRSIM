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

from hsbg.search.types import (  # noqa: F401
    MacroAction,
    Node,
    SearchConfig,
    SearchResult,
    StateEval,
    placement_utility,
    prior_softmax,
)

# 旧 Phase1 搜索实现依赖 torch/hsrl2；在无 torch（或 torch 无 CUDA 库）的
# 训练/评测机上 import 本包不应失败——engine_mcts / pipeline smoke 只用 types。
try:  # pragma: no cover - 环境相关
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
except Exception as _search_import_error:  # noqa: BLE001
    _SEARCH_IMPORT_ERROR = _search_import_error
    DeterminizeInfo = WarbandBank = WarbandSample = None
    determinize = None
    PolicyEvaluator = None
    EngineForwardModel = None
    MCTS = run_search = None
    RolloutStats = generate_macros = None

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
