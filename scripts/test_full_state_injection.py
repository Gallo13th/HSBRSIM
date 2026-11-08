"""准完整人类状态注入（board + hand + 可推断 counters）的单元/接线测试。

不依赖 torch：全部是 ``hsbg_engine`` + 数据解析 + 训练侧结构断言。
覆盖：

1. tag -> 引擎关键词位映射（与 Rust ``Kw`` 逐位一致）；
2. 观测行解析（golden / kw / shield / tier / hand / availability / fail-closed）；
3. 准完整库可被 ``human_board_pool`` 读成 payload，且 board/hand 分位采样 RNG 一致；
4. **默认档逐位等价**：``fidelity="board"`` 与 ``Game.inject_board`` 的 ``state_json`` 相同；
5. hand/full 真的把 board+hand+counters 注入进引擎（回读校验）；
6. 玩家级 overlay（trinkets/effects/stats…）能搬、也能量化残差；
7. 训练接线（``CollectConfig`` / ``collect_ppo_lockstep`` / ``runlog`` / 训练入口）；
8. 训练管线冒烟（连续回合注入，池守恒、invariants 干净）。
"""

from __future__ import annotations

import json
import os
import random

import pytest

hsbg_engine = pytest.importorskip("hsbg_engine")

from hsbg.az.train import human_obs_full as HOF  # noqa: E402
from hsbg.az.train.human_board_pool import (  # noqa: E402
    HumanBoardStats, inject_turn, load_pool,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUASI = os.path.join(ROOT, "data", "real_library", "library_real_quasi_full.jsonl")
DEGRADED = os.path.join(ROOT, "data", "real_library", "library_real_degraded.jsonl")


# ────────────────────────── 工具 ──────────────────────────


def live_game(seed: int = 7, turns: int = 1) -> "hsbg_engine.Game":
    """跑到 ``turns`` 回合的招募阶段（8 席各选完英雄后即 turn1 recruit）。"""
    g = hsbg_engine.Game(seed=int(seed))
    for _ in range(8):
        p = next((i for i in range(8) if g.needs_action(i)), None)
        if p is None:
            break
        g.bot_play(int(p))
    while int(g.turn) < int(turns) and not g.is_over():
        acted = False
        for p in range(8):
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
        if not acted:
            break
    return g


def _payload(**kw):
    base = {
        "schema": "hsbg.human_state_quasi_full", "schema_version": 1, "turn": 1,
        "board": [{"card": 1389, "atk": 3, "hp": 4, "golden": False, "kw": 0,
                   "bonus_kw": 0, "shield_max": 1}],
        "board_flat": [[1389, 3, 4]],
        "hand": [], "hand_available": False, "tier": None, "gold": None,
        "availability": {}, "has_detail": True,
    }
    base.update(kw)
    return base


# ────────────────────────── 1. tag 映射 ──────────────────────────


def test_tag_to_kw_matches_engine_bits():
    """映射里出现的每个名字都必须有引擎位，且位值与会话契约一致。"""
    assert set(HOF.TAG_TO_KW.values()) <= set(HOF.KW_BITS)
    assert HOF.KW_BITS["TAUNT"] == 1 and HOF.KW_BITS["DIVINE_SHIELD"] == 2
    assert HOF.KW_BITS["WINDFURY"] == 4 and HOF.KW_BITS["REBORN"] == 8
    assert HOF.KW_BITS["VENOMOUS"] == 16 and HOF.KW_BITS["POISONOUS"] == 32
    assert HOF.KW_BITS["STEALTH"] == 64 and HOF.KW_BITS["MAGNETIC"] == 128
    # 每个 tag 只映射到一个名字，且同名义 tag 成对出现（190/3614 等）
    for tag, name in HOF.TAG_TO_KW.items():
        assert isinstance(tag, int) and isinstance(name, str)


# ────────────────────────── 2. 观测解析 ──────────────────────────


def _obs_row(**kw):
    row = {
        "board": [
            {"card_id": "BG31_803_G", "attack": 2, "health": 2, "position": 1,
             "entity_id": 11,
             "tags": {"47": 2, "45": 2, "190": 1, "217": 1, "194": 3, "12": 1}},
            {"card_id": "BG33_318", "attack": 5, "health": 6, "position": 2,
             "entity_id": 12, "tags": {"47": 5, "45": 6, "2853": 1}},
        ],
        "heroes": [{"card_id": "BG23_HERO_305", "tags": {"1377": 4}}],
        "known_hand": [
            {"card_id": "BG28_810", "entity_id": 99, "tags": {"202": 5}},
            {"card_id": "BG29_611", "entity_id": 98, "tags": {"202": 4, "47": 1, "45": 1}},
        ],
        "unknown_hand_count": 0,
        "stage": HOF.EOT_STAGE,
        "perspective": "self",
        "turn": 9,
        "game_id": "g1",
        "split": "train",
        "controller": 3,
        "build_number": 254477,
        "library_ready": False,
        "hidden_counters_complete": False,
    }
    row.update(kw)
    return row


def test_parse_observation_quasi_full():
    meta = HOF.load_card_meta()
    assert "BG31_803_G" in meta and "BG33_318" in meta
    p, reasons = HOF.parse_observation(_obs_row(), meta)
    assert p is not None, reasons
    assert p["turn"] == 9 and p["tier"] == 4
    b0, b1 = p["board"][0], p["board"][1]
    # golden：_G 卡 id + tag 12 都指向金色
    assert b0["golden"] is True
    # 关键词位：190 TAUNT + 194 DIVINE_SHIELD；217(亡语) 不在引擎 Kw 里，必须忽略
    assert b0["kw"] & HOF.KW_BITS["TAUNT"]
    assert b0["kw"] & HOF.KW_BITS["DIVINE_SHIELD"]
    assert b0["shield_max"] == 3, "tag 194 的值 = 圣盾层数"
    assert b1["kw"] & HOF.KW_BITS["VENOMOUS"]
    # hand：self 视角 + unknown_hand_count=0 -> 可信；minion 与 spell 都要能区分
    assert p["hand_available"] is True and len(p["hand"]) == 2
    kinds = {h["kind"] for h in p["hand"]}
    assert kinds == {"minion", "spell"}
    assert p["availability"]["hand"] == "observed"
    assert p["availability"]["gold"] == "unavailable"
    assert p["availability"]["counter"] == "unavailable"
    assert p["availability"]["tavern_tier"] == "observed"


def test_parse_observation_fail_closed():
    meta = HOF.load_card_meta()
    # 非 EOT 帧直接丢
    p, r = HOF.parse_observation(_obs_row(stage="first_attack_after_start_effects"), meta)
    assert p is None and "stage" in r
    # 卡表里没有的卡 -> 整行丢弃
    row = _obs_row()
    row["board"][0]["card_id"] = "NOT_A_CARD"
    p, r = HOF.parse_observation(row, meta)
    assert p is None and any("unmapped_minion" in x for x in r)
    # 对手视角的手牌不可信 -> hand 标 unavailable（board 仍可用）
    row = _obs_row(perspective="observed_opponent")
    p, _ = HOF.parse_observation(row, meta)
    assert p is not None and p["hand_available"] is False
    assert p["availability"]["hand"] == "unavailable"


# ────────────────────────── 3. 库 + 采样 ──────────────────────────


@pytest.mark.skipif(not os.path.isfile(QUASI), reason="准完整库未生成")
def test_quasi_library_payload_and_rng_equivalence():
    pool = load_pool(QUASI)
    assert pool is not None and pool.payload_kept == pool.kept > 1000
    assert pool.stats()["fidelity_detail"] == "quasi_full"
    bad = 0
    for turn in range(1, 18):
        for seed in range(20):
            a = pool.sample(turn, random.Random(seed), "auto")
            b = pool.sample_payload(turn, random.Random(seed), "auto")
            assert b is not None and b.get("has_detail") is True
            if a != b["board_flat"]:
                bad += 1
    assert bad == 0, "换保真度档不得改变 RNG/分位选择"


@pytest.mark.skipif(not os.path.isfile(DEGRADED), reason="旧 board-only 库不存在")
def test_board_only_library_degrades_gracefully():
    pool = load_pool(DEGRADED)
    assert pool is not None and pool.payload_kept == 0
    pay = pool.sample_payload(6, random.Random(1), "auto")
    assert pay is not None and pay["has_detail"] is False
    assert pay["board_flat"], "旧库仍要能退化到 board-only"


# ────────────────────────── 4. 默认档逐位等价 ──────────────────────────


def test_board_fidelity_is_bit_identical_to_inject_board():
    pay = _payload(
        board=[{"card": 1389, "atk": 3, "hp": 4, "golden": False, "kw": 0,
                "bonus_kw": 0, "shield_max": 1}],
        board_flat=[[1389, 3, 4]],
        tier=4,
    )
    g1 = live_game(seed=21)
    g2 = live_game(seed=21)
    r1 = g1.inject_board(2, pay["board_flat"], 4)
    r2 = HOF.inject_quasi_state(g2, 2, pay, "board")
    assert r1["applied"] and r2["applied"], (r1, r2)
    assert g1.state_json() == g2.state_json(), "board 档必须与 inject_board 逐位一致"


# ────────────────────────── 5. hand / full 注入 ──────────────────────────


def test_hand_and_full_injection_reads_back():
    meta = HOF.load_card_meta()
    p, _ = HOF.parse_observation(_obs_row(), meta)
    assert p is not None
    g = live_game(seed=31)
    before2 = json.loads(g.player_json(2))
    before0 = json.loads(g.player_json(0))
    rep = HOF.inject_quasi_state(g, 2, p, "full", reset_ended=True)
    assert rep["applied"], rep
    assert rep["hand_applied"] and rep["counters_applied"], rep
    after = json.loads(g.player_json(2))
    # board 完全来自 payload（含被授予的关键词位）
    assert [m["card"] for m in after["board"]] == [b["card"] for b in p["board"]]
    assert after["board"][0]["kw"] & HOF.KW_BITS["DIVINE_SHIELD"]
    assert after["board"][0]["shield_hits"] == 3
    assert after["board"][1]["kw"] & HOF.KW_BITS["VENOMOUS"]
    assert after["tier"] == p["tier"]
    assert len(after["hand"]) == len(p["hand"]), (len(after["hand"]), len(p["hand"]))
    # 训练语义：注入后该座位仍要行动（ended_turn 复位）
    assert after["ended_turn"] is False and g.needs_action(2) is True
    # 引擎不变量与共享池
    assert g.invariant_violations() == []
    held, initial = g.pool_balance()
    assert held == initial
    # 换手牌/换 board 前后，learner 不受影响
    assert json.loads(g.player_json(0))["board"] == before0["board"]
    assert before2["board"] == [] or before2["board"] != after["board"]


def test_fidelity_hand_keeps_live_tier_and_gold():
    meta = HOF.load_card_meta()
    p, _ = HOF.parse_observation(_obs_row(), meta)
    p = dict(p, tier=6, gold=9)
    g = live_game(seed=32)
    before = json.loads(g.player_json(2))
    rep = HOF.inject_quasi_state(g, 2, p, "hand", reset_ended=True)
    assert rep["applied"], rep
    after = json.loads(g.player_json(2))
    assert after["tier"] == before["tier"], "hand 档不写 tier"
    assert after["gold"] == before["gold"], "hand 档不写 gold"
    assert rep["counters_applied"] is False


def test_full_writes_gold_but_hand_keeps_it():
    """``gold`` 透传：full 档写回目标座位，hand 档保持原值（与 tier 同一口径）。"""
    meta = HOF.load_card_meta()
    p, _ = HOF.parse_observation(_obs_row(), meta)
    p = dict(p, tier=6, gold=11)
    g = live_game(seed=31)
    rep = HOF.inject_quasi_state(g, 2, p, "full", reset_ended=True)
    assert rep["applied"], rep
    after = json.loads(g.player_json(2))
    assert after["gold"] == 11, after["gold"]
    assert after["tier"] == p["tier"]
    assert g.invariant_violations() == []


def test_full_without_gold_keeps_live_gold():
    """payload 没有 gold（None，10k+ 准完整库）时 full 档**不覆写**当前金币。"""
    meta = HOF.load_card_meta()
    p, _ = HOF.parse_observation(_obs_row(), meta)
    p = dict(p, tier=5, gold=None)
    g = live_game(seed=31)
    before = json.loads(g.player_json(2))
    rep = HOF.inject_quasi_state(g, 2, p, "full", reset_ended=True)
    assert rep["applied"], rep
    after = json.loads(g.player_json(2))
    assert after["gold"] == before["gold"], "gold=None 不应该改变目标座位金币"
    assert after["tier"] == 5


def test_player_overlay_modes():
    g0 = live_game(seed=41)
    effects = [{"card": 2162, "stacks": 2}]
    stats = dict(json.loads(g0.player_json(2))["stats"])
    stats["tavern_atk"] = 7
    pay = _payload(player={"effects": effects, "stats": stats})
    g = live_game(seed=41)
    rep = HOF.inject_quasi_state(g, 2, pay, "full", reset_ended=True,
                                 player_overlay="combat")
    assert rep["applied"], rep
    after = json.loads(g.player_json(2))
    assert after["effects"] == effects
    assert after["stats"]["tavern_atk"] == 7
    assert rep["overlay"], "应报告实际 overlay 的字段"
    # none 档：玩家级字段保持目标座位原值
    g2 = live_game(seed=41)
    before2 = json.loads(g2.player_json(2))
    rep2 = HOF.inject_quasi_state(g2, 2, pay, "full", reset_ended=True,
                                  player_overlay="none")
    assert rep2["applied"]
    after2 = json.loads(g2.player_json(2))
    assert after2["effects"] == before2["effects"]
    assert after2["stats"]["tavern_atk"] == before2["stats"]["tavern_atk"]


def test_missing_payload_falls_back_to_board_only():
    """hand/full 档遇到没有 board_detail 的行：退化 board-only + 计 payload_missing。"""
    if not os.path.isfile(DEGRADED):
        pytest.skip("旧库不存在")
    pool = load_pool(DEGRADED)
    g = live_game(seed=51, turns=2)
    st = HumanBoardStats()
    inject_turn(g, pool, int(g.turn), seats_count=2, p=1.0, rng=random.Random(3),
                stats=st, fidelity="full")
    meta = st.to_meta()
    assert meta["human_board_fidelity"] == "full"
    assert meta["human_board_payload_missing"] >= 1
    assert meta["human_board_full_applied"] == 0
    assert meta["human_board_attempt"] >= 1


# ────────────────────────── 6. 训练接线 ──────────────────────────


def test_training_wiring():
    from hsbg.az.train.ppo import CollectConfig

    cfg = CollectConfig()
    assert cfg.human_board_fidelity == "board", "默认必须保持 board（逐位等价现状）"
    src = open(os.path.join(ROOT, "hsbg", "az", "train", "parallel_collect.py"),
               encoding="utf-8").read()
    for token in ("human_board_fidelity", "fidelity=human_fidelity",
                  "human_board_payload_rows"):
        assert token in src, token
    entry = open(os.path.join(ROOT, "scripts", "train_entity_sync.py"),
                 encoding="utf-8").read()
    assert "--human-board-fidelity" in entry
    assert 'choices=["board", "hand", "full"]' in entry.replace("'", '"')
    # history.jsonl 的 collect 段必须能拿到这些键（slim_collect 会做提升/聚合）
    from hsbg.az.train.runlog import INJECTION_KEYS, slim_collect

    for key in ("human_board_fidelity", "human_board_hand_applied",
                "human_board_counters_applied", "human_board_unavailable_fields"):
        assert key in INJECTION_KEYS, key
    meta = {"worker_meta": [
        {"human_board_fidelity": "full", "human_board_hand_applied": 3,
         "human_board_counters_applied": 4,
         "human_board_unavailable_fields": {"gold": 4, "counter": 4}},
        {"human_board_fidelity": "full", "human_board_hand_applied": 2,
         "human_board_counters_applied": 1,
         "human_board_unavailable_fields": {"gold": 1}},
    ]}
    slim = slim_collect(meta)
    assert slim["human_board_fidelity"] == "full"
    assert slim["human_board_hand_applied"] == 5
    assert slim["human_board_counters_applied"] == 5
    assert slim["human_board_unavailable_fields"] == {"gold": 5, "counter": 4}


# ────────────────────────── 7. 训练管线冒烟 ──────────────────────────


@pytest.mark.skipif(not os.path.isfile(QUASI), reason="准完整库未生成")
def test_pipeline_injection_smoke_all_fidelities():
    pool = load_pool(QUASI)
    for fid in ("board", "hand", "full"):
        st = HumanBoardStats()
        rng = random.Random(20261031)
        games = 2
        gs = [live_game(seed=700 + i) for i in range(games)]
        turns = 0
        for rnd in range(4000):
            active = [g for g in gs if not g.is_over()]
            if not active:
                break
            for g in active:
                inject_turn(g, pool, int(g.turn), seats_count=2, p=1.0, rng=rng,
                            stats=st, fidelity=fid, set_tier=True)
                acted = False
                for p in range(8):
                    if g.is_over():
                        break
                    if g.needs_action(p):
                        g.bot_play(p)
                        acted = True
                if not acted:
                    break
            turns += 1
        meta = st.to_meta()
        assert meta["human_board_fidelity"] == fid
        assert meta["human_board_applied"] > 0, meta
        assert meta["human_board_pool_unbalanced"] == 0, meta
        for g in gs:
            held, initial = g.pool_balance()
            assert held == initial, (fid, held, initial)
            assert g.invariant_violations() == [], (fid, g.invariant_violations()[:2])
        if fid in ("hand", "full"):
            assert meta["human_board_full_applied"] > 0, meta
            if fid == "full":
                assert meta["human_board_counters_applied"] > 0, meta
            else:
                assert meta["human_board_counters_applied"] == 0, meta
        else:
            assert meta["human_board_full_applied"] == 0
            assert meta["human_board_hand_applied"] == 0
