#!/usr/bin/env python3
"""场面题**质量审计**：从记录的局面重放 3 回合，核对 ``obs`` 与 ``label`` 一致。

为什么需要这个脚本
------------------
``collect_problems`` 的 ``label.strength_before`` 是出题时刻的 learner 战团
``Σ(atk+hp)``，``label.strength_after_t3`` 是 **t+3 回合开始**（注入后）的同口径值。
两者都是从同一局 rollout 里读出来的，**必须能被重新算一遍**，否则题目池可能
静默错位（例如 obs 与 label 来自不同决策点）。

做法
----
``build_board_problems.py --audit-games`` 会把被审计局号的整局状态记下来：

* ``turn_states[t]``：第 t 回合**起始（注入之后）**的精确 ``state_json``；
* ``learner_actions``：learner 的**全部**动作 ``[turn, decision_idx, action]``。

本脚本对每道采样题：

1. 从 ``turn_states[problem.turn]`` 恢复局面，按**与出题循环完全相同的调度**
   （``for seat in range(8)`` + ``bot_play`` + 记录下来的 learner 动作）重放到
   ``problem.decision_idx``；此时
   - 重新编码观测 -> ``obs.sha256`` 必须与池子里**逐位相同**；
   - ``features`` 解出的 ``Σ(atk+hp)`` 必须等于 ``label.strength_before``；
2. 继续重放到 ``turn + horizon`` 回合起始（中途每个回合边界用记录的状态替换
   **对手注入**；替换前后 learner 的 ``player_json`` 必须相同，否则说明重放已漂移）；
3. 用重放得到的强度 ``strength_after_replay`` 与 ``label.strength_after_t3`` 比：
   ``Δ = log1p(after) - log1p(before)`` 的相对偏差必须 < ``--tol``（默认 10%）。

另外做一次**全池廉价检查**（不需要重放）：对 ``--pool`` 里每一道题解码 obs，
比较 ``features -> turn`` / ``features -> Σ(atk+hp)`` 与题目行 ``turn`` /
``label.strength_before``（这道检查覆盖整池，而重放只覆盖采样）。

用法::

    PYTHONPATH=rust/python:. python scripts/audit_board_problems.py \
      --audit runs/ab_late_big/problems_late_big.audit.jsonl \
      --pool data/board_problems/problems_late_big.jsonl \
      --samples 30 --out runs/ab_late_big/audit.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from hsbg.az.train.board_problems import (  # noqa: E402
    board_strength_from_features,
    decode_obs,
    encode_obs,
    turn_from_features,
)


def _strength_of_player_json(txt: str) -> int:
    pj = json.loads(txt)
    return int(sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                   for m in (pj.get("board") or [])))


def _rel(a: float, b: float) -> float:
    """相对偏差 |a-b| / max(|b|, eps)。"""
    return float(abs(a - b) / max(abs(b), 1e-9))


def load_audits(path: str):
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def audit_candidates(audits):
    """可重放的题：label 存活（survived=1）且目标回合状态被记录。"""
    out = []
    for a in audits:
        ts = a.get("turn_states") or {}
        for p in (a.get("problems") or []):
            lab = p.get("label") or {}
            target = int(lab.get("target_turn") or (int(p.get("turn") or 0)
                                                   + int(a.get("horizon") or 3)))
            if not int(lab.get("survived") or 0):
                continue
            if str(int(p.get("turn") or 0)) not in ts or str(target) not in ts:
                continue
            out.append((a, p, target))
    return out


def stratify(cands, samples: int, seed: int = 0):
    """按 turn 分层抽样（每层至少 1，尽量按层大小比例）。"""
    rng = random.Random(int(seed))
    by_turn = {}
    for c in cands:
        by_turn.setdefault(int(c[1].get("turn") or 0), []).append(c)
    turns = sorted(by_turn)
    if not turns:
        return []
    n = min(int(samples), len(cands))
    # 先每层 1 个（层数不超过 n），余量按层大小轮转补齐
    picked = []
    if n >= len(turns):
        for t in turns:
            picked.append(rng.choice(by_turn[t]))
        remain = n - len(picked)
        # 按层大小比例分剩余（largest remainder）
        sizes = {t: len(by_turn[t]) for t in turns}
        total = sum(sizes.values())
        quota = {t: sizes[t] * remain / total for t in turns}
        extra = {t: int(math.floor(quota[t])) for t in turns}
        left = remain - sum(extra.values())
        for t in sorted(turns, key=lambda x: -(quota[x] - extra[x]))[:left]:
            extra[t] += 1
        for t in turns:
            pool = [c for c in by_turn[t] if c not in picked]
            rng.shuffle(pool)
            picked.extend(pool[:extra[t]])
    else:
        rng.shuffle(cands)
        picked = cands[:n]
    picked = picked[:n]
    # 去重（同一题只审一次）
    seen, uniq = set(), []
    for a, p, target in picked:
        key = (a.get("game_seed"), p.get("problem_id"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((a, p, target))
    return uniq


def replay_problem(audit, prob, target: int, *, tol: float = 0.10,
                   max_steps: int = 20000, verbose: bool = False):
    """从记录的回合起始状态重放到题目决策点 + 3 回合，返回核对结果。"""
    import hsbg_engine as E  # 惰性：纯函数路径不需要引擎

    from hsbg.az.train.common import mask_from_bytes, obs_arrays

    seat = int(audit.get("seat") or 0)
    T = int(prob.get("turn") or 0)
    prob_dec = int(prob.get("decision_idx") or 0)
    ts = audit.get("turn_states") or {}
    label = prob.get("label") or {}
    out = {"problem_id": str(prob.get("problem_id")), "game_seed": audit.get("game_seed"),
           "turn": T, "decision_idx": prob_dec, "target_turn": int(target),
           "ok": False, "reason": "", "boundary_match": [],
           "obs_sha_match": None, "obs_dtype": str(prob.get("obs_dtype") or ""),
           "strength_before_label": int(label.get("strength_before") or 0),
           "strength_before_obs": None, "strength_before_replay": None,
           "strength_after_label": int(label.get("strength_after_t3") or 0),
           "strength_after_replay": None,
           "delta_label": float(label.get("strength_delta", label.get("delta_log1p") or 0.0)),
           "delta_replay": None, "delta_rel_dev": None,
           "after_rel_dev": None}
    if str(T) not in ts:
        out["reason"] = "no_turn_state"
        return out
    acts = {}
    for t, d, a in (audit.get("learner_actions") or []):
        acts[(int(t), int(d))] = int(a)
    turn_pos = audit.get("turn_pos") or {}
    state = {"cur_turn": T, "dec_idx": 0, "done": False, "captured": False,
             "pos": int(turn_pos.get(str(T), 0) or 0)}
    g = E.Game.from_json(ts[str(T)])
    boundary = out["boundary_match"]

    def _boundary(t_new: int, p_pos: int) -> bool:
        """回合边界：返回 True 表示已到目标回合（重放结束）。

        ``p_pos`` = 出题循环里「新回合开始那一刻正在处理的座位」：从它继续这一
        pass（不能一律从 0 开始，否则会漏掉同 pass 里已处理过的座位）。
        """
        nonlocal g
        state["cur_turn"] = int(t_new)
        state["dec_idx"] = 0
        state["pos"] = int(p_pos)
        if int(t_new) >= int(target):
            out["strength_after_replay"] = _strength_of_player_json(
                g.player_json(seat))
            post = g.player_json(seat)
            if str(int(t_new)) in ts:
                g2 = E.Game.from_json(ts[str(int(t_new))])
                boundary.append([int(t_new), post == g2.player_json(seat)])
            state["done"] = True
            return True
        pre = g.player_json(seat)
        if str(int(t_new)) in ts:
            # 只替换注入结果（对手战团）；learner 若被改动说明重放漂移。
            repl = E.Game.from_json(ts[str(int(t_new))])
            boundary.append([int(t_new), pre == repl.player_json(seat)])
            g = repl
            state["pos"] = int(turn_pos.get(str(int(t_new)), 0) or 0)
        else:
            boundary.append([int(t_new), None])
        return False

    steps = 0
    while (not g.is_over()) and steps < int(max_steps) and not state["done"]:
        t = int(g.turn)
        if t != state["cur_turn"] and _boundary(t, state["pos"]):
            break
        acted = False
        for p in range(int(state["pos"]), 8):
            if g.is_over() or steps >= int(max_steps) or state["done"]:
                break
            if not g.needs_action(p):
                continue
            steps += 1
            acted = True
            t2 = int(g.turn)
            if t2 != state["cur_turn"] and _boundary(t2, p):
                break
            if p != seat:
                g.bot_play(p)
                continue
            if (int(state["cur_turn"]) == T
                    and int(state["dec_idx"]) == prob_dec
                    and not state["captured"]):
                f, c = obs_arrays(g.observe(seat))
                mask = mask_from_bytes(g.legal_mask(seat))
                dtype = out["obs_dtype"] or "f32"
                enc = encode_obs(f, c, mask, dtype=dtype)
                out["obs_sha_match"] = bool(
                    str(enc.get("sha256")) == str(prob.get("obs_sha256")))
                out["strength_before_obs"] = int(board_strength_from_features(f))
                out["turn_obs"] = int(turn_from_features(f))
                out["strength_before_replay"] = _strength_of_player_json(
                    g.player_json(seat))
                state["captured"] = True
                if verbose:
                    print(f"[audit] capture {out['problem_id']} turn={T} "
                          f"dec={prob_dec} obs_sha_match={out['obs_sha_match']} "
                          f"strength={out['strength_before_replay']} "
                          f"obs_strength={out['strength_before_obs']}", flush=True)
            key = (int(state["cur_turn"]), int(state["dec_idx"]))
            if key not in acts:
                out["reason"] = f"missing_action:{key}"
                return out
            g.step(seat, acts[key])
            state["dec_idx"] += 1
        if state["done"]:
            break
        state["pos"] = 0
        if not acted:
            out["reason"] = "stalled"
            break
    if not state["captured"]:
        out["reason"] = out["reason"] or "not_reached_decision"
        return out
    if out["strength_after_replay"] is None:
        # learner 在目标回合前出局 / 游戏结束：标签本应 survived=0
        out["reason"] = out["reason"] or "terminal_before_target"
        return out
    sb = float(out["strength_before_replay"])
    sa = float(out["strength_after_replay"])
    d_rep = float(math.log1p(max(sa, 0.0)) - math.log1p(max(sb, 0.0)))
    out["delta_replay"] = d_rep
    out["delta_rel_dev"] = _rel(d_rep, out["delta_label"])
    out["after_rel_dev"] = _rel(sa, float(out["strength_after_label"]))
    out["ok"] = bool(out["obs_sha_match"]
                     and out["strength_before_obs"] is not None
                     and int(out["strength_before_obs"])
                     == int(out["strength_before_label"])
                     and abs(d_rep - out["delta_label"]) <= float(tol)
                     * max(abs(out["delta_label"]), 1e-9))
    return out


def pool_obs_check(pool_path: str, limit: int = 0):
    """全池廉价检查：obs 解码出的 turn / 战团强度 vs 题目行 / label。"""
    n = turn_bad = strength_bad = cards_bad = 0
    devs = []
    with open(pool_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if limit and n >= int(limit):
                break
            row = json.loads(line)
            n += 1
            obs = row.get("obs") or {}
            try:
                f, c, _mask = decode_obs(obs)
            except Exception:  # noqa: BLE001 - 坏行计入
                strength_bad += 1
                continue
            t_obs = int(turn_from_features(f))
            if t_obs != int(row.get("turn") or 0):
                turn_bad += 1
            s_obs = int(board_strength_from_features(f))
            s_lab = int((row.get("label") or {}).get("strength_before") or 0)
            if s_obs != s_lab:
                strength_bad += 1
                devs.append(_rel(float(s_obs), float(s_lab)))
            # obs.cards 与 features 的槽位一致性：cards 长度固定 124，这里只查长度
            if len(np.asarray(c).reshape(-1)) not in (0, 124):
                cards_bad += 1
    return {"pool": str(pool_path), "problems": int(n),
            "turn_mismatch": int(turn_bad),
            "strength_mismatch": int(strength_bad),
            "cards_len_mismatch": int(cards_bad),
            "strength_rel_dev_p50": float(np.percentile(devs, 50)) if devs else 0.0,
            "strength_rel_dev_max": float(max(devs)) if devs else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description="场面题质量审计（重放 3 回合核对 obs/label）")
    ap.add_argument("--audit", required=True, help="--audit-games 产出的 .audit.jsonl")
    ap.add_argument("--pool", default="", help="题目池（全池 obs 一致性检查；空 = 跳过）")
    ap.add_argument("--samples", type=int, default=30, help="重放审计题数（默认 30）")
    ap.add_argument("--seed", type=int, default=0, help="分层抽样的随机种子")
    ap.add_argument("--tol", type=float, default=0.10,
                    help="Δ 相对偏差容忍（默认 0.10 = 10%%）")
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--turns", default="",
                    help="只审这些 turn（逗号分隔；默认空 = 全部）。用于补审"
                         "t14/t15 这类存活标签稀少的后期题")
    ap.add_argument("--out", default="")
    ap.add_argument("--verbose", type=int, default=1)
    args = ap.parse_args()

    audits = load_audits(args.audit)
    cands = audit_candidates(audits)
    want = {int(t) for t in str(args.turns or "").split(",") if t.strip()}
    if want:
        cands = [c for c in cands if int(c[1].get("turn") or 0) in want]
        print(f"[audit] --turns {sorted(want)} -> candidates={len(cands)}", flush=True)
    picked = stratify(cands, int(args.samples), seed=int(args.seed))
    print(f"[audit] games={len(audits)} candidates={len(cands)} "
          f"sampled={len(picked)} tol={args.tol:g}", flush=True)
    rows = []
    for a, p, target in picked:
        r = replay_problem(a, p, target, tol=float(args.tol),
                          max_steps=int(args.max_steps),
                          verbose=bool(int(args.verbose)))
        rows.append(r)
        flag = "OK " if r["ok"] else "BAD"
        print(f"[{flag}] {r['problem_id']} seed={r['game_seed']} t{r['turn']} "
              f"dec={r['decision_idx']} obs_sha={r['obs_sha_match']} "
              f"sb={r['strength_before_replay']}/{r['strength_before_label']} "
              f"sa={r['strength_after_replay']}/{r['strength_after_label']} "
              f"dRep={r['delta_replay']} dLab={r['delta_label']} "
              f"dev={r['delta_rel_dev']} {r['reason']}", flush=True)

    ok = [r for r in rows if r["ok"]]
    devs = [float(r["delta_rel_dev"]) for r in rows if r["delta_rel_dev"] is not None]
    sb_bad = [r for r in rows if r["strength_before_obs"] is not None
              and int(r["strength_before_obs"]) != int(r["strength_before_label"])]
    bmatches = [m for r in rows for m in (r["boundary_match"] or [])]
    summary = {
        "audit": str(args.audit), "pool": str(args.pool),
        "samples": len(rows), "ok": len(ok),
        "pass_rate": (len(ok) / len(rows)) if rows else 0.0,
        "tol": float(args.tol),
        "obs_sha_match_all": all(bool(r["obs_sha_match"]) for r in rows if r["obs_sha_match"] is not None),
        "strength_before_mismatch": len(sb_bad),
        "delta_rel_dev_p50": float(np.percentile(devs, 50)) if devs else None,
        "delta_rel_dev_p90": float(np.percentile(devs, 90)) if devs else None,
        "delta_rel_dev_max": float(max(devs)) if devs else None,
        "boundary_checks": len(bmatches),
        "boundary_mismatch": int(sum(1 for _t, m in bmatches if m is False)),
        "by_turn": {str(t): int(sum(1 for r in rows if int(r["turn"]) == t))
                    for t in sorted({int(r["turn"]) for r in rows})},
        "failures": [r for r in rows if not r["ok"]],
        "rows": rows,
    }
    if args.pool:
        summary["pool_obs_check"] = pool_obs_check(str(args.pool))
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("rows", "failures")},
                     ensure_ascii=False, indent=2), flush=True)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"[audit] wrote {args.out}", flush=True)
    return 0 if len(ok) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
