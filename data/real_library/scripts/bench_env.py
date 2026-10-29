#!/usr/bin/env python
"""环境性能/稳定性基准（回归用）。

用法::

    python scripts/bench_env.py --seeds 20 --players 8
    python scripts/bench_env.py --seeds 20 --agent random --opponent heuristic

输出（stdout，ASCII 标签以兼容 Windows 控制台）：
- 每 seed 一行：名次 / 回合 / 步数 / 耗时 / 引擎错误；
- 汇总：崩溃数、单局耗时 min/avg/max、平均回合/步数、招募步耗时、
  end_turn 耗时、引擎/选择/非法动作错误数；
- ``--json path`` 可选：把汇总写成 JSON（默认不写文件）。

退出码：0 = 全部跑完且 0 崩溃；1 = 有崩溃。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.agents.heuristic import HeuristicPolicy  # noqa: E402
from hsbg.agents.registry import make_opponent  # noqa: E402
from hsbg.env import BattlegroundsEnv  # noqa: E402
from hsbg.env.spec import ActionKind, CandidateAction  # noqa: E402


def _pick_action(policy, env, obs) -> CandidateAction:
    if obs.phase == "choice":
        return CandidateAction(kind=ActionKind.CHOOSE.value,
                               option=policy.choose_option_index(obs))
    desc = policy.choose(env.game, env.agent_hero)
    if desc is None:
        return CandidateAction(kind=ActionKind.END_TURN.value)
    return desc.to_candidate()


def _resolve_index(obs, action: CandidateAction):
    sig = action.signature()
    for i, cand in enumerate(obs.candidates):
        if cand.signature() == sig:
            return i, cand
    return None, None


def run_episode(seed: int, args) -> dict:
    policy = make_opponent(args.agent) if args.agent in ("random",) \
        else HeuristicPolicy()
    env = BattlegroundsEnv(num_players=args.players,
                           opponent=args.opponent,
                           max_turns=args.max_turns,
                           seed=seed)
    t0 = time.perf_counter()
    obs = env.reset(seed=seed)
    reset_ms = (time.perf_counter() - t0) * 1000.0
    recruit_ms: list = []
    end_turn_ms: list = []
    steps = 0
    terminated = truncated = False
    info: dict = {}
    while True:
        steps += 1
        action = _pick_action(policy, env, obs)
        is_end = action.kind == ActionKind.END_TURN.value
        t1 = time.perf_counter()
        obs, _reward, terminated, truncated, info = env.step(action)
        dt = (time.perf_counter() - t1) * 1000.0
        (end_turn_ms if is_end else recruit_ms).append(dt)
        if terminated or truncated:
            break
        if steps > args.max_steps:
            raise RuntimeError(f"seed={seed} exceeded {args.max_steps} steps")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    stats = env.stats
    result = {
        "seed": seed,
        "rank": int(info.get("rank", 0)),
        "turn": int(info.get("turn", 0)),
        "steps": steps,
        "elapsed_ms": elapsed_ms,
        "reset_ms": reset_ms,
        "recruit_step_avg_ms": statistics.mean(recruit_ms) if recruit_ms else 0.0,
        "recruit_step_max_ms": max(recruit_ms) if recruit_ms else 0.0,
        "end_turn_avg_ms": statistics.mean(end_turn_ms) if end_turn_ms else 0.0,
        "end_turn_max_ms": max(end_turn_ms) if end_turn_ms else 0.0,
        "engine_errors": int(stats.get("engine_errors", 0)),
        "choice_errors": int(stats.get("choice_errors", 0)),
        "opponent_rejects": int(stats.get("opponent_rejects", 0)),
        "invalid": int(stats.get("invalid", 0)),
        "terminated_reason": str(info.get("terminated_reason", "")),
        "error": None,
    }
    env.close()
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Battlegrounds env benchmark")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--opponent", default="heuristic")
    ap.add_argument("--agent", default="heuristic",
                    help="agent policy: heuristic/random")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=4000)
    ap.add_argument("--json", default=None, help="write summary json to path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    results = []
    crashes = 0
    for i in range(args.seeds):
        seed = args.seed_base + i
        try:
            r = run_episode(seed, args)
        except Exception as exc:                          # noqa: BLE001
            crashes += 1
            print(f"CRASH seed={seed}: {type(exc).__name__}: {exc}",
                  flush=True)
            traceback.print_exc(limit=4)
            continue
        results.append(r)
        if args.verbose:
            print(f"seed={seed:4d} rank={r['rank']} turn={r['turn']:2d} "
                  f"steps={r['steps']:4d} ms={r['elapsed_ms']:6.0f} "
                  f"engine_err={r['engine_errors']}", flush=True)

    if not results:
        print("no successful episodes")
        return 1

    def _stat(key):
        vals = [r[key] for r in results]
        return {"min": min(vals), "avg": statistics.mean(vals),
                "max": max(vals)}

    summary = {
        "episodes": len(results),
        "crashes": crashes,
        "players": args.players,
        "opponent": args.opponent,
        "agent": args.agent,
        "game_ms": _stat("elapsed_ms"),
        "reset_ms": _stat("reset_ms"),
        "turns": _stat("turn"),
        "steps": _stat("steps"),
        "recruit_step_ms": {"avg": statistics.mean(
            [r["recruit_step_avg_ms"] for r in results]),
            "max": max(r["recruit_step_max_ms"] for r in results)},
        "end_turn_ms": {"avg": statistics.mean(
            [r["end_turn_avg_ms"] for r in results]),
            "max": max(r["end_turn_max_ms"] for r in results)},
        "engine_errors": sum(r["engine_errors"] for r in results),
        "choice_errors": sum(r["choice_errors"] for r in results),
        "opponent_rejects": sum(r["opponent_rejects"] for r in results),
        "invalid": sum(r["invalid"] for r in results),
        "ranks": [r["rank"] for r in results],
    }
    print("-" * 78)
    print(f"episodes={summary['episodes']} crashes={summary['crashes']} "
          f"players={args.players} opponent={args.opponent} "
          f"agent={args.agent}")
    print(f"game_ms   min={summary['game_ms']['min']:.0f} "
          f"avg={summary['game_ms']['avg']:.0f} "
          f"max={summary['game_ms']['max']:.0f}")
    print(f"reset_ms  avg={summary['reset_ms']['avg']:.1f}")
    print(f"turns     min={summary['turns']['min']:.0f} "
          f"avg={summary['turns']['avg']:.1f} "
          f"max={summary['turns']['max']:.0f}")
    print(f"steps     min={summary['steps']['min']:.0f} "
          f"avg={summary['steps']['avg']:.1f} "
          f"max={summary['steps']['max']:.0f}")
    print(f"recruit_step_ms avg={summary['recruit_step_ms']['avg']:.2f} "
          f"max={summary['recruit_step_ms']['max']:.2f}")
    print(f"end_turn_ms     avg={summary['end_turn_ms']['avg']:.1f} "
          f"max={summary['end_turn_ms']['max']:.1f}")
    print(f"errors engine={summary['engine_errors']} "
          f"choice={summary['choice_errors']} "
          f"opponent_rejects={summary['opponent_rejects']} "
          f"invalid={summary['invalid']}")
    print(f"ranks={summary['ranks']}")

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"summary written to {path}")
    return 1 if crashes else 0


if __name__ == "__main__":
    sys.exit(main())
