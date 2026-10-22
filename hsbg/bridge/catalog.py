"""AgenticAssistant 公共卡牌目录（``catalog.json``）只读适配器 + 引擎数据差异统计。

数据来源
--------
``C:\\HSagent\\AgenticAssistant\\_internal\\bgassistant\\data\\catalog.json``
（AgenticAssistant 0.5.3 发行包，``game_version = 36.6.3.253932``）。

该目录只提供**公共卡牌元数据**：``id / dbf / kind / name / name_zh / tier /
races / keywords / normal / activatable / activation_cost``（73 条法术另有
``spellcraft_spell``），并附带 653 条英雄皮肤 → 本体英雄的映射。它**不含**
atk / health / cost / 文本 / 脚本参数——数值权威仍是 ``hsdata/CardDefs.xml``
与 ``data/*.json``。因此本模块的差异统计只能覆盖"卡是否存在 / 名称 / 酒馆
等级 / 种族 / 关键词"，不能量化攻击力/生命值改动。

设计原则
--------
* 只读、零第三方依赖、不导入引擎（可被离线工具与测试直接使用）。
* 文件缺失时抛 ``FileNotFoundError``（测试用 ``pytest.skip`` 处理）。
* 比较时对"金色版本"做规范化：catalog 用 ``normal`` 字段折叠 ``_G/_Gt``；
  引擎数据按同规则折叠，避免把金色变体误判成"新增卡"。
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ── 路径 ────────────────────────────────────────────────────────────────
#: 仓库根目录（hsbg/bridge/catalog.py -> parents[2]）
ROOT = Path(__file__).resolve().parents[2]
#: AgenticAssistant 卡牌目录
DEFAULT_CATALOG_PATH = (
    ROOT / "AgenticAssistant" / "_internal" / "bgassistant" / "data" / "catalog.json"
)
#: AgenticAssistant 附带的 GameTag / CardType / Race 枚举（python-hearthstone）
DEFAULT_GAME_TAGS_PATH = (
    ROOT / "AgenticAssistant" / "_internal" / "bgcontroller" / "data" / "game_tags.json"
)
#: 本项目引擎卡牌数据目录（S14 / patch 36.2.2 基线）
DEFAULT_ENGINE_DATA_DIR = ROOT / "data"
#: 差异统计默认落盘位置
DEFAULT_DIFF_OUT = ROOT / "runs" / "data_diff_36.6.3.json"
#: 环境变量覆盖 catalog 路径（便于在别的机器/快照上运行）
CATALOG_ENV_VAR = "HSBG_AGENTIC_CATALOG"

#: 参与"引擎侧"比较的数据文件。``bg_cards.json`` 已覆盖酒馆随从/法术/饰品/
#: 任务奖励/异变等全部 card_set=1453 卡牌；英雄与英雄技能单独成文件。
ENGINE_DATA_FILES: Tuple[str, ...] = (
    "bg_cards.json",
    "bg_heroes.json",
    "bg_hero_powers.json",
    "bg_dark_gifts.json",
    "bg_tavern_spells.json",
    "bg_quest_rewards.json",
    "bg_trinkets.json",
    "bg_anomalies.json",
)

#: catalog keyword 名 -> 引擎 ``data/bg_cards.json`` 里的布尔字段。
#: 只有明确可映射的关键词参与一致性统计；``TRIGGER_VISUAL`` 等大量内部 tag
#: 在引擎数据里没有等价字段，单独计入"未覆盖"。
KEYWORD_TO_ENGINE_FIELD: Dict[str, str] = {
    "DEATHRATTLE": "deathrattle",
    "BATTLECRY": "battlecry",
    "TAUNT": "taunt",
    "DIVINE_SHIELD": "divine_shield",
    "REBORN": "reborn",
    "WINDFURY": "windfury",
    "VENOMOUS": "venomous",
    "POISONOUS": "poisonous",
    "MAGNETIC": "magnetic",
    "CHOOSE_ONE": "choose_one",
    "AVENGE": "avenge",
    "BACON_RALLY": "rally",
    "START_OF_COMBAT": "start_of_combat",
}

#: game_tags.json 缺失时的种族兜底表（与 python-hearthstone enums.Race 一致）。
_RACE_FALLBACK: Dict[int, str] = {
    0: "INVALID", 1: "BLOODELF", 2: "DRAENEI", 3: "DWARF", 4: "GNOME",
    5: "GOBLIN", 6: "HUMAN", 7: "NIGHTELF", 8: "ORC", 9: "TAUREN",
    10: "TROLL", 11: "UNDEAD", 12: "WORGEN", 13: "GOBLIN2", 14: "MURLOC",
    15: "DEMON", 16: "SCOURGE", 17: "MECHANICAL", 18: "ELEMENTAL",
    19: "OGRE", 20: "BEAST", 21: "TOTEM", 22: "NERUBIAN", 23: "PIRATE",
    24: "DRAGON", 25: "BLANK", 26: "ALL", 38: "EGG", 43: "QUILBOAR",
    80: "CENTAUR", 81: "FURBOLG", 83: "HIGHELF", 84: "TREANT",
    85: "OWLKIN", 88: "HALFORC", 89: "LOCK", 92: "NAGA", 93: "OLDGOD",
    94: "PANDAREN", 95: "GRONN", 96: "CELESTIAL", 97: "GNOLL",
    98: "GOLEM", 99: "HARPY", 100: "VULPERA", 126: "ABERRATION",
}


# ══════════════════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CatalogCard:
    """catalog.json 中的一条卡牌记录（只读）。"""

    id: str
    dbf: int
    kind: str
    name: str
    name_zh: str
    tier: int
    races: Tuple[str, ...]
    keywords: Tuple[str, ...]
    #: 金色变体指向的本体 id；非金色为空串
    normal: str = ""
    activatable: bool = False
    activation_cost: int = 0
    spellcraft_spell: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_golden(self) -> bool:
        return bool(self.normal)

    @property
    def base_id(self) -> str:
        return self.normal or self.id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "dbf": self.dbf,
            "kind": self.kind,
            "name": self.name,
            "name_zh": self.name_zh,
            "tier": self.tier,
            "races": list(self.races),
            "keywords": list(self.keywords),
            "normal": self.normal,
            "activatable": self.activatable,
            "activation_cost": self.activation_cost,
            "spellcraft_spell": self.spellcraft_spell,
        }


class AACatalog:
    """AgenticAssistant ``catalog.json`` 的只读查询适配器。"""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        env_path = os.environ.get(CATALOG_ENV_VAR)
        self.path = Path(path or env_path or DEFAULT_CATALOG_PATH)
        if not self.path.is_file():
            raise FileNotFoundError(
                f"AgenticAssistant catalog.json 不存在: {self.path}"
                f"（可用环境变量 {CATALOG_ENV_VAR} 覆盖）"
            )
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("cards"), list):
            raise ValueError(f"catalog.json 结构异常: {self.path}")

        self.game_version: str = str(raw.get("game_version", ""))
        cards: List[CatalogCard] = []
        for row in raw["cards"]:
            if not isinstance(row, Mapping) or not row.get("id"):
                continue
            cards.append(
                CatalogCard(
                    id=str(row["id"]),
                    dbf=int(row.get("dbf") or 0),
                    kind=str(row.get("kind") or ""),
                    name=str(row.get("name") or ""),
                    name_zh=str(row.get("name_zh") or ""),
                    tier=int(row.get("tier") or 0),
                    races=tuple(str(r) for r in (row.get("races") or ())),
                    keywords=tuple(str(k) for k in (row.get("keywords") or ())),
                    normal=str(row.get("normal") or ""),
                    activatable=bool(row.get("activatable", False)),
                    activation_cost=int(row.get("activation_cost") or 0),
                    spellcraft_spell=bool(row.get("spellcraft_spell", False)),
                    raw=dict(row),
                )
            )
        self._cards: Tuple[CatalogCard, ...] = tuple(cards)
        self._by_id: Dict[str, CatalogCard] = {c.id: c for c in cards}
        self._by_dbf: Dict[int, CatalogCard] = {}
        for c in cards:
            if c.dbf:
                # 保留先出现的（通常是本体），金色变体 dbf 与本体重合
                self._by_dbf.setdefault(c.dbf, c)
        self._by_normal: Dict[str, CatalogCard] = {
            c.normal: c for c in cards if c.normal
        }
        self.skins: Dict[str, str] = {
            str(k): str(v) for k, v in (raw.get("skins") or {}).items()
        }
        self._canonical: Dict[str, CatalogCard] = {}
        for c in cards:
            key = c.base_id
            existing = self._canonical.get(key)
            # 同一本体优先保留"非金色"记录：金色变体的 atk/hp/cost 是金色数值，
            # 直接拿来和引擎基础卡比较会系统性偏大/翻倍。
            if existing is None or (existing.is_golden and not c.is_golden):
                self._canonical[key] = c
        self._by_kind: Dict[str, Tuple[CatalogCard, ...]] = {}
        kinds: Dict[str, List[CatalogCard]] = {}
        for c in cards:
            kinds.setdefault(c.kind, []).append(c)
        self._by_kind = {k: tuple(v) for k, v in kinds.items()}

    # ── 基本信息 ────────────────────────────────────────────────────
    @property
    def version(self) -> str:
        """线上规则/数据版本，如 ``36.6.3.253932``。"""
        return self.game_version

    @property
    def cards(self) -> Tuple[CatalogCard, ...]:
        return self._cards

    @property
    def card_count(self) -> int:
        return len(self._cards)

    @property
    def kinds(self) -> Tuple[str, ...]:
        return tuple(sorted(self._by_kind))

    def kind_counts(self) -> Dict[str, int]:
        return {k: len(v) for k, v in sorted(self._by_kind.items())}

    def summary(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "game_version": self.version,
            "card_count": self.card_count,
            "skin_count": len(self.skins),
            "kind_counts": self.kind_counts(),
            "golden_variant_count": sum(1 for c in self._cards if c.is_golden),
        }

    # ── 查询 ────────────────────────────────────────────────────────
    def get(self, card_id: str) -> Optional[CatalogCard]:
        """按精确 id 查询（含金色变体与 token）。"""
        return self._by_id.get(str(card_id))

    def from_dbf(self, dbf: int) -> Optional[CatalogCard]:
        return self._by_dbf.get(int(dbf))

    def by_kind(self, kind: str) -> Tuple[CatalogCard, ...]:
        return self._by_kind.get(str(kind), ())

    def search(self, text: str, limit: int = 20) -> List[CatalogCard]:
        needle = str(text).casefold()
        if not needle:
            return []
        hits = [
            c
            for c in self._cards
            if needle in c.name.casefold()
            or needle in c.name_zh
            or needle in c.id.casefold()
        ]
        return hits[: max(0, int(limit))]

    def name(self, card_id: str, zh: bool = False) -> str:
        card = self.get(card_id)
        if card is None:
            return ""
        return card.name_zh if zh else card.name

    def is_golden(self, card_id: str) -> bool:
        card = self.get(card_id)
        return bool(card is not None and card.is_golden)

    def canonical(self, card_id: str) -> str:
        """把金色变体 / 英雄皮肤解析为"本体 id"；未知 id 原样返回。"""
        cid = str(card_id)
        card = self.get(cid)
        if card is not None and card.normal:
            return card.normal
        if cid in self.skins:
            return self.skins[cid]
        return _canonical_engine_id(cid)

    @property
    def canonical_cards(self) -> Dict[str, CatalogCard]:
        """本体 id -> CatalogCard（金色变体已折叠）。"""
        return dict(self._canonical)


def load_catalog(path: Optional[Path | str] = None) -> AACatalog:
    """加载 AgenticAssistant catalog；文件缺失时抛 ``FileNotFoundError``。"""
    return AACatalog(path)


# ══════════════════════════════════════════════════════════════════════
# 引擎侧数据
# ══════════════════════════════════════════════════════════════════════


def _canonical_engine_id(card_id: str) -> str:
    """折叠引擎数据里的金色变体 id。

    **只折叠 ``XXXX_G``**（金色卡，catalog 用 ``normal`` 指向本体）。``_Gt``
    不能无脑折叠：它既可能是金色衍生物（catalog 的 ``normal`` 有值），也可能是
    独立卡（如 ``BG23_000_Gt`` 与 ``BG23_000t`` 是两张不同 dbf 的卡），因此
    以 catalog 的 ``normal`` 字段为准（见 :meth:`AACatalog.canonical`）。
    """
    cid = str(card_id)
    if cid.endswith("_G"):
        return cid[:-2]
    return cid


def load_engine_cards(
    data_dir: Optional[Path | str] = None,
    canonical_map: Optional[Mapping[str, str]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
    """加载引擎数据 JSON。

    ``canonical_map`` 给出额外的"变体 id -> 本体 id"映射（来自 catalog 的
    ``normal`` 字段，例如金色法术 ``BG19_010_Gt -> BG19_010t``）。

    返回 ``(records, file_counts, raw_union_count)``：``records`` 的 key 是
    **折叠金色后的本体 id**，value 是原始记录（附加 ``_source_file`` /
    ``_raw_id``）；同一 id 以本体记录优先（``bg_cards.json`` 最完整）。
    """
    root = Path(data_dir or DEFAULT_ENGINE_DATA_DIR)
    extra = dict(canonical_map or {})
    records: Dict[str, Dict[str, Any]] = {}
    file_counts: Dict[str, int] = {}
    raw_ids: set = set()
    for filename in ENGINE_DATA_FILES:
        path = root / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        file_counts[filename] = len(data)
        for row in data:
            if not isinstance(row, Mapping) or not row.get("id"):
                continue
            cid = str(row["id"])
            raw_ids.add(cid)
            key = extra.get(cid) or _canonical_engine_id(cid)
            enriched = dict(row)
            enriched["_source_file"] = filename
            enriched["_raw_id"] = cid
            if key not in records:
                records[key] = enriched
            elif records[key]["_raw_id"] != key and cid == key:
                # 同一本体既有金色记录又有本体记录时，优先保留本体（dbf/字段更权威）
                records[key] = enriched
    return records, file_counts, len(raw_ids)


def read_engine_patch(data_dir: Optional[Path | str] = None) -> str:
    """读取 ``data/bg_summary.json`` 里的 ``patch``（如 ``36.2.2.249896``）。"""
    root = Path(data_dir or DEFAULT_ENGINE_DATA_DIR)
    path = root / "bg_summary.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if isinstance(data, Mapping):
        return str(data.get("patch") or "")
    return ""


def load_race_names(
    game_tags_path: Optional[Path | str] = None,
) -> Dict[int, str]:
    """从 game_tags.json 读取 ``Race`` 枚举（数值 -> 名称），失败回退内置表。"""
    path = Path(game_tags_path or DEFAULT_GAME_TAGS_PATH)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        enums = raw["enums"]["Race"]
        names: Dict[int, str] = {}
        for key, value in enums.items():
            # python-hearthstone 里 PET=20 与 BEAST=20 是别名，只保留 BEAST
            if str(key) == "PET":
                continue
            names[int(value)] = str(key)
        return names
    except (OSError, ValueError, KeyError, TypeError):
        return dict(_RACE_FALLBACK)


def _normalize_race(name: str) -> str:
    value = str(name).strip().upper()
    if value in ("", "INVALID", "NONE"):
        return ""
    if value == "MECH":
        return "MECHANICAL"
    return value


def _id_prefix(card_id: str) -> str:
    head = str(card_id).split("_", 1)[0]
    # 双人模式前缀统一归类，避免表格被 BGDUO/BGDUO31/BGDUO33 切碎
    if head.startswith("BGDUO"):
        return "BGDUO"
    return head


# ══════════════════════════════════════════════════════════════════════
# 差异统计
# ══════════════════════════════════════════════════════════════════════


def _samples(rows: Sequence[Mapping[str, Any]], limit: int) -> List[Dict[str, Any]]:
    return [dict(r) for r in list(rows)[: max(0, int(limit))]]


def compare_with_engine_data(
    data_dir: Optional[Path | str] = None,
    catalog_path: Optional[Path | str] = None,
    game_tags_path: Optional[Path | str] = None,
    *,
    sample_limit: int = 25,
    include_timestamp: bool = True,
) -> Dict[str, Any]:
    """统计线上 36.6.3 catalog 与本地引擎数据（S14 / 36.2.2）的差异。

    返回可直接 JSON 序列化的 dict（同时写入 ``runs/data_diff_36.6.3.json``）。
    """
    cat = AACatalog(catalog_path)
    normal_map = {c.id: c.normal for c in cat.cards if c.normal}
    engine, engine_files, engine_raw_union = load_engine_cards(
        data_dir, canonical_map=normal_map
    )
    race_names = load_race_names(game_tags_path)
    engine_patch = read_engine_patch(data_dir)

    cat_canon = cat.canonical_cards
    cat_ids = set(cat_canon)
    eng_ids = set(engine)
    common = cat_ids & eng_ids
    only_catalog = sorted(cat_ids - eng_ids)
    only_engine = sorted(eng_ids - cat_ids)

    # ── overall ────────────────────────────────────────────────────
    overall = {
        "catalog_exact_count": cat.card_count,
        "catalog_canonical_count": len(cat_ids),
        "catalog_golden_variant_count": sum(1 for c in cat.cards if c.is_golden),
        "engine_exact_union_count": engine_raw_union,
        "engine_canonical_count": len(eng_ids),
        "id_intersection": len(common),
        "only_catalog_count": len(only_catalog),
        "only_engine_count": len(only_engine),
        "catalog_coverage": round(len(common) / len(cat_ids), 4) if cat_ids else 0.0,
    }

    # ── by_kind：按 catalog 的 kind 看引擎缺多少 ───────────────────
    by_kind: Dict[str, Dict[str, Any]] = {}
    for kind in cat.kinds:
        exact = cat.by_kind(kind)
        canon = [c for c in cat_canon.values() if c.kind == kind]
        canon_ids = {c.base_id for c in canon}
        matched = len(canon_ids & eng_ids)
        by_kind[kind] = {
            "catalog_cards": len(exact),
            "catalog_canonical": len(canon_ids),
            "matched": matched,
            "engine_missing": len(canon_ids) - matched,
        }

    # ── 新增疑似：按 id 前缀分组 ───────────────────────────────────
    only_catalog_prefix = Counter(_id_prefix(i) for i in only_catalog)
    only_engine_prefix = Counter(_id_prefix(i) for i in only_engine)

    # BG36 前缀是 36.6.3 的新卡池标识；单独给出"线上有、引擎缺"清单。
    bg36_ids = sorted(i for i in cat_ids if i.startswith("BG36"))
    bg36_missing = sorted(i for i in bg36_ids if i not in eng_ids)

    # ── 同 id 的字段差异 ───────────────────────────────────────────
    name_mismatches: List[Dict[str, Any]] = []
    dbf_mismatches: List[Dict[str, Any]] = []
    tier_mismatches: List[Dict[str, Any]] = []
    race_mismatches: List[Dict[str, Any]] = []
    keyword_mismatches: List[Dict[str, Any]] = []
    keyword_checked = 0

    cat_by_dbf: Dict[int, str] = {}
    for c in cat_canon.values():
        if c.dbf:
            cat_by_dbf.setdefault(c.dbf, c.base_id)
    eng_by_dbf: Dict[int, str] = {}
    for cid, row in engine.items():
        dbf = row.get("dbf_id") or row.get("dbf")
        if isinstance(dbf, int) and dbf:
            eng_by_dbf.setdefault(dbf, cid)

    # 引擎导出器只写"为真"的关键词布尔字段，且不同 card_type 支持的字段集合
    # 不同（英雄技能/饰品只导出少数几个）。先统计每个 card_type 出现过哪些
    # 映射字段，避免把"该类型不导出"误判成"没有该关键词"。
    keyword_support: Dict[Any, set] = {}
    mapped_fields = set(KEYWORD_TO_ENGINE_FIELD.values())
    for row in engine.values():
        card_type = row.get("card_type")
        support = keyword_support.setdefault(card_type, set())
        support.update(f for f in mapped_fields if f in row)
    # MINION(4) 导出最完整：全部映射字段都可比较（缺失即 false）
    if 4 in keyword_support:
        keyword_support[4].update(mapped_fields)
    keyword_uncovered = 0

    for cid in sorted(common):
        ccard = cat_canon[cid]
        erow = engine[cid]

        # 英文名（忽略大小写/空白）
        cname = ccard.name.strip().casefold()
        ename = str(erow.get("name") or "").strip().casefold()
        if cname and ename and cname != ename:
            name_mismatches.append(
                {"id": cid, "catalog_name": ccard.name, "engine_name": erow.get("name")}
            )

        # dbf 一致性
        edbf = erow.get("dbf_id") or erow.get("dbf")
        if isinstance(edbf, int) and edbf and ccard.dbf and edbf != ccard.dbf:
            dbf_mismatches.append(
                {"id": cid, "catalog_dbf": ccard.dbf, "engine_dbf": edbf}
            )

        # 酒馆等级（catalog 对非随从/非池内卡多为 0，只比较双方都有值的）
        etier = erow.get("tech_level")
        if ccard.kind == "minion" and ccard.tier > 0 and isinstance(etier, int) and etier > 0:
            if ccard.tier != etier:
                tier_mismatches.append(
                    {"id": cid, "catalog_tier": ccard.tier, "engine_tier": etier}
                )

        # 种族（引擎双种族卡：card_race 主种族 + race_tags 额外种族）
        c_races = {_normalize_race(r) for r in ccard.races if _normalize_race(r)}
        e_races = set()
        erased = erow.get("card_race")
        if isinstance(erased, int):
            e_race = _normalize_race(race_names.get(int(erased), ""))
            if e_race:
                e_races.add(e_race)
        for tag in erow.get("race_tags") or ():
            e_race = _normalize_race(tag)
            if e_race:
                e_races.add(e_race)
        if c_races and e_races and c_races != e_races:
            race_mismatches.append(
                {
                    "id": cid,
                    "catalog_races": sorted(c_races),
                    "engine_races": sorted(e_races),
                }
            )

        # 关键词（只统计该 card_type 确实导出该字段的部分）
        card_type = erow.get("card_type")
        supported = keyword_support.get(card_type, set())
        for keyword, field_name in KEYWORD_TO_ENGINE_FIELD.items():
            if field_name not in supported:
                keyword_uncovered += 1
                continue
            keyword_checked += 1
            cat_has = keyword in ccard.keywords
            eng_has = bool(erow.get(field_name, False))
            if cat_has != eng_has:
                keyword_mismatches.append(
                    {
                        "id": cid,
                        "keyword": keyword,
                        "engine_field": field_name,
                        "catalog_has": cat_has,
                        "engine_has": eng_has,
                    }
                )

    # 同 dbf 但 id 不同（改名/重发卡）——只看本体
    dbf_id_changes: List[Dict[str, Any]] = []
    for dbf, cat_id in sorted(cat_by_dbf.items()):
        eng_id = eng_by_dbf.get(dbf)
        if eng_id and eng_id != cat_id:
            dbf_id_changes.append({"dbf": dbf, "catalog_id": cat_id, "engine_id": eng_id})

    catalog_keywords = Counter()
    for c in cat_canon.values():
        catalog_keywords.update(c.keywords)

    result: Dict[str, Any] = {
        "schema": "hsbg.real_game_data_diff.v1",
        "generated_by": "hsbg.bridge.catalog.compare_with_engine_data",
        "catalog": cat.summary(),
        "engine": {
            "data_dir": str(Path(data_dir or DEFAULT_ENGINE_DATA_DIR)),
            "patch": engine_patch,
            "file_counts": dict(sorted(engine_files.items())),
            "canonical_count": len(eng_ids),
        },
        "overall": overall,
        "by_kind": by_kind,
        "only_catalog": {
            "count": len(only_catalog),
            "ids": only_catalog,
            "by_prefix": dict(only_catalog_prefix.most_common()),
        },
        "only_engine": {
            "count": len(only_engine),
            "ids": only_engine,
            "by_prefix": dict(only_engine_prefix.most_common()),
        },
        "new_cards_suspect": {
            "BG36": {
                "catalog_count": len(bg36_ids),
                "matched": len(bg36_ids) - len(bg36_missing),
                "engine_missing": len(bg36_missing),
                "missing_ids": bg36_missing,
            }
        },
        "field_diffs": {
            "name_mismatches": {
                "count": len(name_mismatches),
                "samples": _samples(name_mismatches, sample_limit),
                "ids": [m["id"] for m in name_mismatches],
            },
            "dbf_mismatches": {
                "count": len(dbf_mismatches),
                "samples": _samples(dbf_mismatches, sample_limit),
            },
            "tier_mismatches": {
                "count": len(tier_mismatches),
                "samples": _samples(tier_mismatches, sample_limit),
                "ids": [m["id"] for m in tier_mismatches],
            },
            "race_mismatches": {
                "count": len(race_mismatches),
                "samples": _samples(race_mismatches, sample_limit),
            },
            "keyword_mismatches": {
                "checked_pairs": keyword_checked,
                "uncovered_pairs": keyword_uncovered,
                "count": len(keyword_mismatches),
                "samples": _samples(keyword_mismatches, sample_limit),
            },
            "dbf_id_changes": {
                "count": len(dbf_id_changes),
                "samples": _samples(dbf_id_changes, sample_limit),
            },
        },
        "catalog_keyword_coverage": {
            "mapped_keywords": sorted(KEYWORD_TO_ENGINE_FIELD),
            "unmapped_keywords": sorted(
                k for k in catalog_keywords if k not in KEYWORD_TO_ENGINE_FIELD
            ),
            "counts": dict(catalog_keywords.most_common()),
        },
        "notes": [
            "catalog.json 只含公共元数据（无 atk/health/cost/text），数值改动无法量化；"
            "数值权威是 hsdata/CardDefs.xml。",
            "比较前对金色变体做了折叠（catalog 用 normal 字段；引擎 _G/_Gt 后缀），"
            "否则会把金色版本误判为新增卡。",
            "engine 侧是累积 CardDefs 导出（含历史/轮换/令牌卡），only_engine 不等于"
            "线上删除；只有 only_catalog 里的 BG36 前缀可视为线上新卡。",
            "BGDUO 前缀是双人模式卡，单人引擎天然缺失，升级时可不迁移。",
            "名称/种族/关键词差异受导出字段覆盖面影响，属指示性统计，不是逐卡审计。",
        ],
    }
    if include_timestamp:
        result["generated_at_utc"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
    return result


def write_diff_json(
    out_path: Optional[Path | str] = None,
    *,
    data_dir: Optional[Path | str] = None,
    catalog_path: Optional[Path | str] = None,
    sample_limit: int = 25,
) -> Path:
    """生成差异统计并写入 UTF-8 JSON，返回输出路径。"""
    target = Path(out_path or DEFAULT_DIFF_OUT)
    target.parent.mkdir(parents=True, exist_ok=True)
    diff = compare_with_engine_data(
        data_dir=data_dir,
        catalog_path=catalog_path,
        sample_limit=sample_limit,
    )
    target.write_text(
        json.dumps(diff, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return target


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def _print_summary(diff: Mapping[str, Any]) -> None:
    overall = diff["overall"]
    catalog = diff["catalog"]
    engine = diff["engine"]
    print(f"catalog: {catalog['game_version']}  cards={catalog['card_count']} "
          f"(canonical {overall['catalog_canonical_count']}, skins={catalog['skin_count']})")
    print(f"engine : patch {engine['patch'] or '?'}  files={len(engine['file_counts'])}  "
          f"canonical={engine['canonical_count']}")
    print(f"id intersection={overall['id_intersection']}  "
          f"only_catalog={overall['only_catalog_count']}  "
          f"only_engine={overall['only_engine_count']}")
    print("by_kind:")
    for kind, row in diff["by_kind"].items():
        print(f"  {kind:16s} catalog={row['catalog_canonical']:5d} "
              f"matched={row['matched']:5d} engine_missing={row['engine_missing']:4d}")
    print("only_catalog by prefix:", diff["only_catalog"]["by_prefix"])
    print("only_engine  by prefix:", diff["only_engine"]["by_prefix"])
    print("BG36 new-card suspect:",
          diff["new_cards_suspect"]["BG36"]["engine_missing"], "missing",
          "/", diff["new_cards_suspect"]["BG36"]["catalog_count"], "catalog")
    field = diff["field_diffs"]
    print("field diffs: name={} tier={} race={} keyword={}/{} dbf_id_changes={}".format(
        field["name_mismatches"]["count"],
        field["tier_mismatches"]["count"],
        field["race_mismatches"]["count"],
        field["keyword_mismatches"]["count"],
        field["keyword_mismatches"]["checked_pairs"],
        field["dbf_id_changes"]["count"],
    ))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="AgenticAssistant catalog.json 只读查询 / 与引擎数据差异统计"
    )
    sub = parser.add_subparsers(dest="command")

    p_info = sub.add_parser("info", help="打印 catalog 概况")
    p_info.add_argument("--catalog", default=None)

    p_diff = sub.add_parser("diff", help="生成与引擎数据的差异统计 JSON")
    p_diff.add_argument("--catalog", default=None)
    p_diff.add_argument("--data-dir", default=None)
    p_diff.add_argument("--out", default=str(DEFAULT_DIFF_OUT))
    p_diff.add_argument("--samples", type=int, default=25)

    p_get = sub.add_parser("get", help="按 id / dbf 查询单卡")
    p_get.add_argument("key")

    args = parser.parse_args(argv)
    if args.command in (None, "info"):
        cat = AACatalog()
        print(json.dumps(cat.summary(), ensure_ascii=False, indent=1))
        return 0
    if args.command == "get":
        cat = AACatalog()
        card = cat.get(args.key) or (
            cat.from_dbf(int(args.key)) if str(args.key).isdigit() else None
        )
        if card is None:
            print(f"未找到: {args.key}")
            return 1
        print(json.dumps(card.to_dict(), ensure_ascii=False, indent=1))
        return 0
    if args.command == "diff":
        diff = compare_with_engine_data(
            data_dir=args.data_dir,
            catalog_path=args.catalog,
            sample_limit=args.samples,
        )
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(diff, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        _print_summary(diff)
        print(f"written: {target}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
