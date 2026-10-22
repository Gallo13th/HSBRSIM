"""宽候选生成（beam 用）：整回合 BC macro + heuristic + teacher/random + 首步全动作枚举。

只用于「候选生成」；不做评分/价值网络。硬搜索的评估仍由 env rollout 完成
（``hard_search.HardSearch`` + ``rollout_backend="env"``）。
"""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Sequence

from hsbg.planning.model import RandomRolloutPolicy
from hsbg.search.forward import EngineForwardModel
from hsbg.search.rollout import (
    MacroAction,
    _bc_policy_chooser,
    _heuristic_chooser,
    _random_chooser,
    _run_policy,
    generate_macros_simple,
)
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.search.evaluator import PolicyEvaluator

__all__ = ["generate_wide_candidates"]


def _label(m: Optional[MacroAction], source: str) -> Optional[MacroAction]:
    return None if m is None else replace(m, source=source)


def _first_step_macros(model: EngineForwardModel, *, max_first: int,
                       seed: int, max_steps: int = 40) -> List[MacroAction]:
    """首步全动作枚举：每个合法首动作 + 随机补齐到 end_turn。"""
    out: List[MacroAction] = []
    base = model.clone()
    base.drain_choices()
    cands = base.candidates()
    if not cands:
        return out
    # 优先非 end_turn，避免候选全是 end_turn
    ordered = [c for c in cands if c.kind != "end_turn"] + \
              [c for c in cands if c.kind == "end_turn"]
    for i, first in enumerate(ordered[:max(0, int(max_first))]):
        try:
            dup = model.clone()
            if not dup.apply(first, advance_end_turn=False):
                continue
            steps = [first]
            if first.kind != "end_turn":
                rnd = RandomRolloutPolicy(seed=int(seed) + 9000 + i,
                                          end_turn_prob=0.25)
                m = _run_policy(dup, _random_chooser(rnd), max_steps)
                if m is not None and m.steps:
                    steps.extend(list(m.steps))
            out.append(MacroAction(steps=tuple(steps), source="first_step"))
        except Exception:  # noqa: BLE001
            continue
    return out


def generate_wide_candidates(model: EngineForwardModel,
                             evaluator: Optional[PolicyEvaluator] = None,
                             *, target: int = 12, seed: int = 0,
                             max_first: int = 12,
                             max_steps: int = 40) -> List[MacroAction]:
    """生成去重后的宽候选（目标 8–16 个），并标注来源。"""
    target = max(4, int(target))
    generated: List[MacroAction] = []

    def _add(m: Optional[MacroAction], source: Optional[str] = None) -> None:
        if m is None:
            return
        generated.append(_label(m, source) if source else m)

    # 1) heuristic macro
    try:
        hp = HeuristicPolicy()
        _add(_run_policy(model.clone(), _heuristic_chooser(hp), max_steps),
             "heuristic")
    except Exception:  # noqa: BLE001
        pass
    # 2) 整回合 BC macro（只用于候选生成，不做评分）
    if evaluator is not None:
        try:
            _add(_run_policy(model.clone(), _bc_policy_chooser(evaluator),
                             max_steps), "bc_policy")
        except Exception:  # noqa: BLE001
            pass
    # 3) 随机变体（最多 3 个）
    for m in generate_macros_simple(model.clone(), count=3,
                                    seed=int(seed) + 17,
                                    max_steps=max_steps):
        src = "random" if m.source == "rollout" else str(m.source)
        _add(m, src)
    # 4) 首步全动作枚举
    for m in _first_step_macros(model, max_first=max_first,
                                seed=int(seed), max_steps=max_steps):
        _add(m, "first_step")

    # 去重（保持来源顺序），截断到 target
    seen = set()
    out: List[MacroAction] = []
    for m in generated:
        sig = m.signatures
        if sig in seen:
            continue
        seen.add(sig)
        out.append(m)
        if len(out) >= target:
            break
    return out
