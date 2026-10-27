"""标准观测 profile（AutoTavern / TavernGym 3227 floats + 124 cards）。

背景与目标
----------
P2 决策：HSBRSIM 的**标准观测 profile** 采用 AutoTavern（AT）TavernGym 的
固定观测编码——``features``（3227 个 f32）+ ``cards``（124 个 i32 卡牌
embedding 下标），与上游 ``taverngym.layout()`` 逐项一致，从而：

1. 与 AT 引擎/策略/数据**逐位可比**（同数据版本下同一浮点块/卡牌槽位含义相同）；
2. 固定形状观测便于统一策略编码器与向量化训练；
3. 训练/搜索只使用这一套 3227+124 观测；旧实体 token 观测已删除。

本模块**不依赖** numpy 以外的第三方库；常量来自 AutoTavern 源码
``crates/taverngym/src/obs.rs``（TavernGym v1.0.0），
金标测试 ``tests/test_obs_std.py`` 逐项对照 ``hsbg_engine.layout()`` /
``OBS_FLOATS`` / ``OBS_CARDS`` / ``N_CARDS``。

数据版本契约（重要）
--------------------
* **布局**（3227 / 124 及各块宽度、字段语义）由**引擎实现**决定，同一
  taverngym 版本内固定；
* **卡牌 id 词表**由**数据版本**决定：``cards[i]`` 是"卡牌 embedding 下标"
  （``CardId + 1``，0 = 空槽），下标 → 卡 id 的映射来自该构建的
  ``crates/taverngym/data/cards.json``（36.6.3 构建 ``N_CARDS=3984``，含空位，
  实际 3983 张）。HSBRSIM 数据基线是 37.0.0.255790，**跨数据版本时卡牌下标
  不可直接比较/复用**（需要按卡 id 重新映射；映射表由数据管线提供）。
* 因此"与 AT 逐位可比"的严格条件是：**同引擎版本 + 同数据版本**（或已完成
  卡牌 id 对齐）。浮点块的**位置**含义跨版本稳定，卡牌块的**内容**不稳定。

浮点块（features，3227）
------------------------
==========  =======  ==========================================
块           宽度     内容
==========  =======  ==========================================
global       53       全局标量（42 项标量 + 11 个 lobby 种族位）
quests       3×2      3 个任务槽（present, progress/goal）
pending      9        pending 种类 one-hot（9 类）
board        7×31     己方棋盘随从（``MINION_F=31``）
hand         10×40    手牌物品（``ITEM_F=40``，随从/法术）
shop         8×40     酒馆物品（``ITEM_F=40``，含当前价格）
choices      16×40    选择选项（``ITEM_F=40``）
opponents    7×9      对手公开摘要（``OPP_F=9``）
opp_boards   7×7×31   与各对手上一场见到的战团（7 对手 × 7 随从）
==========  =======  ==========================================

卡牌块（cards，124）：hero(1) + hero_power(2) + deity(1) + pending_source(1)
+ quests(3×3) + secrets(5) + board(7) + hand(10) + shop(8) + choices(16)
+ trinkets(8) + opponent_heroes(7) + opponent_boards(7×7) = 124。

只读解码
--------
:func:`decode_blocks` 把 ``features``（bytes/little-endian f32/ndarray/list）
与 ``cards``（bytes/little-endian i32/ndarray/list）切成只读块视图：
``dict[str, np.ndarray]``，形状见 :data:`FLOAT_BLOCKS` / :data:`CARD_BLOCKS`。
返回的视图 ``writeable=False``（bytes 输入天然只读；ndarray 输入也不修改原
数组），不复制数据（``copy=True`` 可显式复制）。非法长度/dtype 抛
``ValueError``。

与 AT 的可比性契约（摘要）
--------------------------
1. ``layout()`` 的 32 项（名称+数值）与 ``taverngym.layout()`` **逐项相等**；
2. ``OBS_FLOATS=3227``、``OBS_CARDS=124``、``N_ACTIONS=245`` 与上游一致；
3. 各浮点块切片偏移与上游 ``obs.rs`` 的 ``push_*`` 顺序一致；
4. 卡牌块偏移与上游 ``OBS_CARDS`` 注释顺序一致；
5. 同数据版本下 ``cards`` 下标可直接互认；跨数据版本必须重映射（见上）。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from hsbg.env.action_space_std import (
    A_ACTIVATE,
    A_BUY,
    A_CANCEL,
    A_CHOOSE,
    A_DARK_GIFT,
    A_END,
    A_FREEZE,
    A_HERO_POWER,
    A_MAGNETIZE,
    A_MOVE,
    A_PLAY,
    A_REFRESH,
    A_SELL,
    A_UPGRADE,
    N_ACTIONS,
    N_BOARD,
    N_CHOICE,
    N_HAND,
    N_POS,
    N_POWERS,
    N_SHOP,
)

__all__ = [
    # 布局常量（与 taverngym.layout() 逐项一致）
    "MINION_F", "ITEM_F", "GLOBAL_F", "N_QUESTS", "QUEST_F", "N_SECRETS",
    "OPP_F", "N_OPP", "PENDING_KINDS", "N_SHOP", "N_BOARD", "N_HAND",
    "N_CHOICE", "N_POS", "N_POWERS", "N_ACTIONS", "OBS_FLOATS", "OBS_CARDS",
    "N_LOBBIES", "RACES_COUNT",
    # 卡牌词表
    "EMPTY_CARD_INDEX", "N_CARDS_REFERENCE", "N_CARDS_NOTE",
    # layout()
    "LAYOUT_ITEMS", "layout", "LAYOUT",
    # 浮点块
    "FLOAT_BLOCKS", "FLOAT_BLOCK_SLICES", "SLICE_GLOBAL", "SLICE_QUESTS",
    "SLICE_PENDING", "SLICE_BOARD", "SLICE_HAND", "SLICE_SHOP",
    "SLICE_CHOICES", "SLICE_OPPONENTS", "SLICE_OPP_BOARDS",
    # 卡牌块
    "CARD_BLOCKS", "CARD_BLOCK_SLICES", "SLICE_CARD_HERO",
    "SLICE_CARD_POWERS", "SLICE_CARD_DEITY", "SLICE_CARD_PENDING_SOURCE",
    "SLICE_CARD_QUESTS", "SLICE_CARD_SECRETS", "SLICE_CARD_BOARD",
    "SLICE_CARD_HAND", "SLICE_CARD_SHOP", "SLICE_CARD_CHOICES",
    "SLICE_CARD_TRINKETS", "SLICE_CARD_OPP_HEROES", "SLICE_CARD_OPP_BOARDS",
    # 字段偏移/顺序表
    "GLOBAL_FIELD_INDEX", "GLOBAL_FIELD_SCALE", "GLOBAL_FIELD_NAMES",
    "MINION_PRESENT", "MINION_ATK", "MINION_HP", "MINION_MAX_HP",
    "MINION_TIER", "MINION_GOLDEN", "MINION_ATTACHED", "MINION_SHIELD_HITS",
    "MINION_KEYWORDS", "MINION_RACES", "ITEM_PRESENT", "ITEM_IS_MINION",
    "ITEM_COST", "ITEM_LOCKED", "ITEM_TEMPORARY", "ITEM_COMBINED",
    "ITEM_FROZEN", "ITEM_KEPT", "ITEM_MARKED", "ITEM_MINION",
    "SPELL_PRESENT", "SPELL_DATA", "SPELL_TIER",
    "OPP_PRESENT", "OPP_ALIVE", "OPP_HEALTH", "OPP_ARMOR", "OPP_TIER",
    "OPP_SEEN_BOARD_LEN", "OPP_PLACEMENT", "OPP_IS_LAST", "OPP_IS_NEXT",
    "RACE_NAMES", "KEYWORD_NAMES", "PENDING_KIND_NAMES",
    # 解码
    "decode_blocks", "block_shapes",
]


# ══════════════════════════════════════════════════════════════════════
# 布局常量（与 taverngym.layout() 逐项一致；顺序 = 上游 layout() 顺序）
# ══════════════════════════════════════════════════════════════════════

#: 单个随从块宽度：8 头字段 + 12 关键词位 + 11 种族位 = 31
MINION_F = 8 + 12 + 11
#: 单个物品块宽度：9 头字段 + MINION_F = 40
ITEM_F = 9 + MINION_F
#: 全局标量块宽度：42 标量 + 11 lobby 种族位 = 53
GLOBAL_F = 42 + 11
#: 任务槽数量 / 每个任务块宽度
N_QUESTS = 3
QUEST_F = 2
#: 已打出奥秘的展示槽位数（Hearthstone 上限 5）
N_SECRETS = 5
#: 单个对手摘要块宽度
OPP_F = 9
#: 对手数量（8 人局 - 自己）
N_OPP = 7
#: pending choice 种类 one-hot 宽度
PENDING_KINDS = 9

#: 各块宽度（复用动作空间常量，保证与动作 layout 同源）
#: 注：``N_SHOP/N_BOARD/N_HAND/N_CHOICE/N_POS/N_POWERS/N_ACTIONS`` 由
#: ``hsbg.env.action_space_std`` 提供（与 AT 逐位一致）。
OBS_FLOATS = (
    GLOBAL_F
    + N_QUESTS * QUEST_F
    + PENDING_KINDS
    + N_BOARD * MINION_F
    + N_HAND * ITEM_F
    + N_SHOP * ITEM_F
    + N_CHOICE * ITEM_F
    + N_OPP * OPP_F
    + N_OPP * N_BOARD * MINION_F
)
#: 卡牌块宽度：hero/powers/deity/pending_source/quests/secrets/board/hand/
#: shop/choices/trinkets/opp_heroes/opp_boards
OBS_CARDS = (
    1
    + N_POWERS
    + 2
    + 3 * N_QUESTS
    + N_SECRETS
    + N_BOARD
    + N_HAND
    + N_SHOP
    + N_CHOICE
    + 8
    + N_OPP
    + N_OPP * N_BOARD
)
#: lobby 种族位数（= ``Races::COUNT``）
RACES_COUNT = 11
N_LOBBIES = RACES_COUNT

#: 卡牌 embedding 下标 0 = 空槽；``cards[i] = CardId + 1``
EMPTY_CARD_INDEX = 0
#: 当前 37.0.0.255790 构建的 ``hsbg_engine.N_CARDS``（= 3983 张卡 + 空位 0）。
#: **数据版本相关**：换数据包/重编引擎后该值会变；运行时应优先读
#: ``hsbg_engine.N_CARDS``，本常量仅作文档基线。
N_CARDS_REFERENCE = 3984
N_CARDS_NOTE = (
    "N_CARDS = 1 + 当前构建卡表大小（0 号为空槽）：37.0.0.255790 构建 = 3983 张卡 + 空位 = 3984，"
    "旧基线 36.6.3.253932 的 N_CARDS 同为 3984。两版卡表总数相同但**内容/顺序不同**，"
    "因此 cards 下标不能跨数据版本复用，必须按卡 id 重新映射。"
)

#: ``layout()`` 的 32 项（名称, 数值）——顺序与上游 ``taverngym.layout()`` 相同。
LAYOUT_ITEMS: Tuple[Tuple[str, int], ...] = (
    ("MINION_F", MINION_F),
    ("ITEM_F", ITEM_F),
    ("GLOBAL_F", GLOBAL_F),
    ("N_QUESTS", N_QUESTS),
    ("QUEST_F", QUEST_F),
    ("N_SECRETS", N_SECRETS),
    ("OPP_F", OPP_F),
    ("N_OPP", N_OPP),
    ("PENDING_KINDS", PENDING_KINDS),
    ("N_SHOP", N_SHOP),
    ("N_BOARD", N_BOARD),
    ("N_HAND", N_HAND),
    ("N_CHOICE", N_CHOICE),
    ("N_POS", N_POS),
    ("N_POWERS", N_POWERS),
    ("A_END", A_END),
    ("A_REFRESH", A_REFRESH),
    ("A_FREEZE", A_FREEZE),
    ("A_UPGRADE", A_UPGRADE),
    ("A_HERO_POWER", A_HERO_POWER),
    ("A_DARK_GIFT", A_DARK_GIFT),
    ("A_CANCEL", A_CANCEL),
    ("A_BUY", A_BUY),
    ("A_SELL", A_SELL),
    ("A_ACTIVATE", A_ACTIVATE),
    ("A_CHOOSE", A_CHOOSE),
    ("A_PLAY", A_PLAY),
    ("A_MAGNETIZE", A_MAGNETIZE),
    ("A_MOVE", A_MOVE),
    ("N_ACTIONS", N_ACTIONS),
    ("OBS_FLOATS", OBS_FLOATS),
    ("OBS_CARDS", OBS_CARDS),
)
#: ``layout()`` 的 dict 形式（名称 → 数值）
LAYOUT: Dict[str, int] = dict(LAYOUT_ITEMS)


def layout() -> Tuple[Tuple[str, int], ...]:
    """AT ``taverngym.layout()`` 的等价物（32 项，逐项相同；返回 tuple 副本）。"""
    return LAYOUT_ITEMS


# ══════════════════════════════════════════════════════════════════════
# 浮点块切片（features）
# ══════════════════════════════════════════════════════════════════════


#: 浮点块 `(name, width)`（顺序 = obs.rs 的 push 顺序）
_FLOAT_BLOCK_WIDTHS: Tuple[Tuple[str, int], ...] = (
    ("global", GLOBAL_F),
    ("quests", N_QUESTS * QUEST_F),
    ("pending_kinds", PENDING_KINDS),
    ("board_minions", N_BOARD * MINION_F),
    ("hand_items", N_HAND * ITEM_F),
    ("shop_items", N_SHOP * ITEM_F),
    ("choice_items", N_CHOICE * ITEM_F),
    ("opponents", N_OPP * OPP_F),
    ("opponent_boards", N_OPP * N_BOARD * MINION_F),
)

#: 浮点块名 → slice（索引到 features 向量）
FLOAT_BLOCK_SLICES: Dict[str, slice] = {}
_off = 0
for _name, _width in _FLOAT_BLOCK_WIDTHS:
    FLOAT_BLOCK_SLICES[_name] = slice(_off, _off + _width)
    _off += _width
assert _off == OBS_FLOATS, (_off, OBS_FLOATS)

SLICE_GLOBAL = FLOAT_BLOCK_SLICES["global"]
SLICE_QUESTS = FLOAT_BLOCK_SLICES["quests"]
SLICE_PENDING = FLOAT_BLOCK_SLICES["pending_kinds"]
SLICE_BOARD = FLOAT_BLOCK_SLICES["board_minions"]
SLICE_HAND = FLOAT_BLOCK_SLICES["hand_items"]
SLICE_SHOP = FLOAT_BLOCK_SLICES["shop_items"]
SLICE_CHOICES = FLOAT_BLOCK_SLICES["choice_items"]
SLICE_OPPONENTS = FLOAT_BLOCK_SLICES["opponents"]
SLICE_OPP_BOARDS = FLOAT_BLOCK_SLICES["opponent_boards"]

#: 浮点块 `(name, slice, shape)`（shape 用于 decode_blocks 视图重塑）
FLOAT_BLOCKS: Tuple[Tuple[str, slice, Tuple[int, ...]], ...] = (
    ("global", SLICE_GLOBAL, (GLOBAL_F,)),
    ("quests", SLICE_QUESTS, (N_QUESTS, QUEST_F)),
    ("pending_kinds", SLICE_PENDING, (PENDING_KINDS,)),
    ("board_minions", SLICE_BOARD, (N_BOARD, MINION_F)),
    ("hand_items", SLICE_HAND, (N_HAND, ITEM_F)),
    ("shop_items", SLICE_SHOP, (N_SHOP, ITEM_F)),
    ("choice_items", SLICE_CHOICES, (N_CHOICE, ITEM_F)),
    ("opponents", SLICE_OPPONENTS, (N_OPP, OPP_F)),
    ("opponent_boards", SLICE_OPP_BOARDS, (N_OPP, N_BOARD, MINION_F)),
)


# ══════════════════════════════════════════════════════════════════════
# 卡牌块切片（cards）
# ══════════════════════════════════════════════════════════════════════

_CARD_BLOCK_WIDTHS: Tuple[Tuple[str, int], ...] = (
    ("card_hero", 1),
    ("card_powers", N_POWERS),
    ("card_deity", 1),
    ("card_pending_source", 1),
    ("card_quests", 3 * N_QUESTS),
    ("card_secrets", N_SECRETS),
    ("card_board", N_BOARD),
    ("card_hand", N_HAND),
    ("card_shop", N_SHOP),
    ("card_choices", N_CHOICE),
    ("card_trinkets", 8),
    ("card_opp_heroes", N_OPP),
    ("card_opp_boards", N_OPP * N_BOARD),
)

#: 卡牌块名 → slice（索引到 cards 向量）
CARD_BLOCK_SLICES: Dict[str, slice] = {}
_off = 0
for _name, _width in _CARD_BLOCK_WIDTHS:
    CARD_BLOCK_SLICES[_name] = slice(_off, _off + _width)
    _off += _width
assert _off == OBS_CARDS, (_off, OBS_CARDS)

SLICE_CARD_HERO = CARD_BLOCK_SLICES["card_hero"]
SLICE_CARD_POWERS = CARD_BLOCK_SLICES["card_powers"]
SLICE_CARD_DEITY = CARD_BLOCK_SLICES["card_deity"]
SLICE_CARD_PENDING_SOURCE = CARD_BLOCK_SLICES["card_pending_source"]
SLICE_CARD_QUESTS = CARD_BLOCK_SLICES["card_quests"]
SLICE_CARD_SECRETS = CARD_BLOCK_SLICES["card_secrets"]
SLICE_CARD_BOARD = CARD_BLOCK_SLICES["card_board"]
SLICE_CARD_HAND = CARD_BLOCK_SLICES["card_hand"]
SLICE_CARD_SHOP = CARD_BLOCK_SLICES["card_shop"]
SLICE_CARD_CHOICES = CARD_BLOCK_SLICES["card_choices"]
SLICE_CARD_TRINKETS = CARD_BLOCK_SLICES["card_trinkets"]
SLICE_CARD_OPP_HEROES = CARD_BLOCK_SLICES["card_opp_heroes"]
SLICE_CARD_OPP_BOARDS = CARD_BLOCK_SLICES["card_opp_boards"]

#: 卡牌块 `(name, slice, shape)`
#: ``card_quests`` 形状 (N_QUESTS, 3) = 每槽 [quest, reward, owned_reward]
CARD_BLOCKS: Tuple[Tuple[str, slice, Tuple[int, ...]], ...] = (
    ("card_hero", SLICE_CARD_HERO, (1,)),
    ("card_powers", SLICE_CARD_POWERS, (N_POWERS,)),
    ("card_deity", SLICE_CARD_DEITY, (1,)),
    ("card_pending_source", SLICE_CARD_PENDING_SOURCE, (1,)),
    ("card_quests", SLICE_CARD_QUESTS, (N_QUESTS, 3)),
    ("card_secrets", SLICE_CARD_SECRETS, (N_SECRETS,)),
    ("card_board", SLICE_CARD_BOARD, (N_BOARD,)),
    ("card_hand", SLICE_CARD_HAND, (N_HAND,)),
    ("card_shop", SLICE_CARD_SHOP, (N_SHOP,)),
    ("card_choices", SLICE_CARD_CHOICES, (N_CHOICE,)),
    ("card_trinkets", SLICE_CARD_TRINKETS, (8,)),
    ("card_opp_heroes", SLICE_CARD_OPP_HEROES, (N_OPP,)),
    ("card_opp_boards", SLICE_CARD_OPP_BOARDS, (N_OPP, N_BOARD)),
)


# ══════════════════════════════════════════════════════════════════════
# 块内字段偏移 / 顺序表（与 obs.rs 的 push_* 函数逐项对应）
# ══════════════════════════════════════════════════════════════════════

# ── global（42 标量 + 11 种族位）──
GLOBAL_FIELD_NAMES: Tuple[str, ...] = (
    "turn", "hero_select", "game_over", "alive", "me_alive", "health",
    "armor", "gold", "max_gold_bonus", "gold_next_turn", "tier",
    "upgrade_price", "refresh_price", "minion_price", "free_refreshes",
    "frozen", "power0_usable", "power0_price", "power0_uses_game",
    "power1_usable", "power1_price", "power1_uses_game", "can_dark_gift",
    "dark_gift_uses", "trinket_count", "deity_atk", "deity_hp", "won_last",
    "lost_last", "spell_atk", "spell_hp", "gem_atk", "gem_hp", "board_len",
    "hand_len", "deity_present", "hand_queue_len", "next_is_ghost",
    "tavern_atk", "tavern_hp", "effects_len", "chronum",
)
#: global 字段名 → 下标
GLOBAL_FIELD_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(GLOBAL_FIELD_NAMES)
}
#: global 字段的归一化除数（``raw = round(float * scale)``；``None`` = 原值）
GLOBAL_FIELD_SCALE: Dict[str, float] = {
    "turn": 20.0, "alive": 8.0, "health": 40.0, "armor": 20.0,
    "gold": 10.0, "max_gold_bonus": 5.0, "gold_next_turn": 5.0,
    "tier": 6.0, "upgrade_price": 10.0, "refresh_price": 2.0,
    "minion_price": 3.0, "free_refreshes": 3.0, "power0_price": 5.0,
    "power0_uses_game": 5.0, "power1_price": 5.0,
    "power1_uses_game": 5.0, "dark_gift_uses": 3.0, "trinket_count": 2.0,
    "deity_atk": 10.0, "deity_hp": 10.0, "spell_atk": 5.0,
    "spell_hp": 5.0, "gem_atk": 5.0, "gem_hp": 5.0, "board_len": 7.0,
    "hand_len": 10.0, "hand_queue_len": 5.0, "tavern_atk": 10.0,
    "tavern_hp": 10.0, "effects_len": 5.0, "chronum": 4.0,
}

#: lobby 种族位在 global 块内的起点（42..52）
GLOBAL_LOBBY_RACES_START = 42

# ── minion 块（MINION_F=31）──
MINION_PRESENT = 0
MINION_ATK = 1
MINION_HP = 2
MINION_MAX_HP = 3
MINION_TIER = 4
MINION_GOLDEN = 5
MINION_ATTACHED = 6
MINION_SHIELD_HITS = 7
MINION_KEYWORDS = 8
MINION_RACES = MINION_KEYWORDS + 12

# ── item 块（ITEM_F=40 = 9 头字段 + minion 子块）──
ITEM_PRESENT = 0
ITEM_IS_MINION = 1
ITEM_COST = 2
ITEM_LOCKED = 3
ITEM_TEMPORARY = 4
ITEM_COMBINED = 5
ITEM_FROZEN = 6      # 手牌语义：本回合打出即死亡（Tomb Turning）
ITEM_KEPT = 7
ITEM_MARKED = 8
ITEM_MINION = 9      # 随从子块起点（ITEM_MINION + MINION_F == ITEM_F）
#: 法术块（``ITEM_IS_MINION=0``）字段偏移
SPELL_PRESENT = 9    # 恒 1.0（区别于空槽）
SPELL_DATA = 10      # data / 6
SPELL_TIER = 13      # tier / 6（11/12 为保留 0）

# ── opponent 块（OPP_F=9）──
OPP_PRESENT = 0
OPP_ALIVE = 1
OPP_HEALTH = 2       # /40
OPP_ARMOR = 3        # /20
OPP_TIER = 4         # /6
OPP_SEEN_BOARD_LEN = 5   # /7
OPP_PLACEMENT = 6    # /8
OPP_IS_LAST = 7
OPP_IS_NEXT = 8

# ── 顺序表（bit / one-hot / kind 顺序，全部与上游一致）──
#: 种族位顺序（``Races::NAMES``）
RACE_NAMES: Tuple[str, ...] = (
    "BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC",
    "PIRATE", "QUILBOAR", "UNDEAD", "ABERRATION", "NAGA",
)
#: 关键词位顺序（``Kw::NAMES``）
KEYWORD_NAMES: Tuple[str, ...] = (
    "TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS", "POISONOUS",
    "STEALTH", "MAGNETIC", "MEGA_WINDFURY", "CLEAVE", "IMMUNE",
    "IMMUNE_ATTACKING",
)
#: pending 种类 one-hot 顺序（``PENDING_KINDS=9``）
PENDING_KIND_NAMES: Tuple[str, ...] = (
    "none", "hero", "discover", "choose_one", "target", "hero_power",
    "trinket", "quest", "timewarp",
)


# ══════════════════════════════════════════════════════════════════════
# 块形状（给策略头/校验用）
# ══════════════════════════════════════════════════════════════════════


def block_shapes() -> Dict[str, Tuple[int, ...]]:
    """全部浮点块/卡牌块的形状（``name → shape``；不含 ``features/cards`` 整体）。"""
    out: Dict[str, Tuple[int, ...]] = {}
    for name, _sl, shape in FLOAT_BLOCKS:
        out[name] = shape
    for name, _sl, shape in CARD_BLOCKS:
        out[name] = shape
    return out


# ══════════════════════════════════════════════════════════════════════
# 只读解码
# ══════════════════════════════════════════════════════════════════════


def _as_f32(values: Any, *, name: str = "features") -> np.ndarray:
    """归一化 features 输入为 little-endian float32 一维数组（不复制 bytes）。"""
    if isinstance(values, (bytes, bytearray, memoryview)):
        data = bytes(values) if not isinstance(values, bytes) else values
        if len(data) % 4 != 0:
            raise ValueError(
                f"{name} 字节数 {len(data)} 不是 4 的倍数（f32 流）")
        arr = np.frombuffer(data, dtype="<f4")
    elif isinstance(values, np.ndarray):
        arr = np.ascontiguousarray(values)
        if arr.dtype != np.float32:
            raise ValueError(f"{name} dtype 必须是 float32，得到 {arr.dtype}")
        arr = arr.reshape(-1)
    else:
        flat = list(values)
        arr = np.asarray(flat, dtype="<f4").reshape(-1)
    if arr.size != OBS_FLOATS:
        raise ValueError(
            f"{name} 长度 {arr.size} != OBS_FLOATS {OBS_FLOATS}")
    return arr


def _as_i32(values: Any, *, name: str = "cards") -> np.ndarray:
    """归一化 cards 输入为 little-endian int32 一维数组（不复制 bytes）。"""
    if isinstance(values, (bytes, bytearray, memoryview)):
        data = bytes(values) if not isinstance(values, bytes) else values
        if len(data) % 4 != 0:
            raise ValueError(
                f"{name} 字节数 {len(data)} 不是 4 的倍数（i32 流）")
        arr = np.frombuffer(data, dtype="<i4")
    elif isinstance(values, np.ndarray):
        arr = np.ascontiguousarray(values)
        if arr.dtype != np.int32:
            raise ValueError(f"{name} dtype 必须是 int32，得到 {arr.dtype}")
        arr = arr.reshape(-1)
    else:
        flat = list(values)
        arr = np.asarray(flat, dtype="<i4").reshape(-1)
    if arr.size != OBS_CARDS:
        raise ValueError(f"{name} 长度 {arr.size} != OBS_CARDS {OBS_CARDS}")
    return arr


def _view(arr: np.ndarray, sl: slice, shape: Tuple[int, ...],
          *, copy: bool) -> np.ndarray:
    """从一维数组切只读视图（``copy=True`` 时复制一份独立只读数组）。"""
    out = arr[sl].reshape(shape)
    if copy:
        out = out.copy()
    out.flags.writeable = False
    return out


def decode_blocks(
    features: Any,
    cards: Any,
    *,
    copy: bool = False,
) -> Dict[str, np.ndarray]:
    """把 AT 风格观测切成具名只读块视图。

    参数
    ----
    features : bytes | bytearray | memoryview | np.ndarray | Sequence[float]
        ``OBS_FLOATS=3227`` 个 f32；bytes 按 little-endian 解释（上游
        ``Game.observe()`` 返回的原始字节可直接传入）。
    cards : bytes | bytearray | memoryview | np.ndarray | Sequence[int]
        ``OBS_CARDS=124`` 个 i32 卡牌 embedding 下标（little-endian 字节）。
    copy : bool
        默认 ``False`` = 返回与输入共享内存的只读视图（bytes 输入天然只读）；
        ``True`` = 返回独立副本（同样只读），用于跨进程/长期缓存。

    返回
    ----
    dict[str, np.ndarray]
        ``"features"``/``"cards"``（一维原向量）+ :data:`FLOAT_BLOCKS` /
        :data:`CARD_BLOCKS` 中所有块（已 reshape）。所有返回数组
        ``writeable=False``。
    """
    farr = _as_f32(features)
    carr = _as_i32(cards)
    out: Dict[str, np.ndarray] = {
        "features": _view(farr, slice(0, OBS_FLOATS), (OBS_FLOATS,),
                          copy=copy),
        "cards": _view(carr, slice(0, OBS_CARDS), (OBS_CARDS,), copy=copy),
    }
    for name, sl, shape in FLOAT_BLOCKS:
        out[name] = _view(farr, sl, shape, copy=copy)
    for name, sl, shape in CARD_BLOCKS:
        out[name] = _view(carr, sl, shape, copy=copy)
    return out


# ══════════════════════════════════════════════════════════════════════
# 导入期自检（布局漂移立刻报错）
# ══════════════════════════════════════════════════════════════════════


def _validate_layout() -> None:
    """校验块布局自洽（宽度/偏移/形状/顺序表长度）。"""
    if MINION_F != 8 + len(KEYWORD_NAMES) + len(RACE_NAMES):
        raise AssertionError(
            f"MINION_F={MINION_F} 与关键词/种族位表不符"
            f"（8 + {len(KEYWORD_NAMES)} + {len(RACE_NAMES)}）")
    if ITEM_F != 9 + MINION_F:
        raise AssertionError(f"ITEM_F={ITEM_F} != 9 + MINION_F")
    if GLOBAL_F != len(GLOBAL_FIELD_NAMES) + RACES_COUNT:
        raise AssertionError(
            f"GLOBAL_F={GLOBAL_F} != 42 + {RACES_COUNT}")
    if OBS_FLOATS != 3227:
        raise AssertionError(f"OBS_FLOATS={OBS_FLOATS} != 3227")
    if OBS_CARDS != 124:
        raise AssertionError(f"OBS_CARDS={OBS_CARDS} != 124")
    if len(PENDING_KIND_NAMES) != PENDING_KINDS:
        raise AssertionError(
            f"PENDING_KIND_NAMES 长度 {len(PENDING_KIND_NAMES)} != "
            f"PENDING_KINDS {PENDING_KINDS}")
    if len(layout()) != 32:
        raise AssertionError(f"layout() 项数 {len(layout())} != 32")
    # 块连续覆盖（无空洞/重叠）
    end = 0
    for name, sl, shape in FLOAT_BLOCKS:
        if sl.start != end or sl.stop - sl.start != int(np.prod(shape)):
            raise AssertionError(
                f"浮点块 {name} 偏移/形状不连续：{sl} vs {shape}")
        end = sl.stop
    if end != OBS_FLOATS:
        raise AssertionError(f"浮点块总宽 {end} != OBS_FLOATS")
    end = 0
    for name, sl, shape in CARD_BLOCKS:
        if sl.start != end or sl.stop - sl.start != int(np.prod(shape)):
            raise AssertionError(
                f"卡牌块 {name} 偏移/形状不连续：{sl} vs {shape}")
        end = sl.stop
    if end != OBS_CARDS:
        raise AssertionError(f"卡牌块总宽 {end} != OBS_CARDS")


_validate_layout()
