"""等级进度奖励（tier-target reward）单测。

覆盖（见 ``docs/TIER_TARGET.md``）：

1. 目标表解析 / 格式化 / 非法输入 fail-fast；
2. 未达标扣分（每回合只扣一次）；
3. 首次达标一次性奖励（不重复发）；
4. 越级（tier 远高于目标）仍按档位发放，越过目标后不再发；
5. ``tier_target_coef=0`` 时状态机 / record / packed 与旧路径逐位等价
   （含采集接线：同 seed lockstep 两次逐位一致）；
6. 多局状态隔离（claimed/evaluated 不共享、flush 校验 game_id 不串局）；
7. tier 读取（观测快路径 / player_json 兜底 / 坏状态按 0）；
8. 与势函数塑形叠加时 ``record["reward"] = F + tier_delta``（不互相覆盖）；
9. 聚合 meta 与训练入口 4 个 flag。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.ppo import CollectConfig, build_batch_from_records, pack_records_arrays
from hsbg.az.train.tier_target import (DEFAULT_TIER_BONUS, DEFAULT_TIER_PENALTY,
                                       DEFAULT_TIER_TARGET_TABLE,
                                       DEFAULT_TIER_TARGET_TABLE_SPEC,
                                       TierTargetTracker, aggregate_tier_target,
                                       format_tier_target_table,
                                       parse_tier_target_table, tier_from_obs,
                                       tier_from_player_json, tier_of,
                                       tier_target_for_turn)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _onehot_mask(action: int) -> np.ndarray:
    m = np.zeros(N_ACTIONS, dtype=np.float32)
    m[int(action)] = 1.0
    return m


# ── 1. 目标表 ────────────────────────────────────────────────────────────
def test_parse_table_default_and_custom():
    assert parse_tier_target_table(None) == DEFAULT_TIER_TARGET_TABLE
    assert parse_tier_target_table("") == DEFAULT_TIER_TARGET_TABLE
    assert parse_tier_target_table("   ") == DEFAULT_TIER_TARGET_TABLE
    assert parse_tier_target_table(DEFAULT_TIER_TARGET_TABLE_SPEC) == \
        DEFAULT_TIER_TARGET_TABLE
    assert parse_tier_target_table("7:4,9:5,12:6") == {7: 4, 9: 5, 12: 6}
    # 分号 / 空格 / dict / [(turn, tier)] 都接受
    assert parse_tier_target_table("7:4; 9:5, 12:6") == {7: 4, 9: 5, 12: 6}
    assert parse_tier_target_table({"7": "4"}) == {7: 4}
    assert parse_tier_target_table([(7, 4), (9, 5)]) == {7: 4, 9: 5}
    # 默认目标曲线本身：t9 要 5 级、t12 要 6 级
    table = parse_tier_target_table(None)
    assert tier_target_for_turn(9, table) == 5
    assert tier_target_for_turn(12, table) == 6
    assert tier_target_for_turn(8, table) is None
    assert tier_target_for_turn("x", table) is None


def test_parse_table_invalid_fail_fast():
    for bad in ("7-4", "7:", ":4", "0:4", "7:0", "7:8", "x:4", "7:y",
                "7:4,7:5", "7:4,9", "a:b"):
        with pytest.raises(ValueError):
            parse_tier_target_table(bad)


def test_format_table():
    assert format_tier_target_table({12: 6, 7: 4, 9: 5}) == "7:4,9:5,12:6"
    assert format_tier_target_table([(9, 5), (7, 4)]) == "7:4,9:5"


# ── 2. 未达标扣分 ────────────────────────────────────────────────────────
def test_miss_applies_penalty_once_per_turn():
    t = TierTargetTracker(coef=1.0, penalty=0.02, bonus=0.15, table="7:4,9:5,12:6")
    assert t.enabled
    # turn 7 只有 3 级：扣一次
    assert t.check(7, 3) == pytest.approx(-0.02)
    assert t.stats()["tier_misses"] == 1
    assert t.stats()["tier_hits"] == 0
    assert t.stats()["tier_checks"] == 1
    # 同一 turn 再检查：不重复扣
    assert t.check(7, 3) == 0.0
    assert t.stats()["tier_checks"] == 1
    # 非目标 turn：完全不动
    assert t.check(8, 1) == 0.0
    assert t.check(10, 1) == 0.0
    assert t.stats()["tier_checks"] == 1
    # coef 缩放
    t2 = TierTargetTracker(coef=2.0, penalty=0.02, bonus=0.15, table="7:4")
    assert t2.check(7, 1) == pytest.approx(-0.04)


# ── 3. 达标一次性奖励（不重复）──────────────────────────────────────────
def test_hit_bonus_only_once():
    t = TierTargetTracker(coef=1.0, penalty=0.02, bonus=0.15, table="7:4,9:5,12:6")
    assert t.check(7, 4) == pytest.approx(DEFAULT_TIER_BONUS)
    assert t.stats()["tier_hits"] == 1
    assert t.stats()["tier_bonus_sum"] == pytest.approx(0.15)
    # 同 turn 重复检查 / 重复检查已领取档位：不再发
    assert t.check(7, 5) == 0.0
    assert t.stats()["tier_hits"] == 1
    assert t.check(7, 6) == 0.0
    assert t.stats()["tier_hits"] == 1
    # 每档只发一次：t9 是新档位，可以再发
    assert t.check(9, 5) == pytest.approx(0.15)
    assert t.stats()["tier_hits"] == 2
    # 越过目标后（t13+ 无目标）不再发
    assert t.check(13, 6) == 0.0
    assert t.check(15, 6) == 0.0
    assert t.stats()["tier_hits"] == 2


# ── 4. 越级 ──────────────────────────────────────────────────────────────
def test_overshoot_still_claims_each_target_once():
    t = TierTargetTracker(coef=1.0, table="7:4,9:5,12:6")
    # t7 直接 6 级：越过 4 级目标，仍发 t7 档奖励
    assert t.check(7, 6) == pytest.approx(0.15)
    assert t.check(9, 6) == pytest.approx(0.15)
    assert t.check(12, 6) == pytest.approx(0.15)
    assert t.stats()["tier_hits"] == 3
    assert t.stats()["tier_misses"] == 0
    assert t.stats()["tier_bonus_sum"] == pytest.approx(0.45)
    # 越过目标后不再重复
    assert t.check(12, 7) == 0.0
    assert t.stats()["tier_hits"] == 3


# ── 5. coef=0 逐位等价（纯状态机 / record）──────────────────────────────
def test_zero_coef_is_noop_and_bitwise_identical():
    # 即使 penalty/bonus/table 是非法值，coef=0 也不解析、不报错（旧路径安全）
    t = TierTargetTracker(coef=0.0, penalty=-1.0, bonus=-1.0, table="bad-table")
    assert not t.enabled
    assert t.check(7, 1) == 0.0
    assert t.observe(object(), 0) == 0.0
    assert t.check_obs(7, np.zeros(OBS_FLOATS, dtype=np.float32)) == 0.0
    assert t.queue(0, 0, 0.15) is False
    records = [{"game_id": 0, "reward": 0.5}, {"game_id": 1}]
    assert t.flush(records) == 0
    assert records == [{"game_id": 0, "reward": 0.5}, {"game_id": 1}]
    assert t.stats() == {}
    assert aggregate_tier_target([t.stats()]) == {}
    # CollectConfig 默认必须关闭
    cfg = CollectConfig()
    assert cfg.tier_target_coef == 0.0
    assert cfg.tier_penalty == DEFAULT_TIER_PENALTY
    assert cfg.tier_bonus == DEFAULT_TIER_BONUS
    assert cfg.tier_target_table == DEFAULT_TIER_TARGET_TABLE_SPEC


def test_queue_flush_adds_to_existing_reward():
    t = TierTargetTracker(coef=1.0, table="7:4")
    delta = t.check(7, 3)
    assert t.queue(0, 5, delta) is True
    records = [{"game_id": 5, "reward": 0.3}]
    assert t.flush(records) == 1
    # 与势函数 F=0.3 叠加，而不是覆盖
    assert records[0]["reward"] == pytest.approx(0.3 - 0.02)
    # 已应用的 pending 清空：重复 flush 不重复加
    assert t.flush(records) == 0
    assert records[0]["reward"] == pytest.approx(0.28)
    assert t.stats()["tier_target_applied"] == 1


# ── 6. 多局状态隔离 ─────────────────────────────────────────────────────
def test_multigame_state_isolated():
    cfg = CollectConfig(tier_target_coef=1.0, tier_target_table="7:4,9:5,12:6")
    a = TierTargetTracker(cfg)
    b = TierTargetTracker(cfg)
    # A 局 t7 达标；B 局 t7 未达标（不共享 claimed），A 的领取不影响 B 的扣分
    assert a.check(7, 5) == pytest.approx(0.15)
    assert b.check(7, 3) == pytest.approx(-0.02)
    assert b.stats()["tier_misses"] == 1
    # 各自独立推进
    assert a.check(9, 5) == pytest.approx(0.15)
    assert b.check(9, 5) == pytest.approx(0.15)
    assert a.stats()["tier_hits"] == 2
    assert b.stats()["tier_hits"] == 1
    assert b.stats()["tier_misses"] == 1
    # flush 校验 game_id：A 的待应用增量不能写到 B 的记录上
    a.queue(0, 0, 0.15)
    a.queue(1, 1, 0.15)
    records = [{"game_id": 0}, {"game_id": 1}]
    assert a.flush(records) == 2
    b.queue(1, 0, 0.15)      # index 1 属于 game 1，game_id 对不上 → dropped
    assert b.flush(records) == 0
    assert b.stats()["tier_target_dropped"] == 1
    assert records[1]["reward"] == pytest.approx(0.15)   # 只有 A 的增量


def test_aggregate_meta():
    assert aggregate_tier_target([]) == {}
    assert aggregate_tier_target([{"game_id": 0}]) == {}
    rows = [
        {"tier_target_coef": 1.0, "tier_penalty": 0.02, "tier_bonus": 0.15,
         "tier_target_table": "7:4,9:5,12:6", "tier_checks": 3, "tier_hits": 2,
         "tier_misses": 1, "tier_bonus_sum": 0.30, "tier_penalty_sum": 0.02,
         "tier_target_reward_sum": 0.28, "tier_target_applied": 3,
         "tier_target_dropped": 0},
        {"tier_target_coef": 1.0, "tier_penalty": 0.02, "tier_bonus": 0.15,
         "tier_target_table": "7:4,9:5,12:6", "tier_checks": 2, "tier_hits": 0,
         "tier_misses": 2, "tier_bonus_sum": 0.0, "tier_penalty_sum": 0.04,
         "tier_target_reward_sum": -0.04, "tier_target_applied": 2,
         "tier_target_dropped": 0},
    ]
    agg = aggregate_tier_target(rows)
    assert agg["tier_hits"] == 2 and agg["tier_misses"] == 3
    assert agg["tier_checks"] == 5
    assert agg["tier_bonus_sum"] == pytest.approx(0.30)
    assert agg["tier_target_reward_sum"] == pytest.approx(0.24)
    assert agg["tier_hit_rate"] == pytest.approx(0.4)
    assert agg["tier_target_table"] == "7:4,9:5,12:6"


# ── 7. tier 读取 ────────────────────────────────────────────────────────
def _obs_with_tier(tier: int) -> np.ndarray:
    from hsbg.env.obs_std import GLOBAL_FIELD_INDEX, GLOBAL_FIELD_SCALE
    f = np.zeros(OBS_FLOATS, dtype=np.float32)
    f[int(GLOBAL_FIELD_INDEX["tier"])] = float(tier) / float(
        GLOBAL_FIELD_SCALE["tier"])
    return f


def test_tier_reading_paths():
    assert tier_from_obs(_obs_with_tier(5)) == 5
    assert tier_from_obs(_obs_with_tier(6).tobytes()) == 6
    assert tier_from_player_json(json.dumps({"tier": 4})) == 4
    assert tier_from_player_json("not-json") == 0
    assert tier_from_player_json(json.dumps({"tier": None})) == 0

    class _Game:
        turn = 3

        def observe(self, seat):
            return (_obs_with_tier(6), np.zeros(OBS_CARDS, dtype=np.int32))

    assert tier_of(_Game(), 0) == 6

    class _JsonOnly:
        turn = 3

        def observe(self, seat):
            raise RuntimeError("no obs")

        def player_json(self, seat):
            return json.dumps({"tier": 5})

    assert tier_of(_JsonOnly(), 0) == 5

    class _Broken:
        turn = 3

        def observe(self, seat):
            raise RuntimeError("no obs")

        def player_json(self, seat):
            raise RuntimeError("no json")

    assert tier_of(_Broken(), 0) == 0
    # observe 只在**新** turn 读一次；同一 turn 再调用不读状态（用计数验证）
    calls = []

    class _Counting:
        turn = 7

        def observe(self, seat):
            calls.append(seat)
            return (_obs_with_tier(3), None)

    t = TierTargetTracker(coef=1.0, table="7:4")
    assert t.observe(_Counting(), 0) == pytest.approx(-0.02)
    assert t.observe(_Counting(), 0) == 0.0
    assert len(calls) == 1


# ── 8. 采集接线（engine 可用时才跑）─────────────────────────────────────
def _lockstep(model, seed: int, games: int, **kwargs):
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep

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


@pytest.fixture(scope="module")
def tiny_model():
    torch = pytest.importorskip("torch")
    pytest.importorskip("hsbg_engine")
    from hsbg.az.train.model import build_net
    torch.manual_seed(1234)
    model = build_net(arch="tiny")
    model.eval()
    return model


def test_lockstep_zero_coef_bitwise_identical(tiny_model):
    base, meta0 = _lockstep(tiny_model, 7, 2)
    other, meta1 = _lockstep(
        tiny_model, 7, 2, tier_target_coef=0.0, tier_penalty=9.0, tier_bonus=9.0,
        tier_target_table="1:7,2:7,3:7")
    assert all("reward" not in r for r in base)
    assert all("reward" not in r for r in other)
    for key in ("tier_target_coef", "tier_hits", "tier_misses", "tier_bonus_sum"):
        assert key not in meta0 and key not in meta1
    p0, p1 = pack_records_arrays(base), pack_records_arrays(other)
    assert set(p0) == set(p1)
    for key in p0:
        assert np.array_equal(p0[key], p1[key]), key
    build_batch_from_records(base)   # 旧奖励路径可正常构建


def test_lockstep_miss_and_hit_wiring(tiny_model):
    # 目标 tier=7（不可达）：每个新回合都 miss；t1 第一条 decision 拿到 -0.02
    recs, meta = _lockstep(tiny_model, 3, 2, tier_target_coef=1.0,
                           tier_penalty=0.02, tier_bonus=0.15,
                           tier_target_table="1:7")
    assert meta["tier_target_coef"] == pytest.approx(1.0)
    assert meta["tier_target_table"] == "1:7"
    assert meta["tier_hits"] == 0
    assert meta["tier_checks"] == meta["tier_misses"] > 0
    assert meta["tier_bonus_sum"] == 0.0
    # 注意：引擎 turn 从 0 开始，turn 0 没有目标；惩罚落在 **turn 1 的第一条决策**
    first = {}
    for r in recs:
        if int(r["turn"]) == 1:
            first.setdefault(int(r["game_id"]), r)
    assert len(first) == 2
    for r in first.values():
        assert float(r["reward"]) == pytest.approx(-0.02, abs=1e-6)
    turn0 = [r for r in recs if int(r["turn"]) == 0]
    assert turn0 and all("reward" not in r for r in turn0)

    # 目标 tier=1（一开始就达标）：每个目标档一次性 +0.15
    recs2, meta2 = _lockstep(tiny_model, 3, 2, tier_target_coef=1.0,
                             tier_target_table="1:1")
    assert meta2["tier_hits"] == meta2["tier_checks"] == 2
    assert meta2["tier_misses"] == 0
    assert meta2["tier_bonus_sum"] == pytest.approx(0.30)
    first2 = {}
    for r in recs2:
        if int(r["turn"]) == 1:
            first2.setdefault(int(r["game_id"]), r)
    assert len(first2) == 2
    for r in first2.values():
        assert float(r["reward"]) == pytest.approx(0.15, abs=1e-6)


def test_lockstep_with_potential_shaping_stacks(tiny_model):
    """tier-target 增量与势函数 F 叠加（不是覆盖），顺序在 Φ 回填之后。"""
    from hsbg.az.train.reward_shaping import potential_from_obs, shaping_reward
    coef = 1e-3
    recs, meta = _lockstep(tiny_model, 5, 2, shaping_coef=coef,
                           tier_target_coef=1.0, tier_target_table="1:7")
    assert meta["shaping_coef"] == pytest.approx(coef)
    by_game = {}
    for r in recs:
        by_game.setdefault(int(r["game_id"]), []).append(r)
    for gid, rs in by_game.items():
        phi = [potential_from_obs(r["features"]) for r in rs]
        consumed = False
        for i, r in enumerate(rs):
            nxt = phi[i + 1] if i + 1 < len(rs) else 0.0
            expect = shaping_reward(phi[i], nxt, coef)
            if int(r["turn"]) == 1 and not consumed:
                expect += -0.02           # t1 目标 7，未达标（该回合第一条决策）
                consumed = True
            assert float(r["reward"]) == pytest.approx(expect, abs=2e-6), (gid, i)
        assert consumed


def test_serial_collect_wiring(tiny_model):
    """默认训练路径（collect_ppo_batch 串行）也要接线并产出 meta。"""
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.ppo import collect_ppo_batch

    server = BatchLeafServer(tiny_model, device="cpu", batch_size=32, max_wait_ms=1.0)
    try:
        cfg = CollectConfig(games=1, seed=1, opponent="bot", behavior="net",
                            fast_act=True, max_steps=8000, tier_target_coef=1.0,
                            tier_target_table="1:7")
        _batch, meta = collect_ppo_batch(
            tiny_model, cfg, eval_fn=BatchPPOEvaluator(server), device="cpu", seed=1)
    finally:
        server.close()
    c = meta["collect"]
    assert c["tier_target_coef"] == pytest.approx(1.0)
    assert c["tier_checks"] == c["tier_misses"] > 0
    assert c["tier_hits"] == 0


# ── 9. 训练入口参数 ─────────────────────────────────────────────────────
def test_train_entry_exposes_tier_target_flags():
    proc = subprocess.run([sys.executable,
                           os.path.join(ROOT, "scripts", "train_entity_sync.py"),
                           "--help"], cwd=ROOT, capture_output=True, text=True,
                          timeout=300)
    assert proc.returncode == 0, proc.stderr
    for flag in ("--tier-target-coef", "--tier-penalty", "--tier-bonus",
                 "--tier-target-table"):
        assert flag in proc.stdout, flag
