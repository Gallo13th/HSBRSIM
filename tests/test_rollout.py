"""``tests/test_rollout.py`` —— hard-search rollout 接口（rollout_to_end）测试。

覆盖 `hsbg/planning/rollout_throughput.py`：

- horizon（到终局 / 1 / 3 回合）终止语义；
- 在 clone 上执行（原局面 digest 不变）；
- 同策略 seed 可复现（随机策略）/ 启发式确定性；
- `fast_opponents` 仅改变对手买牌假设，仍能正常推进到终局；
- `benchmark_rollout` 输出结构。
"""

from __future__ import annotations

import pytest

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.agents.base import choose_option_index
from hsbg.env import BattlegroundsEnv
from hsbg.planning.digest import digest as state_digest
from hsbg.planning.rollout_throughput import (
    HeuristicEnginePolicy,
    RandomEnginePolicy,
    benchmark_rollout,
    rollout_batch,
    rollout_to_end,
)


def _snapshot(seed: int = 0, turns: int = 2) -> tuple:
    """启发式推进到第 turns 回合的 8 人快照，返回 (env, game)。"""
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    policy = HeuristicPolicy()
    while int(obs.turn) < turns:
        if obs.phase == "choice":
            action = obs.candidates[choose_option_index(policy, obs, env.game)]
        else:
            desc = policy.choose(env.game, env.agent_hero)
            if desc is None:
                idx = next(i for i, c in enumerate(obs.candidates)
                           if c.kind == "end_turn")
                action = obs.candidates[idx]
            else:
                action = desc.to_candidate()
        obs, _r, term, trunc, _i = env.step(action)
        if term or trunc:
            break
    return env, env.game


@pytest.mark.parametrize("horizon", [1, 2, 3])
def test_rollout_horizon(horizon: int):
    env, game = _snapshot(seed=0, turns=2)
    before = state_digest(game)
    result, final = rollout_to_end(game, HeuristicEnginePolicy(),
                                   max_turns=horizon)
    assert result.truncated is True
    assert result.terminated is False
    assert result.turns == horizon
    assert result.steps > 0
    assert state_digest(game) == before, "rollout 修改了原 game"
    assert final is not None and final is not game
    env.close()


def test_rollout_to_end_terminates():
    env, game = _snapshot(seed=1, turns=2)
    result, final = rollout_to_end(game, HeuristicEnginePolicy())
    assert result.terminated is True
    # 目标英雄被淘汰（游戏可能仍有其他玩家存活 → finished 不一定 True）
    assert (result.alive is False) or result.finished is True
    assert result.turns > 3
    assert 1 <= result.rank <= 8
    assert isinstance(result.value, float)
    assert final is not None
    env.close()


def test_rollout_deterministic_random_policy():
    env, game = _snapshot(seed=2, turns=2)
    r1, _ = rollout_to_end(game, RandomEnginePolicy(seed=17,
                                                    end_turn_prob=0.3),
                           max_turns=2)
    r2, _ = rollout_to_end(game, RandomEnginePolicy(seed=17,
                                                    end_turn_prob=0.3),
                           max_turns=2)
    assert r1.as_dict() == r2.as_dict()
    env.close()


def test_rollout_fast_opponents():
    env, game = _snapshot(seed=3, turns=2)
    before = state_digest(game)
    result, _ = rollout_to_end(game, HeuristicEnginePolicy(),
                               fast_opponents=True)
    assert result.terminated is True
    assert state_digest(game) == before
    env.close()


def test_rollout_batch_and_benchmark():
    env, game = _snapshot(seed=4, turns=2)
    results = rollout_batch(game, HeuristicEnginePolicy(), n=2, max_turns=1)
    assert len(results) == 2
    assert all(r.turns == 1 for r in results)
    stats = benchmark_rollout(game, policy=HeuristicEnginePolicy(),
                              max_turns=1, repeats=2)
    for key in ("p50_ms", "p90_ms", "p99_ms", "rollouts_per_sec",
                "terminated_rate", "champion_rate", "rank_counts"):
        assert key in stats, key
    assert stats["p50_ms"] > 0
    assert 0.0 <= stats["terminated_rate"] <= 1.0
    env.close()
