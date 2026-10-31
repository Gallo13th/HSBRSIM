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
   top-k + 强度/等级标签；
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
    # 层级优先、MMR 阶梯其次：先用最具体的层级在任一分段里找够支撑的桶。
    for lv in REF_LEVELS:
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
    return {"actions": [int(a) for a in top], "weights": weights,
            "matched": True, "level": level, "floor": floor,
            "support": support, "mass_legal": mass / max(total, 1e-9),
            "reason": "ok"}


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

    def __len__(self) -> int:
        return int(self.turn.shape[0])

    def summary(self) -> Dict[str, Any]:
        """池摘要（不含量大的数组；进启动日志 / summary.json）。"""
        n = len(self)
        if n == 0:
            return {"path": self.path, "problems": 0}
        by_turn: Dict[str, int] = {}
        for t in self.turn.tolist():
            by_turn[str(int(t))] = by_turn.get(str(int(t)), 0) + 1
        by_tag: Dict[str, int] = {t: 0 for t in ALL_TAGS}
        for tags in self.tags:
            for t in tags:
                by_tag[t] = by_tag.get(t, 0) + 1
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
                      limit: Optional[int] = None) -> BoardProblemPool:
    """读 ``problems.jsonl``（+ 可选 ``problems.meta.json``）-> :class:`BoardProblemPool`。

    ``problems.meta.json`` 里有 ``strength_norm``（z-score 的 mean/std）；缺失时用池内
    数据现算。文件不存在 / 全被过滤时返回**空池**（训练入口据此自动关闭系数）。
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
            aux_valid=np.zeros(0, bool), tags=[], path=str(path), meta=meta)
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
        norm=norm, meta=meta, path=str(path))


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
    return BoardProblemBatch(
        features=feats, cards=cards, mask=masks, soft=soft,
        bc_valid=bc_valid, strength_target=pool.strength_target[idx].copy(),
        tier_target=pool.tier_up[idx].astype(np.float32),
        aux_valid=aux_valid, ref_top1=top1,
        policy_action=pool.policy_action[idx].copy())


# ══════════════════════════════════════════════════════════════════════════
# 5. 损失
# ══════════════════════════════════════════════════════════════════════════
def problem_bc_soft_ce(logits: Any, batch: BoardProblemBatch) -> Dict[str, Any]:
    """题目状态上的 soft-label 交叉熵（``-Σ_k q_k log p_k``，只在合法动作上）。

    返回 ``{"loss", "top1_acc", "policy_in_ref", "n"}``；``top1_acc`` = 策略 argmax
    命中参考解 top-1 的比例，``policy_in_ref`` = 当前采集动作落在参考解 top-k 的比例
    （0 阶诊断，不参与梯度）。无有效行时 ``loss`` 为 0（不制造假梯度）。
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
                "policy_in_ref": zero.detach(), "n": 0}
    loss = ce_all[valid].mean()
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
                "n": int(valid.sum().item())}


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


@dataclass
class ProblemCollectResult:
    """出题结果：题目行 + 统计 + rollout 元信息。"""

    problems: List[Dict[str, Any]]
    stats: Dict[str, Any]

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
               "no_supervisable": 0, "min_turn": 0}
    n_decisions = 0
    t0 = time.time()
    for gi in range(games):
        gseed = int(cfg.seed) + gi
        game = E.Game(seed=gseed)
        policy.reset()
        policy.reseed(gseed * 7919 + 1)
        hrng = random.Random(gseed * 53 + 11)
        mrng = random.Random(gseed * 31 + 7)
        cur_turn = -1
        turn_rows: Dict[int, Dict[str, Any]] = {}
        pending: List[Dict[str, Any]] = []
        move_last, move_counts, move_n = -1, {}, 0
        dec_in_turn = 0
        fork_in_turn = 0
        m_used_seats: List[int] = []
        steps = 0
        def _new_turn(t: int) -> None:
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
                    _new_turn(cur_turn)
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
            lab = {"strength_before": s0,
                   "strength_after_t3": s3,
                   "delta": s3 - s0,
                   "delta_log1p": float(math.log1p(max(s3, 0.0))
                                        - math.log1p(max(s0, 0.0))),
                   "tier_before": tier0, "tier_after": tier3,
                   "tier_up": int(tier3 >= tier0 + 1),
                   "survived": int(survived), "terminal": int(not survived),
                   "available": 1, "horizon": horizon,
                   "target_turn": int(T + horizon)}
            ref = {"actions": [], "weights": []}
            if reference is not None:
                ref = match_reference_actions(
                    snap["features"], snap["cards"], snap["mask"], reference,
                    top_k=int(top_k), min_support=int(min_support),
                    exclude_move=True,
                    move_last=int(snap["move"]["last"]),
                    move_counts={int(k): int(v)
                                 for k, v in snap["move"]["counts"]},
                    move_n=int(snap["move"]["n"]),
                    cap=int(cfg.move_cap),
                    repeat_limit=int(cfg.move_repeat_limit))
                if not bool(ref.get("matched")):
                    skipped["no_ref"] += 1
            pid = f"bp-{len(problems):06d}"
            problems.append({
                "problem_id": pid,
                "schema": PROBLEM_SCHEMA_VERSION,
                "source_group": f"rollout:seed={int(cfg.seed)}:game={gi}",
                "game_seed": gseed, "turn": T, "seat": seat,
                "decision_idx": int(snap["decision_idx"]),
                "tags": list(snap["tags"]),
                "obs": encode_obs(snap["features"], snap["cards"], snap["mask"],
                                  dtype=str(cfg.obs_dtype)),
                "state": dict(snap["state"]),
                "policy_action": int(snap["policy_action"]),
                "policy_prob": float(snap["policy_prob"]),
                "ref": dict(ref, reason=str(ref.get("reason", ""))),
                "label": lab,
                "move": dict(snap["move"]),
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
    return ProblemCollectResult(problems=problems, stats=stats)


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
    "BoardProblemPool", "BoardProblemBatch", "load_problem_pool",
    "problem_obs_batch", "problem_bc_soft_ce", "strength_aux_loss",
    "fit_strength_head",
    "denormalize_strength", "strength_after_from_delta",
    "ProblemCollectConfig", "ProblemCollectResult", "collect_problems",
    "problem_stats", "write_problems",
]
