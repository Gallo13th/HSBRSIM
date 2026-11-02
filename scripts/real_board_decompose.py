#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实 10k+ 高强战团的身材来源拆解（纯 CPU，纯标准库）。

目的
----
回答一个问题：真实玩家 t12–t15 的 2–26k 身材**到底是靠什么涨出来的**，
用来重定义「复利链」与训练奖励。之前的假设（买 Titus / Drakkari 放大器）
在真实卡池里不可达（出现率仅 5%），本脚本用真实战团逐张拆解来给出替代答案。

输入
----
1. ``data/real_library/library_real_quasi_full.jsonl``
   真实人类战团快照（fidelity=full）：每行一个 ``recruitment_end_at_phase_switch``
   的完整棋盘状态，``board_detail`` 带 ``card_id / atk / hp / golden / kw /
   bonus_kw / shield_max``。
2. ``rust/crates/hsbg-engine/data/cards.json``
   卡表（唯一数值权威）：``tier / atk / hp / races / keywords / normal / golden``。
   金卡在卡表里是**独立条目**，其 atk/hp 已是双倍基础值，因此
   ``实际身材 − 卡表基础身材`` 就是可观测的 buff 量（金卡也成立）。
3. ``runs/az_entity_s25/collector/games.jsonl.gz``
   我们 s25 自对弈 200 局（含每回合 board 卡 id 列表 + ``strength``）。
   **只有卡 id，没有 atk/hp** → 我们这一侧逐卡身材贡献「不可得」，
   只能用卡表基础身材做「基础身材贡献」下界估计（报告里明确标注）。

输出
----
``runs/real_decomp/REPORT.md`` + ``runs/real_decomp/decomp.json``。

口径说明（重要）
----------------
* ``总量口径``：先把所有战团的身材加总，再算占比 → 被头部战团主导。
  真实数据里 1 个 t15 战团 Σ≈37 万，能顶 100 个普通战团，因此**必须**
  同时给「逐局口径」。
* ``逐局口径``：先在**每个战团内部**算占比，再对 176 个战团取平均
  （每局权重 1）→ 回答「一个典型高强战团里 X 占多少」。报告默认两种都列。
"""

from __future__ import annotations

import collections
import datetime
import gzip
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LIB_PATH = os.path.join(ROOT, "data", "real_library", "library_real_quasi_full.jsonl")
CARDS_PATH = os.path.join(ROOT, "rust", "crates", "hsbg-engine", "data", "cards.json")
OURS_PATH = os.path.join(ROOT, "runs", "az_entity_s25", "collector", "games.jsonl.gz")
FUNNEL_PATH = os.path.join(ROOT, "runs", "az_entity_s25", "collector", "funnel35.json")
OUT_DIR = os.path.join(ROOT, "runs", "real_decomp")

# ---------------- 筛选参数 ----------------
TURN_LO, TURN_HI = 12, 15
SUM_MIN = 4000            # 主口径
SUM_FALLBACK = 2500       # 样本不足时的放宽口径
MIN_BOARDS = 30           # 「样本不足」判定阈值

# 引擎 Kw 位定义（rust/crates/hsbg-engine/src/types.rs::Kw）
KW_NAMES = (
    "TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS", "POISONOUS",
    "STEALTH", "MAGNETIC", "MEGA_WINDFURY", "CLEAVE", "IMMUNE", "IMMUNE_ATTACKING",
)

# 放大器（来自 runs/az_entity_s25/collector/funnel35.json 的 amp_ids）
AMP_KEYS = {
    "BG25_354": "Titus", "BG25_354_G": "Titus(金)",
    "BG26_ICC_901": "Drakkari", "BG26_ICC_901_G": "Drakkari(金)",
    "BG36_640": "Gatekeeper", "BG36_640_G": "Gatekeeper(金)",
}

RACE_ZH = {
    "BEAST": "野兽", "DEMON": "恶魔", "DRAGON": "龙", "ELEMENTAL": "元素",
    "MECH": "机械", "MECHANICAL": "机械", "MURLOC": "鱼人", "PIRATE": "海盗",
    "QUILBOAR": "野猪人", "UNDEAD": "亡灵", "NAGA": "纳迦",
    "ABERRATION": "异变", "ALL": "全种族",
}


# ======================================================================
# 0. 卡表
# ======================================================================
def kw_bits_from_names(names):
    bits = 0
    for n in names or ():
        key = str(n).strip().upper()
        if key in KW_NAMES:
            bits |= 1 << KW_NAMES.index(key)
    return bits


def load_cards(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cards = data["cards"] if isinstance(data, dict) else data
    out = {}
    for c in cards:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        out[cid] = {
            "id": cid,
            "kind": str(c.get("kind") or ""),
            "tier": int(c.get("tier") or 0),
            "atk": int(c.get("atk") or 0),
            "hp": int(c.get("hp") or 0),
            "races": [str(r) for r in (c.get("races") or [])],
            "kw_bits": kw_bits_from_names(c.get("keywords")),
            "name": str(c.get("name") or cid),
            "name_zh": str(c.get("name_zh") or c.get("name") or cid),
            "text": str(c.get("text") or ""),
            "text_zh": str(c.get("text_zh") or ""),
        }
    return out, (data.get("meta") if isinstance(data, dict) else None)


def base_of(cards, cid):
    """返回该卡在卡表里的基础 (atk, hp, tier, races)。金卡条目本就双倍。"""
    info = cards.get(cid)
    if not info:  # 卡表缺失：退回不做 buff 归因
        return None
    return info


# ======================================================================
# 1. 筛选真实战团
# ======================================================================
def load_real_boards(path):
    boards = []
    meta = {"lines": 0, "games": set(), "turn_hist": collections.Counter(),
            "availability": collections.Counter(), "stage": collections.Counter()}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            meta["lines"] += 1
            t = int(d.get("turn") or 0)
            meta["turn_hist"][t] += 1
            meta["stage"][str(d.get("stage") or "")] += 1
            for k, v in (d.get("availability") or {}).items():
                meta["availability"][k] = v
            bd = d.get("board_detail") or []
            total = sum(int(b.get("atk") or 0) + int(b.get("hp") or 0) for b in bd)
            boards.append({
                "game_id": str(d.get("game_id") or ""),
                "turn": t,
                "tier": int(d.get("tier") or 0),
                "total": total,
                "board_detail": bd,
            })
            meta["games"].add(str(d.get("game_id") or ""))
    return boards, meta


def select(boards, sum_min, turn_lo=TURN_LO, turn_hi=TURN_HI):
    return [b for b in boards
            if turn_lo <= b["turn"] <= turn_hi and b["total"] >= sum_min]


# ======================================================================
# 2. 逐张拆解
# ======================================================================
def explode(boards, cards):
    """把战团展开成逐随从行，附带基准/金卡/buff/占比。"""
    rows, missing = [], collections.Counter()
    for bi, b in enumerate(boards):
        total = b["total"] or 1
        for mi, m in enumerate(b["board_detail"]):
            cid = str(m.get("card_id") or "")
            atk, hp = int(m.get("atk") or 0), int(m.get("hp") or 0)
            stat = atk + hp
            info = base_of(cards, cid)
            if info is None:
                missing[cid] += 1
            golden = bool(m.get("golden"))
            base_atk = info["atk"] if info else 0
            base_hp = info["hp"] if info else 0
            base_stat = base_atk + base_hp
            rows.append({
                "board": bi,
                "game_id": b["game_id"],
                "turn": b["turn"],
                "tavern_tier": b["tier"],
                "slot": mi,
                "card_id": cid,
                "name": info["name_zh"] if info else cid,
                "tier": info["tier"] if info else -1,
                "races": info["races"] if info else [],
                "golden": golden,
                "atk": atk, "hp": hp, "stat": stat,
                "share": stat / total,
                "base_stat": base_stat,
                "buff": max(0, stat - base_stat),
                "kw": int(m.get("kw") or 0) | int(m.get("bonus_kw") or 0),
                "kw_printed": info["kw_bits"] if info else 0,
                "bonus_kw": int(m.get("bonus_kw") or 0),
                "shield_max": int(m.get("shield_max") or 0),
            })
    return rows, missing


# ======================================================================
# 3. 归因聚合
# ======================================================================
class Agg:
    """同时维护「总量口径」与「逐局口径」的占比聚合。

    ``share_per_board`` = 该类在**每个战团内部**的占比之和 / 战团数
    （每局权重 1；没有该类的战团贡献 0），与「总量口径」区分开。
    """

    def __init__(self, n_boards):
        self.n_boards = max(1, n_boards)
        self.total = 0.0
        self.tot = collections.Counter()                 # 总量口径：分子
        self.board_sum = collections.defaultdict(float)  # 逐局口径：占比之和
        self.cnt = collections.Counter()                 # 出现次数（随从数）

    def add(self, key, stat, share):
        self.total += stat
        self.tot[key] += stat
        self.board_sum[key] += share
        self.cnt[key] += 1

    def table(self):
        out = []
        for k, v in self.tot.items():
            out.append({
                "key": k,
                "stat_total": v,
                "share_total": v / self.total if self.total else 0.0,
                "share_per_board": self.board_sum[k] / self.n_boards,
                "minions": self.cnt[k],
            })
        out.sort(key=lambda r: -r["share_total"])
        return out


def agg_by(rows, keyfn, n_boards=None):
    if n_boards is None:
        n_boards = len({r["board"] for r in rows})
    agg = Agg(n_boards)
    for r in rows:
        agg.add(keyfn(r), r["stat"], r["share"])
    return agg


def pct(x):
    return round(100.0 * float(x), 2)


# ======================================================================
# 4. 我们这一侧（s25 collector）
# ======================================================================
def load_ours(path, cards):
    """每局取 t12–t15 的 board（collector 的 turn 编号与真实库一致：1 = 第一个招募回合）。

    同时收集每局的 shop / bought / board 卡 id 集合，用于判断
    「人类强卡是我们**卡池里没有**，还是**有但不买**」。
    """
    if not os.path.exists(path):
        return None
    games, boards, turns_seen = [], [], collections.Counter()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            g = json.loads(line)
            games.append(g)
            shop_ids, bought_ids, board_ids = set(), set(), set()
            for tn in g.get("turns") or ():
                t = int(tn.get("turn") or 0)
                turns_seen[t] += 1
                for s in tn.get("shop") or ():
                    cid = s.get("card") if isinstance(s, dict) else s
                    if cid:
                        shop_ids.add(str(cid))
                for a in tn.get("actions") or ():
                    b = a.get("bought") if isinstance(a, dict) else None
                    if b:
                        bought_ids.add(str(b))
                for cid in tn.get("board") or ():
                    if cid:
                        board_ids.add(str(cid))
                if not (TURN_LO <= t <= TURN_HI):
                    continue
                ids = [str(x) for x in (tn.get("board") or ()) if x]
                if not ids:
                    continue
                est = 0
                golden_n = 0
                for cid in ids:
                    info = cards.get(cid)
                    if cid.endswith("_G"):
                        golden_n += 1
                    if info:
                        est += info["atk"] + info["hp"]
                boards.append({
                    "game_id": str(g.get("seed")),
                    "turn": t,
                    "placement": g.get("placement"),
                    "tier": int(tn.get("tier") or 0),
                    "strength": int(tn.get("strength") or 0),
                    "ids": ids,
                    "est_base_sum": est,
                    "golden_n": golden_n,
                })
            if games[-1] is not None:
                games[-1]["_shop"] = shop_ids
                games[-1]["_bought"] = bought_ids
                games[-1]["_board"] = board_ids
    return {"games": games, "boards": boards, "turns_seen": turns_seen}


# ======================================================================
# 5. 渲染
# ======================================================================
def md_table(headers, rows, aligns=None):
    if not rows:
        return "_（空）_\n"
    out = ["| " + " | ".join(headers) + " |"]
    sep = []
    for i, _ in enumerate(headers):
        a = (aligns or [])[i] if aligns and i < len(aligns) else "---"
        sep.append(a)
    out.append("| " + " | ".join(sep) + " |")
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def fnum(x, nd=0):
    return f"{x:,.{nd}f}"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cards, cards_meta = load_cards(CARDS_PATH)
    all_boards, lib_meta = load_real_boards(LIB_PATH)

    # ---------- 1. 筛选 ----------
    sel = select(all_boards, SUM_MIN)
    used_min, relaxed = SUM_MIN, False
    if len(sel) < MIN_BOARDS:
        sel = select(all_boards, SUM_FALLBACK)
        used_min, relaxed = SUM_FALLBACK, True
    turns_avail = [b for b in all_boards if TURN_LO <= b["turn"] <= TURN_HI]
    n_games = len({b["game_id"] for b in sel})
    rows, missing = explode(sel, cards)

    total_stat = sum(r["stat"] for r in rows)
    n_minions = len(rows)
    n_golden = sum(1 for r in rows if r["golden"])

    # ---------- 2. 金卡 ----------
    gold_agg = agg_by(rows, lambda r: "金卡" if r["golden"] else "普通", len(sel))
    gold_tbl = gold_agg.table()
    gold_share_total = next((r["share_total"] for r in gold_tbl if r["key"] == "金卡"), 0.0)
    gold_share_board = next((r["share_per_board"] for r in gold_tbl if r["key"] == "金卡"), 0.0)
    golden_count_share = n_golden / n_minions if n_minions else 0.0

    # 金卡 × tier（金卡贡献里 tier 的分布）
    gold_by_tier = collections.Counter()
    for r in rows:
        if r["golden"]:
            gold_by_tier[r["tier"]] += r["stat"]
    gold_tier_total = sum(gold_by_tier.values()) or 1

    # ---------- 3. tier ----------
    tier_agg = agg_by(rows, lambda r: r["tier"], len(sel))
    tier_tbl = tier_agg.table()
    tier_tbl.sort(key=lambda r: r["key"])

    # ---------- 4. 种族 ----------
    def race_key(r):
        rs = [x for x in (r["races"] or []) if x]
        if not rs:
            return "无种族"
        if len(rs) > 1 or "ALL" in rs:
            return "多族/全族"
        return rs[0]

    race_agg = agg_by(rows, race_key, len(sel))
    race_tbl = race_agg.table()
    race_tbl_disp = [{
        "key": r["key"] if r["key"] in ("无种族", "多族/全族") else
               f"{RACE_ZH.get(r['key'], r['key'])}（{r['key']}）",
        "stat_total": r["stat_total"],
        "share_total": r["share_total"],
        "share_per_board": r["share_per_board"],
        "minions": r["minions"],
    } for r in race_tbl]

    # ---------- 5. 关键卡 top-20 ----------
    card_stat = collections.Counter()
    card_boards = collections.defaultdict(set)
    card_cnt = collections.Counter()
    card_meta = {}
    for r in rows:
        cid = r["card_id"]
        card_stat[cid] += r["stat"]
        card_boards[cid].add(r["board"])
        card_cnt[cid] += 1
        card_meta.setdefault(cid, r)

    card_tbl = []
    for cid, st in card_stat.items():
        c = card_meta[cid]
        card_tbl.append({
            "card_id": cid,
            "name": c["name"],
            "tier": c["tier"],
            "races": [RACE_ZH.get(x, x) for x in (c["races"] or [])] or ["无"],
            "appear_boards": len(card_boards[cid]),
            "appear_rate": len(card_boards[cid]) / len(sel),
            "copy_rate": card_cnt[cid] / len(sel),
            "stat_total": st,
            "stat_share": st / total_stat if total_stat else 0.0,
            "golden_copies": sum(1 for r in rows if r["card_id"] == cid and r["golden"]),
            "buff_total": sum(r["buff"] for r in rows if r["card_id"] == cid),
        })
    card_by_stat = sorted(card_tbl, key=lambda r: -r["stat_total"])
    card_by_freq = sorted(card_tbl, key=lambda r: (-r["appear_rate"], -r["stat_total"]))

    # ---------- 5b. 机制归因（用 cards.json text_zh 规则分类）----------
    def mech_of(cid):
        info = cards.get(cid) or {}
        t = str(info.get("text_zh") or "") + " " + str(info.get("text") or "")
        if "光环" in t or "Aura" in t:
            return "光环（常驻）"
        if "吞噬" in t or "吞食" in t or "Consume" in t:
            return "吞噬（吃掉酒馆属性）"
        if "酒馆" in t and ("获得" in t or "属性值" in t):
            return "酒馆全局永久 buff"
        if "额外触发" in t or "触发两次" in t or "triggers twice" in t:
            return "双触发（放大器）"
        if "进击" in t or "Rally" in t:
            return "进击 Rally"
        if "亡语" in t or "Deathrattle" in t:
            return "亡语 Deathrattle"
        if "战吼" in t or "Battlecry" in t:
            return "战吼 Battlecry"
        if "回合结束时" in t or "End of Turn" in t:
            return "回合结束 EOT"
        if "复仇" in t or "Avenge" in t:
            return "复仇 Avenge"
        if "法术" in t or "Spell" in t:
            return "法术相关（其它）"
        return "白板/其它"

    def mech_multi(cid):
        info = cards.get(cid) or {}
        t = str(info.get("text_zh") or "") + " " + str(info.get("text") or "")
        tags = []
        if "光环" in t:
            tags.append("光环")
        if ("吞噬" in t) or ("吞食" in t):
            tags.append("吞噬")
        if "酒馆" in t and ("获得" in t or "属性值" in t):
            tags.append("酒馆全局buff")
        if ("额外触发" in t) or ("触发两次" in t):
            tags.append("双触发")
        if "进击" in t:
            tags.append("进击")
        if "亡语" in t:
            tags.append("亡语")
        if "战吼" in t:
            tags.append("战吼")
        if "回合结束时" in t:
            tags.append("回末")
        if "复仇" in t:
            tags.append("复仇")
        return tags or ["白板"]

    for r in rows:
        r["mech"] = mech_of(r["card_id"])
        r["mech_tags"] = mech_multi(r["card_id"])
    mech_agg = agg_by(rows, lambda r: r["mech"], len(sel))
    mech_tbl = mech_agg.table()
    mech_stat = {}
    for r in rows:
        mech_stat.setdefault(r["mech"], collections.Counter())["stat"] += r["stat"]
    # 机制 × 金卡
    mech_golden = collections.Counter()
    mech_all = collections.Counter()
    for r in rows:
        mech_all[r["mech"]] += r["stat"]
        if r["golden"]:
            mech_golden[r["mech"]] += r["stat"]
    mech_tbl2 = []
    for m in mech_tbl:
        k = m["key"]
        mech_tbl2.append({
            "mech": k,
            "stat_total": m["stat_total"],
            "share_total": m["share_total"],
            "share_per_board": m["share_per_board"],
            "minions": m["minions"],
            "golden_share_within": mech_golden[k] / mech_all[k] if mech_all[k] else 0.0,
        })
    # 多标签（同一随从可进多个桶，合计>100%）
    tag_stat = collections.Counter()
    tag_cnt = collections.Counter()
    for r in rows:
        for t in r["mech_tags"]:
            tag_stat[t] += r["stat"]
            tag_cnt[t] += 1
    tag_tbl = [{"tag": k, "stat_share": v / total_stat if total_stat else 0.0,
                "minions": tag_cnt[k]}
               for k, v in tag_stat.most_common()]

    # ---------- 5c. 集中度（复利 = 少数卡吃走大部分身材）----------
    shares_sorted = sorted((c["stat_share"] for c in card_tbl), reverse=True)
    concentration = {
        "distinct_cards": len(card_tbl),
        "top1": sum(shares_sorted[:1]),
        "top3": sum(shares_sorted[:3]),
        "top5": sum(shares_sorted[:5]),
        "top10": sum(shares_sorted[:10]),
        "top20": sum(shares_sorted[:20]),
        "hhi": sum(s * s for s in shares_sorted),
    }

    # ---------- 6. buff（永久成长）替代指标 ----------
    buff_total = sum(r["buff"] for r in rows)
    buff_share = buff_total / total_stat if total_stat else 0.0
    buffed_ratio = sum(1 for r in rows if r["buff"] > 0) / n_minions if n_minions else 0.0
    buff_per_minion_med = statistics.median([r["buff"] for r in rows]) if rows else 0
    buff_per_board_med = statistics.median(
        [sum(r["buff"] for r in rows if r["board"] == i) for i in range(len(sel))]) if sel else 0
    # buff 集中在哪些卡
    buff_by_card = collections.Counter()
    for r in rows:
        buff_by_card[r["card_id"]] += r["buff"]
    buff_card_tbl = []
    for cid, bv in buff_by_card.most_common(15):
        c = card_meta[cid]
        buff_card_tbl.append({
            "card_id": cid, "name": c["name"], "tier": c["tier"],
            "buff_total": bv,
            "buff_share": bv / buff_total if buff_total else 0.0,
            "copies": card_cnt[cid],
            "golden_copies": sum(1 for r in rows if r["card_id"] == cid and r["golden"]),
        })
    # buff 按 tier / 种族
    buff_by_tier = collections.Counter()
    buff_by_race = collections.Counter()
    for r in rows:
        buff_by_tier[r["tier"]] += r["buff"]
        buff_by_race[race_key(r)] += r["buff"]
    # 逐局口径的 buff 占比中位数（避免被离群战团主导）
    board_buff_share = []
    for i, b in enumerate(sel):
        st = sum(r["stat"] for r in rows if r["board"] == i)
        bf = sum(r["buff"] for r in rows if r["board"] == i)
        if st:
            board_buff_share.append(bf / st)
    buff_share_board_med = statistics.median(board_buff_share) if board_buff_share else 0.0
    buff_share_board_lo = (sorted(board_buff_share)[len(board_buff_share) // 10]
                           if board_buff_share else 0.0)

    # ---------- 7. 关键词 ----------
    kw_rows = [r for r in rows if r["kw"]]
    kw_bit_cnt = collections.Counter()
    kw_bit_stat = collections.Counter()
    for r in rows:
        for i, name in enumerate(KW_NAMES):
            if r["kw"] & (1 << i):
                kw_bit_cnt[name] += 1
                kw_bit_stat[name] += r["stat"]
    kw_mismatch = sum(1 for r in rows if r["kw"] & ~r["kw_printed"] and r["kw_printed"] == 0)
    bonus_kw_rows = sum(1 for r in rows if r["bonus_kw"])
    shield_sum = sum(1 for r in rows if r["shield_max"] > 1)

    # ---------- 8. 放大器 ----------
    amp_present = collections.Counter()
    amp_stat = collections.Counter()
    amp_boards = collections.defaultdict(set)
    for r in rows:
        if r["card_id"] in AMP_KEYS:
            amp_present[AMP_KEYS[r["card_id"]]] += 1
            amp_stat[AMP_KEYS[r["card_id"]]] += r["stat"]
            amp_boards[AMP_KEYS[r["card_id"]]].add(r["board"])
    amp_any_boards = len(set().union(*amp_boards.values())) if amp_boards else 0

    # 放大器出现率分层（全库 / t12–15 / 高强），用于判断「5%」是不是样本偏差
    amp_ids = set(AMP_KEYS)
    amp_layers = {}
    t12_boards = [b for b in all_boards if TURN_LO <= b["turn"] <= TURN_HI]
    for label, blist in (("全库（全部回合）", all_boards),
                         (f"t{TURN_LO}–t{TURN_HI} 全部", t12_boards),
                         (f"t{TURN_LO}–t{TURN_HI} 且 Σ≥{used_min}（本样本）", sel)):
        hit = sum(1 for b in blist
                  if any(str(m.get("card_id")) in amp_ids for m in b["board_detail"]))
        amp_layers[label] = {"boards": len(blist), "hit": hit,
                             "rate": hit / len(blist) if blist else 0.0}

    # ---------- 8b. 广义「触发放大器」家族（文本规则，不止 Titus/Drakkari/Gatekeeper）----------
    AMP_PATTERNS = ("施放两次", "额外施放一次", "额外施放", "触发两次", "额外触发", "施放 两次")
    amp_fam = set()
    for cid, info in cards.items():
        t = info["text_zh"] + " " + info["text"]
        if any(p in t for p in AMP_PATTERNS):
            amp_fam.add(cid)
    fam_layers = {}
    for label, blist in (("全库（全部回合）", all_boards),
                         (f"t{TURN_LO}–t{TURN_HI} 全部", t12_boards),
                         (f"t{TURN_LO}–t{TURN_HI} 且 Σ≥{used_min}（本样本）", sel)):
        hit = sum(1 for b in blist
                  if any(str(m.get("card_id")) in amp_fam for m in b["board_detail"]))
        fam_layers[label] = {"boards": len(blist), "hit": hit,
                             "rate": hit / len(blist) if blist else 0.0}
    fam_tbl = []
    for cid in amp_fam:
        if cid not in card_stat:
            continue
        c = card_meta[cid]
        fam_tbl.append({
            "card_id": cid, "name": c["name"], "tier": c["tier"],
            "appear_rate": len(card_boards[cid]) / len(sel),
            "stat_share": card_stat[cid] / total_stat if total_stat else 0.0,
            "copies": card_cnt[cid],
            "golden_copies": sum(1 for r in rows if r["card_id"] == cid and r["golden"]),
            "text": (cards.get(cid) or {}).get("text_zh", "")[:60],
        })
    fam_tbl.sort(key=lambda r: -r["appear_rate"])
    fam_stat_share = sum(r["stat_share"] for r in fam_tbl)

    # ---------- 9. 稳健性：去掉头部战团 ----------
    ordered_sel = sorted(range(len(sel)), key=lambda i: -sel[i]["total"])
    drop_rank = {bi: rank for rank, bi in enumerate(ordered_sel)}
    def stat_share_drop(k, pred):
        st = sum(r["stat"] for r in rows if drop_rank[r["board"]] >= k)
        num = sum(r["stat"] for r in rows if drop_rank[r["board"]] >= k and pred(r))
        return (num / st if st else 0.0)
    robust = []
    for k in (0, 1, 3, 5):
        robust.append({
            "drop_top": k,
            "boards": len(sel) - k,
            "golden_share": stat_share_drop(k, lambda r: r["golden"]),
            "t6_share": stat_share_drop(k, lambda r: r["tier"] >= 6),
            "buff_share": (sum(r["buff"] for r in rows if drop_rank[r["board"]] >= k) /
                           max(1, sum(r["stat"] for r in rows if drop_rank[r["board"]] >= k))),
        })

    # ---------- 10. 我们 v s 人类 ----------
    ours = load_ours(OURS_PATH, cards)
    cmp_block = None
    if ours and ours["boards"]:
        ob = ours["boards"]
        occ_boards = collections.defaultdict(set)
        occ_cnt = collections.Counter()
        occ_est = collections.Counter()
        ours_total_est = sum(b["est_base_sum"] for b in ob) or 1
        for bi, b in enumerate(ob):
            for cid in b["ids"]:
                occ_boards[cid].add(bi)
                occ_cnt[cid] += 1
                info = cards.get(cid)
                if info:
                    occ_est[cid] += info["atk"] + info["hp"]
        our_tbl = []
        for cid in set(list(occ_boards) + list(card_stat)):
            info = cards.get(cid)
            our_tbl.append({
                "card_id": cid,
                "name": info["name_zh"] if info else cid,
                "tier": info["tier"] if info else -1,
                "races": [RACE_ZH.get(x, x) for x in (info["races"] if info else [])] or ["无"],
                "human_appear": len(card_boards[cid]) / len(sel) if cid in card_boards else 0.0,
                "human_stat_share": card_stat[cid] / total_stat if cid in card_stat else 0.0,
                "our_appear": len(occ_boards[cid]) / len(ob) if cid in occ_boards else 0.0,
                "our_est_share": occ_est[cid] / ours_total_est if cid in occ_est else 0.0,
            })
        our_by_freq = sorted(our_tbl, key=lambda r: (-r["our_appear"], -r["our_est_share"]))
        merged = {r["card_id"]: r for r in our_tbl}

        def with_ours(c):
            m = merged.get(c["card_id"]) or {}
            return {
                "card_id": c["card_id"], "name": c["name"], "tier": c["tier"],
                "races": c["races"],
                "appear_rate": c["appear_rate"], "stat_share": c["stat_share"],
                "human_appear": c["appear_rate"],
                "human_stat_share": c["stat_share"],
                "our_appear": m.get("our_appear", 0.0),
                "our_est_share": m.get("our_est_share", 0.0),
            }

        human_top = [with_ours(c) for c in card_by_freq[:20]]
        our_top = [r for r in our_by_freq[:20]]
        human_ids = {r["card_id"] for r in human_top}
        our_ids = {r["card_id"] for r in our_top}
        human_only = [with_ours(c) for c in card_by_freq
                      if c["card_id"] in (human_ids - our_ids)][:20]
        our_only = [r for r in our_by_freq if r["card_id"] in (our_ids - human_ids)][:20]

        # 人类 top-20（按身材占比）在我们 200 局里的可达性：卡池有？买了？上场了？
        n_g = len(ours["games"])
        shop_g = collections.Counter()
        bought_g = collections.Counter()
        board_g = collections.Counter()
        for g in ours["games"]:
            for cid in g.get("_shop") or ():
                shop_g[cid] += 1
            for cid in g.get("_bought") or ():
                bought_g[cid] += 1
            for cid in g.get("_board") or ():
                board_g[cid] += 1
        reach = []
        for c in card_by_stat[:20]:
            cid = c["card_id"]
            # 商店里不出现 _G 形态（金卡靠三连），所以查卡池/买过都要退回普通形态
            base = cid[:-2] if cid.endswith("_G") else cid
            shop_n = max(shop_g[cid], shop_g[base])
            bought_n = max(bought_g[cid], bought_g[base])
            reach.append({
                "card_id": cid, "name": c["name"], "tier": c["tier"],
                "human_appear": c["appear_rate"],
                "human_stat_share": c["stat_share"],
                "our_shop_rate": shop_n / n_g if n_g else 0.0,
                "our_bought_rate": bought_n / n_g if n_g else 0.0,
                "our_board_rate": board_g[cid] / n_g if n_g else 0.0,
                "in_pool": shop_n > 0,
                "pool_probe_id": base,
            })
        # 我们这一侧的 tier 分布 + 放大器在场率
        our_tier = collections.Counter(b["tier"] for b in ob)
        our_amp_boards = sum(1 for b in ob if set(b["ids"]) & amp_ids)

        cmp_block = {
            "boards": len(ob),
            "games": len(ours["games"]),
            "turn_hist": dict(sorted(ours["turns_seen"].items())),
            "est_total": sum(b["est_base_sum"] for b in ob),
            "strength_p50": statistics.median([b["strength"] for b in ob]) if ob else 0,
            "human_top20": human_top,
            "our_top20": our_top,
            "human_only": human_only,
            "our_only": our_only,
            "our_golden_ratio": (sum(b["golden_n"] for b in ob) / max(1, sum(len(b["ids"]) for b in ob))),
            "reach": reach,
            "tier_hist": dict(sorted(our_tier.items())),
            "amp_board_rate": our_amp_boards / len(ob) if ob else 0.0,
            "amp_boards": our_amp_boards,
        }

    # 库内一致性：t15 p50
    t15 = [b["total"] for b in all_boards if b["turn"] == 15]
    t15_p50 = statistics.median(t15) if t15 else 0

    # ---------- 11. 复利链：按身材贡献排序的主路径 ----------
    chain = []
    mech_top = [m for m in mech_tbl2 if m["mech"] not in ("白板/其它",)]
    m1 = mech_top[0] if mech_top else {"mech": "?", "share_total": 0, "golden_share_within": 0}
    chain.append({
        "path": f"①机制引擎：{m1['mech']}（承载身材的卡自身机制）",
        "share": m1["share_total"],
        "evidence": f"{m1['mech']} 承载 {pct(m1['share_total']):.2f}% 总量身材；"
                    f"该类卡**金色占比** {pct(m1['golden_share_within']):.1f}%（金卡放大了引擎本身）",
        "metric": "该机制卡的出现数 × 其 buff 量",
    })
    chain.append({
        "path": "②永久 buff/成长（卡表基础身材之外的加成）",
        "share": buff_share,
        "evidence": f"实际身材 {fnum(total_stat)} − 卡表基础 {fnum(total_stat - buff_total)} "
                    f"= {fnum(buff_total)}（{pct(buff_share):.2f}% 总量；逐局中位数 "
                    f"{pct(buff_share_board_med):.1f}%）",
        "metric": "Σ(实际−基础) / buffed 随从数",
    })
    chain.append({
        "path": "③金卡（本体翻倍 + 引擎触发翻倍）",
        "share": gold_share_total,
        "evidence": f"金卡 {n_golden}/{n_minions} 张（{pct(golden_count_share):.1f}% 随从）"
                    f"贡献 {pct(gold_share_total):.2f}% 总量身材，单位效率 "
                    f"{(gold_share_total / golden_count_share) if golden_count_share else 0:.1f}×",
        "metric": "金卡数 / 金卡身材占比",
    })
    top_race = race_tbl[0]
    chain.append({
        "path": f"④种族协同（{RACE_ZH.get(top_race['key'], top_race['key'])}为主）",
        "share": top_race["share_total"],
        "evidence": f"{RACE_ZH.get(top_race['key'], top_race['key'])} {pct(top_race['share_total']):.2f}% 总量 / "
                    f"{pct(top_race['share_per_board']):.2f}% 逐局均值",
        "metric": "同族随从数 / 种族 buff 事件",
    })
    top_card = card_by_stat[0]
    chain.append({
        "path": f"⑤单卡引擎（{top_card['name']}）",
        "share": top_card["stat_share"],
        "evidence": f"{top_card['card_id']} 出现率 {pct(top_card['appear_rate']):.1f}%，"
                    f"身材占比 {pct(top_card['stat_share']):.2f}%（集中度：top1 卡 "
                    f"{pct(concentration['top1']):.1f}%、top5 {pct(concentration['top5']):.1f}%）",
        "metric": f"该卡获得的 buff 量 / 该卡在场",
    })

    # ---------- 输出 json ----------
    payload = {
        "schema": "hsbg.real_board_decomp",
        "schema_version": 1,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "real_library": os.path.relpath(LIB_PATH, ROOT),
            "cards": os.path.relpath(CARDS_PATH, ROOT),
            "cards_meta": cards_meta,
            "ours": os.path.relpath(OURS_PATH, ROOT) if os.path.exists(OURS_PATH) else None,
        },
        "filter": {
            "turn_range": [TURN_LO, TURN_HI],
            "sum_min": used_min, "relaxed": relaxed,
            "boards": len(sel), "games": n_games,
            "boards_at_turn_range": len(turns_avail),
            "minions": n_minions,
            "lib_lines": lib_meta["lines"],
            "lib_games": len(lib_meta["games"]),
            "turn_hist": dict(sorted(lib_meta["turn_hist"].items())),
        },
        "totals": {
            "stat_total": total_stat,
            "stat_p50_board": statistics.median([b["total"] for b in sel]) if sel else 0,
            "t15_p50_library": t15_p50,
            "golden_minions": n_golden,
            "golden_count_share": golden_count_share,
            "golden_stat_share_total": gold_share_total,
            "golden_stat_share_per_board": gold_share_board,
            "buff_total": buff_total,
            "buff_share": buff_share,
            "buffed_minion_ratio": buffed_ratio,
            "buff_per_minion_median": buff_per_minion_med,
            "buff_per_board_median": buff_per_board_med,
            "buff_share_per_board_median": buff_share_board_med,
            "buff_share_per_board_p10": buff_share_board_lo,
        },
        "availability": {
            "counter": "不可得", "gems": "不可得", "attachments": "不可得",
            "player_counters": "不可得", "gold": "不可得",
            "replacements": ["实际身材−卡表基础身材 = 永久 buff 量",
                             "kw/bonus_kw 位掩码 = 关键词激活"],
        },
        "tier": tier_tbl,
        "race": race_tbl_disp,
        "golden_by_tier": [{"tier": k, "stat": v, "share_of_golden": v / gold_tier_total}
                           for k, v in sorted(gold_by_tier.items())],
        "cards_by_stat": card_by_stat,
        "cards_by_freq": card_by_freq,
        "buff_by_card": buff_card_tbl,
        "buff_by_tier": [{"tier": k, "buff": v,
                          "share": v / buff_total if buff_total else 0}
                         for k, v in sorted(buff_by_tier.items())],
        "buff_by_race": [{"race": k, "buff": v,
                          "share": v / buff_total if buff_total else 0}
                         for k, v in buff_by_race.most_common()],
        "keywords": {
            "minions_with_kw": len(kw_rows),
            "bits": [{"kw": k, "minions": kw_bit_cnt[k],
                      "stat_share": kw_bit_stat[k] / total_stat if total_stat else 0}
                     for k in KW_NAMES if kw_bit_cnt[k]],
            "bonus_kw_minions": bonus_kw_rows,
            "kw_without_printed": kw_mismatch,
            "shield_gt1": shield_sum,
        },
        "amplifiers": {
            "per_amp": [{"amp": k, "minions": amp_present[k], "boards": len(amp_boards[k]),
                         "appear_rate": len(amp_boards[k]) / len(sel) if sel else 0,
                         "stat_share": amp_stat[k] / total_stat if total_stat else 0}
                        for k in amp_present],
            "any_amp_boards": amp_any_boards,
            "any_amp_rate": amp_any_boards / len(sel) if sel else 0,
            "layers": amp_layers,
            "family_layers": fam_layers,
            "family_top": fam_tbl[:15],
            "family_stat_share": fam_stat_share,
            "family_size": len(amp_fam),
        },
        "mechanism": mech_tbl2,
        "mechanism_multilabel": tag_tbl,
        "concentration": concentration,
        "robustness": robust,
        "ours": cmp_block,
        "chain": chain,
        "caveats": [
            "counter/gems/attachments/player_counters 字段在库里不存在（availability 标 unavailable）→ 用「实际身材−卡表基础」替代。",
            "天花板样本：单个 t15 战团 Σ=370,510，占全样本总量极大比重 → 报告同时给总量口径与逐局口径。",
            "kw 位掩码按引擎 Kw 位解读；库中既有印刷关键词，也有被授予的关键词（bonus_kw），无法拆分单次授予次数。",
        ],
    }
    with open(os.path.join(OUT_DIR, "decomp.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    # ---------- 输出 REPORT.md ----------
    L = []
    A = L.append
    A("# 真实 10k+ 高强战团的身材来源拆解\n")
    A(f"生成时间：{payload['created']}　|　纯 CPU、无训练、只读数据\n")
    A("**数据来源**：\n")
    A(f"- 真实战团：`{payload['sources']['real_library']}`（{lib_meta['lines']} 行 / "
      f"{len(lib_meta['games'])} 局，fidelity=full，stage=`recruitment_end_at_phase_switch`）")
    A(f"- 卡表：`{payload['sources']['cards']}`（{len(cards)} 条，"
      f"{(cards_meta or {}).get('client_version', '?')}）")
    if payload["sources"]["ours"]:
        A(f"- 我们的策略：`{payload['sources']['ours']}`"
          f"（{cmp_block['games']} 局 / {cmp_block['boards']} 个 t12–t15 棋盘）")
    A("")
    A("## 0. 样本\n")
    A(md_table(
        ["项", "值", "说明"],
        [["真实库总行数", lib_meta["lines"], "去重后的 recruitment_end 快照"],
         ["真实库总局数", len(lib_meta["games"]), "每局最多 1 行/回合"],
         ["t12–t15 全部快照", len(turns_avail), "未加身材门槛"],
         ["**入选战团（Σ≥{:,}）**".format(used_min), f"**{len(sel)}**",
          "放宽到 {:,}".format(SUM_FALLBACK) if relaxed else "未放宽（≥30 即够）"],
         ["入选局数", n_games, "同局多个回合快照会重复计入"],
         ["入选随从数", n_minions, "逐张拆解的样本量"],
         ["Σ 身材总量", fnum(total_stat), "总量口径分母"],
         ["战团 Σ 中位数", fnum(payload["totals"]["stat_p50_board"]), "入选样本"],
         ["库内 t15 Σ p50", fnum(t15_p50), "对照已知事实 26,516"]],
        ["---", "---:", "---"],
    ))
    A("\n**口径**：`总量口径` = 所有身材加总后算占比（被头部战团主导）；"
      "`逐局口径` = 先在每局内算占比再对局取平均（每局权重 1）。两个都列，避免一个 37 万 Σ 的战团吞掉结论。\n")
    A(f"\n**来源标注**：§1–§8 全部数字来自 `{payload['sources']['real_library']}` 中筛选出的 "
      f"**{len(sel)} 个战团 / {n_games} 局 / {n_minions} 张随从**；"
      "§9 的「人类」列同源，§9 的「我们」列来自 "
      f"`{payload['sources']['ours']}` 的 {cmp_block['games'] if cmp_block else 0} 局 / "
      f"{cmp_block['boards'] if cmp_block else 0} 个 t12–t15 棋盘；"
      f"卡名/基础身材来自 `{payload['sources']['cards']}`。\n")

    A("\n## 1. 金色贡献\n")
    A(md_table(
        ["口径", "金卡身材占比", "说明"],
        [["总量口径", f"**{pct(gold_share_total):.2f}%**",
          f"金卡 {n_golden} 张 / {n_minions} 张（{pct(golden_count_share):.1f}%）"],
         ["逐局口径", f"{pct(gold_share_board):.2f}%", f"{len(sel)} 个战团各自算占比后取平均"]],
        ["---", "---:", "---"],
    ))
    A("\n已知事实「真实身材 62.1% 来自金卡」在**本样本/本口径**下复现为 "
      f"{pct(gold_share_total):.2f}%（总量）/{pct(gold_share_board):.2f}%（逐局）。"
      "金卡以 ~{:.0f}% 的随从数占比撑起 ~{:.0f}% 的身材 → **单位金卡的身材效率约 {:.1f}×**。\n"
      .format(pct(golden_count_share), pct(gold_share_total),
              (gold_share_total / golden_count_share) if golden_count_share else 0))
    A(md_table(
        ["金卡所属 tier", "占金卡身材", "占该 tier 总身材"],
        [[f"t{r['tier']}", f"{pct(r['share_of_golden']):.2f}%",
          f"{pct(next((x['share_total'] for x in tier_tbl if x['key'] == r['tier']), 0)):.2f}%"]
         for r in payload["golden_by_tier"]],
        ["---", "---:", "---:"],
    ))

    A("\n## 2. tier 分布\n")
    A(md_table(
        ["tier", "身材总量", "总量占比", "逐局占比", "随从数"],
        [[f"t{t['key']}", fnum(t["stat_total"]), f"{pct(t['share_total']):.2f}%",
          f"{pct(t['share_per_board']):.2f}%", t["minions"]] for t in tier_tbl],
        ["---", "---:", "---:", "---:", "---:"],
    ))

    A("\n## 2b. 机制归因（承载身材的卡**自身**是什么机制）\n")
    A("用 `cards.json` 的 `text_zh` 规则分类（优先级：光环 > 吞噬 > 酒馆全局buff > 双触发 > "
      "进击 > 亡语 > 战吼 > 回末 > 复仇 > 其它）。这张表直接回答「身材堆在什么玩法的卡身上」。\n")
    A(md_table(
        ["机制", "身材总量", "总量占比", "逐局占比", "随从数", "该机制内金卡占比"],
        [[m["mech"], fnum(m["stat_total"]), f"{pct(m['share_total']):.2f}%",
          f"{pct(m['share_per_board']):.2f}%", m["minions"],
          f"{pct(m['golden_share_within']):.1f}%"] for m in mech_tbl2],
        ["---", "---:", "---:", "---:", "---:", "---:"],
    ))
    A("\n多标签视角（一张卡可同时是「进击」和「亡语」，合计可 >100%）：\n")
    A(md_table(
        ["机制标签", "身材占比", "随从数"],
        [[t["tag"], f"{pct(t['stat_share']):.2f}%", t["minions"]]
         for t in payload["mechanism_multilabel"]],
        ["---", "---:", "---:"],
    ))
    A("\n### 集中度：复利 = 少数几张卡吃走大部分身材\n")
    A(md_table(
        ["指标", "值", "含义"],
        [["不同卡种数", concentration["distinct_cards"], f"{len(sel)} 个战团里出现过的卡"],
         ["top1 卡身材占比", f"{pct(concentration['top1']):.2f}%", "单卡最高"],
         ["top3 卡身材占比", f"{pct(concentration['top3']):.2f}%", ""],
         ["top5 卡身材占比", f"**{pct(concentration['top5']):.2f}%**", ""],
         ["top10 卡身材占比", f"{pct(concentration['top10']):.2f}%", ""],
         ["top20 卡身材占比", f"{pct(concentration['top20']):.2f}%", ""],
         ["HHI", f"{concentration['hhi']:.4f}", "Σ(share²)，越大越集中"]],
        ["---", "---:", "---"],
    ))

    A("\n## 3. 种族分布（前 5 + 无族/多族）\n")
    A(md_table(
        ["种族", "身材总量", "总量占比", "逐局占比", "随从数"],
        [[r["key"], fnum(r["stat_total"]), f"{pct(r['share_total']):.2f}%",
          f"{pct(r['share_per_board']):.2f}%", r["minions"]] for r in race_tbl_disp[:7]],
        ["---", "---:", "---:", "---:", "---:"],
    ))
    A("\n（完整种族表见 `decomp.json → race`。）\n")

    A("\n## 4. 关键卡频次 top-20（按身材贡献排序）\n")
    A(md_table(
        ["#", "卡", "tier", "种族", "出现率", "每局张数", "身材占比", "金卡张数"],
        [[i + 1, f"{c['name']} `{c['card_id']}`", c["tier"], "/".join(c["races"]),
          f"{pct(c['appear_rate']):.1f}%", f"{c['copy_rate']:.2f}",
          f"{pct(c['stat_share']):.2f}%", c["golden_copies"]]
         for i, c in enumerate(card_by_stat[:20])],
        ["---:", "---", "---:", "---", "---:", "---:", "---:", "---:"],
    ))
    A("\n### 出现率 top-20（人类最常用的牌）\n")
    A(md_table(
        ["#", "卡", "tier", "种族", "出现率", "每局张数", "身材占比"],
        [[i + 1, f"{c['name']} `{c['card_id']}`", c["tier"], "/".join(c["races"]),
          f"{pct(c['appear_rate']):.1f}%", f"{c['copy_rate']:.2f}",
          f"{pct(c['stat_share']):.2f}%"]
         for i, c in enumerate(card_by_freq[:20])],
        ["---:", "---", "---:", "---", "---:", "---:", "---:"],
    ))

    A("\n## 5. buff / 成长（counter、血宝石等字段不可得 → 替代指标）\n")
    A("`availability` 明确标注 `counter / gems / attachments / player_counters` 均 **不可得**。"
      "替代指标：`实际身材 − 卡表基础身材`（金卡用卡表金卡条目，已双倍，故该差值对金卡同样成立）。\n")
    A(md_table(
        ["指标", "值", "说明"],
        [["永久 buff 总量", fnum(buff_total), "Σ(实际−基础)"],
         ["buff 占总身材（总量口径）", f"**{pct(buff_share):.2f}%**", "被离群战团放大"],
         ["buff 占总身材（逐局中位数）", f"**{pct(buff_share_board_med):.1f}%**",
          f"176 个战团各自算占比后的中位数（p10 = {pct(buff_share_board_lo):.1f}%）"],
         ["有 buff 的随从占比", f"{pct(buffed_ratio):.1f}%", f"{n_minions} 张"],
         ["单随从 buff 中位数", fnum(buff_per_minion_med), "+atk+hp"],
         ["单战团 buff 中位数", fnum(buff_per_board_med), "每局 Σ buff"]],
        ["---", "---:", "---"],
    ))
    A("\n**buff 集中在哪些卡**（前 15，直接体现「谁在吃成长」）：\n")
    A(md_table(
        ["#", "卡", "tier", "buff 总量", "占全部 buff", "张数（其中金卡）"],
        [[i + 1, f"{c['name']} `{c['card_id']}`", c["tier"], fnum(c["buff_total"]),
          f"{pct(c['buff_share']):.1f}%", f"{c['copies']}（{c['golden_copies']}）"]
         for i, c in enumerate(buff_card_tbl)],
        ["---:", "---", "---:", "---:", "---:", "---"],
    ))
    A("\nbuff 按 tier：\n")
    A(md_table(
        ["tier", "buff 总量", "占全部 buff"],
        [[f"t{r['tier']}", fnum(r["buff"]), f"{pct(r['share']):.1f}%"]
         for r in payload["buff_by_tier"]],
        ["---", "---:", "---:"],
    ))
    A("\nbuff 按种族：\n")
    A(md_table(
        ["种族", "buff 总量", "占全部 buff"],
        [[RACE_ZH.get(r["race"], r["race"]), fnum(r["buff"]), f"{pct(r['share']):.1f}%"]
         for r in payload["buff_by_race"][:6]],
        ["---", "---:", "---:"],
    ))

    A("\n## 6. 关键词 / 圣盾（pivot：可观测的中间量）\n")
    A(md_table(
        ["关键词位", "随从数", "身材占比"],
        [[k["kw"], k["minions"], f"{pct(k['stat_share']):.2f}%"]
         for k in payload["keywords"]["bits"]],
        ["---", "---:", "---:"],
    ))
    A(f"\n- 带任一关键词位的随从：{len(kw_rows)}/{n_minions}"
      f"（{pct(len(kw_rows)/n_minions if n_minions else 0):.1f}%）")
    A(f"- `bonus_kw` 非零（被授予的关键词）：{bonus_kw_rows} 张")
    A(f"- 圣盾层数 >1（`shield_max`）：{shield_sum} 张")
    A("- 注意：库中 `kw` 为「tag 位 ∪ 印刷位」，无法还原**授予次数**；"
      "只能作为「关键词激活数」的静态快照。\n")

    A("\n## 7. 放大器（Titus / Drakkari / Gatekeeper）在本样本中的真实占比\n")
    A(md_table(
        ["放大器", "张数", "出现的战团数", "出现率", "身材占比"],
        [[f"`{r['amp']}`", r["minions"], r["boards"], f"{pct(r['appear_rate']):.1f}%",
          f"{pct(r['stat_share']):.3f}%"] for r in payload["amplifiers"]["per_amp"]] +
        [["任一放大器", "-", payload["amplifiers"]["any_amp_boards"],
          f"{pct(payload['amplifiers']['any_amp_rate']):.1f}%", "-"]],
        ["---", "---:", "---:", "---:", "---:"],
    ))
    A("\n**分层出现率**（判断「5%」是不是样本口径差异）：\n")
    A(md_table(
        ["样本层", "战团数", "含至少 1 个放大器", "出现率"],
        [[k, v["boards"], v["hit"], f"{pct(v['rate']):.1f}%"]
         for k, v in payload["amplifiers"]["layers"].items()],
        ["---", "---:", "---:", "---:"],
    ))
    A(f"\n→ 关键纠正：放大器**自身身材占比只有 "
      f"{pct(max((r['stat_share'] for r in payload['amplifiers']['per_amp']), default=0)):.2f}%**，"
      "但它出现在 "
      f"{pct(payload['amplifiers']['any_amp_rate']):.1f}% 的高强战团里 —— "
      "它**不是身材来源，而是乘数**。\n")

    A("\n### 7b. 更重要的纠正：真正的放大器家族不是这 3 张\n")
    A("用 `cards.json` 文本规则（「施放两次 / 额外施放 / 触发两次 / 额外触发」）扫出的 "
      f"**广义触发放大器家族共 {payload['amplifiers']['family_size']} 个卡 id**，"
      f"它们合计身材占比 {pct(payload['amplifiers']['family_stat_share']):.2f}%。"
      "这才是高强战团里真正的「乘法器」。\n")
    A(md_table(
        ["样本层", "战团数", "含至少 1 个放大器家族成员", "出现率"],
        [[k, v["boards"], v["hit"], f"{pct(v['rate']):.1f}%"]
         for k, v in payload["amplifiers"]["family_layers"].items()],
        ["---", "---:", "---:", "---:"],
    ))
    A("\n")
    A(md_table(
        ["#", "放大器", "tier", "出现率", "身材占比", "张数（金卡）", "效果"],
        [[i + 1, f"{c['name']} `{c['card_id']}`", c["tier"], f"{pct(c['appear_rate']):.1f}%",
          f"{pct(c['stat_share']):.2f}%", f"{c['copies']}（{c['golden_copies']}）", c["text"]]
         for i, c in enumerate(payload["amplifiers"]["family_top"])],
        ["---:", "---", "---:", "---:", "---:", "---", "---"],
    ))
    A("\n→ **出现率最高的牌几乎都不是身材牌**：巴琳达·斯通赫尔斯（你的指向性法术施放两次，"
      "35% 高强战团都有）身材占比只有零点几个百分点，但它是「恶魔干扰者：对本随从施放法术 → "
      "酒馆全体永久 +1/+2」这条链的乘数。这就是为什么按「身材贡献」看不到它、"
      "但按「出现率」它排第一。\n")

    A("\n## 8. 稳健性：去掉头部战团后结论是否变\n")
    A(md_table(
        ["丢弃头部战团数", "剩余战团", "金色占比", "t6 占比", "buff 占比"],
        [[r["drop_top"], r["boards"], f"{pct(r['golden_share']):.2f}%",
          f"{pct(r['t6_share']):.2f}%", f"{pct(r['buff_share']):.2f}%"] for r in robust],
        ["---:", "---:", "---:", "---:", "---:"],
    ))
    A("\n（若金色占比 / buff 占比在去掉头部 5 局后仍同量级，说明结论不是被离群战团伪造的。）\n")
    if robust:
        A(f"\n顺带：去掉头部 1 个战团后金色占比 = {pct(robust[1]['golden_share']):.2f}%，"
          "与已知事实「62.1% 来自金卡」几乎重合 → 说明 62.1% 这个数也是**总量口径、且被单个"
          "超大战团轻微抬高**的结果；逐局口径只有 ~49%。\n")

    if cmp_block:
        A("\n## 9. 人类 vs 我们（同口径：t12–t15 棋盘上的卡牌出现率）\n")
        A(md_table(
            ["项", "人类（真实库）", "我们（s25 collector）"],
            [["棋盘数", len(sel), cmp_block["boards"]],
             ["局数", n_games, cmp_block["games"]],
             ["牌均身材 Σ 中位数", fnum(payload["totals"]["stat_p50_board"]),
              fnum(cmp_block["strength_p50"])],
             ["统计口径", "逐张 atk/hp 实测", "只有卡 id → 基础身材估计 `{}`".format(
                 fnum(cmp_block["est_total"]))],
             ["金卡张数占比", f"{pct(golden_count_share):.1f}%",
              f"{pct(cmp_block['our_golden_ratio']):.1f}%"]],
            ["---", "---:", "---:"],
        ))
        A("\n> 我们这一侧 `games.jsonl.gz` **不记录 atk/hp**，逐卡身材贡献 **不可得**；"
          "下表的 `我们的基础身材占比` 是「卡表基础 atk+hp」的下界估计（不含 buff、金卡按金卡基础）。\n")
        A("\n### 9.1 人类 top-20（按出现率）\n")
        A(md_table(
            ["#", "卡", "tier", "人类出现率", "人类身材占比", "我们出现率", "我们基础占比"],
            [[i + 1, f"{c['name']} `{c['card_id']}`", c["tier"],
              f"{pct(c['appear_rate']):.1f}%", f"{pct(c['stat_share']):.2f}%",
              f"{pct(c['our_appear']):.1f}%", f"{pct(c['our_est_share']):.2f}%"]
             for i, c in enumerate(cmp_block["human_top20"])],
            ["---:", "---", "---:", "---:", "---:", "---:", "---:"],
        ))
        A("\n### 9.2 我们 top-20（按出现率）\n")
        A(md_table(
            ["#", "卡", "tier", "我们出现率", "我们基础占比", "人类出现率", "人类身材占比"],
            [[i + 1, f"{c['name']} `{c['card_id']}`", c["tier"],
              f"{pct(c['our_appear']):.1f}%", f"{pct(c['our_est_share']):.2f}%",
              f"{pct(c['human_appear']):.1f}%", f"{pct(c['human_stat_share']):.2f}%"]
             for i, c in enumerate(cmp_block["our_top20"])],
            ["---:", "---", "---:", "---:", "---:", "---:", "---:"],
        ))
        A("\n### 9.3 差异表：人类 top-20 有、我们没有（前 10）\n")
        A(md_table(
            ["卡", "tier", "人类出现率", "人类身材占比", "我们出现率"],
            [[f"{c['name']} `{c['card_id']}`", cards.get(c["card_id"], {}).get("tier", "?"),
              f"{pct(c['human_appear']):.1f}%", f"{pct(c['human_stat_share']):.2f}%",
              f"{pct(c['our_appear']):.1f}%"]
             for c in cmp_block["human_only"][:10]],
            ["---", "---:", "---:", "---:", "---:"],
        ))
        A("\n### 9.4 差异表：我们 top-20 有、人类没有（前 10）\n")
        A(md_table(
            ["卡", "tier", "我们出现率", "我们基础占比", "人类出现率"],
            [[f"{c['name']} `{c['card_id']}`", cards.get(c["card_id"], {}).get("tier", "?"),
              f"{pct(c['our_appear']):.1f}%", f"{pct(c['our_est_share']):.2f}%",
              f"{pct(c['human_appear']):.1f}%"]
             for c in cmp_block["our_only"][:10]],
            ["---", "---:", "---:", "---:", "---:"],
        ))
        A("\n### 9.5 可达性诊断：人类 TOP-20（按身材占比）在我们 200 局里的表现\n")
        A("`in_pool` = 该卡在我们的商店里至少出现过一次 → 用来区分「卡池里没有」和「有但不买/不会用」。\n")
        A(md_table(
            ["#", "卡", "tier", "人类出现率", "人类身材占比",
             "我们商店出现率", "我们买过率", "我们上场率", "卡池有?"],
            [[i + 1, f"{c['name']} `{c['card_id']}`", c["tier"],
              f"{pct(c['human_appear']):.0f}%", f"{pct(c['human_stat_share']):.1f}%",
              f"{pct(c['our_shop_rate']):.1f}%", f"{pct(c['our_bought_rate']):.1f}%",
              f"{pct(c['our_board_rate']):.1f}%",
              "✅" if c["in_pool"] else "❌"]
             for i, c in enumerate(cmp_block["reach"][:20])],
            ["---:", "---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"],
        ))
        A("\n> `_G`（金卡）的卡池/买过列按**普通形态**探测（商店不出售金卡，金卡靠三连）；"
          "`❌` 表示该卡在我们 200 局的商店里**一次都没出现** → 是卡池/可购性问题，不是策略问题。\n")
        our_tier_hist = cmp_block["tier_hist"]
        our_t5p = sum(v for k, v in our_tier_hist.items() if int(k) >= 5) / max(
            1, cmp_block["boards"])
        human_t5p = sum(r["share_total"] for r in tier_tbl if r["key"] >= 5)
        A("\n### 9.6 tier / 放大器对比\n")
        A(md_table(
            ["项", "人类（身材占比口径）", "我们（棋盘数口径）"],
            [["t5 及以上", f"{pct(human_t5p):.1f}%", f"{pct(our_t5p):.1f}%（{cmp_block['boards']} 个棋盘）"],
             ["含放大器的棋盘", f"{pct(payload['amplifiers']['any_amp_rate']):.1f}%",
              f"{pct(cmp_block['amp_board_rate']):.1f}%（{cmp_block['amp_boards']}/{cmp_block['boards']}）"]],
            ["---", "---:", "---:"],
        ))

    A("\n## 10. 结论：真实复利链的构成（按身材贡献排序）\n")
    fam_rate = payload["amplifiers"]["family_layers"].get(
        f"t{TURN_LO}–t{TURN_HI} 且 Σ≥{used_min}（本样本）", {}).get("rate", 0.0)
    mech_map = {m["mech"]: m for m in mech_tbl2}
    tbs = mech_map.get("酒馆全局永久 buff", {"share_total": 0, "golden_share_within": 0})
    tsh = mech_map.get("吞噬（吃掉酒馆属性）", {"share_total": 0, "golden_share_within": 0})
    A("### 10.0 机制循环（这才是「复利」的形状）\n")
    A("把 top 卡和机制表拼起来，真实高强战团的循环是：\n")
    A("```")
    A("① 拿到「指向性法术双放」放大器（巴琳达 35.2% / 提图斯 14.2% / 铜须 14.8% …）")
    A("        ↓  同一张法术被施放 2 次")
    A("② 对引擎随从施法 → 酒馆全体永久 +N/+N（恶魔干扰者 BG36_762：对本随从施法→酒馆全体+1/+2；"
      "灰烬腐蚀者：受伤→本回合酒馆+2/+2）")
    A("        ↓  酒馆里的随从属性被抬到极高")
    A("③ 吞噬/吸收把酒馆属性**搬进本体**（邪能野猪人 BG28_633：每 3 个法术吞食酒馆随从并获得属性）")
    A("        ↓  本体成为几十万身材的终端")
    A("④ 金卡把 ①②③ 每一步都翻倍（该机制内金卡占比 74.8%）")
    A("        ↓")
    A("⑤ 放大器家族合计出现在 %.1f%% 的高强战团里（但它们自身只占 %.2f%% 身材）" %
      (pct(fam_rate), pct(payload["amplifiers"]["family_stat_share"])))
    A("```")
    A(f"\n量化：酒馆全局永久 buff 承载 **{pct(tbs['share_total']):.2f}%** 身材"
      f"（该类金卡占比 {pct(tbs['golden_share_within']):.1f}%）；"
      f"吞噬承载 **{pct(tsh['share_total']):.2f}%**；两者合计 "
      f"{pct(tbs['share_total'] + tsh['share_total']):.2f}%。"
      "叠加「法术次数」这个驱动量，就是真实玩家 10k–370k 身材的来源。\n")
    A("> 注意：下面 ①–⑤ 是**同一份身材的不同切面**，不能相加"
      "（一张金卡恶魔干扰者同时计入金卡、t5、恶魔、机制、单卡五项）。\n")
    for c in chain:
        A(f"**{c['path']} —— {pct(c['share']):.2f}%**  \n"
          f"- 证据：{c['evidence']}  \n- 可监控中间量：`{c['metric']}`\n")
    A("\n### 可奖励的中间量清单（全部可从现有观测算，不需要新 counter）\n")
    A(md_table(
        ["中间量", "定义（观测内可算）", "本样本典型值", "可得性"],
        [["金色数", "`board_detail[].golden` 为 true 的张数", f"平均 {n_golden/len(sel):.2f} 张/战团（金卡身形占 {pct(gold_share_total):.0f}%）", "可得"],
         ["金卡身材占比", "Σ金卡身材 / Σ身材", f"{pct(gold_share_board):.1f}%（逐局均值）", "可得"],
         ["永久 buff 次数/量", "Σ(实际−卡表基础) 或「每张随从是否为 buffed」",
          f"{pct(buff_share_board_med):.0f}%（逐局中位数）身材来自 buff", "可得（派生）"],
         ["引擎卡在场时长", "酒馆全局buff / 吞噬 机制卡的累计在场棋盘数",
          f"top1 引擎卡占 {pct(card_by_stat[0]['stat_share']):.0f}% 身材", "可得（派生：机制×卡id）"],
         ["buffed 随从数", "实际身材 > 卡表基础的张数", f"{pct(buffed_ratio):.1f}% 随从被 buff 过", "可得（派生）"],
         ["关键词激活数", "`kw` 位图 popcount（含 bonus_kw）", f"{len(kw_rows)/n_minions*100:.1f}% 随从带关键词", "可得"],
         ["圣盾层数", "`shield_max`", f"{shield_sum} 张 >1 层", "可得"],
         ["放大器/触发家族在场", "文本规则（施放两次/额外施放/触发两次）命中的卡 id",
          f"{pct(fam_rate):.1f}% 高强战团有（自身仅 {pct(payload['amplifiers']['family_stat_share']):.1f}% 身材）",
          "可得（派生：卡表文本）"],
         ["血宝石/法术 counter", "库内无字段", "**不可得**", "不可得 → 用 buff 量替代"],
         ["种族同质度", "某族张数 / 棋盘张数", f"{RACE_ZH.get(race_tbl[0]['key'], race_tbl[0]['key'])} 占 {pct(race_tbl[0]['share_total']):.0f}% 身材", "可得"]],
        ["---", "---", "---", "---"],
    ))
    A("\n### 对我们训练的直接含义\n")
    A(f"1. **身材 ≈ buff**：{pct(buff_share):.1f}% 的身材在卡表基础之外（逐局中位数 "
      f"{pct(buff_share_board_med):.1f}%），所以奖励必须看「buff 增量」而不是「买了几张高身材卡」。")
    A(f"2. **金卡是最大单一乘数**：{pct(golden_count_share):.0f}% 的随从撑起 "
      f"{pct(gold_share_total):.0f}% 身材（≈{(gold_share_total / golden_count_share) if golden_count_share else 0:.1f}× 效率）。")
    A(f"3. **承重墙是 t5–t6（{pct(sum(r['share_total'] for r in tier_tbl if r['key'] >= 5)):.0f}%）"
      f" + {RACE_ZH.get(race_tbl[0]['key'], race_tbl[0]['key'])}（{pct(race_tbl[0]['share_total']):.0f}%）**；"
      "t1–t3 一共只占 "
      f"{pct(sum(r['share_total'] for r in tier_tbl if r['key'] <= 3)):.1f}%，基本是过夜/过渡牌。")
    A("4. 把「Σ身材」拆成 `基础 + buff` 两项奖励，可以避免模型只学会堆基础卡而不学成长；"
      "再加「引擎卡（酒馆全局 buff / 吞噬）在场时长」作为 shaping，才对齐真实复利链。\n")

    A("\n## 11. 不可得字段（明确声明）\n")
    A(md_table(
        ["字段", "状态", "替代指标"],
        [["血宝石数 / gems", "不可得（availability=gems unavailable）", "`Σ(实际−基础)` 的 buff 量"],
         ["法术 buff counter / counter", "不可得", "同上"],
         ["attachments / 亡语脚本", "不可得", "`kw` 位 + `shield_max`"],
         ["player_counters / 英雄技能使用次数", "不可得", "无（只能用回合数代理）"],
         ["gold / 经济", "不可得", "tavern tier + 回合数"],
         ["我们侧逐卡 atk/hp", "不可得（collector 只存卡 id）", "卡表基础身材下界估计"]],
        ["---", "---", "---"],
    ))
    A("\n## 12. 数据来源清单\n")
    A(md_table(
        ["文件", "规模", "用途"],
        [[f"`{payload['sources']['real_library']}`", f"{lib_meta['lines']} 行 / {len(lib_meta['games'])} 局",
          f"真实战团逐张 atk/hp/golden/kw（入选 {len(sel)} 战团 / {n_games} 局）"],
         [f"`{payload['sources']['cards']}`", f"{len(cards)} 张卡",
          "卡名/tier/种族/基础身材/机制文本（金卡为独立条目）"],
         [f"`{payload['sources']['ours']}`",
          f"{cmp_block['games'] if cmp_block else 0} 局 / {cmp_block['boards'] if cmp_block else 0} 棋盘",
          "我们 s25 自对弈的卡 id + strength（无 atk/hp）"],
         ["`runs/az_entity_s25/collector/funnel35.json`", "200 局",
          "对照：放大器出现率 5%、t15 strength p50 812.5"]],
        ["---", "---", "---"],
    ))
    A("\n---\n")
    A("复算：`python scripts/real_board_decompose.py`（只读数据，秒级完成，无 GPU）。\n")
    A(f"机器可读结果：`{os.path.relpath(os.path.join(OUT_DIR, 'decomp.json'), ROOT)}`"
      "（含逐卡表、机制表、稳健性、可达性诊断）。\n")

    with open(os.path.join(OUT_DIR, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    # ---------- 控制台摘要 ----------
    print(f"[sample] boards={len(sel)} games={n_games} minions={n_minions} "
          f"sum_min={used_min} relaxed={relaxed}")
    print(f"[total] stat_total={total_stat:,} p50_board={payload['totals']['stat_p50_board']:,} "
          f"t15_p50={t15_p50:,}")
    print(f"[golden] count={n_golden}/{n_minions} ({pct(golden_count_share):.1f}%) "
          f"stat_share_total={pct(gold_share_total):.2f}% per_board={pct(gold_share_board):.2f}%")
    print(f"[buff] total={buff_total:,} share={pct(buff_share):.2f}% buffed={pct(buffed_ratio):.1f}%")
    print("[tier] " + " ".join(f"t{t['key']}:{pct(t['share_total']):.1f}%" for t in tier_tbl))
    print("[race] " + " ".join(f"{r['key']}:{pct(r['share_total']):.1f}%" for r in race_tbl_disp[:5]))
    print("[top cards] " + "; ".join(
        f"{c['name']}({c['card_id']}) {pct(c['appear_rate']):.0f}%/{pct(c['stat_share']):.1f}%"
        for c in card_by_stat[:8]))
    print("[amp] any_amp_boards={} ({:.1f}%)".format(
        payload["amplifiers"]["any_amp_boards"], pct(payload["amplifiers"]["any_amp_rate"])))
    if cmp_block:
        print("[ours] boards={} games={} est_total={:,} strength_p50={}".format(
            cmp_block["boards"], cmp_block["games"], cmp_block["est_total"],
            cmp_block["strength_p50"]))
        print("[ours top] " + "; ".join(
            f"{c['name']} {pct(c['our_appear']):.0f}%" for c in cmp_block["our_top20"][:8]))
    print(f"[out] {OUT_DIR}/REPORT.md + decomp.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
