"""Power.log 实时阶段监听器测试（合成增量文件 + 真实日志回放）。"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from hsbg.bridge.live_log import (
    DEFAULT_LOG_ROOT,
    EVENT_CHOICE_WINDOW,
    EVENT_ERROR,
    EVENT_GAME_OVER,
    EVENT_GAME_START,
    EVENT_PHASE_CHANGE,
    EVENT_PLAYER_STATE,
    EVENT_SESSION_START,
    EVENT_TURN_START,
    LiveLogEvent,
    LiveLogWatcher,
    discover_power_log,
)

ROOT = Path(__file__).resolve().parents[1]
LOG_2214 = ROOT / "runs" / "powerlog_2214" / "Power.log"
LOG_2240 = ROOT / "runs" / "powerlog_2240" / "Power.log"


def _line(content: str, source: str = "GameState.DebugPrintPower") -> str:
    return f"D 12:00:00.0000001 {source}() - {content}"


BASE_LINES = [
    _line("CREATE_GAME"),
    _line("GameEntity EntityID=7"),
    _line("    tag=GAME_SEED value=4242"),
    _line("Player EntityID=8 PlayerID=1 GameAccountId=[hi=111 lo=222]"),
    _line("    tag=CONTROLLER value=1"),
    _line("    tag=CARDTYPE value=PLAYER"),
    _line("    tag=PLAYER_ID value=1"),
    _line("    tag=HERO_ENTITY value=3"),
    _line("    tag=RESOURCES value=3"),
    _line("    tag=TEMP_RESOURCES value=1"),
    _line("    tag=RESOURCES_USED value=0"),
    _line("    tag=PLAYER_TECH_LEVEL value=1"),
    _line("    tag=HEALTH value=30"),
    _line("Player EntityID=9 PlayerID=2 GameAccountId=[hi=0 lo=0]"),
    _line("    tag=CONTROLLER value=2"),
    _line("    tag=CARDTYPE value=PLAYER"),
    _line("    tag=PLAYER_ID value=2"),
    _line("GameState.DebugPrintGame() - PlayerID=1, PlayerName=Me#1234"),
    _line("GameState.DebugPrintGame() - PlayerID=2, PlayerName=Bob"),
    _line("FULL_ENTITY - Creating ID=3 CardID=BG20_HERO_100"),
    _line("    tag=CARDTYPE value=HERO"),
    _line("    tag=CONTROLLER value=1"),
    _line("    tag=PLAYER_ID value=1"),
    _line("    tag=HEALTH value=30"),
    _line("    tag=ZONE value=PLAY"),
]

CHOICE_LINES = [
    _line("GameState.DebugPrintEntityChoices() - id=1 Player=Me#1234 "
          "TaskList=7 ChoiceType=MULLIGAN CountMin=1 CountMax=1"),
    _line("  Source=GameEntity"),
    _line("  Entities[0]=[entityName=Hero A id=110 zone=HAND zonePos=1 "
          "cardId=BG20_HERO_100 player=1]"),
    _line("  Entities[1]=[entityName=Hero B id=111 zone=HAND zonePos=2 "
          "cardId=BG20_HERO_102 player=1]"),
]

OPTION_LINES = [
    _line("  option 0 type=END_TURN mainEntity= error=INVALID errorParam="),
    _line("  option 1 type=POWER mainEntity=[entityName=刷新 id=388 zone=PLAY "
          "cardId=TB_BaconShop_8p_Reroll_Button player=1] error=NONE errorParam="),
    _line("  option 2 type=POWER mainEntity=[entityName=购买 id=400 zone=PLAY "
          "cardId=TB_BaconShop_DragBuy player=1] error=NONE errorParam="),
    _line("TAG_CHANGE Entity=8 tag=RESOURCES value=5"),
]


def _write(path: Path, lines: list[str], mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def _types(events) -> list[str]:
    return [event.type for event in events]


def test_incremental_feed_and_event_sequence(tmp_path: Path) -> None:
    log = tmp_path / "Power.log"
    _write(log, BASE_LINES)
    watcher = LiveLogWatcher(path=log, poll_interval=0.01)
    events = watcher.poll()
    assert events and events[0].type == EVENT_SESSION_START
    assert EVENT_GAME_START in _types(events)
    assert watcher.log_path == log
    assert watcher.snapshot()["attached"] is True
    assert watcher.snapshot()["game_active"] is True

    # 回合/阶段/选择窗口
    _write(log, [
        _line("TAG_CHANGE Entity=7 tag=TURN value=1"),
        _line("TAG_CHANGE Entity=7 tag=BACON_IN_COMBAT_PHASE value=0"),
    ] + CHOICE_LINES, mode="a")
    events = watcher.poll()
    types = _types(events)
    assert EVENT_TURN_START in types
    assert EVENT_PHASE_CHANGE in types
    # choice 窗口会在下一个 breaking event 时 flush；这里显式 flush
    events += watcher.flush(end_game=False)
    windows = [e for e in events if e.type == EVENT_CHOICE_WINDOW]
    assert any(w.data["kind"] == "choices" for w in windows)
    choice = next(w for w in windows if w.data["kind"] == "choices")
    assert choice.data["choice"]["entities"]
    assert choice.data["local_player_id"] == 1

    # DebugPrintOptions → options 窗口 + 我方 gold 变化
    _write(log, OPTION_LINES, mode="a")
    events = watcher.poll() + watcher.flush(end_game=False)
    windows = [e for e in events if e.type == EVENT_CHOICE_WINDOW]
    assert any(w.data["kind"] == "options" for w in windows)
    option_window = next(w for w in windows if w.data["kind"] == "options")
    cards = {opt["card_id"] for opt in option_window.data["options"]}
    assert "TB_BaconShop_DragBuy" in cards
    states = [e for e in events if e.type == EVENT_PLAYER_STATE]
    assert states
    assert any("gold" in s.data["changed"] for s in states)

    # 战斗阶段 + 结束
    _write(log, [
        _line("TAG_CHANGE Entity=7 tag=BACON_IN_COMBAT_PHASE value=1"),
        _line("TAG_CHANGE Entity=7 tag=STATE value=COMPLETE"),
    ], mode="a")
    events = watcher.poll()
    phases = [e for e in events if e.type == EVENT_PHASE_CHANGE]
    assert phases and phases[-1].data["phase"] == "combat"
    game_over = [e for e in events if e.type == EVENT_GAME_OVER]
    assert len(game_over) == 1
    assert game_over[0].data["reason"] == "state_complete"
    assert watcher.snapshot()["game_over_sent"] is True


def test_truncation_resets_session(tmp_path: Path) -> None:
    log = tmp_path / "Power.log"
    _write(log, BASE_LINES)
    watcher = LiveLogWatcher(path=log)
    first = watcher.poll()
    assert [e.type for e in first].count(EVENT_SESSION_START) == 1
    assert watcher.snapshot()["session_index"] == 1

    # 重写成更短的日志（模拟日志被截断/新一轮）
    _write(log, BASE_LINES[:6])
    events = watcher.poll()
    types = _types(events)
    assert EVENT_SESSION_START in types
    assert types.count(EVENT_SESSION_START) == 1
    assert watcher.snapshot()["session_index"] == 2
    assert watcher.snapshot()["offset"] < len(log.read_bytes()) + 1


def test_auto_discovery_switches_to_new_session(tmp_path: Path) -> None:
    root = tmp_path / "Logs"
    old_dir = root / "Hearthstone_2024_01_01_10_00_00"
    _write(old_dir / "Power.log", BASE_LINES)
    watcher = LiveLogWatcher(log_root=root, poll_interval=0.01)
    events = watcher.poll()
    assert events[0].type == EVENT_SESSION_START
    old_path = watcher.log_path
    assert old_path == old_dir / "Power.log"

    new_dir = root / "Hearthstone_2024_01_02_10_00_00"
    _write(new_dir / "Power.log", BASE_LINES)
    future = time.time() + 30
    os.utime(new_dir / "Power.log", (future, future))
    events = watcher.poll()
    types = _types(events)
    assert EVENT_SESSION_START in types
    assert watcher.log_path == new_dir / "Power.log"
    assert watcher.snapshot()["session_index"] == 2
    # 上一局未结束 → 先发 game_over(file_switched)
    assert any(
        e.type == EVENT_GAME_OVER and e.data.get("reason") == "file_switched"
        for e in events
    )


def test_discover_power_log_prefers_newest(tmp_path: Path) -> None:
    root = tmp_path / "Logs"
    _write(root / "Hearthstone_1" / "Power.log", ["a"])
    _write(root / "Hearthstone_2" / "Power.log", ["b"])
    future = time.time() + 10
    os.utime(root / "Hearthstone_2" / "Power.log", (future, future))
    assert discover_power_log(root) == root / "Hearthstone_2" / "Power.log"
    assert discover_power_log(tmp_path / "nope") is None


def test_callbacks_and_background_thread(tmp_path: Path) -> None:
    log = tmp_path / "Power.log"
    _write(log, BASE_LINES)
    seen = []
    ready = threading.Event()

    def on_event(event: LiveLogEvent) -> None:
        seen.append(event.type)
        if event.type == EVENT_GAME_START:
            ready.set()

    watcher = LiveLogWatcher(path=log, poll_interval=0.01, on_event=on_event)
    watcher.start()
    try:
        assert ready.wait(2.0), "后台线程没有产生事件"
        assert EVENT_SESSION_START in seen
        assert EVENT_GAME_START in seen
    finally:
        watcher.stop()
    assert watcher.running is False


def test_missing_file_emits_error_and_recovers(tmp_path: Path) -> None:
    path = tmp_path / "Power.log"
    watcher = LiveLogWatcher(path=path)
    events = watcher.poll()
    assert any(e.type == EVENT_ERROR for e in events)
    _write(path, BASE_LINES)
    events = watcher.poll()
    assert EVENT_SESSION_START in _types(events)
    assert watcher.snapshot()["attached"] is True


def test_tolerant_lines_without_prefix(tmp_path: Path) -> None:
    """HDT 提取片段可能首行缺 ``D hh:mm:ss`` 前缀；仍应识别 CREATE_GAME。"""
    log = tmp_path / "Power.log"
    lines = list(BASE_LINES)
    lines[0] = "GameState.DebugPrintPower() - CREATE_GAME"
    _write(log, lines)
    watcher = LiveLogWatcher(path=log)
    events = watcher.drain()
    assert EVENT_GAME_START in _types(events)


def _replay(path: Path):
    watcher = LiveLogWatcher(path=path)
    events = watcher.drain()
    return watcher, events


@pytest.mark.skipif(not LOG_2214.is_file(), reason="runs/powerlog_2214/Power.log 不存在")
def test_real_powerlog_2214_events() -> None:
    watcher, events = _replay(LOG_2214)
    types = _types(events)
    assert types.count(EVENT_SESSION_START) == 1
    assert types.count(EVENT_GAME_START) == 1
    assert types.count(EVENT_GAME_OVER) == 1
    assert watcher._local_player_id == 3
    turns = [e.data["turn"] for e in events if e.type == EVENT_TURN_START]
    assert turns == list(range(1, 21))
    phases = [e.data["phase"] for e in events if e.type == EVENT_PHASE_CHANGE]
    assert len(phases) == 19
    assert phases[0] == "combat" and phases[1] == "recruit"
    assert "combat" in phases and "recruit" in phases
    game_over = next(e for e in events if e.type == EVENT_GAME_OVER)
    assert game_over.data["local_player_id"] == 3
    assert game_over.data["reason"] in {"state_complete", "local_playstate", "watch_end"}
    assert game_over.data["result"] == "lost"
    states = [e for e in events if e.type == EVENT_PLAYER_STATE]
    assert len(states) > 20
    assert states[-1].data["player_id"] == 3
    assert set(("gold", "tier", "hero_health")) <= set(states[-1].data)
    windows = [e for e in events if e.type == EVENT_CHOICE_WINDOW]
    assert any(w.data["kind"] == "options" for w in windows)
    assert any(w.data["kind"] == "choices" for w in windows)
    assert not [e for e in events if e.type == EVENT_ERROR]


@pytest.mark.skipif(not LOG_2240.is_file(), reason="runs/powerlog_2240/Power.log 不存在")
def test_real_powerlog_2240_events() -> None:
    watcher, events = _replay(LOG_2240)
    types = _types(events)
    # 该文件首行缺 "D hh:mm:ss" 前缀，但监听器应容错识别
    assert types.count(EVENT_GAME_START) == 1
    assert types.count(EVENT_GAME_OVER) == 1
    assert watcher._local_player_id == 4
    turns = [e.data["turn"] for e in events if e.type == EVENT_TURN_START]
    assert turns == list(range(1, 21))
    phases = [e.data["phase"] for e in events if e.type == EVENT_PHASE_CHANGE]
    assert len(phases) == 19
    game_over = next(e for e in events if e.type == EVENT_GAME_OVER)
    assert game_over.data["reason"] in {"state_complete", "local_playstate", "watch_end"}
    assert any(e.type == EVENT_PLAYER_STATE for e in events)


def test_default_log_root_is_game_logs() -> None:
    assert DEFAULT_LOG_ROOT.name == "Logs"
    assert "Hearthstone" in str(DEFAULT_LOG_ROOT)
