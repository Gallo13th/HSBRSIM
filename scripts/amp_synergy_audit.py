#!/usr/bin/env python3
"""审计"带放大器的盘面"里，其余随从到底有没有和放大器协同。

协同定义（按放大器文本）：
- 提图斯·瑞文戴尔（亡语额外触发一次）→ 需要 **亡语** 随从
- 达卡莱附魔师（回合结束效果触发两次）→ 需要 **回合结束** 随从
- 布莱恩·铜须（战吼触发两次）→ 需要 **战吼** 随从

分类依据：catalog_json 的 ``text_zh``（关键词匹配）。输出每盘面的
"协同张数 / 无关张数"，以及全局汇总和"空协同盘面"清单。

用法： python scripts/amp_synergy_audit.py <lineups.json> [--top N]
"""
from __future__ import annotations
import argparse, collections, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
import hsbg_engine as E  # noqa: E402

AMP_NEEDS = {
    "提图斯·瑞文戴尔": "亡语",
    "达卡莱附魔师": "回合结束",
    "布莱恩·铜须": "战吼",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lineups")
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args(argv)
    cat = {int(c["cid"]): c for c in json.loads(E.catalog_json())}

    def card(cid):
        return cat.get(int(cid)) or {}

    def nm(cid):
        return card(cid).get("name_zh") or f"#{cid}"

    def txt(cid):
        return (card(cid).get("text_zh") or "")

    def has_deathrattle(cid):
        return "亡语" in txt(cid) or "亡语" in (card(cid).get("text") or "")

    def has_endturn(cid):
        t = txt(cid)
        return ("回合结束" in t) or ("回合结束时" in t)

    def has_battlecry(cid):
        return "战吼" in txt(cid)

    CHECK = {"提图斯·瑞文戴尔": has_deathrattle,
             "达卡莱附魔师": has_endturn,
             "布莱恩·铜须": has_battlecry}

    d = json.load(open(a.lineups, encoding="utf-8"))
    rows = []
    for g in (d.get("all") or []):
        if not g.get("ok"):
            continue
        place = int(((g.get("model") or {}).get("placement") or 0))
        board = (g.get("model") or {}).get("board") or []
        amps = [nm(u["card"]) for u in board if nm(u["card"]) in AMP_NEEDS]
        if not amps:
            continue
        amps = sorted(set(amps))
        need = [AMP_NEEDS[x] for x in amps]
        syn, other = [], []
        for u in board:
            c = nm(u["card"])
            if c in AMP_NEEDS:
                continue
            ok = any(CHECK[x](int(u["card"])) for x in amps if x in CHECK)
            (syn if ok else other).append(c)
        rows.append(dict(place=place, amps=amps, need=need, syn=syn, other=other,
                         strength=int((g.get("model") or {}).get("strength") or 0)))
    rows.sort(key=lambda r: (r["place"], -r["strength"]))
    print("带放大器的盘面：%d（其中进前二 %d）" % (
        len(rows), sum(1 for r in rows if 0 < r["place"] <= 2)))
    for r in rows[: a.top]:
        print("\n#%d 强度=%s  放大器=%s  需要=%s" % (
            r["place"], r["strength"], "、".join(f"★{x}" for x in r["amps"]), "/".join(r["need"])))
        print("   协同(%d): %s" % (len(r["syn"]), "、".join(r["syn"]) or "**无**"))
        print("   无关(%d): %s" % (len(r["other"]), "、".join(r["other"]) or "—"))
    n = len(rows)
    if n:
        no_syn = [r for r in rows if not r["syn"]]
        both = [r for r in rows if len(r["syn"]) >= 2]
        avg = sum(len(r["syn"]) for r in rows) / n
        print("\n=== 汇总 ===")
        print("盘面数 %d | 平均协同张数 %.2f | 至少 1 张协同 %d | ≥2 张 %d | 零协同 %d" % (
            n, avg, n - len(no_syn), len(both), len(no_syn)))
        cnt = collections.Counter()
        for r in rows:
            for c in r["syn"]:
                cnt[c] += 1
        print("协同卡频次:", ", ".join("%s×%d" % (k, v) for k, v in cnt.most_common(12)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
