"""快速注入路径的**逐位等价**测试（``human_obs_full.inject_quasi_state(fast=True)``）。

契约：``fast=True`` 与 ``fast=False`` 对同一 ``(game 状态, seat, payload, fidelity)``
必须产生**完全相同**的引擎状态（``Game.state_json()`` 逐字节相等），因此同 seed 下的
动作序列、注入计数口径与 history 字段语义都不变。

覆盖：
1. 真实准完整库的多行 payload × hand/full 两档；
2. 无 orjson 时（强制标准库后端）同样逐位等价；
3. player overlay 分支（``player`` 段 -> 第二次写回走 load/dump）；
4. 拒绝路径（已结束回合的座位）返回同样的 ``applied=False`` 且不改状态；
5. 连续多次注入（视图缓存复用）后状态仍逐步一致。
"""

from __future__ import annotations

import json
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

eng = pytest.importorskip("hsbg_engine")

from hsbg.az.train import human_obs_full as HOF  # noqa: E402
from hsbg.az.train.human_board_pool import load_pool  # noqa: E402

LIB = os.path.join(ROOT, "data", "real_library", "library_real_quasi_full.jsonl")


def _advance(g, turn: int) -> None:
    guard = 0
    while not g.is_over() and int(g.turn) < int(turn) and guard < 200000:
        acted = False
        for p in range(int(g.num_players)):
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
                guard += 1
                break
        if not acted:
            break


@pytest.fixture(scope="module")
def pool():
    if not os.path.isfile(LIB):
        pytest.skip("缺少准完整库")
    p = load_pool(LIB, sample="auto")
    if p is None:
        pytest.skip("准完整库为空")
    return p


def _payload_at(pool, turn: int):
    return pool.sample_payload(int(turn), rng=random.Random(0))


def test_fast_inject_state_identical(pool):
    """hand/full × 多个 turn：fast 与 slow 的 state_json 必须逐字节相同。"""
    checked = 0
    for fid in ("hand", "full"):
        for turn in (2, 5, 8, 12):
            t = min(pool.turns(), key=lambda x: abs(int(x) - int(turn)))
            pay = _payload_at(pool, t)
            if pay is None or not pay.get("has_detail"):
                continue
            for seat in (1, 2, 6):
                base = eng.Game(seed=101)
                _advance(base, max(2, int(t)))
                a = base.copy()
                b = base.copy()
                ra = HOF.inject_quasi_state(a, seat, pay, fid, reset_ended=True)
                rb = HOF.inject_quasi_state(b, seat, pay, fid, reset_ended=True,
                                            fast=True)
                assert ra["applied"] == rb["applied"], (fid, t, seat, ra, rb)
                if not ra["applied"]:
                    assert ra["reason"] == rb["reason"], (ra, rb)
                assert ra["unavailable_fields"] == rb["unavailable_fields"]
                assert ra["hand_applied"] == rb["hand_applied"]
                assert ra["counters_applied"] == rb["counters_applied"]
                assert a.state_json() == b.state_json(), (
                    f"fast/slow 状态不一致: fidelity={fid} turn={t} seat={seat}")
                checked += 1
    assert checked >= 8, checked


def test_fast_inject_stdlib_backend_identical(pool, monkeypatch):
    """强制退回标准库 JSON 后仍逐位等价（证明 orjson 不影响语义）。"""
    monkeypatch.setattr(HOF, "_ORJSON", None)
    pay = _payload_at(pool, min(pool.turns(), key=lambda x: abs(int(x) - 7)))
    base = eng.Game(seed=202)
    _advance(base, 7)
    a = base.copy()
    b = base.copy()
    ra = HOF.inject_quasi_state(a, 3, pay, "full", reset_ended=True)
    rb = HOF.inject_quasi_state(b, 3, pay, "full", reset_ended=True, fast=True)
    assert ra["applied"] and rb["applied"]
    assert a.state_json() == b.state_json()


def test_fast_inject_player_overlay_identical(pool):
    """payload 带 ``player`` 段（overlay 分支）时逐位等价。"""
    pay = dict(_payload_at(pool, min(pool.turns(), key=lambda x: abs(int(x) - 9))))
    base = eng.Game(seed=303)
    _advance(base, 9)
    pj = json.loads(base.player_json(4))
    # 用目标座位**当前**玩家级字段做 overlay（值相同 -> 两边写回同一内容）
    pay["player"] = {k: pj[k] for k in ("trinkets", "quests", "rewards", "secrets",
                                        "levels", "effects", "counters", "stats",
                                        "tier7") if k in pj}
    a = base.copy()
    b = base.copy()
    ra = HOF.inject_quasi_state(a, 4, pay, "full", reset_ended=True,
                                player_overlay="all")
    rb = HOF.inject_quasi_state(b, 4, pay, "full", reset_ended=True,
                                player_overlay="all", fast=True)
    assert ra["applied"] == rb["applied"], (ra, rb)
    assert a.state_json() == b.state_json()


def test_fast_inject_rejection_identical():
    """拒绝路径：已结束回合的座位 -> 两边都不改状态、reason 相同。"""
    base = eng.Game(seed=404)
    # 先让 8 个座位各选英雄进入 turn1 recruit，再把座位 0 EndTurn
    for _ in range(16):
        p = next((i for i in range(int(base.num_players)) if base.needs_action(i)), None)
        if p is None:
            break
        base.bot_play(int(p))
    base.step(0, 0)          # 座位 0 EndTurn
    assert not base.needs_action(0)
    pay = {
        "turn": 1, "board": [{"card": 824, "atk": 1, "hp": 1, "golden": False,
                              "kw": 0, "bonus_kw": 0, "shield_max": 1}],
        "board_flat": [[824, 1, 1]], "hand": [], "hand_available": True,
        "tier": 1, "gold": None, "availability": {}, "has_detail": True,
    }
    a = base.copy()
    b = base.copy()
    ra = HOF.inject_quasi_state(a, 0, pay, "full", reset_ended=True)
    rb = HOF.inject_quasi_state(b, 0, pay, "full", reset_ended=True, fast=True)
    assert ra["applied"] is False and rb["applied"] is False
    assert ra["reason"] == rb["reason"]
    assert a.state_json() == b.state_json()


def test_fast_inject_repeated_uses_view_cache(pool):
    """连续注入（命中视图缓存）不改变状态，且计数与 slow 一致。"""
    pay = _payload_at(pool, min(pool.turns(), key=lambda x: abs(int(x) - 10)))
    a = eng.Game(seed=505)
    _advance(a, 10)
    b = a.copy()
    HOF.FAST_STATS["view_hits"] = 0
    HOF.FAST_STATS["view_builds"] = 0
    for i in range(6):
        ra = HOF.inject_quasi_state(a, 5, pay, "full", reset_ended=True)
        rb = HOF.inject_quasi_state(b, 5, pay, "full", reset_ended=True, fast=True)
        assert ra["applied"] == rb["applied"]
        assert a.state_json() == b.state_json(), f"第 {i} 次注入后不一致"
        # 每次注入后推进一点，模拟训练循环（让下一次注入仍有意义）
        for p in range(int(a.num_players)):
            if a.needs_action(p):
                a.bot_play(p)
                b.bot_play(p)
                break
    assert HOF.FAST_STATS["view_builds"] == 1, HOF.FAST_STATS
    assert HOF.FAST_STATS["view_hits"] >= 5, HOF.FAST_STATS


def test_fast_inject_board_fidelity_untouched():
    """fidelity=board 时 fast 参数不改变行为（仍走 inject_board）。"""
    pay = {
        "turn": 1, "board": [{"card": 824, "atk": 2, "hp": 3, "golden": False,
                              "kw": 0, "bonus_kw": 0, "shield_max": 1}],
        "board_flat": [[824, 2, 3]], "hand": [], "hand_available": True,
        "tier": 2, "gold": None, "availability": {}, "has_detail": True,
    }
    a = eng.Game(seed=606)
    b = eng.Game(seed=606)
    ra = HOF.inject_quasi_state(a, 2, pay, "board")
    rb = HOF.inject_quasi_state(b, 2, pay, "board", fast=True)
    assert ra == rb
    assert a.state_json() == b.state_json()
