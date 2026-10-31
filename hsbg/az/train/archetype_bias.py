"""按流派（archetype）**软偏置**人类操作（训练期引导，默认关闭）。

动机
====

用户诉求：「遇到固定流派时，强制/引导模型按该流派的人类范式操作（先软后硬）」。
硬约束（mask 改写）风险高、不可逆；本模块先做**软偏置**：只在**合法动作**的 logit
上加一个**非负**增量，PPO 仍可自由偏离，因此不改变任何可行动作集合。

数据与分类器
============

``scripts/build_archetype_table.py`` 从 Firestone 149k 动作 + 10.8k 战团帧构造
**两段式**分类器（种族硬标签 + 头部流派 soft，尾部合并 ``other``），并把每个流派的
**动作偏好**（按 turn 分桶：买哪些卡 / 何时升 tier / 何时 reroll 的频率）写成
``data/archetype/archetype_table.json``；权重写 ``archetype_model.npz``。

- 本模块是**训练时的推理侧**，与 builder 共用同一套特征构造
  （:data:`FEATURE_BLOCKS` / :class:`ArchetypeHistory` / :class:`ArchetypeObs`），
  训练/推理不会各写一份导致漂移；
- 单测见 ``tests/test_archetype_bias.py`` / ``tests/test_archetype_table.py``。

泄漏边界（硬约束）
==================

识别与偏置**只允许**用：

1. 本座位 ``Game.observe(seat)`` 里的信息 —— 全局标量（turn/tier/gold/lobby 种族位）、
   己方战团/手牌/酒馆的种族位、卡牌下标（英雄、酒馆卡）；
2. 己方**历史动作序列**（本座位作出过的决策；采集时只有 learner 的决策经过本模块）；
3. 训练期离线统计出来的**流派→动作偏好表**（不含任何本局对手私有信息）。

禁止：对手手牌/战团、本局 seed 对应的终局结果、评测面板、人类库的 ``placement`` 等。
因此 ``parse_obs`` 只读 ``features``/``cards``，绝不读 ``game`` 内部状态或引擎返回值。

偏置规则（只在 ``coef>0`` 时生效）
=================================

检测：``max(p_archetype) >= min_prob`` 且类别不是 ``other`` → 用流派级偏好表；
否则若 ``max(p_tribe) >= min_prob`` → 退回**种族族**级偏好表；都不满足 → 不偏置。

对当前 turn 分桶的偏好表做相对增益打分（全部 ``>=0``、只加不减、不屏蔽）：

- 节奏类 ``upgrade`` / ``reroll`` / ``hero_power``（用**每回合**频率）：
  ``s = clip((r_arch - r_base) / max(r_base, eps), 0, RATE_CAP)``；
- 酒馆随从位（``Buy 8..15``）：种族偏好差 ``(w_arch - w_base) / AFF_SCALE`` 裁剪到
  ``[0,1]``，加上该流派高频购买的卡牌 id 加成（``top_cards``）；
- 手牌位（``Play 46..125``）：同一套种族 affinity × ``PLAY_FACTOR``。

最终逐动作 ``bias = clip(coef * Σ 分项, 0, coef * MAX_TOTAL)``，并把**非法位清零**
（非法位本来就被 masked softmax 归零；清零只是让统计与单测口径干净）。
``coef=0`` 时对象根本不构造 → 与旧路径**逐位等价**。

统计（采集 meta）
=================

``archetype_detected`` / ``archetype_name`` / ``bias_applied`` 等字段由
:meth:`ArchetypeBias.to_meta` 产出，按 worker 汇总用
:func:`aggregate_archetype_bias`。字段语义见 ``docs/ARCHETYPE_BIAS.md``。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from hsbg.env.action_space_std import (
    A_BUY,
    A_DARK_GIFT,
    A_END,
    A_FREEZE,
    A_HERO_POWER,
    A_MAGNETIZE,
    A_PLAY,
    A_REFRESH,
    A_SELL,
    A_UPGRADE,
    N_BOARD,
    N_HAND,
    N_POS,
    N_SHOP,
    N_POWERS,
)
from hsbg.env.obs_std import (
    GLOBAL_FIELD_INDEX,
    GLOBAL_FIELD_SCALE,
    ITEM_F,
    ITEM_IS_MINION,
    ITEM_MINION,
    MINION_F,
    MINION_RACES,
    OBS_CARDS,
    OBS_FLOATS,
    RACE_NAMES,
    SLICE_BOARD,
    SLICE_CARD_SHOP,
    SLICE_GLOBAL,
    SLICE_HAND,
    SLICE_SHOP,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
DEFAULT_TABLE = os.path.join(ROOT, "data", "archetype", "archetype_table.json")
DEFAULT_MODEL = os.path.join(ROOT, "data", "archetype", "archetype_model.npz")

#: 特征布局版本（改动 :data:`FEATURE_BLOCKS` 必须自增；npz 里校验）。
FEATURE_VERSION = 2
#: 英雄 one-hot 词表大小（固定 → 特征维度固定；OOV 落在最后一维 "other"）。
#: 实测 153 个英雄 / 427 局：词表放大到 64 会明显过拟合（top1 42→27%），16 最稳。
HERO_VOCAB_SIZE = 16
#: 种族位顺序（= 引擎 ``Races::NAMES``）；训练侧用同一顺序聚合。
TRIBES: Tuple[str, ...] = tuple(RACE_NAMES)
N_TRIBES = len(TRIBES)

#: 逐动作类型（与 Firestone 动作日志同口径；机械动作不计入，见 :func:`action_type_of`）。
ACTION_TYPES: Tuple[str, ...] = (
    "buy_minion", "buy_spell", "play_minion", "play_spell", "sell", "reroll",
    "freeze", "upgrade", "hero_power", "dark_gift", "end_turn",
)
N_ACTION_TYPES = len(ACTION_TYPES)
_TYPE_INDEX = {t: i for i, t in enumerate(ACTION_TYPES)}

#: 逐回合节奏统计的 6 类动作（``end_turn`` 恒定，不进节奏特征）。
RHYTHM_TYPES: Tuple[str, ...] = (
    "buy_minion", "play_minion", "sell", "reroll", "upgrade", "hero_power",
)
N_RHYTHM = len(RHYTHM_TYPES)

#: turn 分桶（闭区间）；最后一桶到 15。
TURN_BUCKETS: Tuple[Tuple[int, int], ...] = (
    (1, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 15),
)
N_BUCKETS = len(TURN_BUCKETS)

#: 特征块（顺序即向量顺序；训练 npz 用同一顺序校验维度）。
FEATURE_BLOCKS: Tuple[Tuple[str, int], ...] = (
    ("n_actions", 1),
    ("turn", 1),
    ("tempo", 1),
    ("type_share", N_ACTION_TYPES),
    ("rhythm", N_RHYTHM * N_BUCKETS),
    ("flow_tribe", N_TRIBES),
    ("flow_recent", N_TRIBES),
    ("board_tribe", N_TRIBES),
    ("shop_tribe", N_TRIBES),
    ("tier_curve", N_BUCKETS),
    ("tier_now", 1),
    ("max_tier", 1),
    ("gold_mean", 1),
    ("gold_now", 1),
    ("lobby", N_TRIBES),
    ("hero", HERO_VOCAB_SIZE + 1),
)
FEATURE_DIM = int(sum(w for _n, w in FEATURE_BLOCKS))

#: 偏置强度常量（乘 ``coef`` 之后使用）。
RATE_CAP = 2.0          #: 节奏类相对增益上限（倍数差 → 2.0）
AFF_SCALE = 0.12        #: 买牌种族 share 差 12pp 记满分
CARD_MIN_SHARE = 0.01   #: top_cards 进入偏置的最低 share
CARD_SCALE = 0.05       #: 单卡 share 5% 记满分
CARD_W = 1.0            #: 单卡分项权重
BUY_W = 1.0             #: 种族分项权重
PLAY_FACTOR = 0.5       #: 手牌（Play）分项相对系数
MAX_TOTAL = 2.0         #: 单动作 bias 上限（× coef）
RATE_FLOOR = 1e-3       #: 相对增益的分母下限（rate=0 时防爆）
FLOW_DECAY = 0.8        #: 近期流向特征的逐回合衰减
FLOW_EVENT_KEEP = 24    #: 保留的流向事件上限


# ══════════════════════════════════════════════════════════════════════════
# 1. 分桶 / 特征名
# ══════════════════════════════════════════════════════════════════════════
def bucket_of(turn: Any) -> int:
    """turn（1..15）→ 桶下标 0..5；越界裁剪（<=1 → 0，>=13 → 5）。"""
    t = int(turn)
    if t <= 1:
        return 0
    if t >= 13:
        return N_BUCKETS - 1
    for i, (lo, hi) in enumerate(TURN_BUCKETS):
        if lo <= t <= hi:
            return i
    return N_BUCKETS - 1


def bucket_key(b: Any) -> str:
    """桶下标（或 turn）→ 表键（``"1-4"``）。"""
    if isinstance(b, int) and 0 <= b < N_BUCKETS:
        i = int(b)
    else:
        i = bucket_of(int(b))
    lo, hi = TURN_BUCKETS[i]
    return f"{lo}-{hi}"


def bucket_keys() -> Tuple[str, ...]:
    return tuple(bucket_key(i) for i in range(N_BUCKETS))


def feature_names() -> Tuple[str, ...]:
    """展开后的逐维特征名（长度 = :data:`FEATURE_DIM`；单测/调试用）。"""
    out: List[str] = []
    for name, width in FEATURE_BLOCKS:
        if width == 1:
            out.append(name)
        elif name == "type_share":
            out.extend(f"type[{t}]" for t in ACTION_TYPES)
        elif name == "rhythm":
            for t in RHYTHM_TYPES:
                for i in range(N_BUCKETS):
                    out.append(f"rhythm[{t},{bucket_key(i)}]")
        elif name == "tier_curve":
            out.extend(f"tier[{bucket_key(i)}]" for i in range(N_BUCKETS))
        elif name == "hero":
            out.extend(f"hero[{i}]" for i in range(HERO_VOCAB_SIZE))
            out.append("hero[other]")
        elif name == "lobby":
            out.extend(f"lobby[{t}]" for t in TRIBES)
        else:
            out.extend(f"{name}[{t}]" for t in TRIBES)
    assert len(out) == FEATURE_DIM, (len(out), FEATURE_DIM)
    return tuple(out)


# ══════════════════════════════════════════════════════════════════════════
# 2. 观测解析（只用 features/cards；零引擎依赖）
# ══════════════════════════════════════════════════════════════════════════
def _minion_tribes(f: np.ndarray, base: int) -> np.ndarray:
    """一个 ``MINION_F`` 块（起点 ``base``）的种族 one-hot → float[11]。"""
    return np.asarray(f[base + MINION_RACES: base + MINION_RACES + N_TRIBES],
                      dtype=np.float32)


def _item_blocks(f: np.ndarray, sl: slice, n: int) -> Tuple[np.ndarray, np.ndarray,
                                                            np.ndarray]:
    """物品块（shop/hand）：返回 ``(tribes[n,11], is_minion[n], present[n])``。

    保留逐格循环：实测（2026-10-31）numpy 的 fancy-index / as_strided 在小数组上比
    直接标量索引**更慢**（n=7 时 12.0/14.3 µs vs 7.4 µs），因此不做向量化。
    """
    tribes = np.zeros((n, N_TRIBES), dtype=np.float32)
    is_minion = np.zeros((n,), dtype=bool)
    present = np.zeros((n,), dtype=bool)
    off = int(sl.start)
    for i in range(n):
        b = off + i * ITEM_F
        present[i] = float(f[b]) > 0.5
        is_minion[i] = float(f[b + ITEM_IS_MINION]) > 0.5
        if is_minion[i]:
            # 随从子块起点 = ITEM_MINION(=9)，种族位在 +MINION_RACES(20)
            tribes[i] = _minion_tribes(f, b + ITEM_MINION)
    return tribes, is_minion, present


@dataclass
class ArchetypeObs:
    """一次决策时**本座位可见**的流派相关观测（全部来自 observe 数组）。"""

    turn: int
    tier: int
    gold: float
    lobby: np.ndarray           # float[11]（lobby 种族位）
    board_tribes: np.ndarray    # float[11]（已归一化到占比）
    shop_tribes: np.ndarray     # float[N_SHOP, 11]（one-hot 原样）
    shop_minion: np.ndarray     # bool[N_SHOP]
    shop_present: np.ndarray    # bool[N_SHOP]
    hand_tribes: np.ndarray     # float[N_HAND, 11]
    hand_minion: np.ndarray     # bool[N_HAND]
    hand_present: np.ndarray    # bool[N_HAND]
    hero_id: str = ""


def parse_obs(features: Any, cards: Any, *,
              hero_id_of: Optional[Callable[[int], str]] = None) -> ArchetypeObs:
    """``Game.observe(seat)`` 的 ``(features, cards)`` → :class:`ArchetypeObs`。

    只读 features/cards；``hero_id_of``（卡牌下标 → 卡 id）缺省时不产出英雄特征
    （英雄块退化为 ``other`` 位），保证无引擎环境也能跑单测。
    """
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    if f.size != OBS_FLOATS:
        raise ValueError(f"features 维度应为 {OBS_FLOATS}，得到 {f.size}")
    c = np.asarray(cards, dtype=np.int64).reshape(-1)
    if c.size != OBS_CARDS:
        raise ValueError(f"cards 维度应为 {OBS_CARDS}，得到 {c.size}")
    gi = GLOBAL_FIELD_INDEX
    turn = int(round(float(f[gi["turn"]]) * GLOBAL_FIELD_SCALE["turn"]))
    tier = int(round(float(f[gi["tier"]]) * GLOBAL_FIELD_SCALE["tier"]))
    gold = float(f[gi["gold"]]) * GLOBAL_FIELD_SCALE["gold"]
    lobby = np.asarray(f[SLICE_GLOBAL.start + 42: SLICE_GLOBAL.start + 42 + N_TRIBES],
                       dtype=np.float32).copy()
    # 己方战团种族占比
    board = np.zeros(N_TRIBES, dtype=np.float32)
    off = int(SLICE_BOARD.start)
    for i in range(N_BOARD):
        b = off + i * MINION_F
        if float(f[b]) > 0.5:
            board += _minion_tribes(f, b)
    board_total = float(board.sum())
    if board_total > 0:
        board /= board_total
    shop_t, shop_m, shop_p = _item_blocks(f, SLICE_SHOP, N_SHOP)
    hand_t, hand_m, hand_p = _item_blocks(f, SLICE_HAND, N_HAND)
    hero = ""
    if hero_id_of is not None:
        try:
            idx = int(c[0])
            if idx > 0:
                hero = str(hero_id_of(idx) or "")
        except Exception:  # noqa: BLE001 - 英雄查找失败不致命（退化为 other）
            hero = ""
    return ArchetypeObs(
        turn=max(0, turn), tier=max(0, tier), gold=float(gold), lobby=lobby,
        board_tribes=board, shop_tribes=shop_t, shop_minion=shop_m,
        shop_present=shop_p, hand_tribes=hand_t, hand_minion=hand_m,
        hand_present=hand_p, hero_id=hero)


#: 引擎动作下标 → 逐动作类型（``None`` = 机械/不可映射，不计入特征与偏好）。
def action_type_of(action: Any, obs: ArchetypeObs) -> Optional[str]:
    """动作下标 → 类型名（与 Firestone 动作日志同口径）。

    ``Move/Cancel/Choose/Activate`` 这类 AutoTavern 机械动作**不计入**（人类日志里
    没有对应行，计进去会让训练/推理两侧口径不一致）；``Magnetize`` 归到
    ``play_minion``（等价于把手牌随从贴到战团）。
    """
    a = int(action)
    if a == A_END:
        return "end_turn"
    if a == A_REFRESH:
        return "reroll"
    if a == A_FREEZE:
        return "freeze"
    if a == A_UPGRADE:
        return "upgrade"
    if A_HERO_POWER <= a < A_HERO_POWER + N_POWERS:
        return "hero_power"
    if a == A_DARK_GIFT:
        return "dark_gift"
    if A_BUY <= a < A_BUY + N_SHOP:
        slot = a - A_BUY
        if 0 <= slot < N_SHOP and bool(obs.shop_present[slot]):
            return "buy_minion" if bool(obs.shop_minion[slot]) else "buy_spell"
        return "buy_minion"      # 槽位观测缺失：按随从来（宁可略偏 buy_minion）
    if A_SELL <= a < A_SELL + N_BOARD:
        return "sell"
    if A_PLAY <= a < A_PLAY + N_HAND * N_POS:
        h = (a - A_PLAY) // N_POS
        if 0 <= h < N_HAND and bool(obs.hand_present[h]):
            return "play_minion" if bool(obs.hand_minion[h]) else "play_spell"
        return "play_minion"
    if A_MAGNETIZE <= a < A_MAGNETIZE + N_HAND * N_BOARD:
        return "play_minion"
    return None


def _hand_or_shop_tribe(obs: ArchetypeObs, action: int) -> int:
    """买/打动作对应的卡牌种族下标（取 argmax 位）；未知返回 -1。"""
    a = int(action)
    if A_BUY <= a < A_BUY + N_SHOP:
        slot = a - A_BUY
        if 0 <= slot < N_SHOP and bool(obs.shop_minion[slot]):
            return int(np.argmax(obs.shop_tribes[slot]))
        return -1
    if A_PLAY <= a < A_PLAY + N_HAND * N_POS:
        h = (a - A_PLAY) // N_POS
        if 0 <= h < N_HAND and bool(obs.hand_minion[h]):
            return int(np.argmax(obs.hand_tribes[h]))
        return -1
    if A_MAGNETIZE <= a < A_MAGNETIZE + N_HAND * N_BOARD:
        h = (a - A_MAGNETIZE) // N_BOARD
        if 0 <= h < N_HAND and bool(obs.hand_minion[h]):
            return int(np.argmax(obs.hand_tribes[h]))
        return -1
    return -1


# ══════════════════════════════════════════════════════════════════════════
# 3. 逐 (game, seat) 的历史累加器（训练/推理共用）
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class _Hist:
    n: int = 0
    type_counts: np.ndarray = field(
        default_factory=lambda: np.zeros(N_ACTION_TYPES, dtype=np.float32))
    rhythm: np.ndarray = field(
        default_factory=lambda: np.zeros((N_RHYTHM, N_BUCKETS), dtype=np.float32))
    flow: np.ndarray = field(
        default_factory=lambda: np.zeros(N_TRIBES, dtype=np.float32))
    #: 近期买/打流向事件 ``(turn, tribe)``；只留最近若干条（递归衰减特征用）
    flow_events: List[Tuple[int, int]] = field(default_factory=list)
    tier_curve: np.ndarray = field(
        default_factory=lambda: np.zeros(N_BUCKETS, dtype=np.float32))
    max_tier: int = 0
    gold_sum: float = 0.0
    gold_n: int = 0
    last_turn: int = -1
    #: 影响特征向量的状态修订号（``observe`` 的回合切换 / ``note_action`` 命中时自增）。
    #: 用于可选的输入哈希缓存：同一 ``(features, cards, mask, rev)`` 才可复用结果。
    rev: int = 0
    obs: Optional[ArchetypeObs] = None


class ArchetypeHistory:
    """按 ``(game_id, seat)`` 维护己方动作历史 → 流派特征向量。

    与 ``MoveGuard`` 的状态隔离方式一致（key 含 game_id/seat），因此 lock-step
    下多局共用一个对象也互不影响；``clear_state()`` 清逐局状态、保留累计统计。
    """

    def __init__(self) -> None:
        self._h: Dict[Tuple[int, int], _Hist] = {}

    def reset(self) -> None:
        self._h.clear()

    def clear_state(self) -> None:
        self._h.clear()

    def _get(self, game_id: Any, seat: Any) -> _Hist:
        # key 用 str(game_id)：训练侧对局 id 是 UUID 字符串，采集侧是整数，两者都安全
        key = (str(game_id), int(seat))
        st = self._h.get(key)
        if st is None:
            st = _Hist()
            self._h[key] = st
        return st

    def observe(self, game_id: Any, seat: Any, obs: ArchetypeObs) -> _Hist:
        """记录当前观测（每回合只累加一次 gold/tier；向量用最新 obs）。"""
        st = self._get(game_id, seat)
        if obs.turn != st.last_turn:
            b = bucket_of(obs.turn)
            st.tier_curve[b] = max(float(st.tier_curve[b]), float(obs.tier))
            st.max_tier = max(int(st.max_tier), int(obs.tier))
            st.gold_sum += float(obs.gold)
            st.gold_n += 1
            st.last_turn = int(obs.turn)
            st.rev += 1
        st.obs = obs
        return st

    def note_action(self, game_id: Any, seat: Any, action: Any, *,
                    obs: Optional[ArchetypeObs] = None) -> None:
        """记录己方实际动作（机械动作只更新 ``n`` 之外的状态，不计特征）。"""
        st = self._get(game_id, seat)
        o = obs if obs is not None else st.obs
        if o is None:
            return
        at = action_type_of(action, o)
        if at is None:
            return
        st.n += 1
        st.rev += 1
        st.type_counts[_TYPE_INDEX[at]] += 1.0
        if at in RHYTHM_TYPES:
            b = bucket_of(o.turn)
            st.rhythm[RHYTHM_TYPES.index(at), b] += 1.0
        if at in ("buy_minion", "play_minion"):
            t = _hand_or_shop_tribe(o, int(action))
            if 0 <= t < N_TRIBES:
                st.flow[t] += 1.0
                st.flow_events.append((int(o.turn), int(t)))
                if len(st.flow_events) > FLOW_EVENT_KEEP:
                    del st.flow_events[:-FLOW_EVENT_KEEP]

    def vector(self, game_id: Any, seat: Any, obs: ArchetypeObs,
               *, hero_vocab: Sequence[str] = (),
               hero_index: Optional[Dict[str, int]] = None) -> np.ndarray:
        """当前时刻的特征向量（长度 :data:`FEATURE_DIM`）。"""
        st = self._get(game_id, seat)
        return build_vector(st, obs, hero_vocab=hero_vocab, hero_index=hero_index)


#: 每个 turn 桶的宽度（float32；与 ``np.float32 标量 / Python float``
#: 在 NEP50 下的语义一致 -> 向量化后逐位等价）。
_BUCKET_WIDTHS = np.asarray([float(hi - lo + 1) for (lo, hi) in TURN_BUCKETS],
                            dtype=np.float32)
#: ``FLOW_DECAY ** k`` 预计算表（k=0..63；``**`` 是确定性 IEEE 运算，表值逐位相同）。
_FLOW_DECAY_POW: Tuple[float, ...] = tuple(float(FLOW_DECAY) ** k for k in range(64))


def build_vector(st: _Hist, obs: ArchetypeObs, *,
                 hero_vocab: Sequence[str] = (),
                 hero_index: Optional[Dict[str, int]] = None) -> np.ndarray:
    """由历史 + 当前观测拼特征向量（训练/推理**唯一**入口，防两侧漂移）。

    ``hero_index``：``hero_vocab`` 的 ``{name: idx}`` 预映射（可选）。给定时跳过
    ``tuple.index`` 的线性查找；**结果与原路径逐位相同**（同一 idx）。
    """
    x = np.zeros(FEATURE_DIM, dtype=np.float32)
    off = 0
    n = int(st.n)
    turn = max(1, int(obs.turn))
    x[off] = math.log1p(n)
    off += 1
    x[off] = turn / 15.0
    off += 1
    x[off] = n / float(turn)          # tempo：每回合可映射动作数
    off += 1
    # 类型占比
    if n > 0:
        x[off: off + N_ACTION_TYPES] = st.type_counts / float(n)
    off += N_ACTION_TYPES
    # 节奏：每类动作在每个桶内的次数（除以桶宽，口径统一；向量化，逐位等价）
    x[off: off + N_RHYTHM * N_BUCKETS] = (
        st.rhythm / _BUCKET_WIDTHS).astype(np.float32, copy=False).reshape(-1)
    off += N_RHYTHM * N_BUCKETS
    # 买入/打出流向种族占比
    flow_total = float(st.flow.sum())
    if flow_total > 0:
        x[off: off + N_TRIBES] = st.flow / flow_total
    off += N_TRIBES
    # 近期流向（指数衰减）：越近的买/打越能说明当前在打什么流派
    if st.flow_events:
        acc = np.zeros(N_TRIBES, dtype=np.float32)
        _pow = _FLOW_DECAY_POW
        _npow = len(_pow)
        for ev_turn, ev_t in st.flow_events:
            k = turn - int(ev_turn)
            w = _pow[k] if 0 <= k < _npow else float(FLOW_DECAY) ** max(0, k)
            acc[int(ev_t) % N_TRIBES] += w
        tot = float(acc.sum())
        if tot > 0:
            x[off: off + N_TRIBES] = acc / tot
    off += N_TRIBES
    # 当前战团 / 酒馆种族占比
    x[off: off + N_TRIBES] = obs.board_tribes
    off += N_TRIBES
    shop = obs.shop_tribes * obs.shop_minion.reshape(-1, 1)
    shop_total = float(shop.sum())
    if shop_total > 0:
        x[off: off + N_TRIBES] = shop.sum(axis=0) / shop_total
    off += N_TRIBES
    # tier 曲线（未到达的桶恒 0）
    x[off: off + N_BUCKETS] = st.tier_curve
    off += N_BUCKETS
    x[off] = float(obs.tier)
    off += 1
    x[off] = float(st.max_tier)
    off += 1
    x[off] = (st.gold_sum / st.gold_n) if st.gold_n else 0.0
    off += 1
    x[off] = float(obs.gold)
    off += 1
    # lobby 种族位（公共信息）
    x[off: off + N_TRIBES] = obs.lobby
    off += N_TRIBES
    # 英雄 one-hot（公共信息；OOV 落 other 位）
    other = HERO_VOCAB_SIZE
    idx = -1
    if obs.hero_id:
        if hero_index is not None:
            idx = int(hero_index.get(str(obs.hero_id), -1))
        else:
            try:
                idx = int(hero_vocab.index(obs.hero_id)) if obs.hero_id in hero_vocab else -1
            except ValueError:
                idx = -1
    if 0 <= idx < HERO_VOCAB_SIZE:
        x[off + idx] = 1.0
    else:
        x[off + other] = 1.0
    off += HERO_VOCAB_SIZE + 1
    if off != FEATURE_DIM:
        raise AssertionError((off, FEATURE_DIM))
    return x


# ══════════════════════════════════════════════════════════════════════════
# 4. 分类器（纯 numpy softmax 回归；训练脚本写、推理侧读）
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class SoftmaxModel:
    """标准化 + 线性 softmax（W: D×C，b: C）。"""

    classes: Tuple[str, ...]
    W: np.ndarray
    b: np.ndarray
    mean: np.ndarray
    std: np.ndarray
    #: 概率校准温度（``logits / temp``）；1.0 = 未校准。
    temp: float = 1.0

    @property
    def n_classes(self) -> int:
        return len(self.classes)

    def logits(self, X: Any) -> np.ndarray:
        Z = np.asarray(X, dtype=np.float64)
        if Z.ndim == 1:
            Z = Z.reshape(1, -1)
        Z = (Z - self.mean) / self.std
        return Z @ self.W + self.b

    def probs(self, X: Any) -> np.ndarray:
        logits = self.logits(X) / max(1e-6, float(self.temp))
        logits = logits - logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)

    def predict(self, X: Any) -> np.ndarray:
        return self.probs(X).argmax(axis=1)


def save_model(path: str, *, tribe: SoftmaxModel, arch: SoftmaxModel,
               hero_vocab: Sequence[str], mean: np.ndarray, std: np.ndarray,
               meta: Optional[Dict[str, Any]] = None) -> None:
    """把两段式分类器写成 npz（字符串数组用 ``<U``）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    payload: Dict[str, Any] = {
        "feature_version": np.int64(FEATURE_VERSION),
        "feature_dim": np.int64(FEATURE_DIM),
        "hero_vocab": np.asarray([str(h) for h in hero_vocab], dtype="<U64"),
        "norm_mean": np.asarray(mean, dtype=np.float64),
        "norm_std": np.asarray(std, dtype=np.float64),
        "tribe_classes": np.asarray([str(c) for c in tribe.classes], dtype="<U64"),
        "tribe_W": np.asarray(tribe.W, dtype=np.float64),
        "tribe_b": np.asarray(tribe.b, dtype=np.float64),
        "arch_classes": np.asarray([str(c) for c in arch.classes], dtype="<U64"),
        "arch_W": np.asarray(arch.W, dtype=np.float64),
        "arch_b": np.asarray(arch.b, dtype=np.float64),
        "tribe_temp": np.float64(tribe.temp),
        "arch_temp": np.float64(arch.temp),
    }
    if meta:
        payload["meta_json"] = np.asarray(json.dumps(meta, ensure_ascii=False))
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **payload)
    os.replace(tmp, path)


def _model_from_npz(z: Any, prefix: str) -> SoftmaxModel:
    return SoftmaxModel(
        classes=tuple(str(x) for x in z[f"{prefix}_classes"].tolist()),
        W=np.asarray(z[f"{prefix}_W"], dtype=np.float64),
        b=np.asarray(z[f"{prefix}_b"], dtype=np.float64),
        mean=np.asarray(z["norm_mean"], dtype=np.float64),
        std=np.asarray(z["norm_std"], dtype=np.float64),
        temp=(float(np.asarray(z[f"{prefix}_temp"]).reshape(-1)[0])
              if f"{prefix}_temp" in z else 1.0))


def load_models(path: str) -> Tuple[SoftmaxModel, SoftmaxModel, List[str],
                                    Dict[str, Any]]:
    """npz → ``(tribe_model, arch_model, hero_vocab, meta)``。"""
    with np.load(path, allow_pickle=False) as z:
        ver = int(np.asarray(z["feature_version"]).reshape(-1)[0])
        dim = int(np.asarray(z["feature_dim"]).reshape(-1)[0])
        if ver != FEATURE_VERSION:
            raise ValueError(f"archetype 模型特征版本 {ver} != 当前 {FEATURE_VERSION}；"
                             "请重跑 scripts/build_archetype_table.py")
        if dim != FEATURE_DIM:
            raise ValueError(f"archetype 模型特征维度 {dim} != 当前 {FEATURE_DIM}")
        hero_vocab = [str(x) for x in z["hero_vocab"].tolist()]
        tribe = _model_from_npz(z, "tribe")
        arch = _model_from_npz(z, "arch")
        meta: Dict[str, Any] = {}
        if "meta_json" in z:
            meta = json.loads(str(np.asarray(z["meta_json"]).reshape(-1)[0]))
    return tribe, arch, hero_vocab, meta


# ══════════════════════════════════════════════════════════════════════════
# 5. 偏好表 → 偏置向量
# ══════════════════════════════════════════════════════════════════════════
def load_table(path: str = DEFAULT_TABLE) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        table = json.load(f)
    if not isinstance(table, dict) or "archetypes" not in table:
        raise ValueError(f"流派偏好表格式非法: {path}")
    return table


def _rate_gain(r_arch: float, r_base: float) -> float:
    """节奏类相对增益：``(r_arch-r_base)/max(r_base, eps)``，裁剪到 ``[0, RATE_CAP]``。"""
    ra = max(0.0, float(r_arch))
    rb = max(0.0, float(r_base))
    g = (ra - rb) / max(rb, RATE_FLOOR)
    return float(min(RATE_CAP, max(0.0, g)))


def _tribe_gain(w_arch: Sequence[float], w_base: Sequence[float],
                t: int) -> float:
    """种族 affinity：share 差 / ``AFF_SCALE``，裁剪到 ``[0,1]``。"""
    if not (0 <= int(t) < N_TRIBES):
        return 0.0
    d = float(w_arch[t]) - float(w_base[t])
    return float(min(1.0, max(0.0, d / AFF_SCALE)))


def bias_from_pref(pref: Dict[str, Any], base: Dict[str, Any], obs: ArchetypeObs,
                   mask: Any, *, coef: float,
                   card_index_of: Optional[Callable[[int], str]] = None,
                   cards: Any = None) -> np.ndarray:
    """偏好表 → 245 维**非负** bias（非法位为 0；不屏蔽任何动作）。

    ``pref``/``base`` 是同一 turn 分桶的偏好与基线字典；``card_index_of`` 提供
    卡牌下标 → 卡 id（用于 ``top_cards`` 加成），缺省跳过卡牌分项。
    """
    bias = np.zeros(245, dtype=np.float32)
    c = float(coef)
    if c <= 0.0:
        return bias
    # 优先用「每回合」频率（比逐决策 rate 更能区分「何时升 tier / reroll」；
    # 旧表没有 per_turn 时退回 rates）
    rates = pref.get("per_turn") or pref.get("rates") or {}
    brates = base.get("per_turn") or base.get("rates") or {}
    # 节奏类
    for cat, acts in (("upgrade", (A_UPGRADE,)),
                      ("reroll", (A_REFRESH,)),
                      ("hero_power", tuple(range(A_HERO_POWER,
                                                 A_HERO_POWER + N_POWERS)))):
        g = _rate_gain(float(rates.get(cat, 0.0) or 0.0),
                       float(brates.get(cat, 0.0) or 0.0))
        if g > 0.0:
            for a in acts:
                bias[a] += c * g
    # 买：种族 affinity + 单卡加成
    w_buy = pref.get("buy_tribe") or {}
    b_buy = base.get("buy_tribe") or {}
    top_cards = {str(k): float(v) for k, v in (pref.get("top_cards") or {}).items()}
    wa = [float(w_buy.get(t, 0.0) or 0.0) for t in TRIBES]
    wb = [float(b_buy.get(t, 0.0) or 0.0) for t in TRIBES]
    cards_arr = np.asarray(cards).reshape(-1) if cards is not None else None
    shop_tribe: Optional[np.ndarray] = None
    for slot in range(N_SHOP):
        if not bool(obs.shop_present[slot]) or not bool(obs.shop_minion[slot]):
            continue
        if shop_tribe is None:          # 惰性整块 argmax（与逐格 argmax 逐位相同）
            shop_tribe = obs.shop_tribes.argmax(axis=1)
        t = int(shop_tribe[slot])
        g = _tribe_gain(wa, wb, t)
        if g > 0.0:
            bias[A_BUY + slot] += c * BUY_W * g
        if card_index_of is not None and cards_arr is not None and top_cards:
            try:
                # 注意：cards 块与 features 块的切片不同（这里取 card_shop 块）
                idx = int(cards_arr[SLICE_CARD_SHOP.start + slot])
                cid = str(card_index_of(idx)) if idx > 0 else ""
            except Exception:  # noqa: BLE001 - 卡 id 解析失败只跳过卡牌分项
                cid = ""
            share = float(top_cards.get(cid, 0.0) or 0.0)
            if share >= CARD_MIN_SHARE:
                bias[A_BUY + slot] += c * CARD_W * min(1.0, share / CARD_SCALE)
    # 打：手牌种族 affinity × PLAY_FACTOR
    hand_tribe: Optional[np.ndarray] = None
    for h in range(N_HAND):
        if not bool(obs.hand_present[h]) or not bool(obs.hand_minion[h]):
            continue
        if hand_tribe is None:
            hand_tribe = obs.hand_tribes.argmax(axis=1)
        t = int(hand_tribe[h])
        g = _tribe_gain(wa, wb, t)
        if g <= 0.0:
            continue
        base_a = A_PLAY + h * N_POS
        bias[base_a: base_a + N_POS] += c * PLAY_FACTOR * g
    # 只加不减 + 不屏蔽：非法位清零（本来会被 masked softmax 归零）
    m = np.asarray(mask, dtype=bool).reshape(-1)
    bias[~m] = 0.0
    np.clip(bias, 0.0, c * MAX_TOTAL, out=bias)
    return bias


# ══════════════════════════════════════════════════════════════════════════
# 6. 统计
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class ArchetypeBiasStats:
    decisions: int = 0          #: 跑过检测器（且 coef>0）的决策数
    detected: int = 0           #: max_prob >= min_prob 的决策数
    applied: int = 0            #: 实际至少给一个合法动作加了 bias 的决策数
    lvl_archetype: int = 0      #: 用流派级表（头部类）的决策数
    lvl_tribe: int = 0          #: 退回种族族级表的决策数
    lvl_none: int = 0           #: 低置信 → 不偏置的决策数
    prob_sum: float = 0.0       #: 命中类概率之和（算 mean prob）
    bias_sum: float = 0.0       #: bias 总和（含全部动作位）
    bias_actions: int = 0       #: 拿到正 bias 的 (决策, 动作位) 数
    name_counts: Dict[str, int] = field(default_factory=dict)

    def add(self, other: "ArchetypeBiasStats") -> None:
        self.decisions += int(other.decisions)
        self.detected += int(other.detected)
        self.applied += int(other.applied)
        self.lvl_archetype += int(other.lvl_archetype)
        self.lvl_tribe += int(other.lvl_tribe)
        self.lvl_none += int(other.lvl_none)
        self.prob_sum += float(other.prob_sum)
        self.bias_sum += float(other.bias_sum)
        self.bias_actions += int(other.bias_actions)
        for k, v in (other.name_counts or {}).items():
            self.name_counts[str(k)] = self.name_counts.get(str(k), 0) + int(v)


def _top_name(counts: Dict[str, int]) -> str:
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))[0][0]


# ══════════════════════════════════════════════════════════════════════════
# 7. 偏置器（PPO 采集/评测共用）
# ══════════════════════════════════════════════════════════════════════════
class ArchetypeBias:
    """流派软偏置：检测 → 偏好表 → 非负 logit bias。

    ``coef=0`` 时**不要构造本对象**（``CollectConfig.archetype_bias_coef=0`` 即默认
    关闭 → 旧路径逐位等价）。
    """

    def __init__(self, *, table_path: str = DEFAULT_TABLE,
                 model_path: str = DEFAULT_MODEL, coef: float = 0.5,
                 min_prob: float = 0.6, max_bias: float = MAX_TOTAL,
                 card_index_of: Optional[Callable[[int], str]] = None,
                 cache: bool = False) -> None:
        self.coef = float(coef)
        self.min_prob = float(min_prob)
        self.table_path = str(table_path)
        self.model_path = str(model_path)
        if self.coef <= 0.0:
            raise ValueError("ArchetypeBias 需要 coef>0；coef=0 请不要构造对象")
        self.table = load_table(table_path)
        self.tribe_model, self.arch_model, self.hero_vocab, self.model_meta = \
            load_models(model_path)
        self.max_bias = float(max_bias)
        self.history = ArchetypeHistory()
        self.stats = ArchetypeBiasStats()
        self._card_index_of = card_index_of
        self._card_cache: Dict[int, str] = {}
        #: hero_vocab 的 ``{name: idx}`` 预映射（跳过 tuple.index 线性查找）
        self._hero_index: Dict[str, int] = {str(h): i
                                           for i, h in enumerate(self.hero_vocab)}
        #: 输入哈希缓存开关（默认关；命中率实测见 docs/PERF_COLLECT.md）。
        self.cache_enabled = bool(cache)
        self._cache: Dict[Any, Any] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        for key in ("baseline", "archetypes"):
            if key not in self.table:
                raise ValueError(f"流派偏好表缺字段 {key}: {table_path}")

    # -- 卡牌 id 解析（惰性缓存；引擎不可用时返回 ""）------------------------
    def card_id_of(self, index: int) -> str:
        i = int(index)
        got = self._card_cache.get(i)
        if got is not None:
            return got
        cid = ""
        if self._card_index_of is not None:
            try:
                cid = str(self._card_index_of(i) or "")
            except Exception:  # noqa: BLE001
                cid = ""
        self._card_cache[i] = cid
        return cid

    # -- 状态 ---------------------------------------------------------------
    def reset(self) -> None:
        self.history.reset()
        self.stats = ArchetypeBiasStats()

    def clear_state(self) -> None:
        """清逐局历史、保留累计统计（每局开始复用 policy 时调用）。"""
        self.history.clear_state()

    def _pref_for(self, name: str, *, level: str, b: int
                  ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """取 ``(pref_bucket, base_bucket)``；缺桶回退 ``all``，缺流派返回 None。"""
        table = self.table
        node = None
        if level == "archetype":
            node = (table.get("archetypes") or {}).get(name)
        else:
            node = (table.get("tribes") or {}).get(name)
        if not isinstance(node, dict):
            return None
        pref = node.get("pref") or {}
        key = bucket_key(b)
        pb = pref.get(key) or pref.get("all")
        base_all = table.get("baseline") or {}
        bb = base_all.get(key) or base_all.get("all")
        if not isinstance(pb, dict) or not isinstance(bb, dict):
            return None
        return pb, bb

    # -- 主入口 -------------------------------------------------------------
    def _stats_add(self, level: str, name: str, prob: float,
                   n_pos: int, bias_sum: float) -> None:
        """按「检测结果」累加统计（缓存命中时也要重放，保证口径一致）。"""
        self.stats.decisions += 1
        if level == "none":
            self.stats.lvl_none += 1
            return
        self.stats.detected += 1
        self.stats.prob_sum += float(prob)
        self.stats.name_counts[name] = self.stats.name_counts.get(name, 0) + 1
        if level == "archetype":
            self.stats.lvl_archetype += 1
        else:
            self.stats.lvl_tribe += 1
        if n_pos > 0:
            self.stats.applied += 1
            self.stats.bias_actions += int(n_pos)
            self.stats.bias_sum += float(bias_sum)

    def bias(self, features: Any, cards: Any, mask: Any, *,
             game_id: Any, seat: Any) -> Optional[np.ndarray]:
        """当前决策的 245 维 bias（无偏置返回 ``None``）；同时更新统计。

        可选**输入哈希缓存**（``ArchetypeBias(cache=True)`` / ``--archetype-cache 1``）：
        同一 ``(features, cards, mask, 历史修订号)`` 只算一次特征与分类；命中时直接
        重放统计并返回同一份 bias。**缓存与否输出逐位相同**（见
        ``tests/test_archetype_fast.py``）。实测命中率约 0（见 docs/PERF_COLLECT.md）。
        """
        obs = parse_obs(features, cards, hero_id_of=self.card_id_of)
        st = self.history.observe(game_id, seat, obs)
        key = None
        if self.cache_enabled:
            try:
                key = (hash(np.asarray(features, dtype=np.float32).tobytes()),
                       hash(np.asarray(cards).tobytes()),
                       hash(np.asarray(mask).tobytes()),
                       int(st.rev))
            except Exception:  # noqa: BLE001 - 非法输入 -> 不缓存
                key = None
            if key is not None:
                hit = self._cache.get(key)
                if hit is not None:
                    self.cache_hits += 1
                    level, name, prob, n_pos, bias_sum, arr = hit
                    self._stats_add(level, name, prob, n_pos, bias_sum)
                    return None if arr is None else arr.copy()
                self.cache_misses += 1
        x = self.history.vector(game_id, seat, obs, hero_vocab=self.hero_vocab,
                                hero_index=self._hero_index)
        p_t = self.tribe_model.probs(x)[0]
        p_a = self.arch_model.probs(x)[0]
        i_a = int(np.argmax(p_a))
        i_t = int(np.argmax(p_t))
        name_a = str(self.arch_model.classes[i_a])
        prob_a = float(p_a[i_a])
        name_t = str(self.tribe_model.classes[i_t])
        prob_t = float(p_t[i_t])
        b = bucket_of(obs.turn)

        level = "none"
        name = ""
        prob = 0.0
        got = None
        if name_a != "other" and prob_a >= self.min_prob:
            got = self._pref_for(name_a, level="archetype", b=b)
            if got is not None:
                level, name, prob = "archetype", name_a, prob_a
        if got is None and prob_t >= self.min_prob:
            got = self._pref_for(name_t, level="tribe", b=b)
            if got is not None:
                level, name, prob = "tribe", name_t, prob_t

        if got is None:
            self._stats_add("none", "", 0.0, 0, 0.0)
            if key is not None:
                self._cache_put(key, ("none", "", 0.0, 0, 0.0, None))
            return None
        pref, base = got
        bias = bias_from_pref(pref, base, obs, mask, coef=self.coef,
                              card_index_of=self.card_id_of, cards=cards)
        n_pos = int((bias > 0).sum())
        bias_sum = float(bias.sum())
        self._stats_add(level, name, prob, n_pos, bias_sum)
        if key is not None:
            self._cache_put(key, (level, name, prob, n_pos, bias_sum,
                                  None if n_pos == 0 else bias))
        if n_pos == 0:
            return None
        return bias

    def _cache_put(self, key: Any, val: Any) -> None:
        if len(self._cache) > 8192:
            self._cache.clear()
        self._cache[key] = val

    def cache_meta(self) -> Dict[str, Any]:
        """缓存命中率（写进 collect meta，便于判断是否值得开）。"""
        tot = int(self.cache_hits) + int(self.cache_misses)
        return {"archetype_cache_on": bool(self.cache_enabled),
                "archetype_cache_hits": int(self.cache_hits),
                "archetype_cache_misses": int(self.cache_misses),
                "archetype_cache_hit_rate": (float(self.cache_hits) / tot
                                             if tot else 0.0)}

    def note_action(self, action: Any, *, game_id: Any, seat: Any) -> None:
        """记录己方实际动作（供下一次决策的特征向量）。"""
        self.history.note_action(game_id, seat, action)

    # -- meta ---------------------------------------------------------------
    def to_meta(self) -> Dict[str, Any]:
        s = self.stats
        names = sorted((s.name_counts or {}).items(), key=lambda kv: (-kv[1], kv[0]))
        return {
            "archetype_bias": True,
            "archetype_bias_coef": float(self.coef),
            "archetype_min_prob": float(self.min_prob),
            "archetype_table": os.path.basename(self.table_path),
            "archetype_decisions": int(s.decisions),
            "archetype_detected": int(s.detected),
            #: 与 ``archetype_bias_applied`` 同值：任务书里约定的短名（历史 meta 兼容）
            "bias_applied": int(s.applied),
            "archetype_bias_applied": int(s.applied),
            "archetype_name": _top_name(s.name_counts),
            "archetype_names": {str(k): int(v) for k, v in names},
            "archetype_level_archetype": int(s.lvl_archetype),
            "archetype_level_tribe": int(s.lvl_tribe),
            "archetype_level_none": int(s.lvl_none),
            "archetype_mean_prob": (float(s.prob_sum / s.detected)
                                    if s.detected else 0.0),
            "archetype_bias_sum": float(s.bias_sum),
            "archetype_bias_actions": int(s.bias_actions),
        }

    def summary(self) -> Dict[str, Any]:
        """启动期写进 history 的摘要（不含逐决策统计）。"""
        return {
            "schema": str(self.table.get("schema", "")),
            "coef": float(self.coef),
            "min_prob": float(self.min_prob),
            "table_path": self.table_path,
            "model_path": self.model_path,
            "head_classes": len(self.arch_model.classes),
            "tribe_classes": len(self.tribe_model.classes),
            "tribe_top1_cv": self.model_meta.get("tribe_top1_cv"),
            "tribe_top3_cv": self.model_meta.get("tribe_top3_cv"),
            "arch_top1_cv": self.model_meta.get("arch_top1_cv"),
            "arch_top3_cv": self.model_meta.get("arch_top3_cv"),
        }


def aggregate_archetype_bias(metas: Iterable[Any]) -> Dict[str, Any]:
    """把多个 worker/game 的偏置统计汇总成 collect 段顶层字段。

    口径：计数 sum、``archetype_bias`` any、coef/min_prob 取首个、``archetype_names``
    按类求和、``archetype_name`` 取总数最大的名字。没有任何一条带 ``archetype_bias``
    的 meta（= 默认关闭）返回 ``{}``（不新增键）。
    """
    rows = [m for m in metas if isinstance(m, dict) and m.get("archetype_bias")]
    if not rows:
        return {}
    first = rows[0]
    sum_keys = ("archetype_decisions", "archetype_detected", "archetype_bias_applied",
                "archetype_level_archetype", "archetype_level_tribe",
                "archetype_level_none", "archetype_bias_actions")
    out: Dict[str, Any] = {
        "archetype_bias": True,
        "archetype_bias_coef": float(first.get("archetype_bias_coef", 0.0) or 0.0),
        "archetype_min_prob": float(first.get("archetype_min_prob", 0.6) or 0.6),
        "archetype_table": str(first.get("archetype_table", "") or ""),
    }
    for key in sum_keys:
        out[key] = int(sum(int(m.get(key, 0) or 0) for m in rows))
    out["bias_applied"] = int(out["archetype_bias_applied"])
    names: Dict[str, int] = {}
    prob_sum = 0.0
    bias_sum = 0.0
    for m in rows:
        prob_sum += float(m.get("archetype_mean_prob", 0.0) or 0.0) * int(
            m.get("archetype_detected", 0) or 0)
        bias_sum += float(m.get("archetype_bias_sum", 0.0) or 0.0)
        for k, v in (m.get("archetype_names") or {}).items():
            names[str(k)] = names.get(str(k), 0) + int(v)
    det = int(out["archetype_detected"])
    out["archetype_name"] = _top_name(names)
    out["archetype_names"] = names
    out["archetype_mean_prob"] = (prob_sum / det) if det else 0.0
    out["archetype_bias_sum"] = bias_sum
    return out


def engine_card_id_lookup() -> Optional[Callable[[int], str]]:
    """``hsbg_engine.card_info`` 包装成 ``index -> card_id``（引擎缺失返回 None）。"""
    try:
        import hsbg_engine as E  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    def _lookup(idx: int) -> str:
        try:
            return str(E.card_info(int(idx))[0] or "")
        except Exception:  # noqa: BLE001
            return ""

    return _lookup


__all__ = [
    "FEATURE_VERSION", "FEATURE_DIM", "FEATURE_BLOCKS", "HERO_VOCAB_SIZE",
    "TRIBES", "N_TRIBES", "ACTION_TYPES", "RHYTHM_TYPES", "TURN_BUCKETS",
    "N_BUCKETS", "DEFAULT_TABLE", "DEFAULT_MODEL",
    "RATE_CAP", "AFF_SCALE", "CARD_MIN_SHARE", "CARD_SCALE", "MAX_TOTAL",
    "bucket_of", "bucket_key", "bucket_keys", "feature_names",
    "ArchetypeObs", "parse_obs", "action_type_of",
    "ArchetypeHistory", "build_vector", "_Hist",
    "SoftmaxModel", "save_model", "load_models",
    "load_table", "bias_from_pref",
    "ArchetypeBiasStats", "ArchetypeBias",
    "aggregate_archetype_bias", "engine_card_id_lookup",
]
