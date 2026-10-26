"""引擎批量吞吐基准：TavernGym（Rust）vs hsrl2（Python）。

口径
----
* **TavernGym 裸引擎**：``taverngym.run_bot_games(n, seed)``（8 座全 bot，Rust
  侧执行、GIL 释放）→ games/s、ms/局（无观测/策略/环境层开销）。
* **TavernGym BatchEnv**：``BatchEnv(n_games, threads=1/4)``，每轮
  ``observe()`` + 随机 legal 动作 ``step()``（含 Python 侧 numpy 打包），
  报 cycles/s 与 slot-steps/s（说明线程收益与"Python 边界"成本）。
* **hsrl2 整局**：``BattlegroundsEnv`` + ``hsbg.rl.policies.make_policy``
  （random / heuristic）+ 统一 ``run_episode`` harness → games/s、ms/局、
  ms/步。**这是"Python 引擎 + Python 环境 + 每步观测构建"的真实口径**，
  与 TavernGym 裸引擎对比时注意分母不同（见 docs/PERF_ROUTE.md §2）。

用法::

    cd /Users/letiangao/HSAgent/HSBRSIM
    PYTHONPATH=. python3 tools/p2_perf/bench_engine.py --hsrl2-games 10
    # 结果写入 runs/p2_perf/engine.json
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from typing import Any, Dict, List

from tools.p2_perf.common import (
    ROOT,
    machine_info,
    save_json,
    summarize,
)

import sys

if str(ROOT) not in sys.path:                             # noqa: E402
    sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════
# TavernGym（Rust）裸引擎
# ══════════════════════════════════════════════════════════════════════


def bench_taverngym_raw(games: int = 500, seed: int = 0,
                        repeats: int = 3) -> Dict[str, Any]:
    import taverngym

    samples: List[float] = []
    turns: List[int] = []
    for _ in range(int(repeats)):
        t0 = time.perf_counter()
        result_turns = taverngym.run_bot_games(int(games), seed=int(seed))
        samples.append(time.perf_counter() - t0)
        turns = list(result_turns)
    wall = statistics.median(samples)
    return {
        "what": "taverngym.run_bot_games（8 座全 bot，Rust）",
        "games": int(games),
        "seed": int(seed),
        "repeats": int(repeats),
        "wall_seconds_samples": [round(s, 6) for s in samples],
        "median_wall_seconds": round(wall, 6),
        "games_per_second": round(games / wall, 3),
        "ms_per_game": round(wall / games * 1000.0, 4),
        "mean_turns": round(statistics.fmean(turns), 3) if turns else 0.0,
    }


def bench_taverngym_batch(n_games: int = 32, seed: int = 0,
                          threads: int = 1, cycles: int = 60
                          ) -> Dict[str, Any]:
    """BatchEnv：observe+step 一轮为 1 cycle（含 numpy 打包/解包边界）。"""
    import numpy as np
    import taverngym

    env = taverngym.BatchEnv(int(n_games), seed=int(seed),
                             controlled=(0,), threads=int(threads))
    rng = random.Random(int(seed))
    slot_steps = 0
    t0 = time.perf_counter()
    obs = env.observe()
    for _ in range(int(cycles)):
        mask = obs["action_mask"]
        ready = obs["ready"]
        actions = np.zeros(env.n_slots, dtype=np.int64)
        for slot in np.nonzero(ready)[0]:
            legal = np.nonzero(mask[slot])[0]
            if len(legal):
                actions[slot] = int(legal[rng.randrange(len(legal))])
                slot_steps += 1
        obs = None
        _rewards, _dones, info = env.step(actions)
        obs = env.observe()
        if info["placement"].size:
            pass
    wall = time.perf_counter() - t0
    return {
        "what": f"taverngym.BatchEnv(n_games={n_games}, threads={threads}) "
                f"observe+step cycles",
        "n_games": int(n_games),
        "threads": int(threads),
        "cycles": int(cycles),
        "slot_steps": int(slot_steps),
        "wall_seconds": round(wall, 6),
        "cycles_per_second": round(cycles / wall, 3),
        "slot_steps_per_second": round(slot_steps / wall, 3),
        "ms_per_cycle": round(wall / cycles * 1000.0, 3),
        "us_per_slot_step": round(wall / slot_steps * 1e6, 3)
        if slot_steps else 0.0,
    }


# ══════════════════════════════════════════════════════════════════════
# hsrl2（Python）整局
# ══════════════════════════════════════════════════════════════════════


def bench_hsrl2_games(games: int = 8, seed: int = 0,
                      policy_name: str = "random",
                      opponent: str = "heuristic") -> Dict[str, Any]:
    from hsbg.env import BattlegroundsEnv
    from hsbg.rl.api import run_episode
    from hsbg.rl.policies import make_policy

    wall = 0.0
    steps = 0
    turns = 0
    ranks: List[int] = []
    for ep in range(int(games)):
        ep_seed = int(seed) + ep
        env = BattlegroundsEnv(num_players=8, opponent=str(opponent),
                               seed=ep_seed, max_turns=40)
        policy = make_policy(policy_name, seed=ep_seed)
        t0 = time.perf_counter()
        record = run_episode(env, policy, seed=ep_seed, episode_id=ep,
                             max_steps=4000)
        wall += time.perf_counter() - t0
        steps += int(record.steps)
        turns += int(record.turns)
        ranks.append(int(record.rank))
        env.close()
    return {
        "what": f"hsbg.env.BattlegroundsEnv + {policy_name} 整局",
        "policy": str(policy_name),
        "opponent": str(opponent),
        "games": int(games),
        "seed": int(seed),
        "wall_seconds": round(wall, 6),
        "games_per_second": round(games / wall, 3) if wall else 0.0,
        "ms_per_game": round(wall / games * 1000.0, 3) if games else 0.0,
        "steps_total": int(steps),
        "ms_per_step": round(wall / steps * 1000.0, 4) if steps else 0.0,
        "mean_steps": round(steps / games, 3) if games else 0.0,
        "mean_turns": round(turns / games, 3) if games else 0.0,
        "mean_rank": round(statistics.fmean(ranks), 3) if ranks else 0.0,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-games", type=int, default=500)
    parser.add_argument("--batch-games", type=int, default=32)
    parser.add_argument("--batch-cycles", type=int, default=60)
    parser.add_argument("--hsrl2-games", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", type=str,
                        default="runs/p2_perf/engine.json")
    args = parser.parse_args(argv)

    payload: Dict[str, Any] = {"machine": machine_info(),
                               "section": "engine_throughput"}
    payload["taverngym_raw"] = bench_taverngym_raw(
        games=args.engine_games, seed=args.seed)
    payload["taverngym_batch"] = {
        f"threads_{threads}": bench_taverngym_batch(
            n_games=args.batch_games, seed=args.seed, threads=threads,
            cycles=args.batch_cycles)
        for threads in (1, 4)
    }
    payload["hsrl2"] = {
        "random": bench_hsrl2_games(games=args.hsrl2_games, seed=args.seed,
                                    policy_name="random"),
        "heuristic": bench_hsrl2_games(games=args.hsrl2_games, seed=args.seed,
                                       policy_name="heuristic"),
    }
    path = save_json(args.json.split("/")[-1], payload)
    print(f"[bench_engine] saved: {path}")
    raw = payload["taverngym_raw"]
    print(f"taverngym raw : {raw['games_per_second']} games/s, "
          f"{raw['ms_per_game']} ms/局")
    for key, item in payload["hsrl2"].items():
        print(f"hsrl2 {key:9s}: {item['games_per_second']} games/s, "
              f"{item['ms_per_game']} ms/局, {item['ms_per_step']} ms/步")
    for key, item in payload["taverngym_batch"].items():
        print(f"BatchEnv {key}: {item['cycles_per_second']} cycles/s, "
              f"{item['us_per_slot_step']} µs/slot-step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
