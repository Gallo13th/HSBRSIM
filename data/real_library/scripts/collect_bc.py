#!/usr/bin/env python
"""收集行为克隆（BC）示范数据：用引擎级启发式教师打完整对局。

与 `scripts/train_bc.py` 的区别：这里的教师是 `hsbg.agents.heuristic.HeuristicPolicy`
（引擎感知、强度更高），逐动作记录 ``(Observation, 候选下标)`` 到
``BCDataset``（可直接被 ``hsbg.train.bc.BCTrainer.fit`` 消费），并对局结束时
回填终局名次（用于可选价值监督）。

用法::

    python scripts/collect_bc.py --episodes 200 --out runs/bc_data/heuristic_200.pkl
    python scripts/collect_bc.py --episodes 200 --workers 6 --out ...   # 多进程
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.env.spec import ActionKind, CandidateAction  # noqa: E402


def _find_index(obs, target: CandidateAction) -> int:
    sig = target.signature()
    for i, c in enumerate(obs.candidates):
        if c.signature() == sig:
            return i
    return -1


def _end_turn_index(obs) -> int:
    for i, c in enumerate(obs.candidates):
        if c.kind == ActionKind.END_TURN.value:
            return i
    return 0


def play_episode(env, teacher, seed: int) -> Tuple[List, int, int]:
    """跑一局，返回 ``(samples[(obs, idx)], rank, steps)``。

    防御：
    * 教师动作可能不在环境候选集（环境枚举比教师更保守）→ 不计样本，
      若环境拒绝该动作则强制 end_turn，避免死循环；
    * 单局步数硬上限（env.max_steps + 200），超限按 truncate 收尾。
    """
    obs = env.reset(seed=seed)
    samples: List = []
    steps = 0
    info: dict = {}
    max_steps = int(getattr(env.config, "max_steps", 4000)) + 200
    while True:
        steps += 1
        if not obs.candidates:
            # 无候选（已终局/异常态）→ 收尾
            return samples, int(info.get("rank", 0) or 0), steps
        if obs.phase == "choice":
            opt = teacher.choose_option_index(obs)
            action = CandidateAction(kind=ActionKind.CHOOSE.value, option=opt)
        else:
            desc = teacher.choose(env.game, env.agent_hero)
            action = (CandidateAction(kind=ActionKind.END_TURN.value)
                      if desc is None else desc.to_candidate())
        idx = _find_index(obs, action)
        if idx >= 0:
            samples.append((obs, idx))
        else:
            # 教师越界动作：不记录，改为 end_turn 推进回合
            action = obs.candidates[_end_turn_index(obs)]
            idx = _find_index(obs, action)
            if idx >= 0:
                samples.append((obs, idx))
        obs, _reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            rank = int(info.get("rank", 0) or 0)
            return samples, rank, steps
        if info.get("invalid") or info.get("wrong_action"):
            # 环境拒绝且状态未推进：强制 end_turn（若仍非法则退出）
            fallback = obs.candidates[_end_turn_index(obs)]
            if fallback.signature() == action.signature():
                return samples, 0, steps
            obs, _reward, terminated, truncated, info = env.step(fallback)
            if terminated or truncated:
                rank = int(info.get("rank", 0) or 0)
                return samples, rank, steps
        if steps >= max_steps:
            return samples, 0, steps


@dataclass
class _WorkerResult:
    samples: List
    ranks: List[int]
    episodes: int
    steps: int
    seed: int


def _worker(args) -> _WorkerResult:
    """多进程 worker（模块级函数，Windows spawn 安全）。"""
    from hsbg.agents.heuristic import HeuristicPolicy
    from hsbg.env import BattlegroundsEnv

    episodes, base_seed, num_players, opponent, max_turns = args
    env = BattlegroundsEnv(num_players=num_players, opponent=opponent,
                           seed=base_seed, max_turns=max_turns)
    teacher = HeuristicPolicy()
    samples: List = []
    ranks: List[int] = []
    steps_total = 0
    for i in range(episodes):
        s, rank, steps = play_episode(env, teacher, base_seed + i)
        samples.extend((o, a, rank, base_seed + i) for o, a in s)
        ranks.append(rank)
        steps_total += steps
    env.close()
    return _WorkerResult(samples, ranks, episodes, steps_total, base_seed)


def collect_sequential(episodes: int, base_seed: int, num_players: int,
                       opponent: str, max_turns: int) -> _WorkerResult:
    from hsbg.agents.heuristic import HeuristicPolicy
    from hsbg.env import BattlegroundsEnv

    env = BattlegroundsEnv(num_players=num_players, opponent=opponent,
                           seed=base_seed, max_turns=max_turns)
    teacher = HeuristicPolicy()
    samples: List = []
    ranks: List[int] = []
    steps_total = 0
    for i in range(episodes):
        s, rank, steps = play_episode(env, teacher, base_seed + i)
        samples.extend((o, a, rank, base_seed + i) for o, a in s)
        ranks.append(rank)
        steps_total += steps
        if (i + 1) % 20 == 0:
            print(f"  [{i + 1}/{episodes}] rank_mean="
                  f"{sum(ranks) / len(ranks):.2f} samples={len(samples)}",
                  flush=True)
    env.close()
    return _WorkerResult(samples, ranks, episodes, steps_total, base_seed)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="收集引擎启发式教师的 BC 数据")
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--workers", type=int, default=1,
                    help="并行进程数（>1 时用 multiprocessing spawn）")
    ap.add_argument("--seed", type=int, default=10_000)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--opponent", type=str, default="heuristic")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    workers = max(1, min(args.workers, args.episodes))
    if workers == 1:
        result = collect_sequential(args.episodes, args.seed, args.players,
                                    args.opponent, args.max_turns)
        results = [result]
    else:
        import multiprocessing as mp
        per = args.episodes // workers
        rem = args.episodes - per * workers
        jobs = []
        for w in range(workers):
            n = per + (1 if w < rem else 0)
            if n:
                jobs.append((n, args.seed + w * 100_000,
                             args.players, args.opponent, args.max_turns))
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=len(jobs)) as pool:
            results = pool.map(_worker, jobs)

    # 合并成 BCDataset
    from hsbg.train.bc import BCDataset
    ds = BCDataset(meta={
        "teacher": "hsbg.agents.heuristic.HeuristicPolicy",
        "episodes": sum(r.episodes for r in results),
        "players": args.players,
        "opponent": args.opponent,
        "seed": args.seed,
        "script": "scripts/collect_bc.py",
    })
    for r in results:
        for obs, action, rank, ep in r.samples:
            ds.add(obs, action, rank=rank, episode_id=ep)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.save(out)

    all_ranks = [r for res in results for r in res.ranks]
    elapsed = time.perf_counter() - t0
    print(f"[collect_bc] episodes={len(all_ranks)} samples={len(ds)} "
          f"mean_rank={sum(all_ranks) / max(1, len(all_ranks)):.3f} "
          f"win={sum(1 for r in all_ranks if r == 1) / max(1, len(all_ranks)):.1%}")
    print(f"[collect_bc] wall={elapsed:.1f}s "
          f"({len(all_ranks) / max(elapsed, 1e-6):.1f} games/s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
