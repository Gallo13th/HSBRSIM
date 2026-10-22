"""硬搜索（train-free）：候选 macro → 自对弈 rollout 到终局/高胜率 → 选择。

**不使用价值网/BC scorer**。评估完全来自引擎 rollout 的终局名次/胜率/前四。
流程：
1. 生成 macro 回合级候选（heuristic/随机变体，现有 ``generate_macros_simple``）；
2. cheap 剪枝（去重、纯 end_turn、上限；不改引擎语义）；
3. 每个候选 clone→执行 macro→rollout 策略（heuristic/随机）推进到终局/最大 horizon；
4. successive halving：先每候选 1 次 rollout，淘汰后半；幸存者加预算；
5. 公共随机数（同 stage 同 seed）降低方差；按期望名次 utility/胜率选动作。

成本可能很高：默认先跑 ``rollout_budget=1``（每候选一次终局 rollout），
``max_horizon_turns>0`` 可限制 horizon（截断时用当前估计名次，报告中单列）。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from hsbg import planning
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.planning.model import RandomRolloutPolicy
from hsbg.search.forward import EngineForwardModel
from hsbg.search.rollout import generate_macros_simple
from hsbg.search.types import MacroAction, placement_utility

__all__ = [
    "HardSearchConfig",
    "CandidateStat",
    "HardSearchResult",
    "HardSearch",
    "rollout_to_terminal",
]


@dataclass
class HardSearchConfig:
    """硬搜索预算（Phase 1.6，pilot 用）。"""

    #: 候选 macro 数（剪枝前生成数）
    candidates: int = 4
    #: 每个候选最多 rollout 次数（successive halving 会减少实际次数）
    rollout_budget: int = 1
    #: 滚动策略："heuristic" / "random" / "epsilon"（heuristic + ε 随机）
    rollout_policy: str = "heuristic"
    #: ε 随机比例（rollout_policy="epsilon" 时生效）
    rollout_epsilon: float = 0.15
    #: 0=到终局；>0=最多这么多回合（截断，报告单列）
    max_horizon_turns: int = 0
    #: 单次 rollout 最大步数（安全阀）
    max_steps: int = 6000
    #: 随机种子（同一决策可复现；公共随机数按 stage 对齐）
    seed: int = 0
    #: 是否 cheap 剪枝（去重/纯 end_turn/上限）
    prune: bool = True
    #: rollout 后端："env"=env-builder 正常对手买牌（推荐）；"legacy"=旧 ERP 退化实现
    rollout_backend: str = "env"
    #: 选择目标："utility"（期望名次）或 "win"（胜率）
    objective: str = "utility"
    #: 两阶段：screen_horizon_turns>0 时先短 horizon 筛 finalists，再 full 复核
    screen_horizon_turns: int = 0
    screen_rollouts: int = 2
    beam_width: int = 0
    finalists: int = 2
    final_rollout_turns: int = 0
    final_rollouts: int = 1

    def __post_init__(self) -> None:
        self.candidates = max(1, int(self.candidates))
        self.rollout_budget = max(1, int(self.rollout_budget))
        self.max_horizon_turns = max(0, int(self.max_horizon_turns))
        self.max_steps = max(1, int(self.max_steps))
        if self.rollout_policy not in ("heuristic", "random", "epsilon"):
            raise ValueError("rollout_policy 必须是 heuristic/random/epsilon")
        self.rollout_epsilon = float(self.rollout_epsilon)
        if not 0.0 <= self.rollout_epsilon <= 1.0:
            raise ValueError("rollout_epsilon 必须在 [0,1]")
        if self.rollout_backend not in ("env", "legacy"):
            raise ValueError("rollout_backend 必须是 env/legacy")
        if self.objective not in ("utility", "win"):
            raise ValueError("objective 必须是 utility/win")
        self.screen_horizon_turns = max(0, int(self.screen_horizon_turns))
        self.screen_rollouts = max(1, int(self.screen_rollouts))
        self.beam_width = max(0, int(self.beam_width))
        self.finalists = max(1, int(self.finalists))
        self.final_rollout_turns = max(0, int(self.final_rollout_turns))
        self.final_rollouts = max(1, int(self.final_rollouts))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "candidates": self.candidates,
            "rollout_budget": self.rollout_budget,
            "rollout_policy": self.rollout_policy,
            "rollout_epsilon": self.rollout_epsilon,
            "max_horizon_turns": self.max_horizon_turns,
            "max_steps": self.max_steps,
            "seed": self.seed,
            "prune": bool(self.prune),
            "rollout_backend": self.rollout_backend,
            "objective": self.objective,
            "screen_horizon_turns": self.screen_horizon_turns,
            "screen_rollouts": self.screen_rollouts,
            "beam_width": self.beam_width,
            "finalists": self.finalists,
            "final_rollout_turns": self.final_rollout_turns,
            "final_rollouts": self.final_rollouts,
        }


@dataclass
class CandidateStat:
    macro: MacroAction
    ranks: List[int] = field(default_factory=list)
    wins: List[bool] = field(default_factory=list)
    top4: List[bool] = field(default_factory=list)
    truncated: List[bool] = field(default_factory=list)
    #: 两阶段筛选（短 horizon）的 ranks
    screen_ranks: List[int] = field(default_factory=list)
    rollouts: int = 0
    steps: int = 0

    @property
    def mean_rank(self) -> float:
        return float(np.mean(self.ranks)) if self.ranks else float("nan")

    @property
    def utility(self) -> float:
        if not self.ranks:
            return float("-inf")
        return float(np.mean([placement_utility(r, 8) for r in self.ranks]))

    @property
    def win_rate(self) -> float:
        return float(np.mean(self.wins)) if self.wins else 0.0

    @property
    def top4_rate(self) -> float:
        return float(np.mean(self.top4)) if self.top4 else 0.0

    @property
    def screen_utility(self) -> float:
        if not self.screen_ranks:
            return float("-inf")
        return float(np.mean([placement_utility(r, 8)
                              for r in self.screen_ranks]))

    @property
    def screen_mean_rank(self) -> float:
        return (float(np.mean(self.screen_ranks))
                if self.screen_ranks else float("nan"))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "macro": self.macro.as_dict(),
            "rollouts": self.rollouts,
            "ranks": list(self.ranks),
            "wins": list(self.wins),
            "top4": list(self.top4),
            "truncated": list(self.truncated),
            "screen_ranks": list(self.screen_ranks),
            "mean_rank": (None if not self.ranks else round(self.mean_rank, 3)),
            "utility": (None if not self.ranks else round(self.utility, 4)),
            "win_rate": round(self.win_rate, 3),
            "top4_rate": round(self.top4_rate, 3),
            "screen_utility": (None if not self.screen_ranks else
                               round(self.screen_utility, 4)),
        }


@dataclass
class HardSearchResult:
    best: Optional[MacroAction]
    stats: List[CandidateStat]
    total_rollouts: int
    elapsed_s: float
    horizon_truncated: int = 0
    oracle_used: bool = False
    config: Optional[HardSearchConfig] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "best": None if self.best is None else self.best.as_dict(),
            "stats": [s.as_dict() for s in self.stats],
            "total_rollouts": int(self.total_rollouts),
            "elapsed_s": float(self.elapsed_s),
            "horizon_truncated": int(self.horizon_truncated),
            "oracle_used": bool(self.oracle_used),
            "config": None if self.config is None else self.config.as_dict(),
        }


# ══════════════════════════════════════════════════════════════════════
# rollout（不使用任何价值网）
# ══════════════════════════════════════════════════════════════════════
class EpsilonHeuristicPolicy:
    """heuristic + ε 随机合法动作（独立 GameRNG，可复现）。"""

    name = "epsilon"

    def __init__(self, *, seed: int = 0, epsilon: float = 0.15) -> None:
        from hsrl2.rng import GameRNG

        from hsbg.planning.rollout_throughput import RandomEnginePolicy

        self.epsilon = float(epsilon)
        self.heur = HeuristicPolicy()
        self.rand = RandomEnginePolicy(seed=int(seed), end_turn_prob=0.2)
        self.rng = GameRNG(int(seed) + 1)

    def choose_action(self, game, hero):
        try:
            if self.rng.random() < self.epsilon:
                return self.rand.choose_action(game, hero)
            desc = self.heur.choose(game, hero)
            return desc if desc is not None else self.rand.choose_action(game, hero)
        except Exception:  # noqa: BLE001
            return None

    def choose_option_index(self, choice, game):
        try:
            return int(self.rand.choose_option_index(choice, game))
        except Exception:  # noqa: BLE001
            return 0


def _rollout_env(model: EngineForwardModel, *, policy: str,
                 max_horizon_turns: int, seed: int,
                 epsilon: float = 0.15) -> Dict[str, Any]:
    """env-builder 的正常对手 rollout（对手买牌；随机化用 rng fork + 策略随机）。"""
    from hsbg.planning.rollout_throughput import (
        HeuristicEnginePolicy,
        RandomEnginePolicy,
        rollout_to_end,
    )

    dup = model.clone()
    try:
        dup.fork_rng(int(seed))
    except Exception:  # noqa: BLE001 - fork 失败仍继续（退化为同 rng）
        pass
    if policy == "heuristic":
        pol = HeuristicEnginePolicy()
        opp = HeuristicEnginePolicy()
    elif policy == "epsilon":
        pol = EpsilonHeuristicPolicy(seed=int(seed), epsilon=epsilon)
        opp = EpsilonHeuristicPolicy(seed=int(seed) + 7919, epsilon=epsilon)
    else:
        pol = RandomEnginePolicy(seed=int(seed), end_turn_prob=0.2)
        opp = RandomEnginePolicy(seed=int(seed) + 104729, end_turn_prob=0.2)
    res, _dup = rollout_to_end(
        dup.game, pol, max_turns=(None if int(max_horizon_turns) <= 0
                                  else int(max_horizon_turns)),
        opponent_policy=opp, fast_opponents=False, clone_state=False)
    rank = int(getattr(res, "rank", 0) or model.rank())
    terminal = bool(getattr(res, "terminated", False)
                    and getattr(res, "finished", True))
    return {
        "rank": rank,
        "win": bool(getattr(res, "champion", False) or rank == 1),
        "top4": bool(rank <= 4),
        "truncated": bool(getattr(res, "truncated", False) or not terminal),
        "terminal": bool(terminal),
        "turns": int(getattr(res, "turns", 0) or 0),
        "steps": int(getattr(res, "steps", 0) or 0),
    }


def rollout_to_terminal(model: EngineForwardModel, *,
                        policy: str = "heuristic",
                        max_horizon_turns: int = 0,
                        max_steps: int = 6000,
                        seed: int = 0,
                        backend: str = "env",
                        epsilon: float = 0.15) -> Dict[str, Any]:
    """从当前 state clone 后 rollout 到终局/最大 horizon；返回名次等统计。

    ``backend="env"``（默认）走 ``hsbg.planning.rollout_throughput.rollout_to_end``：
    **对手正常买牌（heuristic）**，可选自对弈 heuristic；不使用 BC 价值网。
    ``backend="legacy"`` 是旧实现（对手不买牌），仅用于成本/回归对照。

    截断时名次为当前估计值，并记 ``truncated=True``。
    """
    if backend == "env":
        try:
            return _rollout_env(model, policy=policy,
                                max_horizon_turns=max_horizon_turns,
                                seed=seed, epsilon=epsilon)
        except Exception:  # noqa: BLE001 - 失败回退 legacy，但结果仍标 truncated
            out = _rollout_legacy(model, policy=policy,
                                  max_horizon_turns=max_horizon_turns,
                                  max_steps=max_steps, seed=seed)
            out["backend_fallback"] = "legacy"
            return out
    return _rollout_legacy(model, policy=policy,
                           max_horizon_turns=max_horizon_turns,
                           max_steps=max_steps, seed=seed)


def _rollout_legacy(model: EngineForwardModel, *,
                    policy: str = "heuristic",
                    max_horizon_turns: int = 0,
                    max_steps: int = 6000,
                    seed: int = 0) -> Dict[str, Any]:
    dup = model.clone()
    rnd = RandomRolloutPolicy(seed=int(seed), end_turn_prob=0.2)
    heur = HeuristicPolicy() if policy == "heuristic" else None
    turns = 0
    steps = 0
    truncated = False
    while not dup.is_terminal() and steps < int(max_steps):
        if int(max_horizon_turns) > 0 and turns >= int(max_horizon_turns):
            truncated = True
            break
        dup.drain_choices()
        cands = dup.candidates()
        if not cands:
            break
        cand = None
        if heur is not None:
            try:
                desc = heur.choose(dup.game, dup.hero)
                cand = desc.to_candidate() if desc is not None else None
            except Exception:  # noqa: BLE001
                cand = None
        if cand is None:
            try:
                desc = rnd.choose_action(dup.game, dup.hero)
                cand = desc.to_candidate() if desc is not None else None
            except Exception:  # noqa: BLE001
                cand = None
        if cand is None:
            cand = cands[0]
        prev_turn = dup.turn
        ok = dup.apply(cand)  # end_turn 会推进 ERP
        steps += 1
        if not ok:
            break
        if dup.turn > prev_turn:
            turns += 1
    terminal = dup.is_terminal()
    rank = int(dup.rank() if terminal else dup.rank())
    return {
        "rank": rank,
        "win": bool(terminal and rank == 1),
        "top4": bool(rank <= 4),
        "truncated": bool(truncated or not terminal),
        "terminal": bool(terminal),
        "turns": turns,
        "steps": steps,
    }


# ══════════════════════════════════════════════════════════════════════
# 硬搜索
# ══════════════════════════════════════════════════════════════════════
def _prune_macros_cheap(macros: Sequence[MacroAction],
                        max_macros: int) -> List[MacroAction]:
    """去重 + 纯 end_turn 剪枝 + 上限（不依赖 decision/价值网）。"""
    out: List[MacroAction] = []
    seen = set()
    for m in macros:
        sig = m.signatures
        if sig in seen:
            continue
        seen.add(sig)
        out.append(m)
    nonempty = [m for m in out if len(m.steps) > 1]
    if nonempty:
        out = nonempty + [m for m in out
                          if len(m.steps) == 1
                          and str(getattr(m.first, "kind", "")) != "end_turn"]
    return out[:max(1, int(max_macros))]


class HardSearch:
    """候选 macro → rollout 评估 → successive halving / 期望名次选择。"""

    def __init__(self, config: Optional[HardSearchConfig] = None,
                 candidate_macros: Optional[Sequence[MacroAction]] = None) -> None:
        self.config = config or HardSearchConfig()
        self._provided_macros = (None if candidate_macros is None
                                 else list(candidate_macros))

    def decide(self, model: EngineForwardModel) -> HardSearchResult:
        cfg = self.config
        t0 = time.perf_counter()
        if model.is_terminal():
            return HardSearchResult(None, [], 0, time.perf_counter() - t0,
                                    config=cfg)
        if self._provided_macros is not None:
            macros = list(self._provided_macros)
        else:
            macros = generate_macros_simple(
                model.clone(), count=int(cfg.candidates), seed=int(cfg.seed),
                max_steps=40)
        if cfg.prune:
            macros = _prune_macros_cheap(macros, max_macros=int(cfg.candidates))
        if not macros:
            return HardSearchResult(None, [], 0, time.perf_counter() - t0,
                                    config=cfg)

        stats = [CandidateStat(macro=m) for m in macros]
        root = model.clone()
        if cfg.screen_horizon_turns > 0:
            return self._decide_staged(stats, root, t0)
        budget = int(cfg.rollout_budget)
        stage = 0
        survivors: List[int] = list(range(len(stats)))
        while budget > 0 and survivors:
            # 公共随机数：同一 stage 所有候选/rollout 用同一 seed
            stage_seed = int(cfg.seed) * 1_000_003 + stage * 7919
            for i in survivors:
                try:
                    out = rollout_to_terminal(
                        root, policy=cfg.rollout_policy,
                        max_horizon_turns=cfg.max_horizon_turns,
                        max_steps=cfg.max_steps, seed=stage_seed,
                        backend=cfg.rollout_backend, epsilon=cfg.rollout_epsilon)
                except Exception:  # noqa: BLE001
                    out = {"rank": 8, "win": False, "top4": False,
                           "truncated": True, "terminal": False,
                           "turns": 0, "steps": 0}
                st = stats[i]
                st.ranks.append(int(out["rank"]))
                st.wins.append(bool(out["win"]))
                st.top4.append(bool(out["top4"]))
                st.truncated.append(bool(out["truncated"]))
                st.rollouts += 1
                st.steps += int(out["steps"])
            budget -= 1
            stage += 1
            if budget <= 0 or len(survivors) <= 1:
                break
            # successive halving：按当前均值淘汰后半（至少保留 1 个）
            survivors.sort(key=lambda i: self._rank_key(stats[i]))
            keep = max(1, int(math.ceil(len(survivors) / 2.0)))
            survivors = survivors[:keep]

        # 在最终幸存者里选；若某候选没跑到（异常）则退化到全部
        pool = survivors if survivors else list(range(len(stats)))
        best_i = min(pool, key=lambda i: self._rank_key(stats[i]))
        total = sum(s.rollouts for s in stats)
        truncated_count = sum(1 for s in stats for t in s.truncated if t)
        return HardSearchResult(
            best=stats[best_i].macro if stats else None,
            stats=stats, total_rollouts=total,
            elapsed_s=time.perf_counter() - t0,
            horizon_truncated=truncated_count,
            oracle_used=False, config=cfg,
        )

    def _decide_staged(self, stats: List[CandidateStat],
                       root: EngineForwardModel, t0: float) -> HardSearchResult:
        """两阶段：horizon 短筛选 top-finalists，再 full-to-end 复核。"""
        cfg = self.config
        stage_seed = int(cfg.seed) * 1_000_003 + 101
        total = 0
        # 1) 短 horizon 筛选（同 stage 公共随机数）
        for st in stats:
            for r in range(int(cfg.screen_rollouts)):
                out = rollout_to_terminal(
                    root, policy=cfg.rollout_policy,
                    max_horizon_turns=int(cfg.screen_horizon_turns),
                    max_steps=cfg.max_steps, seed=stage_seed + r,
                    backend=cfg.rollout_backend, epsilon=cfg.rollout_epsilon)
                st.screen_ranks.append(int(out["rank"]))
                st.truncated.append(bool(out["truncated"]))
                st.rollouts += 1
                st.steps += int(out["steps"])
                total += 1
        order = sorted(range(len(stats)), key=lambda i: (
            -stats[i].screen_utility, stats[i].screen_mean_rank))
        if int(cfg.beam_width) > 0:
            order = order[:int(cfg.beam_width)]
        finalists = order[:max(1, min(int(cfg.finalists), len(order)))]
        # 2) full（或指定 horizon）复核
        for i in finalists:
            st = stats[i]
            for r in range(int(cfg.final_rollouts)):
                out = rollout_to_terminal(
                    root, policy=cfg.rollout_policy,
                    max_horizon_turns=int(cfg.final_rollout_turns),
                    max_steps=cfg.max_steps, seed=stage_seed + 10_000 + r,
                    backend=cfg.rollout_backend, epsilon=cfg.rollout_epsilon)
                st.ranks.append(int(out["rank"]))
                st.wins.append(bool(out["win"]))
                st.top4.append(bool(out["top4"]))
                st.truncated.append(bool(out["truncated"]))
                st.rollouts += 1
                st.steps += int(out["steps"])
                total += 1
        pool = finalists if finalists else list(range(len(stats)))
        best_i = min(pool, key=lambda i: self._rank_key(stats[i]))
        truncated_count = sum(1 for s in stats for t in s.truncated if t)
        return HardSearchResult(
            best=stats[best_i].macro if stats else None,
            stats=stats, total_rollouts=total,
            elapsed_s=time.perf_counter() - t0,
            horizon_truncated=truncated_count,
            oracle_used=False, config=cfg,
        )

    def _rank_key(self, st: CandidateStat):
        """排序键（越小越好）：utility 高 → 前；胜率/前四作 tie-break。"""
        cfg = self.config
        if cfg.objective == "win":
            return (-st.win_rate, -st.top4_rate, -st.utility,
                    st.mean_rank if st.ranks else 99.0)
        return (-st.utility, -st.win_rate, -st.top4_rate,
                st.mean_rank if st.ranks else 99.0)


def hard_search_decide(model: EngineForwardModel,
                       config: Optional[HardSearchConfig] = None
                       ) -> HardSearchResult:
    return HardSearch(config).decide(model)
