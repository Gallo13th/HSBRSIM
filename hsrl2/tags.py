"""枚举 — 与 Hearthstone 协议 enumID 数值对齐（XML 权威）。

命名遵循 HearthDb 惯例；未命名的新标签以数字注释说明。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Dict


class Zone(IntEnum):
    INVALID = 0
    PLAY = 1
    HAND = 2
    TAVERN = 3      # 战棋酒馆展示区（本引擎定义）
    GRAVEYARD = 4
    SETASIDE = 5
    REMOVED = 6


class CardType(IntEnum):
    INVALID = 0
    GAME = 1
    PLAYER = 2
    HERO = 3
    MINION = 4
    SPELL = 5
    ENCHANTMENT = 6
    WEAPON = 7
    ITEM = 8
    TOKEN = 9
    HERO_POWER = 10
    # 11 = STAT, 12 = PLAYER (button 实体)
    BACON_TRINKET = 44       # 饰品
    BACON_ANOMALY = 43       # 异变
    BACON_SPELL = 42         # 酒馆法术（BG 数据 card_type=42，203 张；
                             # 此前解析为 INVALID——2026-09-01 补录）
    BACON_QUEST_REWARD = 40  # 任务奖励


class Race(IntEnum):
    INVALID = 0
    UNDEAD = 11
    MURLOC = 14
    DEMON = 15
    MECH = 17        # XML 17 = MECHANICAL
    ELEMENTAL = 18
    BEAST = 20
    PIRATE = 23
    DRAGON = 24
    ALL = 26
    QUILBOAR = 43
    NAGA = 92
    #: 37.0（build 255130）新增第 11 族。官方 `TAG_RACE` 枚举值 126（与
    #: `reversed/hsdata_255130/RaceTagMap.xml <Race race="ABERRATION" tag="4756">`
    #: 的 per-race 布尔 tag 不同：126 是 CARDRACE 主类型取值，4756 是
    #: `CARDRACE_BACON_ABERRATION` 布尔 tag；255130 BG 卡数据只出现 126，
    #: 4756 在 BG 实体中 0 命中——见 `reversed/tag_diff.json`
    #: `other_enums.race.official_only`）。
    ABERRATION = 126
    NONE = 0


DBF_RACE_TO_ENUM = {
    11: Race.UNDEAD, 14: Race.MURLOC, 15: Race.DEMON, 17: Race.MECH,
    18: Race.ELEMENTAL, 20: Race.BEAST, 23: Race.PIRATE, 24: Race.DRAGON,
    26: Race.ALL, 43: Race.QUILBOAR, 92: Race.NAGA,
    126: Race.ABERRATION,
}

#: 酒馆标准 11 族（`Race.ALL` 展开后的规范集合；36.2.2 为 10 族，
#: 37.0 起官方新增 ABERRATION——池内 37 张，见 255130 生成数据）。
#: 权威: hearthstone.wiki.gg `Minion`（revid 817925）"Minions in Hearthstone
#: can have one or two of the following minion types" + `All`（revid 893299）
#: "All minions can be found from random effects and Discover options that
#: cover any specific type" + 255130 `CardDefs.Bacon.xml` 的 CARDRACE=126。
STANDARD_RACES = frozenset({
    Race.UNDEAD, Race.MURLOC, Race.DEMON, Race.MECH, Race.ELEMENTAL,
    Race.BEAST, Race.PIRATE, Race.DRAGON, Race.QUILBOAR, Race.NAGA,
    Race.ABERRATION,
})

#: `Race.ALL` 的规范展开 = 全部标准 11 族（AC-4 / N6 表示契约）。
RACE_SET_ALL = STANDARD_RACES


def race_set(primary: Race, extra=()) -> frozenset:
    """类型身份集合 — `CARDRACE`（主类型）∪ per-race 布尔 tag（AC-3）。

    语义（wiki `Minion` revid 817925 / `Multi-type minion` revid 855346）:
      - 普通多类型: "In any such case, these minions benefit from the
        effects of both types." / "Multi-types are always additions, never
        exclusions."
      - `Race.ALL`: "All minions ... benefit from and are affected by every
        type effect in the game." → 展开为 `STANDARD_RACES`（不是"单值
        匹配一切"哨兵；匹配即 `want in races`）。
      - `Race.NONE` / `INVALID`: 空集（"do not benefit from any specific
        type effects"）。
    """
    out: set = set()
    if primary == Race.ALL:
        out |= STANDARD_RACES
    elif primary not in (Race.NONE, Race.INVALID):
        out.add(Race(primary))
    for r in extra:
        r = Race(r)
        if r == Race.ALL:
            out |= STANDARD_RACES
        elif r not in (Race.NONE, Race.INVALID):
            out.add(r)
    return frozenset(out)


class GameTag(IntEnum):
    """所有可见状态存于 tags 字典。数值与协议 enumID 一致。"""

    # 实体基础
    ENTITY_ID = 12
    CARD_ID = 1225
    CARDTYPE = 202
    RACE = 200
    TECH_LEVEL = 1440          # 酒馆等级
    RARITY = 203
    COST = 48
    NAME = 1000                # 引擎内部（非协议）
    TEXT = 1001                # 引擎内部（非协议）
    ZONE = 49
    ZONE_POSITION = 263

    # 随从属性
    ATK = 47
    HEALTH = 45
    DAMAGE = 44
    BASE_ATK = 1010            # 引擎内部：基础攻击（非协议）
    BASE_HEALTH = 1011         # 引擎内部：基础生命（非协议）
    MAX_HEALTH = 1012          # 引擎内部（非协议）

    # 玩家
    GOLD = 1013                # 引擎内部（非协议）
    ARMOR = 292
    TAVERN_TIER = 1014         # 引擎内部（非协议）
    UPGRADE_COST = 1015        # 引擎内部：当前升级费用（非协议）
    HEALTH2 = 1016             # 引擎内部：玩家当前生命（非协议）

    # 关键词
    TAUNT = 190
    DIVINE_SHIELD = 194
    WINDFURY = 189
    MEGA_WINDFURY = 826
    POISONOUS = 363
    VENOMOUS = 2853
    REBORN = 1085
    DEATHRATTLE = 217
    BATTLECRY = 218
    CLEAVE = 1017              # 引擎内部（协议无独立标签，文本检测）
    MAGNETIC = 849
    STEALTH = 19
    IMMUNE = 240               # XML enumID 240（原误写 49 = ZONE 冲突——
                               # IntEnum 别名化使 has(IMMUNE) 恒真; 2026-09-01 修复）
    SILENCED = 3309

    # 触发时机
    START_OF_COMBAT = 1531
    START_OF_TURN = 1018       # 引擎内部
    END_OF_TURN = 1019         # 引擎内部
    AVENGE = 2129
    AVENGE_TARGET = 1020       # 引擎内部：阈值
    RALLY = 4204
    ON_SELL = 1021             # 引擎内部
    SPELLCRAFT = 2359

    # S14
    ACTIVATE = 4089            # INTERACTABLE_OBJECT
    ACTIVATE_COST = 4090       # INTERACTABLE_OBJECT_COST
    ACTIVATE_USED_THIS_TURN = 1022   # 引擎内部
    DARK_GIFT = 4855
    EVOLUTION_CARD_ID = 2519

    # 三连 / 金色
    GOLDEN = 1023              # 引擎内部
    TRIPLE_REWARD_TIER = 1024  # 引擎内部
    GOLDEN_NO_TRIPLE_REWARD = 1025   # Gilding Dark Gift（引擎内部）

    # 战斗状态（引擎内部，战斗结束清除）
    EXHAUSTED = 1026           # 本场战斗已用尽攻击
    WINDFURY_ATTACKS = 1027    # 本场已攻击次数（风怒计数）
    VENOMOUS_CONSUMED = 1028   # Venomous 已消耗（战斗开始重置 — S14 规则）
    DIVINE_SHIELD_HITS = 1029  # Toreth's Blessing: 圣盾需 N 次击破（引擎内部）
    SHIELD_HITS_TAKEN = 1039   # 圣盾已承受击打次数（引擎内部）

    # 回合计数（玩家）
    GOLD_SPENT_THIS_TURN = 1030
    CARDS_PLAYED_THIS_TURN = 1031
    TAVERN_SPELLS_CAST_THIS_TURN = 1032
    TAVERN_SPELLS_CAST_THIS_GAME = 1033
    FREE_REFRESH_REMAINING = 1034
    FROZEN = 1035              # 冻结（整馆由 player 级 tag 表达）

    # 死亡/胜负记录（引擎内部）
    DEAD = 1036
    KILLER = 1037              # 击杀者引用（引擎内部，不序列化）
    JUST_DIED = 1038
    SELL_VALUE = 1040          # 出售价覆写（引擎内部）
    BATTLECRY_DOUBLER = 1041   # Brann 式光环标志（引擎内部）
    AVENGE_COUNTER = 1042      # 复仇计数（引擎内部）
    TRIPLE_BASE_CARD_ID = 1043 # 金色实体的基础卡 id（引擎内部）
    IMMUNE_WHILE_ATTACKING = 1044  # 攻击时免疫（Warpwing/Invulnerability，引擎内部）
    PERSIST_COMBAT_CHANGES = 1045   # 战斗变化持久化（Tarecgosa's Blessing）
    COUNTER_BATTLECRIES = 1046      # 本局已触发的战吼数（Dark Gifts Battle Scars 资格）
    COUNTER_DEATHRATTLES = 1047     # 本局已触发的亡语数（Death's Embrace 资格）
    LOCKBOX_TURNS_LEFT = 1048       # Lockbox 剩余开启回合数（引擎内部）
    TRIPLE_REWARD_PENDING = 1049    # 手牌三连待发放奖励（打出时触发，引擎内部）
    CHOOSE_ONE = 1050               # Choose One 随从（引擎内部）
    BLOOD_GEM_BONUS_ATK = 1051      # 血宝石额外攻击加成（Player，引擎内部）
    BLOOD_GEM_BONUS_HEALTH = 1052   # 血宝石额外生命加成（Player，引擎内部）
    TAVERN_SPELL_EXTRA_ATK = 1053   # 酒馆法术额外攻击加成（Player）
    TAVERN_SPELL_EXTRA_HEALTH = 1054  # 酒馆法术额外生命加成（Player）
    ELEMENTAL_EXTRA_HEALTH = 1055   # 元素 give-Health 效果加成（Player）
    ELEMENTAL_EXTRA_ATK = 1057      # 元素 give-Attack 效果加成（Player）
    NEXT_SPELL_COST_REDUCTION = 1056  # 下一个购买的酒馆法术折扣（Player）
    CHOOSE_BOTH = 1058              # Choose One 双效合并光环（Thorned Trailblazer）
    INCOME_CAP_BONUS = 1059         # 每回合基础收入上限加成（Strike Oil，Player）
    GEMS_PLAYED_ON = 1060           # 该随从被施放的血宝石数（引擎内部）
    END_OF_TURN_DOUBLER = 1061      # EoT 翻倍光环（Drakkari Enchanter，棋盘扫描）
    DEATHRATTLE_DOUBLER = 1062      # 亡语翻倍光环（Titus Rivendare，棋盘扫描）
    GOLDEN_MINIONS_PLAYED = 1063    # 本局打出的金色随从数（Player）
    HEALTH_REFRESHES_LEFT = 1064    # 本回合剩余健康购买刷新次数（Player，Malchezaar）
    SPELL_DOUBLER = 1065            # 定向法术双施光环（Balinda，棋盘扫描）
    ADJACENT_PERSIST_SOURCE = 1066  # 相邻随从保留战斗增益（Persistent Poet）
    ENCHANT_IMMUNE = 1067           # 不可获得增益（Fishbait "can't gain stats"）
    LOCKED_IN_HAND = 1068           # 手牌锁定不可打出（Search Through Time）
    PERSIST_DOUBLE = 1069           # 战斗属性保留且翻倍（Tarecgosa gift/golden Poet）
    GILDED_NOT_TRIPLED = 1070       # 非三连金色（Reno/Laureate/Golden Touch——回池按 1 份）
    HERO_POWER_USED_THIS_TURN = 1071  # 本回合技能已用次数（Player/hero）
    HERO_POWER_USES_THIS_GAME = 1072  # 本局技能累计使用数（Player/hero）
    TAVERN_MINION_COST_OVERRIDE = 1073  # 随从购买价平价覆盖（Sindragosa/Millhouse=2）
    REFRESH_COST_OVERRIDE = 1074      # 刷新费覆盖（Millhouse=2）
    FREE_MINION_BUYS_THIS_TURN = 1075  # 本回合剩余免费随从购买数（Aranna）
    TRIPLE_THRESHOLD = 1076           # 三连所需份数（默认 3; Clocksworth=2）
    TRIPLE_REWARD_COINS = 1077        # 三连奖励替代为 N 张 Tavern Coin（Clocksworth）
    TURN_SKIPPED = 1078               # 本回合跳过（Faelin/A.F.Kay——招募动作全锁）
    UPGRADE_COST_MOD = 1079           # 升级费加值（Millhouse +1）
    TAVERN_OFFER_MOD = 1080           # 酒馆随从展示数加值（Sindragosa -1）
    HERO_POWER_NEXT_DISCOUNT = 1081  # 下次英雄技能费折扣（Patches 买 Pirate）
    TRIPLE_NO_REWARD = 1082       # 三连合成但无奖励（异变 801 "no Triple Rewards"）
    FREE_SPELL_BUYS_THIS_TURN = 1083  # 本回合剩余免费酒馆法术购买数（Peacebloom Candle）
    FREE_MINION_BUY_RACE = 1084   # 免费随从购买的种族限定（Grifter Portrait; 未设=不限）
    FREE_MINION_BUY_KEYWORD = 1085  # 免费随从购买的关键词限定（Warcry Totem=BATTLECRY）
    TAVERN_SPELL_COST_MOD = 1086  # 酒馆法术持久折扣（Beyond the Mirage -=1; Player）
    SELL_VALUE_OVERRIDE = 1087    # 英雄级出售价覆写（Uncompensated Upset "sell for (0)"）
    HEALTH_MINION_BUYS_THIS_TURN = 1088  # 本回合剩余"以生命代金"购买的随从数
    HEALTH_BUY_RACE = 1089        # 生命代金购买的种族限定（BG32_MagicItem_821 恶魔; 未设=不限）
    HEALTH_SPELL_BUYS_THIS_TURN = 1090   # 本回合剩余"以生命代金"购买的酒馆法术数
    HEALTH_BUY = 1091             # 实体级: 该酒馆实体可"以生命代金"购买（BG35_MagicItem_152）
    COUNTER_ELEMENTALS_PLAYED = 1092  # 本局已打出的元素数（Player; BG26_537 动态属性资格）
    BONUS_KEYWORDS = 1097             # 实体被**授予**的 Bonus Keyword 集合
                                      # （RULES §9.6 六张; 801"gains its
                                      # Bonus Keywords"/891/892 读取点）
    PERSIST_BONUS_ONLY = 1098         # 战斗持久化时**只**保留 Bonus Keyword
                                      # 六张（417 Tarecgosa Sticker）
    MINIONS_SOLD_THIS_TURN = 1093     # 本回合已出售随从数（hero 级，每回合清零;
                                      # BG30_MagicItem_992 Darnassus Pie /
                                      # BG32_MagicItem_832 Windfall Portrait）
    TAVERN_OFFER_TIER_EXACT = 1094    # 本次刷新"只出恰好该 tier"（hero 级;
                                      # BG32_MagicItem_366 Guiding Candle）
    TAVERN_EXTRA_TIER_SLOTS = 1095    # 额外 N 个展示位（hero 级;
                                      # BG30_MagicItem_423 Innkeeper's Stein）
    TAVERN_EXTRA_TIER = 1096          # 上述额外位取自的档位（缺省 = 酒馆等级+1）
    RACES = 1099              # 实例类型身份集合（`frozenset[Race]`; 引擎内部）
    # 注: 数值 1099 与协议枚举 `PLAYER_BASE_SHRINE_DECK_ID` 撞号——本仓
    # 引擎内部 tag 段（1077–1099）沿用此惯例, 该协议枚举未被引擎使用。
                              # ——多类型身份（AC-3）: 由 `CARDRACE` ∪ per-race
                              # tag 得出，绝不含 ALL/NONE（ALL 已在写入时展开为
                              # `STANDARD_RACES`）。读取点 `Minion.races`。


# ══════════════════════════════════════════════════════════════════════
# 动态脚本数据（官方 TAG_SCRIPT_DATA_NUM_1..5）——**独立命名空间**
# ══════════════════════════════════════════════════════════════════════
#
# 背景（2026-10-18，官方一致性 P0）：
#   * 官方 `TAG_SCRIPT_DATA_NUM_1..5` 的**真实 enumID** 经两个权威源核对：
#     `reversed/hsdata_255130/CardDefs.Bacon.xml`（`enumID=N name=...`）与
#     `reversed/net/key_enums.json`（客户端 GAME_TAG 枚举）一致：
#       1 → 2, 2 → 3, 3 → 2889, 4 → 2919, 5 → 2920（另有 6 → 2921）。
#     **注意**：早期分析误以为官方值 = 1068..1072；实际 1068/1069/1070
#     并不在客户端 GAME_TAG 枚举里（是引擎内部自用数值），与官方脚本
#     数据**无对应关系**。本命名空间采用官方真实值，避免同类误判。
#   * 这些数值会出现在 Power.log 的 `tag=2/3/2889/2919/2920` 与
#     CardDefs 的 `TAG_SCRIPT_DATA_NUM_n` 中，且部分卡会**动态改写**
#     （累计购买/死亡/亡语数）。
#   * 无论是否撞号，本批都把脚本数据放**独立存储**（`Entity._script_data`），
#     不混入 `Entity.tags`——避免与 `GameTag` 内部语义互相污染。
#   * 读取优先级（约定）：动态字典值 > CardDef 静态 `script_data_num_n`。
#   * 动态属性脚本（如 Eternal Knight）在动态字典有值时以官方当前值为准。
class ScriptDataNum(IntEnum):
    """官方 ``TAG_SCRIPT_DATA_NUM_1..5`` 的独立命名空间（官方真实 enumID）。

    证据：`CardDefs.Bacon.xml`（255130）与 `reversed/net/key_enums.json`
    的 `GAME_TAG` 枚举一致：NUM_1=2 / NUM_2=3 / NUM_3=2889 / NUM_4=2919 /
    NUM_5=2920（NUM_6=2921 未纳入本批）。
    """

    NUM_1 = 2
    NUM_2 = 3
    NUM_3 = 2889
    NUM_4 = 2919
    NUM_5 = 2920


#: 官方 enumID → 命名空间枚举（日志 tag=1068 → ScriptDataNum.NUM_1）
OFFICIAL_TAG_TO_SCRIPT_DATA_NUM: Dict[int, "ScriptDataNum"] = {
    int(member): member for member in ScriptDataNum
}

#: 命名空间枚举 → 官方 enumID（序列化/回写日志用）
SCRIPT_DATA_NUM_TO_OFFICIAL_TAG: Dict["ScriptDataNum", int] = {
    member: int(member) for member in ScriptDataNum
}

#: 动态属性脚本可读取的「当前值」约定索引：
#:   NUM_DYNAMIC_COUNT = NUM_3 —— 动态累计计数（Eternal Knight 族死亡数、
#:   同类"本局累计"脚本的官方当前值）；由外部注入或脚本生产点写入。
NUM_DYNAMIC_COUNT = ScriptDataNum.NUM_3
