"""Macro 动作生成（rollout policy）。

Phase 1 不做逐动作全宽搜索；每个 macro = 一个招募回合内的动作序列（末尾 end_turn）。
生成 K 条候选（按成本从低到高）：
1. heuristic 引擎策略（便宜、行为合理）；
2. BC-greedy：第一步用评估器 prior 的 top-1，其余用随机 rollout（带策略先验的多样本）；
3. random rollout（不同 seed / end_turn 概率，提供探索）。

所有 macro 都来自合法候选；生成时在 clone 上执行，不污染搜索树/原对局。
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from hsbg import planning
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env.spec import CandidateAction
from hsbg.planning.model import RandomRolloutPolicy
from hsbg.search.evaluator import PolicyEvaluator
from hsbg.search.forward import ACTION_END_TURN, EngineForwardModel
from hsbg.search.types import MacroAction, SearchConfig

__all__ = ["generate_macros", "generate_macros_simple", "RolloutStats"]


class RolloutStats:
    """生成 macro 的调试统计（bench/debug 用）。"""

    def __init__(self) -> None:
        self.attempts: int = 0
        self.kept: int = 0
        self.steps: int = 0
        self.terminated: int = 0

    def as_dict(self) -> dict:
        return {"attempts": self.attempts, "kept": self.kept,
                "steps": self.steps, "terminated": self.terminated}


def _copy_candidate(desc: object) -> Optional[CandidateAction]:
    try:
        return desc.to_candidate()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None


def _run_policy(model: EngineForwardModel,
                chooser: Callable[[EngineForwardModel], Optional[CandidateAction]],
                max_steps: int) -> Optional[MacroAction]:
    """在 model 上执行 chooser 直到 end_turn/终局；返回 macro。"""
    steps: List[CandidateAction] = []
    for _ in range(max(1, int(max_steps))):
        if model.is_terminal():
            break
        model.drain_choices()
        cand = chooser(model)
        if cand is None:
            break
        steps.append(cand)
        # macro 生成不需要跑完整 ERP：end_turn 后 macro 即结束；
        # 叶节点价值另用 simulate_turn_combat（见 forward.combat_leaf）。
        ok = model.apply(cand, advance_end_turn=False)
        if not ok:
            break
        if str(getattr(cand, "kind", "")) == ACTION_END_TURN:
            break
    if not steps:
        return None
    return MacroAction(steps=tuple(steps), source="rollout")


def _heuristic_chooser(policy: HeuristicPolicy
                       ) -> Callable[[EngineForwardModel], Optional[CandidateAction]]:
    def chooser(model: EngineForwardModel) -> Optional[CandidateAction]:
        try:
            desc = policy.choose(model.game, model.hero)
        except Exception:  # noqa: BLE001
            desc = None
        if desc is not None:
            return _copy_candidate(desc)
        ends = [d for d in model.legal_actions()
                if str(getattr(d, "kind", "")) == ACTION_END_TURN]
        return _copy_candidate(ends[0]) if ends else None

    return chooser


def _random_chooser(policy: RandomRolloutPolicy
                    ) -> Callable[[EngineForwardModel], Optional[CandidateAction]]:
    def chooser(model: EngineForwardModel) -> Optional[CandidateAction]:
        try:
            desc = policy.choose_action(model.game, model.hero)
        except Exception:  # noqa: BLE001
            desc = None
        if desc is not None:
            return _copy_candidate(desc)
        actions = model.legal_actions()
        if not actions:
            return None
        return _copy_candidate(actions[0])

    return chooser


def _bc_first_chooser(evaluator: PolicyEvaluator,
                      fallback: RandomRolloutPolicy) -> Callable[[EngineForwardModel], Optional[CandidateAction]]:
    state = {"first": True}

    def chooser(model: EngineForwardModel) -> Optional[CandidateAction]:
        if state["first"]:
            state["first"] = False
            top = evaluator.top_action(model)
            if top is not None:
                return top[0]
        try:
            desc = fallback.choose_action(model.game, model.hero)
        except Exception:  # noqa: BLE001
            desc = None
        return _copy_candidate(desc) if desc is not None else None

    return chooser


def _bc_policy_chooser(evaluator: PolicyEvaluator
                       ) -> Callable[[EngineForwardModel], Optional[CandidateAction]]:
    """整回合都用 BC 策略（每步 top-1）——决策器公平对比用。"""

    def chooser(model: EngineForwardModel) -> Optional[CandidateAction]:
        try:
            top = evaluator.top_action(model)
        except Exception:  # noqa: BLE001
            top = None
        if top is not None:
            return top[0]
        ends = [d for d in model.legal_actions()
                if str(getattr(d, "kind", "")) == ACTION_END_TURN]
        return _copy_candidate(ends[0]) if ends else None

    return chooser


def _direct_end_turn(model: EngineForwardModel) -> Optional[MacroAction]:
    ends = [d for d in model.legal_actions()
            if str(getattr(d, "kind", "")) == ACTION_END_TURN]
    if not ends:
        return None
    cand = _copy_candidate(ends[0])
    if cand is None:
        return None
    return MacroAction(steps=(cand,), source="end_turn")


def generate_macros_simple(model: EngineForwardModel, *,
                           count: int = 4, seed: int = 0,
                           max_steps: int = 40) -> List[MacroAction]:
    """不依赖 BC evaluator 的 macro 候选（heuristic + random rollout）。

    用于无训练决策器（greedy/beam/PUCT 的非 BC scorer）；只应用动作、不跑 ERP。
    """
    if model.is_terminal() or count <= 0:
        return []
    base = model.clone()
    base.drain_choices()
    cands = base.candidates()
    if not cands:
        return []
    if all(str(getattr(c, "kind", "")) == ACTION_END_TURN for c in cands):
        m = _direct_end_turn(base)
        return [m] if m is not None else []

    macros: List[MacroAction] = []
    seen: set = set()

    def _add(m: Optional[MacroAction]) -> None:
        if m is None:
            return
        sigs = m.signatures
        if sigs in seen:
            return
        seen.add(sigs)
        macros.append(m)

    try:
        hp = HeuristicPolicy()
        _add(_run_policy(base.clone(), _heuristic_chooser(hp), max_steps))
    except Exception:  # noqa: BLE001
        pass
    variant = 0
    while len(macros) < count and variant < 8:
        prob = [0.15, 0.30, 0.45, 0.60][variant % 4]
        rnd = RandomRolloutPolicy(seed=int(seed) + 500 + variant,
                                  end_turn_prob=prob)
        _add(_run_policy(base.clone(), _random_chooser(rnd), max_steps))
        variant += 1
    return macros[:count]


def generate_macros(model: EngineForwardModel,
                    evaluator: PolicyEvaluator,
                    config: SearchConfig,
                    *, stats: Optional[RolloutStats] = None) -> List[MacroAction]:
    """生成去重后的 macro 候选（数量 ≤ ``config.macro_candidates``）。"""
    stats = stats or RolloutStats()
    count = int(config.macro_candidates)
    if model.is_terminal() or count <= 0:
        return []

    base = model.clone()
    base.drain_choices()
    cands = base.candidates()
    if not cands:
        return []
    if all(str(getattr(c, "kind", "")) == ACTION_END_TURN for c in cands):
        m = _direct_end_turn(base)
        return [m] if m is not None else []

    macros: List[MacroAction] = []
    seen: set = set()

    def _add(m: Optional[MacroAction]) -> None:
        if m is None:
            return
        stats.attempts += 1
        sigs = m.signatures
        if sigs in seen:
            return
        seen.add(sigs)
        stats.steps += len(m.steps)
        if str(getattr(m.last, "kind", "")) == ACTION_END_TURN:
            macros.append(m)
        else:
            macros.append(m)

    # 1) heuristic 引擎策略
    try:
        hp = HeuristicPolicy()
        _add(_run_policy(base.clone(), _heuristic_chooser(hp),
                         config.max_steps_per_macro))
    except Exception:  # noqa: BLE001
        pass

    # 2a) 整回合 BC 策略 macro（决策器公平对比用；可关闭）
    if config.bc_full_macro and len(macros) < count:
        _add(_run_policy(base.clone(), _bc_policy_chooser(evaluator),
                         config.max_steps_per_macro))

    # 2b) BC-greedy 首步 + 随机（可消融关闭，用于验证 search-vs-BC 不靠“喂答案”）
    if (not config.bc_full_macro) and config.use_bc_first_macro \
            and len(macros) < count:
        rnd = RandomRolloutPolicy(seed=int(config.seed) + 101,
                                  end_turn_prob=0.25)
        _add(_run_policy(base.clone(), _bc_first_chooser(evaluator, rnd),
                         config.max_steps_per_macro))

    # 3) random rollout 变体
    variant = 0
    while len(macros) < count and variant < 8:
        prob = [0.15, 0.30, 0.45, 0.60][variant % 4]
        rnd = RandomRolloutPolicy(seed=int(config.seed) + 200 + variant,
                                  end_turn_prob=prob)
        _add(_run_policy(base.clone(), _random_chooser(rnd),
                         config.max_steps_per_macro))
        variant += 1

    stats.kept = len(macros)
    return macros[:count]
