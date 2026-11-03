#!/usr/bin/env python3
"""全阵容探针：对 ``COMPS``（26 套 roles.json implementable + 2 套扩展）跑合法性与强度。

只读、纯 CPU、不训练、不占 GPU。两种模式：

- ``hybrid``：CompPolicy 只接管阵容动作，其余交引擎 bot（现行默认口径）；
- ``pure``：纯手写经济（``_recruit`` / ``_recruit_f`` 全接管），对照用。

每个（阵容, 模式）跑 ``--games`` 局，输出 legal_rate（**非法动作必须为 0**）、
core_turn p50、t15 Σ p50、placement p50；并抽样做**确定性检验**（同 seed 两次逐字段相同）。

用法::

    PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    $PY scripts/comp_full_probe.py --comps all --games 10
    $PY scripts/comp_full_probe.py --comps J,M,undead_apm --games 10 --modes hybrid
    $PY scripts/comp_full_probe.py --comps all --games 10 --out /tmp/full_probe.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import comp_scripts as CS  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "runs/comp_scripts/full_probe.json")


def _row(key: str, mode: str, rep: dict) -> dict:
    return {
        "comp": key,
        "name": CS.COMPS[key].name,
        "mode": mode,
        "games": rep["games"],
        "legal_rate": round(float(rep["legal_rate"]), 6),
        "illegal": int(rep["illegal"]),
        "decisions": int(rep["decisions"]),
        "t15_p50": rep["sigma_t15_p50"],
        "t15_p90": rep["sigma_t15_p90"],
        "t15_max": rep["sigma_t15_max"],
        "core_turn_p50": rep["core_turn_p50"],
        "core_rate": round(float(rep["core_rate"]), 3),
        "placement_p50": rep.get("placement_p50", rep["placement_mean"]),
        "placement_mean": round(float(rep["placement_mean"]), 3),
        "top4_rate": round(float(rep["top4_rate"]), 3),
        "exit_rate": round(float(rep["exited_rate"]), 3),
        "carrier_rate": round(float(rep["carrier_rate"]), 3),
        "spells_mean": rep["spells_mean"],
    }


def _det_check(keys: List[str], seed: int) -> Dict[str, Any]:
    """确定性：同一 seed 跑两次，整条 episode dict 必须逐字段相同（hybrid）。"""
    out: Dict[str, Any] = {}
    for k in keys:
        spec = CS.COMPS[k]
        a = CS.play_one(seed, spec, hybrid=True)
        b = CS.play_one(seed, spec, hybrid=True)
        same = json.dumps(a, sort_keys=True, default=float) == json.dumps(
            b, sort_keys=True, default=float)
        out[k] = bool(same)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="全阵容脚本探针（CPU，只读）")
    ap.add_argument("--comps", default="all", help="all | 逗号分隔 key（A,J,M,undead_apm）")
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=910000)
    ap.add_argument("--modes", default="hybrid,pure", help="hybrid,pure（逗号分隔）")
    ap.add_argument("--no-exit-on-miss", action="store_true",
                    help="关闭 V2 核心窗口退出（老口径对照）")
    ap.add_argument("--det-check", default="all",
                    help="确定性抽检：all | none | 数字（前 N 套）")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if args.comps == "all":
        keys = CS.comp_keys()
    else:
        keys = [k.strip() for k in args.comps.split(",") if k.strip()]
        bad = [k for k in keys if k not in CS.COMPS]
        if bad:
            print(f"[probe] 未知阵容 {bad}；可选 {CS.comp_keys()}", file=sys.stderr)
            return 2
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in ("hybrid", "pure"):
            print(f"[probe] 未知模式 {m!r}（hybrid|pure）", file=sys.stderr)
            return 2

    t0 = time.time()
    rows: List[dict] = []
    for mode in modes:
        for key in keys:
            eps = CS.run_comp(key, int(args.games), int(args.workers), int(args.seed),
                              "", 0, 0.0, "full", auto=False,
                              hybrid=(mode == "hybrid"),
                              exit_on_miss=not bool(args.no_exit_on_miss))
            rep = CS.summarize(eps)
            r = _row(key, mode, rep)
            rows.append(r)
            print(f"[{mode:6s}/{key:22s}] n={r['games']:2d} legal={r['legal_rate']:.4f} "
                  f"t15Σ p50={r['t15_p50']:6.0f} core_t={r['core_turn_p50']:5.1f} "
                  f"place={r['placement_mean']:.2f} exit={r['exit_rate']:.2f}", flush=True)

    det: Dict[str, Any] = {}
    if args.det_check != "none":
        det_keys = keys if args.det_check == "all" else keys[:int(args.det_check)]
        det = _det_check(det_keys, int(args.seed))

    illegal_total = int(sum(r["illegal"] for r in rows))
    decisions_total = int(sum(r["decisions"] for r in rows))
    summ = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "comps": len(keys),
        "modes": modes,
        "games_per_cell": int(args.games),
        "seed": int(args.seed),
        "exit_on_miss": not bool(args.no_exit_on_miss),
        "illegal_total": illegal_total,
        "decisions_total": decisions_total,
        "legal_rate": round(1.0 - illegal_total / max(1, decisions_total), 6),
        "determinism": det,
        "determinism_ok": all(det.values()) if det else None,
        "rows": rows,
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps({k: v for k, v in summ.items() if k != "rows"},
                     ensure_ascii=False, indent=1), flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1, default=float)
    print(f"[probe] -> {args.out}", flush=True)
    return 0 if illegal_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
