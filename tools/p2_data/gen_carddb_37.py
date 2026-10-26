#!/usr/bin/env python3
"""生成 37.0.0.255130 版本的 AutoTavern schema `cards.json`（离线、可复现）。

背景
----
第二阶段主路线是 fork AutoTavern 的 Rust 引擎（`hsbg_engine`）。上游引擎把
`crates/taverngym/data/cards.json`（36.6.3.253932，3983 卡）编译进二进制；本脚本把
HSBRSIM 官方数据 `data/bg_*.json`（patch 37.0.0.255130）映射为**同一 schema**，输出
`data/p2/cards_37.json`，供 Rust fork 替换数据使用。

设计原则
--------
1. **能映射的映射**（T1，来自 37 官方数据）；映射不了的字段按来源分层处理，绝不编造：
   - T1: 37 数据直接映射；
   - T2: 37 数据没有等价来源、但 36.6.3 上游有且 37 仍存在同一卡片 id → 继承上游值，
     并在 MANIFEST 的 `field_provenance` 里显式登记（`inherit_36_6_3`）；
   - T3: 两版都没有 → 省略字段/用 schema 默认值（Rust serde `default`）。
2. **兼容并集**（compat 条目）：上游 Rust 引擎启动时 `script.rs::registry()` 会对每个
   content 脚本执行 `db().id(id)`，`CardDb::id`（cards.rs:406）对缺失 id 直接 panic。
   36.6.3 有、37.0.0 已不在官方数据里的卡（退环境/轮换）以 compat 条目保留：
   字段沿用上游，但 `pools=[]`、`pool_tag=0`、`reachable=false`，不进入任何池子。
3. **确定性**：输出不含时间戳；同一输入两次运行 byte-identical（`--check` 校验）。
   JSON 仍沿用上游“一行一卡”的 diff 友好格式。
4. **可复算**：MANIFEST 记录源版本/行数/各 kind 计数/字段覆盖率/未映射字段/差分统计/
   生成命令；`--report` 打印同一批数字。

用法
----
    python3 tools/p2_data/gen_carddb_37.py            # 写 data/p2/*
    python3 tools/p2_data/gen_carddb_37.py --check    # 校验已入库产物是否与重算一致
    python3 tools/p2_data/gen_carddb_37.py --report   # 只打印统计，不写文件
    python3 tools/p2_data/gen_carddb_37.py --out DIR  # 写到指定目录（可复现性测试用）

可选参数 `--at-root PATH`（默认 `/Users/letiangao/HSAgent/repos/AutoTavern`，也可用环境
变量 `HSBRSIM_AT_ROOT`）指定只读的 AutoTavern 仓库路径——compat 条目、T2 继承字段、
脚本 id 清单都从那里读取。

写范围：`tools/p2_data/**`、`data/p2/**`。本脚本不改动 `data/**` 既有文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]          # HSBRSIM 仓库根
DATA = ROOT / "data"
DEFAULT_OUT = DATA / "p2"
DEFAULT_AT_ROOT = Path(
    os.environ.get("HSBRSIM_AT_ROOT", "/Users/letiangao/HSAgent/repos/AutoTavern")
)
AT_CARDS_REL = "crates/taverngym/data/cards.json"
AT_SRC_REL = "crates/taverngym/src"

GEN_VERSION = "1.1.0"          # 生成器 schema 版本（改动映射规则时同步 +1）
SCHEMA_ID = "hsbrsim-p2-carddb/1"
CLIENT_VERSION = "37.0.0.255130"
SERVER_PATCH = "37.0.0"
SOURCE_DESC = "HSBRSIM 官方数据 37.0.0.255130 + AutoTavern 36.6.3 compat 条目"

#: 37 数据里 card_type 的语义（见 hsrl2/tags.py CardType）
CARD_TYPE_HERO = 3
CARD_TYPE_MINION = 4
CARD_TYPE_SPELL = 5
CARD_TYPE_HERO_POWER = 10
CARD_TYPE_QUEST_REWARD = 40          # BACON_QUEST_REWARD
CARD_TYPE_TAVERN_SPELL = 42          # BACON_SPELL
CARD_TYPE_ANOMALY = 43               # BACON_ANOMALY
CARD_TYPE_TRINKET = 44               # BACON_TRINKET
CARD_TYPE_PLAYER_BUTTON = 12         # 按钮实体（升级/刷新/黑暗赠礼发现按钮）
CARD_TYPE_UI_22 = 22                 # 拖拽购买/出售占位
CARD_TYPE_UI_24 = 24                 # 伙伴进度条按钮
#: AutoTavern schema 不收录的 37 卡类型（UI/异变）——它们不会进入 cards_37.json，
#: 但会在 new_cards_37.json 中登记。
SKIPPED_CARD_TYPES = {
    CARD_TYPE_ANOMALY: "anomaly",
    CARD_TYPE_PLAYER_BUTTON: "ui_button",
    CARD_TYPE_UI_22: "ui_button",
    CARD_TYPE_UI_24: "ui_button",
}

#: 37 数值 → AutoTavern 种族名。数值来自 hsdata `CARDRACE`（hsrl2/tags.py `Race`）。
RACE_BY_VALUE = {
    11: "UNDEAD",
    14: "MURLOC",
    15: "DEMON",
    17: "MECHANICAL",
    18: "ELEMENTAL",
    20: "BEAST",
    23: "PIRATE",
    24: "DRAGON",
    26: "ALL",
    43: "QUILBOAR",
    92: "NAGA",
    126: "ABERRATION",
}
#: 37 `subset_*` 布尔标记 → AutoTavern 种族名。
#: 语义（由 36.6.3 上游数据实测校准，见 docs/DATA_37_MIGRATION.md §3）：
#:   - 非随从卡：等价于上游 `assoc`（关联种族/饰品适配种族）；
#:   - 酒馆法术：同时等价于上游 `lobby_req`（仅在该种族酒馆出现）；
#:   - 随从卡：是“池内子集”标记（含本种族），`assoc = subset - races`。
SUBSET_TO_RACE = {
    "subset_undead": "UNDEAD",
    "subset_murloc": "MURLOC",
    "subset_demon": "DEMON",
    "subset_mech": "MECHANICAL",
    "subset_elemental": "ELEMENTAL",
    "subset_beast": "BEAST",
    "subset_pirate": "PIRATE",
    "subset_dragon": "DRAGON",
    "subset_quilboar": "QUILBOAR",
    "subset_naga": "NAGA",
}
#: `race_tags` 列表里的字符串可能是 hsdata 内的名字（MECH = MECHANICAL 别名）。
RACE_ALIAS = {"MECH": "MECHANICAL"}

#: 37 布尔 flag → AutoTavern `keywords` 名称（全部由 36.6.3 数据校准：0 误报）。
FLAG_KEYWORDS = [
    ("battlecry", "BATTLECRY"),
    ("deathrattle", "DEATHRATTLE"),
    ("taunt", "TAUNT"),
    ("divine_shield", "DIVINE_SHIELD"),
    ("windfury", "WINDFURY"),
    ("reborn", "REBORN"),
    ("magnetic", "MAGNETIC"),
    ("venomous", "VENOMOUS"),
    ("poisonous", "POISONOUS"),
    ("avenge", "AVENGE"),
    ("start_of_combat", "START_OF_COMBAT"),
    ("rally", "BACON_RALLY"),
    ("choose_one", "CHOOSE_ONE"),
    ("quest", "QUEST"),
]
#: 黑暗赠礼卡在 37 数据里没有布尔 flag，只有文本；按文本里“加粗的机制词”还原。
DARK_GIFT_BOLD_KEYWORDS = {
    "Deathrattle:": "DEATHRATTLE",
    "Taunt": "TAUNT",
    "Divine Shield": "DIVINE_SHIELD",
    "Windfury": "WINDFURY",
    "Reborn": "REBORN",
    "Venomous": "VENOMOUS",
    "Poisonous": "POISONOUS",
    "Magnetic": "MAGNETIC",
    "Stealth": "STEALTH",
}

#: AutoTavern schema 允许的 kind（Rust `CardKind::parse` 的 10 个取值）。
KINDS = (
    "minion",
    "spell",
    "hero",
    "hero_power",
    "trinket_lesser",
    "trinket_greater",
    "tavern_spell",
    "quest",
    "quest_reward",
    "dark_gift",
)
#: 池子名称 → Rust `Pools` 字段；输出时按此顺序稳定排序。
POOL_ORDER = ("minion", "tier7", "hero", "spell", "trinket", "timewarp")

#: 输出字段顺序（必填字段固定，可选字段只在非默认值时输出——与上游 gen_carddb.py 一致）。
REQUIRED_FIELDS = [
    "id", "dbf", "kind", "name", "name_zh", "tier", "atk", "hp", "armor",
    "cost", "races", "assoc", "keywords", "golden", "normal", "pools",
    "text", "text_zh", "pool_tag", "reachable",
]
OPTIONAL_FIELDS = [
    "hero_power", "buddy", "prize_tier", "reward_card", "quest_goal",
    "spellcraft_spell", "spellcraft", "window", "tw_types", "tw_weight",
    "tw_min_minions", "text_alt", "text_alt_zh", "lobby_req",
]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

#: T2（继承 36.6.3）字段：37 数据没有等价来源，但上游 36.6.3 有。
#: 全部在 MANIFEST 的 field_provenance 中登记；docs 里说明收敛计划。
INHERITED_FIELDS = [
    "pools.trinket",
    "pools.timewarp",
    "reachable",
    "window",
    "prize_tier",
    "tw_types",
    "tw_weight",
    "tw_min_minions",
    "lobby_req(19 张 ABERRATION 门控)",
    "golden/normal(目标缺失时补齐)",
    "name_zh(37 中文缺失时)/text_zh(英文逐字对齐时优先 36.6.3)",
]

#: Duos（双人模式）专属文本标记（P2-C 审计 P2-C `docs/PORTING_37_PLAN.md` §2.4/§4.5）。
#: 37 数据里「单人 + Duos」双版本卡的写法是 `单人文本@Duos 文本`（如 BG36_100），拆分后
#: 有第二段 → 单人可用；只有「单段且含下列标记」的卡才是 Duos-only，必须剔除单人池。
DUOS_TEXT_RE = re.compile(r"(?i)\bteammate\b|\bpass (?:a|an|one)\b")

#: AutoTavern 机制元数据（P2-B3）：AT 机制实现依赖、但 37 官方数据没有权威等价来源的
#: 客户端字段。对两版本共享 id 从 36.6.3 上游 `cards.json` 继承（不改变 37 数值/文本）：
#:   - `pool_tag`：客户端 `IS_BACON_POOL_MINION` 原值（0/1/2），Rust strict 池过滤依赖它
#:     （`flow.rs: filter(|c| !cfg.strict_pool_tag || c.pool_tag <= 1)`）；必须精确继承，
#:     含 0 值——37 源只有布尔 `is_pool_minion`，无法表达 `BG25_013` 的 2。
#:   - 其余：AT 有非默认值时才继承（lobby_req/assoc/window/buddy/…），37 独有卡留空。
T3_EXACT_META = ("pool_tag",)
T3_INHERIT_META = (
    "lobby_req", "assoc", "window", "buddy", "hero_power", "reward_card",
    "spellcraft", "spellcraft_spell", "prize_tier", "quest_goal",
    "text_alt", "text_alt_zh",
)

#: Dark Paradox（AT `flow.rs::PARADOX_VARIANTS`）：base 卡不入池；每局从 5 个形态中随机
#: 1 个进池（`universe` 过滤 `c.id.starts_with("BG36_360t")` 后只保留被选中的形态）。
#: 37 源把 base 标成池内、token 不标，因此按 AT 机制约定特例修正；tier/数值保持 37 值。
#: 依据 AT `flow.rs` 注释：tier5 形态是 t4、tier6 形态是 t9；
#: 详见 docs/PORTING_37_PLAN.md；P1 内容移植阶段会改为 37 单卡动态机制。
PARADOX_BASE = "BG36_360"
PARADOX_VARIANTS = ("BG36_360t3", "BG36_360t4", "BG36_360t5", "BG36_360t6", "BG36_360t9")
PARADOX_VARIANT_TIERS = (2, 5, 4, 3, 6)

TAG_RE = re.compile(r"<[^>]+>")
MULTI_SPACE_RE = re.compile(r" {2,}")
PLACEHOLDER_RE = re.compile(r"\{(\d)\}")
PLURAL_RE = re.compile(r"(\d+)\s*\|4\(([^,]+?),\s*([^)]+?)\)")
PLURAL_NO_NUM_RE = re.compile(r"\|4\(([^,]+?),\s*([^)]+?)\)")


# ---------------------------------------------------------------------------
# 37 数据装载
# ---------------------------------------------------------------------------

class SourceData:
    """37.0.0 官方输入数据（只读）。"""

    FILES = {
        "bg_cards": "bg_cards.json",
        "bg_pool_minions": "bg_pool_minions.json",
        "bg_pool_spells": "bg_pool_spells.json",
        "bg_heroes": "bg_heroes.json",
        "bg_hero_powers": "bg_hero_powers.json",
        "bg_trinkets": "bg_trinkets.json",
        "bg_quest_rewards": "bg_quest_rewards.json",
        "bg_anomalies": "bg_anomalies.json",
        "bg_dark_gifts": "bg_dark_gifts.json",
        "bg_tavern_spells": "bg_tavern_spells.json",
    }

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.lists: dict[str, list[dict]] = {}
        for key, name in self.FILES.items():
            path = data_dir / name
            if not path.is_file():
                raise SystemExit(f"缺少输入数据: {path}")
            self.lists[key] = json.loads(path.read_text(encoding="utf-8"))
        summary_path = data_dir / "bg_summary.json"
        self.summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.is_file()
            else {}
        )
        # 中文名/文本（若存在）。card_zhcn.json 是通用卡牌中文表（34607 条）。
        zh_path = data_dir / "card_zhcn.json"
        self.zh: dict[str, dict] = (
            json.loads(zh_path.read_text(encoding="utf-8")) if zh_path.is_file() else {}
        )

        # 37 全部可选实体（卡牌 + 英雄 + 英雄技能），以及 dbf_id → id 反查表。
        self.entities: dict[str, tuple[str, dict]] = {}
        for card in self.lists["bg_cards"]:
            self.entities[card["id"]] = ("card", card)
        for hero in self.lists["bg_heroes"]:
            self.entities[hero["id"]] = ("hero", hero)
        for power in self.lists["bg_hero_powers"]:
            self.entities[power["id"]] = ("hero_power", power)
        self.dbf_to_id: dict[int, str] = {
            obj["dbf_id"]: cid for cid, (_src, obj) in self.entities.items()
        }
        # 各池子文件成员（只保留能映射的 kind；anomaly/按钮不在此列）。
        self.pool_members = {
            "minion": {c["id"] for c in self.lists["bg_pool_minions"]},
            "spell": {c["id"] for c in self.lists["bg_pool_spells"]},
            "hero": {c["id"] for c in self.lists["bg_heroes"]},
            "trinket": {c["id"] for c in self.lists["bg_trinkets"]},
        }
        self.tavern_spells = {c["id"] for c in self.lists["bg_tavern_spells"]}
        self.dark_gifts = {c["id"] for c in self.lists["bg_dark_gifts"]}
        self.quest_rewards = {c["id"] for c in self.lists["bg_quest_rewards"]}


# ---------------------------------------------------------------------------
# 文本规范化（全部是“格式整理”，不引入新内容）
# ---------------------------------------------------------------------------

def _sdn(card: dict, n: int) -> str:
    """`{N}` 占位符的取值来源：script_data_num_{N+1}，缺失时按上游同款渲染为 0。"""
    value = card.get(f"script_data_num_{n}")
    return str(value) if isinstance(value, int) else "0"


def _split_variants(text: str) -> list[str]:
    """拆分 hsdata 里用 '@' 粘连的“多段显示文本”。

    '@' 在 37 数据里有两种含义：多段文本的分隔符、以及动态数值占位符
    （例如 `(@ Gold left!)`、`Summon a @/@`）。判定为分隔符的条件（用 36.6.3
    数据校准）：'@' 前的最后一个非空白/下划线字符是句末标点（`.!?>)` 或全角
    `。！？`、全角右括号 `）` 等），或 '@' 后紧跟 `[x]` / `<b>`。
    """
    parts: list[str] = []
    start = 0
    for match in re.finditer("@", text):
        before = text[: match.start()].rstrip(" _")
        after = text[match.end():].lstrip()
        is_sep = (
            after.startswith("[x]")
            or after.startswith("<b>")
            or (bool(before) and before[-1] in ".!?>)>。！？；：）】」』")
        )
        if is_sep:
            parts.append(text[start: match.start()])
            start = match.end()
    parts.append(text[start:])
    cleaned = [p.strip(" _") for p in parts]
    return [p for p in cleaned if p]


def _substitute(text: str, card: dict) -> str:
    """占位符替换：`{N}` → script_data_num_{N+1}；剩余 '@' → script_data_num_1。"""
    text = PLACEHOLDER_RE.sub(lambda m: _sdn(card, int(m.group(1)) + 1), text)
    return text.replace("@", _sdn(card, 1))


def _clean(text: str) -> str:
    """去标记/压缩空白（与上游 gen_carddb.clean 等价，另处理 37 的 '_' 空格标记）。"""
    text = TAG_RE.sub("", text or "").replace("[x]", "").replace("\xa0", " ")
    text = text.replace("-\n", "- ").replace("\n", " ")
    text = text.replace("_", " ")           # hsdata 用 '_' 表示“此处是空格”
    text = MULTI_SPACE_RE.sub(" ", text).strip()

    def plural(match: re.Match) -> str:
        num, singular, plural_word = match.group(1), match.group(2).strip(), match.group(3).strip()
        return f"{num} {singular if num == '1' else plural_word}"

    text = PLURAL_RE.sub(plural, text)

    # 没有紧邻数字的 |4(singular, plural)：按“同句最近的前置数字”判单复数；
    # 完全没有数字时按复数渲染（中文文本一般不含该标记）。
    def plural_loose(match: re.Match) -> str:
        prefix = text[: match.start()]
        nums = re.findall(r"(?<![\d{.])(\d+)(?![\d}])", prefix)
        word = match.group(2).strip() if not nums else (
            match.group(1).strip() if nums[-1] == "1" else match.group(2).strip()
        )
        return word

    text = PLURAL_NO_NUM_RE.sub(plural_loose, text)
    return MULTI_SPACE_RE.sub(" ", text).strip()


def normalize_text(card: dict, raw: str, *, is_zh: bool = False) -> tuple[str, str]:
    """返回 (text, text_alt)；text_alt 为空表示没有第二段显示文本。"""
    variants = _split_variants(raw or "")
    if not variants:
        return "", ""
    main = _clean(_substitute(variants[0], card))
    alt = _clean(_substitute(variants[1], card)) if len(variants) > 1 else ""
    # 上游 set_texts 的一致性修正：中文第二段若数字与英文主文本不一致则互换（这里没有
    # 英文主文本可对照，仅做“与主文本相同则丢弃”的去重）。
    if alt == main:
        alt = ""
    return main, alt


def normalize_zh(card: dict) -> tuple[str, str]:
    entry = card.get("_zh") or {}
    return normalize_text(card, entry.get("t") or "", is_zh=True)


def is_duos_only(card: dict) -> bool:
    """Duos-only 判定：文本没有第二段（单人变体）且含 Duos 标记。

    依据 P2-C 审计（`docs/PORTING_37_PLAN.md` §2.4）：`bg_pool_spells` 里
    `BG31_242 Bargain Bundle`（“Your teammate gets the other options.”）、
    `BG31_243 Portal in a Fountain` / `BG31_244 Portal in a Crystal`
    （“Pass a minion …”）是单人模式不可用的 Duos 专属法术，单人池应为 73 而非 76；
    36.6.3 上游同 id 的 `pools=[]`、`reachable=false`，与本规则一致。
    三张卡在 37 与 36.6.3 数据中都没有金卡形式（无 `_G` id）。
    """
    main, alt = normalize_text(card, card.get("text") or "")
    return not alt and bool(DUOS_TEXT_RE.search(main))


# ---------------------------------------------------------------------------
# 字段推导
# ---------------------------------------------------------------------------

def subset_races(card: dict) -> set[str]:
    return {race for flag, race in SUBSET_TO_RACE.items() if card.get(flag)}


def races_of(card: dict) -> list[str]:
    """随从种族：card_race 主类型 ∪ race_tags 附加类型（MECH→MECHANICAL）。"""
    races: list[str] = []
    primary = card.get("card_race")
    if primary:
        if primary not in RACE_BY_VALUE:
            raise SystemExit(f"{card['id']}: 未知 card_race 数值 {primary}")
        races.append(RACE_BY_VALUE[primary])
    for tag in card.get("race_tags") or []:
        name = RACE_ALIAS.get(str(tag), str(tag))
        if name not in RACE_BY_VALUE.values():
            raise SystemExit(f"{card['id']}: 未知 race_tags 值 {tag!r}")
        if name not in races:
            races.append(name)
    return races


def assoc_of(kind: str, card: dict, races: list[str]) -> list[str]:
    """关联种族（上游 assoc）：非随从卡 = subset；随从卡 = subset − races。"""
    subset = subset_races(card)
    values = subset - set(races) if kind == "minion" else subset
    return sorted(values)


def lobby_req_of(kind: str, card: dict) -> list[str]:
    """酒馆法术的“种族酒馆门控”等价于 subset 标记（36.6.3 上游 202/205 精确吻合）。"""
    if kind == "tavern_spell":
        return sorted(subset_races(card))
    return []


def kind_of(source: str, card: dict) -> str | None:
    """由 37 卡类型/池子/flag 判定 AutoTavern kind；None = schema 不收录。"""
    if source == "hero":
        return "hero"
    if source == "hero_power":
        return "hero_power"
    card_type = card.get("card_type")
    if card_type == CARD_TYPE_MINION:
        return "minion"
    if card_type == CARD_TYPE_QUEST_REWARD:
        return "quest_reward"
    if card_type == CARD_TYPE_TAVERN_SPELL:
        return "tavern_spell"
    if card_type == CARD_TYPE_TRINKET:
        school = card.get("spell_school")
        # 36.6.3 实测：spell_school 11 = lesser、12 = greater（194/194、215/215 吻合）。
        if school == 11:
            return "trinket_lesser"
        if school == 12:
            return "trinket_greater"
        raise SystemExit(f"{card['id']}: 未知饰品 spell_school {school!r}")
    if card_type == CARD_TYPE_SPELL:
        if card.get("dark_gift"):
            return "dark_gift"
        text = card.get("text") or ""
        if card.get("quest") or (
            card.get("quest_progress_total") is not None
            and ("Quest" in text or "Quests" in text)
        ):
            return "quest"
        return "spell"
    return None


def keywords_of(kind: str, card: dict) -> list[str]:
    """关键词：布尔 flag 直映射 + 少量“上游同款”文本推导 + 黑暗赠礼的加粗机制词。"""
    keywords: set[str] = set()
    for flag, name in FLAG_KEYWORDS:
        if card.get(flag):
            keywords.add(name)
    if card.get("spellcraft_id") is not None:
        keywords.add("BACON_SPELLCRAFT_ID")
    main_text, _alt = normalize_text(card, card.get("text") or "")
    if kind == "minion":
        # 与上游 gen_carddb.text_keywords 相同的规则：文本里有 Start of Combat 就补标签。
        if "Start of Combat:" in main_text:
            keywords.add("START_OF_COMBAT")
        # 固有潜行：文本（去掉标记后）以 Stealth 开头；纯文本无法区分“给予潜行”。
        if main_text.startswith("Stealth"):
            keywords.add("STEALTH")
        # 结束回合触发：36.6.3 数据校准 tp176/fp8/fn15（行为上仅黑暗赠礼 t21 资格用到）。
        if re.search(r"[Ee]nd of\s+(?:(?:your|each|every|the)\s+)?(?:\d+\s+)?turns?\b", main_text):
            keywords.add("END_OF_TURN_TRIGGER")
    elif kind in ("trinket_lesser", "trinket_greater", "hero_power", "quest_reward"):
        # 非随从卡在 37 数据里没有 START_OF_COMBAT 布尔标记；文本规则在 36.6.3 上
        # 实测 tp=55/fp=5（饰品/英雄技能/任务奖励），酒馆法术噪声大故不做。
        if "Start of Combat:" in main_text:
            keywords.add("START_OF_COMBAT")
    elif kind == "dark_gift":
        raw = card.get("text") or ""
        for bold, name in DARK_GIFT_BOLD_KEYWORDS.items():
            if f"<b>{bold}</b>" in raw:
                keywords.add(name)
    return sorted(keywords)


def pools_of(source: str, kind: str, card: dict, source_data: SourceData) -> list[str]:
    """池子成员：minion/tier7/spell/hero 来自 37 池子文件；trinket/timewarp 见 T2 继承。"""
    pools: set[str] = set()
    cid = card["id"]
    duos_only = source == "card" and is_duos_only(card)
    # 当前版本 Naga 不在随从池（历史卡仍保留在卡片表中，但不进入 minion/tier7）。
    naga = int(card.get("card_race") or 0) == 92
    if source == "card" and card.get("is_pool_minion") and not duos_only and not naga:
        pools.add("minion")
        if card.get("tech_level") == 7:
            pools.add("tier7")
    if source == "card" and card.get("is_pool_spell") and not duos_only:
        pools.add("spell")
    if source == "hero":
        pools.add("hero")
    return [name for name in POOL_ORDER if name in pools]


# ---------------------------------------------------------------------------
# compat（36.6.3 上游独有卡）与卡片构建
# ---------------------------------------------------------------------------

def load_at_data(at_root: Path) -> tuple[dict, dict]:
    cards_path = at_root / AT_CARDS_REL
    if not cards_path.is_file():
        raise SystemExit(
            f"找不到上游 AutoTavern 数据: {cards_path}\n"
            "（用 --at-root 或 HSBRSIM_AT_ROOT 指定只读 AutoTavern 仓库）"
        )
    payload = json.loads(cards_path.read_text(encoding="utf-8"))
    return payload.get("meta", {}), {c["id"]: c for c in payload["cards"]}


def _at_field_defaults(card: dict) -> dict:
    """上游卡的可选字段默认值（用于判断是否需要输出）。"""
    return {
        "hero_power": "",
        "buddy": "",
        "prize_tier": 0,
        "reward_card": "",
        "quest_goal": 0,
        "spellcraft_spell": False,
        "spellcraft": "",
        "window": None,
        "tw_types": [],
        "tw_weight": None,
        "tw_min_minions": 0,
        "text_alt": "",
        "text_alt_zh": "",
        "lobby_req": [],
    }


def canonical_entry(fields: dict) -> dict:
    """按固定字段顺序输出；可选字段等于默认值时省略（与上游渲染一致）。"""
    out: dict = {}
    for name in ALL_FIELDS:
        value = fields.get(name)
        if name in REQUIRED_FIELDS:
            out[name] = value
            continue
        default = _at_field_defaults({}).get(name)
        if value is None or value == default or value == [] or value == "":
            continue
        out[name] = value
    return out


def build_card37(source: str, card: dict, source_data: SourceData, at_by_id: dict) -> dict:
    """把一张 37 实体映射为 AutoTavern schema 条目（T1 字段）。"""
    cid = card["id"]
    kind = kind_of(source, card)
    assert kind is not None
    races = races_of(card) if kind == "minion" else []
    # 中文：data/card_zhcn.json 优先（T1）；缺失时按 T2 继承上游（见 finalize_provenance）。
    zh_entry = source_data.zh.get(cid) or {}
    card_for_text = dict(card)
    card_for_text["_zh"] = zh_entry
    name_zh = zh_entry.get("n") or ""
    text_zh, text_alt_zh = normalize_zh(card_for_text)
    text, text_alt = normalize_text(card, card.get("text") or "")
    pools = pools_of(source, kind, card, source_data)
    entry: dict = {
        "id": cid,
        "dbf": card["dbf_id"],
        "kind": kind,
        "name": card.get("name") or cid,
        "name_zh": name_zh,
        "tier": card.get("tech_level") or 0,
        "atk": card.get("atk") or 0,
        "hp": card.get("health") or 0,
        "armor": card.get("armor") or 0,
        "cost": card.get("cost") or 0,
        "races": races,
        "assoc": assoc_of(kind, card, races),
        "keywords": keywords_of(kind, card),
        "golden": "",
        "normal": "",
        "pools": pools,
        "text": text,
        "text_zh": text_zh,
        "pool_tag": 0 if (int(card.get("card_race") or 0) == 92) else
                      (1 if card.get("is_pool_minion") else 0),
        "reachable": bool(pools),
    }
    if is_duos_only(card):
        # P2-C 审计：Duos-only 卡不进单人池（BG31_242/243/244）。
        entry["pools"] = []
        entry["pool_tag"] = 0
        entry["reachable"] = False
    # --- 关系字段（T1：37 数据里都是 dbf_id 引用，转成卡牌 id） ---
    if kind == "hero":
        hp_id = source_data.dbf_to_id.get(card.get("hero_power_dbf"))
        if hp_id and hp_id != cid:
            entry["hero_power"] = hp_id
        buddy = source_data.dbf_to_id.get(card.get("companion_id"))
        if buddy:
            entry["buddy"] = buddy
    if card.get("spellcraft_id") is not None:
        spell_id = source_data.dbf_to_id.get(card["spellcraft_id"])
        if spell_id:
            entry["spellcraft"] = spell_id
    if card.get("reward_dbf_id") is not None:
        reward_id = source_data.dbf_to_id.get(card["reward_dbf_id"])
        if reward_id:
            entry["reward_card"] = reward_id
    if card.get("quest_progress_total") is not None:
        entry["quest_goal"] = card["quest_progress_total"]
    # --- golden / normal：triple_upgrade_id / triple_base_id（dbf→id） ---
    if card.get("triple_upgrade_id") is not None:
        entry["golden"] = source_data.dbf_to_id.get(card["triple_upgrade_id"], "")
    if card.get("triple_base_id") is not None:
        entry["normal"] = source_data.dbf_to_id.get(card["triple_base_id"], "")
    if text_alt:
        entry["text_alt"] = text_alt
    if text_alt_zh:
        entry["text_alt_zh"] = text_alt_zh
    # --- T2 继承：37 无等价来源、上游 36.6.3 有的“版本元数据”字段 ---
    at_card = at_by_id.get(cid)
    if at_card is not None:
        for name in ("prize_tier", "tw_types", "tw_weight", "tw_min_minions", "window"):
            if name in at_card and at_card[name] not in (None, [], 0):
                entry[name] = at_card[name]
        for pool in ("trinket", "timewarp"):
            if pool in at_card.get("pools", []) and pool not in entry["pools"]:
                entry["pools"].append(pool)
        entry["pools"] = [p for p in POOL_ORDER if p in entry["pools"]]
        entry["reachable"] = entry["reachable"] or bool(at_card.get("reachable"))
    lobby_req = lobby_req_of(kind, card)
    if lobby_req:
        entry["lobby_req"] = lobby_req
    return entry


def apply_t2_inheritance(
    entries: dict[str, dict],
    at_by_id: dict,
    source_data: SourceData,
) -> dict:
    """T2 继承补齐：中文文本对齐/补齐、golden/normal 目标缺失、lobby_req（ABERRATION 门控）。

    中文策略（详见 docs/DATA_37_MIGRATION.md §4）：`data/card_zhcn.json` 实测是
    36.2 时代的中文快照（没有 BG36 前缀、多处仍是旧机制/旧数值），与 37 英文逐字
    矛盾；而上游 36.6.3 bundle 的中文与英文同源。因此：当 37 英文文本与 36.6.3
    英文逐字一致时，**优先采用 36.6.3 中文**（`text_zh`/`text_alt_zh`），
    `card_zhcn.json` 仅作兜底（37 与 36.6.3 英文不一致的 7 张边界卡）。
    """
    stats = {
        "name_zh": 0,
        "text_zh_inherited": 0,
        "text_zh_aligned_replaced": 0,
        "text_alt_zh": 0,
        "golden": 0,
        "normal": 0,
        "lobby_req": 0,
    }
    for cid, entry in entries.items():
        at_card = at_by_id.get(cid)
        if at_card is None:          # 37 独有卡（不在上游 schema 内，理论上不会出现）
            continue
        # lobby_req：37 只能还原酒馆法术；上游 ABERRATION 门控只能继承（19 张）。
        if not entry.get("lobby_req") and at_card.get("lobby_req"):
            entry["lobby_req"] = list(at_card["lobby_req"])
            stats["lobby_req"] += 1
        # 中文名：37 中文表缺失时继承上游（名字跨版本极少变化；仅当缺失才补）。
        if not entry.get("name_zh") and at_card.get("name_zh"):
            entry["name_zh"] = at_card["name_zh"]
            stats["name_zh"] += 1
        # 英文文本与上游逐字一致 → 中文采用上游（与英文同源、比 card_zhcn 快照新）。
        aligned = bool(at_card.get("text") == entry.get("text"))
        if aligned and at_card.get("text_zh"):
            if entry.get("text_zh") != at_card["text_zh"]:
                if entry.get("text_zh"):
                    stats["text_zh_aligned_replaced"] += 1
                else:
                    stats["text_zh_inherited"] += 1
                entry["text_zh"] = at_card["text_zh"]
        elif not entry.get("text_zh") and at_card.get("text_zh"):
            entry["text_zh"] = at_card["text_zh"]
            stats["text_zh_inherited"] += 1
        # 中文变体文本与主文本同源：英文对齐时用上游的（上游没有就留空，
        # 避免混入旧版中文快照里的变体）；英文不对齐时保留 card_zhcn 的拆分结果。
        if aligned and at_card.get("text_zh"):
            if at_card.get("text_alt_zh"):
                if not entry.get("text_alt_zh"):
                    stats["text_alt_zh"] += 1
                entry["text_alt_zh"] = at_card["text_alt_zh"]
            else:
                entry.pop("text_alt_zh", None)
    # golden/normal 目标缺失时，用上游链接补齐（37 的 triple_* 目标卡可能只在 compat 里，
    # 实测：37 可解析的 1165 条 golden 链接与上游 100% 一致，所以补齐是安全的）。
    for cid, entry in entries.items():
        at_card = at_by_id.get(cid)
        if at_card is None:
            continue
        if not entry.get("golden") and at_card.get("golden"):
            entry["golden"] = at_card["golden"]
            stats["golden"] += 1
        if not entry.get("normal") and at_card.get("normal"):
            entry["normal"] = at_card["normal"]
            stats["normal"] += 1
    return stats


def apply_t3_mechanism_meta(entries: dict[str, dict], at_by_id: dict) -> dict:
    """T3：继承 AutoTavern 机制元数据（P2-B3）。

    对两版本共享的 mapped id，从 36.6.3 上游 `cards.json` 继承 AT 机制实现所依赖的
    客户端字段（见 `T3_EXACT_META`/`T3_INHERIT_META` 注释）。这些字段不改变 37 的
    数值/文本/原名；37 独有的卡（本迁移中只有不入库的异变/按钮）没有可继承值。

    返回逐字段统计（用于 MANIFEST `t3_inherited_meta`）：
      - at_non_default：上游该字段非默认值的共享 id 数；
      - applied：实际写入的上游值个数（含与 37 推导值相同的情况）；
      - changed：写入后与 37 推导值不同的个数；
      - already_equal：写入时 37 推导值已与上游一致的个数。
    """
    stats: dict[str, dict] = {}
    for field in T3_EXACT_META + T3_INHERIT_META:
        stats[field] = {"at_non_default": 0, "applied": 0, "changed": 0, "already_equal": 0}
    defaults = _at_field_defaults({})
    for cid, entry in entries.items():
        at_card = at_by_id.get(cid)
        if at_card is None:
            continue
        # (a) 客户端原始 tag：精确覆盖（pool_tag=0 也是有意义的“无此 tag”）
        stat = stats["pool_tag"]
        at_value = at_card.get("pool_tag", 0)
        stat["applied"] += 1
        if at_value:
            stat["at_non_default"] += 1
        if entry.get("pool_tag", 0) == at_value:
            stat["already_equal"] += 1
        else:
            stat["changed"] += 1
        entry["pool_tag"] = at_value
        # (b) 其余机制字段：上游有非默认值时才继承
        for field in T3_INHERIT_META:
            value = at_card.get(field)
            default = defaults.get(field)
            if value is None or value in (default, [], "", False):
                continue
            stat = stats[field]
            stat["at_non_default"] += 1
            # 文本变体只在与 37 文本逐字对齐时继承，避免把旧版变体贴到新版正文上
            if field == "text_alt" and entry.get("text") != at_card.get("text"):
                continue
            if field == "text_alt_zh" and entry.get("text_zh") != at_card.get("text_zh"):
                continue
            stat["applied"] += 1
            if entry.get(field) == value:
                stat["already_equal"] += 1
            else:
                stat["changed"] += 1
            entry[field] = list(value) if isinstance(value, list) else value
    return stats


def apply_dark_paradox(mapped: dict[str, dict]) -> dict:
    """Dark Paradox 特例（AT `flow.rs::PARADOX_VARIANTS`，P2-B3）。

    37 数据把 base `BG36_360` 标为池内卡、5 个形态 token 不标；但 AT 机制是“base 不入池、
    每局随机 1 个形态进池”。因此：base → `pools=[]`/`reachable=false`；
    5 个形态 → `pools=['minion']`/`reachable=true`（tier/攻血/文本保持 37 数据值，
    与 AT 的 tier 2/5/4/3/6 一致）。P1 内容移植阶段会改为 37 单卡动态机制。
    """
    info = {
        "base": PARADOX_BASE,
        "variants": [],
        "basis": "AutoTavern flow.rs::PARADOX_VARIANTS（base 不入池；每局随机 1 个形态进池）",
        "note": "37 源把 base 标为池内、token 不标；此处按 AT 机制约定映射，tier/数值保持 37 值",
    }
    base = mapped.get(PARADOX_BASE)
    if base is not None:
        base["pools"] = []
        base["reachable"] = False
        info["base_applied"] = True
    for cid, expected_tier in zip(PARADOX_VARIANTS, PARADOX_VARIANT_TIERS):
        entry = mapped.get(cid)
        if entry is None:
            continue
        entry["pools"] = ["minion"]
        entry["reachable"] = True
        info["variants"].append(
            {"id": cid, "tier": entry["tier"], "at_expected_tier": expected_tier}
        )
    return info


def _split_compat_text(raw: str) -> tuple[str, str]:
    """compat 文本拆分：上游 `cards.json` 里偶发残留 `@` 变体分隔符。

    36.6.3 只有 `JAIL_800hp2`（hero_power）一处：`... twice.@ ({0} left!)@ (Ready!)`。
    compat 条目要求“字段沿用上游”，所以这里只拆 `@` 分隔符（不替换占位符、不做
    其它清洗），保持其余文本与上游逐字一致；多余段（第 3 段起）丢弃。
    """
    if "@" not in (raw or ""):
        return raw or "", ""
    parts = _split_variants(raw)
    if len(parts) < 2:
        return raw, ""
    return parts[0], parts[1]


def make_compat_entry(at_card: dict) -> dict:
    """36.6.3 独有卡：字段沿用上游，但移出所有池子，避免 37 版本被“复活”。"""
    entry = dict(at_card)
    for field, alt_field in (("text", "text_alt"), ("text_zh", "text_alt_zh")):
        main, alt = _split_compat_text(entry.get(field) or "")
        entry[field] = main
        if alt and not entry.get(alt_field):
            entry[alt_field] = alt
    entry["pools"] = []
    entry["pool_tag"] = 0
    entry["reachable"] = False
    return canonical_entry(entry)


# ---------------------------------------------------------------------------
# 上游脚本 id 提取（引擎启动 panic 防护）
# ---------------------------------------------------------------------------

REG_RE = re.compile(r'\(\s*"([A-Za-z0-9_]+)"\s*,')
CARDID_LIT_RE = re.compile(r'cardid!\(\s*"([A-Za-z0-9_]+)"\s*\)')
CARDID_IDENT_RE = re.compile(r"cardid!\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
DB_ID_RE = re.compile(r'\.id\(\s*"([A-Za-z0-9_]+)"\s*\)')
TUPLE_IDENT_RE = re.compile(r"\(\s*([A-Z][A-Z0-9_]*)\s*,")
CONST_STR_RE = re.compile(r'const\s+([A-Z][A-Z0-9_]*)\s*:\s*&str\s*=\s*"([^"]+)"')
ID_LITERAL_RE = re.compile(r'"([A-Z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)"')


def extract_at_script_ids(at_root: Path) -> dict:
    """从上游 Rust 源码抽取会 `db().id(...)` 的卡牌 id。

    来源分类：
      - `registration`：content/*.rs 的脚本注册元组首元素（`("ID", Script)`）；
      - `registration_const`：注册位置用 `&str` 常量（解析常量值）；
      - `cardid`：`cardid!("ID")` / `cardid!(CONST)`（宏内部 `db().id(...)`，惰性调用）；
      - `db_id`：任意 `src/**/*.rs` 的 `.id("ID")`；
      - `content_literal`：content/*.rs 里所有“像卡牌 id”的字符串字面量（保守超集）。
    这些 id 必须全部能在生成的 cards_37.json 里解析，否则引擎启动 `registry()` panic。
    """
    at_src = at_root / AT_SRC_REL
    content = at_src / "content"
    if not content.is_dir():
        raise SystemExit(f"找不到上游源码目录: {content}")
    registration: set[str] = set()
    content_literal: set[str] = set()
    for path in sorted(content.glob("*.rs")):
        text = path.read_text(encoding="utf-8")
        registration |= set(REG_RE.findall(text))
        content_literal |= set(ID_LITERAL_RE.findall(text))
    consts: dict[str, str] = {}
    all_src = sorted(at_src.rglob("*.rs"))
    registration_const: set[str] = set()
    cardid_literals: set[str] = set()
    cardid_idents: set[str] = set()
    db_ids: set[str] = set()
    for path in all_src:
        text = path.read_text(encoding="utf-8")
        for name, value in CONST_STR_RE.findall(text):
            consts[name] = value
        cardid_literals |= set(CARDID_LIT_RE.findall(text))
        cardid_idents |= set(CARDID_IDENT_RE.findall(text))
        db_ids |= set(DB_ID_RE.findall(text))
    # 注册位置使用常量的情况：content 里 `(CONST, ...)` 且常量是 &str。
    for name in set(TUPLE_IDENT_RE.findall("\n".join(
        p.read_text(encoding="utf-8") for p in sorted(content.glob("*.rs"))
    ))):
        if name in consts:
            registration_const.add(consts[name])
    unresolved_consts = sorted(n for n in cardid_idents if n not in consts)
    cardid_const = {consts[n] for n in cardid_idents if n in consts}
    return {
        "registration": sorted(registration),
        "registration_const": sorted(registration_const),
        "cardid": sorted(cardid_literals | cardid_const),
        "db_id": sorted(db_ids),
        "content_literal": sorted(content_literal),
        "unresolved_const_idents": unresolved_consts,   # 非卡牌常量（如 TargetSpec ANY）
    }


# ---------------------------------------------------------------------------
# 差分（37 vs 上游 36.6.3）
# ---------------------------------------------------------------------------

DIFF_FIELDS = [
    "kind", "name", "name_zh", "tier", "atk", "hp", "armor", "cost",
    "races", "assoc", "keywords", "pools", "pool_tag", "reachable",
    "text", "text_zh", "text_alt", "text_alt_zh", "golden", "normal",
    "hero_power", "buddy", "spellcraft", "spellcraft_spell", "quest_goal",
    "reward_card", "window", "prize_tier", "tw_types", "tw_weight",
    "tw_min_minions", "lobby_req",
]
TOP_N = 12


def cross_validate(mapped: dict[str, dict], at_by_id: dict, source_data: SourceData) -> dict:
    """用 36.6.3 上游数据做映射质量交叉验证（共享 id 上的“应一致”字段）。"""
    shared = [cid for cid in mapped if cid in at_by_id]
    scalar_fields = ["name", "tier", "atk", "hp", "armor", "golden", "normal",
                     "pool_tag", "hero_power", "buddy", "spellcraft", "quest_goal",
                     "reward_card"]
    scalar = {}
    for name in scalar_fields:
        same = sum(
            1 for cid in shared
            if _diff_value(name, mapped[cid].get(name)) == _diff_value(name, at_by_id[cid].get(name))
        )
        scalar[name] = {"same": same, "total": len(shared)}
    set_fields = ["races", "assoc", "lobby_req", "keywords", "pools", "tw_types"]
    set_same = {}
    for name in set_fields:
        same = sum(
            1
            for cid in shared
            if _diff_value(name, mapped[cid].get(name)) == _diff_value(name, at_by_id[cid].get(name))
        )
        set_same[name] = {"same": same, "total": len(shared)}
    # 直接 flag → 关键词映射的精确率/召回（36.6.3 为参考真值）
    flag_precision = {}
    for flag, kw in FLAG_KEYWORDS:
        tp = fp = fn = 0
        for cid in shared:
            ours = kw in (mapped[cid].get("keywords") or [])
            theirs = kw in (at_by_id[cid].get("keywords") or [])
            if ours and theirs:
                tp += 1
            elif ours:
                fp += 1
            elif theirs:
                fn += 1
        flag_precision[kw] = {"tp": tp, "fp": fp, "fn": fn}
    # 文本：映射后英文文本与上游一致性（10 张差异均为已知边界，见 docs）
    text_same = sum(1 for cid in shared if mapped[cid].get("text") == at_by_id[cid].get("text"))
    text_zh_both = [cid for cid in shared if mapped[cid].get("text_zh") and at_by_id[cid].get("text_zh")]
    text_zh_same = sum(
        1 for cid in text_zh_both if mapped[cid].get("text_zh") == at_by_id[cid].get("text_zh")
    )
    return {
        "note": "以 36.6.3 上游 cards.json 为参照真值，统计 37 映射结果在共享 id 上的一致性",
        "scalar_fields": scalar,
        "set_fields": set_same,
        "flag_keyword_precision": flag_precision,
        "text_en": {"same": text_same, "total": len(shared),
                    "rate": round(text_same / len(shared), 5)},
        "text_zh": {
            "same": text_zh_same,
            "total": len(text_zh_both),
            "rate": round(text_zh_same / len(text_zh_both), 5) if text_zh_both else 0.0,
            "available_both": len(text_zh_both),
        },
    }


def _diff_value(field: str, value):
    """差异比较口径：列表字段按集合（顺序无语义）；可选字段缺失 = schema 默认值。"""
    if value is None:
        value = _at_field_defaults({}).get(field)
    if field in ("races", "assoc", "keywords", "pools", "lobby_req", "tw_types"):
        return sorted(value or [])
    return value


def compute_diff(mapped: dict[str, dict], at_by_id: dict) -> dict:
    """按字段统计 37 映射结果 vs 36.6.3 上游的差异（共享 id），并列 Top 变化。"""
    shared = [cid for cid in mapped if cid in at_by_id]
    by_kind_total: dict[str, int] = {}
    for cid in shared:
        kind = mapped[cid]["kind"]
        by_kind_total[kind] = by_kind_total.get(kind, 0) + 1
    fields: dict[str, dict] = {}
    for name in DIFF_FIELDS:
        changed_by_kind: dict[str, int] = {}
        examples: list[dict] = []
        detail: dict[str, int] = {}
        for cid in shared:
            ours = mapped[cid]
            theirs = at_by_id[cid]
            ours_v = _diff_value(name, ours.get(name))
            theirs_v = _diff_value(name, theirs.get(name))
            if ours_v == theirs_v:
                continue
            kind = ours["kind"]
            changed_by_kind[kind] = changed_by_kind.get(kind, 0) + 1
            if len(examples) < TOP_N:
                examples.append({"id": cid, "kind": kind, "old": theirs.get(name), "new": ours.get(name)})
            if isinstance(ours_v, list) and isinstance(theirs_v, list):
                for item in ours_v:
                    if item not in theirs_v:
                        detail["added_" + item] = detail.get("added_" + item, 0) + 1
                for item in theirs_v:
                    if item not in ours_v:
                        detail["dropped_" + item] = detail.get("dropped_" + item, 0) + 1
        if changed_by_kind:
            entry = {
                "changed": sum(changed_by_kind.values()),
                "by_kind": dict(sorted(changed_by_kind.items())),
                "examples": examples,
            }
            if detail:
                entry["detail"] = dict(sorted(detail.items()))
            fields[name] = entry
    removed = [cid for cid in at_by_id if cid not in mapped]
    removed_by_kind: dict[str, int] = {}
    removed_by_pool: dict[str, int] = {}
    for cid in removed:
        card = at_by_id[cid]
        removed_by_kind[card["kind"]] = removed_by_kind.get(card["kind"], 0) + 1
        for pool in card.get("pools") or []:
            removed_by_pool[pool] = removed_by_pool.get(pool, 0) + 1
    return {
        "shared_ids": len(shared),
        "shared_by_kind": dict(sorted(by_kind_total.items())),
        "removed_count": len(removed),
        "removed_by_kind": dict(sorted(removed_by_kind.items())),
        "removed_by_pool": dict(sorted(removed_by_pool.items())),
        "removed_ids": sorted(removed),
        "compare_note": "列表字段按集合比较（顺序无语义）；可选字段缺失等价 schema 默认值",
        "changed_fields": fields,
    }


# ---------------------------------------------------------------------------
# 渲染与 MANIFEST
# ---------------------------------------------------------------------------

def render_cards(cards: list[dict], meta: dict) -> str:
    """上游同款格式：meta 一行，随后一行一卡（diff 友好 + 确定性）。"""
    lines = ['{"meta":' + json.dumps(meta, ensure_ascii=False) + ',"cards":[']
    body = [json.dumps(card, ensure_ascii=False, separators=(",", ":")) for card in cards]
    lines.append(",\n".join(body))
    lines.append("]}")
    return "\n".join(lines) + "\n"


def dump_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def field_coverage(cards: list[dict]) -> dict:
    """各字段“非默认值”的覆盖率（分母 = 映射卡数）。"""
    mapped = len(cards)
    coverage: dict[str, dict] = {}
    for name in ALL_FIELDS:
        if name in REQUIRED_FIELDS:
            if name in ("races", "assoc", "keywords", "pools", "golden", "normal",
                        "text_zh", "pool_tag"):
                if name == "pool_tag":
                    non_default = sum(1 for c in cards if c.get("pool_tag"))
                else:
                    non_default = sum(1 for c in cards if c.get(name) not in (None, [], ""))
                coverage[name] = {"non_default": non_default, "total": mapped}
            continue
        default = _at_field_defaults({}).get(name)
        non_default = sum(
            1
            for c in cards
            if (v := c.get(name)) is not None and v != default and v != [] and v != ""
        )
        coverage[name] = {"non_default": non_default, "total": mapped}
    return coverage


# ---------------------------------------------------------------------------
# 构建主流程
# ---------------------------------------------------------------------------

def build(at_root: Path) -> dict:
    """构建全部产物（返回内存中的文本，便于 --check/--write 复用）。"""
    started = time.perf_counter()
    source_data = SourceData(DATA)
    at_meta, at_by_id = load_at_data(at_root)
    at_script_ids = extract_at_script_ids(at_root)

    # Duos-only 卡（P2-C 审计）：即便 37 池子文件给了 is_pool_* 标记，也剔除单人池。
    duos_only_ids = sorted(
        cid for cid, (source, obj) in source_data.entities.items()
        if kind_of(source, obj) is not None and is_duos_only(obj)
    )
    pool_file_ids = (
        set(source_data.pool_members["minion"])
        | set(source_data.pool_members["spell"])
        | set(source_data.pool_members["hero"])
    )
    duos_pool_exclusions = [cid for cid in duos_only_ids if cid in pool_file_ids]

    # ---- 1) 37 映射卡（T1），并登记被排除的 37 独有卡 ----
    mapped: dict[str, dict] = {}
    skipped: list[dict] = []
    for cid, (source, obj) in sorted(source_data.entities.items()):
        kind = kind_of(source, obj)
        if kind is None:
            reason = SKIPPED_CARD_TYPES.get(obj.get("card_type"), "unknown")
            skipped.append(
                {
                    "id": cid,
                    "dbf": obj.get("dbf_id"),
                    "card_type": obj.get("card_type"),
                    "name": obj.get("name") or "",
                    "reason": reason,
                }
            )
            continue
        mapped[cid] = build_card37(source, obj, source_data, at_by_id)
    # spellcraft 目标 → spellcraft_spell
    spellcraft_targets = {
        source_data.dbf_to_id[obj["spellcraft_id"]]
        for _src, obj in source_data.entities.values()
        if obj.get("spellcraft_id") is not None
        and obj["spellcraft_id"] in source_data.dbf_to_id
    }
    for cid, entry in mapped.items():
        if cid in spellcraft_targets:
            entry["spellcraft_spell"] = True

    # ---- 2) T2 继承补齐（中文/链接/lobby_req） ----
    t2_stats = apply_t2_inheritance(mapped, at_by_id, source_data)

    # ---- 2.5) T3 继承 AutoTavern 机制元数据（pool_tag/assoc/lobby_req/…；P2-B3） ----
    t3_stats = apply_t3_mechanism_meta(mapped, at_by_id)

    # Duos-only 卡在 T2/T3 之后强制移出所有池子/可达（防止上游继承把池子加回来）。
    for cid in duos_pool_exclusions:
        entry = mapped.get(cid)
        if entry is not None:
            entry["pools"] = []
            entry["pool_tag"] = 0
            entry["reachable"] = False

    # ---- 2.6) Dark Paradox 特例（AT flow.rs::PARADOX_VARIANTS，P2-B3） ----
    paradox_info = apply_dark_paradox(mapped)

    # ---- 3) compat：36.6.3 独有卡（避免 registry panic / 脚本解析失败） ----
    compat = {
        cid: make_compat_entry(at_card)
        for cid, at_card in at_by_id.items()
        if cid not in mapped
    }

    # ---- 4) 合并、排序、渲染 ----
    union: dict[str, dict] = dict(compat)
    union.update({cid: canonical_entry(entry) for cid, entry in mapped.items()})
    cards = [union[cid] for cid in sorted(union)]

    # ---- 5) 自检（失败直接退出，不允许产出坏数据） ----
    checks = run_self_checks(
        cards, mapped, compat, source_data, at_script_ids, at_by_id, skipped,
        duos_pool_exclusions, paradox_info,
    )
    checks["duos_only_ids"] = duos_only_ids
    checks["duos_pool_exclusions"] = duos_pool_exclusions

    # ---- 6) 差分统计（映射卡 vs 上游共享 id）+ 交叉验证 ----
    diff = compute_diff(mapped, at_by_id)
    cross = cross_validate(mapped, at_by_id, source_data)

    # ---- 7) 渲染产物 ----
    meta = {
        "client_version": CLIENT_VERSION,
        "server_patch": SERVER_PATCH,
        "source": SOURCE_DESC,
        "count": len(cards),
        "mapped_count": len(mapped),
        "compat_count": len(compat),
        "generator": f"HSBRSIM tools/p2_data/gen_carddb_37.py v{GEN_VERSION}",
        "at_baseline": f"{at_meta.get('client_version', '?')} ({at_meta.get('server_patch', '?')})",
    }
    cards_text = render_cards(cards, meta)

    new_cards = {
        "source_patch": CLIENT_VERSION,
        "note": (
            "37.0.0 数据中不存在于 AutoTavern(36.6.3) schema 的卡 id（全部为异变/UI 按钮，"
            "AutoTavern schema 无对应 kind，未进入 cards_37.json；供内容任务参考）"
        ),
        "count": len(skipped),
        "by_reason": _count_by(skipped, "reason"),
        "cards": skipped,
    }
    new_cards_text = dump_json(new_cards)

    script_ids_text = dump_json(
        {
            "source": "AutoTavern 36.6.3 Rust 源码（只读）",
            "purpose": (
                "引擎启动 src/script.rs::registry() 会对每个 content 脚本执行 db().id(id)，"
                "缺失 id 直接 panic；本清单内所有 id 均已包含在 cards_37.json（见 missing）"
            ),
            "counts": {
                "registration": len(at_script_ids["registration"]),
                "registration_const": len(at_script_ids["registration_const"]),
                "cardid": len(at_script_ids["cardid"]),
                "db_id": len(at_script_ids["db_id"]),
                "content_literal": len(at_script_ids["content_literal"]),
                "union": len(
                    set(at_script_ids["registration"])
                    | set(at_script_ids["registration_const"])
                    | set(at_script_ids["cardid"])
                    | set(at_script_ids["db_id"])
                ),
            },
            "unresolved_const_idents": at_script_ids["unresolved_const_idents"],
            "missing": checks["script_ids_missing"],
            "by_category": {
                "registration": at_script_ids["registration"],
                "registration_const": at_script_ids["registration_const"],
                "cardid": at_script_ids["cardid"],
                "db_id": at_script_ids["db_id"],
            },
            "content_literals": at_script_ids["content_literal"],
        }
    )

    manifest = build_manifest(
        mapped=mapped,
        compat=compat,
        cards=cards,
        meta=meta,
        diff=diff,
        cross=cross,
        checks=checks,
        t2_stats=t2_stats,
        at_meta=at_meta,
        source_data=source_data,
        at_script_ids=at_script_ids,
        at_cards_count=len(at_by_id),
        duos_pool_exclusions=duos_pool_exclusions,
        t3_stats=t3_stats,
        paradox_info=paradox_info,
        skipped=skipped,
        outputs={
            "cards_37.json": cards_text,
            "new_cards_37.json": new_cards_text,
            "at_scripted_ids.json": script_ids_text,
        },
    )
    manifest_text = dump_json(manifest)
    elapsed = time.perf_counter() - started
    return {
        "at_root": at_root,
        "meta": meta,
        "cards": cards,
        "mapped": mapped,
        "compat": compat,
        "skipped": skipped,
        "diff": diff,
        "cross": cross,
        "checks": checks,
        "t3_stats": t3_stats,
        "paradox_info": paradox_info,
        "t2_stats": t2_stats,
        "at_script_ids": at_script_ids,
        "outputs": {
            "cards_37.json": cards_text,
            "MANIFEST.json": manifest_text,
            "new_cards_37.json": new_cards_text,
            "at_scripted_ids.json": script_ids_text,
        },
        "elapsed": elapsed,
    }


def _count_by(items: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item[key]] = out.get(item[key], 0) + 1
    return dict(sorted(out.items()))


def build_manifest(**kw) -> dict:
    mapped: dict[str, dict] = kw["mapped"]
    compat: dict[str, dict] = kw["compat"]
    cards: list[dict] = kw["cards"]
    meta: dict = kw["meta"]
    diff: dict = kw["diff"]
    cross: dict = kw["cross"]
    checks: dict = kw["checks"]
    t2_stats: dict = kw["t2_stats"]
    at_meta: dict = kw["at_meta"]
    source_data: SourceData = kw["source_data"]
    at_script_ids: dict = kw["at_script_ids"]
    at_cards_count: int = kw["at_cards_count"]
    duos_pool_exclusions: list[str] = kw.get("duos_pool_exclusions") or []
    t3_stats: dict = kw.get("t3_stats") or {}
    paradox_info: dict = kw.get("paradox_info") or {}
    skipped: list[dict] = kw["skipped"]
    outputs: dict[str, str] = kw["outputs"]

    union_pool_counts = {
        pool: sum(1 for c in cards if pool in c.get("pools", [])) for pool in POOL_ORDER
    }
    kind_counts = {kind: sum(1 for c in cards if c["kind"] == kind) for kind in KINDS}
    mapped_kind_counts = {
        kind: sum(1 for c in mapped.values() if c["kind"] == kind) for kind in KINDS
    }
    compat_kind_counts = {
        kind: sum(1 for c in compat.values() if c["kind"] == kind) for kind in KINDS
    }
    provenance: dict[str, str] = {
        "id": "T1:37",
        "dbf": "T1:37",
        "kind": "T1:37(card_type/池子/flag)",
        "name": "T1:37",
        "name_zh": "T1:data/card_zhcn.json + T2:36.6.3 补齐",
        "tier": "T1:tech_level",
        "atk": "T1:atk",
        "hp": "T1:health",
        "armor": "T1:heroes.armor",
        "cost": "T1:cost",
        "races": "T1:card_race+race_tags",
        "assoc": "T1:subset_*(随从减去 races) + T3:36.6.3 精确继承",
        "keywords": "T1:flags + T1:文本规则(START_OF_COMBAT/STEALTH/END_OF_TURN_TRIGGER)",
        "golden": "T1:triple_upgrade_id + T2:链接目标缺失时用 36.6.3 补",
        "normal": "T1:triple_base_id + T2:同上",
        "pools": "T1:池子文件(minion/tier7/spell/hero，剔除 Duos-only) + T2:trinket/timewarp",
        "pool_tag": "T3:36.6.3 客户端 IS_BACON_POOL_MINION 原值（37 无权威值）",
        "reachable": "T1:池内为真 + T2:36.6.3 reachable",
        "text": "T1:37 text(占位符/变体/复数标记规范化)",
        "text_zh": "T2:36.6.3 中文(英文逐字一致时优先) + T1:card_zhcn 兜底",
        "text_alt": "T1:'@' 变体拆分 + T3:36.6.3(有变体且文本对齐时)",
        "text_alt_zh": "T2:36.6.3 中文变体 + T1:card_zhcn 兜底",
        "hero_power": "T1:hero_power_dbf + T3:36.6.3",
        "buddy": "T1:companion_id + T3:36.6.3",
        "spellcraft": "T1:spellcraft_id + T3:36.6.3",
        "spellcraft_spell": "T1:被 spellcraft 链接指向 + T3:36.6.3",
        "quest_goal": "T1:quest_progress_total + T3:36.6.3",
        "reward_card": "T1:reward_dbf_id + T3:36.6.3",
        "window": "T3:36.6.3",
        "prize_tier": "T3:36.6.3",
        "tw_types": "T2:36.6.3",
        "tw_weight": "T2:36.6.3",
        "tw_min_minions": "T2:36.6.3",
        "lobby_req": "T1:酒馆法术 subset_* + T3:36.6.3(ABERRATION 门控等)",
    }
    at_script_union = sorted(
        set(at_script_ids["registration"])
        | set(at_script_ids["registration_const"])
        | set(at_script_ids["cardid"])
        | set(at_script_ids["db_id"])
    )
    roundtrip = {name: sha256_text(text) for name, text in sorted(outputs.items())}
    return {
        "schema": SCHEMA_ID,
        "generator_version": GEN_VERSION,
        "meta": meta,
        "commands": {
            "generate": "python3 tools/p2_data/gen_carddb_37.py",
            "check": "python3 tools/p2_data/gen_carddb_37.py --check",
            "report": "python3 tools/p2_data/gen_carddb_37.py --report",
            "test": "python3 -m pytest tests/test_p2_data.py -q",
        },
        "source": {
            "hsbrsim_data_patch": source_data.summary.get("patch", CLIENT_VERSION),
            "hsbrsim_total_bg_cards": len(source_data.lists["bg_cards"]),
            "hsbrsim_pool_minions": len(source_data.lists["bg_pool_minions"]),
            "hsbrsim_pool_spells": len(source_data.lists["bg_pool_spells"]),
            "hsbrsim_pool_spells_single_player": (
                len(source_data.lists["bg_pool_spells"]) - len(duos_pool_exclusions)
            ),
            "hsbrsim_heroes": len(source_data.lists["bg_heroes"]),
            "hsbrsim_hero_powers": len(source_data.lists["bg_hero_powers"]),
            "hsbrsim_trinkets": len(source_data.lists["bg_trinkets"]),
            "hsbrsim_quest_rewards": len(source_data.lists["bg_quest_rewards"]),
            "hsbrsim_anomalies": len(source_data.lists["bg_anomalies"]),
            "hsbrsim_dark_gifts": len(source_data.lists["bg_dark_gifts"]),
            "hsbrsim_tavern_spells": len(source_data.lists["bg_tavern_spells"]),
            "hsbrsim_card_zhcn": len(source_data.zh),
            "at_baseline_client_version": at_meta.get("client_version"),
            "at_baseline_server_patch": at_meta.get("server_patch"),
            "at_cards_count": at_cards_count,
        },
        "counts": {
            "cards_total": len(cards),
            "mapped": len(mapped),
            "compat": len(compat),
            "skipped_37_only": len(skipped),
            "by_kind": kind_counts,
            "mapped_by_kind": mapped_kind_counts,
            "compat_by_kind": compat_kind_counts,
            "skipped_by_reason": _count_by(skipped, "reason"),
            "pools": union_pool_counts,
            "pools_single_player": union_pool_counts,
        },
        "pool_scope": {
            "note": (
                "单人池口径：37 池子文件给的是“客户端池子标记”。已按 P2-C 审计剔除 3 张"
                "Duos-only 法术；并按 AT 机制（flow.rs::PARADOX_VARIANTS）修正 Dark Paradox："
                "base BG36_360 不入池（−1）、5 个形态入池（+5）。36.6.3 上游同 id 的 "
                "pools/reachable 与这两种修正一致"
            ),
            "raw_pool_files": {
                "minion": len(source_data.lists["bg_pool_minions"]),
                "spell": len(source_data.lists["bg_pool_spells"]),
                "hero": len(source_data.lists["bg_heroes"]),
            },
            "effective_single_player": union_pool_counts,
            "dark_paradox": paradox_info,
            "excluded_duos_only": {
                "ids": sorted(duos_pool_exclusions),
                "count": len(duos_pool_exclusions),
                "rule": (
                    "文本拆分后没有第二段（无单人变体）且匹配 "
                    "/(?i)\\bteammate\\b|\\bpass (?:a|an|one)\\b/"
                ),
                "evidence": [
                    "docs/PORTING_37_PLAN.md §2.4（P2-C 审计）/ §4.5",
                    "36.6.3 上游 cards.json 中 BG31_242/243/244 均为 pools=[]、reachable=false",
                    "这 3 张在 37 与 36.6.3 数据中都没有金卡形式（无 _G id）",
                ],
            },
        },
        "field_provenance": provenance,
        "field_coverage": field_coverage([canonical_entry(m) for m in mapped.values()]),
        "t2_inherited": {
            "fields": INHERITED_FIELDS,
            "counts": t2_stats,
        },
        "t3_inherited_meta": {
            "note": (
                "AutoTavern 机制实现依赖的“客户端元数据”；37 官方数据没有权威等价来源，"
                "对两版本共享 id 从 36.6.3 上游 cards.json 继承（不改变 37 数值/文本/原名）。"
                "pool_tag 为精确继承（含 0 值），其余字段仅在上游有非默认值时继承；"
                "text_alt/text_alt_zh 还要求与 37 文本/中文逐字对齐（避免错贴变体）。"
            ),
            "source": "AutoTavern 36.6.3 cards.json（crates/taverngym/data/cards.json，只读）",
            "shared_mapped_ids": len(mapped),
            "exact_fields": list(T3_EXACT_META),
            "inherit_when_at_non_default_fields": list(T3_INHERIT_META),
            # 每个字段: at_non_default(上游有值 id 数) / applied(实际写入) /
            # changed(与 37 推导值不同) / already_equal / coverage(applied/共享 mapped)
            "fields": {
                field: dict(
                    stat,
                    coverage=round(stat["applied"] / max(len(mapped), 1), 6),
                )
                for field, stat in t3_stats.items()
            },
        },
        "mechanism_meta": {
            "note": "Rust 引擎机制断言所需的派生计数（可直接对照 cards.rs/mechanics.rs 测试）",
            "pool_counts": union_pool_counts,
            "strict_pool_tag_eligible_minions": {
                "filter": "pools.minion && pool_tag <= 1（strict_pool_tag 默认 true）",
                "count": sum(
                    1 for c in cards if "minion" in c.get("pools", []) and c["pool_tag"] <= 1
                ),
            },
            "pool_tag_gt_1_ids": sorted(
                c["id"] for c in cards if c["pool_tag"] > 1
            ),
            "dark_paradox": paradox_info,
            "lobby_req_non_default_count": sum(
                1 for c in cards if c.get("lobby_req")
            ),
            "lobby_req_ids": sorted(c["id"] for c in cards if c.get("lobby_req")),
        },
        "unmapped": {
            "note": "37 数据没有来源、且上游也没有的字段一律省略（Rust serde default），不编造",
            "fields": [
                {
                    "field": "kind:anomaly/ui_button",
                    "reason": "AutoTavern CardKind 只有 10 个取值，不含异变/UI 按钮",
                    "count": len(skipped),
                },
                {
                    "field": "keywords:AURA/TRIGGER_VISUAL/DISCOVER",
                    "reason": "37 无对应布尔 flag；文本启发式误报率高（DISCOVER 精确率 16%），不映射",
                },
                {
                    "field": "quest_goal 的奖励计数",
                    "reason": "37 只有 quest_progress_total（任务目标），奖励计数无来源",
                },
                {
                    "field": "lobby_req:ABERRATION",
                    "reason": "37 数据无 subset_aberration；19 张共享卡用 T2 从 36.6.3 继承",
                },
                {
                    "field": "text_alt 第 3 段及以后",
                    "reason": "上游 schema 只有一段 text_alt；多段变体只保留前两段",
                },
                {
                    "field": "|4(...) 复数标记（无前置数字时）",
                    "reason": "无法判定单复数，按复数渲染",
                },
            ],
        },
        "diff_vs_at_36_6_3": diff,
        "cross_validation_vs_at_36_6_3": cross,
        "script_ids": {
            "extracted": "AutoTavern src/content/*.rs 注册元组 + src/**/*.rs 的 cardid!/.id()",
            "counts": {
                "registration": len(at_script_ids["registration"]),
                "registration_const": len(at_script_ids["registration_const"]),
                "cardid": len(at_script_ids["cardid"]),
                "db_id": len(at_script_ids["db_id"]),
                "union": len(at_script_union),
            },
            "missing": checks["script_ids_missing"],
            "unresolved_const_idents": at_script_ids["unresolved_const_idents"],
        },
        "checks": checks,
        "outputs_sha256": roundtrip,
    }


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def run_self_checks(
    cards, mapped, compat, source_data, at_script_ids, at_by_id, skipped,
    duos_pool_exclusions=(), paradox_info=None,
) -> dict:
    problems: list[str] = []
    ids = [c["id"] for c in cards]
    if len(ids) != len(set(ids)):
        problems.append("卡 id 重复")
    if ids != sorted(ids):
        problems.append("卡未按 id 排序")
    id_set = set(ids)

    # 1) kind 合法 & 计数
    kind_counts: dict[str, int] = {}
    for card in cards:
        if card["kind"] not in KINDS:
            problems.append(f"{card['id']}: 非法 kind {card['kind']}")
        kind_counts[card["kind"]] = kind_counts.get(card["kind"], 0) + 1

    # 2) 37 池内卡全覆盖（Duos-only 按 P2-C 审计剔除；Dark Paradox 按 AT 机制特例修正）
    duos_excluded = set(duos_pool_exclusions)
    expected_minions = (
        set(source_data.pool_members["minion"]) - {PARADOX_BASE}
    ) | set(PARADOX_VARIANTS)
    for cid in expected_minions:
        if cid not in mapped:
            problems.append(f"池内随从未映射: {cid}")
        elif cid in duos_excluded:
            if mapped[cid]["pools"] or mapped[cid]["reachable"] or mapped[cid]["pool_tag"]:
                problems.append(f"Duos-only 卡仍在单人池: {cid}")
        elif "minion" not in mapped[cid]["pools"]:
            problems.append(f"池内随从缺少 minion 池标记: {cid}")
    # Dark Paradox：base 不入池；5 形态入池且 tier 与 AT 约定一致、通过 strict_pool_tag 过滤
    base = mapped.get(PARADOX_BASE)
    if base is not None and (base["pools"] or base["reachable"]):
        problems.append(f"Dark Paradox base {PARADOX_BASE} 不应在池子/可达")
    for cid, expected_tier in zip(PARADOX_VARIANTS, PARADOX_VARIANT_TIERS):
        entry = mapped.get(cid)
        if entry is None:
            problems.append(f"Dark Paradox 形态未映射: {cid}")
            continue
        if "minion" not in entry["pools"] or not entry["reachable"]:
            problems.append(f"Dark Paradox 形态未标池内: {cid}")
        if entry["tier"] != expected_tier:
            problems.append(f"Dark Paradox 形态 tier 不符: {cid} {entry['tier']}≠{expected_tier}")
        if entry["pool_tag"] > 1:
            problems.append(f"Dark Paradox 形态被 strict_pool_tag 过滤: {cid} pool_tag={entry['pool_tag']}")
    for cid in source_data.pool_members["spell"]:
        if cid not in mapped:
            problems.append(f"池内法术未映射: {cid}")
        elif cid in duos_excluded:
            if mapped[cid]["pools"] or mapped[cid]["reachable"]:
                problems.append(f"Duos-only 池法术未剔除: {cid}")
        elif "spell" not in mapped[cid]["pools"]:
            problems.append(f"池内法术缺少 spell 池标记: {cid}")
    for cid in source_data.pool_members["hero"]:
        if cid not in mapped or "hero" not in mapped[cid]["pools"]:
            problems.append(f"英雄缺少 hero 池标记: {cid}")

    # 2.5) 全卡库文本不得残留 '@' 变体分隔符（P2-C 审计项：JAIL_800hp2）
    for card in cards:
        for field in ("text", "text_alt", "text_zh", "text_alt_zh"):
            if "@" in (card.get(field) or ""):
                problems.append(f"{card['id']}: {field} 残留 '@' 分隔符")

    # 3) 合法域：tier 0..7、atk/hp >= 0、pool_tag 0..2、race 词表内
    valid_races = set(RACE_BY_VALUE.values())
    for card in cards:
        if not 0 <= card["tier"] <= 7:
            problems.append(f"{card['id']}: tier 越界 {card['tier']}")
        if card["atk"] < 0 or card["hp"] < 0:
            problems.append(f"{card['id']}: 负属性")
        if card["pool_tag"] > 2:
            problems.append(f"{card['id']}: pool_tag 越界")
        for race in card["races"] + card["assoc"] + card.get("lobby_req", []):
            if race not in valid_races:
                problems.append(f"{card['id']}: 非法种族 {race}")

    # 4) 无悬空引用（golden/normal/hero_power/buddy/spellcraft/reward_card）
    for card in cards:
        for name in ("golden", "normal", "hero_power", "buddy", "spellcraft", "reward_card"):
            ref = card.get(name)
            if ref and ref not in id_set:
                problems.append(f"{card['id']}: {name} 指向不存在的卡 {ref}")
        if card.get("golden") and card["golden"] == card["id"]:
            problems.append(f"{card['id']}: golden 自引用")
        if card.get("normal") and card["normal"] == card["id"]:
            problems.append(f"{card['id']}: normal 自引用")

    # 5) golden/normal 双向自洽（映射卡与 compat 都检查）
    by_id = {c["id"]: c for c in cards}
    for card in cards:
        golden = card.get("golden")
        if golden:
            target = by_id[golden]
            if target.get("normal") != card["id"]:
                problems.append(f"{card['id']}: golden→{golden} 但后者 normal={target.get('normal')!r}")
    for card in cards:
        normal = card.get("normal")
        if normal:
            target = by_id[normal]
            if target.get("golden") != card["id"]:
                problems.append(f"{card['id']}: normal→{normal} 但后者 golden={target.get('golden')!r}")

    # 6) 上游字段类型一致性（与 Rust RawCard 的 serde 类型逐字段核对）
    type_checks = {
        "id": str, "dbf": int, "kind": str, "name": str, "name_zh": str,
        "tier": int, "atk": int, "hp": int, "armor": int, "cost": int,
        "races": list, "assoc": list, "keywords": list, "golden": str,
        "normal": str, "pools": list, "text": str, "text_zh": str,
        "pool_tag": int, "reachable": bool,
    }
    optional_types = {
        "hero_power": str, "buddy": str, "prize_tier": int, "reward_card": str,
        "quest_goal": int, "spellcraft_spell": bool, "spellcraft": str,
        "window": list, "tw_types": list, "tw_weight": int, "tw_min_minions": int,
        "text_alt": str, "text_alt_zh": str, "lobby_req": list,
    }
    for card in cards:
        for name, typ in type_checks.items():
            if name not in card:
                problems.append(f"{card['id']}: 缺必填字段 {name}")
            elif not isinstance(card[name], typ):
                problems.append(f"{card['id']}: 字段 {name} 类型 {type(card[name]).__name__}≠{typ.__name__}")
        for name, typ in optional_types.items():
            if name in card and not isinstance(card[name], typ):
                problems.append(f"{card['id']}: 可选字段 {name} 类型错误")
        for name in ("races", "assoc", "keywords", "pools"):
            if not all(isinstance(x, str) for x in card[name]):
                problems.append(f"{card['id']}: {name} 含非字符串元素")
        if "window" in card:
            window = card["window"]
            if not (isinstance(window, list) and len(window) == 2):
                problems.append(f"{card['id']}: window 结构错误 {window!r}")

    # 7) compat 条目：不参与池子
    for cid, entry in compat.items():
        if entry["pools"] or entry["reachable"] or entry["pool_tag"]:
            problems.append(f"compat 条目仍在池子/可达: {cid}")

    # 8) 上游脚本 id 全部可解析（引擎 registry() panic 防护）
    at_script_union = sorted(
        set(at_script_ids["registration"])
        | set(at_script_ids["registration_const"])
        | set(at_script_ids["cardid"])
        | set(at_script_ids["db_id"])
    )
    missing = [cid for cid in at_script_union if cid not in id_set]
    # content 里所有“像卡 id”的字面量里，只有出现在上游库里的才要求可解析（前缀匹配等除外）
    content_literals = at_script_ids["content_literal"]
    missing_literals = [
        cid for cid in content_literals if cid in at_by_id and cid not in id_set
    ]

    checks = {
        "problems": problems,
        "ok": not problems,
        "counts": {
            "cards": len(cards),
            "kinds": dict(sorted(kind_counts.items())),
            "mapped": len(mapped),
            "compat": len(compat),
            "skipped_37_only": len(skipped),
        },
        "pool_coverage": {
            "minion": sum(
                1 for cid in expected_minions
                if cid in mapped and cid not in duos_excluded
            ),
            "spell": sum(
                1 for cid in source_data.pool_members["spell"]
                if cid in mapped and cid not in duos_excluded
            ),
            "hero": sum(1 for cid in source_data.pool_members["hero"] if cid in mapped),
            "trinket": sum(1 for cid in source_data.pool_members["trinket"] if cid in mapped),
        },
        "duos_only": sorted(duos_excluded),
        "paradox": paradox_info or {},
        "pool_eligible_strict": {
            "filter": "pools.minion && pool_tag <= 1（Rust strict_pool_tag 默认开启）",
            "count": sum(
                1 for c in cards if "minion" in c["pools"] and c["pool_tag"] <= 1
            ),
            "excluded_ids": sorted(
                c["id"] for c in cards if "minion" in c["pools"] and c["pool_tag"] > 1
            ),
        },
        "script_ids_checked": len(at_script_union),
        "script_ids_missing": missing,
        "content_literals_missing": missing_literals,
    }
    if missing:
        problems.append(f"上游脚本 id 无法解析: {missing[:10]}")
        checks["ok"] = False
    if missing_literals:
        problems.append(f"content 字面量无法解析: {missing_literals[:10]}")
        checks["ok"] = False
    return checks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def report(build_result: dict) -> None:
    meta = build_result["meta"]
    mapped = build_result["mapped"]
    compat = build_result["compat"]
    skip = build_result["skipped"]
    diff = build_result["diff"]
    checks = build_result["checks"]
    outputs = build_result["outputs"]
    print("=" * 78)
    print(f"37.0.0.255130 → AutoTavern schema（生成器 v{GEN_VERSION}）")
    print("=" * 78)
    print(f"meta: client_version={meta['client_version']} server_patch={meta['server_patch']}")
    print(f"      count={meta['count']} mapped={meta['mapped_count']} compat={meta['compat_count']}")
    print(f"37 独有但 schema 不收录: {len(skip)} 张 {_count_by(skip, 'reason')}")
    print()
    print("kind 计数（映射 / compat / 合计）:")
    for kind in KINDS:
        m = sum(1 for c in mapped.values() if c["kind"] == kind)
        cp = sum(1 for c in compat.values() if c["kind"] == kind)
        print(f"  {kind:16s} {m:5d} + {cp:4d} = {m + cp:5d}")
    print()
    union_pools = {
        pool: sum(1 for c in build_result["cards"] if pool in c.get("pools", []))
        for pool in POOL_ORDER
    }
    print("  池子成员（并集）:", union_pools)
    duos = build_result["checks"]["duos_pool_exclusions"]
    print(f"  Duos-only 剔除（P2-C 审计）: {len(duos)} 张 {duos}")
    paradox = build_result.get("paradox_info") or {}
    variants = [v["id"] for v in paradox.get("variants", [])]
    print(f"  Dark Paradox（AT flow.rs 机制）: base={paradox.get('base')} 不入池, "
          f"形态 {len(variants)} 个入池 {variants}")
    eligible = build_result["checks"]["pool_eligible_strict"]
    print(f"  strict_pool_tag 过滤后池内随从（pools.minion && pool_tag<=1）: "
          f"{eligible['count']}；pool_tag>1: {eligible['excluded_ids']}")
    print()
    print("差分 vs 上游 36.6.3:")
    print(f"  共享 id: {diff['shared_ids']}  上游独有(compat): {diff['removed_count']}")
    print(f"  37 独有(不收录): {len(skip)}")
    print("  字段变化（共享 id）:")
    for name, stat in diff["changed_fields"].items():
        print(f"    {name:16s} {stat['changed']:5d}  {stat['by_kind']}")
    print()
    t3 = build_result.get("t3_stats") or {}
    if t3:
        applied = {f: v["changed"] for f, v in t3.items() if v["changed"]}
        print("T3 继承 AT 机制元数据（changed 计数）:", applied)
    print("上游脚本 id 解析:")
    ids = build_result["at_script_ids"]
    print(
        f"  registration={len(ids['registration'])} +const={len(ids['registration_const'])} "
        f"cardid={len(ids['cardid'])} db_id={len(ids['db_id'])}"
    )
    print(f"  检查 {checks['script_ids_checked']} 个 id → missing={len(checks['script_ids_missing'])}")
    print(f"  未解析非卡牌常量: {ids['unresolved_const_idents']}")
    print()
    print("产物:")
    for name, text in sorted(outputs.items()):
        print(f"  {name}: {len(text.encode('utf-8')) // 1024} KiB sha256={sha256_text(text)[:16]}…")
    print(f"自检: {'OK' if checks['ok'] else 'FAILED'}")
    if not checks["ok"]:
        for problem in checks["problems"][:20]:
            print("  -", problem)
    print(f"耗时: {build_result['elapsed']:.2f}s")


def write_outputs(build_result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in build_result["outputs"].items():
        path = out_dir / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)


def check_outputs(build_result: dict, out_dir: Path) -> int:
    problems: list[str] = []
    if not build_result["checks"]["ok"]:
        problems.append("自检失败: " + "; ".join(build_result["checks"]["problems"][:5]))
    meta = build_result["meta"]
    if meta["client_version"] != CLIENT_VERSION:
        problems.append(f"meta.client_version 错误: {meta['client_version']!r}")
    if meta["server_patch"] != SERVER_PATCH:
        problems.append(f"meta.server_patch 错误: {meta['server_patch']!r}")
    for name, text in build_result["outputs"].items():
        path = out_dir / name
        if not path.is_file():
            problems.append(f"缺少产物 {path}")
            continue
        if path.read_text(encoding="utf-8") != text:
            problems.append(f"{path} 与重算结果不一致（重新生成）")
    if problems:
        print("--check FAILED:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("--check OK: 全部产物与重算结果 byte-identical，meta/计数/脚本 id 校验通过")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="37.0.0.255130 → AutoTavern schema 生成器")
    parser.add_argument("--check", action="store_true", help="校验已入库产物是否与重算一致")
    parser.add_argument("--report", action="store_true", help="只打印统计，不写文件")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录（默认 data/p2）")
    parser.add_argument("--at-root", type=Path, default=DEFAULT_AT_ROOT,
                        help="只读的 AutoTavern 仓库路径")
    args = parser.parse_args(argv)

    result = build(args.at_root)
    if args.report:
        report(result)
        return 0
    if args.check:
        return check_outputs(result, args.out)
    if not result["checks"]["ok"]:
        report(result)
        print("自检失败，拒绝写出产物", file=sys.stderr)
        return 1
    write_outputs(result, args.out)
    report(result)
    print(f"已写出: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
