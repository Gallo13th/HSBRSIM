"""脚本对手 / 启发式教师（``docs/ENV_SPEC.md`` §6）。

公开入口::

    from hsbg.agents import make_opponent, OpponentPolicy, EnvContext

    policy = make_opponent("heuristic")
    desc = policy.choose(game, hero, EnvContext(game=game))
    if desc is None:
        ...  # 结束招募阶段
"""

from __future__ import annotations

from hsbg.agents.base import (EnvContext, OpponentPolicy,
                             choose_option_index)
from hsbg.agents.heuristic import HeuristicPolicy, TeacherPolicy
from hsbg.agents.random_agent import RandomPolicy
from hsbg.agents.registry import (  # noqa: F401
    OPPONENT_NAMES,
    build_opponents,
    make_opponent,
)

__all__ = [
    "OpponentPolicy",
    "EnvContext",
    "choose_option_index",
    "RandomPolicy",
    "HeuristicPolicy",
    "TeacherPolicy",
    "make_opponent",
    "build_opponents",
    "OPPONENT_NAMES",
]
