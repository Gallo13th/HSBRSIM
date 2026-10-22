"""真实战斗边界状态语料（``runs/state_corpus/``）回归测试。

- 语料缺失时 → skip（不阻塞未导出环境）；
- 合成/子集导出用例写到 tmp_path，不修改 `runs/state_corpus/`；
- 抽样校验拿语料记录与原始 trace/XML 对比，守住"不用基础卡面替代真实状态"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsbg.bridge import state_corpus as sc

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
CORPUS_DIR = RUNS / "state_corpus"
STATES_PATH = CORPUS_DIR / "states.jsonl"
SCHEMA_PATH = CORPUS_DIR / "schema.json"
INDEX_PATH = CORPUS_DIR / "index.json"
REPORT_PATH = ROOT / "reversed" / "rea" / "state_corpus_report.md"

HAS_CORPUS = STATES_PATH.is_file() and INDEX_PATH.is_file()
pytestmark = pytest.mark.skipif(
    not HAS_CORPUS, reason="runs/state_corpus/states.jsonl 不存在"
)


@pytest.fixture(scope="module")
def corpus():
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    states = [
        json.loads(line)
        for line in STATES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return index, states


def _iter_minions(states):
    for state in states:
        for side in ("player", "opponent"):
            band = state.get(side)
            if not isinstance(band, dict):
                continue
            for minion in band.get("minions") or []:
                yield state, side, minion


def test_corpus_files_exist() -> None:
    assert STATES_PATH.is_file() and STATES_PATH.stat().st_size > 0
    assert SCHEMA_PATH.is_file()
    assert INDEX_PATH.is_file()
    assert REPORT_PATH.is_file()
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    assert index["schema"] == "bg_state_corpus.v1"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"] == "bg_state_pair.v1"
    assert "minion" in schema["definitions"] and "warband" in schema["definitions"]


def test_state_invariants(corpus) -> None:
    index, states = corpus
    assert len(states) >= 700
    ids = set()
    sources: dict = {}
    minions = 0
    hidden_state = 0
    for state in states:
        state_id = state["state_id"]
        assert state_id not in ids, f"duplicate state_id {state_id}"
        ids.add(state_id)
        assert state["schema"] == "bg_state_pair.v1"
        for key in ("trace_id", "source", "player", "opponent",
                    "visibility", "hidden_state", "hidden_reasons"):
            assert key in state
        assert state["source"] in (
            "powerlog", "hdt_bobsbuddy", "bg_last_games_xml"
        )
        sources[state["source"]] = sources.get(state["source"], 0) + 1
        if state["hidden_state"]:
            hidden_state += 1
            assert state["hidden_reasons"], state_id
        # 我方战团必须存在且有真实 minion 状态
        player = state["player"]
        assert isinstance(player, dict)
        for minion in player.get("minions") or []:
            minions += 1
            assert isinstance(minion["slot"], int) and minion["slot"] >= 0
            assert "card_id" in minion and "atk" in minion and "health" in minion
            if minion["hidden_fields"]:
                assert minion["hidden_fields"]
            # keyword_flags 必须与 keywords 一致
            flags = minion.get("keyword_flags") or {}
            present = set(minion.get("keywords") or [])
            for keyword, value in flags.items():
                assert bool(value) == (keyword in present), (state_id, keyword)
        if state["source"] == "bg_last_games_xml":
            assert state["opponent"] is None
            assert state["visibility"]["opponent"] == "hidden"
        else:
            assert isinstance(state["opponent"], dict)
            assert state["visibility"]["opponent"] == "observed"
    # 汇总与 index 一致
    summary = index["summary"]
    assert summary["states"] == len(states)
    assert summary["minions"] == sum(
        len((s.get("player") or {}).get("minions") or [])
        + len((s.get("opponent") or {}).get("minions") or [])
        for s in states
    )
    assert summary["states_hidden_state"] == hidden_state
    assert {k: v["states"] for k, v in summary["by_source"].items()} == sources
    dedupe = index["dedupe"]
    assert dedupe["loaded"] == len(states) + dedupe["duplicates_removed"]


def test_no_private_account_id(corpus) -> None:
    """语料里不能出现 XML 的账号 id / 玩家原标识。"""
    index, _ = corpus
    xml_path = Path(index["inputs"]["xml"])
    if not xml_path.is_file():
        pytest.skip("XML 源不存在")
    import xml.etree.ElementTree as ET

    root = ET.parse(xml_path).getroot()
    raw_players = {g.attrib.get("Player") for g in root.findall("Game")}
    raw_players = {p for p in raw_players if p}
    text = STATES_PATH.read_text(encoding="utf-8")
    for player in raw_players:
        assert player not in text, "state corpus 泄露了 XML 账号 id"


def test_summary_coverage_matches_states(corpus) -> None:
    index, states = corpus
    summary = index["summary"]
    unique_cards = set()
    pool_covered = set()
    pool_total = set()
    for _, _, minion in _iter_minions(states):
        card_id = minion.get("card_id")
        if card_id:
            unique_cards.add(card_id)
    assert summary["unique_cards"] == len(unique_cards)
    assert len(summary["pool_minions_uncovered"]) == (
        summary["pool_minions_total"] - summary["pool_minions_covered"]
    )
    assert summary["pool_minions_covered"] <= summary["pool_minions_total"]
    assert summary["atk_percentiles"]["count"] > 0
    assert summary["health_percentiles"]["count"] > 0
    assert summary["script_data_coverage"]["script_data_num_1"] > 0


def test_sample_validation_against_sources(corpus) -> None:
    _, states = corpus
    result = sc.validate_samples(states, sample=20)
    assert result["checked"] >= 20
    assert result["passed"] == result["checked"]
    assert result["failures"] == []


def test_export_subset_to_tmp(tmp_path: Path) -> None:
    """只取第一组 powerlog，不读 HDT/XML，验证导出管线可复现。"""
    out = tmp_path / "corpus"
    report = tmp_path / "report.md"
    index = sc.export_state_corpus(
        out_dir=out,
        report_path=report,
        powerlog_dirs=[RUNS / "official_traces_powerlog"],
        hdt_dir=tmp_path / "no-hdt",
        xml_path=tmp_path / "no.xml",
        include_xml=False,
        validate_sample=5,
    )
    states_path = out / "states.jsonl"
    assert states_path.is_file()
    lines = [json.loads(x) for x in states_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == index["summary"]["states"]
    assert all(state["source"] == "powerlog" for state in lines)
    assert all(state["boundary"] == "combat_start" for state in lines)
    assert index["dedupe"]["duplicates_removed"] == 0
    assert (out / "schema.json").is_file()
    assert report.is_file()
    validation = index["validation"]
    assert validation["failures"] == 0


def test_hidden_context_reasons_are_documented(corpus) -> None:
    index, _ = corpus
    reasons = index["summary"]["hidden_context_reason_counts"]
    assert reasons.get("trinkets_not_in_official_combat_trace_schema") or (
        0
    )
    # XML 源必须有明确的对手隐藏原因
    assert any("BgsLastGames" in reason for reason in reasons)
    # 侧级缺失字段必须与状态里的 hidden_fields 对得上
    side_fields = index["summary"]["side_hidden_field_counts"]
    assert side_fields.get("player.trinkets", 0) > 0


DEITY_FIELDS = (
    "deity_card_id", "deity_atk", "deity_health", "deity_progress",
    "deity_awakened", "deity_sigil_card_id",
)


def test_deity_fields_in_schema_and_bands(corpus) -> None:
    """每侧六字段 + 隐藏标记；有值/无值的类型都要正确。"""
    _, states = corpus
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    props = schema["definitions"]["warband"]["properties"]
    for name in DEITY_FIELDS:
        assert name in props, name
    assert props["deity_hidden"]["type"] == "boolean"
    seen_visible = 0
    for state in states:
        for side in ("player", "opponent"):
            band = state.get(side)
            if not isinstance(band, dict):
                continue
            for name in DEITY_FIELDS:
                assert name in band, (state["state_id"], side, name)
            assert isinstance(band["deity_hidden"], bool)
            if band["deity_hidden"]:
                assert band["deity_card_id"] is None
                assert "deity" in (band.get("hidden_fields") or [])
                assert band.get("deity_hidden_reason")
            elif band.get("deity_card_id") is not None:
                seen_visible += 1
                assert isinstance(band["deity_card_id"], str)
                assert isinstance(band["deity_atk"], int)
                assert isinstance(band["deity_health"], int)
                assert isinstance(band["deity_progress"], int)
                assert isinstance(band["deity_awakened"], bool)
                assert isinstance(band["deity_sigil_card_id"], str)
            else:
                # 源里没有 Deity 信号：字段 null，但不是 hidden 缺口
                assert band.get("deity_source") == "not_applicable"
                assert band.get("deity_missing_fields") == list(DEITY_FIELDS)
    assert seen_visible >= 2


def test_deity_summary_counts_match_states(corpus) -> None:
    index, states = corpus
    summary = index["summary"]["deity"]
    side_states = {"player": 0, "opponent": 0}
    card_counts: dict = {}
    states_with_any = 0
    both = 0
    for state in states:
        visible = 0
        for side in ("player", "opponent"):
            band = state.get(side)
            if not isinstance(band, dict):
                continue
            if band.get("deity_hidden") or band.get("deity_card_id") is None:
                continue
            side_states[side] += 1
            visible += 1
            card_counts[band["deity_card_id"]] = (
                card_counts.get(band["deity_card_id"], 0) + 1
            )
        if visible:
            states_with_any += 1
        if visible == 2:
            both += 1
    assert summary["states_with_any_deity"] == states_with_any
    assert summary["states_with_both_sides"] == both
    assert summary["side_states"] == side_states
    assert summary["card_id_counts"] == card_counts
    assert summary["field_present_counts"]["deity_card_id"] == sum(
        side_states.values()
    )
    assert summary["tag_mapping"]["deity_sigil_card_id"]


def test_deity_state23_matches_raw_powerlog() -> None:
    """state23/268 基础 trace（ff75… turn18）必须从原始 Power.log 重抽到 Deity。"""
    raw_log = RUNS / "powerlog_2214" / "Power.log"
    trace_path = RUNS / "official_traces_powerlog2" / "ff75d9a57e3babce.json"
    if not raw_log.is_file() or not trace_path.is_file():
        pytest.skip("原始 Power.log/trace 不存在")
    index = sc.load_card_index()
    deity_index = sc.build_deity_index(raw_log, index=index)
    trace = sc.load_trace(trace_path)
    combat = deity_index.get(trace.combat_index)
    assert combat is not None
    sides = sc._map_trace_sides_to_players(trace, combat)
    assert sides == {"player": 3, "opponent": 11}
    state = sc.state_from_trace(
        trace,
        index=index,
        tags_map=sc.load_tag_maps(),
        deity_combat=combat,
        deity_sides=sides,
    )
    player = state["player"]
    opponent = state["opponent"]
    # 真实日志：本地 C'Thun 33/33；对手 objective 87/86（战斗边界）
    assert player["deity_card_id"] == "BGFYM_000"
    assert (player["deity_atk"], player["deity_health"]) == (33, 33)
    assert player["deity_sigil_card_id"] == "BG_OldGod"
    assert opponent["deity_card_id"] == "BGFYM_000"
    assert (opponent["deity_atk"], opponent["deity_health"]) == (87, 86)
    for band in (player, opponent):
        assert band["deity_hidden"] is False
        assert band["deity_progress"] == 0
        assert band["deity_awakened"] is False
        assert band["deity_source"]


def test_deity_hidden_for_hdt_and_xml(corpus) -> None:
    _, states = corpus
    hidden_count = 0
    not_applicable = 0
    for state in states:
        if state["source"] == "powerlog":
            continue
        sides = [state.get("player")]
        if isinstance(state.get("opponent"), dict):
            sides.append(state["opponent"])
        for band in sides:
            if not isinstance(band, dict):
                continue
            if band["deity_hidden"]:
                hidden_count += 1
                assert band["deity_card_id"] is None
                assert "deity" in (band.get("hidden_fields") or [])
            else:
                not_applicable += 1
                assert band["deity_card_id"] is None
                assert band.get("deity_source") == "not_applicable"
    # 没有 Deity 实体的源：绝大多数侧 not_applicable；只有 Deity 相关卡才标 hidden
    assert hidden_count >= 1
    assert not_applicable > hidden_count
