"""可重放状态 + 策略决策一致性（需要 hsbg_engine + torch）。

不做隐藏字段 oracle：只验证 state_json 恢复后公开观测/合法动作/策略决策一致。
隐藏隔离由 test_az_search 的 toy info isolation 覆盖。
"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.common import mask_from_bytes
from hsbg.az.train.model import build_net
from hsbg.az.train.ppo import PPOEvaluator, PPOGreedyPolicy


def _advance_to_learner(game):
    for _ in range(20000):
        if game.is_over():
            return False
        acted = False
        for p in range(game.num_players):
            if not game.needs_action(p):
                continue
            if int(p) == 0:
                return True
            game.bot_play(int(p))
            acted = True
        if not acted:
            return False
    return False


def test_state_json_policy_decision_replay():
    pytest.importorskip("torch")
    pytest.importorskip("hsbg_engine")
    import hsbg_engine as E

    game = E.Game(seed=4242)
    assert _advance_to_learner(game)
    payload = game.state_json()
    f_before, c_before = game.observe(0)
    m_before = mask_from_bytes(game.legal_mask(0))
    restored = E.Game.from_json(payload)
    assert restored.state_json() == payload
    f_after, c_after = restored.observe(0)
    m_after = mask_from_bytes(restored.legal_mask(0))
    assert f_before == f_after and c_before == c_after
    assert np.array_equal(m_before, m_after)

    model = build_net(16)
    model.eval()
    ev = PPOEvaluator(model, device="cpu")
    p1 = PPOGreedyPolicy(ev)
    p2 = PPOGreedyPolicy(ev)
    d1 = p1.decide(game, 0)
    d2 = p2.decide(restored, 0)
    assert int(d1.action) == int(d2.action)
    assert bool(m_before[int(d1.action)])
