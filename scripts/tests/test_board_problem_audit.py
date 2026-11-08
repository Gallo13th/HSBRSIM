"""场面题**质量审计**单测（``docs/BOARD_PROBLEMS.md`` §13.3）。

覆盖：

1. ``parse_game_indices``（``--audit-games`` 语法）：``"0-5,9"`` / 单值 / 空串；
   **非法输入一律 ``ValueError``**（缺区间、逆序、负值、空项……）；
2. 采集侧审计记录：``ProblemCollectConfig(audit_games=…)`` 只在指定局号记录
   ``turn_states`` / ``turn_pos`` / ``learner_actions``，且题目的 ``obs.sha256``
   能从记录的状态重放出来（需要 ``hsbg_engine``）；
3. 重放核对：``scripts/audit_board_problems.replay_problem`` 对采样题得到的
   ``strength_before`` / ``strength_after`` / ``Δ`` 与 ``label`` **完全一致**
   （确定性重放；偏差应为 0，远低于 10% 门限）。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from hsbg.az.train.board_problems import (
    ProblemCollectConfig,
    collect_problems,
    parse_game_indices,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _torch():
    return pytest.importorskip("torch")


def _engine_ok() -> bool:
    try:
        from hsbg.az.train.common import engine_available
        return bool(engine_available())
    except Exception:  # noqa: BLE001
        return False


def _entity(d_model=32):
    _torch()
    from hsbg.az.train.entity_model import (CardTables, TEXT_DIM,
                                            build_entity_net)
    import numpy as np
    tables = CardTables(static=np.zeros((64, 56), np.float32),
                        text=np.zeros((64, TEXT_DIM), np.float32), n_cards=64)
    return build_entity_net(d_model=d_model, n_layers=1, n_heads=4, dim_ff=64,
                            card_dim=8, tables=tables, strength_head=True)


def _audit_module():
    """``scripts/`` 不是包：按文件路径导入审计脚本。"""
    import importlib.util
    path = os.path.join(ROOT, "scripts", "audit_board_problems.py")
    spec = importlib.util.spec_from_file_location("audit_board_problems", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════
# 1. --audit-games 语法
# ══════════════════════════════════════════════════════════════════════════
def test_parse_game_indices_ok():
    assert parse_game_indices("") == []
    assert parse_game_indices("   ") == []
    assert parse_game_indices("3") == [3]
    assert parse_game_indices("0-5,9") == [0, 1, 2, 3, 4, 5, 9]
    assert parse_game_indices("7,0-1") == [0, 1, 7]          # 合并 + 排序去重
    assert parse_game_indices("2-3,3-4") == [2, 3, 4]        # 重叠区间合并


@pytest.mark.parametrize("spec", ["5-1", "-1-3", "a-b", "1-", "1-2,,3", "1:2", 3.5])
def test_parse_game_indices_rejects_invalid(spec):
    with pytest.raises(ValueError):
        parse_game_indices(spec)


# ══════════════════════════════════════════════════════════════════════════
# 2. 采集侧审计记录 + 重放核对（需要引擎）
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _engine_ok(), reason="需要 hsbg_engine")
def test_audit_capture_and_replay_roundtrip():
    model = _entity()
    cfg = ProblemCollectConfig(
        games=2, seed=20200, min_turn=1, human_board_p=0.0, mirror_p=0.0,
        obs_dtype="f32", audit_games="0",
        max_fork_per_turn=2, keep_turn_start=True)
    res = collect_problems(model, cfg, device="cpu")
    assert len(res.audits) == 1, "只审计 gi=0 一局"
    a = res.audits[0]
    assert int(a["game_index"]) == 0
    assert a["turn_states"], "必须记录每回合起始状态"
    assert a["learner_actions"], "必须记录 learner 动作"
    assert set(a["turn_states"]) == set(a["turn_pos"]), "turn 与 pass 位置一一对应"
    assert res.stats["audit_games"] == [0]
    assert int(res.stats["audit_problems"]) == len(a["problems"])
    if not res.problems:
        pytest.skip("rollout 没有出题")
    # 只审 survived 题（标签在目标回合被记录）
    cands = [(a, p, int((p.get("label") or {}).get("target_turn") or 0))
             for p in a["problems"]
             if int((p.get("label") or {}).get("survived") or 0)
             and str(int(p.get("turn") or 0)) in a["turn_states"]
             and str(int((p.get("label") or {}).get("target_turn") or 0))
             in a["turn_states"]]
    if not cands:
        pytest.skip("该局没有存活到 t+3 的题")
    A = _audit_module()
    ok = 0
    for audit, prob, target in cands[:4]:
        r = A.replay_problem(audit, prob, target, tol=0.10, verbose=False)
        assert r["obs_sha_match"] is True, r["reason"]
        assert int(r["strength_before_obs"]) == int(r["strength_before_label"])
        assert int(r["strength_before_replay"]) == int(r["strength_before_label"])
        assert int(r["strength_after_replay"]) == int(r["strength_after_label"])
        assert float(r["delta_rel_dev"]) == 0.0
        assert r["ok"] is True
        assert all(m is not False for _t, m in (r["boundary_match"] or []))
        ok += 1
    assert ok > 0


# ══════════════════════════════════════════════════════════════════════════
# 3. 入口脚本暴露 --audit-games / 非法值退出码 2
# ══════════════════════════════════════════════════════════════════════════
def _run(script, args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script)]
                          + list(args), capture_output=True, text=True,
                          cwd=ROOT, timeout=180,
                          env={**os.environ, "PYTHONPATH": "rust/python:."})


def test_entry_exposes_audit_games():
    out = _run("build_board_problems.py", ["--help"])
    assert out.returncode == 0, out.stderr[-2000:]
    assert "--audit-games" in out.stdout
    assert "--audit-out" in out.stdout


def test_entry_rejects_invalid_audit_games():
    bad = _run("build_board_problems.py",
               ["--games", "2", "--audit-games", "5-1"])
    assert bad.returncode == 2, bad.stderr[-2000:]
