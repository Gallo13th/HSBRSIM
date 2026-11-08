"""AlphaZero 风格**不完全信息**搜索原型（PIMC / determinization + PUCT）。

对应任务 task-2 与设计文档 `docs/AZ_MCTS_SELFPLAY_DESIGN.md` §3/§7.6：

- 决策输入只有 `observe(seat)`；隐藏世界由 `belief.BeliefSampler` 从公开信息采样；
- 每个 determinization 一棵 PUCT 树（PIMC）；根访问数跨世界聚合为 π；
- 根 Dirichlet 噪声、温度、合法掩码、**无符号翻转**的 utility 备份；
- `EndTurn` 是宏动作：Rust 后端折叠在我方边内（bot 推进 7 座 + 引擎 RNG）；
  Python 后端支持 `resample_on_end_turn`（EndTurn 后重新采样对手隐藏世界 = chance 节点）；
- 安全回退：eval 异常/引擎非法动作/全失败 → 记录 fallback，用合法动作或 bot 兜底，
  **不抛出到训练进程**。

两个后端：
- `engine_backend="rust"`：直接调 `hsbg_engine.mcts_search`（每个世界一次，GIL 内回调）；
  快，但 chance 在树内折叠、每世界一次 Dirichlet；
- `engine_backend="python"`：本文件的 PUCT 实现（toy/测试/引擎对照；支持 chance 重采样）。
`engine_backend="auto"`：engine Game → rust（若可用），否则 python。
"""

from __future__ import annotations

import inspect
import math
import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import env_api as EA
from . import puct as P
from .belief import BeliefSampler, DeterminizeInfo, default_sampler, split_simulations
from .policy import CallableEvaluator, HeuristicEvaluator, make_evaluator


@dataclass
class SearchConfig:
    """搜索超参（与 docs 公式一一对应；命令行可覆盖）。"""

    simulations: int = 16              # 每次决策总模拟数（跨世界均分）
    determinizations: int = 4          # 世界数 W（PIMC）
    c_puct: float = 1.5
    temperature: float = 1.0           # π ∝ visits^(1/τ)；<=0 → argmax
    dirichlet_alpha: float = 0.3
    dirichlet_epsilon: float = 0.0     # 自对弈训练建议 0.25；评估 0
    seed: int = 0
    max_depth: int = 0                 # 0=不限；否则按"我方决策步数"截断
    resample_on_end_turn: bool = False  # 仅 Python 后端：EndTurn 后重采样隐藏世界
    fallback: str = "legal"            # "legal" | "bot" | "prior"
    root_prior_floor: float = 0.0      # >0：根先验混入 floor 的合法均匀（防先验过尖）


@dataclass
class SearchResult:
    """一次决策的搜索结果（训练数据/评测/日志共用）。"""

    pi: np.ndarray
    action: int
    root_value: float
    visits: int
    n_simulations: int
    determinizations: int
    n_states: int
    elapsed_s: float
    per_world: List[dict] = field(default_factory=list)
    fallback: bool = False
    info: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "action": int(self.action),
            "root_value": float(self.root_value),
            "visits": int(self.visits),
            "n_simulations": int(self.n_simulations),
            "determinizations": int(self.determinizations),
            "n_states": int(self.n_states),
            "elapsed_s": float(self.elapsed_s),
            "fallback": bool(self.fallback),
            "info": self.info,
            "per_world": self.per_world,
        }


# ── evaluator 适配 ──────────────────────────────────────────────────────────


class _RustStyleEvaluator:
    """适配 `eval_fn(features, cards, mask, seat) -> (policy[245], value)` 回调。

    与 `hsbg_engine.mcts_search` 的 eval 回调逐参一致（training-engineer 可复用）。
    """

    accepts_game = False

    def __init__(self, fn: Callable, name: str = "custom"):
        self.fn = fn
        self.name = name

    def __call__(self, obs: EA.ObsView, seat: int, game: Any = None):
        return self.fn(obs.features, obs.cards, obs.mask, int(seat))


def _wrap_evaluator(ev: Any):
    """归一化 evaluator：None → heuristic；4 参回调 → Rust 风格；其余按 obs 可调用。"""
    if ev is None:
        return HeuristicEvaluator()
    if getattr(ev, "accepts_game", False) or hasattr(ev, "_is_az_evaluator"):
        return ev
    if isinstance(ev, (HeuristicEvaluator,)):
        return ev
    # 尝试判断签名参数个数：4 参 = Rust/训练侧约定 (features, cards, mask, seat)
    try:
        sig = inspect.signature(ev)
        positional = [p for p in sig.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if len(positional) >= 4:
            return _RustStyleEvaluator(ev)
    except (TypeError, ValueError):  # pragma: no cover - 内建/不可签名可调用
        pass
    return CallableEvaluator(ev)


def _call_evaluator(ev, obs: EA.ObsView, seat: int, game: Any) -> Tuple[np.ndarray, float]:
    if getattr(ev, "accepts_game", False):
        policy, value = ev(obs, int(seat), game=game)
    else:
        policy, value = ev(obs, int(seat))
    policy = np.asarray(policy, dtype=np.float32)
    value = float(value)
    if not np.isfinite(value):
        raise ValueError("evaluator returned non-finite value")
    return policy, value


def _uniform_policy(mask: np.ndarray) -> np.ndarray:
    n = int(np.asarray(mask).sum())
    if n <= 0:
        return np.zeros_like(mask, dtype=np.float32)
    return np.asarray(mask, dtype=np.float32) / float(n)


# ── 结果收尾 ────────────────────────────────────────────────────────────────


def _finalize(counts: np.ndarray, root_mask: np.ndarray, cfg: SearchConfig,
              rng: random.Random, root_prior: Optional[np.ndarray] = None
              ) -> Tuple[np.ndarray, int]:
    counts = np.asarray(counts, dtype=np.float64)
    pi = P.visit_distribution(counts, cfg.temperature, root_mask)
    legal = np.flatnonzero(root_mask)
    if legal.size == 0:
        return pi, 0
    if cfg.temperature is not None and cfg.temperature <= 0.0:
        best = float(np.max(pi[legal]))
        cand = legal[np.isclose(pi[legal], best, rtol=0.0, atol=1e-12)]
        if cand.size > 1 and root_prior is not None:
            # 访问数打平（低 sims 常见）：用根先验打破平局，避免退化成"下标最小=EndTurn"
            cand = np.array([int(cand[int(np.argmax(np.asarray(root_prior)[cand]))])])
        action = int(cand[0])
    else:
        action = P.sample_action(pi, rng)
        if not bool(root_mask[action]):
            action = int(legal[int(np.argmax(pi[legal]))])
    return pi, action


def _root_prior_for_tiebreak(evaluator, root_obs: EA.ObsView, seat: int) -> np.ndarray:
    """仅用于 argmax 平局打破的根先验（不参与备份）。"""
    try:
        prior_raw, _ = _call_evaluator(evaluator, root_obs, int(seat), None)
        return P.masked_prior(prior_raw, root_obs.mask)
    except Exception:  # noqa: BLE001
        return _uniform_policy(root_obs.mask)


def _quality_stats(pi: np.ndarray, mask: np.ndarray) -> dict:
    p = np.asarray(pi, dtype=np.float64)
    p = p[np.asarray(mask, dtype=bool) & (p > 0)]
    if p.size == 0:
        return {"entropy": 0.0, "top1_margin": 0.0, "max_prob": 0.0}
    s = float(p.sum())
    q = p / s if s > 0 else p
    ent = float(-np.sum(q * np.log(np.maximum(q, 1e-12))))
    top = np.sort(q)[::-1]
    margin = float(top[0] - (top[1] if top.size > 1 else 0.0))
    return {"entropy": ent, "top1_margin": margin, "max_prob": float(top[0])}


def _fallback_action(game: Any, seat: int, root_mask: np.ndarray,
                     cfg: SearchConfig, prior: Optional[np.ndarray],
                     rng: random.Random) -> int:
    legal = np.flatnonzero(root_mask)
    if legal.size == 0:
        return 0
    mode = (cfg.fallback or "legal").lower()
    if mode == "bot":
        try:
            a = int(EA.bot_action(game, int(seat)))
            if bool(root_mask[a]):
                return a
        except Exception:  # noqa: BLE001
            pass
    elif mode == "prior" and prior is not None and prior.size == legal.size + 0:
        idx = int(np.argmax(np.where(root_mask, prior, -1.0)))
        if bool(root_mask[idx]):
            return idx
    return int(legal[rng.randrange(int(legal.size))])


# ── Python PUCT / PIMC 后端 ─────────────────────────────────────────────────


class _PythonSearch:
    def __init__(self, cfg: SearchConfig, evaluator, sampler: Optional[BeliefSampler]):
        self.cfg = cfg
        self.evaluator = evaluator
        self.sampler = sampler
        self.n_states = 0
        self.n_evals = 0
        self.errors: List[str] = []
        self.obs_invariant: List[Optional[bool]] = []

    # -- 叶评估 -------------------------------------------------------------
    def _expand(self, node: P.Node) -> float:
        try:
            obs = EA.observe(node.game, node.seat)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"observe: {exc}")
            node.terminal_value = 0.0
            return 0.0
        mask = obs.mask
        if int(mask.sum()) == 0:
            tv = EA.terminal_value(node.game, node.seat)
            node.terminal_value = float(tv if tv is not None else 0.0)
            return node.terminal_value
        try:
            prior_raw, value = _call_evaluator(self.evaluator, obs, node.seat, node.game)
            self.n_evals += 1
        except Exception as exc:  # noqa: BLE001 - 安全回退：均匀先验 + value 0
            self.errors.append(f"eval: {type(exc).__name__}: {exc}")
            prior_raw, value = _uniform_policy(mask), 0.0
        prior = P.masked_prior(prior_raw, mask)
        if self.cfg.root_prior_floor > 0.0:
            floor = float(np.clip(self.cfg.root_prior_floor, 0.0, 1.0))
            prior = P.masked_prior((1.0 - floor) * prior + floor * _uniform_policy(mask), mask)
        node.expand(prior, mask, value)
        return float(node.value)

    # -- 子节点（执行动作 + 推进对手 + chance 重采样）------------------------
    def _make_child(self, node: P.Node, action: int, chance_rng: random.Random) -> P.Node:
        nxt = node.game.copy()
        self.n_states += 1
        try:
            EA.step(nxt, node.seat, action)
        except Exception as exc:  # noqa: BLE001 - 非法动作：边终止，价值 0
            self.errors.append(f"step(a={action}): {type(exc).__name__}: {exc}")
            return P.Node(node.game, node.seat, depth=node.depth + 1, terminal_value=0.0)
        try:
            EA.drive_opponents(nxt, node.seat)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"drive_opponents: {exc}")
        if (self.cfg.resample_on_end_turn and action == EA.END_TURN
                and self.sampler is not None):
            try:
                nxt, info = self.sampler.sample(nxt, node.seat, chance_rng)
                self.obs_invariant.append(info.obs_invariant)
                self.n_states += 1
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"chance resample: {exc}")
        tv = EA.terminal_value(nxt, node.seat)
        return P.Node(nxt, node.seat, depth=node.depth + 1, terminal_value=tv)

    # -- 单次模拟 -----------------------------------------------------------
    def simulate(self, root: P.Node, chance_rng: random.Random) -> float:
        path: List[Tuple[P.Node, int]] = []
        node = root
        while True:
            if node.terminal_value is not None:
                v = float(node.terminal_value)
                break
            if not node.expanded:
                v = self._expand(node)
                break
            if self.cfg.max_depth > 0 and node.depth >= self.cfg.max_depth:
                v = float(node.value)
                break
            a = P.puct_select(node, node.mask, self.cfg.c_puct)
            child = node.children.get(a)
            if child is None:
                child = self._make_child(node, a, chance_rng)
                node.children[a] = child
            path.append((node, a))
            node = child
        for parent, a in reversed(path):
            parent.backup(a, v)
        return v

    def run_world(self, game: Any, seat: int, n_sims: int, seed: int,
                  root_obs: EA.ObsView
                  ) -> Tuple[np.ndarray, float, int, np.ndarray]:
        root = P.Node(game, seat)
        tv = EA.terminal_value(game, seat)
        if tv is not None:
            root.terminal_value = float(tv)
            return (root.counts.astype(np.float64), float(tv), 0,
                    np.zeros_like(root_obs.mask, dtype=np.float32))
        mask = root_obs.mask
        if int(mask.sum()) == 0:
            root.terminal_value = 0.0
            return (root.counts.astype(np.float64), 0.0, 0,
                    np.zeros_like(root_obs.mask, dtype=np.float32))
        # 根先验：用真实根观测（所有世界一致），不是世界内部观测
        try:
            prior_raw, value = _call_evaluator(self.evaluator, root_obs, seat, game)
            self.n_evals += 1
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"root eval: {type(exc).__name__}: {exc}")
            prior_raw, value = _uniform_policy(mask), 0.0
        root_prior = P.masked_prior(prior_raw, mask)
        root.expand(root_prior, mask, value)
        rng = random.Random(int(seed))
        if self.cfg.dirichlet_epsilon > 0.0:
            root.prior = P.dirichlet_legal(root.prior, mask, self.cfg.dirichlet_alpha,
                                           self.cfg.dirichlet_epsilon, rng)
        chance_rng = random.Random(int(seed) ^ 0xC0FFEE)
        for _ in range(int(n_sims)):
            self.simulate(root, chance_rng)
        counts = root.counts.astype(np.float64)
        total = float(counts.sum())
        # 根价值：按访问加权 Q（更稳）；无访问用根评估值
        if total > 0:
            rv = float(np.dot(counts, root.q()) / total)
        else:  # pragma: no cover - simulations>=1 时不会发生
            rv = float(root.value)
        return counts, rv, int(root.total_visits), root_prior.astype(np.float32)


def _python_pimc(game: Any, seat: int, cfg: SearchConfig, evaluator,
                 sampler: Optional[BeliefSampler]) -> SearchResult:
    t0 = time.perf_counter()
    root_obs = EA.observe(game, seat)
    root_mask = np.asarray(root_obs.mask, dtype=bool)
    n_worlds = max(1, int(cfg.determinizations))
    if int(root_mask.sum()) == 0:
        return SearchResult(
            pi=np.zeros_like(root_mask, dtype=np.float32), action=0, root_value=0.0,
            visits=0, n_simulations=0, determinizations=0, n_states=0,
            elapsed_s=time.perf_counter() - t0, fallback=True,
            info={"engine_backend": "python", "reason": "no_legal_action"},
        )
    sims = split_simulations(cfg.simulations, n_worlds)
    engine = _PythonSearch(cfg, evaluator, sampler)
    worlds = []
    det_infos: List[Dict[str, Any]] = []
    t_det = time.perf_counter()
    for w in range(n_worlds):
        rng = random.Random(int(cfg.seed) + 104729 * (w + 1))
        if sampler is None:
            world, info = game.copy(), DeterminizeInfo(mode="clone")
        else:
            world, info = sampler.sample(game, seat, rng)
        worlds.append(world)
        det_infos.append(info.as_dict())
    det_elapsed = time.perf_counter() - t_det

    agg = np.zeros_like(root_mask, dtype=np.float64)
    agg_prior = np.zeros_like(root_mask, dtype=np.float64)
    per_world: List[dict] = []
    t_search = time.perf_counter()
    for w, world in enumerate(worlds):
        counts, rv, visits, root_prior = engine.run_world(
            world, seat, sims[w], seed=int(cfg.seed) + 7919 * (w + 1), root_obs=root_obs)
        agg += counts
        agg_prior += root_prior
        per_world.append({"world": w, "seed": int(cfg.seed) + 7919 * (w + 1),
                          "visits": int(visits), "root_value": float(rv),
                          "determinize": det_infos[w]})
    search_elapsed = time.perf_counter() - t_search
    rng = random.Random(int(cfg.seed) ^ 0x5EED)
    tiebreak_prior = P.masked_prior(agg_prior, root_mask) if n_worlds else None
    pi, action = _finalize(agg, root_mask, cfg, rng, tiebreak_prior)
    total_visits = int(agg.sum())
    root_value = (float(np.average([w["root_value"] for w in per_world],
                                   weights=[max(1, w["visits"]) for w in per_world]))
                  if per_world else 0.0)
    fallback = bool(engine.errors)
    if fallback and total_visits <= 0:
        action = _fallback_action(game, seat, root_mask, cfg, None, rng)
        pi = P.visit_distribution(root_mask.astype(np.float64), 0.0, root_mask)
    info: Dict[str, Any] = {
        "engine_backend": "python",
        "eval": getattr(evaluator, "name", type(evaluator).__name__),
        "dirichlet": {"alpha": float(cfg.dirichlet_alpha),
                      "epsilon": float(cfg.dirichlet_epsilon)},
        "chance_resample": bool(cfg.resample_on_end_turn),
        "n_evals": int(engine.n_evals),
        "n_worlds": int(n_worlds),
        "timing": {"determinize_s": float(det_elapsed),
                   "search_s": float(search_elapsed),
                   "total_s": float(time.perf_counter() - t0)},
        "world_obs_invariant": [d.get("obs_invariant") for d in det_infos],
        "determinize_modes": [d.get("mode") for d in det_infos],
        "fallback_reason": "; ".join(engine.errors[:5]) if engine.errors else "",
        "oracle": any(bool(d.get("oracle")) for d in det_infos),
    }
    info.update(_quality_stats(pi, root_mask))
    return SearchResult(
        pi=pi.astype(np.float32), action=int(action), root_value=root_value,
        visits=total_visits, n_simulations=int(sum(sims)),
        determinizations=n_worlds, n_states=int(engine.n_states),
        elapsed_s=float(time.perf_counter() - t0), per_world=per_world,
        fallback=fallback, info=info,
    )


# ── Rust 搜索核后端（每个 determinization 调一次 mcts_search）────────────────


def _rust_pimc(game: Any, seat: int, cfg: SearchConfig, evaluator,
               sampler: Optional[BeliefSampler]) -> SearchResult:
    E = EA.engine_module()
    if E is None or not hasattr(E, "mcts_search"):
        raise ImportError("hsbg_engine.mcts_search 不可用")
    t0 = time.perf_counter()
    root_obs = EA.observe(game, seat)
    root_mask = np.asarray(root_obs.mask, dtype=bool)
    n_worlds = max(1, int(cfg.determinizations))
    if int(root_mask.sum()) == 0:
        return SearchResult(
            pi=np.zeros_like(root_mask, dtype=np.float32), action=0, root_value=0.0,
            visits=0, n_simulations=0, determinizations=0, n_states=0,
            elapsed_s=time.perf_counter() - t0, fallback=True,
            info={"engine_backend": "rust", "reason": "no_legal_action"},
        )
    sims = split_simulations(cfg.simulations, n_worlds)
    stats = {"n_evals": 0, "errors": []}
    tiebreak_prior = None
    if cfg.temperature is not None and cfg.temperature <= 0.0:
        # 仅 argmax 需要 tie-break；这一次评估也计入 n_evals（与用户回调计数一致）
        tiebreak_prior = _root_prior_for_tiebreak(evaluator, root_obs, seat)
        stats["n_evals"] += 1

    def eval_cb(features_b, cards_b, mask_b, seat_arg):
        f = np.frombuffer(features_b, dtype="<f4").copy()
        c = np.frombuffer(cards_b, dtype="<i4").copy()
        m = np.frombuffer(mask_b, dtype=np.uint8).astype(bool)
        obs = EA.ObsView(features=f, cards=c, mask=m, seat=int(seat_arg),
                         turn=int(round(float(f[EA.G_TURN]) * 20.0)) if f.size else 0)
        try:
            prior, value = _call_evaluator(evaluator, obs, int(seat_arg), None)
            stats["n_evals"] += 1
            return np.asarray(prior, dtype=np.float32).tobytes(), float(value)
        except Exception as exc:  # noqa: BLE001 - 回调异常不让 Rust panic
            stats["errors"].append(f"eval: {type(exc).__name__}: {exc}")
            return _uniform_policy(m).tobytes(), 0.0

    t_det = time.perf_counter()
    worlds: List[Any] = []
    det_infos: List[Dict[str, Any]] = []
    for w in range(n_worlds):
        rng = random.Random(int(cfg.seed) + 104729 * (w + 1))
        if sampler is None:
            world, info = game.copy(), DeterminizeInfo(mode="clone")
        else:
            world, info = sampler.sample(game, seat, rng)
        worlds.append(world)
        det_infos.append(info.as_dict())
    det_elapsed = time.perf_counter() - t_det

    agg = np.zeros_like(root_mask, dtype=np.float64)
    per_world: List[dict] = []
    total_visits = 0
    values: List[Tuple[float, int]] = []
    t_search = time.perf_counter()
    for w, world in enumerate(worlds):
        seed_w = int(cfg.seed) + 7919 * (w + 1)
        try:
            pi_bytes, action, rv, visits = E.mcts_search(
                world, int(seat), simulations=int(sims[w]), c_puct=float(cfg.c_puct),
                temperature=1.0, eval_fn=eval_cb, seed=seed_w,
                dirichlet_alpha=float(cfg.dirichlet_alpha),
                dirichlet_epsilon=float(cfg.dirichlet_epsilon), rollout=False)
            pi_w = np.frombuffer(pi_bytes, dtype="<f4").copy()
            counts_w = pi_w.astype(np.float64) * float(max(1, int(visits)))
            agg += counts_w
            total_visits += int(visits)
            values.append((float(rv), int(visits)))
            per_world.append({"world": w, "seed": seed_w, "visits": int(visits),
                              "root_value": float(rv), "determinize": det_infos[w],
                              "engine_action": int(action)})
        except Exception as exc:  # noqa: BLE001 - 单世界失败不影响其它世界
            stats["errors"].append(f"world {w}: {type(exc).__name__}: {exc}")
            per_world.append({"world": w, "seed": seed_w, "visits": 0,
                              "root_value": 0.0, "determinize": det_infos[w],
                              "error": f"{type(exc).__name__}: {exc}"})
    search_elapsed = time.perf_counter() - t_search
    rng = random.Random(int(cfg.seed) ^ 0x5EED)
    if total_visits <= 0:
        action = _fallback_action(game, seat, root_mask, cfg, None, rng)
        pi = np.zeros_like(root_mask, dtype=np.float32)
        pi[int(action)] = 1.0
        fallback = True
        root_value = 0.0
    else:
        pi, action = _finalize(agg, root_mask, cfg, rng, tiebreak_prior)
        fallback = bool(stats["errors"])
        tot = sum(v for _, v in values) or 1
        root_value = float(sum(v * n for v, n in values) / tot)
    info: Dict[str, Any] = {
        "engine_backend": "rust",
        "eval": getattr(evaluator, "name", type(evaluator).__name__),
        "dirichlet": {"alpha": float(cfg.dirichlet_alpha),
                      "epsilon": float(cfg.dirichlet_epsilon)},
        "chance_resample": False,
        "chance_note": ("Rust 核内 EndTurn 的对手/chance 折叠在边内；世界间差异来自 "
                        "determinization。需要逐 EndTurn 重采样时用 engine_backend='python'"),
        "n_evals": int(stats["n_evals"]),
        "n_worlds": int(n_worlds),
        "timing": {"determinize_s": float(det_elapsed),
                   "search_s": float(search_elapsed),
                   "total_s": float(time.perf_counter() - t0)},
        "world_obs_invariant": [d.get("obs_invariant") for d in det_infos],
        "fallback_reason": "; ".join(stats["errors"][:5]) if stats["errors"] else "",
        "oracle": any(bool(d.get("oracle")) for d in det_infos),
        "n_states_estimate": True,
    }
    info.update(_quality_stats(pi, root_mask))
    # n_states 估计：每个世界 1 次根 copy + Rust 树内每个扩展一次 copy（≈ visits）
    return SearchResult(
        pi=pi.astype(np.float32), action=int(action), root_value=float(root_value),
        visits=int(total_visits), n_simulations=int(sum(sims)),
        determinizations=n_worlds, n_states=int(n_worlds + total_visits),
        elapsed_s=float(time.perf_counter() - t0), per_world=per_world,
        fallback=fallback, info=info,
    )


# ── 公共入口 ────────────────────────────────────────────────────────────────


def search(game: Any, seat: int, *, config: Optional[SearchConfig] = None,
           eval_fn: Any = None, belief: Optional[BeliefSampler] = None,
           engine_backend: str = "auto", **cfg_overrides) -> SearchResult:
    """不完全信息搜索（PIMC）：返回根 visit 分布 / 动作 / 诊断。

    参数
    ----
    game : env（`hsbg_engine.Game` 或 toy/测试 env；只读，不会被修改）
    seat : 决策座位
    config : SearchConfig；None → 默认
    eval_fn : None=内置启发式；`fn(features,cards,mask,seat)->(policy,value)`（Rust 兼容）
              或 `fn(obs: ObsView, seat)->(policy,value)`
    belief : BeliefSampler；None → 按 env 类型默认（engine → 公开信息先验）
    engine_backend : "auto" | "rust" | "python"
    """
    cfg = replace(config) if config is not None else SearchConfig()
    if cfg_overrides:
        unknown = set(cfg_overrides) - set(SearchConfig.__dataclass_fields__)
        if unknown:
            raise TypeError(f"未知 SearchConfig 字段: {sorted(unknown)}")
        cfg = replace(cfg, **cfg_overrides)
    if cfg.simulations < 1:
        raise ValueError("simulations 必须 >= 1")
    if cfg.determinizations < 1:
        raise ValueError("determinizations 必须 >= 1")
    if cfg.temperature is None:
        raise ValueError("temperature 不能为 None")

    evaluator = _wrap_evaluator(eval_fn)
    sampler = belief if belief is not None else default_sampler(game)

    backend = (engine_backend or "auto").lower()
    if backend == "auto":
        has_rust = (EA.engine_module() is not None
                    and hasattr(EA.engine_module(), "mcts_search")
                    and EA.is_engine_game(game))
        backend = "rust" if has_rust else "python"
    if backend not in ("rust", "python"):
        raise ValueError(f"engine_backend 必须是 auto/rust/python，得到 {engine_backend!r}")

    if backend == "rust":
        try:
            return _rust_pimc(game, int(seat), cfg, evaluator, sampler)
        except Exception as exc:  # noqa: BLE001 - 安全回退到 Python 实现
            res = _python_pimc(game, int(seat), cfg, evaluator, sampler)
            res.fallback = True
            res.info["backend_fallback"] = f"rust->python: {type(exc).__name__}: {exc}"
            return res
    return _python_pimc(game, int(seat), cfg, evaluator, sampler)


#: 别名（训练/评测脚本可读性）
az_search = search


def search_engine_style(game: Any, seat: int, *,
                        simulations: int = 16, c_puct: float = 1.5,
                        seed: int = 0, determinizations: int = 4,
                        temperature: float = 1.0,
                        eval_fn: Any = None) -> SearchResult:
    """训练侧最常用的扁平参数入口（快捷封装）。"""
    return search(game, seat, simulations=simulations, c_puct=c_puct, seed=seed,
                  determinizations=determinizations, temperature=temperature,
                  eval_fn=eval_fn)


__all__ = ["SearchConfig", "SearchResult", "az_search", "search",
           "search_engine_style"]
