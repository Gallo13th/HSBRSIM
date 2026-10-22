"""硬搜索（train-free）pilot 评测：rollout 选动作 vs 基线。

实验组：hard-search budget=1/2/4（候选 macro 剪枝前后）。
对照组：冻结 BC 策略、heuristic 无搜索、greedy+heuristic。
同 seed 配对、对手 heuristic/teacher 交替、oracle=false；不训练、不用价值网。

输出：runs/search/hard_search_pilot.json + hard_search_pilot.md
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
from hsbg.search.decision import GreedyDecision, make_scorer
from hsbg.search.hard_search import HardSearch, HardSearchConfig
from hsbg.search.wide_beam import generate_wide_candidates

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


def _execute_macro(env, obs, macro) -> Tuple[Any, bool, Dict[str, Any], int]:
    done = False
    info: Dict[str, Any] = {}
    steps = 0
    if macro is None:
        return obs, done, info, steps
    for cand in macro.steps:
        if done:
            break
        if getattr(obs, "phase", "") == "choice":
            obs, _, term, trunc, info = env.step(0)
            steps += 1
            done = bool(term or trunc)
            continue
        sig = cand.signature()
        idx = next((i for i, c in enumerate(obs.candidates)
                    if c.signature() == sig), None)
        if idx is None:
            break
        obs, _, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
    return obs, done, info, steps


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
           "game_s": round(time.perf_counter() - t0, 2)}
    env.close()
    return out


def run_heuristic_policy(*, seed: int, opponent: str,
                         max_steps: int = 2000) -> Dict[str, Any]:
    from hsbg.agents.heuristic import HeuristicPolicy

    env, obs = _new_env(seed, opponent)
    heur = HeuristicPolicy()
    t0 = time.perf_counter()
    done = False
    steps = 0
    info: Dict[str, Any] = {}
    while not done and steps < max_steps:
        idx = 0
        try:
            desc = heur.choose(env.game, env._agent)
            if desc is not None:
                sig = desc.to_candidate().signature()
                idx = next((i for i, c in enumerate(obs.candidates)
                            if c.signature() == sig), 0)
        except Exception:  # noqa: BLE001
            idx = 0
        obs, _, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": int(rank),
           "top4": rank <= 4, "win": rank == 1,
           "game_s": round(time.perf_counter() - t0, 2)}
    env.close()
    return out


def run_greedy_heuristic(*, seed: int, opponent: str,
                         max_steps: int = 2000) -> Dict[str, Any]:
    env, obs = _new_env(seed, opponent)
    decision = GreedyDecision(make_scorer("heuristic"), seed=int(seed) + 7,
                              macro_candidates=4)
    t0 = time.perf_counter()
    done = False
    steps = 0
    dec_ms: List[float] = []
    info: Dict[str, Any] = {}
    while not done and steps < max_steps:
        if getattr(obs, "phase", "") == "choice":
            obs, _, term, trunc, info = env.step(0)
            steps += 1
            done = bool(term or trunc)
            continue
        model = EngineForwardModel.from_env(env, clone=False)
        t1 = time.perf_counter()
        res = decision.decide(model)
        dec_ms.append((time.perf_counter() - t1) * 1000.0)
        obs, done, info, n = _execute_macro(env, obs, res.macro)
        steps += n
        if n == 0:
            if obs.candidates:
                obs, _, term, trunc, info = env.step(0)
                steps += 1
                done = bool(term or trunc)
            else:
                break
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": int(rank),
           "top4": rank <= 4, "win": rank == 1,
           "mean_decision_ms": float(statistics.fmean(dec_ms)) if dec_ms else 0.0,
           "game_s": round(time.perf_counter() - t0, 2)}
    env.close()
    return out


def run_hard_search(*, seed: int, opponent: str, budget: int,
                    candidates: int = 4, prune: bool = True,
                    max_horizon: int = 0, max_steps: int = 2000,
                    rollout_policy: str = "heuristic",
                    rollout_backend: str = "env",
                    screen_horizon: int = 0, screen_rollouts: int = 2,
                    finalists: int = 2, final_rollouts: int = 1,
                    bc_evaluator: Optional[PolicyEvaluator] = None
                    ) -> Dict[str, Any]:
    from collections import Counter

    env, obs = _new_env(seed, opponent)
    hs = HardSearch(HardSearchConfig(
        candidates=candidates, rollout_budget=budget, prune=prune,
        max_horizon_turns=max_horizon, seed=int(seed) + 7,
        rollout_policy=rollout_policy, rollout_backend=rollout_backend,
        screen_horizon_turns=screen_horizon,
        screen_rollouts=screen_rollouts,
        finalists=finalists, final_rollouts=final_rollouts))
    t0 = time.perf_counter()
    done = False
    steps = 0
    dec_ms: List[float] = []
    rollouts: List[int] = []
    n_candidates: List[int] = []
    sources: Counter = Counter()
    first_kinds: Counter = Counter()
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
        if bc_evaluator is not None:
            try:
                top = bc_evaluator.top_action(model)
                bc_sig = None if top is None else top[0].signature()
            except Exception:  # noqa: BLE001
                bc_sig = None
        t1 = time.perf_counter()
        res = hs.decide(model)
        dec_ms.append((time.perf_counter() - t1) * 1000.0)
        rollouts.append(res.total_rollouts)
        n_candidates.append(len(res.stats))
        for st in res.stats:
            sources[str(getattr(st.macro, "source", "?"))] += 1
            first_kinds[str(getattr(st.macro.first, "kind", "?"))] += 1
        if res.best is not None and bc_sig is not None:
            changed.append(res.best.first.signature() != bc_sig)
        obs, done, info, n = _execute_macro(env, obs, res.best)
        steps += n
        if n == 0:
            if obs.candidates:
                obs, _, term, trunc, info = env.step(0)
                steps += 1
                done = bool(term or trunc)
            else:
                break
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": int(rank),
           "top4": rank <= 4, "win": rank == 1,
           "mean_decision_ms": float(statistics.fmean(dec_ms)) if dec_ms else 0.0,
           "mean_rollouts": float(statistics.fmean(rollouts)) if rollouts else 0.0,
           "mean_candidates": (float(statistics.fmean(n_candidates))
                               if n_candidates else 0.0),
           "candidate_sources": dict(sources),
           "candidate_first_kinds": dict(first_kinds),
           "action_change_rate": (float(sum(changed) / len(changed))
                                  if changed else 0.0),
           "n_action_compared": len(changed),
           "game_s": round(time.perf_counter() - t0, 2)}
    env.close()
    return out


def run_wide_beam(*, seed: int, opponent: str, width: int,
                  candidates_target: int = 12, max_steps: int = 2000,
                  screen_horizon: int = 3, screen_rollouts: int = 1,
                  finalists: Optional[int] = None, final_rollouts: int = 1,
                  rollout_policy: str = "heuristic",
                  rollout_epsilon: float = 0.15,
                  bc_evaluator: Optional[PolicyEvaluator] = None,
                  bc_top_fn: Any = None) -> Dict[str, Any]:
    """宽候选 + 大 beam（W）；两阶段：horizon 筛 top-W，再 full top-N 复核。"""
    from collections import Counter

    env, obs = _new_env(seed, opponent)
    t0 = time.perf_counter()
    done = False
    steps = 0
    dec_ms: List[float] = []
    rollouts: List[int] = []
    n_candidates: List[int] = []
    sources: Counter = Counter()
    changed: List[bool] = []
    bc_in_cand: List[bool] = []
    bc_in_topw: List[bool] = []
    screen_var: List[float] = []
    full_var: List[float] = []
    info: Dict[str, Any] = {}
    full_top = (max(2, min(int(width) // 2, 4)) if finalists is None
                else max(1, int(finalists)))
    while not done and steps < max_steps:
        if getattr(obs, "phase", "") == "choice":
            obs, _, term, trunc, info = env.step(0)
            steps += 1
            done = bool(term or trunc)
            continue
        model = EngineForwardModel.from_env(env, clone=False)
        bc_sig = None
        if bc_evaluator is not None:
            try:
                top = bc_evaluator.top_action(model)
                bc_sig = None if top is None else top[0].signature()
            except Exception:  # noqa: BLE001
                bc_sig = None
        cands = generate_wide_candidates(
            model, bc_evaluator, target=candidates_target,
            seed=int(seed) + 7, max_first=min(12, candidates_target))
        cfg = HardSearchConfig(
            candidates=max(1, len(cands)), rollout_budget=1,
            rollout_backend="env", rollout_policy=rollout_policy,
            rollout_epsilon=rollout_epsilon,
            screen_horizon_turns=screen_horizon,
            screen_rollouts=screen_rollouts,
            beam_width=int(width), finalists=int(full_top),
            final_rollout_turns=0, final_rollouts=final_rollouts,
            seed=int(seed) + 7, prune=False)
        hs = HardSearch(cfg, candidate_macros=cands)
        t1 = time.perf_counter()
        res = hs.decide(model)
        dec_ms.append((time.perf_counter() - t1) * 1000.0)
        rollouts.append(res.total_rollouts)
        n_candidates.append(len(res.stats))
        for st in res.stats:
            sources[str(getattr(st.macro, "source", "?"))] += 1
        # 诊断：BC 首步在候选中/在 top-W 中；screen/full 方差
        ordered = sorted(res.stats, key=lambda s: (
            -s.screen_utility, s.screen_mean_rank))
        topw = ordered[:int(width)]
        if bc_sig is not None:
            bc_in_cand.append(any(st.macro.first.signature() == bc_sig
                                  for st in res.stats))
            bc_in_topw.append(any(st.macro.first.signature() == bc_sig
                                  for st in topw))
        sv = [np.std(st.screen_ranks) for st in topw
              if len(st.screen_ranks) > 1]
        if sv:
            screen_var.append(float(np.mean(sv)))
        fin_top = topw[:int(full_top)]
        fv = [np.std(st.ranks) for st in fin_top if len(st.ranks) > 1]
        if fv:
            full_var.append(float(np.mean(fv)))
        if res.best is not None and bc_sig is not None:
            changed.append(res.best.first.signature() != bc_sig)
        obs, done, info, n = _execute_macro(env, obs, res.best)
        steps += n
        if n == 0:
            if obs.candidates:
                obs, _, term, trunc, info = env.step(0)
                steps += 1
                done = bool(term or trunc)
            else:
                break
    rank = _rank(env, info)
    out = {"seed": int(seed), "opponent": opponent, "rank": int(rank),
           "top4": rank <= 4, "win": rank == 1,
           "mean_decision_ms": float(statistics.fmean(dec_ms)) if dec_ms else 0.0,
           "mean_rollouts": float(statistics.fmean(rollouts)) if rollouts else 0.0,
           "mean_candidates": (float(statistics.fmean(n_candidates))
                               if n_candidates else 0.0),
           "candidate_sources": dict(sources),
           "action_change_rate": (float(sum(changed) / len(changed))
                                  if changed else 0.0),
           "n_action_compared": len(changed),
           "bc_first_in_candidates": (float(sum(bc_in_cand) / len(bc_in_cand))
                                      if bc_in_cand else None),
           "bc_first_in_topw": (float(sum(bc_in_topw) / len(bc_in_topw))
                                if bc_in_topw else None),
           "screen_rank_var": (float(statistics.fmean(screen_var))
                               if screen_var else None),
           "full_rank_var": (float(statistics.fmean(full_var))
                             if full_var else None),
           "game_s": round(time.perf_counter() - t0, 2)}
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
    return float(arr.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


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
    out = {
        "n_games": len(rows),
        "mean_rank": float(statistics.fmean(ranks)),
        "top4_rate": sum(1 for r in rows if r["top4"]) / len(rows),
        "win_rate": sum(1 for r in rows if r["win"]) / len(rows),
        "mean_game_s": float(statistics.fmean([r["game_s"] for r in rows])),
        "paired_diff_vs_bc": {"mean": mean, "ci95": [lo, hi],
                              "better": bool(lo > 0), "worse": bool(hi < 0),
                              "wilcoxon_p": _wilcoxon_p(diffs),
                              "n_pairs": len(diffs)},
        "rows": rows,
    }
    if any("mean_decision_ms" in r for r in rows):
        out["mean_decision_ms"] = float(statistics.fmean(
            [r["mean_decision_ms"] for r in rows]))
    if any("mean_rollouts" in r for r in rows):
        out["mean_rollouts"] = float(statistics.fmean(
            [r["mean_rollouts"] for r in rows]))
    if any("mean_candidates" in r for r in rows):
        out["mean_candidates"] = float(statistics.fmean(
            [r["mean_candidates"] for r in rows]))
    if any("action_change_rate" in r for r in rows):
        out["action_change_rate"] = float(statistics.fmean(
            [r["action_change_rate"] for r in rows]))
    for key in ("bc_first_in_candidates", "bc_first_in_topw",
                "screen_rank_var", "full_rank_var"):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if vals:
            out[key] = float(statistics.fmean(vals))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="硬搜索（train-free）pilot")
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--seeds-start", type=int, default=300)
    parser.add_argument("--opponents", default="heuristic,teacher")
    parser.add_argument("--out-dir", default="runs/search")
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--max-steps", type=int, default=2000)
    parser.add_argument("--budgets", default="1,2,4")
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument("--max-horizon", type=int, default=0,
                        help="0=到终局；>0=截断 horizon（回合）")
    parser.add_argument("--screen-horizon", type=int, default=0,
                        help="两阶段筛选 horizon（0=不用两阶段）")
    parser.add_argument("--screen-rollouts", type=int, default=2)
    parser.add_argument("--finalists", type=int, default=2)
    parser.add_argument("--final-rollouts", type=int, default=1)
    parser.add_argument("--rollout-policy", default="heuristic",
                        choices=["heuristic", "random"])
    parser.add_argument("--rollout-backend", default="env",
                        choices=["env", "legacy"],
                        help="env=正常对手买牌(推荐)；legacy=旧退化实现(对照)")
    parser.add_argument("--no-prune-budget", type=int, default=0,
                        help="额外跑一个“不剪枝”的 budget 对照（0=不跑）")
    parser.add_argument("--skip-heuristic", action="store_true",
                        help="不跑 heuristic_policy 无搜索对照")
    parser.add_argument("--skip-greedy", action="store_true",
                        help="不跑 greedy_heuristic 对照（只跑 BC vs hard）")
    parser.add_argument("--out-prefix", default="hard_search_pilot",
                        help="输出文件名前缀，如 hard_search_beamwide")
    parser.add_argument("--wide-widths", default="",
                        help="宽候选 beam 宽度列表，如 4,8,16（设置后替代 budgets）")
    parser.add_argument("--wide-candidates", type=int, default=12,
                        help="宽候选目标数量（8–16）")
    parser.add_argument("--wide-variance", action="store_true",
                        help="方差压缩实验：W=8，h3-r2-full3 与 h1-r2-full3 两格")
    parser.add_argument("--wide-randomized", action="store_true",
                        help="随机化 rollout 实验：random-seed 与 epsilon-policy 两格")
    parser.add_argument("--max-wall-seconds", type=float, default=1500.0,
                        help="墙钟上限；到点保存已完成结果并标 partial")
    args = parser.parse_args(argv)

    games = max(1, int(args.games))
    seeds = [args.seeds_start + i for i in range(games)]
    opponents = [x for x in args.opponents.split(",") if x]
    t0 = time.perf_counter()
    deadline = (t0 + float(args.max_wall_seconds)
                if args.max_wall_seconds and args.max_wall_seconds > 0
                else None)
    cells: Dict[str, List[Dict[str, Any]]] = {}
    partial_cells: List[str] = []
    stopped = False

    def _cell(name: str, fn, **kw) -> None:
        nonlocal stopped
        rows = []
        for i, seed in enumerate(seeds):
            if deadline is not None and time.perf_counter() >= deadline:
                stopped = True
                partial_cells.append(name)
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
                  f"game_s={row['game_s']}")
        cells[name] = rows

    _cell("bc_policy", run_bc_policy, checkpoint=args.checkpoint,
          max_steps=args.max_steps)
    if not args.skip_heuristic:
        _cell("heuristic_policy", run_heuristic_policy, max_steps=args.max_steps)
    if not args.skip_greedy:
        _cell("greedy_heuristic", run_greedy_heuristic, max_steps=args.max_steps)
    bc_eval = PolicyEvaluator(args.checkpoint)
    budgets: List[int] = []
    if args.wide_randomized:
        variants = [
            ("hard-random-seed", dict(rollout_policy="random")),
            ("hard-epsilon-policy", dict(rollout_policy="epsilon",
                                         rollout_epsilon=0.15)),
        ]
        for name, kw in variants:
            if stopped:
                break
            _cell(name, run_wide_beam, width=8,
                  candidates_target=args.wide_candidates,
                  max_steps=args.max_steps, screen_horizon=3,
                  screen_rollouts=2, finalists=2, final_rollouts=3,
                  bc_evaluator=bc_eval, **kw)
    elif args.wide_variance:
        variants = [
            ("hard-var-h3-r2-full3", dict(screen_horizon=3,
                                          screen_rollouts=2, finalists=2,
                                          final_rollouts=3)),
            ("hard-var-h1-r2-full3", dict(screen_horizon=1,
                                          screen_rollouts=2, finalists=2,
                                          final_rollouts=3)),
        ]
        for name, kw in variants:
            if stopped:
                break
            _cell(name, run_wide_beam, width=8,
                  candidates_target=args.wide_candidates,
                  max_steps=args.max_steps, bc_evaluator=bc_eval, **kw)
    elif args.wide_widths:
        widths = [int(x) for x in args.wide_widths.split(",") if x]
        for w in widths:
            if stopped:
                break
            _cell(f"beam_w{w}", run_wide_beam, width=w,
                  candidates_target=args.wide_candidates,
                  max_steps=args.max_steps, bc_evaluator=bc_eval)
    else:
        budgets = [int(x) for x in args.budgets.split(",") if x]
        for b in budgets:
            if stopped:
                break
            _cell(f"hard_b{b}_prune", run_hard_search, budget=b,
                  candidates=args.candidates, prune=True,
                  max_horizon=args.max_horizon, max_steps=args.max_steps,
                  rollout_policy=args.rollout_policy,
                  rollout_backend=args.rollout_backend,
                  screen_horizon=args.screen_horizon,
                  screen_rollouts=args.screen_rollouts,
                  finalists=args.finalists,
                  final_rollouts=args.final_rollouts,
                  bc_evaluator=bc_eval)
    if (not stopped) and args.no_prune_budget > 0:
        _cell(f"hard_b{args.no_prune_budget}_noprune", run_hard_search,
              budget=args.no_prune_budget, candidates=args.candidates,
              prune=False, max_horizon=args.max_horizon,
              max_steps=args.max_steps, rollout_policy=args.rollout_policy)

    ref = {r["seed"]: r["rank"] for r in cells.get("bc_policy", [])}
    matrix = []
    for name, rows in cells.items():
        if not rows or not ref:
            continue
        agg = summarize(rows, ref)
        agg["name"] = name
        matrix.append(agg)

    report = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "games": games, "seeds": seeds, "opponents": opponents,
            "candidates": args.candidates, "budgets": budgets,
            "max_horizon": args.max_horizon,
            "screen_horizon": args.screen_horizon,
            "screen_rollouts": args.screen_rollouts,
            "finalists": args.finalists,
            "final_rollouts": args.final_rollouts,
            "rollout_policy": args.rollout_policy,
            "rollout_backend": args.rollout_backend,
            "wide_widths": args.wide_widths,
            "wide_candidates": args.wide_candidates,
            "wide_variance": bool(args.wide_variance),
            "wide_randomized": bool(args.wide_randomized),
            "checkpoint": args.checkpoint,
            "note": ("train-free 硬搜索：rollout 到终局/高胜率；不用价值网；"
                     "同 seed 配对；oracle=false"),
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "max_wall_seconds": args.max_wall_seconds,
            "partial": bool(partial_cells or stopped),
            "partial_cells": partial_cells,
            "stopped_by_wall": bool(stopped),
        },
        "matrix": matrix,
    }
    out = Path(args.out_dir) / f"{args.out_prefix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    lines = ["# 硬搜索（train-free）pilot", "",
             f"- games/cell: {games}；seeds {seeds[0]}–{seeds[-1]}；"
             f"opponents {opponents}；rollout={args.rollout_policy}；"
             f"horizon={args.max_horizon or '终局'}", "",
             "| 组合 | mean rank | top4 | win | ms/决策 | rollouts/决策 | "
             "候选数 | 动作改变率 vs BC | 配对 Δ vs BC (95% CI) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for m in sorted(matrix, key=lambda x: x["mean_rank"]):
        pd = m["paired_diff_vs_bc"]
        chg = m.get("action_change_rate")
        lines.append(
            f"| {m['name']} | {m['mean_rank']:.2f} | {m['top4_rate']*100:.0f}% | "
            f"{m['win_rate']*100:.0f}% | {m.get('mean_decision_ms', 0):.0f} | "
            f"{m.get('mean_rollouts', 0):.1f} | "
            f"{m.get('mean_candidates', 0):.1f} | "
            f"{'—' if chg is None else f'{chg*100:.0f}%'} | "
            f"{pd['mean']:+.2f} [{pd['ci95'][0]:+.2f},{pd['ci95'][1]:+.2f}] |")
    lines += ["", "> pilot 局数少、CI 宽；硬搜索成本见 ms/决策；不做最终选型结论。"]
    diag = [m for m in matrix if m.get("bc_first_in_topw") is not None]
    if diag:
        lines += ["", "## 诊断（候选质量 vs 数量）", "",
                  "| 组合 | 候选数 | BC 首步在候选 | BC 首步在 top-W | screen rank std | full rank std |",
                  "|---|---:|---:|---:|---:|---:|"]
        for m in sorted(diag, key=lambda x: x["mean_rank"]):
            lines.append(
                f"| {m['name']} | {m['mean_candidates']:.1f} | "
                f"{m['bc_first_in_candidates']*100:.0f}% | "
                f"{m['bc_first_in_topw']*100:.0f}% | "
                f"{m['screen_rank_var']:.2f} | "
                f"{(m.get('full_rank_var') or 0):.2f} |")
    if partial_cells or stopped:
        lines.append(f"> **partial**：墙钟到点停止；未完成/被截断的 cell：{partial_cells}")
    md = Path(args.out_dir) / f"{args.out_prefix}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} and {md} ({report['meta']['elapsed_s']}s)")
    for m in sorted(matrix, key=lambda x: x["mean_rank"]):
        print(f"  {m['name']:22s} rank={m['mean_rank']:.2f} "
              f"top4={m['top4_rate']*100:.0f}% win={m['win_rate']*100:.0f}% "
              f"ms={m.get('mean_decision_ms', 0):.0f} "
              f"rollouts={m.get('mean_rollouts', 0):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
