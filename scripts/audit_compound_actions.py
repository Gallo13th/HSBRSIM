#!/usr/bin/env python3
"""动作效率审计：把教师一局的动作预算拆到 buy / sell / roll / cast / upgrade / hero / …

背景
----
``docs/COMPOUND_TEACHER.md`` 的两个反直觉结论（金币不是瓶颈、金色不是瓶颈）把闸门指向
**动作额度 + 手牌 10 张 / 7 个站位**。本脚本量化一局 ~600 动作（40×15）的**去向**与
**每个动作的边际价值**，用来判断「动作效率」还有多少空间。

记录口径（逐决策）
------------------
- ``gold_delta`` = 动作后金币 − 动作前金币（负 = 花费，正 = 卖出/收入）；
- ``delta_now`` = 动作后战团 Σ − 动作前战团 Σ（即时身材增量；买牌进手牌时 = 0，
  上场/施法才 >0，卖牌 <0）；
- ``fwd3`` = min(t+3,15) 回合**回合末** Σ − 动作前 Σ（「后续 3 回合增量」近似；
  按动作归因是启发式，不是因果）；
- 动作按 :func:`gen_compound_bc.classify_action` 分类；``pending``（饰品/发现/目标）
  与 ``end_turn`` 不算动作额度，单独统计；每回合第 N 个**自主**动作用于边际价值曲线。

浪费口径
--------
``rolls/turn`` 直方图与「打满上限的回合占比」、refresh 后同回合没有买入的「空刷新」、
sell 次数/立即 Σ 损失、每回合末剩余金币、freeze/move/hero power 等杂项动作计数。

用法::

    python scripts/audit_compound_actions.py --config s3_growth_buff3 \
        --games 40 --workers 12 --out data/scaling/compound_bc/action_audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    A_REFRESH, END_TURN, VectorEconomySandbox)
from compound_script import (  # noqa: E402
    A_BUY, A_CHOOSE, A_DARK_GIFT, A_FREEZE, A_HERO_POWER, A_MOVE, A_PLAY, A_SELL,
    A_UPGRADE, N_CHOICE, N_POS, N_SHOP, CompoundPolicy, group_configs)
from gen_compound_bc import ACTION_KINDS, GROUP_SPEC, classify_action  # noqa: E402

#: 原始动作桶（``other`` 的细分，确认 move/freeze 是否被用到）
RAW_BUCKETS = {
    "freeze": A_FREEZE, "upgrade": A_UPGRADE, "hero_power": A_HERO_POWER,
    "dark_gift": A_DARK_GIFT,
}
ORDINAL_CAP = 21          # 第 21 个及以后合并展示
MAX_TURN = 15


def _sum_stats(board: Sequence[dict]) -> int:
    return sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in board)


def _run_shard(payload: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.time()
    cfg = payload["cfg"]
    games = int(payload["games"])
    n_envs = max(1, min(int(payload["n_envs"]), games))
    vec = VectorEconomySandbox(cfg, n_envs=n_envs, seed0=int(payload["seed0"]))
    obs = vec.reset()
    pols = [CompoundPolicy(seed=int(payload["seed0"]) + i,
                           max_refresh=int(payload["max_refresh"]),
                           spell_hold=int(payload["spell_hold"]),
                           triple_first=bool(payload.get("triple_first")),
                           efficient=bool(payload.get("efficient")))
            for i in range(n_envs)]
    cur: List[List[tuple]] = [[] for _ in range(n_envs)]
    done_games = 0
    steps = 0

    def _empty_acc() -> Dict[str, Any]:
        return {
            "by_kind": Counter(), "kind_spent": Counter(), "kind_gained": Counter(),
            "kind_delta": Counter(), "kind_fwd3": Counter(), "kind_fwd3n": Counter(),
            "kind_ratio": Counter(), "kind_turn": Counter(),
            "raw": Counter(), "ordinal": Counter(), "ordinal_delta": Counter(),
            "ordinal_fwd3": Counter(), "ordinal_spent": Counter(),
            "rolls_hist": Counter(), "turns": 0,
        }

    acc = _empty_acc()
    episodes: List[Dict[str, Any]] = []
    while done_games < games and steps < max(4000, 60 * games):
        acts: List[int] = []
        for i, env in enumerate(vec.envs):
            v = json.loads(env.g.view(0))
            me = v.get("me") or {}
            a = int(pols[i].act(v, obs[i].mask))
            kind_i, _is_amp, _is_car, _is_spell, _cid = classify_action(a, v)
            gb = int(me.get("gold") or 0)
            sb = _sum_stats(me.get("board") or [])
            acts.append(a)
            cur[i].append((a, kind_i, int(v.get("turn") or 0), gb, sb))
        obs, _r, dones, infos = vec.step(acts)
        steps += 1
        for i, d in enumerate(dones):
            if not d:
                continue
            ep = infos[i].get("episode") or vec.envs[i].episode_summary()
            rows = {int(r["turn"]): r for r in (ep.get("rows") or [])}
            sig_end = {t: int(r.get("sigma") or 0) for t, r in rows.items()}
            last_t = max(sig_end) if sig_end else MAX_TURN
            seq = cur[i]
            ord_n = 0
            prev_t = -1
            turn_kinds: List[str] = []
            for j, (a, kind_i, t, gb, sb) in enumerate(seq):
                nxt = seq[j + 1] if j + 1 < len(seq) else None
                ga = nxt[3] if nxt is not None else gb
                sa = nxt[4] if nxt is not None else sb
                if nxt is not None and nxt[2] != t:
                    ga, sa = gb, sb      # 跨回合：本动作后的状态不可见，用回退
                if t != prev_t:
                    prev_t = t
                    ord_n = 0
                    if turn_kinds:
                        _flush_turn(acc, turn_kinds, int(payload["max_refresh"]))
                    turn_kinds = []
                kind = ACTION_KINDS[kind_i]
                spent = max(0, gb - ga)
                gained = max(0, ga - gb)
                delta = sa - sb
                s_t = int(sig_end.get(t, sb))
                s_t3 = int(sig_end.get(min(t + 3, last_t), s_t))
                fwd = s_t3 - s_t                       # 未来 3 回合的 Σ 增量
                ratio = (s_t3 + 1.0) / max(1.0, float(s_t) + 1.0)
                is_autonomous = kind not in ("pending", "end_turn")
                if kind == "refresh":
                    turn_kinds.append("refresh")
                elif kind.startswith("buy_"):
                    turn_kinds.append("buy")
                else:
                    turn_kinds.append("other")
                acc["by_kind"][kind] += 1
                acc["kind_spent"][kind] += spent
                acc["kind_gained"][kind] += gained
                acc["kind_delta"][kind] += delta
                acc["kind_fwd3"][kind] += fwd
                acc["kind_fwd3n"][kind] += 1
                acc["kind_ratio"][kind] += ratio
                acc["kind_turn"][kind] += t
                if kind == "other":
                    acc["raw"][_raw_bucket(a)] += 1
                if is_autonomous:
                    ord_n += 1
                    key = min(ord_n, ORDINAL_CAP)
                    acc["ordinal"][key] += 1
                    acc["ordinal_delta"][key] += delta
                    acc["ordinal_fwd3"][key] += fwd
                    acc["ordinal_spent"][key] += spent
            if turn_kinds:
                _flush_turn(acc, turn_kinds, int(payload["max_refresh"]))
            # 局级读数
            gold_end = [int(x) for x in (ep.get("gold_hist") or [])]
            episodes.append({
                "seed": int(ep.get("seed") or 0),
                "sigma_t12": int(ep.get("sigma_t12") or 0),
                "sigma_t15": int(ep.get("sigma_t15") or 0),
                "goldens": int(ep.get("goldens_t15") or 0),
                "spells": int(ep.get("spells_t15") or 0),
                "carriers": int(ep.get("carriers_t15") or 0),
                "gold_end_total": int(ep.get("gold_end_total") or 0),
                "decisions": len(seq),
                "autonomous": sum(1 for (_a, k, _t, _gb, _sb) in seq
                                  if ACTION_KINDS[k] not in ("pending", "end_turn")),
                "rolls": sum(1 for (_a, k, _t, _gb, _sb) in seq if ACTION_KINDS[k] == "refresh"),
                "sells": sum(1 for (_a, k, _t, _gb, _sb) in seq if ACTION_KINDS[k] == "sell"),
                "gold_turns_ge5": sum(1 for g in gold_end if g >= 5),
                "turns": len(gold_end),
            })
            done_games += 1
            cur[i] = []
            pols[i].turn = -1
        if time.time() - t0 > float(payload["max_seconds"]):
            break
    return {"acc": _merge_acc(acc), "episodes": episodes,
            "seconds": time.time() - t0, "steps": steps}


def _kind_from_raw(a: int) -> int:
    """只在动作编码上分类（不需要 shop/hand）：审计用不到「买的是不是放大器」。"""
    if A_BUY <= a < A_BUY + N_SHOP:
        return 4          # buy_minion 兜底桶（细分类在别处做）
    if A_PLAY <= a < A_PLAY + 10 * N_POS:
        return 6          # play_minion 兜底桶
    if A_SELL <= a < A_SELL + 7:
        return 7
    if a == A_UPGRADE:
        return 8
    if a == A_REFRESH:
        return 9
    if a == END_TURN:
        return 10
    if A_CHOOSE <= a < A_CHOOSE + N_CHOICE:
        return 11
    return 0


def _raw_bucket(a: int) -> str:
    if a in (A_HERO_POWER, A_HERO_POWER + 1):
        return "hero_power"
    if a == A_FREEZE:
        return "freeze"
    if a == A_DARK_GIFT:
        return "dark_gift"
    if A_MOVE <= a < A_MOVE + 8:
        return "move"
    return "other"


def _flush_turn(acc: Dict[str, Any], kinds: List[str], roll_cap: int) -> None:
    """记录一个回合的 roll 次数与「空刷新」（refresh 后同回合没有买入）。"""
    rolls = sum(1 for k in kinds if k == "refresh")
    acc["rolls_hist"][rolls] += 1
    acc["turns"] += 1
    buys = [i for i, k in enumerate(kinds) if k == "buy"]
    for i, k in enumerate(kinds):
        if k != "refresh":
            continue
        if not any(b > i for b in buys):     # 该刷新之后同回合没有再买
            acc["raw"]["refresh_no_followup_buy"] += 1
    if rolls >= roll_cap:
        acc["raw"]["turns_at_roll_cap"] += 1


def _merge_acc(a: Dict[str, Any]) -> Dict[str, Any]:
    return a      # 单 worker 内已是 Counter 累加；主进程再合并


def _merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    for key, val in b.items():
        if isinstance(val, Counter):
            a.setdefault(key, Counter()).update(val)
        elif isinstance(val, list):
            a.setdefault(key, []).extend(val)
        else:
            a[key] = a.get(key, 0) + val
    return a


def report(games: Sequence[Dict[str, Any]], acc: Dict[str, Any], cfg,
           max_refresh: int, seconds: float) -> Dict[str, Any]:
    n = len(games)
    tot_dec = sum(int(g["decisions"]) for g in games)
    tot_auto = sum(int(g["autonomous"]) for g in games)
    tot_pend = tot_dec - tot_auto

    def _pct(vals, q):
        return float(np.percentile(np.asarray(vals, dtype=np.float64), q)) if len(vals) else 0.0

    by_kind = {}
    for k, cnt in sorted(acc["by_kind"].items(), key=lambda kv: -kv[1]):
        by_kind[k] = {
            "count": int(cnt), "per_game": cnt / n if n else 0.0,
            "share": cnt / max(1, tot_dec),
            "gold_spent": int(acc["kind_spent"].get(k, 0)),
            "gold_gained": int(acc["kind_gained"].get(k, 0)),
            "gold_spent_mean": acc["kind_spent"].get(k, 0) / max(1, cnt),
            "delta_now_sum": int(acc["kind_delta"].get(k, 0)),
            "delta_now_mean": (acc["kind_delta"].get(k, 0)
                               / max(1, acc["kind_fwd3n"].get(k, 0))),
            "fwd3_mean": (acc["kind_fwd3"].get(k, 0)
                          / max(1, acc["kind_fwd3n"].get(k, 0))),
            "fwd3_ratio_mean": (acc["kind_ratio"].get(k, 0)
                                / max(1, acc["kind_fwd3n"].get(k, 0))),
            "turn_mean": (acc["kind_turn"].get(k, 0)
                          / max(1, acc["kind_fwd3n"].get(k, 0))),
        }
    ordinal = {}
    for key in sorted(acc["ordinal"]):
        c = acc["ordinal"][key]
        ordinal[str(key)] = {
            "count": int(c), "delta_now_mean": acc["ordinal_delta"].get(key, 0) / max(1, c),
            "fwd3_mean": acc["ordinal_fwd3"].get(key, 0) / max(1, c),
            "gold_spent_mean": acc["ordinal_spent"].get(key, 0) / max(1, c),
        }
    turns = int(acc["turns"])
    rolls_hist = {int(k): int(v) for k, v in sorted(acc["rolls_hist"].items())}
    raw = {k: int(v) for k, v in acc["raw"].items()}
    return {
        "games": n,
        "decisions": int(tot_dec),
        "autonomous": int(tot_auto),
        "pending": int(tot_pend),
        "pending_share": tot_pend / max(1, tot_dec),
        "actions_per_game": tot_auto / n if n else 0.0,
        "cap_per_game": 40 * 15,
        "cap_usage": (tot_auto / n) / (40 * 15) if n else 0.0,
        "by_kind": by_kind,
        "ordinal": ordinal,
        "waste": {
            "turns": turns,
            "rolls_mean": float(np.mean([float(g["rolls"]) for g in games])) if n else 0.0,
            "rolls_per_game": sum(int(g["rolls"]) for g in games) / n if n else 0.0,
            "sells_per_game": sum(int(g["sells"]) for g in games) / n if n else 0.0,
            "end_turn_gold_p50": _pct([float(g["gold_end_total"]) / max(1, g["turns"])
                                       for g in games], 50),
            "turns_gold_ge5_share": (sum(int(g["gold_turns_ge5"]) for g in games)
                                     / max(1, sum(int(g["turns"]) for g in games))),
            "rolls_hist": rolls_hist,
            "turns_at_roll_cap": raw.get("turns_at_roll_cap", 0),
            "turns_at_roll_cap_share": raw.get("turns_at_roll_cap", 0) / max(1, turns),
            "refresh_no_followup_buy": raw.get("refresh_no_followup_buy", 0),
            "refresh_no_followup_buy_share": (raw.get("refresh_no_followup_buy", 0)
                                              / max(1, acc["by_kind"].get("refresh", 0))),
            "raw_other": raw,
        },
        "sigma_t15_p50": _pct([float(g["sigma_t15"]) for g in games], 50),
        "sigma_t15_mean": float(np.mean([float(g["sigma_t15"]) for g in games])) if n else 0.0,
        "r12_15_p50": _pct([float(g["sigma_t15"]) / max(1, g["sigma_t12"]) for g in games], 50),
        "spells_mean": float(np.mean([float(g["spells"]) for g in games])) if n else 0.0,
        "goldens_mean": float(np.mean([float(g["goldens"]) for g in games])) if n else 0.0,
        "sigma_per_autonomous_action": float(np.mean([
            float(g["sigma_t15"]) / max(1, g["autonomous"]) for g in games])) if n else 0.0,
        "config": cfg.engine_config() if cfg is not None else {},
        "max_refresh": int(max_refresh),
        "seconds": float(seconds),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CompoundPolicy 动作效率审计")
    ap.add_argument("--config", default="s3_growth_buff3", choices=sorted(GROUP_SPEC))
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--config-index", type=int, default=0,
                    help="seed 偏移（与 gen_compound_bc 的 config 序号一致，便于同种子对比）")
    ap.add_argument("--max-refresh", type=int, default=4)
    ap.add_argument("--spell-hold", type=int, default=1)
    ap.add_argument("--triple-first", type=int, default=0)
    ap.add_argument("--efficient", type=int, default=0)
    ap.add_argument("--gold-cap", type=int, default=99)
    ap.add_argument("--max-seconds", type=float, default=600.0)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "scaling", "compound_bc",
                                                  "action_audit.json"))
    args = ap.parse_args(argv)

    from dataclasses import replace
    spec = GROUP_SPEC[args.config]
    cfg = group_configs(gold_cap=int(args.gold_cap))[spec["group"]]
    if int(args.gold_cap) != 99:
        cfg = replace(cfg, gold_cap=int(args.gold_cap))
    games = int(args.games)
    n_w = max(1, min(int(args.workers), games))
    chunks = [(games + i) // n_w for i in range(n_w)]
    chunks = [c for c in chunks if c > 0]
    payloads = [{
        "cfg": cfg, "games": c, "n_envs": c,
        "seed0": int(args.seed0) + 100000 * int(args.config_index) + 1000 * si,
        "max_refresh": int(args.max_refresh), "spell_hold": int(args.spell_hold),
        "triple_first": int(args.triple_first), "efficient": int(args.efficient),
        "max_seconds": float(args.max_seconds),
    } for si, c in enumerate(chunks)]
    t0 = time.time()
    import multiprocessing as mp
    with mp.get_context("fork").Pool(len(payloads)) as pool:
        outs = pool.map(_run_shard, payloads)
    acc: Dict[str, Any] = {}
    games_all: List[Dict[str, Any]] = []
    for o in outs:
        acc = _merge(acc, o["acc"])
        games_all.extend(o["episodes"])
    rep = report(games_all, acc, cfg, int(args.max_refresh), time.time() - t0)
    rep["efficient"] = int(args.efficient)
    rep["triple_first"] = int(args.triple_first)
    rep["gold_cap"] = int(args.gold_cap)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=float)

    print(f"games={rep['games']} decisions={rep['decisions']} "
          f"autonomous/game={rep['actions_per_game']:.1f} "
          f"(cap 600 → {rep['cap_usage']:.0%}) pending_share={rep['pending_share']:.1%}")
    print(f"t15 Σ p50={rep['sigma_t15_p50']:.0f} mean={rep['sigma_t15_mean']:.0f} "
          f"r12 p50={rep['r12_15_p50']:.2f} spells={rep['spells_mean']:.0f} "
          f"Σ/action={rep['sigma_per_autonomous_action']:.2f} "
          f"({rep['seconds']:.0f}s)")
    print("\n动作去向（花费=金币；ΔΣ=即时 Σ；fwd3=未来 3 回合 Σ 增量；ratio=fwd3 增长倍数）：")
    for k, r in rep["by_kind"].items():
        print(f"  {k:14s} {r['count']:6d} ({r['per_game']:5.1f}/局 {r['share']:5.1%} "
              f"t≈{r['turn_mean']:4.1f}) "
              f"花{r['gold_spent']:7d} 得{r['gold_gained']:5d} "
              f"ΔΣ={r['delta_now_mean']:7.2f} fwd3={r['fwd3_mean']:6.1f} "
              f"×{r['fwd3_ratio_mean']:4.2f}")
    w = rep["waste"]
    print(f"\n浪费：rolls/局={w['rolls_per_game']:.1f}（hist {w['rolls_hist']}）"
          f" 打满上限回合={w['turns_at_roll_cap_share']:.1%}"
          f" 空刷新={w['refresh_no_followup_buy']}（{w['refresh_no_followup_buy_share']:.1%}）")
    print(f"      sells/局={w['sells_per_game']:.1f} 回合末余金p50={w['end_turn_gold_p50']:.1f}"
          f" 余金≥5的回合={w['turns_gold_ge5_share']:.1%} raw={w['raw_other']}")
    print("\n第 N 个自主动作的边际价值：")
    print("  N   count   ΔΣ均值   fwd3均值   花费均值")
    for k, r in rep["ordinal"].items():
        print(f"  {k:>2s} {r['count']:7d} {r['delta_now_mean']:8.2f} "
              f"{r['fwd3_mean']:9.1f} {r['gold_spent_mean']:8.2f}")
    print(f"\n写出 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
