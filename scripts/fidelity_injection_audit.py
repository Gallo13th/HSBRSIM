#!/usr/bin/env python3
"""三组配对保真度审计：**B0 board-only（现状） / B1 +hand / B2 +counters（完整）**。

用 ``scripts/pressure_audit.py`` 的 **460 帧可信完整 EOT 快照**
（``runs/library/snaps_champ/*.json.gz``，我们自己的引擎状态 → 隐藏真值已知），
在**同状态、同战斗 RNG** 下逐帧配对比较五条臂：

======  ====================================================================
臂       定义
======  ====================================================================
B0      现状：``Game.inject_board`` 只注入人类可见 board（金色 ``_G`` 卡 id 保留）
B1      ``fidelity="hand"``：B0 的 board + **手牌**
B2      ``fidelity="full"``：完整帧（关键词位/金身/圣盾层数/attachments/counter/
        gems/tier/gold 全保留）= 任务里的「board + hand + counters」
B2+     B2 + **玩家级 combat overlay**（trinkets/quests/rewards/secrets/effects/
        stats/counters/tier7）——``apply_turn_snapshots`` 白名单保留这些字段，
        Python 侧再补一次；真实观测里这些字段**不可得**
B2++    B2+ 再 overlay ``hero``/``powers``（≈ ground truth；训练不建议，会改变
        后续回合的主动玩法）
FULL    ground truth：``set_player_from_json`` 整帧替换（旧审计的「完整状态」臂）
======  ====================================================================

两种口径：

- ``combat``：容器座位 = 本局真实座位，注入后**立刻**用 ``combat_preview`` 打
  （同帧口径，隔离「信息量」）；``B2 ≈ FULL`` 就是在检验**新注入 API 的数据通路**；
- ``pipeline``：注入发生在**回合起点**，之后该座位照常 bot 行动（训练真实管线），
  再用战斗前战团重播种。这里手牌/金币**才会**产生作用。

输出 ``runs/audit/fidelity_injection.json``（全部数字）+ 控制台配对表。

用法::

    PYTHONPATH=rust/python:. python scripts/fidelity_injection_audit.py \
        --frames 460 --battle-seeds 64 --survivor-seeds 12 --workers 12
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_pa():
    """把 ``scripts/pressure_audit.py`` 当模块载入（复用已审计过的工具函数）。"""
    path = os.path.join(ROOT, "scripts", "pressure_audit.py")
    spec = importlib.util.spec_from_file_location("_pressure_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


PA = _load_pa()
E = PA.load_engine()

N_PLAYERS = PA.N_PLAYERS
LEARNER_SEAT = PA.LEARNER_SEAT
DEFAULT_OUT = "runs/audit/fidelity_injection.json"
ARMS = ("B0", "B1", "B2", "B2r", "B2+", "B2++", "FULL")
PIPELINE_ARMS = ("B0", "B1", "B2", "B2r", "B2+")


# ────────────────────────── 载荷构造 ──────────────────────────


def _frame_payloads(pj: Dict[str, Any], turn: int, golden2base: Dict[int, int]
                    ) -> Dict[str, Dict[str, Any]]:
    """一帧完整 Player JSON -> 四条臂的 payload（B0 直接用 board list）。"""
    board = pj.get("board") or []
    hand = pj.get("hand") or []
    tier = int(pj.get("tier") or 0) or None
    gold = int(pj.get("gold") or 0)
    # 人类观测能看到的 board：金色身份由 _G 卡 id 表达（颜色/统计已在卡面里）
    flat = [[int(m["card"]), int(m["atk"]), int(m["hp"])] for m in board]
    # B1 / B2q：只用「可见」通道重建的 board 项
    det_base: List[Dict[str, Any]] = []
    det_full: List[Dict[str, Any]] = []
    for m in board:
        common = {"card": int(m["card"]), "atk": int(m["atk"]), "hp": int(m["hp"])}
        det_base.append(dict(common))
        det_full.append(dict(common, json=m))
    hand_norm = []
    for h in hand:
        item = h.get("item") or {}
        if isinstance(item, dict) and "Minion" in item:
            mm = item["Minion"]
            hand_norm.append({"card": int(mm["card"]), "kind": "minion",
                              "atk": int(mm.get("atk") or 1), "hp": int(mm.get("hp") or 1),
                              "golden": bool(mm.get("golden")),
                              "kw": int(mm.get("kw") or 0) | int(mm.get("bonus_kw") or 0)})
        elif isinstance(item, dict) and "Spell" in item:
            hand_norm.append({"card": int(item["Spell"]["card"]), "kind": "spell"})
    av = {"board": "observed", "golden": "observed", "keywords": "observed",
          "shield_max": "observed", "tavern_tier": "observed", "hand": "observed",
          "gold": "unavailable", "attachments": "unavailable", "counter": "unavailable",
          "gems": "unavailable", "shop": "unavailable", "pool_delta": "unavailable"}
    # 玩家级字段（trinkets/quests/rewards/secrets/levels/effects/counters/stats/tier7 +
    # hero/powers）：apply_turn_snapshots 的**保留**区，需要 Python 侧 overlay。
    player = {k: pj.get(k) for k in
              ("trinkets", "quests", "rewards", "secrets", "levels", "effects",
               "counters", "stats", "tier7", "hero", "powers") if k in pj}
    base = {"schema": "hsbg.audit_frame", "turn": int(turn), "board_flat": flat,
            "hand_available": True, "hand": hand_norm, "tier": tier, "gold": None,
            "availability": av, "has_detail": True, "player": player}
    return {
        "B0": dict(base, board=det_base, hand_available=False, hand=[]),
        "B1": dict(base, board=det_base),
        "B2": dict(base, board=det_full, gold=int(gold)),
        # B2r：真实观测可做到的版本（gold 不可得 -> 保留当前局 gold；tier 用观测值）
        "B2r": dict(base, board=det_full, gold=None),
        "B2+": dict(base, board=det_full, gold=int(gold)),
        "B2++": dict(base, board=det_full, gold=int(gold)),
        "board_flat": flat,
    }


# ────────────────────────── 单帧、单臂 ──────────────────────────


def _arm_game(cont: Dict[str, Any], boot: int) -> Any:
    return PA._battle_game(E, cont["start_state"], cont["learner_json"],
                           int(cont["target"]), cont["target_json"], boot_seed=boot)


def _apply_arm(E_: Any, g: Any, arm: str, tgt: int, pays: Dict[str, Any],
               tier_derived: int) -> Dict[str, Any]:
    """在容器 ``g`` 上施加某条臂；返回 ``{ok, reason, ...}``。"""
    from hsbg.az.train.human_obs_full import inject_quasi_state  # noqa: PLC0415

    if arm == "B0":
        rep = g.inject_board(int(tgt), [list(x) for x in pays["board_flat"]], int(tier_derived))
        return {"ok": bool(rep.get("applied")), "reason": str(rep.get("reason")),
                "pool_ok": bool(rep.get("pool_balance_ok", True))}
    if arm == "B1":
        rep = inject_quasi_state(g, int(tgt), pays["B1"], "hand", reset_ended=True,
                                 player_overlay="none")
    elif arm in ("B2", "B2r", "B2+", "B2++"):
        pov = {"B2": "none", "B2r": "none", "B2+": "combat", "B2++": "all"}[arm]
        rep = inject_quasi_state(g, int(tgt), pays[arm], "full", reset_ended=True,
                                 player_overlay=pov)
    else:  # FULL：整帧替换（ground truth；与旧审计同一条路）
        g.set_player_from_json(int(tgt), str(pays["_frame_json"]), True, True)
        return {"ok": True, "reason": "ok", "pool_ok": None}
    return {"ok": bool(rep.get("applied")), "reason": str(rep.get("reason")),
            "pool_ok": bool(rep.get("pool_balance_ok", True)),
            "hand": bool(rep.get("hand_applied")), "counters": bool(rep.get("counters_applied"))}


def _preview_arm(arm: str, cont: Dict[str, Any], pays: Dict[str, Any], boot: int,
                 tier_derived: int, n_seed: int) -> Dict[str, Any]:
    g = _arm_game(cont, boot)
    ap = _apply_arm(E, g, arm, int(cont["target"]), pays, tier_derived)
    if not ap["ok"]:
        return {"ok": False, "reason": ap.get("reason")}
    r = PA._trials(PA._preview(E, g, LEARNER_SEAT, int(cont["target"]), int(n_seed), True))
    return {"ok": True, "loss": PA._loss_seq(r["winner"]),
            "win": PA._win_seq(r["winner"]),
            "dmg_taken": PA._mean(r["dmg_taken"]), "dmg_dealt": PA._mean(r["dmg_dealt"]),
            "dmg_taken_seq": r["dmg_taken"], "win_seq": r["winner"],
            "pool_ok": ap.get("pool_ok")}


def _surv_arm(arm: str, cont: Dict[str, Any], pays: Dict[str, Any], base_boot: int,
              tier_derived: int, n: int) -> List[float]:
    out: List[float] = []
    for i in range(max(0, int(n))):
        boot = int(base_boot) ^ ((PA.TRIAL_SEED_K * (i + 1)) & 0xFFFFFFFFFFFFFFFF) ^ PA.TRIAL_SEED_K
        try:
            g = _arm_game(cont, boot)
            ap = _apply_arm(E, g, arm, int(cont["target"]), pays, tier_derived)
            if not ap["ok"]:
                out.append(float("nan"))
                continue
            res = PA._preview(E, g, LEARNER_SEAT, int(cont["target"]), 1, False)
            out.append(float(PA._survivors_of(res, 0)))
        except BaseException:  # noqa: BLE001
            out.append(float("nan"))
    return out


def _realistic_arm(E_: Any, cont: Dict[str, Any], pays: Dict[str, Any], arm: str,
                   boot: int, tier_derived: int, n_seed: int) -> Dict[str, Any]:
    """训练管线口径：回合起点注入 -> 该座位照常 bot 行动 -> 用战斗前战团重播种。"""
    try:
        g = _arm_game(cont, int(cont["seed"]))
        ap = _apply_arm(E_, g, arm, int(cont["target"]), pays, tier_derived)
        if not ap["ok"]:
            return {"ok": False, "reason": ap.get("reason")}
        tgt = int(cont["target"])
        after = None
        guard = 0
        while not g.is_over() and after is None and guard < 64:
            acted = False
            for p in range(1, N_PLAYERS):
                if g.is_over() or after is not None:
                    break
                if not g.needs_action(p):
                    continue
                acted = True
                guard += 1
                g.bot_play(p)
                if p == tgt:
                    after = g.player_json(tgt)
                    break
            if not acted:
                break
        if after is None:
            return {"ok": False, "reason": "target_no_turn"}
        gb = PA._battle_game(E_, cont["start_state"], cont["learner_json"], tgt, after,
                             boot_seed=boot)
        r = PA._trials(PA._preview(E_, gb, LEARNER_SEAT, tgt, int(n_seed), True))
        return {"ok": True, "loss": PA._loss_seq(r["winner"]),
                "win": PA._win_seq(r["winner"]),
                "dmg_taken": PA._mean(r["dmg_taken"]),
                "dmg_dealt": PA._mean(r["dmg_dealt"]),
                "dmg_taken_seq": r["dmg_taken"]}
    except BaseException as exc:  # noqa: BLE001
        return {"ok": False, "reason": repr(exc)[:120]}


def _frame_key(fr: Dict[str, Any]) -> str:
    return f"{fr['file']}#{int(fr['idx'])}"


def _container_indexes(fr: Dict[str, Any], n: int, k: int) -> List[int]:
    """确定性、与 worker 数无关的容器抽样（blake2b of frame key + salt）。

    为什么不用 ``i % len(cands)``：frame 顺序与容器下标会形成周期相关，导致
    「frame ↔ 容器(学习者/对手强度)」配对随 stride 变化，Δ 估计可漂移数 pp。
    这里用帧身份哈希，保证可复现且与分片无关；``K`` 个容器再按帧做 cluster bootstrap。
    """
    import hashlib
    if n <= 0:
        return []
    out: List[int] = []
    for salt in range(max(1, int(k))):
        h = hashlib.blake2b(f"{_frame_key(fr)}|{salt}".encode("utf-8"),
                            digest_size=8).digest()
        out.append(int.from_bytes(h, "big") % int(n))
    return out


def _frame_worker(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    golden2base = PA._golden_to_base_map()
    n_seed = int(payload["battle_seeds"])
    n_surv = int(payload["survivor_seeds"])
    n_cont = int(payload.get("containers", 1))
    arms = tuple(payload.get("arms") or ARMS)
    snaps_by_turn: Dict[int, List[Dict[str, Any]]] = {}
    for s in PA._jsonl_gz_read(os.path.join(ROOT, "runs", "audit", "snapshots.jsonl.gz")):
        snaps_by_turn.setdefault(int(s["t_choice"]), []).append(s)
    turns_all = sorted(snaps_by_turn)
    out: List[Dict[str, Any]] = []
    for fr in payload["frames"]:
        t = int(fr["turn"])
        cands = snaps_by_turn.get(t) or []
        if not cands and turns_all:
            near = min(turns_all, key=lambda k: abs(k - t))
            cands = snaps_by_turn.get(near) or []
        if not cands:
            out.append({"ok": False, "reason": "no_container", "file": fr["file"],
                        "idx": fr["idx"]})
            continue
        pj = fr["player"]
        pays = _frame_payloads(pj, t, golden2base)
        pays["_frame_json"] = json.dumps(pj)
        tier_derived = PA._tier_of(t)
        cidx = _container_indexes(fr, len(cands), n_cont)
        for ci in cidx:
            cont = dict(cands[ci])
            boot = int(cont["seed"]) ^ (0x51ED + ci * 7919)
            row = _one_container(fr, t, cont, ci, pj, pays, boot, tier_derived,
                                 arms, n_seed, n_surv)
            out.append(row)
    return out


def _one_container(fr: Dict[str, Any], t: int, cont: Dict[str, Any], ci: int,
                   pj: Dict[str, Any], pays: Dict[str, Any], boot: int,
                   tier_derived: int, arms: Sequence[str], n_seed: int,
                   n_surv: int) -> Dict[str, Any]:
        row: Dict[str, Any] = {"ok": True, "frame": _frame_key(fr), "cont_i": int(ci),
                               "seed": int(cont["seed"]),
                               "file": fr["file"], "idx": int(fr["idx"]),
                               "turn": t, "target": int(cont["target"]),
                               "board_str": PA._board_strength(pj),
                               "hand_n": len(pj.get("hand") or []),
                               "golden_n": sum(1 for m in (pj.get("board") or [])
                                               if m.get("golden")),
                               "kw_bits": sum(int(m.get("kw") or 0).bit_count()
                                              + int(m.get("bonus_kw") or 0).bit_count()
                                              for m in (pj.get("board") or [])),
                               "tier": int(pj.get("tier") or 0),
                               "combat": {}, "pipeline": {}}
        for arm in arms:
            row["combat"][arm] = _preview_arm(arm, cont, pays, boot, tier_derived, n_seed)
            if row["combat"][arm].get("ok"):
                sv = _surv_arm(arm, cont, pays, boot, tier_derived, n_surv)
                row["combat"][arm]["survivors"] = PA._mean([x for x in sv
                                                            if np.isfinite(x)])
                row["combat"][arm]["surv_seq"] = [round(x, 3) for x in sv]
        for arm in PIPELINE_ARMS:
            row["pipeline"][arm] = _realistic_arm(E, cont, pays, arm, boot,
                                                  tier_derived, n_seed)
        return row


# ────────────────────────── 汇总 ──────────────────────────


def _cluster_bootstrap(by_frame: Dict[str, List[float]], n_boot: int = 4000,
                       alpha: float = 0.05, seed: int = 20261031) -> Dict[str, float]:
    """按**帧**做 cluster bootstrap（同帧多个容器不独立）。"""
    keys = sorted(by_frame)
    if not keys:
        return {"n": 0, "mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    allv = [v for k in keys for v in by_frame[k]]
    rng = np.random.default_rng(int(seed))
    means = np.empty(int(n_boot), dtype=np.float64)
    for i in range(int(n_boot)):
        pick = rng.integers(0, len(keys), size=len(keys))
        s = 0.0
        c = 0
        for j in pick:
            vals = by_frame[keys[int(j)]]
            s += float(sum(vals))
            c += len(vals)
        means[i] = s / max(1, c)
    return {"n": int(len(keys)), "pairs": int(len(allv)),
            "mean": float(np.mean(allv)),
            "ci_low": float(np.percentile(means, 100 * alpha / 2)),
            "ci_high": float(np.percentile(means, 100 * (1 - alpha / 2)))}


def _pairs(rows: List[Dict[str, Any]], mode: str) -> Dict[str, Dict[str, Any]]:
    def seq(arm: str, key: str) -> List[float]:
        return [float(r[mode][arm][key]) for r in rows
                if r[mode].get(arm, {}).get("ok") and r[mode][arm].get(key) is not None]

    def paired(a: str, b: str, key: str) -> List[float]:
        out = []
        for r in rows:
            x, y = r[mode].get(a, {}), r[mode].get(b, {})
            if x.get("ok") and y.get("ok") and x.get(key) is not None \
                    and y.get(key) is not None:
                out.append(float(x[key]) - float(y[key]))
        return out

    def paired_by_frame(a: str, b: str, key: str) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = {}
        for r in rows:
            x, y = r[mode].get(a, {}), r[mode].get(b, {})
            if x.get("ok") and y.get("ok") and x.get(key) is not None \
                    and y.get(key) is not None:
                out.setdefault(str(r["frame"]), []).append(float(x[key]) - float(y[key]))
        return out

    res: Dict[str, Any] = {}
    for arm in ARMS:
        if not any(r[mode].get(arm, {}).get("ok") for r in rows):
            continue
        res[arm] = {
            "n": int(sum(1 for r in rows if r[mode].get(arm, {}).get("ok"))),
            "loss": round(float(np.mean(seq(arm, "loss"))), 4) if seq(arm, "loss") else None,
            "dmg_taken": (round(float(np.mean(seq(arm, "dmg_taken"))), 4)
                          if seq(arm, "dmg_taken") else None),
            "survivors": (round(float(np.mean(seq(arm, "survivors"))), 4)
                          if seq(arm, "survivors") else None),
        }
    pairs = (("B1", "B0"), ("B2", "B1"), ("B2r", "B1"), ("B2", "B2r"),
             ("B2+", "B2"), ("B2++", "B2+"), ("B2++", "FULL"), ("FULL", "B0"),
             ("B2", "B0"), ("B2r", "B0"), ("B2+", "B0"), ("B2++", "B0"))
    res["deltas"] = {}
    for a, b in pairs:
        dl = paired(a, b, "loss")
        dt = paired(a, b, "dmg_taken")
        if not dl:
            continue
        bl = _cluster_bootstrap(paired_by_frame(a, b, "loss"), seed=31)
        bt = _cluster_bootstrap(paired_by_frame(a, b, "dmg_taken"), seed=32)
        d = {
            "n_frames": int(bl["n"]), "n_pairs": int(len(dl)),
            "delta_loss_pp": round(100 * bl["mean"], 2),
            "delta_loss_ci_pp": [round(100 * bl["ci_low"], 2),
                                 round(100 * bl["ci_high"], 2)],
            "delta_dmg_taken": (round(bt["mean"], 3) if dt else None),
            "delta_dmg_taken_ci": ([round(bt["ci_low"], 3), round(bt["ci_high"], 3)]
                                   if dt else None),
            "sign_p_loss": round(PA._sign_test_p(dl), 6),
        }
        bsv = _cluster_bootstrap(paired_by_frame(a, b, "survivors"), seed=33)
        if bsv["n"]:
            d["delta_survivors"] = round(bsv["mean"], 3)
            d["delta_survivors_ci"] = [round(bsv["ci_low"], 3), round(bsv["ci_high"], 3)]
        d["interpretation"] = f"{a} - {b}"
        res["deltas"][f"{a}-{b}"] = d
    return res


def _per_turn(rows: List[Dict[str, Any]], mode: str, a: str, b: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for r in rows:
        if not (r[mode].get(a, {}).get("ok") and r[mode].get(b, {}).get("ok")):
            continue
        t = str(int(r["turn"]))
        d = out.setdefault(t, [])
        d.append(float(r[mode][a]["loss"]) - float(r[mode][b]["loss"]))
    return {t: {"n": len(v), "delta_loss_pp": round(100 * float(np.mean(v)), 2)}
            for t, v in sorted(out.items(), key=lambda kv: int(kv[0]))}


# ────────────────────────── 开销 / 数据侧 ──────────────────────────


def stage_overhead(pool_path: str, reps: int = 40) -> Dict[str, Any]:
    """单次座位注入的墙钟开销（board / hand / full）+ 准完整库统计。"""
    import random as _random

    from hsbg.az.train.human_board_pool import load_pool
    from hsbg.az.train.human_obs_full import inject_quasi_state

    pool = load_pool(pool_path)
    if pool is None:
        return {"available": False}
    g = E.Game(seed=5)
    for _ in range(8):
        p = next(i for i in range(8) if g.needs_action(i))
        g.bot_play(int(p))
    pay = pool.sample_payload(7, _random.Random(1), "auto")
    out: Dict[str, Any] = {"available": True, "pool": pool.stats(),
                           "payload_rows": int(pool.payload_kept)}
    for fid in ("board", "hand", "full"):
        t0 = time.perf_counter()
        for _ in range(int(reps)):
            inject_quasi_state(g, 1, pay, fid, reset_ended=True)
        out[f"ms_per_inject_{fid}"] = round((time.perf_counter() - t0) / reps * 1000, 4)
    # 实际训练管线：3 局 × 全 turn × 2 席，测 apply 率 / 池守恒 / hand 覆盖
    from hsbg.az.train.human_board_pool import HumanBoardStats, inject_turn
    agg: Dict[str, Any] = {}
    for fid in ("board", "hand", "full"):
        st = HumanBoardStats()
        rng = _random.Random(20261031)
        t0 = time.perf_counter()
        turns_played = 0
        for gi in range(3):
            gg = E.Game(seed=910000 + gi)
            for _ in range(8):
                p = next((i for i in range(8) if gg.needs_action(i)), None)
                if p is None:
                    break
                gg.bot_play(int(p))
            last_turn = int(gg.turn)
            while not gg.is_over() and turns_played < 200:
                if int(gg.turn) != last_turn:
                    last_turn = int(gg.turn)
                    inject_turn(gg, pool, last_turn, seats_count=2, p=1.0, rng=rng,
                                stats=st, fidelity=fid, set_tier=True)
                acted = False
                for p in range(8):
                    if gg.is_over():
                        break
                    if gg.needs_action(p):
                        gg.bot_play(p)
                        acted = True
                if not acted:
                    break
            turns_played += int(gg.turn)
        agg[fid] = {
            "attempt": int(st.attempt), "applied": int(st.applied),
            "rejected": int(st.rejected), "hand_applied": int(st.hand_applied),
            "counters_applied": int(st.counters_applied),
            "payload_missing": int(st.payload_missing),
            "pool_unbalanced": int(st.pool_unbalanced),
            "rejected_by_reason": dict(st.rejected_by_reason),
            "seconds": round(time.perf_counter() - t0, 2),
        }
    out["pipeline_3games"] = agg
    return out


# ────────────────────────── 主入口 ──────────────────────────


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="B0/B1/B2 保真度配对审计（CPU）")
    ap.add_argument("--mirror-snaps", default=PA.DEFAULT_MIRROR_SNAPS)
    ap.add_argument("--library", default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--t-lo", type=int, default=6)
    ap.add_argument("--t-hi", type=int, default=15)
    ap.add_argument("--frames", type=int, default=460, help="最多用多少帧（0=全部）")
    ap.add_argument("--battle-seeds", type=int, default=64)
    ap.add_argument("--survivor-seeds", type=int, default=12)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--containers", type=int, default=3,
                    help="每帧抽几个同 turn 容器（帧内平均，按帧 cluster bootstrap）")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args(argv)
    if args.smoke:
        args.frames = 24
        args.battle_seeds = 8
        args.survivor_seeds = 4
        args.workers = min(4, int(args.workers))
        args.out = "runs/audit_smoke/fidelity_injection.json"
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    t_all = time.time()
    print(f"[env] hsbg_engine {E.version()}  frames={args.frames}  workers={args.workers}")
    frames = PA.load_trusted_frames(os.path.join(ROOT, args.mirror_snaps),
                                    int(args.t_lo), int(args.t_hi))
    if args.frames and len(frames) > int(args.frames):
        step = max(1, len(frames) // int(args.frames))
        frames = frames[::step][: int(args.frames)]
    print(f"[fid] 可信完整快照帧 {len(frames)}")
    n_workers = max(1, int(args.workers))
    chunks = [frames[i::n_workers] for i in range(n_workers)]
    payloads = [{"frames": c, "battle_seeds": int(args.battle_seeds),
                 "survivor_seeds": int(args.survivor_seeds), "arms": list(ARMS),
                 "containers": int(args.containers)}
                for c in chunks if c]
    t0 = time.time()
    rows: List[Dict[str, Any]] = []
    if len(payloads) <= 1:
        for p in payloads:
            rows.extend(_frame_worker(p))
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=len(payloads), mp_context=ctx) as ex:
            for rr in ex.map(_frame_worker, payloads):
                rows.extend(rr)
    rows = [r for r in rows if r.get("ok")]
    rows.sort(key=lambda r: (int(r["turn"]), str(r["file"]), int(r["idx"])))
    # 逐 trial 序列只用于算均值/CI，落盘前删掉（JSON 从 ~30MB 降到 ~5MB）。
    for r in rows:
        for mode in ("combat", "pipeline"):
            for arm in (r.get(mode) or {}).values():
                if isinstance(arm, dict):
                    for k in ("win_seq", "dmg_taken_seq", "dmg_dealt_seq", "surv_seq"):
                        arm.pop(k, None)
    sec_run = time.time() - t0
    print(f"[fid] {len(rows)} 帧完成，{sec_run:.1f}s")

    result: Dict[str, Any] = {
        "schema": "hsbg.fidelity_injection_audit", "schema_version": 1,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "repo": ROOT,
        "frames": len({str(r["frame"]) for r in rows}),
        "frame_container_pairs": len(rows), "battle_seeds": int(args.battle_seeds),
        "survivor_seeds": int(args.survivor_seeds),
        "frame_selection": {
            "source": args.mirror_snaps, "turns": [int(args.t_lo), int(args.t_hi)],
            "sampled": len(frames), "note": "等间隔抽样到 --frames 上限",
            "containers_per_frame": int(args.containers),
            "container_choice": "blake2b(frame_key|salt) % len(same-turn containers)",
            "ci": "按帧 cluster bootstrap（4000 次）"},
        "arms": {
            "B0": "inject_board（现状；金色 _G 卡 id 保留）",
            "B1": "inject_quasi_state(fidelity=hand)：B0 board + 手牌",
            "B2": "fidelity=full：完整帧（kw/金身/圣盾/attachments/counter/gems/tier/gold）",
            "B2r": "fidelity=full 但 gold 保留当前局（真实观测 gold 不可得；训练实际形态）",
            "B2+": "B2 + 玩家级 combat overlay（trinkets/quests/rewards/secrets/effects/"
                   "stats/counters/tier7）",
            "B2++": "B2+ 再 overlay hero/powers（≈ground truth；训练不建议）",
            "FULL": "set_player_from_json 整帧替换（ground truth；仅 combat 口径）",
        },
        "pipeline_arms": list(PIPELINE_ARMS),
        "hidden_state": {
            "board_str_mean": round(float(np.mean([r["board_str"] for r in rows])), 2),
            "hand_n_mean": round(float(np.mean([r["hand_n"] for r in rows])), 3),
            "golden_mean": round(float(np.mean([r["golden_n"] for r in rows])), 3),
            "kw_bits_mean": round(float(np.mean([r["kw_bits"] for r in rows])), 3),
            "frac_frames_hand": round(float(np.mean([1.0 if r["hand_n"] else 0.0
                                                     for r in rows])), 4),
            "frac_frames_golden": round(float(np.mean([1.0 if r["golden_n"] else 0.0
                                                       for r in rows])), 4),
            "frac_frames_kw": round(float(np.mean([1.0 if r["kw_bits"] else 0.0
                                                  for r in rows])), 4),
        },
        "combat": _pairs(rows, "combat"),
        "pipeline": _pairs(rows, "pipeline"),
        "per_turn": {
            "combat_B2_minus_B0": _per_turn(rows, "combat", "B2", "B0"),
            "pipeline_B2_minus_B0": _per_turn(rows, "pipeline", "B2", "B0"),
        },
        "rows": rows,
        "stage_seconds": {"frames": round(sec_run, 2),
                          "total": round(time.time() - t_all, 2)},
    }
    try:
        result["overhead"] = stage_overhead(args.library)
    except BaseException as exc:  # noqa: BLE001
        result["overhead"] = {"available": False, "error": repr(exc)[:200]}

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump(result, open(args.out, "w"), ensure_ascii=False, indent=2)

    # ── 控制台配对表 ──
    def _tab(mode: str) -> None:
        c = result[mode]
        print(f"\n== {mode} ==")
        print(f"{'arm':5s} {'n':>4s} {'loss':>7s} {'dmg_taken':>10s} {'surv':>6s}")
        for arm in ARMS:
            if arm not in c:
                continue
            v = c[arm]
            print(f"{arm:5s} {v['n']:4d} {str(v['loss']):>7s} "
                  f"{str(v['dmg_taken']):>10s} {str(v['survivors']):>6s}")
        print(f"{'pair':10s} {'n_fr':>5s} {'dLoss(pp)':>10s} {'95%CI':>18s} "
              f"{'dDmg':>7s} {'dSurv':>7s}")
        for k, d in c["deltas"].items():
            ci = d["delta_loss_ci_pp"]
            print(f"{k:10s} {d.get('n_frames', 0):>5d} {d['delta_loss_pp']:>10.2f} "
                  f"{'[' + str(ci[0]) + ',' + str(ci[1]) + ']':>18s} "
                  f"{str(d['delta_dmg_taken']):>7s} {str(d.get('delta_survivors')):>7s}")

    _tab("combat")
    _tab("pipeline")
    ov = result.get("overhead") or {}
    if ov.get("available"):
        print(f"\n[overhead] board={ov['ms_per_inject_board']}ms hand="
              f"{ov['ms_per_inject_hand']}ms full={ov['ms_per_inject_full']}ms per seat-inject"
              f"；pipeline apply={ov['pipeline_3games']['full']['applied']}/"
              f"{ov['pipeline_3games']['full']['attempt']}")
    print(f"\n[done] {args.out}  ({time.time() - t_all:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
