#!/usr/bin/env python3
"""CompPolicy 只读探针：把「固定阵容脚本」当 1 席对手/学员跑 30 局，输出合法率与强度。

不训练、不写 checkpoint、不占 GPU（纯 CPU）。协议与 ``scripts/comp_scripts.py`` 的
8-bot 组一致：seat0 = CompPolicy（hybrid：阵容动作优先，其余引擎 bot 兜底），
seat1..7 = 引擎 bot；步数上限 4000。

同时按 ``scripts/comp_metrics_probe.py`` 的 T1 口径逐回合算 ``comp_fit``（0..1），
报告 t9 的 fit 分布 —— 用来回答「脚本是否更贴近 T1 势函数，但强度更差」这个对照问题
（模型的同口径基线见 ``runs/comp_scripts/baseline_*_summary.json``）。

用法::

  python scripts/comp_opponent_probe.py --comp auto --games 30
  python scripts/comp_opponent_probe.py --comp J --games 30 --json-out /tmp/probe_J.json
  python scripts/comp_opponent_probe.py --comp auto --games 30 --mode p09   # 5 席人类 p0.9

口径（与 docs/COMP_SCRIPTS_TRAINING.md 对应）
--------------------------------------------
- ``legal_rate`` = 1 - 非法动作 / 决策数（逐动作用 legal mask 复核；非法时回退合法动作）。
- ``sigma_t15`` = 第 15 回合盘面 Σ(atk+hp)；已死取终局（同 comp_scripts）。
- ``fit_t9`` = 该局最后一个 t<=9 决策处的 max-over-comps comp_fit（T1 奖励的同款公式）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import comp_scripts as CS            # noqa: E402
import comp_metrics_probe as CMP     # noqa: E402  （T1 口径的 fit_components/best_comp）
from hsbg.az.train.common import mask_from_bytes  # noqa: E402

A_END = 244
MAX_STEPS = 4000


def _pct(xs: List[float], q: float) -> Optional[float]:
    xs = sorted(float(x) for x in xs if x is not None)
    if not xs:
        return None
    k = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 3)


def play_one(seed: int, spec: Any, *, auto: bool, mode: str,
             human_pool: Any = None, human_seats: int = 5,
             human_p: float = 0.9, human_fidelity: str = "full") -> Optional[dict]:
    """一局：seat0 = CompPolicy(hybrid)，其余引擎 bot；返回决策数/非法数/fit9 等。"""
    game = CS.E.Game(int(seed), CS._config_json(spec, seed))
    CS.EA.finish_hero_select(game)
    pol = CS.CompPolicy(spec, auto=auto, seed=int(seed) % 100000)
    rng = random.Random(int(seed) * 1000003 + 17)
    stats = None
    if human_pool is not None and human_p > 0 and human_seats > 0:
        from hsbg.az.train.human_board_pool import HumanBoardStats, inject_turn
        stats = HumanBoardStats(fidelity=human_fidelity)
    last_turn = -1
    steps = 0
    decisions = 0
    illegal = 0
    fit9: Optional[float] = None
    fit_turn: Dict[int, float] = {}
    while not game.is_over() and steps < MAX_STEPS:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            if stats is not None and t >= 1:
                try:
                    inject_turn(game, human_pool, t, seats_count=human_seats, p=human_p,
                                rng=rng, learner_seat=0, stats=stats, set_tier=True,
                                fidelity=human_fidelity, fast_inject=True)
                except BaseException:  # noqa: BLE001 - 注入失败不影响对局
                    pass
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p != 0:
                game.bot_play(p)
                continue
            mask = mask_from_bytes(game.legal_mask(0))
            v = json.loads(game.view(0))
            me = v.get("me") or {}
            # T1 口径的 comp_fit（每回合一次，取该回合决策处的盘面）
            if int(t) <= 9 and int(t) not in fit_turn:
                try:
                    _c, _f = CMP.best_comp(me, int(t))
                    fit_turn[int(t)] = float(_f)
                    fit9 = float(_f)
                except BaseException:  # noqa: BLE001
                    pass
            decisions += 1
            if pol.spec0 is not None and pol.spec0.key == "f_dragon":
                a = int(pol.act(v, mask))                      # 纯脚本 F V2
            else:
                pol.observe(v, mask)
                if pol.auto:
                    pol._auto_pick(me)
                ca = pol.comp_action(v, mask)                  # 阵容动作优先
                a = int(ca) if ca is not None else int(game.bot_action(0))
            if not (0 <= a < 245 and bool(mask[a])):
                illegal += 1                                   # 期望恒为 0
                nz = np.flatnonzero(mask)
                a = int(nz[0]) if nz.size else A_END
            game.step(0, a)
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    place = list(game.placements())
    pj = json.loads(game.player_json(0))
    final = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                for m in (pj.get("board") or []))
    by_turn = {int(s["turn"]): s for s in pol.snaps}

    def at(t: int) -> dict:
        if t in by_turn:
            return by_turn[t]
        best: dict = {}
        for k in sorted(by_turn):
            if k <= t:
                best = by_turn[k]
        return best

    t15 = at(15)
    return {
        "seed": int(seed),
        "comp": (pol.spec.key if pol.spec else "generic"),
        "comp_name": (pol.spec.name if pol.spec else "generic"),
        "placement": int(place[0]) if place else 0,
        "sigma_t15": int(t15.get("strength") or final),
        "decisions": int(decisions),
        "illegal": int(illegal),
        "fit9": fit9,
        "fit_turn": {str(k): round(v, 3) for k, v in sorted(fit_turn.items())},
        "core_turn": int(min(pol.core_seen.values()) if pol.core_seen else -1),
        "exited": bool(pol.exited),
        "survival": len(pol.snaps),
        "tier_t15": int(t15.get("tier") or 0),
        "types_t15": int(t15.get("types") or 0),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CompPolicy 只读探针（不训练）")
    ap.add_argument("--comp", default="auto", help="auto | A..N | f_dragon（同 comp_scripts）")
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=910000)
    ap.add_argument("--mode", default="bot", choices=["bot", "p09"],
                    help="bot = 7 席引擎 bot；p09 = 5 席人类战团 p0.9（同 baseline_p09）")
    ap.add_argument("--human-boards", default=os.path.join(
        ROOT, "data/real_library/library_real_quasi_full.jsonl"))
    ap.add_argument("--human-seats", type=int, default=5)
    ap.add_argument("--human-p", type=float, default=0.9)
    ap.add_argument("--human-fidelity", default="full")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    key = str(args.comp)
    if key.upper() == "BOT":
        print("[probe] --comp BOT 是 comp_scripts 的基线组，本探针只测脚本", file=sys.stderr)
        return 2
    if key.lower() == "auto":
        spec, auto = None, True
    else:
        spec, auto = CS.COMPS.get(key.upper() if key.upper() in CS.COMPS else key), False
        if spec is None:
            print(f"[probe] 未知阵容 {key!r}；可选 {sorted(CS.COMPS)}", file=sys.stderr)
            return 2

    pool = None
    if args.mode == "p09":
        from hsbg.az.train.human_board_pool import load_pool
        pool = load_pool(args.human_boards, sample="auto")

    t0 = time.time()
    rows: List[dict] = []
    errors = 0
    for i in range(int(args.games)):
        try:
            r = play_one(int(args.seed0) + i, spec, auto=auto, mode=args.mode,
                         human_pool=pool, human_seats=args.human_seats,
                         human_p=args.human_p, human_fidelity=args.human_fidelity)
        except BaseException as e:  # noqa: BLE001
            errors += 1
            print(f"[probe] seed={int(args.seed0) + i} 异常 {type(e).__name__}: {e}",
                  file=sys.stderr)
            continue
        if r is None:
            errors += 1
            continue
        rows.append(r)
        if i % 10 == 0:
            print(f"[probe] {i + 1}/{args.games} t={time.time() - t0:.0f}s", flush=True)

    decisions = sum(r["decisions"] for r in rows)
    illegal = sum(r["illegal"] for r in rows)
    fit9 = [r["fit9"] for r in rows if r["fit9"] is not None]
    summ = {
        "comp": key,
        "mode": args.mode,
        "protocol": "seat0=CompPolicy(hybrid) vs 7 engine bots" if args.mode == "bot"
                    else f"seat0=CompPolicy(hybrid) vs {args.human_seats} human seats p={args.human_p} + bots",
        "games": len(rows),
        "errors": errors,
        "decisions": decisions,
        "illegal": illegal,
        "legal_rate": round(1.0 - illegal / max(1, decisions), 6),
        "mean_rank": round(float(np.mean([r["placement"] for r in rows])), 3) if rows else None,
        "top4_rate": round(float(np.mean([1.0 if 0 < r["placement"] <= 4 else 0.0
                                          for r in rows])), 3) if rows else None,
        "win_rate": round(float(np.mean([1.0 if r["placement"] == 1 else 0.0
                                         for r in rows])), 3) if rows else None,
        "sigma_t15_p50": _pct([r["sigma_t15"] for r in rows], 0.5),
        "sigma_t15_p90": _pct([r["sigma_t15"] for r in rows], 0.9),
        "sigma_t15_max": max((r["sigma_t15"] for r in rows), default=0),
        "fit_t9_mean": round(float(np.mean(fit9)), 3) if fit9 else None,
        "fit_t9_p50": _pct(fit9, 0.5),
        "fit_t9_p90": _pct(fit9, 0.9),
        "fit_t9_n": len(fit9),
        "core_turn_p50": _pct([r["core_turn"] for r in rows if r["core_turn"] > 0], 0.5),
        "core_rate": round(float(np.mean([1.0 if r["core_turn"] > 0 else 0.0
                                          for r in rows])), 3) if rows else None,
        "exit_rate": round(float(np.mean([1.0 if r["exited"] else 0.0 for r in rows])), 3)
        if rows else None,
        "survival_p50": _pct([r["survival"] for r in rows], 0.5),
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(summ, ensure_ascii=False, indent=1), flush=True)
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"summary": summ, "rows": rows}, f, ensure_ascii=False, indent=1)
        print(f"[probe] rows -> {args.json_out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
