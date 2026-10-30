"""势函数奖励塑形（potential-based shaping）单测。

覆盖（见 ``docs/REWARD_SHAPING.md``）：

1. tier 表解析 / 越界 / 非法值安全；
2. Φ 手算数值（board Σ(atk+hp) + tier bonus）与空 board / 缺字段；
3. ``F = λ(γΦ(s')−Φ(s))`` 与系数；
4. ``shaping_coef=0`` 时 records / packed / batch.rewards 与旧路径一致（无 reward 字段、
   同 seed 两次采集逐位相同）；
5. lockstep 接线：reward 字段 = 由观测重算的势函数差（含局末 Φ=0），方向正确；
6. tier 越界 / 空 board / mock 无 observe 的兜底；
7. 开销微基准（可选，宽松阈值）；
8. 训练入口暴露 ``--shaping-*`` 参数。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.common import (N_ACTIONS, OBS_CARDS, OBS_FLOATS,
                                  utility_from_rank)
from hsbg.az.train.ppo import (CollectConfig, build_batch_from_arrays,
                               build_batch_from_records, pack_records_arrays)
from hsbg.az.train.reward_shaping import (DEFAULT_TIER_BONUS, SHAPING_GAMMA,
                                          RewardShaper, aggregate_shaping,
                                          parse_tier_bonus, potential,
                                          potential_from_obs,
                                          potential_from_player,
                                          potential_from_player_json,
                                          shaping_reward, tier_bonus_value)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _onehot_mask(action: int) -> np.ndarray:
    m = np.zeros(N_ACTIONS, dtype=np.float32)
    m[int(action)] = 1.0
    return m


def _synthetic_records(*, game_id: int = 0, turns=(0, 1, 2), rank: int = 2,
                       rewards=None, seat: int = 0) -> list:
    recs = []
    for i, turn in enumerate(turns):
        rec = {
            "features": np.zeros(OBS_FLOATS, dtype=np.float32),
            "cards": np.zeros(OBS_CARDS, dtype=np.int32),
            "mask": _onehot_mask(1),
            "action": 1,
            "old_logprob": -0.1,
            "value": 0.5,
            "target_pi": None,
            "rank": int(rank),
            "seat": int(seat),
            "game_id": int(game_id),
            "turn": int(turn),
        }
        if rewards is not None:
            rec["reward"] = float(rewards[i])
        recs.append(rec)
    return recs


# ── 1. tier 表 ──────────────────────────────────────────────────────────
def test_tier_bonus_parse_and_bounds():
    table = parse_tier_bonus("0,0,20,60,150,400,900")
    assert table == DEFAULT_TIER_BONUS
    assert parse_tier_bonus(None) == DEFAULT_TIER_BONUS
    assert parse_tier_bonus("") == DEFAULT_TIER_BONUS
    assert parse_tier_bonus([0, 1, 2]) == (0.0, 1.0, 2.0)
    assert parse_tier_bonus("0; 1; 2") == (0.0, 1.0, 2.0)
    assert tier_bonus_value(1, table) == 0.0
    assert tier_bonus_value(4, table) == 150.0
    assert tier_bonus_value(6, table) == 900.0
    # 越界 / 非法 tier / 缺省 → 0（tier 7 不在表内）
    for bad in (0, 7, 99, -1, None, "x", 3.7):
        value = tier_bonus_value(bad, table)
        assert isinstance(value, float)
    assert tier_bonus_value(7, table) == 0.0
    assert tier_bonus_value(0, table) == 0.0
    with pytest.raises(ValueError):
        parse_tier_bonus("0,oops,3")


# ── 2. Φ 数值 ───────────────────────────────────────────────────────────
def test_potential_manual_value():
    player = {"tier": 4, "board": [{"atk": 3, "hp": 2}, {"atk": 4, "hp": 5}]}
    # Σ(atk+hp)=14；tier4 bonus=150；Φ = 1.0*14 + 0.5*150 = 89
    phi = potential_from_player(player, w_str=1.0, w_tier=0.5)
    assert phi == pytest.approx(89.0)
    assert potential_from_player_json(json.dumps(player), w_str=1.0,
                                      w_tier=0.5) == pytest.approx(89.0)
    # 空 board / 缺字段 / 非法 tier 都安全（tier4 之外 bonus 记 0）
    assert potential_from_player({"board": [], "tier": 7}) == 0.0
    assert potential_from_player({"tier": 4}) == pytest.approx(75.0)
    assert potential_from_player({}) == 0.0
    assert potential_from_player({"board": [{"atk": 2}, {"hp": 3}]}) == pytest.approx(5.0)
    assert potential_from_player(None) == 0.0
    assert potential_from_player_json("not-json") == 0.0
    # 权重为 0 → 0
    assert potential_from_player(player, w_str=0.0, w_tier=0.0) == 0.0


# ── 3. F 公式 ───────────────────────────────────────────────────────────
def test_shaping_reward_formula():
    assert shaping_reward(89.0, 100.0, 1e-3) == pytest.approx(
        1e-3 * (SHAPING_GAMMA * 100.0 - 89.0))
    assert shaping_reward(100.0, 50.0, 2e-4) == pytest.approx(
        2e-4 * (SHAPING_GAMMA * 50.0 - 100.0))
    assert shaping_reward(100.0, 200.0, 0.0) == 0.0
    # 变大 → 正奖励；变小 → 负奖励（同一个 Φ 量级下）
    assert shaping_reward(100.0, 1000.0, 1e-3) > 0.0
    assert shaping_reward(1000.0, 100.0, 1e-3) < 0.0


def test_reward_shaper_zero_coef_is_noop():
    cfg = CollectConfig(shaping_coef=0.0, shaping_w_str=3.0,
                        shaping_w_tier=9.0, shaping_tier_bonus="1,2,3")
    shaper = RewardShaper(cfg)
    assert shaper.enabled is False
    assert shaper.stats() == {}
    # 禁用时绝不读 game（传 None 也不会炸）
    assert shaper.potential(None, 0) == 0.0
    recs = [{"game_id": 0, "rank": 1}]
    assert shaper.attach(recs, 0, 0, 10.0, 20.0) is False
    assert "reward" not in recs[0]


# ── 4. 批构建：可选 reward 字段 ─────────────────────────────────────────
def test_batch_uses_record_reward_only_when_present():
    base = _synthetic_records(rank=2)
    b0 = build_batch_from_records(base, step_penalty=0.1)
    util = float(utility_from_rank([2])[0])
    assert np.allclose(b0.rewards, np.array([-0.1, -0.1, util - 0.1], np.float32))
    packed0 = pack_records_arrays(base)
    assert "rewards" not in packed0
    b0b = build_batch_from_arrays(packed0, step_penalty=0.1)
    assert np.array_equal(b0.rewards, b0b.rewards)

    shaped = _synthetic_records(rank=2, rewards=(0.5, -0.2, 0.3))
    b1 = build_batch_from_records(shaped, step_penalty=0.1)
    expect = np.array([0.4, -0.3, util - 0.1 + 0.3], np.float32)
    assert np.allclose(b1.rewards, expect, atol=1e-6)
    packed1 = pack_records_arrays(shaped)
    assert "rewards" in packed1
    assert np.allclose(packed1["rewards"], [0.5, -0.2, 0.3])
    b1b = build_batch_from_arrays(packed1, step_penalty=0.1)
    assert np.array_equal(b1.rewards, b1b.rewards)
    assert b1.validate() == [] and b1b.validate() == []


# ── 5. 引擎路径：观测 Φ 与 player_json Φ 一致 ───────────────────────────
def _engine_game_with_board():
    E = pytest.importorskip("hsbg_engine")
    rng = np.random.default_rng(0)
    game = E.Game(seed=5)
    applied = False
    for _ in range(200):
        if game.is_over():
            break
        if game.needs_action(0):
            res = game.inject_board(0, [[824, 7, 9], [1641, 12, 3]], tier=5)
            if bool(res.get("applied")):
                applied = True
                break
        p = next((i for i in range(8) if game.needs_action(i)), None)
        if p is None:
            break
        mask = np.frombuffer(game.legal_mask(int(p)), dtype=bool)
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            break
        game.step(int(p), int(rng.choice(legal)))
    assert applied, "未能进入可注入战团的招募阶段"
    return game


def test_obs_potential_matches_player_json():
    game = _engine_game_with_board()
    phi_obs = potential(game, 0, w_str=1.0, w_tier=0.5)
    player = json.loads(game.player_json(0))
    phi_json = potential_from_player(player, w_str=1.0, w_tier=0.5)
    assert phi_obs == pytest.approx(phi_json)
    # 注入的 board = 7+9 + 12+3 = 31，tier5 bonus=400 → Φ = 31 + 200 = 231
    assert phi_obs == pytest.approx(231.0)
    # 直接给观测 bytes 也必须一致
    feats, _cards = game.observe(0)
    assert potential_from_obs(feats, w_str=1.0,
                              w_tier=0.5) == pytest.approx(231.0)
    assert potential_from_obs(np.frombuffer(feats, dtype=np.float32),
                              w_str=1.0, w_tier=0.5) == pytest.approx(231.0)


def test_potential_falls_back_without_observe():
    class _Mock:
        def player_json(self, seat):
            return json.dumps({"tier": 4, "board": [{"atk": 3, "hp": 2}]})

    assert potential(_Mock(), 0, w_str=1.0, w_tier=0.5) == pytest.approx(80.0)

    class _Broken:
        def observe(self, seat):
            raise RuntimeError("no obs")

        def player_json(self, seat):
            raise RuntimeError("no json")

    assert potential(_Broken(), 0) == 0.0


# ── 6. 采集接线：zero-coef 逐位一致 + 塑形方向 ─────────────────────────
def _lockstep_records(seed: int, games: int, **kwargs):
    torch_ok = pytest.importorskip("torch")
    pytest.importorskip("hsbg_engine")
    assert torch_ok
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.model import build_net
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep

    torch_ok.manual_seed(1234)      # 两次调用同权重，才能做逐位对比
    model = build_net(arch="tiny")
    model.eval()
    server = BatchLeafServer(model, device="cpu", batch_size=32, max_wait_ms=1.0)
    try:
        cfg = CollectConfig(games=games, seed=seed, opponent="bot",
                            behavior="net", fast_act=True, lockstep=True,
                            max_steps=8000, **kwargs)
        records, meta = collect_ppo_lockstep(
            model, cfg, eval_fn=BatchPPOEvaluator(server), device="cpu",
            seed=seed, games=games)
    finally:
        server.close()
    return records, meta


def test_zero_coef_bitwise_identical_and_reward_path():
    """coef=0（即使其它 shaping 参数非默认）必须与旧奖励路径逐位一致。"""
    games, seed = 2, 7
    base, meta0 = _lockstep_records(seed, games)
    other, meta1 = _lockstep_records(
        seed, games, shaping_coef=0.0, shaping_w_str=3.0,
        shaping_w_tier=2.0, shaping_tier_bonus="5,5,5,5,5,5,5")
    assert all("reward" not in r for r in base)
    assert all("reward" not in r for r in other)
    assert "shaping_coef" not in meta0 and "shaping_coef" not in meta1

    p0 = pack_records_arrays(base)
    p1 = pack_records_arrays(other)
    assert set(p0) == set(p1)
    assert "rewards" not in p0 and "rewards" not in p1
    for key in p0:
        assert np.array_equal(p0[key], p1[key]), key

    batch = build_batch_from_records(base, gamma=1.0, lam=0.995)
    # 旧奖励路径：每步 0（step_penalty=0），末步 = u(rank)
    for gid in np.unique(batch.game_ids):
        mask = batch.game_ids == gid
        idx = np.flatnonzero(mask)
        last = int(idx[-1])
        util = float(utility_from_rank([int(batch.ranks[last])])[0])
        assert batch.rewards[last] == pytest.approx(util)
        assert np.allclose(batch.rewards[idx[:-1]], 0.0)
    assert batch.validate() == []


def test_lockstep_shaping_wiring_and_direction():
    coef = 1e-3
    records, meta = _lockstep_records(2, 2, shaping_coef=coef)
    assert len(records) > 0
    assert all("reward" in r for r in records)
    assert meta["shaping_coef"] == pytest.approx(coef)
    assert meta["shaping_w_str"] == pytest.approx(1.0)
    assert meta["shaping_w_tier"] == pytest.approx(0.5)
    assert meta["shaping_calls"] == meta["shaping_decisions"] == len(records)
    assert meta["shaping_seconds"] > 0.0
    assert meta["shaping_overhead_pct"] >= 0.0
    assert meta["reward_shaping_mean"] == pytest.approx(
        float(np.mean([r["reward"] for r in records])), rel=1e-5)

    # 用 record 里的观测重算 Φ，逐条核对 F = λ(γΦ(s')−Φ(s))；局末 Φ=0。
    growth, shrink = [], []
    by_game = {}
    for r in records:
        by_game.setdefault(int(r["game_id"]), []).append(r)
    for gid, rs in by_game.items():
        phi = [potential_from_obs(r["features"]) for r in rs]
        for i, r in enumerate(rs):
            nxt = phi[i + 1] if i + 1 < len(rs) else 0.0
            expect = shaping_reward(phi[i], nxt, coef)
            assert float(r["reward"]) == pytest.approx(expect, abs=2e-6), (gid, i)
            if nxt > phi[i]:
                growth.append(float(r["reward"]))
            elif nxt < phi[i]:
                shrink.append(float(r["reward"]))
    assert growth and shrink, "两局 tiny 采集没有覆盖到战团变大/变小"
    assert float(np.mean(growth)) > float(np.mean(shrink))
    assert max(abs(x) for x in growth + shrink) > 1e-6


def test_serial_collect_shaping_end_to_end():
    """默认训练路径（collect_ppo_batch 串行）也要接线并产出 meta。"""
    torch = pytest.importorskip("torch")
    pytest.importorskip("hsbg_engine")
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import collect_ppo_batch

    torch.manual_seed(99)
    model = build_net(arch="tiny")
    model.eval()
    server = BatchLeafServer(model, device="cpu", batch_size=32, max_wait_ms=1.0)
    try:
        cfg = CollectConfig(games=2, seed=1, opponent="bot", behavior="net",
                            fast_act=True, max_steps=8000, shaping_coef=1e-3)
        batch, meta = collect_ppo_batch(model, cfg, eval_fn=BatchPPOEvaluator(server),
                                        device="cpu", seed=1)
    finally:
        server.close()
    c = meta["collect"]
    assert c["shaping_coef"] == pytest.approx(1e-3)
    assert c["shaping_calls"] == c["shaping_decisions"] == int(c["decisions"])
    assert c["reward_shaping_abs_max"] > 0.0
    assert c["shaping_overhead_pct"] >= 0.0
    assert batch.validate() == []
    # 末步 = u(rank) + F_last；非末步只含 F（step_penalty=0）
    for gid in np.unique(batch.game_ids):
        idx = np.flatnonzero(batch.game_ids == gid)
        util = float(utility_from_rank([int(batch.ranks[int(idx[-1])])])[0])
        assert abs(float(batch.rewards[int(idx[-1])]) - util) < 0.5
    assert int((batch.rewards != 0).sum()) > 2


def test_aggregate_shaping():
    assert aggregate_shaping([]) == {}
    metas = [
        {"shaping_coef": 1e-3, "shaping_gamma": SHAPING_GAMMA,
         "shaping_w_str": 1.0, "shaping_w_tier": 0.5,
         "shaping_tier_bonus": "0,0,20,60,150,400,900",
         "shaping_calls": 10, "shaping_decisions": 10,
         "shaping_seconds": 0.01, "reward_shaping_sum": 0.5,
         "reward_shaping_abs_sum": 2.5, "reward_shaping_abs_max": 0.8},
        {"shaping_coef": 1e-3, "shaping_gamma": SHAPING_GAMMA,
         "shaping_w_str": 1.0, "shaping_w_tier": 0.5,
         "shaping_tier_bonus": "0,0,20,60,150,400,900",
         "shaping_calls": 5, "shaping_decisions": 5,
         "shaping_seconds": 0.01, "reward_shaping_sum": -0.5,
         "reward_shaping_abs_sum": 1.5, "reward_shaping_abs_max": 0.4},
    ]
    agg = aggregate_shaping(metas, elapsed_s=2.0)
    assert agg["shaping_calls"] == 15
    assert agg["shaping_decisions"] == 15
    assert agg["shaping_seconds"] == pytest.approx(0.02)
    assert agg["reward_shaping_sum"] == pytest.approx(0.0)
    assert agg["reward_shaping_mean"] == pytest.approx(0.0)
    assert agg["reward_shaping_abs_mean"] == pytest.approx(4.0 / 15.0)
    assert agg["reward_shaping_abs_max"] == pytest.approx(0.8)
    assert agg["shaping_overhead_pct"] == pytest.approx(1.0)


# ── 7. 开销微基准（可选；只做宽松上界，避免 CI 抖动）────────────────────
def test_potential_microbench(capsys):
    game = _engine_game_with_board()
    n = 200
    import time
    t0 = time.perf_counter()
    for _ in range(n):
        potential(game, 0)
    per_call_us = (time.perf_counter() - t0) / n * 1e6
    with capsys.disabled():
        print(f"[bench] potential(observe) = {per_call_us:.2f} us/call")
    assert per_call_us < 2000.0     # 宽松上界：真实约 2–4 µs


# ── 8. 训练入口参数 ─────────────────────────────────────────────────────
def test_train_entry_exposes_shaping_flags():
    proc = subprocess.run([sys.executable,
                           os.path.join(ROOT, "scripts", "train_entity_sync.py"),
                           "--help"], cwd=ROOT, capture_output=True, text=True,
                          timeout=300)
    assert proc.returncode == 0, proc.stderr
    for flag in ("--shaping-coef", "--shaping-w-str", "--shaping-w-tier",
                 "--shaping-tier-bonus"):
        assert flag in proc.stdout, flag
