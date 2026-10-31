#!/usr/bin/env python3
"""缩放载体（spell-scaling carrier）公共库：识别 / 追踪 / rollout / 汇总。

**载体的定义**：把「施放法术」转成**永久身材（或等价复利）**的随从。
不是只有 ``cast a spell on this`` 那一类——引擎内容脚本里监听 ``ev::SPELL_CAST``
的随从共 12 张在池内（含 ``whenever you cast a Tavern spell`` 的 Hooktail /
Living Azerite / Forsaken Weaver），本库把它们全部登记：

============  ==============================================  ======  ==========
触发类        含义                                            例子     池内张数
============  ==============================================  ======  ==========
cast_on_self  「每当**对本随从**施放法术」                      Distractor  3(+金)
cast_on_race  「每当对**某类型随从**施放法术」                 Tidecaller  2(+金)
cast_on_minion「每当对**一个随从**施放法术」                   Wrangler    0
cast_tavern   「每当/之后你施放**酒馆法术**」                  Hooktail    4(+金)
cast_any      「每当/之后你施放（任意）法术」                  Felboar     1(+金)
after_n       「施放 N 个法术后」                              Felboar     1(+金)
============  ==============================================  ======  ==========

数据源（双重取证，两者都写进 ``data/scaling/carriers.json``）：

1. **卡表** ``rust/crates/hsbg-engine/data/cards.json``：按 ``text``/``text_zh`` 正则；
2. **内容脚本** ``rust/crates/hsbg-engine/src/content/*.rs``：扫描含
   ``listens: ev::SPELL_CAST`` 的 ``Script { ... }`` 块，取块前的卡 id。
3. **运行时可用性** ``hsbg_engine.catalog_json()`` 的 ``in_pool`` / ``implemented``
   / ``tier``（内容模式 ``Implemented`` 会剔掉没实现的卡）。

主集合（``primary``）= 池内 + 已实现 + tier<=6 + 成长（+身材/永久 buff）。
文档口径的窄集合（``narrow``）= 5 张 ``cast a spell on this`` + Felboar
（``docs/SCALING_SIGNAL.md`` §2.3），用于复现 6–9% 的历史读数。

本模块只读：不改引擎、不训练、不写 checkpoint。

用法见 ``scripts/carrier_audit.py`` / ``scripts/carrier_teacher.py``。
"""

from __future__ import annotations

import glob
import json
import os
import random
import re
import sys
import time
import traceback

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CARDS_JSON = os.path.join(ROOT, "rust/crates/hsbg-engine/data/cards.json")
CONTENT_DIR = os.path.join(ROOT, "rust/crates/hsbg-engine/src/content")
CATALOG_OUT = os.path.join(ROOT, "data/scaling/carriers.json")
ROLLOUT_DIR = os.path.join(ROOT, "runs/scaling_carrier/rollouts")

# ── 动作布局（与 rust/crates/hsbg-engine/src/actions.rs 一致）─────────────────
A_END = 0
A_REFRESH = 1
A_FREEZE = 2
A_UPGRADE = 3
A_HERO_POWER = 4
A_CANCEL = 7
A_BUY = 8
A_BUY_END = 16
A_SELL = 16
A_SELL_END = 23
A_ACTIVATE = 23
A_ACTIVATE_END = 30
A_CHOOSE = 30
A_CHOOSE_END = 46
A_PLAY = 46
A_PLAY_END = 126
A_MAGNETIZE = 126
A_MAGNETIZE_END = 196
A_MOVE = 196
A_MOVE_END = 245
N_POS = 8
N_BOARD = 7
N_CHOICE = 16
SPELL_KINDS = ("tavern_spell", "spell")

#: 文档（docs/SCALING_SIGNAL.md §2.3）的窄口径：5 张 cast-a-spell-on-this + Felboar
NARROW_IDS = (
    "BG36_762", "BG36_762_G",
    "BG36_703", "BG36_703_G",
    "BG36_640", "BG36_640_G",
    "BG36_510", "BG36_510_G",
    "BG36_921", "BG36_921_G",
    "BG28_633", "BG28_633_G",
)

#: 文本里带「施法」但**不在施法瞬间成长**的卡：死亡之声/战斗开始按施法数改进，
#: 不是「载体」（不产生每回合复利），单独排除。
NON_CARRIER_IDS = {
    "BG36_318", "BG36_318_G",   # Faceless Converter（死亡之声按本局施法数改进）
    "BG32_822", "BG32_822_G",   # Fire-forged Evoker（战斗开始，按施法数永久改进）
}

# ── 人工登记：每施法一次的等价收益（引擎内容脚本逐条核对）────────────────────
# sigma_* = 期望 Σ(atk+hp) 增量；assumption 写明估算假设，绝不假装是精确值。
CARRIER_SPECS = {
    # ---- 池内主集合（tier<=6）------------------------------------------------
    "BG36_762": {
        "trigger": "cast_on_self", "effect": "tavern_minions_buff_this_game",
        "per_cast": {"atk": 1, "hp": 2}, "per_cast_golden": {"atk": 2, "hp": 4},
        "unit": "tavern_minion", "sigma": 15.0, "sigma_golden": 30.0,
        "compounding": True, "priority": 10,
        "assumption": "按酒馆 5 只随从计：5×3 Σ/次（本局永久，之后买到的酒馆随从也受益）",
        "note": "唯一的跨回合永久复利引擎：法术越多 → 之后买到的随从越强",
    },
    "BG28_707": {
        "trigger": "cast_tavern", "effect": "tavern_elementals_buff_this_game",
        "per_cast": {"atk": 4, "hp": 3}, "per_cast_golden": {"atk": 4, "hp": 3},
        "unit": "tavern_elemental", "sigma": 21.0, "sigma_golden": 42.0,
        "compounding": True, "priority": 9,
        "assumption": "按酒馆 3 只元素计：3×7 Σ/次；金色触发两次等价于翻倍",
        "note": "无需目标：任意酒馆法术都触发，且是“本局”永久",
    },
    "BG28_633": {
        "trigger": "after_n_spells", "effect": "consume_tavern_minion_every_3",
        "per_cast": None, "per_cast_golden": None,
        "unit": "tavern_minion_stats/3", "sigma": 4.0, "sigma_golden": 8.0,
        "compounding": True, "priority": 8,
        "assumption": "每 3 次施法吞一只酒馆随从（≈12 Σ）→ ≈4 Σ/次",
        "note": "Felboar：任意法术计数（不要求打在自己身上）",
    },
    "BG36_704": {
        "trigger": "cast_on_race", "race": "MURLOC",
        "effect": "murlocs_hand_and_board_buff",
        "per_cast": {"atk": 3, "hp": 3}, "per_cast_golden": {"atk": 6, "hp": 6},
        "unit": "murloc", "sigma": 18.0, "sigma_golden": 36.0,
        "compounding": True, "priority": 7,
        "assumption": "场+手按 3 只鱼人计：3×6 Σ/次；自己就是鱼人，可直接点名自己",
        "note": "对任意鱼人施法都触发；目标可以是自己",
    },
    "BG34_692": {
        "trigger": "cast_tavern", "effect": "undead_attack_this_game",
        "per_cast": {"atk": 3, "hp": 0}, "per_cast_golden": {"atk": 6, "hp": 0},
        "unit": "undead", "sigma": 9.0, "sigma_golden": 18.0,
        "compounding": True, "priority": 6,
        "assumption": "按 3 只亡灵计：3×3 Σ/次（本局永久攻击力）",
        "note": "任意酒馆法术触发；“wherever they are” 对之后召回的亡灵也生效",
    },
    "BG36_640": {
        "trigger": "cast_on_self", "effect": "casts_misplaced_tea_set",
        "per_cast": {"atk": 4, "hp": 4}, "per_cast_golden": {"atk": 4, "hp": 4},
        "unit": "distinct_type_minion", "sigma": 32.0, "sigma_golden": 64.0,
        "compounding": True, "priority": 3,
        "assumption": "Misplaced Tea Set = 每类型随从 +4/+4；按 4 个类型计 32 Σ/次（金色两次）",
        "note": "tier6，太晚；但全场类型越多收益越大",
    },
    "BG36_703": {
        "trigger": "cast_on_self", "effect": "leftmost_hand_minion_buff",
        "per_cast": {"atk": 8, "hp": 8}, "per_cast_golden": {"atk": 16, "hp": 16},
        "unit": "hand_minion", "sigma": 16.0, "sigma_golden": 32.0,
        "compounding": False, "priority": 5,
        "assumption": "手牌最左随从 +8/+8 = 16 Σ/次（金色 32）",
        "note": "要求手上有随从，且要打在自己身上",
    },
    "BG36_853": {
        "trigger": "cast_on_race", "race": "MECHANICAL",
        "effect": "magnetize_satellite",
        "per_cast": {"atk": 4, "hp": 4}, "per_cast_golden": {"atk": 4, "hp": 4},
        "unit": "self", "sigma": 8.0, "sigma_golden": 16.0,
        "compounding": False, "priority": 4,
        "assumption": "磁力 4/4 = 8 Σ/次（金色两次）；目标须是机械（可以是自己）",
        "note": "",
    },
    "BG27_005": {
        "trigger": "cast_tavern", "effect": "board_attack_buff",
        "per_cast": {"atk": 1, "hp": 0}, "per_cast_golden": {"atk": 1, "hp": 0},
        "unit": "board_minion", "sigma": 7.0, "sigma_golden": 14.0,
        "compounding": False, "priority": 6,
        "assumption": "全场 7 只随从 +1 攻 = 7 Σ/次（金色触发两次）",
        "note": "**tier 3**：最容易上手的载体，不需要目标，任意酒馆法术触发",
    },
    "BG28_741": {
        "trigger": "cast_tavern", "effect": "divine_shield_attack_buff",
        "per_cast": {"atk": 4, "hp": 0}, "per_cast_golden": {"atk": 8, "hp": 0},
        "unit": "divine_shield_minion", "sigma": 8.0, "sigma_golden": 16.0,
        "compounding": False, "priority": 2,
        "assumption": "按 2 只圣盾随从计：2×4 Σ/次",
        "note": "需要场上有圣盾随从，条件最苛刻",
    },
    "BG36_108": {
        "trigger": "cast_tavern", "effect": "self_and_deity_buff",
        "per_cast": {"atk": 1, "hp": 2}, "per_cast_golden": {"atk": 2, "hp": 4},
        "unit": "self", "sigma": 3.0, "sigma_golden": 6.0,
        "compounding": False, "priority": 2,
        "assumption": "自身 +1/+2 = 3 Σ/次（另加神明，未计）",
        "note": "只在异变/神明大厅可得；tier 3",
    },
    "BG36_111": {
        "trigger": "cast_tavern", "effect": "board_and_deity_buff",
        "per_cast": {"atk": 3, "hp": 3}, "per_cast_golden": {"atk": 6, "hp": 6},
        "unit": "board_minion", "sigma": 21.0, "sigma_golden": 42.0,
        "compounding": False, "priority": 1, "tier7_only": True,
        "assumption": "全场 7 只 +3/+3 = 42 Σ/次？保守按 21 计（tier7 池，本配置抽不到）",
        "note": "tier 7：max_regular_tier=6 时进不了普通酒馆，仅登记",
    },
    # ---- 池外（登记，不参与主集合）------------------------------------------
    "BG36_510": {"trigger": "cast_on_self", "effect": "blood_gems_on_adjacent",
                 "per_cast": {"atk": 1, "hp": 1}, "per_cast_golden": {"atk": 1, "hp": 1},
                 "unit": "adjacent", "sigma": 4.0, "sigma_golden": 8.0,
                 "compounding": False, "priority": 0,
                 "assumption": "相邻 2 只各 +1/+1 ≈ 4 Σ/次",
                 "note": "未实现（implemented=false）且不在池内"},
    "BG36_921": {"trigger": "cast_on_self", "effect": "self_hp",
                 "per_cast": {"atk": 0, "hp": 1}, "per_cast_golden": {"atk": 0, "hp": 2},
                 "unit": "self", "sigma": 1.0, "sigma_golden": 2.0,
                 "compounding": False, "priority": 0,
                 "assumption": "自身 +1 血",
                 "note": "实现但不在池内（tier1 Naga，池外）"},
    "BG23_003": {"trigger": "cast_on_minion", "effect": "target_stats",
                 "per_cast": {"atk": 2, "hp": 2}, "per_cast_golden": {"atk": 4, "hp": 4},
                 "unit": "target", "sigma": 4.0, "sigma_golden": 8.0,
                 "compounding": False, "priority": 0,
                 "assumption": "被施法目标 +2/+2", "note": "池外"},
    "BG23_010": {"trigger": "cast_any", "effect": "self_stats",
                 "per_cast": {"atk": 1, "hp": 1}, "per_cast_golden": {"atk": 2, "hp": 2},
                 "unit": "self", "sigma": 2.0, "sigma_golden": 4.0,
                 "compounding": False, "priority": 0,
                 "assumption": "自身 +1/+1", "note": "池外"},
    "BG23_013": {"trigger": "cast_any", "effect": "naga_stats_permanent",
                 "per_cast": {"atk": 1, "hp": 1}, "per_cast_golden": {"atk": 2, "hp": 2},
                 "unit": "naga", "sigma": 6.0, "sigma_golden": 12.0,
                 "compounding": True, "priority": 0,
                 "assumption": "按 3 只纳迦计", "note": "池外"},
    "BG36_622": {"trigger": "cast_on_race", "race": "NAGA",
                 "effect": "board_stats", "per_cast": {"atk": 2, "hp": 3},
                 "per_cast_golden": {"atk": 4, "hp": 6}, "unit": "board",
                 "sigma": 35.0, "sigma_golden": 70.0, "compounding": False, "priority": 0,
                 "assumption": "全场 7 只 +2/+3", "note": "池外"},
    "BG33_923": {"trigger": "cast_any", "effect": "board_health",
                 "per_cast": {"atk": 0, "hp": 3}, "per_cast_golden": {"atk": 0, "hp": 6},
                 "unit": "board", "sigma": 21.0, "sigma_golden": 42.0,
                 "compounding": False, "priority": 0,
                 "assumption": "全场 7 只 +3 血", "note": "池外"},
}


# ══════════════════════════════════════════════════════════════════════════
# 1. 识别：卡表 + 内容脚本 + 运行时池
# ══════════════════════════════════════════════════════════════════════════

#: 「施法」触发（英/中）；刻意宽，随后由 classify_trigger 细分
_SPELL_TRIGGER_RE = re.compile(
    r"cast(?:s|ing)?\s+(?:a|an|one|two|three|\d+)?\s*"
    r"(?:tavern\s+|spellcraft\s+)?spell"
    r"|施放.{0,10}法术"
    r"|spellcraft\s+spell",
    re.I,
)

_CAST_ON_SELF_RE = re.compile(r"cast a spell on this|对本随从施放", re.I)
_CAST_ON_RACE_RE = re.compile(
    r"cast a spell on an? (murloc|mech|naga|beast|dragon|demon|elemental|pirate|undead|quilboar)",
    re.I,
)
_CAST_ON_MINION_RE = re.compile(r"cast a spell on a minion|对一个随从施放", re.I)
_CAST_ON_OTHER_RE = re.compile(r"cast a spell on a different friendly minion", re.I)
_AFTER_N_RE = re.compile(r"after you cast (one|two|three|\d+) spells?", re.I)
_TAVERN_SPELL_RE = re.compile(r"cast a tavern spell|施放.{0,6}酒馆法术", re.I)


def load_cards(path: str = CARDS_JSON) -> dict:
    with open(path, encoding="utf-8") as f:
        return {c["id"]: c for c in json.load(f)["cards"]}


def engine_catalog() -> dict:
    """``hsbg_engine.catalog_json()`` → {id: entry}；引擎不可用时返回 {}。"""
    try:
        import hsbg_engine as E  # noqa: PLC0415
        return {c["id"]: c for c in json.loads(E.catalog_json())}
    except BaseException:  # noqa: BLE001 - 引擎缺失时退化为只读卡表
        return {}


def scan_script_listeners(content_dir: str = CONTENT_DIR) -> dict:
    """扫 ``content/*.rs``：返回 {card_id: 文件名}，仅收 ``listens: ev::SPELL_CAST``。"""
    out: dict = {}
    pat = re.compile(r'"([A-Za-z0-9_]+)"\s*,\s*Script\s*\{(.*?)\n        \),', re.S)
    for path in sorted(glob.glob(os.path.join(content_dir, "*.rs"))):
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            continue
        for m in pat.finditer(src):
            cid, body = m.group(1), m.group(2)
            if "ev::SPELL_CAST" in body:
                out[cid] = os.path.basename(path)
    return out


def classify_trigger(text: str, text_zh: str = "") -> dict:
    """文本 → {trigger, race}；无法归类返回 {trigger: other}。"""
    t = f"{text or ''} {text_zh or ''}"
    race = None
    m = _CAST_ON_RACE_RE.search(t)
    if m:
        race = m.group(1).upper()
        if race == "MECH":
            race = "MECHANICAL"
        elif race == "QUILBOAR":
            race = "QUILBOAR"
        return {"trigger": "cast_on_race", "race": race}
    if _CAST_ON_SELF_RE.search(t):
        return {"trigger": "cast_on_self", "race": None}
    if _CAST_ON_OTHER_RE.search(t):
        return {"trigger": "cast_on_other", "race": None}
    if _CAST_ON_MINION_RE.search(t):
        return {"trigger": "cast_on_minion", "race": None}
    if _AFTER_N_RE.search(t):
        return {"trigger": "after_n_spells", "race": None}
    if _TAVERN_SPELL_RE.search(t):
        return {"trigger": "cast_tavern", "race": None}
    if _SPELL_TRIGGER_RE.search(t):
        return {"trigger": "cast_any", "race": None}
    return {"trigger": "other", "race": None}


def _is_growth(entry: dict, spec: dict | None) -> bool:
    if entry.get("id") in NON_CARRIER_IDS:
        return False
    if spec is not None:
        return True
    t = f"{entry.get('text') or ''} {entry.get('text_zh') or ''}".lower()
    stat_words = ("+1/+1", "+2/+2", "+2/+1", "+1/+2", "+3/+3", "+4/+4", "attack",
                  "health", "stats", "攻击力", "生命值", "身材")
    return ("+" in t) and any(k in t for k in stat_words)


def _pair_golden(cards: dict) -> dict:
    """normal_id → golden_id（卡表 ``golden`` 字段，缺失时试 ``_G``）。"""
    out = {}
    for cid, c in cards.items():
        g = c.get("golden") or ""
        if g and g in cards:
            out[cid] = g
        elif cid + "_G" in cards:
            out[cid] = cid + "_G"
    return out


def build_catalog(cards_path: str = CARDS_JSON,
                  content_dir: str = CONTENT_DIR,
                  use_engine: bool = True) -> dict:
    """生成载体清单（确定性）。返回可直接 json.dump 的 dict。"""
    cards = load_cards(cards_path)
    engines = engine_catalog() if use_engine else {}
    script_hits = scan_script_listeners(content_dir)
    golden_of = _pair_golden(cards)

    # 候选 = 文本命中 ∪ 脚本监听命中
    cand: set = set()
    for cid, c in cards.items():
        if c.get("kind") != "minion":
            continue
        if _SPELL_TRIGGER_RE.search(f"{c.get('text') or ''} {c.get('text_zh') or ''}"):
            cand.add(cid)
    for cid in script_hits:
        if cards.get(cid, {}).get("kind") == "minion":
            cand.add(cid)

    entries = {}
    for cid in sorted(cand):
        c = cards.get(cid)
        if c is None:
            continue
        cls = classify_trigger(c.get("text") or "", c.get("text_zh") or "")
        if cls["trigger"] == "other" and cid not in script_hits:
            continue
        e = engines.get(cid) or {}
        tier = int(c.get("tier") or 0)
        pools = c.get("pools") or []
        in_pool = bool(e.get("in_pool")) if e else ("minion" in pools)
        implemented = bool(e.get("implemented")) if e else True
        tier7 = bool(e.get("tier7")) or bool(c.get("tier7"))
        spec = CARRIER_SPECS.get(cid)
        growth = _is_growth(c, spec)
        primary = bool(growth and in_pool and implemented and not tier7 and tier <= 6)
        entry = {
            "id": cid,
            "name": c.get("name") or "",
            "name_zh": c.get("name_zh") or "",
            "tier": tier,
            "atk": int(c.get("atk") or 0),
            "hp": int(c.get("hp") or 0),
            "cost": int(c.get("cost") or 3),
            "races": list(c.get("races") or []),
            "trigger": cls["trigger"],
            "trigger_race": cls["race"],
            "text": c.get("text") or "",
            "text_zh": c.get("text_zh") or "",
            "in_tavern_pool": bool(in_pool),
            "implemented": bool(implemented),
            "tier7_only": bool(tier7),
            "script_listens_spell_cast": bool(cid in script_hits),
            "script_file": script_hits.get(cid),
            "is_growth": bool(growth),
            "is_primary": primary,
            "golden_id": golden_of.get(cid),
            "effect": (spec or {}).get("effect", "unknown"),
            "per_cast": (spec or {}).get("per_cast"),
            "per_cast_golden": (spec or {}).get("per_cast_golden"),
            "expected_sigma_per_cast": (spec or {}).get("sigma"),
            "expected_sigma_per_cast_golden": (spec or {}).get("sigma_golden"),
            "compounding": bool((spec or {}).get("compounding", False)),
            "priority": int((spec or {}).get("priority", 0)),
            "assumption": (spec or {}).get("assumption", ""),
            "note": (spec or {}).get("note", ""),
        }
        if not implemented:
            entry["exclude_reason"] = "not_implemented"
        elif not in_pool:
            entry["exclude_reason"] = "not_in_tavern_pool"
        elif tier7:
            entry["exclude_reason"] = "tier7_only"
        elif not growth:
            entry["exclude_reason"] = "no_permanent_growth"
        else:
            entry["exclude_reason"] = None
        entries[cid] = entry

    # 配金色：金色 id 单独登记，继承 normal 的元信息但保留自己的 tier/atk/hp
    for cid, gid in golden_of.items():
        if cid not in entries or gid not in cards:
            continue
        gc = cards[gid]
        base = dict(entries[cid])
        base.update({
            "id": gid, "golden": True, "normal_id": cid,
            "name": gc.get("name") or base["name"],
            "name_zh": gc.get("name_zh") or base["name_zh"],
            "atk": int(gc.get("atk") or 0), "hp": int(gc.get("hp") or 0),
            "text": gc.get("text") or base["text"],
            "text_zh": gc.get("text_zh") or base["text_zh"],
            "in_tavern_pool": False,
            "exclude_reason": "golden_of_normal",
            "golden_id": None,
        })
        entries[gid] = base
    for e in entries.values():
        e.setdefault("golden", False)
        e.setdefault("normal_id", None)

    # 排序：主集合按 tier/priority，其后是其它
    order = sorted(entries.values(), key=lambda x: (
        0 if x["is_primary"] else 1, 0 if not x.get("golden") else 1,
        -int(x.get("priority") or 0), int(x["tier"]), x["id"]))

    primary = [x for x in order if x["is_primary"]]
    secondary = [x for x in order if not x["is_primary"]]
    narrow = [x["id"] for x in order if x["id"] in set(NARROW_IDS)]
    primary_ids = sorted({x["id"] for x in primary}
                         | {x["id"] for x in primary if x.get("golden_id")})
    narrow_ids = sorted(set(NARROW_IDS))
    catalog = {
        "meta": {
            "generated_by": "scripts/carrier_audit.py",
            "source": "rust/crates/hsbg-engine/data/cards.json "
                      "+ rust/crates/hsbg-engine/src/content/*.rs "
                      "+ hsbg_engine.catalog_json()",
            "cards_json": os.path.relpath(cards_path, ROOT),
            "content_dir": os.path.relpath(content_dir, ROOT),
            "definition": "把施放法术转成永久身材/等价复利的随从（池内+已实现+tier<=6）",
            "primary_count": len(primary_ids),
            "primary_normal_count": len([x for x in primary if not x.get("golden")]),
            "narrow_count": len(narrow_ids),
            "script_listener_count": len(script_hits),
            "trigger_classes": sorted({x["trigger"] for x in order}),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        "primary_ids": primary_ids,
        "narrow_ids": narrow_ids,
        "carriers": primary + secondary,
    }
    _ = narrow
    return catalog


def load_or_build_catalog(path: str = CATALOG_OUT,
                          rebuild: bool = False) -> dict:
    if (not rebuild) and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                cat = json.load(f)
            if cat.get("primary_ids") and cat.get("carriers"):
                return cat
        except (OSError, ValueError):
            pass
    return build_catalog()


def ids_from_catalog(catalog: dict, which: str = "primary") -> set:
    """which: primary / narrow / all(池内+已实现) / all_minion。"""
    carriers = catalog.get("carriers") or []
    if which == "primary":
        return set(catalog.get("primary_ids") or [])
    if which == "narrow":
        return set(catalog.get("narrow_ids") or [])
    if which == "pool":
        return {x["id"] for x in carriers
                if x.get("in_tavern_pool") and x.get("implemented")}
    return {x["id"] for x in carriers}


def name_map(catalog: dict) -> dict:
    """名字 → 卡 id（normal 优先；日志里金色与普通同名）。"""
    out = {}
    for x in catalog.get("carriers") or []:
        if x.get("in_tavern_pool") or x.get("is_primary"):
            out.setdefault(str(x.get("name") or ""), x["id"])
    return {k: v for k, v in out.items() if k}


def entry_map(catalog: dict) -> dict:
    return {x["id"]: x for x in catalog.get("carriers") or []}


# ══════════════════════════════════════════════════════════════════════════
# 2. 日志解析：引擎 record_log 的施法行
# ══════════════════════════════════════════════════════════════════════════

_LOG_CAST_RE = re.compile(r"^\[t(\d+)\] p(\d+) casts (.*)$")
_GOLDEN_PREFIX_RE = re.compile(r"^(?:golden|金色)\s+", re.I)


def parse_log_casts(log_lines, seat: int = 0) -> list:
    """从 ``Game.log()`` 行里解析施法：``[tN] p0 casts <Spell> on <Target>``。

    返回 [{turn, caster, spell, target, target_zone}]；``target_zone`` ∈
    {board, tavern, hand, None}。只保留 caster == seat 的行。
    """
    out = []
    for line in log_lines:
        m = _LOG_CAST_RE.match(line or "")
        if not m:
            continue
        turn, who, rest = int(m.group(1)), int(m.group(2)), m.group(3)
        if who != int(seat):
            continue
        target, zone = None, None
        if " on " in rest:
            spell, target = rest.rsplit(" on ", 1)
            if target.endswith(" (tavern)"):
                target, zone = target[: -len(" (tavern)")], "tavern"
            elif target.endswith(" (hand)"):
                target, zone = target[: -len(" (hand)")], "hand"
            else:
                zone = "board"
        else:
            spell = rest
        out.append({"turn": turn, "caster": who, "spell": spell.strip(),
                    "target": target, "target_zone": zone})
    return out


def _target_is_carrier(target: str | None, carrier_names: set) -> bool:
    if not target:
        return False
    t = _GOLDEN_PREFIX_RE.sub("", target.strip())
    return t in carrier_names


# ══════════════════════════════════════════════════════════════════════════
# 3. rollout 驱动（与 scripts/scaling_signal_probe.py 同一条注入序）
# ══════════════════════════════════════════════════════════════════════════

STAT_KEYS = (
    "tavern_spells_cast", "spells_cast", "spellcraft_cast", "golden_played",
    "tavern_atk", "tavern_hp", "tavern_elemental_atk", "tavern_elemental_hp",
    "minions_bought", "cards_played", "cards_discarded", "gold_spent_total",
    "refreshes", "battlecries_triggered", "deathrattles_triggered",
    "elementals_played", "combats_won", "combats_lost",
)

_E = None
_POLICY = None
_HUMAN_POOL = None
_MIRROR_POOL = None
_CFG: dict = {}


def _mask_np(g, seat: int = 0):
    return np.frombuffer(g.legal_mask(seat), dtype=np.uint8)


def _board_carriers(me: dict, carrier_ids: set) -> list:
    return [str(m.get("id")) for m in (me.get("board") or [])
            if str(m.get("id")) in carrier_ids]


def _item_ids(items, carrier_ids: set) -> list:
    return [str(it.get("id")) for it in (items or [])
            if str(it.get("id")) in carrier_ids]


def _make_policy(cfg: dict):
    """建策略：net（s15 权重）或 teacher（载体教师）。"""
    kind = str(cfg.get("policy") or "net")
    if kind == "teacher":
        from carrier_teacher import CarrierTeacher  # noqa: PLC0415
        return CarrierTeacher(
            carriers_json=str(cfg.get("carriers_json") or CATALOG_OUT),
            refresh_cap=int(cfg.get("teacher_refresh_cap", 2)),
            upgrade_curve=tuple(int(x) for x in str(
                cfg.get("teacher_upgrade_curve", "4,6,8,10")).split(",")),
            cast_when_no_carrier_after=int(
                cfg.get("teacher_cast_late_turn", 11)),
            max_actions_per_turn=int(cfg.get("max_actions_per_turn", 40)),
            sell_cap=int(cfg.get("teacher_sell_cap", 3)),
            buy_spells=bool(int(cfg.get("teacher_buy_spells", 1))),
            spell_max_price=int(cfg.get("teacher_spell_max_price", 2)),
            replace_margin=int(cfg.get("teacher_replace_margin", 2)),
        )
    import torch  # noqa: PLC0415
    try:
        torch.set_num_threads(1)
    except BaseException:  # noqa: BLE001
        pass
    from hsbg.az.train.model import load_checkpoint  # noqa: PLC0415
    from hsbg.az.train.ppo import (CollectConfig, PPOEvaluator,  # noqa: PLC0415
                                   PPOSelfPlayPolicy)
    dev = str(cfg["device"])
    model, meta = load_checkpoint(str(cfg["checkpoint"]), device=dev)
    ev = PPOEvaluator(model, device=dev,
                      norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    cc = CollectConfig(games=1, seed=int(cfg["seed_base"]), opponent="bot",
                       behavior="net", max_steps=int(cfg["max_steps"]),
                       max_actions_per_turn=int(cfg["max_actions_per_turn"]),
                       move_guard=bool(int(cfg["move_guard"])),
                       move_cap=int(cfg["move_cap"]),
                       move_repeat_limit=int(cfg["move_repeat_limit"]),
                       fast_act=True, temperature=1.0)
    cfg["_collect_cfg"] = dict(cc.__dict__)
    return PPOSelfPlayPolicy(model, device=dev, config=cc, eval_fn=ev,
                             seed=int(cfg["seed_base"]), move_model=False)


def _init_worker(cfg: dict) -> None:
    global _E, _POLICY, _HUMAN_POOL, _MIRROR_POOL, _CFG
    _CFG = dict(cfg)
    import hsbg_engine as E  # noqa: PLC0415
    _E = E
    _POLICY = _make_policy(_CFG)
    if float(cfg["human_board_p"]) > 0.0:
        from hsbg.az.train.human_board_pool import load_pool as _load_human  # noqa: PLC0415
        _HUMAN_POOL = _load_human(str(cfg["human_boards"]),
                                  sample=str(cfg["human_board_sample"]))
        if _HUMAN_POOL is None:
            raise RuntimeError(f"人类战团库为空/不存在: {cfg['human_boards']}")
    if float(cfg["mirror_p"]) > 0.0:
        from hsbg.az.train.mirror_snapshots import load_pool as _load_mirror  # noqa: PLC0415
        _MIRROR_POOL = _load_mirror(str(cfg["mirror_snaps"]),
                                    sample=str(cfg["mirror_sample"]))
        if _MIRROR_POOL is None:
            print(f"[warn] 回合末快照库为空/不存在: {cfg['mirror_snaps']}",
                  flush=True)


def _snap_view(view: dict, turn: int, shop_seen: set, hand_seen: set,
               carrier_ids: set, board_seen: set | None = None) -> dict:
    """从 ``Game.view(seat)`` 取招募末快照（战团/金币/tier/载体/引擎计数）。"""
    me = view.get("me") or {}
    board = me.get("board") or []
    st = me.get("stats") or {}
    return {
        "turn": int(turn),
        "strength": int(sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                            for m in board)),
        "count": len(board),
        "tier": int(me.get("tier") or 0),
        "gold": int(me.get("gold") or 0),
        "health": int(me.get("health") or 0),
        "alive": bool(me.get("alive", True)),
        "board_ids": [str(m.get("id")) for m in board],
        "board_carriers": _board_carriers(me, carrier_ids),
        "board_carriers_seen": sorted(set(board_seen or [])),
        "hand_ids": [str(it.get("id")) for it in (me.get("hand") or [])],
        "shop_carrier_ids": sorted(shop_seen),
        "hand_carrier_ids": sorted(hand_seen),
        "stats": {k: int(st.get(k) or 0) for k in STAT_KEYS},
    }


def _play_one(seed: int) -> dict:
    """驱动一局：learner = seat 0（net 或 teacher），其余 7 席按 s15 分布。"""
    E = _E
    policy = _POLICY
    cfg = _CFG
    from hsbg.az.train.common import mask_from_bytes  # noqa: PLC0415
    from hsbg.az.train.human_board_pool import (HumanBoardStats,  # noqa: PLC0415
                                                inject_turn as human_inject)
    from hsbg.az.train.mirror_snapshots import (MirrorStats,  # noqa: PLC0415
                                                inject_turn as mirror_inject,
                                                mirror_seats)

    seat = 0
    gold = int(cfg["gold"])
    max_steps = int(cfg["max_steps"])
    carrier_ids = set(cfg["carrier_ids"])
    cast_intent = bool(cfg.get("record_log", 1))
    t0 = time.time()
    if hasattr(policy, "reset"):
        policy.reset()
    if hasattr(policy, "reseed"):
        policy.reseed(int(seed))
    if hasattr(policy, "game_id"):
        policy.game_id = int(seed)

    game = E.Game(int(seed))
    if cast_intent:
        try:
            game.set_record_log(True)
        except BaseException:  # noqa: BLE001
            pass
    rows: list = []
    turns: list = []
    human_stats = None
    mirror_stats = None
    applied: list = []
    mirror_turn = int(game.turn)
    human_turn = int(game.turn)
    gold_turn = int(game.turn) - 1
    mirror_rng = random.Random(int(seed) * 31 + 7)
    human_rng = random.Random(int(seed) * 53 + 11)
    steps = 0
    truncated = False
    n_inject = {"mirror": 0, "human": 0}
    ended_snap_turn = -1
    tracked_turn = -1
    fallback = 0
    shop_seen: set = set()
    hand_seen: set = set()
    board_seen: set = set()
    bought_carriers: list = []
    choice_casts_on_carrier = 0
    lobby_races: list = []
    board_carrier_eids: set = set()

    def maybe_inject() -> None:
        nonlocal mirror_turn, human_turn, gold_turn, applied
        nonlocal human_stats, mirror_stats
        t = int(game.turn)
        if t != mirror_turn:
            mirror_turn = t
            applied = []
            if _MIRROR_POOL is not None and float(cfg["mirror_p"]) > 0.0:
                mirror_stats = mirror_stats or MirrorStats()
                mirror_inject(game, _MIRROR_POOL, t,
                              seats=mirror_seats(int(cfg["mirror_seats"]), 8, seat),
                              p=float(cfg["mirror_p"]), rng=mirror_rng,
                              learner_seat=seat, stats=mirror_stats,
                              applied_out=applied)
                n_inject["mirror"] += len(applied)
        if t != human_turn:
            human_turn = t
            if _HUMAN_POOL is not None and float(cfg["human_board_p"]) > 0.0:
                human_stats = human_stats or HumanBoardStats()
                human_inject(game, _HUMAN_POOL, t,
                             seats_count=int(cfg["human_board_seats"]),
                             p=float(cfg["human_board_p"]), rng=human_rng,
                             learner_seat=seat, stats=human_stats,
                             mirror_seats=tuple(applied), num_players=8,
                             set_tier=bool(int(cfg["human_board_set_tier"])),
                             fidelity=str(cfg["human_board_fidelity"]),
                             fast_inject=bool(int(cfg["human_board_fast_inject"])))
                n_inject["human"] += int(getattr(human_stats, "applied", 0))
        if gold > 0 and t != gold_turn:
            gold_turn = t
            try:
                game.debug(json.dumps({"cmd": "set_player", "p": 0, "gold": gold}))
            except BaseException:  # noqa: BLE001
                pass

    def _sync_policy_meta(view: dict) -> None:
        nonlocal lobby_races
        if not lobby_races:
            lobby_races = [str(x) for x in (view.get("lobby_races") or [])]
        if hasattr(policy, "set_lobby"):
            policy.set_lobby(lobby_races, view.get("me") or {})

    while (not game.is_over()) and steps < max_steps:
        acted = False
        for p in range(8):
            if game.is_over():
                break
            maybe_inject()
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            t_now = int(game.turn)
            if p == seat:
                view = json.loads(game.view(seat))
                _sync_policy_meta(view)
                me = view.get("me") or {}
                mask = mask_from_bytes(game.legal_mask(seat))
                # -- 追踪：本回合见过的商店/手牌载体 -------------------------
                if t_now != tracked_turn:
                    tracked_turn = t_now
                    shop_seen, hand_seen, board_seen = set(), set(), set()
                shop_seen.update(_item_ids(me.get("shop"), carrier_ids))
                hand_seen.update(_item_ids(me.get("hand"), carrier_ids))
                board_seen.update(_board_carriers(me, carrier_ids))
                board_carrier_eids = {
                    int(m.get("eid")) for m in (me.get("board") or [])
                    if str(m.get("id")) in carrier_ids
                }
                # -- 决策 ---------------------------------------------------
                if hasattr(policy, "decide_view"):
                    a = int(policy.decide_view(view, mask))
                else:
                    dec = policy.decide(game, seat)
                    a = int(getattr(dec, "action", dec))
                if not (0 <= a < 245 and bool(mask[a])):
                    nz = np.flatnonzero(mask)
                    a = int(nz[0]) if nz.size else 0
                    fallback += 1
                # -- 追踪：买载体 / 对载体施法（选择目标）---------------------
                if A_BUY <= a < A_BUY_END:
                    slot = a - A_BUY
                    shop = me.get("shop") or []
                    if 0 <= slot < len(shop):
                        sid = str(shop[slot].get("id"))
                        if sid in carrier_ids:
                            bought_carriers.append(sid)
                pend = me.get("pending") or {}
                if A_CHOOSE <= a < A_CHOOSE_END and str(pend.get("kind")) == "target":
                    opts = pend.get("options") or []
                    idx = a - A_CHOOSE
                    if idx < len(opts) and isinstance(opts[idx], int) \
                            and opts[idx] in board_carrier_eids:
                        choice_casts_on_carrier += 1
                if a == A_END and ended_snap_turn != t_now:
                    turns.append(_snap_view(view, t_now, shop_seen, hand_seen,
                                            carrier_ids, board_seen))
                    ended_snap_turn = t_now
                game.step(seat, a)
            else:
                game.bot_play(int(p))
        if not acted and not game.is_over():
            break
    if not game.is_over():
        truncated = True
    try:
        placements = list(game.placements())
        placement = int(placements[seat])
    except BaseException:  # noqa: BLE001
        placement = 0
    end_turns = [r["turn"] for r in turns]
    death_turn = int(end_turns[-1]) if end_turns else None

    # -- 日志：逐回合施法 / 对载体施法 -------------------------------------
    casts = []
    if cast_intent:
        try:
            casts = parse_log_casts(game.log(), seat=seat)
        except BaseException:  # noqa: BLE001
            casts = []
    names = set(cfg.get("carrier_names") or [])
    trig_map = dict(cfg.get("carrier_trigger") or {})
    global_trig = ("cast_tavern", "cast_any", "after_n_spells")
    seen_by_turn = {int(r["turn"]): list(r.get("board_carriers_seen") or [])
                    for r in turns}
    per_turn_casts: dict = {}
    per_turn_on_carrier: dict = {}
    per_turn_trig: dict = {}
    targets_on_carrier = 0
    triggering = 0
    targeted = 0
    for c in casts:
        t = int(c["turn"])
        per_turn_casts[t] = per_turn_casts.get(t, 0) + 1
        hit = False
        if c.get("target"):
            targeted += 1
            if c.get("target_zone") == "board" and _target_is_carrier(
                    c.get("target"), names):
                per_turn_on_carrier[t] = per_turn_on_carrier.get(t, 0) + 1
                targets_on_carrier += 1
                hit = True
        if not hit:
            for cid in seen_by_turn.get(t) or []:
                if trig_map.get(str(cid)) in global_trig:
                    hit = True
                    break
        if hit:
            per_turn_trig[t] = per_turn_trig.get(t, 0) + 1
            triggering += 1
    for row in turns:
        row["casts_turn"] = int(per_turn_casts.get(int(row["turn"]), 0))
        row["casts_on_carrier_turn"] = int(
            per_turn_on_carrier.get(int(row["turn"]), 0))
        row["casts_trigger_carrier_turn"] = int(
            per_turn_trig.get(int(row["turn"]), 0))
    carrier_turns = sum(1 for r in turns if r["board_carriers"])
    return {
        "seed": int(seed),
        "tag": str(cfg.get("tag")),
        "policy": str(cfg.get("policy")),
        "gold": gold,
        "placement": placement,
        "truncated": bool(truncated),
        "steps": int(steps),
        "death_turn": death_turn,
        "lobby_races": lobby_races,
        "fallback_actions": int(fallback),
        "policy_meta": (policy.meta() if hasattr(policy, "meta") else None),
        "injections": dict(n_inject),
        "carrier_bought": sorted(set(bought_carriers)),
        "casts_total": int(len(casts)),
        "casts_targeted": int(targeted),
        "casts_on_carrier": int(targets_on_carrier),
        "casts_trigger_carrier": int(triggering),
        "casts_on_carrier_choice": int(choice_casts_on_carrier),
        "carrier_turns": int(carrier_turns),
        "carrier_ever_on_board": bool(carrier_turns > 0),
        "carrier_ever_in_shop": bool(any(r["shop_carrier_ids"] for r in turns)),
        "carrier_ever_in_hand": bool(any(r["hand_carrier_ids"] for r in turns)),
        "max_tier": int(max([r["tier"] for r in turns] or [0])),
        "elapsed": round(time.time() - t0, 3),
        "turns": turns,
    }


def _job(seed: int) -> dict:
    try:
        return _play_one(int(seed))
    except BaseException:  # noqa: BLE001
        return {"seed": int(seed), "tag": str(_CFG.get("tag")),
                "policy": str(_CFG.get("policy")),
                "error": traceback.format_exc()[-3000:], "turns": [],
                "placement": 0}


def run_rollout(cfg: dict, seeds, workers: int = 1, progress: bool = True) -> list:
    """跑一批局（可多进程），返回按 seed 排序的行。"""
    import multiprocessing as mp
    seeds = [int(s) for s in seeds]
    rows: list = []
    workers = max(1, int(workers))
    t0 = time.time()
    if workers == 1:
        _init_worker(cfg)
        for i, s in enumerate(seeds):
            rows.append(_job(s))
            if progress and (i + 1) % 10 == 0:
                print(f"[{cfg.get('tag')}] {i + 1}/{len(seeds)} "
                      f"{round(time.time() - t0, 1)}s", flush=True)
    else:
        ctx = mp.get_context("fork")
        with ctx.Pool(workers, initializer=_init_worker, initargs=(cfg,)) as pool:
            for i, r in enumerate(pool.imap_unordered(_job, seeds, chunksize=1)):
                rows.append(r)
                if progress and ((i + 1) % 10 == 0 or r.get("error")):
                    print(f"[{cfg.get('tag')}] {i + 1}/{len(seeds)} "
                          f"{round(time.time() - t0, 1)}s", flush=True)
    rows.sort(key=lambda r: r["seed"])
    return rows


def write_rollout(rows: list, path: str, meta: dict | None = None) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if meta is not None:
        with open(path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)


def read_rollout(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ══════════════════════════════════════════════════════════════════════════
# 4. 指标汇总
# ══════════════════════════════════════════════════════════════════════════

def _pct(v, q):
    return float(np.percentile(np.asarray(v, dtype=float), q)) if len(v) else None


def _dist(v) -> dict:
    v = [float(x) for x in v]
    if not v:
        return {"n": 0, "mean": None, "p50": None, "p90": None, "max": None}
    return {"n": len(v), "mean": round(float(np.mean(v)), 3),
            "p50": round(_pct(v, 50), 3), "p90": round(_pct(v, 90), 3),
            "max": round(float(np.max(v)), 3),
            "p25": round(_pct(v, 25), 3), "p75": round(_pct(v, 75), 3)}


def _pearson(x, y) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 3 or x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _rank(v):
    v = np.asarray(v, dtype=float)
    order = v.argsort()
    r = np.empty_like(order, dtype=float)
    r[order] = np.arange(v.size, dtype=float)
    # 平均同秩
    _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
    sums = np.zeros(cnt.size)
    np.add.at(sums, inv, r)
    return (sums / cnt)[inv]


def _spearman(x, y) -> float:
    return _pearson(_rank(x), _rank(y))


def _boot_corr_ci(x, y, B: int = 2000, seed: int = 20261031):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 5:
        return None
    rng = np.random.default_rng(int(seed))
    out = []
    n = x.size
    for _ in range(int(B)):
        idx = rng.integers(0, n, n)
        r = _pearson(x[idx], y[idx])
        if r is not None:
            out.append(r)
    if not out:
        return None
    return [round(float(np.percentile(out, 2.5)), 4),
            round(float(np.percentile(out, 97.5)), 4)]


def _boot_diff_ci(a, b, B: int = 2000, seed: int = 20261031):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 3 or b.size < 3:
        return None
    rng = np.random.default_rng(int(seed))
    out = []
    for _ in range(int(B)):
        out.append(float(np.mean(rng.choice(a, a.size))
                         - np.mean(rng.choice(b, b.size))))
    return [round(float(np.percentile(out, 2.5)), 3),
            round(float(np.percentile(out, 97.5)), 3)]


def _str_at(row: dict, turn: int):
    for r in row.get("turns") or []:
        if int(r.get("turn") or 0) == int(turn):
            return r
    return None


def _per_carrier_stats(rows: list, emap: dict, primary: set) -> dict:
    """每张主集合载体的在场/购买计数（normal 与 golden 合并到 normal）。"""
    out: dict = {}
    for cid in sorted(primary):
        e = emap.get(cid) or {}
        normal = e.get("normal_id") or cid
        rec = out.setdefault(normal, {
            "name": e.get("name") or normal, "tier": e.get("tier"),
            "trigger": e.get("trigger"), "on_board_games": 0,
            "shop_games": 0, "bought_games": 0, "turns": 0,
        })
        for r in rows:
            turns = r.get("turns") or []
            n_t = sum(1 for t in turns if cid in set(t.get("board_carriers") or []))
            n_s = sum(1 for t in turns if cid in set(t.get("shop_carrier_ids") or []))
            n_b = sum(1 for b in (r.get("carrier_bought") or []) if b == cid)
            if n_t:
                rec["on_board_games"] += 1
                rec["turns"] += n_t
            if n_s:
                rec["shop_games"] += 1
            if n_b:
                rec["bought_games"] += 1
    return out


def summarize(rows: list, catalog: dict, *, horizon: int = 12,
              casts_key: str = "casts_trigger_carrier") -> dict:
    """汇总：载体率、Σ 分布、对载体施法分布、r(载体回合数, Σ₁₂)。"""
    emap = entry_map(catalog)
    primary = set(catalog.get("primary_ids") or [])
    narrow = set(catalog.get("narrow_ids") or [])
    ok = [r for r in rows if not r.get("error") and r.get("turns")]
    errs = [r for r in rows if r.get("error")]

    def _ids(row_turn) -> set:
        return set(row_turn.get("board_carriers") or [])

    def _carrier_turns(row, upto=None, ids=primary) -> int:
        return sum(1 for t in row.get("turns") or []
                   if (upto is None or int(t["turn"]) <= int(upto))
                   and (_ids(t) & ids))

    def _str12(row):
        t = _str_at(row, 12)
        return int(t["strength"]) if t is not None else None

    # ---- 载体率（局级 / 回合级；primary 与 narrow 两套口径）-----------------
    ever = [r for r in ok if _carrier_turns(r, ids=primary) > 0]
    ever_narrow = [r for r in ok if _carrier_turns(r, ids=narrow) > 0]
    t9 = [r for r in ok if _ids(_str_at(r, 9) or {}) & primary]
    t12c = [r for r in ok if _ids(_str_at(r, 12) or {}) & primary]
    t9n = [r for r in ok if _ids(_str_at(r, 9) or {}) & narrow]
    t12n = [r for r in ok if _ids(_str_at(r, 12) or {}) & narrow]
    shop_ever = [r for r in ok if r.get("carrier_ever_in_shop")]
    hand_ever = [r for r in ok if r.get("carrier_ever_in_hand")]
    bought = [r for r in ok if r.get("carrier_bought")]

    def _available_ids(row) -> set:
        """本局大厅种族下**可能抽到**的主集合载体 id。"""
        races = set(str(x) for x in (row.get("lobby_races") or []))
        if not races:
            return set()
        out = set()
        for cid in primary:
            e = emap.get(cid) or {}
            r = set(str(x) for x in (e.get("races") or []))
            if not r or "ALL" in r or (r & races):
                out.add(cid)
        return out

    avail = [r for r in ok if _available_ids(r)]
    avail_turn_rows = [t for r in ok for t in (r.get("turns") or [])
                       if _ids(t) & _available_ids(r)]
    recruit_turns = [t for r in ok for t in (r.get("turns") or [])]
    carrier_turn_rows = [t for t in recruit_turns if _ids(t) & primary]
    narrowed_turn_rows = [t for t in recruit_turns if _ids(t) & narrow]
    tier4 = [t for t in recruit_turns if int(t.get("tier") or 0) >= 4]

    # ---- t12 Σ 分布（有/无载体）------------------------------------------
    with12 = [r for r in ok if _str12(r) is not None and _carrier_turns(r, upto=12) > 0]
    without12 = [r for r in ok if _str12(r) is not None
                 and _carrier_turns(r, upto=12) == 0]
    s_with = [int(_str12(r)) for r in with12]
    s_without = [int(_str12(r)) for r in without12]
    s_all = [int(_str12(r)) for r in ok if _str12(r) is not None]
    # 也按窄口径给一份
    with12n = [r for r in ok if _str12(r) is not None
               and _carrier_turns(r, upto=12, ids=narrow) > 0]
    without12n = [r for r in ok if _str12(r) is not None
                  and _carrier_turns(r, upto=12, ids=narrow) == 0]

    # ---- 对载体施法分布 ---------------------------------------------------
    ccast = [int(r.get(casts_key) or 0) for r in ok]
    ccast_with = [int(r.get(casts_key) or 0) for r in ok if r.get("carrier_ever_on_board")]
    log_ccast = [int(r.get("casts_on_carrier") or 0) for r in ok]
    trig_ccast = [int(r.get("casts_trigger_carrier") or 0) for r in ok]
    trig_with = [int(r.get("casts_trigger_carrier") or 0) for r in ok
                 if r.get("carrier_ever_on_board")]
    choice_ccast = [int(r.get("casts_on_carrier_choice") or 0) for r in ok]
    per_cturn = [int(t.get("casts_on_carrier_turn") or 0) for t in carrier_turn_rows]
    per_trig_turn = [int(t.get("casts_trigger_carrier_turn") or 0)
                     for t in carrier_turn_rows]

    # ---- 相关：r(载体在场回合数, Σ₁₂) ------------------------------------
    corr_rows = [r for r in ok if _str12(r) is not None]
    ct = [_carrier_turns(r, upto=12) for r in corr_rows]
    s12 = [_str12(r) for r in corr_rows]
    r_p = _pearson(ct, s12)
    r_s = _spearman(ct, s12)
    ci_p = _boot_corr_ci(ct, s12)
    ci_s = _boot_corr_ci(_rank(ct), _rank(s12))
    # 换一个“口径”：有/无载体组的 t12 Σ 均值差
    diff = (float(np.mean(s_with)) - float(np.mean(s_without))) \
        if s_with and s_without else None
    diff_ci = _boot_diff_ci(s_with, s_without) if s_with and s_without else None
    # 对载体施法次数 vs Σ12
    cc_rows = [r for r in corr_rows]
    cc = [int(r.get(casts_key) or 0) for r in cc_rows]
    r_cc = _pearson(cc, [_str12(r) for r in cc_rows])
    ci_cc = _boot_corr_ci(cc, [_str12(r) for r in cc_rows])

    ranks = [int(r["placement"]) for r in ok if int(r.get("placement") or 0) > 0]
    by_tier = {}
    for t in recruit_turns:
        by_tier.setdefault(int(t.get("tier") or 0), []).append(t)
    return {
        "games": len(ok),
        "errors": len(errs),
        "policy": (rows[0].get("policy") if rows else None),
        "tag": (rows[0].get("tag") if rows else None),
        "mean_rank": round(float(np.mean(ranks)), 3) if ranks else None,
        "top4": round(float(np.mean([x <= 4 for x in ranks])), 4) if ranks else None,
        "win": round(float(np.mean([x == 1 for x in ranks])), 4) if ranks else None,
        "death_turn_p50": _pct([int(r.get("death_turn") or 0) for r in ok
                                if r.get("death_turn")], 50),
        "truncated": int(sum(1 for r in ok if r.get("truncated"))),
        "fallback_actions": int(sum(int(r.get("fallback_actions") or 0) for r in ok)),
        "policy_meta": (rows[0].get("policy_meta") if rows else None),
        "carrier": {
            "primary_ids": len(primary),
            "narrow_ids": len(narrow),
            # 局级
            "carrier_encounter_rate": round(len(ever) / max(1, len(ok)), 4),
            "carrier_encounter_rate_narrow": round(len(ever_narrow) / max(1, len(ok)), 4),
            "carrier_t9_rate": round(len(t9) / max(1, len(ok)), 4),
            "carrier_t12_rate": round(len(t12c) / max(1, len(ok)), 4),
            "carrier_t9_rate_narrow": round(len(t9n) / max(1, len(ok)), 4),
            "carrier_t12_rate_narrow": round(len(t12n) / max(1, len(ok)), 4),
            "carrier_shop_offer_rate": round(len(shop_ever) / max(1, len(ok)), 4),
            "carrier_hand_rate": round(len(hand_ever) / max(1, len(ok)), 4),
            "carrier_bought_rate": round(len(bought) / max(1, len(ok)), 4),
            "carrier_race_available_rate": round(len(avail) / max(1, len(ok)), 4),
            "carrier_offer_given_available_rate": round(
                len([r for r in shop_ever if _available_ids(r)])
                / max(1, len(avail)), 4),
            # 回合级
            "carrier_turn_rate": round(len(carrier_turn_rows)
                                       / max(1, len(recruit_turns)), 4),
            "carrier_turn_rate_narrow": round(len(narrowed_turn_rows)
                                              / max(1, len(recruit_turns)), 4),
            "carrier_turn_rate_given_available": round(
                len(avail_turn_rows) / max(1, sum(
                    len(r.get("turns") or []) for r in avail)), 4),
            "carrier_turns_mean": round(float(np.mean(
                [_carrier_turns(r) for r in ok])), 3) if ok else 0.0,
            "carrier_turns_mean_t12_games": round(float(np.mean(ct)), 3) if ct else 0.0,
            "carrier_turns_dist": _dist([_carrier_turns(r) for r in ok]),
            "recruit_turns": len(recruit_turns),
            "tier4_turn_rate": round(len(tier4) / max(1, len(recruit_turns)), 4),
            "tier_dist": {str(k): len(v) for k, v in sorted(by_tier.items())},
            # 对载体施法
            "casts_total_mean": round(float(np.mean(
                [int(r.get("casts_total") or 0) for r in ok])), 3) if ok else 0.0,
            # 主口径：真正会触发载体（打在身上 / 全局施法触发）的施法次数
            "casts_on_carrier_mean": round(float(np.mean(trig_ccast)), 3)
            if trig_ccast else 0.0,
            "casts_on_carrier_mean_given_carrier": round(
                float(np.mean(trig_with)), 3) if trig_with else 0.0,
            "casts_on_carrier_dist": _dist(trig_ccast),
            "casts_on_carrier_dist_given_carrier": _dist(
                [int(r.get("casts_trigger_carrier") or 0) for r in ever]),
            # 严格口径：日志目标名字就是载体
            "casts_targeted_carrier_mean": round(float(np.mean(log_ccast)), 3)
            if log_ccast else 0.0,
            "casts_targeted_carrier_dist": _dist(log_ccast),
            "casts_on_carrier_choice_mean": round(float(np.mean(choice_ccast)), 3)
            if choice_ccast else 0.0,
            "casts_per_carrier_turn": round(float(np.mean(per_trig_turn)), 3)
            if per_trig_turn else 0.0,
            "casts_targeted_per_carrier_turn": round(float(np.mean(per_cturn)), 3)
            if per_cturn else 0.0,
            # 机制口径别名
            "casts_trigger_carrier_mean": round(float(np.mean(trig_ccast)), 3)
            if trig_ccast else 0.0,
            "casts_trigger_carrier_mean_given_carrier": round(
                float(np.mean(trig_with)), 3) if trig_with else 0.0,
            "casts_trigger_carrier_dist": _dist(trig_ccast),
            "casts_trigger_carrier_dist_given_carrier": _dist(
                [int(r.get("casts_trigger_carrier") or 0) for r in ever]),
            "casts_trigger_per_carrier_turn": round(
                float(np.mean(per_trig_turn)), 3) if per_trig_turn else 0.0,
            "per_carrier": _per_carrier_stats(ok, emap, primary),
        },
        "strength12": {
            "n": len(s_all),
            "all": _dist(s_all),
            "with_carrier": _dist(s_with),
            "without_carrier": _dist(s_without),
            "with_carrier_narrow": _dist([int(_str12(r)) for r in with12n]),
            "without_carrier_narrow": _dist([int(_str12(r)) for r in without12n]),
            "mean_diff": round(diff, 3) if diff is not None else None,
            "mean_diff_ci95": diff_ci,
        },
        "corr_carrier_turns_str12": {
            "n": len(corr_rows),
            "pearson": round(r_p, 4) if r_p is not None else None,
            "pearson_ci95": ci_p,
            "spearman": round(r_s, 4) if r_s is not None else None,
            "spearman_ci95": ci_s,
            "gate_pass": bool(r_p is not None and r_p > 0
                              and (ci_p is None or ci_p[0] > 0)),
        },
        "corr_casts_on_carrier_str12": {
            "n": len(cc_rows),
            "pearson": round(r_cc, 4) if r_cc is not None else None,
            "pearson_ci95": ci_cc,
        },
    }


def gate_check(summary: dict, *, carrier_target: float = 0.25,
               str12_target: float = 1132.0) -> dict:
    """课程退火门的判据（题面）：载体率 ≥25%、t12 Σ ≥2×566、r>0。"""
    c = summary.get("carrier") or {}
    s = summary.get("strength12") or {}
    corr = summary.get("corr_carrier_turns_str12") or {}
    rate = float(c.get("carrier_encounter_rate") or 0.0)
    p50 = (s.get("all") or {}).get("p50") or 0.0
    r = corr.get("pearson")
    return {
        "carrier_target": carrier_target,
        "carrier_encounter_rate": rate,
        "carrier_ok": bool(rate >= carrier_target),
        "str12_p50": p50,
        "str12_target": str12_target,
        "str12_ok": bool(float(p50) >= str12_target),
        "corr_carrier_turns_str12": r,
        "corr_ok": bool(r is not None and r > 0),
        "all_ok": bool(rate >= carrier_target and float(p50) >= str12_target
                       and r is not None and r > 0),
    }


__all__ = [
    "ROOT", "SCRIPTS", "CARDS_JSON", "CONTENT_DIR", "CATALOG_OUT", "ROLLOUT_DIR",
    "NARROW_IDS", "CARRIER_SPECS", "STAT_KEYS",
    "A_END", "A_REFRESH", "A_FREEZE", "A_UPGRADE", "A_HERO_POWER", "A_CANCEL",
    "A_BUY", "A_BUY_END", "A_SELL", "A_SELL_END", "A_ACTIVATE",
    "A_ACTIVATE_END", "A_CHOOSE", "A_CHOOSE_END", "A_PLAY", "A_PLAY_END",
    "A_MAGNETIZE", "A_MOVE", "A_MOVE_END", "N_POS", "N_BOARD", "N_CHOICE",
    "load_cards", "engine_catalog", "scan_script_listeners", "classify_trigger",
    "build_catalog", "load_or_build_catalog", "ids_from_catalog", "name_map",
    "entry_map", "parse_log_casts", "run_rollout", "write_rollout",
    "read_rollout", "summarize", "gate_check", "SPELL_KINDS",
]
