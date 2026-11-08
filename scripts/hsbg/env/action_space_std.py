"""标准动作空间（AutoTavern / TavernGym 兼容 profile）：**前 245 项逐位一致**。

背景与目标
----------
P2 决策：HSBRSIM 的**标准动作 profile** 直接采用 AutoTavern（AT）TavernGym 的
固定 245 维动作空间——索引/语义/``action_name`` 与上游逐位一致，便于：

1. 与 AT 引擎/策略/数据**逐位可比**（同一动作索引在两边含义相同）；
2. 固定动作空间 + 精确 mask 的训练/搜索实现（不再依赖动态候选列表）；
3. 训练/搜索只使用固定 245 动作 + mask；旧动态候选接口已删除。

本模块常量与编码规则来自 AutoTavern 源码 ``crates/taverngym/src/actions.rs``
（TavernGym v1.0.0）；金标测试 ``tests/test_action_space_std.py`` 逐项对照
``hsbg_engine.action_name(i)``（0..244）。

动作段（前 245 = AT ``N_ACTIONS``）
-----------------------------------
======  =====  ====================  =========================================
索引     数量   动作                  参数
======  =====  ====================  =========================================
0       1      EndTurn               —
1       1      Refresh               —
2       1      Freeze                —
3       1      Upgrade               —
4..5    2      HeroPower(slot)       slot ∈ 0..1
6       1      DarkGift              —
7       1      Cancel                —
8..15   8      Buy(shop slot)        slot ∈ 0..7（``N_SHOP=8``）
16..22  7      Sell(board slot)      slot ∈ 0..6（``N_BOARD=7``）
23..29  7      Activate(board slot)  slot ∈ 0..6
30..45  16     Choose(option)        option ∈ 0..15（``N_CHOICE=16``）
46..125 80     Play{hand,pos}        hand ∈ 0..9, pos ∈ 0..7
126..195 70    Magnetize{hand,board} hand ∈ 0..9, board ∈ 0..6
196..244 49    Move{from,to}         from/to ∈ 0..6
======  =====  ====================  =========================================

``action_name(i)`` 与上游 ``format!("{action:?}")`` 逐字一致，例如
``"Play { hand: 2, pos: 3 }"``、``"Magnetize { hand: 0, board: 4 }"``。

扩展动作段（索引 ≥ 245，**不影响**前 245 语义）
-----------------------------------------------
AT 只有 ``Freeze``（整馆 toggle），没有单向解冻；真实游戏可以点掉整馆冻结，
因此把 Unfreeze 作为扩展动作。

=====================  ========  ==========================================
索引                    数量      动作 / 依据
=====================  ========  ==========================================
245                    1         Unfreeze：整馆解冻。AT 的 Freeze(2) 是
                                 **整馆 toggle**（已全冻时即解冻），
                                 std 拆成单向动作便于掩码；245 表达解冻。
246..249               4         HeroPower(2..5) 预留：HSBRSIM
                                 ``game.hero_power_ids(hero)`` 是**列表**，
                                 预留未来 3+ 技能槽。
250..265               16        Choose(16..31) 预留：AT 固定 16 选项；
                                 为未来 >16 选项池预留。
266..273               8         FreezeSlot(0..7)：**按槽位**冻结/解冻酒馆
                                 展示位（toggle；8 槽 = 7 随从 + 1 酒馆法术
                                 槽）。依据：37.0.0 卡面 ``BG22_HERO_004p``
                                 "copy its highest-Tier minion and **Freeze
                                 them both**"。
=====================  ========  ==========================================

扩展段编号 = 245 + 段内偏移；``N_TOTAL_ACTIONS = 245 + 1 + 4 + 16 + 8 = 274``。
已消费扩展段后仍有新增时，**只能追加**在 ``N_TOTAL_ACTIONS`` 之后（禁止插入/
重排），并同步升本模块与文档；前 245 项永远冻结。

确定性：全部函数纯函数、无 I/O、无随机；常量在导入时自检（见模块底部
``validate_layout()``），布局漂移会立刻报错。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple, Union

__all__ = [
    # 标准段常量（AT 逐位一致）
    "A_END", "A_REFRESH", "A_FREEZE", "A_UPGRADE",
    "A_HERO_POWER", "N_POWERS", "A_DARK_GIFT", "A_CANCEL",
    "A_BUY", "N_SHOP", "A_SELL", "A_ACTIVATE",
    "A_CHOOSE", "N_CHOICE", "A_PLAY", "N_POS", "N_HAND",
    "A_MAGNETIZE", "N_BOARD", "A_MOVE",
    "N_ACTIONS", "N_STD_ACTIONS",
    # 扩展段常量
    "A_EXT_BASE", "A_UNFREEZE", "A_EXTRA_POWER", "N_EXTRA_POWER_SLOTS",
    "A_EXTRA_CHOOSE", "N_EXTRA_CHOICE_SLOTS",
    "A_FREEZE_SLOT", "N_FREEZE_SLOTS", "N_EXT_ACTIONS",
    "N_TOTAL_ACTIONS", "N_EXTRA_POWER_SLOTS_MAX", "N_CHOICES_TOTAL",
    "SEGMENTS",
    # 动作数据类
    "EndTurn", "Refresh", "Freeze", "Upgrade", "HeroPower", "DarkGift",
    "Cancel", "Buy", "Sell", "Activate", "Choose", "Play", "Magnetize",
    "Move", "Unfreeze", "FreezeSlot", "StdAction", "STD_ACTION_TYPES",
    # 编解码
    "encode", "decode", "action_name", "is_std_index", "is_extension_index",
    "segment_of",
    # 校验
    "validate_layout",
]

# ══════════════════════════════════════════════════════════════════════
# 常量：与 AutoTavern `crates/taverngym/src/actions.rs` 逐位一致
# ══════════════════════════════════════════════════════════════════════

#: 结束招募阶段
A_END = 0
#: 刷新酒馆
A_REFRESH = 1
#: 冻结酒馆（AT：切换冻结）
A_FREEZE = 2
#: 升级酒馆
A_UPGRADE = 3
#: 英雄技能槽（主槽 0 / 副槽 1；AT ``N_POWERS=2``）
A_HERO_POWER = 4
N_POWERS = 2
#: 黑暗赠礼按钮（S14）
A_DARK_GIFT = 6
#: 取消目标选择（退出法术/技能/Activate 的目标选择）
A_CANCEL = 7
#: 购买酒馆卡（``N_SHOP=8`` 槽）
A_BUY = 8
N_SHOP = 8
#: 出售棋盘随从（``N_BOARD=7`` 槽）
A_SELL = 16
#: 使用随从的 Activate 技能
A_ACTIVATE = 23
#: 结算 PendingChoice 选项（``N_CHOICE=16``）
A_CHOOSE = 30
N_CHOICE = 16
#: 从手牌打出（随从/法术统一：``Play{hand,pos}``）
A_PLAY = 46
N_POS = 8
N_HAND = 10
#: 磁力吸附（手牌随从 → 棋盘随从）
A_MAGNETIZE = 126
N_BOARD = 7
#: 棋盘重排（from → to）
A_MOVE = 196

#: 标准动作总数（= AT ``N_ACTIONS``，本 profile 的前 245 项）
N_ACTIONS = 245
N_STD_ACTIONS = N_ACTIONS

# ── 扩展段（索引 ≥ 245）─────────────────────────────────────────────
#: 扩展段起点（= ``N_ACTIONS``）
A_EXT_BASE = N_ACTIONS
#: 解冻整馆（游戏支持，AT 只有 toggle；本 profile 显式拆成单向）
A_UNFREEZE = A_EXT_BASE
#: 备用英雄技能槽（slot 2..5 → 246..249）
A_EXTRA_POWER = A_UNFREEZE + 1
N_EXTRA_POWER_SLOTS = 4
#: 备用选择槽位（option 16..31 → 250..265）
A_EXTRA_CHOOSE = A_EXTRA_POWER + N_EXTRA_POWER_SLOTS
N_EXTRA_CHOICE_SLOTS = 16
#: 按槽位冻结/解冻酒馆展示位（toggle；8 槽 = 7 随从 + 1 酒馆法术槽）。
#: AT 只有整馆 toggle，而 37.0.0 卡面
#: ``BG22_HERO_004p`` "Freeze them both" 证明冻结是**按随从粒度**的状态。
A_FREEZE_SLOT = A_EXTRA_CHOOSE + N_EXTRA_CHOICE_SLOTS   # = 266
N_FREEZE_SLOTS = 8
#: 扩展动作数 = 1 + 4 + 16 + 8 = 29
N_EXT_ACTIONS = (1 + N_EXTRA_POWER_SLOTS + N_EXTRA_CHOICE_SLOTS
                 + N_FREEZE_SLOTS)
#: 全部动作数（标准 245 + 扩展 29 = 274）
N_TOTAL_ACTIONS = N_STD_ACTIONS + N_EXT_ACTIONS
#: ``HeroPower(slot)`` 可编码的最大 slot（含标准 0..1 与扩展 2..5）
N_EXTRA_POWER_SLOTS_MAX = N_POWERS + N_EXTRA_POWER_SLOTS
#: ``Choose(option)`` 可编码的最大 option（含标准 0..15 与扩展 16..31）
N_CHOICES_TOTAL = N_CHOICE + N_EXTRA_CHOICE_SLOTS

#: 动作段描述表（``(name, lo, hi, count, desc)``；``hi`` 为开区间）。
#: 供文档/测试/策略头切片使用；**顺序即索引顺序，禁止重排**。
SEGMENTS: Tuple[Tuple[str, int, int, int, str], ...] = (
    ("end_turn", A_END, A_END + 1, 1, "结束招募阶段"),
    ("refresh", A_REFRESH, A_REFRESH + 1, 1, "刷新酒馆"),
    ("freeze", A_FREEZE, A_FREEZE + 1, 1, "冻结酒馆"),
    ("upgrade", A_UPGRADE, A_UPGRADE + 1, 1, "升级酒馆"),
    ("hero_power", A_HERO_POWER, A_HERO_POWER + N_POWERS, N_POWERS,
     "英雄技能槽 0..1"),
    ("dark_gift", A_DARK_GIFT, A_DARK_GIFT + 1, 1, "黑暗赠礼"),
    ("cancel", A_CANCEL, A_CANCEL + 1, 1, "取消目标选择"),
    ("buy", A_BUY, A_BUY + N_SHOP, N_SHOP, "购买酒馆卡 0..7"),
    ("sell", A_SELL, A_SELL + N_BOARD, N_BOARD, "出售棋盘随从 0..6"),
    ("activate", A_ACTIVATE, A_ACTIVATE + N_BOARD, N_BOARD,
     "Activate 棋盘随从 0..6"),
    ("choose", A_CHOOSE, A_CHOOSE + N_CHOICE, N_CHOICE, "选择选项 0..15"),
    ("play", A_PLAY, A_PLAY + N_HAND * N_POS, N_HAND * N_POS,
     "打出手牌 hand 0..9 到位置 pos 0..7"),
    ("magnetize", A_MAGNETIZE, A_MAGNETIZE + N_HAND * N_BOARD,
     N_HAND * N_BOARD, "磁力吸附 hand 0..9 → 棋盘 0..6"),
    ("move", A_MOVE, A_MOVE + N_BOARD * N_BOARD, N_BOARD * N_BOARD,
     "棋盘重排 from 0..6 → to 0..6"),
    ("unfreeze", A_UNFREEZE, A_UNFREEZE + 1, 1,
     "扩展：解冻整馆（游戏支持，AT/环境未实现）"),
    ("extra_hero_power", A_EXTRA_POWER,
     A_EXTRA_POWER + N_EXTRA_POWER_SLOTS, N_EXTRA_POWER_SLOTS,
     "扩展预留：英雄技能槽 2..5"),
    ("extra_choose", A_EXTRA_CHOOSE,
     A_EXTRA_CHOOSE + N_EXTRA_CHOICE_SLOTS, N_EXTRA_CHOICE_SLOTS,
     "扩展预留：选择选项 16..31"),
    ("freeze_slot", A_FREEZE_SLOT,
     A_FREEZE_SLOT + N_FREEZE_SLOTS, N_FREEZE_SLOTS,
     "扩展：按槽位冻结/解冻酒馆展示位 0..7（toggle）"),
)


# ══════════════════════════════════════════════════════════════════════
# 动作表示（frozen dataclass；14 类 AT 动作 + 1 类扩展）
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EndTurn:
    """结束招募阶段（索引 0）。"""


@dataclass(frozen=True)
class Refresh:
    """刷新酒馆（索引 1）。"""


@dataclass(frozen=True)
class Freeze:
    """冻结酒馆（索引 2；AT 语义为整馆切换）。"""


@dataclass(frozen=True)
class Upgrade:
    """升级酒馆（索引 3）。"""


@dataclass(frozen=True)
class HeroPower:
    """使用英雄技能（索引 4+slot；扩展槽 2..5 → 246..249）。"""

    slot: int = 0


@dataclass(frozen=True)
class DarkGift:
    """黑暗赠礼（索引 6）。"""


@dataclass(frozen=True)
class Cancel:
    """取消目标选择（索引 7）。"""


@dataclass(frozen=True)
class Buy:
    """购买酒馆卡（索引 8+slot）。"""

    slot: int = 0


@dataclass(frozen=True)
class Sell:
    """出售棋盘随从（索引 16+slot）。"""

    slot: int = 0


@dataclass(frozen=True)
class Activate:
    """使用 Activate 技能（索引 23+slot）。"""

    slot: int = 0


@dataclass(frozen=True)
class Choose:
    """结算选择选项（索引 30+option；扩展 16..31 → 250..265）。"""

    option: int = 0


@dataclass(frozen=True)
class Play:
    """从手牌打出到棋盘位置（索引 46+hand*8+pos）。"""

    hand: int = 0
    pos: int = 0


@dataclass(frozen=True)
class Magnetize:
    """磁力吸附（索引 126+hand*7+board）。"""

    hand: int = 0
    board: int = 0


@dataclass(frozen=True)
class Move:
    """棋盘重排（索引 196+from*7+to）。"""

    src: int = 0
    to: int = 0


@dataclass(frozen=True)
class Unfreeze:
    """扩展动作：解冻整馆（索引 245；AT 无此单向动作）。"""


@dataclass(frozen=True)
class FreezeSlot:
    """扩展动作：按槽位冻结/解冻酒馆展示位（索引 266+slot；toggle）。

    ``slot`` ∈ 0..7（8 个酒馆展示位 = 7 随从槽 + 1 酒馆法术槽）；
    语义 = 对酒馆第 ``slot`` 张卡**切换**其单卡冻结状态（与整馆
    ``Freeze(2)`` / ``Unfreeze(245)`` 相互独立）。依据：37.0.0 卡面
    ``BG22_HERO_004p`` "Freeze them both"。
    """

    slot: int = 0


#: 标准 profile 的动作联合类型（含扩展 ``Unfreeze`` / ``FreezeSlot``）
StdAction = Union[
    EndTurn, Refresh, Freeze, Upgrade, HeroPower, DarkGift, Cancel,
    Buy, Sell, Activate, Choose, Play, Magnetize, Move, Unfreeze,
    FreezeSlot,
]

#: 全部动作类型（顺序与文档一致；用于测试/自检）
STD_ACTION_TYPES: Tuple[type, ...] = (
    EndTurn, Refresh, Freeze, Upgrade, HeroPower, DarkGift, Cancel,
    Buy, Sell, Activate, Choose, Play, Magnetize, Move, Unfreeze,
    FreezeSlot,
)


# ══════════════════════════════════════════════════════════════════════
# 编解码
# ══════════════════════════════════════════════════════════════════════


def _check_int(value: Any, *, field: str, lo: int, hi: int) -> int:
    """字段校验：必须是 ``int``（排除 bool）且在 ``[lo, hi]`` 内。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须是 int，得到 {type(value).__name__}")
    if not lo <= value <= hi:
        raise ValueError(f"{field}={value} 越界（允许 {lo}..{hi}）")
    return int(value)


def encode(action: StdAction) -> int:
    """动作对象 → 标准动作索引；非法对象/字段抛 ``ValueError``。"""
    if isinstance(action, EndTurn):
        return A_END
    if isinstance(action, Refresh):
        return A_REFRESH
    if isinstance(action, Freeze):
        return A_FREEZE
    if isinstance(action, Upgrade):
        return A_UPGRADE
    if isinstance(action, HeroPower):
        slot = _check_int(action.slot, field="HeroPower.slot", lo=0,
                          hi=N_EXTRA_POWER_SLOTS_MAX - 1)
        if slot < N_POWERS:
            return A_HERO_POWER + slot
        return A_EXTRA_POWER + (slot - N_POWERS)
    if isinstance(action, DarkGift):
        return A_DARK_GIFT
    if isinstance(action, Cancel):
        return A_CANCEL
    if isinstance(action, Buy):
        return A_BUY + _check_int(action.slot, field="Buy.slot", lo=0,
                                  hi=N_SHOP - 1)
    if isinstance(action, Sell):
        return A_SELL + _check_int(action.slot, field="Sell.slot", lo=0,
                                   hi=N_BOARD - 1)
    if isinstance(action, Activate):
        return A_ACTIVATE + _check_int(action.slot, field="Activate.slot",
                                       lo=0, hi=N_BOARD - 1)
    if isinstance(action, Choose):
        option = _check_int(action.option, field="Choose.option", lo=0,
                            hi=N_CHOICES_TOTAL - 1)
        if option < N_CHOICE:
            return A_CHOOSE + option
        return A_EXTRA_CHOOSE + (option - N_CHOICE)
    if isinstance(action, Play):
        hand = _check_int(action.hand, field="Play.hand", lo=0, hi=N_HAND - 1)
        pos = _check_int(action.pos, field="Play.pos", lo=0, hi=N_POS - 1)
        return A_PLAY + hand * N_POS + pos
    if isinstance(action, Magnetize):
        hand = _check_int(action.hand, field="Magnetize.hand", lo=0,
                          hi=N_HAND - 1)
        board = _check_int(action.board, field="Magnetize.board", lo=0,
                           hi=N_BOARD - 1)
        return A_MAGNETIZE + hand * N_BOARD + board
    if isinstance(action, Move):
        src = _check_int(action.src, field="Move.src", lo=0, hi=N_BOARD - 1)
        to = _check_int(action.to, field="Move.to", lo=0, hi=N_BOARD - 1)
        return A_MOVE + src * N_BOARD + to
    if isinstance(action, Unfreeze):
        return A_UNFREEZE
    if isinstance(action, FreezeSlot):
        return A_FREEZE_SLOT + _check_int(
            action.slot, field="FreezeSlot.slot", lo=0,
            hi=N_FREEZE_SLOTS - 1)
    raise ValueError(f"不支持的动作类型：{type(action).__name__}")


def decode(index: int) -> StdAction:
    """标准动作索引 → 动作对象（严格校验；扩展段返回 ``Unfreeze``/扩展槽位）。"""
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(f"动作索引必须是 int，得到 {type(index).__name__}")
    if not 0 <= index < N_TOTAL_ACTIONS:
        raise ValueError(
            f"动作索引 {index} 越界（允许 0..{N_TOTAL_ACTIONS - 1}）")
    if index == A_END:
        return EndTurn()
    if index == A_REFRESH:
        return Refresh()
    if index == A_FREEZE:
        return Freeze()
    if index == A_UPGRADE:
        return Upgrade()
    if A_HERO_POWER <= index < A_HERO_POWER + N_POWERS:
        return HeroPower(index - A_HERO_POWER)
    if index == A_DARK_GIFT:
        return DarkGift()
    if index == A_CANCEL:
        return Cancel()
    if A_BUY <= index < A_BUY + N_SHOP:
        return Buy(index - A_BUY)
    if A_SELL <= index < A_SELL + N_BOARD:
        return Sell(index - A_SELL)
    if A_ACTIVATE <= index < A_ACTIVATE + N_BOARD:
        return Activate(index - A_ACTIVATE)
    if A_CHOOSE <= index < A_CHOOSE + N_CHOICE:
        return Choose(index - A_CHOOSE)
    if A_PLAY <= index < A_PLAY + N_HAND * N_POS:
        hand, pos = divmod(index - A_PLAY, N_POS)
        return Play(hand=hand, pos=pos)
    if A_MAGNETIZE <= index < A_MAGNETIZE + N_HAND * N_BOARD:
        hand, board = divmod(index - A_MAGNETIZE, N_BOARD)
        return Magnetize(hand=hand, board=board)
    if A_MOVE <= index < A_MOVE + N_BOARD * N_BOARD:
        src, to = divmod(index - A_MOVE, N_BOARD)
        return Move(src=src, to=to)
    if index == A_UNFREEZE:
        return Unfreeze()
    if A_EXTRA_POWER <= index < A_EXTRA_POWER + N_EXTRA_POWER_SLOTS:
        return HeroPower(N_POWERS + (index - A_EXTRA_POWER))
    if A_EXTRA_CHOOSE <= index < A_EXTRA_CHOOSE + N_EXTRA_CHOICE_SLOTS:
        return Choose(N_CHOICE + (index - A_EXTRA_CHOOSE))
    if A_FREEZE_SLOT <= index < A_FREEZE_SLOT + N_FREEZE_SLOTS:
        return FreezeSlot(index - A_FREEZE_SLOT)
    raise ValueError(f"未定义的动作索引：{index}")  # pragma: no cover - 防御


def action_name(action: Union[int, StdAction]) -> str:
    """动作名（与 ``hsbg_engine.action_name`` **逐字一致**：0..244）。

    扩展段（245..265）返回本 profile 自己的名字（``Unfreeze`` /
    ``HeroPower(2..5)`` / ``Choose(16..31)``）。
    """
    if not isinstance(action, (int, tuple(STD_ACTION_TYPES))):
        raise TypeError(
            f"action_name 需要 int 或 StdAction，得到 {type(action).__name__}")
    if isinstance(action, int):
        action = decode(action)
    if isinstance(action, EndTurn):
        return "EndTurn"
    if isinstance(action, Refresh):
        return "Refresh"
    if isinstance(action, Freeze):
        return "Freeze"
    if isinstance(action, Upgrade):
        return "Upgrade"
    if isinstance(action, HeroPower):
        return f"HeroPower({action.slot})"
    if isinstance(action, DarkGift):
        return "DarkGift"
    if isinstance(action, Cancel):
        return "Cancel"
    if isinstance(action, Buy):
        return f"Buy({action.slot})"
    if isinstance(action, Sell):
        return f"Sell({action.slot})"
    if isinstance(action, Activate):
        return f"Activate({action.slot})"
    if isinstance(action, Choose):
        return f"Choose({action.option})"
    if isinstance(action, Play):
        return f"Play {{ hand: {action.hand}, pos: {action.pos} }}"
    if isinstance(action, Magnetize):
        return f"Magnetize {{ hand: {action.hand}, board: {action.board} }}"
    if isinstance(action, Move):
        return f"Move {{ from: {action.src}, to: {action.to} }}"
    if isinstance(action, Unfreeze):
        return "Unfreeze"
    if isinstance(action, FreezeSlot):
        return f"FreezeSlot({action.slot})"
    raise ValueError(f"不支持的动作类型：{type(action).__name__}")  # pragma: no cover


def is_std_index(index: int) -> bool:
    """是否属于 AT 标准段（0..244）。"""
    return isinstance(index, int) and not isinstance(index, bool) \
        and 0 <= index < N_STD_ACTIONS


def is_extension_index(index: int) -> bool:
    """是否属于扩展段（245..N_TOTAL_ACTIONS-1）。"""
    return isinstance(index, int) and not isinstance(index, bool) \
        and N_STD_ACTIONS <= index < N_TOTAL_ACTIONS


def segment_of(index: int) -> str:
    """动作所属段名（``SEGMENTS`` 的 name）；越界抛 ``ValueError``。"""
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(f"动作索引必须是 int，得到 {type(index).__name__}")
    for name, lo, hi, _count, _desc in SEGMENTS:
        if lo <= index < hi:
            return name
    raise ValueError(f"动作索引 {index} 越界（允许 0..{N_TOTAL_ACTIONS - 1}）")


# ══════════════════════════════════════════════════════════════════════
# 自检（导入即校验；布局/常量漂移立刻报错）
# ══════════════════════════════════════════════════════════════════════


def validate_layout() -> None:
    """校验常量布局自洽：段连续覆盖 ``0..N_TOTAL_ACTIONS-1`` 且无重叠。"""
    expect = 0
    for name, lo, hi, count, _desc in SEGMENTS:
        if lo != expect:
            raise AssertionError(
                f"动作段 {name} 起点 {lo} != 期望 {expect}（段必须连续）")
        if hi - lo != count:
            raise AssertionError(
                f"动作段 {name} 宽度 {hi - lo} != count {count}")
        expect = hi
    if expect != N_TOTAL_ACTIONS:
        raise AssertionError(
            f"动作段总宽 {expect} != N_TOTAL_ACTIONS {N_TOTAL_ACTIONS}")
    # 常量派生关系
    checks = {
        "A_DARK_GIFT": (A_DARK_GIFT, A_HERO_POWER + N_POWERS),
        "A_CANCEL": (A_CANCEL, A_DARK_GIFT + 1),
        "A_BUY": (A_BUY, A_CANCEL + 1),
        "A_SELL": (A_SELL, A_BUY + N_SHOP),
        "A_ACTIVATE": (A_ACTIVATE, A_SELL + N_BOARD),
        "A_CHOOSE": (A_CHOOSE, A_ACTIVATE + N_BOARD),
        "A_PLAY": (A_PLAY, A_CHOOSE + N_CHOICE),
        "A_MAGNETIZE": (A_MAGNETIZE, A_PLAY + N_HAND * N_POS),
        "A_MOVE": (A_MOVE, A_MAGNETIZE + N_HAND * N_BOARD),
        "N_ACTIONS": (N_ACTIONS, A_MOVE + N_BOARD * N_BOARD),
    }
    bad = {name: pair for name, pair in checks.items()
           if pair[0] != pair[1]}
    if bad:
        raise AssertionError(f"动作常量派生关系不成立：{bad}")
    # 编解码全量自检（245 + 29 = 274 项，导入期 < 1 ms）
    for index in range(N_TOTAL_ACTIONS):
        action = decode(index)
        if encode(action) != index:
            raise AssertionError(
                f"动作 {index} 编解码不自洽：{action!r} → {encode(action)}")
        if not isinstance(action_name(action), str) or not action_name(action):
            raise AssertionError(f"动作 {index} action_name 为空")


validate_layout()
