"""方向 A 场面题的**两个强度开关**单测（``docs/BOARD_PROBLEMS.md`` §12）。

覆盖：

1. **turn 权重解析**：``"10:2,12:3,14:4,15:4"`` 语法/字典、空白、重复、权重 0；
   **非法输入一律 ``ValueError``**（不静默）：缺 ``:``、非整数 turn、负 turn、
   负/非有限 weight、空项、重复且不一致；
2. **加权生效**：同一批题目上 ``problem_bc_soft_ce`` 的加权损失 = 手算值
   （``Σ w CE / Σ w``，只在 ``bc_valid`` 行上）；``weight=None`` 时走原来的算术
   （``ce[valid].mean()``，逐位等价路径）；
3. **delta 过滤**：``load_problem_pool(min_strength_delta=…)`` 池子变小、保留下来的题
   ``strength_delta`` 都 ≥ 阈值、报告计数（池大小/按 delta 丢/按 turn 丢）正确；
   缺 ``label.strength_delta`` 且阈值 > 0 时**报错**而不是静默；
4. **默认逐位等价**：空权重 + delta=0 时，同 seed 训练 **2 iter** 的权重 sha256
   与「不传新开关」完全相同；默认关闭时 stats/config 里不出现新键；
5. **``--focus-turns``**：``ProblemCollectConfig.focus_allows`` 只看目标区间；
   真实 rollout 下只产出目标 turn 的题（需要 ``hsbg_engine``）；
6. **入口开关**：``train_entity_sync.py`` / ``build_board_problems.py`` 暴露两个新参数，
   非法值以退出码 2 报错。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.board_problems import (
    LATE_TURN_MIN,
    PROBLEM_SCHEMA_VERSION,
    BoardProblemBatch,
    ProblemCollectConfig,
    collect_problems,
    encode_obs,
    filter_problem_rows,
    format_turn_weights,
    load_problem_pool,
    parse_turn_ranges,
    parse_turn_weights,
    problem_bc_soft_ce,
    problem_obs_batch,
    problem_strength_delta,
    problem_stats,
    turn_in_focus,
    turn_weight_vector,
    write_problems,
    ProblemCollectResult,
)
from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _torch():
    return pytest.importorskip("torch")


def _engine_ok() -> bool:
    try:
        from hsbg.az.train.common import engine_available
        return bool(engine_available())
    except Exception:  # noqa: BLE001 - 引擎缺失 -> 跳过 rollout 测试
        return False


# ══════════════════════════════════════════════════════════════════════════
# 1. turn 权重 / turn 段解析
# ══════════════════════════════════════════════════════════════════════════
def test_parse_turn_weights_ok():
    w = parse_turn_weights("10:2,12:3,14:4,15:4")
    assert w == {10: 2.0, 12: 3.0, 14: 4.0, 15: 4.0}
    # 空白、浮点权重、权重 0（= 剔除该 turn）都要能解析
    assert parse_turn_weights(" 5 : 0.5 , 7:0 ") == {5: 0.5, 7: 0.0}
    # 默认关闭：空串/None/空字典 -> {}
    assert parse_turn_weights("") == {}
    assert parse_turn_weights("   ") == {}
    assert parse_turn_weights(None) == {}
    assert parse_turn_weights({}) == {}
    # Mapping 形式（trainer.pt 里回显的是字符串，这里两种都支持）
    assert parse_turn_weights({10: 2, "12": 3.0}) == {10: 2.0, 12: 3.0}
    # 重复但**一致**的权重允许（去重）
    assert parse_turn_weights("10:2,10:2.0") == {10: 2.0}
    # 回显
    assert format_turn_weights({10: 2.0, 12: 3.0}) == "10:2,12:3"
    assert format_turn_weights({}) == ""


@pytest.mark.parametrize("spec", [
    "10",                 # 缺 ':'
    "10:",                # 缺 weight
    ":2",                 # 缺 turn
    "a:2",                # turn 非整数
    "-1:2",               # 负 turn
    "10:-1",              # 负权重
    "10:nan",             # 非有限
    "10:inf",             # 非有限
    "10:2,10:3",          # 重复且不一致
    "10:2,,12:3",         # 空项（逗号连写）
    "10:2,",              # 尾随空项
    [10, 2],              # 非字符串/字典
    3.5,                  # 非字符串/字典
])
def test_parse_turn_weights_rejects_invalid(spec):
    with pytest.raises(ValueError):
        parse_turn_weights(spec)


def test_parse_turn_ranges_and_focus():
    assert parse_turn_ranges("") == []
    assert parse_turn_ranges("10-15") == [(10, 15)]
    assert parse_turn_ranges("10-15,8") == [(8, 8), (10, 15)]
    assert parse_turn_ranges("8,8-9") == [(8, 9)]      # 重叠区间合并
    assert turn_in_focus(12, parse_turn_ranges("10-15"))
    assert not turn_in_focus(9, parse_turn_ranges("10-15"))
    assert turn_in_focus(3, [])                        # 空 = 全部
    for bad in ("15-10", "-1-3", "a-b", "10-", "10-15,,"):
        with pytest.raises(ValueError):
            parse_turn_ranges(bad)
    cfg = ProblemCollectConfig(focus_turns="10-15")
    assert cfg.focus_allows(10) and cfg.focus_allows(15)
    assert not cfg.focus_allows(9)
    assert ProblemCollectConfig().focus_allows(1)


def test_turn_weight_vector_defaults_to_one():
    turns = np.asarray([5, 6, 7, 15], np.int16)
    w = turn_weight_vector(turns, {6: 2.0, 15: 0.0})
    assert w.dtype == np.float32
    assert w.tolist() == [1.0, 2.0, 1.0, 0.0]


# ══════════════════════════════════════════════════════════════════════════
# 2. 加权 soft-CE = 手算值
# ══════════════════════════════════════════════════════════════════════════
def _soft_ce_batch(turn_weights=None, seed=3):
    """4 行题目：合法动作 {0,1,8,9}，soft 标签固定，bc_valid=[T,T,F,T]。"""
    rng = np.random.default_rng(seed)
    n = 4
    mask = np.zeros((n, N_ACTIONS), bool)
    mask[:, [0, 1, 8, 9]] = True
    soft = np.zeros((n, N_ACTIONS), np.float32)
    for i in range(n):
        soft[i, 0] = 0.7
        soft[i, 8] = 0.3
    logits = np.zeros((n, N_ACTIONS), np.float32)
    logits[:, 0] = 0.5
    logits[:, 1] = -0.25
    logits[:, 8] = 1.5
    logits[:, 9] = -2.0
    logits[:, 40] = 9.0        # 非法动作的高 logit（必须被 mask 掉）
    batch = BoardProblemBatch(
        features=rng.normal(size=(n, OBS_FLOATS)).astype(np.float32),
        cards=rng.integers(0, 300, size=(n, OBS_CARDS)).astype(np.int32),
        mask=mask, soft=soft, bc_valid=np.asarray([1, 1, 0, 1], bool),
        strength_target=np.zeros(n, np.float32),
        tier_target=np.zeros(n, np.float32), aux_valid=np.zeros(n, bool),
        ref_top1=np.zeros(n, np.int16),
        policy_action=np.zeros(n, np.int16),
        turn=np.asarray([5, 6, 7, 15], np.int16),
        weight=(np.asarray(turn_weights, np.float32)
                if turn_weights is not None else None))
    return batch, logits


def _hand_soft_ce(logits, soft, mask, valid, weight=None) -> float:
    """手算：masked log-softmax -> CE -> （加权）均值。纯 numpy，不依赖实现。"""
    lg = np.asarray(logits, np.float64).copy()
    msk = np.asarray(mask, bool)
    lg[~msk] = -np.inf
    m = lg.max(axis=1, keepdims=True)
    lse = m + np.log(np.exp(lg - m).sum(axis=1, keepdims=True))
    logp = np.where(msk, lg - lse, 0.0)
    ce = -(np.asarray(soft, np.float64) * logp).sum(axis=1)
    v = np.asarray(valid, bool)
    if weight is None:
        return float(ce[v].mean())
    w = np.asarray(weight, np.float64)[v]
    return float((ce[v] * w).sum() / w.sum())


def test_turn_weight_soft_ce_matches_hand_computation():
    torch = _torch()
    w = np.asarray([1.0, 3.0, 2.0, 5.0], np.float32)   # 行 2 无效，权重不参与分母
    batch, logits = _soft_ce_batch(turn_weights=w)
    out = problem_bc_soft_ce(torch.from_numpy(logits), batch)
    expect = _hand_soft_ce(logits, batch.soft, batch.mask, batch.bc_valid, w)
    assert float(out["loss"]) == pytest.approx(expect, rel=1e-6)
    assert out["n"] == 3
    assert out["weight_sum"] == pytest.approx(float(w[[0, 1, 3]].sum()))
    # 权重全 1 时与不加权（None 路径）在数值上等价（这里用 approx，默认走 None 路径）
    b1, lg1 = _soft_ce_batch(turn_weights=np.ones(4, np.float32))
    out1 = problem_bc_soft_ce(torch.from_numpy(lg1), b1)
    b0, lg0 = _soft_ce_batch(turn_weights=None)
    out0 = problem_bc_soft_ce(torch.from_numpy(lg0), b0)
    assert float(out1["loss"]) == pytest.approx(float(out0["loss"]), rel=1e-6)


def test_soft_ce_default_path_is_plain_mean():
    torch = _torch()
    batch, logits = _soft_ce_batch(turn_weights=None)
    assert batch.weight is None
    out = problem_bc_soft_ce(torch.from_numpy(logits), batch)
    expect = _hand_soft_ce(logits, batch.soft, batch.mask, batch.bc_valid, None)
    assert float(out["loss"]) == pytest.approx(expect, rel=1e-6)
    assert out["weight_sum"] == 3.0
    # 无有效行 -> 0（不制造假梯度）
    b = BoardProblemBatch(
        features=batch.features, cards=batch.cards, mask=batch.mask,
        soft=batch.soft, bc_valid=np.zeros(4, bool),
        strength_target=batch.strength_target, tier_target=batch.tier_target,
        aux_valid=batch.aux_valid, ref_top1=batch.ref_top1,
        policy_action=batch.policy_action, turn=batch.turn, weight=None)
    out0 = problem_bc_soft_ce(torch.from_numpy(logits), b)
    assert float(out0["loss"]) == 0.0 and out0["n"] == 0


# ══════════════════════════════════════════════════════════════════════════
# 3. delta 过滤 + turn 权重剔除
# ══════════════════════════════════════════════════════════════════════════
def _row(i, *, turn=6, delta=1.0, with_delta_field=True, tier=3):
    rng = np.random.default_rng(1000 + i)
    f = rng.normal(size=OBS_FLOATS).astype(np.float32)
    c = rng.integers(0, 300, size=OBS_CARDS).astype(np.int32)
    m = np.zeros(N_ACTIONS, bool)
    legal = rng.choice(np.arange(0, 40), size=5, replace=False)
    m[legal] = True
    before = 100.0 + 50.0 * i
    after = float(np.expm1(np.log1p(before) + float(delta)))
    lab = {"strength_before": before, "strength_after_t3": after,
           "delta": after - before, "delta_log1p": float(delta),
           "tier_before": tier, "tier_after": tier + 1, "tier_up": 1,
           "survived": 1, "terminal": 0, "available": 1, "horizon": 3,
           "target_turn": turn + 3}
    if with_delta_field:
        lab["strength_delta"] = float(delta)
    return {
        "problem_id": f"bp-{i:06d}", "schema": PROBLEM_SCHEMA_VERSION,
        "source_group": "rollout:seed=1:game=0", "game_seed": 1,
        "turn": int(turn), "is_late_turn": bool(turn >= LATE_TURN_MIN),
        "seat": 0, "decision_idx": 0, "tags": ["turn_start"],
        "obs": encode_obs(f, c, m, dtype="f32"),
        "state": {"gold": 5, "tier": tier, "strength": int(before)},
        "policy_action": int(legal[0]), "policy_prob": 0.5,
        "ref": {"actions": [int(legal[0])], "weights": [1.0], "matched": True,
                "level": "turn_tier", "floor": 10000, "support": 100,
                "mass_legal": 0.5, "reason": "ok"},
        "label": lab, "strength_delta": float(delta),
        "move": {"last": -1, "n": 0, "counts": []},
    }


def _write_pool(tmp_path, rows):
    result = ProblemCollectResult(problems=list(rows), stats={})
    path, _meta = write_problems(result, str(tmp_path / "problems.jsonl"))
    return path


def test_delta_filter_shrinks_pool_and_keeps_threshold(tmp_path):
    deltas = [0.2, 0.4, 0.5, 0.6, 0.9, 1.2]
    rows = [_row(i, turn=6, delta=d) for i, d in enumerate(deltas)]
    path = _write_pool(tmp_path, rows)
    pool0 = load_problem_pool(path)
    assert len(pool0) == len(rows)
    assert pool0.filter_report["problem_pool_dropped_by_delta"] == 0
    assert pool0.filter_report["problem_pool_size"] == len(rows)
    pool = load_problem_pool(path, min_strength_delta=0.5)
    kept = [r for r, d in zip(rows, deltas) if d >= 0.5]
    assert len(pool) == len(kept) == 4
    assert pool.filter_report["problem_pool_dropped_by_delta"] == 2
    assert pool.filter_report["problem_pool_used"] == 4
    # 保留下来的题 delta 都 >= 阈值（从池里的数组和统计两侧都核）
    assert np.all(pool.strength_delta >= 0.5 - 1e-6)
    assert problem_strength_delta(rows[0]) == pytest.approx(deltas[0])
    kept_rows = [dict(r) for r in kept]
    stats = problem_stats(kept_rows)
    assert stats["strength_delta_p50"] == pytest.approx(
        float(np.percentile([r["strength_delta"] for r in kept_rows], 50)))
    assert stats["late_turn_min"] == int(LATE_TURN_MIN)


def test_delta_filter_uses_delta_log1p_fallback(tmp_path):
    # 老池子只有 label.delta_log1p（没有 label.strength_delta）：必须仍能过滤
    rows = [_row(0, delta=0.3, with_delta_field=False),
            _row(1, delta=1.1, with_delta_field=False)]
    path = _write_pool(tmp_path, rows)
    pool = load_problem_pool(path, min_strength_delta=0.5)
    assert len(pool) == 1
    assert float(pool.strength_delta[0]) == pytest.approx(1.1, abs=1e-4)


def test_delta_filter_errors_when_label_missing(tmp_path):
    rows = [_row(0, delta=1.0)]
    del rows[0]["label"]["strength_delta"], rows[0]["label"]["delta_log1p"]
    del rows[0]["strength_delta"]
    path = _write_pool(tmp_path, rows)
    assert len(load_problem_pool(path)) == 1        # 默认（0）不读 delta
    with pytest.raises(ValueError):
        load_problem_pool(path, min_strength_delta=0.5)
    with pytest.raises(ValueError):
        load_problem_pool(path, min_strength_delta=-0.1)


def test_turn_weight_zero_drops_turn_rows(tmp_path):
    rows = [_row(i, turn=t, delta=1.0) for i, t in enumerate([5, 6, 7, 10, 12])]
    path = _write_pool(tmp_path, rows)
    pool = load_problem_pool(path, turn_weights={6: 0, 10: 3})
    assert pool.turn.tolist() == [5, 7, 10, 12]
    assert pool.filter_report["problem_pool_dropped_by_turn"] == 1
    # 未列出的 turn = 1；权重 3 的行权重 3
    assert pool.turn_weight.tolist() == [1.0, 1.0, 3.0, 1.0]
    assert pool.turn_weights == {6: 0.0, 10: 3.0}
    # 默认：不加权 -> turn_weight 为 None，batch.weight 为 None（逐位等价路径）
    p0 = load_problem_pool(path)
    assert p0.turn_weight is None
    b0 = problem_obs_batch(p0, np.arange(len(p0)))
    assert b0.weight is None
    b1 = problem_obs_batch(pool, np.arange(len(pool)))
    assert b1.weight is not None and b1.turn.tolist() == pool.turn.tolist()
    # 过滤报告口径 = history 字段
    rep = pool.filter_report
    assert rep["problem_pool_size"] == 5 and rep["problem_pool_used"] == 4


def test_filter_problem_rows_reports_and_validation():
    rows = [_row(0, turn=6, delta=0.1), _row(1, turn=12, delta=0.9),
            _row(2, turn=15, delta=1.4)]
    kept, report = filter_problem_rows(rows, min_strength_delta=0.5,
                                       turn_weights="15:0")
    assert [r["problem_id"] for r in kept] == ["bp-000001"]
    assert report["problem_pool_dropped_by_delta"] == 1
    assert report["problem_pool_dropped_by_turn"] == 1
    assert report["problem_pool_size"] == 3 and report["problem_pool_used"] == 1
    with pytest.raises(ValueError):
        filter_problem_rows(rows, min_strength_delta=float("nan"))
    with pytest.raises(ValueError):
        filter_problem_rows(rows, turn_weights="12")


# ══════════════════════════════════════════════════════════════════════════
# 4. 默认关闭 = 逐位等价（同 seed 训练 2 iter，记录 sha256）
# ══════════════════════════════════════════════════════════════════════════
def _entity(d_model=32):
    _torch()
    from hsbg.az.train.entity_model import (CardTables, TEXT_DIM,
                                            build_entity_net)
    tables = CardTables(static=np.zeros((64, 56), np.float32),
                        text=np.zeros((64, TEXT_DIM), np.float32), n_cards=64)
    return build_entity_net(d_model=d_model, n_layers=1, n_heads=4, dim_ff=64,
                            card_dim=8, tables=tables, strength_head=True)


def _policy_batch(model, n_games=2, decisions_per_seat=2, seed=7):
    torch = _torch()
    from hsbg.az.train.common import N_PLAYERS
    from hsbg.az.train.ppo import (build_batch_from_records, masked_probs_np,
                                   value_from_rank_logits_np)
    rng = np.random.default_rng(seed)
    records = []
    model.eval()
    for g in range(n_games):
        for seat in range(N_PLAYERS):
            rank = int((g * 3 + seat) % N_PLAYERS) + 1
            for t in range(decisions_per_seat):
                features = rng.normal(size=OBS_FLOATS).astype(np.float32)
                cards = np.zeros(OBS_CARDS, dtype=np.int32)
                mask = np.zeros(N_ACTIONS, dtype=bool)
                legal = rng.choice(np.arange(8, 60), size=5, replace=False)
                mask[legal] = True
                mask[0] = True
                x = torch.from_numpy(features.reshape(1, -1))
                c = torch.from_numpy(cards.astype(np.int64).reshape(1, -1))
                m = torch.from_numpy(mask.reshape(1, -1))
                with torch.no_grad():
                    out = model(x, c, m)
                probs = masked_probs_np(out[0].numpy()[0], mask)
                probs = probs / max(float(probs.sum()), 1e-12)
                action = int(rng.choice(N_ACTIONS, p=probs))
                records.append({
                    "features": features, "cards": cards, "mask": mask,
                    "action": action,
                    "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
                    "value": float(value_from_rank_logits_np(out[1].numpy()[0])[0]),
                    "target_pi": None, "rank": rank, "seat": seat,
                    "game_id": g, "turn": t,
                })
    return build_batch_from_records(records, gamma=1.0, lam=0.95,
                                    step_penalty=1e-3)


def _model_sha(model) -> str:
    h = hashlib.sha256()
    for k, v in model.state_dict().items():
        h.update(k.encode())
        h.update(np.ascontiguousarray(v.detach().cpu().numpy()).tobytes())
    return h.hexdigest()


def _cfg(**kw):
    from hsbg.az.train.ppo import PPOConfig
    base = dict(minibatch=4, epochs=1, lr=1e-3, pi_coef=0.0, entropy_coef=0.0,
                value_coef=0.5, device="cpu", seed=0, kl_early_stop=False,
                compile_train=0, max_grad_norm=10.0, problem_bc_coef=0.05,
                problem_batch=16)
    base.update(kw)
    return PPOConfig(**base)


def _two_iter_sha(pool, batch, *, cfg_kw=None, iters=2):
    """同 seed 训练 ``iters`` iter（固定 batch + 固定题池）-> 权重 sha256。"""
    torch = _torch()
    from hsbg.az.train.ppo import train_ppo
    torch.manual_seed(0)
    model = _entity()
    cfg = _cfg(**(cfg_kw or {}))
    sel = np.arange(min(16, len(pool)))
    from hsbg.az.train.board_problems import problem_obs_batch as _pob
    pb = _pob(pool, sel)
    for _ in range(iters):
        train_ppo(model, batch, cfg, problem_batch=pb)
    return _model_sha(model), model


def test_default_switches_bitwise_two_iters(tmp_path):
    """空权重 + delta=0 与「不传新开关」逐位等价（同 seed、2 iter、sha256 相同）。"""
    _torch()
    rows = [_row(i, turn=t, delta=d)
            for i, (t, d) in enumerate(zip([5, 6, 7, 10, 12, 15],
                                           [0.2, 0.6, 1.2, 0.4, 1.5, 0.9]))]
    path = _write_pool(tmp_path, rows)
    pool_default = load_problem_pool(path)
    batch = _policy_batch(_entity())
    sha_default, _ = _two_iter_sha(pool_default, batch)
    # 显式传「空权重 + 0 阈值」：必须完全一样
    pool_explicit = load_problem_pool(path, min_strength_delta=0.0,
                                     turn_weights="")
    assert pool_explicit.filter_report["problem_pool_used"] == len(rows)
    assert pool_explicit.turn_weight is None
    sha_explicit, _ = _two_iter_sha(pool_explicit, batch)
    assert sha_default == sha_explicit
    # 再跑一次同 seed：确定性（否则上面的相等没有意义）
    sha_again, _ = _two_iter_sha(pool_default, batch)
    assert sha_again == sha_default
    # 换成真的加权（10:2,12:3,14:4,15:4）后权重**必须**变化（否则开关是空转）
    pool_w = load_problem_pool(path, turn_weights="10:2,12:3,14:4,15:4")
    sha_weighted, _ = _two_iter_sha(pool_w, batch)
    assert sha_weighted != sha_default


def test_disabled_new_keys_absent_from_stats(tmp_path):
    """coef=0（默认）时新开关不进 stats/config；启用时才出现。"""
    _torch()
    from hsbg.az.train.ppo import train_ppo
    model = _entity()
    batch = _policy_batch(model)
    rows = [_row(0, turn=6, delta=0.2), _row(1, turn=12, delta=1.4)]
    pool = load_problem_pool(_write_pool(tmp_path, rows))
    pb = problem_obs_batch(pool, np.arange(len(pool)))
    st0 = train_ppo(model, batch, _cfg(problem_bc_coef=0.0), problem_batch=pb)
    for key in ("problem_turn_weight", "problem_min_strength_delta",
                "problem_pool_size", "problem_pool_dropped_by_delta",
                "problem_pool_dropped_by_turn"):
        assert key not in st0["config"], key
        assert key not in st0, key
    st1 = train_ppo(model, batch, _cfg(problem_bc_coef=0.05), problem_batch=pb)
    assert st1["config"]["problem_turn_weight"] == ""
    assert st1["config"]["problem_min_strength_delta"] == 0.0
    assert "problem_bc_loss" in st1


def test_ppo_config_validates_new_switches():
    from hsbg.az.train.ppo import PPOConfig
    with pytest.raises(ValueError):
        PPOConfig(problem_turn_weight="10")
    with pytest.raises(ValueError):
        PPOConfig(problem_turn_weight="10:-2")
    with pytest.raises(ValueError):
        PPOConfig(problem_min_strength_delta=-0.1)
    with pytest.raises(ValueError):
        PPOConfig(problem_min_strength_delta=float("nan"))
    cfg = PPOConfig(problem_turn_weight="10:2,12:3",
                    problem_min_strength_delta=0.5)
    assert float(cfg.problem_min_strength_delta) == 0.5
    assert PPOConfig().problem_turn_weight == ""
    assert PPOConfig().problem_min_strength_delta == 0.0


def test_trainer_pool_report_fields(tmp_path):
    """训练器把池过滤口径暴露给 history（problem_pool_size/dropped_by_*）。"""
    _torch()
    from hsbg.az.train.ppo import PPOConfig
    from hsbg.az.train.ppo_trainer import PPOTrainer
    rows = [_row(0, turn=5, delta=0.2), _row(1, turn=10, delta=0.9),
            _row(2, turn=15, delta=1.4)]
    path = _write_pool(tmp_path, rows)
    tr = PPOTrainer(_entity(), PPOConfig(device="cpu", problem_bc_coef=0.05,
                                         problem_min_strength_delta=0.5,
                                         problem_turn_weight="15:0"))
    from hsbg.az.train.board_problems import load_problem_pool as _load
    tr.set_problem_pool(_load(path, min_strength_delta=0.5,
                              turn_weights="15:0"))
    rep = tr.problem_report()
    assert rep["problem_pool_size"] == 3
    assert rep["problem_pool_used"] == 1
    assert rep["problem_pool_dropped_by_delta"] == 1
    assert rep["problem_pool_dropped_by_turn"] == 1
    assert rep["problem_pool_min_strength_delta"] == 0.5
    assert rep["problem_pool_turn_weight"] == "15:0"
    # 默认（无池）-> 空报告（不产生 history 键）
    assert PPOTrainer(_entity(), PPOConfig(device="cpu")).problem_report() == {}


# ══════════════════════════════════════════════════════════════════════════
# 5. --focus-turns 只产出目标 turn 的题（需要引擎）
# ══════════════════════════════════════════════════════════════════════════
def _collect(model, cfg):
    return collect_problems(model, cfg, device="cpu")


@pytest.mark.skipif(not _engine_ok(), reason="需要 hsbg_engine")
def test_focus_turns_only_produces_target_turns():
    model = _entity()
    base = dict(games=1, seed=20200, max_steps=20000, human_board_p=0.0,
                mirror_p=0.0, move_guard=True, move_cap=3,
                move_repeat_limit=2, min_turn=1, obs_dtype="f32")
    r_all = _collect(model, ProblemCollectConfig(**base))
    assert len(r_all.problems) > 0
    turns = [int(p["turn"]) for p in r_all.problems]
    tmax = max(turns)
    if tmax < 4:
        pytest.skip(f"rollout 只到 t{tmax}，无法验证 focus 区间")
    lo, hi = 2, tmax - 1
    r_focus = _collect(model, ProblemCollectConfig(focus_turns=f"{lo}-{hi}", **base))
    fturns = [int(p["turn"]) for p in r_focus.problems]
    assert fturns, "focus 区间内应当仍有题"
    assert all(lo <= t <= hi for t in fturns)
    assert max(fturns) <= hi
    assert len(fturns) < len(turns)                     # 真的丢掉了区间外的题
    assert int(r_focus.stats["skipped"].get("focus_turn", 0)) > 0
    # 同 seed：区间内的题与全量池里的题观测指纹一致（只是被裁剪）
    keep = {p["obs"]["sha256"] for p in r_all.problems
            if lo <= int(p["turn"]) <= hi}
    assert set(p["obs"]["sha256"] for p in r_focus.problems) <= keep


@pytest.mark.skipif(not _engine_ok(), reason="需要 hsbg_engine")
def test_min_delta_applied_at_collection_time():
    model = _entity()
    base = dict(games=1, seed=20200, max_steps=20000, human_board_p=0.0,
                mirror_p=0.0, min_turn=1, obs_dtype="f32")
    r_all = _collect(model, ProblemCollectConfig(**base))
    deltas = [problem_strength_delta(p) for p in r_all.problems]
    assert deltas
    lo, hi = float(np.min(deltas)), float(np.max(deltas))
    if hi - lo < 1e-3:
        pytest.skip(f"退化 rollout：所有题 delta 相同（{lo:.3f}）")
    thr = (lo + hi) / 2.0
    r_f = _collect(model, ProblemCollectConfig(min_delta=thr, **base))
    kept = [problem_strength_delta(p) for p in r_f.problems]
    assert kept and all(d >= thr - 1e-6 for d in kept)
    assert len(r_f.problems) < len(r_all.problems)
    assert int(r_f.stats["skipped"].get("min_delta", 0)) > 0


# ══════════════════════════════════════════════════════════════════════════
# 6. 入口脚本暴露 + 非法输入以退出码 2 报错
# ══════════════════════════════════════════════════════════════════════════
def _run(script, args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script)]
                          + list(args), capture_output=True, text=True,
                          cwd=ROOT, timeout=180,
                          env={**os.environ, "PYTHONPATH": "rust/python:."})


def test_entry_scripts_expose_switches():
    out = _run("train_entity_sync.py", ["--help"])
    assert out.returncode == 0, out.stderr[-2000:]
    for flag in ("--problem-turn-weight", "--problem-min-strength-delta"):
        assert flag in out.stdout, flag
    out2 = _run("build_board_problems.py", ["--help"])
    assert out2.returncode == 0, out2.stderr[-2000:]
    for flag in ("--focus-turns", "--min-delta"):
        assert flag in out2.stdout, flag


def test_entry_scripts_reject_invalid_switch_values():
    # 非法 turn 权重语法 -> 退出码 2（不静默降级）
    bad = _run("train_entity_sync.py",
               ["--problem-turn-weight", "10", "--games", "1"])
    assert bad.returncode == 2, bad.stderr[-2000:]
    assert "problem-turn-weight" in bad.stderr
    # 非法 focus 区间 -> 退出码 2
    bad2 = _run("build_board_problems.py",
                ["--focus-turns", "15-10", "--games", "1"])
    assert bad2.returncode == 2, bad2.stderr[-2000:]
    assert "focus-turns" in bad2.stderr
    # 负阈值 -> 退出码 2（build 与 train 两侧）
    bad3 = _run("build_board_problems.py", ["--min-delta", "-1", "--games", "1"])
    assert bad3.returncode == 2, bad3.stderr[-2000:]
    bad4 = _run("train_entity_sync.py",
                ["--problem-min-strength-delta", "-1", "--games", "1"])
    assert bad4.returncode == 2, bad4.stderr[-2000:]
