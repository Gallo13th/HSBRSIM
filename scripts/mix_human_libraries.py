#!/usr/bin/env python3
"""人类战团混池：多库按权重混合 + 帧级去重，输出 ``library_mixed.jsonl`` + 统计 JSON。

背景
====

``docs/HUMAN_BOARD_OPPONENT.md`` / ``docs/FIRESTONE_REPLAY_INGEST.md``：

- ``library_real_quasi_full.jsonl``（1,961 行）：10k+ 观测的**准完整**帧（board_detail /
  hand / tier / 关键词 / 金身 / 圣盾层数），是当前训练（``--human-board-fidelity full``）
  的主力库；
- ``library_firestone_recent.jsonl``（10,811 行）：近期 Firestone curated perfect games
  （MMR 中位 ~6.5k）的**准完整**帧，字段覆盖最好，但强度分位**低于** 10k+ 库
  （t5/t10/t15 p50 = 40/731/21,167 vs 48/1,144/29,729）→ 只能作**多样性/上限补充**；
- ``library_real_degraded.jsonl``（4,284 行）：10k+ board-only 帧，没有 payload，
  ``--human-board-fidelity full`` 下会退化为 board-only 注入。

因此混池的目标不是「把新库塞进来替换旧库」，而是**按权重保留 10k+ 强度校准的主导地位**，
用 Firestone 补近期 meta 多样性，用 degraded 补 10k+ 的 turn 覆盖。权重默认
``quasi_full 0.5 / firestone_recent 0.3 / degraded 0.2``。

口径
====

1. **去重**：``(game_id, turn, frame_signature)``。帧签名按
   ``docs/FIRESTONE_REPLAY_INGEST.md §7.1``：
   ``(turn, board(按位置排序的 card/atk/hp [+golden/kw]), hand(card/kind), tier,
   perspective)`` → sha1 前 16 位。跨库**同局同回合同帧**只保留**先出现**的一条
   （源顺序 = 优先级，默认准完整库在前）。
2. **权重 / 规模**：``--sizing proportional``（默认）把权重解释为**输出池的行数占比**，
   不做有放回采样。可达到的最大规模
   ``N = floor(min_i(n_i / w_i))``（不超出任何源的可用行数），因此
   ``quota_i = round(N * w_i) <= n_i``；默认 3 库时 ``N = 3,922``
   （quasi 1,961 全取 + firestone 1,177 + degraded 784）。
   ``--sizing keep-all`` 则保留全部行（只去重，权重仅记录），用于「要最大数据量」的场合。
3. **按 turn 分层抽样**：每个源内部按 turn 行数比例分配配额（最大余数法），再用固定 seed
   在桶内不放回抽样。这样混池的 turn 分布是各源 turn 分布的加权混合，而不是被行数最多的源
   （Firestone 的 t3–t13 偏多）带偏。
4. **幂等**：同一输入 + 同一 seed → 输出 JSONL **逐字节一致**（统计 JSON 里的
   ``generated_at`` / ``elapsed_s`` 除外）。

用法
====

    # 默认（准完整 0.5 / Firestone 0.3 / degraded 0.2）
    python scripts/mix_human_libraries.py

    # 自定义权重（NAME=PATH:WEIGHT，可重复）
    python scripts/mix_human_libraries.py \
        --source high=data/real_library/library_real_quasi_full.jsonl:0.6 \
        --source fs=data/real_library/library_firestone_recent.jsonl:0.4 \
        --sizing proportional --out /tmp/mixed.jsonl

    # 只去重、保留全部行
    python scripts/mix_human_libraries.py --sizing keep-all --out /tmp/all.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 默认混池（名称, 相对仓库根的路径, 权重）。顺序 = 去重优先级（准完整在前）。
DEFAULT_SOURCES: Tuple[Tuple[str, str, float], ...] = (
    ("quasi_full", "data/real_library/library_real_quasi_full.jsonl", 0.5),
    ("firestone_recent", "data/real_library/library_firestone_recent.jsonl", 0.3),
    ("degraded", "data/real_library/library_real_degraded.jsonl", 0.2),
)

DEFAULT_OUT = "data/real_library/library_mixed.jsonl"
DEFAULT_STATS = "data/real_library/library_mixed_stats.json"

SCHEMA = "hsbg.human_mixed_library"
SCHEMA_VERSION = 1

#: 规模口径：``proportional`` = 权重即输出占比（不超采样）；``keep-all`` = 只去重。
SIZINGS = ("proportional", "keep-all")


# ────────────────────────── 行解析 / 帧签名 ──────────────────────────


def _board_flat(row: Dict[str, Any]) -> List[Tuple[int, int, int]]:
    """行内战团 -> ``[(card, atk, hp), ...]``（确定性排序，忽略原始顺序）。

    兼容两种格式：``[[card, atk, hp], ...]``（准完整 / Firestone 库）与
    ``[{"card","atk","hp","position"}, ...]``（旧 board-only 库）。
    """
    out: List[Tuple[int, int, int]] = []
    raw = row.get("board")
    if not isinstance(raw, list):
        return out
    for m in raw:
        try:
            if isinstance(m, dict):
                out.append((int(m["card"]), int(m["atk"]), int(m["hp"])))
            elif isinstance(m, (list, tuple)) and len(m) >= 3:
                out.append((int(m[0]), int(m[1]), int(m[2])))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort()
    return out


def _hand_sig(row: Dict[str, Any]) -> List[int]:
    """手牌签名（只看 ``card``）；手牌不可得时为空。

    ``kind``（minion / spell）由卡表决定、不携带额外信息，因此不进签名——否则
    degraded 的 ``known_hand``（没有 kind）与准完整的 ``hand`` 会永远判成不同帧。
    ``known_hand``（degraded 库）同样是「已揭示的手牌」，一并纳入。
    """
    out: List[int] = []
    hand = row.get("hand")
    if "hand" in row and isinstance(hand, list):
        for h in hand:
            if isinstance(h, dict) and h.get("card") is not None:
                out.append(int(h["card"]))
    else:
        known = row.get("known_hand")
        if isinstance(known, list):
            for h in known:
                if isinstance(h, dict) and h.get("card") is not None:
                    out.append(int(h["card"]))
    out.sort()
    return out


def _detail_sig(row: Dict[str, Any]) -> List[Tuple[bool, int]]:
    """board_detail 的「隐藏状态位」签名（golden, kw）；没有 detail 时为空。"""
    detail = row.get("board_detail")
    board = row.get("board")
    if not isinstance(detail, list) or not isinstance(board, list) or len(detail) != len(board):
        return []
    out: List[Tuple[bool, int]] = []
    for m in detail:
        if not isinstance(m, dict):
            return []
        try:
            out.append((bool(m.get("golden")), int(m.get("kw") or 0)))
        except (TypeError, ValueError):
            return []
    out.sort()
    return out


def frame_signature(row: Dict[str, Any]) -> str:
    """帧签名（``docs/FIRESTONE_REPLAY_INGEST.md §7.1``），sha1 前 16 位。

    组成：``turn`` + ``board``（card/atk/hp，排序）+ ``hand``（card）+ ``tier``
    + ``perspective`` + ``board_detail`` 的 ``(golden, kw)`` 位（有 detail 时）。
    ``strength`` / ``source`` / ``file`` / ``mmr`` 等**不参与**签名：同一帧换个来源
    标记仍然是同一帧。
    """
    sig = {
        "turn": int(row.get("turn") or 0),
        "board": [list(x) for x in _board_flat(row)],
        "hand": [int(x) for x in _hand_sig(row)],
        "tier": row.get("tier"),
        "perspective": str(row.get("perspective") or "self"),
        "detail": [[g, k] for (g, k) in _detail_sig(row)],
    }
    blob = json.dumps(sig, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def dedupe_key(row: Dict[str, Any]) -> Tuple[str, int, str]:
    """去重键 ``(game_id, turn, frame_signature)``。"""
    return (str(row.get("game_id") or ""), int(row.get("turn") or 0), frame_signature(row))


def coarse_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    """「同一观测帧」的粗键：``(game_id, turn, perspective, board, hand)``。

    不含 ``tier`` / ``golden`` / ``kw`` 等细节位，用于**细节富度**去重：同一帧若同时有
    「带 board_detail」与「不带 board_detail」两条，只保留更完整的那条（见
    :func:`mix_libraries` 的去重说明）。
    """
    return (str(row.get("game_id") or ""), int(row.get("turn") or 0),
            str(row.get("perspective") or "self"),
            tuple(_board_flat(row)), tuple(_hand_sig(row)))


def has_detail(row: Dict[str, Any]) -> bool:
    """该行是否带可注入的 ``board_detail``（``--human-board-fidelity full`` 依赖它）。"""
    d = row.get("board_detail")
    b = row.get("board")
    return bool(isinstance(d, list) and isinstance(b, list) and d and len(d) == len(b))


# ────────────────────────── 统计工具 ──────────────────────────


def _percentile_index(q: float, n: int) -> int:
    """最近秩分位下标（与 ``human_board_pool`` / ``MirrorSnapshotPool`` 同一公式）。"""
    if n <= 1:
        return 0
    return min(n - 1, max(0, int(math.floor(float(q) * (n - 1) + 0.5))))


def _pct(values: Sequence[int], q: float) -> Optional[int]:
    if not values:
        return None
    v = sorted(int(x) for x in values)
    return int(v[_percentile_index(q, len(v))])


def _turn_hist(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        t = str(int(row.get("turn") or 0))
        out[t] = out.get(t, 0) + 1
    return {k: out[k] for k in sorted(out, key=lambda x: int(x))}


def _strength_by_turn(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """每回合 ``strength`` 的 p50 / p90 / max（与 Firestone 统计 JSON 同口径）。"""
    buckets: Dict[int, List[int]] = {}
    for row in rows:
        try:
            t = int(row.get("turn") or 0)
            s = int(row.get("strength"))
        except (TypeError, ValueError):
            continue
        buckets.setdefault(t, []).append(s)
    out: Dict[str, Dict[str, int]] = {}
    for t in sorted(buckets):
        vals = buckets[t]
        out[str(t)] = {"n": len(vals), "p50": _pct(vals, 0.5),
                       "p90": _pct(vals, 0.9), "max": int(max(vals))}
    return out


def _payload_rows(rows: Iterable[Dict[str, Any]]) -> int:
    """带 ``board_detail`` 的行数（``--human-board-fidelity full`` 需要它）。"""
    n = 0
    for row in rows:
        d = row.get("board_detail")
        b = row.get("board")
        if isinstance(d, list) and isinstance(b, list) and d and len(d) == len(b):
            n += 1
    return n


def _load_jsonl(path: str) -> Tuple[List[Dict[str, Any]], int]:
    """读取 JSONL；返回 ``(rows, bad_lines)``。空文件 / 空行合法。"""
    rows: List[Dict[str, Any]] = []
    bad = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except BaseException:  # noqa: BLE001 - 坏行不算致命，计数后跳过
                bad += 1
                continue
            if not isinstance(obj, dict):
                bad += 1
                continue
            rows.append(obj)
    return rows, bad


# ────────────────────────── 配额 ──────────────────────────


def _largest_remainder(total: int, weights: Sequence[float],
                       caps: Sequence[int]) -> List[int]:
    """按权重把 ``total`` 拆成整数配额（最大余数法，且 ``quota_i <= caps_i``）。

    ``total`` 应已满足 ``total <= sum(caps)``；若因浮点/取整超出会被逐个削平。
    """
    n = len(weights)
    if n == 0 or total <= 0:
        return [0] * n
    wsum = float(sum(weights))
    if wsum <= 0:
        return [0] * n
    # 权重按和归一：quota_i = total * w_i / Σw。源级配额传入的已是归一权重（Σ=1），
    # 源内 turn 分层传入的是各行数（此处归一成占比），两种用法一致。
    exact = [float(total) * float(w) / wsum for w in weights]
    quota = [min(int(math.floor(x)), int(caps[i])) for i, x in enumerate(exact)]
    rem = int(total) - sum(quota)
    if rem > 0:
        order = sorted(range(n), key=lambda i: (-(exact[i] - math.floor(exact[i])), i))
        while rem > 0:
            progressed = False
            for i in order:
                if rem <= 0:
                    break
                if quota[i] < int(caps[i]):
                    quota[i] += 1
                    rem -= 1
                    progressed = True
            if not progressed:
                break
    elif rem < 0:  # 理论上不会发生（floor + cap），保守兜底
        for i in range(n):
            while rem < 0 and quota[i] > 0:
                quota[i] -= 1
                rem += 1
    return quota


def _feasible_total(counts: Sequence[int], weights: Sequence[float]) -> int:
    """``proportional`` 口径下不超采样的最大总行数 ``floor(min_i n_i / w_i)``。"""
    best = None
    for n, w in zip(counts, weights):
        if w <= 0:
            continue
        cap = int(n) // float(w) if w > 0 else 0
        # 用 floor(n/w) 而不是 n/w：保证 quota_i = N*w_i 不超 n_i。
        cap = int(math.floor(float(n) / float(w) + 1e-9))
        best = cap if best is None else min(best, cap)
    return int(best or 0)


# ────────────────────────── 混池主体 ──────────────────────────


@dataclass
class Source:
    """一个输入库：名称 / 路径 / 权重（可带 turn 窗口）。"""

    name: str
    path: str
    weight: float
    #: 该源自己的 turn 窗口（``min_turn``, ``max_turn``；0 = 不限）。与全局
    #: ``--min-turn/--max-turn`` 取交集，用于「只让 Firestone 补 t>=10」的配方。
    min_turn: int = 0
    max_turn: int = 0


@dataclass
class MixResult:
    """混池结果（行 + 统计），便于测试直接断言。"""

    rows: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


def _parse_source(spec: str) -> Source:
    """``[NAME=]PATH:WEIGHT[@MIN-MAX]`` -> :class:`Source`。

    ``@MIN-MAX`` 是该源自己的 turn 窗口（两端可省略，例如 ``@10-`` 只要 t>=10，
    ``@-12`` 只要 t<=12）。全局 ``--min-turn/--max-turn`` 仍然生效，两者取交集。
    """
    text = str(spec).strip()
    if not text:
        raise ValueError("空的 --source")
    min_turn = max_turn = 0
    if "@" in text:
        text, window = text.rsplit("@", 1)
        text = text.strip()
        win = str(window).strip()
        if win and win != "-":
            if "-" in win:
                lo_s, hi_s = win.split("-", 1)
            else:
                lo_s, hi_s = win, ""
            try:
                min_turn = int(lo_s) if lo_s.strip() else 0
                max_turn = int(hi_s) if hi_s.strip() else 0
            except ValueError as exc:
                raise ValueError(f"--source 的 turn 窗口非法: {window!r}") from exc
            if min_turn < 0 or max_turn < 0:
                raise ValueError(f"--source 的 turn 窗口必须 >= 0: {window!r}")
    name = ""
    if "=" in text:
        name, text = text.split("=", 1)
        name = name.strip()
    if ":" not in text:
        raise ValueError(f"--source 需要 PATH:WEIGHT，得到 {spec!r}")
    path, weight = text.rsplit(":", 1)
    try:
        w = float(weight)
    except ValueError as exc:
        raise ValueError(f"--source 权重非法: {weight!r}") from exc
    if w < 0:
        raise ValueError(f"--source 权重必须 >= 0: {w}")
    path = path.strip()
    if not path:
        raise ValueError(f"--source 路径为空: {spec!r}")
    if not name:
        base = os.path.basename(path)
        for ext in (".jsonl.gz", ".jsonl", ".json"):
            if base.endswith(ext):
                base = base[: -len(ext)]
                break
        name = base[len("library_"):] if base.startswith("library_") else base
    return Source(name=name, path=path, weight=w, min_turn=min_turn, max_turn=max_turn)


def _select(source_rows: List[Dict[str, Any]], quota: int, seed: int,
            source_index: int) -> List[Dict[str, Any]]:
    """按 turn 分层、桶内不放回抽 ``quota`` 行；返回按 ``(turn, 原下标)`` 排序的行。"""
    if quota <= 0 or not source_rows:
        return []
    buckets: Dict[int, List[int]] = {}
    for idx, row in enumerate(source_rows):
        buckets.setdefault(int(row.get("turn") or 0), []).append(idx)
    turns = sorted(buckets)
    caps = [len(buckets[t]) for t in turns]
    per_turn = _largest_remainder(int(quota), [float(c) for c in caps], caps)
    rng = random.Random(f"{int(seed)}:{int(source_index)}")
    picked: List[int] = []
    for t, k in zip(turns, per_turn):
        if k <= 0:
            continue
        idxs = buckets[t]
        if k >= len(idxs):
            picked.extend(idxs)
        else:
            picked.extend(sorted(rng.sample(idxs, k)))
    picked.sort()
    return [source_rows[i] for i in picked]


def mix_libraries(sources: Sequence[Source], *, out: str, stats_out: str = "",
                  sizing: str = "proportional", seed: int = 20261031,
                  max_rows: int = 0, name: str = "",
                  min_turn: int = 0, max_turn: int = 0) -> MixResult:
    """执行混池：读 -> turn 过滤 -> 去重 -> 配额 -> 分层抽样 -> 写盘 + 统计。

    - ``sizing="proportional"``：权重 = 输出占比，``N = floor(min_i n_i/w_i)``
      （``max_rows>0`` 时再取小）；
    - ``sizing="keep-all"``：只去重，全部行保留（权重只记录）；
    - 去重顺序 = ``sources`` 顺序（先出现者胜），因此默认把准完整库放最前；
    - ``min_turn`` / ``max_turn``：只保留该回合区间（``max_turn=0`` 表示不设上限）。
      用于「只拿 Firestone 补高端上限」的配方（例如 ``--min-turn 10``），
      在**去重之前**过滤，因此不会影响到「同帧优先级」的口径；
    - ``stats_out`` 为空时只返回统计不写文件。
    """
    t0 = time.time()
    sizing = str(sizing or "proportional").strip().lower()
    if sizing not in SIZINGS:
        raise ValueError(f"未知 sizing={sizing!r}（可选 {SIZINGS}）")
    srcs = list(sources)
    if not srcs:
        raise ValueError("至少需要一个输入库")

    loaded: List[List[Dict[str, Any]]] = []
    input_rows: List[int] = []
    bad_lines: List[int] = []
    out_of_turn = [0] * len(srcs)
    turn_windows: List[List[int]] = []
    lo, hi = int(min_turn or 0), int(max_turn or 0)
    for i, s in enumerate(srcs):
        if not os.path.isfile(s.path):
            raise FileNotFoundError(f"输入库不存在: {s.path}")
        rows, bad = _load_jsonl(s.path)
        input_rows.append(len(rows))
        bad_lines.append(int(bad))
        s_lo = max(lo, int(getattr(s, "min_turn", 0) or 0))
        his = [x for x in (hi, int(getattr(s, "max_turn", 0) or 0)) if x > 0]
        s_hi = min(his) if his else 0
        if s_lo > 1 or s_hi > 0:
            kept: List[Dict[str, Any]] = []
            for row in rows:
                t = int(row.get("turn") or 0)
                if t < s_lo or (s_hi > 0 and t > s_hi):
                    out_of_turn[i] += 1
                    continue
                kept.append(row)
            rows = kept
            turn_windows.append([int(s_lo), int(s_hi)])
        else:
            turn_windows.append([0, 0])
        loaded.append(rows)

    # ---- 帧级去重（顺序 = 优先级） ----
    # 1) 严格签名相同 -> 重复；
    # 2) 同一粗键（game/turn/perspective/board/hand）且一边有 board_detail、另一边没有
    #    -> 只保留更完整的那条（缺 detail 的行是同一观测帧的**低信息版本**）。
    #    缺 detail 的行与「有 detail 但隐藏位不同」的行**不**算重复（golden/kw 是真实差异）。
    seen: Dict[Tuple[str, int, str], int] = {}
    coarse: Dict[Tuple[Any, ...], int] = {}
    dedup_removed = [0] * len(srcs)
    dedup_low_detail = [0] * len(srcs)
    kept_all: List[Tuple[int, Dict[str, Any]]] = []
    alive: List[bool] = []
    for i, rows in enumerate(loaded):
        for row in rows:
            key = dedupe_key(row)
            if key in seen:
                dedup_removed[i] += 1
                continue
            ck = coarse_key(row)
            rich = has_detail(row)
            j = coarse.get(ck)
            if j is not None:
                prev_src, prev_row = kept_all[j]
                if has_detail(prev_row) and not rich:
                    seen[key] = i
                    dedup_low_detail[i] += 1
                    continue
                if rich and not has_detail(prev_row):
                    alive[j] = False           # 更完整的后来者替换低信息版本
                    dedup_low_detail[prev_src] += 1
            seen[key] = i
            coarse[ck] = len(kept_all)
            kept_all.append((i, row))
            alive.append(True)
    deduped: List[List[Dict[str, Any]]] = [[] for _ in srcs]
    for (src_i, row), ok in zip(kept_all, alive):
        if ok:
            deduped[src_i].append(row)

    # ---- 配额 ----
    avail = [len(rows) for rows in deduped]
    raw_weights = [max(0.0, float(s.weight)) for s in srcs]
    wsum = float(sum(raw_weights))
    if wsum <= 0:
        raise ValueError("权重之和必须 > 0")
    # 权重是**绝对占比**：先归一，再由 total * w_norm 得到配额。
    weights = [w / wsum for w in raw_weights]
    if sizing == "keep-all":
        quotas = list(avail)
        total = int(sum(quotas))
        if max_rows > 0 and total > int(max_rows):
            quotas = _largest_remainder(int(max_rows), weights, avail)
            total = int(sum(quotas))
    else:
        total = _feasible_total(avail, weights)
        if max_rows > 0:
            total = min(total, int(max_rows))
        quotas = _largest_remainder(total, weights, avail)
        total = int(sum(quotas))

    # ---- 分层抽样 ----
    out_rows: List[Dict[str, Any]] = []
    selected: List[List[Dict[str, Any]]] = []
    for i, rows in enumerate(deduped):
        picked = _select(rows, quotas[i], seed, i)
        selected.append(picked)
        out_rows.extend(picked)

    # ---- 写盘（JSONL 逐字节确定：同输入同 seed 幂等） ----
    out_abs = os.path.abspath(out)
    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
    tmp = out_abs + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")
    os.replace(tmp, out_abs)

    # ---- 统计 ----
    per_source: List[Dict[str, Any]] = []
    for i, s in enumerate(srcs):
        per_source.append({
            "name": s.name,
            "path": s.path,
            "weight": float(s.weight),
            "weight_norm": round(float(weights[i]), 6),
            "rows_input": int(input_rows[i]),
            "bad_lines": int(bad_lines[i]),
            "rows_out_of_turn": int(out_of_turn[i]),
            "turn_window": list(turn_windows[i]),
            "dedup_removed": int(dedup_removed[i]),
            "dedup_low_detail": int(dedup_low_detail[i]),
            "rows_available": int(avail[i]),
            "quota": int(quotas[i]),
            "rows_out": int(len(selected[i])),
            "payload_rows_out": int(_payload_rows(selected[i])),
            "turn_hist_out": _turn_hist(selected[i]),
            "strength_by_turn_in": _strength_by_turn(loaded[i]),
        })
    stats: Dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "name": str(name or ""),
        "seed": int(seed),
        "sizing": sizing,
        "max_rows": int(max_rows),
        "turn_filter": [int(lo), int(hi)],
        "out": out_abs,
        "dedupe": {"key": "(game_id, turn, frame_signature)",
                   "low_detail": "同粗键(game/turn/视角/战团/手牌)且缺 board_detail 的低信息版本",
                   "signature": ("turn, board(card/atk/hp sorted), hand(card), "
                                 "tier, perspective, board_detail(golden,kw)"),
                   "priority": "sources 顺序（先出现者胜）"},
        "sources": per_source,
        "totals": {
            "rows_input": int(sum(input_rows)),
            "bad_lines": int(sum(bad_lines)),
            "rows_out_of_turn": int(sum(out_of_turn)),
            "dedup_removed": int(sum(dedup_removed)),
            "dedup_low_detail": int(sum(dedup_low_detail)),
            "rows_available": int(sum(avail)),
            "rows_out": int(len(out_rows)),
            "payload_rows_out": int(_payload_rows(out_rows)),
            "payload_ratio_out": (round(_payload_rows(out_rows) / len(out_rows), 4)
                                  if out_rows else 0.0),
            "turn_min": (min(int(r.get("turn") or 0) for r in out_rows)
                         if out_rows else 0),
            "turn_max": (max(int(r.get("turn") or 0) for r in out_rows)
                         if out_rows else 0),
        },
        "turn_hist": _turn_hist(out_rows),
        "strength_by_turn_mixed": _strength_by_turn(out_rows),
        "elapsed_s": round(time.time() - t0, 3),
    }

    # ---- 可选：用真实的 HumanBoardPool 复读一遍（确认能进训练） ----
    pool_check: Dict[str, Any] = {}
    try:
        sys.path.insert(0, ROOT)
        from hsbg.az.train.human_board_pool import HumanBoardPool  # noqa: PLC0415

        pool = HumanBoardPool(out_abs)
        pool_check = {"rows": int(pool.rows), "kept": int(pool.kept),
                      "payload_kept": int(pool.payload_kept),
                      "filtered": dict(pool.filtered),
                      "turns": [int(t) for t in pool.turns()]}
    except BaseException as exc:  # noqa: BLE001 - 复读只是自检，失败不改变产物
        pool_check = {"error": repr(exc)[:200]}
    stats["pool_check"] = pool_check

    if stats_out:
        stats_abs = os.path.abspath(stats_out)
        os.makedirs(os.path.dirname(stats_abs) or ".", exist_ok=True)
        tmp_s = stats_abs + ".tmp"
        with open(tmp_s, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_s, stats_abs)
    return MixResult(rows=out_rows, stats=stats)


# ────────────────────────── CLI ──────────────────────────


def _fmt_table(stats: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"[mix] sizing={stats['sizing']} seed={stats['seed']} "
                 f"rows_out={stats['totals']['rows_out']} "
                 f"(input {stats['totals']['rows_input']}, "
                 f"dedup_removed {stats['totals']['dedup_removed']})")
    lines.append(f"{'source':<20}{'weight':>8}{'in':>9}{'dedup':>8}{'avail':>9}"
                 f"{'quota':>8}{'out':>8}{'payload':>9}")
    for s in stats["sources"]:
        lines.append(f"{s['name']:<20}{s['weight']:>8.2f}{s['rows_input']:>9}"
                     f"{s['dedup_removed']:>8}{s['rows_available']:>9}"
                     f"{s['quota']:>8}{s['rows_out']:>8}{s['payload_rows_out']:>9}")
    # 强度 p50 对比（混池 vs 各源）
    mixed = stats.get("strength_by_turn_mixed") or {}
    sources = stats["sources"]
    turns = sorted({int(t) for s in sources
                    for t in (s.get("strength_by_turn_in") or {})}
                   | {int(t) for t in mixed})
    header = f"{'turn':>5}{'mixed':>9}" + "".join(f"{s['name']:>20}" for s in sources)
    lines.append(header)
    for t in turns:
        cells = [f"{t:>5}"]
        m = (mixed.get(str(t)) or {}).get("p50")
        cells.append(f"{m if m is not None else '-':>9}")
        for s in sources:
            p = ((s.get("strength_by_turn_in") or {}).get(str(t)) or {}).get("p50")
            cells.append(f"{p if p is not None else '-':>20}")
        lines.append("".join(cells))
    pc = stats.get("pool_check") or {}
    lines.append(f"[mix] pool_check: rows={pc.get('rows')} kept={pc.get('kept')} "
                 f"payload_kept={pc.get('payload_kept')} "
                 f"filtered={pc.get('filtered')} err={pc.get('error')}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="人类战团混池（多库加权 + (game_id, turn, frame signature) 去重）")
    ap.add_argument("--source", action="append", default=None,
                    metavar="[NAME=]PATH:WEIGHT[@MIN-MAX]",
                    help="输入库 + 权重（可重复），可选 @MIN-MAX 只取该 turn 区间；"
                         "默认 quasi_full 0.5 / firestone_recent 0.3 / degraded 0.2")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"输出 JSONL（默认 {DEFAULT_OUT}）")
    ap.add_argument("--stats-out", default=DEFAULT_STATS,
                    help=f"统计 JSON（默认 {DEFAULT_STATS}）")
    ap.add_argument("--sizing", default="proportional", choices=list(SIZINGS),
                    help="proportional=权重即输出占比（默认）；keep-all=只去重保留全部")
    ap.add_argument("--seed", type=int, default=20261031, help="桶内抽样 seed（默认 20261031）")
    ap.add_argument("--max-rows", type=int, default=0,
                    help="输出行数上限（0=按 sizing 自动）")
    ap.add_argument("--name", default="", help="写进统计的混池名（如 s14_default）")
    ap.add_argument("--min-turn", type=int, default=0,
                    help="只保留 turn >= 该值的帧（0=不过滤）；配合 --max-turn 做「只补高端」")
    ap.add_argument("--max-turn", type=int, default=0,
                    help="只保留 turn <= 该值的帧（0=不设上限）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    specs = list(args.source or [])
    sources: List[Source] = []
    if specs:
        for spec in specs:
            src = _parse_source(spec)
            if not os.path.isabs(src.path) and not os.path.isfile(src.path):
                src.path = os.path.join(ROOT, src.path)
            sources.append(src)
    else:
        for nm, rel, w in DEFAULT_SOURCES:
            sources.append(Source(name=nm, path=os.path.join(ROOT, rel), weight=w))

    try:
        result = mix_libraries(sources, out=args.out, stats_out=args.stats_out,
                               sizing=args.sizing, seed=int(args.seed),
                               max_rows=int(args.max_rows), name=args.name,
                               min_turn=int(args.min_turn),
                               max_turn=int(args.max_turn))
    except (ValueError, FileNotFoundError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    if not args.quiet:
        print(_fmt_table(result.stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
