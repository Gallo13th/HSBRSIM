"""rizling 发行包版本跟踪 / 卡池对齐统计测试。

真实包（`reversed/rizling_latest/`）缺失时，真实包相关用例自动 skip；
合成包用例只依赖本文件构造的 JSON/二进制样例。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsbg.bridge.rizling import (
    compare_catalogs,
    compare_catalog_with_project,
    compare_game_tags,
    compare_game_tags_with_official,
    compare_packages,
    compare_versions,
    detect_version_signals,
    package_summary,
    parse_version,
    pool_alignment,
    read_product_db,
    read_readme_rule_version,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "reversed" / "rizling_latest"
LOCAL_DIR = ROOT / "AgenticAssistant"
PROJECT_DATA = ROOT / "data"
OFFICIAL_ENUMS = ROOT / "reversed" / "net" / "Assembly-CSharp" / "enums.json"
PRODUCT_DB = Path(r"C:\Program Files (x86)\Hearthstone\.product.db")
STATIC_ANALYSIS = REAL_DIR / "STATIC_ANALYSIS.json"

HAS_REAL_PACKAGE = (
    (REAL_DIR / "release-manifest.json").is_file()
    and (REAL_DIR / "bgassistant" / "data" / "catalog.json").is_file()
    and (REAL_DIR / "bgcontroller" / "data" / "game_tags.json").is_file()
)
SKIP_REAL = pytest.mark.skipif(
    not HAS_REAL_PACKAGE, reason="reversed/rizling_latest/ 真实发行包不存在"
)


# ══════════════════════════════════════════════════════════════════════
# 合成样例工具
# ══════════════════════════════════════════════════════════════════════


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def _card(card_id: str, **overrides) -> dict:
    card = {
        "id": card_id,
        "dbf": 1,
        "kind": "minion",
        "name": "Card " + card_id,
        "name_zh": "卡 " + card_id,
        "tier": 1,
        "races": [],
        "keywords": [],
        "normal": "",
        "activatable": False,
        "activation_cost": 0,
    }
    card.update(overrides)
    return card


def _make_package(
    base: Path,
    *,
    version: str,
    game_version: str | None,
    cards: list,
    enums: dict,
    readme: str = "",
    built: str = "20260101-000000",
    layout: str = "rizling",
) -> Path:
    """构造一个最小发行包目录（rizling 布局或本地 0.5.3 布局）。"""
    if layout == "rizling":
        catalog_rel = "bgassistant/data/catalog.json"
        tags_rel = "bgcontroller/data/game_tags.json"
    else:  # 本地 0.5.3：代码在 _internal 下
        catalog_rel = "_internal/bgassistant/data/catalog.json"
        tags_rel = "_internal/bgcontroller/data/game_tags.json"
    _write_json(
        base / "release-manifest.json",
        {
            "version": version,
            "built": built,
            "game_version": game_version,
            "files": {"dummy.bin": "00"},
            "client_sources": ["__main__.py", "reader.py"],
            "bundled_project_modules": ["bgassistant", "bgcontroller"],
            "offline_smoke": {"version": version},
        },
    )
    _write_json(
        base / catalog_rel,
        {
            "game_version": game_version or "36.6.3.253932",
            "pool_scope": "solo_snapshot",
            "cards": cards,
            "skins": {},
        },
    )
    _write_json(
        base / tags_rel,
        {
            "source": "synthetic",
            "commit": "deadbeef",
            "enums": enums,
        },
    )
    if readme:
        (base / "使用说明.txt").write_text(readme, encoding="utf-8")
    return base


def _mini_data_dir(base: Path) -> Path:
    """构造一个最小的项目 data/ 目录（bg_cards + 池 + summary）。"""
    _write_json(
        base / "bg_cards.json",
        [
            {"id": "BG_TEST_001", "dbf_id": 1, "name": "Card BG_TEST_001",
             "card_type": 4, "atk": 3, "health": 4, "tech_level": 1, "cost": 3},
            {"id": "BG_TEST_002", "dbf_id": 2, "name": "Card BG_TEST_002",
             "card_type": 5, "cost": 3, "tech_level": 2},
        ],
    )
    _write_json(base / "bg_pool_minions.json", [{"id": "BG_TEST_001"}])
    _write_json(base / "bg_pool_spells.json", [{"id": "BG_TEST_002"}])
    _write_json(base / "bg_heroes.json", [])
    _write_json(base / "bg_summary.json", {"patch": "37.0.0.255130"})
    return base


# ══════════════════════════════════════════════════════════════════════
# 版本解析 / .product.db
# ══════════════════════════════════════════════════════════════════════


def test_parse_version_variants() -> None:
    assert parse_version("0.6.1") == (0, 6, 1)
    assert parse_version("0.5.3") == (0, 5, 3)
    assert parse_version("37.0.0.255130.254477") == (37, 0, 0, 255130, 254477)
    assert parse_version("36.6.3.253932") == (36, 6, 3, 253932)
    assert parse_version(None) == ()
    assert parse_version("no-version") == ()
    assert compare_versions("0.6.1", "0.5.3") > 0
    assert compare_versions("37.0.0.255130", "36.6.3.253932") > 0
    assert compare_versions("0.5.3", "0.5.3") == 0


def test_read_product_db_synthetic(tmp_path: Path) -> None:
    fake = tmp_path / ".product.db"
    fake.write_bytes(
        b"\x0a\x07hs_beta\x12\x03hsb\x1a\x53"
        + b"\x22\x61" + b"37.0.0.255130.254477"
        + b"\x00\xff"
    )
    info = read_product_db(fake)
    assert info is not None
    assert info["version"] == "37.0.0.255130"
    assert info["build"] == 255130
    assert info["revision"] == 254477
    assert read_product_db(tmp_path / "missing.db") is None


def test_read_readme_rule_version(tmp_path: Path) -> None:
    old = tmp_path / "old" / "使用说明.txt"
    old.parent.mkdir(parents=True)
    old.write_text("……\n当前规则版本 36.6.3.253932 单人酒馆；游戏升级后需同步更新解析和服务规则。\n",
                   encoding="utf-8")
    assert read_readme_rule_version(old) == "36.6.3.253932"
    new = tmp_path / "new" / "使用说明.txt"
    new.parent.mkdir(parents=True)
    new.write_text("Agentic 酒馆助手 0.6.1 使用说明\n\n没有版本行。\n", encoding="utf-8")
    assert read_readme_rule_version(new) is None


# ══════════════════════════════════════════════════════════════════════
# 包概况 / 包间差异
# ══════════════════════════════════════════════════════════════════════


def test_package_summary_synthetic(tmp_path: Path) -> None:
    base = _make_package(
        tmp_path / "pkg",
        version="0.6.1",
        game_version="36.6.3.253932",
        cards=[_card("BG_A", atk=1, hp=1), _card("BG_B", kind="spell", cost=3)],
        enums={"GameTag": {"ATK": 47}, "CardType": {"MINION": 4}},
        readme="当前规则版本 36.6.3.253932",
    )
    summary = package_summary(base, local_root=tmp_path / "nope")
    assert summary["manifest"]["version"] == "0.6.1"
    assert summary["manifest"]["game_version"] == "36.6.3.253932"
    assert summary["catalog"]["card_count"] == 2
    assert summary["catalog"]["has_stats"] is True
    assert summary["readme_rule_version"] == "36.6.3.253932"
    assert summary["rule_version_signal"]["manifest_game_version"] == "36.6.3.253932"
    json.dumps(summary)  # 必须可序列化


def test_compare_packages_synthetic(tmp_path: Path) -> None:
    old_cards = [_card("BG_A", name="A old"), _card("BG_B", kind="spell")]
    new_cards = [
        _card("BG_A", name="A new", atk=2, hp=2, available_in_solo_pool=True),
        _card("BG_B", kind="spell"),
        _card("BG_C"),
    ]
    old = _make_package(
        tmp_path / "old", version="0.5.3", game_version=None,
        cards=old_cards, enums={"GameTag": {"ATK": 47}}, layout="local",
    )
    new = _make_package(
        tmp_path / "new", version="0.6.1", game_version="36.6.3.253932",
        cards=new_cards, enums={"GameTag": {"ATK": 47}},
    )
    diff = compare_packages(old, new)
    assert diff["old"]["version"] == "0.5.3"
    assert diff["new"]["version"] == "0.6.1"
    assert diff["version_newer"] is True
    # 旧 manifest 没有 game_version，应回退到 catalog 的版本
    assert diff["old"]["game_version_effective"] == "36.6.3.253932"
    assert diff["game_version_changed"] is False
    catalog = diff["catalog"]
    assert catalog["ids_identical"] is False
    assert catalog["only_new_ids"] == ["BG_C"]
    assert "atk" in catalog["fields_added"]
    assert catalog["new_kind_counts"]["minion"] == 2
    assert diff["game_tags"]["identical"] is True
    json.dumps(diff)


def test_compare_catalogs_synthetic(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    _write_json(old, {"game_version": "36.6.3.253932", "cards": [
        _card("X", tier=1, atk=1), _card("Y", kind="spell"),
    ], "skins": {"S": "X"}})
    _write_json(new, {"game_version": "36.6.3.253932", "cards": [
        _card("X", tier=2, atk=1), _card("Y", kind="spell"), _card("Z"),
    ], "skins": {"S": "X"}})
    diff = compare_catalogs(old, new)
    assert diff["ids_identical"] is False
    assert diff["only_new_ids"] == ["Z"]
    assert diff["field_value_diffs"]["tier"]["count"] == 1
    assert diff["field_value_diffs"]["tier"]["ids"] == ["X"]
    assert diff["skins_identical"] is True


def test_compare_game_tags_synthetic(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    _write_json(a, {"enums": {"GameTag": {"ATK": 47, "OLD": 1},
                              "CardType": {"MINION": 4}}})
    _write_json(b, {"enums": {"GameTag": {"ATK": 47, "NEW": 2},
                              "CardType": {"MINION": 4}}})
    diff = compare_game_tags(a, b)
    assert diff["identical"] is False
    tag = diff["game_tag"]
    assert tag["common"] == 1  # ATK
    assert tag["added"] == ["NEW"]
    assert tag["removed"] == ["OLD"]
    assert tag["value_mismatch_count"] == 0


# ══════════════════════════════════════════════════════════════════════
# game_tags ↔ 官方枚举
# ══════════════════════════════════════════════════════════════════════


def test_compare_game_tags_with_official_synthetic(tmp_path: Path) -> None:
    tags = tmp_path / "tags.json"
    _write_json(tags, {"commit": "deadbeef", "enums": {
        "GameTag": {"ATK": 47, "HEALTH": 999, "LEGACY": 5},
        "CardType": {"MINION": 4, "SPELL": 5},
    }})
    official = tmp_path / "official.json"
    _write_json(official, {
        "GAME_TAG": {"values": {"ATK": 47, "HEALTH": 45, "NEW_TAG": 100}},
        "TAG_CARDTYPE": {"values": {"MINION": 4, "SPELL": 5}},
    })
    diff = compare_game_tags_with_official(tags, official)
    tag = diff["enums"]["GameTag"]
    assert tag["official_count"] == 3
    assert tag["rizling_count"] == 3
    assert tag["common"] == 2
    assert tag["value_mismatch_count"] == 1
    assert tag["value_mismatches"][0]["name"] == "HEALTH"
    assert tag["official_only"] == ["NEW_TAG"]
    assert tag["rizling_only"] == ["LEGACY"]
    card_type = diff["enums"]["CardType"]
    assert card_type["value_mismatch_count"] == 0


# ══════════════════════════════════════════════════════════════════════
# catalog ↔ 项目数据对齐（合成）
# ══════════════════════════════════════════════════════════════════════


def test_compare_catalog_with_project_synthetic(tmp_path: Path) -> None:
    data_dir = _mini_data_dir(tmp_path / "data")
    catalog = tmp_path / "catalog.json"
    _write_json(catalog, {
        "game_version": "36.6.3.253932",
        "pool_scope": "solo_snapshot",
        "cards": [
            _card("BG_TEST_001", atk=2, hp=4, cost=0, golden="BG_TEST_001_G",
                  available_in_solo_pool=True),
            _card("BG_TEST_002", kind="spell", cost=3,
                  available_in_solo_pool=True),
            _card("BG_TEST_ONLY"),
        ],
        "skins": {},
    })
    report = compare_catalog_with_project(catalog, data_dir)
    assert report["catalog"]["game_version"] == "36.6.3.253932"
    assert report["project"]["patch"] == "37.0.0.255130"
    assert report["ids"]["intersection"] == 2
    assert report["ids"]["only_catalog"] == 1
    assert report["ids"]["only_catalog_ids"] == ["BG_TEST_ONLY"]
    # BG_TEST_001 的 atk 不一致（catalog 2 vs 引擎 3）
    assert report["numeric"]["count"] >= 1
    assert any(r["field"] == "atk" for r in report["numeric"]["samples"])
    assert report["golden"]["engine_missing"] == 1
    minion_pool = report["pools"]["kinds"]["minion"]
    assert minion_pool["catalog"] == 1
    assert minion_pool["project"] == 1
    assert minion_pool["intersection"] == 1
    json.dumps(report)


def test_pool_alignment_synthetic(tmp_path: Path) -> None:
    from hsbg.bridge.catalog import AACatalog

    data_dir = _mini_data_dir(tmp_path / "data")
    catalog_path = tmp_path / "catalog.json"
    _write_json(catalog_path, {
        "game_version": "36.6.3.253932",
        "pool_scope": "solo_snapshot",
        "cards": [
            _card("BG_TEST_001", kind="minion", available_in_solo_pool=True),
            _card("BG_TEST_002", kind="tavern_spell", available_in_solo_pool=True),
            _card("BG_TEST_X", kind="minion", available_in_solo_pool=False),
        ],
        "skins": {},
    })
    pools = pool_alignment(AACatalog(catalog_path), data_dir)
    assert pools["catalog_pool_scope"] == "solo_snapshot"
    assert pools["kinds"]["minion"]["catalog"] == 1
    assert pools["kinds"]["minion"]["project"] == 1
    assert pools["kinds"]["tavern_spell"]["intersection"] == 1


def test_detect_version_signals_synthetic(tmp_path: Path) -> None:
    data_dir = _mini_data_dir(tmp_path / "data")
    pkg = _make_package(
        tmp_path / "rizling", version="0.6.1", game_version="36.6.3.253932",
        cards=[_card("BG_A")], enums={"GameTag": {"ATK": 47}},
    )
    product = tmp_path / ".product.db"
    product.write_bytes(b"\x0a\x07hs_beta\x1a\x10" + b"37.0.0.255130.254477" + b"\x00")
    hsroot = tmp_path / "reversed"
    _write_json(hsroot / "hsdata_255130" / "source.json",
                {"tag": "255130", "files": {"CardDefs.Bacon.xml": {}}})
    signals = detect_version_signals(
        project_data_dir=data_dir, rizling_root=pkg,
        product_db=product, hsdata_root=hsroot,
    )
    assert signals["project"]["patch"] == "37.0.0.255130"
    assert signals["checks"]["product_matches_project"] is True
    assert signals["checks"]["rizling_matches_project"] is False
    assert signals["checks"]["hsdata_matches_project"] is True
    assert any("落后" in note for note in signals["notes"])
    json.dumps(signals)


# ══════════════════════════════════════════════════════════════════════
# 真实包 / 真实对齐（缺包 skip）
# ══════════════════════════════════════════════════════════════════════


@SKIP_REAL
def test_real_package_summary() -> None:
    summary = package_summary(REAL_DIR, local_root=LOCAL_DIR)
    manifest = summary["manifest"]
    assert manifest["version"] == "0.6.1"
    assert manifest["built"] == "20261018-160659"
    assert manifest["game_version"] == "36.6.3.253932"
    assert len(manifest["bundled_project_modules"]) == 36
    assert "bgassistant.hotkeys" in manifest["bundled_project_modules"]
    assert "bgassistant.artwork" in manifest["bundled_project_modules"]
    catalog = summary["catalog"]
    assert catalog["game_version"] == "36.6.3.253932"
    assert catalog["card_count"] == 3983
    assert catalog["skin_count"] == 653
    assert catalog["has_stats"] is True
    assert catalog["solo_pool_count"] == 678
    assert summary["readme_rule_version"] is None  # 0.6.1 说明不再写规则版本行
    local = summary["local_reference"]
    assert local is not None
    assert local["version"] == "0.5.3"
    assert summary["vs_local"]["version_newer"] is True
    assert summary["vs_local"]["game_version_changed"] is False
    assert summary["vs_local"]["game_tags_identical"] is True


@SKIP_REAL
def test_real_package_vs_local() -> None:
    diff = compare_packages(LOCAL_DIR, REAL_DIR)
    assert diff["version_newer"] is True
    assert diff["game_version_changed"] is False
    catalog = diff["catalog"]
    assert catalog["ids_identical"] is True
    assert catalog["old_card_count"] == catalog["new_card_count"] == 3983
    assert catalog["old_kind_counts"] == catalog["new_kind_counts"]
    for field in ("atk", "hp", "armor", "cost", "text", "text_zh",
                  "available_in_solo_pool", "is_reference_only"):
        assert field in catalog["fields_added"]
    # 共享字段（名称/等级/种族/关键词等）在两版之间没有任何取值变化
    old_shared = {"name", "name_zh", "tier", "races", "keywords",
                  "normal", "activatable", "activation_cost"}
    assert not (old_shared & set(catalog["field_value_diffs"]))
    tags = diff["game_tags"]
    assert tags["identical"] is True
    assert tags["game_tag"]["value_mismatch_count"] == 0
    assert diff["new"]["version"] == "0.6.1"


@SKIP_REAL
def test_real_catalog_alignment_with_project() -> None:
    if not (PROJECT_DATA / "bg_cards.json").is_file():
        pytest.skip("项目 data/ 不存在")
    report = compare_catalog_with_project(
        REAL_DIR / "bgassistant" / "data" / "catalog.json", PROJECT_DATA,
        sample_limit=5,
    )
    assert report["catalog"]["game_version"] == "36.6.3.253932"
    assert report["project"]["patch"].startswith("37.0.0.255130")
    ids = report["ids"]
    # 集合恒等式：交集 + 单侧 = 各侧本体数
    assert ids["intersection"] + ids["only_catalog"] == report["catalog"]["canonical_count"]
    assert ids["intersection"] + ids["only_engine"] == report["project"]["canonical_count"]
    # 本项目 255130 数据已覆盖 rizling catalog 的全部 BG36 卡
    bg36 = report["bg36"]
    assert bg36["catalog_canonical"] > 0
    assert bg36["missing"] == []
    assert bg36["matched"] == bg36["catalog_canonical"]
    # 数值差异只出现在 is_reference_only=true 的构造/引用卡上
    numeric = report["numeric"]
    assert numeric["non_reference_count"] == 0
    assert all(row["reference_only"] for row in numeric["samples"])
    # 池子恒等式：交集 + 单侧 = 各侧池
    for kind, row in report["pools"]["kinds"].items():
        assert row["intersection"] + row["catalog_only_count"] == row["catalog"]
        assert row["intersection"] + row["project_only_count"] == row["project"]
    # 本项目 37.0.0 池 >= rizling 36.6.3 快照（37.0.0 的池变化）
    minion = report["pools"]["kinds"]["minion"]
    assert minion["project"] >= minion["catalog"]
    for kind in ("tavern_spell", "hero"):
        row = report["pools"]["kinds"][kind]
        assert row["project"] >= row["catalog"]
    json.dumps(report)


@SKIP_REAL
def test_real_game_tags_vs_official() -> None:
    if not OFFICIAL_ENUMS.is_file():
        pytest.skip("reversed/net/Assembly-CSharp/enums.json 不存在")
    diff = compare_game_tags_with_official(
        REAL_DIR / "bgcontroller" / "data" / "game_tags.json", OFFICIAL_ENUMS
    )
    game_tag = diff["enums"]["GameTag"]
    assert game_tag["official_count"] == 1214
    assert game_tag["value_mismatch_count"] == 0  # 同名必同值
    assert game_tag["official_only_count"] > 0    # rizling 枚举落后于 255130
    for key in ("CardType", "Race", "Zone", "PlayState", "State", "Step"):
        enum = diff["enums"][key]
        assert enum["value_mismatch_count"] == 0, key


def test_real_version_signals() -> None:
    if not HAS_REAL_PACKAGE:
        pytest.skip("真实包不存在")
    signals = detect_version_signals(rizling_root=REAL_DIR, project_data_dir=PROJECT_DATA)
    assert signals["project"]["patch"].startswith("37.0.0.255130")
    assert signals["rizling"]["version"] == "0.6.1"
    assert signals["rizling"]["game_version"] == "36.6.3.253932"
    assert signals["checks"]["rizling_matches_project"] is False
    assert signals["hsdata"] is not None
    assert signals["hsdata"]["tag"] == "255130"
    if PRODUCT_DB.is_file():
        product = read_product_db(PRODUCT_DB)
        assert product is not None
        assert product["version"].startswith("37.0.0.255130")
        assert signals["checks"]["product_matches_project"] is True


def test_real_static_analysis_artifact() -> None:
    if not STATIC_ANALYSIS.is_file():
        pytest.skip("STATIC_ANALYSIS.json 不存在")
    data = json.loads(STATIC_ANALYSIS.read_text(encoding="utf-8"))
    assert data["pyz"]["client_modules_old"] == 27
    assert data["pyz"]["client_modules_new"] == 36
    assert data["exe"]["sha256_matches_manifest"] is True
    identical = set(data["client_modules_byte_identical"])
    # 解析/映射/内存/protocol 等核心模块与 0.5.3 完全一致 → 没有 37.0 规则更新
    for name in ("bgcontroller.client.powerlog", "bgcontroller.client.mapping",
                 "bgcontroller.client.tags", "bgcontroller.client.memory",
                 "bgassistant.protocol"):
        assert name in identical
    for bad in ("torch", "onnx", "pyautogui", "pynput", "liveclient", "simulator"):
        assert bad in data["forbidden_modules_absent"]
    assert data["version_constants_in_client_code"] == {}
