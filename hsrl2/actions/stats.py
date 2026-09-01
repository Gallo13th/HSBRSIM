"""属性 / 关键词 / 变形类 Action。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.events import DIVINE_SHIELD_LOST, KEYWORD_LOST
from hsrl2.game import GameStateError
from hsrl2.queue import Action
from hsrl2.tags import GameTag, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.minion import Minion


class Buff(Action):
    """给目标添加附魔。

    本类与附魔类 entity.Buff 重名——本模块以 ``entity.Buff`` 引用附魔类。
    temporary=True 的附魔战斗结束清除（RULES §3.5 战斗 buff 不延续）。
    gem=True 透传附魔血宝石标记（Gem Confiscation 移转数据源）。
    """

    def __init__(self, target: "Minion", atk: int = 0, health: int = 0,
                 temporary: bool = False, gem: bool = False) -> None:
        self.target = target
        self.atk = atk
        self.health = health
        self.temporary = temporary
        self.gem = gem

    def do(self, game: "Game") -> None:
        self.target.add_buff(entity.Buff(
            atk=self.atk, health=self.health, temporary=self.temporary,
            gem=self.gem))


class GainKeyword(Action):
    """目标获得关键词 tag；fire "keyword_gained" (minion=, tag=)。"""

    def __init__(self, target: "Minion", tag: GameTag) -> None:
        self.target = target
        self.tag = tag

    def do(self, game: "Game") -> None:
        self.target.set(self.tag, True)
        game.events.fire(game, "keyword_gained",
                         minion=self.target, tag=self.tag)


class LoseKeyword(Action):
    """目标失去关键词 tag。

    fire KEYWORD_LOST (minion=, tag=)；tag 为 DIVINE_SHIELD 时额外 fire
    DIVINE_SHIELD_LOST (minion=)。
    """

    def __init__(self, target: "Minion", tag: GameTag) -> None:
        self.target = target
        self.tag = tag

    def do(self, game: "Game") -> None:
        self.target.clear(self.tag)
        game.events.fire(game, KEYWORD_LOST,
                         minion=self.target, tag=self.tag)
        if self.tag == GameTag.DIVINE_SHIELD:
            game.events.fire(game, DIVINE_SHIELD_LOST, minion=self.target)


class Transform(Action):
    """目标变形为 new_card_id（evolve/transform 语义）。

    - 金色状态继承: 新实体按金色卡定义创建（db.golden_version）
    - keep_buffs=True: 原 _buffs 整体转移到新实体，HEALTH 重算为新实体
      max_health（直接替换 _buffs 而非逐个 add_buff——后者会重复加血）
    - keep_buffs=False: 白板新实体
    - 原棋盘位置替换; 旧实体 zone=REMOVED 并注销其监听器（光环生命周期）
    - fire "transform" (old=, new=)
    """

    def __init__(self, target: "Minion", new_card_id: str,
                 keep_buffs: bool = True) -> None:
        self.target = target
        self.new_card_id = new_card_id
        self.keep_buffs = keep_buffs

    def do(self, game: "Game") -> None:
        target = self.target
        controller = target.controller
        if controller is None or target not in controller.board:
            raise GameStateError(
                f"Transform target {target.card_id} not on a board")
        new = game.create_minion(self.new_card_id, controller=controller,
                                 golden=target.is_golden)
        if self.keep_buffs:
            new._buffs = list(target._buffs)
            new.set(GameTag.HEALTH, new.max_health)
        idx = controller.board.index(target)
        new.zone = Zone.PLAY
        controller.board[idx] = new
        game._update_positions(controller)
        target.zone = Zone.REMOVED
        game.events.unregister_owner(target)
        game.events.fire(game, "transform", old=target, new=new)
