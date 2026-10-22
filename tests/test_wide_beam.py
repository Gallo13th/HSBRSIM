"""宽候选生成 / 大 beam 决策冒烟（不训练、不用评分网）。"""

from __future__ import annotations

from pathlib import Path

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel
from hsbg.search.hard_search import HardSearch, HardSearchConfig
from hsbg.search.wide_beam import generate_wide_candidates

CHECKPOINT = Path("runs/bc/official_320/policy_bc.pt")


def _model(seed: int = 9) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    for _ in range(3):
        pick = next((i for i, c in enumerate(obs.candidates) if c.kind == "buy"), 0)
        obs, *_ = env.step(pick)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def test_wide_candidates_dedupe_count_and_legality() -> None:
    model = _model(9)
    cands = generate_wide_candidates(model, None, target=8, seed=1,
                                     max_first=8)
    assert 4 <= len(cands) <= 8
    sigs = [m.signatures for m in cands]
    assert len(sigs) == len(set(sigs))
    sources = {m.source for m in cands}
    assert "first_step" in sources
    # 每条 macro 的每一步都是合法候选（在 clone 上逐条验证）
    for m in cands:
        dup = model.clone()
        for c in m.steps:
            if dup.is_terminal():
                break
            legal = {x.signature() for x in dup.candidates()}
            assert c.signature() in legal
            assert dup.apply(c, advance_end_turn=False)


def test_hard_search_accepts_provided_candidates_and_beam_width() -> None:
    model = _model(10)
    cands = generate_wide_candidates(model, None, target=8, seed=2,
                                     max_first=6)
    cfg = HardSearchConfig(candidates=len(cands), rollout_budget=1,
                           rollout_backend="env", rollout_policy="heuristic",
                           screen_horizon_turns=3, screen_rollouts=1,
                           beam_width=4, finalists=2, final_rollouts=1,
                           seed=3, prune=False)
    res = HardSearch(cfg, candidate_macros=cands).decide(model)
    assert res.best is not None
    assert res.total_rollouts >= 1
    assert len(res.stats) == len(cands)
    assert res.oracle_used is False
