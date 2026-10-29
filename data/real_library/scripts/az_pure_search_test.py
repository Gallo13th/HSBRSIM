"""纯搜索能力测试：seat0 用 Rust MCTS + bot-rollout 价值 vs 7 个引擎 bot。

不训练、不用 NN（rollout=True 时 eval_fn 被忽略）；与 heuristic 基线同 seed 比较。

运行（远程）：
  python3 scripts/az_pure_search_test.py --games 100 --sims 1,2,4 \
      --out runs/pure_search --seed 70000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hsbg_engine as E


def _legal(g, seat):
    return np.frombuffer(g.legal_mask(seat), dtype=np.uint8).astype(bool)


def run_game(seed: int, sims: int, mode: str):
    """mode: search_rollout | heuristic. seat0 controlled, others engine bots."""
    g = E.Game(seed=seed)
    decisions = 0
    searches = 0
    last_turn = g.turn
    steps_in_turn = 0
    t0 = time.perf_counter()
    while not g.is_over():
        acted = False
        for p in range(g.num_players):
            if not g.needs_action(p):
                continue
            if p == 0:
                mask = _legal(g, 0)
                if mode == "heuristic":
                    action = int(g.bot_action(0))
                else:
                    if steps_in_turn >= 8:
                        legal = np.nonzero(mask)[0]
                        action = 0 if mask[0] else int(legal[0])
                    else:
                        pi, action, rv, vis = E.mcts_search(
                            g, 0, simulations=int(sims), c_puct=1.5, temperature=1.0,
                            eval_fn=None, seed=seed * 100_003 + decisions,
                            dirichlet_alpha=0.3, dirichlet_epsilon=0.0, rollout=True)
                        searches += 1
                g.step(0, int(action))
                decisions += 1
            else:
                g.bot_play(p)
            acted = True
            if g.turn != last_turn:
                last_turn = g.turn
                steps_in_turn = 0
            else:
                steps_in_turn += 1
            if decisions + searches > 20000:
                raise RuntimeError("game guard")
        if not acted:
            break
    dt = time.perf_counter() - t0
    return {"rank": int(g.placements()[0]), "turns": int(g.turn), "seat0_decisions": decisions,
            "searches": searches, "seconds": dt}


def summarize(rows, label):
    ranks = np.asarray([r["rank"] for r in rows], dtype=np.float32)
    return {
        "label": label,
        "games": len(rows),
        "mean_rank": float(ranks.mean()),
        "top4_rate": float((ranks <= 4).mean()),
        "win_rate": float((ranks == 1).mean()),
        "rank_counts": {int(k): int(v) for k, v in Counter(int(x) for x in ranks).items()},
        "mean_turns": float(np.mean([r["turns"] for r in rows])),
        "mean_seat0_decisions": float(np.mean([r["seat0_decisions"] for r in rows])),
        "mean_seconds_per_game": float(np.mean([r["seconds"] for r in rows])),
        "total_seconds": float(np.sum([r["seconds"] for r in rows])),
        "total_searches": int(np.sum([r["searches"] for r in rows])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100, help="每个配置的局数")
    ap.add_argument("--sims", type=str, default="1,2,4", help="逗号分隔的 MCTS sims")
    ap.add_argument("--seed", type=int, default=70000)
    ap.add_argument("--out", type=str, default="runs/pure_search")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    sims_list = [int(x) for x in args.sims.split(",") if x.strip()]
    print("engine:", E.game_version(), E.db_info(), "rollout search:", hasattr(E, "mcts_search"))
    report = {"engine": E.game_version(), "games_per_config": args.games,
              "seed": args.seed, "configs": {}}

    # heuristic baseline（同 seed 集）
    rows = [run_game(args.seed + gi, 0, "heuristic") for gi in range(args.games)]
    report["configs"]["heuristic"] = summarize(rows, "heuristic")
    print("[heuristic]", json.dumps(report["configs"]["heuristic"], ensure_ascii=False), flush=True)

    for sims in sims_list:
        t0 = time.time()
        rows = [run_game(args.seed + gi, sims, "search_rollout") for gi in range(args.games)]
        summary = summarize(rows, f"search_rollout_sims{sims}")
        summary["wall_seconds"] = time.time() - t0
        report["configs"][f"sims{sims}"] = summary
        print(f"[sims={sims}]", json.dumps(summary, ensure_ascii=False), flush=True)

    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("[saved]", os.path.join(args.out, "report.json"))


if __name__ == "__main__":
    main()
