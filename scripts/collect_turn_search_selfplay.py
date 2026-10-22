"""turn-search 自对弈数据采集（价值网 Phase1 主数据）。

用法（先验证，再全量）::

    # 2 局验证：schema/readonly/determinism（约 2–4 分钟）
    python scripts/collect_turn_search_selfplay.py --validate-only 2

    # 全量：states=8，140 局（≈20k+ 样本），8 workers
    python scripts/collect_turn_search_selfplay.py --episodes 140 --workers 8 \
        --states-budget 8 --out runs/value_data/turn_search_20k.pkl

产物：
* `runs/value_data/turn_search_20k.pkl`：`BCDataset` 兼容（samples=(obs,action), ranks, episode_ids, meta）
* 每 worker shard（`*.partN.pkl`，合并后可删）
* `runs/value_split.json`：新增 `turn_search_20k` split（保留原有 BC/RL 字段）
* `runs/value_data/turn_search_20k_audit.json`：样本/标签/分布/耗时/fallback/磁盘

约束：env 不参与 pickle（worker 内 make_env）；payload 只放 bind 前的 `TurnSearchPolicyConfig` dict；
worker 内构造 policy + bind；`finally: env.close()`；不碰 `data/`/引擎；只产数据不训练。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import pickle
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsbg.env import BattlegroundsEnv  # noqa: E402
from hsbg.rl.api import run_episode  # noqa: E402
from hsbg.rl.api import obs_digest as _summary_obs_digest  # noqa: E402
from hsbg.search.policy import TurnSearchPolicy, TurnSearchPolicyConfig  # noqa: E402
from hsbg.train.bc import BCDataset  # noqa: E402

DEFAULT_OUT = "runs/value_data/turn_search_20k.pkl"
DEFAULT_SPLIT = "runs/value_split.json"


def _obs_digest(obs: Any) -> str:
    """语义摘要：不含 entity_id（引擎 uuid 每次运行不同，不能用于 determinism 对比）。"""
    cands = tuple(getattr(obs, "candidates", ()) or ())
    sig = tuple((getattr(c, "kind", ""), getattr(c, "src_zone", ""),
                 getattr(c, "src_slot", -1), getattr(c, "tgt_zone", ""),
                 getattr(c, "tgt_slot", -1), getattr(c, "option", -1),
                 getattr(c, "cost", -1)) for c in cands)
    return str(_summary_obs_digest(obs)) + "|" + repr(sig)


def _make_env(num_players: int, opponent: str, seed: int) -> BattlegroundsEnv:
    return BattlegroundsEnv(num_players=int(num_players),
                            opponent=str(opponent), seed=int(seed))


def _episode_payloads(args_dict: Dict[str, Any], episodes: Sequence[Tuple[int, int]],
                      shard_paths: Sequence[str], seed_start: int) -> List[Dict[str, Any]]:
    workers = max(1, len(shard_paths))
    chunks: List[List[Tuple[int, int]]] = [[] for _ in range(workers)]
    for i, item in enumerate(episodes):
        chunks[i % workers].append(item)
    payloads = []
    for wid, chunk in enumerate(chunks):
        if not chunk:
            continue
        payloads.append({
            "worker": wid,
            "episodes": list(chunk),
            "shard": shard_paths[wid],
            "search": dict(args_dict["search"]),
            "num_players": int(args_dict["num_players"]),
            "opponent": str(args_dict["opponent"]),
            "max_steps": int(args_dict["max_steps"]),
            "seed_start": int(seed_start),
        })
    return payloads


def _run_episode_with_policy(env: BattlegroundsEnv, policy: TurnSearchPolicy,
                             seed: int, episode_id: int,
                             max_steps: int) -> Any:
    policy.set_episode_seed(int(seed))
    return run_episode(env, policy, seed=int(seed), episode_id=int(episode_id),
                       max_steps=int(max_steps), collect_transitions=True)


def _worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    """worker：构造 policy（bind 前 picklable）→ 每局独立 env → 写 shard。"""
    cfg = TurnSearchPolicyConfig(**payload["search"])
    samples = []
    ranks: List[int] = []
    episode_ids: List[int] = []
    episodes_meta: List[Dict[str, Any]] = []
    fallbacks = 0
    wall0 = time.perf_counter()
    try:
        for eid, seed in payload["episodes"]:
            env = _make_env(payload["num_players"], payload["opponent"], seed)
            policy = TurnSearchPolicy(cfg)
            try:
                policy.bind_env(env)
                rec = _run_episode_with_policy(env, policy, seed, eid,
                                               payload["max_steps"])
            finally:
                try:
                    env.close()
                except Exception:  # noqa: BLE001
                    pass
            n = len(rec.transitions)
            for tr in rec.transitions:
                samples.append((tr.obs, int(tr.action)))
            ranks.extend([int(rec.rank)] * n)
            episode_ids.extend([int(eid)] * n)
            stats = policy.stats_dict()
            fallbacks += int(stats.get("fallbacks", 0))
            episodes_meta.append({
                "episode_id": int(eid), "seed": int(seed),
                "rank": int(rec.rank), "turns": int(rec.turns),
                "steps": int(rec.steps), "samples": int(n),
                "terminated": bool(rec.terminated),
                "truncated": bool(rec.truncated),
                "reason": str(rec.reason),
                "total_reward": float(rec.total_reward),
                "wall_s": float(rec.wall_seconds),
                "search": stats,
            })
        ds = BCDataset(samples=samples, ranks=ranks, episode_ids=episode_ids,
                       meta={"worker": int(payload["worker"]),
                             "source": "turn_search_selfplay",
                             "episodes": episodes_meta})
        ds.save(payload["shard"])
        return {"worker": payload["worker"], "ok": True, "episodes": len(episodes_meta),
                "samples": len(samples), "fallbacks": int(fallbacks),
                "wall_s": round(time.perf_counter() - wall0, 1),
                "shard": payload["shard"], "episodes_meta": episodes_meta}
    except Exception as exc:  # noqa: BLE001 - 单 worker 失败不拖垮整体
        return {"worker": payload["worker"], "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "shard": payload.get("shard"),
                "wall_s": round(time.perf_counter() - wall0, 1)}


def _merge_shards(shard_paths: Sequence[str], meta: Dict[str, Any]) -> BCDataset:
    samples: List[Tuple[Any, int]] = []
    ranks: List[int] = []
    episode_ids: List[int] = []
    episodes_meta: List[Dict[str, Any]] = []
    for path in shard_paths:
        if not Path(path).is_file():
            continue
        ds = BCDataset.load(path)
        samples.extend(ds.samples)
        ranks.extend(ds.ranks)
        episode_ids.extend(ds.episode_ids)
        episodes_meta.extend(ds.meta.get("episodes", []))
    # 按 episode_id 去重（同 id 只保留第一份；样本按 episode 连续排列）
    keep: List[int] = []
    seen = set()
    current: Optional[int] = None
    keep_current = True
    for i, eid in enumerate(episode_ids):
        key = int(eid)
        if key != current:
            current = key
            keep_current = key not in seen
            if keep_current:
                seen.add(key)
        if keep_current:
            keep.append(i)
    if len(keep) != len(episode_ids):
        samples = [samples[i] for i in keep]
        ranks = [ranks[i] for i in keep]
        episode_ids = [episode_ids[i] for i in keep]
    seen_meta = set()
    unique_meta = []
    for m in sorted(episodes_meta, key=lambda x: int(x["episode_id"])):
        eid = int(m["episode_id"])
        if eid in seen_meta:
            continue
        seen_meta.add(eid)
        unique_meta.append(m)
    merged_meta = dict(meta)
    merged_meta["episodes"] = unique_meta
    return BCDataset(samples=samples, ranks=ranks, episode_ids=episode_ids,
                     meta=merged_meta)


def _golden_split(episode_ids: Sequence[int], ratios: Tuple[float, float, float],
                  seed: int = 0) -> Dict[str, List[int]]:
    ids = sorted({int(e) for e in episode_ids})
    rng = random.Random(int(seed))
    rng.shuffle(ids)
    n = len(ids)
    n_train = int(n * ratios[0])
    n_val = int(n * ratios[1])
    return {
        "train": sorted(ids[:n_train]),
        "val": sorted(ids[n_train:n_train + n_val]),
        "test": sorted(ids[n_train + n_val:]),
    }


def _write_split(split: Dict[str, List[int]], samples_by_ep: Dict[int, int],
                 dataset_path: str, split_path: str, seed: int) -> Dict[str, Any]:
    episode_to_split = {}
    for name, ids in split.items():
        for eid in ids:
            episode_to_split[int(eid)] = name
    payload = {
        "strategy": "episode_id 70/15/15（固定 seed；同局不跨 split）",
        "seed": int(seed),
        "dataset": str(dataset_path),
        "episodes": {k: len(v) for k, v in split.items()},
        "samples": {k: int(sum(samples_by_ep.get(int(e), 0) for e in v))
                    for k, v in split.items()},
        "episode_to_split": {str(k): v for k, v in episode_to_split.items()},
        "leak_check": {
            "train_val": len(set(split["train"]) & set(split["val"])),
            "train_test": len(set(split["train"]) & set(split["test"])),
            "val_test": len(set(split["val"]) & set(split["test"])),
        },
    }
    p = Path(split_path)
    existing = {}
    if p.is_file():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = {}
    existing.setdefault("seed", int(seed))
    existing.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    existing["turn_search_20k" if Path(dataset_path).stem == "turn_search_20k"
             else f"turn_search_{Path(dataset_path).stem}"] = payload
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return payload


def _build_audit(dataset: BCDataset, dataset_path: Path, elapsed_s: float,
                 worker_results: Sequence[Dict[str, Any]],
                 split_info: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    ranks = Counter(int(r) for r in dataset.ranks)
    turns = Counter()
    phases = Counter()
    obs_versions = Counter()
    decisions = 0
    fallbacks = 0
    for obs, _ in dataset.samples:
        turns[int(getattr(obs, "turn", 0) or 0)] += 1
        phases[str(getattr(obs, "phase", ""))] += 1
        obs_versions[str(getattr(obs, "version", None))] += 1
    eps_meta = dataset.meta.get("episodes", [])
    for m in eps_meta:
        decisions += int(m.get("search", {}).get("decisions", 0))
        fallbacks += int(m.get("search", {}).get("fallbacks", 0))
    try:
        import hsbg.env.spec as spec
        spec_version = int(spec.Observation().version)
    except Exception:  # noqa: BLE001
        spec_version = None
    data_patch = None
    try:
        data_patch = json.loads((ROOT / "data/bg_summary.json").read_text(
            encoding="utf-8")).get("patch")
    except Exception:  # noqa: BLE001
        pass
    return {
        "schema": "hsbg.turn_search_selfplay.audit.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": str(dataset_path),
        "dataset_bytes": int(dataset_path.stat().st_size),
        "dataset_mb": round(dataset_path.stat().st_size / 1e6, 2),
        "engine_data_patch": data_patch,
        "search": dict(args.search),
        "search_seed": int(args.search.get("search_seed", 0)),
        "num_players": int(args.num_players),
        "opponent": str(args.opponent),
        "episodes": int(dataset.num_episodes()),
        "samples": int(len(dataset)),
        "samples_per_episode_mean": round(
            len(dataset) / max(dataset.num_episodes(), 1), 2),
        "rank_coverage": int(sum(1 for r in dataset.ranks if int(r) >= 1)),
        "rank_dist": {str(k): int(v) for k, v in sorted(ranks.items())},
        "turns": {str(k): int(v) for k, v in sorted(turns.items())},
        "phases": {str(k): int(v) for k, v in phases.items()},
        "obs_versions": {str(k): int(v) for k, v in obs_versions.items()},
        "spec_obs_version": spec_version,
        "episode_seed_range": [int(args.seed_start),
                                int(args.seed_start) + int(args.episodes) - 1],
        "workers": int(args.workers),
        "elapsed_s": round(elapsed_s, 1),
        "elapsed_min": round(elapsed_s / 60.0, 2),
        "search_decisions": int(decisions),
        "fallbacks": int(fallbacks),
        "fallback_rate": round(fallbacks / max(decisions, 1), 4),
        "episodes_meta": eps_meta,
        "worker_results": list(worker_results),
        "split": {
            "path": str(args.split),
            "episodes": split_info.get("episodes"),
            "samples": split_info.get("samples"),
            "leak_check": split_info.get("leak_check"),
        },
        "reproduce": ("python scripts/collect_turn_search_selfplay.py "
                      f"--episodes {args.episodes} --workers {args.workers} "
                      f"--states-budget {args.search['states_budget']} "
                      f"--seed-start {args.seed_start} --out {args.out}"),
    }


def _validate(args: argparse.Namespace) -> int:
    """2 局验证：readonly（digest 不变）+ determinism（同 seed 轨迹/rank 一致）。"""
    from hsbg.planning import digest as game_digest
    cfg = TurnSearchPolicyConfig(**args.search)
    episode_ok = 0
    for i in range(int(args.validate_only)):
        eid, seed = i, int(args.seed_start) + i
        env = _make_env(args.num_players, args.opponent, seed)
        policy = TurnSearchPolicy(cfg)
        policy.bind_env(env)
        obs = env.reset(seed=seed)
        # 若开局是 choice，先 resolve 到 recruit 再测 act 的只读性
        for _ in range(64):
            if str(getattr(obs, "phase", "")) != "choice":
                break
            obs, _, _term, _trunc, _info = env.step(0)
        before = game_digest(env.game)
        _ = policy.act(obs)
        after = game_digest(env.game)
        env.close()
        if before != after:
            print(f"[validate] episode {eid}: FAIL readonly（game digest 变化）")
            return 2
        # determinism：同 seed 跑两次
        runs = []
        for _ in range(2):
            env = _make_env(args.num_players, args.opponent, seed)
            p = TurnSearchPolicy(cfg)
            p.bind_env(env)
            try:
                rec = _run_episode_with_policy(env, p, seed, eid, args.max_steps)
            finally:
                env.close()
            runs.append({
                "actions": [int(t.action) for t in rec.transitions],
                "digests": [_obs_digest(t.obs) for t in rec.transitions],
                "rank": int(rec.rank), "steps": int(rec.steps),
                "obs_version": [int(getattr(t.obs, "version", -1))
                                for t in rec.transitions[:1]],
            })
        same = (runs[0]["actions"] == runs[1]["actions"]
                and runs[0]["digests"] == runs[1]["digests"]
                and runs[0]["rank"] == runs[1]["rank"])
        print(f"[validate] episode {eid}: readonly=OK determinism="
              f"{'OK' if same else 'FAIL'} steps={runs[0]['steps']} "
              f"rank={runs[0]['rank']} obs_version={runs[0]['obs_version']}")
        if not same:
            return 3
        episode_ok += 1
    print(f"[validate] passed {episode_ok}/{args.validate_only}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="turn-search 自对弈 value 数据采集")
    p.add_argument("--episodes", type=int, default=140, help="局数（默认 140≈20k+ 样本）")
    p.add_argument("--workers", type=int, default=8, help="并行 worker 数")
    p.add_argument("--seed-start", type=int, default=20000, help="episode seed 起点")
    p.add_argument("--num-players", type=int, default=8)
    p.add_argument("--opponent", type=str, default="heuristic")
    p.add_argument("--max-steps", type=int, default=2000)
    p.add_argument("--states-budget", type=int, default=8)
    p.add_argument("--samples-per-action", type=int, default=1)
    p.add_argument("--combat-samples", type=int, default=1)
    p.add_argument("--completion-policy", type=str, default="heuristic")
    p.add_argument("--state-scorer", type=str, default="pairwise",
                   choices=["pairwise", "value", "value_prune_pairwise"])
    p.add_argument("--prune-top-k", type=int, default=4)
    p.add_argument("--search-seed", type=int, default=0)
    p.add_argument("--evaluator-checkpoint", type=str,
                   default="runs/bc/official_320/policy_bc.pt")
    p.add_argument("--out", type=str, default=DEFAULT_OUT)
    p.add_argument("--split", type=str, default=DEFAULT_SPLIT)
    p.add_argument("--validate-only", type=int, default=0,
                   help="只跑 N 局 readonly/determinism 验证，不写数据集")
    p.add_argument("--golden-seed", type=int, default=0)
    p.add_argument("--golden-ratios", type=str, default="0.7,0.15,0.15")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    args.search = {
        "states_budget": int(args.states_budget),
        "samples_per_action": int(args.samples_per_action),
        "combat_samples": int(args.combat_samples),
        "completion_policy": str(args.completion_policy),
        "state_scorer": str(args.state_scorer),
        "prune_top_k": int(args.prune_top_k),
        "action_aggregate": "max",
        "max_steps_per_turn": 40,
        "search_seed": int(args.search_seed),
        "evaluator_checkpoint": str(args.evaluator_checkpoint),
    }
    if args.validate_only:
        return _validate(args)

    t0 = time.perf_counter()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shard_dir = out_path.parent / f"{out_path.stem}_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_paths = [str(shard_dir / f"{out_path.stem}.part{i}.pkl")
                   for i in range(int(args.workers))]
    episodes = [(i, int(args.seed_start) + i) for i in range(int(args.episodes))]
    payloads = _episode_payloads(args.__dict__, episodes, shard_paths,
                                 int(args.seed_start))
    print(f"[collect] out={out_path} episodes={args.episodes} workers="
          f"{len(payloads)} states={args.states_budget}")

    if len(payloads) == 1:
        results = [_worker(payloads[0])]
    else:
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=len(payloads)) as pool:
            results = pool.map(_worker, payloads)
    for r in results:
        print(f"[worker {r.get('worker')}] ok={r.get('ok')} "
              f"episodes={r.get('episodes')} samples={r.get('samples')} "
              f"fallbacks={r.get('fallbacks')} wall={r.get('wall_s')}s "
              f"{r.get('error', '')}")
    if not all(r.get("ok") for r in results):
        print("[collect] 有 worker 失败，停止合并；见上方错误")
        return 4

    data_patch = None
    try:
        data_patch = json.loads((ROOT / "data/bg_summary.json").read_text(
            encoding="utf-8")).get("patch")
    except Exception:  # noqa: BLE001
        pass
    ratios = tuple(float(x) for x in str(args.golden_ratios).split(","))
    all_episode_ids = [int(e) for e, _ in episodes]
    split_ids = _golden_split(all_episode_ids, ratios, seed=int(args.golden_seed))
    golden_split = {str(e): name for name, ids in split_ids.items() for e in ids}
    meta = {
        "schema": "hsbg.value_selfplay.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "turn_search_selfplay",
        "engine_data_patch": data_patch,
        "search_config": dict(args.search),
        "policy_header": {"name": "TurnSearchPolicy", "states_budget":
                          int(args.states_budget),
                          "checkpoint": str(args.evaluator_checkpoint)},
        "opponent": str(args.opponent),
        "num_players": int(args.num_players),
        "obs_version": 2,
        "seed_range": [int(args.seed_start),
                        int(args.seed_start) + int(args.episodes) - 1],
        "golden_split": golden_split,
        "golden_seed": int(args.golden_seed),
    }
    dataset = _merge_shards(shard_paths, meta)
    dataset.save(out_path)
    elapsed = time.perf_counter() - t0
    samples_by_ep: Dict[int, int] = {}
    for m in dataset.meta.get("episodes", []):
        samples_by_ep[int(m["episode_id"])] = int(m.get("samples", 0))
    split_info = _write_split(split_ids, samples_by_ep, str(out_path),
                              str(args.split), int(args.golden_seed))
    audit = _build_audit(dataset, out_path, elapsed, results, split_info, args)
    audit_path = out_path.parent / f"{out_path.stem}_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(f"[collect] done samples={len(dataset)} episodes={dataset.num_episodes()} "
          f"mb={out_path.stat().st_size / 1e6:.1f} elapsed={elapsed / 60:.1f}min")
    print(f"[collect] dataset={out_path}")
    print(f"[collect] split={args.split} audit={audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
