"""``tests/test_search_env_readonly.py`` —— turn-search 对 env 的只读契约。

`hsbg/search` 的 `TurnSearch.decide(model)` 使用 ``EngineForwardModel``
（默认 ``clone=False`` 绑定 env 当前 game）；本测试确认：

1. `from_env(env, clone=False).game is env.game`（不额外 clone）；
2. 一次决定前后：`env.game` 的 digest、RNG 状态、候选动作、agent 状态都不变；
3. 决定后 env 仍可继续 step。

这是价值数据采集（`TurnSearchPolicy`）安全性的前提：采集循环在真实 env 上
反复调用 decide，不应偷跑/污染对局。
"""

from __future__ import annotations

from hsbg.agents.base import choose_option_index
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import BattlegroundsEnv
from hsbg.planning.digest import digest as state_digest
from hsbg.search.forward import EngineForwardModel
from hsbg.search.turn_search import TurnSearch, TurnSearchConfig


def _env_to_turn(seed: int = 0, turn: int = 3) -> BattlegroundsEnv:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    policy = HeuristicPolicy()
    while int(obs.turn) < turn:
        if obs.phase == "choice":
            action = obs.candidates[choose_option_index(policy, obs, env.game)]
        else:
            desc = policy.choose(env.game, env.agent_hero)
            if desc is None:
                action = obs.candidates[
                    next(i for i, c in enumerate(obs.candidates)
                         if c.kind == "end_turn")]
            else:
                action = desc.to_candidate()
        obs, _r, term, trunc, _i = env.step(action)
        if term or trunc:
            break
    while obs.phase == "choice":
        obs, _r, term, trunc, _i = env.step(0)
        if term or trunc:
            break
    return env


def test_turn_search_does_not_mutate_env():
    env = _env_to_turn(seed=0, turn=3)
    game = env.game
    hero = env.agent_hero
    before = state_digest(game)
    rng_before = game.rng._rng.getstate()
    health_before = int(hero.health)
    gold_before = int(hero.gold)
    board_before = tuple(m.card_id for m in hero.board)
    candidates_before = tuple(env.legal_actions())

    model = EngineForwardModel.from_env(env, clone=False)
    assert model.game is game, "clone=False 应绑定 env.game（不额外 clone）"
    assert model.hero is hero or model.hero.card_id == hero.card_id

    search = TurnSearch(TurnSearchConfig(
        states_budget=4, samples_per_action=1, combat_samples=1,
        completion_policy="heuristic", seed=7))
    result = search.decide(model)
    assert result.turn == int(game.turn)

    assert state_digest(game) == before, "TurnSearch.decide 修改了 env.game"
    assert game.rng._rng.getstate() == rng_before, "TurnSearch 消耗了引擎 RNG"
    assert int(hero.health) == health_before
    assert int(hero.gold) == gold_before
    assert tuple(m.card_id for m in hero.board) == board_before
    assert tuple(env.legal_actions()) == candidates_before

    # 决定后 env 仍可正常推进
    actions = env.legal_actions()
    assert actions
    end_idx = next(i for i, c in enumerate(actions) if c.kind == "end_turn")
    _obs, _r, term, trunc, _i = env.step(end_idx)
    assert isinstance(term, bool) and isinstance(trunc, bool)
    env.close()
