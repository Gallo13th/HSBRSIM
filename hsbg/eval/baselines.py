"""基线策略：随机 / 首个合法 / 贪心启发式（评测对照用）。"""

from __future__ import annotations

import random
from typing import Any, Optional

from hsbg.env.spec import ActionKind, Observation


class RandomPolicy:
    """在合法候选中均匀随机（有 ``end_turn`` 时不优先选它）。"""

    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    def __call__(self, obs: Observation, rng: Optional[random.Random] = None):
        if not obs.candidates:
            return 0
        rng = rng or self._rng
        return rng.randrange(len(obs.candidates))


class FirstLegalPolicy:
    """总是选第一个候选（通常是最左的买/卖）。"""

    name = "first"

    def __call__(self, obs: Observation, rng=None):
        return 0


class EndTurnPolicy:
    """优先 end_turn（用于测环境最小闭环/回合推进）。"""

    name = "end_turn"

    def __call__(self, obs: Observation, rng=None):
        for i, c in enumerate(obs.candidates):
            if c.kind == ActionKind.END_TURN.value:
                return i
        return 0


def make_baseline(name: str, **kwargs: Any):
    if name == "random":
        return RandomPolicy(**kwargs)
    if name == "first":
        return FirstLegalPolicy()
    if name == "end_turn":
        return EndTurnPolicy()
    raise ValueError(f"unknown baseline: {name!r}")
