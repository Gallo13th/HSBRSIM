#!/usr/bin/env python3
"""流派（archetype）分类器 + 动作偏好表构建（Firestone 动作日志 → 上线制品）。

产物
====

- ``data/archetype/archetype_model.npz``：两段式分类器权重
  （种族族 softmax + 头部流派 softmax，尾部合并 ``other``）；
- ``data/archetype/archetype_table.json``：每流派的**动作偏好表**（按 turn 分桶：
  买哪些卡 / 何时升 tier / 何时 reroll / 战团种族构成）+ 全局基线（用于算相对增益）；
- ``data/archetype/archetype_metrics.json``：分组交叉验证指标 + 标签分布（写进
  ``docs/ARCHETYPE_BIAS.md`` 的数字来源）。

特征口径（训练 = 推理）
=======================

特征**只用本座位可见信息 + 公共信息**，并且逐动作回放 Firestone 日志，
复用 ``hsbg.az.train.archetype_bias`` 的 :class:`ArchetypeHistory` /
:func:`build_vector` —— 训练与线上推理共用同一份代码，避免两侧漂移。

每个有标签的对局在 **turn 起点**取一个前缀样本（turn 1..最后一回合），
因此同一个 game 会贡献多个样本但**只有一个标签**；交叉验证按 ``game_id`` 分组，
同一个 game 的前缀样本绝不跨折（无泄漏）。这条前缀口径与线上「第 t 回合开始时
做检测」严格一致。

两段式
======

1. **种族族**（archetype 名第一段，如 ``mech_apm → mech``）：全部样本都参与训练，
   大类样本多、top-1/top-3 高；
2. **头部流派**：支持数 ``>= --min-games`` 的流派作为类别，其余合并成 ``other``。
   推理时：流派类概率达标且不是 ``other`` → 用流派级偏好表；否则退回第 1 段的
   种族族级偏好表（粗粒度但覆盖全）。见 ``hsbg/az/train/archetype_bias.py``。

用法::

    python scripts/build_archetype_table.py
    python scripts/build_archetype_table.py --min-games 8 --folds 5 --no-hero
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.archetype_bias import (  # noqa: E402
    ACTION_TYPES,
    AFF_SCALE,
    ArchetypeHistory,
    ArchetypeObs,
    FEATURE_BLOCKS,
    FEATURE_DIM,
    FEATURE_VERSION,
    HERO_VOCAB_SIZE,
    N_BUCKETS,
    N_TRIBES,
    RHYTHM_TYPES,
    SoftmaxModel,
    TRIBES,
    TURN_BUCKETS,
    bucket_key,
    bucket_of,
    build_vector,
    parse_obs,
    save_model,
)

DEFAULT_ACTIONS = os.path.join(ROOT, "data/firestone_replays/firestone_recent_actions.jsonl.gz")
DEFAULT_LIBRARY = os.path.join(ROOT, "data/real_library/library_firestone_recent.jsonl")
DEFAULT_CARDS = os.path.join(ROOT, "rust/crates/hsbg-engine/data/cards.json")
DEFAULT_TABLE = os.path.join(ROOT, "data/archetype/archetype_table.json")
DEFAULT_MODEL = os.path.join(ROOT, "data/archetype/archetype_model.npz")
DEFAULT_METRICS = os.path.join(ROOT, "data/archetype/archetype_metrics.json")

SCHEMA = "hsbg.archetype_table"
SCHEMA_VERSION = 1
#: 偏好表狄利克雷平滑（伪计数）：小样本流派的 rate/tribe 分布向基线收缩。
RATE_ALPHA = 8.0
TRIBE_ALPHA = 5.0
#: top_cards 保留条数 / 最低 share。
TOP_CARDS = 10
CARD_MIN_SHARE = 0.01
#: 表里逐桶输出的动作类型（偏好 + 基线同序）
_RATE_KEYS = ("buy_minion", "buy_spell", "play_minion", "play_spell", "sell",
              "reroll", "freeze", "upgrade", "hero_power", "dark_gift", "end_turn")


# ══════════════════════════════════════════════════════════════════════════
# 数据读取
# ══════════════════════════════════════════════════════════════════════════
def load_library(path: str) -> Dict[str, Dict[str, Any]]:
    """``game_id -> {archetype, hero, lobby, mmr, placement}``（每局首个有标签帧）。"""
    out: Dict[str, Dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gid = str(row.get("game_id") or "")
            if not gid:
                continue
            cur = out.setdefault(gid, {"archetype": "", "hero": "", "lobby": None,
                                       "mmr": None, "placement": None})
            arch = row.get("archetype")
            if arch and not cur["archetype"]:
                cur["archetype"] = str(arch)
            hero = row.get("hero_card_id")
            if hero and not cur["hero"]:
                cur["hero"] = str(hero)
            tribes = row.get("tribes")
            if tribes and cur["lobby"] is None:
                cur["lobby"] = [str(t) for t in tribes]
            if cur["mmr"] is None and row.get("mmr") is not None:
                cur["mmr"] = row.get("mmr")
            if cur["placement"] is None and row.get("placement") is not None:
                cur["placement"] = row.get("placement")
    return out


def load_cards(path: str) -> Dict[str, Dict[str, Any]]:
    """``card_id -> {races, is_minion}``（tribes 顺序按 :data:`TRIBES`）。"""
    data = json.load(open(path, encoding="utf-8"))
    cards = data.get("cards") if isinstance(data, dict) else data
    out: Dict[str, Dict[str, Any]] = {}
    for c in cards or []:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        races = [str(x).upper() for x in (c.get("races") or [])]
        kind = str(c.get("kind") or "")
        out[cid] = {"races": races, "is_minion": kind == "minion", "kind": kind}
    return out


def load_game_actions(path: str,
                      games: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    """流式读 gz，只保留 ``games`` 的对局动作（保持文件内时间顺序）。"""
    keep = set(str(g) for g in games)
    out: Dict[str, List[Dict[str, Any]]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gid = str(row.get("game_id") or "")
            if gid not in keep:
                continue
            out.setdefault(gid, []).append(row)
    return out


# ══════════════════════════════════════════════════════════════════════════
# 动作行 → ArchetypeObs（**与线上 parse_obs 同语义**，只是数据源换成人日志）
# ══════════════════════════════════════════════════════════════════════════
def tribe_vector(ids: Sequence[str], cards: Dict[str, Dict[str, Any]]) -> np.ndarray:
    """卡 id 列表 → 种族计数（未识别/无种族忽略；返回未归一化计数）。"""
    v = np.zeros(N_TRIBES, dtype=np.float32)
    for cid in ids:
        info = cards.get(str(cid))
        if not info:
            continue
        for r in info.get("races") or []:
            if r in TRIBES:
                v[TRIBES.index(r)] += 1.0
    return v


def lobby_bits(lobby: Optional[Sequence[str]]) -> np.ndarray:
    """可用种族列表 → 11 维 one-hot（公共信息，开局即知）。"""
    v = np.zeros(N_TRIBES, dtype=np.float32)
    for r in lobby or []:
        r = str(r).upper()
        if r in TRIBES:
            v[TRIBES.index(r)] = 1.0
    return v


def obs_from_row(row: Dict[str, Any], cards: Dict[str, Dict[str, Any]], *,
                 lobby: Sequence[str], hero: str) -> ArchetypeObs:
    """一条动作记录 → :class:`ArchetypeObs`（只用该行里对局玩家可见的字段）。"""
    shop = [str(x) for x in (row.get("shop_cards") or [])]
    hand = [str(x) for x in (row.get("hand_cards") or [])]
    board = [str(x) for x in (row.get("board_cards") or [])]
    shop_t = np.zeros((8, N_TRIBES), dtype=np.float32)
    shop_m = np.zeros((8,), dtype=bool)
    shop_p = np.zeros((8,), dtype=bool)
    for i, cid in enumerate(shop[:8]):
        info = cards.get(cid)
        shop_p[i] = True
        if info and info["is_minion"]:
            shop_m[i] = True
            for r in info["races"]:
                if r in TRIBES:
                    shop_t[i, TRIBES.index(r)] = 1.0
    hand_t = np.zeros((10, N_TRIBES), dtype=np.float32)
    hand_m = np.zeros((10,), dtype=bool)
    hand_p = np.zeros((10,), dtype=bool)
    for i, cid in enumerate(hand[:10]):
        info = cards.get(cid)
        hand_p[i] = True
        if info and info["is_minion"]:
            hand_m[i] = True
            for r in info["races"]:
                if r in TRIBES:
                    hand_t[i, TRIBES.index(r)] = 1.0
    board_t = tribe_vector(board, cards)
    tot = float(board_t.sum())
    if tot > 0:
        board_t = board_t / tot
    return ArchetypeObs(
        turn=int(row.get("turn") or 0), tier=int(row.get("tier") or 0),
        gold=float(row.get("gold") or 0.0), lobby=lobby_bits(lobby),
        board_tribes=board_t, shop_tribes=shop_t, shop_minion=shop_m,
        shop_present=shop_p, hand_tribes=hand_t, hand_minion=hand_m,
        hand_present=hand_p, hero_id=str(hero or ""))


def action_index_of(row: Dict[str, Any]) -> int:
    """动作行 → 引擎动作下标（缺 ``action_index`` 时按类型/槽位重建）。"""
    ai = row.get("action_index")
    if ai is not None:
        try:
            return int(ai)
        except (TypeError, ValueError):
            pass
    at = str(row.get("action_type") or "")
    base = {"end_turn": 0, "reroll": 1, "refresh": 1, "freeze": 2, "upgrade": 3,
            "hero_power": 4, "dark_gift": 6, "buy_minion": 8, "buy_spell": 8,
            "sell": 16, "play_minion": 46, "play_spell": 46, "magnetize": 126}.get(at)
    if base is None:
        return 0
    slot = row.get("shop_slot") if base == 8 else (
        row.get("board_slot") if base in (16, 23) else (
            row.get("hand_slot") if base in (46, 126) else None))
    if slot is None:
        return base
    try:
        s = int(slot)
    except (TypeError, ValueError):
        return base
    if base == 46:
        pos = row.get("play_pos")
        pos = 0 if pos is None else int(pos)
        return 46 + s * 8 + pos
    return base + s


# ══════════════════════════════════════════════════════════════════════════
# 前缀样本（训练集）
# ══════════════════════════════════════════════════════════════════════════
def build_prefix_samples(games: Dict[str, List[Dict[str, Any]]],
                         lib: Dict[str, Dict[str, Any]],
                         cards: Dict[str, Dict[str, Any]],
                         *, hero_vocab: Sequence[str] = (),
                         max_turn: int = 15) -> Dict[str, Any]:
    """逐局回放 → (X, game_ids, archetypes, heroes, n_cuts)。

    每个 turn 起点一个样本（用该回合第一条动作行构造 obs），样本特征只包含
    **该回合之前**的己方动作历史，因此与线上「第 t 回合开始时检测」一致。
    """
    X: List[np.ndarray] = []
    gids: List[str] = []
    arch: List[str] = []
    turns: List[int] = []
    heroes: List[str] = []
    skipped = 0
    for gid in sorted(games):
        rows = games[gid]
        info = lib.get(gid) or {}
        label = str(info.get("archetype") or "")
        if not label:
            continue
        hero = str(info.get("hero") or "")
        lobby = info.get("lobby") or []
        hist = ArchetypeHistory()
        # 按 turn 分组（文件顺序即时间顺序）
        cur_turn = None
        last_snapshot_turn = -1
        for row in rows:
            turn = int(row.get("turn") or 0)
            if turn <= 0:
                continue
            if turn != cur_turn:
                cur_turn = turn
                if turn <= int(max_turn) and turn > last_snapshot_turn:
                    obs = obs_from_row(row, cards, lobby=lobby, hero=hero)
                    x = build_vector(hist._get(gid, 0), obs, hero_vocab=hero_vocab)
                    X.append(x)
                    gids.append(gid)
                    arch.append(label)
                    turns.append(turn)
                    heroes.append(hero)
                    last_snapshot_turn = turn
            obs = obs_from_row(row, cards, lobby=lobby, hero=hero)
            hist.observe(gid, 0, obs)
            hist.note_action(gid, 0, action_index_of(row))
    if not X:
        raise RuntimeError("没有可用样本：检查 actions / library 路径与标签")
    return {"X": np.asarray(X, dtype=np.float32), "games": gids,
            "archetype": arch, "turn": turns, "hero": heroes,
            "skipped_games": int(skipped)}


# ══════════════════════════════════════════════════════════════════════════
# 偏好表（每流派 × turn 分桶）
# ══════════════════════════════════════════════════════════════════════════
class _Agg:
    """一个分组（流派 / 种族族 / 全局基线）在某个 turn 分桶上的计数。"""

    def __init__(self) -> None:
        self.n = 0                                     # 计入的决策数
        self.turns = 0                                 # 计入的 (game, turn) 数
        self.types: Dict[str, int] = collections.Counter()
        self.buy_tribe: np.ndarray = np.zeros(N_TRIBES, dtype=np.float64)
        self.board_tribe: np.ndarray = np.zeros(N_TRIBES, dtype=np.float64)
        self.buy_cards: Dict[str, int] = collections.Counter()
        self.buy_minion_n = 0

    def add(self, other: "_Agg") -> None:
        self.n += other.n
        self.turns += other.turns
        for k, v in other.types.items():
            self.types[k] += int(v)
        self.buy_tribe += other.buy_tribe
        self.board_tribe += other.board_tribe
        for k, v in other.buy_cards.items():
            self.buy_cards[k] += int(v)
        self.buy_minion_n += other.buy_minion_n


def _per_turn_from(agg: _Agg, base: Optional[Dict[str, float]] = None,
                   alpha: float = 0.0) -> Dict[str, float]:
    """计数 → **每回合** rate（比逐决策 rate 更能体现「何时升 tier/reroll」）。"""
    nt = int(agg.turns)
    out: Dict[str, float] = {}
    for t in ACTION_TYPES:
        k = float(agg.types.get(t, 0))
        if alpha > 0.0 and base is not None:
            out[t] = round(float((k + alpha * float(base.get(t, 0.0)))
                                 / (nt + alpha)), 6)
        else:
            out[t] = round(float((k / nt) if nt > 0 else 0.0), 6)
    return out


def _rates_from(agg: _Agg, base: Optional[Dict[str, float]] = None,
                alpha: float = 0.0) -> Dict[str, float]:
    """计数 → 逐决策 rate（可选向 ``base`` 做伪计数平滑）。"""
    n = int(agg.n)
    out: Dict[str, float] = {}
    for t in ACTION_TYPES:
        k = float(agg.types.get(t, 0))
        if alpha > 0.0 and base is not None:
            r = (k + alpha * float(base.get(t, 0.0))) / (n + alpha)
        else:
            r = (k / n) if n > 0 else 0.0
        out[t] = round(float(r), 6)
    return out


def _dist_from(counts: np.ndarray, base: Optional[np.ndarray] = None,
               alpha: float = 0.0) -> Dict[str, float]:
    """种族计数 → 归一化分布（可选向 ``base`` 平滑）。"""
    c = np.asarray(counts, dtype=np.float64).copy()
    if alpha > 0.0 and base is not None:
        c = c + alpha * np.asarray(base, dtype=np.float64)
    tot = float(c.sum())
    if tot <= 0:
        return {}
    return {t: round(float(c[i] / tot), 6) for i, t in enumerate(TRIBES)
            if float(c[i]) > 0.0}


def _subset(base: Dict[str, Any], keys: Sequence[str]) -> Dict[str, float]:
    return {k: float(base.get(k, 0.0) or 0.0) for k in keys}


def build_preference_table(games: Dict[str, List[Dict[str, Any]]],
                           lib: Dict[str, Dict[str, Any]],
                           cards: Dict[str, Dict[str, Any]],
                           *, head_archetypes: Sequence[str]) -> Dict[str, Any]:
    """统计 流派 / 种族族 / 基线 的逐分桶动作偏好（带狄利克雷平滑）。"""
    bufs: Dict[str, Dict[str, _Agg]] = {"archetypes": {}, "tribes": {}}
    base: Dict[str, _Agg] = {}
    base_all = _Agg()
    # 第一遍：原始计数（每条动作行同时累加到 基线 / 流派 / 种族族 三个层级）
    for gid in sorted(games):
        info = lib.get(gid) or {}
        label = str(info.get("archetype") or "")
        if not label:
            continue
        family = label.split("_", 1)[0]
        last_turn = None
        for row in games[gid]:
            turn = int(row.get("turn") or 0)
            if turn <= 0:
                continue
            b = bucket_key(bucket_of(turn))
            new_turn = (turn != last_turn)
            last_turn = turn
            at = str(row.get("action_type") or "")
            if at not in ACTION_TYPES:
                continue
            adders = [base.setdefault(b, _Agg()), base_all]
            for buf, key in ((bufs["archetypes"], label), (bufs["tribes"], family)):
                adders.append(buf.setdefault(key, {}).setdefault(b, _Agg()))
            board_ids = [str(x) for x in (row.get("board_cards") or [])]
            board_t = tribe_vector(board_ids, cards).astype(np.float64)
            buy_t = np.zeros(N_TRIBES, dtype=np.float64)
            cid = row.get("card_id")
            if at == "buy_minion" and isinstance(cid, str) and cid:
                buy_t = tribe_vector([cid], cards).astype(np.float64)
            for agg in adders:
                agg.n += 1
                if new_turn:
                    agg.turns += 1
                agg.types[at] += 1
                agg.board_tribe += board_t
                if at == "buy_minion":
                    agg.buy_minion_n += 1
                    agg.buy_tribe += buy_t
                    if isinstance(cid, str) and cid:
                        agg.buy_cards[cid] += 1
    # 补齐：每个流派 / 种族族都要有全部桶键（缺桶 → 平滑后≈基线）
    for buf in bufs.values():
        for node in buf.values():
            for b in [bucket_key(i) for i in range(N_BUCKETS)]:
                node.setdefault(b, _Agg())
    # 基线（含 all 桶）
    base_rates: Dict[str, Dict[str, float]] = {}
    base_turns: Dict[str, Dict[str, float]] = {}
    base_buy: Dict[str, Dict[str, float]] = {}
    for b in [bucket_key(i) for i in range(N_BUCKETS)] + ["all"]:
        agg = base_all if b == "all" else (base.get(b) or _Agg())
        base_rates[b] = _rates_from(agg)
        base_turns[b] = _per_turn_from(agg)
        buy = _dist_from(agg.buy_tribe)
        base_buy[b] = buy
    base_board = {b: (_dist_from((base_all if b == "all" else (base.get(b) or _Agg()))
                                 .board_tribe)) for b in base_rates}

    def _node(buf: Dict[str, Dict[str, _Agg]], name: str,
              extra: Dict[str, Any]) -> Dict[str, Any]:
        node: Dict[str, Any] = dict(extra)
        pref: Dict[str, Any] = {}
        all_agg = _Agg()
        for b in [bucket_key(i) for i in range(N_BUCKETS)]:
            agg = buf.get(name, {}).get(b, _Agg())
            all_agg.add(agg)
            rates = _rates_from(agg, base_rates.get(b), RATE_ALPHA)
            turns_rate = _per_turn_from(agg, base_turns.get(b), RATE_ALPHA)
            top = _top_cards(agg)
            pref[b] = {
                "n": int(agg.n),
                "turns": int(agg.turns),
                "rate_keys": list(_RATE_KEYS),
                "rates": {k: rates[k] for k in _RATE_KEYS},
                "per_turn": {k: turns_rate[k] for k in _RATE_KEYS},
                "buy_tribe": _smooth_dist(agg.buy_tribe, base_buy.get(b) or {},
                                          TRIBE_ALPHA),
                "board_tribe": _smooth_dist(agg.board_tribe, base_board.get(b) or {},
                                            TRIBE_ALPHA),
                "top_cards": top,
            }
        # all 桶：跨桶合并，桶回退用
        rates_all = _rates_from(all_agg, base_rates.get("all"), RATE_ALPHA)
        pref["all"] = {
            "n": int(all_agg.n),
            "turns": int(all_agg.turns),
            "rate_keys": list(_RATE_KEYS),
            "rates": rates_all,
            "per_turn": _per_turn_from(all_agg, base_turns.get("all"), RATE_ALPHA),
            "buy_tribe": _smooth_dist(all_agg.buy_tribe, base_buy.get("all") or {},
                                      TRIBE_ALPHA),
            "board_tribe": _smooth_dist(all_agg.board_tribe,
                                        base_board.get("all") or {}, TRIBE_ALPHA),
            "top_cards": _top_cards(all_agg),
        }
        node["pref"] = pref
        return node

    arch_out: Dict[str, Any] = {}
    support = collections.Counter()
    for gid in games:
        info = lib.get(gid) or {}
        if info.get("archetype"):
            support[str(info["archetype"])] += 1
    for name in sorted(set(list(bufs["archetypes"].keys()) + list(head_archetypes))):
        arch_out[name] = _node(bufs["archetypes"], name, {
            "support": int(support.get(name, 0)),
            "tribe_family": name.split("_", 1)[0],
            "head": bool(name in set(head_archetypes)),
        })
    tribe_out: Dict[str, Any] = {}
    tribe_support = collections.Counter()
    for gid in games:
        info = lib.get(gid) or {}
        if info.get("archetype"):
            tribe_support[str(info["archetype"]).split("_", 1)[0]] += 1
    for name in sorted(bufs["tribes"].keys()):
        tribe_out[name] = _node(bufs["tribes"], name, {
            "support": int(tribe_support.get(name, 0)),
        })
    return {
        "baseline": {b: {"n": int((base_all if b == "all" else (base.get(b) or _Agg())).n),
                         "turns": int((base_all if b == "all"
                                       else (base.get(b) or _Agg())).turns),
                         "rate_keys": list(_RATE_KEYS),
                         "rates": base_rates[b], "per_turn": base_turns[b],
                         "buy_tribe": base_buy[b],
                         "board_tribe": base_board[b]}
                     for b in base_rates},
        "archetypes": arch_out,
        "tribes": tribe_out,
        "support": dict(sorted(support.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def _smooth_dist(counts: Any, base: Dict[str, float], alpha: float
                 ) -> Dict[str, float]:
    """种族分布平滑：``(count + alpha*base)/(tot + alpha)``；空计数返回基线。"""
    c = np.asarray(counts, dtype=np.float64)
    tot = float(c.sum())
    if tot <= 0.0:
        return {k: round(float(v), 6) for k, v in (base or {}).items()}
    b = np.asarray([float((base or {}).get(t, 0.0) or 0.0) for t in TRIBES],
                   dtype=np.float64)
    c = c + alpha * b
    tot2 = float(c.sum())
    if tot2 <= 0.0:
        return {}
    return {t: round(float(c[i] / tot2), 6) for i, t in enumerate(TRIBES)
            if float(c[i]) > 0.0}


def _top_cards(agg: _Agg) -> Dict[str, float]:
    """高频购买卡（share over buy_minion；只留 share >= 阈值的前 N 张）。"""
    tot = float(sum(agg.buy_cards.values()))
    if tot <= 0:
        return {}
    rows = sorted(agg.buy_cards.items(), key=lambda kv: (-kv[1], kv[0]))
    out: Dict[str, float] = {}
    for cid, n in rows[:TOP_CARDS]:
        share = float(n) / tot
        if share >= CARD_MIN_SHARE:
            out[str(cid)] = round(share, 6)
    return out


# ══════════════════════════════════════════════════════════════════════════
# numpy softmax 回归（无 sklearn 依赖）
# ══════════════════════════════════════════════════════════════════════════
def fit_softmax(X: np.ndarray, y: np.ndarray, n_classes: int, *,
                l2: float = 0.03, epochs: int = 800, lr: float = 0.08,
                class_weight: bool = False, seed: int = 0) -> Tuple[np.ndarray,
                                                                    np.ndarray]:
    """全批 Adam 训练线性 softmax；返回 ``(W[D,C], b[C])``。"""
    rng = np.random.default_rng(int(seed))
    n, d = X.shape
    Y = np.zeros((n, n_classes), dtype=np.float64)
    Y[np.arange(n), y] = 1.0
    if class_weight:
        counts = np.bincount(y, minlength=n_classes).astype(np.float64)
        w = np.zeros_like(counts)
        nz = counts > 0
        w[nz] = n / (float(nz.sum()) * counts[nz])
        w[w <= 0] = 0.0
        Y = Y * w.reshape(1, -1)
    W = np.zeros((d, n_classes), dtype=np.float64)
    b = np.zeros((n_classes,), dtype=np.float64)
    mW = np.zeros_like(W)
    vW = np.zeros_like(W)
    mb = np.zeros_like(b)
    vb = np.zeros_like(b)
    b1, b2, eps = 0.9, 0.999, 1e-8
    for ep in range(1, int(epochs) + 1):
        logits = X @ W + b
        logits -= logits.max(axis=1, keepdims=True)
        P = np.exp(logits)
        P /= np.maximum(P.sum(axis=1, keepdims=True), 1e-12)
        G = (P - Y) / float(n)
        gW = X.T @ G + l2 * W
        gb = G.sum(axis=0)
        mW = b1 * mW + (1 - b1) * gW
        vW = b2 * vW + (1 - b2) * (gW * gW)
        mb = b1 * mb + (1 - b1) * gb
        vb = b2 * vb + (1 - b2) * (gb * gb)
        mh = mW / (1 - b1 ** ep)
        vh = vW / (1 - b2 ** ep)
        W -= lr * mh / (np.sqrt(vh) + eps)
        b -= lr * (mb / (1 - b1 ** ep)) / (np.sqrt(vb / (1 - b2 ** ep)) + eps)
    return W, b


def _standardize(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-6] = 1.0
    return (X - mean) / std, mean, std


def grouped_folds(games: Sequence[str], y: Sequence[str], k: int,
                  seed: int = 0) -> np.ndarray:
    """按 ``game_id`` 分组 + 类内轮转的折分配（同一局的前缀样本必在同折）。"""
    uniq = sorted(set(games))
    rng = np.random.default_rng(int(seed))
    by_class: Dict[str, List[str]] = {}
    first_y: Dict[str, str] = {}
    for g, c in zip(games, y):
        first_y.setdefault(str(g), str(c))
    for g in uniq:
        by_class.setdefault(first_y[g], []).append(g)
    fold_of: Dict[str, int] = {}
    for c in sorted(by_class):
        gs = list(by_class[c])
        rng.shuffle(gs)
        for j, g in enumerate(gs):
            fold_of[g] = j % int(k)
    return np.asarray([fold_of[str(g)] for g in games], dtype=np.int32)


def metrics(y_true: Sequence[str], proba: np.ndarray,
            classes: Sequence[str]) -> Dict[str, Any]:
    """top-1 / top-3 / macro-F1 / 混淆大类（多类）。"""
    cls = [str(c) for c in classes]
    idx = {c: i for i, c in enumerate(cls)}
    y = np.asarray([idx[str(v)] for v in y_true], dtype=np.int64)
    P = np.asarray(proba, dtype=np.float64)
    pred = P.argmax(axis=1)
    top1 = float((pred == y).mean())
    order = np.argsort(-P, axis=1)
    k3 = min(3, len(cls))
    top3 = float(np.mean([y[i] in order[i, :k3] for i in range(len(y))]))
    f1s: List[float] = []
    for c in range(len(cls)):
        tp = float(((pred == c) & (y == c)).sum())
        fp = float(((pred == c) & (y != c)).sum())
        fn = float(((pred != c) & (y == c)).sum())
        f1 = (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) > 0 else 0.0
        if (y == c).sum() > 0:
            f1s.append(f1)
    maj = collections.Counter([str(v) for v in y_true]).most_common(1)[0]
    return {
        "samples": int(len(y)),
        "classes": len(cls),
        "top1": round(top1, 4),
        "top3": round(top3, 4),
        "macro_f1": round(float(np.mean(f1s)) if f1s else 0.0, 4),
        "majority_class": str(maj[0]),
        "majority_acc": round(float(maj[1] / len(y)), 4),
    }


def _softmax_rows(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)


def fit_temperature(logits: np.ndarray, y: np.ndarray,
                    grid: Optional[Sequence[float]] = None) -> float:
    """单标量温度校准（OOF logits 上网格搜 NLL 最小）。"""
    z = np.asarray(logits, dtype=np.float64)
    yy = np.asarray(y, dtype=np.int64)
    n = max(1, len(yy))
    best_t, best = 1.0, float("inf")
    for t in (grid if grid is not None else np.arange(0.4, 4.01, 0.05)):
        P = _softmax_rows(z / float(t))
        nll = float(-np.log(np.maximum(P[np.arange(n), yy], 1e-12)).sum() / n)
        if nll < best:
            best, best_t = nll, float(t)
    return best_t


def _ece(proba: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """期望校准误差（top-1 置信度 vs 命中率，等宽分箱）。"""
    conf = proba.max(axis=1)
    hit = (proba.argmax(axis=1) == y).astype(np.float64)
    edges = np.linspace(0.0, 1.0, int(bins) + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if not m.any():
            continue
        ece += float(m.mean()) * abs(float(hit[m].mean()) - float(conf[m].mean()))
    return ece


def cross_validate(X: np.ndarray, y_labels: Sequence[str], games: Sequence[str], *,
                   folds: int = 5, epochs: int = 800, l2: float = 0.03,
                   class_weight: bool = False, turns: Optional[Sequence[int]] = None,
                   seed: int = 0) -> Tuple[SoftmaxModel, Dict[str, Any]]:
    """分组 CV：返回（全量重训 + 温度校准的模型，CV 指标）。

    ``turns`` 给出每个前缀样本的 turn 时，额外报**逐 turn 分桶**的 gate 工作点
    （线上「第 t 回合检测」实际会看到的覆盖率/精度）。
    """
    classes = sorted(set(str(v) for v in y_labels))
    idx = {c: i for i, c in enumerate(classes)}
    y = np.asarray([idx[str(v)] for v in y_labels], dtype=np.int64)
    fold_id = grouped_folds(games, y_labels, folds, seed)
    Xs, mean, std = _standardize(np.asarray(X, dtype=np.float64))
    oof_z = np.zeros((len(y), len(classes)), dtype=np.float64)
    for f in range(int(folds)):
        tr = fold_id != f
        te = ~tr
        if not tr.any() or not te.any():
            continue
        W, b = fit_softmax(Xs[tr], y[tr], len(classes), l2=l2, epochs=epochs,
                           class_weight=class_weight, seed=seed + f)
        oof_z[te] = Xs[te] @ W + b
    temp = fit_temperature(oof_z, y)
    proba = _softmax_rows(oof_z / temp)
    cv = metrics([str(v) for v in y_labels], proba, classes)
    cv["per_fold"] = int(folds)
    cv["by_game"] = True
    cv["temperature"] = round(float(temp), 4)
    cv["ece"] = round(float(_ece(proba, y)), 4)
    cv["nll"] = round(float(-np.log(np.maximum(
        proba[np.arange(len(y)), y], 1e-12)).mean()), 4)
    # 阈值工作点：min_prob=0.6 时的覆盖率与精度（线上 gating 的实际口径）
    conf = proba.max(axis=1)
    hit = (proba.argmax(axis=1) == y)
    for th in (0.5, 0.6, 0.7, 0.8):
        m = conf >= float(th)
        cv[f"gate_{th:.1f}"] = {
            "coverage": round(float(m.mean()), 4),
            "precision": round(float(hit[m].mean()), 4) if m.any() else 0.0,
        }
    if turns is not None:
        tv = np.asarray(turns, dtype=np.int64)
        by_turn: Dict[str, Any] = {}
        for i in range(N_BUCKETS):
            lo, hi = TURN_BUCKETS[i]
            mb = (tv >= lo) & (tv <= hi)
            if not mb.any():
                continue
            gate = mb & (conf >= 0.6)
            by_turn[bucket_key(i)] = {
                "samples": int(mb.sum()),
                "top1": round(float(hit[mb].mean()), 4),
                "coverage": round(float((conf[mb] >= 0.6).mean()), 4),
                "precision": (round(float(hit[gate].mean()), 4)
                              if gate.any() else 0.0),
            }
        cv["by_turn"] = by_turn
    W, b = fit_softmax(Xs, y, len(classes), l2=l2, epochs=epochs,
                       class_weight=class_weight, seed=seed)
    model = SoftmaxModel(classes=tuple(classes), W=W, b=b, mean=mean, std=std,
                         temp=float(temp))
    return model, cv


# ══════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="构建流派分类器 + 动作偏好表")
    ap.add_argument("--actions", default=DEFAULT_ACTIONS)
    ap.add_argument("--library", default=DEFAULT_LIBRARY)
    ap.add_argument("--cards", default=DEFAULT_CARDS)
    ap.add_argument("--out-table", default=DEFAULT_TABLE)
    ap.add_argument("--out-model", default=DEFAULT_MODEL)
    ap.add_argument("--out-metrics", default=DEFAULT_METRICS)
    ap.add_argument("--min-games", type=int, default=8,
                    help="头部流派最小样本数（其余合并 other；默认 8）")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--epochs", type=int, default=800)
    ap.add_argument("--l2", type=float, default=0.03)
    ap.add_argument("--max-turn", type=int, default=15)
    ap.add_argument("--hero-vocab", type=int, default=0,
                    help="英雄 one-hot 词表大小 K（默认 0=不用；实测 K>=8 会过拟合，"
                         "见 docs/ARCHETYPE_BIAS.md §分类器消融）")
    ap.add_argument("--no-hero", action="store_true",
                    help="等价于 --hero-vocab 0（保留旧消融入口）")
    ap.add_argument("--class-weight", type=int, default=0, choices=[0, 1],
                    help="1=类别平衡权重。实测 0 明显更好（balanced 会把稀有类概率"
                         "抬高、gate 精度掉 20pp+）")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    lib = load_library(args.library)
    cards = load_cards(args.cards)
    labeled = {g for g, v in lib.items() if v.get("archetype")}
    print(f"[data] 库内对局={len(lib)} 有标签={len(labeled)} "
          f"卡表={len(cards)} 特征维={FEATURE_DIM}")
    games = load_game_actions(args.actions, labeled)
    print(f"[data] 动作数据命中={len(games)} 局 "
          f"动作数={sum(len(v) for v in games.values())}")

    # 英雄词表：按“有标签对局数”取 topK
    hero_cnt = collections.Counter(
        str(lib[g].get("hero") or "") for g in labeled if lib[g].get("hero"))
    k_hero = 0 if args.no_hero else max(0, min(int(args.hero_vocab), HERO_VOCAB_SIZE))
    hero_vocab = [h for h, _n in hero_cnt.most_common(k_hero)] if k_hero else []
    sup = collections.Counter(str(lib[g]["archetype"]) for g in labeled)
    heads = sorted(a for a, c in sup.items() if c >= int(args.min_games))
    print(f"[labels] 流派类数={len(sup)} 头部类(>= {args.min_games})={len(heads)} "
          f"other={sum(c for a, c in sup.items() if a not in set(heads))}")
    for a, c in sup.most_common():
        tag = "head" if a in set(heads) else "other"
        print(f"    {a:<38s} {c:>4d}  [{tag}]")

    # 前缀样本
    pack = build_prefix_samples(games, lib, cards, hero_vocab=hero_vocab,
                                max_turn=int(args.max_turn))
    X = pack["X"]
    arch = pack["archetype"]
    gids = pack["games"]
    print(f"[samples] 前缀样本={len(X)} 覆盖对局={len(set(gids))} "
          f"平均每局={len(X) / max(1, len(set(gids))):.2f}")
    # 特征健全性
    if not np.all(np.isfinite(X)):
        raise RuntimeError("特征含 NaN/Inf")

    # 段 1：种族族
    tribe_lbl = [a.split("_", 1)[0] for a in arch]
    turns_lbl = pack["turn"]
    tribe_model, tribe_cv = cross_validate(
        X, tribe_lbl, gids, folds=int(args.folds), epochs=int(args.epochs),
        l2=float(args.l2), class_weight=bool(int(args.class_weight)),
        turns=turns_lbl, seed=int(args.seed))
    print(f"[cv/tribe] {json.dumps(tribe_cv, ensure_ascii=False)}")

    # 段 2：头部流派 + other
    head_set = set(heads)
    arch_lbl = [a if a in head_set else "other" for a in arch]
    arch_model, arch_cv = cross_validate(
        X, arch_lbl, gids, folds=int(args.folds), epochs=int(args.epochs),
        l2=float(args.l2), class_weight=bool(int(args.class_weight)),
        turns=turns_lbl, seed=int(args.seed))
    print(f"[cv/archetype] {json.dumps(arch_cv, ensure_ascii=False)}")

    # 偏好表（全量统计；不做 CV）
    pref = build_preference_table(games, lib, cards, head_archetypes=heads)
    table = {
        "schema": SCHEMA,
        "version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_dim": FEATURE_DIM,
        "feature_blocks": [[n, int(w)] for n, w in FEATURE_BLOCKS],
        "tribes": list(TRIBES),
        "turn_buckets": [list(b) for b in TURN_BUCKETS],
        "action_types": list(ACTION_TYPES),
        "rhythm_types": list(RHYTHM_TYPES),
        "head_archetypes": list(heads),
        "hero_vocab": list(hero_vocab),
        "min_games": int(args.min_games),
        "smoothing": {"rate_alpha": RATE_ALPHA, "tribe_alpha": TRIBE_ALPHA},
        "rate_kind": "per_turn(主) + rates(逐决策，仅分析)",
        "jitter_scale": AFF_SCALE,
        "baseline": pref["baseline"],
        "archetypes": pref["archetypes"],
        "tribes": pref["tribes"],
        "support": pref["support"],
        "games": {
            "library_games": len(lib), "labeled_games": len(labeled),
            "action_games": len(games),
            "prefix_samples": int(len(X)), "action_rows":
                int(sum(len(v) for v in games.values())),
        },
        "metrics": {"tribe": tribe_cv, "archetype": arch_cv},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_table)) or ".", exist_ok=True)
    tmp = args.out_table + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out_table)
    save_model(args.out_model, tribe=tribe_model, arch=arch_model,
               hero_vocab=hero_vocab, mean=tribe_model.mean, std=tribe_model.std,
               meta={"tribe_top1_cv": tribe_cv["top1"],
                     "tribe_top3_cv": tribe_cv["top3"],
                     "arch_top1_cv": arch_cv["top1"],
                     "arch_top3_cv": arch_cv["top3"],
                     "feature_version": FEATURE_VERSION,
                     "min_games": int(args.min_games),
                     "hero": bool(hero_vocab),
                     "class_weight": bool(int(args.class_weight))})
    out = {
        "schema": "hsbg.archetype_metrics",
        "version": 1,
        "data": table["games"],
        "feature_dim": FEATURE_DIM,
        "hero_vocab_size": len(hero_vocab),
        "hero_enabled": bool(hero_vocab),
        "min_games": int(args.min_games),
        "folds": int(args.folds),
        "labeled_archetypes": len(sup),
        "head_archetypes": len(heads),
        "archetype_support": dict(sorted(sup.items(), key=lambda kv: (-kv[1], kv[0]))),
        "head_classes": list(heads),
        "tribe": tribe_cv,
        "archetype": arch_cv,
        "table_path": os.path.abspath(args.out_table),
        "model_path": os.path.abspath(args.out_model),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_metrics)) or ".", exist_ok=True)
    with open(args.out_metrics + ".tmp", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(args.out_metrics + ".tmp", args.out_metrics)
    print(f"[out] table={args.out_table} model={args.out_model} "
          f"metrics={args.out_metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
