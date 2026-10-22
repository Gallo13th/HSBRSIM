"""Power.log 实时阶段监听器（纯本地、只读）。

给 bot runner 用：轮询/回调地告诉你"现在是什么阶段、轮到第几回合、我方
gold/tier/英雄血量、什么时候出现选择窗口、什么时候对局结束"。

严格边界
--------
**Power.log 看不到酒馆商店 offer（买什么/刷出什么）**。那是客户端内存里的状态，
需要 rea-operator 的内存读取才能补；本模块只负责：

* 日志目录轮转/新会话切换（``Logs/Hearthstone_*/Power.log``）；
* 增量 tail（byte offset、截断/重写检测）；
* 结构化事件：``session_start`` / ``game_start`` / ``turn_start`` /
  ``phase_change``（``BACON_IN_COMBAT_PHASE``）/ ``game_over`` /
  ``choice_window``（DebugPrintOptions / EntityChoices）/ ``player_state``
  （我方 gold / tier / hero health 变化）；
* 线程安全的 ``LiveLogWatcher(path=None, poll_interval=0.05)``。

用法::

    watcher = LiveLogWatcher()                 # 自动找最新 Logs/Hearthstone_*/Power.log
    watcher.on("turn_start", lambda ev: print(ev.data["turn"]))
    watcher.on("phase_change", lambda ev: runner.on_phase(ev.data["phase"]))
    watcher.start()                            # 后台线程轮询；runner 也可以自己 poll()

    # 或手动轮询：
    watcher = LiveLogWatcher(path=".../Power.log")
    while True:
        for event in watcher.poll():
            ...

局限
----
* 商店 offer / 手牌详情 / 内存型隐藏信息**不在 Power.log 里**；
* 日志行可能延迟/乱序，``choice_window`` 代表"服务端已下发选项"，不代表一定
  要立刻操作；
* 所有解析复用 ``hsbg.bridge.powerlog.PowerLogParser`` 的口径；本模块不写入任何
  游戏文件、不读进程内存、不自动点击。
"""

from __future__ import annotations

import collections
import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .powerlog import (
    EVENT_CHANGE_ENTITY,
    EVENT_CHOICE,
    EVENT_CREATE_GAME,
    EVENT_FULL_ENTITY,
    EVENT_GAME_ENTITY,
    EVENT_OPTION,
    EVENT_PLAYER,
    EVENT_PLAYER_NAME,
    EVENT_SHOW_ENTITY,
    EVENT_TAG_CHANGE,
    PowerLogParser,
)

#: 默认日志根目录（只读）
DEFAULT_LOG_ROOT = Path(r"C:\Program Files (x86)\Hearthstone\Logs")

# ── 事件类型 ──────────────────────────────────────────────────────────
EVENT_SESSION_START = "session_start"
EVENT_GAME_START = "game_start"
EVENT_TURN_START = "turn_start"
EVENT_PHASE_CHANGE = "phase_change"
EVENT_GAME_OVER = "game_over"
EVENT_CHOICE_WINDOW = "choice_window"
EVENT_PLAYER_STATE = "player_state"
EVENT_ERROR = "error"

#: 这些事件代表"一个新阶段/新动作"，遇到时先把未完成的选择窗口 flush 掉。
#: 注意 ``EVENT_OTHER``（如 EntityChoices 的 ``Source=`` 行）不能触发 flush，
#: 否则 choice 的 ``Entities[...]`` 还没读到就被提前发出来了。
_WINDOW_BREAKING_KINDS = frozenset({
    EVENT_CREATE_GAME,
    EVENT_TAG_CHANGE,
    EVENT_PLAYER,
    EVENT_FULL_ENTITY,
    EVENT_SHOW_ENTITY,
    EVENT_CHANGE_ENTITY,
    EVENT_GAME_ENTITY,
    "block_start",
})

#: 本地玩家会操作的按钮/拖拽实体（用于从 DebugPrintOptions 反推本地 Player 实体）
_LOCAL_CONTROL_PREFIXES = (
    "TB_BaconShop_DragBuy",
    "TB_BaconShop_DragSell",
    "TB_BaconShop_8p_Reroll_Button",
    "TB_BaconShop_8P_Reroll_Button",
    "TB_BaconShopTechUp",
    "TB_BaconShop_8p_Freeze_Button",
    "TB_BaconShop_8P_Freeze_Button",
)
_PLAYER_NAME_RE = re.compile(r"PlayerID=(\d+),\s*PlayerName=(.*)$")
_ENTITY_PLAYER_RE = re.compile(r"\bplayer=(\d+)")
_ENTITY_ID_RE = re.compile(r"\bid=(\d+)")
_CARD_ID_RE = re.compile(r"\bcardId=(\S+)")
_TERMINAL_PLAYSTATES = {"LOST", "WON", "TIED", "CONCEDED", "WONBUTTIE"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def discover_power_log(log_root: Optional[Path | str] = None) -> Optional[Path]:
    """找最新的 ``Logs/Power.log`` 或 ``Logs/Hearthstone_*/Power.log``。

    取 ``(mtime, 目录名)`` 最大者；没有日志返回 ``None``。
    """
    root = Path(log_root or DEFAULT_LOG_ROOT)
    candidates: List[Path] = []
    direct = root / "Power.log"
    if direct.is_file():
        candidates.append(direct)
    try:
        for directory in root.glob("Hearthstone_*"):
            path = directory / "Power.log"
            if path.is_file():
                candidates.append(path)
    except OSError:
        pass
    if not candidates:
        return None

    def key(path: Path) -> tuple:
        try:
            stat = path.stat()
            return (stat.st_mtime, path.parent.name, str(path))
        except OSError:
            return (0.0, "", str(path))

    return max(candidates, key=key)


@dataclass(frozen=True)
class LiveLogEvent:
    """监听器输出的一条结构化事件。"""

    type: str
    data: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    log_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            "log_path": self.log_path,
            "data": dict(self.data),
        }


class LiveLogWatcher:
    """Power.log 增量 tail + 事件回调（线程安全）。

    Parameters
    ----------
    path:
        显式 ``Power.log`` 路径；``None`` 时自动从 ``log_root`` 找最新的
        ``Hearthstone_*/Power.log``。
    poll_interval:
        后台线程轮询间隔（秒，默认 0.05）。
    log_root:
        自动发现日志的根目录（默认 ``C:\\Program Files (x86)\\Hearthstone\\Logs``）。
    local_player_id:
        显式指定本地 PlayerID（默认自动推断：DebugPrintGame/EntityChoices/
        DebugPrintOptions 的本地控制实体）。
    on_event:
        可选的总回调（等价于 ``on("*", cb)``）。
    include_tasklist:
        是否也解析 ``PowerTaskList.*``（默认 False；实时监听不需要重复消息）。
    """

    def __init__(
        self,
        path: Optional[Path | str] = None,
        poll_interval: float = 0.05,
        *,
        log_root: Optional[Path | str] = None,
        local_player_id: Optional[int] = None,
        on_event: Optional[Callable[[LiveLogEvent], None]] = None,
        include_tasklist: bool = False,
    ) -> None:
        self._explicit_path = Path(path) if path else None
        self.poll_interval = max(0.005, float(poll_interval))
        self.log_root = Path(log_root or DEFAULT_LOG_ROOT)
        self._local_override = local_player_id
        self.include_tasklist = bool(include_tasklist)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callbacks: Dict[str, List[Callable[[LiveLogEvent], None]]] = (
            collections.defaultdict(list)
        )
        if on_event is not None:
            self.on("*", on_event)

        self._parser = self._new_parser()
        self.log_path: Optional[Path] = None
        self._offset = 0
        self._buffer = b""
        self._identity: Optional[tuple] = None
        self._session_index = 0
        self._session_id: Optional[str] = None
        self._attached = False
        self._last_missing: Optional[str] = None
        self._errors = 0
        self._last_error: Optional[str] = None
        self._bytes_read = 0
        self._pending_error_events: List[LiveLogEvent] = []

        # 每局状态
        self._game_active = False
        self._game_over_sent = False
        self._turn: Optional[int] = None
        self._phase: Optional[str] = None
        self._local_player_id: Optional[int] = local_player_id
        self._player_names: Dict[int, str] = {}
        self._player_has_account: Dict[int, bool] = {}
        self._pending_options: Optional[List[Dict[str, Any]]] = None
        self._pending_choice: Optional[Dict[str, Any]] = None
        self._last_player_state: Optional[tuple] = None
        self._local_hero_entity_id: Optional[int] = None
        self._tag_transfer_entity_id: Optional[int] = None

    # ── 生命周期 ────────────────────────────────────────────────────
    def start(self) -> "LiveLogWatcher":
        """启动后台轮询线程（幂等）。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="hsbg-live-log", daemon=True
            )
            self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        """停止后台线程并 flush 未完成事件。"""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None
        self.flush()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def close(self) -> None:
        self.stop()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll()
            except Exception as exc:  # noqa: BLE001 - 后台线程绝不因异常退出
                with self._lock:
                    self._record_error(f"poll loop: {type(exc).__name__}: {exc}")
            self._stop.wait(self.poll_interval)

    # ── 回调注册 ────────────────────────────────────────────────────
    def on(self, event_type: str, callback: Callable[[LiveLogEvent], None]) -> "LiveLogWatcher":
        """注册回调；``event_type="*"`` 表示所有事件。"""
        if not callable(callback):
            raise TypeError("callback 必须可调用")
        with self._lock:
            self._callbacks[str(event_type)].append(callback)
        return self

    def off(self, event_type: str, callback: Callable[[LiveLogEvent], None]) -> None:
        with self._lock:
            try:
                self._callbacks[str(event_type)].remove(callback)
            except ValueError:
                pass

    # ── 轮询/读取 ───────────────────────────────────────────────────
    def poll(self) -> List[LiveLogEvent]:
        """读取新增字节、解析并返回本次产生的事件（同时触发回调）。"""
        with self._lock:
            events = self._poll_locked()
            if self._pending_error_events:
                events.extend(self._pending_error_events)
                self._pending_error_events = []
        for event in events:
            self._dispatch(event)
        return events

    def drain(self, max_polls: int = 1000) -> List[LiveLogEvent]:
        """回放已存在的静态文件：反复 poll 直到无新字节，再 flush。"""
        out: List[LiveLogEvent] = []
        idle = 0
        for _ in range(max(1, int(max_polls))):
            with self._lock:
                before = self._offset
            events = self.poll()
            out.extend(events)
            with self._lock:
                new_bytes = self._offset - before
            if new_bytes == 0 and not events:
                idle += 1
                if idle >= 2:
                    break
            else:
                idle = 0
        out.extend(self.flush())
        return out

    def flush(
        self, reason: str = "watch_end", *, end_game: bool = True
    ) -> List[LiveLogEvent]:
        """冲刷未完成窗口；``end_game=True`` 时若对局仍未结束补发 ``game_over``。

        实时 tail 中不要主动调用（文件可能继续增长）；回放/stop 时使用。
        只想强制发出 ``choice_window``、但不想结束对局时传 ``end_game=False``。
        """
        with self._lock:
            events: List[LiveLogEvent] = []
            events.extend(self._flush_windows())
            if end_game and self._game_active and not self._game_over_sent:
                events.append(
                    self._emit(
                        EVENT_GAME_OVER,
                        {
                            "reason": reason,
                            "turn": self._turn,
                            "result": None,
                            "placement": None,
                        },
                    )
                )
                self._game_over_sent = True
                self._game_active = False
        for event in events:
            self._dispatch(event)
        return events

    def snapshot(self) -> Dict[str, Any]:
        """当前状态快照（供 runner 查询，不消费事件）。"""
        with self._lock:
            state = self._parser.game_state()
            gold, tier, health = self._local_player_values()
            return {
                "log_path": str(self.log_path) if self.log_path else None,
                "attached": self._attached,
                "offset": self._offset,
                "session_id": self._session_id,
                "session_index": self._session_index,
                "errors": self._errors,
                "last_error": self._last_error,
                "game_active": self._game_active,
                "game_over_sent": self._game_over_sent,
                "turn": self._turn or state.get("turn"),
                "phase": self._phase or state.get("phase"),
                "local_player_id": self._local_player_id,
                "gold": gold,
                "tier": tier,
                "hero_health": health,
                "pending_choice_window": bool(
                    self._pending_options or self._pending_choice
                ),
                "parser": state,
            }

    # ── 主轮询逻辑（持锁）──────────────────────────────────────────
    def _poll_locked(self) -> List[LiveLogEvent]:
        events: List[LiveLogEvent] = []
        path = self._resolve_path()
        if path is None:
            self._record_missing()
            return events
        if not self._attached or self.log_path != path:
            events.extend(self._switch_session(path, reason="file_switched"))
        try:
            stat = path.stat()
        except OSError as exc:
            self._record_error(f"stat {path}: {exc}")
            self._attached = False
            return events
        identity = (stat.st_dev, stat.st_ino)
        if self._identity is not None and identity != self._identity:
            events.extend(self._switch_session(path, reason="log_replaced"))
            try:
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
            except OSError:
                return events
        if stat.st_size < self._offset:
            events.extend(self._switch_session(path, reason="log_truncated"))
            try:
                stat = path.stat()
            except OSError:
                return events
        if stat.st_size == self._offset:
            return events
        try:
            with path.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read(stat.st_size - self._offset)
        except OSError as exc:
            self._record_error(f"read {path}: {exc}")
            return events
        if not data:
            return events
        self._offset += len(data)
        self._bytes_read += len(data)
        self._buffer += data
        lines = self._buffer.split(b"\n")
        self._buffer = lines.pop() if lines else b""
        if len(self._buffer) > 4 * 1024 * 1024:  # 异常超长行，丢弃并重建
            self._record_error("log line exceeds 4MiB; dropping partial buffer")
            self._buffer = b""
        for raw in lines:
            text = raw.decode("utf-8", errors="replace").rstrip("\r")
            events.extend(self._handle_line(text))
        return events

    def _resolve_path(self) -> Optional[Path]:
        if self._explicit_path is not None:
            path = self._explicit_path
            if path.is_dir():
                return discover_power_log(path)
            return path if path.is_file() else None
        return discover_power_log(self.log_root)

    def _switch_session(self, path: Path, *, reason: str) -> List[LiveLogEvent]:
        events: List[LiveLogEvent] = []
        if self._attached:
            events.extend(self._flush_windows())
            if self._game_active and not self._game_over_sent:
                events.append(
                    self._emit(
                        EVENT_GAME_OVER,
                        {"reason": reason, "turn": self._turn,
                         "result": None, "placement": None},
                    )
                )
                self._game_over_sent = True
                self._game_active = False
        self.log_path = path
        self._parser = self._new_parser()
        self._offset = 0
        self._buffer = b""
        self._bytes_read = 0
        self._attached = True
        self._last_missing = None
        try:
            stat = path.stat()
            self._identity = (stat.st_dev, stat.st_ino)
        except OSError:
            self._identity = None
        self._session_index += 1
        try:
            stat = path.stat()
            identity = f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}"
        except OSError:
            identity = str(path)
        self._session_id = _sha(str(path) + "|" + identity)
        self._local_player_id = self._local_override
        self._player_names.clear()
        self._player_has_account.clear()
        self._turn = None
        self._phase = None
        self._last_player_state = None
        self._local_hero_entity_id = None
        self._tag_transfer_entity_id = None
        self._game_active = False
        self._game_over_sent = False
        self._pending_options = None
        self._pending_choice = None
        events.append(
            self._emit(
                EVENT_SESSION_START,
                {
                    "path": str(path),
                    "session_id": self._session_id,
                    "session_index": self._session_index,
                    "reason": reason,
                },
            )
        )
        return events

    def _new_parser(self) -> PowerLogParser:
        # capture_player_names=True 只在内存中保存 PlayerName，用于把
        # DebugPrintGame/EntityChoices 的名字映射到 PlayerID；不落盘。
        return PowerLogParser(
            include_tasklist=self.include_tasklist,
            capture_player_names=True,
        )

    def _record_missing(self) -> None:
        text = f"no Power.log under {self._explicit_path or self.log_root}"
        if self._last_missing != text:
            self._last_missing = text
            self._record_error(text)

    def _record_error(self, message: str) -> None:
        self._errors += 1
        self._last_error = message
        self._pending_error_events.append(
            self._emit_locked(
                EVENT_ERROR,
                {
                    "message": message,
                    "log_path": str(self.log_path) if self.log_path else None,
                },
            )
        )

    # ── 单行 → PowerLogParser → 结构化事件 ─────────────────────────
    def _handle_line(self, line: str) -> List[LiveLogEvent]:
        text = line.strip()
        if not text:
            return []
        # 真实 tail 的行都带 "D hh:mm:ss..." 前缀；但 HDT/旧提取片段可能丢掉
        # 前缀（例如首行 "GameState.DebugPrintPower() - CREATE_GAME"）。
        # 这种行补一个合成前缀再喂解析器，避免整局事件丢失。
        if (
            not text.startswith(("D ", "I ", "W ", "E "))
            and "() - " in text
        ):
            text = "D 00:00:00.0000000 " + text
        events: List[LiveLogEvent] = []
        for parsed in self._parser.feed(text):
            events.extend(self._handle_parser_event(parsed))
        return events

    def _handle_parser_event(self, event: Any) -> List[LiveLogEvent]:
        kind = event.kind
        out: List[LiveLogEvent] = []
        # 先处理需要"打断"窗口聚合的事件（TAG_CHANGE/FULL_ENTITY 等）
        if kind in _WINDOW_BREAKING_KINDS:
            out.extend(self._flush_windows())

        if kind == EVENT_CREATE_GAME:
            self._game_active = True
            self._game_over_sent = False
            self._turn = None
            self._phase = None
            self._last_player_state = None
            self._local_hero_entity_id = None
            self._tag_transfer_entity_id = None
            out.append(
                self._emit(
                    EVENT_GAME_START,
                    {
                        "game_index": self._parser.game_index,
                        "seed": self._parser.game_seed or None,
                        "local_player_id": self._local_player_id,
                    },
                )
            )
            return out

        if kind == EVENT_PLAYER:
            player_id = event.data.get("player_id")
            if isinstance(player_id, int):
                self._player_has_account[player_id] = bool(
                    event.data.get("has_account_id")
                )
            return out

        if kind == EVENT_PLAYER_NAME:
            match = _PLAYER_NAME_RE.search(event.text or "")
            if match:
                player_id = int(match.group(1))
                name = match.group(2).strip()
                self._player_names[player_id] = name
                self._maybe_set_local_from_name(name)
            return out

        if kind == EVENT_TAG_CHANGE:
            out.extend(self._handle_tag_change(event))
            out.extend(self._maybe_player_state())
            return out

        if kind == EVENT_OPTION:
            option = dict(event.data)
            number = option.get("option")
            if number == 0 or self._pending_options is None:
                if self._pending_options is not None or self._pending_choice is not None:
                    out.extend(self._flush_windows())
                self._pending_options = []
            self._pending_options.append(option)
            self._maybe_set_local_from_option(option)
            out.extend(self._maybe_player_state())
            return out

        if kind == EVENT_CHOICE:
            data = dict(event.data)
            if "choice_type" in data and "player" in data:
                # EntityChoices 头行：新窗口
                if self._pending_choice is not None:
                    out.extend(self._flush_windows())
                self._pending_choice = {
                    "choice_id": data.get("id"),
                    "player_name": data.get("player"),
                    "choice_type": data.get("choice_type"),
                    "count_min": data.get("count_min"),
                    "count_max": data.get("count_max"),
                    "entities": {},
                }
                self._maybe_set_local_from_name(str(data.get("player") or ""))
            elif "choice_entity" in data and self._pending_choice is not None:
                self._pending_choice["entities"][int(data["choice_entity"])] = (
                    event.text or ""
                )
            out.extend(self._maybe_player_state())
            return out

        # 其他事件只用于更新本地玩家推断/状态
        out.extend(self._maybe_player_state())
        return out

    def _handle_tag_change(self, event: Any) -> List[LiveLogEvent]:
        out: List[LiveLogEvent] = []
        tag = str(event.tag or "")
        value = str(event.value or "")
        self._remember_local_entities(event)
        if tag == "TURN":
            # 只把 GameEntity 的 TURN 当“回合推进”；玩家/Bob 实体也有 TURN 副本。
            game_eid = self._parser.game_entity_id
            if game_eid and event.entity_id != game_eid:
                return out
            try:
                turn = int(value)
            except ValueError:
                return out
            if turn > 0 and turn != self._turn:
                previous = self._turn
                self._turn = turn
                out.append(
                    self._emit(
                        EVENT_TURN_START,
                        {"turn": turn, "previous": previous,
                         "phase": self._phase, "local_player_id": self._local_player_id},
                    )
                )
        elif tag == "BACON_IN_COMBAT_PHASE":
            phase = "combat" if value not in ("0", "", "false", "False") else "recruit"
            if phase != self._phase:
                previous = self._phase
                self._phase = phase
                out.append(
                    self._emit(
                        EVENT_PHASE_CHANGE,
                        {"phase": phase, "previous": previous, "turn": self._turn,
                         "local_player_id": self._local_player_id},
                    )
                )
        elif tag == "STATE" and value.upper() == "COMPLETE":
            # GameEntity 的 STATE=COMPLETE 是官方对局结束信号
            if event.entity_id == self._parser.game_entity_id:
                out.extend(self._emit_game_over(reason="state_complete"))
        elif tag == "PLAYSTATE":
            if self._is_local_entity(event.entity_id) and value.upper() in _TERMINAL_PLAYSTATES:
                out.extend(
                    self._emit_game_over(
                        reason="local_playstate",
                        result=value.lower(),
                    )
                )
        return out

    def _emit_game_over(
        self, *, reason: str, result: Optional[str] = None
    ) -> List[LiveLogEvent]:
        if not self._game_active or self._game_over_sent:
            return []
        self._game_over_sent = True
        self._game_active = False
        placement = None
        if self._local_player_id is not None:
            candidates = [
                self._parser.players.get(self._local_player_id),
                self._local_hero_entity_id,
            ]
            for entity_id in candidates:
                if not entity_id:
                    continue
                raw_place = self._parser.int_tag(
                    entity_id, "PLAYER_LEADERBOARD_PLACE", 0
                )
                if 1 <= raw_place <= 8:
                    placement = raw_place
                    break
        if result is None and self._local_player_id is not None:
            player_entity = self._parser.players.get(self._local_player_id)
            if player_entity is not None:
                playstate = self._parser.tag(player_entity, "PLAYSTATE", "").upper()
                result = {
                    "WON": "win",
                    "LOST": "loss",
                    "TIED": "tie",
                    "CONCEDED": "conceded",
                }.get(playstate)
        return [
            self._emit(
                EVENT_GAME_OVER,
                {
                    "reason": reason,
                    "result": result,
                    "turn": self._turn,
                    "placement": placement,
                    "local_player_id": self._local_player_id,
                },
            )
        ]

    # ── 本地玩家识别 ───────────────────────────────────────────────
    def _is_local_entity(self, entity_id: int) -> bool:
        if self._local_player_id is None:
            return False
        return self._parser.players.get(self._local_player_id) == int(entity_id)

    def _remember_local_entities(self, event: Any) -> None:
        """记录本地英雄实体 / 标签转移实体（BG 日志里玩家 HUD 状态可能挂在这里）。"""
        if self._local_player_id is None:
            return
        entity = self._parser.entities.get(int(event.entity_id))
        if entity is None:
            return
        tag = str(event.tag or "")
        if entity.tag("CARDTYPE") == "HERO" and entity.tag("PLAYER_ID") == str(
            self._local_player_id
        ):
            if self._local_hero_entity_id is None or tag in (
                "HEALTH",
                "ARMOR",
                "PLAYER_TECH_LEVEL",
                "PLAYER_LEADERBOARD_PLACE",
            ):
                self._local_hero_entity_id = entity.entity_id
        if (
            entity.card_id == "Bacon_TagTransferPlayerE"
            and entity.controller == self._local_player_id
        ):
            if self._tag_transfer_entity_id is None or tag in (
                "RESOURCES",
                "TEMP_RESOURCES",
                "RESOURCES_USED",
                "PLAYER_TECH_LEVEL",
            ):
                self._tag_transfer_entity_id = entity.entity_id

    def _maybe_set_local_from_name(self, name: str) -> None:
        if self._local_player_id is not None or not name:
            return
        matches = [pid for pid, value in self._player_names.items() if value == name]
        if len(matches) == 1:
            self._set_local_player(matches[0])

    def _maybe_set_local_from_option(self, option: Mapping[str, Any]) -> None:
        if self._local_player_id is not None:
            return
        main_entity = str(option.get("main_entity") or "")
        if not any(prefix in main_entity for prefix in _LOCAL_CONTROL_PREFIXES):
            return
        match = _ENTITY_PLAYER_RE.search(main_entity)
        if match:
            self._set_local_player(int(match.group(1)))

    def _maybe_set_local_from_players(self) -> None:
        if self._local_player_id is not None:
            return
        players = self._parser.players
        if len(players) == 1:
            self._set_local_player(next(iter(players)))
            return
        if not players:
            return
        # 2 人局（练习/Bob）：真实账号那一方是本地；8 人局要等
        # EntityChoices/DebugPrintOptions 的本地信号，不能盲猜 PlayerID=1。
        with_account = [
            pid for pid in players
            if self._player_has_account.get(pid)
        ]
        if len(players) == 2 and len(with_account) == 1:
            self._set_local_player(with_account[0])
            return
        if len(players) == 1:
            self._set_local_player(next(iter(players)))

    def _set_local_player(self, player_id: int) -> None:
        if self._local_player_id is not None:
            return
        self._local_player_id = int(player_id)
        # 立即发一次当前状态，runner 不必等下一次变化
        self._last_player_state = None

    def _local_player_values(self) -> tuple:
        """（gold, tier, hero_health）；未知字段为 None。

        BG 日志里玩家 HUD 状态可能挂在三个地方：
        1. 正常 Player 实体（8 人局常见）；
        2. ``Bacon_TagTransferPlayerE`` 标签转移实体（练习/Bob 局）；
        3. 本地英雄实体（``PLAYER_ID`` + ``CARDTYPE=HERO``，血量/等级）。
        """
        if self._local_player_id is None:
            return (None, None, None)
        player_entity = self._parser.players.get(self._local_player_id)
        gold: Optional[int] = None
        tier: Optional[int] = None
        health: Optional[int] = None

        def _has(*tags: str) -> bool:
            return player_entity is not None and any(
                tag in self._parser.entities[player_entity].tags for tag in tags
            )

        if player_entity is not None and _has(
            "RESOURCES", "TEMP_RESOURCES", "RESOURCES_USED"
        ):
            gold = max(
                0,
                self._parser.int_tag(player_entity, "RESOURCES", 0)
                + self._parser.int_tag(player_entity, "TEMP_RESOURCES", 0)
                - self._parser.int_tag(player_entity, "RESOURCES_USED", 0),
            )
        if player_entity is not None and _has("PLAYER_TECH_LEVEL"):
            tier = self._parser.int_tag(player_entity, "PLAYER_TECH_LEVEL", 0) or None
        if player_entity is not None and _has("HEALTH"):
            health = self._parser.int_tag(player_entity, "HEALTH", 0) or None

        transfer = self._tag_transfer_entity_id
        if transfer and transfer in self._parser.entities:
            if gold is None:
                tags = self._parser.entities[transfer].tags
                if any(k in tags for k in ("RESOURCES", "TEMP_RESOURCES", "RESOURCES_USED")):
                    gold = max(
                        0,
                        self._parser.int_tag(transfer, "RESOURCES", 0)
                        + self._parser.int_tag(transfer, "TEMP_RESOURCES", 0)
                        - self._parser.int_tag(transfer, "RESOURCES_USED", 0),
                    )
            if tier is None:
                tier = self._parser.int_tag(transfer, "PLAYER_TECH_LEVEL", 0) or None

        hero = self._local_hero_entity_id
        if hero and hero in self._parser.entities:
            if health is None:
                health = self._parser.int_tag(hero, "HEALTH", 0) or None
            if tier is None:
                tier = self._parser.int_tag(hero, "PLAYER_TECH_LEVEL", 0) or None
        return (gold, tier, health)

    def _maybe_player_state(self) -> List[LiveLogEvent]:
        if self._local_player_id is None:
            self._maybe_set_local_from_players()
        gold, tier, health = self._local_player_values()
        if self._local_player_id is None:
            return []
        player_entity = self._parser.players.get(self._local_player_id)
        if gold is None and tier is None and health is None:
            return []
        state = (gold, tier, health)
        if state == self._last_player_state:
            return []
        previous = self._last_player_state
        self._last_player_state = state
        names = ("gold", "tier", "hero_health")
        if previous is None:
            changed = [name for name, value in zip(names, state) if value is not None]
        else:
            changed = [
                name
                for index, name in enumerate(names)
                if previous[index] != state[index]
            ]
        if not changed:
            return []
        return [
            self._emit(
                EVENT_PLAYER_STATE,
                {
                    "player_id": self._local_player_id,
                    "gold": gold,
                    "tier": tier,
                    "hero_health": health,
                    "changed": changed,
                    "turn": self._turn,
                    "phase": self._phase,
                    "sources": {
                        "player_entity": player_entity,
                        "hero_entity": self._local_hero_entity_id,
                        "tag_transfer_entity": self._tag_transfer_entity_id,
                    },
                },
            )
        ]

    # ── 选择窗口 ────────────────────────────────────────────────────
    def _flush_windows(self) -> List[LiveLogEvent]:
        out: List[LiveLogEvent] = []
        if self._pending_options is not None:
            options = self._pending_options
            self._pending_options = None
            if options:
                out.append(
                    self._emit(
                        EVENT_CHOICE_WINDOW,
                        {
                            "kind": "options",
                            "options": [self._normalize_option(o) for o in options],
                            "choice": None,
                            "turn": self._turn,
                            "phase": self._phase,
                            "local_player_id": self._local_player_id,
                        },
                    )
                )
        if self._pending_choice is not None:
            choice = self._pending_choice
            self._pending_choice = None
            if choice:
                choice = dict(choice)
                choice["entities"] = {
                    int(index): self._parse_entity_ref(text)
                    for index, text in (choice.get("entities") or {}).items()
                }
                out.append(
                    self._emit(
                        EVENT_CHOICE_WINDOW,
                        {
                            "kind": "choices",
                            "options": [],
                            "choice": choice,
                            "turn": self._turn,
                            "phase": self._phase,
                            "local_player_id": self._local_player_id,
                        },
                    )
                )
        return out

    def _normalize_option(self, option: Mapping[str, Any]) -> Dict[str, Any]:
        main_entity = str(option.get("main_entity") or "")
        ref = self._parse_entity_ref(main_entity) if main_entity else {}
        return {
            "option": option.get("option"),
            "type": option.get("type"),
            "main_entity": main_entity,
            "error": option.get("error"),
            "entity_id": ref.get("entity_id"),
            "card_id": ref.get("card_id"),
            "controller": ref.get("controller"),
        }

    @staticmethod
    def _parse_entity_ref(text: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {"entity_id": None, "card_id": None, "controller": None}
        if not text:
            return out
        match = _ENTITY_ID_RE.search(text)
        if match:
            out["entity_id"] = int(match.group(1))
        match = _CARD_ID_RE.search(text)
        if match:
            out["card_id"] = match.group(1)
        match = _ENTITY_PLAYER_RE.search(text)
        if match:
            out["controller"] = int(match.group(1))
        return out

    # ── 事件发射/回调 ───────────────────────────────────────────────
    def _emit(self, event_type: str, data: Mapping[str, Any]) -> LiveLogEvent:
        with self._lock:
            return self._emit_locked(event_type, data)

    def _emit_locked(self, event_type: str, data: Mapping[str, Any]) -> LiveLogEvent:
        event = LiveLogEvent(
            type=event_type,
            data=dict(data),
            timestamp=time.monotonic(),
            log_path=str(self.log_path) if self.log_path else "",
        )
        return event

    def _dispatch(self, event: LiveLogEvent) -> None:
        with self._lock:
            callbacks = list(self._callbacks.get(event.type, ()))
            callbacks += list(self._callbacks.get("*", ()))
        for callback in callbacks:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - 回调异常不影响监听
                pass
