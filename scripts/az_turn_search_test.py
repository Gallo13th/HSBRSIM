"""Rust TurnSearch 基线：seat0 回合内 pairwise 搜索 vs 7 个引擎 bot。

与 `az_pure_search_test.py` 不同：这里 seat0 用 `hsbg_engine.turn_search`
（当前回合状态枚举 + 真实 pairwise 战斗），不是 bot full-game rollout。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

import numpy as np

import hsbg_engine as E


def _initialise_heroes(g: E.Game) -> None:
    # 每个座位选一个英雄；seat0 可能还有后续 pending（英雄技能/任务等）。
    for p in range(g.num_players):
        if g.needs_action(p):
            g.step(p, g.bot_action(p))
    for _ in range(12):
        legal = np.frombuffer(g.legal_mask(0), dtype=np.uint8).astype(bool)
        if legal[0] or not g.needs_action(0):
            return
        g.step(0, g.bot_action(0))


def run_game(seed: int, *, states_budget: int, samples: int,
             combat_samples: int, max_steps: int) -> dict:
    g = E.Game(seed)
    _initialise_heroes(g)
    decisions = 0
    searches = 0
    states = 0
    combats = 0
    last_action = None
    repeat = 0
    t0 = time.time()
    for _ in range(3000):
        if g.is_over():
            break
        if g.needs_action(0):
            r = E.turn_search(
                g, 0, states_budget=states_budget,
                samples_per_action=samples,
                combat_samples=combat_samples,
                max_steps_per_turn=max_steps, seed=seed & 0x7FFFFFFF,
            )
            action = int(r[1])
            # 进展守卫：TurnSearch 在空的/冻结的局面可能反复选 Refresh/Freeze；
            # 连续两次相同非 EndTurn 动作后强制结束回合（防止单回合死循环）。
            if action == last_action and action != 0:
                repeat += 1
            else:
                repeat = 0
            last_action = action
            if repeat >= 2:
                action = 0
            searches += 1
            states += int(r[3])
            combats += int(r[4])
            g.step(0, action)
            decisions += 1
            if action == 0:
                last_action = None
                repeat = 0
            continue
        acted = False
        for p in range(1, g.num_players):
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
        if not acted:
            break
    places = list(g.placements())
    rank = int(places[0]) if places else 0
    if rank == 0:
        # 未终局：按存活数近似（不应在正常 max_turns 内发生）
        rank = 8
    return {
        "seed": int(seed),
        "rank": rank,
        "top4": rank <= 4,
        "win": rank == 1,
        "turn": int(g.turn),
        "decisions": decisions,
        "searches": searches,
        "mean_states": states / max(1, searches),
        "mean_combats": combats / max(1, searches),
        "seconds": time.time() - t0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=70000)
    ap.add_argument("--states-budget", type=int, default=8)
    ap.add_argument("--samples-per-action", type=int, default=1)
    ap.add_argument("--combat-samples", type=int, default=1)
    ap.add_argument("--max-steps-per-turn", type=int, default=40)
    ap.add_argument("--out", default="runs/turn_search_rust")
    args = ap.parse_args()
    rows = [run_game(args.seed + i, states_budget=args.states_budget,
                     samples=args.samples_per_action,
                     combat_samples=args.combat_samples,
                     max_steps=args.max_steps_per_turn)
            for i in range(args.games)]
    ranks = [r["rank"] for r in rows]
    summary = {
        "games": len(rows),
        "mean_rank": statistics.fmean(ranks),
        "top4_rate": sum(r["top4"] for r in rows) / max(1, len(rows)),
        "win_rate": sum(r["win"] for r in rows) / max(1, len(rows)),
        "mean_decisions": statistics.fmean(r["decisions"] for r in rows),
        "mean_searches": statistics.fmean(r["searches"] for r in rows),
        "mean_states": statistics.fmean(r["mean_states"] for r in rows),
        "mean_combats": statistics.fmean(r["mean_combats"] for r in rows),
        "mean_seconds": statistics.fmean(r["seconds"] for r in rows),
        "config": {
            "states_budget": args.states_budget,
            "samples_per_action": args.samples_per_action,
            "combat_samples": args.combat_samples,
            "max_steps_per_turn": args.max_steps_per_turn,
        },
        "rows": rows,
    }
    import os
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False))
    print("saved", os.path.join(args.out, "report.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
