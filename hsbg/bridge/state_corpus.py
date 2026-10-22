"""真实战斗边界状态语料导出（``runs/state_corpus/``）。

用途
----
离线批量差分（engine-analyst 的 BobsBuddy oracle / diff-harness）需要**真实对局
状态分布**，而不是"基础卡面"：战斗边界的双方战团、每个随从的当前 atk/health/
golden/关键词/脚本计数、英雄与技能上下文，以及**哪些字段不可见**。

输入（全部已有产物，只读）
--------------------------
* ``runs/official_traces_powerlog{,2,3}/``：真实 Power.log 轨迹（26 场战斗，
  有 card_id / 关键词 / 事件流）；
* ``runs/official_traces_hdt/``：HDT BobsBuddy 会话日志抽取的 677 条真实战斗
  （双方战团快照 + 官方实际结果 + BB 概率；无事件流、无英雄血量/等级）；
* ``runs/bg_last_games_20261018.xml``：HDT ``BgsLastGames.xml`` 的 45 局终局
  战团（只有本地玩家一侧，含完整 tag 数值）。

输出
----
* ``states.jsonl``：一行一个战斗边界状态对；
* ``schema.json``：字段说明（JSON Schema 风格）；
* 覆盖率报告（默认 ``reversed/rea/state_corpus_report.md``）。

设计原则
--------
1. **不用基础卡面替代真实状态**：atk/health/golden/关键词/脚本计数全部来自
   真实 trace/日志；卡面只用于补 **静态身份字段**（tier/races/card name），
   并显式标注 ``*_source="carddb"``。
2. **不可见就写 hidden**：对手战团缺失、英雄血量/等级/技能缺失、trinket/anomaly/
   quest 不在 trace schema 里，都写进 ``hidden_fields`` / ``hidden_reasons``，
   绝不猜测填充。
3. **只读**：不修改 `data/`、`hsrl2/`、`hsbg/env/` 或游戏目录。
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .catalog import load_engine_cards
from .powerlog import (
    EVENT_BLOCK_START,
    EVENT_CREATE_GAME,
    EVENT_ENTITY_TAG,
    EVENT_FULL_ENTITY,
    EVENT_PLAYER,
    EVENT_SHOW_ENTITY,
    EVENT_TAG_CHANGE,
    PowerLogParser,
)
from .trace import OfficialCombatTrace, iter_trace_paths, load_trace

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "runs"
DEFAULT_OUT_DIR = RUNS_DIR / "state_corpus"
DEFAULT_POWERLOG_DIRS: Tuple[Path, ...] = (
    RUNS_DIR / "official_traces_powerlog",
    RUNS_DIR / "official_traces_powerlog2",
    RUNS_DIR / "official_traces_powerlog3",
)
DEFAULT_HDT_DIR = RUNS_DIR / "official_traces_hdt"
DEFAULT_XML = RUNS_DIR / "bg_last_games_20261018.xml"
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_REPORT = ROOT / "reversed" / "rea" / "state_corpus_report.md"
DEFAULT_TAG_SOURCES = {
    "official": ROOT / "reversed" / "net" / "Assembly-CSharp" / "enums.json",
    "hearthdb": ROOT / "reversed" / "net" / "HearthDb" / "enums.json",
    "rizling": ROOT
    / "reversed"
    / "rizling_latest"
    / "bgcontroller"
    / "data"
    / "game_tags.json",
}

SCHEMA_STATE = "bg_state_pair.v1"
SCHEMA_CORPUS = "bg_state_corpus.v1"
SOURCE_POWERLOG = "powerlog"
SOURCE_HDT = "hdt_bobsbuddy"
SOURCE_XML = "bg_last_games_xml"

#: 关键字 tag 名（XML 数值 tag 用官方枚举反查后匹配）
KEYWORD_TAG_NAMES: Mapping[str, str] = {
    "TAUNT": "taunt",
    "DIVINE_SHIELD": "divine_shield",
    "POISONOUS": "poisonous",
    "VENOMOUS": "venomous",
    "REBORN": "reborn",
    "WINDFURY": "windfury",
    "MEGA_WINDFURY": "mega_windfury",
    "CLEAVE": "cleave",
    "STEALTH": "stealth",
    "ELUSIVE": "elusive",
    "IMMUNE": "immune",
}
#: trace 里 HDT 简写/别名 → 规范关键词
_KEYWORD_ALIASES: Mapping[str, str] = {
    "div": "divine_shield",
    "divine shield": "divine_shield",
    "pois": "poisonous",
    "poison": "poisonous",
    "ven": "venomous",
    "mega-windfury": "mega_windfury",
}
KNOWN_KEYWORDS: Tuple[str, ...] = (
    "taunt", "divine_shield", "poisonous", "venomous", "reborn",
    "windfury", "mega_windfury", "cleave", "stealth", "elusive", "immune",
)

# ── Deity（旧神）隐藏状态 ─────────────────────────────────────────────
#: 两个 Deity token（官方二选一；见 hsrl2/deity.py / ENGINE_NOTES F-07）
DEITY_CARD_IDS: Tuple[str, ...] = ("BGFYM_000", "BGFYM_011")
#: Power.log 里的 Deity 目标/签名卡（`BG_OldGod`，OBJECTIVE + BOOK/Sigil tag）
DEITY_SIGIL_CARD_ID = "BG_OldGod"
#: Deity 目标实体卡 id（`BG_OldGod` 承载 cardid/atk/health/progress/sigil）
DEITY_OBJECTIVE_CARD_ID = "BG_OldGod"
DEITY_FIELDS: Tuple[str, ...] = (
    "deity_card_id",
    "deity_atk",
    "deity_health",
    "deity_progress",
    "deity_awakened",
    "deity_sigil_card_id",
)
#: XML 里关心的数值 tag 名
XML_STAT_TAGS = {
    "atk": "ATK",
    "health": "HEALTH",
    "damage": "DAMAGE",
    "premium": "PREMIUM",
    "tech_level": "TECH_LEVEL",
    "card_race": "CARDRACE",
    "zone_position": "ZONE_POSITION",
    "attached": "ATTACHED",
    "creator": "CREATOR",
    "copied_from_entity_id": "COPIED_FROM_ENTITY_ID",
    "script_data_num_1": "TAG_SCRIPT_DATA_NUM_1",
    "script_data_num_2": "TAG_SCRIPT_DATA_NUM_2",
    "script_data_num_3": "TAG_SCRIPT_DATA_NUM_3",
    "script_data_num_4": "TAG_SCRIPT_DATA_NUM_4",
    "script_data_num_5": "TAG_SCRIPT_DATA_NUM_5",
    "script_data_num_6": "TAG_SCRIPT_DATA_NUM_6",
}
_SCRIPT_TAG_RE = re.compile(r"(?:TAG_)?ScriptDataNum([1-6])", re.I)


# ══════════════════════════════════════════════════════════════════════
# 静态资源（卡面身份 / 枚举反查）
# ══════════════════════════════════════════════════════════════════════


def load_card_index(data_dir: Optional[Path | str] = None) -> Dict[str, Any]:
    """加载项目 `data/` 的卡牌记录（只用于补 tier/races/name 等静态身份字段）。"""
    root = Path(data_dir or DEFAULT_DATA_DIR)
    records, files, raw_union = load_engine_cards(root)
    by_id: Dict[str, Dict[str, Any]] = {}
    by_dbf: Dict[int, str] = {}
    for key, record in records.items():
        by_id[key] = record
        raw_id = record.get("_raw_id")
        if raw_id:
            by_id[str(raw_id)] = record
        dbf = record.get("dbf_id")
        if isinstance(dbf, int) and dbf:
            by_dbf.setdefault(dbf, str(record.get("id") or raw_id or key))
    return {
        "data_dir": str(root),
        "records": records,
        "by_id": by_id,
        "by_dbf": by_dbf,
        "file_counts": files,
        "raw_union": raw_union,
        "patch": _read_patch(root),
        "pool_minions": _read_id_list(root / "bg_pool_minions.json"),
        "pool_spells": _read_id_list(root / "bg_pool_spells.json"),
    }


def _read_patch(data_dir: Path) -> Optional[str]:
    path = data_dir / "bg_summary.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return str(raw.get("patch")) if isinstance(raw, dict) else None
    except (OSError, ValueError):
        return None


def _read_id_list(path: Path) -> set:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(raw, list):
        return set()
    return {str(x["id"]) for x in raw if isinstance(x, Mapping) and x.get("id")}


def load_tag_maps() -> Dict[str, Any]:
    """数值 tag id → 名字（官方为主，HearthDb/rizling 补充），以及种族名表。"""
    tag_names: Dict[int, str] = {}
    race_names: Dict[int, str] = {}
    sources: Dict[str, Optional[str]] = {"official": None, "hearthdb": None, "rizling": None}

    official_path = DEFAULT_TAG_SOURCES["official"]
    if official_path.is_file():
        try:
            enums = json.loads(official_path.read_text(encoding="utf-8"))
            values = (enums.get("GAME_TAG") or {}).get("values") or {}
            for name, value in values.items():
                tag_names.setdefault(int(value), str(name))
            race_values = (enums.get("TAG_RACE") or {}).get("values") or {}
            for name, value in race_values.items():
                race_names.setdefault(int(value), str(name))
            sources["official"] = str(official_path)
        except (OSError, ValueError):
            pass
    hearthdb_path = DEFAULT_TAG_SOURCES["hearthdb"]
    if hearthdb_path.is_file():
        try:
            enums = json.loads(hearthdb_path.read_text(encoding="utf-8"))
            values = (enums.get("HearthDb.Enums.GameTag") or {}).get("values") or {}
            for name, value in values.items():
                tag_names.setdefault(int(value), str(name).replace("HearthDb.Enums.", ""))
            sources["hearthdb"] = str(hearthdb_path)
        except (OSError, ValueError):
            pass
    rizling_path = DEFAULT_TAG_SOURCES["rizling"]
    if rizling_path.is_file():
        try:
            raw = json.loads(rizling_path.read_text(encoding="utf-8"))
            enums = raw.get("enums") or {}
            values = enums.get("GameTag") or {}
            for name, value in values.items():
                tag_names.setdefault(int(value), str(name))
            race_values = enums.get("Race") or {}
            for name, value in race_values.items():
                race_names.setdefault(int(value), str(name))
            sources["rizling"] = str(rizling_path)
        except (OSError, ValueError):
            pass
    # 反向：名字 → 数值（供 XML tag 名匹配）
    tag_ids = {name: value for value, name in tag_names.items()}
    return {
        "tag_names": tag_names,
        "tag_ids": tag_ids,
        "race_names": race_names,
        "sources": sources,
        "mapped_tag_count": len(tag_names),
    }


# ══════════════════════════════════════════════════════════════════════
# 单卡/战团 → 语料记录
# ══════════════════════════════════════════════════════════════════════


def _canonical_card_id(card_id: str) -> str:
    cid = str(card_id)
    if cid.endswith("_G"):
        return cid[:-2]
    return cid


def _card_lookup(index: Mapping[str, Any], card_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not card_id:
        return None
    by_id = index["by_id"]
    return by_id.get(str(card_id)) or by_id.get(_canonical_card_id(str(card_id)))


def _static_card_fields(
    card: Optional[Mapping[str, Any]],
    races_by_id: Mapping[int, str],
) -> Dict[str, Any]:
    """只返回静态身份字段；真实状态（atk/health/golden/keywords）不由卡面覆盖。"""
    if not card:
        return {
            "card_found": False,
            "static": {},
            "tier_source": None,
            "races_source": None,
        }
    tier = card.get("tech_level")
    races: List[str] = []
    card_race = card.get("card_race")
    if isinstance(card_race, int):
        name = races_by_id.get(card_race)
        if name:
            races.append(name)
    for item in card.get("race_tags") or []:
        text = str(item).upper()
        if text and text not in races:
            races.append(text)
    base_keywords: List[str] = []
    for field_name, keyword in (
        ("deathrattle", "deathrattle"),
        ("battlecry", "battlecry"),
        ("taunt", "taunt"),
        ("divine_shield", "divine_shield"),
        ("reborn", "reborn"),
        ("windfury", "windfury"),
        ("venomous", "venomous"),
        ("poisonous", "poisonous"),
        ("magnetic", "magnetic"),
        ("choose_one", "choose_one"),
        ("avenge", "avenge"),
        ("rally", "rally"),
        ("start_of_combat", "start_of_combat"),
    ):
        if card.get(field_name):
            base_keywords.append(keyword)
    static = {
        "name": card.get("name"),
        "card_type": card.get("card_type"),
        "tier": tier if isinstance(tier, int) else None,
        "races": races,
        "base_keywords": base_keywords,
        "spell_school": card.get("spell_school"),
        "text": card.get("text"),
    }
    return {
        "card_found": True,
        "static": static,
        "tier_source": "carddb" if isinstance(tier, int) else None,
        "races_source": "carddb" if races else None,
    }


def _normalize_keywords(keywords: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for raw in keywords or []:
        text = str(raw).strip()
        if not text:
            continue
        lowered = text.casefold()
        name = _KEYWORD_ALIASES.get(lowered, lowered.replace(" ", "_"))
        if name and name not in out:
            out.append(name)
    return out


def _keyword_flags(keywords: Iterable[str]) -> Dict[str, bool]:
    present = set(keywords)
    return {keyword: keyword in present for keyword in KNOWN_KEYWORDS}


def _script_data_from_trace_tags(tags: Mapping[str, Any]) -> Dict[str, Optional[int]]:
    out: Dict[str, Optional[int]] = {f"script_data_num_{i}": None for i in range(1, 5)}
    for key, value in (tags or {}).items():
        match = _SCRIPT_TAG_RE.search(str(key))
        if not match:
            continue
        try:
            out[f"script_data_num_{match.group(1)}"] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _enchantment_from_trace_tags(tags: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    raw = {}
    for key in ("Enchantments", "Deathrattles", "AttachedModularEntity"):
        if tags.get(key) not in (None, ""):
            raw[key] = str(tags[key])
    if not raw:
        return None
    return {"source": "bobsbuddy_tag", **raw}


def _minion_from_trace(
    minion: Any,
    *,
    index: Mapping[str, Any],
    tags_map: Mapping[str, Any],
    side: str,
) -> Dict[str, Any]:
    card = _card_lookup(index, minion.card_id)
    static = _static_card_fields(card, tags_map["race_names"])
    keywords = _normalize_keywords(minion.keywords)
    script = _script_data_from_trace_tags(minion.tags)
    hidden_fields: List[str] = []
    if not minion.card_id:
        hidden_fields.append("card_id")
    if minion.atk is None:
        hidden_fields.append("atk")
    if minion.health is None:
        hidden_fields.append("health")
    record: Dict[str, Any] = {
        "slot": int(minion.slot),
        "zone_position": int(minion.slot),
        "zone_position_source": "simulation_input_order",
        "side": side,
        "card_id": minion.card_id,
        "name": minion.name or (static["static"].get("name") if card else None),
        "atk": minion.atk,
        "health": minion.health,
        "max_health": None,
        "damage": None,
        "golden": bool(minion.golden),
        "golden_source": "trace_observed",
        "tier": static["static"].get("tier"),
        "tier_source": static["tier_source"],
        "races": list(static["static"].get("races") or []),
        "races_source": static["races_source"],
        "keywords": keywords,
        "keyword_flags": _keyword_flags(keywords),
        "keyword_source": "trace_observed",
        "card_keywords_static": list(static["static"].get("base_keywords") or []),
        "script_data_num_1": script["script_data_num_1"],
        "script_data_num_2": script["script_data_num_2"],
        "script_data_num_3": script["script_data_num_3"],
        "script_data_num_4": script["script_data_num_4"],
        "script_data_source": "trace_tags" if any(
            value is not None for value in script.values()
        ) else None,
        "enchantment_derived": _enchantment_from_trace_tags(minion.tags),
        "raw_tags": dict(minion.tags or {}),
        "annotations": list(minion.annotations or []),
        "card_found": static["card_found"],
        "hidden_fields": hidden_fields,
        "derived_fields": {},
    }
    if static["tier_source"]:
        record["derived_fields"]["tier"] = "data/bg_cards.json(static identity)"
    if static["races_source"]:
        record["derived_fields"]["races"] = "data/bg_cards.json(static identity)"
    return record


def _side_hidden_fields(
    band: Any, source: str
) -> Tuple[List[str], List[str]]:
    """返回（显式隐藏字段, 原因）。不猜测任何缺失字段。"""
    hidden: List[str] = []
    reasons: List[str] = []
    if band.health is None:
        hidden.append("hero_health")
        reasons.append("hero_health_not_in_source")
    if band.armor is None:
        hidden.append("hero_armor")
        reasons.append("hero_armor_not_in_source")
    if band.tier is None:
        hidden.append("tavern_tier")
        reasons.append("tavern_tier_not_in_source")
    if band.hero_card_id is None:
        hidden.append("hero_card_id")
        reasons.append("hero_card_id_not_in_source")
    if band.hero_power_id is None:
        hidden.append("hero_power_id")
        reasons.append("hero_power_id_not_in_source")
    if band.hero_power_used is None:
        hidden.append("hero_power_used")
        reasons.append("hero_power_used_not_in_source")
    # trace schema 不保留饰品/异变/任务实体
    hidden.extend(["trinkets", "anomaly", "quest"])
    reasons.extend(
        [
            "trinkets_not_in_official_combat_trace_schema",
            "anomaly_not_in_official_combat_trace_schema",
            "quest_not_in_official_combat_trace_schema",
        ]
    )
    return hidden, reasons


def _board_signature(board: Iterable[Any]) -> Tuple[Tuple[Any, ...], ...]:
    return tuple(sorted(tuple(item) for item in board))


def _trace_board_signature(minions: Iterable[Any]) -> Tuple[Tuple[Any, ...], ...]:
    return tuple(sorted(
        (
            str(getattr(m, "card_id", "") or ""),
            getattr(m, "atk", None),
            getattr(m, "health", None),
        )
        for m in minions
    ))


def _raw_log_for_trace_dir(directory: Path) -> Optional[Path]:
    """official_traces_powerlog*/index.json → 原始 Power.log 路径。"""
    index_path = Path(directory) / "index.json"
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    paths = ((raw.get("powerlog") or {}).get("paths") or []) if isinstance(raw, dict) else []
    for item in paths:
        path = Path(str(item))
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            return path
    fallback = {
        "official_traces_powerlog": RUNS_DIR / "powerlog" / "Power.log",
        "official_traces_powerlog2": RUNS_DIR / "powerlog_2214" / "Power.log",
        "official_traces_powerlog3": RUNS_DIR / "powerlog_2240" / "Power.log",
    }
    candidate = fallback.get(Path(directory).name)
    return candidate if candidate is not None and candidate.is_file() else None


def _entity_player_id(parser: PowerLogParser, entity_id: int) -> Optional[int]:
    entity = parser.entities.get(int(entity_id))
    if entity is None:
        return None
    pid = entity.int_tag("PLAYER_ID", 0)
    if pid:
        return pid
    ctrl = entity.int_tag("CONTROLLER", 0)
    return ctrl or None


def _board_snapshot(parser: PowerLogParser) -> Dict[int, List[Tuple[Any, ...]]]:
    boards: Dict[int, List[Tuple[Any, ...]]] = {}
    for entity in parser.entities.values():
        if entity.tag("CARDTYPE") != "MINION" or entity.tag("ZONE") != "PLAY":
            continue
        ctrl = entity.int_tag("CONTROLLER", 0)
        if not ctrl:
            continue
        boards.setdefault(ctrl, []).append((
            str(entity.card_id or ""),
            entity.int_tag("ATK", 0),
            entity.int_tag("HEALTH", 0),
        ))
    for board in boards.values():
        board.sort()
    return boards


def _dbf_to_deity_card(index: Mapping[str, Any], dbf: int) -> Optional[str]:
    if not dbf:
        return None
    card_id = (index.get("by_dbf") or {}).get(int(dbf))
    if card_id:
        return card_id
    return None


def build_deity_index(
    raw_log_path: Path,
    *,
    index: Mapping[str, Any],
) -> Dict[int, Dict[str, Any]]:
    """从原始 Power.log 重建每场战斗开始时的 Deity 隐藏状态。

    证据映射（37.0 Aberration / BG_OldGod）：
    - ``BG_OldGod`` objective 创建 tag：``TAG_SCRIPT_DATA_NUM_2/3`` = Deity
      atk/health，``BACON_EVOLUTION_CARD_ID``/``TAG_SCRIPT_DATA_NUM_6`` = dbf，
      ``BACON_DEITY_SIGIL`` = 1 → sigil card ``BG_OldGod``；
    - ``BACON_OLD_GOD_ATTACK/HEALTH``（玩家/英雄实体）= 该玩家当前 Deity 属性
      （本地玩家；objective reveal 后的 CONTROLLER 指向对手）；
    - ``BGFYM_000/011`` token summon = 该侧 Deity 卡 id（战斗内 awaken 后可见）。
    - 战斗开始 progress 按卡面 "each combat" 重置为 0；awakened 为 False；
      不猜测未观测字段。
    """
    parser = PowerLogParser(capture_player_names=True)

    def _owner_from_text(raw: str) -> Optional[int]:
        if not raw:
            return None
        match = re.search(r"\bplayer=(\d+)", raw)
        return int(match.group(1)) if match else None

    combats: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    phase: Optional[str] = None
    turn = 0
    objectives: Dict[int, Dict[str, Any]] = {}
    tokens: Dict[int, Dict[str, Any]] = {}
    deity_stats: Dict[int, Dict[str, int]] = {}
    known_cards: Dict[int, str] = {}
    known_sigils: Dict[int, str] = {}

    for line in Path(raw_log_path).open("r", encoding="utf-8", errors="replace"):
        for event in parser.feed(line):
            text = str(getattr(event, "text", "") or "")
            if (
                event.kind == EVENT_BLOCK_START
                and str(getattr(event, "block_type", "") or "").upper() == "ATTACK"
                and current is not None
                and current.get("boards") is None
            ):
                current["boards"] = _board_snapshot(parser)
            if event.kind == EVENT_TAG_CHANGE:
                if event.entity_id == parser.game_entity_id:
                    if event.tag == "TURN":
                        try:
                            turn = int(event.value)
                        except (TypeError, ValueError):
                            pass
                    elif event.tag == "BACON_IN_COMBAT_PHASE":
                        if event.value == "1" and phase != "1":
                            phase = "1"
                            current = {
                                "combat_index": len(combats),
                                "turn": turn,
                                # 战斗边界板面在第一个 ATTACK block 才完整
                                # （对手战团会逐步进入 PLAY，与 trace 口径一致）；
                                # 无攻击战斗用 phase 时快照兜底。
                                "boards": None,
                                "phase_boards": _board_snapshot(parser),
                                "start_deity": {
                                    pid: dict(values)
                                    for pid, values in deity_stats.items()
                                },
                                "objective_eids": [],
                                "token_eids": [],
                            }
                            combats.append(current)
                        elif event.value == "0":
                            phase = "0"
                if event.tag in ("BACON_OLD_GOD_ATTACK", "BACON_OLD_GOD_HEALTH"):
                    pid = _entity_player_id(parser, event.entity_id)
                    if pid:
                        try:
                            value = int(event.value)
                        except (TypeError, ValueError):
                            value = 0
                        deity_stats.setdefault(pid, {})[event.tag] = value
                if event.entity_id in objectives and event.tag == "CONTROLLER":
                    try:
                        objectives[event.entity_id]["controller"] = int(event.value)
                    except (TypeError, ValueError):
                        pass
                if event.entity_id in tokens:
                    token = tokens[event.entity_id]
                    owner = _owner_from_text(text)
                    if owner:
                        token["owner"] = owner
                    if event.tag in ("ATK", "HEALTH"):
                        try:
                            token[event.tag.lower()] = int(event.value)
                        except (TypeError, ValueError):
                            pass
                if event.entity_id in tokens and event.tag == "CONTROLLER":
                    try:
                        tokens[event.entity_id]["owner"] = int(event.value)
                    except (TypeError, ValueError):
                        pass
            elif event.kind in (EVENT_FULL_ENTITY, EVENT_SHOW_ENTITY):
                entity = parser.entities.get(int(event.entity_id))
                if entity is None:
                    continue
                if entity.card_id == DEITY_OBJECTIVE_CARD_ID:
                    obj = objectives.setdefault(
                        int(event.entity_id),
                        {"combat_index": current["combat_index"] if current else None,
                         "creation": {}, "controller": None},
                    )
                    if current is not None and current["combat_index"] not in current["objective_eids"]:
                        current["objective_eids"].append(int(event.entity_id))
                if entity.card_id in DEITY_CARD_IDS:
                    token = tokens.setdefault(
                        int(event.entity_id),
                        {"combat_index": current["combat_index"] if current else None,
                         "card_id": entity.card_id, "owner": None,
                         "atk": None, "health": None},
                    )
                    token["card_id"] = entity.card_id
                    owner = _owner_from_text(text) or _entity_player_id(parser, event.entity_id)
                    if owner:
                        token["owner"] = owner
                    if current is not None and int(event.entity_id) not in current["token_eids"]:
                        current["token_eids"].append(int(event.entity_id))
            elif event.kind == EVENT_ENTITY_TAG:
                entity = parser.entities.get(int(event.entity_id))
                if entity is None:
                    continue
                if entity.card_id == DEITY_OBJECTIVE_CARD_ID:
                    obj = objectives.setdefault(
                        int(event.entity_id),
                        {"combat_index": current["combat_index"] if current else None,
                         "creation": {}, "controller": None},
                    )
                    obj["creation"][event.tag] = event.value
                if entity.card_id in DEITY_CARD_IDS:
                    token = tokens.setdefault(
                        int(event.entity_id),
                        {"combat_index": current["combat_index"] if current else None,
                         "card_id": entity.card_id, "owner": None,
                         "atk": None, "health": None},
                    )
                    token["card_id"] = entity.card_id
                    if event.tag == "CONTROLLER":
                        try:
                            token["owner"] = int(event.value)
                        except (TypeError, ValueError):
                            pass
                    elif event.tag in ("ATK", "HEALTH"):
                        try:
                            token[event.tag.lower()] = int(event.value)
                        except (TypeError, ValueError):
                            pass

    # 战斗外创建的持久 objective（如 395）承载玩家 Deity 卡 id / sigil；
    # 属性仍以 BACON_OLD_GOD_* 边界 tag 为准。
    for obj in objectives.values():
        if obj.get("combat_index") is not None:
            continue
        creation = obj.get("creation") or {}
        pid = obj.get("controller")
        if not pid:
            try:
                pid = int(creation.get("CONTROLLER") or 0) or None
            except (TypeError, ValueError):
                pid = None
        if not pid:
            continue
        for key in ("BACON_EVOLUTION_CARD_ID", "TAG_SCRIPT_DATA_NUM_6"):
            try:
                dbf = int(creation.get(key) or 0)
            except (TypeError, ValueError):
                dbf = 0
            if dbf:
                card_id = _dbf_to_deity_card(index, dbf)
                if card_id:
                    known_cards.setdefault(pid, card_id)
                break
        if str(creation.get("BACON_DEITY_SIGIL") or "0") == "1":
            known_sigils.setdefault(pid, DEITY_SIGIL_CARD_ID)

    # 每场战斗：优先 objective 创建 tag（对手 objective 在 combat 内 reveal），
    # 再用玩家 BACON_OLD_GOD_* 边界快照（本地持久 tag），最后 token 卡 id。
    for combat in combats:
        deities: Dict[int, Dict[str, Any]] = {}
        for pid, values in (combat.get("start_deity") or {}).items():
            if "BACON_OLD_GOD_ATTACK" in values or "BACON_OLD_GOD_HEALTH" in values:
                deities[pid] = {
                    "deity_atk": values.get("BACON_OLD_GOD_ATTACK"),
                    "deity_health": values.get("BACON_OLD_GOD_HEALTH"),
                    "deity_source": "powerlog_BACON_OLD_GOD_tag",
                }
        for eid in combat.get("objective_eids") or []:
            obj = objectives.get(eid) or {}
            creation = obj.get("creation") or {}
            pid = obj.get("controller")
            if not pid:
                try:
                    pid = int(creation.get("CONTROLLER") or 0) or None
                except (TypeError, ValueError):
                    pid = None
            if not pid:
                continue
            dbf = 0
            for key in ("BACON_EVOLUTION_CARD_ID", "TAG_SCRIPT_DATA_NUM_6"):
                try:
                    dbf = int(creation.get(key) or 0)
                except (TypeError, ValueError):
                    dbf = 0
                if dbf:
                    break
            card_id = _dbf_to_deity_card(index, dbf)
            if card_id:
                known_cards[pid] = card_id
            try:
                atk = int(creation.get("TAG_SCRIPT_DATA_NUM_2") or 0)
                health = int(creation.get("TAG_SCRIPT_DATA_NUM_3") or 0)
            except (TypeError, ValueError):
                atk = health = 0
            sigil = str(creation.get("BACON_DEITY_SIGIL") or "0") == "1"
            if sigil:
                known_sigils[pid] = DEITY_SIGIL_CARD_ID
            entry = deities.setdefault(pid, {})
            if atk:
                entry["deity_atk"] = atk
            if health:
                entry["deity_health"] = health
            if card_id:
                entry["deity_card_id"] = card_id
            if sigil:
                entry["deity_sigil_card_id"] = DEITY_SIGIL_CARD_ID
            entry["deity_source"] = "powerlog_BG_OldGod_objective"
        for eid in combat.get("token_eids") or []:
            token = tokens.get(eid) or {}
            pid = token.get("owner")
            if not pid:
                continue
            card_id = token.get("card_id")
            if card_id:
                known_cards.setdefault(pid, card_id)
            entry = deities.setdefault(pid, {})
            if card_id and not entry.get("deity_card_id"):
                entry["deity_card_id"] = card_id
            if token.get("atk") and not entry.get("deity_atk"):
                entry["deity_atk"] = token["atk"]
            if token.get("health") and not entry.get("deity_health"):
                entry["deity_health"] = token["health"]
            entry.setdefault("deity_source", "powerlog_BGFYM_token")
        for pid, entry in deities.items():
            entry.setdefault("deity_card_id", known_cards.get(pid))
            entry.setdefault("deity_sigil_card_id", known_sigils.get(pid))
            entry["deity_progress"] = 0
            entry["deity_awakened"] = False
        combat["deities"] = deities
        if combat.get("boards") is None:
            combat["boards"] = combat.pop("phase_boards", {})
        else:
            combat.pop("phase_boards", None)
    return {combat["combat_index"]: combat for combat in combats}


def _map_trace_sides_to_players(
    trace: OfficialCombatTrace,
    combat: Mapping[str, Any],
) -> Dict[str, int]:
    """用战斗边界板面签名把 trace 的 player/opponent 映射回原始 player id。"""
    boards = combat.get("boards") or {}
    if not boards:
        return {}
    player_sig = _trace_board_signature(trace.player.minions)
    opponent_sig = _trace_board_signature(trace.opponent.minions)
    for pid, board in boards.items():
        sig = _board_signature(board)
        if sig != player_sig:
            continue
        others = [other for other in boards if other != pid]
        for other in others:
            if _board_signature(boards[other]) == opponent_sig:
                return {"player": pid, "opponent": other}
    # 退化匹配：只按随从数 + card id 多重集
    def _cards(sig: Iterable[Any]) -> Tuple[str, ...]:
        return tuple(sorted(str(item[0]) for item in sig))
    for pid, board in boards.items():
        sig = _board_signature(board)
        if _cards(sig) != _cards(player_sig):
            continue
        for other in boards:
            if other == pid:
                continue
            if _cards(_board_signature(boards[other])) == _cards(opponent_sig):
                return {"player": pid, "opponent": other}
    return {}


def _deity_relevant(card_ids: Iterable[Any], index: Mapping[str, Any]) -> bool:
    """该侧是否出现 Deity 机制相关卡（静态卡面文本含 Deity / BGFYM token）。

    只用于判断"缺字段是否属于 Deity 缺口"；不据此填充任何数值。
    """
    by_id = index.get("by_id") or {}
    for card_id in card_ids:
        cid = str(card_id or "")
        if cid in DEITY_CARD_IDS:
            return True
        record = by_id.get(cid) or {}
        if "Deity" in str(record.get("text") or ""):
            return True
    return False


def _deity_for_side(
    deity: Optional[Mapping[str, Any]],
    *,
    side: str,
    hidden_reason: str,
    relevant: bool = True,
) -> Dict[str, Any]:
    fields = {name: None for name in DEITY_FIELDS}
    if not deity:
        fields["deity_hidden"] = bool(relevant)
        fields["deity_source"] = "not_applicable" if not relevant else None
        fields["deity_hidden_reason"] = hidden_reason if relevant else None
        return fields
    for name in DEITY_FIELDS:
        fields[name] = deity.get(name)
    fields["deity_hidden"] = not bool(deity.get("deity_card_id"))
    fields["deity_source"] = deity.get("deity_source")
    if fields["deity_hidden"]:
        fields["deity_hidden_reason"] = "deity_card_id_not_observed"
    return fields


def _warband_from_trace(
    band: Any,
    *,
    side: str,
    index: Mapping[str, Any],
    tags_map: Mapping[str, Any],
) -> Dict[str, Any]:
    hidden, reasons = _side_hidden_fields(band, SOURCE_POWERLOG)
    minions = [
        _minion_from_trace(m, index=index, tags_map=tags_map, side=side)
        for m in band.minions
    ]
    hand = [
        _minion_from_trace(m, index=index, tags_map=tags_map, side=side)
        for m in band.hand
    ]
    return {
        "side": side,
        "hero_card_id": band.hero_card_id,
        "hero_name": band.hero_name,
        "hero_power_id": band.hero_power_id,
        "hero_power_used": band.hero_power_used,
        "hero_power_data": band.hero_power_data,
        "second_hero_power_id": band.second_hero_power_id,
        "health": band.health,
        "armor": band.armor,
        "tier": band.tier,
        "tier_source": "trace_observed" if band.tier is not None else None,
        "minions": minions,
        "hand": hand,
        "detected": list(getattr(band, "detected", []) or []),
        "unsupported": list(getattr(band, "unsupported", []) or []),
        "trace_missing_fields": list(getattr(band, "missing_fields", []) or []),
        "hidden_fields": hidden,
        "hidden_reasons": reasons,
        **{name: None for name in DEITY_FIELDS},
        "deity_hidden": True,
        "deity_source": None,
        "deity_hidden_reason": None,
    }


def _state_id(*parts: Any) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def state_from_trace(
    trace: OfficialCombatTrace,
    *,
    index: Mapping[str, Any],
    tags_map: Mapping[str, Any],
    deity_combat: Optional[Mapping[str, Any]] = None,
    deity_sides: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """把一条 ``official_combat_trace.v1`` 转成一个状态对记录。"""
    player = _warband_from_trace(
        trace.player, side="player", index=index, tags_map=tags_map
    )
    opponent = _warband_from_trace(
        trace.opponent, side="opponent", index=index, tags_map=tags_map
    )
    deity_sources = deity_combat.get("deities") if deity_combat else None
    for side_name, band in (("player", player), ("opponent", opponent)):
        pid = (deity_sides or {}).get(side_name)
        info = (deity_sources or {}).get(pid) if pid is not None else None
        trace_band = trace.player if side_name == "player" else trace.opponent
        relevant = _deity_relevant(
            [m.card_id for m in (trace_band.minions or [])], index
        )
        if deity_combat is None:
            reason = "deity_not_in_source"
        elif info is None:
            reason = "deity_not_observed_in_powerlog_combat"
        else:
            reason = None
        fields = _deity_for_side(
            info, side=side_name, hidden_reason=reason, relevant=relevant
        )
        band.update(fields)
        missing = [name for name in DEITY_FIELDS if band.get(name) is None]
        if missing:
            band["deity_missing_fields"] = missing
        if fields.get("deity_hidden"):
            if "deity" not in band["hidden_fields"]:
                band["hidden_fields"].append("deity")
            if fields.get("deity_hidden_reason"):
                band["hidden_reasons"].append(fields["deity_hidden_reason"])
    # 板面级隐藏：任意随从缺 card_id/atk/health 视为状态不完整
    board_hidden: List[str] = []
    for side_name, band in (("player", player), ("opponent", opponent)):
        for slot, minion in enumerate(band["minions"]):
            if minion["hidden_fields"]:
                board_hidden.append(f"{side_name}.minion[{slot}]")
    context_reasons: List[str] = []
    for band in (player, opponent):
        context_reasons.extend(band["hidden_reasons"])
    context_reasons = sorted(set(context_reasons))
    hidden_state = bool(board_hidden)
    hidden_context = bool(context_reasons)
    state = {
        "schema": SCHEMA_STATE,
        "state_id": _state_id(trace.source, trace.episode_id, trace.trace_id),
        "trace_id": trace.trace_id,
        "episode_id": trace.episode_id,
        "source": trace.source,
        "combat_index": trace.combat_index,
        "turn": trace.turn,
        "boundary": "combat_start",
        "official_result": trace.official_result,
        "official_lethal": trace.official_lethal,
        "player": player,
        "opponent": opponent,
        "visibility": {"player": "observed", "opponent": "observed"},
        "hidden_state": hidden_state,
        "hidden_reasons": board_hidden,
        "hidden_context": hidden_context,
        "hidden_context_reasons": context_reasons,
        "context": {
            "official_damage": trace.official_damage,
            "damage_cap": trace.damage_cap,
            "damage_cap_enabled": trace.damage_cap_enabled,
            "game_seed": trace.game_seed,
            "bb_rates": trace.bb_rates,
            "bb_iterations": trace.bb_iterations,
            "heroes": trace.heroes,
            "boundary_mode": trace.boundary_mode,
            "event_count": len(trace.events),
            "trace_missing_fields": list(trace.missing_fields or []),
            "trace_notes": list(trace.notes or []),
        },
    }
    return state


# ══════════════════════════════════════════════════════════════════════
# BgsLastGames.xml（终局战团；仅本地玩家一侧）
# ══════════════════════════════════════════════════════════════════════


def _xml_text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    return text or None


def _decode_xml_tags(
    tags: Mapping[int, int],
    tag_names: Mapping[int, str],
) -> Tuple[Dict[str, Any], List[int]]:
    decoded: Dict[str, Any] = {}
    unmapped: List[int] = []
    for tag_id, value in sorted(tags.items()):
        name = tag_names.get(int(tag_id))
        if name:
            decoded[str(name)] = int(value)
        else:
            decoded[f"tag_{tag_id}"] = int(value)
            unmapped.append(int(tag_id))
    return decoded, unmapped


def _minion_from_xml(
    minion: ET.Element,
    *,
    slot: int,
    index: Mapping[str, Any],
    tags_map: Mapping[str, Any],
) -> Dict[str, Any]:
    card_id = _xml_text(minion.find("CardId"))
    tags: Dict[int, int] = {}
    for tag in minion.findall("Tags"):
        try:
            tags[int(tag.attrib["Tag"])] = int(tag.attrib["Value"])
        except (KeyError, TypeError, ValueError):
            continue
    tag_names = tags_map["tag_names"]
    tag_ids = tags_map["tag_ids"]
    decoded, unmapped = _decode_xml_tags(tags, tag_names)
    card = _card_lookup(index, card_id)
    static = _static_card_fields(card, tags_map["race_names"])

    def tag_value(field: str) -> Optional[int]:
        name = XML_STAT_TAGS.get(field)
        if not name:
            return None
        tag_id = tag_ids.get(name)
        if tag_id is None:
            return None
        value = tags.get(tag_id)
        return int(value) if value is not None else None

    atk = tag_value("atk")
    health = tag_value("health")
    damage = tag_value("damage")
    premium = tag_value("premium")
    tech_level = tag_value("tech_level")
    zone_position = tag_value("zone_position")
    keywords: List[str] = []
    for tag_name, keyword in KEYWORD_TAG_NAMES.items():
        tag_id = tag_ids.get(tag_name)
        if tag_id is not None and int(tags.get(tag_id, 0)) > 0:
            keywords.append(keyword)
    script = {
        f"script_data_num_{i}": tag_value(f"script_data_num_{i}")
        for i in range(1, 7)
    }
    enchantment = None
    if tag_value("attached") is not None or tag_value("creator") is not None:
        enchantment = {
            "source": "xml_raw_tags",
            "attached": tag_value("attached"),
            "creator": tag_value("creator"),
            "copied_from_entity_id": tag_value("copied_from_entity_id"),
        }
    hidden_fields: List[str] = []
    if not card_id:
        hidden_fields.append("card_id")
    if atk is None:
        hidden_fields.append("atk")
    if health is None:
        hidden_fields.append("health")
    record: Dict[str, Any] = {
        "slot": slot,
        "zone_position": zone_position if zone_position is not None else slot,
        "zone_position_source": "xml_tag_ZONE_POSITION"
        if zone_position is not None
        else "final_board_list_order",
        "side": "player",
        "card_id": card_id,
        "name": static["static"].get("name"),
        "atk": atk,
        "health": health,
        "max_health": (health + damage) if (health is not None and damage is not None) else None,
        "damage": damage,
        "golden": bool(premium) if premium is not None else None,
        "golden_source": "xml_tag_PREMIUM" if premium is not None else None,
        "tier": tech_level if tech_level is not None else static["static"].get("tier"),
        "tier_source": "xml_tag_TECH_LEVEL"
        if tech_level is not None
        else static["tier_source"],
        "races": list(static["static"].get("races") or []),
        "races_source": static["races_source"],
        "keywords": keywords,
        "keyword_flags": _keyword_flags(keywords),
        "keyword_source": "xml_numeric_tags"
        if keywords
        else "xml_tags_present_but_no_keyword_tag",
        "card_keywords_static": list(static["static"].get("base_keywords") or []),
        "script_data_num_1": script["script_data_num_1"],
        "script_data_num_2": script["script_data_num_2"],
        "script_data_num_3": script["script_data_num_3"],
        "script_data_num_4": script["script_data_num_4"],
        "script_data_num_5": script["script_data_num_5"],
        "script_data_num_6": script["script_data_num_6"],
        "script_data_source": "xml_tags",
        "enchantment_derived": enchantment,
        "raw_tags": decoded,
        "unmapped_tag_ids": unmapped,
        "annotations": [],
        "card_found": static["card_found"],
        "hidden_fields": hidden_fields,
        "derived_fields": {},
    }
    if static["tier_source"] and tech_level is None:
        record["derived_fields"]["tier"] = "data/bg_cards.json(static identity)"
    if static["races_source"]:
        record["derived_fields"]["races"] = "data/bg_cards.json(static identity)"
    return record


def states_from_xml(
    xml_path: Optional[Path | str] = None,
    *,
    index: Mapping[str, Any],
    tags_map: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """解析 HDT ``BgsLastGames.xml`` → 终局状态对（对手隐藏）。"""
    path = Path(xml_path or DEFAULT_XML)
    tree = ET.parse(path)
    root = tree.getroot()
    states: List[Dict[str, Any]] = []
    for game in root.findall("Game"):
        attrs = dict(game.attrib)
        start = attrs.get("StartTime") or ""
        end = attrs.get("EndTime") or ""
        hero = attrs.get("Hero")
        # 隐私：Player 是账号 id，绝不出现在语料里；只用于派生匿名 id
        player_raw = attrs.get("Player") or ""
        anon = hashlib.sha256(f"{player_raw}|{start}".encode("utf-8")).hexdigest()[:12]
        trace_id = f"xml_{anon}"
        final_board = game.find("FinalBoard")
        minions = []
        if final_board is not None:
            for slot, element in enumerate(final_board.findall("Minion")):
                minions.append(
                    _minion_from_xml(
                        element, slot=slot, index=index, tags_map=tags_map
                    )
                )
        board_hidden: List[str] = []
        for slot, minion in enumerate(minions):
            if minion["hidden_fields"]:
                board_hidden.append(f"player.minion[{slot}]")
        deity_relevant = _deity_relevant(
            [m.get("card_id") for m in minions], index
        )
        context_reasons = [
            "opponent_hidden: BgsLastGames only stores local player's final board",
            "hero_health_armor_tier_not_in_final_board",
            "hero_power_not_in_final_board",
            "trinkets_not_in_final_board",
            "anomaly_not_in_final_board",
            "quest_not_in_final_board",
        ]
        if deity_relevant:
            context_reasons.append("deity_not_in_final_board")
        state = {
            "schema": SCHEMA_STATE,
            "state_id": _state_id(SOURCE_XML, anon, trace_id),
            "trace_id": trace_id,
            "episode_id": f"ep_{anon}",
            "source": SOURCE_XML,
            "combat_index": None,
            "turn": None,
            "boundary": "game_end_final_board",
            "official_result": None,
            "final_placement": _int_or_none(attrs.get("Placemenent")),
            "player": {
                "side": "player",
                "hero_card_id": hero,
                "hero_name": None,
                "hero_power_id": None,
                "hero_power_used": None,
                "hero_power_data": None,
                "second_hero_power_id": None,
                "health": None,
                "armor": None,
                "tier": None,
                "tier_source": None,
                "minions": minions,
                "hand": [],
                "detected": [],
                "unsupported": [],
                "trace_missing_fields": [],
                "hidden_fields": [
                    "hero_health",
                    "hero_armor",
                    "tavern_tier",
                    "hero_power_id",
                    "hero_power_used",
                    "trinkets",
                    "anomaly",
                    "quest",
                ] + (["deity"] if deity_relevant else []),
                "hidden_reasons": [
                    "final_board_only_no_hero_state",
                    "trinkets_not_in_final_board",
                    "anomaly_not_in_final_board",
                    "quest_not_in_final_board",
                ] + (["deity_not_in_final_board"] if deity_relevant else []),
                **{name: None for name in DEITY_FIELDS},
                "deity_hidden": bool(deity_relevant),
                "deity_source": None if deity_relevant else "not_applicable",
                "deity_hidden_reason": (
                    "deity_not_in_final_board" if deity_relevant else None
                ),
                "deity_missing_fields": list(DEITY_FIELDS),
            },
            "opponent": None,
            "visibility": {"player": "observed_final_board", "opponent": "hidden"},
            "hidden_state": True,
            "hidden_reasons": sorted(
                ["opponent_warband_hidden"] + board_hidden
            ),
            "hidden_context": True,
            "hidden_context_reasons": context_reasons,
            "context": {
                "game_start": start,
                "game_end": end,
                "rating": _int_or_none(attrs.get("Rating")),
                "rating_after": _int_or_none(attrs.get("RatingAfter")),
                "friendly_game": str(attrs.get("FriendlyGame", "")).lower() == "true",
                "duos": str(attrs.get("Duos", "")).lower() == "true",
                "note": "HDT BgsLastGames 历史终局战团（本机导出 2026-10-18；对局时间见 game_start）",
            },
        }
        states.append(state)
    return states


def _int_or_none(text: Any) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════
# Schema
# ══════════════════════════════════════════════════════════════════════


def build_schema() -> Dict[str, Any]:
    """返回语料 schema（JSON Schema 风格，附来源/hidden 语义说明）。"""
    nullable_int = {"type": ["integer", "null"]}
    nullable_str = {"type": ["string", "null"]}
    keyword_flags = {
        "type": "object",
        "properties": {k: {"type": "boolean"} for k in KNOWN_KEYWORDS},
        "additionalProperties": False,
    }
    minion = {
        "type": "object",
        "required": ["slot", "zone_position", "card_id", "atk", "health",
                     "golden", "keywords", "hidden_fields"],
        "properties": {
            "slot": {"type": "integer", "minimum": 0, "description": "0 起站位（战斗边界顺序）"},
            "zone_position": {"type": "integer", "minimum": 0, "description": "ZONE_POSITION（HDT 快照顺序或 XML tag=263）"},
            "zone_position_source": {"type": "string"},
            "side": {"enum": ["player", "opponent"]},
            "card_id": nullable_str,
            "name": nullable_str,
            "atk": nullable_int,
            "health": nullable_int,
            "max_health": nullable_int,
            "damage": nullable_int,
            "golden": {"type": ["boolean", "null"]},
            "golden_source": nullable_str,
            "tier": nullable_int,
            "tier_source": nullable_str,
            "races": {"type": "array", "items": {"type": "string"}},
            "races_source": nullable_str,
            "keywords": {"type": "array", "items": {"enum": list(KNOWN_KEYWORDS)}},
            "keyword_flags": keyword_flags,
            "keyword_source": nullable_str,
            "card_keywords_static": {"type": "array", "items": {"type": "string"}},
            "script_data_num_1": nullable_int,
            "script_data_num_2": nullable_int,
            "script_data_num_3": nullable_int,
            "script_data_num_4": nullable_int,
            "script_data_num_5": nullable_int,
            "script_data_num_6": nullable_int,
            "script_data_source": nullable_str,
            "enchantment_derived": {"type": ["object", "null"]},
            "raw_tags": {"type": "object"},
            "unmapped_tag_ids": {"type": "array", "items": {"type": "integer"}},
            "annotations": {"type": "array", "items": {"type": "string"}},
            "card_found": {"type": "boolean"},
            "hidden_fields": {"type": "array", "items": {"type": "string"},
                              "description": "该随从缺失的观测字段；空数组=完整"},
            "derived_fields": {"type": "object",
                               "description": "由卡面静态身份补的字段（不是状态）"},
        },
    }
    warband = {
        "type": "object",
        "required": ["side", "hero_card_id", "hero_power_id", "health",
                     "armor", "tier", "minions", "hidden_fields"],
        "properties": {
            "side": {"enum": ["player", "opponent"]},
            "hero_card_id": nullable_str,
            "hero_name": nullable_str,
            "hero_power_id": nullable_str,
            "hero_power_used": {"type": ["boolean", "null"]},
            "hero_power_data": nullable_int,
            "second_hero_power_id": nullable_str,
            "health": nullable_int,
            "armor": nullable_int,
            "tier": nullable_int,
            "tier_source": nullable_str,
            "minions": {"type": "array", "items": {"$ref": "#/definitions/minion"}},
            "hand": {"type": "array", "items": {"$ref": "#/definitions/minion"}},
            "detected": {"type": "array", "items": {"type": "object"}},
            "unsupported": {"type": "array", "items": {"type": "object"}},
            "trace_missing_fields": {"type": "array", "items": {"type": "string"}},
            "hidden_fields": {"type": "array", "items": {"type": "string"}},
            "hidden_reasons": {"type": "array", "items": {"type": "string"}},
            "deity_card_id": nullable_str,
            "deity_atk": nullable_int,
            "deity_health": nullable_int,
            "deity_progress": nullable_int,
            "deity_awakened": {"type": ["boolean", "null"]},
            "deity_sigil_card_id": nullable_str,
            "deity_hidden": {"type": "boolean",
                             "description": "Deity 核心状态未观测（不要猜；oracle 标 unsupported:deity）"},
            "deity_source": nullable_str,
            "deity_hidden_reason": nullable_str,
            "deity_missing_fields": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": SCHEMA_STATE,
        "description": "真实对局战斗边界状态对（双方战团 + 隐藏字段标注）；"
                       "atk/health/golden/keywords/script 全部来自真实日志/trace，"
                       "tier/races/name 若由卡面补全会标 *_source=carddb。",
        "type": "object",
        "required": ["schema", "state_id", "trace_id", "source",
                     "player", "opponent", "visibility", "hidden_state",
                     "hidden_reasons"],
        "properties": {
            "schema": {"const": SCHEMA_STATE},
            "state_id": {"type": "string"},
            "trace_id": {"type": "string"},
            "episode_id": {"type": "string"},
            "source": {"enum": [SOURCE_POWERLOG, SOURCE_HDT, SOURCE_XML]},
            "combat_index": nullable_int,
            "turn": nullable_int,
            "boundary": {"enum": ["combat_start", "game_end_final_board"]},
            "official_result": {"type": ["string", "null"]},
            "official_lethal": {"type": ["string", "null"]},
            "final_placement": nullable_int,
            "player": {"$ref": "#/definitions/warband"},
            "opponent": {"anyOf": [{"$ref": "#/definitions/warband"}, {"type": "null"}]},
            "visibility": {
                "type": "object",
                "properties": {
                    "player": {"type": "string"},
                    "opponent": {"enum": ["observed", "hidden"]},
                },
            },
            "hidden_state": {"type": "boolean",
                             "description": "板面级状态不完整（对手缺失/随从缺身份或数值）"},
            "hidden_reasons": {"type": "array", "items": {"type": "string"}},
            "hidden_context": {"type": "boolean",
                               "description": "英雄/技能/饰品/异变等上下文不完整"},
            "hidden_context_reasons": {"type": "array", "items": {"type": "string"}},
            "context": {"type": "object"},
        },
        "definitions": {"minion": minion, "warband": warband},
    }


# ══════════════════════════════════════════════════════════════════════
# 导出 / 汇总 / 校验
# ══════════════════════════════════════════════════════════════════════


def _state_sort_key(state: Mapping[str, Any]) -> Tuple[int, str, int]:
    order = {SOURCE_POWERLOG: 0, SOURCE_HDT: 1, SOURCE_XML: 2}
    return (
        order.get(str(state.get("source")), 9),
        str(state.get("trace_id") or ""),
        int(state.get("combat_index") or 0),
    )


def collect_states(
    *,
    powerlog_dirs: Optional[Sequence[Path | str]] = None,
    hdt_dir: Optional[Path | str] = None,
    xml_path: Optional[Path | str] = None,
    data_dir: Optional[Path | str] = None,
    include_xml: bool = True,
    stats: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """从所有输入产物收集状态对（不写文件；按 ``(source, trace_id)`` 去重）。

    `runs/official_traces_powerlog{,2,3}/` 是不同时间分批抽的，目录间可能有
    同一条 trace 被重复保存（实测 2 条）；这里按 trace_id 去重，重复数记到
    ``stats["duplicates"]``。
    """
    index = load_card_index(data_dir)
    tags_map = load_tag_maps()
    states: List[Dict[str, Any]] = []
    seen: set = set()
    counters = stats if stats is not None else {}
    counters.setdefault("loaded", 0)
    counters.setdefault("duplicates", 0)
    counters.setdefault("by_source", {})

    def add(state: Dict[str, Any]) -> None:
        counters["loaded"] += 1
        key = (str(state.get("source")), str(state.get("trace_id")))
        if key in seen:
            counters["duplicates"] += 1
            return
        seen.add(key)
        counters["by_source"][key[0]] = counters["by_source"].get(key[0], 0) + 1
        states.append(state)

    for directory in powerlog_dirs or DEFAULT_POWERLOG_DIRS:
        directory = Path(directory)
        raw_log = _raw_log_for_trace_dir(directory)
        deity_index: Mapping[int, Mapping[str, Any]] = {}
        if raw_log is not None:
            counters["deity_powerlog"] = counters.get("deity_powerlog", 0) + 1
            deity_index = build_deity_index(raw_log, index=index)
        for path in iter_trace_paths(directory):
            trace = load_trace(path)
            combat = deity_index.get(int(trace.combat_index or 0))
            sides = _map_trace_sides_to_players(trace, combat) if combat else {}
            add(state_from_trace(
                trace, index=index, tags_map=tags_map,
                deity_combat=combat, deity_sides=sides,
            ))
    hdt_path = Path(hdt_dir or DEFAULT_HDT_DIR)
    if hdt_path.is_dir():
        for path in iter_trace_paths(hdt_path):
            trace = load_trace(path)
            add(state_from_trace(
                trace, index=index, tags_map=tags_map, deity_combat=None,
            ))
    if include_xml and Path(xml_path or DEFAULT_XML).is_file():
        for state in states_from_xml(xml_path, index=index, tags_map=tags_map):
            add(state)
    states.sort(key=_state_sort_key)
    return states


def _percentiles(values: Sequence[int]) -> Dict[str, Optional[int]]:
    clean = sorted(int(v) for v in values if isinstance(v, int))
    if not clean:
        return {"min": None, "p10": None, "p25": None, "p50": None,
                "p75": None, "p90": None, "p99": None, "max": None, "count": 0}

    def pct(p: float) -> int:
        index = min(len(clean) - 1, max(0, round((len(clean) - 1) * p)))
        return clean[index]

    return {
        "min": clean[0], "p10": pct(0.10), "p25": pct(0.25), "p50": pct(0.50),
        "p75": pct(0.75), "p90": pct(0.90), "p99": pct(0.99),
        "max": clean[-1], "count": len(clean),
    }


def summarize_states(
    states: Sequence[Mapping[str, Any]],
    *,
    card_index: Optional[Mapping[str, Any]] = None,
    tag_maps: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """覆盖率/分布摘要（供 index.json 与 report 使用）。"""
    by_source: Dict[str, int] = {}
    hidden_state = 0
    hidden_context = 0
    minion_count = 0
    minion_hidden = 0
    unique_cards: set = set()
    missing_cards: set = set()
    keyword_counts: Dict[str, int] = {}
    keyword_combos: Dict[str, int] = {}
    atk_values: List[int] = []
    health_values: List[int] = []
    script_counts = {f"script_data_num_{i}": 0 for i in range(1, 7)}
    enchantment_minions = 0
    xml_unmapped: Dict[int, int] = {}
    sources_meta: Dict[str, Dict[str, Any]] = {}
    placements: List[int] = []
    results: Dict[str, int] = {}
    hidden_context_reason_counts: Dict[str, int] = {}
    side_hidden_field_counts: Dict[str, int] = {}
    minion_hidden_field_counts: Dict[str, int] = {}
    deity_states = 0
    deity_states_both = 0
    deity_side_states = {"player": 0, "opponent": 0}
    deity_hidden_side_states = {"player": 0, "opponent": 0}
    deity_not_applicable_side_states = {"player": 0, "opponent": 0}
    deity_field_counts = {name: 0 for name in DEITY_FIELDS}
    deity_card_counts: Dict[str, int] = {}
    deity_source_counts: Dict[str, int] = {}
    deity_hidden_reason_counts: Dict[str, int] = {}
    deity_source_states: Dict[str, int] = {}
    deity_awakened_true = 0
    deity_progress_nonzero = 0
    for state in states:
        source = str(state.get("source"))
        by_source[source] = by_source.get(source, 0) + 1
        sources_meta.setdefault(source, {"states": 0, "boundary": set()})
        sources_meta[source]["states"] += 1
        sources_meta[source]["boundary"].add(str(state.get("boundary")))
        if state.get("hidden_state"):
            hidden_state += 1
        if state.get("hidden_context"):
            hidden_context += 1
        for reason in state.get("hidden_context_reasons") or []:
            hidden_context_reason_counts[str(reason)] = (
                hidden_context_reason_counts.get(str(reason), 0) + 1
            )
        result = state.get("official_result")
        if result:
            results[str(result)] = results.get(str(result), 0) + 1
        placement = state.get("final_placement")
        if isinstance(placement, int):
            placements.append(placement)
        sides_with_deity = 0
        for side_name in ("player", "opponent"):
            band = state.get(side_name)
            if not isinstance(band, Mapping):
                continue
            if not band.get("deity_hidden"):
                if band.get("deity_card_id") is not None:
                    deity_side_states[side_name] += 1
                    sides_with_deity += 1
                    card_id = band.get("deity_card_id")
                    deity_card_counts[str(card_id)] = (
                        deity_card_counts.get(str(card_id), 0) + 1
                    )
                    source_name = str(band.get("deity_source") or "unknown")
                    deity_source_counts[source_name] = (
                        deity_source_counts.get(source_name, 0) + 1
                    )
                    for name in DEITY_FIELDS:
                        if band.get(name) is not None:
                            deity_field_counts[name] += 1
                    if band.get("deity_awakened"):
                        deity_awakened_true += 1
                    progress = band.get("deity_progress")
                    if isinstance(progress, int) and progress:
                        deity_progress_nonzero += 1
                else:
                    deity_not_applicable_side_states[side_name] += 1
            else:
                deity_hidden_side_states[side_name] += 1
                reason = band.get("deity_hidden_reason")
                if reason:
                    deity_hidden_reason_counts[str(reason)] = (
                        deity_hidden_reason_counts.get(str(reason), 0) + 1
                    )
            for field_name in band.get("hidden_fields") or []:
                key = f"{side_name}.{field_name}"
                side_hidden_field_counts[key] = (
                    side_hidden_field_counts.get(key, 0) + 1
                )
            for minion in band.get("minions") or []:
                if not isinstance(minion, Mapping):
                    continue
                minion_count += 1
                if minion.get("hidden_fields"):
                    minion_hidden += 1
                for field_name in minion.get("hidden_fields") or []:
                    key = f"minion.{field_name}"
                    minion_hidden_field_counts[key] = (
                        minion_hidden_field_counts.get(key, 0) + 1
                    )
                card_id = minion.get("card_id")
                if card_id:
                    unique_cards.add(str(card_id))
                    if not minion.get("card_found"):
                        missing_cards.add(str(card_id))
                if isinstance(minion.get("atk"), int):
                    atk_values.append(minion["atk"])
                if isinstance(minion.get("health"), int):
                    health_values.append(minion["health"])
                keywords = [str(k) for k in (minion.get("keywords") or [])]
                for keyword in keywords:
                    keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
                combo = "|".join(sorted(keywords))
                keyword_combos[combo] = keyword_combos.get(combo, 0) + 1
                for key in script_counts:
                    if isinstance(minion.get(key), int):
                        script_counts[key] += 1
                if minion.get("enchantment_derived"):
                    enchantment_minions += 1
                for tag_id in minion.get("unmapped_tag_ids") or []:
                    xml_unmapped[int(tag_id)] = xml_unmapped.get(int(tag_id), 0) + 1
        if sides_with_deity:
            deity_states += 1
            deity_source_states[source] = deity_source_states.get(source, 0) + 1
        if sides_with_deity == 2:
            deity_states_both += 1
    pool = set(card_index.get("pool_minions") or set()) if card_index else set()
    report_sources = {}
    for source, meta in sources_meta.items():
        report_sources[source] = {
            "states": meta["states"],
            "boundaries": sorted(meta["boundary"]),
            "hidden_state_states": sum(
                1 for s in states
                if s.get("source") == source and s.get("hidden_state")
            ),
            "hidden_context_states": sum(
                1 for s in states
                if s.get("source") == source and s.get("hidden_context")
            ),
            "deity_states": deity_source_states.get(source, 0),
        }
    return {
        "schema": SCHEMA_CORPUS,
        "states": len(states),
        "minions": minion_count,
        "minions_with_hidden_fields": minion_hidden,
        "states_hidden_state": hidden_state,
        "states_hidden_context": hidden_context,
        "hidden_state_ratio": round(hidden_state / len(states), 4) if states else 0.0,
        "hidden_context_ratio": round(hidden_context / len(states), 4) if states else 0.0,
        "deity": {
            "states_with_any_deity": deity_states,
            "states_with_both_sides": deity_states_both,
            "state_ratio": round(deity_states / len(states), 4) if states else 0.0,
            "side_states": dict(deity_side_states),
            "side_hidden_states": dict(deity_hidden_side_states),
            "side_not_applicable_states": dict(deity_not_applicable_side_states),
            "field_present_counts": dict(deity_field_counts),
            "field_coverage": {
                name: round(count / (len(states) * 2), 4)
                for name, count in deity_field_counts.items()
            },
            "card_id_counts": dict(sorted(deity_card_counts.items())),
            "source_counts": dict(sorted(deity_source_counts.items())),
            "source_states": dict(sorted(deity_source_states.items())),
            "hidden_reason_counts": dict(sorted(deity_hidden_reason_counts.items())),
            "awakened_true": deity_awakened_true,
            "progress_nonzero": deity_progress_nonzero,
            "tag_mapping": {
                "deity_card_id": "BG_OldGod.BACON_EVOLUTION_CARD_ID/TAG_SCRIPT_DATA_NUM_6 (dbf→BGFYM_000/011) 或 BGFYM token card id",
                "deity_atk": "BG_OldGod.TAG_SCRIPT_DATA_NUM_2；本地 BGFYM token owner 优先 BACON_OLD_GOD_ATTACK",
                "deity_health": "BG_OldGod.TAG_SCRIPT_DATA_NUM_3；本地 BGFYM token owner 优先 BACON_OLD_GOD_HEALTH",
                "deity_progress": "战斗开始按卡面 each combat 重置为 0（objective QUEST_PROGRESS 为战斗内进度）",
                "deity_awakened": "战斗开始为 False（awaken 在战斗内发生）",
                "deity_sigil_card_id": "BG_OldGod.BACON_DEITY_SIGIL=1 → \"BG_OldGod\"",
            },
        },
        "hidden_context_reason_counts": dict(
            sorted(hidden_context_reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "side_hidden_field_counts": dict(
            sorted(side_hidden_field_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "minion_hidden_field_counts": dict(
            sorted(minion_hidden_field_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "by_source": report_sources,
        "unique_cards": len(unique_cards),
        "unique_cards_sample": sorted(unique_cards)[:30],
        "pool_minions_covered": len(unique_cards & pool),
        "pool_minions_total": len(pool),
        "pool_minions_uncovered": sorted(pool - unique_cards),
        "cards_not_in_current_data": sorted(missing_cards),
        "keyword_counts": dict(sorted(keyword_counts.items())),
        "top_keyword_combos": sorted(
            keyword_combos.items(), key=lambda kv: (-kv[1], kv[0])
        )[:12],
        "script_data_coverage": script_counts,
        "minions_with_enchantment_derived": enchantment_minions,
        "atk_percentiles": _percentiles(atk_values),
        "health_percentiles": _percentiles(health_values),
        "official_results": results,
        "placement_counts": (
            {str(p): placements.count(p) for p in sorted(set(placements))}
            if placements else {}
        ),
        "xml_unmapped_tag_ids": dict(
            sorted(xml_unmapped.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    }


def validate_samples(
    states: Sequence[Mapping[str, Any]],
    *,
    powerlog_dirs: Optional[Sequence[Path | str]] = None,
    hdt_dir: Optional[Path | str] = None,
    xml_path: Optional[Path | str] = None,
    sample: int = 20,
) -> Dict[str, Any]:
    """抽样把语料记录与原始 trace/XML 对比（字段级一致性）。"""
    traces: Dict[str, OfficialCombatTrace] = {}
    for directory in list(powerlog_dirs or DEFAULT_POWERLOG_DIRS) + [
        hdt_dir or DEFAULT_HDT_DIR
    ]:
        path = Path(directory)
        if not path.is_dir():
            continue
        for trace_path in iter_trace_paths(path):
            trace = load_trace(trace_path)
            traces[trace.trace_id] = trace
    xml_states = {
        state["trace_id"]: state
        for state in states_from_xml(
            xml_path,
            index=load_card_index(),
            tags_map=load_tag_maps(),
        )
    } if Path(xml_path or DEFAULT_XML).is_file() else {}
    candidates = [s for s in states if s.get("source") in (SOURCE_POWERLOG, SOURCE_HDT)
                  and s.get("trace_id") in traces]
    xml_candidates = [s for s in states if s.get("source") == SOURCE_XML]
    checked = 0
    failures: List[Dict[str, Any]] = []

    def pick(items: Sequence[Mapping[str, Any]], count: int) -> List[Mapping[str, Any]]:
        if not items:
            return []
        if len(items) <= count:
            return list(items)
        step = max(1, len(items) // count)
        return list(items[::step])[:count]

    for state in pick(candidates, max(0, sample)):
        trace = traces[state["trace_id"]]
        checked += 1
        for side in ("player", "opponent"):
            expected = trace.player if side == "player" else trace.opponent
            actual = state[side]
            problems = []
            if len(actual.get("minions") or []) != len(expected.minions):
                problems.append(f"{side}.minion_count")
            for index, (want, got) in enumerate(zip(expected.minions, actual["minions"])):
                for field_name in ("card_id", "atk", "health"):
                    if want.__dict__.get(field_name) != got.get(field_name):
                        problems.append(f"{side}.minion[{index}].{field_name}")
                if bool(want.golden) != bool(got.get("golden")):
                    problems.append(f"{side}.minion[{index}].golden")
                if list(want.keywords or []) != list(got.get("keywords") or []):
                    problems.append(f"{side}.minion[{index}].keywords")
            if problems:
                failures.append({"trace_id": state["trace_id"], "problems": problems})
    for state in pick(xml_candidates, max(0, sample // 2)):
        expected = xml_states.get(state["trace_id"])
        if expected is None:
            failures.append({"trace_id": state["trace_id"], "problems": ["xml_missing"]})
            continue
        checked += 1
        if len(expected["player"]["minions"]) != len(state["player"]["minions"]):
            failures.append(
                {"trace_id": state["trace_id"], "problems": ["xml.minion_count"]}
            )
    return {"checked": checked, "passed": checked - len(failures), "failures": failures}


def export_state_corpus(
    *,
    out_dir: Optional[Path | str] = None,
    report_path: Optional[Path | str] = None,
    powerlog_dirs: Optional[Sequence[Path | str]] = None,
    hdt_dir: Optional[Path | str] = None,
    xml_path: Optional[Path | str] = None,
    data_dir: Optional[Path | str] = None,
    include_xml: bool = True,
    validate_sample: int = 20,
) -> Dict[str, Any]:
    """导出 ``states.jsonl`` + ``schema.json`` + ``index.json`` + 覆盖率报告。"""
    target = Path(out_dir or DEFAULT_OUT_DIR)
    target.mkdir(parents=True, exist_ok=True)
    collect_stats: Dict[str, Any] = {}
    states = collect_states(
        powerlog_dirs=powerlog_dirs,
        hdt_dir=hdt_dir,
        xml_path=xml_path,
        data_dir=data_dir,
        include_xml=include_xml,
        stats=collect_stats,
    )
    index = load_card_index(data_dir)
    tags_map = load_tag_maps()
    states_path = target / "states.jsonl"
    with states_path.open("w", encoding="utf-8", newline="\n") as handle:
        for state in states:
            handle.write(json.dumps(state, ensure_ascii=False) + "\n")
    schema_path = target / "schema.json"
    schema_path.write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    summary = summarize_states(states, card_index=index, tag_maps=tags_map)
    validation = validate_samples(
        states,
        powerlog_dirs=powerlog_dirs,
        hdt_dir=hdt_dir,
        xml_path=xml_path if include_xml else None,
        sample=validate_sample,
    )
    validation_summary = {
        "checked": validation["checked"],
        "passed": validation["passed"],
        "failures": len(validation["failures"]),
        "failure_samples": validation["failures"][:10],
    }
    corpus_index = {
        "schema": SCHEMA_CORPUS,
        "generated_at_utc": _now_utc(),
        "out_dir": str(target),
        "states_file": str(states_path),
        "schema_file": str(schema_path),
        "states_sha256": _sha256(states_path),
        "data_patch": index.get("patch"),
        "dedupe": {
            "loaded": collect_stats.get("loaded"),
            "duplicates_removed": collect_stats.get("duplicates"),
            "by_source": collect_stats.get("by_source"),
            "note": "runs/official_traces_powerlog{,2,3}/ 目录间有重复 trace，"
                    "已按 (source, trace_id) 去重",
        },
        "inputs": {
            "powerlog_dirs": [str(p) for p in (powerlog_dirs or DEFAULT_POWERLOG_DIRS)],
            "hdt_dir": str(hdt_dir or DEFAULT_HDT_DIR),
            "xml": str(xml_path or DEFAULT_XML) if include_xml else None,
        },
        "summary": summary,
        "validation": validation_summary,
    }
    index_path = target / "index.json"
    index_path.write_text(
        json.dumps(corpus_index, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    report = Path(report_path or DEFAULT_REPORT)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        render_report(corpus_index, summary, validation_summary), encoding="utf-8"
    )
    return corpus_index


def _now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def render_report(
    index: Mapping[str, Any],
    summary: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> str:
    lines: List[str] = []
    add = lines.append
    add("# 真实战斗边界状态语料报告（state_corpus）")
    add("")
    add("> 自动生成，勿手改。生成命令：")
    add("> `python -m hsbg.bridge.state_corpus export`")
    add("")
    add(f"- 生成时间（UTC）: {index.get('generated_at_utc')}")
    add(f"- 数据基线 patch: `{index.get('data_patch')}`")
    add(f"- states: `{index.get('states_file')}`（sha256 `{str(index.get('states_sha256'))[:16]}…`）")
    add(f"- schema: `{index.get('schema_file')}`")
    add("")
    add("## 1. 规模")
    add("")
    add("| 指标 | 值 |")
    add("|------|----|")
    for key in (
        "states",
        "minions",
        "minions_with_hidden_fields",
        "states_hidden_state",
        "hidden_state_ratio",
        "states_hidden_context",
        "hidden_context_ratio",
        "unique_cards",
        "pool_minions_covered",
        "pool_minions_total",
    ):
        add(f"| `{key}` | {summary.get(key)} |")
    dedupe = index.get("dedupe") or {}
    if dedupe:
        add(
            f"\n- 输入加载 {dedupe.get('loaded')} 条，按 `(source, trace_id)` 去重 "
            f"**{dedupe.get('duplicates_removed')}** 条（powerlog 分批目录间有重复）。"
        )
    add("")
    add("## 2. 来源构成")
    add("")
    add("| source | states | boundaries | hidden_state | hidden_context |")
    add("|--------|-------:|------------|-------------:|---------------:|")
    for source, row in sorted((summary.get("by_source") or {}).items()):
        add(
            f"| `{source}` | {row.get('states')} | {', '.join(row.get('boundaries') or [])} "
            f"| {row.get('hidden_state_states')} | {row.get('hidden_context_states')} |"
        )
    add("")
    add("## 3. 可见 / 隐藏比例")
    add("")
    states = summary.get("states") or 0
    hidden_state = summary.get("states_hidden_state") or 0
    hidden_context = summary.get("states_hidden_context") or 0
    add(
        f"- 板面级 `hidden_state`（对手缺失/随从缺身份或数值）："
        f"**{hidden_state}/{states} = {summary.get('hidden_state_ratio')}**"
    )
    add(
        f"- 上下文级 `hidden_context`（英雄血量/技能/饰品/异变等缺失）："
        f"**{hidden_context}/{states} = {summary.get('hidden_context_ratio')}**"
    )
    add("- 说明：Power.log/HDT 的双方战团 minion 状态是**真实观测**；"
        "HDT 缺英雄血量/等级、XML 缺对手，均显式写 hidden，未用卡面替代。")
    reason_counts = summary.get("hidden_context_reason_counts") or {}
    if reason_counts:
        add("")
        add("### 上下文缺失原因（出现状态数）")
        add("")
        add("| reason | states |")
        add("|--------|-------:|")
        for reason, count in reason_counts.items():
            add(f"| `{reason}` | {count} |")
    side_hidden = summary.get("side_hidden_field_counts") or {}
    if side_hidden:
        add("")
        add("### 侧级缺失字段（出现次数）")
        add("")
        add("| 字段 | 次数 |")
        add("|------|-----:|")
        for field_name, count in list(side_hidden.items())[:20]:
            add(f"| `{field_name}` | {count} |")
    add("")
    add("## 4. 覆盖卡集合 / 池覆盖")
    add("")
    add(f"- 唯一 card_id: **{summary.get('unique_cards')}**")
    add(
        f"- 命中当前池内随从: **{summary.get('pool_minions_covered')}"
        f"/{summary.get('pool_minions_total')}**"
    )
    uncovered_pool = summary.get("pool_minions_uncovered") or []
    if uncovered_pool:
        add(f"- 本语料**未覆盖**的当前池内随从: {len(uncovered_pool)} 个"
            + (f"（前 30：`{', '.join(uncovered_pool[:30])}`）" if uncovered_pool else ""))
    missing = summary.get("cards_not_in_current_data") or []
    add(f"- 当前 `data/` 中找不到的 card_id: {len(missing)} 个"
        + (f"：`{', '.join(missing[:20])}`" if missing else ""))
    add("")
    add("## 5. 关键词分布")
    add("")
    add("| keyword | minion 次数 |")
    add("|---------|------------:|")
    for keyword, count in (summary.get("keyword_counts") or {}).items():
        add(f"| `{keyword}` | {count} |")
    add("")
    add("### Top 关键词组合")
    add("")
    add("| 组合 | 次数 |")
    add("|------|-----:|")
    for combo, count in (summary.get("top_keyword_combos") or []):
        add(f"| `{combo or '(none)'}` | {count} |")
    add("")
    add("## 6. 数值分位（真实状态，非卡面）")
    add("")
    add("| 指标 | min | p10 | p25 | p50 | p75 | p90 | p99 | max | n |")
    add("|------|----:|----:|----:|----:|----:|----:|----:|----:|--:|")
    for label, key in (("atk", "atk_percentiles"), ("health", "health_percentiles")):
        row = summary.get(key) or {}
        add(
            f"| {label} | {row.get('min')} | {row.get('p10')} | {row.get('p25')} "
            f"| {row.get('p50')} | {row.get('p75')} | {row.get('p90')} "
            f"| {row.get('p99')} | {row.get('max')} | {row.get('count')} |"
        )
    add("")
    add("## 7. ScriptData / 附魔派生")
    add("")
    add("| 字段 | 有值 minion 数 |")
    add("|------|--------------:|")
    for key, count in (summary.get("script_data_coverage") or {}).items():
        add(f"| `{key}` | {count} |")
    add(
        f"| `enchantment_derived` | {summary.get('minions_with_enchantment_derived')} |"
    )
    add("")
    add("## 8. Deity（旧神）覆盖")
    add("")
    deity = summary.get("deity") or {}
    add(
        f"- 含至少一侧 Deity 观测的状态: **{deity.get('states_with_any_deity')}"
        f"/{states} = {deity.get('state_ratio')}**；双方都有: "
        f"**{deity.get('states_with_both_sides')}**"
    )
    side_states = deity.get("side_states") or {}
    side_hidden_states = deity.get("side_hidden_states") or {}
    side_na = deity.get("side_not_applicable_states") or {}
    add(
        f"- 侧级观测/隐藏/无 Deity 信号: player {side_states.get('player', 0)}"
        f"/{side_hidden_states.get('player', 0)}/{side_na.get('player', 0)}，"
        f"opponent {side_states.get('opponent', 0)}"
        f"/{side_hidden_states.get('opponent', 0)}/{side_na.get('opponent', 0)}"
    )
    source_states = deity.get("source_states") or {}
    if source_states:
        add("- 按来源: " + "，".join(
            f"`{source}` {count}" for source, count in sorted(source_states.items())
        ))
    source_counts = deity.get("source_counts") or {}
    if source_counts:
        add("- 字段来源计数: " + "，".join(
            f"`{source}` {count}" for source, count in sorted(source_counts.items())
        ))
    card_counts = deity.get("card_id_counts") or {}
    if card_counts:
        add("- Deity 卡 id: " + "，".join(
            f"`{card}` {count}" for card, count in sorted(card_counts.items())
        ))
    add("")
    add("| 字段 | 有值侧数 | 侧覆盖率 |")
    add("|------|--------:|---------:|")
    field_counts = deity.get("field_present_counts") or {}
    field_coverage = deity.get("field_coverage") or {}
    for name in DEITY_FIELDS:
        add(f"| `{name}` | {field_counts.get(name, 0)} | {field_coverage.get(name, 0)} |")
    add("")
    add("| Deity tag（Power.log） | 语义 |")
    add("|----------------------|------|")
    for key, value in (deity.get("tag_mapping") or {}).items():
        add(f"| `{key}` | {value} |")
    hidden_reasons = deity.get("hidden_reason_counts") or {}
    if hidden_reasons:
        add("")
        add("缺失原因（侧数）：" + "，".join(
            f"`{reason}` {count}" for reason, count in sorted(hidden_reasons.items())
        ))
    add("")
    add("> 只从真实 Power.log 抽；HDT/XML 源无 Deity 实体 → 六字段 null + "
        "`deity_hidden=true`（原因 `deity_not_in_source`），不猜。"
        "战斗开始 `deity_progress=0`、`deity_awakened=false`（卡面 each combat 重置）。")
    add("")
    add("## 9. 无法导出的字段及原因")
    add("")
    add("| 字段 | 原因 |")
    add("|------|------|")
    add("| 对手终局战团（XML 源） | `BgsLastGames.xml` 只保存本地玩家 `FinalBoard` |")
    add("| 英雄血量/护甲/酒馆等级（HDT 源） | BobsBuddy Simulation Input 不包含这些字段 |")
    add("| 技能使用状态（HDT/Power.log 部分） | trace schema 未保留 EXHAUSTED/激活信息 |")
    add("| 饰品 / 异变 / 任务实体 | `official_combat_trace.v1` 不含这些实体 |")
    add("| 完整附魔链 | 原始 trace/XML 只保留部分字段（HDT 的 Enchantments/Deathrattles、"
        "XML 的 CREATOR/COPIED_FROM_ENTITY_ID），没有完整 enchantment 实体图 |")
    add("| XML 无法映射的数值 tag | 旧 tag/客户端内部 tag 不在官方 255130 枚举中，"
        "保留为 `tag_<id>` 与 `unmapped_tag_ids` |")
    add("")
    unmapped = summary.get("xml_unmapped_tag_ids") or {}
    if unmapped:
        add("### XML 未映射 tag（top）")
        add("")
        add("| tag_id | 出现 minion 次数 |")
        add("|--------|-----------------:|")
        for tag_id, count in list(unmapped.items())[:20]:
            add(f"| `{tag_id}` | {count} |")
        add("")
    add("## 10. 抽样校验")
    add("")
    add(f"- 抽样条数: {validation.get('checked')}；通过: {validation.get('passed')}；"
        f"失败: {validation.get('failures')}")
    for failure in validation.get("failure_samples") or []:
        add(f"  - `{failure.get('trace_id')}`: {failure.get('problems')}")
    add("")
    add("## 11. 口径与限制")
    add("")
    add("- atk/health/golden/keywords/script_data 全部来自真实日志或 trace 快照；"
        "tier/races/name 若由 `data/bg_cards.json` 补全，字段旁标 `*_source=carddb`。")
    add("- 状态空间随对局历史变化：语料保留的是**该时间点真实状态**，"
        "不是基础卡面；使用时不要把 card 静态字段当作状态。")
    add("- HDT 结果的 `official_result` 来自官方结算（BobsBuddy Validate 日志）；"
        "`bb_rates` 仅为第二实现参照。")
    add("- XML 源的 45 局为 HDT 历史终局（2024 年对局，旧 build），"
        "card_id 有 2 个不在当前 37.0.0 数据中，已列入 §4；不得用其替代当前版本状态分布。")
    add("")
    add("## 12. 复现")
    add("")
    add("```powershell")
    add("python -m hsbg.bridge.state_corpus export")
    add("python -m hsbg.bridge.state_corpus validate")
    add("python -m pytest tests\\test_state_corpus.py -q")
    add("```")
    add("")
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="真实战斗边界状态语料导出/校验")
    sub = parser.add_subparsers(dest="command")
    p_export = sub.add_parser("export", help="导出 states.jsonl/schema.json/报告")
    p_export.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p_export.add_argument("--report", default=str(DEFAULT_REPORT))
    p_export.add_argument("--hdt-dir", default=str(DEFAULT_HDT_DIR))
    p_export.add_argument("--xml", default=str(DEFAULT_XML))
    p_export.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p_export.add_argument("--no-xml", action="store_true")
    p_export.add_argument("--validate-sample", type=int, default=20)

    p_validate = sub.add_parser("validate", help="重新抽样校验已导出的 states.jsonl")
    p_validate.add_argument("--corpus", default=str(DEFAULT_OUT_DIR / "states.jsonl"))
    p_validate.add_argument("--sample", type=int, default=20)

    args = parser.parse_args(argv)
    if args.command in (None, "export"):
        index = export_state_corpus(
            out_dir=args.out_dir if args.command else None,
            report_path=args.report if args.command else None,
            hdt_dir=args.hdt_dir if args.command else None,
            xml_path=args.xml if args.command else None,
            data_dir=args.data_dir if args.command else None,
            include_xml=not (args.no_xml if args.command else False),
            validate_sample=args.validate_sample if args.command else 20,
        )
        print(json.dumps(
            {
                "states": index["summary"]["states"],
                "minions": index["summary"]["minions"],
                "hidden_state_ratio": index["summary"]["hidden_state_ratio"],
                "hidden_context_ratio": index["summary"]["hidden_context_ratio"],
                "unique_cards": index["summary"]["unique_cards"],
                "validation": index["validation"],
                "states_file": index["states_file"],
                "report": str(DEFAULT_REPORT if not args.command else args.report),
            },
            ensure_ascii=False,
            indent=1,
        ))
        return 0
    if args.command == "validate":
        corpus_path = Path(args.corpus)
        states = [
            json.loads(line)
            for line in corpus_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        result = validate_samples(states, sample=args.sample)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
