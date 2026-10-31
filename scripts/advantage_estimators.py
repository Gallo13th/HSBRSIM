#!/usr/bin/env python3
"""方向 B 离线诊断：GAE / 幂率迹 / 几何迹 三种 advantage estimator 对比。

对应 ``docs/RESEARCH_PLAN_V2.md`` §B.1–B.3 与 §4.2：

1. **读轨迹**：优先读
   - ``runs/audit/trajectories.jsonl.gz``（620 局冻结审计轨迹，s10 checkpoint，CPU，
     bot 对手、无注入；每局只含 learner 决策 ``[turn, action, value]`` 与 rank）；
   - ``runs/adv_estimators/records_*.jsonl.gz``（本工具 ``--dump-records`` 产出的
     s14 checkpoint 32 局自对弈 records 转储；含 value/action/turn/old_logprob）；
   - 训练 worker 的 ``rec_*.npz``（若存在；字段为 SoA 数组）。
2. **三种 estimator**（同一批轨迹）：
   - ① GAE(γ=1, λ=0.995)，旧路径逐位等价；
   - ② 幂率/分数阶：``w_l = (1+l/κ)^(−α)``，前向 ``A_t = Σ w̃_l γ^l δ_{t+l}``；
   - ③ 几何对照：``λ^l``；按与幂率核的 KL 最小拟合 λ*（horizon 归一化）。
3. **报告**：与 Monte-Carlo/终局回报的相关性、ESS/``N_eff``、早期 (t≤8) 终端分量
   占比、同一批轨迹上的方差、α/κ 网格；输出 ``report.json`` + ``REPORT.md``。

因为 trainer 不落盘 records（只有 worker 临时 npz），``--dump-records 32`` 会用
**CPU** 跑 s14 checkpoint 的 32 局自对弈并转储（不占 GPU、不改训练目录）。

用法::

    PYTHONPATH=rust/python:. python scripts/advantage_estimators.py \
        --dump-records 32 --checkpoint runs/az_entity_s14/model.pt --workers 8 \
        --out runs/adv_estimators

    # 只分析已有轨迹（不跑采集）
    PYTHONPATH=rust/python:. python scripts/advantage_estimators.py \
        --input runs/audit/trajectories.jsonl.gz --out runs/adv_estimators

所有输出只写 ``--out``（默认 ``runs/adv_estimators``），不碰主训练 run。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import N_PLAYERS, RANK_UTILITY, utility_from_rank  # noqa: E402
from hsbg.az.train.power_trace import (compute_credit, effective_sample_size,  # noqa: E402
                                       kernel_weights, power_raw_kernel)

DEFAULT_OUT = os.path.join(ROOT, "runs", "adv_estimators")
DEFAULT_AUDIT = os.path.join(ROOT, "runs", "audit", "trajectories.jsonl.gz")
S14_RUN = os.path.join(ROOT, "runs", "az_entity_s14")


# ══════════════════════════════════════════════════════════════════════════
# 0. 小工具
# ══════════════════════════════════════════════════════════════════════════
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _git_revision() -> str:
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "-C", ROOT, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except Exception:  # noqa: BLE001
        return ""


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_jsonable(v) for v in x.tolist()]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    return x


def _read_jsonl_gz(path: str) -> Iterable[Dict[str, Any]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _write_jsonl_gz(path: str, rows: Iterable[Dict[str, Any]]) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_jsonable(row), ensure_ascii=False) + "\n")
            n += 1
    return n


# ══════════════════════════════════════════════════════════════════════════
# 1. 轨迹读取（统一成 Episode dict）
# ══════════════════════════════════════════════════════════════════════════
def _episode_from_arrays(*, game_id: int, seat: int, rank: int,
                         turns: Sequence[Any], actions: Sequence[Any],
                         values: Sequence[Any],
                         old_logprobs: Optional[Sequence[Any]] = None,
                         rewards: Optional[Sequence[Any]] = None,
                         dones: Optional[Sequence[Any]] = None,
                         forced: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    n = len(values)
    r = np.zeros(n, dtype=np.float64)
    u = float(utility_from_rank([int(rank)])[0]) if 1 <= int(rank) <= N_PLAYERS else 0.0
    if rewards is None:
        if n:
            r[-1] = u
    else:
        r = np.asarray(rewards, dtype=np.float64).reshape(-1)
        if r.size != n:
            r = np.zeros(n, dtype=np.float64)
            if n:
                r[-1] = u
    d = np.zeros(n, dtype=np.float64)
    if dones is None:
        if n:
            d[-1] = 1.0
    else:
        d = np.asarray(dones, dtype=np.float64).reshape(-1)
        if d.size != n:
            d = np.zeros(n, dtype=np.float64)
            if n:
                d[-1] = 1.0
    return {
        "game_id": int(game_id), "seat": int(seat), "rank": int(rank),
        "turns": [int(x) for x in turns],
        "actions": [int(x) for x in actions],
        "values": [float(x) for x in values],
        "old_logprobs": (None if old_logprobs is None
                         else [float(x) for x in old_logprobs]),
        "rewards": r.tolist(), "dones": d.tolist(),
        "forced": (None if forced is None else [bool(x) for x in forced]),
    }


def load_audit(path: str, max_games: int = 0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """``runs/audit/trajectories.jsonl.gz``：每局 records=[[turn,action,value],...]。"""
    eps: List[Dict[str, Any]] = []
    games = 0
    for game in _read_jsonl_gz(path):
        games += 1
        recs = game.get("records") or []
        rank = int(game.get("rank", 0) or 0)
        if not recs or not (1 <= rank <= N_PLAYERS):
            continue
        turns = [int(r[0]) for r in recs]
        actions = [int(r[1]) for r in recs]
        values = [float(r[2]) for r in recs]
        eps.append(_episode_from_arrays(
            game_id=int(game.get("seed", games)), seat=0, rank=rank,
            turns=turns, actions=actions, values=values))
        if max_games and len(eps) >= int(max_games):
            break
    meta = {
        "path": os.path.abspath(path), "format": "audit_trajectories",
        "games_seen": int(games), "episodes": int(len(eps)),
        "decisions": int(sum(len(e["values"]) for e in eps)),
        "provenance": ("s10 checkpoint, 7 engine bots, no injection, CPU; "
                       "one learner seat per game (PRESSURE_AUDIT §2.5)"),
        "sha256": _sha256(path),
    }
    return eps, meta


def load_records(path: str, max_games: int = 0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """本工具 dump 的 jsonl.gz（每行一个 seat-episode）。"""
    eps: List[Dict[str, Any]] = []
    for row in _read_jsonl_gz(path):
        n = min(len(row.get("values") or []), len(row.get("turns") or []),
                len(row.get("actions") or []))
        if n <= 0:
            continue
        eps.append(_episode_from_arrays(
            game_id=int(row.get("game_id", len(eps))),
            seat=int(row.get("seat", 0)), rank=int(row.get("rank", 0) or 0),
            turns=(row["turns"][:n]), actions=(row["actions"][:n]),
            values=(row["values"][:n]),
            old_logprobs=(row.get("old_logprobs") or [None] * n)[:n]
            if row.get("old_logprobs") is not None else None,
            rewards=row.get("rewards"), dones=row.get("dones"),
            forced=row.get("forced")))
        if max_games and len({e["game_id"] for e in eps}) >= int(max_games):
            break
    meta = {
        "path": os.path.abspath(path), "format": "records_dump",
        "episodes": int(len(eps)),
        "games": int(len({e["game_id"] for e in eps})),
        "decisions": int(sum(len(e["values"]) for e in eps)),
        "sha256": _sha256(path),
    }
    return eps, meta


def load_npz(path: str, max_games: int = 0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """训练 worker 的 ``rec_*.npz``（SoA；按 episode_ids 分组）。"""
    z = np.load(path, allow_pickle=True)
    if "episode_ids" in z:
        groups = np.asarray(z["episode_ids"]).reshape(-1)
    else:
        groups = (np.asarray(z["game_ids"]).astype(np.int64) * 8
                  + np.asarray(z["seats"]).astype(np.int64))
    eps: List[Dict[str, Any]] = []
    for g in np.unique(groups):
        idx = np.flatnonzero(groups == g)
        if idx.size == 0:
            continue
        eps.append(_episode_from_arrays(
            game_id=int(z["game_ids"][idx[0]]), seat=int(z["seats"][idx[0]]),
            rank=int(z["ranks"][idx[-1]]),
            turns=z["turns"][idx], actions=z["actions"][idx],
            values=z["values"][idx],
            old_logprobs=(z["old_logprobs"][idx]
                          if "old_logprobs" in z else None),
            rewards=(z["rewards"][idx] if "rewards" in z else None),
            dones=(z["dones"][idx] if "dones" in z else None),
            forced=(z["forced"][idx] if "forced" in z else None)))
        if max_games and len({e["game_id"] for e in eps}) >= int(max_games):
            break
    meta = {
        "path": os.path.abspath(path), "format": "worker_npz",
        "episodes": int(len(eps)),
        "games": int(len({e["game_id"] for e in eps})),
        "decisions": int(sum(len(e["values"]) for e in eps)),
        "sha256": _sha256(path),
    }
    return eps, meta


def load_any(path: str, max_games: int = 0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    p = str(path)
    if p.endswith(".npz"):
        return load_npz(p, max_games)
    # 用首行判断：audit 行有 'records' 且 records 元素是 list；dump 行有 turns/values
    first: Dict[str, Any] = {}
    for row in _read_jsonl_gz(p):
        first = row
        break
    if "records" in first and isinstance(first.get("records"), list):
        return load_audit(p, max_games)
    return load_records(p, max_games)


# ══════════════════════════════════════════════════════════════════════════
# 2. 32 局 records 转储（CPU，自对弈，s14 checkpoint）
# ══════════════════════════════════════════════════════════════════════════
def _dump_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    import torch  # noqa: PLC0415

    torch.set_num_threads(int(payload.get("threads", 2)))
    from hsbg.az.train.model import load_checkpoint  # noqa: PLC0415
    from hsbg.az.train.ppo import (CollectConfig, PPOEvaluator,  # noqa: PLC0415
                                   PPOSelfPlayPolicy)
    from hsbg.az.train.selfplay import play_selfplay_game  # noqa: PLC0415

    t0 = time.time()
    model, meta = load_checkpoint(str(payload["checkpoint"]), device="cpu")
    cfg = CollectConfig(
        games=1, seed=0, opponent="self", behavior="net", temperature=1.0,
        max_steps=20000, max_actions_per_turn=40,
        move_guard=bool(int(payload.get("move_guard", 1))),
        move_cap=int(payload.get("move_cap", 3)),
        move_repeat_limit=int(payload.get("move_repeat_limit", 2)))
    ev = PPOEvaluator(model, device="cpu",
                      norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    pol = PPOSelfPlayPolicy(model, device="cpu", config=cfg, eval_fn=ev,
                            seed=int(payload["seed"]), move_model=False)
    episodes: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    g0 = int(payload["game_offset"])
    for k in range(int(payload["games"])):
        gid = g0 + k
        pol.game_id = gid
        pol.reseed(int(payload["seed"]) + gid)
        _samples, gm = play_selfplay_game(
            pol, seed=int(payload["seed"]) + gid, game_id=gid,
            sample_stride=1, max_steps=20000, collect=False)
        metas.append({k2: gm.get(k2) for k2 in
                      ("game_id", "seed", "decisions", "truncated",
                       "placements", "elapsed_s", "illegal_actions")})
        if bool(gm.get("truncated")):
            continue
        placements = list(gm.get("placements") or [0] * N_PLAYERS)
        for seat in range(N_PLAYERS):
            recs = [r for r in pol.records if int(r["seat"]) == seat]
            if not recs:
                continue
            episodes.append(_episode_from_arrays(
                game_id=gid, seat=seat, rank=int(placements[seat]),
                turns=[int(r.get("turn", -1)) for r in recs],
                actions=[int(r["action"]) for r in recs],
                values=[float(r["value"]) for r in recs],
                old_logprobs=[float(r["old_logprob"]) for r in recs],
                forced=[bool(r.get("forced", False)) for r in recs]))
    return {"episodes": episodes, "games_meta": metas,
            "seconds": time.time() - t0, "worker": int(payload["worker_id"])}


def dump_records(*, checkpoint: str, games: int, out: str, workers: int,
                 seed: int, threads: int, move_guard: int = 1) -> Dict[str, Any]:
    """CPU 跑 ``games`` 局 8 座自对弈并写 records 转储；返回 manifest。"""
    t0 = time.time()
    n = max(1, int(games))
    w = max(1, min(int(workers), n))
    per = (n + w - 1) // w
    payloads = []
    for i in range(w):
        g0 = i * per
        cnt = min(per, n - g0)
        if cnt <= 0:
            continue
        payloads.append({
            "worker_id": i, "game_offset": g0, "games": cnt,
            "checkpoint": os.path.abspath(checkpoint), "seed": int(seed),
            "threads": int(threads), "move_guard": int(move_guard)})
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=len(payloads)) as pool:
        results = pool.map(_dump_worker, payloads)
    eps: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    for res in results:
        eps.extend(res["episodes"])
        metas.extend(res["games_meta"])
    eps.sort(key=lambda e: (int(e["game_id"]), int(e["seat"])))
    path = os.path.join(out, f"records_s14_{n}g.jsonl.gz")
    _write_jsonl_gz(path, eps)
    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checkpoint": os.path.abspath(checkpoint),
        "checkpoint_sha256": _sha256(checkpoint),
        "checkpoint_meta": {"arch": "entity", "loaded": True},
        "games_requested": int(n), "games_finished": int(sum(
            1 for m in metas if not bool(m.get("truncated")))),
        "games_meta": metas,
        "episodes": int(len(eps)),
        "decisions": int(sum(len(e["values"]) for e in eps)),
        "seed": int(seed), "workers": len(payloads),
        "threads_per_worker": int(threads), "device": "cpu",
        "move_guard": int(move_guard),
        "opponent": "self (8 seats, s14 policy, no human/mirror injection)",
        "elapsed_s": round(time.time() - t0, 2),
        "path": os.path.abspath(path), "sha256": _sha256(path),
        "note": ("trainer 不落盘 records；本转储只保留 estimator replay 需要的标量字段"
                 "（turn/action/value/old_logprob/rank），不含 features/cards/mask。"),
    }
    with open(os.path.join(out, "records_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(_jsonable(manifest), f, ensure_ascii=False, indent=2)
    return manifest


# ══════════════════════════════════════════════════════════════════════════
# 3. estimator 评估
# ══════════════════════════════════════════════════════════════════════════
def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 2 or b.size < 2:
        return 0.0
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    sa = float(a.std())
    sb = float(b.std())
    if sa < 1e-12 or sb < 1e-12:
        return 0.0
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 2:
        return 0.0
    ra = np.argsort(np.argsort(a.astype(np.float64)))
    rb = np.argsort(np.argsort(b.astype(np.float64)))
    return _pearson(ra.astype(np.float64), rb.astype(np.float64))


def _episode_arrays(ep: Dict[str, Any]) -> Tuple[np.ndarray, ...]:
    r = np.asarray(ep["rewards"], dtype=np.float64)
    v = np.asarray(ep["values"], dtype=np.float64)
    d = np.asarray(ep["dones"], dtype=np.float64)
    t = np.asarray(ep["turns"], dtype=np.int64)
    return r, v, d, t


def _credit_for(ep: Dict[str, Any], spec: Dict[str, Any]):
    r, v, d, t = _episode_arrays(ep)
    tb = str(spec.get("timebase", "decision"))
    kw: Dict[str, Any] = dict(mode=spec["mode"], gamma=float(spec.get("gamma", 1.0)))
    if spec["mode"] in ("gae", "geom"):
        kw["lam"] = float(spec.get("lam", 0.995))
    if spec["mode"] == "geom":
        kw["normalize"] = bool(spec.get("normalize", False))
    if spec["mode"] == "power":
        kw["alpha"] = float(spec["alpha"])
        kw["kappa"] = float(spec["kappa"])
        kw["normalize"] = bool(spec.get("normalize", True))
    if spec.get("cutoff"):
        kw["cutoff"] = int(spec["cutoff"])
    if tb == "turn":
        kw["timebase"] = "turn"
        kw["turns"] = t
    adv, _ret, diag = compute_credit(r, v, d, **kw)
    return adv.astype(np.float64), diag, r, v, t


def _spec_name(spec: Dict[str, Any]) -> str:
    if spec["mode"] == "gae":
        return f"gae_lam{spec.get('lam', 0.995):g}"
    if spec["mode"] == "geom":
        return f"geom_lam{spec.get('lam', 0.995):g}" + (
            "" if spec.get("normalize", False) else "_unnorm")
    return (f"power_a{spec['alpha']:g}_k{spec['kappa']:g}"
            + ("_norm" if spec.get("normalize", True) else "_unnorm")
            + ("_turn" if spec.get("timebase") == "turn" else ""))


def evaluate_spec(episodes: Sequence[Dict[str, Any]], spec: Dict[str, Any],
                  ref_spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """在**完全相同的 episodes** 上评估一个 estimator。"""
    name = _spec_name(spec)
    per_ep: List[Dict[str, float]] = []
    adv_all: List[np.ndarray] = []
    mc_all: List[np.ndarray] = []
    ref_all: List[np.ndarray] = []
    ess_all: List[np.ndarray] = []
    share_all: List[np.ndarray] = []
    tw_all: List[np.ndarray] = []
    turns_all: List[np.ndarray] = []
    var_eps: List[float] = []
    ref_var_eps: List[float] = []
    mean_eps: List[float] = []
    ret_eps: List[float] = []
    z_adv: List[np.ndarray] = []
    z_mc: List[np.ndarray] = []
    for ep in episodes:
        adv, diag, r, v, t = _credit_for(ep, spec)
        n = adv.size
        if n == 0:
            continue
        # γ=1 终局 utility 回报（records 的奖励只在末步）；MC advantage = R − V_t
        R = float(r[-1]) if n else 0.0
        mc_adv = np.full(n, R) - v
        adv_all.append(adv)
        mc_all.append(mc_adv)
        if ref_spec is not None:
            radv, _rd, _rr, _rv, _rt = _credit_for(ep, ref_spec)
            ref_all.append(radv.astype(np.float64))
            ref_var_eps.append(float(np.var(radv)))
        ess_all.append(np.asarray(diag["ess"], dtype=np.float64))
        share_all.append(np.asarray(diag["terminal_share"], dtype=np.float64))
        tw_all.append(np.asarray(diag["terminal_weight"], dtype=np.float64))
        turns_all.append(t)
        var_eps.append(float(np.var(adv)))
        mean_eps.append(float(np.mean(adv)))
        ret_eps.append(R)
        sa = float(np.std(adv))
        sm = float(np.std(mc_adv))
        if n >= 2 and sa > 1e-12 and sm > 1e-12:
            z_adv.append((adv - adv.mean()) / sa)
            z_mc.append((mc_adv - mc_adv.mean()) / sm)
        early = t <= 8
        if n >= 2:
            per_ep.append({
                "corr_mc_adv": _pearson(adv[early], mc_adv[early]) if int(early.sum()) >= 2 else 0.0,
                "corr_mc_adv_all": _pearson(adv, mc_adv),
                "spearman_mc_adv": _spearman(adv[early], mc_adv[early]) if int(early.sum()) >= 2 else 0.0,
                "corr_adv_ref": (_pearson(adv, ref_all[-1])
                                 if ref_spec is not None else 0.0),
                "n_early": int(early.sum()),
                "n": int(n),
            })
    if not adv_all:
        return {"name": name, "spec": spec, "episodes": 0, "decisions": 0}

    A = np.concatenate(adv_all)
    M = np.concatenate(mc_all)
    E = np.concatenate(ess_all)
    S = np.concatenate(share_all)
    TW = np.concatenate(tw_all)
    T = np.concatenate(turns_all)
    early = T <= 8
    early_list = [p for p in per_ep if p["n_early"] >= 2]
    early_c = [p["corr_mc_adv"] for p in early_list]
    all_c = [p["corr_mc_adv_all"] for p in per_ep]
    ref_c = [p["corr_adv_ref"] for p in per_ep]
    out: Dict[str, Any] = {
        "name": name, "spec": dict(spec),
        "episodes": int(len(adv_all)), "decisions": int(A.size),
        "corr_mc_adv_pooled": _pearson(A, M),
        "corr_episode_mean_vs_return": _pearson(
            np.asarray(mean_eps), np.asarray(ret_eps)),
        "corr_episode_mean_vs_return_spearman": _spearman(
            np.asarray(mean_eps), np.asarray(ret_eps)),
        "spearman_mc_adv_pooled": _spearman(A, M),
        "corr_mc_adv_episode_mean": float(np.mean(early_c)) if early_c else 0.0,
        "corr_mc_adv_episode_median": float(np.median(early_c)) if early_c else 0.0,
        "corr_mc_adv_episode_p10": (float(np.quantile(early_c, 0.1))
                                    if early_c else 0.0),
        "corr_mc_adv_all_episode_mean": float(np.mean(all_c)) if all_c else 0.0,
        "corr_mc_adv_all_episode_median": float(np.median(all_c)) if all_c else 0.0,
        "spearman_mc_adv_episode_mean": float(np.mean(
            [p["spearman_mc_adv"] for p in early_list])) if early_list else 0.0,
        "corr_adv_ref_episode_mean": float(np.mean(ref_c)) if ref_c else 0.0,
        "n_early_episodes": len(early_list),
        "ess_mean": float(np.mean(E)),
        "ess_median": float(np.median(E)),
        "ess_t8": float(np.mean(E[T == 8])) if np.any(T == 8) else None,
        "ess_t12": float(np.mean(E[T == 12])) if np.any(T == 12) else None,
        "ess_t15": float(np.mean(E[T == 15])) if np.any(T == 15) else None,
        "terminal_share_median": float(np.median(S)),
        "terminal_share_mean": float(np.mean(S)),
        "terminal_share_early_median": float(np.median(S[early])) if early.any() else None,
        "terminal_weight_early_median": (float(np.median(TW[early]))
                                         if early.any() else None),
        "adv_var": float(np.var(A)),
        "adv_std": float(np.std(A)),
        "adv_mean_abs": float(np.mean(np.abs(A))),
        "adv_mean": float(np.mean(A)),
        "adv_mean_abs_early": (float(np.mean(np.abs(A[early])))
                               if early.any() else None),
        "adv_mean_abs_late": (float(np.mean(np.abs(A[~early])))
                              if (~early).any() else None),
        "early_abs_share": (float(np.abs(A[early]).sum()
                                  / max(np.abs(A).sum(), 1e-12))
                            if early.any() else None),
        "mean_episode_var": float(np.mean(var_eps)),
        "within_episode_var": float(np.mean(var_eps)),
        "within_episode_var_ratio_vs_ref": (float(np.mean(var_eps)
                                                  / max(np.mean(ref_var_eps), 1e-12))
                                            if ref_var_eps else None),
        "mean_episode_mean": float(np.mean(mean_eps)),
        "var_of_episode_means": float(np.var(np.asarray(mean_eps))),
        "mc_adv_var": float(np.var(M)),
        "mc_explained_var": (1.0 - float(np.var(M - A)) / max(float(np.var(M)), 1e-12)),
        "mc_explained_var_standardized": (
            1.0 - float(np.var(np.concatenate(z_mc) - np.concatenate(z_adv))
                        / max(float(np.var(np.concatenate(z_mc))), 1e-12))
            if z_adv else None),
        "early_n": int(early.sum()),
    }
    if ref_spec is not None:
        R = np.concatenate(ref_all)
        out["corr_adv_ref_pooled"] = _pearson(A, R)
        out["var_ratio_vs_ref"] = float(np.var(A) / max(float(np.var(R)), 1e-12))
        out["std_ratio_vs_ref"] = float(np.std(A) / max(float(np.std(R)), 1e-12))
    return out


def kernel_table(alphas: Sequence[float], kappas: Sequence[float],
                 lengths: Sequence[int] = (64, 128, 181)) -> List[Dict[str, Any]]:
    rows = []
    for a in alphas:
        for k in kappas:
            row = {"alpha": float(a), "kappa": float(k)}
            for L in lengths:
                w = kernel_weights(int(L), "power", alpha=float(a),
                                   kappa=float(k), normalize=True)
                row[f"ess_L{int(L)}"] = float(effective_sample_size(w))
                row[f"w0_L{int(L)}"] = float(w[0]) if w.size else 0.0
                row[f"wlast_L{int(L)}"] = float(w[-1]) if w.size else 0.0
            rows.append(row)
    return rows


def fit_geometric_lambda(alpha: float, kappa: float, L: int = 64) -> Dict[str, Any]:
    """在 λ 网格上对归一化幂率核做最小 KL 的几何拟合（用于对照）。"""
    k = np.arange(int(L), dtype=np.float64)
    w = power_raw_kernel(int(L), alpha, kappa)
    w = w / w.sum()
    best = None
    for lam in np.exp(np.linspace(math.log(1e-4), math.log(0.999), 4000)):
        g = (1.0 - float(lam)) * np.power(float(lam), k)
        kl = float(np.sum(w * np.log(np.maximum(w, 1e-300)
                                     / np.maximum(g, 1e-300))))
        if best is None or kl < best[0]:
            cos = float(np.dot(w, g) / math.sqrt(float(np.dot(w, w) * np.dot(g, g))))
            best = (kl, float(lam), cos)
    return {"lambda": best[1], "kl": best[0], "cosine": best[2], "L": int(L)}


# ══════════════════════════════════════════════════════════════════════════
# 4. 报告
# ══════════════════════════════════════════════════════════════════════════
def _fmt(x: Any, nd: int = 4) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _markdown(report: Dict[str, Any], primary: str) -> str:
    lines: List[str] = []
    lines.append("# 方向 B 离线 advantage estimator 对比\n")
    lines.append(f"- 生成：{report.get('created_at')}；git `{report.get('git_revision', '')[:12]}`")
    lines.append(f"- 主数据源：`{primary}`")
    lines.append("- 定义：GAE(γ=1, λ=0.995) / 幂率 `w_l=(1+l/κ)^(−α)` / 几何 `λ^l`；"
                 "power 与 geom 做 horizon 归一化（PPO advantage normalization 前尺度可比），"
                 "GAE 保持旧路径未归一化。")
    lines.append("")
    src = report["sources"].get(primary, {})
    if src:
        lines.append(f"## 数据（{primary}）\n")
        lines.append(f"- episodes={src.get('episodes')}，decisions={src.get('decisions')}，"
                     f"games={src.get('games', '—')}；{src.get('provenance', '')}")
    lines.append("\n## 三种 estimator（同一批轨迹）\n")
    lines.append("| estimator | corr(MC adv, 早期 t≤8) | corr(MC adv, 全部) | ESS 均值 | "
                 "N_eff@t8 / t12 / t15 | 终端占比 t≤8 | 早期 \\|A\\| 占比 | "
                 "Adv 方差 | 方差比 vs GAE |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key in ("gae", "power", "power_unnorm", "geom"):
        row = report["estimators"].get(key)
        if not row:
            continue
        lines.append(
            f"| {row['name']} | {_fmt(row.get('corr_mc_adv_episode_mean'))} | "
            f"{_fmt(row.get('corr_mc_adv_all_episode_mean'))} | "
            f"{_fmt(row.get('ess_mean'), 2)} | "
            f"{_fmt(row.get('ess_t8'), 1)} / {_fmt(row.get('ess_t12'), 1)} / "
            f"{_fmt(row.get('ess_t15'), 1)} | "
            f"{_fmt(row.get('terminal_share_early_median'))} | "
            f"{_fmt(row.get('early_abs_share'), 3)} | "
            f"{_fmt(row.get('adv_var'), 5)} | {_fmt(row.get('var_ratio_vs_ref'), 3)} |")
    lines.append("\n> `corr(MC adv)` 是 estimator advantage 与 `R − V_t`（γ=1 终局回报）"
                 "的 per-episode Pearson 均值；pooled 是跨局拼接后的相关。"
                 "方差比以同一批轨迹的 GAE 为 1。")
    lines.append("\n## 跨源一致性（同一 α/κ，不混合统计）\n")
    lines.append("| source | episodes | decisions | GAE corr(MC) | power_norm corr | "
                 "power_unnorm corr | ESS 变化 | 终端占比变化(norm) | 终端占比变化(unnorm) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for sname, srow in report.get("by_source", {}).items():
        est = srow.get("estimators") or {}
        g = est.get("gae") or {}
        p = est.get("power") or {}
        pu = est.get("power_unnorm") or {}
        ess_drop = 1.0 - float(p.get("ess_mean", 0.0)) / max(
            float(g.get("ess_mean", 1.0)), 1e-9)
        gain = (float(p.get("terminal_share_early_median") or 0.0)
                / max(float(g.get("terminal_share_early_median") or 0.0), 1e-9) - 1.0)
        gain_u = (float(pu.get("terminal_share_early_median") or 0.0)
                  / max(float(g.get("terminal_share_early_median") or 0.0), 1e-9)
                  - 1.0)
        lines.append(f"| {sname} | {srow.get('episodes')} | {srow.get('decisions')} | "
                     f"{_fmt(g.get('corr_mc_adv_episode_mean'))} | "
                     f"{_fmt(p.get('corr_mc_adv_episode_mean'))} | "
                     f"{_fmt(pu.get('corr_mc_adv_episode_mean'))} | "
                     f"{-ess_drop * 100:+.1f}% | {gain * 100:+.1f}% | "
                     f"{gain_u * 100:+.1f}% |")
    lines.append("\n## α/κ 网格（幂率，decision 时基）\n")
    lines.append("| α | κ | normalize | N_eff(t≤8) | 终端占比 t≤8 | 早期\\|A\\|占比 | "
                 "corr(MC adv) | Adv 方差 | 方差比 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in report.get("power_sweep", []):
        lines.append(
            f"| {row['alpha']:g} | {row['kappa']:g} | "
            f"{int(bool(row.get('normalize')))} | "
            f"{_fmt(row.get('ess_t8'), 1)} | "
            f"{_fmt(row.get('terminal_share_early_median'))} | "
            f"{_fmt(row.get('early_abs_share'), 3)} | "
            f"{_fmt(row.get('corr_mc_adv_episode_mean'))} | "
            f"{_fmt(row.get('adv_var'), 5)} | {_fmt(row.get('var_ratio_vs_ref'), 3)} |")
    lines.append("\n## 几何对照拟合\n")
    for row in report.get("geom_fits", []):
        lines.append(f"- α={row['alpha']:g}, κ={row['kappa']:g}: λ*={row['fit']['lambda']:.6g}，"
                     f"KL={row['fit']['kl']:.3g}，cosine={row['fit']['cosine']:.6f}")
    lines.append("\n## 建议\n")
    rec = report.get("recommendation", {})
    for line in rec.get("notes", []):
        lines.append(f"- {line}")
    lines.append("\n> 估计器只改变**信用分配核**，不改变 reward/γ/模型容量；离线相关/ESS "
                 "提升不是策略改进证明，接训练前仍需 §2.3 人类+质量面板门禁。")
    return "\n".join(lines) + "\n"


def analyze(sources: Dict[str, List[Dict[str, Any]]], src_meta: Dict[str, Dict[str, Any]],
            *, alpha_grid: Sequence[float], kappa_grid: Sequence[float],
            main_alpha: float, main_kappa: float,
            out: str) -> Dict[str, Any]:
    primary = "s14_records" if "s14_records" in sources else (
        next(iter(sources)) if sources else "")
    if not primary or not sources[primary]:
        raise SystemExit("没有可用轨迹：请先 --dump-records 32 或 --input <trajectories>")
    episodes = sources[primary]
    gae_spec = {"mode": "gae", "gamma": 1.0, "lam": 0.995}
    power_spec = {"mode": "power", "gamma": 1.0, "alpha": float(main_alpha),
                  "kappa": float(main_kappa), "normalize": True}
    power_unnorm_spec = {"mode": "power", "gamma": 1.0,
                         "alpha": float(main_alpha),
                         "kappa": float(main_kappa), "normalize": False}
    fit = fit_geometric_lambda(float(main_alpha), float(main_kappa), L=64)
    geom_spec = {"mode": "geom", "gamma": 1.0, "lam": fit["lambda"],
                 "normalize": True}
    gae = evaluate_spec(episodes, gae_spec)
    power = evaluate_spec(episodes, power_spec, ref_spec=gae_spec)
    power_unnorm = evaluate_spec(episodes, power_unnorm_spec, ref_spec=gae_spec)
    geom = evaluate_spec(episodes, geom_spec, ref_spec=gae_spec)

    # 跨源一致性：每个源都跑三种 estimator（报告里区分，不混合统计）
    by_source: Dict[str, Any] = {
        primary: {"episodes": len(episodes),
                  "decisions": int(sum(len(e["values"]) for e in episodes)),
                  "estimators": {"gae": gae, "power": power,
                                 "power_unnorm": power_unnorm, "geom": geom}}
    }
    for key, eps in sources.items():
        if key == primary or not eps:
            continue
        g2 = evaluate_spec(eps, gae_spec)
        p2 = evaluate_spec(eps, power_spec, ref_spec=gae_spec)
        pu2 = evaluate_spec(eps, power_unnorm_spec, ref_spec=gae_spec)
        gm2 = evaluate_spec(eps, geom_spec, ref_spec=gae_spec)
        ess_drop2 = 1.0 - float(p2["ess_mean"]) / max(float(g2["ess_mean"]), 1e-9)
        by_source[key] = {
            "episodes": len(eps),
            "decisions": int(sum(len(e["values"]) for e in eps)),
            "estimators": {"gae": g2, "power": p2,
                           "power_unnorm": pu2, "geom": gm2},
            "power_vs_gae": {
                "ess_drop_frac": float(ess_drop2),
                "terminal_share_gain_frac": (
                    float(p2.get("terminal_share_early_median") or 0.0)
                    / max(float(g2.get("terminal_share_early_median") or 0.0), 1e-9)
                    - 1.0),
                "corr_mc_adv_delta": (
                    float(p2["corr_mc_adv_episode_mean"])
                    - float(g2["corr_mc_adv_episode_mean"])),
            },
        }
    tol = 1e-9

    power_sweep = []
    for a in alpha_grid:
        for k in kappa_grid:
            for norm in (True, False):
                spec = {"mode": "power", "gamma": 1.0, "alpha": float(a),
                        "kappa": float(k), "normalize": bool(norm)}
                row = evaluate_spec(episodes, spec, ref_spec=gae_spec)
                row["alpha"], row["kappa"] = float(a), float(k)
                row["normalize"] = bool(norm)
                power_sweep.append(row)
    # 只保留关键列，避免 report.json 过大
    sweep_keys = ("name", "alpha", "kappa", "normalize", "decisions", "ess_mean",
                  "ess_t8", "ess_t12", "ess_t15", "terminal_share_early_median",
                  "terminal_share_median", "terminal_weight_early_median",
                  "corr_mc_adv_episode_mean", "corr_mc_adv_episode_median",
                  "corr_mc_adv_all_episode_mean", "corr_mc_adv_pooled",
                  "adv_var", "adv_std", "mean_abs_adv", "early_abs_share",
                  "adv_mean_abs_early", "adv_mean_abs_late",
                  "within_episode_var", "within_episode_var_ratio_vs_ref",
                  "mc_explained_var_standardized",
                  "var_ratio_vs_ref", "std_ratio_vs_ref", "mc_explained_var",
                  "early_n")
    power_sweep = [{k: r.get(k) for k in sweep_keys} for r in power_sweep]
    geom_fits = [{"alpha": float(main_alpha), "kappa": float(main_kappa),
                  "fit": fit}]

    notes = []
    ess_drop = 1.0 - float(power["ess_mean"]) / max(float(gae["ess_mean"]), tol)
    pu_ess_drop = 1.0 - float(power_unnorm["ess_mean"]) / max(
        float(gae["ess_mean"]), tol)
    share_gain = (float(power["terminal_share_early_median"] or 0.0)
                  / max(float(gae["terminal_share_early_median"] or 0.0), tol) - 1.0)
    pu_share_gain = (float(power_unnorm["terminal_share_early_median"] or 0.0)
                     / max(float(gae["terminal_share_early_median"] or 0.0), tol)
                     - 1.0)
    corr_gain = (float(power["corr_mc_adv_episode_mean"])
                 - float(gae["corr_mc_adv_episode_mean"]))
    pu_corr_gain = (float(power_unnorm["corr_mc_adv_episode_mean"])
                    - float(gae["corr_mc_adv_episode_mean"]))
    var_ratio = float(power.get("var_ratio_vs_ref", 0.0))
    pu_var_ratio = float(power_unnorm.get("var_ratio_vs_ref", 0.0))
    gae_early_share = float(gae.get("early_abs_share") or 0.0)
    pu_early_share = float(power_unnorm.get("early_abs_share") or 0.0)
    p_early_share = float(power.get("early_abs_share") or 0.0)
    notes.append(f"[spec 默认 normalize=1] ESS 相对 GAE 变化 {(-ess_drop) * 100:+.1f}%；"
                 f"早期 t≤8 终端占比 {float(power['terminal_share_early_median'] or 0):.3f}"
                 f" vs GAE {float(gae['terminal_share_early_median'] or 0):.3f}"
                 f"（{share_gain * 100:+.1f}%）；但早期 |A| 占全部 |A| 的比例 "
                 f"{p_early_share:.3f} vs GAE {gae_early_share:.3f}——"
                 f"horizon 归一化把早期 advantage 幅度压成 ~1/L，PPO 全局归一化后早期反而更轻。")
    notes.append(f"[normalize=0 变体] ESS 变化 {(-pu_ess_drop) * 100:+.1f}%；终端占比 "
                 f"{pu_share_gain * 100:+.1f}%；corr(MC adv) Δ={pu_corr_gain:+.4f}；"
                 f"早期 |A| 占比 {pu_early_share:.3f}（GAE {gae_early_share:.3f}）；"
                 f"方差比 {pu_var_ratio:.3f}×。")
    notes.append("PPO 在 loss 内对 advantage 做全局归一化（normalize_advantage），"
                 "因此 normalize=0 的绝对尺度不改变策略梯度；但 returns=A+V 会进 value loss，"
                 "尺度需保持在 GAE 量级。")
    verdict = "hold"
    if (pu_ess_drop < 0.5 and pu_share_gain > 0.05 and pu_corr_gain > -0.02
            and pu_early_share >= 0.95 * gae_early_share):
        verdict = "candidate_ab"
    notes.append(f"离线判定：{verdict}（不是策略改进证明；需 §2.3 人类+质量面板门禁）。")
    report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_revision": _git_revision(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "primary_source": primary,
        "sources": {k: {**v} for k, v in src_meta.items()},
        "kernel_table": kernel_table(alpha_grid, kappa_grid),
        "estimators": {"gae": gae, "power": power,
                       "power_unnorm": power_unnorm, "geom": geom},
        "by_source": by_source,
        "power_sweep": power_sweep,
        "geom_fits": geom_fits,
        "recommendation": {
            "verdict": verdict,
            "alpha": float(main_alpha), "kappa": float(main_kappa),
            "geom_lambda_matched": float(fit["lambda"]),
            "ess_drop_frac": float(ess_drop),
            "terminal_share_gain_frac": float(share_gain),
            "corr_mc_adv_delta": float(corr_gain),
            "var_ratio_vs_ref": float(var_ratio),
            "power_unnorm": {
                "ess_drop_frac": float(pu_ess_drop),
                "terminal_share_gain_frac": float(pu_share_gain),
                "corr_mc_adv_delta": float(pu_corr_gain),
                "var_ratio_vs_ref": float(pu_var_ratio),
                "early_abs_share": float(pu_early_share),
                "gae_early_abs_share": float(gae_early_share),
            },
            "notes": notes,
        },
    }
    report = _jsonable(report)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    md = _markdown(report, primary)
    with open(os.path.join(out, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write(md)
    return report


# ══════════════════════════════════════════════════════════════════════════
# 5. main
# ══════════════════════════════════════════════════════════════════════════
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="方向 B：三种 advantage estimator 离线对比 + records 转储")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dump-records", type=int, default=0,
                    help="CPU 跑 N 局 s14 自对弈并转储 records（0=不跑）")
    ap.add_argument("--checkpoint", default=os.path.join(S14_RUN, "model.pt"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--dump-seed", type=int, default=20100)
    ap.add_argument("--move-guard", type=int, default=1)
    ap.add_argument("--input", action="append", default=[],
                    help="额外轨迹文件（jsonl.gz 或 rec_*.npz）；可多次")
    ap.add_argument("--no-auto-sources", action="store_true",
                    help="只读 --input（不自动加 audit/已有 dump）")
    ap.add_argument("--max-games", type=int, default=0,
                    help="每个源最多读多少局（0=全部）")
    ap.add_argument("--alpha-grid", default="0,0.125,0.25,0.5,1,2,4")
    ap.add_argument("--kappa-grid", default="3,10,30")
    ap.add_argument("--alpha", type=float, default=0.25,
                    help="主幂率 estimator 的 α（默认 0.25，见报告建议）")
    ap.add_argument("--kappa", type=float, default=3.0)
    ap.add_argument("--skip-dump-if-present", type=int, default=1)
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    manifest = None
    if args.dump_records > 0:
        if not os.path.isfile(args.checkpoint):
            print(f"[error] checkpoint 不存在: {args.checkpoint}", file=sys.stderr)
            return 2
        print(f"[dump] CPU 自对弈 {args.dump_records} 局，workers={args.workers} "
              f"threads={args.threads} checkpoint={args.checkpoint}", flush=True)
        manifest = dump_records(
            checkpoint=args.checkpoint, games=int(args.dump_records), out=args.out,
            workers=int(args.workers), seed=int(args.dump_seed),
            threads=int(args.threads), move_guard=int(args.move_guard))
        print(f"[dump] episodes={manifest['episodes']} decisions={manifest['decisions']} "
              f"games={manifest['games_finished']} elapsed={manifest['elapsed_s']}s "
              f"-> {manifest['path']}", flush=True)

    paths: List[str] = []
    if not args.no_auto_sources:
        if os.path.isfile(DEFAULT_AUDIT):
            paths.append(DEFAULT_AUDIT)
        for name in sorted(os.listdir(args.out)) if os.path.isdir(args.out) else []:
            if name.startswith("records_") and name.endswith(".jsonl.gz"):
                paths.append(os.path.join(args.out, name))
    paths.extend(args.input)
    # 去重（保持顺序）
    seen = set()
    paths = [p for p in paths if not (p in seen or seen.add(p))]
    if not paths:
        print("[error] 没有轨迹源；用 --dump-records 32 或 --input <path>", file=sys.stderr)
        return 2

    sources: Dict[str, List[Dict[str, Any]]] = {}
    src_meta: Dict[str, Dict[str, Any]] = {}
    for p in paths:
        if not os.path.isfile(p):
            print(f"[warn] 跳过不存在的源: {p}", flush=True)
            continue
        try:
            eps, meta = load_any(p, max_games=int(args.max_games))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 读取失败 {p}: {exc!r}", flush=True)
            continue
        if not eps:
            continue
        key = "s14_records" if "records_s14" in os.path.basename(p) else (
            "audit" if "trajectories" in os.path.basename(p) else
            os.path.splitext(os.path.basename(p))[0])
        # 同名源追加
        if key in sources:
            sources[key].extend(eps)
            src_meta[key]["episodes"] = len(sources[key])
        else:
            sources[key] = eps
            src_meta[key] = meta
        print(f"[load] {key}: episodes={len(eps)} from {p}", flush=True)

    alpha_grid = [float(x) for x in str(args.alpha_grid).split(",") if x.strip()]
    kappa_grid = [float(x) for x in str(args.kappa_grid).split(",") if x.strip()]
    report = analyze(sources, src_meta, alpha_grid=alpha_grid,
                     kappa_grid=kappa_grid, main_alpha=float(args.alpha),
                     main_kappa=float(args.kappa), out=args.out)
    if manifest is not None:
        report["dump_manifest"] = manifest
        with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
            json.dump(_jsonable(report), f, ensure_ascii=False, indent=2)
    rec = report["recommendation"]
    print(f"[done] -> {os.path.join(args.out, 'report.json')}", flush=True)
    print(f"[verdict] {rec['verdict']} alpha={rec['alpha']:g} kappa={rec['kappa']:g} "
          f"ess_drop={rec['ess_drop_frac'] * 100:.1f}% "
          f"terminal_gain={rec['terminal_share_gain_frac'] * 100:.1f}% "
          f"corr_delta={rec['corr_mc_adv_delta']:+.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
