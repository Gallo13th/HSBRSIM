#!/usr/bin/env python3
"""卡牌影响统计：哪些卡被"常选"、以及选中它们的对局强度曲线差多少。

问题：模型在低本（3–4 本）把盘面属性滚得很高，疑似依赖某些"每回合/每购买成长"的小核心
（虔诚的萨特唤魔者 / 泰蕾苟萨 / 永恒骑士 / 夺金健将 …）。本脚本用足够多的对局量化：

1. **出场率**：每张卡在**终局盘面**上出现的对局比例（以及平均张数、金色率）；
2. **影响**：把对局按"终局盘面含卡 X / 不含"分组，比较
   - 强度-回合曲线（中位 + 四分位）
   - **按终局 tier 分层**的终局强度（这是关键：同一 tier 下高低对比）
   - 第 1 名率
3. 可选：把「是否在 t≤10 就上场」也分开（早期核心 vs 后期补强）。

口径：8 席，seat 0 = 模型 vs 7 引擎 bot，无人类注入，`game_config_json()` 同训练
（因此 `HSBRSIM_BAN_TRINKETS` 若已设置则自动生效）。

用法：
  PYTHONPATH=rust/python:. python scripts/card_impact.py \
    --checkpoint runs/az_stage300m_b07/eval/ckpt_2500xxxxx.pt \
    --device cuda:7 --games 448 --out runs/card_impact/b07_250m
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

import hsbg_engine as E  # noqa: E402

from hsbg.az.train.game_rules import game_config_json  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402

MODEL_SEAT = 0

#: 默认关注的"成长型小核心"（名字 -> 引擎卡 index）
DEFAULT_FOCUS = {
    "虔诚的萨特唤魔者": 1868,
    "泰蕾苟萨": 117,
    "永恒骑士": 453,
    "夺金健将": 1640,
    "拔线机": 992,
    "时空船长钩尾": 717,
    "青铜守卫": 3278,
    "黑暗悖论体": 2877,
}


_NAME_IDS = None
_ID_NAME = None
_ID_GOLDEN = None


def _build_index() -> None:
    """扫描卡表：名字 -> 所有变体 index（`_G` 金色、`t3..t9` 分档变体都是独立 index）。"""
    global _NAME_IDS, _ID_NAME, _ID_GOLDEN
    if _NAME_IDS is not None:
        return
    name_ids, id_name, id_golden = {}, {}, {}
    i = 1
    while i < 12000:
        try:
            info = E.card_info(i)
        except Exception:  # noqa: BLE001
            break
        if not info:
            i += 1
            continue
        cid, en, zh, _tier = info
        idx = i - 1
        nm = zh or en or str(cid)
        name_ids.setdefault(nm, set()).add(idx)
        id_name[idx] = nm
        id_golden[idx] = "_G" in str(cid)
        i += 1
    _NAME_IDS, _ID_NAME, _ID_GOLDEN = name_ids, id_name, id_golden


def _name(idx: int) -> str:
    _build_index()
    return _ID_NAME.get(int(idx), f"#{idx}")


def _tier(idx: int) -> int:
    try:
        info = E.card_info(int(idx) + 1)
    except Exception:  # noqa: BLE001
        return 0
    return int(info[3]) if info else 0


def play_one(seed: int, policy, max_steps: int = 20000) -> dict:
    game = E.Game(int(seed), game_config_json())
    policy.reset()
    curve = {}
    first_seen = {}       # card idx -> 首次上场的 turn
    last_turn = -1
    steps = 0
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pj = json.loads(game.player_json(MODEL_SEAT))
            board = pj.get("board") or []
            curve[t] = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in board)
            for m in board:
                for key in (int(m.get("card") or 0),):
                    if key and key not in first_seen:
                        first_seen[key] = t
                for a in (m.get("attached") or []):
                    c = int(a.get("card") if isinstance(a, dict) else a)
                    if c and c not in first_seen:
                        first_seen[c] = t
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == MODEL_SEAT:
                game.step(MODEL_SEAT, int(policy.decide(game, MODEL_SEAT).action))
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break

    pj = json.loads(game.player_json(MODEL_SEAT))
    board = pj.get("board") or []
    final_cards = {}
    for m in board:
        c = int(m.get("card") or 0)
        if not c:
            continue
        rec = final_cards.setdefault(c, {"n": 0, "golden": 0, "atk": 0, "hp": 0})
        rec["n"] += 1
        rec["golden"] += 1 if m.get("golden") else 0
        rec["atk"] += int(m.get("atk") or 0)
        rec["hp"] += int(m.get("hp") or 0)
    placements = [int(x) for x in game.placements()]
    return {
        "seed": int(seed),
        "ok": bool(game.is_over()),
        "turn": int(game.turn),
        "placement": int(placements[MODEL_SEAT]),
        "tier": int(pj.get("tier") or 0),
        "strength_final": sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in board),
        "final_cards": {str(k): v for k, v in final_cards.items()},
        "ever_cards": {str(k): v for k, v in first_seen.items()},
        "curve": {int(k): int(v) for k, v in curve.items()},
        "trinkets": [int(x) for x in (pj.get("trinkets") or [])],
    }


def _quantile(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    if len(v) == 1:
        return float(v[0])
    pos = q * (len(v) - 1)
    lo = int(pos)
    hi = min(len(v) - 1, lo + 1)
    frac = pos - lo
    return float(v[lo] * (1 - frac) + v[hi] * frac)


def _stats(vals):
    if not vals:
        return {"n": 0, "median": None, "p25": None, "p75": None}
    return {"n": len(vals), "median": _quantile(vals, 0.5),
            "p25": _quantile(vals, 0.25), "p75": _quantile(vals, 0.75)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=448)
    ap.add_argument("--seed-base", type=int, default=860000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--top", type=int, default=20, help="出场率榜取前多少张")
    ap.add_argument("--out", default="runs/card_impact/ckpt")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args(argv)

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps), move_guard=True,
                        move_cap=3, move_repeat_limit=2)
    policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                               seed=int(args.seed_base), move_model=False)

    games = []
    for i in range(int(args.games)):
        games.append(play_one(int(args.seed_base) + i, policy, max_steps=int(args.max_steps)))
        if (i + 1) % 32 == 0:
            print(f"[card] {i + 1}/{args.games}", flush=True)

    ok = [g for g in games if g["ok"]]
    n = max(1, len(ok))

    # ---- 出场率（终局盘面 / 全程出现过）----
    # 金色/分档变体是独立卡 index，必须按"名字"聚合后再统计出场率
    _build_index()
    freq = {}
    for g in ok:
        seen = set()
        for c, rec in g["final_cards"].items():
            nm = _name(int(c))
            d = freq.setdefault(nm, {"final_n": 0, "copies": 0, "golden": 0, "ids": set()})
            d["copies"] += rec["n"]
            d["golden"] += rec["golden"]
            d["ids"].add(int(c))
            if nm not in seen:
                d["final_n"] += 1
                seen.add(nm)
    top = sorted(freq.items(), key=lambda kv: -kv[1]["final_n"])[: int(args.top)]
    freq_rows = []
    for nm, d in top:
        ids = sorted(d["ids"], key=lambda x: (not _ID_GOLDEN.get(x, False), _tier(x)))
        base = ids[0] if ids else -1
        freq_rows.append({
            "name": nm, "card": int(base), "tier": _tier(int(base)),
            "variants": ids,
            "final_rate": d["final_n"] / n,
            "final_games": d["final_n"],
            "avg_copies": d["copies"] / max(1, d["final_n"]),
            "golden_rate": d["golden"] / max(1, d["copies"]),
        })

    # ---- 关注卡的影响（分层：按终局 tier）----
    turns = list(range(8, 17))
    focus = {}
    for name, idx in DEFAULT_FOCUS.items():
        ids = {str(x) for x in _NAME_IDS.get(name, {idx})}
        with_g = [g for g in ok if ids & set(g["final_cards"])]
        without = [g for g in ok if not (ids & set(g["final_cards"]))]
        entry = {
            "card": idx, "ids": sorted(int(x) for x in ids),
            "name": name, "tier": _tier(idx),
            "with": {"n": len(with_g),
                     "curve": {t: _stats([g["curve"][t] for g in with_g if t in g["curve"]])
                               for t in turns},
                     "final": _stats([g["strength_final"] for g in with_g]),
                     "first_place": (sum(1 for g in with_g if g["placement"] == 1)
                                     / max(1, len(with_g))),
                     "by_final_tier": {}},
            "without": {"n": len(without),
                        "curve": {t: _stats([g["curve"][t] for g in without if t in g["curve"]])
                                  for t in turns},
                        "final": _stats([g["strength_final"] for g in without]),
                        "first_place": (sum(1 for g in without if g["placement"] == 1)
                                        / max(1, len(without))),
                        "by_final_tier": {}},
        }
        for tier in (3, 4, 5):
            a = [g["strength_final"] for g in with_g if g["tier"] == tier]
            b = [g["strength_final"] for g in without if g["tier"] == tier]
            entry["with"]["by_final_tier"][str(tier)] = _stats(a)
            entry["without"]["by_final_tier"][str(tier)] = _stats(b)
        # 早出场比例
        early = [g for g in with_g
                 if min([int(g["ever_cards"].get(x, 99)) for x in ids] or [99]) <= 10]
        entry["early_rate"] = len(early) / max(1, len(with_g))
        focus[name] = entry

    res = {
        "checkpoint": args.checkpoint,
        "games": int(args.games),
        "ok": len(ok),
        "ban_env": (os.environ.get("HSBRSIM_BAN_TRINKETS", "") or "").strip(),
        "placement_counts": {str(k): sum(1 for g in ok if g["placement"] == k) for k in range(1, 9)},
        "tier_counts": {str(k): sum(1 for g in ok if g["tier"] == k) for k in range(2, 8)},
        "median_final_strength": _quantile([g["strength_final"] for g in ok], 0.5),
        "frequency": freq_rows,
        "focus": focus,
        "raw": [{k: g[k] for k in ("seed", "ok", "turn", "placement", "tier",
                                   "strength_final", "final_cards", "ever_cards",
                                   "curve", "trinkets")} for g in games],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(res, open(args.out + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n[card] ok={len(ok)} 终局强度中位={res['median_final_strength']:.0f} "
          f"tier分布={res['tier_counts']}")
    print("\n== 出场率 Top %d（终局盘面上出现的对局占比）==" % len(freq_rows))
    print("  %-16s T  出场率  平均张数  金色率" % "卡名")
    for r in freq_rows:
        print("  %-16s %d  %5.1f%%  %6.2f  %5.0f%%" %
              (r["name"][:16], r["tier"], 100 * r["final_rate"], r["avg_copies"],
               100 * r["golden_rate"]))
    print("\n== 关注卡：含 vs 不含 ==")
    print("  %-14s  含(n/强度p50/1st)          不含(n/强度p50/1st)        T4强度(含/不含)  早期出场" % "卡名")
    for name, e in focus.items():
        w, o = e["with"], e["without"]
        t4w = w["by_final_tier"]["4"]["median"]
        t4o = o["by_final_tier"]["4"]["median"]
        print("  %-14s  %3d/%6s/%4.0f%%        %3d/%6s/%4.0f%%        %6s/%-6s   %4.0f%%" %
              (name[:14], w["n"], "—" if w["final"]["median"] is None else "%.0f" % w["final"]["median"],
               100 * w["first_place"], o["n"],
               "—" if o["final"]["median"] is None else "%.0f" % o["final"]["median"],
               100 * o["first_place"],
               "—" if t4w is None else "%.0f" % t4w, "—" if t4o is None else "%.0f" % t4o,
               100 * e["early_rate"]))
    print(f"[out] {args.out}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
