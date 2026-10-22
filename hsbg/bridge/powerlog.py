"""Power.log 增量解析器原型（只读、标准库、无第三方依赖）。

背景
----
炉石客户端在 ``log.config`` 里打开 ``[Power] FilePrinting=True`` 后，会把服务端
下发的 Power 消息逐行写入 ``Logs/Power.log``。本模块只解析 **GameState 命名空间**
的行（``PowerTaskList.*`` 是客户端回放动画时的重复消息，默认跳过），把实体与
tag 增量维护成可查询的表，供"真实对局 → 观测"桥接使用。

关键行格式（均来自真实日志，见 docs/REAL_GAME_BRIDGE.md）
----------------------------------------------------------
::

    D 15:31:06.1234567 GameState.DebugPrintPower() - CREATE_GAME
    D ... - GameEntity EntityID=1
    D ... - Player EntityID=2 PlayerID=1 GameAccountId=[hi=.. lo=..]
    D ... - FULL_ENTITY - Creating ID=64 CardID=
    D ... -     tag=ZONE value=SETASIDE
    D ... - FULL_ENTITY - Updating [entityName=... id=64 zone=PLAY ...] CardID=CS2_042
    D ... - SHOW_ENTITY - Updating Entity=[entityName=... id=64 ...] CardID=BG_XXX
    D ... - TAG_CHANGE Entity=[entityName=... id=64 ...] tag=ZONE value=PLAY
    D ... - BLOCK_START BlockType=PLAY Entity=[...] EffectCardId=... EffectIndex=0 Target=.. SubOption=-1
    D ... - BLOCK_END

设计约束
--------
* **未知行绝不崩溃**：无法识别的行返回 ``kind="unknown"`` 事件并计数。
* **不保存隐私字段**：``GameAccountId`` 解析后立即丢弃；默认不保存
  ``PlayerName``（``capture_player_names=False``），符合"不采集昵称/账号"约定。
* **可增量喂行**：``feed(line) -> list[PowerLogEvent]`` 适合跟随文件 tail；
  也可用 ``feed_file`` 一次性灌入。
"""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional

# ══════════════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════════════

#: 一行日志：级别 时间 来源() - 内容
LINE_RE = re.compile(
    r"^(?P<level>[DIWE])\s+(?P<ts>\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(?P<source>[\w.]+)\(\)\s+-\s*(?P<content>.*?)\s*$"
)

#: 只解析这些命名空间（GameState 是服务端消息；PowerTaskList 是动画回放副本）
GAME_STATE_PREFIX = "GameState."
POWER_TASK_LIST_PREFIX = "PowerTaskList."

# ── 事件类型 ──────────────────────────────────────────────────────────
EVENT_CREATE_GAME = "create_game"
EVENT_GAME_ENTITY = "game_entity"
EVENT_PLAYER = "player"
EVENT_FULL_ENTITY = "full_entity"
EVENT_SHOW_ENTITY = "show_entity"
EVENT_CHANGE_ENTITY = "change_entity"
EVENT_TAG_CHANGE = "tag_change"
EVENT_ENTITY_TAG = "entity_tag"          # FULL_ENTITY/Player 之后缩进的 tag= 行
EVENT_BLOCK_START = "block_start"
EVENT_BLOCK_END = "block_end"
EVENT_OPTION = "option"                  # GameState.DebugPrintOptions
EVENT_CHOICE = "choice"                  # GameState.DebugPrintEntityChoices
EVENT_PLAYER_NAME = "player_name"        # 仅 capture_player_names=True 时产生
EVENT_OTHER = "other"                    # 其他可识别但未建模的 GameState 行
EVENT_UNKNOWN = "unknown"                # 无法识别的行

# ── 正则（字段尽量宽松，格式演变时不崩溃）─────────────────────────────
_RE_GAME_ENTITY = re.compile(r"^GameEntity EntityID=(\d+)")
_RE_PLAYER = re.compile(
    r"^Player EntityID=(\d+) PlayerID=(\d+)"
    r"(?: GameAccountId=\[hi=(\d+) lo=(\d+)\])?"
)
_RE_PLAYER_NAME = re.compile(r"PlayerID=(\d+),\s*PlayerName=(.*)$")
_RE_FULL_CREATE = re.compile(r"^FULL_ENTITY - Creating ID=(\d+) CardID=(\S*)")
_RE_FULL_UPDATE = re.compile(r"^FULL_ENTITY - Updating (.+?) CardID=(\S*)$")
_RE_SHOW = re.compile(r"^(?:SHOW_ENTITY|CHANGE_ENTITY) - Updating Entity=(.+?) CardID=(\S*)")
_RE_TAG_CHANGE = re.compile(r"^TAG_CHANGE Entity=(.+?)\s+tag=(\S+)\s+value=(\S*)")
_RE_TAG_META = re.compile(r"^tag=(\S+)\s+value=(\S*)$")
_RE_ID = re.compile(r"\bid=(\d+)")
_RE_CARD_IN_REF = re.compile(r"\bcardId=(\S+)")
_RE_ZONE_IN_REF = re.compile(r"\bzone=(\S+)")
_RE_NAME_IN_REF = re.compile(r"\bentityName=(.+?)(?:\s+id=|\s+zone=|$)")
_RE_OPTION = re.compile(r"^option (\d+) type=(\S+) mainEntity=(.*?) error=(\S*)")
_RE_CHOICE = re.compile(
    r"id=(\d+) Player=(.+?) TaskList=(\S*) ChoiceType=(\S+) "
    r"CountMin=(\d+) CountMax=(\d+)"
)
_RE_CHOICE_ENTITY = re.compile(r"^Entities\[(\d+)\]=(.+)$")
_RE_BLOCK_TYPE = re.compile(r"BlockType=(\S+)")
_RE_BLOCK_ENTITY = re.compile(r"Entity=(.+?)(?=\s+EffectCardId=|\s*$)")
_RE_BLOCK_EFFECT_CARD = re.compile(r"EffectCardId=(\S*)")
_RE_BLOCK_EFFECT_INDEX = re.compile(r"EffectIndex=(-?\d+)")
_RE_BLOCK_TARGET = re.compile(r"Target=(.+?)(?=\s+SubOption=|\s+TriggerKeyword=|\s*$)")
_RE_BLOCK_SUB = re.compile(r"SubOption=(-?\d+)")
_RE_BLOCK_TRIGGER = re.compile(r"TriggerKeyword=(\S+)")


# ══════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PowerLogEvent:
    """解析出的一条事件（不可变；``data`` 存放各事件的附加字段）。"""

    kind: str
    timestamp: str = ""
    source: str = ""
    raw: str = ""
    entity_id: int = 0
    card_id: str = ""
    tag: str = ""
    value: str = ""
    block_type: str = ""
    text: str = ""
    data: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "kind": self.kind,
            "timestamp": self.timestamp,
            "source": self.source,
            "entity_id": self.entity_id,
            "card_id": self.card_id,
            "tag": self.tag,
            "value": self.value,
            "block_type": self.block_type,
        }
        if self.data:
            out["data"] = dict(self.data)
        return out


@dataclass
class PowerEntity:
    """一个游戏实体的增量 tags 表。"""

    entity_id: int
    card_id: str = ""
    name: str = ""
    tags: Dict[str, str] = field(default_factory=dict)

    def tag(self, name: str, default: str = "") -> str:
        return self.tags.get(str(name), default)

    def int_tag(self, name: str, default: int = 0) -> int:
        raw = self.tags.get(str(name))
        try:
            return int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    @property
    def zone(self) -> str:
        return self.tag("ZONE")

    @property
    def controller(self) -> int:
        return self.int_tag("CONTROLLER", -1)

    @property
    def card_type(self) -> str:
        return self.tag("CARDTYPE")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "card_id": self.card_id,
            "name": self.name,
            "zone": self.zone,
            "controller": self.controller,
            "card_type": self.card_type,
            "tags": dict(self.tags),
        }


@dataclass
class PowerBlock:
    """BLOCK_START ... BLOCK_END 之间的一个服务端 block。"""

    block_type: str
    entity_id: int = 0
    card_id: str = ""
    effect_card_id: str = ""
    effect_index: int = -1
    target: str = ""
    sub_option: int = -1
    trigger_keyword: str = ""
    index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_type": self.block_type,
            "entity_id": self.entity_id,
            "card_id": self.card_id,
            "effect_card_id": self.effect_card_id,
            "effect_index": self.effect_index,
            "target": self.target,
            "sub_option": self.sub_option,
            "trigger_keyword": self.trigger_keyword,
            "index": self.index,
        }


# ══════════════════════════════════════════════════════════════════════
# 解析器
# ══════════════════════════════════════════════════════════════════════


class PowerLogParser:
    """增量 Power.log 解析器。

    Parameters
    ----------
    include_tasklist:
        是否同时解析 ``PowerTaskList.*`` 行（默认 False，避免一条消息算两遍）。
    capture_player_names:
        是否保存 ``PlayerName``（默认 False；本项目的隐私约定是不采集昵称）。
    max_events:
        ``events`` 环形缓冲的容量（只保留最近 N 条事件；统计计数不受影响）。
    """

    def __init__(
        self,
        *,
        include_tasklist: bool = False,
        capture_player_names: bool = False,
        max_events: int = 20000,
    ) -> None:
        self.include_tasklist = bool(include_tasklist)
        self.capture_player_names = bool(capture_player_names)
        self.max_events = max(1, int(max_events))

        self.entities: Dict[int, PowerEntity] = {}
        self.players: Dict[int, int] = {}          # player_id -> entity_id
        self.blocks: List[PowerBlock] = []
        self.events: Deque[PowerLogEvent] = deque(maxlen=self.max_events)
        self.stats: Counter = Counter()
        self.events_by_kind: Counter = Counter()
        self.last_options: List[Dict[str, Any]] = []
        self.last_choice: Optional[Dict[str, Any]] = None
        self.turn = 0
        self.game_seed = 0
        self.game_index = 0
        self.phase = ""
        self.game_entity_id = 0

        self._pending_entity_id = 0
        self._name_to_eid: Dict[str, int] = {}

    # ── 公共 API ────────────────────────────────────────────────────
    def feed(self, line: str) -> List[PowerLogEvent]:
        """喂入一行日志，返回本行产生的事件列表（未知行也不会抛异常）。"""
        try:
            text = line if isinstance(line, str) else str(line)
            text = text.rstrip("\r\n")
            if not text.strip():
                return []
            self.stats["lines_total"] += 1
            match = LINE_RE.match(text)
            if match is None:
                self.stats["unknown_lines"] += 1
                return [self._emit(EVENT_UNKNOWN, raw=text, text=text)]
            level = match.group("level")
            timestamp = match.group("ts")
            source = match.group("source")
            content = match.group("content")

            if source.startswith(POWER_TASK_LIST_PREFIX) and not self.include_tasklist:
                self.stats["tasklist_lines"] += 1
                return []

            event = self._parse_content(timestamp, source, content, text)
            if event is not None:
                return [self._emit_event(event)]
            if source.startswith(GAME_STATE_PREFIX):
                self.stats["other_lines"] += 1
                return [
                    self._emit(
                        EVENT_OTHER, timestamp=timestamp, source=source,
                        raw=text, text=content,
                    )
                ]
            self.stats["foreign_lines"] += 1
            return []

        except Exception:  # noqa: BLE001 - 解析器必须对未知/畸形行容错
            self.stats["parse_errors"] += 1
            try:
                raw_text = line if isinstance(line, str) else str(line)
            except Exception:  # noqa: BLE001
                raw_text = ""
            return [self._emit(EVENT_UNKNOWN, raw=raw_text, text=raw_text)]

    def feed_lines(self, lines: Iterable[str]) -> List[PowerLogEvent]:
        out: List[PowerLogEvent] = []
        for line in lines:
            out.extend(self.feed(line))
        return out

    def feed_file(
        self,
        path: Path | str,
        *,
        encoding: str = "utf-8",
        tail_bytes: Optional[int] = None,
        max_lines: Optional[int] = None,
    ) -> int:
        """读取整个文件（或末尾 ``tail_bytes`` 字节）并解析，返回行数。"""
        file_path = Path(path)
        with file_path.open("r", encoding=encoding, errors="replace") as handle:
            if tail_bytes is not None and tail_bytes > 0:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - int(tail_bytes)), 0)
                if size > tail_bytes:
                    handle.readline()  # 丢弃半行
            count = 0
            for line in handle:
                self.feed(line)
                count += 1
                if max_lines is not None and count >= int(max_lines):
                    break
        return count

    # ── 快照 ────────────────────────────────────────────────────────
    def game_state(self) -> Dict[str, Any]:
        """当前解析到的游戏状态快照（纯 dict，可直接 JSON 序列化）。"""
        players: List[Dict[str, Any]] = []
        for player_id, entity_id in sorted(self.players.items()):
            entity = self.entities.get(entity_id)
            hero_entity_id = entity.int_tag("HERO_ENTITY") if entity else 0
            hero = self.entities.get(hero_entity_id)
            players.append(
                {
                    "player_id": player_id,
                    "entity_id": entity_id,
                    "health": entity.int_tag("HEALTH") if entity else 0,
                    "armor": entity.int_tag("ARMOR") if entity else 0,
                    "tier": entity.int_tag("PLAYER_TECH_LEVEL") if entity else 0,
                    "gold": self._gold_of(entity),
                    "hero_entity_id": hero_entity_id,
                    "hero_card_id": (hero.card_id if hero else ""),
                    "hand_count": self._count_zone(entity_id, "HAND"),
                    "board_count": self._count_zone(entity_id, "PLAY"),
                }
            )

        return {
            "game_index": self.game_index,
            "game_seed": self.game_seed,
            "turn": self.turn,
            "phase": self.phase,
            "game_entity_id": self.game_entity_id,
            "players": players,
            "entities": {
                str(eid): entity.to_dict() for eid, entity in sorted(self.entities.items())
            },
            "blocks": [block.to_dict() for block in self.blocks],
            "last_options": list(self.last_options),
            "last_choice": dict(self.last_choice) if self.last_choice else None,
            "stats": dict(self.stats),
        }

    # ── 查询辅助 ────────────────────────────────────────────────────
    def entity(self, entity_id: int) -> Optional[PowerEntity]:
        return self.entities.get(int(entity_id))

    def card_id(self, entity_id: int) -> str:
        entity = self.entities.get(int(entity_id))
        return entity.card_id if entity else ""

    def tag(self, entity_id: int, name: str, default: str = "") -> str:
        entity = self.entities.get(int(entity_id))
        return entity.tag(name, default) if entity else default

    def int_tag(self, entity_id: int, name: str, default: int = 0) -> int:
        entity = self.entities.get(int(entity_id))
        return entity.int_tag(name, default) if entity else default

    def entities_in_zone(self, zone: str) -> List[PowerEntity]:
        target = str(zone).upper()
        return [e for e in self.entities.values() if e.zone == target]

    def minions_in_play(self) -> List[PowerEntity]:
        return [
            e
            for e in self.entities.values()
            if e.zone == "PLAY" and e.tag("CARDTYPE") == "MINION"
        ]

    def summary(self) -> Dict[str, Any]:
        return {
            "lines_total": self.stats.get("lines_total", 0),
            "tasklist_lines": self.stats.get("tasklist_lines", 0),
            "unknown_lines": self.stats.get("unknown_lines", 0),
            "parse_errors": self.stats.get("parse_errors", 0),
            "foreign_lines": self.stats.get("foreign_lines", 0),
            "events_by_kind": dict(self.events_by_kind),
            "entity_count": len(self.entities),
            "player_count": len(self.players),
            "block_depth": len(self.blocks),
            "turn": self.turn,
            "phase": self.phase,
            "game_index": self.game_index,
        }

    def reset(self) -> None:
        """清空状态（等价于遇到新的 CREATE_GAME）。"""
        self.entities.clear()
        self.players.clear()
        self.blocks.clear()
        self.events.clear()
        self.events_by_kind.clear()
        self.last_options = []
        self.last_choice = None
        self._pending_entity_id = 0
        self._name_to_eid.clear()
        self.game_entity_id = 0
        self.turn = 0
        self.game_seed = 0
        self.phase = ""
        self.game_index += 1

    # ── 内部：事件派发 ─────────────────────────────────────────────
    def _parse_content(
        self, timestamp: str, source: str, content: str, raw: str
    ) -> Optional[PowerLogEvent]:
        if content == "CREATE_GAME":
            self.reset()
            self.stats["create_game"] += 1
            return PowerLogEvent(
                kind=EVENT_CREATE_GAME, timestamp=timestamp, source=source,
                raw=raw, text=content,
                data={"game_index": self.game_index},
            )

        if content.startswith("GameEntity "):
            match = _RE_GAME_ENTITY.match(content)
            if match:
                entity = self._ensure_entity(int(match.group(1)))
                self.game_entity_id = entity.entity_id
                self._pending_entity_id = entity.entity_id
                return PowerLogEvent(
                    kind=EVENT_GAME_ENTITY, timestamp=timestamp, source=source,
                    raw=raw, entity_id=entity.entity_id, text=content,
                )

        if content.startswith("Player "):
            match = _RE_PLAYER.match(content)
            if match:
                entity_id = int(match.group(1))
                player_id = int(match.group(2))
                entity = self._ensure_entity(entity_id)
                self.players[player_id] = entity_id
                self._pending_entity_id = entity_id
                # GameAccountId 只用于确认"是真实玩家"，解析后不保留（隐私）
                return PowerLogEvent(
                    kind=EVENT_PLAYER, timestamp=timestamp, source=source,
                    raw=raw, entity_id=entity_id, text=content,
                    data={
                        "player_id": player_id,
                        "has_account_id": match.group(3) is not None,
                    },
                )

        if content.startswith("FULL_ENTITY - "):
            return self._parse_full_entity(timestamp, source, content, raw)

        if content.startswith(("SHOW_ENTITY - ", "CHANGE_ENTITY - ")):
            return self._parse_show_entity(timestamp, source, content, raw)

        if content.startswith("TAG_CHANGE "):
            return self._parse_tag_change(timestamp, source, content, raw)

        if content.startswith("BLOCK_START"):
            return self._parse_block_start(timestamp, source, content, raw)

        if content.startswith("BLOCK_END"):
            return self._parse_block_end(timestamp, source, content, raw)

        match = _RE_TAG_META.match(content)
        if match and self._pending_entity_id:
            tag, value = match.group(1), match.group(2)
            entity = self._ensure_entity(self._pending_entity_id)
            entity.tags[tag] = value
            self._apply_global_tag(tag, value)
            return PowerLogEvent(
                kind=EVENT_ENTITY_TAG, timestamp=timestamp, source=source,
                raw=raw, entity_id=entity.entity_id, tag=tag, value=value,
                text=content,
            )

        if content.startswith("option "):
            match = _RE_OPTION.match(content)
            if match:
                option = {
                    "option": int(match.group(1)),
                    "type": match.group(2),
                    "main_entity": match.group(3).strip(),
                    "error": match.group(4),
                }
                self.last_options.append(option)
                return PowerLogEvent(
                    kind=EVENT_OPTION, timestamp=timestamp, source=source,
                    raw=raw, text=content, data=option,
                )

        if content.startswith("Entities["):
            match = _RE_CHOICE_ENTITY.match(content)
            if match:
                choice = self.last_choice or {}
                choice.setdefault("entities", {})[int(match.group(1))] = match.group(2)
                self.last_choice = choice
                return PowerLogEvent(
                    kind=EVENT_CHOICE, timestamp=timestamp, source=source,
                    raw=raw, text=content, data={"choice_entity": int(match.group(1))},
                )

        if "ChoiceType=" in content:
            match = _RE_CHOICE.search(content)
            if match:
                self.last_choice = {
                    "id": int(match.group(1)),
                    "player": match.group(2),
                    "task_list": match.group(3),
                    "choice_type": match.group(4),
                    "count_min": int(match.group(5)),
                    "count_max": int(match.group(6)),
                    "entities": {},
                }
                return PowerLogEvent(
                    kind=EVENT_CHOICE, timestamp=timestamp, source=source,
                    raw=raw, text=content, data=dict(self.last_choice),
                )

        match = _RE_PLAYER_NAME.search(content)
        if match:
            player_id = int(match.group(1))
            name = match.group(2)
            if self.capture_player_names:
                entity_id = self.players.get(player_id)
                if entity_id:
                    entity = self._ensure_entity(entity_id)
                    entity.name = name
                    self._name_to_eid.setdefault(name, entity_id)
            return PowerLogEvent(
                kind=EVENT_PLAYER_NAME, timestamp=timestamp, source=source,
                raw=raw, text=content,
                data={"player_id": player_id, "captured": self.capture_player_names},
            )

        return None

    def _parse_full_entity(
        self, timestamp: str, source: str, content: str, raw: str
    ) -> Optional[PowerLogEvent]:
        match = _RE_FULL_CREATE.match(content)
        if match:
            entity_id = int(match.group(1))
            card_id = match.group(2)
            entity = self._ensure_entity(entity_id)
            if card_id:
                entity.card_id = card_id
            self._pending_entity_id = entity_id
            return PowerLogEvent(
                kind=EVENT_FULL_ENTITY, timestamp=timestamp, source=source,
                raw=raw, entity_id=entity_id, card_id=card_id, text=content,
                data={"creating": True},
            )
        match = _RE_FULL_UPDATE.match(content)
        if match:
            ref, card_id = match.group(1), match.group(2)
            entity_id = self._resolve_entity_ref(ref)
            if not entity_id:
                self.stats["unresolved_entity_refs"] += 1
                return None
            entity = self._ensure_entity(entity_id)
            if card_id:
                entity.card_id = card_id
            self._update_from_ref(entity, ref)
            self._pending_entity_id = entity_id
            return PowerLogEvent(
                kind=EVENT_FULL_ENTITY, timestamp=timestamp, source=source,
                raw=raw, entity_id=entity_id, card_id=card_id, text=content,
                data={"creating": False},
            )
        return None

    def _parse_show_entity(
        self, timestamp: str, source: str, content: str, raw: str
    ) -> Optional[PowerLogEvent]:
        match = _RE_SHOW.match(content)
        if not match:
            return None
        ref, card_id = match.group(1), match.group(2)
        entity_id = self._resolve_entity_ref(ref)
        if not entity_id:
            self.stats["unresolved_entity_refs"] += 1
            return None
        entity = self._ensure_entity(entity_id)
        if card_id:
            entity.card_id = card_id
        self._update_from_ref(entity, ref)
        self._pending_entity_id = entity_id
        is_change = content.startswith("CHANGE_ENTITY")
        return PowerLogEvent(
            kind=EVENT_CHANGE_ENTITY if is_change else EVENT_SHOW_ENTITY,
            timestamp=timestamp,
            source=source,
            raw=raw,
            entity_id=entity_id,
            card_id=card_id,
            text=content,
            data={"change": is_change},
        )

    def _parse_tag_change(
        self, timestamp: str, source: str, content: str, raw: str
    ) -> Optional[PowerLogEvent]:
        match = _RE_TAG_CHANGE.match(content)
        if not match:
            self.stats["malformed_tag_change"] += 1
            return None
        ref, tag, value = match.group(1), match.group(2), match.group(3)
        entity_id = self._resolve_entity_ref(ref)
        if not entity_id:
            self.stats["unresolved_entity_refs"] += 1
            return None
        entity = self._ensure_entity(entity_id)
        entity.tags[tag] = value
        self._update_from_ref(entity, ref)
        self._apply_global_tag(tag, value)
        return PowerLogEvent(
            kind=EVENT_TAG_CHANGE, timestamp=timestamp, source=source,
            raw=raw, entity_id=entity_id, tag=tag, value=value, text=content,
        )

    def _parse_block_start(
        self, timestamp: str, source: str, content: str, raw: str
    ) -> Optional[PowerLogEvent]:
        block_match = _RE_BLOCK_TYPE.search(content)
        if not block_match:
            self.stats["malformed_block_start"] += 1
            return None
        block_type = block_match.group(1)
        entity_match = _RE_BLOCK_ENTITY.search(content)
        ref = entity_match.group(1) if entity_match else ""
        entity_id = self._resolve_entity_ref(ref) if ref else 0
        effect_card = _RE_BLOCK_EFFECT_CARD.search(content)
        effect_index = _RE_BLOCK_EFFECT_INDEX.search(content)
        target = _RE_BLOCK_TARGET.search(content)
        sub_option = _RE_BLOCK_SUB.search(content)
        trigger = _RE_BLOCK_TRIGGER.search(content)
        block = PowerBlock(
            block_type=block_type,
            entity_id=entity_id,
            card_id=self.card_id(entity_id) if entity_id else "",
            effect_card_id=effect_card.group(1) if effect_card else "",
            effect_index=int(effect_index.group(1)) if effect_index else -1,
            target=target.group(1).strip() if target else "",
            sub_option=int(sub_option.group(1)) if sub_option else -1,
            trigger_keyword=trigger.group(1) if trigger else "",
            index=self.stats.get("blocks_started", 0),
        )
        self.stats["blocks_started"] += 1
        self.blocks.append(block)
        return PowerLogEvent(
            kind=EVENT_BLOCK_START, timestamp=timestamp, source=source,
            raw=raw, entity_id=entity_id, block_type=block_type, text=content,
            data=block.to_dict(),
        )

    def _parse_block_end(
        self, timestamp: str, source: str, content: str, raw: str
    ) -> Optional[PowerLogEvent]:
        block = self.blocks.pop() if self.blocks else None
        if block is not None:
            self.stats["blocks_ended"] += 1
        return PowerLogEvent(
            kind=EVENT_BLOCK_END, timestamp=timestamp, source=source,
            raw=raw, block_type=block.block_type if block else "", text=content,
            data={"block": block.to_dict() if block else None,
                  "depth_after": len(self.blocks)},
        )

    # ── 内部：实体/引用 ────────────────────────────────────────────
    def _ensure_entity(self, entity_id: int) -> PowerEntity:
        entity = self.entities.get(entity_id)
        if entity is None:
            entity = PowerEntity(entity_id=entity_id)
            self.entities[entity_id] = entity
        return entity

    def _resolve_entity_ref(self, ref: str) -> int:
        """把日志里的 Entity=... 引用解析成 entity id；解析不了返回 0。"""
        text = str(ref or "").strip()
        if not text:
            return 0
        match = _RE_ID.search(text)
        if match:
            return int(match.group(1))
        if "GameEntity" in text:
            return self.game_entity_id
        if text.isdigit():
            return int(text)
        name_match = _RE_NAME_IN_REF.search(text)
        if name_match:
            entity_id = self._name_to_eid.get(name_match.group(1).strip())
            if entity_id:
                return entity_id
        # 真实日志里 TAG_CHANGE 也会直接用玩家名（如 ``Entity=玩家名#1234``）
        # 或实体名（``Entity=GameEntity`` 之外）引用；名字表里能查到就解析。
        bare = text.strip()
        if bare in self._name_to_eid:
            return self._name_to_eid[bare]
        # 名字可能带尾随空格/标点
        stripped = bare.rstrip(" .,;:")
        if stripped in self._name_to_eid:
            return self._name_to_eid[stripped]
        return 0

    def _update_from_ref(self, entity: PowerEntity, ref: str) -> None:
        card_match = _RE_CARD_IN_REF.search(ref)
        if card_match and card_match.group(1) and not entity.card_id:
            entity.card_id = card_match.group(1)
        zone_match = _RE_ZONE_IN_REF.search(ref)
        if zone_match:
            entity.tags.setdefault("ZONE", zone_match.group(1))
        name_match = _RE_NAME_IN_REF.search(ref)
        if name_match:
            name = name_match.group(1).strip()
            if name and not entity.name:
                entity.name = name
                self._name_to_eid.setdefault(name, entity.entity_id)

    def _apply_global_tag(self, tag: str, value: str) -> None:
        """把全局相关 tag 同步到快照字段（turn/phase/seed）。"""
        if tag == "GAME_SEED":
            try:
                self.game_seed = int(value)
            except (TypeError, ValueError):
                pass
        elif tag == "TURN":
            try:
                turn = int(value)
            except (TypeError, ValueError):
                return
            if 0 < turn < 1000:
                self.turn = turn
        elif tag == "BACON_IN_COMBAT_PHASE":
            self.phase = "combat" if value not in ("0", "", "false", "False") else "recruit"
        elif tag == "PLAYSTATE" and not self.phase:
            self.phase = "recruit"

    def _gold_of(self, entity: Optional[PowerEntity]) -> int:
        if entity is None:
            return 0
        gold = (
            entity.int_tag("RESOURCES")
            + entity.int_tag("TEMP_RESOURCES")
            - entity.int_tag("RESOURCES_USED")
        )
        return max(0, gold)

    def _count_zone(self, player_entity_id: int, zone: str) -> int:
        count = 0
        for entity in self.entities.values():
            if entity.controller == player_entity_id and entity.zone == zone:
                count += 1
        return count

    # ── 内部：事件记录 ─────────────────────────────────────────────
    def _emit(self, kind: str, **kwargs: Any) -> PowerLogEvent:
        event = PowerLogEvent(kind=kind, **kwargs)
        return self._emit_event(event)

    def _emit_event(self, event: PowerLogEvent) -> PowerLogEvent:
        self.events.append(event)
        self.events_by_kind[event.kind] += 1
        return event
