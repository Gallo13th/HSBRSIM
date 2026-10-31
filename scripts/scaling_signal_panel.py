#!/usr/bin/env python3
"""逐回合面板（面板内固定效应）分析：**一次施法到底换来多少身材？**

为什么需要它：跨局相关（``scripts/scaling_signal_analysis.py``）里，施法与身材/名次都可能
被「这一局运气好不好」共同驱动。这里改用**局内面板**：

    对每一局、每一回合 t（1..T），取增量
        Δcasts_t  = 累计施法(t) - 累计施法(t-1)
        Δstr_t    = 战团 Σ(t)   - 战团 Σ(t-1)
    然后做**局内去均值**（等价于加 game fixed effects）的 OLS：
        Δstr_t - mean_game(Δstr) = b * (Δcasts_t - mean_game(Δcasts)) + e

``b`` 就是「多施放 1 次法术，当回合战团多长多少身材」——局内比较自动消掉大厅强度、
种子配牌等所有「局级」混杂。bootstrap 按**局**重采样（cluster bootstrap）。

也报告同一口径下的「每回合酒馆永久 buff 触发」「金色生成」对身材的贡献。

用法::

  python scripts/scaling_signal_panel.py --dir runs/scaling_signal \
      --arms real,gold99,gold99_cap120,dose_g12,dose_g15,dose_g20,dose_g30,dose_g50,dose_g99
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

B = 4000
SEED = 20261031


def load_panel(path: str) -> Tuple[List[Tuple[float, float, float, float, float, float]], List[int]]:
    """返回 (obs, game_sizes)：obs=(turn, d_casts, d_str, d_golden, d_tavern, d_bought)。"""
    obs: List[Tuple[float, float, float, float, float, float]] = []
    sizes: List[int] = []
    if not os.path.isfile(path):
        return obs, sizes
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            te = [t for t in (r.get("turns") or []) if t.get("stage") == "recruit_end"]
            if not te or int(r.get("placement") or 0) <= 0:
                continue
            prev = {"tavern_spells_cast": 0.0, "golden_played": 0.0,
                    "tavern": 0.0, "minions_bought": 0.0}
            prev_str = 0.0
            n0 = len(obs)
            for t in te:
                st = t.get("stats") or {}
                casts = float(st.get("tavern_spells_cast", 0) or 0)
                golden = float(st.get("golden_played", 0) or 0)
                tavern = float(st.get("tavern_atk", 0) or 0) + float(st.get("tavern_hp", 0) or 0)
                bought = float(st.get("minions_bought", 0) or 0)
                s = float(t.get("strength") or 0)
                obs.append((float(t["turn"]), casts - prev["tavern_spells_cast"],
                            s - prev_str, golden - prev["golden_played"],
                            tavern - prev["tavern"], bought - prev["minions_bought"]))
                prev = {"tavern_spells_cast": casts, "golden_played": golden,
                        "tavern": tavern, "minions_bought": bought}
                prev_str = s
            if len(obs) > n0:
                sizes.append(len(obs) - n0)
    return obs, sizes


def _within(x: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """按组去均值。"""
    out = np.empty_like(x)
    for g in np.unique(groups):
        m = groups == g
        out[m] = x[m] - x[m].mean()
    return out


def panel_slope(obs: np.ndarray, sizes: List[int], xcol: int, *, B: int = B,
                seed: int = SEED) -> Dict[str, Any]:
    """局内去均值 OLS：Δstr ~ Δx（game FE）；cluster bootstrap（按局）。"""
    n_games = len(sizes)
    if n_games < 8:
        return {"n_games": n_games, "slope": None}
    groups = np.repeat(np.arange(n_games), sizes)
    y = _within(obs[:, 2], groups)
    x = _within(obs[:, xcol], groups)
    denom = float((x * x).sum())
    if denom <= 0:
        return {"n_games": n_games, "slope": None, "note": "x 全为 0"}
    b = float((x * y).sum() / denom)
    # 局内 R²（含局固定效应）
    resid = y - b * x
    ss_res = float((resid ** 2).sum())
    ss_tot = float((y ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rng = np.random.default_rng(seed)
    bs = []
    starts = np.concatenate([[0], np.cumsum(sizes)])
    xg = [x[starts[i]:starts[i + 1]] for i in range(n_games)]
    yg = [y[starts[i]:starts[i + 1]] for i in range(n_games)]
    for _ in range(B):
        pick = rng.integers(0, n_games, size=n_games)
        xb = np.concatenate([xg[i] for i in pick])
        yb = np.concatenate([yg[i] for i in pick])
        d = float((xb * xb).sum())
        if d > 0:
            bs.append(float((xb * yb).sum() / d))
    bs = np.array(bs, dtype=np.float64)
    lo, hi = (np.percentile(bs, [2.5, 97.5]) if bs.size else (float("nan"), float("nan")))
    return {"n_games": n_games, "n_obs": int(obs.shape[0]),
            "slope": round(b, 4), "ci": [round(float(lo), 4), round(float(hi), 4)],
            "r2_within": round(float(r2), 4),
            "mean_dx": round(float(obs[:, xcol].mean()), 3),
            "sd_dx": round(float(obs[:, xcol].std()), 3),
            "mean_dstr": round(float(obs[:, 2].mean()), 3)}


def panel_multi(obs: np.ndarray, sizes: List[int], xcol: int, ctl: int, *,
                B: int = B, seed: int = SEED) -> Dict[str, Any]:
    """局内去均值 OLS：Δstr ~ Δx + Δctl（二元），返回 Δx 的系数与 cluster bootstrap CI。

    用途：把「这一回合有钱/动作多」的机械混杂（用 Δbought=本回合买牌数 代理）扣掉，
    剩下的系数才是「同样买牌量下，多施放一次法术」的身材增量。
    """
    n_games = len(sizes)
    if n_games < 8:
        return {"n_games": n_games, "coef": None}
    groups = np.repeat(np.arange(n_games), sizes)
    y = _within(obs[:, 2], groups)
    X = np.column_stack([_within(obs[:, xcol], groups), _within(obs[:, ctl], groups)])
    starts = np.concatenate([[0], np.cumsum(sizes)])

    def _fit(yy: np.ndarray, XX: np.ndarray) -> float:
        try:
            beta, *_ = np.linalg.lstsq(XX, yy, rcond=None)
        except BaseException:  # noqa: BLE001
            return float("nan")
        return float(beta[0])

    coef = _fit(y, X)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(B):
        pick = rng.integers(0, n_games, size=n_games)
        yb = np.concatenate([y[starts[i]:starts[i + 1]] for i in pick])
        Xb = np.vstack([X[starts[i]:starts[i + 1]] for i in pick])
        if np.linalg.matrix_rank(Xb) < 2:
            continue
        bs.append(_fit(yb, Xb))
    bs = np.array([b for b in bs if np.isfinite(b)], dtype=np.float64)
    lo, hi = (np.percentile(bs, [2.5, 97.5]) if bs.size else (float("nan"), float("nan")))
    return {"n_games": n_games, "n_obs": int(obs.shape[0]),
            "slope": round(coef, 4) if np.isfinite(coef) else None,
            "coef": round(coef, 4) if np.isfinite(coef) else None,
            "ci": [round(float(lo), 4), round(float(hi), 4)], "control": "bought"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="runs/scaling_signal")
    ap.add_argument("--arms", default="real,gold99,gold99_cap120")
    ap.add_argument("--out", default="runs/scaling_signal/panel.json")
    args = ap.parse_args()
    rdir = os.path.join(args.dir, "rollouts")
    rows: List[Dict[str, Any]] = []
    for name in [x.strip() for x in args.arms.split(",") if x.strip()]:
        obs_l, sizes = load_panel(os.path.join(rdir, f"{name}.jsonl"))
        if not obs_l:
            continue
        obs = np.asarray(obs_l, dtype=np.float64)
        rows.append({
            "arm": name,
            "casts_per_turn": round(float(obs[:, 1].mean()), 3),
            "casts_per_turn_p90": round(float(np.percentile(obs[:, 1], 90)), 3),
            "dstr_per_turn": round(float(obs[:, 2].mean()), 2),
            "str_per_cast": panel_slope(obs, sizes, 1),
            "str_per_golden": panel_slope(obs, sizes, 3),
            "str_per_tavern_buff": panel_slope(obs, sizes, 4),
            "str_per_bought": panel_slope(obs, sizes, 5),
            "str_per_cast_ctrl_bought": panel_multi(obs, sizes, 1, 5),
        })
    out = {"panel": rows, "note": "局内去均值 OLS（game fixed effects）；Δ 为逐回合增量；"
                                  "bootstrap 按局重采样"}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    L = ["### 局内面板（game fixed effects）：每单位行为换来多少身材\n",
         "| arm | 每回合施法 | 每回合 ΔΣ | **每次施法 → Σ** | 每次施法 → Σ<br>(控制买牌数) | 每个金色 → Σ | 每点酒馆 buff → Σ | 每买 1 张 → Σ |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        def f(d: Dict[str, Any]) -> str:
            if not d or d.get("slope") is None:
                return "n/a"
            lo, hi = d["ci"]
            return f"{d['slope']:+.2f} [{lo:+.2f},{hi:+.2f}]"
        L.append(f"| {r['arm']} | {r['casts_per_turn']} (p90 {r['casts_per_turn_p90']}) | "
                 f"{r['dstr_per_turn']} | {f(r['str_per_cast'])} | "
                 f"{f(r['str_per_cast_ctrl_bought'])} | {f(r['str_per_golden'])} | "
                 f"{f(r['str_per_tavern_buff'])} | {f(r['str_per_bought'])} |")
    L.append("")
    md = "\n".join(L)
    with open(os.path.join(args.dir, "panel.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
