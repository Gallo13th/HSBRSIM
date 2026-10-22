"""Spell — 酒馆法术 / 血宝石 / Dark Gift / Lockbox 等非随从牌。"""

from __future__ import annotations

from hsrl2.entity import Entity
from hsrl2.tags import CardType


class Spell(Entity):
    def __init__(self, card_id: str, name: str = "", *, cost: int = 0):
        super().__init__(card_id, name, card_type=CardType.SPELL)
        from hsrl2.tags import GameTag
        self.set(GameTag.COST, cost)
