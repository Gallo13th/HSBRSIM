"""Warband showcase: 4 PUCT/search-composed warbands vs 4 BC-composed warbands.

The full 8-seat BG env is single-agent (one controlled seat + scripted opponents),
so this showcase compares the two policy families at the **warband level**:
- 4 BC seats: frozen BC checkpoint plays a short recruit phase; take its board.
- 4 search seats: PUCT search over candidate warbands scored by the trained
  warband value network.
- Then run an 8-player warband bracket with the engine combat simulator.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import torch

from hsbg.env import BattlegroundsEnv
from hsrl2.db import CardDB
from hsbg.planning.live_warband import build_warband, simulate_combat_warbands
from hsbg.value.warband_model import WarbandEncoder


def _spec_from_minion(m) -> Dict[str, Any]:
    return {"card": getattr(m, "card_id", ""), "atk": int(getattr(m, "atk", 0)),
            "hp": int(getattr(m, "health", 1)),
            "keywords": sorted(getattr(m, "keywords", ()) or ()),
            "tier": int(getattr(m, "tech_level", 1) or 1), "golden": False}


def bc_warband(seed: int, turns: int = 6, checkpoint="runs/bc/official_320/policy_bc.pt"):
    from hsbg.rl.policies import CheckpointPolicy
    policy = CheckpointPolicy(checkpoint, device="cpu")
    env = BattlegroundsEnv(num_players=8, agent_index=0, opponent="heuristic",
                           seed=seed, max_turns=max(8, turns), max_steps=3000)
    obs = env.reset(seed=seed)
    try:
        while int(env.game.turn) <= turns and obs.candidates:
            idx = policy.act(obs, deterministic=True)
            obs, _, done, trunc, _ = env.step(int(idx))
            if done or trunc:
                break
        hero = env.agent_hero
        return [_spec_from_minion(m) for m in (hero.board or ())][:7]
    finally:
        env.close()


def random_specs(rng: random.Random, pool, turn: int, n: int) -> List[List[Dict[str, Any]]]:
    out = []
    max_tier = min(6, 1 + (turn - 1) // 2)
    cand = [d for d in pool if int(d.tech_level or 1) <= max_tier]
    for _ in range(n):
        size = rng.randint(4, 7)
        specs = []
        for _ in range(size):
            d = rng.choice(cand)
            b = rng.randint(0, 8)
            specs.append({
                "card": d.id, "atk": int(d.atk or 0) + rng.randint(0, b),
                "hp": int(d.health or 1) + rng.randint(0, b),
                "keywords": sorted(str(k) for k in (d.keywords or ())),
                "tier": int(d.tech_level or 1), "golden": False,
            })
        out.append(specs)
    return out


def encode(specs: List[Dict[str, Any]], meta, max_len=7):
    ci = {c: i for i, c in enumerate(meta["card_ids"])}
    kw = {k: i for i, k in enumerate(meta["keywords"])}
    cards = np.zeros(max_len, np.int64); atk = np.zeros(max_len, np.float32)
    hp = np.zeros(max_len, np.float32); tier = np.zeros(max_len, np.float32)
    kws = np.zeros((max_len, len(kw)), np.float32)
    for i, s in enumerate(specs[:max_len]):
        cards[i] = ci.get(s["card"], 0); atk[i] = s["atk"]; hp[i] = s["hp"]
        tier[i] = s["tier"]
        for k in s["keywords"]:
            j = kw.get(k)
            if j is not None:
                kws[i, j] = 1
    return (torch.from_numpy(cards).long(), torch.from_numpy(atk),
            torch.from_numpy(hp), torch.from_numpy(tier),
            torch.from_numpy(kws).unsqueeze(0),
            torch.tensor([len(specs[:max_len])]))


@torch.no_grad()
def score_specs(model, meta, specs, device):
    cards, atk, hp, tier, kws, ln = encode(specs, meta)
    cards = cards[None].to(device); atk = atk[None].to(device); hp = hp[None].to(device)
    tier = tier[None].to(device); kws = kws.to(device); ln = ln.to(device)
    s, z = model(cards, atk, hp, tier, kws, ln)
    return float(s.item()), z[0]


def puct_select(model, meta, candidates, device, n_sims=32, seed=0):
    rng = random.Random(seed)
    scores = []
    for c in candidates:
        s, _ = score_specs(model, meta, c, device)
        scores.append(s)
    scores = np.asarray(scores)
    visits = np.zeros(len(candidates)); q = np.zeros(len(candidates))
    for t in range(n_sims):
        ucb = q + 2.0 * np.sqrt(np.log(t + 1) / (visits + 1))
        ucb[visits == 0] = 1e9
        i = int(np.argmax(ucb))
        visits[i] += 1
        q[i] = scores[i]
    order = np.argsort(-q)
    return [candidates[i] for i in order[:4]], [float(scores[i]) for i in order[:4]]


def fight(a_spec, b_spec, db, seed=0):
    a = build_warband({"board": a_spec}, "board", db=db)
    b = build_warband({"board": b_spec}, "board", db=db)
    wins = 0
    for k in range(3):
        r = simulate_combat_warbands(a, b, seed=seed + k, alive_count=8, damage_cap=15)
        wins += 1 if r.winner_side == "a" else 0
    return wins >= 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="runs/demo_warband_4search_vs_4bc")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--candidates", type=int, default=256)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--value-checkpoint", default="runs/warband_value/model_60k/checkpoint.pt")
    ap.add_argument("--bc-checkpoint", default="runs/bc/official_320/policy_bc.pt")
    args = ap.parse_args()

    db = CardDB.load("data")
    pool = db.pool_minions()
    ck = torch.load(args.value_checkpoint, map_location=args.device)
    meta = json.loads(Path("runs/warband_value/pairs_20k.json").read_text(encoding="utf-8"))
    model = WarbandEncoder(len(meta["card_ids"]), len(meta["keywords"]),
                           dim=ck["args"]["dim"], layers=ck["args"]["layers"]).to(args.device)
    model.load_state_dict(ck["model"]); model.eval()

    rng = random.Random(args.seed)
    bc_boards = [bc_warband(args.seed + i, checkpoint=args.bc_checkpoint) for i in range(4)]
    candidates = random_specs(rng, pool, 8, args.candidates)
    search_boards, search_scores = puct_select(model, meta, candidates, args.device,
                                               n_sims=32, seed=args.seed)

    seats = [("P0", "search", b) for b in search_boards] + \
            [("P4", "BC", b) for b in bc_boards]
    seats[0] = ("P0", "search", search_boards[0])
    # bracket: 4 search vs 4 BC, then final
    rounds = []
    winners: List[Tuple[str, List[Dict[str, Any]]]] = []
    for i in range(4):
        a = search_boards[i]; b = bc_boards[i]
        aw = fight(a, b, db, seed=args.seed * 100 + i)
        rounds.append({"round": "quarter", "a": f"search-{i}", "b": f"BC-{i}",
                       "winner": f"search-{i}" if aw else f"BC-{i}"})
        winners.append((f"search-{i}", a) if aw else (f"BC-{i}", b))
    semis = []
    finalists: List[Tuple[str, List[Dict[str, Any]]]] = []
    for i in range(0, 4, 2):
        (ka, a), (kb, b) = winners[i], winners[i + 1]
        aw = fight(a, b, db, seed=args.seed * 200 + i)
        label = f"{ka}" if aw else f"{kb}"
        semis.append({"round": "semi", "a": ka, "b": kb, "winner": label})
        finalists.append((label, a if aw else b))
    fa, fb = finalists[0], finalists[1]
    fw = fight(fa[1], fb[1], db, seed=args.seed * 300)
    result = {"seed": args.seed, "candidates": args.candidates,
              "bc": [{"seat": f"P{4+i}", "policy": "BC", "board": b} for i, b in enumerate(bc_boards)],
              "search": [{"seat": f"P{i}", "policy": "PUCT-search", "board": b,
                          "score": s} for i, (b, s) in enumerate(zip(search_boards, search_scores))],
              "quarter": rounds, "semi": semis,
              "final": {"a": fa[0], "b": fb[0],
                        "winner": fa[0] if fw else fb[0]}}
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "showcase.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    md = ["# 4 PUCT-search vs 4 BC — warband showcase", "",
          f"- seed={args.seed}；search candidates={args.candidates}；N=32 PUCT",
          "", "## Quarter finals", "", "| match | winner |", "|---|---|"]
    for r in rounds:
        md.append(f"| {r['a']} vs {r['b']} | {r['winner']} |")
    md += ["", "## Semis", "", "| match | winner |", "|---|---|"]
    for r in semis:
        md.append(f"| {r['a']} vs {r['b']} | {r['winner']} |")
    md += ["", "## Final", "", f"**{result['final']['winner']}** wins the showcase."]
    (out / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "final": result["final"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
