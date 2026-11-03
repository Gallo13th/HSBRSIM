#!/usr/bin/env python3
"""HSBRSIM 人类对战界面：本地 Web UI（零 Web 框架，只用标准库 ``http.server``）。

目标
----
让人直接在浏览器里打完整对局（自己 vs 引擎原生 7 个 bot），并把**每一个人类决策**
（``features`` 3227 + ``cards`` 124 + ``mask`` 245 + ``action`` + ``turn``）按训练数据
同口径落盘到 ``runs/human_play/*.jsonl.gz``，可直接作为 BC 示范数据。

设计
----
- 单用户、单进程、``HTTPServer``（无并发），默认只绑 ``127.0.0.1``；
- 动作空间**直接用引擎 245 维**（``hsbg/env/action_space_std.py`` 常量与
  ``hsbg_engine.action_name``）；前端按钮全部映射到具体 action id；
- 每次请求只做一件事：``GET /state`` 读状态，``POST /act {action}`` 推进一步；
- bot 座位用引擎原生 ``Game.bot_play(p)`` 推进到本回合结束（不训练、不占 GPU）；
- replay 逐决策**增量**写 gzip（多 member 拼接，``gzip.open`` 可正常读）。

HTTP 端点
---------
======  ======  ==========================================================
方法    路径     说明
======  ======  ==========================================================
GET     /       内嵌 HTML/JS 界面
GET     /state  当前状态 JSON（商店/手牌/场上/HUD/合法动作/对手/pending）
POST    /act    ``{"action": int}`` 执行一步并返回新状态（非法动作 400）
POST    /new    ``{"seed": int}``（可省）开新局并返回新状态
GET     /replay 下载本局 replay（jsonl.gz）
GET     /snapshot 注入当前状态的静态 HTML（同步渲染，便于截图/复盘）
GET     /health 存活探针
======  ======  ==========================================================

用法::

    # 远端机器上启动（项目根目录）
    python scripts/human_arena.py --port 8000 --seed 1234
    # 本地浏览器（SSH 端口转发）
    ssh -L 8000:127.0.0.1:8000 bicourse-glt   # 然后打开 http://127.0.0.1:8000

    # 无浏览器自测：脚本化人类跑完一整局 + 校验 replay 可转 BC npz
    python scripts/human_arena.py --selftest --seed 1234

    # replay -> BC npz（train_compound_bc.load_npz 可直接读）
    python scripts/human_arena.py --to-npz runs/human_play --npz-out data/human_bc/human_play.npz

replay 格式（每行一个 JSON；gzip 多 member）
--------------------------------------------
- 首行 ``{"type": "meta", ...}``：engine / game_version / seed / seat / obs 尺寸；
- 中间每行 ``{"type": "decision", ...}``：``features``(3227) / ``cards``(124) /
  ``mask``(245) / ``action`` / ``turn`` / ``tier`` / ``gold`` / ``phase`` / ``decision``；
- 末行 ``{"type": "summary", ...}``：placement / placements / decisions / turns。

BC 转换：``--to-npz`` 生成 ``obs``(n,3351 float32) + ``cards`` + ``mask``(bool) +
``action`` + ``turn/tier/gold/episode_id``，与 ``scripts/train_compound_bc.py::load_npz``
的字段约定一致（也保留 ``features`` float16 以便复用现有工具）。
"""

from __future__ import annotations

import argparse
import functools
import glob
import gzip
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.env.action_space_std import (  # noqa: E402
    A_ACTIVATE,
    A_BUY,
    A_CANCEL,
    A_CHOOSE,
    A_DARK_GIFT,
    A_END,
    A_FREEZE,
    A_HERO_POWER,
    A_MAGNETIZE,
    A_MOVE,
    A_PLAY,
    A_REFRESH,
    A_SELL,
    A_UPGRADE,
    N_ACTIONS,
    N_BOARD,
    N_HAND,
    N_POS,
    N_SHOP,
    action_name,
)

#: 观测尺寸（冻结契约，与 hsbg/env/obs_std.py 一致）
OBS_FLOATS = 3227
OBS_CARDS = 124
OBS_TOTAL = OBS_FLOATS + OBS_CARDS
#: 默认 replay 目录（项目根下）
DEFAULT_OUT = os.path.join(ROOT, "runs", "human_play")

#: 卡图（HSJSON 原图）；加载失败时前端回退为文字占位，绝不阻塞操作。
ART_URL_TEMPLATE = "https://art.hearthstonejson.com/v1/orig/{card_id}.png"
#: 静态卡表（只读）：只用于补**卡面**关键词/效果全文，实例数值一律以引擎 view 为准。
CARDS_JSON_PATH = os.path.join(ROOT, "rust", "crates", "hsbg-engine", "data", "cards.json")

#: 种族英文名 -> 中文（与 ``hsbg/env/obs_std.py::RACE_NAMES`` 同序）。
RACE_ZH: Dict[str, str] = {
    "BEAST": "野兽", "DEMON": "恶魔", "DRAGON": "龙", "ELEMENTAL": "元素",
    "MECHANICAL": "机械", "MURLOC": "鱼人", "PIRATE": "海盗", "QUILBOAR": "野猪人",
    "UNDEAD": "亡灵", "ABERRATION": "畸变怪", "NAGA": "纳迦", "ALL": "全部",
}
#: 动态关键词（实例状态；引擎 ``minion_json.keywords``）。
KEYWORD_ZH: Dict[str, str] = {
    "TAUNT": "嘲讽", "DIVINE_SHIELD": "圣盾", "WINDFURY": "风怒", "REBORN": "复生",
    "VENOMOUS": "烈毒", "POISONOUS": "剧毒", "STEALTH": "潜行", "MAGNETIC": "磁力",
    "MEGA_WINDFURY": "超级风怒", "CLEAVE": "顺劈", "IMMUNE": "免疫",
    "IMMUNE_ATTACKING": "攻击时免疫",
}
#: 卡面静态关键词（不包含动态 12 位：战吼/亡语等不在其中）。
CARD_KEYWORD_ZH: Dict[str, str] = {
    "BATTLECRY": "战吼", "DEATHRATTLE": "亡语", "InvisibleDeathrattle": "亡语",
    "AVENGE": "复仇", "END_OF_TURN_TRIGGER": "回合结束时", "START_OF_COMBAT": "战斗开始时",
    "AURA": "光环", "CHOOSE_ONE": "抉择", "DISCOVER": "发现", "QUEST": "任务",
    "BACON_RALLY": "集结", "BACON_SPELLCRAFT_ID": "法术灌注", "TRIGGER_VISUAL": "触发效果",
    "CANT_BE_DESTROYED": "无法被摧毁", "CHARGE": "冲锋", "FRENZY": "暴怒",
    "OVERKILL": "超杀", "ADJACENT_BUFF": "相邻增益",
}
#: 动态关键词集合：卡面同名词不重复渲染，避免把已失去的圣盾“补回来”。
DYNAMIC_KEYWORDS = frozenset(KEYWORD_ZH)
KIND_ZH: Dict[str, str] = {
    "minion": "随从", "tavern_spell": "酒馆法术", "spell": "法术", "hero": "英雄",
    "hero_power": "英雄技能", "trinket_lesser": "小饰品", "trinket_greater": "大饰品",
    "dark_gift": "黑暗之赐", "quest": "任务", "quest_reward": "任务奖励",
}
#: 选择面板说明（Discover/抉择/饰品等），前端与 ``state_text`` 共用。
PENDING_KIND_ZH: Dict[str, str] = {
    "hero": "选择英雄", "discover": "发现（Discover）", "choose_one": "抉择",
    "target": "选择目标", "hero_power": "选择英雄技能", "trinket": "选择饰品",
    "quest": "选择任务", "timewarp": "时空扭曲酒馆",
}
PENDING_HINTS: Dict[str, str] = {
    "hero": "点击英雄卡确定本局英雄与技能",
    "discover": "发现：三选一，选中即免费获得/施放，不花金币",
    "choose_one": "抉择：选项 1/2（引擎暂不提供分支文本，不能按卡面顺序猜）",
    "target": "选择目标：按「区域+位置+名称」区分同名目标",
    "hero_power": "点击一个英雄技能（被动技能无需发动）",
    "trinket": "第 6/9 回合的饰品四选一（回合数≠酒馆星级）；价格见每张卡，weight 是出价权重不是胜率",
    "quest": "任务与奖励成对出现；目标/奖励以卡面为准",
    "timewarp": "时空扭曲酒馆：选项用时空币支付，leave 退出",
}


def art_url(card_id: Any) -> str:
    """卡图 URL（``card_id`` 为 ``cards.json`` 的字符串 id，如 ``BGS_121``）。"""
    cid = str(card_id or "").strip()
    return ART_URL_TEMPLATE.format(card_id=quote(cid, safe="")) if cid else ""


def keyword_label(name: Any) -> str:
    key = str(name or "")
    return KEYWORD_ZH.get(key) or CARD_KEYWORD_ZH.get(key) or key


def race_label(name: Any) -> str:
    key = str(name or "")
    return RACE_ZH.get(key) or key


@functools.lru_cache(maxsize=1)
def _static_card_db() -> Dict[str, Dict[str, Any]]:
    """``id -> 静态卡表条目``（只读；文件缺失/损坏时返回空表，退化为 view 字段）。"""
    path = os.environ.get("HSBRSIM_CARDS_JSON") or CARDS_JSON_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 - 静态补全失败不能影响手打
        return {}
    cards = data.get("cards") if isinstance(data, dict) else data
    return {
        str(c.get("id")): c
        for c in (cards or [])
        if isinstance(c, dict) and c.get("id")
    }


def static_keywords(card_id: Any) -> List[str]:
    """卡面静态关键词（已剔除动态 12 位同名词，如圣盾/嘲讽）。"""
    d = _static_card_db().get(str(card_id or "")) or {}
    out: List[str] = []
    for k in d.get("keywords") or []:
        if k in DYNAMIC_KEYWORDS or k in out:
            continue
        out.append(str(k))
    return out


def _kind_label(kind: Any) -> str:
    k = str(kind or "")
    return KIND_ZH.get(k, k)


def _breakdown_brief(src: Any) -> Dict[str, Any]:
    """数值拆解：基础/已记录 mods（含来源）/本局增益/临时/其余/已受伤。"""
    bd = src if isinstance(src, dict) else {}
    mods: List[Dict[str, Any]] = []
    for m in bd.get("mods") or []:
        if not isinstance(m, dict):
            continue
        s = m.get("src") or {}
        mods.append({
            "kind": m.get("kind") or "",
            "atk": m.get("atk"),
            "hp": m.get("hp"),
            "src_name": s.get("name_zh") or s.get("name") or "",
            "src_card_id": s.get("id") or "",
        })
    return {
        "base": list(bd.get("base") or []),
        "mods": mods,
        "this_game_bonus": list(bd.get("this_game_bonus") or []),
        "temporary": list(bd.get("temporary") or []),
        "other": list(bd.get("other") or []),
        "damage": bd.get("damage") or 0,
    }


def breakdown_text(bd: Dict[str, Any]) -> str:
    """把 breakdown 压成一行中文（数值全部来自引擎记录，不反算）。"""
    if not bd:
        return ""
    parts: List[str] = []
    base = bd.get("base") or []
    if len(base) == 2:
        parts.append("基础 %s/%s" % (base[0], base[1]))
    for m in bd.get("mods") or []:
        src = m.get("src_name") or m.get("kind") or "?"
        parts.append("%s %+d/%+d" % (src, int(m.get("atk") or 0), int(m.get("hp") or 0)))
    for key, name in (("this_game_bonus", "本局"), ("temporary", "临时"), ("other", "其他")):
        pair = bd.get(key) or []
        if len(pair) == 2 and (pair[0] or pair[1]):
            parts.append("%s %+d/%+d" % (name, int(pair[0] or 0), int(pair[1] or 0)))
    if bd.get("damage"):
        parts.append("已受伤 %d" % int(bd["damage"]))
    return " · ".join(parts)


def _attached_brief(items: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for a in items or []:
        if isinstance(a, dict):
            kind = a.get("kind") or ""
            cid = a.get("id") or ""
            label = _kind_label(kind)
            if kind == "dark_gift":
                label = "黑暗之赐"
            elif str(cid).startswith("BG20_GEM"):
                label = "鲜血宝石"
            elif "MAGNETIC" in ((_static_card_db().get(cid) or {}).get("keywords") or []):
                label = "磁力"
            out.append({
                "card_id": cid,
                "art": art_url(cid),
                "kind": kind,
                "kind_label": label,
                "name": a.get("name") or "",
                "name_zh": a.get("name_zh") or a.get("name") or "",
                "text": a.get("text_zh") or a.get("text") or "",
                "cost": a.get("cost"),
            })
        else:
            out.append({"card_id": "", "art": "", "kind": "", "kind_label": "附件",
                        "name": str(a), "name_zh": str(a), "text": "", "cost": None})
    return out


def _card_brief(it: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """卡牌/随从的完整展示字段（静态卡面 + 实例数值/关键词/附件/拆解）。"""
    it = it or {}
    cid = str(it.get("id") or "")
    kind = str(it.get("kind") or "")
    typ = str(it.get("type") or kind or "minion")
    dyn_kw = [str(k) for k in (it.get("keywords") or [])]
    races = [str(x) for x in (it.get("races") or [])]
    card_kw = static_keywords(cid) if cid else []
    golden = bool(it.get("golden"))
    tier = int(it.get("tier") or 0)
    text = it.get("text_zh") or it.get("text") or ""
    bd = _breakdown_brief(it.get("breakdown"))
    golden_text = ""
    gt = it.get("golden_text")
    if isinstance(gt, dict):
        golden_text = gt.get("text_zh") or gt.get("text") or ""
    attached = _attached_brief(it.get("attached"))
    return {
        "name": it.get("name") or "",
        "name_zh": it.get("name_zh") or it.get("name") or "",
        "card_id": cid,
        "art": art_url(cid),
        "kind": kind,
        "kind_label": _kind_label(kind or typ),
        "type": typ,
        "is_minion": typ == "minion",
        "tier": tier,
        "tier_label": ("★%d" % tier) if tier else "—",
        "atk": it.get("atk"),
        "hp": it.get("hp"),
        "max_hp": it.get("max_hp", it.get("hp")),
        "base_atk": it.get("base_atk"),
        "base_hp": it.get("base_hp"),
        "temp_atk": it.get("temp_atk"),
        "temp_hp": it.get("temp_hp"),
        "races": races,
        "race_labels": [race_label(r) for r in races],
        "race_text": "/".join(race_label(r) for r in races) if races else "无",
        "golden": golden,
        "golden_label": "金色" if golden else "",
        "keywords": dyn_kw,
        "keyword_labels": [keyword_label(k) for k in dyn_kw],
        "card_keywords": card_kw,
        "card_keyword_labels": [keyword_label(k) for k in card_kw],
        "text": text,
        "text_note": "卡面" if text else "",
        "text_is_live": bool(it.get("live_text")),
        "golden_text": golden_text,
        "cost": it.get("cost"),
        "play_cost": it.get("play_cost"),
        "activate_cost": it.get("activate_cost"),
        "unplayable": bool(it.get("unplayable")),
        "implemented": it.get("implemented"),
        "shield_hits": it.get("shield_hits"),
        "counter": it.get("counter"),
        "attached": attached,
        "attached_names": [a["name_zh"] for a in attached],
        "breakdown": bd,
        "breakdown_text": breakdown_text(bd),
    }


# ══════════════════════════════════════════════════════════════════════
# 神明（Deity）：名字 + atk/hp + 金卡/复生 + 效果全文 + 结构化触发要求
# ══════════════════════════════════════════════════════════════════════

#: 触发阶段（结构化字段；与「招募 / 战斗 / 回合结束」同口径）。
DEITY_PHASE_ZH: Dict[str, str] = {
    "recruit": "招募", "combat": "战斗", "end_of_turn": "回合结束",
}
#: 兜底唤醒门槛；实际值优先取引擎 ``RulesConfig.deity_threshold``（默认 4）。
DEITY_THRESHOLD_FALLBACK = 4

#: 神明脚本行为（与 ``flow.rs::DEITIES`` 的 2 个神明一一对应）。
#: 卡面只写了「神明 / 被唤醒后 / 亡语」，**唤醒条件**只在引擎脚本里：
#: ``engine.rs::check_deity``（本场战斗畸变怪累计死亡 ≥ cfg.deity_threshold）+
#: ``content/mod.rs::deity_awakened``（克苏恩均分属性）/
#: ``content/minions.rs::yshaarj``（亚煞极亡语）。卡表 id 来自 ``Game.view`` 的
#: ``me.deity.card``，名字/文本/种族/星级/类型用 ``cards.json`` 补全。
DEITY_RULES: Dict[str, Dict[str, Any]] = {
    "BGFYM_000": {
        "awaken": "唤醒克苏恩：把它召唤到己方战场最右侧（属性 = 面板 atk/hp；金卡使用金色卡）",
        "after_awaken": "把它的属性值均分给你的其他随从；金卡按它的双倍属性值分配（余数按 1 点随机分配）",
        "source_ref": "engine.rs::check_deity + content/mod.rs::deity_awakened",
        "golden_mult": 2,
    },
    "BGFYM_011": {
        "awaken": "唤醒亚煞极：把它召唤到己方战场最右侧（属性 = 面板 atk/hp；金卡使用金色卡）",
        "deathrattle": "召唤你在本场战斗中死亡的前 2 个畸变怪（金卡 4 个），"
                       "并使其具有其最大属性值（神明除外）",
        "source_ref": "engine.rs::check_deity + content/minions.rs::yshaarj",
        "golden_mult": 2,
        "revive": 2,
    },
}


def normal_card_id(card_id: Any) -> str:
    """去除金卡后缀（``BGFYM_000_G`` -> ``BGFYM_000``）。"""
    cid = str(card_id or "")
    return cid[:-2] if cid.endswith("_G") else cid


@functools.lru_cache(maxsize=1)
def _engine_default_config() -> Dict[str, Any]:
    """引擎默认 ``RulesConfig``（只读；用于取 ``deity_threshold`` 等数值）。"""
    try:
        return json.loads(load_engine().default_config_json())
    except Exception:  # noqa: BLE001 - 配置读取失败不能影响手打
        return {}


@functools.lru_cache(maxsize=1)
def deity_buff_card_ids() -> Tuple[str, ...]:
    """静态卡表中卡面提到「神明 / Deity」的卡 id（含金卡与衍生；只用于展示数量）。"""
    out: List[str] = []
    for cid, c in sorted(_static_card_db().items()):
        text = "%s %s" % (c.get("text_zh") or "", c.get("text") or "")
        if "神明" in text or "Deity" in text:
            out.append(cid)
    return tuple(out)


def _deity_threshold(cfg: Optional[Dict[str, Any]] = None) -> int:
    """唤醒门槛：会话配置 > 引擎默认配置 > 兜底 4。"""
    raw: Any = (cfg or {}).get("deity_threshold")
    if raw is None:
        raw = _engine_default_config().get("deity_threshold")
    try:
        return int(raw) if raw is not None else DEITY_THRESHOLD_FALLBACK
    except (TypeError, ValueError):
        return DEITY_THRESHOLD_FALLBACK


def deity_brief(raw: Optional[Dict[str, Any]],
                cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """神明面板数据：名字/atk/hp/金卡/复生/效果全文/结构化触发要求/数值。

    ``raw`` 来自 ``Game.view(...)["me"]["deity"]``（``card/atk/hp/golden/reborn``）。
    卡面文本以 view 为准，缺失时用 ``cards.json`` 补；触发条件卡面没写，由引擎脚本
    推导并标 ``脚本``；未收录的神明 id 退化为 ``推断``。无神明时返回
    ``{"present": False, "label": "本局无神明", ...}``。
    """
    threshold = _deity_threshold(cfg)
    n_buff = len(deity_buff_card_ids())
    if not isinstance(raw, dict) or not raw.get("card"):
        return {
            "present": False,
            "label": "本局无神明",
            "name": "", "name_zh": "", "card_id": "", "art": "",
            "atk": None, "hp": None, "golden": False, "reborn": False,
            "golden_label": "", "reborn_label": "",
            "text": "", "text_note": "", "effect_text": "", "effect_source": "",
            "tier": 0, "tier_label": "", "type": "", "kind": "", "kind_label": "",
            "races": [], "race_labels": [], "race_text": "无",
            "triggers": [], "numbers": [],
            "threshold": threshold, "buff_card_count": n_buff,
            "hint": "本局大厅没有畸变怪（ABERRATION）；神明只在含畸变怪的大厅出现",
        }

    card = _card_brief(raw.get("card"))
    cid = normal_card_id(card.get("card_id"))
    meta = _static_card_db().get(cid) or {}
    golden = bool(raw.get("golden"))
    reborn = bool(raw.get("reborn"))
    atk, hp = raw.get("atk"), raw.get("hp")
    golden_id = str(meta.get("golden_id") or (cid + "_G"))
    golden_meta = _static_card_db().get(golden_id) or {}

    # cards.json 只补静态字段；view 有就以 view 为准。
    name = card.get("name") or meta.get("name") or ""
    name_zh = card.get("name_zh") or meta.get("name_zh") or name
    text = card.get("text") or meta.get("text_zh") or meta.get("text") or ""
    text_note = "卡面" if text else ""
    if golden and golden_meta.get("text_zh"):
        text, text_note = golden_meta["text_zh"], "金卡卡面"
    races = list(card.get("races") or meta.get("races") or [])
    tier = card.get("tier") or int(meta.get("tier") or 0)
    typ = meta.get("type") or card.get("type") or card.get("kind") or "minion"

    rule = DEITY_RULES.get(cid)
    triggers: List[Dict[str, Any]] = []
    if rule:
        triggers.append({
            "phase": "combat", "phase_label": DEITY_PHASE_ZH["combat"],
            "condition": "本场战斗中你的畸变怪累计死亡 ≥ %d 只" % threshold,
            "condition_source": "脚本",
            "effect": rule["awaken"],
            "effect_source": "脚本",
            "source": "脚本",
            "source_ref": rule["source_ref"],
            "detail": "唤醒阈值来自引擎 RulesConfig.deity_threshold（默认 %d），卡面没有写" % threshold,
        })
        if rule.get("after_awaken"):
            triggers.append({
                "phase": "combat", "phase_label": DEITY_PHASE_ZH["combat"],
                "condition": "神明被唤醒（召唤）后",
                "condition_source": "脚本",
                "effect": rule["after_awaken"],
                "effect_source": "脚本",
                "source": "脚本",
                "source_ref": rule["source_ref"],
                "detail": "金卡按双倍属性值分配（脚本 `me.g()`）",
            })
        if rule.get("deathrattle"):
            triggers.append({
                "phase": "combat", "phase_label": DEITY_PHASE_ZH["combat"],
                "condition": "神明死亡（亡语结算）",
                "condition_source": "卡面",
                "effect": rule["deathrattle"],
                "effect_source": "脚本",
                "source": "卡面",
                "source_ref": rule["source_ref"],
                "detail": "「最大属性值」= 该随从本场战斗达到过的峰值（peak_atk/peak_hp）",
            })
    else:
        triggers.append({
            "phase": "combat", "phase_label": DEITY_PHASE_ZH["combat"],
            "condition": "卡面未写唤醒条件（引擎未收录该神明 id，推断为战斗内唤醒）",
            "condition_source": "推断",
            "effect": text or "卡面/脚本均未收录",
            "effect_source": "卡面" if text else "推断",
            "source": "推断",
            "source_ref": "cards.json 无对应神明脚本",
            "detail": "未收录 id：只展示卡面，不编造触发条件",
        })
    if n_buff:
        triggers.append({
            "phase": "recruit", "phase_label": DEITY_PHASE_ZH["recruit"],
            "condition": "打出/触发卡面提到「神明」的卡（%d 张，含金卡/衍生）" % n_buff,
            "condition_source": "卡面",
            "effect": "你的神明获得对应属性值（面板 atk/hp 随之变化，本面板实时同步）",
            "effect_source": "卡面",
            "source": "卡面",
            "source_ref": "cards.json 静态卡表（文本检索）",
            "detail": "属性成长不是唤醒；只影响唤醒后的身材",
        })

    numbers: List[Dict[str, Any]] = [
        {"key": "atk_hp", "label": "面板属性", "value": "%s/%s" % (atk, hp),
         "source": "引擎 view"},
    ]
    if meta:
        numbers.append({
            "key": "base", "label": "初始属性（卡面）",
            "value": "%s/%s（金卡 %s/%s）" % (
                meta.get("atk"), meta.get("hp"),
                golden_meta.get("atk", meta.get("atk")), golden_meta.get("hp", meta.get("hp"))),
            "source": "卡面",
        })
    numbers.append({
        "key": "threshold", "label": "唤醒门槛（本场畸变怪死亡）",
        "value": str(threshold), "source": "引擎 config.deity_threshold",
    })
    if cid == "BGFYM_000" and rule and rule.get("golden_mult"):
        numbers.append({
            "key": "golden_mult", "label": "金卡均分倍率",
            "value": "×%s" % rule["golden_mult"], "source": "脚本",
        })
    if rule and rule.get("revive"):
        numbers.append({
            "key": "revive", "label": "亡语复活数量",
            "value": "%d 只（金卡 %d 只）" % (rule["revive"], rule["revive"] * 2),
            "source": "卡面+脚本",
        })
    if n_buff:
        numbers.append({
            "key": "buff_cards", "label": "可提升神明的卡",
            "value": "%d 张" % n_buff, "source": "卡面（卡表检索）",
        })

    out = dict(card)
    out.update({
        "present": True,
        "label": "%s %s/%s" % (name_zh, atk, hp),
        "name": name, "name_zh": name_zh,
        "card_id": card.get("card_id") or cid,
        "atk": atk, "hp": hp,
        "golden": golden, "golden_label": "金色" if golden else "",
        "reborn": reborn, "reborn_label": "复生" if reborn else "",
        "text": text, "text_note": text_note,
        "effect_text": text, "effect_source": text_note or ("脚本" if rule else "推断"),
        "tier": tier, "tier_label": ("★%d" % tier) if tier else "—",
        "type": typ, "kind": card.get("kind") or "minion",
        "kind_label": card.get("kind_label") or "随从",
        "races": races,
        "race_labels": [race_label(r) for r in races],
        "race_text": "/".join(race_label(r) for r in races) if races else "无",
        "triggers": triggers, "numbers": numbers,
        "threshold": threshold, "buff_card_count": n_buff,
        "hint": "唤醒门槛：本场战斗畸变怪死亡 ≥ %d 只" % threshold,
    })
    return out


# ══════════════════════════════════════════════════════════════════════
# 引擎与动作
# ══════════════════════════════════════════════════════════════════════


def load_engine() -> Any:
    """导入 Rust 主引擎 ``hsbg_engine``（未构建时给出可执行提示）。"""
    try:
        import hsbg_engine as E  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "hsbg_engine 不可用：请先 `cd rust && python -m pip install -e .`"
            "（见 docs/RUST_ENGINE.md）"
        ) from exc
    return E


def _parse_config(config_json: Any) -> Dict[str, Any]:
    """解析 ``--config-json`` / ``GameSession(config_json=...)``：JSON 对象或 dict。"""
    if config_json in (None, ""):
        return {}
    if isinstance(config_json, str):
        cfg = json.loads(config_json)
    elif isinstance(config_json, dict):
        cfg = dict(config_json)
    else:
        raise ValueError(f"config_json 必须是 JSON 对象/字符串，得到 {type(config_json)!r}")
    if not isinstance(cfg, dict):
        raise ValueError("config_json 必须是 JSON 对象")
    return cfg


class IllegalAction(Exception):
    """非法/不可执行的 action（HTTP 层转 400）。"""


def _hero_brief(it: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not it:
        return None
    d = _card_brief(it)
    d["armor"] = it.get("armor")
    d["hp"] = it.get("hp")
    power = it.get("hero_power")
    if power:
        d["power"] = {
            "name_zh": power.get("name_zh") or power.get("name") or "",
            "text": power.get("text_zh") or power.get("text") or "",
        }
    return d


def _power_brief(it: Dict[str, Any]) -> Dict[str, Any]:
    d = _card_brief(it)
    d.update({
        "slot": int(it.get("slot") or 0),
        "action": it.get("action"),
        "price": it.get("price"),
        "usable": bool(it.get("usable")),
        "passive": bool(it.get("passive")),
        "uses_turn": it.get("uses_turn"),
    })
    return d


def _price_label(price: Any, costs_health: bool = False) -> str:
    if price is None:
        return "不可购买"
    return f"{price} 金" + ("（以生命支付）" if costs_health else "")


def _combat_brief(c: Dict[str, Any], seat: int, frames: bool = False) -> Dict[str, Any]:
    """战斗记录（从 ``seat`` 视角解码胜/负/平；绝不推断全局末三条）。"""
    a, b = c.get("a"), c.get("b")
    winner = c.get("winner")
    mine = (a == seat) or (b == seat)
    side = 0 if a == seat else 1
    result = ""
    if mine:
        if winner == 0 or winner == 1:
            result = "win" if int(winner) == side else "loss"
        else:
            result = "tie"
    opp = None
    if mine:
        opp = b if side == 0 else a
    out: Dict[str, Any] = {
        "turn": c.get("turn"),
        "a": a,
        "b": b,
        "winner": winner,
        "damage": c.get("damage"),
        "truncated": bool(c.get("truncated")),
        "mine": mine,
        "opponent": opp,
        "result": result,
        "result_label": {"win": "胜", "loss": "负", "tie": "平"}.get(result, ""),
    }
    if frames:
        fr = []
        for f in (c.get("frames") or [])[-12:]:
            boards = f.get("boards") or [[], []]
            fr.append({
                "log": list(f.get("log") or []),
                "attacks": list(f.get("attacks") or []),
                "boards": [
                    [_card_brief(m) for m in (side_boards or [])]
                    for side_boards in (boards if len(boards) == 2 else [[], []])
                ],
            })
        out["frames"] = fr
        out["frame_count"] = len(c.get("frames") or [])
    return out


def _pending_brief(pend: Optional[Dict[str, Any]], mask: List[int],
                   eid_names: Dict[int, str]) -> Optional[Dict[str, Any]]:
    """把 ``me.pending`` 转成前端可直接渲染的结构（含合法 Choose action 下标）。"""
    if not pend:
        return None

    def choose_action(i: int) -> Optional[int]:
        a = A_CHOOSE + i
        return a if 0 <= a < N_ACTIONS and mask[a] else None

    kind = pend.get("kind") or ""
    out: Dict[str, Any] = {
        "kind": kind,
        "kind_label": PENDING_KIND_ZH.get(kind, "选择：" + kind),
        "hint": PENDING_HINTS.get(kind, ""),
        "source": _card_brief(pend.get("source")),
        "options": [],
        "targets": [],
        "leave_action": None,
        # 引擎只在可取消时把 Cancel 放进掩码，因此直接由掩码派生
        "cancel_action": (A_CANCEL if (0 <= A_CANCEL < N_ACTIONS and mask[A_CANCEL]) else None),
        "free": bool(pend.get("free")),
        "replace": _card_brief(pend.get("replace")) if pend.get("replace") else None,
        "slot": pend.get("slot"),
        "major": pend.get("major"),
        "chronum": pend.get("chronum"),
    }
    options = pend.get("options") or []
    if kind == "target":
        for i, eid in enumerate(pend.get("targets") or []):
            out["targets"].append({
                "index": i,
                "eid": eid,
                "name": eid_names.get(eid, f"#{eid}"),
                "action": choose_action(i),
                "action_reason": "" if choose_action(i) is not None else "该目标不可选（不在掩码）",
            })
    else:
        for i, opt in enumerate(options):
            item = _card_brief(opt)
            item["index"] = i
            item["action"] = choose_action(i)
            if item["action"] is None:
                item["action_reason"] = "该选项当前不可选（引擎掩码未放行）"
            if kind == "hero":
                item["armor"] = opt.get("armor")
                item["hp"] = opt.get("hp")
                power = opt.get("hero_power")
                if power:
                    item["power"] = {
                        "name_zh": power.get("name_zh") or power.get("name") or "",
                        "text": power.get("text_zh") or power.get("text") or "",
                    }
            if kind == "choose_one":
                item["branch_label"] = "选项 %d" % (i + 1)
            if opt.get("cost") is not None:
                item["cost"] = opt.get("cost")
            if opt.get("base_cost") is not None:
                item["base_cost"] = opt.get("base_cost")
            if opt.get("weight") is not None:
                item["weight"] = opt.get("weight")
            if opt.get("chronum_cost") is not None:
                item["chronum_cost"] = opt.get("chronum_cost")
            if opt.get("goal") is not None:
                item["goal"] = opt.get("goal")
            if opt.get("reward") is not None:
                item["reward"] = _card_brief(opt.get("reward"))
            if kind == "trinket":
                item["major"] = bool(pend.get("major"))
                item["price_label"] = ("免费" if pend.get("free")
                                       else ("%s 金" % opt.get("cost")
                                             if opt.get("cost") is not None else "价格未知"))
            out["options"].append(item)
    leave = pend.get("leave")
    if isinstance(leave, int) and 0 <= leave < 16:
        out["leave_action"] = choose_action(leave)
    return out


# ══════════════════════════════════════════════════════════════════════
# 对局会话：人类座位 + 7 个引擎 bot
# ══════════════════════════════════════════════════════════════════════


class GameSession:
    """一局人类 vs 7 bot；每次 ``act`` 落一条 BC 决策记录。"""

    def __init__(self, seed: int, seat: int = 0, out_dir: str = DEFAULT_OUT,
                 engine: Any = None, config_json: Any = None) -> None:
        self.E = engine or load_engine()
        self.seat = int(seat)
        if not 0 <= self.seat < 8:
            raise ValueError(f"seat 必须在 0..7，得到 {seat}")
        self.out_dir = os.path.abspath(out_dir)
        os.makedirs(self.out_dir, exist_ok=True)
        self._stamp_seq = 0
        self.seed = int(seed)
        # 引擎 RulesConfig（只读透传；用于 --aberration/--config-json 与测试的确定性大厅）。
        self.config = _parse_config(config_json)
        self.new_game(self.seed)

    # ── 开局 / 落盘 ──────────────────────────────────────────────────
    def new_game(self, seed: Optional[int] = None) -> None:
        """开新局：新 replay 文件 + 清空计数；bot 先选完英雄。"""
        if seed is None:
            seed = self.seed
        self.seed = int(seed)
        if self.config:
            self.game = self.E.Game(seed=self.seed,
                                    config_json=json.dumps(self.config, ensure_ascii=False))
        else:
            self.game = self.E.Game(seed=self.seed)
        self.decisions = 0
        self.steps = 0
        self.over = False
        # 引擎只保留最近若干条 combats；人类被淘汰后继续打时，缓存自己的最后一场战果
        self.last_my_combat: Optional[Dict[str, Any]] = None
        self.placement = 0
        self.placements: List[int] = []
        self.started = time.time()
        self.replay_path = self._new_replay_path()
        with gzip.open(self.replay_path, "wt", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "type": "meta",
                "engine": "hsbg_engine",
                "game_version": str(self.E.game_version()),
                "seed": self.seed,
                "seat": self.seat,
                "n_actions": N_ACTIONS,
                "obs_floats": OBS_FLOATS,
                "obs_cards": OBS_CARDS,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, ensure_ascii=False) + "\n")
        # 让 7 个 bot 先选英雄，界面上一开始就能看到对手英雄。
        self._bots_pick_heroes()

    def _new_replay_path(self) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        while True:
            self._stamp_seq += 1
            name = f"human_{stamp}_seed{self.seed}_{self._stamp_seq:02d}.jsonl.gz"
            path = os.path.join(self.out_dir, name)
            if not os.path.exists(path):
                return path

    def _append_line(self, payload: Dict[str, Any]) -> None:
        with gzip.open(self.replay_path, "at", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _bots_pick_heroes(self) -> None:
        g = self.game
        for p in range(int(g.num_players)):
            if p == self.seat or not g.needs_action(p):
                continue
            g.bot_play(p)
            self.steps += 1

    def _finish(self) -> None:
        """对局结束：写 summary 行（只写一次）。"""
        if self.over:
            return
        g = self.game
        self.over = bool(g.is_over())
        if not self.over:
            return
        try:
            self.placements = [int(x) for x in g.placements()]
        except Exception:  # noqa: BLE001 - 防御：老引擎可能没有 placements
            self.placements = []
        if len(self.placements) > self.seat:
            self.placement = int(self.placements[self.seat])
        self._append_line({
            "type": "summary",
            "seed": self.seed,
            "seat": self.seat,
            "placement": self.placement,
            "placements": self.placements,
            "decisions": self.decisions,
            "steps": self.steps,
            "turns": int(g.turn),
            "seconds": round(time.time() - self.started, 3),
        })

    # ── 引擎状态 ─────────────────────────────────────────────────────
    def _obs(self) -> Tuple[Any, Any]:
        import numpy as np  # noqa: PLC0415

        f_raw, c_raw = self.game.observe(self.seat)
        f = np.frombuffer(f_raw, dtype="<f4").copy().astype(np.float32)
        c = np.frombuffer(c_raw, dtype="<i4").copy().astype(np.int32)
        if f.size != OBS_FLOATS or c.size != OBS_CARDS:
            raise RuntimeError(f"观测尺寸异常：{f.size}+{c.size}")
        return f, c

    def _mask(self) -> List[int]:
        raw = self.game.legal_mask(self.seat)
        import numpy as np  # noqa: PLC0415

        m = np.frombuffer(raw, dtype=np.uint8).astype(np.int8).tolist()
        if len(m) != N_ACTIONS:
            raise RuntimeError(f"动作掩码长度 {len(m)} != {N_ACTIONS}")
        return m

    def advance_bots(self, max_steps: int = 20000) -> None:
        """把非人类座位全部推进到「人类需要行动」或对局结束。"""
        g = self.game
        guard = 0
        while not g.is_over():
            if g.needs_action(self.seat):
                break
            acted = False
            for p in range(int(g.num_players)):
                if p == self.seat or not g.needs_action(p):
                    continue
                g.bot_play(p)
                self.steps += 1
                acted = True
                if g.is_over():
                    break
            if not acted:
                break
            guard += 1
            if guard > int(max_steps):
                raise RuntimeError(f"bot 推进超过 {max_steps} 轮，疑似死循环")
        if g.is_over():
            self._finish()

    # ── 状态 / 动作 ─────────────────────────────────────────────────
    def state(self) -> Dict[str, Any]:
        """返回前端所需的完整状态（JSON 可序列化）。"""
        g = self.game
        v = json.loads(g.view(self.seat))
        me = v.get("me") or {}
        mask = self._mask()
        legal = [i for i, x in enumerate(mask) if x]
        phase = str(v.get("phase") or "")

        # eid -> 名字（target pending 的 option 是 EntityId，可能落在场上/酒馆里）
        eid_names: Dict[int, str] = {}
        for it in me.get("board") or []:
            if it.get("eid") is not None:
                eid_names[int(it["eid"])] = it.get("name_zh") or it.get("name") or ""
        for it in me.get("shop") or []:
            if it.get("eid") is not None:
                eid_names[int(it["eid"])] = it.get("name_zh") or it.get("name") or ""
        for o in v.get("opponents") or []:
            for it in o.get("seen_board") or []:
                if it.get("eid") is not None:
                    eid_names[int(it["eid"])] = it.get("name_zh") or it.get("name") or ""
        # target 名称需要 eid map，重建一次
        pending = _pending_brief(me.get("pending"), mask, eid_names)

        def legal_a(a: Optional[int]) -> bool:
            return a is not None and 0 <= int(a) < N_ACTIONS and bool(mask[int(a)])

        gold = int(me.get("gold") or 0)
        hand_limit = int(me.get("hand_limit") or 10)
        hand_len = len(me.get("hand") or [])
        dark_raw = me.get("dark_gift") or {}

        # 酒馆
        shop = []
        for i, it in enumerate(me.get("shop") or []):
            e = _card_brief(it)
            price = it.get("price")
            buy = (A_BUY + i) if (i < N_SHOP and legal_a(A_BUY + i)) else None
            if buy is not None:
                buy_reason = ""
            elif price is not None and gold < int(price):
                buy_reason = f"金币不足：需要 {price} 金，现有 {gold}"
            elif hand_len >= hand_limit:
                buy_reason = f"手牌已满（{hand_len}/{hand_limit}）"
            elif phase != "recruit":
                buy_reason = f"当前阶段（{phase}）不能购买"
            else:
                buy_reason = "当前不可购买（引擎掩码未放行）"
            e.update({
                "slot": i,
                "slot_label": f"酒馆 {i + 1} 号位",
                "price": price,
                "price_label": _price_label(price, bool(it.get("costs_health"))),
                "costs_health": bool(it.get("costs_health")),
                "frozen": bool(it.get("frozen")),
                "kept": bool(it.get("kept")),
                "owned": it.get("owned"),
                "triple_need": it.get("triple_need"),
                "buy": buy,
                "buy_action": (A_BUY + i) if i < N_SHOP else None,
                "buy_reason": buy_reason,
            })
            shop.append(e)

        # 手牌（打出位置 / 磁力目标都由掩码给出）
        hand = []
        for i, it in enumerate(me.get("hand") or []):
            e = _card_brief(it)
            plays = [
                {"pos": j, "action": A_PLAY + i * N_POS + j}
                for j in range(N_POS) if legal_a(A_PLAY + i * N_POS + j)
            ]
            mags = [
                {"board": j, "action": A_MAGNETIZE + i * N_BOARD + j}
                for j in range(N_BOARD) if legal_a(A_MAGNETIZE + i * N_BOARD + j)
            ]
            e.update({
                "index": i,
                "hid": it.get("hid"),
                "locked": it.get("locked") or 0,
                "locked_label": (f"锁定 {int(it.get('locked'))} 回合"
                                 if int(it.get("locked") or 0) > 0 else ""),
                "held": bool(it.get("held")),
                "temporary": bool(it.get("temporary")),
                "hand_slot_label": f"手牌 {i + 1} 号位",
                "play_cost": it.get("play_cost", 0),
                "play_cost_label": f"实际打出 {it.get('play_cost', 0)} 金",
                "play": plays,
                "magnetize": mags,
                "play_reason": "" if plays else "现在不能打出（无合法位置/目标）",
                "magnetize_reason": "" if mags else "没有可磁力吸附的机械",
            })
            hand.append(e)

        # 场上
        board = []
        for i, it in enumerate(me.get("board") or []):
            e = _card_brief(it)
            moves = [
                {"to": j, "action": A_MOVE + i * N_BOARD + j}
                for j in range(N_BOARD)
                if j != i and legal_a(A_MOVE + i * N_BOARD + j)
            ]
            sell = (A_SELL + i) if legal_a(A_SELL + i) else None
            activate = (A_ACTIVATE + i) if legal_a(A_ACTIVATE + i) else None
            e.update({
                "index": i,
                "position_label": f"{i + 1} 号位",
                "eid": it.get("eid"),
                "sell": sell,
                "sell_reason": "" if sell is not None else "当前不能出售",
                "activate": activate,
                "activate_cost": it.get("activate_cost"),
                "activate_reason": ("" if activate is not None else
                                    ("该随从没有可发动技能" if it.get("activate_cost") is None
                                     else "当前不能发动（掩码未放行）")),
                "move": moves,
                "attached": _attached_brief(it.get("attached")),
                "attached_names": [a["name_zh"] for a in _attached_brief(it.get("attached"))],
            })
            board.append(e)

        powers = [_power_brief(p) for p in (me.get("hero_powers") or [])]

        # 饰品（已获得，小/大）与持续效果：名称+类型+效果摘要（不做“恰好两个槽”假设）
        trinkets = [_card_brief(t) for t in (me.get("trinkets") or [])]
        for t in trinkets:
            t["slot_tag"] = ("小饰品" if t["kind"] == "trinket_lesser"
                             else ("大饰品" if t["kind"] == "trinket_greater"
                                   else t["kind_label"]))
        effects = [
            {"card": _card_brief(x.get("card")), "stacks": x.get("stacks")}
            for x in (me.get("effects") or []) if isinstance(x, dict)
        ]
        deity_raw = me.get("deity") or None
        # 始终给出结构化的神明面板（无神明时 present=False + “本局无神明”）。
        deity = deity_brief(deity_raw, cfg=getattr(self, "config", None))

        # 黑暗之赐：cost/uses/max_uses/tiers + 使用按钮与不可用原因
        dark_gift = dict(dark_raw)
        dark_enabled = legal_a(A_DARK_GIFT)
        dg_cost = dark_raw.get("cost")
        dg_uses = int(dark_raw.get("uses") or 0)
        dg_max = int(dark_raw.get("max_uses") or 0)
        dg_turn = v.get("turn") or 0
        dg_tiers = [int(t) for t in (dark_raw.get("tiers") or [])]
        dg_next = [int(t) for t in (dark_raw.get("next_tiers") or [])]
        if dark_enabled:
            dg_reason = ""
        elif dark_raw.get("unlock_turn") and int(dg_turn) < int(dark_raw["unlock_turn"]):
            dg_reason = f"第 {dark_raw['unlock_turn']} 回合解锁（当前第 {dg_turn} 回合）"
        elif dark_raw.get("used_this_turn"):
            dg_reason = "本回合已使用"
        elif dg_max and dg_uses >= dg_max:
            dg_reason = f"已达上限（{dg_uses}/{dg_max}）"
        elif dg_cost is not None and gold < int(dg_cost):
            dg_reason = f"金币不足：需要 {dg_cost} 金，现有 {gold}"
        elif phase != "recruit":
            dg_reason = f"当前阶段（{phase}）不可使用"
        else:
            dg_reason = "当前不可用（引擎掩码未放行）"
        dark_gift.update({
            "action": A_DARK_GIFT,
            "enabled": dark_enabled,
            "button_label": "黑暗之赐",
            "cost_label": (f"{dg_cost} 金" if dg_cost is not None else "费用未知"),
            "uses_label": f"{dg_uses}/{dg_max}" if dg_max else str(dg_uses),
            "tiers_label": "/".join(str(t) for t in dg_tiers) or "—",
            "next_tiers_label": "/".join(str(t) for t in dg_next) or "—",
            "reason": dg_reason,
        })

        hud = {
            "hero": _hero_brief(me.get("hero")),
            "hero_power": _hero_brief(me.get("hero_power")),
            "health": me.get("health"),
            "armor": me.get("armor"),
            "alive": bool(me.get("alive")),
            "gold": me.get("gold"),
            "max_gold": me.get("max_gold"),
            "max_gold_bonus": me.get("max_gold_bonus"),
            "gold_next_turn": me.get("gold_next_turn"),
            "tier": me.get("tier"),
            "upgrade_price": me.get("upgrade_price"),
            "can_upgrade_tier": bool(me.get("can_upgrade_tier", True)),
            "refresh_price": me.get("refresh_price"),
            "minion_price": me.get("minion_price"),
            "free_refreshes": me.get("free_refreshes"),
            "frozen": bool(me.get("frozen")),
            "ended_turn": bool(me.get("ended_turn")),
            "win_streak": me.get("win_streak"),
            "last_damage": me.get("last_damage"),
            "last_warband": me.get("last_warband"),
            "placement": me.get("placement"),
            "hand_limit": me.get("hand_limit"),
            "hand_queue_len": len(me.get("hand_queue") or []),
            "turn": v.get("turn"),
            "phase": phase,
            "alive_players": v.get("alive"),
            "lobby_races": v.get("lobby_races") or [],
            "lobby_races_zh": [race_label(r) for r in (v.get("lobby_races") or [])],
            "next_is_ghost": bool(me.get("next_is_ghost")),
            "last_opponent": me.get("last_opponent"),
            "next_opponent": me.get("next_opponent"),
            "trinkets": trinkets,
            "effects": effects,
            "deity": deity,
            "dark_gift": dark_gift,
        }

        def gold_reason(price: Any, what: str) -> str:
            try:
                p = int(price)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                return ""
            if gold < p:
                return f"金币不足：{what}需要 {p} 金，现有 {gold}"
            return ""

        refresh_price = me.get("refresh_price")
        free_refreshes = int(me.get("free_refreshes") or 0)
        upgrade_price = me.get("upgrade_price")
        tier_now = int(me.get("tier") or 0)
        refresh_ok = legal_a(A_REFRESH)
        upgrade_ok = legal_a(A_UPGRADE)
        end_ok = legal_a(A_END)
        freeze_ok = legal_a(A_FREEZE)
        buttons = [
            {"key": "end", "label": "结束回合", "action": A_END, "enabled": end_ok,
             "price": 0, "hint": "结算战斗并进入下一回合",
             "reason": "" if end_ok else ("对局已结束" if (g.is_over() or self.over)
                                          else "当前阶段不能结束回合")},
            {"key": "refresh", "label": "刷新酒馆", "action": A_REFRESH, "enabled": refresh_ok,
             "price": refresh_price,
             "hint": (f"{refresh_price} 金" if refresh_price is not None else "价格未知")
                     + (f" · 剩 {free_refreshes} 次免费" if free_refreshes else ""),
             "reason": "" if refresh_ok else (gold_reason(refresh_price, "刷新")
                                              or "当前不能刷新")},
            {"key": "freeze",
             "label": "解除冻结" if me.get("frozen") else "冻结酒馆",
             "action": A_FREEZE, "enabled": freeze_ok, "price": 0, "hint": "免费",
             "reason": "" if freeze_ok else "当前不能改变冻结状态"},
            {"key": "upgrade",
             "label": (f"升级到 T{tier_now + 1}" if tier_now else "升级酒馆"),
             "action": A_UPGRADE, "enabled": upgrade_ok, "price": upgrade_price,
             "hint": (f"{upgrade_price} 金" if upgrade_price is not None else "价格未知")
                     + (f" · 当前 T{tier_now}" if tier_now else ""),
             "reason": "" if upgrade_ok else
                       ("已到最高酒馆等级" if not me.get("can_upgrade_tier", True)
                        else (gold_reason(upgrade_price, "升级") or "当前不能升级"))},
        ]
        if dark_raw:
            buttons.append({
                "key": "dark_gift", "label": "黑暗之赐", "action": A_DARK_GIFT,
                "enabled": dark_enabled, "price": dg_cost,
                "hint": " · ".join(x for x in (
                    dark_gift["cost_label"],
                    f"已用 {dark_gift['uses_label']}",
                    f"可选星级 {dark_gift['tiers_label']}") if x),
                "reason": dg_reason,
            })
        for p in powers:
            a = p.get("action")
            hint = []
            if p.get("price"):
                hint.append(f"{p['price']} 金")
            hint.append("被动" if p.get("passive") else "主动")
            if p.get("uses_turn"):
                hint.append(f"本回合已用 {p['uses_turn']}")
            a_int = int(a) if a is not None else None
            power_ok = bool(a_int is not None and legal_a(a_int) and p.get("usable", True))
            if power_ok:
                power_reason = ""
            elif p.get("passive"):
                power_reason = "被动技能无需发动"
            elif a_int is not None and not legal_a(a_int):
                power_reason = gold_reason(p.get("price"), "技能") or "当前不能发动（本回合已用/阶段不符）"
            else:
                power_reason = "当前不能发动"
            buttons.append({
                "key": f"power{p.get('slot')}",
                "label": f"技能：{p.get('name_zh') or ''}",
                "action": a_int, "enabled": power_ok,
                "price": p.get("price"), "hint": " ".join(hint),
                "reason": power_reason,
            })

        # 对手：只给公开信息（英雄/血甲/等级/上次交战时所见战团/公开饰品/任务）
        opponents = []
        for o in v.get("opponents") or []:
            seen = [_card_brief(x) for x in (o.get("seen_board") or [])]
            seen_turn = o.get("seen_turn")
            opponents.append({
                "id": o.get("id"),
                "hero": _hero_brief(o.get("hero")) if o.get("hero") else None,
                "health": o.get("health"),
                "armor": o.get("armor"),
                "tier": o.get("tier"),
                "alive": bool(o.get("alive")),
                "placement": o.get("placement"),
                "win_streak": o.get("win_streak"),
                "last_damage": o.get("last_damage"),
                "hand_size": o.get("hand_size"),
                "is_next": bool(o.get("is_next_opponent")),
                "was_last_opponent": bool(o.get("was_last_opponent")),
                "last_warband": o.get("last_warband"),
                "seen_turn": seen_turn,
                "seen_label": (f"第 {seen_turn} 回合交战时所见" if seen_turn
                               else "从未交战（未知阵容）"),
                "seen_board": seen,
                "seen_board_size": len(seen),
                "trinkets": [_card_brief(x) for x in (o.get("trinkets") or [])],
                "trinket_names": [x.get("name_zh") or x.get("name") or ""
                                  for x in (o.get("trinkets") or [])],
                "quests": [
                    {"quest": _card_brief(q.get("quest")),
                     "reward": _card_brief(q.get("reward")),
                     "progress": q.get("progress"), "goal": q.get("goal")}
                    for q in (o.get("quests") or []) if isinstance(q, dict)
                ],
                "rewards": [_card_brief(x) for x in (o.get("rewards") or [])],
            })
        opponent_by_id = {o["id"]: o for o in opponents}

        # 战斗：先从完整 combats 过滤出自己参与的战斗，再取最近一场（不是全局末三条）
        raw_combats = v.get("combats") or []
        combats = [_combat_brief(c, self.seat) for c in raw_combats[-6:]]
        my_combat = None
        for c in reversed(raw_combats):
            cb = _combat_brief(c, self.seat, frames=True)
            if not cb["mine"]:
                continue
            opp = cb.get("opponent")
            if opp is None:
                cb["opponent_label"] = "幽灵（空场）"
                cb["opponent_hero_name"] = "幽灵"
            else:
                oh = opponent_by_id.get(opp) or {}
                hero = oh.get("hero") or {}
                cb["opponent_hero"] = hero
                cb["opponent_hero_name"] = hero.get("name_zh") or hero.get("name") or f"座位 {opp}"
                cb["opponent_label"] = f"座位 {opp} · {cb['opponent_hero_name']}"
            cb["summary"] = ("第 %s 回合 vs %s：%s，伤害 %s%s" % (
                cb.get("turn"), cb["opponent_label"], cb.get("result_label") or "?",
                cb.get("damage"), "（截断）" if cb.get("truncated") else ""))
            my_combat = cb
            break
        if my_combat is None:
            my_combat = {"mine": False, "result": "", "result_label": "尚未交战",
                         "summary": "本局还没有自己的战斗记录", "damage": None,
                         "turn": None, "opponent": None, "opponent_label": "—",
                         "frames": [], "frame_count": 0, "truncated": False}
        elif my_combat.get("mine"):
            self.last_my_combat = my_combat
        if not my_combat.get("mine") and self.last_my_combat:
            # 对局后期引擎的 combats 可能已滚掉自己的战斗：回退到本局最后一次见到的那场
            my_combat = dict(self.last_my_combat)
            my_combat["cached"] = True

        events = me.get("turn_events") or []
        if not isinstance(events, list):
            events = [events]
        stats_src = me.get("stats") or {}
        stats = {k: stats_src.get(k) for k in (
            "combats_won", "combats_lost", "cards_bought", "minions_sold",
            "refreshes", "gold_spent_total", "triples_held",
            "won_last", "lost_last", "tied_last", "last_damage") if k in stats_src}

        return {
            "ok": True,
            "seat": self.seat,
            "seed": self.seed,
            "turn": v.get("turn"),
            "phase": phase,
            "phase_label": {"hero_select": "选择英雄", "recruit": "招募",
                            "game_over": "对局结束"}.get(phase, phase),
            "over": bool(g.is_over()),
            "alive": v.get("alive"),
            "hero_select": phase == "hero_select",
            "hud": hud,
            "shop": shop,
            "hand": hand,
            "board": board,
            "hero_powers": powers,
            "buttons": buttons,
            "pending": pending,
            "opponents": opponents,
            "my_combat": my_combat,
            "combats": combats,
            "events": events[-8:],
            "stats": stats,
            "mask": mask,
            "legal": legal,
            "legal_names": [action_name(i) for i in legal],
            "action_space": {
                "N_ACTIONS": N_ACTIONS,
                "END": A_END, "REFRESH": A_REFRESH, "FREEZE": A_FREEZE,
                "UPGRADE": A_UPGRADE, "HERO_POWER": A_HERO_POWER,
                "DARK_GIFT": A_DARK_GIFT, "CANCEL": A_CANCEL,
                "BUY": A_BUY, "SELL": A_SELL, "ACTIVATE": A_ACTIVATE,
                "CHOOSE": A_CHOOSE, "PLAY": A_PLAY, "MAGNETIZE": A_MAGNETIZE,
                "MOVE": A_MOVE, "N_SHOP": N_SHOP, "N_POS": N_POS,
                "N_BOARD": N_BOARD, "N_HAND": N_HAND,
            },
            "decisions": self.decisions,
            "steps": self.steps,
            "placement": self.placement,
            "placements": self.placements,
            "replay": {
                "path": self.replay_path,
                "url": "/replay",
                "bytes": os.path.getsize(self.replay_path) if os.path.exists(self.replay_path) else 0,
            },
            "version": str(self.E.game_version()),
        }

    def _block_reason(self, a: int, snap: Dict[str, Any]) -> str:
        """给出掩码外动作的可读原因（只依据 view 里已有的价格/状态，不猜规则）。"""
        me = snap.get("me") or {}
        gold = int(me.get("gold") or 0)
        phase = str(snap.get("phase") or "")
        if a == A_UPGRADE:
            price = me.get("upgrade_price")
            if not me.get("can_upgrade_tier", True):
                return "已到最高酒馆等级"
            if price is not None and gold < int(price):
                return f"金币不足：升级需要 {price} 金，现有 {gold}"
            return "当前阶段不能升级酒馆"
        if a == A_REFRESH:
            price = me.get("refresh_price")
            if (price is not None and gold < int(price)
                    and not int(me.get("free_refreshes") or 0)):
                return f"金币不足：刷新需要 {price} 金，现有 {gold}"
            return "当前阶段不能刷新酒馆"
        if A_BUY <= a < A_BUY + N_SHOP:
            slot = a - A_BUY
            shop = me.get("shop") or []
            if slot < len(shop):
                price = shop[slot].get("price")
                if price is not None and gold < int(price):
                    return f"金币不足：买这张牌需要 {price} 金，现有 {gold}"
            if len(me.get("hand") or []) >= int(me.get("hand_limit") or 10):
                return "手牌已满"
            return "该酒馆槽位当前不能购买"
        if a == A_DARK_GIFT:
            dg = me.get("dark_gift") or {}
            if dg.get("unlock_turn") and int(snap.get("turn") or 0) < int(dg["unlock_turn"]):
                return f"第 {dg['unlock_turn']} 回合才解锁黑暗之赐"
            if dg.get("used_this_turn"):
                return "本回合已经用过黑暗之赐"
            if dg.get("max_uses") and int(dg.get("uses") or 0) >= int(dg["max_uses"]):
                return "黑暗之赐已用尽"
            if dg.get("cost") is not None and gold < int(dg["cost"]):
                return f"金币不足：黑暗之赐需要 {dg['cost']} 金，现有 {gold}"
            return "当前阶段不能使用黑暗之赐"
        if A_HERO_POWER <= a < A_HERO_POWER + 2:
            slot = a - A_HERO_POWER
            powers = me.get("hero_powers") or []
            if slot < len(powers):
                p = powers[slot]
                if p.get("passive"):
                    return "这是被动技能，无需发动"
                price = p.get("price")
                if price is not None and gold < int(price):
                    return f"金币不足：技能需要 {price} 金，现有 {gold}"
            return "当前阶段/次数不能发动技能"
        if phase == "hero_select":
            return "当前是选英雄阶段，只能选择英雄"
        return "该动作当前不在合法动作掩码中（金币/位置/阶段/目标不满足）"

    def act(self, action: Any) -> Dict[str, Any]:
        """执行一个人类动作（先按掩码校验），返回新状态。"""
        g = self.game
        try:
            a = int(action)
        except Exception as exc:  # noqa: BLE001
            raise IllegalAction(f"action 必须是整数，得到 {action!r}") from exc
        if not 0 <= a < N_ACTIONS:
            raise IllegalAction(f"动作 {a} 越界（允许 0..{N_ACTIONS - 1}）")
        if g.is_over() or self.over:
            raise IllegalAction("对局已结束，请新开一局")
        if not g.needs_action(self.seat):
            raise IllegalAction("当前不需要你行动")
        snap = json.loads(g.view(self.seat))
        mask = self._mask()
        if not mask[a]:
            raise IllegalAction(f"动作 {a}（{action_name(a)}）非法：{self._block_reason(a, snap)}")

        features, cards = self._obs()
        turn = int(g.turn)
        phase = str(snap.get("phase") or "")
        tier = int((snap.get("me") or {}).get("tier") or 0)
        gold = int((snap.get("me") or {}).get("gold") or 0)
        try:
            g.step(self.seat, a)
        except Exception as exc:  # noqa: BLE001 - 掩码通过但引擎仍拒绝：包装成 400
            raise IllegalAction(f"引擎拒绝动作 {a}（{action_name(a)}）：{exc}") from exc
        self.steps += 1

        self._append_line({
            "type": "decision",
            "seed": self.seed,
            "seat": self.seat,
            "decision": self.decisions,
            "turn": turn,
            "phase": phase,
            "tier": tier,
            "gold": gold,
            "action": a,
            "action_name": action_name(a),
            "legal": True,
            "features": features.tolist(),
            "cards": cards.tolist(),
            "mask": mask,
        })
        self.decisions += 1

        self.advance_bots()
        return self.state()

    def replay_bytes(self) -> bytes:
        with open(self.replay_path, "rb") as fh:
            return fh.read()


# ══════════════════════════════════════════════════════════════════════
# replay -> BC npz
# ══════════════════════════════════════════════════════════════════════


def convert_replays(src: str, out: str, skip_hero_select: bool = False) -> Dict[str, Any]:
    """``runs/human_play/*.jsonl.gz`` -> BC npz（``train_compound_bc.load_npz`` 可读）。

    - 跳过 ``meta`` / ``summary`` 行；
    - ``--skip-hero-select`` 可过滤英雄选择阶段的决策（部分训练流程不喂该阶段）；
    - 输出 ``obs``(n,3351) float32（前 3227 浮点 + 后 124 卡牌 id），并同时给
      ``features`` float16 / ``cards`` int16 / ``mask`` bool / ``action`` int64 /
      ``turn`` ``tier`` ``gold`` ``episode_id``。
    """
    import numpy as np  # noqa: PLC0415

    paths = sorted(glob.glob(os.path.join(src, "*.jsonl.gz")))
    if not paths:
        raise SystemExit(f"{src}: 没有找到 *.jsonl.gz")
    feats: List[List[float]] = []
    cards: List[List[int]] = []
    masks: List[List[int]] = []
    actions: List[int] = []
    turns: List[int] = []
    tiers: List[int] = []
    golds: List[int] = []
    eids: List[int] = []
    skipped = {"hero_select": 0, "bad": 0, "meta": 0}
    for ep, path in enumerate(paths):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("type") != "decision" or "action" not in rec:
                    skipped["meta"] += 1
                    continue
                if skip_hero_select and rec.get("phase") == "hero_select":
                    skipped["hero_select"] += 1
                    continue
                f = rec.get("features")
                c = rec.get("cards")
                m = rec.get("mask")
                a = int(rec.get("action", -1))
                if (not isinstance(f, list) or not isinstance(c, list) or not isinstance(m, list)
                        or len(f) != OBS_FLOATS or len(c) != OBS_CARDS
                        or len(m) != N_ACTIONS or not 0 <= a < N_ACTIONS or not m[a]):
                    skipped["bad"] += 1
                    continue
                feats.append(f)
                cards.append(c)
                masks.append(m)
                actions.append(a)
                turns.append(int(rec.get("turn") or 0))
                tiers.append(int(rec.get("tier") or 0))
                golds.append(int(rec.get("gold") or 0))
                eids.append(ep)
    n = len(actions)
    if n == 0:
        raise SystemExit(f"{src}: 没有可用决策行（跳过 {skipped}）")
    feat_arr = np.asarray(feats, dtype=np.float32)
    card_arr = np.asarray(cards, dtype=np.int32)
    mask_arr = np.asarray(masks, dtype=bool)
    obs = np.zeros((n, OBS_TOTAL), dtype=np.float32)
    obs[:, :OBS_FLOATS] = feat_arr
    obs[:, OBS_FLOATS:] = card_arr
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    np.savez_compressed(
        out,
        obs=obs,
        features=feat_arr.astype(np.float16),
        cards=card_arr.astype(np.int16),
        mask=mask_arr,
        action=np.asarray(actions, dtype=np.int64),
        turn=np.asarray(turns, dtype=np.uint8),
        tier=np.asarray(tiers, dtype=np.uint8),
        gold=np.asarray(golds, dtype=np.int16),
        episode_id=np.asarray(eids, dtype=np.int32),
    )
    return {
        "files": len(paths),
        "decisions": n,
        "skipped": skipped,
        "episodes": len(set(eids)) if eids else 0,
        "out": out,
        "bytes": os.path.getsize(out),
    }


# ══════════════════════════════════════════════════════════════════════
# 纯文本状态（``/snapshot`` 内嵌、``/snapshot.txt`` 直接返回、自测打印）
# ══════════════════════════════════════════════════════════════════════


def _card_text(c: Dict[str, Any]) -> str:
    bits = [c.get("name_zh") or c.get("name") or "?"]
    tier = int(c.get("tier") or 0)
    bits.append("★%d" % tier if tier else "★—")
    if c.get("golden"):
        bits.append("金色")
    if c.get("is_minion"):
        bits.append(c.get("race_text") or "无")
        bits.append("%s/%s" % (c.get("atk"), c.get("hp")))
        if c.get("max_hp") is not None and c.get("max_hp") != c.get("hp"):
            bits.append("(上限 %s)" % c.get("max_hp"))
    else:
        bits.append(c.get("kind_label") or c.get("kind") or "")
    if c.get("keyword_labels"):
        bits.append("动态关键词：" + "/".join(c["keyword_labels"]))
    if c.get("card_keyword_labels"):
        bits.append("卡面关键词：" + "/".join(c["card_keyword_labels"]))
    if c.get("price_label"):
        bits.append("价格 " + c["price_label"])
    if c.get("play_cost_label"):
        bits.append(c["play_cost_label"])
    if c.get("attached"):
        bits.append("附件：" + "、".join(
            "%s(%s)" % (a.get("name_zh"), a.get("kind_label") or "附件")
            for a in c["attached"]))
    line = "  ".join("%s" % b for b in bits)
    if c.get("text"):
        line += "\n      [卡面] " + str(c["text"]).replace("\n", " ")
    if c.get("breakdown_text"):
        line += "\n      [数值] " + c["breakdown_text"]
    return line


def state_text(st: Dict[str, Any]) -> str:
    """中局状态纯文本（含种族/关键词/饰品/赐福/对手/战果），供 /snapshot 与自测。"""
    hud = st.get("hud") or {}
    hero = hud.get("hero") or {}
    lines: List[str] = []
    lines.append("=== 第 %s 回合 · %s · 种子 %s · 座位 %s ===" % (
        st.get("turn"), st.get("phase_label") or st.get("phase"),
        st.get("seed"), st.get("seat")))
    lines.append("英雄：%s  生命 %s  护甲 %s  金币 %s/%s  等级 T%s  存活 %s/8" % (
        hero.get("name_zh") or hero.get("name") or "-", hud.get("health"),
        hud.get("armor"), hud.get("gold"), hud.get("max_gold"), hud.get("tier"),
        st.get("alive")))
    races = hud.get("lobby_races_zh") or hud.get("lobby_races") or []
    lines.append("本局种族：" + ("/".join(str(x) for x in races) if races else "无"))
    if hud.get("tier"):
        lines.append("酒馆：T%s（下一级 T%s，升级 %s 金）· 刷新 %s 金%s" % (
            hud.get("tier"), int(hud.get("tier")) + 1, hud.get("upgrade_price"),
            hud.get("refresh_price"),
            (" · 剩 %s 次免费" % hud.get("free_refreshes")) if hud.get("free_refreshes") else ""))

    pend = st.get("pending")
    if pend:
        lines.append("选择面板：%s — %s" % (pend.get("kind_label") or pend.get("kind"),
                                          pend.get("hint") or ""))
        if pend.get("source") and (pend["source"].get("name_zh") or pend["source"].get("name")):
            lines.append("  来源：" + (pend["source"].get("name_zh") or pend["source"].get("name")))
        for t in pend.get("targets") or []:
            lines.append("  [目标 %s] %s（eid %s，action %s）" % (
                t.get("index"), t.get("name"), t.get("eid"), t.get("action")))
        for o in pend.get("options") or []:
            extra = ""
            if o.get("branch_label"):
                extra += " " + o["branch_label"]
            if o.get("price_label"):
                extra += " 价格 " + o["price_label"]
            if o.get("weight") is not None:
                extra += " 权重 %s%%" % o.get("weight")
            lines.append("  [选项 %s%s] %s" % (o.get("index"), extra, _card_text(o)))

    lines.append("酒馆：")
    if st.get("shop"):
        for c in st["shop"]:
            lines.append("  %s %s" % (c.get("slot_label") or "", _card_text(c)))
    else:
        lines.append("  （空）")

    lines.append("手牌：%d/%s" % (len(st.get("hand") or []), hud.get("hand_limit")))
    for c in st.get("hand") or []:
        lines.append("  %s %s" % (c.get("hand_slot_label") or "", _card_text(c)))

    lines.append("战场：%d 只" % len(st.get("board") or []))
    for c in st.get("board") or []:
        lines.append("  %s %s" % (c.get("position_label") or "", _card_text(c)))

    trinkets = hud.get("trinkets") or []
    lines.append("饰品（已获得 %d）：" % len(trinkets))
    if trinkets:
        for t in trinkets:
            lines.append("  [%s] %s" % (t.get("slot_tag") or t.get("kind_label"),
                                        t.get("name_zh") or t.get("name")))
            if t.get("text"):
                lines.append("      [卡面] " + str(t["text"]).replace("\n", " "))
    else:
        lines.append("  （无）")

    dg = hud.get("dark_gift") or {}
    if dg:
        lines.append("黑暗之赐：%s · 已用 %s · 本回合%s · 可选星级 %s（下回合 %s）· %s" % (
            dg.get("cost_label"), dg.get("uses_label"),
            "已用" if dg.get("used_this_turn") else "未用",
            dg.get("tiers_label"), dg.get("next_tiers_label"),
            "可用 [%s]" % dg.get("action") if dg.get("enabled") else ("不可用：" + str(dg.get("reason")))))
    for eff in hud.get("effects") or []:
        card = eff.get("card") or {}
        lines.append("持续效果：%s ×%s" % (card.get("name_zh") or card.get("name"),
                                          eff.get("stacks")))
    d = hud.get("deity") or {}
    if d.get("present"):
        lines.append("神明（deity，不等于赐福）：%s %s/%s%s%s · %s · %s（%s）" % (
            d.get("name_zh") or d.get("name"), d.get("atk"), d.get("hp"),
            " · 金色" if d.get("golden") else "",
            " · 复生" if d.get("reborn") else "",
            d.get("tier_label") or "—", d.get("race_text") or "无",
            d.get("card_id") or "?"))
        if d.get("text"):
            lines.append("  [%s] %s" % (d.get("text_note") or "卡面",
                                        str(d["text"]).replace("\n", " ")))
        lines.append("  触发要求（阶段｜条件｜效果｜来源）：")
        for i, t in enumerate(d.get("triggers") or [], 1):
            lines.append("    %d) 阶段=%s｜条件=%s｜效果=%s｜来源=%s" % (
                i, t.get("phase_label") or t.get("phase"), t.get("condition"),
                t.get("effect"), t.get("source")))
        if d.get("numbers"):
            lines.append("  数值：" + " · ".join(
                "%s=%s[%s]" % (n.get("label"), n.get("value"), n.get("source"))
                for n in d["numbers"]))
        if d.get("hint"):
            lines.append("  提示：" + str(d["hint"]))
    else:
        lines.append("神明（deity，不等于赐福）：本局无神明")
        if d.get("hint"):
            lines.append("  " + str(d["hint"]))

    lines.append("对手：")
    for o in st.get("opponents") or []:
        oh = o.get("hero") or {}
        state = ("生命 %s 护甲 %s T%s" % (o.get("health"), o.get("armor"), o.get("tier"))
                 if o.get("alive") else ("已淘汰 #%s" % o.get("placement")))
        mark = "▶下位 " if o.get("is_next") else ""
        lines.append("  %s%s：%s · %s%s" % (mark, oh.get("name_zh") or oh.get("name") or "未知英雄",
                                           state, o.get("seen_label") or "",
                                           "（幽灵局）" if (o.get("is_next") and hud.get("next_is_ghost")) else ""))
        for m in o.get("seen_board") or []:
            lines.append("      " + _card_text(m))

    mc = st.get("my_combat") or {}
    lines.append("上轮战果：" + (mc.get("summary") or "无")
                 + ("（缓存：本局最后一次见到的己方战斗）" if mc.get("cached") else ""))
    if mc.get("frames"):
        lines.append("  战斗帧：%d 帧（可展开）" % len(mc["frames"]))

    lines.append("按钮：")
    for b in st.get("buttons") or []:
        lines.append("  [%s] %s%s%s%s" % (
            b.get("action"), b.get("label"), (" · " + b["hint"]) if b.get("hint") else "",
            "" if b.get("enabled") else "（不可用）",
            (" 原因：" + b["reason"]) if b.get("reason") else ""))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 内嵌界面（HTML/CSS/JS，无外部依赖）
# ══════════════════════════════════════════════════════════════════════

INDEX_HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HSBRSIM 人类对战</title>
<style>
:root{--bg:#12141c;--panel:#1b1f2c;--line:#2c3245;--fg:#e8ecf5;--dim:#93a0bd;
      --gold:#f2c14e;--hp:#e05a5a;--good:#5ad18a;--bad:#e07070;--spell:#8f7ff0;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
header{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--line);background:#171a25;position:sticky;top:0;z-index:5}
header .hero{font-size:18px;font-weight:700;color:var(--gold)}
header .pill{background:#232838;border:1px solid var(--line);border-radius:999px;padding:3px 10px}
header .hp{color:var(--hp);font-weight:700}
header .gold{color:var(--gold);font-weight:700}
header .dim{color:var(--dim)}
main{display:grid;grid-template-columns:minmax(420px,1.25fr) minmax(360px,1fr) minmax(300px,.9fr);gap:12px;padding:12px}
section{display:flex;flex-direction:column;gap:12px;min-width:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}
.ptitle{display:flex;justify-content:space-between;align-items:center;color:var(--dim);font-size:12px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:8px}
.card{position:relative;background:#202636;border:1px solid var(--line);border-radius:8px;padding:7px;min-height:110px;cursor:default;transition:border-color .1s,transform .1s}
.card.clickable{cursor:pointer}
.card.clickable:hover{border-color:var(--gold);transform:translateY(-1px)}
.card.legal{border-color:#3d5a8a}
.card.golden{border-color:#b8860b;box-shadow:0 0 0 1px #b8860b inset}
.card .cname{font-weight:700;font-size:13px;line-height:1.25;margin-bottom:4px}
.card .cmeta{display:flex;justify-content:space-between;align-items:center;color:var(--dim);font-size:11px}
.card .stats{color:var(--fg);font-weight:700}
.card .stats .a{color:#f0b95a}.card .stats .h{color:var(--hp)}
.card .ctext{color:var(--dim);font-size:11px;line-height:1.3;margin-top:5px;max-height:52px;overflow:hidden}
.card .badge{position:absolute;right:6px;bottom:5px;background:#2c3245;border-radius:6px;padding:1px 6px;font-size:11px;color:var(--gold)}
.card .spell{color:var(--spell);font-size:11px}
.card .frozen{position:absolute;left:6px;top:5px;color:#7fd1ff;font-size:11px}
.handrow{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px}
.handrow .card{min-width:128px;max-width:150px}
.board{display:flex;gap:8px;flex-wrap:wrap;min-height:132px}
.board .card{width:132px;min-height:124px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;position:relative;z-index:2}
.chip{background:#2c3245;border:1px solid #3a4258;color:var(--fg);border-radius:6px;padding:2px 7px;font-size:11px;cursor:pointer}
.chip:hover{border-color:var(--gold)}
.chip.on{background:#3b4a25;border-color:#7bb43f}
.btns{display:flex;flex-wrap:wrap;gap:8px}
button{background:#2a3146;color:var(--fg);border:1px solid #3a4258;border-radius:8px;padding:7px 12px;font-size:13px;cursor:pointer}
button:hover:not(:disabled){border-color:var(--gold)}
button:disabled{opacity:.35;cursor:not-allowed}
button.primary{background:#3b4a25;border-color:#6f9c3c}
button.end{background:#5a2b2b;border-color:#8a4242}
button.new{background:#2b3d5a;border-color:#45608a}
.opp{display:flex;flex-direction:column;gap:6px;max-height:280px;overflow:auto}
.opprow{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 8px;border-bottom:1px dashed var(--line);padding:4px 0;font-size:12px}
.opprow>span{white-space:nowrap}
.opprow.dead{opacity:.45;text-decoration:line-through}
.mini{color:var(--dim);font-size:11px;margin-top:2px}
#overlay{position:fixed;inset:0;background:rgba(8,10,16,.78);display:flex;align-items:center;justify-content:center;z-index:50}
#overlay.hidden{display:none}
.pbox{background:var(--panel);border:1px solid #4a5470;border-radius:14px;padding:18px;max-width:min(860px,92vw);max-height:86vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.pbox h2{margin:0 0 4px;font-size:20px}
.pbox .sub{color:var(--dim);margin-bottom:12px}
.popts{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin:10px 0}
.popts .card{min-height:120px}
#toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:#5a2b2b;border:1px solid #8a4242;color:#fff;padding:8px 16px;border-radius:8px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:60}
#toast.show{opacity:1}
#newgame{display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap}
#newgame input{width:110px;background:#202636;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:6px}
#newgame a{color:#8fc1ff;font-size:12px}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 10px}
summary{color:var(--dim);cursor:pointer;font-size:12px}
#legal{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px;max-height:180px;overflow:auto}
#legal span{background:#202636;border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:11px;color:var(--dim)}
.good{color:var(--good)}.bad{color:var(--bad)}
/* ── 卡图与卡面信息 ── */
.art{position:relative;height:56px;background:#171b26;border:1px solid var(--line);border-radius:6px;
     margin:0 0 5px;overflow:hidden;display:flex;align-items:center;justify-content:center}
.art img{position:absolute;inset:0;margin:auto;max-height:100%;max-width:100%;object-fit:contain}
.artph{color:#46506b;font-size:15px;font-weight:700;letter-spacing:.06em;user-select:none}
.card .tier-badge{position:absolute;left:7px;top:7px;background:#1a1e2b;border:1px solid #4a5470;
     border-radius:6px;padding:0 5px;font-size:11px;color:var(--gold);z-index:3}
.card .raceline{color:#9fb0d6;font-size:11px;margin:1px 0}
.card .kwchips{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.kw{background:#2a3550;border:1px solid #3d4c6e;border-radius:5px;padding:0 5px;font-size:10px;color:#bcd0ff}
.kw.card-kw{background:#3a2f4e;border-color:#5a4478;color:#d8c4ff}
.kw.golden-kw{background:#4a3a12;border-color:#8a6d20;color:var(--gold)}
.card .atk-hp{font-weight:700;font-size:13px}
.card .atk-hp .a{color:#f0b95a}.card .atk-hp .h{color:var(--hp)}
.card .quote{color:#8d99b5;font-size:11px;line-height:1.3;margin-top:4px;max-height:44px;overflow:hidden}
.card details,.card .attach{margin-top:4px;font-size:10px;color:#93a0bd}
.card details summary{font-size:10px;color:#8fc1ff}
.card .reason{color:#e0a06a;font-size:10px;margin-top:3px}
.btns .bwrap{display:flex;flex-direction:column;gap:2px}
.btns .bwrap .reason{color:#e0a06a;font-size:10px;max-width:220px}
.trinket{display:flex;flex-direction:column;gap:2px;border-bottom:1px dashed var(--line);padding:4px 0}
.trinket .tname{font-weight:700;font-size:12px}
.dg{display:flex;flex-direction:column;gap:4px;border:1px solid #4a3d6b;border-radius:8px;padding:8px;background:#241f33}
.dg .dgline{font-size:12px}
.dg .reason{color:#e0a06a;font-size:11px}
.deity{border:1px solid #5a4478;border-radius:8px;padding:8px;background:#241f33;display:flex;flex-direction:column;gap:5px}
.deity .dname{font-size:15px}
.deity .dmeta{color:#93a0bd;font-size:11px}
.deity .dtext{color:#c8d2e8;font-size:12px;line-height:1.4}
.deity .dtrig{font-size:12px;line-height:1.4}
.deity .dtrig b{color:var(--gold)}
.deity .src{color:#8d99b5;font-size:10px}
.deity .dnumline{display:flex;flex-wrap:wrap;gap:6px;font-size:11px;color:#c8d2e8}
.deity .dnum{background:#2c3245;border:1px solid #3a4258;border-radius:6px;padding:1px 6px}
.deity .dempty{color:#93a0bd;font-size:12px}
.mycombat{border-left:3px solid var(--line);padding-left:8px;margin-bottom:4px}
.mycombat.win{border-color:var(--good)}.mycombat.loss{border-color:var(--bad)}
.mycombat.tie{border-color:var(--gold)}
.frames{max-height:200px;overflow:auto;font-size:11px}
.frames .fr{border-bottom:1px dashed var(--line);padding:3px 0}
#statetext{white-space:pre-wrap;font-size:11px;line-height:1.35;color:#c8d2e8;max-height:340px;overflow:auto;margin:0}
</style>
</head>
<body>
<header id="hud"><span class="dim">加载中…</span></header>
<main>
  <section>
    <div class="panel">
      <div class="ptitle"><span>酒馆</span><span id="tavernhint" class="mini"></span></div>
      <div id="shop" class="grid"></div>
    </div>
    <div class="panel">
      <div class="ptitle"><span>手牌</span><span id="handhint" class="mini"></span></div>
      <div id="hand" class="handrow"></div>
    </div>
  </section>
  <section>
    <div class="panel">
      <div class="ptitle"><span>我的战场</span><span id="boardhint" class="mini"></span></div>
      <div id="board" class="board"></div>
    </div>
    <div class="panel">
      <div class="ptitle"><span>神明（Deity，独立于赐福）</span><span id="deityhint" class="mini"></span></div>
      <div id="deity"></div>
    </div>
    <div class="panel">
      <div class="ptitle"><span>饰品 / 黑暗之赐</span><span id="trinkethint" class="mini"></span></div>
      <div id="trinkets" class="mini"></div>
      <div id="darkgift" style="margin-top:8px"></div>
      <div id="effects" class="mini" style="margin-top:6px"></div>
    </div>
    <div class="panel">
      <div class="ptitle"><span>操作</span><span class="mini">按钮 = 动作名 + 价格 + [引擎动作下标]</span></div>
      <div id="buttons" class="btns"></div>
      <div id="newgame">
        <input id="seed" type="number" placeholder="seed" title="留空 = 当前 seed">
        <button id="newbtn" class="new">新开一局</button>
        <a id="replaylink" href="/replay">下载 replay</a>
        <span id="replaymeta" class="mini"></span>
      </div>
    </div>
  </section>
  <section>
    <div class="panel">
      <div class="ptitle"><span>对手（公开信息）</span><span id="opphint" class="mini"></span></div>
      <div id="opp" class="opp"></div>
    </div>
    <div class="panel">
      <div class="ptitle"><span>我的上轮战果</span><span id="combathint" class="mini"></span></div>
      <div id="mycombat"></div>
      <details style="margin-top:6px"><summary>最近战斗（全部座位）</summary><div id="combats" class="mini"></div></details>
    </div>
    <div class="panel">
      <div class="ptitle"><span>本回合事件</span></div>
      <div id="events" class="mini"></div>
    </div>
    <details>
      <summary>合法动作掩码（点击展开）</summary>
      <div id="legal"></div>
    </details>
    <details>
      <summary>中局状态文本（/snapshot.txt）</summary>
      <!--SNAPSHOT_TEXT-->
    </details>
  </section>
</main>
<div id="overlay" class="hidden"></div>
<div id="toast"></div>
<script>
"use strict";
let S = /*STATE_JSON*/null;
let toastTimer = 0;
let BUSY = false;   /* 请求中锁定提交，避免双击产生第二次（非法）动作 */

const $ = (id) => document.getElementById(id);
function esc(s) {
  return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}
async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  };
  let res, data;
  try {
    res = await fetch(path, opt);
  } catch (e) {
    toast("网络错误：" + e);
    return null;
  }
  try { data = await res.json(); } catch (e) { data = {error: "响应不是 JSON"}; }
  if (!res.ok) { toast(data.error || ("HTTP " + res.status)); return null; }
  return data;
}
async function refresh() {
  const data = await api("/state");
  if (data) { S = data; render(); }
}
async function act(action) {
  if (action === null || action === undefined) { toast("该操作当前不可用"); return; }
  if (!S || BUSY) { if (BUSY) toast("请求处理中，请稍候"); return; }
  BUSY = true;
  try {
    const data = await api("/act", {action: action});
    if (data) { S = data; render(); } else { await refresh(); }
  } finally {
    BUSY = false;
  }
}
async function newGame() {
  if (BUSY) { toast("请求处理中，请稍候"); return; }
  BUSY = true;
  try {
    const raw = $("seed").value.trim();
    const body = raw === "" ? {} : {seed: Number(raw)};
    const data = await api("/new", body);
    if (data) { S = data; render(); toast("新开一局：seed " + data.seed); }
  } finally {
    BUSY = false;
  }
}

/* ── 渲染 ─────────────────────────────────────────────────────── */
function heroName(h) { return h ? (h.name_zh || h.name) : "选择英雄"; }
function artHTML(c) {
  const name = c.name_zh || c.name || "?";
  const ph = '<span class="artph">' + esc(String(name).slice(0, 2)) + '</span>';
  if (!c.art) return '<div class="art">' + ph + '</div>';
  /* 在线卡图失败时移除 img，露出底层文字占位；不阻塞任何操作 */
  return '<div class="art">' + ph +
    '<img loading="lazy" alt="" src="' + esc(c.art) +
    '" onload="this.previousElementSibling.style.display=\'none\'" onerror="this.remove()"></div>';
}
function kwHTML(c) {
  const out = [];
  for (const k of c.keyword_labels || []) out.push('<span class="kw">' + esc(k) + '</span>');
  for (const k of c.card_keyword_labels || []) out.push('<span class="kw card-kw">卡面·' + esc(k) + '</span>');
  return out.length ? '<div class="kwchips">' + out.join("") + '</div>' : "";
}
function statsHTML(c) {
  if (!c.is_minion) return "";
  let s = '<span class="atk-hp"><span class="a">' + (c.atk ?? "") + '</span>/' +
          '<span class="h">' + (c.hp ?? "") + '</span></span>';
  if (c.max_hp !== null && c.max_hp !== undefined && c.max_hp !== c.hp) {
    s += ' <span class="dim">(上限 ' + c.max_hp + ')</span>';
  }
  return s;
}
function cardHTML(c, extra) {
  const name = c.name_zh || c.name || "?";
  const parts = [];
  parts.push(artHTML(c));
  parts.push('<div class="tier-badge">' + esc(c.tier_label || ("★" + (c.tier || 0))) + '</div>');
  parts.push('<div class="cname">' + esc(name) +
    (c.golden ? ' <span class="kw golden-kw">金色</span>' : '') + '</div>');
  parts.push('<div class="raceline">' + esc(c.race_text || "无") +
    (c.kind_label && !c.is_minion ? ' · ' + esc(c.kind_label) : '') + '</div>');
  parts.push('<div class="cmeta"><span>' + statsHTML(c) + '</span><span class="spell">' +
    (c.activate_cost !== null && c.activate_cost !== undefined ? '发动 ' + c.activate_cost + ' 金' : '') +
    '</span></div>');
  parts.push(kwHTML(c));
  if (c.text) parts.push('<div class="quote">[卡面] ' + esc(c.text) + '</div>');
  if (c.attached && c.attached.length) {
    parts.push('<div class="attach">附件：' + c.attached.map((a) =>
      esc(a.name_zh || a.name || "?") + '（' + esc(a.kind_label || "附件") +
      (a.text ? '：' + esc(a.text) : '') + '）').join('；') + '</div>');
  }
  if (c.breakdown_text) {
    parts.push('<details><summary>数值拆解</summary><div>' + esc(c.breakdown_text) + '</div></details>');
  }
  return parts.join("") + (extra || "");
}
function shopCard(c) {
  const el = document.createElement("div");
  const buyable = c.buy !== null && c.buy !== undefined;
  el.className = "card" + (buyable ? " clickable legal" : "") + (c.golden ? " golden" : "");
  el.innerHTML = cardHTML(c,
    '<div class="badge">' + esc(c.price_label || "价格未知") + '</div>' +
    (c.frozen ? '<div class="frozen">❄</div>' : '') +
    (c.owned ? '<div class="mini">已持有 ' + c.owned + (c.triple_need ? '/' + c.triple_need : '') + '</div>' : '') +
    (buyable ? '' : '<div class="reason">不可购买：' + esc(c.buy_reason || "") + '</div>'));
  if (buyable) el.onclick = () => act(c.buy);
  el.title = (c.card_id || "") + (buyable
    ? ("  购买 = Buy(" + c.slot + ") = action " + c.buy + "，价格 " + (c.price_label || ""))
    : ("  不可购买：" + (c.buy_reason || "")));
  return el;
}
function handCard(c) {
  const el = document.createElement("div");
  const ok = (c.play && c.play.length) || (c.magnetize && c.magnetize.length);
  el.className = "card" + (ok ? " legal" : "");
  const chips = [];
  if (c.play && c.play.length === 1) {
    chips.push('<span class="chip" data-a="' + c.play[0].action + '">打出（' + (c.play_cost ?? 0) + '金）· [' + c.play[0].action + ']</span>');
  } else {
    for (const p of (c.play || [])) {
      chips.push('<span class="chip" data-a="' + p.action + '">打出到 ' + p.pos + ' 号位（' + (c.play_cost ?? 0) + '金）· [' + p.action + ']</span>');
    }
  }
  for (const m of (c.magnetize || [])) {
    chips.push('<span class="chip" data-a="' + m.action + '">磁力→随从' + m.board + ' · [' + m.action + ']</span>');
  }
  el.innerHTML = cardHTML(c,
    '<div class="mini">' + esc(c.play_cost_label || "") + (c.locked_label ? ' · ' + esc(c.locked_label) : '') +
    (c.temporary ? ' · 临时牌' : '') + '</div>' +
    '<div class="chips">' + chips.join("") + '</div>' +
    (!ok ? '<div class="reason">' + esc(c.play_reason || "当前不能打出") + '</div>' : ''));
  el.querySelectorAll(".chip").forEach((ch) => { ch.onclick = (e) => { e.stopPropagation(); act(Number(ch.dataset.a)); }; });
  el.title = (c.card_id || "") + "  手牌 #" + c.index + "（点击按钮打出，不是整卡点击）";
  return el;
}
function boardCard(c) {
  const el = document.createElement("div");
  el.className = "card" + (c.golden ? " golden" : "");
  const chips = [];
  if (c.sell !== null && c.sell !== undefined) chips.push('<span class="chip" data-a="' + c.sell + '">出售 · [' + c.sell + ']</span>');
  if (c.activate !== null && c.activate !== undefined) {
    chips.push('<span class="chip" data-a="' + c.activate + '">发动' +
      (c.activate_cost !== null && c.activate_cost !== undefined ? '（' + c.activate_cost + '金）' : '') +
      ' · [' + c.activate + ']</span>');
  }
  for (const m of (c.move || [])) chips.push('<span class="chip" data-a="' + m.action + '">移到 ' + m.to + ' · [' + m.action + ']</span>');
  let reason = "";
  if (c.sell === null || c.sell === undefined) reason = c.sell_reason || "当前不能出售";
  else if ((c.activate === null || c.activate === undefined) && c.activate_reason) reason = c.activate_reason;
  el.innerHTML = cardHTML(c, '<div class="chips">' + chips.join("") + '</div>' +
    (reason ? '<div class="reason">' + esc(reason) + '</div>' : ''));
  el.querySelectorAll(".chip").forEach((ch) => { ch.onclick = (e) => { e.stopPropagation(); act(Number(ch.dataset.a)); }; });
  el.title = (c.card_id || "") + "  " + (c.position_label || "") + "（顺序即左右位置）";
  return el;
}
function trinketHTML(t) {
  return '<div class="trinket"><span class="tname">[' + esc(t.slot_tag || t.kind_label || "饰品") + '] ' +
    esc(t.name_zh || t.name) + '</span>' +
    (t.text ? '<span>' + esc(t.text) + '</span>' : '') +
    (t.tier ? '<span class="mini">T' + t.tier + '</span>' : '') + '</div>';
}
function renderTrinkets() {
  const h = S.hud || {};
  const ts = h.trinkets || [];
  $("trinkethint").textContent = "已获得 " + ts.length + " 个";
  $("trinkets").innerHTML = ts.length ? ts.map(trinketHTML).join("")
    : '<div class="dim">尚未获得饰品（第 6 回合小饰品 / 第 9 回合大饰品的四选一会走 pending 弹窗）</div>';
  const dg = h.dark_gift;
  if (!dg) {
    $("darkgift").innerHTML = '<div class="dim">无黑暗之赐数据</div>';
  } else {
    $("darkgift").innerHTML = '<div class="dg">' +
      '<div class="dgline"><b>黑暗之赐</b> · 费用 ' + esc(dg.cost_label || "?") +
      ' · 已用 ' + esc(dg.uses_label || "0") +
      ' · 本回合' + (dg.used_this_turn ? "已用" : "未用") +
      ' · 可选星级 ' + esc(dg.tiers_label || "—") +
      '（下回合 ' + esc(dg.next_tiers_label || "—") + '，第 ' + esc(dg.unlock_turn) + ' 回合解锁）</div>' +
      '<div><button data-a-dark="' + dg.action + '" class="primary"' +
      ((!dg.enabled || S.over) ? ' disabled' : '') + '>使用黑暗之赐 [' + dg.action + ']</button></div>' +
      (dg.reason ? '<div class="reason">不可用：' + esc(dg.reason) + '</div>' : '') +
      '</div>';
    const btn = $("darkgift").querySelector("[data-a-dark]");
    if (btn) btn.onclick = () => act(Number(btn.dataset.aDark));
  }
  const effects = h.effects || [];
  $("effects").innerHTML = effects.map((e) => {
    const card = e.card || {};
    return '<div>持续效果：' + esc(card.name_zh || card.name) + ' ×' + esc(e.stacks) + '</div>';
  }).join("");
}
function deityHTML(d) {
  if (!d || !d.present) {
    return '<div class="dempty">本局无神明</div>' +
      '<div class="dmeta">' + esc((d && d.hint) || "大厅没有畸变怪时不会出现神明") + '</div>';
  }
  const badges = [];
  if (d.golden) badges.push('<span class="kw golden-kw">金色</span>');
  if (d.reborn) badges.push('<span class="kw">复生</span>');
  const trigs = (d.triggers || []).map((t, i) =>
    '<div class="dtrig">' + (i + 1) + ') <b>阶段：' + esc(t.phase_label || t.phase) + '</b>' +
    ' · 条件：' + esc(t.condition) + ' · 效果：' + esc(t.effect) +
    ' <span class="src">[' + esc(t.source) + ']</span></div>').join("");
  const nums = (d.numbers || []).map((n) =>
    '<span class="dnum"><b>' + esc(n.label) + '</b> ' + esc(n.value) +
    ' <span class="src">[' + esc(n.source) + ']</span></span>').join("");
  return '<div class="dname"><b>' + esc(d.name_zh || d.name) + '</b> ' +
    '<span class="atk-hp"><span class="a">' + (d.atk ?? "") + '</span>/' +
    '<span class="h">' + (d.hp ?? "") + '</span></span> ' + badges.join(" ") + '</div>' +
    '<div class="dmeta">' + esc(d.tier_label || "") + ' · ' + esc(d.race_text || "") +
    ' · ' + esc(d.card_id || "") + '</div>' +
    (d.text ? '<div class="dtext">[' + esc(d.text_note || "卡面") + '] ' + esc(d.text) + '</div>' : '') +
    '<div class="dtrig"><span class="src">触发要求（结构化）</span>' + trigs + '</div>' +
    (nums ? '<div class="dnumline">' + nums + '</div>' : '');
}
function renderDeity() {
  const d = (S.hud || {}).deity || {};
  $("deityhint").textContent = d.present ? ("唤醒门槛 ≥ " + d.threshold + " 只畸变怪死亡")
    : "本局大厅无畸变怪";
  $("deity").innerHTML = deityHTML(d);
}
function render() {
  if (!S) return;
  const h = S.hud;
  const races = (h.lobby_races_zh && h.lobby_races_zh.length ? h.lobby_races_zh : h.lobby_races) || [];
  $("hud").innerHTML =
    '<span class="hero">' + esc(heroName(h.hero)) + '</span>' +
    '<span class="pill">生命 <span class="hp">' + (h.health ?? "?") + '</span></span>' +
    '<span class="pill">护甲 ' + (h.armor ?? 0) + '</span>' +
    '<span class="pill">金币 <span class="gold">' + (h.gold ?? "?") + '</span>/' + (h.max_gold ?? "?") + '</span>' +
    '<span class="pill">等级 T' + (h.tier ?? "?") + '</span>' +
    '<span class="pill">回合 ' + (S.turn ?? "?") + ' · ' + esc(S.phase_label || S.phase) + '</span>' +
    '<span class="pill">存活 ' + (S.alive ?? "?") + '/8</span>' +
    '<span class="pill">名次 ' + (S.over ? ('<b class="good">' + S.placement + '</b>') : (h.placement || "-")) + '</span>' +
    '<span class="pill">本局种族 ' + esc(races.join("/") || "无") + '</span>' +
    (h.next_is_ghost ? '<span class="pill bad">下位对手：幽灵局</span>' : '') +
    (h.hero_power ? '<span class="pill">技能：' + esc(h.hero_power.name_zh || h.hero_power.name) + '</span>' : '') +
    '<span class="pill dim">seed ' + S.seed + ' · 决策 ' + S.decisions + '</span>' +
    (S.over ? '<span class="pill bad">对局结束</span>' : '');

  $("tavernhint").textContent = "刷新 " + h.refresh_price + " 金" +
    (h.free_refreshes ? "（免费 " + h.free_refreshes + "）" : "") +
    " · 升级 " + h.upgrade_price + " 金 → T" + ((h.tier || 0) + 1) +
    " · 冻结 " + (h.frozen ? "开" : "关");
  $("shop").innerHTML = "";
  for (const c of S.shop) $("shop").appendChild(shopCard(c));
  if (!S.shop.length) $("shop").innerHTML = '<span class="dim">酒馆为空（先选英雄 / 点刷新）</span>';

  $("handhint").textContent = S.hand.length + " / " + (h.hand_limit ?? 10) +
    (h.hand_queue_len ? " · 队列 " + h.hand_queue_len : "");
  $("hand").innerHTML = "";
  for (const c of S.hand) $("hand").appendChild(handCard(c));
  if (!S.hand.length) $("hand").innerHTML = '<span class="dim">手牌为空</span>';

  $("boardhint").textContent = S.board.length + " 个随从";
  $("board").innerHTML = "";
  for (const c of S.board) $("board").appendChild(boardCard(c));
  if (!S.board.length) $("board").innerHTML = '<span class="dim">场上没有随从</span>';

  renderTrinkets();
  renderDeity();

  $("buttons").innerHTML = "";
  for (const b of S.buttons) {
    const wrap = document.createElement("div");
    wrap.className = "bwrap";
    const el = document.createElement("button");
    el.innerHTML = '<b>' + esc(b.label) + '</b>' +
      (b.price ? ' <span class="gold">' + b.price + ' 金</span>' : '') +
      (b.action !== null ? ' <span class="dim">[' + b.action + ']</span>' : '');
    el.disabled = !b.enabled || S.over;
    el.onclick = () => act(b.action);
    el.title = (b.key || "") + " = action " + b.action +
      (b.hint ? " · " + b.hint : "") + (b.reason ? " · 不可用：" + b.reason : "");
    if (b.key === "end") el.classList.add("end");
    wrap.appendChild(el);
    if (!b.enabled && b.reason) {
      const r = document.createElement("span");
      r.className = "reason";
      r.textContent = b.reason;
      wrap.appendChild(r);
    }
    $("buttons").appendChild(wrap);
  }

  $("opphint").textContent = "存活 " + (S.alive ?? "?") + "/8";
  $("opp").innerHTML = S.opponents.map((o) => {
    const oh = o.hero || {};
    const head = '<div class="opprow' + (o.alive ? '' : ' dead') + '">' +
      '<span>' + (o.is_next ? '▶ ' : '') + esc(oh.name_zh || oh.name || "未知英雄") + '</span>' +
      '<span>' + (o.alive
        ? ('生命 <b class="hp">' + o.health + '</b> · 护甲 ' + (o.armor ?? 0) + ' · T' + o.tier +
           (o.win_streak ? ' · 连胜 ' + o.win_streak : ''))
        : ('淘汰 #' + (o.placement || "?"))) + '</span></div>';
    const seen = (o.seen_board && o.seen_board.length)
      ? '<div class="mini">' + esc(o.seen_label || "上次所见") + '：' +
        o.seen_board.map((m) => esc(m.name_zh || m.name) + ' ' + (m.atk ?? '') + '/' + (m.hp ?? '') +
          (m.golden ? '★' : '') + (m.race_text ? '[' + esc(m.race_text) + ']' : '')).join('、') + '</div>'
      : '<div class="mini dim">' + esc(o.seen_label || "从未交战（未知阵容）") + '</div>';
    const tr = (o.trinket_names && o.trinket_names.length)
      ? '<div class="mini">饰品：' + esc(o.trinket_names.join('、')) + '</div>' : '';
    return head + seen + tr;
  }).join("");

  const mc = S.my_combat || {};
  $("combathint").textContent = mc.mine ? (mc.result_label + " · 伤害 " + mc.damage) : "尚未交战";
  let combatHTML = '<div class="mycombat ' + (mc.result || '') + '">' +
    '<div>' + esc(mc.summary || "本局还没有自己的战斗记录") + '</div>' +
    ((mc.cached) ? '<div class="mini dim">缓存：本局最后一次见到的己方战斗</div>' : '') +
    ((mc.truncated) ? '<div class="mini bad">战斗被截断</div>' : '') +
    ((mc.frames && mc.frames.length)
      ? '<details><summary>战斗帧 ' + mc.frames.length + '/' + (mc.frame_count || mc.frames.length) + '（点击展开）</summary>' +
        '<div class="frames">' + mc.frames.map((f, i) =>
          '<div class="fr"><b>帧 ' + (i + 1) + '</b> ' + esc((f.log || []).join('；')) +
          ((f.boards && f.boards.length)
            ? '<div class="mini">场面：' + f.boards.map((bd) => bd.map((m) =>
                (m.name_zh || m.name) + ' ' + (m.atk ?? '') + '/' + (m.hp ?? '')).join('、')).join('  ⚔  ') + '</div>'
            : '') + '</div>').join('') + '</div></details>'
      : '<div class="mini dim">无战斗帧（引擎未记录 frames）</div>') +
    '</div>';
  $("mycombat").innerHTML = combatHTML;

  $("combats").innerHTML = S.combats.length
    ? S.combats.map((c) => {
        const bName = c.b === null || c.b === undefined ? '幽灵' : ('座位 ' + c.b);
        const win = c.winner === 0 ? ('座位 ' + c.a + ' 胜')
          : (c.winner === 1 ? (bName + ' 胜') : '平');
        return (c.mine ? '▶ ' : '') + 'T' + c.turn + '：座位 ' + c.a + ' vs ' + bName + ' → ' + win +
          '，伤害 ' + c.damage + (c.truncated ? '（截断）' : '');
      }).join('<br>')
    : '<span class="dim">暂无</span>';
  $("events").innerHTML = S.events.length ? S.events.map((e) => '<div>' + esc(typeof e === "string" ? e : JSON.stringify(e)) + '</div>').join("") : '<span class="dim">暂无</span>';

  $("legal").innerHTML = S.legal.map((a, i) => '<span>' + a + ' ' + esc(S.legal_names[i]) + '</span>').join("");
  $("replaymeta").textContent = (S.replay.bytes / 1024).toFixed(1) + " KB · " + S.replay.path.split("/").pop();
  $("replaylink").href = "/replay?ts=" + Date.now();

  renderOverlay();
}
function pendingTitle(kind) {
  return {hero: "选择英雄", discover: "发现（Discover）", trinket: "选择饰品", choose_one: "抉择",
          target: "选择目标", hero_power: "选择英雄技能", timewarp: "时空扭曲酒馆", quest: "选择任务"}[kind] || ("选择：" + kind);
}
function renderOverlay() {
  const ov = $("overlay");
  if (S.over) {
    ov.classList.remove("hidden");
    ov.innerHTML = '<div class="pbox"><h2>对局结束</h2>' +
      '<div class="sub">seed ' + S.seed + ' · 名次 <b class="good">' + S.placement + '</b> / 8 · 共 ' + S.decisions + ' 个决策</div>' +
      '<div class="mini">placements（座位→名次）：' + esc((S.placements || []).join(", ")) + '</div>' +
      '<div class="btns" style="margin-top:14px"><button class="new" id="again">再来一局（同 seed）</button>' +
      '<button id="again2">随机新 seed</button></div></div>';
    $("again").onclick = () => api("/new", {seed: S.seed}).then((d) => { if (d) { S = d; render(); } });
    $("again2").onclick = () => api("/new", {}).then((d) => { if (d) { S = d; render(); } });
    return;
  }
  const p = S.pending;
  if (!p) { ov.classList.add("hidden"); ov.innerHTML = ""; return; }
  ov.classList.remove("hidden");
  const parts = [];
  parts.push('<div class="pbox"><h2>' + esc(p.kind_label || pendingTitle(p.kind)) + '</h2>');
  if (p.hint) parts.push('<div class="sub">' + esc(p.hint) + '</div>');
  if (p.source && (p.source.name_zh || p.source.name)) {
    parts.push('<div class="sub">来源：' + esc(p.source.name_zh || p.source.name) +
      (p.source.text ? ' — [卡面] ' + esc(p.source.text) : '') + '</div>');
  }
  if (p.kind === "target") {
    parts.push('<div class="sub">点击一个目标（action = 30 + 序号）</div><div class="popts">');
    for (const t of p.targets) {
      parts.push('<div class="card' + (t.action !== null ? ' clickable' : '') + '" data-a="' + t.action + '">' +
        '<div class="cname">' + esc(t.name) + '</div>' +
        '<div class="mini">eid ' + esc(t.eid) + ' · 目标 ' + t.index + '</div>' +
        '<div class="chips"><span class="chip">选择 · [' + t.action + ']</span></div>' +
        (t.action_reason ? '<div class="reason">' + esc(t.action_reason) + '</div>' : '') + '</div>');
    }
    parts.push('</div>');
  } else if (p.kind === "hero") {
    parts.push('<div class="sub">选择本局英雄（技能与护甲随英雄而定）</div><div class="popts">');
    for (const o of p.options) {
      const ok = o.action !== null && o.action !== undefined;
      parts.push('<div class="card' + (ok ? ' clickable' : '') + '" data-a="' + o.action + '">' +
        cardHTML(o,
          '<div class="cmeta"><span>护甲 ' + (o.armor ?? 0) + '</span><span>生命 ' + (o.hp ?? 30) + '</span></div>' +
          (o.power ? '<div class="attach">技能：' + esc(o.power.name_zh || "") +
            (o.power.text ? '<br>[卡面] ' + esc(o.power.text) : '') + '</div>' : '') +
          '<div class="chips"><span class="chip">选择 · [' + o.action + ']</span></div>' +
          (ok ? '' : '<div class="reason">' + esc(o.action_reason || "") + '</div>')) + '</div>');
    }
    parts.push('</div>');
  } else {
    if (p.kind === "trinket") {
      parts.push('<div class="sub">' + (p.free ? "免费饰品" : "购买一个饰品") +
        (p.replace ? '（替换现有饰品：' + esc(p.replace.name_zh || p.replace.name) + '）' : '') +
        ' · 四选一，回合数（第 6/9 回合）≠ 酒馆星级</div>');
    }
    parts.push('<div class="popts">');
    for (const o of p.options) {
      const ok = o.action !== null && o.action !== undefined;
      const priceBits = [];
      if (o.price_label) priceBits.push(o.price_label);
      else if (o.cost !== undefined && o.cost !== null && (p.kind === "trinket" || p.kind === "timewarp")) {
        priceBits.push(o.cost + ' 金');
      }
      if (o.chronum_cost !== undefined && o.chronum_cost !== null) priceBits.push(o.chronum_cost + ' 时空币');
      if (o.weight !== undefined && o.weight !== null) priceBits.push('出价权重 ' + o.weight + '%');
      parts.push('<div class="card' + (ok ? ' clickable' : '') + '" data-a="' + o.action + '">' +
        cardHTML(o,
          '<div class="mini">' + (o.branch_label ? esc(o.branch_label) + ' · ' : '') +
          (o.goal ? '目标：' + esc(o.goal) + ' ' : '') +
          (o.reward ? '奖励：' + esc(o.reward.name_zh || o.reward.name) : '') + '</div>' +
          (priceBits.length ? '<div class="badge">' + esc(priceBits.join(' · ')) + '</div>' : '') +
          '<div class="chips"><span class="chip">选择 · [' + o.action + ']</span></div>' +
          (ok ? '' : '<div class="reason">' + esc(o.action_reason || "当前不可选") + '</div>')) + '</div>');
    }
    parts.push('</div>');
  }
  if (p.leave_action !== null && p.leave_action !== undefined) {
    parts.push('<button data-a="' + p.leave_action + '">离开时空酒馆（' + p.leave_action + '）</button> ');
  }
  if (p.chronum !== null && p.chronum !== undefined) parts.push('<span class="mini">时空币：' + p.chronum + ' · </span>');
  if (p.cancel_action !== null && p.cancel_action !== undefined) {
    parts.push('<button data-a="' + p.cancel_action + '">取消（' + p.cancel_action + '）</button>');
  }
  parts.push('</div>');
  ov.innerHTML = parts.join("");
  ov.querySelectorAll("[data-a]").forEach((el) => {
    if (el.dataset.a === "null") { el.style.opacity = ".55"; return; }
    el.onclick = () => act(Number(el.dataset.a));
    el.style.cursor = "pointer";
  });
}
$("newbtn").onclick = newGame;
if (S) { render(); } else { refresh(); }
</script>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════
# HTTP 层
# ══════════════════════════════════════════════════════════════════════


def render_html(state: Optional[Dict[str, Any]] = None) -> str:
    """内嵌页面；给定 ``state`` 时注入状态 JSON + 纯文本快照（截图/复盘用）。"""
    if state is None:
        return INDEX_HTML
    payload = json.dumps(state, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    out = INDEX_HTML.replace("/*STATE_JSON*/null", payload)
    text = state_text(state).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return out.replace("<!--SNAPSHOT_TEXT-->", '<pre id="statetext">' + text + "</pre>")


class ArenaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: Tuple[str, int], session: GameSession) -> None:
        super().__init__(addr, ArenaHandler)
        self.session = session
        self.lock = threading.Lock()


class ArenaHandler(BaseHTTPRequestHandler):
    server_version = "HSBRArena/1.0"
    protocol_version = "HTTP/1.1"

    # ── 基础工具 ─────────────────────────────────────────────────
    def _json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"请求体不是 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def log_message(self, fmt: str, *args: Any) -> None:  # 安静日志
        if os.environ.get("HUMAN_ARENA_VERBOSE"):
            sys.stderr.write("[arena] " + (fmt % args) + "\n")

    # ── 路由 ─────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                body = INDEX_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/state":
                with self.server.lock:  # type: ignore[attr-defined]
                    self._json(200, self.server.session.state())  # type: ignore[attr-defined]
            elif path == "/health":
                self._json(200, {"ok": True, "engine": "hsbg_engine",
                                 "game_version": str(self.server.session.E.game_version())})  # type: ignore[attr-defined]
            elif path == "/snapshot":
                with self.server.lock:  # type: ignore[attr-defined]
                    html = render_html(self.server.session.state())  # type: ignore[attr-defined]
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/snapshot.txt":
                with self.server.lock:  # type: ignore[attr-defined]
                    txt = state_text(self.server.session.state())  # type: ignore[attr-defined]
                body = (txt + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/replay":
                with self.server.lock:  # type: ignore[attr-defined]
                    data = self.server.session.replay_bytes()  # type: ignore[attr-defined]
                    name = os.path.basename(self.server.session.replay_path)  # type: ignore[attr-defined]
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            else:
                self._json(404, {"ok": False, "error": f"未知路径 {path}"})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                             "trace": traceback.format_exc(limit=3)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body()
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        try:
            if path == "/act":
                if "action" not in body:
                    raise IllegalAction("缺少 action 字段")
                with self.server.lock:  # type: ignore[attr-defined]
                    self._json(200, self.server.session.act(body["action"]))  # type: ignore[attr-defined]
            elif path == "/new":
                seed = body.get("seed")
                if seed is not None:
                    try:
                        seed = int(seed)
                    except Exception as exc:  # noqa: BLE001
                        raise IllegalAction(f"seed 必须是整数，得到 {seed!r}") from exc
                with self.server.lock:  # type: ignore[attr-defined]
                    sess = self.server.session  # type: ignore[attr-defined]
                    if seed is None:
                        seed = int(time.time()) % 1_000_000
                    sess.new_game(int(seed))
                    self._json(200, sess.state())
            else:
                self._json(404, {"ok": False, "error": f"未知路径 {path}"})
        except IllegalAction as exc:
            payload: Dict[str, Any] = {"ok": False, "error": str(exc)}
            if "action" in body:
                payload["action"] = body["action"]
            self._json(400, payload)
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                             "trace": traceback.format_exc(limit=3)})


# ══════════════════════════════════════════════════════════════════════
# 自测（无浏览器跑完一整局）与 CLI
# ══════════════════════════════════════════════════════════════════════


def scripted_action(st: Dict[str, Any]) -> int:
    """确定性「人类替身」：覆盖 pending/买/卖/升级/技能/刷新/结束，用于自测。"""
    pend = st.get("pending")
    if pend:
        if pend["kind"] == "target" and pend.get("targets"):
            a = pend["targets"][0].get("action")
            return int(a if a is not None else A_CANCEL)
        for o in pend.get("options") or []:
            if o.get("action") is not None:
                return int(o["action"])
        if pend.get("leave_action") is not None:
            return int(pend["leave_action"])
        if pend.get("cancel_action") is not None:
            return int(pend["cancel_action"])
    for c in st.get("hand") or []:
        if c.get("play"):
            return int(c["play"][0]["action"])
    for c in st.get("shop") or []:
        if c.get("buy") is not None:
            return int(c["buy"])
    sold = [c for c in (st.get("board") or []) if c.get("sell") is not None]
    if len(st.get("board") or []) >= 7 and sold:
        return int(sold[-1]["sell"])
    for b in st.get("buttons") or []:
        if b.get("key") == "upgrade" and b.get("enabled"):
            return int(b["action"])
    for b in st.get("buttons") or []:
        if str(b.get("key", "")).startswith("power") and b.get("enabled"):
            return int(b["action"])
    if int(st.get("turn") or 0) % 3 == 0:
        for b in st.get("buttons") or []:
            if b.get("key") == "refresh" and b.get("enabled"):
                return int(b["action"])
    return A_END


def run_selftest(seed: int, seat: int, out_dir: str, max_decisions: int = 3000,
                 config_json: Any = None) -> Dict[str, Any]:
    """脚本化人类打完整一局，打印中局状态文本并校验 replay/npz。"""
    t0 = time.time()
    sess = GameSession(seed=seed, seat=seat, out_dir=out_dir, config_json=config_json)
    n = 0
    mid_text = ""
    while not sess.over and n < max_decisions:
        st = sess.state()
        # 中局状态文本（至少拿到 1 个饰品，保证 /snapshot 文本含饰品区）
        if not mid_text and int(st.get("turn") or 0) >= 6:
            if st["hud"].get("trinkets") or int(st.get("turn") or 0) >= 7:
                mid_text = state_text(st)
        a = scripted_action(st)
        sess.act(a)
        n += 1
    st = sess.state()
    elapsed = time.time() - t0
    print("=" * 72)
    print("自测对局：seed=%d seat=%d 结束=%s 回合=%s 决策=%d 用时=%.2fs"
          % (seed, seat, st["over"], st["turn"], st["decisions"], elapsed))
    print("名次=%s placements=%s" % (st["placement"], st["placements"]))
    print("replay=%s (%.1f KB)" % (st["replay"]["path"], st["replay"]["bytes"] / 1024))
    h = st["hud"]
    print("HUD：英雄=%s 血量=%s 护甲=%s 金币=%s/%s 等级=T%s 回合=%s"
          % (hero_name(h.get("hero")), h.get("health"), h.get("armor"), h.get("gold"),
             h.get("max_gold"), h.get("tier"), st["turn"]))
    print("本局种族：%s" % ("/".join(h.get("lobby_races_zh") or h.get("lobby_races") or []) or "无"))
    print("酒馆等级：T%s（下一级 T%s，升级 %s 金，刷新 %s 金）"
          % (h.get("tier"), int(h.get("tier") or 0) + 1, h.get("upgrade_price"),
             h.get("refresh_price")))
    print("酒馆：%s" % (" | ".join(
        "%s(%s金,T%d)" % (c["name_zh"], c["price"], c["tier"]) for c in st["shop"]) or "空"))
    print("手牌：%s" % (" | ".join(c["name_zh"] for c in st["hand"]) or "空"))
    print("战场：%s" % (" | ".join(
        "%s %s/%s%s" % (c["name_zh"], c["atk"], c["hp"], "★" if c["golden"] else "")
        for c in st["board"]) or "空"))
    trs = h.get("trinkets") or []
    print("饰品（%d）：%s" % (len(trs), " | ".join(
        "%s[%s]" % (t.get("name_zh"), t.get("slot_tag")) for t in trs) or "无"))
    dg = h.get("dark_gift") or {}
    if dg:
        print("黑暗之赐：%s · 已用 %s · 星级 %s · %s"
              % (dg.get("cost_label"), dg.get("uses_label"), dg.get("tiers_label"),
                 "可用" if dg.get("enabled") else ("不可用：" + str(dg.get("reason")))))
    print("上轮战果：%s" % (st.get("my_combat") or {}).get("summary"))
    print("合法动作数=%d（首 12：%s）" % (len(st["legal"]), st["legal"][:12]))
    print("-" * 72)
    print("中局状态文本（GET /snapshot.txt 同款；含种族/关键词/饰品）：")
    print(mid_text or state_text(st))
    print("-" * 72)
    # replay 行完整性
    with gzip.open(st["replay"]["path"], "rt", encoding="utf-8") as fh:
        lines = [json.loads(x) for x in fh if x.strip()]
    dec = [r for r in lines if r.get("type") == "decision"]
    bad = [r for r in dec if not (
        isinstance(r.get("features"), list) and len(r["features"]) == OBS_FLOATS
        and isinstance(r.get("cards"), list) and len(r["cards"]) == OBS_CARDS
        and isinstance(r.get("mask"), list) and len(r["mask"]) == N_ACTIONS
        and r.get("action") in range(N_ACTIONS) and r["mask"][r["action"]] )]
    print("replay 行：meta=%d decision=%d summary=%d 不完整=%d"
          % (sum(1 for r in lines if r.get("type") == "meta"),
             len(dec), sum(1 for r in lines if r.get("type") == "summary"), len(bad)))
    npz_out = os.path.join(out_dir, "human_play_bc.npz")
    info = convert_replays(out_dir, npz_out)
    print("转 BC npz：%s（%d 决策 / %d 局 / 跳过=%s / %.1f KB）"
          % (info["out"], info["decisions"], info["episodes"], info["skipped"], info["bytes"] / 1024))
    print("=" * 72)
    return {"state": st, "replay_lines": lines, "npz": info, "elapsed": elapsed}


def hero_name(h: Optional[Dict[str, Any]]) -> str:
    if not h:
        return "-"
    return str(h.get("name_zh") or h.get("name") or "-")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="HSBRSIM 人类对战界面（本地 Web UI）")
    ap.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    ap.add_argument("--host", default="127.0.0.1",
                    help="监听地址（默认 127.0.0.1；改成 0.0.0.0 会暴露到网络，自行承担风险）")
    ap.add_argument("--seed", type=int, default=1234, help="初始对局 seed")
    ap.add_argument("--seat", type=int, default=0, help="人类座位 0..7（默认 0）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="replay 输出目录")
    ap.add_argument("--selftest", action="store_true", help="不开服务器：脚本化跑完一局并校验 replay")
    ap.add_argument("--config-json", default="",
                    help="透传给引擎的 RulesConfig JSON（例如强制畸变怪大厅）")
    ap.add_argument("--aberration", action="store_true",
                    help="强制大厅包含畸变怪（等价于 config_json.aberration_forced=true）")
    ap.add_argument("--to-npz", default="", metavar="DIR", help="把 DIR 下 *.jsonl.gz 转成 BC npz 后退出")
    ap.add_argument("--npz-out", default="", help="--to-npz 的输出 npz 路径")
    ap.add_argument("--skip-hero-select", action="store_true",
                    help="--to-npz 时跳过英雄选择阶段决策")
    ap.add_argument("--quiet", action="store_true", help="不打印启动横幅")
    args = ap.parse_args(argv)

    config: Dict[str, Any] = {}
    if args.config_json:
        config = _parse_config(args.config_json)
    if args.aberration:
        config = dict(config)
        config["aberration_forced"] = True

    if args.to_npz:
        out = args.npz_out or os.path.join(os.path.dirname(os.path.abspath(args.to_npz)) or ".",
                                          "human_play_bc.npz")
        info = convert_replays(args.to_npz, out, skip_hero_select=bool(args.skip_hero_select))
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    if args.selftest:
        run_selftest(int(args.seed), int(args.seat), os.path.abspath(args.out),
                     config_json=config)
        return 0

    E = load_engine()
    sess = GameSession(seed=int(args.seed), seat=int(args.seat),
                       out_dir=os.path.abspath(args.out), engine=E, config_json=config)
    httpd = ArenaServer((str(args.host), int(args.port)), sess)
    url = f"http://{args.host}:{args.port}"
    if not args.quiet:
        print("HSBRSIM 人类对战界面已启动：%s" % url)
        print("  seat=%d seed=%d engine=%s replay=%s"
              % (sess.seat, sess.seed, E.game_version(), sess.replay_path))
        print("  本地浏览器：ssh -L %d:127.0.0.1:%d <host>，然后打开 %s" % (args.port, args.port, url))
        print("  Ctrl+C 退出；每局 replay 落在 %s" % sess.out_dir)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
