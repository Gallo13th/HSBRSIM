"""官方 GameTag/CardType/Zone/Race 枚举 vs 引擎 tags.py 的差异测试。

依赖 `python tools/rea_net_extract.py`（Mono.Cecil 提取 Assembly-CSharp 枚举）
与 `python tools/rea_tag_compare.py`（生成 reversed/tag_diff.{md,json}）。
产物缺失 → skip；不在测试里联网/反编译（避免拖慢 CI）。

运行:
    python -m pytest tests/test_official_tags.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENUMS = ROOT / "reversed" / "net" / "Assembly-CSharp" / "enums.json"
KEY_ENUMS = ROOT / "reversed" / "net" / "key_enums.json"
REPORT_JSON = ROOT / "reversed" / "tag_diff.json"
REPORT_MD = ROOT / "reversed" / "tag_diff.md"

pytestmark = pytest.mark.skipif(
    not REPORT_JSON.exists(),
    reason="缺少 reversed/tag_diff.json（先跑 rea_net_extract.py + rea_tag_compare.py）")


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def key_enums() -> dict:
    if not KEY_ENUMS.exists():
        pytest.skip("缺少 reversed/net/key_enums.json")
    return json.loads(KEY_ENUMS.read_text(encoding="utf-8-sig"))


def test_report_files_and_summary(report):
    assert REPORT_MD.exists()
    g = report["game_tag"]
    assert g["official_count"] == 1214, "官方 GAME_TAG 成员数应为 1214"
    assert 100 <= g["engine_count"] <= 200
    assert g["name_matched"] >= 30
    assert g["value_mismatch_count"] >= 10
    assert g["official_only_count"] > 1000
    assert g["engine_only_count"] > 80
    assert g["engine_only_numeric_collision_count"] > 30
    md = REPORT_MD.read_text(encoding="utf-8")
    assert "GameTag" in md and "数值撞号" in md


def test_official_key_tag_values(key_enums):
    """官方协议数值断言（B 步提取结果的硬事实）。"""
    g = key_enums["game_tag"]["values"]
    expected = {
        "CARDTYPE": 202, "ATK": 47, "HEALTH": 45, "COST": 48, "ZONE": 49,
        "TAUNT": 190, "DIVINE_SHIELD": 194, "WINDFURY": 189,
        "DEATHRATTLE": 217, "BATTLECRY": 218, "POISONOUS": 363,
        "REBORN": 1085, "VENOMOUS": 2853, "MAGNETIC": 849,
        "TECH_LEVEL": 1440, "BACON_EVOLUTION_CARD_ID": 2519,
        "ENTITY_ID": 53, "IMMUNE": 240, "STEALTH": 191, "SILENCED": 188,
        "MEGA_WINDFURY": 1207, "FROZEN": 260, "EXHAUSTED": 43,
        "IMMUNE_WHILE_ATTACKING": 373, "DARK_GIFT": 3627,
        "BONUS_KEYWORDS": 3423, "CHOOSE_ONE": 443, "CHOOSE_BOTH": 419,
    }
    for name, value in expected.items():
        assert g.get(name) == value, f"官方 GAME_TAG.{name} 期望 {value}"


def test_value_mismatches_are_pinned(report):
    """引擎同名但数值错的 tag：固定清单，回归时必须同步。"""
    names = {m["name"] for m in report["game_tag"]["value_mismatches"]}
    expected = {"ENTITY_ID", "STEALTH", "SILENCED", "MEGA_WINDFURY",
                "FROZEN", "EXHAUSTED", "IMMUNE_WHILE_ATTACKING",
                "DARK_GIFT", "BONUS_KEYWORDS", "CHOOSE_ONE", "CHOOSE_BOTH"}
    assert expected <= names, f"缺失的同名数值差异: {expected - names}"


def test_other_enums_diff(report):
    o = report["other_enums"]
    # CardType：值全对，只是命名不同（BACON_* vs BATTLEGROUND_*）
    assert o["card_type"]["value_mismatch_count"] == 0
    # Zone：引擎自定义了 TAVERN，且 HAND/SETASIDE/REMOVED 数值与官方不同
    assert o["zone"]["value_mismatch_count"] == 3
    assert "TAVERN" in {x["name"] for x in o["zone"]["engine_only"]}
    # Race：值全对（只是 MECH vs MECHANICAL 命名）
    assert o["race"]["value_mismatch_count"] == 0
    # SpellSchool 官方 14 项（引擎未定义枚举；数据层用裸 int）
    assert "LESSER_TRINKET" in o["spell_school"]["values"]
    assert o["spell_school"]["values"]["GREATER_TRINKET"] == 12


def test_tool_regenerates_report(tmp_path):
    """`rea_tag_compare.py` 在已有提取物时必须可重复生成报告（退出码 0）。"""
    if not ENUMS.exists():
        pytest.skip("缺少 enums.json")
    path = ROOT / "tools" / "rea_tag_compare.py"
    spec = importlib.util.spec_from_file_location("rea_tag_compare", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "tag_diff.md"
    js = tmp_path / "tag_diff.json"
    rc = mod.main(["--out", str(out), "--json", str(js)])
    assert rc == 0
    assert out.exists() and js.exists()
    d = json.loads(js.read_text(encoding="utf-8"))
    assert d["game_tag"]["official_count"] == 1214


def test_engine_tags_importable():
    """引擎 tags.py 仍可导入（防止对比工具改动引入语法错误）。"""
    from hsrl2.tags import CardType, GameTag, Race, Zone
    assert int(GameTag.ATK) == 47
    assert int(CardType.MINION) == 4
    assert int(Zone.PLAY) == 1
    assert int(Race.MURLOC) == 14
