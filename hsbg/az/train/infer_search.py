"""推理期搜索：**完整游戏**上的 rollout 叶值 + π_search（评测/面板包装层）。

依据 ``runs/search_labels_v2/REPORT.md``（沙盒实测）：

- 关键决策按 π_search 采样，比 π_base **+10.3% t12 / +12.3% t15**；
- **3 回合叶值**把 t15 拉 **+27%**（t12 不变）⇒ 深度买的是后期复利；
- 单次搜索 p50 **30 ms**（1 回合）/ 167 ms（3 回合），每局约 30 次 ⇒ 1–5 s/局。

本模块把**同一套搜索**（候选动作 → π_base greedy rollout → 叶值
``log1p(回合末 Σ)/log1p(30000)``；π ∝ p̃·exp(clip(A/τ))）搬到**完整游戏**
（Rust ``hsbg_engine``）状态上，只作为评测/面板策略的**外包一层**：

- **不改训练**：不碰 ``ppo.py`` 的采集路径、不产生训练标签、不写 checkpoint；
- rollout 驱动：候选动作在 ``game.copy()``（引擎深拷贝，实测 ≈0.011 ms）上执行，
  **learner 座位用 π_base argmax 继续走到本回合（或第 ``turns`` 个回合）末**，
  其它座位用引擎 ``bot_play`` 推进（只有 ``turns>1`` 才需要，1 回合时 learner
  一结束回合就收叶子，省掉全部 bot 动作）；
- 叶值 Σ 走与 ``quality_monitor`` 同一口径（``atk+hp`` 求和）；实现上从 learner
  观测解码（``sigmas_from_features``，×10 标定），12 局 157 个决策上与
  ``player_json`` 逐一相等（见 tests）；
- 动作规则可选（``InferSearchConfig.action``）：

  - ``pi_argmax``（默认）：取 π_search 的 argmax —— 与「按 π_search 采样」同分布族，
    但**确定性**，评测面板可复现；
  - ``argmax_q``：取搜索叶值最高的候选（= 沙盒报告里的 ``best``，ΔΣ 均值 +28.8）；
  - ``sample``：按 π_search 采样（沙盒 §3 在线口径），RNG 由
    ``(seed, seat, turn, 本局第几次决策)`` 派生 ⇒ 可复现。

与训练/评测的边界
-----------------
``InferSearchPolicy`` **只**包一层 ``decide``：先调 ``base.decide`` 拿到基线动作与
先验，再决定是否覆盖动作。``enabled=0`` 时是纯 pass-through（逐位等于裸 base 策略，
见 tests）。所有统计（``search_calls`` / ``search_ms_total`` / ``mean_ms_per_call`` /
``sigma_by_turn``）都能从 :meth:`InferSearchPolicy.stats` /
:meth:`InferSearchPolicy.game_rows` 取到。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .common import N_ACTIONS, mask_from_bytes, obs_arrays
from .policies import Decision, Policy
from .sandbox_rollout import (CARD_BOARD, CARD_HAND, CARD_SHOP, STRENGTH_REF,
                              DecisionTags, FEAT_TIER, FEAT_TIER_SCALE,
                              RolloutConfig, card_tables, pi_from_q,
                              root_candidates, sigmas_from_features,
                              search_when_names, tag_matches)

#: 载体卡 id 集合（``hsbg.az.train.sandbox_rollout.carrier_ids`` 同一来源）
def _carrier_ids() -> set:
    from .economy_sandbox import carrier_ids
    return set(carrier_ids())


#: 观测解码里 Σ 的标定（features 存的是 atk/hp 的 1/10；实测与 player_json 逐一相等）
SIGMA_SCALE = 10.0

#: ``--infer-search-action`` 支持的动作规则
ACTION_MODES = ("pi_argmax", "argmax_q", "sample")

#: 叶值曲线（与沙盒 ``_L`` 同一公式；这里显式写出来避免依赖私有名）
_LOG_REF = math.log1p(STRENGTH_REF)

#: 血量项归一化参考（英雄满血 30；``health_bonus`` 的权重是对「满血」而言）
HEALTH_REF = 30.0


def leaf_value(sigma: float) -> float:
    """``L(Σ) = log1p(Σ)/log1p(30000)``（与沙盒叶值同一曲线）。"""
    return math.log1p(max(0.0, float(sigma))) / _LOG_REF


def leaf_score(sigma: float, *, tier: int = 0, health: Optional[int] = None,
               tier_bonus: float = 0.0, health_bonus: float = 0.0,
               health_ref: float = HEALTH_REF) -> float:
    """叶值 = ``L(Σ) + w_t·(tier/6) + w_h·(health/30)``。

    - ``tier_bonus`` / ``health_bonus`` 默认 0 ⇒ 逐位等于 :func:`leaf_value`（旧口径）；
    - tier 项与沙盒 ``RolloutConfig.tier_bonus`` 同一归一（``tier/6``）；
    - health 项用**决策时刻的血量**（不是战团血量），归一 ``health/30``：
      惩罚「高身材但快死」的选择，权重必须远小于 ``L`` 的候选间差（≈0.01–0.05）。
    """
    s = leaf_value(sigma)
    if float(tier_bonus) != 0.0:
        s += float(tier_bonus) * (max(0, int(tier)) / 6.0)
    if float(health_bonus) != 0.0 and health is not None:
        s += float(health_bonus) * (max(0, int(health)) / max(1e-9, float(health_ref)))
    return float(s)


# ══════════════════════════════════════════════════════════════════════════
# 1. 配置
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class InferSearchConfig:
    """推理期搜索的预算/口径（评测侧，默认全部关闭）。"""

    #: 0 = 不搜索（pass-through，逐位等于裸 base 策略）；1 = 关键决策开搜索
    enabled: int = 0
    #: 叶值 horizon：1 = 到本回合末；3 = 到第 3 个回合末（后期复利）
    turns: int = 1
    #: 每回合最多搜索几次（沙盒证据里是 3）
    max_searches_per_turn: int = 3
    #: 根候选数 = π_base top-k（非 Move 合法动作）
    topk: int = 8
    #: 关键决策口径（``sandbox_rollout.SEARCH_WHEN_NAMES``；逗号分隔可组合）
    search_when: str = "carrier_or_spell"
    #: 覆盖动作的规则（见 ACTION_MODES）
    action: str = "pi_argmax"
    #: rollout 行为：auto（K=1 时 greedy，K>1 时 sample）/ greedy / sample。
    #: **auto 是新增默认值**：K=1 逐位等于旧路径（greedy），K>1 才切到采样型搜索。
    rollout_mode: str = "auto"
    #: 同一动作的独立 rollout 数 K（随机性感知搜索：对 RNG/隐藏信息做蒙特卡洛）。
    #: K=1 时逐位等于旧路径；K>1 时叶值 = K 次叶分的均值，并给出标准误。
    rollouts: int = 1
    #: ``auto``/``sample`` 的基准 RNG 种子（同一 searcher 内按「第几次搜索 × 候选 ×
    #: 副本」派生；同 seed 可复现，换 seed 得到不同样本）。
    rollout_seed: int = 0
    #: π 构造（与沙盒同一套，透传给 ``sandbox_rollout.pi_from_q``）
    pi_mode: str = "advantage"
    q_temp: float = 0.0
    q_temp_scale: float = 1.0
    adv_clip: float = 30.0
    #: 叶值附加项（默认 0 = 纯 log1p(Σ)）：``tier_bonus`` / ``health_bonus`` 已接线
    #: （见 :func:`leaf_score`）；``carrier_bonus`` 只为沙盒口径保留，推理期**未接线**
    tier_bonus: float = 0.0
    carrier_bonus: float = 0.0
    #: 叶值血量项：``+ health_bonus·(health/health_ref)``（抑制「高身材但快死」）
    health_bonus: float = 0.0
    health_ref: float = HEALTH_REF
    #: 候选剔除 Move 段（换位不改变盘面 Σ）
    skip_move: bool = True
    #: rollout 内 learner 每回合动作上限（与评测 ``max_actions_per_turn`` 同口径；
    #: 超限强制 EndTurn，防止 greedy rollout 陷入 Play/Cancel 死循环）
    rollout_max_actions_per_turn: int = 40
    #: rollout 硬步数上限（0 = 自动 ``64*turns + 64``）
    max_rollout_steps: int = 0
    #: 单次搜索墙钟上限（ms；0 = 不限）。超时立即放弃搜索、退回 π_base 动作 ——
    #: 部署（竞技场/评测）用这个兜住「长回合 + 3 回合叶值」的尾延迟。
    max_ms_per_search: float = 0.0
    #: ``action=sample`` 的 RNG 基准种子（面板脚本写 seed_base）
    seed: int = 0
    #: 是否复用 ``base.decide`` 返回的 ``pi`` 当根先验（PPOGreedyPolicy 的 pi 就是
    #: π_base masked 归一；PPOSelfPlayPolicy 的 pi 可能是均匀/one-hot ⇒ 传 0）
    use_base_prior: int = 1
    #: 是否记录 Σ(turn) 轨迹（t12/t15 强度比用；enabled=0 时也可开）
    trace: int = 1

    def validate(self) -> "InferSearchConfig":
        if int(self.enabled) not in (0, 1):
            raise ValueError("enabled 只能是 0/1")
        if int(self.turns) < 1:
            raise ValueError("turns 必须 >= 1")
        if int(self.max_searches_per_turn) < 0:
            raise ValueError("max_searches_per_turn 必须 >= 0（0 = 不限）")
        if float(self.max_ms_per_search) < 0.0:
            raise ValueError("max_ms_per_search 必须 >= 0（0 = 不限）")
        if str(self.action) not in ACTION_MODES:
            raise ValueError(f"action 只能是 {ACTION_MODES}")
        if str(self.rollout_mode) not in ("auto", "greedy", "sample"):
            raise ValueError("rollout_mode 只能是 auto|greedy|sample")
        if not (1 <= int(self.rollouts) <= 64):
            raise ValueError("rollouts 必须在 1..64")
        if int(self.rollouts) > 1 and str(self.rollout_mode) == "greedy":
            # greedy + K>1 的所有副本会逐位相同（引擎无 RNG 重播种 API），K 是白花的；
            # 明确拒绝而不是静默浪费算力。
            raise ValueError("rollouts>1 需要 rollout_mode=auto|sample"
                             "（greedy 的 K 个副本必然相同）")
        for name in ("tier_bonus", "carrier_bonus", "health_bonus", "health_ref"):
            v = float(getattr(self, name))
            if not math.isfinite(v):
                raise ValueError(f"{name} 必须是有限数")
        if float(self.health_ref) <= 0.0:
            raise ValueError("health_ref 必须 > 0")
        search_when_names(str(self.search_when))    # 触发校验
        return self

    def effective_rollout_mode(self) -> str:
        """``auto`` → K=1 用 greedy（旧路径逐位一致）/ K>1 用 sample（蒙特卡洛）。"""
        mode = str(self.rollout_mode)
        if mode == "auto":
            return "greedy" if int(self.rollouts) <= 1 else "sample"
        return mode

    def rollout_config(self) -> RolloutConfig:
        """映射成沙盒的 ``RolloutConfig``（π 构造唯一真源）。"""
        rc = RolloutConfig(
            topk=int(self.topk), turns=int(self.turns),
            rollout_mode=self.effective_rollout_mode(), pi_mode=str(self.pi_mode),
            q_temp=float(self.q_temp), q_temp_scale=float(self.q_temp_scale),
            adv_clip=float(self.adv_clip), tier_bonus=float(self.tier_bonus),
            carrier_bonus=float(self.carrier_bonus),
            skip_move=bool(self.skip_move),
            search_when=str(self.search_when),
            max_searches_per_turn=int(self.max_searches_per_turn),
            seed=int(self.seed))
        rc.validate()
        return rc


# ══════════════════════════════════════════════════════════════════════════
# 2. 搜索结果
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class SearchOutcome:
    """一次推理期搜索的结果（候选叶值真值 + π_search）。"""

    pi: np.ndarray              # f32[245]，支撑 = cands
    cands: np.ndarray           # i64[n]，π_base 先验降序
    q: np.ndarray               # f64[n]，叶分 = mean_k L(Σ_end,k) [+ w·tier + w·health]
    sigma_end: np.ndarray       # i64[n]，回合末战团 Σ（K 次的均值，四舍五入）
    tier_end: np.ndarray        # i64[n]，叶位置酒馆等级（0..6；K 次均值）
    health_end: np.ndarray      # i64[n]，叶位置英雄血量（-1 = 引擎不可用；K 次均值）
    base: int                   # π_base top-1
    best: int                   # argmax Q
    best_q: float
    sigma_root: int
    sigma_base: int
    sigma_best: int
    value: float
    q_std: float
    tau: float
    action: int
    switch: bool                # 覆盖了 base 动作
    elapsed_ms: float
    leaf_steps: int
    truncated: int
    #: 随机性感知搜索的诊断量（K=1 时为 0/None，逐位不影响旧口径）
    q_se: np.ndarray = None          # f64[n]，mean 的标准误（K>1）
    sigma_se: np.ndarray = None      # f64[n]，Σ 的标准误（K>1）
    q_samples: np.ndarray = None     # f64[n,K]，每条候选的 K 次叶分（诊断/单测）
    rollouts: int = 1

    def as_dict(self, k: int = 8) -> Dict[str, Any]:
        p = np.asarray(self.pi, dtype=np.float64)
        nz = np.flatnonzero(p > 0)
        order = nz[np.argsort(-p[nz])][:int(k)] if nz.size else []
        return {"pi_topk": [[int(a), round(float(p[a]), 6)] for a in order],
                "top1": int(self.action), "cands": [int(a) for a in self.cands],
                "q": [round(float(v), 6) for v in self.q],
                "sigma_end": [int(v) for v in self.sigma_end],
                "tier_end": [int(v) for v in self.tier_end],
                "health_end": [int(v) for v in self.health_end],
                "base": int(self.base), "best": int(self.best),
                "best_q": round(float(self.best_q), 6),
                "sigma_root": int(self.sigma_root),
                "sigma_base": int(self.sigma_base),
                "sigma_best": int(self.sigma_best),
                "value": round(float(self.value), 6),
                "q_std": round(float(self.q_std), 6),
                "q_se": ([round(float(v), 6) for v in self.q_se]
                         if self.q_se is not None else None),
                "rollouts": int(self.rollouts),
                "tau": round(float(self.tau), 6),
                "switch": bool(self.switch),
                "elapsed_ms": round(float(self.elapsed_ms), 3),
                "leaf_steps": int(self.leaf_steps),
                "truncated": int(self.truncated)}


# ══════════════════════════════════════════════════════════════════════════
# 3. rollout 驱动（完整游戏状态）
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class _Roll:
    """一条候选的 rollout 状态（game 是 ``copy()`` 出来的独立局面）。"""

    cand: int
    game: Any
    root_turn: int
    target_turn: int
    sigma: int = 0
    #: 叶位置的酒馆等级 / 英雄血量（叶值附加项用；health = -1 表示引擎不可用）
    tier: int = 0
    health: int = -1
    turn_actions: int = 0
    steps: int = 0
    done: bool = False
    truncated: bool = False
    #: 该副本的 RNG（K>1 时逐副本独立；K=1 greedy 不读）
    rng: Any = None
    replica: int = 0


def _masked_softmax_rows(logits: Any, mask: Any) -> np.ndarray:
    """按行 masked softmax（非法位严格 0；空行返回全 0）。"""
    lg = np.asarray(logits, dtype=np.float64)
    m = np.asarray(mask, dtype=bool)
    lg = np.where(m, lg, -np.inf)
    mx = np.max(lg, axis=1, keepdims=True)
    e = np.exp(lg - mx)
    e = np.where(np.isfinite(e), e, 0.0)
    s = e.sum(axis=1, keepdims=True)
    out = np.where(s > 0.0, e / np.maximum(s, 1e-12), 0.0)
    return out.astype(np.float32)


class InferSearcher:
    """完整游戏上的 rollout 叶评估搜索（单决策、候选 lockstep 批量前向）。"""

    def __init__(self, evaluator: Any, cfg: Optional[InferSearchConfig] = None,
                 *, n_players: int = 8) -> None:
        self.evaluator = evaluator
        self.cfg = (cfg or InferSearchConfig()).validate()
        self._rc = self.cfg.rollout_config()
        self._when = search_when_names(str(self.cfg.search_when))
        self.n_players = int(n_players)
        self._carriers = _carrier_ids()
        tab = card_tables()
        self._cid2id: Dict[int, str] = tab["cid2id"]
        self._id2kind: Dict[str, str] = tab["id2kind"]
        # 累计统计（跨局；面板脚本按快照取增量）
        self.calls = 0
        self.ms_total = 0.0
        self.errors = 0
        self.timeouts = 0
        self.switched = 0
        self.leaf_steps = 0
        self.truncated = 0
        #: 搜索序号（派生逐副本 RNG；同 seed 同调用序 ⇒ 逐位可复现）
        self._search_seq = 0

    # ── 观测解码 ────────────────────────────────────────────────────────
    def tags(self, feats: np.ndarray, cards: np.ndarray) -> DecisionTags:
        """从观测直接解码关键决策事实（与沙盒 ``RolloutSearcher.tags`` 同口径）。"""
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
                if self._id2kind.get(self._cid2id.get(int(cid), "")) in \
                        ("tavern_spell", "spell"):
                    n += 1
            return n

        hand = c[CARD_HAND]
        return DecisionTags(
            sigma=int(round(sigmas_from_features(f[None, :])[0])),
            tier=max(0, int(round(float(f[FEAT_TIER]) * FEAT_TIER_SCALE))),
            carriers_board=_carrier(c[CARD_BOARD]),
            carrier_in_shop=_carrier(c[CARD_SHOP]),
            carrier_in_hand=_carrier(hand),
            spell_in_hand=_spell(hand),
            shop_n=int((c[CARD_SHOP] > 0).sum()),
            hand_n=int((hand > 0).sum()))

    def should_search(self, tags: DecisionTags, *,
                      searched_this_turn: int) -> bool:
        cap = int(self.cfg.max_searches_per_turn)
        if cap > 0 and int(searched_this_turn) >= cap:
            return False
        return bool(tag_matches(tags, self._when))

    def sigma(self, feats: np.ndarray) -> int:
        """观测特征 → 战团 Σ（``atk+hp`` 求和，×10 标定）。"""
        return int(round(float(sigmas_from_features(
            np.asarray(feats, dtype=np.float32)[None, :])[0])))

    def health(self, game: Any, seat: int) -> int:
        """英雄血量（引擎不可用/旧构建返回 -1 ⇒ 叶值不加血量项）。"""
        try:
            return int(game.health()[int(seat)])
        except Exception:      # noqa: BLE001 - 无 health() 时退化为「无血量项」
            return -1

    def leaf_q(self, r: "_Roll") -> float:
        """叶分：``L(Σ) [+ w_t·tier/6] [+ w_h·health/30]``（权重 0 ⇒ 旧口径）。"""
        return leaf_score(
            r.sigma, tier=int(r.tier),
            health=(int(r.health) if int(r.health) >= 0 else None),
            tier_bonus=float(self.cfg.tier_bonus),
            health_bonus=float(self.cfg.health_bonus),
            health_ref=float(self.cfg.health_ref))

    # ── 网络 ────────────────────────────────────────────────────────────
    def prior_batch(self, feats: np.ndarray, cards: np.ndarray,
                    masks: np.ndarray) -> np.ndarray:
        """批量 π_base：``(prior[n,245] masked 归一, value[n])`` 里的 prior。"""
        f = np.atleast_2d(np.asarray(feats, dtype=np.float32))
        c = np.atleast_2d(np.asarray(cards, dtype=np.int64))
        m = np.atleast_2d(np.asarray(masks, dtype=bool))
        logits = getattr(self.evaluator, "logits", None)
        if logits is not None:
            plog, _ = logits(f, c, m)
            return _masked_softmax_rows(plog, m)
        # 回退：逐行 ``__call__``（旧 evaluator 接口）
        out = np.zeros((f.shape[0], N_ACTIONS), dtype=np.float32)
        for i in range(f.shape[0]):
            p, _v = self.evaluator(f[i], c[i], m[i], 0)
            p = np.asarray(p, dtype=np.float32)
            p[~m[i]] = 0.0
            s = float(p.sum())
            out[i] = p / s if s > 0 else m[i].astype(np.float32) / max(
                1.0, float(m[i].sum()))
        return out

    # ── 搜索 ────────────────────────────────────────────────────────────
    def search(self, game: Any, seat: int, *, prior: Any = None,
               mask: Any = None, rng: Any = None) -> Optional[SearchOutcome]:
        """对 ``(game, seat)`` 当前决策点跑一次推理期搜索。

        返回 ``None`` 表示「不搜/搜不了」（候选 < 2、无合法动作等）；
        ``game`` 本身**不会被修改**（每条 rollout 都在 ``game.copy()`` 上做）。
        """
        t0 = time.perf_counter()
        seat = int(seat)
        try:
            f, c = obs_arrays(game.observe(seat))
            mask = (np.asarray(mask, dtype=bool).reshape(-1) if mask is not None
                    else mask_from_bytes(game.legal_mask(seat)))
            p = None
            if int(self.cfg.use_base_prior) and prior is not None:
                pa = np.asarray(prior, dtype=np.float32)
                if pa.size == N_ACTIONS and np.all(np.isfinite(pa)) and \
                        float(pa[~mask].sum()) <= 1e-6 and float(pa.sum()) > 0.0:
                    p = pa
            if p is None:
                p = self.prior_batch(f[None, :], c[None, :], mask[None, :])[0]
            cands = root_candidates(mask, p, int(self.cfg.topk),
                                    skip_move=bool(self.cfg.skip_move))
            if cands.size < 2:
                return None
            sigma_root = self.sigma(f)
            root_tier = max(0, int(round(float(f[FEAT_TIER]) * FEAT_TIER_SCALE)))
            root_health = self.health(game, seat)
            root_turn = int(getattr(game, "turn", 0))
            target = root_turn + max(0, int(self.cfg.turns) - 1)
            # ── 随机性感知：每个候选跑 K 个独立副本 ─────────────────────────
            # 引擎没有 RNG 重播种 API（``Game.copy()`` 会连同 RNG 状态一起复制），
            # 所以独立性来自「逐副本不同的动作采样流」：副本各自从 π_base 采样后续
            # 动作，动作序列不同 ⇒ 后续商店刷新/战斗的引擎 RNG 消耗不同 ⇒ 隐藏信息
            # 沿不同分支展开。K=1 且 greedy 时与旧路径逐位一致。
            K = int(self.cfg.rollouts)
            eff_mode = self.cfg.effective_rollout_mode()
            base_seed = (int(self.cfg.rollout_seed) if int(self.cfg.rollout_seed) > 0
                         else int(self.cfg.seed))
            seq = int(self._search_seq)
            self._search_seq += 1
            rolls: List[_Roll] = []
            for ci, a in enumerate(cands.tolist()):
                for k in range(K):
                    g = game.copy()
                    r = _Roll(cand=int(a), game=g, root_turn=root_turn,
                              target_turn=int(target), sigma=int(sigma_root),
                              tier=int(root_tier), health=int(root_health),
                              replica=int(k))
                    if eff_mode == "sample":
                        r.rng = np.random.default_rng(
                            [base_seed, seq, int(ci), int(k)])
                    r.turn_actions = 1
                    try:
                        g.step(seat, int(a))
                    except (RuntimeError, ValueError):
                        r.truncated = True
                        r.done = True
                    if not r.done and bool(g.is_over()):
                        r.done = True
                    rolls.append(r)
            max_steps = int(self.cfg.max_rollout_steps) or (64 * int(self.cfg.turns) + 64)
            steps_total = 0
            it = 0
            budget_ms = float(self.cfg.max_ms_per_search)
            while it < max_steps:
                it += 1
                if budget_ms > 0.0 and (time.perf_counter() - t0) * 1000.0 > budget_ms:
                    # 超时兜底：放弃本次搜索，调用方退回 π_base 动作（不影响评测）
                    self.timeouts += 1
                    return None
                todo = [r for r in rolls if not r.done]
                if not todo:
                    break
                batch: List[Tuple[_Roll, np.ndarray, np.ndarray, np.ndarray]] = []
                for r in todo:
                    g = r.game
                    if bool(g.is_over()):
                        r.done = True
                        continue
                    if int(g.turn) > int(r.target_turn):     # 目标回合已过
                        r.done = True
                        continue
                    if bool(g.needs_action(seat)):
                        gf, gc = obs_arrays(g.observe(seat))
                        gm = mask_from_bytes(g.legal_mask(seat))
                        batch.append((r, gf, gc, gm))
                        continue
                    # learner 本回合已结束
                    if int(self.cfg.turns) <= 1:
                        r.done = True
                        continue
                    if not self._alive(g, seat):
                        r.done = True
                        continue
                    if not self._advance_others(g, seat):
                        r.truncated = True
                        r.done = True
                        continue
                    if bool(g.is_over()) or int(g.turn) > int(r.target_turn):
                        r.done = True
                if not batch:
                    continue
                fmat = np.stack([b[1] for b in batch])
                cmat = np.stack([b[2] for b in batch])
                mmat = np.stack([b[3] for b in batch])
                pri = self.prior_batch(fmat, cmat, mmat)
                sig = sigmas_from_features(fmat)
                tiers = np.rint(np.asarray(fmat, dtype=np.float64)[:, FEAT_TIER]
                                * FEAT_TIER_SCALE).astype(np.int64)
                for k, (r, _gf, _gc, gm) in enumerate(batch):
                    r.sigma = int(round(float(sig[k])))
                    r.tier = max(0, int(tiers[k]))
                    r.health = self.health(r.game, seat)
                    r.steps += 1
                    steps_total += 1
                    if eff_mode == "sample" and r.rng is not None:
                        pk = np.asarray(pri[k], dtype=np.float64)
                        s = float(pk.sum())
                        if s > 0.0 and np.all(np.isfinite(pk)):
                            a = int(r.rng.choice(N_ACTIONS, p=pk / s))
                        else:
                            a = int(np.argmax(pri[k]))
                    else:
                        a = int(np.argmax(pri[k]))
                    r.turn_actions += 1
                    if int(self.cfg.rollout_max_actions_per_turn) > 0 \
                            and r.turn_actions > int(self.cfg.rollout_max_actions_per_turn) \
                            and bool(gm[0]):
                        a = 0           # 与评测同口径的回合守卫
                    if not bool(gm[int(a)]):     # 采样退化时兜底到先验 argmax
                        a = int(np.argmax(pri[k]))
                    try:
                        r.game.step(seat, int(a))
                    except (RuntimeError, ValueError):
                        r.truncated = True
                        r.done = True
                        continue
                    if bool(r.game.is_over()):
                        r.done = True
            for r in rolls:
                if not r.done:
                    r.truncated = True
                    r.done = True
            # ── 聚合：K 次的均值 + 标准误（K=1 时与旧路径逐位一致）──────────
            n_c = int(cands.size)
            q_samples = np.asarray([self.leaf_q(r) for r in rolls],
                                   dtype=np.float64).reshape(n_c, K)
            sig_samples = np.asarray([int(r.sigma) for r in rolls],
                                     dtype=np.float64).reshape(n_c, K)
            tier_samples = np.asarray([int(r.tier) for r in rolls],
                                      dtype=np.float64).reshape(n_c, K)
            health_samples = np.asarray([int(r.health) for r in rolls],
                                        dtype=np.float64).reshape(n_c, K)
            q = q_samples.mean(axis=1)
            if K > 1:
                q_se = q_samples.std(axis=1, ddof=1) / math.sqrt(K)
                sig_se = sig_samples.std(axis=1, ddof=1) / math.sqrt(K)
            else:
                q_se = np.zeros(n_c, dtype=np.float64)
                sig_se = np.zeros(n_c, dtype=np.float64)
            sg = np.rint(sig_samples.mean(axis=1)).astype(np.int64)
            tg = np.rint(tier_samples.mean(axis=1)).astype(np.int64)
            hg = np.rint(health_samples.mean(axis=1)).astype(np.int64)
            pi, tau, V = pi_from_q(p, cands, q, self._rc)
            order = np.argsort(-np.asarray(p, dtype=np.float64)[cands], kind="stable")
            base_idx = int(order[0]) if cands.size else 0
            best_idx = int(np.argmax(q)) if q.size else 0
            n_trunc = int(sum(1 for r in rolls if r.truncated))
            el = (time.perf_counter() - t0) * 1000.0
            self.calls += 1
            self.ms_total += float(el)
            self.leaf_steps += int(steps_total)
            self.truncated += n_trunc
            return SearchOutcome(
                pi=pi, cands=np.asarray(cands, dtype=np.int64), q=q,
                sigma_end=sg, tier_end=tg, health_end=hg, base=int(cands[base_idx]),
                best=int(cands[best_idx]), best_q=float(q[best_idx]),
                sigma_root=int(sigma_root),
                sigma_base=int(sg[base_idx]), sigma_best=int(sg[best_idx]),
                value=float(V), q_std=float(np.std(q)) if q.size else 0.0,
                tau=float(tau), action=int(cands[base_idx]), switch=False,
                elapsed_ms=float(el), leaf_steps=int(steps_total),
                truncated=n_trunc, q_se=q_se, sigma_se=sig_se,
                q_samples=q_samples, rollouts=int(K))
        except Exception:      # noqa: BLE001 - 搜索失败绝不打断评测
            self.errors += 1
            return None

    # ── 内部 ────────────────────────────────────────────────────────────
    def _alive(self, game: Any, seat: int) -> bool:
        try:
            return int(game.health()[int(seat)]) > 0
        except Exception:      # noqa: BLE001 - 旧构建无 health()
            return True

    def _advance_others(self, game: Any, seat: int) -> bool:
        """让其它座位用引擎 bot 走一步（``turns>1`` 时才需要）。返回是否推进过。"""
        moved = False
        for p in range(self.n_players):
            if int(p) == int(seat):
                continue
            if bool(game.is_over()):
                break
            if bool(game.needs_action(int(p))):
                game.bot_play(int(p))
                moved = True
        return moved


# ══════════════════════════════════════════════════════════════════════════
# 4. 策略包装（评测入口）
# ══════════════════════════════════════════════════════════════════════════
class InferSearchPolicy(Policy):
    """把 ``base`` 策略包一层推理期搜索（``enabled=0`` 时逐位等于 base）。

    统计（面板用）：

    - ``search_calls`` / ``search_ms_total`` / ``mean_ms_per_call``（累计，整次评测）；
    - ``game_rows()``：每局的 ``sigma_by_turn``（进入回合时的 Σ）/ ``sigma_end_by_turn``
      （本回合最后一个决策时的 Σ）/ 决策数 / 搜索次数 / 耗时 / 覆盖次数。
    """

    name = "infer_search"

    def __init__(self, base: Policy, *, evaluator: Any = None,
                 config: Optional[InferSearchConfig] = None,
                 device: str = "", n_players: int = 8) -> None:
        self.base = base
        self.cfg = (config or InferSearchConfig()).validate()
        self.name = str(getattr(base, "name", "base")) + (
            "+search" if int(self.cfg.enabled) else "")
        self.playstyle = getattr(base, "playstyle", None)
        self.searcher = (InferSearcher(evaluator, self.cfg, n_players=n_players)
                         if (int(self.cfg.enabled) and evaluator is not None) else None)
        self._rng = np.random.default_rng(int(self.cfg.seed))
        self._game: Optional[Dict[str, Any]] = None
        self.games: List[Dict[str, Any]] = []
        # 整次评测的累计量
        self.decisions = 0
        self.searched_decisions = 0
        self.search_calls = 0
        self.search_ms_total = 0.0
        self.switched = 0
        self.search_errors = 0
        self.leaf_steps = 0
        self.rollout_truncated = 0
        #: K 次采样的叶值标准误累计（随机性感知搜索的方差诊断）
        self.q_se_sum = 0.0
        self.q_spread_sum = 0.0
        self._turn_searched: Dict[Tuple[int, int], int] = {}
        self._dec_in_turn: Dict[Tuple[int, int], int] = {}

    # ── 生命周期 ────────────────────────────────────────────────────────
    def reset(self) -> None:
        self.base.reset()
        self._flush()
        self._game = {"sigma_by_turn": {}, "sigma_end_by_turn": {},
                      "decisions": 0, "search_calls": 0, "search_ms": 0.0,
                      "switched": 0, "max_turn": 0, "tier_by_turn": {}}
        self._turn_searched = {}
        self._dec_in_turn = {}

    def _flush(self) -> None:
        if self._game is not None:
            self.games.append(self._game)
            self._game = None

    def flush(self) -> None:
        """把当前在飞的这一局也收进 ``games``（评测返回后调用；幂等）。"""
        self._flush()

    # ── 统计 ────────────────────────────────────────────────────────────
    @property
    def forced_actions(self) -> int:
        return int(getattr(self.base, "forced_actions", 0))

    @forced_actions.setter
    def forced_actions(self, v: int) -> None:
        try:
            self.base.forced_actions = int(v)
        except Exception:      # noqa: BLE001 - base 无此属性则忽略
            pass

    def move_guard_meta(self) -> Dict[str, Any]:
        """透传 base 的换位守卫统计（``quality_monitor`` 会读它）。"""
        fn = getattr(self.base, "move_guard_meta", None)
        try:
            return dict(fn()) if callable(fn) else {}
        except Exception:      # noqa: BLE001
            return {}

    def stats(self) -> Dict[str, Any]:
        n = int(self.search_calls)
        ng = int(len(self.games))
        return {
            "search_enabled": int(self.cfg.enabled),
            "search_turns": int(self.cfg.turns),
            "search_rollouts": int(self.cfg.rollouts),
            "search_rollout_mode": str(self.cfg.effective_rollout_mode()),
            "search_when": str(self.cfg.search_when),
            "search_action": str(self.cfg.action),
            "decisions": int(self.decisions),
            "search_calls": n,
            "search_ms_total": round(float(self.search_ms_total), 1),
            "mean_ms_per_call": round(float(self.search_ms_total) / n, 2) if n else None,
            "mean_q_se": (round(float(self.q_se_sum) / n, 6) if n else None),
            "mean_q_spread": (round(float(self.q_spread_sum) / n, 6) if n else None),
            "q_se_ratio": (round(float(self.q_se_sum)
                                 / max(float(self.q_spread_sum), 1e-12), 4)
                           if n and self.q_spread_sum > 0 else None),
            "mean_ms_per_decision": (round(float(self.search_ms_total)
                                           / max(int(self.decisions), 1), 3)
                                     if n else None),
            "searched_ratio": (round(float(self.searched_decisions) / max(
                int(self.decisions), 1), 4) if n else None),
            "search_switch": int(self.switched),
            "search_switch_rate": (round(float(self.switched) / n, 4) if n else None),
            "search_errors": int(self.search_errors),
            "search_timeouts": int(getattr(self.searcher, "timeouts", 0)
                                   if self.searcher is not None else 0),
            "rollout_leaf_steps": int(self.leaf_steps),
            "rollout_leaf_steps_per_call": (round(float(self.leaf_steps) / n, 1)
                                            if n else None),
            "rollout_truncated": int(self.rollout_truncated),
            "games": ng,
            "search_calls_per_game": round(float(n) / ng, 2) if ng else None,
            "search_ms_per_game": round(float(self.search_ms_total) / ng, 1) if ng else None,
        }

    def game_rows(self) -> List[Dict[str, Any]]:
        """每局的 Σ(turn) 轨迹（t12/t15 强度比用）。"""
        return list(self.games)

    def snapshot(self) -> Dict[str, Any]:
        """取一个「按增量取数」用的快照（面板按 seat 分段聚合）。"""
        return {"search_calls": self.search_calls,
                "search_ms_total": float(self.search_ms_total),
                "switched": int(self.switched),
                "decisions": int(self.decisions),
                "errors": int(self.search_errors),
                "timeouts": int(getattr(self.searcher, "timeouts", 0)
                                if self.searcher is not None else 0),
                "leaf_steps": int(self.leaf_steps),
                "truncated": int(self.rollout_truncated),
                "searched": int(self.searched_decisions),
                "q_se_sum": float(self.q_se_sum),
                "q_spread_sum": float(self.q_spread_sum),
                "games": int(len(self.games))}

    def since(self, snap: Dict[str, Any]) -> Dict[str, Any]:
        n = int(self.search_calls) - int(snap["search_calls"])
        ms = float(self.search_ms_total) - float(snap["search_ms_total"])
        dec = int(self.decisions) - int(snap["decisions"])
        sw = int(self.switched) - int(snap["switched"])
        games = int(len(self.games)) - int(snap["games"])
        return {"search_calls": n, "search_ms_total": round(ms, 1),
                "mean_ms_per_call": round(ms / n, 2) if n else None,
                "switched": sw, "switch_rate": round(sw / n, 4) if n else None,
                "decisions": dec,
                "search_errors": int(self.search_errors) - int(snap["errors"]),
                "search_timeouts": int(getattr(self.searcher, "timeouts", 0)
                                       if self.searcher is not None else 0)
                - int(snap.get("timeouts", 0)),
                "leaf_steps": int(self.leaf_steps) - int(snap["leaf_steps"]),
                "rollout_truncated": int(self.rollout_truncated) - int(snap["truncated"]),
                "mean_q_se": (round((float(self.q_se_sum)
                                     - float(snap.get("q_se_sum", 0.0))) / n, 6)
                              if n else None),
                "q_se_ratio": (
                    round((float(self.q_se_sum) - float(snap.get("q_se_sum", 0.0)))
                          / max(float(self.q_spread_sum)
                                - float(snap.get("q_spread_sum", 0.0)), 1e-12), 4)
                    if n and (float(self.q_spread_sum)
                              - float(snap.get("q_spread_sum", 0.0))) > 0 else None),
                "games": games,
                "search_calls_per_game": round(n / games, 2) if games else None,
                "search_ms_per_game": round(ms / games, 1) if games else None}

    # ── 决策 ────────────────────────────────────────────────────────────
    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        turn = int(getattr(game, "turn", -1))
        dec = self.base.decide(game, seat)
        action = int(dec.action)
        info: Dict[str, Any] = dict(dec.info or {})
        self.decisions += 1
        g = self._game
        if g is None:
            self._game = g = {"sigma_by_turn": {}, "sigma_end_by_turn": {},
                              "decisions": 0, "search_calls": 0, "search_ms": 0.0,
                              "switched": 0, "max_turn": 0, "tier_by_turn": {}}
        g["decisions"] = int(g["decisions"]) + 1
        g["max_turn"] = max(int(g.get("max_turn", 0)), int(turn))
        # ── Σ(turn) 轨迹（search 开关两条臂都记录，口径完全一致）───────────
        if int(self.cfg.trace) and turn >= 0:
            try:
                f, c = obs_arrays(game.observe(seat))
                sig = int(round(float(sigmas_from_features(f[None, :])[0])))
                g["sigma_by_turn"].setdefault(int(turn), sig)
                g["sigma_end_by_turn"][int(turn)] = sig
                g["tier_by_turn"][int(turn)] = max(
                    0, int(round(float(f[FEAT_TIER]) * FEAT_TIER_SCALE)))
            except Exception:  # noqa: BLE001 - 轨迹是诊断项，失败不影响评测
                pass
        else:
            f = c = None
        if self.searcher is None or bool(info.get("forced")):
            return dec
        if f is None:
            try:
                f, c = obs_arrays(game.observe(seat))
            except Exception:  # noqa: BLE001
                return dec
        key = (seat, turn)
        searched = int(self._turn_searched.get(key, 0))
        tags = self.searcher.tags(f, c)
        if not self.searcher.should_search(tags, searched_this_turn=searched):
            return dec
        mask = mask_from_bytes(game.legal_mask(seat))
        rng = (self._rng if str(self.cfg.action) == "sample" else None)
        out = self.searcher.search(game, seat, prior=dec.pi, mask=mask, rng=rng)
        if out is None:
            return dec
        self._turn_searched[key] = searched + 1
        self.searched_decisions += 1
        self.search_calls += 1
        self.search_ms_total += float(out.elapsed_ms)
        self.leaf_steps += int(out.leaf_steps)
        self.rollout_truncated += int(out.truncated)
        if out.q_se is not None:
            self.q_se_sum += float(np.mean(out.q_se))
            self.q_spread_sum += float(out.q_std)
        g["search_calls"] = int(g["search_calls"]) + 1
        g["search_ms"] = float(g["search_ms"]) + float(out.elapsed_ms)
        # 动作规则
        if str(self.cfg.action) == "argmax_q":
            pick = int(out.best)
        elif str(self.cfg.action) == "sample":
            pw = np.asarray(out.pi, dtype=np.float64)
            s = float(pw.sum())
            pick = (int(self._rng.choice(N_ACTIONS, p=pw / s)) if s > 0 else int(out.best))
        else:
            pick = int(np.argmax(out.pi))
        if pick != int(out.base) and pick != action:
            self.switched += 1
            g["switched"] = int(g["switched"]) + 1
        info.update({"search": True, "search_action": str(self.cfg.action),
                     "search_turns": int(self.cfg.turns),
                     "search_rollouts": int(out.rollouts),
                     "search_q_se_mean": (round(float(np.mean(out.q_se)), 6)
                                          if out.q_se is not None else None),
                     "search_calls": int(g["search_calls"]),
                     "search_base": int(out.base), "search_best": int(out.best),
                     "search_pick": int(pick),
                     "search_sigma_root": int(out.sigma_root),
                     "search_sigma_best": int(out.sigma_best),
                     "search_elapsed_ms": round(float(out.elapsed_ms), 2)})
        return Decision(int(pick if bool(mask[int(pick)]) else action),
                        out.pi, info)


__all__ = ["ACTION_MODES", "HEALTH_REF", "InferSearchConfig", "InferSearchPolicy",
           "InferSearcher", "SearchOutcome", "leaf_score", "leaf_value",
           "trace_summary"]


def trace_summary(rows: List[Dict[str, Any]], turns=(12, 15)) -> Dict[str, Any]:
    """每局 Σ(turn) 轨迹 → 每回合分位 + t12/t15 点名（面板强度比用）。

    输入是 :meth:`InferSearchPolicy.game_rows` 的行；``sigma_by_turn`` 是**进入该回合
    时**的盘面 Σ（与 ``quality_monitor`` 的 per-turn ``strength`` 同口径），
    ``sigma_end_by_turn`` 是**该回合最后一个决策时**的 Σ。
    """
    def _agg(table: Dict[int, List[int]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for t in sorted(table):
            v = np.asarray(table[int(t)], dtype=np.float64)
            out[str(int(t))] = {"n": int(v.size),
                                "p50": round(float(np.percentile(v, 50)), 1),
                                "p75": round(float(np.percentile(v, 75)), 1),
                                "mean": round(float(v.mean()), 1)}
        return out

    start: Dict[int, List[int]] = {}
    end: Dict[int, List[int]] = {}
    last: List[int] = []
    for r in rows:
        for t, v in (r.get("sigma_by_turn") or {}).items():
            start.setdefault(int(t), []).append(int(v))
        for t, v in (r.get("sigma_end_by_turn") or {}).items():
            end.setdefault(int(t), []).append(int(v))
        eb = r.get("sigma_end_by_turn") or {}
        if eb:
            mt = int(r.get("max_turn") or max(int(k) for k in eb))
            last.append(int(eb.get(int(mt), eb[max(eb, key=lambda k: int(k))])))
    named: Dict[str, Any] = {}
    for t in turns:
        ev = np.asarray(end.get(int(t), []), dtype=np.float64)
        sv = np.asarray(start.get(int(t), []), dtype=np.float64)
        named[str(int(t))] = {
            "n": int(ev.size),
            "sigma_start_p50": (round(float(np.percentile(sv, 50)), 1)
                                if sv.size else None),
            "sigma_end_p50": (round(float(np.percentile(ev, 50)), 1)
                              if ev.size else None),
            "sigma_end_mean": (round(float(ev.mean()), 1) if ev.size else None),
        }
    lv = np.asarray(last, dtype=np.float64)
    return {"per_turn_start": _agg(start), "per_turn_end": _agg(end),
            "strength": named, "games": int(len(rows)),
            # 局内最后一个决策时的盘面 Σ（≈ 死亡时强度；t15 在 human 面板上常常
            # 无样本，这是不受「活到 t15」条件限制的强度指标）
            "last_turn_sigma": {
                "n": int(lv.size),
                "p50": round(float(np.percentile(lv, 50)), 1) if lv.size else None,
                "mean": round(float(lv.mean()), 1) if lv.size else None,
            }}

