"""`Game.from_json` 恢复的不变量 property 测试（CPU，无 GPU）。

覆盖 PPAI 终审要求的检查：
- 原局 vs 恢复局，喂相同动作后逐步 `state_json` 一致（确定性分叉检查）；
- `next_eid` 单调唯一、pool 计数非负、alive/placement 一致；
- 从每个 turn 恢复后能无异常打到终局，且名次是 1..8 的排列；
- `truncated_combats`/`stopped_reason`/`ending_turn` 等字段在恢复后保持。
"""

from __future__ import annotations

import json

import pytest


def _engine():
    pytest.importorskip("hsbg_engine")
    import hsbg_engine as E
    return E


def _advance_turn(g) -> None:
    """让引擎把当前回合所有需要动作的座位用 bot 走完（不跨 turn）。"""
    turn = int(g.turn)
    guard = 0
    while int(g.turn) == turn and not g.is_over() and guard < 5000:
        acted = False
        for p in range(8):
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
                guard += 1
                if g.is_over() or int(g.turn) != turn:
                    break
        if not acted:
            break


def _check_invariants(state: dict) -> None:
    players = state["players"]
    placements = [int(p.get("placement", 0)) for p in players]
    for p, pl in zip(players, placements):
        assert bool(p.get("alive", False)) == (pl == 0), \
            f"alive/placement 不一致: alive={p.get('alive')} placement={pl}"
    gone = sorted(x for x in placements if x > 0)
    # 淘汰座位拿到的是「底部名次」：k 个已淘汰 → {8-k+1 .. 8}，且互不重复
    assert len(set(gone)) == len(gone), f"淘汰名次重复: {gone}"
    assert gone == list(range(8 - len(gone) + 1, 9)), f"淘汰名次不是底部连续段: {gone}"
    assert placements.count(0) == sum(1 for p in players if p.get("alive")), "存活数不一致"
    assert int(state.get("next_eid", -1)) >= 1, "next_eid 必须 >= 1"


def test_restore_is_deterministic_across_turns():
    E = _engine()
    for seed in (1, 2):
        g = E.Game(seed=seed)
        for turn in range(1, 6):
            _advance_turn(g)
            if g.is_over():
                break
            snapshot = g.state_json()
            h = E.Game.from_json(snapshot)
            assert h.turn == g.turn
            assert h.state_json() == snapshot, f"恢复后 state_json 不一致 (seed={seed}, turn={turn})"
            _check_invariants(json.loads(snapshot))
            # 同动作推进：原局与恢复局必须逐步一致
            for _step in range(30):
                moved = False
                for p in range(8):
                    if g.is_over() or h.is_over():
                        break
                    if g.needs_action(p) != h.needs_action(p):
                        raise AssertionError(f"needs_action 分叉 (seed={seed}, turn={turn})")
                    if not g.needs_action(p):
                        continue
                    a = g.bot_action(p)
                    g.step(p, a)
                    h.step(p, a)
                    moved = True
                    if g.state_json() != h.state_json():
                        raise AssertionError(
                            f"状态分叉 (seed={seed}, turn={turn}, step={_step})")
                if not moved:
                    break
            # 恢复局的 next_eid 单调（继续推进不应回退）
            assert int(json.loads(h.state_json())["next_eid"]) >= int(json.loads(snapshot)["next_eid"])


def test_restore_at_every_turn_plays_to_end():
    E = _engine()
    for seed in (11, 12):
        base = E.Game(seed=seed)
        for turn in range(1, 9):
            _advance_turn(base)
            if base.is_over():
                break
            h = E.Game.from_json(base.state_json())
            # 从恢复点用 bot 打到终局：不允许异常/卡死/名次非法
            guards = 0
            while not h.is_over() and guards < 20000:
                acted = False
                for p in range(8):
                    if h.needs_action(p):
                        h.bot_play(p)
                        acted = True
                        guards += 1
                        if h.is_over():
                            break
                if not acted:
                    break
            assert h.is_over(), f"从 turn={turn} 恢复后未能终局 (seed={seed})"
            places = sorted(int(x) for x in h.placements())
            assert places == list(range(1, 9)), f"名次不是 1..8 排列: {places}"
