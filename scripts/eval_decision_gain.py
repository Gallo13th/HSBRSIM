"""无训练决策器 pilot 评测（不训练、不更新权重）。

矩阵：{greedy-1ply, beam-w2, beam-w4, puct-n8, puct-n32}
      × {bc_value, combat, heuristic, uniform}
每局固定 seed/对手（heuristic/teacher 混合），同 seed 配对；报告名次/前四/吃鸡、
配对差 bootstrap CI / Wilcoxon（scipy 可用则用）、决策耗时、动作改变率（vs BC top-1）。

输出：runs/search/decision_pilot.json + decision_pilot.md
"""

from __future__ import annotations

import argparse
import json
import math
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
from hsbg.search.decision import (
    BCValueScorer,
    DecisionResult,
    make_decision,
    make_scorer,
)

CHECKPOINT = "runs/bc/official_320/policy_bc.pt"

#: 决策矩阵（名字 → factory 参数）
DECISION_SPECS: Dict[str, Dict[str, Any]] = {
    "greedy-1ply": {"kind": "greedy", "macro_candidates": 4},
    "beam-w2": {"kind": "beam", "width": 2, "depth": 1},
    "beam-w4": {"kind": "beam", "width": 4, "depth": 1},
    "puct-n8": {"kind": "puct", "width": 2, "simulations": 8},
    "puct-n32": {"kind": "puct", "width": 2, "simulations": 32},
}
SCORER_NAMES = ["bc_value", "combat", "heuristic", "uniform"]


def _mk(decision_name: str, scorer, *, seed: int):
    spec = DECISION_SPECS[decision_name]
    return make_decision(
        spec["kind"], scorer, seed=seed, width=spec.get("width", 2),
        depth=spec.get("depth", 1), simulations=spec.get("simulations", 8),
        macro_candidates=spec.get("macro_candidates", 4),
    )


def _rank_of(env: BattlegroundsEnv, info: Dict[str, Any]) -> int:
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


def _execute_macro(env: BattlegroundsEnv, obs, macro) -> Tuple[Any, bool, Dict[str, Any], int]:
    """在当前 env 上按 macro 逐步执行；返回 (obs, done, info, steps)。"""
    done = False
    info: Dict[str, Any] = {}
    steps = 0
    if macro is None:
        return obs, done, info, steps
    for cand in macro.steps:
        if done:
            break
        # choice 步：pilot 用默认选择，避免卡死
        if getattr(obs, "phase", "") == "choice":
            obs, _, term, trunc, info = env.step(0)
            steps += 1
            done = bool(term or trunc)
            if done:
                break
        sig = cand.signature()
        idx = next((i for i, c in enumerate(obs.candidates)
                    if c.signature() == sig), None)
        if idx is None:
            break
        obs, _, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
    return obs, done, info, steps


def run_one_game(*, seed: int, opponent: str, decision_name: str,
                 scorer_name: str, max_steps: int = 2000,
                 bc_evaluator: Optional[PolicyEvaluator] = None
                 ) -> Dict[str, Any]:
    env = BattlegroundsEnv(num_players=8, opponent=opponent, seed=int(seed))
    obs = env.reset(seed=int(seed))
    scorer = make_scorer(scorer_name)
    decision = _mk(decision_name, scorer, seed=int(seed) + 7)
    decisions: List[Dict[str, Any]] = []
    t_game = time.perf_counter()
    done = False
    steps = 0
    info: Dict[str, Any] = {}
    while not done and steps < max_steps:
        if getattr(obs, "phase", "") == "choice":
            obs, _, term, trunc, info = env.step(0)
            steps += 1
            done = bool(term or trunc)
            continue
        model = EngineForwardModel.from_env(env, clone=False)
        t0 = time.perf_counter()
        try:
            res: DecisionResult = decision.decide(model)
        except Exception as exc:  # noqa: BLE001
            decisions.append({"turn": int(obs.turn), "error": f"{type(exc).__name__}: {exc}"})
            break
        dt = time.perf_counter() - t0
        chosen_sig = None if res.macro is None else res.macro.first.signature()
        bc_sig = None
        if bc_evaluator is not None:
            try:
                top = bc_evaluator.top_action(model)
                bc_sig = None if top is None else top[0].signature()
            except Exception:  # noqa: BLE001
                bc_sig = None
        decisions.append({
            "turn": int(obs.turn),
            "ms": round(dt * 1000.0, 2),
            "score": round(float(res.score), 4),
            "n_steps": 0 if res.macro is None else len(res.macro.steps),
            "chosen_first": None if chosen_sig is None else list(chosen_sig),
            "bc_top": None if bc_sig is None else list(bc_sig),
            "changed_vs_bc": (chosen_sig is not None and bc_sig is not None
                              and chosen_sig != bc_sig),
        })
        obs, done, info, executed = _execute_macro(env, obs, res.macro)
        steps += executed
        if executed == 0:
            # 决策失败兜底：走第一个合法候选，保证能推进
            cands = obs.candidates
            if cands:
                obs, _, term, trunc, info = env.step(0)
                steps += 1
                done = bool(term or trunc)
            else:
                break
    rank = _rank_of(env, info) if done else _rank_of(env, info)
    game_s = time.perf_counter() - t_game
    dec_ms = [d["ms"] for d in decisions if isinstance(d.get("ms"), (int, float))]
    changed = [bool(d["changed_vs_bc"]) for d in decisions
               if "changed_vs_bc" in d]
    result = {
        "seed": int(seed),
        "opponent": str(opponent),
        "decision": decision_name,
        "scorer": scorer_name,
        "rank": int(rank),
        "top4": bool(int(rank) <= 4),
        "win": bool(int(rank) == 1),
        "steps": int(steps),
        "turns": int(getattr(obs, "turn", 0)),
        "decisions": len(decisions),
        "mean_decision_ms": float(statistics.fmean(dec_ms)) if dec_ms else 0.0,
        "game_s": round(game_s, 2),
        "action_change_rate": (sum(changed) / len(changed)) if changed else 0.0,
        "n_changed": int(sum(changed)),
        "n_compared": len(changed),
        "terminated": bool(done),
        "errors": [d["error"] for d in decisions if "error" in d],
    }
    env.close()
    return result


def run_bc_policy_game(*, seed: int, opponent: str,
                       checkpoint: str = CHECKPOINT,
                       max_steps: int = 2000) -> Dict[str, Any]:
    """同 seed/对手下的冻结 BC 策略基线（不是本矩阵的 macro 决策器）。"""
    env = BattlegroundsEnv(num_players=8, opponent=opponent, seed=int(seed))
    obs = env.reset(seed=int(seed))
    try:
        policy = make_policy(str(checkpoint), device="cpu")
    except Exception:  # noqa: BLE001
        policy = make_policy("checkpoint:" + str(checkpoint), device="cpu")
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
    rank = _rank_of(env, info)
    game_s = time.perf_counter() - t0
    env.close()
    return {"seed": int(seed), "opponent": str(opponent), "rank": int(rank),
            "top4": bool(int(rank) <= 4), "win": bool(int(rank) == 1),
            "steps": steps, "game_s": round(game_s, 2), "terminated": bool(done)}


def _bootstrap_ci(diffs: Sequence[float], *, n_boot: int = 2000,
                  seed: int = 0) -> Tuple[float, float, float]:
    arr = np.asarray(list(diffs), dtype=np.float64)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        means[i] = rng.choice(arr, size=arr.size, replace=True).mean()
    return (float(arr.mean()), float(np.percentile(means, 2.5)),
            float(np.percentile(means, 97.5)))


def _wilcoxon_p(diffs: Sequence[float]) -> Optional[float]:
    arr = np.asarray([d for d in diffs if d != 0.0], dtype=np.float64)
    if arr.size == 0:
        return None
    try:
        from scipy.stats import wilcoxon  # type: ignore
        return float(wilcoxon(arr).pvalue)
    except Exception:  # noqa: BLE001 - scipy 可选；回退符号检验
        pos = int((arr > 0).sum())
        return float(min(1.0, 2 * min(pos, arr.size - pos) / max(1, arr.size)))


def summarize(rows: List[Dict[str, Any]], reference: Dict[int, int]) -> Dict[str, Any]:
    ranks = [r["rank"] for r in rows]
    diffs = [float(reference[r["seed"]] - r["rank"]) for r in rows
             if r["seed"] in reference]  # 正=比参考好
    mean, lo, hi = _bootstrap_ci(diffs, seed=0)
    return {
        "n_games": len(rows),
        "mean_rank": float(statistics.fmean(ranks)),
        "std_rank": float(statistics.pstdev(ranks)) if len(ranks) > 1 else 0.0,
        "top4_rate": float(sum(1 for r in rows if r["top4"]) / len(rows)),
        "win_rate": float(sum(1 for r in rows if r["win"]) / len(rows)),
        "mean_decision_ms": float(statistics.fmean(
            [r["mean_decision_ms"] for r in rows])),
        "mean_game_s": float(statistics.fmean([r["game_s"] for r in rows])),
        "action_change_rate": float(statistics.fmean(
            [r["action_change_rate"] for r in rows])),
        "paired_diff_vs_ref": {
            "mean": mean, "ci95": [lo, hi],
            "better": bool(lo > 0), "worse": bool(hi < 0),
            "wilcoxon_p": _wilcoxon_p(diffs),
            "n_pairs": len(diffs),
        },
        "errors": sum(1 for r in rows if r.get("errors")),
        "rows": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="无训练决策器 pilot 评测")
    parser.add_argument("--games", type=int, default=5,
                        help="每个组合的局数（pilot 5–10；全量 20）")
    parser.add_argument("--seeds-start", type=int, default=300)
    parser.add_argument("--opponents", default="heuristic,teacher")
    parser.add_argument("--decisions", default=",".join(DECISION_SPECS))
    parser.add_argument("--scorers", default=",".join(SCORER_NAMES))
    parser.add_argument("--max-steps", type=int, default=2000)
    parser.add_argument("--out-dir", default="runs/search")
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--baseline-only", action="store_true",
                        help="只跑同 seed 的冻结 BC 策略基线（与矩阵对照）")
    args = parser.parse_args(argv)

    decisions = [x for x in args.decisions.split(",") if x]
    scorers = [x for x in args.scorers.split(",") if x]
    opponents = [x for x in args.opponents.split(",") if x]
    seeds = [args.seeds_start + i for i in range(int(args.games))]
    if not decisions or not scorers or not seeds:
        print("empty matrix")
        return 2

    if args.baseline_only:
        rows = []
        for i, seed in enumerate(seeds):
            opp = opponents[i % len(opponents)]
            row = run_bc_policy_game(seed=seed, opponent=opp,
                                     checkpoint=args.checkpoint)
            rows.append(row)
            print(f"  bc_policy seed={seed} opp={opp} rank={row['rank']}")
        ranks = [r["rank"] for r in rows]
        baseline = {
            "meta": {"created_at": datetime.now().isoformat(timespec="seconds"),
                     "games": len(rows), "seeds": seeds,
                     "opponents": opponents, "note": "冻结 BC 策略基线（非同矩阵 macro 决策器）"},
            "n_games": len(rows),
            "mean_rank": float(statistics.fmean(ranks)),
            "top4_rate": float(sum(1 for r in rows if r["top4"]) / len(rows)),
            "win_rate": float(sum(1 for r in rows if r["win"]) / len(rows)),
            "mean_game_s": float(statistics.fmean([r["game_s"] for r in rows])),
            "rows": rows,
        }
        out = Path(args.out_dir) / "decision_bc_baseline.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"wrote {out}: mean_rank={baseline['mean_rank']:.2f} "
              f"top4={baseline['top4_rate']*100:.0f}% "
              f"win={baseline['win_rate']*100:.0f}%")
        return 0

    print(f"pilot: {len(decisions)} decisions × {len(scorers)} scorers × "
          f"{len(seeds)} games = {len(decisions) * len(scorers) * len(seeds)} games")
    t0 = time.perf_counter()
    bc_eval = PolicyEvaluator(args.checkpoint)
    results: Dict[str, Dict[str, Any]] = {}
    all_rows: List[Dict[str, Any]] = []
    for dname in decisions:
        for sname in scorers:
            key = f"{dname}|{sname}"
            rows: List[Dict[str, Any]] = []
            for i, seed in enumerate(seeds):
                opp = opponents[i % len(opponents)]
                try:
                    row = run_one_game(
                        seed=seed, opponent=opp, decision_name=dname,
                        scorer_name=sname, max_steps=args.max_steps,
                        bc_evaluator=bc_eval)
                except Exception as exc:  # noqa: BLE001
                    row = {"seed": seed, "opponent": opp, "decision": dname,
                           "scorer": sname, "rank": 8, "top4": False,
                           "win": False, "errors": [f"{type(exc).__name__}: {exc}"],
                           "mean_decision_ms": 0.0, "game_s": 0.0,
                           "action_change_rate": 0.0, "n_changed": 0,
                           "n_compared": 0, "steps": 0, "turns": 0,
                           "decisions": 0, "terminated": False}
                rows.append(row)
                all_rows.append(row)
                print(f"  {key} seed={seed} opp={opp} rank={row['rank']} "
                      f"ms/dec={row.get('mean_decision_ms',0):.1f}")
            results[key] = rows

    reference_key = "greedy-1ply|bc_value"
    if reference_key not in results:
        reference_key = next(iter(results))
    reference = {r["seed"]: r["rank"] for r in results[reference_key]}
    matrix: List[Dict[str, Any]] = []
    for key, rows in results.items():
        dname, sname = key.split("|", 1)
        agg = summarize(rows, reference)
        agg.update({"decision": dname, "scorer": sname})
        matrix.append(agg)

    report = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "games_per_cell": len(seeds),
            "seeds": seeds,
            "opponents": opponents,
            "decisions": decisions,
            "scorers": scorers,
            "reference": reference_key,
            "checkpoint": args.checkpoint,
            "note": ("无训练 pilot；macro 回合级（每次决策=一个回合的 macro），"
                     "K=1、oracle=False；隐藏信息缺失（determinization 仅摘要）"),
            "elapsed_s": round(time.perf_counter() - t0, 1),
        },
        "matrix": matrix,
    }
    out_json = Path(args.out_dir) / "decision_pilot.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    # Markdown
    lines = ["# 无训练决策器 pilot（不训练）", "",
             f"- games/cell: {len(seeds)}；seeds {seeds[0]}–{seeds[-1]}；"
             f"opponents {opponents}",
             f"- reference: `{reference_key}`；配对差正=比参考好", "",
             "| decision | scorer | mean rank | top4 | win | ms/decision | "
             "paired Δ vs ref (95% CI) | action change vs BC |",
             "|---|---|---:|---:|---:|---:|---|---:|"]
    for m in sorted(matrix, key=lambda x: (x["mean_rank"], x["decision"], x["scorer"])):
        pd = m["paired_diff_vs_ref"]
        lines.append(
            f"| {m['decision']} | {m['scorer']} | {m['mean_rank']:.2f} | "
            f"{m['top4_rate']*100:.0f}% | {m['win_rate']*100:.0f}% | "
            f"{m['mean_decision_ms']:.1f} | "
            f"{pd['mean']:+.2f} [{pd['ci95'][0]:+.2f},{pd['ci95'][1]:+.2f}] | "
            f"{m['action_change_rate']*100:.0f}% |")
    lines += ["", "> 注：pilot 局数少，CI 宽；只用于排除实现问题/排序参考，不是最终结论。"]
    out_md = Path(args.out_dir) / "decision_pilot.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_json} and {out_md} ({report['meta']['elapsed_s']}s)")
    for m in sorted(matrix, key=lambda x: x["mean_rank"])[:8]:
        print(f"  {m['decision']:12s} {m['scorer']:10s} rank={m['mean_rank']:.2f} "
              f"top4={m['top4_rate']*100:.0f}% win={m['win_rate']*100:.0f}% "
              f"ms={m['mean_decision_ms']:.0f} dRef={m['paired_diff_vs_ref']['mean']:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
