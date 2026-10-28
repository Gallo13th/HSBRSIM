#!/usr/bin/env python3
"""单决策成本分解（纯 CPU，不占 GPU）：引擎 step / 观测 / mask / 策略记账各占多少。

跑一段 bot 对局，对 learner 座位的每个决策分别计时：
- `bot_play/step`：引擎推进（含 7 个 bot 座位）
- `observe`：观测数组解码（obs_std）
- `legal_mask`：mask 提取
- 合计 → 得到「每决策 Python/引擎成本」，与 GPU 前向时间对比。

用法：
  PYTHONPATH=rust/python:. python scripts/bench_decision_cost.py --games 3
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="runs/profile_resource/decision_cost.json")
    args = ap.parse_args()

    import hsbg_engine as E
    from hsbg.az.train.common import mask_from_bytes, obs_arrays

    rows = []
    for g in range(int(args.games)):
        game = E.Game(seed=int(args.seed) + g)
        steps = 0
        while not game.is_over() and steps < 200000:
            acted = False
            for p in range(int(game.num_players)):
                if not game.needs_action(p):
                    continue
                acted = True
                if p == 0:
                    t_a = time.perf_counter()
                    f, c = obs_arrays(game.observe(0))
                    t_b = time.perf_counter()
                    raw = game.legal_mask(0)
                    m = mask_from_bytes(raw)
                    t_c = time.perf_counter()
                    # 模拟策略侧记账（records append + numpy 小操作）
                    _ = (f.shape, c.shape, int(np.flatnonzero(m)[0]))
                    t_d = time.perf_counter()
                    a = int(game.bot_action(0))
                    t_e = time.perf_counter()
                    game.step(0, a)
                    t_f = time.perf_counter()
                    # 对手座位（bot 推进）——单独计时，归到「引擎」
                    t_g0 = time.perf_counter()
                    for q in range(1, int(game.num_players)):
                        if game.needs_action(q):
                            game.bot_play(q)
                    t_g1 = time.perf_counter()
                    rows.append({
                        "observe_ms": (t_b - t_a) * 1e3,
                        "mask_ms": (t_c - t_b) * 1e3,
                        "policy_ms": (t_d - t_c) * 1e3,
                        "bot_action_ms": (t_e - t_d) * 1e3,
                        "step_learner_ms": (t_f - t_e) * 1e3,
                        "opponents_ms": (t_g1 - t_g0) * 1e3,
                    })
                else:
                    game.bot_play(p)
                steps += 1
                if game.is_over():
                    break
            if not acted:
                break

    keys = ["observe_ms", "mask_ms", "policy_ms", "bot_action_ms",
            "step_learner_ms", "opponents_ms"]
    med = {k: st.median(r[k] for r in rows) for k in keys}
    total = sum(med.values())
    out = {"n_decisions": len(rows), "median_ms": med, "total_ms": total,
           "share": {k: v / total for k, v in med.items()}}
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps({"n": len(rows), "total_ms": round(total, 3),
                      **{k: round(v, 3) for k, v in med.items()}}, ensure_ascii=False))
    print("share:", {k: f"{v*100:.1f}%" for k, v in out["share"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
