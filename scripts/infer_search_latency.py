#!/usr/bin/env python3
"""推理期搜索的**单次延迟**实测（部署口径：单进程、无其它评测并发）。

在若干个**真实中局决策点**上各跑一次完整搜索，报每次搜索的
``elapsed_ms``（p50/p90/max）、rollout 步数、候选数、动作切换次数。
这是 ``docs/INFERENCE_SEARCH.md`` §5.4 的数字来源；面板里的
``search.mean_ms_per_call`` 会因为并发跑多条臂而偏高。

用法::

    PYTHONPATH=rust/python:. python scripts/infer_search_latency.py \
        --checkpoint runs/infer_search_ab/ckpt_s16b_snapshot.pt \
        --device cuda:7 --turns 1 --samples 16 --out /tmp/lat.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import mask_from_bytes  # noqa: E402
from hsbg.az.train.infer_search import (InferSearchConfig,  # noqa: E402
                                        InferSearcher)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator  # noqa: E402


def _states(seeds: List[int], min_turns=(4, 6, 8, 10, 12, 13)):
    """在若干 seed 上取「learner 需要动作」的决策点（每个目标回合一个）。"""
    import hsbg_engine as E
    out = []
    for seed in seeds:
        for t in min_turns:
            g = E.Game(seed=int(seed))
            guard = 0
            while not g.is_over() and guard < 6000:
                guard += 1
                if int(g.turn) >= int(t) and bool(g.needs_action(0)):
                    out.append((int(seed), int(g.turn), g))
                    break
                acted = False
                for p in range(8):
                    if bool(g.is_over()):
                        break
                    if bool(g.needs_action(p)):
                        g.bot_play(p)
                        acted = True
                if not acted:
                    break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="推理期搜索单次延迟实测")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--turns", type=int, default=1, choices=[1, 3])
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--max-per-turn", type=int, default=3)
    ap.add_argument("--when", default="carrier_or_spell")
    ap.add_argument("--action", default="pi_argmax")
    ap.add_argument("--max-ms", type=float, default=0.0)
    ap.add_argument("--samples", type=int, default=16,
                    help="最多测多少个决策点（每个点跑一次搜索）")
    ap.add_argument("--seed0", type=int, default=420000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device, norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    cfg = InferSearchConfig(enabled=1, turns=int(args.turns), topk=int(args.topk),
                            max_searches_per_turn=int(args.max_per_turn),
                            search_when=str(args.when), action=str(args.action),
                            max_ms_per_search=float(args.max_ms),
                            seed=int(args.seed0)).validate()
    sr = InferSearcher(ev, cfg)
    pts = _states([int(args.seed0) + i for i in range(4)])[:int(args.samples)]
    if not pts:
        print("[error] 取不到决策点", file=sys.stderr)
        return 2
    rows: List[Dict[str, Any]] = []
    for seed, turn, g in pts:
        mask = mask_from_bytes(g.legal_mask(0))
        out = sr.search(g, 0, mask=mask)
        if out is None:
            rows.append({"seed": seed, "turn": turn, "skipped": True})
            continue
        rows.append({"seed": seed, "turn": turn, "turn_actions": int(out.leaf_steps),
                     "elapsed_ms": round(float(out.elapsed_ms), 2),
                     "cands": int(out.cands.size),
                     "pi_top1": int(np.argmax(out.pi)),
                     "switch": int(int(np.argmax(out.pi)) != int(out.base)),
                     "sigma_root": int(out.sigma_root),
                     "sigma_best": int(out.sigma_best),
                     "truncated": int(out.truncated)})
    ms = np.asarray([r["elapsed_ms"] for r in rows if "elapsed_ms" in r],
                    dtype=np.float64)
    steps = np.asarray([r["turn_actions"] for r in rows if "turn_actions" in r],
                       dtype=np.float64)
    rep = {"checkpoint": args.checkpoint, "device": args.device, "turns": int(args.turns),
           "topk": int(args.topk), "action": str(args.action), "when": str(args.when),
           "n": int(ms.size),
           "mean_ms": round(float(ms.mean()), 2) if ms.size else None,
           "p50_ms": round(float(np.percentile(ms, 50)), 2) if ms.size else None,
           "p90_ms": round(float(np.percentile(ms, 90)), 2) if ms.size else None,
           "max_ms": round(float(ms.max()), 2) if ms.size else None,
           "mean_leaf_steps": round(float(steps.mean()), 1) if steps.size else None,
           "switch_rate": (round(float(np.mean([r.get("switch", 0) for r in rows
                                                if "elapsed_ms" in r])), 3)
                           if ms.size else None),
           "per_call_ms": [round(float(x), 2) for x in ms.tolist()],
           "rows": rows}
    txt = json.dumps(rep, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(txt)
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
