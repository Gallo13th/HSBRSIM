"""determinization v0：WarbandBank 摘要采样 + 不注入隐藏状态（诚实缺口）。"""

from __future__ import annotations

import json

import pytest

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel
from hsbg.search.determinize import WarbandBank, determinize


def _model(seed: int = 11) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed)
    env.reset(seed=seed)
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def _write_bank(tmp_path):
    path = tmp_path / "steps.jsonl"
    rows = [
        {"type": "step", "obs": {"turn": 3, "tier": 2, "opponent_size": 2}},
        {"type": "step", "obs": {"turn": 4, "tier": 2, "opponent_size": 3}},
        {"type": "step", "obs": {"turn": 5, "tier": 3, "opponent_size": 4}},
        {"type": "header", "episodes": 1},
        {"type": "step", "obs": {"turn": 5, "tier": 3}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def test_warband_bank_basic(tmp_path) -> None:
    bank = WarbandBank.from_jsonl([_write_bank(tmp_path)])
    assert bank.n_records == 3
    st = bank.stats()
    assert st["n_records"] == 3 and st["n_buckets"] >= 1
    rng = __import__("random").Random(0)
    s = bank.sample(turn=4, tier=2, rng=rng)
    assert s is not None
    assert 1 <= s.size <= 4
    assert 1 <= s.tier <= 6


def test_determinize_v0_does_not_inject_hidden_state(tmp_path) -> None:
    model = _model()
    bank = WarbandBank.from_jsonl([_write_bank(tmp_path)])
    dup, info = determinize(model, bank, seed=1, oracle=False)
    assert info.oracle is False
    assert info.injected_hidden is False
    assert info.mode == "summary_only_uninjected"
    assert info.n_samples >= 1
    # 副本独立
    assert dup.game is not model.game
    # 原模型未被改动
    assert dup.turn == model.turn


def test_determinize_oracle_flag_is_training_only() -> None:
    model = _model()
    dup, info = determinize(model, None, seed=1, oracle=True)
    assert info.oracle is True
    assert info.injected_hidden is True
    assert dup.game is not model.game


def test_determinize_without_bank_mode_none() -> None:
    model = _model()
    dup, info = determinize(model, None, seed=0, oracle=False)
    assert info.mode == "none"
    assert info.injected_hidden is False
