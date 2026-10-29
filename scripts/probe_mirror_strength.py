#!/usr/bin/env python3
"""镜像快照难度探针：learner=指定 checkpoint（seat0），对手席位按 arm 注入
「我们自采的 EOT 快照」或保持引擎 bot，比较 learner 名次。

arm 0 : 全 bot
arm N : seat1..N 每回合开始注入 snapshot（来自 --snap-dir），其余 bot

**回合推进（2026-10-29 修复）**：注入调用带 ``advance=True``。注入把目标座位置
``ended_turn=true``；如果**所有存活座位**都已被注入（常见于后期：learner 与 bot 已淘汰，
只剩镜像座位），引擎必须立刻打一场并进入下一回合，否则探针会看到「没有任何座位
needs_action 但局未结束」而退出（旧版 18/40 终局的根因，见
``docs/MIRROR_PROBE_DIAGNOSIS.md``）。若推进真的发生了（turn 变化），回到循环顶部给新
回合重新注入，绝不让新回合的座位在注入前行动。

用法::

  PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python scripts/probe_mirror_strength.py \
      --checkpoint runs/champion_c0_2279.pt --device cuda:3 \
      --snap-dir runs/library/snaps_champ --games 40 --arms 0,2,3 \
      --seed 92001 --out runs/library/probe_mirror_fixed.json

``--no-advance`` 复现旧行为（注入不推进），仅用于诊断对照。
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available  # noqa: E402
from hsbg.az.train.mirror_snapshots import (MirrorStats, inject_turn, load_pool,  # noqa: E402
                                            mirror_seats)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402


def _reject_kind(reason: str) -> str:
    """把引擎拒绝理由归一成可聚合的分类（``pending_choice(2)`` -> ``pending_choice``）。"""
    s = str(reason)
    head = s.split("(", 1)[0].strip()
    return head if head else ("empty" if not s else "other")


def _stall_snapshot(game) -> dict:
    """未终局退出时的最小现场。

    ``Game`` 没有 phase getter，但 ``state_json()`` 序列化了 ``phase``（Recruit/GameOver/
    HeroSelect）；卡死时用一次完整 state 读取来确证「仍在 Recruit、所有存活座位 ended_turn」。
    """
    try:
        phase = str(json.loads(game.state_json()).get("phase"))
    except BaseException:  # noqa: BLE001 - 诊断字段，失败不影响主流程
        phase = "unknown"
    seats = []
    for p in range(int(game.num_players)):
        pj = json.loads(game.player_json(p))
        seats.append({"seat": p, "alive": bool(pj.get("alive")),
                      "ended_turn": bool(pj.get("ended_turn")),
                      "health": int(pj.get("health", 0)),
                      "pending": len(pj.get("pending") or []),
                      "board": len(pj.get("board") or []),
                      "needs_action": bool(game.needs_action(p))})
    return {"turn": int(game.turn), "is_over": bool(game.is_over()), "phase": phase,
            "needs_action": [bool(game.needs_action(p)) for p in range(8)],
            "placements": [int(x) for x in game.placements()],
            "health": [int(x) for x in game.health()], "seats": seats}


def _play(arm: int, game_seed: int, learner, pool, temperature: float, max_steps: int,
          inject_advance: bool = True):
    """一局。返回 dict：rank（未终局为 None）/steps/stats/诊断计数。

    ``inject_advance=False`` 复现旧版（注入不推进）；``inject_advance=True`` 时还会在
    「无人需要行动但局未结束」时做一次防御性推进，正常情况下不该触发。
    """
    import hsbg_engine as E
    game = E.Game(seed=int(game_seed))
    rng = random.Random(int(game_seed) + 13)
    stats = MirrorStats()
    seats = mirror_seats(arm) if (pool is not None and arm > 0) else []
    last_turn = -1
    steps = 0
    t0 = time.time()
    turn_ms: list[float] = []
    reject_kinds: collections.Counter = collections.Counter()
    diag = {"inject_advances": 0, "forced_advance": 0, "no_action_stall": 0,
            "max_steps_hit": 0, "stall": None}
    while not game.is_over() and steps < int(max_steps):
        t_turn = time.time()
        if int(game.turn) != last_turn:
            last_turn = int(game.turn)
            if seats:
                # 清空上一回合的拒绝明细，保证本回合（<=7 个座位）的分类不因 16 条上限丢失。
                stats.last_rejected[:] = []
                inject_turn(game, pool, last_turn, seats=seats, p=1.0, rng=rng,
                            stats=stats, advance=inject_advance)
                for item in stats.last_rejected:
                    reject_kinds[_reject_kind(item[1])] += 1
                stats.last_rejected[:] = []
                if game.is_over():
                    break
                if int(game.turn) != last_turn:
                    # 所有存活座位都被注入 -> fight_when_all_ended 已推进；新回合必须在任何
                    # 座位行动前重新注入，否则这一回合会变成「未注入的 bot 回合」。
                    diag["inject_advances"] += 1
                    turn_ms.append((time.time() - t_turn) * 1000.0)
                    continue
        acted = False
        for p in range(8):
            if game.is_over() or not game.needs_action(p):
                continue
            acted = True
            if p == 0:
                game.step(0, int(learner.decide(game, 0).action))
            else:
                game.bot_play(int(p))
            steps += 1
            if game.is_over() or int(game.turn) != last_turn:
                break   # 回合已推进：先回到回合起点注入，再让剩余座位行动
        turn_ms.append((time.time() - t_turn) * 1000.0)
        if not acted:
            # 防御：所有存活座位 ended_turn=true 时 apply_turn_snapshots([], advance=True)
            # 只调用一次 fight_when_all_ended（不注入任何座位）。
            if not game.is_over() and inject_advance:
                game.apply_turn_snapshots([], True)
                diag["forced_advance"] += 1
                if int(game.turn) != last_turn:
                    continue
            if not game.is_over():
                diag["no_action_stall"] += 1
                diag["stall"] = _stall_snapshot(game)
            break
    if not game.is_over() and steps >= int(max_steps):
        diag["max_steps_hit"] = 1
    rank = int(list(game.placements())[0]) if game.is_over() else None
    return {"rank": rank, "steps": steps, "turn": int(game.turn),
            "stats": stats, "reject_kinds": reject_kinds, "diag": diag,
            "sec": time.time() - t0,
            "truncated_combats": int(game.truncated_combats),
            "turn_limit_end": bool(game.turn_limit_end),
            "mean_turn_ms": (float(np.mean(turn_ms)) if turn_ms else 0.0),
            "max_turn_ms": (float(np.max(turn_ms)) if turn_ms else 0.0),
            # 每回合首个计时点包含 CUDA/图编译预热（第一局第一回合可到 ~200ms），
            # 判断「战斗是否慢」时应排除它。
            "first_turn_ms": (float(turn_ms[0]) if turn_ms else 0.0),
            "max_turn_ms_after_first": (float(np.max(turn_ms[1:]))
                                        if len(turn_ms) > 1 else 0.0)}


def _pool_stats(pool) -> dict:
    """快照池静态统计（H3：pool_copies=0 / 超大身材 / 超长 board 是否会拖慢战斗）。"""
    if pool is None:
        return {}
    frames = [f for v in pool.index.values() for f in v]
    boards = [len((f.player.get("board") or [])) for f in frames]
    atk, hp, copies0, copies = [], [], 0, 0
    for f in frames:
        for m in f.player.get("board") or []:
            atk.append(int(m.get("atk", 0)))
            hp.append(int(m.get("hp", 0)))
            copies += 1
            if int(m.get("pool_copies", 0) or 0) <= 0:
                copies0 += 1
    return {"frames": len(frames), "board_min": int(min(boards)) if boards else 0,
            "board_max": int(max(boards)) if boards else 0,
            "atk_max": int(max(atk)) if atk else 0, "hp_max": int(max(hp)) if hp else 0,
            "board_minions": copies, "pool_copies_zero": copies0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/champion_c0_2279.pt")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--snap-dir", default="runs/library/snaps_champ")
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--arms", default="0,2,3")
    ap.add_argument("--seed", type=int, default=92001)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--no-advance", action="store_true",
                    help="复现旧行为：注入后不推进回合（仅诊断对照）")
    ap.add_argument("--out", default="runs/library/probe_mirror.json")
    args = ap.parse_args()
    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2

    import hashlib
    src_hashes = {}
    for rel in ("scripts/probe_mirror_strength.py", "hsbg/az/train/mirror_snapshots.py",
                "hsbg/az/train/ppo.py", "hsbg/az/train/model.py",
                "hsbg/az/train/entity_model.py"):
        try:
            with open(os.path.join(ROOT, rel), "rb") as f:
                src_hashes[rel] = hashlib.sha256(f.read()).hexdigest()[:16]
        except BaseException:  # noqa: BLE001 - 仅审计字段
            src_hashes[rel] = None
    import hsbg_engine as E
    engine_stamp = {"engine": str(E.version()), "game": str(E.game_version())}
    print(f"[probe] source hashes {src_hashes}", flush=True)

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    evaluator = PPOEvaluator(model, device=args.device,
                             norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(args.seed), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps), temperature=float(args.temperature))
    learner = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=evaluator,
                                seed=int(args.seed), move_model=False)
    pool = load_pool(args.snap_dir)
    pstats = _pool_stats(pool)
    print(f"[probe] pool={args.snap_dir} frames={0 if pool is None else pool.frames} "
          f"advance={not args.no_advance}", flush=True)
    rows = []
    t0 = time.time()
    for arm in [int(x) for x in str(args.arms).split(",") if x.strip()]:
        ranks, steps_all = [], []
        agg = MirrorStats()
        reject_kinds: collections.Counter = collections.Counter()
        diag_agg = {"inject_advances": 0, "forced_advance": 0, "no_action_stall": 0,
                    "max_steps_hit": 0}
        stalls, slowest = [], []
        for g in range(int(args.games)):
            learner.reset()
            out = _play(arm, int(args.seed) + g, learner, pool,
                        float(args.temperature), int(args.max_steps),
                        inject_advance=not args.no_advance)
            r, st = out["rank"], out["steps"]
            ms = out["stats"]
            if r is not None:
                ranks.append(r)
            steps_all.append(st)
            for k in ("attempt", "applied", "rejected", "missing", "errors",
                      "pool_unbalanced", "pool_species_unbalanced"):
                setattr(agg, k, getattr(agg, k) + getattr(ms, k))
            reject_kinds.update(out["reject_kinds"])
            for k in diag_agg:
                diag_agg[k] += int(out["diag"][k])
            if out["diag"]["stall"] is not None and len(stalls) < 3:
                stalls.append({"seed": int(args.seed) + g, **out["diag"]["stall"]})
            slowest.append({"seed": int(args.seed) + g,
                            "sec": round(float(out["sec"]), 3), "turn": int(out["turn"]),
                            "steps": int(st), "terminal": r is not None,
                            "truncated_combats": int(out["truncated_combats"]),
                            "turn_limit_end": bool(out["turn_limit_end"]),
                            "mean_turn_ms": round(float(out["mean_turn_ms"]), 2),
                            "max_turn_ms": round(float(out["max_turn_ms"]), 2),
                            "first_turn_ms": round(float(out["first_turn_ms"]), 2),
                            "max_turn_ms_after_first": round(
                                float(out["max_turn_ms_after_first"]), 2)})
        n = int(args.games)
        row = {"arm": arm, "games_played": n, "games": len(ranks),
               "terminal": len(ranks), "n_terminal": len(ranks),
               "terminal_rate": round(len(ranks) / n, 4) if n else 0.0}
        if ranks:
            row.update({
                "mean_rank": round(float(np.mean(ranks)), 4),
                "top4": round(float(np.mean([x <= 4 for x in ranks])), 4),
                "win": round(float(np.mean([x == 1 for x in ranks])), 4),
                "mean_steps": round(float(np.mean(steps_all)), 1),
                "mean_turn": round(float(np.mean([s["turn"] for s in slowest])), 1),
                "placements": ranks,
            })
        row["mirror"] = {k: getattr(agg, k) for k in
                         ("attempt", "applied", "rejected", "missing", "errors",
                          "pool_unbalanced", "pool_species_unbalanced")}
        row["mirror"]["rejected_reasons"] = dict(sorted(reject_kinds.items()))
        row["diagnostics"] = {
            **diag_agg,
            "truncated_combats": int(sum(s["truncated_combats"] for s in slowest)),
            "turn_limit_end": int(sum(1 for s in slowest
                                      if s.get("turn_limit_end"))),
            "mean_game_s": round(float(np.mean([s["sec"] for s in slowest])), 3),
            "max_game_s": round(float(max(s["sec"] for s in slowest)), 3),
            "mean_turn_ms": round(float(np.mean([s["mean_turn_ms"] for s in slowest])), 2),
            "max_turn_ms": round(float(max(s["max_turn_ms_after_first"] for s in slowest)), 2),
            "warmup_turn_ms": round(float(max(s["first_turn_ms"] for s in slowest)), 2),
            "slowest": sorted(slowest, key=lambda s: -s["sec"])[:5],
            "stalls": stalls,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False)[:600], flush=True)
    base = next((r for r in rows if r["arm"] == 0 and r.get("games")), None)
    out = {"checkpoint": args.checkpoint, "snap_dir": args.snap_dir,
           "pool_frames": 0 if pool is None else int(pool.frames),
           "pool_stats": pstats,
           "advance": not args.no_advance,
           "engine": engine_stamp, "source_hashes": src_hashes,
           "games_per_arm": int(args.games), "seed_base": int(args.seed),
           "elapsed_s": round(time.time() - t0, 1), "arms": rows,
           "delta_vs_arm0": {str(r["arm"]): (round(r["mean_rank"] - base["mean_rank"], 4)
                                            if base and r.get("games") else None)
                              for r in rows}}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"delta_vs_arm0": out["delta_vs_arm0"],
                      "terminal_rate": {str(r["arm"]): r["terminal_rate"] for r in rows},
                      "elapsed_s": out["elapsed_s"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
