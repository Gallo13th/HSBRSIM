"""沙盒策略 → 完整对局：A1 采集（+ A2 蒸馏入口）

task-12 (A)：把达标沙盒策略（`runs/compound_bc/ppo/rv_telescope/model.pt`，greedy 解码）
放到**完整对局**里跑 200 局（7 席人类战团真实强度、5 席 p0.9、`fidelity=full`、move-guard 1），
记录每条 learner 决策的 `features/cards/mask/action` 与整局标签（t12/t15 Σ、名次、tier、
goldens、放大器购买数、施法、存活回合）。

为什么要重写采集循环（而不是直接用 `quality_monitor._play`）：那个函数不导出逐决策观测，
也没有「放大器购买 / goldens」两个沙盒口径的计量。这里**沿用它的同一条引擎路径**：
`E.Game(seed)` + `inject_human_turn(...)` + `needs_action/legal_mask/step/bot_play` +
`PPOSelfPlayPolicy.decide`，只在 learner 的决策点上多记一份 `policy.records[-1]`。

用法::

    PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    export PYTHONPATH=rust/python:.
    # A1：采 200 局（约 10–20 min）
    $PY scripts/distill_to_full.py --mode collect \
        --checkpoint runs/compound_bc/ppo/rv_telescope/model.pt --games 200 \
        --human-boards data/real_library/library_real_quasi_full.jsonl \
        --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
        --move-guard 1 --out-dir runs/full_distill

    # A2：把采集到的决策做 masked CE 蒸馏（复用已验证的 train_compound_bc.py）
    $PY scripts/distill_to_full.py --mode distill --out-dir runs/full_distill

产物：`runs/full_distill/rollouts_<tag>.jsonl.gz`（逐局：决策流 + 标签）、
`.../bc_dataset_<tag>.npz`（训练用，schema 与 `data/scaling/compound_bc/*.npz` 一致）、
`.../stats_<tag>.json`（Σ/tier/goldens/amp/名次/存活统计）。
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT_DIR = os.path.join(ROOT, "runs", "full_distill")
AMP_RANGE = range(8, 16)          # A_BUY .. A_BUY+7
KIND = {"end_turn": 10, "refresh": 9, "upgrade": 8, "sell": 7, "buy": 4, "play": 6,
        "pending": 11}


def _pct(v: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(v, dtype=np.float64), q)) if len(v) else 0.0


def _mean(v: Sequence[float]) -> float:
    return float(np.mean(np.asarray(v, dtype=np.float64))) if len(v) else 0.0


def build_policy(ckpt: str, device: str, seed: int, move_guard: bool,
                 move_cap: int, repeat_limit: int, max_steps: int):
    from hsbg.az.train.model import load_checkpoint  # noqa: PLC0415
    from hsbg.az.train.ppo import (CollectConfig, PPOEvaluator,  # noqa: PLC0415
                                   PPOSelfPlayPolicy)
    model, meta = load_checkpoint(ckpt, device=device)
    ev = PPOEvaluator(model, device=device, norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(seed), opponent="bot", behavior="net",
                        max_steps=int(max_steps), move_guard=bool(move_guard),
                        move_cap=int(move_cap), move_repeat_limit=int(repeat_limit))
    pol = PPOSelfPlayPolicy(model, device=device, config=cfg, eval_fn=ev,
                            seed=int(seed), move_model=False)
    pol.records.clear()
    return pol, meta


def play_one(seed: int, policy, q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """跑一局完整对局，返回逐决策记录 + 整局标签；超步数返回 None。"""
    import hsbg_engine as E  # noqa: PLC0415

    from hsbg.az.train.common import mask_from_bytes  # noqa: PLC0415
    from hsbg.az.train.human_board_pool import (HumanBoardStats,  # noqa: PLC0415
                                                inject_turn as inject_human_turn)
    game = E.Game(seed=int(seed))
    policy.reset()
    policy.records.clear()
    hpool = q.get("human_board_pool")
    hb_seats = int(q.get("human_board_seats", 5))
    hb_p = float(q.get("human_board_p", 0.0))
    hb_fid = str(q.get("human_board_fidelity", "board"))
    hb_stats = HumanBoardStats(fidelity=hb_fid)
    hb_rng = random.Random(int(seed) * 1000003 + 17)
    max_steps = int(q.get("max_steps", 20000))
    injected = -1
    turns: List[Dict[str, Any]] = []
    dec_rows: List[Dict[str, Any]] = []
    amp_buys = 0
    casts = 0
    last_turn = -1
    steps = 0

    def maybe_inject(t: int) -> None:
        nonlocal injected
        if hpool is None or hb_p <= 0.0 or int(t) == injected or int(t) < 1:
            return
        injected = int(t)
        inject_human_turn(game, hpool, int(t), seats_count=hb_seats, p=hb_p,
                          rng=hb_rng, learner_seat=0, stats=hb_stats,
                          set_tier=bool(q.get("human_board_set_tier", True)),
                          fidelity=hb_fid, fast_inject=False)

    # ── 每回合的 Σ / tier / goldens / amp 采样（learner 动作后取）───────────
    pending_turn_row: Optional[Dict[str, Any]] = None

    def snap(turn: int) -> Dict[str, Any]:
        pj = json.loads(game.player_json(0))
        board = pj.get("board") or []
        strength = 0
        for m in board:            # player_json 的字段是 atk/hp（不是 stats.attack）
            strength += int(m.get("atk") or 0) + int(m.get("hp") or 0)
        golden = sum(1 for m in board if bool(m.get("golden")))
        return {"turn": int(turn), "strength": int(strength),
                "tier": int(pj.get("tier") or 0), "gold": int(pj.get("gold") or 0),
                "health": int(pj.get("health") or 0),
                "alive": bool(pj.get("alive", True)),
                "count": len(board), "goldens": int(golden)}

    while not game.is_over() and steps < max_steps:
        maybe_inject(int(game.turn))
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pending_turn_row = snap(t)
            turns.append(pending_turn_row)
        acted = False
        for p in range(8):
            if game.is_over():
                break
            maybe_inject(int(game.turn))
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p != 0:
                game.bot_play(p)
                continue
            mask = mask_from_bytes(game.legal_mask(0))
            dec = policy.decide(game, 0)
            a = int(dec.action)
            if not (0 <= a < 245 and bool(mask[a])):
                nz = np.flatnonzero(mask)
                a = int(nz[0]) if nz.size else 0
            # 放大器购买（player_json 的 shop 槽是 item.Minion.card = cid）
            if a in AMP_RANGE:
                try:
                    pj0 = json.loads(game.player_json(0))
                    shop = pj0.get("shop") or []
                    i = a - 8
                    if 0 <= i < len(shop):
                        item = (shop[i] or {}).get("item") or {}
                        mn = item.get("Minion") if isinstance(item, dict) else None
                        if isinstance(mn, dict):
                            cid = int(mn.get("card") or -1)
                            if q.get("cid2id", {}).get(cid) in q.get("amp_ids", set()):
                                amp_buys += 1
                except BaseException:  # noqa: BLE001
                    pass
            if 30 <= a < 46:
                casts += 1                      # 目标选择（施法打人）次数
            rec = policy.records[-1] if policy.records else None
            if rec is not None:
                dec_rows.append({
                    "features": np.asarray(rec["features"], dtype=np.float32),
                    "cards": np.asarray(rec["cards"], dtype=np.int32),
                    "mask": np.asarray(rec["mask"], dtype=bool),
                    "action": int(a), "turn": int(t), "forced": bool(rec["forced"]),
                    "value": float(rec.get("value") or 0.0),
                    "seat": 0})
            game.step(0, a)
            pending_turn_row = snap(int(game.turn)) if False else pending_turn_row
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    # 终局再补一行（末回合 Σ）
    turns.append(snap(int(game.turn)))
    placements = list(game.placements())
    by_turn = {int(r["turn"]): r for r in turns}

    def at(t: int) -> Dict[str, Any]:
        if t in by_turn:
            return by_turn[t]
        best = None
        for k in sorted(by_turn):
            if k <= t:
                best = by_turn[k]
        return best or {}

    s12 = int(at(12).get("strength") or 0)
    s15 = int(turns[-1].get("strength") or 0)
    return {
        "seed": int(seed),
        "placement": int(placements[0]) if placements else 0,
        "death_turn": int(turns[-1]["turn"]),
        "survival_turns": len(turns),
        "sigma_t12": s12, "sigma_t15": s15,
        "r12_15": (s15 / s12) if s12 > 0 else 0.0,
        "tier_t15": int(turns[-1].get("tier") or 0),
        "goldens_t15": int(turns[-1].get("goldens") or 0),
        "amp_buys": int(amp_buys), "casts": int(casts),
        "board_count_t15": int(turns[-1].get("count") or 0),
        "health_t15": int(turns[-1].get("health") or 0),
        "decisions": len(dec_rows),
        "turns": turns,
        "human_board": hb_stats.to_meta(),
        "_rows": dec_rows,
    }


def cmd_collect(args) -> int:
    import hsbg_engine as E  # noqa: PLC0415

    from hsbg.az.train.human_board_pool import load_pool  # noqa: PLC0415
    try:
        import compound_script as C  # noqa: PLC0415
        amp_ids = set(C.AMP_IDS)
    except Exception as exc:  # noqa: BLE001
        print(f"[full] 警告：拿不到 AMP_IDS（{exc}），amp 统计将为 0", flush=True)
        amp_ids = set()
    try:
        cid2id = {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}
    except BaseException:  # noqa: BLE001
        cid2id = {}
    pool = load_pool(str(args.human_boards), sample=str(args.human_board_sample)) \
        if args.human_boards else None
    q = {"human_board_pool": pool, "human_board_seats": int(args.human_board_seats),
         "human_board_p": float(args.human_board_p),
         "human_board_fidelity": str(args.human_board_fidelity),
         "human_board_set_tier": bool(int(args.human_board_set_tier)),
         "max_steps": int(args.max_steps), "amp_ids": amp_ids, "cid2id": cid2id}
    policy, meta = build_policy(str(args.checkpoint), str(args.device),
                                int(args.seed_base), bool(int(args.move_guard)),
                                int(args.move_cap), int(args.move_repeat_limit),
                                int(args.max_steps))
    print(f"[full] 策略 {args.checkpoint}（{meta.get('size')}）；"
          f"人类战团 {args.human_board_seats} 席 p={args.human_board_p} "
          f"fidelity={args.human_board_fidelity}；move_guard={args.move_guard}",
          flush=True)
    os.makedirs(str(args.out_dir), exist_ok=True)
    tag = str(args.tag)
    jl = os.path.join(str(args.out_dir), f"rollouts_{tag}.jsonl.gz")
    feats: List[np.ndarray] = []
    cards: List[np.ndarray] = []
    masks: List[np.ndarray] = []
    acts: List[int] = []
    eids: List[int] = []
    ep_meta: List[Dict[str, Any]] = []
    t0 = time.time()
    games = 0
    truncated = 0
    with gzip.open(jl, "wt", encoding="utf-8") as fh:
        for g in range(int(args.games)):
            seed = int(args.seed_base) + g
            rep = play_one(seed, policy, q)
            if rep is None:
                truncated += 1
                continue
            rows = rep.pop("_rows")
            for r in rows:
                feats.append(r["features"])
                cards.append(r["cards"])
                masks.append(r["mask"])
                acts.append(int(r["action"]))
                eids.append(games)
            rep["episode_id"] = games
            rep["ep_truncated"] = False
            ep_meta.append({k: v for k, v in rep.items() if k != "turns"})
            fh.write(json.dumps({"game": rep, "n_decisions": len(rows)},
                                ensure_ascii=False) + "\n")
            games += 1
            if games % 10 == 0:
                print(f"[full] {games}/{args.games} 局，"
                      f"{sum(len(x) for x in feats) if False else len(acts)} 决策，"
                      f"{time.time() - t0:.0f}s", flush=True)
    s12 = [float(r["sigma_t12"]) for r in ep_meta]
    s15 = [float(r["sigma_t15"]) for r in ep_meta]
    r12 = [float(r["r12_15"]) for r in ep_meta]
    stats = {
        "checkpoint": str(args.checkpoint), "tag": tag, "games": games,
        "truncated": truncated, "decisions": int(len(acts)),
        "seed_base": int(args.seed_base),
        "human_board": {"seats": int(args.human_board_seats),
                        "p": float(args.human_board_p),
                        "fidelity": str(args.human_board_fidelity)},
        "move_guard": bool(int(args.move_guard)),
        "sigma_t12_p50": _pct(s12, 50), "sigma_t12_p90": _pct(s12, 90),
        "sigma_t15_p50": _pct(s15, 50), "sigma_t15_p90": _pct(s15, 90),
        "sigma_t15_max": max(s15) if s15 else 0.0,
        "r12_15_p50": _pct(r12, 50), "r12_15_p90": _pct(r12, 90),
        "tier_p50": _pct([float(r["tier_t15"]) for r in ep_meta], 50),
        "goldens_mean": _mean([float(r["goldens_t15"]) for r in ep_meta]),
        "amp_mean": _mean([float(r["amp_buys"]) for r in ep_meta]),
        "casts_mean": _mean([float(r["casts"]) for r in ep_meta]),
        "placement_mean": _mean([float(r["placement"]) for r in ep_meta]),
        "placement_hist": {int(k): int(v) for k, v in zip(
            *np.unique([int(r["placement"]) for r in ep_meta], return_counts=True))},
        "survival_turns_mean": _mean([float(r["survival_turns"]) for r in ep_meta]),
        "decisions_per_game": _mean([float(r["decisions"]) for r in ep_meta]),
        "decisions_median": _pct([float(r["decisions"]) for r in ep_meta], 50),
        "seconds": round(time.time() - t0, 1),
        "jsonl": os.path.relpath(jl, ROOT),
        "episodes": ep_meta,
    }
    sp = os.path.join(str(args.out_dir), f"stats_{tag}.json")
    with open(sp, "w", encoding="utf-8") as f2:
        json.dump(stats, f2, ensure_ascii=False, indent=1)
    # 训练用 npz（与 data/scaling/compound_bc schema 一致；日志自带 action_kind 缺省 0）
    npz = os.path.join(str(args.out_dir), f"bc_dataset_{tag}.npz")
    payload = {
        "features": np.stack(feats) if feats else np.zeros((0, 3227), np.float32),
        "cards": np.stack(cards).astype(np.int16) if cards else np.zeros((0, 124), np.int16),
        "mask": np.stack(masks) if masks else np.zeros((0, 245), bool),
        "action": np.asarray(acts, dtype=np.uint8),
        "episode_id": np.asarray(eids, dtype=np.int32),
        "turn": np.asarray([0] * len(acts), dtype=np.uint8),
        "tier": np.asarray([0] * len(acts), dtype=np.uint8),
        "gold": np.asarray([0] * len(acts), dtype=np.int16),
        "ep_sigma_t12": np.asarray([int(r["sigma_t12"]) for r in ep_meta], dtype=np.int32),
        "ep_sigma_t15": np.asarray([int(r["sigma_t15"]) for r in ep_meta], dtype=np.int32),
        "ep_r12_15": np.asarray([float(r["r12_15"]) for r in ep_meta], dtype=np.float32),
        "ep_split": np.asarray([1 if (i % 10 == 0) else 0
                                for i in range(len(ep_meta))], dtype=np.uint8),
    }
    np.savez_compressed(npz, **payload)
    print("[full] " + json.dumps({k: stats[k] for k in
                                  ("games", "decisions", "sigma_t12_p50",
                                   "sigma_t15_p50", "sigma_t15_max", "r12_15_p50",
                                   "tier_p50", "goldens_mean", "amp_mean",
                                   "placement_mean", "survival_turns_mean",
                                   "seconds")}, ensure_ascii=False), flush=True)
    print(f"[full] 写出 {jl}\n[full] 写出 {sp}\n[full] 写出 {npz}", flush=True)
    return 0


def cmd_distill(args) -> int:
    """A2：把采集到的决策做 masked CE 蒸馏（复用已验证的训练脚本）。"""
    import subprocess  # noqa: PLC0415
    npz = str(args.npz) or os.path.join(str(args.out_dir),
                                       f"bc_dataset_{args.tag}.npz")
    if not os.path.isfile(npz):
        raise SystemExit(f"找不到 {npz}，先跑 --mode collect")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "train_compound_bc.py"),
           "--data", npz, "--out", str(args.out_dir),
           "--device", str(args.device), "--arch", "entity",
           "--d-model", str(args.d_model), "--n-layers", str(args.n_layers),
           "--n-heads", "8", "--epochs", str(args.epochs), "--lr", str(args.lr),
           "--batch-size", "256", "--holdout", "0.05",
           "--action-weight-mode", "manual",
           "--action-weight-kinds", "buy_amp:4,buy_carrier:2,play_spell:4,upgrade:4",
           "--size-name", str(args.tag)]
    print("[distill] " + " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="沙盒策略 → 完整对局（A1 采集 / A2 蒸馏）")
    ap.add_argument("--mode", default="collect", choices=["collect", "distill"])
    ap.add_argument("--checkpoint",
                    default="runs/compound_bc/ppo/rv_telescope/model.pt")
    ap.add_argument("--out-dir", dest="out_dir", default=OUT_DIR)
    ap.add_argument("--tag", default="s21")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed-base", dest="seed_base", type=int, default=960000)
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--max-steps", dest="max_steps", type=int, default=20000)
    # 完整游戏对手（与 s14 训练/评测同口径）
    ap.add_argument("--human-boards", dest="human_boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-board-p", dest="human_board_p", type=float, default=0.9)
    ap.add_argument("--human-board-seats", dest="human_board_seats", type=int, default=5)
    ap.add_argument("--human-board-sample", dest="human_board_sample", default="auto")
    ap.add_argument("--human-board-fidelity", dest="human_board_fidelity",
                    default="full")
    ap.add_argument("--human-board-set-tier", dest="human_board_set_tier", type=int,
                    default=1)
    ap.add_argument("--move-guard", dest="move_guard", type=int, default=1)
    ap.add_argument("--move-cap", dest="move_cap", type=int, default=3)
    ap.add_argument("--move-repeat-limit", dest="move_repeat_limit", type=int, default=2)
    # distill
    ap.add_argument("--npz", default="")
    ap.add_argument("--d-model", dest="d_model", type=int, default=384)
    ap.add_argument("--n-layers", dest="n_layers", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=3e-5)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if str(args.mode) == "distill":
        return cmd_distill(args)
    return cmd_collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
