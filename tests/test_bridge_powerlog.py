"""Power.log 解析器原型测试（不依赖真实日志）。"""

from __future__ import annotations

import json

from hsbg.bridge.powerlog import (
    EVENT_BLOCK_END,
    EVENT_BLOCK_START,
    EVENT_CHANGE_ENTITY,
    EVENT_CHOICE,
    EVENT_CREATE_GAME,
    EVENT_ENTITY_TAG,
    EVENT_FULL_ENTITY,
    EVENT_GAME_ENTITY,
    EVENT_OPTION,
    EVENT_PLAYER,
    EVENT_PLAYER_NAME,
    EVENT_SHOW_ENTITY,
    EVENT_TAG_CHANGE,
    EVENT_UNKNOWN,
    LINE_RE,
    PowerLogParser,
    PowerLogEvent,
)

# 一局极小的真实格式日志：两个玩家、一个英雄、一个随从，买卖 + 战斗 block。
SAMPLE_LINES = [
    "D 16:00:00.1000000 GameState.DebugPrintPower() - CREATE_GAME",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - GameEntity EntityID=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=GAME_SEED value=424242",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - Player EntityID=2 PlayerID=1 GameAccountId=[hi=11 lo=22]",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=PLAYER_ID value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=HERO_ENTITY value=3",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=HEALTH value=40",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=ARMOR value=2",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=RESOURCES value=3",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=TEMP_RESOURCES value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=RESOURCES_USED value=2",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=PLAYER_TECH_LEVEL value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=TURN value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - Player EntityID=9 PlayerID=5 GameAccountId=[hi=33 lo=44]",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=PLAYER_ID value=5",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=HEALTH value=38",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=3 CardID=BG20_HERO_100",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=CARDTYPE value=HERO",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=ZONE value=PLAY",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=64 CardID=",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
    "D 16:00:00.1000000 GameState.DebugPrintPower() -     tag=ZONE value=SETASIDE",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - FULL_ENTITY - Updating "
    "[entityName=Alleycat id=64 zone=HAND zonePos=1 cardId=BG20_100 player=1] CardID=",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE "
    "Entity=[entityName=Alleycat id=64 zone=HAND zonePos=1 cardId=BG20_100 player=1] "
    "tag=ZONE value=PLAY",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE "
    "Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] "
    "tag=ATK value=2",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE "
    "Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] "
    "tag=HEALTH value=3",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - SHOW_ENTITY - Updating "
    "Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] "
    "CardID=BG20_100",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_START BlockType=PLAY "
    "Entity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] "
    "EffectCardId= EffectIndex=0 Target=0 SubOption=-1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_END",
    "D 16:00:00.1000000 GameState.DebugPrintOptions() - option 0 type=END_TURN mainEntity= error=INVALID",
    "D 16:00:00.1000000 GameState.DebugPrintOptions() - option 1 type=POWER "
    "mainEntity=[entityName=Alleycat id=64 zone=PLAY zonePos=1 cardId=BG20_100 player=1] error=INVALID",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=BACON_IN_COMBAT_PHASE value=1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=GameEntity tag=TURN value=2",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_START BlockType=TRIGGER "
    "Entity=GameEntity EffectCardId= EffectIndex=14 Target=0 SubOption=-1",
    "D 16:00:00.1000000 GameState.DebugPrintPower() - BLOCK_END",
]


def _parser_with_sample(**kwargs) -> PowerLogParser:
    parser = PowerLogParser(**kwargs)
    parser.feed_lines(SAMPLE_LINES)
    return parser


def test_line_regex_matches_real_format() -> None:
    match = LINE_RE.match(
        "D 15:31:06.1234567 GameState.DebugPrintPower() - CREATE_GAME"
    )
    assert match is not None
    assert match.group("level") == "D"
    assert match.group("ts") == "15:31:06.1234567"
    assert match.group("source") == "GameState.DebugPrintPower"
    assert match.group("content") == "CREATE_GAME"


def test_feed_returns_event_per_line() -> None:
    parser = PowerLogParser()
    events = list(parser.feed_lines(SAMPLE_LINES))
    assert len(events) == len(SAMPLE_LINES)
    assert all(isinstance(event, PowerLogEvent) for event in events)
    kinds = [event.kind for event in events]
    assert EVENT_CREATE_GAME in kinds
    assert EVENT_GAME_ENTITY in kinds
    assert EVENT_PLAYER in kinds
    assert EVENT_FULL_ENTITY in kinds
    assert EVENT_SHOW_ENTITY in kinds
    assert EVENT_TAG_CHANGE in kinds
    assert EVENT_BLOCK_START in kinds
    assert EVENT_BLOCK_END in kinds
    assert EVENT_ENTITY_TAG in kinds
    assert EVENT_OPTION in kinds


def test_entities_and_tags_are_maintained() -> None:
    parser = _parser_with_sample()
    alleycat = parser.entity(64)
    assert alleycat is not None
    assert alleycat.card_id == "BG20_100"
    assert alleycat.zone == "PLAY"
    assert alleycat.tag("CARDTYPE") == "MINION"
    assert alleycat.int_tag("ATK") == 2
    assert alleycat.int_tag("HEALTH") == 3
    assert parser.card_id(64) == "BG20_100"
    assert parser.tag(64, "ZONE") == "PLAY"
    assert parser.int_tag(999, "ATK", default=-1) == -1


def test_game_header_and_players() -> None:
    parser = _parser_with_sample()
    assert parser.game_index == 1
    assert parser.game_seed == 424242
    assert parser.turn == 2
    assert parser.phase == "combat"
    state = parser.game_state()
    players = {row["player_id"]: row for row in state["players"]}
    assert set(players) == {1, 5}
    assert players[1]["health"] == 40
    assert players[1]["armor"] == 2
    # gold = RESOURCES + TEMP_RESOURCES - RESOURCES_USED
    assert players[1]["gold"] == 2
    assert players[1]["hero_entity_id"] == 3
    assert players[1]["hero_card_id"] == "BG20_HERO_100"
    # GameAccountId 不应出现在任何快照字段里（隐私）
    assert "1234" not in json.dumps(state)
    assert "GameAccountId" not in json.dumps(state)


def test_show_entity_reveals_card_id() -> None:
    parser = PowerLogParser()
    for line in [
        "D 16:00:00.1 GameState.DebugPrintPower() - FULL_ENTITY - Creating ID=70 CardID=",
        "D 16:00:00.1 GameState.DebugPrintPower() -     tag=CARDTYPE value=MINION",
        "D 16:00:00.1 GameState.DebugPrintPower() - SHOW_ENTITY - Updating "
        "Entity=[entityName=Secret Token id=70 zone=PLAY zonePos=1 cardId= player=2] "
        "CardID=BG_FAKE_001",
    ]:
        parser.feed(line)
    assert parser.entity(70) is not None
    assert parser.card_id(70) == "BG_FAKE_001"
    assert parser.tag(70, "CARDTYPE") == "MINION"


def test_block_start_and_end_stack() -> None:
    parser = _parser_with_sample()
    starts = [e for e in parser.events if e.kind == EVENT_BLOCK_START]
    ends = [e for e in parser.events if e.kind == EVENT_BLOCK_END]
    assert [e.block_type for e in starts] == ["PLAY", "TRIGGER"]
    assert len(ends) == 2
    assert parser.blocks == []  # 全部闭合
    assert parser.stats["blocks_started"] == 2
    assert parser.stats["blocks_ended"] == 2


def test_block_end_without_start_is_tolerated() -> None:
    parser = PowerLogParser()
    events = parser.feed("D 16:00:00.1 GameState.DebugPrintPower() - BLOCK_END")
    assert len(events) == 1
    assert events[0].kind == EVENT_BLOCK_END
    assert events[0].block_type == ""


def test_unknown_and_malformed_lines_do_not_crash() -> None:
    parser = PowerLogParser()
    for line in [
        "这不是一行日志",
        "",
        "D 16:00:00.1 GameState.DebugPrintPower() - 未来未知行",
        "D 坏行",
        "E 16:00:00.1 GameState.SomeThing() - ???",
    ]:
        parser.feed(line)
    summary = parser.summary()
    assert summary["unknown_lines"] >= 2
    assert summary["parse_errors"] == 0
    assert summary["lines_total"] == 4  # 空行不计
    # 未知行也进入事件流，便于诊断
    assert any(e.kind == EVENT_UNKNOWN for e in parser.events)


def test_tasklist_lines_skipped_by_default() -> None:
    parser = PowerLogParser()
    parser.feed("D 16:00:00.1 GameState.DebugPrintPower() - CREATE_GAME")
    events = parser.feed(
        "D 16:00:00.1 PowerTaskList.DebugPrintPower() - TAG_CHANGE Entity=1 tag=TURN value=9"
    )
    assert events == []
    assert parser.stats["tasklist_lines"] == 1
    assert parser.turn == 0  # 重复消息没有被重复计入

    parser2 = PowerLogParser(include_tasklist=True)
    events2 = parser2.feed(
        "D 16:00:00.1 PowerTaskList.DebugPrintPower() - TAG_CHANGE Entity=1 tag=TURN value=9"
    )
    assert len(events2) == 1
    assert events2[0].kind == EVENT_TAG_CHANGE


def test_options_and_choices_are_recorded() -> None:
    parser = PowerLogParser()
    parser.feed(
        "D 16:00:00.1 GameState.DebugPrintOptions() - "
        "option 0 type=END_TURN mainEntity= error=INVALID"
    )
    parser.feed(
        "D 16:00:00.1 GameState.DebugPrintOptions() - "
        "option 1 type=POWER mainEntity=64 error=INVALID"
    )
    assert len(parser.last_options) == 2
    assert parser.last_options[1]["type"] == "POWER"
    parser.feed(
        "D 16:00:00.1 GameState.DebugPrintEntityChoices() - "
        "id=1 Player=Bob TaskList= ChoiceType=GENERAL CountMin=0 CountMax=1"
    )
    assert parser.last_choice is not None
    assert parser.last_choice["choice_type"] == "GENERAL"
    assert [e.kind for e in parser.events].count(EVENT_CHOICE) == 1


def test_player_name_not_captured_by_default() -> None:
    parser = PowerLogParser()
    parser.feed("D 16:00:00.1 GameState.DebugPrintGame() - PlayerID=1, PlayerName=Secret#1234")
    assert any(e.kind == EVENT_PLAYER_NAME for e in parser.events)
    assert parser.entities == {}  # 没有玩家实体时也不会创建/保存昵称

    parser2 = PowerLogParser(capture_player_names=True)
    parser2.feed("D 16:00:00.1 GameState.DebugPrintPower() - Player EntityID=2 PlayerID=1")
    parser2.feed("D 16:00:00.1 GameState.DebugPrintGame() - PlayerID=1, PlayerName=Tester#1")
    assert parser2.entity(2) is not None
    assert parser2.entity(2).name == "Tester#1"


def test_create_game_resets_state_and_increments_index() -> None:
    parser = _parser_with_sample()
    assert parser.entity(64) is not None
    parser.feed("D 16:10:00.1 GameState.DebugPrintPower() - CREATE_GAME")
    assert parser.game_index == 2
    assert parser.entities == {}
    assert parser.players == {}
    assert parser.turn == 0
    assert parser.stats["create_game"] == 2


def test_unresolved_entity_reference_is_counted_but_tolerated() -> None:
    parser = PowerLogParser()
    event = parser.feed(
        "D 16:00:00.1 GameState.DebugPrintPower() - TAG_CHANGE "
        "Entity=[entityName=Ghost id=999 zone=PLAY] tag=ATK value=9"
    )[0]
    # 引用完全无法解析时：不抛异常、不产生 tag_change，只计数
    other = parser.feed(
        "D 16:00:00.1 GameState.DebugPrintPower() - TAG_CHANGE Entity=UnknownThing tag=ATK value=9"
    )[0]
    assert event.kind == EVENT_TAG_CHANGE
    assert other.kind not in (EVENT_TAG_CHANGE,)
    assert parser.stats["unresolved_entity_refs"] == 1


def test_game_state_is_json_serializable() -> None:
    parser = _parser_with_sample()
    state = parser.game_state()
    text = json.dumps(state, ensure_ascii=False)
    assert isinstance(text, str) and len(text) > 100
    assert state["entities"]["64"]["card_id"] == "BG20_100"
    assert state["stats"]["lines_total"] == len(SAMPLE_LINES)


def test_feed_file_reads_utf8_and_handles_bom(tmp_path) -> None:
    log = tmp_path / "Power.log"
    log.write_text("\ufeff" + "\n".join(SAMPLE_LINES) + "\n", encoding="utf-8")
    parser = PowerLogParser()
    count = parser.feed_file(log)
    assert count == len(SAMPLE_LINES)
    assert parser.stats["lines_total"] == len(SAMPLE_LINES)
    # BOM 行不应导致解析异常（归为 unknown / 忽略）
    assert parser.stats["parse_errors"] == 0


def test_feed_file_tail_bytes_skips_partial_line(tmp_path) -> None:
    log = tmp_path / "Power.log"
    log.write_text("\n".join(SAMPLE_LINES) + "\n", encoding="utf-8")
    parser = PowerLogParser()
    parser.feed_file(log, tail_bytes=200)
    # 只读末尾，不应产生解析异常
    assert parser.stats["parse_errors"] == 0
    assert parser.stats["lines_total"] > 0


def test_change_entity_event_kind() -> None:
    parser = PowerLogParser()
    parser.feed(
        "D 16:00:00.1 GameState.DebugPrintPower() - CHANGE_ENTITY - Updating "
        "Entity=[entityName=Token id=80 zone=PLAY cardId= player=1] CardID=BG_FAKE_002"
    )
    events = [e for e in parser.events if e.kind == EVENT_CHANGE_ENTITY]
    assert len(events) == 1
    assert events[0].card_id == "BG_FAKE_002"
    assert parser.card_id(80) == "BG_FAKE_002"


def test_event_to_dict_roundtrip() -> None:
    parser = _parser_with_sample()
    first = parser.events[0]
    assert first.to_dict()["kind"] == EVENT_CREATE_GAME
    assert json.dumps([e.to_dict() for e in parser.events], ensure_ascii=False)
