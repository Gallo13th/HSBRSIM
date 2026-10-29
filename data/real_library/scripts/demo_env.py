#!/usr/bin/env python
"""环境演示：启发式策略驱动智能体打完整一局酒馆战棋。

用法::

    python scripts/demo_env.py --players 8 --seed 42

输出（每回合一行）: turn / hp+armor / tavern tier / gold / board power /
hand / rank；end_turn 后附战斗结果；结束打印最终名次、总步数、耗时。

说明：智能体英雄由 :class:`hsbg.agents.heuristic.HeuristicPolicy` 驱动
（与默认脚本对手同源），只通过环境的候选动作 API 行动；PendingChoice 由
同一策略的选项启发式决策。

注：脚本输出刻意使用 ASCII 标签（Windows 控制台编码兼容）。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.agents.heuristic import HeuristicPolicy  # noqa: E402
from hsbg.env import BattlegroundsEnv  # noqa: E402
from hsbg.env.spec import (  # noqa: E402
    ActionKind,
    CandidateAction,
)


def board_power(obs) -> int:
    return sum(int(t.atk) + int(t.health) for t in obs.board)


def print_turn(obs, info) -> None:
    hero = obs.hero
    if hero is None:                                      # pragma: no cover
        return
    print(f"[T{obs.turn:02d}] hp={hero.health:2d}+{hero.armor:2d} "
          f"tier={hero.tier} gold={hero.gold:2d} "
          f"board_power={board_power(obs):3d} board={len(obs.board)} "
          f"hand={len(obs.hand)} rank={info.get('rank', obs.rank)}"
          f"/{obs.alive_count}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Battlegrounds RL env demo (heuristic agent)")
    ap.add_argument("--players", type=int, default=8,
                    help="player count (2..8, default 8)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--opponent", default="heuristic",
                    help="opponent policy name (random/heuristic/teacher)")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--hero", default=None,
                    help="agent hero id (default: random)")
    ap.add_argument("--anomaly", default=None, help="anomaly card id")
    ap.add_argument("--quiet", action="store_true",
                    help="print one line every 5 turns only")
    args = ap.parse_args(argv)

    policy = HeuristicPolicy()
    t_start = time.perf_counter()
    env = BattlegroundsEnv(num_players=args.players, opponent=args.opponent,
                           hero_id=args.hero, anomaly=args.anomaly,
                           max_turns=args.max_turns, seed=args.seed)
    obs = env.reset(seed=args.seed)
    t_reset = time.perf_counter() - t_start
    hero_id = obs.hero.hero_id if obs.hero is not None else "?"

    print("=" * 78)
    print(f"Battlegrounds RL env demo | players={args.players} "
          f"seed={args.seed} opponent={args.opponent}")
    print(f"agent hero: {hero_id} | initial rank={obs.rank} | "
          f"reset {t_reset * 1000:.1f} ms")
    print("=" * 78)

    total_reward = 0.0
    steps = 0
    last_printed_turn = -1
    t_run = time.perf_counter()
    terminated = truncated = False
    info: dict = {}
    while True:
        steps += 1
        if obs.phase == "choice":
            option = policy.choose_option_index(obs)
            kind = obs.pending_choice.kind if obs.pending_choice else "?"
            print(f"[T{obs.turn:02d}] CHOICE kind={kind} -> option {option}")
            action = CandidateAction(kind=ActionKind.CHOOSE.value,
                                     option=option)
        else:
            # 回合开始（动作前）打印状态：金币/等级/场面战力
            if obs.turn != last_printed_turn and (
                    not args.quiet or obs.turn % 5 == 0):
                print_turn(obs, {"rank": obs.rank})
                last_printed_turn = obs.turn
            desc = policy.choose(env.game, env.agent_hero)
            if desc is None:
                action = CandidateAction(kind=ActionKind.END_TURN.value)
            else:
                action = desc.to_candidate()
        is_end_turn = action.kind == ActionKind.END_TURN.value
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        if is_end_turn or terminated or truncated:
            combat = info.get("combat") or {}
            print(f"    -> combat: dealt={combat.get('dealt', 0)} "
                  f"taken={combat.get('taken', 0)} "
                  f"won={combat.get('won', 0)} lost={combat.get('lost', 0)} "
                  f"| reward={reward:+.4f}")
        if terminated or truncated:
            if obs.turn != last_printed_turn:
                print_turn(obs, info)
                last_printed_turn = obs.turn
            break
        if steps > 20000:                                # 防御性护栏
            print("!! step cap 20000 reached, stop")
            break
    elapsed = time.perf_counter() - t_run
    total_elapsed = time.perf_counter() - t_start

    print("-" * 78)
    print(f"episode end: {'TERMINATED' if terminated else 'TRUNCATED'} "
          f"reason={info.get('terminated_reason', '')}")
    print(f"final rank={info.get('rank')} / {args.players} | "
          f"health={info.get('health')} | alive={info.get('alive_count')}")
    print(f"steps={steps} | turns={info.get('turn')} | "
          f"total_reward={total_reward:+.4f}")
    print(f"elapsed: game {elapsed * 1000:.1f} ms "
          f"(avg {elapsed / max(1, steps) * 1000:.2f} ms/step) | "
          f"with reset {total_elapsed * 1000:.1f} ms")
    stats = env.stats
    print(f"engine_errors={stats['engine_errors']} "
          f"choice_errors={stats['choice_errors']} "
          f"opponent_rejects={stats['opponent_rejects']} "
          f"invalid={stats['invalid']}")
    env.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
