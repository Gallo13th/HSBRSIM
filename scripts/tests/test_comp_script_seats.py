"""脚本席（comp script seats）接入训练的单元测试（CPU，无训练、无 checkpoint）。

覆盖：
1. 真实引擎上 seat 1/2 连续 30 次 decide，动作全部合法（illegal==0）；
2. 两 seat 使用不同阵容、CompPolicy 状态隔离（turn/core_seen 不串）；
3. 同 seed 两实例动作序列逐位相同；reset() 后可从同一起点重放；
4. resolve_comp_keys：comp:auto 的 n 席 → n 个不同 key（稳定/可复现），显式 key 解析与非法报错。
"""

from __future__ import annotations

import numpy as np
import pytest

E = pytest.importorskip("hsbg_engine")
from hsbg.az import env_api as EA  # noqa: E402

from hsbg.az.train.comp_offline_policy import (  # noqa: E402
    CompOpponentPolicy,
    comp_script_keys,
    resolve_comp_keys,
)

KEYS = comp_script_keys()
assert len(KEYS) >= 2, "comp_scripts 至少需要 2 套阵容才能测双席位"


def _new_game(seed: int):
    g = E.Game(int(seed))
    EA.finish_hero_select(g)
    return g


def _first_legal(g, seat: int) -> int:
    return int(np.flatnonzero(np.frombuffer(
        g.legal_mask(seat), dtype=np.uint8).astype(bool))[0])


def _drive(pol: CompOpponentPolicy, seed: int, n: int = 30,
           seats=(1, 2), record: list | None = None) -> list:
    """让 seats 里的席位各决策，其余座位 bot；返回 [(seat, action), ...]。"""
    g = _new_game(seed)
    out: list = []
    while len(out) < n and not g.is_over():
        acted = False
        for q in range(8):
            if len(out) >= n or g.is_over():
                break
            if not g.needs_action(q):
                continue
            acted = True
            if q in seats:
                d = pol.decide(g, q)
                mask = np.frombuffer(g.legal_mask(q), dtype=np.uint8).astype(bool)
                assert 0 <= int(d.action) < 245 and bool(mask[int(d.action)]), (
                    f"seat {q} 非法动作 {d.action}")
                g.step(q, int(d.action))
                out.append((q, int(d.action)))
            else:
                g.bot_play(q)
        if not acted:
            break
    return out


@pytest.mark.parametrize("hybrid", [True, False])
def test_decide_30_actions_all_legal(hybrid: bool) -> None:
    pol = CompOpponentPolicy(KEYS[:2], seed=27401, hybrid=hybrid)
    seq = _drive(pol, seed=880101, n=30)
    assert len(seq) == 30, f"只拿到 {len(seq)} 个脚本席决策"
    assert pol.stats["decisions"] == 30
    assert pol.stats["illegal"] == 0, pol.stats
    # 两个席位都真的上过场
    assert {s for s, _ in seq} == {1, 2}
    if hybrid:
        # hybrid 语义：每个决策要么是脚本接管、要么交给 bot 兜底，不应出现脚本异常
        assert pol.stats["comp_actions"] + pol.stats["bot_fallback"] == 30
        assert pol.stats["errors"] == 0, pol.stats


def test_two_seats_have_distinct_comps_and_isolated_state() -> None:
    keys = KEYS[:2]
    assert keys[0] != keys[1]
    pol = CompOpponentPolicy(keys, seed=27401)
    assert [p.spec.key for p in pol.policies] == keys
    assert pol.policies[0] is not pol.policies[1]

    g = _new_game(seed=880202)
    # 只在 seat 1 上跑几次决策：seat 2 的 CompPolicy 必须完全没被触碰
    for _ in range(3):
        while not g.needs_action(1) and not g.is_over():
            q = next(p for p in range(8) if g.needs_action(p))
            g.bot_play(q)
        if g.is_over():
            break
        d = pol.decide(g, 1)
        g.step(1, int(d.action))
    assert pol.policies[0].turn >= 0
    assert pol.policies[1].turn == -1
    assert pol.policies[1].core_seen == {}
    assert pol.policies[1].refreshes == 0

    # seat 2 第一次决策后才开始有自己的状态
    while not g.needs_action(2) and not g.is_over():
        q = next(p for p in range(8) if g.needs_action(p))
        g.bot_play(q)
    if not g.is_over():
        d2 = pol.decide(g, 2)
        g.step(2, int(d2.action))
        assert pol.policies[1].turn >= 0
        assert pol.policies[0].turn >= 0


def test_same_seed_is_deterministic_and_reset_replays() -> None:
    p1 = CompOpponentPolicy(KEYS[:2], seed=27401)
    p2 = CompOpponentPolicy(KEYS[:2], seed=27401)
    seq1 = _drive(p1, seed=880303, n=24)
    seq2 = _drive(p2, seed=880303, n=24)
    assert seq1 == seq2

    # reset 后从同一局面重放，序列必须一致（CompPolicy.reset 复位）
    p1.reset()
    seq3 = _drive(p1, seed=880303, n=24)
    assert seq3 == seq1


def test_resolve_auto_rotates_and_is_stable() -> None:
    a = resolve_comp_keys("auto", 2, seed=27401)
    b = resolve_comp_keys("auto", 2, seed=27401)
    assert a == b, "同 seed 的 auto 选套必须稳定"
    assert len(a) == 2 and len(set(a)) == 2, a
    assert all(k in KEYS for k in a)
    # 不同 seed 的轮转偏移不同（keys 数 > 2 时）
    if len(KEYS) > 2:
        c = resolve_comp_keys("auto", 2, seed=27402)
        assert c != a


def test_resolve_explicit_and_invalid() -> None:
    picked = resolve_comp_keys(f"{KEYS[0]},{KEYS[1]}", 2, seed=1)
    assert picked == [KEYS[0], KEYS[1]]
    # 只给一套时循环填满座位
    one = resolve_comp_keys(KEYS[0], 2, seed=1)
    assert one == [KEYS[0], KEYS[0]]
    with pytest.raises(ValueError):
        resolve_comp_keys("definitely_not_a_comp", 1, seed=1)
    # n 席被截断到可用 key 数 / 最多 7
    assert len(resolve_comp_keys("auto", 99, seed=1)) == min(7, len(KEYS))
    assert resolve_comp_keys("auto", 0, seed=1) == []
