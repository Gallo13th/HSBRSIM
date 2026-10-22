"""搜索用 checkpoint / push-pop 接口（clone 之上，不改引擎）。

引擎 `Game` 没有 restore API；AlphaZero 的树搜索需要“回到某节点”。本模块
用 **clone 快照**实现：

- :func:`push_checkpoint(game)` → :class:`Checkpoint`（= ``clone(game)`` 快照）；
- :func:`pop_checkpoint(checkpoint)` → **新的独立 Game**（再 clone 一次快照）；

为什么 pop 还要 clone：快照可能被多次恢复/继续展开，返回共享对象会被后续
search 分支污染；两个 clone 成本在 Phase1 预算内（N≤32 macro 仍可用）。
若未来引擎提供 in-place restore（`set_state`），可在此替换实现且保持 API。

成本：push ≈ clone（8p T2 ~1.2–1.5ms、T4 ~1.8–2.3ms）；pop ≈ clone。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hsrl2.game import Game

from hsbg.planning.model import clone

__all__ = [
    "Checkpoint",
    "push_checkpoint",
    "pop_checkpoint",
    "CheckpointStack",
]


@dataclass
class Checkpoint:
    """一个不可变快照（内部 Game 不再被外部直接推进）。"""

    game: Game
    label: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def turn(self) -> int:
        return int(getattr(self.game, "turn", 0))

    def restore(self) -> Game:
        """返回快照的独立副本（可安全继续搜索/推进）。"""
        return pop_checkpoint(self)


def push_checkpoint(game: Game, *, label: str = "",
                    meta: Optional[Dict[str, Any]] = None) -> Checkpoint:
    """保存当前局面快照（clone；O(clone)）。"""
    if game is None:
        raise ValueError("push_checkpoint(None)")
    return Checkpoint(game=clone(game), label=label, meta=dict(meta or {}))


def pop_checkpoint(checkpoint: Checkpoint) -> Game:
    """从快照恢复出**独立** Game（再 clone；不修改快照本身）。"""
    if not isinstance(checkpoint, Checkpoint):
        raise TypeError("pop_checkpoint expects Checkpoint")
    return clone(checkpoint.game)


class CheckpointStack:
    """LIFO 快照栈（用于 DFS/MCTS 回溯）。

    用法::

        stack = CheckpointStack(game)
        stack.push()          # 保存根
        game2 = model.clone(game); ...  # 展开/推进
        game = stack.pop()    # 回到根（独立副本）

    注意：本类不持有"当前 game"的推送语义——每次 push 保存的是**传入时**
    （构造或 ``push(game)`` 参数）的局面；restore 返回独立副本。
    """

    def __init__(self, game: Optional[Game] = None):
        self.game = game
        self._stack: List[Checkpoint] = []

    def push(self, game: Optional[Game] = None, *,
             label: str = "") -> Checkpoint:
        target = game if game is not None else self.game
        if target is None:
            raise ValueError("CheckpointStack.push: 没有 game")
        if game is not None:
            self.game = game
        cp = push_checkpoint(target, label=label)
        self._stack.append(cp)
        return cp

    def pop(self) -> Game:
        if not self._stack:
            raise IndexError("CheckpointStack.pop: empty")
        cp = self._stack.pop()
        self.game = pop_checkpoint(cp)
        return self.game

    def peek(self) -> Optional[Checkpoint]:
        return self._stack[-1] if self._stack else None

    def __len__(self) -> int:
        return len(self._stack)

    @property
    def depth(self) -> int:
        return len(self._stack)
