"""回合内自枚举 + 两两胜率搜索：合法性/同回合/矩阵/确定性/budget/无泄漏。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel
from hsbg.search.turn_search import (
    TurnSearch,
    TurnSearchConfig,
    enumerate_turn_states,
    pairwise_winrate_matrix,
)


def _model(seed: int = 5, buys: int = 4) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    for _ in range(buys):
        pick = next((i for i, c in enumerate(obs.candidates) if c.kind == "buy"), 0)
        obs, *_ = env.step(pick)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def test_enumerate_only_current_turn() -> None:
    model = _model(6)
    cfg = TurnSearchConfig(states_budget=8, samples_per_action=1, seed=1)
    states = enumerate_turn_states(model, cfg)
    flat = [st for rows in states.values() for st in rows]
    assert flat, "应枚举出至少一个 turn-end 状态"
    for st in flat:
        assert st.model.turn == model.turn
        # 动作序列不应已推进回合（end_turn 未执行）
        assert str(st.actions[-1].kind) == "end_turn"


def test_pairwise_matrix_shape_and_symmetry() -> None:
    model = _model(7)
    cfg = TurnSearchConfig(states_budget=8, samples_per_action=1, seed=2)
    by_action = enumerate_turn_states(model, cfg)
    flat = [st for rows in by_action.values() for st in rows]
    flat = flat[:6]
    mat, n_combats = pairwise_winrate_matrix(
        flat, model, seed=3, samples=1)
    assert mat.shape == (len(flat), len(flat))
    assert n_combats >= 1
    for i in range(len(flat)):
        assert mat[i, i] == 0.0
        for j in range(len(flat)):
            if i != j:
                assert abs(mat[i, j] + mat[j, i] - 1.0) < 1e-6


def test_turn_search_deterministic_and_budget() -> None:
    model = _model(8)
    cfg = TurnSearchConfig(states_budget=8, samples_per_action=1,
                           seed=5, combat_samples=1)
    r1 = TurnSearch(cfg).decide(model)
    r2 = TurnSearch(cfg).decide(model)
    assert r1.action is not None and r2.action is not None
    assert r1.action.signature() == r2.action.signature()
    assert r1.action_scores == r2.action_scores
    assert r1.n_states <= 8
    assert r1.n_combats <= max(0, r1.n_states * (r1.n_states - 1) // 2)
    assert r1.turn == model.turn
    assert r1.oracle_used is False


def test_decision_action_is_legal() -> None:
    model = _model(9)
    res = TurnSearch(TurnSearchConfig(states_budget=6, samples_per_action=1,
                                      seed=1)).decide(model)
    assert res.action is not None
    legal = {c.signature() for c in model.candidates()}
    assert res.action.signature() in legal


def test_no_value_net_or_hidden(monkeypatch) -> None:
    import hsbg.planning as planning
    import hsbg.search.evaluator as evmod

    def _boom(*args, **kwargs):
        raise AssertionError("turn-search 不应使用价值网/隐藏注入")

    monkeypatch.setattr(planning.hidden, "inject_hidden_state", _boom)
    monkeypatch.setattr(evmod.PolicyEvaluator, "evaluate", _boom)
    model = _model(10)
    res = TurnSearch(TurnSearchConfig(
        states_budget=6, samples_per_action=1, seed=2,
        completion_policy="heuristic"), evaluator=None).decide(model)
    assert res.action is not None
    assert res.oracle_used is False


def test_value_prune_final_choice_is_pairwise() -> None:
    """value 只剪枝；最终 argmax 必须来自 final pairwise 分。"""
    from hsbg.search import PolicyEvaluator

    model = _model(11)
    ev = PolicyEvaluator()
    cfg = TurnSearchConfig(
        states_budget=8, samples_per_action=1, seed=3,
        state_scorer="value_prune_pairwise", prune_top_k=2)
    res = TurnSearch(cfg, evaluator=ev).decide(model)
    assert res.action is not None
    assert res.final_choice_by_pairwise is True
    assert res.n_value_evals > 0
    assert len(res.finalist_actions) >= 2
    assert set(res.pairwise_action_scores) == set(res.action_scores)
    best_val = max(res.pairwise_action_scores.values())
    assert abs(res.action_scores[str(res.action.signature())] - best_val) < 1e-9
    assert res.action_scores == res.pairwise_action_scores
