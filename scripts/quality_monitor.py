#!/usr/bin/env python3
"""对局质量监控：逐回合记录我方战团强度/经济，并与真实 10k+ MMR 同 turn 分位对比。

指标（learner seat）：
- board_strength = Σ(atk+hp)，board_count，tier，gold，health，turn
- 死亡回合、死亡时战团强度、每 turn 的强度分位
对比基准：data/real_library/strength_calibration.json 的 real p50/p75/p90（分 turn）。

用法::

  PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
    --checkpoint runs/champion_c0_1746.pt --device cuda:2 --games 256 \
    --seed-base 520000 --out runs/quality/champ_1746.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, mask_from_bytes, obs_arrays  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402


def _board_stats(pj: dict) -> dict:
    board = pj.get("board") or []
    strength = 0
    for m in board:
        strength += int(m.get("atk") or 0) + int(m.get("hp") or 0)
    return {"strength": strength, "count": len(board)}


def _board_sig(game, seat: int = 0) -> list[str]:
    """棋盘卡牌序列（**顺序敏感**）：换位的净效果就看这个签名是否变化。"""
    pj = json.loads(game.player_json(int(seat)))
    return [str(m.get("card")) for m in (pj.get("board") or [])]


def _play(seed: int, policy, q: dict) -> dict | None:
    """跑一局；返回 {'placement','death_turn','death_strength','turns':[{...}]}。

    每个 turn 行额外记录 ``moves``（本回合 learner 选择的换位次数）、
    ``board_start``/``board_end``（回合内 learner **最后一次行动后**的棋盘卡牌序列），
    用于统计「每回合换位次数」与「净盘面不变回合比例」。
    """
    import hsbg_engine as E

    game = E.Game(seed=int(seed))
    policy.reset()
    turns = []
    last_turn = -1
    steps = 0
    max_steps = int((q or {}).get("max_steps", 20000) or 20000)
    # 与 official eval（hsbg/az/train/evaluate.py）一致：**每个 pass 每个座位只走一步**。
    # 不能用 `while needs_action(p)`：引擎可能在一次 EndTurn 后立刻推进到下一回合，
    # 会把两个回合的 learner 动作记进同一行（历史 quality_monitor 的 turn 行会错位）。
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pj = json.loads(game.player_json(0))
            bs = _board_stats(pj)
            turns.append({"turn": t, "strength": bs["strength"], "count": bs["count"],
                          "tier": int(pj.get("tier") or 0), "gold": int(pj.get("gold") or 0),
                          "health": int(pj.get("health") or 0),
                          "alive": bool(pj.get("alive", True)),
                          "moves": 0, "move_legal": False,
                          "board_start": [str(m.get("card")) for m in (pj.get("board") or [])],
                          "board_end": None})
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == 0:
                m = mask_from_bytes(game.legal_mask(0))
                if bool(m[196:245].any()):
                    turns[-1]["move_legal"] = True
                a = int(policy.decide(game, 0).action)
                if not (0 <= a < 245 and bool(m[a])):
                    nz = np.flatnonzero(m)
                    a = int(nz[0]) if nz.size else 0
                if 196 <= a < 245:      # Move 段：196..244
                    turns[-1]["moves"] = int(turns[-1].get("moves", 0)) + 1
                game.step(0, a)
                # 只取「learner 行动后、战斗前」的盘面，避免战斗死亡污染净盘面判定
                turns[-1]["board_end"] = _board_sig(game)
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    placements = list(game.placements())
    death_turn = None
    death_strength = None
    alive_rows = [row for row in turns if row["alive"]]
    if alive_rows:
        # 取死亡前最后一个「非空战团」回合；若最后一行恰好被清空（终局/战斗后），回退一格
        pick = alive_rows[-1]
        for row in reversed(alive_rows):
            if row["strength"] > 0:
                pick = row
                break
        death_turn, death_strength = pick["turn"], pick["strength"]
    return {"placement": int(placements[0]), "death_turn": death_turn,
            "death_strength": death_strength, "turns": turns}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/champion_c0_1746.pt")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=256)
    ap.add_argument("--seed-base", type=int, default=520000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--calibration", default="data/real_library/strength_calibration.json")
    ap.add_argument("--move-guard", type=int, default=0, choices=[0, 1],
                    help="1=评测时也启用换位去抖守卫（默认 0=纯模型行为）")
    ap.add_argument("--move-cap", type=int, default=3,
                    help="每回合换位次数上限（仅 --move-guard 1 时生效；默认 3）")
    ap.add_argument("--move-repeat-limit", type=int, default=2,
                    help="同一 (from,to) 本回合出现 >=N 次后屏蔽（默认 2）")
    ap.add_argument("--out", default="runs/quality/quality.json")
    args = ap.parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    from hsbg.az.train.ppo import CollectConfig
    cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps),
                        move_guard=bool(int(args.move_guard)),
                        move_cap=int(args.move_cap),
                        move_repeat_limit=int(args.move_repeat_limit))
    policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                               seed=int(args.seed_base), move_model=False)

    rows = []
    for g in range(int(args.games)):
        r = _play(int(args.seed_base) + g, policy, cfg.__dict__)
        if r:
            rows.append(r)
    # 聚合：每 turn 的强度分位
    by_turn: dict[int, list[int]] = {}
    deaths: dict[int, list[int]] = {}
    tiers: dict[int, list[int]] = {}
    golds: dict[int, list[int]] = {}
    turn_moves: dict[int, list[int]] = {}
    all_turn_moves: list[int] = []
    net_unchanged = 0
    net_measured = 0
    move_legal_turns = 0
    move_turns = 0
    net_unchanged_move_turns = 0
    for r in rows:
        for row in r["turns"]:
            by_turn.setdefault(row["turn"], []).append(row["strength"])
            tiers.setdefault(row["turn"], []).append(row["tier"])
            golds.setdefault(row["turn"], []).append(row["gold"])
            n_mv = int(row.get("moves", 0) or 0)
            all_turn_moves.append(n_mv)
            turn_moves.setdefault(row["turn"], []).append(n_mv)
            if bool(row.get("move_legal")):
                move_legal_turns += 1
            if n_mv > 0:
                move_turns += 1
            be, bs = row.get("board_end"), row.get("board_start")
            if be is not None and bs is not None:
                net_measured += 1
                same = list(be) == list(bs)
                if same:
                    net_unchanged += 1
                if n_mv > 0 and same:
                    net_unchanged_move_turns += 1
        dt = r["death_turn"] or 0
        if r["placement"] > 1 and r["death_strength"] is not None:
            deaths.setdefault(dt, []).append(r["death_strength"])
    calib = {}
    if os.path.isfile(args.calibration):
        calib = json.load(open(args.calibration))
    summary = []
    for t in sorted(by_turn):
        v = np.asarray(by_turn[t])
        real = (calib.get(str(t)) or {}).get("real") or {}
        summary.append({
            "turn": t, "n": int(v.size),
            "ours_p50": float(np.percentile(v, 50)), "ours_p90": float(np.percentile(v, 90)),
            "ours_max": float(v.max()),
            "real_p50": real.get("p50"), "real_p75": real.get("p75"), "real_p90": real.get("p90"),
            "ratio_p50": (float(np.percentile(v, 50)) / real["p50"]) if real.get("p50") else None,
            "tier_p50": float(np.percentile(tiers[t], 50)),
            "gold_p50": float(np.percentile(golds[t], 50)),
            "moves_mean": float(np.mean(turn_moves[t])),
            "moves_max": int(np.max(turn_moves[t])),
        })
    if deaths:
        all_deaths = [s for v in deaths.values() for s in v]
        death_turns = [t for t, v in deaths.items() for _ in v]
    else:
        all_deaths, death_turns = [], []
    out = {"checkpoint": args.checkpoint, "games": len(rows),
           "seed_base": int(args.seed_base),
           "placements": [r["placement"] for r in rows],
           "mean_rank": float(np.mean([r["placement"] for r in rows])) if rows else None,
           "top4": float(np.mean([r["placement"] <= 4 for r in rows])) if rows else None,
           "win": float(np.mean([r["placement"] == 1 for r in rows])) if rows else None,
           "death_turn_hist": {str(t): len(v) for t, v in sorted(deaths.items())},
           "death_strength_p50": float(np.percentile(all_deaths, 50)) if all_deaths else None,
           "death_strength_mean": float(np.mean(all_deaths)) if all_deaths else None,
           "by_turn": summary,
           "death_turn_p50": float(np.percentile(death_turns, 50)) if death_turns else None,
           # ── 换位去抖（guard）指标 ──
           "move_guard": bool(int(args.move_guard)),
           "move_cap": int(args.move_cap),
           "move_repeat_limit": int(args.move_repeat_limit),
           "turns_total": int(len(all_turn_moves)),
           "move_actions_total": int(sum(all_turn_moves)),
           "moves_per_turn_mean": (float(np.mean(all_turn_moves))
                                   if all_turn_moves else 0.0),
           "moves_per_turn_p50": (float(np.percentile(all_turn_moves, 50))
                                  if all_turn_moves else 0.0),
           "moves_per_turn_p90": (float(np.percentile(all_turn_moves, 90))
                                  if all_turn_moves else 0.0),
           "moves_per_turn_max": int(np.max(all_turn_moves)) if all_turn_moves else 0,
           "turns_with_move": int(sum(1 for v in all_turn_moves if v > 0)),
           "turns_with_move_ratio": (float(np.mean([1.0 if v > 0 else 0.0
                                                    for v in all_turn_moves]))
                                     if all_turn_moves else 0.0),
           "move_legal_turns": int(move_legal_turns),
           "moves_per_move_legal_turn_mean": (float(sum(all_turn_moves))
                                              / move_legal_turns
                                              if move_legal_turns else 0.0),
           "move_turns": int(move_turns),
           "moves_per_move_turn_mean": (float(sum(all_turn_moves)) / move_turns
                                       if move_turns else 0.0),
           "net_board_unchanged_turns": int(net_unchanged),
           "net_board_unchanged_measured": int(net_measured),
           "net_board_unchanged_ratio": (float(net_unchanged) / net_measured
                                         if net_measured else 0.0),
           "net_board_unchanged_move_turns": int(net_unchanged_move_turns),
           "net_board_unchanged_move_ratio": (float(net_unchanged_move_turns)
                                              / move_turns if move_turns else 0.0),
           "tier_p50_t9": (next((row["tier_p50"] for row in summary
                                 if row["turn"] == 9), None)),
           "tier_p50_t12": (next((row["tier_p50"] for row in summary
                                  if row["turn"] == 12), None)),
           "move_guard_meta": policy.move_guard_meta()}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(json.dumps({k: out[k] for k in (
        "games", "mean_rank", "top4", "win", "death_turn_p50", "death_strength_p50",
        "moves_per_turn_mean", "moves_per_turn_p90", "moves_per_turn_max",
        "moves_per_move_legal_turn_mean", "moves_per_move_turn_mean",
        "net_board_unchanged_turns", "net_board_unchanged_ratio",
        "net_board_unchanged_move_turns", "net_board_unchanged_move_ratio",
        "tier_p50_t9", "tier_p50_t12")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
