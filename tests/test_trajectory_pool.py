"""轨迹库单测：加载/统计/采样/回放脚本（含 bot 兜底返回 None）。"""

from __future__ import annotations

import gzip
import json
import random

from hsbg.az.train.trajectory_pool import ReplayScript, TrajectoryPool


def _traj_file(root, seed=1, frames=(6, 8)):
    rec = {"seed": seed, "learner_seat": 0, "placements": [1, 2, 3, 4, 5, 6, 7, 8],
           "frames": [{"turn": t, "state": "{}",
                       "actions": [[1, 10 + t], [2, 20 + t]]} for t in frames],
           "meta": {"checkpoint": "ckpt"}}
    path = root / f"traj_{seed:08d}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rec, f)
    return path


def test_load_sample_stats(tmp_path):
    _traj_file(tmp_path, seed=1, frames=(6, 8, 10))
    _traj_file(tmp_path, seed=2, frames=(6,))
    pool = TrajectoryPool(str(tmp_path))
    assert len(pool.items) == 2
    st = pool.stats()
    assert st["size"] == 2 and st["entry_turn_min"] == 6
    t = pool.sample(random.Random(0), entry_turn=6, tolerance=0)
    assert t is not None and t.entry_turn == 6
    assert pool.sample(random.Random(0), entry_turn=99, tolerance=0) is not None  # 回退全库


def test_replay_script_order_and_fallback(tmp_path):
    _traj_file(tmp_path, seed=3, frames=(6, 8))
    pool = TrajectoryPool(str(tmp_path))
    t = pool.items[0]
    sc = ReplayScript(t, learner_seat=0)
    assert sc.next_action(1, 6) == 16      # 10 + turn
    assert sc.next_action(2, 6) == 26
    assert sc.next_action(1, 6) is None    # 用完 → bot 接管
    assert sc.next_action(0, 6) is None    # 学习座位不回放
    assert sc.next_action(3, 6) is None
    assert sc.next_action(1, 8) == 18      # 下一帧
    assert sc.has_turn(8) is True          # seat2 的 8 回合动作还在
    assert sc.next_action(2, 8) == 28
    assert sc.has_turn(8) is False         # 两个座位都取完
