"""机制审计（task-7）：供给 / 卡面数值 / 触发放大。

三块：
1. **供给**：教师 12 局，逐回合读 view 的 shop，统计「随从数 / 法术数」与 tier，
   对照引擎 `RulesConfig`（shop_minion_slots=[3,4,4,5,5,6,6]、shop_spell_slots=1）
   与线上 37.0（同 3/4/4/5/5/6/7 + 1 法术位）。
2. **卡面数值**：top 复利卡 + 放大器 → 卡表 `implemented/scripted/text` + Rust 实现片段。
3. **触发放大**：从 Rust 源码抽取 `battlecry_mult`/`deathrattle_mult`/`end_of_turn_mult`
   与 `EXTRA_*` flag 赋值，核对「普通 ×2 / 金色 ×3」。

产出 `runs/sandbox_econ/mechanics_audit.json`。
用法：python scripts/mechanics_audit.py --games 12
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hsbg.az.train.economy_sandbox import EconomySandbox, SandboxConfig  # noqa: E402
from compound_script import CompoundPolicy, group_configs  # noqa: E402

#: 线上 37.0 的 tavern 槽位（tier 1..7）
REAL_MINION_SLOTS = [3, 4, 4, 5, 5, 6, 7]
REAL_SPELL_SLOTS = 1
#: 审计的卡（复利核心 + 放大器 + 触发器）
AUDIT_CARDS = [
    ("BG20_GEM", "Blood Gem（法术）"),
    ("BG36_762", "Devilish Distractor"),
    ("BG28_633", "Felboar"),
    ("BG36_640", "Gatekeeper Amalgam"),
    ("BG31_176", "Dr. Boom's Monster"),
    ("BG28_707", "Living Azerite"),
    ("BG28_886", "Staff of Enrichment"),
    ("BG30_MagicItem_544t", "Nomi Sticker（大饰品）"),
    ("BG35_123", "Cataclysmic Harbinger"),
    ("BG25_165", "Dr. Boombox"),
    ("BG25_354", "Titus Rivendare"),
    ("BG_LOE_077", "Brann Bronzebeard"),
    ("BG26_ICC_901", "Drakkari Enchanter"),
]


def _engine_config() -> Dict[str, Any]:
    import hsbg_engine as E
    cfg = json.loads(E.default_config_json())
    return {k: cfg.get(k) for k in
            ("shop_minion_slots", "shop_spell_slots", "shop_max_cards",
             "pool_copies_by_tier", "spell_copies_by_tier", "board_size",
             "hand_size", "max_regular_tier")}


def _supply_probe(games: int) -> Dict[str, Any]:
    cfg = group_configs(gold_cap=0)["S3"]
    rows: List[Dict[str, Any]] = []
    by_tier: Dict[int, List[Dict[str, int]]] = {}
    for gi in range(games):
        seed = 880000 + gi
        env = EconomySandbox(cfg)
        obs = env.reset(seed)
        pol = CompoundPolicy(seed=seed)
        last_turn = -1
        while not env.done:
            v = json.loads(env.g.view(0))
            me = v.get("me") or {}
            t = int(v.get("turn") or 0)
            if t != last_turn:      # 只记**回合开始**的商店（不含本回合已买掉的牌）
                last_turn = t
                shop = me.get("shop") or []
                n_min = sum(1 for it in shop if it.get("type") == "minion")
                n_sp = sum(1 for it in shop if it.get("type") != "minion")
                tier = int(me.get("tier") or 0)
                by_tier.setdefault(tier, []).append(
                    {"minions": n_min, "spells": n_sp, "turn": t})
            a = int(pol.act(v, obs.mask))
            obs, _r, _d, _i = env.step(a)
    tiers = sorted(by_tier)
    per_tier = {t: {"minions_p50": float(np.percentile(
        [r["minions"] for r in by_tier[t]], 50)),
        "spells_p50": float(np.percentile([r["spells"] for r in by_tier[t]], 50)),
        "samples": len(by_tier[t])} for t in tiers}
    return {"games": games, "engine_slots": _engine_config(),
            "real_minion_slots": REAL_MINION_SLOTS, "real_spell_slots": REAL_SPELL_SLOTS,
            "per_turn_observed": per_tier}


def _card_audit() -> List[Dict[str, Any]]:
    import hsbg_engine as E
    cat = json.loads(E.catalog_json())
    byid = {e["id"]: e for e in cat}
    src_files = glob.glob(os.path.join(ROOT, "rust", "crates", "hsbg-engine", "src",
                                       "content", "*.rs"))
    src_files += glob.glob(os.path.join(ROOT, "rust", "crates", "hsbg-engine", "src",
                                        "*.rs"))
    out = []
    for cid, label in AUDIT_CARDS:
        e = byid.get(cid)
        if not e:
            out.append({"id": cid, "label": label, "found": False})
            continue
        snips = []
        for path in src_files:
            try:
                lines = open(path, encoding="utf-8").read().split("\n")
            except Exception:
                continue
            for i, ln in enumerate(lines):
                if f'"{cid}"' in ln or f'cardid!("{cid}")' in ln:
                    snips.append({"file": os.path.basename(path),
                                  "line": i + 1,
                                  "snippet": "\n".join(lines[i:i + 4])[:280]})
                    if len(snips) >= 4:
                        break
            if len(snips) >= 4:
                break
        out.append({"id": cid, "label": label, "found": True,
                    "name": e.get("name"), "kind": e.get("kind"),
                    "tier": e.get("tier"), "implemented": bool(e.get("implemented")),
                    "scripted": bool(e.get("scripted")), "in_pool": bool(e.get("in_pool")),
                    "text": e.get("text"), "text_zh": e.get("text_zh"),
                    "source_hits": snips})
    return out


def _trigger_audit() -> Dict[str, Any]:
    base = os.path.join(ROOT, "rust", "crates", "hsbg-engine", "src")
    out: Dict[str, Any] = {"engine_rs_snippets": {}, "flag_assignments": []}
    eng = open(os.path.join(base, "engine.rs"), encoding="utf-8").read().split("\n")
    for fn in ("battlecry_mult", "deathrattle_mult", "end_of_turn_mult"):
        for i, ln in enumerate(eng):
            if f"pub fn {fn}" in ln:
                out["engine_rs_snippets"][fn] = "\n".join(eng[i:i + 26])
                break
    mins = open(os.path.join(base, "content", "minions.rs"), encoding="utf-8").read()
    for cid in ("BG25_354", "BG_LOE_077", "BG26_ICC_901"):
        idx = mins.find(f'"{cid}"')
        if idx >= 0:
            out["flag_assignments"].append(
                {"id": cid, "snippet": mins[max(0, idx - 120):idx + 260]})
    out["flags_defined"] = [ln.strip() for ln in
                            open(os.path.join(base, "script.rs"), encoding="utf-8")
                            if "EXTRA_" in ln and "pub const" in ln]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="机制审计：供给/卡面/触发")
    ap.add_argument("--games", type=int, default=12)
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "sandbox_econ",
                                                       "mechanics_audit.json"))
    args = ap.parse_args(argv)
    out = {"supply": _supply_probe(int(args.games)),
           "cards": _card_audit(),
           "triggers": _trigger_audit()}
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"supply": out["supply"]["per_turn_observed"],
                      "engine_slots": out["supply"]["engine_slots"]},
                     ensure_ascii=False, indent=1))
    print("cards:", [(c["id"], c.get("implemented"), c.get("scripted"))
                     for c in out["cards"]])
    print(f"WROTE {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
