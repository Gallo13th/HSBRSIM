"""枚举 — 与 Hearthstone 协议 enumID 数值对齐（XML 权威）。

命名遵循 HearthDb 惯例；未命名的新标签以数字注释说明。
"""

from __future__ import annotations

from enum import IntEnum


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
    NONE = 0


DBF_RACE_TO_ENUM = {
    11: Race.UNDEAD, 14: Race.MURLOC, 15: Race.DEMON, 17: Race.MECH,
    18: Race.ELEMENTAL, 20: Race.BEAST, 23: Race.PIRATE, 24: Race.DRAGON,
    26: Race.ALL, 43: Race.QUILBOAR, 92: Race.NAGA,
}


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
    IMMUNE = 49
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
