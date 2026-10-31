#!/usr/bin/env python3
"""缩放信号相关性诊断（离线；读 ``runs/scaling_signal/rollouts/*.jsonl``）。

回答三件事：
1. **相关性**：``前 9 回合施法次数`` / ``金色数`` / ``酒馆永久 buff`` 与
   ``最终名次(效用)`` / ``t12 战团 Σ(atk+hp)`` 的 Pearson + Spearman + bootstrap 95% CI；
   分组：真实经济（1x）vs ∞金币课程。
2. **梯度**：``utility ~ 施法次数``、``utility ~ log1p(战团)``、``战团 ~ 施法次数`` 的回归
   斜率（每单位 = 多少效用 / 身材），即「多施放一次法术在终局奖励里值多少」。
3. **阈值平坦性**：战团按十分位分桶 → 每桶平均名次/效用（附局级 bootstrap CI）；相邻桶
   ``|Δ名次| < 0.05 且身材 > 1.3×`` 计为「平坦且陡峭」。三种身材口径：
   - 绝对 ``t12`` Σ(atk+hp)（题面口径；自然只覆盖活到 t12 的子集）；
   - ``t9`` Σ / 真实 p50(t9) = 缩放倍数（无存活截断）；
   - ``本局战场相对值`` = 自己 Σ / 7 席对手平均 Σ（需要 ``--record-opponents``）。

统计口径
--------
- 名次 1..8 → 效用 ``u = 1 - 2(r-1)/7``（与 ``hsbg/az/train/common.py::RANK_UTILITY`` 一致）；
  「施法越多越好」应表现为 **与效用正相关**（与原始名次负相关）。
- bootstrap：局级有放回重采样，B=4000，percentile 95% CI，固定种子。
- 部分相关：秩残差法（先转秩，再对控制变量回归取残差，最后求 Pearson）。

用法::

  python scripts/scaling_signal_analysis.py --dir runs/scaling_signal \
      --arms real,gold99,gold99_cap120 --out runs/scaling_signal/report.json
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

RNG_SEED = 20261031
B = 4000
N_RANKS = 8
RANK_UTILITY = np.array([1.0 - 2.0 * (r - 1) / (N_RANKS - 1) for r in range(1, N_RANKS + 1)],
                        dtype=np.float64)
#: 真实 10k+ MMR 库的 t 回合 p50（data/real_library，见 runs/ceiling_probe/REPORT.md）
REAL_P50 = {9: 547, 10: 1132, 11: 2211, 12: 4458, 13: 9446, 14: 20889, 15: 26194}


#: 缩放载体（引擎 catalog 里 "cast a spell on this" 类 + Felboar）卡 id 集合
_CARRIER_IDS: Optional[set] = None
#: ``player_json`` 的 board 里 ``card`` 是 CardId(int)；这里缓存 int -> 卡 id 字符串
_CARD_ID_CACHE: Dict[int, str] = {}


def card_id_of(idx: Any) -> str:
    """CardId(int) -> 卡 id 字符串（如 ``BG36_762``）；引擎缺失/越界返回 ""。"""
    try:
        i = int(idx)
    except BaseException:  # noqa: BLE001
        return ""
    got = _CARD_ID_CACHE.get(i)
    if got is not None:
        return got
    out = ""
    try:
        import hsbg_engine as E
        out = str(E.card_info(i)[0] or "")
    except BaseException:  # noqa: BLE001
        out = ""
    _CARD_ID_CACHE[i] = out
    return out


def carrier_ids() -> set:
    """缩放载体卡 id：``cast a spell on this``（Devilish Distractor 等）+ Felboar。"""
    global _CARRIER_IDS
    if _CARRIER_IDS is not None:
        return _CARRIER_IDS
    ids = {"BG28_633"}          # Felboar：施放 3 个法术后吞食酒馆随从
    try:
        import hsbg_engine as E
        for c in json.loads(E.catalog_json()):
            txt = (c.get("text") or "").lower()
            if "cast a spell on this" in txt or "whenever you cast a spell on this" in txt:
                ids.add(str(c.get("id")))
    except BaseException:  # noqa: BLE001 - 引擎缺失时退化为只有 Felboar
        pass
    _CARRIER_IDS = ids
    return ids


# ══════════════════════════════════════════════════════════════════════════
# 每局派生指标
# ══════════════════════════════════════════════════════════════════════════
def _recruits(r: dict) -> List[dict]:
    return [t for t in (r.get("turns") or []) if t.get("stage") == "recruit_end"]


def derive(r: dict) -> Optional[dict]:
    te = _recruits(r)
    if not te or int(r.get("placement") or 0) <= 0:
        return None
    final = (r.get("turns") or [])[-1]
    by_turn = {int(t["turn"]): t for t in te}

    def cum(turn: int, key: str) -> Optional[int]:
        t = by_turn.get(int(turn))
        return None if t is None else int(t["stats"].get(key, 0) or 0)

    def last_le(turn: int, key: str) -> float:
        cand = [t for t in te if int(t["turn"]) <= int(turn)]
        t = cand[-1] if cand else final
        return float(t["stats"].get(key, 0) or 0)

    def str_at(turn: int) -> Optional[int]:
        t = by_turn.get(int(turn))
        return None if t is None else int(t["strength"])

    def opp_at(turn: int, key: str = "opp_mean") -> Optional[float]:
        t = by_turn.get(int(turn))
        if not t or t.get(key) is None:
            return None
        return float(t[key])

    casts9 = last_le(9, "tavern_spells_cast")
    tav_turns = 0
    prev = 0.0
    for t in [x for x in te if int(x["turn"]) <= 9]:
        cur = float(t["stats"].get("tavern_atk", 0) or 0) + float(t["stats"].get("tavern_hp", 0) or 0)
        if cur > prev:
            tav_turns += 1
        prev = max(prev, cur)
    p = int(r["placement"])
    s9 = str_at(9)
    s12 = str_at(12)
    opp9 = opp_at(9)
    opp_last = te[-1].get("opp_mean") if te else None
    rel9 = (float(s9) / max(float(opp9), 1.0)) if (s9 is not None and opp9) else None
    slast = int(te[-1]["strength"])
    rel_last = (float(slast) / max(float(opp_last), 1.0)) if opp_last else None
    # 施法速率：把「死得早 → 累计施法少」的机械混杂按回合数归一（分母用 min(死亡回合, 9)）
    cids = carrier_ids()

    def _ncarrier(t: dict) -> int:
        return sum(1 for c in (t.get("board_cards") or []) if card_id_of(c) in cids)

    carrier_turns = 0
    for t in [x for x in te if int(x["turn"]) <= 9]:
        if _ncarrier(t) > 0:
            carrier_turns += 1
    t9row = by_turn.get(9) or (te[-1] if te else {})
    has_carrier9 = bool(_ncarrier(t9row) > 0)
    carrier_max = max([_ncarrier(t) for t in te] or [0])
    horizon = max(1, min(int(r.get("death_turn") or 0) or 9, 9))
    return {
        "seed": int(r["seed"]),
        "tag": str(r.get("tag")),
        "gold": int(r.get("gold") or 0),
        "placement": p,
        "utility": float(RANK_UTILITY[p - 1]),
        "death_turn": int(r.get("death_turn") or 0),
        "turns_played": len(te),
        "truncated": bool(r.get("truncated")),
        "decisions": int(r.get("decisions") or 0),
        # 前 9 回合（窗口内累计）
        "casts9": casts9,
        "casts9_rate": float(casts9) / horizon,
        "spells9": last_le(9, "spells_cast"),
        "golden9": last_le(9, "golden_played"),
        "tavern9": last_le(9, "tavern_atk") + last_le(9, "tavern_hp"),
        "tavern_turns9": float(tav_turns),
        "gold_spent9": last_le(9, "gold_spent_total"),
        "bought9": last_le(9, "minions_bought"),
        "played9": last_le(9, "cards_played"),
        "refreshes9": last_le(9, "refreshes"),
        "full9": bool(9 in by_turn),
        "has_carrier9": int(has_carrier9),
        "carrier_turns9": float(carrier_turns),
        "carrier_max": float(carrier_max),
        # 战团
        "str9": s9,
        "str12": s12,
        "str15": str_at(15),
        "str_last": slast,
        "ratio9": (float(s9) / REAL_P50[9]) if s9 is not None else None,
        "ratio12": (float(s12) / REAL_P50[12]) if s12 is not None else None,
        "opp_mean9": opp9,
        "opp_max9": (by_turn.get(9) or {}).get("opp_max"),
        "opp_mean_last": opp_last,
        "rel9": rel9,
        "rel_last": rel_last,
        "tier9": (by_turn.get(9) or {}).get("tier"),
        "gold9": (by_turn.get(9) or {}).get("gold"),
    }


def load_arm(path: str) -> List[dict]:
    out: List[dict] = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = derive(json.loads(line))
            if d is not None:
                out.append(d)
    out.sort(key=lambda d: d["seed"])
    return out


# ══════════════════════════════════════════════════════════════════════════
# 统计工具
# ══════════════════════════════════════════════════════════════════════════
def _rank(a: np.ndarray) -> np.ndarray:
    """平均秩（处理并列）。"""
    a = np.asarray(a, dtype=np.float64)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(a.size, dtype=np.float64)
    ranks[order] = np.arange(1, a.size + 1, dtype=np.float64)
    vals, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    if vals.size < a.size:
        sums = np.zeros(vals.size, dtype=np.float64)
        np.add.at(sums, inv, ranks)
        ranks = (sums / counts)[inv]
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.size < 2:
        return float("nan")
    if x.std() == 0.0 or y.std() == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    return pearson(_rank(np.asarray(x)), _rank(np.asarray(y)))


def boot_ci_corr(x: Sequence[float], y: Sequence[float], *, method: str = "pearson",
                 B: int = B, seed: int = RNG_SEED) -> Tuple[float, float, float]:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n = x.size
    fn = spearman if method == "spearman" else pearson
    point = fn(x, y)
    if n < 4 or not np.isfinite(point):
        return point, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n))
    vals = np.array([fn(x[i], y[i]) for i in idx], dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return point, float("nan"), float("nan")
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return point, float(lo), float(hi)


def boot_ci_mean(v: Sequence[float], *, B: int = B, seed: int = RNG_SEED) -> Tuple[float, float, float]:
    v = np.asarray(v, dtype=np.float64)
    v = v[np.isfinite(v)]
    n = v.size
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    if n == 1:
        return float(v[0]), float(v[0]), float(v[0])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n))
    vals = v[idx].mean(axis=1)
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(v.mean()), float(lo), float(hi)


def _resid(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    if X.size == 0:
        return y - y.mean()
    A = np.column_stack([np.ones(y.size, dtype=np.float64), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return y - A @ beta


def partial_corr_rank(x: np.ndarray, y: np.ndarray, controls: Sequence[np.ndarray],
                      *, B: int = B, seed: int = RNG_SEED) -> Tuple[float, float, float]:
    rx, ry = _rank(x), _rank(y)
    X = (np.column_stack([_rank(c) for c in controls])
         if controls else np.empty((rx.size, 0)))
    ex, ey = _resid(rx, X), _resid(ry, X)
    point = pearson(ex, ey)
    n = rx.size
    if n < 6 or not np.isfinite(point):
        return point, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n))
    vals = np.array([pearson(ex[i], ey[i]) for i in idx], dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return point, float("nan"), float("nan")
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return point, float(lo), float(hi)


def boot_slope(y: Sequence[float], x: Sequence[float], *, B: int = B,
               seed: int = RNG_SEED) -> Dict[str, float]:
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if x.size < 4:
        return {"slope": float("nan"), "lo": float("nan"), "hi": float("nan"), "r2": float("nan")}
    X = np.column_stack([np.ones(x.size), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(B, x.size))
    bs = []
    for i in idx:
        if np.ptp(x[i]) == 0:
            continue
        bb, *_ = np.linalg.lstsq(X[i], y[i], rcond=None)
        bs.append(float(bb[1]))
    bs = np.array([b for b in bs if np.isfinite(b)], dtype=np.float64)
    lo, hi = (np.percentile(bs, [2.5, 97.5]) if bs.size else (float("nan"), float("nan")))
    return {"slope": float(beta[1]), "lo": float(lo), "hi": float(hi), "r2": float(r2)}


def corr_table(rows: List[dict], pairs: Sequence[Tuple[str, str, str]],
               *, seed: int = RNG_SEED) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for label, xk, yk in pairs:
        sub = [r for r in rows if r.get(xk) is not None and r.get(yk) is not None]
        x = np.array([r[xk] for r in sub], dtype=np.float64)
        y = np.array([r[yk] for r in sub], dtype=np.float64)
        if x.size < 4 or np.ptp(x) == 0 or np.ptp(y) == 0:
            out[label] = {"n": int(x.size), "pearson": None, "spearman": None,
                          "note": "退化（常量或样本 <4）"}
            continue
        pr, plo, phi = boot_ci_corr(x, y, method="pearson", seed=seed)
        sr, slo, shi = boot_ci_corr(x, y, method="spearman", seed=seed)
        out[label] = {
            "n": int(x.size), "x": xk, "y": yk,
            "pearson": round(pr, 4), "pearson_ci": [round(plo, 4), round(phi, 4)],
            "spearman": round(sr, 4), "spearman_ci": [round(slo, 4), round(shi, 4)],
            "x_mean": round(float(x.mean()), 3), "y_mean": round(float(y.mean()), 3),
            "x_p50": round(float(np.percentile(x, 50)), 3),
            "x_p90": round(float(np.percentile(x, 90)), 3),
        }
    return out


# ══════════════════════════════════════════════════════════════════════════
# 十分位阈值平坦性
# ══════════════════════════════════════════════════════════════════════════
def decile_flatness(rows: List[dict], skey: str, *, by: str = "utility",
                    n_bins: int = 10, min_n: int = 40, seed: int = RNG_SEED) -> Dict[str, Any]:
    sub = [r for r in rows if r.get(skey) is not None]
    if len(sub) < min_n:
        return {"n": len(sub), "bins": [], "note": f"样本不足（n={len(sub)} < {min_n}）"}
    vals = np.array([r[skey] for r in sub], dtype=np.float64)
    edges = np.quantile(vals, np.linspace(0, 1, n_bins + 1))
    edges[0] = -np.inf
    edges[-1] = np.inf
    bins = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        grp = [r for r in sub if lo <= r[skey] < hi]
        if not grp:
            continue
        y = np.array([r[by] for r in grp], dtype=np.float64)
        place = np.array([r["placement"] for r in grp], dtype=np.float64)
        s = np.array([r[skey] for r in grp], dtype=np.float64)
        mu, mlo, mhi = boot_ci_mean(y, seed=seed + i)
        rng = np.random.default_rng(seed + 100 + i)
        idx = rng.integers(0, place.size, size=(B, place.size))
        pmeans = place[idx].mean(axis=1)
        bins.append({
            "bin": i + 1, "n": len(grp),
            "lo": (None if lo == -np.inf else round(float(lo), 1)),
            "hi": (None if hi == np.inf else round(float(hi), 1)),
            "x_mean": round(float(s.mean()), 1),
            "mean_placement": round(float(place.mean()), 3),
            "place_ci": [round(float(np.percentile(pmeans, 2.5)), 3),
                         round(float(np.percentile(pmeans, 97.5)), 3)],
            "mean_utility": round(mu, 4),
            "utility_ci": [round(mlo, 4), round(mhi, 4)],
        })
    adj = []
    for a, b in zip(bins, bins[1:]):
        d_place = b["mean_placement"] - a["mean_placement"]
        ratio = (b["x_mean"] / a["x_mean"]) if a["x_mean"] else float("inf")
        adj.append({
            "pair": f"{a['bin']}->{b['bin']}",
            "d_place": round(float(d_place), 4),
            "d_utility": round(float(b["mean_utility"] - a["mean_utility"]), 4),
            "strength_ratio": round(float(ratio), 3),
            "d_place_per_100str": (round(float(d_place) / max(b["x_mean"] - a["x_mean"], 1e-9) * 100.0, 4)
                                   if b["x_mean"] != a["x_mean"] else None),
            "flat": bool(abs(d_place) < 0.05),
            "steep": bool(ratio > 1.3),
            "flat_and_steep": bool(abs(d_place) < 0.05 and ratio > 1.3),
        })
    overall = None
    if len(bins) >= 2:
        first, last = bins[0], bins[-1]
        overall = {
            "d_place_top_minus_bottom": round(float(last["mean_placement"] - first["mean_placement"]), 4),
            "d_utility": round(float(last["mean_utility"] - first["mean_utility"]), 4),
            "strength_ratio": round(float(last["x_mean"] / max(first["x_mean"], 1e-9)), 3),
        }
    return {"n": len(sub), "key": skey, "bins": bins, "adjacent": adj,
            "flat_and_steep_pairs": sum(1 for a in adj if a["flat_and_steep"]),
            "n_pairs": len(adj), "overall": overall}


# ══════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════
PAIRS = (
    ("casts9_utility", "casts9", "utility"),
    ("casts9_placement", "casts9", "placement"),
    ("casts9_rate_utility", "casts9_rate", "utility"),
    ("casts9_str9", "casts9", "str9"),
    ("casts9_str12", "casts9", "str12"),
    ("golden9_str12", "golden9", "str12"),
    ("golden9_utility", "golden9", "utility"),
    ("tavern9_str12", "tavern9", "str12"),
    ("tavern9_utility", "tavern9", "utility"),
    ("str9_utility", "str9", "utility"),
    ("str12_utility", "str12", "utility"),
    ("ratio9_utility", "ratio9", "utility"),
    ("rel9_utility", "rel9", "utility"),
    ("rel_last_utility", "rel_last", "utility"),
    ("bought9_str12", "bought9", "str12"),
    ("carrier9_utility", "has_carrier9", "utility"),
    ("carrier_turns9_str12", "carrier_turns9", "str12"),
    ("carrier_turns9_utility", "carrier_turns9", "utility"),
    ("casts9_str9_given_carrier", "casts9", "str9"),
)


def describe(rows: List[dict]) -> Dict[str, Any]:
    def q(key: str, p: float) -> Optional[float]:
        v = [r[key] for r in rows if r.get(key) is not None]
        return None if not v else round(float(np.percentile(v, p)), 2)

    def m(key: str) -> Optional[float]:
        v = [r[key] for r in rows if r.get(key) is not None]
        return None if not v else round(float(np.mean(v)), 3)

    def frac(key: str, thr: float) -> Optional[float]:
        v = [r[key] for r in rows if r.get(key) is not None]
        return None if not v else round(float(np.mean([1.0 if x >= thr else 0.0 for x in v])), 3)

    return {
        "n": len(rows),
        "mean_rank": m("placement"),
        "top4": (round(float(np.mean([r["placement"] <= 4 for r in rows])), 3) if rows else None),
        "win": (round(float(np.mean([r["placement"] == 1 for r in rows])), 3) if rows else None),
        "mean_utility": m("utility"),
        "utility_sd": (round(float(np.std([r["utility"] for r in rows])), 4) if rows else None),
        "placement_sd": (round(float(np.std([r["placement"] for r in rows])), 4) if rows else None),
        "death_turn_p50": q("death_turn", 50),
        "death_turn_p90": q("death_turn", 90),
        "turns_played_p50": q("turns_played", 50),
        "casts9_mean": m("casts9"), "casts9_p50": q("casts9", 50),
        "casts9_p90": q("casts9", 90), "casts9_max": q("casts9", 100),
        "casts9_ge1": frac("casts9", 1), "casts9_ge5": frac("casts9", 5),
        "casts9_ge10": frac("casts9", 10),
        "golden9_mean": m("golden9"), "golden9_p90": q("golden9", 90),
        "tavern9_mean": m("tavern9"), "tavern9_ge1": frac("tavern9", 1),
        "tavern_turns9_mean": m("tavern_turns9"),
        "gold_spent9_mean": m("gold_spent9"),
        "bought9_mean": m("bought9"), "refreshes9_mean": m("refreshes9"),
        "str9_p50": q("str9", 50), "ratio9_p50": q("ratio9", 50),
        "str12_n": len([r for r in rows if r.get("str12") is not None]),
        "str12_p50": q("str12", 50), "str12_p90": q("str12", 90),
        "str15_n": len([r for r in rows if r.get("str15") is not None]),
        "str15_p50": q("str15", 50),
        "str_last_p50": q("str_last", 50), "str_last_p90": q("str_last", 90),
        "rel9_p50": q("rel9", 50),
        "opp_mean9_p50": q("opp_mean9", 50),
        "decisions_mean": m("decisions"),
        "carrier9_frac": m("has_carrier9"),
        "carrier_turns9_mean": m("carrier_turns9"),
        "carrier_max_mean": m("carrier_max"),
    }


def analyze_arm(rows: List[dict], name: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"arm": name, "describe": describe(rows),
                           "corr": corr_table(rows, PAIRS)}
    # 稳健性：只取活到 t9 招募末的局（消除「死得早 → 累计施法少」的机械混杂）
    full9 = [r for r in rows if r.get("full9")]
    out["corr_full9"] = corr_table(full9, (("casts9_utility", "casts9", "utility"),
                                           ("casts9_str12", "casts9", "str12"),
                                           ("golden9_str12", "golden9", "str12")))
    out["n_full9"] = len(full9)
    # 有缩放载体（"cast a spell on this"/Felboar）的子集：施法是否终于能换来身材？
    car = [r for r in rows if int(r.get("has_carrier9") or 0) > 0]
    out["n_carrier"] = len(car)
    out["corr_carrier"] = corr_table(car, (("casts9_str9", "casts9", "str9"),
                                           ("casts9_str12", "casts9", "str12"),
                                           ("casts9_utility", "casts9", "utility"),
                                           ("casts9_str_last", "casts9", "str_last")))
    # 部分相关
    sub12 = [r for r in rows if r.get("str12") is not None]
    part: Dict[str, Any] = {}
    spec = (("casts9_utility|death_turn", "casts9", "utility", ["death_turn"], "all"),
            ("casts9_utility|death_turn+gold_spent9", "casts9", "utility",
             ["death_turn", "gold_spent9"], "all"),
            ("casts9_str12|gold_spent9", "casts9", "str12", ["gold_spent9"], "s12"),
            ("casts9_str12|death_turn+gold_spent9", "casts9", "str12",
             ["death_turn", "gold_spent9"], "s12"))
    for label, xk, yk, ctl, pool in spec:
        sel = [r for r in (rows if pool == "all" else sub12)
               if all(r.get(c) is not None for c in (xk, yk, *ctl))]
        if len(sel) < 8:
            part[label] = {"n": len(sel), "note": "样本不足"}
            continue
        x = np.array([r[xk] for r in sel], dtype=np.float64)
        y = np.array([r[yk] for r in sel], dtype=np.float64)
        C = [np.array([r[c] for r in sel], dtype=np.float64) for c in ctl]
        pr, lo, hi = partial_corr_rank(x, y, C)
        part[label] = {"n": len(sel),
                       "partial_r": round(pr, 4) if np.isfinite(pr) else None,
                       "ci": [round(lo, 4) if np.isfinite(lo) else None,
                              round(hi, 4) if np.isfinite(hi) else None],
                       "controls": ctl}
    out["partial"] = part
    # 斜率：每单位 = 多少效用 / 多少身材
    slopes: Dict[str, Any] = {}
    spec2 = (("utility~casts9", "casts9", "utility", (0, 0)),
             ("utility~log1p_str12", "str12", "utility", (1, 0)),
             ("str9~casts9", "casts9", "str9", (0, 0)),
             ("log1p_str9~casts9", "casts9", "str9", (0, 1)),
             ("str12~casts9", "casts9", "str12", (0, 0)),
             ("utility~log1p_ratio9", "ratio9", "utility", (1, 0)),
             ("utility~str9", "str9", "utility", (0, 0)))
    for label, xk, yk, lg in spec2:
        sel = [r for r in rows if r.get(xk) is not None and r.get(yk) is not None]
        y = np.array([r[yk] for r in sel], dtype=np.float64)
        x = np.array([r[xk] for r in sel], dtype=np.float64)
        if lg[0]:
            x = np.log1p(np.maximum(x, 0.0))
        if lg[1]:
            y = np.log1p(np.maximum(y, 0.0))
        sl = boot_slope(y, x)
        slopes[label] = {
            "n": int(x.size),
            "slope": round(sl["slope"], 6) if np.isfinite(sl["slope"]) else None,
            "ci": [None if not np.isfinite(sl["lo"]) else round(sl["lo"], 6),
                   None if not np.isfinite(sl["hi"]) else round(sl["hi"], 6)],
            "r2": round(sl["r2"], 4) if np.isfinite(sl["r2"]) else None,
            "log_x": int(lg[0]), "log_y": int(lg[1]), "x": xk, "y": yk,
        }
    out["slope"] = slopes
    out["flat_str12"] = decile_flatness(rows, "str12")
    out["flat_ratio9"] = decile_flatness(rows, "ratio9")
    out["flat_rel9"] = decile_flatness(rows, "rel9")
    out["flat_str_last"] = decile_flatness(rows, "str_last")
    # 施法三分位 → 名次/身材（「有没有梯度」的直观读数）
    tert = []
    sel = [r for r in rows if r.get("casts9") is not None]
    if len(sel) >= 30:
        vals = np.array([r["casts9"] for r in sel], dtype=np.float64)
        q1, q2 = np.quantile(vals, [1 / 3, 2 / 3])
        groups = [("low", [r for r in sel if r["casts9"] < q1]),
                  ("mid", [r for r in sel if q1 <= r["casts9"] < q2]),
                  ("high", [r for r in sel if r["casts9"] >= q2])]
        for name, grp in groups:
            mu, lo, hi = boot_ci_mean([r["utility"] for r in grp], seed=RNG_SEED + 7)
            s9 = [r["str9"] for r in grp if r.get("str9") is not None]
            tert.append({"group": name, "n": len(grp),
                         "casts9_mean": round(float(np.mean([r["casts9"] for r in grp])), 2),
                         "mean_placement": round(float(np.mean([r["placement"] for r in grp])), 3),
                         "mean_utility": round(mu, 4),
                         "utility_ci": [round(lo, 4), round(hi, 4)],
                         "str9_p50": (round(float(np.percentile(s9, 50)), 1) if s9 else None),
                         "top4": round(float(np.mean([r["placement"] <= 4 for r in grp])), 3)})
    out["tertile"] = tert
    return out


def _fmt_ci(point: Optional[float], ci: Sequence[Optional[float]]) -> str:
    if point is None:
        return "n/a"
    lo, hi = (ci[0], ci[1]) if len(ci) == 2 else (None, None)
    if lo is None or hi is None or (isinstance(lo, float) and not np.isfinite(lo)):
        return f"{point:+.3f} [n/a]"
    return f"{point:+.3f} [{lo:+.3f},{hi:+.3f}]"


def md_tables(report: Dict[str, Any]) -> str:
    L: List[str] = []
    arms = report["arms"]
    names = [a["arm"] for a in arms]
    L.append("### A. 描述统计\n")
    keys = ["n", "mean_rank", "placement_sd", "top4", "win", "mean_utility", "utility_sd",
            "death_turn_p50",
            "casts9_mean", "casts9_p50", "casts9_p90", "casts9_ge5",
            "golden9_mean", "tavern9_mean", "tavern9_ge1", "gold_spent9_mean",
            "str9_p50", "ratio9_p50", "str12_n", "str12_p50", "str_last_p50",
            "opp_mean9_p50", "rel9_p50", "decisions_mean"]
    L.append("| 指标 | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for k in keys:
        vals = []
        for a in arms:
            v = a["describe"].get(k)
            vals.append("—" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v)))
        L.append(f"| {k} | " + " | ".join(vals) + " |")
    L.append("")
    L.append("### B. 相关性（Pearson r / Spearman ρ，bootstrap 95% CI）\n")
    L.append("| 相关对 | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for label, _x, _y in PAIRS:
        cells = []
        for a in arms:
            c = a["corr"].get(label) or {}
            if c.get("pearson") is None:
                cells.append("n/a")
                continue
            cells.append(f"r={_fmt_ci(c['pearson'], c['pearson_ci'])}"
                         f"<br>ρ={_fmt_ci(c['spearman'], c['spearman_ci'])}"
                         f"<br>n={c['n']}")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("### C. 稳健性：只取活到 t9 招募末的局（消除存活混杂）\n")
    L.append("| 相关对 | " + " | ".join(f"{n}(n={a['n_full9']})" for n, a in zip(names, arms)) + " |")
    L.append("|---|" + "---|" * len(names))
    for label in ("casts9_utility", "casts9_str12", "golden9_str12"):
        cells = []
        for a in arms:
            c = a["corr_full9"].get(label) or {}
            if c.get("pearson") is None:
                cells.append("n/a")
                continue
            cells.append(f"r={_fmt_ci(c['pearson'], c['pearson_ci'])}"
                         f"<br>ρ={_fmt_ci(c['spearman'], c['spearman_ci'])}"
                         f"<br>n={c['n']}")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("### C2. 只取「有缩放载体」的局（cast-a-spell-on-this / Felboar 在场）\n")
    L.append("| 相关对 | " + " | ".join(f"{n}(n={a.get('n_carrier')})" for n, a in zip(names, arms)) + " |")
    L.append("|---|" + "---|" * len(names))
    for label in ("casts9_str9", "casts9_str12", "casts9_utility", "casts9_str_last"):
        cells = []
        for a in arms:
            c = (a.get("corr_carrier") or {}).get(label) or {}
            if c.get("pearson") is None:
                cells.append("n/a")
                continue
            cells.append(f"r={_fmt_ci(c['pearson'], c['pearson_ci'])}"
                         f"<br>ρ={_fmt_ci(c['spearman'], c['spearman_ci'])}"
                         f"<br>n={c['n']}")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("### D. 部分相关（秩残差，控制存活/活动量）\n")
    L.append("| 控制 | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for label in ("casts9_utility|death_turn", "casts9_utility|death_turn+gold_spent9",
                  "casts9_str12|gold_spent9", "casts9_str12|death_turn+gold_spent9"):
        cells = []
        for a in arms:
            p = a["partial"].get(label) or {}
            if p.get("partial_r") is None:
                cells.append("n/a")
                continue
            cells.append(f"{_fmt_ci(p['partial_r'], p['ci'])}<br>n={p['n']}")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("### E. 斜率（每单位 = 效用 / 身材增量）\n")
    L.append("| 回归 | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for label in ("utility~casts9", "utility~log1p_str12", "utility~log1p_ratio9",
                  "utility~str9", "str9~casts9", "log1p_str9~casts9", "str12~casts9"):
        cells = []
        for a in arms:
            s = a["slope"].get(label) or {}
            if s.get("slope") is None:
                cells.append("n/a")
                continue
            cells.append(f"{_fmt_ci(s['slope'], s['ci'])}<br>R²={s['r2']} n={s['n']}")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("### F. 施法三分位（低/中/高）→ 名次与身材\n")
    L.append("| arm | 组 | n | 施法数均值 | 平均名次 | 平均效用 [95%CI] | top4 | t9 Σ p50 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for a in arms:
        for t in a.get("tertile") or []:
            L.append(f"| {a['arm']} | {t['group']} | {t['n']} | {t['casts9_mean']} | "
                     f"{t['mean_placement']} | {_fmt_ci(t['mean_utility'], t['utility_ci'])} | "
                     f"{t['top4']} | {t['str9_p50']} |")
    L.append("")
    titles = {"flat_str12": "t12 Σ(atk+hp) 十分位（题面口径；仅活到 t12 的子集）",
              "flat_ratio9": "t9 Σ / 真实 p50(t9)=547 的缩放倍数十分位",
              "flat_rel9": "t9 Σ / 7 席对手平均 Σ 十分位（同局相对强度）",
              "flat_str_last": "终局（最后一回合）Σ 十分位"}
    for a in arms:
        for skey, title in titles.items():
            f = a.get(skey) or {}
            if not f.get("bins"):
                continue
            L.append(f"#### {a['arm']} — {title}（n={f['n']}）\n")
            L.append("| 桶 | n | Σ 均值 | 区间 | 平均名次 | 名次 95%CI | 平均效用 |")
            L.append("|---|---|---|---|---|---|---|")
            for b in f["bins"]:
                if b["lo"] is None:
                    rng_ = f"<{b['hi']}"
                elif b["hi"] is None:
                    rng_ = f"≥{b['lo']}"
                else:
                    rng_ = f"{b['lo']}–{b['hi']}"
                L.append(f"| {b['bin']} | {b['n']} | {b['x_mean']} | {rng_} | "
                         f"{b['mean_placement']} | [{b['place_ci'][0]},{b['place_ci'][1]}] | "
                         f"{b['mean_utility']:+.3f} |")
            L.append("")
            L.append("| 相邻桶 | Δ名次 | Δ效用 | 身材比 | 平坦(<0.05) | 陡峭(>1.3×) | 平坦且陡峭 |")
            L.append("|---|---|---|---|---|---|---|")
            for ad in f["adjacent"]:
                L.append(f"| {ad['pair']} | {ad['d_place']:+.3f} | {ad['d_utility']:+.3f} | "
                         f"{ad['strength_ratio']:.2f}× | {'✓' if ad['flat'] else ''} | "
                         f"{'✓' if ad['steep'] else ''} | {'**✓**' if ad['flat_and_steep'] else ''} |")
            o = f.get("overall")
            if o:
                L.append("")
                L.append(f"整体（最低桶→最高桶）：Δ名次 {o['d_place_top_minus_bottom']:+.3f}，"
                         f"Δ效用 {o['d_utility']:+.3f}，身材 {o['strength_ratio']:.2f}×；"
                         f"「平坦且陡峭」相邻桶对 {f['flat_and_steep_pairs']}/{f['n_pairs']}")
            L.append("")
    if report.get("paired"):
        p = report["paired"]
        L.append("### G. 配对比较（同 seed：real vs gold99）\n")
        L.append(f"- 共享 seed：{p['shared_seeds']}；名次变化均值 {p['d_placement']['mean_delta']:+.3f} "
                 f"[{p['d_placement']['ci'][0]:+.3f},{p['d_placement']['ci'][1]:+.3f}]"
                 f"（gold 更好 {p['wins_gold']} 局 / real 更好 {p['wins_real']} 局 / 平 {p['ties']}）")
        L.append(f"- 前 9 回合施法次数变化 {p['d_casts9']['mean_delta']:+.3f} "
                 f"[{p['d_casts9']['ci'][0]:+.3f},{p['d_casts9']['ci'][1]:+.3f}]")
        L.append(f"- t12 战团 Σ 变化 {p['d_str12']['mean_delta']:+.1f} "
                 f"[{p['d_str12']['ci'][0]:+.1f},{p['d_str12']['ci'][1]:+.1f}]（n={p['d_str12']['n']}）")
        L.append("")
    if report.get("dose"):
        L.append("### H. 金币剂量曲线（「课程开多大」）\n")
        L.append("| gold | n | 施法数(t9) 均值 | 施法 p90 | Σ(t9) p50 | Σ/真实p50(t9) | "
                 "平均名次 | top4 | r(施法,效用) | r(Σ9,效用) | r(施法,Σ12) |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for d in report["dose"]:
            c = d.get("corr_casts_utility") or {}
            c2 = d.get("corr_str9_utility") or {}
            c3 = d.get("corr_casts_str12") or {}
            L.append(f"| {d['gold']} | {d['n']} | {d['casts9_mean']} | {d['casts9_p90']} | "
                     f"{d['str9_p50']} | {d.get('ratio9_p50')} | {d['mean_rank']} | {d['top4']} | "
                     f"{_fmt_ci(c.get('pearson'), c.get('pearson_ci') or [None, None])} | "
                     f"{_fmt_ci(c2.get('pearson'), c2.get('pearson_ci') or [None, None])} | "
                     f"{_fmt_ci(c3.get('pearson'), c3.get('pearson_ci') or [None, None])} |")
        L.append("")
    if report.get("verdict"):
        L.append("### I. 判定（题面判据）\n")
        for k, v in report["verdict"].items():
            L.append(f"- **{k}**：{v}")
        L.append("")
    return "\n".join(L)


def decide_verdict(report: Dict[str, Any]) -> Dict[str, str]:
    """按题面判据给出自动判定（原始数字另行人工解读）。"""
    arms = {a["arm"]: a for a in report["arms"]}
    out: Dict[str, str] = {}

    def pick(prefix: str) -> Optional[str]:
        for k in arms:
            if str(k).startswith(prefix):
                return k
        return None

    def cell(prefix: str, key: str) -> Optional[dict]:
        k = pick(prefix)
        a = arms.get(k) if k else None
        return None if a is None else (a["corr"].get(key) or None)

    r = cell("real", "casts9_utility")
    g = cell("gold99", "casts9_utility")
    if r and r.get("pearson") is not None:
        lo, hi = r["pearson_ci"]
        out["真实经济 corr(施法9, 效用)"] = (
            f"r={r['pearson']:+.3f} CI[{lo:+.3f},{hi:+.3f}] "
            f"(CI 含 0: {'是' if lo <= 0 <= hi else '否'}; |r|<0.1: "
            f"{'是' if abs(r['pearson']) < 0.1 else '否'})")
    if g and g.get("pearson") is not None:
        lo, hi = g["pearson_ci"]
        out["∞金币 corr(施法9, 效用)"] = (
            f"r={g['pearson']:+.3f} CI[{lo:+.3f},{hi:+.3f}] "
            f"(r>0.3 且 CI 不含 0: {'是' if (g['pearson'] > 0.3 and lo > 0) else '否'})")
    rt = cell("real", "casts9_str12")
    gt = cell("gold99", "casts9_str12")
    gs = cell("gold99", "casts9_str9")
    if gs and gs.get("pearson") is not None:
        lo, hi = gs["pearson_ci"]
        out["∞金币 corr(施法9, t9 Σ)"] = (
            f"r={gs['pearson']:+.3f} CI[{lo:+.3f},{hi:+.3f}] "
            f"(≤0 说明「多施法」并不换来更强战团)")
    if rt:
        out["真实经济 corr(施法9, t12 Σ)"] = f"r={rt['pearson']:+.3f} n={rt['n']}"
    if gt:
        out["∞金币 corr(施法9, t12 Σ)"] = f"r={gt['pearson']:+.3f} n={gt['n']}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="runs/scaling_signal")
    ap.add_argument("--arms", default="real,gold99,gold99_cap120")
    ap.add_argument("--dose-tags",
                    default="dose_g12,dose_g15,dose_g20,dose_g30,dose_g50,dose_g99")
    ap.add_argument("--out", default="runs/scaling_signal/report.json")
    ap.add_argument("--tables", default="runs/scaling_signal/tables.md")
    args = ap.parse_args()

    rdir = os.path.join(args.dir, "rollouts")
    arms: List[Dict[str, Any]] = []
    data: Dict[str, List[dict]] = {}
    for name in [x.strip() for x in args.arms.split(",") if x.strip()]:
        rows = load_arm(os.path.join(rdir, f"{name}.jsonl"))
        if not rows:
            print(f"[warn] 空 arm: {name}")
            continue
        data[name] = rows
        arms.append(analyze_arm(rows, name))
    report: Dict[str, Any] = {"generated_from": rdir, "arms": arms,
                              "bootstrap": {"B": B, "seed": RNG_SEED},
                              "real_p50": {str(k): v for k, v in REAL_P50.items()}}

    k_real = next((k for k in data if str(k).startswith("real")), None)
    k_gold = next((k for k in data if str(k).startswith("gold99")
                   and "cap" not in str(k)), None)
    if k_real and k_gold:
        ra = {r["seed"]: r for r in data[k_real]}
        rb = {r["seed"]: r for r in data[k_gold]}
        shared = sorted(set(ra) & set(rb))
        if len(shared) >= 8:
            d_place = np.array([rb[s]["placement"] - ra[s]["placement"] for s in shared],
                               dtype=np.float64)
            d_cast = np.array([rb[s]["casts9"] - ra[s]["casts9"] for s in shared],
                              dtype=np.float64)
            both = [s for s in shared
                    if ra[s]["str12"] is not None and rb[s]["str12"] is not None]
            d_str = np.array([rb[s]["str12"] - ra[s]["str12"] for s in both],
                             dtype=np.float64)

            def _pair(v):
                mu, lo, hi = boot_ci_mean(v)
                return {"n": int(v.size), "mean_delta": round(mu, 3),
                        "ci": [round(lo, 3), round(hi, 3)]}

            report["paired"] = {
                "shared_seeds": len(shared),
                "d_placement": _pair(d_place),
                "d_casts9": _pair(d_cast),
                "d_str12": _pair(d_str),
                "real_arm": k_real, "gold_arm": k_gold,
        "wins_gold": int((d_place < 0).sum()),
                "wins_real": int((d_place > 0).sum()),
                "ties": int((d_place == 0).sum()),
            }

    dose: List[Dict[str, Any]] = []
    for tag in [x.strip() for x in args.dose_tags.split(",") if x.strip()]:
        rows = load_arm(os.path.join(rdir, f"{tag}.jsonl"))
        if not rows:
            continue
        d = describe(rows)
        c = corr_table(rows, (("casts9_utility", "casts9", "utility"),
                              ("casts9_str9", "casts9", "str9"),
                              ("str9_utility", "str9", "utility"),
                              ("ratio9_utility", "ratio9", "utility"),
                              ("casts9_str12", "casts9", "str12")))
        dose.append({"tag": tag, "gold": rows[0]["gold"], "n": len(rows),
                     "casts9_mean": d["casts9_mean"], "casts9_p90": d["casts9_p90"],
                     "casts9_ge5": d["casts9_ge5"],
                     "str9_p50": d["str9_p50"], "str12_p50": d["str12_p50"],
                     "ratio9_p50": d["ratio9_p50"],
                     "opp_mean9_p50": d["opp_mean9_p50"],
                     "rel9_p50": d["rel9_p50"],
                     "carrier9_frac": d["carrier9_frac"],
                     "mean_rank": d["mean_rank"], "top4": d["top4"],
                     "win": d["win"], "mean_utility": d["mean_utility"],
                     "corr_casts_utility": c.get("casts9_utility"),
                     "corr_casts_str9": c.get("casts9_str9"),
                     "corr_str9_utility": c.get("str9_utility"),
                     "corr_ratio9_utility": c.get("ratio9_utility"),
                     "corr_casts_str12": c.get("casts9_str12")})
    if dose:
        dose.sort(key=lambda x: x["gold"])
        report["dose"] = dose

    report["verdict"] = decide_verdict(report)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    md = md_tables(report)
    with open(args.tables, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"\n[out] {args.out}\n[out] {args.tables}")
    if report.get("paired"):
        print("[paired]", json.dumps(report["paired"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
