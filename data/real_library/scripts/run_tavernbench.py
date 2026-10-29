#!/usr/bin/env python3
"""TavernBench 决策质量评测入口（HSBRSIM 集成版）。

TavernBench 是 AutoTavern 发布的 LLM 决策基准（960 任务 / 40 场景 / 8 类别；
其中 368 任务为论文固定评测集 ``data/eval``），自带评分代码、任务标签、
模拟器状态 JSON 与已发布模型答案。本脚本是 vendored 副本
``benchmarks/tavernbench`` 的 HSBRSIM 侧统一入口：

- 自动处理 ``PYTHONPATH`` 与工作目录，在 HSBRSIM 根目录即可运行，无需 ``cd``；
- 正常模式调用上游 ``tavernbench.report`` 生成「系统 × 类别」评测表；
- ``--check`` 校验 vendored 数据完整性，并复现已发布答案的评分结果
  （与 ``benchmarks/tavernbench/expected/eval_report.json`` 逐项对拍，
  该 golden 由 AutoTavern 原仓库同一命令生成，见 MANIFEST.json）；
- ``--upstream`` 额外与 AutoTavern 原仓库现场对拍（可选，本机有 checkout 时用）。

用法::

    python3 scripts/run_tavernbench.py --check
    python3 scripts/run_tavernbench.py
    python3 scripts/run_tavernbench.py --systems tavernagent,gpt-6-astra,jev
    python3 scripts/run_tavernbench.py --set data/eval --runs results/eval \
        --json runs/tavernbench.json
    python3 scripts/run_tavernbench.py --check --upstream /path/to/AutoTavern/tavernbench

退出码：0 = 成功 / 检查全绿；1 = 检查失败；2 = 参数或数据路径错误。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]  # HSBRSIM 仓库根
BENCH = ROOT / "benchmarks" / "tavernbench"  # vendored TavernBench 根
UPSTREAM = "https://github.com/MCG-NJU/AutoTavern"

DEFAULT_SET = "data/eval"
DEFAULT_RUNS = "results/eval"

#: 论文主表的已发布答案系统（results/eval/<name>/answers.jsonl）
PUBLISHED_EVAL_SYSTEMS = [
    "tavernagent",
    "claude-opus-5.5",
    "claude-sonnet-5.5",
    "gpt-6-astra",
    "gpt-6.1-sol",
    "gemini-3.8-flash",
    "grok-4.7",
    "glm-5.3",
    "kimi-k2.6",
    "intern-s2-preview",
    "deepseek-v4.1-flash",
    "jev",
]

#: 工具使用（tool-use）已发布答案系统（results/tools/<name>/answers.jsonl）
PUBLISHED_TOOLS_SYSTEMS = [
    "deepseek-v4.1-flash",
    "glm-5.3",
    "gpt-6-astra",
    "intern-s2-preview",
    "kimi-k2.6",
]

#: 数据完整性基线（上游 README / docs/TAVERNBENCH.md 公布的数字）
FULL_TASKS = 960
EVAL_TASKS = 368
SCENARIOS = 40
CATEGORIES = 8
FULL_STATES = 720
EVAL_STATES = 288
TOOLS_TASKS = 144
#: data/eval 的抽样规则：每个场景 8 题，D4/N1/N2 为整场景（16/29/27 题）
EVAL_SCENARIO_SIZES = {"D4": 16, "N1": 29, "N2": 27}
DEFAULT_SCENARIO_SIZE = 8
#: 支持的分值口径（score.score_item 的 kind 分支）
SCORING_KINDS = {
    "exact", "brier", "numeric_rel", "set", "numeric_abs",
    "value_map_str", "value_json", "value_map",
}
EXPECTED_SCORING_COUNTS = {
    "exact": 232, "value_json": 48, "value_map_str": 40, "brier": 16,
    "set": 8, "value_map": 8, "numeric_rel": 8, "numeric_abs": 8,
}
RULE_SCENARIOS = ["R1", "R3", "R4", "R5", "R6", "R7", "E1", "E2", "E4", "E5"]


# ---------------------------------------------------------------- 基础工具


def bench_path(path: str) -> Path:
    """相对路径按 vendored 基准根解析（与上游 ``cd tavernbench`` 语义一致）。"""
    p = Path(path)
    return p if p.is_absolute() else (BENCH / p)


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """UTF-8 显式读取 JSONL（AGENTS.md 约定；Windows 上不受 locale 编码影响）。"""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_states(path: Path) -> List[Dict[str, Any]]:
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_expected(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载/复现基准：上游原仓库同一命令生成的已发布答案评分报告。"""
    p = path or (BENCH / "expected" / "eval_report.json")
    return json.loads(p.read_text(encoding="utf-8"))


def list_systems(runs_dir: Path) -> List[str]:
    """答案目录下所有带 answers.jsonl 的系统名（排序）。"""
    if not runs_dir.is_dir():
        return []
    return sorted(d.name for d in runs_dir.iterdir()
                  if (d / "answers.jsonl").is_file())


def resolve_systems(spec: str, runs_dir: Path) -> List[str]:
    """``"all"``/空 = 已发布顺序 ∩ 现有答案目录；否则按逗号解析。"""
    if not spec or spec.strip().lower() == "all":
        available = set(list_systems(runs_dir))
        ordered = [s for s in PUBLISHED_EVAL_SYSTEMS if s in available]
        ordered += [s for s in sorted(available) if s not in ordered]
        return ordered
    return [s.strip() for s in spec.split(",") if s.strip()]


# ---------------------------------------------------------------- 上游模块调用
# 通过子进程 ``python -m tavernbench.report`` 调用上游模块：
#   1) 与上游命令行完全同一条执行路径，评分对拍无“复刻逻辑”偏差；
#   2) 以 PYTHONPATH 指向 vendored 根，并强制 PYTHONUTF8=1，
#      避免 Windows 默认 locale 编码读取含非 ASCII 的 answers.jsonl 出错。


def _upstream_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BENCH) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # 不往 vendored 目录写 __pycache__（保持交付树干净）
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_upstream_report(
    systems: List[str],
    set_dir: Path,
    runs_dir: Path,
    *,
    cwd: Optional[Path] = None,
    out_path: Optional[Path] = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    """调用上游 ``tavernbench.report``，返回 ``--out`` 的评分报告 dict。

    ``cwd`` 默认 vendored 根；传入 AutoTavern/tavernbench 目录可与原仓库对拍。
    出错（非 0 退出 / 未产出 JSON）抛 RuntimeError，附上游输出尾部。
    """
    workdir = cwd or BENCH
    if out_path is None:
        fd, name = tempfile.mkstemp(prefix="tavernbench_", suffix=".json")
        os.close(fd)
        out = Path(name)
    else:
        out = out_path
    cmd = [
        sys.executable, "-m", "tavernbench.report",
        "--set", str(set_dir),
        "--runs", str(runs_dir),
        "--systems", ",".join(systems),
        "--out", str(out),
    ]
    proc = subprocess.run(
        cmd, cwd=str(workdir), env=_upstream_env(), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
        raise RuntimeError(
            f"tavernbench.report 失败 rc={proc.returncode} cwd={workdir}\n{tail}"
        )
    if not out.is_file():
        raise RuntimeError(f"tavernbench.report 未生成 --out 报告: {out}")
    if out_path is None:
        payload = json.loads(out.read_text(encoding="utf-8"))
        try:
            out.unlink()
        except OSError:
            pass
        return payload
    return json.loads(out.read_text(encoding="utf-8"))


def build_report(
    systems: List[str],
    set_dir: Optional[Path] = None,
    runs_dir: Optional[Path] = None,
    *,
    out_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """生成「chance + 各系统」报告 dict（与上游 ``--out`` 格式完全一致）。"""
    return run_upstream_report(
        systems,
        set_dir or bench_path(DEFAULT_SET),
        runs_dir or bench_path(DEFAULT_RUNS),
        out_path=out_path,
    )


# ---------------------------------------------------------------- 报告比对


def diff_values(want: Any, got: Any, path: str = "$", tol: float = 1e-9) -> List[str]:
    """递归比较两份评分报告；浮点按 ``tol`` 容差，其余严格相等。"""
    diffs: List[str] = []
    if isinstance(want, dict) and isinstance(got, dict):
        for key in sorted(set(want) | set(got)):
            sub = f"{path}.{key}"
            if key not in want:
                diffs.append(f"{sub}: 多出 {got[key]!r}")
            elif key not in got:
                diffs.append(f"{sub}: 缺少（期望 {want[key]!r}）")
            else:
                diffs.extend(diff_values(want[key], got[key], sub, tol))
        return diffs
    if isinstance(want, (int, float)) and isinstance(got, (int, float)) \
            and not isinstance(want, bool) and not isinstance(got, bool):
        if abs(float(want) - float(got)) > tol:
            diffs.append(f"{path}: 期望 {want!r}，实得 {got!r}")
        return diffs
    if want != got:
        diffs.append(f"{path}: 期望 {want!r}，实得 {got!r}")
    return diffs


def format_report_table(report: Dict[str, Any]) -> str:
    """把报告 dict 渲染为与上游 ``tavernbench.report`` 相同的人类可读表。"""
    cols = ["rules", "combat", "positioning", "ordering", "targets", "selection",
            "strategy", "economy"]
    lines = [
        f"{'system':28s} play  rule  "
        + " ".join(f"{('1v1' if c == 'rules' else c[:5]):>5s}" for c in cols)
        + "  out_tok trunc"
    ]
    for name, r in report.items():
        lines.append(
            f"{name:28s} {r['play']:.2f}  {r['rule_score']:.2f}  "
            + " ".join(f"{r.get(c, float('nan')):5.2f}" for c in cols)
            + f"  {r.get('tokens_out', 0):7.0f} {r.get('truncated', 0):.2f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------- 完整性检查


def _check(name: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _fmt_counts(prompts: List[Dict[str, Any]]) -> str:
    scen: Dict[str, int] = {}
    cats = set()
    for p in prompts:
        scen[p["scenario"]] = scen.get(p["scenario"], 0) + 1
        cats.add(p["category"])
    return f"{len(prompts)} 任务 / {len(scen)} 场景 / {len(cats)} 类别"


def check_layout() -> List[Dict[str, Any]]:
    """目录结构检查：vendored 树、许可、NOTICE、golden、MANIFEST。"""
    items: List[Dict[str, Any]] = []

    missing = []
    for rel in ("tavernbench/score.py", "tavernbench/report.py",
                "tavernbench/chance.py", "tavernbench/run_openai.py",
                "data/full/prompts.jsonl", "data/full/labels.jsonl",
                "data/full/states.jsonl.gz", "data/eval/prompts.jsonl",
                "data/eval/labels.jsonl", "data/eval/states.jsonl.gz",
                "results/eval", "results/tools",
                "expected/eval_report.json", "MANIFEST.json"):
        if not (BENCH / rel).exists():
            missing.append(rel)
    items.append(_check("目录结构 / 评分代码 / 数据 / golden",
                        not missing, "缺少: " + ", ".join(missing) if missing else str(BENCH)))

    lic = (BENCH / "LICENSE").read_text(encoding="utf-8") if (BENCH / "LICENSE").is_file() else ""
    notice = (BENCH / "NOTICE").read_text(encoding="utf-8") if (BENCH / "NOTICE").is_file() else ""
    ok_lic = "MIT License" in lic and "AutoTavern Authors" in lic
    ok_notice = "Blizzard" in notice and "TavernBench" in notice
    items.append(_check("MIT LICENSE 与 NOTICE 归因", ok_lic and ok_notice,
                        "LICENSE=MIT/AutoTavern Authors; NOTICE 含 Blizzard 权利声明"
                        if ok_lic and ok_notice else "LICENSE/NOTICE 缺失或内容不符"))
    return items


def check_manifest() -> List[Dict[str, Any]]:
    """数据/答案/评分代码文件 sha256 与 MANIFEST.json 对拍（防拷贝损坏/篡改）。"""
    import hashlib

    try:
        manifest = json.loads((BENCH / "MANIFEST.json").read_text(encoding="utf-8"))
        files = manifest["files"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:  # pragma: no cover
        return [_check("MANIFEST 文件哈希", False, f"MANIFEST.json 不可读: {exc}")]

    bad: List[str] = []
    for rel, meta in files.items():
        path = BENCH / rel
        if not path.is_file():
            bad.append(f"{rel}: 文件缺失")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != meta["sha256"]:
            bad.append(f"{rel}: sha256 不符")
        elif path.stat().st_size != meta["size"]:
            bad.append(f"{rel}: 大小不符")
    ok = not bad and len(files) == manifest.get("file_count", -1)
    detail = f"{len(files)} 个文件哈希一致" if ok else "; ".join(bad[:5])
    return [_check("MANIFEST 文件哈希（数据/答案/代码）", ok, detail)]


def check_datasets() -> List[Dict[str, Any]]:
    """任务数 / 场景数 / 类别数 / 标签覆盖 / 状态覆盖等数据完整性检查。"""
    items: List[Dict[str, Any]] = []
    try:
        full_p = load_jsonl(BENCH / "data/full/prompts.jsonl")
        full_l = load_jsonl(BENCH / "data/full/labels.jsonl")
        eval_p = load_jsonl(BENCH / "data/eval/prompts.jsonl")
        eval_l = load_jsonl(BENCH / "data/eval/labels.jsonl")
        full_s = load_states(BENCH / "data/full/states.jsonl.gz")
        eval_s = load_states(BENCH / "data/eval/states.jsonl.gz")
    except (OSError, ValueError) as exc:  # pragma: no cover
        return [_check("数据文件可解析", False, f"JSONL/gzip 读取失败: {exc}")]

    items.append(_check(
        "全量任务数 (960) / 评测集任务数 (368)",
        len(full_p) == len(full_l) == FULL_TASKS
        and len(eval_p) == len(eval_l) == EVAL_TASKS,
        f"full={len(full_p)}/{len(full_l)} tasks/labels, "
        f"eval={len(eval_p)}/{len(eval_l)} tasks/labels",
    ))

    items.append(_check(
        "场景数 (40) / 类别数 (8)",
        len({p["scenario"] for p in full_p}) == SCENARIOS
        and len({p["category"] for p in full_p}) == CATEGORIES
        and len({p["scenario"] for p in eval_p}) == SCENARIOS,
        f"full: {_fmt_counts(full_p)}; eval: {_fmt_counts(eval_p)}",
    ))

    expect_sizes = {s: EVAL_SCENARIO_SIZES.get(s, DEFAULT_SCENARIO_SIZE)
                    for s in {p["scenario"] for p in eval_p}}
    got_sizes: Dict[str, int] = {}
    for p in eval_p:
        got_sizes[p["scenario"]] = got_sizes.get(p["scenario"], 0) + 1
    bad_sizes = {s: got_sizes.get(s) for s in sorted(expect_sizes)
                 if got_sizes.get(s) != expect_sizes[s]}
    items.append(_check(
        "评测集抽样规则（每场景 8；D4=16/N1=29/N2=27）",
        not bad_sizes, "不符: " + str(bad_sizes) if bad_sizes else "40 场景全部符合"),
    )

    def _ids(rows: List[Dict[str, Any]]) -> set:
        return {r["id"] for r in rows}

    def _label_ok(labels: List[Dict[str, Any]]) -> bool:
        for lab in labels:
            if "id" not in lab or "answer" not in lab or "scoring" not in lab:
                return False
            if lab["scoring"] not in SCORING_KINDS:
                return False
        return True

    counts = {k: 0 for k in EXPECTED_SCORING_COUNTS}
    for lab in eval_l:
        counts[lab["scoring"]] = counts.get(lab["scoring"], 0) + 1
    items.append(_check(
        "标签覆盖 & 评分口径分布",
        _ids(full_p) == _ids(full_l) and _ids(eval_p) == _ids(eval_l)
        and _label_ok(full_l) and _label_ok(eval_l)
        and counts == EXPECTED_SCORING_COUNTS,
        f"labels 与 prompts id 一一对应; eval 口径 {counts}",
    ))

    items.append(_check(
        "模拟器状态数（全量 720 / 评测集 288）",
        len(full_s) == FULL_STATES and len(eval_s) == EVAL_STATES
        and _ids(eval_s) <= _ids(eval_p) and _ids(full_s) <= _ids(full_p),
        f"full={len(full_s)}, eval={len(eval_s)}; 状态 id 均为对应任务子集",
    ))

    rule = set(RULE_SCENARIOS)
    play_scen = {p["scenario"] for p in eval_p if p["scenario"] not in rule}
    state_scen = {s["id"].split("-")[0] for s in eval_s}
    items.append(_check(
        "状态覆盖 30 个对局场景（10 个规则场景无需状态）",
        play_scen == state_scen and len(play_scen) == 30,
        f"对局场景 {len(play_scen)}，规则场景 {len(rule)}，状态场景 {len(state_scen)}",
    ))

    items.append(_check(
        "评测集题目唯一 / id 无重复",
        len({p["id"] for p in eval_p}) == EVAL_TASKS
        and len({p["id"] for p in eval_l}) == EVAL_TASKS,
        "368 个 id 均唯一",
    ))
    return items


def check_released_answers() -> List[Dict[str, Any]]:
    """已发布答案覆盖检查：数量、id 合法性、无 error 行。"""
    items: List[Dict[str, Any]] = []
    eval_ids = {p["id"] for p in load_jsonl(BENCH / "data/eval/prompts.jsonl")}
    runs = BENCH / "results" / "eval"
    report: List[str] = []
    ok = True
    found = list_systems(runs)
    missing = [s for s in PUBLISHED_EVAL_SYSTEMS if s not in found]
    if missing:
        ok = False
        report.append("缺少系统: " + ", ".join(missing))
    for name in [s for s in PUBLISHED_EVAL_SYSTEMS if s in found]:
        rows = load_jsonl(runs / name / "answers.jsonl")
        ids = [r["id"] for r in rows]
        expect = EVAL_TASKS - (1 if name == "gemini-3.8-flash" else 0)
        problems = []
        if len(ids) != len(set(ids)):
            problems.append("id 重复")
        if not set(ids) <= eval_ids:
            problems.append("id 不在评测集")
        if len(rows) != expect:
            problems.append(f"行数 {len(rows)} != {expect}")
        if any(r.get("error") or r.get("is_error") for r in rows):
            problems.append("含 error 行")
        if problems:
            ok = False
            report.append(f"{name}: " + ", ".join(problems))
    items.append(_check(
        "已发布答案覆盖（12 系统 × 368，gemini 缺 P2-000 计错）",
        ok, "全部符合" if ok else "; ".join(report),
    ))

    tools_runs = BENCH / "results" / "tools"
    tools_ok = True
    details = []
    for name in PUBLISHED_TOOLS_SYSTEMS:
        path = tools_runs / name / "answers.jsonl"
        if not path.is_file():
            tools_ok = False
            details.append(f"缺少 tools/{name}")
            continue
        rows = load_jsonl(path)
        ids = [r["id"] for r in rows]
        if len(rows) != TOOLS_TASKS or len(ids) != len(set(ids)) \
                or not set(ids) <= eval_ids \
                or any(r.get("error") or r.get("is_error") for r in rows):
            tools_ok = False
            details.append(f"tools/{name}: {len(rows)} 行")
    items.append(_check(
        "工具使用答案覆盖（5 系统 × 144）", tools_ok,
        "全部符合" if tools_ok else "; ".join(details),
    ))
    return items


_SELFSCORE_CODE = r"""
import json, sys
from pathlib import Path
from tavernbench import score

bench = Path.cwd()
prompts = [json.loads(l) for l in open(bench / "data/eval/prompts.jsonl", encoding="utf-8") if l.strip()]
labels = {d["id"]: d for d in map(json.loads, open(bench / "data/eval/labels.jsonl", encoding="utf-8"))}
checked = 0
bad = []
for p in prompts:
    lab = labels[p["id"]]
    if lab["scoring"] not in ("exact", "set"):
        continue
    row = {"id": p["id"], "response": json.dumps({"answer": lab["answer"]})}
    if score.score_answer(lab, row)[0] != 1:
        bad.append(p["id"])
    checked += 1
print(json.dumps({"checked": checked, "bad": bad}))
"""


def check_labels_selfscore() -> List[Dict[str, Any]]:
    """用 vendored ``tavernbench.score`` 校验 exact/set 标签能给自己满分。"""
    proc = subprocess.run(
        [sys.executable, "-c", _SELFSCORE_CODE], cwd=str(BENCH), env=_upstream_env(),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-6:])
        return [_check("标签自评分（score 模块 exact/set）", False, tail)]
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):  # pragma: no cover
        return [_check("标签自评分（score 模块 exact/set）", False, "无法解析 score 输出")]
    ok = not payload["bad"] and payload["checked"] == 240
    detail = (f"exact/set 标签 {payload['checked']} 个全部满分"
              if ok else f"自评分失败: {payload['bad'][:5]} (checked={payload['checked']})")
    return [_check("标签自评分（score 模块 exact/set）", ok, detail)]


def check_reproducible(systems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """复现已发布答案评分：HSBRSIM 侧重算结果 vs 上游 golden 报告逐项对拍。"""
    try:
        expected = load_expected()
    except (OSError, ValueError) as exc:  # pragma: no cover
        return [_check("评分复现（golden 可读）", False, f"expected/eval_report.json: {exc}")]
    systems = systems or [s for s in expected if s != "chance"]
    try:
        got = build_report(systems)
    except RuntimeError as exc:  # pragma: no cover
        return [_check("评分复现（上游 report 可执行）", False, str(exc))]

    items: List[Dict[str, Any]] = []
    missing = [s for s in expected if s not in got]
    if missing:
        items.append(_check("评分复现（系统集合）", False, "缺少: " + ", ".join(missing)))
    for name in expected:
        if name not in got:
            continue
        diffs = diff_values(expected[name], got[name], path=name)
        items.append(_check(
            f"评分复现 {name}", not diffs,
            f"n={len(expected[name].get('by_scenario', {}))} 场景, "
            f"play={got[name].get('play', float('nan')):.4f}"
            if not diffs else "; ".join(diffs[:3]),
        ))
    return items


def run_upstream_parity(upstream_bench: Path) -> List[Dict[str, Any]]:
    """与 AutoTavern 原仓库现场对拍：同一命令在原仓库跑，JSON 应与 HSBRSIM 一致。

    ``upstream_bench`` 可以是 AutoTavern 仓库根，也可以是其 ``tavernbench/`` 子目录。
    """
    candidates = [upstream_bench, upstream_bench / "tavernbench"]
    bench = next(
        (c for c in candidates if (c / "tavernbench" / "report.py").is_file()), None)
    if bench is None:
        return [_check("与 AutoTavern 原仓库对拍", False,
                       f"找不到上游 tavernbench: {upstream_bench}")]
    try:
        systems = [s for s in load_expected() if s != "chance"]
        upstream = run_upstream_report(
            systems, Path("data/eval"), Path("results/eval"), cwd=bench)
        local = build_report(systems)
    except (OSError, RuntimeError) as exc:  # pragma: no cover
        return [_check("与 AutoTavern 原仓库对拍", False, str(exc))]
    diffs = diff_values(upstream, local, path="report")
    return [_check(
        "与 AutoTavern 原仓库对拍（同一命令 JSON 一致）", not diffs,
        f"原仓库 {bench}；12 系统 × 40 场景评分一致" if not diffs else "; ".join(diffs[:3]),
    )]


def run_check(upstream: Optional[Path] = None) -> List[Dict[str, Any]]:
    """``--check``：全部完整性 + 复现检查，返回检查项列表。"""
    items: List[Dict[str, Any]] = []
    items += check_layout()
    items += check_manifest()
    items += check_datasets()
    items += check_released_answers()
    items += check_labels_selfscore()
    items += check_reproducible()
    if upstream is not None:
        items += run_upstream_parity(Path(upstream))
    return items


# ---------------------------------------------------------------- 主流程


def _print_checks(items: List[Dict[str, Any]]) -> int:
    passed = 0
    for item in items:
        mark = "PASS" if item["ok"] else "FAIL"
        passed += int(item["ok"])
        detail = f"  — {item['detail']}" if item["detail"] else ""
        print(f"[{mark}] {item['name']}{detail}")
    total = len(items)
    print("-" * 72)
    if passed == total:
        print(f"CHECK PASSED: {passed}/{total} 项通过")
        return 0
    print(f"CHECK FAILED: {passed}/{total} 项通过，"
          f"失败项: {[i['name'] for i in items if not i['ok']]}")
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="TavernBench 评测入口（HSBRSIM vendored 版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--check", action="store_true",
                    help="校验数据完整性并复现已发布答案评分（不跑模型）")
    ap.add_argument("--set", default=DEFAULT_SET,
                    help=f"评测集目录（相对 benchmarks/tavernbench，默认 {DEFAULT_SET}）")
    ap.add_argument("--runs", default=DEFAULT_RUNS,
                    help="答案目录（相对 benchmarks/tavernbench，默认 results/eval）")
    ap.add_argument("--systems", default="all",
                    help="逗号分隔的系统名；all = 已发布答案全部系统")
    ap.add_argument("--json", default="", help="把评分报告 JSON 写入该路径")
    ap.add_argument("--upstream", default="",
                    help="AutoTavern 原仓库/tavernbench 目录；配合 --check 现场对拍")
    ap.add_argument("--list-systems", action="store_true", help="列出答案目录内系统后退出")
    args = ap.parse_args(argv)

    try:
        return _run(args)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    if not (BENCH / "tavernbench" / "report.py").is_file():
        print(f"ERROR: 找不到 vendored TavernBench: {BENCH}", file=sys.stderr)
        return 2

    runs_dir = bench_path(args.runs)
    if args.list_systems:
        systems = resolve_systems(args.systems, runs_dir)
        print("\n".join(systems))
        return 0

    if args.check:
        print("TavernBench 完整性/复现检查（--check）")
        print(f"  基准根: {BENCH}")
        print(f"  上游  : {UPSTREAM} @ fb61201 (v1.0.0, patch 36.6.3), MIT")
        items = run_check(Path(args.upstream) if args.upstream else None)
        return _print_checks(items)

    set_dir = bench_path(args.set)
    if not (set_dir / "prompts.jsonl").is_file():
        print(f"ERROR: 评测集不存在: {set_dir}", file=sys.stderr)
        return 2
    systems = resolve_systems(args.systems, runs_dir)
    if not systems:
        print(f"ERROR: {runs_dir} 下没有答案目录", file=sys.stderr)
        return 2
    missing = [s for s in systems if not (runs_dir / s / "answers.jsonl").is_file()]
    if missing:
        print(f"ERROR: 缺少答案文件: {missing}（--runs {runs_dir}）", file=sys.stderr)
        return 2

    prompts = load_jsonl(set_dir / "prompts.jsonl")
    print("TavernBench — 决策质量评测（LLM 决策基准，非 self-play）")
    print(f"  基准根: {BENCH}")
    print(f"  数据  : {set_dir}  {_fmt_counts(prompts)}")
    print(f"  答案  : {runs_dir}  {len(systems)} 个系统")
    print("-" * 72)

    out_path = None
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(systems, set_dir, runs_dir, out_path=out_path)
    if args.json:
        print(f"（JSON 已写入 {args.json}）")
    print(format_report_table(report))
    print("-" * 72)
    print("play = 30 个对局场景均值；rule = 10 个规则执行场景均值；"
          "chance = 选项随机基线（参考）；规则场景以外列均值为类别均值")
    print("说明：TavernBench 评测 LLM 在静态局面上的决策质量，"
          "与 HSBRSIM RL 策略 self-play 胜率评测不同口径（见 docs/TAVERNBENCH.md）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
