"""事件总线 + 监听器生命周期。

与旧引擎的差异:
  - Listener 挂在实体上，实体离场（死亡/出售/移除）时自动注销
    —— Brann 式光环随离场失效，废除 sticky player-tag 方案
  - 事件参数显式命名（kwargs），废除 args[0]=target 的隐式契约
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from hsrl2.entity import Entity
    from hsrl2.game import Game

# ── 事件名常量 ──
ENTITY_CREATED = "entity_created"
MINION_PLAYED = "minion_played"          # (minion,)
CARD_PLAYED = "card_played"              # (card,)
MINION_BOUGHT = "minion_bought"          # (minion,)
MINION_SOLD = "minion_sold"              # (minion,)
TAVERN_REFRESH = "tavern_refresh"        # ()
TAVERN_SPELL_CAST = "tavern_spell_cast"  # (spell,)
SPELLCRAFT_CAST = "spellcraft_cast"      # (spell,)
BATTLECRY_TRIGGER = "battlecry_trigger"  # (minion,)  — 自然打出与重触发都广播
DEATHRATTLE_TRIGGER = "deathrattle_trigger"  # (minion,)
GOLD_SPENT = "gold_spent"                # (amount,)
HERO_DAMAGE_TAKEN = "hero_damage_taken"  # (amount,)
START_OF_COMBAT = "start_of_combat"      # (player,)
AFTER_ATTACK = "after_attack"            # (attacker, defender) — 伤害结算后
AFTER_ATTACKED = "after_attacked"        # (defender,)
BEFORE_ATTACK = "before_attack"          # (attacker, defender)
DIVINE_SHIELD_LOST = "divine_shield_lost"  # (minion,)
KEYWORD_LOST = "keyword_lost"            # (minion, tag)
DEATH = "death"                          # (minion,)
SUMMON = "summon"                        # (minion,)
MINION_OVERFLOW = "minion_overflow"      # (minion,)
TRIPLE_COMBINED = "triple_combined"      # (golden,)
TURN_START = "turn_start"                # (turn,)
TURN_END = "turn_end"                    # (turn,)
ACTIVATE_USED = "activate_used"          # (minion,)
DARK_GIFT_GIVEN = "dark_gift_given"      # (minion, gift_id,)
ELEMENTAL_PLAYED = "elemental_played"    # (minion,)
# ── actions/ 与 game.py 共用（验收入册）──
DAMAGE = "damage"                        # (minion, amount, source)
KEYWORD_GAINED = "keyword_gained"        # (minion, tag)
TRANSFORM = "transform"                  # (old, new)
COMBAT_END = "combat_end"                # (hero_a, hero_b, result)
HERO_ELIMINATED = "hero_eliminated"      # (hero,)
REBORN_EVENT = "reborn"                  # (minion,)
MINION_CONSUMED = "minion_consumed"      # (demon, minion) — 吞噬（非死亡）
MAGNETIZED = "magnetized"                # (host, attached)


@dataclass
class Listener:
    event: str
    owner: "Entity"                       # 生命周期宿主
    callback: Callable[..., Any]          # fn(game, **event_args)
    condition: Optional[Callable[..., bool]] = None
    once: bool = False
    _fired: bool = False                  # once 监听器已触发标记（战斗快照恢复用）


class EventBus:
    def __init__(self) -> None:
        self._listeners: Dict[str, List[Listener]] = {}
        # 本次 fire 的存活分发集（注销即失效——对抗审查 BUG-4;
        # unregister_owner 联动剔除; 嵌套 fire 由 save/restore 隔离）
        self._live_ids: Optional[set] = None

    def register(self, listener: Listener) -> None:
        self._listeners.setdefault(listener.event, []).append(listener)

    def unregister_owner(self, owner: "Entity") -> None:
        """实体离场：注销其全部监听器（光环生命周期）。"""
        for event in list(self._listeners):
            remaining = []
            for l in self._listeners[event]:
                if l.owner is owner:
                    if self._live_ids is not None:
                        self._live_ids.discard(id(l))
                else:
                    remaining.append(l)
            self._listeners[event] = remaining

    def fire(self, game: "Game", event: str, **kwargs) -> None:
        """触发事件。

        契约:
          - 回调异常向上传播（禁止静默吞掉）
          - once 监听器触发后注销；未满足 condition 的保留
          - 回调中新增的监听器在本次事件中不触发（快照语义）
          - 回调内注销（unregister_owner）的其他监听器本次不再分发
            （对抗审查 BUG-4——once 消费与注销失效语义分离）
        """
        current = list(self._listeners.get(event, []))
        to_dispatch = [l for l in current
                       if l.condition is None or l.condition(**kwargs)]
        dispatch_ids = {id(l) for l in to_dispatch}
        # 注册表更新: once 且本次分发的移除（消费）; 其余保留
        self._listeners[event] = [
            l for l in current if not (l.once and id(l) in dispatch_ids)]
        prev_live = self._live_ids
        self._live_ids = dispatch_ids
        try:
            for l in to_dispatch:
                if id(l) not in self._live_ids:
                    continue   # 回调执行期间被注销
                l._fired = True
                l.callback(game, **kwargs)
        finally:
            self._live_ids = prev_live
