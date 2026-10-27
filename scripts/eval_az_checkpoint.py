#!/usr/bin/env python3
"""固定 seed 评测一个 checkpoint / random / bot（seat0 vs 7 引擎 bot）。

用法：
    python scripts/eval_az_checkpoint.py --checkpoint runs/az_ppo_1h/current/model.pt \
        --arch tiny --games 100 --seed 90000 --out runs/az_ppo_1h/eval_final.json
    python scripts/eval_az_checkpoint.py --policy random --games 100
    python scripts/eval_az_checkpoint.py --checkpoint ... --baseline  # 同时跑 random/bot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.evaluate import EvalConfig, evaluate_policy  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.policies import make_policy  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOGreedyPolicy  # noqa: E402


def _run(policy: Any, games: int, seed: int, max_steps: int,
         policy_seat: int = 0) -> Dict[str, Any]:
    res = evaluate_policy(policy, EvalConfig(games=games, seed=seed,
                                            max_steps=max_steps,
                                            policy_seat=policy_seat))
    res.pop("examples", None)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="AZ checkpoint 固定 seed 评测")
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--policy", default="net", choices=["net", "random", "bot"])
    ap.add_argument("--arch", default="tiny", choices=["tiny", "entity"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=90000)
    ap.add_argument("--policy-seat", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=50000)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--baseline", action="store_true",
                    help="额外跑 random 与 bot 基线")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    out: Dict[str, Any] = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                           "games": int(args.games), "seed": int(args.seed),
                           "policy_seat": int(args.policy_seat),
                           "policy": args.policy, "checkpoint": args.checkpoint,
                           "results": {}}
    if args.baseline:
        out["results"]["random"] = _run(make_policy("random", seed=args.seed),
                                        args.games, args.seed, args.max_steps,
                                        args.policy_seat)
        out["results"]["bot"] = _run(make_policy("bot"), args.games, args.seed,
                                     args.max_steps, args.policy_seat)
    if args.policy == "random":
        out["results"]["random"] = _run(make_policy("random", seed=args.seed),
                                        args.games, args.seed, args.max_steps,
                                        args.policy_seat)
    elif args.policy == "bot":
        out["results"]["bot"] = _run(make_policy("bot"), args.games, args.seed,
                                     args.max_steps, args.policy_seat)
    else:
        if not args.checkpoint:
            raise SystemExit("--policy net 需要 --checkpoint")
        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        evaluator = PPOEvaluator(model, device=args.device,
                                 norm_mean=meta.get("norm_mean"),
                                 norm_std=meta.get("norm_std"))
        policy = PPOGreedyPolicy(evaluator,
                                 max_actions_per_turn=args.max_actions_per_turn)
        res = _run(policy, args.games, args.seed, args.max_steps,
                   args.policy_seat)
        res["arch"] = meta.get("arch", args.arch)
        out["results"]["net"] = res
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"[eval] -> {args.out}")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
