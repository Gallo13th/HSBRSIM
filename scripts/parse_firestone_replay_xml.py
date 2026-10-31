#!/usr/bin/env python3
"""把 Firestone Web 回放站抓到的 BG 回放解析成人类战团库 + 动作样本。

数据来源（抓取脚本见 ``docs/FIRESTONE_REPLAY_INGEST.md``）：

* ``<xmlz>/<reviewId>.xml.zip``：HSReplay XML（Firestone 原始回放，~11 MB/局）；
* ``<pms>/<reviewId>.json``：Firestone post-match stats（每场战斗双方战团、
  英雄血量、酒馆等级；~190 KB/局）；
* ``index.json``：``bgs-perfect-games`` feed 的元数据（reviewId / replayKey /
  MMR / 英雄 / 回合数 / 部落池）；
* ``rust/crates/hsbg-engine/data/cards.json``：卡表（card_id -> 引擎 cid / kind）。

为什么 XML + PMS 两者都用：

* XML 是唯一能拿到 **逐动作**（buy / sell / reroll / upgrade / hero_power /
  triple / play）和 **最终名次**（``PLAYER_LEADERBOARD_PLACE`` = tag 1373）
  的来源；
* 对手战团在 XML 里是战斗开始时逐步 ``ShowEntity`` 揭示的，首刀时刻不一定
  完整；post-match stats 的 ``battleResultHistory[].battleInfo`` 直接给出双方
  完整战团，因此**战团以 PMS 为准**，XML 自身战团作为 cross-check / 回退。

输出：

* ``library_firestone_recent.jsonl``：每行一个 (game, turn, perspective) 战团帧，
  schema 对齐 ``library_real_quasi_full.jsonl``，``human_board_pool`` 可直接加载；
* ``library_firestone_recent_stats.json``：局数/回合覆盖/字段缺失/动作覆盖/
  XML-PMS 一致性；
* ``firestone_recent_actions.jsonl``：每行一个 XML 动作样本（对齐
  ``bc_samples.jsonl.gz`` 的关键字段）。

只依赖 Python 标准库；解析只走 CPU。
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
import traceback
import zipfile
import xml.etree.ElementTree as ET
from multiprocessing import Pool

# ════════════════════════════════════════════════════════════════════════
# Hearthstone tag / keyword 常量
# ════════════════════════════════════════════════════════════════════════
TAG_ZONE = "49"
TAG_CONTROLLER = "50"
TAG_ENTITY_ID = "53"
TAG_POSITION = "263"
TAG_RESOURCES = "26"
TAG_TURN = "20"
TAG_HERO_ENTITY = "27"
TAG_HEALTH = "45"
TAG_DAMAGE = "44"
TAG_ARMOR = "292"
TAG_TECH_LEVEL = "1377"
TAG_PREMIUM = "12"
TAG_LEADERBOARD_PLACE = "1373"
TAG_DIVINE_SHIELD = "194"

ZONE_PLAY = "1"
ZONE_HAND = "3"
ZONE_SETASIDE = "6"

BLOCK_ATTACK = "1"
BLOCK_PLAY = "7"
BLOCK_MOVE_MINION = "12"

#: 数字 tag -> 引擎关键词名（与 ``hsbg.az.train.human_obs_full.TAG_TO_KW`` 一致）
TAG_TO_KW = {
    190: "TAUNT", 3614: "TAUNT",
    194: "DIVINE_SHIELD", 3617: "DIVINE_SHIELD",
    189: "WINDFURY", 3622: "WINDFURY",
    1085: "REBORN", 3621: "REBORN",
    2853: "VENOMOUS",
    363: "POISONOUS", 3620: "POISONOUS",
    849: "MAGNETIC",
    191: "STEALTH", 3619: "STEALTH",
}
KW_BITS = {
    "TAUNT": 1 << 0, "DIVINE_SHIELD": 1 << 1, "WINDFURY": 1 << 2,
    "REBORN": 1 << 3, "VENOMOUS": 1 << 4, "POISONOUS": 1 << 5,
    "STEALTH": 1 << 6, "MAGNETIC": 1 << 7, "MEGA_WINDFURY": 1 << 8,
    "CLEAVE": 1 << 9, "IMMUNE": 1 << 10, "IMMUNE_ATTACKING": 1 << 11,
}
CARD_KINDS = ("minion", "spell", "tavern_spell")
HAND_KINDS = ("minion", "spell", "tavern_spell")

ENT_TAGS = ("Player", "GameEntity", "FullEntity", "ShowEntity", "ChangeEntity")
SKIN_RE = re.compile(r"_SKIN_[A-Z0-9]+$")
GOLD_RE = re.compile(r"_G(\d+)?$")

#: 动作 -> 标准动作空间（hsbg/env/action_space_std.py），与
#: ``scripts/firestone_bc_parse.py`` 的 ACTION_MAP 保持一致。
ACTION_MAP = {
    "end_turn": ("0", True),
    "reroll": ("1", True),
    "freeze": ("2", True),
    "upgrade": ("3", True),
    "hero_power": ("4+slot", True),
    "dark_gift": ("6", True),
    "buy_minion": ("8+slot", True),
    "buy_spell": ("15", True),
    "sell": ("16+slot", True),
    "play_minion": ("46+hand*8+pos", True),
    "play_spell": ("46+hand*8+pos", True),
    "reposition": ("196+from*7+to", True),
    "triple": ("30+option", False),
}


# ════════════════════════════════════════════════════════════════════════
# 卡表
# ════════════════════════════════════════════════════════════════════════
class CardDb:
    def __init__(self, cards_path: str):
        raw = json.load(open(cards_path, "r", encoding="utf-8"))
        cards = raw.get("cards") if isinstance(raw, dict) else raw
        self.cards = cards
        self.by_id = {}
        self.alias = {}
        for i, c in enumerate(cards):
            cid = c.get("id")
            if not isinstance(cid, str):
                continue
            kw = 0
            for name in c.get("keywords") or ():
                kw |= KW_BITS.get(str(name).strip().upper(), 0)
            self.by_id[cid] = {
                "cid": i,
                "kind": str(c.get("kind") or ""),
                "tier": int(c.get("tier") or 0),
                "atk": int(c.get("atk") or 0),
                "hp": int(c.get("hp") or 0),
                "kw": kw,
                "normal": c.get("normal") or "",
                "golden": c.get("golden") or "",
            }
            self.alias[cid] = i
            for alias in (c.get("normal"), c.get("golden")):
                if alias:
                    self.alias.setdefault(alias, i)

    def cid(self, card_id):
        if not card_id:
            return None
        if card_id in self.alias:
            return self.alias[card_id]
        base = card_id
        m = GOLD_RE.search(base)
        if m:
            base = base[:m.start()]
        if base in self.alias:
            return self.alias[base]
        base = SKIN_RE.sub("", base)
        return self.alias.get(base)

    def info(self, card_id):
        cid = self.cid(card_id)
        if cid is None:
            return None
        return self.by_id.get(self.cards[cid].get("id"))

    def kind(self, card_id):
        info = self.info(card_id)
        return info["kind"] if info else None

    def printed_kw(self, card_id):
        info = self.info(card_id)
        return int(info["kw"]) if info else 0


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ════════════════════════════════════════════════════════════════════════
# XML 解析
# ════════════════════════════════════════════════════════════════════════
class XmlReplay:
    def __init__(self, cdb: CardDb):
        self.cdb = cdb
        self.ent = {}              # eid -> {"card","tags","last"}
        self.players = {}          # player eid -> controller (str)
        self.main = None
        self.main_ctrl = None
        self.main_hero = None
        self.main_name = None
        self.bob_ctrl = None
        self.round = 0
        self.gold = None
        self.tier = None
        self.hero_hp = None
        self.hero_damage = None
        self.hero_armor = None
        self.placement = None
        self.seq = 0
        self.snapshots = []
        self.last_snap_round = -1
        self.snapped_turns = set()
        self.actions = []
        self.block_stack = []
        self.opp_hero_card = None

    # ---- 实体 / tag ----
    def e(self, eid):
        return self.ent.setdefault(str(eid), {"card": None, "tags": {}, "last": 0})

    def set_tag(self, eid, k, v):
        eid = str(eid)
        if eid in ("", "None"):
            return
        k = str(k)
        e = self.e(eid)
        e["tags"][k] = v
        e["last"] = self.seq
        if k == TAG_CONTROLLER:
            if "BaconShopBob" in (e.get("card") or ""):
                self.bob_ctrl = v
            if eid in self.players:
                self.players[eid] = v
            if eid == str(self.main):
                self.main_ctrl = v
        elif k == TAG_HERO_ENTITY:
            if eid == str(self.main):
                self.main_hero = v
        elif k == TAG_TURN and eid == str(self.main):
            nt = _int(v)
            if nt is not None and nt > self.round:
                # 没有战斗的回合（1/2 回合、对手空场等）不会有 ATTACK block，
                # 在回合切换瞬间补一张“回合末”快照（此时战斗已结算完）。
                if self.round > 0 and self.round not in self.snapped_turns:
                    self.snapshot("turn_end")
                self.round = nt
        elif k == TAG_RESOURCES and eid == str(self.main):
            self.gold = _int(v)
        elif k == TAG_TECH_LEVEL and eid == str(self.main):
            self.tier = _int(v)
        elif k == TAG_LEADERBOARD_PLACE:
            p = _int(v)
            ctrl = e["tags"].get(TAG_CONTROLLER)
            if p and p > 0 and (eid == str(self.main) or eid == str(self.main_hero)
                                or (self.main_ctrl is not None and ctrl == self.main_ctrl)):
                self.placement = p
        if eid == str(self.main_hero):
            if k == TAG_HEALTH:
                self.hero_hp = _int(v)
            elif k == TAG_DAMAGE:
                self.hero_damage = _int(v)
            elif k == TAG_ARMOR:
                self.hero_armor = _int(v)

    def _on_entity_end(self, el):
        eid = el.get("id") or el.get("entity")
        if not eid:
            return
        e = self.e(eid)
        card_id = el.get("cardID")
        if card_id:
            e["card"] = card_id
        if el.tag == "Player":
            e["is_main"] = el.get("isMainPlayer") == "true"
            e["name"] = el.get("name")
            self.players[str(eid)] = None
            if e["is_main"]:
                self.main = str(eid)
                self.main_name = el.get("name")
        tags = [(x.get("tag"), x.get("value")) for x in el.findall("Tag")]
        if not tags:
            return
        # Firestone/HSReplay 写回放时会在每个 phase 边界把
        # GameEntity + 双方 Player + 英雄的 tag 合并进一个 <GameEntity>。
        # 分组规则：出现 tag 50 (CONTROLLER) 且组内已有 53 (ENTITY_ID) 时
        # 开启新组；组的实体 id 取组内 53。
        groups = []
        cur = []
        for k, v in tags:
            if k == TAG_CONTROLLER and any(x[0] == TAG_ENTITY_ID for x in cur):
                groups.append(cur)
                cur = []
            cur.append((k, v))
        if cur:
            groups.append(cur)
        for g in groups:
            gid = next((v for k, v in g if k == TAG_ENTITY_ID), None) or eid
            for k, v in g:
                self.set_tag(gid, k, v)

    # ---- 状态快照 ----
    def _board(self, ctrl):
        out = []
        for eid, e in self.ent.items():
            t = e["tags"]
            if t.get(TAG_ZONE) != ZONE_PLAY:
                continue
            if ctrl is not None and t.get(TAG_CONTROLLER) != str(ctrl):
                continue
            card_id = e.get("card")
            if not card_id or self.cdb.kind(card_id) != "minion":
                continue
            info = self.cdb.info(card_id)
            atk = _int(t.get("47"), info["atk"] if info else 0)
            hp = _int(t.get(TAG_HEALTH), info["hp"] if info else 0)
            if hp is None or hp <= 0 or atk is None or atk < 0:
                continue
            pos = _int(t.get(TAG_POSITION), 99)
            shv = _int(t.get(TAG_DIVINE_SHIELD), 0) or 0
            gold = card_id.endswith("_G") or (_int(t.get(TAG_PREMIUM), 0) or 0) != 0
            printed = self.cdb.printed_kw(card_id)
            observed = 0
            for tg, name in TAG_TO_KW.items():
                if (_int(t.get(str(tg)), 0) or 0) != 0:
                    observed |= KW_BITS[name]
            out.append({
                "eid": eid, "card": self.cdb.cid(card_id), "card_id": card_id,
                "atk": int(atk), "hp": int(hp), "golden": bool(gold),
                "kw": int(observed | printed),
                "bonus_kw": int(observed & ~printed),
                "shield_max": int(3 if shv >= 3 else 1),
                "position": int(pos), "tier": _int(t.get(TAG_TECH_LEVEL), info["tier"] if info else 0),
                "last": int(e.get("last") or 0),
            })
        # 同位置只保留最近更新的实体（战斗复制体 / 已死旧实体去重）
        by_pos = {}
        for m in out:
            p = m["position"]
            if p not in by_pos or m["last"] >= by_pos[p]["last"]:
                by_pos[p] = m
        out = [by_pos[k] for k in sorted(by_pos)][:7]
        out.sort(key=lambda m: m["position"])
        return out

    def _cards(self, zone, ctrl, kinds):
        out = []
        for eid, e in self.ent.items():
            t = e["tags"]
            if t.get(TAG_ZONE) != zone:
                continue
            if ctrl is not None and t.get(TAG_CONTROLLER) != str(ctrl):
                continue
            card_id = e.get("card")
            if not card_id:
                continue
            kind = self.cdb.kind(card_id)
            if kind not in kinds:
                continue
            info = self.cdb.info(card_id)
            atk = _int(t.get("47"), info["atk"] if info else 0)
            hp = _int(t.get(TAG_HEALTH), info["hp"] if info else 0)
            pos = _int(t.get(TAG_POSITION), 99)
            out.append({
                "eid": eid, "card": self.cdb.cid(card_id), "card_id": card_id,
                "kind": kind, "atk": int(atk or 0), "hp": int(hp or 0),
                "golden": card_id.endswith("_G") or (_int(t.get(TAG_PREMIUM), 0) or 0) != 0,
                "position": int(pos),
            })
        out.sort(key=lambda m: (m["position"], m["eid"]))
        return out

    def snapshot(self, reason="attack"):
        if self.main_ctrl is None:
            return None
        opp_ctrl = None
        for pid, ctrl in self.players.items():
            if ctrl is not None and ctrl != self.main_ctrl:
                opp_ctrl = ctrl
                break
        opp_hero = None
        if opp_ctrl is not None:
            for pid, ctrl in self.players.items():
                if ctrl == opp_ctrl:
                    hero_id = self.ent.get(pid, {}).get("tags", {}).get(TAG_HERO_ENTITY)
                    opp_hero = (self.ent.get(str(hero_id)) or {}).get("card")
                    break
            self.opp_hero_card = opp_hero
        snap = {
            "turn": int(self.round),
            "reason": reason,
            "self_board": self._board(self.main_ctrl),
            "hand": self._cards(ZONE_HAND, self.main_ctrl, HAND_KINDS)[:10],
            "shop": [],
            "gold": self.gold,
            "tier": self.tier,
            "hero_hp": self.hero_hp,
            "hero_damage": self.hero_damage,
            "hero_armor": self.hero_armor,
            "opp_hero_card": opp_hero,
        }
        if self.bob_ctrl is not None:
            shop = []
            seen = set()
            for zone in (ZONE_PLAY, ZONE_SETASIDE):
                for m in self._cards(zone, self.bob_ctrl, CARD_KINDS):
                    key = (m["position"], m["card_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    shop.append(m)
            shop.sort(key=lambda m: (m["position"], m["eid"]))
            snap["shop"] = shop[:8]
        self.snapshots.append(snap)
        self.snapped_turns.add(int(self.round))
        return snap

    # ---- Block / 动作 ----
    def _classify(self, card_id, eid):
        c = card_id or ""
        if "DragBuy" in c:
            return "buy_spell" if "Spell" in c else "buy_minion"
        if "DragSell" in c:
            return "sell"
        if "Reroll" in c:
            return "reroll"
        if "LockAll" in c or "Freeze" in c:
            return "freeze"
        if "TechUp" in c:
            return "upgrade"
        if "Triples" in c:
            return "triple"
        if "DarkGift" in c:
            return "dark_gift"
        if c.startswith("TB_BaconShop_HP_") or self.cdb.kind(c) == "hero_power":
            return "hero_power"
        kind = self.cdb.kind(c)
        if kind == "minion":
            return "play_minion"
        if kind in ("spell", "tavern_spell"):
            return "play_spell"
        return None

    def _action_index(self, a):
        at = a["action_type"]
        if at == "end_turn":
            return 0
        if at in ("reroll",):
            return 1
        if at == "freeze":
            return 2
        if at == "upgrade":
            return 3
        if at == "hero_power":
            return 4
        if at == "dark_gift":
            return 6
        if at == "buy_minion":
            s = a.get("shop_slot")
            return 8 + s if isinstance(s, int) and 0 <= s <= 7 else None
        if at == "buy_spell":
            return 15
        if at == "sell":
            s = a.get("board_slot")
            return 16 + s if isinstance(s, int) and 0 <= s <= 6 else None
        if at in ("play_minion", "play_spell"):
            h, p = a.get("hand_slot"), a.get("play_pos")
            if isinstance(h, int) and isinstance(p, int) and 0 <= h <= 9 and 0 <= p <= 7:
                return 46 + h * 8 + p
        if at == "reposition":
            f, t = a.get("from_slot"), a.get("to_slot")
            if isinstance(f, int) and isinstance(t, int) and 0 <= f <= 6 and 0 <= t <= 6:
                return 196 + f * 7 + t
        return None

    def _on_block_start(self, el):
        bt = el.get("type")
        eid = el.get("entity")
        rec = {"bt": bt, "eid": str(eid) if eid else None, "action": None}
        if bt == BLOCK_ATTACK and self.round != self.last_snap_round:
            self.last_snap_round = self.round
            self.snapshot("attack")
        if bt == BLOCK_PLAY:
            e = self.ent.get(str(eid)) or {}
            card_id = e.get("card")
            at = self._classify(card_id, eid)
            if at is not None:
                target = el.get("target")
                tgt = self.ent.get(str(target)) or {}
                snap = {
                    "turn": int(self.round), "action_type": at,
                    "card_id": None, "target_card_id": None,
                    "entity_id": str(eid) if eid else None, "target_id": str(target) if target else None,
                    "gold": self.gold, "tier": self.tier,
                    "hero_hp": self.hero_hp, "hero_armor": self.hero_armor,
                    "shop_slot": None, "board_slot": None,
                    "hand_slot": None, "play_pos": None,
                    "board_cards": [m["card_id"] for m in self._board(self.main_ctrl)],
                    "hand_cards": [m["card_id"] for m in self._cards(ZONE_HAND, self.main_ctrl, HAND_KINDS)],
                    "shop_cards": [],
                }
                if self.bob_ctrl is not None:
                    shop = []
                    seen = set()
                    for zone in (ZONE_PLAY, ZONE_SETASIDE):
                        for m in self._cards(zone, self.bob_ctrl, CARD_KINDS):
                            k = (m["position"], m["card_id"])
                            if k not in seen:
                                seen.add(k)
                                shop.append(m)
                    shop.sort(key=lambda m: (m["position"], m["eid"]))
                    snap["shop_cards"] = [m["card_id"] for m in shop[:8]]
                if at in ("buy_minion", "buy_spell"):
                    if tgt.get("card"):
                        snap["card_id"] = tgt.get("card")
                        p = _int((tgt.get("tags") or {}).get(TAG_POSITION))
                        snap["shop_slot"] = (p - 1) if p is not None and 1 <= p <= 8 else None
                elif at == "sell":
                    if tgt.get("card"):
                        snap["card_id"] = tgt.get("card")
                        p = _int((tgt.get("tags") or {}).get(TAG_POSITION))
                        snap["board_slot"] = (p - 1) if p is not None and 1 <= p <= 7 else None
                elif at in ("play_minion", "play_spell"):
                    snap["card_id"] = card_id
                    p = _int((e.get("tags") or {}).get(TAG_POSITION))
                    zone = (e.get("tags") or {}).get(TAG_ZONE)
                    snap["hand_slot"] = (p - 1) if zone == ZONE_HAND and p is not None and 1 <= p <= 10 else 0
                elif at == "hero_power":
                    snap["card_id"] = card_id
                else:
                    snap["card_id"] = None if at in ("reroll", "freeze", "upgrade") else card_id
                rec["action"] = snap
        self.block_stack.append(rec)

    def _on_block_end(self, el):
        if not self.block_stack:
            return
        bt = el.get("type")
        eid = el.get("entity")
        rec = None
        for i in range(len(self.block_stack) - 1, -1, -1):
            r = self.block_stack[i]
            if r is not None and r.get("eid") == (str(eid) if eid else None) and r.get("bt") == bt:
                rec = self.block_stack.pop(i)
                break
        if rec is None:
            self.block_stack.pop()
            return
        a = rec.get("action")
        if not a:
            return
        if a["action_type"] in ("play_minion", "play_spell"):
            e = self.ent.get(str(eid)) or {}
            zone = (e.get("tags") or {}).get(TAG_ZONE)
            p = _int((e.get("tags") or {}).get(TAG_POSITION))
            if zone == ZONE_PLAY and p is not None:
                a["play_pos"] = (p - 1) if 1 <= p <= 7 else None
            elif a["action_type"] == "play_spell" and a.get("play_pos") is None:
                a["play_pos"] = 0
        a["action_index"] = self._action_index(a)
        self.actions.append(a)

    # ---- 主循环 ----
    def parse(self, zip_path):
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")]
            if not names:
                return None
            with z.open(names[0]) as fh:
                for ev, el in ET.iterparse(fh, events=("start", "end")):
                    self.seq += 1
                    if ev == "start":
                        if el.tag == "Block":
                            self._on_block_start(el)
                        elif el.tag == "TagChange":
                            eid = el.get("entity")
                            if eid:
                                self.set_tag(eid, el.get("tag"), el.get("value"))
                    else:
                        if el.tag in ENT_TAGS:
                            self._on_entity_end(el)
                            el.clear()
                        elif el.tag == "Block":
                            self._on_block_end(el)
                            el.clear()
        return self.result()

    def result(self):
        # 每个回合补一条 end_turn 动作（状态取该回合战斗开始前的战团快照）
        by_turn = {s["turn"]: s for s in self.snapshots}
        for t, s in sorted(by_turn.items()):
            a = {
                "turn": int(t), "action_type": "end_turn", "card_id": None,
                "target_card_id": None, "entity_id": None, "target_id": None,
                "gold": s.get("gold"), "tier": s.get("tier"),
                "hero_hp": s.get("hero_hp"), "hero_armor": s.get("hero_armor"),
                "shop_slot": None, "board_slot": None, "hand_slot": None,
                "play_pos": None,
                "board_cards": [m["card_id"] for m in s["self_board"]],
                "hand_cards": [m["card_id"] for m in s["hand"]],
                "shop_cards": [m["card_id"] for m in s["shop"]],
                "action_index": 0,
            }
            self.actions.append(a)
        self.actions.sort(key=lambda a: (a["turn"], a["action_type"]))
        return {
            "main_name": self.main_name,
            "hero_card_id": (self.ent.get(str(self.main_hero)) or {}).get("card"),
            "placement": self.placement,
            "turn_count": int(self.round),
            "snapshots": self.snapshots,
            "actions": self.actions,
        }


# ════════════════════════════════════════════════════════════════════════
# PMS（post-match stats）解析
# ════════════════════════════════════════════════════════════════════════
def _pms_kw(cdb: CardDb, m):
    card_id = m.get("cardId") or ""
    printed = cdb.printed_kw(card_id)
    bits = 0
    for field, name in (("taunt", "TAUNT"), ("divineShield", "DIVINE_SHIELD"),
                        ("windfury", "WINDFURY"), ("reborn", "REBORN"),
                        ("venomous", "VENOMOUS"), ("poisonous", "POISONOUS"),
                        ("stealth", "STEALTH")):
        if m.get(field):
            bits |= KW_BITS[name]
    tags = m.get("tags") or {}
    if _int(tags.get("MAGNETIC"), 0):
        bits |= KW_BITS["MAGNETIC"]
    sh = _int(tags.get("DIVINE_SHIELD"), 0) or (1 if m.get("divineShield") else 0)
    shield = 3 if sh >= 3 else (1 if sh else 1)
    return int(bits | printed), int(bits & ~printed), shield


def pms_minions(cdb: CardDb, raw, keep_kinds=CARD_KINDS):
    out = []
    for i, m in enumerate(raw or []):
        if not isinstance(m, dict):
            continue
        card_id = m.get("cardId")
        cid = cdb.cid(card_id)
        info = cdb.info(card_id)
        if cid is None or info is None:
            out.append({"unmapped": card_id, "position": i + 1})
            continue
        if info["kind"] not in keep_kinds:
            continue
        atk = _int(m.get("attack"), 0) or 0
        hp = _int(m.get("health"), 0) or 0
        if hp <= 0 or atk < 0:
            continue
        kw, bonus, shield = _pms_kw(cdb, m)
        tags = m.get("tags") or {}
        out.append({
            "card": int(cid), "card_id": card_id, "kind": info["kind"],
            "atk": int(atk), "hp": int(hp),
            "golden": bool(str(card_id).endswith("_G") or _int(tags.get("PREMIUM"), 0)),
            "kw": int(kw), "bonus_kw": int(bonus), "shield_max": int(shield),
            "position": i + 1, "tier": _int(tags.get("TECH_LEVEL"), info["tier"]),
        })
    return [m for m in out if "unmapped" not in m]


def pms_parse(path, cdb: CardDb, feed):
    d = json.load(open(path, "r", encoding="utf-8"))
    mapping = d.get("playerIdToCardIdMapping") or {}
    main_pid = None
    for pid, cid in mapping.items():
        if cid == feed.get("playerCardId"):
            main_pid = pid
            break
    battles = []
    for i, b in enumerate(d.get("battleResultHistory") or []):
        bi = b.get("battleInfo")
        if not bi:
            continue
        pb = bi.get("playerBoard") or {}
        ob = bi.get("opponentBoard") or {}
        if main_pid is None:
            pc = (pb.get("player") or {}).get("cardId")
            if pc == feed.get("playerCardId"):
                main_pid = "self"
        battles.append({
            "idx": i,
            "turn_field": b.get("turn"),
            "actual": b.get("actualResult") is not None,
            "actual_result": b.get("actualResult"),
            "self_board": pms_minions(cdb, pb.get("board")),
            "opp_board": pms_minions(cdb, ob.get("board")),
            "self_player": pb.get("player") or {},
            "opp_player": ob.get("player") or {},
            "self_hand": pms_minions(cdb, (pb.get("player") or {}).get("hand")),
            "opp_hero": (ob.get("player") or {}).get("cardId"),
            "raw_self_n": len(pb.get("board") or []),
            "raw_opp_n": len(ob.get("board") or []),
        })
    return {
        "battles": battles,
        "main_pid": main_pid,
        "leaderboard": d.get("leaderboardPositionOverTurn") or {},
        "old_mmr": d.get("oldMmr"),
        "new_mmr": d.get("newMmr"),
    }


# ════════════════════════════════════════════════════════════════════════
# 行构造
# ════════════════════════════════════════════════════════════════════════
def _sig(row):
    b = tuple((int(m["card"]), int(m["atk"]), int(m["hp"]), bool(m.get("golden")),
               int(m.get("kw") or 0)) for m in (row.get("board_detail") or []))
    h = tuple((int(x["card"]), str(x.get("kind"))) for x in (row.get("hand") or []))
    return (int(row["turn"]), b, h, row.get("tier"), row.get("perspective"))


def _split(game_id: str) -> str:
    return "evaluation" if (int(hashlib.md5(game_id.encode()).hexdigest()[:8], 16) % 10 == 0) else "train"


def _row_from_board(*, game_id, turn, board, hand, hand_available, tier, gold,
                    hero_cid, hero_card_id, hp, armor, placement, main_placement, source,
                    perspective, opponent_hero, build, mmr, archetype, tribes,
                    banned, real_pms, action_counts, split, stage="combat_start"):
    """把一组 minion dict 变成 human_board_pool 可直接加载的库行。"""
    board = sorted(board, key=lambda m: (m["position"], m.get("card") or 0))
    if not board or len(board) > 7:
        return None
    strength = sum(int(m["atk"]) + int(m["hp"]) for m in board)
    if strength > 250_000:
        return None
    detail = []
    flat = []
    for i, m in enumerate(board):
        detail.append({
            "card": int(m["card"]), "card_id": m.get("card_id"),
            "atk": int(m["atk"]), "hp": int(m["hp"]),
            "golden": bool(m.get("golden")), "kw": int(m.get("kw") or 0),
            "bonus_kw": int(m.get("bonus_kw") or 0),
            "shield_max": int(m.get("shield_max") or 1),
            "position": i + 1,
        })
        flat.append([int(m["card"]), int(m["atk"]), int(m["hp"])])
    hand_rows = []
    for x in hand or []:
        hand_rows.append({
            "card": int(x["card"]), "card_id": x.get("card_id"),
            "kind": x.get("kind") or "minion",
            "atk": int(x.get("atk") or 0), "hp": int(x.get("hp") or 0),
            "golden": bool(x.get("golden")), "kw": int(x.get("kw") or 0),
        })
    av = {
        "board": "observed", "golden": "observed", "keywords": "observed",
        "shield_max": "observed", "tavern_tier": "observed" if tier else "unavailable",
        "hand": "observed" if hand_available else "unavailable",
        "gold": "observed" if gold is not None else "unavailable",
        "hero": "observed_not_injected",
        "counter": "unavailable", "gems": "unavailable", "attachments": "unavailable",
        "deathrattle_scripts": "unavailable", "player_counters": "unavailable",
        "hero_power_uses": "unavailable", "shop": "unavailable" if perspective == "self" else "unavailable",
        "pool_delta": "unavailable",
    }
    return {
        "turn": int(turn),
        "strength": int(strength),
        "board": flat,
        "board_detail": detail,
        "hand": hand_rows,
        "hand_available": bool(hand_available),
        "hand_n": len(hand_rows),
        "tier": int(tier) if tier is not None else None,
        "gold": int(gold) if gold is not None else None,
        "hero": int(hero_cid) if hero_cid is not None else None,
        "hero_card_id": hero_card_id,
        "hero_hp": int(hp) if hp is not None else None,
        "hero_armor": int(armor) if armor is not None else None,
        "placement": int(placement) if placement is not None else None,
        "main_placement": int(main_placement if main_placement is not None else placement)
                          if (main_placement is not None or placement is not None) else None,
        "source": source,
        "schema": "hsbg.human_state_quasi_full",
        "schema_version": 1,
        "game_id": game_id,
        "split": split,
        "stage": stage,
        "perspective": perspective,
        "controller": None,
        "opponent_hero_card_id": opponent_hero,
        "build_number": build,
        "mmr": _int(mmr),
        "archetype": archetype,
        "tribes": tribes,
        "banned_tribes": banned,
        "actual_battle": bool(real_pms),
        "action_counts": action_counts or {},
        "availability": av,
    }


def jaccard(a, b):
    ca = collections.Counter(a)
    cb = collections.Counter(b)
    if not ca and not cb:
        return 1.0
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return inter / union if union else 1.0


# ════════════════════════════════════════════════════════════════════════
# 单局处理
# ════════════════════════════════════════════════════════════════════════
def parse_game(task):
    feed, xmlz, pms_dir, cards_path, drop_unmapped = task
    rid = feed["reviewId"]
    t0 = time.time()
    out = {"game_id": rid, "rows": [], "actions": [], "stats": {}, "errors": []}
    try:
        cdb = CardDb(cards_path)
        xml_path = os.path.join(xmlz, rid + ".xml.zip")
        pms_path = os.path.join(pms_dir, rid + ".json")
        xml = None
        if os.path.exists(xml_path):
            xml = XmlReplay(cdb).parse(xml_path)
        pms = None
        if os.path.exists(pms_path):
            pms = pms_parse(pms_path, cdb, feed)
        if xml is None:
            out["stats"]["error"] = "xml_missing"
            return out

        hero_cid = cdb.cid(feed.get("playerCardId"))
        placement = xml.get("placement")
        build = feed.get("buildNumber")
        mmr = feed.get("playerRank")
        archetype = feed.get("bgsCompArchetype")
        tribes = feed.get("bgsAvailableTribes")
        banned = feed.get("bgsBannedTribes")
        split = _split(rid)
        snaps = {s["turn"]: s for s in xml["snapshots"]}

        # 动作为每回合计数
        counts = collections.defaultdict(collections.Counter)
        for a in xml["actions"]:
            counts[a["turn"]][a["action_type"]] += 1

        matched = {}
        match_scores = []
        if pms:
            actuals = [b for b in pms["battles"] if b["actual"]]
            cand = []
            for b in actuals:
                a = [m["card_id"] for m in b["self_board"]]
                for turn, s in snaps.items():
                    bcards = [m["card_id"] for m in s["self_board"]]
                    sc = jaccard(a, bcards)
                    if sc > 0:
                        cand.append((sc, turn, b["idx"]))
            cand.sort(reverse=True)
            used_turns, used_battles = set(), set()
            for sc, turn, idx in cand:
                if turn in used_turns or idx in used_battles or sc < 0.34:
                    continue
                used_turns.add(turn)
                used_battles.add(idx)
                b = next(x for x in actuals if x["idx"] == idx)
                matched[turn] = (sc, b)
                match_scores.append(sc)

        for turn in sorted(snaps):
            s = snaps[turn]
            m = matched.get(turn)
            if m and len(m[1]["self_board"]) >= len(s["self_board"]):
                board = m[1]["self_board"]
                tier = _int(m[1]["self_player"].get("tavernTier"), s.get("tier"))
                hp = _int(m[1]["self_player"].get("hpLeft"), s.get("hero_hp"))
                hand = m[1]["self_hand"] or s["hand"]
                hand_available = True
                real_pms = True
                src = "firestone_pms+xml"
            else:
                board = s["self_board"]
                tier = s.get("tier")
                hp = s.get("hero_hp")
                hand = s["hand"]
                hand_available = bool(s["hand"])
                real_pms = False
                src = "firestone_xml"
            if drop_unmapped and any(m.get("card") is None for m in board):
                out["stats"]["drop_unmapped_self"] = out["stats"].get("drop_unmapped_self", 0) + 1
            elif board:
                row = _row_from_board(
                    game_id=rid, turn=turn, board=board, hand=hand,
                    hand_available=hand_available, tier=tier, gold=s.get("gold"),
                    hero_cid=hero_cid, hero_card_id=feed.get("playerCardId"),
                    hp=hp, armor=s.get("hero_armor"), placement=placement,
                    main_placement=placement,
                    source=src, perspective="self", opponent_hero=(m[1]["opp_hero"] if m else s.get("opp_hero_card")),
                    build=build, mmr=mmr, archetype=archetype, tribes=tribes, banned=banned,
                    real_pms=real_pms, action_counts=dict(counts.get(turn, {})), split=split)
                if row:
                    out["rows"].append(row)
            # 对手帧（仅当 PMS 实际战斗与 XML 回合匹配）
            if m and m[1]["opp_board"]:
                ob = m[1]["opp_board"]
                opp_hero = m[1]["opp_hero"]
                opp_cid = cdb.cid(opp_hero)
                row = _row_from_board(
                    game_id=rid, turn=turn, board=ob, hand=[], hand_available=False,
                    tier=_int(m[1]["opp_player"].get("tavernTier")),
                    gold=None, hero_cid=opp_cid, hero_card_id=opp_hero,
                    hp=_int(m[1]["opp_player"].get("hpLeft")), armor=None,
                    placement=None, main_placement=placement,
                    source="firestone_pms_opponent",
                    perspective="opponent", opponent_hero=feed.get("playerCardId"),
                    build=build, mmr=mmr, archetype=archetype, tribes=tribes, banned=banned,
                    real_pms=True, action_counts={}, split=split)
                if row:
                    out["rows"].append(row)

        # 动作样本
        for a in xml["actions"]:
            out["actions"].append({
                "game_id": rid,
                "turn": int(a["turn"]),
                "action_type": a["action_type"],
                "card_id": a.get("card_id"),
                "target_card_id": a.get("target_card_id"),
                "entity_id": a.get("entity_id"),
                "target_id": a.get("target_id"),
                "gold": a.get("gold"), "tier": a.get("tier"),
                "health": a.get("hero_hp"), "armor": a.get("hero_armor"),
                "board_cards": a.get("board_cards") or [],
                "hand_cards": a.get("hand_cards") or [],
                "shop_cards": a.get("shop_cards") or [],
                "shop_slot": a.get("shop_slot"), "board_slot": a.get("board_slot"),
                "hand_slot": a.get("hand_slot"), "play_pos": a.get("play_pos"),
                "action_index": a.get("action_index"),
                "placement": placement,
                "build_number": build,
                "source": "firestone_xml",
            })

        out["stats"].update({
            "xml_ok": True,
            "pms_ok": pms is not None,
            "turns": len(snaps),
            "turn_count": xml.get("turn_count"),
            "placement": placement,
            "actions": len(xml["actions"]),
            "matches": len(matched),
            "match_scores": match_scores,
            "pms_battles": len(pms["battles"]) if pms else 0,
            "pms_actual": sum(1 for b in pms["battles"] if b["actual"]) if pms else 0,
            "self_rows": sum(1 for r in out["rows"] if r["perspective"] == "self"),
            "opp_rows": sum(1 for r in out["rows"] if r["perspective"] == "opponent"),
            "action_counts": {k: sum(c[k] for c in counts.values()) for k in
                              set().union(*[set(c) for c in counts.values()])} if counts else {},
        })
    except Exception as e:  # noqa: BLE001
        out["errors"].append({"game_id": rid, "error": f"{type(e).__name__}: {e}",
                              "trace": traceback.format_exc()[-1500:]})
    out["stats"]["seconds"] = round(time.time() - t0, 2)
    return out


# ════════════════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════════════════
def _pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/firestone_replays")
    ap.add_argument("--xmlz", default="")
    ap.add_argument("--pms", default="")
    ap.add_argument("--index", default="")
    ap.add_argument("--cards", default="rust/crates/hsbg-engine/data/cards.json")
    ap.add_argument("--out", default="data/real_library/library_firestone_recent.jsonl")
    ap.add_argument("--stats", default="data/real_library/library_firestone_recent_stats.json")
    ap.add_argument("--actions-out", default="data/firestone_replays/firestone_recent_actions.jsonl.gz")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    root = args.root
    xmlz = args.xmlz or os.path.join(root, "xmlz")
    pms_dir = args.pms or os.path.join(root, "pms")
    index = args.index or os.path.join(root, "index.json")
    feed = json.load(open(index, "r", encoding="utf-8"))
    if args.limit:
        feed = feed[: args.limit]
    print(f"games={len(feed)} workers={args.workers}", file=sys.stderr)

    tasks = [(g, xmlz, pms_dir, args.cards, True) for g in feed]
    t0 = time.time()
    results = []
    if args.workers <= 1:
        for i, task in enumerate(tasks):
            results.append(parse_game(task))
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(tasks)} {time.time()-t0:.0f}s", file=sys.stderr)
    else:
        with Pool(args.workers) as pool:
            for i, r in enumerate(pool.imap(parse_game, tasks, chunksize=1)):
                results.append(r)
                if (i + 1) % 50 == 0:
                    print(f"  {i+1}/{len(tasks)} {time.time()-t0:.0f}s", file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.stats)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.actions_out)), exist_ok=True)

    rows = []
    actions = []
    errors = []
    games_ok = games_xml = games_pms = 0
    matches = 0
    pms_battles = pms_actual = 0
    match_scores = []
    turn_hist = collections.Counter()
    turn_rows = collections.Counter()
    size_hist = collections.Counter()
    strengths = collections.defaultdict(list)
    action_counts = collections.Counter()
    act_mappable = collections.Counter()
    act_total = collections.Counter()
    per_game = []
    fields = collections.Counter()
    minion_mentions = 0
    unmapped = collections.Counter()
    placements = collections.Counter()
    build_hist = collections.Counter()
    mmr_values = []
    for r in results:
        games_ok += 1
        st = r["stats"]
        if st.get("xml_ok"):
            games_xml += 1
        if st.get("pms_ok"):
            games_pms += 1
        if r["errors"]:
            errors.extend(r["errors"])
            continue
        matches += st.get("matches", 0)
        pms_battles += st.get("pms_battles", 0)
        pms_actual += st.get("pms_actual", 0)
        match_scores.extend(st.get("match_scores") or [])
        turn_hist[st.get("turns", 0)] += 1
        per_game.append(st.get("self_rows", 0) + st.get("opp_rows", 0))
        placements[st.get("placement")] += 1
        build_hist[st.get("actions", 0) and 0 or 0] += 0
        for k, v in (st.get("action_counts") or {}).items():
            action_counts[k] += v
        rows.extend(r["rows"])
        actions.extend(r["actions"])

    # 去重
    seen = set()
    dedup = 0
    kept = []
    for row in rows:
        s = _sig(row)
        if s in seen:
            dedup += 1
            continue
        seen.add(s)
        kept.append(row)
    rows = kept
    for a in actions:
        act_total[a["action_type"]] += 1
        if a.get("action_index") is not None:
            act_mappable[a["action_type"]] += 1
    for row in rows:
        turn_rows[row["turn"]] += 1
        size_hist[len(row["board"])] += 1
        strengths[row["turn"]].append(row["strength"])
        for m in row["board_detail"]:
            minion_mentions += 1
            if m["card"] is None:
                unmapped[m.get("card_id")] += 1
        if row.get("tier") is not None:
            fields["tier"] += 1
        if row.get("gold") is not None:
            fields["gold"] += 1
        if row.get("hero") is not None:
            fields["hero"] += 1
        if row.get("placement") is not None:
            fields["placement"] += 1
        if row.get("main_placement") is not None:
            fields["main_placement"] += 1
        if row.get("hand_available"):
            fields["hand"] += 1
        if row.get("hero_hp") is not None:
            fields["hero_hp"] += 1
        if row.get("board_detail"):
            fields["board"] += 1
        if any(m["kw"] for m in row["board_detail"]):
            fields["keywords"] += 1
        if any(m["golden"] for m in row["board_detail"]):
            fields["golden"] += 1
        if row.get("mmr"):
            mmr_values.append(int(row["mmr"]))
    n = max(1, len(rows))

    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    if str(args.actions_out).endswith(".gz"):
        af = gzip.open(args.actions_out, "wt", encoding="utf-8", compresslevel=6)
    else:
        af = open(args.actions_out, "w", encoding="utf-8")
    with af:
        for a in actions:
            af.write(json.dumps(a, ensure_ascii=False, separators=(",", ":")) + "\n")

    turn_strength = {}
    for t in sorted(strengths):
        v = strengths[t]
        turn_strength[str(t)] = {"n": len(v), "p50": _pct(v, 0.5), "p90": _pct(v, 0.9),
                                 "max": max(v)}
    stats = {
        "schema": "hsbg.firestone_replay_library.stats",
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {
            "root": root,
            "xmlz": xmlz,
            "pms": pms_dir,
            "index": index,
            "cards": args.cards,
            "feed": "https://static.zerotoheroes.com/api/bgs/bgs-perfect-games.json",
            "xml_endpoint": "https://xml.firestoneapp.com/<replayKey>",
            "pms_endpoint": "https://bgs-post-match-stats.firestoneapp.com/<reviewId>.gz.json",
        },
        "games": {
            "feed": len(feed),
            "processed": games_ok,
            "xml_ok": games_xml,
            "pms_ok": games_pms,
            "errors": len(errors),
        },
        "rows": {
            "total": len(rows),
            "self": sum(1 for r in rows if r["perspective"] == "self"),
            "opponent": sum(1 for r in rows if r["perspective"] == "opponent"),
            "from_pms": sum(1 for r in rows if "pms" in r["source"]),
            "from_xml": sum(1 for r in rows if r["source"] == "firestone_xml"),
            "dedup_removed": dedup,
            "per_game_mean": round(sum(per_game) / max(1, len(per_game)), 1),
        },
        "battles": {
            "pms_battles_with_info": pms_battles,
            "pms_actual": pms_actual,
            "matched_to_xml": matches,
            "match_rate_of_actual": round(matches / max(1, pms_actual), 3),
            "match_jaccard_p50": _pct(match_scores, 0.5),
            "match_jaccard_mean": round(sum(match_scores) / max(1, len(match_scores)), 3),
            "exact_match": sum(1 for x in match_scores if x >= 0.999),
        },
        "turns": {
            "per_game": dict(sorted(turn_hist.items())),
            "rows_by_turn": {str(k): v for k, v in sorted(turn_rows.items())},
            "strength_by_turn": turn_strength,
        },
        "board": {
            "size_hist": {str(k): v for k, v in sorted(size_hist.items())},
            "empty": sum(1 for r in rows if not r["board"]),
        },
        "placement": {str(k): v for k, v in placements.most_common()},
        "fields": {
            "rows": n,
            "coverage": {k: round(v / n, 4) for k, v in sorted(fields.items())},
            "mmr_min": min(mmr_values) if mmr_values else None,
            "mmr_max": max(mmr_values) if mmr_values else None,
        },
        "card_mapping": {
            "minion_mentions": minion_mentions,
            "unmapped": sum(unmapped.values()),
            "unmapped_ratio": round(sum(unmapped.values()) / max(1, minion_mentions), 5),
            "top_unmapped": unmapped.most_common(20),
        },
        "actions": {
            "total": len(actions),
            "by_type": dict(action_counts.most_common()),
            "mappable_by_type": {k: {"samples": act_total[k], "mappable": act_mappable[k],
                                     "ratio": round(act_mappable[k] / max(1, act_total[k]), 3)}
                                 for k in act_total},
            "mappable_ratio": round(sum(act_mappable.values()) / max(1, len(actions)), 3),
        },
        "errors": errors[:20],
        "elapsed_s": round(time.time() - t0, 1),
    }
    with open(args.stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"rows={len(rows)} actions={len(actions)} games={games_ok} "
          f"errors={len(errors)} elapsed={time.time()-t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
