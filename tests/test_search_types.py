"""Phase 1 搜索：纯逻辑 + 真实引擎集成测试（不训练、不 live）。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.search.types import (
    MacroAction,
    SearchConfig,
    Node,
    placement_utility,
    prior_softmax,
)
from hsbg.env.spec import CandidateAction


def _cand(kind: str = "end_turn") -> CandidateAction:
    return CandidateAction(kind=kind)


# ── 基础函数 ──
def test_placement_utility_matches_reward_config() -> None:
    assert placement_utility(1, 8) == pytest.approx(1.0)
    assert placement_utility(8, 8) == pytest.approx(-1.0)
    assert placement_utility(4, 8) == pytest.approx(1.0 - 2.0 * 3 / 7)
    assert placement_utility(1, 2) == pytest.approx(1.0)
    assert placement_utility(2, 2) == pytest.approx(-1.0)


def test_prior_softmax_masked_and_stable() -> None:
    p = prior_softmax([1.0, 2.0, 3.0], temperature=1.0)
    assert p.sum() == pytest.approx(1.0)
    assert p[2] > p[1] > p[0]
    # 全 mask → 空
    assert prior_softmax([1.0, 2.0], mask=[False, False]).size == 0
    # 部分 mask
    q = prior_softmax([1.0, 2.0, 3.0], mask=[False, True, True])
    assert q[0] == 0.0
    assert q.sum() == pytest.approx(1.0)
    # 极端 logits 不 NaN
    r = prior_softmax([1e9, -1e9])
    assert np.isfinite(r).all() and r.sum() == pytest.approx(1.0)


def test_macro_action_requires_steps() -> None:
    with pytest.raises(ValueError):
        MacroAction(steps=())
    m = MacroAction(steps=(_cand("buy"), _cand("end_turn")))
    assert m.first.kind == "buy"
    assert m.last.kind == "end_turn"
    assert len(m.signatures) == 2


def test_search_config_phase1_guards() -> None:
    cfg = SearchConfig()
    assert cfg.simulations >= 1
    assert cfg.world_lines == 1
    assert cfg.oracle is False
    with pytest.raises(ValueError):
        SearchConfig(simulations=0)
    with pytest.raises(ValueError):
        SearchConfig(world_lines=4)
    with pytest.raises(ValueError):
        SearchConfig(oracle=True)
    with pytest.raises(ValueError):
        SearchConfig(macro_candidates=0)
    with pytest.raises(ValueError):
        SearchConfig(max_depth_turns=0)


def test_node_q_and_backup_formula() -> None:
    node = Node(depth=0, macros=[MacroAction(steps=(_cand(),))],
                priors=np.array([1.0]), children=[Node(depth=1)],
                N=0, value_sum=0.0)
    assert node.Q == 0.0
    node.N = 2
    node.value_sum = 1.0
    assert node.Q == pytest.approx(0.5)
    node.children[0].N = 3
    node.children[0].value_sum = -0.6
    assert node.children[0].Q == pytest.approx(-0.2)
