"""高并发轨迹采集（多进程 + JSONL + 断点续采）。

用法
----
命令行（``--envs`` = 并行 worker 数）::

    python -m hsbg.rl.collector --policy heuristic --envs 4 --episodes 100 \
        --out runs/rl/heuristic_100.jsonl

    python -m hsbg.rl.collector --policy random --envs 2 --episodes 10 --backend mock

Python API::

    from hsbg.rl.collector import collect_trajectories, collect_rollouts
    stats = collect_trajectories("heuristic", num_envs=4, episodes=100,
                                 seed=0, out_path="runs/rl/heuristic_100.jsonl")
    records, stats = collect_rollouts("random", num_envs=2, episodes=16, seed=0)

设计
----
* **确定性**：第 ``k`` 局的种子固定为 ``seed + k``（与 worker 划分无关），
  策略随机源为 ``random.Random(seed + k)``；同一 seed 两次采集的 episode
  集合与动作序列完全一致（worker 数只影响速度/顺序）。
* **多进程**：Windows 必须 ``spawn``；worker 是模块级函数。policy 为字符串
  （worker 内重建）或可 pickle 的模块级对象/函数；否则需 ``num_envs=1``。
* **JSONL**：每个 worker 先写自己的 shard 文件，结束后主进程按
  ``episode_id`` 排序合并为最终文件（含 header）；崩溃时 shard 里已有数据。
* **断点续采**：``resume=True`` 时扫描已有文件里**完整的** episode（按 seed
  去重），只补采缺失的 episode；合并时按 ``(episode_id, step)`` 去重，
  保证可重复执行且不产生重复数据。
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from hsbg.rl.api import (
    SCHEMA_VERSION,
    EpisodeRecord,
    error_record,
    header_record,
    run_episode,
)
from hsbg.rl.envs import BACKENDS, make_env, real_env_available
from hsbg.rl.policies import (
    describe_policy,
    ensure_picklable,
    make_policy,
    policy_requires_engine,
)

#: 默认输出目录（相对仓库根）
DEFAULT_OUT_DIR = "runs/rl"


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════


@dataclass
class CollectStats:
    """一次采集任务的汇总（吞吐 / 名次分布 / 动作分布）。"""

    episodes: int = 0
    new_episodes: int = 0
    steps: int = 0
    #: 本次运行新采集的步数（断点续采时与 steps 不同）
    new_steps: int = 0
    wall_seconds: float = 0.0
    workers: int = 1
    policy: str = ""
    backend: str = ""
    out_path: str = ""
    mean_rank: float = 0.0
    rank_distribution: Dict[str, float] = field(default_factory=dict)
    action_kinds: Dict[str, int] = field(default_factory=dict)
    invalid_actions: int = 0
    truncated: int = 0
    errors: int = 0
    resumed_skipped: int = 0
    episode_seeds: List[int] = field(default_factory=list)

    @property
    def games_per_second(self) -> float:
        if self.wall_seconds <= 0 or self.new_episodes <= 0:
            return 0.0
        return self.new_episodes / self.wall_seconds

    @property
    def steps_per_second(self) -> float:
        if self.wall_seconds <= 0 or self.new_steps <= 0:
            return 0.0
        return self.new_steps / self.wall_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episodes": self.episodes,
            "new_episodes": self.new_episodes,
            "steps": self.steps,
            "new_steps": self.new_steps,
            "wall_seconds": round(self.wall_seconds, 3),
            "games_per_second": round(self.games_per_second, 3),
            "steps_per_second": round(self.steps_per_second, 2),
            "workers": self.workers,
            "policy": self.policy,
            "backend": self.backend,
            "out_path": self.out_path,
            "mean_rank": round(self.mean_rank, 4),
            "rank_distribution": dict(self.rank_distribution),
            "action_kinds": dict(self.action_kinds),
            "invalid_actions": self.invalid_actions,
            "truncated": self.truncated,
            "errors": self.errors,
            "resumed_skipped": self.resumed_skipped,
        }

    def format(self) -> str:
        lines = [
            "== collect ==",
            f"episodes={self.episodes} (new={self.new_episodes}, "
            f"resumed_skipped={self.resumed_skipped})  "
            f"steps={self.steps} (new={self.new_steps})  "
            f"workers={self.workers}  policy={self.policy}  backend={self.backend}",
            f"wall={self.wall_seconds:.2f}s  games/s={self.games_per_second:.2f}  "
            f"steps/s={self.steps_per_second:.0f}",
            f"mean_rank={self.mean_rank:.3f}  "
            f"truncated={self.truncated}  invalid={self.invalid_actions}  "
            f"errors={self.errors}",
        ]
        if self.rank_distribution:
            lines.append("rank_dist: " + "  ".join(
                f"{k}:{v:.0%}" for k, v in sorted(
                    ((int(k), v) for k, v in self.rank_distribution.items()))))
        if self.action_kinds:
            top = sorted(self.action_kinds.items(), key=lambda kv: -kv[1])[:8]
            lines.append("actions: " + "  ".join(f"{k}:{v}" for k, v in top))
        if self.out_path:
            lines.append(f"out: {self.out_path}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# JSONL 读写 / 合并
# ══════════════════════════════════════════════════════════════════════


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:  # pragma: no cover - 坏行容错
                rows.append({"type": "error", "v": SCHEMA_VERSION,
                             "episode_id": -1, "seed": -1,
                             "error": f"json_decode_error_line_{lineno}"})
    return rows


def read_dataset(path: Union[str, Path]) -> Dict[str, Any]:
    """读取 JSONL 数据集：``{"header", "episodes": {id: {"steps": {n: row}, "episode": row}}, "errors"}``。"""
    rows = _load_jsonl(Path(path))
    header: Optional[Dict[str, Any]] = None
    episodes: Dict[int, Dict[str, Any]] = {}
    errors: List[Dict[str, Any]] = []
    for row in rows:
        kind = row.get("type")
        if kind == "header":
            if header is None:
                header = row
            continue
        if kind == "error":
            errors.append(row)
            continue
        ep_id = int(row.get("episode_id", -1))
        slot = episodes.setdefault(ep_id, {"steps": {}, "episode": None})
        if kind == "step":
            slot["steps"][int(row.get("step", 0))] = row
        elif kind == "episode":
            slot["episode"] = row
    return {"header": header, "episodes": episodes, "errors": errors}


def completed_seeds(path: Union[str, Path]) -> Dict[int, int]:
    """已完整采集的 ``seed -> episode_id`` 映射（断点续采按 seed 去重）。"""
    data = read_dataset(path)
    out: Dict[int, int] = {}
    for ep_id, slot in data["episodes"].items():
        episode = slot.get("episode")
        if episode is not None:
            out[int(episode.get("seed", -1))] = int(ep_id)
    return out


def _merge_dataset(
    final_path: Path,
    shard_paths: Sequence[Path],
    *,
    header: Dict[str, Any],
    extra_errors: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """把所有 shard + 已有的最终文件合并成排序后的单一 JSONL（原子替换）。"""
    merged: Dict[int, Dict[str, Any]] = {}
    errors: List[Dict[str, Any]] = []

    def _absorb(path: Path) -> None:
        data = read_dataset(path)
        errors.extend(data["errors"])
        for ep_id, slot in data["episodes"].items():
            dst = merged.setdefault(ep_id, {"steps": {}, "episode": None})
            for step, row in slot["steps"].items():
                dst["steps"][step] = row
            if slot["episode"] is not None:
                dst["episode"] = slot["episode"]

    # 先吸收已有最终文件（保留其已完成的 episode），再吸收新 shard
    _absorb(final_path)
    for shard in shard_paths:
        _absorb(shard)
    if extra_errors:
        errors.extend(extra_errors)

    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for ep_id in sorted(merged):
            slot = merged[ep_id]
            for step in sorted(slot["steps"]):
                f.write(json.dumps(slot["steps"][step], ensure_ascii=False) + "\n")
            if slot["episode"] is not None:
                f.write(json.dumps(slot["episode"], ensure_ascii=False) + "\n")
        for row in errors:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp_path, final_path)
    return {"episodes": len(merged), "errors": len(errors)}


def _summarize_dataset(path: Path) -> Dict[str, Any]:
    """从最终 JSONL 重新聚合统计（保证 stats 与文件内容一致）。"""
    data = read_dataset(path)
    ranks: List[int] = []
    steps = 0
    invalid = 0
    truncated = 0
    kinds: Dict[str, int] = {}
    seeds: List[int] = []
    for ep_id, slot in data["episodes"].items():
        episode = slot.get("episode")
        if episode is None:
            continue
        ranks.append(int(episode.get("rank", 0) or 0))
        seeds.append(int(episode.get("seed", -1)))
        steps += int(episode.get("steps", len(slot["steps"])))
        invalid += int(episode.get("invalid_actions", 0) or 0)
        truncated += int(bool(episode.get("truncated", False)))
        for row in slot["steps"].values():
            kind = str(row.get("action_kind", ""))
            kinds[kind] = kinds.get(kind, 0) + 1
    num_players = 8
    dist: Dict[str, float] = {}
    if ranks:
        n = len(ranks)
        for r in range(1, num_players + 1):
            dist[str(r)] = sum(1 for x in ranks if x == r) / n
    return {
        "episodes": len(ranks),
        "ranks": ranks,
        "steps": steps,
        "invalid": invalid,
        "truncated": truncated,
        "action_kinds": kinds,
        "seeds": seeds,
        "rank_distribution": dist,
        "mean_rank": statistics.fmean(ranks) if ranks else 0.0,
        "errors": len(data["errors"]),
        "header": data["header"],
    }


# ══════════════════════════════════════════════════════════════════════
# 多进程 worker（模块级：Windows spawn 必须可导入/pickle）
# ══════════════════════════════════════════════════════════════════════


def _worker_policy(spec: Any, seed: int, device: str = "cpu") -> Any:
    return make_policy(spec, seed=seed, device=device)


def _collect_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    """采集指定 episode 列表并写 shard；返回该 worker 的统计。"""
    worker_id = int(payload["worker_id"])
    shard_path = Path(payload["shard_path"])
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    policy = _worker_policy(payload["policy_spec"], payload["policy_seed"],
                            payload.get("device", "cpu"))
    env = make_env(
        backend=payload.get("backend", "auto"),
        num_players=int(payload.get("num_players", 8)),
        opponent=payload.get("opponent", "heuristic"),
        env_kwargs=payload.get("env_kwargs"),
        mock_kwargs=payload.get("mock_kwargs"),
    )
    max_steps = int(payload.get("max_steps_per_episode", 2000))
    per_step = bool(payload.get("per_step", True))
    include_board = bool(payload.get("include_board", True))
    include_extra = bool(payload.get("include_extra", False))
    deterministic = bool(payload.get("deterministic", False))
    stats: Dict[str, Any] = {
        "worker_id": worker_id, "episodes": 0, "steps": 0, "ranks": [],
        "action_kinds": {}, "invalid": 0, "truncated": 0, "errors": 0,
        "wall_seconds": 0.0, "shard": str(shard_path),
    }
    t0 = time.perf_counter()
    try:
        with open(shard_path, "w", encoding="utf-8") as f:
            for episode_id, ep_seed in payload["episodes"]:
                try:
                    record = run_episode(
                        env, policy,
                        seed=int(ep_seed),
                        episode_id=int(episode_id),
                        max_steps=max_steps,
                        deterministic=deterministic,
                        rng=random.Random(int(ep_seed)),
                        collect_transitions=True,
                    )
                    for row in record.to_jsonl_lines(
                            per_step=per_step, include_board=include_board,
                            include_extra=include_extra):
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stats["episodes"] += 1
                    stats["steps"] += int(record.steps)
                    stats["ranks"].append(int(record.rank))
                    for kind, count in record.action_kinds().items():
                        stats["action_kinds"][kind] = (
                            stats["action_kinds"].get(kind, 0) + count)
                    stats["invalid"] += int(record.invalid_actions)
                    stats["truncated"] += int(bool(record.truncated))
                except Exception as exc:  # noqa: BLE001 - 单局失败不拖垮整批
                    stats["errors"] += 1
                    row = error_record(
                        episode_id=int(episode_id), seed=int(ep_seed),
                        error=f"{type(exc).__name__}: {exc}", worker=worker_id,
                    )
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()
        stats["wall_seconds"] = time.perf_counter() - t0
    return stats


def _rollout_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    """采集指定 episode 列表并**返回内存中的 EpisodeRecord**（不写文件）。"""
    policy = _worker_policy(payload["policy_spec"], payload["policy_seed"],
                            payload.get("device", "cpu"))
    env = make_env(
        backend=payload.get("backend", "auto"),
        num_players=int(payload.get("num_players", 8)),
        opponent=payload.get("opponent", "heuristic"),
        env_kwargs=payload.get("env_kwargs"),
        mock_kwargs=payload.get("mock_kwargs"),
    )
    records: List[EpisodeRecord] = []
    errors: List[Dict[str, Any]] = []
    max_steps = int(payload.get("max_steps_per_episode", 2000))
    deterministic = bool(payload.get("deterministic", False))
    t0 = time.perf_counter()
    try:
        for episode_id, ep_seed in payload["episodes"]:
            try:
                records.append(run_episode(
                    env, policy,
                    seed=int(ep_seed),
                    episode_id=int(episode_id),
                    max_steps=max_steps,
                    deterministic=deterministic,
                    rng=random.Random(int(ep_seed)),
                    collect_transitions=True,
                ))
            except Exception as exc:  # noqa: BLE001
                errors.append({"episode_id": int(episode_id),
                               "seed": int(ep_seed),
                               "error": f"{type(exc).__name__}: {exc}"})
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()
    return {"records": records, "errors": errors,
            "wall_seconds": time.perf_counter() - t0}


# ══════════════════════════════════════════════════════════════════════
# 任务划分 / 并行执行
# ══════════════════════════════════════════════════════════════════════


def _episode_seed(seed: int, episode_index: int) -> int:
    return int(seed) + int(episode_index)


def _split_episodes(
    tasks: Sequence[Tuple[int, int]], workers: int
) -> List[List[Tuple[int, int]]]:
    """把 ``(episode_id, seed)`` 轮转分配给 workers（与完成顺序无关）。"""
    workers = max(1, int(workers))
    chunks: List[List[Tuple[int, int]]] = [[] for _ in range(workers)]
    for i, task in enumerate(tasks):
        chunks[i % workers].append(task)
    return [chunk for chunk in chunks if chunk]


def _run_payloads(
    payloads: Sequence[Dict[str, Any]], worker_fn: Any
) -> List[Any]:
    """单进程直接跑；多进程用 spawn Pool。"""
    if len(payloads) == 0:
        return []
    if len(payloads) == 1:
        return [worker_fn(payloads[0])]
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=len(payloads)) as pool:
        return pool.map(worker_fn, payloads)


def _base_payload(
    *,
    worker_id: int,
    policy_spec: Any,
    seed: int,
    episodes: Sequence[Tuple[int, int]],
    backend: str,
    num_players: int,
    opponent: str,
    env_kwargs: Optional[Dict[str, Any]],
    mock_kwargs: Optional[Dict[str, Any]],
    max_steps_per_episode: int,
    deterministic: bool,
    device: str,
) -> Dict[str, Any]:
    return {
        "worker_id": int(worker_id),
        "policy_spec": policy_spec,
        "policy_seed": int(seed),
        "episodes": list(episodes),
        "backend": str(backend),
        "num_players": int(num_players),
        "opponent": str(opponent),
        "env_kwargs": env_kwargs,
        "mock_kwargs": mock_kwargs,
        "max_steps_per_episode": int(max_steps_per_episode),
        "deterministic": bool(deterministic),
        "device": str(device),
    }


def _check_parallel_policy(policy_spec: Any, workers: int) -> None:
    if workers <= 1:
        return
    if isinstance(policy_spec, str):
        return
    ensure_picklable(policy_spec, what="policy")


def _check_policy_backend(policy_spec: Any, backend: str) -> None:
    """引擎感知策略（teacher）需要真实环境：mock/回退场景提前明确报错。"""
    if not policy_requires_engine(policy_spec):
        return
    backend_name = str(backend or "auto").lower()
    if backend_name == "mock":
        raise ValueError(
            "teacher 策略需要真实环境（env.game/env.agent_hero），"
            "backend='mock' 不支持。请用 --backend real/auto，"
            "或改用 heuristic/random（观测级可移植策略）。"
        )
    if backend_name == "auto" and not real_env_available():
        raise ValueError(
            "teacher 策略需要真实环境，但当前真实环境不可用（hsbg.env 导入失败）。"
            "请检查环境层，或改用 heuristic/random。"
        )


# ══════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════


def collect_trajectories(
    policy: Any = "heuristic",
    *,
    num_envs: int = 1,
    episodes: int = 10,
    seed: int = 0,
    out_path: Union[str, Path] = "runs/rl/collect.jsonl",
    resume: bool = True,
    per_step: bool = True,
    include_board: bool = True,
    include_extra: bool = False,
    num_players: int = 8,
    opponent: str = "heuristic",
    backend: str = "auto",
    env_kwargs: Optional[Dict[str, Any]] = None,
    mock_kwargs: Optional[Dict[str, Any]] = None,
    max_steps_per_episode: int = 2000,
    deterministic: bool = False,
    device: str = "cpu",
    verbose: bool = False,
) -> CollectStats:
    """多进程采集轨迹并写 JSONL（支持断点续采）。

    返回 :class:`CollectStats`；``stats.episodes`` 是最终文件里的完整局数。
    """
    if episodes < 0:
        raise ValueError("episodes 必须 >= 0")
    _check_policy_backend(policy, backend)
    workers = max(1, int(num_envs))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not resume and out_path.exists():
        # 显式要求"重新采集"：丢弃旧文件（否则合并逻辑会保留旧 episode）
        out_path.unlink()
    t0 = time.perf_counter()

    done = completed_seeds(out_path) if resume and out_path.exists() else {}
    tasks: List[Tuple[int, int]] = [
        (k, _episode_seed(seed, k)) for k in range(int(episodes))
        if _episode_seed(seed, k) not in done
    ]
    skipped = len(done) if resume else 0
    errors_from_workers: List[Dict[str, Any]] = []
    worker_stats: List[Dict[str, Any]] = []
    shard_paths: List[Path] = []

    if tasks:
        worker_count = min(workers, len(tasks))
        _check_parallel_policy(policy, worker_count)
        chunks = _split_episodes(tasks, worker_count)
        payloads: List[Dict[str, Any]] = []
        for worker_id, chunk in enumerate(chunks):
            shard = out_path.with_name(f"{out_path.name}.part{worker_id}")
            shard_paths.append(shard)
            payload = _base_payload(
                worker_id=worker_id, policy_spec=policy, seed=seed,
                episodes=chunk, backend=backend, num_players=num_players,
                opponent=opponent, env_kwargs=env_kwargs,
                mock_kwargs=mock_kwargs,
                max_steps_per_episode=max_steps_per_episode,
                deterministic=deterministic, device=device,
            )
            payload.update({"shard_path": str(shard),
                            "per_step": bool(per_step),
                            "include_board": bool(include_board),
                            "include_extra": bool(include_extra)})
            payloads.append(payload)
        if verbose:
            print(f"[collect] out={out_path} tasks={len(tasks)} workers={len(payloads)}")
        worker_stats = _run_payloads(payloads, _collect_worker)
        for stats in worker_stats:
            if stats.get("errors"):
                errors_from_workers.append(
                    error_record(episode_id=-1, seed=-1,
                                 error=f"worker_{stats['worker_id']}_errors={stats['errors']}",
                                 worker=int(stats["worker_id"]))
                )
    wall_seconds = time.perf_counter() - t0

    # ── 合并 + 汇总（始终以最终文件为准，保证 stats 与内容一致）──
    existing_header = None
    if out_path.exists():
        existing_header = read_dataset(out_path)["header"]
    header = existing_header or header_record(
        policy=describe_policy(policy),
        backend=backend,
        num_players=int(num_players),
        opponent=str(opponent),
        seed=int(seed),
        episodes=int(episodes),
        workers=workers,
        api_version=1,
        obs_version=1,
        source="hsbg.rl.collector",
    )
    _merge_dataset(out_path, shard_paths, header=header,
                   extra_errors=errors_from_workers)
    for shard in shard_paths:
        try:
            shard.unlink()
        except OSError:  # pragma: no cover
            pass
    summary = _summarize_dataset(out_path)
    num_players_ctx = int((summary["header"] or {}).get("num_players", num_players) or num_players)
    ranks: List[int] = summary["ranks"]
    dist: Dict[str, float] = {}
    if ranks:
        for r in range(1, num_players_ctx + 1):
            dist[str(r)] = sum(1 for x in ranks if x == r) / len(ranks)
    newly_completed = max(0, int(summary["episodes"]) - len(done)) if resume else int(summary["episodes"])
    new_steps = int(sum(int(worker.get("steps", 0) or 0)
                        for worker in worker_stats)) if worker_stats else 0
    return CollectStats(
        episodes=int(summary["episodes"]),
        new_episodes=int(newly_completed),
        steps=int(summary["steps"]),
        new_steps=new_steps,
        wall_seconds=float(wall_seconds),
        workers=workers,
        policy=describe_policy(policy),
        backend=str(backend),
        out_path=str(out_path),
        mean_rank=float(summary["mean_rank"]),
        rank_distribution=dist,
        action_kinds=dict(summary["action_kinds"]),
        invalid_actions=int(summary["invalid"]),
        truncated=int(summary["truncated"]),
        errors=int(summary["errors"]),
        resumed_skipped=int(skipped),
        episode_seeds=list(summary["seeds"]),
    )


def collect_rollouts(
    policy: Any = "heuristic",
    *,
    num_envs: int = 1,
    episodes: int = 10,
    seed: int = 0,
    num_players: int = 8,
    opponent: str = "heuristic",
    backend: str = "auto",
    env_kwargs: Optional[Dict[str, Any]] = None,
    mock_kwargs: Optional[Dict[str, Any]] = None,
    max_steps_per_episode: int = 2000,
    deterministic: bool = False,
    device: str = "cpu",
    verbose: bool = False,
) -> Tuple[List[EpisodeRecord], CollectStats]:
    """采集并返回内存中的 :class:`EpisodeRecord` 列表 + 统计（不写文件）。

    适合离线分析 / BC 数据准备；大批量建议用 :func:`collect_trajectories`。
    """
    if episodes < 0:
        raise ValueError("episodes 必须 >= 0")
    _check_policy_backend(policy, backend)
    workers = max(1, int(num_envs))
    tasks: List[Tuple[int, int]] = [
        (k, _episode_seed(seed, k)) for k in range(int(episodes))
    ]
    t0 = time.perf_counter()
    records: List[EpisodeRecord] = []
    errors: List[Dict[str, Any]] = []
    if tasks:
        worker_count = min(workers, len(tasks))
        _check_parallel_policy(policy, worker_count)
        chunks = _split_episodes(tasks, worker_count)
        payloads = [
            _base_payload(
                worker_id=worker_id, policy_spec=policy, seed=seed,
                episodes=chunk, backend=backend, num_players=num_players,
                opponent=opponent, env_kwargs=env_kwargs,
                mock_kwargs=mock_kwargs,
                max_steps_per_episode=max_steps_per_episode,
                deterministic=deterministic, device=device,
            )
            for worker_id, chunk in enumerate(chunks)
        ]
        if verbose:
            print(f"[rollouts] episodes={len(tasks)} workers={len(payloads)}")
        results = _run_payloads(payloads, _rollout_worker)
        for result in results:
            records.extend(result["records"])
            errors.extend(result["errors"])
    wall_seconds = time.perf_counter() - t0
    records.sort(key=lambda rec: rec.episode_id)
    ranks = [int(rec.rank) for rec in records]
    kinds: Dict[str, int] = {}
    steps = 0
    invalid = 0
    truncated = 0
    for rec in records:
        steps += int(rec.steps)
        invalid += int(rec.invalid_actions)
        truncated += int(bool(rec.truncated))
        for kind, count in rec.action_kinds().items():
            kinds[kind] = kinds.get(kind, 0) + count
    dist: Dict[str, float] = {}
    if ranks:
        for r in range(1, int(num_players) + 1):
            dist[str(r)] = sum(1 for x in ranks if x == r) / len(ranks)
    stats = CollectStats(
        episodes=len(records),
        new_episodes=len(records),
        steps=steps,
        new_steps=steps,
        wall_seconds=wall_seconds,
        workers=workers,
        policy=describe_policy(policy),
        backend=str(backend),
        out_path="",
        mean_rank=statistics.fmean(ranks) if ranks else 0.0,
        rank_distribution=dist,
        action_kinds=kinds,
        invalid_actions=invalid,
        truncated=truncated,
        errors=len(errors),
        resumed_skipped=0,
        episode_seeds=[int(rec.seed) for rec in records],
    )
    return records, stats


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m hsbg.rl.collector",
        description="高并发采集酒馆战棋轨迹（多进程 + JSONL + 断点续采）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--policy", default="heuristic",
                   help="策略：heuristic/random/first/end_turn、checkpoint 路径或模块级 callable")
    p.add_argument("--envs", "--workers", dest="envs", type=int, default=1,
                   help="并行 worker 数")
    p.add_argument("--episodes", type=int, default=10, help="目标总局数")
    p.add_argument("--seed", type=int, default=0, help="基准种子；第 k 局用 seed+k")
    p.add_argument("--out", default=None,
                   help=f"JSONL 输出路径（默认 {DEFAULT_OUT_DIR}/collect.jsonl；传空表示只跑内存）")
    p.add_argument("--num-players", type=int, default=8)
    p.add_argument("--opponent", default="heuristic", help="真环境对手策略名")
    p.add_argument("--backend", default="auto", choices=list(BACKENDS),
                   help="auto=真环境优先，不可用回退 mock")
    p.add_argument("--max-steps-per-episode", type=int, default=2000,
                   help="单局步数硬上限（防策略死循环）")
    p.add_argument("--deterministic", action="store_true",
                   help="策略尽量贪心（评测/演示）；默认随机采样")
    p.add_argument("--no-resume", action="store_true", help="关闭断点续采")
    p.add_argument("--no-per-step", action="store_true", help="只写每局一行（不写逐步）")
    p.add_argument("--no-board", action="store_true", help="观测摘要不含棋盘/手牌/酒馆卡 id")
    p.add_argument("--include-extra", action="store_true",
                   help="JSONL 观测摘要包含 Observation.extra 白名单（frozen/任务进度等；体积更大）")
    p.add_argument("--device", default="cpu", help="checkpoint 策略推理设备")
    p.add_argument("--json", action="store_true", help="以 JSON 打印统计")
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    use_file = args.out is not None
    out_path = Path(args.out) if use_file else None
    try:
        if use_file and out_path is not None:
            stats = collect_trajectories(
                args.policy,
                num_envs=args.envs,
                episodes=args.episodes,
                seed=args.seed,
                out_path=out_path,
                resume=not args.no_resume,
                per_step=not args.no_per_step,
                include_board=not args.no_board,
                include_extra=args.include_extra,
                num_players=args.num_players,
                opponent=args.opponent,
                backend=args.backend,
                max_steps_per_episode=args.max_steps_per_episode,
                deterministic=args.deterministic,
                device=args.device,
                verbose=not args.quiet,
            )
        else:
            _records, stats = collect_rollouts(
                args.policy,
                num_envs=args.envs,
                episodes=args.episodes,
                seed=args.seed,
                num_players=args.num_players,
                opponent=args.opponent,
                backend=args.backend,
                max_steps_per_episode=args.max_steps_per_episode,
                deterministic=args.deterministic,
                device=args.device,
                verbose=not args.quiet,
            )
    except (ValueError, RuntimeError) as exc:
        # 参数/后端不匹配（如 teacher + mock）→ 简洁错误，不打印整段 traceback
        print(f"[hsbg.rl.collector] 错误: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(stats.format())
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    raise SystemExit(main())


__all__ = [
    "CollectStats",
    "DEFAULT_OUT_DIR",
    "collect_trajectories",
    "collect_rollouts",
    "read_dataset",
    "completed_seeds",
    "build_arg_parser",
    "main",
]
