"""JSON 报告构建/校验/落盘（评测报告 + 自对弈训练 smoke 报告）。

报告是任务验收证据的一部分：字段固定、可被测试断言、可复现命令写进 ``repro``。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from .common import to_jsonable

EVAL_SCHEMA = "hsbg.az.eval/v1"
TRAIN_SCHEMA = "hsbg.az.train_smoke/v1"

#: 评测报告必需字段（tests/test_az_train.py 会断言）
REQUIRED_EVAL_FIELDS = (
    "schema", "generated_at", "engine", "protocol", "policies", "comparison",
)
REQUIRED_ENGINE_FIELDS = (
    "engine_version", "game_version", "data_version", "n_actions", "obs_floats", "obs_cards",
)
REQUIRED_PROTOCOL_FIELDS = (
    "games_per_policy", "seed_start", "seed_end", "policy_seat", "opponent",
)
REQUIRED_POLICY_FIELDS = (
    "games", "games_finished", "truncated_games", "mean_rank", "top4_rate",
    "win_rate", "rank_counts", "legal_action_rate", "decisions",
    "seconds", "ms_per_decision",
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def build_eval_report(*, engine: Dict[str, Any], protocol: Dict[str, Any],
                      policies: Dict[str, Dict[str, Any]],
                      comparison: Optional[Dict[str, Any]] = None,
                      data_quality: Optional[Dict[str, Any]] = None,
                      repro: Optional[Dict[str, Any]] = None,
                      notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """构建 ``hsbg.az.eval/v1`` 报告。"""
    out: Dict[str, Any] = {
        "schema": EVAL_SCHEMA,
        "generated_at": _now_iso(),
        "engine": dict(engine),
        "protocol": dict(protocol),
        "policies": {name: _strip_examples(metrics) for name, metrics in policies.items()},
        "comparison": dict(comparison or {}),
        "data_quality": dict(data_quality or {}),
        "repro": dict(repro or {}),
        "notes": list(notes or []),
    }
    return to_jsonable(out)


def _strip_examples(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """报告里不放大数组：只记录样本检查的摘要。"""
    m = dict(metrics)
    ex = m.pop("examples", None)
    if ex is not None:
        m["examples_saved"] = int(len(ex))
    return m


def build_train_report(*, engine: Dict[str, Any], collect: Dict[str, Any],
                       data_quality: Dict[str, Any], train: Dict[str, Any],
                       supervised: Dict[str, Any], checkpoint: str,
                       eval_search: Optional[Dict[str, Any]] = None,
                       repro: Optional[Dict[str, Any]] = None,
                       notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """构建 ``hsbg.az.train_smoke/v1`` 报告。"""
    out = {
        "schema": TRAIN_SCHEMA,
        "generated_at": _now_iso(),
        "engine": dict(engine),
        "collect": dict(collect),
        "data_quality": dict(data_quality),
        "train": dict(train),
        "supervised": dict(supervised),
        "checkpoint": str(checkpoint),
        "eval_search": dict(eval_search or {}),
        "repro": dict(repro or {}),
        "notes": list(notes or []),
    }
    return to_jsonable(out)


def validate_eval_report(report: Dict[str, Any]) -> List[str]:
    """校验评测报告字段完整性；返回问题列表（空 = 通过）。"""
    errs: List[str] = []
    for k in REQUIRED_EVAL_FIELDS:
        if k not in report:
            errs.append(f"缺少顶层字段 {k}")
    engine = report.get("engine") or {}
    for k in REQUIRED_ENGINE_FIELDS:
        if k not in engine:
            errs.append(f"engine 缺少字段 {k}")
    protocol = report.get("protocol") or {}
    for k in REQUIRED_PROTOCOL_FIELDS:
        if k not in protocol:
            errs.append(f"protocol 缺少字段 {k}")
    policies = report.get("policies") or {}
    if not policies:
        errs.append("policies 为空（至少要有 random/bot/heuristic/search 之一）")
    for name, m in policies.items():
        for k in REQUIRED_POLICY_FIELDS:
            if k not in m:
                errs.append(f"policies[{name}] 缺少字段 {k}")
        if not isinstance(m.get("rank_counts"), dict):
            errs.append(f"policies[{name}].rank_counts 应为 dict")
        legal = m.get("legal_action_rate")
        if legal is not None and not (0.0 <= float(legal) <= 1.0):
            errs.append(f"policies[{name}].legal_action_rate 越界: {legal}")
        games = m.get("games", 0)
        finished = m.get("games_finished", 0)
        if int(finished) + int(m.get("truncated_games", 0)) != int(games):
            errs.append(f"policies[{name}] games_finished+truncated != games")
    return errs


def write_report(path: str, report: Dict[str, Any]) -> str:
    """写 JSON（UTF-8，原子替换尽量简单）；自动创建父目录。"""
    path = str(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(to_jsonable(report), f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


def load_report(path: str) -> Dict[str, Any]:
    with open(str(path), "r", encoding="utf-8") as f:
        return json.load(f)


def format_summary_table(policies: Dict[str, Dict[str, Any]]) -> str:
    """终端表格：策略 | 平均名次 | 前四率 | 冠军率 | 合法率 | truncated | 耗时。"""
    header = f"{'policy':<16}{'rank':>7}{'top4':>8}{'win':>8}{'legal':>8}{'trunc':>7}{'s':>9}"
    lines = [header, "-" * len(header)]
    for name, m in policies.items():
        rank = m.get("mean_rank")
        top4 = m.get("top4_rate")
        win = m.get("win_rate")
        legal = float(m.get("legal_action_rate", 0.0))
        rank_s = f"{rank:.3f}" if rank is not None else "n/a"
        top4_s = f"{top4:.3f}" if top4 is not None else "n/a"
        win_s = f"{win:.3f}" if win is not None else "n/a"
        lines.append(
            f"{name:<16}{rank_s:>7}{top4_s:>8}{win_s:>8}{legal:>8.3f}"
            f"{int(m.get('truncated_games', 0)):>7}"
            f"{float(m.get('seconds', 0.0)):>9.2f}"
        )
    return "\n".join(lines)


__all__ = [
    "EVAL_SCHEMA",
    "TRAIN_SCHEMA",
    "REQUIRED_EVAL_FIELDS",
    "REQUIRED_ENGINE_FIELDS",
    "REQUIRED_PROTOCOL_FIELDS",
    "REQUIRED_POLICY_FIELDS",
    "build_eval_report",
    "build_train_report",
    "validate_eval_report",
    "write_report",
    "load_report",
    "format_summary_table",
]
