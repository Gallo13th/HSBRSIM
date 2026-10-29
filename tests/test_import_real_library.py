"""``scripts/import_real_library.py`` 单测：质量门 / 卡表映射 / 去重 / 强度 / turn 分桶。

只用 8 行合成 jsonl，不依赖 621 MB 真实观测。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "import_real_library", ROOT / "scripts" / "import_real_library.py")
irl = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = irl  # dataclass 需要模块已在 sys.modules
_SPEC.loader.exec_module(irl)


CARDS = {
    "meta": {"client_version": "test", "count": 5},
    "cards": [
        {"id": "AAA"},   # 0
        {"id": "BBB"},   # 1
        {"id": "CCC"},   # 2
        {"id": "HERO_1"},  # 3（皮肤 id 归一到它）
        {"id": "DDD"},   # 4
    ],
}


def _minion(card_id, atk, hp, pos):
    return {"card_id": card_id, "attack": atk, "health": hp,
            "damage": 0, "position": pos}


def _row(turn, board, *, ready=True, complete=True, game_id=None, heroes=None,
         hand=None, **extra):
    row = {
        "game_id": game_id or f"g{turn}",
        "turn": turn,
        "board": board,
        "known_hand": hand or [],
        "heroes": heroes or [],
        "build_number": 123456,
        "stage": "recruitment_end_at_phase_switch",
        "split": "train",
        "perspective": "self",
        "controller": 3,
        "combat_index": 1,
        "quality_flags": [],
    }
    if ready is not None:
        row["library_ready"] = ready
    if complete is not None:
        row["hidden_counters_complete"] = complete
    row.update(extra)
    return row


@pytest.fixture()
def dataset(tmp_path):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(CARDS), encoding="utf-8")
    obs = tmp_path / "obs"
    obs.mkdir()
    rows = [
        # 1) 合法，turn 5，强度 2+3 + 1+1 = 7；英雄皮肤归一；手牌映射
        _row(5, [_minion("AAA", 2, 3, 1), _minion("BBB", 1, 1, 2)],
             game_id="g1", heroes=[{"card_id": "HERO_1_SKIN_X"}],
             hand=[{"card_id": "CCC"}]),
        # 2) 同 turn 同 board（顺序不同）-> 去重
        _row(5, [_minion("BBB", 1, 1, 2), _minion("AAA", 2, 3, 1)],
             game_id="g2"),
        # 3) 同 board 但 turn 不同 -> 保留（按 turn 分桶）
        _row(6, [_minion("AAA", 2, 3, 1), _minion("BBB", 1, 1, 2)],
             game_id="g3"),
        # 4) 质量门：hidden_counters_complete=false
        _row(7, [_minion("CCC", 3, 3, 1)], complete=False, game_id="g4"),
        # 5) 卡表映射失败 -> fail-closed
        _row(8, [_minion("ZZZ_404", 1, 1, 1)], game_id="g5"),
        # 6) 两个质量字段都缺失
        _row(9, [_minion("CCC", 4, 4, 1)], ready=None, complete=None,
             game_id="g6"),
        # 7) attack=None -> 结构不完整
        _row(10, [{"card_id": "DDD", "attack": None, "health": 5,
                   "position": 1}], game_id="g7"),
        # 8) 只缺 library_ready
        _row(11, [_minion("AAA", 5, 5, 1)], ready=None, game_id="g8"),
    ]
    path = obs / "synthetic.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return obs, cards


def test_card_index_and_hero_skin_mapping():
    index, meta = irl.load_card_index(
        ROOT / "rust" / "crates" / "hsbg-engine" / "data" / "cards.json")
    # 整数索引 == cards 数组下标（与 Rust CardId 一致）
    assert isinstance(index["BG31_803"], int)
    assert meta["count"] == len(index) > 3000
    # 合成表语义
    idx = {"AAA": 0, "HERO_1": 3}
    assert irl.map_hero("HERO_1", idx) == (3, "direct")
    assert irl.map_hero("HERO_1_SKIN_X", idx) == (3, "skin_base")
    assert irl.map_hero("NOPE_SKIN_X", idx) == (None, "unmapped")
    assert irl.map_hero(None, idx) == (None, "none")


def test_strict_import_gate_mapping_dedup_strength_and_turns(dataset):
    obs, cards = dataset
    entries, stats = irl.run_import(obs, cards)

    # 只有 turn 5 / turn 6 两条通过严格门；turn 5 的第二条被去重
    assert stats["rows"]["total"] == 8
    assert stats["rows"]["kept"] == 2
    assert [e.turn for e in entries] == [5, 6]
    assert [e.strength for e in entries] == [7, 7]
    assert entries[0].board == [
        {"card": 0, "atk": 2, "hp": 3, "position": 1},
        {"card": 1, "atk": 1, "hp": 1, "position": 2},
    ]
    assert entries[0].hero == 3
    assert entries[0].hero_card_id == "HERO_1_SKIN_X"
    assert entries[0].known_hand == [{"card": 2, "card_id": "CCC"}]
    assert entries[0].source == "real_10k"
    assert entries[0].quality == "ready"
    assert entries[0].degraded_reasons == []

    # turn / 强度分桶
    assert stats["turns"] == {"5": 1, "6": 1}
    assert stats["strength"]["p50"] == 7.0
    assert stats["strength"]["p90"] == 7.0
    assert stats["per_turn_strength"]["5"]["p50"] == 7.0

    # 丢弃原因
    dr = stats["drop_reasons"]
    assert dr["duplicate"] == 1
    assert dr["hidden_counters_incomplete"] == 1
    assert dr["unmapped_card"] == 1
    assert dr["missing_library_ready"] == 2
    assert dr["incomplete_stats"] == 1
    assert stats["gate_failures"]["hidden_counters_incomplete"] == 1
    assert stats["gate_failures"]["missing_hidden_counters_complete"] == 1

    # 卡表映射失败率：11 张随从里 1 张 ZZZ_404
    m = stats["mapping"]
    assert m["minions_seen"] == 11
    assert m["unmapped_minion_occurrences"] == 1
    assert m["rows_with_unmapped_minion"] == 1
    assert m["mapping_failure_rate"] == pytest.approx(1 / 11)
    assert m["unmapped_unique_card_ids"] == [{"card_id": "ZZZ_404", "count": 1}]
    assert m["hero_via_skin_base"] == 1
    assert m["hero_direct"] == 0
    assert m["known_hand_unmapped"] == 0


def test_relaxed_mode_marks_degraded_but_still_fail_closed(dataset):
    obs, cards = dataset
    entries, stats = irl.run_import(obs, cards, allow_unready=True)

    assert stats["config"]["quality_gate"] == "relaxed"
    # turn 5/6/7/9/11 保留；turn 8 卡映射失败、turn 10 数值缺失仍丢弃
    assert [e.turn for e in entries] == [5, 6, 7, 9, 11]
    assert stats["rows"]["kept"] == 5
    degraded = {e.turn: e for e in entries if e.quality == "degraded"}
    assert set(degraded) == {7, 9, 11}
    assert degraded[7].degraded_reasons == ["hidden_counters_incomplete"]
    assert set(degraded[9].degraded_reasons) == {
        "missing_library_ready", "missing_hidden_counters_complete"}
    assert degraded[11].degraded_reasons == ["missing_library_ready"]
    assert all(e.quality == "ready" for e in entries if e.turn in (5, 6))

    # 放宽模式丢弃原因只算结构问题
    assert stats["drop_reasons"] == {
        "duplicate": 1, "unmapped_card": 1, "incomplete_stats": 1}
    # 强度 [6, 7, 7, 8, 10]
    assert stats["strength"]["p50"] == 7.0
    assert stats["strength"]["p90"] == pytest.approx(9.2)


def test_limit_and_min_board(dataset):
    obs, cards = dataset
    entries, stats = irl.run_import(obs, cards, limit=2)
    assert stats["rows"]["total"] == 2
    assert stats["rows"]["kept"] == 1          # 第 2 行同 turn 同签名去重
    assert entries[0].turn == 5

    # 空牌面在 min_board=1 下被结构校验丢弃（不依赖额外行）
    index, _ = irl.load_card_index(cards)
    snap, failures, _ = irl.parse_snapshot(
        {"turn": 1, "board": [], "library_ready": True,
         "hidden_counters_complete": True},
        card_index=index, min_board=1)
    assert snap is None
    assert "board_too_small" in failures


def test_parse_snapshot_reports_missing_gate_fields():
    index, _ = irl.load_card_index(ROOT / "rust" / "crates" / "hsbg-engine"
                                   / "data" / "cards.json")
    snap, failures, metrics = irl.parse_snapshot(
        {"turn": 5, "board": [{"card_id": "BG31_803", "attack": 1,
                               "health": 2, "position": 1}]},
        card_index=index)
    assert snap is None
    assert "missing_library_ready" in failures
    assert "missing_hidden_counters_complete" in failures
    assert metrics["board_minions"] == 1
