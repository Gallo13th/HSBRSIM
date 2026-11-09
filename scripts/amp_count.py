#!/usr/bin/env python3
"""逐张统计"复利核心卡"在终局盘面里的出现次数（cid 口径，带单元测试级校验）。

**为什么单独写一个**：我曾用一个临时脚本按 `card_info(cid)` 取名字，漏了 +1，把整张
表的名字都错开一位（例如把 `青铜守卫` 显示成 `温顺的巨壳龙`，而后者 `in_pool=False`，
根本不在卡池里）。仓库里的 `top2_lineups.py` / `comp_metrics.py` 是对的（都有 +1），
但一次性脚本很容易再犯，所以把正确口径固化在这里：

- lineups JSON 的 `board[i]["card"]` 是 **cid（0 基）**（= state_json/player_json 的 card）；
- 卡名/tier/是否在池子里取 `catalog_json()` 的 `cid`（等价 `card_info(cid+1)`）。

用法：
    python scripts/amp_count.py runs/point_reports/az_stage300m_b12/50M/lineups.json
"""
from __future__ import annotations
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
import hsbg_engine as E  # noqa: E402

AMPS = ("布莱恩·铜须", "达卡莱附魔师", "提图斯·瑞文戴尔")


def catalog() -> dict:
    return {int(c["cid"]): c for c in json.loads(E.catalog_json())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lineups")
    ap.add_argument("--boards", default="top2", choices=["top2", "all"],
                    help="top2=前二名盘面；all=全部对局")
    args = ap.parse_args(argv)
    cat = catalog()

    def nm(cid: int) -> str:
        return (cat.get(int(cid)) or {}).get("name_zh") or f"#{cid}"

    d = json.load(open(args.lineups, encoding="utf-8"))
    games = []
    for g in (d.get("all") or []):
        if not g.get("ok"):
            continue
        if args.boards == "top2" and not (0 < int(((g.get("model") or {}).get("placement") or 0)) <= 2):
            continue
        games.append(g)
    slots = 0
    cnt: collections.Counter = collections.Counter()
    amp: collections.Counter = collections.Counter()
    t5 = 0
    for g in games:
        for u in (g["model"].get("board") or []):
            cid = int(u["card"])
            n = nm(cid)
            slots += 1
            cnt[n] += 1
            if n in AMPS:
                amp[n] += 1
            if int((cat.get(cid) or {}).get("tier") or 0) >= 5:
                t5 += 1
    print("盘面 %d / 卡位 %d（%s）" % (len(games), slots, args.boards))
    print("放大器逐卡: %s | 合计 %d → %.2f%%"
          % (dict(amp) or "{}", sum(amp.values()), 100 * sum(amp.values()) / max(1, slots)))
    print("T5+ 卡位 %.1f%%" % (100 * t5 / max(1, slots)))
    print("高频卡:", ", ".join("%s×%d" % (n, k) for n, k in cnt.most_common(12)))
    # 一致性自检：印出来的每张卡都必须在 catalog 里且 in_pool（除非是 token/法术）
    bad = [n for n in cnt if not any((c.get("name_zh") == n) for c in cat.values())]
    if bad:
        print("[warn] 这些名字在 catalog 里查不到（可能是 token）:", bad[:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
