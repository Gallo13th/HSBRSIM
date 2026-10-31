#!/usr/bin/env python3
"""单座位完整保真度注入的阶段耗时拆解（CPU 微基准，不占 GPU）。

对局推进到 turn≈8（board/hand/shop 都满），然后反复对同一座位做
``inject_quasi_state(fidelity="full")`` 并逐段计时：

1. ``player_json``（Rust 序列化）→ ``json.loads``（Python 解码）
2. 建新 board：``_minion_json`` × len(board)
3. 建新 hand：``_hand_json``
4. ``json.dumps``（Python 编码）→ ``apply_turn_snapshots``（Rust 解码 + 提交）
5. 复位 ended / overlay：``player_json`` + ``json.loads`` + ``dumps`` +
   ``set_player_from_json``

用法：
  PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
  PYTHONPATH=rust/python:. $PY scripts/bench_inject_stages.py --n 300
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _mid_game(seed: int, target_turn: int):
    import hsbg_engine as E
    g = E.Game(seed=int(seed))
    guard = 0
    while not g.is_over() and int(g.turn) < int(target_turn) and guard < 200000:
        acted = False
        for p in range(int(g.num_players)):
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
                guard += 1
                break
        if not acted:
            break
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--turn", type=int, default=8)
    ap.add_argument("--seat", type=int, default=2)
    ap.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    args = ap.parse_args()

    from hsbg.az.train import human_obs_full as HOF
    from hsbg.az.train.human_board_pool import load_pool

    pool = load_pool(args.human_boards, sample="auto")
    assert pool is not None
    # 取 turn≈args.turn 的 payload（最近桶）
    t = min(pool.turns(), key=lambda x: abs(x - int(args.turn)))
    row = pool.index[t][0]
    pay0 = pool.sample_payload(t, rng=random.Random(0))
    print(f"[setup] turn={t} board={len(pay0['board'])} hand={len(pay0['hand'])} "
          f"hand_avail={pay0['hand_available']} tier={pay0['tier']}")

    g = _mid_game(1, args.turn)
    print(f"[setup] game turn={g.turn} seat={args.seat} needs_action="
          f"{g.needs_action(int(args.seat))}")
    pj0 = g.player_json(int(args.seat))
    print(f"[setup] player_json bytes={len(pj0)}")
    fr = json.loads(pj0)
    print(f"[setup] frame board={len(fr.get('board') or [])} "
          f"hand={len(fr.get('hand') or [])} shop={len(fr.get('shop') or [])} "
          f"keys={len(fr)}")

    fid = "full"
    n = int(args.n)
    stage: Dict[str, float] = {}

    def tick(k: str, t0: float) -> float:
        t = time.perf_counter()
        stage[k] = stage.get(k, 0.0) + (t - t0)
        return t

    # 预热
    for _ in range(8):
        HOF.inject_quasi_state(g, int(args.seat), pay0, fid, reset_ended=True)

    total0 = time.perf_counter()
    for i in range(n):
        pay = pool.sample_payload(t, rng=random.Random(i))
        seat = int(args.seat)
        t0 = time.perf_counter()
        frame = json.loads(g.player_json(seat))
        t1 = tick("1_read_frame", t0)
        used = {int(m.get("eid", 0)) for m in (frame.get("board") or [])}
        used |= {int(h.get("hid", 0)) for h in (frame.get("hand") or [])}
        used |= {int(s.get("sid", 0)) for s in (frame.get("shop") or [])}
        nid = max(used | {50000}) + 1
        new_board = []
        for b in pay["board"]:
            new_board.append(HOF._minion_json(b, nid, with_counters=True))
            nid += 1
        t2 = tick("2_build_board", t1)
        frame["board"] = new_board
        hj, nid = HOF._hand_json(pay, nid)
        frame["hand"] = hj
        frame["tier"] = int(pay["tier"] or 1)
        t3 = tick("3_build_hand", t2)
        js = json.dumps(frame)
        t4 = tick("4a_json_dumps", t3)
        rep = g.apply_turn_snapshots([[seat, js]], None)
        t5 = tick("4b_apply_turn_snapshots", t4)
        assert int(rep.get("applied", 0)) == 1, rep
        ended = not bool(g.needs_action(seat))
        pj = json.loads(g.player_json(seat))
        t6 = tick("5a_readback", t5)
        if ended:
            pj["ended_turn"] = False
        s2 = json.dumps(pj)
        t7 = tick("5b_json_dumps", t6)
        g.set_player_from_json(seat, s2, True, False)
        t8 = tick("5c_set_player_from_json", t7)
        _ = t8
    total = (time.perf_counter() - total0) / n
    print(f"\n[per-injection] total {total * 1e6:8.1f} us  (n={n})")
    print(f"{'stage':32s} {'us/call':>10s} {'share':>7s}")
    for k, v in stage.items():
        us = v / n * 1e6
        print(f"{k:32s} {us:10.1f} {us / (total * 1e6) * 100:6.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
