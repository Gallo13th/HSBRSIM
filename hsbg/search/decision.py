"""无训练决策器 / 评分器（Phase 1.5，pilot 用）。

评分器全部冻结、可插拔：
- ``BCValueScorer``：冻结 BC checkpoint 的 rank 价值头（utility/期望名次）；
- ``CombatScorer``：``planning.simulate_turn_combat`` 的胜负/伤害（引擎精确裁决）；
- ``HeuristicScorer``：``planning.evaluate`` 的棋盘/经济启发式；
- ``UniformScorer``：对照（无信息，均匀）。

决策规则（全部无训练）：
- ``GreedyDecision``：macro 1-ply（每回合的 K 条 macro 候选 → clone → scorer → argmax）；
- ``BeamDecision``：宽度 W、深度 D（回合）的 macro beam；
- ``PuctDecision``：复用 ``hsbg.search.mcts``，expand 仅 top-W macro，N=8/16/32；
- ``prune_candidates / prune_macros``：去重、合法过滤、保留 end_turn、简单上限剪枝
  （不改引擎语义）。

隐藏信息：K=1、oracle=False（不读对手隐藏状态）；determinization 数据缺口见
``docs/ALGORITHM_RESEARCH.md`` §3.6。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from hsbg import planning
from hsbg.env.spec import CandidateAction
from hsbg.search.evaluator import PolicyEvaluator
from hsbg.search.forward import EngineForwardModel
from hsbg.search.mcts import run_search
from hsbg.search.rollout import generate_macros_simple
from hsbg.search.types import (
    MacroAction,
    SearchConfig,
    StateEval,
    prior_softmax,
)

__all__ = [
    "Scorer",
    "BCValueScorer",
    "CombatScorer",
    "HeuristicScorer",
    "UniformScorer",
    "prune_candidates",
    "prune_macros",
    "GreedyDecision",
    "BeamDecision",
    "PuctDecision",
    "make_scorer",
    "make_decision",
    "ScorerEvaluator",
]


# ══════════════════════════════════════════════════════════════════════
# Scorers（冻结，不训练）
# ══════════════════════════════════════════════════════════════════════
class Scorer:
    """评分器协议：对 state 打分（越大越好）+ 候选 prior（PUCT 用）。"""

    name = "scorer"

    def score(self, model: EngineForwardModel) -> float:
        raise NotImplementedError

    def prior(self, model: EngineForwardModel,
              candidates: Sequence[CandidateAction]) -> np.ndarray:
        n = len(candidates)
        return np.full(n, 1.0 / n, dtype=np.float64) if n else np.zeros(0)

    def top_action(self, model: EngineForwardModel):
        cands = model.candidates()
        if not cands:
            return None
        p = self.prior(model, cands)
        i = int(np.argmax(p))
        return cands[i], float(p[i])

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name}


class BCValueScorer(Scorer):
    """冻结 BC checkpoint 的 rank 价值头（不训练、不更新权重）。"""

    name = "bc_value"

    def __init__(self, evaluator: Optional[PolicyEvaluator] = None,
                 checkpoint: str = "runs/bc/official_320/policy_bc.pt") -> None:
        self.evaluator = evaluator or PolicyEvaluator(checkpoint)

    def score(self, model: EngineForwardModel) -> float:
        return float(self.evaluator.evaluate(model).value)

    def prior(self, model: EngineForwardModel,
              candidates: Sequence[CandidateAction]) -> np.ndarray:
        ev = self.evaluator.evaluate(model)
        # 候选顺序与 ev.candidates 一致
        if len(ev.candidates) == len(candidates) and ev.prior.size == len(candidates):
            return np.asarray(ev.prior, dtype=np.float64)
        return super().prior(model, candidates)

    def top_action(self, model: EngineForwardModel):
        return self.evaluator.top_action(model)


class CombatScorer(Scorer):
    """引擎精确战斗裁决：``simulate_turn_combat`` 的胜负/伤害。"""

    name = "combat"

    def __init__(self, *, win_weight: float = 1.0, damage_weight: float = 0.02) -> None:
        self.win_weight = float(win_weight)
        self.damage_weight = float(damage_weight)

    def score(self, model: EngineForwardModel) -> float:
        if model.is_terminal():
            return float(model.terminal_utility())
        try:
            summary, _ = planning.simulate_turn_combat(
                model.game, model.hero, keep_state=False)
        except Exception:  # noqa: BLE001
            return -1.0
        if not isinstance(summary, dict):
            return -1.0
        win = summary.get("winner_is_hero")
        if win is None:
            win = bool(summary.get("hero_alive_after"))
        signal = 1.0 if win else (-1.0 if summary.get("loser") is not None else 0.0)
        dmg = float(summary.get("damage_dealt", 0) or 0)
        return float(self.win_weight * signal + self.damage_weight * dmg)


class HeuristicScorer(Scorer):
    """现有 heuristic/teacher 的棋盘/经济评分（planning.evaluate）。"""

    name = "heuristic"

    def score(self, model: EngineForwardModel) -> float:
        if model.is_terminal():
            return float(model.terminal_utility())
        try:
            return float(planning.evaluate(model.game, model.hero).get("value", 0.0))
        except Exception:  # noqa: BLE001
            return 0.0


class UniformScorer(Scorer):
    """对照：无信息评分（均匀 prior/固定 0 分）。"""

    name = "uniform"

    def score(self, model: EngineForwardModel) -> float:
        return 0.0


def make_scorer(name: str) -> Scorer:
    key = name.strip().lower()
    if key in ("bc", "bc_value", "bcvalue"):
        return BCValueScorer()
    if key in ("combat", "combat_score"):
        return CombatScorer()
    if key in ("heuristic", "heuristic_score"):
        return HeuristicScorer()
    if key in ("uniform", "none", "random"):
        return UniformScorer()
    raise ValueError(f"未知 scorer: {name}")


# ══════════════════════════════════════════════════════════════════════
# 剪枝规则（只过滤候选，不改引擎语义）
# ══════════════════════════════════════════════════════════════════════
_KIND_PRIORITY = {
    "end_turn": 100, "choose": 99, "upgrade": 90, "use_dark_gift": 85,
    "hero_power": 80, "buy": 70, "play_minion": 65, "play_spell": 60,
    "reroll": 50, "freeze": 40, "activate": 30, "sell": 20,
}


def prune_candidates(candidates: Sequence[CandidateAction],
                     *, max_candidates: int = 8,
                     keep_end_turn: bool = True) -> Tuple[CandidateAction, ...]:
    """去重 + 类别优先级 + 上限；保证保留 end_turn（若有）。"""
    out: List[CandidateAction] = []
    seen = set()
    for c in candidates:
        sig = c.signature()
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    if keep_end_turn:
        ends = [c for c in out if str(getattr(c, "kind", "")) == "end_turn"]
        others = [c for c in out if str(getattr(c, "kind", "")) != "end_turn"]
        others.sort(key=lambda c: -_KIND_PRIORITY.get(str(c.kind), 0))
        room = max(0, int(max_candidates) - len(ends))
        out2 = others[:room] + ends
        return tuple(out2)
    out.sort(key=lambda c: -_KIND_PRIORITY.get(str(c.kind), 0))
    return tuple(out[:max(1, int(max_candidates))])


def prune_macros(macros: Sequence[MacroAction], *,
                 max_macros: int = 4,
                 drop_empty_end_turn: bool = True) -> Tuple[MacroAction, ...]:
    """macro 去重 + 上限；可选丢弃纯 end_turn（若有非空 macro）。"""
    out: List[MacroAction] = []
    seen = set()
    for m in macros:
        sig = m.signatures
        if sig in seen:
            continue
        seen.add(sig)
        out.append(m)
    if drop_empty_end_turn:
        nonempty = [m for m in out if len(m.steps) > 1]
        if nonempty:
            out = nonempty + [m for m in out
                              if len(m.steps) == 1
                              and str(getattr(m.first, "kind", "")) != "end_turn"]
    return tuple(out[:max(1, int(max_macros))])


# ══════════════════════════════════════════════════════════════════════
# MCTS 适配：把任意 Scorer 当成 evaluator
# ══════════════════════════════════════════════════════════════════════
class ScorerEvaluator:
    """给 MCTS 用的 evaluator 适配（value=scorer，prior=scorer.prior）。"""

    def __init__(self, scorer: Scorer) -> None:
        self.scorer = scorer

    def evaluate(self, model: EngineForwardModel) -> StateEval:
        candidates = () if model.is_terminal() else model.candidates()
        if model.is_terminal():
            return StateEval(candidates=(), prior=np.zeros(0),
                             value=float(model.terminal_utility()),
                             expected_rank=float(model.rank()),
                             rank_probs=np.zeros(model.total_players))
        prior = self.scorer.prior(model, candidates)
        return StateEval(
            candidates=candidates, prior=np.asarray(prior, dtype=np.float64),
            value=float(self.scorer.score(model)),
            expected_rank=float(model.rank()),
            rank_probs=np.zeros(model.total_players),
        )

    def top_action(self, model: EngineForwardModel):
        return self.scorer.top_action(model)


# ══════════════════════════════════════════════════════════════════════
# 决策规则
# ══════════════════════════════════════════════════════════════════════
@dataclass
class DecisionResult:
    macro: Optional[MacroAction]
    score: float = 0.0
    n_evaluated: int = 0
    elapsed_s: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


class _BaseDecision:
    name = "base"

    def __init__(self, scorer: Scorer, *, seed: int = 0,
                 max_steps: int = 40) -> None:
        self.scorer = scorer
        self.seed = int(seed)
        self.max_steps = int(max_steps)

    def decide(self, model: EngineForwardModel) -> DecisionResult:
        raise NotImplementedError

    def _macros(self, model: EngineForwardModel, count: int,
                seed_offset: int = 0) -> List[MacroAction]:
        # BC scorer 需要包含“BC 策略首步”的 macro，否则 BC 评分器会被
        # heuristic/random macro 集合限制（公平性；不训练，只用冻结 BC prior）。
        if isinstance(self.scorer, BCValueScorer):
            from hsbg.search.rollout import generate_macros

            cfg = SearchConfig(
                simulations=1, macro_candidates=max(1, int(count)),
                max_depth_turns=1, seed=self.seed + seed_offset,
                use_bc_first_macro=False, bc_full_macro=True,
                prior_mode="bc", leaf_mode="combat")
            try:
                return generate_macros(
                    model.clone(), self.scorer.evaluator, cfg)
            except Exception:  # noqa: BLE001 - 回退 simple
                pass
        return generate_macros_simple(
            model.clone(), count=count, seed=self.seed + seed_offset,
            max_steps=self.max_steps)


class GreedyDecision(_BaseDecision):
    """macro 1-ply：每个 macro 候选 clone→apply→scorer→argmax。"""

    name = "greedy_1ply"

    def __init__(self, scorer: Scorer, *, seed: int = 0,
                 macro_candidates: int = 4, **kw) -> None:
        super().__init__(scorer, seed=seed, **kw)
        self.macro_candidates = int(macro_candidates)

    def decide(self, model: EngineForwardModel) -> DecisionResult:
        import time
        t0 = time.perf_counter()
        macros = prune_macros(self._macros(model, self.macro_candidates),
                              max_macros=self.macro_candidates)
        if not macros:
            return DecisionResult(None, elapsed_s=time.perf_counter() - t0)
        scores: List[float] = []
        for m in macros:
            try:
                dup = model.clone()
                ok = dup.apply_macro(m)
                s = self.scorer.score(dup) if ok else -1e9
            except Exception:  # noqa: BLE001
                s = -1e9
            scores.append(float(s))
        i = int(np.argmax(scores))
        return DecisionResult(macros[i], score=scores[i],
                              n_evaluated=len(macros),
                              elapsed_s=time.perf_counter() - t0,
                              extra={"scores": scores})


class BeamDecision(_BaseDecision):
    """macro beam：宽度 W、深度 D 回合，按 scorer 剪枝。"""

    name = "beam"

    def __init__(self, scorer: Scorer, *, width: int = 2, depth: int = 1,
                 seed: int = 0, macro_candidates: int = 3, **kw) -> None:
        super().__init__(scorer, seed=seed, **kw)
        self.width = int(width)
        self.depth = int(depth)
        self.macro_candidates = int(macro_candidates)

    def decide(self, model: EngineForwardModel) -> DecisionResult:
        import time
        t0 = time.perf_counter()
        beam: List[Tuple[List[MacroAction], float, EngineForwardModel]] = [
            ([], float("-inf"), model.clone())]
        n_eval = 0
        for d in range(max(1, self.depth)):
            candidates: List[Tuple[List[MacroAction], float, EngineForwardModel]] = []
            for path, _, state in beam:
                try:
                    macros = prune_macros(
                        self._macros(state, self.macro_candidates,
                                     seed_offset=d * 10),
                        max_macros=self.macro_candidates)
                except Exception:  # noqa: BLE001
                    continue
                for m in macros:
                    try:
                        dup = state.clone()
                        ok = dup.apply_macro(m)
                        s = self.scorer.score(dup) if ok else -1e9
                    except Exception:  # noqa: BLE001
                        s = -1e9
                        dup = state
                    n_eval += 1
                    candidates.append((path + [m], float(s), dup))
            if not candidates:
                break
            candidates.sort(key=lambda x: -x[1])
            beam = candidates[:max(1, self.width)]
        if not beam:
            return DecisionResult(None, elapsed_s=time.perf_counter() - t0)
        path, score, _ = beam[0]
        return DecisionResult(path[0] if path else None, score=score,
                              n_evaluated=n_eval,
                              elapsed_s=time.perf_counter() - t0,
                              extra={"path_len": len(path)})


class PuctDecision(_BaseDecision):
    """复用 MCTS：expand 仅 top-W macro，N=8/16/32。"""

    name = "puct"

    def __init__(self, scorer: Scorer, *, width: int = 2, simulations: int = 8,
                 seed: int = 0, **kw) -> None:
        super().__init__(scorer, seed=seed, **kw)
        self.width = int(width)
        self.simulations = int(simulations)

    def decide(self, model: EngineForwardModel) -> DecisionResult:
        import time
        t0 = time.perf_counter()
        is_bc = isinstance(self.scorer, BCValueScorer)
        cfg = SearchConfig(
            simulations=self.simulations,
            macro_candidates=max(1, self.width),
            max_depth_turns=1,
            seed=self.seed,
            prior_mode="bc" if is_bc else "uniform",
            leaf_mode="combat" if is_bc else "erp",
            use_bc_first_macro=False,
            bc_full_macro=is_bc,
            cache_root_values=False,
        )
        ev = ScorerEvaluator(self.scorer)
        res = run_search(model, ev, cfg)  # duck-typed evaluator
        return DecisionResult(res.best_macro, score=float(
            np.nanmax(res.root_values)) if np.isfinite(res.root_values).any()
            else 0.0,
            n_evaluated=len(res.root_macros),
            elapsed_s=time.perf_counter() - t0,
            extra={"pi": res.pi.tolist(), "visits": res.visits.tolist()})


def make_decision(name: str, scorer: Scorer, *, seed: int = 0,
                  width: int = 2, depth: int = 1,
                  simulations: int = 8, macro_candidates: int = 4
                  ) -> _BaseDecision:
    key = name.strip().lower()
    if key in ("greedy", "greedy_1ply", "1ply"):
        return GreedyDecision(scorer, seed=seed,
                              macro_candidates=macro_candidates)
    if key.startswith("beam"):
        return BeamDecision(scorer, width=width, depth=depth, seed=seed,
                            macro_candidates=macro_candidates)
    if key.startswith("puct"):
        return PuctDecision(scorer, width=width, simulations=simulations,
                            seed=seed)
    raise ValueError(f"未知 decision: {name}")
