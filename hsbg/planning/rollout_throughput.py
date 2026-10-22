"""Hard search（不评分）用 rollout 到终局/有限 horizon 的统一接口与吞吐工具。

背景：用户要求 **train-free 决策**——不训练价值网，用"rollout 到终局"的
胜率/名次估计动作好坏（hard search / rollout policy）。本模块提供：

- :class:`HeuristicEnginePolicy` / :class:`RandomEnginePolicy`：引擎层策略
  适配器（heuristic 的 `choose(game, hero)` + 选择步默认策略）；
- :func:`drive_recruit_turn`：驱动**所有英雄**的一个招募回合（目标英雄用
  给定策略、对手用 `opponent_policy`），再 `game.end_recruit_phase()`——
  与 ``BattlegroundsEnv`` 的对手语义一致（对手会买牌/刷新），但跳过 obs
  构建，专为吞吐设计；
- :func:`rollout_to_end`：从桌面快照 rollout 到终局/``max_turns``，返回
  :class:`RolloutEndResult`（rank/health/turns/steps/是否冠军）；
- :func:`rollout_batch`：顺序批量 rollout；:func:`benchmark_rollout`：分位数
  与吞吐统计（脚本 ``scripts/bench_rollout.py`` 使用）。

**不改引擎语义**：使用引擎自己的招募/战斗/淘汰流程；rollout 默认在
``model.clone`` 出的独立副本上执行（不污染原局面）。
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from hsrl2.game import Game
from hsrl2.hero import Hero

from hsbg.agents.base import choose_option_index  # noqa: F401  (obs 辅助)
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import driver
from hsbg.planning import model

__all__ = [
    "HeuristicEnginePolicy",
    "RandomEnginePolicy",
    "RolloutEndResult",
    "drive_recruit_turn",
    "rollout_to_end",
    "rollout_batch",
    "benchmark_rollout",
]


# ══════════════════════════════════════════════════════════════════════
# 引擎层策略适配器
# ══════════════════════════════════════════════════════════════════════


class HeuristicEnginePolicy:
    """把 ``HeuristicPolicy`` 包成"引擎层 rollout 策略"。

    - ``choose_action(game, hero)`` 直接调用 heuristic 的 ``choose``（其内部
      用 driver 枚举，返回 ActionDescriptor）；
    - ``choose_option_index(choice, game)`` 用 engine 默认选择策略（可替换）。
    """

    name = "heuristic"

    def __init__(self, policy: Any = None):
        self.policy = policy or HeuristicPolicy()

    def choose_action(self, game: Game, hero: Hero) -> Optional[Any]:
        try:
            return self.policy.choose(game, hero)
        except Exception:                                 # noqa: BLE001
            return None

    def choose_option_index(self, choice: Any, game: Game) -> int:
        return int(driver.default_pick_index(choice, game))


class RandomEnginePolicy(model.RandomRolloutPolicy):
    """引擎层随机策略（独立 RNG，可复现；适配 rollout 接口）。"""

    name = "random"

    def choose_action(self, game: Game, hero: Hero) -> Optional[Any]:
        return self.choose_action_random(game, hero)

    def choose_action_random(self, game: Game, hero: Hero) -> Optional[Any]:
        actions = model.legal_actions(game, hero)
        if not actions:
            return None
        choice = model.pending_choice(game, hero)
        if choice is not None:
            return actions[self.rng.randint(0, len(actions) - 1)]
        end = [d for d in actions
               if d.kind == driver.ActionKind.END_TURN.value]
        others = [d for d in actions
                  if d.kind != driver.ActionKind.END_TURN.value]
        if end and (not others or self.rng.random() < self.end_turn_prob):
            return end[0]
        if not others:
            return end[0] if end else None
        return others[self.rng.randint(0, len(others) - 1)]


def _policy_choose_action(policy: Any, game: Game, hero: Hero) -> Optional[Any]:
    fn = getattr(policy, "choose_action", None)
    if fn is not None:
        return fn(game, hero)
    fn = getattr(policy, "choose", None)
    if fn is not None:
        return fn(game, hero)
    return None


def _policy_choose_option(policy: Any, choice: Any, game: Game) -> int:
    fn = getattr(policy, "choose_option_index", None)
    if fn is not None:
        try:
            return int(fn(choice, game))
        except Exception:                                 # noqa: BLE001
            pass
    return int(driver.default_pick_index(choice, game))


# ══════════════════════════════════════════════════════════════════════
# 回合驱动 / rollout
# ══════════════════════════════════════════════════════════════════════


def drive_recruit_turn(game: Game, policies: Dict[int, Any], *,
                       hero_indices: Optional[Sequence[int]] = None,
                       max_actions_per_hero: int = 120) -> int:
    """驱动**所有存活英雄**的一个招募回合（含选择步），返回动作数。

    ``policies``: ``{hero_index: policy}``；未提供的英雄用引擎默认选择策略
    兜底（仍会行动：有 end_turn 就结束）。对手会像 env 一样买牌/刷新，随后
    调用一次 ``game.end_recruit_phase()``（配对/战斗/淘汰/下一回合初始化）。
    """
    steps = 0
    indices = (list(hero_indices) if hero_indices is not None
               else list(range(len(game.heroes))))
    for idx in indices:
        hero = game.heroes[idx]
        if not hero.is_alive:
            continue
        policy = policies.get(idx)
        for _ in range(max_actions_per_hero):
            choice = model.pending_choice(game, hero)
            if choice is not None:
                option = _policy_choose_option(policy, choice, game) \
                    if policy is not None else int(
                        driver.default_pick_index(choice, game))
                if not game.pending_choices \
                        or game.pending_choices[0] is not choice:
                    continue
                game.pending_choices.pop(0)
                try:
                    choice.choose(option)
                except Exception:                         # noqa: BLE001
                    pass
                steps += 1
                continue
            action = (_policy_choose_action(policy, game, hero)
                      if policy is not None else None)
            if action is None:
                ends = [d for d in model.legal_actions(game, hero)
                        if d.kind == driver.ActionKind.END_TURN.value]
                action = ends[0] if ends else None
            if action is None:
                break
            res = model.apply(game, hero, action)
            steps += 1
            if not res.success:
                ends = [d for d in model.legal_actions(game, hero)
                        if d.kind == driver.ActionKind.END_TURN.value]
                if not ends or not model.apply(game, hero, ends[0]).success:
                    break
                action = ends[0]
            model.drain_choices(game, hero)
            if action.kind == driver.ActionKind.END_TURN.value:
                break
    # 清理所有残余选择后推进宏回合
    try:
        driver.resolve_pending_choices(game, None, None)
    except Exception:                                     # noqa: BLE001
        pass
    game.end_recruit_phase()
    try:
        driver.resolve_pending_choices(game, None, None)
    except Exception:                                     # noqa: BLE001
        pass
    return steps


@dataclass
class RolloutEndResult:
    """rollout 到终局/有限 horizon 的结果。"""

    terminated: bool = False
    truncated: bool = False
    turns: int = 0
    steps: int = 0
    rank: int = 0
    health: int = 0
    alive: bool = False
    champion: bool = False
    value: float = 0.0
    finished: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "terminated": bool(self.terminated),
            "truncated": bool(self.truncated),
            "turns": int(self.turns),
            "steps": int(self.steps),
            "rank": int(self.rank),
            "health": int(self.health),
            "alive": bool(self.alive),
            "champion": bool(self.champion),
            "value": float(self.value),
            "finished": bool(self.finished),
        }


def _rank(game: Game, hero: Hero) -> int:
    if not hero.is_alive:
        return max(1, sum(1 for h in game.heroes if h.is_alive) + 1)
    if game.finished:
        return 1
    my_hp = int(hero.health) + int(hero.armor)
    better = sum(1 for h in game.heroes
                 if h is not hero and h.is_alive
                 and int(h.health) + int(h.armor) > my_hp)
    return 1 + better


def rollout_to_end(game: Game, policy: Any = None,
                   *, hero: Optional[Hero] = None,
                   max_turns: Optional[int] = None,
                   opponent_policy: Any = None,
                   fast_opponents: bool = False,
                   clone_state: bool = True,
                   max_steps: int = 20000) -> Tuple[RolloutEndResult, Game]:
    """从快照 rollout 到终局（或 ``max_turns`` 个宏回合），返回结果与终局副本。

    - ``policy``：目标英雄的滚动策略（``HeuristicEnginePolicy`` /
      ``RandomEnginePolicy`` / 任意带 ``choose_action``/``choose`` 的对象）；
    - 对手默认用 ``HeuristicEnginePolicy``；
    - ``max_turns=None`` → 打到终局；给整数 → 运行 N 个宏回合后截断；
    - ``clone_state=True``（默认）在副本上执行，原 game 不被修改；
    - 返回 ``(RolloutEndResult, final_game)``，便于复用终局状态/观测。
    """
    if game is None:
        raise ValueError("rollout_to_end(None)")
    dup = model.clone(game) if clone_state else game
    hero_idx = 0
    if hero is not None:
        try:
            hero_idx = game.heroes.index(hero)
        except ValueError as exc:
            raise ValueError("hero 不属于该 game") from exc
    target = dup.heroes[hero_idx]
    policy = policy or HeuristicEnginePolicy()
    opponent_policy = opponent_policy or HeuristicEnginePolicy()

    policies: Dict[int, Any] = {i: opponent_policy
                                for i in range(len(dup.heroes))}
    policies[hero_idx] = policy
    result = RolloutEndResult(health=int(target.health),
                              alive=bool(target.is_alive))
    turns = 0
    steps = 0
    while True:
        if not target.is_alive or dup.finished:
            result.terminated = True
            break
        if steps > max_steps:
            result.truncated = True
            break
        steps += drive_recruit_turn(
            dup, policies,
            hero_indices=[hero_idx] if fast_opponents else None)
        turns += 1
        if not target.is_alive or dup.finished:
            result.terminated = True
            break
        if max_turns is not None and turns >= int(max_turns):
            result.truncated = True
            break
    result.turns = turns
    result.steps = steps
    result.health = int(target.health) if target.is_alive else 0
    result.alive = bool(target.is_alive)
    result.finished = bool(dup.finished)
    result.rank = _rank(dup, target)
    result.champion = bool(result.rank == 1 and (target.is_alive
                                                 or dup.finished))
    try:
        result.value = float(model.evaluate(dup, target)["value"])
    except Exception:                                     # noqa: BLE001
        result.value = 0.0
    return result, dup


def rollout_batch(game: Game, policy: Any = None, *, n: int = 4,
                  max_turns: Optional[int] = None,
                  opponent_policy: Any = None,
                  fast_opponents: bool = False,
                  seeds: Optional[Sequence[int]] = None) -> List[RolloutEndResult]:
    """顺序批量 rollout（每个 rollout 内部 clone；``seeds`` 给策略随机种子）。"""
    results: List[RolloutEndResult] = []
    for i in range(max(1, int(n))):
        if seeds is not None and i < len(seeds):
            if isinstance(policy, RandomEnginePolicy):
                policy = RandomEnginePolicy(seed=int(seeds[i]),
                                            end_turn_prob=policy.end_turn_prob)
        res, _dup = rollout_to_end(game, policy, max_turns=max_turns,
                                   opponent_policy=opponent_policy,
                                   fast_opponents=fast_opponents)
        results.append(res)
    return results


# ══════════════════════════════════════════════════════════════════════
# 基准统计
# ══════════════════════════════════════════════════════════════════════


def benchmark_rollout(game: Game, *, policy: Any = None,
                      opponent_policy: Any = None,
                      max_turns: Optional[int] = None,
                      fast_opponents: bool = False,
                      repeats: int = 5,
                      seeds: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """对同一快照做 ``repeats`` 次 rollout，返回分位数/吞吐/结果分布。"""
    times: List[float] = []
    results: List[RolloutEndResult] = []
    for i in range(max(1, repeats)):
        pol = policy
        if isinstance(policy, RandomEnginePolicy):
            base_seed = None if seeds is None else None
            seed = (int(seeds[i]) if seeds is not None and i < len(seeds)
                    else int(policy.rng.randint(0, 1_000_000)))
            pol = RandomEnginePolicy(seed=seed,
                                     end_turn_prob=policy.end_turn_prob)
        t0 = time.perf_counter()
        res, _dup = rollout_to_end(game, pol, max_turns=max_turns,
                                   opponent_policy=opponent_policy,
                                   fast_opponents=fast_opponents)
        times.append((time.perf_counter() - t0) * 1000.0)
        results.append(res)
    times.sort()
    n = len(times)

    def _pct(p: float) -> float:
        return times[min(n - 1, int(round(p * (n - 1))))]

    ranks = [r.rank for r in results]
    return {
        "repeats": n,
        "max_turns": max_turns,
        "turn_mean": statistics.fmean([r.turns for r in results]),
        "steps_mean": statistics.fmean([r.steps for r in results]),
        "p50_ms": _pct(0.5),
        "p90_ms": _pct(0.9),
        "p99_ms": _pct(0.99),
        "mean_ms": statistics.fmean(times),
        "min_ms": times[0],
        "max_ms": times[-1],
        "rollouts_per_sec": 1000.0 / statistics.fmean(times),
        "terminated_rate": sum(1 for r in results if r.terminated) / n,
        "champion_rate": sum(1 for r in results if r.champion) / n,
        "rank_mean": statistics.fmean(ranks),
        "rank_counts": {str(k): ranks.count(k)
                        for k in sorted(set(ranks))},
        "value_mean": statistics.fmean([r.value for r in results]),
    }
