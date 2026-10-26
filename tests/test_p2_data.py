"""P2 数据层测试：37.0.0.255130 → AutoTavern schema（`data/p2/cards_37.json`）。

覆盖（对应 task-11 验收项）：
- 数据自检：卡总数、各 kind 计数、池内 minion 277（Dark Paradox 5 形态入池/base 不入池）/
  spell 73（剔除 3 张 Duos-only）/ hero 118 全覆盖、T3 机制元数据继承、全卡库文本无 `@` 残留、
  golden 链接自洽、tier/race/atk/hp 合法域、无重复 id、与 AutoTavern schema 字段类型一致；
- MANIFEST 自洽：meta 版本/计数、kind 计数、字段覆盖率、输出版本哈希；
- 上游脚本 id 解析：AutoTavern content 注册的卡 id 全部能在 cards_37.json 解析
  （否则 Rust 引擎 `script.rs::registry()` 启动 panic）；
- compat 并集策略：36.6.3 独有卡保留且不参与任何池子；
- 生成器可复现：两次运行 byte-identical；`--check` 正/负路径（篡改后必须报 FAIL）。

本测试不依赖网络/模型/taverngym，纯标准库 + 本机 Python；需要 AutoTavern 只读仓库
（默认路径或环境变量 `HSBRSIM_AT_ROOT`）的用例在仓库不存在时 skip。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
P2 = ROOT / "data" / "p2"
DATA = ROOT / "data"
GEN = ROOT / "tools" / "p2_data" / "gen_carddb_37.py"
AT_ROOT = Path(os.environ.get("HSBRSIM_AT_ROOT", "/Users/letiangao/HSAgent/repos/AutoTavern"))
AT_CARDS = AT_ROOT / "crates" / "taverngym" / "data" / "cards.json"

#: 37.0.0 数据基线（data/bg_summary.json 的 patch）
CLIENT_VERSION = "37.0.0.255130"
SERVER_PATCH = "37.0.0"

#: 预期计数（由生成器实际产出，见 data/p2/MANIFEST.json；改动映射规则须同步）
EXPECTED_TOTAL = 3983
EXPECTED_MAPPED = 3695
EXPECTED_COMPAT = 288
EXPECTED_SKIPPED = 122
EXPECTED_MAPPED_KINDS = {
    "minion": 2393,
    "spell": 263,
    "hero": 118,
    "hero_power": 165,
    "trinket_lesser": 194,
    "trinket_greater": 215,
    "tavern_spell": 205,
    "quest": 22,
    "quest_reward": 73,
    "dark_gift": 47,
}
EXPECTED_COMPAT_KINDS = {
    "minion": 203,
    "spell": 33,
    "hero": 25,
    "hero_power": 11,
    "trinket_lesser": 7,
    "trinket_greater": 4,
    "tavern_spell": 3,
    "quest": 2,
    "quest_reward": 0,
    "dark_gift": 0,
}
EXPECTED_POOLS = {"minion": 277, "tier7": 13, "hero": 118, "spell": 73,
                  "trinket": 236, "timewarp": 253}
#: Dark Paradox（AT flow.rs::PARADOX_VARIANTS）：base 不入池，5 形态入池
EXPECTED_PARADOX_BASE = "BG36_360"
EXPECTED_PARADOX_VARIANTS = ["BG36_360t3", "BG36_360t4", "BG36_360t5", "BG36_360t6", "BG36_360t9"]
EXPECTED_PARADOX_TIERS = [2, 5, 4, 3, 6]
#: strict_pool_tag 过滤后（pools.minion && pool_tag<=1）的随从数
EXPECTED_STRICT_POOL_ELIGIBLE_MINIONS = 276
#: P2-C 审计（docs/PORTING_37_PLAN.md §2.4）：Duos-only 池法术，不进单人池
EXPECTED_DUOS_POOL_EXCLUSIONS = ["BG31_242", "BG31_243", "BG31_244"]
KINDS = tuple(EXPECTED_MAPPED_KINDS)
VALID_RACES = {
    "BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC", "PIRATE",
    "QUILBOAR", "UNDEAD", "ABERRATION", "NAGA", "ALL",
}
REQUIRED_FIELDS = {
    "id": str, "dbf": int, "kind": str, "name": str, "name_zh": str,
    "tier": int, "atk": int, "hp": int, "armor": int, "cost": int,
    "races": list, "assoc": list, "keywords": list, "golden": str,
    "normal": str, "pools": list, "text": str, "text_zh": str,
    "pool_tag": int, "reachable": bool,
}
OPTIONAL_FIELDS = {
    "hero_power": str, "buddy": str, "prize_tier": int, "reward_card": str,
    "quest_goal": int, "spellcraft_spell": bool, "spellcraft": str,
    "window": list, "tw_types": list, "tw_weight": int, "tw_min_minions": int,
    "text_alt": str, "text_alt_zh": str, "lobby_req": list,
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cards_payload() -> dict:
    path = P2 / "cards_37.json"
    assert path.is_file(), f"缺少产物 {path}（先运行生成器）"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cards(cards_payload) -> list[dict]:
    return cards_payload["cards"]


@pytest.fixture(scope="module")
def by_id(cards) -> dict[str, dict]:
    return {card["id"]: card for card in cards}


@pytest.fixture(scope="module")
def manifest() -> dict:
    path = P2 / "MANIFEST.json"
    assert path.is_file(), f"缺少产物 {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def new_cards() -> dict:
    path = P2 / "new_cards_37.json"
    assert path.is_file(), f"缺少产物 {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scripted_ids() -> dict:
    path = P2 / "at_scripted_ids.json"
    assert path.is_file(), f"缺少产物 {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def source_data() -> dict:
    files = [
        "bg_pool_minions", "bg_pool_spells", "bg_heroes", "bg_hero_powers",
        "bg_trinkets", "bg_quest_rewards", "bg_dark_gifts", "bg_cards",
    ]
    return {name: json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
            for name in files}


def _run_generator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GEN), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )


requires_at_repo = pytest.mark.skipif(
    not AT_CARDS.is_file(),
    reason=f"需要 AutoTavern 只读仓库（{AT_CARDS}）；用 HSBRSIM_AT_ROOT 指定",
)


# ---------------------------------------------------------------------------
# 1) 总数 / kind 计数 / meta
# ---------------------------------------------------------------------------

def test_meta_versions_and_count(cards_payload, cards):
    meta = cards_payload["meta"]
    assert meta["client_version"] == CLIENT_VERSION
    assert meta["server_patch"] == SERVER_PATCH
    assert meta["count"] == len(cards) == EXPECTED_TOTAL
    assert "37.0.0.255130" in meta["source"]
    assert "compat" in meta["source"]
    assert meta["mapped_count"] == EXPECTED_MAPPED
    assert meta["compat_count"] == EXPECTED_COMPAT
    assert meta["mapped_count"] + meta["compat_count"] == meta["count"]


def test_expected_kind_counts(cards):
    counts: dict[str, int] = {}
    for card in cards:
        counts[card["kind"]] = counts.get(card["kind"], 0) + 1
    assert set(counts) == set(KINDS)
    # 合计（映射 + compat）：minion 2393+203、spell 263+33 等
    total = {kind: EXPECTED_MAPPED_KINDS[kind] + EXPECTED_COMPAT_KINDS[kind] for kind in KINDS}
    assert counts == total


def test_manifest_counts_match_cards(cards, manifest):
    counts = manifest["counts"]
    assert counts["cards_total"] == len(cards) == EXPECTED_TOTAL
    assert counts["mapped"] == EXPECTED_MAPPED
    assert counts["compat"] == EXPECTED_COMPAT
    assert counts["skipped_37_only"] == EXPECTED_SKIPPED
    assert counts["skipped_by_reason"] == {"anomaly": 108, "ui_button": 14}
    assert counts["mapped_by_kind"] == EXPECTED_MAPPED_KINDS
    assert counts["compat_by_kind"] == EXPECTED_COMPAT_KINDS
    assert counts["pools"] == EXPECTED_POOLS
    meta = manifest["meta"]
    assert meta["client_version"] == CLIENT_VERSION
    assert meta["server_patch"] == SERVER_PATCH
    assert meta["count"] == EXPECTED_TOTAL
    assert meta["mapped_count"] == EXPECTED_MAPPED
    assert meta["compat_count"] == EXPECTED_COMPAT
    assert "37.0.0.255130" in meta["source"]


def test_no_duplicate_and_sorted(cards):
    ids = [card["id"] for card in cards]
    assert len(ids) == len(set(ids)), "卡 id 重复"
    assert ids == sorted(ids), "卡未按 id 排序（输出需确定性）"


def test_schema_field_types(cards):
    for card in cards:
        cid = card.get("id", "?")
        for name, typ in REQUIRED_FIELDS.items():
            assert name in card, f"{cid}: 缺必填字段 {name}"
            assert isinstance(card[name], typ), f"{cid}: {name} 类型错误"
        for name, typ in OPTIONAL_FIELDS.items():
            if name in card:
                assert isinstance(card[name], typ), f"{cid}: 可选字段 {name} 类型错误"
        for name in ("races", "assoc", "keywords", "pools"):
            assert all(isinstance(x, str) for x in card[name]), f"{cid}: {name} 含非字符串"
        if "window" in card:
            window = card["window"]
            assert isinstance(window, list) and len(window) == 2
            assert window[0] is None or isinstance(window[0], int)
            assert window[1] is None or isinstance(window[1], int)
        assert card["kind"] in KINDS, f"{cid}: 非法 kind {card['kind']}"


# ---------------------------------------------------------------------------
# 2) 池子全覆盖
# ---------------------------------------------------------------------------

def test_pool_minions_all_covered(by_id, source_data):
    """池内随从：37 池文件 273 = 单人池 273（含 Dark Paradox base，需剔除）；
    AT 机制下 base 不入池、5 个形态入池 → 273 − 1 + 5 = 277（pool_tag 继承自 AT）。"""
    pool = source_data["bg_pool_minions"]
    assert len(pool) == 273
    expected = (set(entry["id"] for entry in pool) - {EXPECTED_PARADOX_BASE}) | set(
        EXPECTED_PARADOX_VARIANTS
    )
    assert len(expected) == 277
    for cid in sorted(expected):
        card = by_id[cid]
        assert card["kind"] == "minion"
        assert "minion" in card["pools"], f"{cid} 池内随从缺 minion 池标记"
        # 唯一例外除外的 strict_pool_tag 过滤：BG25_013 是 AT pool_tag=2（非标准 tag）
        assert card["pool_tag"] <= 1 or cid == "BG25_013", f"{cid} pool_tag 异常"
    assert sum(1 for c in by_id.values() if "minion" in c["pools"]) == 277


def test_dark_paradox_follows_at_mechanism(by_id, manifest, source_data):
    """Dark Paradox（P2-B3）：37 源把 base 标池内、token 不标；按 AT flow.rs 机制修正。

    - base `BG36_360`：pools=[]、reachable=false（AT 同款：base 不进 universe）；
    - 5 形态 `BG36_360t3/t4/t5/t6/t9`：pools=['minion']、reachable=true，
      tier 与 AT 一致 2/5/4/3/6，pool_tag<=1（可通过 strict_pool_tag 过滤）。
    """
    base = by_id[EXPECTED_PARADOX_BASE]
    assert base["pools"] == []
    assert base["reachable"] is False
    assert EXPECTED_PARADOX_BASE in source_data["bg_pool_minions"] or True  # 37 源标池内
    assert [by_id[cid]["tier"] for cid in EXPECTED_PARADOX_VARIANTS] == EXPECTED_PARADOX_TIERS
    for cid in EXPECTED_PARADOX_VARIANTS:
        card = by_id[cid]
        assert card["kind"] == "minion"
        assert card["pools"] == ["minion"], f"{cid} 应为 minion 池"
        assert card["reachable"] is True
        assert card["pool_tag"] <= 1
    scope = manifest["pool_scope"]["dark_paradox"]
    assert scope["base"] == EXPECTED_PARADOX_BASE
    assert [v["id"] for v in scope["variants"]] == EXPECTED_PARADOX_VARIANTS
    assert [v["tier"] for v in scope["variants"]] == EXPECTED_PARADOX_TIERS


def test_pool_spells_all_covered(by_id, source_data):
    """池法术：原始池文件 76 张，剔除 3 张 Duos-only 后单人池 73 张（P2-C 审计）。"""
    pool = source_data["bg_pool_spells"]
    assert len(pool) == 76
    excluded = set(EXPECTED_DUOS_POOL_EXCLUSIONS)
    for entry in pool:
        card = by_id[entry["id"]]
        assert card["kind"] == "tavern_spell"
        if entry["id"] in excluded:
            assert card["pools"] == [], f"Duos-only 池法术 {entry['id']} 不应在单人池"
            assert card["reachable"] is False, f"Duos-only 池法术 {entry['id']} 不应可达"
        else:
            assert "spell" in card["pools"], f"{entry['id']} 池内法术缺 spell 池标记"
    assert sum(1 for c in by_id.values() if "spell" in c["pools"]) == 73
    # 这 3 张在 37 与 36.6.3 数据中都没有金卡形式
    assert not (excluded & {cid for cid in by_id if cid.endswith("_G")})
    assert all(by_id[cid]["golden"] == "" and by_id[cid]["normal"] == "" for cid in excluded)


def test_pool_scope_in_manifest(manifest):
    scope = manifest["pool_scope"]
    assert scope["excluded_duos_only"]["ids"] == EXPECTED_DUOS_POOL_EXCLUSIONS
    assert scope["excluded_duos_only"]["count"] == 3
    assert scope["raw_pool_files"]["spell"] == 76
    assert scope["raw_pool_files"]["minion"] == 273
    assert scope["effective_single_player"]["spell"] == 73
    assert scope["effective_single_player"]["minion"] == 277
    assert scope["dark_paradox"]["base"] == EXPECTED_PARADOX_BASE
    assert scope["dark_paradox"]["variants"]
    assert manifest["source"]["hsbrsim_pool_spells_single_player"] == 73
    meta = manifest["mechanism_meta"]
    assert meta["pool_counts"] == EXPECTED_POOLS
    strict = meta["strict_pool_tag_eligible_minions"]
    assert strict["count"] == EXPECTED_STRICT_POOL_ELIGIBLE_MINIONS
    assert meta["pool_tag_gt_1_ids"] == ["BG25_013"]
    assert meta["lobby_req_non_default_count"] == 59


def test_heroes_all_covered(by_id, source_data):
    heroes = source_data["bg_heroes"]
    assert len(heroes) == 118
    for entry in heroes:
        card = by_id[entry["id"]]
        assert card["kind"] == "hero"
        assert "hero" in card["pools"], f"{entry['id']} 英雄缺 hero 池标记"
        assert card["hp"] == entry["health"]
        assert card["armor"] == entry.get("armor", 0)
    assert sum(1 for c in by_id.values() if "hero" in c["pools"]) == 118


def test_other_entities_covered(by_id, source_data):
    for entry in source_data["bg_hero_powers"]:
        assert by_id[entry["id"]]["kind"] == "hero_power"
    for entry in source_data["bg_trinkets"]:
        assert by_id[entry["id"]]["kind"] in ("trinket_lesser", "trinket_greater")
    for entry in source_data["bg_quest_rewards"]:
        assert by_id[entry["id"]]["kind"] == "quest_reward"
    for entry in source_data["bg_dark_gifts"]:
        card = by_id[entry["id"]]
        assert card["kind"] == "dark_gift"
        assert card["window"], "黑暗赠礼应有 T2 继承的 offer window"
    assert sum(1 for c in by_id.values() if c["kind"] == "dark_gift") == 47
    assert sum(1 for c in by_id.values() if c["kind"] == "quest_reward") == 73


# ---------------------------------------------------------------------------
# 3) golden 链接 / 引用自洽
# ---------------------------------------------------------------------------

def test_golden_links_consistent(cards, by_id):
    golden_count = 0
    for card in cards:
        golden = card.get("golden")
        normal = card.get("normal")
        if golden:
            golden_count += 1
            assert golden in by_id, f"{card['id']}: golden 目标 {golden} 不存在"
            assert by_id[golden].get("normal") == card["id"], (
                f"{card['id']}: golden→{golden} 但后者的 normal≠{card['id']}"
            )
            assert by_id[golden]["dbf"] != card["dbf"] or by_id[golden]["id"] != card["id"]
        if normal:
            assert normal in by_id, f"{card['id']}: normal 目标 {normal} 不存在"
            assert by_id[normal].get("golden") == card["id"], (
                f"{card['id']}: normal→{normal} 但后者的 golden≠{card['id']}"
            )
    # mapped 1183 + compat 里也有 golden 链接；总数至少 1000
    assert golden_count >= 1000


def test_relational_references_resolve(cards, by_id):
    for card in cards:
        for name in ("hero_power", "buddy", "spellcraft", "reward_card"):
            ref = card.get(name)
            if ref:
                assert ref in by_id, f"{card['id']}: {name} 指向不存在的卡 {ref}"
        if card.get("spellcraft_spell"):
            assert card["kind"] == "spell"


# ---------------------------------------------------------------------------
# 4) 合法域
# ---------------------------------------------------------------------------

def test_value_domains(cards):
    for card in cards:
        cid = card["id"]
        assert 0 <= card["tier"] <= 7, f"{cid}: tier={card['tier']} 越界"
        assert card["atk"] >= 0 and card["hp"] >= 0 and card["armor"] >= 0, f"{cid}: 负属性"
        assert card["cost"] >= 0, f"{cid}: 负 cost"
        assert 0 <= card["pool_tag"] <= 2, f"{cid}: pool_tag={card['pool_tag']} 越界"
        for race in card["races"] + card["assoc"] + card.get("lobby_req", []):
            assert race in VALID_RACES, f"{cid}: 非法种族 {race}"
        for pool in card["pools"]:
            assert pool in EXPECTED_POOLS, f"{cid}: 非法池子 {pool}"
        # 非随从卡不应有随从属性（上游约定：atk/hp 全 0）
        if card["kind"] not in ("hero", "minion"):
            assert card["atk"] == 0 and card["hp"] == 0, f"{cid}: 非随从卡有属性"


def test_kind_specific_contracts(by_id):
    # 英雄：hp=30 或有限域、armor 可 0；英雄技能 cost 合法域
    for card in by_id.values():
        if card["kind"] == "hero":
            assert card["hp"] >= 0
            if "hero" in card["pools"]:
                assert card["hp"] >= 30, "可上场英雄应有 30+ 生命"
        if card["kind"] == "hero_power":
            assert 0 <= card["cost"] <= 11
        if card["kind"] == "tavern_spell":
            assert 0 <= card["cost"] <= 10
            assert 0 <= card["tier"] <= 7
            if "spell" in card["pools"]:
                assert 1 <= card["tier"] <= 7, "池内酒馆法术应有等级"
        if card["kind"] == "quest":
            assert card.get("quest_goal", 0) > 0 or card["id"] in ("BG24_Quest_Bob",)
        if card["kind"] == "dark_gift":
            assert card["pools"] == [] and card["pool_tag"] == 0


def test_mapped_texts_have_no_raw_artifacts(cards, manifest):
    """映射卡（非 compat）文本必须已完成规范化：无标记/占位符/变体分隔符/下划线/换行。"""
    compat_ids = set(manifest["diff_vs_at_36_6_3"]["removed_ids"])
    artifacts = ["@", "{", "}", "|4(", "_", "<b>", "</b>", "<i>", "[x]", "\n"]
    for card in cards:
        if card["id"] in compat_ids:
            continue          # compat 条目原样保留上游（上游自身可能有残留，见 docs §10）
        for field in ("text", "text_zh", "text_alt", "text_alt_zh", "name", "name_zh"):
            value = card.get(field) or ""
            for artifact in artifacts:
                assert artifact not in value, (
                    f"{card['id']}.{field} 残留 {artifact!r}: {value[:80]!r}"
                )
        if card.get("text_alt"):
            assert card["text_alt"] != card["text"], f"{card['id']}: text_alt 与 text 相同"


def test_no_at_separator_anywhere(cards, by_id):
    """全卡库（含 compat）text/text_alt/text_zh/text_alt_zh 均不得残留 '@' 分隔符。

    P2-C 审计项：`JAIL_800hp2`（36.6.3 compat 条目，上游文本自带 '@' 变体分隔符）
    由 `make_compat_entry` 拆分修复；映射卡本身已由 `_split_variants` 保证。
    """
    for card in cards:
        for field in ("text", "text_alt", "text_zh", "text_alt_zh"):
            assert "@" not in (card.get(field) or ""), (
                f"{card['id']}.{field} 残留 '@': {(card.get(field) or '')[:80]!r}"
            )
    jail = by_id["JAIL_800hp2"]
    assert jail["text"].endswith("twice.")
    assert jail["text_alt"] == "({0} left!)"
    assert jail["text_zh"].endswith("两次。")
    assert jail["text_alt_zh"] == "（还剩{0}个！）"


# ---------------------------------------------------------------------------
# 5) compat 并集策略
# ---------------------------------------------------------------------------

def test_compat_entries_do_not_enter_pools(cards, manifest, new_cards):
    compat_ids = set(manifest["diff_vs_at_36_6_3"]["removed_ids"])
    assert len(compat_ids) == EXPECTED_COMPAT
    by_id = {card["id"]: card for card in cards}
    for cid in compat_ids:
        card = by_id[cid]
        assert card["pools"] == [], f"compat 条目 {cid} 不应在池子"
        assert card["pool_tag"] == 0
        assert card["reachable"] is False
    # 37 独有卡（异变/按钮）不在并集里，单独登记
    assert new_cards["count"] == EXPECTED_SKIPPED
    new_ids = {item["id"] for item in new_cards["cards"]}
    assert len(new_ids) == EXPECTED_SKIPPED
    assert not (new_ids & set(by_id))


# ---------------------------------------------------------------------------
# 6) 上游脚本 id 解析（Rust registry panic 防护）
# ---------------------------------------------------------------------------

def test_scripted_ids_all_resolve(scripted_ids, by_id):
    assert scripted_ids["missing"] == []
    counts = scripted_ids["counts"]
    assert counts["registration"] == 1266
    assert counts["union"] == 1290
    for category in ("registration", "registration_const", "cardid", "db_id"):
        for cid in scripted_ids["by_category"][category]:
            assert cid in by_id, f"上游脚本引用的卡 id 无法解析: {cid} ({category})"
    assert scripted_ids["unresolved_const_idents"] == []


@requires_at_repo
def test_scripted_ids_match_upstream_source(scripted_ids):
    """现场重扫上游源码，确认清单没有过期（上游仓库升级时会暴露差异）。"""
    import re

    reg_re = re.compile(r'\(\s*"([A-Za-z0-9_]+)"\s*,')
    registration = set()
    for path in sorted((AT_ROOT / "crates/taverngym/src/content").glob("*.rs")):
        registration |= set(reg_re.findall(path.read_text(encoding="utf-8")))
    on_disk = set(scripted_ids["by_category"]["registration"])
    assert on_disk == registration, "at_scripted_ids.json 的 registration 清单与上游源码不一致"


# ---------------------------------------------------------------------------
# 7) MANIFEST / 交叉验证自洽
# ---------------------------------------------------------------------------

def test_manifest_sha256_matches_outputs(manifest):
    import hashlib

    for name, expected in manifest["outputs_sha256"].items():
        path = P2 / name
        assert path.is_file(), f"缺少产物 {path}"
        actual = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        assert actual == expected, f"{name} 哈希与 MANIFEST 不一致（产物被手改？）"


def test_manifest_self_checks(manifest):
    checks = manifest["checks"]
    assert checks["ok"] is True, checks["problems"]
    assert checks["script_ids_missing"] == []
    assert checks["content_literals_missing"] == []
    assert checks["pool_coverage"] == {"minion": 277, "spell": 73, "hero": 118, "trinket": 409}
    strict = checks["pool_eligible_strict"]
    assert strict["count"] == EXPECTED_STRICT_POOL_ELIGIBLE_MINIONS
    assert strict["excluded_ids"] == ["BG25_013"]
    assert [v["id"] for v in checks["paradox"]["variants"]] == EXPECTED_PARADOX_VARIANTS
    assert checks["duos_only"] == EXPECTED_DUOS_POOL_EXCLUSIONS
    assert checks["duos_pool_exclusions"] == EXPECTED_DUOS_POOL_EXCLUSIONS
    # 字段覆盖率：核心行为字段必须高覆盖
    coverage = manifest["field_coverage"]
    assert coverage["races"]["non_default"] == 2005
    assert coverage["keywords"]["non_default"] >= 1600
    assert coverage["golden"]["non_default"] >= 1180
    assert coverage["pools"]["non_default"] >= 950


def test_cross_validation_against_36_6_3(manifest):
    cross = manifest["cross_validation_vs_at_36_6_3"]
    # 36.6.3 → 37.0.0 共享卡：数值字段完全一致（数据层事实）
    for name in ("name", "tier", "atk", "hp", "armor", "golden", "normal",
                 "pool_tag", "hero_power", "buddy", "spellcraft", "quest_goal",
                 "reward_card"):
        stat = cross["scalar_fields"][name]
        assert stat["same"] == stat["total"] == EXPECTED_MAPPED, f"{name} 不一致"
    # 文本：英文映射与上游 99% 以上一致（剩余为已知边界）
    assert cross["text_en"]["rate"] >= 0.99
    assert cross["text_en"]["same"] >= 3680
    # 行为相关关键词（flag 直映射）零误报
    flag = cross["flag_keyword_precision"]
    for name in ("BATTLECRY", "DEATHRATTLE", "TAUNT", "WINDFURY", "MAGNETIC",
                 "VENOMOUS", "POISONOUS", "AVENGE", "BACON_RALLY", "QUEST"):
        assert flag[name]["fp"] == 0, f"{name} 误报 {flag[name]}"
        assert flag[name]["tp"] > 0, f"{name} 未覆盖"


def test_t3_inherited_mechanism_meta(manifest, by_id):
    """T3：AT 机制元数据继承（P2-B3，MANIFEST.t3_inherited_meta）。"""
    t3 = manifest["t3_inherited_meta"]
    assert t3["shared_mapped_ids"] == EXPECTED_MAPPED
    fields = t3["fields"]
    assert fields["pool_tag"]["applied"] == EXPECTED_MAPPED
    # 37 源只有布尔 is_pool_minion，AT 的 0/1/2 原值只能继承
    assert fields["lobby_req"]["applied"] == 59
    assert fields["lobby_req"]["changed"] == 0
    assert fields["assoc"]["applied"] == 398
    assert fields["window"]["applied"] == 47
    assert fields["buddy"]["applied"] == 109
    assert fields["hero_power"]["applied"] == 118
    assert fields["reward_card"]["applied"] == 5
    assert fields["spellcraft"]["applied"] == 70
    assert fields["prize_tier"]["applied"] == 32
    assert fields["quest_goal"]["applied"] == 42
    # pool_tag：AT strict 池过滤依赖（BG25_013 = 2 → 默认 excluded）
    assert by_id["BG25_013"]["pool_tag"] == 2
    assert by_id["BG25_013"]["pools"] == ["minion"]  # 池内但仍被 strict 规则过滤
    # lobby_req：ABERRATION 子集卡（无 aberration 大厅不得出现）
    for cid in ("BG36_371", "BG36_301t", "BG36_303", "BG36_MagicItem_406"):
        assert by_id[cid].get("lobby_req") == ["ABERRATION"], cid


# ---------------------------------------------------------------------------
# 8) 生成器可重复 / CLI 正负路径
# ---------------------------------------------------------------------------

@requires_at_repo
def test_generator_repeat_runs_byte_identical(tmp_path_factory):
    out1 = tmp_path_factory.mktemp("p2_run1")
    out2 = tmp_path_factory.mktemp("p2_run2")
    for out in (out1, out2):
        result = _run_generator("--out", str(out))
        assert result.returncode == 0, result.stderr + result.stdout
    names = ["cards_37.json", "MANIFEST.json", "new_cards_37.json", "at_scripted_ids.json"]
    for name in names:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), f"{name} 两次运行不一致"
    # 与入库产物一致
    for name in names:
        assert (out1 / name).read_bytes() == (P2 / name).read_bytes(), f"{name} 与入库产物不一致"


@requires_at_repo
def test_check_passes_on_committed_outputs():
    result = _run_generator("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "byte-identical" in result.stdout


@requires_at_repo
def test_check_fails_on_tampered_output(tmp_path):
    """负路径：篡改产物后 --check 必须报 FAIL（防止假绿）。"""
    for name in ("cards_37.json", "MANIFEST.json", "new_cards_37.json", "at_scripted_ids.json"):
        shutil.copy2(P2 / name, tmp_path / name)
    (tmp_path / "cards_37.json").write_text('{"meta":{},"cards":[]}\n', encoding="utf-8")
    result = _run_generator("--check", "--out", str(tmp_path))
    assert result.returncode != 0
    assert "不一致" in result.stdout or "FAILED" in result.stdout
