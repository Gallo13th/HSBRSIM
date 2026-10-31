"""幂率/分数阶资格迹与 **forward advantage** 核（默认关闭；见 docs/CREDIT_ASSIGNMENT.md）。

本模块只提供纯函数，不 import torch / 引擎，CPU 可测。它对应
``docs/RESEARCH_PLAN_V2.md`` §B.1–§B.3：

1. **后向资格迹**（trace，不是 PPO advantage）::

       e_t = Σ_{k=0}^{t} (1 + k/κ)^(−α) γ^k ∇log π(a_{t−k}|s_{t−k})

   ``k`` 是 **lag**（k=0 当前决策），避免「γ^k 随绝对时间改变尺度」的原点歧义。
   后向迹只用于 ``Δθ ∝ δ_t e_t``，**不得**直接当 advantage 传给 PPO。

2. **前向 advantage**（PPO 的 drop-in 替换对象）::

       δ_t = r_t + γ V(s_{t+1}) − V(s_t)
       A_t = Σ_{l=0}^{L_t−1} w̃_l γ^l δ_{t+l}
       w_l = (1 + l/κ)^(−α),  w̃_l = w_l / Σ_{j=0}^{L_t−1} w_j

   它替换的是 GAE 内部的 **时间核 λ^d**，保留 ``V(s)`` critic、γ、reward、
   TD 残差和 terminal/bootstrap/mask。``mode="gae"`` 与旧
   :func:`hsbg.az.train.ppo.compute_gae` 逐位等价（同一递推、float64）。

3. **两个极限**（单测覆盖）：α→0 权重均匀、``N_eff=L``；α→∞ 归一化核→δ_{l0}、
   ``A_t→δ_t``、``N_eff→1``。α 大 **不是** GAE(0.995) 的等价，只是局部几何率
   ``λ_eff≈e^{−α/κ}``。

4. **有效记忆长度**::

       N_eff(t; α, κ) = (Σ_l w_l)² / Σ_l w_l² = 1 / Σ_l w̃_l²

   horizon 归一化（``normalize=True``）让不同 α 的 advantage 尺度可比；GAE 分支
   保持**不归一化**以逐位等价旧路径。

边界约定（与旧 GAE 一致）：
- ``dones[t] > 0.5`` 是 terminal/truncated 边界：该步不 bootstrap，下一段权重重新起算；
- 数组末尾没有 done 的尾段按「无 next value」处理（不给 bootstrap，等价旧路径）；
- ``timebase="decision"``：lag = 决策步数；
- ``timebase="turn"``：lag = **未来 elapsed turn**（``turns[j] − turns[t]``），
  γ^lag 是 SMDP 折扣；同一 turn 的多个动作共享 lag=0 的权重，生产侧应明确是否按
  turn 聚合，禁止把 action-step 与 turn 混用；
- ``cutoff>0``：lag 超过 cutoff 的项直接截断（只在 power/geom 支持；GAE 传 cutoff 报错）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

MODES: Tuple[str, ...] = ("gae", "geom", "power")
TIMEBASES: Tuple[str, ...] = ("decision", "turn")
_EPS = 1e-12


# ══════════════════════════════════════════════════════════════════════════
# 1. 核函数（纯 numpy）
# ══════════════════════════════════════════════════════════════════════════
def _validate_kernel_params(alpha: float, kappa: float, gamma: float,
                            cutoff: int) -> Tuple[float, float, float, int]:
    a = float(alpha)
    k = float(kappa)
    g = float(gamma)
    c = int(cutoff)
    if not math.isfinite(a) or a < 0.0:
        raise ValueError(f"alpha 必须有限且 >= 0，得到 {alpha!r}")
    if not math.isfinite(k) or k <= 0.0:
        raise ValueError(f"kappa 必须有限且 > 0，得到 {kappa!r}")
    if not math.isfinite(g) or not (0.0 < g <= 1.0):
        raise ValueError(f"gamma 必须在 (0, 1]，得到 {gamma!r}")
    if c < 0:
        raise ValueError(f"cutoff 必须 >= 0，得到 {cutoff!r}")
    return a, k, g, c


def power_raw_kernel(length: int, alpha: float, kappa: float,
                     dtype: Any = np.float64) -> np.ndarray:
    """``w_l = (1 + l/κ)^(−α)``（不含 γ、未归一化），``l=0..length-1``。"""
    L = int(length)
    if L < 0:
        raise ValueError(f"length 必须 >= 0，得到 {length!r}")
    a, k, _g, _c = _validate_kernel_params(alpha, kappa, 1.0, 0)
    if L == 0:
        return np.zeros(0, dtype=dtype)
    lag = np.arange(L, dtype=dtype)
    return np.power(1.0 + lag / k, -a)


def geometric_raw_kernel(length: int, lam: float,
                         dtype: Any = np.float64) -> np.ndarray:
    """``w_l = λ^l``（未归一化；不含 γ，γ^l 由调用方另乘）。"""
    L = int(length)
    if L < 0:
        raise ValueError(f"length 必须 >= 0，得到 {length!r}")
    lam = float(lam)
    if not math.isfinite(lam) or not (0.0 <= lam <= 1.0):
        raise ValueError(f"lam 必须在 [0, 1]，得到 {lam!r}")
    if L == 0:
        return np.zeros(0, dtype=dtype)
    return np.power(float(lam), np.arange(L, dtype=dtype))


def trace_weights(length: int, alpha: float, kappa: float,
                  gamma: float = 1.0) -> np.ndarray:
    """后向资格迹的 lag 权重 ``(1+k/κ)^(−α) γ^k``（k=0 当前决策）。

    它**不是** advantage：``e_t = Σ_k trace_weights[k] · ∇logπ(a_{t−k}|s_{t−k})``，
    只用于 actor-critic 的 ``Δθ ∝ δ_t e_t`` 更新；PPO 的 forward advantage 用
    :func:`compute_credit`。单独乘回报/优势才构成 REINFORCE 型更新。
    """
    a, k, g, _c = _validate_kernel_params(alpha, kappa, gamma, 0)
    L = int(length)
    if L < 0:
        raise ValueError(f"length 必须 >= 0，得到 {length!r}")
    if L == 0:
        return np.zeros(0, dtype=np.float64)
    lag = np.arange(L, dtype=np.float64)
    return np.power(1.0 + lag / k, -a) * np.power(g, lag)


def horizon_normalize(weights: Any) -> np.ndarray:
    """归一化到和=1；空/非有限/和为 0 时返回零数组（不产生 NaN）。"""
    w = np.asarray(weights, dtype=np.float64).reshape(-1)
    if w.size == 0:
        return w.astype(np.float64)
    if not np.all(np.isfinite(w)):
        raise ValueError("kernel 权重含非有限值")
    s = float(w.sum())
    if s <= 0.0:
        return np.zeros_like(w)
    return w / s


def kernel_weights(length: int, mode: str, *, alpha: float = 0.5,
                   kappa: float = 3.0, lam: float = 0.995, gamma: float = 1.0,
                   cutoff: int = 0, normalize: bool = True) -> np.ndarray:
    """一维 lag 核 ``w_l``（含可选 γ^l 与 horizon 归一化）。"""
    m = str(mode).strip().lower()
    if m not in ("power", "geom"):
        raise ValueError(f"kernel_weights 只支持 power|geom，得到 {mode!r}")
    _a, _k, g, c = _validate_kernel_params(alpha, kappa, gamma, cutoff)
    L = int(length)
    if L < 0:
        raise ValueError(f"length 必须 >= 0，得到 {length!r}")
    if L == 0:
        return np.zeros(0, dtype=np.float64)
    max_l = L if c <= 0 else min(L, c)
    if m == "power":
        w = power_raw_kernel(max_l, alpha, kappa)
    else:
        w = geometric_raw_kernel(max_l, lam)
    if normalize:
        w = horizon_normalize(w)
    return w * np.power(g, np.arange(max_l, dtype=np.float64))


def effective_sample_size(weights: Any) -> float:
    """``N_eff = 1 / Σ w̃²``；输入会被归一化（全零/空 -> 0.0，不产生 NaN）。"""
    w = horizon_normalize(weights)
    if w.size == 0:
        return 0.0
    denom = float(np.dot(w, w))
    if denom <= 0.0:
        return 0.0
    return 1.0 / denom


# ══════════════════════════════════════════════════════════════════════════
# 2. advantage 计算
# ══════════════════════════════════════════════════════════════════════════
def _as_1d(name: str, x: Any) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64).reshape(-1)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含非有限值（NaN/Inf）")
    return arr


def _episode_segments(dones: np.ndarray) -> Iterable[Tuple[int, int]]:
    """按 ``done>0.5`` 切段，返回 ``[start, end)``；末尾无 done 的尾段也算一段。"""
    n = int(dones.size)
    start = 0
    for t in range(n):
        if dones[t] > 0.5:
            yield start, t + 1
            start = t + 1
    if start < n:
        yield start, n


def _lags_for_segment(t: int, end: int, *, timebase: str,
                      turns: Optional[np.ndarray],
                      duration: Optional[np.ndarray]) -> np.ndarray:
    """从决策 t 到段内未来每个决策的 lag 数组（长度 end-t）。"""
    H = end - t
    if timebase == "decision":
        if duration is None:
            return np.arange(H, dtype=np.float64)
        d = np.asarray(duration[t:end], dtype=np.float64)
        return np.concatenate([[0.0], np.cumsum(d)[:-1]])
    if duration is not None:
        d = np.asarray(duration[t:end], dtype=np.float64)
        return np.concatenate([[0.0], np.cumsum(d)[:-1]])
    if turns is None:
        raise ValueError("timebase='turn' 需要 turns（每决策所处 turn）或 duration")
    lag = np.asarray(turns[t:end], dtype=np.float64) - float(turns[t])
    if np.any(lag < 0.0):
        raise ValueError("turns 在 episode 内必须非降（timebase='turn'）")
    return lag


def compute_credit(rewards: Any, values: Any, dones: Any, *,
                   mode: str = "gae", gamma: float = 1.0, lam: float = 0.995,
                   alpha: float = 0.5, kappa: float = 3.0, cutoff: int = 0,
                   normalize: Optional[bool] = None,
                   timebase: str = "decision",
                   turns: Any = None, duration: Any = None
                   ) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """计算 advantage / returns 与诊断（纯函数）。

    参数
    ----
    rewards, values, dones : 1-D，按 episode 连续排列（同 ``compute_gae``）。
    mode : ``"gae"``（逐位等价旧路径）| ``"geom"``（λ^l 对照）| ``"power"``（幂率核）。
    gamma, lam : 与旧 GAE 一致；``lam`` 只用于 gae/geom。
    alpha, kappa : 幂率核参数（``alpha>=0``、``kappa>0``）。
    cutoff : lag 截断（0=不截断）；gae 模式传 >0 会报错。
    normalize : horizon 归一化；默认 gae=False、geom=False、power=True。
    timebase : ``decision`` | ``turn``。
    turns : timebase='turn' 时必须给（每决策 turn，段内非降）。
    duration : 可选逐决策持续时间（SMDP）；给定时 lag 用累计 duration。

    返回
    ----
    advantages : float32[n]（旧 GAE 路径保留 float32 输出）
    returns : float32[n] = advantages + values
    diagnostics : dict（标量 + 逐步 ``ess``/``terminal_share`` 数组）

    说明
    ----
    ``mode="gae"`` 直接走与 ``ppo.compute_gae`` **相同的 float64 递推**；不 import
    ppo，避免循环依赖，由 ``tests/test_credit.py`` 断言逐元素相等。
    """
    m = str(mode).strip().lower()
    if m not in MODES:
        raise ValueError(f"mode 必须是 {MODES} 之一，得到 {mode!r}")
    tb = str(timebase).strip().lower()
    if tb not in TIMEBASES:
        raise ValueError(f"timebase 必须是 {TIMEBASES} 之一，得到 {timebase!r}")
    g = float(gamma)
    if not math.isfinite(g) or not (0.0 < g <= 1.0):
        raise ValueError(f"gamma 必须在 (0, 1]，得到 {gamma!r}")
    lam_f = float(lam)
    if not math.isfinite(lam_f) or not (0.0 <= lam_f <= 1.0):
        raise ValueError(f"lam 必须在 [0, 1]，得到 {lam!r}")
    c = int(cutoff)
    if c < 0:
        raise ValueError(f"cutoff 必须 >= 0，得到 {cutoff!r}")
    if normalize is None:
        normalize = (m == "power")
    normalize = bool(normalize)
    if m == "gae":
        if c > 0:
            raise ValueError("mode='gae' 不支持 cutoff（要保持与旧 compute_gae 逐位等价）")
        if normalize:
            raise ValueError("mode='gae' 不支持 normalize=True（旧 GAE 不归一化）")

    r = _as_1d("rewards", rewards)
    v = _as_1d("values", values)
    d = _as_1d("dones", dones)
    if not (r.shape == v.shape == d.shape):
        raise ValueError(f"rewards/values/dones 形状不一致: {r.shape}/{v.shape}/{d.shape}")
    n = int(r.size)
    if n == 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, empty, {
            "mode": m, "n": 0, "n_episodes": 0, "gamma": g, "lam": lam_f,
            "alpha": float(alpha), "kappa": float(kappa), "cutoff": c,
            "normalize": normalize, "timebase": tb,
            "ess": np.zeros(0, dtype=np.float64),
            "terminal_share": np.zeros(0, dtype=np.float64),
            "terminal_weight": np.zeros(0, dtype=np.float64),
            "mean_abs_adv": 0.0, "adv_std": 0.0, "adv_var": 0.0,
        }

    if m == "gae":
        if tb != "decision":
            raise ValueError("mode='gae' 只支持 timebase='decision'（旧 GAE 是 action-step）")
        adv, ret, ess_all, share_all, tw_all = _compute_gae_like(r, v, d, g, lam_f)
        return adv, ret, _summarize(
            mode=m, adv=adv, ess=ess_all, share=share_all, term_w=tw_all,
            gamma=g, lam=lam_f, alpha=float(alpha), kappa=float(kappa),
            cutoff=c, normalize=False, timebase=tb,
            n_episodes=len(list(_episode_segments(d))))

    a, k, _g, _c = _validate_kernel_params(alpha, kappa, g, c)
    turn_arr = None if turns is None else np.asarray(turns, dtype=np.float64).reshape(-1)
    if turn_arr is not None and turn_arr.size != n:
        raise ValueError(f"turns 形状应为 ({n},)，得到 {turn_arr.shape}")
    dur_arr = None if duration is None else np.asarray(duration, dtype=np.float64).reshape(-1)
    if dur_arr is not None:
        if dur_arr.size != n:
            raise ValueError(f"duration 形状应为 ({n},)，得到 {dur_arr.shape}")
        if np.any(dur_arr < 0.0):
            raise ValueError("duration 不能为负")
    if tb == "turn" and turn_arr is None and dur_arr is None:
        raise ValueError("timebase='turn' 需要 turns 或 duration")

    adv64, ess_all, share_all, tw_all = _compute_kernel_advantages(
        r, v, d, mode=m, gamma=g, lam=lam_f, alpha=a, kappa=k, cutoff=c,
        normalize=normalize, timebase=tb, turns=turn_arr, duration=dur_arr)
    adv = adv64.astype(np.float32)
    ret = (adv.astype(np.float64) + v).astype(np.float32)
    n_episodes = len(list(_episode_segments(d)))
    return adv, ret, _summarize(
        mode=m, adv=adv, ess=ess_all, share=share_all, term_w=tw_all,
        gamma=g, lam=lam_f, alpha=a, kappa=k, cutoff=c, normalize=normalize,
        timebase=tb, n_episodes=n_episodes)


def _compute_gae_like(r: np.ndarray, v: np.ndarray, d: np.ndarray,
                      gamma: float, lam: float):
    """与 ``ppo.compute_gae`` 完全相同的递推；额外产出 ess/terminal share。

    逐位等价条件：同一 float64 运算顺序、末步 done 不 bootstrap、越界 next_value=0。
    """
    n = int(r.size)
    adv = np.zeros(n, dtype=np.float64)
    ess = np.zeros(n, dtype=np.float64)
    share = np.zeros(n, dtype=np.float64)
    tw = np.zeros(n, dtype=np.float64)
    last_adv = 0.0
    next_value = 0.0
    for t in range(n - 1, -1, -1):
        if d[t] > 0.5:
            next_value = 0.0
            last_adv = 0.0
        delta = float(r[t]) + float(gamma) * next_value - float(v[t])
        last_adv = delta + float(gamma) * float(lam) * last_adv
        adv[t] = last_adv
        next_value = float(v[t])

    # 逐段统计：GAE 未归一化，终端项 = (γλ)^{end-1-t} * δ_end
    for start, end in _episode_segments(d):
        H = end - start
        seg_delta = np.zeros(H, dtype=np.float64)
        for i in range(H):
            t = start + i
            nxt = float(v[t + 1]) if t + 1 < end else 0.0
            seg_delta[i] = float(r[t]) + float(gamma) * nxt - float(v[t])
        for t in range(start, end):
            H_t = end - t
            w = np.power(float(gamma) * float(lam), np.arange(H_t, dtype=np.float64))
            wn = w / max(float(w.sum()), _EPS)
            denom = float(np.dot(wn, wn))
            ess[t] = (1.0 / denom) if denom > 0 else 0.0
            term = float(w[-1]) * float(seg_delta[-1])
            share[t] = abs(term) / max(abs(adv[t]), _EPS)
            tw[t] = float(w[-1] / max(float(w.sum()), _EPS))
    return adv.astype(np.float32), (adv.astype(np.float64) + v).astype(np.float32), ess, share, tw


def _compute_kernel_advantages(r: np.ndarray, v: np.ndarray, d: np.ndarray, *,
                               mode: str, gamma: float, lam: float,
                               alpha: float, kappa: float, cutoff: int,
                               normalize: bool, timebase: str,
                               turns: Optional[np.ndarray],
                               duration: Optional[np.ndarray]):
    n = int(r.size)
    adv = np.zeros(n, dtype=np.float64)
    ess = np.zeros(n, dtype=np.float64)
    share = np.zeros(n, dtype=np.float64)
    tw = np.zeros(n, dtype=np.float64)
    for start, end in _episode_segments(d):
        H = end - start
        delta = np.zeros(H, dtype=np.float64)
        for i in range(H):
            t = start + i
            nxt = float(v[t + 1]) if t + 1 < end else 0.0
            delta[i] = float(r[t]) + float(gamma) * nxt - float(v[t])
        for i in range(H):
            t = start + i
            lag = _lags_for_segment(t, end, timebase=timebase, turns=turns,
                                    duration=duration)
            orig_H = int(lag.size)
            H_t = orig_H
            if cutoff > 0:
                keep = lag <= float(cutoff)
                if not bool(keep[0]):
                    keep[0] = True
                lag = lag[keep]
                H_t = int(lag.size)
            if mode == "power":
                w = np.power(1.0 + lag / kappa, -alpha)
            else:
                w = np.power(float(lam), lag)
            wsum = float(w.sum())
            if wsum <= 0.0 or not math.isfinite(wsum):
                adv[t] = 0.0
                ess[t] = 0.0
                share[t] = 0.0
                continue
            disc = np.power(float(gamma), lag)
            num = float(np.dot(w * disc, delta[i:i + H_t]))
            a = (num / wsum) if normalize else num
            adv[t] = a
            wnorm = w / wsum
            ess[t] = 1.0 / max(float(np.dot(wnorm, wnorm)), _EPS)
            # 终端项：仅当 cutoff 没有截掉段末（H_t == orig_H）时存在
            if H_t == orig_H:
                term = float(w[-1] * disc[-1] * delta[-1])
                share[t] = abs(term) / max(abs(a), _EPS)
                tw[t] = float(w[-1] / wsum)
            else:
                share[t] = 0.0
                tw[t] = 0.0
    return adv, ess, share, tw


def _summarize(*, mode: str, adv: np.ndarray, ess: np.ndarray,
               share: np.ndarray, term_w: np.ndarray, gamma: float, lam: float,
               alpha: float, kappa: float, cutoff: int, normalize: bool,
               timebase: str, n_episodes: int) -> Dict[str, Any]:
    a = np.asarray(adv, dtype=np.float64)
    mean_abs = float(np.mean(np.abs(a))) if a.size else 0.0
    var = float(np.var(a)) if a.size else 0.0
    return {
        "mode": mode, "n": int(a.size), "n_episodes": int(n_episodes),
        "gamma": float(gamma), "lam": float(lam), "alpha": float(alpha),
        "kappa": float(kappa), "cutoff": int(cutoff), "normalize": bool(normalize),
        "timebase": timebase,
        "ess": np.asarray(ess, dtype=np.float64),
        "terminal_share": np.asarray(share, dtype=np.float64),
        "terminal_weight": np.asarray(term_w, dtype=np.float64),
        "mean_abs_adv": mean_abs, "adv_std": float(math.sqrt(var)),
        "adv_var": var, "mean_adv": float(np.mean(a)) if a.size else 0.0,
        "ess_mean": float(np.mean(ess)) if ess.size else 0.0,
        "ess_median": float(np.median(ess)) if ess.size else 0.0,
        "terminal_share_median": (float(np.median(share)) if share.size else 0.0),
    }


def compact_diagnostics(diag: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """去掉逐决策大数组，只留可写入 records/meta 的标量/分位数。"""
    if not diag:
        return {}
    out: Dict[str, Any] = {}
    for key, val in diag.items():
        if isinstance(val, np.ndarray):
            if val.size == 0:
                continue
            q = np.quantile(np.asarray(val, dtype=np.float64), [0.1, 0.5, 0.9])
            out[f"{key}_p10"] = float(q[0])
            out[f"{key}_p50"] = float(q[1])
            out[f"{key}_p90"] = float(q[2])
        elif isinstance(val, (int, float, bool, str)):
            out[key] = val
    return out


__all__ = [
    "MODES", "TIMEBASES", "power_raw_kernel", "geometric_raw_kernel",
    "trace_weights", "horizon_normalize", "kernel_weights",
    "effective_sample_size", "compute_credit", "compact_diagnostics",
]
