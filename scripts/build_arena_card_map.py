#!/usr/bin/env python3
"""构建竞技场卡牌下标 → HSBRSIM 下标的映射（TavernArena v2 观测用）。

竞技场跑公开 TavernGym 1.1.0（36.6.3 数据），我们训练用 37.0.0.255790 的 cards.json；
两边的 ``cards`` 数组都是「卡牌下标」，但词表不同。映射按 **卡牌 id 字符串**对齐：
竞技场 catalog 的 index→id，对照我们 cards.json 的 id→index（obs 值 = index+1）。

用法：
  python scripts/build_arena_card_map.py --arena https://rizling.top \
      --out runs/arena/card_map.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "hsbrsim-cardmap/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arena", default="https://rizling.top")
    ap.add_argument("--cards", default=os.path.join(ROOT, "data/p2/cards_37.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "runs/arena/card_map.json"))
    args = ap.parse_args()

    manifest = fetch_json(args.arena.rstrip("/") + "/api/v1/manifest")
    catalog = fetch_json(args.arena.rstrip("/") + "/api/v1/catalog")
    their = {int(c["index"]): str(c["id"]) for c in catalog["cards"]}
    data = json.load(open(args.cards, encoding="utf-8"))
    cards = data["cards"] if isinstance(data, dict) else data
    our = {str(c["id"]): i for i, c in enumerate(cards)}

    mapping = {0: 0}
    missing = []
    for idx, cid in their.items():
        j = our.get(cid)
        if j is None:
            missing.append(cid)
            continue
        mapping[int(idx)] = int(j) + 1
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "arena": args.arena,
            "ruleset_id": manifest.get("ruleset_id"),
            "arena_catalog_sha256": manifest.get("catalog_sha256"),
            "arena_cards": len(their), "our_cards": len(cards),
            "mapped": len(mapping) - 1, "missing_in_ours": missing[:50],
            "note": "arena card index -> our obs card value (our CardId+1); 0=empty/unknown",
            "mapping": mapping,
        }, f, separators=(",", ":"))
    print(json.dumps({"ruleset_id": manifest.get("ruleset_id"),
                      "arena_cards": len(their), "our_cards": len(cards),
                      "mapped": len(mapping) - 1,
                      "missing": len(missing), "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
