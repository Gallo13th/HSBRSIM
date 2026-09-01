"""Action 队列 — 波次结算，防死循环采用**报错**而非静默截断。

旧引擎教训: _MAX_DEATH_WAVES/_MAX_ACTIONS 超限时静默 return，
复杂亡语链被截断后状态损坏且无法排查。v2 超限抛 CombatLoopError。
"""

from __future__ import annotations

from typing import Callable, List, Optional, TYPE_CHECKING

import hsrl2.constants as C

if TYPE_CHECKING:
    from hsrl2.game import Game


class CombatLoopError(RuntimeError):
    """战斗/队列超出保护上限 — 引擎 bug 或死循环脚本。"""


class Action:
    """状态变更原子。do(game) 执行；可 enqueue 子动作。"""

    def do(self, game: "Game") -> None:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"


class ActionQueue:
    def __init__(self) -> None:
        self._queue: List[Action] = []
        self._resolving = False

    def enqueue(self, action: Action) -> None:
        self._queue.append(action)

    def enqueue_all(self, actions) -> None:
        for a in actions or []:
            self._queue.append(a)

    @property
    def pending(self) -> int:
        return len(self._queue)

    def resolve(self, game: "Game") -> None:
        """FIFO 执行全部动作；每个动作后触发死亡检查波次。"""
        if self._resolving:
            return  # 嵌套调用直接返回（由外层统一驱动）
        self._resolving = True
        executed = 0
        try:
            while self._queue:
                action = self._queue.pop(0)
                action.do(game)
                executed += 1
                if executed > C.QUEUE_MAX_ACTIONS:
                    raise CombatLoopError(
                        f"queue exceeded {C.QUEUE_MAX_ACTIONS} actions")
                game.check_deaths()
        finally:
            self._resolving = False
