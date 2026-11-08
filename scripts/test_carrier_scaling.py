"""缩放载体识别 / 教师合法性 / 指标门的单测（纯 CPU）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import carrier_common as C  # noqa: E402

# 池内 + 已实现 + tier<=6 的 11 张主集合（普通形态）
EXPECTED_PRIMARY_NORMAL = {
    "BG36_762", "BG28_707", "BG28_633", "BG36_704", "BG28_741",
    "BG27_005", "BG34_692", "BG36_703", "BG36_853", "BG36_640",
    "BG36_108",
}


def test_catalog_primary_set():
    cat = C.build_catalog(use_engine=True)
    emap = C.entry_map(cat)
    prim_norm = {cid for cid in cat["primary_ids"]
                 if not (emap.get(cid) or {}).get("golden")}
    assert prim_norm == EXPECTED_PRIMARY_NORMAL
    # 金色 id 也被登记（同 id + _G），且主集合 id 数 = 2×
    assert len(cat["primary_ids"]) == 22
    for cid in EXPECTED_PRIMARY_NORMAL:
        e = emap[cid]
        assert e["in_tavern_pool"] and e["implemented"]
        assert 1 <= e["tier"] <= 6
        assert e["trigger"] in ("cast_on_self", "cast_on_race", "cast_tavern",
                                "after_n_spells")
        assert e["golden_id"], cid
        assert e["expected_sigma_per_cast"] is not None, cid


def test_catalog_excludes_unreachable_and_tier7():
    cat = C.build_catalog(use_engine=True)
    emap = C.entry_map(cat)
    # 旧文档的 5 张里有两张其实池外
    assert emap["BG36_510"]["exclude_reason"] == "not_implemented"
    assert not emap["BG36_510"]["is_primary"]
    assert emap["BG36_921"]["exclude_reason"] == "not_in_tavern_pool"
    # tier7 不进普通酒馆
    assert emap["BG36_111"]["exclude_reason"] == "tier7_only"
    # 死亡之声改进型不是载体
    assert emap["BG36_318"]["exclude_reason"] == "no_permanent_growth"


def test_narrow_ids_are_doc_set():
    cat = C.build_catalog(use_engine=True)
    assert set(cat["narrow_ids"]) == set(C.NARROW_IDS)
    assert len(cat["narrow_ids"]) == 12


def test_legacy_cid_mapping_is_1_based():
    """旧 rollout 的 ``board_cards`` 是 0-based cid；映射必须 +1（不是错位一张）。"""
    hsbg_engine = pytest.importorskip("hsbg_engine")
    cat = C.build_catalog(use_engine=True)
    # 2968 是 BG36_853 的 0-based cid
    cat_json = json.loads(hsbg_engine.catalog_json())
    cid2id = {int(c["cid"]): str(c["id"]) for c in cat_json}
    assert cid2id[2968] == "BG36_853"
    # 旧脚本的 card_info(2968) 错位一张；正确是 card_info(2969)
    assert hsbg_engine.card_info(2968)[0] != "BG36_853"
    assert hsbg_engine.card_info(2969)[0] == "BG36_853"
    rows = [{"seed": 1, "turns": [
        {"turn": 5, "strength": 100, "tier": 3, "board_cards": ["2968"]},
    ]}]
    out = __import__("carrier_audit").adapt_legacy(rows, cat)
    assert out[0]["turns"][0]["board_carriers"] == ["BG36_853"]


def test_parse_log_casts():
    log = [
        "[t3] p0 casts Tavern Dish Banana on Devilish Distractor",
        "[t3] p0 casts Shiny Ring",
        "[t3] p0 casts Hired Headhunter on Twilight Tidehunter (tavern)",
        "[t3] p1 casts Shiny Ring",
    ]
    casts = C.parse_log_casts(log, seat=0)
    assert len(casts) == 3
    assert casts[0]["target"] == "Devilish Distractor"
    assert casts[0]["target_zone"] == "board"
    assert casts[1]["target"] is None
    assert casts[2]["target_zone"] == "tavern"


def test_gate_check_shape():
    summ = {
        "carrier": {"carrier_encounter_rate": 0.3},
        "strength12": {"all": {"p50": 1200.0}},
        "corr_carrier_turns_str12": {"pearson": 0.2},
    }
    g = C.gate_check(summ)
    assert g["carrier_ok"] and g["str12_ok"] and g["corr_ok"] and g["all_ok"]
    summ2 = {
        "carrier": {"carrier_encounter_rate": 0.1},
        "strength12": {"all": {"p50": 100.0}},
        "corr_carrier_turns_str12": {"pearson": -0.1},
    }
    assert not C.gate_check(summ2)["all_ok"]


def test_teacher_actions_are_legal():
    hsbg_engine = pytest.importorskip("hsbg_engine")
    from carrier_teacher import CarrierTeacher
    from hsbg.az.train.common import mask_from_bytes

    teacher = CarrierTeacher()
    game = hsbg_engine.Game(123456)
    teacher.reset()
    n = 0
    while not game.is_over() and n < 400:
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            n += 1
            if p == 0:
                view = json.loads(game.view(0))
                mask = mask_from_bytes(game.legal_mask(0))
                a = int(teacher.decide_view(view, mask))
                assert 0 <= a < 245 and bool(mask[a]), f"illegal action {a}"
                game.step(0, a)
            else:
                game.bot_play(p)
        if not acted:
            break
    assert n > 0
    meta = teacher.meta()
    assert meta.get("illegal_first_choice", 0) == 0
    assert meta.get("fallbacks", 0) == 0
