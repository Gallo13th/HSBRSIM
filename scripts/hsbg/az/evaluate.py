"""搜索质量评测：固定 seed 下与 random / heuristic / bot 基线比较名次。

用法（远程机，需 hsbg_engine）::

    python -m hsbg.az.evaluate --games 20 --seed0 70000 \
        --agents random,heuristic,bot,search_uniform,search_heuristic \
        --sims 16 --determinizations 4 --eval heuristic --backend rust

设计：
- 目标座位（默认 seat0）换 agent，其余 7 座固定用引擎 bot（`BotAgent`），
  这样所有 agent 面对**完全相同**的对手种子分布（配对比较）；
- 指标：平均名次（主）、前四率、冠军率、期望效用、决策数、耗时、搜索回退率；
- 报告 JSON 可写入指定路径（默认只打印）；训练侧可复用 `play_game/evaluate_specs`。
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

from . import env_api as EA
from .policy import (Agent, BotAgent, HeuristicAgent, RandomAgent, SearchAgent,
                     make_evaluator)
from .search import SearchConfig


@dataclass
class GameRecord:
    seed: int
    rank: int = 0
    utility: float = 0.0
    turns: int = 0
    decisions: int = 0
    elapsed_s: float = 0.0
    over: bool = False
    fallbacks: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _make_engine_game(seed: int):
    E = EA.engine_module()
    if E is None:
        raise ImportError("评测需要 hsbg_engine（cd rust && python -m pip install -e .）")
    g = E.Game(int(seed))
    EA.finish_hero_select(g)
    return g


def play_game(agents: Dict[int, Agent], seed: int, *,
              max_steps: int = 50000, seat: int = 0) -> GameRecord:
    """一局 8 人 engine 对局：`agents[p]` 控制座位 p（未给的座位用 bot）。"""
    t0 = time.perf_counter()
    g = _make_engine_game(seed)
    n = EA.num_players(g)
    for p in range(n):
        agents.setdefault(p, BotAgent())
    decisions = 0
    steps = 0
    while not EA.is_over(g) and steps < max_steps:
        acted = False
        for p in range(n):
            if not EA.needs_action(g, p):
                continue
            a = int(agents[p].act(g, p))
            if p == seat:
                decisions += 1
            try:
                EA.step(g, p, a)
            except Exception:  # noqa: BLE001 - 安全回退：bot 动作
                EA.step(g, p, EA.bot_action(g, p))
            acted = True
            steps += 1
        if not acted:
            break
    place = EA.placements(g)
    rank = int(place[seat]) if seat < len(place) else 0
    rec = GameRecord(
        seed=int(seed), rank=rank, utility=EA.placement_utility(rank, n),
        turns=int(getattr(g, "turn", 0) or 0), decisions=decisions,
        elapsed_s=float(time.perf_counter() - t0), over=bool(EA.is_over(g)),
    )
    search_agents = [a for a in agents.values() if isinstance(a, SearchAgent)]
    rec.fallbacks = sum(int(getattr(a, "n_fallbacks", 0)) for a in search_agents)
    return rec


def summarize(records: Sequence[GameRecord]) -> dict:
    if not records:
        return {"games": 0}
    ranks = np.array([r.rank for r in records if r.rank > 0], dtype=np.float64)
    utils = np.array([r.utility for r in records], dtype=np.float64)
    out = {
        "games": len(records),
        "finished": int(len(ranks)),
        "mean_rank": float(ranks.mean()) if ranks.size else float("nan"),
        "top4_rate": float((ranks <= 4).mean()) if ranks.size else float("nan"),
        "win_rate": float((ranks == 1).mean()) if ranks.size else float("nan"),
        "mean_utility": float(utils.mean()) if utils.size else float("nan"),
        "mean_turns": float(np.mean([r.turns for r in records])),
        "decisions": int(sum(r.decisions for r in records)),
        "fallbacks": int(sum(r.fallbacks for r in records)),
        "elapsed_s": float(sum(r.elapsed_s for r in records)),
    }
    if ranks.size:
        # 95% bootstrap CI（1000 次，固定内部 seed，保证报告可复现）
        rng = np.random.default_rng(12345)
        means = [float(rng.choice(ranks, size=ranks.size, replace=True).mean())
                 for _ in range(1000)]
        out["mean_rank_ci95"] = [float(np.percentile(means, 2.5)),
                                 float(np.percentile(means, 97.5))]
    return out


def _agent_factory(name: str, *, evaluator=None, sims: int, determ: int,
                   backend: str, c_puct: float, dirichlet_eps: float,
                   temperature: float, search_seed: int) -> callable:
    key = name.lower()
    if key == "random":
        return lambda: RandomAgent(seed=search_seed)
    if key == "heuristic":
        return lambda: HeuristicAgent()
    if key == "bot":
        return lambda: BotAgent()
    if key.startswith("search"):
        ev = evaluator
        eff_backend = backend
        if key == "search_uniform":
            ev = make_evaluator("uniform")
        elif key == "search_rollout":
            ev = make_evaluator("rollout", horizon=8)
        elif key in ("search_bot", "search_bot_prior"):
            # bot 先验需要 game 对象 → Python 后端（Rust 回调只有观测）
            ev = make_evaluator("bot_prior", blend=0.75)
            eff_backend = "python"
        elif key == "search_heuristic":
            ev = ev or make_evaluator("heuristic")

        def make():
            return SearchAgent(
                SearchConfig(simulations=int(sims), determinizations=int(determ),
                             c_puct=float(c_puct), temperature=float(temperature),
                             dirichlet_epsilon=float(dirichlet_eps), seed=int(search_seed)),
                evaluator=ev, backend=eff_backend, name=name)
        return make
    raise ValueError(f"未知 agent: {name}")


def evaluate_specs(specs: Dict[str, callable], seeds: Iterable[int], *,
                   seat: int = 0, eval_name: str = "heuristic",
                   max_steps: int = 50000) -> dict:
    """对每个 agent 规格在固定 seed 集上跑对局并汇总（配对：同 seeds 同对手）。"""
    seeds = [int(s) for s in seeds]
    report: Dict[str, Any] = {"seat": int(seat), "seeds": seeds, "agents": {}}
    for name, factory in specs.items():
        records: List[GameRecord] = []
        for sd in seeds:
            agent = factory()
            if hasattr(agent, "reset"):
                agent.reset(sd)
            agents = {int(seat): agent}
            records.append(play_game(agents, sd, max_steps=max_steps, seat=seat))
        summary = summarize(records)
        summary["per_game"] = [r.as_dict() for r in records]
        report["agents"][name] = summary
    return report


def _parse_seeds(args) -> List[int]:
    return [int(args.seed0) + i for i in range(int(args.games))]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AlphaZero 不完全信息搜索质量评测（固定 seed）")
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--seed0", type=int, default=70000)
    ap.add_argument("--seat", type=int, default=0)
    ap.add_argument("--agents", type=str,
                    default="random,heuristic,bot,search_uniform,search_heuristic")
    ap.add_argument("--sims", type=int, default=16)
    ap.add_argument("--determinizations", type=int, default=4)
    ap.add_argument("--c-puct", type=float, default=1.5)
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="评测默认 argmax（0）；训练自对弈用 1.0")
    ap.add_argument("--dirichlet-epsilon", type=float, default=0.0)
    ap.add_argument("--eval", dest="eval_name", type=str, default="heuristic",
                    choices=["heuristic", "uniform", "rollout"])
    ap.add_argument("--backend", type=str, default="auto",
                    choices=["auto", "rust", "python"])
    ap.add_argument("--search-seed", type=int, default=0)
    ap.add_argument("--report-json", type=str, default=None)
    args = ap.parse_args(argv)

    evaluator = make_evaluator(args.eval_name, **({"horizon": 8}
                                                 if args.eval_name == "rollout" else {}))
    specs = {
        name.strip(): _agent_factory(
            name.strip(), evaluator=evaluator if name.strip().startswith("search") else None,
            sims=args.sims, determ=args.determinizations, backend=args.backend,
            c_puct=args.c_puct, dirichlet_eps=args.dirichlet_epsilon,
            temperature=args.temperature, search_seed=args.search_seed)
        for name in args.agents.split(",") if name.strip()
    }
    report = evaluate_specs(specs, _parse_seeds(args), seat=args.seat,
                            eval_name=args.eval_name)
    report["config"] = {
        "sims": args.sims, "determinizations": args.determinizations,
        "c_puct": args.c_puct, "temperature": args.temperature,
        "dirichlet_epsilon": args.dirichlet_epsilon, "eval": args.eval_name,
        "backend": args.backend, "engine": (EA.engine_module().version()
                                            if EA.engine_module() else None),
        "data": (EA.engine_module().data_info() if EA.engine_module() else None),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
