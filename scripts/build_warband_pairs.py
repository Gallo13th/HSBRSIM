"""Generate warband pairs and pairwise combat labels for value-network training.

Idea (user's direction): no full-game simulation needed.  Enumerate/sample
minion compositions + orderings, simulate pairwise combats, and train a
warband embedding / value network on the pairwise win rates.

Outputs a single .npz with padded warband features and pair labels, plus a
JSON meta (card vocab / keyword vocab / args).
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def keyword_vocab(pool) -> List[str]:
    kws = set()
    for d in pool:
        for k in (d.keywords or ()):
            kws.add(str(k))
    # combat-relevant / common first, then alphabetic for determinism
    priority = [
        "taunt", "divine_shield", "poisonous", "windfury", "reborn",
        "deathrattle", "battlecry", "magnetic", "cleave", "avenge",
        "spellburst", "rally", "blood_gem", "frenzy", "start_of_combat",
    ]
    out = [k for k in priority if k in kws]
    out += sorted(k for k in kws if k not in out)
    return out


def make_spec(rng: random.Random, pool, max_tier: int) -> List[Dict[str, Any]]:
    n = rng.randint(1, 7)
    cand = [d for d in pool if int(d.tech_level or 1) <= max_tier]
    if not cand:
        cand = list(pool)
    specs = []
    for _ in range(n):
        d = rng.choice(cand)
        # buffs roughly scale with turn; keeps stats/feature coverage
        buff = rng.randint(0, max(0, max_tier * 3))
        atk = max(0, int(d.atk or 0) + rng.randint(0, buff))
        hp = max(1, int(d.health or 1) + rng.randint(0, buff))
        kws = [str(k) for k in (d.keywords or ())]
        # occasionally add combat keywords to cover real late-game states
        for extra in ("taunt", "divine_shield", "poisonous", "windfury", "reborn"):
            if rng.random() < 0.04:
                kws.append(extra)
        specs.append({
            "card": d.id,
            "atk": atk,
            "hp": hp,
            "tier": int(d.tech_level or 1),
            "keywords": kws,
            "golden": False,
        })
    return specs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warbands", type=int, default=5000)
    ap.add_argument("--opponents", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="runs/warband_value/pairs_pilot.npz")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    from hsrl2.db import CardDB
    from hsbg.planning.live_warband import build_warband, simulate_combat_warbands

    t0 = time.time()
    db = CardDB.load(args.data_dir)
    pool = db.pool_minions()
    pool = [d for d in pool if int(d.tech_level or 0) >= 1]
    kw = keyword_vocab(pool)
    kw_index = {k: i for i, k in enumerate(kw)}
    card_ids = sorted({d.id for d in pool})
    card_index = {c: i for i, c in enumerate(card_ids)}
    rng = random.Random(args.seed)

    specs: List[List[Dict[str, Any]]] = []
    for _ in range(args.warbands):
        turn = rng.randint(1, args.max_turns)
        max_tier = min(6, 1 + (turn - 1) // 2)
        specs.append(make_spec(rng, pool, max_tier))

    # pre-build warbands once
    builds = []
    built_specs = []
    for s in specs:
        try:
            b = build_warband({"board": s}, "board", db=db)
            builds.append(b)
            built_specs.append(s)
        except Exception:
            builds.append(None)
            built_specs.append(None)
    n = len(builds)
    max_len = 7
    kw_dim = len(kw)
    cards = np.zeros((n, max_len), dtype=np.int16)
    atk = np.zeros((n, max_len), dtype=np.float32)
    hp = np.zeros((n, max_len), dtype=np.float32)
    tier = np.zeros((n, max_len), dtype=np.float32)
    kwf = np.zeros((n, max_len, kw_dim), dtype=np.uint8)
    lengths = np.zeros((n,), dtype=np.int8)
    for i, s in enumerate(built_specs):
        if s is None:
            continue
        lengths[i] = len(s)
        for p, it in enumerate(s[:max_len]):
            cards[i, p] = card_index.get(it["card"], 0)
            atk[i, p] = float(it["atk"])
            hp[i, p] = float(it["hp"])
            tier[i, p] = float(it["tier"])
            for k in it.get("keywords", []):
                j = kw_index.get(k)
                if j is not None:
                    kwf[i, p, j] = 1

    i_idx, j_idx, wins, damages, rounds = [], [], [], [], []
    for i in range(n):
        if builds[i] is None:
            continue
        for _ in range(args.opponents):
            j = rng.randrange(n)
            if j == i or builds[j] is None:
                continue
            w = 0.0
            dmg = 0
            rnd = 0
            ok = 0
            for s in range(args.seeds):
                try:
                    r = simulate_combat_warbands(builds[i], builds[j], seed=args.seed + s, alive_count=8)
                except Exception:
                    continue
                ok += 1
                if r.winner_side == "a":
                    w += 1.0
                elif r.winner_side == "tie":
                    w += 0.5
                if r.winner_side == "a":
                    dmg += int(r.capped_damage or 0)
                rnd += int(r.rounds or 0)
            if ok == 0:
                continue
            i_idx.append(i)
            j_idx.append(j)
            wins.append(w / ok)
            damages.append(dmg / ok)
            rounds.append(rnd / ok)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        cards=cards, atk=atk, hp=hp, tier=tier, kw=kwf, lengths=lengths,
        pair_i=np.asarray(i_idx, dtype=np.int32),
        pair_j=np.asarray(j_idx, dtype=np.int32),
        pair_win=np.asarray(wins, dtype=np.float32),
        pair_damage=np.asarray(damages, dtype=np.float32),
        pair_rounds=np.asarray(rounds, dtype=np.float32),
    )
    meta = {
        "args": vars(args),
        "card_ids": card_ids,
        "keywords": kw,
        "n_warbands": n,
        "n_pairs": len(i_idx),
        "elapsed_s": round(time.time() - t0, 1),
    }
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out} warbands={n} pairs={len(i_idx)} in {meta['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
