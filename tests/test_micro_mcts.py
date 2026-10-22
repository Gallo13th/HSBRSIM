"""动作级 micro-PUCT：PUCT 选择/备份、宽度剪枝、确定性、budget、无 oracle。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel, PolicyEvaluator
from hsbg.search.micro_mcts import MicroConfig, MicroMCTS, MicroNode


def _model(seed: int = 5) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    for _ in range(3):
        pick = next((i for i, c in enumerate(obs.candidates) if c.kind == "buy"), 0)
        obs, *_ = env.step(pick)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def test_puct_select_formula() -> None:
    cfg = MicroConfig(simulations=1, width=2, c_puct=1.5)
    mcts = MicroMCTS(cfg, evaluator=None)  # _select 不依赖 evaluator
    node = MicroNode(depth=0, actions=[], priors=np.array([0.5, 0.5]),
                     children={}, N=2)
    from hsbg.env.spec import CandidateAction

    node.actions = [CandidateAction(kind="buy"), CandidateAction(kind="sell")]
    node.priors = np.array([0.5, 0.5])
    c0 = MicroNode(depth=1)
    c0.N, c0.value_sum = 2, 0.2
    node.children = {0: c0, 1: MicroNode(depth=1)}
    # score0=0.1+1.5*0.5*sqrt2/3≈0.454; score1=0+1.5*0.5*sqrt2/1≈1.061
    assert mcts._select(node) == 1


def test_width_pruning_and_budget() -> None:
    model = _model(6)
    cfg = MicroConfig(simulations=2, width=2, max_depth_actions=2,
                      leaf_horizon_turns=1, seed=1)
    mcts = MicroMCTS(cfg, evaluator=PolicyEvaluator())
    node = MicroNode(depth=0)
    mcts._expand(node, model)
    assert len(node.actions) <= 2
    assert len(node.all_actions) >= len(node.actions)
    res = mcts.decide(model)
    assert res.action is not None
    assert res.n_simulations == 2
    assert res.oracle_used is False
    legal = {c.signature() for c in model.candidates()}
    assert res.action.signature() in legal


def test_deterministic_same_seed() -> None:
    model = _model(7)
    cfg = MicroConfig(simulations=2, width=2, max_depth_actions=2,
                      leaf_horizon_turns=1, seed=3)
    ev = PolicyEvaluator()
    r1 = MicroMCTS(cfg, evaluator=ev).decide(model)
    r2 = MicroMCTS(cfg, evaluator=ev).decide(model)
    assert r1.action is not None and r2.action is not None
    assert r1.action.signature() == r2.action.signature()
    assert np.array_equal(r1.root_visits, r2.root_visits)


def test_no_hidden_state_injection(monkeypatch) -> None:
    import hsbg.planning as planning

    def _boom(*args, **kwargs):
        raise AssertionError("micro-PUCT 不应注入隐藏状态")

    monkeypatch.setattr(planning.hidden, "inject_hidden_state", _boom)
    model = _model(8)
    res = MicroMCTS(MicroConfig(simulations=1, width=2,
                                leaf_horizon_turns=1, seed=1),
                    evaluator=PolicyEvaluator()).decide(model)
    assert res.action is not None
    assert res.oracle_used is False
