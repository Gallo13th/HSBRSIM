#!/usr/bin/env python3
"""把 Firestone 回放数据集解析成 BC 紧凑样本。

输入目录结构（解压自 firestone-full-replays.7z）::

    <root>/player_<hash>/<game-uuid>/events.jsonl.gz
    <root>/player_<hash>/<game-uuid>/metadata.json

`events.jsonl.gz` 是 HSReplay XML 的扁平事件流：每行一个 XML 元素的
``start``/``end`` 记录，``type`` ∈ {HSReplay, Game, GameEntity, Player,
FullEntity, ShowEntity, HideEntity, ChangeEntity, Tag, TagChange, Block,
Choices, Choice, ChosenEntities, Option, SubOption, Target, Info, MetaData}。

本脚本只依赖标准库，输出：

* ``bc_samples.jsonl.gz``：每行一个决策样本；
* ``bc_parse_stats.json``：全局统计 + 卡表/动作映射覆盖率。

用法::

    python firestone_bc_parse.py --root <players> --cards cards.json \
        --out bc_samples.jsonl.gz --stats bc_parse_stats.json --workers 8
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import sys
import time
import traceback
from multiprocessing import Pool

# ── Hearthstone 枚举（只保留解析需要的常量）──────────────────────────────
TAG_ZONE = "49"
TAG_CONTROLLER = "50"
TAG_ENTITY_ID = "53"
TAG_POSITION = "263"
TAG_RESOURCES = "26"          # 金币
TAG_TURN = "20"
TAG_HERO_ENTITY = "27"
TAG_HEALTH = "45"
TAG_DAMAGE = "44"
TAG_ARMOR = "292"
TAG_TECH_LEVEL = "1377"       # 酒馆等级
TAG_CURRENT_PLAYER = "23"

ZONE_PLAY = "1"
ZONE_HAND = "3"
ZONE_SETASIDE = "6"

BLOCK_PLAY = "7"
BLOCK_MOVE_MINION = "12"

CARD_KINDS = ("minion", "spell", "tavern_spell")
HAND_KINDS = ("minion", "spell", "tavern_spell")

# 动作 → 标准动作空间（hsbg/env/action_space_std.py）
# (索引表达式, 是否可映射, 说明)
ACTION_MAP = {
    "end_turn": ("0", True, "EndTurn"),
    "reroll": ("1", True, "Refresh"),
    "freeze": ("2", True, "Freeze（整馆 toggle）"),
    "upgrade": ("3", True, "Upgrade"),
    "hero_power": ("4+slot", True, "HeroPower(slot)，slot 0..1"),
    "dark_gift": ("6", True, "DarkGift"),
    "buy_minion": ("8+slot", True, "Buy(shop slot 0..7)"),
    "buy_spell": ("8+7", True, "Buy(tavern spell slot 7)"),
    "sell": ("16+slot", True, "Sell(board slot 0..6)"),
    "play_minion": ("46+hand*8+pos", True, "Play{hand 0..9, pos 0..7}"),
    "play_spell": ("46+hand*8+pos", True, "Play{hand 0..9, pos 0..7}"),
    "reposition": ("196+from*7+to", True, "Move{from 0..6, to 0..6}"),
    "triple": ("30+option", False, "Choose(option)：选项未知，不可直接映射"),
    "activate": ("23+slot", False, "Activate：回放中未单独标注，未提取"),
    "magnetize": ("126+...", False, "BG 无磁力，不适用"),
}


def card_kind(cmap, cid):
    c = cmap.get(cid)
    return c.get("kind") if c else None


def base_id(cid):
    """去掉金色/升级后缀，用于卡表归一化匹配。"""
    if not cid:
        return cid
    if cid.endswith("_G"):
        return cid[:-2]
    return cid


def load_metadata(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    idx = d.get("indexEntry") or {}
    rec = d.get("recordingPlayer") or {}
    game = d.get("game") or {}
    return {
        "game_id": d.get("reviewId"),
        "player_folder": d.get("playerFolder"),
        "hero": idx.get("playerCardId"),
        "mmr": idx.get("playerRank"),
        "build": game.get("buildNumber") or idx.get("buildNumber"),
        "seed": game.get("gameSeed"),
        "tribes": idx.get("bgsAvailableTribes"),
        "banned_tribes": idx.get("bgsBannedTribes"),
        "duration_s": idx.get("gameDurationSeconds"),
        "duration_turns": idx.get("gameDurationTurns"),
        "recording_player": rec.get("name"),
        "is_main": rec.get("isMainPlayer"),
        "source_url": d.get("sourceUrl"),
    }


class GameParser:
    def __init__(self, cmap, meta, path):
        self.cmap = cmap
        self.meta = meta
        self.path = path
        self.entities = {}
        self.zone_sets = collections.defaultdict(set)
        self.cur = None                 # 当前实体 id（FullEntity/Player/GameEntity）
        self.main_id = None
        self.main_ctrl = None
        self.main_hero = None
        self.main_name = None
        self.bob_ctrl = None
        self.turn = None
        self.gold = None
        self.tier = None
        self.health = None
        self.damage = None
        self.armor = None
        self.block_stack = []
        self.samples = []
        self.counters = collections.Counter()
        self.card_mentions = collections.Counter()
        self.unmatched = collections.Counter()
        self.shopsize_hist = collections.Counter()
        self.turn_sizes = collections.Counter()
        self.last_turn = None
        self.seq = 0

    # ── 实体标签维护 ────────────────────────────────────────────────
    def ent(self, eid):
        e = self.entities.get(eid)
        if e is None:
            e = {"card": None, "tags": {}}
            self.entities[eid] = e
        return e

    def set_card(self, eid, cid):
        if cid:
            self.ent(eid)["card"] = cid

    def set_tag(self, eid, tag, val):
        e = self.ent(eid)
        if tag == TAG_ZONE:
            old = e["tags"].get(TAG_ZONE)
            if old in self.zone_sets:
                self.zone_sets[old].discard(eid)
            if val is not None:
                self.zone_sets.setdefault(val, set()).add(eid)
        e["tags"][tag] = val
        if tag == TAG_CONTROLLER:
            card = e.get("card") or ""
            if "BaconShopBob" in card:
                self.bob_ctrl = val
        if eid == self.main_id:
            if tag == TAG_RESOURCES:
                self.gold = _int(val)
            elif tag == TAG_TECH_LEVEL:
                self.tier = _int(val)
            elif tag == TAG_TURN:
                t = _int(val)
                if t is not None and self.turn is not None and t > self.turn:
                    # 回合切换 = 主玩家“结束回合”决策点，状态取切换前
                    self._emit_end_turn(self.turn)
                self.turn = t
            elif tag == TAG_HERO_ENTITY:
                self.main_hero = val
            elif tag == TAG_CONTROLLER:
                self.main_ctrl = val
        elif eid == self.main_hero:
            if tag == TAG_HEALTH:
                self.health = _int(val)
            elif tag == TAG_DAMAGE:
                self.damage = _int(val)
            elif tag == TAG_ARMOR:
                self.armor = _int(val)

    # ── 状态快照 ───────────────────────────────────────────────────
    def _cards_in(self, zone_ids, kinds, ctrl):
        out = []
        for eid in zone_ids:
            e = self.entities.get(eid)
            if not e:
                continue
            tg = e["tags"]
            if ctrl is not None and tg.get(TAG_CONTROLLER) != ctrl:
                continue
            cid = e.get("card")
            if not cid or cid.startswith("TB_"):
                continue
            if card_kind(self.cmap, cid) not in kinds:
                continue
            pos = _int(tg.get(TAG_POSITION))
            out.append((pos if pos is not None else 99, eid, cid))
        out.sort()
        return out

    def snapshot(self):
        board = self._cards_in(self.zone_sets.get(ZONE_PLAY, ()), ("minion",), self.main_ctrl)
        hand = self._cards_in(self.zone_sets.get(ZONE_HAND, ()), HAND_KINDS, self.main_ctrl)
        shop = []
        if self.bob_ctrl is not None:
            shop_ids = set(self.zone_sets.get(ZONE_PLAY, ())) | set(self.zone_sets.get(ZONE_SETASIDE, ()))
            shop = self._cards_in(shop_ids, CARD_KINDS, self.bob_ctrl)
            # 同一槽位去重（zone 1/6 可能同时存在同一张展示卡）
            seen = set()
            uniq = []
            for pos, eid, cid in shop:
                key = (pos, cid)
                if key in seen:
                    continue
                seen.add(key)
                uniq.append((pos, eid, cid))
            shop = uniq
        return {
            "board": [c for _, _, c in board],
            "hand": [c for _, _, c in hand],
            "shop": [c for _, _, c in shop],
            "board_ids": [e for _, e, _ in board],
            "hand_ids": [e for _, e, _ in hand],
            "shop_ids": [e for _, e, _ in shop],
            "shop_pos": [p - 1 for p, _, _ in shop],
            "board_pos": [p - 1 for p, _, _ in board],
            "hand_pos": [p - 1 for p, _, _ in hand],
        }

    # ── 样本构造 ───────────────────────────────────────────────────
    def _base_sample(self, action_type, action_card, entity_id, target_id):
        st = self.snapshot()
        main = self.entities.get(self.main_id) or {}
        mt = main.get("tags") or {}
        hero_id = mt.get(TAG_HERO_ENTITY) or self.main_hero
        hero = self.entities.get(hero_id) or {}
        ht = hero.get("tags") or {}
        s = {
            "game_id": self.meta.get("game_id"),
            "player_folder": self.meta.get("player_folder"),
            "player": self.main_name or self.main_id,
            "hero": self.meta.get("hero"),
            "mmr": self.meta.get("mmr"),
            "turn": _int(mt.get(TAG_TURN)) if mt else self.turn,
            "action_type": action_type,
            "card_id": None,
            "entity_id": entity_id,
            "target_id": target_id,
            "gold": _int(mt.get(TAG_RESOURCES)) if mt else self.gold,
            "tier": _int(mt.get(TAG_TECH_LEVEL)) if mt else self.tier,
            "health": _int(ht.get(TAG_HEALTH)),
            "damage": _int(ht.get(TAG_DAMAGE)),
            "armor": _int(ht.get(TAG_ARMOR)),
            "board_cards": st["board"],
            "hand_cards": st["hand"],
            "shop_cards": st["shop"],
            "shop_pos": st["shop_pos"],
            "board_pos": st["board_pos"],
            "hand_pos": st["hand_pos"],
            "ts": None,
            "seq": self.seq,
        }
        return s

    def _finish(self, s):
        cards = []
        if s.get("card_id"):
            cards.append(s["card_id"])
        cards.extend(s.get("shop_cards") or [])
        cards.extend(s.get("hand_cards") or [])
        cards.extend(s.get("board_cards") or [])
        for cid in cards:
            self.card_mentions[cid] += 1
            if cid not in self.cmap and base_id(cid) not in self.cmap:
                self.unmatched[cid] += 1
        at = s["action_type"]
        self.counters["samples"] += 1
        self.counters["act_" + at] += 1
        if s["turn"] is not None:
            self.turn_sizes[s["turn"]] += 1
        if s["shop_cards"]:
            self.counters["shop_nonempty"] += 1
            self.shopsize_hist[len(s["shop_cards"])] += 1
        if s["gold"] is None:
            self.counters["gold_missing"] += 1
        if s["tier"] is None:
            self.counters["tier_missing"] += 1
        if s["health"] is None:
            self.counters["health_missing"] += 1
        if not s["board_cards"]:
            self.counters["board_empty"] += 1
        if not s["hand_cards"]:
            self.counters["hand_empty"] += 1
        # 动作槽位可映射性
        ok, idx = self.action_index(s)
        self.counters["mappable_action" if ok else "unmappable_action"] += 1
        if ok:
            self.counters["map_" + at] += 1
        s["action_index"] = idx
        self.samples.append(s)

    def action_index(self, s):
        at = s["action_type"]
        info = ACTION_MAP.get(at)
        if not info or not info[1]:
            return False, None
        expr = info[0]
        if at in ("buy_minion",):
            slot = s.get("shop_slot")
            if slot is None or not (0 <= slot <= 7):
                return False, None
            return True, 8 + slot
        if at in ("buy_spell",):
            return True, 8 + 7
        if at == "sell":
            slot = s.get("board_slot")
            if slot is None or not (0 <= slot <= 6):
                return False, None
            return True, 16 + slot
        if at in ("play_minion", "play_spell"):
            h = s.get("hand_slot")
            p = s.get("play_pos")
            if h is None or not (0 <= h <= 9):
                return False, None
            if p is None or not (0 <= p <= 7):
                return False, None
            return True, 46 + h * 8 + p
        if at == "reposition":
            a = s.get("from_slot")
            b = s.get("to_slot")
            if a is None or b is None or not (0 <= a <= 6) or not (0 <= b <= 6):
                return False, None
            return True, 196 + a * 7 + b
        if at == "hero_power":
            return True, 4
        if expr.isdigit():
            return True, int(expr)
        return False, None

    def _emit_end_turn(self, turn):
        s = self._base_sample("end_turn", None, None, None)
        s["turn"] = turn
        self._finish(s)

    # ── 动作识别 ───────────────────────────────────────────────────
    def classify(self, card, entity_id):
        c = card or ""
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
        if c.startswith("TB_BaconShop_HP_") or card_kind(self.cmap, c) == "hero_power":
            return "hero_power"
        k = card_kind(self.cmap, c)
        if k == "minion":
            return "play_minion"
        if k in ("spell", "tavern_spell"):
            return "play_spell"
        return None

    def on_block_start(self, a, seq):
        bt = a.get("type")
        if bt not in (BLOCK_PLAY, BLOCK_MOVE_MINION):
            self.block_stack.append(None)
            return
        eid = a.get("entity")
        e = self.entities.get(eid) or {}
        card = e.get("card")
        rec = {"entity": eid, "type": bt, "sample": None}
        if bt == BLOCK_MOVE_MINION:
            k = card_kind(self.cmap, card)
            ctrl = e["tags"].get(TAG_CONTROLLER)
            in_action = any(r for r in self.block_stack if r)
            if (in_action or (card or "").startswith("TB_") or k != "minion"
                    or (self.main_ctrl is not None and ctrl != self.main_ctrl)):
                self.block_stack.append(rec)
                return
            s = self._base_sample("reposition", card, eid, a.get("target"))
            s["card_id"] = card
            pos = _int(e["tags"].get(TAG_POSITION))
            s["from_slot"] = (pos - 1) if pos else None
            s["to_slot"] = None
            rec["sample"] = s
        else:
            at = self.classify(card, eid)
            if at is None:
                self.block_stack.append(rec)
                return
            target_id = a.get("target")
            target = self.entities.get(target_id) or {}
            s = self._base_sample(at, card, eid, target_id)
            s["ts"] = a.get("ts")
            if at in ("buy_minion", "buy_spell"):
                s["card_id"] = target.get("card")
                pos = _int(target["tags"].get(TAG_POSITION))
                s["shop_slot"] = (pos - 1) if pos else None
            elif at == "sell":
                s["card_id"] = target.get("card")
                pos = _int(target["tags"].get(TAG_POSITION))
                s["board_slot"] = (pos - 1) if pos else None
            elif at in ("play_minion", "play_spell"):
                s["card_id"] = card
                s["play_pos"] = None
                zone = e["tags"].get(TAG_ZONE)
                pos = _int(e["tags"].get(TAG_POSITION))
                s["hand_slot"] = (pos - 1) if (zone == ZONE_HAND and pos) else None
                if zone == ZONE_HAND and s["hand_slot"] is None:
                    s["hand_slot"] = 0
            elif at == "hero_power":
                s["card_id"] = card
            else:
                # reroll / freeze / upgrade 等 UI 按钮不是游戏卡牌，不参与卡表映射
                s["card_id"] = None if at in ("reroll", "freeze", "upgrade") else card
            rec["sample"] = s
        self.block_stack.append(rec)

    def on_block_end(self, a, seq):
        if not self.block_stack:
            return
        bt = a.get("type")
        eid = a.get("entity")
        rec = None
        for i in range(len(self.block_stack) - 1, -1, -1):
            r = self.block_stack[i]
            if r is not None and r.get("entity") == eid and r.get("type") == bt:
                rec = self.block_stack.pop(i)
                break
        if rec is None:
            if self.block_stack:
                self.block_stack.pop()
            return
        s = rec.get("sample")
        if not s:
            return
        at = s["action_type"]
        if at in ("play_minion", "play_spell"):
            e = self.entities.get(eid) or {}
            zone = e["tags"].get(TAG_ZONE)
            pos = _int(e["tags"].get(TAG_POSITION))
            if zone == ZONE_PLAY and pos:
                s["play_pos"] = pos - 1
            elif at == "play_spell" and s.get("play_pos") is None:
                s["play_pos"] = 0
        elif at == "reposition":
            e = self.entities.get(eid) or {}
            pos = _int(e["tags"].get(TAG_POSITION))
            if pos:
                s["to_slot"] = pos - 1
        if at == "reposition" and (s.get("from_slot") is None or s.get("to_slot") is None
                                   or s.get("from_slot") == s.get("to_slot")):
            return
        self._finish(s)

    # ── 主循环 ─────────────────────────────────────────────────────
    def run(self):
        ev_path = self.path
        with gzip.open(ev_path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                t = o.get("type")
                a = o.get("attributes") or {}
                seq = o.get("seq", 0)
                self.seq = seq
                ev = o.get("event")

                if t in ("FullEntity", "ShowEntity", "ChangeEntity", "Player", "GameEntity"):
                    eid = a.get("id")
                    if ev == "start":
                        if eid:
                            self.cur = eid
                            self.ent(eid)
                            self.set_card(eid, a.get("cardID"))
                            if t == "Player" and a.get("isMainPlayer") == "true":
                                self.main_id = eid
                                self.main_name = a.get("name")
                        else:
                            self.cur = None
                    else:
                        self.cur = None
                    continue

                if t == "Tag":
                    if self.cur is not None:
                        self.set_tag(self.cur, a.get("tag"), a.get("value"))
                    continue

                if t == "TagChange":
                    eid = a.get("entity")
                    if eid:
                        self.set_tag(eid, a.get("tag"), a.get("value"))
                    continue

                if t == "Block":
                    if ev == "start":
                        self.on_block_start(a, seq)
                    else:
                        self.on_block_end(a, seq)
        return self


def _int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_game(args):
    root, game_dir, cmap = args
    meta_path = os.path.join(game_dir, "metadata.json")
    ev_path = os.path.join(game_dir, "events.jsonl.gz")
    meta = load_metadata(meta_path) if os.path.exists(meta_path) else {}
    meta.setdefault("game_id", os.path.basename(game_dir))
    meta.setdefault("player_folder", os.path.basename(os.path.dirname(game_dir)))
    p = GameParser(cmap, meta, ev_path)
    try:
        p.run()
    except Exception as e:
        return {
            "game_id": meta.get("game_id"),
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc()[-1500:],
            "samples": [],
            "stats": {},
        }
    stats = {
        "samples": p.counters.get("samples", 0),
        "counters": dict(p.counters),
        "turn_sizes": dict(p.turn_sizes),
        "shopsize_hist": dict(p.shopsize_hist),
        "card_mentions": dict(p.card_mentions),
        "unmatched": dict(p.unmatched),
    }
    return {"game_id": meta.get("game_id"), "meta": meta, "samples": p.samples, "stats": stats}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="players 目录（player_*/uuid 的父目录）")
    ap.add_argument("--cards", required=True, help="cards.json 路径")
    ap.add_argument("--out", required=True, help="bc_samples.jsonl.gz")
    ap.add_argument("--stats", required=True, help="bc_parse_stats.json")
    ap.add_argument("--workers", type=int, default=max(1, min(16, (os.cpu_count() or 4))))
    ap.add_argument("--limit", type=int, default=0, help="只解析前 N 局（调试）")
    args = ap.parse_args()

    with open(args.cards, "r", encoding="utf-8") as f:
        cdb = json.load(f)
    cmap = {c["id"]: c for c in cdb.get("cards", [])}

    games = []
    for pf in sorted(os.listdir(args.root)):
        pd = os.path.join(args.root, pf)
        if not os.path.isdir(pd):
            continue
        for gid in sorted(os.listdir(pd)):
            gd = os.path.join(pd, gid)
            if os.path.isdir(gd) and os.path.exists(os.path.join(gd, "events.jsonl.gz")):
                games.append(gd)
    if args.limit:
        games = games[: args.limit]
    if not games:
        print("no games found", file=sys.stderr)
        return 2

    print(f"games={len(games)} workers={args.workers}", file=sys.stderr)
    t0 = time.time()
    results = []
    tasks = [(args.root, g, cmap) for g in games]
    if args.workers <= 1:
        for i, task in enumerate(tasks):
            results.append(parse_game(task))
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(tasks)} {time.time()-t0:.0f}s", file=sys.stderr)
    else:
        with Pool(args.workers) as pool:
            for i, r in enumerate(pool.imap(parse_game, tasks, chunksize=2)):
                results.append(r)
                if (i + 1) % 50 == 0:
                    print(f"  {i+1}/{len(tasks)} {time.time()-t0:.0f}s", file=sys.stderr)

    # 汇总
    total_samples = 0
    errors = []
    act_counts = collections.Counter()
    turn_counts = collections.Counter()
    shopsize = collections.Counter()
    mentions = collections.Counter()
    unmatched = collections.Counter()
    counters = collections.Counter()
    per_game = []
    with gzip.open(args.out, "wt", encoding="utf-8", compresslevel=6) as fo:
        for r in results:
            if "error" in r:
                errors.append({"game_id": r.get("game_id"), "error": r["error"]})
                continue
            st = r.get("stats") or {}
            per_game.append(st.get("samples", 0))
            for k, v in (st.get("counters") or {}).items():
                counters[k] += v
            act_counts.update({k[4:]: v for k, v in (st.get("counters") or {}).items() if k.startswith("act_")})
            turn_counts.update(st.get("turn_sizes") or {})
            shopsize.update(st.get("shopsize_hist") or {})
            mentions.update(st.get("card_mentions") or {})
            unmatched.update(st.get("unmatched") or {})
            for s in r["samples"]:
                total_samples += 1
                fo.write(json.dumps(s, ensure_ascii=False, separators=(",", ":")) + "\n")

    exact = sum(c for cid, c in mentions.items() if cid in cmap)
    norm = sum(c for cid, c in mentions.items() if cid not in cmap and base_id(cid) in cmap)
    unmapped = sum(c for cid, c in mentions.items() if cid not in cmap and base_id(cid) not in cmap)
    unique_ids = len(mentions)
    unique_exact = sum(1 for cid in mentions if cid in cmap)
    unique_norm = sum(1 for cid in mentions if cid not in cmap and base_id(cid) in cmap)
    unique_unmapped = unique_ids - unique_exact - unique_norm

    # 每类动作的可映射数/不可映射数
    act_mappable = {}
    for at in ACTION_MAP:
        m = counters.get("map_" + at, 0)
        tot = act_counts.get(at, 0)
        act_mappable[at] = {
            "samples": tot,
            "mappable_slot": m,
            "index_expr": ACTION_MAP[at][0],
            "mappable": ACTION_MAP[at][1],
            "note": ACTION_MAP[at][2],
        }

    n = max(1, total_samples)
    stats = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {
            "root": args.root,
            "cards": args.cards,
            "card_db_count": len(cmap),
            "games_found": len(games),
            "games_parsed": len(per_game),
            "games_failed": len(errors),
        },
        "samples_total": total_samples,
        "per_game_samples": {
            "min": min(per_game) if per_game else 0,
            "max": max(per_game) if per_game else 0,
            "mean": round(sum(per_game) / len(per_game), 1) if per_game else 0,
            "total": sum(per_game),
        },
        "by_action_type": dict(act_counts.most_common()),
        "by_turn": {str(k): v for k, v in sorted(turn_counts.items())},
        "action_mapping": act_mappable,
        "coverage": {
            "shop_snapshot_ratio": round(counters.get("shop_nonempty", 0) / n, 4),
            "shop_size_hist": dict(sorted(shopsize.items())),
            "gold_missing_ratio": round(counters.get("gold_missing", 0) / n, 4),
            "tier_missing_ratio": round(counters.get("tier_missing", 0) / n, 4),
            "health_missing_ratio": round(counters.get("health_missing", 0) / n, 4),
            "board_empty_ratio": round(counters.get("board_empty", 0) / n, 4),
            "hand_empty_ratio": round(counters.get("hand_empty", 0) / n, 4),
            "mappable_action_ratio": round(counters.get("mappable_action", 0) / n, 4),
        },
        "card_mapping": {
            "mentions_total": sum(mentions.values()),
            "mentions_exact": exact,
            "mentions_normalized": norm,
            "mentions_unmapped": unmapped,
            "exact_ratio": round(exact / max(1, sum(mentions.values())), 4),
            "normalized_ratio": round((exact + norm) / max(1, sum(mentions.values())), 4),
            "unique_ids": unique_ids,
            "unique_exact": unique_exact,
            "unique_normalized": unique_norm,
            "unique_unmapped": unique_unmapped,
            "top_unmapped": unmatched.most_common(60),
        },
        "errors": errors[:50],
        "elapsed_s": round(time.time() - t0, 1),
    }
    with open(args.stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"samples={total_samples} games={len(per_game)} errors={len(errors)} out={args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
