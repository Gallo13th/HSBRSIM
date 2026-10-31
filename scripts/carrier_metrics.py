#!/usr/bin/env python3
"""载体率指标（可接 ``scripts/quality_monitor.py`` / 课程退火门 / CI）。

从 rollout jsonl（``scripts/carrier_audit.py`` / ``scripts/carrier_teacher.py``
产出的格式，或历史 ``runs/scaling_signal/rollouts/*.jsonl``）计算质量面板需要
的三个量：

- ``carrier_encounter_rate``：局级载体率（曾有主集合载体上场）；
- ``casts_on_carrier_mean``：每局对载体施法次数（日志口径）；
- ``r_carrier_turns_str12``：r(载体在场回合数, Σ₁₂)（Pearson/Spearman + bootstrap CI）。

外加 ``carrier_t9_rate`` / ``carrier_turn_rate`` / ``carrier_turns_mean`` /
``carrier_shop_offer_rate`` / ``str12_p50`` 等辅助量，以及课程退火门判定。

用法::

  PYTHONPATH=rust/python:. python scripts/carrier_metrics.py \
      --source runs/scaling_carrier/rollouts/*.jsonl \
      --out runs/scaling_carrier/carrier_metrics.json

  # 作为门禁（不达标返回 3）
  PYTHONPATH=rust/python:. python scripts/carrier_metrics.py --source ... --strict
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import carrier_common as C  # noqa: E402


def _adapt(rows: list, catalog: dict) -> list:
    """旧格式（board_cards 是卡下标）→ 载体 id 口径。"""
    need = [r for r in rows
            if r.get("turns") and "board_carriers" not in (r["turns"][0] or {})]
    if not need:
        return rows
    try:
        import carrier_audit as A  # noqa: PLC0415
        return A.adapt_legacy(rows, catalog)
    except BaseException:  # noqa: BLE001 - 退化为不做映射
        return rows


def compute(paths, carriers: str = C.CATALOG_OUT,
            carrier_target: float = 0.25,
            str12_target: float = 1132.0) -> dict:
    """读 rollout 文件 → 面板指标 dict（纯函数式，可被 quality_monitor 调用）。"""
    catalog = C.load_or_build_catalog(carriers)
    rows: list = []
    used = []
    for p in paths:
        for f in sorted(glob.glob(p)) or [p]:
            if os.path.isfile(f):
                rows.extend(C.read_rollout(f))
                used.append(f)
    rows = _adapt(rows, catalog)
    summ = C.summarize(rows, catalog)
    gate = C.gate_check(summ, carrier_target=carrier_target,
                        str12_target=str12_target)
    c = summ["carrier"]
    s = summ["strength12"]
    corr = summ["corr_carrier_turns_str12"]
    return {
        "sources": used,
        "games": summ["games"],
        "errors": summ["errors"],
        "policy": summ.get("policy"),
        "tag": summ.get("tag"),
        # ── 三个主指标（质量面板 / 退火门）──────────────────────────────
        "carrier_encounter_rate": c["carrier_encounter_rate"],
        "casts_on_carrier_mean": c["casts_on_carrier_mean"],
        "r_carrier_turns_str12": corr.get("pearson"),
        "r_carrier_turns_str12_ci95": corr.get("pearson_ci95"),
        "r_carrier_turns_str12_spearman": corr.get("spearman"),
        "r_carrier_turns_str12_spearman_ci95": corr.get("spearman_ci95"),
        "n_t12": corr.get("n"),
        # ── 辅助 ────────────────────────────────────────────────────────
        "carrier_encounter_rate_narrow": c["carrier_encounter_rate_narrow"],
        "carrier_t9_rate": c["carrier_t9_rate"],
        "carrier_t9_rate_narrow": c.get("carrier_t9_rate_narrow"),
        "carrier_t12_rate": c["carrier_t12_rate"],
        "carrier_turn_rate": c["carrier_turn_rate"],
        "carrier_turns_mean": c["carrier_turns_mean"],
        "carrier_turns_mean_t12_games": c["carrier_turns_mean_t12_games"],
        "carrier_shop_offer_rate": c["carrier_shop_offer_rate"],
        "carrier_bought_rate": c["carrier_bought_rate"],
        "casts_total_mean": c["casts_total_mean"],
        "casts_on_carrier_mean_given_carrier":
            c["casts_on_carrier_mean_given_carrier"],
        "casts_per_carrier_turn": c["casts_per_carrier_turn"],
        "casts_on_carrier_p50": c["casts_on_carrier_dist"].get("p50"),
        "casts_on_carrier_p90": c["casts_on_carrier_dist"].get("p90"),
        "str12_p50": (s.get("all") or {}).get("p50"),
        "str12_mean": (s.get("all") or {}).get("mean"),
        "str12_with_carrier": s.get("with_carrier"),
        "str12_without_carrier": s.get("without_carrier"),
        "str12_mean_diff": s.get("mean_diff"),
        "str12_mean_diff_ci95": s.get("mean_diff_ci95"),
        "mean_rank": summ.get("mean_rank"),
        "top4": summ.get("top4"),
        "gate": gate,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", action="append", default=[], required=True,
                    help="rollout jsonl（可多次，支持 glob）")
    ap.add_argument("--carriers", default=C.CATALOG_OUT)
    ap.add_argument("--out", default="runs/scaling_carrier/carrier_metrics.json")
    ap.add_argument("--carrier-target", type=float, default=0.25)
    ap.add_argument("--str12-target", type=float, default=1132.0,
                    help="默认 2×566（s14_70M quality_monitor 的 t12 p50）")
    ap.add_argument("--strict", action="store_true",
                    help="三项门（载体率/t12 Σ/r>0）不全过时返回 3")
    args = ap.parse_args()
    out = compute(args.source, carriers=args.carriers,
                  carrier_target=float(args.carrier_target),
                  str12_target=float(args.str12_target))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in (
        "games", "policy", "tag", "carrier_encounter_rate",
        "carrier_encounter_rate_narrow", "casts_on_carrier_mean",
        "r_carrier_turns_str12", "r_carrier_turns_str12_ci95",
        "str12_p50", "mean_rank", "gate")}, ensure_ascii=False, indent=1))
    print(f"[out] {args.out}")
    if args.strict and not out["gate"].get("all_ok"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
