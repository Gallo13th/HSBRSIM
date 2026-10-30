"""真实人类对局（Firestone 回放）→ PPO 的 **BC 辅助正则**（形态 A：小权重辅助 CE）。

本模块做四件事，默认不参与任何训练路径（``bc_coef=0`` 时零影响）：

1. :func:`load_bc_samples`：读 ``data/firestone_bc/bc_samples.jsonl.gz``，按动作白名单、
   动作下标合法性、MMR 下限过滤，返回 numpy 数组池（含 MMR 权重 / 类别计数 /
   卡牌身份标签）；
2. :func:`bc_obs_batch`：把样本编码成我们固定 ``3227 floats + 124 cards`` 观测的
   **部分观测**（只填回放可见的槽位：商店 8 槽、手牌 10 槽、棋盘 7 槽、gold/tier/
   health/turn/hero；未知槽位补 0 并写 mask），同时产出 245 动作 -> 9/10 类的
   ``type_ids`` 与卡牌身份标签；
3. :func:`bc_type_logits` / :func:`bc_hier_loss`：**分层目标**——245 动作 logits 按动作
   类型做 log-sum-exp 聚合的 9 类 CE（对槽位错位不敏感；启用 ``--bc-include-reposition``
   时追加第 10 类 ``reposition`` = Move 196..244）+ buy/play 样本上的
   3983 类卡牌身份 CE；两层按 ``bc_type_weight`` / ``bc_card_weight`` 加权；
4. :func:`bc_ce_loss`：旧的 245 维 class-balanced（动作类别频率倒数归一）+ MMR 加权
   CE，保留给对照/兼容测试；新训练路径使用分层目标。

设计/数据质量/风险/启用方式见 ``docs/BC_AUX.md``。数据字段以
``data/firestone_bc/SCHEMA.md`` 与实际抽样为准（``action_index`` 已映射到 245 动作）。

约束
----
- 本模块在**没有 torch / 没有引擎**的机器上仍可 import（torch 在 CE 内惰性导入）；
- 所有布局偏移来自 :mod:`hsbg.env.obs_std`，动作段来自
  :mod:`hsbg.env.action_space_std`，不硬编码偏移；
- BC 是**条件辅助目标**：动作掩码只覆盖与白名单动作类型相关的“可观测候选动作”，
  不是引擎 ``legal_mask`` 的精确重建（见 docs 的风险一节）。
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.seq_aux import (  # noqa: F401 - 对外复用/重导出
    RampPoints,
    SeqCoefSchedule,
    format_coef_ramp,
    parse_coef_ramp,
    ramp_coef,
    resolve_coef,
)
from hsbg.env import action_space_std as ACT
from hsbg.env import obs_std as O

__all__ = [
    "DEFAULT_BC_SAMPLES_PATH",
    "DEFAULT_MMR_MIN",
    "DEFAULT_BC_ACTION_TYPES",
    "BC_ACTION_TYPES",
    "BC_ACTION_CLASSES",
    "BC_TYPE_CLASSES",
    "N_BC_TYPES",
    "BC_REPOSITION_TYPE",
    "BC_ACTION_TYPES_WITH_REPOSITION",
    "N_BC_TYPES_WITH_REPOSITION",
    "BC_MOVE_SLICE",
    "bc_action_types",
    "BC_CARD_TYPE_NAMES",
    "BC_CARD_CLASS_IDS",
    "BC_STATIC_TYPE_IDS",
    "STD_ACTION_SEGMENT",
    "ACTION_TYPE_TABLE",
    "BC_CARD_TABLE_PATH",
    "BCCardTable",
    "BCSamples",
    "BCObsLayout",
    "BC_OBS_LAYOUT",
    "BCObsBatch",
    "mmr_weight",
    "load_bc_card_table",
    "bc_card_head_size",
    "load_bc_samples",
    "bc_obs_batch",
    "bc_type_ids",
    "bc_class_balance_weights",
    "parse_bc_class_weights",
    "bc_ce_loss",
    "bc_type_logits",
    "bc_card_ce_loss",
    "bc_hier_loss",
    "parse_bc_coef_ramp",
    "bc_pool_summary",
]

# ══════════════════════════════════════════════════════════════════════════
# 0. 常量
# ══════════════════════════════════════════════════════════════════════════
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
DEFAULT_BC_SAMPLES_PATH = os.path.join(
    _REPO_ROOT, "data", "firestone_bc", "bc_samples.jsonl.gz")
BC_CARD_TABLE_PATH = os.path.join(
    _REPO_ROOT, "rust", "crates", "hsbg-engine", "data", "cards.json")
DEFAULT_MMR_MIN = 6000

#: 白名单：标签干净、回放状态覆盖足够高的动作类型。顺序即类别 id 顺序。
DEFAULT_BC_ACTION_TYPES: Tuple[str, ...] = (
    "sell", "reroll", "buy_minion", "buy_spell", "play_spell",
    "play_minion", "upgrade", "hero_power", "end_turn",
)
BC_ACTION_TYPES = DEFAULT_BC_ACTION_TYPES
BC_ACTION_CLASSES: Dict[str, int] = {
    name: i for i, name in enumerate(BC_ACTION_TYPES)
}

#: 可选第 10 类：棋盘换位（Move 196..244）。默认**不启用**（9 类 = 历史行为）。
#:
#: 动机：9 类白名单完全不监督 Move 族，而 entity 的 Move logits 是棋盘 token 的
#: 双线性项，容易随 trunk 漂移后在推理时抢占 argmax（见 ``docs/BC_PRETRAIN.md``
#: §5.1）。把 ``reposition`` 追加成第 10 类后，196..244 作为**一个类型**参与
#: log-sum-exp 聚合 CE：模型既学会“什么时候该换位”，也被约束“非换位样本上
#: 换位族的总概率不能过大”。
BC_REPOSITION_TYPE: str = "reposition"
BC_ACTION_TYPES_WITH_REPOSITION: Tuple[str, ...] = (
    tuple(DEFAULT_BC_ACTION_TYPES) + (BC_REPOSITION_TYPE,))
N_BC_TYPES_WITH_REPOSITION: int = len(BC_ACTION_TYPES_WITH_REPOSITION)

#: 分层 BC 的「动作类型」类别 = BC 白名单顺序（9 类；与 ``action_class`` 对齐）。
BC_TYPE_CLASSES: Tuple[str, ...] = tuple(BC_ACTION_TYPES)
N_BC_TYPES: int = len(BC_TYPE_CLASSES)
if N_BC_TYPES != 9:  # pragma: no cover - 常量漂移防御
    raise AssertionError(f"分层 BC 类型数应为 9，得到 {N_BC_TYPES}")
if N_BC_TYPES_WITH_REPOSITION != 10:  # pragma: no cover - 常量漂移防御
    raise AssertionError(
        f"含 reposition 的分层 BC 类型数应为 10，得到 {N_BC_TYPES_WITH_REPOSITION}")

#: Move 段下标区间（196..244，`from*7 + to`）。
BC_MOVE_SLICE: slice = slice(
    int(ACT.A_MOVE), int(ACT.A_MOVE) + int(ACT.N_BOARD) * int(ACT.N_BOARD))


def bc_action_types(include_reposition: bool = False) -> Tuple[str, ...]:
    """返回 BC 动作类型表：默认 9 类（历史行为），``True`` = 追加 ``reposition``。"""
    return (BC_ACTION_TYPES_WITH_REPOSITION if bool(include_reposition)
            else tuple(DEFAULT_BC_ACTION_TYPES))

#: 需要「卡牌身份」监督的 BC 类型（buy/play 四类；其余类型的 card CE 不参与）。
BC_CARD_TYPE_NAMES: Tuple[str, ...] = (
    "buy_minion", "buy_spell", "play_minion", "play_spell")
BC_CARD_CLASS_IDS: Tuple[int, ...] = tuple(
    BC_ACTION_CLASSES[name] for name in BC_CARD_TYPE_NAMES)

#: 默认两层权重（总 BC = ``w_type*CE_type + w_card*CE_card``，再乘 ``bc_coef``）。
DEFAULT_BC_TYPE_WEIGHT = 1.0
DEFAULT_BC_CARD_WEIGHT = 0.5

#: 卡表里 ``_G`` 是金色变体（卡表有独立条目），这里只用于 golden 位。
_GOLDEN_RE = re.compile(r"_G$")
#: 英雄皮肤后缀（与 ``scripts/import_real_library.py`` 同一规则）。
_SKIN_RE = re.compile(r"_SKIN_[A-Z0-9]+$")


# ── 动作段 / 类型映射（分层 BC）───────────────────────────────────────────
def _build_action_segment_table(n_actions: int = N_ACTIONS) -> Tuple[str, ...]:
    """245 个标准动作 -> 段名（来自 :data:`hsbg.env.action_space_std.SEGMENTS`）。

    前 245 项必须恰好被标准段连续覆盖一次；扩展段（>=245）不参与 BC。
    """
    seg = [""] * int(n_actions)
    for name, lo, hi, _count, _desc in ACT.SEGMENTS:
        for i in range(max(0, int(lo)), min(int(hi), int(n_actions))):
            if seg[i]:
                raise AssertionError(
                    f"动作 {i} 同时属于动作段 {seg[i]!r} 与 {name!r}（段重叠）")
            seg[i] = str(name)
    missing = [i for i, s in enumerate(seg) if not s]
    if missing:
        raise AssertionError(f"动作段未覆盖标准动作下标：{missing[:8]}...")
    return tuple(seg)


#: ``STD_ACTION_SEGMENT[i]`` = 标准动作 ``i`` 所属段名（14 段，唯一归属）。
STD_ACTION_SEGMENT: Tuple[str, ...] = _build_action_segment_table()


def _build_static_type_ids() -> np.ndarray:
    """与样本无关的 245 -> 9 类映射（``-1`` = 不参与类型聚合）。

    静态可分的 7 类：end_turn / reroll / upgrade / hero_power / sell /
    buy_minion（商店 0..6）/ buy_spell（商店第 7 槽 = 酒馆法术槽）。
    ``play_spell`` / ``play_minion`` 无法从动作下标静态区分（取决于手牌该槽是
    随从还是法术），由 :func:`bc_type_ids` 按样本观测的手牌卡种动态细分。
    """
    ids = np.full(N_ACTIONS, -1, dtype=np.int16)

    def _fill(name: str, actions: Iterable[int]) -> None:
        cls = int(BC_ACTION_CLASSES[name])
        for a in actions:
            ai = int(a)
            if not 0 <= ai < N_ACTIONS:
                raise AssertionError(f"类型 {name} 的动作下标越界：{ai}")
            if ids[ai] != -1 and int(ids[ai]) != cls:
                raise AssertionError(
                    f"动作 {ai} 同时映射到类型 {int(ids[ai])} 与 {cls}")
            ids[ai] = cls

    _fill("end_turn", (ACT.A_END,))
    _fill("reroll", (ACT.A_REFRESH,))
    _fill("upgrade", (ACT.A_UPGRADE,))
    _fill("hero_power", range(ACT.A_HERO_POWER, ACT.A_HERO_POWER + ACT.N_POWERS))
    _fill("sell", range(ACT.A_SELL, ACT.A_SELL + ACT.N_BOARD))
    # 酒馆第 7 槽（``A_BUY+7``）是酒馆法术槽；0..6 是随从槽。
    _fill("buy_minion", range(ACT.A_BUY, ACT.A_BUY + ACT.N_SHOP - 1))
    _fill("buy_spell", (ACT.A_BUY + ACT.N_SHOP - 1,))
    return ids


#: 245 -> 9 类静态映射（play_* 为 -1，见 :func:`bc_type_ids`）。
BC_STATIC_TYPE_IDS: np.ndarray = _build_static_type_ids()


def _build_action_type_table() -> Tuple[str, ...]:
    """245 个动作 -> **唯一**动作类型名（段级；``play`` 段保留 ``"play"``）。

    与 :func:`bc_type_ids` 的区别：本表与样本无关，用于“每个动作唯一归属”的静态
    校验；``play`` 段在运行时按手牌卡种细分为 ``play_spell`` / ``play_minion``。
    """
    out = []
    for a in range(N_ACTIONS):
        seg = STD_ACTION_SEGMENT[a]
        if seg == "buy":
            out.append("buy_spell" if a == ACT.A_BUY + ACT.N_SHOP - 1
                       else "buy_minion")
        elif seg == "refresh":  # BC 白名单里叫 reroll
            out.append("reroll")
        else:
            out.append(seg)
    return tuple(out)


#: ``ACTION_TYPE_TABLE[i]`` = 标准动作 ``i`` 的唯一类型名（245 项）。
ACTION_TYPE_TABLE: Tuple[str, ...] = _build_action_type_table()

#: 观测里我们实际填写/可信的“叶子”切片（用于单测验证不重叠）。
#: 由 :func:`_build_bc_obs_layout` 从 obs_std 常量生成。


@dataclass(frozen=True)
class BCCardTable:
    """卡表静态信息（index 0 = 空槽；``index = cards.json 数组下标 + 1``）。

    与 ``hsbg_engine`` 的卡牌 embedding 下标一致；只保存 BC 编码需要的字段。
    """

    ids: Tuple[str, ...]
    id_to_index: Mapping[str, int]
    kind: np.ndarray          # int8: 0=unknown, 1=minion, 2=spell
    tier: np.ndarray          # float32
    atk: np.ndarray           # float32
    hp: np.ndarray            # float32
    cost: np.ndarray          # float32
    keywords: np.ndarray      # int32 bitmask（顺序 = O.KEYWORD_NAMES）
    races: np.ndarray         # int32 bitmask（顺序 = O.RACE_NAMES）

    @property
    def n_cards(self) -> int:
        return int(self.kind.shape[0])

    @property
    def n_ids(self) -> int:
        """卡牌条目数（不含 index 0 空槽；37.0.0 = 3983）。"""
        return int(self.kind.shape[0]) - 1


def load_bc_card_table(path: Optional[str] = None) -> BCCardTable:
    """读 ``rust/crates/hsbg-engine/data/cards.json``，返回 BC 编码用卡表。"""
    p = str(path or BC_CARD_TABLE_PATH)
    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cards = raw.get("cards") if isinstance(raw, dict) else raw
    if not isinstance(cards, list):
        raise ValueError(f"cards.json 结构异常（无 cards 数组）: {p}")
    n = len(cards) + 1
    kind = np.zeros(n, dtype=np.int8)
    tier = np.zeros(n, dtype=np.float32)
    atk = np.zeros(n, dtype=np.float32)
    hp = np.zeros(n, dtype=np.float32)
    cost = np.zeros(n, dtype=np.float32)
    keywords = np.zeros(n, dtype=np.int32)
    races = np.zeros(n, dtype=np.int32)
    ids: List[str] = [""] * n
    id_to_index: Dict[str, int] = {}
    kw_index = {name: i for i, name in enumerate(O.KEYWORD_NAMES)}
    race_index = {name: i for i, name in enumerate(O.RACE_NAMES)}
    for i, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        idx = i + 1
        cid = card.get("id")
        if isinstance(cid, str):
            ids[idx] = cid
            # 与 Rust ``by_id.insert`` 一致：重复 id 后者覆盖
            id_to_index[cid] = idx
        k = str(card.get("kind") or "").lower()
        if k == "minion":
            kind[idx] = 1
        elif k in ("spell", "tavern_spell", "battleground_spell"):
            kind[idx] = 2
        tier[idx] = float(card.get("tier") or 0)
        atk[idx] = float(card.get("atk") or 0)
        hp[idx] = float(card.get("hp") or 0)
        cost[idx] = float(card.get("cost") or 0)
        for kw in card.get("keywords") or []:
            j = kw_index.get(str(kw).upper())
            if j is not None:
                keywords[idx] |= (1 << j)
        for race in card.get("races") or []:
            j = race_index.get(str(race).upper())
            if j is not None:
                races[idx] |= (1 << j)
    return BCCardTable(ids=tuple(ids), id_to_index=id_to_index, kind=kind,
                       tier=tier, atk=atk, hp=hp, cost=cost,
                       keywords=keywords, races=races)


_CARD_HEAD_SIZE_CACHE: Optional[int] = None


def bc_card_head_size(cards_path: Optional[str] = None) -> int:
    """卡牌身份头输出维度 = 卡表条目数（不含空槽；37.0.0 = 3983）。

    标签是 ``card_id`` 经 :meth:`BCCardTable.id_to_index` 映射后的 **0-based** 下标
    （= 卡表下标 - 1），与模型侧 ``card_head`` 的输出维一致。
    ``cards_path`` 为 None 时用仓库默认卡表并缓存；换卡表版本时缓存需重建进程。
    """
    global _CARD_HEAD_SIZE_CACHE
    if cards_path is None and _CARD_HEAD_SIZE_CACHE is not None:
        return int(_CARD_HEAD_SIZE_CACHE)
    n = int(load_bc_card_table(cards_path).n_ids)
    if n <= 0:
        raise ValueError("卡表为空：无法确定 card_head 维度")
    if cards_path is None:
        _CARD_HEAD_SIZE_CACHE = int(n)
    return int(n)


# ══════════════════════════════════════════════════════════════════════════
# 1. 样本池
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class BCSamples:
    """过滤后的 BC 样本池（SoA numpy 数组；``n = len(action_index)``）。"""

    action_index: np.ndarray          # int64[n]
    action_class: np.ndarray          # int16[n]（下标到 action_types）
    action_types: Tuple[str, ...]
    mmr: np.ndarray                   # int32[n]
    weight: np.ndarray                # float32[n]（MMR 权重）
    #: 稀有动作类别覆盖权重（``class_weight_overrides``；默认全 1.0）。
    #: 在 loss 里与 class-balanced 权重、MMR 权重逐样本相乘。
    class_weight: np.ndarray          # float32[n]
    turn: np.ndarray                  # int16[n]（0 = 未知）
    gold: np.ndarray                  # int16[n]
    tier: np.ndarray                  # int16[n]
    health: np.ndarray                # int16[n]
    armor: np.ndarray                 # int16[n]
    turn_known: np.ndarray            # bool[n]
    gold_known: np.ndarray            # bool[n]
    tier_known: np.ndarray            # bool[n]
    health_known: np.ndarray          # bool[n]
    armor_known: np.ndarray           # bool[n]
    hero: np.ndarray                  # int32[n]（卡表下标+1；0=未知）
    shop: np.ndarray                  # int32[n, N_SHOP]
    shop_present: np.ndarray          # bool[n, N_SHOP]
    hand: np.ndarray                  # int32[n, N_HAND]
    hand_present: np.ndarray          # bool[n, N_HAND]
    board: np.ndarray                 # int32[n, N_BOARD]
    board_present: np.ndarray         # bool[n, N_BOARD]
    class_counts: np.ndarray          # int64[C]（全池类别计数）
    #: 卡牌身份标签：``card_id`` -> 卡表下标-1（0-based）；-1 = 不可用/不适用。
    card_target: np.ndarray            # int32[n]
    #: 该样本是否参与卡牌身份 CE（buy/play 四类且 card_id 映射成功）。
    card_valid: np.ndarray             # bool[n]
    card_table: BCCardTable
    path: str = ""
    mmr_min: int = DEFAULT_MMR_MIN
    meta: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.action_index.shape[0])

    def class_distribution(self) -> Dict[str, int]:
        """``{action_type: count}``（只含全池计数，顺序同 action_types）。"""
        return {name: int(self.class_counts[i])
                for i, name in enumerate(self.action_types)}


def mmr_weight(mmr: Any, *, mmr_min: int = DEFAULT_MMR_MIN,
               mmr_full: int = 8000, boost: float = 1.0) -> float:
    """MMR 权重：``mmr < mmr_min -> 0``；默认 ``>= mmr_min -> 1.0``。

    ``boost > 1`` 时在 ``[mmr_min, mmr_full]`` 上从 1.0 线性升到 ``boost``，
    ``mmr >= mmr_full`` 后保持 ``boost``（“6000–8000 线性增强”可选）。
    """
    try:
        m = float(mmr)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(m) or m < float(mmr_min):
        return 0.0
    b = float(boost)
    if not math.isfinite(b) or b <= 1.0:
        return 1.0
    if m >= float(mmr_full):
        return b
    lo, hi = float(mmr_min), float(mmr_full)
    if hi <= lo:
        return b
    frac = (m - lo) / (hi - lo)
    return float(1.0 + (b - 1.0) * max(0.0, min(1.0, frac)))


def _resolve_path(path: str) -> str:
    p = os.path.expanduser(str(path))
    if not os.path.isabs(p) and not os.path.isfile(p):
        cand = os.path.join(_REPO_ROOT, p)
        if os.path.isfile(cand):
            return cand
    return p


def _open_text(path: str):
    """透明读取 ``.gz`` / 纯文本 JSONL。"""
    p = _resolve_path(path)
    if p.endswith(".gz"):
        return gzip.open(p, "rt", encoding="utf-8")
    return open(p, "r", encoding="utf-8")


def _allowed_actions(actions: Optional[Any]) -> Optional[np.ndarray]:
    """``actions`` -> bool[N_ACTIONS]；None = 全部合法。"""
    if actions is None:
        return None
    arr = np.asarray(actions)
    if arr.dtype == bool:
        if arr.size != N_ACTIONS:
            raise ValueError(
                f"actions 布尔掩码长度 {arr.size} != N_ACTIONS {N_ACTIONS}")
        return arr.reshape(-1)
    out = np.zeros(N_ACTIONS, dtype=bool)
    for a in arr.reshape(-1):
        ai = int(a)
        if 0 <= ai < N_ACTIONS:
            out[ai] = True
    return out


def _place_cards(cards: Any, positions: Any, cap: int,
                 table: BCCardTable) -> Tuple[np.ndarray, np.ndarray]:
    """卡 id 列表 + 位置 -> ``(index[cap], present[cap])``；未知卡/越界位置跳过。"""
    idx = np.zeros(int(cap), dtype=np.int32)
    present = np.zeros(int(cap), dtype=bool)
    if not isinstance(cards, (list, tuple)):
        return idx, present
    pos_list = positions if isinstance(positions, (list, tuple)) else []
    for i, cid in enumerate(cards):
        if not isinstance(cid, str) or not cid:
            continue
        ci = table.id_to_index.get(cid)
        if ci is None:
            # 允许皮肤/未知 UI 卡：不填入，避免把 0 当真实卡
            continue
        pos = int(pos_list[i]) if i < len(pos_list) else int(i)
        if 0 <= pos < int(cap):
            idx[pos] = int(ci)
            present[pos] = True
    return idx, present


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return int(f)


def _map_hero(hero: Any, table: BCCardTable) -> int:
    """英雄卡 id -> 卡表下标+1；先直接命中，再去皮肤后缀。失败返回 0。"""
    if not isinstance(hero, str) or not hero:
        return 0
    ci = table.id_to_index.get(hero)
    if ci is not None:
        return int(ci)
    base = _SKIN_RE.sub("", hero)
    if base and base in table.id_to_index:
        return int(table.id_to_index[base])
    return 0


def _map_card_label(card_id: Any, table: BCCardTable) -> int:
    """动作卡牌 id -> 卡牌身份头标签（0-based，= 卡表下标 - 1）。失败返回 -1。

    只接受卡表里能命中的 id（金色 ``_G`` 变体在卡表中有独立条目）；映射失败
    的样本只是**不参与 card CE**，仍参与 type CE（见 :data:`BC_CARD_CLASS_IDS`）。
    """
    if not isinstance(card_id, str) or not card_id:
        return -1
    ci = table.id_to_index.get(card_id)
    if ci is None:
        return -1
    label = int(ci) - 1
    return label if 0 <= label < table.n_ids else -1


def parse_bc_class_weights(spec: str,
                          action_types: Optional[Sequence[str]] = None
                          ) -> Dict[str, float]:
    """解析稀有动作类别权重覆盖串：``"upgrade=4,hero_power=2"``。

    空串 -> ``{}``（现状，零影响）。名称必须属于 ``action_types``（默认 9 类
    白名单；启用 reposition 监督时传入含 ``"reposition"`` 的 10 类表，即可写
    ``"reposition=2"``），值必须是有限正数；格式错误立刻 ``ValueError``
    （CLI 启动期 fail-fast）。
    """
    text = str(spec or "").strip()
    if not text:
        return {}
    allowed = set(action_types or DEFAULT_BC_ACTION_TYPES)
    out: Dict[str, float] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, raw = part.partition("=")
        name = name.strip()
        if not sep or not name:
            raise ValueError(f"类别权重项格式应为 name=value，得到 {part!r}")
        if name not in allowed:
            raise ValueError(
                f"未知 BC 动作类别 {name!r}；可选: {sorted(allowed)}")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"类别权重 {name!r} 不是数字: {raw!r}") from exc
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"类别权重 {name!r} 必须是有限正数，得到 {value!r}")
        out[name] = float(value)
    return out


def load_bc_samples(path: str = DEFAULT_BC_SAMPLES_PATH, *,
                    actions: Optional[Any] = None,
                    mmr_min: int = DEFAULT_MMR_MIN,
                    limit: Optional[int] = None,
                    action_types: Optional[Sequence[str]] = None,
                    cards_path: Optional[str] = None,
                    mmr_full: int = 8000,
                    mmr_boost: float = 1.0,
                    class_weight_overrides: Optional[Mapping[str, float]] = None
                    ) -> BCSamples:
    """加载并过滤 BC 样本。

    过滤规则（缺一即跳过）：

    1. ``action_type`` 在白名单（默认 :data:`DEFAULT_BC_ACTION_TYPES`，9 类；
       传 :data:`BC_ACTION_TYPES_WITH_REPOSITION` = 追加 ``reposition``，10 类）；
    2. ``action_index`` 是合法整数（``0 <= a < 245``），且在 ``actions`` 允许集合内；
    3. ``mmr`` 可解析且 ``>= mmr_min``（缺失 MMR 视为不可用）。

    ``gold/tier/health/turn/armor`` 缺失不丢样本：对应值填 0、``*_known=False``，
    编码时 mask 为假（部分观测）。``shop/hand/board`` 中的未知卡 id 直接跳过该槽。

    返回 :class:`BCSamples`（numpy 数组 + 类别计数 + 卡表），``limit`` 为保留条数上限
    （按文件顺序；用于单测/小规模冒烟）。
    """
    types = tuple(action_types or DEFAULT_BC_ACTION_TYPES)
    class_map = {name: i for i, name in enumerate(types)}
    # 稀有动作类别权重覆盖（默认空 = 现状）：在 class-balanced 权重之上再乘
    overrides: Dict[str, float] = {}
    if class_weight_overrides is not None:
        for _name, _value in dict(class_weight_overrides).items():
            _name = str(_name)
            if _name not in class_map:
                raise ValueError(
                    f"未知 BC 动作类别 {_name!r}；可选: {sorted(class_map)}")
            _v = float(_value)
            if not math.isfinite(_v) or _v <= 0.0:
                raise ValueError(
                    f"类别权重 {_name!r} 必须是有限正数，得到 {_v!r}")
            overrides[_name] = float(_v)
    allowed = _allowed_actions(actions)
    table = load_bc_card_table(cards_path)
    cap = int(limit) if limit is not None and int(limit) >= 0 else None

    action_index: List[int] = []
    action_class: List[int] = []
    mmr_list: List[int] = []
    weight_list: List[float] = []
    class_weight_list: List[float] = []
    turn_l: List[int] = []
    gold_l: List[int] = []
    tier_l: List[int] = []
    health_l: List[int] = []
    armor_l: List[int] = []
    known = {k: [] for k in ("turn", "gold", "tier", "health", "armor")}
    hero_l: List[int] = []
    shop_l: List[np.ndarray] = []
    shop_p: List[np.ndarray] = []
    hand_l: List[np.ndarray] = []
    hand_p: List[np.ndarray] = []
    board_l: List[np.ndarray] = []
    board_p: List[np.ndarray] = []
    card_l: List[int] = []
    card_valid_l: List[bool] = []

    total_lines = 0
    skipped = {k: 0 for k in (
        "bad_json", "action_type", "action_index", "action_not_allowed",
        "mmr", "mmr_low")}

    with _open_text(path) as f:
        for line in f:
            if cap is not None and len(action_index) >= cap:
                break
            total_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except (ValueError, TypeError):
                skipped["bad_json"] += 1
                continue
            if not isinstance(r, dict):
                skipped["bad_json"] += 1
                continue
            atype = r.get("action_type")
            if not isinstance(atype, str) or atype not in class_map:
                skipped["action_type"] += 1
                continue
            ai = _int_or_none(r.get("action_index"))
            if ai is None or not (0 <= ai < N_ACTIONS):
                skipped["action_index"] += 1
                continue
            if allowed is not None and not bool(allowed[ai]):
                skipped["action_not_allowed"] += 1
                continue
            m = _int_or_none(r.get("mmr"))
            if m is None:
                skipped["mmr"] += 1
                continue
            if m < int(mmr_min):
                skipped["mmr_low"] += 1
                continue
            w = mmr_weight(m, mmr_min=int(mmr_min), mmr_full=int(mmr_full),
                           boost=float(mmr_boost))
            if w <= 0.0:
                skipped["mmr_low"] += 1
                continue

            cls = int(class_map[atype])
            action_index.append(int(ai))
            action_class.append(cls)
            mmr_list.append(int(m))
            weight_list.append(float(w))
            class_weight_list.append(float(overrides.get(atype, 1.0)))
            label = _map_card_label(r.get("card_id"), table)
            card_l.append(int(label))
            card_valid_l.append(bool(label >= 0 and cls in BC_CARD_CLASS_IDS))
            for key, dst in (("turn", turn_l), ("gold", gold_l), ("tier", tier_l),
                             ("health", health_l), ("armor", armor_l)):
                v = _int_or_none(r.get(key))
                dst.append(int(v) if v is not None else 0)
                known[key].append(v is not None)
            hero_l.append(_map_hero(r.get("hero"), table))
            sc, sp = _place_cards(r.get("shop_cards"), r.get("shop_pos"),
                                  O.N_SHOP, table)
            hc, hp = _place_cards(r.get("hand_cards"), r.get("hand_pos"),
                                  O.N_HAND, table)
            bc, bp = _place_cards(r.get("board_cards"), r.get("board_pos"),
                                  O.N_BOARD, table)
            shop_l.append(sc); shop_p.append(sp)
            hand_l.append(hc); hand_p.append(hp)
            board_l.append(bc); board_p.append(bp)

    n = len(action_index)
    counts = np.bincount(np.asarray(action_class, dtype=np.int64),
                         minlength=len(types)).astype(np.int64) if n else \
        np.zeros(len(types), dtype=np.int64)
    if n == 0:
        empty_i32 = np.zeros((0, O.N_SHOP), dtype=np.int32)
        return BCSamples(
            action_index=np.zeros(0, dtype=np.int64),
            action_class=np.zeros(0, dtype=np.int16),
            action_types=types, mmr=np.zeros(0, dtype=np.int32),
            weight=np.zeros(0, dtype=np.float32),
            class_weight=np.zeros(0, dtype=np.float32),
            turn=np.zeros(0, dtype=np.int16), gold=np.zeros(0, dtype=np.int16),
            tier=np.zeros(0, dtype=np.int16), health=np.zeros(0, dtype=np.int16),
            armor=np.zeros(0, dtype=np.int16),
            turn_known=np.zeros(0, dtype=bool), gold_known=np.zeros(0, dtype=bool),
            tier_known=np.zeros(0, dtype=bool), health_known=np.zeros(0, dtype=bool),
            armor_known=np.zeros(0, dtype=bool),
            hero=np.zeros(0, dtype=np.int32),
            shop=empty_i32, shop_present=np.zeros((0, O.N_SHOP), dtype=bool),
            hand=np.zeros((0, O.N_HAND), dtype=np.int32),
            hand_present=np.zeros((0, O.N_HAND), dtype=bool),
            board=np.zeros((0, O.N_BOARD), dtype=np.int32),
            board_present=np.zeros((0, O.N_BOARD), dtype=bool),
            class_counts=counts,
            card_target=np.zeros(0, dtype=np.int32),
            card_valid=np.zeros(0, dtype=bool),
            card_table=table, path=_resolve_path(path),
            mmr_min=int(mmr_min),
            meta={"lines": total_lines, "kept": 0, "skipped": skipped,
                  "mmr_boost": float(mmr_boost), "mmr_full": int(mmr_full),
                  "class_weight_overrides": dict(overrides)})

    return BCSamples(
        action_index=np.asarray(action_index, dtype=np.int64),
        action_class=np.asarray(action_class, dtype=np.int16),
        action_types=types,
        mmr=np.asarray(mmr_list, dtype=np.int32),
        weight=np.asarray(weight_list, dtype=np.float32),
        class_weight=np.asarray(class_weight_list, dtype=np.float32),
        turn=np.asarray(turn_l, dtype=np.int16),
        gold=np.asarray(gold_l, dtype=np.int16),
        tier=np.asarray(tier_l, dtype=np.int16),
        health=np.asarray(health_l, dtype=np.int16),
        armor=np.asarray(armor_l, dtype=np.int16),
        turn_known=np.asarray(known["turn"], dtype=bool),
        gold_known=np.asarray(known["gold"], dtype=bool),
        tier_known=np.asarray(known["tier"], dtype=bool),
        health_known=np.asarray(known["health"], dtype=bool),
        armor_known=np.asarray(known["armor"], dtype=bool),
        hero=np.asarray(hero_l, dtype=np.int32),
        shop=np.stack(shop_l), shop_present=np.stack(shop_p),
        hand=np.stack(hand_l), hand_present=np.stack(hand_p),
        board=np.stack(board_l), board_present=np.stack(board_p),
        class_counts=counts,
        card_target=np.asarray(card_l, dtype=np.int32),
        card_valid=np.asarray(card_valid_l, dtype=bool),
        card_table=table, path=_resolve_path(path),
        mmr_min=int(mmr_min),
        meta={"lines": total_lines, "kept": int(n), "skipped": skipped,
              "mmr_boost": float(mmr_boost), "mmr_full": int(mmr_full),
              "class_weight_overrides": dict(overrides)})


def bc_pool_summary(samples: BCSamples) -> Dict[str, Any]:
    """池摘要（进启动日志 / summary.json；不含大数组）。"""
    n = len(samples)
    out: Dict[str, Any] = {
        "path": samples.path,
        "samples": int(n),
        "mmr_min": int(samples.mmr_min),
        "mmr_mean": (float(samples.mmr.mean()) if n else 0.0),
        "mmr_max": (int(samples.mmr.max()) if n else 0),
        "class_counts": samples.class_distribution(),
        "class_fractions": {
            k: (float(v) / n if n else 0.0)
            for k, v in samples.class_distribution().items()},
        "card_valid": int(samples.card_valid.sum()) if n else 0,
        "card_valid_rate": float(samples.card_valid.mean()) if n else 0.0,
        "filter": dict(samples.meta),
    }
    return out


# ══════════════════════════════════════════════════════════════════════════
# 2. 布局与部分观测编码
# ══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class BCObsLayout:
    """BC 编码实际使用的切片（全部由 ``hsbg.env.obs_std`` 常量派生）。

    ``leaf_slices`` 是互不重叠的叶子切片，单测会检查它们不重叠且不越界。
    """

    global_slice: slice
    board_slice: slice
    hand_slice: slice
    shop_slice: slice
    board_slots: Tuple[slice, ...]
    hand_slots: Tuple[slice, ...]
    shop_slots: Tuple[slice, ...]
    card_hero: slice
    card_board: slice
    card_hand: slice
    card_shop: slice
    leaf_slices: Tuple[slice, ...]
    card_leaf_slices: Tuple[slice, ...]

    def describe(self) -> Dict[str, Any]:
        def _sl(s: slice) -> List[int]:
            return [int(s.start), int(s.stop)]
        return {
            "global": _sl(self.global_slice),
            "board": _sl(self.board_slice),
            "hand": _sl(self.hand_slice),
            "shop": _sl(self.shop_slice),
            "card_hero": _sl(self.card_hero),
            "card_board": _sl(self.card_board),
            "card_hand": _sl(self.card_hand),
            "card_shop": _sl(self.card_shop),
            "leaf_count": len(self.leaf_slices),
        }


def _build_bc_obs_layout() -> BCObsLayout:
    board_slots = tuple(
        slice(O.SLICE_BOARD.start + i * O.MINION_F,
              O.SLICE_BOARD.start + (i + 1) * O.MINION_F)
        for i in range(O.N_BOARD))
    hand_slots = tuple(
        slice(O.SLICE_HAND.start + i * O.ITEM_F,
              O.SLICE_HAND.start + (i + 1) * O.ITEM_F)
        for i in range(O.N_HAND))
    shop_slots = tuple(
        slice(O.SLICE_SHOP.start + i * O.ITEM_F,
              O.SLICE_SHOP.start + (i + 1) * O.ITEM_F)
        for i in range(O.N_SHOP))
    leaves: List[slice] = [O.SLICE_GLOBAL]
    leaves.extend(board_slots)
    leaves.extend(hand_slots)
    leaves.extend(shop_slots)
    card_leaves: Tuple[slice, ...] = (
        O.SLICE_CARD_HERO, O.SLICE_CARD_BOARD,
        O.SLICE_CARD_HAND, O.SLICE_CARD_SHOP)
    return BCObsLayout(
        global_slice=O.SLICE_GLOBAL,
        board_slice=O.SLICE_BOARD,
        hand_slice=O.SLICE_HAND,
        shop_slice=O.SLICE_SHOP,
        board_slots=board_slots, hand_slots=hand_slots, shop_slots=shop_slots,
        card_hero=O.SLICE_CARD_HERO, card_board=O.SLICE_CARD_BOARD,
        card_hand=O.SLICE_CARD_HAND, card_shop=O.SLICE_CARD_SHOP,
        leaf_slices=tuple(leaves), card_leaf_slices=card_leaves)


BC_OBS_LAYOUT: BCObsLayout = _build_bc_obs_layout()


@dataclass
class BCObsBatch:
    """``bc_obs_batch`` 的输出（可直接喂给模型/BC CE）。"""

    features: np.ndarray        # float32[n, 3227]
    cards: np.ndarray           # int32[n, 124]
    feature_mask: np.ndarray    # bool[n, 3227]（True=该特征可信）
    card_mask: np.ndarray       # bool[n, 124]（True=该卡槽有已知卡）
    action_mask: np.ndarray     # bool[n, 245]（近似合法动作；含 target）
    action_index: np.ndarray    # int64[n]
    weights: np.ndarray         # float32[n]（MMR 权重）
    #: 稀有动作类别覆盖权重（默认全 1.0；在 class-balanced 之上再乘）。
    class_weight: np.ndarray    # float32[n]
    class_ids: np.ndarray       # int16[n]
    class_counts: np.ndarray    # int64[C]（全池类别计数）
    #: 每个动作位归属的类型 id（``-1`` = 不参与类型聚合；play_* 按手牌卡种细分；
    #: 启用 reposition 监督时 Move 段 = 第 10 类）。
    type_ids: np.ndarray        # int8/int16[n, 245]
    #: 卡牌身份标签（0-based；-1 = 不可用/不适用）。
    card_target: np.ndarray     # int32[n]
    #: 是否参与卡牌身份 CE（buy/play 四类且映射成功）。
    card_valid: np.ndarray      # bool[n]

    def __len__(self) -> int:
        return int(self.features.shape[0])


def _fill_minion_at(features: np.ndarray, mbase: int, card: int,
                    table: BCCardTable, fmask: np.ndarray,
                    *, golden: bool = False) -> None:
    """在 ``mbase``（``MINION_F`` 块起点）填随从静态字段。"""
    fmask[mbase + O.MINION_PRESENT] = True
    features[mbase + O.MINION_PRESENT] = 1.0
    for off, val in ((O.MINION_ATK, table.atk[card] / 10.0),
                     (O.MINION_HP, table.hp[card] / 10.0),
                     (O.MINION_MAX_HP, table.hp[card] / 10.0),
                     (O.MINION_TIER, table.tier[card] / 6.0),
                     (O.MINION_GOLDEN, 1.0 if golden else 0.0)):
        fmask[mbase + off] = True
        features[mbase + off] = float(val)
    kw = int(table.keywords[card])
    for j in range(len(O.KEYWORD_NAMES)):
        fmask[mbase + O.MINION_KEYWORDS + j] = True
        features[mbase + O.MINION_KEYWORDS + j] = float((kw >> j) & 1)
    races = int(table.races[card])
    for j in range(len(O.RACE_NAMES)):
        fmask[mbase + O.MINION_RACES + j] = True
        features[mbase + O.MINION_RACES + j] = float((races >> j) & 1)


def _fill_item(features: np.ndarray, fbase: int, card: int,
               table: BCCardTable, fmask: np.ndarray,
               *, cost: float = 0.0, golden: bool = False) -> None:
    """填一个 shop/hand item：随从走 minion 子块，法术走 spell 字段。"""
    kind = int(table.kind[card]) if 0 <= card < table.n_cards else 0
    features[fbase + O.ITEM_PRESENT] = 1.0
    fmask[fbase + O.ITEM_PRESENT] = True
    if kind == 2:
        features[fbase + O.ITEM_IS_MINION] = 0.0
        fmask[fbase + O.ITEM_IS_MINION] = True
        features[fbase + O.ITEM_COST] = float(cost) / 5.0
        fmask[fbase + O.ITEM_COST] = True
        # 法术：present=1，data 未知（保持 0/mask False），tier 来自卡表
        features[fbase + O.SPELL_PRESENT] = 1.0
        fmask[fbase + O.SPELL_PRESENT] = True
        features[fbase + O.SPELL_TIER] = float(table.tier[card]) / 6.0
        fmask[fbase + O.SPELL_TIER] = True
    else:
        features[fbase + O.ITEM_IS_MINION] = 1.0
        fmask[fbase + O.ITEM_IS_MINION] = True
        features[fbase + O.ITEM_COST] = float(cost) / 5.0
        fmask[fbase + O.ITEM_COST] = True
        _fill_minion_at(features, fbase + O.ITEM_MINION, card, table, fmask,
                        golden=golden)


def _place_board_slots(features: np.ndarray, fbase: int,
                       values: np.ndarray, present: np.ndarray,
                       table: BCCardTable, fmask: np.ndarray,
                       cards_out: np.ndarray, card_mask: np.ndarray,
                       card_slice: slice) -> None:
    for slot in range(len(values)):
        if not bool(present[slot]):
            continue
        card = int(values[slot])
        fb = int(fbase) + int(slot) * O.MINION_F
        _fill_minion_at(features, fb, card, table, fmask,
                        golden=bool(_GOLDEN_RE.search(table.ids[card] or "")))
        cards_out[card_slice.start + slot] = card
        card_mask[card_slice.start + slot] = True


def _place_slots(features: np.ndarray, fbase: int, fstride: int,
                 values: np.ndarray, present: np.ndarray,
                 table: BCCardTable, fmask: np.ndarray,
                 cards_out: np.ndarray, card_mask: np.ndarray,
                 card_slice: slice, *, hand: bool = False) -> None:
    for slot in range(len(values)):
        if not bool(present[slot]):
            continue
        card = int(values[slot])
        fb = int(fbase) + int(slot) * int(fstride)
        _fill_item(features, fb, card, table, fmask,
                   cost=0.0 if hand else float(table.cost[card]),
                   golden=bool(_GOLDEN_RE.search(table.ids[card] or "")))
        cards_out[card_slice.start + slot] = card
        card_mask[card_slice.start + slot] = True


def bc_type_ids(samples: BCSamples,
                indices: Optional[Any] = None) -> np.ndarray:
    """样本 + 观测手牌 -> ``int16[n, 245]`` 的类型归属（``-1`` = 不参与聚合）。

    类型数由 ``samples.action_types`` 决定：默认 9 类；当它含 ``"reposition"``
    （第 10 类，``--bc-include-reposition 1``）时，Move 段 196..244 整体归属
    ``reposition``（与 ``action_mask`` 里的合法换位候选取交集后做 log-sum-exp）。

    ``play_spell`` / ``play_minion`` 无法只靠动作下标区分，因此按**该样本观测到的
    手牌卡种**细分：手牌槽是法术 -> 只有 ``pos=0`` 的那个 play 动作属于
    ``play_spell``；是随从 -> 该槽 8 个 play 动作都属于 ``play_minion``。
    手牌卡种未知的动作保持 ``-1``（不参与聚合），但**真实动作**总是被强制写回
    其 ``action_type`` 对应类别（标签优先，保证类型 CE 的分母非空）。

    其余 7 类（end_turn / reroll / upgrade / hero_power / sell / buy_minion /
    buy_spell）来自 :data:`BC_STATIC_TYPE_IDS`，与样本无关。
    """
    n_total = len(samples) if indices is None else 0
    if indices is None:
        idx = np.arange(n_total, dtype=np.int64)
    else:
        idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    n = int(idx.size)
    types = tuple(getattr(samples, "action_types", DEFAULT_BC_ACTION_TYPES))
    class_map = {name: i for i, name in enumerate(types)}
    out = np.tile(BC_STATIC_TYPE_IDS.astype(np.int16), (n, 1))
    # 可选第 10 类：Move 段整体归属 reposition（关闭时 types 不含它 -> 不写，逐位不变）
    if BC_REPOSITION_TYPE in class_map:
        out[:, BC_MOVE_SLICE] = int(class_map[BC_REPOSITION_TYPE])
    table = samples.card_table
    play_spell_id = int(class_map.get("play_spell",
                                      BC_ACTION_CLASSES["play_spell"]))
    play_minion_id = int(class_map.get("play_minion",
                                       BC_ACTION_CLASSES["play_minion"]))
    for row, si in enumerate(idx):
        si = int(si)
        for slot in range(ACT.N_HAND):
            if not bool(samples.hand_present[si, slot]):
                continue
            card = int(samples.hand[si, slot])
            if not (0 <= card < table.n_cards):
                continue
            kind = int(table.kind[card])
            base = ACT.A_PLAY + int(slot) * ACT.N_POS
            if kind == 2:      # 法术：只有 pos=0 合法
                out[row, base] = play_spell_id
            elif kind == 1:    # 随从：8 个落位都属于 play_minion
                out[row, base:base + ACT.N_POS] = play_minion_id
        ai = int(samples.action_index[si])
        if 0 <= ai < N_ACTIONS:
            out[row, ai] = int(samples.action_class[si])
    return out


def bc_obs_batch(samples: BCSamples, layout: Optional[BCObsLayout] = None, *,
                 indices: Optional[Any] = None) -> BCObsBatch:
    """把 BC 样本编码成部分观测（``features`` / ``cards`` / 三个 mask）。

    - 已知槽位：global(turn/health/armor/gold/tier/board_len/hand_len)、棋盘 7、
      手牌 10、商店 8（含法术槽）、hero；
    - 未知槽位：float/card 全 0，``feature_mask`` / ``card_mask`` 对应位 False；
    - ``action_mask``：由部分观测可推断的候选动作（白名单动作族）+ 真实动作（保证合法），
      用于 BC 的 masked CE；**不是**引擎 legal_mask 的精确重建。启用 reposition
      监督（``samples.action_types`` 含 ``"reposition"``）时额外填入 196..244 的近似
      合法换位（棋盘长度内 ``from != to``），否则 Move 位保持历史行为。
    """
    lay = layout or BC_OBS_LAYOUT
    type_map = {name: i for i, name in enumerate(
        tuple(getattr(samples, "action_types", DEFAULT_BC_ACTION_TYPES)))}
    n_total = len(samples)
    if indices is None:
        idx = np.arange(n_total, dtype=np.int64)
    else:
        idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    n = int(idx.size)
    features = np.zeros((n, OBS_FLOATS), dtype=np.float32)
    cards = np.zeros((n, OBS_CARDS), dtype=np.int32)
    feature_mask = np.zeros((n, OBS_FLOATS), dtype=bool)
    card_mask = np.zeros((n, OBS_CARDS), dtype=bool)
    action_mask = np.zeros((n, N_ACTIONS), dtype=bool)
    table = samples.card_table

    for row, si in enumerate(idx):
        si = int(si)
        f = features[row]
        fm = feature_mask[row]
        # ── global（只填回放可见字段）──
        if bool(samples.turn_known[si]):
            f[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["turn"]] = \
                float(samples.turn[si]) / 20.0
            fm[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["turn"]] = True
        if bool(samples.health_known[si]):
            f[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["health"]] = \
                float(samples.health[si]) / 40.0
            fm[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["health"]] = True
        if bool(samples.armor_known[si]):
            f[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["armor"]] = \
                float(samples.armor[si]) / 20.0
            fm[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["armor"]] = True
        if bool(samples.gold_known[si]):
            f[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["gold"]] = \
                float(samples.gold[si]) / 10.0
            fm[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["gold"]] = True
        if bool(samples.tier_known[si]):
            f[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["tier"]] = \
                float(samples.tier[si]) / 6.0
            fm[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["tier"]] = True
        for field, val, known in (
                ("board_len", float(np.count_nonzero(samples.board_present[si])) / 7.0,
                 True),
                ("hand_len", float(np.count_nonzero(samples.hand_present[si])) / 10.0,
                 True),
                ("alive", 1.0, True), ("me_alive", 1.0, True)):
            j = O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX[field]
            f[j] = float(val)
            fm[j] = bool(known)

        # ── 棋盘 / 手牌 / 商店 ──
        _place_board_slots(f, O.SLICE_BOARD.start,
                           samples.board[si], samples.board_present[si], table, fm,
                           cards[row], card_mask[row], lay.card_board)
        _place_slots(f, O.SLICE_HAND.start, O.ITEM_F,
                     samples.hand[si], samples.hand_present[si], table, fm,
                     cards[row], card_mask[row], lay.card_hand, hand=True)
        _place_slots(f, O.SLICE_SHOP.start, O.ITEM_F,
                     samples.shop[si], samples.shop_present[si], table, fm,
                     cards[row], card_mask[row], lay.card_shop, hand=False)

        # hero（卡表下标+1；未知保持 0 / mask False）
        hero = int(samples.hero[si])
        if hero > 0:
            cards[row, lay.card_hero.start] = hero
            card_mask[row, lay.card_hero.start] = True

        # ── 近似动作掩码：白名单动作族中可推断的候选 ──
        am = action_mask[row]
        gold_known = bool(samples.gold_known[si])
        gold = int(samples.gold[si]) if gold_known else 0
        board_len = int(np.count_nonzero(samples.board_present[si]))
        am[O.A_END] = True
        am[O.A_UPGRADE] = (not bool(samples.tier_known[si])
                           or int(samples.tier[si]) < 6)
        am[O.A_HERO_POWER] = True
        # 刷新通常 1 金；只有明确 0 金才排除（价格可能有折扣，保守）
        am[O.A_REFRESH] = (not gold_known) or gold >= 1
        for slot in range(O.N_SHOP):
            if not bool(samples.shop_present[si, slot]):
                continue
            card = int(samples.shop[si, slot])
            # 金币已知时排除“基础价都买不起”的槽（实际价格可能有折扣，仅作近似）
            if gold_known and 0 <= card < table.n_cards \
                    and float(table.cost[card]) > float(gold):
                continue
            am[O.A_BUY + slot] = True
        for slot in range(O.N_BOARD):
            if bool(samples.board_present[si, slot]):
                am[O.A_SELL + slot] = True
        # 可选：Move 段（196..244）候选 = 引擎 ``legal_mask`` 的近似重建
        # （from/to 都在棋盘长度内且 from != to）。关闭 reposition 监督时不写，
        # 保证 action_mask 与历史行为逐位一致（Move 位全 False，除真实动作）。
        if BC_REPOSITION_TYPE in type_map:
            n_occupied = int(np.count_nonzero(samples.board_present[si]))
            n_move = min(n_occupied, int(ACT.N_BOARD))
            for src in range(n_move):
                for dst in range(n_move):
                    if src != dst:
                        am[ACT.A_MOVE + src * ACT.N_BOARD + dst] = True
        play_positions = max(1, min(O.N_POS, board_len + 1))
        for slot in range(O.N_HAND):
            if not bool(samples.hand_present[si, slot]):
                continue
            card = int(samples.hand[si, slot])
            is_spell = (0 <= card < table.n_cards
                        and int(table.kind[card]) == 2)
            if is_spell:
                am[O.A_PLAY + slot * O.N_POS] = True
            else:
                for pos in range(play_positions):
                    am[O.A_PLAY + slot * O.N_POS + pos] = True
        # 真实动作必须可算 CE（若近似掩码漏掉，至少把这个动作补上）
        ai = int(samples.action_index[si])
        if 0 <= ai < N_ACTIONS:
            am[ai] = True

    return BCObsBatch(
        features=features, cards=cards,
        feature_mask=feature_mask, card_mask=card_mask,
        action_mask=action_mask, action_index=np.asarray(
            samples.action_index[idx], dtype=np.int64),
        weights=np.asarray(samples.weight[idx], dtype=np.float32),
        class_weight=np.asarray(samples.class_weight[idx], dtype=np.float32),
        class_ids=np.asarray(samples.action_class[idx], dtype=np.int16),
        class_counts=np.asarray(samples.class_counts, dtype=np.int64),
        type_ids=bc_type_ids(samples, idx),
        card_target=np.asarray(samples.card_target[idx], dtype=np.int32),
        card_valid=np.asarray(samples.card_valid[idx], dtype=bool))


# ══════════════════════════════════════════════════════════════════════════
# 3. 损失
# ══════════════════════════════════════════════════════════════════════════
def _torch():
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("torch 不可用：BC 损失需要 `pip install torch`") from exc
    return torch


def bc_class_balance_weights(class_ids: Any, class_counts: Any = None) -> np.ndarray:
    """动作类别频率倒数并归一（各类别权重均值 = 1）。

    ``w_c = (1 / count_c) / mean_{c: count_c>0}(1 / count_c)``；缺失类别=0。
    该归一化保持损失量级与未加权 CE 可比，同时让每个动作类别总权重近似相等。
    """
    ids = np.asarray(class_ids, dtype=np.int64).reshape(-1)
    if ids.size == 0:
        return np.zeros(0, dtype=np.float64)
    if class_counts is None:
        counts = np.bincount(ids).astype(np.float64)
    else:
        counts = np.asarray(class_counts, dtype=np.float64).reshape(-1)
    if counts.size == 0:
        return np.ones(ids.size, dtype=np.float64)
    max_id = int(ids.max()) if ids.size else -1
    if max_id >= counts.size:
        # 容错：补齐到最大类别（不可见类别 count=0）
        counts = np.pad(counts, (0, max_id + 1 - counts.size))
    inv = np.zeros_like(counts, dtype=np.float64)
    pos = counts > 0
    if not bool(pos.any()):
        return np.ones(ids.size, dtype=np.float64)
    inv[pos] = 1.0 / counts[pos]
    mean_inv = float(inv[pos].mean())
    if mean_inv <= 0.0:
        return np.ones(ids.size, dtype=np.float64)
    class_w = inv / mean_inv
    return class_w[ids]


def bc_ce_loss(logits: Any, target_action: Any, weights: Any = None,
               mask: Any = None, class_ids: Any = None,
               class_counts: Any = None, class_weight: Any = None):
    """class-balanced + MMR 加权的交叉熵（torch 标量；惰性导入 torch）。

    参数
    ----
    logits : ``[B, 245]``（调用方应已把非法动作填成 ``-1e30``）
    target_action : ``[B]`` 真实动作下标
    weights : ``[B]`` MMR 权重（None = 1）
    mask : ``[B]`` bool/0-1 样本 mask；**只对 True 的样本求均值**
    class_ids : ``[B]`` 动作类别 id（None = 不做 class-balanced）
    class_counts : ``[C]`` 全池类别计数（None = 用当前 batch 计数）
    class_weight : ``[B]`` 稀有动作类别覆盖权重（None = 1；在 class-balanced 之上再乘）

    所有权重全 0 / mask 全 False 时返回 0（不产生 NaN，且保留计算图）。
    """
    torch = _torch()
    F = torch.nn.functional
    if not torch.is_tensor(logits):
        logits = torch.as_tensor(logits)
    if not torch.is_tensor(target_action):
        target_action = torch.as_tensor(target_action)
    target = target_action.to(device=logits.device, dtype=torch.long).reshape(-1)
    per = F.cross_entropy(logits.float(), target, reduction="none")
    w = torch.ones_like(per)
    if weights is not None:
        wt = weights if torch.is_tensor(weights) else torch.as_tensor(weights)
        w = w * wt.to(device=per.device, dtype=per.dtype).reshape(-1)
    if class_ids is not None:
        ci = class_ids if torch.is_tensor(class_ids) else torch.as_tensor(class_ids)
        ci = ci.to(device=per.device, dtype=torch.long).reshape(-1)
        if class_counts is None:
            cc_np = np.bincount(ci.detach().cpu().numpy().astype(np.int64))
        else:
            cc_np = (class_counts.detach().cpu().numpy()
                     if torch.is_tensor(class_counts) else np.asarray(class_counts))
        cw_np = bc_class_balance_weights(ci.detach().cpu().numpy(), cc_np)
        cw = torch.as_tensor(cw_np, device=per.device, dtype=per.dtype)
        w = w * cw
    if class_weight is not None:
        cwt = (class_weight if torch.is_tensor(class_weight)
               else torch.as_tensor(class_weight))
        w = w * cwt.to(device=per.device, dtype=per.dtype).reshape(-1)
    if mask is not None:
        mt = mask if torch.is_tensor(mask) else torch.as_tensor(mask)
        w = w * mt.to(device=per.device, dtype=per.dtype).reshape(-1)
    w = w.clamp_min(0.0)
    denom = w.sum()
    if float(denom.detach().cpu()) <= 0.0:
        return logits.float().sum() * 0.0
    return (per * w).sum() / denom


#: 某类型在当前样本上没有任何候选动作时，类型 logits 的填充值（避免 -inf）。
BC_EMPTY_TYPE_LOGIT = -1e30


def bc_type_logits(policy_logits: Any, type_ids: Any, action_mask: Any = None,
                   n_types: int = N_BC_TYPES):
    """245 维动作 logits -> ``n_types`` 类**聚合** logits（log-sum-exp，数值稳定）。

    对每个类型 ``c``：

    ``L_c = logsumexp_{a: type_ids[a]==c 且 legal(a)} logits[a]``

    即“先选类型、再在该类型的候选动作里任选”的边际概率 ``p(c)=Σ_{a∈c} p(a)``
    对应的 log 概率。空类型（无候选）填 :data:`BC_EMPTY_TYPE_LOGIT`，不会产生
    ``-inf``/NaN；调用方应保证 target 类型至少有一个候选（``bc_type_ids`` 会把
    真实动作强制归入其 ``action_type``）。

    ``n_types`` 默认 9（历史行为）；启用 reposition 监督时传 10
    （:data:`N_BC_TYPES_WITH_REPOSITION`），Move 段 196..244 就是第 10 类。

    ``policy_logits`` ``[B,245]``；``type_ids`` ``[B,245]``（``-1`` 忽略）；
    ``action_mask`` ``[B,245]`` bool（None = 全部参与）。
    """
    torch = _torch()
    logits = policy_logits.float()
    tids = (type_ids if torch.is_tensor(type_ids)
            else torch.as_tensor(type_ids))
    tids = tids.to(device=logits.device, dtype=torch.long).reshape(
        logits.shape[0], -1)
    if tids.shape != logits.shape:
        raise ValueError(
            f"type_ids 形状 {tuple(tids.shape)} != policy_logits {tuple(logits.shape)}")
    am = None
    if action_mask is not None:
        am = (action_mask if torch.is_tensor(action_mask)
              else torch.as_tensor(action_mask))
        am = am.to(device=logits.device, dtype=torch.bool).reshape(
            logits.shape[0], -1)
    cols = []
    for c in range(int(n_types)):
        sel = (tids == int(c))
        if am is not None:
            sel = sel & am
        z = logits.masked_fill(~sel, float("-inf"))
        lse = torch.logsumexp(z, dim=-1)
        # 空类型 -> 有限哨兵（CE 的 log_softmax 仍稳定；不会 NaN）
        lse = torch.where(torch.isfinite(lse), lse,
                          torch.full_like(lse, float(BC_EMPTY_TYPE_LOGIT)))
        cols.append(lse)
    return torch.stack(cols, dim=-1)


def bc_card_ce_loss(card_logits: Any, card_target: Any, weights: Any = None,
                    mask: Any = None):
    """卡牌身份交叉熵（3983 类；只在 ``mask`` 为 True 的 buy/play 样本上平均）。

    ``card_target`` 里的 ``-1`` 表示“本样本没有卡牌身份标签”（非 buy/play 或
    ``card_id`` 映射失败），在 CE 前替换成 0 并用 mask 排除——因此不会因为
    ``cross_entropy`` 的 target 越界报错，也不会稀释分母。

    与 :func:`bc_ce_loss` 不同，这里**不做** class-balanced（3983 类频率倒数在
    小 batch 上噪声过大）；只用 MMR 权重。
    """
    torch = _torch()
    F = torch.nn.functional
    logits = card_logits.float()
    tgt = (card_target if torch.is_tensor(card_target)
           else torch.as_tensor(card_target)).to(
        device=logits.device, dtype=torch.long).reshape(-1)
    if tgt.numel() != logits.shape[0]:
        raise ValueError(
            f"card_target 长度 {tgt.numel()} != card_logits 行数 {logits.shape[0]}")
    valid = tgt >= 0
    if mask is not None:
        mt = (mask if torch.is_tensor(mask) else torch.as_tensor(mask))
        valid = valid & mt.to(device=logits.device, dtype=torch.bool).reshape(-1)
    safe = torch.where(valid, tgt, torch.zeros_like(tgt))
    per = F.cross_entropy(logits, safe, reduction="none")
    w = valid.to(per.dtype)
    if weights is not None:
        wt = (weights if torch.is_tensor(weights) else torch.as_tensor(weights))
        w = w * wt.to(device=per.device, dtype=per.dtype).reshape(-1)
    w = w.clamp_min(0.0)
    denom = w.sum()
    if float(denom.detach().cpu()) <= 0.0:
        return logits.sum() * 0.0
    return (per * w).sum() / denom


def bc_hier_loss(policy_logits: Any, type_ids: Any, target_class: Any, *,
                 action_mask: Any = None, card_logits: Any = None,
                 card_target: Any = None, card_valid: Any = None,
                 weights: Any = None, class_counts: Any = None,
                 class_weight: Any = None,
                 type_weight: float = DEFAULT_BC_TYPE_WEIGHT,
                 card_weight: float = DEFAULT_BC_CARD_WEIGHT,
                 n_types: Optional[int] = None) -> Dict[str, Any]:
    """分层 BC 损失：``w_type*CE_type + w_card*CE_card``（torch 标量字典）。

    参数
    ----
    policy_logits : ``[B,245]`` 主策略头 logits（同一 forward 的输出）
    type_ids : ``[B,245]`` 动作 -> 类型归属（-1 忽略；9 或 10 类）
    target_class : ``[B]`` 真实 ``action_type`` 的类别 id（0..8；启用 reposition 时 0..9）
    action_mask : ``[B,245]`` 合法/候选动作（类型聚合只在这些动作上取 log-sum-exp）
    card_logits : ``[B,3983]`` 卡牌身份头输出（None 或 ``card_weight<=0`` 时不算）
    card_target : ``[B]`` 卡牌标签（0..3982；-1 = 无标签）
    card_valid : ``[B]`` bool（buy/play 且映射成功）
    weights : ``[B]`` 样本权重（MMR；类型层还叠加 class-balanced）
    class_counts : ``[C]`` 全池类型计数（class-balanced；C = 9 或 10）
    class_weight : ``[B]`` 稀有动作类别权重覆盖（类型层在 class-balanced 之上再乘）
    n_types : 类型数；None = :data:`N_BC_TYPES`（9，历史行为）。
        ``type_ids`` / ``target_class`` / ``class_counts`` 用 10 类时传 10。

    返回 ``{"loss", "type_loss", "card_loss", "type_logits"}``；所有项都保留
    计算图。全空/全 0 时返回 0（不 NaN）。
    """
    tw = max(0.0, float(type_weight))
    cw = max(0.0, float(card_weight))
    n_cls = int(N_BC_TYPES if n_types is None else n_types)
    type_logits = bc_type_logits(policy_logits, type_ids,
                                 action_mask=action_mask, n_types=n_cls)
    type_loss = bc_ce_loss(type_logits, target_class, weights=weights, mask=None,
                           class_ids=target_class, class_counts=class_counts,
                           class_weight=class_weight)
    if card_logits is not None and cw > 0.0 and card_target is not None:
        card_loss = bc_card_ce_loss(card_logits, card_target, weights=weights,
                                    mask=card_valid)
    else:
        card_loss = policy_logits.float().sum() * 0.0
    return {
        "loss": tw * type_loss + cw * card_loss,
        "type_loss": type_loss,
        "card_loss": card_loss,
        "type_logits": type_logits,
    }


def parse_bc_coef_ramp(spec: str) -> RampPoints:
    """与 ``seq_aux.parse_coef_ramp`` 完全相同语法的 BC ramp（直接复用实现）。"""
    return parse_coef_ramp(spec)
