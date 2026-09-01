"""Entity — 一切游戏对象的基类。

设计约束（吸取旧引擎教训）:
  - 所有可见状态进 tags；buff 堆叠进 _buffs
  - 脚本钩子统一签名 (source, game, ctx) -> Action | list[Action] | None
  - ctx 携带上下文（攻击目标、击杀者等），废除旧引擎的 game._last_attack_target 全局
  - 监听器随实体离场自动注销（光环生命周期）
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from hsrl2.tags import CardType, GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


class Buff:
    """附魔。temporary=True 的 buff 在战斗结束清除。

    gem=True 标记血宝石来源 buff（Gem Confiscation "steals all Blood
    Gems" 移转语义的数据源——不依赖数值比对）。
    """

    __slots__ = ("atk", "health", "temporary", "source_id", "dark_gift",
                 "gem")

    def __init__(self, atk: int = 0, health: int = 0, *,
                 temporary: bool = False, source_id: str = "",
                 dark_gift: str | None = None, gem: bool = False):
        self.atk = atk
        self.health = health
        self.temporary = temporary
        self.source_id = source_id        # 来源卡牌 id（审计用）
        self.dark_gift = dark_gift        # Dark Gift 附魔名
        self.gem = gem

    def __repr__(self) -> str:
        t = " (temp)" if self.temporary else ""
        g = " (gem)" if self.gem else ""
        return f"<Buff +{self.atk}/+{self.health}{t}{g}>"


class Entity:
    """tags 保存全部可见状态；typed 属性只是 tags 的视图。"""

    def __init__(self, card_id: str, name: str = "", *,
                 card_type: CardType = CardType.MINION):
        self.uuid: str = uuid.uuid4().hex[:12]
        self.card_id = card_id
        self.game: Optional["Game"] = None
        self.controller: Optional["Hero"] = None
        self.tags: Dict[GameTag, Any] = {}
        self._buffs: List[Buff] = []
        self.scripts: Any = None            # 脚本类（由 scripts/registry 绑定）
        self._script_overrides: Dict[str, Any] = {}
        self.tags[GameTag.CARD_ID] = card_id
        self.tags[GameTag.NAME] = name
        self.tags[GameTag.CARDTYPE] = card_type
        self.tags[GameTag.ZONE] = Zone.INVALID

    # ── tag 存取 ──

    def get(self, tag: GameTag, default: Any = 0) -> Any:
        return self.tags.get(tag, default)

    def set(self, tag: GameTag, value: Any) -> None:
        self.tags[tag] = value

    def has(self, tag: GameTag) -> bool:
        return bool(self.tags.get(tag, False))

    def clear(self, tag: GameTag) -> None:
        self.tags.pop(tag, None)

    # ── 通用属性 ──

    @property
    def zone(self) -> Zone:
        return Zone(self.get(GameTag.ZONE, Zone.INVALID))

    @zone.setter
    def zone(self, value: Zone) -> None:
        self.set(GameTag.ZONE, value)

    @property
    def name(self) -> str:
        return self.get(GameTag.NAME, "")

    @property
    def dead(self) -> bool:
        return self.has(GameTag.DEAD) or self.get(GameTag.HEALTH, 0) <= 0

    # ── 数值（base + buffs；光环由子类扩展） ──

    @property
    def atk(self) -> int:
        total = self.get(GameTag.BASE_ATK, 0)
        for b in self._buffs:
            total += b.atk
        total += self._aura_atk()
        # 动态属性脚本钩子: "Has +X for each Y" 家族（Falling Sky Golem
        # 等 wherever-this-is 静态读数）——脚本返回 int 覆盖或 None 回落
        if self.scripts is not None and not self.has(GameTag.SILENCED):
            atk_fn = getattr(self.scripts, "atk", None)
            if callable(atk_fn):
                result = atk_fn(self)
                if result is not None:
                    return max(0, result)
        return max(0, total)

    def _aura_atk(self) -> int:
        """种族光环（"Your <race> have +X/+Y this game wherever they are"）。

        hero.race_auras: dict[Race, (atk, health)]，叠加式;
        随从种族匹配或任一侧为 ALL（Amalgam）时生效。
        """
        hero = getattr(self, "controller", None)
        if hero is None:
            return 0
        auras = getattr(hero, "race_auras", None)
        race = getattr(self, "race", None)
        if not auras or race is None or race == Race.NONE:
            return 0
        total = 0
        for aura_race, (atk, _health) in auras.items():
            if race == aura_race or race == Race.ALL or aura_race == Race.ALL:
                total += atk
        return total

    @property
    def max_health(self) -> int:
        total = self.get(GameTag.BASE_HEALTH, 0)
        for b in self._buffs:
            total += b.health
        total += self._aura_health()
        # 动态属性脚本钩子（同 atk——Falling Sky Golem 家族）
        if self.scripts is not None and not self.has(GameTag.SILENCED):
            health_fn = getattr(self.scripts, "health", None)
            if callable(health_fn):
                result = health_fn(self)
                if result is not None:
                    return max(1, result) if result > 0 else result
        return max(1, total) if total > 0 else total

    def _aura_health(self) -> int:
        hero = getattr(self, "controller", None)
        if hero is None:
            return 0
        auras = getattr(hero, "race_auras", None)
        race = getattr(self, "race", None)
        if not auras or race is None or race == Race.NONE:
            return 0
        total = 0
        for aura_race, (_atk, health) in auras.items():
            if race == aura_race or race == Race.ALL or aura_race == Race.ALL:
                total += health
        return total

    @property
    def health(self) -> int:
        return self.get(GameTag.HEALTH, 0)

    @health.setter
    def health(self, value: int) -> None:
        self.set(GameTag.HEALTH, max(0, value))
        if self.get(GameTag.HEALTH, 0) <= 0:
            self.set(GameTag.DEAD, True)

    # ── buff 管理 ──

    def add_buff(self, buff: Buff) -> None:
        """应用 buff。

        引擎钩子:
          - ENCHANT_IMMUNE（Fishbait "This can't gain stats"）: 正值
            增益不生效，直接丢弃（官方: 无法获得属性）
          - 永久化翻转（Lava Lurker "The first Spellcraft spell ...
            is permanent"）: game._permanence_pending 命中本实体时，
            temporary buff 转永久
          - buff_applied 事件（Scarlet Survivor 阈值监听等）
        """
        if buff.atk > 0 or buff.health > 0:
            if self.has(GameTag.ENCHANT_IMMUNE):
                return
        if buff.temporary and self.game is not None \
                and getattr(self.game, "_permanence_pending", None) \
                == self.uuid:
            buff.temporary = False
        self._buffs.append(buff)
        if buff.health > 0:
            self.set(GameTag.HEALTH, self.health + buff.health)
        if self.game is not None:
            from hsrl2.events import Listener  # noqa: F401
            self.game.events.fire(self.game, "buff_applied",
                                  target=self, buff=buff)

    def remove_buff(self, buff: Buff) -> None:
        if buff in self._buffs:
            self._buffs.remove(buff)
            # 当前血不可超上限（HS 语义: 移除生命增益即 clamp——
            # 对抗审查 BUG-5）
            if self.health > self.max_health:
                self.set(GameTag.HEALTH, self.max_health)

    def clear_temporary_buffs(self) -> None:
        self._buffs = [b for b in self._buffs if not b.temporary]
        if self.health > self.max_health:
            self.set(GameTag.HEALTH, self.max_health)

    @property
    def buffs(self) -> List[Buff]:
        return list(self._buffs)

    # ── 脚本钩子分发 ──

    def call_script(self, hook: str, ctx: Any = None):
        """调用脚本钩子。静默随从无任何效果。"""
        if self.has(GameTag.SILENCED):
            return None
        override = self._script_overrides.get(hook)
        if override is not None:
            return override(self, self.game, ctx) if callable(override) else override
        if self.scripts is None:
            return None
        fn = getattr(self.scripts, hook, None)
        if fn is None:
            return None
        return fn(self, self.game, ctx)

    def set_script_override(self, hook: str, fn) -> None:
        self._script_overrides[hook] = fn

    def __repr__(self) -> str:
        return f"<{self.card_id} {self.name} ({self.uuid})>"
