#!/usr/bin/env python3
"""把前二名阵容打印成可读文本（卡名 + 金色 + 攻/血 + 关键张），并标出复利核心卡。

用法：
    python scripts/show_lineups.py runs/point_reports/az_stage300m_b13/300M/lineups.json \
        --top 12 --mark-mult
"""
from __future__ import annotations
import argparse, collections, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
import hsbg_engine as E  # noqa: E402

AMPS = ("布莱恩·铜须", "达卡莱附魔师", "提图斯·瑞文戴尔")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lineups")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--boards", choices=["top2", "all"], default="top2")
    ap.add_argument("--full", action="store_true", help="打印全部盘面")
    a = ap.parse_args(argv)
    cat = {int(c["cid"]): c for c in json.loads(E.catalog_json())}

    def nm(cid):
        return (cat.get(int(cid)) or {}).get("name_zh") or f"#{cid}"

    def tier(cid):
        return int((cat.get(int(cid)) or {}).get("tier") or 0)

    d = json.load(open(a.lineups, encoding="utf-8"))
    games = []
    for g in (d.get("all") or []):
        if not g.get("ok"):
            continue
        place = int(((g.get("model") or {}).get("placement") or 0))
        if a.boards == "top2" and not (0 < place <= 2):
            continue
        games.append((place, g))
    games.sort(key=lambda x: x[0])
    print("共 %d 局（%s）" % (len(games), a.boards))
    n = len(games) if a.full else min(a.top, len(games))
    for place, g in games[:n]:
        m = g["model"]
        board = m.get("board") or []
        amps = [nm(u["card"]) for u in board if nm(u["card"]) in AMPS]
        t5 = sum(1 for u in board if tier(u["card"]) >= 5)
        gold = sum(1 for u in board if u.get("golden"))
        # 张数统计（同名卡出现次数）
        cnt = collections.Counter(nm(u["card"]) for u in board)
        dup = {k: v for k, v in cnt.items() if v > 1}
        print("\n#%d  name=%s  turn=%s  tier=%s  strength=%s" % (
            place, g.get("hero") or "", m.get("turn"), m.get("tier"), m.get("strength")))
        print("   放大器: %s | T5+: %d/7 | 金色: %d | 成对: %s" % (
            "、".join(amps) if amps else "无", t5, gold,
            ", ".join("%s×%d" % (k, v) for k, v in dup.items()) if dup else "无"))
        cells = []
        for u in board:
            c = nm(u["card"])
            mark = "★" if c in AMPS else ""
            g_ = "金" if u.get("golden") else ""
            cells.append("%s%s%s(%d/%d)" % (mark, c, g_, int(u.get("atk") or 0), int(u.get("hp") or 0)))
        print("   " + "、".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
