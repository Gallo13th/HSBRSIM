"""沙盒 rollout 叶评估搜索（搜索标签 v2）。

对应 ``docs/ECONOMY_SANDBOX.md`` §10 的三条改进（v1 的失败原因见那一节）：

1. **叶值 = 回合末真实 Σ（rollout 评估）**：v1 用 entity 的 scalar value 头估叶子，
   而完整游戏 checkpoint 的 value 头在训练里 ``value_head_coef=0``（只训 rank 头），
   拟合后对单步动作的 Spearman 也只有 0.25、Q 的跨动作标准差 0.034 vs 头残差 0.037。
   v2 直接**执行候选动作后用当前策略 rollout 到本回合末**，叶值 =
   ``log1p(回合末战团 Σ)``（可加权叠加 tier / 载体项）。跨候选、跨局 lockstep 批量
   前向，所以 8 候选 × 20 步的代价是一次批量 forward 而不是 160 次。
2. **只搜关键决策**：``search_when`` 用观测里能直接解码的事实判定（``carrier_in_shop``
   / ``carrier_in_hand`` / ``spell_in_hand`` / ``carrier_on_board`` / ``tier4plus`` /
   ``carrier_or_spell`` / ``any``），每回合最多 ``max_searches_per_turn``（默认 3）次；
   其余决策直接用 π_base。
3. **DAgger 式标签的数据口径**：行为**永远**是 π_base（``sample``），搜索只用来产生
   标签 π_search。本模块只负责「给定决策 → π_search」；行为/记录在
   ``scripts/gen_search_labels_v2.py``。

与 v1 PUCT 的关系
------------------
v1 的 PUCT 用 ``c_puct`` 探索项分配访问次数；因为 Q 的跨动作差极小，默认
``c_puct=1.5`` 时 KL(π_search‖π_base) 只有 0.011（≈自蒸馏），把 c_puct 压到 0.25 又
让行为更差。v2 不再用探索预算分配 π，而是：

- 候选集 = π_base 概率 top-k 的**非 Move 合法动作**（含 π_base top-1）；
- 对**每个候选**跑一条 rollout → 叶分 Q(a)；
- 基线 ``V = Σ_a p̃(a)·Q(a)``（p̃ = 候选上归一化的 π_base），优势 ``A(a) = Q(a) − V``；
- ``π_search(a) ∝ p̃(a)·exp(A(a)/τ)``，τ 自适应（``q_temp_scale × std(Q)``），
  所以「搜索发现的更好动作」直接拿到标签质量，不再被探索项稀释。

接口
----
``RolloutSearcher.policy(feats, cards, masks) -> (prior, value)``
``RolloutSearcher.search(envs, feats, cards, masks, priors) -> list[RolloutResult]``

``RolloutResult`` 里带每个候选的 ``q`` / ``sigma_end``（回合末 Σ）/ ``steps``，
因此可以直接做「**搜索动作 vs 策略动作的回合末 Σ 差**」这个诊断。
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .economy_sandbox import (END_TURN, N_ACTIONS, SEAT, EconomySandbox,
                              SandboxConfig, SandboxObs, carrier_ids, stack_obs)
from .sandbox_search import (MOVE_HI, MOVE_LO, SearchConfig, SearchRunner,
                             action_kind)

STRENGTH_REF = 30000.0

# ── 冻结的 obs 布局（hsbg/env/obs_std.py）──────────────────────────────────
#: 卡牌块：board(7) / hand(10) / shop(8)（= cards[19:26] / [26:36] / [36:44]）
CARD_BOARD = slice(19, 26)
CARD_HAND = slice(26, 36)
CARD_SHOP = slice(36, 44)
#: global 块：tier = features[10] * 6，board Σ 在 features[68:285]（7×31）
FEAT_TIER = 10
FEAT_TIER_SCALE = 6.0

#: 手牌里的「法术」kind（酒馆法术 + 普通法术）
SPELL_KINDS = ("tavern_spell", "spell")

#: ``--search-when`` 支持的全部名字（``carrier_or_spell`` / ``any`` 是组合别名）
SEARCH_WHEN_NAMES = ("carrier_in_shop", "carrier_in_hand", "spell_in_hand",
                     "carrier_on_board", "tier4plus", "carrier_or_spell", "any")


def _L(sigma: float) -> float:
    """与 ``EconomySandbox`` 同一强度曲线：``log1p(Σ)/log1p(30000)``。"""
    return math.log1p(max(0.0, float(sigma))) / math.log1p(STRENGTH_REF)


# ── 卡表 / 载体表（每个 searcher 建一次，避免每次决策读文件）────────────────


def card_tables() -> Dict[str, Any]:
    """``cid -> id`` 与 ``id -> kind``（引擎不可用时返回空表，不阻断）。"""
    out: Dict[str, Any] = {"cid2id": {}, "id2kind": {}}
    try:
        import hsbg_engine as E
        cards = json.loads(E.catalog_json())
    except Exception:  # noqa: BLE001 - 无引擎时载体/法术判定恒 False
        return out
    for c in cards:
        try:
            cid = int(c.get("cid"))
            cid_str = str(c.get("id") or "")
        except (TypeError, ValueError):
            continue
        out["cid2id"][cid] = cid_str
        out["id2kind"][cid_str] = str(c.get("kind") or "")
    return out


# ── 关键决策判定（观测可解码的事实）────────────────────────────────────────


def search_when_names(when: str) -> Tuple[str, ...]:
    """把 ``--search-when`` 解析成原子标签（别名展开；``any`` 短路）。"""
    raw = [x.strip() for x in str(when or "").split(",") if x.strip()]
    if not raw:
        return ("any",)
    out: List[str] = []
    for name in raw:
        if name not in SEARCH_WHEN_NAMES:
            raise ValueError(f"search_when 未知项 {name!r}，可选：{SEARCH_WHEN_NAMES}")
        if name == "any":
            return ("any",)
        if name == "carrier_or_spell":
            out.extend(["carrier_in_shop", "carrier_in_hand", "spell_in_hand"])
        else:
            out.append(name)
    return tuple(dict.fromkeys(out))


@dataclass
class DecisionTags:
    """一次决策点能从观测直接解码的事实（用于 search_when + 叶值附加项）。"""

    sigma: int = 0
    tier: int = 0
    carriers_board: int = 0
    carrier_in_shop: int = 0
    carrier_in_hand: int = 0
    spell_in_hand: int = 0
    shop_n: int = 0
    hand_n: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {"sigma": int(self.sigma), "tier": int(self.tier),
                "carriers_board": int(self.carriers_board),
                "carrier_in_shop": int(self.carrier_in_shop),
                "carrier_in_hand": int(self.carrier_in_hand),
                "spell_in_hand": int(self.spell_in_hand)}


def tag_matches(tags: DecisionTags, names: Sequence[str]) -> bool:
    """原子标签匹配（``any`` 恒 True）。"""
    for name in names:
        if name == "any":
            return True
        if name == "tier4plus":
            if int(tags.tier) >= 4:
                return True
        elif name == "carrier_in_shop":
            if int(tags.carrier_in_shop) > 0:
                return True
        elif name == "carrier_in_hand":
            if int(tags.carrier_in_hand) > 0:
                return True
        elif name == "spell_in_hand":
            if int(tags.spell_in_hand) > 0:
                return True
        elif name == "carrier_on_board":
            if int(tags.carriers_board) > 0:
                return True
        else:
            raise ValueError(f"未知原子标签 {name!r}")
    return False


def sigmas_from_features(feats: np.ndarray) -> np.ndarray:
    """批量解码战团 Σ（与 ``EconomySandbox.sigma_from_features`` 同口径）。"""
    f = np.asarray(feats, dtype=np.float32)
    if f.ndim == 1:
        f = f[None, :]
    b = f[:, 68:285].reshape(len(f), 7, 31)
    present = b[:, :, 0] > 0.5
    sig = (b[:, :, 1] + b[:, :, 2]) * present
    return np.rint(sig.sum(axis=1) * 10.0).astype(np.int64)


# ── 配置 ────────────────────────────────────────────────────────────────────


@dataclass
class RolloutConfig:
    """rollout 叶评估搜索的预算与口径。"""

    #: 根候选数 = π_base top-k（非 Move 合法动作；0/负 = 全部非 Move）
    topk: int = 8
    #: 单条 rollout 的最大决策步数（硬上限；沙盒每回合动作上限 40）
    max_steps: int = 128
    #: 向前 rollout 几个回合（1 = 到本回合末；2/3 = 多回合复利）
    turns: int = 1
    #: rollout 行为：``greedy``（确定性，叶值 = 该动作后的精确结果）
    #: 或 ``sample``（按 π_base 采样，期望意义下的价值，= 部署口径）
    rollout_mode: str = "greedy"
    #: ``rollout_mode=sample`` 时每个候选采样几条轨迹（公共随机数；K>1 降方差）
    rollout_samples: int = 1
    #: π_search 构造：``advantage``（p̃·exp(A/τ)）/ ``softmax``（只按 Q）
    pi_mode: str = "advantage"
    #: τ（L 单位）；>0 固定，0 = 自适应 ``q_temp_scale × std(Q)``
    q_temp: float = 0.0
    q_temp_scale: float = 1.0
    min_temp: float = 1e-4
    #: 优势项裁剪（nats）：``clip(A/τ, ±adv_clip)``。30 = 近乎不裁（原始口径）；
    #: 3–6 = KL 信任域（防止「先验饱和的决策被微小 Q 差整条翻转」）
    adv_clip: float = 30.0
    #: 叶值附加项（默认 0 = 纯 log1p(回合末 Σ)，即任务口径）
    tier_bonus: float = 0.0
    carrier_bonus: float = 0.0
    #: 搜索候选剔除 Move 段（沙盒无战斗 ⇒ 换位不改变强度）
    skip_move: bool = True
    #: 至少多少个候选才值得搜
    min_cands: int = 2
    #: 关键决策口径（见 SEARCH_WHEN_NAMES）
    search_when: str = "carrier_or_spell"
    #: 每回合最多搜索几次
    max_searches_per_turn: int = 3
    #: rollout 采样（rollout_mode=sample）的随机种子基准
    seed: int = 0

    def validate(self) -> None:
        if int(self.topk) == 0:
            raise ValueError("topk 不能为 0（<=0 表示全部）")
        if int(self.max_steps) < 1:
            raise ValueError("max_steps 必须 >= 1")
        if int(self.turns) < 1:
            raise ValueError("turns 必须 >= 1")
        if str(self.rollout_mode) not in ("greedy", "sample"):
            raise ValueError("rollout_mode 只能是 greedy|sample")
        if int(self.rollout_samples) < 1:
            raise ValueError("rollout_samples 必须 >= 1")
        if str(self.pi_mode) not in ("advantage", "softmax"):
            raise ValueError("pi_mode 只能是 advantage|softmax")
        if float(self.q_temp) < 0.0:
            raise ValueError("q_temp 必须 >= 0（0 = 自适应）")
        if float(self.q_temp_scale) <= 0.0:
            raise ValueError("q_temp_scale 必须 > 0")
        if int(self.max_searches_per_turn) < 0:
            raise ValueError("max_searches_per_turn 必须 >= 0（0 = 不限）")
        search_when_names(self.search_when)   # 触发校验

    @property
    def search_when_tags(self) -> Tuple[str, ...]:
        return search_when_names(self.search_when)


# ── 结果 ────────────────────────────────────────────────────────────────────


@dataclass
class RolloutResult:
    """一个决策的 rollout 搜索结果（π + 每个候选的叶值真值）。"""

    pi: np.ndarray                 # f32[245]，支撑 = cands
    cands: np.ndarray              # i32[n]，按 π_base 先验降序
    q: np.ndarray                  # f64[n]，叶分 = L(Σ_end) + bonus
    sigma_end: np.ndarray          # i64[n]，回合末战团 Σ（真值）
    tier_end: np.ndarray           # i64[n]
    carriers_end: np.ndarray       # i64[n]
    base: int                      # π_base top-1（候选里先验最高）
    base_q: float
    best: int                      # argmax Q（搜索找到的最好动作）
    best_q: float
    sigma_base: int
    sigma_best: int
    value: float                   # 先验加权叶值 V
    q_std: float
    tau: float
    pi_top1_mass: float
    elapsed_s: float
    leaf_steps: int
    truncated: int

    def top_pi(self, k: int = 8) -> List[List[float]]:
        p = np.asarray(self.pi, dtype=np.float64)
        nz = np.flatnonzero(p > 0)
        if nz.size == 0:
            return []
        order = nz[np.argsort(-p[nz])][:int(k)]
        return [[int(a), round(float(p[a]), 6)] for a in order]

    def top1(self) -> int:
        p = np.asarray(self.pi, dtype=np.float64)
        return int(np.argmax(p)) if p.size else END_TURN


# ── 候选 / π ────────────────────────────────────────────────────────────────


def root_candidates(mask: np.ndarray, prior: np.ndarray, topk: int,
                    *, skip_move: bool = True) -> np.ndarray:
    """根候选：π_base 概率 top-k 的（非 Move）合法动作，按先验降序。"""
    mask = np.asarray(mask, dtype=bool)
    legal = np.flatnonzero(mask)
    if legal.size == 0:
        return np.zeros(0, dtype=np.int64)
    pool = legal
    if bool(skip_move):
        keep = (pool < MOVE_LO) | (pool >= MOVE_HI)
        if bool(keep.any()):
            pool = pool[keep]
    p = np.asarray(prior, dtype=np.float64)[pool]
    p = np.where(np.isfinite(p) & (p > 0), p, 0.0)
    if float(p.sum()) <= 0.0:
        p = np.ones(pool.size, dtype=np.float64)
    order = np.argsort(-p, kind="stable")
    k = int(topk)
    if k > 0:
        order = order[:k]
    return np.asarray(pool[order], dtype=np.int64)


def pi_from_q(prior: np.ndarray, cands: np.ndarray, q: np.ndarray,
              cfg: RolloutConfig) -> Tuple[np.ndarray, float, float]:
    """候选叶值 Q → π_search（返回 ``(pi, tau, V)``）。"""
    pi = np.zeros(N_ACTIONS, dtype=np.float32)
    n = int(len(cands))
    if n == 0:
        return pi, 0.0, 0.0
    if n == 1:
        pi[int(cands[0])] = 1.0
        return pi, 0.0, float(q[0])
    p = np.asarray(prior, dtype=np.float64)[np.asarray(cands, dtype=np.int64)]
    p = np.where(np.isfinite(p) & (p > 0), p, 0.0)
    if float(p.sum()) <= 0.0:
        p = np.ones(n, dtype=np.float64)
    p = p / float(p.sum())
    qv = np.asarray(q, dtype=np.float64)
    V = float(np.sum(p * qv))
    if str(cfg.pi_mode) == "softmax":
        A = qv - float(qv.max())
    else:
        A = qv - V
    std = float(np.sqrt(max(0.0, np.sum(p * (qv - V) ** 2))))
    tau = float(cfg.q_temp) if float(cfg.q_temp) > 0.0 else max(
        float(cfg.min_temp), float(cfg.q_temp_scale) * std)
    clip = max(0.1, float(getattr(cfg, "adv_clip", 30.0)))
    w = p * np.exp(np.clip(A / max(tau, float(cfg.min_temp)), -clip, clip))
    s = float(w.sum())
    if not np.isfinite(s) or s <= 0.0:
        w = p
        s = float(w.sum())
    pi[np.asarray(cands, dtype=np.int64)] = (w / s).astype(np.float32)
    s2 = float(pi.sum())
    if s2 > 0:
        pi /= s2
    return pi, float(tau), V


# ── rollout 搜索 ───────────────────────────────────────────────────────────


@dataclass
class _Rollout:
    """一条候选的 rollout 状态。"""

    game: int
    action: int
    env: EconomySandbox
    obs: Optional[SandboxObs]
    target_turn: int
    rng: Any = None
    steps: int = 0
    done: bool = False
    truncated: bool = False
    sigma: int = 0
    tier: int = 0
    carriers: int = 0


class RolloutSearcher:
    """跨局 / 跨候选 lockstep 的 rollout 叶评估搜索。

    ``envs`` 必须是**当前决策点**的沙盒（不会被修改：每条 rollout 用 ``clone()``）。
    """

    def __init__(self, model: Any = None, device: str = "cuda",
                 cfg: Optional[RolloutConfig] = None, *, dtype: str = "fp32",
                 chunk: int = 256, policy_fn: Any = None) -> None:
        self.cfg = cfg or RolloutConfig()
        self.cfg.validate()
        self.model = model
        self.device = str(device)
        self.dtype = str(dtype)
        if policy_fn is not None:
            # 测试 / 诊断用：外部策略 ``(feats, cards, masks) -> (prior, value)``
            self._runner = None
            self._eval = policy_fn
        else:
            if model is None:
                raise ValueError("RolloutSearcher 需要 model 或 policy_fn")
            # 只为拿到「策略先验」（π_base）与 value；sims 不影响 evaluate
            self._runner = SearchRunner(
                model, device=device,
                cfg=SearchConfig(sims=1, topk=max(1, int(self.cfg.topk)),
                                 skip_move=bool(self.cfg.skip_move)),
                dtype=dtype, chunk=chunk)
            self._eval = self._runner.evaluate
        self._carriers = set(carrier_ids())
        tab = card_tables()
        self._cid2id: Dict[int, str] = tab["cid2id"]
        self._id2kind: Dict[str, str] = tab["id2kind"]
        self._when = self.cfg.search_when_tags

    # ── 观测解码 ────────────────────────────────────────────────────────
    def tags(self, feats: np.ndarray, cards: np.ndarray) -> DecisionTags:
        f = np.asarray(feats, dtype=np.float32)
        c = np.asarray(cards, dtype=np.int64)

        def _carrier(ids: np.ndarray) -> int:
            n = 0
            for cid in ids:
                if int(cid) <= 0:
                    continue
                if self._cid2id.get(int(cid)) in self._carriers:
                    n += 1
            return n

        def _spell(ids: np.ndarray) -> int:
            n = 0
            for cid in ids:
                if int(cid) <= 0:
                    continue
                if self._id2kind.get(self._cid2id.get(int(cid), "")) in SPELL_KINDS:
                    n += 1
            return n

        hand = c[CARD_HAND]
        return DecisionTags(
            sigma=int(sigmas_from_features(f[None, :])[0]),
            tier=max(0, int(round(float(f[FEAT_TIER]) * FEAT_TIER_SCALE))),
            carriers_board=_carrier(c[CARD_BOARD]),
            carrier_in_shop=_carrier(c[CARD_SHOP]),
            carrier_in_hand=_carrier(hand),
            spell_in_hand=_spell(hand),
            shop_n=int((c[CARD_SHOP] > 0).sum()),
            hand_n=int((hand > 0).sum()))

    def should_search(self, tags: DecisionTags, *, searched_this_turn: int) -> bool:
        if int(self.cfg.max_searches_per_turn) > 0 \
                and int(searched_this_turn) >= int(self.cfg.max_searches_per_turn):
            return False
        if not tag_matches(tags, self._when):
            return False
        return True

    # ── 网络 ────────────────────────────────────────────────────────────
    def policy(self, feats: np.ndarray, cards: np.ndarray,
               masks: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """批量策略/价值：``(prior[n,245] 已 mask 归一, value[n])``。"""
        return self._eval(feats, cards, masks)

    # ── 搜索 ────────────────────────────────────────────────────────────
    def search(self, envs: Sequence[EconomySandbox], feats: np.ndarray,
               cards: np.ndarray, masks: np.ndarray,
               priors: np.ndarray) -> List[RolloutResult]:
        """对一批决策各跑一次 rollout 搜索（跨决策 lockstep 批量前向）。"""
        t0 = time.time()
        n = int(len(envs))
        feats = np.asarray(feats, dtype=np.float32)
        cards = np.asarray(cards, dtype=np.int64)
        masks = np.asarray(masks, dtype=bool)
        cand_list: List[np.ndarray] = []
        rollouts: List[_Rollout] = []
        #: ``cand_rollouts[i][j]`` = 第 i 个决策第 j 个候选的 K 条 rollout
        cand_rollouts: List[List[List[_Rollout]]] = []
        samples = max(1, int(self.cfg.rollout_samples))
        for i in range(n):
            env = envs[i]
            cands = root_candidates(masks[i], priors[i], int(self.cfg.topk),
                                    skip_move=bool(self.cfg.skip_move))
            cand_list.append(cands)
            root_turn = int(env.obs().turn) if env.g is not None else 0
            target = root_turn + max(0, int(self.cfg.turns) - 1)
            per_cand: List[List[_Rollout]] = []
            for a in cands.tolist():
                group: List[_Rollout] = []
                for s in range(samples):
                    # **公共随机数（CRN）**：同一决策的所有候选共用一条采样流，
                    # 候选间的差异尽量只来自动作本身（``rollout_mode=sample``）。
                    r = _Rollout(game=i, action=int(a), env=env.clone(), obs=None,
                                 target_turn=int(target),
                                 rng=(np.random.default_rng(
                                     int(self.cfg.seed) * 1000003 + i * 104729
                                     + s * 7919)
                                     if str(self.cfg.rollout_mode) == "sample" else None))
                    # 候选动作本身可能直接结束本回合（EndTurn）/ 结束整局；EndTurn
                    # 不改棋盘，所以此时「本回合末状态」= 根状态。
                    try:
                        advanced = bool(r.env.search_step(int(a)))
                    except RuntimeError:
                        advanced = False
                        over = True
                    else:
                        over = bool(r.env.g.is_over()) or bool(r.env.done)
                    if over or (advanced and int(target) <= int(root_turn)):
                        _finish(r, self.tags(feats[i], cards[i]))
                    else:
                        r.obs = r.env.obs()
                    rollouts.append(r)
                    group.append(r)
                per_cand.append(group)
            cand_rollouts.append(per_cand)
        # lockstep rollout（跨决策 / 跨候选一次批量前向）
        active = [r for r in rollouts if not r.done]
        for _it in range(int(self.cfg.max_steps)):
            if not active:
                break
            f = np.stack([r.obs.features for r in active])        # type: ignore[union-attr]
            c = np.stack([r.obs.cards for r in active])           # type: ignore[union-attr]
            m = np.stack([r.obs.mask for r in active])            # type: ignore[union-attr]
            p, _v = self.policy(f, c, m)
            nxt: List[_Rollout] = []
            for k, r in enumerate(active):
                obs = r.obs
                if str(self.cfg.rollout_mode) == "greedy":
                    a = int(np.argmax(p[k]))
                else:
                    pk = np.asarray(p[k], dtype=np.float64)
                    pk = np.where(np.isfinite(pk) & (pk > 0), pk, 0.0)
                    s = float(pk.sum())
                    a = int(r.rng.choice(N_ACTIONS, p=pk / s)) if s > 0 else END_TURN
                pre_turn = int(obs.turn)
                r.steps += 1
                try:
                    advanced = bool(r.env.search_step(int(a)))
                except RuntimeError:
                    r.truncated = True
                    _finish(r, self.tags(obs.features, obs.cards))
                    continue
                over = bool(r.env.g.is_over()) or bool(r.env.done)
                if over or (advanced and pre_turn >= int(r.target_turn)):
                    _finish(r, self.tags(obs.features, obs.cards))
                    continue
                r.obs = r.env.obs()
                if int(r.steps) >= int(self.cfg.max_steps):
                    r.truncated = True
                    _finish(r, self.tags(r.obs.features, r.obs.cards))
                    continue
                nxt.append(r)
            active = [r for r in nxt if not r.done]
        for r in active:   # 步数上限截断
            r.truncated = True
            if r.obs is not None:
                _finish(r, self.tags(r.obs.features, r.obs.cards))
            else:   # pragma: no cover - 只有 turns>1 且步数上限极小的极端配置
                _finish(r, self.tags(feats[r.game], cards[r.game]))
        elapsed = time.time() - t0
        per = elapsed / max(1, n)
        out: List[RolloutResult] = []
        for i in range(n):
            cands = cand_list[i]
            groups = cand_rollouts[i]
            q = np.asarray([float(np.mean([self._score(r) for r in g])) if g else 0.0
                            for g in groups], dtype=np.float64)
            sig = np.asarray([int(round(float(np.mean([r.sigma for r in g])))) if g else 0
                              for g in groups], dtype=np.int64)
            tier = np.asarray([int(round(float(np.mean([r.tier for r in g])))) if g else 0
                               for g in groups], dtype=np.int64)
            car = np.asarray([int(round(float(np.mean([r.carriers for r in g])))) if g else 0
                              for g in groups], dtype=np.int64)
            n_steps = int(sum(r.steps for g in groups for r in g))
            n_trunc = int(sum(1 for g in groups for r in g if r.truncated))
            pi, tau, V = pi_from_q(priors[i], cands, q, self.cfg)
            order = np.argsort(-np.asarray(priors[i], dtype=np.float64)[cands],
                               kind="stable")
            base = int(cands[int(order[0])]) if cands.size else END_TURN
            base_idx = int(order[0]) if cands.size else 0
            best_idx = int(np.argmax(q)) if q.size else 0
            top1 = int(np.argmax(pi)) if pi.size else END_TURN
            out.append(RolloutResult(
                pi=pi, cands=np.asarray(cands, dtype=np.int64), q=q,
                sigma_end=sig, tier_end=tier, carriers_end=car,
                base=base, base_q=float(q[base_idx]) if q.size else 0.0,
                best=int(cands[best_idx]) if cands.size else END_TURN,
                best_q=float(q[best_idx]) if q.size else 0.0,
                sigma_base=int(sig[base_idx]) if q.size else 0,
                sigma_best=int(sig[best_idx]) if q.size else 0,
                value=float(V), q_std=float(np.std(q)) if q.size else 0.0,
                tau=float(tau),
                pi_top1_mass=float(pi[top1]) if pi.size else 0.0,
                elapsed_s=float(per), leaf_steps=int(n_steps),
                truncated=int(n_trunc)))
        return out

    def _score(self, r: _Rollout) -> float:
        s = _L(float(r.sigma))
        cfg = self.cfg
        if float(cfg.tier_bonus) != 0.0:
            s += float(cfg.tier_bonus) * (float(r.tier) / 6.0)
        if float(cfg.carrier_bonus) != 0.0:
            s += float(cfg.carrier_bonus) * (float(r.carriers) / 7.0)
        return float(s)


def _finish(r: _Rollout, tags: DecisionTags) -> None:
    r.done = True
    r.sigma = int(tags.sigma)
    r.tier = int(tags.tier)
    r.carriers = int(tags.carriers_board)


# ── 摘要（标签 summary / 报告用）────────────────────────────────────────────


def result_summary(res: RolloutResult, k: int = 8) -> Dict[str, Any]:
    """把一条搜索结果压成可写 JSON 的结构。"""
    return {"pi_topk": res.top_pi(k), "top1": res.top1(),
            "cands": [int(a) for a in res.cands],
            "q": [round(float(v), 6) for v in res.q],
            "sigma_end": [int(v) for v in res.sigma_end],
            "tier_end": [int(v) for v in res.tier_end],
            "carriers_end": [int(v) for v in res.carriers_end],
            "base": int(res.base), "base_q": round(float(res.base_q), 6),
            "best": int(res.best), "best_q": round(float(res.best_q), 6),
            "sigma_base": int(res.sigma_base), "sigma_best": int(res.sigma_best),
            "value": round(float(res.value), 6),
            "q_std": round(float(res.q_std), 6), "tau": round(float(res.tau), 6),
            "pi_top1_mass": round(float(res.pi_top1_mass), 4),
            "elapsed_s": round(float(res.elapsed_s), 5),
            "leaf_steps": int(res.leaf_steps), "truncated": int(res.truncated)}
