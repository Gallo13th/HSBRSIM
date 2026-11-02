#!/usr/bin/env python3
"""T1 基线探针：comp_fit / trinket_match(t6,t9) / fit_max9 与 t15 Σ（不训练）。

用法::

  python scripts/comp_metrics_probe.py --checkpoint runs/az_entity_s27d/model.pt \
      --games 96 --mode p09 --device cuda:4 --out runs/comp_scripts/baseline_p09.jsonl.gz

口径
----
comp_fit(t) = 0.30·core(在手/场) + 0.25·enabler/target + 0.20·种族多样性/type_min
              + 0.25·[tier >= curve(t)]；取 max over 26 套（trinket 项单独算）。
trinket_match 以 **最终阵容** 为准（不是 t6 暂定）；另报 t6 时点判断正确率。
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hsbg.az.train.common import mask_from_bytes  # noqa: E402

A_CHOOSE = 30
N_CHOICE = 16
ECON_TRINKETS = {"BG30_MagicItem_705", "BG36_MagicItem_852", "BG36_MagicItem_300"}
EARLIEST_TIER = {1: 1, 2: 3, 3: 5, 4: 6, 5: 8, 6: 10}
ROLES = json.load(open(os.path.join(ROOT, "runs/comp_scripts/roles.json"),
                       encoding="utf-8"))["comps"]
COMPS = [c for c in ROLES if c.get("implementable")]
_SUPPLY_P = os.path.join(ROOT, "runs/comp_scripts/supply.json")
if os.path.isfile(_SUPPLY_P):
    try:
        _reach = set(int(x) for x in json.load(
            open(_SUPPLY_P, encoding="utf-8")).get("reachable") or [])
        _sel = [c for c in COMPS if int(c.get("idx", -1)) in _reach]
        if _sel:
            COMPS = _sel
    except BaseException:  # noqa: BLE001
        pass
try:
    import comp_scripts as _CS
    _TYPE_MIN = {str(sp.name): int(sp.type_min) for sp in _CS.COMPS.values()}
except BaseException:  # noqa: BLE001
    _TYPE_MIN = {}

_CARDS = None


def cards() -> Dict[str, dict]:
    global _CARDS
    if _CARDS is None:
        d = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
        if isinstance(d, dict):
            d = d.get("cards") or d.get("data") or list(d.values())
        _CARDS = {str(c["id"]): c for c in d if isinstance(c, dict) and c.get("id")}
    return _CARDS


def _norm(cid: str) -> str:
    cid = str(cid or "")
    if cid.endswith("_G") and cid[:-2] in cards():
        return cid[:-2]
    return cid


def _ids(xs: List[Any]) -> set:
    out = set()
    for x in xs or []:
        if isinstance(x, (list, tuple)) and x:
            out.add(_norm(str(x[0])))
        elif isinstance(x, str):
            out.add(_norm(x))
        elif isinstance(x, dict) and x.get("id"):
            out.add(_norm(str(x["id"])))
    return {x for x in out if x}


def _exp_tier(turn: int) -> int:
    exp = 1
    for k, t0 in EARLIEST_TIER.items():
        if int(turn) >= t0:
            exp = max(exp, int(k))
    return exp


def _races_of(item: dict) -> set:
    r = item.get("races") or []
    if isinstance(r, list) and r:
        return {str(x) for x in r}
    c = cards().get(_norm(str(item.get("id") or ""))) or {}
    rr = c.get("races") or []
    return {str(x) for x in rr} if isinstance(rr, list) else set()


def fit_components(me: dict, comp: dict, turn: int) -> Dict[str, float]:
    board = list(me.get("board") or [])
    hand = list(me.get("hand") or [])
    core = _ids(comp.get("core"))
    enab = _ids(comp.get("enabler"))
    n_core = sum(1 for x in board + hand if _norm(str(x.get("id") or "")) in core)
    n_enab = sum(1 for x in board + hand if _norm(str(x.get("id") or "")) in enab)
    races = set()
    for x in board:
        races |= _races_of(x)
    type_min = max(1, int(_TYPE_MIN.get(str(comp.get("name")), 4)))
    tier = int(me.get("tier") or 0)
    c = {}
    c["core"] = 0.30 * min(1.0, n_core)
    c["enabler"] = 0.25 * min(1.0, n_enab / 2.0)
    c["races"] = 0.20 * min(1.0, len(races) / float(type_min))
    c["tier"] = 0.25 * (1.0 if tier >= _exp_tier(turn) else 0.0)
    c["fit"] = sum(c.values())
    return c


def best_comp(me: dict, turn: int):
    best, best_fit = None, -1.0
    for comp in COMPS:
        f = fit_components(me, comp, turn)
        if f["fit"] > best_fit:
            best, best_fit = comp, f["fit"]
    return best, best_fit


class MetricsPolicy:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.eval_fn = None
        self.reset()

    def reset(self) -> None:
        self.inner.reset()
        self.fit: Dict[int, float] = {}
        self.turn_comp: Dict[int, str] = {}
        self.trinkets: List[dict] = []
        self.last_me: dict = {}

    def decide(self, game, seat: int = 0):
        v = json.loads(game.view(int(seat)))
        me = v.get("me") or {}
        t = int(v.get("turn") or 0)
        self.last_me = me
        if t not in self.fit:
            comp, f = best_comp(me, t)
            self.fit[t] = float(f)
            self.turn_comp[t] = str(comp.get("name")) if comp else ""
        pend = me.get("pending")
        ents = pend if isinstance(pend, list) else ([pend] if pend else [])
        tr = None
        for e in ents:
            if isinstance(e, dict) and str(e.get("kind")) == "trinket":
                tr = e
                break
        d = self.inner.decide(game, seat)
        a = int(d.action)
        if tr is not None and A_CHOOSE <= a < A_CHOOSE + N_CHOICE:
            opts = tr.get("options") or []
            i = a - A_CHOOSE
            if 0 <= i < len(opts):
                o = opts[i]
                _cid = str(o.get("id") if isinstance(o, dict) else o)
                _comp, _ = best_comp(me, t)
                _core = _ids(_comp.get("core")) if _comp else set()
                _board = list(me.get("board") or [])
                _hand = list(me.get("hand") or [])
                _core_seen = any(_norm(str(x.get("id") or "")) in _core
                                 for x in _board + _hand)
                _key = _ids(_comp.get("trinkets") if _comp else [])
                _offered = any((str((x or {}).get("id")) if isinstance(x, dict) else str(x))
                               in _key for x in opts)
                self.trinkets.append({"turn": t, "chosen": _cid,
                                      "core_seen": bool(_core_seen),
                                      "offered": bool(_offered),
                                      "econ": _cid in ECON_TRINKETS,
                                      "options": [str((x or {}).get("id")) if isinstance(x, dict) else str(x)
                                                  for x in opts]})
        return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default=os.path.join(ROOT, "runs/az_entity_s27d/model.pt"))
    ap.add_argument("--games", type=int, default=96)
    ap.add_argument("--seed0", type=int, default=520000)
    ap.add_argument("--mode", default="p09", choices=["bot", "p09"])
    ap.add_argument("--device", default="cuda:4")
    ap.add_argument("--human-boards", default=os.path.join(
        ROOT, "data/real_library/library_real_quasi_full.jsonl"))
    ap.add_argument("--human-seats", type=int, default=5)
    ap.add_argument("--human-p", type=float, default=0.9)
    ap.add_argument("--human-fidelity", default="full")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy
    from hsbg.az.train.human_board_pool import load_pool
    from quality_monitor import _play
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device, norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(args.seed0), opponent="bot", behavior="net",
                        max_steps=20000)
    net = PPOSelfPlayPolicy(model, device=args.device, config=cfg,
                            eval_fn=ev, seed=int(args.seed0), move_model=False)
    hpool = load_pool(args.human_boards, sample="auto") if args.mode == "p09" else None
    q = {"max_steps": 20000, "human_board_pool": hpool,
         "human_board_p": (args.human_p if args.mode == "p09" else 0.0),
         "human_board_seats": args.human_seats,
         "human_board_fidelity": args.human_fidelity}
    rows = []
    t0 = time.time()
    for i in range(int(args.games)):
        pol = MetricsPolicy(net)
        r = _play(int(args.seed0) + i, pol, q)
        if r is None:
            continue
        turns = r.get("turns") or []
        st = {int(x["turn"]): int(x.get("strength") or 0) for x in turns}
        tier_at = {int(x["turn"]): int(x.get("tier") or 0) for x in turns}
        t15 = int(st.get(15) or (max(st.values()) if st else 0))
        # 最终阵容 = 终局盘面 best comp
        final_me = pol.last_me
        fcomp, ffit = best_comp(final_me, int(max(st.keys()) if st else 9))
        trs = []
        for tr in pol.trinkets:
            chosen = _norm(tr["chosen"])
            key = _ids(fcomp.get("trinkets") if fcomp else [])
            trs.append(dict(tr, matched=(chosen in key), final_comp=fcomp.get("name") if fcomp else None))
        t6 = next((x for x in trs if x["turn"] == 6), None)
        t9 = next((x for x in trs if x["turn"] == 9), None)
        rows.append({"seed": int(args.seed0) + i, "mode": args.mode, "t15": t15,
                     "fit": {str(k): round(v, 4) for k, v in pol.fit.items()},
                     "fit_max9": round(float(pol.fit.get(9, max(pol.fit.values()) if pol.fit else 0.0)), 4),
                     "comp_t9": pol.turn_comp.get(9),
                     "final_comp": fcomp.get("name") if fcomp else None,
                     "final_fit": round(float(ffit), 4),
                     "trinkets": trs,
                     "t6_match": bool(t6["matched"]) if t6 else None,
                     "t9_match": bool(t9["matched"]) if t9 else None,
                     "t6_comp_correct": (pol.turn_comp.get(6) == (fcomp.get("name") if fcomp else None)),
                     "placement": int(r.get("placement") or 8)})
        if i % 20 == 0:
            print(f"[probe] {i}/{args.games} t={time.time()-t0:.0f}s", flush=True)
    out = args.out or os.path.join(ROOT, "runs/comp_scripts", f"baseline_{args.mode}.jsonl.gz")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    # 汇总
    def pct(xs, p):
        xs = sorted(float(x) for x in xs if x is not None)
        return round(xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))], 3) if xs else None
    f9 = [r["fit_max9"] for r in rows]
    t6m = [r["t6_match"] for r in rows if r["t6_match"] is not None]
    t9m = [r["t9_match"] for r in rows if r["t9_match"] is not None]
    t6c = [r["t6_comp_correct"] for r in rows]
    match_any = [r for r in rows if any(t["matched"] for t in r["trinkets"])]
    no_match = [r for r in rows if not any(t["matched"] for t in r["trinkets"])]
    summ = {"mode": args.mode, "games": len(rows),
            "fit_max9_p50": pct(f9, 0.5), "fit_max9_mean": round(float(np.mean(f9)), 3) if f9 else None,
            "comp_t9_top": (max({r["comp_t9"] for r in rows if r["comp_t9"]},
                                key=lambda k: sum(1 for r in rows if r["comp_t9"] == k))
                            if any(r["comp_t9"] for r in rows) else None),
            "trinket_t6_match_rate": round(float(np.mean(t6m)), 3) if t6m else None,
            "trinket_t9_match_rate": round(float(np.mean(t9m)), 3) if t9m else None,
            "trinket_t6_n": len(t6m), "trinket_t9_n": len(t9m),
            "t6_comp_correct_rate": round(float(np.mean(t6c)), 3) if t6c else None,
            "trinket_core_seen_match_rate": (
                round(float(np.mean([t["matched"] for r in rows for t in r["trinkets"]
                                     if t.get("core_seen")])), 3)
                if any(t.get("core_seen") for r in rows for t in r["trinkets"]) else None),
            "trinket_core_seen_n": int(sum(1 for r in rows for t in r["trinkets"] if t.get("core_seen"))),
            "trinket_uncommitted_econ_rate": (
                round(float(np.mean([t["econ"] for r in rows for t in r["trinkets"]
                                     if not t.get("core_seen")])), 3)
                if any(not t.get("core_seen") for r in rows for t in r["trinkets"]) else None),
            "trinket_uncommitted_n": int(sum(1 for r in rows for t in r["trinkets"]
                                            if not t.get("core_seen"))),
            "trinket_conditional_match_rate": (
                round(float(np.mean([t["matched"] for r in rows for t in r["trinkets"]
                                     if t.get("offered")])), 3)
                if any(t.get("offered") for r in rows for t in r["trinkets"]) else None),
            "trinket_offered_n": int(sum(1 for r in rows for t in r["trinkets"]
                                         if t.get("offered"))),
            "t15_with_match_p50": pct([r["t15"] for r in match_any], 0.5),
            "t15_without_match_p50": pct([r["t15"] for r in no_match], 0.5),
            "t15_with_match_n": len(match_any), "t15_without_match_n": len(no_match),
            "seconds": round(time.time() - t0, 1)}
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    with open(os.path.join(ROOT, "runs/comp_scripts", f"baseline_{args.mode}_summary.json"),
              "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())