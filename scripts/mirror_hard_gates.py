#!/usr/bin/env python3
"""PPAI CPU 硬门：回合末快照镜像注入的 ``p × seats`` 矩阵（无 GPU / 无 torch）。

用途：证明「每回合开始、任何座位行动前」注入在正常回合 / pending（饰品 t6/t9）/
死亡座位 / hand_queue 引用 / 缺帧 / 注入后淘汰等场景下都满足：

- 时序：注入永远发生在该回合任何座位行动之前；
- EID：注入后全局 EID 唯一；
- 池：``pool_balance`` 总量守恒、逐物种无违规（pending 待选时跳过——引擎文档允许）、
  结构 ``invariant_violations()`` 为空；
- 拒绝：只允许 pending/死亡等预期原因；任何非预期 reject 即失败；
- 拒绝事务性：每次拒绝前后 ``state_json`` 字节完全一致（100%）；
- 规模：``--seeds``（每格 seed 数，默认 1000）× 15 格，累计注入
  ≥ ``--min-injections``（默认 100000，不够自动加大 seed 数）。

对局完全由引擎 bot 驱动（``E.Game(seed)`` + ``bot_play``），不加载任何模型。

用法::

  PYTHONPATH=rust/python:. python scripts/mirror_hard_gates.py
  PYTHONPATH=rust/python:. python scripts/mirror_hard_gates.py --seeds 50 --min-injections 5000
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.mirror_snapshots import (  # noqa: E402
    EXPECTED_REJECT_REASONS, MirrorSnapshotPool, MirrorStats, SnapshotFrame,
    engine_stamp, inject_turn, is_expected_reject, load_pool, mirror_seats_random,
    reject_reason_class,
)

N_PLAYERS = 8
GATE_SCHEMA = "hsbg.mirror_hard_gates"


# ────────────────────────── 小工具 ──────────────────────────


def _alive_and_pending(game: Any) -> Tuple[List[int], Set[int]]:
    """当前存活座位 + 其中有 pending 待选的座位（一次 player_json 扫描）。"""
    alive: List[int] = []
    pending: Set[int] = set()
    for s in range(N_PLAYERS):
        try:
            pj = json.loads(game.player_json(int(s)))
        except BaseException:  # noqa: BLE001
            continue
        if bool(pj.get("alive")):
            alive.append(int(s))
            if pj.get("pending"):
                pending.add(int(s))
    return alive, pending


def _global_eids(state: Dict[str, Any]) -> List[int]:
    """全局实体 id（board eid / hand hid / shop sid / hand_queue minion eid）。"""
    out: List[int] = []
    for pl in state.get("players") or []:
        out += [int(m["eid"]) for m in pl.get("board") or []]
        out += [int(h["hid"]) for h in pl.get("hand") or []]
        out += [int(s["sid"]) for s in pl.get("shop") or []]
        for it in pl.get("hand_queue") or []:
            if isinstance(it, dict) and "Minion" in it:
                out.append(int(it["Minion"]["eid"]))
    return out


def _drive_to_turn(game: Any, turn: int, *, max_rounds: int = 200) -> Any:
    """bot 推进到 ``turn`` 回合开始（所有存活座位均未行动）。"""
    rounds = 0
    while not game.is_over() and int(game.turn) < int(turn) and rounds < max_rounds:
        rounds += 1
        for p in range(N_PLAYERS):
            if game.is_over() or int(game.turn) >= int(turn):
                break
            if game.needs_action(p):
                game.bot_play(int(p))
    return game


def _play_round(game: Any) -> None:
    """让所有可行动座位走完本回合（可能推进到下一回合）。"""
    t = int(game.turn)
    for p in range(N_PLAYERS):
        if game.is_over() or int(game.turn) != t:
            break
        if game.needs_action(p):
            game.bot_play(int(p))


class _FixedPool:
    """探针用：无论 (turn, seat) 都返回同一帧（只为触发引擎校验路径）。"""

    frames = 1
    sample_mode = "probe"

    def __init__(self, frame: SnapshotFrame):
        self.frame = frame

    def get(self, turn: int, seat: int, rng: Any = None) -> Optional[SnapshotFrame]:
        return self.frame


class _EmptyPool:
    """探针用：任何 (turn, seat) 都缺帧。"""

    frames = 0
    sample_mode = "empty"

    def get(self, turn: int, seat: int, rng: Any = None) -> Optional[SnapshotFrame]:
        return None


def _first_frame(pool: MirrorSnapshotPool) -> Optional[SnapshotFrame]:
    for frames in pool.index.values():
        if frames:
            return frames[0]
    return None


def _hand_queue_frame(pool: MirrorSnapshotPool) -> Tuple[Optional[SnapshotFrame], bool]:
    """找一个 hand_queue 非空的帧；库里没有则合成一个（把 board 末位移入队列）。"""
    for frames in pool.index.values():
        for fr in frames:
            if fr.player.get("hand_queue"):
                return fr, False
    base = _first_frame(pool)
    if base is None:
        return None, False
    player = copy.deepcopy(base.player)
    if not player.get("board"):
        return None, False
    minion = player["board"].pop()
    player.setdefault("hand_queue", []).append({"Minion": minion})
    # 故意不补齐 hand_queue_marks：长度不一致时引擎跳过 mark 校验，minion.eid 即实体 id。
    synth = SnapshotFrame(turn=int(base.turn), seat=int(base.seat), player=player,
                          source_game_seed=int(base.source_game_seed))
    return synth, True


# ────────────────────────── 探针（场景覆盖） ──────────────────────────


def _identity_probe(game: Any, pool: Any, turn: int, seat: int,
                    stats: MirrorStats) -> Dict[str, Any]:
    """一次注入 + 拒绝前后 state_json 字节比较。"""
    s0 = game.state_json()
    before = {"applied": stats.applied, "rejected": stats.rejected,
              "missing": stats.missing}
    inject_turn(game, pool, turn, seats=[seat], p=1.0, stats=stats)
    s1 = game.state_json()
    return {"seat": int(seat), "turn": int(turn),
            "applied": int(stats.applied - before["applied"]),
            "rejected": int(stats.rejected - before["rejected"]),
            "missing": int(stats.missing - before["missing"]),
            "reasons": dict(stats.rejected_by_reason),
            "state_identical": bool(s0 == s1)}


def _scenario_probes(pool: MirrorSnapshotPool, learner: int) -> Dict[str, Any]:
    """正常/pending/死亡/缺帧/hand_queue/注入后淘汰 的场景探针。"""
    out: Dict[str, Any] = {"failures": []}
    reject_identity = {"checked": 0, "identical": 0}
    sample = _first_frame(pool)

    def _note_identity(probe: Dict[str, Any]) -> None:
        if int(probe["rejected"]) > 0:
            reject_identity["checked"] += 1
            if probe["state_identical"]:
                reject_identity["identical"] += 1
            else:
                out["failures"].append(
                    f"reject_state_changed:{probe['turn']}/{probe['seat']}")

    # ---- 1) pending：饰品回合 t6 / t9 ----
    pending_rec: List[Dict[str, Any]] = []
    g = _drive_to_turn(__import__("hsbg_engine").Game(seed=730001), 6)
    for target_turn in (6, 9):
        if int(g.turn) < target_turn:
            _drive_to_turn(g, target_turn)
        alive, pending = _alive_and_pending(g)
        if not pending:
            # 某些 seed 的 t6/t9 pending 可能已被上一轮消掉：继续打一轮再试。
            for _ in range(3):
                _play_round(g)
                alive, pending = _alive_and_pending(g)
                if pending:
                    break
        if not pending or sample is None:
            pending_rec.append({"turn": target_turn, "found": False})
            continue
        choices = sorted(s for s in pending if int(s) != int(learner))
        if not choices:
            pending_rec.append({"turn": target_turn, "found": False})
            continue
        seat = choices[0]
        st = MirrorStats()
        probe = _identity_probe(g, _FixedPool(sample), target_turn, seat, st)
        reason = reject_reason_class(next(iter(st.rejected_by_reason), ""))
        probe.update({"turn": target_turn, "found": True, "reason": reason,
                      "expected": reason in EXPECTED_REJECT_REASONS})
        if probe["rejected"] <= 0:
            out["failures"].append(f"pending_not_rejected:t{target_turn}/s{seat}")
        if reason not in EXPECTED_REJECT_REASONS:
            out["failures"].append(
                f"pending_unexpected_reason:{reason}@t{target_turn}/s{seat}")
        _note_identity(probe)
        pending_rec.append(probe)
    out["pending"] = pending_rec

    # ---- 2) 死亡座位 ----
    dead_rec: Dict[str, Any] = {"found": False}
    g2 = __import__("hsbg_engine").Game(seed=730002)
    for _ in range(12):
        if g2.is_over():
            break
        _play_round(g2)
        alive, _pending = _alive_and_pending(g2)
        dead = [s for s in range(N_PLAYERS) if s not in alive and s != int(learner)]
        if dead and int(g2.turn) >= 3 and not g2.is_over():
            seat = dead[0]
            st = MirrorStats()
            probe = _identity_probe(g2, _FixedPool(sample), int(g2.turn), seat, st)
            reason = reject_reason_class(next(iter(st.rejected_by_reason), ""))
            probe.update({"found": True, "reason": reason,
                          "expected": reason in EXPECTED_REJECT_REASONS})
            if probe["rejected"] <= 0:
                out["failures"].append(f"dead_seat_not_rejected:s{seat}")
            if reason not in EXPECTED_REJECT_REASONS:
                out["failures"].append(f"dead_seat_unexpected_reason:{reason}")
            _note_identity(probe)
            dead_rec = probe
            break
    if not dead_rec.get("found"):
        # 显式淘汰一个非 learner 座位后再探测（避免依赖随机对局恰好出现死亡）。
        g2b = _drive_to_turn(__import__("hsbg_engine").Game(seed=730005), 4)
        victim = 7 if int(learner) != 7 else 6
        try:
            g2b.debug(json.dumps({"cmd": "set_player", "p": int(victim), "health": 0}))
        except BaseException:  # noqa: BLE001
            pass
        for _ in range(300):
            if g2b.is_over():
                break
            pj = json.loads(g2b.player_json(int(victim)))
            if not bool(pj.get("alive")):
                break
            _play_round(g2b)
        if not g2b.is_over() and not bool(
                json.loads(g2b.player_json(int(victim))).get("alive")):
            st = MirrorStats()
            probe = _identity_probe(g2b, _FixedPool(sample), int(g2b.turn), victim, st)
            reason = reject_reason_class(next(iter(st.rejected_by_reason), ""))
            probe.update({"found": True, "reason": reason, "victim": int(victim),
                          "expected": reason in EXPECTED_REJECT_REASONS})
            if probe["rejected"] <= 0:
                out["failures"].append(f"dead_seat_not_rejected:s{victim}")
            if reason not in EXPECTED_REJECT_REASONS:
                out["failures"].append(f"dead_seat_unexpected_reason:{reason}")
            _note_identity(probe)
            dead_rec = probe
    out["dead_seat"] = dead_rec

    # ---- 3) 缺帧 ----
    empty_pool = _EmptyPool()
    g3 = __import__("hsbg_engine").Game(seed=730003)
    st3 = MirrorStats()
    s0 = g3.state_json()
    inject_turn(g3, empty_pool, 1, seats=[1, 2, 3], p=1.0, stats=st3)
    missing_rec = {"attempt": int(st3.attempt), "missing": int(st3.missing),
                   "applied": int(st3.applied),
                   "state_identical": bool(g3.state_json() == s0)}
    if not (missing_rec["attempt"] == 3 and missing_rec["missing"] == 3
            and missing_rec["applied"] == 0):
        out["failures"].append(f"missing_probe_bad:{missing_rec}")
    if not missing_rec["state_identical"]:
        out["failures"].append("missing_probe_changed_state")
    # 真实库 + 越界 turn：也应计入 missing 且不改状态。
    st3b = MirrorStats()
    s1 = g3.state_json()
    inject_turn(g3, pool, 10 ** 6, seats=[1, 2], p=1.0, stats=st3b)
    missing_rec["real_pool_attempt"] = int(st3b.attempt)
    missing_rec["real_pool_missing"] = int(st3b.missing)
    missing_rec["real_pool_state_identical"] = bool(g3.state_json() == s1)
    if missing_rec["real_pool_attempt"] != 2 or missing_rec["real_pool_missing"] != 2:
        out["failures"].append(f"missing_real_pool_bad:{missing_rec}")
    out["missing"] = missing_rec

    # ---- 4) hand_queue 引用 ----
    hq_frame, synth = _hand_queue_frame(pool)
    hq_rec: Dict[str, Any] = {"found": hq_frame is not None, "synthetic": bool(synth),
                              "applied": 0, "eid_unique": False,
                              "state_has_hand_queue": False, "invariants_ok": False}
    if hq_frame is not None:
        # 帧载荷与目标局无关（引擎只校验 Player 载荷），固定在第 2 回合的干净座位上注入。
        for attempt_i in range(6):
            g4 = _drive_to_turn(__import__("hsbg_engine").Game(seed=730004 + attempt_i), 2)
            alive, pending = _alive_and_pending(g4)
            candidates = [s for s in alive if s not in pending and s != learner]
            if not candidates:
                continue
            seat = candidates[attempt_i % len(candidates)]
            st4 = MirrorStats()
            inject_turn(g4, _FixedPool(hq_frame), int(g4.turn), seats=[seat],
                        p=1.0, stats=st4)
            if int(st4.applied) <= 0:
                continue
            state = json.loads(g4.state_json())
            target = state["players"][seat]
            eids = _global_eids(state)
            hq_rec.update({
                "seat": int(seat), "turn": int(g4.turn), "applied": int(st4.applied),
                "eid_unique": len(eids) == len(set(eids)),
                "state_has_hand_queue": bool(target.get("hand_queue")),
                "invariants_ok": not bool(g4.invariant_violations()),
                "pool_balance_ok": (g4.pool_balance()[0] == g4.pool_balance()[1]),
            })
            break
        if hq_rec["applied"] <= 0:
            out["failures"].append("hand_queue_frame_not_applied")
        if hq_rec["applied"] and not hq_rec["eid_unique"]:
            out["failures"].append("hand_queue_eid_duplicate")
        if hq_rec["applied"] and not hq_rec["state_has_hand_queue"]:
            out["failures"].append("hand_queue_not_replaced")
    out["hand_queue"] = hq_rec

    out["reject_state_identity"] = reject_identity
    return out


# ────────────────────────── 主矩阵 ──────────────────────────


def _new_cell(p: float, seats: int) -> Dict[str, Any]:
    return {
        "p": float(p), "seats": int(seats), "seeds": 0, "games": 0,
        "attempt": 0, "applied": 0, "rejected": 0, "missing": 0, "errors": 0,
        "rejected_by_reason": {},
        "coverage_by_turn_and_alive_seat": {},
        "violations": {"timing": 0, "duplicate_eid": 0, "pool_balance": 0,
                       "pool_species": 0, "invariants": 0, "unexpected_reject": 0,
                       "errors": 0},
        "reject_identity": {"checked": 0, "identical": 0},
        "post_injection_eliminations": 0,
        "injected_seats_eliminated": 0,
        "queue_injections": 0,
        "eid_full_checks": 0,
        "eid_checks_turns": 0,
        "engine_pool_species_turns": 0,
        "engine_pool_species_samples": [],
        "truncated_games": 0,
        "elapsed_s": 0.0,
    }


def _cov(cell: Dict[str, Any], turn: int, seat: int) -> Dict[str, int]:
    by_turn = cell["coverage_by_turn_and_alive_seat"].setdefault(str(int(turn)), {})
    return by_turn.setdefault(str(int(seat)), {"alive": 0, "attempt": 0, "applied": 0})


def _check_pool(game: Any, has_pending: bool, cell: Dict[str, Any]) -> None:
    """池**总量**守恒 + 结构不变量（含全局 EID）。

    逐物种守恒不在这里做绝对判断：引擎允许 pending Discover / 淘汰瞬间在区域外持有
    副本（纯 bot 对局也会出现，见 ``baseline_pool_species``）。注入前后的逐物种集合
    必须**逐次不变**，这一条在 :func:`_run_seed` 里按每次注入调用逐次校验。
    """
    if not has_pending:
        try:
            held, initial = game.pool_balance()
            if int(held) != int(initial):
                cell["violations"]["pool_balance"] += 1
        except BaseException:  # noqa: BLE001
            cell["violations"]["pool_balance"] += 1
    try:
        iv = list(game.invariant_violations())
    except BaseException:  # noqa: BLE001
        cell["violations"]["invariants"] += 1
        return
    cell["eid_checks_turns"] += 1
    for msg in iv:
        if "duplicate eid" in str(msg):
            cell["violations"]["duplicate_eid"] += 1
        else:
            cell["violations"]["invariants"] += 1


def _check_eids(game: Any, cell: Dict[str, Any]) -> None:
    """注入后全局 EID 唯一性。"""
    try:
        _check_eids_state(json.loads(game.state_json()), cell)
    except BaseException:  # noqa: BLE001
        cell["violations"]["errors"] += 1


def _check_eids_state(state: Dict[str, Any], cell: Dict[str, Any]) -> None:
    try:
        eids = _global_eids(state)
    except BaseException:  # noqa: BLE001
        cell["violations"]["errors"] += 1
        return
    if len(eids) != len(set(eids)):
        cell["violations"]["duplicate_eid"] += 1


def _alive_by_placements(game: Any) -> List[int]:
    """``placements() == 0`` 表示仍存活（引擎约定；死亡座位已获名次）。"""
    try:
        pl = list(game.placements())
    except BaseException:  # noqa: BLE001
        return []
    return [int(s) for s, rank in enumerate(pl) if int(rank) == 0]


def _has_pending_text(player_json: str) -> bool:
    """不做完整 JSON 解析：serde 紧凑序列化下 ``pending`` 为空即 ``"pending":[]``。"""
    return not ('"pending":[]' in player_json or '"pending": []' in player_json)


def _run_seed(cell: Dict[str, Any], seed: int, *, pool: MirrorSnapshotPool,
              p: float, seats_count: int, learner: int, max_steps: int) -> None:
    """一局 bot 对局：每回合开始注入，校验时序/EID/池/拒绝事务性。

    性能：每回合只序列化存活座位的 ``player_json``（约 0.2 ms），用子串判断
    ``alive``/``pending``/``ended_turn``；完整 ``state_json`` 只在「注入的帧带
    hand_queue」时解析一次做全量 EID 校验。EID/结构/池的常规检查走引擎
    ``invariant_violations`` / ``pool_*``（都是毫秒级以下）。
    """
    import hsbg_engine as E

    g = E.Game(seed=int(seed))
    rng = random.Random((int(seed) * 1000003 + int(seats_count) * 7919
                         + int(round(float(p) * 1000)) * 104729) & 0x7FFFFFFF)
    st = MirrorStats()
    steps = 0
    last_turn = -1
    p_on = float(p) > 0.0
    while not g.is_over() and steps < int(max_steps):
        turn = int(g.turn)
        applied_seats: Set[int] = set()
        alive: List[int] = []
        if turn != last_turn:
            last_turn = turn
            alive = _alive_by_placements(g)
            texts = {int(s): g.player_json(int(s)) for s in alive}
            pending = {s for s, txt in texts.items() if _has_pending_text(txt)}
            ended = {s for s, txt in texts.items() if '"ended_turn":true' in txt}
            alive_set = set(alive)
            # turn 0 是 hero-select / 没有「回合末」定义（设计 §2.2）：不注入、不记覆盖。
            if turn >= 1:
                for s in alive:
                    _cov(cell, turn, s)["alive"] += 1
            targets = mirror_seats_random(int(seats_count), rng, N_PLAYERS, learner)

            # 信息项：引擎在 pending/淘汰边缘可能合法持有区域外池副本（非注入引起）。
            try:
                sp_turn = list(g.pool_species_violations())
            except BaseException:  # noqa: BLE001
                sp_turn = []
            if sp_turn:
                cell["engine_pool_species_turns"] += 1
                if len(cell["engine_pool_species_samples"]) < 5:
                    cell["engine_pool_species_samples"].append(
                        {"turn": int(turn), "sample": [str(x) for x in sp_turn[:2]]})

            # 时序：新回合开始，任何存活座位都不应已 ended（即已行动过）。
            if turn >= 1:
                cell["violations"]["timing"] += len(ended)

            if p_on and turn >= 1:
                for seat in targets:
                    if int(g.turn) != turn:
                        cell["violations"]["timing"] += 1
                        break
                    if int(seat) in ended:
                        cell["violations"]["timing"] += 1
                    a0, ap0, r0, m0, e0 = (st.attempt, st.applied, st.rejected,
                                           st.missing, st.errors)
                    hq0 = st.applied_with_hand_queue
                    pb0 = tuple(int(x) for x in g.pool_balance())
                    sp0 = frozenset(g.pool_species_violations())
                    inject_turn(g, pool, turn, seats=[int(seat)], p=float(p), rng=rng,
                                learner_seat=int(learner), stats=st)
                    pb1 = tuple(int(x) for x in g.pool_balance())
                    sp1 = frozenset(g.pool_species_violations())
                    # 注入事务性（提交阶段只归还旧 parts、新实体 pool_copies=0）：
                    # 总量与逐物种集合都必须逐次不变。
                    if pb0 != pb1:
                        cell["violations"]["pool_balance"] += 1
                    if sp0 != sp1:
                        cell["violations"]["pool_species"] += 1
                    d_attempt = st.attempt - a0
                    d_applied = st.applied - ap0
                    d_rejected = st.rejected - r0
                    # 覆盖率只统计「该回合存活座位」；死亡座位的尝试计入 not_alive 拒绝。
                    if d_attempt and int(seat) in alive_set:
                        _cov(cell, turn, int(seat))["attempt"] += d_attempt
                    if d_applied:
                        if int(seat) in alive_set:
                            _cov(cell, turn, int(seat))["applied"] += d_applied
                        applied_seats.add(int(seat))
                    if st.errors != e0:
                        cell["violations"]["errors"] += int(st.errors - e0)
                    if st.applied_with_hand_queue != hq0:
                        cell["queue_injections"] += int(
                            st.applied_with_hand_queue - hq0)
                        # 含 hand_queue 的注入：做一次全量全局 EID 校验。
                        cell["eid_full_checks"] += 1
                        try:
                            _check_eids_state(json.loads(g.state_json()), cell)
                        except BaseException:  # noqa: BLE001
                            cell["violations"]["errors"] += 1
                    if d_rejected:
                        # 拒绝事务性：在**当前状态**上复现同一拒绝，比较前后 state_json 字节。
                        frame = pool.get(turn, int(seat), rng=random.Random(0))
                        if frame is not None:
                            s0 = g.state_json()
                            try:
                                g.apply_turn_snapshots(
                                    [[int(seat), frame.player_json]], None)
                            except BaseException:  # noqa: BLE001
                                cell["violations"]["errors"] += 1
                            s1 = g.state_json()
                            cell["reject_identity"]["checked"] += 1
                            if s0 == s1:
                                cell["reject_identity"]["identical"] += 1

            # 注入后检查（每回合一次）：结构不变量（含全局 EID）+ 池守恒。
            _check_pool(g, bool(pending), cell)

        # bot 推进本回合（被注入座位 ended_turn=true，不再行动）。
        acted = False
        for p2 in range(N_PLAYERS):
            if g.is_over() or int(g.turn) != turn:
                break
            if g.needs_action(int(p2)):
                g.bot_play(int(p2))
                acted = True
                steps += 1
        if not g.is_over() and int(g.turn) == turn and not acted:
            break

        # 注入后淘汰：本回合结束（进入下一回合/终局）时统计。
        if p_on and (g.is_over() or int(g.turn) != turn):
            alive_after = set(_alive_by_placements(g))
            dead_now = [s for s in alive if s not in alive_after]
            if dead_now:
                cell["post_injection_eliminations"] += len(dead_now)
                cell["injected_seats_eliminated"] += len(set(dead_now) & applied_seats)

    if steps >= int(max_steps) and not g.is_over():
        cell["truncated_games"] += 1

    # 汇总本局计数。
    cell["attempt"] += int(st.attempt)
    cell["applied"] += int(st.applied)
    cell["rejected"] += int(st.rejected)
    cell["missing"] += int(st.missing)
    cell["errors"] += int(st.errors)
    for reason, n in st.rejected_by_reason.items():
        cls = reject_reason_class(reason)
        cell["rejected_by_reason"][cls] = cell["rejected_by_reason"].get(cls, 0) + int(n)
        if cls not in EXPECTED_REJECT_REASONS:
            cell["violations"]["unexpected_reject"] += int(n)
    if st.rejected != sum(int(v) for v in st.rejected_by_reason.values()):
        # 理论上恒等；不等说明统计路径漏计。
        cell["violations"]["errors"] += 1
    _check_pool(g, False, cell)


def _finalize_cell(cell: Dict[str, Any]) -> None:
    v = cell["violations"]
    ident = cell["reject_identity"]
    rate = (ident["identical"] / ident["checked"]) if ident["checked"] else 1.0
    cell["reject_identity"]["rate"] = float(rate)
    cell["consistency_ok"] = (
        int(cell["attempt"]) == int(cell["applied"]) + int(cell["rejected"])
        + int(cell["missing"]))
    cell["zero_violations"] = bool(
        all(int(v[k]) == 0 for k in v) and rate == 1.0 and cell["consistency_ok"])


def run_cell(p: float, seats_count: int, *, seeds: int, base_seed: int,
             pool: MirrorSnapshotPool, learner: int, max_steps: int,
             seed_salt: int = 0) -> Dict[str, Any]:
    cell = _new_cell(p, seats_count)
    t0 = time.time()
    for k in range(int(seeds)):
        _run_seed(cell, int(base_seed) + k + int(seed_salt), pool=pool, p=float(p),
                  seats_count=int(seats_count), learner=int(learner),
                  max_steps=int(max_steps))
    cell["seeds"] = int(seeds)
    cell["games"] = int(seeds)
    cell["elapsed_s"] = round(time.time() - t0, 3)
    _finalize_cell(cell)
    return cell


#: 进程池（fork）里复用父进程已加载的只读快照库；spawn 回退时按路径重载。
_GLOBAL_POOL: Optional[MirrorSnapshotPool] = None


def _cell_task(task: Tuple[Any, ...]) -> Dict[str, Any]:
    (p, seats_count, seeds, base_seed, snaps, sample, learner,
     max_steps, seed_salt) = task
    pool = _GLOBAL_POOL
    if pool is None:
        pool = load_pool(str(snaps), sample=str(sample))
    if pool is None:
        raise RuntimeError(f"快照库为空/不存在: {snaps}")
    return run_cell(p, seats_count, seeds=seeds, base_seed=base_seed, pool=pool,
                    learner=learner, max_steps=max_steps, seed_salt=seed_salt)


# ────────────────────────── CLI / 汇总 ──────────────────────────


def _parse_floats(text: str) -> List[float]:
    return [float(x) for x in str(text).split(",") if str(x).strip()]


def _parse_ints(text: str) -> List[int]:
    return [int(float(x)) for x in str(text).split(",") if str(x).strip()]


def _baseline_pool_species(base_seed: int, games: int) -> Dict[str, Any]:
    """纯 bot 基线：统计引擎自身（无任何注入）出现的逐物种池违规。

    引擎文档允许 pending Discover / 淘汰瞬间在区域外持有副本；这里量化该基线，用于
    区分「注入引入的违规」（必须为 0）与「引擎轨迹边缘态」（信息项）。
    """
    import hsbg_engine as E

    seeds_with = 0
    events = 0
    samples: List[Dict[str, Any]] = []
    for k in range(int(games)):
        seed = int(base_seed) + k
        g = E.Game(seed=seed)
        last = -1
        hit = False
        while not g.is_over():
            if int(g.turn) != last:
                last = int(g.turn)
                try:
                    sv = list(g.pool_species_violations())
                except BaseException:  # noqa: BLE001
                    sv = []
                if sv:
                    events += 1
                    hit = True
                    if len(samples) < 5:
                        samples.append({"seed": seed, "turn": int(last),
                                        "sample": [str(x) for x in sv[:2]]})
            acted = False
            for p in range(N_PLAYERS):
                if g.is_over() or int(g.turn) != last:
                    break
                if g.needs_action(int(p)):
                    g.bot_play(int(p))
                    acted = True
            if not acted:
                break
        if hit:
            seeds_with += 1
    return {"games": int(games),
            "seeds_with_pool_species_violation": int(seeds_with),
            "events": int(events), "samples": samples}


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="镜像快照注入 CPU 硬门（p×seats 矩阵）")
    ap.add_argument("--snaps", default="runs/library/snaps_champ",
                    help="快照库目录（snap_*.json.gz）")
    ap.add_argument("--out", default="runs/library/mirror_hard_gates.json",
                    help="输出 JSON 路径")
    ap.add_argument("--seeds", type=int, default=1000,
                    help="每个 (p, seats) 格的 seed 数（默认 1000，共 15 格）")
    ap.add_argument("--min-injections", type=int, default=100000,
                    help="全矩阵累计注入下限；不够自动加大 seed 数")
    ap.add_argument("--base-seed", type=int, default=730000, help="对局 seed 起点")
    ap.add_argument("--max-steps", type=int, default=20000, help="单局步数守卫")
    ap.add_argument("--learner-seat", type=int, default=0, help="learner 座位（不注入）")
    ap.add_argument("--sample", default="p50",
                    choices=["p50", "p75", "p90", "max", "strong", "weak", "random"],
                    help="快照桶内采样模式（默认 p50 课程）")
    ap.add_argument("--p-values", default="0,0.1,0.25,0.5,1")
    ap.add_argument("--seat-values", default="1,3,7")
    ap.add_argument("--workers", type=int, default=0,
                    help="矩阵并行进程数（0=min(格数, CPU)；fork 复用已加载快照库）")
    ap.add_argument("--baseline-games", type=int, default=2000,
                    help="纯 bot 基线局数：量化引擎自身的逐物种池边缘态（信息项）")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    t_all = time.time()
    p_values = _parse_floats(args.p_values)
    seat_values = _parse_ints(args.seat_values)
    for p in p_values:
        if not (0.0 <= p <= 1.0):
            print(f"[error] p 越界: {p}", file=sys.stderr)
            return 2
    for s in seat_values:
        if not (1 <= s <= N_PLAYERS - 1):
            print(f"[error] seats 越界: {s}", file=sys.stderr)
            return 2

    pool = load_pool(args.snaps, sample=str(args.sample))
    if pool is None:
        print(f"[error] 快照库为空/不存在: {args.snaps}", file=sys.stderr)
        return 2
    print(f"[gate] engine={engine_stamp()} snaps={pool.stats()}", flush=True)

    seeds = max(1, int(args.seeds))
    workers = int(args.workers)
    if workers <= 0:
        workers = min(len(p_values) * len(seat_values), os.cpu_count() or 1)
    workers = max(1, workers)
    print(f"[gate] cells={len(p_values) * len(seat_values)} seeds/cell={seeds} "
          f"workers={workers}", flush=True)

    global _GLOBAL_POOL
    _GLOBAL_POOL = pool
    results: List[Dict[str, Any]] = []
    total_attempt = 0
    for round_i in range(4):
        tasks = [(float(p), int(seats_count), int(seeds), int(args.base_seed),
                  str(args.snaps), str(args.sample), int(args.learner_seat),
                  int(args.max_steps), round_i * 100000)
                 for p in p_values for seats_count in seat_values]
        results = []
        if workers > 1 and len(tasks) > 1:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor
            methods = mp.get_all_start_methods()
            ctx = mp.get_context("fork") if "fork" in methods else mp.get_context()
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
                for cell in ex.map(_cell_task, tasks):
                    results.append(cell)
                    print(f"[cell] p={cell['p']:.2f} seats={cell['seats']} "
                          f"seeds={seeds} attempt={cell['attempt']} "
                          f"applied={cell['applied']} rejected={cell['rejected']} "
                          f"missing={cell['missing']} zero={cell['zero_violations']} "
                          f"elapsed={cell['elapsed_s']}s", flush=True)
        else:
            for task in tasks:
                cell = _cell_task(task)
                results.append(cell)
                print(f"[cell] p={cell['p']:.2f} seats={cell['seats']} seeds={seeds} "
                      f"attempt={cell['attempt']} applied={cell['applied']} "
                      f"rejected={cell['rejected']} missing={cell['missing']} "
                      f"zero={cell['zero_violations']} elapsed={cell['elapsed_s']}s",
                      flush=True)
        total_attempt = int(sum(c["attempt"] for c in results))
        if total_attempt >= int(args.min_injections):
            break
        scale = math.ceil(int(args.min_injections) / max(total_attempt, 1) * 1.05)
        new_seeds = max(seeds + 1, int(math.ceil(seeds * scale)))
        print(f"[gate] 注入 {total_attempt} < {args.min_injections}；"
              f"seeds {seeds} -> {new_seeds} 重跑", flush=True)
        seeds = new_seeds

    # 场景探针（与矩阵独立，保证 pending/死亡/缺帧/hand_queue 至少各测一次）。
    t_probe = time.time()
    scenarios = _scenario_probes(pool, int(args.learner_seat))
    scenarios["elapsed_s"] = round(time.time() - t_probe, 3)
    # 纯 bot 基线（信息项）：引擎自身在 pending/淘汰边缘的逐物种池边缘态。
    baseline = _baseline_pool_species(int(args.base_seed),
                                      max(1, int(args.baseline_games)))

    failures: List[str] = []
    if total_attempt < int(args.min_injections):
        failures.append(f"injections {total_attempt} < min {args.min_injections}")
    if int(sum(c["applied"] for c in results)) <= 0:
        failures.append("no_successful_injection")
    if int(sum(c["injected_seats_eliminated"] for c in results)) <= 0:
        failures.append("scenario_not_covered: injected_seat_eliminated==0")
    for cell in results:
        if not cell["zero_violations"]:
            failures.append(f"cell p={cell['p']} seats={cell['seats']} violations="
                            f"{cell['violations']} identity="
                            f"{cell['reject_identity']}")
    failures.extend(scenarios.pop("failures", []))

    total_identity = {"checked": 0, "identical": 0}
    for cell in results:
        total_identity["checked"] += int(cell["reject_identity"]["checked"])
        total_identity["identical"] += int(cell["reject_identity"]["identical"])
    sb = scenarios.get("reject_state_identity") or {}
    total_identity["checked"] += int(sb.get("checked", 0))
    total_identity["identical"] += int(sb.get("identical", 0))
    total_identity["rate"] = (total_identity["identical"]
                              / total_identity["checked"]
                              if total_identity["checked"] else 1.0)
    if total_identity["rate"] != 1.0:
        failures.append(f"reject_state_identity rate={total_identity['rate']} < 1.0")

    def _cell_key(c: Dict[str, Any]) -> Tuple[float, int]:
        return (float(c["p"]), int(c["seats"]))

    payload = {
        "schema": GATE_SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "engine": engine_stamp(),
        "config": {
            "snaps": os.path.abspath(str(args.snaps)),
            "sample": str(args.sample),
            "seeds_per_cell": int(seeds),
            "min_injections": int(args.min_injections),
            "p_values": list(p_values),
            "seat_values": list(seat_values),
            "learner_seat": int(args.learner_seat),
            "base_seed": int(args.base_seed),
            "max_steps": int(args.max_steps),
            "pool_stats": pool.stats(),
            "expected_reject_reasons": sorted(EXPECTED_REJECT_REASONS),
        },
        "totals": {
            "games": int(sum(c["games"] for c in results)),
            "seeds": int(seeds),
            "attempt": int(sum(c["attempt"] for c in results)),
            "applied": int(sum(c["applied"] for c in results)),
            "rejected": int(sum(c["rejected"] for c in results)),
            "missing": int(sum(c["missing"] for c in results)),
            "errors": int(sum(c["errors"] for c in results)),
            "engine_pool_species_turns": int(
                sum(c["engine_pool_species_turns"] for c in results)),
            "post_injection_eliminations": int(
                sum(c["post_injection_eliminations"] for c in results)),
            "injected_seats_eliminated": int(
                sum(c["injected_seats_eliminated"] for c in results)),
            "reject_identity": total_identity,
            "elapsed_s": round(time.time() - t_all, 3),
        },
        "cells": sorted(results, key=_cell_key),
        "scenarios": scenarios,
        "baseline_pool_species": baseline,
        "failures": failures,
        "zero_violations": not failures,
    }

    out_path = os.path.abspath(str(args.out))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, out_path)
    print(f"[gate] -> {out_path}  zero_violations={payload['zero_violations']}  "
          f"attempt={payload['totals']['attempt']} applied={payload['totals']['applied']} "
          f"elapsed={payload['totals']['elapsed_s']}s", flush=True)

    if failures:
        for msg in failures:
            print(f"[FAIL] {msg}", file=sys.stderr, flush=True)
        return 1
    print("[gate] PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
