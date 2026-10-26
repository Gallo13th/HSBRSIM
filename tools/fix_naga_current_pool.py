#!/usr/bin/env python3
"""当前版本（37 赛季）Naga 不在随从池：从生成产物中移除 Naga 池成员。

这不是数据源重建；只修正已生成 JSON 的池成员标记：
- `data/bg_pool_minions.json` 删除 Naga 条目；
- `data/bg_cards.json` 的 Naga 条目 `is_pool_minion` 置 false；
- `data/bg_summary.json` 重算 pool_minions count/by_tier/by_race；
- `data/p2/cards_37.json` 与 Rust `data/cards.json` 的 Naga 条目移除 minion/tier7 池，
  pool_tag=0、reachable=false。

用法:
    python tools/fix_naga_current_pool.py --check
    python tools/fix_naga_current_pool.py --apply
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAGA = 92
POOL_KEYS = ("minion", "tier7")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_naga_record(rec: dict) -> bool:
    return int(rec.get("card_race") or 0) == NAGA


def is_naga_card(card: dict) -> bool:
    races = card.get("races") or []
    return NAGA in races or "NAGA" in races


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pool_path = ROOT / "data/bg_pool_minions.json"
    cards_path = ROOT / "data/bg_cards.json"
    summary_path = ROOT / "data/bg_summary.json"
    p2_path = ROOT / "data/p2/cards_37.json"
    rust_path = ROOT / "rust/crates/hsbg-engine/data/cards.json"

    pool = load(pool_path)
    cards = load(cards_path)
    summary = load(summary_path)
    p2 = load(p2_path)
    rust = load(rust_path)

    new_pool = [x for x in pool if not is_naga_record(x)]
    changed_pool = len(pool) - len(new_pool)

    new_cards = []
    changed_cards = 0
    for rec in cards:
        if is_naga_record(rec) and rec.get("is_pool_minion"):
            rec = dict(rec)
            rec["is_pool_minion"] = False
            changed_cards += 1
        new_cards.append(rec)

    counts = Counter(int(x.get("tech_level") or 0) for x in new_pool)
    races = Counter(
        "NONE" if x.get("card_race") is None else str(x.get("card_race"))
        for x in new_pool
    )
    race_names = {
        11: "UNDEAD", 14: "MURLOC", 15: "DEMON", 17: "MECHANICAL",
        18: "ELEMENTAL", 20: "BEAST", 23: "PIRATE", 24: "DRAGON",
        26: "ALL", 43: "QUILBOAR", 92: "NAGA", 126: "ABERRATION",
    }
    by_race = Counter(
        race_names.get(int(x["card_race"]), str(x["card_race"]))
        if x.get("card_race") is not None else "NONE"
        for x in new_pool
    )
    summary["pool_minions"]["count"] = len(new_pool)
    summary["pool_minions"]["by_tier"] = {str(k): v for k, v in sorted(counts.items())}
    summary["pool_minions"]["by_race"] = {k: v for k, v in sorted(by_race.items())}

    changed_p2 = 0
    for card in p2.get("cards", []):
        if is_naga_card(card):
            pools = [p for p in card.get("pools", []) if p not in POOL_KEYS]
            card["pools"] = pools
            card["pool_tag"] = 0
            card["reachable"] = bool(pools)
            changed_p2 += 1

    changed_rust = 0
    for card in rust.get("cards", []):
        if is_naga_card(card):
            pools = [p for p in card.get("pools", []) if p not in POOL_KEYS]
            card["pools"] = pools
            card["pool_tag"] = 0
            card["reachable"] = bool(pools)
            changed_rust += 1

    print(
        f"naga pool removed: {changed_pool}; bg_cards flags: {changed_cards}; "
        f"p2 cards: {changed_p2}; rust cards: {changed_rust}; "
        f"pool count {len(pool)} -> {len(new_pool)}"
    )
    if not args.apply:
        print("check only; pass --apply to write")
        return 0

    dump(pool_path, new_pool)
    dump(cards_path, new_cards)
    dump(summary_path, summary)
    dump(p2_path, p2)
    dump(rust_path, rust)
    print("written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
