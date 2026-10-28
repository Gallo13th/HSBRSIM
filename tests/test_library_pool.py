"""镜像对手库（LibraryPool）单测：质量门、去重、按 turn 采样、持久化。"""

from __future__ import annotations

import json
import random

from hsbg.az.train.library_pool import LibraryEntry, LibraryPool, board_strength


def _player(cards, turn=10):
    return {"board": [{"card": c, "atk": 10, "hp": 10, "golden": False} for c in cards],
            "hand": [], "tier": 4, "health": 20, "gold": 10, "turn": turn}


def _entry(cards, turn=10, placement=1):
    p = _player(cards, turn)
    return LibraryEntry(player=p, turn=turn, placement=placement,
                        strength=board_strength(p))


def test_quality_gate_filters_weak_and_early():
    pool = LibraryPool(min_turn=8, max_placement=2, min_board=4)
    assert pool.add(_entry([1, 2, 3, 4], turn=10, placement=2)) is True
    assert pool.add(_entry([1, 2, 3, 4], turn=6, placement=1)) is False      # 太早
    assert pool.add(_entry([1, 2, 3], turn=10, placement=1)) is False        # 牌太少
    assert pool.add(_entry([1, 2, 3, 4], turn=10, placement=3)) is False     # 名次太差
    assert len(pool.entries) == 1


def test_dedup_same_signature():
    pool = LibraryPool(min_turn=8, max_placement=2, min_board=4)
    assert pool.add(_entry([1, 2, 3, 4])) is True
    assert pool.add(_entry([1, 2, 3, 4])) is False
    assert len(pool.entries) == 1


def test_sampling_respects_turn_bucket():
    pool = LibraryPool(min_turn=8, max_placement=2, min_board=4, bucket=2)
    for i, turn in enumerate((8, 10, 12, 14)):
        e = _entry([1, 2, 3, 4], turn=turn)
        e.strength = 100 + i * 10
        pool.add(e)
    rng = random.Random(0)
    got = {pool.sample(12, rng=rng).turn for _ in range(20)}
    assert got <= {10, 12, 14}, got                      # 只看 turn 桶 ±1
    assert pool.sample(4, rng=rng) is None               # 太早没有候选


def test_save_load_roundtrip(tmp_path):
    pool = LibraryPool(min_turn=8, max_placement=2, min_board=4)
    pool.add(_entry([1, 2, 3, 4], turn=10))
    pool.add(_entry([5, 6, 7, 8], turn=12))
    path = str(tmp_path / "pool.jsonl")
    pool.save(path)
    n = len(open(path).read().strip().splitlines())
    assert n == 2
    again = LibraryPool(path)
    assert len(again.entries) == 2
    assert again.stats()["turn_min"] == 10
    assert again.stats()["size"] == 2
