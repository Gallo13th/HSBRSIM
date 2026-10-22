"""无训练决策器：剪枝正确性 / 确定性 / 无隐藏信息泄漏。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.env.spec import CandidateAction
from hsbg.search import EngineForwardModel
from hsbg.search.decision import (
    GreedyDecision,
    prune_candidates,
    prune_macros,
    make_decision,
    make_scorer,
)
from hsbg.search.types import MacroAction

CHECKPOINT = Path("runs/bc/official_320/policy_bc.pt")


def _c(kind: str, slot: int = -1) -> CandidateAction:
    return CandidateAction(kind=kind, src_zone="board", src_slot=slot)


def test_prune_candidates_dedupe_and_keep_end_turn() -> None:
    cands = [_c("buy", 0), _c("buy", 0), _c("sell", 1), _c("end_turn")]
    out = prune_candidates(cands, max_candidates=3)
    sigs = [c.signature() for c in out]
    assert len(sigs) == len(set(sigs))
    assert any(c.kind == "end_turn" for c in out)
    assert len(out) <= 3
    # 无 end_turn 时不强加
    out2 = prune_candidates([_c("buy", 0)], keep_end_turn=True)
    assert [c.kind for c in out2] == ["buy"]


def test_prune_macros_dedupe_and_drop_pure_end_turn() -> None:
    m1 = MacroAction(steps=(_c("buy", 0), _c("end_turn")))
    m2 = MacroAction(steps=(_c("buy", 0), _c("end_turn")))
    m3 = MacroAction(steps=(_c("end_turn"),))
    out = prune_macros([m1, m2, m3], max_macros=4, drop_empty_end_turn=True)
    assert len(out) == 1
    assert out[0].signatures == m1.signatures
    # 全是 end_turn 时保留
    out2 = prune_macros([m3], max_macros=4, drop_empty_end_turn=True)
    assert len(out2) == 1


def _model(seed: int = 5) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    for _ in range(3):
        pick = next((i for i, c in enumerate(obs.candidates) if c.kind == "buy"), 0)
        obs, *_ = env.step(pick)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def test_scorers_finite_and_uniform_control() -> None:
    model = _model()
    for name in ("combat", "heuristic", "uniform"):
        s = make_scorer(name)
        v = s.score(model)
        assert np.isfinite(v)
    assert make_scorer("uniform").score(model) == 0.0
    if CHECKPOINT.exists():
        bc = make_scorer("bc_value")
        assert np.isfinite(bc.score(model))


def test_greedy_deterministic_same_seed() -> None:
    model = _model()
    for scorer in ("heuristic", "uniform"):
        d1 = GreedyDecision(make_scorer(scorer), seed=11, macro_candidates=2)
        d2 = GreedyDecision(make_scorer(scorer), seed=11, macro_candidates=2)
        r1 = d1.decide(model)
        r2 = d2.decide(model)
        assert r1.macro is not None and r2.macro is not None
        assert r1.macro.signatures == r2.macro.signatures
        # 每一步都是合法候选（在 clone 上逐条检查）
        dup = model.clone()
        for cand in r1.macro.steps:
            if dup.is_terminal():
                break
            legal = {c.signature() for c in dup.candidates()}
            assert cand.signature() in legal
            assert dup.apply(cand) is True


def test_decision_no_hidden_state_injection(monkeypatch) -> None:
    """决策器不应调用 hidden.inject_hidden_state（K=1/oracle=False）。"""
    import hsbg.planning as planning

    def _boom(*args, **kwargs):
        raise AssertionError("decision 不应注入隐藏状态")

    monkeypatch.setattr(planning.hidden, "inject_hidden_state", _boom)
    model = _model(6)
    for name, kw in (("greedy", {}), ("beam", {"width": 2, "depth": 1})):
        d = make_decision(name, make_scorer("heuristic"), seed=1, **kw)
        r = d.decide(model)
        assert r.macro is not None


def test_puct_decision_smoke() -> None:
    model = _model(7)
    d = make_decision("puct", make_scorer("uniform"), seed=1,
                      width=2, simulations=2)
    r = d.decide(model)
    assert r.macro is not None
    assert r.elapsed_s >= 0.0
