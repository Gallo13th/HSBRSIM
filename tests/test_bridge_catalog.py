"""AgenticAssistant catalog 适配器与引擎数据差异统计测试。

文件是只读发行包的一部分；缺失时自动 skip（不阻塞无发行包的环境）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsbg.bridge import catalog as catalog_mod
from hsbg.bridge.catalog import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_ENGINE_DATA_DIR,
    ENGINE_DATA_FILES,
    AACatalog,
    compare_with_engine_data,
    load_catalog,
    write_diff_json,
)

pytestmark = pytest.mark.skipif(
    not DEFAULT_CATALOG_PATH.is_file(),
    reason=f"AgenticAssistant catalog.json 不存在: {DEFAULT_CATALOG_PATH}",
)

ENGINE_READY = (DEFAULT_ENGINE_DATA_DIR / "bg_cards.json").is_file()


# ══════════════════════════════════════════════════════════════════════
# 加载 / 查询
# ══════════════════════════════════════════════════════════════════════


def test_catalog_version_and_counts() -> None:
    cat = load_catalog()
    assert cat.version == "36.6.3.253932"
    assert cat.card_count == 3983
    assert len(cat.skins) == 653
    kinds = cat.kind_counts()
    assert kinds["minion"] == 2596
    assert kinds["spell"] == 297
    assert kinds["hero"] == 143
    assert kinds["hero_power"] == 176
    assert kinds["trinket_lesser"] == 201
    assert kinds["trinket_greater"] == 219
    assert kinds["tavern_spell"] == 208
    assert kinds["quest_reward"] == 73
    assert kinds["dark_gift"] == 47
    assert kinds["quest"] == 23
    summary = cat.summary()
    assert summary["game_version"] == cat.version
    assert summary["golden_variant_count"] > 0


def test_get_by_id_and_dbf() -> None:
    cat = load_catalog()
    card = cat.get("AT_121")
    assert card is not None
    assert card.kind == "minion"
    assert card.name == "Crowd Favorite"
    assert card.name_zh == "人气选手"
    assert card.tier == 3
    assert card.dbf == 2518
    assert cat.get("不存在_卡_001") is None
    by_dbf = cat.from_dbf(2518)
    assert by_dbf is not None and by_dbf.id == "AT_121"
    assert cat.name("AT_121") == "Crowd Favorite"
    assert cat.name("AT_121", zh=True) == "人气选手"


def test_canonical_folds_golden_and_skins() -> None:
    cat = load_catalog()
    assert cat.is_golden("BG19_010_G") is True
    assert cat.canonical("BG19_010_G") == "BG19_010"
    assert cat.is_golden("BG19_010") is False
    # 皮肤 -> 本体英雄
    skin_id, hero_id = next(iter(cat.skins.items()))
    assert cat.canonical(skin_id) == hero_id
    # 未知 id 原样返回
    assert cat.canonical("NOT_A_CARD") == "NOT_A_CARD"
    canonical_cards = cat.canonical_cards
    assert len(canonical_cards) < cat.card_count  # 金色变体被折叠


def test_by_kind_and_search() -> None:
    cat = load_catalog()
    minions = cat.by_kind("minion")
    assert len(minions) == cat.kind_counts()["minion"]
    assert all(card.kind == "minion" for card in minions)
    assert cat.by_kind("不存在的类型") == ()
    hits = cat.search("Alleycat", limit=5)
    assert hits and all("alleycat" in (c.name + c.name_zh + c.id).casefold() for c in hits)
    assert cat.search("Alleycat", limit=0) == []


def test_missing_catalog_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        AACatalog(tmp_path / "nope.json")
    with pytest.raises(FileNotFoundError):
        load_catalog(tmp_path / "nope.json")


# ══════════════════════════════════════════════════════════════════════
# 差异统计
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not ENGINE_READY, reason="引擎 data/bg_cards.json 不存在")
def test_compare_structure_and_internal_consistency() -> None:
    diff = compare_with_engine_data(include_timestamp=False)
    assert diff["schema"] == "hsbg.real_game_data_diff.v1"
    assert diff["catalog"]["game_version"] == "36.6.3.253932"
    # 37.0.0（build 255130）数据升级后引擎 patch 已前移；catalog 仍是
    # 36.6.3 发行包（对照组不可变）。
    assert diff["engine"]["patch"].startswith("37.0.0")

    overall = diff["overall"]
    cat_total = overall["catalog_canonical_count"]
    eng_total = overall["engine_canonical_count"]
    inter = overall["id_intersection"]
    # 折叠金色变体后：canonical = exact - golden
    assert cat_total == overall["catalog_exact_count"] - overall["catalog_golden_variant_count"]
    assert inter + overall["only_catalog_count"] == cat_total
    assert inter + overall["only_engine_count"] == eng_total
    assert overall["only_catalog_count"] > 0  # 线上比本地新
    assert overall["only_engine_count"] >= 0

    # by_kind 的 matched + engine_missing 必须等于 catalog_canonical
    for kind, row in diff["by_kind"].items():
        assert row["matched"] + row["engine_missing"] == row["catalog_canonical"], kind
        assert row["catalog_cards"] >= row["catalog_canonical"], kind

    # 列表长度与计数一致
    assert len(diff["only_catalog"]["ids"]) == overall["only_catalog_count"]
    assert len(diff["only_engine"]["ids"]) == overall["only_engine_count"]
    assert set(diff["only_catalog"]["ids"]) & set(diff["only_engine"]["ids"]) == set()

    # 引擎文件确实被读到
    assert "bg_cards.json" in diff["engine"]["file_counts"]
    assert set(diff["engine"]["file_counts"]) <= set(ENGINE_DATA_FILES)


@pytest.mark.skipif(not ENGINE_READY, reason="引擎 data/bg_cards.json 不存在")
def test_bg36_new_cards_are_detected() -> None:
    """37.0（build 255130）数据升级后，引擎已覆盖 catalog 的全部 BG36 卡。

    升级前（36.2.2 引擎）本测试验证新卡**缺失**可被差分发现；
    现改为反向守卫：catalog（36.6.3）的 BG36 族必须 100% 被引擎覆盖，
    差分器对"新卡"的识别能力由 `catalog_count > 0` + `matched` 结构保证。
    """
    diff = compare_with_engine_data(include_timestamp=False)
    bg36 = diff["new_cards_suspect"]["BG36"]
    assert bg36["catalog_count"] > 0
    assert bg36["engine_missing"] == 0, bg36["missing_ids"][:10]
    assert bg36["matched"] == bg36["catalog_count"]
    assert bg36["missing_ids"] == []
    # 引擎数据比 catalog 新 → only_engine 非空（差分方向翻转，仍可检出差异）
    assert diff["overall"]["only_engine_count"] > 0


@pytest.mark.skipif(not ENGINE_READY, reason="引擎 data/bg_cards.json 不存在")
def test_field_diff_sections_are_present_and_serializable() -> None:
    diff = compare_with_engine_data(include_timestamp=False, sample_limit=3)
    fields = diff["field_diffs"]
    for key in (
        "name_mismatches",
        "dbf_mismatches",
        "tier_mismatches",
        "race_mismatches",
        "keyword_mismatches",
        "dbf_id_changes",
    ):
        assert key in fields
        assert isinstance(fields[key]["count"], int)
        assert len(fields[key]["samples"]) <= 3
    assert fields["keyword_mismatches"]["checked_pairs"] > 0
    assert diff["catalog_keyword_coverage"]["unmapped_keywords"]
    assert diff["notes"]
    # 整个结果必须可 JSON 序列化（UTF-8 落盘前提）
    text = json.dumps(diff, ensure_ascii=False)
    assert "36.6.3.253932" in text
    # 不含未序列化的 tuple / set
    assert json.loads(text)["overall"]["only_catalog_count"] == diff["overall"]["only_catalog_count"]


@pytest.mark.skipif(not ENGINE_READY, reason="引擎 data/bg_cards.json 不存在")
def test_write_diff_json(tmp_path: Path) -> None:
    out = tmp_path / "diff.json"
    path = write_diff_json(out, sample_limit=2)
    assert path == out and out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["catalog"]["card_count"] == 3983
    assert "generated_at_utc" in data
    # 默认输出位置常量指向 runs/
    assert catalog_mod.DEFAULT_DIFF_OUT.name == "data_diff_36.6.3.json"


def test_engine_data_files_exist() -> None:
    if not ENGINE_READY:
        pytest.skip("引擎数据不存在")
    for filename in ENGINE_DATA_FILES:
        assert (DEFAULT_ENGINE_DATA_DIR / filename).is_file(), filename
