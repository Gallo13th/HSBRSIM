"""版本/环境自检：保证审计结论对应的版本组合是本次实测的组合。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# 可移植性守卫：taverngym 是可选依赖（Windows 开发机可能未安装），
# 未安装时整目录 skip 而不是 collection error（见 docs/TAVERNGYM_BACKEND.md）。
pytest.importorskip(
    "taverngym",
    reason="跨引擎一致性套件需要可选依赖 taverngym（见 docs/TAVERNGYM_BACKEND.md）")

import taverngym

ROOT = Path(__file__).resolve().parent.parent.parent


def test_autotavern_reference_version():
    assert taverngym.version() == "1.0.0"
    assert taverngym.game_version() == "36.6.3.253932"
    assert taverngym.server_rules_version() == "36.6.3"
    assert int(taverngym.N_ACTIONS) == 245


def test_hsrl2_data_patch():
    summary = json.loads((ROOT / "data" / "bg_summary.json")
                         .read_text(encoding="utf-8"))
    assert summary["patch"] == "37.0.0.255130"


def test_hsrl2_engine_importable_and_deterministic():
    from tools.ac_conformance import hsrl2_api
    a = [{"atk": 2, "hp": 2, "kws": []}]
    b = [{"atk": 1, "hp": 1, "kws": []}]
    r1 = hsrl2_api.run_trials(a, b, seeds=4)
    r2 = hsrl2_api.run_trials(a, b, seeds=4)
    assert r1["wins"] == r2["wins"]
    assert r1["damage_by_winner"] == r2["damage_by_winner"]
