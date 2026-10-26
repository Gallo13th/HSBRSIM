"""hsbg/az 不完全信息搜索原型测试（task-2）。

分两层：
1. **本地 toy 层**（无需 hsbg_engine）：信息隔离、确定性 seed、合法动作、根分布、
   PUCT/温度/Dirichlet 数学性质、安全回退、源局面不被修改、无隐藏信息调用；
2. **引擎层**（`pytest.importorskip("hsbg_engine")`）：真实 Game 上的 determinization
   公开信息保持、搜索冒烟、确定性、禁用 view/state_json 的信息隔离审计。

运行::

    python -m pytest tests/test_az_search.py -q
"""

from __future__ import annotations

import json
import os
import random

import numpy as np
import pytest

from hsbg.az import (CloneSampler, DeterminizeInfo, HeuristicEvaluator, Node,
                     SearchConfig, UniformEvaluator, heuristic_prior,
                     heuristic_value, placement_utility, search, visit_distribution)
from hsbg.az import belief as B
from hsbg.az import env_api as EA
from hsbg.az import puct as P
from hsbg.az.policy import RolloutEvaluator
from hsbg.az.toy_env import ToyGame

hsbg_engine = None
try:  # 引擎是可选依赖：本地 toy 测试在没有 Rust 构建的机器上也要能跑
    import hsbg_engine  # type: ignore[no-redef]
except Exception:  # noqa: BLE001 - 未构建/未安装
    hsbg_engine = None

_HAS_ENGINE = hsbg_engine is not None


def toy_in_play(turns: int = 4, seed: int = 5) -> ToyGame:
    g = ToyGame(seed=seed)
    for _ in range(200):
        if g.is_over() or g.turn >= turns:
            break
        for p in range(g.num_players()):
            if g.needs_action(p):
                g.bot_play(p)
    return g


# ══════════════════════════════════════════════════════════════════════
# 1. 本地 toy 层
# ══════════════════════════════════════════════════════════════════════


def test_toy_search_pi_and_action_legal():
    g = toy_in_play()
    res = search(g, 0, config=SearchConfig(simulations=8, determinizations=2,
                                           temperature=1.0, seed=3))
    mask = EA.legal_mask(g, 0)
    assert res.pi.shape == (EA.num_actions(g),)
    assert res.pi.dtype == np.float32
    assert res.action in np.flatnonzero(mask)
    assert abs(float(res.pi.sum()) - 1.0) < 1e-5
    # 根分布集中在合法动作上
    assert float(res.pi[~mask].sum()) == 0.0
    assert res.visits > 0
    assert res.determinizations == 2
    assert res.n_simulations == 8
    assert res.n_states >= 2
    assert res.elapsed_s >= 0.0
    assert res.info["engine_backend"] == "python"
    assert res.info["n_worlds"] == 2
    # 世界采样不变量：公开观测在 determinization 前后一致
    assert all(v is True for v in res.info["world_obs_invariant"])
    assert res.info["oracle"] is False


def test_toy_search_deterministic_same_seed_and_differs_across_seed():
    g = toy_in_play()
    cfg = SearchConfig(simulations=6, determinizations=2, temperature=1.0, seed=17)
    r1 = search(g, 0, config=cfg)
    r2 = search(g, 0, config=cfg)
    assert r1.action == r2.action
    assert np.array_equal(r1.pi, r2.pi)
    assert [w["visits"] for w in r1.per_world] == [w["visits"] for w in r2.per_world]
    # 不同搜索 seed 允许不同（不强制），但必须仍合法
    r3 = search(g, 0, config=SearchConfig(simulations=6, determinizations=2,
                                          temperature=1.0, seed=18))
    assert bool(EA.legal_mask(g, 0)[r3.action])


def test_toy_info_isolation_hidden_state_does_not_change_decision():
    """对手隐藏量不同、公开观测相同 → 搜索决策/π 必须完全相同（禁止用隐藏信息）。"""
    g1 = toy_in_play(turns=6, seed=9)
    g2 = g1.copy()
    for q in range(1, g1.num_players()):
        g2.players[q]["strength"] = 400 + q
        g2.players[q]["gold"] = 0
        g2.players[q]["hand"] = [7, 7, 7]
        g2.players[q]["shop"] = [9, 9, 9]
    f1, c1 = g1.observe(0)
    f2, c2 = g2.observe(0)
    assert np.array_equal(f1, f2) and np.array_equal(c1, c2), "构造的隐藏量不应进入公开观测"
    cfg = SearchConfig(simulations=8, determinizations=3, temperature=0.0, seed=23)
    r1 = search(g1, 0, config=cfg)
    r2 = search(g2, 0, config=cfg)
    assert r1.action == r2.action
    assert np.array_equal(r1.pi, r2.pi)
    assert r1.info["oracle"] is False


def test_toy_search_does_not_mutate_source_state():
    g = toy_in_play()
    before = g.snapshot()
    search(g, 0, config=SearchConfig(simulations=6, determinizations=2, seed=1))
    assert g.snapshot() == before


def test_toy_eval_exception_falls_back_safely():
    g = toy_in_play()

    def boom(obs, seat, game=None):
        raise RuntimeError("eval down")

    res = search(g, 0, config=SearchConfig(simulations=4, determinizations=2, seed=2),
                 eval_fn=boom)
    assert res.fallback is True
    assert bool(EA.legal_mask(g, 0)[res.action])
    assert abs(float(res.pi.sum()) - 1.0) < 1e-5
    assert "eval down" in res.info["fallback_reason"] or res.info["fallback_reason"]


def test_toy_terminal_root_returns_empty_pi():
    g = toy_in_play(turns=4, seed=3)
    g.over = True
    g.players[0]["alive"] = False
    g.players[0]["placement"] = 8
    res = search(g, 0, config=SearchConfig(simulations=4, determinizations=2, seed=0))
    assert res.fallback is True
    assert float(res.pi.sum()) == 0.0


def test_toy_temperature_zero_is_argmax():
    g = toy_in_play()
    res = search(g, 0, config=SearchConfig(simulations=8, determinizations=2,
                                           temperature=0.0, seed=4))
    assert int(np.argmax(res.pi)) == res.action
    assert float(res.pi.sum()) == pytest.approx(1.0)


def test_dirichlet_noise_only_on_legal_and_normalized():
    g = toy_in_play()
    res = search(g, 0, config=SearchConfig(
        simulations=8, determinizations=2, temperature=0.0, seed=5,
        dirichlet_alpha=0.3, dirichlet_epsilon=0.25))
    mask = EA.legal_mask(g, 0)
    assert float(res.pi[~mask].sum()) == 0.0
    assert float(res.pi.sum()) == pytest.approx(1.0)
    assert res.info["dirichlet"]["epsilon"] == 0.25


def test_root_value_in_utility_range():
    g = toy_in_play()
    res = search(g, 0, config=SearchConfig(simulations=6, determinizations=2, seed=6))
    assert -1.0 <= res.root_value <= 1.0


def test_determinize_world_preserves_public_observation():
    g = toy_in_play()
    rng = random.Random(7)
    world, info = g.determinize_world(0, rng)
    f0, c0 = g.observe(0)
    f1, c1 = world.observe(0)
    assert np.array_equal(f0, f1) and np.array_equal(c0, c1)
    assert info.injected_hidden is True
    assert info.obs_invariant is True
    assert info.n_opponents == g.num_players() - 1


def test_chance_resample_on_end_turn_runs():
    g = toy_in_play()
    # 只搜 1 步；强制 evaluate 正常，EndTurn 重采样应被触发并保持不变量
    res = search(g, 0, config=SearchConfig(
        simulations=6, determinizations=1, temperature=1.0, seed=8,
        resample_on_end_turn=True))
    assert bool(EA.legal_mask(g, 0)[res.action])
    assert abs(float(res.pi.sum()) - 1.0) < 1e-5


def test_puct_select_prefers_high_prior_unvisited():
    node = Node(ToyGame(1), 0)
    mask = np.zeros(EA.num_actions(node.game), dtype=bool)
    mask[[0, 1, 2]] = True
    prior = np.zeros_like(mask, dtype=np.float32)
    prior[2] = 0.9
    prior[0], prior[1] = 0.05, 0.05
    node.expand(prior, mask, 0.0)
    assert P.puct_select(node, mask, c_puct=1.5) == 2


def test_puct_select_uses_q_after_visits():
    node = Node(ToyGame(1), 0)
    mask = np.zeros(EA.num_actions(node.game), dtype=bool)
    mask[[0, 1]] = True
    prior = np.zeros_like(mask, dtype=np.float32)
    prior[0] = prior[1] = 0.5
    node.expand(prior, mask, 0.0)
    node.backup(0, -1.0)
    node.backup(0, -1.0)
    node.backup(1, 1.0)
    assert P.puct_select(node, mask, c_puct=0.1) == 1


def test_visit_distribution_temperature_and_empty():
    counts = np.array([10.0, 1.0, 0.0], dtype=np.float64)
    mask = np.array([True, True, True])
    p0 = visit_distribution(counts, 0.0, mask)
    assert int(np.argmax(p0)) == 0 and float(p0.sum()) == pytest.approx(1.0)
    p1 = visit_distribution(counts, 1.0, mask)
    assert p1[0] > p1[1] > p1[2] == 0.0
    assert float(p1.sum()) == pytest.approx(1.0)
    pe = visit_distribution(np.zeros(3), 1.0, mask)
    assert float(pe.sum()) == pytest.approx(1.0)  # 无访问 → 合法动作均匀


def test_masked_prior_sanitizes_nan_negative_illegal():
    raw = np.array([np.nan, -1.0, 2.0, 1.0], dtype=np.float32)
    mask = np.array([True, True, True, False])
    p = P.masked_prior(raw, mask)
    assert float(p[3]) == 0.0
    assert float(p.sum()) == pytest.approx(1.0)
    p_bad = P.masked_prior(np.zeros(4, dtype=np.float32), mask)
    assert p_bad[0] == p_bad[1] == p_bad[2]
    assert p_bad[3] == 0.0


def test_split_simulations_even_and_min_one():
    assert B.split_simulations(16, 4) == [4, 4, 4, 4]
    assert B.split_simulations(10, 4) == [3, 3, 2, 2]
    assert B.split_simulations(2, 4) == [1, 1, 1, 1]


def test_heuristic_prior_is_legal_distribution_and_deterministic():
    g = toy_in_play()
    obs = EA.observe(g, 0)
    p = heuristic_prior(obs)
    mask = obs.mask
    assert abs(float(p.sum()) - 1.0) < 1e-5
    assert float(p[~mask].sum()) == 0.0
    assert np.array_equal(p, heuristic_prior(EA.observe(g, 0)))
    assert -1.0 <= heuristic_value(obs, 0) <= 1.0


def test_rollout_evaluator_returns_finite_value():
    g = toy_in_play()
    ev = RolloutEvaluator(horizon=4)
    obs = EA.observe(g, 0)
    prior, value = ev(obs, 0, game=g)
    assert abs(float(np.sum(prior)) - 1.0) < 1e-5
    assert np.isfinite(value) and -1.0 <= value <= 1.0


def test_bot_prior_evaluator_blends_bot_action():
    from hsbg.az.policy import BotPriorEvaluator

    g = toy_in_play()
    obs = EA.observe(g, 0)
    ev = BotPriorEvaluator(blend=0.75)
    prior, value = ev(obs, 0, game=g)
    assert abs(float(prior.sum()) - 1.0) < 1e-5
    assert float(prior[~obs.mask].sum()) == 0.0
    a = EA.bot_action(g, 0)
    if bool(obs.mask[a]):
        assert float(prior[a]) > 0.5  # 0.75 blend 的 bot 动作占主导
    assert -1.0 <= value <= 1.0


def test_uniform_evaluator_masks_legal():
    g = toy_in_play()
    obs = EA.observe(g, 0)
    prior, value = UniformEvaluator()(obs, 0)
    assert abs(float(prior.sum()) - 1.0) < 1e-6
    assert float(prior[~obs.mask].sum()) == 0.0
    assert value == 0.0


def test_config_validation():
    g = toy_in_play()
    with pytest.raises(ValueError):
        search(g, 0, simulations=0)
    with pytest.raises(ValueError):
        search(g, 0, determinizations=0)
    with pytest.raises(TypeError):
        search(g, 0, not_a_config_field=1)


def test_placement_utility_endpoints():
    assert placement_utility(1) == 1.0
    assert placement_utility(8) == -1.0
    assert placement_utility(0) == 0.0


def test_source_audit_no_hidden_reads_in_decision_path():
    """静态审计：搜索/世界采样代码不读取真实隐藏状态（view/state_json）。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "hsbg" / "az"
    suspicious = re.compile(r"\.view\s*\(|state_json\s*\(")
    offenders = []
    for name in ("search.py", "belief.py", "puct.py", "policy.py"):
        text = (root / name).read_text(encoding="utf-8")
        # 去掉注释/文档字符串后检查（docstring 会提到这些名字）
        code = re.sub(r'""".*?"""', "", text, flags=re.S)
        code = re.sub(r"#.*", "", code)
        for m in suspicious.finditer(code):
            offenders.append((name, m.group(0)))
    assert not offenders, f"决策路径出现隐藏信息读取调用: {offenders}"


# ══════════════════════════════════════════════════════════════════════
# 2. 引擎层（无 hsbg_engine 时自动 skip）
# ══════════════════════════════════════════════════════════════════════

requires_engine = pytest.mark.skipif(not _HAS_ENGINE, reason="hsbg_engine 未安装")


def engine_midgame(seed: int = 70101, turns: int = 4):
    E = hsbg_engine
    g = E.Game(int(seed))
    EA.finish_hero_select(g)
    EA.warmup_with_bots(g, turns=turns)
    return g


@requires_engine
def test_engine_no_endturn_degeneracy_at_recruit_root():
    """回归测试（Lead 报告的"总选 EndTurn"）：

    招募回合根状态必须满足：pending 标志为 False（pending_kinds[0]=none 不算待选）、
    规则先验把质量放在买入/打出而不是 EndTurn、搜索 argmax 不是 EndTurn。
    """
    g = engine_midgame(seed=70000, turns=1)
    obs = EA.observe(g, 0)
    assert obs.public.has_pending_choice is False
    p = heuristic_prior(obs)
    mask = obs.mask
    assert float(p[EA.END_TURN]) < max(float(p[a]) for a in np.flatnonzero(mask)
                                       if a != EA.END_TURN)
    res = search(g, 0, config=SearchConfig(simulations=16, determinizations=4,
                                           temperature=0.0, seed=3))
    assert int(res.action) != EA.END_TURN, (
        f"搜索退化为 EndTurn: action={res.action}, prior_end={p[EA.END_TURN]:.3f}, "
        f"root_value={res.root_value:.3f}")


@requires_engine
def test_engine_search_smoke_rust_backend():
    g = engine_midgame()
    before = g.state_json()
    res = search(g, 0, config=SearchConfig(simulations=8, determinizations=2,
                                           temperature=1.0, seed=3),
                 engine_backend="rust")
    assert res.info["engine_backend"] == "rust"
    assert res.pi.shape == (EA.N_ACTIONS,)
    mask = EA.legal_mask(g, 0)
    assert bool(mask[res.action])
    assert float(res.pi[~mask].sum()) == 0.0
    assert abs(float(res.pi.sum()) - 1.0) < 1e-4
    assert res.root_value >= -1.0 and res.root_value <= 1.0
    assert res.determinizations == 2
    assert res.visits > 0
    assert res.info["n_evals"] > 0
    # 搜索只读：传入的 game 不被修改
    assert g.state_json() == before
    # determinization 公开信息保持
    assert res.info["world_obs_invariant"] == [True, True]


@requires_engine
def test_engine_determinization_public_invariant_and_hidden_overwrite():
    g = engine_midgame(turns=5)
    f0, c0 = g.observe(0)
    sampler = B.EnginePublicPriorSampler()
    world, info = sampler.sample(g, 0, random.Random(11))
    f1, c1 = world.observe(0)
    assert f0 == f1 and c0 == c1, "determinization 后公开观测必须逐字节一致"
    assert info.obs_invariant is True
    assert info.injected_hidden is True
    assert info.oracle is False
    assert info.n_injections > 0
    # 隐藏世界确实被改写过（用 state_json 仅作为**测试/诊断**证据）
    assert world.state_json() != g.state_json()
    # 源局面不被修改
    f0b, c0b = g.observe(0)
    assert f0 == f0b and c0 == c0b


@requires_engine
def test_engine_search_deterministic_same_seed_python_backend():
    g = engine_midgame(seed=70102, turns=4)
    cfg = SearchConfig(simulations=4, determinizations=2, temperature=1.0, seed=9)
    r1 = search(g, 0, config=cfg, engine_backend="python")
    r2 = search(g, 0, config=cfg, engine_backend="python")
    assert r1.action == r2.action
    assert np.array_equal(r1.pi, r2.pi)
    assert r1.info["engine_backend"] == "python"


@requires_engine
def test_engine_heuristic_prior_legal_and_value_range():
    g = engine_midgame(seed=70103)
    obs = EA.observe(g, 0)
    p = heuristic_prior(obs)
    assert abs(float(p.sum()) - 1.0) < 1e-4
    assert float(p[~obs.mask].sum()) < 1e-6
    assert -1.0 <= heuristic_value(obs, 0) <= 1.0


@requires_engine
def test_engine_search_fallback_on_bad_eval():
    g = engine_midgame(seed=70104)

    def boom(obs, seat, game=None):
        raise RuntimeError("nn crash")

    # python 后端：eval 异常 → 均匀先验 + value 0 继续搜（fallback=True 但仍有 π）
    res = search(g, 0, config=SearchConfig(simulations=4, determinizations=1, seed=1),
                 eval_fn=boom, engine_backend="python")
    assert res.fallback is True
    assert bool(EA.legal_mask(g, 0)[res.action])
    assert abs(float(res.pi.sum()) - 1.0) < 1e-5


@requires_engine
def test_engine_rust_eval_callback_signature_compatible():
    """训练侧 4 参回调（features, cards, mask, seat）直接可用。"""
    g = engine_midgame(seed=70105)
    calls = {"n": 0}

    def eval_fn(features, cards, mask, seat):
        calls["n"] += 1
        assert features.shape == (EA.OBS_FLOATS,)
        assert cards.shape == (EA.OBS_CARDS,)
        assert mask.shape == (EA.N_ACTIONS,)
        prior = mask.astype(np.float32) / max(1.0, float(mask.sum()))
        return prior, 0.0

    res = search(g, 0, config=SearchConfig(simulations=4, determinizations=1, seed=2),
                 eval_fn=eval_fn, engine_backend="rust")
    assert calls["n"] > 0
    assert res.info["n_evals"] == calls["n"]


@pytest.mark.skipif(not _HAS_ENGINE or os.environ.get("AZ_EVAL", "") != "1",
                    reason="慢评测；设置 AZ_EVAL=1 才运行")
def test_engine_small_quality_comparison():
    """2 局配对：heuristic 基线 vs 搜索必须都完成、名次合法（详细报告见 evaluate.py）。"""
    from hsbg.az.evaluate import evaluate_specs
    from hsbg.az.policy import BotAgent, HeuristicAgent, SearchAgent

    def search_factory():
        return SearchAgent(SearchConfig(simulations=8, determinizations=2,
                                        temperature=0.0, seed=0),
                           evaluator=HeuristicEvaluator(), backend="rust")

    report = evaluate_specs(
        {"heuristic": lambda: HeuristicAgent(), "search": search_factory},
        [70110, 70111], seat=0)
    for name in ("heuristic", "search"):
        row = report["agents"][name]
        assert row["games"] == 2
        assert 1 <= row["mean_rank"] <= 8
