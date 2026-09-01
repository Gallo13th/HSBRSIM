"""召唤类 Action。"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from hsrl2.queue import Action
from hsrl2.tags import GameTag

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.minion import Minion


class Summon(Action):
    """创建并召唤随从（token 语义: create_minion 不经过池，不占池副本）。

    满场由 game.summon 处理（fire "minion_overflow" 后返回 False），
    本 Action 不吞该信号。
    """

    def __init__(self, hero: "Hero", card_id: str,
                 position: Optional[int] = None) -> None:
        self.hero = hero
        self.card_id = card_id
        self.position = position

    def do(self, game: "Game") -> None:
        m = game.create_minion(self.card_id, controller=self.hero)
        game.summon(self.hero, m, self.position)


class SummonPlainCopy(Action):
    """召唤 source 的 plain copy（官方用语: 无附魔的复制）。

    - 金色 source → 金色 copy（TRIPLE_BASE_CARD_ID 定位基础卡后按金色
      卡定义创建）
    - 不带 source 的任何 buff/受击状态——纯白板
    - 召唤到 source.controller 棋盘（满场同样由 game.summon 处理）
    """

    def __init__(self, minion: "Minion",
                 position: Optional[int] = None) -> None:
        self.minion = minion
        self.position = position

    def do(self, game: "Game") -> None:
        source = self.minion
        if source.is_golden:
            base_id = (source.get(GameTag.TRIPLE_BASE_CARD_ID, None)
                       or source.card_id)
            copy = game.create_minion(base_id, controller=source.controller,
                                      golden=True)
        else:
            copy = game.create_minion(source.card_id,
                                      controller=source.controller)
        game.summon(source.controller, copy, self.position)
