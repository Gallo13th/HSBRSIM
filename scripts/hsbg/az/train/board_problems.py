"""场面题（board problems）：在**自对弈关键局面**上出题，用人类参考动作分布 + 短程
战团强度标签做辅助监督（``docs/RESEARCH_PLAN_V2.md`` §4.1 / ``docs/BOARD_PROBLEMS.md``）。

**为什么不是 BC。** BC 预训练失败的根因是「人类回放的状态分布 ≠ 自对弈状态分布」
（``docs/BC_PRETRAIN.md`` §9.4）。本模块只从**当前策略自己的轨迹**里取关键局面
（每回合起点 + 决策分叉点），人类数据仅作「标准解的来源之一」：按 ``(turn, tier)``
匹配 Firestone 动作分布 top-k，并要求候选动作在**当前局面的合法掩码**内。

**默认关闭。** ``problem_bc_coef=0`` 且 ``strength_aux_coef=0`` 时训练入口既不导入本
模块（``hsbg.az.train.ppo`` 里是惰性导入）、也不加载 ``problems.jsonl``、不消耗 RNG、
不改 records/stats/checkpoint，动作序列与旧版逐位一致。

组成部分：

1. **观测编解码** ``encode_obs`` / ``decode_obs``：观测 = features(f32/f16) + cards +
   合法动作下标（比 ``state_json`` 小且与训练输入同口径，可逐位复现）；
2. **题目池** :class:`BoardProblemPool` / :func:`load_problem_pool`：稀疏参考动作
   top-k + 强度/等级标签；两个**池开关**（默认关闭、逐位等价）：
   ``--problem-min-strength-delta``（只留 t+3 归一化强度增量 ≥ 阈值的题）与
   ``--problem-turn-weight``（按 ``turn`` 给 soft-CE 加权，权重 0 = 剔除该 turn）；
   过滤报告（池大小/按 delta 丢/按 turn 丢）进训练 history；
3. **损失** :func:`problem_bc_soft_ce`（soft-label CE）、:func:`strength_aux_loss`
   （t+3 强度**增量**的 log1p 回归 + tier+1 二分类）、:func:`fit_strength_head`
   （在题目池上离线拟合冻结的线性探针）；
4. **参考解匹配** :class:`ReferenceTable` / :func:`match_reference_actions`：从
   Firestone ``bc_samples`` 建分布，按 MMR 阶梯（10k+/8k+/6k+）与 ``(turn,tier)``
   匹配，缺失时逐级退化并记录；
5. **Move 安全** :func:`apply_move_guard`：题目生成（rollout 采样）与监督（参考解
   候选）都套用 ``move_guard`` 规则，标准解里不会出现「连按换位」；
6. **采集器** :func:`collect_problems`：用当前权重按训练分布 rollout（人类战团 5 席
   p0.9 + 镜像 2 席 p0.2 + move-guard），记录关键局面与 t+3 真实强度。
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from hsbg.env import obs_std as O
from .common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from .move_guard import (DEFAULT_MOVE_CAP, DEFAULT_MOVE_REPEAT_LIMIT, MOVE_HI,
                         MOVE_LO, decode_move, encode_move, is_move)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: 题目 schema 版本（进 manifest / 单测 round-trip）。
PROBLEM_SCHEMA_VERSION = "board_problem_v1"
DEFAULT_PROBLEM_PATH = os.path.join(_REPO_ROOT, "data", "board_problems",
                                    "problems.jsonl")
DEFAULT_PROBLEM_META = os.path.join(_REPO_ROOT, "data", "board_problems",
                                    "problems.meta.json")
DEFAULT_BC_SAMPLES = os.path.join(_REPO_ROOT, "data", "firestone_bc",
                                  "bc_samples.jsonl.gz")
#: 原始 Firestone 动作流（按 tier 分桶统计「人类高频购买」表；§14 参考解修正）。
DEFAULT_FIRESTONE_ACTIONS = os.path.join(
    _REPO_ROOT, "data", "firestone_replays", "firestone_recent_actions.jsonl.gz")

#: 短程标签视界（t+3 回合）。
DEFAULT_HORIZON = 3

#: 关键局面标签。
TAG_TURN_START = "turn_start"
TAG_UPGRADE_READY = "upgrade_ready"
TAG_TRIPLE_READY = "triple_ready"
TAG_CORE_CARD = "core_card"
FORK_TAGS: Tuple[str, ...] = (TAG_UPGRADE_READY, TAG_TRIPLE_READY, TAG_CORE_CARD)
ALL_TAGS: Tuple[str, ...] = (TAG_TURN_START,) + FORK_TAGS

#: 参考解动作类型白名单（= BC 的 9 类；``reposition`` 默认**排除**，见模块说明）。
REF_TYPES: Tuple[str, ...] = (
    "sell", "reroll", "buy_minion", "buy_spell", "play_spell",
    "play_minion", "upgrade", "hero_power", "end_turn")
REF_TYPE_INDEX: Dict[str, int] = {name: i for i, name in enumerate(REF_TYPES)}

#: 动作段常量（与 ``hsbg.env.action_space_std`` 一致；这里内联避免引擎依赖）。
A_END = 0
A_REFRESH = 1
A_UPGRADE = 3
A_HERO_POWER = 4
A_BUY = 8
A_SELL = 16
A_PLAY = 46
N_SHOP = O.N_SHOP
N_HAND = O.N_HAND
N_BOARD = O.N_BOARD

#: MMR 阶梯（参考解优先用高分段；不够支撑再退化）。
DEFAULT_REF_FLOORS: Tuple[int, ...] = (10000, 8000, 6000)


# ══════════════════════════════════════════════════════════════════════════
# 0. 从观测反推「可读状态」（与训练输入同口径，不额外读 player_json）
# ══════════════════════════════════════════════════════════════════════════
#: 观测里 atk/hp 的缩放（``obs = raw / 10``；见 ``hsbg/env/obs_std.py`` 与实测）。
OBS_STRENGTH_SCALE = 10.0


def _g(glob: Any, name: str) -> float:
    return float(glob[O.GLOBAL_FIELD_INDEX[name]])


def tier_from_features(features: Any) -> int:
    """obs features -> tavern tier（obs 内 tier 除以 6）。"""
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    return int(round(_g(f[O.SLICE_GLOBAL], "tier") * O.GLOBAL_FIELD_SCALE["tier"]))


def gold_from_features(features: Any) -> int:
    """obs features -> 当前金币（obs 内 gold 除以 10）。"""
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    return int(round(_g(f[O.SLICE_GLOBAL], "gold") * O.GLOBAL_FIELD_SCALE["gold"]))


def turn_from_features(features: Any) -> int:
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    return int(round(_g(f[O.SLICE_GLOBAL], "turn") * O.GLOBAL_FIELD_SCALE["turn"]))


def board_strength_from_features(features: Any) -> int:
    """obs features -> 己方战团总身材 ``Σ(atk+hp)``。

    观测里随从 atk/hp 已除以 :data:`OBS_STRENGTH_SCALE`（实测 10），只统计
    ``MINION_PRESENT`` 的槽位；与 ``quality_monitor`` 的 ``Σ(atk+hp)`` 同口径。
    """
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    board = f[O.SLICE_BOARD].reshape(N_BOARD, O.MINION_F)
    present = board[:, O.MINION_PRESENT] > 0.5
    if not bool(present.any()):
        return 0
    total = float((board[present, O.MINION_ATK]
                   + board[present, O.MINION_HP]).sum())
    return int(round(total * OBS_STRENGTH_SCALE))


def shop_phase_from_features(features: Any) -> int:
    """酒馆当前是否还有牌（1=有）。

    人类动作分布必须按这个维度对齐：``end_turn`` 行大量出现在酒馆刷空/进入战斗之后，
    只按 ``(turn,tier,gold)`` 匹配会把「回合已结束」的样本当成回合起点的标准解。
    """
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    blk = f[O.SLICE_SHOP].reshape(N_SHOP, O.ITEM_F)
    return 1 if bool((blk[:, O.ITEM_PRESENT] > 0.5).any()) else 0


def board_card_ids(cards: Any) -> np.ndarray:
    """obs cards -> 棋盘 7 槽的卡牌下标（0 = 空槽）。"""
    c = np.asarray(cards, dtype=np.int64).reshape(-1)
    return c[O.SLICE_CARD_BOARD].astype(np.int64)


def shop_card_ids(cards: Any) -> np.ndarray:
    c = np.asarray(cards, dtype=np.int64).reshape(-1)
    return c[O.SLICE_CARD_SHOP].astype(np.int64)


def hand_card_ids(cards: Any) -> np.ndarray:
    c = np.asarray(cards, dtype=np.int64).reshape(-1)
    return c[O.SLICE_CARD_HAND].astype(np.int64)


def _slot_is_minion(features: np.ndarray, kind: str, i: int) -> bool:
    """观测里的 item 块/board 块是否标记该槽为随从（法术槽返回 False）。"""
    if kind == "board":
        blk = features[O.SLICE_BOARD].reshape(N_BOARD, O.MINION_F)
        return bool(blk[i, O.MINION_PRESENT] > 0.5)
    sl = O.SLICE_SHOP if kind == "shop" else O.SLICE_HAND
    blk = features[sl].reshape(N_SHOP if kind == "shop" else N_HAND, O.ITEM_F)
    if not bool(blk[i, O.ITEM_PRESENT] > 0.5):
        return False
    return bool(blk[i, O.ITEM_IS_MINION] > 0.5)


def fork_tags(mask: Any, features: Any, cards: Any, *,
              core_min_tier: int = 3) -> List[str]:
    """一个决策点是否是「分叉点」，返回标签列表（空 = 普通局面）。

    - ``upgrade_ready``：引擎判定**当前可升本**（``mask[3]`` 为合法动作，已含金币约束）；
    - ``triple_ready``：手牌+棋盘里某张牌已有 ≥2 张，且酒馆里能买到最后一张（三连）；
    - ``core_card``：棋盘上有 ``tier >= core_min_tier``（默认 3）的「核心随从」。
    """
    m = np.asarray(mask, dtype=bool).reshape(-1)
    tags: List[str] = []
    if bool(m[A_UPGRADE]):
        tags.append(TAG_UPGRADE_READY)
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    shop = shop_card_ids(cards)
    hand = hand_card_ids(cards)
    board = board_card_ids(cards)
    counts: Dict[int, int] = {}
    for cid in list(hand) + list(board):
        cid = int(cid)
        if cid > 0:
            counts[cid] = counts.get(cid, 0) + 1
    if counts:
        for cid in set(int(x) for x in shop if int(x) > 0):
            if counts.get(cid, 0) >= 2:
                tags.append(TAG_TRIPLE_READY)
                break
    tbl = _card_tier_table()
    if tbl is not None:
        tiers = [int(tbl[int(c)]) for c in board
                 if 0 < int(c) < tbl.shape[0]]
        if tiers and max(tiers) >= int(core_min_tier):
            tags.append(TAG_CORE_CARD)
    return tags


_CARD_TIER_CACHE: Optional[np.ndarray] = None


def _card_tier_table() -> Optional[np.ndarray]:
    """卡牌下标 -> tier 表（惰性、失败返回 None，不阻塞出题）。"""
    global _CARD_TIER_CACHE
    if _CARD_TIER_CACHE is None:
        try:
            from .bc_aux import load_bc_card_table
            _CARD_TIER_CACHE = np.asarray(load_bc_card_table().tier,
                                          dtype=np.float32)
        except Exception:  # noqa: BLE001 - 缺卡表时跳过 core_card 标签
            return None
    return _CARD_TIER_CACHE


# ══════════════════════════════════════════════════════════════════════════
# 1. 观测编解码（可复现、与训练输入同口径）
# ══════════════════════════════════════════════════════════════════════════
def obs_sha256(features: Any, cards: Any, mask: Any) -> str:
    """观测指纹（同 seed 出题可复现的断言依据）。"""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(features, dtype=np.float32).tobytes())
    h.update(np.ascontiguousarray(cards, dtype=np.int32).tobytes())
    h.update(np.ascontiguousarray(mask, dtype=bool).tobytes())
    return h.hexdigest()


def encode_obs(features: Any, cards: Any, mask: Any, *,
               dtype: str = "f32") -> Dict[str, Any]:
    """观测 -> JSON 可存字典：``features`` 走 base64、``legal`` 存合法动作下标。"""
    f = np.ascontiguousarray(features, dtype=np.float32).reshape(-1)
    if f.size != OBS_FLOATS:
        raise ValueError(f"features 长度 {f.size} != {OBS_FLOATS}")
    c = np.ascontiguousarray(cards, dtype=np.int32).reshape(-1)
    if c.size != OBS_CARDS:
        raise ValueError(f"cards 长度 {c.size} != {OBS_CARDS}")
    m = np.ascontiguousarray(mask, dtype=bool).reshape(-1)
    if m.size != N_ACTIONS:
        raise ValueError(f"mask 长度 {m.size} != {N_ACTIONS}")
    dt = str(dtype or "f32").strip().lower()
    if dt in ("f16", "float16", "half"):
        buf = f.astype(np.float16).tobytes()
        dt = "f16"
    else:
        buf = f.astype(np.float32).tobytes()
        dt = "f32"
    return {
        "dtype": dt,
        "features_b64": base64.b64encode(buf).decode("ascii"),
        "cards": [int(x) for x in c],
        "legal": [int(x) for x in np.flatnonzero(m)],
        "sha256": obs_sha256(f, c, m),
    }


def decode_obs(obs: Mapping[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``encode_obs`` 的逆：返回 ``(features f32, cards int32, mask bool)``。"""
    dt = str(obs.get("dtype", "f32")).strip().lower()
    raw = base64.b64decode(str(obs["features_b64"]))
    arr = np.frombuffer(raw, dtype=np.float16 if dt == "f16" else np.float32)
    f = np.asarray(arr, dtype=np.float32).reshape(-1).copy()
    if f.size != OBS_FLOATS:
        raise ValueError(f"解码 features 长度 {f.size} != {OBS_FLOATS}")
    c = np.asarray(obs.get("cards") or [], dtype=np.int32).reshape(-1).copy()
    if c.size != OBS_CARDS:
        raise ValueError(f"解码 cards 长度 {c.size} != {OBS_CARDS}")
    m = np.zeros(N_ACTIONS, dtype=bool)
    for a in obs.get("legal") or []:
        ai = int(a)
        if 0 <= ai < N_ACTIONS:
            m[ai] = True
    return f, c, m


# ══════════════════════════════════════════════════════════════════════════
# 2. Move 安全：候选动作 -> 守卫后的候选（题目生成/监督共用同一规则）
# ══════════════════════════════════════════════════════════════════════════
#: 参考解可覆盖的动作下标集合（9 类白名单；不含 choose/activate/magnetize/move）。
SUPERVISABLE_ACTIONS: Tuple[int, ...] = (
    (A_END, A_REFRESH, A_UPGRADE, A_HERO_POWER, A_HERO_POWER + 1)
    + tuple(range(A_BUY, A_SELL + N_BOARD))
    + tuple(range(A_PLAY, A_PLAY + 8 * 8 + 8)))


def supervisable_legal_actions(mask: Any) -> np.ndarray:
    """合法动作里**参考解可以覆盖**的下标（choose 等无参考类别的不算）。"""
    m = np.asarray(mask, dtype=bool).reshape(-1)
    out = [a for a in SUPERVISABLE_ACTIONS
           if 0 <= a < m.size and bool(m[a])]
    # play 段覆盖 46..125（手牌 10 × 落位 8）
    out.extend(a for a in range(A_PLAY, min(126, m.size)) if bool(m[a]))
    return np.asarray(sorted(set(int(a) for a in out)), dtype=np.int64)


def apply_move_guard(actions: Sequence[int], *, mask: Any = None,
                     move_last: int = -1, move_counts: Mapping[int, int]
                     = None, move_n: int = 0,
                     cap: int = DEFAULT_MOVE_CAP,
                     repeat_limit: int = DEFAULT_MOVE_REPEAT_LIMIT) -> List[int]:
    """按 ``move_guard`` 的三条规则过滤候选动作（顺序无关、不改输入）。

    规则与 :class:`hsbg.az.train.move_guard.MoveGuard` 完全一致：

    1. **逆换位**：上一步是 ``Move(a→b)`` 时去掉 ``Move(b→a)``；
    2. **重复上限**：同一 ``(from,to)`` 本回合已出现 ``>= repeat_limit`` 次后去掉；
    3. **每回合上限**：本回合已选 ``>= cap`` 次换位后去掉全部 49 个换位动作。

    非 Move 动作永远保留（守卫只约束换位族），因此本题的**标准解不会包含连按换位**。
    """
    counts = {int(k): int(v) for k, v in dict(move_counts or {}).items()}
    cap_hit = int(move_n) >= int(cap)
    inverse = -1
    last = int(move_last)
    if is_move(last):
        src, dst = decode_move(last)
        if src != dst:
            inverse = encode_move(dst, src)
    m = None if mask is None else np.asarray(mask, dtype=bool).reshape(-1)
    out: List[int] = []
    for a in actions:
        ai = int(a)
        if m is not None and not (0 <= ai < m.size and bool(m[ai])):
            continue
        if is_move(ai):
            if cap_hit or ai == inverse or counts.get(ai, 0) >= int(repeat_limit):
                continue
        out.append(ai)
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3. 参考解：Firestone 动作分布（按 MMR 阶梯 + turn/tier 匹配）
# ══════════════════════════════════════════════════════════════════════════
def _open_text(path: str):
    if str(path).endswith(".gz"):
        import gzip
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def _counts_add(dst: Dict[Any, Dict[Tuple[str, str], float]],
                key: Any, atype: str, card: str, w: float) -> None:
    bucket = dst.get(key)
    if bucket is None:
        bucket = {}
        dst[key] = bucket
    k = (atype, card)
    bucket[k] = bucket.get(k, 0.0) + float(w)


@dataclass
class ReferenceTable:
    """人类参考动作分布（Firestone ``bc_samples``）按 MMR 阶梯分组的多级计数表。

    ``tables[floor]`` 是 key -> ``{(action_type, card_id): weight}`` 的字典组：
    ``by_turn_tier_gold[(shop,turn,tier,gold)]`` / ``by_turn_tier[(shop,turn,tier)]`` /
    ``by_tier[(shop,tier)]`` / ``by_turn[(shop,turn)]`` / ``all[shop]``。

    **每个 key 都以「酒馆是否还有牌」（``shop_phase``）为最外层维度**。原因（实测）：
    Firestone 的 ``end_turn`` 行经常出现在酒馆已刷空/进入战斗之后（``shop_cards=[]``，
    ``gold`` 字段也是陈旧的），若只按 ``(turn,tier,gold)`` 匹配，会把这类「回合已结束」
    的行当成「回合起点的标准解」，让 60% 的题 top-1 变成 EndTurn。按酒馆状态对齐后，
    标准解才是「同一决策阶段人类会做什么」。
    """

    floors: Tuple[int, ...]
    tables: Dict[int, Dict[str, Dict[Any, Dict[Tuple[str, str], float]]]]
    rows: Dict[int, int]
    path: str = ""
    card_ids: Optional[Tuple[str, ...]] = None

    def n(self, floor: int) -> int:
        return int(self.rows.get(int(floor), 0))

    def to_json(self) -> Dict[str, Any]:
        """摘要（不落全表；用于 meta/stats）。"""
        return {"path": self.path, "floors": list(self.floors),
                "rows": {str(k): int(v) for k, v in self.rows.items()},
                "levels": list((self.tables.get(int(self.floors[-1])) or {}).keys())
                if self.floors else []}


def build_reference_table(path: str = DEFAULT_BC_SAMPLES, *,
                          floors: Sequence[int] = DEFAULT_REF_FLOORS,
                          limit: Optional[int] = None) -> ReferenceTable:
    """扫 ``bc_samples.jsonl(.gz)`` 建参考动作分布（9 类白名单，排除 reposition）。

    每行按 ``mmr >= floor`` 归入各阶梯；权重 = 1（每条人类动作等权）。缺失
    ``action_type`` 不在白名单 / ``action_index`` 越界的行跳过（与 BC 同口径）。
    """
    fl = tuple(sorted({int(x) for x in floors}, reverse=True))
    tables: Dict[int, Dict[str, Dict[Any, Dict[Tuple[str, str], float]]]] = {
        f: {"by_turn_tier_gold": {}, "by_turn_tier": {}, "by_tier": {},
            "by_turn": {}, "all": {}}
        for f in fl}
    rows = {f: 0 for f in fl}
    cap = int(limit) if limit is not None and int(limit) >= 0 else None
    n_read = 0
    with _open_text(path) as fh:
        for line in fh:
            if cap is not None and n_read >= cap:
                break
            line = line.strip()
            if not line:
                continue
            n_read += 1
            try:
                r = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(r, dict):
                continue
            atype = str(r.get("action_type") or "")
            if atype not in REF_TYPE_INDEX:
                continue
            try:
                mmr = int(r.get("mmr"))
            except (TypeError, ValueError):
                continue
            if mmr < min(fl):
                continue
            card = str(r.get("card_id") or "")
            shop = 1 if (r.get("shop_cards") or []) else 0
            turn = r.get("turn")
            tier = r.get("tier")
            gold = r.get("gold")
            for floor in fl:
                if mmr < floor:
                    continue
                rows[floor] += 1
                t = tables[floor]
                _counts_add(t["all"], shop, atype, card, 1.0)
                if turn is not None:
                    _counts_add(t["by_turn"], (shop, int(turn)),
                                atype, card, 1.0)
                if tier is not None:
                    _counts_add(t["by_tier"], (shop, int(tier)),
                                atype, card, 1.0)
                if turn is not None and tier is not None:
                    _counts_add(t["by_turn_tier"], (shop, int(turn), int(tier)),
                                atype, card, 1.0)
                    if gold is not None:
                        _counts_add(t["by_turn_tier_gold"],
                                    (shop, int(turn), int(tier),
                                     min(10, max(0, int(gold)))),
                                    atype, card, 1.0)
    ids: Optional[Tuple[str, ...]] = None
    try:
        from .bc_aux import load_bc_card_table
        ids = tuple(load_bc_card_table().ids)
    except Exception:  # noqa: BLE001 - 卡表只是加速，缺失时退化为「按类型均分」
        ids = None
    return ReferenceTable(floors=fl, tables=tables, rows=rows,
                          path=str(path), card_ids=ids)


#: 匹配时尝试的层级顺序（越靠前越具体；**层级优先于 MMR 阶梯**：先用最具体的层级在
#: 任一分段里找够支撑的桶，再考虑更粗的层级）。
REF_LEVELS: Tuple[str, ...] = ("turn_tier_gold", "turn_tier", "tier", "turn", "all")

#: ``level`` -> (表内键, key 生成函数) 的映射（供 :func:`match_reference_actions`）。
_REF_LEVEL_TABLES: Dict[str, str] = {
    "turn_tier_gold": "by_turn_tier_gold", "turn_tier": "by_turn_tier",
    "tier": "by_tier", "turn": "by_turn", "all": "all"}


def _bucket_stats(bucket: Optional[Mapping[Tuple[str, str], float]]
                  ) -> Tuple[float, Dict[str, float]]:
    """``{(type,card): w}`` -> ``(总权重, {type: 权重})``。"""
    if not bucket:
        return 0.0, {}
    total = float(sum(bucket.values()))
    per_type: Dict[str, float] = {}
    for (atype, _card), w in bucket.items():
        per_type[atype] = per_type.get(atype, 0.0) + float(w)
    return total, per_type


def match_reference_actions(features: Any, cards: Any, mask: Any,
                            table: ReferenceTable, *, top_k: int = 8,
                            min_support: int = 40,
                            exclude_move: bool = True,
                            move_last: int = -1,
                            move_counts: Optional[Mapping[int, int]] = None,
                            move_n: int = 0, cap: int = DEFAULT_MOVE_CAP,
                            repeat_limit: int = DEFAULT_MOVE_REPEAT_LIMIT,
                            levels: Optional[Sequence[str]] = None,
                            late_ref: Optional["LateRefConfig"] = None,
                            buy_table: Optional["HumanBuyTable"] = None,
                            card_ids: Optional[Sequence[str]] = None,
                            ) -> Dict[str, Any]:
    """在**当前局面**上把人类动作分布映射成合法动作的 top-k 软标签。

    算法（逐级退化，全部记录进返回值，便于统计匹配率）：

    1. 选 MMR 阶梯（默认 10k+ → 8k+ → 6k+）与层级（``turn_tier`` → ``tier`` →
       ``turn`` → ``all``）：第一个支撑数 ``>= min_support`` 的组合胜出；
    2. 类型分布 ``p(type) = Σ_card p(type,card)``；
    3. 卡牌型动作（buy/play/sell）优先落到**同卡 id** 的槽位；同卡质量之外的部分
       按类型在合法槽位上均分（避免「人类买了另一张牌」时给错槽位硬标签）；
    4. 过滤：合法掩码 + Move 守卫（``apply_move_guard``）；剩下质量重新归一；
    5. 取 top-k（权重和为 1），返回 ``actions/weights/level/floor/support/...``。

    ``exclude_move=True``（默认）时 Move 族完全不作为标准解（``reposition`` 也不在
    ``REF_TYPES`` 里）；``False`` 时仍会经过 Move 守卫过滤。

    ``levels``（默认 ``None`` = :data:`REF_LEVELS` 全阶梯）：只允许这些层级。后期
    参考解修正（``--late-ref-policy fixed``）传 ``("turn_tier_gold",)``，即**不再向
    更粗层级退化**——匹配不到就是「无严格参考解」，由调用方显式记录，而不是偷偷
    退化成 ``(turn,tier)`` 桶。
    """
    m = np.asarray(mask, dtype=bool).reshape(-1)
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    c = np.asarray(cards, dtype=np.int32).reshape(-1)
    turn = turn_from_features(f)
    tier = tier_from_features(f)
    gold = min(10, max(0, gold_from_features(f)))
    shop_phase = shop_phase_from_features(f)
    if not bool(m.any()):
        return {"actions": [], "weights": [], "matched": False,
                "level": "none", "floor": 0, "support": 0, "mass_legal": 0.0,
                "reason": "empty_mask"}
    level = "none"
    floor = 0
    bucket: Optional[Dict[Tuple[str, str], float]] = None
    support = 0
    levels_seq = tuple(levels) if levels else REF_LEVELS
    # 层级优先、MMR 阶梯其次：先用最具体的层级在任一分段里找够支撑的桶。
    for lv in levels_seq:
        for fl in table.floors:
            t = table.tables.get(int(fl)) or {}
            src = t.get(_REF_LEVEL_TABLES[lv]) or {}
            key = ({"turn_tier_gold": (shop_phase, turn, tier, gold),
                    "turn_tier": (shop_phase, turn, tier),
                    "tier": (shop_phase, tier),
                    "turn": (shop_phase, turn),
                    "all": shop_phase}[lv])
            cand = src.get(key)
            tot, _ = _bucket_stats(cand)
            if tot >= float(min_support):
                bucket, level, floor, support = cand, lv, int(fl), int(tot)
                break
        if bucket is not None:
            break
    if bucket is None:
        return {"actions": [], "weights": [], "matched": False, "level": "none",
                "floor": 0, "support": 0, "mass_legal": 0.0,
                "reason": "no_support"}
    total, per_type = _bucket_stats(bucket)
    # ── 候选动作权重 ────────────────────────────────────────────────────
    cand: Dict[int, float] = {}

    def _add(action: int, w: float) -> None:
        if w <= 0.0:
            return
        ai = int(action)
        if not (0 <= ai < N_ACTIONS and bool(m[ai])):
            return
        cand[ai] = cand.get(ai, 0.0) + float(w)

    # 标量动作
    if per_type.get("end_turn", 0.0) > 0.0:
        _add(A_END, per_type["end_turn"])
    if per_type.get("reroll", 0.0) > 0.0:
        _add(A_REFRESH, per_type["reroll"])
    if per_type.get("upgrade", 0.0) > 0.0:
        _add(A_UPGRADE, per_type["upgrade"])
    hp = per_type.get("hero_power", 0.0)
    if hp > 0.0:
        legal_hp = [A_HERO_POWER + k for k in range(2)
                    if bool(m[A_HERO_POWER + k])]
        for a in legal_hp:
            _add(a, hp / float(len(legal_hp)))
    ids = table.card_ids
    card_of_id = ({cid: i for i, cid in enumerate(ids)} if ids else {})

    def _card_slot_weights(atype: str, slot_card_ids: Sequence[int],
                           action_of_slot) -> None:
        """卡牌型动作：同卡优先 + 余量在合法槽位上均分。"""
        p_type = per_type.get(atype, 0.0)
        if p_type <= 0.0:
            return
        slots = [(i, int(cid)) for i, cid in enumerate(slot_card_ids)
                 if int(cid) > 0 and action_of_slot(i) is not None
                 and bool(m[int(action_of_slot(i))])]
        if not slots:
            return
        matched = 0.0
        per_slot: Dict[int, float] = {}
        for i, cid in slots:
            sid = ids[int(cid)] if ids and 0 <= int(cid) < len(ids) else ""
            w = float(bucket.get((atype, sid), 0.0)) if sid else 0.0
            if w > 0.0:
                per_slot[i] = per_slot.get(i, 0.0) + w
                matched += w
        residual = max(0.0, p_type - matched)
        share = residual / float(len(slots))
        for i, _cid in slots:
            _add(action_of_slot(i), per_slot.get(i, 0.0) + share)

    # buy：商店 8 槽（0..6 随从，7 法术槽）
    shop_ids = shop_card_ids(c).tolist()

    def _buy_action(i: int) -> Optional[int]:
        a = A_BUY + i
        if i < N_SHOP - 1:
            want = per_type.get("buy_minion", 0.0)
            if not _slot_is_minion(f, "shop", i):
                return None
            return a if want > 0 else None
        return a if per_type.get("buy_spell", 0.0) > 0 else None

    _card_slot_weights("buy_minion", shop_ids, _buy_action)
    if per_type.get("buy_spell", 0.0) > 0 and bool(m[A_BUY + N_SHOP - 1]):
        _add(A_BUY + N_SHOP - 1, per_type["buy_spell"])
    # sell：棋盘 7 槽
    board_ids = board_card_ids(c).tolist()
    _card_slot_weights("sell", board_ids,
                       lambda j: A_SELL + j if bool(m[A_SELL + j]) else None)
    # play：手牌 10 槽 × 合法落位 8 种
    hand_ids = hand_card_ids(c).tolist()

    def _play_actions(h: int, atype: str) -> Optional[int]:
        if not (0 <= h < N_HAND) or int(hand_ids[h]) <= 0:
            return None
        is_min = _slot_is_minion(f, "hand", h)
        want = atype == "play_minion"
        if bool(is_min) != bool(want):
            return None
        return A_PLAY + h * 8  # 占位；具体落位在 _card_slot_weights 外单独处理

    for atype in ("play_minion", "play_spell"):
        p_type = per_type.get(atype, 0.0)
        if p_type <= 0.0:
            continue
        slots = [h for h in range(N_HAND) if _play_actions(h, atype) is not None]
        if not slots:
            continue
        matched = 0.0
        per_slot: Dict[int, float] = {}
        for h in slots:
            sid = (ids[int(hand_ids[h])] if ids and int(hand_ids[h]) < len(ids)
                   else "")
            w = float(bucket.get((atype, sid), 0.0)) if sid else 0.0
            if w > 0.0:
                per_slot[h] = w
                matched += w
        residual = max(0.0, p_type - matched)
        share = residual / float(len(slots))
        for h in slots:
            pos = [A_PLAY + h * 8 + k for k in range(8)
                   if bool(m[A_PLAY + h * 8 + k])]
            if not pos:
                continue
            w = (per_slot.get(h, 0.0) + share) / float(len(pos))
            for a in pos:
                _add(a, w)
    # ── Move 守卫 + top-k ───────────────────────────────────────────────
    # ── 后期参考解修正（默认 late_ref=None：完全不改动）──────────────────
    # 必须在 **top-k 截断之前** 作用于完整候选分布：否则 reroll 封顶/买牌加权只能
    # 在被截断的 8 个动作里重归一，被丢掉的买牌质量再也回不来，cap 也就名存实亡。
    late_audit: Dict[str, Any] = {}
    if late_ref is not None and late_ref.applies(turn) and cand:
        cand, late_audit = reweight_reference_candidates(
            cand, f, c, turn=int(turn), cfg=late_ref, buy_table=buy_table,
            card_ids=(card_ids if card_ids is not None else table.card_ids))
    acts = list(cand.keys())
    if exclude_move:
        acts = [a for a in acts if not is_move(a)]
    else:
        acts = apply_move_guard(acts, mask=m, move_last=move_last,
                                move_counts=move_counts, move_n=move_n,
                                cap=cap, repeat_limit=repeat_limit)
    if not acts:
        return {"actions": [], "weights": [], "matched": False, "level": level,
                "floor": floor, "support": support, "mass_legal": 0.0,
                "reason": "no_legal_ref"}
    mass = float(sum(cand[a] for a in acts))
    top = sorted(acts, key=lambda a: (-cand[a], a))[:max(1, int(top_k))]
    wsum = float(sum(cand[a] for a in top))
    if wsum <= 0.0:
        return {"actions": [], "weights": [], "matched": False, "level": level,
                "floor": floor, "support": support, "mass_legal": 0.0,
                "reason": "zero_weight"}
    weights = [float(cand[a]) / wsum for a in top]
    if late_audit:
        # reroll 上限作用在**训练真正看到的 top-k 分布**上（候选层的 reroll 占比
        # 会被 slot 摊薄，若在候选层判定 cap，截断重归一后又可能回到 cap 以上）；
        # 买牌加权仍必须在候选层做（否则买牌质量在截断时已被丢掉）。
        kinds_top = [ref_action_kind(a) for a in top]
        weights, capped_final = _cap_reroll_weights(
            kinds_top, weights, float(late_ref.reroll_cap))
        order2 = sorted(range(len(top)), key=lambda i: (-float(weights[i]), int(top[i])))
        top = [int(top[i]) for i in order2]
        weights = [float(weights[i]) for i in order2]
        keep = [i for i, w in enumerate(weights) if float(w) > 1e-12]
        if keep and len(keep) < len(weights):
            top = [int(top[i]) for i in keep]
            weights = [float(weights[i]) for i in keep]
        kinds_top = [ref_action_kind(a) for a in top]
        late_audit.update({
            "capped_topk": bool(capped_final),
            "reroll_topk_after": _kind_mass(kinds_top, weights, "reroll"),
            "buy_topk_after": _kind_mass(kinds_top, weights, "buy"),
            "play_topk_after": _kind_mass(kinds_top, weights, "play"),
            "top1_kind_after": kinds_top[0] if kinds_top else "other",
        })
    out = {"actions": [int(a) for a in top], "weights": weights,
           "matched": True, "level": level, "floor": floor,
           "support": support, "mass_legal": mass / max(total, 1e-9),
           "reason": "ok"}
    if late_audit:
        out["late_ref"] = dict(late_audit)
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3.5 题目池开关：turn 权重 / 强度增量过滤 / turn 段（**默认关闭**）
# ══════════════════════════════════════════════════════════════════════════
#: 「后期」判据（``is_late_turn``）：阶段强度表（``runs/plots/strength_stages.md``）
#: 显示 t12 之后我们的强度比几乎不涨（t12 0.13 / t15 0.03，真实 t15 p50 26,516 vs
#: 我们 ~821），所以 ``turn >= 10`` 作为「要重点补的后期回合」的一致口径。
LATE_TURN_MIN = 10

#: ``--problem-turn-weight`` 里未列出的 turn 的权重。
DEFAULT_TURN_WEIGHT = 1.0


# ══════════════════════════════════════════════════════════════════════════
# 3b. 后期参考解修正（``--late-ref-policy fixed``）
# ══════════════════════════════════════════════════════════════════════════
# 为什么需要（docs/BOARD_PROBLEMS.md §13.5）：t13–t15 的参考 top-1 有 65–77% 是
# ``reroll``、``buy`` 质量 < 8%。turn 加权等于教「刷酒馆」。这里提供三个**只在
# ``fixed`` 模式、只对 t >= turn_min`` 生效的修正，全部有显式记录、默认关闭：
#
# 1. 严格层级：只接受 ``turn_tier_gold``（同时匹配 turn/tier/gold），不再向更粗层级
#    退化；匹配不到 = 无严格参考解（显式记账，不偷偷降级）；
# 2. reroll 上限：该状态参考分布里 reroll 总质量 <= ``reroll_cap``，其余按质量重归一；
# 3. 买牌加权：buy/play 的卡若出现在「该 tier 人类高频购买」表里，权重 ×``buy_boost``。
#
# 顺序固定为 **先买牌加权、再 reroll 上限、再归一**，报告里同时给 before/after。

#: 有「卡牌身份」的动作类型（买牌加权只作用在这几类上）。
REF_CARD_KINDS: Tuple[str, ...] = ("buy", "play", "sell")

#: 报告里的动作族（``ref_action_kind`` 的取值域）。
REF_KINDS: Tuple[str, ...] = ("end_turn", "reroll", "upgrade", "hero_power",
                              "buy", "sell", "play", "other")


def ref_action_kind(action: Any) -> str:
    """动作下标 -> 动作族（与 :data:`REF_TYPES` 对齐；其它段归 ``other``）。"""
    a = int(action)
    if a == A_END:
        return "end_turn"
    if a == A_REFRESH:
        return "reroll"
    if a == A_UPGRADE:
        return "upgrade"
    if A_HERO_POWER <= a < A_HERO_POWER + 2:
        return "hero_power"
    if A_BUY <= a < A_BUY + N_SHOP:
        return "buy"
    if A_SELL <= a < A_SELL + N_BOARD:
        return "sell"
    if A_PLAY <= a < A_PLAY + N_HAND * 8:
        return "play"
    return "other"


_BC_CARD_IDS_CACHE: Optional[Tuple[str, ...]] = None


def _bc_card_ids() -> Optional[Tuple[str, ...]]:
    """bc 卡表 ``ids``（卡牌下标 -> 卡 id；惰性、失败返回 None）。"""
    global _BC_CARD_IDS_CACHE
    if _BC_CARD_IDS_CACHE is None:
        try:
            from .bc_aux import load_bc_card_table
            _BC_CARD_IDS_CACHE = tuple(load_bc_card_table().ids)
        except Exception:  # noqa: BLE001 - 卡表只是加权依据，缺失时退化为不加权
            return None
    return _BC_CARD_IDS_CACHE


def ref_action_card(features: Any, cards: Any, action: Any,
                    card_ids: Optional[Sequence[str]] = None
                    ) -> Tuple[str, int]:
    """参考动作 -> ``(卡 id, 卡牌下标)``；非卡牌型动作返回 ``("", 0)``。"""
    kind = ref_action_kind(action)
    c = np.asarray(cards, dtype=np.int64).reshape(-1)
    cid = 0
    if kind == "buy":
        i = int(action) - A_BUY
        if 0 <= i < N_SHOP:
            cid = int(shop_card_ids(c)[i])
    elif kind == "sell":
        j = int(action) - A_SELL
        if 0 <= j < N_BOARD:
            cid = int(board_card_ids(c)[j])
    elif kind == "play":
        h = (int(action) - A_PLAY) // 8
        if 0 <= h < N_HAND:
            cid = int(hand_card_ids(c)[h])
    ids = card_ids if card_ids is not None else _bc_card_ids()
    sid = ids[cid] if (ids is not None and 0 <= cid < len(ids)) else ""
    return str(sid or ""), int(cid)


@dataclass
class HumanBuyTable:
    """按 tier 分桶的人类购买频次表 -> 「该 tier 的高频购买卡」集合。

    来源 ``data/firestone_replays/firestone_recent_actions.jsonl.gz``（原始动作流，
    含 ``tier``/``card_id``）。只统计 ``buy_minion`` / ``buy_spell``（真正的「购买」
    动作；``play_*`` 是打出手牌，不是购买）。高频判据：该卡在本 tier 的购买次数
    占比 ``>= min_freq``（默认 0.01，即 1%）。
    """

    path: str = ""
    counts: Dict[int, Dict[str, float]] = field(default_factory=dict)
    totals: Dict[int, float] = field(default_factory=dict)
    high: Dict[int, Tuple[str, ...]] = field(default_factory=dict)
    min_freq: float = 0.01
    rows: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)

    def freq(self, tier: int, card_id: str) -> float:
        """该卡在 ``tier`` 桶里的购买占比（0 = 未出现）。"""
        t = int(tier)
        tot = float(self.totals.get(t, 0.0))
        if tot <= 0.0:
            return 0.0
        return float(self.counts.get(t, {}).get(str(card_id), 0.0)) / tot

    def is_high(self, tier: int, card_id: str) -> bool:
        """``card_id`` 是否属于该 tier 的「高频购买」表。"""
        return str(card_id) in set(self.high.get(int(tier), ()))

    def to_json(self) -> Dict[str, Any]:
        """摘要（不落全表）：tier -> (购买动作数, 高频卡数)。"""
        return {
            "path": self.path, "rows": int(self.rows),
            "min_freq": float(self.min_freq),
            "tiers": {str(t): {"buys": int(self.totals.get(t, 0.0)),
                               "cards": int(len(self.counts.get(t, {}))),
                               "high_cards": int(len(self.high.get(t, ())))}
                      for t in sorted(self.counts)},
            "skipped": dict(self.skipped),
        }


def build_human_buy_table(path: str = DEFAULT_FIRESTONE_ACTIONS, *,
                          min_freq: float = 0.01,
                          actions: Sequence[str] = ("buy_minion", "buy_spell"),
                          ) -> HumanBuyTable:
    """扫 Firestone 原始动作流，建 ``tier -> {card: count}`` 购买频次表。"""
    mf = float(min_freq)
    if not math.isfinite(mf) or not (0.0 <= mf <= 1.0):
        raise ValueError(f"min_freq 必须有限且 0..1，得到 {min_freq!r}")
    allow = {str(a) for a in actions}
    counts: Dict[int, Dict[str, float]] = {}
    totals: Dict[int, float] = {}
    skipped = {"type": 0, "no_card": 0, "bad_tier": 0, "bad_row": 0}
    n = 0
    with _open_text(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except (ValueError, TypeError):
                skipped["bad_row"] += 1
                continue
            if not isinstance(r, dict):
                skipped["bad_row"] += 1
                continue
            if str(r.get("action_type") or "") not in allow:
                skipped["type"] += 1
                continue
            card = str(r.get("card_id") or "")
            if not card:
                skipped["no_card"] += 1
                continue
            try:
                tier = int(r.get("tier"))
            except (TypeError, ValueError):
                skipped["bad_tier"] += 1
                continue
            n += 1
            bucket = counts.setdefault(int(tier), {})
            bucket[card] = bucket.get(card, 0.0) + 1.0
            totals[int(tier)] = totals.get(int(tier), 0.0) + 1.0
    high: Dict[int, Tuple[str, ...]] = {}
    for tier, bucket in counts.items():
        tot = float(totals.get(tier, 0.0))
        high[int(tier)] = tuple(sorted(
            cid for cid, cnt in bucket.items() if tot > 0 and cnt / tot >= mf))
    return HumanBuyTable(path=str(path), counts=counts, totals=totals, high=high,
                         min_freq=mf, rows=int(n), skipped=skipped)


@dataclass
class LateRefConfig:
    """后期参考解修正配置（``--late-ref-policy``；默认 ``current`` = 逐位等价）。

    - ``policy="current"``：完全走原有匹配/加权，不新增任何字段；
    - ``policy="fixed"``：``turn >= turn_min`` 的题只接受 ``strict_levels`` 层级、
      reroll 质量封顶、buy/play 按人类高频购买表加权；
    - ``turn_min`` 默认 :data:`LATE_TURN_MIN`（10），与 turn 加权口径一致。
    """

    policy: str = "current"
    turn_min: int = LATE_TURN_MIN
    reroll_cap: float = 0.25
    buy_boost: float = 2.0
    buy_min_freq: float = 0.01
    strict_levels: Tuple[str, ...] = ("turn_tier_gold",)

    def __post_init__(self) -> None:
        p = str(self.policy or "current").strip().lower()
        if p not in ("current", "fixed"):
            raise ValueError(f"late_ref_policy 必须是 current|fixed，得到 {self.policy!r}")
        self.policy = p
        self.turn_min = int(self.turn_min)
        self.reroll_cap = float(self.reroll_cap)
        self.buy_boost = float(self.buy_boost)
        self.buy_min_freq = float(self.buy_min_freq)
        if not math.isfinite(self.reroll_cap) or not (0.0 <= self.reroll_cap <= 1.0):
            raise ValueError(f"ref_reroll_cap 必须有限且 0..1，得到 {self.reroll_cap!r}")
        if not math.isfinite(self.buy_boost) or self.buy_boost < 1.0:
            raise ValueError(f"ref_buy_boost 必须是 >= 1 的有限数，得到 {self.buy_boost!r}")
        lv = tuple(str(x) for x in (self.strict_levels or ()))
        if any(x not in REF_LEVELS for x in lv):
            raise ValueError(f"strict_levels 只能取 {REF_LEVELS}，得到 {lv!r}")
        self.strict_levels = lv or ("turn_tier_gold",)

    def enabled(self) -> bool:
        """是否启用修正（``fixed``）。"""
        return str(self.policy) == "fixed"

    def applies(self, turn: int) -> bool:
        """该 turn 是否落在修正范围（``fixed`` 且 ``turn >= turn_min``）。"""
        return bool(self.enabled()) and int(turn) >= int(self.turn_min)

    def to_json(self) -> Dict[str, Any]:
        return {"policy": str(self.policy), "turn_min": int(self.turn_min),
                "reroll_cap": float(self.reroll_cap),
                "buy_boost": float(self.buy_boost),
                "buy_min_freq": float(self.buy_min_freq),
                "strict_levels": list(self.strict_levels)}


def _kind_mass(kinds: Sequence[str], weights: Any, kind: str) -> float:
    """``weights`` 中动作族 == ``kind`` 的质量和。"""
    w = np.asarray(weights, dtype=np.float64).reshape(-1)
    return float(sum(float(wi) for k, wi in zip(kinds, w) if k == kind))


def reweight_reference_candidates(cand: Mapping[int, float], features: Any,
                                  cards: Any, *, turn: int,
                                  cfg: LateRefConfig,
                                  buy_table: Optional[HumanBuyTable] = None,
                                  card_ids: Optional[Sequence[str]] = None,
                                  ) -> Tuple[Dict[int, float], Dict[str, Any]]:
    """在**完整合法候选分布**上给 buy/play 加权（``--ref-buy-boost``）。

    为什么必须作用在完整候选（而不是先截 top-k 再改权重）：后期 t14/t15 的合法候选
    有几十个（reroll + 10×8 个 play 落位 + 7 个 sell + 8 个 buy），单类质量被摊薄；
    若先截 top-8 再重归一，buy 的质量基本已被丢掉。实测 t14 严格层桶里 buy 本身有
    ~11.6% 质量，先截断后掉到 <1%。因此买牌加权在 top-k 之前做；reroll 上限则由
    :func:`match_reference_actions` 在**截断后的最终分布**上做（保证训练看到的
    ref 里 reroll 质量确实 <= cap）。

    返回 ``(new_cand, audit)``；``audit`` 的 before/after 都是**候选层**质量占比。
    """
    tier = tier_from_features(features)
    kinds = {int(a): ref_action_kind(a) for a in cand}
    w = {int(a): float(v) for a, v in cand.items() if float(v) > 0.0}
    if not w:
        return {}, {"policy": str(cfg.policy), "applied": False, "reason": "empty"}
    tot = float(sum(w.values()))
    order_before = sorted(w, key=lambda a: (-w[a], a))
    before = {k: sum(v for a, v in w.items() if kinds[a] == k) / tot
              for k in ("reroll", "buy", "play", "sell")}
    boosted: List[int] = []
    if buy_table is not None and float(cfg.buy_boost) > 1.0:
        for a in list(w):
            if kinds[a] not in ("buy", "play"):
                continue
            sid, _cid = ref_action_card(features, cards, a, card_ids)
            if sid and buy_table.is_high(tier, sid):
                w[a] *= float(cfg.buy_boost)
                boosted.append(int(a))
    tot = float(sum(w.values())) or 1.0
    after = {k: sum(v for a, v in w.items() if kinds[a] == k) / tot
             for k in ("reroll", "buy", "play", "sell")}
    audit = {
        "policy": str(cfg.policy), "applied": True, "tier": int(tier),
        "candidates": int(len(w)), "boosted": int(len(boosted)),
        "boosted_actions": boosted[:8],
        "reroll_before": before["reroll"], "reroll_after": after["reroll"],
        "buy_before": before["buy"], "buy_after": after["buy"],
        "play_before": before["play"], "play_after": after["play"],
        "sell_before": before["sell"], "sell_after": after["sell"],
        "top1_kind_before": kinds[order_before[0]] if order_before else "other",
    }
    return w, audit


def _cap_reroll_weights(kinds: Sequence[str], weights: Sequence[float],
                        cap: float) -> Tuple[List[float], bool]:
    """把 top-k 参考分布里的 reroll 质量封顶到 ``cap``，其余按质量重归一。"""
    w = np.asarray(weights, dtype=np.float64).reshape(-1)
    c = float(cap)
    r = _kind_mass(kinds, w, "reroll")
    if not (0.0 <= c < 1.0) or r <= c + 1e-12 or r >= 1.0 - 1e-12:
        return [float(x) for x in w], False
    scale_r = c / r
    scale_o = (1.0 - c) / (1.0 - r)
    w = np.asarray([float(x) * (scale_r if k == "reroll" else scale_o)
                    for x, k in zip(w, kinds)], dtype=np.float64)
    tot = float(w.sum())
    if not math.isfinite(tot) or tot <= 0.0:
        return [float(x) for x in np.asarray(weights, dtype=np.float64)], False
    return [float(x) for x in (w / tot)], True


def rewrite_problem_rows(rows: Sequence[Mapping[str, Any]], table: ReferenceTable,
                         *, cfg: Optional[LateRefConfig] = None,
                         buy_table: Optional[HumanBuyTable] = None,
                         top_k: int = 8, min_support: int = 40,
                         card_ids: Optional[Sequence[str]] = None,
                         keep_ref_before: bool = True,
                         progress: bool = False
                         ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """对**已有题池**重算参考解（不重跑 rollout）：``fixed`` 时走严格层 + 重加权。

    ``cfg=None`` 或 ``policy="current"`` 时等价于「用同一张表重新匹配」——与当初出题
    同样的 ``top_k``/``min_support``/默认层级，因此结果与旧 ``ref`` 一致（可当回归）。
    返回 ``(new_rows, report)``；``report`` 记账严格层匹配失败、修正生效行数与原因。
    """
    out: List[Dict[str, Any]] = []
    n = 0
    n_strict = 0
    report: Dict[str, Any] = {
        "schema": "board_late_ref_rewrite_v1",
        "rows": int(len(rows)),
        "late_rows": 0, "late_strict_matched": 0, "late_strict_unmatched": 0,
        "strict_unmatched_by_turn": {}, "applied": 0,
        "unmatched_by_turn": {}, "reasons": {},
    }
    for i, r in enumerate(rows):
        f, c, m = decode_obs(r.get("obs") or {})
        turn = int(r.get("turn") or turn_from_features(f))
        use_strict = bool(cfg is not None and cfg.applies(turn))
        old = dict(r.get("ref") or {})
        ref = match_reference_actions(
            f, c, m, table, top_k=int(top_k), min_support=int(min_support),
            levels=(cfg.strict_levels if use_strict else None),
            late_ref=(cfg if use_strict else None), buy_table=buy_table,
            card_ids=card_ids)
        if use_strict:
            n_strict += 1
            report["late_rows"] += 1
            if bool(ref.get("matched")):
                report["late_strict_matched"] += 1
            else:
                report["late_strict_unmatched"] += 1
                key = str(int(turn))
                d = report["strict_unmatched_by_turn"]
                d[key] = int(d.get(key, 0)) + 1
        if not bool(ref.get("matched")):
            key = str(int(turn))
            d = report["unmatched_by_turn"]
            d[key] = int(d.get(key, 0)) + 1
            report["reasons"][str(ref.get("reason", ""))] = int(
                report["reasons"].get(str(ref.get("reason", "")), 0)) + 1
        audit = dict(ref.get("late_ref") or {})
        if use_strict and not audit:
            audit = {"policy": str(cfg.policy), "applied": False,
                     "reason": str(ref.get("reason", "")),
                     "strict_levels": list(cfg.strict_levels)}
        new_ref = {k: v for k, v in ref.items() if k != "late_ref"}
        row = dict(r)
        if keep_ref_before:
            row["ref_before"] = {
                "actions": [int(a) for a in (old.get("actions") or [])],
                "weights": [float(x) for x in (old.get("weights") or [])],
                "matched": bool(old.get("matched")),
                "level": str(old.get("level") or "none"),
                "floor": int(old.get("floor") or 0),
                "support": int(old.get("support") or 0),
                "mass_legal": float(old.get("mass_legal") or 0.0),
            }
        row["ref"] = dict(new_ref, reason=str(new_ref.get("reason", "")))
        if bool(audit.get("applied")):
            report["applied"] += 1
            row["late_ref"] = audit
        elif cfg is not None and cfg.applies(turn):
            row["late_ref"] = audit
        out.append(row)
        n += 1
        if progress and (i + 1) % 1500 == 0:
            print(f"[late-ref] {i + 1}/{len(rows)}", flush=True)
    report["rows"] = int(n)
    return out, report


def ref_type_distribution(rows: Sequence[Mapping[str, Any]], *,
                          turns: Optional[Sequence[int]] = None
                          ) -> Dict[str, Any]:
    """参考解的**动作族分布**（按 turn）：质量占比 + top-1 类型 + 层级计数。

    只看 ``ref.matched`` 的题；``mass_share`` 是逐行归一后的质量在所有行上的平均
    （等价于「每题一票」的混合分布），``top1_share`` 是 argmax 类型占比。
    """
    want = ({int(t) for t in turns} if turns is not None else None)
    cells: Dict[str, Dict[str, Any]] = {}

    def _cell(key: str) -> Dict[str, Any]:
        if key not in cells:
            cells[key] = {
                "n": 0, "matched": 0,
                "mass": {k: 0.0 for k in REF_KINDS},
                "top1": {k: 0 for k in REF_KINDS},
                "reroll_mass_sum": 0.0, "buy_mass_sum": 0.0,
                "play_mass_sum": 0.0, "reroll_top1": 0, "buy_top1": 0,
                "level": {},
            }
        return cells[key]

    for r in rows:
        t = int(r.get("turn") or 0)
        if want is not None and t not in want:
            continue
        ref = r.get("ref") or {}
        key = str(t)
        cell = _cell(key)
        cell["n"] += 1
        lv = str(ref.get("level") or "none")
        cell["level"][lv] = int(cell["level"].get(lv, 0)) + 1
        if not bool(ref.get("matched")):
            continue
        acts = [int(a) for a in (ref.get("actions") or [])]
        wts = [float(x) for x in (ref.get("weights") or [])]
        if not acts or len(acts) != len(wts):
            continue
        s = float(sum(wts))
        if not math.isfinite(s) or s <= 0.0:
            continue
        wts = [x / s for x in wts]
        kinds = [ref_action_kind(a) for a in acts]
        cell["matched"] += 1
        for k, w in zip(kinds, wts):
            cell["mass"][k] = float(cell["mass"].get(k, 0.0)) + float(w)
        top = kinds[0]
        cell["top1"][top] = int(cell["top1"].get(top, 0)) + 1
        rr = _kind_mass(kinds, wts, "reroll")
        bu = _kind_mass(kinds, wts, "buy")
        pl = _kind_mass(kinds, wts, "play")
        cell["reroll_mass_sum"] += rr
        cell["buy_mass_sum"] += bu
        cell["play_mass_sum"] += pl
        cell["reroll_top1"] += int(top == "reroll")
        cell["buy_top1"] += int(top == "buy")
    out: Dict[str, Any] = {}
    for key, cell in cells.items():
        m = int(cell["matched"])
        n = int(cell["n"])
        mass_sum = float(sum(cell["mass"].values()))
        share = ({k: (v / mass_sum if mass_sum > 0 else 0.0)
                  for k, v in cell["mass"].items()})
        top1_sum = int(sum(cell["top1"].values()))
        top1_share = ({k: (v / top1_sum if top1_sum > 0 else 0.0)
                       for k, v in cell["top1"].items()})
        out[key] = {
            "n": n, "matched": m,
            "match_rate": (float(m) / n if n else 0.0),
            "mass_share": {k: round(float(v), 6) for k, v in share.items()},
            "top1": {k: int(v) for k, v in cell["top1"].items() if int(v) > 0},
            "top1_share": {k: round(float(v), 6)
                           for k, v in top1_share.items() if float(v) > 0},
            "mean_reroll_mass": round(float(cell["reroll_mass_sum"]) / m, 6) if m else 0.0,
            "mean_buy_mass": round(float(cell["buy_mass_sum"]) / m, 6) if m else 0.0,
            "mean_play_mass": round(float(cell["play_mass_sum"]) / m, 6) if m else 0.0,
            "reroll_top1_share": round(float(cell["reroll_top1"]) / m, 6) if m else 0.0,
            "buy_top1_share": round(float(cell["buy_top1"]) / m, 6) if m else 0.0,
            "level": dict(sorted(cell["level"].items())),
        }
    return {"turns": out,
            "overall": _merge_cells(list(out.values()))}


def _merge_cells(cells: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """把逐 turn 的 cell 汇总（仅用于报告展示；质量按行平均，不按题数加权）。"""
    n = int(sum(int(c.get("n", 0)) for c in cells))
    m = int(sum(int(c.get("matched", 0)) for c in cells))
    if m <= 0:
        return {"n": n, "matched": 0}
    mass = {k: 0.0 for k in REF_KINDS}
    top1 = {k: 0 for k in REF_KINDS}
    for c in cells:
        msum = float(sum((c.get("mass_share") or {}).values()))
        for k in mass:
            mass[k] += float((c.get("mass_share") or {}).get(k, 0.0)) * msum
        for k, v in (c.get("top1") or {}).items():
            top1[k] = int(top1.get(k, 0)) + int(v)
    tot = float(sum(mass.values())) or 1.0
    tsum = int(sum(top1.values())) or 1
    return {"n": n, "matched": m,
            "mass_share": {k: round(float(v) / tot, 6) for k, v in mass.items()},
            "top1_share": {k: round(float(v) / tsum, 6)
                           for k, v in top1.items() if int(v) > 0}}


def parse_turn_weights(spec: Any) -> Dict[int, float]:
    """解析 ``--problem-turn-weight`` 的 ``"10:2,12:3,14:4,15:4"`` 语法。

    - 每项 ``turn:weight``，逗号分隔；``turn`` 必须是非负整数、``weight`` 必须
      有限且 ``>= 0``；未列出的 turn 权重 :data:`DEFAULT_TURN_WEIGHT`；
    - ``weight == 0`` 表示**该 turn 的题直接从池里剔除**（记入
      ``dropped_by_turn``），因此空权重（默认）与「全 1」都等价于现状；
    - 空串 / ``None`` / 空字典 -> ``{}``（默认关闭）；
    - **非法输入一律 ``ValueError``**（调用方报错退出，不静默降级）：语法错、
      turn 不是整数/为负、weight 非有限/为负、同一 turn 重复且权重不一致。

    也接受 ``Mapping``（`{10: 2, ...}`），键/值同样校验。
    """
    if spec is None:
        return {}
    if isinstance(spec, Mapping):
        items = [(str(k), v) for k, v in spec.items()]
    elif isinstance(spec, str):
        text = str(spec).strip()
        if not text:
            return {}
        items = []
        for part in text.split(","):
            piece = part.strip()
            if not piece:
                raise ValueError(
                    f"turn 权重语法错误：出现空项（{spec!r}）；期望 "
                    f"'10:2,12:3,14:4,15:4'")
            if ":" not in piece:
                raise ValueError(
                    f"turn 权重语法错误：{piece!r} 缺少 ':'；期望 turn:weight")
            turn_s, weight_s = piece.split(":", 1)
            items.append((turn_s.strip(), weight_s.strip()))
    else:
        raise ValueError(
            f"turn 权重必须是字符串或字典，得到 {type(spec).__name__}: {spec!r}")
    out: Dict[int, float] = {}
    for turn_s, weight_s in items:
        try:
            turn = int(str(turn_s).strip())
        except (TypeError, ValueError):
            raise ValueError(
                f"turn 权重语法错误：turn {turn_s!r} 不是整数") from None
        if turn < 0:
            raise ValueError(f"turn 权重语法错误：turn 必须 >= 0，得到 {turn}")
        try:
            weight = float(weight_s)
        except (TypeError, ValueError):
            raise ValueError(
                f"turn 权重语法错误：turn {turn} 的 weight {weight_s!r} 不是数字"
            ) from None
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError(
                f"turn 权重语法错误：turn {turn} 的 weight 必须是有限且 >= 0，"
                f"得到 {weight!r}")
        if turn in out and out[turn] != weight:
            raise ValueError(
                f"turn 权重语法错误：turn {turn} 重复且权重不一致"
                f"（{out[turn]!r} vs {weight!r}）")
        out[turn] = weight
    return dict(sorted(out.items()))


def format_turn_weights(weights: Mapping[int, float]) -> str:
    """``{10: 2.0, 12: 3}`` -> ``"10:2,12:3"``（日志/回显用；空 -> ``""``）。"""
    items = sorted((int(k), float(v)) for k, v in dict(weights or {}).items())
    return ",".join(f"{t}:{w:g}" for t, w in items)


def parse_turn_ranges(spec: Any) -> List[Tuple[int, int]]:
    """解析 ``--focus-turns`` 的 ``"10-15"`` / ``"10-15,8"`` 语法 -> ``[(10,15),(8,8)]``。

    每项 ``a-b``（闭区间）或单个 ``a``；``a <= b``、均非负；空串 -> ``[]``（全部 turn）。
    非法输入抛 ``ValueError``（不静默）。返回按起点排序、合并重叠后的区间列表。
    """
    if spec is None:
        return []
    if isinstance(spec, (list, tuple)):
        items = [str(x) for x in spec]
    elif isinstance(spec, str):
        text = str(spec).strip()
        if not text:
            return []
        items = [p.strip() for p in text.split(",")]
    else:
        raise ValueError(
            f"focus-turns 必须是字符串，得到 {type(spec).__name__}: {spec!r}")
    raw: List[Tuple[int, int]] = []
    for piece in items:
        if not piece:
            raise ValueError(f"focus-turns 语法错误：出现空项（{spec!r}）")
        if "-" in piece:
            lo_s, hi_s = piece.split("-", 1)
        else:
            lo_s = hi_s = piece
        try:
            lo, hi = int(lo_s.strip()), int(hi_s.strip())
        except (TypeError, ValueError):
            raise ValueError(
                f"focus-turns 语法错误：{piece!r} 不是 'a-b' 或整数") from None
        if lo < 0 or hi < 0:
            raise ValueError(f"focus-turns 语法错误：turn 必须 >= 0（{piece!r}）")
        if lo > hi:
            raise ValueError(
                f"focus-turns 语法错误：区间下界 > 上界（{piece!r}）")
        raw.append((lo, hi))
    merged: List[Tuple[int, int]] = []
    for lo, hi in sorted(raw):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def turn_in_focus(turn: int, ranges: Sequence[Tuple[int, int]]) -> bool:
    """``turn`` 是否落在 ``parse_turn_ranges`` 的区间里（空列表 = 全部回合）。"""
    if not ranges:
        return True
    t = int(turn)
    return any(int(lo) <= t <= int(hi) for lo, hi in ranges)


def parse_game_indices(spec: Any) -> List[int]:
    """解析 ``--audit-games`` 的 ``"0-5,9"`` 语法 -> ``[0,1,2,3,4,5,9]``。

    空串 -> ``[]``（不审计任何局）；非法输入抛 ``ValueError``（不静默）。
    """
    ranges = parse_turn_ranges(spec)
    out: List[int] = []
    for lo, hi in ranges:
        out.extend(range(int(lo), int(hi) + 1))
    return sorted(set(out))


def problem_strength_delta(row: Mapping[str, Any]) -> float:
    """题目行 -> t+3 **归一化强度增量** ``log1p(after) - log1p(before)``。

    字段优先级：``label.strength_delta``（新池子显式写的别名）-> ``label.delta_log1p``
    （老池子只有这个）。两者都缺失时返回 ``nan``（由调用方决定是报错还是忽略）：
    **不猜**原始 ``label.delta``（量纲差 3 个数量级，混用会让阈值失去意义）。
    """
    lab = (row.get("label") or {}) if isinstance(row, Mapping) else {}
    for key in ("strength_delta", "delta_log1p"):
        if key in lab and lab[key] is not None:
            try:
                return float(lab[key])
            except (TypeError, ValueError):
                return float("nan")
    if "strength_delta" in row and row["strength_delta"] is not None:
        try:
            return float(row["strength_delta"])
        except (TypeError, ValueError):
            return float("nan")
    return float("nan")


def turn_weight_vector(turns: Any, weights: Mapping[int, float]) -> np.ndarray:
    """题目 ``turn`` 数组 -> 每行的 soft-CE 权重（f32；未列出的 turn = 1.0）。"""
    t = np.asarray(turns, dtype=np.int64).reshape(-1)
    w = np.full(t.shape, float(DEFAULT_TURN_WEIGHT), dtype=np.float32)
    for turn, weight in dict(weights or {}).items():
        w[t == int(turn)] = float(weight)
    return w


def filter_problem_rows(rows: Sequence[Mapping[str, Any]], *,
                        min_strength_delta: float = 0.0,
                        turn_weights: Any = None
                        ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """按 `--problem-min-strength-delta` / `--problem-turn-weight` 过滤题目行。

    返回 ``(kept_rows, report)``；``report`` 里的字段就是训练 history 的口径：

    - ``problem_pool_size``：过滤前题数；
    - ``problem_pool_dropped_by_delta``：``strength_delta < min_strength_delta`` 掉的数量；
    - ``problem_pool_dropped_by_turn``：turn 权重为 0 掉的数量；
    - ``problem_pool_used``：过滤后题数；
    - ``problem_pool_turn_weights`` / ``problem_pool_min_strength_delta``：生效值。

    ``min_strength_delta > 0`` 而题目缺 ``strength_delta`` 字段时**报错**（``ValueError``），
    不静默保留/丢弃；默认 ``0`` 时不做任何过滤（逐位等价）。
    """
    tw = parse_turn_weights(turn_weights)
    thr = float(min_strength_delta)
    if not math.isfinite(thr) or thr < 0.0:
        raise ValueError(
            f"min_strength_delta 必须有限且 >= 0，得到 {min_strength_delta!r}")
    n_all = len(rows)
    kept: List[Dict[str, Any]] = []
    drop_delta = 0
    drop_turn = 0
    missing_delta = 0
    zero_turns = {t for t, w in tw.items() if float(w) == 0.0}
    for row in rows:
        if zero_turns:
            try:
                turn = int(row.get("turn") or 0)
            except (TypeError, ValueError):
                turn = 0
            if turn in zero_turns:
                drop_turn += 1
                continue
        if thr > 0.0:
            delta = problem_strength_delta(row)
            if not math.isfinite(delta):
                missing_delta += 1
                raise ValueError(
                    "题目缺少 label.strength_delta/delta_log1p，无法按 "
                    f"--problem-min-strength-delta={thr} 过滤（problem_id="
                    f"{row.get('problem_id')!r}）")
            if delta < thr:
                drop_delta += 1
                continue
        kept.append(dict(row))
    report = {
        "problem_pool_size": int(n_all),
        "problem_pool_used": int(len(kept)),
        "problem_pool_dropped_by_delta": int(drop_delta),
        "problem_pool_dropped_by_turn": int(drop_turn),
        "problem_pool_missing_delta": int(missing_delta),
        "problem_pool_min_strength_delta": float(thr),
        "problem_pool_turn_weights": {str(t): float(w) for t, w in tw.items()},
    }
    return kept, report


# ══════════════════════════════════════════════════════════════════════════
# 4. 题目池
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class BoardProblemPool:
    """面试题池（SoA numpy；``n = len(turn)``）。

    ``features/cards/mask`` 是**训练输入同口径**的观测；``ref_*`` 是 top-k 软标签；
    ``strength_target`` 是**强度增量**的 z-score：``log1p(after)-log1p(before)``（t+3）。

    为什么预测增量而不是绝对强度：绝对强度几乎完全由「当前局面/回合」决定（实测在
    trunk 的 global token 上 CV-R²≈0.91，辅助任务退化成恒等式），而增量才是**动作能
    改变**的部分（CV-R²≈0.69，残差大 3 倍），也是 [RESEARCH_PLAN_V2](RESEARCH_PLAN_V2.md)
    §4.1 定义的结果标注口径。绝对强度仍保留在 ``strength_after`` 里供报告。
    """

    features: np.ndarray      # f32[n, 3227]
    cards: np.ndarray         # int32[n, 124]
    mask: np.ndarray          # bool[n, 245]
    turn: np.ndarray          # int16[n]
    tier: np.ndarray          # int16[n]
    gold: np.ndarray          # int16[n]
    ref_actions: np.ndarray   # int16[n, k]（-1 = pad）
    ref_weights: np.ndarray   # f32[n, k]
    policy_action: np.ndarray  # int16[n]
    strength_before: np.ndarray  # f32[n]
    strength_after: np.ndarray   # f32[n]
    strength_target: np.ndarray  # f32[n]（z-score of log1p(after)-log1p(before)）
    tier_up: np.ndarray       # int8[n]
    bc_valid: np.ndarray      # bool[n]（有合法参考解）
    aux_valid: np.ndarray     # bool[n]（有 t+3 强度标注）
    tags: List[List[str]] = field(default_factory=list)
    horizon: int = DEFAULT_HORIZON
    norm: Dict[str, float] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    path: str = ""
    #: 每题的 t+3 归一化强度增量（``log1p(after)-log1p(before)``；缺失 = nan）。
    strength_delta: Optional[np.ndarray] = None
    #: 每题的 soft-CE 权重（``--problem-turn-weight``；None / 未配置 = 全 1）。
    turn_weight: Optional[np.ndarray] = None
    #: 生效的 turn 权重（空 = 不加权，逐位等价）。
    turn_weights: Dict[int, float] = field(default_factory=dict)
    #: 池过滤报告（``problem_pool_size`` / ``..._dropped_by_delta`` / ``..._by_turn``）。
    filter_report: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.turn.shape[0])

    def summary(self) -> Dict[str, Any]:
        """池摘要（不含量大的数组；进启动日志 / summary.json）。"""
        n = len(self)
        if n == 0:
            return {"path": self.path, "problems": 0,
                    "filter": dict(self.filter_report)}
        by_turn: Dict[str, int] = {}
        for t in self.turn.tolist():
            by_turn[str(int(t))] = by_turn.get(str(int(t)), 0) + 1
        by_tag: Dict[str, int] = {t: 0 for t in ALL_TAGS}
        for tags in self.tags:
            for t in tags:
                by_tag[t] = by_tag.get(t, 0) + 1
        delta = (np.asarray(self.strength_delta, np.float64)
                 if self.strength_delta is not None
                 else np.zeros(0, np.float64))
        delta = delta[np.isfinite(delta)]
        late = int((np.asarray(self.turn, np.int64) >= LATE_TURN_MIN).sum())
        return {
            "path": self.path, "schema": PROBLEM_SCHEMA_VERSION,
            "problems": int(n),
            "bc_valid": int(self.bc_valid.sum()),
            "bc_valid_rate": float(self.bc_valid.mean()),
            "aux_valid": int(self.aux_valid.sum()),
            "aux_valid_rate": float(self.aux_valid.mean()),
            "ref_top1": int((self.ref_actions[:, 0] >= 0).sum())
            if self.ref_actions.ndim == 2 and self.ref_actions.shape[1] else 0,
            "by_turn": dict(sorted(by_turn.items(), key=lambda kv: int(kv[0]))),
            "by_tag": by_tag,
            "late_turn_min": int(LATE_TURN_MIN),
            "late_turn_problems": int(late),
            "strength_delta_p50": float(np.percentile(delta, 50))
            if delta.size else 0.0,
            "strength_delta_mean": float(delta.mean()) if delta.size else 0.0,
            "turn_weights": {str(t): float(w)
                             for t, w in sorted(self.turn_weights.items())},
            "filter": dict(self.filter_report),
            "strength_target": str(self.norm.get("target", "delta_log1p")),
            "tier_up_rate": float(self.tier_up[self.aux_valid].mean())
            if bool(self.aux_valid.any()) else 0.0,
            "strength_before_p50": float(np.percentile(
                self.strength_before, 50)) if n else 0.0,
            "strength_after_p50": float(np.percentile(
                self.strength_after[self.aux_valid], 50))
            if bool(self.aux_valid.any()) else 0.0,
            "norm": dict(self.norm),
            "horizon": int(self.horizon),
            "build": dict(self.meta),
        }


def _ref_rows(ref: Mapping[str, Any], k: int) -> Tuple[np.ndarray, np.ndarray]:
    acts = np.full(k, -1, dtype=np.int16)
    wts = np.zeros(k, dtype=np.float32)
    a = list(ref.get("actions") or [])
    w = list(ref.get("weights") or [])
    for i in range(min(k, len(a), len(w))):
        acts[i] = int(a[i])
        wts[i] = float(w[i])
    s = float(wts.sum())
    if s > 0:
        wts = wts / s
    return acts, wts


def load_problem_pool(path: str = DEFAULT_PROBLEM_PATH, *,
                      meta_path: Optional[str] = None,
                      top_k: int = 8,
                      limit: Optional[int] = None,
                      min_strength_delta: float = 0.0,
                      turn_weights: Any = None) -> BoardProblemPool:
    """读 ``problems.jsonl``（+ 可选 ``problems.meta.json``）-> :class:`BoardProblemPool`。

    ``problems.meta.json`` 里有 ``strength_norm``（z-score 的 mean/std）；缺失时用池内
    数据现算。文件不存在 / 全被过滤时返回**空池**（训练入口据此自动关闭系数）。

    两个可选开关（**默认关闭 = 逐位等价**，见 :func:`filter_problem_rows`）：

    - ``min_strength_delta``：只保留 ``label.strength_delta >= 阈值`` 的题
      （t+3 归一化强度增量；默认 0 = 不过滤）；
    - ``turn_weights``：``"10:2,12:3,14:4,15:4"`` 或 ``{10: 2.0, ...}``，给每题的
      soft-CE 损失加权（未列出的 turn 权重 1；权重 0 = 该 turn 的题直接剔除）。
    """
    rows: List[Dict[str, Any]] = []
    cap = int(limit) if limit is not None and int(limit) >= 0 else None
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if cap is not None and len(rows) >= cap:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(r, dict) and r.get("obs") and r.get("label"):
                    rows.append(r)
    meta: Dict[str, Any] = {}
    mp = meta_path or (os.path.splitext(path)[0] + ".meta.json")
    if os.path.isfile(mp):
        try:
            with open(mp, "r", encoding="utf-8") as fh:
                meta = json.load(fh) or {}
        except (ValueError, TypeError, OSError):
            meta = {}
    tw = parse_turn_weights(turn_weights)
    rows, report = filter_problem_rows(rows, min_strength_delta=min_strength_delta,
                                       turn_weights=tw)
    report["problem_pool_path"] = str(path)
    n = len(rows)
    k = max(1, int(top_k))
    if n == 0:
        z = np.zeros((0,), dtype=np.float32)
        return BoardProblemPool(
            features=np.zeros((0, OBS_FLOATS), np.float32),
            cards=np.zeros((0, OBS_CARDS), np.int32),
            mask=np.zeros((0, N_ACTIONS), bool),
            turn=np.zeros(0, np.int16), tier=np.zeros(0, np.int16),
            gold=np.zeros(0, np.int16),
            ref_actions=np.full((0, k), -1, np.int16),
            ref_weights=np.zeros((0, k), np.float32),
            policy_action=np.zeros(0, np.int16),
            strength_before=z, strength_after=z.copy(), strength_target=z.copy(),
            tier_up=np.zeros(0, np.int8), bc_valid=np.zeros(0, bool),
            aux_valid=np.zeros(0, bool), tags=[], path=str(path), meta=meta,
            strength_delta=z.copy(), filter_report=report,
            turn_weights=tw)
    feats = np.zeros((n, OBS_FLOATS), np.float32)
    cards = np.zeros((n, OBS_CARDS), np.int32)
    masks = np.zeros((n, N_ACTIONS), bool)
    ref_a = np.full((n, k), -1, np.int16)
    ref_w = np.zeros((n, k), np.float32)
    turn = np.zeros(n, np.int16)
    tier = np.zeros(n, np.int16)
    gold = np.zeros(n, np.int16)
    pol = np.zeros(n, np.int16)
    sb = np.zeros(n, np.float32)
    sa = np.zeros(n, np.float32)
    sdel = np.zeros(n, np.float32)
    tu = np.zeros(n, np.int8)
    aux = np.zeros(n, bool)
    tags: List[List[str]] = []
    for i, r in enumerate(rows):
        f, c, m = decode_obs(r["obs"])
        feats[i], cards[i], masks[i] = f, c, m
        turn[i] = int(r.get("turn") or 0)
        tier[i] = int((r.get("state") or {}).get("tier") or 0)
        gold[i] = int((r.get("state") or {}).get("gold") or 0)
        pol[i] = int(r.get("policy_action") or 0)
        ra, rw = _ref_rows(r.get("ref") or {}, k)
        ref_a[i], ref_w[i] = ra, rw
        lab = r.get("label") or {}
        sb[i] = float(lab.get("strength_before") or 0.0)
        sa[i] = float(lab.get("strength_after_t3") or 0.0)
        tu[i] = int(lab.get("tier_up") or 0)
        sdel[i] = problem_strength_delta(r)
        # 强度头只在「t+3 时仍存活」的题上训练：出局的题用最后可见值，尺度不可比；
        # 它们仍保留在池里（题目 CE 用），只是不进强度损失（masked，而不是填 0）。
        aux[i] = bool(lab.get("available", 1)) and bool(lab.get("survived", 1))
        tags.append([str(t) for t in (r.get("tags") or [])])
    delta_lp = (np.log1p(np.maximum(sa, 0.0))
                - np.log1p(np.maximum(sb, 0.0)))
    norm = dict(meta.get("strength_norm") or {})
    if (not norm or float(norm.get("std", 0.0)) <= 0.0
            or str(norm.get("target", "")) not in ("delta_log1p", "")):
        vals = delta_lp[aux]
        mean = float(vals.mean()) if vals.size else 0.0
        std = float(vals.std()) or 1.0
        norm = {"mean": mean, "std": std, "source": "pool",
                "target": "delta_log1p"}
    z = (delta_lp - float(norm["mean"])) / float(norm["std"])
    bc_valid = (ref_a[:, 0] >= 0) & (ref_w.sum(axis=1) > 0)
    return BoardProblemPool(
        features=feats, cards=cards, mask=masks, turn=turn, tier=tier,
        gold=gold, ref_actions=ref_a, ref_weights=ref_w, policy_action=pol,
        strength_before=sb, strength_after=sa, strength_target=z.astype(np.float32),
        tier_up=tu, bc_valid=bc_valid, aux_valid=aux, tags=tags,
        horizon=int(meta.get("horizon", DEFAULT_HORIZON) or DEFAULT_HORIZON),
        norm=norm, meta=meta, path=str(path),
        strength_delta=sdel,
        turn_weight=(turn_weight_vector(turn, tw) if tw else None),
        turn_weights=tw, filter_report=report)


@dataclass
class BoardProblemBatch:
    """一批题目（``problem_obs_batch`` 的输出；只有被采样到的行）。"""

    features: np.ndarray          # f32[n, 3227]
    cards: np.ndarray             # int32[n, 124]
    mask: np.ndarray              # bool[n, 245]
    soft: np.ndarray              # f32[n, 245]（参考解软标签，行和为 1 或全 0）
    bc_valid: np.ndarray          # bool[n]
    strength_target: np.ndarray   # f32[n]（z-score of log1p）
    tier_target: np.ndarray       # f32[n]
    aux_valid: np.ndarray         # bool[n]
    ref_top1: np.ndarray          # int16[n]（-1 = 无）
    policy_action: np.ndarray     # int16[n]
    #: 题目 turn（诊断 / 测试用；默认 None 表示未填）。
    turn: Optional[np.ndarray] = None
    #: soft-CE 的每行权重（``--problem-turn-weight``；None = 不加权，逐位等价）。
    weight: Optional[np.ndarray] = None

    def __len__(self) -> int:
        return int(self.features.shape[0])


def problem_obs_batch(pool: BoardProblemPool, indices: Any, *,
                      only_bc: bool = False, only_aux: bool = False
                      ) -> BoardProblemBatch:
    """按 ``indices`` 组一批题目观测 + 软标签 + 强度标签。

    ``soft`` 只会落在**合法掩码内**的动作上（构造期已过滤，这里再防御性清零并重新
    归一化）；没有任何合法参考解的题 ``bc_valid=False``，缺 t+3 标签的题
    ``aux_valid=False`` —— 损失只在这些有效行上平均，**不用默认 0 伪造标签**。
    """
    idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    n = int(idx.size)
    feats = pool.features[idx].copy()
    cards = pool.cards[idx].copy()
    masks = pool.mask[idx].copy()
    soft = np.zeros((n, N_ACTIONS), np.float32)
    ra = pool.ref_actions[idx]
    rw = pool.ref_weights[idx]
    for i in range(n):
        for j in range(ra.shape[1]):
            a = int(ra[i, j])
            if a < 0:
                break
            if a < N_ACTIONS and bool(masks[i, a]):
                soft[i, a] = float(rw[i, j])
        s = float(soft[i].sum())
        if s > 0:
            soft[i] /= s
    bc_valid = pool.bc_valid[idx].copy() & (soft.sum(axis=1) > 0)
    aux_valid = pool.aux_valid[idx].copy()
    if only_bc:
        aux_valid[:] = False
    if only_aux:
        bc_valid[:] = False
    top1 = np.full(n, -1, dtype=np.int16)
    for i in range(n):
        if bc_valid[i]:
            top1[i] = int(np.argmax(soft[i]))
    weight = None
    if pool.turn_weights and pool.turn_weight is not None:
        weight = np.asarray(pool.turn_weight, np.float32)[idx].copy()
    return BoardProblemBatch(
        features=feats, cards=cards, mask=masks, soft=soft,
        bc_valid=bc_valid, strength_target=pool.strength_target[idx].copy(),
        tier_target=pool.tier_up[idx].astype(np.float32),
        aux_valid=aux_valid, ref_top1=top1,
        policy_action=pool.policy_action[idx].copy(),
        turn=pool.turn[idx].copy(), weight=weight)


# ══════════════════════════════════════════════════════════════════════════
# 5. 损失
# ══════════════════════════════════════════════════════════════════════════
def problem_bc_soft_ce(logits: Any, batch: BoardProblemBatch) -> Dict[str, Any]:
    """题目状态上的 soft-label 交叉熵（``-Σ_k q_k log p_k``，只在合法动作上）。

    返回 ``{"loss", "top1_acc", "policy_in_ref", "n"}``；``top1_acc`` = 策略 argmax
    命中参考解 top-1 的比例，``policy_in_ref`` = 当前采集动作落在参考解 top-k 的比例
    （0 阶诊断，不参与梯度）。无有效行时 ``loss`` 为 0（不制造假梯度）。

    **turn 加权**（``--problem-turn-weight``，默认关闭）：``batch.weight`` 为 None 时
    走原来的 ``ce[valid].mean()``（逐位等价）；非 None 时走加权均值
    ``Σ w_i CE_i / Σ w_i``（同样只在 ``bc_valid`` 行上），因此权重全 1 时与不加权
    数学等价、但实现路径不同（默认走 None 路径，避免浮点顺序差异）。
    """
    import torch  # 惰性：本模块在纯 numpy 路径下不要求 torch
    from .ppo import masked_log_softmax_torch
    dev = logits.device
    mask_t = torch.from_numpy(np.ascontiguousarray(batch.mask.astype(bool))).to(dev)
    soft = torch.from_numpy(np.ascontiguousarray(batch.soft.astype(np.float32))).to(dev)
    valid = torch.from_numpy(np.ascontiguousarray(batch.bc_valid.astype(bool))).to(dev)
    logp = masked_log_softmax_torch(logits.float(), mask_t)
    ce_all = -(soft * torch.where(mask_t, logp, torch.zeros_like(logp))).sum(dim=-1)
    if not bool(valid.any()):
        zero = torch.zeros((), device=dev)
        return {"loss": zero, "top1_acc": zero.detach(),
                "policy_in_ref": zero.detach(), "n": 0, "weight_sum": 0.0}
    weight = getattr(batch, "weight", None)
    if weight is None:
        loss = ce_all[valid].mean()
        w_sum = float(valid.sum().item())
    else:
        w = torch.from_numpy(np.ascontiguousarray(
            np.asarray(weight, np.float32).reshape(-1))).to(dev)[valid]
        w = w.clamp_min(0.0)
        w_sum = float(w.sum().item())
        if w_sum <= 0.0:
            zero = torch.zeros((), device=dev)
            return {"loss": zero, "top1_acc": zero.detach(),
                    "policy_in_ref": zero.detach(), "n": 0, "weight_sum": 0.0}
        loss = (ce_all[valid] * w).sum() / w.sum()
    with torch.no_grad():
        pred = logp.argmax(dim=-1)
        t1 = torch.from_numpy(np.ascontiguousarray(
            batch.ref_top1.astype(np.int64))).to(dev)
        ok = (pred == t1) & valid
        pa = torch.from_numpy(np.ascontiguousarray(
            batch.policy_action.astype(np.int64))).to(dev)
        in_ref = (soft.gather(1, pa.clamp(0, N_ACTIONS - 1).unsqueeze(1)).squeeze(1)
                  > 0) & valid
        return {"loss": loss,
                "top1_acc": ok.to(torch.float32).sum() / valid.sum().clamp_min(1),
                "policy_in_ref": (in_ref.to(torch.float32).sum()
                                  / valid.sum().clamp_min(1)),
                "n": int(valid.sum().item()), "weight_sum": float(w_sum)}


def strength_aux_loss(pred: Any, batch: BoardProblemBatch,
                      pos_weight: float = 1.0) -> Dict[str, Any]:
    """强度辅助头损失：``MSE(z(log1p(strength_t3))) + BCE(tier_up)``。

    ``pred`` 形状 ``[n, 2]``（第 0 列 = 强度回归、第 1 列 = tier+1 logit）。
    两个子损失各自只在**有标注的行**上平均；无有效行时返回 0（不制造假梯度）。
    """
    import torch
    import torch.nn.functional as F
    dev = pred.device
    aux = torch.from_numpy(np.ascontiguousarray(
        batch.aux_valid.astype(bool))).to(dev)
    zero = torch.zeros((), device=dev)
    if not bool(aux.any()):
        return {"loss": zero, "mse": zero.detach(), "bce": zero.detach(), "n": 0,
                "tier_up_acc": zero.detach()}
    s_tgt = torch.from_numpy(np.ascontiguousarray(
        batch.strength_target.astype(np.float32))).to(dev)
    t_tgt = torch.from_numpy(np.ascontiguousarray(
        batch.tier_target.astype(np.float32))).to(dev)
    pw = (torch.as_tensor(float(pos_weight), device=dev)
          if float(pos_weight) > 0.0 else None)
    mse = F.mse_loss(pred[aux, 0].float(), s_tgt[aux])
    bce = F.binary_cross_entropy_with_logits(pred[aux, 1].float(), t_tgt[aux],
                                             pos_weight=pw)
    with torch.no_grad():
        acc = ((pred[aux, 1] > 0).to(torch.float32) == t_tgt[aux]).to(
            torch.float32).mean()
    return {"loss": mse + bce, "mse": mse.detach(), "bce": bce.detach(),
            "n": int(aux.sum().item()), "tier_up_acc": acc}


def fit_strength_head(model: Any, pool: BoardProblemPool, *,
                      ridge: float = 1.0, tier_steps: int = 200,
                      tier_lr: float = 0.1, tier_l2: float = 1e-2,
                      freeze: bool = True, cv: int = 5,
                      device: str = "cpu", chunk: int = 64) -> Dict[str, Any]:
    """在题目池上**离线拟合**强度辅助头（线性探针），默认随后**冻结**它。

    为什么需要（两件实测事实）：

    1. 40–60 iter 的 s14 配方 ``lr=1.2e-6``，一次 Adam 步最多动权重 ~1e-6；随机初始化
       的头在 200 步内**不可能校准**，它给 trunk 的梯度只是一个随机方向（实测随机头与
       目标的相关性甚至可以是 −0.79，取决于哪个高方差方向抽到负号）；
    2. 但**不冻结**的线性头在 315 道题上会过拟合（d_model=384、n=293 时 MSE 可到 0.04），
       残差 ≈0 ⇒ ``dL/dg = Wᵀ(y−ŷ) ≈ 0``，辅助损失对 trunk 也没有信号。

    所以这里做的是 **CV 选 λ 的 ridge 线性探针 + 冻结**：头只在池上拟合一次，训练中
    不更新（``requires_grad=False``），辅助损失只作用在 trunk 上——语义是「**让 trunk 的
    表示保持对 t+3 战团强度的可预测性**」，而不是「训练一个会过拟合的回归头」。

    只用 ``aux_valid=True``（t+3 前存活）的题；目标是**强度增量**（t+3 的 log1p 差值）。
    返回 CV 误差/相关性与选中的 λ。
    """
    import torch
    head = getattr(model, "strength_head", None)
    if head is None:
        raise ValueError("模型没有 strength_head：先 attach_strength_head()")
    fn = getattr(model, "forward_global", None)
    if fn is None:
        raise ValueError("模型不支持 forward_global（只有 entity/entity18m 支持）")
    if len(pool) == 0 or not bool(np.asarray(pool.aux_valid).any()):
        raise ValueError("题目池没有可用的 t+3 强度标注（aux_valid 全 False）")
    was_training = bool(getattr(model, "training", False))
    model.eval()
    dev = torch.device(device)
    gs = []
    try:
        with torch.no_grad():
            for start in range(0, len(pool), int(chunk)):
                b = problem_obs_batch(
                    pool, np.arange(start, min(start + int(chunk), len(pool))),
                    only_aux=True)
                x = torch.from_numpy(b.features).to(dev)
                c = torch.from_numpy(b.cards.astype(np.int64)).to(dev)
                m = torch.from_numpy(b.mask).to(dev)
                gs.append(fn(x, c, m).float().cpu())
    finally:
        model.train(was_training)
    G = torch.cat(gs, dim=0)
    aux = torch.from_numpy(np.asarray(pool.aux_valid, dtype=bool))
    X = G[aux].float()
    y = torch.from_numpy(np.asarray(pool.strength_target, np.float32))[aux]
    t = torch.from_numpy(pool.tier_up.astype(np.float32))[aux]
    mu = X.mean(dim=0, keepdim=True)
    sd = X.std(dim=0, keepdim=True).clamp_min(1e-6)
    Xs = (X - mu) / sd
    n, d = int(Xs.shape[0]), int(Xs.shape[1])

    def _solve(xx: Any, yy: Any, lam: float) -> Any:
        A = xx.T @ xx + (float(lam) * float(xx.shape[0])) * torch.eye(
            xx.shape[1], dtype=xx.dtype)
        return torch.linalg.solve(A, xx.T @ yy)

    # ── 1) CV 选 ridge λ（只在标准化特征上；λ 已按样本数缩放）────────────
    grid = [1e-3, 1e-2, 1e-1, 1.0, 10.0]
    k = max(2, min(int(cv), n))
    folds = np.array_split(np.arange(n), k)
    best = None
    for lam in grid:
        mse = []
        for f in folds:
            tr = np.setdiff1d(np.arange(n), f)
            if tr.size < 2 or f.size == 0:
                continue
            w = _solve(Xs[tr], y[tr], lam)
            mse.append(float(torch.nn.functional.mse_loss(Xs[f] @ w, y[f])))
        if mse:
            cand = (float(np.mean(mse)), float(lam))
            if best is None or cand[0] < best[0]:
                best = cand
    cv_mse, lam = best if best is not None else (float("nan"), float(ridge))
    w = _solve(Xs, y, lam)
    # ── 2) tier+1：L2 logistic（Adam，避免完全分离时权重发散）───────────
    wt = torch.zeros(d, requires_grad=True)
    bt = torch.zeros(1, requires_grad=True)
    opt = torch.optim.Adam([wt, bt], lr=float(tier_lr))
    for _ in range(max(1, int(tier_steps))):
        opt.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(
            Xs @ wt + bt, t) + float(tier_l2) * float((wt ** 2).mean())
        loss.backward()
        opt.step()
    with torch.no_grad():
        head.weight[0].copy_((w / sd[0]).to(head.weight.device))
        head.bias[0].copy_((-(w * mu[0] / sd[0]).sum()).to(head.bias.device))
        head.weight[1].copy_((wt.detach() / sd[0]).to(head.weight.device))
        head.bias[1].copy_((bt.detach()[0]
                            - (wt.detach() * mu[0] / sd[0]).sum()).to(head.bias.device))
        pred = head(G.float())
        mse = float(torch.nn.functional.mse_loss(pred[aux, 0], y))
        bce = float(torch.nn.functional.binary_cross_entropy_with_logits(
            pred[aux, 1], t))
        acc = float(((pred[aux, 1] > 0).float() == t).float().mean())
        corr = (float(np.corrcoef(y.numpy(), pred[aux, 0].numpy())[0, 1])
                if n > 2 else 0.0)
    # ── 3) 冻结：辅助损失只作用在 trunk（见 docstring 的推导）─────────────
    if bool(freeze):
        for prm in head.parameters():
            prm.requires_grad_(False)
    model.strength_norm = dict(pool.norm)
    return {"n": n, "mse": mse, "cv_mse": float(cv_mse), "bce": bce,
            "tier_acc": acc, "pearson_delta": corr, "ridge": float(lam),
            "frozen": bool(freeze), "folds": k}


def denormalize_strength(z: Any, norm: Mapping[str, Any]) -> np.ndarray:
    """z-score -> **强度增量**（``log1p(after)-log1p(before)``，非原始强度）。"""
    mean = float((norm or {}).get("mean", 0.0) or 0.0)
    std = float((norm or {}).get("std", 1.0) or 1.0)
    return np.asarray(z, dtype=np.float64) * std + mean


def strength_after_from_delta(z: Any, strength_before: Any,
                              norm: Mapping[str, Any]) -> np.ndarray:
    """由增量 z-score + 当前强度还原 t+3 强度（``expm1``；报告/校准用）。"""
    delta = denormalize_strength(z, norm)
    before = np.asarray(strength_before, dtype=np.float64)
    return np.expm1(np.log1p(np.maximum(before, 0.0)) + delta)


# ══════════════════════════════════════════════════════════════════════════
# 6. 题目构造：按训练分布 rollout，记录关键局面 + t+3 标签
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class ProblemCollectConfig:
    """出题 rollout 配置（默认 = s14 训练分布：人类 5 席 p0.9 + 镜像 2 席 p0.2）。"""

    games: int = 16
    seed: int = 20200
    max_steps: int = 20000
    learner_seat: int = 0
    horizon: int = DEFAULT_HORIZON
    #: 最小出题回合（默认 1：跳过 turn 0 的选英雄局面）。
    min_turn: int = 1
    #: 每回合最多保留的分叉点题数（回合起点题总是保留，受 ``keep_turn_start`` 控制）。
    max_fork_per_turn: int = 2
    keep_turn_start: bool = True
    #: 分叉点判据：核心随从的最低 tier。
    core_min_tier: int = 3
    #: 人类战团注入（与 s14 同分布）。
    human_boards: str = os.path.join(_REPO_ROOT, "data", "real_library",
                                     "library_real_quasi_full.jsonl")
    human_board_p: float = 0.9
    human_board_seats: int = 5
    human_board_fidelity: str = "full"
    human_board_fast_inject: bool = True
    #: 镜像快照注入（与 s14 同分布）。
    mirror_snaps: str = os.path.join(_REPO_ROOT, "runs", "library", "snaps_champ")
    mirror_seats: int = 2
    mirror_p: float = 0.2
    mirror_sample: str = "p75"
    #: 策略采样温度 / 行为（与采集一致）。
    temperature: float = 1.0
    #: 换位守卫（题目生成与监督都套用）。
    move_guard: bool = True
    move_cap: int = DEFAULT_MOVE_CAP
    move_repeat_limit: int = DEFAULT_MOVE_REPEAT_LIMIT
    #: 观测存储精度（`f32` 逐位可复现；`f16` 体积减半）。
    obs_dtype: str = "f32"
    #: 只在指定 turn 段出题（``"10-15"`` / ``"10-15,8"``；空 = 全部）。空默认关闭。
    focus_turns: str = ""
    #: 出题时就按 rollout 的 t+3 归一化强度增量过滤（``>= 阈值``；0 = 不过滤）。
    min_delta: float = 0.0
    #: 质量审计（默认空 = 关闭）：这些**局号**（0 起的 ``gi``）会被整局记录
    #: （每回合起始 ``state_json`` + 全部 learner 动作），供
    #: ``scripts/audit_board_problems.py`` 从局面重放 3 回合核对 ``label``。
    audit_games: str = ""
    #: 后期参考解修正（``current`` = 逐位等价；``fixed`` 见 :class:`LateRefConfig`）。
    late_ref_policy: str = "current"
    ref_reroll_cap: float = 0.25
    ref_buy_boost: float = 2.0
    ref_buy_min_freq: float = 0.01
    ref_buy_table: str = ""

    def late_ref(self) -> LateRefConfig:
        """由出题配置构造 :class:`LateRefConfig`（非法值抛 ``ValueError``）。"""
        return LateRefConfig(policy=str(self.late_ref_policy),
                             turn_min=int(LATE_TURN_MIN),
                             reroll_cap=float(self.ref_reroll_cap),
                             buy_boost=float(self.ref_buy_boost),
                             buy_min_freq=float(self.ref_buy_min_freq))

    def focus_ranges(self) -> List[Tuple[int, int]]:
        """``focus_turns`` 解析后的闭区间列表（非法输入抛 ``ValueError``）。"""
        return parse_turn_ranges(self.focus_turns)

    def focus_allows(self, turn: int) -> bool:
        """``turn`` 是否在 ``focus_turns`` 里（空 = 全部允许）。"""
        return turn_in_focus(turn, self.focus_ranges())


@dataclass
class ProblemCollectResult:
    """出题结果：题目行 + 统计 + rollout 元信息。"""

    problems: List[Dict[str, Any]]
    stats: Dict[str, Any]
    #: 质量审计记录（``audit_games`` 为空时恒为空列表）：一行一局，含每回合起始
    #: ``state_json``、全部 learner 动作、以及该局题目摘要。
    audits: List[Dict[str, Any]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.problems)


def _strength_of(player: Mapping[str, Any]) -> int:
    total = 0
    for m in (player.get("board") or []):
        total += int(m.get("atk") or 0) + int(m.get("hp") or 0)
    return int(total)


def collect_problems(model: Any, cfg: ProblemCollectConfig, *,
                     device: str = "cpu", reference: Optional[ReferenceTable] = None,
                     top_k: int = 8, min_support: int = 40,
                     norm_mean: Any = None, norm_std: Any = None,
                     late_ref: Optional[LateRefConfig] = None,
                     late_ref_buy_table: Optional[HumanBuyTable] = None,
                     progress: bool = False) -> ProblemCollectResult:
    """用**当前权重**按训练分布 rollout，记录关键局面 + t+3 真实标签 + 参考解。

    关键局面：

    - **每回合起点**（learner 的第一个决策，``tags=[turn_start,...]``）；
    - **决策分叉点**：``upgrade_ready``（引擎判定当前可升本）/ ``triple_ready``（三连）
      / ``core_card``（棋盘有 tier≥``core_min_tier`` 的核心随从）；每回合最多保留
      ``max_fork_per_turn`` 个（按出现顺序）。

    每个题目记录：观测（features+cards+合法动作，可复现）、当前策略动作/概率、
    人类参考动作 top-k（``match_reference_actions``，含合法掩码与 Move 守卫）、以及
    **t+3 回合**的战团强度/等级真实值（rollout 后回填）。learner 在 t+3 前出局时
    ``available=true`` 但 ``survived=false``、``terminal=true``，强度取最后可见值。

    确定性：模型 eval + 固定 ``seed`` + 每局独立 RNG（注入/采样）→ 同 seed 逐位可复现。
    """
    import hsbg_engine as E  # 惰性：本模块的纯函数路径不依赖引擎

    from .common import mask_from_bytes, obs_arrays
    from .human_board_pool import HumanBoardStats, inject_turn as inject_human, \
        load_pool as load_human_pool
    from .mirror_snapshots import MirrorStats, inject_turn as inject_mirror, \
        load_pool as load_mirror_pool
    from .ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy

    games = max(1, int(cfg.games))
    seat = int(cfg.learner_seat)
    horizon = max(1, int(cfg.horizon))
    ccfg = CollectConfig(games=1, seed=int(cfg.seed), opponent="bot",
                         behavior="net", max_steps=int(cfg.max_steps),
                         temperature=float(cfg.temperature),
                         move_guard=bool(cfg.move_guard),
                         move_cap=int(cfg.move_cap),
                         move_repeat_limit=int(cfg.move_repeat_limit))
    ev = PPOEvaluator(model, device=device, norm_mean=norm_mean,
                      norm_std=norm_std)
    policy = PPOSelfPlayPolicy(model, device=device, config=ccfg, eval_fn=ev,
                               seed=int(cfg.seed), norm_mean=norm_mean,
                               norm_std=norm_std, move_model=False)
    hpool = None
    if str(cfg.human_boards) and float(cfg.human_board_p) > 0:
        hpool = load_human_pool(str(cfg.human_boards))
    mpool = None
    if str(cfg.mirror_snaps) and float(cfg.mirror_p) > 0:
        try:
            mpool = load_mirror_pool(str(cfg.mirror_snaps), sample=str(cfg.mirror_sample))
        except Exception:  # noqa: BLE001 - 镜像库缺失不阻塞出题
            mpool = None
    h_stats = HumanBoardStats(fidelity=str(cfg.human_board_fidelity))
    m_stats = MirrorStats()
    problems: List[Dict[str, Any]] = []
    per_game: List[Dict[str, Any]] = []
    skipped = {"no_ref": 0, "no_label": 0, "fork_cap": 0,
               "no_supervisable": 0, "min_turn": 0, "focus_turn": 0,
               "min_delta": 0}
    focus_ranges = cfg.focus_ranges()
    min_delta = float(cfg.min_delta or 0.0)
    if not math.isfinite(min_delta) or min_delta < 0.0:
        raise ValueError(f"min_delta 必须有限且 >= 0，得到 {cfg.min_delta!r}")
    # 后期参考解修正（默认 current = 不读表、不加字段、逐位等价）
    late_ref_cfg = late_ref if late_ref is not None else cfg.late_ref()
    if late_ref_cfg.enabled() and late_ref_buy_table is None:
        bpath = str(cfg.ref_buy_table or "") or DEFAULT_FIRESTONE_ACTIONS
        late_ref_buy_table = build_human_buy_table(
            bpath, min_freq=float(late_ref_cfg.buy_min_freq))
        print(f"[late-ref] buy_table={bpath} rows={late_ref_buy_table.rows} "
              f"high={ {t: len(v) for t, v in late_ref_buy_table.high.items()} }",
              flush=True)
    audit_set = set(parse_game_indices(cfg.audit_games))
    audits: List[Dict[str, Any]] = []
    n_decisions = 0
    t0 = time.time()
    for gi in range(games):
        gseed = int(cfg.seed) + gi
        game = E.Game(seed=gseed)
        policy.reset()
        policy.reseed(gseed * 7919 + 1)
        hrng = random.Random(gseed * 53 + 11)
        mrng = random.Random(gseed * 31 + 7)
        audit_game = gi in audit_set
        turn_states: Dict[str, str] = {}
        turn_pos: Dict[str, int] = {}
        learner_actions: List[List[int]] = []
        prob_start = len(problems)
        cur_turn = -1
        turn_rows: Dict[int, Dict[str, Any]] = {}
        pending: List[Dict[str, Any]] = []
        move_last, move_counts, move_n = -1, {}, 0
        dec_in_turn = 0
        fork_in_turn = 0
        m_used_seats: List[int] = []
        steps = 0
        def _new_turn(t: int, p_pos: int = 0) -> None:
            nonlocal move_last, move_counts, move_n, dec_in_turn, fork_in_turn, m_used_seats
            move_last, move_counts, move_n = -1, {}, 0
            dec_in_turn = 0
            fork_in_turn = 0
            m_used_seats = []
            if mpool is not None:
                seats = [1, 2][:max(0, int(cfg.mirror_seats))]
                inject_mirror(game, mpool, t, seats=seats, p=float(cfg.mirror_p),
                              rng=mrng, learner_seat=seat, stats=m_stats,
                              applied_out=m_used_seats)
            if hpool is not None:
                inject_human(game, hpool, t, seats_count=int(cfg.human_board_seats),
                             p=float(cfg.human_board_p), rng=hrng,
                             learner_seat=seat, stats=h_stats,
                             mirror_seats=tuple(m_used_seats),
                             fidelity=str(cfg.human_board_fidelity),
                             fast_inject=bool(cfg.human_board_fast_inject))
            pj = json.loads(game.player_json(seat))
            turn_rows[int(t)] = {"strength": _strength_of(pj),
                                 "tier": int(pj.get("tier") or 0),
                                 "gold": int(pj.get("gold") or 0)}
            if audit_game:
                # 审计用：**注入之后**的整局状态（重放的注入来源）。
                # ``p_pos`` 是「本回合开始那一刻正在处理的座位」：回合在
                # seat p 行动后推进时，新回合的前 p 个座位已经在同一 pass 里
                # 处理过了，重放必须从 p 继续（否则会漏掉它们的首动作）。
                turn_states[str(int(t))] = game.state_json()
                turn_pos[str(int(t))] = int(p_pos)
        while not game.is_over() and steps < int(cfg.max_steps):
            t = int(game.turn)
            if t != cur_turn:
                cur_turn = t
                _new_turn(t)
            acted = False
            for p in range(8):
                if game.is_over() or steps >= int(cfg.max_steps):
                    break
                if not game.needs_action(p):
                    continue
                steps += 1
                acted = True
                if int(game.turn) != cur_turn:
                    cur_turn = int(game.turn)
                    _new_turn(cur_turn, p)
                if p != seat:
                    game.bot_play(p)
                    continue
                f, c = obs_arrays(game.observe(seat))
                mask = mask_from_bytes(game.legal_mask(seat))
                pj = json.loads(game.player_json(seat))
                tags = fork_tags(mask, f, c, core_min_tier=int(cfg.core_min_tier))
                is_start = dec_in_turn == 0
                keep = False
                skipless = True
                if int(t) < int(cfg.min_turn):
                    skipped["min_turn"] += 1
                    skipless = False
                elif not turn_in_focus(int(t), focus_ranges):
                    # --focus-turns：只在指定 turn 段出题（默认空 = 全部回合）
                    skipped["focus_turn"] += 1
                    skipless = False
                elif supervisable_legal_actions(mask).size == 0:
                    # 只剩 choose/activate/magnetize/move 之类的合法动作：没有 9 类
                    # 参考解可以覆盖的动作，出题没有监督价值（不是「缺失」，是跳过）。
                    skipped["no_supervisable"] += 1
                    skipless = False
                if skipless:
                    if is_start and bool(cfg.keep_turn_start):
                        keep = True
                    if tags:
                        if fork_in_turn < int(cfg.max_fork_per_turn):
                            keep = True
                            fork_in_turn += 1
                        else:
                            skipped["fork_cap"] += 1
                snap = None
                if keep:
                    snap = {
                        "features": f.copy(), "cards": c.copy(), "mask": mask.copy(),
                        "turn": int(t), "decision_idx": int(dec_in_turn),
                        "tags": ([TAG_TURN_START] if is_start else []) + list(tags),
                        "state": {"strength": _strength_of(pj),
                                  "tier": int(pj.get("tier") or 0),
                                  "gold": int(pj.get("gold") or 0),
                                  "board_len": len(pj.get("board") or []),
                                  "hand_len": len(pj.get("hand") or []),
                                  "shop_len": len(pj.get("shop") or [])},
                        "move": {"last": int(move_last),
                                 "n": int(move_n),
                                 "counts": [[int(k), int(v)]
                                            for k, v in move_counts.items()]},
                    }
                dec = policy.decide(game, seat)
                a = int(dec.action)
                n_decisions += 1
                if audit_game:
                    # 审计用：decision_idx 是**本回合 learner 第几次决策**（0 起），
                    # turn 取动作落下的真实回合（跨回合时 ``t`` 可能过期）。
                    learner_actions.append([int(game.turn), int(dec_in_turn), int(a)])
                if snap is not None:
                    pi = getattr(dec, "pi", None)
                    probs = (np.asarray(pi, dtype=np.float64)
                             if pi is not None else None)
                    snap["policy_action"] = a
                    snap["policy_prob"] = (float(probs[a]) if probs is not None
                                           and probs.size > a else 0.0)
                    pending.append(snap)
                game.step(seat, a)
                move_last = a
                if is_move(a):
                    move_counts[a] = move_counts.get(a, 0) + 1
                    move_n += 1
                dec_in_turn += 1
            if not acted and not game.is_over():
                break
        # ── rollout 后回填 t+3 标签 + 参考解 ─────────────────────────────
        last_turn = max(turn_rows) if turn_rows else 0
        last_row = turn_rows.get(last_turn, {"strength": 0, "tier": 0})
        for snap in pending:
            T = int(snap["turn"])
            tgt = turn_rows.get(T + horizon)
            survived = tgt is not None
            if tgt is None:
                skipped["no_label"] += 1
                tgt = last_row
            s0 = float(snap["state"]["strength"])
            s3 = float(tgt["strength"])
            tier0 = int(snap["state"]["tier"])
            tier3 = int(tgt["tier"])
            strength_delta = float(math.log1p(max(s3, 0.0))
                                   - math.log1p(max(s0, 0.0)))
            if min_delta > 0.0 and strength_delta < min_delta:
                # --min-delta：出题时就用 rollout 的强度增量过滤（默认 0 = 不过滤）
                skipped["min_delta"] += 1
                continue
            lab = {"strength_before": s0,
                   "strength_after_t3": s3,
                   "delta": s3 - s0,
                   "delta_log1p": strength_delta,
                   "strength_delta": strength_delta,
                   "tier_before": tier0, "tier_after": tier3,
                   "tier_up": int(tier3 >= tier0 + 1),
                   "survived": int(survived), "terminal": int(not survived),
                   "available": 1, "horizon": horizon,
                   "target_turn": int(T + horizon)}
            ref = {"actions": [], "weights": []}
            late_audit: Dict[str, Any] = {}
            if reference is not None:
                use_strict = bool(late_ref_cfg.applies(int(T)))
                ref = match_reference_actions(
                    snap["features"], snap["cards"], snap["mask"], reference,
                    top_k=int(top_k), min_support=int(min_support),
                    exclude_move=True,
                    move_last=int(snap["move"]["last"]),
                    move_counts={int(k): int(v)
                                 for k, v in snap["move"]["counts"]},
                    move_n=int(snap["move"]["n"]),
                    cap=int(cfg.move_cap),
                    repeat_limit=int(cfg.move_repeat_limit),
                    levels=(late_ref_cfg.strict_levels if use_strict else None),
                    late_ref=(late_ref_cfg if use_strict else None),
                    buy_table=late_ref_buy_table)
                if not bool(ref.get("matched")):
                    skipped["no_ref"] += 1
                    if use_strict:
                        # 严格层匹配失败：显式记账（不偷偷退回更粗层级）
                        skipped["late_ref_no_support"] = int(
                            skipped.get("late_ref_no_support", 0)) + 1
                if use_strict:
                    late_audit = dict(ref.pop("late_ref", {}) or {})
                    if not late_audit:
                        late_audit = {
                            "policy": str(late_ref_cfg.policy),
                            "applied": False,
                            "reason": str(ref.get("reason", "")),
                            "strict_levels": list(late_ref_cfg.strict_levels)}
            pid = f"bp-{len(problems):06d}"
            row = {
                "problem_id": pid,
                "schema": PROBLEM_SCHEMA_VERSION,
                "source_group": f"rollout:seed={int(cfg.seed)}:game={gi}",
                "game_seed": gseed, "turn": T,
                "is_late_turn": bool(int(T) >= LATE_TURN_MIN),
                "seat": seat,
                "decision_idx": int(snap["decision_idx"]),
                "tags": list(snap["tags"]),
                "obs": encode_obs(snap["features"], snap["cards"], snap["mask"],
                                  dtype=str(cfg.obs_dtype)),
                "state": dict(snap["state"]),
                "policy_action": int(snap["policy_action"]),
                "policy_prob": float(snap["policy_prob"]),
                "ref": dict(ref, reason=str(ref.get("reason", ""))),
                "label": lab,
                "strength_delta": strength_delta,
                "move": dict(snap["move"]),
            }
            if late_audit:
                row["late_ref"] = dict(late_audit)
            problems.append(row)
        if audit_game:
            # 审计记录：一行一局。``turn_states`` 是每回合起始（注入后）的精确状态，
            # ``learner_actions`` 是 learner 的全部动作 ``[turn, decision_idx, action]``。
            audits.append({
                "schema": "board_problem_audit_v1",
                "game_seed": int(gseed), "game_index": int(gi),
                "seat": int(seat), "horizon": int(horizon),
                "turn_states": turn_states,
                "turn_pos": turn_pos,
                "learner_actions": learner_actions,
                "problems": [{
                    "problem_id": str(r.get("problem_id")),
                    "turn": int(r.get("turn") or 0),
                    "decision_idx": int(r.get("decision_idx") or 0),
                    "tags": list(r.get("tags") or []),
                    "obs_sha256": str((r.get("obs") or {}).get("sha256") or ""),
                    "obs_dtype": str((r.get("obs") or {}).get("dtype") or ""),
                    "policy_action": int(r.get("policy_action") or -1),
                    "state": dict(r.get("state") or {}),
                    "label": dict(r.get("label") or {}),
                } for r in problems[prob_start:]],
            })
        per_game.append({"game_seed": gseed, "decisions": int(steps),
                         "turns": int(last_turn), "problems": int(len(pending)),
                         "placement": int(list(game.placements())[seat]),
                         "terminal_no_label": int(sum(
                             1 for s in pending
                             if turn_rows.get(int(s["turn"]) + horizon) is None))})
        if progress:
            print(f"[problems] game {gi + 1}/{games} seed={gseed} "
                  f"problems={len(pending)} elapsed={time.time() - t0:.1f}s",
                  flush=True)
    stats = problem_stats(problems, cfg=cfg, per_game=per_game,
                          skipped=skipped, decisions=n_decisions,
                          human_stats=h_stats.to_meta() if hpool is not None else {},
                          mirror_stats=m_stats.to_meta() if mpool is not None else {},
                          seconds=round(time.time() - t0, 1))
    if audits:
        stats["audit_games"] = [int(a["game_index"]) for a in audits]
        stats["audit_problems"] = int(sum(len(a.get("problems") or []) for a in audits))
    return ProblemCollectResult(problems=problems, stats=stats, audits=audits)


def problem_stats(problems: Sequence[Mapping[str, Any]], *,
                  cfg: Optional[ProblemCollectConfig] = None,
                  per_game: Optional[Sequence[Mapping[str, Any]]] = None,
                  skipped: Optional[Mapping[str, int]] = None,
                  decisions: int = 0,
                  human_stats: Optional[Mapping[str, Any]] = None,
                  mirror_stats: Optional[Mapping[str, Any]] = None,
                  seconds: float = 0.0) -> Dict[str, Any]:
    """题目统计：题目数、覆盖 turn、匹配率、缺失率、标签分布、Move 守卫。

    匹配率口径（分母 = 题目数）：``ref_matched`` = 有合法参考解的题；``ref_level_*``
    是匹配层级分布（``turn_tier`` 最具体）；``ref_mass_legal`` 是参考解里**合法且
    未被 Move 守卫过滤**的质量占比（中位）。
    """
    n = len(problems)
    by_turn: Dict[str, int] = {}
    by_tag: Dict[str, int] = {}
    lv: Dict[str, int] = {}
    floors: Dict[str, int] = {}
    for r in problems:
        by_turn[str(int(r.get("turn") or 0))] = by_turn.get(
            str(int(r.get("turn") or 0)), 0) + 1
        for t in (r.get("tags") or []):
            by_tag[str(t)] = by_tag.get(str(t), 0) + 1
        ref = r.get("ref") or {}
        key = str(ref.get("level") or "none")
        lv[key] = lv.get(key, 0) + 1
        floors[str(int(ref.get("floor") or 0))] = floors.get(
            str(int(ref.get("floor") or 0)), 0) + 1
    matched = sum(1 for r in problems if bool((r.get("ref") or {}).get("matched")))
    mass = [float((r.get("ref") or {}).get("mass_legal") or 0.0)
            for r in problems if bool((r.get("ref") or {}).get("matched"))]
    top1_hit = sum(1 for r in problems
                   if bool((r.get("ref") or {}).get("matched"))
                   and int((r.get("ref") or {}).get("actions", [0])[0]) ==
                   int(r.get("policy_action") or -1))
    sa = [float((r.get("label") or {}).get("strength_after_t3") or 0.0)
          for r in problems if int((r.get("label") or {}).get("available", 1))]
    # z-score 口径：只用 **t+3 前存活** 的题（出局的题用最后可见值，尺度不可比）
    sa_surv = [float((r.get("label") or {}).get("strength_after_t3") or 0.0)
               for r in problems
               if int((r.get("label") or {}).get("available", 1))
               and int((r.get("label") or {}).get("survived", 1))]
    sb = [float((r.get("label") or {}).get("strength_before") or 0.0)
          for r in problems]
    tier_up = [int((r.get("label") or {}).get("tier_up") or 0) for r in problems]
    survived = [int((r.get("label") or {}).get("survived") or 0) for r in problems]
    # --min-delta / --focus-turns 的口径：每题显式的 strength_delta + 后期回合覆盖
    sdel = np.asarray([problem_strength_delta(r) for r in problems],
                      dtype=np.float64)
    sdel = sdel[np.isfinite(sdel)]
    late_turns = [int(t) for t in (r.get("turn") or 0 for r in problems)]
    late_n = int(sum(1 for t in late_turns if t >= LATE_TURN_MIN))
    _d = (np.log1p(np.maximum(np.asarray(
        [float((r.get("label") or {}).get("strength_after_t3") or 0.0)
         for r in problems], dtype=np.float64), 0.0))
        - np.log1p(np.maximum(np.asarray(sb, dtype=np.float64), 0.0)))
    _ds = _d[np.asarray(survived, dtype=bool)] if survived else _d
    logs = _ds if _ds.size else _d
    strength_norm = {
        "mean": float(logs.mean()) if logs.size else 0.0,
        "std": float(logs.std()) if logs.size and float(logs.std()) > 0 else 1.0,
        "source": "problems_survived", "target": "delta_log1p",
    }
    move_counts = [int((r.get("move") or {}).get("n") or 0) for r in problems]
    cfgd = {}
    if cfg is not None:
        cfgd = {k: v for k, v in cfg.__dict__.items()}
    return {
        "schema": PROBLEM_SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "problems": int(n),
        "decisions": int(decisions),
        "seconds": float(seconds),
        "by_turn": dict(sorted(by_turn.items(), key=lambda kv: int(kv[0]))),
        "turn_min": (min((int(k) for k in by_turn), default=0)),
        "turn_max": (max((int(k) for k in by_turn), default=0)),
        "by_tag": dict(sorted(by_tag.items())),
        "ref_matched": int(matched),
        "ref_match_rate": (float(matched) / n if n else 0.0),
        "ref_missing": int(n - matched),
        "ref_missing_rate": (float(n - matched) / n if n else 0.0),
        "ref_level": dict(sorted(lv.items())),
        "ref_floor": dict(sorted(floors.items())),
        "ref_mass_legal_p50": (float(np.percentile(mass, 50)) if mass else 0.0),
        "ref_mass_legal_mean": (float(np.mean(mass)) if mass else 0.0),
        "policy_top1_in_ref": int(top1_hit),
        "policy_top1_in_ref_rate": (float(top1_hit) / n if n else 0.0),
        "label_available": int(len(sa)),
        "label_missing": int(n - len(sa)),
        "label_survived": int(len(sa_surv)),
        "label_terminal": int(len(sa) - len(sa_surv)),
        "label_survived_rate": (float(np.mean(survived)) if survived else 0.0),
        "tier_up_rate": (float(np.mean(tier_up)) if tier_up else 0.0),
        "strength_before_p50": (float(np.percentile(sb, 50)) if sb else 0.0),
        "strength_after_p50": (float(np.percentile(sa, 50)) if sa else 0.0),
        "strength_norm": strength_norm,
        "strength_delta_log1p_p50": float(np.percentile(_ds, 50)) if _ds.size else 0.0,
        # 出题期开关（--focus-turns / --min-delta）的口径：delta 分布 + 后期覆盖
        "strength_delta_p50": float(np.percentile(sdel, 50)) if sdel.size else 0.0,
        "strength_delta_p90": float(np.percentile(sdel, 90)) if sdel.size else 0.0,
        "strength_delta_mean": float(sdel.mean()) if sdel.size else 0.0,
        "late_turn_min": int(LATE_TURN_MIN),
        "late_turn_problems": int(late_n),
        "late_turn_by_turn": {str(t): int(sum(1 for x in late_turns if x == t))
                              for t in sorted({x for x in late_turns
                                               if x >= LATE_TURN_MIN})},
        "move_n_p50": (float(np.percentile(move_counts, 50)) if move_counts else 0.0),
        "move_n_max": int(max(move_counts)) if move_counts else 0,
        "skipped": dict(skipped or {}),
        "per_game": list(per_game or []),
        "human_board": dict(human_stats or {}),
        "mirror": dict(mirror_stats or {}),
        "config": cfgd,
    }


def write_problems(result: ProblemCollectResult, path: str = DEFAULT_PROBLEM_PATH,
                   meta_path: Optional[str] = None) -> Tuple[str, str]:
    """把题目写成 ``problems.jsonl`` + ``problems.meta.json``；返回两个路径。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in result.problems:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)
    mp = meta_path or (os.path.splitext(path)[0] + ".meta.json")
    meta = dict(result.stats)
    meta.setdefault("schema", PROBLEM_SCHEMA_VERSION)
    meta["problems_path"] = str(path)
    meta["problems_sha256"] = _file_sha256(path)
    os.makedirs(os.path.dirname(os.path.abspath(mp)) or ".", exist_ok=True)
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return path, mp


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


__all__ = [
    "PROBLEM_SCHEMA_VERSION", "DEFAULT_PROBLEM_PATH", "DEFAULT_PROBLEM_META",
    "DEFAULT_BC_SAMPLES", "DEFAULT_HORIZON",
    "TAG_TURN_START", "TAG_UPGRADE_READY", "TAG_TRIPLE_READY", "TAG_CORE_CARD",
    "FORK_TAGS", "ALL_TAGS", "REF_TYPES", "DEFAULT_REF_FLOORS",
    "OBS_STRENGTH_SCALE",
    "tier_from_features", "gold_from_features", "turn_from_features",
    "shop_phase_from_features",
    "board_strength_from_features", "board_card_ids", "shop_card_ids",
    "hand_card_ids", "fork_tags", "obs_sha256", "encode_obs", "decode_obs",
    "apply_move_guard",
    "ReferenceTable", "build_reference_table", "match_reference_actions",
    "REF_LEVELS",
    "DEFAULT_FIRESTONE_ACTIONS", "REF_CARD_KINDS", "ref_action_kind",
    "ref_action_card", "HumanBuyTable", "build_human_buy_table",
    "LateRefConfig", "reweight_reference_candidates", "rewrite_problem_rows",
    "ref_type_distribution", "REF_KINDS",
    "BoardProblemPool", "BoardProblemBatch", "load_problem_pool",
    "problem_obs_batch", "problem_bc_soft_ce", "strength_aux_loss",
    "fit_strength_head",
    "LATE_TURN_MIN", "DEFAULT_TURN_WEIGHT", "parse_turn_weights",
    "format_turn_weights", "parse_turn_ranges", "parse_game_indices",
    "turn_in_focus",
    "problem_strength_delta", "turn_weight_vector", "filter_problem_rows",
    "denormalize_strength", "strength_after_from_delta",
    "ProblemCollectConfig", "ProblemCollectResult", "collect_problems",
    "problem_stats", "write_problems",
]
