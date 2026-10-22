"""策略评测（多进程、固定种子、置信区间、名次分布）。

复用 ``hsbg.eval.metrics`` 的指标实现（:class:`hsbg.eval.metrics.EvalResult`、
bootstrap CI、名次分布），在 RL 接口层补上：

* **固定种子集**：第 ``k`` 局种子 = ``seed + k``（或显式 ``seeds=[...]``），
  与 worker 划分无关 ⇒ 同 seed 同 worker 数或不同 worker 数结果一致；
* **多进程**：spawn-safe 的模块级 worker，每个 worker 独立 env；
* **吞吐统计**：games/s、steps/s；
* **异常/无效动作/truncated 计数**。

命令行::

    python -m hsbg.rl.evaluate --policy random --episodes 20
    python -m hsbg.rl.evaluate --policy heuristic --policy random --episodes 20 --workers 2
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from hsbg.eval.metrics import EvalResult, format_summary
from hsbg.rl.api import run_episode
from hsbg.rl.envs import BACKENDS, make_env, real_env_available
from hsbg.rl.policies import (
    describe_policy,
    ensure_picklable,
    make_policy,
    policy_requires_engine,
)


# ══════════════════════════════════════════════════════════════════════
# 结果
# ══════════════════════════════════════════════════════════════════════


@dataclass
class EvalSummary:
    """一次评测的聚合结果（内嵌 ``hsbg.eval.metrics.EvalResult``）。"""

    name: str = "policy"
    policy: str = "policy"
    num_players: int = 8
    result: EvalResult = field(default_factory=EvalResult)
    wall_seconds: float = 0.0
    workers: int = 1
    backend: str = "auto"
    episode_seeds: List[int] = field(default_factory=list)
    errors: int = 0
    #: 评测配置（写 JSON 便于回归对比：seed/episodes/opponent/...）
    config: Dict[str, Any] = field(default_factory=dict)

    # ── 指标 ──
    @property
    def games_per_second(self) -> float:
        n = len(self.result.ranks)
        if n <= 0 or self.wall_seconds <= 0:
            return 0.0
        return n / self.wall_seconds

    @property
    def steps_per_second(self) -> float:
        steps = sum(self.result.steps)
        if steps <= 0 or self.wall_seconds <= 0:
            return 0.0
        return steps / self.wall_seconds

    def summary(self) -> Dict[str, float]:
        base = dict(self.result.summary())
        base.update({
            "games_per_second": self.games_per_second,
            "steps_per_second": self.steps_per_second,
            "wall_seconds": self.wall_seconds,
            "workers": float(self.workers),
            "errors": float(self.errors),
        })
        return base

    def rank_distribution(self) -> Dict[int, float]:
        return self.result.rank_distribution()

    def detailed(self) -> Dict[str, Any]:
        """更细的统计（含按名次的平均 reward/步数、重复种子检查用）。"""
        ranks = self.result.ranks
        by_rank: Dict[str, Dict[str, float]] = {}
        for rank in range(1, self.num_players + 1):
            idx = [i for i, r in enumerate(ranks) if r == rank]
            if not idx:
                continue
            by_rank[str(rank)] = {
                "count": float(len(idx)),
                "mean_reward": float(statistics.fmean(
                    self.result.rewards[i] for i in idx)),
                "mean_steps": float(statistics.fmean(
                    self.result.steps[i] for i in idx)),
            }
        return {
            "by_rank": by_rank,
            "reasons": dict(_counter(self.result.reasons)),
            "seeds": list(self.episode_seeds),
        }

    def episodes(self) -> List[Dict[str, Any]]:
        """逐局明细（rank/reward/steps/turns/reason，按 episode 顺序）。"""
        rows: List[Dict[str, Any]] = []
        n = len(self.result.ranks)
        for i in range(n):
            rows.append({
                "episode_id": i,
                "seed": (self.episode_seeds[i]
                         if i < len(self.episode_seeds) else -1),
                "rank": int(self.result.ranks[i]),
                "reward": float(self.result.rewards[i]),
                "turns": int(self.result.turns[i]),
                "steps": int(self.result.steps[i]),
                "reason": (self.result.reasons[i]
                           if i < len(self.result.reasons) else ""),
            })
        return rows

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "policy": self.policy,
            "num_players": self.num_players,
            "backend": self.backend,
            "workers": self.workers,
            "wall_seconds": round(self.wall_seconds, 3),
            "games_per_second": round(self.games_per_second, 3),
            "steps_per_second": round(self.steps_per_second, 2),
            "config": dict(self.config),
            "summary": self.summary(),
            "rank_distribution": {str(k): v for k, v in self.rank_distribution().items()},
            "ranks": list(self.result.ranks),
            "rewards": list(self.result.rewards),
            "turns": list(self.result.turns),
            "steps": list(self.result.steps),
            "reasons": list(self.result.reasons),
            "episode_seeds": list(self.episode_seeds),
            "episodes": self.episodes(),
            "errors": self.errors,
            "detailed": self.detailed(),
        }

    def format(self) -> str:
        body = format_summary(self.result, self.name)
        return (
            f"{body}\n"
            f"wall={self.wall_seconds:.2f}s  games/s={self.games_per_second:.2f}  "
            f"steps/s={self.steps_per_second:.0f}  workers={self.workers}  "
            f"errors={self.errors}"
        )

    def save(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path


def _counter(values: Sequence[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return out


# ══════════════════════════════════════════════════════════════════════
# 多进程 worker（spawn-safe 模块级函数）
# ══════════════════════════════════════════════════════════════════════


def _evaluate_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    """在一个 worker 内跑指定 seed 列表并返回每局摘要行。"""
    policy = make_policy(payload["policy_spec"], seed=0,
                         device=payload.get("device", "cpu"))
    env = make_env(
        backend=payload.get("backend", "auto"),
        num_players=int(payload.get("num_players", 8)),
        opponent=payload.get("opponent", "heuristic"),
        env_kwargs=payload.get("env_kwargs"),
        mock_kwargs=payload.get("mock_kwargs"),
    )
    rows: List[Dict[str, Any]] = []
    errors = 0
    max_steps = int(payload.get("max_steps_per_episode", 2000))
    deterministic = bool(payload.get("deterministic", False))
    t0 = time.perf_counter()
    try:
        for episode_id, ep_seed in payload["episodes"]:
            try:
                record = run_episode(
                    env, policy,
                    seed=int(ep_seed),
                    episode_id=int(episode_id),
                    max_steps=max_steps,
                    deterministic=deterministic,
                    rng=random.Random(int(ep_seed)),
                    collect_transitions=False,
                    include_next_obs=False,
                )
                rows.append({
                    "episode_id": int(episode_id),
                    "seed": int(ep_seed),
                    "rank": int(record.rank),
                    "reward": float(record.total_reward),
                    "turns": int(record.turns),
                    "steps": int(record.steps),
                    "invalid": int(record.invalid_actions),
                    "truncated": bool(record.truncated),
                    "terminated": bool(record.terminated),
                    "reason": str(record.reason),
                })
            except Exception as exc:  # noqa: BLE001 - 单局失败不拖垮整批评测
                errors += 1
                rows.append({
                    "episode_id": int(episode_id),
                    "seed": int(ep_seed),
                    "rank": 0,
                    "reward": 0.0,
                    "turns": 0,
                    "steps": 0,
                    "invalid": 0,
                    "truncated": False,
                    "terminated": False,
                    "reason": f"error:{type(exc).__name__}",
                    "error": str(exc),
                })
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()
    return {"rows": rows, "errors": errors,
            "wall_seconds": time.perf_counter() - t0}


def _run_payloads(payloads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not payloads:
        return []
    if len(payloads) == 1:
        return [_evaluate_worker(payloads[0])]
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=len(payloads)) as pool:
        return pool.map(_evaluate_worker, payloads)


def _resolve_seeds(episodes: int, seed: int,
                   seeds: Optional[Sequence[int]]) -> List[Tuple[int, int]]:
    if seeds:
        return [(k, int(s)) for k, s in enumerate(seeds)]
    if episodes < 0:
        raise ValueError("episodes 必须 >= 0")
    return [(k, int(seed) + k) for k in range(int(episodes))]


def _split(tasks: Sequence[Tuple[int, int]], workers: int) -> List[List[Tuple[int, int]]]:
    workers = max(1, int(workers))
    chunks: List[List[Tuple[int, int]]] = [[] for _ in range(workers)]
    for i, task in enumerate(tasks):
        chunks[i % workers].append(task)
    return [chunk for chunk in chunks if chunk]


def _check_policy_backend(policy: Any, backend: str) -> None:
    """引擎感知策略（teacher）需要真实环境：mock/回退场景提前明确报错。"""
    if not policy_requires_engine(policy):
        return
    backend_name = str(backend or "auto").lower()
    if backend_name == "mock":
        raise ValueError(
            "teacher 策略需要真实环境（env.game/env.agent_hero），"
            "backend='mock' 不支持。请用 backend='real'/'auto'，"
            "或改用 heuristic/random（观测级可移植策略）。"
        )
    if backend_name == "auto" and not real_env_available():
        raise ValueError(
            "teacher 策略需要真实环境，但当前真实环境不可用（hsbg.env 导入失败）。"
        )


# ══════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════


def evaluate(
    policy: Any = "heuristic",
    *,
    episodes: int = 20,
    seed: int = 0,
    workers: int = 1,
    seeds: Optional[Sequence[int]] = None,
    num_players: int = 8,
    opponent: str = "heuristic",
    backend: str = "auto",
    env_kwargs: Optional[Dict[str, Any]] = None,
    mock_kwargs: Optional[Dict[str, Any]] = None,
    max_steps_per_episode: int = 2000,
    deterministic: bool = False,
    device: str = "cpu",
    name: Optional[str] = None,
    verbose: bool = False,
) -> EvalSummary:
    """在固定种子集上评测一个策略（多进程可选）。"""
    _check_policy_backend(policy, backend)
    tasks = _resolve_seeds(int(episodes), int(seed), seeds)
    workers = max(1, int(workers))
    t0 = time.perf_counter()
    rows: List[Dict[str, Any]] = []
    errors = 0
    if tasks:
        worker_count = min(workers, len(tasks))
        if worker_count > 1:
            if not isinstance(policy, str):
                ensure_picklable(policy, what="policy")
        chunks = _split(tasks, worker_count)
        payloads = []
        for worker_id, chunk in enumerate(chunks):
            payloads.append({
                "worker_id": worker_id,
                "policy_spec": policy,
                "policy_seed": int(seed),
                "episodes": list(chunk),
                "backend": str(backend),
                "num_players": int(num_players),
                "opponent": str(opponent),
                "env_kwargs": env_kwargs,
                "mock_kwargs": mock_kwargs,
                "max_steps_per_episode": int(max_steps_per_episode),
                "deterministic": bool(deterministic),
                "device": str(device),
            })
        if verbose:
            print(f"[evaluate] policy={describe_policy(policy)} episodes={len(tasks)} "
                  f"workers={len(payloads)}")
        for result in _run_payloads(payloads):
            rows.extend(result["rows"])
            errors += int(result["errors"])
    wall_seconds = time.perf_counter() - t0
    rows.sort(key=lambda row: int(row["episode_id"]))
    result = EvalResult(num_players=int(num_players))
    for row in rows:
        result.add(
            rank=int(row["rank"]),
            reward=float(row["reward"]),
            turns=int(row["turns"]),
            steps=int(row["steps"]),
            invalid=int(row["invalid"]),
            truncated=bool(row["truncated"]),
            reason=str(row["reason"]),
        )
    return EvalSummary(
        name=name or describe_policy(policy),
        policy=describe_policy(policy),
        num_players=int(num_players),
        result=result,
        wall_seconds=wall_seconds,
        workers=workers,
        backend=str(backend),
        episode_seeds=[int(row["seed"]) for row in rows],
        errors=int(errors),
        config={
            "policy": describe_policy(policy),
            "episodes": int(len(tasks)),
            "episodes_requested": int(episodes),
            "seed": int(seed),
            "seeds": ([int(s) for s in seeds] if seeds else None),
            "workers": int(workers),
            "num_players": int(num_players),
            "opponent": str(opponent),
            "backend": str(backend),
            "max_steps_per_episode": int(max_steps_per_episode),
            "deterministic": bool(deterministic),
            "device": str(device),
        },
    )


def evaluate_many(
    policies: Sequence[Any],
    *,
    episodes: int = 20,
    seed: int = 0,
    workers: int = 1,
    seeds: Optional[Sequence[int]] = None,
    **kwargs: Any,
) -> List[EvalSummary]:
    """依次评测多个策略（同一固定种子集，便于对照）。"""
    out: List[EvalSummary] = []
    for policy in policies:
        out.append(evaluate(
            policy, episodes=episodes, seed=seed, workers=workers,
            seeds=seeds, **kwargs,
        ))
    return out


def comparison_table(summaries: Sequence[EvalSummary]) -> str:
    """多策略对照表（等宽文本）。"""
    columns = ["policy", "episodes", "mean_rank", "ci_low", "ci_high",
               "win_rate", "top4_rate", "mean_steps", "games/s"]
    rows: List[List[str]] = []
    for summary in summaries:
        s = summary.summary()
        rows.append([
            summary.name,
            f"{int(s['episodes'])}",
            f"{s['mean_rank']:.3f}",
            f"{s['mean_rank_ci_low']:.2f}",
            f"{s['mean_rank_ci_high']:.2f}",
            f"{s['win_rate']:.1%}",
            f"{s['top_half_rate']:.1%}",
            f"{s['mean_steps']:.0f}",
            f"{summary.games_per_second:.2f}",
        ])
    widths = [
        max(len(columns[i]), max((len(row[i]) for row in rows), default=0))
        for i in range(len(columns))
    ]
    lines = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(columns)),
             "  ".join("-" * w for w in widths)]
    for row in rows:
        lines.append("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m hsbg.rl.evaluate",
        description="评测策略（固定种子、bootstrap CI、名次分布、多进程）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--policy", action="append", default=None,
                   help="策略（可重复）：heuristic/teacher/random/first/end_turn/checkpoint 路径/callable")
    p.add_argument("--episodes", type=int, default=20)
    p.add_argument("--seed", type=int, default=0, help="第 k 局种子 = seed + k")
    p.add_argument("--seeds", default=None,
                   help="显式种子列表（逗号分隔，覆盖 --episodes/--seed）")
    p.add_argument("--workers", type=int, default=1, help="并行 worker 数")
    p.add_argument("--num-players", type=int, default=8)
    p.add_argument("--opponent", default="heuristic")
    p.add_argument("--backend", default="auto", choices=list(BACKENDS))
    p.add_argument("--max-steps-per-episode", type=int, default=2000)
    p.add_argument("--deterministic", action="store_true",
                   help="策略尽量贪心（默认关闭：随机策略保持采样）")
    p.add_argument("--device", default="cpu")
    p.add_argument("--out", default=None, help="结果 JSON 输出路径")
    p.add_argument("--json", action="store_true", help="以 JSON 打印结果")
    p.add_argument("--quiet", action="store_true")
    return p


def _payload(summaries: Sequence[EvalSummary]) -> Dict[str, Any]:
    """CLI ``--out`` 的 JSON 结构（指标 + 配置 + per-episode rank）。"""
    config = dict(summaries[0].config) if summaries else {}
    config["policies"] = [summary.policy for summary in summaries]
    return {
        "schema": "hsbg.rl.evaluate/v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": config,
        "results": [summary.to_dict() for summary in summaries],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    policies = args.policy or ["heuristic"]
    seeds: Optional[List[int]] = None
    if args.seeds:
        seeds = [int(x) for x in str(args.seeds).split(",") if x.strip()]
    try:
        summaries = evaluate_many(
            policies,
            episodes=args.episodes,
            seed=args.seed,
            workers=args.workers,
            seeds=seeds,
            num_players=args.num_players,
            opponent=args.opponent,
            backend=args.backend,
            max_steps_per_episode=args.max_steps_per_episode,
            deterministic=args.deterministic,
            device=args.device,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"[hsbg.rl.evaluate] 错误: {exc}", file=sys.stderr)
        return 2
    payload = _payload(summaries)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not args.quiet:
        for summary in summaries:
            print(summary.format())
            print()
        if len(summaries) > 1:
            print("== comparison ==")
            print(comparison_table(summaries))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not args.quiet and not args.json:
            print(f"\nresults -> {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    raise SystemExit(main())


__all__ = [
    "EvalSummary",
    "evaluate",
    "evaluate_many",
    "comparison_table",
    "build_arg_parser",
    "main",
]
