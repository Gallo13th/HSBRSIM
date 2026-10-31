#!/usr/bin/env python3
"""离线支持覆盖审计（docs/EXPERT_INJECTION_THEORY.md §3）。

回答一个问题：**后期专家成长状态/动作，在 s15 当前策略的占用测度与动作支持里的
比例是多少？** 全程离线（CPU 优先；不训练、不占训练卡）。

四个指标（状态类按整局 cluster bootstrap 给 95% CI）：

1. **状态覆盖** ``C_state``：专家 t→t+3 成长窗口的起点状态，在 learner rollout 状态的
   kNN 密度阈值 η（learner holdout 的 95 分位）之内 = 覆盖；``OOD = 1 - C_state``；
2. **专家动作 KL**：在**可比状态**（learner 题池，带同一份人类参考解）上算
   ``KL(ref || π_θ)``、``NLL`` 与动作支持覆盖 ``C_act``（参考质量落在
   ``π_θ(a) > 1e-3`` 的动作上的比例）；
3. **三回合成长路径可行性**：按 ``Π π_θ(a*|s)`` 连乘（log10 报告），``a*`` 是参考解里
   的成长动作（buy/play 里权重最高者），另报 ``Π π_θ(buy∪play)``（策略自行取得成长
   动作的概率）；
4. **判据**（预注册）：``C_state < --coverage-threshold``（默认 0.90）或
   ``p3 < 1e-6`` -> 判定「极端条件」，下一步 DAgger/搜索标签；否则先修参考解。

数据来源：
- 专家：``data/real_library/obs/observations/*.jsonl`` 全帧解析（``parse_observation``，
  EOT 帧优先、否则同回合取最大强度帧），每局每回合一个状态；t→t+3 强度增量 top
  分位 = 成长窗口；
- learner：``--learner-pool``（s15 当前权重的后期题池；本仓库由
  ``scripts/build_board_problems.py --checkpoint runs/az_entity_s15/model.pt
  --focus-turns 10-15 --late-ref-policy fixed`` 生成）。

局限性（必须和数字一起读，见报告 ``limitations``）：

- 专家观测**没有 gold/shop/隐藏量**，与 learner 状态只能在**共有的可见子空间**
  （turn/tier/强度/身材/金身/关键词/圣盾/卡 tier 构成）里比；kNN 是表示空间的近邻
  质量，不是全状态密度（EXPERIMENT §7.3）；
- 专家帧上**无法执行动作**（shop 不可得 → 买牌动作映射不到槽位），所以动作 KL 只能在
  「可比状态」（learner 题池 + 人类参考解）上算；三回合可行性是**固定状态序列上的
  动作似然连乘**，不是含转移概率的真实路径概率（§3.4）。
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from hsbg.env import obs_std as O  # noqa: E402
from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS  # noqa: E402
from hsbg.az.train.board_problems import (  # noqa: E402
    DEFAULT_BC_SAMPLES,
    DEFAULT_FIRESTONE_ACTIONS,
    LATE_TURN_MIN,
    REF_CARD_KINDS,
    LateRefConfig,
    _card_tier_table,
    board_card_ids,
    board_strength_from_features,
    build_human_buy_table,
    build_reference_table,
    decode_obs,
    gold_from_features,
    match_reference_actions,
    ref_action_kind,
    shop_phase_from_features,
    tier_from_features,
    turn_from_features,
)
from hsbg.az.train.bc_aux import load_bc_card_table  # noqa: E402

DEFAULT_OBS_DIR = os.path.join(ROOT, "data", "real_library", "obs",
                               "observations")
DEFAULT_POOL = os.path.join(ROOT, "runs", "support_audit",
                            "problems_s15_late.jsonl")
DEFAULT_OUT = os.path.join(ROOT, "runs", "support_audit", "report.json")

#: 共享状态向量（专家与 learner 都能算的**可见子空间**，13 维）。
VECTOR_NAMES: Tuple[str, ...] = (
    "turn", "tier", "log_strength", "board_len", "hand_n", "golden_n",
    "kw_n", "shield_n", "mean_card_tier", "max_card_tier", "n_tier_ge3",
    "n_tier_ge5", "n_dupes")


# ══════════════════════════════════════════════════════════════════════════
# 1. 专家状态（真实 10k+ 观测）
# ══════════════════════════════════════════════════════════════════════════
def load_expert_states(obs_dir: str) -> Tuple[Dict[Tuple[str, int], Dict[str, Any]],
                                              Dict[str, Any]]:
    """解析观测目录 -> ``{(game_id, turn): state}``（EOT 帧优先、否则最大强度帧）。"""
    from hsbg.az.train.human_obs_full import (EOT_STAGE, load_card_meta,
                                              parse_observation)
    meta = load_card_meta()
    files = sorted(glob.glob(os.path.join(obs_dir, "*.jsonl")))
    counts = {"files": len(files), "frames": 0, "parsed": 0,
              "dropped": Counter()}
    best: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                counts["frames"] += 1
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    counts["dropped"]["bad_json"] += 1
                    continue
                payload, reasons = parse_observation(row, meta, eot_only=False)
                if payload is None:
                    counts["dropped"][str((reasons or ["unknown"])[-1])] += 1
                    continue
                counts["parsed"] += 1
                gid = str(payload.get("game_id") or row.get("game_id") or "")
                turn = int(payload.get("turn") or 0)
                if not gid or turn <= 0:
                    counts["dropped"]["bad_key"] += 1
                    continue
                board = payload.get("board") or []
                strength = int(sum(int(b["atk"]) + int(b["hp"]) for b in board))
                eot = str(row.get("stage") or "") == EOT_STAGE
                cand = {
                    "game_id": gid, "turn": turn, "eot": bool(eot),
                    "strength": int(strength), "board": board,
                    "hand_n": int(len(payload.get("hand") or [])),
                    "hand_available": bool(payload.get("hand_available")),
                    "tier": (None if payload.get("tier") is None
                             else int(payload["tier"])),
                }
                key = (gid, turn)
                prev = best.get(key)
                if prev is None or (cand["eot"] and not prev["eot"]) or (
                        cand["eot"] == prev["eot"]
                        and cand["strength"] > prev["strength"]):
                    best[key] = cand
    counts["dropped"] = dict(counts["dropped"].most_common(8))
    counts["game_turns"] = len(best)
    counts["games"] = len({k[0] for k in best})
    counts["eot_share"] = (float(sum(1 for v in best.values() if v["eot"]))
                           / max(1, len(best)))
    return best, dict(counts)


def expert_windows(states: Dict[Tuple[str, int], Dict[str, Any]], *,
                   turn_min: int = LATE_TURN_MIN, horizon: int = 3
                   ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """所有 t→t+horizon 窗口 + 后期窗口（含 ``delta_log1p``）。"""
    all_w: List[Dict[str, Any]] = []
    for (gid, turn), st in states.items():
        nxt = states.get((gid, turn + int(horizon)))
        if nxt is None:
            continue
        d = float(math.log1p(max(0, nxt["strength"]))
                  - math.log1p(max(0, st["strength"])))
        w = {"game_id": gid, "turn": int(turn),
             "strength_before": int(st["strength"]),
             "strength_after": int(nxt["strength"]),
             "delta_log1p": d,
             "start": st, "end": nxt}
        all_w.append(w)
    late = [w for w in all_w if int(w["turn"]) >= int(turn_min)]
    return all_w, late


def state_vector_expert(st: Dict[str, Any], *, id_to_index: Dict[str, int],
                        tiers: np.ndarray) -> np.ndarray:
    """专家状态 -> 13 维可见子空间向量（与 learner 同口径）。"""
    board = st.get("board") or []
    lens = len(board)
    gtier: List[float] = []
    golden = 0
    kw_n = 0
    shield = 0
    dup = Counter()
    for b in board:
        cid = str(b.get("card_id") or "")
        idx = id_to_index.get(cid)
        gtier.append(float(tiers[idx]) if idx is not None else np.nan)
        golden += int(bool(b.get("golden")))
        kw_n += int(bin(int(b.get("kw") or 0) | int(b.get("bonus_kw") or 0))
                    .count("1"))
        shield += int(int(b.get("shield_max") or 1) > 1)
        dup[cid] += 1
    t = np.asarray(gtier, dtype=np.float64)
    t = t[np.isfinite(t)]
    return np.asarray([
        float(st.get("turn") or 0),
        float(st.get("tier") if st.get("tier") is not None else 0),
        float(math.log1p(max(0, int(st.get("strength") or 0)))),
        float(lens),
        float(st.get("hand_n") or 0),
        float(golden),
        float(kw_n),
        float(shield),
        float(t.mean()) if t.size else 0.0,
        float(t.max()) if t.size else 0.0,
        float((t >= 3).sum()) if t.size else 0.0,
        float((t >= 5).sum()) if t.size else 0.0,
        float(lens - len(dup)),
    ], dtype=np.float64)


# ══════════════════════════════════════════════════════════════════════════
# 2. learner 状态 + 策略概率
# ══════════════════════════════════════════════════════════════════════════
def load_learner_pool(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("obs") and r.get("label"):
                rows.append(r)
    return rows


def state_vector_learner(features: np.ndarray, cards: np.ndarray,
                         tier_tbl: Optional[np.ndarray]) -> np.ndarray:
    """learner 观测 -> 13 维可见子空间向量（与专家同口径）。"""
    f = np.asarray(features, dtype=np.float32).reshape(-1)
    board = f[O.SLICE_BOARD].reshape(O.N_BOARD, O.MINION_F)
    present = board[:, O.MINION_PRESENT] > 0.5
    board_len = int(present.sum())
    golden = float((board[present, O.MINION_GOLDEN] > 0.5).sum())
    kw_n = float((board[present, O.MINION_KEYWORDS] > 0.5).sum())
    shield = float((board[present, O.MINION_SHIELD_HITS] > 0.5).sum())
    hand = f[O.SLICE_HAND].reshape(O.N_HAND, O.ITEM_F)
    hand_n = float((hand[:, O.ITEM_PRESENT] > 0.5).sum())
    ids = [int(c) for c in board_card_ids(cards).tolist()]
    ids = [i for i in ids if i > 0]
    dup = Counter(ids)
    t: List[float] = []
    if tier_tbl is not None:
        t = [float(tier_tbl[i]) for i in ids if 0 <= i < len(tier_tbl)]
    ta = np.asarray(t, dtype=np.float64)
    ta = ta[np.isfinite(ta)]
    return np.asarray([
        float(turn_from_features(f)),
        float(tier_from_features(f)),
        float(math.log1p(max(0, int(board_strength_from_features(f))))),
        float(board_len),
        float(hand_n),
        float(golden),
        float(kw_n),
        float(shield),
        float(ta.mean()) if ta.size else 0.0,
        float(ta.max()) if ta.size else 0.0,
        float((ta >= 3).sum()) if ta.size else 0.0,
        float((ta >= 5).sum()) if ta.size else 0.0,
        float(len(ids) - len(dup)),
    ], dtype=np.float64)


def masked_softmax(logits: np.ndarray, mask: np.ndarray) -> np.ndarray:
    x = np.where(mask, np.asarray(logits, dtype=np.float64), -np.inf)
    mx = x.max(axis=1, keepdims=True)
    e = np.exp(x - mx) * mask
    s = e.sum(axis=1, keepdims=True)
    return e / np.maximum(s, 1e-300)


def score_policy(checkpoint: str, features: np.ndarray, cards: np.ndarray,
                 mask: np.ndarray, *, device: str = "cpu",
                 chunk: int = 512) -> Tuple[np.ndarray, Dict[str, Any]]:
    """s15 权重 -> 每行的 masked 动作概率 ``π``（形状 ``[n, 245]``）。"""
    import torch
    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.ppo import forward_model, split_model_outputs
    model, meta = load_checkpoint(checkpoint, device=device)
    mean = meta.get("norm_mean")
    std = meta.get("norm_std")
    x_all = np.asarray(features, dtype=np.float32)
    if mean is not None:
        x_all = x_all - np.asarray(mean, dtype=np.float32)
    if std is not None:
        x_all = x_all / np.maximum(np.asarray(std, dtype=np.float32), 1e-6)
    out = np.zeros((features.shape[0], mask.shape[1]), dtype=np.float64)
    t0 = time.time()
    with torch.no_grad():
        for start in range(0, features.shape[0], int(chunk)):
            sl = slice(start, start + int(chunk))
            x = torch.from_numpy(np.ascontiguousarray(x_all[sl])).to(device)
            c = torch.from_numpy(np.ascontiguousarray(
                cards[sl].astype(np.int64))).to(device)
            m = torch.from_numpy(np.ascontiguousarray(
                mask[sl].astype(bool))).to(device)
            logits, _rank, _scalar = split_model_outputs(
                forward_model(model, x, c, m))
            out[sl] = logits.float().cpu().numpy()
    pi = masked_softmax(out, mask)
    info = {"checkpoint": str(checkpoint), "arch": str(meta.get("arch")),
            "device": str(device), "norm": bool(mean is not None),
            "seconds": round(time.time() - t0, 1)}
    return pi, info


# ══════════════════════════════════════════════════════════════════════════
# 3. kNN 覆盖 + bootstrap
# ══════════════════════════════════════════════════════════════════════════
def knn_dist(X: np.ndarray, Q: np.ndarray, k: int = 5) -> np.ndarray:
    """``Q`` 每点到 ``X`` 的 k 近邻平均欧氏距离。"""
    if X.size == 0 or Q.size == 0:
        return np.zeros(Q.shape[0], dtype=np.float64)
    out = np.zeros(Q.shape[0], dtype=np.float64)
    kk = max(1, min(int(k), X.shape[0]))
    step = 256
    for start in range(0, Q.shape[0], step):
        q = Q[start:start + step]
        d2 = ((q[:, None, :] - X[None, :, :]) ** 2).sum(axis=-1)
        idx = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
        out[start:start + step] = np.sqrt(
            np.take_along_axis(d2, idx, axis=1)).mean(axis=1)
    return out


def _cluster_bootstrap_coverage(d_hold: np.ndarray, hold_games: np.ndarray,
                                d_exp: np.ndarray, exp_games: np.ndarray, *,
                                q: float = 95.0, reps: int = 1000,
                                seed: int = 7) -> Dict[str, Any]:
    """整局 cluster bootstrap：重采样 holdout（定 η）与专家局（算覆盖）。"""
    rng = np.random.default_rng(int(seed))
    hold_ids = np.asarray(sorted(set(hold_games.tolist())))
    exp_ids = np.asarray(sorted(set(exp_games.tolist())))
    if hold_ids.size == 0 or exp_ids.size == 0:
        return {"coverage": float("nan"), "ci95": [None, None], "reps": 0}
    eta = float(np.percentile(d_hold, q))
    cov = float(np.mean(d_exp <= eta))
    vals = []
    for _ in range(int(reps)):
        hb = rng.choice(hold_ids, size=hold_ids.size, replace=True)
        eb = rng.choice(exp_ids, size=exp_ids.size, replace=True)
        dh = np.concatenate([d_hold[hold_games == g] for g in hb])
        de = np.concatenate([d_exp[exp_games == g] for g in eb])
        e = float(np.percentile(dh, q)) if dh.size else eta
        vals.append(float(np.mean(de <= e)))
    vals_arr = np.asarray(vals, dtype=np.float64)
    return {
        "coverage": cov, "eta": eta, "ood": 1.0 - cov,
        "ci95": [float(np.percentile(vals_arr, 2.5)),
                 float(np.percentile(vals_arr, 97.5))],
        "median_log10_p": float(np.log10(max(cov, 1e-12))),
        "bootstrap_mean": float(vals_arr.mean()), "reps": int(reps),
        "n_holdout_games": int(hold_ids.size),
        "n_expert_games": int(exp_ids.size),
    }


# ══════════════════════════════════════════════════════════════════════════
# 4. 动作 KL / 支持覆盖
# ══════════════════════════════════════════════════════════════════════════
def _ref_arrays(ref: Dict[str, Any]) -> Tuple[List[int], List[float]]:
    a = [int(x) for x in (ref.get("actions") or [])]
    w = [float(x) for x in (ref.get("weights") or [])]
    s = float(sum(w))
    if s <= 0:
        return a, [0.0] * len(a)
    return a, [x / s for x in w]


def action_stats(pi: np.ndarray, refs: Sequence[Dict[str, Any]], *,
                 eta: float = 1e-3) -> Dict[str, Any]:
    """``KL(ref||π)`` / ``NLL(ref top1)`` / 动作支持覆盖 ``C_act``。"""
    kls: List[float] = []
    nlls: List[float] = []
    cacts: List[float] = []
    zero_rows = 0
    missing = 0
    top1_kinds: Counter = Counter()
    for r, p in zip(refs, np.asarray(pi, dtype=np.float64)):
        if not bool(r.get("matched")):
            missing += 1
            continue
        acts, wts = _ref_arrays(r)
        if not acts:
            missing += 1
            continue
        kl = 0.0
        has_zero = False
        ca = 0.0
        for a, w in zip(acts, wts):
            pa = float(p[int(a)])
            if pa <= 0.0:
                has_zero = True
                kl = float("inf")
            elif math.isfinite(kl):
                kl += w * (math.log(w) - math.log(pa))
            if pa > float(eta):
                ca += w
        kls.append(kl)
        cacts.append(float(ca))
        zero_rows += int(has_zero)
        top1_kinds[ref_action_kind(acts[0])] += 1
        ptop = float(p[int(acts[0])])
        nlls.append(float(-math.log(max(ptop, 1e-12))))
    fin = [x for x in kls if math.isfinite(x)]
    return {
        "n": int(len(kls)), "missing": int(missing),
        "kl_median": float(np.percentile(fin, 50)) if fin else None,
        "kl_p90": float(np.percentile(fin, 90)) if fin else None,
        "kl_mean": float(np.mean(fin)) if fin else None,
        "kl_inf_rows": int(sum(1 for x in kls if not math.isfinite(x))),
        "zero_mass_rows": int(zero_rows),
        "nll_median": float(np.percentile(nlls, 50)) if nlls else None,
        "nll_p90": float(np.percentile(nlls, 90)) if nlls else None,
        "c_act_mean": float(np.mean(cacts)) if cacts else None,
        "c_act_p10": float(np.percentile(cacts, 10)) if cacts else None,
        "eta": float(eta),
        "top1_kind": dict(top1_kinds.most_common()),
    }


# ══════════════════════════════════════════════════════════════════════════
# 5. 三回合成长路径可行性
# ══════════════════════════════════════════════════════════════════════════
def _growth_action(ref: Dict[str, Any]) -> Tuple[Optional[int], bool]:
    """参考解里的成长动作（buy/play 里权重最高者）；没有则退回 top-1。"""
    acts, wts = _ref_arrays(ref)
    best = None
    best_w = -1.0
    for a, w in zip(acts, wts):
        if ref_action_kind(a) in ("buy", "play") and w > best_w:
            best, best_w = int(a), float(w)
    if best is not None:
        return best, True
    return ((int(acts[0]), False) if acts else (None, False))


def feasibility(pool_rows: Sequence[Dict[str, Any]], pis: np.ndarray,
                masks: np.ndarray, refs_cur: Sequence[Dict[str, Any]],
                refs_fix: Sequence[Dict[str, Any]], *,
                horizon: int = 3) -> Dict[str, Any]:
    """同一局 t..t+2 三个回合起点的 ``Π π(a*|s)``（固定状态序列上的动作似然）。"""
    by_game: Dict[Any, Dict[int, int]] = defaultdict(dict)
    for i, r in enumerate(pool_rows):
        if int(r.get("decision_idx") or 0) != 0:
            continue
        gid = r.get("game_seed", r.get("source_group"))
        by_game[gid][int(r.get("turn") or 0)] = int(i)
    win_rows: List[Tuple[Any, List[int]]] = []
    for gid, turns in by_game.items():
        for t in sorted(turns):
            idx = [turns.get(t + k) for k in range(int(horizon))]
            if all(x is not None for x in idx):
                win_rows.append((gid, [int(x) for x in idx]))
    out: Dict[str, Any] = {"windows": int(len(win_rows)), "horizon": int(horizon)}
    if not win_rows:
        return out
    logs: Dict[str, List[float]] = {"p3_fixed": [], "p3_current": [],
                                    "p3_growth": []}
    no_growth = 0
    skipped_unmatched = 0
    for _gid, idx in win_rows:
        if not all(bool(refs_fix[i].get("matched")) for i in idx):
            # 严格参考解只覆盖 part of states：三回合里缺任一回合就无法定义 p3_fixed
            skipped_unmatched += 1
            continue
        l_fixed = 0.0
        l_cur = 0.0
        l_growth = 0.0
        for i in idx:
            p = np.asarray(pis[i], dtype=np.float64)
            m = np.asarray(masks[i], dtype=bool)
            a_f, has_growth = _growth_action(refs_fix[i])
            a_c, _ = _growth_action(refs_cur[i])
            if not has_growth:
                no_growth += 1
            l_fixed += math.log(max(float(p[a_f]) if a_f is not None else 0.0, 1e-12))
            l_cur += math.log(max(float(p[a_c]) if a_c is not None else 0.0, 1e-12))
            growth_mass = float(sum(
                float(p[a]) for a in np.flatnonzero(m)
                if ref_action_kind(int(a)) in ("buy", "play")))
            l_growth += math.log(max(growth_mass, 1e-12))
        logs["p3_fixed"].append(l_fixed / math.log(10.0))
        logs["p3_current"].append(l_cur / math.log(10.0))
        logs["p3_growth"].append(l_growth / math.log(10.0))
    for key, vals in logs.items():
        v = np.asarray(vals, dtype=np.float64)
        out[key] = {
            "n": int(v.size),
            "log10_median": float(np.percentile(v, 50)),
            "log10_p10": float(np.percentile(v, 10)),
            "log10_p90": float(np.percentile(v, 90)),
            "median": float(10.0 ** float(np.percentile(v, 50))),
            "lt_1e_6": float(np.mean(v < -6.0)),
            "lt_1e_9": float(np.mean(v < -9.0)),
        }
    out["no_growth_decisions"] = int(no_growth)
    out["skipped_unmatched_fixed"] = int(skipped_unmatched)
    return out


# ══════════════════════════════════════════════════════════════════════════
# 6. 主流程
# ══════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="离线支持覆盖审计（Astra 理论 §3）")
    ap.add_argument("--learner-pool", default=DEFAULT_POOL,
                    help="s15 当前权重的后期题池（jsonl）")
    ap.add_argument("--checkpoint", default="runs/az_entity_s15/model.pt")
    ap.add_argument("--device", default="cpu", help="策略打分设备（默认 cpu）")
    ap.add_argument("--observations", default=DEFAULT_OBS_DIR,
                    help="真实 10k+ 观测目录（*.jsonl）")
    ap.add_argument("--turn-min", type=int, default=LATE_TURN_MIN)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--growth-quantile", type=float, default=0.5,
                    help="成长窗口 = 后期窗口里 Δ 的 top 分位（默认 top 50%）")
    ap.add_argument("--growth-quantile-scope", default="turn",
                    choices=["turn", "pool"],
                    help="分位在**同一 turn 内**算（默认，保证 t13–15 也有样本）"
                         "还是在整个后期池算（旧的全局口径）")
    ap.add_argument("--knn-k", type=int, default=5)
    ap.add_argument("--holdout-frac", type=float, default=0.2,
                    help="learner 局的分割比例（定 η 用 holdout）")
    ap.add_argument("--eta-percentile", type=float, default=95.0,
                    help="learner holdout 的 kNN 距离分位 = 密度阈值 η")
    ap.add_argument("--coverage-threshold", type=float, default=0.90,
                    help="判据：C_state 低于它 -> 极端条件（默认 0.90）")
    ap.add_argument("--p3-threshold", type=float, default=1e-6,
                    help="判据：p3 低于它 -> 极端条件（默认 1e-6）")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ref-samples", default=DEFAULT_BC_SAMPLES)
    ap.add_argument("--ref-buy-table", default=DEFAULT_FIRESTONE_ACTIONS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--md", default="")
    args = ap.parse_args()

    t0 = time.time()
    for path, name in ((args.learner_pool, "--learner-pool"),
                       (args.checkpoint, "--checkpoint")):
        if not os.path.exists(path):
            print(f"[error] {name} 不存在：{path}", file=sys.stderr)
            return 2
    if not os.path.isdir(args.observations):
        print(f"[error] --observations 不是目录：{args.observations}",
              file=sys.stderr)
        return 2
    gq = float(args.growth_quantile)
    if not (0.0 < gq <= 1.0):
        print(f"[error] --growth-quantile 必须 (0,1]，得到 {gq}", file=sys.stderr)
        return 2

    # ── (1) 专家状态 / 成长窗口 ──────────────────────────────────────────
    print("[audit] 解析专家观测 ...", flush=True)
    states, st_counts = load_expert_states(str(args.observations))
    all_w, late_w = expert_windows(states, turn_min=int(args.turn_min),
                                   horizon=int(args.horizon))
    deltas = np.asarray([w["delta_log1p"] for w in late_w], dtype=np.float64)
    tau = float(np.quantile(deltas, 1.0 - gq)) if deltas.size else float("nan")
    tau_by_turn: Dict[str, float] = {}
    selected: List[Dict[str, Any]] = []
    for w in late_w:
        t = int(w["turn"])
        if str(args.growth_quantile_scope) == "turn":
            vals = [x["delta_log1p"] for x in late_w if int(x["turn"]) == t]
            tau_t = (float(np.quantile(vals, 1.0 - gq)) if len(vals) >= 4
                     else tau)
        else:
            tau_t = tau
        tau_by_turn[str(t)] = tau_t
        if float(w["delta_log1p"]) >= tau_t - 1e-12:
            selected.append(w)
    print(f"[audit] 专家: game_turns={st_counts['game_turns']} "
          f"games={st_counts['games']} windows={len(all_w)} late={len(late_w)} "
          f"selected={len(selected)} tau={tau:.3f}", flush=True)
    if not selected:
        print("[error] 没有专家成长窗口（数据/阈值问题）", file=sys.stderr)
        return 2

    # ── (2) learner 状态 + 策略概率 ──────────────────────────────────────
    print("[audit] 读取 learner 题池 ...", flush=True)
    pool = load_learner_pool(str(args.learner_pool))
    if not pool:
        print("[error] learner 题池为空", file=sys.stderr)
        return 2
    table = load_bc_card_table()
    tier_tbl = _card_tier_table()
    feats = np.zeros((len(pool), OBS_FLOATS), dtype=np.float32)
    cards = np.zeros((len(pool), OBS_CARDS), dtype=np.int32)
    masks = np.zeros((len(pool), N_ACTIONS), dtype=bool)
    vec_learner = np.zeros((len(pool), len(VECTOR_NAMES)), dtype=np.float64)
    game_ids = np.zeros(len(pool), dtype=np.int64)
    turns = np.zeros(len(pool), dtype=np.int64)
    for i, r in enumerate(pool):
        f, c, m = decode_obs(r["obs"])
        feats[i], cards[i], masks[i] = f, c, m
        vec_learner[i] = state_vector_learner(f, c, tier_tbl)
        gid = r.get("game_seed")
        if gid is None:
            gid = abs(hash(str(r.get("source_group") or "x"))) % (2 ** 31)
        game_ids[i] = int(gid)
        turns[i] = int(r.get("turn") or 0)
    _id2i = table.id_to_index
    _tiers = np.asarray(table.tier, dtype=np.float64)

    def _vec_win(w: Dict[str, Any]) -> np.ndarray:
        return state_vector_expert(w["start"], id_to_index=_id2i, tiers=_tiers)

    vec_expert = np.stack([_vec_win(w) for w in selected])
    vec_late = (np.stack([_vec_win(w) for w in late_w]) if late_w
                else np.zeros((0, len(VECTOR_NAMES)), dtype=np.float64))
    late_games = np.asarray([w["game_id"] for w in late_w])
    print(f"[audit] learner states={len(pool)} games={len(set(game_ids.tolist()))} "
          f"expert states={vec_expert.shape[0]}", flush=True)

    # ── (3) kNN 覆盖 + cluster bootstrap ────────────────────────────────
    games = np.asarray(sorted(set(game_ids.tolist())), dtype=np.int64)
    rng = np.random.default_rng(int(args.seed))
    rng.shuffle(games)
    n_hold = max(1, int(round(len(games) * float(args.holdout_frac))))
    hold_ids = set(games[:n_hold].tolist())
    fit_mask = np.asarray([g not in hold_ids for g in game_ids])
    hold_mask = ~fit_mask
    X_fit = vec_learner[fit_mask]
    X_hold = vec_learner[hold_mask]
    if X_fit.shape[0] < 10 or X_hold.shape[0] < 5:
        print(f"[error] learner 状态太少（fit={X_fit.shape[0]} "
              f"hold={X_hold.shape[0]}）", file=sys.stderr)
        return 2
    mu = X_fit.mean(axis=0)
    sd = X_fit.std(axis=0)
    sd[sd <= 1e-9] = 1.0
    Xf = (X_fit - mu) / sd
    Xh = (X_hold - mu) / sd
    Xe = (vec_expert - mu) / sd
    d_hold = knn_dist(Xf, Xh, int(args.knn_k))
    d_exp_all = knn_dist(Xf, Xe, int(args.knn_k))
    d_late = (knn_dist(Xf, (vec_late - mu) / sd, int(args.knn_k))
              if vec_late.shape[0] else np.zeros(0, dtype=np.float64))
    exp_games_all = np.asarray([w["game_id"] for w in selected])
    occ = _cluster_bootstrap_coverage(
        d_hold, game_ids[hold_mask], d_exp_all, exp_games_all,
        q=float(args.eta_percentile), reps=int(args.bootstrap),
        seed=int(args.seed))
    eta = occ["eta"]
    by_turn: Dict[str, Any] = {}
    for t in sorted({int(w["turn"]) for w in selected}):
        m = np.asarray([int(w["turn"]) == t for w in selected])
        if bool(m.any()):
            by_turn[str(t)] = {
                "n": int(m.sum()),
                "coverage": float(np.mean(d_exp_all[m] <= eta)),
                "median_distance": float(np.median(d_exp_all[m])),
            }
    # 成长强弱两组（top 25% vs 其余）的 OOD，用来看「越强成长越 OOD」
    dsel = np.asarray([w["delta_log1p"] for w in selected], dtype=np.float64)
    if dsel.size >= 8:
        tau25 = float(np.quantile(dsel, 0.75))
        top = dsel >= tau25 - 1e-12
        occ["by_growth_strength"] = {
            "top25_n": int(top.sum()),
            "top25_coverage": float(np.mean(d_exp_all[top] <= eta)),
            "rest_n": int((~top).sum()),
            "rest_coverage": float(np.mean(d_exp_all[~top] <= eta)) if (~top).any() else None,
        }
    occ["learner"] = {
        "fit_states": int(X_fit.shape[0]), "holdout_states": int(X_hold.shape[0]),
        "games": int(games.size), "holdout_games": int(len(hold_ids)),
        "k": int(args.knn_k), "eta_percentile": float(args.eta_percentile),
        "eta": float(eta),
        "holdout_coverage": float(np.mean(d_hold <= eta)),
        "distance_ratio_median": float(
            np.median(d_exp_all) / max(np.median(d_hold), 1e-9)),
        "feature_names": list(VECTOR_NAMES),
    }
    occ["by_turn"] = by_turn
    # η 灵敏度：即使把阈值放到 learner holdout 的 p99.9，专家状态还在不在里面
    eta_sens: Dict[str, Any] = {}
    for q in (90.0, 95.0, 99.0, 99.9):
        e = float(np.percentile(d_hold, q))
        eta_sens[str(q)] = {
            "eta": e,
            "expert_coverage": float(np.mean(d_exp_all <= e)),
        }
    occ["eta_sensitivity"] = eta_sens
    # 全部后期窗口（不只成长 top 分位）的覆盖，作为选择偏差的对照
    if d_late.size:
        late_cov = _cluster_bootstrap_coverage(
            d_hold, game_ids[hold_mask], d_late, late_games,
            q=float(args.eta_percentile), reps=int(args.bootstrap),
            seed=int(args.seed) + 1)
        by_turn_late: Dict[str, Any] = {}
        for t in sorted({int(w["turn"]) for w in late_w}):
            m = np.asarray([int(w["turn"]) == t for w in late_w])
            if bool(m.any()):
                by_turn_late[str(t)] = {
                    "n": int(m.sum()),
                    "coverage": float(np.mean(d_late[m] <= eta)),
                }
        occ["all_late"] = {"coverage": late_cov["coverage"],
                           "ci95": late_cov["ci95"], "by_turn": by_turn_late}
    # 同 turn 覆盖（最严格口径：只在同一 turn 的 learner 状态里定 η 与近邻）
    same_turn: Dict[str, Any] = {}
    for t in sorted({int(w["turn"]) for w in selected}):
        mfit = fit_mask & (turns == int(t))
        mhold = hold_mask & (turns == int(t))
        mexp = np.asarray([int(w["turn"]) == int(t) for w in selected])
        if int(mfit.sum()) < 10 or int(mhold.sum()) < 5 or not bool(mexp.any()):
            same_turn[str(t)] = {"n": int(mexp.sum()), "coverage": None,
                                 "note": "learner 同 turn 样本不足"}
            continue
        Xf_t = vec_learner[mfit]
        mu_t = Xf_t.mean(axis=0)
        sd_t = Xf_t.std(axis=0)
        sd_t[sd_t <= 1e-9] = 1.0
        Xfz_t = (Xf_t - mu_t) / sd_t
        dh_t = knn_dist(Xfz_t, (vec_learner[mhold] - mu_t) / sd_t,
                        int(args.knn_k))
        de_t = knn_dist(Xfz_t, (vec_expert[mexp] - mu_t) / sd_t,
                        int(args.knn_k))
        eta_t = float(np.percentile(dh_t, float(args.eta_percentile)))
        same_turn[str(t)] = {
            "n": int(mexp.sum()),
            "learner_fit": int(mfit.sum()), "learner_holdout": int(mhold.sum()),
            "eta": eta_t,
            "coverage": float(np.mean(de_t <= eta_t)),
            "min_distance": float(np.min(de_t)),
            "median_distance": float(np.median(de_t)),
        }
    occ["by_turn_same_turn"] = same_turn
    # 同 turn 的强度对比（解释 OOD 的最主要来源）
    strength_by_turn: Dict[str, Any] = {}
    for t in sorted({int(w["turn"]) for w in selected}):
        ex = [int(w["strength_before"]) for w in selected
              if int(w["turn"]) == t]
        le = [float((pool[i].get("state") or {}).get("strength") or 0)
              for i in range(len(pool)) if int(turns[i]) == int(t)]
        strength_by_turn[str(t)] = {
            "expert_p50": float(np.median(ex)) if ex else None,
            "learner_p50": float(np.median(le)) if le else None,
            "ratio_p50": (float(np.median(ex) / max(np.median(le), 1.0))
                          if ex and le else None),
            "n_expert": int(len(ex)), "n_learner": int(len(le)),
        }
    occ["strength_by_turn"] = strength_by_turn
    occ["expert_hand_available"] = float(np.mean(
        [bool(w["start"].get("hand_available")) for w in selected]))

    # ── (4) 策略概率 + 动作 KL / 支持 ────────────────────────────────────
    print("[audit] 打分 s15 策略 ...", flush=True)
    pi, pinfo = score_policy(str(args.checkpoint), feats, cards, masks,
                             device=str(args.device))
    print(f"[audit] policy: {pinfo}", flush=True)
    ref_table = build_reference_table(str(args.ref_samples))
    buy_table = build_human_buy_table(str(args.ref_buy_table), min_freq=0.01)
    fixed_cfg = LateRefConfig(policy="fixed")
    refs_cur: List[Dict[str, Any]] = []
    refs_fix: List[Dict[str, Any]] = []
    for i in range(len(pool)):
        f, c, m = feats[i], cards[i], masks[i]
        refs_cur.append(match_reference_actions(f, c, m, ref_table))
        refs_fix.append(match_reference_actions(
            f, c, m, ref_table, levels=fixed_cfg.strict_levels,
            late_ref=fixed_cfg, buy_table=buy_table))
    def _action_by_turn(refs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for t in sorted(set(int(x) for x in turns.tolist())):
            idx = np.flatnonzero(turns == t)
            if idx.size == 0:
                continue
            st = action_stats(pi[idx], [refs[i] for i in idx])
            out[str(int(t))] = {
                "n": int(st["n"]),
                "kl_median": st["kl_median"], "kl_p90": st["kl_p90"],
                "nll_median": st["nll_median"],
                "c_act_mean": st["c_act_mean"],
            }
        return out

    action = {
        "ref_current": action_stats(pi, refs_cur),
        "ref_fixed": action_stats(pi, refs_fix),
        "ref_current_by_turn": _action_by_turn(refs_cur),
        "ref_fixed_by_turn": _action_by_turn(refs_fix),
        "score": pinfo,
    }

    # ── (5) 三回合可行性 ────────────────────────────────────────────────
    feas = feasibility(pool, pi, masks, refs_cur, refs_fix,
                       horizon=int(args.horizon))

    # ── (6) 判据 ────────────────────────────────────────────────────────
    cov = float(occ["coverage"])
    p3 = feas.get("p3_fixed", {}).get("log10_median")
    extreme_cov = bool(cov < float(args.coverage_threshold))
    extreme_p3 = bool(p3 is not None and float(p3) < math.log10(float(args.p3_threshold)))
    extreme = bool(extreme_cov or extreme_p3)
    decision = {
        "coverage": cov, "coverage_ci95": occ["ci95"],
        "coverage_threshold": float(args.coverage_threshold),
        "p3_fixed_log10_median": p3,
        "p3_threshold": float(args.p3_threshold),
        "p3_threshold_log10": float(math.log10(float(args.p3_threshold))),
        "extreme_coverage": extreme_cov, "extreme_p3": extreme_p3,
        "extreme": extreme,
        "verdict": ("extreme_condition" if extreme else "not_extreme"),
        "next_step": ("DAgger / search labels（在 learner 状态上取当前状态搜索标签，"
                      "离线人类近邻只作候选）" if extreme else
                      "先修参考解（本轮 fixed 参考解 + rerank），DAgger 暂缓"),
    }

    report = {
        "schema": "support_coverage_audit_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checkpoint": str(args.checkpoint),
        "learner_pool": str(args.learner_pool),
        "expert": {
            "observations": str(args.observations),
            "counts": st_counts,
            "windows_all": int(len(all_w)),
            "windows_late": int(len(late_w)),
            "windows_selected": int(len(selected)),
            "growth_quantile": gq, "growth_tau_log1p": tau,
            "growth_scope": str(args.growth_quantile_scope),
            "growth_tau_by_turn": tau_by_turn,
            "delta_p50_all": (float(np.percentile(
                [w["delta_log1p"] for w in all_w], 50)) if all_w else None),
            "delta_p90_late": (float(np.percentile(deltas, 90))
                               if deltas.size else None),
            "turns": dict(sorted(Counter(
                int(w["turn"]) for w in selected).items())),
        },
        "occupancy": occ,
        "action": action,
        "feasibility": feas,
        "decision": decision,
        "config": {
            "turn_min": int(args.turn_min), "horizon": int(args.horizon),
            "knn_k": int(args.knn_k), "holdout_frac": float(args.holdout_frac),
            "bootstrap": int(args.bootstrap), "seed": int(args.seed),
            "eta_percentile": float(args.eta_percentile),
        },
        "limitations": [
            "专家观测缺 gold/shop/隐藏量：kNN 只在共有可见子空间（13 维）里比，"
            "不是全状态密度（EXPERIMENT §7.3）；",
            "专家帧上不能执行动作（shop 不可得、买牌映射不到槽位），动作 KL 只在"
            "「可比状态」（learner 题池 + 人类参考解）上算；",
            "三回合可行性是固定状态序列上的动作似然连乘（Ππ），不是含环境转移的"
            "真实路径概率；",
            "专家样本量小（每局每回合一帧；t≥13 窗口 <20），turn 级 CI 很宽；",
            "learner 状态来自 s15 弱对手后期池（human p0.4×3 席），不是训练主分布。",
        ],
        "seconds": round(time.time() - t0, 1),
    }
    os.makedirs(os.path.dirname(os.path.abspath(str(args.out))) or ".",
                exist_ok=True)
    with open(str(args.out), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"[audit] report -> {args.out}", flush=True)

    md_path = str(args.md or "") or os.path.splitext(str(args.out))[0] + ".md"
    _write_md(md_path, report)
    print(f"[audit] markdown -> {md_path}", flush=True)
    print(json.dumps({
        "expert_windows": len(selected),
        "coverage": round(cov, 4), "coverage_ci95": [round(x, 4) for x in occ["ci95"]],
        "ood": round(1.0 - cov, 4),
        "kl_fixed_median": action["ref_fixed"]["kl_median"],
        "c_act_fixed": action["ref_fixed"]["c_act_mean"],
        "p3_fixed_log10_median": p3,
        "p3_growth_log10_median": feas.get("p3_growth", {}).get("log10_median"),
        "decision": decision["verdict"],
        "next_step": decision["next_step"],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


def _fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _write_md(path: str, report: Dict[str, Any]) -> None:
    occ = report["occupancy"]
    act = report["action"]
    feas = report["feasibility"]
    dec = report["decision"]
    exp = report["expert"]
    lines: List[str] = []
    lines.append("# 离线支持覆盖审计（s15 后期）\n")
    lines.append(f"> 由 `scripts/support_coverage_audit.py` 生成 "
                 f"（{report['generated_at']}）。全程离线，不训练。\n")
    lines.append("## 1. 一句话\n")
    lines.append(
        f"- 专家后期成长窗口 **{exp['windows_selected']}** 个"
        f"（t→t+{report['config']['horizon']}，Δ top "
        f"{int(report['expert']['growth_quantile'] * 100)}%，"
        f"t≥{report['config']['turn_min']}）；"
        f"落在 learner 占用测度内的比例 **C_state = {_fmt(dec['coverage'], 3)}**"
        f"（95% CI [{_fmt(dec['coverage_ci95'][0], 3)}, "
        f"{_fmt(dec['coverage_ci95'][1], 3)}]）⇒ **OOD = {_fmt(1 - dec['coverage'], 3)}**。\n")
    lines.append(
        f"- 三回合成长路径可行性（fixed 参考解）："
        f"log10 p3 中位 **{_fmt(dec['p3_fixed_log10_median'], 2)}**；"
        f"判定 **{dec['verdict']}**（阈值：C_state ≥ {dec['coverage_threshold']:.2f} 且 "
        f"p3 ≥ {dec['p3_threshold']:.0e}）。\n")
    lines.append(f"- 下一步：**{dec['next_step']}**。\n")
    lines.append("## 2. 关键数字\n")
    lines.append("| 指标 | 值 |\n|---|---:|")
    lines.append(f"| 专家 game-turn / 局数 | {exp['counts']['game_turns']} / {exp['counts']['games']} |")
    lines.append(f"| t→t+3 后期窗口 | {exp['windows_late']} |")
    lines.append(f"| 成长窗口（top {int(exp['growth_quantile'] * 100)}%） | {exp['windows_selected']} |")
    lines.append(f"| learner 状态 / 局 | {occ['learner']['fit_states'] + occ['learner']['holdout_states']} / {occ['learner']['games']} |")
    lines.append(f"| kNN k / η(p{occ['learner']['eta_percentile']:.0f}) | {occ['learner']['k']} / {_fmt(occ['learner']['eta'], 3)} |")
    lines.append(f"| learner holdout 覆盖率（=η 口径） | {_fmt(occ['learner']['holdout_coverage'], 3)} |")
    lines.append(f"| **专家覆盖率 C_state [95% CI]** | **{_fmt(dec['coverage'], 3)}** "
                 f"[{_fmt(dec['coverage_ci95'][0], 3)}, {_fmt(dec['coverage_ci95'][1], 3)}] |")
    lines.append(f"| 专家距离 / learner 中位距离 | {_fmt(occ['learner']['distance_ratio_median'], 2)}× |")
    lines.append(f"| KL(ref_fixed‖π) 中位 / p90 | {_fmt(act['ref_fixed']['kl_median'], 2)} / {_fmt(act['ref_fixed']['kl_p90'], 2)} |")
    lines.append(f"| NLL(ref top-1) 中位 | {_fmt(act['ref_fixed']['nll_median'], 2)} |")
    lines.append(f"| 动作支持覆盖 C_act（π>1e-3 的参考质量） | {_fmt(act['ref_fixed']['c_act_mean'], 3)} |")
    lines.append(f"| p3(fixed) log10 中位 / p10 | {_fmt(dec['p3_fixed_log10_median'], 2)} / "
                 f"{_fmt(feas.get('p3_fixed', {}).get('log10_p10'), 2)} |")
    lines.append(f"| p3(growth) log10 中位 | {_fmt(feas.get('p3_growth', {}).get('log10_median'), 2)} |")
    lines.append("")
    if occ.get("by_growth_strength"):
        g = occ["by_growth_strength"]
        lines.append("成长越强的专家状态越 OOD：" + 
                     f"top25% 覆盖 {_fmt(g['top25_coverage'], 3)}（n={g['top25_n']}）"
                     f" vs 其余 {_fmt(g['rest_coverage'], 3)}（n={g['rest_n']}）。\n")
    lines.append("## 3. 逐 turn 覆盖与强度对比\n")
    lines.append("| turn | 专家窗口 | 覆盖率(全局η) | 同 turn 覆盖率 | 中位 kNN 距离 | 专家强度 p50 | learner 强度 p50 | 比值 |\n"
                 "|---:|---:|---:|---:|---:|---:|---:|---:|")
    sbt = occ.get("strength_by_turn") or {}
    stt = occ.get("by_turn_same_turn") or {}
    for t, c in sorted(occ.get("by_turn", {}).items(), key=lambda kv: int(kv[0])):
        st = sbt.get(t) or {}
        sc = (stt.get(t) or {}).get("coverage")
        lines.append(f"| {t} | {c['n']} | {_fmt(c['coverage'], 3)} | "
                     f"{_fmt(sc, 3)} | {_fmt(c['median_distance'], 3)} | "
                     f"{_fmt(st.get('expert_p50'), 0)} | "
                     f"{_fmt(st.get('learner_p50'), 0)} | "
                     f"{_fmt(st.get('ratio_p50'), 1)}× |")
    lines.append("")
    al = occ.get("all_late") or {}
    if al:
        lines.append(f"对照：**全部** t≥{report['config']['turn_min']} 后期窗口（不按成长分位筛）"
                     f"覆盖率 {_fmt(al.get('coverage'), 3)} "
                     f"[{_fmt((al.get('ci95') or [None, None])[0], 3)}, "
                     f"{_fmt((al.get('ci95') or [None, None])[1], 3)}]。\n")
    lines.append("η 灵敏度（即使把密度阈值放宽到 learner holdout 的 p99.9）：\n")
    lines.append("| η 分位 | η | 专家覆盖率 |\n|---:|---:|---:|")
    for q, c in sorted((occ.get("eta_sensitivity") or {}).items(),
                       key=lambda kv: float(kv[0])):
        lines.append(f"| p{q} | {_fmt(c['eta'], 2)} | {_fmt(c['expert_coverage'], 3)} |")
    lines.append("")
    lines.append("## 4. 动作分布（可比状态 = learner 题池，n=%d）\n"
                 % act["ref_fixed"]["n"])
    lines.append("| 参考解 | n | KL 中位 | KL p90 | C_act | top-1 类型 |\n|---|---:|---:|---:|---:|---|")
    for key, name in (("ref_current", "current（旧）"), ("ref_fixed", "fixed（本轮）")):
        a = act[key]
        lines.append(f"| {name} | {a['n']} | {_fmt(a['kl_median'], 2)} | "
                     f"{_fmt(a['kl_p90'], 2)} | {_fmt(a['c_act_mean'], 3)} | "
                     f"{json.dumps(a['top1_kind'], ensure_ascii=False)} |")
    lines.append("")
    lines.append("逐 turn（fixed 参考解，只在严格层匹配到的题上）：\n")
    lines.append("| turn | n | KL 中位 | C_act |\n|---:|---:|---:|---:|")
    for t, a in sorted((act.get("ref_fixed_by_turn") or {}).items(),
                       key=lambda kv: int(kv[0])):
        lines.append(f"| {t} | {a['n']} | {_fmt(a['kl_median'], 2)} | "
                     f"{_fmt(a['c_act_mean'], 3)} |")
    lines.append("")
    lines.append("## 5. 判据与结论\n")
    lines.append(f"- C_state = {_fmt(dec['coverage'], 3)} "
                 f"{'<' if dec['extreme_coverage'] else '≥'} "
                 f"{dec['coverage_threshold']:.2f}；"
                 f"p3 log10 中位 = {_fmt(dec['p3_fixed_log10_median'], 2)} "
                 f"{'<' if dec['extreme_p3'] else '≥'} "
                 f"{dec['p3_threshold_log10']:.1f}。\n")
    lines.append(f"- **{dec['verdict']}** ⇒ {dec['next_step']}。\n")
    lines.append("## 6. 限制（必须一起读）\n")
    for x in report.get("limitations") or []:
        lines.append(f"- {x}")
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
