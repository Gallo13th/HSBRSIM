"""生成 `docs/CONFORMANCE_AUTOTAVERN.md` 中的场景矩阵/统计表片段。

（只用于生成文档片段；产物直接打印到 stdout，由人类/agent 粘贴进台账，
不写仓库文件。重跑：``python3 -m tools.ac_conformance.gen_doc``）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .paths import ROOT

REPORT = ROOT / "runs" / "conformance" / "report.json"


def _load() -> Dict[str, Any]:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def scenario_table(report: Dict[str, Any], group: str) -> str:
    rows = [r for r in report["rows"] if r["group"] == group]
    lines = ["| ID | 场景 | 输入（A vs B） | 观察 | 判定 |",
             "|----|------|----------------|------|------|"]
    for r in rows:
        detail = r.get("detail") or {}
        obs = ""
        if r["kind"] in ("duel", "card_duel"):
            tw = detail.get("tavern_win_rate") or {}
            obs = (f"胜率 T(a/b/tie)={tw.get('a', 0):.2f}/"
                   f"{tw.get('b', 0):.2f}/{tw.get('tie', 0):.2f}；"
                   f"damage T={detail.get('tavern_damage', {}).get('a_values')} "
                   f"H={detail.get('hsrl2_damage', {}).get('a_values')}")
            if detail.get("first_attacker"):
                fa = detail["first_attacker"]
                obs += (f"；首攻 T={fa['tavern_attackers']} "
                        f"H={fa['hsrl2_attacker_counts']}")
        elif r["kind"] == "economy":
            obs = f"差异字段={[d['key'] for d in detail.get('diff_fields', [])]}"
        elif r["kind"] == "flow":
            obs = "整局不变量"
        why = r.get("why") or r.get("reason") or ""
        lines.append(
            f"| {r['id']} | {_md_escape(r['title'])} | {_md_escape(obs)} | "
            f"{_md_escape(why)[:120]} | **{r['classification']}** |")
    return "\n".join(lines)


def main() -> int:
    report = _load()
    print("## summary\n")
    print(json.dumps(report["summary"], ensure_ascii=False))
    for group in ("combat", "card", "economy", "flow"):
        print(f"\n### {group}\n")
        print(scenario_table(report, group))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
