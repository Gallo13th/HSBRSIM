"""经济类 Action。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.queue import Action

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


class GainGold(Action):
    """英雄获得金币。hero.gold setter 已执行 99 持有上限与 max(0,·)
    （RULES §1.4）。"""

    def __init__(self, hero: "Hero", amount: int) -> None:
        self.hero = hero
        self.amount = amount

    def do(self, game: "Game") -> None:
        self.hero.gold += self.amount


class ScheduleNextTurn(Action):
    """效果推迟到 hero 下一个招募阶段开始执行
    （game.defer_until_next_turn）。"""

    def __init__(self, hero: "Hero", action: Action) -> None:
        self.hero = hero
        self.action = action

    def do(self, game: "Game") -> None:
        game.defer_until_next_turn(self.hero, self.action)
