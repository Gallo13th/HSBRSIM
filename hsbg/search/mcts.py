"""PUCT / MCTS 骨架（Phase 1：macro 回合级搜索）。

- 边 = ``MacroAction``（一个招募回合的动作序列）；节点在回合边界；
- 选择 = PUCT（单智能体 MDP；7 个对手视为环境随机性，不做 negamax）；
- 叶价值 = BC rank 分布 → placement utility；终局 = 实际/估计名次；
- 世界线 K=1（Phase 1）；``oracle`` 禁止；determinization 只做摘要记录（§3.6）。

Phase 1 只验证：可运行、可复现、合法、成本；不训练、不追求棋力提升。
"""

from __future__ import annotations

import math
import time
from typing import List, Optional, Tuple

import numpy as np

from hsbg.search.determinize import WarbandBank, determinize
from hsbg.search.evaluator import PolicyEvaluator
from hsbg.search.forward import EngineForwardModel
from hsbg.search.rollout import RolloutStats, generate_macros
from hsbg.search.types import (
    MacroAction,
    Node,
    SearchConfig,
    SearchResult,
    placement_utility,
)

__all__ = ["MCTS", "run_search"]


class MCTS:
    """minimal PUCT：Node 批量展开 macro、按 PUCT 选择、叶评估、备份。"""

    def __init__(self, model: EngineForwardModel, evaluator: PolicyEvaluator,
                 config: SearchConfig,
                 *, bank: Optional[WarbandBank] = None) -> None:
        self.model = model
        self.evaluator = evaluator
        self.config = config
        self.bank = bank
        self._expansions = 0
        self._rollout_stats = RolloutStats()
        #: Phase 1 K=1 的确定性模型：root macro 结果只算一次，后续 sims 复用
        #: （clone/rollout 是主要成本；这不是近似——同 root 同 macro 结果确定）。
        self._root_cache: dict = {}
        self._root_world: Optional[EngineForwardModel] = None

    # ── 公开入口 ──
    def search(self) -> SearchResult:
        cfg = self.config
        t0 = time.perf_counter()
        world, info = determinize(
            self.model, self.bank, seed=cfg.seed, oracle=False,
            n_world_lines=cfg.world_lines,
        )
        root = Node(depth=0)
        self._expand(root, world.clone())
        self._root_world = world
        self._root_cache = {}
        if not root.macros:
            return SearchResult(
                best_macro=None, pi=np.zeros(0), visits=np.zeros(0),
                root_prior=np.zeros(0), simulations=0,
                elapsed_s=time.perf_counter() - t0,
                n_expansions=self._expansions,
                oracle_used=False, hidden_info_mode=info.mode,
                root_macros=(), best_index=-1,
            )
        for _ in range(int(cfg.simulations)):
            if int(cfg.max_depth_turns) == 1 and cfg.cache_root_values:
                self._simulate_root_cached(root)
            else:
                self._simulate(root, world.clone())
            if cfg.time_budget_s > 0 and (time.perf_counter() - t0) >= cfg.time_budget_s:
                break
        visits = np.asarray(
            [c.N if c is not None else 0 for c in root.children], dtype=np.int64)
        total = int(visits.sum())
        if total > 0:
            pi = visits.astype(np.float64) / float(total)
            best_i = int(np.argmax(visits))
        else:
            pi = np.asarray(root.priors, dtype=np.float64).copy()
            best_i = int(np.argmax(pi)) if pi.size else 0
        best = root.macros[best_i] if root.macros else None
        n = len(root.macros or [])
        root_values = np.full(n, np.nan, dtype=np.float64)
        for i, child in enumerate(root.children):
            if child is not None and child.N > 0:
                root_values[i] = float(child.Q)
        for i, v in self._root_cache.items():
            if 0 <= int(i) < n and not np.isfinite(root_values[int(i)]):
                root_values[int(i)] = float(v)
        return SearchResult(
            best_macro=best, pi=pi, visits=visits,
            root_prior=np.asarray(root.priors, dtype=np.float64).copy(),
            simulations=int(cfg.simulations),
            elapsed_s=float(time.perf_counter() - t0),
            n_expansions=self._expansions,
            oracle_used=False,
            hidden_info_mode=info.mode,
            root_values=root_values,
            root_macros=tuple(root.macros or ()),
            best_index=int(best_i),
        )

    # ── 树操作 ──
    def _expand(self, node: Node, state: EngineForwardModel) -> None:
        """在当前 state 生成 macro 候选 + prior；不改变 state 外部对象。"""
        self._expansions += 1
        macros = generate_macros(
            state, self.evaluator, self.config, stats=self._rollout_stats)
        node.macros = list(macros)
        node.terminal = not macros
        if not macros:
            node.priors = np.zeros(0, dtype=np.float64)
        elif self.config.prior_mode == "uniform":
            node.priors = np.full(len(macros), 1.0 / len(macros), dtype=np.float64)
        else:
            ev = self.evaluator.evaluate(state)
            node.priors = ev.macro_priors(macros)
        node.init_children()

    def _select(self, node: Node) -> int:
        cfg = self.config
        n_total = max(1, int(node.N))
        best_i = 0
        best_score = -float("inf")
        priors = node.priors if node.priors is not None else np.zeros(0)
        for i in range(len(node.macros or [])):
            child = node.children[i]
            n_a = int(child.N) if child is not None else 0
            q = float(child.Q) if child is not None else 0.0
            p = float(priors[i]) if i < len(priors) else 0.0
            score = q + cfg.c_puct * p * math.sqrt(n_total) / (1.0 + n_a)
            if score > best_score:
                best_score = score
                best_i = i
        return best_i

    def _leaf_value(self, model: EngineForwardModel) -> float:
        if model.is_terminal():
            return float(model.terminal_utility())
        return float(self.evaluator.evaluate(model).value)

    def _combat_leaf_value(self, model: EngineForwardModel) -> float:
        """叶价值（Phase 1 快速路径）：simulate_turn_combat + BC value。

        比完整 ERP 便宜（3.51ms vs 12.96ms）；不做下一回合状态推进，
        因此只用于 depth-1 叶节点（跨回合仍用 ERP，见 ``_simulate``）。
        差距（combat leaf vs ERP leaf）在 bench 报告中单列，不声称等价。
        """
        if model.is_terminal():
            return float(model.terminal_utility())
        summary, dup = model.combat_leaf()
        if dup is not None:
            try:
                return float(self.evaluator.evaluate(dup).value)
            except Exception:  # noqa: BLE001
                pass
        return self._leaf_value(model)

    def _simulate_root_cached(self, root: Node) -> float:
        """Phase 1 根 macro bandit：K=1 确定性 ⇒ 每个 macro 只算一次真实结果。

        与逐 sim clone 的 MCTS 等价（无 chance/隐藏采样时），只省掉重复成本。
        """
        a = self._select(root)
        child = root.children[a]
        if child is None:
            child = Node(depth=1)
            root.children[a] = child
        value = self._root_cache.get(a)
        if value is None:
            model = self._root_world.clone() if self._root_world is not None \
                else self.model.clone()
            if self.config.leaf_mode == "combat":
                ok = model.apply_macro_before_end(root.macros[a])
                value = self._combat_leaf_value(model) if ok else -1.0
            else:
                ok = model.apply_macro(root.macros[a])
                value = self._leaf_value(model) if ok else -1.0
            self._root_cache[a] = float(value)
        root.N += 1
        root.value_sum += float(value)
        child.N += 1
        child.value_sum += float(value)
        return float(value)

    def _simulate(self, node: Node, model: EngineForwardModel) -> float:
        cfg = self.config
        if node.terminal or node.depth >= int(cfg.max_depth_turns):
            return self._leaf_value(model)
        if not node.expanded:
            self._expand(node, model.clone())
            if node.terminal:
                return self._leaf_value(model)
        a = self._select(node)
        macros = node.macros or []
        if a >= len(macros):
            return self._leaf_value(model)
        child = node.children[a]
        if child is None:
            child = Node(depth=node.depth + 1)
            node.children[a] = child
        is_leaf = int(child.depth) >= int(cfg.max_depth_turns)
        if is_leaf and cfg.leaf_mode == "combat":
            ok = model.apply_macro_before_end(macros[a])
            value = self._combat_leaf_value(model) if ok else self._leaf_value(model)
        else:
            ok = model.apply_macro(macros[a])
            if not ok or model.is_terminal():
                value = self._leaf_value(model)
            else:
                value = self._simulate(child, model)
        node.N += 1
        node.value_sum += float(value)
        child.N += 1
        child.value_sum += float(value)
        return float(value)

    # ── 调试 ──
    def stats(self) -> dict:
        return {
            "expansions": int(self._expansions),
            "rollout": self._rollout_stats.as_dict(),
        }


def run_search(model: EngineForwardModel,
               evaluator: PolicyEvaluator,
               config: Optional[SearchConfig] = None,
               *, bank: Optional[WarbandBank] = None) -> SearchResult:
    """便捷函数：``MCTS(model, evaluator, config).search()``。"""
    return MCTS(model, evaluator, config or SearchConfig(), bank=bank).search()
