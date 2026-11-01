#!/usr/bin/env python3
"""沙盒「可表达上限」探测：脚本策略 × 动作上限 × 金币 × 免费 tier6。

为什么需要
----------
``docs/COMP_LINES_TINY.md`` 的判据是「t15 Σ p50 ≥ 10,000 且 t12→t15 ≥ 3×」。
在解读 1M 小模型的训练结果之前，必须先知道**这个沙盒本身**能表达多大的成长：
连「专门手写的缩放脚本 + 无限金币」都到不了的话，模型学不到就不是训练问题，
而是环境口径问题（或判据口径问题）。

本脚本只用 ``hsbg/az/train/economy_sandbox.py`` 的脚本策略
（``SandboxPolicies``：teacher / carrier_teacher / spell / greedy / random），
不训练、不动 GPU（``--device`` 不使用），并把**成长曲线形状**一起打出来。

用法::

    python scripts/sandbox_ceiling_probe.py --games 6 --json-out runs/comp_lines/ceiling.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    EconomySandbox, SandboxConfig, SandboxPolicies, growth_shape, summarize)


def run(cfg: SandboxConfig, policy: str, games: int, seed0: int) -> Dict[str, Any]:
    eps: List[Dict[str, Any]] = []
    for i in range(int(games)):
        env = EconomySandbox(cfg)
        obs = env.reset(int(seed0) + i)
        pol = SandboxPolicies(env.g, policy, seed=i)
        steps = 0
        while not env.done:
            a = pol.act(env.g, obs.mask)
            obs, _r, _d, _i = env.step(int(a))
            steps += 1
        ep = env.episode_summary()
        ep["decisions"] = steps
        eps.append(ep)
    rep = summarize(eps)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="沙盒可表达上限探测（脚本策略，无训练）")
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--seed", type=int, default=700000)
    ap.add_argument("--policies", default="teacher,spell,carrier_teacher")
    ap.add_argument("--caps", default="40,120")
    ap.add_argument("--golds", default="30,99")
    ap.add_argument("--free-tier6", dest="free", default="0,1")
    ap.add_argument("--trinkets", type=int, default=1, help="1=开启饰品（默认）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    rows: List[Dict[str, Any]] = []
    for pol in [x.strip() for x in args.policies.split(",") if x.strip()]:
        for cap in [int(x) for x in args.caps.split(",") if x.strip()]:
            for gold in [int(x) for x in args.golds.split(",") if x.strip()]:
                for free in [int(x) for x in args.free.split(",") if x.strip()]:
                    cfg = SandboxConfig(turns=15, gold_per_turn=gold, action_cap=cap,
                                        reward="log_strength",
                                        trinkets=(None if args.trinkets < 0
                                                  else bool(args.trinkets)),
                                        free_tier6=bool(free))
                    t0 = time.perf_counter()
                    rep = run(cfg, pol, int(args.games), int(args.seed))
                    row = {
                        "policy": pol, "action_cap": cap, "gold": gold,
                        "free_tier6": bool(free),
                        "sigma_t12_p50": rep["sigma_t12_p50"],
                        "sigma_t15_p50": rep["sigma_t15_p50"],
                        "sigma_t15_max": rep["sigma_t15_max"],
                        "spells_p50": rep["spells_p50"],
                        "carrier_rate": rep["carrier_rate"],
                        "tier_p50": rep["tier_p50"],
                        "tavern_buff_p50": rep["tavern_buff_p50"],
                        "growth_slope_late_p50": rep.get("growth_slope_late_p50"),
                        "growth_ratio_12_15_p50": rep.get("growth_ratio_12_15_p50"),
                        "exp_segment_rate": rep.get("exp_segment_rate"),
                        "trinkets_p50": rep.get("trinkets_p50"),
                        "trinket_offers_mean": rep.get("trinket_offers_mean"),
                        "decisions_mean": rep.get("decisions_mean"),
                        "secs": round(time.perf_counter() - t0, 1),
                    }
                    rows.append(row)
                    print(f"{pol:16s} cap={cap:3d} gold={gold:2d} free6={free} → "
                          f"t12={row['sigma_t12_p50']:7.0f} t15={row['sigma_t15_p50']:8.0f} "
                          f"(max {row['sigma_t15_max']:8.0f}) spells={row['spells_p50']:4.0f} "
                          f"carr={row['carrier_rate']:.2f} slope_late="
                          f"{(row['growth_slope_late_p50'] or 0):.2f} "
                          f"r12_15={(row['growth_ratio_12_15_p50'] or 0):.2f} "
                          f"exp={row['exp_segment_rate']:.2f} {row['secs']:.0f}s", flush=True)
    best = max(rows, key=lambda r: float(r["sigma_t15_p50"] or 0)) if rows else {}
    print(f"\n[ceiling] 最高 t15 p50 = {best.get('sigma_t15_p50')} "
          f"@ {best.get('policy')} cap={best.get('action_cap')} gold={best.get('gold')} "
          f"free6={best.get('free_tier6')}")
    if args.json_out:
        out = os.path.join(ROOT, args.json_out) if not os.path.isabs(args.json_out) \
            else args.json_out
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"meta": {"generated_by": "scripts/sandbox_ceiling_probe.py",
                                "games": int(args.games), "seed0": int(args.seed),
                                "note": "脚本策略下的沙盒可表达上限（无训练）"},
                       "rows": rows, "best": best}, f, ensure_ascii=False, indent=1)
        print(f"[ceiling] → {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
