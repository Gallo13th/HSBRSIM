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
        """FIFO 执行全部动作；每个动作后触发死亡检查波次。

        行动来源作用域（`game._action_source`）: 队列结算期间该属性指向
        **当前正在执行的 Action 的来源实体**。解析顺序（**逐 Action 独立
        解析**——每个动作开始前先复位到调用方作用域）:
          1. 动作**显式声明**的 `source`（`Buff(source=...)`——优先）
          2. 否则**继承调用方作用域**（`Game.run_script_hook` 把正在执行
             钩子的实体置为 `_action_source`）——脚本返回的 `Buff` 未声明
             `source` 时，来源即"本次钩子的施动实体"
          3. 两者皆无 → 调用方作用域本身的值（可能为 None = 来源不明）
        **逐迭代复位（2026-09-20 修复）**: 循环每次迭代把
        `_action_source` 复位为 `prev_source` 再套用本动作的显式
        `source`——否则一个**未声明来源**的动作会继承**上一个动作**的
        `source`（对抗验证实测: `[Buff(dummy, source=ship), Buff(ship)]`
        的第二个 buff 被错误归属给 `ship`），与"继承调用方作用域"矛盾
        （上一个动作不是调用方）。`prev_source` 只在 resolve 入口记录、
        `finally` 恢复——支持嵌套（`run_actions` 会在监听器回调内重入，
        返回后外层来源复原）。
        `Entity.add_buff` 据此填充 `stats_gained` 的 `source` 载荷
        （BG21_018 "from other sources" / BG31_820 "another friendly
        Pirate" / BG26_966 "a different friendly Dragon" 的排除依据;
        ENGINE_BACKLOG §E D7）。
        """
        if self._resolving:
            return  # 嵌套调用直接返回（由外层统一驱动）
        self._resolving = True
        executed = 0
        prev_source = getattr(game, "_action_source", None)
        try:
            while self._queue:
                action = self._queue.pop(0)
                # 逐动作复位: 未声明 source 的动作只继承**调用方作用域**
                # （prev_source），不继承**上一个动作**的 source。
                game._action_source = prev_source
                if getattr(action, "source", None) is not None:
                    game._action_source = action.source
                action.do(game)
                executed += 1
                if executed > C.QUEUE_MAX_ACTIONS:
                    raise CombatLoopError(
                        f"queue exceeded {C.QUEUE_MAX_ACTIONS} actions")
                game.check_deaths()
        finally:
            game._action_source = prev_source
            self._resolving = False
