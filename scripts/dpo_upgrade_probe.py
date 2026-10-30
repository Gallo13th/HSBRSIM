#!/usr/bin/env python3
"""upgrade 子集 DPO 的离线诊断（干净基线；不训练、不改权重）。

在 ``runs/az_entity_s8b/model.pt``（干净基线）上统计 upgrade 样本的：

1. ``logp(upgrade)`` 的均值/分位；
2. 当前策略（masked softmax argmax）选 upgrade 的比例；
3. one-sided DPO 损失的初值（``beta`` 可调）与「argmax==chosen 跳过」的接受率；
4. ``logp(upgrade)`` 与「该局面是否真的该升本（tier < 对应目标）」的交叉统计：
   - ``exact``：turn 命中目标表（默认 ``7:4,9:5,12:6``）的样本，``tier < target`` 才叫 should；
   - ``step``：把目标表当阶梯曲线（turn>=12→6、>=9→5、>=7→4）外推，覆盖更多样本。

用法::

    PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python \
        scripts/dpo_upgrade_probe.py --checkpoint runs/az_entity_s8b/model.pt \
        --device cpu --beta 0.1 --out runs/dpo_upgrade_probe.json

``--device cpu`` 默认（不抢训练/评测卡）；GPU 7 空闲时可用 ``--device cuda:7``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

from hsbg.az.train.dpo_upgrade import (  # noqa: E402
    UPGRADE_ACTION,
    dpo_pair_loss,
    load_upgrade_samples,
    masked_policy_logprobs,
)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.tier_target import (  # noqa: E402
    DEFAULT_TIER_TARGET_TABLE,
    tier_target_for_turn,
)


def _softplus(x: np.ndarray) -> np.ndarray:
    return np.logaddexp(0.0, x)


def _step_target(turn: int, table: dict) -> int | None:
    """目标表的阶梯外推：``max{v : t <= turn}``（turn 太小 = None）。"""
    hits = [int(v) for t, v in table.items() if int(turn) >= int(t)]
    return max(hits) if hits else None


def _stats(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    if x.size == 0:
        return {"n": 0, "mean": None, "median": None, "p10": None, "p90": None}
    return {
        "n": int(x.size),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "p10": float(np.percentile(x, 10)),
        "p90": float(np.percentile(x, 90)),
    }


def _group_stat(mask: np.ndarray, logp_chosen: np.ndarray, margins: np.ndarray,
                picked: np.ndarray, beta: float) -> dict:
    """一组样本的 logp/选 upgrade 比例/DPO 损失（跳过 picked 样本）。"""
    n = int(np.count_nonzero(mask))
    if n == 0:
        return {"n": 0}
    lp = logp_chosen[mask]
    mg = margins[mask]
    pk = picked[mask]
    accept = ~pk
    n_acc = int(np.count_nonzero(accept))
    dpo = float(_softplus(-beta * mg[accept]).mean()) if n_acc else None
    out = {
        "n": n,
        "picked": int(np.count_nonzero(pk)),
        "picked_rate": float(np.count_nonzero(pk)) / float(n),
        "n_accepted": n_acc,
        "accept_rate": float(n_acc) / float(n),
        "logp": _stats(lp),
        "mean_margin": float(mg.mean()),
        "dpo_loss": dpo,
    }
    return out


def _crosstab(batch, logp_chosen, margins, picked, targets, beta):
    """``should / ok / na`` × (是否选 upgrade) 的交叉统计 + 2x2 计数。"""
    tier = np.asarray(batch.tier, dtype=np.int64)
    known = np.asarray(batch.tier_known, dtype=bool) & \
        np.asarray(batch.turn_known, dtype=bool)
    tgt = np.asarray([(-1 if t is None else int(t)) for t in targets], dtype=np.int64)
    has_t = (tgt > 0) & known
    should = has_t & (tier < tgt)
    ok = has_t & (tier >= tgt)
    na = ~has_t
    groups = {}
    for name, m in (("should", should), ("ok", ok), ("na", na)):
        groups[name] = _group_stat(m, logp_chosen, margins, picked, beta)
    cells = {}
    for name, m in (("should", should), ("ok", ok), ("na", na)):
        cells[name] = {
            "n": int(np.count_nonzero(m)),
            "picked_upgrade": int(np.count_nonzero(picked & m)),
            "not_picked": int(np.count_nonzero((~picked) & m)),
        }
    shortfall = np.where(has_t, tgt - tier, -1)
    by_shortfall = {}
    for k in (0, 1, 2, 3):
        m = known & (shortfall >= k) if k == 3 else known & (shortfall == k)
        if int(np.count_nonzero(m)):
            by_shortfall[str(k) if k < 3 else "3+"] = _group_stat(
                m, logp_chosen, margins, picked, beta)
    return {
        "groups": groups,
        "cells": cells,
        "by_shortfall": by_shortfall,
    }


def _turn_should(batch, logp_chosen, margins, picked, targets, beta):
    """按 **turn** 拆 should / ok（目标表命中样本）。

    t9/t12 的 ``should.picked_rate`` 就是「该升没升」的 headroom（docs/DPO_UPGRADE.md
    用它做 DPO A/B 的池上效应指标：训练只改这些状态的选择率）。
    """
    tier = np.asarray(batch.tier, dtype=np.int64)
    turns = np.asarray(batch.turn, dtype=np.int64)
    known = np.asarray(batch.tier_known, dtype=bool) & \
        np.asarray(batch.turn_known, dtype=bool)
    tgt = np.asarray([(-1 if t is None else int(t)) for t in targets], dtype=np.int64)
    has_t = (tgt > 0) & known
    should = has_t & (tier < tgt)
    ok = has_t & (tier >= tgt)
    out = {}
    for t in sorted({int(x) for x in turns[has_t].tolist()}):
        mt = has_t & (turns == t)
        s, o = mt & should, mt & ok
        if int(np.count_nonzero(s)) == 0 and int(np.count_nonzero(o)) == 0:
            continue
        out[str(t)] = {"should": _group_stat(s, logp_chosen, margins, picked, beta),
                       "ok": _group_stat(o, logp_chosen, margins, picked, beta)}
    return out


def _tier_should(batch, logp_chosen, margins, picked, targets, beta):
    """按 tier 拆 should / ok（目标表命中样本）；定位 headroom 在哪一级。"""
    tier = np.asarray(batch.tier, dtype=np.int64)
    known = np.asarray(batch.tier_known, dtype=bool) & \
        np.asarray(batch.turn_known, dtype=bool)
    tgt = np.asarray([(-1 if t is None else int(t)) for t in targets], dtype=np.int64)
    has_t = (tgt > 0) & known
    should = has_t & (tier < tgt)
    ok = has_t & (tier >= tgt)
    out = {}
    for t in range(1, 8):
        mt = known & (tier == t)
        s, o = mt & should, mt & ok
        if int(np.count_nonzero(s)) == 0 and int(np.count_nonzero(o)) == 0:
            continue
        out[str(t)] = {
            "should": _group_stat(s, logp_chosen, margins, picked, beta),
            "ok": _group_stat(o, logp_chosen, margins, picked, beta),
        }
    return out


def _fmt_table(rows, headers):
    line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    out = [line, sep]
    for r in rows:
        out.append("| " + " | ".join(str(v) for v in r) + " |")
    return "\n".join(out)


def _fmt(v, nd=4):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="runs/az_entity_s8b/model.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--mmr-min", type=int, default=6000)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--chunk", type=int, default=1024)
    ap.add_argument("--loss-check-limit", type=int, default=256,
                    help="用 dpo_pair_loss 复核前 N 条（0=不复核）")
    ap.add_argument("--out", default="runs/dpo_upgrade_probe.json")
    args = ap.parse_args()
    beta = float(args.beta)

    t0 = time.time()
    batch = load_upgrade_samples(mmr_min=int(args.mmr_min), limit=args.limit)
    n = len(batch)
    if n == 0:
        print("[error] 没有 upgrade 样本（检查路径/MMR 下限）", file=sys.stderr)
        return 1
    print(f"[data] n={n}  mmr_min={args.mmr_min}  path={batch.path}  "
          f"({time.time() - t0:.1f}s)")

    t0 = time.time()
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    model.eval()
    print(f"[model] {args.checkpoint}  arch={meta.get('arch')}  "
          f"device={args.device}  ({time.time() - t0:.1f}s)")

    t0 = time.time()
    logp = masked_policy_logprobs(model, batch, device=args.device,
                                  chunk=int(args.chunk))
    print(f"[forward] {logp.shape} ({time.time() - t0:.1f}s)")

    rows = np.arange(n)
    chosen = np.asarray(batch.action_index, dtype=np.int64)
    logp_chosen = logp[rows, chosen].astype(np.float64)
    # masked argmax = 策略选的动作；rejected 的 logp 即该行最大 logp
    argmax = logp.argmax(axis=1)
    picked = argmax == UPGRADE_ACTION
    logp_rej = logp[rows, argmax].astype(np.float64)
    margins = logp_chosen - logp_rej
    accept = ~picked
    dpo_np = float(_softplus(-beta * margins[accept]).mean()) if accept.any() else None

    tiers = np.asarray(batch.tier, dtype=np.int64)
    turns = np.asarray(batch.turn, dtype=np.int64)
    table = dict(DEFAULT_TIER_TARGET_TABLE)
    targets_exact = [tier_target_for_turn(int(t), table) if k else None
                     for t, k in zip(turns, batch.turn_known)]
    targets_step = [_step_target(int(t), table) if k else None
                    for t, k in zip(turns, batch.turn_known)]

    overall = {
        "n": n,
        "logp_upgrade": _stats(logp_chosen),
        "policy": {
            "picks_upgrade": int(np.count_nonzero(picked)),
            "picks_upgrade_rate": float(np.count_nonzero(picked)) / float(n),
            "mean_margin": float(margins.mean()),
        },
        "dpo": {
            "beta": beta,
            "loss": dpo_np,
            "accept_rate": float(np.count_nonzero(accept)) / float(n),
            "n_accepted": int(np.count_nonzero(accept)),
        },
    }
    # argmax 频次前 5（被拒绝动作的主体，便于判断 DPO 把 upgrade 与谁对比）
    uniq, cnt = np.unique(argmax, return_counts=True)
    order = np.argsort(-cnt)[:5]
    overall["policy"]["argmax_top5"] = [[int(uniq[i]), int(cnt[i])] for i in order]

    # 一致性复核：用模块的 dpo_pair_loss 在子集上再算一次（same beta）
    check = None
    if int(args.loss_check_limit) > 0:
        sub = load_upgrade_samples(mmr_min=int(args.mmr_min),
                                   limit=int(args.loss_check_limit))
        if len(sub) > 0:
            torch = __import__("torch")
            with torch.no_grad():
                loss_t, rate_t = dpo_pair_loss(model, sub, beta=beta,
                                               device=args.device)
            check = {"n": len(sub), "loss": float(loss_t), "accept_rate": float(rate_t)}
            sub_picked = logp[:len(sub)].argmax(axis=1) == UPGRADE_ACTION
            check["loss_numpy"] = (float(_softplus(
                -beta * margins[:len(sub)][~sub_picked]).mean())
                if (~sub_picked).any() else None)

    ct_exact = _crosstab(batch, logp_chosen, margins, picked, targets_exact, beta)
    ct_step = _crosstab(batch, logp_chosen, margins, picked, targets_step, beta)
    by_tier_should = _tier_should(batch, logp_chosen, margins, picked,
                                  targets_exact, beta)
    by_turn_should = _turn_should(batch, logp_chosen, margins, picked,
                                  targets_exact, beta)

    by_tier = {}
    for t in range(1, 8):
        m = np.asarray(batch.tier_known, dtype=bool) & (tiers == t)
        if int(np.count_nonzero(m)):
            by_tier[str(t)] = _group_stat(m, logp_chosen, margins, picked, beta)

    result = {
        "checkpoint": args.checkpoint,
        "device": args.device,
        "mmr_min": int(args.mmr_min),
        "n_samples": n,
        "overall": overall,
        "loss_check": check,
        "crosstab_exact": {"target_table": table, **ct_exact},
        "crosstab_step": {"target_table": table, **ct_step},
        "by_tier": by_tier,
        "by_tier_should": by_tier_should,
        "by_turn_should": by_turn_should,
        "elapsed_s": None,
    }

    # ── 打印摘要 ──
    print()
    print(f"== upgrade 样本 n={n}（MMR>={args.mmr_min}）==")
    print(f"logp(upgrade): mean={overall['logp_upgrade']['mean']:.4f}  "
          f"median={overall['logp_upgrade']['median']:.4f}  "
          f"p10={overall['logp_upgrade']['p10']:.4f}  "
          f"p90={overall['logp_upgrade']['p90']:.4f}")
    print(f"策略选 upgrade: {overall['policy']['picks_upgrade']}/{n} = "
          f"{overall['policy']['picks_upgrade_rate']:.1%}   平均 margin="
          f"{overall['policy']['mean_margin']:.4f}")
    print(f"DPO(beta={beta}): loss={_fmt(overall['dpo']['loss'])}  "
          f"n_accepted={overall['dpo']['n_accepted']}  "
          f"accept_rate={overall['dpo']['accept_rate']:.1%}")
    if check:
        print(f"复核 dpo_pair_loss(n={check['n']}): loss={check['loss']:.4f}  "
              f"accept={check['accept_rate']:.1%}  vs numpy={_fmt(check['loss_numpy'])}")

    for name, ct in (("exact", ct_exact), ("step", ct_step)):
        print()
        print(f"== 交叉统计 / {name}（目标表 {table}）==")
        print(_fmt_table(
            [[g, s["n"], s.get("picked", 0), _fmt(s.get("picked_rate")),
              _fmt(s.get("mean_margin")), _fmt(s.get("logp", {}).get("mean")),
              _fmt(s.get("dpo_loss"))]
             for g, s in ct["groups"].items() if s["n"]],
            ["group", "n", "选upgrade", "picked率", "mean margin",
             "mean logp", "DPO loss"]))
        print("2x2:", {k: (v["picked_upgrade"], v["not_picked"])
                       for k, v in ct["cells"].items()})

    print()
    print("== 按 tier ==")
    print(_fmt_table(
        [[t, s["n"], _fmt(s["picked_rate"]), _fmt(s["logp"]["mean"])]
         for t, s in by_tier.items()],
        ["tier", "n", "picked率", "mean logp"]))

    print()
    print("== tier × should（目标表命中样本；should = tier < target）==")
    print(_fmt_table(
        [[t, v["should"].get("n", 0), _fmt(v["should"].get("picked_rate")),
          _fmt(v["should"].get("logp", {}).get("mean")),
          v["ok"].get("n", 0), _fmt(v["ok"].get("picked_rate")),
          _fmt(v["ok"].get("logp", {}).get("mean"))]
         for t, v in by_tier_should.items()],
        ["tier", "should n", "should pick率", "should logp",
         "ok n", "ok pick率", "ok logp"]))

    print()
    print("== turn × should（目标表命中样本；t9/t12 的 should pick率 = headroom）==")
    print(_fmt_table(
        [[t, v["should"].get("n", 0), _fmt(v["should"].get("picked_rate")),
          _fmt(v["should"].get("logp", {}).get("mean")),
          v["ok"].get("n", 0), _fmt(v["ok"].get("picked_rate")),
          _fmt(v["ok"].get("logp", {}).get("mean"))]
         for t, v in by_turn_should.items()],
        ["turn", "should n", "should pick率", "should logp",
         "ok n", "ok pick率", "ok logp"]))

    result["elapsed_s"] = time.time() - t0
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2,
                      default=lambda o: str(o))
        print(f"\n[json] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
