#!/usr/bin/env python3
"""同状态对拷实验：从 s27d@5M 在 5 席 p0.9 打到 t8 的状态出发，比较 M/S 两条后续路径。

阶段 1（dump）：用模型（greedy）跑 N 局，在 **turn 8 开始** 保存 `state_json` + 人类战团注入 RNG 状态。
阶段 2（arms）：同一批 state 各跑一次到终局，记录 t8/t15 的 Σ、载体 buff 占比、法术、tier@t15、名次。
  M     模型继续（s27d@5M, greedy）
  S     脚本接管（comp_scripts CompPolicy, --comp auto）
  MS    模型到 t10 再交脚本

用法::
  python scripts/comp_state_ab.py --dump --games 200 --device cuda:4 --out /tmp/s22/t8_states.jsonl.gz
  python scripts/comp_state_ab.py --run --arms M,S,MS --device cuda:5 \
      --states /tmp/s22/t8_states.jsonl.gz --out runs/comp_scripts/state_ab.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hsbg.az.train.common import mask_from_bytes  # noqa: E402
import comp_scripts as CS  # noqa: E402
from comp_handover import ModelPolicy, ScriptAdapter  # noqa: E402

_MODELS: Dict[str, Any] = {}


def get_model(ckpt: str, device: str) -> "ModelPolicy":
    key = f"{ckpt}|{device}"
    if key not in _MODELS:
        _m = ModelPolicy(ckpt, device)
        try:
            _m.cfg.temperature = 1e-6   # greedy（温度趋 0）
        except BaseException:  # noqa: BLE001
            pass
        _MODELS[key] = _m
    return _MODELS[key]

_BASE_STATS: Dict[str, Tuple[int, int]] = {}


def base_stats() -> Dict[str, Tuple[int, int]]:
    if not _BASE_STATS:
        cards = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
        if isinstance(cards, dict):
            cards = cards.get("cards") or cards.get("data") or list(cards.values())
        for c in cards:
            if isinstance(c, dict) and c.get("id") and c.get("atk") is not None:
                _BASE_STATS[str(c["id"])] = (int(c["atk"]), int(c["hp"]))
    return _BASE_STATS


def _pool(path: str):
    from hsbg.az.train.human_board_pool import load_pool
    return load_pool(path, sample="auto") if path else None


def _play_segment(game, pol, q, gate_turn: Optional[int] = None,
                  stop_turn: Optional[int] = None, max_steps: int = 20000) -> Dict[str, Any]:
    """从当前 game 继续；gate_turn=到达该回合开始就返回；stop_turn=该回合开始就停。"""
    from hsbg.az.train.human_board_pool import HumanBoardStats, inject_turn as inject_human_turn
    hpool = q.get("human_board_pool")
    hb_p = float(q.get("human_board_p") or 0.0)
    hb_seats = int(q.get("human_board_seats") or 5)
    stats = HumanBoardStats(fidelity=str(q.get("human_board_fidelity") or "full"))
    rng = q.get("rng") or random.Random(0)
    injected = q.get("injected", -1)
    strength: Dict[int, int] = {int(k): int(v) for k, v in (q.get("strength") or {}).items()}
    q["strength"] = strength
    tiers: Dict[int, int] = {int(k): int(v) for k, v in (q.get("tiers") or {}).items()}
    q["tiers"] = tiers
    steps = 0
    gate_hit = False
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if stop_turn is not None and t >= stop_turn:
            break
        if gate_turn is not None and t >= gate_turn:
            gate_hit = True
            break
        if t != injected and t >= 1 and hpool is not None and hb_p > 0:
            injected = t
            try:
                inject_human_turn(game, hpool, t, seats_count=hb_seats, p=hb_p,
                                  rng=rng, learner_seat=0, stats=stats, set_tier=True,
                                  fidelity=str(q.get("human_board_fidelity") or "full"),
                                  fast_inject=True)
            except BaseException:  # noqa: BLE001
                pass
        if t not in strength:
            pj = json.loads(game.player_json(0))
            strength[t] = int(sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                                  for m in (pj.get("board") or [])))
            tiers[t] = int(pj.get("tier") or 0)
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == 0:
                a = int(pol.decide(game, 0).action)
                m = mask_from_bytes(game.legal_mask(0))
                if not (0 <= a < 245 and bool(m[a])):
                    nz = np.flatnonzero(m)
                    a = int(nz[0]) if nz.size else 0
                game.step(0, a)
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    return {"strength": strength, "injected": injected, "gate_hit": gate_hit,
            "steps": steps, "over": bool(game.is_over())}


def dump_states(args) -> int:
    import hsbg_engine as E
    hpool = _pool(args.human_boards) if args.mode == "p09" else None
    rows = []
    t0 = time.time()
    for i in range(int(args.games)):
        seed = int(args.seed0) + i
        game = E.Game(seed=seed)
        pol = get_model(args.model_checkpoint, args.device)
        rng = random.Random(seed * 1000003 + 17)
        q = {"human_board_pool": hpool, "human_board_p": (args.human_p if args.mode == "p09" else 0.0),
             "human_board_seats": args.human_seats, "human_board_fidelity": args.human_fidelity,
             "rng": rng, "strength": {}}
        pol.reset()
        r = _play_segment(game, pol, q, gate_turn=8)
        if not r["gate_hit"]:
            continue
        j = game.state_json()
        rows.append({"seed": seed, "state": j, "strength": r["strength"],
                     "rng": pickle.dumps(rng.getstate()).hex(),
                     "injected": r["injected"],
                     "t8_sigma": int(r["strength"].get(7) or r["strength"].get(8) or 0)})
        if i % 20 == 0:
            print(f"[dump] {i}/{args.games} t={time.time()-t0:.0f}s", flush=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[dump] saved {len(rows)} states -> {args.out} ({time.time()-t0:.0f}s)", flush=True)
    return 0


def _run_arm(state: dict, arm: str, args, spec) -> Optional[dict]:
    import hsbg_engine as E
    game = E.Game.from_json(state["state"])
    model = get_model(args.model_checkpoint, args.device) if arm in ("M", "MS") else None
    script = ScriptAdapter(spec, seed=int(state["seed"]), auto=True)
    if arm == "M":
        pol = model
    elif arm == "S":
        pol = script
    else:
        pol = model  # 先模型到 t10，再换 script（下面分段跑）
    rng = random.Random(0)
    rng.setstate(pickle.loads(bytes.fromhex(state["rng"])))
    q = {"human_board_pool": _pool_cached(args), "human_board_p": (args.human_p if args.mode == "p09" else 0.0),
         "human_board_seats": args.human_seats, "human_board_fidelity": args.human_fidelity,
         "rng": rng, "injected": int(state.get("injected") or -1),
         "strength": dict(state.get("strength") or {})}
    if arm == "MS":
        _play_segment(game, model, q, gate_turn=10)
        if not game.is_over():
            _play_segment(game, script, q)
    else:
        _play_segment(game, pol, q)
    st = q["strength"]
    t8 = int(state.get("t8_sigma") or 0)
    t15 = int(st.get(15) or (max(st.values()) if st else 0))
    fb = []
    try:
        v = json.loads(game.view(0))
        fb = (v.get("me") or {}).get("board") or []
    except BaseException:  # noqa: BLE001
        pass
    base = base_stats()
    cb = tb = 0.0
    for m in fb:
        cid = str(m.get("id") or "")
        _b = base.get(cid) or (0, 0)
        mult = 2 if m.get("golden") else 1
        buf = max(0.0, (int(m.get("atk") or 0) - mult * _b[0])
                  + (int(m.get("hp") or 0) - mult * _b[1]))
        tb += buf
        if spec is not None and cid in CS.expand(spec.carrier):
            cb += buf
    return {"seed": state["seed"], "arm": arm, "t8": t8, "t15": t15,
            "alive_t15": bool(15 in st),
            "delta": t15 - t8, "multiple": (float(t15) / float(t8)) if t8 > 0 else None,
            "carrier_buff_share": (cb / tb) if tb > 0 else None,
            "spells": int(getattr(script.pol, "spells", 0) or 0) if script is not None else 0,
            "placement": int(list(game.placements())[0]) if game.is_over() else None,
            "tier15": int((q.get("tiers") or {}).get(15) or 0)}


_POOL = {}


def _pool_cached(args):
    if not _POOL:
        _POOL["p"] = _pool(args.human_boards) if args.mode == "p09" else None
    return _POOL["p"]


def _pct(xs, p):
    xs = sorted(float(x) for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))], 1)


def run_arms(args) -> int:
    states = [json.loads(l) for l in gzip.open(args.states, "rt", encoding="utf-8")]
    if args.limit:
        states = states[: int(args.limit)]
    spec = CS.COMPS.get(str(args.comp).strip())
    arms = [a.strip() for a in str(args.arms).split(",") if a.strip()]
    out: Dict[str, List[dict]] = {a: [] for a in arms}
    t0 = time.time()
    for i, st in enumerate(states):
        for arm in arms:
            try:
                r = _run_arm(st, arm, args, spec)
            except BaseException as exc:  # noqa: BLE001
                r = {"seed": st["seed"], "arm": arm, "error": repr(exc)}
            out[arm].append(r)
        if i % 20 == 0:
            print(f"[run] {i}/{len(states)} ({time.time()-t0:.0f}s)", flush=True)
    summ = {}
    for arm in arms:
        rows = [r for r in out[arm] if r and "error" not in r]
        summ[arm] = {"n": len(rows),
                     "t8_p50": _pct([r["t8"] for r in rows], 0.5),
                     "t15_p50": _pct([r["t15"] for r in rows], 0.5),
                     "t15_p90": _pct([r["t15"] for r in rows], 0.9),
                     "t15_max": max([r["t15"] for r in rows]) if rows else None,
                     "delta_p50": _pct([r["delta"] for r in rows], 0.5),
                     "multiple_p50": _pct([r["multiple"] for r in rows], 0.5),
                     "carrier_buff_share_mean": (round(float(np.mean(
                         [r["carrier_buff_share"] for r in rows
                          if r["carrier_buff_share"] is not None])), 3) if any(
                         r["carrier_buff_share"] is not None for r in rows) else None),
                     "spells_mean": round(float(np.mean([r["spells"] for r in rows])), 2) if rows else None,
                     "tier15_p50": _pct([r["tier15"] for r in rows], 0.5),
                     "rank_mean": (round(float(np.mean([r["placement"] for r in rows
                                                        if r["placement"] is not None])), 3)
                                   if any(r["placement"] is not None for r in rows) else None)}
    # 配对差 S-M（同 seed）
    pair = {}
    if "M" in out:
        m = {r["seed"]: r["t15"] for r in out["M"] if r and "error" not in r}
        for arm in arms:
            if arm == "M":
                continue
            diffs = [r["t15"] - m[r["seed"]] for r in out[arm]
                     if r and "error" not in r and r["seed"] in m]
            if not diffs:
                continue
            arr = np.asarray(diffs, dtype=np.float64)
            boot = [float(np.mean(np.random.default_rng(k).choice(arr, arr.size, replace=True)))
                    for k in range(1000)]
            pair[f"{arm}_minus_M"] = {"mean": round(float(arr.mean()), 1),
                                      "p50": round(float(np.median(arr)), 1),
                                      "ci95": [round(float(np.percentile(boot, 2.5)), 1),
                                               round(float(np.percentile(boot, 97.5)), 1)],
                                      "n": int(arr.size)}
    if getattr(args, "dump_records", ""):
        _rec = {"arms": out, "n_states": len(states)}
        with open(args.dump_records, "w", encoding="utf-8") as _f:
            json.dump(_rec, _f, ensure_ascii=False, indent=1)
    res = {"arms": summ, "paired": pair, "n_states": len(states),
           "seconds": round(time.time() - t0, 1)}
    print(json.dumps(res, ensure_ascii=False), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed0", type=int, default=520000)
    ap.add_argument("--mode", default="p09", choices=["bot", "p09"])
    ap.add_argument("--arms", default="M,S,MS")
    ap.add_argument("--comp", default="A")
    ap.add_argument("--model-checkpoint", default=os.path.join(ROOT, "runs/az_entity_s27d/model.pt"))
    ap.add_argument("--device", default="cuda:4")
    ap.add_argument("--human-boards", default=os.path.join(
        ROOT, "data/real_library/library_real_quasi_full.jsonl"))
    ap.add_argument("--human-seats", type=int, default=5)
    ap.add_argument("--human-p", type=float, default=0.9)
    ap.add_argument("--human-fidelity", default="full")
    ap.add_argument("--states", default="/tmp/s22/t8_states.jsonl.gz")
    ap.add_argument("--out", default="")
    ap.add_argument("--dump-records", default="", help="每状态逐臂记录 JSON（shadow 用）")
    args = ap.parse_args()
    if args.dump:
        return dump_states(args)
    return run_arms(args)


if __name__ == "__main__":
    sys.exit(main())