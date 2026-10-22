"""turn-search 策略适配器：把 `hsbg.search.turn_search` 接到 env/collector。

设计要点（与 env-builder 对齐）：
* 模块级类，**bind_env 前可 pickle**（只持 config / 惰性创建的 heuristic）；
* `requires_engine=True`，`bind_env(env)` 后 `act(obs)` 用
  `EngineForwardModel.from_env(env, clone=False)`（只读；见 tests/test_search_env_readonly.py）
  + `TurnSearch.decide`；动作按 `CandidateAction.signature()` 映射回 `obs.candidates` 下标；
* 失败/无动作/turn 不一致/choice 阶段 → 回退 heuristic；
* 不依赖全局随机：search seed 从 config + episode seed + 决策序号显式导出。

用法::

    from hsbg.search.policy import TurnSearchPolicy, TurnSearchPolicyConfig
    policy = TurnSearchPolicy(TurnSearchPolicyConfig(states_budget=8))
    policy.bind_env(env)          # 之后不要 pickle / 不要跨进程传
    idx = policy.act(obs)
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from hsbg.env.spec import Observation
from hsbg.rl.policies import BasePolicy, HeuristicPolicy


@dataclass
class TurnSearchPolicyConfig:
    """可 pickle 的搜索配置（不放 env / 模型）。"""

    states_budget: int = 8
    samples_per_action: int = 1
    combat_samples: int = 1
    completion_policy: str = "heuristic"
    state_scorer: str = "pairwise"          # pairwise / value / value_prune_pairwise
    prune_top_k: int = 4
    action_aggregate: str = "max"
    max_steps_per_turn: int = 40
    #: 搜索 RNG 基种子；实际每决策用 base + episode_seed*100003 + decision_no
    search_seed: int = 0
    #: 仅 state_scorer != pairwise 时使用（BC checkpoint，用于 value/value_prune）
    evaluator_checkpoint: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TurnSearchPolicy(BasePolicy):
    """turn-search 驱动的单步策略（每条 env step 搜索一次；choice 阶段回退 heuristic）。"""

    name = "turn_search"
    requires_engine = True

    def __init__(self, config: Optional[TurnSearchPolicyConfig] = None) -> None:
        self.config = config or TurnSearchPolicyConfig()
        self._env: Any = None
        self._heuristic: Optional[HeuristicPolicy] = None
        self._evaluator: Any = None
        self._episode_seed: int = 0
        self._decision_no: int = 0
        self._reset_stats()

    # ── 生命周期 ──
    def bind_env(self, env: Any) -> None:
        self._env = env

    def set_episode_seed(self, seed: int) -> None:
        self._episode_seed = int(seed)

    def reset(self) -> None:
        self._decision_no = 0
        self._reset_stats()
        if self._heuristic is not None:
            self._heuristic.reset()

    def _reset_stats(self) -> None:
        self.stats: Dict[str, Any] = {
            "decisions": 0, "choice_steps": 0, "fallbacks": 0,
            "total_decision_ms": 0.0, "n_states": 0, "n_combats": 0,
            "n_value_evals": 0, "last_error": "",
        }

    # ── 内部构造 ──
    def _heuristic_policy(self) -> HeuristicPolicy:
        if self._heuristic is None:
            self._heuristic = HeuristicPolicy(seed=int(self.config.search_seed))
        return self._heuristic

    def _search_seed(self) -> int:
        # 显式、可复现；与 worker/调度无关
        return int(self.config.search_seed) + int(self._episode_seed) * 100003 + self._decision_no

    def _make_search(self):
        from hsbg.search.turn_search import TurnSearch, TurnSearchConfig
        cfg = TurnSearchConfig(
            states_budget=int(self.config.states_budget),
            samples_per_action=int(self.config.samples_per_action),
            combat_samples=int(self.config.combat_samples),
            completion_policy=str(self.config.completion_policy),
            state_scorer=str(self.config.state_scorer),
            prune_top_k=int(self.config.prune_top_k),
            action_aggregate=str(self.config.action_aggregate),
            max_steps_per_turn=int(self.config.max_steps_per_turn),
            seed=self._search_seed(),
        )
        if self._evaluator is None and str(self.config.state_scorer) != "pairwise":
            ckpt = str(self.config.evaluator_checkpoint or "")
            if ckpt:
                from hsbg.search.evaluator import PolicyEvaluator
                self._evaluator = PolicyEvaluator(ckpt)
        return TurnSearch(cfg, evaluator=self._evaluator)

    @staticmethod
    def _candidate_index(obs: Observation, action: Any) -> Optional[int]:
        cands = tuple(getattr(obs, "candidates", ()) or ())
        if not cands or action is None:
            return None
        sig = getattr(action, "signature", None)
        if sig is not None:
            try:
                target = sig()
            except Exception:  # noqa: BLE001
                target = None
            if target is not None:
                for i, cand in enumerate(cands):
                    try:
                        if cand.signature() == target:
                            return i
                    except Exception:  # noqa: BLE001
                        continue
        return None

    # ── 策略接口 ──
    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Any = None) -> int:
        fallback = self._fallback_index(obs)
        # choice 阶段不搜索（与 eval_turn_search.py 一致；避免在选项上浪费搜索）
        if str(getattr(obs, "phase", "")) == "choice":
            self.stats["choice_steps"] += 1
            return fallback
        env = self._env
        if env is None:
            self.stats["fallbacks"] += 1
            return fallback
        try:
            from hsbg.search.forward import EngineForwardModel
            model = EngineForwardModel.from_env(env, clone=False)
            if int(getattr(model, "turn", -1)) != int(getattr(obs, "turn", -2)):
                self.stats["fallbacks"] += 1
                return fallback
            ts = self._make_search()
            t0 = time.perf_counter()
            res = ts.decide(model)
            self.stats["total_decision_ms"] += (
                (time.perf_counter() - t0) * 1000.0)
            self.stats["n_states"] += int(res.n_states)
            self.stats["n_combats"] += int(res.n_combats)
            self.stats["n_value_evals"] += int(getattr(res, "n_value_evals", 0) or 0)
            self.stats["decisions"] += 1
            self._decision_no += 1
            idx = self._candidate_index(obs, res.action)
            if idx is None or int(getattr(res, "turn", -1)) != int(
                    getattr(obs, "turn", -2)):
                self.stats["fallbacks"] += 1
                return fallback
            return int(idx)
        except Exception as exc:  # noqa: BLE001 - 搜索失败绝不阻塞采集
            self.stats["last_error"] = f"{type(exc).__name__}: {exc}"
            self.stats["fallbacks"] += 1
            return fallback

    def _fallback_index(self, obs: Observation) -> int:
        cands = tuple(getattr(obs, "candidates", ()) or ())
        if not cands:
            return 0
        try:
            idx = int(self._heuristic_policy().act(obs))
            if 0 <= idx < len(cands):
                return idx
        except Exception:  # noqa: BLE001
            pass
        # 最终兜底：end_turn 优先，否则 0
        for i, cand in enumerate(cands):
            kind = getattr(cand, "kind", "")
            if kind == "end_turn":
                return i
        return 0

    def stats_dict(self) -> Dict[str, Any]:
        out = dict(self.stats)
        out["mean_decision_ms"] = (
            out["total_decision_ms"] / out["decisions"]
            if out["decisions"] else 0.0)
        out["mean_states"] = (
            out["n_states"] / out["decisions"] if out["decisions"] else 0.0)
        out["mean_combats"] = (
            out["n_combats"] / out["decisions"] if out["decisions"] else 0.0)
        return out


__all__ = ["TurnSearchPolicy", "TurnSearchPolicyConfig"]
