"""Hero — 战棋玩家英雄（金币/护甲/酒馆等级/手牌/棋盘/酒馆展示）。"""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

import hsrl2.constants as C
from hsrl2.entity import Entity
from hsrl2.events import Listener
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import CardType, GameTag, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game


class Hero(Entity):
    def __init__(self, card_id: str, name: str = "", *,
                 base_health: int = C.HERO_BASE_HEALTH, armor: int = 0):
        super().__init__(card_id, name, card_type=CardType.HERO)
        self.set(GameTag.HEALTH2, base_health)
        self.set(GameTag.ARMOR, armor)
        self.set(GameTag.TAVERN_TIER, 1)
        self.set(GameTag.UPGRADE_COST, C.BASE_UPGRADE_COSTS[2])
        self.set(GameTag.GOLD, 0)
        # 区域容器
        self.board: List[Minion] = []
        self.hand: List[Entity] = []
        self.tavern: List[Entity] = []
        self.graveyard: List[Entity] = []
        self.trinkets: List[Entity] = []

    # ── 属性 ──

    @property
    def health(self) -> int:
        return self.get(GameTag.HEALTH2, 0)

    @health.setter
    def health(self, value: int) -> None:
        self.set(GameTag.HEALTH2, max(0, value))

    @property
    def armor(self) -> int:
        return self.get(GameTag.ARMOR, 0)

    @armor.setter
    def armor(self, value: int) -> None:
        self.set(GameTag.ARMOR, max(0, value))

    @property
    def gold(self) -> int:
        return self.get(GameTag.GOLD, 0)

    @gold.setter
    def gold(self, value: int) -> None:
        """回合内收入可超过基础量，持有上限 99（RULES §1.4）。"""
        self.set(GameTag.GOLD, min(max(0, value), C.GOLD_HOLD_CAP))

    @property
    def tavern_tier(self) -> int:
        return self.get(GameTag.TAVERN_TIER, 1)

    @property
    def upgrade_cost(self) -> int:
        return self.get(GameTag.UPGRADE_COST, C.BASE_UPGRADE_COSTS[2])

    @property
    def is_alive(self) -> bool:
        return self.health + self.armor > 0

    @property
    def frozen_tavern(self) -> bool:
        return self.has(GameTag.FROZEN)

    @property
    def income_cap(self) -> int:
        """每回合基础收入上限（默认 10; Strike Oil 类效果递增）。"""
        return C.GOLD_INCOME_CAP + self.get(GameTag.INCOME_CAP_BONUS, 0)

    # ── 伤害（先护甲后生命, RULES §1.3）──

    def take_damage(self, amount: int) -> int:
        if amount <= 0:
            return 0
        health_before = self.health
        armor_before = self.armor
        absorbed_by_armor = min(self.armor, amount)
        self.armor = self.armor - absorbed_by_armor
        remaining = amount - absorbed_by_armor
        if remaining > 0:
            self.health = self.health - remaining
        # 英雄受伤事件（护甲吸收也算受伤 — 官方 Floating Watcher 语义;
        # 携带伤害前生命/护甲——Rewind 类效果（Soul Rewinder）据以
        # 全量回溯该伤害实例，含护甲部分）
        if self.game is not None:
            from hsrl2.events import HERO_DAMAGE_TAKEN
            self.game.events.fire(self.game, HERO_DAMAGE_TAKEN,
                                  hero=self, amount=amount,
                                  health_before=health_before,
                                  armor_before=armor_before)
        return amount

    # ── 棋盘辅助 ──

    def living_minions(self) -> List[Minion]:
        return [m for m in self.board if not m.dead]

    def board_full(self) -> bool:
        return len(self.board) >= C.BOARD_SIZE

    def hand_full(self) -> bool:
        return len(self.hand) >= C.HAND_SIZE

    def add_to_hand(self, entity: Entity) -> bool:
        """满手牌返回 False — 调用方决定排队等待或丢弃（RULES §3.3: 等待）。

        入手钩子: on_enter_hand（Bream Counter 手牌联动 / Aureate
        Laureate 恒金 / Search Through Time 锁定类效果的触发点）。
        """
        if self.hand_full():
            return False
        entity.zone = Zone.HAND
        self.hand.append(entity)
        if self.game is not None:
            self.game.run_script_hook(entity, "on_enter_hand")
        return True
