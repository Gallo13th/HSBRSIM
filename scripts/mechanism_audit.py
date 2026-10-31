#!/usr/bin/env python3
"""机制能力审计：引擎 vs 线上 37.0 真实观测（只读，不训练）。

回答：
  1. 引擎实现了哪些机制/多少卡（按 kind / 是否在池 / 是否有脚本）；
  2. 真实观测里出现的卡与机制，有多少在引擎里**不存在或不可用**；
  3. 真实高强度战团（t>=11, Σ>=1000）的身材有多少来自**未实现**的卡；
  4. 线上 37.0 的系统开关（trinket / quest / anomaly / tavern spell / prizes）
     与引擎默认 `RulesConfig` 是否一致。

用法：
  python scripts/mechanism_audit.py                    # 用 real_library 库 + matches.jsonl
  python scripts/mechanism_audit.py --obs-scan 376     # 额外扫描 observations/*.jsonl 的 card_id
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import multiprocessing as mp
import os
import re
import statistics

import hsbg_engine as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "data/real_library/library_real_quasi_full.jsonl")
MATCHES = os.path.join(ROOT, "data/real_library/obs/matches.jsonl")
OBS = os.path.join(ROOT, "data/real_library/obs/observations")

# 引擎 Kw（rust/crates/hsbg-engine/src/types.rs::Kw::NAMES）
KW_NAMES = ["TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS", "POISONOUS",
            "STEALTH", "MAGNETIC", "MEGA_WINDFURY", "CLEAVE", "IMMUNE", "IMMUNE_ATTACKING"]
# library 的 kw 位（scripts/parse_firestone_replay_xml.py::KW_BITS 同序取子集）
LIB_KW = ["TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS", "POISONOUS",
          "STEALTH", "MAGNETIC", "MEGA_WINDFURY", "CLEAVE", "IMMUNE", "IMMUNE_ATTACKING"]


def catalog() -> dict[str, dict]:
    return {c["id"]: c for c in json.loads(E.catalog_json())}


def engine_inventory(cat: dict[str, dict]) -> dict:
    kinds = collections.Counter(c["kind"] for c in cat.values())
    inv = {}
    for kind in sorted(kinds):
        rows = [c for c in cat.values() if c["kind"] == kind]
        in_pool = [c for c in rows if c.get("in_pool")]
        impl = [c for c in rows if c.get("implemented")]
        inv[kind] = {
            "total": len(rows),
            "in_pool": len(in_pool),
            "in_pool_implemented": sum(1 for c in in_pool if c.get("implemented")),
            "reachable": sum(1 for c in rows if c.get("reachable")),
            "implemented": len(impl),
        }
    return inv


def real_card_usage() -> dict:
    rows = [json.loads(l) for l in open(LIB)]
    frames = collections.Counter()   # card_id -> 出现帧数
    stat_total = 0
    for r in rows:
        for m in r.get("board_detail") or []:
            frames[m["card_id"]] += 1
            stat_total += int(m["atk"]) + int(m["hp"])
    return {"rows": len(rows), "frames": frames, "stat_total": stat_total}


def strength_attribution(rows, cat) -> dict:
    """t>=11 且 strength>=1000 的真实战团：身材按卡分解，看未实现卡占比。"""
    hi = [r for r in rows if r["turn"] >= 11 and r["strength"] >= 1000]
    total = 0
    by_card = collections.Counter()
    by_card_n = collections.Counter()
    impl_stat = 0
    for r in hi:
        for m in r["board_detail"]:
            s = int(m["atk"]) + int(m["hp"])
            total += s
            by_card[m["card_id"]] += s
            by_card_n[m["card_id"]] += 1
            if cat.get(m["card_id"], {}).get("implemented"):
                impl_stat += s
    top = []
    for cid, s in by_card.most_common(20):
        c = cat.get(cid, {})
        top.append({"card_id": cid, "name": c.get("name"), "tier": c.get("tier"),
                    "stats": s, "share": round(s / max(1, total), 4),
                    "frames": by_card_n[cid], "implemented": c.get("implemented")})
    return {"rows": len(hi), "stat_total": total,
            "implemented_share": round(impl_stat / max(1, total), 4),
            "top_cards": top}


def system_flags() -> dict:
    rows = [json.loads(l) for l in open(MATCHES)]
    out = {}
    for k in ("bgsAnomalies", "bgsHasQuests", "bgsHasSpells", "bgsTrinkets", "bgsHasPrizes"):
        vals = [r.get(k) for r in rows]
        if k in ("bgsAnomalies", "bgsTrinkets"):
            n_true = sum(1 for v in vals if v and any(v))
        else:
            n_true = sum(1 for v in vals if v is True)
        out[k] = {"true": n_true, "n": len(vals), "rate": round(n_true / max(1, len(vals)), 4)}
    out["build_numbers"] = dict(collections.Counter(str(r.get("buildNumber")) for r in rows).most_common(5))
    return out


_RE_CID = re.compile(r'"card_id":"([^"]+)"')


def _scan_one(path):
    with open(path, "r", errors="ignore") as f:
        txt = f.read()
    return collections.Counter(_RE_CID.findall(txt))


def obs_scan(limit: int) -> dict:
    files = sorted(glob.glob(os.path.join(OBS, "*.jsonl")))[:limit]
    total = collections.Counter()
    with mp.Pool(min(32, os.cpu_count() or 1)) as pool:
        for c in pool.imap_unordered(_scan_one, files, chunksize=2):
            total.update(c)
    return {"files": len(files), "distinct": len(total), "counts": total}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--obs-scan", type=int, default=0)
    ap.add_argument("--out", default="runs/ceiling_probe/mechanism_audit.json")
    args = ap.parse_args()

    cat = catalog()
    inv = engine_inventory(cat)
    rows = [json.loads(l) for l in open(LIB)]
    usage = real_card_usage()
    attr = strength_attribution(rows, cat)
    flags = system_flags()

    frames = usage["frames"]
    missing = {cid: n for cid, n in frames.items() if cid not in cat}
    notimpl = {cid: n for cid, n in frames.items() if cid in cat and not cat[cid].get("implemented")}
    kinds_seen = collections.Counter(cat[cid]["kind"] for cid in frames if cid in cat)
    kw_freq = collections.Counter()
    for r in rows:
        for m in r.get("board_detail") or []:
            k = int(m.get("kw") or 0)
            for i, name in enumerate(LIB_KW):
                if k >> i & 1:
                    kw_freq[name] += 1

    report = {
        "engine": {"version": E.game_version(), "cards": len(cat), "inventory": inv,
                   "defaults": json.loads(E.default_config_json()),
                   "keywords_supported": KW_NAMES},
        "real_library": {
            "rows": usage["rows"],
            "distinct_minion_cards": len(frames),
            "missing_from_engine": {"n": len(missing), "frames": sum(missing.values()),
                                    "cards": sorted(missing)[:20]},
            "in_engine_but_unimplemented": {"n": len(notimpl),
                                            "frames": sum(notimpl.values()),
                                            "frame_share": round(sum(notimpl.values()) / max(1, sum(frames.values())), 4),
                                            "cards": sorted(notimpl)[:20]},
            "kinds_seen": dict(kinds_seen),
            "keyword_frames": dict(kw_freq),
            "keyword_unsupported": [k for k in kw_freq if k not in KW_NAMES],
        },
        "strength_attribution_t11plus": attr,
        "systems_real_37": flags,
    }

    if args.obs_scan:
        sc = obs_scan(args.obs_scan)
        counts = sc.pop("counts")
        # 只统计"实体/卡"层面的 id：排除以 e 结尾的附魔（挂件），单独统计
        cards = {c: n for c, n in counts.items() if c in cat}
        unk = {c: n for c, n in counts.items() if c not in cat}
        nonminion = {c: n for c, n in counts.items()
                     if c in cat and cat[c]["kind"] != "minion"}
        sc.update({
            "cards_in_engine": len(cards),
            "cards_not_in_engine": len(unk),
            "not_in_engine_top": dict(collections.Counter(unk).most_common(15)),
            "non_minion_cards_present": len(nonminion),
            "non_minion_top": {c: n for c, n in collections.Counter(nonminion).most_common(15)},
        })
        report["obs_scan"] = sc

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)

    # ---- 打印摘要 ----
    print(f"引擎 {report['engine']['version']}  卡表 {len(cat)} 张")
    print(f"{'kind':16s} {'pool':>6s} {'pool_impl':>9s} {'reach':>6s} {'impl':>6s} {'total':>6s}")
    for k, v in inv.items():
        print(f"{k:16s} {v['in_pool']:6d} {v['in_pool_implemented']:9d} {v['reachable']:6d} "
              f"{v['implemented']:6d} {v['total']:6d}")
    print(f"\n真实库 {usage['rows']} 行, 去重随从 {len(frames)} 张")
    print(f"  引擎缺卡: {len(missing)} 张 / {sum(missing.values())} 帧")
    print(f"  引擎有但未实现: {len(notimpl)} 张 / {sum(notimpl.values())} 帧 "
          f"({report['real_library']['in_engine_but_unimplemented']['frame_share']:.2%})")
    print(f"  真实关键词帧: {dict(kw_freq)}")
    print(f"\nt>=11 且 Σ>=1000 的真实战团 {attr['rows']} 行: "
          f"已实现卡贡献 {attr['implemented_share']:.2%} 身材")
    for c in attr["top_cards"][:12]:
        print(f"   {c['card_id']:16s} {c['stats']:8d} ({c['share']:6.2%}) impl={c['implemented']} {c['name']}")
    print("\n线上 37.0 系统开关（matches.jsonl）:")
    for k in ("bgsAnomalies", "bgsHasQuests", "bgsHasSpells", "bgsTrinkets", "bgsHasPrizes"):
        v = flags[k]
        print(f"   {k:16s} {v['true']:4d}/{v['n']} = {v['rate']:.1%}")
    print(f"\n[{args.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
