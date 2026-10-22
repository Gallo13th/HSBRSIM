"""动作级 micro-PUCT（train-free）：单回合内逐动作展开 + rollout 叶评估。

与 macro `HardSearch` 的区别：
- 节点 = 一个动作后的状态；边 = 当前合法 ``CandidateAction``；
- 每次模拟沿树选择动作、执行，叶用 ``rollout_to_end``（env 正常对手）评估；
- 宽度剪枝：每个节点只**展开** top-W 动作（按 BC policy prior/heuristic），
  其余合法动作保留为“未展开边”（记录在 ``all_actions``）；
- 选择 root 最优动作交给 env 执行；下一步重新取 state 继续（同一回合内逐步）。

不训练、不更新权重；叶评估不用价值网（rollout 名次→utility）。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from hsbg import planning
from hsbg.env.spec import CandidateAction
from hsbg.search.evaluator import PolicyEvaluator
from hsbg.search.forward import ACTION_END_TURN, EngineForwardModel
from hsbg.search.hard_search import rollout_to_terminal
from hsbg.search.types import placement_utility, prior_softmax

__all__ = ["MicroConfig", "MicroNode", "MicroResult", "MicroMCTS"]


@dataclass
class MicroConfig:
    #: 每决策模拟次数
    simulations: int = 8
    #: 每节点展开宽度（top-W 动作）
    width: int = 8
    #: 最大动作深度（本回合内）
    max_depth_actions: int = 6
    #: 叶 rollout horizon（0=到终局；3=截断）
    leaf_horizon_turns: int = 3
    #: PUCT 探索常数
    c_puct: float = 1.5
    #: 随机种子（同 seed 可复现；模拟间用 seed+k 做独立 rollout）
    seed: int = 0
    #: rollout 策略（heuristic/epsilon/random）
    rollout_policy: str = "heuristic"
    rollout_epsilon: float = 0.15
    #: 叶评估目标："utility"（名次）/"win"
    objective: str = "utility"
    #: root 最终 top-K 动作各做 1 次 full-to-end 复核（0=关闭）
    final_full_check: int = 0
    #: 稠密叶评估：边即时奖励 + discounted backup + horizon value
    dense_leaf: bool = False
    gamma: float = 0.95
    alpha_value: float = 0.5
    w_combat: float = 0.4
    w_board: float = 0.2
    w_health: float = 0.2
    w_economy: float = 0.2
    prior_heuristic_mix: float = 0.3
    #: 树复用/调试：每节点最多保留
    max_nodes: int = 512

    def __post_init__(self) -> None:
        self.simulations = max(1, int(self.simulations))
        self.width = max(1, int(self.width))
        self.max_depth_actions = max(1, int(self.max_depth_actions))
        self.leaf_horizon_turns = max(0, int(self.leaf_horizon_turns))
        self.c_puct = float(self.c_puct)
        self.final_full_check = max(0, int(self.final_full_check))
        self.dense_leaf = bool(self.dense_leaf)
        self.gamma = float(self.gamma)
        self.alpha_value = float(self.alpha_value)
        self.prior_heuristic_mix = float(self.prior_heuristic_mix)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "simulations": self.simulations, "width": self.width,
            "max_depth_actions": self.max_depth_actions,
            "leaf_horizon_turns": self.leaf_horizon_turns,
            "c_puct": self.c_puct, "seed": self.seed,
            "rollout_policy": self.rollout_policy,
            "rollout_epsilon": self.rollout_epsilon,
            "objective": self.objective,
            "final_full_check": self.final_full_check,
            "dense_leaf": self.dense_leaf,
            "gamma": self.gamma,
            "alpha_value": self.alpha_value,
            "w_combat": self.w_combat,
            "w_board": self.w_board,
            "w_health": self.w_health,
            "w_economy": self.w_economy,
            "prior_heuristic_mix": self.prior_heuristic_mix,
        }


@dataclass
class MicroNode:
    depth: int = 0
    path: Tuple[CandidateAction, ...] = ()
    #: 已展开的 top-W 动作
    actions: List[CandidateAction] = field(default_factory=list)
    priors: np.ndarray = field(default_factory=lambda: np.zeros(0))
    #: 全部合法动作（含未展开；仅记录）
    all_actions: List[CandidateAction] = field(default_factory=list)
    children: Dict[int, "MicroNode"] = field(default_factory=dict)
    N: int = 0
    value_sum: float = 0.0
    #: 该节点对应状态的 digest（树复用验证）
    state_digest: str = ""

    @property
    def expanded(self) -> bool:
        return bool(self.actions)

    @property
    def Q(self) -> float:
        return self.value_sum / self.N if self.N > 0 else 0.0


@dataclass
class MicroResult:
    action: Optional[CandidateAction]
    visits: int
    elapsed_s: float
    depth: int = 1
    root_visits: Optional[np.ndarray] = None
    root_q: Optional[np.ndarray] = None
    n_simulations: int = 0
    oracle_used: bool = False
    final_full_ranks: Optional[List[int]] = None


class MicroMCTS:
    """动作级 PUCT；每决策重建树（root=当前 state），叶 rollout 到终局/截断。"""

    def __init__(self, config: Optional[MicroConfig] = None,
                 evaluator: Optional[PolicyEvaluator] = None) -> None:
        self.config = config or MicroConfig()
        self.evaluator = evaluator or PolicyEvaluator()
        self._leaf_rollouts = 0
        self._expansions = 0
        self._reuse_root: Optional[MicroNode] = None

    # ── 公开 ──
    def commit(self, action: CandidateAction) -> bool:
        """执行 root 动作后，把对应 child 提升为下次 search 的 root（树复用）。"""
        root = self._reuse_root
        if root is None:
            return False
        for i, a in enumerate(root.actions):
            if a.signature() == action.signature():
                child = root.children.get(i)
                if child is not None:
                    self._reuse_root = child
                    return True
        return False

    def decide(self, model: EngineForwardModel) -> MicroResult:
        cfg = self.config
        t0 = time.perf_counter()
        if model.is_terminal():
            return MicroResult(None, 0, time.perf_counter() - t0,
                               n_simulations=0, oracle_used=False)
        root_model = model.clone()
        try:
            from hsbg import planning
            dg = planning.digest(model.game)
        except Exception:  # noqa: BLE001
            dg = ""
        if (self._reuse_root is not None and dg
                and self._reuse_root.state_digest == dg):
            root = self._reuse_root
        else:
            root = MicroNode(depth=0, path=(), state_digest=dg)
            self._expand(root, root_model)
        self._reuse_root = root
        if not root.actions:
            return MicroResult(None, 0, time.perf_counter() - t0,
                               n_simulations=0, oracle_used=False)
        for k in range(int(cfg.simulations)):
            self._simulate(root, root_model.clone(), k)
        visits = np.asarray(
            [root.children[i].N if i in root.children else 0
             for i in range(len(root.actions))])
        qvals = np.asarray([root.children[i].Q if i in root.children else 0.0
                            for i in range(len(root.actions))])
        best_i = int(np.argmax(visits)) if visits.sum() > 0 else 0
        final_ranks: Optional[List[int]] = None
        if int(cfg.final_full_check) > 0 and len(root.actions) > 1:
            order = sorted(range(len(root.actions)),
                           key=lambda i: (visits[i], qvals[i]),
                           reverse=True)[:max(1, int(cfg.final_full_check))]
            best_val = -1e18
            final_ranks = []
            for i in order:
                dup = root_model.clone()
                try:
                    ok = dup.apply(root.actions[i])
                except Exception:  # noqa: BLE001
                    ok = False
                if not ok:
                    continue
                out = rollout_to_terminal(
                    dup, policy=cfg.rollout_policy,
                    epsilon=cfg.rollout_epsilon, max_horizon_turns=0,
                    seed=int(cfg.seed) * 1_000_003 + 900_000 + i,
                    backend="env")
                rank = int(out.get("rank", 8))
                final_ranks.append(rank)
                val = float(placement_utility(rank, 8))
                if val > best_val:
                    best_val = val
                    best_i = i
        return MicroResult(
            action=root.actions[best_i], visits=int(visits.sum()),
            elapsed_s=time.perf_counter() - t0, depth=1,
            root_visits=visits, root_q=qvals,
            n_simulations=int(cfg.simulations), oracle_used=False,
            final_full_ranks=final_ranks)

    # ── 树操作 ──
    def _prior(self, model: EngineForwardModel,
               actions: Sequence[CandidateAction]) -> np.ndarray:
        base = np.full(len(actions), 1.0 / max(1, len(actions)))
        try:
            ev = self.evaluator.evaluate(model)
            cand = list(ev.candidates)
            if len(cand) == len(actions) and ev.prior.size == len(actions):
                base = np.asarray(ev.prior, dtype=np.float64)
        except Exception:  # noqa: BLE001
            pass
        # heuristic kind prior（手工先验，非学习评分器）
        prio = {"end_turn": 100, "upgrade": 90, "use_dark_gift": 85,
                "hero_power": 80, "buy": 70, "play_minion": 65,
                "play_spell": 60, "reroll": 50, "freeze": 40,
                "activate": 30, "sell": 20, "choose": 99}
        hp = np.asarray([prio.get(str(a.kind), 10) for a in actions],
                        dtype=np.float64)
        if hp.size and hp.sum() > 0:
            hp = hp / hp.sum()
            mix = float(self.config.prior_heuristic_mix)
            out = (1.0 - mix) * base + mix * hp
        else:
            out = base
        s = float(out.sum())
        return out / s if s > 0 else base

    # ── 稠密奖励 ──
    def _features(self, model: EngineForwardModel) -> Dict[str, float]:
        try:
            ev = planning.evaluate(model.game, model.hero)
            hero = model.hero
            return {"board": float(ev.get("board_power", 0) or 0),
                    "health": float(ev.get("health", 0) or 0)
                    + float(ev.get("armor", 0) or 0),
                    "gold": float(getattr(hero, "gold", 0) or 0),
                    "tier": float(getattr(hero, "tavern_tier", 0) or 0)}
        except Exception:  # noqa: BLE001
            return {"board": 0.0, "health": 0.0, "gold": 0.0, "tier": 0.0}

    def _combat_signal(self, model: EngineForwardModel) -> float:
        try:
            summary, _ = planning.simulate_turn_combat(
                model.game, model.hero, keep_state=False)
        except Exception:  # noqa: BLE001
            return 0.0
        if not isinstance(summary, dict):
            return 0.0
        win = summary.get("winner_is_hero")
        if win is None:
            win = bool(summary.get("hero_alive_after"))
        signal = 1.0 if win else (-1.0 if summary.get("loser") is not None else 0.0)
        return float(signal + 0.01 * float(summary.get("damage_dealt", 0) or 0))

    def _edge_reward(self, pre: Dict[str, float],
                     post: Dict[str, float], combat: float) -> float:
        c = self.config
        board_d = (post["board"] - pre["board"]) / 50.0
        hp_d = (post["health"] - pre["health"]) / 10.0
        econ_d = ((post["gold"] - pre["gold"]) / 10.0
                  + (post["tier"] - pre["tier"]))
        return float(c.w_combat * combat + c.w_board * board_d
                     + c.w_health * hp_d + c.w_economy * econ_d)

    def _expand(self, node: MicroNode, model: EngineForwardModel) -> None:
        self._expansions += 1
        all_actions = list(model.candidates())
        node.all_actions = all_actions
        if not all_actions:
            node.actions = []
            node.priors = np.zeros(0)
            return
        prior = self._prior(model, all_actions)
        order = np.argsort(-np.asarray(prior))[:max(1, int(self.config.width))]
        node.actions = [all_actions[int(i)] for i in order]
        node.priors = np.asarray([prior[int(i)] for i in order], dtype=np.float64)
        if node.priors.sum() <= 0:
            node.priors = np.full(len(node.actions), 1.0 / len(node.actions))

    def _select(self, node: MicroNode) -> int:
        total = max(1, int(node.N))
        best_i, best = 0, -1e18
        for i in range(len(node.actions)):
            child = node.children.get(i)
            n_a = child.N if child is not None else 0
            q = child.Q if child is not None else 0.0
            p = float(node.priors[i]) if i < len(node.priors) else 0.0
            score = q + self.config.c_puct * p * math.sqrt(total) / (1 + n_a)
            if score > best:
                best, best_i = score, i
        return best_i

    def _leaf_value(self, model: EngineForwardModel, sim: int) -> float:
        self._leaf_rollouts += 1
        if model.is_terminal():
            return float(model.terminal_utility())
        seed = int(self.config.seed) * 1_000_003 + int(sim) * 7919 + 17
        out = rollout_to_terminal(
            model, policy=self.config.rollout_policy,
            epsilon=self.config.rollout_epsilon,
            max_horizon_turns=int(self.config.leaf_horizon_turns),
            seed=seed, backend="env")
        rank = int(out.get("rank", 8))
        if self.config.objective == "win":
            return 1.0 if out.get("win") else -1.0
        return float(placement_utility(rank, 8))

    def _simulate(self, root: MicroNode, model: EngineForwardModel,
                  sim: int) -> float:
        cfg = self.config
        node = root
        # (node, action, immediate reward)
        path: List[Tuple[MicroNode, int, float]] = []
        terminal_leaf = False
        while True:
            if node.depth >= int(cfg.max_depth_actions):
                value = self._leaf_value(model, sim)
                break
            if not node.expanded:
                self._expand(node, model)
                if not node.actions:
                    value = self._leaf_value(model, sim)
                    break
            a = self._select(node)
            action = node.actions[a]
            pre = self._features(model) if cfg.dense_leaf else None
            combat = 0.0
            if cfg.dense_leaf and str(getattr(action, "kind", "")) == ACTION_END_TURN:
                combat = self._combat_signal(model)
            ok = model.apply(action)
            reward = 0.0
            if cfg.dense_leaf and ok:
                try:
                    post = self._features(model)
                    reward = self._edge_reward(pre, post, combat)
                except Exception:  # noqa: BLE001
                    reward = 0.0
            path.append((node, a, reward))
            child = node.children.get(a)
            if child is None:
                child = MicroNode(depth=node.depth + 1, path=node.path + (action,))
                node.children[a] = child
            if node is root and not child.state_digest:
                try:
                    child.state_digest = planning.digest(model.game)
                except Exception:  # noqa: BLE001
                    pass
            terminal_leaf = bool(model.is_terminal())
            if not ok or terminal_leaf \
                    or str(getattr(action, "kind", "")) == ACTION_END_TURN:
                value = self._leaf_value(model, sim)
                break
            node = child
        if cfg.dense_leaf and not terminal_leaf:
            value = float(cfg.alpha_value) * float(value)
        g = float(value)
        for n, a, r in reversed(path):
            g = float(r) + float(cfg.gamma) * g
            n.N += 1
            n.value_sum += g
        return g
