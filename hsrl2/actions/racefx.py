"""种族光环 / 酒馆法术增幅 — "Your <race> have +X/+Y this game" 家族。

- ApplyRaceAura: hero.race_auras[Race] += (atk, health)（叠加式）。
  经 Minion._aura_atk/_aura_health 生效——board/hand/未来获得的所有
  匹配随从实时计算（"wherever they are"）。
- tavern_spell_buff(): 酒馆法术 buff 类效果的统一出口——自动叠加
  hero 的 TAVERN_SPELL_EXTRA_ATK/HEALTH（"Your Tavern spells give an
  extra +X" 家族设置）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions.stats import Buff
from hsrl2.entity import Entity
from hsrl2.queue import Action
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


def _auras(hero: "Hero") -> dict:
    if not hasattr(hero, "race_auras"):
        hero.race_auras = {}
    return hero.race_auras


class ApplyRaceAura(Action):
    """永久种族光环（叠加）。source_id 仅审计用。"""

    def __init__(self, hero: "Hero", race: Race, atk: int, health: int,
                 source_id: str = ""):
        self.hero = hero
        self.race = race
        self.atk = atk
        self.health = health
        self.source_id = source_id

    def do(self, game: "Game") -> None:
        auras = _auras(self.hero)
        prev_atk, prev_health = auras.get(self.race, (0, 0))
        auras[self.race] = (prev_atk + self.atk, prev_health + self.health)
        # 官方可观测行为: 光环生命加成同步抬升当前血量（不显示受损态）
        # —— 对当前在场的全部匹配随从一次性 +health 增量; 未来入场的
        # 匹配随从由 summon 满血初始化（game.summon 已设 HEALTH 重算）
        if self.health:
            for zone_list in (self.hero.board, self.hero.hand):
                for m in zone_list:
                    race = getattr(m, "race", None)
                    if race is None:
                        continue
                    if race == self.race or race == Race.ALL \
                            or self.race == Race.ALL:
                        m.set(GameTag.HEALTH, m.health + self.health)


def tavern_spell_buff(target: Entity, atk: int, health: int) -> Buff:
    """酒馆法术的 buff 出口: 基础值 + hero 的 TAVERN_SPELL_EXTRA_*。

    法术脚本（spells 批次）对随从施加增益时**必须**经此函数构造 Buff，
    使 "Your Tavern spells give an extra +X" 修饰符正确叠加。
    """
    hero = getattr(target, "controller", None)
    extra_atk = hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) if hero else 0
    extra_health = hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) if hero else 0
    return Buff(target, atk=atk + extra_atk, health=health + extra_health)
