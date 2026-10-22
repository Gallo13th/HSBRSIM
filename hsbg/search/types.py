"""Phase 1 搜索原语：config / macro action / PUCT 节点 / 结果类型。

设计对应 ``docs/ALGORITHM_RESEARCH.md`` §6：
- 先 **macro 回合级**：一条 ``MacroAction`` = 一个招募回合内的动作序列（末尾 ``end_turn``）；
- 世界线 K=1（Phase 1）；tree depth 默认 1（根节点 macro bandit），可配 2；
- 价值 = 自己的 placement utility ∈ [-1, 1]（非 minimax；7 个对手视为环境随机性）；
- Phase 1 不训练、不接 PPO/BC 训练管线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from hsbg.env.spec import CandidateAction, Observation

__all__ = [
    "MacroAction",
    "SearchConfig",
    "Node",
    "SearchResult",
    "StateEval",
    "placement_utility",
    "prior_softmax",
]


def placement_utility(rank: int, num_players: int = 8) -> float:
    """名次 → utility（与 ``RewardConfig.placement`` 一致：第 1=+1，最后=-1）。"""
    rank = int(rank)
    n = int(num_players)
    if n <= 1:
        return 1.0
    rank = max(1, min(rank, n))
    return 1.0 - 2.0 * (rank - 1) / (n - 1)


def prior_softmax(logits: Sequence[float], *, temperature: float = 1.0,
                  mask: Optional[Sequence[bool]] = None) -> np.ndarray:
    """数值稳定的 masked softmax（返回 float64，和=1；无合法项返回空）。"""
    arr = np.asarray(list(logits), dtype=np.float64)
    if arr.size == 0:
        return np.zeros(0, dtype=np.float64)
    if mask is not None:
        m = np.asarray(list(mask), dtype=bool)
        if m.size != arr.size:
            raise ValueError("mask 长度与 logits 不一致")
        if not m.any():
            return np.zeros(0, dtype=np.float64)
        arr = np.where(m, arr, -np.inf)
    temp = max(1e-6, float(temperature))
    z = arr / temp
    z = z - np.max(z[arr > -np.inf]) if np.isfinite(z).any() else z
    e = np.exp(z)
    e[~np.isfinite(z)] = 0.0
    s = float(e.sum())
    if s <= 0.0:
        out = np.zeros_like(e)
        out[arr > -np.inf] = 1.0 / max(1, int(np.sum(arr > -np.inf)))
        return out
    return e / s


@dataclass(frozen=True)
class MacroAction:
    """一个招募回合的 macro 动作：按顺序应用的候选动作（最后一个为 end_turn）。

    Phase 1 的 macro 由 rollout policy 生成；搜索在树边上是 macro，而不是逐动作。
    """

    steps: Tuple[CandidateAction, ...]
    source: str = ""

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("MacroAction.steps 不能为空")

    @property
    def first(self) -> CandidateAction:
        return self.steps[0]

    @property
    def last(self) -> CandidateAction:
        return self.steps[-1]

    @property
    def signatures(self) -> Tuple[Tuple[Any, ...], ...]:
        return tuple(c.signature() for c in self.steps)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "n_steps": len(self.steps),
            "kinds": [c.kind for c in self.steps],
            "signatures": [list(s) for s in self.signatures],
        }


@dataclass
class SearchConfig:
    """Phase 1 搜索预算（按 env-builder clone=6.49ms 校准）。"""

    #: 每次决策的模拟次数（Phase 1 验收用 1/8/16/32）
    simulations: int = 16
    #: 每节点生成的 macro 候选数（K）
    macro_candidates: int = 4
    #: macro 树深度（回合数）；Phase 1 默认 1（根 macro bandit）
    max_depth_turns: int = 1
    #: PUCT 探索常数
    c_puct: float = 2.0
    #: determinization 世界线条数（Phase 1 固定 1）
    world_lines: int = 1
    #: policy prior 温度（1=原样）
    prior_temperature: float = 1.0
    #: 随机种子（macro 生成/rollout/抽样）
    seed: int = 0
    #: 是否生成“BC 首步 + 随机补齐”的 macro（用于 search-vs-BC 解释/消融）
    use_bc_first_macro: bool = True
    #: 是否生成“整回合都用 BC 策略”的 macro（决策器公平对比用；成本更高）
    bc_full_macro: bool = False
    #: prior 模式："bc"（默认，BC logits）/"uniform"（消融：排除 prior 影响）
    prior_mode: str = "bc"
    #: 叶价值模式："combat"（simulate_turn_combat，快，默认 Phase1）/"erp"（完整下一回合）
    leaf_mode: str = "combat"
    #: Phase 1 K=1 确定性优化：每个 root macro 只算一次叶结果（True=省 clone/rollout；
    #: False=逐 sim clone+apply，更接近标准 MCTS）。默认 False（用新 clone 1.63ms 跑真 MCTS）。
    cache_root_values: bool = False
    #: 单 macro 最多动作数（防死循环）
    max_steps_per_macro: int = 40
    #: True = 允许读取引擎隐藏状态（仅训练期 teacher；Phase 1 必须 False）
    oracle: bool = False
    #: >0 时到预算提前停止（Phase 1 默认关闭，保证 sims 可比）
    time_budget_s: float = 0.0

    def __post_init__(self) -> None:
        self.simulations = int(self.simulations)
        self.macro_candidates = int(self.macro_candidates)
        self.max_depth_turns = int(self.max_depth_turns)
        self.world_lines = int(self.world_lines)
        self.max_steps_per_macro = int(self.max_steps_per_macro)
        if self.simulations < 1:
            raise ValueError("simulations 必须 >=1")
        if not 1 <= self.macro_candidates <= 16:
            raise ValueError("macro_candidates 必须在 1..16")
        if not 1 <= self.max_depth_turns <= 4:
            raise ValueError("max_depth_turns 必须在 1..4")
        if self.world_lines != 1:
            # Phase 1 只实现 K=1；K>1 留给 clone 优化后（见 ROADMAP/文档）
            raise ValueError("Phase 1 仅支持 world_lines=1")
        if self.oracle:
            raise ValueError("Phase 1 禁止 oracle=True（会泄漏隐藏信息）")
        if self.prior_mode not in ("bc", "uniform"):
            raise ValueError("prior_mode 必须是 'bc' 或 'uniform'")
        if self.leaf_mode not in ("combat", "erp"):
            raise ValueError("leaf_mode 必须是 'combat' 或 'erp'")
        self.c_puct = float(self.c_puct)
        self.prior_temperature = float(self.prior_temperature)
        self.time_budget_s = float(self.time_budget_s)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "simulations": self.simulations,
            "macro_candidates": self.macro_candidates,
            "max_depth_turns": self.max_depth_turns,
            "c_puct": self.c_puct,
            "world_lines": self.world_lines,
            "prior_temperature": self.prior_temperature,
            "seed": self.seed,
            "max_steps_per_macro": self.max_steps_per_macro,
            "use_bc_first_macro": bool(self.use_bc_first_macro),
            "bc_full_macro": bool(self.bc_full_macro),
            "prior_mode": self.prior_mode,
            "leaf_mode": self.leaf_mode,
            "cache_root_values": bool(self.cache_root_values),
            "oracle": self.oracle,
            "time_budget_s": self.time_budget_s,
        }


@dataclass
class Node:
    """PUCT 树节点；边是 macro。统计量：N/value_sum；Q=N==0 ? 0 : value_sum/N。"""

    depth: int = 0
    macros: Optional[List[MacroAction]] = None
    priors: Optional[np.ndarray] = None
    children: List[Optional["Node"]] = field(default_factory=list)
    N: int = 0
    value_sum: float = 0.0
    terminal: bool = False

    @property
    def expanded(self) -> bool:
        return self.macros is not None

    @property
    def Q(self) -> float:
        return self.value_sum / self.N if self.N > 0 else 0.0

    def init_children(self) -> None:
        if self.macros is None:
            self.children = []
            return
        self.children = [None] * len(self.macros)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "depth": self.depth,
            "expanded": self.expanded,
            "n_macros": 0 if self.macros is None else len(self.macros),
            "N": self.N,
            "Q": self.Q,
        }


@dataclass
class StateEval:
    """一个状态的评估：候选 prior + placement utility 价值。"""

    candidates: Tuple[CandidateAction, ...]
    prior: np.ndarray
    value: float
    expected_rank: float
    rank_probs: np.ndarray
    obs: Optional[Observation] = None

    def prior_of_first(self, macro: MacroAction) -> float:
        """macro 的先验 = 其第一个动作在当前候选里的 prior（找不到则 0）。"""
        if not self.candidates:
            return 0.0
        target = macro.first.signature()
        for i, cand in enumerate(self.candidates):
            if cand.signature() == target:
                return float(self.prior[i]) if i < len(self.prior) else 0.0
        return 0.0

    def macro_priors(self, macros: Sequence[MacroAction],
                     *, uniform_if_missing: bool = True) -> np.ndarray:
        arr = np.asarray([self.prior_of_first(m) for m in macros], dtype=np.float64)
        if arr.size == 0:
            return arr
        if arr.sum() <= 0.0 and uniform_if_missing:
            arr = np.full(arr.shape, 1.0 / len(arr), dtype=np.float64)
        elif arr.sum() <= 0.0:
            arr = np.zeros(arr.shape, dtype=np.float64)
        else:
            arr = arr / arr.sum()
        return arr


@dataclass
class SearchResult:
    """一次 root 搜索的输出。"""

    best_macro: Optional[MacroAction]
    pi: np.ndarray
    visits: np.ndarray
    root_prior: np.ndarray
    simulations: int
    elapsed_s: float
    n_expansions: int = 0
    oracle_used: bool = False
    hidden_info_mode: str = "none"
    #: 根 macro 的叶价值（K=1 缓存；深度>1 或未访问为 nan）
    root_values: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    #: 根 macro 候选（用于 report/消融；Phase 1 K≤4）
    root_macros: Tuple[MacroAction, ...] = ()
    #: best macro 在 root 的下标
    best_index: int = -1

    @property
    def first_action(self) -> Optional[CandidateAction]:
        return self.best_macro.first if self.best_macro is not None else None

    @property
    def policy_entropy(self) -> float:
        p = np.asarray(self.pi, dtype=np.float64)
        p = p[p > 0]
        if p.size == 0:
            return 0.0
        return float(-(p * np.log(p)).sum())

    def as_dict(self) -> Dict[str, Any]:
        return {
            "best_macro": None if self.best_macro is None else self.best_macro.as_dict(),
            "best_first": (None if self.best_macro is None
                           else self.best_macro.first.signature()),
            "pi": [float(x) for x in np.asarray(self.pi).tolist()],
            "visits": [int(x) for x in np.asarray(self.visits).tolist()],
            "root_prior": [float(x) for x in np.asarray(self.root_prior).tolist()],
            "root_values": [float(x) for x in np.asarray(self.root_values).tolist()],
            "root_macros": [m.as_dict() for m in self.root_macros],
            "root_firsts": [list(m.first.signature()) for m in self.root_macros],
            "best_index": int(self.best_index),
            "simulations": int(self.simulations),
            "elapsed_s": float(self.elapsed_s),
            "n_expansions": int(self.n_expansions),
            "policy_entropy": self.policy_entropy,
            "oracle_used": bool(self.oracle_used),
            "hidden_info_mode": self.hidden_info_mode,
        }
