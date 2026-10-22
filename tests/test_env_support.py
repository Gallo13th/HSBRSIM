"""环境测试共享工具（无测试用例；供 ``test_env_*.py`` / ``test_agents_*.py`` 复用）。"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import driver
from hsbg.env.spec import CandidateAction

#: 无脚本的池内随从（构造边界状态用；不会被任何效果脚本改写）
VANILLA_MINION = "BG25_001"      # Risen Rider 2/1 Tier1 Undead
VANILLA_MINION2 = "BGS_119"      # Crackling Cyclone 2/1 Tier1 Elemental


def hero_pool() -> List[str]:
    db = driver.get_card_db()
    ids = []
    for d in db._by_id.values():
        try:
            is_hero = int(getattr(d, "card_type", -1)) == 3
        except Exception:                                 # noqa: BLE001
            is_hero = False
        if is_hero and str(d.id).startswith(("TB_BaconShop_HERO", "BG")):
            ids.append(str(d.id))
    return sorted(ids)


def make_engine_game(seed: int = 0, num_players: int = 8
                     ) -> Tuple[Game, List[Hero]]:
    """构造一个已 ``start_game`` 且无待决选择的引擎对局（不经过环境层）。"""
    db = driver.get_card_db()
    ids = hero_pool()
    heroes = [Hero(ids[i], f"P{i}") for i in range(num_players)]
    game = Game(heroes, db, seed=seed)
    game.start_game()
    driver.resolve_pending_choices(game, None)
    return game, heroes


def add_minion_to_board(game: Game, hero: Hero, card_id: str = VANILLA_MINION,
                        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m)
    return m


def add_minion_to_hand(game: Game, hero: Hero, card_id: str = VANILLA_MINION
                       ) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert hero.add_to_hand(m)
    return m


def add_spell_to_hand(game: Game, hero: Hero, card_id: str) -> Any:
    s = game.create_spell(card_id, controller=hero)
    assert hero.add_to_hand(s)
    return s


def first_tavern_spell(game: Game, hero: Hero) -> Optional[str]:
    """酒馆里第一个法术的 card_id（用于构造手牌法术）。"""
    from hsrl2.spell import Spell as _Spell
    for e in hero.tavern:
        if isinstance(e, _Spell):
            return e.card_id
    return None


def descriptors_signatures(descs: Sequence[Any]) -> List[Tuple]:
    return [d.to_candidate().signature() for d in descs]


def play_game(seed: int, *, policy: Any = None,
              max_steps: int = 2000, env_kwargs: Optional[Dict[str, Any]] = None
              ) -> Tuple[Any, Any, Dict[str, Any], List[Tuple], Tuple[bool, bool]]:
    """用启发式策略驱动智能体跑完一局。

    返回 ``(env, obs, info, trace, (terminated, truncated))``；
    ``trace`` 每步记录 ``(turn, phase, 候选签名元组, reward, 动作签名)``。
    """
    from hsbg.env import BattlegroundsEnv
    policy = policy or HeuristicPolicy()
    kwargs = dict(env_kwargs or {})
    kwargs.pop("seed", None)
    env = BattlegroundsEnv(seed=seed, **kwargs)
    obs = env.reset(seed=seed)
    trace: List[Tuple] = []
    steps = 0
    terminated = truncated = False
    while True:
        steps += 1
        if obs.phase == "choice":
            action = CandidateAction(kind="choose",
                                     option=policy.choose_option_index(obs))
        else:
            desc = policy.choose(env.game, env.agent_hero)
            action = CandidateAction(kind="end_turn") if desc is None \
                else desc.to_candidate()
        cands = tuple(c.signature() for c in obs.candidates)
        obs, reward, terminated, truncated, info = env.step(action)
        trace.append((obs.turn, obs.phase, cands, float(reward),
                      action.signature()))
        if terminated or truncated:
            break
        if steps >= max_steps:
            raise AssertionError(f"game seed={seed} did not finish in "
                                 f"{max_steps} steps")
    return env, obs, info, trace, (bool(terminated), bool(truncated))


def run_game(seed: int, *, policy: Any = None, max_steps: int = 2000,
             env_kwargs: Optional[Dict[str, Any]] = None
             ) -> Dict[str, Any]:
    """跑完一局并返回**纯数据**摘要（环境随即关闭，便于缓存复用）。"""
    import time as _time
    t0 = _time.perf_counter()
    env, obs, info, trace, flags = play_game(seed, policy=policy,
                                             max_steps=max_steps,
                                             env_kwargs=env_kwargs)
    elapsed = _time.perf_counter() - t0
    stats = dict(env.stats)
    summary = {
        "seed": seed,
        "info": dict(info),
        "trace": trace,
        "rewards": [t[3] for t in trace],
        "total_reward": float(sum(t[3] for t in trace)),
        "steps": len(trace),
        "turn": int(info.get("turn", 0)),
        "rank": int(info.get("rank", 0)),
        "final_phase": str(obs.phase),
        "terminated": bool(flags[0]),
        "truncated": bool(flags[1]),
        "engine_errors": int(stats.get("engine_errors", 0)),
        "invalid": int(stats.get("invalid", 0)),
        "episode_steps": int(info.get("episode_steps", 0)),
        "elapsed_ms": elapsed * 1000.0,
    }
    env.close()
    return summary
