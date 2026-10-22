"""属性 / 关键词 / 变形类 Action。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

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
    persist=True / source_id 透传"按来源跨战斗持久化"标记（RULES §3.5
    例外 4——Bewitched Ribbon `BG35_MagicItem_923` / Cyclist Portrait
    `BG36_MagicItem_362`；`Game.run_combat` 恢复阶段按该标记重放附魔）。
    source 透传**来源实体**（`ActionQueue.resolve` 写入
    `game._action_source` → `Entity.add_buff` 填入 `stats_gained` 的
    `source` 载荷; 缺省 None = 来源不明，不得臆造）。
    """

    def __init__(self, target: "Minion", atk: int = 0, health: int = 0,
                 temporary: bool = False, gem: bool = False,
                 persist: bool = False, source_id: str = "",
                 source=None) -> None:
        self.target = target
        self.atk = atk
        self.health = health
        self.temporary = temporary
        self.gem = gem
        self.persist = persist
        self.source_id = source_id
        self.source = source

    def do(self, game: "Game") -> None:
        self.target.add_buff(entity.Buff(
            atk=self.atk, health=self.health, temporary=self.temporary,
            gem=self.gem, persist=self.persist,
            source_id=self.source_id, source=self.source))


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
    - gilded_not_tripled=True: 目标为金色但调用方只从池里扣到 <3 份
      新卡副本（池不足以支撑一次完整三连金）→ 新实体打
      GILDED_NOT_TRIPLED（出售/淘汰按 1 份回池, RULES §2.3 Reno 口径），
      否则"扣 1 份、退 3 份"会让池净增 2（2026-09-02 对抗审查实测）
    - force_golden=True/False: 覆写金色状态（缺省 None = 继承目标）。
      "Make a friendly minion Golden until next turn" 需要把**非金**实体
      变为金色（True）与到期**回退为非金**（False）——`new_card_id` 仍是
      基础 id，`create_minion(golden=)` 负责解析金色独立卡定义
      （RULES §7.4.14 临时金色）
    """

    def __init__(self, target: "Minion", new_card_id: str,
                 keep_buffs: bool = True,
                 gilded_not_tripled: bool = False,
                 force_golden: Optional[bool] = None) -> None:
        self.target = target
        self.new_card_id = new_card_id
        self.keep_buffs = keep_buffs
        self.gilded_not_tripled = gilded_not_tripled
        self.force_golden = force_golden

    def do(self, game: "Game") -> None:
        target = self.target
        controller = target.controller
        if controller is None or target not in controller.board:
            raise GameStateError(
                f"Transform target {target.card_id} not on a board")
        golden = target.is_golden if self.force_golden is None \
            else self.force_golden
        new = game.create_minion(self.new_card_id, controller=controller,
                                 golden=golden)
        if self.gilded_not_tripled:
            new.set(GameTag.GILDED_NOT_TRIPLED, True)
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
        # 被动效果重接线（RULES §6.21）: Transform **不**触发召唤/battlecry
        # 类效果（官方语义），但新实体的**被动**能力必须立即生效——
        # 旧实现只换卡面，`on_summon` 里注册被动监听/tag 的卡（Titus /
        # Drakkari / Groundbreaker 家族）变身之后完全空转
        # （2026-09-02 对抗审查证伪: Transform 成 BG31_035 后打 Naga，
        # 本体不增益、只有镜像饰品增益）。缺失该钩子的脚本为 no-op。
        game.run_script_hook(new, "on_transform", ctx={"old": target})
        # 战斗内变身 → 战后重放（RULES §3.5 例外: 变身是永久卡身份变更，
        # 不是战斗 buff; `run_combat` 复原棋盘时会用本记录换回新实体）
        if game.in_combat or game._active_combat is not None:
            game._combat_transforms.append((target.uuid, new))
