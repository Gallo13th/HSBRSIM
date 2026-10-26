"""跨引擎一致性套件（AutoTavern 36.6.3 参照 vs hsrl2 37.0.0）。

回归口径：场景矩阵的 ``expected`` 是 `docs/CONFORMANCE_AUTOTAVERN.md`
台账的审计结论快照（MATCH / ENGINE_BUG / UNSUPPORTED / ...）。若引擎行为
变化导致判定不同，本测试失败 → 必须同步更新台账（而不是放宽断言）。

运行::

    python3 -m pytest tests/conformance -q
"""

import pytest

# 可移植性守卫：taverngym 是可选依赖（Windows 开发机可能未安装），
# 未安装时整目录 skip 而不是 collection error（见 docs/TAVERNGYM_BACKEND.md）。
pytest.importorskip(
    "taverngym",
    reason="跨引擎一致性套件需要可选依赖 taverngym（见 docs/TAVERNGYM_BACKEND.md）")

from tools.ac_conformance import run as runner
from tools.ac_conformance import scenarios

#: pytest 里用较小 trial 数（分布类场景两引擎仍各 24 次独立 trial/seed）。
SEEDS = 24


@pytest.fixture(scope="module")
def report():
    return runner.run_all(seeds=SEEDS, progress=False)


def test_all_scenarios_have_expected_baseline():
    ids = [s.id for s in scenarios.ALL_SCENARIOS]
    assert len(ids) == len(set(ids)), "场景 id 必须唯一"
    expected = {s.id: s.expected for s in scenarios.ALL_SCENARIOS}
    assert all(v in {"MATCH", "ENGINE_BUG", "CONVENTION_DIFF",
                     "DATA_GAP", "UNSUPPORTED", "DEFERRED"}
               for v in expected.values())


def test_report_matches_ledger_baseline(report):
    expected = {s.id: s.expected for s in scenarios.ALL_SCENARIOS}
    mismatched = []
    for row in report["rows"]:
        assert row["id"] in expected, row["id"]
        if row["classification"] != expected[row["id"]]:
            mismatched.append(
                (row["id"], expected[row["id"]], row["classification"],
                 row.get("reason")))
    assert not mismatched, (
        "判定与台账基线不一致（行为变化或回归；请复核后更新"
        " docs/CONFORMANCE_AUTOTAVERN.md 与 scenarios.expected）: "
        f"{mismatched}")


def test_report_summary_and_coverage(report):
    summary = report["summary"]
    assert summary["total"] == len(scenarios.ALL_SCENARIOS)
    counts = summary["counts"]
    # 覆盖要求：≥40 个机制/卡牌场景
    assert summary["total"] >= 40, summary
    # 2026-10-26 最终状态（engine-fixer F-35 结论后）：AC-02/03 已修复、
    # AC-01 与 AC-04 均判 CONVENTION_DIFF（后者为参照侧脚本异常，非 hsrl2
    # 分歧），无遗留 ENGINE_BUG。若后续修复/改判，同步更新台账与 expected。
    assert counts.get("ENGINE_BUG", 0) == 0, counts
    assert counts.get("CONVENTION_DIFF", 0) == 2, counts
    assert counts.get("UNSUPPORTED", 0) == 1, counts
    assert counts.get("DEFERRED", 0) == 0, counts
    # 战斗/卡牌场景不允许出现 UNSUPPORTED 之外的无法比较结果
    kinds = {row["kind"] for row in report["rows"]}
    assert {"duel", "card_duel", "economy", "flow"} <= kinds


def test_convention_diffs_are_isolated_and_reproducible(report):
    """最终裁定：2 条 CONVENTION_DIFF = C24（先攻约定）+ K15（参照侧脚本
    异常，F-35）；无 ENGINE_BUG；K15 带确定性复现证据且 C26 白板对照 MATCH。"""
    conv = {r["id"]: r for r in report["rows"]
            if r["classification"] == "CONVENTION_DIFF"}
    assert set(conv) == {"C24", "K15"}, {k: v["title"] for k, v in conv.items()}
    assert ("deterministic damage mismatch"
            in conv["K15"]["detail"].get("mismatch_reason", ""))
    assert "参照侧脚本" in conv["K15"]["reason"] or "AT" in conv["K15"]["reason"]
    fa = conv["C24"]["detail"].get("first_attacker") or {}
    assert fa.get("verdict") == "mismatch"
    assert fa.get("tavern_deterministic") is True
    assert not [r for r in report["rows"]
                if r["classification"] == "ENGINE_BUG"]
    # 对照场景（同属性无脚本白板）必须 MATCH，用于隔离 AT 侧脚本异常
    c26 = next(r for r in report["rows"] if r["id"] == "C26")
    assert c26["classification"] == "MATCH"
