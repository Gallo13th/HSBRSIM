"""hsbg.az.train 初期脚手架测试（task-3 验收）。

覆盖：
1. 策略掩码合法性 / 观测无关（引擎无关）
2. 数据集往返、形状、轨迹合法性、质量指标（引擎无关）
3. 训练 loss 有限 + checkpoint 保存/加载 + 监督评估（torch 可选）
4. 评估报告字段校验与落盘（引擎无关）
5. BatchEnv 8 座自对弈 smoke、Game 自对弈确定性、Rust MCTS 策略（需 hsbg_engine）

引擎相关用例在没有 ``hsbg_engine`` 的开发机上自动 skip（保持 `pytest tests -q` 全绿）。
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

from hsbg.az.train import (
    EvalConfig,
    SelfPlayConfig,
    engine_available,
    evaluate_policy,
    make_policy,
)
from hsbg.az.train.common import (
    N_ACTIONS,
    N_PLAYERS,
    OBS_CARDS,
    OBS_FLOATS,
    one_hot_policy,
    uniform_mask_policy,
    utility_from_rank,
)
from hsbg.az.train.data import AZDataset
from hsbg.az.train.policies import HeuristicPolicy, _normalize_search_result
from hsbg.az.train.report import (
    EVAL_SCHEMA,
    build_eval_report,
    build_train_report,
    load_report,
    validate_eval_report,
    write_report,
)

def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


requires_engine = pytest.mark.skipif(
    not engine_available(),
    reason="hsbg_engine 未构建安装（cd rust && python -m pip install -e .）",
)
needs_torch = pytest.mark.skipif(not _torch_available(), reason="torch 不可用")


# ── 测试数据构造 ─────────────────────────────────────────────────────────
def _synthetic_samples(n: int = 64, seed: int = 0) -> list:
    rng = np.random.default_rng(seed)
    samples = []
    for i in range(n):
        mask = np.zeros(N_ACTIONS, dtype=bool)
        legal = rng.choice(N_ACTIONS, size=int(rng.integers(2, 8)), replace=False)
        mask[legal] = True
        action = int(rng.choice(legal))
        pi = np.zeros(N_ACTIONS, dtype=np.float32)
        pi[legal] = rng.random(legal.size).astype(np.float32)
        pi /= pi.sum()
        rank = int(rng.integers(1, N_PLAYERS + 1))
        samples.append({
            "features": rng.normal(size=OBS_FLOATS).astype(np.float32),
            "cards": rng.integers(0, 4000, size=OBS_CARDS).astype(np.int32),
            "mask": mask,
            "action": action,
            "pi": pi if i % 2 == 0 else None,
            "rank": rank,
            "seat": i % N_PLAYERS,
            "turn": int(i % 12),
            "game_id": i // N_PLAYERS,
            "source": 1 if i % 2 == 0 else 0,
        })
    return samples


# ── 1. 策略掩码合法性 ────────────────────────────────────────────────────
def test_policy_only_returns_legal_actions():
    rng = np.random.default_rng(3)
    random_pol = make_policy("random", seed=1)
    heur = HeuristicPolicy()
    for _ in range(50):
        mask = np.zeros(N_ACTIONS, dtype=bool)
        legal = rng.choice(N_ACTIONS, size=int(rng.integers(1, 12)), replace=False)
        mask[legal] = True
        turn = int(rng.integers(0, 15))
        a_rand = random_pol.act_batch(None, None, mask, turn)
        a_heur = heur.act_batch(None, None, mask, turn)
        assert bool(mask[a_rand]), "random 选了非法动作"
        assert bool(mask[a_heur]), "heuristic 选了非法动作"


def test_heuristic_prefers_play_and_falls_back_to_end_turn():
    heur = HeuristicPolicy()
    # 招募阶段：EndTurn(0) + Play(46) + Buy(8) 合法 -> 选 Play
    mask = np.zeros(N_ACTIONS, dtype=bool)
    mask[[0, 8, 46]] = True
    a = heur.act_batch(None, None, mask, turn=3)
    assert a == 46, f"期望优先 Play(46)，实际 {a}"
    # 只有 EndTurn 合法 -> EndTurn
    mask2 = np.zeros(N_ACTIONS, dtype=bool)
    mask2[0] = True
    assert heur.act_batch(None, None, mask2, turn=4) == 0
    # 选择阶段：只有 Choose(30..) 合法 -> 选合法 Choose
    mask3 = np.zeros(N_ACTIONS, dtype=bool)
    mask3[[30, 31]] = True
    assert heur.act_batch(None, None, mask3, turn=5) in (30, 31)


def test_masked_policy_normalization():
    mask = np.zeros(N_ACTIONS, dtype=bool)
    mask[[0, 46]] = True
    pi = uniform_mask_policy(mask)
    assert pi.shape == (N_ACTIONS,)
    assert abs(float(pi.sum()) - 1.0) < 1e-6
    assert not pi[~mask].any()
    one = one_hot_policy(46, mask)
    assert one[46] == 1.0 and abs(float(one.sum()) - 1.0) < 1e-6
    # 非法动作给 one_hot 时退化为合法均匀
    bad = one_hot_policy(123, mask)
    assert abs(float(bad.sum()) - 1.0) < 1e-6 and bad[123] == 0.0


def test_utility_rank_mapping():
    u = utility_from_rank([1, 4, 8, 0])
    assert u[0] == pytest.approx(1.0) and u[2] == pytest.approx(-1.0)
    assert u[3] == pytest.approx(0.0)


# ── 2. 数据集形状/合法性/质量指标 ────────────────────────────────────────
def test_dataset_shapes_legality_and_quality():
    ds = AZDataset.from_samples(_synthetic_samples(64))
    assert len(ds) == 64
    assert ds.arrays["features"].shape == (64, OBS_FLOATS)
    assert ds.arrays["cards"].shape == (64, OBS_CARDS)
    assert ds.arrays["masks"].shape == (64, N_ACTIONS)
    assert ds.arrays["pi"].shape == (64, N_ACTIONS)
    assert ds.arrays["ranks"].shape == (64,)
    assert ds.validate() == [], f"数据集自检失败: {ds.validate()}"
    metrics = ds.quality_metrics()
    assert metrics["samples"] == 64
    assert metrics["legal_action_rate"] == pytest.approx(1.0)
    assert 0.0 <= metrics["search_target_rate"] <= 1.0
    assert metrics["pi_entropy_mean"] >= 0.0
    assert metrics["games"] >= 1
    # pi 行和 ≈ 1
    sums = ds.arrays["pi"].astype(np.float32).sum(axis=1)
    assert np.allclose(sums, 1.0, atol=1e-3)


def test_dataset_save_load_and_concat(tmp_path):
    ds = AZDataset.from_samples(_synthetic_samples(32))
    ds.meta["tag"] = "unit"
    path = os.path.join(tmp_path, "data.npz")
    ds.save(path)
    assert os.path.isfile(path)
    loaded = AZDataset.load(path)
    assert len(loaded) == len(ds)
    for k in ds.arrays:
        assert np.array_equal(ds.arrays[k], loaded.arrays[k]), k
    merged = AZDataset.concat([ds, ds])
    assert len(merged) == 64
    assert merged.meta["samples"] == 64


# ── 3. 训练 loss 有限 + checkpoint ───────────────────────────────────────
@needs_torch
def test_train_loss_finite_and_checkpoint_roundtrip(tmp_path):
    from hsbg.az.train.model import build_net, load_checkpoint, save_checkpoint
    from hsbg.az.train.train_loop import evaluate_supervised, train_policy_value

    ds = AZDataset.from_samples(_synthetic_samples(96))
    net = build_net(hidden=32)
    out = train_policy_value(net, ds, epochs=2, batch_size=32, lr=1e-3, device="cpu", seed=0)
    assert out["samples"] == 96
    assert out["seconds"] > 0
    assert len(out["epochs"]) == 2
    for rec in out["epochs"]:
        assert np.isfinite(rec["loss"]) and rec["loss"] > 0
        assert np.isfinite(rec["policy_loss"]) and np.isfinite(rec["value_loss"])
    assert out["samples_per_s"] > 0
    ckpt = os.path.join(tmp_path, "model.pt")
    save_checkpoint(net, ckpt, meta={"hidden": 32, "samples": 96},
                    norm_mean=out["norm_mean"], norm_std=out["norm_std"])
    assert os.path.isfile(ckpt)
    model2, meta = load_checkpoint(ckpt, device="cpu")
    assert meta["hidden"] == 32
    assert "norm_mean" in meta and "norm_std" in meta
    sup = evaluate_supervised(model2, ds, norm_mean=meta.get("norm_mean"),
                              norm_std=meta.get("norm_std"), device="cpu", limit=64)
    assert sup["samples"] == 64
    assert np.isfinite(sup["policy_top1_agreement"])
    assert sup["policy_top1_agreement"] >= 0.0
    if sup["value_rank_corr"] is not None:
        assert np.isfinite(sup["value_rank_corr"])


# ── 4. 报告字段 ─────────────────────────────────────────────────────────
def _synthetic_policy_metrics(games: int = 3) -> dict:
    return {
        "games": games,
        "games_finished": games,
        "truncated_games": 0,
        "seed_start": 90000,
        "seed_end": 90000 + games - 1,
        "mean_rank": 4.5,
        "top4_rate": 0.5,
        "win_rate": 1.0 / games,
        "rank_counts": {"1": 1, "5": 1, "8": 1},
        "decisions": 100 * games,
        "decisions_per_game": 100.0,
        "illegal_actions": 0,
        "legal_action_rate": 1.0,
        "truncated_combats": 0,
        "seconds": 1.0,
        "ms_per_decision": 10.0,
        "games_per_s": float(games),
    }


def test_eval_report_fields_and_roundtrip(tmp_path):
    engine = {"engine_version": "1.0.0", "game_version": "37.0.0.255130",
              "data_version": "37.0.0.255130", "n_actions": 245,
              "obs_floats": 3227, "obs_cards": 124}
    report = build_eval_report(
        engine=engine,
        protocol={"games_per_policy": 3, "seed_start": 90000, "seed_end": 90002,
                  "policy_seat": 0, "opponent": "engine_bot"},
        policies={"random": _synthetic_policy_metrics(), "bot": _synthetic_policy_metrics()},
        comparison={"random_vs_bot": {"mean_rank_delta": 0.0}},
        data_quality={"samples": 0},
    )
    assert report["schema"] == EVAL_SCHEMA
    assert validate_eval_report(report) == []
    path = os.path.join(tmp_path, "report.json")
    write_report(path, report)
    loaded = load_report(path)
    assert loaded["schema"] == EVAL_SCHEMA
    assert loaded["policies"]["random"]["legal_action_rate"] == pytest.approx(1.0)
    # 故意删字段 -> 校验应报错
    bad = json.loads(json.dumps(report))
    del bad["protocol"]["seed_end"]
    del bad["policies"]["random"]["mean_rank"]
    errs = validate_eval_report(bad)
    assert any("seed_end" in e for e in errs)
    assert any("mean_rank" in e for e in errs)


def test_train_report_builder(tmp_path):
    engine = {"engine_version": "1.0.0", "game_version": "37.0.0.255130",
              "data_version": "37.0.0.255130", "n_actions": 245,
              "obs_floats": 3227, "obs_cards": 124}
    report = build_train_report(
        engine=engine,
        collect={"games": 1, "samples": 10},
        data_quality={"legal_action_rate": 1.0},
        train={"loss_first": 3.0, "loss_last": 2.0, "samples_per_s": 100.0},
        supervised={"value_rank_corr": 0.1, "policy_top1_agreement": 0.2},
        checkpoint="runs/az_eval/x/model.pt",
    )
    assert report["schema"] == "hsbg.az.train_smoke/v1"
    path = os.path.join(tmp_path, "train_report.json")
    write_report(path, report)
    assert os.path.isfile(path)
    assert load_report(path)["train"]["loss_last"] == pytest.approx(2.0)


# ── 5. 搜索结果规范化 ────────────────────────────────────────────────────
def test_normalize_search_result_variants():
    pi = np.zeros(N_ACTIONS, dtype=np.float32)
    pi[[0, 46]] = 0.5
    action, out_pi, info = _normalize_search_result((pi, 46, {"visits": 3}))
    assert action == 46 and np.allclose(out_pi, pi) and info["visits"] == 3

    class Result:
        action = 46
        pi = out_pi
        root_value = 0.1
        visits = 5
        n_simulations = 8
        determinizations = 2
        elapsed_s = 0.01
        fallback = False
        info = {"engine_backend": "rust"}

    action2, pi2, info2 = _normalize_search_result(Result())
    assert action2 == 46
    assert info2["visits"] == 5 and info2["determinizations"] == 2
    assert info2["engine_backend"] == "rust"


def test_make_policy_unknown_raises():
    with pytest.raises(ValueError):
        make_policy("does_not_exist")


# ── 6. 引擎相关：BatchEnv 8 座自对弈 smoke ──────────────────────────────
@requires_engine
def test_batchenv_selfplay_smoke_trajectories():
    from hsbg.az.train.selfplay import collect_selfplay

    pol = make_policy("heuristic")
    cfg = SelfPlayConfig(games=1, seed=42, mode="batch", n_games=1, sample_stride=1,
                         max_steps=20000)
    ds, meta = collect_selfplay(pol, cfg)
    assert len(ds) > 0, "BatchEnv 自对弈没有采到样本"
    assert meta["mode"] == "batch"
    assert meta["games"] == 1, f"未完成 1 局: {meta}"
    # 轨迹形状/合法性
    assert ds.arrays["features"].dtype == np.float32
    assert ds.arrays["features"].shape[1] == OBS_FLOATS
    assert ds.arrays["cards"].shape[1] == OBS_CARDS
    assert ds.arrays["masks"].shape[1] == N_ACTIONS
    assert ds.validate() == [], f"数据集自检失败: {ds.validate()}"
    # 8 个座位都覆盖，名次全部已知（1..8）
    assert int(np.unique(ds.arrays["seat"]).size) == N_PLAYERS
    ranks = ds.arrays["ranks"][ds.arrays["ranks"] >= 1]
    assert ranks.size == len(ds), "存在未知名次样本（应为完整对局）"
    assert set(np.unique(ranks).tolist()) <= set(range(1, N_PLAYERS + 1))
    # utility 与 rank 一致
    util = ds.arrays["utility"]
    expect = utility_from_rank(ds.arrays["ranks"])
    assert np.allclose(util, expect, atol=1e-5)
    metrics = ds.quality_metrics()
    assert metrics["legal_action_rate"] == pytest.approx(1.0)


@requires_engine
def test_game_selfplay_deterministic_same_seed():
    from hsbg.az.train.selfplay import play_selfplay_game

    def run():
        pol = make_policy("random", seed=7)
        samples, meta = play_selfplay_game(pol, seed=123, game_id=0, sample_stride=1)
        acts = [int(s["action"]) for s in samples]
        return acts, meta

    a1, m1 = run()
    a2, m2 = run()
    assert a1 == a2, "同 seed 同策略的动作序列不一致（破坏确定性）"
    assert m1["truncated"] == m2["truncated"]
    assert len(a1) >= 8
    assert m1["illegal_actions"] == 0


@requires_engine
def test_rust_mcts_policy_decisions_legal():
    import hsbg_engine as E

    from hsbg.az.train.evaluators import make_evaluator
    from hsbg.az.train.policies import RustMCTSPolicy

    if not hasattr(E, "mcts_search"):
        pytest.skip("当前 hsbg_engine 构建无 mcts_search")
    game = E.Game(seed=11)
    pol = RustMCTSPolicy(simulations=2, seed=0, evaluator=None)
    # 无评估器 = uniform prior + value 0（不依赖网络即可跑）
    dec = pol.decide(game, 0)
    mask = np.frombuffer(game.legal_mask(0), dtype=np.uint8).astype(bool)
    assert bool(mask[int(dec.action)]), "Rust MCTS 返回了非法动作"
    assert dec.pi is not None and abs(float(dec.pi.sum()) - 1.0) < 1e-4
    pol2 = RustMCTSPolicy(simulations=2, seed=0, evaluator=make_evaluator("heuristic"))
    dec2 = pol2.decide(game, 0)
    assert bool(mask[int(dec2.action)])


@requires_engine
def test_eval_one_game_report_and_validate():
    pol = make_policy("random", seed=5)
    cfg = EvalConfig(games=1, seed=99000, max_steps=20000)
    res = evaluate_policy(pol, cfg)
    assert res["games"] == 1
    assert res["games_finished"] + res["truncated_games"] == 1
    assert 0.0 <= float(res["legal_action_rate"]) <= 1.0
    assert res["decisions"] > 0
    assert res["seconds"] > 0
    if res["games_finished"] == 1:
        assert 1 <= int(list(res["rank_counts"])[0]) <= N_PLAYERS
    engine = {"engine_version": "1.0.0", "game_version": "37.0.0.255130",
              "data_version": "37.0.0.255130", "n_actions": 245,
              "obs_floats": 3227, "obs_cards": 124}
    report = build_eval_report(
        engine=engine,
        protocol={"games_per_policy": 1, "seed_start": 99000, "seed_end": 99000,
                  "policy_seat": 0, "opponent": "engine_bot"},
        policies={"random": res},
    )
    assert validate_eval_report(report) == []
