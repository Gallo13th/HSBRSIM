"""``tests/test_live_warband.py`` —— live 战团构造/战斗模拟辅助层测试。

覆盖 `hsbg/planning/live_warband.py`：
- live state → 引擎 Minion（stats/keywords/races/golden/position/attached）；
- 单场/两两战斗：同 seed 可复现、无副作用、与直接 run_combat 一致；
- buy/play/sell 后盘面近似预测（不改原 state，标注 approximation）；
- 性能/规模冒烟。
"""

from __future__ import annotations

import copy

from hsrl2.tags import GameTag, Race

from hsbg.planning.live_warband import (
    build_warband,
    make_combat_game,
    normalize_entities,
    pairwise_winrate,
    predict_after_action,
    simulate_combat_warbands,
)


def _live_state() -> dict:
    return {
        "schema": "hsbg.live_state.v1",
        "phase": "recruit",
        "turn": 6,
        "gold": 10,
        "tier": 4,
        "health": 25,
        "armor": 2,
        "board": [
            {"card": "BG25_001", "card_id": "BG25_001", "atk": 5, "hp": 7,
             "golden": False, "keywords": ["TAUNT", "DIVINE_SHIELD"],
             "races": ["UNDEAD"], "position": 0},
            # live 只带 WINDFURY：BGS_119 的 CardDef 原生圣盾应被清掉
            {"card": "BGS_119", "atk": 9, "hp": 9,
             "keywords": ["WINDFURY"], "races": ["ELEMENTAL"],
             "position": 1},
        ],
        "hand": [
            {"card": "BG25_001", "atk": 2, "hp": 1,
             "keywords": [], "races": ["UNDEAD"], "position": 0},
            {"card": "BG28_518", "is_spell": True, "cost": 2, "position": 1},
        ],
        "shop": [
            {"card": "BGS_119", "atk": 3, "hp": 3, "cost": 3,
             "is_minion": True, "position": 0},
            {"card": "BG28_518", "is_spell": True, "cost": 2, "position": 1},
        ],
    }


def test_build_warband_from_live_state():
    state = _live_state()
    build = build_warband(state, "board", seed=1)
    assert build.card_ids() == ["BG25_001", "BGS_119"]
    m0, m1 = build.minions
    assert (int(m0.atk), int(m0.health)) == (5, 7)
    assert (int(m1.atk), int(m1.health)) == (9, 9)
    # live 关键词精确覆盖（清掉 CardDef 原生圣盾）
    assert m0.has(GameTag.TAUNT) and m0.has(GameTag.DIVINE_SHIELD)
    assert m1.has(GameTag.WINDFURY) and not m1.has(GameTag.DIVINE_SHIELD)
    assert Race.UNDEAD in m0.races
    assert build.health == 25 and build.armor == 2
    # 输入不被修改
    assert state == _live_state()


def test_build_warband_attached_and_golden():
    state = _live_state()
    state["board"] = [
        {"card": "BG25_001", "atk": 3, "hp": 4, "golden": True,
         "keywords": ["TAUNT"], "races": ["UNDEAD"], "position": 0,
         "attached": [{"card": "BG26_146", "atk": 2, "hp": 2,
                       "keywords": ["DIVINE_SHIELD"]}]},
    ]
    build = build_warband(state, "board", seed=2)
    m = build.minions[0]
    assert int(m.atk) == 5 and int(m.health) == 6
    assert bool(getattr(m, "is_golden", False))
    assert m.has(GameTag.DIVINE_SHIELD)
    assert any("attached" in w for w in build.warnings)


def test_build_warband_from_hand_and_shop():
    state = _live_state()
    hand = build_warband(state, "hand", seed=1)
    assert hand.card_ids() == ["BG25_001", "BG28_518"]
    shop_specs = normalize_entities(state, "shop")
    assert [s.get("card") or s.get("card_id") for s in shop_specs] == [
        "BGS_119", "BG28_518"]


def test_simulate_combat_deterministic_and_no_side_effect():
    state = _live_state()
    before = copy.deepcopy(state)
    a = state["board"]
    b = state["board"][:1]
    r1 = simulate_combat_warbands(a, b, seed=7)
    r2 = simulate_combat_warbands(a, b, seed=7)
    assert r1.as_dict() == r2.as_dict()
    assert r1.winner_side in ("a", "b", "draw")
    assert r1.rounds >= 0 and r1.damage_dealt >= 0
    assert state == before, "simulate_combat_warbands 修改了输入 state"
    # 不同 seed 至少允许不同（不强制）
    r3 = simulate_combat_warbands(a, b, seed=8)
    assert r3.winner_side in ("a", "b", "draw")


def test_simulate_matches_direct_run_combat():
    state = _live_state()
    specs_a = state["board"]
    specs_b = state["board"][:1]
    seed = 11
    game, ha, hb = make_combat_game(seed=seed, health=30, armor=0)
    ba = build_warband(specs_a, "board", game=game, hero=ha, seed=seed)
    bb = build_warband(specs_b, "board", game=game, hero=hb, seed=seed)
    assert ba.card_ids() and bb.card_ids()
    direct = game.run_combat(ha, hb, alive_count=8)
    direct_winner = ("a" if direct.winner is ha
                     else "b" if direct.winner is hb else "draw")
    sim = simulate_combat_warbands(specs_a, specs_b, seed=seed,
                                   alive_count=8)
    assert sim.winner_side == direct_winner
    assert sim.rounds == int(direct.rounds)
    assert sim.capped_damage == int(direct.capped_damage)


def test_pairwise_winrate_matrix():
    state = _live_state()
    warbands = [state["board"], state["board"][:1], []]
    r1 = pairwise_winrate(warbands, seed=3, samples=2)
    r2 = pairwise_winrate(warbands, seed=3, samples=2)
    assert r1.matrix == r2.matrix and r1.scores == r2.scores
    n = len(warbands)
    assert len(r1.matrix) == n and all(len(row) == n for row in r1.matrix)
    for i in range(n):
        assert r1.matrix[i][i] == 0.0
        for j in range(n):
            if i != j:
                assert abs(r1.matrix[i][j] + r1.matrix[j][i] - 1.0) < 1e-9
    assert all(0.0 <= s <= 1.0 for s in r1.scores)
    assert 0 <= r1.best_index() < n
    assert r1.n_combats == n * (n - 1) // 2 * 2


def test_simulate_accepts_warband_build():
    state = _live_state()
    build = build_warband(state, "board", seed=5)
    r1 = simulate_combat_warbands(build, build, seed=7)
    r2 = simulate_combat_warbands(
        build.specs, build.specs, seed=7,
        a_health=build.health, b_health=build.health,
        a_armor=build.armor, b_armor=build.armor)
    assert r1.as_dict() == r2.as_dict()


def test_predict_after_action_buy_play_sell():
    state = _live_state()
    before = copy.deepcopy(state)
    st1 = predict_after_action(state, {"kind": "buy", "shop_index": 0})
    assert len(st1["hand"]) == 3 and len(st1["shop"]) == 1
    assert st1["gold"] == 7
    assert st1["approximations"]

    st2 = predict_after_action(st1, {"kind": "play", "hand_index": 0,
                                     "position": 1})
    assert len(st2["board"]) == 3 and len(st2["hand"]) == 2
    assert [e.get("position") for e in st2["board"]] == [0, 1, 2]

    st3 = predict_after_action(st2, {"kind": "sell", "board_index": 0})
    assert len(st3["board"]) == 2
    # spell（BG28_518）不改变 board（它在 hand 中）
    spell_idx = next(i for i, e in enumerate(st3["hand"])
                     if e.get("is_spell") or e.get("card") == "BG28_518")
    st4 = predict_after_action(st3, {"kind": "play",
                                     "hand_index": spell_idx})
    assert [e.get("card") for e in st4["board"]] == [
        e.get("card") for e in st3["board"]]
    assert st4["approximations"]
    assert state == before, "predict_after_action 修改了输入 state"


def test_live_warband_performance_smoke():
    import time
    state = _live_state()
    specs = [state["board"]] * 8
    t0 = time.perf_counter()
    result = pairwise_winrate(specs, seed=1, samples=1)
    elapsed = time.perf_counter() - t0
    assert result.n_combats == 28
    assert elapsed < 5.0, f"pairwise 8 warbands too slow: {elapsed:.2f}s"
