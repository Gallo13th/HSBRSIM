"""HSbg Engine 基准（可复现，本机实测用；不参与 pytest）。

度量四项，每项都做 warmup + 多次取中位数：

1. **裸引擎吞吐**：``run_bot_games(n, seed)``（8 座全 bot、纯 Rust 执行、GIL 释放）
   -> games/s、ms/局、平均回合数；
2. **端到端 8 人局**：Python 侧 ``Game`` + ``bot_play`` 驱动完整一局
   -> ms/局（含 Python 调用开销，代表"从 Python 跑一整局"的真实速度）；
3. **BatchEnv 吞吐**：``BatchEnv(n_games, controlled=(0,), threads=t)`` 并行采样
   -> episodes/s、steps/s（训练采样的吞吐口径）；
4. **SoloEnv 观测+决策循环**：``SoloEnv`` 每步 ``observe() + legal_mask() + step()``
   （单学习座位对 7 个 bot，含观测 bytes 构建）-> games/s、ms/局、步/局。

同机同 harness 对照上游 ``taverngym``（若已安装）；``hsrl2`` 是纯 Python 引擎，
没有等价的 ``run_bot_games``，其端到端口径用 ``hsbg.backends.benchmark``（见
``docs/RUST_ENGINE.md``）。

用法::

    python3 rust/bench_engine.py                      # 默认 2000 局裸吞吐 / 20 局端到端
    python3 rust/bench_engine.py --games 1000 --e2e-games 10 --repeats 3
    python3 rust/bench_engine.py --json runs/engine_bench.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

#: 裸吞吐默认局数（一次 run_bot_games 调用）
DEFAULT_GAMES = 2000
#: 端到端默认局数（Python 逐动作驱动，较慢）
DEFAULT_E2E_GAMES = 20
#: SoloEnv 观测+决策循环默认局数
DEFAULT_SOLO_GAMES = 100
#: BatchEnv 默认局数 / 线程数 / 采样步数
DEFAULT_BATCH_GAMES = 64
DEFAULT_BATCH_THREADS = 8
DEFAULT_BATCH_STEPS = 200


def _machine_info() -> dict:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": __import__("os").cpu_count(),
        "python": sys.version.split()[0],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _timeit(fn, repeats: int):
    """warmup 一次后重复计时；返回 (best, median, 最后一次结果)。"""
    warmup = fn()
    del warmup
    times = []
    result = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return min(times), statistics.median(times), result


def _run_game_to_end(game, limit: int = 1000) -> int:
    """用内置 bot 驱动全部座位到终局，返回循环轮数（防御死循环）。"""
    guard = 0
    while not game.is_over() and guard < limit:
        guard += 1
        for p in range(game.num_players):
            if game.needs_action(p):
                game.bot_play(p)
    return guard


def bench_bare(mod, games: int, repeats: int) -> dict:
    best, med, turns = _timeit(lambda: mod.run_bot_games(games, seed=0), repeats)
    return {
        "games": games,
        "best_s": best,
        "median_s": med,
        "games_per_s_best": games / best,
        "games_per_s_median": games / med,
        "ms_per_game_median": med / games * 1000.0,
        "avg_turns": statistics.fmean(turns) if turns else 0.0,
    }


def bench_e2e(mod, games: int, repeats: int) -> dict:
    def run():
        return [_run_game_to_end(mod.Game(seed)) for seed in range(games)]

    best, med, loops = _timeit(run, repeats)
    return {
        "games": games,
        "best_s": best,
        "median_s": med,
        "games_per_s_median": games / med,
        "ms_per_game_median": med / games * 1000.0,
        "avg_seat_sweeps": statistics.fmean(loops),
    }


def bench_solo(mod, games: int, repeats: int) -> dict:
    """SoloEnv 观测+决策循环（单学习座位对 7 bot，含 observations bytes 构建）。"""

    def run():
        steps = 0
        for seed in range(games):
            env = mod.SoloEnv(seed, None, 0)
            while not env.done():
                env.observe()
                mask = np.frombuffer(env.legal_mask(), dtype=np.uint8)
                env.step(int(np.flatnonzero(mask)[0]))
                steps += 1
        return steps

    best, med, steps = _timeit(run, repeats)
    return {
        "games": games,
        "best_s": best,
        "median_s": med,
        "games_per_s_median": games / med,
        "ms_per_game_median": med / games * 1000.0,
        "steps_per_game": steps / games,
    }


def bench_batch(mod, games: int, threads: int, steps: int, repeats: int) -> dict:
    def run():
        env = mod.BatchEnv(n_games=games, seed=0, controlled=(0,), threads=threads)
        obs = env.observe()
        done_episodes = 0
        for _ in range(steps):
            actions = []
            for slot in range(env.n_slots):
                mask = obs["action_mask"][slot]
                actions.append(int(np.flatnonzero(mask)[0]) if mask.any() else 0)
            _, dones, info = env.step(actions)
            done_episodes += int(np.count_nonzero(dones))
            obs = env.observe()
        return done_episodes

    best, med, done = _timeit(run, repeats)
    total_slots = games * steps
    return {
        "n_games": games,
        "threads": threads,
        "steps": steps,
        "episodes_finished": done,
        "best_s": best,
        "median_s": med,
        "episodes_per_s_median": done / med if med else 0.0,
        "slot_steps_per_s_median": total_slots / med,
    }


def _print_table(title: str, rows: list[tuple[str, dict]], fmt) -> None:
    print(f"\n== {title} ==")
    for name, data in rows:
        print(f"  {name:<22} {fmt(data)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="HSbg Engine 基准（hsbg_engine vs 上游 taverngym）")
    ap.add_argument("--games", type=int, default=DEFAULT_GAMES, help="裸吞吐局数")
    ap.add_argument("--e2e-games", type=int, default=DEFAULT_E2E_GAMES, help="端到端局数")
    ap.add_argument("--solo-games", type=int, default=DEFAULT_SOLO_GAMES, help="SoloEnv 循环局数")
    ap.add_argument("--batch-games", type=int, default=DEFAULT_BATCH_GAMES)
    ap.add_argument("--batch-threads", type=int, default=DEFAULT_BATCH_THREADS)
    ap.add_argument("--batch-steps", type=int, default=DEFAULT_BATCH_STEPS)
    ap.add_argument("--repeats", type=int, default=3, help="每项重复次数（取中位数）")
    ap.add_argument("--json", type=str, default=None, help="结果写 JSON 的路径")
    args = ap.parse_args()

    import hsbg_engine

    modules: list[tuple[str, object]] = [("hsbg_engine", hsbg_engine)]
    try:
        import taverngym

        modules.append(("taverngym(上游)", taverngym))
    except ImportError:
        print("[warn] 上游 taverngym 未安装，只测 hsbg_engine", file=sys.stderr)

    report = {
        "machine": _machine_info(),
        "engine_version": hsbg_engine.version(),
        "game_version": hsbg_engine.game_version(),
        "server_rules_version": hsbg_engine.server_rules_version(),
        "source_hash": hsbg_engine.build_info()["source_hash"],
        "data_info": hsbg_engine.data_info(),
        "repeats": args.repeats,
        "results": {},
    }

    bare_rows = []
    for name, mod in modules:
        r = bench_bare(mod, args.games, args.repeats)
        report["results"].setdefault(name, {})["bare"] = r
        bare_rows.append((name, r))
    _print_table(
        f"裸引擎 run_bot_games({args.games}, seed=0)（8 座全 bot）",
        bare_rows,
        lambda r: (
            f"{r['games_per_s_median']:.1f} games/s, "
            f"{r['ms_per_game_median']:.2f} ms/局, 平均 {r['avg_turns']:.1f} 回合"
        ),
    )

    e2e_rows = []
    for name, mod in modules:
        r = bench_e2e(mod, args.e2e_games, args.repeats)
        report["results"].setdefault(name, {})["e2e"] = r
        e2e_rows.append((name, r))
    _print_table(
        f"端到端 8 人局（Python Game+bot 驱动，{args.e2e_games} 局）",
        e2e_rows,
        lambda r: (
            f"{r['ms_per_game_median']:.2f} ms/局, "
            f"{r['games_per_s_median']:.1f} games/s, "
            f"平均 {r['avg_seat_sweeps']:.1f} 轮驱动"
        ),
    )

    solo_rows = []
    for name, mod in modules:
        r = bench_solo(mod, args.solo_games, args.repeats)
        report["results"].setdefault(name, {})["solo"] = r
        solo_rows.append((name, r))
    _print_table(
        f"SoloEnv 观测+决策循环（{args.solo_games} 局，单学习座位 vs 7 bot）",
        solo_rows,
        lambda r: (
            f"{r['games_per_s_median']:.1f} games/s, "
            f"{r['ms_per_game_median']:.2f} ms/局, {r['steps_per_game']:.1f} 步/局"
        ),
    )

    batch_rows = []
    for name, mod in modules:
        r = bench_batch(
            mod, args.batch_games, args.batch_threads, args.batch_steps, args.repeats
        )
        report["results"].setdefault(name, {})["batch"] = r
        batch_rows.append((name, r))
    _print_table(
        f"BatchEnv 并行采样（{args.batch_games} 局, controlled=(0,), "
        f"threads={args.batch_threads}, {args.batch_steps} 步）",
        batch_rows,
        lambda r: (
            f"{r['episodes_finished']} 局完成, {r['episodes_per_s_median']:.1f} episodes/s, "
            f"{r['slot_steps_per_s_median']:.0f} slot-steps/s"
        ),
    )

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
