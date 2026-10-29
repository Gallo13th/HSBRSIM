"""回合末场面快照镜像对手：引擎侧 + 采集 + 训练侧注入的 CPU 单测（无 GPU / 无 torch）。

覆盖（对应 ``docs/MIRROR_SNAPSHOT_DESIGN.md`` §8 与任务清单）：

1. 字段白名单：``board``/``tier`` 被替换，``health``/``alive``/``placement``/``hero`` 保留；
2. EID：注入后全局（board/hand/shop/hand_queue）EID 无重复，且与源帧的 EID 不同；
3. 池：注入前后 ``pool_balance`` 都 ok、逐物种守恒；注入实体 ``pool_copies=0``（不占池）；
4. 拒绝路径：死座位 / 已 ended / 未知引用 —— 不抛异常、``state_json`` 前后一致；
5. ``scripts/capture_trajectory.py --emit-snapshots`` 的 schema 冒烟（1 局、bot 驱动、
   CPU）+ 采集到的帧能被引擎真正接受；
6. 训练侧注入驱动（``inject_turn``，与 ``collect_ppo_lockstep`` 同一条路径）的 CPU 冒烟，
   以及 ``--mirror-p 0`` 的零影响；
7. ``collect_ppo_lockstep`` 的接线（结构断言；torch 不可用时不做真实前向）。

torch 在本机不可用（CUDA 版缺 nvidia 库），因此训练侧用「无 torch 的注入驱动 + 引擎
bot 驱动」跑通整条注入链路。
"""

from __future__ import annotations

import gzip
import inspect
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

hsbg_engine = pytest.importorskip(
    "hsbg_engine",
    reason="hsbg_engine 未安装（Rust 引擎需 `cd rust && python3 -m pip install -e .`）")
MR = pytest.importorskip("hsbg.az.train.mirror_snapshots",
                         reason="hsbg.az.train.mirror_snapshots 不可用")

ROOT = Path(__file__).resolve().parents[1]
N_PLAYERS = 8


# ────────────────────────── 工具 ──────────────────────────


def drive_to(game, turn: int):
    """推进到某个**新回合**开始（所有座位都未 ended、尚未行动）。"""
    while not game.is_over() and int(game.turn) < int(turn):
        for p in range(N_PLAYERS):
            if int(game.turn) >= int(turn) or game.is_over():
                break
            if game.needs_action(p):
                game.bot_play(p)
    return game


def play_one_round(game) -> None:
    """让每个仍能行动的座位把本回合走完（bot），直到进入下一回合。"""
    for p in range(N_PLAYERS):
        if game.is_over():
            return
        if game.needs_action(p):
            game.bot_play(p)


def play_out(game, *, max_steps: int = 20000) -> int:
    steps = 0
    while not game.is_over() and steps < max_steps:
        acted = False
        for p in range(N_PLAYERS):
            if game.needs_action(p):
                game.bot_play(p)
                acted = True
                steps += 1
        if not acted:
            break
    return steps


def seat_json(game, seat: int):
    return json.loads(game.player_json(int(seat)))


def clean_seats(game):
    """pending 为空且存活的座位（只有这些座位能作为注入目标）。"""
    out = []
    for s in range(N_PLAYERS):
        pj = seat_json(game, s)
        if pj.get("alive") and not pj.get("pending"):
            out.append(s)
    return out


def recruit_game(seed: int, turn: int = 4, *, need_clean: bool = True):
    """推进到一个「有可注入座位」的新回合：饰品回合（6/9）所有座位都有 pending，
    自动再多打一回合绕开（pending 非空按设计 fail-closed 拒绝）。"""
    g = drive_to(hsbg_engine.Game(seed=seed), turn)
    for _ in range(4):
        if g.is_over():
            break
        if not need_clean or clean_seats(g):
            return g
        play_one_round(g)
    return g


def clean_seat(game, seats=None, *, need_board: bool = True):
    """找一个 pending 为空（且牌面非空）的座位，返回 ``(seat, player_dict)``。"""
    for s in (seats if seats is not None else range(N_PLAYERS)):
        pj = seat_json(game, s)
        if pj.get("pending") or not pj.get("alive"):
            continue
        if need_board and not pj.get("board"):
            continue
        return int(s), pj
    return None, None


def global_eids(game) -> list:
    st = json.loads(game.state_json())
    out = []
    for pl in st["players"]:
        out += [int(m["eid"]) for m in pl["board"]]
        out += [int(h["hid"]) for h in pl["hand"]]
        out += [int(s["sid"]) for s in pl["shop"]]
        for it in pl.get("hand_queue") or []:
            if isinstance(it, dict) and "Minion" in it:
                out.append(int(it["Minion"]["eid"]))
    return out


def board_sig(player) -> list:
    return [(int(m["card"]), int(m["atk"]), int(m["hp"]), bool(m.get("golden")))
            for m in player.get("board") or []]


@pytest.fixture(scope="module")
def snap_dir(tmp_path_factory) -> Path:
    """跑一次 ``capture_trajectory.py --driver bot --emit-snapshots``（1 局 CPU）。"""
    out = tmp_path_factory.mktemp("mirror_smoke")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "rust" / "python"), str(ROOT), env.get("PYTHONPATH", "")])
    cmd = [sys.executable, str(ROOT / "scripts" / "capture_trajectory.py"),
           "--driver", "bot", "--games", "1", "--seed", "810000",
           "--from-turn", "1", "--min-frames", "1", "--max-steps", "4000",
           "--emit-snapshots", "1", "--out", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=900)
    assert proc.returncode == 0, proc.stderr[-2000:]
    info = json.loads(proc.stdout.strip().splitlines()[-1])
    assert int(info["snap_files"]) == 1, info
    assert int(info["snap_frames"]) > 0, info
    (out / "info.json").write_text(json.dumps(info), encoding="utf-8")
    return out


def pool_of(snap_dir: Path):
    return MR.MirrorSnapshotPool(str(snap_dir / "snapshots"))


# ────────────────────────── 1. 字段白名单 ──────────────────────────


def test_field_whitelist_health_alive_kept_board_replaced():
    g = recruit_game(1001, 4)
    h = recruit_game(3003, 7)
    src_seat, src = clean_seat(h)
    assert src_seat is not None, "没有可用的源场面"
    cleans = clean_seats(g)
    assert cleans, "目标局没有任何可注入座位"
    seat = 1 if 1 in cleans else cleans[0]
    before = seat_json(g, seat)
    pb_before = g.pool_balance()

    rep = g.apply_turn_snapshots([[seat, json.dumps(src)]], None)
    assert rep["applied"] == 1, rep
    assert list(rep["rejected"]) == [], rep
    assert rep["pool_balance_ok"] and rep["pool_species_ok"], rep
    assert rep["advanced"] is False

    after = seat_json(g, seat)
    # 白名单外：当前局字段原样保留
    for key in ("id", "health", "armor", "alive", "placement", "hero", "sees_all_boards"):
        assert after.get(key) == before.get(key), key
    assert len(after.get("powers") or []) == len(before.get("powers") or [])
    # 白名单内：场面被替换
    assert board_sig(after) == board_sig(src)
    assert int(after["tier"]) == int(src["tier"])
    assert int(after["gold"]) == int(src["gold"])
    assert after["last_board"] and len(after["last_board"]) == len(after["board"])
    # EOT 语义：本回合不再行动
    assert bool(after["ended_turn"]) is True
    assert not g.needs_action(seat)
    # 注入实体不占共享池
    assert all(int(m.get("pool_copies", 0)) == 0 for m in after["board"])
    # 池状态不变（总量 + 逐物种）
    assert g.pool_balance() == pb_before
    assert g.pool_species_violations() == []
    assert g.invariant_violations() == []


# ────────────────────────── 2. EID 唯一性 ──────────────────────────


def test_eid_unique_after_injection():
    g = recruit_game(1001, 4)
    h = recruit_game(4004, 8)
    cleans = clean_seats(g)
    assert len(cleans) >= 3
    targets = cleans[:3]
    snaps, src_eids = [], set()
    used_sources = set()
    for target in targets:
        src_seat, src = clean_seat(h, seats=[s for s in range(N_PLAYERS)
                                             if s not in used_sources])
        if src_seat is None:
            break
        used_sources.add(src_seat)
        src_eids.update(int(m["eid"]) for m in src["board"])
        src_eids.update(int(x["hid"]) for x in src["hand"])
        snaps.append([target, json.dumps(src)])
    assert len(snaps) >= 2, "至少要有 2 个源帧"
    rep = g.apply_turn_snapshots(snaps, None)
    assert rep["applied"] == len(snaps), rep

    eids = global_eids(g)
    assert len(eids) == len(set(eids)), "注入后全局 EID 必须唯一"
    # 新实体的 EID 必须重新分配（不能复用源帧的 EID）
    for target, _ in snaps:
        got = {int(m["eid"]) for m in seat_json(g, target)["board"]}
        assert got and not (got & src_eids), "注入实体必须用 alloc_eid 重新分配"
    assert g.invariant_violations() == []


# ────────────────────────── 3. 池守恒 / 旧持有物归还 ──────────────────────────


def test_pool_balance_and_old_holding_returned():
    g = recruit_game(1001, 5)
    h = recruit_game(5005, 8)
    src_seat, src = clean_seat(h)
    assert src_seat is not None
    cleans = clean_seats(g)
    seat = 2 if 2 in cleans else cleans[0]
    old = seat_json(g, seat)
    old_held = MR.held_pool_parts(old)
    assert old_held, "目标座位原本应占用共享池副本（否则本测试无意义）"
    pb_before = g.pool_balance()
    assert pb_before[0] == pb_before[1], "基线必须自洽"

    rep = g.apply_turn_snapshots([[seat, json.dumps(src)]], None)
    assert rep["applied"] == 1, rep
    assert rep["pool_balance_ok"], rep
    assert rep["pool_species_ok"], rep
    # 旧持有物按 visit_pool_parts 归还 → 总量与逐物种都不变
    assert g.pool_balance() == pb_before
    assert g.pool_species_violations() == []
    after = seat_json(g, seat)
    assert MR.held_pool_parts(after) == [], "注入场面不得占用共享池"
    # 继续打完整局：池守恒与结构不变量始终成立
    play_out(g)
    assert g.is_over()
    assert g.pool_balance()[0] == g.pool_balance()[1]
    assert g.pool_species_violations() == []


# ────────────────────────── 4. 拒绝路径不改状态 ──────────────────────────


def test_rejections_do_not_change_state():
    g = recruit_game(1001, 4)
    h = recruit_game(6006, 7)
    src_seat, src = clean_seat(h)
    assert src_seat is not None
    snap = json.dumps(src)
    cleans = clean_seats(g)
    assert len(cleans) >= 2
    ended_seat = cleans[0]
    ref_seat = cleans[1]

    # (a) 已结束回合
    assert g.needs_action(ended_seat)
    g.step(ended_seat, 0)
    s0 = g.state_json()
    pb0 = g.pool_balance()
    assert bool(seat_json(g, ended_seat)["ended_turn"]) is True
    rep = g.apply_turn_snapshots([[ended_seat, snap]], None)
    assert rep["applied"] == 0
    assert rep["rejected"] and int(rep["rejected"][0][0]) == ended_seat
    assert "already_ended" in str(rep["rejected"][0][1]), rep
    assert g.state_json() == s0
    assert g.pool_balance() == pb0

    # (b) 未知 typed 引用（killed_by 指向帧外实体）
    bad = json.loads(snap)
    bad["board"] = [dict(m) for m in bad["board"]]
    bad["board"][0]["killed_by"] = 987654
    rep = g.apply_turn_snapshots([[ref_seat, json.dumps(bad)]], None)
    assert rep["applied"] == 0
    assert "unknown_ref" in str(rep["rejected"][0][1]), rep
    assert g.state_json() == s0

    # (c) 死座位：把血量清零 -> 淘汰 -> 拒绝且状态不变
    dead_seat = next(s for s in range(N_PLAYERS) if s not in (ended_seat, ref_seat))
    g.debug(json.dumps({"cmd": "set_player", "p": int(dead_seat), "health": 0}))
    guard = 0
    while not g.is_over() and guard < 200:
        if not bool(seat_json(g, dead_seat).get("alive")):
            break
        p = next((q for q in range(N_PLAYERS) if g.needs_action(q) and q != dead_seat), None)
        if p is None:
            break
        g.step(int(p), 0)
        guard += 1
    assert not bool(seat_json(g, dead_seat).get("alive")), "该座位应已被淘汰"
    s1 = g.state_json()
    rep = g.apply_turn_snapshots([[dead_seat, snap]], None)
    assert rep["applied"] == 0
    assert rep["rejected"] and int(rep["rejected"][0][0]) == dead_seat
    assert "not_alive" in str(rep["rejected"][0][1]), rep
    assert g.state_json() == s1


# ────────────────────────── 5. 采集 schema 冒烟 ──────────────────────────


def test_capture_emit_snapshots_schema(snap_dir: Path):
    info = json.loads((snap_dir / "info.json").read_text(encoding="utf-8"))
    assert int(info["games"]) == 1
    files = sorted((snap_dir / "snapshots").glob("snap_*.json.gz"))
    assert len(files) == 1, files
    with gzip.open(files[0], "rt", encoding="utf-8") as f:
        rec = json.load(f)
    assert rec["schema"] == MR.SCHEMA
    assert int(rec["schema_version"]) == MR.SCHEMA_VERSION
    assert int(rec["schema_version"]) == int(hsbg_engine.snapshot_schema_version())
    assert rec["engine"]["game_version"] and rec["engine"]["version"]
    assert rec["meta"]["driver"] == "bot"
    frames = rec["frames"]
    assert len(frames) == int(info["snap_frames"])
    turns = {int(fr["turn"]) for fr in frames}
    seats = {int(fr["seat"]) for fr in frames}
    assert turns and seats == set(range(N_PLAYERS))
    for fr in frames[:8]:
        for key in ("turn", "seat", "player", "held_pool_parts", "stage", "pool_mode",
                    "frame_sha256", "source_game_seed"):
            assert key in fr, key
        assert fr["stage"] == MR.STAGE_EOT
        assert fr["pool_mode"] == "unknown"
        assert fr["player"]["ended_turn"] is True
        assert len(fr["frame_sha256"]) == 64
    # 读取端 + 引擎回读：采到的帧能被真实注入一次
    pool = MR.MirrorSnapshotPool(str(snap_dir / "snapshots"))
    assert pool.frames == int(info["snap_frames"])
    assert pool.stats()["seats"] == list(range(N_PLAYERS))
    g = recruit_game(810000, 8)
    assert not g.is_over()
    target, frame = None, None
    for s in clean_seats(g):
        for t in sorted(turns, reverse=True):
            fr = pool.get(t, s)
            if fr is not None:
                target, frame = s, fr
                break
        if frame is not None:
            break
    assert frame is not None and target is not None, "没有「可注入座位 + 该座位帧」的组合"
    pb = g.pool_balance()
    rep = g.apply_turn_snapshots([[target, frame.player_json]], None)
    assert rep["applied"] == 1, rep
    assert rep["pool_balance_ok"] and rep["pool_species_ok"], rep
    assert g.pool_balance() == pb
    assert board_sig(seat_json(g, target)) == board_sig(frame.player)
    play_out(g)
    assert g.is_over()


# ────────────────────────── 6. 训练侧注入驱动（CPU 冒烟） ──────────────────────────


def test_lockstep_mirror_driver_smoke(snap_dir: Path):
    """复刻 ``collect_ppo_lockstep`` 的注入窗口：新 turn、任何座位行动前注入。"""
    pool = pool_of(snap_dir)
    assert pool.frames > 0
    seed, games, seats, prob = 777000, 2, 3, 0.6
    learner = 0
    targets = MR.mirror_seats(seats, N_PLAYERS, learner)
    assert targets == [1, 2, 3]
    stats = MR.MirrorStats()
    states = []
    for gi in range(games):
        g = hsbg_engine.Game(seed=seed + gi)
        states.append({"g": g, "rng": random.Random(seed + gi * 31),
                       "turn": int(g.turn)})
    pool_checks = 0
    rounds = 0
    while True:
        active = [st for st in states if not st["g"].is_over()]
        if not active:
            break
        for st in active:
            g, r = st["g"], st["rng"]
            if int(g.turn) != int(st["turn"]):        # 新回合开始
                st["turn"] = int(g.turn)
                MR.inject_turn(g, pool, int(g.turn), seats=targets, p=prob, rng=r,
                               learner_seat=learner, stats=stats)
                held, initial = g.pool_balance()
                pool_checks += 1
                assert held == initial, (g.turn, held, initial)
                assert g.pool_species_violations() == [], g.turn
            # 其余座位由 bot 驱动（被注入的座位 ended_turn=true，不再消耗动作）
            for p in range(N_PLAYERS):
                if p == learner:
                    continue
                if g.needs_action(p):
                    g.bot_play(p)
            if g.needs_action(learner):
                g.bot_play(learner)
        rounds += 1
        assert rounds < 20000

    meta = stats.to_meta()
    assert meta["mirror_attempt"] > 0, meta
    assert meta["mirror_applied"] > 0, meta
    assert meta["mirror_pool_unbalanced"] == 0, meta
    assert meta["mirror_pool_species_unbalanced"] == 0, meta
    assert meta["mirror_rejected"] > 0, "饰品回合（pending 非空）应被 fail-closed 拒绝"
    assert meta["mirror_missing"] > 0, "没有该 turn/seat 的帧应计入 missing"
    assert meta["mirror_fallback"] >= meta["mirror_missing"], meta
    for st in states:
        assert st["g"].is_over()
        held, initial = st["g"].pool_balance()
        assert held == initial
        assert st["g"].pool_species_violations() == []
    # 记录数字，便于人工核对冒烟规模
    print(f"[mirror-smoke] games={games} seats={targets} p={prob} pool_checks={pool_checks} "
          f"attempt={meta['mirror_attempt']} applied={meta['mirror_applied']} "
          f"rejected={meta['mirror_rejected']} missing={meta['mirror_missing']} "
          f"fallback={meta['mirror_fallback']} errors={meta['mirror_errors']}")


def test_mirror_p_zero_is_noop(snap_dir: Path):
    """``--mirror-p 0``（默认）必须零影响：同一 seed 的终局状态字节一致。"""
    pool = pool_of(snap_dir)
    seats = MR.mirror_seats(3, N_PLAYERS, 0)

    def run(with_pool: bool) -> str:
        g = hsbg_engine.Game(seed=910000)
        r = random.Random(12345)
        turn = int(g.turn)
        stats = MR.MirrorStats()
        guard = 0
        while not g.is_over() and guard < 20000:
            if int(g.turn) != int(turn):
                turn = int(g.turn)
                MR.inject_turn(g, pool if with_pool else None, turn,
                               seats=seats, p=0.0, rng=r, learner_seat=0, stats=stats)
            acted = False
            for p in range(N_PLAYERS):
                if g.needs_action(p):
                    g.bot_play(p)
                    acted = True
                    guard += 1
            if not acted:
                break
        if with_pool:
            assert stats.to_meta()["mirror_applied"] == 0
            assert stats.to_meta()["mirror_attempt"] == 0
        return g.state_json()

    assert run(False) == run(True)


# ────────────────────────── 7. 训练侧接线（结构断言） ──────────────────────────


def test_collect_ppo_lockstep_wiring():
    """torch 不可用时只做结构断言：``--mirror-*`` 已接到 lockstep 采集。"""
    pc = pytest.importorskip("hsbg.az.train.parallel_collect")
    sig = inspect.signature(pc.collect_ppo_lockstep)
    for name in ("mirror_pool", "mirror_seats_count", "mirror_p"):
        assert name in sig.parameters, name
    from hsbg.az.train.ppo import CollectConfig

    cfg = CollectConfig()
    assert cfg.mirror_snaps == "" and cfg.mirror_p == 0.0 and cfg.mirror_seats == 0
    src = (ROOT / "hsbg" / "az" / "train" / "parallel_collect.py").read_text(encoding="utf-8")
    for token in ("_maybe_mirror", "inject_turn", "mirror_seats_count", "mirror_stats"):
        assert token in src, token
    meta = MR.MirrorStats(attempt=1, applied=1, rejected=2, missing=3, fallback=4).to_meta()
    for key in ("mirror_attempt", "mirror_applied", "mirror_rejected", "mirror_missing",
                "mirror_fallback"):
        assert key in meta, key
