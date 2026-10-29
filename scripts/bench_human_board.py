"""人类战团（board-only）注入的开销实测（CPU tiny，不需要 GPU）。

同 seed 同 N 局、lockstep bot 对手，交替跑「关 / 开 human-board」若干次取中位数，并插桩统计
注入自身的耗时占比（把 ``parallel_collect.inject_human_boards`` 包一层计时）。

用法::

    PYTHONPATH=rust/python:. python scripts/bench_human_board.py --reps 21 --games 4
    PYTHONPATH=rust/python:. python scripts/bench_human_board.py --device cuda:7 --arch tiny

输出（每行一个 arm）::

    ARM off       runs=21 collect_s med=0.1162 ... calls med=0
    ARM p0.15_s2  runs=21 collect_s med=0.1199 ... calls med=58 inject_ms med=1.391
    DELTA p0.15_s2: wall +3.17% | inject self 1.160% of collect_s | net-of-inject wall +1.97%

``calls`` 是 ``inject_turn`` 的调用次数（每回合每局一次，不是座位数）；``inject_ms`` 是这些调用
自身耗时之和。设计的稳态开销见 ``docs/HUMAN_BOARD_OPPONENT.md`` §8（微基准 7.5 µs/回合/2 座）。
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DEFAULT_BOARDS = "data/real_library/library_real_degraded.jsonl"


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="人类战团注入开销实测（CPU tiny）")
    ap.add_argument("--boards", default=DEFAULT_BOARDS,
                    help="人类战团 JSONL（默认 data/real_library/library_real_degraded.jsonl）")
    ap.add_argument("--games", type=int, default=4, help="每 arm 的局数（默认 4）")
    ap.add_argument("--seed", type=int, default=31000)
    ap.add_argument("--reps", type=int, default=5, help="每个 arm 的重复次数（默认 5；report 用 21）")
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--arch", default="tiny")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--threads", type=int, default=4)
    return ap.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    import torch

    import hsbg.az.train.parallel_collect as pc
    from hsbg.az.train.human_board_pool import (HumanBoardPool, HumanBoardStats,
                                               inject_turn)
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import CollectConfig, PPOEvaluator

    pool = HumanBoardPool(str(args.boards))
    torch.manual_seed(7)
    torch.set_num_threads(max(1, int(args.threads)))
    model = build_net(hidden=int(args.hidden), arch=str(args.arch))
    model.eval()
    evaluator = PPOEvaluator(model, device=str(args.device))

    acc: Dict[str, float] = {"s": 0.0, "calls": 0, "injected": 0}
    orig = pc.inject_human_boards

    def _timed(*a: Any, **kw: Any):
        # stats 是「累计」对象：用前后差值算本次实际注入的座位数。
        st = kw.get("stats")
        before = int(st.applied) if st is not None else 0
        t0 = time.perf_counter()
        out = orig(*a, **kw)
        acc["s"] += time.perf_counter() - t0
        acc["calls"] += 1
        acc["injected"] += int(out.applied) - before
        return out

    pc.inject_human_boards = _timed

    def run(p: float, seats: int) -> Tuple[float, int, Dict[str, float]]:
        acc.update({"s": 0.0, "calls": 0.0, "injected": 0.0})
        cfg = CollectConfig(
            games=int(args.games), seed=int(args.seed), opponent="bot",
            behavior="net", max_actions_per_turn=40, max_steps=8000,
            lockstep=True, fast_act=True)
        t0 = time.time()
        _recs, meta = pc.collect_ppo_lockstep(
            model, cfg, eval_fn=evaluator, device=str(args.device), seed=int(args.seed),
            games=int(args.games), gamemode="bot",
            human_board_pool=pool if p > 0.0 else None,
            human_board_p=float(p), human_board_seats=int(seats))
        dt = time.time() - t0
        return dt, int(meta.get("decisions", 0)), dict(acc)

    arms = [("off", 0.0, 0), (f"p0.15_s2", 0.15, 2), ("p1.0_s7", 1.0, 7)]
    res: Dict[str, List[Tuple[float, int, Dict[str, float]]]] = {n: [] for n, _, _ in arms}
    try:
        for rep in range(int(args.reps)):
            for name, p, seats in arms:
                if name == "p1.0_s7" and rep >= max(3, int(args.reps) // 2):
                    continue
                res[name].append(run(p, seats))
    finally:
        pc.inject_human_boards = orig

    def med(name: str, i: int) -> float:
        return statistics.median(v[i] for v in res[name])

    for name, _, _ in arms:
        v = res[name]
        if not v:
            continue
        d = statistics.median(x[0] for x in v)
        inj = statistics.median(x[2]["s"] for x in v) * 1e3
        calls = statistics.median(x[2]["calls"] for x in v)
        applied = statistics.median(x[2]["injected"] for x in v)
        print(f"ARM {name:10s} runs={len(v):2d} collect_s med={d:.4f} "
              f"min={min(x[0] for x in v):.4f} max={max(x[0] for x in v):.4f} "
              f"dec={statistics.median(x[1] for x in v):.0f} "
              f"inject_ms med={inj:.3f} calls med={calls:.0f} applied med={applied:.0f}",
              flush=True)

    off = med("off", 0)
    off_inj = statistics.median(x[2]["s"] for x in res["off"]) * 1e3
    for name in ("p0.15_s2", "p1.0_s7"):
        if not res[name]:
            continue
        d = statistics.median(x[0] for x in res[name])
        inj = statistics.median(x[2]["s"] for x in res[name]) * 1e3
        net = (d - inj / 1e3) / (off - off_inj / 1e3) - 1.0
        print(f"DELTA {name}: wall {d - off:+.4f}s = {d / off - 1:+.2%} | "
              f"inject self {inj:.3f}ms = {inj / (d * 1e3):.3%} of collect_s | "
              f"net-of-inject wall {net:+.2%}", flush=True)

    # 微基准（稳定态）：采样 / 单次引擎注入 / 完整 inject_turn
    import random

    import hsbg_engine as E

    g = E.Game(seed=1)
    while not g.is_over() and int(g.turn) < 4:
        for p in range(8):
            if g.needs_action(p):
                g.bot_play(p)
    rng = random.Random(0)
    t0 = time.perf_counter()
    for i in range(20000):
        pool.sample(6 + i % 8, rng)
    print(f"MICRO sample            {(time.perf_counter() - t0) / 20000 * 1e6:.2f} us/call")
    board = pool.sample(4, rng)
    t0 = time.perf_counter()
    for _ in range(20000):
        rep = g.inject_board(1, board, 3)
        assert rep["applied"], rep
    print(f"MICRO Game.inject_board {(time.perf_counter() - t0) / 20000 * 1e6:.2f} us/call "
          f"(board_len={len(board)})")
    st = HumanBoardStats()
    t0 = time.perf_counter()
    for _ in range(3000):
        inject_turn(g, pool, 4, seats_count=2, p=0.15, rng=rng, learner_seat=0, stats=st)
    print(f"MICRO inject_turn(p=.15,2 seats) "
          f"{(time.perf_counter() - t0) / 3000 * 1e6:.2f} us/call")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
