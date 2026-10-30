"""人类战团对手面板（``scripts/human_panel_eval.py``）回归测试。

覆盖四件事：

1. **真实 8 局冒烟**（champion checkpoint，GPU cuda:7 或 CPU）：注入 applied/attempt > 0、
   0 illegal / 0 truncation、JSON schema 完整（与 c0_gate 相同 panels 结构 + panel/
   quantile/human_board_pool_stats/injection 字段）；
2. **难度方向**：``--quantile p90`` 的 mean rank 应比 ``p50`` 更差（p90 对手更强）；
3. **训练接线**：``AsyncEvalRunner`` 的 bot/human 双面板串行排队、history 记录带 ``panel``
   与 ``human_mean_rank``（用假评测脚本，不需要 GPU/torch）；
4. **CLI 接线**：``train_entity_sync.py`` 暴露 ``--eval-panel`` / ``--eval-human-quantile``。

真实冒烟用 ``--games 8``（8 seat × 1 局）。设备选择：``HSBRSIM_TEST_DEVICE`` 环境变量 >
有空闲索引 7 的 CUDA（任务约定 cuda:7）> cuda:0 > cpu。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REAL_JSONL = ROOT / "data" / "real_library" / "library_real_degraded.jsonl"
CKPT = ROOT / "runs" / "champion_c0_1746.pt"

#: 与 scripts/human_panel_eval.py 的 output schema 对齐（c0 面板键 + human 额外键）。
PANEL_KEYS = {
    "passed", "n", "mean_diff", "ci_low", "ci_high", "model_mean_rank",
    "bot_mean_rank", "model_top4", "bot_top4", "model_win", "illegal",
    "truncated", "truncated_combats", "reasons", "details", "panel",
    "quantile", "opponent", "human_board_pool_stats", "injection",
}


def _device() -> str:
    env = str(os.environ.get("HSBRSIM_TEST_DEVICE", "")).strip()
    if env:
        return env
    torch = pytest.importorskip("torch", reason="需要 torch 加载 checkpoint")
    if torch.cuda.is_available():
        return "cuda:7" if torch.cuda.device_count() > 7 else "cuda:0"
    return "cpu"


def _subprocess_env() -> dict:
    env = dict(os.environ)
    parts = [str(ROOT), str(ROOT / "rust" / "python")]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run_panel(tmp_path: Path, quantile: str, *, baseline_bot: int = 0,
               seed_base: int = 100000, games: int = 8,
               bootstrap: int = 200) -> dict:
    """跑一次真实 8 局面板（子进程，完整 CLI 路径），返回结果 JSON。"""
    pytest.importorskip("hsbg_engine", reason="hsbg_engine 未安装")
    if not CKPT.is_file():
        pytest.skip(f"checkpoint 不存在: {CKPT}")
    if not REAL_JSONL.is_file():
        pytest.skip("真实人类战团库不存在")
    out = tmp_path / f"human_{quantile}_{baseline_bot}.json"
    cmd = [sys.executable, str(ROOT / "scripts" / "human_panel_eval.py"),
           "--checkpoint", str(CKPT), "--games", str(int(games)),
           "--smoke", "--device", _device(), "--quantile", str(quantile),
           "--seed-base", str(int(seed_base)), "--bootstrap", str(int(bootstrap)),
           "--baseline-bot", str(int(baseline_bot)), "--out", str(out)]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=_subprocess_env(),
                          capture_output=True, text=True, timeout=1800)
    # smoke / passed=False 时退出码为 1，属预期；只有 2 及以上是错误。
    assert proc.returncode in (0, 1), (
        f"human_panel_eval rc={proc.returncode}\n"
        f"stdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}")
    assert out.is_file(), f"未写结果 JSON\nstderr:\n{proc.stderr[-3000:]}"
    return json.loads(out.read_text(encoding="utf-8"))


def test_human_panel_schema_and_injection(tmp_path: Path):
    """auto 分位 8 局：schema 完整、注入真的生效、协议干净。"""
    data = _run_panel(tmp_path, "auto", baseline_bot=1)
    assert data.get("panel") == "human_board"
    assert data.get("quantile") == "auto"
    assert data.get("protocol") == "human_panel_smoke"
    assert data.get("checkpoint_sha256") and len(data["checkpoint_sha256"]) == 64
    for key in ("passed", "smoke_result", "engine", "config", "panels",
                "human_board_pool_stats", "generated_at"):
        assert key in data, key
    panels = data["panels"]
    assert len(panels) == 1
    p = panels[0]
    assert PANEL_KEYS <= set(p), PANEL_KEYS - set(p)
    assert p["panel"] == "human_board" and p["quantile"] == "auto"
    assert p["opponent"] == "human_board_approx"
    assert p["n"] == 8
    assert 1.0 <= float(p["model_mean_rank"]) <= 8.0
    assert 0.0 <= float(p["model_top4"]) <= 1.0
    assert 0.0 <= float(p["model_win"]) <= 1.0
    assert p["illegal"] == 0 and p["truncated"] == 0
    # 注入确实发生：attempt/applied > 0，0 Python 异常 / 池不守恒。
    inj = p["injection"]
    assert inj["human_board_source"] == "human_board_approx"
    assert int(inj["human_board_attempt"]) > 0
    assert int(inj["human_board_applied"]) > 0
    assert int(inj["human_board_errors"]) == 0
    assert int(inj["human_board_pool_unbalanced"]) == 0
    assert int(inj["human_board_tier_set"]) == int(inj["human_board_applied"])
    # 每 seat 行都有 model（和 bot 基线）指标 + 决策数 + 注入计数。
    per_seat = p["details"]["per_seat"]
    assert set(per_seat) == {f"seat_{i}" for i in range(8)}
    row = per_seat["seat_0"]
    for name in ("model", "bot"):
        m = row[name]
        assert m["rank_sequence"] and len(m["rank_sequence"]) == 1
        assert m["decisions_per_game"] >= 0
        assert "human_board" in m
        assert m["human_board_turns"] >= 1
    assert int(row["model"]["decisions"]) > 0
    # 池摘要：真实 10k+ 数据 + 分位桶。
    pool = p["human_board_pool_stats"]
    assert pool["source"] == "human_board_approx"
    assert int(pool["kept"]) >= 4000
    assert pool["sample"] == "auto"


def test_p90_is_harder_than_p50(tmp_path: Path):
    """同一 seed 下 p90 对手更强 -> learner 名次更差（差值方向断言）。"""
    p50 = _run_panel(tmp_path, "p50", baseline_bot=0)
    p90 = _run_panel(tmp_path, "p90", baseline_bot=0)
    m50 = float(p50["panels"][0]["model_mean_rank"])
    m90 = float(p90["panels"][0]["model_mean_rank"])
    assert m50 >= 1.0 and m90 <= 8.0
    assert m90 > m50, f"p90 应更难: p50={m50} p90={m90}"
    # 无 bot 基线时 schema 仍完整，bot_* / CI 为 null。
    p = p90["panels"][0]
    assert p["bot_mean_rank"] is None and p["ci_low"] is None
    assert p["injection"]["human_board_applied"] > 0


def test_parse_panel_result_and_cmd_builders(tmp_path: Path):
    """训练侧解析/命令行：human 记录用 human_mean_rank，bot 记录用 mean_rank。"""
    from scripts.async_eval import (build_human_cmd, panels_from_spec,
                                    parse_panel_result)

    assert panels_from_spec("bot") == ["bot"]
    assert panels_from_spec("human") == ["human"]
    assert panels_from_spec("both") == ["bot", "human"]   # 串行顺序固定

    cmd = build_human_cmd("python", str(ROOT), "ckpt.pt", arch="entity",
                          device="cuda:7", games=8, seats=8, seed_base=100000,
                          out_json="out.json", quantile="p90",
                          baseline_bot=False)
    assert "--quantile" in cmd and cmd[cmd.index("--quantile") + 1] == "p90"
    assert "--baseline-bot" in cmd and cmd[cmd.index("--baseline-bot") + 1] == "0"
    assert "--smoke" in cmd

    human_json = tmp_path / "fake_human_panel.json"
    human_json.write_text(json.dumps({
        "passed": False, "panel": "human_board", "quantile": "auto",
        "panels": [{"model_mean_rank": 6.5, "bot_mean_rank": None,
                    "model_top4": 0.125, "bot_top4": None, "model_win": 0.0,
                    "mean_diff": None, "ci_low": None, "ci_high": None,
                    "illegal": 0, "truncated": 0,
                    "injection": {"human_board_applied": 10}}],
    }), encoding="utf-8")
    rec = parse_panel_result(123, 1, 1.5, str(human_json), panel="human")
    assert rec["panel"] == "human"
    assert rec["human_mean_rank"] == pytest.approx(6.5)
    assert rec["mean_rank"] is None                 # 不冒充 bot 面板
    assert rec["human_top4"] == pytest.approx(0.125)
    assert rec["injection"]["human_board_applied"] == 10
    assert "error" not in rec

    bot_json = tmp_path / "fake_bot_panel.json"
    bot_json.write_text(json.dumps({
        "passed": False,
        "panels": [{"model_mean_rank": 2.5, "bot_mean_rank": 4.5,
                    "model_top4": 0.9, "model_win": 0.3,
                    "mean_diff": -2.0, "ci_low": -2.5, "ci_high": -1.5,
                    "illegal": 0, "truncated": 0}],
    }), encoding="utf-8")
    rec = parse_panel_result(123, 1, 1.5, str(bot_json), panel="bot")
    assert rec["mean_rank"] == pytest.approx(2.5)
    assert rec["top4"] == pytest.approx(0.9)


def test_train_cli_exposes_panel_flags():
    """``train_entity_sync.py`` 必须暴露 --eval-panel / --eval-human-quantile。"""
    src = (ROOT / "scripts" / "train_entity_sync.py").read_text(encoding="utf-8")
    assert '"--eval-panel"' in src and 'choices=["bot", "human", "both"]' in src
    assert '"--eval-human-quantile"' in src
    assert "panels_from_spec(args.eval_panel)" in src
    assert "human_mean_rank" in src        # history.jsonl eval 段


# ────────────────────────── 异步双面板队列（假脚本，无 GPU） ──────────────────────────

FAKE_C0 = r'''
import argparse, json
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
a, _ = ap.parse_known_args()
panel = {"model_mean_rank": 2.5, "bot_mean_rank": 4.5, "model_top4": 0.9,
         "model_win": 0.3, "mean_diff": -2.0, "ci_low": -2.5, "ci_high": -1.5,
         "illegal": 0, "truncated": 0}
json.dump({"passed": False, "panels": [panel]}, open(a.out, "w"))
'''

FAKE_HUMAN = r'''
import argparse, json
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--quantile", default="auto")
ap.add_argument("--baseline-bot", default="0")
a, _ = ap.parse_known_args()
panel = {"model_mean_rank": 6.5, "bot_mean_rank": None, "model_top4": 0.125,
         "bot_top4": None, "model_win": 0.0, "mean_diff": None,
         "ci_low": None, "ci_high": None, "illegal": 0, "truncated": 0,
         "injection": {"human_board_applied": 99}}
json.dump({"passed": True, "panel": "human_board", "quantile": a.quantile,
           "panels": [panel]}, open(a.out, "w"))
'''


def test_async_runner_queues_both_panels(tmp_path: Path):
    """bot -> human 串行排队；history 用 panel 区分，human 记录带 human_mean_rank。"""
    from scripts.async_eval import AsyncEvalRunner

    (tmp_path / "fake_c0.py").write_text(FAKE_C0, encoding="utf-8")
    (tmp_path / "fake_human.py").write_text(FAKE_HUMAN, encoding="utf-8")
    logs: list = []
    runner = AsyncEvalRunner(
        out_dir=str(tmp_path / "run"), root=str(tmp_path), arch="tiny",
        device="cpu", games=8, seats=8, seed_base=100000,
        gate_script=str(tmp_path / "fake_c0.py"),
        human_script=str(tmp_path / "fake_human.py"),
        panels=("bot", "human"), human_quantile="auto",
        python=sys.executable, log=logs.append)
    try:
        assert runner.submit(2000, str(tmp_path / "ckpt.pt")) is True
        # 立刻 drain：close 必须等 bot -> human 两个排队 panel 全部完成
        # （曾经只 join 当前线程，human 会被训练退出杀掉）。
    finally:
        runner.close(drain=True)
    assert runner.completed == 2 and runner.failed == 0
    hist = json.loads((tmp_path / "run" / "eval" / "history.json").read_text(
        encoding="utf-8"))["evals"]
    assert [r["panel"] for r in hist] == ["bot", "human"]
    assert hist[0]["mean_rank"] == pytest.approx(2.5)
    assert hist[1]["human_mean_rank"] == pytest.approx(6.5)
    assert hist[1]["mean_rank"] is None
    assert hist[1]["human_top4"] == pytest.approx(0.125)
    assert runner.stats()["panels"] == ["bot", "human"]
    assert any("panel=human" in m for m in logs)
