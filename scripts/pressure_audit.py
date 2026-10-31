#!/usr/bin/env python3
"""PPAI 终审：纯 CPU 的**冻结轨迹反事实审计**（不训练 / 不用 GPU / 不重跑网络）。

回答一条链是否成立::

    注入人类战团（board-only） → 学习者实际遇敌压力 → 终局奖励对早期决策的信用

做法（全部离线、CPU）：

1. **暴露测量**：用 s10 模型（``runs/az_entity_s10/model.pt``，CPU、eval 模式、无梯度）在
   独立 seed 面板上跑 ≥N 条大厅轨迹（无注入的纯 bot 大厅 = 配对设计的对照世界）。每条轨迹
   在 t∈[6,15] 预抽**一个**存活快照：记录该 turn 起点 ``state_json``、学习者/对手座位在
   **战斗前**的完整 ``player_json``、以及该 turn 学习者实际对位（``next_opponent``）。
   对每个快照 × 三种注入配置（s10 的 p90×2 席×p0.3 / A 的 auto×2×p0.3 / B 的 auto×3×p0.5）
   独立重播种 ≥64 次战斗，并与"同快照、同 RNG 种子、不注入"逐种子配对。

2. **压力有效性**（预注册）：注入组战斗败率 ≥ +5pp，或期望承受伤害 ≥ +1.0（配对 95% CI）。
   同时报告**条件效应**（=100% 命中）与**按暴露折算的每 learner-turn 效应**。

3. **信号传播**：用 ``runs/az_entity_s10/history.jsonl`` + 本审计自己采的轨迹，离线重算
   GAE（γ=1、λ=0.995；另附日志里记录的 λ=0.95 作敏感性）：终局奖励到 t≤8 / t7 升本决策的
   信用权重 ``(γλ)^(N-1-k)`` 分布、GAE 终端分量 vs 价值 bootstrap 分量、截断/掩码影响。

4. **保真度配对消融**：≥200 个**可信完整快照**（``runs/library/snaps_champ`` 里我们自己的
   EOT 快照，含完整 Player 状态）上，board-only 注入 vs 完整 hand/counters/golden 注入
   配对（同状态、同 RNG）。真实人类数据没有隐藏真值 → 只报"机制上界/下界"，明确数据不足。

5. **结论**：按预注册判据输出 (a)/(b)/(c) 三分支之一（见 :func:`decide_branch`）。

用法::

    # 正式（CPU，12 进程）
    CUDA_VISIBLE_DEVICES="" python scripts/pressure_audit.py \
        --games 512 --battle-seeds 64 --workers 12

    # 冒烟（16 局 / 8 seed / 24 帧）
    CUDA_VISIBLE_DEVICES="" python scripts/pressure_audit.py --smoke

输出：``runs/audit/pressure_audit.json``（全部数字）+ 缓存
``runs/audit/trajectories.jsonl.gz`` / ``runs/audit/snapshots.jsonl.gz``。

注意事项（必须如实标注）：

- 轨迹大厅是**无注入**的 s10 vs 7 引擎 bot；这是配对设计的对照世界（注入在快照处施加），
  不是 s10 训练时的镜像+人类混合大厅。方向性影响：训练大厅的对手更强 → 学习者战团更弱 →
  本文的压力效应是**保守下界**。
- board-only 注入在引擎里由 ``Game.inject_board`` 完成：新实体 ``pool_copies=0``，因此在
  "非本局"容器上池守恒可能报 ``pool_balance_ok=false``（只影响池账本，不影响战斗数值）。
- 人类观测没有 golden / 隐藏 counters / hand → 真实人类的隐藏真值**不可得**（数据不足）。
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

N_PLAYERS = 8
LEARNER_SEAT = 0
UPGRADE_ACTION = 3          # hsbg/env/action_space_std.py: A_UPGRADE = 3
RANK_UTILITY = [1.0 - 2.0 * (r - 1) / (N_PLAYERS - 1) for r in range(1, N_PLAYERS + 1)]
TRIAL_SEED_K = 0x9E3779B9   # 引擎 debug.rs: rng = g.seed ^ (K*(i+1))

#: 三种训练注入配置（s10 实际 / lib_ab A / lib_ab B）。
CONFIGS: Tuple[Dict[str, Any], ...] = (
    {"name": "s10", "sample": "p90", "seats": 2, "p": 0.3,
     "desc": "s10 实际：p90 × 2 席 × p0.3"},
    {"name": "A", "sample": "auto", "seats": 2, "p": 0.3,
     "desc": "A：auto × 2 席 × p0.3"},
    {"name": "B", "sample": "auto", "seats": 3, "p": 0.5,
     "desc": "B：auto × 3 席 × p0.5"},
)

DEFAULT_HUMAN_BOARDS = "data/real_library/library_real_degraded.jsonl"
DEFAULT_MIRROR_SNAPS = "runs/library/snaps_champ"
DEFAULT_HISTORY = "runs/az_entity_s10/history.jsonl"
DEFAULT_LIB_AB = "runs/lib_ab"
DEFAULT_OUT = "runs/audit/pressure_audit.json"


# ════════════════════════════════════════════════════════════════════════
# 基础工具
# ════════════════════════════════════════════════════════════════════════


def _jsonl_gz_write(path: str, rows: Iterable[Dict[str, Any]]) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
    return n


def _jsonl_gz_read(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return out
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _read_jsonl_gz_slice(path: str, positions: Sequence[int]) -> List[Dict[str, Any]]:
    """只解析 line index ∈ positions 的行（省内存/时间）。"""
    want = {int(p): i for i, p in enumerate(sorted(positions))}
    out: List[Optional[Dict[str, Any]]] = [None] * len(want)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            j = want.get(i)
            if j is None:
                continue
            out[j] = json.loads(line)
    return [r for r in out if r is not None]


def _pct(x: Any) -> Dict[str, float]:
    a = np.asarray(x, dtype=np.float64).reshape(-1)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return {"n": 0}
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "p10": float(np.percentile(a, 10)),
        "p50": float(np.percentile(a, 50)),
        "p90": float(np.percentile(a, 90)),
        "min": float(a.min()),
        "max": float(a.max()),
    }


def _bootstrap_ci(x: Any, n_boot: int = 4000, alpha: float = 0.05,
                  seed: int = 20261031) -> Dict[str, float]:
    a = np.asarray(x, dtype=np.float64).reshape(-1)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return {"n": 0, "mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    r = np.random.default_rng(int(seed))
    idx = r.integers(0, a.size, size=(int(n_boot), int(a.size)))
    means = a[idx].mean(axis=1)
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "ci_low": float(np.percentile(means, 100 * alpha / 2)),
        "ci_high": float(np.percentile(means, 100 * (1 - alpha / 2))),
    }


def _sign_test_p(d: Any) -> float:
    a = np.asarray(d, dtype=np.float64).reshape(-1)
    a = a[np.isfinite(a) & (a != 0.0)]
    if a.size == 0:
        return 1.0
    pos = float((a > 0).sum())
    n = float(a.size)
    z = (pos - n / 2.0) / max(1e-12, math.sqrt(n) / 2.0)
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


def _mean(x: Any) -> float:
    a = np.asarray(x, dtype=np.float64).reshape(-1)
    return float(a.mean()) if a.size else 0.0


# ════════════════════════════════════════════════════════════════════════
# 引擎 / 数据池
# ════════════════════════════════════════════════════════════════════════


def load_engine():
    import hsbg_engine as E  # noqa: PLC0415
    return E


def load_pool(path: str, sample: str = "auto"):
    from hsbg.az.train.human_board_pool import load_pool as _load  # noqa: PLC0415
    pool = _load(path, sample=sample)
    if pool is None:
        raise FileNotFoundError(f"人类战团池不存在/为空: {path}")
    return pool


def _board_strength(pj: Dict[str, Any]) -> int:
    return int(sum(int(m.get("atk", 0)) + int(m.get("hp", 0))
                   for m in (pj.get("board") or [])))


def _tier_of(turn: int) -> int:
    from hsbg.az.train.human_board_pool import turn_tier  # noqa: PLC0415
    return int(turn_tier(int(turn)))


def _golden_to_base_map() -> Dict[int, int]:
    """golden cid -> base cid（catalog 的 normal_id）。真实人类观测没有金色身份。"""
    E = load_engine()
    rows = json.loads(E.catalog_json())
    by_id = {str(r.get("id")): int(r["cid"]) for r in rows if r.get("cid") is not None}
    out: Dict[int, int] = {}
    for r in rows:
        cid, norm = r.get("cid"), r.get("normal_id")
        if cid is None or not norm:
            continue
        base = by_id.get(str(norm))
        if base is not None and int(base) != int(cid):
            out[int(cid)] = int(base)
    return out


# ────────────────────────── 战斗复现（CombatPreview） ──────────────────────────


def _preview(E: Any, g: Any, a: int, b: int, n: int, details: bool = True) -> Dict[str, Any]:
    raw = g.debug(json.dumps({"cmd": "combat_preview", "a": int(a), "b": int(b),
                              "n": int(n), "details": bool(details)}))
    return json.loads(raw)


def _trials(res: Dict[str, Any]) -> Dict[str, List[float]]:
    t = res.get("trials") or []
    return {
        "winner": [int(x.get("winner", 2)) for x in t],
        "dmg_dealt": [float(x.get("damage_dealt", 0)) for x in t],
        "dmg_taken": [float(x.get("damage_taken", 0)) for x in t],
        "truncated": [int(bool(x.get("truncated"))) for x in t],
    }


def _survivors_of(res: Dict[str, Any], side: int = 0) -> int:
    sample = res.get("sample") or {}
    frames = sample.get("frames") or []
    if not frames:
        return 0
    boards = frames[-1].get("boards") or [[], []]
    side_board = boards[side] if side < len(boards) else []
    return int(sum(1 for m in side_board if int(m.get("hp", 0)) > 0))


def _battle_game(E: Any, start_state: str, learner_json: str, target_seat: int,
                 target_json: str, boot_seed: Optional[int] = None) -> Any:
    """用 turn 起点的 8 人 ``state_json`` 作容器，装入学习者/对手的**战斗前**完整状态。"""
    st = json.loads(start_state)
    if boot_seed is not None:
        st["seed"] = int(boot_seed)
    g = E.Game.from_json(json.dumps(st))
    g.set_player_from_json(LEARNER_SEAT, learner_json, True, True)
    g.set_player_from_json(int(target_seat), target_json, True, True)
    return g


def _loss_seq(seq: Sequence[int]) -> float:
    return _mean([1.0 if int(w) == 1 else 0.0 for w in seq])


def _win_seq(seq: Sequence[int]) -> float:
    return _mean([1.0 if int(w) == 0 else 0.0 for w in seq])


# ════════════════════════════════════════════════════════════════════════
# 阶段 1：冻结轨迹采集（s10 模型，CPU，无注入大厅）
# ════════════════════════════════════════════════════════════════════════


def _traj_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    import torch  # noqa: PLC0415

    from hsbg.az.train.model import load_checkpoint  # noqa: PLC0415
    from hsbg.az.train.ppo import (CollectConfig, PPOEvaluator,  # noqa: PLC0415
                                   PPOSelfPlayPolicy)

    torch.set_num_threads(int(payload.get("threads", 2)))
    E = load_engine()
    device = "cpu"
    model, meta = load_checkpoint(str(payload["checkpoint"]), device=device)
    ev = PPOEvaluator(model, device=device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=0, opponent="bot", behavior="net",
                        temperature=1.0, max_steps=20000,
                        move_guard=bool(int(payload.get("move_guard", 0))))
    pol = PPOSelfPlayPolicy(model, device=device, config=cfg, eval_fn=ev,
                            seed=0, move_model=False)
    t_lo, t_hi = int(payload["t_lo"]), int(payload["t_hi"])
    out: List[Dict[str, Any]] = []
    for seed in payload["seeds"]:
        seed = int(seed)
        trng = random.Random(seed ^ 0x5EED5EED)
        t_choice = t_lo + trng.randrange(t_hi - t_lo + 1)
        snap = _play_one(E, pol, cfg, seed, t_choice)
        snap["seed"] = seed
        snap["t_choice"] = int(t_choice)
        out.append(snap)
    del model
    return {"snaps": out, "worker": int(payload.get("worker_id", 0))}


def _play_one(E: Any, pol: Any, cfg: Any, seed: int, t_choice: int) -> Dict[str, Any]:
    from hsbg.az.train.common import mask_from_bytes  # noqa: PLC0415

    game = E.Game(seed=int(seed))
    pol.reset()
    pol.reseed(int(seed))
    steps = 0
    last_turn = -1
    t_choice = int(t_choice)
    res: Dict[str, Any] = {
        "ok": False, "fail": "", "target": None,
        "start_state": None, "learner_json": None, "target_json": None,
        "learner_str": 0, "target_str": 0, "target_board_n": 0,
        "records": [], "rank": 0, "over": False, "final_turn": 0,
    }

    def _check_turn() -> None:
        nonlocal last_turn
        t = int(game.turn)
        if t == last_turn:
            return
        last_turn = t
        if t != t_choice:
            return
        pj0 = json.loads(game.player_json(LEARNER_SEAT))
        if not bool(pj0.get("alive", False)) or int(pj0.get("health", 0)) <= 0:
            res["fail"] = "learner_dead"
            return
        res["start_state"] = game.state_json()
        nxt = pj0.get("next_opponent")
        if nxt is None:
            res["fail"] = "ghost_opponent"
            return
        res["target"] = int(nxt)

    while not game.is_over() and steps < int(getattr(cfg, "max_steps", 20000)):
        _check_turn()
        acted = False
        for p in range(N_PLAYERS):
            if game.is_over():
                break
            _check_turn()
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            t = int(game.turn)
            if p == LEARNER_SEAT:
                pre = game.player_json(LEARNER_SEAT)
                dec = pol.decide(game, LEARNER_SEAT)
                a = int(dec.action)
                m = mask_from_bytes(game.legal_mask(LEARNER_SEAT))
                if not (0 <= a < int(m.size) and bool(m[a])):
                    nz = np.flatnonzero(m)
                    a = int(nz[0]) if nz.size else 0
                game.step(LEARNER_SEAT, a)
                if t == t_choice and res["learner_json"] is None:
                    if a == 0 or not game.needs_action(LEARNER_SEAT):
                        post = json.loads(game.player_json(LEARNER_SEAT))
                        pj = json.loads(pre)
                        lb = post.get("last_board") or []
                        if lb:
                            pj["board"] = lb      # 含 end-of-turn 效果的战斗前战团
                        res["learner_json"] = json.dumps(pj)
                        res["learner_str"] = _board_strength(pj)
            else:
                game.bot_play(p)
                if (t == t_choice and res["target"] is not None
                        and p == int(res["target"]) and res["target_json"] is None):
                    tj = game.player_json(p)
                    res["target_json"] = tj
                    pjj = json.loads(tj)
                    res["target_str"] = _board_strength(pjj)
                    res["target_board_n"] = len(pjj.get("board") or [])
        if not acted and not game.is_over():
            break

    res["over"] = bool(game.is_over())
    res["final_turn"] = int(game.turn)
    if res["over"]:
        res["rank"] = int(list(game.placements())[LEARNER_SEAT])
    res["records"] = [[int(r.get("turn", -1)), int(r.get("action", -1)),
                       round(float(r.get("value", 0.0)), 6)] for r in pol.records]
    if res["fail"]:
        res["ok"] = False
    else:
        res["ok"] = bool(res["start_state"] is not None
                         and res["learner_json"] is not None
                         and res["target_json"] is not None)
        if not res["ok"]:
            if res["start_state"] is None:
                res["fail"] = ("ended_before_turn" if not res["over"]
                               else "game_over_before_turn")
            else:
                missing = [k for k in ("start_state", "learner_json", "target_json")
                           if res[k] is None]
                res["fail"] = "missing:" + ",".join(missing)
    return res


def stage_trajectories(args: argparse.Namespace) -> Dict[str, Any]:
    cache_all = os.path.join(args.out_dir, "trajectories.jsonl.gz")
    cache_ok = os.path.join(args.out_dir, "snapshots.jsonl.gz")
    if os.path.isfile(cache_ok) and os.path.isfile(cache_all) and not args.force:
        rows = _jsonl_gz_read(cache_all)
        print(f"[traj] 复用缓存 {cache_all}: {len(rows)} 条")
        return {"rows": rows, "cached": True}

    seeds = [int(args.seed_base) + i for i in range(int(args.max_games))]
    n_workers = max(1, int(args.workers))
    chunks = [seeds[i::n_workers] for i in range(n_workers)]
    payloads = [{"seeds": c, "worker_id": i, "checkpoint": args.checkpoint,
                 "threads": args.threads, "t_lo": args.t_lo, "t_hi": args.t_hi,
                 "move_guard": args.move_guard}
                for i, c in enumerate(chunks) if c]
    t0 = time.time()
    results: List[Dict[str, Any]] = []
    if len(payloads) == 1:
        results.append(_traj_worker(payloads[0]))
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=len(payloads), mp_context=ctx) as ex:
            for r in ex.map(_traj_worker, payloads):
                results.append(r)
    rows: List[Dict[str, Any]] = []
    for r in results:
        rows.extend(r["snaps"])
    rows.sort(key=lambda x: int(x["seed"]))
    ok = [r for r in rows if r.get("ok")]
    _jsonl_gz_write(cache_all, rows)
    _jsonl_gz_write(cache_ok, ok)
    print(f"[traj] {len(rows)} 局 / {len(ok)} 快照有效，{time.time() - t0:.1f}s -> {cache_all}")
    return {"rows": rows, "cached": False, "seconds": time.time() - t0}


# ════════════════════════════════════════════════════════════════════════
# 阶段 2：三种配置 × 快照 的配对战斗
# ════════════════════════════════════════════════════════════════════════


def _battle_worker(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    E = load_engine()
    pool = load_pool(str(payload["human_boards"]))
    n_seed = int(payload["battle_seeds"])
    n_surv = int(payload["survivor_seeds"])
    configs = payload["configs"]
    snaps = _read_jsonl_gz_slice(str(payload["snap_path"]), payload["positions"])
    out: List[Dict[str, Any]] = []

    for snap in snaps:
        seed = int(snap["seed"])
        t = int(snap["t_choice"])
        target = int(snap["target"])
        learner_json = snap["learner_json"]
        target_json = snap["target_json"]
        start_state = snap["start_state"]
        row: Dict[str, Any] = {"seed": seed, "t": t, "target": target,
                               "learner_str": int(snap["learner_str"]),
                               "target_str": int(snap["target_str"]),
                               "rank": int(snap["rank"]), "configs": {}}

        # ---- 对照：同快照、不注入（三配置共享；逐 trial 同 RNG 种子）
        g_ctrl = _battle_game(E, start_state, learner_json, target, target_json,
                              boot_seed=seed)
        ctrl = _trials(_preview(E, g_ctrl, LEARNER_SEAT, target, n_seed, True))
        surv_ctrl = _survivor_series(E, start_state, learner_json, target,
                                     target_json, seed, n_surv)
        row["ctrl"] = {
            "loss": _loss_seq(ctrl["winner"]),
            "win": _win_seq(ctrl["winner"]),
            "tie": _mean([1.0 if w == 2 else 0.0 for w in ctrl["winner"]]),
            "dmg_dealt": _mean(ctrl["dmg_dealt"]),
            "dmg_taken": _mean(ctrl["dmg_taken"]),
            "survivors": _mean(surv_ctrl),
            "trunc": _mean(ctrl["truncated"]),
            "win_seq": ctrl["winner"],
            "dmg_taken_seq": ctrl["dmg_taken"],
            "dmg_dealt_seq": ctrl["dmg_dealt"],
            "surv_seq": [round(x, 3) for x in surv_ctrl],
        }

        for ci, cfg in enumerate(configs):
            name = str(cfg["name"])
            board = pool.sample(t, random.Random(seed * 131 + t * 17 + ci * 7919),
                                str(cfg["sample"]))
            if not board:
                row["configs"][name] = {"ok": False, "reason": "pool_missing"}
                continue
            tier = _tier_of(t)
            # ---- raw：战斗时刻把对手战团替换成人类战团（条件效应 = 100% 命中）
            try:
                g_raw = _battle_game(E, start_state, learner_json, target, target_json,
                                     boot_seed=seed)
                rep = g_raw.inject_board(target, [list(x) for x in board], int(tier))
            except BaseException as e:  # noqa: BLE001
                row["configs"][name] = {"ok": False, "reason": f"exc:{repr(e)[:120]}"}
                continue
            if not bool(rep.get("applied")):
                row["configs"][name] = {"ok": False,
                                        "reason": f"inject:{rep.get('reason')}"}
                continue
            raw = _trials(_preview(E, g_raw, LEARNER_SEAT, target, n_seed, True))
            surv_raw = _survivor_series(E, start_state, learner_json, target,
                                        target_json, seed, n_surv,
                                        board=[list(x) for x in board], tier=tier)
            real = _realistic_arm(E, start_state, learner_json, target, target_json,
                                  board, tier, seed, n_seed)
            row["configs"][name] = {
                "ok": True,
                "board_str": int(sum(int(a) + int(h) for _c, a, h in board)),
                "board_n": len(board),
                "pool_balance_ok": bool(rep.get("pool_balance_ok", True)),
                "raw": {
                    "loss": _loss_seq(raw["winner"]),
                    "win": _win_seq(raw["winner"]),
                    "tie": _mean([1.0 if w == 2 else 0.0 for w in raw["winner"]]),
                    "dmg_dealt": _mean(raw["dmg_dealt"]),
                    "dmg_taken": _mean(raw["dmg_taken"]),
                    "survivors": _mean(surv_raw),
                    "trunc": _mean(raw["truncated"]),
                    "win_seq": raw["winner"],
                    "dmg_taken_seq": raw["dmg_taken"],
                    "dmg_dealt_seq": raw["dmg_dealt"],
                    "surv_seq": [round(x, 3) for x in surv_raw],
                },
                "realistic": real,
            }
        out.append(row)
    return out


def _survivor_series(E: Any, start_state: str, learner_json: str, target: int,
                     target_json: str, base_seed: int, n: int,
                     board: Optional[Sequence[Sequence[int]]] = None,
                     tier: int = 4) -> List[float]:
    """复现 trial i 的 RNG（改容器 seed）后跑 ``n=1``，取最后一帧存活随从数。"""
    out: List[float] = []
    for i in range(max(0, int(n))):
        boot = int(base_seed) ^ ((TRIAL_SEED_K * (i + 1)) & 0xFFFFFFFFFFFFFFFF) ^ TRIAL_SEED_K
        try:
            g = _battle_game(E, start_state, learner_json, target, target_json,
                             boot_seed=boot)
            if board is not None:
                rep = g.inject_board(int(target), [list(x) for x in board], int(tier))
                if not bool(rep.get("applied")):
                    out.append(float("nan"))
                    continue
            res = _preview(E, g, LEARNER_SEAT, target, 1, False)
            out.append(float(_survivors_of(res, 0)))
        except BaseException:  # noqa: BLE001
            out.append(float("nan"))
    return out


def _realistic_arm(E: Any, start_state: str, learner_json: str, target: int,
                   target_json: str, board: Sequence[Sequence[int]], tier: int,
                   seed: int, n_seed: int) -> Dict[str, Any]:
    """训练管线复刻：turn 起点注入（条件在命中）→ 该座位 bot 行动 → 战斗。"""
    try:
        g = E.Game.from_json(start_state)
        rep = g.inject_board(int(target), [list(x) for x in board], int(tier))
    except BaseException as e:  # noqa: BLE001
        return {"ok": False, "reason": f"exc:{repr(e)[:100]}"}
    if not bool(rep.get("applied")):
        return {"ok": False, "reason": f"inject_turn_start:{rep.get('reason')}"}
    injected_str = int(sum(int(a) + int(h) for _c, a, h in board))
    target_after_json = None
    guard = 0
    while not g.is_over() and target_after_json is None and guard < 64:
        acted = False
        for p in range(1, N_PLAYERS):
            if g.is_over() or target_after_json is not None:
                break
            if not g.needs_action(p):
                continue
            acted = True
            guard += 1
            g.bot_play(p)
            if p == int(target):
                target_after_json = g.player_json(int(target))
                break
        if not acted:
            break
    if target_after_json is None:
        return {"ok": False, "reason": "target_no_turn"}
    pj = json.loads(target_after_json)
    after_str = _board_strength(pj)
    try:
        gb = _battle_game(E, start_state, learner_json, target, target_after_json,
                          boot_seed=seed)
        r = _trials(_preview(E, gb, LEARNER_SEAT, target, n_seed, True))
    except BaseException as e:  # noqa: BLE001
        return {"ok": False, "reason": f"battle:{repr(e)[:100]}"}
    return {
        "ok": True,
        "injected_str": injected_str,
        "after_str": after_str,
        "dilution": (float(after_str) / float(injected_str)) if injected_str > 0 else 0.0,
        "board_n_after": len(pj.get("board") or []),
        "loss": _loss_seq(r["winner"]),
        "win": _win_seq(r["winner"]),
        "tie": _mean([1.0 if w == 2 else 0.0 for w in r["winner"]]),
        "dmg_dealt": _mean(r["dmg_dealt"]),
        "dmg_taken": _mean(r["dmg_taken"]),
        "trunc": _mean(r["truncated"]),
        "win_seq": r["winner"],
        "dmg_taken_seq": r["dmg_taken"],
        "dmg_dealt_seq": r["dmg_dealt"],
    }


def stage_battles(args: argparse.Namespace) -> Dict[str, Any]:
    cache = os.path.join(args.out_dir, "battles.json")
    if os.path.isfile(cache) and not args.force:
        data = json.load(open(cache))
        print(f"[battle] 复用缓存 {cache}: {len(data['rows'])} 快照")
        return data
    snap_path = os.path.join(args.out_dir, "snapshots.jsonl.gz")
    all_snaps = _jsonl_gz_read(snap_path)
    idx = list(range(len(all_snaps)))
    n_workers = max(1, int(args.workers))
    chunks = [idx[i::n_workers] for i in range(n_workers)]
    payloads = [{"positions": c, "snap_path": snap_path, "configs": list(CONFIGS),
                 "human_boards": args.human_boards,
                 "battle_seeds": args.battle_seeds,
                 "survivor_seeds": args.survivor_seeds}
                for c in chunks if c]
    t0 = time.time()
    rows: List[Dict[str, Any]] = []
    if len(payloads) == 1:
        for p in payloads:
            rows.extend(_battle_worker(p))
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=len(payloads), mp_context=ctx) as ex:
            for rr in ex.map(_battle_worker, payloads):
                rows.extend(rr)
    rows.sort(key=lambda x: int(x["seed"]))
    data = {"rows": rows, "seconds": time.time() - t0}
    os.makedirs(args.out_dir, exist_ok=True)
    json.dump(data, open(cache, "w"), ensure_ascii=False)
    print(f"[battle] {len(rows)} 快照 × {len(CONFIGS)} 配置，{time.time() - t0:.1f}s -> {cache}")
    return data


# ════════════════════════════════════════════════════════════════════════
# 阶段 3：保真度配对消融（可信完整快照：board-only vs full state）
# ════════════════════════════════════════════════════════════════════════


def load_trusted_frames(path: str, t_lo: int, t_hi: int) -> List[Dict[str, Any]]:
    frames: List[Dict[str, Any]] = []
    if not os.path.isdir(path):
        return frames
    for fn in sorted(os.listdir(path)):
        if not (fn.endswith(".json.gz") or fn.endswith(".json")):
            continue
        fp = os.path.join(path, fn)
        try:
            opener = gzip.open if fn.endswith(".gz") else open
            with opener(fp, "rt", encoding="utf-8") as f:
                d = json.load(f)
        except BaseException:  # noqa: BLE001
            continue
        src = os.path.basename(fn)
        for i, fr in enumerate(d.get("frames") or []):
            t = int(fr.get("turn", 0))
            if not (t_lo <= t <= t_hi):
                continue
            pj = fr.get("player") or {}
            if not pj.get("board"):
                continue
            frames.append({"file": src, "idx": i, "turn": t,
                           "seat": int(fr.get("seat", -1)), "player": pj})
    return frames


def _frame_hidden_stats(pj: Dict[str, Any]) -> Dict[str, Any]:
    b = pj.get("board") or []
    golden = 0
    kw_bits = 0
    counters = 0
    attached = 0
    for m in b:
        golden += int(bool(m.get("golden")))
        kw_bits += int(m.get("kw", 0)) + int(m.get("bonus_kw", 0))
        counters += int(int(m.get("counter", 0)) != 0)
        attached += len(m.get("attached") or [])
    return {
        "board_n": len(b),
        "board_str": _board_strength(pj),
        "golden": golden,
        "kw_bits": kw_bits,
        "minions_with_counter": counters,
        "attached": attached,
        "hand_n": len(pj.get("hand") or []),
        "shop_n": len(pj.get("shop") or []),
        "tier": int(pj.get("tier", 0) or 0),
    }


def _fidelity_worker(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    E = load_engine()
    golden2base = _golden_to_base_map()
    snaps_by_turn: Dict[int, List[Dict[str, Any]]] = {}
    for s in _jsonl_gz_read(str(payload["snap_path"])):
        snaps_by_turn.setdefault(int(s["t_choice"]), []).append(s)
    turns_all = sorted(snaps_by_turn)
    n_seed = int(payload["battle_seeds"])
    n_surv = int(payload["survivor_seeds"])
    out: List[Dict[str, Any]] = []
    for i, fr in enumerate(payload["frames"]):
        t = int(fr["turn"])
        cands = snaps_by_turn.get(t) or []
        if not cands and turns_all:
            near = min(turns_all, key=lambda k: abs(k - t))
            cands = snaps_by_turn.get(near) or []
        if not cands:
            out.append({"ok": False, "reason": "no_container"})
            continue
        cont = cands[i % len(cands)]
        tgt = int(cont["target"])          # 容器里该 turn 存活的对位座位
        pj = fr["player"]
        board_base = [[int(golden2base.get(int(m["card"]), int(m["card"]))),
                       int(m["atk"]), int(m["hp"])] for m in (pj.get("board") or [])]
        board_obs = [[int(m["card"]), int(m["atk"]), int(m["hp"])]
                     for m in (pj.get("board") or [])]
        tier = int(pj.get("tier", 4) or 4)
        boot = int(cont["seed"]) ^ (0x51ED + i * 7919)
        fj = json.dumps(pj)
        stats = _frame_hidden_stats(pj)

        try:
            # arm 1: 完整状态注入（同一帧的完整 Player：board+hand+counters+golden）
            g_full = _battle_game(E, cont["start_state"], cont["learner_json"], tgt, fj,
                                  boot_seed=boot)
            # arm 2(A)：同一帧状态，只把 board 换成 board-only（去 golden/keywords/counters）
            g_bo = _battle_game(E, cont["start_state"], cont["learner_json"], tgt, fj,
                                boot_seed=boot)
            rep_bo = g_bo.inject_board(tgt, board_base, tier)
            # arm 2(B)：真实管线 —— 当前局座位 + 只注入人类观测 board（无 hand/hero 真值）
            g_pipe = _battle_game(E, cont["start_state"], cont["learner_json"], tgt,
                                  cont["target_json"], boot_seed=boot)
            rep_pipe = g_pipe.inject_board(tgt, board_obs, tier)
        except BaseException as e:  # noqa: BLE001
            out.append({"ok": False, "reason": f"exc:{repr(e)[:100]}"})
            continue
        if not bool(rep_bo.get("applied")) or not bool(rep_pipe.get("applied")):
            out.append({"ok": False,
                        "reason": f"inject:bo={rep_bo.get('reason')},"
                                  f"pipe={rep_pipe.get('reason')}"})
            continue
        full = _trials(_preview(E, g_full, LEARNER_SEAT, tgt, n_seed, True))
        bo = _trials(_preview(E, g_bo, LEARNER_SEAT, tgt, n_seed, True))
        pipe = _trials(_preview(E, g_pipe, LEARNER_SEAT, tgt, n_seed, True))
        surv_full = _survivor_series(E, cont["start_state"], cont["learner_json"], tgt,
                                     fj, boot, n_surv)
        surv_bo = _survivor_series(E, cont["start_state"], cont["learner_json"], tgt,
                                   fj, boot, n_surv, board=board_base, tier=tier)
        out.append({
            "ok": True, "file": fr["file"], "idx": int(fr["idx"]), "turn": t,
            "stats": stats,
            "full": {"loss": _loss_seq(full["winner"]),
                     "win": _win_seq(full["winner"]),
                     "tie": _mean([1.0 if w == 2 else 0.0 for w in full["winner"]]),
                     "dmg_taken": _mean(full["dmg_taken"]),
                     "dmg_dealt": _mean(full["dmg_dealt"]),
                     "survivors": _mean(surv_full)},
            "board_only": {"loss": _loss_seq(bo["winner"]),
                           "win": _win_seq(bo["winner"]),
                           "tie": _mean([1.0 if w == 2 else 0.0 for w in bo["winner"]]),
                           "dmg_taken": _mean(bo["dmg_taken"]),
                           "dmg_dealt": _mean(bo["dmg_dealt"]),
                           "survivors": _mean(surv_bo)},
            "board_only_pipeline": {"loss": _loss_seq(pipe["winner"]),
                                    "win": _win_seq(pipe["winner"]),
                                    "tie": _mean([1.0 if w == 2 else 0.0 for w in pipe["winner"]]),
                                    "dmg_taken": _mean(pipe["dmg_taken"]),
                                    "dmg_dealt": _mean(pipe["dmg_dealt"])},
        })
    return out


def stage_fidelity(args: argparse.Namespace) -> Dict[str, Any]:
    cache = os.path.join(args.out_dir, "fidelity.json")
    if os.path.isfile(cache) and not args.force:
        data = json.load(open(cache))
        print(f"[fid] 复用缓存 {cache}: {len(data['rows'])} 帧")
        return data
    frames = load_trusted_frames(args.mirror_snaps, args.t_lo, args.t_hi)
    print(f"[fid] 可信完整快照帧: {len(frames)}（t∈[{args.t_lo},{args.t_hi}]）")
    snap_path = os.path.join(args.out_dir, "snapshots.jsonl.gz")
    n_workers = max(1, int(args.workers))
    chunks = [frames[i::n_workers] for i in range(n_workers)]
    payloads = [{"frames": c, "snap_path": snap_path,
                 "battle_seeds": args.battle_seeds,
                 "survivor_seeds": min(int(args.survivor_seeds), 8)}
                for c in chunks if c]
    t0 = time.time()
    rows: List[Dict[str, Any]] = []
    if len(payloads) == 1:
        for p in payloads:
            rows.extend(_fidelity_worker(p))
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=len(payloads), mp_context=ctx) as ex:
            for rr in ex.map(_fidelity_worker, payloads):
                rows.extend(rr)
    ok = [r for r in rows if r.get("ok")]
    data = {"rows": ok, "attempted": len(rows), "frames": len(frames),
            "seconds": time.time() - t0}
    os.makedirs(args.out_dir, exist_ok=True)
    json.dump(data, open(cache, "w"), ensure_ascii=False)
    print(f"[fid] {len(ok)}/{len(rows)} 帧完成，{time.time() - t0:.1f}s -> {cache}")
    return data


# ════════════════════════════════════════════════════════════════════════
# 阶段 4：暴露（投递 / 命中）
# ════════════════════════════════════════════════════════════════════════


def _read_history(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except BaseException:  # noqa: BLE001
                continue
    if not rows:
        return {}
    header = rows[0].get("args") or {}
    iters = [r for r in rows if "iter" in r]
    return {"header": header, "iters": iters}


def _turns_per_game_estimate(hist: Dict[str, Any]) -> float:
    it = hist.get("iters") or []
    h = hist.get("header") or {}
    seats = int(h.get("human_board_seats", 0) or 0)
    p = float(h.get("human_board_p", 0.0) or 0.0)
    if not it or seats <= 0 or p <= 0:
        return 0.0
    att = sum(float((r.get("collect") or {}).get("human_board_attempt", 0) or 0) for r in it)
    games = sum(float((r.get("collect") or {}).get("games", 0) or 0) for r in it)
    if games <= 0:
        return 0.0
    return att / games / max(1e-9, seats * p)


def _delivery_stats(hist: Dict[str, Any]) -> Dict[str, Any]:
    if not hist:
        return {}
    it = hist["iters"]
    h = hist["header"]
    keys = ("human_board_attempt", "human_board_applied", "human_board_rejected",
            "human_board_missing", "human_board_errors", "human_board_skipped_by_mirror",
            "mirror_attempt", "mirror_applied", "mirror_rejected", "mirror_missing",
            "games", "decisions", "truncated_games", "forced_end_turns", "records")
    sums: Dict[str, float] = {}
    for r in it:
        c = r.get("collect") or {}
        for k in keys:
            if c.get(k) is not None:
                sums[k] = sums.get(k, 0.0) + float(c[k])
    n = max(1, len(it))
    games = max(1.0, sums.get("games", 0.0))
    out = {
        "iters": int(len(it)),
        "games": float(sums.get("games", 0.0)),
        "decisions": float(sums.get("decisions", 0.0)),
        "per_iter": {k: (sums.get(k, 0.0) / n) for k in keys if k in sums},
        "lam_header": h.get("lam"),
        "lam_ppo_config": (it[-1].get("ppo", {}).get("config") or {}).get("lam"),
        "gamma": (it[-1].get("ppo", {}).get("config") or {}).get("gamma"),
        "human_board_p": h.get("human_board_p"),
        "human_board_seats": h.get("human_board_seats"),
        "human_board_sample": h.get("human_board_sample"),
        "mirror_seat_random": h.get("mirror_seat_random"),
        "mirror_seats": h.get("mirror_seats"),
        "mirror_p": h.get("mirror_p"),
        "turns_per_game_est": _turns_per_game_estimate(hist),
        "truncated_games_per_iter": sums.get("truncated_games", 0.0) / n,
        "forced_end_turns_per_iter": sums.get("forced_end_turns", 0.0) / n,
    }
    for pre in ("human_board", "mirror"):
        a = sums.get(f"{pre}_attempt", 0.0)
        ap = sums.get(f"{pre}_applied", 0.0)
        if a > 0:
            out[f"{pre}_apply_rate"] = ap / a
        out[f"{pre}_applied_per_iter"] = ap / n
        out[f"{pre}_applied_per_game"] = ap / games
    return out


def stage_exposure(args: argparse.Namespace,
                   run_hists: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    delivery = {name: _delivery_stats(h) for name, h in run_hists.items() if h}
    base = delivery.get("s10") or {}
    mirror_rate = float(base.get("mirror_apply_rate", 0.55) or 0.55)
    mirror_seats = int(base.get("mirror_seats", 3) or 3)
    mirror_p = float(base.get("mirror_p", 0.3) or 0.3)
    snaps = _jsonl_gz_read(os.path.join(args.out_dir, "snapshots.jsonl.gz"))
    targets = [int(s["target"]) for s in snaps]
    t_choices = [int(s["t_choice"]) for s in snaps]
    rng = random.Random(20261031)
    draws = 300
    out: Dict[str, Any] = {
        "mirror_competition": {"seats": mirror_seats, "p": mirror_p,
                               "apply_rate": mirror_rate},
        "n_snapshots": len(targets),
        "delivery": delivery,
        "configs": {},
    }
    for ci, cfg in enumerate(CONFIGS):
        c, p, name = int(cfg["seats"]), float(cfg["p"]), str(cfg["name"])
        run = delivery.get(name) or base
        human_rate = float(run.get("human_board_apply_rate", 0.60) or 0.60)
        per_snap: List[float] = []
        per_turn: Dict[int, List[float]] = {}
        single: List[int] = []
        single_rng = random.Random(0xC0FFEE + ci)
        for tgt, t in zip(targets, t_choices):
            h = 0
            for _ in range(draws):
                mset = set(rng.sample(range(1, N_PLAYERS), mirror_seats))
                mir_applied = {s for s in mset if rng.random() < mirror_p * mirror_rate}
                applied = set()
                for s in set(rng.sample(range(1, N_PLAYERS), c)):
                    if s in mir_applied:
                        continue
                    if rng.random() < p and rng.random() < human_rate:
                        applied.add(s)
                h += int(tgt in applied)
            p_i = h / float(draws)
            per_snap.append(p_i)
            per_turn.setdefault(t, []).append(p_i)
            # 额外：一次独立抽签的 per-snapshot 二值暴露（“该快照位置实际是否遇到注入席”）
            ms = set(single_rng.sample(range(1, N_PLAYERS), mirror_seats))
            ma = {s for s in ms if single_rng.random() < mirror_p * mirror_rate}
            ap = set()
            for s in set(single_rng.sample(range(1, N_PLAYERS), c)):
                if s in ma:
                    continue
                if single_rng.random() < p and single_rng.random() < human_rate:
                    ap.add(s)
            single.append(int(tgt in ap))
        out["configs"][name] = {
            "seats": c, "p": p, "sample": str(cfg["sample"]),
            "human_apply_rate": human_rate,
            "hit_prob_per_learner_turn": float(np.mean(per_snap)) if per_snap else 0.0,
            "hit_prob_ci": _bootstrap_ci(per_snap, seed=7 + ci),
            "per_turn": {str(t): float(np.mean(v)) for t, v in sorted(per_turn.items())},
            "single_draw": single,
            "single_draw_hits": int(sum(single)),
            "single_draw_hit_ratio": float(np.mean(single)) if single else 0.0,
            "snapshot_targets": targets,
        }
    turns = float(base.get("turns_per_game_est", 0.0) or 0.0)
    if turns > 0:
        for name, v in out["configs"].items():
            ph = float(v["hit_prob_per_learner_turn"])
            v["reach_per_game_approx"] = 1.0 - (1.0 - ph) ** turns
            v["turns_per_game"] = turns
            # 自洽校验：模拟命中率 × 7 个对手座位 × 每局 turn 数 ≈ 实测 applied/game
            v["implied_applied_per_game"] = ph * 7.0 * turns
            emp = ((delivery.get(name) or {}).get("human_board_applied_per_game"))
            if emp:
                v["observed_applied_per_game"] = float(emp)
    return out


# ════════════════════════════════════════════════════════════════════════
# 阶段 5：信号传播（GAE 信用权重 + 截断/掩码）
# ════════════════════════════════════════════════════════════════════════


def compute_gae_np(rewards: np.ndarray, values: np.ndarray, dones: np.ndarray,
                   gamma: float = 1.0, lam: float = 0.995) -> np.ndarray:
    """与 ``hsbg.az.train.ppo.compute_gae`` 逐位一致的独立实现（不依赖 torch）。"""
    r = np.asarray(rewards, dtype=np.float64).reshape(-1)
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    d = np.asarray(dones, dtype=np.float64).reshape(-1)
    n = int(r.size)
    adv = np.zeros(n, dtype=np.float64)
    last = 0.0
    nextv = 0.0
    for t in range(n - 1, -1, -1):
        if d[t] > 0.5:
            nextv = 0.0
            last = 0.0
        delta = float(r[t]) + float(gamma) * nextv - float(v[t])
        last = delta + float(gamma) * float(lam) * last
        adv[t] = last
        nextv = float(v[t])
    return adv


def _game_credit(records: List[List[Any]], rank: int,
                 lams: Sequence[float]) -> Dict[str, Any]:
    n = len(records)
    if n <= 0 or not (1 <= int(rank) <= N_PLAYERS):
        return {"ok": False}
    turns = np.asarray([int(r[0]) for r in records], dtype=np.int64)
    actions = np.asarray([int(r[1]) for r in records], dtype=np.int64)
    values = np.asarray([float(r[2]) for r in records], dtype=np.float64)
    R = float(RANK_UTILITY[int(rank) - 1])
    rewards = np.zeros(n, dtype=np.float64)
    rewards[-1] = R
    dones = np.zeros(n, dtype=np.float64)
    dones[-1] = 1.0
    out: Dict[str, Any] = {"ok": True, "n": int(n), "rank": int(rank), "R": R,
                           "turns": turns, "actions": actions, "values": values,
                           "by_lambda": {}}
    for lam in lams:
        gl = float(lam)
        adv = compute_gae_np(rewards, values, dones, gamma=1.0, lam=gl)
        w = gl ** np.arange(n - 1, -1, -1, dtype=np.float64)
        dR = R - float(values[-1])
        aR = w * dR
        out["by_lambda"][f"{lam:g}"] = {"w": w, "adv": adv, "adv_R": aR,
                                        "adv_V": adv - aR, "dR": dR}
    return out


def stage_signal(args: argparse.Namespace,
                 run_hists: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    lams = (0.995, 0.95)
    snaps = [s for s in _jsonl_gz_read(os.path.join(args.out_dir, "snapshots.jsonl.gz"))
             if s.get("records")]
    per = [_game_credit(s["records"], int(s.get("rank", 0)), lams) for s in snaps]
    per = [p for p in per if p.get("ok")]
    out: Dict[str, Any] = {"games": len(per), "lambda_sensitivity": list(lams)}

    def _collect(mask_fn, lam: str) -> Dict[str, Any]:
        w_all: List[float] = []
        share: List[float] = []
        abs_a: List[float] = []
        abs_ar: List[float] = []
        for p in per:
            d = p["by_lambda"][lam]
            sel = np.asarray(mask_fn(p), dtype=bool)
            if not np.any(sel):
                continue
            w_all.extend(d["w"][sel].tolist())
            ar = np.abs(d["adv_R"][sel])
            av = np.abs(d["adv_V"][sel])
            share.extend((ar / np.maximum(1e-12, ar + av)).tolist())
            abs_a.extend(np.abs(d["adv"][sel]).tolist())
            abs_ar.extend(ar.tolist())
        return {"w": _pct(w_all), "terminal_share": _pct(share),
                "abs_adv": _pct(abs_a), "abs_adv_terminal": _pct(abs_ar)}

    for lam in (0.995, 0.95):
        key = f"{lam:g}"
        out[f"lambda_{key}"] = {
            "early_t_le_8": _collect(lambda p: p["turns"] <= 8, key),
            "t7_any": _collect(lambda p: p["turns"] == 7, key),
            "t7_upgrade": _collect(lambda p: (p["turns"] == 7) & (p["actions"] == UPGRADE_ACTION), key),
            "all": _collect(lambda p: np.ones(len(p["turns"]), dtype=bool), key),
        }
    n_t7u = 0
    k_t7u: List[int] = []
    for p in per:
        idx = np.flatnonzero((p["turns"] == 7) & (p["actions"] == UPGRADE_ACTION))
        if idx.size:
            n_t7u += 1
            k_t7u.extend(idx.tolist())
    out["t7_upgrade_games"] = int(n_t7u)
    out["t7_upgrade_game_ratio"] = float(n_t7u / max(1, len(per)))
    out["t7_upgrade_decision_index"] = _pct(k_t7u)
    out["game_length_decisions"] = _pct([p["n"] for p in per])
    out["t7_decision_index"] = _pct([int(np.flatnonzero(p["turns"] == 7)[0])
                                     for p in per if np.any(p["turns"] == 7)])
    out["rank_utility"] = _pct([p["R"] for p in per])

    hist = run_hists.get("s10") or {}
    if hist:
        it = hist["iters"]
        h = hist["header"]
        dec = sum(float((r.get("collect") or {}).get("decisions", 0) or 0) for r in it)
        games = sum(float((r.get("collect") or {}).get("games", 0) or 0) for r in it)
        trunc = sum(float((r.get("collect") or {}).get("truncated_games", 0) or 0) for r in it)
        forced = sum(float((r.get("collect") or {}).get("forced_end_turns", 0) or 0) for r in it)
        cfg = (it[-1].get("ppo", {}) or {}).get("config") or {}
        kl = [((r.get("ppo", {}).get("epochs") or [{}])[-1].get("approx_kl", 0.0) or 0.0)
              for r in it]
        ent = [((r.get("ppo", {}).get("epochs") or [{}])[-1].get("entropy", 0.0) or 0.0)
               for r in it]
        pl = [abs(((r.get("ppo", {}).get("epochs") or [{}])[-1].get("policy_loss", 0.0) or 0.0))
              for r in it]
        out["training"] = {
            "iters": int(len(it)),
            "decisions": dec,
            "games": games,
            "decisions_per_game": dec / max(1.0, games),
            "truncated_games": trunc,
            "truncated_ratio": trunc / max(1.0, games),
            "forced_end_turns": forced,
            "forced_ratio_of_decisions": forced / max(1.0, dec),
            "lam_header_arg": h.get("lam"),
            "lam_ppo_config_logged": cfg.get("lam"),
            "gamma_ppo_config_logged": cfg.get("gamma"),
            "lr": cfg.get("lr"),
            "pi_coef": cfg.get("pi_coef"),
            "value_loss": cfg.get("value_loss"),
            "approx_kl_mean": float(np.mean(kl)) if kl else None,
            "entropy_first5": float(np.mean(ent[:5])) if ent else None,
            "entropy_last5": float(np.mean(ent[-5:])) if ent else None,
            "policy_loss_abs_mean": float(np.mean(pl)) if pl else None,
        }
    return out


# ════════════════════════════════════════════════════════════════════════
# 阶段 6：汇总 / 预注册判据 / 分支
# ════════════════════════════════════════════════════════════════════════


def summarize_battles(data: Dict[str, Any]) -> Dict[str, Any]:
    rows = data["rows"]
    out: Dict[str, Any] = {"n_snapshots": len(rows), "configs": {}}
    for cfg in CONFIGS:
        name = cfg["name"]
        d_loss: List[float] = []
        d_taken: List[float] = []
        d_dealt: List[float] = []
        d_surv: List[float] = []
        d_loss_real: List[float] = []
        d_taken_real: List[float] = []
        raw_loss: List[float] = []
        ctrl_loss: List[float] = []
        real_loss: List[float] = []
        raw_taken: List[float] = []
        ctrl_taken: List[float] = []
        raw_surv: List[float] = []
        ctrl_surv: List[float] = []
        dilution: List[float] = []
        per_turn: Dict[int, Dict[str, List[float]]] = {}
        applied = 0
        for r in rows:
            c = (r.get("configs") or {}).get(name) or {}
            if not c.get("ok"):
                continue
            applied += 1
            ctrl, raw = r["ctrl"], c["raw"]
            ctrl_loss.append(float(ctrl["loss"]))
            raw_loss.append(float(raw["loss"]))
            raw_taken.append(float(raw["dmg_taken"]))
            ctrl_taken.append(float(ctrl["dmg_taken"]))
            raw_surv.append(float(raw["survivors"]))
            ctrl_surv.append(float(ctrl["survivors"]))
            d_loss.append(float(raw["loss"]) - float(ctrl["loss"]))
            d_taken.append(float(raw["dmg_taken"]) - float(ctrl["dmg_taken"]))
            d_dealt.append(float(raw["dmg_dealt"]) - float(ctrl["dmg_dealt"]))
            d_surv.append(float(raw["survivors"]) - float(ctrl["survivors"]))
            t = int(r["t"])
            pt = per_turn.setdefault(t, {"d_loss": [], "learner_str": [], "board_str": []})
            pt["d_loss"].append(float(raw["loss"]) - float(ctrl["loss"]))
            pt["learner_str"].append(float(r["learner_str"]))
            pt["board_str"].append(float(c["board_str"]))
            real = c.get("realistic") or {}
            if real.get("ok"):
                real_loss.append(float(real["loss"]))
                d_loss_real.append(float(real["loss"]) - float(ctrl["loss"]))
                d_taken_real.append(float(real["dmg_taken"]) - float(ctrl["dmg_taken"]))
                if float(real.get("injected_str", 0)) > 0:
                    dilution.append(float(real.get("dilution", 0.0)))
        n_real = len(d_loss_real)
        out["configs"][name] = {
            "desc": cfg["desc"],
            "applied_snapshots": int(applied),
            "ctrl_loss_mean": float(np.mean(ctrl_loss)) if ctrl_loss else 0.0,
            "raw_loss_mean": float(np.mean(raw_loss)) if raw_loss else 0.0,
            "ctrl_dmg_taken_mean": float(np.mean(ctrl_taken)) if ctrl_taken else 0.0,
            "raw_dmg_taken_mean": float(np.mean(raw_taken)) if raw_taken else 0.0,
            "ctrl_survivors_mean": float(np.mean(ctrl_surv)) if ctrl_surv else 0.0,
            "raw_survivors_mean": float(np.mean(raw_surv)) if raw_surv else 0.0,
            "delta_loss_raw_pp": float(100 * np.mean(d_loss)) if d_loss else 0.0,
            "delta_loss_raw": _bootstrap_ci(d_loss, seed=11),
            "delta_dmg_taken_raw": _bootstrap_ci(d_taken, seed=12),
            "delta_dmg_dealt_raw": _bootstrap_ci(d_dealt, seed=13),
            "delta_survivors_raw": _bootstrap_ci(d_surv, seed=14),
            "sign_p_loss": _sign_test_p(d_loss),
            "sign_p_dmg_taken": _sign_test_p(d_taken),
            "realistic_applied_ratio": (float(n_real) / float(applied)) if applied else 0.0,
            "realistic_loss_mean": float(np.mean(real_loss)) if real_loss else None,
            "delta_loss_realistic": _bootstrap_ci(d_loss_real, seed=15),
            "delta_dmg_taken_realistic": _bootstrap_ci(d_taken_real, seed=16),
            "delta_loss_realistic_dose": (
                (float(n_real) / float(applied)) * float(np.mean(d_loss_real))
                if n_real and applied else None),
            "dilution_post_bot": _pct(dilution),
            "n_realistic": n_real,
            "per_turn": {
                str(t): {"n": len(v["d_loss"]),
                         "delta_loss_pp": float(100 * np.mean(v["d_loss"])),
                         "learner_str_p50": float(np.median(v["learner_str"])),
                         "injected_board_str_p50": float(np.median(v["board_str"]))}
                for t, v in sorted(per_turn.items())},
        }
    return out


def summarize_fidelity(data: Dict[str, Any]) -> Dict[str, Any]:
    rows = [r for r in data.get("rows", []) if r.get("ok")]
    if not rows:
        return {"n": 0, "available": False}
    d_loss = [float(r["full"]["loss"]) - float(r["board_only"]["loss"]) for r in rows]
    d_taken = [float(r["full"]["dmg_taken"]) - float(r["board_only"]["dmg_taken"]) for r in rows]
    d_surv = [float(r["board_only"]["survivors"]) - float(r["full"]["survivors"]) for r in rows]
    pl = [float(r["full"]["loss"]) - float(r["board_only_pipeline"]["loss"])
          for r in rows]
    pt = [float(r["full"]["dmg_taken"]) - float(r["board_only_pipeline"]["dmg_taken"])
          for r in rows]
    stats = [r["stats"] for r in rows]
    return {
        "n": len(rows),
        "available": True,
        "full_loss_mean": float(np.mean([r["full"]["loss"] for r in rows])),
        "board_only_loss_mean": float(np.mean([r["board_only"]["loss"] for r in rows])),
        "board_only_pipeline_loss_mean": float(np.mean(
            [r["board_only_pipeline"]["loss"] for r in rows])),
        # 同一帧状态，只剥掉 board 内部隐藏状态（golden/keywords/counters/attachments）
        "delta_loss_full_minus_board_only": _bootstrap_ci(d_loss, seed=21),
        "delta_dmg_taken_full_minus_board_only": _bootstrap_ci(d_taken, seed=22),
        "delta_survivors_board_only_minus_full": _bootstrap_ci(d_surv, seed=23),
        # 真实管线：完整状态 vs“当前局座位 + 只有人类观测 board”
        "delta_loss_pipeline": _bootstrap_ci(pl, seed=24),
        "delta_dmg_taken_pipeline": _bootstrap_ci(pt, seed=25),
        "sign_p_loss": _sign_test_p(d_loss),
        "sign_p_loss_pipeline": _sign_test_p(pl),
        "hidden_state": {
            "board_n": _pct([s["board_n"] for s in stats]),
            "board_str": _pct([s["board_str"] for s in stats]),
            "golden_minions": _pct([s["golden"] for s in stats]),
            "kw_bits": _pct([s["kw_bits"] for s in stats]),
            "minions_with_counter": _pct([s["minions_with_counter"] for s in stats]),
            "attached": _pct([s["attached"] for s in stats]),
            "hand_n": _pct([s["hand_n"] for s in stats]),
            "shop_n": _pct([s["shop_n"] for s in stats]),
        },
        "frac_frames_golden": float(np.mean([1.0 if s["golden"] > 0 else 0.0 for s in stats])),
        "frac_frames_any_kw": float(np.mean([1.0 if s["kw_bits"] > 0 else 0.0 for s in stats])),
        "frac_frames_hand": float(np.mean([1.0 if s["hand_n"] > 0 else 0.0 for s in stats])),
        "caveat": ("可信完整快照来自**我们自己的** EOT 状态（有隐藏真值）；真实人类观测没有 "
                   "golden/keywords/counters/hand，真实人类的隐藏差距**不可测（数据不足）**。"
                   "本消融只给出“board-only 会丢多少信息”的机制量级。"),
    }


def decide_branch(pressure: Dict[str, Any], fidelity: Dict[str, Any],
                  signal: Dict[str, Any]) -> Dict[str, Any]:
    """**预注册判据**（跑数之前写死；三条分支按顺序判定）。

    P1（压力有效）：任一配置满足 ``Δ败率(raw) ≥ +0.05`` 且 95% CI 下界 > 0，或
        ``Δ承受伤害(raw) ≥ +1.0`` 且 95% CI 下界 > 0。
    F1（保真度实质差异）：可信完整快照上 ``Δ败率(full−board_only) ≥ +0.05`` 且 CI 下界 > 0，
        或 ``Δ承受伤害 ≥ +1.0`` 且 CI 下界 > 0。
    C1（早期信号被压没）：λ=0.995 下 ``median GAE 权重(t≤8) < 0.10``
        或 ``median 终端分量占比(t≤8) < 0.10``。

    判定顺序：``not P1 -> (a)``；``C1 -> (b)``；``F1 -> (c)``；否则 ``(b)``。
    （若 P1 与 F1 同时成立，优先 (b)：早期信用都没了，补保真度也不会被学到。）
    """
    reasons: List[str] = []
    p1 = False
    p_detail = {}
    for name, c in (pressure.get("configs") or {}).items():
        dl, dt = c["delta_loss_raw"], c["delta_dmg_taken_raw"]
        loss_ok = bool(dl["mean"] >= 0.05 and dl["ci_low"] > 0.0)
        dmg_ok = bool(dt["mean"] >= 1.0 and dt["ci_low"] > 0.0)
        p_detail[name] = {"loss_ok": loss_ok, "dmg_ok": dmg_ok,
                          "P1": bool(loss_ok or dmg_ok),
                          "delta_loss_pp": round(100 * dl["mean"], 2),
                          "delta_loss_ci_pp": [round(100 * dl["ci_low"], 2),
                                               round(100 * dl["ci_high"], 2)],
                          "delta_dmg_taken": dt["mean"],
                          "delta_dmg_taken_ci": [dt["ci_low"], dt["ci_high"]]}
        p1 = p1 or bool(loss_ok or dmg_ok)
    if not p1:
        reasons.append("P1 未满足：三种注入配置的条件败率提升均 < +5pp（或 CI 跨 0），"
                       "期望承受伤害提升 < +1.0。")
    f1 = False
    f_detail: Dict[str, Any] = {"F1": False, "note": "无可用可信完整快照 -> 数据不足"}
    if fidelity.get("available"):
        dl = fidelity["delta_loss_pipeline"]
        dt = fidelity["delta_dmg_taken_pipeline"]
        dl_i = fidelity["delta_loss_full_minus_board_only"]
        f1 = bool((dl["mean"] >= 0.05 and dl["ci_low"] > 0.0)
                  or (dt["mean"] >= 1.0 and dt["ci_low"] > 0.0))
        f_detail = {"loss_mean": dl["mean"], "loss_ci": [dl["ci_low"], dl["ci_high"]],
                    "dmg_mean": dt["mean"], "dmg_ci": [dt["ci_low"], dt["ci_high"]],
                    "loss_mean_same_frame": dl_i["mean"],
                    "loss_ci_same_frame": [dl_i["ci_low"], dl_i["ci_high"]],
                    "F1": f1}
    c1 = False
    c_detail: Dict[str, Any] = {"C1": False, "note": "无可用轨迹记录 -> 数据不足"}
    sig = signal.get("lambda_0.995") or {}
    early = sig.get("early_t_le_8") or {}
    if (early.get("w") or {}).get("n", 0) > 0:
        med_w = float(early["w"]["p50"])
        med_share = float((early.get("terminal_share") or {}).get("p50", 0.0))
        c1 = bool(med_w < 0.10 or med_share < 0.10)
        c_detail = {"median_w_early": med_w, "median_terminal_share_early": med_share,
                    "C1": c1}
    if not p1:
        branch, action = "a", ("修采样校准：先确认注入真的落在对手座位上（投递/拒绝/曝光），"
                              "再谈强度。")
    elif c1:
        branch, action = "b", ("信用分配：压力有效，但早期（t≤8）拿到的终局信用被 "
                               "λ 衰减 / 价值 bootstrap 压没。")
    elif f1:
        branch, action = "c", ("保真度扩展：完整状态（golden/keywords/counters/hand）与 "
                               "board-only 有实质差异。")
    else:
        branch, action = "b", ("压力有效、早期信用未被压没、保真度无显著差异："
                               "回到信用分配/剂量（曝光）复核。")
    return {"branch": branch, "P1": p1, "C1": c1, "F1": f1,
            "pressure_detail": p_detail, "fidelity_detail": f_detail,
            "credit_detail": c_detail, "reasons": reasons, "action": action,
            "preregistered_rule": "not P1 -> (a); C1 -> (b); F1 -> (c); else (b)"}


# ════════════════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════════════════


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="PPAI 冻结轨迹反事实审计（CPU）")
    ap.add_argument("--checkpoint", default="runs/az_entity_s10/model.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--games", type=int, default=512, help="目标有效快照数")
    ap.add_argument("--max-games", type=int, default=760, help="最多跑的轨迹局数")
    ap.add_argument("--seed-base", type=int, default=910000, help="独立 seed 面板起点")
    ap.add_argument("--t-lo", type=int, default=6)
    ap.add_argument("--t-hi", type=int, default=15)
    ap.add_argument("--battle-seeds", type=int, default=64)
    ap.add_argument("--survivor-seeds", type=int, default=24)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--threads", type=int, default=2, help="每个轨迹 worker 的 torch 线程数")
    ap.add_argument("--move-guard", type=int, default=0)
    ap.add_argument("--human-boards", default=DEFAULT_HUMAN_BOARDS)
    ap.add_argument("--mirror-snaps", default=DEFAULT_MIRROR_SNAPS)
    ap.add_argument("--history", default=DEFAULT_HISTORY)
    ap.add_argument("--lib-ab", default=DEFAULT_LIB_AB)
    ap.add_argument("--out-dir", default="runs/audit")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true", help="忽略缓存重跑")
    ap.add_argument("--smoke", action="store_true", help="冒烟：16 局 / 8 seed / 24 帧")
    args = ap.parse_args(argv)
    if args.smoke:
        args.games = 16
        args.max_games = 24
        args.battle_seeds = 8
        args.survivor_seeds = 4
        args.workers = min(4, int(args.workers))
        args.out_dir = "runs/audit_smoke"
        args.out = "runs/audit_smoke/pressure_audit.json"
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    t_all = time.time()

    E = load_engine()
    print(f"[env] hsbg_engine {E.version()}  device={args.device}  pid={os.getpid()}")
    if args.device != "cpu":
        print("[warn] 本审计只允许 CPU（--device cpu）；忽略其它值", flush=True)
        args.device = "cpu"

    # ── 1) 轨迹 ──
    traj = stage_trajectories(args)
    rows = traj["rows"]
    ok = [r for r in rows if r.get("ok")]
    if len(ok) < args.games:
        print(f"[warn] 有效快照 {len(ok)} < 目标 {args.games}（max_games={args.max_games}）")
    fails: Dict[str, int] = {}
    for r in rows:
        if not r.get("ok"):
            key = str(r.get("fail", "?"))
            fails[key] = fails.get(key, 0) + 1
    print(f"[traj] 有效 {len(ok)} / {len(rows)}；失败分布 {fails}")

    # ── 2) 战斗 ──
    battles = stage_battles(args)

    # ── 3) 保真度消融 ──
    fid = stage_fidelity(args)

    # ── 4) 暴露 ──
    run_hists = {"s10": _read_history(args.history)}
    for arm in ("A", "B", "C"):
        p = os.path.join(args.lib_ab, arm, "history.jsonl")
        if os.path.isfile(p):
            run_hists[arm] = _read_history(p)
    exposure = stage_exposure(args, run_hists)

    # ── 5) 信号 ──
    signal = stage_signal(args, run_hists)

    # ── 6) 汇总 ──
    pressure = summarize_battles(battles)
    fidelity = summarize_fidelity(fid)
    decision = decide_branch(pressure, fidelity, signal)

    # 剂量：条件效应 × 每 learner-turn 命中概率（训练里“实际承受的压力”）
    dose: Dict[str, Any] = {}
    for name, c in pressure["configs"].items():
        ex = (exposure.get("configs") or {}).get(name, {})
        ph = float(ex.get("hit_prob_per_learner_turn", 0.0))
        dose[name] = {
            "hit_prob_per_learner_turn": ph,
            "reach_per_game_approx": ex.get("reach_per_game_approx"),
            "conditional_delta_loss_pp": 100.0 * float(c["delta_loss_raw"]["mean"]),
            "conditional_delta_dmg_taken": float(c["delta_dmg_taken_raw"]["mean"]),
            "per_turn_delta_loss_pp": ph * 100.0 * float(c["delta_loss_raw"]["mean"]),
            "per_turn_delta_dmg_taken": ph * float(c["delta_dmg_taken_raw"]["mean"]),
            "conditional_delta_loss_pp_realistic": (100.0 * float(c["delta_loss_realistic"]["mean"])
                                                   if c.get("delta_loss_realistic") else None),
        }
    dose["panel_reference"] = {
        "note": "human 面板（主指标）把 7 个对手座位**每回合全部**换成人类战团（p=1.0, auto）",
        "hit_prob_per_learner_turn": 1.0,
    }

    # 链式摘要：注入 → 暴露 → 压力 → 终局信用（+ 保真度）
    sig995 = (signal or {}).get("lambda_0.995") or {}
    sig995_early = sig995.get("early_t_le_8") or {}
    sig995_t7u = sig995.get("t7_upgrade") or {}
    tr = (signal or {}).get("training") or {}
    chain = {
        "link1_injection_to_exposure": {
            name: {"hit_prob_per_learner_turn": dose[name]["hit_prob_per_learner_turn"],
                   "reach_per_game_approx": dose[name]["reach_per_game_approx"],
                   "observed_applied_per_game": (
                       (exposure.get("configs") or {}).get(name) or {}
                   ).get("observed_applied_per_game")}
            for name in ("s10", "A", "B") if name in dose
        },
        "link2_exposure_to_pressure": {
            name: {"conditional_delta_loss_pp": dose[name]["conditional_delta_loss_pp"],
                   "conditional_delta_dmg_taken": dose[name]["conditional_delta_dmg_taken"],
                   "per_turn_delta_loss_pp": dose[name]["per_turn_delta_loss_pp"],
                   "per_turn_delta_dmg_taken": dose[name]["per_turn_delta_dmg_taken"],
                   "realistic_delta_loss_pp_conditional":
                       dose[name]["conditional_delta_loss_pp_realistic"]}
            for name in ("s10", "A", "B") if name in dose
        },
        "link3_pressure_to_terminal_credit": {
            "lambda_actual": 0.995,
            "lambda_logged_in_ppo_config": tr.get("lam_ppo_config_logged"),
            "median_gae_weight_t_le_8": (sig995_early.get("w") or {}).get("p50"),
            "median_terminal_share_t_le_8": (sig995_early.get("terminal_share") or {}).get("p50"),
            "median_gae_weight_t7_upgrade": (sig995_t7u.get("w") or {}).get("p50"),
            "median_gae_weight_t_le_8_lambda_0.95":
                (((signal or {}).get("lambda_0.95") or {}).get("early_t_le_8") or {}).get(
                    "w", {}).get("p50"),
            "approx_kl_mean": tr.get("approx_kl_mean"),
            "policy_loss_abs_mean": tr.get("policy_loss_abs_mean"),
            "entropy_first5": tr.get("entropy_first5"),
            "entropy_last5": tr.get("entropy_last5"),
            "lr": tr.get("lr"),
        },
        "link4_fidelity": {
            "n_trusted_frames": (fidelity or {}).get("n"),
            "delta_loss_pipeline_pp": (
                100.0 * ((fidelity or {}).get("delta_loss_pipeline") or {}).get("mean", 0.0)),
            "delta_loss_same_frame_pp": (
                100.0 * ((fidelity or {}).get("delta_loss_full_minus_board_only")
                         or {}).get("mean", 0.0)),
            "real_human_hidden_truth": "data_insufficient",
        },
    }

    s10_summary: Dict[str, Any] = {}
    sp = os.path.join(os.path.dirname(args.history), "summary.json")
    if os.path.isfile(sp):
        try:
            sj = json.load(open(sp))
            ev = sj.get("evals") or []
            s10_summary = {
                "human_panel": [{"decisions": e.get("decisions"),
                                 "mean_rank": e.get("human_mean_rank"),
                                 "top4": e.get("human_top4")}
                                for e in ev if e.get("panel") == "human"],
                "bot_panel": [{"decisions": e.get("decisions"),
                               "model_mean_rank": e.get("mean_rank"),
                               "baseline_bot_mean_rank": e.get("bot_mean_rank")}
                              for e in ev if e.get("panel") == "bot"],
            }
        except BaseException:  # noqa: BLE001
            pass

    result = {
        "schema": "hsbg.pressure_audit",
        "schema_version": 1,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "repo": ROOT,
        "checkpoint": args.checkpoint,
        "device": args.device,
        "seed_base": int(args.seed_base),
        "configs": list(CONFIGS),
        "design": {
            "trajectory_lobby": "s10 model vs 7 engine bots, no injection (paired control world)",
            "snapshot_turns": [int(args.t_lo), int(args.t_hi)],
            "battle_seeds": int(args.battle_seeds),
            "survivor_seeds": int(args.survivor_seeds),
            "paired": "same snapshot + same combat RNG seeds, injection vs no injection",
            "raw_arm": "inject_board at combat time (conditional on hit, 100% exposure)",
            "realistic_arm": "inject at turn start + victim seat plays its bot turn (training pipeline)",
            "fidelity_arm": "trusted EOT snapshots: full Player JSON vs board-only (base card ids)",
            "gae": "gamma=1.0, lambda=0.995 (also 0.95 sensitivity)",
        },
        "exposure": exposure,
        "trajectories": {
            "games_run": len(rows),
            "valid_snapshots": len(ok),
            "failures": fails,
            "learner_board_str": _pct([int(r["learner_str"]) for r in ok]),
            "target_board_str": _pct([int(r["target_str"]) for r in ok]),
            "turn_hist": {str(t): sum(1 for r in ok if int(r["t_choice"]) == t)
                          for t in range(int(args.t_lo), int(args.t_hi) + 1)},
            "rank_hist": {str(k): sum(1 for r in ok if int(r["rank"]) == k)
                          for k in range(1, N_PLAYERS + 1)},
        },
        "pressure": pressure,
        "fidelity": fidelity,
        "signal": signal,
        "dose": dose,
        "chain": chain,
        "s10_eval_context": s10_summary,
        "decision": decision,
        "stage_seconds": {
            "trajectories": traj.get("seconds"),
            "battles": battles.get("seconds"),
            "fidelity": fid.get("seconds"),
        },
        "seconds": time.time() - t_all,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(result, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps({"trajectories": result["trajectories"],
                      "decision": result["decision"]},
                     ensure_ascii=False, indent=2)[:4000])
    print(f"[done] {args.out}  ({time.time() - t_all:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
