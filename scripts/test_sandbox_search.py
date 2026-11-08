"""沙盒搜索（`hsbg/az/train/sandbox_search.py`）的状态转移与 PUCT 契约测试。

三件事必须成立，否则标签会静默失真：
1. `EconomySandbox.clone()` + `search_step()` 与 `step()` **状态机一致**（逐位 state_json）；
2. PUCT 只落**合法且非 Move**的动作，π 在候选上归一化，确定性可复现；
3. `should_search` 只在关键决策（策略 top-1 是 buy/play/choose/...）上触发，且受每回合预算限制。
"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.economy_sandbox import EconomySandbox, SandboxConfig
from hsbg.az.train.sandbox_search import (MOVE_LO, MOVE_HI, SandboxTree,
                                          SearchConfig, action_kind, should_search)

pytest.importorskip("hsbg_engine")


def _legal_actions(env):
    return np.flatnonzero(env.obs().mask)


def _pick(rng, legal):
    """确定性「随机」策略：优先买/施法/选择，避免全 Move。"""
    key = [int(a) for a in legal if a < MOVE_LO]
    pool = key if key and rng.random() < 0.8 else [int(a) for a in legal]
    return int(pool[int(rng.integers(len(pool)))])


def test_clone_search_step_matches_env_step():
    """search_step 与 step 的引擎状态逐位一致（含新回合金币/回血/对手 EndTurn）。"""
    cfg = SandboxConfig(gold_per_turn=10)
    a = EconomySandbox(cfg)
    a.reset(seed=1234)
    b = a.clone()
    rng = np.random.default_rng(7)
    for step in range(900):
        legal = _legal_actions(a)
        assert legal.size > 0
        act = _pick(rng, legal)
        a.step(act)
        b.search_step(act)
        assert a.g.state_json() == b.g.state_json(), f"state 分叉 @ step {step} act {act}"
        assert int(a.g.turn) == int(b.g.turn)
        assert bool(a.g.is_over()) == bool(b.g.is_over())
        if a.g.is_over():
            break
    assert a.g.is_over(), "900 步内应打到终局（15 回合）"


def test_search_legal_sparse_deterministic():
    """PUCT：π 只落在合法非 Move 候选上、和=1、同输入逐位可复现。"""
    env = EconomySandbox(SandboxConfig(gold_per_turn=10))
    env.reset(seed=910000)
    # 往前走到一个「金币够买」的决策点（否则可能没有可搜候选）
    obs = env.obs()
    legal = np.flatnonzero(obs.mask)
    if not (legal < MOVE_LO).any():
        pytest.skip("该 seed 的首个决策点没有非 Move 合法动作")

    cfg = SearchConfig(sims=32, topk=8, depth_turns=1, max_searches_per_turn=0)
    prior = np.where(obs.mask, 1.0, 0.0).astype(np.float32)
    prior[legal] = np.linspace(1.0, 0.2, legal.size).astype(np.float32)

    def run():
        tree = SandboxTree(env, obs.features, obs.cards, obs.mask, prior, 0.4, cfg)
        for _ in range(int(cfg.sims)):
            leaf = tree.simulate()
            if leaf is not None:
                tree.finish(np.where(leaf.mask, 1.0, 0.0).astype(np.float32)
                            / max(1.0, float(leaf.mask.sum())), 0.4)
        return tree.result(sims=int(cfg.sims))

    r1, r2 = run(), run()
    assert np.array_equal(r1.pi, r2.pi), "同输入必须逐位可复现"
    assert 0.0 < float(r1.pi.sum()) <= 1.0 + 1e-6
    support = np.flatnonzero(r1.pi > 0)
    assert support.size > 0
    assert bool(np.all(obs.mask[support])), "π 只能落在合法动作上"
    assert bool(np.all((support < MOVE_LO) | (support >= MOVE_HI))), "默认剔除 Move"
    assert support.size <= int(cfg.topk), "π 的支撑应 <= top-k"
    assert r1.sims == int(cfg.sims)


def test_should_search_only_key_decisions():
    """关键决策判定：top-1 是 Move / EndTurn 不搜；buy/play 搜；每回合预算生效。"""
    cfg = SearchConfig(max_searches_per_turn=2, skip_move=True)
    mask = np.zeros(245, dtype=bool)
    mask[[0, 8, 9, 46, 47, 196, 197]] = True
    from hsbg.az.train.economy_sandbox import SandboxObs
    obs = SandboxObs(features=np.zeros(3227, np.float32),
                     cards=np.zeros(124, np.int32), mask=mask, turn=3)
    buy = np.zeros(245, np.float32); buy[8] = 0.8; buy[0] = 0.2
    move = np.zeros(245, np.float32); move[196] = 0.9
    assert should_search(obs, cfg, searched_this_turn=0, prior=buy)
    assert not should_search(obs, cfg, searched_this_turn=0, prior=move)
    assert not should_search(obs, cfg, searched_this_turn=2, prior=buy)
    # 没有先验时按「mask 里是否有关键段」判定
    assert should_search(obs, cfg, searched_this_turn=0, prior=None)


def test_action_kind_segments():
    assert action_kind(0) == "end"
    assert action_kind(3) == "upgrade"
    assert action_kind(8) == "buy"
    assert action_kind(30) == "choose"
    assert action_kind(46) == "play"
    assert action_kind(196) == "move"
