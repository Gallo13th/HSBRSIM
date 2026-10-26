"""数据差异 / 规则常量快照测试（36.6.3 vs 37.0.0）。

数字是本次审计实测快照；若上游参考仓库或 data/ 更新，应重跑
`python3 -m tools.ac_conformance.data_diff` 并同步台账。
"""

import pytest

# 可移植性守卫：taverngym 是可选依赖（Windows 开发机可能未安装），
# 未安装时整目录 skip 而不是 collection error（见 docs/TAVERNGYM_BACKEND.md）。
pytest.importorskip(
    "taverngym",
    reason="跨引擎一致性套件需要可选依赖 taverngym（见 docs/TAVERNGYM_BACKEND.md）")

from tools.ac_conformance import data_diff


def test_card_id_snapshot():
    diff = data_diff.compare_cards()
    ids = diff["ids"]
    assert ids["autotavern_cards"] == 3983
    assert ids["hsrl2_cards"] == 3534
    assert ids["shared"] == 3412


def test_shared_minions_are_data_identical():
    diff = data_diff.compare_cards()["minions"]
    assert diff["shared_minions"] == 2393
    assert diff["stat_diff_count"] == 0
    assert diff["tier_diff_count"] == 0
    assert diff["race_diff_count"] == 0
    # 8 条：4 张卡 × 普通/金色 的 START_OF_COMBAT 字段缺口（真实数据差异）
    # + 2 张测试卡（BGMinionAbilityTest*）的 ACTIVATE 标记差异（非池卡）
    rows = diff["keyword_diff"]
    assert diff["keyword_diff_count"] == 8
    soc = [r for r in rows if "START_OF_COMBAT" in r["at_only"]]
    assert len(soc) == 6
    assert all(r["hs_only"] == [] for r in soc)
    rest = [r for r in rows if r not in soc]
    assert all(r["id"].startswith("BGMinionAbilityTest") for r in rest)


def test_text_diff_is_mostly_representation():
    diff = data_diff.compare_cards()["minions"]
    # 2393 张共享随从里：卡面文本 847 条仅表示差异、37 条待人工复核
    assert diff["text_formatting_only_count"] == 847
    assert diff["text_diff_count"] == 37


def test_pool_membership_diff():
    pool = data_diff.compare_cards()["pool"]
    assert pool["autotavern_pool_minions"] == 245
    assert pool["hsrl2_pool_minions"] == 273
    assert pool["shared_pool_minions"] == 240
    assert len(pool["only_autotavern_pool"]) == 5
    assert len(pool["only_hsrl2_pool"]) == 33


def test_rule_constants_match_after_ac02_ac03_fix():
    """AC-02/AC-03 修复后（2026-10-26）：18 项规则常量应与参照完全一致。"""
    const = data_diff.compare_rule_constants()
    assert const["diff_count"] == 0, const["diffs"]
    by_key = {row["key"]: row for row in const["rows"]}
    assert by_key["pool_copies_by_tier"]["match"] is True
    assert by_key["upgrade_costs"]["match"] is True
    assert by_key["pool_copies_by_tier"]["hsrl2"] == [15, 15, 13, 11, 9, 7, 5]
    assert by_key["upgrade_costs"]["hsrl2"] == [5, 7, 8, 11, 11, 10]


def test_spell_pool_and_shop_slots_match():
    const = data_diff.compare_rule_constants()
    by_key = {row["key"]: row for row in const["rows"]}
    assert by_key["spell_copies_by_tier"]["match"] is True
    assert by_key["shop_minion_slots"]["match"] is True
    assert by_key["damage_caps"]["match"] is True
    assert by_key["triple_copies"]["match"] is True
