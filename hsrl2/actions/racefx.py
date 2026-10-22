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
                    races = getattr(m, "races", None)
                    if races is None:
                        continue
                    if self.race == Race.ALL or self.race in races:
                        # 类型身份集合（AC-3）; ALL 光环命中全部（含无类型），
                        # 限定光环按集合成员判定（双类型随从吃两种族光环）。
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


def elemental_give_bonus(source) -> tuple:
    """元素 give-stats 加成 `(atk, health)`（RULES §7.4.5）。

    "Your Elementals that give stats grant an extra +X/+Y"（Fountain Pen
    `BG32_MagicItem_802` / Amplifying Essence `BG36_MagicItem_380`）与
    "Your Elementals give an extra +X Attack / +X Health this game"
    （Sand Swirler `BG32_841` / Glowing Cinder `BG32_842` / Moat Custodian
    `BG36_351`）写入 hero 级 `ELEMENTAL_EXTRA_ATK(1057)` /
    `ELEMENTAL_EXTRA_HEALTH(1055)`。

    **只有给予者本身是元素**（race ∈ {ELEMENTAL, ALL}）时才叠加——
    Champion of Sargeras（非元素）等卡的全馆增益不吃该加成。
    返回 `(0, 0)` 表示无加成（source 非元素 / 无 controller）。
    """
    hero = getattr(source, "controller", None)
    has_race = getattr(source, "has_race", None)
    if hero is None or has_race is None or not has_race(Race.ELEMENTAL):
        return (0, 0)
    return (hero.get(GameTag.ELEMENTAL_EXTRA_ATK, 0),
            hero.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0))
