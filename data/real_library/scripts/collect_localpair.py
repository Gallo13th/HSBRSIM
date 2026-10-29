"""B 路线采集：本地 turn-search 枚举状态 + pairwise 得分 sidecar。

每局每回合最多取 1 个决策；记录每个枚举 state 的 obs/board/score，
以及该决策的 pairwise 矩阵。多进程各自从 seed 独立跑，不传 engine/快照。

输出：
  runs/value_data/turn_search_localpair.pkl（samples/obs + labels + matrices）
  runs/value_data/turn_search_localpair.npz（indices/scores/turn/tier/episode）
  runs/value_data/turn_search_localpair.json（统计）
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pickle
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.search import EngineForwardModel
from hsbg.search.turn_search import TurnSearch, TurnSearchConfig


def _rank(env, info) -> int:
    r = info.get("rank") if isinstance(info, dict) else None
    if isinstance(r, int) and 1 <= r <= 8:
        return r
    agents = [h for h in env.game.heroes if bool(getattr(h, "is_alive", False))]
    if bool(getattr(env.game, "finished", False)):
        return 1
    if not bool(getattr(env._agent, "is_alive", False)):
        return max(1, len(agents) + 1)
    return max(1, len(agents))


def collect_worker(job: Tuple[int, int, int, int, str]) -> str:
    wid, episodes, seed_start, states_budget, out_dir = job
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    shard = out / f"localpair.part{wid}.pkl"
    samples: List[Tuple[Any, int]] = []
    scores: List[float] = []
    turns: List[int] = []
    tiers: List[int] = []
    episode_ids: List[int] = []
    ranks: List[int] = []
    decisions: List[int] = []
    matrices: List[List[List[float]]] = []
    selected: List[bool] = []
    t0 = time.perf_counter()
    for ep in range(max(1, episodes)):
        seed = int(seed_start) + wid * 10007 + ep
        opponent = "heuristic" if (wid + ep) % 2 == 0 else "teacher"
        env = BattlegroundsEnv(num_players=8, opponent=opponent, seed=seed)
        obs = env.reset(seed=seed)
        ts = TurnSearch(TurnSearchConfig(
            states_budget=int(states_budget), samples_per_action=1,
            combat_samples=1, completion_policy="heuristic",
            seed=seed * 31 + 7, record_trace=True), evaluator=None)
        last_turn = -1
        dec_no = 0
        done = False
        final_info: Dict[str, Any] = {}
        while not done:
            if getattr(obs, "phase", "") == "choice":
                obs, _, term, trunc, final_info = env.step(0)
                done = bool(term or trunc)
                continue
            try:
                model = EngineForwardModel.from_env(env, clone=False)
            except Exception:  # noqa: BLE001
                break
            res = ts.decide(model)
            if res.action is None or res.turn != int(obs.turn):
                idx = 0
            else:
                trace = res.trace or {}
                took = False
                if trace and int(res.turn) != last_turn:
                    last_turn = int(res.turn)
                    for st in trace.get("states", []):
                        ob = st.get("obs")
                        if ob is None:
                            continue
                        samples.append((ob, 0))
                        scores.append(float(st.get("score", 0.5)))
                        turns.append(int(st.get("turn", res.turn)))
                        tiers.append(int(st.get("tier", 0)))
                        episode_ids.append(seed)
                        ranks.append(-1)  # 终局回填
                        decisions.append(dec_no)
                        matrices.append(trace.get("matrix") or [])
                        selected.append(True)
                        took = True
                idx = next((i for i, c in enumerate(obs.candidates)
                            if c.signature() == res.action.signature()), 0)
            if took if 'took' in locals() else False:
                pass
            obs, _, term, trunc, final_info = env.step(idx)
            dec_no += 1
            done = bool(term or trunc)
        rank = _rank(env, final_info)
        # 本局样本回填 rank
        for i in range(len(samples) - 1, -1, -1):
            if episode_ids[i] == seed:
                ranks[i] = int(rank)
            else:
                break
        env.close()
        if (ep + 1) % 5 == 0:
            print(f"[worker {wid}] ep {ep+1}/{episodes}, states={len(samples)}, "
                  f"{(time.perf_counter()-t0):.1f}s", flush=True)
    with open(shard, "wb") as f:
        pickle.dump({"samples": samples, "scores": scores, "turns": turns,
                     "tiers": tiers, "episode_ids": episode_ids,
                     "ranks": ranks, "decisions": decisions,
                     "matrices": matrices,
                     "meta": {"worker": wid, "episodes": episodes,
                              "states_budget": states_budget,
                              "wall_s": round(time.perf_counter() - t0, 1)}},
                    f, protocol=pickle.HIGHEST_PROTOCOL)
    return str(shard)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="collect local pairwise sidecar")
    p.add_argument("--episodes", type=int, default=80)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--states-budget", type=int, default=8)
    p.add_argument("--seed-start", type=int, default=20000)
    p.add_argument("--out-dir", default="runs/value_data/localpair_shards")
    p.add_argument("--out", default="runs/value_data/turn_search_localpair.pkl")
    args = p.parse_args(argv)

    t0 = time.perf_counter()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    per = max(1, args.episodes // max(1, args.workers))
    jobs = [(w, per, args.seed_start, args.states_budget, str(out_dir))
            for w in range(args.workers)]
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=args.workers) as pool:
        shards = pool.map(collect_worker, jobs)
    samples, scores, turns, tiers, eps, ranks, decisions, matrices = ([] for _ in range(8))
    for sh in shards:
        with open(sh, "rb") as f:
            d = pickle.load(f)
        samples.extend(d["samples"])
        scores.extend(d["scores"])
        turns.extend(d["turns"])
        tiers.extend(d["tiers"])
        eps.extend(d["episode_ids"])
        ranks.extend(d["ranks"])
        decisions.extend(d["decisions"])
        matrices.extend(d["matrices"])
    data = {"samples": samples, "scores": scores, "turns": turns,
            "tiers": tiers, "episode_ids": eps, "ranks": ranks,
            "decisions": decisions, "matrices": matrices,
            "meta": {"episodes": len(set(eps)), "states": len(samples),
                     "states_budget": args.states_budget,
                     "workers": args.workers, "wall_s": round(time.perf_counter() - t0, 1)}}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    np.savez_compressed(
        str(Path(args.out).with_suffix(".npz")),
        scores=np.asarray(scores, dtype=np.float32),
        turn=np.asarray(turns, dtype=np.int16),
        tier=np.asarray(tiers, dtype=np.int16),
        episode_id=np.asarray(eps, dtype=np.int64),
        rank=np.asarray(ranks, dtype=np.int16),
        decision=np.asarray(decisions, dtype=np.int32))
    meta = dict(data["meta"], elapsed_s=round(time.perf_counter() - t0, 1),
                paths={"pkl": args.out,
                       "npz": str(Path(args.out).with_suffix(".npz"))})
    Path(args.out).with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
