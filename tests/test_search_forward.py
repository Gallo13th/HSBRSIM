"""EngineForwardModel：clone 隔离 / 候选合法 / end_turn 宏推进（真实引擎，不 live）。"""

from __future__ import annotations

import pytest

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search.forward import EngineForwardModel
from hsbg.search.types import MacroAction


def _model(seed: int = 5) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    env.reset(seed=seed)
    # 走两步非 end_turn，保证有金币/候选（避免开局空）
    obs = env.reset(seed=seed)
    for _ in range(2):
        if not obs.candidates:
            break
        # 选 buy 优先，否则第一个非 end_turn
        pick = next((i for i, c in enumerate(obs.candidates)
                     if c.kind == "buy"), 0)
        if obs.candidates[pick].kind == "end_turn":
            pick = 0
        obs, *_ = env.step(pick)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def test_clone_isolated_from_original() -> None:
    model = _model()
    before = model.state_summary()
    dup = model.clone()
    # 在 dup 上应用一个候选；原 model 不应变化
    cands = dup.candidates()
    if cands:
        # 优先非 end_turn；找不到就 end_turn 也可（会推进宏回合）
        pick = next((c for c in cands if c.kind != "end_turn"), cands[0])
        assert dup.apply(pick) is True
    after = model.state_summary()
    assert after == before
    assert dup.game is not model.game


def test_candidates_are_legal_and_nonempty() -> None:
    model = _model()
    cands = model.candidates()
    assert cands, "招募期应有候选"
    from hsbg import planning
    legal_sigs = {d.to_candidate().signature()
                  for d in planning.legal_actions(model.game, model.hero)}
    for c in cands:
        assert c.signature() in legal_sigs


def test_macro_end_turn_advances_clone_only() -> None:
    model = _model()
    cands = model.candidates()
    ends = [c for c in cands if c.kind == "end_turn"]
    if not ends:
        pytest.skip("当前状态没有 end_turn 候选")
    turn0 = model.turn
    dup = model.clone()
    macro = MacroAction(steps=(ends[0],), source="test")
    assert dup.apply_macro(macro) is True
    assert dup.turn == turn0 + 1
    assert model.turn == turn0


def test_two_clones_same_seed_same_path() -> None:
    model = _model()
    a = model.clone()
    b = model.clone()
    # 依次选择相同的第一个候选（至少一个合法动作）
    for _ in range(2):
        ca = a.candidates()
        cb = b.candidates()
        if not ca or not cb:
            break
        assert [c.signature() for c in ca] == [c.signature() for c in cb]
        assert a.apply(ca[0]) is True
        assert b.apply(cb[0]) is True
    assert a.state_summary()["turn"] == b.state_summary()["turn"]
    assert a.rank() == b.rank()


def test_terminal_utility_range() -> None:
    model = _model()
    u = model.terminal_utility()
    assert -1.0 <= u <= 1.0
