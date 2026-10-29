"""动作级 micro-PUCT pilot：BC baseline vs micro-PUCT（train-free）。

每个 env 决策步用 micro-PUCT（动作级树，W=8/N=8/深度6），叶用 env rollout
（horizon=3 或 0=终局）；执行 root 最优动作后继续下一步，同一回合内逐步决策。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.rl.policies import act_index, make_policy
from hsbg.search import EngineForwardModel, PolicyEvaluator
from hsbg.search.micro_mcts import MicroConfig, MicroMCTS

CHECKPOINT = "runs/bc/official_320/policy_bc.pt"


def _rank(env: BattlegroundsEnv, info: Dict[str, Any]) -> int:
    r = info.get("rank") if isinstance(info, dict) else None
    if isinstance(r, int) and 1 <= r <= 8:
        return r
    game = env.game
    agents = [h for h in game.heroes if bool(getattr(h, "is_alive", False))]
    if bool(getattr(game, "finished", False)):
        return 1
    if not bool(getattr(env._agent, "is_alive", False)):
        return max(1, len(agents) + 1)
    return max(1, len(agents))


def _new_env(seed: int, opponent: str):
    env = BattlegroundsEnv(num_players=8, opponent=opponent, seed=int(seed))
    obs = env.reset(seed=int(seed))
    return env, obs


def run_bc_policy(*, seed: int, opponent: str, checkpoint: str = CHECKPOINT,
                  max_steps: int = 2000) -> Dict[str, Any]:
    env, obs = _new_env(seed, opponent)
    policy = make_policy(str(checkpoint), device="cpu")
    t0 = time.perf_counter()
    done = False
    steps = 0
    info: Dict[str, Any] = {}
    while not done and steps < max_steps:
        try:
            idx = act_index(policy, obs)
        except Exception:  # noqa: BLE001
            idx = 0
        obs, _, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": int(rank),
           "top4": rank <= 4, "win": rank == 1,
           "game_s": round(time.perf_counter() - t0, 2),
           "decisions": steps, "mean_decision_ms": 0.0,
           "mean_simulations": 0.0, "action_change_rate": 0.0}
    env.close()
    return out


def run_micro(*, seed: int, opponent: str, simulations: int, width: int,
              horizon: int, leaf_policy: str, checkpoint: str = CHECKPOINT,
              final_full_check: int = 0, dense_leaf: bool = False,
              max_steps: int = 2000
              ) -> Dict[str, Any]:
    env, obs = _new_env(seed, opponent)
    evaluator = PolicyEvaluator(checkpoint)
    mcts = MicroMCTS(MicroConfig(
        simulations=simulations, width=width,
        max_depth_actions=6, leaf_horizon_turns=horizon,
        seed=int(seed) + 7, rollout_policy=leaf_policy,
        final_full_check=int(final_full_check),
        dense_leaf=bool(dense_leaf)))
    t0 = time.perf_counter()
    done = False
    steps = 0
    dec_ms: List[float] = []
    sims: List[int] = []
    changed: List[bool] = []
    info: Dict[str, Any] = {}
    while not done and steps < max_steps:
        if getattr(obs, "phase", "") == "choice":
            obs, _, term, trunc, info = env.step(0)
            steps += 1
            done = bool(term or trunc)
            continue
        model = EngineForwardModel.from_env(env, clone=False)
        t1 = time.perf_counter()
        res = mcts.decide(model)
        dec_ms.append((time.perf_counter() - t1) * 1000.0)
        sims.append(res.n_simulations)
        cand = res.action
        if cand is None:
            if obs.candidates:
                obs, _, term, trunc, info = env.step(0)
                steps += 1
                done = bool(term or trunc)
            else:
                break
            continue
        # action change vs BC top-1
        try:
            top = evaluator.top_action(model)
            bc_sig = None if top is None else top[0].signature()
            changed.append(cand.signature() != bc_sig if bc_sig else False)
        except Exception:  # noqa: BLE001
            pass
        idx = next((i for i, c in enumerate(obs.candidates)
                    if c.signature() == cand.signature()), None)
        if idx is None:
            idx = 0
        obs, _, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
        try:
            mcts.commit(cand)
        except Exception:  # noqa: BLE001
            pass
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": int(rank),
           "top4": rank <= 4, "win": rank == 1,
           "game_s": round(time.perf_counter() - t0, 2),
           "decisions": len(dec_ms),
           "mean_decision_ms": (float(statistics.fmean(dec_ms))
                                if dec_ms else 0.0),
           "mean_simulations": (float(statistics.fmean(sims))
                                if sims else 0.0),
           "action_change_rate": (float(sum(changed) / len(changed))
                                  if changed else 0.0)}
    env.close()
    return out


def _bootstrap_ci(diffs: Sequence[float], n_boot: int = 2000,
                  seed: int = 0) -> Tuple[float, float, float]:
    arr = np.asarray(list(diffs), dtype=np.float64)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(arr, size=arr.size, replace=True).mean()
                      for _ in range(n_boot)])
    return (float(arr.mean()), float(np.percentile(means, 2.5)),
            float(np.percentile(means, 97.5)))


def _wilcoxon_p(diffs: Sequence[float]) -> Optional[float]:
    arr = np.asarray([d for d in diffs if d != 0.0], dtype=np.float64)
    if arr.size == 0:
        return None
    try:
        from scipy.stats import wilcoxon
        return float(wilcoxon(arr).pvalue)
    except Exception:  # noqa: BLE001
        pos = int((arr > 0).sum())
        return float(min(1.0, 2 * min(pos, arr.size - pos) / max(1, arr.size)))


def summarize(rows: List[Dict[str, Any]], ref: Dict[int, int]) -> Dict[str, Any]:
    ranks = [r["rank"] for r in rows]
    diffs = [float(ref[r["seed"]] - r["rank"]) for r in rows]
    mean, lo, hi = _bootstrap_ci(diffs)
    out = {"n_games": len(rows),
           "mean_rank": float(statistics.fmean(ranks)),
           "top4_rate": sum(1 for r in rows if r["top4"]) / len(rows),
           "win_rate": sum(1 for r in rows if r["win"]) / len(rows),
           "mean_game_s": float(statistics.fmean([r["game_s"] for r in rows])),
           "mean_decision_ms": float(statistics.fmean(
               [r.get("mean_decision_ms", 0.0) for r in rows])),
           "mean_simulations": float(statistics.fmean(
               [r.get("mean_simulations", 0.0) for r in rows])),
           "mean_decisions": float(statistics.fmean(
               [r.get("decisions", 0) for r in rows])),
           "action_change_rate": float(statistics.fmean(
               [r.get("action_change_rate", 0.0) for r in rows])),
           "paired_diff_vs_bc": {"mean": mean, "ci95": [lo, hi],
                                 "better": bool(lo > 0),
                                 "worse": bool(hi < 0),
                                 "wilcoxon_p": _wilcoxon_p(diffs),
                                 "n_pairs": len(diffs)},
           "rows": rows}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="动作级 micro-PUCT pilot")
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--seeds-start", type=int, default=300)
    parser.add_argument("--opponents", default="heuristic,teacher")
    parser.add_argument("--sims", default="8")
    parser.add_argument("--widths", default="8")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--final-full-check", type=int, default=0,
                        help="root 最终 top-K 动作各做 1 次 full-to-end 复核")
    parser.add_argument("--dense-leaf", action="store_true",
                        help="dense edge reward + discounted backup + prior mix")
    parser.add_argument("--leaf-policy", default="heuristic",
                        choices=["heuristic", "epsilon", "random"])
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--out-dir", default="runs/search")
    parser.add_argument("--out-prefix", default="micro_mcts_pilot")
    parser.add_argument("--max-wall-seconds", type=float, default=1500.0)
    parser.add_argument("--max-steps", type=int, default=2000)
    args = parser.parse_args(argv)

    seeds = [args.seeds_start + i for i in range(max(1, args.games))]
    opponents = [x for x in args.opponents.split(",") if x]
    sims_list = [int(x) for x in args.sims.split(",") if x]
    widths = [int(x) for x in args.widths.split(",") if x]
    t0 = time.perf_counter()
    deadline = t0 + float(args.max_wall_seconds)
    cells: Dict[str, List[Dict[str, Any]]] = {}
    partial: List[str] = []

    def _cell(name: str, fn, **kw) -> None:
        rows = []
        for i, seed in enumerate(seeds):
            if time.perf_counter() >= deadline:
                partial.append(name)
                break
            opp = opponents[i % len(opponents)]
            try:
                row = fn(seed=seed, opponent=opp, **kw)
            except Exception as exc:  # noqa: BLE001
                row = {"seed": seed, "opponent": opp, "rank": 8,
                       "top4": False, "win": False, "game_s": 0.0,
                       "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            print(f"  {name} seed={seed} opp={opp} rank={row['rank']} "
                  f"game_s={row['game_s']} decisions={row.get('decisions', '?')}")
        cells[name] = rows

    _cell("bc_policy", run_bc_policy, checkpoint=args.checkpoint,
          max_steps=args.max_steps)
    for n in sims_list:
        for w in widths:
            _cell(f"micro_n{n}_w{w}_h{args.horizon}", run_micro,
                  simulations=n, width=w, horizon=args.horizon,
                  leaf_policy=args.leaf_policy, checkpoint=args.checkpoint,
                  final_full_check=int(args.final_full_check),
                  dense_leaf=bool(args.dense_leaf),
                  max_steps=args.max_steps)
    ref = {r["seed"]: r["rank"] for r in cells.get("bc_policy", [])}
    matrix = [dict(summarize(rows, ref), name=name)
              for name, rows in cells.items() if rows and ref]
    report = {
        "meta": {"created_at": datetime.now().isoformat(timespec="seconds"),
                 "games": len(seeds), "seeds": seeds, "opponents": opponents,
                 "sims": sims_list, "widths": widths,
                 "horizon": args.horizon, "leaf_policy": args.leaf_policy,
                 "dense_leaf": bool(args.dense_leaf),
                 "elapsed_s": round(time.perf_counter() - t0, 1),
                 "partial": bool(partial), "partial_cells": partial,
                 "note": ("动作级 micro-PUCT；节点=动作后状态，边=合法动作，"
                          "叶=env rollout（horizon=3 截断，非全终局）；"
                          "宽度只看 top-W；无价值网")},
        "matrix": matrix,
    }
    out = Path(args.out_dir) / f"{args.out_prefix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    lines = ["# 动作级 micro-PUCT pilot（train-free）", "",
             f"- games/cell={len(seeds)}；seeds {seeds[0]}–{seeds[-1]}；"
             f"sims={sims_list}；widths={widths}；leaf horizon={args.horizon}；"
             f"elapsed={report['meta']['elapsed_s']}s", "",
             "| 组合 | mean rank | top4 | win | ms/决策 | sims/决策 | "
             "decisions/局 | 动作改变率 | 配对 Δ vs BC (95% CI) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for m in sorted(matrix, key=lambda x: x["mean_rank"]):
        pd = m["paired_diff_vs_bc"]
        lines.append(
            f"| {m['name']} | {m['mean_rank']:.2f} | {m['top4_rate']*100:.0f}% | "
            f"{m['win_rate']*100:.0f}% | {m['mean_decision_ms']:.0f} | "
            f"{m['mean_simulations']:.1f} | {m['mean_decisions']:.1f} | "
            f"{m['action_change_rate']*100:.0f}% | "
            f"{pd['mean']:+.2f} [{pd['ci95'][0]:+.2f},{pd['ci95'][1]:+.2f}] |")
    lines += ["", "> 动作级树：每次决策只展开 top-W 动作；叶 rollout horizon="
              f"{args.horizon}（截断，非全终局）；样本小只报方向。"]
    if partial:
        lines.append(f"> **partial**：{partial}")
    md = Path(args.out_dir) / f"{args.out_prefix}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} and {md} ({report['meta']['elapsed_s']}s)")
    for m in sorted(matrix, key=lambda x: x["mean_rank"]):
        print(f"  {m['name']:22s} rank={m['mean_rank']:.2f} "
              f"top4={m['top4_rate']*100:.0f}% win={m['win_rate']*100:.0f}% "
              f"ms={m['mean_decision_ms']:.0f} "
              f"sims={m['mean_simulations']:.1f} "
              f"dec={m['mean_decisions']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
