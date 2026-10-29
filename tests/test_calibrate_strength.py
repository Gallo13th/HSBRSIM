"""强度校准脚本的 CPU 单测（3 行合成 jsonl + 2 个假快照帧，不碰大文件 / 引擎 / GPU）。

覆盖：

1. 真实侧只保留 ``recruitment_end_at_phase_switch``，其它 stage 被丢弃并计数；
2. ``strength = Σ(attack+health)``（真实字段名）与 ``Σ(atk+hp)``（引擎快照）同义；
3. 按 turn 分桶 + p50/p75/p90/p99/max/count（线性插值）；
4. ``MirrorSnapshotPool`` 读取 2 个假帧，忽略非法 stage / 缺数值行；
5. ``build_calibration`` 的 ratio 与「真实分位 -> 我们分位」映射；
6. ``main --report`` 端到端（临时目录）。
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

import scripts.calibrate_strength as C

# ────────────────────────── 合成数据 ──────────────────────────


def _real_row(stage: str, turn, board) -> dict:
    return {"stage": stage, "turn": turn, "board": board}


#: 3 行：两行目标 stage（strength 10 / 4），一行其它 stage（必须忽略）。
REAL_ROWS = [
    _real_row(C.STAGE_REAL, 2, [{"attack": 1, "health": 2},
                                {"attack": 3, "health": 4}]),   # 10
    _real_row(C.STAGE_REAL, 2, [{"attack": 2, "health": 2}]),    # 4
    _real_row("first_attack_after_start_effects", 2,
              [{"attack": 9, "health": 9}]),                     # 忽略
]


def _write_real(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _snap_frame(turn: int, seat: int, atk: int, hp: int) -> dict:
    return {
        "turn": turn, "seat": seat, "source_game_seed": 1,
        "stage": "recruitment_end_before_combat", "pool_mode": "unknown",
        "held_pool_parts": [],
        "player": {"health": 30, "board": [{"eid": 1, "card": 1,
                                            "atk": atk, "hp": hp}]},
    }


def _write_snap(path: Path, frames) -> None:
    payload = {"schema": "hsbg.mirror_snapshots", "schema_version": 1,
               "created": "2026-01-01T00:00:00Z", "meta": {"seed": 1},
               "frames": frames}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)


@pytest.fixture()
def real_dir(tmp_path: Path) -> Path:
    d = tmp_path / "real"
    d.mkdir()
    _write_real(d / "game_a.jsonl", REAL_ROWS)
    return d


@pytest.fixture()
def snap_dir(tmp_path: Path) -> Path:
    d = tmp_path / "snaps"
    d.mkdir()
    # 2 个假帧：strength 7 (3+4) 与 20 (10+10)，同 turn=2。
    _write_snap(d / "snap_00000001.json.gz",
                [_snap_frame(2, 0, 3, 4), _snap_frame(2, 1, 10, 10)])
    return d


# ────────────────────────── 统计纯函数 ──────────────────────────


def test_percentile_linear_interpolation():
    assert C.percentile([], 0.5) is None
    assert C.percentile([4], 0.5) == 4.0
    assert C.percentile([4, 10], 0.50) == 7.0
    assert C.percentile([4, 10], 0.75) == 8.5
    assert C.percentile([4, 10], 0.90) == pytest.approx(9.4)
    assert C.percentile([4, 10], 0.99) == pytest.approx(9.94)


def test_strength_stats_buckets():
    st = C.strength_stats([10, 4])
    assert st == {"count": 2, "p50": 7.0, "p75": 8.5, "p90": pytest.approx(9.4),
                  "p99": pytest.approx(9.94), "max": 10}
    empty = C.strength_stats([])
    assert empty["count"] == 0 and empty["p50"] is None and empty["max"] is None


def test_real_board_strength_definition():
    # 真实字段 attack/health；与 mirror_snapshots.board_strength 同义。
    assert C.real_board_strength([{"attack": 2, "health": 3},
                                  {"attack": 0, "health": 1}]) == (6, True)
    assert C.real_board_strength([]) == (0, True)
    assert C.real_board_strength([{"attack": None, "health": 1}]) == (0, False)
    assert C.real_board_strength([{"attack": 1}]) == (0, False)


def test_quantile_of_value_maps_real_target_to_ours():
    assert C.quantile_of_value([], 5) is None
    assert C.quantile_of_value([7], 7) == 0.0
    assert C.quantile_of_value([7], 8) == 100.0
    # 目标 3 < min 7 -> 0；目标 7 -> 0；目标 9.4 在 [7,20] 的 18.46%。
    assert C.quantile_of_value([7, 20], 3) == 0.0
    assert C.quantile_of_value([7, 20], 7) == 0.0
    assert C.quantile_of_value([7, 20], 9.4) == pytest.approx(18.4615, abs=1e-4)
    # 目标高于 max -> 100（重采样不可达）。
    assert C.quantile_of_value([7, 20], 100) == 100.0


# ────────────────────────── 读取 / 分桶 ──────────────────────────


def test_collect_real_stage_filter_and_strength(real_dir: Path):
    by_turn, meta = C.collect_real(real_dir)
    assert sorted(by_turn[2]) == [4, 10]
    assert meta["rows_total"] == 3
    assert meta["rows_used"] == 2
    assert meta["stage_counts"] == {C.STAGE_REAL: 2,
                                    "first_attack_after_start_effects": 1}
    assert meta["bad_json"] == 0


def test_collect_real_skips_invalid_rows(tmp_path: Path):
    d = tmp_path / "real_bad"
    d.mkdir()
    _write_real(d / "bad.jsonl", [
        _real_row(C.STAGE_REAL, 3, []),                              # 空牌面：保留 0
        _real_row(C.STAGE_REAL, 3, [{"attack": None, "health": 1}]),  # 缺数值：跳过
        _real_row(C.STAGE_REAL, None, [{"attack": 1, "health": 1}]),  # 缺 turn：跳过
    ])
    by_turn, meta = C.collect_real(d)
    assert by_turn[3] == [0]
    assert meta["rows_used"] == 1
    assert meta["invalid_minion_stats"] == 1
    assert meta["missing_turn"] == 1
    assert meta["empty_board"] == 1


def test_collect_ours_uses_mirror_pool_with_two_frames(snap_dir: Path):
    by_turn, meta = C.collect_ours(snap_dir)
    assert sorted(by_turn[2]) == [7, 20]
    assert meta["frames"] == 2
    assert meta["files"] == 1
    assert meta["bad_files"] == 0
    assert meta["keys"] == 2
    assert meta["reader"].endswith("MirrorSnapshotPool")


# ────────────────────────── 汇总 / CLI ──────────────────────────


def test_build_calibration_ratios_and_mapping():
    cal = C.build_calibration({2: [4, 10]}, {2: [7, 20]},
                              {"files": 1}, {"files": 1})
    e = cal["2"]
    # real p50=7, p90=9.4；ours p50=13.5, p90=18.7。
    assert e["real"]["p50"] == 7.0
    assert e["ours"]["p50"] == 13.5
    assert e["ratio_p50"] == pytest.approx(round(7.0 / 13.5, 4))
    assert e["ratio_p90"] == pytest.approx(round(9.4 / 18.7, 4), abs=1e-4)
    assert "real" in e and "ours" in e
    # 真实 p50=7 对应我们库的 0 分位；p90=9.4 对应 ~18.46 分位。
    assert e["ours_quantile_for_real"]["p50"] == 0.0
    assert e["ours_quantile_for_real"]["p90"] == pytest.approx(18.4615, abs=1e-4)
    assert e["reachable"]["p50"] is True
    # 只在一侧出现的 turn 也输出，缺失侧 count=0、ratio=None。
    cal2 = C.build_calibration({}, {4: [5, 6]}, {}, {})
    assert cal2["4"]["real"]["count"] == 0
    assert cal2["4"]["ratio_p50"] is None


def test_main_report_end_to_end(real_dir: Path, snap_dir: Path, tmp_path: Path,
                                capsys):
    out = tmp_path / "cal.json"
    rc = C.main(["--real-dir", str(real_dir), "--snap-dir", str(snap_dir),
                 "--out", str(out), "--report"])
    assert rc == 0
    cal = json.loads(out.read_text(encoding="utf-8"))
    assert cal["_meta"]["schema"] == "hsbg.strength_calibration"
    assert cal["2"]["real"]["count"] == 2
    assert cal["2"]["ours"]["count"] == 2
    assert cal["2"]["ratio_p50"] is not None
    printed = capsys.readouterr().out
    assert "turn" in printed and "ratio" not in printed  # 表头用 r_p50/r_p90
    assert "r_p50" in printed and " 2 " in printed


def test_main_missing_dirs(tmp_path: Path):
    rc = C.main(["--real-dir", str(tmp_path / "nope"),
                 "--snap-dir", str(tmp_path / "nope2"),
                 "--out", str(tmp_path / "x.json")])
    assert rc == 2
