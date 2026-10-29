#!/usr/bin/env python3
"""真实 10k+ MMR 观测 vs 自采镜像快照库的**牌面强度校准**（离线统计，不训练 / 不用 GPU / 不依赖引擎）。

数据：

- 真实观测：``data/real_library/obs/observations/*.jsonl``（Firestone 可见牌面重建）；
- 自采快照：``runs/library/snaps_champ/snap_*.json.gz``，用
  :class:`hsbg.az.train.mirror_snapshots.MirrorSnapshotPool` 读取（不重复实现解析）。

口径（见 ``docs/STRENGTH_CALIBRATION.md``）：

- 只取真实数据 ``stage == "recruitment_end_at_phase_switch"`` 的行；其余 stage 丢弃并计数；
- ``strength = Σ(attack + health)``（自采库 ``strength = Σ(atk + hp)``，与
  :func:`hsbg.az.train.mirror_snapshots.board_strength` 同一定义）；
- 按 ``turn`` 分桶，输出 ``count / p50 / p75 / p90 / p99 / max``；
- 输出 ``{"<turn>": {"real": {...}, "ours": {...}, "ratio_p50": ..., "ratio_p90": ...},
  "_meta": {...}}``；``ratio_* = real / ours``（>1 表示我们比真实弱）。

用法::

  PYTHONPATH=rust/python:. python scripts/calibrate_strength.py --report
  PYTHONPATH=rust/python:. python scripts/calibrate_strength.py --out /tmp/cal.json
"""

from __future__ import annotations

import argparse
import bisect
import glob
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 真实观测里「招募结束、战斗开始前」的阶段名（另一个 first_attack_* 阶段必须丢弃）。
STAGE_REAL = "recruitment_end_at_phase_switch"
#: 自采快照的阶段名（``mirror_snapshots.STAGE_EOT``），仅用于文档/断言。
STAGE_OURS = "recruitment_end_before_combat"

DEFAULT_REAL_DIR = ROOT / "data" / "real_library" / "obs" / "observations"
DEFAULT_SNAP_DIR = ROOT / "runs" / "library" / "snaps_champ"
DEFAULT_OUT = ROOT / "data" / "real_library" / "strength_calibration.json"

#: 汇报的分位数（与任务要求一致）。
QUANTILES: Tuple[Tuple[str, float], ...] = (
    ("p50", 0.50), ("p75", 0.75), ("p90", 0.90), ("p99", 0.99))
#: 采样建议用到的目标分位（真实侧）。
TARGET_QUANTILES: Tuple[Tuple[str, float], ...] = (
    ("p50", 0.50), ("p75", 0.75), ("p90", 0.90))


# ────────────────────────── 纯函数 ──────────────────────────


def percentile(sorted_values: List[float], q: float) -> Optional[float]:
    """线性插值分位数（与 numpy 默认一致）；空序列返回 ``None``。

    ``sorted_values`` 必须已升序（调用方用 :func:`strength_stats` 保证）。
    """
    s = sorted_values
    if not s:
        return None
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * float(q)
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def strength_stats(values: List[int]) -> Dict[str, Any]:
    """一个 turn 桶的强度统计：``count / p50 / p75 / p90 / p99 / max``。"""
    s = sorted(int(v) for v in values)
    if not s:
        return {"count": 0, "p50": None, "p75": None, "p90": None, "p99": None,
                "max": None}
    out: Dict[str, Any] = {"count": len(s)}
    for name, q in QUANTILES:
        out[name] = round(float(percentile(s, q)), 4)
    out["max"] = int(s[-1])
    return out


def real_board_strength(board: Any) -> Tuple[int, bool]:
    """真实行的牌面强度 ``Σ(attack + health)``；含非法数值时返回 ``(0, False)``。

    真实 jsonl 的字段名是 ``attack`` / ``health``；自采引擎 JSON 是 ``atk`` / ``hp``，
    两者语义相同（当前攻/当前血），因此与 ``mirror_snapshots.board_strength`` 同定义。
    """
    if not isinstance(board, list):
        return 0, False
    total = 0
    for m in board:
        if not isinstance(m, dict):
            return 0, False
        a = m.get("attack")
        h = m.get("health")
        if a is None or h is None or isinstance(a, bool) or isinstance(h, bool):
            return 0, False
        try:
            total += int(a) + int(h)
        except (TypeError, ValueError):
            return 0, False
    return total, True


def quantile_of_value(sorted_values: List[int], target: Optional[float]) -> Optional[float]:
    """``target`` 在自采分布中的经验分位（0..100，线性插值）。

    用于把「真实 p50/p75/p90 的强度」映射成「我们库该取哪个分位」：返回 100 表示
    我们的最大值都低于该目标（重采样不可达）。空序列返回 ``None``。
    """
    s = sorted_values
    if not s or target is None:
        return None
    n = len(s)
    t = float(target)
    if n == 1:
        return 0.0 if t <= float(s[0]) else 100.0
    if t <= float(s[0]):
        return 0.0
    if t >= float(s[-1]):
        return 100.0
    i = bisect.bisect_right(s, t) - 1
    if i >= n - 1:
        return 100.0
    if s[i + 1] == s[i]:
        return round(100.0 * i / (n - 1), 4)
    frac = (t - float(s[i])) / (float(s[i + 1]) - float(s[i]))
    return round(100.0 * (i + frac) / (n - 1), 4)


def _ratio(real: Optional[float], ours: Optional[float]) -> Optional[float]:
    """``real / ours``；任一侧缺失或我们为 0 时返回 ``None``。"""
    if real is None or ours is None or float(ours) == 0.0:
        return None
    return round(float(real) / float(ours), 4)


def _rel(path: Any) -> str:
    """尽量输出相对仓库根的路径（报告/JSON 用）。"""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return str(p)


# ────────────────────────── 读取 ──────────────────────────


def collect_real(real_dir: Any) -> Tuple[Dict[int, List[int]], Dict[str, Any]]:
    """读取真实观测目录，返回 ``(turn -> strengths, meta)``。

    - 非 ``STAGE_REAL`` 的行丢弃，按 stage 计数；
    - 缺 ``turn`` / 缺数值（``attack``/``health`` 为 null）的行跳过并计数；
    - 空牌面保留（strength 0）；``board > 7`` 保留但计数（下游可在文档里标注噪声）。
    """
    by_turn: Dict[int, List[int]] = {}
    stage_counts: Counter = Counter()
    meta: Dict[str, Any] = {
        "source": _rel(real_dir), "files": 0, "rows_total": 0, "rows_used": 0,
        "bad_json": 0, "missing_turn": 0, "invalid_minion_stats": 0,
        "empty_board": 0, "board_over_7": 0, "stage_counts": stage_counts,
    }
    pattern = os.path.join(str(real_dir), "*.jsonl")
    for path in sorted(glob.glob(pattern)):
        meta["files"] += 1
        try:
            fh = open(path, "r", encoding="utf-8")
        except OSError:
            meta["bad_json"] += 1
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                meta["rows_total"] += 1
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    meta["bad_json"] += 1
                    continue
                if not isinstance(row, dict):
                    meta["bad_json"] += 1
                    continue
                stage = str(row.get("stage", "<missing>"))
                stage_counts[stage] += 1
                if stage != STAGE_REAL:
                    continue
                turn = row.get("turn")
                if not isinstance(turn, int) or isinstance(turn, bool) or turn <= 0:
                    meta["missing_turn"] += 1
                    continue
                board = row.get("board")
                if not isinstance(board, list):
                    meta["invalid_minion_stats"] += 1
                    continue
                if not board:
                    meta["empty_board"] += 1
                elif len(board) > 7:
                    meta["board_over_7"] += 1
                strength, ok = real_board_strength(board)
                if not ok:
                    meta["invalid_minion_stats"] += 1
                    continue
                by_turn.setdefault(int(turn), []).append(int(strength))
                meta["rows_used"] += 1
    meta["stage_counts"] = dict(sorted(stage_counts.items()))
    return by_turn, meta


def collect_ours(snap_dir: Any) -> Tuple[Dict[int, List[int]], Dict[str, Any]]:
    """用 ``MirrorSnapshotPool`` 读取自采快照，返回 ``(turn -> strengths, meta)``。

    注意：这里统计**全部帧**（同一 ``(turn, seat)`` 的多个来源都计入），因此
    ``sample=`` 模式只影响 :meth:`MirrorSnapshotPool.get`，不影响本分布。
    """
    from hsbg.az.train.mirror_snapshots import MirrorSnapshotPool

    pool = MirrorSnapshotPool(str(snap_dir))
    by_turn: Dict[int, List[int]] = {}
    for frames in pool.index.values():
        for fr in frames:
            by_turn.setdefault(int(fr.turn), []).append(int(fr.strength))
    stats = pool.stats()
    turns = sorted(by_turn)
    meta: Dict[str, Any] = {
        "source": _rel(snap_dir),
        "reader": "hsbg.az.train.mirror_snapshots.MirrorSnapshotPool",
        "stage": STAGE_OURS,
        "sample_mode": "all",
        "sample_note": ("全部帧直接统计；MirrorSnapshotPool 的 sample= 只影响 get()，"
                        "不影响本分布"),
        "files": int(stats.get("files", pool.files)),
        "frames": int(stats.get("frames", pool.frames)),
        "bad_files": int(pool.bad_files),
        "keys": int(len(pool.index)),
        "schema_versions": dict(sorted((pool.schema_versions or {}).items())),
        "turn_min": turns[0] if turns else None,
        "turn_max": turns[-1] if turns else None,
    }
    return by_turn, meta


# ────────────────────────── 汇总 ──────────────────────────


def build_calibration(real: Dict[int, List[int]], ours: Dict[int, List[int]],
                      real_meta: Dict[str, Any],
                      ours_meta: Dict[str, Any]) -> Dict[str, Any]:
    """构造输出 JSON：每个 turn 一个 ``{real, ours, ratio_p50, ratio_p90}`` 条目。"""
    out: Dict[str, Any] = {
        "_meta": {
            "schema": "hsbg.strength_calibration",
            "version": 1,
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stage_real": STAGE_REAL,
            "stage_ours": STAGE_OURS,
            "strength_definition": ("real: sum(attack+health) over board; "
                                    "ours: sum(atk+hp) over board"),
            "ratio_definition": "ratio = real / ours (>1 表示我们偏弱)",
            "percentiles": [name for name, _ in QUANTILES],
            "real": real_meta,
            "ours": ours_meta,
        }
    }
    for turn in sorted(set(real) | set(ours)):
        rs = strength_stats(real.get(turn, []))
        os_ = strength_stats(ours.get(turn, []))
        ours_sorted = sorted(int(v) for v in ours.get(turn, []))
        mapping: Dict[str, Optional[float]] = {}
        reachable: Dict[str, Optional[bool]] = {}
        for name, _ in TARGET_QUANTILES:
            target = rs.get(name)
            q = quantile_of_value(ours_sorted, target)
            mapping[name] = q
            if target is None:
                reachable[name] = None
            elif not ours_sorted:
                reachable[name] = False
            else:
                reachable[name] = bool(float(target) <= float(ours_sorted[-1]))
        out[str(int(turn))] = {
            "real": rs,
            "ours": os_,
            "ratio_p50": _ratio(rs["p50"], os_["p50"]),
            "ratio_p90": _ratio(rs["p90"], os_["p90"]),
            "ours_quantile_for_real": mapping,
            "reachable": reachable,
        }
    return out


def _fmt(value: Any, nd: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{nd}f}"
    return str(value)


def format_report(cal: Dict[str, Any]) -> str:
    """``--report`` 的对照表：turn / 真实分位 / 我们的分位 / 比值 / 建议分位。"""
    lines: List[str] = []
    lines.append("turn  real_n  real_p50  real_p75  real_p90  real_p99  real_max"
                 " | ours_n  ours_p50  ours_p75  ours_p90  ours_p99"
                 " | r_p50  r_p90 | q50  q90")
    lines.append("-" * 150)
    for key in sorted((k for k in cal if not k.startswith("_")), key=int):
        e = cal[key]
        r, o = e["real"], e["ours"]
        qr = e.get("ours_quantile_for_real") or {}
        lines.append(
            f"{int(key):>4}  {_fmt(r['count']):>6}  {_fmt(r['p50']):>8}  {_fmt(r['p75']):>8}  "
            f"{_fmt(r['p90']):>8}  {_fmt(r['p99']):>9}  {_fmt(r['max']):>8}"
            f" | {_fmt(o['count']):>6}  {_fmt(o['p50']):>8}  {_fmt(o['p75']):>8}  "
            f"{_fmt(o['p90']):>8}  {_fmt(o['p99']):>9}"
            f" | {_fmt(e['ratio_p50'], 3):>5}  {_fmt(e['ratio_p90'], 3):>5}"
            f" | {_fmt(qr.get('p50'), 1):>4}  {_fmt(qr.get('p90'), 1):>4}"
        )
    return "\n".join(lines)


# ────────────────────────── CLI ──────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="真实 10k+ MMR 观测 vs 自采镜像快照库的牌面强度校准")
    ap.add_argument("--real-dir", default=str(DEFAULT_REAL_DIR),
                    help="真实观测 jsonl 目录")
    ap.add_argument("--snap-dir", default=str(DEFAULT_SNAP_DIR),
                    help="自采快照目录（snap_*.json.gz）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出 JSON 路径")
    ap.add_argument("--report", action="store_true", help="打印分 turn 对照表")
    ap.add_argument("--quiet", action="store_true", help="只写文件，不打印摘要")
    args = ap.parse_args(argv)

    real_dir = Path(args.real_dir)
    snap_dir = Path(args.snap_dir)
    if not real_dir.is_dir():
        print(f"[error] 真实观测目录不存在: {real_dir}", file=sys.stderr)
        return 2
    if not snap_dir.is_dir():
        print(f"[error] 自采快照目录不存在: {snap_dir}", file=sys.stderr)
        return 2

    real, real_meta = collect_real(real_dir)
    ours, ours_meta = collect_ours(snap_dir)
    cal = build_calibration(real, ours, real_meta, ours_meta)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(cal, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    if not args.quiet:
        stages = ", ".join(f"{k}={v}" for k, v in real_meta["stage_counts"].items())
        print(f"[real] files={real_meta['files']} rows={real_meta['rows_total']} "
              f"used={real_meta['rows_used']} | stages: {stages}")
        print(f"[real] skipped invalid_minion_stats={real_meta['invalid_minion_stats']} "
              f"missing_turn={real_meta['missing_turn']} bad_json={real_meta['bad_json']} "
              f"empty_board={real_meta['empty_board']} board_over_7={real_meta['board_over_7']}")
        print(f"[ours] files={ours_meta['files']} frames={ours_meta['frames']} "
              f"keys={ours_meta['keys']} turns={ours_meta['turn_min']}..{ours_meta['turn_max']}")
        print(f"[out] {_rel(out)}")

    if args.report:
        print()
        print(format_report(cal))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
