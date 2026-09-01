"""Minion — 战棋随从实体（含 Activate / Venomous 状态）。"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from hsrl2.entity import Buff, Entity
from hsrl2.tags import CardType, GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


class Minion(Entity):
    def __init__(self, card_id: str, name: str = "", *,
                 atk: int = 0, health: int = 0,
                 race: Race = Race.NONE, tech_level: int = 0):
        super().__init__(card_id, name, card_type=CardType.MINION)
        self.set(GameTag.BASE_ATK, atk)
        self.set(GameTag.BASE_HEALTH, health)
        self.set(GameTag.HEALTH, health)
        self.set(GameTag.RACE, race)
        self.set(GameTag.TECH_LEVEL, tech_level or 1)   # token 默认 T1（伤害公式）

    # ── 关键词视图 ──

    @property
    def race(self) -> Race:
        return Race(self.get(GameTag.RACE, Race.NONE))

    @property
    def tech_level(self) -> int:
        return self.get(GameTag.TECH_LEVEL, 1)

    @property
    def taunt(self) -> bool:
        return self.has(GameTag.TAUNT)

    @property
    def divine_shield(self) -> bool:
        return self.has(GameTag.DIVINE_SHIELD)

    @property
    def poisonous(self) -> bool:
        return self.has(GameTag.POISONOUS)

    @property
    def venomous_active(self) -> bool:
        """S14: Venomous 每场战斗重置 — 未消耗即生效。"""
        return self.has(GameTag.VENOMOUS) and not self.has(GameTag.VENOMOUS_CONSUMED)

    @property
    def reborn(self) -> bool:
        return self.has(GameTag.REBORN)

    @property
    def windfury(self) -> bool:
        return self.has(GameTag.WINDFURY)

    @property
    def cleave(self) -> bool:
        return self.has(GameTag.CLEAVE)

    @property
    def is_golden(self) -> bool:
        return self.has(GameTag.GOLDEN)

    @property
    def exhausted(self) -> bool:
        return self.has(GameTag.EXHAUSTED)

    # ── 战斗攻击能力（调度器查询） ──

    def can_attack(self) -> bool:
        """存活且攻>0。攻击轮转由调度器游标管理——真实规则中随从
        在一轮内攻击后，待本方其他随从各攻击一次后可再次攻击
        （修复 v1 "每场只攻击一次" 的重大规则错误）。"""
        return not self.dead and self.atk > 0

    def reset_for_combat(self) -> None:
        """战斗开始: 重置 Venomous（S14 每场重置）与圣盾击打计数。"""
        self.clear(GameTag.VENOMOUS_CONSUMED)
        self.clear(GameTag.SHIELD_HITS_TAKEN)

    # ── 伤害 ──

    def take_damage(self, amount: int, source: Optional["Minion"] = None) -> int:
        """结算伤害。返回**实际造成的**伤害（0 = 被圣盾抵消/无效）。

        规则 (RULES §6.2/§6.3):
          - 圣盾完全抵消第一次伤害实例，返回 0 → 剧毒不触发
          - actual_damage > 0 才算造成伤害
        """
        if amount <= 0 or self.dead:
            return 0
        # 圣盾（Toreth's Blessing: 需 N 次击破）
        if self.has(GameTag.DIVINE_SHIELD):
            hits_needed = max(1, self.get(GameTag.DIVINE_SHIELD_HITS, 1))
            hits_taken = self.get(GameTag.SHIELD_HITS_TAKEN, 0) + 1
            self.set(GameTag.SHIELD_HITS_TAKEN, hits_taken)
            if hits_taken < hits_needed:
                return 0    # 盾未破
            self.clear(GameTag.DIVINE_SHIELD)
            self.clear(GameTag.SHIELD_HITS_TAKEN)
            return 0        # 盾破但仍抵消本次伤害
        self.health = self.health - amount
        if source is not None:
            self.set(GameTag.KILLER, source)
        return amount

    # ── 亡语/复生上下文 ──

    @property
    def zone_position(self) -> int:
        return self.get(GameTag.ZONE_POSITION, 0)

    def snapshot_state(self) -> dict:
        """复生/分裂用: 保留 buff/关键词/金色的完整状态副本。"""
        import copy
        return {
            "tags": copy.deepcopy(self.tags),
            "buffs": [b for b in self._buffs],
        }

    def restore_state(self, snap: dict) -> None:
        self.tags = dict(snap["tags"])
        self._buffs = list(snap["buffs"])
