#!/usr/bin/env python3
"""在「可指定收入口径」的 economy sandbox 上评测一个 checkpoint（greedy + sample）。

为什么要单独一个脚本
--------------------
``scripts/train_economy_sandbox.py`` 的评测是训练循环里的（每 1M 决策 48 局），
而 ``t15 Σ`` 是重尾分布（p90/max 差一个量级），48 局的 p50 有 ±20% 噪声。复现判据
（``docs/COMPOUND_INCOME.md`` §4）需要**同一口径下更多局**的复核值，所以这里复用
训练脚本的 ``evaluate()``（同一套 ``VectorEconomySandbox`` / 同一套度量），
只把「收入口径」与「局数」暴露成 CLI。

用法::

    python scripts/eval_income_sandbox.py \
        --checkpoint runs/comp_lines/tiny_G15_growth/model.pt \
        --gold-mode growth --gold-growth-rate 0.15 --gold-per-carrier 2 \
        --games 192 --device cuda:7 --json-out runs/comp_lines/tiny_G15_eval192.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hsbg.az.train.economy_sandbox import SandboxConfig, summarize  # noqa: E402


def _comps_ids(path: str):
    """Firestone 阵容 → (核心牌 id 列表, 关键饰品 id 列表)。"""
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(p):
        return [], []
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    cs = d.get("comps") or []
    core = sorted({str(c["id"]) for x in cs for c in (x.get("core_cards") or ())
                   if str(c.get("id"))})
    trk = sorted({str(t["id"]) for x in cs for t in (x.get("trinkets") or ())
                  if str(t.get("id"))})
    return core, trk


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="economy sandbox checkpoint 评测（收入口径可配）")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--games", type=int, default=192)
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--seed-base", type=int, default=950000)
    ap.add_argument("--sample", type=int, default=1, help="1 = 采样(T=1)，0 = greedy")
    ap.add_argument("--both", type=int, default=1, help="1 = sample 与 greedy 都评")
    ap.add_argument("--turns", type=int, default=15)
    ap.add_argument("--gold-per-turn", type=int, default=30)
    ap.add_argument("--gold-mode", default="growth",
                    choices=["fixed", "set", "add", "growth"],
                    help="收入口径（与 --gold-mode 训练参数同义，见 docs/COMPOUND_INCOME.md）")
    ap.add_argument("--gold-add", type=int, default=0)
    ap.add_argument("--gold-growth-rate", type=float, default=0.0)
    ap.add_argument("--gold-per-carrier", type=int, default=0)
    ap.add_argument("--sandbox-income-scale", dest="income_scale", type=float, default=1.0)
    ap.add_argument("--gold-cap", type=int, default=99)
    ap.add_argument("--action-cap", type=int, default=40)
    ap.add_argument("--action-cap-per-gold", dest="action_cap_per_gold", type=int,
                    default=0, help="闸门 1：动作上限 = action-cap + floor(金币/K)（0=关）")
    ap.add_argument("--tavern-buff-scale", dest="tavern_buff_scale", type=float,
                    default=1.0, help="闸门 2：酒馆永久 buff 的增量缩放（1.0=引擎原样）")
    ap.add_argument("--sandbox-trinkets", dest="trinkets", type=int, default=1)
    ap.add_argument("--comps-json", default="data/scaling/comps_top.json")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    from hsbg.az.train.model import load_checkpoint  # noqa: PLC0415
    from train_economy_sandbox import evaluate  # noqa: PLC0415

    cfg = SandboxConfig(
        turns=int(args.turns), gold_per_turn=int(args.gold_per_turn),
        gold_mode=str(args.gold_mode), action_cap=int(args.action_cap),
        action_cap_per_gold=int(args.action_cap_per_gold),
        tavern_buff_scale=float(args.tavern_buff_scale),
        gold_add=int(args.gold_add), gold_growth_rate=float(args.gold_growth_rate),
        gold_per_carrier=int(args.gold_per_carrier),
        income_scale=float(args.income_scale), gold_cap=int(args.gold_cap),
        trinkets=(None if int(args.trinkets) < 0 else bool(int(args.trinkets))),
        reward="exp_growth", reward_mix="",
        growth_w_final=1.0, growth_w_super=0.2, growth_slope_base=0.35,
        growth_from=10, growth_w_ratio=0.3, seed=0)
    cfg.validate()
    core_ids, trinket_ids = _comps_ids(str(args.comps_json))
    if cfg.trinkets is None:
        trinket_ids = None

    model, meta = load_checkpoint(str(args.checkpoint), device="cpu")
    import torch  # noqa: PLC0415
    model.to(torch.device(args.device))
    print(f"[eval] ckpt={args.checkpoint} meta={ {k: meta.get(k) for k in ('arch','d_model','n_layers')} } "
          f"gold={cfg.gold_mode} base={cfg.gold_per_turn} r={cfg.gold_growth_rate} "
          f"per_carrier={cfg.gold_per_carrier} cap={cfg.gold_cap} games={args.games}", flush=True)

    out: Dict[str, Any] = {"checkpoint": args.checkpoint,
                           "cfg": {"gold_mode": cfg.gold_mode,
                                   "gold_per_turn": cfg.gold_per_turn,
                                   "gold_add": cfg.gold_add,
                                   "gold_growth_rate": cfg.gold_growth_rate,
                                   "gold_per_carrier": cfg.gold_per_carrier,
                                   "income_scale": cfg.income_scale,
                                   "gold_cap": cfg.gold_cap,
                                   "action_cap": cfg.action_cap,
                                   "action_cap_per_gold": cfg.action_cap_per_gold,
                                   "tavern_buff_scale": cfg.tavern_buff_scale,
                                   "trinkets": cfg.trinkets,
                                   "turns": cfg.turns},
                           "games": int(args.games)}
    modes = [1, 0] if int(args.both) else [int(args.sample)]
    for smp in modes:
        eps = evaluate(model, cfg, int(args.games), args.device,
                       seed0=int(args.seed_base), sample=bool(smp),
                       core_ids=core_ids, trinket_ids=trinket_ids)
        rep = summarize(eps) if isinstance(eps, list) else eps
        tag = "sample" if smp else "greedy"
        out[tag] = rep
        print(f"[eval:{tag}] t12 p50={rep['sigma_t12_p50']:.0f} t15 p50={rep['sigma_t15_p50']:.0f} "
              f"p90={rep.get('sigma_t15_p90', 0):.0f} max={rep.get('sigma_t15_max', 0):.0f} "
              f"Σ12/金={rep.get('sigma12_per_gold_p50', 0):.2f} "
              f"r12_15={rep.get('growth_ratio_12_15_p50', 0):.2f} "
              f"gold={rep.get('gold_total_income_p50', 0):.0f} "
              f"goldens={rep.get('goldens_p50', 0):.0f} spells={rep['spells_p50']:.0f} "
              f"core={rep.get('core_t15_p50', 0):.0f} "
              + (f"g1_act={rep.get('actions_total_p50', 0):.0f} "
                 f"cap={rep.get('action_cap_eff_mean', 0):.0f} "
                 if "actions_total_p50" in rep else "")
              + (f"g2_tavS={rep.get('tavern_buff_scaled_p50', 0):.0f} "
                 f"ex={rep.get('tavern_extra_p50', 0):.0f} "
                 if "tavern_extra_p50" in rep else "")
              + f"trk={rep.get('trinkets_p50', 0):.0f}/{rep.get('trinket_hit_rate', 0):.2f}",
              flush=True)
    if args.json_out:
        p = args.json_out if os.path.isabs(args.json_out) else os.path.join(ROOT, args.json_out)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"[eval] → {os.path.relpath(p, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
