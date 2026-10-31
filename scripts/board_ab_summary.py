#!/usr/bin/env python3
"""汇总方向 A 的 A/B/C/D 四臂：human 配对 Δ/CI + 质量面板强度/tier + collect 增幅。

只读 ``human_panel_eval.py`` / ``quality_monitor.py`` / ``train_entity_sync.py`` 的产物，
输出 JSON 与 markdown 表（直接贴进 ``docs/BOARD_PROBLEMS.md``）。

配对口径：所有臂用**同一** ``--seed-base``，``human_panel_eval`` 的每局 seed 只由
``(seed_base, seat, 局号)`` 决定，因此逐局 ``D = rank_arm - rank_base`` 是严格配对的
（同 seed/seat/对手注入序列）。CI 用对局级 bootstrap（5000 次，百分位法）。

用法::

    python scripts/board_ab_summary.py \
      --human A=runs/eval/ab_board/human_A.json \
      --human B=runs/eval/ab_board/human_B.json \
      --quality A=runs/quality/ab_board/quality_A.json \
      --quality B=runs/quality/ab_board/quality_B.json \
      --history A=runs/ab_board/armA --history B=runs/ab_board/armB \
      --base A --out runs/ab_board/SUMMARY.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _pair(spec: str) -> tuple:
    if "=" not in spec:
        raise SystemExit(f"--human/--quality/--history 需要 name=path，得到 {spec!r}")
    name, path = spec.split("=", 1)
    return name.strip(), path.strip()


def human_per_game(panel: dict) -> np.ndarray:
    """从 human_panel_eval 的 JSON 取**逐局名次**（按 seat 顺序展开）。"""
    p0 = (panel.get("panels") or [{}])[0]
    per_seat = ((p0.get("details") or {}).get("per_seat") or {})
    ranks = []
    for seat in sorted(per_seat, key=lambda s: int(s.split("_")[-1])):
        seq = ((per_seat[seat].get("model") or {}).get("rank_sequence") or [])
        ranks.extend(int(r) for r in seq)
    return np.asarray(ranks, dtype=np.int64)


def boot_ci(d: np.ndarray, n: int = 5000, seed: int = 420000) -> tuple:
    if d.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = np.empty(int(n), dtype=np.float64)
    for i in range(int(n)):
        means[i] = d[rng.integers(0, d.size, size=d.size)].mean()
    return (float(np.percentile(means, 2.5)),
            float(np.percentile(means, 97.5)))


def human_arm(panel: dict) -> dict:
    ranks = human_per_game(panel)
    p0 = (panel.get("panels") or [{}])[0]
    n = int(ranks.size)
    return {
        "checkpoint": panel.get("checkpoint"),
        "games": n,
        "mean_rank": float(ranks.mean()) if n else None,
        "top4": float(np.mean(ranks <= 4)) if n else None,
        "win": float(np.mean(ranks == 1)) if n else None,
        "illegal": int(p0.get("illegal", 0) or 0),
        "truncated": int(p0.get("truncated", 0) or 0),
        "truncated_combats": int(p0.get("truncated_combats", 0) or 0),
        "injection": p0.get("injection"),
        "seconds": p0.get("seconds"),
        "_ranks": ranks,
    }


def quality_arm(q: dict) -> dict:
    keys = ("mean_rank", "top4", "win", "death_turn_p50", "death_strength_p50",
            "tier_p50_t9", "tier_p50_t12", "tier_p50_t15",
            "tier_ge5_t9", "tier_ge5_t12", "tier_ge5_t15",
            "strength_ratio_t9", "strength_ratio_t12", "strength_ratio_t15",
            "moves_per_turn_mean", "moves_per_turn_p90", "moves_per_turn_max",
            "net_board_unchanged_ratio", "move_original_before_guard"
            if "move_original_before_guard" in q else "moves_per_move_turn_mean",
            "games", "move_guard")
    return {k: q.get(k) for k in keys}


def collect_stats(run_dir: str, *, min_iters: int = 20) -> dict:
    """从 ``history.jsonl`` 取 p50 ``collect_s`` 与 ``decisions_per_s``（连续 iter）。"""
    path = os.path.join(run_dir, "history.jsonl")
    if not os.path.isfile(path):
        return {}
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except (ValueError, TypeError):
                continue
            if "iter" not in r:
                continue
            rows.append(r)
    cols = []
    for r in rows:
        prof = r.get("profile") or {}
        if prof.get("collect_s"):
            cols.append(float(prof["collect_s"]))
    # 每 iter 的吞吐：本 iter 的 decisions / 本 iter 的 wall（seconds 是累计值）
    #   collect_dec_s = decisions / collect_s（只算采集阶段，门禁口径）
    #   wall_dec_s    = decisions / (本 iter wall，含 PPO/保存)
    dps, cdec, wdec = [], [], []
    for i, r in enumerate(rows):
        coll = r.get("collect") or {}
        dec = float(coll.get("decisions") or 0)
        cs = float((r.get("profile") or {}).get("collect_s") or 0.0)
        if dec > 0 and cs > 0:
            cdec.append(dec / cs)
        if i == 0:
            continue
        dt = float(r.get("seconds") or 0) - float(rows[i - 1].get("seconds") or 0)
        if dt > 0 and dec > 0:
            wdec.append(dec / dt)
            dps.append(dec / dt)
    out = {"iters": len(rows)}
    if cols:
        seg = cols[:max(int(min_iters), 1)] if len(cols) >= min_iters else cols
        out["collect_s_p50"] = float(np.percentile(seg, 50))
        out["collect_s_n"] = len(seg)
    if cdec:
        seg = cdec[:max(int(min_iters), 1)] if len(cdec) >= min_iters else cdec
        out["collect_decisions_per_s_p50"] = float(np.percentile(seg, 50))
    if wdec:
        seg = wdec[:max(int(min_iters), 1)] if len(wdec) >= min_iters else wdec
        out["wall_decisions_per_s_p50"] = float(np.percentile(seg, 50))
    ppo = [float((r.get("profile") or {}).get("ppo_s") or 0.0) for r in rows]
    if ppo:
        out["ppo_s_p50"] = float(np.percentile(ppo, 50))
    out["last_iter"] = rows[-1].get("iter")
    ppo_rec = rows[-1].get("ppo") or {}
    for k in ("problem_bc_loss", "problem_bc_top1_acc", "strength_aux_loss",
              "strength_mse", "strength_bce", "strength_tier_acc", "bc_loss",
              "dpo_loss", "bc_accept_rate"):
        if k in ppo_rec:
            out[k] = ppo_rec[k]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--human", action="append", default=[],
                    help="name=path（human_panel_eval 输出 JSON）")
    ap.add_argument("--quality", action="append", default=[],
                    help="name=path（quality_monitor 输出 JSON）")
    ap.add_argument("--history", action="append", default=[],
                    help="name=run_dir（train_entity_sync 的 out 目录）")
    ap.add_argument("--base", default="A", help="对照臂名（默认 A）")
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    human = {_pair(s)[0]: human_arm(_load(_pair(s)[1])) for s in args.human}
    qual = {_pair(s)[0]: quality_arm(_load(_pair(s)[1])) for s in args.quality}
    hist = {_pair(s)[0]: collect_stats(_pair(s)[1]) for s in args.history}
    base = args.base
    names = sorted(set(human) | set(qual) | set(hist))
    base_ranks = human.get(base, {}).get("_ranks")
    summary = {"base": base, "arms": {}}
    for name in names:
        row = {"human": {k: v for k, v in (human.get(name) or {}).items()
                         if not k.startswith("_")},
               "quality": qual.get(name) or {},
               "collect": hist.get(name) or {}}
        if base_ranks is not None and name in human:
            r = human[name]["_ranks"]
            if r.size == base_ranks.size:
                d = (r - base_ranks).astype(np.float64)
                lo, hi = boot_ci(d, n=int(args.bootstrap))
                row["paired"] = {
                    "n": int(d.size), "delta_mean": float(d.mean()),
                    "ci_low": lo, "ci_high": hi,
                    "top4_delta_pp": float(100.0 * (
                        np.mean(r <= 4) - np.mean(base_ranks <= 4))),
                }
        if base in qual and name in qual:
            b = qual[base]
            row["quality_delta"] = {}
            for k in ("strength_ratio_t12", "strength_ratio_t15",
                      "tier_ge5_t12", "tier_ge5_t15", "death_strength_p50",
                      "tier_p50_t12", "tier_p50_t15"):
                v, bv = row["quality"].get(k), b.get(k)
                if isinstance(v, (int, float)) and isinstance(bv, (int, float)) \
                        and float(bv) != 0.0:
                    row["quality_delta"][k] = {
                        "value": float(v), "base": float(bv),
                        "rel_pct": float(100.0 * (float(v) / float(bv) - 1.0))}
        summary["arms"][name] = row

    # 门禁判定（§2.3）：human Δ<=-0.10 且 CI 上界<+0.05；top4 >= base-2pp；
    # 强度比 t12/t15 各 >= +10%；tier>=5 与出局强度不低于 base；collect < +15%。
    base_collect = (summary["arms"].get(base, {}).get("collect") or {})
    for name, row in summary["arms"].items():
        if name == base:
            continue
        gates = {}
        p = row.get("paired") or {}
        if p:
            gates["human_delta"] = bool(p["delta_mean"] <= -0.10
                                        and p["ci_high"] < 0.05)
            gates["human_top4"] = bool(p["top4_delta_pp"] >= -2.0)
        qd = row.get("quality_delta") or {}
        for k, need in (("strength_ratio_t12", 10.0),
                        ("strength_ratio_t15", 10.0)):
            if k in qd:
                gates[f"{k}_ge_{int(need)}pct"] = bool(qd[k]["rel_pct"] >= need)
        for k in ("tier_ge5_t12", "tier_ge5_t15", "death_strength_p50"):
            if k in qd:
                gates[f"{k}_not_lower"] = bool(qd[k]["rel_pct"] >= 0.0)
        hc = row.get("collect") or {}
        # 采集门（§5.4）：wall 与吞吐**都不退化超过 15%**。
        #   collect_s:  cand/base - 1 < 0.15
        #   dec/s   :  cand/base > 1/1.15（吞吐下降不超过 15%）
        if base_collect.get("collect_decisions_per_s_p50") and \
                hc.get("collect_decisions_per_s_p50"):
            ratio = (hc["collect_decisions_per_s_p50"]
                     / base_collect["collect_decisions_per_s_p50"])
            hc["decisions_per_s_rel_pct"] = float(100.0 * (ratio - 1.0))
            gates["collect_dec_s_not_worse_15pct"] = bool(ratio > 1.0 / 1.15)
        if base_collect.get("collect_s_p50") and hc.get("collect_s_p50"):
            rel = hc["collect_s_p50"] / base_collect["collect_s_p50"] - 1.0
            hc["collect_s_rel_pct"] = float(100.0 * rel)
            gates["collect_s_not_worse_15pct"] = bool(rel < 0.15)
        q = row.get("quality") or {}
        gates["hard_errors_zero"] = bool(
            not (row["human"].get("illegal") or row["human"].get("truncated")
                 or row["human"].get("truncated_combats")))
        row["gates"] = gates
        row["passed"] = bool(gates) and all(gates.values())

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)

    # markdown 表
    def _f(v, nd=3):
        return "—" if not isinstance(v, (int, float)) else f"{v:.{nd}f}"

    lines = ["| arm | human mean | Δ vs " + base + " [95% CI] | top4 Δpp | "
             "str t12 | str t15 | tier≥5@t12 | tier≥5@t15 | 出局强度 | "
             "moves/turn | collect Δ | 门禁 |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for name in names:
        r = summary["arms"][name]
        h, q, c = r["human"], r["quality"], r["collect"]
        p, qd = r.get("paired") or {}, r.get("quality_delta") or {}

        def _rel(k):
            return "—" if k not in qd else f"{qd[k]['rel_pct']:+.1f}%"

        if p:
            delta = (f"{p['delta_mean']:+.3f} "
                     f"[{p['ci_low']:+.3f}, {p['ci_high']:+.3f}]")
            top4 = f"{p['top4_delta_pp']:+.2f}"
        else:
            delta, top4 = "—", "—"
        crel = ("—" if "decisions_per_s_rel_pct" not in c
                else f"{c['decisions_per_s_rel_pct']:+.1f}%")
        verdict = ("baseline" if name == base
                   else ("PASS" if r.get("passed") else "FAIL"))
        lines.append(
            f"| {name} | {_f(h.get('mean_rank'))} | {delta} | {top4} | "
            f"{_f(q.get('strength_ratio_t12'))} ({_rel('strength_ratio_t12')}) | "
            f"{_f(q.get('strength_ratio_t15'))} ({_rel('strength_ratio_t15')}) | "
            f"{_f(q.get('tier_ge5_t12'), 2)} ({_rel('tier_ge5_t12')}) | "
            f"{_f(q.get('tier_ge5_t15'), 2)} ({_rel('tier_ge5_t15')}) | "
            f"{_f(q.get('death_strength_p50'), 0)} ({_rel('death_strength_p50')}) | "
            f"{_f(q.get('moves_per_turn_mean'), 2)} | {crel} | {verdict} |")
    md = "\n".join(lines)
    print(text if not args.out else md)
    if args.out:
        with open(args.out + ".md", "w", encoding="utf-8") as fh:
            fh.write(md + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
