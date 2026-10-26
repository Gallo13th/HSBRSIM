"""GameRNG — 全部随机性走 game.rng，可 seed 可回放。

规则: 引擎与脚本禁止 import random / 使用模块级随机源。
任何随机决策都必须通过 game.rng.*，否则回放断裂。

审计日志（F-28 / READINESS D-6）: 每个带 label 的随机决策记录一条
``(label, repr(choice))`` 到 ``decisions``，供回放比对（tools/probe_*、
`hsbg/planning/rng.py` 依赖默认开启）。单局约 1.3k 条、<0.2 MB，对吞吐
无显著影响；RL 大批量 rollout 可传 ``audit=False`` 关闭，或用
``clear_decisions()`` 周期清理（两者都不改变随机流）。
"""

from __future__ import annotations

import random
from typing import Any, List, Sequence, TypeVar

T = TypeVar("T")


class GameRNG:
    """薄封装 random.Random，便于记录决策日志做确定性回放。"""

    def __init__(self, seed: int | None = None, *, audit: bool = True) -> None:
        self.seed_value = seed
        self._rng = random.Random(seed)
        # 审计开关: 默认 True = 既有行为（decisions 持续记录）。关闭后
        # 随机流完全不变，仅不再追加审计条目（D-6 的"可关/可清"能力）。
        self.audit: bool = bool(audit)
        self.decisions: List[tuple] = []   # (label, choice) 审计日志

    def _record(self, label: str, value: Any) -> None:
        if self.audit and label:
            self.decisions.append((label, value))

    def clear_decisions(self) -> None:
        """清空审计日志（不改变随机流状态；F-28/D-6）。"""
        self.decisions.clear()

    def choice(self, seq: Sequence[T], label: str = "") -> T:
        if not seq:
            raise ValueError("rng.choice on empty sequence")
        pick = self._rng.choice(seq)
        self._record(label, repr(pick)[:80])
        return pick

    def sample(self, seq: Sequence[T], k: int, label: str = "") -> List[T]:
        picks = self._rng.sample(seq, k)
        self._record(label, repr(picks)[:80])
        return picks

    def shuffle(self, lst: List[Any], label: str = "") -> None:
        self._rng.shuffle(lst)
        self._record(label, f"n={len(lst)}")

    def random(self) -> float:
        return self._rng.random()

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)
