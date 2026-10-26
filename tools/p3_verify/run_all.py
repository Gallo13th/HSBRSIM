"""P3 验证一键入口：coverage + oracle + gates → runs/p3_verify/report.json/summary.md。

用法::

    python3 -m tools.p3_verify.run_all                 # 重建扩展 + 全部门禁
    python3 -m tools.p3_verify.run_all --skip-rebuild  # 已重建，仅跑验证
    python3 -m tools.p3_verify.run_all --no-full-test  # 跳过全量 cargo test（省时）

只读 `rust/**`、`data/**`、`hsrl2/**`；产物写 `runs/p3_verify/`（gitignore）。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import common, coverage, gates, oracle


def _summary_md(report: Dict[str, Any]) -> str:
    cov = report["coverage"]
    gate = cov["gate"]
    lines = ["# P3 独立验证摘要（自动生成）", ""]
    lines.append(f"- 生成时间：{report['meta']['generated_at']}")
    lines.append(f"- 引擎构建：{json.dumps(cov['meta']['engine_build'], ensure_ascii=False)[:300]}")
    lines.append("")
    lines.append("## 池内脚本覆盖（P1 门禁）")
    lines.append("")
    lines.append("| 集合 | 总数 | 已实现 | 缺失 |")
    lines.append("|---|---:|---:|---:|")
    for key, label in (("pool_minions", "池内随从"),
                       ("pool_spells", "池内酒馆法术"),
                       ("primary_hero_powers", "英雄主技能")):
        item = cov[key]
        implemented = item["counts"].get("scripted", 0) + item["counts"].get(
            "keyword_only", 0)
        lines.append(f"| {label} | {item['total']} | {implemented} | "
                     f"{len(item['missing'])} |")
    lines.append("")
    lines.append(f"- P1 18 卡缺失：**{gate['p1_required_missing']}**"
                 f"（按 owner：{json.dumps(cov['p1']['missing_by_owner'], ensure_ascii=False)}）")
    lines.append(f"- P1 关联主技能 BG22_HERO_007p2 缺失：{gate['p1_associated_missing']}")
    lines.append(f"- 静态注册表：{cov['counts']['static_registered_ids']} ids / "
                 f"{cov['static']['modules_with_registrations']} modules；"
                 f"build_current={gate['build_current']}")
    lines.append(f"- **覆盖门禁：{'PASS' if gate['pass'] else 'FAIL'}**")
    lines.append("")
    lines.append("## oracle 差分（hsrl2 vs hsbg_engine）")
    lines.append("")
    lines.append(f"- counts: `{json.dumps(report['oracle']['counts'], ensure_ascii=False)}`")
    for row in report["oracle"]["rows"]:
        lines.append(f"- {row['id']} `{row['card']}` → **{row['classification']}**"
                     + (f"（{row.get('reason')}）" if row.get("reason") else ""))
    for row in report["oracle"]["deferred"]:
        lines.append(f"- {row['id']} `{row['card']}` → DEFERRED（{row['reason'][:80]}…）")
    for row in report["oracle"]["structural"]:
        lines.append(f"- {row['id']} `{row['card']}` → {row['classification']}")
    lines.append("")
    lines.append("## 门禁")
    lines.append("")
    gj = report["gates"]["gate_summary"]
    lines.append(f"- 总判定：**{'PASS' if gj['pass'] else 'FAIL'}**，耗时 {gj['elapsed_s']}s")
    for g in report["gates"]["gates"]:
        lines.append(f"- [{'PASS' if g.get('passed') else 'FAIL'}] {g['name']}")
    smoke = report["gates"]["smoke"]
    det = report["gates"]["determinism"]
    lines.append(f"- [{'PASS' if smoke['passed'] else 'FAIL'}] bot_smoke "
                 f"seeds={smoke['seeds']} crashes={len(smoke['crashes'])} "
                 f"turns={smoke.get('turn_min')}..{smoke.get('turn_max')}")
    lines.append(f"- [{'PASS' if det['passed'] else 'FAIL'}] determinism "
                 f"checks={len(det.get('checks') or [])}")
    review = report["gates"]["worker_tests_review"]
    lines.append("")
    lines.append("### worker 测试复核")
    for name, info in review["files"].items():
        lines.append(f"- {name}: exists={info.get('exists')} "
                     f"tests={info.get('test_count')} "
                     f"cards_missing={info.get('expected_missing')} "
                     f"tests_without_assert={info.get('tests_without_assert')}")
    return "\n".join(lines) + "\n"


def run_all(*, rebuild: bool = True, include_full_test: bool = True,
            verify_all: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    report: Dict[str, Any] = {
        "meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
    }
    if rebuild:
        rebuild_res = gates.gate_python_rebuild()
        report["rebuild"] = rebuild_res
    report["coverage"] = coverage.run_audit()
    report["gates"] = gates.run_all(rebuild=False,
                                    include_full_test=include_full_test,
                                    verify_all=verify_all)
    report["oracle"] = oracle.run_all()
    report["meta"]["elapsed_s"] = round(time.time() - t0, 2)
    # 各分项产物单独落盘（文档/复现命令引用的文件名保持一致）
    common.write_json("coverage.json", report["coverage"])
    common.write_json("gates.json", report["gates"])
    common.write_json("oracle.json", report["oracle"])
    return report


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="P3 验证一键入口")
    ap.add_argument("--skip-rebuild", action="store_true")
    ap.add_argument("--no-full-test", action="store_true")
    ap.add_argument("--verify-all", action="store_true")
    args = ap.parse_args(argv)
    report = run_all(rebuild=not args.skip_rebuild,
                     include_full_test=not args.no_full_test,
                     verify_all=args.verify_all)
    common.write_json("report.json", report)
    common.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (common.RUNS_DIR / "summary.md").write_text(_summary_md(report),
                                                encoding="utf-8")
    cov = report["coverage"]["gate"]
    print("coverage gate:", "PASS" if cov["pass"] else "FAIL",
          json.dumps({k: cov[k] for k in (
              "pool_minions_missing", "pool_spells_missing",
              "p1_required_missing", "p1_associated_missing",
              "build_current")}, ensure_ascii=False))
    print("oracle:", json.dumps(report["oracle"]["counts"], ensure_ascii=False))
    print("gates:", json.dumps(report["gates"]["gate_summary"],
                               ensure_ascii=False))
    print("wrote runs/p3_verify/report.json + summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
