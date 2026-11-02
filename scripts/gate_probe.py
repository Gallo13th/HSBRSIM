#!/usr/bin/env python3
"""闸门 1+2 的上界探针（脚本策略，纯 CPU）：动作额度 ∝ 收入 + 酒馆永久 buff 可 farm。

为什么单独一个脚本
------------------
``docs/COMPOUND_INCOME.md`` §5.1 的结论是：沙盒「机制齐全、但乘性链条无法被放大」，
缺的是两条**结构性**的东西：

1. **闸门 1**（``--action-cap-per-gold K``）：40 个动作最多花 ~120 金，growth 收入下
   ~60% 的金币是废的 → 每回合动作上限改成 ``action_cap + floor(金币/K)``；
2. **闸门 2**（``--tavern-buff-scale S``）：``tavern_buff_p50 = 8``，真实是「每回合
   5–10 次施法 × 每次 +1~+5 × 再被金色/触发翻倍」→ 把酒馆永久 buff 的增量整体 ×S。

本脚本**不训练**，只用脚本策略在 4 组配置（+3 组 growth 补充档）各跑 N 局，回答
「把这两条结构性限制拆掉之后，形状闸门能不能打开」：

判据（``docs/GATE_ACTION_BUFF.md``）：出现 ``Σ15/Σ12 ≥ 2`` **且** ``t15 Σ ≥ 3,000``
的配置，才算「形状闸门被打开」。

用法::

    python scripts/gate_probe.py --games 100 --workers 12 \
        --json-out runs/comp_lines/gate_probe.json
    python scripts/gate_probe.py --arms G0,G3 --games 8 --workers 4     # 快速冒烟
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    EconomySandbox, SandboxConfig, summarize)

from income_probe import (  # noqa: E402
    BASE_GOLD_TOTAL, GOLD_REF, TURNS_REF, IncomeSandboxPolicies, _gold_ids, _spell_ids)

#: 收入偏好（任务口径：优先金币/法术生成饰品 + 载体施法）。
#: ``buy_income=0``：I4/I5 的实测结论是「为了收入买牌会挤掉载体」，这里保持载体优先。
_POL = dict(trinket_classes=("gold", "spell_gen", "spell_amp"), buy_income=False,
            unlock_refresh=True)

#: growth 收入档（与训练臂 G15 同口径）：闸门 1 只有在「钱多于 30/回合」时才会咬住
_GROWTH = dict(gold_mode="growth", gold_per_turn=GOLD_REF, gold_growth_rate=0.15,
               gold_per_carrier=2, gold_cap=99)

ARMS: Dict[str, Dict[str, Any]] = {
    "G0": {
        "desc": "基线：fixed 30/回合、动作上限 40、S=1（= 现状）",
        "cfg": dict(gold_mode="fixed", gold_per_turn=GOLD_REF),
    },
    "G1": {
        "desc": "闸门 1：+ --action-cap-per-gold 3（30 金 → +10 动作）",
        "cfg": dict(gold_mode="fixed", gold_per_turn=GOLD_REF, action_cap_per_gold=3),
    },
    "G2": {
        "desc": "闸门 2：+ --tavern-buff-scale 3（酒馆永久 buff 的增量 ×3）",
        "cfg": dict(gold_mode="fixed", gold_per_turn=GOLD_REF, tavern_buff_scale=3.0),
    },
    "G3": {
        "desc": "两者叠加：action-cap-per-gold 3 + tavern-buff-scale 3",
        "cfg": dict(gold_mode="fixed", gold_per_turn=GOLD_REF, action_cap_per_gold=3,
                    tavern_buff_scale=3.0),
    },
    # ── 补充档：闸门 1 在 fixed 30 金下几乎不咬（40 动作本来花不完 30 金），
    #    真正该看的是 growth 收入下它能不能把「废掉的金币」变成动作。
    "G0g": {
        "desc": "补充基线：growth 0.15 + 2/载体（与 G15 同口径）、动作上限 40、S=1",
        "cfg": dict(_GROWTH),
    },
    "G1g": {
        "desc": "补充：growth 收入 + action-cap-per-gold 3",
        "cfg": dict(_GROWTH, action_cap_per_gold=3),
    },
    "G3g": {
        "desc": "补充：growth 收入 + 两个闸门都开（K=3, S=3）",
        "cfg": dict(_GROWTH, action_cap_per_gold=3, tavern_buff_scale=3.0),
    },
    # ── S 扫描：沙盒的 tavern buff 计量器 15 回合只到 ~8，真实是「每回合 5–10 次施法
    #    × 每次 +1~+5 × 触发/金色翻倍」≈ 50–500 ⇒ 要把 S 当**标定系数**扫，
    #    找到「等效于真实量级」的 S 以及两个判据的临界 S。
    "G3gS6": {
        "desc": "补充：growth + K=3 + S=6（酒馆 buff 等效 ×6）",
        "cfg": dict(_GROWTH, action_cap_per_gold=3, tavern_buff_scale=6.0),
    },
    "G3gS12": {
        "desc": "补充：growth + K=3 + S=12（把 8 点的计量器标定到 ~96，接近真实量级）",
        "cfg": dict(_GROWTH, action_cap_per_gold=3, tavern_buff_scale=12.0),
    },
    "G3gS24": {
        "desc": "补充：growth + K=3 + S=24（上界：计量器 ~192）",
        "cfg": dict(_GROWTH, action_cap_per_gold=3, tavern_buff_scale=24.0),
    },
    # ── 钱极多的上界（与 I4/G35u 同口径）：闸门 1 在这里才真正咬住（金币远超 30/回合）
    "Ub0": {
        "desc": "上界基线：growth 0.35 + 2/载体、无金币上限、动作 120（= I4/G35u 口径）",
        "cfg": dict(gold_mode="growth", gold_per_turn=GOLD_REF, gold_growth_rate=0.35,
                    gold_per_carrier=2, gold_cap=0, action_cap=120),
    },
    "Ub1": {
        "desc": "上界 + 闸门 1：动作上限 = 120 + floor(金币/3)（钱多 → 动作多）",
        "cfg": dict(gold_mode="growth", gold_per_turn=GOLD_REF, gold_growth_rate=0.35,
                    gold_per_carrier=2, gold_cap=0, action_cap=120,
                    action_cap_per_gold=3),
    },
    "Ub2": {
        "desc": "上界 + 两个闸门（K=3, S=12）",
        "cfg": dict(gold_mode="growth", gold_per_turn=GOLD_REF, gold_growth_rate=0.35,
                    gold_per_carrier=2, gold_cap=0, action_cap=120,
                    action_cap_per_gold=3, tavern_buff_scale=12.0),
    },
}

#: 判据（docs/GATE_ACTION_BUFF.md）：形状闸门「打开」的两个条件
CRITERIA = {"ratio_12_15": 2.0, "sigma_t15": 3000.0}


def _arm_cfg(name: str) -> SandboxConfig:
    kw: Dict[str, Any] = dict(turns=TURNS_REF, action_cap=40, trinkets=True,
                              reward="log_strength")
    kw.update(ARMS[name]["cfg"])
    return SandboxConfig(**kw)


def run_games(arm: str, seeds: Sequence[int]) -> List[Dict[str, Any]]:
    cfg = _arm_cfg(arm)
    out: List[Dict[str, Any]] = []
    for s in seeds:
        env = EconomySandbox(cfg)
        obs = env.reset(int(s))
        pol = IncomeSandboxPolicies(env.g, seed=0, **_POL)
        steps = 0
        while not env.done:
            a = pol.act(env.g, obs.mask)
            obs, _r, _d, _info = env.step(int(a))
            steps += 1
        ep = dict(env.episode_summary())
        ep["decisions"] = int(steps)
        ep["arm"] = arm
        ep["picked_trinkets"] = list(ep.get("trinket_ids") or [])
        out.append(ep)
    return out


def aggregate(arm: str, eps: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """一档的汇总：形状（Σ15/Σ12）+ 两个中间指标 + 金币口径。"""
    rep = summarize(eps)
    s12 = [float(e.get("sigma_t12") or 0) for e in eps]
    s15 = [float(e.get("sigma_t15") or 0) for e in eps]
    gi = [float(e.get("gold_total_income") or 0) for e in eps]

    def _pct(vals: Sequence[float], q: float) -> float:
        return float(np.percentile(np.asarray(vals, np.float64), q)) if vals else 0.0

    gold_ids = _gold_ids()
    spell_ids = _spell_ids()
    rep.update({
        "arm": arm,
        "desc": ARMS[arm]["desc"],
        "games": len(eps),
        "gold_total_income_p50": rep.get("gold_total_income_p50"),
        "gold_income_ratio": (float(np.mean(gi)) / BASE_GOLD_TOTAL) if gi else 0.0,
        "sigma12_per_gold_mean": float(np.mean(
            [a / b for a, b in zip(s12, gi) if b > 0])) if gi else 0.0,
        "sigma15_per_gold_mean": float(np.mean(
            [a / b for a, b in zip(s15, gi) if b > 0])) if gi else 0.0,
        "golden_trinket_pick_rate": float(np.mean([
            1.0 if any(x in gold_ids for x in (e.get("picked_trinkets") or ())) else 0.0
            for e in eps])) if eps else 0.0,
        "spell_trinket_pick_rate": float(np.mean([
            1.0 if any(x in spell_ids for x in (e.get("picked_trinkets") or ())) else 0.0
            for e in eps])) if eps else 0.0,
        "t15_p90": _pct(s15, 90),
        "t15_p99": _pct(s15, 99),
        "t15_ge_3k_rate": float(np.mean([1.0 if v >= 3000 else 0.0 for v in s15]))
        if s15 else 0.0,
        "t15_ge_10k_rate": float(np.mean([1.0 if v >= 10000 else 0.0 for v in s15]))
        if s15 else 0.0,
    })
    rep["gate_open"] = bool(
        float(rep.get("growth_ratio_12_15_p50") or 0.0) >= CRITERIA["ratio_12_15"]
        and float(rep.get("sigma_t15_p50") or 0.0) >= CRITERIA["sigma_t15"])
    return rep


def _chunks(items: Sequence[int], n: int) -> List[List[int]]:
    k = max(1, int(math.ceil(len(items) / max(1, n))))
    return [list(items[i:i + k]) for i in range(0, len(items), k)]


def _worker(task):
    arm, seeds = task
    return arm, run_games(arm, seeds)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="闸门 1+2 上界探针（脚本策略，纯 CPU）")
    ap.add_argument("--games", type=int, default=100, help="每档局数（默认 100）")
    ap.add_argument("--seed", type=int, default=770000)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--json-out", default="runs/comp_lines/gate_probe.json")
    args = ap.parse_args(argv)

    arms = [a.strip() for a in str(args.arms).split(",") if a.strip()]
    for a in arms:
        if a not in ARMS:
            raise SystemExit(f"未知档位 {a!r}（可选 {sorted(ARMS)}）")
    seeds = [int(args.seed) + i for i in range(int(args.games))]
    tasks = [(a, c) for a in arms for c in _chunks(seeds, max(1, int(args.workers)))]

    t0 = time.perf_counter()
    eps_by_arm: Dict[str, List[Dict[str, Any]]] = {a: [] for a in arms}
    if int(args.workers) > 1:
        ctx = mp.get_context("fork")
        with ctx.Pool(int(args.workers)) as pool:
            for arm, eps in pool.imap_unordered(_worker, tasks):
                eps_by_arm[arm].extend(eps)
                print(f"  [{arm}] +{len(eps)} 局 "
                      f"({len(eps_by_arm[arm])}/{len(seeds)}) "
                      f"{time.perf_counter() - t0:.0f}s", flush=True)
    else:
        for task in tasks:
            arm, eps = _worker(task)
            eps_by_arm[arm].extend(eps)

    reps: Dict[str, Dict[str, Any]] = {}
    hdr = (f"{'arm':5s} {'t12':>7s} {'t15':>7s} {'r12_15':>6s} {'tav':>5s} "
           f"{'tavS':>6s} {'tavEx':>7s} {'gold':>5s} {'spells':>6s} {'金币':>6s} "
           f"{'S15/金':>6s} {'act':>5s} {'cap':>5s} {'open'}")
    print("\n" + hdr)
    for a in arms:
        rep = aggregate(a, eps_by_arm[a])
        reps[a] = rep
        print(f"{a:5s} {rep['sigma_t12_p50']:7.0f} {rep['sigma_t15_p50']:7.0f} "
              f"{rep.get('growth_ratio_12_15_p50') or 0:6.2f} "
              f"{rep.get('tavern_buff_p50') or 0:5.0f} "
              f"{rep.get('tavern_buff_scaled_p50') or 0:6.0f} "
              f"{rep.get('tavern_extra_p50') or 0:7.0f} "
              f"{rep.get('goldens_p50') or 0:5.0f} {rep['spells_p50']:6.0f} "
              f"{rep.get('gold_total_income_p50') or 0:6.0f} "
              f"{rep.get('sigma15_per_gold_p50') or 0:6.2f} "
              f"{rep.get('actions_total_p50') or 0:5.0f} "
              f"{rep.get('action_cap_eff_mean') or 0:5.0f} "
              f"{'✓' if rep['gate_open'] else '✗'}")

    opened = [a for a in arms if reps[a]["gate_open"]]
    best = max(reps.values(), key=lambda r: float(r.get("sigma_t15_p50") or 0))
    print(f"\n[verdict] 打开形状闸门的档位: {opened or '无'}"
          f"（判据 Σ15/Σ12 ≥ {CRITERIA['ratio_12_15']} 且 t15 Σ ≥ {CRITERIA['sigma_t15']:.0f}）")
    print(f"[verdict] t15 Σ 最高 = {best['sigma_t15_p50']:.0f} @ {best['arm']}"
          f"（Σ15/Σ12 = {best.get('growth_ratio_12_15_p50'):.2f}）")

    if args.json_out:
        out = os.path.abspath(args.json_out)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        payload = {
            "meta": {"generated_by": "scripts/gate_probe.py",
                     "games_per_arm": int(args.games), "seed0": int(args.seed),
                     "workers": int(args.workers), "turns": TURNS_REF,
                     "gold_ref": GOLD_REF, "base_gold_total": BASE_GOLD_TOTAL,
                     "seconds": round(time.perf_counter() - t0, 1),
                     "policy": {k: (list(v) if isinstance(v, tuple) else v)
                                for k, v in _POL.items()},
                     "note": "脚本策略（spell 基线 + 金币/法术饰品偏好）下的闸门上界探针"},
            "criteria": CRITERIA,
            "arms": reps,
            "verdict": {"opened": opened,
                        "best_arm": best["arm"],
                        "best_sigma_t15_p50": best["sigma_t15_p50"],
                        "best_ratio_12_15": best.get("growth_ratio_12_15_p50")},
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"[probe] → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
