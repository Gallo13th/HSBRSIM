"""GameRNG — 全部随机性走 game.rng，可 seed 可回放。

规则: 引擎与脚本禁止 import random / 使用模块级随机源。
任何随机决策都必须通过 game.rng.*，否则回放断裂。
"""

from __future__ import annotations

import random
from typing import Any, List, Sequence, TypeVar

T = TypeVar("T")


class GameRNG:
    """薄封装 random.Random，便于未来记录决策日志做确定性回放。"""

    def __init__(self, seed: int | None = None) -> None:
        self.seed_value = seed
        self._rng = random.Random(seed)
        self.decisions: List[tuple] = []   # (label, choice) 审计日志

    def choice(self, seq: Sequence[T], label: str = "") -> T:
        if not seq:
            raise ValueError("rng.choice on empty sequence")
        pick = self._rng.choice(seq)
        if label:
            self.decisions.append((label, repr(pick)[:80]))
        return pick

    def sample(self, seq: Sequence[T], k: int, label: str = "") -> List[T]:
        picks = self._rng.sample(seq, k)
        if label:
            self.decisions.append((label, repr(picks)[:80]))
        return picks

    def shuffle(self, lst: List[Any], label: str = "") -> None:
        self._rng.shuffle(lst)
        if label:
            self.decisions.append((label, f"n={len(lst)}"))

    def random(self) -> float:
        return self._rng.random()

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)
