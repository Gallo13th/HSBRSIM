"""沙盒 PUCT/MCTS：在 ``economy_sandbox`` 上产出「搜索改进后的策略」π。

为什么需要它
------------
``docs/ECONOMY_SANDBOX.md`` §9 的结论：沙盒 PPO 从 ±1e-3 的 advantage 里学不出
「买载体 → 反复施法 → 复利」这条多回合链（12M 决策后部署金币下反而 −60%）。
沙盒一局只有 ~22 ms（无战斗/无淘汰），所以可以在**关键决策**上跑 MCTS，把
``(obs → π_search)`` 当监督标签做离线 BC / DAgger，而不是让 PPO 自己找。

搜索契约
--------
- **先验**：现有 entity 策略头（245 维 masked softmax），每步 64–256 次模拟；
- **叶评估**：entity 的 scalar value 头。value 头在沙盒里训练时的目标是
  ``L_T - L(s)``（``L = log1p(Σ)/log1p(30000)``，奖励望远镜求和 = ``L_T``），
  所以叶子的终局强度估计是 ``L(s_leaf) + V(s_leaf)``（``--search-value-mode total``，
  默认）。**注意**：完整游戏 checkpoint（s14/s16）的 scalar 头在训练里
  ``value_head_coef=0``（只训 rank 头），直接拿来当叶评估是**随机头**；用
  ``scripts/gen_sandbox_search_labels.py --fit-value-games N`` 先在沙盒里把
  value 头拟合到 ``L_T - L(s)``（trunk 冻结，只训头）。
- **只搜关键决策**（``--search-topk 8``）：根节点只保留策略概率最高的 8 个合法
  动作（默认再剔除 Move 段 196..244 —— 沙盒无战斗，换位不改变强度）；其余步直接
  按策略。每回合搜索次数上限 ``--search-max-per-turn``。
- **预算**：``--search-sims``（默认 128）、``--search-depth``（向前看几个回合的
  recruit 末，默认 1 = 本回合末）、``--search-max-plies``（硬上限）。
- **状态转移**：直接用引擎 ``Game.copy()``（~8 µs）+ ``EconomySandbox.search_step``
  （与 ``step`` 同一状态机：新回合注入金币/回血、其余座位立刻 EndTurn）。

输出
----
每个搜索决策返回 :class:`SearchResult`：访问分布 ``pi``（稀疏 top-k）、根动作
Q 值、模拟次数与耗时。批量接口 :class:`SearchRunner` 在多个并行局之间**批量**
评估叶子（一次前向 B 条），这是 500 局标签生成能跑得动的关键。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .economy_sandbox import (END_TURN, N_ACTIONS, SEAT, EconomySandbox,
                              SandboxConfig, SandboxObs, stack_obs)

#: 动作段名字（与 ``docs/ACTION_SPACE_STD.md`` 一致）
_UTIL_SEGMENTS = {0: "end", 1: "refresh", 2: "freeze", 3: "upgrade",
                  4: "hero_power", 5: "hero_power2", 6: "dark_gift", 7: "cancel"}

#: 默认「关键决策」段：会改变战团/缩放链条的动作
DEFAULT_KEY_SEGMENTS = ("buy", "sell", "activate", "choose", "play", "magnetize",
                        "upgrade", "hero_power", "dark_gift")

#: Move 段（196..244）：沙盒无战斗 ⇒ 纯噪声
MOVE_LO, MOVE_HI = 196, 245


def action_kind(a: int) -> str:
    """动作下标 -> 段名。"""
    a = int(a)
    if a < 8:
        return _UTIL_SEGMENTS.get(a, "util")
    if a < 16:
        return "buy"
    if a < 23:
        return "sell"
    if a < 30:
        return "activate"
    if a < 46:
        return "choose"
    if a < 126:
        return "play"
    if a < MOVE_LO:
        return "magnetize"
    if a < MOVE_HI:
        return "move"
    return "out"


# ── 配置 ────────────────────────────────────────────────────────────────────


@dataclass
class SearchConfig:
    """PUCT 预算与开关（默认值 = 任务给的 128 sims / top-8 / 本回合末）。"""

    sims: int = 128
    #: 根节点候选集：策略概率 top-k（0/负数 = 全部合法）
    topk: int = 8
    #: 向前看几个**回合**（1 = 到本回合末；3 = 三个回合）
    depth_turns: int = 1
    #: 单条路径的最大步数（硬上限，防止 pending 链过长）
    max_plies: int = 64
    c_puct: float = 1.5
    #: 未访问动作的 Q 初值 = 父节点 value 估计（first-play urgency）
    fpu_use_parent: bool = True
    #: 根 Dirichlet 噪声（标签生成默认 0 = 纯利用）
    root_noise: float = 0.0
    root_noise_alpha: float = 0.3
    #: 叶值口径：``total`` = L(s)+V(s)（推荐）；``raw`` = V(s)
    value_mode: str = "total"
    #: 每个**搜索步**最多搜多少个关键决策（0 = 不限）
    max_searches_per_turn: int = 8
    #: 关键决策的动作段（逗号分隔；空 = 所有段）
    key_segments: str = ",".join(DEFAULT_KEY_SEGMENTS)
    #: 搜索时剔除 Move 段（沙盒无战斗，换位不改变强度）
    skip_move: bool = True
    #: 至少多少个合法动作才值得搜
    min_legal: int = 2
    #: π 的温度（τ=1 = 按访问次数；τ→0 = argmax）
    temperature: float = 1.0
    #: 完全展开后是否继续模拟（内部节点候选用尽时重复访问，默认 True）
    repeat_visits: bool = True

    def key_set(self) -> set:
        raw = str(self.key_segments or "").strip()
        if not raw:
            return set()
        return {x.strip() for x in raw.split(",") if x.strip()}

    def validate(self) -> None:
        if int(self.sims) < 1:
            raise ValueError("sims 必须 >= 1")
        if int(self.topk) < 1:
            raise ValueError("topk 必须 >= 1")
        if int(self.depth_turns) < 1:
            raise ValueError("depth_turns 必须 >= 1")
        if float(self.c_puct) <= 0.0:
            raise ValueError("c_puct 必须 > 0")
        if str(self.value_mode) not in ("total", "raw"):
            raise ValueError("value_mode 只能是 total|raw")


def should_search(obs: SandboxObs, cfg: SearchConfig, *, searched_this_turn: int,
                  prior: Optional[np.ndarray] = None) -> bool:
    """这个决策值不值得跑搜索（关键段 + 合法数 + 每回合预算）。

    「关键」判定用**策略 top-1**（给了 ``prior`` 时）或 mask 里是否出现关键段：
    看 top-1 是为了不把「策略本来就想 Move/EndTurn」的步也拿来搜。
    """
    if int(cfg.max_searches_per_turn) > 0 and int(searched_this_turn) >= int(cfg.max_searches_per_turn):
        return False
    mask = np.asarray(obs.mask, dtype=bool)
    legal = np.flatnonzero(mask)
    if legal.size < int(cfg.min_legal):
        return False
    if prior is not None and legal.size:
        p = np.asarray(prior, dtype=np.float64)[legal]
        top = int(legal[int(np.argmax(p))]) if p.size else int(legal[0])
        kind = action_kind(top)
    else:
        kinds = {action_kind(int(a)) for a in legal}
        key = cfg.key_set()
        return (not key) or bool(kinds & key)
    key = cfg.key_set()
    if key and kind not in key:
        return False
    if bool(cfg.skip_move) and MOVE_LO <= top < MOVE_HI:
        return False
    # 除 top-1 外还得有可搜的候选（至少 2 个非 move 合法动作）
    n_cand = int(legal.size)
    if bool(cfg.skip_move):
        n_cand = int(((legal < MOVE_LO) | (legal >= MOVE_HI)).sum())
    return n_cand >= int(cfg.min_legal)


# ── 树节点 ──────────────────────────────────────────────────────────────────


class _Node:
    """PUCT 节点：一局沙盒状态 + 该状态的先验/价值 + 子边统计。"""

    __slots__ = ("env", "turn", "ply", "feats", "cards", "mask", "prior", "cands",
                 "value_est", "sigma", "terminal", "term_value", "children",
                 "N", "W", "n_total")

    def __init__(self, *, env: EconomySandbox, turn: int, ply: int,
                 feats: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                 sigma: float) -> None:
        self.env = env
        self.turn = int(turn)
        self.ply = int(ply)
        self.feats = feats
        self.cards = cards
        self.mask = mask
        self.sigma = float(sigma)
        self.prior = np.zeros(N_ACTIONS, dtype=np.float32)
        self.cands = np.zeros(0, dtype=np.int32)
        self.value_est = 0.0
        self.terminal = False
        self.term_value = 0.0
        self.children: Dict[int, "_Node"] = {}
        self.N = np.zeros(N_ACTIONS, dtype=np.int32)
        self.W = np.zeros(N_ACTIONS, dtype=np.float32)
        self.n_total = 0


@dataclass
class SearchResult:
    """一个决策的搜索结果。"""

    pi: np.ndarray                  # f32[245]，稀疏（只在候选动作上有质量）
    cands: np.ndarray               # 候选动作（按先验降序）
    q: Dict[int, float]             # 根动作 Q（final-L 估计）
    visits: Dict[int, int]
    root_value: float               # 根状态的 L+V（终局强度估计）
    root_sigma: int
    sims: int
    elapsed_s: float
    expanded_nodes: int
    leaf_value_calls: int

    def top_pi(self, k: int = 8) -> List[List[float]]:
        """稀疏 top-k：``[[action, prob], ...]``（按 prob 降序，和 = 1 内）。"""
        p = np.asarray(self.pi, dtype=np.float64)
        nz = np.flatnonzero(p > 0)
        if nz.size == 0:
            return []
        order = nz[np.argsort(-p[nz])][:int(k)]
        return [[int(a), float(p[a])] for a in order]

    def top1(self) -> int:
        p = np.asarray(self.pi, dtype=np.float64)
        return int(np.argmax(p)) if p.size else END_TURN


class SandboxTree:
    """单局 PUCT 树；``simulate()`` 一次模拟，必要时用 ``finish(prior, value)`` 收尾。"""

    def __init__(self, env: EconomySandbox, feats: np.ndarray, cards: np.ndarray,
                 mask: np.ndarray, prior: np.ndarray, value: float,
                 cfg: SearchConfig, *, rng: Optional[np.random.Generator] = None) -> None:
        self.cfg = cfg
        self.rng = rng or np.random.default_rng(0)
        sigma = EconomySandbox.sigma_from_features(feats)
        root = _Node(env=env, turn=int(env.g.turn), ply=0, feats=feats, cards=cards,
                     mask=mask, sigma=sigma)
        self._init_prior(root, prior)
        root.value_est = self._leaf_value(sigma, float(value))
        self.root = root
        self._path: List[Tuple[_Node, int]] = []
        self._pending: Optional[_Node] = None
        self.n_leaf_calls = 0
        self.n_nodes = 1

    # ── 先验 / 价值 ──────────────────────────────────────────────────────
    def _leaf_value(self, sigma: float, value: float) -> float:
        if str(self.cfg.value_mode) == "raw":
            return float(value)
        return float(_L(sigma)) + float(value)

    def _init_prior(self, node: _Node, prior: np.ndarray) -> None:
        mask = np.asarray(node.mask, dtype=bool)
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            node.cands = np.zeros(0, dtype=np.int32)
            return
        pool = legal
        if bool(self.cfg.skip_move):
            keep = (pool < MOVE_LO) | (pool >= MOVE_HI)
            pool = pool[keep]
        if pool.size == 0:
            node.cands = np.zeros(0, dtype=np.int32)
            return
        p = np.asarray(prior, dtype=np.float64)[pool]
        p = np.where(np.isfinite(p) & (p > 0), p, 0.0)
        if float(p.sum()) <= 0.0:
            p = np.ones(pool.size, dtype=np.float64)
        if int(self.cfg.topk) > 0 and pool.size > int(self.cfg.topk):
            order = np.argsort(-p, kind="stable")[:int(self.cfg.topk)]
            pool = pool[order]
            p = p[order]
        order = np.argsort(-p, kind="stable")
        pool = np.asarray(pool, dtype=np.int64)[order]
        p = np.asarray(p, dtype=np.float64)[order]
        q = np.zeros(N_ACTIONS, dtype=np.float32)
        q[pool] = (p / max(float(p.sum()), 1e-12)).astype(np.float32)
        node.cands = pool.astype(np.int32)
        node.prior = q
        # 根噪声（默认 0）
        if self.cfg.root_noise > 0.0 and pool.size > 1:
            eps = float(np.clip(self.cfg.root_noise, 0.0, 1.0))
            draws = self.rng.dirichlet(
                np.full(pool.size, float(self.cfg.root_noise_alpha)))
            node.prior[pool] = ((1.0 - eps) * node.prior[pool]
                                + eps * draws.astype(np.float32))

    # ── 选择 / 展开 / 回传 ───────────────────────────────────────────────
    def _select(self, node: _Node) -> int:
        cands = node.cands
        if cands.size == 0:
            return END_TURN
        # 先补齐「未访问」候选（按先验顺序各访问一次）：低 c_puct 下 Q 才有机会说话；
        # 否则首访 Q 用父值、探索项又小，树会只沿先验 top-1 展开（实测 π≈π_base）。
        unv = cands[node.N[cands] == 0]
        if unv.size:
            return int(unv[0])
        if node.n_total == 0:
            return int(cands[0])
        n = node.N[cands].astype(np.float64)
        w = node.W[cands].astype(np.float64)
        q0 = node.value_est if bool(self.cfg.fpu_use_parent) else 0.0
        q = np.where(n > 0, w / np.maximum(n, 1.0), q0)
        u = (float(self.cfg.c_puct) * node.prior[cands].astype(np.float64)
             * math.sqrt(float(node.n_total) + 1.0) / (1.0 + n))
        return int(cands[int(np.argmax(q + u))])

    def _make_child(self, node: _Node, action: int) -> _Node:
        g2 = node.env.clone()
        g2.search_step(int(action))
        sigma = float(node.sigma)          # 终局/深度截断用的最后已知 Σ
        if bool(g2.g.is_over()):
            child = _Node(env=g2, turn=int(g2.g.turn), ply=node.ply + 1,
                          feats=node.feats, cards=node.cards, mask=node.mask,
                          sigma=sigma)
            child.terminal = True
            child.term_value = float(_L(sigma))
            return child
        obs = g2.obs()
        sigma = float(EconomySandbox.sigma_from_features(obs.features))
        child = _Node(env=g2, turn=int(obs.turn), ply=node.ply + 1,
                      feats=obs.features, cards=obs.cards, mask=obs.mask, sigma=sigma)
        self.n_nodes += 1
        return child

    def _backup(self, value: float) -> None:
        for node, a in reversed(self._path):
            node.N[a] += 1
            node.W[a] += float(value)
            node.n_total += 1
        self._path = []

    def simulate(self) -> Optional[_Node]:
        """跑一次模拟；返回需要网络评估的叶子（调用方随后 ``finish``），否则 ``None``。"""
        self._pending = None
        self._path = []
        node = self.root
        while True:
            if node.terminal:
                self._backup(node.term_value)
                return None
            if node.cands.size == 0:
                # 没有可搜候选（全是 Move / 无合法动作）：按当前价值收尾，不落子
                self._backup(node.value_est)
                return None
            if (node.ply >= int(self.cfg.max_plies)
                    or (node.turn - self.root.turn) >= int(self.cfg.depth_turns)):
                self._backup(node.value_est)
                return None
            a = self._select(node)
            self._path.append((node, int(a)))
            child = node.children.get(int(a))
            if child is None:
                child = self._make_child(node, int(a))
                node.children[int(a)] = child
                if child.terminal:
                    self._backup(child.term_value)
                    return None
                self._pending = child
                return child
            node = child

    def finish(self, prior: np.ndarray, value: float) -> None:
        """用网络评估结果收尾当前 pending 叶（先验 + 价值 + 回传）。"""
        leaf = self._pending
        self._pending = None
        if leaf is None:
            return
        self._init_prior(leaf, prior)
        leaf.value_est = self._leaf_value(leaf.sigma, float(value))
        self.n_leaf_calls += 1
        self._backup(leaf.value_est)

    # ── 结果 ────────────────────────────────────────────────────────────
    def result(self, elapsed_s: float = 0.0, sims: int = 0) -> SearchResult:
        root = self.root
        counts = root.N.astype(np.float64)
        total = float(counts.sum())
        pi = np.zeros(N_ACTIONS, dtype=np.float32)
        if total <= 0.0:
            pi[root.cands] = root.prior[root.cands]
        else:
            pi[root.cands] = (counts[root.cands] / total).astype(np.float32)
        s = float(pi.sum())
        if s > 0:
            pi /= s
        q: Dict[int, float] = {}
        visits: Dict[int, int] = {}
        for a in root.cands:
            visits[int(a)] = int(root.N[a])
            q[int(a)] = (float(root.W[a]) / float(root.N[a])
                         if root.N[a] > 0 else float(root.value_est))
        if float(self.cfg.temperature) <= 0.0 and int(pi.argmax()) >= 0:
            best = int(pi.argmax())
            pi = np.zeros(N_ACTIONS, dtype=np.float32)
            pi[best] = 1.0
        return SearchResult(pi=pi, cands=np.asarray(root.cands, dtype=np.int32),
                            q=q, visits=visits, root_value=float(root.value_est),
                            root_sigma=int(round(float(root.sigma))),
                            sims=int(sims), elapsed_s=float(elapsed_s),
                            expanded_nodes=int(self.n_nodes),
                            leaf_value_calls=int(self.n_leaf_calls))


def _L(sigma: float) -> float:
    """与 ``EconomySandbox`` 同一强度曲线：``log1p(Σ)/log1p(30000)``。"""
    return math.log1p(max(0.0, float(sigma))) / math.log1p(float(30000.0))


# ── 批量搜索（跨局共享一次前向）────────────────────────────────────────────


class SearchRunner:
    """跑 PUCT，把多局的叶评估**批量**送进网络（一次前向 B 条叶子）。

    ``dtype`` 与 ``scripts/train_economy_sandbox.batch_act`` 同口径（默认 fp32；
    采集/训练用 bf16 时这里也要 bf16，否则价值/先验会偏）。
    """

    def __init__(self, model: Any, device: str = "cuda", cfg: Optional[SearchConfig] = None,
                 *, dtype: str = "fp32", chunk: int = 256) -> None:
        import torch
        self.torch = torch
        self.model = model
        self.device = torch.device(device)
        self.cfg = cfg or SearchConfig()
        self.cfg.validate()
        self.dtype = str(dtype)
        self.chunk = int(chunk)
        self.model.to(self.device)

    def _autocast(self):
        t = self.torch
        if self.dtype == "bf16" and t.cuda.is_available():
            return t.autocast("cuda", dtype=t.bfloat16)
        import contextlib
        return contextlib.nullcontext()

    def evaluate(self, feats: np.ndarray, cards: np.ndarray,
                 masks: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """批量叶评估：``(prior[B,245], value[B])``（prior 已按 mask 归一化）。"""
        t = self.torch
        from .ppo import forward_model
        n = int(len(masks))
        prior = np.zeros((n, N_ACTIONS), dtype=np.float32)
        value = np.zeros(n, dtype=np.float32)
        self.model.eval()
        with t.no_grad(), self._autocast():
            for s in range(0, n, self.chunk):
                e = min(n, s + self.chunk)
                f = t.from_numpy(np.ascontiguousarray(feats[s:e], dtype=np.float32)).to(self.device)
                c = t.from_numpy(np.ascontiguousarray(cards[s:e], dtype=np.int64)).to(self.device)
                m = t.from_numpy(np.ascontiguousarray(masks[s:e], dtype=bool)).to(self.device)
                logits, _rank, val = forward_model(self.model, f, c, m)
                logits = logits.float().masked_fill(~m, -1e9)
                p = t.softmax(logits, dim=-1)
                prior[s:e] = p.detach().cpu().numpy()
                if val is not None:
                    value[s:e] = val.detach().float().cpu().numpy()
        return prior, value

    def run(self, envs: Sequence[EconomySandbox], feats: np.ndarray,
            cards: np.ndarray, masks: np.ndarray, priors: np.ndarray,
            values: np.ndarray, *, seeds: Optional[Sequence[int]] = None,
            progress: bool = False) -> List[SearchResult]:
        """对一批局各建一棵树并跑 ``cfg.sims`` 次模拟（跨局批量评估叶子）。"""
        t0 = time.time()
        trees: List[SandboxTree] = []
        for i, env in enumerate(envs):
            rng = np.random.default_rng(0 if seeds is None else int(seeds[i]))
            trees.append(SandboxTree(env, feats[i], cards[i], masks[i],
                                     priors[i], float(values[i]), self.cfg, rng=rng))
        active = list(range(len(trees)))
        for _it in range(int(self.cfg.sims)):
            if not active:
                break
            pending: List[int] = []
            for i in active:
                leaf = trees[i].simulate()
                if leaf is not None:
                    pending.append(i)
            if not pending:
                continue
            f = np.stack([trees[i]._pending.feats for i in pending])  # type: ignore[union-attr]
            c = np.stack([trees[i]._pending.cards for i in pending])  # type: ignore[union-attr]
            m = np.stack([trees[i]._pending.mask for i in pending])   # type: ignore[union-attr]
            p, v = self.evaluate(f, c, m)
            for j, i in enumerate(pending):
                trees[i].finish(p[j], float(v[j]))
        elapsed = time.time() - t0
        per = elapsed / max(1, len(trees))
        return [tree.result(elapsed_s=per, sims=int(self.cfg.sims)) for tree in trees]


# ── 便捷：单局搜索（诊断 / 测试）────────────────────────────────────────────


def search_step(env: EconomySandbox, model: Any, device: str = "cuda",
                cfg: Optional[SearchConfig] = None, *, dtype: str = "fp32") -> SearchResult:
    """对当前状态跑一次搜索（单局、非批量；测试/诊断用）。"""
    c = cfg or SearchConfig()
    runner = SearchRunner(model, device=device, cfg=c, dtype=dtype)
    obs = env.obs()
    f, cc, m = stack_obs([obs])
    p, v = runner.evaluate(f, cc, m)
    return runner.run([env], f, cc, m, p, v)[0]


def result_summary(res: SearchResult, k: int = 8) -> Dict[str, Any]:
    """把搜索结果压成可写 JSON 的精简结构（标签 / 报告用）。"""
    top = res.top_pi(k)
    return {"pi_topk": top, "top1": res.top1(),
            "q": {str(a): round(q, 4) for a, q in sorted(res.q.items())},
            "visits": {str(a): n for a, n in sorted(res.visits.items())},
            "root_value": round(float(res.root_value), 4),
            "root_sigma": int(res.root_sigma),
            "sims": int(res.sims), "elapsed_s": round(float(res.elapsed_s), 4),
            "nodes": int(res.expanded_nodes), "leaf_calls": int(res.leaf_value_calls)}
