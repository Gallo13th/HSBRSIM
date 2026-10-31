#!/usr/bin/env python3
"""合并 / 切分场面题池：按 ``obs.sha256`` 去重，输出统计（各 turn 题数 + Δ 分布）。

为什么需要合并：``problems_s14_s15.jsonl`` 是 s14 **训练分布**（人类战团 5 席 p0.9 +
镜像 2 席）与**弱对手**（human p0.5×3、无镜像）两次 rollout 的合并池，t14/t15 只有
22/12 题；``problems_late_big.jsonl`` 是弱对手分布**扩容**（t14 ≥120 / t15 ≥100）。
训练侧只读一个 ``--problem-pool``，所以这里按 obs 内容做去重合并，并保留来源标注。

去重口径：``obs.sha256``（观测 = features + cards + 合法掩码，f32 逐位可复现；同 sha
= 同一局面的同一决策点，重复采样无信息增益）。冲突（同 sha、不同 label）会计数报出。

用法::

    PYTHONPATH=rust/python:. python scripts/merge_board_problems.py \
      --inputs data/board_problems/problems_s14_s15.jsonl \
               data/board_problems/problems_late_big.jsonl \
      --out data/board_problems/problems_all.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from hsbg.az.train.board_problems import LATE_TURN_MIN, problem_strength_delta  # noqa: E402


def _load(path: str):
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _delta(row) -> float:
    d = problem_strength_delta(row)
    return float(d) if math.isfinite(d) else float("nan")


def summarize(rows, *, source: str = "") -> dict:
    n = len(rows)
    by_turn = {}
    for r in rows:
        t = str(int(r.get("turn") or 0))
        by_turn[t] = by_turn.get(t, 0) + 1
    delta = np.asarray([_delta(r) for r in rows], dtype=np.float64)
    delta = delta[np.isfinite(delta)]
    survived = [int((r.get("label") or {}).get("survived") or 0) for r in rows]
    late = {t: int(c) for t, c in sorted(by_turn.items(), key=lambda kv: int(kv[0]))
            if int(t) >= LATE_TURN_MIN}
    # 逐 turn 的 Δ 分布（p50/mean）
    per_turn_delta = {}
    for t in sorted(by_turn, key=lambda x: int(x)):
        vals = [d for r, d in ((r, _delta(r)) for r in rows
                               if str(int(r.get("turn") or 0)) == t)
                if math.isfinite(d)]
        if vals:
            per_turn_delta[t] = {"n": len(vals),
                                 "p50": round(float(np.percentile(vals, 50)), 4),
                                 "mean": round(float(np.mean(vals)), 4)}
    tags = {}
    for r in rows:
        for tag in (r.get("tags") or []):
            tags[str(tag)] = tags.get(str(tag), 0) + 1
    return {
        "source": source,
        "problems": int(n),
        "by_turn": {t: int(c) for t, c in sorted(by_turn.items(),
                                                 key=lambda kv: int(kv[0]))},
        "late_turn_by_turn": late,
        "late_turn_problems": int(sum(late.values())),
        "late_turn_min": int(LATE_TURN_MIN),
        "strength_delta_p50": round(float(np.percentile(delta, 50)), 4) if delta.size else 0.0,
        "strength_delta_p90": round(float(np.percentile(delta, 90)), 4) if delta.size else 0.0,
        "strength_delta_mean": round(float(delta.mean()), 4) if delta.size else 0.0,
        "strength_delta_by_turn": per_turn_delta,
        "label_survived_rate": round(float(np.mean(survived)), 4) if survived else 0.0,
        "by_tag": dict(sorted(tags.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="合并场面题池（按 obs sha256 去重）")
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stats-out", default="")
    ap.add_argument("--meta-out", default="")
    args = ap.parse_args()

    merged = []
    seen = {}
    per_source = []
    conflicts = 0
    for path in args.inputs:
        rows = _load(str(path))
        per_source.append(summarize(rows, source=str(path)))
        added = dup = 0
        for r in rows:
            sha = str(((r.get("obs") or {}).get("sha256")) or "")
            if not sha:
                continue  # 无观测哈希的行不参与去重（也不丢）
            src = os.path.basename(str(path))
            if sha in seen:
                dup += 1
                prev = seen[sha]
                if (float(_delta(prev)) != float(_delta(r))
                        or int((prev.get("label") or {}).get("strength_before") or -1)
                        != int((r.get("label") or {}).get("strength_before") or -2)):
                    conflicts += 1
                prev.setdefault("dup_sources", []).append(src)
                continue
            r = dict(r)
            r["source_pool"] = src
            r["dup_sources"] = []
            seen[sha] = r
            merged.append(r)
            added += 1
        print(f"[merge] {path}: rows={len(rows)} added={added} dup={dup}",
              flush=True)

    # 重新编号 problem_id（跨池唯一；保留原 id 到 origin_problem_id）
    for i, r in enumerate(merged):
        r["origin_problem_id"] = str(r.get("problem_id"))
        r["problem_id"] = f"bp-{i:06d}"

    stats = {
        "schema": "board_problems_merge_v1",
        "inputs": [str(p) for p in args.inputs],
        "sources": per_source,
        "problems": len(merged),
        "duplicates_dropped": int(sum(len(r.get("dup_sources") or []) for r in merged)),
        "duplicate_conflicts": int(conflicts),
        "merged": summarize(merged, source="merged"),
        "note": "按 obs.sha256 去重；source_pool 记录首个来源池，dup_sources 记录重复出现池",
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    tmp = str(args.out) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in merged:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, args.out)
    meta_path = str(args.meta_out or "") or (os.path.splitext(str(args.out))[0]
                                             + ".meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"[merge] wrote {len(merged)} problems -> {args.out} (meta={meta_path})",
          flush=True)
    print(json.dumps({k: stats[k] for k in ("problems", "duplicates_dropped",
                                            "duplicate_conflicts")},
                     ensure_ascii=False, indent=2), flush=True)
    print(json.dumps(stats["merged"]["by_turn"], ensure_ascii=False), flush=True)
    print(json.dumps(stats["merged"]["late_turn_by_turn"], ensure_ascii=False),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
