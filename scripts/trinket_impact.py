#!/usr/bin/env python3
"""统计「加重护手」(`BG36_MagicItem_414`) 对成长曲线的影响。

问题：该饰品「回合结束 +1/+1、每回合翻倍」让**低本阵容**把属性滚得很大，
可能掩盖"该升本换高质量核心"的行为。本脚本量化：

1. 有多少比例的对局会选择它（在未禁用时）；
2. 选它 / 不选它 两条 **强度-回合曲线** 的差异（中位数 + 四分位）；
3. 按**终局 tavern tier** 分组的终局强度分布（同样分两组）。

口径：8 席，seat 0 = 模型 vs 7 引擎 bot，无人类注入，`game_config_json()` 同训练；
`HSBRSIM_BAN_TRINKETS` 若已在环境里设置，引擎报价会剔除被禁饰品（因此"禁用后"那一组
要么不出现、要么比例显著下降）。

用法：
  # A) 未禁用（看模型自然选择时的分布）
  HSBRSIM_BAN_TRINKETS= PYTHONPATH=rust/python:. python scripts/trinket_impact.py \
    --checkpoint runs/az_stage300m_b07/eval/ckpt_150021999.pt --games 96 \
    --out runs/trinket/noban_150m
  # B) 禁用后（对照组）
  HSBRSIM_BAN_TRINKETS=BG36_MagicItem_414 PYTHONPATH=rust/python:. python scripts/trinket_impact.py \
    --checkpoint runs/az_stage300m_b07/eval/ckpt_150021999.pt --games 96 \
    --out runs/trinket/ban_150m
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
TRINKET_ID = "BG36_MagicItem_414"
TRINKET_NAME = "加重护手"


def _trinket_idx() -> int:
    for i in range(1, 20000):
        try:
            info = E.card_info(i)
        except Exception:  # noqa: BLE001
            break
        if not info:
            continue
        if info[0] == TRINKET_ID:
            return i - 1
    return -1


def _board_strength(pj: dict) -> int:
    return sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
               for m in (pj.get("board") or []))


def play_one(seed: int, policy, max_steps: int = 20000) -> dict:
    game = E.Game(int(seed), game_config_json())
    policy.reset()
    tid = _trinket_idx()
    curve = {}
    last_turn = -1
    steps = 0
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pj = json.loads(game.player_json(MODEL_SEAT))
            curve[t] = _board_strength(pj)
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
    trinkets = [int(x) for x in (pj.get("trinkets") or [])]
    placements = [int(x) for x in game.placements()]
    return {
        "seed": int(seed),
        "ok": bool(game.is_over()),
        "turn": int(game.turn),
        "placement": int(placements[MODEL_SEAT]),
        "tier": int(pj.get("tier") or 0),
        "health": int(pj.get("health") or 0),
        "strength_final": _board_strength(pj),
        "units_final": len(pj.get("board") or []),
        "has_trinket": bool(tid >= 0 and tid in trinkets),
        "trinkets": trinkets,
        "curve": {int(k): int(v) for k, v in curve.items()},
    }


def _agg_curve(games, turns):
    out = {}
    for t in turns:
        vals = [g["curve"][t] for g in games if t in g["curve"]]
        if not vals:
            continue
        vals.sort()
        n = len(vals)
        out[t] = {
            "n": n,
            "median": float(st.median(vals)),
            "p25": float(vals[max(0, int(0.25 * (n - 1)))]),
            "p75": float(vals[min(n - 1, int(0.75 * (n - 1)))]),
            "mean": float(sum(vals) / n),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--games", type=int, default=96)
    ap.add_argument("--seed-base", type=int, default=850000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="runs/trinket/impact")
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
        if (i + 1) % 16 == 0:
            print(f"[trinket] {i + 1}/{args.games}", flush=True)

    ok = [g for g in games if g["ok"]]
    with_t = [g for g in ok if g["has_trinket"]]
    without = [g for g in ok if not g["has_trinket"]]
    turns = list(range(6, 19))
    res = {
        "checkpoint": args.checkpoint,
        "games": int(args.games),
        "ban_env": (os.environ.get("HSBRSIM_BAN_TRINKETS", "") or "").strip(),
        "ok": len(ok),
        "with_trinket": {
            "n": len(with_t),
            "placements": {str(k): sum(1 for g in with_t if g["placement"] == k) for k in range(1, 9)},
            "tiers": {str(k): sum(1 for g in with_t if g["tier"] == k) for k in range(3, 8)},
            "curve": _agg_curve(with_t, turns),
            "final_strength_p50": float(st.median([g["strength_final"] for g in with_t])) if with_t else None,
        },
        "without_trinket": {
            "n": len(without),
            "placements": {str(k): sum(1 for g in without if g["placement"] == k) for k in range(1, 9)},
            "tiers": {str(k): sum(1 for g in without if g["tier"] == k) for k in range(3, 8)},
            "curve": _agg_curve(without, turns),
            "final_strength_p50": float(st.median([g["strength_final"] for g in without])) if without else None,
        },
        # 按终局 tier 分组的终局强度
        "by_final_tier": {},
        "raw": games,
    }
    for tier in range(3, 8):
        gw = [g["strength_final"] for g in with_t if g["tier"] == tier]
        gn = [g["strength_final"] for g in without if g["tier"] == tier]
        if not gw and not gn:
            continue
        res["by_final_tier"][str(tier)] = {
            "with": {"n": len(gw), "p50": float(st.median(gw)) if gw else None},
            "without": {"n": len(gn), "p50": float(st.median(gn)) if gn else None},
        }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(res, open(args.out + ".json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\n[trinket] ok={len(ok)}  带{TRINKET_NAME}={len(with_t)} "
          f"({100 * len(with_t) / max(1, len(ok)):.0f}%)  不带={len(without)}")
    print("turn | 带(中位/四分位)        | 不带(中位/四分位)")
    for t in turns:
        a = res["with_trinket"]["curve"].get(t)
        b = res["without_trinket"]["curve"].get(t)
        fmt = lambda c: ("%6.0f (%.0f-%.0f, n=%d)" % (c["median"], c["p25"], c["p75"], c["n"])
                         if c else "—")
        print(f"{t:4d} | {fmt(a)} | {fmt(b)}")
    print("\n终局 tier | 带: n / 终局强度p50 | 不带: n / 终局强度p50")
    for tier, d in res["by_final_tier"].items():
        w, o = d["with"], d["without"]
        print(f"T{tier}       | {w['n']:3d} / {('—' if w['p50'] is None else '%.0f' % w['p50']):>8} "
              f"| {o['n']:3d} / {('—' if o['p50'] is None else '%.0f' % o['p50']):>8}")
    print(f"[out] {args.out}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
