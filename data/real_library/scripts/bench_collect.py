#!/usr/bin/env python
"""高并发数据采集吞吐基准：不同 worker 数下的 games/s / steps/s / 单局耗时。

用法::

    python scripts/bench_collect.py --worker-list 1,2,4,8,12 --episodes-per-worker 10

产物：`runs/bench_collect.json` + 控制台表格。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_case(workers: int, episodes_per_worker: int, policy: str,
             seed: int) -> dict:
    from hsbg.rl.collector import collect_trajectories
    import tempfile

    episodes = workers * episodes_per_worker
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / f"bench_{workers}.jsonl"
        t0 = time.perf_counter()
        report = collect_trajectories(
            policy=policy, num_envs=workers, episodes=episodes,
            seed=seed, out_path=out, num_players=8, opponent="heuristic",
            backend="real",
        )
        wall = time.perf_counter() - t0
    # CollectStats dataclass → 通用字段
    def g(name, default=None):
        return getattr(report, name, default)

    episodes_done = int(g("new_episodes", g("episodes", episodes)) or episodes)
    steps = int(g("new_steps", g("steps", 0)) or 0)
    ranks = list(g("episode_seeds", []) or [])
    mean_rank = g("mean_rank")
    return {
        "workers": workers,
        "episodes": episodes_done,
        "steps": steps,
        "wall_s": round(wall, 2),
        "games_per_s": round(episodes_done / wall, 2),
        "steps_per_s": round(steps / wall, 0) if steps else 0,
        "ms_per_game": round(wall / max(1, episodes_done) * 1000, 0),
        "mean_rank": (round(float(mean_rank), 3) if mean_rank is not None
                      else None),
        "invalid": int(g("invalid_actions", 0) or 0),
        "errors": int(g("errors", 0) or 0),
        "truncated": int(g("truncated", 0) or 0),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker-list", default="1,2,4,8")
    ap.add_argument("--episodes-per-worker", type=int, default=10)
    ap.add_argument("--policy", default="teacher")
    ap.add_argument("--seed", type=int, default=9000)
    ap.add_argument("--json", default="runs/bench_collect.json")
    args = ap.parse_args(argv)

    workers_list = [int(x) for x in args.worker_list.split(",") if x.strip()]
    rows = []
    for w in workers_list:
        try:
            row = run_case(w, args.episodes_per_worker, args.policy, args.seed)
        except Exception as exc:  # noqa: BLE001 - 基准脚本不应中断
            row = {"workers": w, "error": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"policy": args.policy, "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")
    # 简易加速比
    base = next((r for r in rows if r.get("workers") == 1
                 and "games_per_s" in r), None)
    if base:
        print(f"\n{'workers':>8} {'games/s':>9} {'speedup':>8} {'steps/s':>9}")
        for r in rows:
            if "games_per_s" not in r:
                continue
            print(f"{r['workers']:>8} {r['games_per_s']:>9} "
                  f"{r['games_per_s'] / base['games_per_s']:>8.2f}x "
                  f"{r['steps_per_s']:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
