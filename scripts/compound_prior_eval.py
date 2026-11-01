#!/usr/bin/env python3
"""复利核心牌先验的**统一评测**（训练结束后对 checkpoint 做一次干净读数）。

为什么单独一个脚本
------------------
``scripts/train_economy_sandbox.py`` 的训练期评测不做载体施法审计（每决策多一次
``view(0)`` ≈0.45 ms，训练时每次都做太贵）。这里对**同一个 checkpoint** 一次性跑：

- ``t12 / t15 Σ`` p50/p90（``sample`` 与 ``greedy`` 两种口径）；
- 载体率、载体在场回合数、**对载体施法数**（``carrier_audit=1``，与
  ``scripts/quality_monitor.py --carrier-audit 1`` 同口径的 sandbox 版）；
- **目标流派核心牌在场数**（``core_t15_p50`` / ``core_rate`` / ``core_turns_mean``）；
- 可选的复利先验（``--compound-prior-coef`` / ``--archetype-background-penalty``），
  与训练时**同一个** ``CompoundPrior`` 对象口径。

用法
----
    python scripts/compound_prior_eval.py \
        --checkpoint runs/compound_prior/A_noprior/model_final.pt \
        --compound-archetype DEMON --games 64 --device cuda:7 \
        --json-out runs/compound_prior/eval_A.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional, Sequence


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.economy_sandbox import SandboxConfig  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="复利核心牌先验统一评测（载体施法审计 + 核心牌在场）")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=64)
    ap.add_argument("--seed-base", type=int, default=900000)
    ap.add_argument("--turns", type=int, default=15)
    ap.add_argument("--gold-per-turn", type=int, default=30)
    ap.add_argument("--action-cap", type=int, default=40)
    ap.add_argument("--num-players", type=int, default=8)
    ap.add_argument("--lobby-types", default="DEMON,QUILBOAR,DRAGON,PIRATE,MURLOC")
    ap.add_argument("--carrier-audit", type=int, default=1)
    ap.add_argument("--modes", default="sample,greedy")
    # 复利先验（与训练一致的两个系数）
    ap.add_argument("--compound-prior-coef", type=float, default=0.0)
    ap.add_argument("--archetype-background-penalty", type=float, default=0.0)
    ap.add_argument("--compound-archetype", default="")
    ap.add_argument("--compound-table", default="")
    ap.add_argument("--compound-prior-min-prob", type=float, default=0.6)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    from hsbg.az.train.model import load_checkpoint
    from scripts.train_economy_sandbox import _cfg_dict, evaluate  # noqa: PLC0415

    cfg = SandboxConfig(
        turns=int(args.turns), gold_per_turn=int(args.gold_per_turn),
        action_cap=int(args.action_cap), num_players=int(args.num_players),
        lobby_types=tuple(x.strip().upper() for x in args.lobby_types.split(",")
                          if x.strip()))
    cfg.validate()

    prior = None
    core_ids = None
    if float(args.compound_prior_coef) > 0.0 or float(args.archetype_background_penalty) > 0.0:
        from hsbg.az.train.compound_prior import (  # noqa: PLC0415
            DEFAULT_COMPOUND, CompoundPrior, engine_card_id_lookup)
        prior = CompoundPrior(
            coef=float(args.compound_prior_coef),
            background_penalty=float(args.archetype_background_penalty),
            compound_path=str(args.compound_table) or DEFAULT_COMPOUND,
            archetype=str(args.compound_archetype or ""),
            min_prob=float(args.compound_prior_min_prob),
            card_index_of=engine_card_id_lookup())
    if str(args.compound_archetype):
        from hsbg.az.train.compound_prior import DEFAULT_COMPOUND, core_ids_for  # noqa: PLC0415
        core_ids = core_ids_for(str(args.compound_archetype),
                                path=str(args.compound_table) or DEFAULT_COMPOUND,
                                )

    model, meta = load_checkpoint(args.checkpoint, device=str(args.device))
    out: Dict[str, Any] = {"checkpoint": args.checkpoint,
                           "checkpoint_meta": {k: v for k, v in (meta or {}).items()
                                               if k in ("arch", "d_model", "n_layers",
                                                        "decisions", "updates",
                                                        "sandbox_gold_ramp")},
                           "config": _cfg_dict(cfg),
                           "compound_prior": (prior.summary() if prior is not None else {}),
                           "compound_core_ids": core_ids or [],
                           "evals": {}}
    for mode in [m.strip() for m in str(args.modes).split(",") if m.strip()]:
        ev = evaluate(model, cfg, int(args.games), str(args.device),
                      seed0=int(args.seed_base), sample=(mode == "sample"),
                      dtype="fp32", carrier_audit=int(args.carrier_audit),
                      prior=prior, core_ids=core_ids)
        out["evals"][mode] = ev
        print(f"[eval] {mode:6} t12_p50={ev['sigma_t12_p50']:.0f} "
              f"t12_p90={ev['sigma_t12_p90']:.0f} t15_p50={ev['sigma_t15_p50']:.0f} "
              f"carrier={ev['carrier_rate']:.2f} spells={ev['spells_p50']:.0f} "
              f"tavern={ev['tavern_buff_p50']:.0f} "
              f"casts_on_carrier={ev.get('casts_on_carrier_mean', 0.0):.2f} "
              f"core_t15={ev.get('core_t15_p50', 0.0):.0f} "
              f"core_rate={ev.get('core_rate', 0.0):.2f}", flush=True)
    if prior is not None:
        out["compound_prior_stats"] = prior.to_meta()
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, default=float)
        print(f"[eval] 写出 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
