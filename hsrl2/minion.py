"""Minion — 战棋随从实体（含 Activate / Venomous 状态）。"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from hsrl2.entity import Buff, Entity
from hsrl2.tags import CardType, GameTag, Race, race_set

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


class Minion(Entity):
    def __init__(self, card_id: str, name: str = "", *,
                 atk: int = 0, health: int = 0,
                 race: Race = Race.NONE, tech_level: int = 0,
                 races: Optional[frozenset] = None):
        super().__init__(card_id, name, card_type=CardType.MINION)
        self.set(GameTag.BASE_ATK, atk)
        self.set(GameTag.BASE_HEALTH, health)
        self.set(GameTag.HEALTH, health)
        self.set(GameTag.RACE, race)
        # 类型身份集合（AC-3: CARDRACE ∪ per-race tag）。未显式给出时
        # 由主类型单值推导（`race_set` 负责 ALL → 全 10 族展开）。
        self.set(GameTag.RACES, frozenset(races) if races is not None
                 else race_set(race))
        self.set(GameTag.TECH_LEVEL, tech_level or 1)   # token 默认 T1（伤害公式）

    def set(self, tag, value) -> None:
        """tag 写入 — 写 `GameTag.RACE` 时同步身份集合。

        兼容契约: 旧调用方/测试直接 `set(GameTag.RACE, X)` 表达"该随从
        现在是 X 类型"（单值语义）。此时 `GameTag.RACES`（多类型身份）
        必须同步重置为 `race_set(X)`，否则身份集合会保留旧的额外类型，
        形成"主类型与身份不一致"的静默第三态。多类型身份请显式写
        `GameTag.RACES`（`create_minion` 由 `CardDef.races` 写入）。
        """
        super().set(tag, value)
        if tag == GameTag.RACE:
            super().set(GameTag.RACES, race_set(Race(value)))

    # ── 关键词视图 ──

    @property
    def race(self) -> Race:
        """**主类型**（`CARDRACE` 单值视图; 兼容既有调用方）。

        多类型身份请用 `races`（集合）/ `has_race(want)`——单值视图对
        双类型随从只给出 CARDRACE 主类型（AC-3）。
        """
        return Race(self.get(GameTag.RACE, Race.NONE))

    @property
    def races(self) -> frozenset:
        """**类型身份集合**（含 owner 家族类型改写读取点）。

        权威: wiki `Multi-type minion`（revid 855346）"Multi-types are
        always additions, never exclusions."；`Minion`（revid 817925）
        "these minions benefit from the effects of both types"。

        读取点语义:
          - 基础集 = `GameTag.RACES`（create_minion 由 `CardDef.races`
            写入; 绝不含 ALL/NONE）;
          - **家族类型改写**（Portrait 族 "Your X are both A and B" /
            "have all minion types"）: 若该实体的 owner 持有对应家族的
            改写规则（`Game.family_races`），则**覆写**为规则集合。
            作用域 = owner 视角（warband/手牌/酒馆均生效）——825 的
            official Dev Comment（Patch 30.2.0.205267，wiki revid 814123）
            "This applies to Whelp Smugglers you see in the Tavern or
            Discover as well, not just the ones in your warband."；
            对手实体（controller 不同）不生效。
        """
        base = self.get(GameTag.RACES, None)
        base = frozenset(base) if base is not None else race_set(self.race)
        hero = getattr(self, "controller", None)
        game = getattr(self, "game", None)
        if hero is not None and game is not None:
            override = game.family_races(hero, self.card_id)
            if override is not None:
                # **并集而非替换**（wiki `Multi-type minion` revid 855346:
                # "Multi-types are always additions, never exclusions."）——
                # 家族改写只**增加**类型; 若写成替换, 会使 Incubation
                # Mutation（`_notype_is_all`）授予的全类型被 Portrait
                # **削减**为 1-2 类（第四轮对抗验证 F1 实测）。
                return base | override
        return base

    def has_race(self, want: Race) -> bool:
        """该实例是否具有种族 `want`（集合语义: `want in races`）。

        替代旧的"单值 == want 或 == ALL"读法——`Race.ALL` 已在
        `races` 中展开为全 10 族，故 ALL 随从对任何标准种族返回 True，
        无类型随从对任何种族返回 False（wiki `All` revid 893299 /
        `Minion` revid 817925）。
        """
        return Race(want) in self.races

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
        """战斗开始: 重置 Venomous（S14 每场重置）、圣盾击打计数、
        Avenge 计数（RULES §6.11——Avenge 只统计**本场**战斗的友方死亡，
        不得跨战斗累积; 2026-09-01 修复）。"""
        self.clear(GameTag.VENOMOUS_CONSUMED)
        self.clear(GameTag.SHIELD_HITS_TAKEN)
        self.clear(GameTag.AVENGE_COUNTER)

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
            # 破盾事件（RULES §6.2; 2026-09-02 对抗审查 CRITICAL: 真实
            # 伤害路径此前静默 clear → "After a friendly minion loses
            # Divine Shield" 族（BG32_MagicItem_171 Divine Signet /
            # BG30_MagicItem_910 Mechagon Adapter）成为死监听）。
            # 与 `actions/stats.py::LoseKeyword` 同口径: 先
            # `keyword_lost` 再 `divine_shield_lost`。战斗内由
            # CombatScheduler 的事件快照恢复机制一并保护。
            g = getattr(self, "game", None)
            if g is not None:
                from hsrl2.events import DIVINE_SHIELD_LOST, KEYWORD_LOST
                g.events.fire(g, KEYWORD_LOST, minion=self,
                              tag=GameTag.DIVINE_SHIELD)
                g.events.fire(g, DIVINE_SHIELD_LOST, minion=self)
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
        """复生/分裂/战斗前快照用: 保留 buff/关键词/金色的完整状态副本。

        2026-10-18 修复（ENGINE_NOTES F-01）: tags 中的**实体引用类值**
        （`GameTag.KILLER` = 击杀者 Entity）不得 deepcopy —— 深拷贝会把
        整张 Game 对象图拉进快照（实测整局 7.2×、ERP 11×、内存 98×），
        且战斗结束 `restore_state` 后 KILLER 指向**克隆实体**污染
        "由击杀者触发"类读取点。口径与 `game._frozen_clone` 一致:
        实体引用类值直接丢弃（KILLER 本身是战斗内瞬态，快照复原后
        不应保留）。
        """
        import copy
        tags: dict = {}
        for tag, value in self.tags.items():
            if isinstance(value, Entity):
                continue
            tags[tag] = copy.deepcopy(value)
        return {
            "tags": tags,
            "buffs": list(self._buffs),
        }

    def restore_state(self, snap: dict) -> None:
        self.tags = dict(snap["tags"])
        self._buffs = list(snap["buffs"])
