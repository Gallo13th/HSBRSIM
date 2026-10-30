#!/usr/bin/env python3
"""对局质量监控：逐回合记录我方战团强度/经济，并与真实 10k+ MMR 同 turn 分位对比。

指标（learner seat）：
- board_strength = Σ(atk+hp)，board_count，tier，gold，health，turn
- 死亡回合、死亡时战团强度、每 turn 的强度分位
对比基准：data/real_library/strength_calibration.json 的 real p50/p75/p90（分 turn）。

用法::

  PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
    --checkpoint runs/champion_c0_1746.pt --device cuda:2 --games 256 \
    --seed-base 520000 --out runs/quality/champ_1746.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, mask_from_bytes, obs_arrays  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402


def _board_stats(pj: dict) -> dict:
    board = pj.get("board") or []
    strength = 0
    for m in board:
        strength += int(m.get("atk") or 0) + int(m.get("hp") or 0)
    return {"strength": strength, "count": len(board)}


def _play(seed: int, policy, q: dict) -> dict | None:
    """跑一局；返回 {'placement','death_turn','death_strength','turns':[{...}]}。"""
    import hsbg_engine as E

    game = E.Game(seed=int(seed))
    policy.reset()
    turns = []
    last_turn = -1
    while not game.is_over():
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pj = json.loads(game.player_json(0))
            bs = _board_stats(pj)
            turns.append({"turn": t, "strength": bs["strength"], "count": bs["count"],
                          "tier": int(pj.get("tier") or 0), "gold": int(pj.get("gold") or 0),
                          "health": int(pj.get("health") or 0),
                          "alive": bool(pj.get("alive", True))})
        acted = False
        for p in range(8):
            if game.is_over():
                break
            while game.needs_action(p):
                acted = True
                if p == 0:
                    a = int(policy.decide(game, 0).action)
                    m = mask_from_bytes(game.legal_mask(0))
                    if not (0 <= a < 245 and bool(m[a])):
                        nz = np.flatnonzero(m)
                        a = int(nz[0]) if nz.size else 0
                    game.step(0, a)
                else:
                    game.bot_play(p)
                if game.is_over():
                    break
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    placements = list(game.placements())
    death_turn = None
    death_strength = None
    alive_rows = [row for row in turns if row["alive"]]
    if alive_rows:
        # 取死亡前最后一个「非空战团」回合；若最后一行恰好被清空（终局/战斗后），回退一格
        pick = alive_rows[-1]
        for row in reversed(alive_rows):
            if row["strength"] > 0:
                pick = row
                break
        death_turn, death_strength = pick["turn"], pick["strength"]
    return {"placement": int(placements[0]), "death_turn": death_turn,
            "death_strength": death_strength, "turns": turns}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/champion_c0_1746.pt")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=256)
    ap.add_argument("--seed-base", type=int, default=520000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--calibration", default="data/real_library/strength_calibration.json")
    ap.add_argument("--out", default="runs/quality/quality.json")
    args = ap.parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    from hsbg.az.train.ppo import CollectConfig
    cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps))
    policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                               seed=int(args.seed_base), move_model=False)

    rows = []
    for g in range(int(args.games)):
        r = _play(int(args.seed_base) + g, policy, cfg.__dict__)
        if r:
            rows.append(r)
    # 聚合：每 turn 的强度分位
    by_turn: dict[int, list[int]] = {}
    deaths: dict[int, list[int]] = {}
    tiers: dict[int, list[int]] = {}
    golds: dict[int, list[int]] = {}
    for r in rows:
        for row in r["turns"]:
            by_turn.setdefault(row["turn"], []).append(row["strength"])
            tiers.setdefault(row["turn"], []).append(row["tier"])
            golds.setdefault(row["turn"], []).append(row["gold"])
        dt = r["death_turn"] or 0
        if r["placement"] > 1 and r["death_strength"] is not None:
            deaths.setdefault(dt, []).append(r["death_strength"])
    calib = {}
    if os.path.isfile(args.calibration):
        calib = json.load(open(args.calibration))
    summary = []
    for t in sorted(by_turn):
        v = np.asarray(by_turn[t])
        real = (calib.get(str(t)) or {}).get("real") or {}
        summary.append({
            "turn": t, "n": int(v.size),
            "ours_p50": float(np.percentile(v, 50)), "ours_p90": float(np.percentile(v, 90)),
            "ours_max": float(v.max()),
            "real_p50": real.get("p50"), "real_p75": real.get("p75"), "real_p90": real.get("p90"),
            "ratio_p50": (float(np.percentile(v, 50)) / real["p50"]) if real.get("p50") else None,
            "tier_p50": float(np.percentile(tiers[t], 50)),
            "gold_p50": float(np.percentile(golds[t], 50)),
        })
    if deaths:
        all_deaths = [s for v in deaths.values() for s in v]
        death_turns = [t for t, v in deaths.items() for _ in v]
    else:
        all_deaths, death_turns = [], []
    out = {"checkpoint": args.checkpoint, "games": len(rows),
           "seed_base": int(args.seed_base),
           "placements": [r["placement"] for r in rows],
           "mean_rank": float(np.mean([r["placement"] for r in rows])) if rows else None,
           "top4": float(np.mean([r["placement"] <= 4 for r in rows])) if rows else None,
           "win": float(np.mean([r["placement"] == 1 for r in rows])) if rows else None,
           "death_turn_hist": {str(t): len(v) for t, v in sorted(deaths.items())},
           "death_strength_p50": float(np.percentile(all_deaths, 50)) if all_deaths else None,
           "death_strength_mean": float(np.mean(all_deaths)) if all_deaths else None,
           "by_turn": summary,
           "death_turn_p50": float(np.percentile(death_turns, 50)) if death_turns else None}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps({k: out[k] for k in ("games", "mean_rank", "top4", "win",
                                          "death_turn_p50", "death_strength_p50")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
