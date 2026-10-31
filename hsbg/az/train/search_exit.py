"""最小 ExIt 蒸馏：learner-DAgger + 优势加权软 ExIt + KL 信赖域。

严格按 ``docs/SEARCH_DISTILL_THEORY.md`` §5 的推荐方案实现（只实现「最小可跑」的
一轮闭环，不碰 PPO 主循环）：

1. **learner-DAgger 状态覆盖**：行为策略恒为 π_base（``PPOGreedyPolicy`` 的 argmax，
   即部署口径；可选 ``behavior=sample``），在**完整游戏**（Rust 引擎）里跑局。搜索
   **不改变行为动作**，只做标签 —— 与 ``scripts/gen_search_labels_v2.py`` 的 DAgger
   口径一致（沙盒版），把状态分布钉在 learner/部署策略的访问分布上。
2. **标签 = π_search**：对满足 ``search_when``（默认 ``carrier_or_spell``）的决策查询
   :class:`hsbg.az.train.infer_search.InferSearcher`（1 回合 rollout 叶值、top-k 8、
   每回合 ≤3 次，与 ``runs/infer_search_ab`` 完全同源），得到候选上的 ``π_S``、
   每个候选的 ``Q̂``（回合末 Σ 的叶分）与 ``π_base`` 先验 ``p̃``。
3. **优势加权**：``Â(a) = Q̂(a) − Σ_b p̃(b)Q̂(b)``；
   - ``weight_mode=adv``（默认）：样本权重 ``w_i = clamp(Â_i/τ_A, 0, 1)``，
     ``Â_i`` 取 ``max_a Â(a)``（``weight_stat=max``）或 ``Σ_a π_S(a)Â(a)``；
   - ``weight_mode=awr``：逐候选 ``w_a = exp(clip(Â_a/τ_A, -2, 2))``，
     ``L = −Σ_a w_a p_S(a) log π_θ(a) / Σ_a w_a p_S(a)``。
   ``τ_A = tau_scale · std_{p̃}(Q̂)``（与 ``pi_from_q`` 同一 τ）。
   只有 ``w_i ≥ min_weight`` 的状态参与训练 —— 即「搜索确实更优」的决策。
4. **软标签**：``p_S^{(1/T)}`` 归一（``distill_temp``，§5.2 建议 T=2），
   ``L = Σ_i w_i · KL(π_S ‖ π_θ)``（在候选支撑上算 CE，减去教师熵即 KL）。
5. **KL 信赖域**：``KL(π_ref‖π_θ)``（ref = 本轮起点权重，按 probe 状态集算）
   超过 ``kl_anchor``（默认 0.05）⇒ 回退该 epoch 并停止蒸馏；同时监控
   ``KL_max``、熵（不低于 ref 的 ``entropy_floor``）与 sell/refresh 的 top-1 份额
   （``freq_limit``，相对 ref 单轮增幅上限）。

边界（与理论文档一致的自觉约束）：

- 叶值只含盘面 Σ，**不是**终局 rank；蒸馏只在 ``w>0`` 的局部优势上做，不能当成
  「搜索是终局专家」；
- 不改 PPO、不改采集路径、不写 runs/az_entity_*；所有产物落在 ``--out`` 目录；
- 关闭搜索才是验收口径，``capture ratio`` 的分母/分子都由**外部面板**（
  ``scripts/human_panel_eval.py``）给出，本模块只负责「训练 + 记录曲线」。
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .common import N_ACTIONS, mask_from_bytes, obs_arrays
from .infer_search import InferSearchConfig, InferSearcher
from .policies import Decision, Policy
from .sandbox_rollout import pi_from_q, search_when_names, tag_matches
from .sandbox_search import action_kind

#: 策略头参数名（``train_scope=policy`` 只训这些；trunk/辅助头全部冻结）
#: 前 13 项是 entity 的 pointer 头；``policy_head`` 是 tiny 架构的策略输出层。
POLICY_PARAM_PREFIXES = ("scalar_head", "q_buy", "q_board", "buy_bias", "sell_bias",
                         "activate_bias", "choose_bias", "play_bias", "magnetize_bias",
                         "move_bias", "pos_play", "move_from", "move_to",
                         "policy_head")

#: 动作类型门限里关心的段（docs §5.2.6：sell/refresh 相对 base 单轮增幅 ≤1.5×）
GATED_KINDS = ("sell", "refresh")

#: 记录曲线时按类型统计的段
KIND_ORDER = ("end", "refresh", "freeze", "upgrade", "hero_power", "hero_power2",
              "dark_gift", "cancel", "buy", "sell", "activate", "choose", "play",
              "magnetize", "move", "out", "util")


def _pct(vals: Sequence[float], q: float) -> Optional[float]:
    if len(vals) == 0:
        return None
    return float(np.percentile(np.asarray(vals, dtype=np.float64), float(q)))


def _mean(vals: Sequence[float]) -> Optional[float]:
    if len(vals) == 0:
        return None
    return float(np.mean(np.asarray(vals, dtype=np.float64)))


def _std(vals: Sequence[float]) -> Optional[float]:
    if len(vals) == 0:
        return None
    return float(np.std(np.asarray(vals, dtype=np.float64)))


def _masked_softmax(logits: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """行内 masked softmax（非法位严格 0）。"""
    lg = np.where(np.asarray(mask, dtype=bool), np.asarray(logits, dtype=np.float64),
                  -np.inf)
    mx = np.max(lg, axis=-1, keepdims=True)
    e = np.exp(lg - mx)
    e = np.where(np.isfinite(e), e, 0.0)
    s = e.sum(axis=-1, keepdims=True)
    return np.where(s > 0.0, e / np.maximum(s, 1e-12), 0.0)


# ══════════════════════════════════════════════════════════════════════════
# 1. 配置
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class ExitConfig:
    """一轮 ExIt 的全部旋钮（采集 + 搜索口径 + 蒸馏）。"""

    # ── 采集（learner-DAgger）────────────────────────────────────────────
    games: int = 128
    seed_base: int = 600000
    seats: int = 8
    max_steps: int = 50000
    max_actions_per_turn: int = 40
    #: greedy = π_base 的 argmax（= 部署/评测口径）；sample = 按 π_base 采样
    behavior: str = "greedy"
    #: 人类战团注入（与 256 局 human 面板同口径；空 = 纯 bot 对手）
    human_boards: str = ""
    human_board_quantile: str = "auto"
    human_board_set_tier: int = 1

    # ── 搜索口径（与 infer_search / AB 面板同源）──────────────────────────
    turns: int = 1
    topk: int = 8
    max_searches_per_turn: int = 3
    search_when: str = "carrier_or_spell"
    pi_mode: str = "advantage"
    q_temp: float = 0.0
    q_temp_scale: float = 1.0
    adv_clip: float = 30.0
    max_ms_per_search: float = 0.0

    # ── 优势加权（标签层面）──────────────────────────────────────────────
    weight_mode: str = "adv"        # adv | awr | none
    weight_stat: str = "max"        # max | expected（只对 weight_mode=adv）
    tau: float = 0.0                # >0 用固定 τ_A；否则 tau_scale·std(Q̂)
    tau_scale: float = 1.0
    min_weight: float = 1e-3
    distill_temp: float = 2.0       # 软标签温度（π_S^(1/T) 归一）
    awr_clip: float = 2.0           # weight_mode=awr 的指数裁剪

    # ── 蒸馏 ─────────────────────────────────────────────────────────────
    lr: float = 1e-5
    epochs: int = 1
    batch: int = 256
    train_scope: str = "policy"     # policy | all
    weight_decay: float = 0.0
    #: 历史轮聚合：0 = 只用本轮；k>0 = 最近 k 轮一起（DAgger 聚合历史标签）
    agg_rounds: int = 0

    # ── 信赖域 / 门禁 ────────────────────────────────────────────────────
    kl_anchor: float = 0.05         # KL(π_ref‖π_θ) 硬上限（超限回退并停）
    kl_target: float = 0.02         # 每轮 KL(π_old‖π_θ) 预算（达到即停 epoch）
    kl_report_p90: int = 1
    entropy_floor: float = 0.90     # 熵不低于 ref 的 90%（低于则回退并停）
    freq_limit: float = 1.5         # sell/refresh top-1 份额单轮增幅上限
    #: 频率门禁的最小分母（probe 上份额 < freq_min_share 或计数 < freq_min_count 不判）
    freq_min_share: float = 0.03
    freq_min_count: int = 8
    #: probe 状态数（KL 锚/熵/频率都在这个固定子集上算）
    probe_n: int = 1024
    halt_on_gate: int = 1           # 1 = 门禁触发即停止后续蒸馏
    stall_epochs: int = 4           # 损失连续不改善的 epoch 数（收敛提前停）
    #: 1 = 逐 minibatch 快照可训练参数，KL 超预算就回退**该步**（last-in-budget）。
    #: 默认 0 = 只做 epoch 级回退（``runs/search_exit`` 的 A/B 臂就是 0 跑的：
    #: 单个 Adam 步能跨 0.01–0.12 的 KL，故 δ_total=0.05 在 2 轮内就被花完）。
    budget_rollback: int = 0
    seed: int = 0
    device: str = "cuda:7"

    def validate(self) -> "ExitConfig":
        if int(self.turns) < 1:
            raise ValueError("turns 必须 >= 1")
        if int(self.topk) < 2:
            raise ValueError("topk 必须 >= 2")
        if str(self.behavior) not in ("greedy", "sample"):
            raise ValueError("behavior 只能是 greedy|sample")
        if str(self.weight_mode) not in ("adv", "awr", "none"):
            raise ValueError("weight_mode 只能是 adv|awr|none")
        if str(self.weight_stat) not in ("max", "expected"):
            raise ValueError("weight_stat 只能是 max|expected")
        if str(self.train_scope) not in ("policy", "all"):
            raise ValueError("train_scope 只能是 policy|all")
        if float(self.distill_temp) <= 0.0:
            raise ValueError("distill_temp 必须 > 0")
        if float(self.kl_anchor) <= 0.0:
            raise ValueError("kl_anchor 必须 > 0")
        if float(self.kl_target) <= 0.0:
            raise ValueError("kl_target 必须 > 0")
        if float(self.min_weight) < 0.0:
            raise ValueError("min_weight 必须 >= 0")
        if int(self.games) <= 0 or int(self.games) % int(self.seats) != 0:
            raise ValueError("games 必须能被 seats 整除")
        search_when_names(str(self.search_when))     # 触发校验
        return self

    def search_config(self) -> InferSearchConfig:
        return InferSearchConfig(
            enabled=0, turns=int(self.turns), topk=int(self.topk),
            max_searches_per_turn=int(self.max_searches_per_turn),
            search_when=str(self.search_when), action="pi_argmax",
            pi_mode=str(self.pi_mode), q_temp=float(self.q_temp),
            q_temp_scale=float(self.q_temp_scale), adv_clip=float(self.adv_clip),
            max_ms_per_search=float(self.max_ms_per_search),
            seed=int(self.seed)).validate()

    def as_dict(self) -> Dict[str, Any]:
        return {k: (v if isinstance(v, (int, float, str, bool)) else str(v))
                for k, v in self.__dict__.items()}


# ══════════════════════════════════════════════════════════════════════════
# 2. 采集：π_base 行为 + 关键决策查询搜索（DAgger）
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class SearchSample:
    """一个被搜索的决策点（标签 + 状态 + 权重原料）。"""

    f: np.ndarray          # f16[3227] 观测特征
    c: np.ndarray          # i16[124] 卡牌下标
    mask: np.ndarray       # bool[245] 合法掩码
    cands: np.ndarray      # i16[n] 候选动作（π_base 先验降序）
    p_base: np.ndarray     # f32[n] 候选上的 π_base 先验（已归一 = p̃）
    p_s: np.ndarray        # f32[n] π_search 在候选上的分布
    q: np.ndarray          # f32[n] 候选叶分 = L(Σ_end)
    adv: np.ndarray        # f32[n] 优势 Â = Q̂ − Σ p̃ Q̂
    q_std: float
    tau: float
    base: int
    teacher: int           # π_search 的 top-1
    turn: int
    seat: int
    seed: int
    game: int
    sigma_root: int
    switch: bool

    def to_npz(self) -> Dict[str, np.ndarray]:
        return {"f": self.f, "c": self.c, "mask": self.mask, "cands": self.cands,
                "p_base": self.p_base, "p_s": self.p_s, "q": self.q, "adv": self.adv,
                "meta": np.asarray([self.q_std, self.tau, float(self.base),
                                    float(self.teacher), float(self.turn),
                                    float(self.seat), float(self.seed),
                                    float(self.game), float(self.sigma_root),
                                    float(bool(self.switch))], dtype=np.float64)}


def sample_weight(s: SearchSample, cfg: ExitConfig) -> Tuple[float, Dict[str, float]]:
    """按 §5 的口径算样本权重（adv 模式）与诊断量。"""
    adv = np.asarray(s.adv, dtype=np.float64)
    ps = np.asarray(s.p_s, dtype=np.float64)
    tau = float(cfg.tau) if float(cfg.tau) > 0.0 else max(
        1e-6, float(cfg.tau_scale) * float(s.q_std))
    if str(cfg.weight_mode) == "none":
        w = 1.0
    elif str(cfg.weight_stat) == "expected":
        w = float(np.clip(np.dot(ps, adv) / max(tau, 1e-6), 0.0, 1.0))
    else:
        w = float(np.clip(np.max(adv) / max(tau, 1e-6), 0.0, 1.0))
    if str(cfg.weight_mode) == "awr":
        # AWR：损失内部逐候选加权，样本权重只用于筛选
        wa = np.exp(np.clip(adv / max(tau, 1e-6), -float(cfg.awr_clip),
                            float(cfg.awr_clip)))
        w = float(np.clip(float(np.dot(ps, wa)) - 1.0, 0.0, 1e9))
    return w, {"tau": tau, "adv_max": float(np.max(adv)),
               "adv_expected": float(np.dot(ps, adv)),
               "adv_min": float(np.min(adv))}


class ExitCollector(Policy):
    """π_base 行为的采集器：关键决策查询搜索，只记录标签、**不改动作**。"""

    name = "exit_collector"

    def __init__(self, base: Policy, evaluator: Any, cfg: ExitConfig, *,
                 n_players: int = 8) -> None:
        self.base = base
        self.cfg = cfg
        self.searcher = InferSearcher(evaluator, cfg.search_config(),
                                      n_players=int(n_players))
        self._when = search_when_names(str(cfg.search_when))
        self._rng = np.random.default_rng(int(cfg.seed))
        self.samples: List[SearchSample] = []
        self.decisions = 0
        self.searched = 0
        self.games = 0
        self.errors = 0
        self.switched = 0
        self.forced = 0
        self._turn_searched: Dict[Tuple[int, int], int] = {}
        self._dec_in_turn: Dict[Tuple[int, int], int] = {}
        #: 当前 seat 的 seed 起点与局内序号（由 :meth:`begin_seat` 设定）
        self._seat_seed = 0
        self._game_in_seat = -1

    # ── 生命周期 ────────────────────────────────────────────────────────
    def begin_seat(self, seat: int, seed: int) -> None:
        """开始一个新 seat 的 seed 块（``reset()`` 每局调用一次，序号自增）。"""
        self._seat_seed = int(seed)
        self._game_in_seat = -1

    def reset(self) -> None:
        self.base.reset()
        self._turn_searched = {}
        self._dec_in_turn = {}
        self._game_in_seat += 1
        self.games += 1

    @property
    def game_seed(self) -> int:
        return int(self._seat_seed) + int(self._game_in_seat)

    # ── 决策 ────────────────────────────────────────────────────────────
    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        dec = self.base.decide(game, seat)
        self.decisions += 1
        if bool((dec.info or {}).get("forced")):
            self.forced += 1
            return dec
        turn = int(getattr(game, "turn", -1))
        f, c = obs_arrays(game.observe(seat))
        mask = mask_from_bytes(game.legal_mask(seat))
        tags = self.searcher.tags(f, c)
        key = (seat, turn)
        n_turn = int(self._dec_in_turn.get(key, 0)) + 1
        self._dec_in_turn[key] = n_turn
        if not self.searcher.should_search(
                tags, searched_this_turn=int(self._turn_searched.get(key, 0))):
            return dec
        prior = dec.pi
        if prior is None or not np.all(np.isfinite(np.asarray(prior, dtype=np.float32))):
            prior = None
        out = self.searcher.search(game, seat, prior=prior, mask=mask)
        if out is None:
            self.errors += 1
            return dec
        self._turn_searched[key] = int(self._turn_searched.get(key, 0)) + 1
        self.searched += 1
        # ── 优势与先验（与 pi_from_q 完全同一口径）───────────────────────
        cands = np.asarray(out.cands, dtype=np.int64)
        q = np.asarray(out.q, dtype=np.float64)
        p = (self.searcher.prior_batch(f[None, :], c[None, :], mask[None, :])[0]
             if prior is None else np.asarray(prior, dtype=np.float64))
        p = np.where(np.isfinite(p) & (p > 0), p, 0.0)
        pc = p[cands]
        if float(pc.sum()) <= 0.0:
            pc = np.ones(cands.size, dtype=np.float64)
        pc = pc / float(pc.sum())
        V = float(np.dot(pc, q))
        adv = q - V
        q_std = float(math.sqrt(max(0.0, float(np.dot(pc, (q - V) ** 2)))))
        ps = np.asarray(out.pi, dtype=np.float64)[cands]
        if float(ps.sum()) <= 0.0:
            ps = pc
        ps = ps / float(ps.sum())
        teacher = int(cands[int(np.argmax(ps))])
        switch = bool(int(out.base) != teacher)
        self.switched += int(switch)
        self.samples.append(SearchSample(
            f=f.astype(np.float16), c=c.astype(np.int16), mask=mask.astype(bool),
            cands=cands.astype(np.int16), p_base=pc.astype(np.float32),
            p_s=ps.astype(np.float32), q=q.astype(np.float32),
            adv=adv.astype(np.float32), q_std=float(q_std), tau=float(out.tau),
            base=int(out.base), teacher=int(teacher), turn=int(turn), seat=int(seat),
            seed=int(self.game_seed), game=int(self.games - 1),
            sigma_root=int(out.sigma_root), switch=switch))
        if str(self.cfg.behavior) == "sample":
            pw = np.asarray(dec.pi, dtype=np.float64)
            s = float(pw.sum())
            a = (int(self._rng.choice(N_ACTIONS, p=pw / s)) if s > 0 else int(dec.action))
            if bool(mask[a]):
                return Decision(a, dec.pi, dec.info)
        return dec

    def stats(self) -> Dict[str, Any]:
        return {"games": int(self.games), "decisions": int(self.decisions),
                "searched": int(self.searched),
                "searched_ratio": (float(self.searched) / max(int(self.decisions), 1)),
                "switch": int(self.switched),
                "switch_rate": (float(self.switched) / max(int(self.searched), 1)),
                "errors": int(self.errors), "forced": int(self.forced),
                "search_ms_total": round(float(self.searcher.ms_total), 1),
                "leaf_steps": int(self.searcher.leaf_steps),
                "search_calls": int(self.searcher.calls)}


def collect_round(model: Any, evaluator: Any, cfg: ExitConfig, *,
                  seed_base: int, out_npz: str = "") -> Tuple[Any, Dict[str, Any]]:
    """跑一轮 DAgger 采集（learner 座位轮换，人类战团注入与面板同口径）。"""
    from .evaluate import EvalConfig, evaluate_policy
    from .human_board_pool import load_pool
    from .ppo import PPOGreedyPolicy

    pool = None
    if str(cfg.human_boards):
        pool = load_pool(str(cfg.human_boards), sample=str(cfg.human_board_quantile))
    base = PPOGreedyPolicy(evaluator, max_actions_per_turn=int(cfg.max_actions_per_turn))
    col = ExitCollector(base, evaluator, cfg)
    per_seat = int(cfg.games) // max(int(cfg.seats), 1)
    t0 = time.time()
    for seat in range(int(cfg.seats)):
        seed = int(seed_base) + seat * per_seat
        ec = EvalConfig(games=per_seat, seed=seed, policy_seat=seat,
                        max_steps=int(cfg.max_steps), human_board_pool=pool)
        col.begin_seat(seat, seed)
        evaluate_policy(col, ec)
    stats = col.stats()
    stats.update({"seed_base": int(seed_base), "seconds": round(time.time() - t0, 1),
                  "per_seat": per_seat, "seats": int(cfg.seats),
                  "human_board_pool": (pool.stats() if pool is not None else None)})
    weights = [sample_weight(s, cfg)[0] for s in col.samples]
    stats.update({
        "n_states": int(len(col.samples)),
        "mean_weight": _mean(weights),
        "kept": int(sum(1 for w in weights if w >= float(cfg.min_weight))),
        "kept_ratio": (float(sum(1 for w in weights if w >= float(cfg.min_weight)))
                       / max(len(weights), 1)),
        "mean_adv_max": _mean([float(np.max(s.adv)) for s in col.samples]),
        "mean_q_std": _mean([float(s.q_std) for s in col.samples]),
        "teacher_top1_mass": _mean([float(np.max(s.p_s)) for s in col.samples]),
        "base_teacher_agree": _mean([1.0 if s.base == s.teacher else 0.0
                                     for s in col.samples]),
        "mean_sigma_root": _mean([float(s.sigma_root) for s in col.samples]),
    })
    if out_npz:
        _save_samples(col.samples, out_npz)
        stats["npz"] = str(out_npz)
    return col.samples, stats


def _save_samples(samples: Sequence[SearchSample], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    f = np.stack([s.f for s in samples]) if samples else np.zeros((0, 0), np.float16)
    c = np.stack([s.c for s in samples]) if samples else np.zeros((0, 0), np.int16)
    mask = np.stack([s.mask for s in samples]) if samples else np.zeros((0, 0), bool)
    n = len(samples)
    nmax = max([len(s.cands) for s in samples], default=0)
    cands = np.full((n, nmax), -1, dtype=np.int16)
    p_base = np.zeros((n, nmax), dtype=np.float32)
    p_s = np.zeros((n, nmax), dtype=np.float32)
    q = np.zeros((n, nmax), dtype=np.float32)
    adv = np.zeros((n, nmax), dtype=np.float32)
    meta = np.zeros((n, 10), dtype=np.float64)
    for i, s in enumerate(samples):
        k = len(s.cands)
        cands[i, :k] = s.cands
        p_base[i, :k] = s.p_base
        p_s[i, :k] = s.p_s
        q[i, :k] = s.q
        adv[i, :k] = s.adv
        meta[i] = s.to_npz()["meta"]
    np.savez_compressed(path, f=f, c=c, mask=mask, cands=cands, p_base=p_base,
                        p_s=p_s, q=q, adv=adv, meta=meta)


def load_samples(path: str) -> List[SearchSample]:
    z = np.load(path)
    n = int(z["mask"].shape[0])
    out: List[SearchSample] = []
    for i in range(n):
        meta = z["meta"][i]
        k = int((z["cands"][i] >= 0).sum())
        out.append(SearchSample(
            f=z["f"][i], c=z["c"][i], mask=z["mask"][i],
            cands=z["cands"][i, :k].astype(np.int16),
            p_base=z["p_base"][i, :k], p_s=z["p_s"][i, :k],
            q=z["q"][i, :k], adv=z["adv"][i, :k],
            q_std=float(meta[0]), tau=float(meta[1]), base=int(meta[2]),
            teacher=int(meta[3]), turn=int(meta[4]), seat=int(meta[5]),
            seed=int(meta[6]), game=int(meta[7]), sigma_root=int(meta[8]),
            switch=bool(meta[9])))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3. 蒸馏：优势加权软标签 KL + KL 信赖域
# ══════════════════════════════════════════════════════════════════════════
def _torch():
    import torch
    return torch


def policy_param_names(model: Any) -> List[str]:
    return [n for n, _ in model.named_parameters()
            if any(n.startswith(p) for p in POLICY_PARAM_PREFIXES)]


class ExitTrainer:
    """在一批搜索标签上做「优势加权软 ExIt + KL 信赖域」。"""

    def __init__(self, model: Any, ref_model: Any, cfg: ExitConfig,
                 *, device: str = "cuda:7") -> None:
        torch = _torch()
        self.torch = torch
        self.model = model
        self.ref = ref_model
        #: 本轮起点权重（π_old）：每轮预算 KL(π_old‖π_θ) ≤ kl_target
        self.prev = copy.deepcopy(model)
        self.prev.eval()
        for p in self.prev.parameters():
            p.requires_grad_(False)
        self.cfg = cfg
        self.device = torch.device(device)
        self.model.eval()
        self.ref.eval()
        #: tiny 架构的 ``forward(features, cards)`` 没有 mask 形参（entity 有）；
        #: 掩码在 :meth:`_logp` 里统一再打一次（幂等），两种架构行为一致。
        import inspect
        self._takes_mask = "mask" in inspect.signature(model.forward).parameters
        for p in self.ref.parameters():
            p.requires_grad_(False)
        names = (policy_param_names(model) if str(cfg.train_scope) == "policy"
                 else [n for n, _ in model.named_parameters()])
        self.trainable = [n for n in names]
        params = [p for n, p in model.named_parameters() if n in set(self.trainable)]
        for n, p in model.named_parameters():
            p.requires_grad_(n in set(self.trainable))
        self.opt = torch.optim.Adam(params, lr=float(cfg.lr),
                                    weight_decay=float(cfg.weight_decay))
        self.n_params = int(sum(p.numel() for p in params))
        self.held = 0
        self.gates: List[Dict[str, Any]] = []

    # ── 张量 ────────────────────────────────────────────────────────────
    def _tensors(self, samples: Sequence[SearchSample]) -> Dict[str, Any]:
        torch = self.torch
        n = len(samples)
        kmax = max([len(s.cands) for s in samples], default=1)
        f = np.stack([s.f for s in samples]).astype(np.float32)
        c = np.stack([s.c for s in samples]).astype(np.int64)
        mask = np.stack([s.mask for s in samples]).astype(bool)
        cand = np.zeros((n, kmax), dtype=np.int64)
        pb = np.zeros((n, kmax), dtype=np.float32)
        ps = np.zeros((n, kmax), dtype=np.float32)
        q = np.zeros((n, kmax), dtype=np.float32)
        adv = np.zeros((n, kmax), dtype=np.float32)
        for i, s in enumerate(samples):
            k = len(s.cands)
            cand[i, :k] = s.cands
            pb[i, :k] = s.p_base
            ps[i, :k] = s.p_s
            q[i, :k] = s.q
            adv[i, :k] = s.adv
        out = {
            "f": torch.from_numpy(f).to(self.device),
            "c": torch.from_numpy(c).to(self.device),
            "mask": torch.from_numpy(mask).to(self.device),
            "cand": torch.from_numpy(cand).to(self.device),
            "p_base": torch.from_numpy(pb).to(self.device),
            "p_s": torch.from_numpy(ps).to(self.device),
            "q": torch.from_numpy(q).to(self.device),
            "adv": torch.from_numpy(adv).to(self.device),
        }
        # 每样本 τ_A（与 pi_from_q 同一 τ：q_temp_scale·std_{p̃}(Q̂)）与权重
        w = np.zeros(n, dtype=np.float32)
        tau = np.zeros(n, dtype=np.float32)
        for i, s in enumerate(samples):
            w[i] = sample_weight(s, self.cfg)[0]
            tau[i] = (float(self.cfg.tau) if float(self.cfg.tau) > 0.0 else max(
                1e-6, float(self.cfg.tau_scale) * float(s.q_std)))
        if str(self.cfg.weight_mode) == "awr":
            # AWR 的加权在损失内部（逐候选 w_a），样本权重只当筛选闸门
            w = np.ones(n, dtype=np.float32)
        out["w"] = torch.from_numpy(w).to(self.device)
        out["tau"] = torch.from_numpy(tau).to(self.device)
        return out

    def _teacher(self, t: Dict[str, Any]) -> Dict[str, Any]:
        torch = self.torch
        ps = t["p_s"]
        if str(self.cfg.weight_mode) == "awr":
            wa = torch.exp(torch.clamp(t["adv"] / torch.clamp(t["tau"], min=1e-6),
                                       -float(self.cfg.awr_clip),
                                       float(self.cfg.awr_clip)))
            tgt = ps * wa
        else:
            tgt = ps
        if float(self.cfg.distill_temp) != 1.0:
            # 注意：**先判零再取幂**（clamp 到 1e-12 再开方会把 0 变成 1e-6，
            # 在非法动作 logp≈-1e9 处放大成 ~1e3 的伪 KL；曾把 probe KL 骗成 610）
            tgt = torch.where(tgt > 0,
                              torch.pow(torch.clamp(tgt, min=1e-30),
                                        1.0 / float(self.cfg.distill_temp)),
                              torch.zeros_like(tgt))
        s = tgt.sum(dim=1, keepdim=True)
        tgt = torch.where(s > 0, tgt / torch.clamp(s, min=1e-12), ps)
        t["tgt"] = tgt.detach()
        return t

    def _logp(self, model: Any, t: Dict[str, Any], *, grad: bool = True) -> Any:
        torch = self.torch
        with torch.set_grad_enabled(bool(grad)):
            logits = (model(t["f"], t["c"], t["mask"]) if self._takes_mask
                      else model(t["f"], t["c"]))[0]
            logits = logits.masked_fill(~t["mask"].bool(), -1e9)
            return torch.log_softmax(logits, dim=-1)

    def _loss(self, t: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
        torch = self.torch
        logp = self._logp(self.model, t, grad=True)
        tgt = t["tgt"]
        picked = logp.gather(1, t["cand"])
        pos = (tgt > 0).float()
        ce = -(torch.where(pos > 0, tgt * picked, torch.zeros_like(picked))).sum(-1)
        h = -(torch.where(pos > 0, tgt * torch.log(torch.clamp(tgt, min=1e-12)),
                          torch.zeros_like(tgt))).sum(-1)
        kl = ce - h
        w = t["w"]
        sw = torch.clamp(w.sum(), min=1e-8)
        loss = (w * kl).sum() / sw
        return loss, {"ce": float(ce.detach().mean()), "kl": float(kl.detach().mean()),
                      "h": float(h.detach().mean())}

    # ── 监控 ────────────────────────────────────────────────────────────
    def probe(self, samples: Sequence[SearchSample], *, n: int = 0,
              seed: int = 0) -> Dict[str, Any]:
        """固定 probe 集上的 KL(ref‖θ)、熵、KL_max、动作类型 top-1 份额。"""
        torch = self.torch
        if not samples:
            return {}
        idx = np.arange(len(samples))
        n = int(n or getattr(self.cfg, "probe_n", 1024) or 1024)
        if idx.size > n:
            rng = np.random.default_rng(int(seed))
            idx = np.sort(rng.choice(idx, size=int(n), replace=False))
        sub = [samples[int(i)] for i in idx]
        t = self._teacher(self._tensors(sub))
        with torch.no_grad():
            logp = self._logp(self.model, t, grad=False)
            ref_logp = self._logp(self.ref, t, grad=False)
            prev_logp = self._logp(self.prev, t, grad=False)
            p_ref = ref_logp.exp()
            kl = (p_ref * (ref_logp - logp)).sum(-1)
            p_prev = prev_logp.exp()
            kl_prev = (p_prev * (prev_logp - logp)).sum(-1)
            ent = -(logp.exp() * logp).sum(-1)
            ent_ref = -(p_ref * ref_logp).sum(-1)
            arg = logp.masked_fill(~t["mask"], -1e9).argmax(-1)
            arg_ref = ref_logp.masked_fill(~t["mask"], -1e9).argmax(-1)
            arg_prev = prev_logp.masked_fill(~t["mask"], -1e9).argmax(-1)
        kinds = [action_kind(int(a)) for a in arg.cpu().numpy().tolist()]
        kinds_ref = [action_kind(int(a)) for a in arg_ref.cpu().numpy().tolist()]
        kinds_prev = [action_kind(int(a)) for a in arg_prev.cpu().numpy().tolist()]
        n_s = max(len(kinds), 1)

        def _share(ks: Sequence[str], name: str) -> float:
            return sum(1 for k in ks if k == name) / n_s

        kl_np = kl.cpu().numpy()
        klp_np = kl_prev.cpu().numpy()
        # 教师（软化标签）与当前策略的 KL：诊断「蒸馏拟合误差」
        tgt = t["tgt"]
        kl_t = ((tgt * (torch.log(torch.clamp(tgt, min=1e-12))
                        - logp.gather(1, t["cand"]))).sum(-1))
        return {
            "n": int(len(sub)),
            "kl_to_ref_mean": float(kl_np.mean()),
            "kl_to_ref_p50": float(np.percentile(kl_np, 50)),
            "kl_to_ref_p90": float(np.percentile(kl_np, 90)),
            "kl_to_ref_p99": float(np.percentile(kl_np, 99)),
            "kl_to_ref_max": float(kl_np.max()),
            "kl_to_prev_mean": float(klp_np.mean()),
            "kl_to_prev_p90": float(np.percentile(klp_np, 90)),
            "kl_to_prev_max": float(klp_np.max()),
            "kl_to_teacher_mean": float(kl_t.mean()),
            "entropy": float(ent.mean()),
            "entropy_ref": float(ent_ref.mean()),
            "entropy_ratio": float(ent.mean() / max(float(ent_ref.mean()), 1e-9)),
            "top1_share": {k: _share(kinds, k) for k in KIND_ORDER},
            "top1_share_ref": {k: _share(kinds_ref, k) for k in KIND_ORDER},
            "top1_share_prev": {k: _share(kinds_prev, k) for k in KIND_ORDER},
            "teacher_top1_agree": float(
                (arg.reshape(-1) == t["cand"][torch.arange(len(sub), device=self.device),
                                              tgt.argmax(-1)]).float().mean()),
        }

    # ── 可训练参数快照（last-in-budget 回退用；只 1 MB 级）────────────────
    def _snap(self) -> Dict[str, Any]:
        keep = set(self.trainable)
        return {n: p.detach().clone() for n, p in self.model.named_parameters()
                if n in keep}

    def _restore(self, snap: Dict[str, Any]) -> None:
        for n, p in self.model.named_parameters():
            if n in snap:
                p.data.copy_(snap[n])

    # ── 训练 ────────────────────────────────────────────────────────────
    def fit(self, samples: Sequence[SearchSample], *, round_id: int = 0,
            probe_samples: Optional[Sequence[SearchSample]] = None
            ) -> Dict[str, Any]:
        torch = self.torch
        cfg = self.cfg
        trainable = [s for s in samples
                     if (str(cfg.weight_mode) == "none"
                         or sample_weight(s, cfg)[0] >= float(cfg.min_weight))]
        self.held = len(samples) - len(trainable)
        probe = list(probe_samples if probe_samples is not None else samples)
        before = self.probe(probe, seed=int(cfg.seed) + int(round_id))
        hist: List[Dict[str, Any]] = []
        if not trainable:
            return {"round": int(round_id), "n_train": 0, "n_held": self.held,
                    "before": before, "after": before, "epochs": [],
                    "gate": None, "params": self.n_params,
                    "trainable": len(self.trainable)}
        rng = np.random.default_rng(int(cfg.seed) + 7919 * (int(round_id) + 1))
        gate: Optional[Dict[str, Any]] = None
        stop_reason = ""
        prev_loss = float("inf")
        stall = 0
        for ep in range(int(cfg.epochs)):
            # 硬锚回退用的快照（按 epoch；逐 minibatch 只做预算检查）
            snap = {k: v.detach().clone() for k, v in self.model.state_dict().items()}
            order = rng.permutation(len(trainable))
            ep_stats: List[Dict[str, float]] = []
            t0 = time.time()
            budget_hit = False
            for start in range(0, len(order), int(cfg.batch)):
                idx = order[start:start + int(cfg.batch)]
                batch = [trainable[int(i)] for i in idx]
                t = self._teacher(self._tensors(batch))
                loss, st = self._loss(t)
                self.opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    [p for p in self.model.parameters() if p.requires_grad], 5.0)
                # last-in-budget：step 前快照可训练参数（只在 rollback 模式下）
                prev_step = self._snap() if int(cfg.budget_rollback) else None
                self.opt.step()
                ep_stats.append(st)
                # ── 逐 minibatch 检查 KL 预算/硬锚（细粒度，避免 1 个 epoch 冲过锚）──
                # **必须与报告用同一个 probe 集合**：早期版本这里传 n=512、报告传
                # n=probe_n(1024)，两个子集不嵌套 ⇒ 检查低估 KL（第 2 轮 0.01→0.027 的
                # 一半原因是这个测量错配）。现在统一用 cfg.probe_n。
                lp = self.probe(probe, seed=int(cfg.seed) + int(round_id))
                _over_anchor = float(lp["kl_to_ref_mean"]) > float(cfg.kl_anchor)
                _over_budget = float(lp["kl_to_prev_mean"]) >= float(cfg.kl_target)
                if int(cfg.budget_rollback) and (_over_anchor or _over_budget):
                    # 这一步越界 ⇒ 回退到**上一步**（in-budget 权重）后停
                    self._restore(prev_step)
                    stop_reason = "gate_rollback" if _over_anchor else "kl_target"
                    budget_hit = True
                    break
                if _over_anchor:
                    self.model.load_state_dict(snap)
                    gate = {"epoch": int(ep), "batch": int(len(ep_stats)),
                            "reasons": [f"kl_to_ref={lp['kl_to_ref_mean']:.4f}"
                                        f">{cfg.kl_anchor}"],
                            "reverted": True,
                            "probe_after_revert": self.probe(
                                probe, seed=int(cfg.seed) + int(round_id))}
                    hist.append({"gate": gate})
                    stop_reason = "gate"
                    budget_hit = True
                    break
                if float(lp["kl_to_prev_mean"]) >= float(cfg.kl_target):
                    stop_reason = "kl_target"
                    budget_hit = True
                    break
            if budget_hit:
                break
            ep_probe = self.probe(probe, seed=int(cfg.seed) + int(round_id))
            mean_ce = _mean([s["ce"] for s in ep_stats])
            row = {"epoch": int(ep), "n_batches": len(ep_stats),
                   "loss_ce": mean_ce,
                   "loss_kl": _mean([s["kl"] for s in ep_stats]),
                   "teacher_entropy": _mean([s["h"] for s in ep_stats]),
                   "seconds": round(time.time() - t0, 2), **ep_probe}
            hist.append(row)
            # ── 门禁：KL 硬锚 / 熵地板 / sell+refresh 单轮份额 ─────────────
            reasons: List[str] = []
            if float(ep_probe["kl_to_ref_mean"]) > float(cfg.kl_anchor):
                reasons.append(f"kl_to_ref={ep_probe['kl_to_ref_mean']:.4f}"
                               f">{cfg.kl_anchor}")
            if float(ep_probe["entropy_ratio"]) < float(cfg.entropy_floor):
                reasons.append(f"entropy_ratio={ep_probe['entropy_ratio']:.3f}"
                               f"<{cfg.entropy_floor}")
            n_pr = max(int(ep_probe.get("n", 1)), 1)
            for k in GATED_KINDS:
                base_sh = float(ep_probe["top1_share_prev"].get(k, 0.0))
                now_sh = float(ep_probe["top1_share"].get(k, 0.0))
                if (base_sh >= float(cfg.freq_min_share)
                        and round(now_sh * n_pr) - round(base_sh * n_pr)
                        >= int(cfg.freq_min_count)
                        and now_sh > float(cfg.freq_limit) * base_sh):
                    reasons.append(f"{k}_share {base_sh:.3f}->{now_sh:.3f}"
                                   f">{cfg.freq_limit}x")
            if reasons:
                self.model.load_state_dict(snap)
                gate = {"epoch": int(ep), "reasons": reasons,
                        "reverted": True,
                        "probe_after_revert": self.probe(
                            probe, seed=int(cfg.seed) + int(round_id))}
                hist.append({"gate": gate})
                stop_reason = "gate"
                break
            # ── 每轮 KL 预算（KL(π_old‖π_θ) ≤ kl_target）与收敛提前停 ────
            if float(ep_probe["kl_to_prev_mean"]) >= float(cfg.kl_target):
                stop_reason = "kl_target"
                break
            _ce = float(mean_ce or 0.0)
            if _ce >= prev_loss * (1.0 - 1e-3):
                stall += 1
                if stall >= max(int(cfg.stall_epochs), 1):
                    stop_reason = "stall"
                    break
            else:
                stall = 0
            prev_loss = min(prev_loss, _ce)
        after = self.probe(probe, seed=int(cfg.seed) + int(round_id))
        return {"round": int(round_id), "n_train": len(trainable),
                "n_held": int(self.held), "before": before, "after": after,
                "epochs": hist, "gate": gate, "params": self.n_params,
                "trainable": len(self.trainable), "lr": float(cfg.lr),
                "scope": str(cfg.train_scope), "stop_reason": stop_reason,
                "n_epochs": len([h for h in hist if "epoch" in h])}


__all__ = ["ExitConfig", "ExitCollector", "ExitTrainer", "POLICY_PARAM_PREFIXES",
           "GATED_KINDS", "KIND_ORDER", "SearchSample", "collect_round",
           "load_samples", "policy_param_names", "sample_weight"]
