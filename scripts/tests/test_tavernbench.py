"""TavernBench 集成测试：vendored 数据完整性 + 已发布答案评分复现（离线）。

覆盖（对应 task-3 目标一）：
- 数据完整性：960 任务 / 368 评测集 / 40 场景 / 8 类别 / 720·288 个模拟器状态、
  labels 与 prompts 一一对应、评测集抽样规则、已发布答案覆盖；
- 评分可复现：``scripts/run_tavernbench.py`` 重算的「系统 × 场景」评分必须与
  ``benchmarks/tavernbench/expected/eval_report.json`` 逐项一致；该 golden 由
  AutoTavern 原仓库同一命令生成（见 MANIFEST.json），即对拍基准；
- ``--check`` 正/负路径：正常数据全绿；篡改 golden 后必须报 FAIL（防止假绿）；
- 与 AutoTavern 原仓库现场对拍（可选）：设置 ``AUTOTAVERN_ROOT`` 时执行，
  未设置则 skip（CI/交付机通常没有原仓库 checkout）。

本测试不依赖网络、模型或 taverngym，纯标准库 + vendored 评分代码。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks" / "tavernbench"

#: 原仓库路径只从环境变量读取，不写死本机路径（交付/CI 机通常没有 checkout）
AUTOTAVERN_ROOT = os.environ.get("AUTOTAVERN_ROOT", "").strip()

#: 评测集各类别任务数（上游 README/docs 公布口径）
EVAL_CATEGORY_COUNTS = {
    "rules": 56, "strategy": 56, "combat": 48, "selection": 48,
    "economy": 40, "positioning": 40, "ordering": 40, "targets": 40,
}
#: 评测集各场景任务数（每场景 8，D4/N1/N2 为整个对局场景）
EVAL_SCENARIO_SIZES = {"D4": 16, "N1": 29, "N2": 27}


def _load_script(
    relpath: str = "scripts/run_tavernbench.py",
    name: str = "hsbg_script_run_tavernbench",
):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


# ---------------------------------------------------------------- 来源与许可


def test_vendored_provenance_and_license() -> None:
    """vendored 副本来源可追溯：commit/版本/许可/归因齐全，且未混入 .git。"""
    manifest = json.loads((BENCH / "MANIFEST.json").read_text(encoding="utf-8"))
    up = manifest["upstream"]
    assert up["repository"] == "https://github.com/MCG-NJU/AutoTavern"
    assert up["commit"] == "fb61201"
    assert up["release_tag"] == "v1.0.0"
    assert up["game_patch"] == "36.6.3"
    assert up["license"] == "MIT"
    assert "AutoTavern Authors" in up["copyright"]
    assert manifest["vendored_path"] == "benchmarks/tavernbench"
    # 36 个数据/答案/评分代码文件 + MANIFEST 自身（不含 MANIFEST 的哈希项）
    assert manifest["file_count"] == len(manifest["files"]) == 36
    assert not list(BENCH.rglob(".git")) and not (BENCH / ".git").exists()
    license_text = (BENCH / "LICENSE").read_text(encoding="utf-8")
    notice_text = (BENCH / "NOTICE").read_text(encoding="utf-8")
    assert "MIT License" in license_text and "AutoTavern Authors" in license_text
    assert "Blizzard" in notice_text and "TavernBench" in notice_text


# ---------------------------------------------------------------- 数据完整性


def test_dataset_counts_scenarios_categories(script) -> None:
    """960 任务 / 368 评测集 / 40 场景 / 8 类别 / 720·288 状态。"""
    full_p = script.load_jsonl(BENCH / "data/full/prompts.jsonl")
    full_l = script.load_jsonl(BENCH / "data/full/labels.jsonl")
    eval_p = script.load_jsonl(BENCH / "data/eval/prompts.jsonl")
    eval_l = script.load_jsonl(BENCH / "data/eval/labels.jsonl")
    full_s = script.load_states(BENCH / "data/full/states.jsonl.gz")
    eval_s = script.load_states(BENCH / "data/eval/states.jsonl.gz")

    assert len(full_p) == len(full_l) == 960
    assert len(eval_p) == len(eval_l) == 368
    assert len(full_s) == 720 and len(eval_s) == 288
    assert len({p["scenario"] for p in full_p}) == 40
    assert len({p["scenario"] for p in eval_p}) == 40
    assert {p["category"] for p in full_p} == set(EVAL_CATEGORY_COUNTS)

    counts: dict = {}
    for p in eval_p:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    assert counts == EVAL_CATEGORY_COUNTS

    sizes: dict = {}
    for p in eval_p:
        sizes[p["scenario"]] = sizes.get(p["scenario"], 0) + 1
    for sid, n in sizes.items():
        assert n == EVAL_SCENARIO_SIZES.get(sid, 8), f"场景 {sid} 任务数 {n} 不符"

    # 状态覆盖 30 个对局场景；10 个规则执行场景不需要状态
    assert {s["id"] for s in eval_s} <= {p["id"] for p in eval_p}
    rule = set(script.RULE_SCENARIOS)
    play_scen = {p["scenario"] for p in eval_p if p["scenario"] not in rule}
    state_scen = {s["id"].split("-")[0] for s in eval_s}
    assert play_scen == state_scen and len(play_scen) == 30


def test_labels_cover_tasks_and_scoring_kinds(script) -> None:
    """labels 与 prompts id 一一对应，评分口径分布与上游一致。"""
    full_p = script.load_jsonl(BENCH / "data/full/prompts.jsonl")
    full_l = script.load_jsonl(BENCH / "data/full/labels.jsonl")
    eval_p = script.load_jsonl(BENCH / "data/eval/prompts.jsonl")
    eval_l = script.load_jsonl(BENCH / "data/eval/labels.jsonl")

    assert {r["id"] for r in full_p} == {r["id"] for r in full_l}
    assert {r["id"] for r in eval_p} == {r["id"] for r in eval_l}
    for lab in full_l + eval_l:
        assert {"id", "answer", "scoring"} <= set(lab)
        assert lab["scoring"] in script.SCORING_KINDS, lab["id"]
    counts = {k: 0 for k in script.EXPECTED_SCORING_COUNTS}
    for lab in eval_l:
        counts[lab["scoring"]] += 1
    assert counts == script.EXPECTED_SCORING_COUNTS
    # 上游不变式：评分器必须能给 exact/set 标签自己满分（用 vendored score 模块验证）
    items = script.check_labels_selfscore()
    assert len(items) == 1 and items[0]["ok"], items[0]["detail"]


def test_released_answers_cover_tasks(script) -> None:
    """已发布答案：12 个 eval 系统 × 368（gemini 缺 P2-000 计错）+ 5 个 tool-use 系统 × 144。"""
    eval_ids = {p["id"] for p in script.load_jsonl(BENCH / "data/eval/prompts.jsonl")}
    runs = BENCH / "results" / "eval"
    assert script.list_systems(runs) == sorted(script.PUBLISHED_EVAL_SYSTEMS)
    for name in script.PUBLISHED_EVAL_SYSTEMS:
        rows = script.load_jsonl(runs / name / "answers.jsonl")
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids)), f"{name} id 重复"
        assert set(ids) <= eval_ids, f"{name} 出现评测集外 id"
        expect = 368 - (1 if name == "gemini-3.8-flash" else 0)
        assert len(rows) == expect, f"{name} 答案数 {len(rows)} != {expect}"
        assert not any(r.get("error") or r.get("is_error") for r in rows), name

    tools_runs = BENCH / "results" / "tools"
    assert script.list_systems(tools_runs) == sorted(script.PUBLISHED_TOOLS_SYSTEMS)
    for name in script.PUBLISHED_TOOLS_SYSTEMS:
        rows = script.load_jsonl(tools_runs / name / "answers.jsonl")
        assert len(rows) == 144 and len({r["id"] for r in rows}) == 144, name
        assert set(r["id"] for r in rows) <= eval_ids, name


# ---------------------------------------------------------------- 评分复现 / 对拍


def test_scoring_reproduces_upstream_golden(script) -> None:
    """HSBRSIM 侧重算评分 == AutoTavern 原仓库命令生成的 golden（逐系统逐场景）。"""
    expected = script.load_expected()
    systems = [name for name in expected if name != "chance"]
    got = script.build_report(systems)

    assert set(got) == set(expected)
    assert len(got) == 13  # chance + 12 个已发布系统
    diffs = script.diff_values(expected, got, tol=1e-9)
    assert not diffs, "\n".join(diffs[:10])

    # 关键数字抽检（论文主表口径；与上游 README/报告一致）
    assert got["tavernagent"]["play"] == pytest.approx(0.9143917624521073)
    assert got["tavernagent"]["rule_score"] == pytest.approx(1.0)
    assert got["gpt-6-astra"]["play"] == pytest.approx(0.6316, abs=1e-4)
    assert got["claude-opus-5.5"]["rule_score"] == pytest.approx(0.925)
    assert got["jev"]["play"] == pytest.approx(0.37, abs=1e-4)
    assert got["chance"]["play"] == pytest.approx(0.2182, abs=1e-4)
    # 场景数：30 个对局 + 10 个规则
    for name in got:
        assert got[name]["n_play"] == 30 and got[name]["n_rules"] == 10, name


def test_check_passes_and_covers_all_groups(script) -> None:
    """``--check`` 全绿：目录/许可/哈希/数据/答案/自评分/评分复现各分组均通过。"""
    items = script.run_check()
    failed = [i for i in items if not i["ok"]]
    assert not failed, failed
    names = [i["name"] for i in items]
    assert any("MANIFEST" in n for n in names)
    assert any("960" in n for n in names)
    assert any("已发布答案覆盖" in n for n in names)
    assert len([n for n in names if n.startswith("评分复现 ")]) == 13


def test_check_detects_tampered_golden(script, monkeypatch) -> None:
    """负路径：golden 被改后 ``--check`` 必须报 FAIL，防止检查函数假绿。"""
    expected = copy.deepcopy(script.load_expected())
    expected["tavernagent"]["play"] += 0.1
    monkeypatch.setattr(script, "load_expected", lambda path=None: expected)
    items = script.check_reproducible()
    bad = [i for i in items if not i["ok"]]
    assert bad and any("tavernagent" in i["name"] for i in bad)


def test_report_table_format_matches_upstream(script, capsys) -> None:
    """人类可读表：列头与上游一致，包含 play/rule 与 8 个类别列。"""
    script.main(["--systems", "tavernagent,jev"])
    out = capsys.readouterr().out
    header = next(line for line in out.splitlines() if line.startswith("system"))
    for column in ("play", "rule", "1v1", "comba", "posit", "order",
                   "targe", "selec", "strat", "econo"):
        assert column in header, f"表头缺少 {column}"
    assert "tavernagent" in out and "chance" in out


def test_cli_systems_filter_and_json(tmp_path, capsys, script) -> None:
    """``--systems`` 过滤系统，``--json`` 输出与上游同格式的报告 JSON。"""
    out_json = tmp_path / "tavernbench_report.json"
    rc = script.main(["--systems", "tavernagent,jev", "--json", str(out_json)])
    assert rc == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert set(report) == {"chance", "tavernagent", "jev"}
    expected = script.load_expected()
    assert script.diff_values(
        {k: expected[k] for k in ("chance", "tavernagent", "jev")}, report) == []
    assert "JSON 已写入" in capsys.readouterr().out
    # 不存在的系统名 → 退出码 2，不静默按“全错”评分
    assert script.main(["--systems", "no-such-system"]) == 2


def test_cli_runs_from_repo_root() -> None:
    """从 HSBRSIM 根目录直接运行（不手动设 PYTHONPATH、不 cd）可跑通。"""
    proc = subprocess.run(
        [sys.executable, "scripts/run_tavernbench.py", "--check"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert "CHECK PASSED" in proc.stdout

    proc = subprocess.run(
        [sys.executable, "scripts/run_tavernbench.py", "--systems", "tavernagent"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert "tavernagent" in proc.stdout and "play" in proc.stdout


@pytest.mark.skipif(not AUTOTAVERN_ROOT,
                    reason="未设置 AUTOTAVERN_ROOT：本机没有 AutoTavern 原仓库 checkout 可现场对拍")
def test_upstream_repo_parity_live(script) -> None:
    """可选现场对拍：在 AutoTavern 原仓库跑同一命令，评分 JSON 与 HSBRSIM 完全一致。"""
    upstream = Path(AUTOTAVERN_ROOT)
    if not (upstream / "tavernbench" / "tavernbench" / "report.py").is_file():
        pytest.skip(f"AUTOTAVERN_ROOT={upstream} 下找不到 tavernbench 包")
    items = script.run_upstream_parity(upstream)
    assert items and all(i["ok"] for i in items), [i for i in items if not i["ok"]]
