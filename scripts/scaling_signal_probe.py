#!/usr/bin/env python3
"""缩放行为信号探测（离线，纯 CPU，不训练、不占 GPU）。

问题：**终局名次奖励对「缩放行为」（施法 / 金色化 / 酒馆永久 buff）是否存在可学梯度？
∞金币课程能否把不可学信号变成可学信号？**

做法（不改引擎、不改训练）：
- 策略＝给定 checkpoint 的 s15 权重，走训练采集的**同一条代码路径**
  （``PPOSelfPlayPolicy`` + ``behavior=net`` / ``temperature=1`` / ``move_guard`` /
  ``max_actions_per_turn``），不训练、不搜索。
- 对手＝s15 训练分布复刻：``human_board_p=0.9`` 的 5 席人类战团注入
  （``library_real_quasi_full.jsonl``，``fidelity=full``，``set_tier=1``，
  ``sample=auto``）＋ ``mirror_p=0.2`` 的 2 席回合末快照镜像
  （``runs/library/snaps_champ``，``sample=p75``）＋ 其余引擎 bot。
- 每个 turn 在 learner **结束招募前**（EndTurn 动作之前）取一次 ``player_json(0)`` 快照，
  记录战团 Σ(atk+hp)、tier、金币、以及引擎 ``PlayerStats`` 计数：
  ``tavern_spells_cast`` / ``spells_cast`` / ``golden_played`` / ``tavern_atk+tavern_hp``
  / ``minions_bought`` / ``gold_spent_total`` / ``cards_played`` 等。
- ``--record-opponents 1``（默认）：同一时刻再取一次 ``view(0)``，记录 7 席对手**当前**
  战团 Σ（含人类战团 / 镜像快照），用于「相对身材 vs 名次」的阈值平坦性分析。
- ``--gold`` >0 时每个新回合开始 ``debug set_player gold=N``（与
  ``scripts/engine_ceiling_probe.py --cheat gold`` 同法），即「∞金币课程」条件。

产物：``runs/scaling_signal/rollouts/<tag>.jsonl``（每行一局）+ ``<tag>.meta.json``。

用法::

  PYTHONPATH=rust/python:. python scripts/scaling_signal_probe.py \\
      --checkpoint runs/scaling_signal/ckpt/s15_step301.pt --games 200 --tag real \\
      --workers 10 --device cpu
  ... --games 200 --gold 99 --tag gold99
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
import traceback

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

#: 每局快照里保留的引擎 PlayerStats 计数（全部来自 `Game.player_json(seat)["stats"]`）
STAT_KEYS = (
    "tavern_spells_cast",       # 酒馆法术施放总数（本局累计）
    "spells_cast",              # 所有法术（含手牌/技能法术）
    "spellcraft_cast",          # Spellcraft 法术
    "golden_played",            # 金色随从生成/打出次数（三连）
    "tavern_atk",               # 酒馆随从永久 +atk（本局累计）
    "tavern_hp",                # 酒馆随从永久 +hp
    "tavern_elemental_atk",
    "tavern_elemental_hp",
    "minions_bought",
    "cards_played",
    "cards_discarded",
    "gold_spent_total",
    "refreshes",
    "battlecries_triggered",
    "deathrattles_triggered",
    "elementals_played",
    "combats_won",
    "combats_lost",
)

# ── worker 全局（每个进程只加载一次）─────────────────────────────────────────
_E = None
_POLICY = None
_HUMAN_POOL = None
_MIRROR_POOL = None
_CFG: dict = {}


def _board_stats(pj: dict) -> dict:
    board = pj.get("board") or []
    strength = 0
    for m in board:
        strength += int(m.get("atk") or 0) + int(m.get("hp") or 0)
    return {"strength": strength, "count": len(board),
            "golden_on_board": sum(1 for m in board if m.get("golden"))}


def _snap(g, stage: str) -> dict:
    """learner 快照：战团 + 引擎 PlayerStats（一次 ``player_json``，约 0.13 ms）。

    ``stage="recruit_end"`` 且开了 ``record_opponents`` 时，额外取一次 ``view(0)``
    记录 7 席对手当前战团 Σ（离线诊断用；不是策略观测）。
    """
    pj = json.loads(g.player_json(0))
    st = pj.get("stats") or {}
    bs = _board_stats(pj)
    rec = {
        "turn": int(g.turn),
        "stage": stage,
        "strength": int(bs["strength"]),
        "count": int(bs["count"]),
        "golden_on_board": int(bs["golden_on_board"]),
        "tier": int(pj.get("tier") or 0),
        "gold": int(pj.get("gold") or 0),
        "health": int(pj.get("health") or 0),
        "armor": int(pj.get("armor") or 0),
        "alive": bool(pj.get("alive", True)),
        "stats": {k: int(st.get(k) or 0) for k in STAT_KEYS},
        "board_cards": [str(m.get("card")) for m in (pj.get("board") or [])],
    }
    if _CFG.get("record_opponents") and stage == "recruit_end":
        try:
            v = json.loads(g.view(0))
            opp = []
            for o in (v.get("opponents") or []):
                if not o.get("alive", True):
                    continue
                opp.append(sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                               for m in (o.get("board") or [])))
            rec["opp_strengths"] = opp
            rec["opp_max"] = int(max(opp)) if opp else 0
            rec["opp_mean"] = round(float(sum(opp)) / len(opp), 1) if opp else 0.0
            rec["opp_n"] = len(opp)
            rec["alive_count"] = int(v.get("alive") or len(opp) + 1)
        except BaseException:  # noqa: BLE001
            rec["opp_strengths"] = None
    return rec


def _init_worker(cfg: dict) -> None:
    global _E, _POLICY, _HUMAN_POOL, _MIRROR_POOL, _CFG
    _CFG = dict(cfg)
    import torch
    try:
        torch.set_num_threads(1)          # 多进程各 1 线程，避免 CPU 过度订阅
    except BaseException:                 # noqa: BLE001
        pass
    import hsbg_engine as E
    _E = E
    from hsbg.az.train.ppo import PPOEvaluator, PPOSelfPlayPolicy, CollectConfig
    from hsbg.az.train.model import load_checkpoint
    dev = str(cfg["device"])
    model, meta = load_checkpoint(str(cfg["checkpoint"]), device=dev)
    ev = PPOEvaluator(model, device=dev,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cc = CollectConfig(games=1, seed=int(cfg["seed_base"]), opponent="bot",
                       behavior="net", max_steps=int(cfg["max_steps"]),
                       max_actions_per_turn=int(cfg["max_actions_per_turn"]),
                       move_guard=bool(int(cfg["move_guard"])),
                       move_cap=int(cfg["move_cap"]),
                       move_repeat_limit=int(cfg["move_repeat_limit"]),
                       fast_act=True, temperature=1.0)
    _POLICY = PPOSelfPlayPolicy(model, device=dev, config=cc, eval_fn=ev,
                                seed=int(cfg["seed_base"]), move_model=False)
    _CFG["_collect_cfg"] = cc.__dict__
    if float(cfg["human_board_p"]) > 0.0:
        from hsbg.az.train.human_board_pool import load_pool as _load_human
        _HUMAN_POOL = _load_human(str(cfg["human_boards"]),
                                  sample=str(cfg["human_board_sample"]))
        if _HUMAN_POOL is None:
            raise RuntimeError(f"人类战团库为空/不存在: {cfg['human_boards']}")
    if float(cfg["mirror_p"]) > 0.0:
        from hsbg.az.train.mirror_snapshots import load_pool as _load_mirror
        _MIRROR_POOL = _load_mirror(str(cfg["mirror_snaps"]),
                                    sample=str(cfg["mirror_sample"]))
        if _MIRROR_POOL is None:
            print(f"[warn] 回合末快照库为空/不存在: {cfg['mirror_snaps']}", flush=True)


def _play_one(seed: int) -> dict:
    """驱动一局：learner=seat 0，其余 7 席按训练分布（镜像→人类战团→引擎 bot）。"""
    from hsbg.az.train.common import mask_from_bytes

    E = _E
    policy = _POLICY
    cfg = _CFG
    seat = 0
    gold = int(cfg["gold"])
    max_steps = int(cfg["max_steps"])
    t0 = time.time()
    policy.reset()
    policy.reseed(int(seed))
    policy.game_id = int(seed)
    g = E.Game(int(seed))

    rows: list = []
    human_stats = None
    mirror_stats = None
    applied: list = []
    mirror_turn = int(g.turn)
    human_turn = int(g.turn)
    gold_turn = int(g.turn) - 1      # 允许 turn 1 就生效（与 ceiling probe 一致）
    mirror_rng = random.Random(int(seed) * 31 + 7)
    human_rng = random.Random(int(seed) * 53 + 11)
    steps = 0
    truncated = False
    n_inject = {"mirror": 0, "human": 0}
    ended_snap_turn = -1

    def maybe_inject() -> None:
        """新回合开始、任何座位行动前：镜像快照 → 人类战团 → ∞金币。"""
        nonlocal mirror_turn, human_turn, gold_turn, applied, human_stats, mirror_stats
        t = int(g.turn)
        if t != mirror_turn:
            mirror_turn = t
            applied = []
            if _MIRROR_POOL is not None and float(cfg["mirror_p"]) > 0.0:
                from hsbg.az.train.mirror_snapshots import (MirrorStats, inject_turn,
                                                           mirror_seats)
                mirror_stats = mirror_stats or MirrorStats()
                inject_turn(g, _MIRROR_POOL, t,
                            seats=mirror_seats(int(cfg["mirror_seats"]), 8, seat),
                            p=float(cfg["mirror_p"]), rng=mirror_rng,
                            learner_seat=seat, stats=mirror_stats,
                            applied_out=applied)
                n_inject["mirror"] += len(applied)
        if t != human_turn:
            human_turn = t
            if _HUMAN_POOL is not None and float(cfg["human_board_p"]) > 0.0:
                from hsbg.az.train.human_board_pool import HumanBoardStats, inject_turn
                human_stats = human_stats or HumanBoardStats()
                inject_turn(g, _HUMAN_POOL, t,
                            seats_count=int(cfg["human_board_seats"]),
                            p=float(cfg["human_board_p"]), rng=human_rng,
                            learner_seat=seat, stats=human_stats,
                            mirror_seats=tuple(applied), num_players=8,
                            set_tier=bool(int(cfg["human_board_set_tier"])),
                            fidelity=str(cfg["human_board_fidelity"]),
                            fast_inject=bool(int(cfg["human_board_fast_inject"])))
                n_inject["human"] += int(getattr(human_stats, "applied", 0))
        if gold > 0 and t != gold_turn:
            gold_turn = t
            try:              # ∞金币课程：每回合开始把金币拉满（同 ceiling probe --cheat gold）
                g.debug(json.dumps({"cmd": "set_player", "p": 0, "gold": gold}))
            except BaseException:  # noqa: BLE001
                pass

    while (not g.is_over()) and steps < max_steps:
        acted = False
        for p in range(8):
            if g.is_over():
                break
            maybe_inject()
            if not g.needs_action(p):
                continue
            acted = True
            steps += 1
            t_now = int(g.turn)
            if p == seat:
                dec = policy.decide(g, seat)
                a = int(dec.action)
                mask = mask_from_bytes(g.legal_mask(seat))
                if not (0 <= a < 245 and bool(mask[a])):
                    nz = np.flatnonzero(mask)
                    a = int(nz[0]) if nz.size else 0
                if a == 0 and ended_snap_turn != t_now:
                    # EndTurn 之前取快照 = 本回合「招募结束、战斗之前」的战团（与真实库口径一致）
                    rows.append(_snap(g, "recruit_end"))
                    ended_snap_turn = t_now
                g.step(seat, a)
            else:
                g.bot_play(int(p))
        if not acted and not g.is_over():
            break
    if not g.is_over():
        truncated = True
    final = _snap(g, "final")
    rows.append(final)
    try:
        placements = list(g.placements())
        placement = int(placements[seat])
    except BaseException:  # noqa: BLE001
        placement = 0
    # 存活回合：最后一个「招募末」快照的 turn（死亡则该回合即死亡回合）
    end_turns = [r["turn"] for r in rows if r["stage"] == "recruit_end"]
    death_turn = int(end_turns[-1]) if end_turns else None
    return {
        "seed": int(seed),
        "tag": str(cfg["tag"]),
        "gold": gold,
        "placement": placement,
        "truncated": bool(truncated),
        "steps": int(steps),
        "decisions": int(len(policy.records)),
        "death_turn": death_turn,
        "final_turn": int(final["turn"]),
        "alive_at_end": bool(final["alive"]),
        "injections": dict(n_inject),
        "human_inject_meta": (None if human_stats is None else {
            k: int(v) for k, v in human_stats.__dict__.items()
            if isinstance(v, (int, bool))}),
        "mirror_inject_meta": (None if mirror_stats is None else {
            k: int(v) for k, v in mirror_stats.__dict__.items()
            if isinstance(v, (int, bool))}),
        "elapsed": round(time.time() - t0, 3),
        "turns": rows,
    }


def _job(seed: int) -> dict:
    try:
        return _play_one(int(seed))
    except BaseException:  # noqa: BLE001
        return {"seed": int(seed), "error": traceback.format_exc()[-2000:],
                "tag": str(_CFG.get("tag")), "gold": int(_CFG.get("gold") or 0),
                "placement": 0, "turns": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", default="runs/scaling_signal/ckpt/s15_step301.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed-base", type=int, default=880000)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--tag", default="real")
    # ∞金币课程：>0 = 每回合开始把 learner 金币设为该值（0=真实经济）
    ap.add_argument("--gold", type=int, default=0)
    # 训练同口径的回合动作上限（ceiling probe 用 120 探索「资源更松」的更大档位）
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--move-guard", type=int, default=1, choices=[0, 1])
    ap.add_argument("--move-cap", type=int, default=3)
    ap.add_argument("--move-repeat-limit", type=int, default=2)
    # 对手当前战团快照（阈值平坦性 / 相对身材分析用；与策略观测无关）
    ap.add_argument("--record-opponents", type=int, default=1)
    # 训练分布复刻（s15 采集参数）
    ap.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-board-p", type=float, default=0.9)
    ap.add_argument("--human-board-seats", type=int, default=5)
    ap.add_argument("--human-board-sample", default="auto")
    ap.add_argument("--human-board-set-tier", type=int, default=1)
    ap.add_argument("--human-board-fidelity", default="full")
    ap.add_argument("--human-board-fast-inject", type=int, default=1)
    ap.add_argument("--mirror-snaps", default="runs/library/snaps_champ")
    ap.add_argument("--mirror-p", type=float, default=0.2)
    ap.add_argument("--mirror-seats", type=int, default=2)
    ap.add_argument("--mirror-sample", default="p75")
    ap.add_argument("--out-dir", default="runs/scaling_signal/rollouts")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    cfg = {
        "checkpoint": os.path.abspath(args.checkpoint),
        "device": str(args.device),
        "seed_base": int(args.seed_base),
        "tag": str(args.tag),
        "gold": int(args.gold),
        "max_actions_per_turn": int(args.max_actions_per_turn),
        "max_steps": int(args.max_steps),
        "move_guard": int(args.move_guard),
        "move_cap": int(args.move_cap),
        "move_repeat_limit": int(args.move_repeat_limit),
        "record_opponents": int(args.record_opponents),
        "human_boards": str(args.human_boards),
        "human_board_p": float(args.human_board_p),
        "human_board_seats": int(args.human_board_seats),
        "human_board_sample": str(args.human_board_sample),
        "human_board_set_tier": int(args.human_board_set_tier),
        "human_board_fidelity": str(args.human_board_fidelity),
        "human_board_fast_inject": int(args.human_board_fast_inject),
        "mirror_snaps": str(args.mirror_snaps),
        "mirror_p": float(args.mirror_p),
        "mirror_seats": int(args.mirror_seats),
        "mirror_sample": str(args.mirror_sample),
    }
    seeds = [int(args.seed_base) + i for i in range(int(args.games))]
    out_jsonl = os.path.join(args.out_dir, f"{args.tag}.jsonl")
    t0 = time.time()
    rows: list = []
    workers = max(1, int(args.workers))
    if workers == 1:
        _init_worker(cfg)
        for s in seeds:
            rows.append(_job(s))
            print(f"[{args.tag}] {len(rows)}/{len(seeds)} seed={s} "
                  f"place={rows[-1].get('placement')} "
                  f"{rows[-1].get('elapsed')}s", flush=True)
    else:
        with mp.Pool(workers, initializer=_init_worker, initargs=(cfg,)) as pool:
            for r in pool.imap_unordered(_job, seeds, chunksize=1):
                rows.append(r)
                if len(rows) % 10 == 0 or r.get("error"):
                    print(f"[{args.tag}] {len(rows)}/{len(seeds)} "
                          f"{round(time.time() - t0, 1)}s", flush=True)
    rows.sort(key=lambda r: r["seed"])
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    errs = [r for r in rows if r.get("error")]
    placed = [r for r in rows if int(r.get("placement") or 0) > 0]
    meta = {
        "tag": str(args.tag),
        "games": len(rows),
        "errors": len(errs),
        "placed_games": len(placed),
        "checkpoint": cfg["checkpoint"],
        "gold": int(args.gold),
        "max_actions_per_turn": int(args.max_actions_per_turn),
        "record_opponents": int(args.record_opponents),
        "workers": workers,
        "elapsed_s": round(time.time() - t0, 1),
        "mean_rank": (float(np.mean([r["placement"] for r in placed]))
                      if placed else None),
        "win": (float(np.mean([r["placement"] == 1 for r in placed]))
                if placed else None),
        "top4": (float(np.mean([r["placement"] <= 4 for r in placed]))
                 if placed else None),
        "mean_death_turn": (float(np.mean([r["death_turn"] for r in placed
                                           if r["death_turn"]])) if placed else None),
        "injection": {
            "human_p": float(args.human_board_p),
            "human_seats": int(args.human_board_seats),
            "human_library": str(args.human_boards),
            "human_fidelity": str(args.human_board_fidelity),
            "mirror_p": float(args.mirror_p),
            "mirror_seats": int(args.mirror_seats),
            "mirror_lib": str(args.mirror_snaps),
        },
        "config": cfg,
        "stderr_tail": [r["error"] for r in errs][:3],
    }
    with open(os.path.join(args.out_dir, f"{args.tag}.meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: meta[k] for k in ("tag", "games", "errors", "mean_rank",
                                           "win", "top4", "mean_death_turn",
                                           "elapsed_s")}, ensure_ascii=False))
    print(f"[out] {out_jsonl}")
    return 0 if not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
