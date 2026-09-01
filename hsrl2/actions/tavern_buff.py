"""酒馆持久 Buff 系统 — "your Tavern minions have ..." 类效果的数据结构与动作。

语义模型（作业单规格）:
  - TavernBuff: 不可变描述子（数值 + 匹配条件）。数值来源由脚本层从
    CardDef.num(0/1) 取，本模块零硬编码。
  - ApplyTavernBuff: 持久记录——append 到 hero.tavern_buffs，供
    refresh_tavern 在新随从入馆时应用（引擎挂接点，见下方缺口报告）
  - BuffCurrentTavern: 立即对当前酒馆全部匹配随从施加 Buff

匹配规则（与 actions/discover._pool_candidates 的种族/tier 过滤一致）:
  - race_filter: d.race == race_filter 或 d.race == Race.ALL
    （Amalgam 规则——全种族随从匹配任何种族查询）
  - min_tier/max_tier: None = 不限

引擎缺口（本作业不可改 game.py，报告主线）:
  game.refresh_tavern 在 minion_pool.draw_tavern 抽取新随从后，
  **没有**应用 hero.tavern_buffs 的逻辑（grep 验证: game.py / hero.py
  均无 tavern_buffs）。需主线在 refresh_tavern 新随从 zone=TAVERN 后
  追加约 5 行: 对每个新 Minion 查 db 定义，逐个应用
  hero.tavern_buffs 中全部 matches 的 TavernBuff。冻结（keep）随从
  已在入馆时获得过 Buff，刷新保留时不得重复应用。
  hero.py 亦无 tavern_buffs 属性——本模块用 hasattr 延迟初始化，
  主线接线时可改为 Hero.__init__ 正式字段。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from hsrl2 import entity
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.queue import Action
from hsrl2.tags import Race

if TYPE_CHECKING:
    from hsrl2.defs import CardDef
    from hsrl2.game import Game
    from hsrl2.hero import Hero


@dataclass(frozen=True)
class TavernBuff:
    """酒馆持久 Buff 描述子。

    字段:
      atk/health:        施加的永久增益数值（来源: 脚本层 CardDef.num）
      race_filter:       仅匹配该种族（None = 不限; Race.ALL 卡总匹配）
      min_tier/max_tier: tier 下/上限（None = 不限）
      source_id:         来源卡牌 id（审计用，不参与匹配）
    """

    atk: int = 0
    health: int = 0
    race_filter: Optional[Race] = None
    min_tier: Optional[int] = None
    max_tier: Optional[int] = None
    source_id: str = ""

    def matches(self, minion_def: "CardDef") -> bool:
        """CardDef 是否被本 Buff 覆盖（种族/tier 组合过滤）。"""
        if (self.race_filter is not None
                and minion_def.race != self.race_filter
                and minion_def.race != Race.ALL):
            return False
        if self.min_tier is not None and minion_def.tech_level < self.min_tier:
            return False
        if self.max_tier is not None and minion_def.tech_level > self.max_tier:
            return False
        return True


def _tavern_buffs_list(hero: "Hero") -> list:
    """hero.tavern_buffs 延迟初始化（不改 hero.py 的 setattr 方案）。"""
    if not hasattr(hero, "tavern_buffs"):
        hero.tavern_buffs = []
    return hero.tavern_buffs


class ApplyTavernBuff(Action):
    """登记持久酒馆 Buff: append 到 hero.tavern_buffs。

    仅记录、不立即生效（"from now on" 语义的持久面）。立即面由
    BuffCurrentTavern 或（主线接线后）refresh_tavern 应用。
    """

    def __init__(self, hero: "Hero", buff: TavernBuff) -> None:
        self.hero = hero
        self.buff = buff

    def do(self, game: "Game") -> None:
        _tavern_buffs_list(self.hero).append(self.buff)


class BuffCurrentTavern(Action):
    """对 hero 当前酒馆中全部匹配的随从立即施加 Buff。

    - 仅 Minion（酒馆法术不可被 buff）
    - 匹配判定用 db 中该卡的 CardDef（matches 契约）
    - 永久 Buff（temporary=False），购买后随实体带走的属性保留
    - 未知 card_id → GameStateError（禁止静默跳过）
    """

    def __init__(self, hero: "Hero", buff: TavernBuff) -> None:
        self.hero = hero
        self.buff = buff

    def do(self, game: "Game") -> None:
        for e in list(self.hero.tavern):
            if not isinstance(e, Minion):
                continue
            d = game.db.get(e.card_id)
            if d is None:
                raise GameStateError(
                    f"BuffCurrentTavern: unknown card {e.card_id} in tavern")
            if self.buff.matches(d):
                e.add_buff(entity.Buff(
                    atk=self.buff.atk, health=self.buff.health,
                    source_id=self.buff.source_id))
