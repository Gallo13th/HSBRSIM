"""对手策略注册表：``make_opponent(name, **kwargs) -> OpponentPolicy``。

内置:

- ``random``     : 随机合法动作（冒烟/基线）
- ``heuristic``  : 贪心买/打/升级/刷新（默认对手）
- ``teacher``    : 更强的启发式（BC 教师；当前与 heuristic 同实现，
                   后续可接入搜索/学习策略）
"""

from __future__ import annotations

from typing import Any, List

from hsbg.agents.base import EnvContext, OpponentPolicy
from hsbg.agents.heuristic import HeuristicPolicy, TeacherPolicy
from hsbg.agents.random_agent import RandomPolicy

__all__ = ["make_opponent", "build_opponents", "OPPONENT_NAMES",
           "EnvContext", "OpponentPolicy"]

OPPONENT_NAMES = ("random", "heuristic", "teacher")


def make_opponent(name: Any = "heuristic", **kwargs: Any) -> OpponentPolicy:
    """按名字创建对手策略实例。

    ``name`` 也接受一个工厂（``callable``），便于测试/外部注入自定义策略。
    """
    if name is None:
        name = "heuristic"
    if callable(name):
        return name(**kwargs)
    key = str(name).strip().lower()
    if key == "random":
        return RandomPolicy(**kwargs)
    if key in ("heuristic", "heuristic_v1", "greedy"):
        return HeuristicPolicy(**kwargs)
    if key in ("teacher", "bc_teacher"):
        return TeacherPolicy(**kwargs)
    raise ValueError(f"unknown opponent {name!r}; expected one of "
                     f"{OPPONENT_NAMES} or a callable factory")


def build_opponents(name: Any, count: int, **kwargs: Any
                    ) -> List[OpponentPolicy]:
    """为 ``count`` 名对手各建一个独立实例（含每英雄内部状态）。"""
    return [make_opponent(name, **kwargs) for _ in range(max(0, int(count)))]
