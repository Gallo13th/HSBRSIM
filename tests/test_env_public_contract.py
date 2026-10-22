"""``tests/test_env_public_contract.py`` —— 外部采集器依赖的 env 公开接口契约。

data-upgrade 的 `TurnSearchPolicy` / `scripts/collect_turn_search_selfplay.py`
依赖以下**稳定公开面**（不要无故改名/改签名）：

- ``BattlegroundsEnv(num_players=..., opponent=..., seed=...)``；
- ``env.reset(seed=...) -> Observation``；
- ``env.step(candidate) -> (obs, reward, terminated, truncated, info)``；
- ``env.agent_hero -> Hero``（公开 property；不要用私有 ``_agent``）；
- ``env.game -> Game``、``env.legal_actions()``、``env.num_players``；
- ``hsbg.rl.api.run_episode(env, policy, seed=..., collect_transitions=True)``。

外部采集脚本每 worker 内 ``make_env``（env 不 pickle）；本测试同时验证
``run_episode`` 能直接驱动 ``BattlegroundsEnv`` 并产出带完整 Observation 的
Transition（value 训练数据来源）。
"""

from __future__ import annotations

from hsrl2.hero import Hero

from hsbg.env import BattlegroundsEnv
from hsbg.env.spec import Observation


def test_env_public_surface_for_external_collectors():
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=3)
    obs = env.reset(seed=3)
    assert isinstance(obs, Observation)
    assert env.game is not None
    assert env.num_players == 8
    hero = env.agent_hero
    assert isinstance(hero, Hero), "env.agent_hero 必须是公开 property 且 reset 后非空"
    # 与 game.heroes[agent_index] 同一实体（外部 policy 据此定位）
    assert hero is env.game.heroes[env.config.agent_index]

    actions = env.legal_actions()
    assert isinstance(actions, tuple) and actions
    obs2, reward, terminated, truncated, info = env.step(actions[0])
    assert isinstance(obs2, Observation)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool) and isinstance(truncated, bool)
    assert isinstance(info, dict)
    assert env.agent_hero is hero or obs2.hero is not None
    # 支持候选下标 / CandidateAction 两种常用调用
    if obs2.candidates:
        env.step(obs2.candidates[0])
    env.close()


def test_run_episode_contract_with_battlegrounds_env():
    """`hsbg.rl.api.run_episode` + `BattlegroundsEnv`：完整 obs Transition 可采。"""
    from hsbg.rl.api import run_episode
    from hsbg.rl.policies import HeuristicPolicy as RLHeuristicPolicy

    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=4)
    try:
        record = run_episode(env, RLHeuristicPolicy(), seed=4,
                             episode_id=0, max_steps=100,
                             collect_transitions=True)
        assert record.episode_id == 0
        assert record.seed == 4
        assert 1 <= int(record.rank) <= 8
        assert len(record.transitions) > 0
        for tr in record.transitions[:10]:
            assert isinstance(tr.obs, Observation), "Transition.obs 必须是完整 Observation"
            assert tr.episode_id == 0 and tr.seed == 4
            assert isinstance(tr.action, int)
            assert tr.action_kind
        summary = record.summary_dict()
        assert int(summary["rank"]) == int(record.rank)
        assert "placement" not in summary  # 现行 schema 用 rank（值 1..8）

        # 同 seed 可复现：Transition 的 (action, obs_digest) 序列一致
        from hsbg.rl.api import obs_digest
        record2 = run_episode(env, RLHeuristicPolicy(), seed=4,
                              episode_id=0, max_steps=100,
                              collect_transitions=True)
        sig1 = [(int(t.action), obs_digest(t.obs)) for t in record.transitions]
        sig2 = [(int(t.action), obs_digest(t.obs)) for t in record2.transitions]
        assert sig1 == sig2, "同 seed+同 policy 采集轨迹应完全一致"
        assert int(record2.rank) == int(record.rank)
    finally:
        env.close()
