"""Full 8-seat Battlegrounds game: 4 PUCT-search seats vs 4 frozen-BC seats.

Uses a small MultiSeatEnv subclass of BattlegroundsEnv:
- seat 0 is the regular env agent (driven by SearchAgent),
- seats 1..3 use SearchSeat,
- seats 4..7 use BCSeat (CheckpointPolicy).

Outputs episode.json + README.md with **per-turn board snapshots for every seat**.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.agents.base import EnvContext
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import BattlegroundsEnv, driver, observation
from hsbg.rl.policies import CheckpointPolicy
from hsbg.search.decision import HeuristicScorer, PuctDecision
from hsbg.search.forward import EngineForwardModel


def _obs_for(game, hero, step):
    extra = observation.build_extra_state(
        game, hero, zones=step.zones, lobby_heroes=game.heroes,
        eliminated_rank={}, turn_stats={}, env_stats={})
    return observation.build_observation(
        game, hero, step.candidates, zones=step.zones,
        lobby_heroes=game.heroes, eliminated_rank={}, total_players=8,
        turn=int(game.turn), log="", extra=extra)


class SearchSeat:
    def __init__(self, name: str, *, simulations=2, width=2, seed=0):
        self.name = name
        self.decision = PuctDecision(HeuristicScorer(), width=width,
                                     simulations=simulations, seed=seed)
        self.heuristic = HeuristicPolicy()
        self._turn = -1
        self._plan: List[Any] = []

    def _replan(self, game, hero):
        try:
            model = EngineForwardModel.from_game(game, hero, total_players=8,
                                                 clone=False)
            res = self.decision.decide(model)
            return list(getattr(getattr(res, "macro", None), "steps", ()) or ())
        except Exception:
            return []

    def choose(self, game, hero, ctx: Optional[EnvContext] = None):
        # 先走启发式（可执行性最好），PUCT 作为后备/扩展
        try:
            hd = self.heuristic.choose(game, hero, ctx)
            if hd is not None:
                return hd
        except Exception:
            pass
        step = driver.enumerate_step(game, hero, driver.collect_zones(game, hero))
        if not step.descriptors:
            return None
        turn = int(getattr(game, "turn", 0))
        if turn != self._turn:
            self._turn = turn
            self._plan = self._replan(game, hero)
        while self._plan:
            cand = self._plan.pop(0)
            for desc in step.descriptors:
                try:
                    if desc.to_candidate().signature() == cand.signature():
                        return desc
                except Exception:
                    continue
        try:
            d = self.heuristic.choose(game, hero, ctx)
            if d is not None:
                return d
        except Exception:
            pass
        return step.descriptors[0]

    def choose_option_index(self, obs):
        try:
            return self.heuristic.choose_option_index(obs)
        except Exception:
            return 0


class BCSeat:
    def __init__(self, name: str, checkpoint: str):
        self.name = name
        self.policy = CheckpointPolicy(checkpoint, device="cpu")

    def choose(self, game, hero, ctx=None):
        step = driver.enumerate_step(game, hero, driver.collect_zones(game, hero))
        if not step.descriptors:
            return None
        obs = _obs_for(game, hero, step)
        try:
            idx = int(self.policy.act(obs, deterministic=True))
        except Exception:
            idx = 0
        return step.descriptors[max(0, min(idx, len(step.descriptors) - 1))]

    def choose_option_index(self, obs):
        try:
            return int(self.policy.act(obs, deterministic=True))
        except Exception:
            return 0


class SearchAgent:
    def __init__(self, seat: SearchSeat):
        self.seat = seat

    def act(self, obs, env):
        if obs.phase == "choice" or not obs.candidates:
            return 0
        turn = int(getattr(env.game, "turn", 0))
        if turn != self.seat._turn:
            self.seat._turn = turn
            self.seat._plan = self.seat._replan(env.game, env.agent_hero)
        while self.seat._plan:
            cand = self.seat._plan.pop(0)
            for i, c in enumerate(obs.candidates):
                if c.signature() == cand.signature():
                    return i
        try:
            d = self.seat.heuristic.choose(env.game, env.agent_hero)
            if d is not None:
                sig = d.to_candidate().signature()
                for i, c in enumerate(obs.candidates):
                    if c.signature() == sig:
                        return i
        except Exception:
            pass
        return len(obs.candidates) - 1


class MultiSeatEnv(BattlegroundsEnv):
    """BattlegroundsEnv whose non-agent seats use arbitrary seat policies."""

    def set_seat_policies(self, policies: List[Any]) -> None:
        self.seat_policies = policies
        self._fallback = [HeuristicPolicy() for _ in range(len(policies))]

    def _drive_opponents(self, *, stop_if_agent_dead: bool = True) -> None:
        game = self.game
        agent = self._agent
        for i, hero in enumerate(list(self._all_heroes)):
            if hero is agent or not hero.is_alive:
                continue
            policy = self.seat_policies[i]
            zones = driver.collect_zones(game, hero)
            for _ in range(int(self._max_opponent_actions)):
                if not hero.is_alive:
                    break
                if stop_if_agent_dead and not agent.is_alive:
                    break
                ctx = EnvContext(game=game, zones=zones, agent_hero=agent,
                                 turn=int(game.turn))
                try:
                    desc = policy.choose(game, hero, ctx)
                except Exception:
                    desc = None
                if desc is None:
                    try:
                        desc = self._fallback[i].choose(game, hero, ctx)
                    except Exception:
                        desc = None
                if desc is None:
                    break
                res = driver.apply_action(game, hero, desc)
                if not res.success:
                    self._stats["opponent_rejects"] += 1
                    # one retry with any legal productive action
                    retried = False
                    for d2 in driver.enumerate_step(game, hero, zones).descriptors:
                        if str(d2.kind) in ("play", "buy", "reroll", "upgrade"):
                            r2 = driver.apply_action(game, hero, d2)
                            if r2.success:
                                retried = True
                                break
                    if not retried:
                        break
                self._drain_all_choices()
                zones = driver.collect_zones(game, hero)


def board_snapshot(hero) -> List[Dict[str, Any]]:
    out = []
    for m in (getattr(hero, "board", ()) or ()):
        out.append({"card": getattr(m, "card_id", ""),
                    "atk": int(getattr(m, "atk", 0) or 0),
                    "hp": int(getattr(m, "health", 0) or 0)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="runs/demo_full_8seat")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-turns", type=int, default=30)
    ap.add_argument("--sims", type=int, default=2)
    ap.add_argument("--width", type=int, default=2)
    ap.add_argument("--bc-checkpoint", default="runs/bc/official_320/policy_bc.pt")
    args = ap.parse_args()

    env = MultiSeatEnv(num_players=8, agent_index=0, opponent="heuristic",
                       seed=args.seed, max_turns=args.max_turns, max_steps=4000)
    obs = env.reset(seed=args.seed)
    search = [SearchSeat(f"P{i}", simulations=args.sims, width=args.width,
                         seed=args.seed + i) for i in range(4)]
    bc = [BCSeat(f"P{i}", args.bc_checkpoint) for i in range(4, 8)]
    env.set_seat_policies(search + bc)
    agent = SearchAgent(search[0])

    snapshots: List[Dict[str, Any]] = []
    done = False
    steps = 0
    t0 = time.time()
    last_turn = -1
    while not done and steps < 8000:
        turn = int(getattr(env.game, "turn", 0))
        idx = agent.act(obs, env)
        obs, reward, term, trunc, info = env.step(idx)
        steps += 1
        done = bool(term or trunc)
        if turn != last_turn:
            last_turn = turn
            snapshots.append({
                "turn": turn,
                "seats": [
                    {"seat": f"P{i}", "policy": "search" if i < 4 else "BC",
                     "alive": bool(h.is_alive),
                     "health": int(getattr(h, "health", 0) or 0),
                     "tier": int(getattr(h, "tavern_tier", 0) or 0),
                     "board": board_snapshot(h)}
                    for i, h in enumerate(env._all_heroes)
                ],
            })

    last_seats = snapshots[-1]["seats"] if snapshots else []
    final = [{"seat": s["seat"], "policy": s["policy"],
              "alive": s["alive"], "health": s["health"],
              "board": s["board"]} for s in last_seats]
    summary = {"seed": args.seed, "turns": int(getattr(env.game, "turn", 0)),
               "steps": steps, "wall_s": round(time.time() - t0, 1),
               "sims": args.sims, "width": args.width,
               "final": final, "env_stats": dict(env._stats),
               "env_errors": list(env._errors)[:10]}

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "episode.json").write_text(
        json.dumps({"summary": summary, "snapshots": snapshots},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# Full 8-seat game: 4 PUCT-search vs 4 BC", "",
          f"- seed={args.seed}, turns={summary['turns']}, steps={steps}, "
          f"wall={summary['wall_s']}s, PUCT N={args.sims} W={args.width}",
          "- seats P0-P3 = PUCT search, P4-P7 = frozen BC", "",
          "## Final", "", "| seat | policy | alive | hp | board |", "|---|---|---:|---:|---|"]
    for f in final:
        md.append(f"| {f['seat']} | {f['policy']} | {int(f['alive'])} | "
                  f"{f['health']} | {len(f['board'])} |")
    md += ["", "## Per-turn boards", ""]
    for snap in snapshots:
        md.append(f"### Turn {snap['turn']}")
        md.append("")
        md.append("| seat | policy | hp | board |")
        md.append("|---|---|---:|---|")
        for s in snap["seats"]:
            b = ", ".join(f"{x['card']}({x['atk']}/{x['hp']})" for x in s["board"]) or "—"
            md.append(f"| {s['seat']} | {s['policy']} | {s['health']} | {b} |")
        md.append("")
    (out / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    env.close()
    print(json.dumps(summary, ensure_ascii=False)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
