"""固定 seed 的策略评测：seat0 = 被评策略，其余 7 座 = 引擎 bot。

评测协议（docs/AZ_MCTS_SELFPLAY_DESIGN.md §9）：
- 评测 seed 集与自对弈 seed 分离（默认从 ``--seed`` 递增，调用方保证不重叠）；
- 记录：平均名次（主）、前四率、冠军率、期望效用、合法动作率、truncated、耗时、决策数；
- 引擎 bot 基线 = 同一循环里 seat0 也走 ``bot_action``（特权，仅作基线）。

**人类战团对手面板**（``docs/EVAL_PANELS.md``）：``EvalConfig.human_board_pool`` 非空时，
每个**新回合开始、任何座位行动前**，把该 turn 分位的人类战团（board-only）注入全部
非 learner 座位。注入是 board-only 近似（无 hand/shop/池差量），只用于对手强度评测，
不改变被评策略的观测/动作口径。注入 RNG 按 ``(seed, game, turn, seat)`` 独立派生，
因此同一 seed 的 model / bot 基线面对的是同一批人类战团。

只用 ``observe/legal_mask`` 作为被评策略的决策输入；``bot_action`` 只出现在基线策略里。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .common import (
    N_PLAYERS,
    load_engine,
    mask_from_bytes,
    obs_arrays,
    utility_from_rank,
)
from .human_board_pool import HumanBoardStats, inject_turn
from .policies import EngineBotPolicy, Policy


@dataclass
class EvalConfig:
    """评测配置。"""

    games: int = 20
    seed: int = 90000
    policy_seat: int = 0
    max_steps: int = 50000
    opponent: str = "engine_bot"   # 其余座位策略（当前只支持引擎 bot）
    collect_examples: int = 0      # >0 时保留若干决策样本用于人工抽查
    #: 人类战团池（``HumanBoardPool``）；None = 纯引擎 bot 面板（零影响）。
    human_board_pool: Any = None
    #: 注入时是否同时写入按 turn 派生的 tier（人类数据没有 tier 字段）。
    human_board_set_tier: bool = True


def _mix_seed(*parts: int) -> int:
    """把 ``(seed, game, turn, seat)`` 混合成稳定的 63-bit 注入 RNG 种子。

    **不能**依赖调用顺序：model / bot 两条基线局内死亡座位不同，若用单一 RNG 顺序
    消耗，同一 seed 的两条基线在后期会抽到不同的战团，配对差分就失去了可比性。
    """
    h = 0x9E3779B97F4A7C15
    for p in parts:
        h ^= (int(p) + 0x9E3779B97F4A7C15 + (h << 6) + (h >> 2)) & 0xFFFFFFFFFFFFFFFF
        h &= 0xFFFFFFFFFFFFFFFF
    return int(h % ((1 << 63) - 1))


def _inject_human_turn(game: Any, config: "EvalConfig", *, seed: int, gi: int,
                       turn: int, stats: HumanBoardStats) -> int:
    """新回合开始：给全部存活、非 learner 座位各注入该 turn 的一条人类战团。

    逐座位独立调用 :func:`inject_turn`（``seats=[seat]``），这样每个座位的采样 RNG
    只由 ``(seed, game, turn, seat)`` 决定，与其它座位是否存活/注入成功无关。
    返回尝试注入的座位数。
    """
    pool = getattr(config, "human_board_pool", None)
    if pool is None:
        return 0
    learner = int(config.policy_seat)
    try:
        health = [int(h) for h in game.health()]
    except Exception:  # noqa: BLE001 - 旧构建没有 health() -> 不按血量过滤
        health = [1] * N_PLAYERS
    seats = [s for s in range(N_PLAYERS)
             if s != learner and 0 <= s < len(health) and health[s] > 0]
    for seat in seats:
        rng = random.Random(_mix_seed(int(seed) + int(gi), int(turn), int(seat)))
        inject_turn(game, pool, int(turn), seats=[int(seat)], p=1.0, rng=rng,
                    learner_seat=learner, stats=stats,
                    set_tier=bool(getattr(config, "human_board_set_tier", True)))
    return len(seats)


def evaluate_policy(policy: Policy, config: EvalConfig) -> Dict[str, Any]:
    """评测一个策略（固定 seeds，seat0 vs 7 引擎 bot / 可选人类战团注入）。"""
    E = load_engine()
    seat0 = int(config.policy_seat)
    ranks: List[int] = []
    truncated = 0
    decisions = 0
    illegal = 0
    examples: List[Dict[str, Any]] = []
    truncated_combats = 0
    hb_stats = HumanBoardStats()
    hb_turns = 0
    t0 = time.time()
    for gi in range(int(config.games)):
        game = E.Game(seed=int(config.seed) + gi)
        game_seed = int(config.seed) + gi
        policy.reset()
        steps = 0
        last_turn = -1
        state: Dict[str, int] = {"turns": 0}

        def _maybe_inject() -> None:
            """在**任何座位行动前**检查是否进入新回合；新回合则注入一次。

            必须在 while 顶层和 ``for p`` 内都调用：引擎可能在 ``for p`` 中途推进
            turn（例如 learner 结束本回合后，后续座位的 ``bot_play`` 已经属于新回合），
            只在 while 顶层注入会错过窗口、被 ``already_ended`` 拒绝。
            """
            nonlocal last_turn
            if getattr(config, "human_board_pool", None) is None:
                return
            turn_now = int(game.turn)
            if turn_now == last_turn:
                return
            last_turn = turn_now
            if turn_now < 1:
                # 引擎 turn=0 是开局准备帧（人类数据从 turn=1 起，且该帧注入会被
                # 引擎以 not_recruit 拒绝）；直接从 turn=1 开始注入。
                return
            _inject_human_turn(game, config, seed=int(config.seed), gi=gi,
                               turn=turn_now, stats=hb_stats)
            state["turns"] += 1

        while not game.is_over() and steps < int(config.max_steps):
            _maybe_inject()
            acted = False
            for p in range(N_PLAYERS):
                _maybe_inject()
                if not game.needs_action(p):
                    continue
                seat = int(p)
                if seat == seat0:
                    mask = mask_from_bytes(game.legal_mask(seat))
                    dec = policy.decide(game, seat)
                    action = int(dec.action)
                    if not (0 <= action < mask.size and bool(mask[action])):
                        illegal += 1
                        legal = np.flatnonzero(mask)
                        action = int(legal[0]) if legal.size else 0
                    if len(examples) < int(config.collect_examples):
                        f, c = obs_arrays(game.observe(seat))
                        examples.append({"features": f, "cards": c, "mask": mask,
                                         "action": action, "seat": seat,
                                         "turn": int(game.turn), "seed": game_seed,
                                         "info": dec.info})
                    game.step(seat, action)
                    decisions += 1
                else:
                    game.bot_play(seat)
                acted = True
                steps += 1
                if game.is_over():
                    break
            if not acted:
                break
        hb_turns += int(state["turns"])
        if game.is_over():
            ranks.append(int(game.placements()[seat0]))
        else:
            truncated += 1
            ranks.append(0)
        try:
            truncated_combats += int(game.truncated_combats())
        except Exception:  # noqa: BLE001 - 旧构建可能无此 API
            pass
    elapsed = time.time() - t0
    known = np.asarray([r for r in ranks if r >= 1], dtype=np.float32)
    n_known = int(known.size)
    util = utility_from_rank(known) if n_known else np.zeros(0, dtype=np.float32)
    rank_counts: Dict[int, int] = {}
    for r in ranks:
        rank_counts[int(r)] = rank_counts.get(int(r), 0) + 1
    hb_meta = hb_stats.to_meta()
    return {
        "policy": getattr(policy, "name", "unknown"),
        "gameplay": getattr(policy, "playstyle", None),
        "games": int(config.games),
        "games_finished": int(n_known),
        "truncated_games": int(truncated),
        "seed_start": int(config.seed),
        "seed_end": int(config.seed) + int(config.games) - 1,
        "policy_seat": seat0,
        "opponent": str(config.opponent),
        "mean_rank": float(known.mean()) if n_known else None,
        "top4_rate": float((known <= 4).mean()) if n_known else None,
        "win_rate": float((known == 1).mean()) if n_known else None,
        "mean_utility": float(util.mean()) if n_known else None,
        "rank_counts": rank_counts,
        "rank_sequence": [int(r) for r in ranks],
        "decisions": int(decisions),
        "decisions_per_game": float(decisions / max(config.games, 1)),
        "illegal_actions": int(illegal),
        "legal_action_rate": float(1.0 - illegal / max(decisions, 1)),
        "truncated_combats": int(truncated_combats),
        "seconds": float(elapsed),
        "ms_per_decision": float(1000.0 * elapsed / max(decisions, 1)),
        "games_per_s": float(config.games / max(elapsed, 1e-9)),
        # 人类战团注入计数（纯 bot 面板时全为 0；写进 panel details 便于核对是否真的生效）
        "human_board": hb_meta,
        "human_board_turns": int(hb_turns),
        "examples": examples,
    }


def evaluate_baseline(config: EvalConfig) -> Dict[str, Any]:
    """引擎 bot 基线（同协议：seat0=bot，其余 bot）。"""
    cfg = EvalConfig(games=config.games, seed=config.seed,
                     policy_seat=config.policy_seat, max_steps=config.max_steps,
                     opponent=config.opponent)
    return evaluate_policy(EngineBotPolicy(), cfg)


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def run_comparison(policy_factory: Dict[str, Any], config: EvalConfig) -> Dict[str, Any]:
    """跑一组策略的对比评测。

    ``policy_factory``：``{name: zero-arg callable -> Policy}``；
    返回 ``{"protocol":..., "policies": {name: metrics}, "comparison": {...}}``
    """
    results: Dict[str, Dict[str, Any]] = {}
    for name, factory in policy_factory.items():
        policy = factory()
        print(f"[eval] policy={name} games={config.games} seeds={config.seed}"
              f"..{config.seed + config.games - 1}", flush=True)
        res = evaluate_policy(policy, config)
        results[name] = res
        print(f"[eval] {name}: mean_rank={res['mean_rank']} top4={res['top4_rate']} "
              f"win={res['win_rate']} trunc={res['truncated_games']} "
              f"legal={res['legal_action_rate']:.4f} {res['seconds']:.1f}s", flush=True)
    base = results.get("bot") or results.get("engine_bot")
    comparison: Dict[str, Any] = {}
    for name, res in results.items():
        if name == "bot" or name == base:
            continue
        comparison[f"{name}_vs_bot"] = {
            "mean_rank_delta": _delta(res.get("mean_rank"),
                                      base.get("mean_rank") if base else None),
            "top4_rate_delta": _delta(res.get("top4_rate"),
                                      base.get("top4_rate") if base else None),
            "win_rate_delta": _delta(res.get("win_rate"),
                                     base.get("win_rate") if base else None),
            "mean_utility_delta": _delta(res.get("mean_utility"),
                                         base.get("mean_utility") if base else None),
        }
    return {
        "protocol": {
            "games_per_policy": int(config.games),
            "seed_start": int(config.seed),
            "seed_end": int(config.seed) + int(config.games) - 1,
            "policy_seat": int(config.policy_seat),
            "opponent": str(config.opponent),
            "max_steps": int(config.max_steps),
        },
        "policies": results,
        "comparison": comparison,
    }


__all__ = ["EvalConfig", "evaluate_policy", "evaluate_baseline", "run_comparison"]
