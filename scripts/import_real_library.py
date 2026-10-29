#!/usr/bin/env python3
"""真实 10k+ MMR 战团库导入（real_10k）。

输入：``data/real_library/obs/observations/<game_hash>.jsonl``，每行是一条真实对局的
战斗/招募快照。脚本把它转成引擎可用的「战团库」JSONL：

    {"turn": T, "strength": S, "hero": <int|None>, "known_hand": [...],
     "board": [{"card": <int>, "atk": <int>, "hp": <int>, "position": <int>}, ...],
     "source": "real_10k", "game_id": "...", "build_number": ..., "file": "..."}

关键约定
--------
* **整数卡索引**：``rust/crates/hsbg-engine/data/cards.json`` 的 ``cards`` 是数组，
  引擎 ``CardId`` 就是数组下标（见 Rust ``cards.rs``：``CardId(i as u16)``）。
  本脚本只读该 JSON，绝不修改。
* **质量门（默认 strict）**：只保留 ``library_ready is True`` 且
  ``hidden_counters_complete is True`` 的行；字段缺失单独记因。
* **卡表映射 fail-closed**：牌面里任何一张随从映射不到整数索引，整条丢弃。
* **强度**：``Σ(attack + health)``。
* **去重**：``(turn, 排序后的 (card, atk, hp) 多重集)``。
* **按 turn 分桶**：输出按 ``(turn, strength, signature)`` 排序，同 turn 连续。

严格门会筛掉本数据集全部行（见 docs/LIBRARY_POOL_PLAN.md §H）；``--allow-unready``
是显式的诊断模式：仍做结构校验，但允许两个质量标志为 false，并在记录里写
``quality: "degraded"`` 与 ``degraded_reasons``。**不要把 degraded 库当作 ready 库用。**

用法::

    PYTHONPATH=rust/python:. python scripts/import_real_library.py --stats \
        --stats-json data/real_library/library_real_stats.json

    PYTHONPATH=rust/python:. python scripts/import_real_library.py --allow-unready \
        --out data/real_library/library_real_degraded.jsonl \
        --stats-json data/real_library/library_real_degraded_stats.json --stats
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBS_DIR = REPO_ROOT / "data" / "real_library" / "obs" / "observations"
DEFAULT_CARDS = REPO_ROOT / "rust" / "crates" / "hsbg-engine" / "data" / "cards.json"
DEFAULT_OUT = REPO_ROOT / "data" / "real_library" / "library_real.jsonl"

SOURCE_TAG = "real_10k"

#: 英雄皮肤 id -> 基础英雄 id（卡表里只有基础英雄，皮肤是 *_SKIN_X 变体）。
_SKIN_RE = re.compile(r"_SKIN_[A-Z0-9]+$")

#: 一行可能同时犯多个错；按此优先级取一个「主因」写进丢弃分布。
PRIMARY_REASON_ORDER: Tuple[str, ...] = (
    "parse_error",
    "not_object",
    "missing_library_ready",
    "library_ready_false",
    "missing_hidden_counters_complete",
    "hidden_counters_incomplete",
    "bad_board",
    "bad_turn",
    "board_too_large",
    "board_too_small",
    "bad_minion",
    "unmapped_card",
    "incomplete_stats",
    "negative_stats",
    "duplicate",
)

GATE_REASONS = frozenset({
    "missing_library_ready",
    "library_ready_false",
    "missing_hidden_counters_complete",
    "hidden_counters_incomplete",
})

_MISSING = object()


# ---------------------------------------------------------------------------
# 卡表
# ---------------------------------------------------------------------------
def load_card_index(path: str | Path) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """读 cards.json，返回 ``(card_id -> 数组下标, meta)``。

    下标即 Rust ``CardId``，**不排序、不重排、不改文件**。重复 id 按 Rust
    ``by_id.insert`` 语义后者覆盖（当前数据无重复）。
    """
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    cards = raw.get("cards") if isinstance(raw, dict) else raw
    if not isinstance(cards, list):
        raise ValueError(f"cards.json 结构异常（无 cards 数组）: {p}")
    index: Dict[str, int] = {}
    for i, card in enumerate(cards):
        if isinstance(card, dict) and isinstance(card.get("id"), str):
            index[card["id"]] = i
    meta = dict(raw.get("meta", {})) if isinstance(raw, dict) else {}
    meta["count"] = len(cards)
    meta["mapped_count"] = len(index)
    return index, meta


def map_hero(card_id: Optional[str], index: Dict[str, int]
             ) -> Tuple[Optional[int], str]:
    """英雄卡映射：直接命中 -> 去皮肤后缀命中 -> 失败。

    返回 ``(int|None, mode)``，mode ∈ ``{"direct", "skin_base", "unmapped", "none"}``。
    """
    if not card_id:
        return None, "none"
    if card_id in index:
        return index[card_id], "direct"
    base = _SKIN_RE.sub("", card_id)
    if base and base in index:
        return index[base], "skin_base"
    return None, "unmapped"


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------
@dataclass
class BoardSnapshot:
    """一条清洗后的战团快照（对应一行观测）。"""

    turn: int
    strength: int
    hero: Optional[int]
    hero_card_id: Optional[str]
    known_hand: List[Dict[str, Any]]
    board: List[Dict[str, int]]
    source: str = SOURCE_TAG
    game_id: str = ""
    build_number: Optional[int] = None
    file: str = ""
    controller: Optional[int] = None
    stage: str = ""
    split: str = ""
    combat_index: Optional[int] = None
    quality: str = "ready"
    degraded_reasons: List[str] = field(default_factory=list)
    library_ready: bool = True
    hidden_counters_complete: bool = True
    quality_flags: List[str] = field(default_factory=list)

    def signature(self) -> Tuple[int, Tuple[Tuple[int, int, int], ...]]:
        """去重签名：``(turn, 排序后的 board (card, atk, hp))``。"""
        return (self.turn,
                tuple(sorted((int(m["card"]), int(m["atk"]), int(m["hp"]))
                             for m in self.board)))

    def to_record(self) -> Dict[str, Any]:
        """输出 JSONL 记录（前 9 个字段是需求约定，其后为溯源/质量元数据）。"""
        return {
            "turn": self.turn,
            "strength": self.strength,
            "hero": self.hero,
            "known_hand": self.known_hand,
            "board": self.board,
            "source": self.source,
            "game_id": self.game_id,
            "build_number": self.build_number,
            "file": self.file,
            "hero_card_id": self.hero_card_id,
            "controller": self.controller,
            "stage": self.stage,
            "split": self.split,
            "combat_index": self.combat_index,
            "quality": self.quality,
            "degraded_reasons": self.degraded_reasons,
            "library_ready": self.library_ready,
            "hidden_counters_complete": self.hidden_counters_complete,
            "quality_flags": self.quality_flags,
        }


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _blank_metrics() -> Dict[str, Any]:
    return {
        "minions_seen": 0,
        "board_minions": 0,
        "unmapped_minions": 0,
        "unmapped_ids": [],
        "incomplete_stats": 0,
        "known_hand": 0,
        "known_hand_unmapped": 0,
        "hero_mode": "none",
        "hero_card_id": None,
    }


def parse_snapshot(row: Any, *, card_index: Dict[str, int], source_file: str = "",
                   allow_unready: bool = False, max_board: int = 7,
                   min_board: int = 0
                   ) -> Tuple[Optional[BoardSnapshot], List[str], Dict[str, Any]]:
    """解析一行 JSON -> (快照 | None, 失败原因列表, 该行映射指标)。

    * 结构错误（board/attack/health/卡映射/turn）永远丢弃，与 ``allow_unready`` 无关；
    * 质量门错误只在 ``allow_unready=False`` 时丢弃；
    * 返回的失败列表包含**全部**原因（便于统计），调用方按优先级取主因。
    """
    failures: List[str] = []
    m = _blank_metrics()

    if not isinstance(row, dict):
        return None, ["not_object"], m

    raw_board = row.get("board")
    if not isinstance(raw_board, list):
        return None, ["bad_board"], m

    m["minions_seen"] = len(raw_board)
    if len(raw_board) > max_board:
        failures.append("board_too_large")
    if len(raw_board) < min_board:
        failures.append("board_too_small")

    board: List[Dict[str, int]] = []
    strength = 0
    for i, minion in enumerate(raw_board):
        if not isinstance(minion, dict):
            failures.append("bad_minion")
            continue
        card_id = minion.get("card_id")
        if not isinstance(card_id, str) or card_id not in card_index:
            failures.append("unmapped_card")
            m["unmapped_minions"] += 1
            m["unmapped_ids"].append(card_id if isinstance(card_id, str) else repr(card_id))
            continue
        atk = minion.get("attack")
        hp = minion.get("health")
        if not _is_int(atk) or not _is_int(hp):
            failures.append("incomplete_stats")
            m["incomplete_stats"] += 1
            continue
        atk = int(atk)
        hp = int(hp)
        if atk < 0 or hp < 0:
            failures.append("negative_stats")
            continue
        pos = minion.get("position")
        if not _is_int(pos) or int(pos) < 1:
            pos = i + 1
        board.append({"card": int(card_index[card_id]), "atk": atk, "hp": hp,
                      "position": int(pos)})
        strength += atk + hp
        m["board_minions"] += 1

    turn = row.get("turn")
    if not _is_int(turn) or int(turn) <= 0:
        failures.append("bad_turn")

    # 质量门
    gate: List[str] = []
    library_ready = row.get("library_ready", _MISSING)
    hidden_ok = row.get("hidden_counters_complete", _MISSING)
    if library_ready is _MISSING:
        gate.append("missing_library_ready")
    elif library_ready is not True:
        gate.append("library_ready_false")
    if hidden_ok is _MISSING:
        gate.append("missing_hidden_counters_complete")
    elif hidden_ok is not True:
        gate.append("hidden_counters_incomplete")

    # 英雄 / 手牌（不参与 fail-closed，只做尽力映射并计数）
    hero_card_id: Optional[str] = None
    heroes = row.get("heroes")
    if isinstance(heroes, list) and heroes and isinstance(heroes[0], dict):
        cid = heroes[0].get("card_id")
        if isinstance(cid, str):
            hero_card_id = cid
    hero_idx, hero_mode = map_hero(hero_card_id, card_index)
    m["hero_mode"] = hero_mode
    m["hero_card_id"] = hero_card_id

    known_hand: List[Dict[str, Any]] = []
    raw_hand = row.get("known_hand")
    if isinstance(raw_hand, list):
        for item in raw_hand:
            if not isinstance(item, dict):
                continue
            cid = item.get("card_id")
            cid = cid if isinstance(cid, str) else None
            card = card_index.get(cid) if cid is not None else None
            known_hand.append({"card": int(card) if card is not None else None,
                               "card_id": cid})
            m["known_hand"] += 1
            if card is None:
                m["known_hand_unmapped"] += 1

    all_failures = gate + failures
    if failures:
        return None, all_failures, m
    if gate and not allow_unready:
        return None, all_failures, m

    quality_flags = [str(x) for x in row.get("quality_flags", [])] \
        if isinstance(row.get("quality_flags"), list) else []
    build_number = row.get("build_number")
    combat_index = row.get("combat_index")
    controller = row.get("controller")

    snap = BoardSnapshot(
        turn=int(turn),
        strength=int(strength),
        hero=hero_idx,
        hero_card_id=hero_card_id,
        known_hand=known_hand,
        board=board,
        source=SOURCE_TAG,
        game_id=str(row.get("game_id") or ""),
        build_number=int(build_number) if _is_int(build_number) else None,
        file=_rel(source_file),
        controller=int(controller) if _is_int(controller) else None,
        stage=str(row.get("stage") or ""),
        split=str(row.get("split") or ""),
        combat_index=int(combat_index) if _is_int(combat_index) else None,
        quality="degraded" if gate else "ready",
        degraded_reasons=list(gate),
        library_ready=library_ready is True,
        hidden_counters_complete=hidden_ok is True,
        quality_flags=quality_flags,
    )
    # 诊断模式下 gate 失败不算丢弃，但仍把原因返回给统计层。
    return snap, (gate if allow_unready else []), m


# ---------------------------------------------------------------------------
# 统计工具
# ---------------------------------------------------------------------------
def _rel(path: str | Path) -> str:
    p = Path(path).resolve()
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """线性插值分位数；空序列返回 None。"""
    if not values:
        return None
    s = sorted(float(v) for v in values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * float(q)
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    val = s[lo] + (s[hi] - s[lo]) * (k - lo)
    return round(val, 4)


def _pick_primary(failures: Sequence[str], allow_unready: bool = False) -> str:
    """按优先级取一个主因；放宽模式下质量门不算丢弃原因。"""
    fs = set(failures)
    if allow_unready:
        fs -= GATE_REASONS
    for reason in PRIMARY_REASON_ORDER:
        if reason in fs:
            return reason
    return failures[0] if failures else "unknown"


def _strength_stats(values: Sequence[int]) -> Dict[str, Any]:
    vals = [int(v) for v in values]
    if not vals:
        return {"n": 0, "p50": None, "p90": None, "p99": None,
                "mean": None, "min": None, "max": None}
    return {
        "n": len(vals),
        "p50": percentile(vals, 0.50),
        "p90": percentile(vals, 0.90),
        "p99": percentile(vals, 0.99),
        "mean": round(sum(vals) / len(vals), 4),
        "min": min(vals),
        "max": max(vals),
    }


def _iter_lines(obs_dir: Path, pattern: str, limit: int
                ) -> Iterator[Tuple[Path, int, str]]:
    """按文件名排序逐行产出；``limit`` 为输入行数上限（0=不限）。"""
    files = sorted(obs_dir.glob(pattern))
    read = 0
    for path in files:
        try:
            fh = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with fh:
            for lineno, line in enumerate(fh, 1):
                if limit and read >= limit:
                    return
                read += 1
                yield path, lineno, line


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_import(obs_dir: str | Path = DEFAULT_OBS_DIR,
               cards_path: str | Path = DEFAULT_CARDS,
               *, allow_unready: bool = False, max_board: int = 7,
               min_board: int = 0, limit: int = 0, dedup: bool = True,
               pattern: str = "*.jsonl") -> Tuple[List[BoardSnapshot], Dict[str, Any]]:
    """执行导入，返回 ``(快照列表, 统计 dict)``；不写文件。"""
    card_index, card_meta = load_card_index(cards_path)
    obs_path = Path(obs_dir)
    files = sorted(obs_path.glob(pattern))
    if not files:
        raise FileNotFoundError(f"没有匹配的观测文件: {obs_path}/{pattern}")

    t0 = time.time()
    entries: List[BoardSnapshot] = []
    seen: set = set()

    total = 0
    parsed = 0
    files_read: set = set()
    drop = Counter()
    gate = Counter()
    structural = Counter()
    turns_input = Counter()
    flags = Counter()
    stages = Counter()
    splits = Counter()
    perspectives = Counter()
    builds = Counter()
    board_sizes_input = Counter()

    mapping = Counter()
    unmapped_unique = Counter()

    for path, _lineno, line in _iter_lines(obs_path, pattern, int(limit)):
        total += 1
        files_read.add(path)
        if not line.strip():
            drop["empty_line"] += 1
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            drop["parse_error"] += 1
            continue
        parsed += 1

        snap, failures, m = parse_snapshot(
            row, card_index=card_index, source_file=path,
            allow_unready=allow_unready, max_board=max_board, min_board=min_board)

        # 映射/输入分布：无论该行是否被质量门筛掉都统计。
        mapping["minions_seen"] += m["minions_seen"]
        mapping["board_minions"] += m["board_minions"]
        mapping["unmapped_minions"] += m["unmapped_minions"]
        mapping["incomplete_stats"] += m["incomplete_stats"]
        mapping["known_hand"] += m["known_hand"]
        mapping["known_hand_unmapped"] += m["known_hand_unmapped"]
        mapping[f"hero_{m['hero_mode']}"] += 1
        for cid in m["unmapped_ids"]:
            unmapped_unique[cid] += 1
        if m["unmapped_minions"]:
            mapping["rows_with_unmapped_minion"] += 1

        if isinstance(row, dict):
            turn = row.get("turn")
            if _is_int(turn):
                turns_input[int(turn)] += 1
            board = row.get("board")
            if isinstance(board, list):
                board_sizes_input[len(board)] += 1
            for k, ctr in (("stage", stages), ("split", splits),
                           ("perspective", perspectives)):
                if isinstance(row.get(k), str):
                    ctr[row[k]] += 1
            if _is_int(row.get("build_number")):
                builds[int(row["build_number"])] += 1
            qf = row.get("quality_flags")
            if isinstance(qf, list):
                for q in qf:
                    flags[str(q)] += 1
            for r in failures:
                if r in GATE_REASONS:
                    gate[r] += 1
                else:
                    structural[r] += 1

        if snap is None:
            drop[_pick_primary(failures, allow_unready)] += 1
            continue

        if dedup:
            key = snap.signature()
            if key in seen:
                drop["duplicate"] += 1
                continue
            seen.add(key)
        entries.append(snap)

    entries.sort(key=lambda e: (e.turn, e.strength, e.signature()))

    elapsed = time.time() - t0
    turns_kept = Counter(e.turn for e in entries)
    board_sizes_kept = Counter(len(e.board) for e in entries)
    strengths = [e.strength for e in entries]

    per_turn: Dict[str, Any] = {}
    by_turn: Dict[int, List[int]] = {}
    for e in entries:
        by_turn.setdefault(e.turn, []).append(e.strength)
    for turn in sorted(by_turn):
        vals = by_turn[turn]
        per_turn[str(turn)] = {
            "n": len(vals),
            "p50": percentile(vals, 0.50),
            "p90": percentile(vals, 0.90),
            "min": min(vals),
            "max": max(vals),
        }

    mapping_out = {
        "card_table": _rel(cards_path),
        "card_count": int(card_meta.get("count", 0)),
        "client_version": card_meta.get("client_version"),
        "minions_seen": mapping["minions_seen"],
        "board_minions_mapped": mapping["board_minions"],
        "unmapped_minion_occurrences": mapping["unmapped_minions"],
        "rows_with_unmapped_minion": mapping["rows_with_unmapped_minion"],
        "mapping_failure_rate": (
            round(mapping["unmapped_minions"] / mapping["minions_seen"], 8)
            if mapping["minions_seen"] else 0.0),
        "unmapped_unique_card_ids": [
            {"card_id": cid, "count": n}
            for cid, n in unmapped_unique.most_common(50)
        ],
        "hero_direct": mapping["hero_direct"],
        "hero_via_skin_base": mapping["hero_skin_base"],
        "hero_unmapped": mapping["hero_unmapped"],
        "hero_none": mapping["hero_none"],
        "known_hand_cards": mapping["known_hand"],
        "known_hand_unmapped": mapping["known_hand_unmapped"],
        "incomplete_stats_occurrences": mapping["incomplete_stats"],
    }

    stats: Dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_sec": round(elapsed, 3),
        "source": {
            "tag": SOURCE_TAG,
            "obs_dir": _rel(obs_path),
            "pattern": pattern,
            "files": len(files),
            "files_read": len(files_read),
            "lines": total,
            "bytes": 0,
        },
        "config": {
            "quality_gate": "relaxed" if allow_unready else "strict",
            "allow_unready": bool(allow_unready),
            "max_board": int(max_board),
            "min_board": int(min_board),
            "dedup": bool(dedup),
            "limit": int(limit),
            "source_tag": SOURCE_TAG,
        },
        "rows": {
            "total": total,
            "parsed": parsed,
            "kept": len(entries),
            "dropped": total - len(entries),
        },
        "drop_reasons": dict(sorted(drop.items(), key=lambda kv: (-kv[1], kv[0]))),
        "gate_failures": dict(sorted(gate.items(), key=lambda kv: (-kv[1], kv[0]))),
        "structural_failures": dict(sorted(structural.items(),
                                          key=lambda kv: (-kv[1], kv[0]))),
        "mapping": mapping_out,
        "turns": {str(k): v for k, v in sorted(turns_kept.items())},
        "turns_input": {str(k): v for k, v in sorted(turns_input.items())},
        "strength": _strength_stats(strengths),
        "per_turn_strength": per_turn,
        "board_sizes": {str(k): v for k, v in sorted(board_sizes_kept.items())},
        "board_sizes_input": {str(k): v for k, v in sorted(board_sizes_input.items())},
        "stages": dict(stages.most_common()),
        "splits": dict(splits.most_common()),
        "perspectives": dict(perspectives.most_common()),
        "builds": {str(k): v for k, v in sorted(builds.items())},
        "quality_flags": dict(flags.most_common()),
    }
    # 统计总字节（只对读到的文件计一次，避免重复 sum）
    stats["source"]["bytes"] = sum(p.stat().st_size for p in files_read)
    return entries, stats


def write_jsonl(entries: Sequence[BoardSnapshot], path: str | Path) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e.to_record(), ensure_ascii=False) + "\n")
    return str(out)


def write_stats(stats: Dict[str, Any], path: str | Path) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    return str(out)


def print_stats(stats: Dict[str, Any], out_path: Optional[str] = None) -> None:
    s = stats["source"]
    rows = stats["rows"]
    m = stats["mapping"]
    mode = stats["config"]["quality_gate"]
    print("=== 真实战团库导入统计 ===")
    print(f"模式        : {mode}"
          + ("（--allow-unready，仅诊断，不是 library_ready 数据）"
             if mode == "relaxed" else "（library_ready & hidden_counters_complete）"))
    print(f"输入        : {s['files']} 文件 / {s['lines']} 行 / "
          f"{s['bytes'] / 1024 / 1024:.1f} MB")
    print(f"保留        : {rows['kept']} 条（解析 {rows['parsed']} 行，"
          f"丢弃 {rows['dropped']}）")
    if out_path:
        print(f"库文件      : {out_path}")
    print("丢弃原因    : " + (", ".join(f"{k}={v}" for k, v in
                                        stats["drop_reasons"].items()) or "无"))
    if stats["gate_failures"]:
        print("质量门失败  : " + ", ".join(f"{k}={v}" for k, v in
                                          stats["gate_failures"].items()))
    print(f"卡表        : {m['card_count']} 张（{m['card_table']}）")
    print(f"随从映射    : {m['board_minions_mapped']}/{m['minions_seen']} 成功，"
          f"失败 {m['unmapped_minion_occurrences']} "
          f"（{m['mapping_failure_rate'] * 100:.4f}%），"
          f"受影响行 {m['rows_with_unmapped_minion']}")
    print(f"英雄映射    : direct={m['hero_direct']} skin_base={m['hero_via_skin_base']} "
          f"unmapped={m['hero_unmapped']} none={m['hero_none']}")
    print(f"已知手牌    : {m['known_hand_cards']} 张，未映射 {m['known_hand_unmapped']}")
    turns = stats["turns"]
    print("turn 分布   : " + (", ".join(f"{k}:{v}" for k, v in turns.items()) or "无"))
    st = stats["strength"]
    if st["n"]:
        print(f"强度        : n={st['n']} p50={st['p50']} p90={st['p90']} "
              f"p99={st['p99']} mean={st['mean']} min={st['min']} max={st['max']}")
        print("每 turn p50/p90 : " + ", ".join(
            f"{t}:{v['p50']}/{v['p90']}"
            for t, v in stats["per_turn_strength"].items()))
    else:
        print("强度        : 无保留条目（严格门未通过）")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="真实 10k+ MMR 战团库导入（strict 质量门默认开启）")
    p.add_argument("--obs-dir", default=str(DEFAULT_OBS_DIR),
                   help="observations 目录（默认 data/real_library/obs/observations）")
    p.add_argument("--cards", default=str(DEFAULT_CARDS),
                   help="引擎卡表 cards.json（只读）")
    p.add_argument("--out", default=str(DEFAULT_OUT),
                   help="输出 JSONL（默认 data/real_library/library_real.jsonl）")
    p.add_argument("--stats-json", default=None,
                   help="统计 JSON 输出路径")
    p.add_argument("--limit", type=int, default=0,
                   help="只读前 N 行（调试用，0=全量）")
    p.add_argument("--allow-unready", action="store_true",
                   help="诊断模式：允许 library_ready/hidden_counters_complete "
                        "为 false，记录标记为 degraded")
    p.add_argument("--max-board", type=int, default=7,
                   help="牌面随从上限（BG 上限 7；超出视为解析损坏，默认 7）")
    p.add_argument("--min-board", type=int, default=0,
                   help="牌面随从下限（默认 0）")
    p.add_argument("--no-dedup", action="store_true", help="关闭 (turn, board) 去重")
    p.add_argument("--pattern", default="*.jsonl", help="观测文件 glob（默认 *.jsonl）")
    p.add_argument("--stats", action="store_true", help="打印统计")
    p.add_argument("--dry-run", action="store_true", help="不写输出文件")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    entries, stats = run_import(
        args.obs_dir, args.cards,
        allow_unready=args.allow_unready,
        max_board=args.max_board,
        min_board=args.min_board,
        limit=args.limit,
        dedup=not args.no_dedup,
        pattern=args.pattern,
    )
    out_written = None
    if not args.dry_run:
        out_written = write_jsonl(entries, args.out)
        if args.stats_json:
            write_stats(stats, args.stats_json)
    if args.stats or args.dry_run:
        print_stats(stats, out_written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
