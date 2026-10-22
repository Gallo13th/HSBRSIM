"""PUCT 选择/备份公式 + 真实引擎 search 冒烟（不训练、不 live）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hsbg.env.spec import CandidateAction
from hsbg.search import EngineForwardModel, PolicyEvaluator, SearchConfig, run_search
from hsbg.search.mcts import MCTS
from hsbg.search.types import MacroAction, Node

CHECKPOINT = Path("runs/bc/official_320/policy_bc.pt")


# ── 纯逻辑：PUCT 公式 / 备份 ──
def test_puct_select_formula() -> None:
    cfg = SearchConfig(simulations=1, macro_candidates=2)
    mcts = MCTS(model=None, evaluator=None, config=cfg)  # _select 不依赖 model
    m0 = MacroAction(steps=(CandidateAction(kind="buy", src_zone="tavern",
                                            src_slot=0),))
    m1 = MacroAction(steps=(CandidateAction(kind="buy", src_zone="tavern",
                                            src_slot=1),))
    node = Node(depth=0, macros=[m0, m1], priors=np.array([0.5, 0.5]),
                children=[Node(depth=1), Node(depth=1)], N=2)
    node.children[0].N = 2
    node.children[0].value_sum = 0.2
    node.children[1].N = 0
    # score0 = 0.1 + 2.0*0.5*sqrt(2)/(1+2) ≈ 0.571
    # score1 = 0.0 + 2.0*0.5*sqrt(2)/(1+0) ≈ 1.414
    assert mcts._select(node) == 1


def _make_fake(monkeypatch):
    class FakeModel:
        def __init__(self, state: int = 0):
            self.state = state

        def clone(self):
            return FakeModel(self.state)

        def is_terminal(self):
            return False

        def terminal_utility(self):
            return 0.0

        def apply_macro(self, macro):
            self.state = int(macro.steps[0].option) + 1
            return True

        def apply_macro_before_end(self, macro):
            self.state = int(macro.steps[0].option) + 1
            return True

        def combat_leaf(self):
            return None, None

    class Ev:
        def value(self, model):
            return 0.2 if model.state == 1 else 0.8

        def macro_priors(self, macros):
            return np.full(len(macros), 1.0 / len(macros))

        def evaluate(self, model):
            outer = self

            class _E:
                value = outer.value(model)
                expected_rank = 0.0
                prior = np.zeros(0)
                candidates = ()
                rank_probs = np.zeros(8)
                obs = None

                def macro_priors(self, macros):
                    return outer.macro_priors(macros)

            return _E()

    macros = [
        MacroAction(steps=(CandidateAction(kind="buy", option=0),), source="fake"),
        MacroAction(steps=(CandidateAction(kind="buy", option=1),), source="fake"),
    ]

    def fake_generate(state, evaluator, config, stats=None):
        return list(macros)

    monkeypatch.setattr("hsbg.search.mcts.generate_macros", fake_generate)
    return FakeModel(), Ev(), macros


def test_backup_and_visits(monkeypatch) -> None:
    model, ev, macros = _make_fake(monkeypatch)
    cfg = SearchConfig(simulations=8, macro_candidates=2, max_depth_turns=1)
    res = MCTS(model, ev, cfg).search()
    assert res.best_macro is not None
    assert res.visits.sum() == cfg.simulations
    assert res.pi.sum() == pytest.approx(1.0)
    # 叶 value：macro1(0.8) > macro0(0.2)，PUCT 应更常选 1
    assert res.visits[1] > res.visits[0]
    assert res.best_index == 1
    assert res.root_values[0] == pytest.approx(0.2)
    assert res.root_values[1] == pytest.approx(0.8)


# ── 真实引擎：合法性 / 确定性 / 无 oracle ──
pytestmark = pytest.mark.skipif(
    not CHECKPOINT.exists(), reason="缺少 BC checkpoint")


def _real_model():
    from hsbg.env.game_env import BattlegroundsEnv

    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=7)
    obs = env.reset(seed=7)
    for _ in range(3):
        pick = next((i for i, c in enumerate(obs.candidates) if c.kind == "buy"), 0)
        obs, *_ = env.step(pick)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def _verify_macro(model: EngineForwardModel, macro: MacroAction) -> bool:
    dup = model.clone()
    for cand in macro.steps:
        if dup.is_terminal():
            return True
        if cand.signature() not in {c.signature() for c in dup.candidates()}:
            return False
        if not dup.apply(cand):
            return False
    return True


def test_search_real_state_legal_deterministic_no_oracle() -> None:
    model = _real_model()
    ev = PolicyEvaluator(str(CHECKPOINT), device="cpu")
    cfg = SearchConfig(simulations=4, macro_candidates=2, max_depth_turns=1,
                       seed=3)
    res = run_search(model, ev, cfg)
    assert res.best_macro is not None
    assert res.pi.sum() == pytest.approx(1.0)
    assert np.all(res.pi >= 0)
    assert _verify_macro(model, res.best_macro)
    assert res.oracle_used is False
    assert res.hidden_info_mode in ("none", "summary_only_uninjected")
    # 同 seed 复现
    res2 = run_search(model, ev, cfg)
    assert np.array_equal(res.pi, res2.pi)
    assert np.array_equal(res.visits, res2.visits)
    assert res.best_macro.signatures == res2.best_macro.signatures
