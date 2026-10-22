"""Demo: one 8-player lobby, 4 AlphaZero-style PUCT search seats vs 4 BC seats.

Seats P0..P3: PUCT search (engine forward model + heuristic value).
Seats P4..P7: frozen Behavior Cloning checkpoint (`runs/bc/official_320/policy_bc.pt`).

Outputs an episode JSON + a readable Markdown summary for presentation.
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

from hsbg import planning
from hsbg.agents.base import EnvContext, choose_option_index
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import BattlegroundsEnv
from hsbg.env import driver, observation
from hsbg.env.spec import CandidateAction
from hsbg.search.decision import HeuristicScorer, PuctDecision
from hsbg.search.forward import EngineForwardModel


def _valid_desc(game, hero, desc) -> bool:
    """Apply on a clone to filter descriptors that the env would reject."""
    try:
        dup = planning.clone(game)
        idx = game.heroes.index(hero)
        h2 = dup.heroes[idx]
        res = driver.apply_action(dup, h2, desc)
        return bool(getattr(res, "ok", True))
    except Exception:
        return False


def _obs_for(game, hero, step, *, phase="recruit", pending=None):
    zones = step.zones
    extra = observation.build_extra_state(
        game, hero, zones=zones, lobby_heroes=game.heroes,
        eliminated_rank={}, turn_stats={}, env_stats={})
    return observation.build_observation(
        game, hero, step.candidates, phase=phase, pending=pending,
        zones=zones, lobby_heroes=game.heroes, eliminated_rank={},
        total_players=8, turn=int(game.turn), log="", extra=extra)


class SearchSeat:
    """PUCT over macro candidates, executes the first step each choose()."""

    def __init__(self, name: str, *, simulations: int = 2, width: int = 2,
                 seed: int = 0) -> None:
        self.name = name
        self.decision = PuctDecision(
            HeuristicScorer(), width=width, simulations=simulations, seed=seed)
        self.heuristic = HeuristicPolicy()
        self.stats = {"decisions": 0, "elapsed_s": 0.0}
        self._plan_turn = -1
        self._plan: List[Any] = []

    def _replan(self, game, hero) -> List[Any]:
        zones = driver.collect_zones(game, hero)
        step = driver.enumerate_step(game, hero, zones)
        if not step.descriptors:
            return []
        t0 = time.perf_counter()
        try:
            model = EngineForwardModel.from_game(game, hero, total_players=8,
                                                 clone=False)
            res = self.decision.decide(model)
            macro = getattr(res, "macro", None)
            if macro and getattr(macro, "steps", None):
                self.stats["decisions"] += 1
                self.stats["elapsed_s"] += time.perf_counter() - t0
                return list(macro.steps)
        except Exception:
            pass
        return []

    def choose(self, game, hero, ctx: Optional[EnvContext] = None):
        turn = int(getattr(game, "turn", 0))
        if turn != self._plan_turn:
            self._plan_turn = turn
            self._plan = self._replan(game, hero)
        zones = driver.collect_zones(game, hero)
        step = driver.enumerate_step(game, hero, zones)
        if not step.descriptors:
            return None
        # 保底：优先把能买/能上的动作做掉，避免搜索计划只选到 end_turn
        for desc in step.descriptors:
            try:
                if str(desc.kind) in ("play", "buy"):
                    return desc
            except Exception:
                continue
        # consume plan until a matching descriptor is found
        has_productive = any(
            str(getattr(d, "kind", "")) in ("buy", "play", "reroll", "upgrade")
            for d in step.descriptors)
        while self._plan:
            cand = self._plan.pop(0)
            for desc in step.descriptors:
                try:
                    if desc.to_candidate().signature() == cand.signature():
                        if has_productive and str(desc.kind) == "end_turn":
                            self._plan = []
                            break
                        return desc
                except Exception:
                    continue
            if not self._plan:
                break
        try:
            hdesc = self.heuristic.choose(game, hero, ctx)
            if hdesc is not None:
                return hdesc
        except Exception:
            pass
        # last resort: prefer a productive action over end_turn
        for desc in step.descriptors:
            try:
                if str(desc.kind) in ("buy", "play", "reroll", "upgrade"):
                    return desc
            except Exception:
                continue
        return step.descriptors[0]

    def choose_option_index(self, obs: Any) -> int:
        try:
            return choose_option_index(self.heuristic, obs)
        except Exception:
            return 0


class BCSeat:
    """Frozen BC checkpoint wrapped as an opponent policy."""

    def __init__(self, name: str, checkpoint: str) -> None:
        from hsbg.rl.policies import CheckpointPolicy
        self.name = name
        self.policy = CheckpointPolicy(checkpoint, device="cpu")
        self.stats = {"decisions": 0, "elapsed_s": 0.0}

    def choose(self, game, hero, ctx: Optional[EnvContext] = None):
        zones = driver.collect_zones(game, hero)
        step = driver.enumerate_step(game, hero, zones)
        if not step.descriptors:
            return None
        obs = _obs_for(game, hero, step)
        t0 = time.perf_counter()
        try:
            idx = int(self.policy.act(obs, deterministic=True))
        except Exception:
            idx = 0
        self.stats["decisions"] += 1
        self.stats["elapsed_s"] += time.perf_counter() - t0
        idx = max(0, min(idx, len(step.descriptors) - 1))
        return step.descriptors[idx]

    def choose_option_index(self, obs: Any) -> int:
        try:
            return int(self.policy.act(obs, deterministic=True))
        except Exception:
            return 0


class SearchAgent:
    """Seat-0 agent: same PUCT search, but returns an env candidate index."""

    def __init__(self, seat: SearchSeat) -> None:
        self.seat = seat
        self._turn = -1
        self._plan: List[Any] = []

    def _replan(self, env: BattlegroundsEnv) -> List[Any]:
        model = EngineForwardModel.from_env(env, clone=False)
        res = self.seat.decision.decide(model)
        macro = getattr(res, "macro", None)
        return list(getattr(macro, "steps", ()) or ())

    def act(self, obs: Any, env: BattlegroundsEnv) -> int:
        if obs.phase == "choice" or not obs.candidates:
            return 0
        turn = int(getattr(env.game, "turn", 0))
        if turn != self._turn:
            self._turn = turn
            self._plan = self._replan(env)
        while self._plan:
            cand = self._plan.pop(0)
            for i, c in enumerate(obs.candidates):
                if c.signature() == cand.signature():
                    return i
        # no plan / mismatch: use heuristic once, then last candidate
        try:
            desc = self.seat.heuristic.choose(env.game, env.agent_hero)
            if desc is not None:
                sig = desc.to_candidate().signature()
                for i, c in enumerate(obs.candidates):
                    if c.signature() == sig:
                        return i
        except Exception:
            pass
        return len(obs.candidates) - 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="runs/demo_4search_vs_4bc")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-turns", type=int, default=30)
    ap.add_argument("--search-sims", type=int, default=2)
    ap.add_argument("--search-width", type=int, default=2)
    ap.add_argument("--checkpoint", default="runs/bc/official_320/policy_bc.pt")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    env = BattlegroundsEnv(num_players=8, agent_index=0, opponent="heuristic",
                           seed=args.seed, max_turns=args.max_turns,
                           max_steps=4000)
    obs = env.reset(seed=args.seed)

    search = [SearchSeat(f"P{i}", simulations=args.search_sims,
                         width=args.search_width, seed=args.seed + i)
              for i in range(4)]
    bc = [BCSeat(f"P{i}", args.checkpoint) for i in range(4, 8)]
    # env creates heuristic policies for seats 1..7; replace by desired seats
    env._policies[1:4] = search[1:4]
    env._policies[4:8] = bc
    agent = SearchAgent(search[0])

    rows: List[Dict[str, Any]] = []
    done = False
    step = 0
    t0 = time.time()
    while not done and step < 8000:
        turn = int(getattr(env.game, "turn", 0))
        ranks = {}
        print(f"[loop] step={step} turn={turn} phase={obs.phase} "
              f"cands={len(obs.candidates)}", flush=True)
        action = agent.act(obs, env)
        cand = obs.candidates[action] if obs.candidates else None
        obs, reward, term, trunc, info = env.step(action)
        done = bool(term or trunc)
        step += 1
        rows.append({
            "step": step, "turn": turn, "phase": obs.phase,
            "hero": "P0", "action": getattr(cand, "kind", ""),
            "reward": float(reward), "done": done,
            "alive": int(sum(1 for h in env.game.heroes
                             if bool(getattr(h, "is_alive", False)))),
            "ranks": ranks,
        })

    final = []
    for h in env.game.heroes:
        final.append({
            "hero": h.name,
            "alive": bool(getattr(h, "is_alive", False)),
            "health": int(getattr(h, "health", 0) or 0),
            "board": len(getattr(h, "board", ()) or ()),
            "hand": len(getattr(h, "hand", ()) or ()),
            "gold": int(getattr(h, "gold", 0) or 0),
        })
    # placement approximated by elimination order if available
    placement = {}
    try:
        for i, h in enumerate(env.game.heroes):
            placement[h.name] = i
    except Exception:
        pass
    summary = {
        "seed": args.seed,
        "turns": int(getattr(env.game, "turn", 0)),
        "steps": step,
        "wall_s": round(time.time() - t0, 1),
        "search_sims": args.search_sims,
        "search_width": args.search_width,
        "search_stats": [s.stats for s in search],
        "bc_stats": [s.stats for s in bc],
        "final": final,
        "env_stats": dict(env._stats),
        "env_errors": list(env._errors)[:8],
    }
    (out / "episode.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False,
                   indent=1), encoding="utf-8")
    md = ["# 4 Search vs 4 BC — demo", "",
          f"- seed: {args.seed}，turns: {summary['turns']}，steps: {step}，"
          f"wall: {summary['wall_s']}s",
          f"- PUCT: N={args.search_sims}, width={args.search_width}",
          "", "## 最终状态", "",
          "| seat | policy | alive | hp | board |", "|---|---|---:|---:|---:|"]
    for i, h in enumerate(env.game.heroes):
        pol = "search" if i < 4 else "BC"
        md.append(f"| {h.name} | {pol} | {int(h.is_alive)} | "
                  f"{int(getattr(h, 'health', 0) or 0)} | "
                  f"{len(getattr(h, 'board', ()) or ())} |")
    (out / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    env.close()
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
