"""随机对手 —— 只枚举合法动作并随机选一个（冒烟/基线用）。

随机源固定走 ``game.rng``（AGENTS §3：新增代码禁止 ``import random``），
因此同一 seed 的对局完全可复现。
"""

from __future__ import annotations

from typing import Any, Optional

from hsbg.env import driver
from hsbg.env.spec import ActionKind


class RandomPolicy:
    """随机合法动作策略。"""

    name = "random"

    def __init__(self, *, end_turn_prob: float = 0.10,
                 prefer_playables: bool = True) -> None:
        self.end_turn_prob = float(end_turn_prob)
        self.prefer_playables = bool(prefer_playables)

    def choose(self, game: Any, hero: Any, ctx: Any = None
               ) -> Optional[driver.ActionDescriptor]:
        if not hero.is_alive:
            return None
        zones = getattr(ctx, "zones", None) if ctx is not None else None
        try:
            descriptors = driver.enumerate_actions(game, hero, zones)
        except Exception:                                 # noqa: BLE001
            return None
        actions = [d for d in descriptors
                   if d.kind != ActionKind.END_TURN.value]
        if not actions:
            return None
        if game.rng.random() < self.end_turn_prob:
            return None
        return game.rng.choice(actions, label="random_agent_action")
