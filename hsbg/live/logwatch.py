"""实时对局状态观察：tail ``Power.log`` + HDT 日志 → :class:`LiveSnapshot`。

用途
----
自动代打需要知道"现在处于哪个阶段"——主菜单 / 酒馆大厅 / 英雄选择 /
招募（自己的回合）/ 战斗（对手回合）/ 选择窗口（发现·三选一·任务）/
对局结束。本模块以**只读日志 tail** 方式恢复该状态：

数据源
------
1. **HDT 日志**（``hdt_log.txt``，信息最直接）：
   - ``GameEventHandler.HandleGameStart`` → 新对局
   - ``GameEventHandler.HandleTurnStart >> --- Player turn N ---`` → 招募（第 N 回合）
   - ``GameEventHandler.HandleTurnStart >> --- Opponent turn N ---`` → 战斗
   - ``BobsBuddyInvoker.StartShoppingAsync ... Setting UI state to Shopping`` → 招募
   - ``BobsBuddyInvoker.StartCombat`` / ``Setting UI state to combat`` → 战斗
   - ``Setting UI state to GameOver`` / ``HandleGameEnd`` / ``HandleLoss/Win``
     / ``GameStats.GameEnd`` → 对局结束
   - ``GameV2.CurrentMode >> HUB/BACON/LOGIN/GAMEPLAY`` → 菜单/酒馆大厅模式
   - ``[HrSRL] ... Game started: bg_YYYYMMDD_HHMMSS_xxxx`` → 会话/对局 id
2. **Power.log**（补充，用于回合号与"我方是否可以操作"）：
   - ``CREATE_GAME`` → 新对局（HDT 不可用时的兜底）
   - ``GameType=GT_BATTLEGROUNDS`` → 酒馆模式
   - ``TAG_CHANGE Entity=GameEntity tag=TURN value=N`` → 第 N 回合
   - ``GameState.DebugPrintOptions()`` 中出现 ``type=END_TURN`` → 招募阶段
     （本地玩家有操作权）
   - ``GameState.DebugPrintEntityChoices() - ... ChoiceType=X`` → 选择窗口
     （MULLIGAN → 英雄选择；其它 → 发现/三选一）
   - ``STEP value=MAIN_END`` → 已结束回合（进入战斗）
   - 本地玩家识别：``Player EntityID=.. PlayerID=.. GameAccountId=[hi=.. lo=..]``
     中 hi/lo 非 0 的是本机账号；其 ``tag=HERO_ENTITY`` 即本地英雄实体；
     ``PLAYSTATE value=DEAD`` 或该英雄 ``HEALTH value=0`` → 对局结束（备用信号）

接入点
------
* ``hsbg.bridge.live_log.LiveLogWatcher`` 由 rea-operator 提供；若已存在，
  :func:`create_watcher` 会优先使用它（通过 :class:`ExternalWatcherAdapter` 适配），
  否则用本模块的 :class:`LiveLogWatcher`（只依赖日志文件，已可工作）。
* ``tools/live_state_mem.read_live_state()`` 的内存状态由
  :mod:`hsbg.live.memory_state` 合并（可拿到精确 shop/hand/board/rank）。

注意
----
* 日志时间戳只有本地时间（无日期），本模块一律用**文件增量读取 + wall clock**
  标记事件到达时间；跨天/跨会话由文件截断/轮转检测处理。
* 所有逻辑都是**只读**，不写日志、不改游戏。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from hsbg.live.config import LiveConfig

#: 阶段常量（planner/runner 共用）
PHASE_UNKNOWN = "unknown"
PHASE_MENU = "menu"            # 主菜单 / 非酒馆界面
PHASE_LOBBY = "lobby"          # 酒馆大厅（已进 BG，未开局）
PHASE_HERO_SELECT = "hero_select"
PHASE_RECRUIT = "recruit"      # 我方招募阶段（可操作）
PHASE_COMBAT = "combat"        # 对手回合/战斗（只等待）
PHASE_CHOICE = "choice"        # 发现/三选一/任务等选择窗口
PHASE_GAME_OVER = "game_over"

PHASES: Tuple[str, ...] = (
    PHASE_UNKNOWN, PHASE_MENU, PHASE_LOBBY, PHASE_HERO_SELECT,
    PHASE_RECRUIT, PHASE_COMBAT, PHASE_CHOICE, PHASE_GAME_OVER,
)


@dataclass
class LiveSnapshot:
    """某一时刻的对局状态快照（日志 + 可选内存状态的融合结果）。"""

    phase: str = PHASE_UNKNOWN
    turn: int = 0
    game_id: int = 0
    session_id: str = ""
    in_game: bool = False
    choice_active: bool = False
    mode: str = ""
    placement: Optional[int] = None
    turns_played: int = 0
    power_log_path: str = ""
    power_log_offset: int = 0
    hdt_log_path: str = ""
    hdt_log_offset: int = 0
    last_event: str = ""
    last_event_age_s: float = 0.0
    game_started_at: Optional[float] = None
    game_ended_at: Optional[float] = None
    source: str = "logwatch"
    updated_at: float = 0.0
    notes: Dict[str, Any] = field(default_factory=dict)

    # ── 便利 ──
    def is_phase(self, *phases: str) -> bool:
        return self.phase in phases

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "turn": int(self.turn),
            "game_id": int(self.game_id),
            "session_id": self.session_id,
            "in_game": bool(self.in_game),
            "choice_active": bool(self.choice_active),
            "mode": self.mode,
            "placement": self.placement,
            "turns_played": int(self.turns_played),
            "power_log_path": self.power_log_path,
            "power_log_offset": int(self.power_log_offset),
            "hdt_log_path": self.hdt_log_path,
            "hdt_log_offset": int(self.hdt_log_offset),
            "last_event": self.last_event,
            "last_event_age_s": round(float(self.last_event_age_s), 3),
            "game_started_at": self.game_started_at,
            "game_ended_at": self.game_ended_at,
            "source": self.source,
            "updated_at": self.updated_at,
            "notes": dict(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LiveSnapshot":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in (data or {}).items() if k in allowed}
        return cls(**kwargs)

    @classmethod
    def blind(cls, **kwargs: Any) -> "LiveSnapshot":
        """没有日志/内存状态时的盲操作快照（phase=unknown）。"""
        return cls(phase=PHASE_UNKNOWN, source="blind", **kwargs)


# ══════════════════════════════════════════════════════════════════════
# 文件 tail 工具
# ══════════════════════════════════════════════════════════════════════


class _FileTail:
    """增量读取文本文件（处理轮转/截断/半行），返回新增行。"""

    def __init__(self, path: Optional[Path], *, start_at_end: bool = True) -> None:
        self.path = Path(path) if path else None
        self._offset = 0
        self._buffer = ""
        self._started = False
        self._start_at_end = start_at_end
        self._inode_key: Tuple[int, int] = (0, 0)

    @property
    def offset(self) -> int:
        return self._offset

    def reset(self, *, start_at_end: bool = True) -> None:
        self._offset = 0
        self._buffer = ""
        self._started = False
        self._start_at_end = start_at_end

    def read_new_lines(self) -> List[str]:
        """读取自上次以来新增的完整行；文件不存在/未变化返回空列表。"""
        path = self.path
        if path is None or not path.exists():
            return []
        try:
            st = path.stat()
            key = (int(st.st_ino), int(st.st_dev))
            if not self._started:
                self._started = True
                self._inode_key = key
                if self._start_at_end:
                    self._offset = int(st.st_size)
                    return []
            elif key != self._inode_key:
                # 文件被替换（HDT 轮转 / HS 重启）→ 从头读
                self._inode_key = key
                self._offset = 0
                self._buffer = ""
            elif int(st.st_size) < self._offset:
                # 原地截断（Power.log "Truncating log"）→ 从头读
                self._offset = 0
                self._buffer = ""
            if int(st.st_size) <= self._offset:
                return []
            with open(path, "rb") as f:
                f.seek(self._offset)
                chunk = f.read()
                self._offset = int(f.tell())
        except OSError:
            return []
        text = chunk.decode("utf-8", errors="replace")
        if self._buffer:
            text = self._buffer + text
        if text.endswith("\n"):
            self._buffer = ""
        else:
            idx = text.rfind("\n")
            if idx < 0:
                self._buffer = text
                return []
            self._buffer = text[idx + 1:]
            text = text[: idx + 1]
        lines = text.splitlines()
        return [line for line in lines if line.strip()]


# ══════════════════════════════════════════════════════════════════════
# 正则（兼容中英文日志；只匹配结构，不依赖玩家名）
# ══════════════════════════════════════════════════════════════════════

_RE_PLAYER_BLOCK = re.compile(
    r"Player EntityID=(?P<eid>\d+) PlayerID=(?P<pid>\d+) "
    r"GameAccountId=\[hi=(?P<hi>-?\d+) lo=(?P<lo>-?\d+)\]"
)
_RE_HERO_ENTITY_TAG = re.compile(r"tag=HERO_ENTITY value=(?P<hid>\d+)")
_RE_CREATE_GAME = re.compile(r"\bCREATE_GAME\b")
_RE_GAME_TYPE_BG = re.compile(r"GameType=GT_BATTLEGROUNDS")
_RE_TURN_TAG = re.compile(
    r"GameState\.DebugPrintPower\(\) - .*TAG_CHANGE Entity=(?P<entity>[^\s]+) "
    r"tag=TURN value=(?P<turn>\d+)"
)
_RE_OPTION_END_TURN = re.compile(r"option \d+ type=END_TURN")
_RE_OPTIONS_HEADER = re.compile(r"GameState\.DebugPrintOptions\(\)")
_RE_CHOICES_HEADER = re.compile(r"GameState\.DebugPrintEntityChoices\(\)")
_RE_CHOICE_TYPE = re.compile(r"ChoiceType=(?P<ctype>[A-Z_]+)")
_RE_STEP_MAIN_END = re.compile(r"GameState\.DebugPrintPower\(\) - .*TAG_CHANGE Entity=\S+ tag=STEP value=MAIN_END")
_RE_STEP_MAIN_READY = re.compile(r"GameState\.DebugPrintPower\(\) - .*TAG_CHANGE Entity=\S+ tag=STEP value=MAIN_(?:READY|START)")
_RE_PLAYSTATE = re.compile(
    r"TAG_CHANGE Entity=(?P<entity>\d+) tag=PLAYSTATE value=(?P<state>DEAD|LOST|WON)"
)
_RE_HEALTH_ZERO = re.compile(
    r"TAG_CHANGE Entity=(?P<entity>\d+) tag=HEALTH value=0"
)

# HDT 日志（`HH:MM:SS|Level|Source >> message`）
_RE_HDT_LINE = re.compile(r"^(?P<ts>\d{2}:\d{2}:\d{2})\|(?P<level>[^|]*)\|(?P<body>.*)$")
_RE_HDT_GAME_START = re.compile(r"GameEventHandler\.HandleGameStart >>")
_RE_HDT_TURN = re.compile(
    r"GameEventHandler\.HandleTurnStart >> --- (?P<who>Player|Opponent) turn (?P<turn>\d+) ---"
)
_RE_HDT_HANDLE_END = re.compile(
    r"(?:GameEventHandler\.HandleGameEnd|GameEventHandler\.HandleLoss|"
    r"GameEventHandler\.HandleWin|GameStats\.GameEnd|Setting UI state to GameOver)"
)
_RE_HDT_GAME_TURNS = re.compile(r"GameStats\.GameEnd >> Current Game ended after (?P<turns>\d+) turns")
_RE_HDT_MODE = re.compile(r"GameV2\.CurrentMode >> (?P<mode>[A-Z_]+)")
_RE_HDT_SHOPPING = re.compile(
    r"(?:BobsBuddyInvoker\.StartShoppingAsync >> (?P<id>\S+_(\d+))|"
    r"Setting UI state to Shopping)"
)
_RE_HDT_COMBAT = re.compile(
    r"(?:BobsBuddyInvoker\.StartCombat >> (?P<id>\S+_(\d+))|"
    r"Setting UI state to combat)"
)
_RE_HDT_HERO_PICK = re.compile(r"(?:GetBattlegroundsHeroPickStats|BattlegroundsDbSingleton)")
_RE_HRSRL_GAME_START = re.compile(r"\[HrSRL\].*Game started: (?P<gid>\S+)")


# ══════════════════════════════════════════════════════════════════════
# HDT 日志观察器（补充 bridge watcher 无法区分的 主菜单/酒馆大厅）
# ══════════════════════════════════════════════════════════════════════


class _HdtObserver:
    """轻量 tail HDT 日志：只提取 ``GameV2.CurrentMode``（HUB/BACON）与对局阶段。

    用于区分"主菜单"和"酒馆大厅"——``hsbg.bridge.live_log`` 只给
    recruit/combat/hero_select/game_over，不区分大厅；而大厅需要点「开始」。
    """

    def __init__(self, hdt_dir: Optional[Path | str] = None) -> None:
        self.hdt_dir = Path(hdt_dir) if hdt_dir else None
        self.mode: str = ""
        self.phase: str = ""
        self.turn: int = 0
        self.in_game: bool = False
        self._path: Optional[Path] = None
        self._tail: Optional[_FileTail] = None
        self._inode: int = 0
        self._last_size: int = 0

    def _resolve(self) -> Optional[Path]:
        """找最新的 HDT 日志文件（兼容不同安装目录/文件名）。"""
        candidates: List[Path] = []
        if self.hdt_dir is not None:
            candidates.append(self.hdt_dir)
        for env in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if not base:
                continue
            for name in ("HearthstoneDeckTracker", "Hearthstone Deck Tracker"):
                candidates.append(Path(base) / name / "Logs")
        best: Optional[Tuple[Tuple[float, int], Path]] = None
        for directory in candidates:
            try:
                if not directory.exists():
                    continue
                files = [p for p in directory.glob("*.txt") if p.is_file()]
            except OSError:
                continue
            for path in files:
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                score = (mtime, 1 if path.name == "hdt_log.txt" else 0)
                if best is None or score > best[0]:
                    best = (score, path)
        return best[1] if best else None

    @property
    def has_sources(self) -> bool:
        return self._path is not None or self._resolve() is not None

    def poll(self) -> "_HdtObserver":
        path = self._resolve()
        if path is None:
            return self
        try:
            st = path.stat()
            inode = int(st.st_ino)
            size = int(st.st_size)
        except OSError:
            return self
        # 仅在文件轮转/截断时从头读；正常 grow 只读增量
        rotate = (path != self._path or inode != self._inode
                  or size < self._last_size)
        if rotate:
            self._path = path
            self._inode = inode
            self._tail = _FileTail(path, start_at_end=False)
        self._last_size = size
        if self._tail is None:
            return self
        for raw in self._tail.read_new_lines():
            self._handle(raw)
        return self

    def _handle(self, raw: str) -> None:
        match = _RE_HDT_LINE.match(raw)
        body = match.group("body") if match else raw
        gm = _RE_HDT_MODE.search(body)
        if gm:
            mode = gm.group("mode")
            self.mode = mode
            if mode in ("HUB", "LOGIN"):
                self.in_game = False
                self.phase = PHASE_MENU
            elif mode == "BACON":
                self.in_game = False
                self.phase = PHASE_LOBBY
            elif mode == "GAMEPLAY":
                self.in_game = True
            return
        if _RE_HDT_GAME_START.search(body):
            self.in_game = True
            self.phase = PHASE_HERO_SELECT
            return
        turn_m = _RE_HDT_TURN.search(body)
        if turn_m:
            self.in_game = True
            self.turn = int(turn_m.group("turn"))
            self.phase = (PHASE_RECRUIT if turn_m.group("who") == "Player"
                          else PHASE_COMBAT)
            return
        if _RE_HDT_SHOPPING.search(body):
            self.in_game = True
            self.phase = PHASE_RECRUIT
            return
        if _RE_HDT_COMBAT.search(body) and "StartCombat" in body:
            self.in_game = True
            self.phase = PHASE_COMBAT
            return
        if _RE_HDT_HANDLE_END.search(body):
            self.in_game = False
            self.phase = PHASE_GAME_OVER
            return


# ══════════════════════════════════════════════════════════════════════
# 实时 watcher
# ══════════════════════════════════════════════════════════════════════


class LiveLogWatcher:
    """tail Power.log + HDT 日志，维护 :class:`LiveSnapshot`（只读）。

    参数
    ----
    power_log_path : 显式 Power.log 路径（None = 从 config/默认位置找）
    hdt_log_dir    : HDT 日志目录；自动选择最新 ``*.txt`` 并跟随轮转
    start_at_end   : True = 从文件末尾开始（线上实时）；False = 从头读（测试/回放）
    clock          : wall clock 函数（测试可注入假时钟）
    """

    def __init__(
        self,
        power_log_path: Optional[Path | str] = None,
        hdt_log_dir: Optional[Path | str] = None,
        *,
        start_at_end: bool = True,
        clock: Callable[[], float] = time.time,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.clock = clock
        self.logger = logger or (lambda msg: None)
        self._power_path = Path(power_log_path) if power_log_path else None
        self._hdt_dir = Path(hdt_log_dir) if hdt_log_dir else None
        self._power_tail = _FileTail(self._power_path, start_at_end=start_at_end)
        self._hdt_tail: Optional[_FileTail] = None
        self._hdt_path: Optional[Path] = None
        self._start_at_end = start_at_end
        # 状态
        self._phase = PHASE_UNKNOWN
        self._turn = 0
        self._game_id = 0
        self._session_id = ""
        self._in_game = False
        self._choice_active = False
        self._mode = ""
        self._placement: Optional[int] = None
        self._turns_played = 0
        self._last_event = ""
        self._last_event_ts = clock()
        self._game_started_at: Optional[float] = None
        self._game_ended_at: Optional[float] = None
        self._notes: Dict[str, Any] = {}
        # Power 侧辅助状态
        self._power_game_seen = False
        self._power_turn_seen = 0
        self._power_step_main_end = False
        self._choice_serial = 0
        self._options_seen = False
        self._local_player_id: Optional[int] = None
        self._local_entity_id: Optional[int] = None
        self._local_hero_id: Optional[int] = None
        self._current_player_entity: Optional[int] = None
        self._hdt_game_start_ts: Optional[float] = None
        #: 已知对局开始/结束的 wall-clock 历史（runner 归档用）
        self.game_history: List[Dict[str, Any]] = []
        self._snapshot_version = 0

    # ── 路径自动发现 ──
    @property
    def has_sources(self) -> bool:
        """Power.log 或 HDT 日志目录是否存在（用于决定是否需要 simulate 降级）。"""
        try:
            if self._power_path is not None and Path(self._power_path).exists():
                return True
            if self._hdt_dir is not None and Path(self._hdt_dir).exists():
                if any(Path(self._hdt_dir).glob("*.txt")):
                    return True
        except OSError:
            return False
        return False

    @classmethod
    def from_config(
        cls, config: LiveConfig, **kwargs: Any
    ) -> "LiveLogWatcher":
        return cls(
            power_log_path=config.power_log_path(),
            hdt_log_dir=config.hdt_log_dir_resolved(),
            **kwargs,
        )

    def _resolve_hdt_file(self) -> Optional[Path]:
        if self._hdt_dir is None or not self._hdt_dir.exists():
            return None
        candidates = [
            p for p in self._hdt_dir.glob("*.txt")
            if p.is_file()
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    # ── 公共 API ──
    def poll(self) -> LiveSnapshot:
        """读取增量日志并更新状态，返回最新快照。"""
        # 1) HDT 日志（可能轮转出新文件）
        hdt_file = self._resolve_hdt_file()
        if hdt_file is not None:
            if self._hdt_path != hdt_file:
                self._hdt_path = hdt_file
                self._hdt_tail = _FileTail(hdt_file, start_at_end=self._start_at_end)
            assert self._hdt_tail is not None
            for line in self._hdt_tail.read_new_lines():
                self._handle_hdt_line(line)
        # 2) Power.log
        for line in self._power_tail.read_new_lines():
            self._handle_power_line(line)
        self._apply_derived_phase()
        return self.snapshot()

    def snapshot(self) -> LiveSnapshot:
        now = self.clock()
        return LiveSnapshot(
            phase=self._phase,
            turn=int(self._turn),
            game_id=int(self._game_id),
            session_id=self._session_id,
            in_game=bool(self._in_game),
            choice_active=bool(self._choice_active),
            mode=self._mode,
            placement=self._placement,
            turns_played=int(self._turns_played),
            power_log_path=str(self._power_path or ""),
            power_log_offset=self._power_tail.offset,
            hdt_log_path=str(self._hdt_path or ""),
            hdt_log_offset=self._hdt_tail.offset if self._hdt_tail else 0,
            last_event=self._last_event,
            last_event_age_s=max(0.0, now - self._last_event_ts),
            game_started_at=self._game_started_at,
            game_ended_at=self._game_ended_at,
            source="logwatch",
            updated_at=now,
            notes=dict(self._notes),
        )

    def reset(self) -> None:
        self._power_tail.reset(start_at_end=self._start_at_end)
        if self._hdt_tail is not None:
            self._hdt_tail.reset(start_at_end=self._start_at_end)
        self._phase = PHASE_UNKNOWN
        self._turn = 0
        self._game_id = 0
        self._in_game = False
        self._choice_active = False
        self._power_game_seen = False
        self._power_turn_seen = 0
        self._notes.clear()

    # ── 事件记录 ──
    def _touch(self, event: str) -> None:
        self._last_event = event
        self._last_event_ts = self.clock()

    def _start_game(self, source: str) -> None:
        if self._in_game and self._phase not in (PHASE_GAME_OVER, PHASE_MENU, PHASE_LOBBY):
            # 同一局内重复的 start 信号（HDT + Power）→ 忽略
            return
        self._game_id += 1
        self._in_game = True
        self._phase = PHASE_HERO_SELECT
        self._turn = 0
        self._choice_active = False
        self._placement = None
        self._turns_played = 0
        self._game_started_at = self.clock()
        self._game_ended_at = None
        self._power_game_seen = False
        self._power_turn_seen = 0
        self._power_step_main_end = False
        self._local_player_id = None
        self._local_entity_id = None
        self._local_hero_id = None
        self._touch(f"game_start:{source}")

    def _end_game(self, reason: str) -> None:
        if not self._in_game and self._phase == PHASE_GAME_OVER:
            return
        self._in_game = False
        self._phase = PHASE_GAME_OVER
        self._choice_active = False
        self._game_ended_at = self.clock()
        self.game_history.append({
            "game_id": self._game_id,
            "session_id": self._session_id,
            "started_at": self._game_started_at,
            "ended_at": self._game_ended_at,
            "turns": self._turns_played or self._turn,
            "placement": self._placement,
            "reason": reason,
            "power_log": str(self._power_path or ""),
            "hdt_log": str(self._hdt_path or ""),
        })
        self._touch(f"game_end:{reason}")

    # ── HDT 日志处理 ──
    def _handle_hdt_line(self, raw: str) -> None:
        match = _RE_HDT_LINE.match(raw)
        body = match.group("body") if match else raw
        changed = False
        hr = _RE_HRSRL_GAME_START.search(body)
        if hr:
            self._session_id = hr.group("gid")
            changed = True
        if _RE_HDT_GAME_START.search(body):
            self._hdt_game_start_ts = self.clock()
            self._start_game("hdt")
            changed = True
        turn_m = _RE_HDT_TURN.search(body)
        if turn_m:
            self._turn = int(turn_m.group("turn"))
            self._turns_played = max(self._turns_played, self._turn - 1)
            if turn_m.group("who") == "Player":
                self._phase = PHASE_RECRUIT
            else:
                self._phase = PHASE_COMBAT
            self._in_game = True
            self._choice_active = False
            self._touch(f"turn:{turn_m.group('who')}:{self._turn}")
            changed = True
        combat = _RE_HDT_COMBAT.search(body)
        if combat and "StartCombat" in body:
            self._phase = PHASE_COMBAT
            self._in_game = True
            self._touch("combat")
            changed = True
        shopping = _RE_HDT_SHOPPING.search(body)
        if shopping:
            if shopping.groupdict().get("id"):
                turn = int(shopping.groupdict().get("id").rsplit("_", 1)[-1]) \
                    if shopping.groupdict().get("id") else 0
                if turn > 0:
                    self._turn = max(self._turn, turn)
                    self._turns_played = max(self._turns_played, turn - 1)
            self._phase = PHASE_RECRUIT
            self._in_game = True
            self._choice_active = False
            self._touch("shopping")
            changed = True
        gm = _RE_HDT_MODE.search(body)
        if gm:
            mode = gm.group("mode")
            self._mode = mode
            if mode in ("HUB", "LOGIN"):
                if self._in_game:
                    self._end_game("mode_hub")
                self._phase = PHASE_MENU
                self._in_game = False
            elif mode == "BACON":
                self._phase = PHASE_LOBBY
                self._in_game = False
            elif mode == "GAMEPLAY":
                self._in_game = True
            changed = True
        turns_m = _RE_HDT_GAME_TURNS.search(body)
        if turns_m:
            self._turns_played = int(turns_m.group("turns"))
            # HDT 的 "Current Game ended after N turns" 可能在 HandleGameEnd 之后才出现
            if self.game_history:
                self.game_history[-1]["turns"] = self._turns_played
            changed = True
        if _RE_HDT_HANDLE_END.search(body):
            if "GameStats.GameEnd" not in body and self._turns_played == 0:
                self._turns_played = self._turn
            self._end_game("hdt_game_end")
            changed = True
        if changed:
            self._touch(self._last_event)

    # ── Power.log 处理 ──
    def _handle_power_line(self, raw: str, *, source: str = "power") -> None:
        changed = False
        if _RE_CREATE_GAME.search(raw) and "PowerTaskList" not in raw:
            self._power_game_seen = True
            # HDT 已经报过 start 的同一局不重复计数
            if not self._in_game:
                self._start_game("power")
            elif self._phase in (PHASE_GAME_OVER, PHASE_MENU, PHASE_LOBBY):
                self._start_game("power")
            changed = True
        if _RE_GAME_TYPE_BG.search(raw):
            self._mode = "BACON"
            changed = True
        player_m = _RE_PLAYER_BLOCK.search(raw)
        if player_m:
            self._current_player_entity = int(player_m.group("eid"))
            if int(player_m.group("hi")) != 0 or int(player_m.group("lo")) != 0:
                self._local_player_id = int(player_m.group("pid"))
                self._local_entity_id = int(player_m.group("eid"))
            changed = True
        hero_m = _RE_HERO_ENTITY_TAG.search(raw)
        if hero_m and self._current_player_entity == self._local_entity_id:
            self._local_hero_id = int(hero_m.group("hid"))
            changed = True
        turn_m = _RE_TURN_TAG.search(raw)
        if turn_m and "PowerTaskList" not in raw:
            turn = int(turn_m.group("turn"))
            if turn >= 1:
                self._turn = max(self._turn, turn) if self._power_turn_seen else turn
                self._power_turn_seen = 1
                self._turns_played = max(self._turns_played, self._turn - 1)
                if self._turn > 0:
                    self._in_game = True
                    if self._phase in (PHASE_UNKNOWN, PHASE_HERO_SELECT):
                        self._phase = PHASE_RECRUIT
                changed = True
        if _RE_OPTIONS_HEADER.search(raw):
            self._options_seen = True
        if _RE_OPTION_END_TURN.search(raw):
            self._options_seen = True
            if self._in_game and self._phase in (PHASE_HERO_SELECT, PHASE_CHOICE,
                                                 PHASE_UNKNOWN):
                self._phase = PHASE_RECRUIT
            self._choice_active = False
            changed = True
        if _RE_CHOICES_HEADER.search(raw):
            self._choice_serial += 1
            ctype_m = _RE_CHOICE_TYPE.search(raw)
            ctype = ctype_m.group("ctype") if ctype_m else ""
            self._choice_active = True
            if ctype == "MULLIGAN":
                self._phase = PHASE_HERO_SELECT
            else:
                self._phase = PHASE_CHOICE
            self._notes["choice_type"] = ctype
            self._notes["choice_serial"] = self._choice_serial
            self._in_game = True
            changed = True
        if _RE_STEP_MAIN_END.search(raw):
            self._power_step_main_end = True
            if self._in_game:
                self._phase = PHASE_COMBAT
                self._choice_active = False
            changed = True
        if _RE_STEP_MAIN_READY.search(raw):
            self._power_step_main_end = False
            if self._in_game:
                self._phase = PHASE_RECRUIT
            changed = True
        state_m = _RE_PLAYSTATE.search(raw)
        if state_m and self._local_hero_id is not None:
            if int(state_m.group("entity")) == self._local_hero_id and \
                    state_m.group("state") == "DEAD":
                self._end_game("local_hero_dead")
                changed = True
        health_m = _RE_HEALTH_ZERO.search(raw)
        if health_m and self._local_hero_id is not None and \
                int(health_m.group("entity")) == self._local_hero_id:
            self._end_game("local_hero_dead")
            changed = True
        if changed:
            self._touch(self._last_event)

    # ── 融合推导 ──
    def _apply_derived_phase(self) -> None:
        """补足日志缺失时的阶段推导（保持保守，不覆盖明确信号）。"""
        if not self._in_game:
            if self._phase not in (PHASE_MENU, PHASE_LOBBY, PHASE_GAME_OVER):
                self._phase = PHASE_MENU
            return
        if self._phase == PHASE_UNKNOWN and self._turn >= 1:
            self._phase = PHASE_RECRUIT

    #: Phase 常量（便于外部引用）
    PHASE_UNKNOWN = PHASE_UNKNOWN
    PHASE_MENU = PHASE_MENU
    PHASE_LOBBY = PHASE_LOBBY
    PHASE_HERO_SELECT = PHASE_HERO_SELECT
    PHASE_RECRUIT = PHASE_RECRUIT
    PHASE_COMBAT = PHASE_COMBAT
    PHASE_CHOICE = PHASE_CHOICE
    PHASE_GAME_OVER = PHASE_GAME_OVER


#: 兼容名称：Power.log-only 场景下可直接使用（同一实现）
PowerLogWatcher = LiveLogWatcher


# ══════════════════════════════════════════════════════════════════════
# 外部 watcher（hsbg.bridge.live_log）适配
# ══════════════════════════════════════════════════════════════════════


class ExternalWatcherAdapter:
    """把 ``hsbg.bridge.live_log.LiveLogWatcher`` 适配成本模块接口。

    已按 rea-operator 的实际接口实现（2026-10 版本）：
    ``LiveLogWatcher(path=None, poll_interval=..., log_root=...)``；
    ``poll() -> List[LiveLogEvent]``（读取增量并更新内部状态）；
    ``snapshot() -> dict``（`log_path/attached/session_id/game_active/
    game_over_sent/turn/phase/local_player_id/gold/tier/hero_health/
    pending_choice_window/parser/...`，phase ∈ recruit/combat/hero_select/
    game_over/空）。本适配器每轮先 ``poll()`` 再 ``snapshot()`` 并转成
    :class:`LiveSnapshot`。
    """

    def __init__(self, cls: Any, config: LiveConfig) -> None:
        power_log = config.power_log_path()
        path_arg = str(power_log) if power_log.exists() else None
        attempts = (
            {"path": path_arg, "poll_interval": 0.1},
            {"path": path_arg},
            {"poll_interval": 0.1},
            {},
        )
        last_exc: Optional[Exception] = None
        self._impl: Any = None
        for kwargs in attempts:
            try:
                self._impl = cls(**kwargs)
                break
            except TypeError as exc:
                last_exc = exc
                continue
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        if self._impl is None:
            raise RuntimeError(f"无法构造外部 LiveLogWatcher: {last_exc}")
        # HDT 日志补充：区分主菜单(HUB)/酒馆大厅(BACON)
        self._hdt = _HdtObserver(config.hdt_log_dir_resolved())
        self._last_snap: Optional[LiveSnapshot] = None

    # ── 生命周期 ──
    @property
    def has_sources(self) -> bool:
        log_path = getattr(self._impl, "log_path", None)
        try:
            if log_path is not None and Path(log_path).exists():
                return True
        except OSError:
            pass
        try:
            hdt_dir = self._hdt.hdt_dir
            if hdt_dir is not None and hdt_dir.exists():
                if any(hdt_dir.glob("*.txt")):
                    return True
        except OSError:
            pass
        try:
            if self._hdt.has_sources:
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            from hsbg.bridge.live_log import discover_power_log

            return discover_power_log() is not None
        except Exception:  # noqa: BLE001
            return False

    def poll(self) -> LiveSnapshot:
        # 外部 watcher 的 poll() 负责读取增量并更新内部状态；随后取 snapshot
        try:
            self._impl.poll()
        except Exception:  # noqa: BLE001 - 读日志异常不影响已状态
            pass
        try:
            self._hdt.poll()
        except Exception:  # noqa: BLE001
            pass
        snap = self.snapshot()
        self._apply_hdt(snap)
        self._last_snap = snap
        return snap

    def _apply_hdt(self, snap: LiveSnapshot) -> None:
        """用 HDT 日志补充/纠正 bridge 的阶段（尤其区分主菜单/酒馆大厅）。"""
        h = self._hdt
        if not h.mode and not h.phase:
            return
        # HDT 说"不在对局"时以它为准（bridge 的 Power.log 可能还停在旧会话）
        if not h.in_game and h.mode in ("HUB", "LOGIN"):
            snap.phase = PHASE_MENU
            snap.mode = h.mode
            snap.in_game = False
        elif not h.in_game and (h.mode == "BACON" or h.phase == PHASE_LOBBY):
            snap.phase = PHASE_LOBBY
            snap.mode = "BACON"
            snap.in_game = False
        elif not snap.in_game:
            if h.in_game and h.phase:
                snap.phase = h.phase
                snap.in_game = True
        elif h.in_game and snap.phase in (PHASE_UNKNOWN, PHASE_MENU, PHASE_LOBBY):
            snap.phase = h.phase or snap.phase
            snap.turn = snap.turn or h.turn
        if snap.phase in (PHASE_MENU, PHASE_LOBBY):
            snap.in_game = False
        # 记录 HDT 路径/回合号，供 records 归档
        if h._path is not None:
            snap.hdt_log_path = str(h._path)
        if h.turn > snap.turn and snap.in_game:
            snap.turn = h.turn
            snap.turns_played = max(snap.turns_played, h.turn - 1)

    def snapshot(self) -> LiveSnapshot:
        if self._last_snap is not None:
            return self._last_snap
        try:
            raw = self._impl.snapshot()
        except Exception:  # noqa: BLE001
            return LiveSnapshot(source="external")
        return self._normalize(raw)

    def reset(self) -> None:
        for name in ("reset", "flush", "close"):
            fn = getattr(self._impl, name, None)
            if callable(fn):
                try:
                    fn()
                    return
                except Exception:  # noqa: BLE001
                    continue

    def close(self) -> None:
        fn = getattr(self._impl, "close", None)
        if callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    # ── 归一化 ──
    _PHASE_MAP = {
        "": PHASE_UNKNOWN,
        "recruit": PHASE_RECRUIT,
        "combat": PHASE_COMBAT,
        "hero_select": PHASE_HERO_SELECT,
        "hero_pick": PHASE_HERO_SELECT,
        "choice": PHASE_CHOICE,
        "game_over": PHASE_GAME_OVER,
        "menu": PHASE_MENU,
        "lobby": PHASE_LOBBY,
        "no_active_game": PHASE_MENU,
        "unavailable": PHASE_UNKNOWN,
    }

    @classmethod
    def _normalize(cls, value: Any) -> LiveSnapshot:
        if isinstance(value, LiveSnapshot):
            return value
        if not isinstance(value, dict):
            data: Dict[str, Any] = {}
            for name in LiveSnapshot.__dataclass_fields__:  # type: ignore[attr-defined]
                if hasattr(value, name):
                    data[name] = getattr(value, name)
            return LiveSnapshot.from_dict(data)

        phase_raw = str(value.get("phase") or "").strip().lower()
        phase = cls._PHASE_MAP.get(phase_raw, PHASE_UNKNOWN)
        game_active = bool(value.get("game_active"))
        game_over_sent = bool(value.get("game_over_sent"))
        if game_over_sent:
            phase = PHASE_GAME_OVER
        pending = bool(value.get("pending_choice_window"))
        if pending and game_active and phase not in (PHASE_GAME_OVER, PHASE_HERO_SELECT):
            phase = PHASE_CHOICE
        in_game = bool(game_active) or phase in (
            PHASE_RECRUIT, PHASE_COMBAT, PHASE_HERO_SELECT, PHASE_CHOICE,
        )
        if phase in (PHASE_MENU, PHASE_LOBBY):
            in_game = False
        turn = 0
        try:
            turn = int(value.get("turn") or 0)
        except (TypeError, ValueError):
            turn = 0
        notes: Dict[str, Any] = {"bridge": True}
        if value.get("parser"):
            parser = value.get("parser")
            if isinstance(parser, dict):
                notes["parser_phase"] = parser.get("phase")
                notes["parser_turn"] = parser.get("turn")
        for key in ("gold", "tier", "hero_health", "local_player_id"):
            if value.get(key) is not None:
                notes[key] = value[key]
        return LiveSnapshot(
            phase=phase,
            turn=turn,
            session_id=str(value.get("session_id") or ""),
            in_game=in_game,
            choice_active=bool(pending),
            mode="",
            placement=None,
            power_log_path=str(value.get("log_path") or ""),
            power_log_offset=int(value.get("offset") or 0),
            hdt_log_path="",
            hdt_log_offset=0,
            last_event="",
            last_event_age_s=0.0,
            source="bridge.live_log",
            notes=notes,
        )


def create_watcher(
    config: LiveConfig,
    *,
    start_at_end: bool = True,
    clock: Callable[[], float] = time.time,
    logger: Optional[Callable[[str], None]] = None,
) -> Any:
    """创建实时 watcher：优先 ``hsbg.bridge.live_log``，否则内置实现。"""
    try:
        from hsbg.bridge import live_log  # type: ignore

        cls = getattr(live_log, "LiveLogWatcher", None)
        if cls is not None:
            try:
                watcher = ExternalWatcherAdapter(cls, config)
                if logger:
                    logger("[logwatch] 使用 hsbg.bridge.live_log.LiveLogWatcher")
                return watcher
            except Exception as exc:  # noqa: BLE001
                if logger:
                    logger(f"[logwatch] 外部 watcher 不可用，回退内置实现: {exc}")
    except Exception:  # noqa: BLE001 - 模块尚在开发中
        if logger:
            logger("[logwatch] hsbg.bridge.live_log 尚未就绪，使用内置日志 watcher")
    return LiveLogWatcher(
        power_log_path=config.power_log_path(),
        hdt_log_dir=config.hdt_log_dir_resolved(),
        start_at_end=start_at_end,
        clock=clock,
        logger=logger,
    )


__all__ = [
    "PHASE_UNKNOWN",
    "PHASE_MENU",
    "PHASE_LOBBY",
    "PHASE_HERO_SELECT",
    "PHASE_RECRUIT",
    "PHASE_COMBAT",
    "PHASE_CHOICE",
    "PHASE_GAME_OVER",
    "PHASES",
    "LiveSnapshot",
    "LiveLogWatcher",
    "PowerLogWatcher",
    "ExternalWatcherAdapter",
    "create_watcher",
]
