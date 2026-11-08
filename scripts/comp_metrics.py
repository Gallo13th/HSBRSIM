#!/usr/bin/env python3
"""盘面「复利骨架」指标：放大器占比 / 重复张数 / 高本卡频。

用于 B09 的判据：人类 6 本盘面的放大器卡位占比 ~7.0%、每唯一卡 ~1.14 张；
B08（强制升本）是 0.0% / 1.06。

用法：
  python scripts/comp_metrics.py runs/lineups/b09_150m_top2.json
  python scripts/comp_metrics.py --human          # 只算人类 6 本参考
"""
from __future__ import annotations
import argparse, collections, json, os, sys, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
import hsbg_engine as E  # noqa: E402

#: 放大器（"复利"骨架）：战吼双倍 / 回合末双倍 / 亡语双倍
AMPLIFIERS = {"布莱恩·铜须", "达卡莱附魔师", "提图斯·瑞文戴尔"}
NAME: dict = {}


def name(idx: int) -> str:
    if idx not in NAME:
        try:
            info = E.card_info(int(idx) + 1)
        except Exception:  # noqa: BLE001
            info = None
        NAME[idx] = (info[2] or info[1]) if info else f"#{idx}"
    return NAME[idx]


def tier(idx: int) -> int:
    try:
        info = E.card_info(int(idx) + 1)
        return int(info[3]) if info else 0
    except Exception:  # noqa: BLE001
        return 0


def _stats(boards: list) -> dict:
    slots = sum(sum(b.values()) for b in boards)
    uniq = sum(len(b) for b in boards)
    amps = sum(v for b in boards for k, v in b.items() if name(k) in AMPLIFIERS)
    t5 = sum(v for b in boards for k, v in b.items() if tier(k) >= 5)
    cnt = collections.Counter()
    for b in boards:
        cnt.update(b)
    return {
        "boards": len(boards), "slots": slots,
        "copies_per_unique": slots / max(1, uniq),
        "amplifier_slot_ratio": amps / max(1, slots),
        "tier5plus_slot_ratio": t5 / max(1, slots),
        "top_cards": [(name(c), tier(c), n / max(1, slots)) for c, n in cnt.most_common(12)],
    }


def human_boards(path: str, min_turn: int = 13, min_tier: int = 6) -> list:
    groups, cur, buf = [], None, collections.Counter()
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if int(d.get("turn") or 0) < min_turn or int(d.get("tier") or 0) < min_tier:
                continue
            det = d.get("board_detail") or []
            if not det:
                continue
            gid = (d.get("game_id"), d.get("file"))
            if cur is not None and gid != cur:
                if buf: groups.append(buf)
                buf = collections.Counter()
            cur = gid
            for m in det:
                buf[int(m.get("card") or 0)] += 1
    if buf: groups.append(buf)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lineups", nargs="?", default="")
    ap.add_argument("--human", action="store_true")
    ap.add_argument("--human-path", default="data/real_library/library_real_quasi_full.jsonl")
    args = ap.parse_args()
    if args.human or not args.lineups:
        s = _stats(human_boards(args.human_path))
        print("[人类 6 本参考] boards=%d slots=%d 放大器占比=%.2f%% T5+占比=%.2f%% 每唯一卡=%.2f"
              % (s["boards"], s["slots"], 100 * s["amplifier_slot_ratio"],
                 100 * s["tier5plus_slot_ratio"], s["copies_per_unique"]))
        for nm, t, r in s["top_cards"]:
            print("   %-16s T%s %.2f%%" % (nm, t, 100 * r))
    if args.lineups:
        d = json.load(open(args.lineups, encoding="utf-8"))
        # 用**全部**对局（`all`），不是只显示的前 N 行（`rows`）——否则 8 个盘面的
        # 1 张卡会被读成 1.79%，与 45 个盘面的 0.64% 差 3 倍（B09@50M 踩过这个坑）。
        boards = []
        src = d.get("all") or d.get("rows") or []
        for g in src:
            if src is not d.get("rows") and not g.get("ok"):
                continue
            m = g.get("model") or {}
            if src is not d.get("rows") and not (0 < int(m.get("placement") or 0) <= 2):
                continue
            b = collections.Counter(u["card"] for u in (m.get("board") or []))
            if b: boards.append(b)
        s = _stats(boards)
        print("\n[%s] boards=%d slots=%d 放大器占比=%.2f%% T5+占比=%.2f%% 每唯一卡=%.2f"
              % (os.path.basename(args.lineups), s["boards"], s["slots"],
                 100 * s["amplifier_slot_ratio"], 100 * s["tier5plus_slot_ratio"],
                 s["copies_per_unique"]))
        for nm, t, r in s["top_cards"]:
            print("   %-16s T%s %.2f%%" % (nm, t, 100 * r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
