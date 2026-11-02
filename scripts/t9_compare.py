#!/usr/bin/env python3
"""t9 对照：真实玩家（library_real_quasi_full）vs 我们（s27d@5M, 5 席 p0.9, 96 局）。

真实侧：board_detail 逐随从 card_id/atk/hp；我们侧：quality_monitor._play 的 turns。
指标：t9 tier/gold/Σ/随从数/种族多样性/有 core/有 enabler；death_turn 分布。
"""
from __future__ import annotations
import argparse, json, os, sys
from typing import Any, Dict, List
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

def _pct(xs, p):
    xs = sorted(float(x) for x in xs if x is not None)
    return round(xs[min(len(xs)-1, max(0, int(round(p*(len(xs)-1)))))], 1) if xs else None

def _cards():
    d = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("cards") or d.get("data") or list(d.values())
    return {str(c["id"]): c for c in d if isinstance(c, dict) and c.get("id")}

def _roles():
    roles = json.load(open(os.path.join(ROOT, "runs/comp_scripts/roles.json"),
                           encoding="utf-8"))["comps"]
    core, en = set(), set()
    for c in roles:
        for x in c.get("core") or []:
            core.add(str(x[0]))
        for x in c.get("enabler") or []:
            en.add(str(x[0]))
    return core, en

def _norm(cid: str) -> str:
    cid = str(cid or "")
    return cid[:-2] if cid.endswith("_G") and cid[:-2] else cid

def real_stats(path: str) -> Dict[str, Any]:
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    core, en = _roles(); cards = _cards()
    core_low = {c for c in core if int((cards.get(c) or {}).get("tier") or 0) <= 4}
    core_high = {c for c in core if int((cards.get(c) or {}).get("tier") or 0) >= 5}
    t9 = [r for r in rows if int(r.get("turn") or 0) == 9]
    tiers, sigs, cnts, races_n, core_hit, en_hit = [], [], [], [], 0, 0
    core_high_hit = core_low_hit = 0
    for r in t9:
        bd = r.get("board_detail") or []
        ids = {_norm(x.get("card_id") or "") for x in bd}
        tiers.append(int(r.get("tier") or 0))
        sigs.append(int(r.get("strength") or 0))
        cnts.append(len(bd))
        rr = set()
        for x in bd:
            c = cards.get(_norm(x.get("card_id") or "")) or {}
            for t in (c.get("races") or []):
                rr.add(str(t))
        races_n.append(len(rr))
        if ids & core: core_hit += 1
        if ids & core_high: core_high_hit += 1
        if ids & core_low: core_low_hit += 1
        if ids & en: en_hit += 1
    games = {}
    for r in rows:
        g = str(r.get("game_id")); games[g] = max(games.get(g, 0), int(r.get("turn") or 0))
    maxt = list(games.values())
    return {"n_t9": len(t9), "games": len(games),
            "tier_p50": _pct(tiers, .5), "tier_dist": {str(k): tiers.count(k) for k in sorted(set(tiers))},
            "sigma_p50": _pct(sigs, .5), "sigma_p90": _pct(sigs, .9),
            "count_p50": _pct(cnts, .5), "races_p50": _pct(races_n, .5),
            "core_rate": round(core_hit/max(1, len(t9)), 3),
            "core_t5_plus_rate": round(core_high_hit/max(1, len(t9)), 3),
            "core_t4_minus_rate": round(core_low_hit/max(1, len(t9)), 3),
            "enabler_rate": round(en_hit/max(1, len(t9)), 3),
            "maxturn_p50": _pct(maxt, .5), "maxturn_p90": _pct(maxt, .9)}

class _CountPolicy:
    """包一层统计每局 upgrade(动作3) 次数，不动动作本身。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.upg = 0

    def reset(self) -> None:
        self.inner.reset()
        self.upg = 0

    def decide(self, game, seat: int = 0):
        d = self.inner.decide(game, seat)
        if int(getattr(d, "action", -1)) == 3:
            self.upg += 1
        return d

    def __getattr__(self, name):
        return getattr(self.inner, name)


def ours_stats(args) -> Dict[str, Any]:
    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy
    from hsbg.az.train.human_board_pool import load_pool
    from quality_monitor import _play
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device, norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=int(args.seed0), opponent="bot", behavior="net",
                        max_steps=20000)
    net = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                            seed=int(args.seed0), move_model=False)
    hpool = load_pool(args.human_boards, sample="auto")
    q = {"max_steps": 20000, "human_board_pool": hpool, "human_board_p": 0.9,
         "human_board_seats": 5, "human_board_fidelity": "full"}
    core, en = _roles(); cards = _cards()
    core_low = {c for c in core if int((cards.get(c) or {}).get("tier") or 0) <= 4}
    core_high = {c for c in core if int((cards.get(c) or {}).get("tier") or 0) >= 5}
    import hsbg_engine as _E
    cid2id = {int(c["cid"]): str(c["id"]) for c in json.loads(_E.catalog_json())}
    tiers, golds, sigs, cnts, races_n, core_hit, en_hit = [], [], [], [], [], 0, 0
    core_high_hit = core_low_hit = 0
    deaths = []
    strata = []
    for i in range(int(args.games)):
        pcount = _CountPolicy(net)
        r = _play(int(args.seed0) + i, pcount, q)
        if r is None:
            continue
        _death = int(r.get("death_turn") or 0)
        deaths.append(_death)
        _rows9 = [x for x in (r.get("turns") or []) if int(x.get("turn") or 0) == 9]
        _sig9 = int(_rows9[-1].get("strength") or 0) if _rows9 else None
        strata.append({"upg": int(pcount.upg), "sig9": _sig9, "death": _death})
        row = next((x for x in (r.get("turns") or []) if int(x.get("turn") or 0) == 9), None)
        if row is None:
            continue
        board = [cid2id.get(int(x), "") for x in (row.get("board_end") or row.get("board_start") or [])]
        board = [b for b in board if b]
        ids = {_norm(str(x)) for x in board}
        tiers.append(int(row.get("tier") or 0)); golds.append(int(row.get("gold") or 0))
        sigs.append(int(row.get("strength") or 0)); cnts.append(int(row.get("count") or len(board)))
        rr = set()
        for cid in board:
            c = cards.get(_norm(str(cid))) or {}
            for t in (c.get("races") or []):
                rr.add(str(t))
        races_n.append(len(rr))
        if ids & core: core_hit += 1
        if ids & core_high: core_high_hit += 1
        if ids & core_low: core_low_hit += 1
        if ids & en: en_hit += 1
    n9 = len(tiers)
    return {"n_t9": n9, "games": len(deaths),
            "tier_p50": _pct(tiers, .5), "tier_dist": {str(k): tiers.count(k) for k in sorted(set(tiers))},
            "gold_p50": _pct(golds, .5),
            "sigma_p50": _pct(sigs, .5), "sigma_p90": _pct(sigs, .9),
            "count_p50": _pct(cnts, .5), "races_p50": _pct(races_n, .5),
            "core_rate": round(core_hit/max(1, n9), 3),
            "core_t5_plus_rate": round(core_high_hit/max(1, n9), 3),
            "core_t4_minus_rate": round(core_low_hit/max(1, n9), 3),
            "enabler_rate": round(en_hit/max(1, n9), 3),
            "death_turn_p50": _pct(deaths, .5), "death_turn_p90": _pct(deaths, .9),
            "stratified": {
                "upg_yes": {"n": sum(1 for x in strata if x["upg"] > 0),
                            "sig9_p50": _pct([x["sig9"] for x in strata
                                              if x["upg"] > 0], .5),
                            "death_p50": _pct([x["death"] for x in strata
                                               if x["upg"] > 0], .5)},
                "upg_no": {"n": sum(1 for x in strata if x["upg"] == 0),
                           "sig9_p50": _pct([x["sig9"] for x in strata
                                             if x["upg"] == 0], .5),
                           "death_p50": _pct([x["death"] for x in strata
                                              if x["upg"] == 0], .5)},
                "upg_per_game_mean": round(float(np.mean([x["upg"] for x in strata])), 1)
                if strata else None}}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", default=os.path.join(ROOT, "data/real_library/library_real_quasi_full.jsonl"))
    ap.add_argument("--checkpoint", default=os.path.join(ROOT, "runs/az_entity_s27d/model.pt"))
    ap.add_argument("--games", type=int, default=96)
    ap.add_argument("--seed0", type=int, default=520000)
    ap.add_argument("--device", default="cuda:4")
    ap.add_argument("--human-boards", default=os.path.join(ROOT, "data/real_library/library_real_quasi_full.jsonl"))
    ap.add_argument("--out", default=os.path.join(ROOT, "runs/comp_scripts/t9_compare.json"))
    args = ap.parse_args()
    real = real_stats(args.real)
    ours = ours_stats(args)
    out = {"real": real, "ours_s27d": ours}
    print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0

if __name__ == "__main__":
    sys.exit(main())