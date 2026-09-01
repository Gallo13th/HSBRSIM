"""规则常量 — 单一事实来源。

每个常量标注出处（docs/BATTLEGROUNDS_RULES.md §x，简称 RULES）。
修改任何数值前必须核对 RULES 与官方补丁说明。
"""

from __future__ import annotations

# ── 金币经济 (RULES §1.4) ─────────────────────────────────────────
GOLD_START = 3            # 第 1 回合基础收入
GOLD_INCOME_CAP = 10      # 自然增长上限（第 8 回合达到 10）
GOLD_HOLD_CAP = 99        # 持有上限（效果获得可超过当回合基础量）
MINION_BUY_COST = 3       # 购买随从
MINION_SELL_VALUE = 1     # 出售随从返还（金色出售返还池 3 份但金币仍 1）
REFRESH_COST = 1          # 刷新酒馆
FREEZE_COST = 0           # 冻结免费 (RULES §6.17)


def gold_base_income(turn: int, income_cap: int = GOLD_INCOME_CAP) -> int:
    """回合开始的基础金币收入: turn1=3, +1/回合, 封顶 income_cap
    （默认 10; Strike Oil 类效果经 hero.income_cap 提升）。"""
    return min(GOLD_START + turn - 1, income_cap)


# ── 酒馆等级 (RULES §3.1) ─────────────────────────────────────────
TAVERN_MAX_TIER = 6       # 常规上限（Tier 7 仅特殊效果可达）
BASE_UPGRADE_COSTS = {2: 5, 3: 7, 4: 8, 5: 9, 6: 10, 7: 11}
UPGRADE_DECAY_PER_TURN = 1   # 每回合未升级 -1
UPGRADE_COST_FLOOR = 0       # 下限 0 金（RULES §3.1，旧实现错误地取 1）

# ── 酒馆展示数 (RULES §2.4) ───────────────────────────────────────
TAVERN_OFFERS = {1: 3, 2: 4, 3: 4, 4: 5, 5: 5, 6: 6}

# ── 区域容量 (RULES §3.3) ─────────────────────────────────────────
BOARD_SIZE = 7
HAND_SIZE = 10

# ── 池副本数 (RULES §2.2) ─────────────────────────────────────────
POOL_COPIES_BY_TIER = {1: 16, 2: 15, 3: 13, 4: 11, 5: 9, 6: 7, 7: 5}

# ── 伤害 (RULES §5) ───────────────────────────────────────────────
DAMAGE_CAP_BY_TURN = 5    # 第 1-3 回合
DAMAGE_CAP_T4_T7 = 10     # 第 4-7 回合
DAMAGE_CAP_T8_PLUS = 15   # 第 8 回合及以后
DAMAGE_CAP_REMOVED_AT_PLAYERS = 4   # 剩 4 人解除
TOKEN_TECH_LEVEL = 1      # token 计 T1


def damage_cap(turn: int, alive_players: int) -> int | None:
    """单次战斗伤害上限; None = 无上限 (RULES §5.2)。"""
    if alive_players <= DAMAGE_CAP_REMOVED_AT_PLAYERS:
        return None
    if turn <= 3:
        return DAMAGE_CAP_BY_TURN
    if turn <= 7:
        return DAMAGE_CAP_T4_T7
    return DAMAGE_CAP_T8_PLUS


# ── 战斗循环保护 ──────────────────────────────────────────────────
COMBAT_MAX_ATTACK_ROUNDS = 2000    # 超限抛异常（旧实现静默平局）
DEATH_MAX_WAVES = 100              # 死亡波次上限（超限抛异常）
QUEUE_MAX_ACTIONS = 20000          # 单次 resolve 动作上限（超限抛异常）

# ── 三连 (RULES §10) ──────────────────────────────────────────────
TRIPLE_COPIES_NEEDED = 3
GOLDEN_POOL_RETURN_COPIES = 3      # 金色出售/淘汰返还池份数

# ── 酒馆法术 (RULES §3.6) ─────────────────────────────────────────
TAVERN_SPELLS_PER_REFRESH = 1      # 每次刷新固定 1 张法术

# ── S14: Dark Gifts (官方 36.2 赛季公告) ──────────────────────────
DARK_GIFT_START_TURN = 3           # 第 3 回合起可用
DARK_GIFT_COST = 3                 # 每次 3 金
DARK_GIFT_USES_PER_TURN = 1        # 每回合 1 次
DARK_GIFT_USES_PER_GAME = 3        # 每局最多 3 次
# 提供档位曲线（官方 36.2 dev post: turn → 可随从 tier 列表）
DARK_GIFT_TIERS = {
    3: [2], 4: [2, 3], 5: [3], 6: [3, 4], 7: [4],
    8: [4, 5], 9: [4, 5, 6], 10: [5, 6],
}
DARK_GIFT_TIERS_DEFAULT = [6]      # turn 11 及以后
# S14 Lockbox（BG36_520t: "In 5 turns, break this open..." num(0)=5）
LOCKBOX_CARD_ID = "BG36_520t"
LOCKBOX_TURNS = 5                  # data/bg_cards.xml num(0) 权威
# S14 Demonology Fodder（BG35_150t Demon Fodder，S13 遗留 token，
# "Add a Fodder to your next 3 Refreshes"）
FODDER_CARD_ID = "BG35_150t"
FODDER_REFRESHES = 3               # Demonology 文本 "next 3 Refreshes"

# ── 伙伴 (RULES §9.4) ─────────────────────────────────────────────
BUDDY_COST_WIN_DECAY = 3           # 胜/平局费用 -3
BUDDY_COST_LOSS_DECAY = 2          # 失败 -2

# ── Bounty 卡集（36.2.2 数据核实: BG33_811..815 五张 T3 法术）─────
# "Get a random Bounty" 类效果的候选全集
BOUNTY_SPELL_IDS = frozenset({
    "BG33_811", "BG33_812", "BG33_813", "BG33_814", "BG33_815",
})

# ── 英雄基础 (RULES §1.3) ─────────────────────────────────────────
HERO_BASE_HEALTH = 30
