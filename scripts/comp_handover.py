#!/usr/bin/env python3
"""Handover 对照：模型（s27d@5M）与阵容脚本（scripts/comp_scripts.py 的 CompPolicy）
按回合区间切换，评测 4 组臂：

  all_model          t0-15:model
  all_script         t0-15:script
  script_then_model  t0-7:script,t8-15:model
  model_then_script  t0-7:model,t8-15:script

指标：t15 Σ p50/p90/max、载体 buff 占比、法术/局、core/enabler/filler 购买、名次。
复用 quality_monitor._play（含 5 席 p0.9 人类战团注入与 .jsonl 产物）。

用法::

  python scripts/comp_handover.py --arm model_then_script --games 96 --mode p09 \
      --comp A --device cuda:4 --out-dir runs/comp_scripts
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hsbg.az.train.common import mask_from_bytes  # noqa: E402
import comp_scripts as CS  # noqa: E402  (阵容规格/CompPolicy)


class _D:
    __slots__ = ("action",)

    def __init__(self, a: int) -> None:
        self.action = int(a)


class ScriptAdapter:
    """把 comp_scripts.CompPolicy.act(v, mask) 包成 decide(game, seat)。"""

    def __init__(self, spec, seed: int = 0, auto: bool = False) -> None:
        self.pol = CS.CompPolicy(spec, auto=bool(auto), seed=int(seed))
        self.eval_fn = None
        self.stats = {"decisions": 0}
        self.carrier_ids = set()
        self.core_ids = set()
        try:
            if spec is not None:
                self.carrier_ids = set(CS.expand(spec.carrier))
                self.core_ids = set(CS.expand(spec.core))
        except BaseException:  # noqa: BLE001
            pass

    def reset(self) -> None:
        self.stats = {"decisions": 0}

    def decide(self, game, seat: int = 0):
        v = json.loads(game.view(int(seat)))
        mask = mask_from_bytes(game.legal_mask(int(seat)))
        self.stats["decisions"] += 1
        return _D(self.pol.act(v, mask))


class ModelPolicy:
    def __init__(self, checkpoint: str, device: str) -> None:
        from hsbg.az.train.model import load_checkpoint
        from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy
        model, meta = load_checkpoint(checkpoint, device=device)
        self.ev = PPOEvaluator(model, device=device, norm_mean=meta.get("norm_mean"),
                               norm_std=meta.get("norm_std"))
        self.cfg = CollectConfig(games=1, seed=0, opponent="bot", behavior="net",
                                 max_steps=20000)
        self.pol = PPOSelfPlayPolicy(model, device=device, config=self.cfg,
                                     eval_fn=self.ev, seed=0, move_model=False)
        self.eval_fn = None
        self.stats = {"decisions": 0}

    def reset(self) -> None:
        self.pol.reset()
        self.stats = {"decisions": 0}

    def decide(self, game, seat: int = 0):
        self.stats["decisions"] += 1
        return self.pol.decide(game, seat)


def parse_spec(spec: str) -> List[Tuple[int, int, str]]:
    out = []
    for part in str(spec).split(","):
        if not part.strip():
            continue
        rng, who = part.split(":")
        lo, hi = rng.replace("t", "").split("-")
        out.append((int(lo), int(hi), who.strip()))
    return out or [(0, 99, "script")]


class HandoverPolicy:
    def __init__(self, model, script, spec: str) -> None:
        self.model = model
        self.script = script
        self.spec = parse_spec(spec)
        self.eval_fn = None
        self.stats = {"decisions": 0, "model_decisions": 0, "script_decisions": 0}

    def reset(self) -> None:
        self.model.reset()
        self.script.reset()
        self.stats = {"decisions": 0, "model_decisions": 0, "script_decisions": 0}

    def _who(self, t: int) -> str:
        for lo, hi, who in self.spec:
            if lo <= int(t) <= hi:
                return who
        return "script"

    def decide(self, game, seat: int = 0):
        t = int(game.turn)
        self.stats["decisions"] += 1
        if self._who(t) == "model":
            self.stats["model_decisions"] += 1
            return self.model.decide(game, seat)
        self.stats["script_decisions"] += 1
        return self.script.decide(game, seat)


def play_one(seed: int, spec, q: dict) -> Optional[dict]:
    from quality_monitor import _play
    auto = bool(q.get("auto"))
    script = ScriptAdapter(spec, seed=int(seed), auto=auto)
    arm = q["arm"]
    if arm == "all_model":
        model = ModelPolicy(q["model_checkpoint"], q["device"])
        pol = HandoverPolicy(model, script, "t0-15:model")
    elif arm == "all_script":
        pol = script
    elif arm == "script_then_model":
        pol = HandoverPolicy(ModelPolicy(q["model_checkpoint"], q["device"]), script,
                             "t0-7:script,t8-15:model")
    else:  # model_then_script
        pol = HandoverPolicy(ModelPolicy(q["model_checkpoint"], q["device"]), script,
                             "t0-7:model,t8-15:script")
    _qq = {k: v for k, v in q.items()
           if k not in ("arm", "model_checkpoint", "device", "auto")}
    _qq["bias_carrier_ids"] = sorted(script.carrier_ids)
    _qq["carrier_ids"] = sorted(script.carrier_ids)
    r = _play(int(seed), pol, _qq)
    if r is None:
        return None
    turns = r.get("turns") or []
    strength = {int(x["turn"]): int(x.get("strength") or 0) for x in turns}
    t12, t15 = strength.get(12), strength.get(15)
    if t15 is None and strength:
        t15 = max(strength.values())
    return {"seed": int(seed), "arm": arm, "placement": int(r.get("placement") or 8),
            "t12": t12, "t15": t15,
            "r12_15": (float(t15) / float(t12)) if (t12 and t15) else None,
            "carrier_buff": r.get("carrier_buff"),
            "total_buff": r.get("total_buff"),
            "carrier_buff_share": r.get("carrier_buff_share"),
            "casts_on_carrier": r.get("casts_on_carrier"),
            "stats": dict(getattr(pol, "stats", {})),
            "script_stats": dict(getattr(script.pol, "stats", {})),
            "turns": turns}


def _pct(xs, p):
    xs = sorted(float(x) for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))], 1)


def summarize(rows: List[dict], tag: str) -> dict:
    ok = [r for r in rows if r and "error" not in r]
    t15 = [r["t15"] for r in ok]
    share = [r["carrier_buff_share"] for r in ok if r.get("carrier_buff_share") is not None]
    return {"tag": tag, "games": len(ok), "errors": len(rows) - len(ok),
            "t15_p50": _pct(t15, 0.5), "t15_p90": _pct(t15, 0.9),
            "t15_max": (max(t15) if t15 else None),
            "r12_15_p50": _pct([r["r12_15"] for r in ok], 0.5),
            "carrier_buff_share_mean": (round(float(np.mean(share)), 3) if share else None),
            "carrier_buff_share_p50": _pct(share, 0.5),
            "casts_on_carrier_mean": round(float(np.mean(
                [float(r.get("casts_on_carrier") or 0) for r in ok])), 3) if ok else None,
            "model_decisions": round(float(np.mean(
                [float((r.get("stats") or {}).get("model_decisions") or 0) for r in ok])), 1) if ok else None,
            "script_decisions": round(float(np.mean(
                [float((r.get("stats") or {}).get("script_decisions") or 0) for r in ok])), 1) if ok else None,
            "mean_rank": round(float(np.mean([r["placement"] for r in ok])), 3) if ok else None,
            "win_rate": round(float(np.mean([r["placement"] == 1 for r in ok])), 3) if ok else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True,
                    choices=["all_model", "all_script", "script_then_model", "model_then_script"])
    ap.add_argument("--comp", default="A")
    ap.add_argument("--games", type=int, default=96)
    ap.add_argument("--seed0", type=int, default=520000)
    ap.add_argument("--mode", default="p09", choices=["bot", "p09"])
    ap.add_argument("--model-checkpoint", default=os.path.join(ROOT, "runs/az_entity_s27d/model.pt"))
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--human-boards", default=os.path.join(
        ROOT, "data/real_library/library_real_quasi_full.jsonl"))
    ap.add_argument("--human-seats", type=int, default=5)
    ap.add_argument("--human-p", type=float, default=0.9)
    ap.add_argument("--human-fidelity", default="full")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "runs/comp_scripts"))
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    from hsbg.az.train.human_board_pool import load_pool
    hpool = None
    if args.mode == "p09":
        hpool = load_pool(args.human_boards, sample="auto")
    spec = CS.COMPS.get(str(args.comp).strip())
    q = {"arm": args.arm, "model_checkpoint": args.model_checkpoint, "device": args.device,
         "max_steps": 20000, "human_board_pool": hpool,
         "human_board_p": (args.human_p if args.mode == "p09" else 0.0),
         "human_board_seats": args.human_seats,
         "human_board_fidelity": args.human_fidelity}
    t0 = time.time()
    rows = []
    for i in range(int(args.games)):
        try:
            r = play_one(args.seed0 + i, spec, q)
        except BaseException as exc:  # noqa: BLE001
            r = {"seed": args.seed0 + i, "error": repr(exc)}
        rows.append(r)
    dt = time.time() - t0
    tag = f"{args.arm}_{args.mode}"
    out = os.path.join(args.out_dir, f"handover_{tag}.jsonl.gz")
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summ = summarize(rows, tag)
    summ.update({"comp": args.comp, "mode": args.mode, "seconds": round(dt, 1),
                 "games_per_min": round(len(rows) / max(1e-9, dt) * 60.0, 1)})
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    with open(os.path.join(args.out_dir, "handover_summary.json"), "a", encoding="utf-8") as f:
        f.write(json.dumps(summ, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())