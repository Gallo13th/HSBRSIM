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
from urllib.parse import urlparse

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


class IllegalAction(Exception):
    """非法/不可执行的 action（HTTP 层转 400）。"""


# ══════════════════════════════════════════════════════════════════════
# 视图裁剪（只保留 UI 需要的字段，避免把整份 view 全发给前端）
# ══════════════════════════════════════════════════════════════════════

#: 对手只展示公开信息（``seen_board`` 等）；**不**展示 debug view 里对手的实时棋盘。
def _card_brief(it: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """卡牌/随从的紧凑展示字段。"""
    it = it or {}
    return {
        "name": it.get("name") or "",
        "name_zh": it.get("name_zh") or it.get("name") or "",
        "card_id": it.get("id") or "",
        "type": it.get("type") or it.get("kind") or "minion",
        "tier": int(it.get("tier") or 0),
        "atk": it.get("atk"),
        "hp": it.get("hp"),
        "races": list(it.get("races") or []),
        "text": it.get("text_zh") or it.get("text") or "",
        "golden": bool(it.get("golden")),
        "keywords": list(it.get("keywords") or []),
    }


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
            })
    else:
        for i, opt in enumerate(options):
            item = _card_brief(opt)
            item["index"] = i
            item["action"] = choose_action(i)
            if kind == "hero":
                item["armor"] = opt.get("armor")
                item["hp"] = opt.get("hp")
                power = opt.get("hero_power")
                if power:
                    item["power"] = {
                        "name_zh": power.get("name_zh") or power.get("name") or "",
                        "text": power.get("text_zh") or power.get("text") or "",
                    }
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
                 engine: Any = None) -> None:
        self.E = engine or load_engine()
        self.seat = int(seat)
        if not 0 <= self.seat < 8:
            raise ValueError(f"seat 必须在 0..7，得到 {seat}")
        self.out_dir = os.path.abspath(out_dir)
        os.makedirs(self.out_dir, exist_ok=True)
        self._stamp_seq = 0
        self.seed = int(seed)
        self.new_game(self.seed)

    # ── 开局 / 落盘 ──────────────────────────────────────────────────
    def new_game(self, seed: Optional[int] = None) -> None:
        """开新局：新 replay 文件 + 清空计数；bot 先选完英雄。"""
        if seed is None:
            seed = self.seed
        self.seed = int(seed)
        self.game = self.E.Game(seed=self.seed)
        self.decisions = 0
        self.steps = 0
        self.over = False
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

        # 酒馆
        shop = []
        for i, it in enumerate(me.get("shop") or []):
            e = _card_brief(it)
            e.update({
                "slot": i,
                "price": it.get("price"),
                "costs_health": bool(it.get("costs_health")),
                "frozen": bool(it.get("frozen")),
                "kept": bool(it.get("kept")),
                "owned": it.get("owned"),
                "triple_need": it.get("triple_need"),
                "buy": (A_BUY + i) if (i < N_SHOP and legal_a(A_BUY + i)) else None,
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
                "held": bool(it.get("held")),
                "temporary": bool(it.get("temporary")),
                "play": plays,
                "magnetize": mags,
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
            e.update({
                "index": i,
                "eid": it.get("eid"),
                "sell": (A_SELL + i) if legal_a(A_SELL + i) else None,
                "activate": (A_ACTIVATE + i) if legal_a(A_ACTIVATE + i) else None,
                "move": moves,
                "attached": [
                    (a.get("name_zh") or a.get("name") or "") if isinstance(a, dict) else str(a)
                    for a in (it.get("attached") or [])
                ],
            })
            board.append(e)

        powers = [_power_brief(p) for p in (me.get("hero_powers") or [])]

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
            "refresh_price": me.get("refresh_price"),
            "minion_price": me.get("minion_price"),
            "free_refreshes": me.get("free_refreshes"),
            "frozen": bool(me.get("frozen")),
            "ended_turn": bool(me.get("ended_turn")),
            "win_streak": me.get("win_streak"),
            "last_damage": me.get("last_damage"),
            "placement": me.get("placement"),
            "hand_limit": me.get("hand_limit"),
            "turn": v.get("turn"),
            "phase": phase,
            "alive_players": v.get("alive"),
            "lobby_races": v.get("lobby_races") or [],
        }

        buttons = [
            {"key": "end", "label": "结束回合", "action": A_END,
             "enabled": legal_a(A_END), "hint": ""},
            {"key": "refresh", "label": "刷新酒馆", "action": A_REFRESH,
             "enabled": legal_a(A_REFRESH), "hint": f"{me.get('refresh_price')} 金"},
            {"key": "freeze",
             "label": "解除冻结" if me.get("frozen") else "冻结酒馆",
             "action": A_FREEZE, "enabled": legal_a(A_FREEZE), "hint": ""},
            {"key": "upgrade", "label": "升级酒馆", "action": A_UPGRADE,
             "enabled": legal_a(A_UPGRADE),
             "hint": f"{me.get('upgrade_price')} 金"},
        ]
        if legal_a(A_DARK_GIFT):
            buttons.append({"key": "dark_gift", "label": "黑暗赠礼", "action": A_DARK_GIFT,
                            "enabled": True, "hint": "S14"})
        for p in powers:
            a = p.get("action")
            hint = []
            if p.get("price"):
                hint.append(f"{p['price']} 金")
            if p.get("passive"):
                hint.append("被动")
            buttons.append({
                "key": f"power{p.get('slot')}",
                "label": f"技能：{p.get('name_zh') or ''}",
                "action": int(a) if a is not None else None,
                "enabled": bool(a is not None and legal_a(int(a)) and p.get("usable", True)),
                "hint": " ".join(hint),
            })

        # 对手：只给公开信息（英雄/血量/护甲/等级/上次见到的战团）
        opponents = []
        for o in v.get("opponents") or []:
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
                "seen_turn": o.get("seen_turn"),
                "seen_board": [_card_brief(x) for x in (o.get("seen_board") or [])],
                "trinkets": [x.get("name_zh") or x.get("name") or ""
                             for x in (o.get("trinkets") or [])],
            })

        combats = []
        for c in (v.get("combats") or [])[-3:]:
            combats.append({
                "turn": c.get("turn"),
                "a": c.get("a"),
                "b": c.get("b"),
                "winner": c.get("winner"),
                "damage": c.get("damage"),
                "truncated": bool(c.get("truncated")),
            })

        events = me.get("turn_events") or []
        if not isinstance(events, list):
            events = [events]
        stats_src = me.get("stats") or {}
        stats = {k: stats_src.get(k) for k in (
            "combats_won", "combats_lost", "cards_bought", "minions_sold",
            "refreshes", "gold_spent_total", "triples_held") if k in stats_src}

        return {
            "ok": True,
            "seat": self.seat,
            "seed": self.seed,
            "turn": v.get("turn"),
            "phase": phase,
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
        mask = self._mask()
        if not mask[a]:
            raise IllegalAction(f"动作 {a}（{action_name(a)}）当前非法")

        features, cards = self._obs()
        snap = json.loads(g.view(self.seat))
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
      <div class="ptitle"><span>操作</span><span class="mini">所有按钮 = 引擎动作下标</span></div>
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
      <div class="ptitle"><span>最近战斗</span></div>
      <div id="combats" class="mini"></div>
    </div>
    <div class="panel">
      <div class="ptitle"><span>本回合事件</span></div>
      <div id="events" class="mini"></div>
    </div>
    <details>
      <summary>合法动作掩码（点击展开）</summary>
      <div id="legal"></div>
    </details>
  </section>
</main>
<div id="overlay" class="hidden"></div>
<div id="toast"></div>
<script>
"use strict";
let S = /*STATE_JSON*/null;
let toastTimer = 0;

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
  if (!S) { return; }
  const data = await api("/act", {action: action});
  if (data) { S = data; render(); } else { refresh(); }
}
async function newGame() {
  const raw = $("seed").value.trim();
  const body = raw === "" ? {} : {seed: Number(raw)};
  const data = await api("/new", body);
  if (data) { S = data; render(); toast("新开一局：seed " + data.seed); }
}

/* ── 渲染 ─────────────────────────────────────────────────────── */
function heroName(h) { return h ? (h.name_zh || h.name) : "选择英雄"; }
function cardHTML(c, extra) {
  const meta = (c.type === "spell" || c.type === "tavern_spell")
    ? '<span class="spell">法术</span>'
    : (c.type === "minion"
      ? '<span class="stats"><span class="a">' + (c.atk ?? "") + '/' + (c.hp ?? "") + '</span></span>'
      : '<span class="tier">' + (c.type || "") + '</span>');
  return '<div class="cname">' + esc(c.name_zh || c.name) + (c.golden ? ' <span style="color:#f2c14e">★</span>' : '') + '</div>' +
    '<div class="cmeta"><span class="tier">T' + (c.tier ?? 0) + '</span>' + meta + '</div>' +
    '<div class="ctext">' + esc(c.text || "") + '</div>' + (extra || "");
}
function shopCard(c) {
  const el = document.createElement("div");
  el.className = "card" + (c.buy !== null ? " clickable legal" : "");
  el.innerHTML = cardHTML(c, '<div class="badge">' + (c.price ?? "?") + ' 金' + (c.costs_health ? ' (血)' : '') + '</div>' +
    (c.frozen ? '<div class="frozen">❄</div>' : '') +
    ((c.owned ? '<div class="mini">已持有 ' + c.owned + (c.triple_need ? '/' + c.triple_need : '') + '</div>' : '')));
  if (c.buy !== null) el.onclick = () => act(c.buy);
  el.title = (c.card_id || "") + (c.buy !== null ? ("  Buy(" + c.slot + ") = action " + c.buy) : " 不可购买");
  return el;
}
function handCard(c) {
  const el = document.createElement("div");
  el.className = "card" + (c.play.length || c.magnetize.length ? " legal" : "");
  const chips = [];
  if (c.play.length === 1) {
    chips.push('<span class="chip" data-a="' + c.play[0].action + '">打出 · action ' + c.play[0].action + '</span>');
  } else {
    for (const p of c.play) chips.push('<span class="chip" data-a="' + p.action + '">位置 ' + p.pos + ' · ' + p.action + '</span>');
  }
  for (const m of c.magnetize) chips.push('<span class="chip" data-a="' + m.action + '">磁力→随从' + m.board + ' · ' + m.action + '</span>');
  el.innerHTML = cardHTML(c) + '<div class="chips">' + chips.join("") + '</div>';
  el.querySelectorAll(".chip").forEach((ch) => { ch.onclick = (e) => { e.stopPropagation(); act(Number(ch.dataset.a)); }; });
  el.title = (c.card_id || "") + "  手牌 #" + c.index;
  return el;
}
function boardCard(c) {
  const el = document.createElement("div");
  el.className = "card" + (c.golden ? " golden" : "");
  const chips = [];
  if (c.sell !== null) chips.push('<span class="chip" data-a="' + c.sell + '">出售 · ' + c.sell + '</span>');
  if (c.activate !== null) chips.push('<span class="chip" data-a="' + c.activate + '">发动 · ' + c.activate + '</span>');
  for (const m of c.move) chips.push('<span class="chip" data-a="' + m.action + '">移到 ' + m.to + '</span>');
  el.innerHTML = cardHTML(c, (c.attached && c.attached.length ? '<div class="mini">附着：' + esc(c.attached.join("、")) + '</div>' : '')) +
    '<div class="chips">' + chips.join("") + '</div>';
  el.querySelectorAll(".chip").forEach((ch) => { ch.onclick = (e) => { e.stopPropagation(); act(Number(ch.dataset.a)); }; });
  el.title = (c.card_id || "") + "  随从位置 #" + c.index;
  return el;
}
function render() {
  if (!S) return;
  const h = S.hud;
  $("hud").innerHTML =
    '<span class="hero">' + esc(heroName(h.hero)) + '</span>' +
    '<span class="pill">血量 <span class="hp">' + (h.health ?? "?") + '</span>' + (h.armor ? ' +' + h.armor : '') + '</span>' +
    '<span class="pill">金币 <span class="gold">' + (h.gold ?? "?") + '</span>/' + (h.max_gold ?? "?") + '</span>' +
    '<span class="pill">等级 T' + (h.tier ?? "?") + '</span>' +
    '<span class="pill">回合 ' + (S.turn ?? "?") + '</span>' +
    '<span class="pill">存活 ' + (S.alive ?? "?") + '/8</span>' +
    '<span class="pill">名次 ' + (S.over ? ('<b class="good">' + S.placement + '</b>') : (h.placement || "-")) + '</span>' +
    (h.hero_power ? '<span class="pill">技能：' + esc(h.hero_power.name_zh || h.hero_power.name) + '</span>' : '') +
    '<span class="pill dim">seed ' + S.seed + ' · 决策 ' + S.decisions + ' · ' + esc(S.phase) + '</span>' +
    (S.over ? '<span class="pill bad">对局结束</span>' : '');

  $("tavernhint").textContent = "刷新 " + h.refresh_price + " 金 · 升级 " + h.upgrade_price + " 金 · 冻结 " + (h.frozen ? "开" : "关");
  $("shop").innerHTML = "";
  for (const c of S.shop) $("shop").appendChild(shopCard(c));
  if (!S.shop.length) $("shop").innerHTML = '<span class="dim">酒馆为空（先选英雄 / 点刷新）</span>';

  $("handhint").textContent = S.hand.length + " / " + (h.hand_limit ?? 10);
  $("hand").innerHTML = "";
  for (const c of S.hand) $("hand").appendChild(handCard(c));
  if (!S.hand.length) $("hand").innerHTML = '<span class="dim">手牌为空</span>';

  $("boardhint").textContent = S.board.length + " 个随从";
  $("board").innerHTML = "";
  for (const c of S.board) $("board").appendChild(boardCard(c));
  if (!S.board.length) $("board").innerHTML = '<span class="dim">场上没有随从</span>';

  $("buttons").innerHTML = "";
  for (const b of S.buttons) {
    const el = document.createElement("button");
    el.textContent = b.label + (b.hint ? " · " + b.hint : "") + (b.action !== null ? " [" + b.action + "]" : "");
    el.disabled = !b.enabled || S.over;
    el.onclick = () => act(b.action);
    el.title = b.key + " = action " + b.action;
    if (b.key === "end") el.classList.add("end");
    $("buttons").appendChild(el);
  }

  $("opphint").textContent = "存活 " + (S.alive ?? "?") + "/8";
  $("opp").innerHTML = S.opponents.map((o) =>
    '<div class="opprow' + (o.alive ? '' : ' dead') + (o.is_next ? ' ' : '') + '">' +
      '<span>' + (o.is_next ? '▶ ' : '') + esc(o.hero ? (o.hero.name_zh || o.hero.name) : "未知英雄") + '</span>' +
      '<span>' + (o.alive ? ('<b class="hp">' + o.health + '</b>' + (o.armor ? '+' + o.armor : '') + ' · T' + o.tier) : '淘汰 #' + o.placement) + '</span>' +
    '</div>' +
    (o.seen_board && o.seen_board.length
      ? '<div class="mini">上次见过：' + esc(o.seen_board.map((m) => (m.name_zh || m.name) + ' ' + (m.atk ?? '') + '/' + (m.hp ?? '')).join('、')) + '</div>'
      : '')).join("");

  $("combats").innerHTML = S.combats.length
    ? S.combats.map((c) => {
        const bName = c.b === null || c.b === undefined ? '幽灵' : ('座位 ' + c.b);
        const win = c.winner === 0 ? ('座位 ' + c.a + ' 胜')
          : (c.winner === 1 ? (bName + ' 胜') : '平');
        return 'T' + c.turn + '：座位 ' + c.a + ' vs ' + bName + ' → ' + win +
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
  return {hero: "选择英雄", discover: "发现一张牌", trinket: "选择饰品", choose_one: "抉择",
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
  parts.push('<div class="pbox"><h2>' + esc(pendingTitle(p.kind)) + '</h2>');
  if (p.source && (p.source.name_zh || p.source.name)) {
    parts.push('<div class="sub">来源：' + esc(p.source.name_zh || p.source.name) + '</div>');
  }
  if (p.kind === "target") {
    parts.push('<div class="sub">点击一个目标（action = 30 + 序号）</div><div class="popts">');
    for (const t of p.targets) {
      parts.push('<div class="card clickable" data-a="' + t.action + '"><div class="cname">' + esc(t.name) + '</div>' +
        '<div class="mini">eid ' + t.eid + '</div><div class="chips"><span class="chip">目标 ' + t.index + ' · ' + t.action + '</span></div></div>');
    }
    parts.push('</div>');
  } else if (p.kind === "hero") {
    parts.push('<div class="sub">选择本局英雄</div><div class="popts">');
    for (const o of p.options) {
      parts.push('<div class="card clickable" data-a="' + o.action + '">' +
        '<div class="cname">' + esc(o.name_zh || o.name) + '</div>' +
        '<div class="cmeta"><span>护甲 ' + (o.armor ?? 0) + '</span><span>生命 ' + (o.hp ?? 30) + '</span></div>' +
        '<div class="ctext">技能：' + esc(o.power ? (o.power.name_zh || o.power.name) : "") +
        '<br>' + esc(o.power ? (o.power.text || "") : "") + '</div>' +
        '<div class="chips"><span class="chip">选择 · ' + o.action + '</span></div></div>');
    }
    parts.push('</div>');
  } else {
    if (p.kind === "trinket") {
      parts.push('<div class="sub">' + (p.free ? "免费饰品" : "购买一个饰品") + (p.replace ? '（替换现有饰品）' : '') + '</div>');
    }
    parts.push('<div class="popts">');
    for (const o of p.options) {
      const showGold = (p.kind === "trinket" || p.kind === "timewarp") &&
        o.cost !== undefined && o.cost !== null;
      parts.push('<div class="card clickable" data-a="' + o.action + '">' + cardHTML(o) +
        (showGold ? '<div class="badge">' + o.cost + ' 金</div>' : '') +
        (o.chronum_cost !== undefined && o.chronum_cost !== null ? '<div class="badge">' + o.chronum_cost + ' 时空币</div>' : '') +
        (o.goal ? '<div class="mini">目标：' + esc(o.goal) + '</div>' : '') +
        (o.reward ? '<div class="mini">奖励：' + esc(o.reward.name_zh || o.reward.name) + '</div>' : '') +
        '<div class="chips"><span class="chip">选择 · ' + o.action + '</span></div></div>');
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
    """内嵌页面；给定 ``state`` 时把状态注入 JS，页面**同步**渲染（截图/复盘用）。"""
    if state is None:
        return INDEX_HTML
    payload = json.dumps(state, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return INDEX_HTML.replace("/*STATE_JSON*/null", payload)


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
            self._json(400, {"ok": False, "error": str(exc)})
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


def run_selftest(seed: int, seat: int, out_dir: str, max_decisions: int = 3000) -> Dict[str, Any]:
    """脚本化人类打完整一局，打印状态文本并校验 replay/npz。"""
    t0 = time.time()
    sess = GameSession(seed=seed, seat=seat, out_dir=out_dir)
    n = 0
    while not sess.over and n < max_decisions:
        st = sess.state()
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
    print("酒馆：%s" % " | ".join(
        "%s(%s金,T%d)" % (c["name_zh"], c["price"], c["tier"]) for c in st["shop"]) or "空")
    print("手牌：%s" % (" | ".join(c["name_zh"] for c in st["hand"]) or "空"))
    print("战场：%s" % (" | ".join(
        "%s %s/%s%s" % (c["name_zh"], c["atk"], c["hp"], "★" if c["golden"] else "")
        for c in st["board"]) or "空"))
    print("合法动作数=%d（首 12：%s）" % (len(st["legal"]), st["legal"][:12]))
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
    ap.add_argument("--to-npz", default="", metavar="DIR", help="把 DIR 下 *.jsonl.gz 转成 BC npz 后退出")
    ap.add_argument("--npz-out", default="", help="--to-npz 的输出 npz 路径")
    ap.add_argument("--skip-hero-select", action="store_true",
                    help="--to-npz 时跳过英雄选择阶段决策")
    ap.add_argument("--quiet", action="store_true", help="不打印启动横幅")
    args = ap.parse_args(argv)

    if args.to_npz:
        out = args.npz_out or os.path.join(os.path.dirname(os.path.abspath(args.to_npz)) or ".",
                                          "human_play_bc.npz")
        info = convert_replays(args.to_npz, out, skip_hero_select=bool(args.skip_hero_select))
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    if args.selftest:
        run_selftest(int(args.seed), int(args.seat), os.path.abspath(args.out))
        return 0

    E = load_engine()
    sess = GameSession(seed=int(args.seed), seat=int(args.seat),
                       out_dir=os.path.abspath(args.out), engine=E)
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
