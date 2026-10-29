"""value 分 vs pairwise 胜率分的 Spearman 相关（仅用于剪枝质量诊断）。"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel, PolicyEvaluator
from hsbg.search.turn_search import (
    TurnSearchConfig, enumerate_turn_states, pairwise_winrate_matrix,
)


def spearman(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 2:
        return 0.0

    def ranks(v):
        order = np.argsort(v)
        r = np.empty_like(v, dtype=float)
        r[order] = np.arange(len(v), dtype=float)
        # average ties
        for val in np.unique(v):
            idx = np.where(v == val)[0]
            if idx.size > 1:
                r[idx] = r[idx].mean()
        return r

    rx, ry = ranks(x), ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--decisions", type=int, default=12)
    p.add_argument("--states", type=int, default=16)
    p.add_argument("--checkpoint", default="runs/bc/official_320/policy_bc.pt")
    p.add_argument("--out", default="runs/search/turn_search_value_corr.json")
    args = p.parse_args(argv)
    ev = PolicyEvaluator(args.checkpoint)
    cfg = TurnSearchConfig(states_budget=args.states, samples_per_action=1,
                           seed=11)
    xs, ys, per = [], [], []
    teacher = HeuristicPolicy()
    captured = 0
    step = 0
    for game_seed in range(401, 409):
        if captured >= args.decisions:
            break
        env = BattlegroundsEnv(seed=game_seed, opponent="teacher")
        obs = env.reset(seed=game_seed)
        while captured < args.decisions and step < 600:
            if getattr(obs, "phase", "") == "choice":
                obs, *_ = env.step(0)
                step += 1
                continue
            try:
                m = EngineForwardModel.from_env(env, clone=False)
            except Exception:  # noqa: BLE001
                break
            by = enumerate_turn_states(m, cfg)
            flat = [st for sts in by.values() for st in sts]
            if len(flat) >= 4:
                vb = ev.value_batch([st.model for st in flat])
                v = (np.asarray(vb["value"], dtype=float) + 1.0) / 2.0
                mat, _ = pairwise_winrate_matrix(flat, m, seed=11, samples=1)
                pw = np.array([float(np.sum(mat[i])) / max(1, len(flat) - 1)
                               for i in range(len(flat))])
                rho = spearman(v, pw)
                xs.extend(v.tolist())
                ys.extend(pw.tolist())
                per.append({"seed": game_seed, "turn": int(m.turn),
                            "n_states": len(flat),
                            "spearman": round(rho, 4)})
                captured += 1
            try:
                d = teacher.choose(env.game, env._agent)
                sig = None if d is None else d.to_candidate().signature()
                idx = next((i for i, c in enumerate(obs.candidates)
                            if c.signature() == sig), 0)
            except Exception:  # noqa: BLE001
                idx = 0
            obs, *_ = env.step(idx)
            step += 1
        env.close()
    rho_all = spearman(xs, ys)
    out = {"n_states": len(xs), "spearman": round(rho_all, 4),
           "per_decision": per,
           "note": "value 与 pairwise 状态分相关；仅用于评估 value 剪枝质量，"
                   "最终选择必须 pairwise"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n_states", "spearman")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
