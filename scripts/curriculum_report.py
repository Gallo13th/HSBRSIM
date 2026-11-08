#!/usr/bin/env python3
"""小模型专家课程结果汇总：``curriculum.jsonl`` → Markdown 表 + ``REPORT.json``。

用法::

    python scripts/curriculum_report.py --dir runs/small_expert/main \
        --out runs/small_expert/main/REPORT.md
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


def _load(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _fmt(v: Any, nd: int = 0) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="runs/small_expert/main")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    rows = _load(os.path.join(args.dir, "curriculum.jsonl"))
    out = args.out or os.path.join(args.dir, "REPORT.md")
    lines: List[str] = ["# 小模型专家课程结果", ""]

    # S1
    s1 = [r for r in rows if r.get("stage") == "S1"]
    if s1:
        lines += ["## S1 无约束缩放（沙盒 gold=99 / cap=120）", "",
                  "| 事件 | 训练决策 | t12 Σ p50 | t15 Σ p50 | 载体率 | 对载体施法 | tier 分布 |",
                  "|---|---:|---:|---:|---:|---:|---|"]
        for r in s1:
            tid = r.get("tier_dist")
            lines.append(
                f"| {r.get('event')} | {r.get('decisions')} | {_fmt(r.get('t12'))} | "
                f"{_fmt(r.get('t15'))} | {_fmt(r.get('carrier_rate'), 3)} | "
                f"{_fmt(r.get('casts_on_carrier'), 2)} | {json.dumps(tid, ensure_ascii=False) if tid else '—'} |")
        lines.append("")

    # S2
    s2 = [r for r in rows if r.get("stage") == "S2"]
    if s2:
        lines += ["## S2 两维硬限制（gold 99→30→15→10，cap 120→40→20→10）", "",
                  "| 档 | gold | cap | 事件 | 训练决策 | t12 Σ p50 | t15 Σ p50 | 掉幅 | 载体率 | 对载体施法 | tier 分布 |",
                  "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|"]
        for r in s2:
            tid = r.get("tier_dist")
            lines.append(
                f"| {r.get('level')} | {r.get('gold')} | {r.get('action_cap')} | {r.get('event')} | "
                f"{r.get('decisions')} | {_fmt(r.get('t12'))} | {_fmt(r.get('t15'))} | "
                f"{_fmt(r.get('drop'), 3)} | {_fmt(r.get('carrier_rate'), 3)} | "
                f"{_fmt(r.get('casts_on_carrier'), 2)} | "
                f"{json.dumps(tid, ensure_ascii=False) if tid else '—'} |")
        lines.append("")

    # S3
    s3 = [r for r in rows if r.get("stage") == "S3"]
    if s3:
        lines += ["## S3 加对手（完整游戏，人类战团 1→3→5 席）", "",
                  "| band | 席数 | p | 训练决策 | t12 Σ p50 | t15 Σ p50 | mean rank | top4 | 载体回合 | 载体率@t12 | 对载体施法 |",
                  "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in s3:
            lines.append(
                f"| {r.get('band')} | {r.get('seats')} | {r.get('p')} | {r.get('decisions')} | "
                f"{_fmt(r.get('t12_sigma_p50'))} | {_fmt(r.get('t15_sigma_p50'))} | "
                f"{_fmt(r.get('mean_rank'), 3)} | {_fmt(r.get('top4'), 3)} | "
                f"{_fmt(r.get('carrier_turns_mean'), 2)} | "
                f"{_fmt(r.get('carrier_t12_rate'), 3)} | {_fmt(r.get('casts_on_carrier_mean'), 2)} |")
        lines.append("")

    spent = max((int(r.get("spent") or 0) for r in rows), default=0)
    gates = [r for r in rows if r.get("event") == "gate_pass"]
    lines += ["## 汇总", "",
              f"- 训练决策总数（沙盒+完整游戏）：**{spent:,}**",
              f"- S1 门禁（t12≥1200）：{'通过' if gates else '未通过'}",
              f"- S2 档位门禁：{sum(1 for r in s2 if r.get('event') == 'level_done' and r.get('gate_pass'))}"
              f"/{sum(1 for r in s2 if r.get('event') == 'level_done')} 档通过",
              ""]
    text = "\n".join(lines)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"[ok] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
