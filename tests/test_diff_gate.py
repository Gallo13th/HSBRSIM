"""官方一致性门禁测试（`scripts/audit_official_consistency.py`）。

覆盖：指标提取、三项硬门禁、样本不足告警、基线读写/Δ、CLI 退出码。
不依赖真实语料（合成 summary）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.audit_official_consistency import (  # noqa: E402
    BASELINE_SCHEMA,
    baseline_from_metrics,
    compare_to_baseline,
    evaluate_gates,
    load_baseline,
    main,
    metrics_from_summary,
)


def make_summary(**overrides):
    summary = {
        "traces": 679,
        "data_gap": 0,
        "skipped": 41,
        "match": 399,
        "match_rate": 0.6891,
        "engine_divergence": 180,
        "context_gap": 59,
        "behavior_mismatch": 0,
        "clean_subset_traces": 13,
        "clean_subset_match": 13,
        "clean_subset_match_rate": 1.0,
        "deterministic_traces": 343,
        "deterministic_match": 290,
        "deterministic_match_rate": 0.8455,
        "deterministic_tolerant_match": 318,
        "deterministic_tolerant_match_rate": 0.9271,
        "divergence_attribution": {"missing_script": 180},
        "context_gap_attribution": {"unmodeled_dynamic_state": 54,
                                    "unmodeled_context": 5},
    }
    summary.update(overrides)
    return summary


def make_report(summary=None):
    return {
        "schema": "diff_report.v1",
        "summary": summary or make_summary(),
        "settings": {"seeds_per_trace": 64},
        "engine_root": str(ROOT),
    }


def write_report(tmp_path: Path, summary=None) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(make_report(summary), ensure_ascii=False),
                    encoding="utf-8")
    return path


def test_metrics_from_summary_extracts_all_fields():
    metrics = metrics_from_summary(make_summary())
    assert metrics["match"] == 399
    assert metrics["clean_subset_traces"] == 13
    assert metrics["behavior_mismatch"] == 0
    assert metrics["divergence_attribution"] == {"missing_script": 180}
    assert metrics["context_gap_attribution"]["unmodeled_context"] == 5


def test_gates_pass_on_clean_summary():
    failures, warnings = evaluate_gates(metrics_from_summary(make_summary()))
    assert failures == []
    assert any("无基线" in w for w in warnings)
    assert any("样本" not in w for w in warnings)


def test_gate_fails_on_data_gap():
    failures, _ = evaluate_gates(
        metrics_from_summary(make_summary(data_gap=2)))
    assert any("DATA_GAP" in f for f in failures)


def test_gate_fails_on_behavior_mismatch():
    failures, _ = evaluate_gates(
        metrics_from_summary(make_summary(behavior_mismatch=1)))
    assert any("behavior_mismatch" in f for f in failures)


def test_gate_fails_when_clean_subset_not_100_percent():
    failures, _ = evaluate_gates(metrics_from_summary(make_summary(
        clean_subset_traces=13, clean_subset_match=12,
        clean_subset_match_rate=12 / 13)))
    assert any("干净子集" in f for f in failures)


def test_small_clean_sample_warns_not_fails():
    failures, warnings = evaluate_gates(
        metrics_from_summary(make_summary(
            clean_subset_traces=2, clean_subset_match=1,
            clean_subset_match_rate=0.5)),
        min_clean_sample=5)
    assert failures == []
    assert any("样本仅 2" in w for w in warnings)


def test_baseline_roundtrip_and_zero_delta(tmp_path):
    metrics = metrics_from_summary(make_summary())
    payload = baseline_from_metrics(
        metrics, seeds=64, traces=679, engine_root=str(ROOT),
        attribution=metrics["divergence_attribution"],
        context_attribution=metrics["context_gap_attribution"])
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    baseline = load_baseline(path)
    assert baseline is not None
    assert baseline["schema"] == BASELINE_SCHEMA
    delta = compare_to_baseline(
        metrics, baseline, attribution=metrics["divergence_attribution"],
        context_attribution=metrics["context_gap_attribution"])
    assert any("Δ match " in line and "= +0" in line for line in delta)
    assert any("Δ match_rate" in line and "+0.00pp" in line
               for line in delta)


def test_baseline_detects_metric_drop(tmp_path):
    old = baseline_from_metrics(
        metrics_from_summary(make_summary(match=399, match_rate=0.6891)),
        seeds=64, traces=679, engine_root=str(ROOT),
        attribution={"missing_script": 180}, context_attribution={})
    new_metrics = metrics_from_summary(make_summary(
        match=395, match_rate=0.6823))
    delta = compare_to_baseline(
        new_metrics, old, attribution={"missing_script": 184},
        context_attribution={})
    assert any("Δ match " in line and "↓" in line for line in delta)
    assert any("divergence[missing_script]" in line for line in delta)


def test_invalid_baseline_is_ignored(tmp_path):
    path = tmp_path / "bad_baseline.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_baseline(path) is None
    failures, warnings = evaluate_gates(
        metrics_from_summary(make_summary()), baseline=None)
    assert failures == []
    assert any("无基线" in w for w in warnings)


def test_cli_report_pass_exit_0(tmp_path):
    report = write_report(tmp_path)
    rc = main(["--report", str(report),
               "--baseline", str(tmp_path / "none.json")])
    assert rc == 0


def test_cli_report_failure_exit_1(tmp_path):
    report = write_report(tmp_path, make_summary(behavior_mismatch=1))
    rc = main(["--report", str(report),
               "--baseline", str(tmp_path / "none.json")])
    assert rc == 1


def test_cli_missing_report_exit_2(tmp_path):
    rc = main(["--report", str(tmp_path / "missing.json")])
    assert rc == 2


def test_cli_update_baseline_writes_file(tmp_path):
    report = write_report(tmp_path)
    baseline = tmp_path / "baseline.json"
    rc = main(["--report", str(report), "--baseline", str(baseline),
               "--update-baseline", "--quiet"])
    assert rc == 0
    assert baseline.exists()
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["schema"] == BASELINE_SCHEMA
    assert payload["metrics"]["match"] == 399
    assert payload["divergence_attribution"] == {"missing_script": 180}


def test_cli_update_baseline_skipped_when_gate_fails(tmp_path):
    report = write_report(tmp_path, make_summary(data_gap=1))
    baseline = tmp_path / "baseline.json"
    rc = main(["--report", str(report), "--baseline", str(baseline),
               "--update-baseline", "--quiet"])
    assert rc == 1
    assert not baseline.exists()
