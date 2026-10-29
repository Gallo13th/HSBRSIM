"""状态级硬搜索信号诊断（不做完整对局）。

10 个决策状态（BC/teacher 轨迹，覆盖 turn 3/6/9）：
- 每个状态生成宽候选（~8–12），对每个候选 full-to-end R=5 随机化 epsilon rollout；
- 记录候选名次均值/std/前四率；
- 比较：候选 max-min 是否 > 噪声(std/√R)、BC 首步 vs 最优候选 lift、
  是否存在显著优于 BC 首步的候选（均值差>1 且配对 bootstrap CI 不跨 0）。

输出 runs/search/hard_signal_diag.json + .md。
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
from hsbg.search.hard_search import rollout_to_terminal
from hsbg.search.wide_beam import generate_wide_candidates

CHECKPOINT = "runs/bc/official_320/policy_bc.pt"


def build_states(*, n_states: int = 10, turns: Sequence[int] = (3, 6, 9),
                 seed_start: int = 500) -> List[EngineForwardModel]:
    states: List[EngineForwardModel] = []
    seed = seed_start
    while len(states) < n_states and seed < seed_start + 40:
        opp = "heuristic" if (seed - seed_start) % 2 == 0 else "teacher"
        env = BattlegroundsEnv(num_players=8, opponent=opp, seed=seed)
        obs = env.reset(seed=seed)
        teacher = make_policy("teacher")
        try:
            teacher.bind_env(env)
        except Exception:  # noqa: BLE001
            pass
        wanted = set(int(t) for t in turns)
        steps = 0
        while steps < 600:
            t = int(getattr(obs, "turn", 0))
            if t in wanted and t > 0:
                wanted.discard(t)
                try:
                    states.append(EngineForwardModel.from_env(env, clone=True))
                except Exception:  # noqa: BLE001
                    pass
                if len(states) >= n_states:
                    break
            obs, _, term, trunc, _ = env.step(act_index(teacher, obs))
            steps += 1
            if term or trunc:
                break
        env.close()
        seed += 1
    return states[:n_states]


def _bootstrap_ci(diffs: Sequence[float], n_boot: int = 2000,
                  seed: int = 0) -> Tuple[float, float, float]:
    arr = np.asarray(diffs, dtype=np.float64)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(arr, size=arr.size, replace=True).mean()
                      for _ in range(n_boot)])
    return (float(arr.mean()), float(np.percentile(means, 2.5)),
            float(np.percentile(means, 97.5)))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="硬搜索状态级信号诊断")
    parser.add_argument("--states", type=int, default=10)
    parser.add_argument("--rollouts", type=int, default=5)
    parser.add_argument("--turns", default="3,6,9")
    parser.add_argument("--candidates", type=int, default=12)
    parser.add_argument("--epsilon", type=float, default=0.15)
    parser.add_argument("--out-dir", default="runs/search")
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    args = parser.parse_args(argv)

    turns = [int(x) for x in args.turns.split(",") if x]
    t0 = time.perf_counter()
    bc_eval = PolicyEvaluator(args.checkpoint)
    states = build_states(n_states=args.states, turns=turns)
    print(f"states: {len(states)} (build {time.perf_counter()-t0:.1f}s)")

    rows: List[Dict[str, Any]] = []
    for si, model in enumerate(states):
        cands = generate_wide_candidates(
            model, bc_eval, target=args.candidates,
            seed=1000 + si, max_first=min(12, args.candidates))
        top = bc_eval.top_action(model)
        bc_sig = None if top is None else top[0].signature()
        base_seed = 7000 + si * 101
        stats = []
        for ci, macro in enumerate(cands):
            dup = model.clone()
            try:
                ok = dup.apply_macro(macro)
            except Exception:  # noqa: BLE001
                ok = False
            ranks: List[int] = []
            if ok:
                for r in range(int(args.rollouts)):
                    out = rollout_to_terminal(
                        dup, policy="epsilon", epsilon=args.epsilon,
                        max_horizon_turns=0, seed=base_seed + r, backend="env")
                    ranks.append(int(out["rank"]))
            mean = float(np.mean(ranks)) if ranks else 8.0
            std = float(np.std(ranks)) if len(ranks) > 1 else 0.0
            stats.append({
                "index": ci,
                "source": getattr(macro, "source", "?"),
                "first": list(macro.first.signature()),
                "is_bc_first": bool(bc_sig is not None
                                    and macro.first.signature() == bc_sig),
                "n_steps": len(macro.steps),
                "ranks": ranks,
                "mean_rank": round(mean, 3),
                "std_rank": round(std, 3),
                "top4_rate": round(float(np.mean([x <= 4 for x in ranks])), 3)
                if ranks else 0.0,
            })
        means = [s["mean_rank"] for s in stats]
        noise = [s["std_rank"] / max(1.0, (args.rollouts ** 0.5))
                 for s in stats]
        max_min = max(means) - min(means) if means else 0.0
        max_noise = max(noise) if noise else 0.0
        best = min(stats, key=lambda s: s["mean_rank"]) if stats else None
        bc_cands = [s for s in stats if s["is_bc_first"]]
        bc_stat = bc_cands[0] if bc_cands else None
        lift = (bc_stat["mean_rank"] - best["mean_rank"]
                if bc_stat is not None and best is not None else None)
        paired = None
        if bc_stat is not None and best is not None:
            diffs = [float(b - c) for b, c in zip(bc_stat["ranks"],
                                                  best["ranks"])]
            mean, lo, hi = _bootstrap_ci(diffs)
            paired = {"mean": mean, "ci95": [lo, hi],
                      "significant_lift": bool(mean > 1.0 and lo > 0.0)}
        row = {
            "state": si,
            "turn": model.turn,
            "rank": model.rank(),
            "n_candidates": len(stats),
            "bc_first_found": bool(bc_stat is not None),
            "bc_first_mean_rank": (bc_stat["mean_rank"] if bc_stat else None),
            "best_mean_rank": (best["mean_rank"] if best else None),
            "best_source": (best["source"] if best else None),
            "max_min_mean_diff": round(max_min, 3),
            "max_noise_std_sqrtR": round(max_noise, 3),
            "signal_gt_noise": bool(max_min > max_noise and max_min > 0.5),
            "bc_first_lift": (None if lift is None else round(lift, 3)),
            "paired_bc_vs_best": paired,
            "candidates": stats,
        }
        rows.append(row)
        print(f"state {si} turn={model.turn} cands={len(stats)} "
              f"max-min={max_min:.2f} noise={max_noise:.2f} "
              f"lift={lift if lift is None else round(lift, 2)} "
              f"sig={row['signal_gt_noise']}")

    n = len(rows)
    n_sig = sum(1 for r in rows if r["signal_gt_noise"])
    n_lift = sum(1 for r in rows if r.get("bc_first_lift") is not None
                 and r["bc_first_lift"] > 1.0)
    n_significant = sum(
        1 for r in rows
        if r.get("paired_bc_vs_best")
        and r["paired_bc_vs_best"]["significant_lift"])
    lifts = [r["bc_first_lift"] for r in rows
             if r.get("bc_first_lift") is not None]
    maxmins = [r["max_min_mean_diff"] for r in rows]
    noises = [r["max_noise_std_sqrtR"] for r in rows]
    conclusion = "signal_usable" if n_significant >= 2 else "no_usable_signal"
    report = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "n_states": n, "rollouts": args.rollouts,
            "candidates_target": args.candidates,
            "epsilon": args.epsilon,
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "note": ("状态级诊断；full-to-end R=5 随机化 epsilon rollout；"
                     "UCB 候选生成含 BC macro；只判断信号是否存在，不训练"),
        },
        "summary": {
            "states_with_signal_gt_noise": n_sig,
            "states_with_lift_gt_1": n_lift,
            "states_significant_lift": n_significant,
            "mean_max_min_diff": float(statistics.fmean(maxmins)) if maxmins else 0.0,
            "mean_max_noise": float(statistics.fmean(noises)) if noises else 0.0,
            "mean_bc_first_lift": float(statistics.fmean(lifts)) if lifts else None,
            "conclusion": conclusion,
        },
        "states": rows,
    }
    out = Path(args.out_dir) / "hard_signal_diag.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    lines = ["# 硬搜索状态级信号诊断", "",
             f"- states={n}；R={args.rollouts}；candidates≈{args.candidates}；"
             f"epsilon={args.epsilon}；elapsed={report['meta']['elapsed_s']}s", "",
             "| state | turn | rank | cands | max-min mean | max noise | "
             "BC-first lift | significant lift |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        paired = r.get("paired_bc_vs_best")
        sig = "—" if not paired else ("YES" if paired["significant_lift"] else "no")
        lift = "—" if r.get("bc_first_lift") is None else f"{r['bc_first_lift']:+.2f}"
        lines.append(
            f"| {r['state']} | {r['turn']} | {r['rank']} | {r['n_candidates']} | "
            f"{r['max_min_mean_diff']:.2f} | {r['max_noise_std_sqrtR']:.2f} | "
            f"{lift} | {sig} |")
    sm = report["summary"]
    lines += ["", "## 结论", "",
              f"- 有候选间信号（max-min > noise）：**{sm['states_with_signal_gt_noise']}/{n}**；",
              f"- BC 首步 lift >1 名：**{sm['states_with_lift_gt_1']}/{n}**；",
              f"- 显著优于 BC 首步（均值>1 且 CI>0）：**{sm['states_significant_lift']}/{n}**；",
              f"- 平均 max-min={sm['mean_max_min_diff']:.2f}，平均 max noise="
              f"{sm['mean_max_noise']:.2f}，平均 BC lift="
              f"{sm['mean_bc_first_lift'] if sm['mean_bc_first_lift'] is not None else 'NA'}。",
              "",
              f"**{('存在可利用信号' if conclusion == 'signal_usable' else '当前 rollout 信号不足以支撑搜索')}**"
              "（状态级诊断；仅方向性，不训练）。"]
    md = Path(args.out_dir) / "hard_signal_diag.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} and {md} ({report['meta']['elapsed_s']}s)")
    print(report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
