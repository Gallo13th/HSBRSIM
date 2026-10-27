#!/usr/bin/env python3
"""Run one search+BotPrior demo game and write a WebUI replay JSON.

This is a presentation/replay runner, not a training entrypoint. The agent is
``AZSearchPolicy`` with ``BotPriorEvaluator`` (privileged prior, diagnostic only).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from hsbg.az.policy import BotPriorEvaluator
from hsbg.az.train.policies import AZSearchPolicy
import hsbg_engine as E


def _view(g: Any, seat: int = 0) -> Dict[str, Any]:
    v = json.loads(g.view(seat))
    me = v.get("me") or {}
    opponents = []
    for o in v.get("opponents") or []:
        opponents.append({
            "seat": o.get("seat"),
            "hero": (o.get("hero") or {}).get("name") or (o.get("hero") or {}).get("id"),
            "alive": o.get("alive"),
            "health": o.get("health"),
            "armor": o.get("armor"),
            "tier": o.get("tier"),
            "board_size": len(o.get("board") or []),
            "last_warband": o.get("last_warband"),
        })
    return {
        "turn": int(v.get("turn") or 0),
        "phase": v.get("phase"),
        "me": {
            "hero": (me.get("hero") or {}).get("name") or (me.get("hero") or {}).get("id"),
            "health": me.get("health"),
            "armor": me.get("armor"),
            "gold": me.get("gold"),
            "tier": me.get("tier"),
            "board": [
                {"name": m.get("name"), "atk": m.get("atk"), "hp": m.get("hp"),
                 "tier": m.get("tier")}
                for m in (me.get("board") or [])
            ],
            "hand": [
                {"name": m.get("name"), "atk": m.get("atk"), "hp": m.get("hp")}
                for m in (me.get("hand") or [])
            ],
            "shop": [
                {"name": m.get("name"), "atk": m.get("atk"), "hp": m.get("hp"),
                 "cost": m.get("cost")}
                for m in (me.get("shop") or [])
            ],
        },
        "opponents": opponents,
        "combats": v.get("combats") or [],
    }


def run(seed: int, simulations: int, determinizations: int) -> Dict[str, Any]:
    t0 = time.time()
    g = E.Game(int(seed))
    policy = AZSearchPolicy(
        simulations=int(simulations),
        determinizations=int(determinizations),
        engine_backend="python",
        evaluator=BotPriorEvaluator(blend=0.75),
        temperature=0.0,
        seed=int(seed),
    )
    trace: List[Dict[str, Any]] = []
    steps = 0
    limit = 4000
    while not g.is_over() and steps < limit:
        steps += 1
        if g.needs_action(0):
            state = _view(g, 0)
            d = policy.decide(g, 0)
            action = int(d.action)
            rec = {
                "index": len(trace),
                "turn": state["turn"],
                "phase": state["phase"],
                "action": action,
                "action_name": str(E.action_name(action)),
                "value": float((getattr(d, "info", {}) or {}).get("root_value", 0.0) or 0.0),
                "visits": int((getattr(d, "info", {}) or {}).get("visits", 0) or 0),
                "state": state,
            }
            g.step(0, action)
            rec["after"] = _view(g, 0)
            trace.append(rec)
            continue
        acted = False
        for p in range(1, g.num_players):
            if g.needs_action(p):
                g.bot_play(p)
                acted = True
        if not acted:
            break
    places = list(g.placements())
    return {
        "schema": "hsbg.az.webui_match/v1",
        "seed": int(seed),
        "config": {
            "agent": "search_az+bot_prior",
            "simulations": int(simulations),
            "determinizations": int(determinizations),
            "temperature": 0.0,
            "opponents": "engine_bot",
            "privileged_prior": True,
            "az_training_input_ok": False,
        },
        "result": {
            "rank": int(places[0]) if places else 0,
            "placements": places,
            "turns": int(g.turn),
            "decisions": len(trace),
            "steps": steps,
            "seconds": round(time.time() - t0, 3),
        },
        "trace": trace,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=90000)
    ap.add_argument("--simulations", type=int, default=32)
    ap.add_argument("--determinizations", type=int, default=2)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data = run(args.seed, args.simulations, args.determinizations)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: data[k] for k in ("seed", "config", "result")}, ensure_ascii=False))
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
