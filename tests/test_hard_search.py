"""硬搜索（train-free）：确定性 / 剪枝 / budget / 无价值网 / 无 hidden 泄漏。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel
from hsbg.search import hard_search as hsm
from hsbg.search.hard_search import (
    HardSearch,
    HardSearchConfig,
    rollout_to_terminal,
)
from hsbg.search.types import MacroAction
from hsbg.env.spec import CandidateAction


def _model(seed: int = 5) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    for _ in range(3):
        pick = next((i for i, c in enumerate(obs.candidates) if c.kind == "buy"), 0)
        obs, *_ = env.step(pick)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def test_rollout_to_terminal_deterministic_and_sane() -> None:
    model = _model(5)
    a = rollout_to_terminal(model, policy="random", seed=7)
    b = rollout_to_terminal(model, policy="random", seed=7)
    assert a["rank"] == b["rank"]
    assert 1 <= a["rank"] <= 8
    assert a["steps"] >= 1
    assert a["truncated"] in (True, False)


def test_prune_macros_cheap_dedupe_and_end_turn() -> None:
    c = CandidateAction(kind="buy", src_zone="tavern", src_slot=0)
    m1 = MacroAction(steps=(c, CandidateAction(kind="end_turn")))
    m2 = MacroAction(steps=(c, CandidateAction(kind="end_turn")))
    m3 = MacroAction(steps=(CandidateAction(kind="end_turn"),))
    out = hsm._prune_macros_cheap([m1, m2, m3], max_macros=4)
    assert len(out) == 1
    assert out[0].steps == m1.steps


def test_hard_search_deterministic_and_budget_effective() -> None:
    model = _model(6)
    cfg = HardSearchConfig(candidates=3, rollout_budget=1, seed=11,
                           rollout_policy="random")
    r1 = HardSearch(cfg).decide(model)
    r2 = HardSearch(cfg).decide(model)
    assert r1.best is not None and r2.best is not None
    assert r1.best.signatures == r2.best.signatures
    assert r1.total_rollouts == r2.total_rollouts
    assert 1 <= r1.total_rollouts <= 3
    # budget=2：successive halving 后总 rollout 不应超过 candidates*budget
    cfg2 = HardSearchConfig(candidates=3, rollout_budget=2, seed=11,
                            rollout_policy="random")
    r3 = HardSearch(cfg2).decide(model)
    assert 1 <= r3.total_rollouts <= 6
    assert r3.total_rollouts >= r1.total_rollouts


def test_no_value_net_import_or_call(monkeypatch) -> None:
    src = open(hsm.__file__, encoding="utf-8").read()
    assert "PolicyEvaluator" not in src
    assert "BCValueScorer" not in src
    assert "hsbg.search.evaluator" not in src
    # 运行 hard search 时若意外调用 BC value，会抛错
    import hsbg.search.evaluator as evmod

    def _boom(*args, **kwargs):
        raise AssertionError("hard search 不应调用价值网")

    monkeypatch.setattr(evmod.PolicyEvaluator, "evaluate", _boom)
    model = _model(7)
    res = HardSearch(HardSearchConfig(candidates=2, rollout_budget=1,
                                      seed=3, rollout_policy="random")).decide(model)
    assert res.best is not None


def test_no_hidden_state_injection(monkeypatch) -> None:
    import hsbg.planning as planning

    def _boom(*args, **kwargs):
        raise AssertionError("hard search 不应注入隐藏状态")

    monkeypatch.setattr(planning.hidden, "inject_hidden_state", _boom)
    model = _model(8)
    res = HardSearch(HardSearchConfig(candidates=2, rollout_budget=1,
                                      seed=1, rollout_policy="random")).decide(model)
    assert res.best is not None
    assert res.oracle_used is False
