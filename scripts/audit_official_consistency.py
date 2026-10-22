#!/usr/bin/env python
"""官方一致性门禁（CI gate）：679 场官方 BG 轨迹差分 + 硬门禁 + 基线趋势。

一条命令复用 `tools/diff_replay_combat.py` 的差分结果，输出：

* 三项**硬门禁**（失败 → exit 1）：
  1. ``DATA_GAP == 0``（官方卡名解析必须全覆盖）
  2. ``behavior_mismatch == 0``（干净子集内确证引擎行为错误）
  3. 干净子集 MATCH == 100%（样本数 < ``--min-clean-sample`` 时只告警）
* 趋势指标（不设硬阈值）：strict MATCH、确定性 strict/tolerant、
  CONTEXT_GAP/ENGINE_DIVERGENCE 计数、按归因分类计数；
* 与 ``runs/diff_baseline.json`` 的 Δ 对比；``--update-baseline`` 更新基线。

用法::

    python scripts/audit_official_consistency.py                 # 全量 679 场
    python scripts/audit_official_consistency.py --update-baseline
    python scripts/audit_official_consistency.py --report runs/diff_report.json
    python scripts/audit_official_consistency.py --limit 20 \
        --json runs/diff_smoke.json --md runs/diff_smoke.md

退出码：0 = 门禁通过（可含告警）；1 = 硬门禁失败；2 = 环境/输入错误。
无官方语料（``runs/official_traces`` 不存在或为空）时输出 SKIP 并 exit 0，
保证无 HDT 数据的机器上 CI 不误红（需 JSON 时由调用方判空）。

门禁定义与基线更新流程见 ``docs/DIFF_HARNESS.md`` §8「CI 门禁」。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TRACES = ROOT / "runs" / "official_traces"
DEFAULT_JSON = ROOT / "runs" / "diff_report.json"
DEFAULT_MD = ROOT / "runs" / "diff_report.md"
DEFAULT_BASELINE = ROOT / "runs" / "diff_baseline.json"
BASELINE_SCHEMA = "diff_baseline.v1"

#: 干净子集样本不足时只告警（默认 5；全量语料当前 13）
DEFAULT_MIN_CLEAN_SAMPLE = 5

#: 基线 JSON 中保存/对比的数值指标（key = summary 取值路径）
METRIC_FIELDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("match", ("match",)),
    ("match_rate", ("match_rate",)),
    ("data_gap", ("data_gap",)),
    ("behavior_mismatch", ("behavior_mismatch",)),
    ("engine_divergence", ("engine_divergence",)),
    ("context_gap", ("context_gap",)),
    ("skipped", ("skipped",)),
    ("clean_subset_traces", ("clean_subset_traces",)),
    ("clean_subset_match", ("clean_subset_match",)),
    ("clean_subset_match_rate", ("clean_subset_match_rate",)),
    ("deterministic_traces", ("deterministic_traces",)),
    ("deterministic_match", ("deterministic_match",)),
    ("deterministic_match_rate", ("deterministic_match_rate",)),
    ("deterministic_tolerant_match", ("deterministic_tolerant_match",)),
    ("deterministic_tolerant_match_rate",
     ("deterministic_tolerant_match_rate",)),
)

RATE_FIELDS = {"match_rate", "clean_subset_match_rate",
               "deterministic_match_rate",
               "deterministic_tolerant_match_rate"}


def _dig(summary: Mapping[str, Any], path: Tuple[str, ...]) -> Any:
    node: Any = summary
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def metrics_from_summary(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """从 diff summary 提取门禁/趋势指标（缺失字段为 None，不臆造 0）。"""
    metrics: Dict[str, Any] = {}
    for name, path in METRIC_FIELDS:
        metrics[name] = _dig(summary, path)
    metrics["divergence_attribution"] = dict(
        summary.get("divergence_attribution") or {})
    metrics["context_gap_attribution"] = dict(
        summary.get("context_gap_attribution") or {})
    metrics["traces"] = summary.get("traces")
    metrics["behavior_mismatch"] = int(summary.get("behavior_mismatch") or 0)
    metrics["data_gap"] = int(summary.get("data_gap") or 0)
    return metrics


def evaluate_gates(metrics: Mapping[str, Any], *,
                   min_clean_sample: int = DEFAULT_MIN_CLEAN_SAMPLE,
                   baseline: Optional[Mapping[str, Any]] = None
                   ) -> Tuple[List[str], List[str]]:
    """返回 (hard_failures, warnings)。pure function，便于单测。

    硬门禁：
      1. DATA_GAP == 0
      2. behavior_mismatch == 0
      3. 干净子集 MATCH == 100%（clean_subset_traces >= min_clean_sample 时）
    """
    failures: List[str] = []
    warnings: List[str] = []

    data_gap = int(metrics.get("data_gap") or 0)
    if data_gap != 0:
        failures.append(f"DATA_GAP={data_gap}（必须 0；官方卡名解析不全）")

    behavior = int(metrics.get("behavior_mismatch") or 0)
    if behavior != 0:
        failures.append(
            f"behavior_mismatch={behavior}（必须 0；干净子集内确证引擎行为错误）")

    clean_n = int(metrics.get("clean_subset_traces") or 0)
    clean_match = int(metrics.get("clean_subset_match") or 0)
    clean_rate = metrics.get("clean_subset_match_rate")
    if clean_n < min_clean_sample:
        warnings.append(
            f"干净子集样本仅 {clean_n}（< {min_clean_sample}）→ 100% 门禁仅告警")
    elif clean_rate is not None and float(clean_rate) < 1.0:
        failures.append(
            f"干净子集 MATCH={clean_match}/{clean_n}="
            f"{float(clean_rate):.1%}（必须 100%）")

    if baseline is None:
        warnings.append("无基线文件 → 跳过 Δ 对比（可 --update-baseline 建立）")
    return failures, warnings


def baseline_from_metrics(metrics: Mapping[str, Any], *, seeds: int,
                          traces: int, engine_root: str,
                          attribution: Mapping[str, Any],
                          context_attribution: Mapping[str, Any]
                          ) -> Dict[str, Any]:
    """构造基线 JSON（--update-baseline 写入内容）。"""
    keep = {}
    for name, _path in METRIC_FIELDS:
        if name in metrics:
            keep[name] = metrics[name]
    return {
        "schema": BASELINE_SCHEMA,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine_root": engine_root,
        "traces": traces,
        "seeds": seeds,
        "metrics": keep,
        "divergence_attribution": dict(attribution or {}),
        "context_gap_attribution": dict(context_attribution or {}),
    }


def load_baseline(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != BASELINE_SCHEMA:
        return None
    return data


def _fmt_rate(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def _delta_line(name: str, old: Any, new: Any) -> str:
    if old is None or new is None:
        return f"  Δ {name:28s} {old!s:>10} → {new!s:<10}（无基线）"
    if name in RATE_FIELDS:
        diff = (float(new) - float(old)) * 100
        arrow = "↑" if diff > 1e-9 else ("↓" if diff < -1e-9 else "=")
        return (f"  Δ {name:28s} {float(old):8.2%} → {float(new):8.2%}  "
                f"{arrow} {diff:+.2f}pp")
    diff_n = float(new) - float(old)
    arrow = "↑" if diff_n > 0 else ("↓" if diff_n < 0 else "=")
    return (f"  Δ {name:28s} {old!s:>10} → {new!s:<10} {arrow} {diff_n:+.0f}")


def compare_to_baseline(metrics: Mapping[str, Any],
                        baseline: Optional[Mapping[str, Any]],
                        *, attribution: Mapping[str, Any],
                        context_attribution: Mapping[str, Any]
                        ) -> List[str]:
    lines: List[str] = []
    if baseline is None:
        return lines
    old_metrics = baseline.get("metrics") or {}
    lines.append(f"基线：{baseline.get('created_at', '?')} "
                 f"（traces={baseline.get('traces')}，"
                 f"seeds={baseline.get('seeds')}）")
    for name, _path in METRIC_FIELDS:
        if name not in old_metrics:
            continue
        lines.append(_delta_line(name, old_metrics.get(name), metrics.get(name)))
    old_div = baseline.get("divergence_attribution") or {}
    old_ctx = baseline.get("context_gap_attribution") or {}
    for key in sorted(set(old_div) | set(attribution)):
        lines.append(
            f"  Δ divergence[{key}] {old_div.get(key, 0)} → "
            f"{attribution.get(key, 0)}")
    for key in sorted(set(old_ctx) | set(context_attribution)):
        lines.append(
            f"  Δ context[{key}] {old_ctx.get(key, 0)} → "
            f"{context_attribution.get(key, 0)}")
    return lines


def _top_attribution(metrics: Mapping[str, Any], limit: int = 6) -> str:
    attribution = metrics.get("divergence_attribution") or {}
    context = metrics.get("context_gap_attribution") or {}
    parts = [f"{k}={v}" for k, v in sorted(attribution.items(),
                                          key=lambda kv: -kv[1])[:limit]]
    if context:
        parts.append("context: " + ", ".join(
            f"{k}={v}" for k, v in sorted(context.items(),
                                          key=lambda kv: -kv[1])[:limit]))
    return "; ".join(parts) if parts else "（无）"


def render_summary(metrics: Mapping[str, Any], failures: List[str],
                   warnings: List[str], delta_lines: List[str],
                   *, baseline_path: Path) -> str:
    lines: List[str] = [
        "[official-consistency] 官方一致性门禁",
        f"  traces={metrics.get('traces')}  "
        f"DATA_GAP={metrics.get('data_gap')}  "
        f"SKIPPED={metrics.get('skipped')}",
        f"  MATCH {metrics.get('match')} = {_fmt_rate(metrics.get('match_rate'))}"
        f"（strict 可比）| ENGINE_DIVERGENCE={metrics.get('engine_divergence')}"
        f"  CONTEXT_GAP={metrics.get('context_gap')}",
        f"  behavior_mismatch={metrics.get('behavior_mismatch')}",
        f"  干净子集 {metrics.get('clean_subset_match')}/"
        f"{metrics.get('clean_subset_traces')} = "
        f"{_fmt_rate(metrics.get('clean_subset_match_rate'))}",
        f"  确定性 strict {metrics.get('deterministic_match')}/"
        f"{metrics.get('deterministic_traces')} = "
        f"{_fmt_rate(metrics.get('deterministic_match_rate'))}"
        f" | tolerant = {_fmt_rate(metrics.get('deterministic_tolerant_match_rate'))}",
        f"  归因：{_top_attribution(metrics)}",
    ]
    if delta_lines:
        lines.append("")
        lines.extend(delta_lines)
    lines.append("")
    lines.append(f"  基线文件：{baseline_path}"
                 f"{'' if baseline_path.exists() else '（不存在）'}")
    if warnings:
        lines.append("")
        for warning in warnings:
            lines.append(f"  [WARN] {warning}")
    lines.append("")
    if failures:
        lines.append(f"GATE FAIL（{len(failures)} 项硬门禁失败）：")
        for failure in failures:
            lines.append(f"  - {failure}")
    else:
        lines.append("GATE PASS（DATA_GAP=0；behavior_mismatch=0；"
                     "干净子集 100%（样本足量时））")
    return "\n".join(lines)


def _run_diff(args: argparse.Namespace) -> Dict[str, Any]:
    from hsbg.bridge import trace as T
    from hsrl2.db import CardDB
    from tools.diff_replay_combat import ENGINE_DATA_DIR, diff_traces

    traces = T.load_traces(str(args.traces), limit=args.limit)
    if not traces:
        return {"_empty": True}
    db = CardDB.load(ENGINE_DATA_DIR)
    return diff_traces(
        traces, db=db, seeds=args.seeds, seed_base=args.seed_base,
        limit=args.limit, hero_powers="on_bind",
        l1_threshold=args.l1_threshold, tolerant_rate=args.tolerant_rate,
        inject_script_data=not args.no_script_data_injection,
        traces_dir=str(args.traces))


def card_audit_summary(report: Mapping[str, Any]) -> Dict[str, Any]:
    """按卡聚合差分证据（供每轮不确定卡审计追踪）。"""
    import re
    cards: Dict[str, Dict[str, Any]] = {}

    def entry(card_id: str) -> Dict[str, Any]:
        return cards.setdefault(card_id, {
            "card_id": card_id, "divergent_traces": 0,
            "missing_script": 0, "dynamic_state": 0,
            "behavior_mismatch": 0, "sample_traces": [],
        })

    for row in report.get("divergences") or []:
        for card_id in row.get("suspect_cards") or []:
            item = entry(str(card_id))
            item["divergent_traces"] += 1
            item["missing_script"] += 1 if row.get("attribution") == "missing_script" else 0
            item["behavior_mismatch"] += 1 if row.get("attribution") == "behavior_mismatch" else 0
            if len(item["sample_traces"]) < 3:
                item["sample_traces"].append(row.get("trace_id"))
    for rec in report.get("records") or []:
        gaps = (rec.get("simulation") or {}).get("context_gaps") or []
        for gap in gaps:
            m = re.match(r"(?:no_script|dynamic_script_data|"
                         r"deathrattle_annotation):([A-Za-z0-9_]+)", gap)
            if not m:
                continue
            item = entry(m.group(1))
            if gap.startswith("dynamic_script_data"):
                item["dynamic_state"] += 1
            else:
                item["missing_script"] += 1
    # suspect_cards 是引擎侧聚合的卡（含不在 divergences 截断列表里的）
    for suspect in report.get("suspect_cards") or []:
        card_id = str(suspect.get("card"))
        item = entry(card_id)
        item["divergent_traces"] = max(item["divergent_traces"],
                                       int(suspect.get("divergent_traces") or 0))
        if suspect.get("no_engine_script"):
            item["missing_script"] = max(item["missing_script"], 1)
        if suspect.get("behavior_mismatch_traces"):
            item["behavior_mismatch"] = max(
                item["behavior_mismatch"],
                int(suspect.get("behavior_mismatch_traces") or 0))
    rows = sorted(cards.values(),
                  key=lambda x: (-x["divergent_traces"],
                                 -x["behavior_mismatch"], x["card_id"]))
    with_evidence = [r for r in rows if r["divergent_traces"] or
                     r["missing_script"] or r["dynamic_state"]]
    return {
        "schema": "card_audit_summary.v1",
        "cards_with_evidence": len(with_evidence),
        "cards": rows,
        "no_evidence_cards": [r["card_id"] for r in rows
                              if r not in with_evidence],
    }


def render_card_audit(data: Mapping[str, Any]) -> str:
    lines = ["# 按卡审计摘要（差分证据）", "",
             f"> gate 生成；有证据卡 **{data['cards_with_evidence']}** 张。"
             "证据口径：679 差分 divergent/suspect + context_gaps "
             "(no_script/dynamic_script_data)。", "",
             "| 卡 | divergent | missing_script | dynamic_state | behavior | 样本 trace |",
             "|---|---|---|---|---|---|"]
    for row in data["cards"][:200]:
        lines.append(f"| `{row['card_id']}` | {row['divergent_traces']} | "
                     f"{row['missing_script']} | {row['dynamic_state']} | "
                     f"{row['behavior_mismatch']} | "
                     f"{', '.join(str(x) for x in row['sample_traces'] if x)} |")
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="官方一致性门禁（差分硬门禁 + 基线趋势）")
    ap.add_argument("--traces", default=str(DEFAULT_TRACES))
    ap.add_argument("--seeds", type=int, default=64)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--l1-threshold", type=float, default=0.15)
    ap.add_argument("--tolerant-rate", type=float, default=0.8)
    ap.add_argument("--no-script-data-injection", action="store_true",
                    help="关闭官方 ScriptDataNum 注入（A/B 用，默认开启）")
    ap.add_argument("--report", default=None,
                    help="直接评估既有 diff_report.json（不重跑引擎）")
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--md", default=str(DEFAULT_MD))
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--min-clean-sample", type=int,
                    default=DEFAULT_MIN_CLEAN_SAMPLE)
    ap.add_argument("--card-audit-json", default="runs/card_audit.json",
                    help="按卡审计摘要 JSON（每轮审计追踪）")
    ap.add_argument("--card-audit-md", default="runs/card_audit.md",
                    help="按卡审计摘要 Markdown")
    ap.add_argument("--quiet", action="store_true",
                    help="不打印逐行报告（仍打印门禁结论与失败归因）")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    reports: Dict[str, Any]
    started = time.time()

    if args.report:
        report_path = Path(args.report)
        if not report_path.exists():
            print(f"[official-consistency] report 不存在: {report_path}",
                  file=sys.stderr)
            return 2
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[official-consistency] report JSON 非法: {exc}",
                  file=sys.stderr)
            return 2
        if not isinstance(report, dict) or "summary" not in report:
            print("[official-consistency] report 缺少 summary 字段",
                  file=sys.stderr)
            return 2
        report.setdefault("settings", {})
        reports = report
    else:
        traces_dir = Path(args.traces)
        if not traces_dir.exists() or not any(traces_dir.glob("*.json")):
            print("[official-consistency] SKIP：无官方轨迹语料"
                  f"（{traces_dir}）——无 HDT 数据的机器上不算失败")
            return 0
        try:
            report = _run_diff(args)
        except Exception as exc:  # noqa: BLE001 - CLI 边界：转退出码
            print(f"[official-consistency] 差分执行失败: {exc}",
                  file=sys.stderr)
            return 2
        if report.get("_empty"):
            print(f"[official-consistency] SKIP：语料为空（{traces_dir}）")
            return 0
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        try:
            from tools.diff_replay_combat import render_markdown
            Path(args.md).parent.mkdir(parents=True, exist_ok=True)
            Path(args.md).write_text(render_markdown(report),
                                     encoding="utf-8")
        except Exception:  # noqa: BLE001 - 报告渲染失败不阻断门禁
            pass
        reports = report

    try:
        card_audit = card_audit_summary(reports)
        Path(args.card_audit_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.card_audit_json).write_text(
            json.dumps(card_audit, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        Path(args.card_audit_md).write_text(
            render_card_audit(card_audit), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - 摘要失败不阻断门禁
        print(f"[official-consistency] card audit 生成失败: {exc}",
              file=sys.stderr)

    summary = reports.get("summary") or {}
    metrics = metrics_from_summary(summary)
    attribution = metrics["divergence_attribution"]
    context_attribution = metrics["context_gap_attribution"]
    baseline_path = Path(args.baseline)
    baseline = load_baseline(baseline_path)
    # 采样模式（--limit）与全量基线不同口径 → 不做 Δ 对比，避免误读
    compare_baseline = None if args.limit is not None else baseline
    failures, warnings = evaluate_gates(
        metrics, min_clean_sample=args.min_clean_sample,
        baseline=compare_baseline)
    if args.limit is not None:
        warnings = [w for w in warnings if "无基线" not in w]
        warnings.insert(0, f"--limit={args.limit} 采样模式：跳过基线 Δ 对比")
    delta_lines = compare_to_baseline(
        metrics, compare_baseline, attribution=attribution,
        context_attribution=context_attribution)

    output = render_summary(metrics, failures, warnings, delta_lines,
                            baseline_path=baseline_path)
    print(output)

    if args.update_baseline and not failures:
        settings = reports.get("settings") or {}
        payload = baseline_from_metrics(
            metrics,
            seeds=int(settings.get("seeds_per_trace", args.seeds)),
            traces=int(metrics.get("traces") or 0),
            engine_root=str(reports.get("engine_root", "")),
            attribution=attribution,
            context_attribution=context_attribution)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        print(f"\n[official-consistency] 基线已更新 → {baseline_path}")
    elif args.update_baseline:
        print("\n[official-consistency] 门禁失败：不更新基线")

    elapsed = time.time() - started
    if not args.quiet:
        print(f"\n[official-consistency] 完成（{elapsed:.1f}s）")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
