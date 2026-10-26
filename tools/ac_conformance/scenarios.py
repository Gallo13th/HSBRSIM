"""场景矩阵：机制级 + 卡牌级 + 经济/流程。

每个场景有稳定 id（AC-xx 台账引用它）与 `expected`（本审计基线判定）。
`expected` 只用于 pytest 回归：若未来引擎修复/回归导致判定变化，测试会
失败并提示更新台账——它不是「期望引擎正确」的断言，而是审计结论快照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


def U(atk: int, hp: int, *kws: str, tier: int = 1) -> Dict[str, Any]:
    return {"atk": atk, "hp": hp, "kws": list(kws), "tier": tier}


@dataclass
class Duel:
    """合成随从对战场景（不依赖卡牌数据）。"""
    id: str
    title: str
    a: List[Dict[str, Any]]
    b: List[Dict[str, Any]]
    kind: str = "duel"
    group: str = "combat"
    turn: int = 1
    alive: int = 8
    tier_a: int = 1
    tier_b: int = 1
    check_first_attacker: bool = False
    expected: str = "MATCH"
    why: str = ""
    unsupported_reason: str = ""


@dataclass
class CardDuel:
    """真实卡牌对战场景（两版本共享且卡面数据一致）。"""
    id: str
    title: str
    card_a: List[str]
    card_b: List[str]
    kind: str = "card_duel"
    group: str = "card"
    turn: int = 1
    alive: int = 8
    tier_a: int = 1
    tier_b: int = 1
    golden_a: List[bool] = field(default_factory=list)
    golden_b: List[bool] = field(default_factory=list)
    units_a: List[Dict[str, Any]] = field(default_factory=list)
    units_b: List[Dict[str, Any]] = field(default_factory=list)
    expected: str = "MATCH"
    why: str = ""
    unsupported_reason: str = ""


@dataclass
class Economy:
    """经济/规则常量场景：比较两侧探针 dict 中的某一组值/行为。"""
    id: str
    title: str
    keys: List[str]
    kind: str = "economy"
    group: str = "economy"
    expected: str = "MATCH"
    why: str = ""


@dataclass
class Flow:
    """整局流程不变量场景（两引擎各自跑完整对局，比较不变量而非具体结果）。"""
    id: str
    title: str
    kind: str = "flow"
    group: str = "flow"
    expected: str = "MATCH"
    why: str = ""


# ══════════════════════════════════════════════════════════════════════
# 1. 战斗核心机制（合成随从；tier 与 taverngym 白板卡一致，伤害公式可比）
# ══════════════════════════════════════════════════════════════════════

COMBAT: List[Duel] = [
    Duel("C01", "圣盾吸收一次攻击（2/2 DS vs 1/1）",
         [U(2, 2, "DIVINE_SHIELD")], [U(1, 1)],
         why="圣盾抵消第一次伤害后攻击者存活；胜方伤害=酒馆1+token tier1"),
    Duel("C02", "圣盾+嘲讽 vs 大身材（吸收后被击穿）",
         [U(3, 3, "DIVINE_SHIELD", "TAUNT")], [U(10, 10)],
         why="嘲讽强制被攻击；圣盾只吸收一次，10/10 两击杀死 3/3"),
    Duel("C03", "嘲讽优先于普通随从",
         [U(1, 1)], [U(10, 1, "TAUNT"), U(5, 5)],
         why="唯一攻击者只能打嘲讽；胜方原始伤害 1+10=11 → turn1 上限 5"),
    Duel("C04", "潜行随从不可被选中",
         [U(2, 2)], [U(1, 1, "STEALTH"), U(3, 3)],
         why="潜行者不能被指定为目标；2/2 只能打 3/3 并战死"),
    Duel("C05", "顺劈同时命中相邻随从",
         [U(3, 3, "CLEAVE")], [U(2, 2), U(2, 2), U(2, 2)],
         why="顺劈 3 点同时对目标与相邻生效，三只 2/2 全灭，胜方 3/3 存活"),
    Duel("C06", "剧毒同归于尽（平局）",
         [U(1, 1, "POISONOUS")], [U(9, 9)],
         why="剧毒伤害即时生效 → 双方死亡 → 平局且无英雄伤害"),
    Duel("C07", "烈毒同归于尽（平局）",
         [U(1, 1, "VENOMOUS")], [U(9, 9)],
         why="烈毒与剧毒战斗语义一致（伤害后销毁）"),
    Duel("C08", "剧毒 vs 圣盾（圣盾免疫毒杀）",
         [U(1, 1, "POISONOUS")], [U(9, 9, "DIVINE_SHIELD")],
         why="圣盾吸收的伤害不触发剧毒；攻击者被 9/9 反杀"),
    Duel("C09", "风怒镜像（同归于尽）",
         [U(2, 2, "WINDFURY")], [U(2, 2)],
         why="风怒只影响攻击次数，1v1 双方同时伤害 → 平局"),
    Duel("C10", "超级风怒连续 4 次攻击",
         [U(2, 10, "MEGA_WINDFURY")], [U(3, 3)],
         why="超级风怒一个轮次内攻击四次；2/10 应存活"),
    Duel("C11", "复生随从战后以 1 血重立",
         [U(3, 3)], [U(2, 1, "REBORN")],
         why="复生体 1 血重立并继续战斗，2 攻最终换掉 3/3"),
    Duel("C12", "全员 0 攻 —— 平局且无伤害",
         [U(0, 5)], [U(0, 5)],
         why="双方均无可攻击者 → 平局"),
    Duel("C13", "0 攻 vs 1 攻（0 攻方被白吃）",
         [U(0, 5)], [U(1, 1)],
         why="0 攻随从不攻击；1/1 反复攻击直到 5 血耗尽"),
    Duel("C14", "嘲讽+潜行混合（嘲讽仍强制）",
         [U(1, 1)], [U(5, 5, "TAUNT"), U(2, 2, "STEALTH")],
         why="嘲讽存在时攻击者必须打嘲讽，潜行不参与"),
    Duel("C15", "turn1 伤害上限 5（原始 6）",
         [U(1, 10, tier=5)], [U(0, 1)],
         why="胜方酒馆1+存活 tier5=原始 6，第 1 回合上限 5"),
    Duel("C16", "turn4 伤害上限 10（原始 11）",
         [U(1, 10, tier=5), U(1, 10, tier=5)], [U(0, 1)], turn=4,
         why="胜方酒馆1+2×tier5=原始 11，turn4 上限 10"),
    Duel("C17", "turn8 伤害上限 15（原始 26）",
         [U(1, 10, tier=5), U(1, 10, tier=5), U(1, 10, tier=5),
          U(1, 10, tier=5)],
         [U(0, 1)], turn=8,
         why="四级 tier5 token=20 + 酒馆1 = 原始 21，turn8 上限 15"),
    Duel("C18", "存活≤4 解除伤害上限（原始 21 全额）",
         [U(1, 10, tier=5), U(1, 10, tier=5), U(1, 10, tier=5),
          U(1, 10, tier=5)],
         [U(0, 1)], turn=8, alive=4,
         expected="UNSUPPORTED",
         unsupported_reason=(
             "AutoTavern Python API 无法把 8 人局改成 4 人存活："
             "combat_preview 的伤害上限按真实 lobby 存活人数计算（仍为 8），"
             "不能注入 alive=4；hsrl2 侧 alive_count=4 可观察到无上限 21 伤害。"
             "规则常量本身一致（见 E14）。"),
         why="存活≤4 时无上限；hsrl2 观测到 21 全额（参照侧不可构造，UNSUPPORTED）"),
    Duel("C19", "token tier 计入伤害（tier3 token）",
         [U(9, 9, tier=3)], [U(1, 1)],
         why="胜方伤害=酒馆1+tier3=4"),
    Duel("C20", "酒馆等级计入伤害（胜方 tier4）",
         [U(2, 2)], [U(1, 1)], tier_a=4,
         why="胜方伤害=酒馆4+tier1=5"),
    Duel("C21", "顺劈+嘲讽（顺劈波及后排）",
         [U(4, 4, "CLEAVE")], [U(1, 1, "TAUNT"), U(5, 5)],
         why="顺劈对嘲讽目标与相邻的 5/5 同时造成 4 点"),
    Duel("C22", "复生+圣盾（复生体恢复圣盾，F-14 回归）",
         [U(3, 3)], [U(2, 1, "DIVINE_SHIELD", "REBORN")],
         why="官方 36.6.3/F-14：复生体恢复卡面基础关键词（圣盾）"),
    Duel("C23", "先攻：随从多的一方先攻",
         [U(1, 1), U(1, 1)], [U(2, 2)],
         check_first_attacker=True,
         why="AutoTavern combat.rs:316 与 hsrl2 C10 同规则（数量多者先）"),
    Duel("C24", "先攻：数量相同 → 参照按酒馆等级高者先攻 [AC-01→CONVENTION_DIFF]",
         [U(2, 2)], [U(2, 2)], tier_a=1, tier_b=5,
         check_first_attacker=True, expected="CONVENTION_DIFF",
         why="AutoTavern 采用等级优先约定（combat.rs:316）；官方 wiki 现行文本为"
             "「同数量随机」；无决定性证据，HSBRSIM 保持随机（2026-10-26 Lead 裁定"
             "改判 CONVENTION_DIFF，详见台账 AC-01）"),
    Duel("C25", "先攻：数量/等级都相同 → 随机（约定差异容忍）",
         [U(1, 1)], [U(1, 1)],
         check_first_attacker=True,
         why="两引擎都随机 → 只要求双方都出现两侧先攻"),
    Duel("C26", "对照：同属性无脚本白板（5/4 tier3 + 3×1/3 vs 3×2/2）",
         [U(5, 4, tier=3), U(1, 3), U(1, 3), U(1, 3)],
         [U(2, 2), U(2, 2), U(2, 2)], turn=8,
         why="AC-04 控制实验：把 BG34_405 换成同属性无脚本白板后两侧伤害集合"
             "应一致（用于隔离 AT 侧脚本 405 的异常）"),
]


# ══════════════════════════════════════════════════════════════════════
# 2. 卡牌级（两版本共享、卡面数据一致；见 data_diff.json）
# ══════════════════════════════════════════════════════════════════════

CARDS: List[CardDuel] = [
    CardDuel("K01", "BG28_300 Harmless Bonehead 亡语召唤 2 只 1/1",
             ["BG28_300"], [], why="死亡结算：移除→亡语召唤，召唤物参与后续攻击"),
    CardDuel("K02", "BG25_354 Titus 使亡语额外触发（Bonehead 召唤 4 只）",
             ["BG28_300", "BG25_354"], ["BGS_034"],
             why="Titus '亡语额外触发一次' 的倍率语义（参照 config 文档）"),
    CardDuel("K03", "BG29_611 Cord Puller 圣盾+亡语召唤 1/1",
             ["BG29_611"], [], why="圣盾吸收与亡语召唤顺序"),
    CardDuel("K04", "BG25_010 Handless Forsaken 亡语召唤复生 Hand",
             ["BG25_010"], [], why="亡语先于复生结算，召唤物带 Reborn"),
    CardDuel("K05", "BGS_034 青铜守卫 (DS+Reborn) vs BGS_119 爆裂飓风 (DS+Windfury)",
             ["BGS_034"], ["BGS_119"],
             why="复生体恢复圣盾（F-14）+ 风怒攻击次数"),
    CardDuel("K06", "BGS_131 Deadly Spore 烈毒 vs 9/9",
             ["BGS_131"], [], why="烈毒同归于尽"),
    CardDuel("K07", "BG23_318 Leeroy 亡语灭杀击杀者",
             ["BG23_318"], [], why="亡语 '消灭击杀它的随从' 双向死亡 → 平局"),
    CardDuel("K08", "BG36_620 Boom-in-a-Box 战斗开始 AoE 3",
             ["BG36_620"], ["BGS_034"],
             why="Start of Combat 阶段先于先攻判定"),
    CardDuel("K09", "BG31_803 Buzzing Vermin 嘲讽+亡语召唤甲虫",
             ["BG31_803"], [], why="嘲讽目标选择 + 亡语召唤位置"),
    CardDuel("K10", "BG24_500 Amber Guardian 战斗开始给龙圣盾+2/+2",
             ["BGS_034", "BG24_500"], ["BGS_119"],
             why="SoC 增益与圣盾（Bronze Warden 为龙）"),
    CardDuel("K11", "BG25_022 Scarlet Skull 复生+亡语给亡灵+1/+2",
             ["BG25_022"], [], why="复生/亡语的死亡结算顺序"),
    CardDuel("K12", "BGS_040 Nadina 亡语给 3 条友方龙圣盾",
             ["BGS_040", "BGS_034"], ["BGS_119", "BGS_119"],
             why="亡语群体圣盾；BGS_034 本身是龙"),
    CardDuel("K13", "BG25_013 Rot Hide Gnoll 本场死亡计数动态攻击",
             ["BG25_013"], ["BG28_300"],
             why="战内动态属性（+1 攻/本场死亡随从）"),
    CardDuel("K14", "BG25_016 Sin'dorei Straight Shot 圣盾风怒 Rally 移除关键词",
             ["BG25_016"], ["BGS_034"],
             why="Rally（攻击时）触发器 + 关键词移除"),
    CardDuel("K15", "BG34_405 Relentless Deflector 复仇(3)重获圣盾",
             ["BG34_405"], [], units_a=[U(1, 3), U(1, 3), U(1, 3)],
             units_b=[U(2, 2), U(2, 2), U(2, 2)],
             expected="CONVENTION_DIFF",
             why="AC-04（参照侧脚本行为异常，非 hsrl2 分歧）：同胜负下胜方可达"
                 "伤害集合不同（AT {2,3,5} vs HS {3,4,5}）。engine-fixer F-35 证据："
                 "405 的 Avenge/圣盾/嘲讽在 400 局中从未触发；换成同属性无脚本白板"
                 "后两侧一致（本套件 C26 对照 MATCH）；只有 AT 侧“带脚本 405”时"
                 "分布异常 → 属参照引擎侧脚本候选问题，hsrl2 与白板一致，不改 hsrl2"),
    CardDuel("K16", "亡语连锁死亡结算顺序（Bonehead + Cord Puller 同场）",
             ["BG28_300", "BG29_611"], [], golden_a=[False, False],
             units_b=[U(3, 3, "DIVINE_SHIELD")],
             why="多个亡语按死亡位置/顺序结算，召唤物参与后续攻击"),
]


# ══════════════════════════════════════════════════════════════════════
# 3. 招募经济 / 规则常量（探针见 tavern_api.economy_probe / hsrl2_api）
# ══════════════════════════════════════════════════════════════════════

ECONOMY: List[Economy] = [
    Economy("E01", "起始金币 3", ["start_gold"]),
    Economy("E02", "金币收入曲线 3/4/5/6/7（上限 10）", ["gold_progression"]),
    Economy("E03", "购买随从费用与行为扣费", ["buy_cost", "buy_gold_delta"]),
    Economy("E04", "出售随从返还 1 金", ["sell_value", "sell_gold_delta"]),
    Economy("E05", "刷新费用 1 金", ["refresh_cost"]),
    Economy("E06", "各酒馆等级随从槽位 3/4/4/5/5/6",
            ["shop_minion_slots", "shop_by_tier"]),
    Economy("E07", "酒馆法术槽位 1", ["shop_spell_slots"]),
    Economy("E08", "基础升级费阶梯 T2..T6 = 5/7/8/11/11 [AC-03 已修复]",
            ["upgrade_costs", "upgrade_by_tier"],
            why="官方 wiki/参照 config：T5=11、T6=11；hsrl2 修复后常量与行为均一致"
                "（2026-10-26 engine-fixer）"),
    Economy("E09", "每回合升级费衰减 1", ["upgrade_discount_per_turn"]),
    Economy("E10", "各等级随从池份数 15/15/13/11/9/7/5 [AC-02 已修复]",
            ["pool_copies_by_tier"],
            why="官方 wiki/参照 config：T1=15；hsrl2 修复后常量一致"
                "（2026-10-26 engine-fixer）"),
    Economy("E11", "各等级酒馆法术池份数 5/7/9/11/9/7",
            ["spell_copies_by_tier"]),
    Economy("E12", "棋盘/手牌上限 7/10", ["board_size", "hand_size"]),
    Economy("E13", "三连所需份数 3", ["triple_copies"]),
    Economy("E14", "伤害上限阶梯 (1,5)/(4,10)/(8,15) 与解除阈值",
            ["damage_caps", "damage_cap_until_alive", "max_regular_tier"]),
]


# ══════════════════════════════════════════════════════════════════════
# 4. 流程不变量（整局）
# ══════════════════════════════════════════════════════════════════════

FLOW: List[Flow] = [
    Flow("F01", "AutoTavern 整局 bot 对局：名次唯一/无崩溃/结束"),
    Flow("F02", "hsrl2 整局随机对局：50 回合内结束/无崩溃"),
]


ALL_SCENARIOS = COMBAT + CARDS + ECONOMY + FLOW
