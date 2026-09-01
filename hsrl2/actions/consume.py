"""吞噬（Consume / Fodder）Action — 官方 "consume ... to gain its stats"。

数据依据（36.2.2 基线，data/bg_cards.json 权威）:
  - BG21_004 Insatiable Ur'zul: "After you play a Demon, consume a random
    minion in the Tavern to gain its stats."
  - BG23_357 Mind Muck: "Battlecry: Choose a friendly Demon. It consumes a
    minion in the Tavern to gain its stats."
  - BG36_880 Methodical Madness: "Choose a friendly Demon. It consumes 2
    random Tavern minions to gain their stats and Bonus Keywords."
  - RULES §7.1 Fodder: "被吞噬的随从被移除，恶魔获得强大的永久增益"

池语义裁定（本作业单 + RULES §2.3）:
  - 酒馆来源（zone==TAVERN）: 未购随从回池（池守恒——与 refresh_tavern
    旧内容回池同源），release_minion_entity 统一金色/普通记账
  - 手牌来源（zone==HAND）: 手牌随从占过池 → 回池（同上）
  - 棋盘来源（zone==PLAY，友方）: **不回池**。RULES §2.3 列举的回池路径
    为 出售/金色出售/磁力宿主出售/淘汰——吞噬不在列; 被吞噬的友方随从
    永久消失（副本已在购买时扣减，出售才回池）。

吞噬不是死亡（与 game._process_single_death 的招募期死亡路径区分）:
  - 不触发亡语（官方: consume 不触发 deathrattle）
  - 不 fire "death" 事件、不进 graveyard、无复生判定、无 Avenge 计数
  - 手动 board 移除 + zone=REMOVED + 注销监听器（光环生命周期）

属性语义（v1 教训）: 恶魔获得受害者的 atk 与 **max_health**（属性值），
非当前 health——受损/满血受害者等价。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions.stats import Buff as BuffAction
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.queue import Action
from hsrl2.tags import Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# 事件名常量定义于此而非 events.py（events.py 不在本作业白名单——
# 已在作业报告中报告，主线可移册）。kwargs: demon=, minion=（受害者）
CONSUME_EVENT = "minion_consumed"


def _owning_hero(game: "Game", victim: Minion, zone: Zone) -> "Hero":
    """定位 victim 所在区域（tavern/hand）的持有英雄。

    优先 victim.controller（create_minion 时设置），失配则全英雄搜索;
    两者皆失败 = 引擎契约违反（zone 标记与实际容器不一致）→ 抛异常。
    """
    attr = "tavern" if zone == Zone.TAVERN else "hand"
    hero = victim.controller
    if hero is not None and victim in getattr(hero, attr):
        return hero
    for h in game.heroes:
        if victim in getattr(h, attr):
            return h
    raise GameStateError(
        f"ConsumeMinion: victim {victim.card_id} zone={zone.name} "
        f"but not found in any hero's {attr}")


class ConsumeMinion(Action):
    """恶魔吞噬一个随从**实体**（不是 card_id）:

    1. 恶魔获得受害者 atk / max_health（永久 Buff，temporary=False）
    2. 受害者按来源处置:
       - TAVERN: 从持有英雄酒馆移除 + 回池 + zone=REMOVED
       - HAND:   从持有英雄手牌移除 + 回池 + zone=REMOVED
       - PLAY:   仅限友方（victim.controller is demon.controller）;
                 从棋盘移除 + zone=REMOVED + **不回池** + 不触发亡语
    3. fire CONSUME_EVENT ("minion_consumed", demon=, minion=) —
       "whenever a friendly minion is consumed" 类监听源
    """

    def __init__(self, demon: Minion, victim: Minion) -> None:
        self.demon = demon
        self.victim = victim

    def do(self, game: "Game") -> None:
        demon = self.demon
        victim = self.victim
        if demon is victim:
            raise GameStateError("ConsumeMinion: demon cannot consume itself")
        if victim.dead:
            raise GameStateError(
                f"ConsumeMinion: victim {victim.card_id} is dead")

        # 1. 属性快照（移除前）+ 永久增益。
        #    max_health 是属性值（base+buffs），不是当前 health——v1 教训。
        #    直接执行 Buff.do（纯属性变更、无致死可能，无需排队）。
        BuffAction(demon, atk=victim.atk,
                   health=victim.max_health).do(game)

        # 2. 按来源处置
        zone = victim.zone
        if zone == Zone.TAVERN:
            owner = _owning_hero(game, victim, Zone.TAVERN)
            owner.tavern.remove(victim)
            game.minion_pool.release_minion_entity(victim)
        elif zone == Zone.HAND:
            owner = _owning_hero(game, victim, Zone.HAND)
            owner.hand.remove(victim)
            game.minion_pool.release_minion_entity(victim)
        elif zone == Zone.PLAY:
            owner = victim.controller
            if owner is None or victim not in owner.board:
                raise GameStateError(
                    f"ConsumeMinion: victim {victim.card_id} zone=PLAY "
                    f"but not on any board")
            if owner is not demon.controller:
                raise GameStateError(
                    "ConsumeMinion: board victim must be friendly "
                    f"({victim.card_id} belongs to {owner.name})")
            owner.board.remove(victim)
            game._update_positions(owner)
            # 不回池（RULES §2.3 裁定，见模块 docstring）
        else:
            raise GameStateError(
                f"ConsumeMinion: victim {victim.card_id} in unconsumable "
                f"zone {zone.name}")
        victim.zone = Zone.REMOVED
        game.events.unregister_owner(victim)
        game.events.fire(game, CONSUME_EVENT, demon=demon, minion=victim)


class ConsumeRandomTavernMinion(Action):
    """吞噬 demon 控制者酒馆中的一个随机随从（BG21_004 类）。

    - 候选 = hero.tavern 中的 Minion（法术不可被吞噬）
    - 随机走 game.rng.choice（label="consume_random_tavern"）
    - 空候选 → 直接 return（效果落空——真实游戏行为，非静默失败）
    - 直接调用 ConsumeMinion.do（无论本 Action 经队列还是直接调用，
      吞噬都同步完成，不依赖外层 resolve 循环）
    """

    def __init__(self, demon: Minion) -> None:
        self.demon = demon

    def do(self, game: "Game") -> None:
        hero = self.demon.controller
        if hero is None:
            raise GameStateError(
                "ConsumeRandomTavernMinion: demon has no controller")
        candidates = [m for m in hero.tavern if isinstance(m, Minion)]
        if not candidates:
            return
        victim = game.rng.choice(candidates, label="consume_random_tavern")
        ConsumeMinion(self.demon, victim).do(game)
