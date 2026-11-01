#!/usr/bin/env python3
"""抓取 Firestone 的 Battlegrounds「comps（阵容）」数据 → ``data/scaling/comps_top.json``。

背景
----
用户的核心判断：现有训练都停在弱局部最优上，真正要学的是**复利阵容的几何/指数成长**。
``docs/COMPOUND_CHAINS.md``/``data/scaling/compound_cards.json`` 是从**引擎卡表**里
挖「复利卡」；本脚本补上**人类共识**那一半：Firestone 的 comps 页（top MMR）系统
整理了若干阵容，含「核心牌 / 附加牌 / 循环牌 / 上分难度 / 适配饰品 / 打法要点」。

数据来源（页面是 SPA，真正的数据在静态 JSON 端点；URL 从 ``main.*.js`` bundle 里
grep 得到，见 ``docs/COMP_LINES_TINY.md`` §1）
--------------------------------------------------------------
| 用途 | URL |
|---|---|
| 阵容定义（27 套，含 CORE/ADDON/CYCLE + 专家 tip） | ``static.zerotoheroes.com/hearthstone/data/battlegrounds-strategies/bgs-comps-strategies.gz.json?v=37.0`` |
| 阵容战绩（按 MMR 分桶的平均名次） | ``static.zerotoheroes.com/api/bgs/comp-stats/last-patch/overview-v3.gz.json`` |
| 阵容示例终局面板（真实高 MMR 玩家） | ``static.zerotoheroes.com/api/bgs/comp-stats/last-patch/boards/<archetype>.json`` |
| 饰品专家点评（142 条） | ``static.zerotoheroes.com/hearthstone/data/battlegrounds-strategies/bgs-trinket-strategies.gz.json`` |
| 饰品战绩（按 MMR 分桶的选取率/名次） | ``static.zerotoheroes.com/api/bgs/trinket-stats/last-patch/overview-from-hourly.gz.json`` |

**饰品（trinkets）没有 comp→trinket 的官方映射**，本脚本按三条可核验的证据合成，
并把证据写进每条记录的 ``why``（不编造）：

1. ``mention``：饰品专家点评里用 ``[[卡名]]`` 明确提到的本阵容**核心/附加卡**；
2. ``assoc``：引擎卡表 ``cards.json`` 的 ``assoc``（阵营归属）命中本阵容的种族；
3. ``mechanic``：饰品的 ``text`` 与本阵容核心卡的机制词（复生/战吼/亡语/酒馆 buff…）重合。

排序用 top-10% MMR 分桶的平均名次与选取率（``rank=10`` 口径，与页面 ``?rank=10`` 一致）。

用法::

    python scripts/comp_lines_fetch.py                    # 抓网络 + 写文件
    python scripts/comp_lines_fetch.py --offline DIR      # 用本地缓存（runs/comp_lines/raw）
    python scripts/comp_lines_fetch.py --no-boards        # 跳过示例面板（省 35 次请求）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATIC = "https://static.zerotoheroes.com"
URL_COMPS = (STATIC + "/hearthstone/data/battlegrounds-strategies/"
             "bgs-comps-strategies.gz.json?v=37.0")
URL_COMP_STATS = STATIC + "/api/bgs/comp-stats/last-patch/overview-v3.gz.json"
URL_COMP_BOARDS = STATIC + "/api/bgs/comp-stats/last-patch/boards/{archetype}.json"
URL_TRINKET_TIPS = (STATIC + "/hearthstone/data/battlegrounds-strategies/"
                    "bgs-trinket-strategies.gz.json")
URL_TRINKET_STATS = STATIC + "/api/bgs/trinket-stats/last-patch/overview-from-hourly.gz.json"

#: 页面 ``?rank=10`` = top 10% MMR 分桶（overview 的 mmr 桶是 100/50/25/10/1 百分位，
#: 1 = 最强 1%）。阵容排序与判据都用这个桶。
MMR_BUCKET = 10

#: 机制词 → 中文成长机制标签（用于 ``growth_mechanism`` 归一化）
MECH_KEYWORDS: Sequence[Tuple[str, str]] = (
    ("reborn", "复生（reborn）"),
    ("deathrattle", "亡语（deathrattle）"),
    ("battlecry", "战吼（battlecry）"),
    ("windfury", "风怒（windfury）"),
    ("divine shield", "圣盾（divine shield）"),
    ("taunt", "嘲讽（taunt）"),
    ("attack", "攻击触发"),
    ("summon", "召唤/铺场"),
    ("spell", "法术联动"),
    ("tavern", "酒馆 buff"),
    ("blood gem", "鲜血宝石"),
    ("gem", "鲜血宝石"),
    ("end of turn", "结束回合触发"),
    ("start of combat", "战斗开始触发"),
    ("discover", "发现"),
    ("choose one", "抉择"),
    ("golden", "金色/三连"),
    ("consume", "吞噬"),
    ("discard", "弃牌"),
    ("refresh", "刷新酒馆"),
    ("trigger", "触发链放大"),
    ("duplicate", "复制（复制核心牌）"),
    ("bounty", "悬赏（bounty）"),
    ("scale", "缩放（永久成长）"),
    ("stats", "身材成长"),
)


def _get(url: str, cache_dir: str, *, timeout: float = 45.0) -> Any:
    """下载（或读缓存）一个 JSON。缓存文件名 = URL 的路径后缀（可读、可复现）。"""
    os.makedirs(cache_dir, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("//", 1)[1])[:180]
    path = os.path.join(cache_dir, name)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        req = urllib.request.Request(url, headers={"User-Agent": "hsbrsim-comp-lines/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - 固定静态域名
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
        time.sleep(0.15)
    with open(path, "rb") as f:
        raw = f.read()
    return json.loads(raw.decode("utf-8"))


def _mmr_bucket(rows: Optional[Sequence[Dict[str, Any]]], bucket: int,
                key: str) -> Optional[float]:
    for r in rows or ():
        if int(r.get("mmr", -1)) == int(bucket):
            v = r.get(key)
            return None if v is None else float(v)
    return None


def load_engine_cards() -> Dict[str, Dict[str, Any]]:
    """引擎权威卡表（``rust/crates/hsbg-engine/data/cards.json``）：id → 卡。"""
    p = os.path.join(ROOT, "rust", "crates", "hsbg-engine", "data", "cards.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return {str(c["id"]): c for c in d["cards"]}


def load_json(rel: str) -> Any:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def _tip_text(tips: Iterable[Dict[str, Any]]) -> Tuple[str, str]:
    """(when_to_commit, 全文)。Firestone 的 tip 有 ``tip``/``summary`` 两种键。"""
    when, body = "", []
    for t in tips or ():
        w = str(t.get("whenToCommit") or "").strip()
        if w and not when:
            when = w
        s = str(t.get("tip") or t.get("summary") or "").strip()
        if s:
            body.append(s)
    return when, " ".join(body)


def _mechanisms(text: str) -> List[str]:
    low = (text or "").lower()
    out: List[str] = []
    for kw, zh in MECH_KEYWORDS:
        if kw in low and zh not in out:
            out.append(zh)
    return out


def trinket_candidates(cards: Dict[str, Dict[str, Any]],
                       trinket_tips: Dict[str, Dict[str, Any]],
                       trinket_stats: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """全部饰品 + 它们的证据原料（供每套阵容打分）；一次构造，多次复用。"""
    out: List[Dict[str, Any]] = []
    for cid, c in cards.items():
        if not str(c.get("kind") or "").startswith("trinket"):
            continue
        tips = trinket_tips.get(cid) or {}
        mention_names = set()
        body = []
        for t in tips.get("tips") or ():
            s = str(t.get("summary") or t.get("tip") or "")
            body.append(s)
            for m in re.finditer(r"\[\[([^\]]+)\]\]", s):
                mention_names.add(m.group(1).strip().lower())
        tips_text = " ".join(body).lower()
        st = trinket_stats.get(cid) or {}
        out.append({
            "id": cid,
            "name": str(c.get("name") or ""),
            "name_zh": str(c.get("name_zh") or ""),
            "kind": str(c.get("kind") or ""),
            "cost": int(c.get("cost") or 0),
            "assoc": [str(x).upper() for x in (c.get("assoc") or ())],
            "text": str(c.get("text") or ""),
            "text_zh": str(c.get("text_zh") or ""),
            "tips_text": tips_text,
            "mention_names": mention_names,
            "place10": _mmr_bucket(st.get("averagePlacementAtMmr"), MMR_BUCKET, "placement"),
            "pick10": _mmr_bucket(st.get("pickRateAtMmr"), MMR_BUCKET, "pickRate"),
            "place_all": (float(st["averagePlacement"]) if st.get("averagePlacement") else None),
            "data_points": int(st.get("dataPoints") or 0),
        })
    return out


def score_trinkets(comp: Dict[str, Any], cands: Sequence[Dict[str, Any]], *,
                   topn: int = 4) -> List[Dict[str, Any]]:
    """给一套阵容挑「关键饰品」：三条证据 + 战绩排序（见模块 docstring）。"""
    tribe = str(comp.get("tribe") or "").upper()
    key_cards = [str(c.get("name") or "").lower()
                 for c in (comp.get("core_cards") or []) + (comp.get("addon_cards") or [])
                 if str(c.get("name") or "")]
    mech_words = {kw for kw, _zh in MECH_KEYWORDS
                  if kw in (comp.get("growth_text") or "").lower()}
    picked: List[Dict[str, Any]] = []
    for t in cands:
        why: List[str] = []
        score = 0.0
        hits = [n for n in t["mention_names"] if n in key_cards]
        if hits:
            why.append("mention:" + ",".join(sorted(hits)))
            score += 3.0 * len(hits)
        # 专家点评里直接用**普通文字**点名本阵容关键牌（`[[..]]` 之外的写法）：
        # 只在名字足够长（>=7 字符）时才认，避免 "titus" 之类的噪声。
        bare = [n for n in key_cards if len(n) >= 7 and n in t["tips_text"]]
        if bare:
            why.append("text:" + ",".join(sorted(bare)[:3]))
            score += 1.5 * len(bare)
        if tribe and tribe in t["assoc"]:
            why.append(f"assoc:{tribe}")
            score += 2.0
        mh = [w for w in mech_words if w in (t["text"] or "").lower()]
        if mh:
            why.append("mechanic:" + ",".join(sorted(mh)))
            score += 0.6 * len(mh)
        if not why:
            continue
        # 战绩：top-10% MMR 名次越好、选取率越高越靠前（没数据的不加分）
        if t["place10"] is not None:
            score += max(0.0, (4.6 - float(t["place10"]))) * 1.2
        if t["pick10"]:
            score += min(1.0, float(t["pick10"])) * 0.8
        picked.append({
            "id": t["id"], "name": t["name"], "name_zh": t["name_zh"],
            "kind": t["kind"], "cost": t["cost"], "assoc": t["assoc"],
            "text": t["text"][:400], "text_zh": t["text_zh"][:400],
            "place10": t["place10"], "pick10": t["pick10"],
            "data_points": t["data_points"],
            "why": why, "score": round(score, 3),
        })
    picked.sort(key=lambda x: (-x["score"], x["place10"] if x["place10"] is not None else 9.9))
    return picked[:int(topn)]


def board_sigma(board: Sequence[Dict[str, Any]]) -> int:
    return int(sum(int((m.get("tags") or {}).get("ATK") or 0) +
                   int((m.get("tags") or {}).get("HEALTH") or 0) for m in board or ()))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Firestone comps 数据 → data/scaling/comps_top.json")
    ap.add_argument("--out", default="data/scaling/comps_top.json")
    ap.add_argument("--cache", default="runs/comp_lines/raw", help="原始 JSON 缓存目录")
    ap.add_argument("--top", type=int, default=4, help="每套阵容取几个关键饰品")
    ap.add_argument("--no-boards", action="store_true", help="不抓示例面板")
    ap.add_argument("--top-n", type=int, default=10, help="标记 top-N 阵容（按 rank=10 名次）")
    args = ap.parse_args(argv)

    cache = os.path.join(ROOT, args.cache) if not os.path.isabs(args.cache) else args.cache
    cards = load_engine_cards()
    comps_raw = _get(URL_COMPS, cache)
    stats_raw = _get(URL_COMP_STATS, cache)
    tips_raw = _get(URL_TRINKET_TIPS, cache)
    tstats_raw = _get(URL_TRINKET_STATS, cache)

    trinket_tips = {str(t.get("cardId")): t for t in tips_raw if t.get("cardId")}
    trinket_stats = {str(t.get("trinketCardId")): t
                     for t in (tstats_raw.get("trinketStats") or ()) if t.get("trinketCardId")}
    cands = trinket_candidates(cards, trinket_tips, trinket_stats)
    stat_by = {str(c.get("archetype")): c for c in (stats_raw.get("compStats") or ())}

    comps: List[Dict[str, Any]] = []
    missing_boards: List[str] = []
    for e in comps_raw:
        cid = str(e.get("compId") or "").strip()
        if not cid:
            continue
        cs = stat_by.get(cid) or {}
        by_status: Dict[str, List[Dict[str, Any]]] = {"CORE": [], "ADDON": [], "CYCLE": []}
        for c in e.get("cards") or ():
            st = str(c.get("status") or "").upper()
            by_status.setdefault(st or "OTHER", []).append({
                "id": str(c.get("cardId") or ""),
                "name": str(c.get("name") or ""),
                "name_zh": str((cards.get(str(c.get("cardId") or "")) or {}).get("name_zh") or ""),
                "tier": int((cards.get(str(c.get("cardId") or "")) or {}).get("tier") or 0),
                "in_engine": str(c.get("cardId") or "") in cards,
            })
        when, body = _tip_text(e.get("tips") or ())
        # 阵容的主种族 = CORE+ADDON 里的**多数票**（按整个 comp 的种族计数），
        # 不是「第一张核心牌的种族」：一张跨种族的核心牌（如海盗 Sky Admiral
        # Rogers 进「Undead APM」）会把整个阵容判错。
        votes: Dict[str, int] = {}
        for w, group in ((2, by_status.get("CORE") or ()),
                         (1, by_status.get("ADDON") or ())):
            for c in group:
                for r in ((cards.get(c["id"]) or {}).get("races") or ()):
                    r = str(r).upper()
                    if r in ("ALL", "NEUTRAL"):
                        continue
                    votes[r] = votes.get(r, 0) + w
        tribe = max(votes, key=lambda k: votes[k]) if votes else ""
        comp = {
            "archetype": cid,
            "name": str(e.get("name") or cid),
            "tribe": tribe,
            "power_level": str(e.get("powerLevel") or ""),
            "difficulty": str(e.get("difficulty") or ""),
            "patch_number": e.get("patchNumber"),
            "core_cards": by_status.get("CORE") or [],
            "addon_cards": by_status.get("ADDON") or [],
            "cycle_cards": by_status.get("CYCLE") or [],
            # ``growth_text`` = 专家 tip 全文（成长机制的原始描述）；
            # ``text`` = 同一份内容的通用别名（与任务约定的字段名对齐）。
            "growth_text": body,
            "text": body,
            "when_to_commit": when,
            "growth_mechanism": _mechanisms(body + " " + when),
        }
        comp["trinkets"] = score_trinkets(comp, cands, topn=int(args.top))
        # 战绩（rank=10 口径 + 全量）
        a = cs.get("averagePlacementAtMmr") or []
        comp["stats"] = {
            "data_points": int(cs.get("dataPoints") or 0),
            "place_all": (round(float(cs["averagePlacement"]), 3)
                          if cs.get("averagePlacement") else None),
            "place_100": _mmr_bucket(a, 100, "placement"),
            "place_50": _mmr_bucket(a, 50, "placement"),
            "place_25": _mmr_bucket(a, 25, "placement"),
            "place_10": _mmr_bucket(a, MMR_BUCKET, "placement"),
            "dp_10": int(next((x.get("dataPoints") or 0 for x in a
                               if int(x.get("mmr", -1)) == MMR_BUCKET), 0)),
            "rank": None, "is_top": False,
        }
        # 示例终局面板：真实高 MMR 玩家的终局战团（Σ 口径与沙盒一致）
        if not args.no_boards:
            try:
                b = _get(URL_COMP_BOARDS.format(archetype=cid), cache)
                boards = b.get("boards") or []
                sig = [board_sigma(x.get("board")) for x in boards]
                if sig:
                    sig_sorted = sorted(sig)
                    comp["example_boards"] = {
                        "n": len(sig),
                        "sigma_max": int(max(sig)),
                        "sigma_p50": int(sig_sorted[len(sig_sorted) // 2]),
                        "mmr_max": int(max((x.get("mmr") or 0) for x in boards)),
                        "boards": [{"mmr": x.get("mmr"), "hero": x.get("heroCardId"),
                                    "sigma": board_sigma(x.get("board")),
                                    "cards": [m.get("cardID") for m in (x.get("board") or ())]}
                                   for x in boards[:8]],
                    }
                else:
                    comp["example_boards"] = {"n": 0}
            except Exception as exc:  # noqa: BLE001 - 面板缺失不影响主数据
                missing_boards.append(f"{cid}:{type(exc).__name__}")
                comp["example_boards"] = {"n": 0}
        comps.append(comp)

    # 排序：rank=10 名次优先（无数据的排最后），并标记 top-N
    def _key(c: Dict[str, Any]) -> Tuple[float, float]:
        p = c["stats"].get("place_10")
        return (9.9 if p is None else float(p), -(c["stats"]["data_points"]))

    comps.sort(key=_key)
    for i, c in enumerate(comps):
        c["stats"]["rank"] = i + 1
        c["stats"]["is_top"] = bool(i < int(args.top_n) and c["stats"].get("place_10") is not None)

    # ── 统计与交集 ──────────────────────────────────────────────────────
    carriers = load_json("data/scaling/carriers.json")
    compound = load_json("data/scaling/compound_cards.json")
    carrier_ids = [str(x) for x in carriers.get("primary_ids") or ()]
    core_all = sorted({str(x["id"]) for grp in (compound["core"]["by_archetype"] or {}).values()
                       for x in (grp.get("core") or ())})
    global_ids = [str(x["id"]) for x in compound["core"]["global"]]
    common_ids = [str(x) for x in compound["core"]["common_ids"]]

    def _norm(ids: Iterable[str]) -> List[str]:
        """去掉金色后缀（``_G``）后比较，避免「同一张牌两个 id」拉低交集。"""
        return sorted({i[:-2] if i.endswith("_G") else i for i in ids})

    union_core = sorted({c["id"] for comp in comps for c in comp["core_cards"]})
    union_core_addon = sorted({c["id"] for comp in comps
                               for c in comp["core_cards"] + comp["addon_cards"]})
    union_all = sorted({c["id"] for comp in comps
                        for c in comp["core_cards"] + comp["addon_cards"] + comp["cycle_cards"]})
    n_core_engine = sum(1 for i in union_core if i in cards)
    inter_carrier = sorted(set(_norm(union_core)) & set(_norm(carrier_ids)))
    inter_compound = sorted(set(_norm(union_core)) & set(_norm(core_all)))
    inter_carrier_ca = sorted(set(_norm(union_core_addon)) & set(_norm(carrier_ids)))
    inter_compound_ca = sorted(set(_norm(union_core_addon)) & set(_norm(core_all)))
    per_comp = []
    for c in comps:
        cids = [x["id"] for x in c["core_cards"]]
        per_comp.append({
            "archetype": c["archetype"], "name": c["name"],
            "core": len(cids),
            "core_in_engine": sum(1 for i in cids if i in cards),
            "core_in_compound": len(set(_norm(cids)) & set(_norm(core_all))),
            "core_in_carriers": len(set(_norm(cids)) & set(_norm(carrier_ids))),
            "core_is_carrier": len(set(_norm(cids)) & set(_norm(carrier_ids))),
            "trinkets": len(c["trinkets"]),
            "compound_by_archetype": (c["archetype"] in (compound["core"]["by_archetype"] or {})),
        })
    stats = {
        "n_comps": len(comps),
        "n_comps_with_stats": sum(1 for c in comps if c["stats"].get("place_10") is not None),
        "n_top": sum(1 for c in comps if c["stats"]["is_top"]),
        "mmr_bucket": MMR_BUCKET,
        "core_cards_union": len(union_core),
        "core_cards_in_engine": n_core_engine,
        "all_cards_union": len(union_all),
        "all_cards_in_engine": sum(1 for i in union_all if i in cards),
        "compound_core_ids": len(core_all),
        "compound_global_ids": len(global_ids),
        "compound_common_ids": len(common_ids),
        "carrier_ids": len(carrier_ids),
        "intersection_core_x_carriers": inter_carrier,
        "n_intersection_core_x_carriers": len(inter_carrier),
        "intersection_core_x_compound": inter_compound,
        "n_intersection_core_x_compound": len(inter_compound),
        "core_addon_union": len(union_core_addon),
        "intersection_core_addon_x_carriers": inter_carrier_ca,
        "n_intersection_core_addon_x_carriers": len(inter_carrier_ca),
        "intersection_core_addon_x_compound": inter_compound_ca,
        "n_intersection_core_addon_x_compound": len(inter_compound_ca),
        "coverage_core_in_compound_pct": round(
            100.0 * len(inter_compound) / max(1, len(_norm(union_core))), 1),
        "coverage_core_addon_in_compound_pct": round(
            100.0 * len(inter_compound_ca) / max(1, len(_norm(union_core_addon))), 1),
        "per_comp": per_comp,
        "trinkets_total_engine": len(cands),
        "trinkets_with_tips": len(trinket_tips),
        "trinkets_with_stats": len(trinket_stats),
        "boards_missing": missing_boards,
    }

    doc = {
        "meta": {
            "generated_by": "scripts/comp_lines_fetch.py",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sources": {
                "comps": URL_COMPS, "comp_stats": URL_COMP_STATS,
                "boards": URL_COMP_BOARDS, "trinket_tips": URL_TRINKET_TIPS,
                "trinket_stats": URL_TRINKET_STATS,
            },
            "cache": os.path.relpath(cache, ROOT),
            "note": "饰品无官方 comp 映射，trinkets 由 scripts/comp_lines_fetch.py "
                    "的三条证据（mention/assoc/mechanic）合成，证据写在 why 字段",
            "page": "https://www.firestoneapp.com/battlegrounds/comps?rank=10",
        },
        "stats": stats,
        "comps": comps,
    }
    out = os.path.join(ROOT, args.out) if not os.path.isabs(args.out) else args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"[comps] {len(comps)} 套阵容 → {os.path.relpath(out, ROOT)}")
    print(f"[comps] 核心牌并集 {len(union_core)} 张（引擎在库 {n_core_engine}）；"
          f"∩carriers={len(inter_carrier)}；∩compound={len(inter_compound)} "
          f"({stats['coverage_core_in_compound_pct']}%)")
    print(f"[comps] 饰品候选 {len(cands)} 张（有专家点评 {len(trinket_tips)}、有战绩 "
          f"{len(trinket_stats)}）")
    for c in comps[:int(args.top_n)]:
        print(f"  #{c['stats']['rank']:2d} {c['name']:<26s} place10={c['stats']['place_10']}"
              f" core={len(c['core_cards'])} trinkets={len(c['trinkets'])}"
              f" power={c['power_level']}")
    if missing_boards:
        print(f"[comps][warn] {len(missing_boards)} 套缺示例面板: {missing_boards[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
