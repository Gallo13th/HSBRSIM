"""收集 8h 自主工作的可复现证据：live run、审计文档、测试产物、git 状态。

用法：
  python scripts/collect_8h_evidence.py --out runs/8h/evidence_summary.md
只读；不修改代码/游戏。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"<error: {exc}>"


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8"))
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/8h/evidence_summary.md")
    args = ap.parse_args()

    docs = [
        "docs/LIVE_AUTOMATION_PROTOCOL.md",
        "docs/AUDIT_PROTOCOL.md",
        "docs/MULTI_AGENT_RULES.md",
        "docs/AUDIT_LIVE_TO_SIM.md",
        "docs/AUDIT_ENV_ACTIONS.md",
        "docs/AUDIT_ENGINE_MECHANICS.md",
        "docs/LIVE_TO_SIM_GAP.md",
        "docs/AUDIT_CONSISTENCY.md",
    ]
    lines = [f"# 8h evidence summary", "",
             f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
             f"- head: {_run(['git', 'log', '--oneline', '-1'])}",
             "", "## docs", "", "| doc | lines |", "|---|---:|"]
    for d in docs:
        p = ROOT / d
        lines.append(f"| {d} | {_count_lines(p) if p.exists() else -1} |")

    lines += ["", "## live runs", "", "| run | actions lines | screenshots | settled | diagnostics |",
              "|---|---:|---:|---:|---:|"]
    live = ROOT / "runs" / "live"
    if live.exists():
        for d in sorted(live.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
            if not d.is_dir():
                continue
            a = _count_lines(d / "actions.jsonl") if (d / "actions.jsonl").exists() else 0
            shots = len(list((d / "screenshots").glob("*.png"))) if (d / "screenshots").exists() else 0
            settled = len(list((d / "settled").glob("*.json"))) if (d / "settled").exists() else 0
            diag = len(list((d / "diagnostics").iterdir())) if (d / "diagnostics").exists() else 0
            lines.append(f"| {d.name} | {a} | {shots} | {settled} | {diag} |")

    lines += ["", "## audit artifacts", ""]
    audit = ROOT / "runs" / "audit"
    if audit.exists():
        for p in sorted(audit.glob("*.json")):
            lines.append(f"- `{p.relative_to(ROOT)}` ({p.stat().st_size} bytes)")
    lines += ["", "## git status", "", "```", _run(["git", "status", "--short"]), "```"]

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
