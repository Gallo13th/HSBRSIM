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
- replay 逐决策**增量**写 gzip（多 member 拼接，``gzip.open`` 可正常读）；
- 撤回：每个可撤回动作前用引擎 ``Game.state_json()`` 做**精确快照**（``Game.from_json``
  可逐位续局），栈默认 50 步（≥10）；撤回后 replay 追加 ``{"type":"undo"}`` 标记，
  ``convert_replays`` 把被撤回的决策行**剔除**（不进入 BC 数据）。

HTTP 端点
---------
======  ======  ==========================================================
方法    路径     说明
======  ======  ==========================================================
GET     /       内嵌 HTML/JS 界面
GET     /state  当前状态 JSON（商店/手牌/场上/HUD/合法动作/对手/pending/撤回）
POST    /act    ``{"action": int}`` 执行一步并返回新状态（非法动作 400）
POST    /undo   撤回上一步并返回新状态（不可撤回时 400 + 原因）
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
- 撤回时追加 ``{"type": "undo", decision, action, turn, phase, ...}``：``decision`` 指向被
  撤回的决策序号；``convert_replays`` 读到 undo 就弹出对应 decision 行（``skipped.undone``）；
- 末行 ``{"type": "summary", ...}``：placement / placements / decisions / turns。

BC 转换：``--to-npz`` 生成 ``obs``(n,3351 float32) + ``cards`` + ``mask``(bool) +
``action`` + ``turn/tier/gold/episode_id``，与 ``scripts/train_compound_bc.py::load_npz``
的字段约定一致（也保留 ``features`` float16 以便复用现有工具）。
"""

from __future__ import annotations

import argparse
import copy
import functools
import glob
import gzip
import hashlib
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
#: 撤回栈默认深度（任务要求至少 10；50 × ~30KB 快照 ≈ 1.5MB，可接受）
UNDO_LIMIT_DEFAULT = 50
#: replay 里撤回的标记方式：追加 ``{"type":"undo"}``，转换 BC 时剔除被撤回的决策
UNDO_REPLAY_MODE = "mark-undone"

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
# 拖拽 -> 标准动作（纯函数；前端 JS 与单测共用同一映射契约）
# ══════════════════════════════════════════════════════════════════════

#: 拖拽源/目标类型（与 HTML ``data-drag-kind`` / ``data-drop`` 一致）
DRAG_SHOP = "shop"
DRAG_HAND = "hand"
DRAG_BOARD = "board"
DRAG_BUY = "buy"
DRAG_SELL = "sell"
DRAG_ACTIVATE = "activate"


def _drag_result(ok: bool, action: Optional[int] = None, reason: str = "",
                 label: str = "", toast: str = "", note: str = "") -> Dict[str, Any]:
    """统一的拖拽结果：``action=None`` 表示**不调用 /act**，只提示并回滚。"""
    return {
        "ok": bool(ok),
        "action": int(action) if action is not None else None,
        "reason": reason,
        "label": label,
        "toast": toast,
        "note": note,
    }


def drag_action(st: Any, src_kind: Any, src_index: Any,
                dst_kind: Any, dst_index: Any = None) -> Dict[str, Any]:
    """把一次拖拽映射成 245 维标准动作（动作 id 与 ``hsbg/env/action_space_std.py`` 同源）。

    映射表（对应 ``docs/HUMAN_ARENA_UI_SPEC_V2.md`` 第 3 节）：

    - 商店 i -> 战场/购买区：``Buy == 8+i``；**只购买**，卡进手牌并提示“已购买”。
      “买完自动打出”需要新增端点，本版不做。
    - 手牌 h -> 战场空槽 p：``Play == 46+h*8+p``。
    - 手牌 h（磁力）-> 战场随从 b：``Magnetize == 126+h*7+b``。
    - 战场 from -> 战场 to：``Move == 196+from*7+to``（from != to）。
    - 战场 b -> 出售区：``Sell == 16+b``；战场 b -> 发动区：``Activate == 23+b``。

    非法拖拽返回 ``ok=False`` + 可读 ``reason``，前端据此**回滚且不提交**。
    所有合法动作还会再核对当前 ``state.mask``，避免用过期 UI 发非法动作。
    """
    st = st if isinstance(st, dict) else {}
    if st.get("over"):
        return _drag_result(False, reason="对局已结束，不能再操作")
    if st.get("pending"):
        return _drag_result(False, reason="选择面板打开时先完成选择/取消，拖拽已暂停")
    if st.get("busy"):
        return _drag_result(False, reason="请求处理中，请稍候")

    def _int(v: Any) -> Optional[int]:
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _allowed(a: Optional[int]) -> bool:
        if a is None or not 0 <= int(a) < N_ACTIONS:
            return False
        mask = st.get("mask")
        return bool(mask[int(a)]) if isinstance(mask, list) and mask else True

    def _bad(reason: str) -> Dict[str, Any]:
        return _drag_result(False, reason=reason)

    src = str(src_kind or "")
    dst = str(dst_kind or "")
    si, di = _int(src_index), _int(dst_index)

    if src == DRAG_SHOP:
        shop = st.get("shop") or []
        if dst not in (DRAG_BOARD, DRAG_HAND, DRAG_BUY):
            return _bad("商店卡只能拖到购买区/战场：只触发 Buy，购买后进入手牌")
        if si is None or not 0 <= si < len(shop):
            return _bad("该酒馆槽位为空，不能购买")
        c = shop[si] or {}
        a = _int(c.get("buy"))
        if a is None or not _allowed(a):
            return _bad(str(c.get("buy_reason") or "该酒馆槽位当前不能购买"))
        name = c.get("name_zh") or c.get("name") or "?"
        return _drag_result(
            True, a,
            label="购买 %s -> Buy(%d) = %d" % (name, si, a),
            toast="已购买：%s，已进入手牌；请从手牌拖到战场打出" % name,
            note="只触发 Buy；买完自动打出需要新端点，本版不做",
        )

    if src == DRAG_HAND:
        if dst != DRAG_BOARD:
            return _bad("手牌只能拖到我方战场槽位（Play 或 Magnetize）")
        hand = st.get("hand") or []
        if si is None or not 0 <= si < len(hand):
            return _bad("该手牌槽位为空")
        c = hand[si] or {}
        if di is None or not 0 <= di < N_POS:
            return _bad("战场位置越界（0..%d）" % (N_POS - 1))
        board = st.get("board") or []
        name = c.get("name_zh") or c.get("name") or "?"
        if di < len(board):
            # 已有随从：优先解释为磁力吸附目标（空槽才是 Play）。
            mag = next((m for m in (c.get("magnetize") or [])
                        if _int(m.get("board")) == di), None)
            a = _int((mag or {}).get("action"))
            if mag is not None and _allowed(a):
                target = (board[di] or {}).get("name_zh") or (board[di] or {}).get("name") or "?"
                return _drag_result(
                    True, a,
                    label="%s 磁力 -> %s：Magnetize(%d,%d) = %d" % (name, target, si, di, a),
                    toast="已磁力吸附：%s -> %s" % (name, target),
                )
            return _bad(str(c.get("magnetize_reason") or "该牌不能磁力吸附到这个随从"))
        p = next((x for x in (c.get("play") or []) if _int(x.get("pos")) == di), None)
        a = _int((p or {}).get("action"))
        if p is not None and _allowed(a):
            return _drag_result(
                True, a,
                label="%s 打出到 %d 号位：Play(%d,%d) = %d" % (name, di + 1, si, di, a),
                toast="已打出：%s" % name,
            )
        return _bad(str(c.get("play_reason") or "现在不能打出到这个位置"))

    if src == DRAG_BOARD:
        board = st.get("board") or []
        if si is None or not 0 <= si < len(board):
            return _bad("该战场槽位为空")
        b = board[si] or {}
        name = b.get("name_zh") or b.get("name") or "?"
        if dst == DRAG_BOARD:
            if di is None or not 0 <= di < N_BOARD:
                return _bad("战场位置越界（0..%d）" % (N_BOARD - 1))
            if di == si:
                return _bad("随从已在原位，未提交")
            mv = next((m for m in (b.get("move") or []) if _int(m.get("to")) == di), None)
            a = _int((mv or {}).get("action"))
            if mv is not None and _allowed(a):
                return _drag_result(
                    True, a,
                    label="移动 %s：%d -> %d = Move %d" % (name, si, di, a),
                    toast="已移动：%s 到 %d 号位" % (name, di + 1),
                )
            return _bad("该位置不能移动（以引擎 move 掩码为准）")
        if dst == DRAG_SELL:
            a = _int(b.get("sell"))
            if a is None or not _allowed(a):
                return _bad(str(b.get("sell_reason") or "当前不能出售"))
            return _drag_result(True, a, label="出售 %s = Sell %d" % (name, a),
                                toast="已出售：%s" % name)
        if dst == DRAG_ACTIVATE:
            a = _int(b.get("activate"))
            if a is None or not _allowed(a):
                return _bad(str(b.get("activate_reason") or "该随从没有可发动技能"))
            return _drag_result(True, a, label="发动 %s = Activate %d" % (name, a),
                                toast="已发动：%s" % name)
        return _bad("战场随从只能拖到战场槽位/出售区/发动区")

    return _bad("未知拖拽源：%s" % (src or "?"))


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
                 engine: Any = None, config_json: Any = None,
                 undo_limit: int = UNDO_LIMIT_DEFAULT) -> None:
        self.E = engine or load_engine()
        self.seat = int(seat)
        if not 0 <= self.seat < 8:
            raise ValueError(f"seat 必须在 0..7，得到 {seat}")
        self.out_dir = os.path.abspath(out_dir)
        os.makedirs(self.out_dir, exist_ok=True)
        self._stamp_seq = 0
        self.seed = int(seed)
        # 撤回栈：每步动作前的引擎 state_json + 会话计数（new_game 清空）
        self.undo_limit = max(10, int(undo_limit))
        self.undo_stack: List[Dict[str, Any]] = []
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
        # 新局清空撤回栈（旧局快照不能跨局使用）
        self.undo_stack = []
        self.undo_barrier = ""
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

        undo_ok, undo_reason = self.can_undo()
        return {
            "ok": True,
            "seat": self.seat,
            "seed": self.seed,
            "turn": v.get("turn"),
            "phase": phase,
            "phase_label": {"hero_select": "选择英雄", "recruit": "招募",
                            "game_over": "对局结束"}.get(phase, phase),
            "over": bool(g.is_over()),
            "undo": {"enabled": undo_ok, "reason": undo_reason,
                      "depth": len(self.undo_stack), "limit": self.undo_limit},
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

    def _undo_reason(self) -> str:
        """返回撤回禁用原因；战斗结算/Discover 选择点不可跨越。"""
        if self.over or self.game.is_over():
            return "对局已结束，不能撤回"
        v = json.loads(self.game.view(self.seat))
        phase = str(v.get("phase") or "")
        if phase in ("combat", "game_over"):
            return "战斗已结算，不能撤回"
        me = v.get("me") or {}
        if me.get("pending"):
            kind = str((me.get("pending") or {}).get("kind") or "")
            if kind == "discover":
                return "Discover 已选/选择面板进行中，不能撤回"
        if not self.undo_stack:
            return self.undo_barrier or "没有可撤回的动作"
        return ""

    def can_undo(self) -> Tuple[bool, str]:
        reason = self._undo_reason()
        return (not reason, reason)

    def undo(self) -> Dict[str, Any]:
        ok, reason = self.can_undo()
        if not ok:
            raise IllegalAction(reason)
        item = self.undo_stack.pop()
        # state_json 是引擎的精确序列化；from_json 恢复 RNG、bot 与 pending。
        self.game = self.E.Game.from_json(item["state_json"])
        self.decisions = int(item["decisions"])
        self.steps = int(item["steps"])
        self.over = False
        self.placement = 0
        self.placements = []
        self.last_my_combat = copy.deepcopy(item.get("last_my_combat"))
        with gzip.open(self.replay_path, "rt", encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        for rec in reversed(records):
            if (rec.get("type") == "decision" and not rec.get("undone")
                    and rec.get("decision") == item["decision"]):
                rec["undone"] = True
                break
        # 只在 Undo 重写日志，使下载的原始 decision 本身携带 undone: true。
        with gzip.open(self.replay_path, "wt", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._append_line({"type": "undo", "decision": item["decision"],
                           "action": item["action"], "turn": item["turn"],
                           "phase": item["phase"], "undone": True})
        return self.state()
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
        self.undo_stack.append({
            "state_json": g.state_json(), "decisions": self.decisions,
            "steps": self.steps, "decision": self.decisions, "action": a,
            "turn": turn, "phase": phase,
            "last_my_combat": copy.deepcopy(self.last_my_combat),
        })
        if len(self.undo_stack) > self.undo_limit:
            self.undo_stack.pop(0)
        try:
            g.step(self.seat, a)
        except Exception as exc:  # noqa: BLE001 - 掩码通过但引擎仍拒绝：包装成 400
            self.undo_stack.pop()
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
        pending_kind = str(((snap.get("me") or {}).get("pending") or {}).get("kind") or "")
        if a == A_END or int(self.game.turn) != turn or self.game.is_over():
            self.undo_stack.clear()
            self.undo_barrier = "回合已结束 / 战斗已结算，不能撤回"
        elif pending_kind == "discover" and A_CHOOSE <= a < A_CHOOSE + 16:
            self.undo_stack.clear()
            self.undo_barrier = "Discover 已选，不能撤回"
        else:
            self.undo_barrier = ""
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
    skipped = {"hero_select": 0, "bad": 0, "meta": 0, "undone": 0}
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
                if rec.get("undone"):
                    skipped["undone"] += 1
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
:root{
  --bg:#0b0e14;--panel:#141922;--panel2:#1b2230;--line:#28303f;
  --fg:#e9eef7;--dim:#8b98ad;--accent:#5b9dff;--danger:#e06c6c;
  --gold:#f0c674;--good:#67c98a;--hp:#ff8a8a;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--fg)}
body{font:13px/1.45 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;padding-bottom:64px}
body.busy .card,body.busy button,body.busy .slot{pointer-events:none;opacity:.7}
button,a,input{font:inherit}
button{cursor:pointer}
.bad{color:var(--danger)}.good{color:var(--good)}.gold{color:var(--gold)}.dim{color:var(--dim)}
.mini{font-size:12px;color:var(--dim);line-height:1.4}
h2{margin:0;font-size:15px;font-weight:700}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
kbd{font:12px/1 "Segoe UI",sans-serif;background:#0e131b;border:1px solid var(--line);border-radius:8px;padding:0 8px;color:var(--fg)}

/* ── 顶部 HUD（固定一行 + 提示行） ─────────────────────────── */
header#hud{position:sticky;top:0;z-index:40;background:var(--bg);border-bottom:1px solid var(--line)}
.hudrow{display:flex;align-items:center;gap:8px;padding:8px 16px;min-height:48px;overflow:hidden;white-space:nowrap}
.brand{font-size:20px;font-weight:700;color:var(--accent);margin-right:8px;flex-shrink:0}
.brand small{font-size:12px;color:var(--dim);font-weight:400;margin-left:8px}
#hudstats{display:flex;align-items:center;gap:8px;flex:1;min-width:0;overflow-x:auto;overflow-y:hidden;scrollbar-width:none}
#hudstats::-webkit-scrollbar{display:none}
#endturnbtn{flex-shrink:0}
.hstat{display:inline-flex;align-items:baseline;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px}
.hstat i{font-size:12px;color:var(--dim);font-style:normal}
.hstat b{font-size:15px;font-weight:700;color:var(--fg)}
.hstat.hp b{color:var(--hp)}.hstat.gold b{color:var(--gold)}
.hud-hero{font-size:15px;font-weight:700;color:var(--fg);margin-right:8px}
.hintrow{display:flex;align-items:center;gap:8px;padding:0 16px 8px;min-height:24px}
#hintline{font-size:13px;color:#b9c6da;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(max-width:900px){#hintline{white-space:normal}}

/* ── 主布局 ─────────────────────────────────────────────────── */
main.arena{max-width:1760px;margin:0 auto;padding:16px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:16px;align-items:start}
.left,.right{display:flex;flex-direction:column;gap:16px;min-width:0}
.right{display:flex;flex-direction:column;gap:16px;min-width:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px;min-width:0}
.phead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
.phead .hint{font-size:12px;color:var(--dim);font-weight:400}
.pill{display:inline-flex;gap:8px;align-items:baseline;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px;font-size:12px;color:var(--dim)}
.pill i{font-style:normal}
.pill b{font-size:13px;color:var(--fg)}
.chips-line{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}

/* ── 卡牌网格 ───────────────────────────────────────────────── */
.grid{display:grid;gap:8px;overflow-x:auto;padding-bottom:8px}
.shop-grid{grid-template-columns:repeat(8,minmax(92px,1fr))}
.board-grid{grid-template-columns:repeat(7,minmax(108px,1fr))}
.hand-grid{grid-template-columns:repeat(10,minmax(88px,1fr))}
.slot{position:relative;min-height:168px;border:1px dashed var(--line);border-radius:8px;padding:8px;background:#10151e;transition:border-color .1s,background .1s,box-shadow .1s}
.slot.empty{display:flex;align-items:center;justify-content:center;color:#556176;font-size:12px;text-align:center}
.slot.play-target{border:2px dashed var(--accent);background:rgba(91,157,255,.1);box-shadow:inset 0 0 0 1px rgba(91,157,255,.25)}
.slot.mag-target{border:2px dashed var(--good);background:rgba(103,201,138,.08)}
.slot.move-target{border:2px dashed var(--accent);background:rgba(91,157,255,.06)}
.slot.dragover{border-color:var(--good);background:#16251d}
.slot.dragover-bad{border-color:var(--danger);background:#2a1a1a}
.card{display:flex;flex-direction:column;height:100%;min-width:0;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px;cursor:pointer;user-select:none;overflow:hidden;transition:border-color .1s,box-shadow .1s,transform .1s;touch-action:manipulation}
.card:hover{border-color:var(--accent)}
.card:active{cursor:grabbing}
.card.golden{border-color:#8a6d20}
.card.golden .cname{color:var(--gold)}
.card.buyable{border-color:var(--good)}
.card.muted{opacity:.6}
.card.unavailable{opacity:.45}
.card.selected{border-color:var(--accent);box-shadow:inset 0 0 0 2px var(--accent)}
.card.dragging{opacity:.4;transform:scale(.97)}
.card.shake{animation:shake .35s linear}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-4px)}50%{transform:translateX(4px)}75%{transform:translateX(-2px)}}
.dragghost{position:fixed;z-index:80;pointer-events:none;width:132px;opacity:.9;box-shadow:0 12px 30px rgba(0,0,0,.55);transform:translate(-50%,-50%) rotate(1deg)}
.ctop{display:flex;align-items:center;gap:8px;margin-bottom:8px;min-height:20px}
.tier{border:1px solid var(--line);border-radius:8px;padding:0 8px;font-size:12px;color:var(--fg);background:#0e131b}
.tag{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:0 8px;color:var(--dim);background:#0e131b}
.tag.gold{color:var(--gold);border-color:#8a6d20}
.tag.accent{color:var(--accent);border-color:var(--accent)}
.tag.danger{color:var(--danger);border-color:var(--danger)}
.price{margin-left:auto;font-size:13px;font-weight:700;color:var(--gold);white-space:nowrap}
.cname{font-size:13px;font-weight:700;line-height:1.3;margin-bottom:8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.crace{font-size:12px;color:var(--dim);margin-bottom:8px}
.ctext{font-size:12px;color:#b9c4d4;line-height:1.4;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;flex:1}
.cfoot{margin-top:auto;display:flex;align-items:center;gap:8px;padding-top:8px}
.cstats{display:inline-flex;align-items:center;gap:8px;background:#0e131b;border:1px solid var(--line);border-radius:8px;padding:0 8px;font-size:13px}
.cstats .atk{color:#ffd479;font-weight:700}
.cstats .hp{color:var(--hp);font-weight:700}
.cstats .slash{color:var(--dim)}
.stat-mini{font-size:12px;color:var(--dim)}
.kwchips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.kw{font-size:12px;background:#1e2a3d;border:1px solid #31435f;border-radius:8px;padding:0 8px;color:#bcd0ff}
.kw.gold{background:#2d2512;border-color:#6f5a1d;color:var(--gold)}
.cnote{font-size:12px;color:var(--gold);margin-top:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.details-inline{font-size:12px;color:var(--dim);margin-top:8px}
details>summary{cursor:pointer;list-style:none;font-size:12px;color:var(--accent)}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"+ ";color:var(--dim)}
details[open]>summary::before{content:"- "}
.quote{font-size:12px;color:#b9c4d4;line-height:1.45;margin-top:8px;white-space:pre-wrap}

/* ── 拖放区 / 按钮 / 撤回 ───────────────────────────────────── */
.droprow{display:flex;gap:8px;margin-top:8px}
#sellrow{display:flex;flex:0 0 200px}
#sellzone{width:100%}
.dropzone{flex:1;border:1px dashed var(--line);border-radius:8px;padding:8px;color:var(--dim);font-size:12px;min-height:40px;display:flex;align-items:center;justify-content:center;text-align:center}
.dropzone.danger{border-color:#6f3a3a;color:#e6a0a0;background:#1c1216}
.dropzone.dragover{border-color:var(--good);background:#16251d;color:var(--good)}
.dropzone.dragover-bad{border-color:var(--danger);background:#2a1a1a;color:var(--danger)}
.btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.btn{background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px 16px;font-size:13px;line-height:1.2;display:inline-flex;align-items:center;gap:8px}
.btn:hover:not(:disabled){border-color:var(--accent)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn.primary{background:#1d3557;border-color:var(--accent);color:#fff;font-weight:700}
.btn.ghost{background:transparent}
.btn.danger{background:#3a1e1e;border-color:var(--danger);color:#ffd0d0}
.btn.small{padding:8px;font-size:12px}
.undoline{display:flex;align-items:center;gap:8px;margin-top:8px;min-height:24px}
.undoline .mini{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* ── 选中操作条 ─────────────────────────────────────────────── */
.selbar{display:flex;flex-direction:column;gap:8px;background:#16202f;border:1px solid var(--accent);border-radius:8px;padding:16px;position:sticky;top:80px;z-index:35}
.selbar.hidden{display:none}
.selhead{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.selname{font-size:15px;font-weight:700}
.selacts{display:flex;flex-wrap:wrap;gap:8px}
.seldetails{margin-top:8px}

/* ── 右侧信息 ───────────────────────────────────────────────── */
.opp{display:flex;flex-direction:column;gap:8px}
.opprow{padding:8px 0;border-bottom:1px solid var(--line);font-size:13px}
.opprow:last-child{border-bottom:0}
.opphead{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.opphead b{font-size:13px}
.opphead .mini{margin-left:auto}
.opprow.dead{opacity:.5;text-decoration:line-through}
.lineitem{padding:8px 0;border-bottom:1px solid var(--line);font-size:13px;display:flex;flex-direction:column;gap:8px}
.lineitem:last-child{border-bottom:0}
.lineitem .lhead{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.mycombat{border-left:3px solid var(--line);padding-left:8px;margin-bottom:8px}
.mycombat.win{border-color:var(--good)}.mycombat.loss{border-color:var(--danger)}.mycombat.tie{border-color:var(--gold)}
.frames{max-height:220px;overflow:auto;font-size:12px}
.frames .fr{border-bottom:1px solid var(--line);padding:8px 0}
.eventline{font-size:12px;border-bottom:1px solid var(--line);padding:8px 0}
.deity{border-left:3px solid #5a4478;padding-left:8px;display:flex;flex-direction:column;gap:8px}
.deity .dname{font-size:15px}
.deity .dmeta{font-size:12px;color:var(--dim)}
.deity .dtrig{font-size:12px;line-height:1.4}
.deity .dtrig b{color:var(--gold)}
.deity .src{color:var(--dim);font-size:12px}
.dnumline{display:flex;flex-wrap:wrap;gap:8px}
.dnum{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:0 8px;font-size:12px}

/* ── 数据 / 开发折叠区 ─────────────────────────────────────── */
.data-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}
.data-cell{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:8px;display:flex;flex-direction:column;gap:8px}
.data-cell i{font-size:12px;color:var(--dim);font-style:normal}
.data-cell b{font-size:15px}
.data-cell.wide{grid-column:1 / -1}
.data-cell b.file{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.newgame{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
#seed{width:120px;background:#0e131b;border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px}
.devpanel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px}
.devpanel>summary{font-size:13px;color:var(--dim)}
#connhint{margin:8px 0}
#legal{display:flex;flex-wrap:wrap;gap:8px;max-height:200px;overflow:auto}
#legal span{font-size:12px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:0 8px;color:var(--dim)}
#statetext{white-space:pre-wrap;font-size:12px;line-height:1.4;color:#c8d2e8;max-height:360px;overflow:auto;margin:8px 0 0;background:#0e131b;border:1px solid var(--line);border-radius:8px;padding:8px}

/* ── 浮层 / 菜单 / 提示 ─────────────────────────────────────── */
#overlay{position:fixed;inset:0;background:rgba(6,9,14,.82);display:flex;align-items:center;justify-content:center;z-index:60;padding:16px}
#overlay.hidden{display:none}
.pbox{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:24px;max-width:min(960px,94vw);max-height:88vh;overflow:auto;box-shadow:0 24px 64px rgba(0,0,0,.55)}
.pbox h2{font-size:20px;margin-bottom:8px}
.pbox .sub{font-size:13px;color:var(--dim);margin-bottom:8px}
.popts{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin:16px 0}
.optcard{position:relative;display:flex;flex-direction:column;gap:8px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:16px;cursor:pointer;user-select:none}
.optcard:hover{border-color:var(--accent)}
.optcard.disabled{opacity:.45;cursor:not-allowed}
.optcard .optcta{font-size:13px;font-weight:700;color:var(--accent);margin-top:auto}
.optcard .ctext{-webkit-line-clamp:unset;display:block;overflow:visible}
#menubox{position:fixed;inset:0;background:rgba(6,9,14,.75);display:flex;align-items:center;justify-content:center;z-index:70;padding:16px}
#menubox.hidden{display:none}
.menu{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px;max-width:min(560px,92vw);max-height:80vh;overflow:auto;display:flex;flex-direction:column;gap:8px}
.menu h3{margin:0 0 8px;font-size:15px}
#toast{position:fixed;left:50%;bottom:56px;transform:translateX(-50%);background:#3a1e1e;border:1px solid var(--danger);color:#fff;padding:8px 16px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:100;max-width:88vw;text-align:center}
#toast.show{opacity:1}
#toast.ok{background:#17301f;border-color:var(--good)}
#loading{position:fixed;top:64px;right:16px;background:#1d3557;border:1px solid var(--accent);color:#dce9ff;border-radius:8px;padding:8px 16px;font-size:12px;z-index:90;display:none}
body.busy #loading{display:block}
#shortcuts{position:fixed;right:8px;bottom:8px;z-index:30;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 16px;font-size:12px;color:var(--dim);display:flex;flex-wrap:wrap;gap:8px;max-width:calc(100vw - 16px);pointer-events:none}
#shortcuts b{color:var(--fg);font-weight:400}

/* ── 响应式：≥1280 双栏，≤900 单列 ─────────────────────────── */
@media(max-width:900px){
  main.arena{padding:8px}
  .layout{grid-template-columns:1fr}
  .right{position:static;max-height:none;overflow:visible;padding-right:0}
  .shop-grid{grid-template-columns:repeat(8,104px)}
  .board-grid{grid-template-columns:repeat(7,120px)}
  .hand-grid{grid-template-columns:repeat(10,96px)}
  .hudrow{padding:8px}
  .hintrow{padding:0 8px 8px}
  .brand small{display:none}
  #sellrow{flex:0 0 140px}
  .panel{padding:8px}
  .data-grid{grid-template-columns:1fr}
  .data-cell.wide{grid-column:auto}
}
</style>
</head>
<body>
<header id="hud">
  <div class="hudrow">
    <div class="brand">HSBRSIM<small>人类对战</small></div>
    <div id="hudstats"></div>
    <button id="endturnbtn" class="btn primary" disabled>结束回合</button>
  </div>
  <div class="hintrow"><span id="hintline">加载中…</span></div>
</header>

<main class="arena">
  <div id="selbar" class="selbar hidden"></div>
  <div class="layout">
    <div class="left">
      <section id="shoprow" class="panel">
        <div class="phead"><h2>鲍勃酒馆</h2><span id="tavernhint" class="hint"></span></div>
        <div id="taverninfo" class="chips-line"></div>
        <div id="shop" class="grid shop-grid" aria-label="鲍勃酒馆"></div>
        <div class="btns" id="buttons"></div>
        <div class="undoline">
          <button id="undobtn" class="btn" disabled>撤回</button>
          <span id="undoreason" class="mini"></span>
        </div>
      </section>

      <section id="boardrow" class="panel">
        <div class="phead"><h2>我方战场</h2><span id="boardhint" class="hint"></span></div>
        <div id="board" class="grid board-grid" aria-label="我方战场"></div>
        <div class="droprow">
          <div id="activatezone" class="dropzone" data-drop="activate">拖到这里发动技能</div>
          <div id="sellrow"><div id="sellzone" class="dropzone danger" data-drop="sell">拖到这里出售</div></div>
        </div>
      </section>

      <section id="handrow" class="panel">
        <div class="phead"><h2>手牌</h2><span id="handhint" class="hint"></span></div>
        <div id="hand" class="grid hand-grid" aria-label="手牌"></div>
      </section>
    </div>

    <aside class="right">
      <section class="panel">
        <div class="phead"><h2>对手</h2><span id="opphint" class="hint"></span></div>
        <div id="opp" class="opp"></div>
      </section>

      <section class="panel">
        <div class="phead"><h2>饰品与效果</h2><span id="trinkethint" class="hint"></span></div>
        <div id="trinkets" class="mini"></div>
        <div id="darkgift" style="margin-top:8px"></div>
        <div id="effects" class="mini" style="margin-top:8px"></div>
      </section>

      <section class="panel">
        <div class="phead"><h2>神明</h2><span id="deityhint" class="hint"></span></div>
        <div id="deity"></div>
      </section>

      <section class="panel">
        <div class="phead"><h2>上轮战果</h2><span id="combathint" class="hint"></span></div>
        <div id="mycombat"></div>
        <details data-key="all-combats"><summary>最近战斗</summary><div id="combats" class="mini"></div></details>
      </section>

      <section class="panel">
        <div class="phead"><h2>本回合事件</h2></div>
        <div id="events" class="mini"></div>
      </section>

      <section class="panel">
        <div class="phead"><h2>数据采集</h2><span id="replaymeta" class="hint"></span></div>
        <div class="data-grid">
          <div class="data-cell"><i>已记录</i><b id="decCount">0</b></div>
          <div class="data-cell"><i>撤回次数</i><b id="undoCount">0</b></div>
          <div class="data-cell wide"><i>可撤回深度</i><b id="undoDepth">0 / 0</b></div>
        </div>
        <a id="replaylink" href="/replay" download>下载 replay</a>
        <div id="newgame" class="newgame">
          <input id="seed" type="number" placeholder="seed" title="留空 = 当前 seed">
          <button id="newbtn" class="btn">新开一局</button>
        </div>
      </section>

      <details class="devpanel" id="devpanel">
        <summary>开发信息</summary>
        <div id="connhint" class="mini">状态源 /state · 提交入口 /act</div>
        <div id="legal"></div>
        <!--SNAPSHOT_TEXT-->
      </details>
    </aside>
  </div>
</main>

<div id="overlay" class="hidden"></div>
<div id="menubox" class="hidden"></div>
<div id="toast"></div>
<div id="loading">处理中…</div>
<div id="shortcuts">
  <span><kbd>Enter</kbd> <b>确认/结束</b></span>
  <span><kbd>Ctrl+Z</kbd> <b>撤回</b></span>
  <span><kbd>Esc</kbd> <b>取消选中</b></span>
  <span><kbd>1-8</kbd> <b>选商店格</b></span>
</div>

<script>
"use strict";
let S = /*STATE_JSON*/null;
const INITIAL_S = !!S;
let toastTimer = 0;
let BUSY = false;
let UNDO_COUNT = 0;
let SEL = {kind: null, index: null};
let MENU = {acts: []};
const DRAG = {payload:null, sourceEl:null, ghost:null, targetEl:null,
              timer:0, pointer:null, suppressClickUntil:0};

const $ = (id) => document.getElementById(id);
function esc(s) {
  return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
function evText(e) { return typeof e === "string" ? e : JSON.stringify(e); }
function basename(p) { return String(p || "").split("/").pop(); }
function fmtKB(b) { return (Number(b || 0) / 1024).toFixed(1) + " KB"; }
function cardName(c) { return c ? (c.name_zh || c.name || "?") : "?"; }
function heroName(h) { return h ? (h.name_zh || h.name) : "选择英雄"; }

function toast(msg, ok) {
  const t = $("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.toggle("ok", !!ok);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2800);
}
function setConn(ok, msg) {
  const el = $("connhint");
  if (!el) return;
  el.className = "mini" + (ok ? "" : " bad");
  el.textContent = ok
    ? "已连接 · 状态源 /state · 提交入口 /act"
    : ("连接异常" + (msg ? "：" + msg : "") + " · 提交未确认");
}

async function api(path, body, label) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  };
  let res, data;
  try {
    res = await fetch(path, opt);
  } catch (e) {
    setConn(false, String(e));
    toast("连接失败，提交未确认", false);
    return null;
  }
  try { data = await res.json(); } catch (e) { data = {error: "响应不是 JSON"}; }
  if (!res.ok) {
    setConn(true);
    const err = data.error || ("HTTP " + res.status);
    toast(label ? (label + " · 未提交：" + err) : ("读取状态失败：" + err), false);
    return null;
  }
  setConn(true);
  return data;
}

async function refresh() {
  const data = await api("/state");
  if (data) { S = data; render(); }
}
async function act(action, okMsg) {
  if (action === null || action === undefined) { toast("该操作当前不可用"); return; }
  if (!S) { toast("状态尚未加载"); return; }
  if (BUSY) { toast("请求处理中，请稍候"); return; }
  BUSY = true;
  document.body.classList.add("busy");
  try {
    const data = await api("/act", {action: action}, "动作 " + action);
    if (data) {
      S = data;
      SEL = {kind: null, index: null};
      render();
      if (okMsg) toast(okMsg, true);
    } else {
      await refresh();
    }
  } finally {
    BUSY = false;
    document.body.classList.remove("busy");
  }
}
async function undo() {
  if (!S || BUSY) return;
  if (!S.undo || !S.undo.enabled) { toast((S.undo && S.undo.reason) || "不可撤回，未提交"); return; }
  BUSY = true;
  document.body.classList.add("busy");
  try {
    const data = await api("/undo", {}, "撤回");
    if (data) {
      UNDO_COUNT += 1;
      S = data;
      SEL = {kind: null, index: null};
      render();
      toast("已撤回一步", true);
    } else {
      await refresh();
    }
  } finally {
    BUSY = false;
    document.body.classList.remove("busy");
  }
}
async function newGame(seedArg) {
  if (BUSY) { toast("请求处理中，请稍候"); return; }
  let body = {};
  if (seedArg === "random") {
    body = {};
  } else if (typeof seedArg === "number") {
    body = {seed: seedArg};
  } else {
    const raw = $("seed").value.trim();
    if (raw !== "") {
      const n = Number(raw);
      if (!Number.isFinite(n) || !Number.isInteger(n)) { toast("seed 需为整数", false); return; }
      body = {seed: n};
    }
  }
  BUSY = true;
  document.body.classList.add("busy");
  try {
    const data = await api("/new", body, "新开一局");
    if (data) {
      S = data;
      UNDO_COUNT = 0;
      SEL = {kind: null, index: null};
      render();
      toast("新开一局：seed " + data.seed, true);
    }
  } finally {
    BUSY = false;
    document.body.classList.remove("busy");
  }
}
function endTurn() {
  if (!S) return;
  const b = (S.buttons || []).find((x) => x.key === "end");
  if (!b) { toast("结束回合不可用，未提交"); return; }
  if (!b.enabled) { toast(b.reason || "当前不能结束回合", false); return; }
  act(b.action, "已结束回合");
}

/* ── 选择状态 ───────────────────────────────────────────────── */
function currentCard() {
  if (!S || !SEL.kind) return null;
  const list = SEL.kind === "shop" ? S.shop : (SEL.kind === "hand" ? S.hand : S.board);
  return (list || [])[SEL.index] || null;
}
function clearSel() {
  SEL = {kind: null, index: null};
  applySelection();
  updateHint();
}
function selectCard(kind, index) {
  if (!S || S.over) { toast("对局结束，未提交"); return; }
  if (S.pending) { toast("先完成选择面板"); return; }
  SEL = {kind: kind, index: index};
  applySelection();
  updateHint();
  const el = document.querySelector('.card[data-kind="' + kind + '"][data-index="' + index + '"]');
  if (el) el.scrollIntoView({block: "nearest", inline: "nearest"});
}
function updateHint() {
  const el = $("hintline");
  if (!el) return;
  let msg = "点卡选中，再点按钮或战场空位";
  if (S) {
    if (S.over) msg = "对局结束，可开新局或下载 replay";
    else if (S.pending) msg = "先完成弹出面板中的选择";
    else if (SEL.kind === "shop") msg = "已选商店卡，点购买或再点一次卡";
    else if (SEL.kind === "hand") msg = "点战场蓝色空位打出手牌";
    else if (SEL.kind === "board") msg = "点出售、发动或目标位置换位";
    else if (S.hero_select) msg = "先选择本局英雄";
  }
  el.textContent = msg;
}
function applySelection() {
  document.querySelectorAll(".card.selected, .slot.play-target, .slot.mag-target, .slot.move-target")
    .forEach((el) => el.classList.remove("selected", "play-target", "mag-target", "move-target"));
  const bar = $("selbar");
  if (!bar) return;
  if (!S || S.pending || S.over || !SEL.kind) {
    SEL = {kind: null, index: null};
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  const c = currentCard();
  if (!c) {
    SEL = {kind: null, index: null};
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  const card = document.querySelector('.card[data-kind="' + SEL.kind + '"][data-index="' + SEL.index + '"]');
  if (card) card.classList.add("selected");
  if (SEL.kind === "hand") {
    document.querySelectorAll("#board .slot").forEach((slot) => {
      const i = Number(slot.dataset.index);
      const occupied = !!(S.board || [])[i];
      if (!occupied && (c.play || []).some((p) => p.pos === i)) slot.classList.add("play-target");
      else if (occupied && (c.magnetize || []).some((m) => m.board === i)) slot.classList.add("mag-target");
    });
  } else if (SEL.kind === "board") {
    document.querySelectorAll("#board .slot").forEach((slot) => {
      const i = Number(slot.dataset.index);
      if ((c.move || []).some((m) => m.to === i)) slot.classList.add("move-target");
    });
  }
  renderSelbar(c);
  updateHint();
}

/* ── 选中操作条 ─────────────────────────────────────────────── */
function actionButton(label, action, opts) {
  opts = opts || {};
  const dis = action === null || action === undefined || opts.disabled;
  const title = opts.title || opts.reason || "";
  return '<button class="btn ' + (opts.cls || "") + '"' +
    (dis ? " disabled" : ' data-act="' + action + '"') +
    (opts.ok ? ' data-ok="' + esc(opts.ok) + '"' : "") +
    (title ? ' title="' + esc(title) + '"' : "") + ">" + esc(label) + "</button>";
}
function cardDetailsHTML(c) {
  const bits = [];
  if (c.text) bits.push('<div class="quote">[卡面] ' + esc(c.text) + "</div>");
  if (c.golden_text) bits.push('<div class="quote">[金卡] ' + esc(c.golden_text) + "</div>");
  for (const a of (c.attached || [])) {
    bits.push('<div class="quote"><b>' + esc(a.name_zh || a.name || "?") + "</b> " +
      esc(a.kind_label || "附件") + (a.text ? "：" + esc(a.text) : "") + "</div>");
  }
  if (c.breakdown_text) bits.push('<div class="quote">属性来源：' + esc(c.breakdown_text) + "</div>");
  if (!bits.length) return "";
  return '<details class="seldetails" data-key="sel-details"><summary>卡面详情</summary>' +
    bits.join("") + "</details>";
}
function renderSelbar(c) {
  const bar = $("selbar");
  if (!bar) return;
  const bits = [];
  bits.push('<div class="selhead"><span class="selname">' + esc(cardName(c)) + "</span>");
  if (c.tier) bits.push('<span class="tag">T' + esc(c.tier) + "</span>");
  if (c.golden) bits.push('<span class="tag gold">金色</span>');
  bits.push("</div>");
  bits.push('<div class="selacts">');
  if (SEL.kind === "shop") {
    bits.push(actionButton("购买" + (c.price_label ? " · " + c.price_label : ""), c.buy,
      {reason: c.buy_reason, ok: "已购买：" + cardName(c)}));
    const rb = (S.buttons || []).find((b) => b.key === "refresh");
    bits.push(actionButton("刷新" + (rb && rb.price !== null && rb.price !== undefined ? " · " + rb.price + "金" : ""),
      rb && rb.enabled ? rb.action : null, {reason: rb && rb.reason, cls: "ghost"}));
  } else if (SEL.kind === "hand") {
    const plays = c.play || [];
    const mags = c.magnetize || [];
    for (const p of plays) {
      bits.push(actionButton("打到 " + (p.pos + 1) + " 号位", p.action, {ok: "已打出：" + cardName(c)}));
    }
    for (const m of mags) {
      bits.push(actionButton("磁力→" + (m.board + 1), m.action, {ok: "已磁力吸附：" + cardName(c), cls: "ghost"}));
    }
    if (!plays.length && !mags.length) bits.push('<span class="mini bad">' + esc(c.play_reason || "当前不能打出") + "</span>");
  } else if (SEL.kind === "board") {
    if (c.sell !== null && c.sell !== undefined) {
      bits.push(actionButton("出售", c.sell, {ok: "已出售：" + cardName(c), cls: "danger"}));
    }
    if (c.activate !== null && c.activate !== undefined) {
      bits.push(actionButton("发动" + (c.activate_cost !== null && c.activate_cost !== undefined ? " · " + c.activate_cost + "金" : ""),
        c.activate, {ok: "已发动：" + cardName(c)}));
    }
    for (const m of (c.move || [])) {
      bits.push(actionButton("换到 " + (m.to + 1), m.action, {ok: "已换位：" + cardName(c), cls: "ghost"}));
    }
    bits.push('<button class="btn ghost" data-menu="1">更多</button>');
  }
  if (SEL.kind === "hand" && ((c.play || []).length || (c.magnetize || []).length)) {
    bits.push('<button class="btn ghost" data-menu="1">更多</button>');
  }
  bits.push('<button class="btn ghost" data-selclear="1">取消</button>');
  bits.push("</div>");
  bits.push(cardDetailsHTML(c));
  bar.innerHTML = bits.join("");
  bar.classList.remove("hidden");
}

/* ── 渲染 ───────────────────────────────────────────────────── */
function collectOpen() {
  const m = {};
  document.querySelectorAll("details[data-key]").forEach((d) => { m[d.dataset.key] = d.open; });
  return m;
}
function restoreOpen(m) {
  document.querySelectorAll("details[data-key]").forEach((d) => { if (m[d.dataset.key]) d.open = true; });
}
function hudStat(label, value, cls) {
  return '<span class="hstat' + (cls ? " " + cls : "") + '"><i>' + esc(label) +
    "</i><b>" + esc(String(value)) + "</b></span>";
}
function renderHud() {
  const h = S.hud || {};
  const end = (S.buttons || []).find((b) => b.key === "end") || null;
  const bits = [
    '<span class="hud-hero">' + esc(heroName(h.hero)) + "</span>",
    hudStat("回合", S.turn ?? "?"),
    hudStat("血量", (h.health ?? "?") + (h.armor ? " +" + h.armor : ""), "hp"),
    hudStat("金币", (h.gold ?? "?") + "/" + (h.max_gold ?? "?"), "gold"),
    hudStat("等级", "T" + (h.tier ?? "?")),
    hudStat("升本", (h.upgrade_price ?? "-") + " 金"),
    hudStat("已记录", (S.decisions ?? 0) + " 条")
  ];
  $("hudstats").innerHTML = bits.join("");
  const b = $("endturnbtn");
  b.disabled = !end || !end.enabled || !!S.over;
  b.textContent = S.over ? "对局结束" : "结束回合";
  b.title = (end && (end.reason || end.hint)) || "结束回合";
  if (end && end.enabled && !S.over) b.dataset.act = String(end.action);
  else delete b.dataset.act;
}
function renderTavern() {
  const h = S.hud || {};
  $("tavernhint").textContent = "槽位 " + ((S.shop || []).length) + "/8";
  $("taverninfo").innerHTML = [
    '<span class="pill"><i>刷新</i><b>' + esc((h.refresh_price ?? "?") + " 金") + "</b></span>",
    '<span class="pill"><i>升本</i><b>' + esc((h.upgrade_price ?? "?") + " 金 → T" + ((h.tier || 0) + 1)) + "</b></span>",
    '<span class="pill"><i>冻结</i><b>' + esc(h.frozen ? "是" : "否") + "</b></span>"
  ].join("");
}
function statsHTML(c) {
  if (!c.is_minion) return '<span class="stat-mini">' + esc(c.kind_label || "") + "</span>";
  const max = (c.max_hp !== null && c.max_hp !== undefined && c.max_hp !== c.hp)
    ? '<span class="stat-mini">上限 ' + esc(c.max_hp) + "</span>" : "";
  return '<span class="cstats"><b class="atk">' + esc(c.atk ?? "-") + '</b><span class="slash">/</span>' +
    '<b class="hp">' + esc(c.hp ?? "-") + "</b></span>" + max;
}
function kwHTML(c) {
  const out = [];
  for (const k of (c.keyword_labels || []).slice(0, 4)) out.push('<span class="kw">' + esc(k) + "</span>");
  if ((c.keyword_labels || []).length > 4) out.push('<span class="kw">+' + (c.keyword_labels.length - 4) + "</span>");
  return out.length ? '<div class="kwchips">' + out.join("") + "</div>" : "";
}
function cardHTML(c, opts) {
  opts = opts || {};
  const bits = [];
  const tierText = c.tier ? ("T" + c.tier) : (c.kind_label || "—");
  bits.push('<div class="ctop">');
  bits.push('<span class="tier">' + esc(tierText) + "</span>");
  if (c.golden) bits.push('<span class="tag gold">金色</span>');
  if (opts.price) bits.push('<span class="price">' + esc(opts.price) + "</span>");
  bits.push("</div>");
  bits.push('<div class="cname">' + esc(cardName(c)) + "</div>");
  const race = c.is_minion ? (c.race_text || "无") : (c.kind_label || c.race_text || "");
  if (race && race !== tierText) bits.push('<div class="crace">' + esc(race) + "</div>");
  bits.push(kwHTML(c));
  if (c.text) bits.push('<div class="ctext" title="' + esc(c.text) + '">' + esc(c.text) + "</div>");
  if (opts.note) bits.push('<div class="cnote">' + esc(opts.note) + "</div>");
  bits.push('<div class="cfoot">' + statsHTML(c) + "</div>");
  return bits.join("");
}
function makeCard(c, opts) {
  opts = opts || {};
  const el = document.createElement("div");
  el.className = "card" + (opts.state ? " " + opts.state : "");
  if (c.golden) el.classList.add("golden");
  if (opts.full) el.classList.add("fulltext");
  el.dataset.kind = opts.kind;
  el.dataset.index = String(opts.index);
  el.dataset.dragKind = opts.kind;
  el.dataset.dragIndex = String(opts.index);
  el.dataset.dragName = cardName(c);
  el.setAttribute("draggable", "true");
  el.setAttribute("aria-grabbed", "false");
  el.tabIndex = 0;
  el.innerHTML = cardHTML(c, opts);
  el.title = (c.card_id || "") + (opts.title ? "  " + opts.title : "");
  return el;
}
function shopState(c) {
  if (c.buy !== null && c.buy !== undefined) return "buyable";
  const r = String(c.buy_reason || "");
  if (r.indexOf("金币不足") >= 0 || r.indexOf("手牌已满") >= 0) return "muted";
  return "unavailable";
}
function renderShop() {
  const n = (S.action_space && S.action_space.N_SHOP) || 8;
  const box = $("shop");
  box.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const slot = document.createElement("div");
    slot.className = "slot shop-slot";
    slot.dataset.drop = "shop";
    slot.dataset.index = String(i);
    const c = (S.shop || [])[i];
    if (c) {
      slot.appendChild(makeCard(c, {
        kind: "shop", index: i, state: shopState(c),
        price: c.price_label || "", note: c.frozen ? "已冻结" : (c.owned ? "已持有 " + c.owned + (c.triple_need ? "/" + c.triple_need : "") : ""),
        title: c.buy_reason || ""
      }));
    } else {
      slot.classList.add("empty");
      slot.textContent = "空槽";
    }
    box.appendChild(slot);
  }
}
function renderHand() {
  const n = (S.action_space && S.action_space.N_HAND) || 10;
  const box = $("hand");
  box.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const slot = document.createElement("div");
    slot.className = "slot hand-slot";
    slot.dataset.drop = "hand";
    slot.dataset.index = String(i);
    const c = (S.hand || [])[i];
    if (c) {
      const usable = (c.play || []).length || (c.magnetize || []).length;
      const note = [c.play_cost_label, c.locked_label, c.temporary ? "临时牌" : ""].filter(Boolean).join(" · ");
      slot.appendChild(makeCard(c, {
        kind: "hand", index: i, state: usable ? "" : "unavailable",
        note: note, title: c.play_reason || ""
      }));
    } else {
      slot.classList.add("empty");
      slot.textContent = "空手牌位";
    }
    box.appendChild(slot);
  }
  const h = S.hud || {};
  $("handhint").textContent = (S.hand || []).length + " / " + (h.hand_limit ?? 10) +
    (h.hand_queue_len ? " · 队列 " + h.hand_queue_len : "");
}
function renderBoard() {
  const n = (S.action_space && S.action_space.N_BOARD) || 7;
  const box = $("board");
  box.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const slot = document.createElement("div");
    slot.className = "slot board-slot";
    slot.dataset.drop = "board";
    slot.dataset.index = String(i);
    const c = (S.board || [])[i];
    if (c) {
      slot.appendChild(makeCard(c, {
        kind: "board", index: i, note: (c.attached_names || []).length ? "附件 " + c.attached_names.length : "",
        title: c.sell_reason || ""
      }));
    } else {
      slot.classList.add("empty");
      slot.textContent = (i + 1) + " 号空位";
    }
    box.appendChild(slot);
  }
  $("boardhint").textContent = (S.board || []).length + " / 7 随从";
}
function renderButtons() {
  const box = $("buttons");
  box.innerHTML = "";
  for (const b of (S.buttons || [])) {
    if (b.key === "end") continue;
    const el = document.createElement("button");
    el.className = "btn" + (b.key === "dark_gift" ? " primary" : "");
    el.textContent = b.label + (b.price ? " · " + b.price + "金" : "");
    el.disabled = !b.enabled || !!S.over || b.action === null || b.action === undefined;
    if (!el.disabled) el.dataset.act = String(b.action);
    el.title = [b.hint, b.reason].filter(Boolean).join(" · ");
    box.appendChild(el);
  }
}
function renderTrinkets() {
  const h = S.hud || {};
  const ts = h.trinkets || [];
  $("trinkethint").textContent = "已获得 " + ts.length + " 个";
  $("trinkets").innerHTML = ts.length ? ts.map((t) => (
    '<div class="lineitem"><div class="lhead"><span class="tag">' + esc(t.slot_tag || "饰品") + "</span>" +
    "<b>" + esc(cardName(t)) + "</b></div>" +
    (t.text ? '<details data-key="trinket-' + esc(t.card_id || cardName(t)) + '"><summary>效果</summary>' +
      '<div class="quote">' + esc(t.text) + "</div></details>" : "") + "</div>"
  )).join("") : '<div class="mini dim">尚未获得饰品</div>';
  const dg = h.dark_gift;
  if (!dg) {
    $("darkgift").innerHTML = '<div class="mini dim">无黑暗之赐</div>';
  } else {
    $("darkgift").innerHTML = '<div class="lineitem"><div class="lhead"><span class="tag">黑暗之赐</span>' +
      '<span class="mini">' + esc(dg.cost_label || "?") + " · 已用 " + esc(dg.uses_label || "0") + "</span></div>" +
      '<div class="mini">可选星级 ' + esc(dg.tiers_label || "—") + " · 下回合 " + esc(dg.next_tiers_label || "—") + "</div>" +
      '<div class="selacts">' + actionButton("使用黑暗之赐", (!dg.enabled || S.over) ? null : dg.action,
        {reason: dg.reason, ok: "已使用黑暗之赐"}) + "</div></div>";
  }
  const effects = h.effects || [];
  $("effects").innerHTML = effects.map((e) => {
    const card = e.card || {};
    return '<div class="mini">持续效果：' + esc(cardName(card)) + " x" + esc(e.stacks) + "</div>";
  }).join("");
}
function renderDeity() {
  const d = (S.hud || {}).deity || {};
  $("deityhint").textContent = d.present ? ("门槛 " + d.threshold + " 只") : "本局无神明";
  if (!d.present) {
    $("deity").innerHTML = '<div class="mini dim">' + esc(d.hint || "本局大厅无畸变怪") + "</div>";
    return;
  }
  const trigs = (d.triggers || []).map((t, i) => (
    '<div class="dtrig">' + (i + 1) + ") <b>" + esc(t.phase_label || t.phase) + "</b> · " +
    esc(t.condition) + " · " + esc(t.effect) + " <span class=\"src\">" + esc(t.source) + "</span></div>"
  )).join("");
  const nums = (d.numbers || []).map((n) => (
    '<span class="dnum">' + esc(n.label) + " " + esc(n.value) + " <span class=\"src\">" + esc(n.source) + "</span></span>"
  )).join("");
  const dstats = (d.atk !== null && d.atk !== undefined)
    ? '<span class="cstats"><b class="atk">' + esc(d.atk) + '</b><span class="slash">/</span><b class="hp">' + esc(d.hp ?? "-") + "</b></span>"
    : "";
  $("deity").innerHTML = '<div class="deity">' +
    '<div class="dname"><b>' + esc(cardName(d)) + "</b> " + dstats + "</div>" +
    '<div class="dmeta">' + esc(d.tier_label || "") + " · " + esc(d.race_text || "") + "</div>" +
    (d.text ? '<details data-key="deity-text"><summary>卡面效果</summary><div class="quote">' + esc(d.text) + "</div></details>" : "") +
    (trigs ? '<details data-key="deity-triggers"><summary>触发 ' + (d.triggers || []).length + " 条</summary>" + trigs + "</details>" : "") +
    (nums ? '<details data-key="deity-nums"><summary>数值与来源</summary><div class="dnumline">' + nums + "</div></details>" : "") +
    "</div>";
}
function renderOpponents() {
  $("opphint").textContent = "存活 " + (S.alive ?? "?") + "/8";
  $("opp").innerHTML = (S.opponents || []).map((o) => {
    const oh = o.hero || {};
    const name = oh.name_zh || oh.name || "未知英雄";
    const status = o.alive
      ? ("生命 " + o.health + " · 护甲 " + (o.armor ?? 0) + " · T" + o.tier)
      : ("淘汰 #" + (o.placement || "?"));
    const seen = (o.seen_board || []).length
      ? ('<details data-key="seen-' + esc(o.id) + '"><summary>曾见 ' + o.seen_board.length + " 随从</summary>" +
         '<div class="mini">' + o.seen_board.map((m) => esc(cardName(m)) + " " + esc(m.atk ?? "") + "/" + esc(m.hp ?? "") +
           (m.golden ? " 金" : "")).join("、") + "</div></details>")
      : '<div class="mini dim">' + esc(o.seen_label || "从未交战") + "</div>";
    const tr = (o.trinket_names || []).length
      ? '<div class="mini">饰品：' + esc(o.trinket_names.join("、")) + "</div>" : "";
    return '<div class="opprow' + (o.alive ? "" : " dead") + '"><div class="opphead">' +
      "<b>" + esc(name) + "</b>" + (o.is_next ? '<span class="tag accent">下位</span>' : "") +
      '<span class="mini">' + esc(status) + "</span></div>" + seen + tr + "</div>";
  }).join("");
}
function renderCombat() {
  const mc = S.my_combat || {};
  $("combathint").textContent = mc.mine ? ((mc.result_label || "") + (mc.damage !== null && mc.damage !== undefined ? " · 伤害 " + mc.damage : "")) : "尚未交战";
  $("mycombat").innerHTML = '<div class="mycombat ' + esc(mc.result || "") + '">' +
    "<div>" + esc(mc.summary || "本局还没有自己的战斗记录") + "</div>" +
    (mc.cached ? '<div class="mini dim">缓存：本局最后一次所见</div>' : "") +
    (mc.truncated ? '<div class="mini bad">战斗被截断</div>' : "") +
    ((mc.frames && mc.frames.length)
      ? '<details data-key="combat-frames"><summary>战斗帧 ' + mc.frames.length + "/" + (mc.frame_count || mc.frames.length) + "</summary>" +
        '<div class="frames">' + mc.frames.map((f, i) => (
          '<div class="fr"><b>帧 ' + (i + 1) + "</b> " + esc((f.log || []).join("；")) +
          ((f.boards && f.boards.length)
            ? '<div class="mini">' + f.boards.map((bd) => bd.map((m) => esc(cardName(m)) + " " + esc(m.atk ?? "") + "/" + esc(m.hp ?? "")).join("、")).join(" vs ") + "</div>"
            : "") + "</div>"
        )).join("") + "</div></details>"
      : '<div class="mini dim">无战斗帧</div>') + "</div>";
  $("combats").innerHTML = (S.combats || []).length ? S.combats.map((c) => {
    const bName = (c.b === null || c.b === undefined) ? "幽灵" : ("座位 " + c.b);
    const win = c.winner === 0 ? ("座位 " + c.a + " 胜") : (c.winner === 1 ? (bName + " 胜") : "平");
    return esc((c.mine ? "下位 " : "") + "T" + c.turn + "：座位 " + c.a + " vs " + bName + " → " + win + "，伤害 " + c.damage);
  }).join("<br>") : '<span class="dim">暂无</span>';
}
function renderEvents() {
  const evs = S.events || [];
  if (!evs.length) { $("events").innerHTML = '<span class="dim">暂无</span>'; return; }
  const latest = evText(evs[evs.length - 1]);
  const rest = evs.slice(0, -1).reverse().map((e) => '<div class="eventline">' + esc(evText(e)) + "</div>").join("");
  $("events").innerHTML = '<div class="eventline">' + esc(latest) + "</div>" +
    (rest ? '<details data-key="events-more"><summary>更多日志</summary>' + rest + "</details>" : "");
}
function renderData() {
  $("decCount").textContent = String(S.decisions ?? 0);
  $("undoCount").textContent = String(UNDO_COUNT);
  $("undoDepth").textContent = (S.undo && S.undo.depth !== undefined ? S.undo.depth : 0) + " / " +
    (S.undo && S.undo.limit !== undefined ? S.undo.limit : 0);
  const rp = S.replay || {};
  $("replaymeta").textContent = rp.path ? (basename(rp.path) + " · " + fmtKB(rp.bytes)) : "—";
  $("replaymeta").title = rp.path || "";
  $("replaylink").href = "/replay?ts=" + Date.now();
  const ub = $("undobtn");
  ub.disabled = !(S.undo && S.undo.enabled);
  $("undoreason").textContent = (S.undo && S.undo.enabled)
    ? ("可撤回 " + (S.undo.depth || 0) + " 步")
    : ((S.undo && S.undo.reason) || "不可撤回");
}
function renderLegal() {
  $("legal").innerHTML = (S.legal || []).map((a, i) => (
    "<span>" + a + " " + esc((S.legal_names || [])[i] || "") + "</span>"
  )).join("");
}
async function loadDevText() {
  const box = $("devpanel");
  if (!box || !box.open || INITIAL_S) return;  /* /snapshot 已由服务端注入 */
  let pre = $("statetext");
  if (!pre) {
    pre = document.createElement("pre");
    pre.id = "statetext";
    box.appendChild(pre);
  }
  try {
    const res = await fetch("/snapshot.txt?ts=" + Date.now());
    if (!res.ok) throw new Error("HTTP " + res.status);
    pre.textContent = await res.text();
  } catch (e) {
    pre.textContent = "快照文本不可用：" + e;
  }
}

/* ── 浮层（pending / 对局结束） ─────────────────────────────── */
function pendingTitle(kind) {
  return {hero: "选择英雄", discover: "发现", trinket: "选择饰品", choose_one: "抉择",
          target: "选择目标", hero_power: "选择英雄技能", timewarp: "时空扭曲酒馆", quest: "选择任务"}[kind] || ("选择：" + kind);
}
function optionHTML(o, p) {
  const ok = o.action !== null && o.action !== undefined;
  const extra = [];
  if (p.kind === "hero") {
    extra.push('<div class="mini">护甲 ' + esc(o.armor ?? 0) + " · 生命 " + esc(o.hp ?? 30) + "</div>");
    if (o.power) extra.push('<div class="mini">技能：' + esc(o.power.name_zh || "") + (o.power.text ? " · " + esc(o.power.text) : "") + "</div>");
  }
  if (p.kind === "trinket") {
    extra.push('<div class="mini">' + (p.free ? "免费" : (o.price_label || "价格未知")) + "</div>");
  }
  if (p.kind === "timewarp" && o.cost !== undefined && o.cost !== null) extra.push('<div class="mini">' + esc(o.cost) + " 金</div>");
  if (o.chronum_cost !== undefined && o.chronum_cost !== null) extra.push('<div class="mini">' + esc(o.chronum_cost) + " 时空币</div>");
  if (o.weight !== undefined && o.weight !== null) extra.push('<div class="mini">权重 ' + esc(o.weight) + "%</div>");
  if (o.branch_label) extra.push('<div class="mini">' + esc(o.branch_label) + "</div>");
  if (o.goal) extra.push('<div class="mini">目标：' + esc(o.goal) + "</div>");
  if (o.reward) extra.push('<div class="mini">奖励：' + esc(cardName(o.reward)) + "</div>");
  return '<div class="optcard' + (ok ? "" : " disabled") + '"' +
    (ok ? ' data-act="' + o.action + '" data-ok="已选择：' + esc(cardName(o)) + '"' : "") +
    ' role="button" tabindex="' + (ok ? "0" : "-1") + '">' +
    cardHTML(o, {full: true}) + extra.join("") +
    (ok ? '<div class="optcta">选择</div>' : '<div class="mini bad">' + esc(o.action_reason || "当前不可选") + "</div>") +
    "</div>";
}
function renderOverlay() {
  const ov = $("overlay");
  if (!ov) return;
  if (S.over) {
    ov.classList.remove("hidden");
    ov.innerHTML = '<div class="pbox"><h2>对局结束</h2>' +
      '<div class="sub">名次 <b class="good">' + esc(S.placement) + "</b> / 8 · 已记录 " + esc(S.decisions) + " 条决策</div>" +
      '<div class="mini">' + esc(basename((S.replay || {}).path || "")) + " · " + fmtKB((S.replay || {}).bytes) + "</div>" +
      '<div class="btns" style="margin-top:16px">' +
      '<button class="btn primary" data-newgame="same">同 seed 再来</button>' +
      '<button class="btn" data-newgame="random">随机新局</button>' +
      '<a class="btn" href="/replay?ts=' + Date.now() + '" download>下载 replay</a></div></div>';
    return;
  }
  const p = S.pending;
  if (!p) { ov.classList.add("hidden"); ov.innerHTML = ""; return; }
  ov.classList.remove("hidden");
  const bits = [];
  bits.push('<div class="pbox"><h2>' + esc(p.kind_label || pendingTitle(p.kind)) + "</h2>");
  if (p.hint) bits.push('<div class="sub">' + esc(p.hint) + "</div>");
  if (p.source && (p.source.name_zh || p.source.name)) {
    bits.push('<div class="sub">来源：' + esc(cardName(p.source)) + (p.source.text ? " · " + esc(p.source.text) : "") + "</div>");
  }
  if (p.replace) bits.push('<div class="sub">替换：' + esc(cardName(p.replace)) + "</div>");
  bits.push('<div class="popts">');
  if (p.kind === "target") {
    for (const t of (p.targets || [])) {
      const ok = t.action !== null && t.action !== undefined;
      bits.push('<div class="optcard' + (ok ? "" : " disabled") + '"' +
        (ok ? ' data-act="' + t.action + '" data-ok="已选择目标"' : "") + ' role="button" tabindex="' + (ok ? "0" : "-1") + '">' +
        '<div class="cname">' + esc(t.name) + "</div>" +
        '<div class="mini">目标 ' + esc(t.index) + "</div>" +
        (ok ? '<div class="optcta">选择</div>' : '<div class="mini bad">' + esc(t.action_reason || "不可选") + "</div>") + "</div>");
    }
  } else {
    for (const o of (p.options || [])) bits.push(optionHTML(o, p));
  }
  bits.push("</div>");
  if (p.chronum !== null && p.chronum !== undefined) bits.push('<div class="mini">时空币：' + esc(p.chronum) + "</div>");
  bits.push('<div class="btns">');
  if (p.leave_action !== null && p.leave_action !== undefined) {
    bits.push('<button class="btn" data-act="' + p.leave_action + '">离开时空酒馆</button>');
  }
  if (p.cancel_action !== null && p.cancel_action !== undefined) {
    bits.push('<button class="btn ghost" data-act="' + p.cancel_action + '">取消选择</button>');
  }
  bits.push("</div></div>");
  ov.innerHTML = bits.join("");
}

function render() {
  if (!S) return;
  if (S.pending) SEL = {kind: null, index: null};
  const open = collectOpen();
  renderHud();
  renderTavern();
  renderShop();
  renderHand();
  renderBoard();
  renderButtons();
  renderTrinkets();
  renderDeity();
  renderOpponents();
  renderCombat();
  renderEvents();
  renderData();
  renderLegal();
  restoreOpen(open);
  renderOverlay();
  applySelection();
  updateHint();
}

/* ── 键盘菜单 ───────────────────────────────────────────────── */
function menuActions(payload) {
  const out = [];
  const i = payload.index;
  if (payload.kind === "shop") {
    const c = (S.shop || [])[i];
    if (c && c.buy !== null && c.buy !== undefined) out.push({label: "购买 " + cardName(c), action: c.buy, toast: "已购买：" + cardName(c)});
  } else if (payload.kind === "hand") {
    const c = (S.hand || [])[i] || {};
    for (const p of (c.play || [])) out.push({label: "打到 " + (p.pos + 1) + " 号位", action: p.action, toast: "已打出：" + cardName(c)});
    for (const m of (c.magnetize || [])) out.push({label: "磁力→随从 " + (m.board + 1), action: m.action, toast: "已磁力吸附：" + cardName(c)});
  } else if (payload.kind === "board") {
    const b = (S.board || [])[i] || {};
    if (b.sell !== null && b.sell !== undefined) out.push({label: "出售", action: b.sell, toast: "已出售：" + cardName(b)});
    if (b.activate !== null && b.activate !== undefined) out.push({label: "发动", action: b.activate, toast: "已发动：" + cardName(b)});
    for (const m of (b.move || [])) out.push({label: "换到 " + (m.to + 1) + " 号位", action: m.action, toast: "已换位：" + cardName(b)});
  }
  return out;
}
function showActionMenu(payload) {
  const acts = menuActions(payload);
  if (!acts.length) { toast("该卡当前没有可执行动作"); return; }
  MENU.acts = acts;
  const box = $("menubox");
  box.classList.remove("hidden");
  box.innerHTML = '<div class="menu"><h3>更多操作 · ' + esc(payload.name || "") + "</h3>" +
    acts.map((a, i) => '<button class="btn" data-mi="' + i + '">' + esc(a.label) + "</button>").join("") +
    '<button class="btn ghost" data-menu-close="1">关闭</button></div>';
}
function hideMenu() {
  const box = $("menubox");
  if (box) { box.classList.add("hidden"); box.innerHTML = ""; }
  MENU.acts = [];
}
function showMenuForSelection() {
  const c = currentCard();
  if (!c) return;
  showActionMenu({kind: SEL.kind, index: SEL.index, name: cardName(c)});
}
function primaryAction() {
  if (!S || S.pending || S.over) return;
  if (SEL.kind === "shop") {
    const c = (S.shop || [])[SEL.index];
    if (!c) return;
    if (c.buy === null || c.buy === undefined) { toast(c.buy_reason || "当前不能购买，未提交"); return; }
    act(c.buy, "已购买：" + cardName(c));
  } else if (SEL.kind === "hand") {
    const c = (S.hand || [])[SEL.index] || {};
    const p = (c.play || [])[0];
    if (p) { act(p.action, "已打出：" + cardName(c)); return; }
    const m = (c.magnetize || [])[0];
    if (m) { act(m.action, "已磁力吸附：" + cardName(c)); return; }
    toast(c.play_reason || "当前不能打出，未提交");
  } else if (SEL.kind === "board") {
    showMenuForSelection();
  }
}

/* ── 点击 / 键盘 / 菜单（事件委托） ─────────────────────────── */
function onCardClick(kind, index) {
  if (!S || S.over) { toast("对局结束，未提交"); return; }
  if (S.pending) { toast("先完成选择面板"); return; }
  if (kind === "board" && SEL.kind === "hand") {
    const h = (S.hand || [])[SEL.index] || {};
    const m = (h.magnetize || []).find((x) => x.board === index);
    if (m) { act(m.action, "已磁力吸附：" + cardName(h)); return; }
  }
  if (kind === "board" && SEL.kind === "board" && SEL.index !== index) {
    const b = (S.board || [])[SEL.index] || {};
    const mv = (b.move || []).find((x) => x.to === index);
    if (mv) { act(mv.action, "已换位：" + cardName(b)); return; }
  }
  if (SEL.kind === kind && SEL.index === index) {
    if (kind === "shop") primaryAction();
    else showMenuForSelection();
    return;
  }
  selectCard(kind, index);
}
function onSlotClick(slot) {
  if (!S || S.pending || S.over) return;
  if (slot.dataset.drop !== "board") return;
  const i = Number(slot.dataset.index);
  if (SEL.kind === "hand") {
    const c = (S.hand || [])[SEL.index] || {};
    const p = (c.play || []).find((x) => x.pos === i);
    if (p) { act(p.action, "已打出：" + cardName(c)); return; }
    const m = (c.magnetize || []).find((x) => x.board === i);
    if (m) { act(m.action, "已磁力吸附：" + cardName(c)); return; }
    toast("该位置不能打出，未提交");
  } else if (SEL.kind === "board") {
    const b = (S.board || [])[SEL.index] || {};
    const mv = (b.move || []).find((x) => x.to === i);
    if (mv) act(mv.action, "已换位：" + cardName(b));
    else toast("不能移到该位置，未提交");
  } else if (!(S.board || [])[i]) {
    toast("先点一张手牌");
  }
}
document.addEventListener("click", (ev) => {
  const t = ev.target;
  if (t.closest("[data-selclear]")) { clearSel(); return; }
  const mi = t.closest("[data-mi]");
  if (mi) {
    const a = MENU.acts[Number(mi.dataset.mi)];
    hideMenu();
    if (a) act(a.action, a.toast);
    return;
  }
  if (t.closest("[data-menu-close]")) { hideMenu(); return; }
  if (t.closest("[data-menu]")) { showMenuForSelection(); return; }
  if (t.closest("#undobtn")) { undo(); return; }
  if (t.closest("#endturnbtn")) {
    const b = t.closest("#endturnbtn");
    if (b.dataset.act) act(Number(b.dataset.act), "已结束回合");
    return;
  }
  if (t.closest("#newbtn")) { newGame(); return; }
  const ng = t.closest("[data-newgame]");
  if (ng) {
    const mode = ng.dataset.newgame;
    if (mode === "same") newGame(Number(S.seed));
    else newGame("random");
    return;
  }
  const actEl = t.closest("[data-act]");
  if (actEl) {
    if (actEl.disabled) return;
    if (Date.now() < DRAG.suppressClickUntil) return;
    act(Number(actEl.dataset.act), actEl.dataset.ok || undefined);
    return;
  }
  if (Date.now() < DRAG.suppressClickUntil) return;
  const card = t.closest(".card[data-kind]");
  if (card) {
    if (t.closest("details, summary, a, input, button, select, textarea")) return;
    onCardClick(card.dataset.kind, Number(card.dataset.index));
    return;
  }
  const slot = t.closest(".slot[data-drop]");
  if (slot) onSlotClick(slot);
});
document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (t.closest("input, textarea, select, [contenteditable]")) return;
  if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && ev.key.toLowerCase() === "z") {
    ev.preventDefault();
    undo();
    return;
  }
  if (ev.key === "Escape") {
    hideMenu();
    clearSel();
    return;
  }
  if (ev.key === "Enter" || ev.key === " ") {
    if (t.closest("button, a")) return;
    const focusAct = t.closest("[data-act]");
    if (focusAct) { ev.preventDefault(); focusAct.click(); return; }
    const focusCard = t.closest(".card[data-kind]");
    if (focusCard && !BUSY) {
      ev.preventDefault();
      onCardClick(focusCard.dataset.kind, Number(focusCard.dataset.index));
      return;
    }
    if (ev.key !== "Enter") return;
    if (!S || BUSY || S.pending) return;
    if (SEL.kind) { ev.preventDefault(); primaryAction(); }
    else if (!S.over) { ev.preventDefault(); endTurn(); }
    return;
  }
  if (/^[1-8]$/.test(ev.key) && S && !S.pending && !S.over && !BUSY) {
    if (!$("menubox").classList.contains("hidden")) return;
    const i = Number(ev.key) - 1;
    if ((S.shop || [])[i]) selectCard("shop", i);
    else toast("该商店槽为空");
  }
});

/* ── 拖拽（保留原有 DnD，事件委托） ─────────────────────────── */
function canDrag() { return !!(S && !S.over && !BUSY && !S.pending); }
function num(v) { return (v === null || v === undefined || Number.isNaN(Number(v))) ? null : Number(v); }
function mkPlan(ok, action, reason, label, okMsg) {
  return {ok: ok, action: action, reason: reason, label: label, toast: okMsg};
}
function planDrop(src, dst) {
  if (!S) return mkPlan(false, null, "状态尚未加载");
  if (S.over) return mkPlan(false, null, "对局已结束");
  if (S.pending) return mkPlan(false, null, "先完成选择面板");
  if (BUSY) return mkPlan(false, null, "请求处理中，请稍候");
  if (!src || !dst) return mkPlan(false, null, "没有识别到拖拽源/目标");
  const sk = src.kind, si = num(src.index), dk = dst.kind, di = num(dst.index);
  if (sk === "shop") {
    if (dk !== "hand" && dk !== "board" && dk !== "buy") {
      return mkPlan(false, null, "商店卡只能拖到购买区或战场");
    }
    const c = (S.shop || [])[si];
    if (!c) return mkPlan(false, null, "该酒馆槽位为空");
    const a = num(c.buy);
    if (a === null) return mkPlan(false, null, c.buy_reason || "该槽当前不能购买");
    return mkPlan(true, a, "", "购买 " + cardName(c), "已购买：" + cardName(c) + "，已进入手牌");
  }
  if (sk === "hand") {
    if (dk !== "board") return mkPlan(false, null, "手牌只能拖到战场槽位");
    const c = (S.hand || [])[si];
    if (!c) return mkPlan(false, null, "该手牌槽位为空");
    const npos = (S.action_space && S.action_space.N_POS) || 8;
    if (di === null || di < 0 || di >= npos) return mkPlan(false, null, "战场位置越界");
    const board = S.board || [];
    if (di < board.length) {
      const mag = (c.magnetize || []).find((m) => num(m.board) === di);
      if (mag) return mkPlan(true, mag.action, "", "磁力 " + cardName(c), "已磁力吸附：" + cardName(c));
      return mkPlan(false, null, c.magnetize_reason || "不能磁力吸附到该随从");
    }
    const play = (c.play || []).find((p) => num(p.pos) === di);
    if (play) return mkPlan(true, play.action, "", "打出 " + cardName(c), "已打出：" + cardName(c));
    return mkPlan(false, null, c.play_reason || "现在不能打出到该位置");
  }
  if (sk === "board") {
    const b = (S.board || [])[si];
    if (!b) return mkPlan(false, null, "该战场槽位为空");
    if (dk === "board") {
      if (di === si) return mkPlan(false, null, "随从已在原位");
      const mv = (b.move || []).find((m) => num(m.to) === di);
      if (mv) return mkPlan(true, mv.action, "", "移动 " + cardName(b), "已换位：" + cardName(b));
      return mkPlan(false, null, "该位置不能移动");
    }
    if (dk === "sell") {
      const a = num(b.sell);
      if (a === null) return mkPlan(false, null, b.sell_reason || "当前不能出售");
      return mkPlan(true, a, "", "出售 " + cardName(b), "已出售：" + cardName(b));
    }
    if (dk === "activate") {
      const a = num(b.activate);
      if (a === null) return mkPlan(false, null, b.activate_reason || "该随从没有可发动技能");
      return mkPlan(true, a, "", "发动 " + cardName(b), "已发动：" + cardName(b));
    }
    return mkPlan(false, null, "战场随从只能拖到战场、出售区或发动区");
  }
  return mkPlan(false, null, "未知拖拽源");
}
function clearTarget() {
  if (DRAG.targetEl) {
    DRAG.targetEl.classList.remove("dragover", "dragover-bad");
    DRAG.targetEl = null;
  }
}
function setTarget(z) {
  clearTarget();
  if (!z) return;
  const plan = planDrop(DRAG.payload || {}, z);
  z.el.classList.add(plan.ok ? "dragover" : "dragover-bad");
  DRAG.targetEl = z.el;
}
function dropTargetAt(x, y) {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  const z = el.closest("[data-drop]");
  if (!z) return null;
  return {kind: z.dataset.drop, index: z.dataset.index === "" ? undefined : Number(z.dataset.index), el: z};
}
function beginDrag(payload, el, ev) {
  DRAG.payload = payload;
  DRAG.sourceEl = el;
  el.classList.add("dragging");
  el.setAttribute("aria-grabbed", "true");
  document.body.classList.add("dragging");
  if (ev && ev.dataTransfer) {
    ev.dataTransfer.effectAllowed = "move";
    try { ev.dataTransfer.setData("text/plain", JSON.stringify(payload)); } catch (e) { /* 兼容旧浏览器 */ }
  }
}
function endDrag() {
  if (DRAG.sourceEl && DRAG.sourceEl.isConnected) {
    DRAG.sourceEl.classList.remove("dragging");
    DRAG.sourceEl.setAttribute("aria-grabbed", "false");
  }
  if (DRAG.ghost) { DRAG.ghost.remove(); DRAG.ghost = null; }
  clearTarget();
  DRAG.payload = null;
  DRAG.sourceEl = null;
  document.body.classList.remove("dragging");
}
function rollbackDrag(reason, sourceEl) {
  toast((reason || "操作不合法") + "，已回滚", false);
  if (sourceEl) {
    sourceEl.classList.remove("dragging");
    sourceEl.classList.add("shake");
    setTimeout(() => sourceEl.classList.remove("shake"), 450);
  }
  endDrag();
}
function dispatchDrop(dst, payload, srcEl) {
  const plan = planDrop(payload, dst);
  if (!plan.ok) { rollbackDrag(plan.reason || plan.label, srcEl); return; }
  DRAG.suppressClickUntil = Date.now() + 300;
  endDrag();
  act(plan.action, plan.toast || plan.label);
}
function makeGhost(el, x, y) {
  if (DRAG.ghost) DRAG.ghost.remove();
  const g = el.cloneNode(true);
  g.classList.add("dragghost");
  g.classList.remove("dragging", "shake");
  g.querySelectorAll("[id]").forEach((n) => n.removeAttribute("id"));
  g.style.left = x + "px";
  g.style.top = y + "px";
  document.body.appendChild(g);
  DRAG.ghost = g;
}
function moveGhost(x, y) {
  if (!DRAG.ghost) return;
  DRAG.ghost.style.left = x + "px";
  DRAG.ghost.style.top = y + "px";
}
function startPointerDrag(ev, el, payload) {
  if (ev.pointerType === "mouse") return;
  if (!canDrag()) return;
  if (ev.target.closest("button, summary, a, input, select, textarea")) return;
  const sx = ev.clientX, sy = ev.clientY;
  const timer = setTimeout(() => {
    if (!canDrag() || !DRAG.pointer) return;
    DRAG.pointer.active = true;
    beginDrag(payload, el, null);
    makeGhost(el, sx, sy);
    document.body.classList.add("pointer-dragging");
  }, 150);
  DRAG.timer = timer;
  DRAG.pointer = {el: el, payload: payload, active: false};
  function cleanup() {
    clearTimeout(timer);
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", finish);
    document.removeEventListener("pointercancel", cancel);
    DRAG.pointer = null;
    document.body.classList.remove("pointer-dragging");
  }
  function move(e) {
    if (!DRAG.pointer) return;
    if (!DRAG.pointer.active) {
      if (Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) > 16) cleanup();
      return;
    }
    e.preventDefault();
    moveGhost(e.clientX, e.clientY);
    setTarget(dropTargetAt(e.clientX, e.clientY));
  }
  function finish(e) {
    if (DRAG.pointer && DRAG.pointer.active) {
      e.preventDefault();
      DRAG.suppressClickUntil = Date.now() + 300;
      const z = dropTargetAt(e.clientX, e.clientY);
      const pl = DRAG.pointer.payload, src = DRAG.pointer.el;
      cleanup();
      if (z) dispatchDrop(z, pl, src);
      else rollbackDrag("拖到了无效区域", src);
      return;
    }
    cleanup();
  }
  function cancel() {
    const p = DRAG.pointer;
    cleanup();
    if (p && p.active) rollbackDrag("拖拽取消", p.el);
  }
  document.addEventListener("pointermove", move, {passive: false});
  document.addEventListener("pointerup", finish);
  document.addEventListener("pointercancel", cancel);
}
function payloadOf(el) {
  return {kind: el.dataset.dragKind, index: Number(el.dataset.dragIndex), name: el.dataset.dragName || ""};
}
document.addEventListener("dragstart", (ev) => {
  const el = ev.target.closest(".card[data-drag-kind]");
  if (!el) return;
  if (!canDrag()) { ev.preventDefault(); return; }
  beginDrag(payloadOf(el), el, ev);
});
document.addEventListener("dragend", () => endDrag());
document.addEventListener("pointerdown", (ev) => {
  const el = ev.target.closest(".card[data-drag-kind]");
  if (el) startPointerDrag(ev, el, payloadOf(el));
});
document.addEventListener("dragover", (ev) => {
  if (!DRAG.payload) return;
  ev.preventDefault();
  const z = dropTargetAt(ev.clientX, ev.clientY);
  setTarget(z);
  if (ev.dataTransfer) {
    const plan = z ? planDrop(DRAG.payload, z) : {ok: false};
    ev.dataTransfer.dropEffect = plan.ok ? "move" : "none";
  }
});
document.addEventListener("drop", (ev) => {
  if (!DRAG.payload) return;
  ev.preventDefault();
  const z = dropTargetAt(ev.clientX, ev.clientY);
  const payload = DRAG.payload, src = DRAG.sourceEl;
  if (!z) { rollbackDrag("拖到了无效区域", src); return; }
  dispatchDrop(z, payload, src);
});

$("devpanel").addEventListener("toggle", () => {
  if ($("devpanel").open) loadDevText();
});

if (S) { setConn(true); render(); } else { refresh(); }
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
            elif path == "/undo":
                with self.server.lock:
                    self._json(200, self.server.session.undo())
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
