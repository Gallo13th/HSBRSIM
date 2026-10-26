"""最小可运行的逐步 MCTS（hsbg_engine 版，用于训练管线 smoke 测试）。

注意：这是 M1 之前的**原型**，不是最终 Rust 搜索核：
- PUCT/备份/温度/合法掩码/EndTurn 对手推进都按设计文档实现；
- 每个节点持有 Game 拷贝（remote 实测 2.45µs）便于调试；性能未优化；
- 隐藏信息：只使用该座位 observe()，搜索内对手用策略网络（policy-only）推进，
  不做 determinization（后续由 BeliefSampler 接入）；
- 成对胜负矩阵（rank-level）暂未接入，价值用网络输出（smoke 用随机初始化也允许）。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, Tuple

import numpy as np

N_ACTIONS = 245
END_TURN = 0
N_PLAYERS = 8
UTILITY = np.array([1.0 - 2.0 * (r - 1) / (N_PLAYERS - 1) for r in range(1, N_PLAYERS + 1)],
                   dtype=np.float32)


@dataclass
class MCTSConfig:
    simulations: int = 2
    c_puct: float = 1.5
    temperature: float = 1.0
    dirichlet_alpha: float = 0.3
    dirichlet_epsilon: float = 0.0
    seed: int = 0


class Node:
    __slots__ = ("game", "seat", "prior", "counts", "wins", "value", "expanded", "children")

    def __init__(self, game, seat: int):
        self.game = game
        self.seat = seat
        self.prior = None       # np.float32[245]
        self.counts = np.zeros(N_ACTIONS, dtype=np.int32)
        self.wins = np.zeros(N_ACTIONS, dtype=np.float32)
        self.value = 0.0
        self.expanded = False
        self.children: Dict[int, "Node"] = {}


def _placement_utility(placements, seat: int) -> float:
    # placements[p] = 1..8
    r = int(placements[seat])
    if r <= 0:
        return 0.0
    return float(UTILITY[r - 1])


def _masked_policy(policy: np.ndarray, mask: np.ndarray) -> np.ndarray:
    p = np.asarray(policy, dtype=np.float32).copy()
    p[~mask] = 0.0
    s = p.sum()
    if s <= 0:
        return (mask.astype(np.float32) / max(mask.sum(), 1))
    return p / s


def _drive_opponents(game, seat: int):
    """推进直到 seat 需要动作或对局结束；搜索内其他座位用引擎 bot（快速）。

    说明：训练自对弈的“8 座全模型”由外层主循环保证；搜索内部的对手推进用 bot，
    是 smoke 阶段的近似（对手策略换成 league/历史回放留给 M1+）。
    """
    guard = 0
    while not game.is_over():
        if game.needs_action(seat):
            return
        moved = False
        for q in range(game.num_players):
            if q == seat:
                continue
            if game.needs_action(q):
                game.bot_play(q)
                moved = True
                guard += 1
                if guard > 2000:
                    raise RuntimeError("drive_opponents guard")
                break
        if not moved:
            return


class EngineMCTS:
    def __init__(self, evaluator: Callable, cfg: MCTSConfig):
        self.evaluator = evaluator
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.n_evals = 0

    # ---- internal ----
    @staticmethod
    def _obs(game, seat: int):
        f, c = game.observe(seat)
        return (np.frombuffer(f, dtype="<f4").copy(),
                np.frombuffer(c, dtype="<i4").copy())

    @staticmethod
    def _legal_mask(game, seat: int) -> np.ndarray:
        return np.frombuffer(game.legal_mask(seat), dtype=np.uint8).astype(bool)

    def _eval(self, game, seat: int):
        f, c = self._obs(game, seat)
        mask = self._legal_mask(game, seat)
        policy, value = self.evaluator(f, c, mask, seat)
        self.n_evals += 1
        return _masked_policy(policy, mask), float(value), mask

    def _policy_action(self, game, seat: int) -> int:
        f, c = self._obs(game, seat)
        mask = self._legal_mask(game, seat)
        policy, _ = self.evaluator(f, c, mask, seat)
        self.n_evals += 1
        p = _masked_policy(policy, mask)
        return int(np.argmax(p))

    def _expand(self, node: Node):
        game, seat = node.game, node.seat
        if game.is_over():
            return
        policy, value, _ = self._eval(game, seat)
        node.prior = policy
        node.value = value
        node.expanded = True

    def _select(self, node: Node) -> int:
        counts = node.counts.astype(np.float32)
        q = np.where(counts > 0, node.wins / np.maximum(counts, 1), 0.0)
        total = float(counts.sum())
        u = self.cfg.c_puct * node.prior * math.sqrt(max(total, 1.0)) / (1.0 + counts)
        score = q + u
        # 只在合法动作中选（prior 已 mask）
        return int(np.argmax(score))

    def _step_copy(self, game, seat: int, action: int):
        g = game.copy()
        g.step(seat, action)
        _drive_opponents(g, seat)
        return g

    def _simulate(self, root: Node) -> None:
        node = root
        path = []  # (parent, action)
        while True:
            if node.game.is_over():
                v = _placement_utility(node.game.placements(), node.seat)
                break
            if not node.expanded:
                self._expand(node)
                v = node.value
                break
            a = self._select(node)
            child = node.children.get(a)
            if child is None:
                child = Node(self._step_copy(node.game, node.seat, a), node.seat)
                node.children[a] = child
            path.append((node, a))
            node = child
        for parent, a in path:
            parent.counts[a] += 1
            parent.wins[a] += v

    def search(self, game, seat: int) -> Tuple[np.ndarray, int, Dict]:
        root = Node(game.copy(), seat)
        self._expand(root)
        if self.cfg.dirichlet_epsilon > 0:
            noise = np.random.default_rng(self.cfg.seed).dirichlet(
                [self.cfg.dirichlet_alpha] * N_ACTIONS)
            root.prior = (1.0 - self.cfg.dirichlet_epsilon) * root.prior + \
                self.cfg.dirichlet_epsilon * noise.astype(np.float32)
            root.prior = _masked_policy(root.prior, self._legal_mask(game, seat))
        for _ in range(max(0, self.cfg.simulations)):
            self._simulate(root)
        counts = root.counts.astype(np.float32)
        if counts.sum() <= 0:
            pi = root.prior.copy() if root.prior is not None else np.ones(N_ACTIONS, np.float32) / N_ACTIONS
        else:
            tau = max(self.cfg.temperature, 1e-6)
            pi = np.power(np.maximum(counts, 0) + 1e-8, 1.0 / tau)
            pi = pi / pi.sum()
        u = self.rng.random()
        cum = np.cumsum(pi.astype(np.float64))
        action = int(np.searchsorted(cum, u * cum[-1]))
        action = max(0, min(N_ACTIONS - 1, action))
        stats = {"root_value": float(root.value), "visits": int(counts.sum()),
                 "n_evals": self.n_evals}
        return pi.astype(np.float32), action, stats


def search(game, seat: int, evaluator: Callable, cfg: MCTSConfig):
    return EngineMCTS(evaluator, cfg).search(game, seat)
