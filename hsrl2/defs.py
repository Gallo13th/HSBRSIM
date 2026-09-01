"""CardDef — 不可变卡牌蓝图。

字段与 data/*.json (generate_bg_data.py v2 输出) 一一对应。
script_data_num_1/2 是卡牌文本 {0}/{1} 模板参数的权威数值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from hsrl2.tags import CardType, DBF_RACE_TO_ENUM, GameTag, Race


@dataclass(frozen=True)
class CardDef:
    id: str
    dbf_id: int = 0
    name: str = ""
    text: str = ""
    card_type: CardType = CardType.MINION
    race: Race = Race.NONE
    tech_level: int = 0
    atk: int = 0
    health: int = 0
    cost: int = 3
    rarity: int = 0
    armor: int = 0
    # 文本模板参数 {0}/{1}/{2}/{3} — 卡牌效果数值的权威来源
    script_data_num_1: Optional[int] = None
    script_data_num_2: Optional[int] = None
    script_data_num_3: Optional[int] = None
    script_data_num_4: Optional[int] = None
    # 三连
    triple_upgrade_id: Optional[int] = None   # dbf id of golden version
    triple_base_id: Optional[int] = None
    # 关键词标志（来自 XML 权威标签 + 文本兜底）
    keywords: frozenset[str] = frozenset()
    avenge_target: Optional[int] = None
    activate_cost: Optional[int] = None
    spellcraft_id: Optional[int] = None       # dbf id
    evolution_card_id: Optional[int] = None   # dbf id（Fishbait 等进化链）
    companion_id: Optional[int] = None        # dbf id（伙伴）
    hero_power_id: Optional[int] = None       # dbf id
    sell_value: Optional[int] = None
    unplayable: bool = False
    dark_gift: bool = False
    health_cost: bool = False          # 以生命购买（Hasty Excavation）
    is_pool_minion: bool = False
    is_pool_spell: bool = False
    subsets: frozenset[str] = frozenset()
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_minion(self) -> bool:
        return self.card_type == CardType.MINION

    @property
    def is_golden_def(self) -> bool:
        """金色版本体（由 triple_base_id 标识）。"""
        return self.triple_base_id is not None

    def num(self, index: int, default: int | None = None) -> Optional[int]:
        """按模板序号取参数: num(0)={0}, num(1)={1}, num(2)={2}, num(3)={3}。"""
        vals = (self.script_data_num_1, self.script_data_num_2,
                self.script_data_num_3, self.script_data_num_4)
        if not 0 <= index < 4:
            raise IndexError(index)
        return vals[index] if vals[index] is not None else default

    @staticmethod
    def from_json(entry: dict) -> "CardDef":
        kw: set[str] = set()
        for k in ("windfury", "taunt", "divine_shield", "deathrattle",
                  "battlecry", "poisonous", "magnetic", "reborn", "venomous",
                  "start_of_combat", "rally", "cleave", "activate",
                  "stealth", "choose_one"):
            if entry.get(k):
                kw.add(k)
        avenge = entry.get("avenge")
        avenge_target = None
        if isinstance(avenge, int) and not isinstance(avenge, bool):
            avenge_target = avenge
        elif avenge and entry.get("script_data_num_1"):
            avenge_target = entry["script_data_num_1"]

        subsets = frozenset(
            k.replace("subset_", "") for k in entry
            if k.startswith("subset_") and entry[k]
        )

        hp = entry.get("hero_power_id")

        try:
            ct = CardType(entry.get("card_type", 4))
        except ValueError:
            ct = CardType.INVALID   # 未知协议类型（皮肤/内部实体等）

        return CardDef(
            id=entry["id"],
            dbf_id=entry.get("dbf_id", 0),
            name=entry.get("name", ""),
            text=entry.get("text", ""),
            card_type=ct,
            race=DBF_RACE_TO_ENUM.get(entry.get("card_race", 0), Race.NONE),
            tech_level=entry.get("tech_level", 0) or 0,
            atk=entry.get("atk", 0) or 0,
            health=entry.get("health", 0) or 0,
            cost=(entry.get("cost",
                            0 if entry.get("card_type") == 10 else 3)),
            rarity=entry.get("rarity", 0) or 0,
            armor=entry.get("armor", 0) or 0,
            script_data_num_1=entry.get("script_data_num_1"),
            script_data_num_2=entry.get("script_data_num_2"),
            script_data_num_3=entry.get("script_data_num_3"),
            script_data_num_4=entry.get("script_data_num_4"),
            triple_upgrade_id=entry.get("triple_upgrade_id"),
            triple_base_id=entry.get("triple_base_id"),
            keywords=frozenset(kw),
            avenge_target=avenge_target,
            activate_cost=entry.get("activate_cost"),
            spellcraft_id=entry.get("spellcraft_id"),
            evolution_card_id=entry.get("evolution_card_id"),
            companion_id=entry.get("companion_id"),
            hero_power_id=hp,
            sell_value=entry.get("sell_value"),
            unplayable=bool(entry.get("unplayable")),
            dark_gift=bool(entry.get("dark_gift")),
            health_cost=bool(entry.get("health_cost")),
            is_pool_minion=bool(entry.get("is_pool_minion")),
            is_pool_spell=bool(entry.get("is_pool_spell")),
            subsets=subsets,
            raw=entry,
        )
