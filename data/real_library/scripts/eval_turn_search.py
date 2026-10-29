"""回合内自枚举 + 两两胜率搜索 pilot（train-free）。

对照：冻结 BC baseline、heuristic；实验：TurnSearch（单回合内枚举状态、两两战斗胜率）。
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

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.rl.policies import act_index, make_policy
from hsbg.search import EngineForwardModel, PolicyEvaluator
from hsbg.search.turn_search import TurnSearch, TurnSearchConfig

CHECKPOINT = "runs/bc/official_320/policy_bc.pt"


def _rank(env, info) -> int:
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
    out = {"seed": int(seed), "opponent": opponent, "rank": rank,
           "top4": rank <= 4, "win": rank == 1,
           "game_s": round(time.perf_counter() - t0, 2), "decisions": steps,
           "mean_decision_ms": 0.0, "mean_states": 0.0, "mean_combats": 0.0,
           "action_change_rate": 0.0}
    env.close()
    return out


def run_heuristic_policy(*, seed: int, opponent: str,
                         max_steps: int = 2000) -> Dict[str, Any]:
    env, obs = _new_env(seed, opponent)
    heur = HeuristicPolicy()
    t0 = time.perf_counter()
    done = False
    steps = 0
    info: Dict[str, Any] = {}
    while not done and steps < max_steps:
        idx = 0
        try:
            d = heur.choose(env.game, env._agent)
            if d is not None:
                sig = d.to_candidate().signature()
                idx = next((i for i, c in enumerate(obs.candidates)
                            if c.signature() == sig), 0)
        except Exception:  # noqa: BLE001
            idx = 0
        obs, _, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": rank,
           "top4": rank <= 4, "win": rank == 1,
           "game_s": round(time.perf_counter() - t0, 2), "decisions": steps,
           "mean_decision_ms": 0.0, "mean_states": 0.0, "mean_combats": 0.0,
           "action_change_rate": 0.0}
    env.close()
    return out


def run_turn_search(*, seed: int, opponent: str, states_budget: int,
                    samples_per_action: int, combat_samples: int,
                    completion_policy: str, state_scorer: str = "pairwise",
                    prune_top_k: int = 4, checkpoint: str = CHECKPOINT,
                    max_steps: int = 2000) -> Dict[str, Any]:
    env, obs = _new_env(seed, opponent)
    evaluator = PolicyEvaluator(checkpoint)
    ts = TurnSearch(TurnSearchConfig(
        states_budget=states_budget, samples_per_action=samples_per_action,
        combat_samples=combat_samples, completion_policy=completion_policy,
        state_scorer=state_scorer, prune_top_k=prune_top_k,
        seed=int(seed) + 7), evaluator=evaluator)
    t0 = time.perf_counter()
    done = False
    steps = 0
    dec_ms: List[float] = []
    n_states: List[int] = []
    n_combats: List[int] = []
    n_value: List[int] = []
    changed: List[bool] = []
    info: Dict[str, Any] = {}
    while not done and steps < max_steps:
        if getattr(obs, "phase", "") == "choice":
            obs, _, term, trunc, info = env.step(0)
            steps += 1
            done = bool(term or trunc)
            continue
        model = EngineForwardModel.from_env(env, clone=False)
        bc_sig = None
        try:
            top = evaluator.top_action(model)
            bc_sig = None if top is None else top[0].signature()
        except Exception:  # noqa: BLE001
            pass
        t1 = time.perf_counter()
        res = ts.decide(model)
        dec_ms.append((time.perf_counter() - t1) * 1000.0)
        n_states.append(res.n_states)
        n_combats.append(res.n_combats)
        n_value.append(res.n_value_evals)
        if res.action is None or res.turn != obs.turn:
            # 安全兜底：不应该跨回合；走 heuristic
            if obs.candidates:
                obs, _, term, trunc, info = env.step(0)
                steps += 1
                done = bool(term or trunc)
            else:
                break
            continue
        cand = res.action
        if bc_sig is not None:
            changed.append(cand.signature() != bc_sig)
        idx = next((i for i, c in enumerate(obs.candidates)
                    if c.signature() == cand.signature()), None)
        if idx is None:
            idx = 0
        obs, _, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": rank,
           "top4": rank <= 4, "win": rank == 1,
           "game_s": round(time.perf_counter() - t0, 2),
           "decisions": len(dec_ms),
           "mean_decision_ms": (float(statistics.fmean(dec_ms))
                                if dec_ms else 0.0),
           "mean_states": (float(statistics.fmean(n_states))
                           if n_states else 0.0),
           "mean_combats": (float(statistics.fmean(n_combats))
                            if n_combats else 0.0),
           "mean_value_evals": (float(statistics.fmean(n_value))
                                if n_value else 0.0),
           "state_scorer": state_scorer,
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
        # 无 scipy：精确符号检验（zeros 已剔除）
        from math import comb
        n = int(arr.size)
        pos = int((arr > 0).sum())
        k = min(pos, n - pos)
        p = 2.0 * sum(comb(n, i) for i in range(k + 1)) / (2.0 ** n)
        return float(min(1.0, p))


def summarize(rows: List[Dict[str, Any]], ref: Dict[int, int]) -> Dict[str, Any]:
    ranks = [r["rank"] for r in rows]
    diffs = [float(ref[r["seed"]] - r["rank"]) for r in rows]
    mean, lo, hi = _bootstrap_ci(diffs)
    return {"n_games": len(rows),
            "mean_rank": float(statistics.fmean(ranks)),
            "top4_rate": sum(1 for r in rows if r["top4"]) / len(rows),
            "win_rate": sum(1 for r in rows if r["win"]) / len(rows),
            "mean_decision_ms": float(statistics.fmean(
                [r["mean_decision_ms"] for r in rows])),
            "mean_states": float(statistics.fmean(
                [r["mean_states"] for r in rows])),
            "mean_combats": float(statistics.fmean(
                [r["mean_combats"] for r in rows])),
            "mean_decisions": float(statistics.fmean(
                [r["decisions"] for r in rows])),
            "mean_game_s": float(statistics.fmean(
                [r["game_s"] for r in rows])),
            "action_change_rate": float(statistics.fmean(
                [r["action_change_rate"] for r in rows])),
            "paired_diff_vs_bc": {"mean": mean, "ci95": [lo, hi],
                                  "wilcoxon_p": _wilcoxon_p(diffs),
                                  "n_pairs": len(diffs)},
            "rows": rows}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="回合内两两胜率搜索 pilot")
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--seeds-start", type=int, default=300)
    parser.add_argument("--opponents", default="heuristic,teacher")
    parser.add_argument("--states-budget", type=int, default=16)
    parser.add_argument("--samples-per-action", type=int, default=1)
    parser.add_argument("--combat-samples", type=int, default=1)
    parser.add_argument("--completion-policy", default="heuristic",
                        choices=["heuristic", "bc", "random"])
    parser.add_argument("--state-scorer", default="pairwise,value_prune_pairwise",
                        help="逗号分隔：pairwise / value_prune_pairwise / value(仅对照)")
    parser.add_argument("--prune-top-k", default="4,6",
                        help="逗号分隔的 K（value_prune_pairwise）")
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--out-dir", default="runs/search")
    parser.add_argument("--out-prefix", default="turn_search_pilot")
    parser.add_argument("--max-wall-seconds", type=float, default=1500.0)
    parser.add_argument("--max-steps", type=int, default=2000)
    args = parser.parse_args(argv)

    seeds = [args.seeds_start + i for i in range(max(1, args.games))]
    opponents = [x for x in args.opponents.split(",") if x]
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
                       "decisions": 0, "mean_decision_ms": 0.0,
                       "mean_states": 0.0, "mean_combats": 0.0,
                       "action_change_rate": 0.0,
                       "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            print(f"  {name} seed={seed} opp={opp} rank={row['rank']} "
                  f"game_s={row['game_s']} ms/dec={row['mean_decision_ms']:.1f}")
        cells[name] = rows

    _cell("bc_policy", run_bc_policy, checkpoint=args.checkpoint,
          max_steps=args.max_steps)
    modes = [m.strip() for m in args.state_scorer.split(",") if m.strip()]
    prune_ks = [int(x) for x in str(args.prune_top_k).split(",") if x.strip()]
    for mode in modes:
        if mode == "value_prune_pairwise":
            for k in prune_ks:
                _cell(f"turn_value_prune_k{k}", run_turn_search,
                      states_budget=args.states_budget,
                      samples_per_action=args.samples_per_action,
                      combat_samples=args.combat_samples,
                      completion_policy=args.completion_policy,
                      state_scorer=mode, prune_top_k=k,
                      checkpoint=args.checkpoint, max_steps=args.max_steps)
            continue
        name = ("turn_pairwise" if mode == "pairwise"
                else f"turn_{mode}_control")
        _cell(name, run_turn_search,
              states_budget=args.states_budget,
              samples_per_action=args.samples_per_action,
              combat_samples=args.combat_samples,
              completion_policy=args.completion_policy,
              state_scorer=mode, prune_top_k=prune_ks[0],
              checkpoint=args.checkpoint, max_steps=args.max_steps)
    ref = {r["seed"]: r["rank"] for r in cells.get("bc_policy", [])}
    matrix = [dict(summarize(rows, ref), name=name)
              for name, rows in cells.items() if rows and ref]
    report = {"meta": {"created_at": datetime.now().isoformat(timespec="seconds"),
                       "games": len(seeds), "seeds": seeds,
                       "opponents": opponents,
                       "states_budget": args.states_budget,
                       "samples_per_action": args.samples_per_action,
                       "combat_samples": args.combat_samples,
                       "completion_policy": args.completion_policy,
                       "state_scorer": modes,
                       "prune_top_k": args.prune_top_k,
                       "elapsed_s": round(time.perf_counter() - t0, 1),
                       "partial": bool(partial), "partial_cells": partial,
                       "note": ("回合内搜索：只枚举当前回合到 end_turn 的状态，"
                                "两两战斗胜率；不模拟后续回合、不用名次/价值网")},
              "matrix": matrix}
    out = Path(args.out_dir) / f"{args.out_prefix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    lines = ["# 回合内两两胜率搜索 pilot", "",
             f"- games/cell={len(seeds)}；seeds {seeds[0]}–{seeds[-1]}；"
             f"states={args.states_budget}；combat_samples={args.combat_samples}；"
             f"elapsed={report['meta']['elapsed_s']}s", "",
             "| 组合 | mean rank | top4 | win | ms/决策 | states/决策 | "
             "combats/决策 | 动作改变率 | 配对 Δ vs BC (95% CI) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for m in sorted(matrix, key=lambda x: x["mean_rank"]):
        pd = m["paired_diff_vs_bc"]
        lines.append(
            f"| {m['name']} | {m['mean_rank']:.2f} | {m['top4_rate']*100:.0f}% | "
            f"{m['win_rate']*100:.0f}% | {m['mean_decision_ms']:.1f} | "
            f"{m['mean_states']:.1f} | {m['mean_combats']:.1f} | "
            f"{m['action_change_rate']*100:.0f}% | "
            f"{pd['mean']:+.2f} [{pd['ci95'][0]:+.2f},{pd['ci95'][1]:+.2f}] |")
    lines += ["", "> 单回合搜索：不模拟下一回合、无 full-game rollout、无名次/价值网。"]
    if partial:
        lines.append(f"> partial: {partial}")
    md = Path(args.out_dir) / f"{args.out_prefix}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} and {md} ({report['meta']['elapsed_s']}s)")
    for m in sorted(matrix, key=lambda x: x["mean_rank"]):
        print(f"  {m['name']:16s} rank={m['mean_rank']:.2f} "
              f"top4={m['top4_rate']*100:.0f}% win={m['win_rate']*100:.0f}% "
              f"ms={m['mean_decision_ms']:.1f} states={m['mean_states']:.1f} "
              f"combats={m['mean_combats']:.1f} "
              f"chg={m['action_change_rate']*100:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
