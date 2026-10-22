"""伤害类 Action。"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from hsrl2.queue import Action

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.minion import Minion


class Hit(Action):
    """对随从造成一次伤害实例并结算死亡。

    - actual = target.take_damage(amount, source)（圣盾抵消 → actual=0）
    - game.check_deaths() 触发死亡波次（亡语/复生/复仇，RULES §6.5/§6.11）
    - fire "damage" (minion=, amount=actual, source=)

    注意: 法术/效果伤害**不触发** poisonous/venomous——官方规则剧毒只随
    攻击伤害触发；本 Action 不做任何剧毒判定（攻击路径由
    CombatScheduler 结算）。
    """

    def __init__(self, target: "Minion", amount: int,
                 source: Optional["Minion"] = None) -> None:
        self.target = target
        self.amount = amount
        self.source = source

    def do(self, game: "Game") -> None:
        actual = self.target.take_damage(self.amount, self.source)
        # damage 事件先于死亡处理——受害者（含濒死者）能看到自己受到伤害
        game.events.fire(game, "damage", minion=self.target,
                         amount=actual, source=self.source)
        game.check_deaths()
