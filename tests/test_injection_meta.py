"""注入计数可见性（``mirror_*`` / ``human_board_*`` 进 history）+ 采集冒烟。

背景：s6 之前 ``history.jsonl`` 的 ``collect`` 段里看不到镜像快照 / 人类战团的注入
计数（process_pool 只把 worker meta 塞进 ``worker_meta``，而 ``slim_collect`` 会把这个
大字段整块丢掉），因此无法验证 ``--mirror-*`` / ``--human-board-*`` 是否真的生效。

覆盖：

1. ``slim_collect`` 保留注入键：顶层 / 嵌套 ``collect`` / 仅 ``worker_meta`` 三种位置；
   缺失时不补键、不报错；其余大字段仍被剔除；
2. ``aggregate_injection`` 的跨 worker 聚合口径：计数 sum / 开关 any / p mean；
3. CPU tiny 冒烟：``collect_ppo_lockstep`` 同时带 mirror 快照 + 人类战团，meta 里
   ``mirror_applied > 0`` 且 ``human_board_applied > 0``（引擎 + torch 缺失则 skip）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsbg.az.train.runlog import (INJECTION_KEYS, aggregate_injection,
                                  slim_collect)


# ══════════════════════════════════════════════════════════════════════════
# 1. slim_collect：三种位置都能保住注入键
# ══════════════════════════════════════════════════════════════════════════
def test_slim_keeps_top_level_injection_fields():
    meta = {
        "decisions": 31000,
        "worker_meta": [{"big": "x" * 100}],
        "mirror_on": True, "mirror_attempt": 30, "mirror_applied": 21,
        "mirror_rejected": 6, "mirror_missing": 3, "mirror_p": 0.3,
        "mirror_sample": "p75", "mirror_fallback": 9, "mirror_errors": 0,
        "mirror_last_rejected": [[3, "pending_choice(1)"]],
        "human_board_on": True, "human_board_attempt": 20,
        "human_board_applied": 12, "human_board_rejected": 5,
        "human_board_missing": 3, "human_board_skipped_by_mirror": 4,
        "human_board_errors": 0, "human_board_p": 0.15,
        "human_board_sample": "auto",
    }
    slim = slim_collect(meta)
    assert "worker_meta" not in slim
    for key in INJECTION_KEYS:
        if key in meta:
            assert slim[key] == meta[key], key
    assert slim["mirror_applied"] == 21
    assert slim["mirror_errors"] == 0
    assert slim["human_board_skipped_by_mirror"] == 4
    # 原对象不被修改
    assert "worker_meta" in meta


def test_slim_lifts_injection_from_nested_collect():
    meta = {
        "decisions": 100,
        "worker_meta": [{"big": 1}],
        "collect": {
            "decisions": 100,
            "worker_meta": [{"big": 2}],
            "mirror_on": True, "mirror_attempt": 7, "mirror_applied": 5,
            "human_board_on": False, "human_board_attempt": 0,
        },
    }
    slim = slim_collect(meta)
    assert "worker_meta" not in slim and "worker_meta" not in slim["collect"]
    # 提升到 collect 段顶层，history 里 rec["collect"]["mirror_applied"] 可直接读
    assert slim["mirror_applied"] == 5
    assert slim["mirror_on"] is True
    assert slim["human_board_on"] is False
    assert "human_board_applied" not in slim      # 缺失不补键


def test_slim_aggregates_worker_meta_when_parent_missing():
    meta = {
        "decisions": 64,
        "worker_meta": [
            {"mirror_on": True, "mirror_attempt": 4, "mirror_applied": 3,
             "mirror_rejected": 1, "mirror_missing": 0, "mirror_p": 0.3,
             "mirror_sample": "p75",
             "human_board_on": True, "human_board_attempt": 2,
             "human_board_applied": 1, "human_board_rejected": 1,
             "human_board_missing": 0, "human_board_skipped_by_mirror": 1,
             "human_board_p": 0.1, "human_board_sample": "auto"},
            {"mirror_on": False, "mirror_attempt": 6, "mirror_applied": 4,
             "mirror_rejected": 2, "mirror_missing": 1, "mirror_p": 0.5,
             "mirror_sample": "p75",
             "human_board_on": False, "human_board_attempt": 3,
             "human_board_applied": 2, "human_board_rejected": 1,
             "human_board_missing": 0, "human_board_skipped_by_mirror": 2,
             "human_board_p": 0.3, "human_board_sample": "auto"},
        ],
    }
    slim = slim_collect(meta)
    assert "worker_meta" not in slim
    assert slim["mirror_on"] is True              # any
    assert slim["mirror_attempt"] == 10           # sum
    assert slim["mirror_applied"] == 7
    assert slim["mirror_p"] == pytest.approx(0.4)  # mean
    assert slim["human_board_applied"] == 3
    assert slim["human_board_skipped_by_mirror"] == 3
    assert slim["human_board_sample"] == "auto"


def test_slim_missing_injection_does_not_raise():
    meta = {"decisions": 1, "collect": {"decisions": 1}}
    slim = slim_collect(meta)
    assert slim["decisions"] == 1
    assert not any(k in slim for k in INJECTION_KEYS)
    # 非 dict 输入同样安全
    assert slim_collect(None) == {}
    assert slim_collect("nope") == {}


def test_aggregate_injection_handles_nested_and_garbage():
    agg = aggregate_injection([
        {"collect": {"mirror_attempt": 2, "mirror_applied": 1}},
        {"mirror_attempt": 3, "mirror_applied": 2, "mirror_on": False},
        "garbage",
        None,
    ])
    assert agg["mirror_attempt"] == 5
    assert agg["mirror_applied"] == 3
    assert agg["mirror_on"] is False


# ══════════════════════════════════════════════════════════════════════════
# 2. CPU tiny 冒烟：lockstep 采集带 mirror + human board，meta 计数可见
# ══════════════════════════════════════════════════════════════════════════
def _synthetic_human_pool(tmp_path: Path):
    HB = pytest.importorskip("hsbg.az.train.human_board_pool")
    rows = []
    for turn in range(1, 16):
        for j, (card, atk, hp) in enumerate(
                [(824, 2, 2), (992, 3, 3), (824, 4, 4)]):
            rows.append({
                "turn": int(turn), "strength": int(atk + hp),
                "board": [{"card": int(card), "atk": int(atk), "hp": int(hp),
                           "position": k} for k, (card, atk, hp) in
                          enumerate([(824, 2, 2), (992, 3, 3)][: 1 + (j % 2)])],
                "hero": 371, "source": "real_10k", "game_id": "synthetic",
                "quality": "degraded", "split": "train",
            })
    path = tmp_path / "human_pool.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return HB.HumanBoardPool(str(path), sample="auto")


def _synthetic_mirror_pool(tmp_path: Path):
    """用引擎 bot 自对弈前几回合，采集真实 EOT 快照帧（不跑子进程）。"""
    E = pytest.importorskip("hsbg_engine")
    MR = pytest.importorskip("hsbg.az.train.mirror_snapshots")
    g = E.Game(seed=881001)
    frames = []
    guard = 0
    while not g.is_over() and int(g.turn) <= 8 and guard < 20000:
        guard += 1
        for seat in range(1, 8):
            if g.is_over():
                break
            if g.needs_action(seat):
                try:
                    fr = MR.capture_eot(g, seat)
                except (ValueError, RuntimeError):
                    fr = None       # 选英雄阶段等：本回合跳过该座位
                if fr is not None:
                    frames.append(fr)
        for seat in range(8):
            if g.is_over():
                break
            if g.needs_action(seat):
                g.step(seat, int(g.bot_action(seat)))
    assert frames, "没有采到任何 EOT 快照帧"
    root = tmp_path / "snapshots"
    MR.write_snapshot_file(str(root / "snap_00000001.json.gz"), frames,
                           seed=881001)
    return MR.MirrorSnapshotPool(str(root))


def test_lockstep_collect_with_mirror_and_human_board_reports_counts(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("hsbg_engine")
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.model import build_net
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep
    from hsbg.az.train.ppo import CollectConfig

    mirror = _synthetic_mirror_pool(tmp_path)
    human = _synthetic_human_pool(tmp_path)
    model = build_net(arch="tiny")
    model.eval()
    server = BatchLeafServer(model, device="cpu", batch_size=64, max_wait_ms=1.0)
    try:
        cfg = CollectConfig(games=2, seed=881002, opponent="bot",
                            behavior="net", max_steps=8000,
                            lockstep=True, fast_act=True)
        records, meta = collect_ppo_lockstep(
            model, cfg, eval_fn=BatchPPOEvaluator(server), device="cpu",
            seed=881002, games=2,
            mirror_pool=mirror, mirror_seats_count=3, mirror_p=1.0,
            mirror_seat_random=False,
            human_board_pool=human, human_board_p=1.0, human_board_seats=6,
            human_board_sample="auto", human_board_set_tier=True)
    finally:
        server.close()

    assert meta["mode"] == "lockstep" and meta["decisions"] == len(records) > 0
    assert meta["mirror_on"] is True and meta["human_board_on"] is True
    assert meta["mirror_p"] == 1.0 and meta["human_board_p"] == 1.0
    assert meta["mirror_attempt"] > 0, meta
    assert meta["mirror_applied"] > 0, meta
    assert meta["human_board_attempt"] > 0, meta
    assert meta["human_board_applied"] > 0, meta
    # slim 后这些计数仍在（history.jsonl 的 collect 段就是这个形状）
    slim = slim_collect(meta)
    for key in ("mirror_on", "mirror_attempt", "mirror_applied",
                "human_board_on", "human_board_attempt", "human_board_applied"):
        assert key in slim, key
    assert slim["mirror_applied"] == meta["mirror_applied"]
    assert slim["human_board_applied"] == meta["human_board_applied"]
    # 至少有一条记录可构 batch（注入没把对局搞坏）
    assert all(bool(r["mask"][int(r["action"])]) for r in records)
