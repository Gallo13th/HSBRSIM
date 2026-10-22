#!/usr/bin/env python
"""策略评测入口：在固定种子集上比较 random / heuristic / checkpoint 策略。

用法::

    python scripts/evaluate.py --baseline random --episodes 20 --seed 0
    python scripts/evaluate.py --baseline heuristic --episodes 20
    python scripts/evaluate.py --checkpoint runs/ppo/best.pt --episodes 20
    python scripts/evaluate.py --compare heuristic --checkpoint runs/ppo/best.pt

设计说明
--------
* 环境：``hsbg.env.BattlegroundsEnv``（8 人、启发式对手）。
* 策略：均匀随机 / 启发式教师 / 训练好的实体 Transformer。
* 每个策略在**同一组种子**上评测，结果含 95% bootstrap 置信区间。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsbg.eval.metrics import EvalResult, format_summary  # noqa: E402
from hsbg.eval.runner import evaluate_policy  # noqa: E402


def make_env(args):
    from hsbg.env import BattlegroundsEnv
    return BattlegroundsEnv(
        num_players=args.players,
        opponent=args.opponent,
        seed=args.seed,
        max_turns=args.max_turns,
    )


def baseline_policy(name: str, env):
    """基线策略：random / first / end_turn / heuristic。"""
    if name in ("random", "first", "end_turn"):
        from hsbg.eval.baselines import make_baseline
        return make_baseline(name, seed=0)
    if name == "heuristic":
        from hsbg.agents.heuristic import HeuristicPolicy
        from hsbg.env.spec import ActionKind, CandidateAction
        teacher = HeuristicPolicy()

        def policy(obs, rng=None):
            if obs.phase == "choice":
                return _find_candidate(obs, CandidateAction(
                    kind=ActionKind.CHOOSE.value,
                    option=teacher.choose_option_index(obs)))
            desc = teacher.choose(env.game, env.agent_hero)
            if desc is None:
                return _find_candidate(obs, CandidateAction(
                    kind=ActionKind.END_TURN.value))
            return _find_candidate(obs, desc.to_candidate())
        return policy
    raise ValueError(f"unknown baseline: {name!r}")


def _find_candidate(obs, target) -> int:
    sig = target.signature()
    for i, c in enumerate(obs.candidates):
        if c.signature() == sig:
            return i
    return len(obs.candidates) - 1 if obs.candidates else 0


def checkpoint_policy(path: str, device: str = "auto"):
    """加载 checkpoint，返回 policy(obs, rng) -> action index。"""
    import torch
    from hsbg.policy.model import load_policy_and_encoder

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model, encoder = load_policy_and_encoder(path, map_location=device)
    model.to(device).eval()

    def policy(obs, rng=None):
        encoded = encoder.encode_batch([obs])
        batch = {k: torch.as_tensor(v, device=device) for k, v in encoded.items()}
        with torch.no_grad():
            actions, _logp, _value = model.act(batch, greedy=True)
        return int(actions[0].item())

    meta = {
        "checkpoint": str(path),
        "device": device,
        "params": int(model.count_parameters()),
        "vocab": int(len(encoder.vocab)),
    }
    return policy, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=str, default=None)
    ap.add_argument("--baseline", type=str, default=None,
                    choices=["random", "first", "end_turn", "heuristic"])
    ap.add_argument("--compare", action="store_true",
                    help="同时评测 checkpoint 与指定基线（默认 random）")
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--opponent", type=str, default="heuristic")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--device", type=str, default="auto")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    env = make_env(args)
    results: Dict[str, EvalResult] = {}

    baseline_name = args.baseline or ("random" if args.compare else None)
    if baseline_name:
        results[baseline_name] = evaluate_policy(
            env, baseline_policy(baseline_name, env),
            episodes=args.episodes, seed=args.seed, name=baseline_name,
            log_every=0)
    if args.checkpoint:
        policy, meta = checkpoint_policy(args.checkpoint, args.device)
        name = f"ckpt:{Path(args.checkpoint).name}"
        results[name] = evaluate_policy(
            env, policy, episodes=args.episodes, seed=args.seed, name=name)
        print(json.dumps(meta, ensure_ascii=False))
    if not results:
        print("nothing to evaluate: pass --baseline and/or --checkpoint")
        return 2

    for name, res in results.items():
        print(format_summary(res, name))
        if res.wall_seconds:
            print(f"wall_time={res.wall_seconds:.2f}s  "
                  f"games/s={len(res.ranks) / res.wall_seconds:.2f}")

    if args.out:
        payload = {name: res.to_dict() for name, res in results.items()}
        payload["config"] = vars(args)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
