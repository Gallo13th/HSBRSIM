"""CardDef — 不可变卡牌蓝图。

字段与 data/*.json (generate_bg_data.py v2 输出) 一一对应。
script_data_num_1/2 是卡牌文本 {0}/{1} 模板参数的权威数值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from hsrl2.tags import (CardType, DBF_RACE_TO_ENUM, GameTag, Race,
                        race_set)


@dataclass(frozen=True)
class CardDef:
    id: str
    dbf_id: int = 0
    name: str = ""
    text: str = ""
    card_type: CardType = CardType.MINION
    race: Race = Race.NONE
    #: per-race 布尔 tag（`RaceTagMap.xml` enumID 2522–2556 的 BG 标准 10 族）;
    #: 与 `race`（CARDRACE 主类型）取并集 = **类型身份集合**（AC-3）。
    race_tags: frozenset = frozenset()
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
    script_data_num_5: Optional[int] = None   # {4}（NUM_5; 2026-09-02 导出）
    # 三连
    triple_upgrade_id: Optional[int] = None   # dbf id of golden version
    triple_base_id: Optional[int] = None
    # 酒馆法术派系（饰品: 11=Lesser / 12=Greater——数据全量导出）
    spell_school: Optional[int] = None
    # 关键词标志（来自 XML 权威标签 + 文本兜底）
    keywords: frozenset[str] = frozenset()
    avenge_target: Optional[int] = None
    activate_cost: Optional[int] = None
    spellcraft_id: Optional[int] = None       # dbf id
    evolution_card_id: Optional[int] = None   # dbf id（Fishbait 等进化链）
    companion_id: Optional[int] = None        # dbf id（伙伴）
    reward_dbf_id: Optional[int] = None       # dbf id（任务奖励 {0} 指向卡）
    hero_power_id: Optional[int] = None       # dbf id
    sell_value: Optional[int] = None
    unplayable: bool = False
    dark_gift: bool = False
    health_cost: bool = False          # 以生命购买（Hasty Excavation）
    is_pool_minion: bool = False
    is_pool_spell: bool = False
    # ── 任务卡（2026-09-18）──
    # `quest=True` = 任务卡本体（CardDefs tag 2466）。实测（2026-09-18，
    # `data/bg_cards.json`）共 **11** 张带此标志（旧注写"仅 10 张"为假）。
    # **该标志当前不被引擎逻辑读取**（`Game.quest_defs()` 用
    # `is_quest_card` 三条谓词，不看 `quest`）——只有
    # `test_batch_quests.py` 断言它; 保留为数据忠实导出，不得据此判定任务。
    # 公告 token（`BG24_Quest_Bob` / `BG33_Anomaly_008_Quest`）实测
    # `quest=False` 但 **card_type=SPELL 且 `quest_progress_total`=3**
    # ——它们**满足** `Game.quest_defs()` 的 SPELL/tag 535/id 三条谓词，
    # 只由 `game._QUEST_ANNOUNCE_TOKENS` 显式排除（不是 card-type 过滤，
    # 也不是靠 `quest` 标志）。
    # `quest_progress_total` = 完成基线值（tag 535）——数值权威 =
    # 各卡 wiki 页 "New baseline requirement" 的当前值（逐卡见
    # `docs/agents/QUEST_DEFERRED_SPEC.md`）。实测 42 个已载入定义带
    # tag 535（card_type 横跨 SPELL/奖励/酒馆法术/异变/饰品）。它是
    # `Game.quest_target` 的**交叉校验**来源，不作为运行期进度缩放因子
    # （缩放公式无权威，项目所有者裁定的权威序下不采用）。
    quest: bool = False
    quest_progress_total: Optional[int] = None
    subsets: frozenset[str] = frozenset()
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_minion(self) -> bool:
        return self.card_type == CardType.MINION

    @property
    def races(self) -> frozenset:
        """**类型身份集合**（不可变）— `CARDRACE` ∪ per-race 布尔 tag。

        权威: wiki `Multi-type minion`（revid 855346）"Multi-types are
        always additions, never exclusions." + `Minion`（revid 817925）
        "In any such case, these minions benefit from the effects of both
        types."；`Race.ALL` → `STANDARD_RACES` 全 10 族（`All` revid
        893299）；`Race.NONE` → 空集。

        **不是** `CardDef.subsets`（`BACON_SUBSET_*`）——后者是饰品的
        "关联随从类型"，`BG21_013` Whelp Smuggler 有 `subset_dragon` 却
        无 DRAGON tag（AC-7）。多类型随从池成员 = 10 张（AC-3）。
        """
        return race_set(self.race, self.race_tags)

    @property
    def is_golden_def(self) -> bool:
        """金色版本体（由 triple_base_id 标识）。"""
        return self.triple_base_id is not None

    def num(self, index: int, default: int | None = None) -> Optional[int]:
        """按模板序号取参数: num(0)={0} … num(4)={4}（最多 5 个）。

        生成器自 2026-09-02 起导出 `TAG_SCRIPT_DATA_NUM_5` →
        `script_data_num_5`（`{4}` 类卡: Bubble Crown `BG35_MagicItem_920` /
        Bewitched Ribbon `BG35_MagicItem_923` / Thornspike Pauldron
        `BG35_MagicItem_431t`）。
        """
        vals = (self.script_data_num_1, self.script_data_num_2,
                self.script_data_num_3, self.script_data_num_4,
                self.script_data_num_5)
        if not 0 <= index < 5:
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

        # per-race 布尔 tag（生成器 `race_tags`）→ Race 值。拼写错误
        # fail-loud: 未知种族名静默丢弃会让多类型身份**静默降级**为单类型
        # （正是本原语要消灭的第三态）。
        try:
            race_tags = frozenset(
                Race[name] for name in entry.get("race_tags", ())
            )
        except KeyError as exc:
            raise ValueError(
                f"CardDef {entry.get('id')!r}: 未知 race_tags 名称 {exc.args[0]!r}"
                "——数据层出现 Race 枚举未收录的种族，必须先在 "
                "hsrl2/tags.py::Race 补录（fail-loud，禁止静默丢弃）"
            ) from None

        # CARDRACE 主类型。未知取值必须 fail-loud（37.0 ABERRATION=126
        # 曾因 `.get(..., Race.NONE)` 静默变成"无种族"——数据层与引擎
        # 枚举不同步时宁可加载失败，也不能静默降级）。
        raw_race = entry.get("card_race", 0)
        if raw_race in (None, 0):
            race = Race.NONE
        else:
            try:
                race = DBF_RACE_TO_ENUM[raw_race]
            except KeyError:
                raise ValueError(
                    f"CardDef {entry.get('id')!r}: 未知 card_race={raw_race!r}"
                    "——数据层出现 Race 枚举未收录的种族，必须先在 "
                    "hsrl2/tags.py::Race / DBF_RACE_TO_ENUM 补录"
                    "（fail-loud，禁止静默降级为 Race.NONE）"
                ) from None

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
            race=race,
            race_tags=race_tags,
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
            script_data_num_5=entry.get("script_data_num_5"),
            triple_upgrade_id=entry.get("triple_upgrade_id"),
            triple_base_id=entry.get("triple_base_id"),
            spell_school=entry.get("spell_school"),
            keywords=frozenset(kw),
            avenge_target=avenge_target,
            activate_cost=entry.get("activate_cost"),
            spellcraft_id=entry.get("spellcraft_id"),
            evolution_card_id=entry.get("evolution_card_id"),
            companion_id=entry.get("companion_id"),
            reward_dbf_id=entry.get("reward_dbf_id"),
            hero_power_id=hp,
            sell_value=entry.get("sell_value"),
            unplayable=bool(entry.get("unplayable")),
            dark_gift=bool(entry.get("dark_gift")),
            health_cost=bool(entry.get("health_cost")),
            is_pool_minion=bool(entry.get("is_pool_minion")),
            is_pool_spell=bool(entry.get("is_pool_spell")),
            quest=bool(entry.get("quest")),
            quest_progress_total=entry.get("quest_progress_total"),
            subsets=subsets,
            raw=entry,
        )
