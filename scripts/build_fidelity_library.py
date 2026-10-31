#!/usr/bin/env python3
"""把真实 10k+ MMR 观测补全为**准完整状态**库（board + hand + 可推断 counters）。

输入：``data/real_library/obs/observations/*.jsonl``（376 文件 / 13,120 行 Firestone
可见牌面重建）。输出：

- ``data/real_library/library_real_quasi_full.jsonl``：一行一个 EOT 帧，
  ``board_detail`` 带 golden / kw / bonus_kw / shield_max，``hand`` 带手牌，``tier``
  来自 hero tag 1377；
- ``data/real_library/library_real_quasi_full_stats.json``：可得性矩阵的分子/分母
  （写进 ``docs/FIDELITY_INJECTION.md`` 的数字都从这里来）。

与 ``library_real_degraded.jsonl`` 的关系：**不替代**它。旧库是 board-only（4,284 行），
``human_board_pool`` 默认仍读旧库、行为逐位不变；本脚本只新增一个可选数据源，
``--human-boards ..._quasi_full.jsonl --human-board-fidelity hand|full`` 才用它。

用法::

    PYTHONPATH=rust/python:. python scripts/build_fidelity_library.py --stats
    PYTHONPATH=rust/python:. python scripts/build_fidelity_library.py \
        --out data/real_library/library_real_quasi_full.jsonl \
        --stats-json data/real_library/library_real_quasi_full_stats.json --stats
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.human_obs_full import (  # noqa: E402
    EOT_STAGE, FIELDS_INJECTABLE, FIELDS_UNAVAILABLE, KW_BITS, KW_NAMES,
    TAG_TO_KW, load_card_meta, parse_observation,
)

DEFAULT_OBS_DIR = os.path.join(ROOT, "data", "real_library", "obs", "observations")
DEFAULT_OUT = os.path.join(ROOT, "data", "real_library", "library_real_quasi_full.jsonl")
DEFAULT_STATS = os.path.join(
    ROOT, "data", "real_library", "library_real_quasi_full_stats.json")

SOURCE = "human_obs_quasi_full"
_SKIN_RE = re.compile(r"_SKIN_[A-Z0-9]+$")


def _pct(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(float(v) for v in values)
    k = (len(s) - 1) * float(q)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 4)


def _rel(path: str) -> str:
    try:
        return os.path.relpath(os.path.abspath(path), ROOT)
    except ValueError:
        return os.path.abspath(path)


def payload_to_row(payload: Dict[str, Any], *, source_file: str = "") -> Dict[str, Any]:
    """准完整 payload -> 库行（``human_board_pool`` 读 ``board`` + ``board_detail``）。"""
    board = payload.get("board") or []
    strength = int(sum(int(b["atk"]) + int(b["hp"]) for b in board))
    hand = payload.get("hand") or []
    hero = payload.get("hero_card_id")
    hero_cid = None
    if isinstance(hero, str):
        meta = load_card_meta()
        if hero in meta:
            hero_cid = int(meta[hero]["cid"])
        else:
            base = _SKIN_RE.sub("", hero)
            if base in meta:
                hero_cid = int(meta[base]["cid"])
    return {
        "turn": int(payload["turn"]),
        "strength": strength,
        "board": [list(x) for x in (payload.get("board_flat") or [])],
        "board_detail": [
            {"card": int(b["card"]), "card_id": b.get("card_id"),
             "atk": int(b["atk"]), "hp": int(b["hp"]),
             "golden": bool(b.get("golden")), "kw": int(b.get("kw") or 0),
             "bonus_kw": int(b.get("bonus_kw") or 0),
             "shield_max": int(b.get("shield_max") or 1)}
            for b in board],
        "hand": hand,
        "hand_available": bool(payload.get("hand_available")),
        "hand_n": len(hand),
        "tier": payload.get("tier"),
        "hero": hero_cid,
        "hero_card_id": hero,
        "source": SOURCE,
        "schema": payload.get("schema"),
        "schema_version": payload.get("schema_version"),
        "game_id": payload.get("game_id"),
        "split": payload.get("split"),
        "stage": payload.get("stage"),
        "perspective": payload.get("perspective"),
        "controller": payload.get("controller"),
        "build_number": payload.get("build_number"),
        "availability": payload.get("availability") or {},
        "file": _rel(source_file),
    }


def signature(row: Dict[str, Any]) -> Tuple[Any, ...]:
    """去重签名：turn + board（card/atk/hp/golden/kw）+ hand + tier。"""
    b = tuple((int(m["card"]), int(m["atk"]), int(m["hp"]), bool(m.get("golden")),
               int(m.get("kw") or 0)) for m in (row.get("board_detail") or []))
    h = tuple((int(x["card"]), str(x.get("kind"))) for x in (row.get("hand") or []))
    return (int(row["turn"]), b, h, row.get("tier"))


def _iter_rows(obs_dir: str, pattern: str = "*.jsonl"):
    files = sorted(f for f in os.listdir(obs_dir) if f.endswith(".jsonl"))
    for fn in files:
        path = os.path.join(obs_dir, fn)
        try:
            fh = open(path, "r", encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield path, json.loads(line)
                except json.JSONDecodeError:
                    yield path, None


def run(obs_dir: str = DEFAULT_OBS_DIR, *, out: str = DEFAULT_OUT,
        stats_path: Optional[str] = DEFAULT_STATS, dedup: bool = True,
        max_board: int = 7, limit: int = 0, t_lo: int = 1, t_hi: int = 99
        ) -> Dict[str, Any]:
    t0 = time.time()
    meta = load_card_meta()
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    total = 0
    parsed = 0
    drop = Counter()
    stage = Counter()
    persp = Counter()
    builds = Counter()
    files = set()
    kw_hist = Counter()
    per_turn = Counter()
    hand_n_hist = Counter()
    n_hand_avail = 0
    n_tier = 0
    n_golden_frames = 0
    kw_bits_frame: List[int] = []
    kw_val_frame: List[int] = []
    golden_frame: List[int] = []
    hand_frame: List[int] = []
    tier_hist = Counter()
    avail = Counter()
    for path, row in _iter_rows(obs_dir):
        total += 1
        files.add(path)
        if not isinstance(row, dict):
            drop["unreadable"] += 1
            continue
        parsed += 1
        stage[str(row.get("stage") or "")] += 1
        persp[str(row.get("perspective") or "")] += 1
        if isinstance(row.get("build_number"), int):
            builds[str(row["build_number"])] += 1
        if limit and len(rows) >= limit:
            break
        payload, reasons = parse_observation(row, meta, eot_only=True,
                                             max_board=int(max_board))
        if payload is None:
            drop[reasons[-1] if reasons else "unknown"] += 1
            continue
        if not (int(t_lo) <= int(payload["turn"]) <= int(t_hi)):
            drop["turn_out_of_range"] += 1
            continue
        item = payload_to_row(payload, source_file=path)
        if dedup:
            sig = signature(item)
            if sig in seen:
                drop["duplicate"] += 1
                continue
            seen.add(sig)
        for k, v in (item.get("availability") or {}).items():
            avail[f"{k}={v}"] += 1
        rows.append(item)
        per_turn[int(item["turn"])] += 1
        hand_n_hist[int(item.get("hand_n") or 0)] += 1
        n_hand_avail += int(bool(item.get("hand_available")))
        n_tier += int(item.get("tier") is not None)
        g = sum(1 for m in item["board_detail"] if m.get("golden"))
        golden_frame.append(g)
        n_golden_frames += int(g > 0)
        kb = sum(int(m.get("kw") or 0).bit_count() for m in item["board_detail"])
        kv = sum(int(m.get("kw") or 0) for m in item["board_detail"])
        kw_bits_frame.append(kb)
        kw_val_frame.append(kv)
        for m in item["board_detail"]:
            for name in KW_NAMES:
                if int(m.get("kw") or 0) & int(KW_BITS[name]):
                    kw_hist[name] += 1
        hand_frame.append(int(item.get("hand_n") or 0))
        if item.get("tier") is not None:
            tier_hist[int(item["tier"])] += 1

    rows.sort(key=lambda r: (int(r["turn"]), int(r["strength"]), signature(r)))
    stats = {
        "schema": "hsbg.human_state_quasi_full.stats",
        "schema_version": 1,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "repo": ROOT,
        "obs_dir": _rel(obs_dir),
        "files": len(files),
        "rows_input": int(total),
        "rows_parsed": int(parsed),
        "rows_kept": len(rows),
        "dedup": bool(dedup),
        "drop": {str(k): int(v) for k, v in sorted(drop.items())},
        "stage_input": {str(k): int(v) for k, v in sorted(stage.items())},
        "perspective_input": {str(k): int(v) for k, v in sorted(persp.items())},
        "build_numbers": {str(k): int(v) for k, v in sorted(builds.items())},
        "eot_stage": EOT_STAGE,
        "turns": {str(k): int(v) for k, v in sorted(per_turn.items())},
        "availability": {
            "fields": list(FIELDS_INJECTABLE),
            "unavailable": list(FIELDS_UNAVAILABLE),
            "counts": {str(k): int(v) for k, v in sorted(avail.items())},
            "frac_hand_available": round(n_hand_avail / max(1, len(rows)), 4),
            "frac_tier_observed": round(n_tier / max(1, len(rows)), 4),
        },
        "hidden_state_per_frame": {
            "kw_bits_mean": round(sum(kw_bits_frame) / max(1, len(rows)), 3),
            "kw_bits_p50": _pct(kw_bits_frame, 0.50),
            "kw_bits_p90": _pct(kw_bits_frame, 0.90),
            "kw_value_mean": round(sum(kw_val_frame) / max(1, len(rows)), 3),
            "kw_value_p50": _pct(kw_val_frame, 0.50),
            "kw_value_p90": _pct(kw_val_frame, 0.90),
            "golden_mean": round(sum(golden_frame) / max(1, len(rows)), 3),
            "frac_frames_golden": round(n_golden_frames / max(1, len(rows)), 4),
            "hand_mean": round(sum(hand_frame) / max(1, len(rows)), 3),
            "hand_p50": _pct(hand_frame, 0.50),
            "hand_p90": _pct(hand_frame, 0.90),
            "frac_frames_hand": round(sum(1 for x in hand_frame if x) / max(1, len(rows)), 4),
            "hand_n_hist": {str(k): int(v) for k, v in sorted(hand_n_hist.items())[:12]},
            "kw_hist": {str(k): int(v) for k, v in sorted(kw_hist.items())},
            "tier_hist": {str(k): int(v) for k, v in sorted(tier_hist.items())},
        },
        "tag_to_kw": {str(k): v for k, v in sorted(TAG_TO_KW.items())},
        "seconds": round(time.time() - t0, 2),
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    if stats_path:
        os.makedirs(os.path.dirname(os.path.abspath(stats_path)) or ".", exist_ok=True)
        json.dump(stats, open(stats_path, "w"), ensure_ascii=False, indent=2)
    print(f"[fid-lib] {len(rows)} 行（输入 {total}，丢弃 {sum(drop.values())}）"
          f"  {stats['seconds']}s -> {out}")
    print(f"[fid-lib] hand 可用 {stats['availability']['frac_hand_available']:.1%} / "
          f"tier 可得 {stats['availability']['frac_tier_observed']:.1%} / "
          f"金身帧 {stats['hidden_state_per_frame']['frac_frames_golden']:.1%} / "
          f"关键词帧 {sum(1 for x in kw_bits_frame if x)/max(1,len(rows)):.1%}")
    return stats


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="真实观测 -> 准完整状态库")
    ap.add_argument("--obs-dir", default=DEFAULT_OBS_DIR)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--stats-json", default=DEFAULT_STATS)
    ap.add_argument("--stats", action="store_true", help="打印/写统计")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--max-board", type=int, default=7)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--t-lo", type=int, default=1)
    ap.add_argument("--t-hi", type=int, default=99)
    return ap.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    stats = run(args.obs_dir, out=args.out,
                stats_path=(args.stats_json if args.stats else None),
                dedup=not args.no_dedup, max_board=int(args.max_board),
                limit=int(args.limit), t_lo=int(args.t_lo), t_hi=int(args.t_hi))
    if args.stats:
        print(json.dumps({k: stats[k] for k in
                          ("rows_kept", "drop", "availability",
                           "hidden_state_per_frame")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
