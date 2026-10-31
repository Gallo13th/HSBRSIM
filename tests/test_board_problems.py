"""场面题（board problems）单测：schema / 参考解匹配 / Move 守卫 / 可复现 / 标签。

覆盖（``docs/BOARD_PROBLEMS.md``）：

1. **观测 round-trip**：``encode_obs``/``decode_obs`` 对 f32 逐位、f16 近似；合法掩码
   只由 ``legal`` 下标重建（不泄漏非法动作）；``sha256`` 随观测变化；
2. **状态反推**：``tier/gold/turn/board_strength/shop_phase`` 与观测同口径（不读
   ``player_json``）；
3. **分叉点标签**：可升本 / 三连 / 核心随从；
4. **Move 安全**：``apply_move_guard`` 的逆换位/重复上限/每回合上限；监督候选与 rollout
   采样都套用同一规则（题目里 ``move.n`` 不会超过 ``move_cap``）；
5. **参考解匹配**：按 ``(shop,turn,tier,gold)`` 分层、同卡优先落到对应槽位、只返回合法
   动作、soft 权重和为 1、支撑不足逐级退化/无支撑返回未匹配；**酒馆空/满两个阶段
   的 end_turn 偏置被对齐**；
6. **题目池**：``write_problems``→``load_problem_pool`` round-trip、强度 z-score、
   空池/缺文件、``problem_stats`` 聚合口径；
7. **可复现**：同 seed 两次 ``collect_problems`` 的观测/动作/标签完全相同（需要引擎）。
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from hsbg.env import obs_std as O
from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.board_problems import (
    ALL_TAGS,
    PROBLEM_SCHEMA_VERSION,
    BoardProblemPool,
    ProblemCollectConfig,
    ProblemCollectResult,
    ReferenceTable,
    TAG_CORE_CARD,
    TAG_TRIPLE_READY,
    TAG_TURN_START,
    TAG_UPGRADE_READY,
    _card_tier_table,
    apply_move_guard,
    board_strength_from_features,
    build_reference_table,
    collect_problems,
    decode_obs,
    encode_obs,
    fork_tags,
    gold_from_features,
    load_problem_pool,
    match_reference_actions,
    obs_sha256,
    problem_obs_batch,
    problem_stats,
    shop_phase_from_features,
    supervisable_legal_actions,
    tier_from_features,
    turn_from_features,
    write_problems,
)
from hsbg.az.train.move_guard import encode_move

TURN_START = TAG_TURN_START


# ── 工具：合成观测 ─────────────────────────────────────────────────────
def _blank_obs():
    return np.zeros(OBS_FLOATS, np.float32), np.zeros(OBS_CARDS, np.int32)


def _set_global(f: np.ndarray, **kw) -> None:
    scale = O.GLOBAL_FIELD_SCALE
    for name, value in kw.items():
        i = O.GLOBAL_FIELD_INDEX[name]
        s = scale.get(name)
        f[O.SLICE_GLOBAL][i] = float(value) / float(s) if s else float(value)


def _set_board(f: np.ndarray, slot: int, card: int, atk: int, hp: int) -> None:
    base = O.SLICE_BOARD.start + slot * O.MINION_F
    f[base + O.MINION_PRESENT] = 1.0
    f[base + O.MINION_ATK] = atk / 10.0
    f[base + O.MINION_HP] = hp / 10.0


def _set_shop(f: np.ndarray, slot: int, card: int, minion: bool = True) -> None:
    base = O.SLICE_SHOP.start + slot * O.ITEM_F
    f[base + O.ITEM_PRESENT] = 1.0
    f[base + O.ITEM_IS_MINION] = 1.0 if minion else 0.0


def _set_hand(f: np.ndarray, slot: int, card: int, minion: bool = True) -> None:
    base = O.SLICE_HAND.start + slot * O.ITEM_F
    f[base + O.ITEM_PRESENT] = 1.0
    f[base + O.ITEM_IS_MINION] = 1.0 if minion else 0.0


def _state_obs(*, turn=5, tier=3, gold=5, board=(), shop=(), hand=()):
    """构造一个「像样」的观测：棋盘/酒馆/手牌 + global 字段。"""
    f, c = _blank_obs()
    _set_global(f, turn=turn, tier=tier, gold=gold,
                board_len=len(board), hand_len=len(hand), alive=1,
                health=30)
    for (slot, card, atk, hp) in board:
        _set_board(f, slot, card, atk, hp)
        c[O.SLICE_CARD_BOARD.start + slot] = card
    for (slot, card) in shop:
        _set_shop(f, slot, card)
        c[O.SLICE_CARD_SHOP.start + slot] = card
    for (slot, card) in hand:
        _set_hand(f, slot, card)
        c[O.SLICE_CARD_HAND.start + slot] = card
    return f, c


def _mask(*acts):
    m = np.zeros(N_ACTIONS, dtype=bool)
    for a in acts:
        m[int(a)] = True
    return m


def _big_mask():
    """一个「几乎全合法」的掩码（0..125 + 196..244）。"""
    m = np.zeros(N_ACTIONS, dtype=bool)
    m[0:126] = True
    m[196:245] = True
    return m


# ── 1. 观测 round-trip ─────────────────────────────────────────────────
def test_obs_roundtrip_f32_bitwise():
    f, c = _state_obs(board=[(0, 100, 4, 5)], shop=[(0, 200)], hand=[(0, 300)])
    m = _mask(0, 3, 8, 16, 46)
    enc = encode_obs(f, c, m, dtype="f32")
    assert enc["dtype"] == "f32"
    assert enc["legal"] == [0, 3, 8, 16, 46]
    f2, c2, m2 = decode_obs(enc)
    assert np.array_equal(f2, f)
    assert np.array_equal(c2, c)
    assert np.array_equal(m2, m)
    assert enc["sha256"] == obs_sha256(f, c, m)


def test_obs_roundtrip_f16_close_and_sha_changes():
    f, c = _state_obs(shop=[(0, 7)])
    m = _mask(0, 8)
    enc = encode_obs(f, c, m, dtype="f16")
    f2, c2, m2 = decode_obs(enc)
    assert np.allclose(f2, f, atol=1e-3)
    assert np.array_equal(c2, c) and np.array_equal(m2, m)
    # 改一个字节 -> 指纹变化
    f3 = f.copy()
    f3[0] += 1.0
    assert obs_sha256(f3, c, m) != enc["sha256"]


def test_decode_obs_ignores_illegal_indices():
    f, c = _state_obs()
    enc = encode_obs(f, c, _mask(0, 5))
    enc["legal"] = [0, 5, 999, -3]        # 越界下标被忽略（防御）
    _f, _c, m = decode_obs(enc)
    assert m.sum() == 2 and bool(m[0]) and bool(m[5])


def test_encode_obs_rejects_bad_shapes():
    f, c = _state_obs()
    with pytest.raises(ValueError):
        encode_obs(f[:-1], c, _mask(0))
    with pytest.raises(ValueError):
        encode_obs(f, c[:-1], _mask(0))
    with pytest.raises(ValueError):
        encode_obs(f, c, np.zeros(10, bool))


# ── 2. 状态反推 ────────────────────────────────────────────────────────
def test_state_from_features():
    f, _c = _state_obs(turn=7, tier=4, gold=9,
                       board=[(0, 1, 3, 4), (1, 2, 6, 7)], shop=[(0, 9)])
    assert turn_from_features(f) == 7
    assert tier_from_features(f) == 4
    assert gold_from_features(f) == 9
    # Σ(atk+hp) = (3+4) + (6+7) = 20
    assert board_strength_from_features(f) == 20
    assert shop_phase_from_features(f) == 1
    f2, _ = _state_obs(shop=[])
    assert shop_phase_from_features(f2) == 0


def test_board_strength_empty_board_is_zero():
    f, _ = _state_obs(shop=[(0, 1)])
    assert board_strength_from_features(f) == 0


# ── 3. 分叉点标签 ──────────────────────────────────────────────────────
def test_fork_tags_upgrade_triple_core():
    tbl = _card_tier_table()
    assert tbl is not None, "需要卡表来测 core_card"
    high = int(np.flatnonzero(tbl >= 5)[0])
    low = int(np.flatnonzero((tbl >= 1) & (tbl <= 2))[0])
    f, c = _state_obs(tier=2, board=[(0, high, 5, 5)],
                      shop=[(0, 777)], hand=[(0, 777), (1, 777)])
    tags = fork_tags(_mask(0, 3, 8), f, c, core_min_tier=3)
    assert TAG_UPGRADE_READY in tags          # mask[3] 合法 = 引擎判定可升本
    assert TAG_TRIPLE_READY in tags           # 手牌 2 张 + 酒馆 1 张
    assert TAG_CORE_CARD in tags              # 棋盘有 tier>=3 的核心随从
    # 不可升本 / 没三连 / 没核心
    assert TAG_UPGRADE_READY not in fork_tags(_mask(0, 8), f, c)
    f2, c2 = _state_obs(board=[(0, low, 1, 1)], shop=[(0, 5)], hand=[(0, 6)])
    tags2 = fork_tags(_mask(0, 8, 3), f2, c2, core_min_tier=3)
    assert TAG_TRIPLE_READY not in tags2
    assert TAG_CORE_CARD not in tags2


# ── 4. Move 守卫 ───────────────────────────────────────────────────────
def test_apply_move_guard_inverse_repeat_cap():
    a, b = 1, 3
    forward, back = encode_move(a, b), encode_move(b, a)
    # 逆换位：上一步 a→b，本步 b→a 被去掉
    out = apply_move_guard([forward, back, 0], move_last=forward)
    assert back not in out and forward in out and 0 in out
    # 重复上限：同一 (from,to) 已出现 2 次（默认 repeat_limit=2）
    out = apply_move_guard([forward, 0], move_counts={forward: 2})
    assert forward not in out and 0 in out
    # 每回合上限：已选 3 次换位（默认 cap=3）-> 所有换位被去掉
    out = apply_move_guard([forward, back, 0], move_n=3)
    assert forward not in out and back not in out and 0 in out
    # 非 Move 动作永远保留
    assert apply_move_guard([0, 1, 3, 8], move_n=99) == [0, 1, 3, 8]


def test_apply_move_guard_respects_mask():
    fwd = encode_move(0, 1)
    m = _mask(0)                      # 只允许 EndTurn
    assert apply_move_guard([fwd, 0], mask=m) == [0]
    assert apply_move_guard([fwd], mask=m) == []


def test_supervisable_legal_actions():
    m = np.zeros(N_ACTIONS, bool)
    m[[30, 31, 32, 196]] = True       # 只有 choose / move -> 不可监督
    assert supervisable_legal_actions(m).size == 0
    m[[0, 3, 8, 46]] = True
    assert set(supervisable_legal_actions(m).tolist()) == {0, 3, 8, 46}


# ── 5. 参考解匹配 ──────────────────────────────────────────────────────
def _ref_jsonl(tmp_path, rows):
    p = tmp_path / "bc_rows.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return str(p)


def _human_row(*, turn, tier, gold, atype, card="", mmr=12000, shop=True):
    return {"turn": turn, "tier": tier, "gold": gold, "action_type": atype,
            "card_id": card, "mmr": str(mmr),
            "shop_cards": ["X"] if shop else [], "hand_cards": [],
            "board_cards": []}


def test_reference_table_and_matching_prefers_same_card_slot(tmp_path):
    from hsbg.az.train.bc_aux import load_bc_card_table
    ids = load_bc_card_table().ids
    # 找一个 tier>=2 的随从卡 id
    tbl = _card_tier_table()
    idx = int(np.flatnonzero((tbl >= 2) & (tbl <= 6))[0])
    cid = ids[idx]
    rows = [_human_row(turn=5, tier=3, gold=5, atype="buy_minion", card=cid)
            for _ in range(60)]
    rows += [_human_row(turn=5, tier=3, gold=5, atype="end_turn")
             for _ in range(10)]
    rows += [_human_row(turn=5, tier=3, gold=5, atype="end_turn", shop=False)
             for _ in range(100)]
    table = build_reference_table(_ref_jsonl(tmp_path, rows), floors=(10000,))
    assert table.rows[10000] == len(rows)
    f, c = _state_obs(turn=5, tier=3, gold=5, shop=[(0, 5), (2, idx)])
    m = _mask(0, 1, 3, 8, 9, 10)
    out = match_reference_actions(f, c, m, table, top_k=4, min_support=10)
    assert out["matched"] and out["level"] == "turn_tier_gold"
    # 同卡优先落到 slot 2（权重最高），且权重大于 end_turn
    w = dict(zip(out["actions"], out["weights"]))
    assert 8 + 2 in w, out
    assert max(w, key=lambda a: w[a]) == 8 + 2, out
    assert abs(sum(out["weights"]) - 1.0) < 1e-6
    # 只返回合法动作
    assert all(bool(m[a]) for a in out["actions"])
    # 酒馆已空（shop_phase=0）的 end_turn 样本不会污染「酒馆有牌」的题
    assert w.get(8 + 2, 0.0) > w.get(0, 0.0)


def test_reference_matching_shop_phase_separates_end_turn(tmp_path):
    """酒馆空的 end_turn 行只进 ``shop_phase=0``，不把「回合起点」推去 EndTurn。"""
    rows = []
    for _ in range(50):
        rows.append(_human_row(turn=2, tier=1, gold=4, atype="end_turn",
                               shop=False))
        rows.append(_human_row(turn=2, tier=1, gold=4, atype="upgrade"))
    table = build_reference_table(_ref_jsonl(tmp_path, rows), floors=(10000,))
    f, c = _state_obs(turn=2, tier=1, gold=4, shop=[(0, 3)])
    m = _mask(0, 1, 3, 4)
    out = match_reference_actions(f, c, m, table, top_k=4, min_support=10)
    assert out["matched"]
    assert out["actions"][0] == 3     # upgrade（shop 有牌阶段的主动作）
    w = dict(zip(out["actions"], out["weights"]))
    assert w.get(3, 0.0) > w.get(0, 0.0)


def test_reference_matching_falls_back_when_support_low(tmp_path):
    rows = [_human_row(turn=9, tier=5, gold=6, atype="reroll") for _ in range(60)]
    table = build_reference_table(_ref_jsonl(tmp_path, rows), floors=(10000,))
    f, c = _state_obs(turn=9, tier=5, gold=6, shop=[(0, 3)])
    m = _mask(0, 1, 3, 8)
    strict = match_reference_actions(f, c, m, table, min_support=1000)
    assert not strict["matched"] and strict["reason"] == "no_support"
    loose = match_reference_actions(f, c, m, table, min_support=10)
    assert loose["matched"] and loose["actions"][0] == 1


def test_reference_matching_no_legal_ref(tmp_path):
    rows = [_human_row(turn=3, tier=2, gold=5, atype="buy_minion", card="NOPE")
            for _ in range(30)]
    table = build_reference_table(_ref_jsonl(tmp_path, rows), floors=(10000,))
    f, c = _state_obs(turn=3, tier=2, gold=5, shop=[(0, 5)])
    m = _mask(30, 31)                  # 只有 choose 合法
    out = match_reference_actions(f, c, m, table, min_support=10)
    assert not out["matched"] and out["reason"] == "no_legal_ref"


def test_reference_matching_excludes_move():
    table = ReferenceTable(floors=(10000,), rows={10000: 1}, tables={
        10000: {"by_turn_tier_gold": {}, "by_turn_tier": {}, "by_tier": {},
                "by_turn": {}, "all": {
                    1: {("end_turn", ""): 1.0,
                        ("reposition", ""): 50.0}}}})
    f, c = _state_obs(turn=5, tier=3, gold=5, shop=[(0, 3)])
    m = _big_mask()
    out = match_reference_actions(f, c, m, table, min_support=0)
    assert out["matched"]
    assert not any(196 <= a < 245 for a in out["actions"])


# ── 6. 题目池 round-trip / 统计 ────────────────────────────────────────
def _row(i, *, turn, tier, gold, act=(0, 8), weights=(0.6, 0.4),
         s_before=100.0, s_after=300.0, tier_up=1, terminal=0, tags=None,
         level="turn_tier", floor=10000, policy=8):
    f, c = _state_obs(turn=turn, tier=tier, gold=gold, shop=[(0, 3)])
    m = _mask(0, 1, 3, 8, 9)
    return {
        "problem_id": f"bp-{i:06d}", "schema": PROBLEM_SCHEMA_VERSION,
        "source_group": "rollout:seed=1:game=0", "game_seed": 1,
        "turn": turn, "seat": 0, "decision_idx": 0,
        "tags": list(tags or [TURN_START]),
        "obs": encode_obs(f, c, m, dtype="f32"),
        "state": {"gold": gold, "tier": tier, "strength": int(s_before),
                  "board_len": 1, "hand_len": 0, "shop_len": 1},
        "policy_action": int(policy), "policy_prob": 0.5,
        "ref": {"actions": list(act), "weights": list(weights),
                "matched": len(act) > 0, "level": level, "floor": floor,
                "support": 100, "mass_legal": 0.5, "reason": "ok"},
        "label": {"strength_before": s_before, "strength_after_t3": s_after,
                  "delta": s_after - s_before,
                  "delta_log1p": float(np.log1p(s_after) - np.log1p(s_before)),
                  "tier_before": tier, "tier_after": tier + int(tier_up),
                  "tier_up": int(tier_up), "survived": int(not terminal),
                  "terminal": int(terminal), "available": 1, "horizon": 3,
                  "target_turn": turn + 3},
        "move": {"last": -1, "n": 0, "counts": []},
    }


def test_write_and_load_problem_pool(tmp_path):
    rows = [_row(0, turn=5, tier=3, gold=5),
            _row(1, turn=8, tier=4, gold=9, act=(1,), weights=(1.0,),
                 s_before=200.0, s_after=800.0, tier_up=0),
            _row(2, turn=3, tier=1, gold=3, terminal=1, act=(3,),
                 weights=(1.0,))]
    stats = problem_stats(rows)
    assert stats["problems"] == 3
    assert stats["ref_matched"] == 3
    assert stats["label_survived_rate"] == pytest.approx(2 / 3)
    res = ProblemCollectResult(problems=rows, stats=stats)
    path, meta_path = write_problems(res, str(tmp_path / "problems.jsonl"))
    assert os.path.isfile(path) and os.path.isfile(meta_path)
    pool = load_problem_pool(path)
    assert len(pool) == 3
    assert pool.turn.tolist() == [5, 8, 3]
    assert pool.bc_valid.all()
    # aux_valid = 有 t+3 标签 **且存活**：terminal 题不进强度损失（masked 而不是填 0）
    assert pool.aux_valid.tolist() == [True, True, False]
    assert pool.ref_actions.shape[1] >= 2
    # 强度目标是**增量**（log1p(after) - log1p(before)）的 z-score
    norm = pool.norm
    before = np.asarray([100.0, 200.0, 100.0])
    after = np.asarray([300.0, 800.0, 300.0])
    delta = np.log1p(after) - np.log1p(before)
    expect = (delta - norm["mean"]) / norm["std"]
    assert np.allclose(pool.strength_target, expect, atol=1e-5)
    assert norm.get("target") == "delta_log1p"
    assert pool.policy_action.tolist() == [8, 8, 8]
    # 空文件 / 缺文件 -> 空池（训练入口据此自动关闭系数）
    empty = load_problem_pool(str(tmp_path / "nope.jsonl"))
    assert len(empty) == 0
    with open(tmp_path / "empty.jsonl", "w") as fh:
        fh.write("\n")
    assert len(load_problem_pool(str(tmp_path / "empty.jsonl"))) == 0


def test_problem_obs_batch_soft_label_masking():
    rows = [_row(0, turn=5, tier=3, gold=5, act=(0, 8), weights=(0.7, 0.3)),
            _row(1, turn=6, tier=3, gold=6, act=(30,), weights=(1.0,)),
            _row(2, turn=7, tier=3, gold=7, act=(9,), weights=(1.0,))]
    pool = BoardProblemPool(
        features=np.stack([decode_obs(r["obs"])[0] for r in rows]),
        cards=np.stack([decode_obs(r["obs"])[1] for r in rows]),
        mask=np.stack([decode_obs(r["obs"])[2] for r in rows]),
        turn=np.asarray([r["turn"] for r in rows], np.int16),
        tier=np.asarray([r["state"]["tier"] for r in rows], np.int16),
        gold=np.asarray([r["state"]["gold"] for r in rows], np.int16),
        ref_actions=np.asarray(
            [r["ref"]["actions"] + [-1] * (3 - len(r["ref"]["actions"]))
             for r in rows], np.int16),
        ref_weights=np.asarray(
            [r["ref"]["weights"] + [0.0] * (3 - len(r["ref"]["weights"]))
             for r in rows], np.float32),
        policy_action=np.asarray([r["policy_action"] for r in rows], np.int16),
        strength_before=np.zeros(3, np.float32),
        strength_after=np.ones(3, np.float32),
        strength_target=np.zeros(3, np.float32),
        tier_up=np.ones(3, np.int8),
        bc_valid=np.asarray([True, False, True]),
        aux_valid=np.ones(3, bool),
        tags=[r["tags"] for r in rows],
        norm={"mean": 0.0, "std": 1.0})
    batch = problem_obs_batch(pool, np.arange(3))
    # 行 0：两个参考动作都合法 -> 权重保持
    assert batch.soft[0, 0] == pytest.approx(0.7)
    assert batch.soft[0, 8] == pytest.approx(0.3)
    # 行 1：参考动作 30 不在掩码里 -> 无合法参考 -> bc_valid False
    assert not batch.bc_valid[1]
    assert batch.soft[1].sum() == 0.0
    # 行 2：合法单个参考
    assert batch.bc_valid[2] and batch.ref_top1[2] == 9
    assert np.allclose(batch.soft.sum(axis=1)[[0, 2]], 1.0)


def test_problem_stats_reports_missing_and_tiers():
    rows = [_row(0, turn=5, tier=3, gold=5),
            dict(_row(1, turn=5, tier=3, gold=5),
                 ref={"actions": [], "weights": [], "matched": False,
                      "level": "none", "floor": 0, "support": 0,
                      "mass_legal": 0.0, "reason": "no_support"})]
    stats = problem_stats(rows)
    assert stats["problems"] == 2
    assert stats["ref_matched"] == 1
    assert stats["ref_missing"] == 1
    assert stats["ref_missing_rate"] == pytest.approx(0.5)
    assert stats["ref_level"]["none"] == 1
    assert set(stats["by_tag"]).issubset(set(ALL_TAGS))
    assert stats["strength_norm"]["std"] > 0.0


# ── 7. rollout 出题（需要引擎）────────────────────────────────────────
def _engine_ok():
    from hsbg.az.train.common import engine_available
    return bool(engine_available())


def _tiny_model():
    from hsbg.az.train.entity_model import CardTables, TEXT_DIM, build_entity_net
    tables = CardTables(static=np.zeros((64, 56), np.float32),
                        text=np.zeros((64, TEXT_DIM), np.float32), n_cards=64)
    return build_entity_net(d_model=32, n_layers=1, n_heads=4, dim_ff=64,
                            card_dim=8, tables=tables)


@pytest.mark.skipif(not _engine_ok(), reason="需要 hsbg_engine")
def test_collect_problems_reproducible_and_labels():
    model = _tiny_model()
    cfg = ProblemCollectConfig(games=1, seed=20200, max_steps=20000,
                               human_board_p=0.0, mirror_p=0.0,
                               move_guard=True, move_cap=3,
                               move_repeat_limit=2, max_fork_per_turn=2,
                               min_turn=1, obs_dtype="f32")
    r1 = collect_problems(model, cfg, device="cpu")
    r2 = collect_problems(model, cfg, device="cpu")
    assert len(r1.problems) > 0
    # 同 seed -> 观测指纹/动作/标签完全相同
    assert [p["obs"]["sha256"] for p in r1.problems] == \
           [p["obs"]["sha256"] for p in r2.problems]
    assert [p["policy_action"] for p in r1.problems] == \
           [p["policy_action"] for p in r2.problems]
    assert [p["label"] for p in r1.problems] == [p["label"] for p in r2.problems]
    # 不同 seed -> 不一样
    cfg2 = ProblemCollectConfig(games=1, seed=99999, max_steps=20000,
                                human_board_p=0.0, mirror_p=0.0)
    r3 = collect_problems(model, cfg2, device="cpu")
    assert [p["obs"]["sha256"] for p in r3.problems] != \
           [p["obs"]["sha256"] for p in r1.problems]
    for p in r1.problems:
        assert p["turn"] >= 1                       # 跳过选英雄回合
        assert TURN_START in p["tags"] or p["tags"]  # 每道题至少带一个标签
        lab = p["label"]
        assert lab["available"] == 1
        assert lab["target_turn"] == p["turn"] + 3
        assert lab["tier_up"] == int(lab["tier_after"] >= lab["tier_before"] + 1)
        assert lab["terminal"] == int(not lab["survived"])
        # Move 守卫在生成端生效：题目记录的本回合换位数不会超过 cap
        assert int(p["move"]["n"]) <= 3
    # 统计口径
    stats = r1.stats
    assert stats["problems"] == len(r1.problems)
    assert stats["ref_missing_rate"] == pytest.approx(
        1.0 - stats["ref_match_rate"])
    assert stats["label_available"] + stats["label_missing"] == len(r1.problems)


# ── 8. 强度辅助头离线拟合（CV ridge + 冻结）────────────────────────────
def _rand_problem_rows(n: int = 48, seed: int = 3):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        f = rng.normal(size=OBS_FLOATS).astype(np.float32)
        c = rng.integers(0, 300, size=OBS_CARDS).astype(np.int32)
        m = np.zeros(N_ACTIONS, bool)
        legal = rng.choice(np.arange(0, 80), size=6, replace=False)
        m[legal] = True
        before = float(rng.integers(20, 600))
        after = float(max(0.0, before + rng.normal(120, 160)))
        rows.append({
            "problem_id": f"bp-{i:06d}", "schema": PROBLEM_SCHEMA_VERSION,
            "source_group": "rollout:seed=1:game=0", "game_seed": 1,
            "turn": int(rng.integers(1, 13)), "seat": 0, "decision_idx": 0,
            "tags": [TURN_START],
            "obs": encode_obs(f, c, m, dtype="f32"),
            "state": {"gold": 5, "tier": 3, "strength": int(before)},
            "policy_action": int(legal[0]), "policy_prob": 0.5,
            "ref": {"actions": [int(legal[0])], "weights": [1.0],
                    "matched": True, "level": "turn_tier", "floor": 10000,
                    "support": 100, "mass_legal": 0.5, "reason": "ok"},
            "label": {"strength_before": before, "strength_after_t3": after,
                      "delta": after - before,
                      "delta_log1p": float(np.log1p(after) - np.log1p(before)),
                      "tier_before": 3, "tier_after": int(rng.integers(3, 6)),
                      "tier_up": int(rng.random() > 0.5),
                      "survived": int(i % 9 != 0), "terminal": int(i % 9 == 0),
                      "available": 1, "horizon": 3,
                      "target_turn": int(rng.integers(4, 16))},
            "move": {"last": -1, "n": 0, "counts": []},
        })
    return rows


def test_fit_strength_head_frozen_and_isolated(tmp_path):
    torch = pytest.importorskip("torch")
    from hsbg.az.train.board_problems import fit_strength_head
    from hsbg.az.train.entity_model import (CardTables, TEXT_DIM,
                                            build_entity_net)
    from hsbg.az.train.model import attach_strength_head
    rows = _rand_problem_rows()
    path = str(tmp_path / "p.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    stats = problem_stats(rows)
    from hsbg.az.train.board_problems import ProblemCollectResult
    path, meta_path = write_problems(
        ProblemCollectResult(problems=rows, stats=stats), path)
    pool = load_problem_pool(path)
    assert int(pool.aux_valid.sum()) == sum(
        1 for r in rows if r["label"]["survived"])
    tables = CardTables(static=np.zeros((64, 56), np.float32),
                        text=np.zeros((64, TEXT_DIM), np.float32), n_cards=64)
    model = build_entity_net(d_model=32, n_layers=1, n_heads=4, dim_ff=64,
                             card_dim=8, tables=tables)
    attach_strength_head(model, norm=pool.norm)
    before = {k: v.detach().clone() for k, v in model.state_dict().items()}
    rep = fit_strength_head(model, pool, device="cpu")
    assert rep["n"] == int(pool.aux_valid.sum())
    assert rep["folds"] >= 2 and np.isfinite(rep["cv_mse"])
    assert rep["frozen"] and 0.0 < rep["ridge"]
    assert np.isfinite(rep["pearson_delta"])
    # 冻结：头不参与训练
    assert all(not prm.requires_grad for prm in model.strength_head.parameters())
    # 只有 strength_head.* 变化，其余权重逐位不变
    for k, v in before.items():
        now = model.state_dict()[k]
        if k.startswith("strength_head."):
            assert not torch.equal(v, now), k
        else:
            assert torch.equal(v, now), k
    # 幂等：重拟合得到同一组权重
    w1 = model.strength_head.weight.detach().clone()
    fit_strength_head(model, pool, device="cpu")
    assert torch.allclose(w1, model.strength_head.weight, atol=1e-6)


def test_fit_strength_head_requires_pool_labels(tmp_path):
    from hsbg.az.train.board_problems import fit_strength_head
    from hsbg.az.train.entity_model import (CardTables, TEXT_DIM,
                                            build_entity_net)
    from hsbg.az.train.model import attach_strength_head
    tables = CardTables(static=np.zeros((64, 56), np.float32),
                        text=np.zeros((64, TEXT_DIM), np.float32), n_cards=64)
    model = build_entity_net(d_model=32, n_layers=1, n_heads=4, dim_ff=64,
                             card_dim=8, tables=tables)
    rows = _rand_problem_rows(12)
    stats = problem_stats(rows)
    path, _ = write_problems(
        ProblemCollectResult(problems=rows, stats=stats),
        str(tmp_path / "p.jsonl"))
    pool = load_problem_pool(path)
    pool.aux_valid[:] = False
    attach_strength_head(model, norm=pool.norm)
    with pytest.raises(ValueError):
        fit_strength_head(model, pool, device="cpu")


def test_strength_after_from_delta():
    from hsbg.az.train.board_problems import (denormalize_strength,
                                              strength_after_from_delta)
    norm = {"mean": 1.0, "std": 0.5}
    z = np.asarray([0.0, 1.0])
    delta = denormalize_strength(z, norm)
    assert np.allclose(delta, [1.0, 1.5])
    after = strength_after_from_delta(z, np.asarray([100.0, 100.0]), norm)
    assert np.allclose(after, np.expm1(np.log1p(100.0)
                                       + np.asarray([1.0, 1.5])), rtol=1e-5)
