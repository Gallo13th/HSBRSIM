"""搜索作为行为策略的 PPO：决策级混合行为策略 ``μ=(1−ε)π+ε·π_search``。

## 为什么必须写 μ

推理期搜索（``infer_search.InferSearcher``，t6 口径：1 回合叶值 / top-8 /
carrier_or_spell / 每回合 ≤6）已经被证明能在**开启搜索时**改善名次
（`docs/INFERENCE_SEARCH.md`）。要把这份能力的**状态分布**学回策略，第二条路线
（第一条 ExIt 蒸馏触到 KL 上限即停，见 `docs/SEARCH_EXIT.md`）是把搜索直接放进
**行为策略**：在关键决策点以概率 ``ε`` 从 ``π_search`` 采样、否则从 ``π`` 采样。

这样轨迹的真实采样分布是

.. math::

    \\mu_{\\theta_{old}}(a\\mid s) = (1-\\varepsilon)\\,\\pi_{\\theta_{old}}(a\\mid s)
        + \\varepsilon\\,\\pi_S(a\\mid s),

它才是 behavior policy，``π`` **不是** on-policy 分布。PPO 的重要性比必须是

.. math::

    r_t(\\theta) = \\frac{\\pi_\\theta(a_t\\mid s_t)}
                        {\\mu_{\\theta_{old}}(a_t\\mid s_t)},

用 ``π_old`` 当分母会得到 ``E_{a~μ}[(π/π_old)Â] ≠ E_{a~π}[Â]``，偏差随 ``ε`` 与
``KL(π_S‖π)`` 增大（`docs/SEARCH_DISTILL_THEORY.md` §4.5）。

因此本模块负责三件事：

1. **触发**：关键决策（``search_when``）+ 每回合搜索上限 + ``ε`` 概率 + 排除
   ``forced``（环境确定性守卫）决策；
2. **计算** ``π``（与采集采样完全同一套 masked softmax / 温度）、跑搜索拿
   ``π_search``、按 ``μ`` 采样动作，并给出该动作在 ``μ`` 与 ``π`` 下的精确 log 概率；
3. **统计**：``ε`` 命中率、搜索覆盖率、``KL(μ‖π)``、搜索耗时，供
   ``--behavior-mix-report`` 落盘。

## ε=0 的严格等价

``eps<=0`` 时调用方根本不会构造 :class:`BehaviorMixer`（``CollectConfig.behavior_mix_eps``
默认 0），``PPOSelfPlayPolicy`` 里只有 ``self._mix is None`` 一次判空 → 不抽 RNG、
不加 record 字段、不改 mask/动作/logprob，采集与 PPO 通路与旧版本逐位一致。

## 方差

``μ ≥ ε π_S`` ⇒ ``r ≤ π_θ/(ε π_S)``。``π_S`` 近 one-hot（``pi_argmax`` 派生）时搜索
分支权重 ~``1/ε``，IS 二阶矩按 ``1/ε²`` 放大，ESS 随 ``ε`` 下降 —— 所以 ``ε`` 取
0.1–0.3（本实验 0.2），并在 PPO 侧逐 update 报 ESS / 权重分位 / max r。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .common import N_ACTIONS
from .ppo import LOGPROB_FLOOR, masked_probs_np
from .sandbox_rollout import search_when_names, tag_matches

#: ``KL(μ‖π)`` 分位数用的环形缓冲上限（只影响统计内存，不影响训练）。
_KL_CAP = 8192
_MS_CAP = 8192


# ══════════════════════════════════════════════════════════════════════════
# 纯函数：μ 的分布 / logprob / KL（单测直接手算对照）
# ══════════════════════════════════════════════════════════════════════════
def _as_dist(x: Any) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64).reshape(-1)
    if a.size != N_ACTIONS:
        raise ValueError(f"分布维度必须是 {N_ACTIONS}，得到 {a.size}")
    if not np.all(np.isfinite(a)):
        raise ValueError("分布含 NaN/Inf")
    return np.maximum(a, 0.0)


def mix_distribution(pi: Any, pi_search: Any, eps: float) -> np.ndarray:
    """``μ = (1−ε)π + ε π_search``（两者都应是 masked 归一分布）。

    返回 f64[245]，和 = 1（只在浮点漂移 ``|Σ-1|>1e-9`` 时重归一，正常情况下
    逐位等于加权和，便于手算对照）。
    """
    pi_a = _as_dist(pi)
    ps_a = _as_dist(pi_search)
    e = float(eps)
    if not (0.0 <= e < 1.0):
        raise ValueError(f"eps 必须在 [0,1)，得到 {eps!r}")
    mu = (1.0 - e) * pi_a + e * ps_a
    s = float(mu.sum())
    if not math.isfinite(s) or s <= 0.0:
        raise ValueError("μ 的支撑为空（π 与 π_search 都不含概率质量）")
    if abs(s - 1.0) > 1e-9:
        mu = mu / s
    return mu


def mu_logprob(pi: Any, pi_search: Any, eps: float, action: int) -> float:
    """``log μ(a) = log((1−ε)π(a) + ε π_search(a))``（不做重归一，直接按定义）。"""
    a = int(action)
    if not (0 <= a < N_ACTIONS):
        raise ValueError(f"动作下标越界: {action}")
    pi_a = _as_dist(pi)
    ps_a = _as_dist(pi_search)
    e = float(eps)
    if not (0.0 <= e < 1.0):
        raise ValueError(f"eps 必须在 [0,1)，得到 {eps!r}")
    p = (1.0 - e) * float(pi_a[a]) + e * float(ps_a[a])
    return float(math.log(max(p, LOGPROB_FLOOR)))


def kl_mu_pi(mu: Any, pi: Any) -> float:
    """``KL(μ‖π) = Σ_a μ(a) log(μ(a)/π(a))``；π(a)=0 而 μ(a)>0 → ``inf``。"""
    mu_a = _as_dist(mu)
    pi_a = _as_dist(pi)
    s = float(mu_a.sum())
    if s <= 0.0:
        raise ValueError("μ 的支撑为空")
    mu_a = mu_a / s
    nz = mu_a > 0.0
    if bool((pi_a[nz] <= 0.0).any()):
        return float("inf")
    return float(np.sum(mu_a[nz] * np.log(mu_a[nz] / pi_a[nz])))


# ══════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class BehaviorMixConfig:
    """混合行为策略的配置（默认 ``eps=0`` = 完全关闭）。"""

    #: 关键决策以该概率改用 π_search 采样；0 = 关闭（逐位等价旧路径）
    eps: float = 0.0
    #: 关键决策口径（``sandbox_rollout.SEARCH_WHEN_NAMES``；可逗号组合）
    when: str = "carrier_or_spell"
    #: 每回合最多搜索几次（0 = 不限；默认 6，与 t6 配置一致）
    max_per_turn: int = 6
    #: 根候选数 = π top-k（非 Move 合法动作）
    topk: int = 8
    #: 叶值 horizon（1 = 本回合末；沿用 s17 的 t1 口径）
    turns: int = 1
    #: 单次搜索墙钟上限 ms（0 = 不限）；超时放弃搜索、回退按 π 采样
    max_ms: float = 500.0
    #: 搜索侧 RNG 基准种子（逐进程派生；同 seed 可复现）
    seed: int = 0
    #: 精确模式（默认 1）：**每个**关键决策都跑搜索（从而 π_S 已知），动作按 ε 分支
    #: 从 π_S / π 采样，logp_mu = log μ(a) 对**所有**关键决策精确成立。这样 PPO 的
    #: IS 比 π/μ 在两种分支上都精确（E_μ[r·f]=E_π[f]，权重 ≤ 1/(1−ε)）。
    #: 0 = 省钱模式：只在 ε 命中时搜索，未命中决策的行为是 π（logp_mu=logp_pi），
    #: 等价于把「分支」当作状态的一部分；搜索成本降到 ~ε 倍，但「μ 是行为策略」
    #: 只在命中决策上成立（跨分支不再等价于 marginal μ，见 docs 的偏差说明）。
    exact: int = 1

    def validate(self) -> "BehaviorMixConfig":
        e = float(self.eps)
        if not (0.0 <= e < 1.0):
            raise ValueError(f"behavior_mix_eps 必须在 [0,1)，得到 {self.eps!r}")
        if int(self.max_per_turn) < 0:
            raise ValueError("behavior_mix_max_per_turn 必须 >= 0（0 = 不限）")
        if int(self.topk) < 2:
            raise ValueError("behavior_mix_topk 必须 >= 2")
        if int(self.turns) < 1:
            raise ValueError("behavior_mix_turns 必须 >= 1")
        if float(self.max_ms) < 0.0:
            raise ValueError("behavior_mix_max_ms 必须 >= 0（0 = 不限）")
        if int(self.exact) not in (0, 1):
            raise ValueError("behavior_mix_exact 只能是 0/1")
        search_when_names(str(self.when))     # 触发口径校验
        return self


# ══════════════════════════════════════════════════════════════════════════
# 结果
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class MixOutcome:
    """一次混合决策的结果：动作 + 两个 logprob（都对应**同一个**动作）。"""

    action: int
    #: log μ(a) = log((1−ε)π(a)+ε π_search(a))
    logp_mu: float
    #: log π(a)（π_old 下该动作的 log 概率；PPO 的 KL/approx_kl 用它）
    logp_pi: float
    #: KL(μ‖π)（该状态）
    kl_mu_pi: float
    #: 搜索耗时（含 π 前向；ms）
    elapsed_ms: float
    #: π_search 的 top-1 是否与 π 的 argmax 不同
    switched: bool = False
    #: 该动作是否由 π_search 采样（False = 由 π 采样；两种情况下 logp_mu 都可能 ≠ logp_pi）
    used_search: bool = False


# ══════════════════════════════════════════════════════════════════════════
# 混合器
# ══════════════════════════════════════════════════════════════════════════
class BehaviorMixer:
    """在 lockstep/逐局采集的每个 learner 决策点上按 μ 混合搜索。

    ``searcher`` 必须是 :class:`hsbg.az.train.infer_search.InferSearcher`
    （提供 ``tags`` / ``search`` / ``prior_batch`` 与 ``evaluator``）。
    """

    def __init__(self, searcher: Any, cfg: BehaviorMixConfig, *,
                 n_players: int = 8) -> None:
        self.searcher = searcher
        self.cfg = cfg.validate()
        self._when = search_when_names(str(self.cfg.when))
        self.n_players = int(n_players)
        self.reset()

    # ── 生命周期 ────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return float(self.cfg.eps) > 0.0

    def reset(self) -> None:
        """每次 collect 前清计数（统计按 iteration 归零）。"""
        self._turn_searched: Dict[tuple, int] = {}
        self.n_decisions = 0
        self.n_eligible = 0
        self.n_eps_hits = 0
        self.n_searched = 0
        self.n_from_search = 0
        self.n_failed = 0
        self.n_cap_skipped = 0
        self.n_switched = 0
        self._kl: List[float] = []
        self._ms: List[float] = []
        self._bytes = 0
        # 搜索器跨 collect 复用时，本次 iteration 的增量（累计值没有归零语义）
        self._calls0 = int(getattr(self.searcher, "calls", 0) or 0)
        self._timeouts0 = int(getattr(self.searcher, "timeouts", 0) or 0)

    # ── π（与采集采样同一套 masked softmax / 温度）───────────────────────
    def policy_probs(self, f: np.ndarray, c: np.ndarray, mask: np.ndarray,
                     temperature: float = 1.0) -> np.ndarray:
        """当前策略在 ``(f, c, mask)`` 上的 π（f64[245]，和 = 1）。

        优先走 ``searcher.evaluator.logits``（与 ``PPOEvaluator.act`` 的
        ``masked_probs_np(logits, mask, T)`` 完全同一套）；没有 ``logits`` 接口时
        退回 ``InferSearcher.prior_batch``（T=1）再按温度重标。
        """
        m = np.asarray(mask, dtype=bool).reshape(-1)
        ev = getattr(self.searcher, "evaluator", None)
        logits_fn = getattr(ev, "logits", None)
        if logits_fn is not None:
            plog, _rlog = logits_fn(np.asarray(f, np.float32).reshape(1, -1),
                                    np.asarray(c, np.int64).reshape(1, -1),
                                    m.reshape(1, -1))
            return np.asarray(masked_probs_np(plog[0], m, float(temperature)),
                              dtype=np.float64)
        p = np.asarray(self.searcher.prior_batch(
            np.asarray(f, np.float32).reshape(1, -1),
            np.asarray(c, np.int64).reshape(1, -1),
            m.reshape(1, -1))[0], dtype=np.float64)
        t = float(temperature)
        if t != 1.0:
            p = np.power(np.maximum(p, 0.0), 1.0 / t)
            s = float(p.sum())
            p = p / s if s > 0.0 else p
        return p

    # ── 每个决策点的入口 ────────────────────────────────────────────────
    def propose(self, game: Any, seat: int, game_id: Any, *,
                action: int, logprob: float, f: np.ndarray, c: np.ndarray,
                mask: np.ndarray, temperature: float = 1.0,
                rng: Any = None) -> Optional[MixOutcome]:
        """触发则跑搜索并按 μ 重采样；返回 ``None`` 表示「本次不混合」。

        ``None`` 的语义包括：ε 未命中 / 非关键决策 / 每回合上限 / 搜索失败或超时 /
        无 RNG。调用方此时保留原来按 π 采样的动作与 logprob（``logp_mu=logp_pi``）。
        """
        if not self.enabled or rng is None:
            return None
        seat = int(seat)
        self.n_decisions += 1
        m = np.asarray(mask, dtype=bool).reshape(-1)
        if not bool(m.any()):
            return None
        turn = int(getattr(game, "turn", -1))
        key = (int(game_id), seat, turn)
        used = int(self._turn_searched.get(key, 0))
        cap = int(self.cfg.max_per_turn)
        if cap > 0 and used >= cap:
            self.n_cap_skipped += 1
            return None
        tags = self.searcher.tags(np.asarray(f, np.float32), np.asarray(c, np.int64))
        if not tag_matches(tags, self._when):
            return None
        self.n_eligible += 1
        eps = float(self.cfg.eps)
        exact = bool(int(self.cfg.exact))
        coin_hit = bool(float(rng.random()) < eps)
        if not exact and not coin_hit:
            # 省钱模式：未命中不搜索、行为就是 π（logp_mu=logp_pi）
            return None
        if coin_hit:
            self.n_eps_hits += 1
        t0 = time.perf_counter()
        try:
            pi = self.policy_probs(f, c, m, float(temperature))
        except BaseException:      # noqa: BLE001 - 前向失败 → 退回 π 采样
            self.n_failed += 1
            return None
        try:
            out = self.searcher.search(game, seat, prior=pi.astype(np.float32),
                                       mask=m)
        except BaseException:      # noqa: BLE001 - 搜索绝不打断训练
            self.n_failed += 1
            return None
        if out is None:
            self.n_failed += 1
            return None
        ps = np.asarray(out.pi, dtype=np.float64)
        try:
            mu = mix_distribution(pi, ps, float(self.cfg.eps))
        except BaseException:      # noqa: BLE001 - 数值异常 → 退回 π
            self.n_failed += 1
            return None
        # 动作：ε 分支命中时**按 π_search 采样**（任务口径「按其采样动作」），否则
        # 沿用调用方已按 π 采样的动作。两种分支合起来的边际正是
        # μ=(1−ε)π+ε·π_S，所以 IS 分母统一用 μ(a)（精确模式）在两种分支上都成立。
        ps_n = np.maximum(ps, 0.0)
        s_ps = float(ps_n.sum())
        if s_ps <= 0.0:
            ps_n = np.where(m, 1.0, 0.0)
            s_ps = float(ps_n.sum())
        if coin_hit:
            a = int(rng.choice(N_ACTIONS, p=ps_n / s_ps))
            if not bool(m[a]):         # 数值兜底：只在合法动作上取最大质量
                legal = np.flatnonzero(m)
                a = int(legal[int(np.argmax(ps_n[legal]))])
        else:
            a = int(action)
        lp_mu = float(math.log(max(float(mu[a]), LOGPROB_FLOOR)))
        lp_pi = float(math.log(max(float(pi[a]), LOGPROB_FLOOR)))
        kl = kl_mu_pi(mu, pi)
        self._turn_searched[key] = used + 1
        self.n_searched += 1
        self.n_from_search += int(coin_hit)
        self.n_switched += int(bool(coin_hit) and int(a) != int(action))
        el = (time.perf_counter() - t0) * 1000.0
        self._push(self._kl, kl)
        self._push(self._ms, el)
        return MixOutcome(action=a, logp_mu=lp_mu, logp_pi=lp_pi,
                          kl_mu_pi=kl, elapsed_ms=el,
                          switched=bool(int(a) != int(action)),
                          used_search=bool(coin_hit))

    @staticmethod
    def _push(buf: List[float], v: float) -> None:
        buf.append(float(v))
        if len(buf) > _KL_CAP:
            del buf[: len(buf) - _KL_CAP]

    # ── 统计 ────────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """本次 collect 的混合统计（关闭时返回 ``{}`` = 不新增 meta 键）。"""
        if not self.enabled:
            return {}

        def _pct(xs: Sequence[float], q: float) -> float:
            if not len(xs):
                return 0.0
            ys = sorted(float(x) for x in xs)
            i = min(len(ys) - 1, max(0, int(round(q * (len(ys) - 1)))))
            return float(ys[i])

        nd = max(int(self.n_decisions), 1)
        ne = max(int(self.n_eligible), 1)
        nh = max(int(self.n_eps_hits), 1)
        kl = list(self._kl)
        ms = list(self._ms)
        return {
            "enabled": True,
            "eps": float(self.cfg.eps),
            "when": str(self.cfg.when),
            "max_per_turn": int(self.cfg.max_per_turn),
            "topk": int(self.cfg.topk),
            "turns": int(self.cfg.turns),
            "max_ms": float(self.cfg.max_ms),
            "decisions": int(self.n_decisions),
            "eligible": int(self.n_eligible),
            "trigger_ratio": float(self.n_eligible) / nd,
            "eps_hits": int(self.n_eps_hits),
            "eps_hit_rate": float(self.n_eps_hits) / ne,
            "exact": bool(int(self.cfg.exact)),
            "searched": int(self.n_searched),
            "searched_ratio": float(self.n_searched) / nd,
            "actions_from_search": int(self.n_from_search),
            "action_from_search_rate": (float(self.n_from_search)
                                        / max(int(self.n_searched), 1)),
            "search_success_rate": float(self.n_searched) / nh,
            "failed": int(self.n_failed),
            "cap_skipped": int(self.n_cap_skipped),
            "switched": int(self.n_switched),
            "switch_rate": float(self.n_switched) / max(int(self.n_from_search), 1),
            "kl_mu_pi_mean": (float(np.mean(kl)) if kl else 0.0),
            "kl_mu_pi_p50": _pct(kl, 0.5),
            "kl_mu_pi_p95": _pct(kl, 0.95),
            "kl_mu_pi_max": (float(max(kl)) if kl else 0.0),
            "search_ms_mean": (float(np.mean(ms)) if ms else 0.0),
            "search_ms_p50": _pct(ms, 0.5),
            "search_ms_p95": _pct(ms, 0.95),
            "search_ms_total": float(sum(ms)),
            "search_calls": int(getattr(self.searcher, "calls", 0) or 0) - self._calls0,
            "search_timeouts": (int(getattr(self.searcher, "timeouts", 0) or 0)
                                - self._timeouts0),
        }


def aggregate_behavior_mix(metas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """把多 shard 的 ``meta["behavior_mix"]`` 汇总成一份（默认关闭 → ``{}``）。"""
    rows = [dict(m["behavior_mix"]) for m in metas
            if isinstance(m, dict) and isinstance(m.get("behavior_mix"), dict)]
    if not rows:
        return {}

    def _sum(k: str) -> int:
        return int(sum(int(r.get(k, 0) or 0) for r in rows))

    def _wmean(k: str, w: str) -> float:
        num = sum(float(r.get(k, 0.0) or 0.0) * float(r.get(w, 0) or 0) for r in rows)
        den = sum(float(r.get(w, 0) or 0) for r in rows)
        return float(num / den) if den > 0 else 0.0

    decisions = _sum("decisions")
    eligible = _sum("eligible")
    hits = _sum("eps_hits")
    searched = _sum("searched")
    out = dict(rows[0])
    out.update({
        "decisions": decisions,
        "eligible": eligible,
        "eps_hits": hits,
        "searched": searched,
        "actions_from_search": _sum("actions_from_search"),
        "action_from_search_rate": _sum("actions_from_search") / max(searched, 1),
        "failed": _sum("failed"),
        "cap_skipped": _sum("cap_skipped"),
        "switched": _sum("switched"),
        "trigger_ratio": eligible / max(decisions, 1),
        "eps_hit_rate": hits / max(eligible, 1),
        "searched_ratio": searched / max(decisions, 1),
        "search_success_rate": searched / max(hits, 1),
        "switch_rate": _sum("switched") / max(searched, 1),
        "kl_mu_pi_mean": _wmean("kl_mu_pi_mean", "searched"),
        "search_ms_mean": _wmean("search_ms_mean", "searched"),
        "kl_mu_pi_p95": max(float(r.get("kl_mu_pi_p95", 0.0) or 0.0) for r in rows),
        "kl_mu_pi_max": max(float(r.get("kl_mu_pi_max", 0.0) or 0.0) for r in rows),
        "search_ms_p95": max(float(r.get("search_ms_p95", 0.0) or 0.0) for r in rows),
        "search_ms_total": float(sum(float(r.get("search_ms_total", 0.0) or 0.0)
                                     for r in rows)),
        "search_calls": _sum("search_calls"),
        "search_timeouts": _sum("search_timeouts"),
        "shards": len(rows),
    })
    return out


__all__ = [
    "BehaviorMixConfig", "BehaviorMixer", "MixOutcome",
    "aggregate_behavior_mix", "kl_mu_pi", "mix_distribution", "mu_logprob",
]
