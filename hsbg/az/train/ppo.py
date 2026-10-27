"""MCTS 引导的 PPO 训练阶段（不完全信息 MCTS + 自对弈 + PPO）。

**定位（务必与纯 AlphaZero 区分）**

纯 AlphaZero 的目标是 ``CE(π_MCTS, π_θ)``：用搜索 visit 分布做蒸馏，行为动作也来自
MCTS。本模块是 **MCTS 引导的 PPO（MCTS-guided PPO）**：

- 主目标：PPO clipped surrogate（固定 245 动作、masked softmax），importance ratio 的
  分母是**行为策略实际分布**下的 ``old_logprob``；
- 辅助目标：``alpha * CE(π_MCTS, π_θ)``，``alpha=pi_coef`` 可配、可 0 关闭；
- 价值：rank 头（名次 CE）或 value MSE，二选一可配；critic 价值统一取
  ``E_{p(r)}[u(r)]``（``u(r)=1-2*(r-1)/(N-1)``），因此 tiny/entity 两个 arch 一致；
- 行为策略可配置：
  - ``behavior="net"``：动作由网络 masked softmax 采样（严格 on-policy PPO），
    同时（若开了 ``search_fn``）用 MCTS visit π 作辅助 CE 目标 —— 默认路径；
  - ``behavior="mcts"``：动作由 MCTS visit π 采样，``old_logprob=log π_MCTS[a]``
    （行为策略=MCTS 的 off-policy ratio；不是严格 on-policy，慎用于大 lr）；
  - ``behavior="mixed"``：``μ=(1-ε)π_MCTS+ε π_net`` 采样，记录 μ 下精确 logprob。

**轨迹来源**

``collect_ppo_batch`` 复用 ``hsbg.az.train.selfplay.play_selfplay_game`` 做 8 座自对弈
（或 1 个学习座 vs 引擎 bot），每个决策记录：``features[3227]``、``cards[124]``、
``mask[245]``、``action``、``old_logprob``、``value``、``reward``（终局 placement
utility + 可选小 step penalty）、``done``、``seat``、``game_id``、``rank``，以及可选的
MCTS visit ``π``。按 ``(game_id, seat)`` 分组计算 GAE(λ) 与 reward-to-go；截断局
（rank=0）丢弃。

**硬约束**

- 动作空间固定 245；所有概率都在合法掩码上做 masked softmax，非法动作概率恒 0；
- 只依赖 numpy / 可选 torch / ``hsbg.az.*``；引擎相关入口惰性加载，无引擎机器上
  本模块仍可 import（masked logprob / GAE / PPO loss 的单测不依赖引擎）。
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .common import (
    N_ACTIONS,
    N_PLAYERS,
    N_RANKS,
    OBS_CARDS,
    OBS_FLOATS,
    RANK_UTILITY,
    load_engine,
    mask_from_bytes,
    masked_normalize,
    obs_arrays,
    to_jsonable,
    utility_from_rank,
)
from .policies import Decision, Policy

# ── 数值边界 ──────────────────────────────────────────────────────────────
#: torch 侧非法 logits 的填充值（float32 下 ``exp(-1e30)=0``，避免 -inf 制造 NaN 梯度）。
MASKED_LOGIT = -1e30
#: logprob 下限（行为分布采样时防 log(0)）。
LOGPROB_FLOOR = 1e-12


def _torch():
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - 缺 torch 时给出可读错误
        raise RuntimeError("torch 不可用：PPO 训练需要 `pip install torch`") from exc
    return torch


def torch_available() -> bool:
    """当前环境是否可 import torch。"""
    try:
        import torch  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════
# 1. masked softmax / logprob（numpy 与 torch 两套；非法动作概率恒 0）
# ══════════════════════════════════════════════════════════════════════════
def masked_log_softmax_np(logits: Any, mask: Any, temperature: float = 1.0) -> np.ndarray:
    """合法动作上的 log-softmax（非法位 = ``-inf``）。

    温度 τ>0：``log softmax(logits / τ)``；全无合法动作时整行 ``-inf``。
    """
    x = np.asarray(logits, dtype=np.float64).reshape(-1)
    m = np.asarray(mask, dtype=bool).reshape(-1)
    if x.shape != m.shape:
        raise ValueError(f"logits 与 mask 形状不一致: {x.shape} vs {m.shape}")
    t = float(temperature)
    if not math.isfinite(t) or t <= 0.0:
        raise ValueError(f"temperature 必须为正有限数，得到 {temperature!r}")
    if not bool(m.any()):
        return np.full(x.shape, -np.inf, dtype=np.float64)
    z = np.where(m, x / t, -np.inf)
    mx = float(np.max(z[m]))
    lse = mx + math.log(float(np.exp(z[m] - mx).sum()))
    out = z - lse
    out[~m] = -np.inf
    return out


def masked_probs_np(logits: Any, mask: Any, temperature: float = 1.0) -> np.ndarray:
    """合法动作上的 softmax（非法位严格为 0.0）。"""
    return np.exp(masked_log_softmax_np(logits, mask, temperature))


def action_logprob_np(logits: Any, mask: Any, action: int,
                      temperature: float = 1.0) -> float:
    """指定（必须合法的）动作在 masked softmax 下的 log 概率。"""
    m = np.asarray(mask, dtype=bool).reshape(-1)
    a = int(action)
    if not (0 <= a < m.size and bool(m[a])):
        raise ValueError(f"动作 {a} 不在合法掩码内，不能计算 logprob")
    return float(masked_log_softmax_np(logits, m, temperature)[a])


def masked_log_softmax_torch(logits: Any, mask: Any):
    """torch 版 masked log-softmax：非法位填充 ``MASKED_LOGIT``（exp 后严格 0）。"""
    torch = _torch()
    m = mask.to(dtype=torch.bool)
    z = logits.masked_fill(~m, float(MASKED_LOGIT))
    return torch.log_softmax(z, dim=-1)


def masked_probs_torch(logits: Any, mask: Any):
    """torch 版 masked softmax：非法动作概率严格为 0。"""
    return masked_log_softmax_torch(logits, mask).exp()


def value_from_rank_logits_np(rank_logits: Any) -> np.ndarray:
    """名次 logits -> ``E[u(rank)]`` ∈ [-1, 1]（32 位浮点，供 GAE/诊断）。"""
    z = np.asarray(rank_logits, dtype=np.float64)
    if z.ndim == 1:
        z = z.reshape(1, -1)
    z = z - np.max(z, axis=-1, keepdims=True)
    p = np.exp(z)
    p = p / np.maximum(p.sum(axis=-1, keepdims=True), 1e-300)
    return (p * RANK_UTILITY.astype(np.float64)).sum(axis=-1).astype(np.float32)


def value_from_rank_logits_torch(rank_logits: Any):
    """torch 版 ``E[u(rank)]``（对 rank logits 可微）。"""
    torch = _torch()
    u = torch.as_tensor(RANK_UTILITY, dtype=rank_logits.dtype, device=rank_logits.device)
    p = torch.softmax(rank_logits, dim=-1)
    return (p * u).sum(dim=-1)


# ══════════════════════════════════════════════════════════════════════════
# 2. GAE(λ) / reward-to-go / clip surrogate
# ══════════════════════════════════════════════════════════════════════════
def reward_to_go_np(rewards: Any, dones: Any, gamma: float = 1.0) -> np.ndarray:
    """按 episode（``done=1`` 为末步）反向累计折扣回报。"""
    r = np.asarray(rewards, dtype=np.float64).reshape(-1)
    d = np.asarray(dones, dtype=np.float64).reshape(-1)
    if r.shape != d.shape:
        raise ValueError(f"rewards/dones 形状不一致: {r.shape} vs {d.shape}")
    out = np.zeros(r.shape, dtype=np.float64)
    acc = 0.0
    for t in range(r.size - 1, -1, -1):
        if d[t] > 0.5:
            acc = 0.0
        acc = float(r[t]) + float(gamma) * acc
        out[t] = acc
    return out


def compute_gae(rewards: Any, values: Any, dones: Any, *,
                gamma: float = 1.0, lam: float = 0.95) -> Tuple[np.ndarray, np.ndarray]:
    """GAE(λ) 与 reward-to-go（returns = advantages + values）。

    要求序列按 episode 连续排列，``dones[t]=1`` 标记该 episode 的末步；末步不做
    bootstrap（价值目标 = 该步 reward）。
    """
    r = np.asarray(rewards, dtype=np.float64).reshape(-1)
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    d = np.asarray(dones, dtype=np.float64).reshape(-1)
    if not (r.shape == v.shape == d.shape):
        raise ValueError(f"rewards/values/dones 形状不一致: {r.shape}/{v.shape}/{d.shape}")
    n = int(r.size)
    adv = np.zeros(n, dtype=np.float64)
    last_adv = 0.0
    next_value = 0.0
    for t in range(n - 1, -1, -1):
        if d[t] > 0.5:
            next_value = 0.0
            last_adv = 0.0
        delta = float(r[t]) + float(gamma) * next_value - float(v[t])
        last_adv = delta + float(gamma) * float(lam) * last_adv
        adv[t] = last_adv
        next_value = float(v[t])
    returns = adv + v
    return adv.astype(np.float32), returns.astype(np.float32)


def clipped_surrogate(ratio: Any, advantages: Any, clip: float):
    """PPO clip 目标：``-mean(min(r*A, clip(r,1±ε)*A))`` 与裁剪比例。

    返回 ``(loss, clipped_fraction)``，两者都是 torch 张量（0 维）。
    """
    torch = _torch()
    eps = float(clip)
    if eps <= 0.0:
        raise ValueError(f"clip 必须 > 0，得到 {clip!r}")
    unclipped = ratio * advantages
    clipped = torch.clamp(ratio, 1.0 - eps, 1.0 + eps) * advantages
    loss = -torch.min(unclipped, clipped).mean()
    frac = ((ratio < 1.0 - eps) | (ratio > 1.0 + eps)).to(ratio.dtype).mean()
    return loss, frac


def normalize_advantages(advantages: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """优势标准化（整批/每个 minibatch 内），std 退化时返回零均值。"""
    a = np.asarray(advantages, dtype=np.float64).reshape(-1)
    if a.size == 0:
        return a.astype(np.float32)
    std = float(a.std())
    if std < float(eps):
        return (a - a.mean()).astype(np.float32)
    return ((a - a.mean()) / std).astype(np.float32)


# ══════════════════════════════════════════════════════════════════════════
# 3. 配置
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class CollectConfig:
    """MCTS 自对弈采集配置。"""

    games: int = 8
    seed: int = 0
    max_steps: int = 20000
    game_id_offset: int = 0
    #: self=8 座自对弈（selfplay.play_selfplay_game）；bot=1 学习座 vs 7 引擎 bot
    opponent: str = "self"
    learner_seat: int = 0
    #: net=网络采样（严格 on-policy）；mcts=visit π 采样；mixed=混合
    behavior: str = "net"
    temperature: float = 1.0       # 网络采样温度（logits / τ）
    pi_epsilon: float = 0.0        # mixed 行为分布中网络概率权重 ε
    step_penalty: float = 0.0      # 每决策小惩罚（进入 reward）
    #: 单座位单回合决策数上限（超过且 EndTurn 合法则强制结束回合；0=关闭）。
    #: 未训练网络容易陷入 Play/Cancel 循环，默认 40 保证采集/评测能走到终局。
    max_actions_per_turn: int = 40


@dataclass
class PPOConfig:
    """PPO 优化配置（固定 245 动作、masked softmax）。"""

    epochs: int = 2
    minibatch: int = 64
    lr: float = 3e-4
    clip: float = 0.2
    gamma: float = 1.0             # 8 座单局终局效用，通常不折扣
    lam: float = 0.95              # GAE λ
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    #: MCTS visit π 辅助交叉熵权重 alpha（0 = 关闭，退化为纯 PPO）
    pi_coef: float = 0.5
    #: rank=名次 CE；mse=value MSE（critic=E[u(rank)]）
    value_loss: str = "rank"
    #: entity 有标量 value 头时的辅助 MSE 权重（tiny 无此头，忽略）
    value_head_coef: float = 0.0
    target_kl: float = 0.02        # >0 且 kl_early_stop 时启用
    kl_early_stop: bool = True
    normalize_advantage: bool = True
    max_grad_norm: float = 0.5
    device: str = "cpu"
    seed: int = 0
    max_samples: Optional[int] = None
    log_every: int = 0

    def __post_init__(self) -> None:
        mode = str(self.value_loss).strip().lower()
        if mode not in ("rank", "mse"):
            raise ValueError(f"value_loss 只能是 rank|mse，得到 {self.value_loss!r}")
        self.value_loss = mode


# ══════════════════════════════════════════════════════════════════════════
# 4. 轨迹批次
# ══════════════════════════════════════════════════════════════════════════
#: 批次字段（保存/加载顺序）
BATCH_FIELDS: Tuple[str, ...] = (
    "features", "cards", "masks", "actions", "old_logprobs", "values", "rewards",
    "dones", "advantages", "returns", "seats", "game_ids", "ranks", "turns",
    "target_pi", "has_pi", "episode_ids",
)


@dataclass
class PPOBatch:
    """一条 PPO 轨迹批次（按 episode 分组、含 GAE）。

    数组形状（n = 样本数）::

        features f32[n,3227]  cards int16[n,124]  masks bool[n,245]
        actions int64[n]      old_logprobs f32[n] values f32[n]
        rewards f32[n]        dones f32[n]        advantages/returns f32[n]
        seats int32[n]        game_ids int64[n]   ranks int64[n]  turns int32[n]
        target_pi f32[n,245]  has_pi bool[n]      episode_ids int32[n]
    """

    features: np.ndarray
    cards: np.ndarray
    masks: np.ndarray
    actions: np.ndarray
    old_logprobs: np.ndarray
    values: np.ndarray
    rewards: np.ndarray
    dones: np.ndarray
    advantages: np.ndarray
    returns: np.ndarray
    seats: np.ndarray
    game_ids: np.ndarray
    ranks: np.ndarray
    turns: np.ndarray
    target_pi: np.ndarray
    has_pi: np.ndarray
    episode_ids: np.ndarray
    meta: Dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.actions.shape[0])

    # ── 校验 ──
    def validate(self) -> List[str]:
        """形状/合法性自检；返回问题列表（空 = 通过）。"""
        errs: List[str] = []
        n = len(self)
        expected = {
            "features": (n, OBS_FLOATS), "cards": (n, OBS_CARDS),
            "masks": (n, N_ACTIONS), "actions": (n,),
            "old_logprobs": (n,), "values": (n,), "rewards": (n,), "dones": (n,),
            "advantages": (n,), "returns": (n,), "seats": (n,), "game_ids": (n,),
            "ranks": (n,), "turns": (n,), "target_pi": (n, N_ACTIONS),
            "has_pi": (n,), "episode_ids": (n,),
        }
        for name, shape in expected.items():
            arr = getattr(self, name)
            if tuple(arr.shape) != shape:
                errs.append(f"{name}: shape {tuple(arr.shape)} != {shape}")
        if n == 0:
            return errs
        m = self.masks.astype(bool)
        a = self.actions.astype(np.int64)
        bad = (a < 0) | (a >= N_ACTIONS)
        if bad.any():
            errs.append(f"{int(bad.sum())} 个动作下标越界")
        else:
            legal = m[np.arange(n), a]
            if not bool(legal.all()):
                errs.append(f"{int((~legal).sum())} 个动作不在合法掩码内")
        if not np.isfinite(self.old_logprobs).all():
            errs.append("old_logprobs 含 NaN/Inf")
        if not np.isfinite(self.features).all():
            errs.append("features 含 NaN/Inf")
        if not np.isfinite(self.rewards).all() or not np.isfinite(self.values).all():
            errs.append("rewards/values 含 NaN/Inf")
        if not np.isin(self.dones.astype(np.int64), (0, 1)).all():
            errs.append("dones 必须为 0/1")
        ranks = self.ranks.astype(np.int64)
        if ((ranks < 1) | (ranks > N_RANKS)).any():
            errs.append("ranks 必须在 1..8（截断局应已丢弃）")
        pi = self.target_pi.astype(np.float64)
        hp = self.has_pi.astype(bool)
        if hp.any():
            s = pi[hp].sum(axis=1)
            if not np.allclose(s, 1.0, atol=5e-3):
                errs.append(f"target_pi 行和误差过大: {float(np.abs(s - 1.0).max()):.5f}")
            if bool((pi[hp] * (~m[hp])).sum() > 5e-3):
                errs.append("target_pi 在非法动作上有质量")
        # 每个 episode 恰好一个 done，且位于该 episode 末步
        for ep in np.unique(self.episode_ids):
            idx = np.flatnonzero(self.episode_ids == ep)
            if idx.size == 0:
                continue
            if int(self.dones[idx].sum()) != 1:
                errs.append(f"episode {int(ep)} 的 done 数 != 1")
            elif float(self.dones[idx[-1]]) < 0.5:
                errs.append(f"episode {int(ep)} 的 done 不在末步")
        return errs

    def summary(self) -> Dict[str, Any]:
        """批次质量摘要（进 JSON 报告，不含大数组）。"""
        n = len(self)
        if n == 0:
            return {"samples": 0}
        m = self.masks.astype(bool)
        a = self.actions.astype(np.int64)
        hp = self.has_pi.astype(bool)
        return {
            "samples": int(n),
            "games": int(np.unique(self.game_ids).size),
            "episodes": int(np.unique(self.episode_ids).size),
            "seats": sorted(int(s) for s in np.unique(self.seats)),
            "legal_action_rate": float(m[np.arange(n), a].mean()),
            "old_logprob_mean": float(self.old_logprobs.mean()),
            "value_mean": float(self.values.mean()),
            "reward_mean": float(self.rewards.mean()),
            "return_mean": float(self.returns.mean()),
            "advantage_mean": float(self.advantages.mean()),
            "advantage_std": float(self.advantages.std()),
            "rank_mean": float(self.ranks.mean()),
            "target_pi_rate": float(hp.mean()) if n else 0.0,
        }

    # ── 存储 ──
    def save(self, path: str) -> str:
        """保存为 npz（数组 + meta json）。"""
        path = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        payload = {f"arr_{k}": getattr(self, k) for k in BATCH_FIELDS}
        payload["meta_json"] = np.asarray(
            json.dumps(to_jsonable(self.meta), ensure_ascii=False))
        np.savez_compressed(path, **payload)
        return path

    @classmethod
    def load(cls, path: str) -> "PPOBatch":
        with np.load(str(path), allow_pickle=False) as z:
            missing = [k for k in BATCH_FIELDS if f"arr_{k}" not in z]
            if missing:
                raise ValueError(f"PPO 批次文件缺少字段: {missing}")
            arrays = {k: np.asarray(z[f"arr_{k}"]) for k in BATCH_FIELDS}
            meta = json.loads(str(z["meta_json"])) if "meta_json" in z else {}
        return cls(meta=meta, **arrays)


def _group_order(records: List[Dict[str, Any]]) -> List[int]:
    """按 (game_id, seat) 稳定排序的索引：同座位内保持决策时序。"""
    keys = [(int(r["game_id"]), int(r["seat"])) for r in records]
    return sorted(range(len(records)), key=lambda i: keys[i])


def build_batch_from_records(records: List[Dict[str, Any]], *,
                             gamma: float = 1.0, lam: float = 0.95,
                             step_penalty: float = 0.0,
                             meta: Optional[Dict[str, Any]] = None) -> PPOBatch:
    """把决策记录列表整理成 ``PPOBatch``（奖励/GAE 均已计算）。

    ``records`` 每条至少包含::

        features[3227], cards[124], mask[245], action, old_logprob, value,
        rank(1..8), seat, game_id, turn; 可选 target_pi[245]（MCTS visit π）。

    rank=0（截断/未知）的样本丢弃。奖励：每步 ``-step_penalty``，该座位 episode
    末步再加终局 ``u(rank)``；``done`` 只在该座位末步为 1。
    """
    if not isinstance(records, (list, tuple)):
        raise TypeError("records 必须是决策记录列表")
    recs = [r for r in records if 1 <= int(r.get("rank", 0) or 0) <= N_RANKS]
    dropped = len(records) - len(recs)
    if not recs:
        raise ValueError("没有可用样本（rank 全为 0 / 记录为空）；截断局请重跑")
    recs = [recs[i] for i in _group_order(recs)]
    n = len(recs)

    features = np.stack([np.asarray(r["features"], dtype=np.float32).reshape(-1)
                         for r in recs]).astype(np.float32)
    cards = np.stack([np.asarray(r["cards"], dtype=np.int16).reshape(-1)
                      for r in recs]).astype(np.int16)
    masks = np.stack([np.asarray(r["mask"], dtype=bool).reshape(-1)
                      for r in recs]).astype(bool)
    if features.shape[1] != OBS_FLOATS or cards.shape[1] != OBS_CARDS \
            or masks.shape[1] != N_ACTIONS:
        raise ValueError("features/cards/mask 形状不符合 3227/124/245 固定协议")
    actions = np.asarray([int(r["action"]) for r in recs], dtype=np.int64)
    old_logprobs = np.asarray([float(r["old_logprob"]) for r in recs], dtype=np.float32)
    values = np.asarray([float(r["value"]) for r in recs], dtype=np.float32)
    seats = np.asarray([int(r["seat"]) for r in recs], dtype=np.int32)
    game_ids = np.asarray([int(r["game_id"]) for r in recs], dtype=np.int64)
    ranks = np.asarray([int(r["rank"]) for r in recs], dtype=np.int64)
    turns = np.asarray([int(r.get("turn", -1)) for r in recs], dtype=np.int32)

    target_pi = np.zeros((n, N_ACTIONS), dtype=np.float32)
    has_pi = np.zeros(n, dtype=bool)
    for i, r in enumerate(recs):
        pi = r.get("target_pi")
        if pi is None:
            continue
        pi_arr = np.asarray(pi, dtype=np.float32).reshape(-1)
        if pi_arr.size != N_ACTIONS:
            continue
        pi_arr = masked_normalize(pi_arr, masks[i])
        s = float(pi_arr.sum())
        if s > 1e-8:
            target_pi[i] = pi_arr / s
            has_pi[i] = True

    # 按 episode（game_id, seat 已连续）写 reward/done
    rewards = np.full(n, -float(step_penalty), dtype=np.float32)
    dones = np.zeros(n, dtype=np.float32)
    episode_ids = np.zeros(n, dtype=np.int32)
    start = 0
    ep = 0
    while start < n:
        key = (int(game_ids[start]), int(seats[start]))
        end = start + 1
        while end < n and (int(game_ids[end]), int(seats[end])) == key:
            end += 1
        episode_ids[start:end] = ep
        last = end - 1
        rewards[last] = float(utility_from_rank([int(ranks[last])])[0]) - float(step_penalty)
        dones[last] = 1.0
        ep += 1
        start = end

    advantages, returns = compute_gae(rewards, values, dones, gamma=gamma, lam=lam)
    merged_meta: Dict[str, Any] = dict(meta or {})
    merged_meta.update({
        "gamma": float(gamma), "lam": float(lam), "step_penalty": float(step_penalty),
        "dropped_unknown_rank": int(dropped), "episodes": int(ep),
    })
    return PPOBatch(
        features=features, cards=cards, masks=masks, actions=actions,
        old_logprobs=old_logprobs, values=values, rewards=rewards, dones=dones,
        advantages=advantages, returns=returns, seats=seats, game_ids=game_ids,
        ranks=ranks, turns=turns, target_pi=target_pi, has_pi=has_pi,
        episode_ids=episode_ids, meta=merged_meta)


# ══════════════════════════════════════════════════════════════════════════
# 5. 网络前向统一接口（tiny: (f,c)；entity: (f,c,mask)）
# ══════════════════════════════════════════════════════════════════════════
def _accepts_mask(model: Any) -> bool:
    import inspect

    forward = getattr(model, "forward", None)
    if forward is None:
        return False
    try:
        return "mask" in inspect.signature(forward).parameters
    except (TypeError, ValueError):  # pragma: no cover - 内建 forward
        return False


def split_model_outputs(out: Any) -> Tuple[Any, Any, Optional[Any]]:
    """``(logits, rank_logits, scalar_value|None)``（tiny 只有前两个）。"""
    if not isinstance(out, (tuple, list)):
        raise ValueError("模型 forward 必须返回 (logits, rank_logits[, value]) 元组")
    logits, rank_logits = out[0], out[1]
    value = out[2] if len(out) > 2 else None
    return logits, rank_logits, value


def forward_model(model: Any, features: Any, cards: Any, mask: Any = None):
    """统一调用 tiny / entity：entity 会额外吃 mask，tiny 忽略。"""
    if _accepts_mask(model):
        return model(features, cards, mask)
    return model(features, cards)


def policy_values(model: Any, features: Any, cards: Any, mask: Any):
    """带掩码前向 -> ``(masked_probs, rank_logits, critic_value)``（torch 张量）。"""
    logits, rank_logits, _scalar = split_model_outputs(
        forward_model(model, features, cards, mask))
    return masked_probs_torch(logits, mask), rank_logits


class PPOEvaluator:
    """把 PPO 策略/价值网络包装成 MCTS 叶评估器：

    ``__call__(features, cards, mask, seat) -> (prior[245], value)``。
    prior 用 **masked softmax**（不是 logits 归一），非法动作为 0；value 取
    ``E[u(rank)]``。与 ``hsbg.az.train.model.NetEvaluator`` 的接口一致，可直接喂给
    ``hsbg.az.search``。
    """

    name = "ppo_net"
    accepts_game = False

    def __init__(self, model: Any, device: str = "cpu", temperature: float = 1.0,
                 norm_mean: Optional[np.ndarray] = None,
                 norm_std: Optional[np.ndarray] = None) -> None:
        self.torch = _torch()
        self.model = model
        self.device = self.torch.device(device)
        self.temperature = float(temperature)
        self.mean = None if norm_mean is None else np.asarray(norm_mean, dtype=np.float32)
        self.std = None if norm_std is None else np.asarray(norm_std, dtype=np.float32)
        self.model.to(self.device)
        self.model.eval()

    def _normalize(self, features: np.ndarray) -> np.ndarray:
        x = np.asarray(features, dtype=np.float32)
        if self.mean is not None:
            x = x - self.mean
        if self.std is not None:
            x = x / self.std
        return x

    def logits(self, features: np.ndarray, cards: Any = None,
               mask: Any = None) -> Tuple[np.ndarray, np.ndarray]:
        """批量前向 -> ``(policy_logits, rank_logits)``。"""
        torch = self.torch
        x = self._normalize(np.atleast_2d(features))
        c = np.zeros((x.shape[0], OBS_CARDS), dtype=np.int64) if cards is None \
            else np.atleast_2d(np.asarray(cards, dtype=np.int64))
        m = None if mask is None else torch.from_numpy(
            np.ascontiguousarray(np.atleast_2d(np.asarray(mask, dtype=bool)))).to(self.device)
        with torch.no_grad():
            xt = torch.from_numpy(np.ascontiguousarray(x)).to(self.device)
            ct = torch.from_numpy(np.ascontiguousarray(c)).to(self.device)
            out = forward_model(self.model, xt, ct, m)
            plog, rlog, _ = split_model_outputs(out)
        return plog.detach().cpu().numpy(), rlog.detach().cpu().numpy()

    def __call__(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                 seat: int = 0) -> Tuple[np.ndarray, float]:
        plog, rlog = self.logits(np.asarray(features, np.float32),
                                 np.asarray(cards, np.int64),
                                 np.asarray(mask, bool))
        prior = masked_probs_np(plog[0], np.asarray(mask, bool), self.temperature)
        prior = prior / max(float(prior.sum()), 1e-12)
        value = float(value_from_rank_logits_np(rlog[0])[0])
        return prior.astype(np.float32), value


class PPOGreedyPolicy(Policy):
    """固定 seed 评测用的网络 argmax 策略（带单回合决策数守卫）。

    - 决策只用 ``observe(seat)`` + ``legal_mask``（通过 evaluator）；
    - ``max_actions_per_turn>0`` 时，同一座位/回合动作数超限且 ``EndTurn`` 合法则
      强制结束回合，避免未训练网络陷入 Play/Cancel 死循环导致对局 truncated；
      该守卫只影响病态循环，正常对局不会触发（报告里记录触发次数）。
    """

    name = "ppo_net"
    supports_pi = False

    def __init__(self, evaluator: Any, *, max_actions_per_turn: int = 40) -> None:
        self.evaluator = evaluator
        self.max_actions_per_turn = int(max_actions_per_turn)
        self._turn_counts: Dict[tuple, int] = {}
        self.forced_actions = 0

    def reset(self) -> None:
        self._turn_counts = {}

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        f, c = obs_arrays(game.observe(seat))
        mask = mask_from_bytes(game.legal_mask(seat))
        prior, value = self.evaluator(f, c, mask, seat)
        pi = masked_normalize(prior, mask)
        turn = int(getattr(game, "turn", -1))
        key = (seat, turn)
        n_turn = self._turn_counts.get(key, 0) + 1
        self._turn_counts[key] = n_turn
        forced = bool(self.max_actions_per_turn > 0 and n_turn > self.max_actions_per_turn
                      and bool(mask[0]))
        if forced:
            self.forced_actions += 1
            action = 0
        elif float(pi.sum()) > 0.0:
            action = int(np.argmax(pi))
        else:
            legal = np.flatnonzero(mask)
            action = int(legal[0]) if legal.size else 0
        return Decision(int(action), pi, {"search": False, "policy": self.name,
                                          "value": float(value), "forced": forced})


# ══════════════════════════════════════════════════════════════════════════
# 6. PPO loss / 训练
# ══════════════════════════════════════════════════════════════════════════
def ppo_losses(model: Any, batch: PPOBatch, config: PPOConfig,
               indices: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """计算一个 minibatch 的 PPO 损失（返回 torch 张量字典）。

    - policy: ``-min(r*A, clip(r,1±ε)*A).mean()``；
    - value: ``rank``（名次 CE）或 ``mse``（``E[u(rank)]`` vs returns）；
    - aux: ``pi_coef * CE(π_MCTS, π_θ)``（仅 ``has_pi`` 样本）；
    - entropy: masked 策略熵（鼓励探索）；
    - 非法动作：logits 在 loss 内重新 masked，概率严格 0（``illegal_prob_max`` 可验证）。
    """
    torch = _torch()
    F = torch.nn.functional
    if indices is None:
        indices = np.arange(len(batch), dtype=np.int64)
    idx = np.asarray(indices, dtype=np.int64).reshape(-1)
    if idx.size == 0:
        raise ValueError("PPO minibatch 为空")
    dev = torch.device(config.device)
    x = torch.from_numpy(np.ascontiguousarray(batch.features[idx])).to(dev)
    c = torch.from_numpy(np.ascontiguousarray(batch.cards[idx].astype(np.int64))).to(dev)
    m = torch.from_numpy(np.ascontiguousarray(batch.masks[idx].astype(bool))).to(dev)
    actions = torch.from_numpy(np.ascontiguousarray(batch.actions[idx].astype(np.int64))).to(dev)
    old_logp = torch.from_numpy(
        np.ascontiguousarray(batch.old_logprobs[idx].astype(np.float32))).to(dev)
    returns_t = torch.from_numpy(
        np.ascontiguousarray(batch.returns[idx].astype(np.float32))).to(dev)
    adv = torch.from_numpy(
        np.ascontiguousarray(batch.advantages[idx].astype(np.float32))).to(dev)
    ranks = torch.from_numpy(np.ascontiguousarray(batch.ranks[idx].astype(np.int64))).to(dev)
    target_pi = torch.from_numpy(
        np.ascontiguousarray(batch.target_pi[idx].astype(np.float32))).to(dev)
    has_pi = torch.from_numpy(
        np.ascontiguousarray(batch.has_pi[idx].astype(bool))).to(dev)
    if config.normalize_advantage:
        std = adv.std(unbiased=False)
        adv = (adv - adv.mean()) / std.clamp_min(1e-8)

    out = forward_model(model, x, c, m)
    logits, rank_logits, scalar_value = split_model_outputs(out)
    logp = masked_log_softmax_torch(logits, m)
    action_logp = logp.gather(1, actions.unsqueeze(1)).squeeze(1)
    ratio = torch.exp(action_logp - old_logp)
    policy_loss, clip_frac = clipped_surrogate(ratio, adv, config.clip)

    probs = logp.exp()
    safe_logp = torch.where(m, logp, torch.zeros_like(logp))
    entropy = -(probs * safe_logp).sum(dim=-1).mean()

    value_pred = value_from_rank_logits_torch(rank_logits)
    if config.value_loss == "rank":
        value_loss = F.cross_entropy(rank_logits, (ranks - 1).clamp(0, N_RANKS - 1))
    else:
        value_loss = F.mse_loss(value_pred, returns_t)
    if scalar_value is not None and float(config.value_head_coef) > 0.0:
        value_loss = value_loss + float(config.value_head_coef) * F.mse_loss(
            scalar_value, returns_t)

    if bool(has_pi.any()) and float(config.pi_coef) > 0.0:
        aux_all = -(target_pi * safe_logp).sum(dim=-1)
        aux_pi_loss = aux_all[has_pi].mean()
    else:
        aux_pi_loss = torch.zeros((), device=dev)

    total = (policy_loss + float(config.value_coef) * value_loss
             + float(config.pi_coef) * aux_pi_loss
             - float(config.entropy_coef) * entropy)
    approx_kl = (old_logp - action_logp).mean()
    illegal_prob_max = (probs * (~m).to(probs.dtype)).max()
    return {
        "total": total,
        "policy_loss": policy_loss,
        "value_loss": value_loss,
        "aux_pi_loss": aux_pi_loss,
        "entropy": entropy,
        "approx_kl": approx_kl,
        "clip_frac": clip_frac,
        "ratio_mean": ratio.mean(),
        "illegal_prob_max": illegal_prob_max,
        "adv_mean": adv.mean(),
        "value_pred_mean": value_pred.mean(),
    }


def train_ppo(model: Any, batch: PPOBatch, config: Optional[PPOConfig] = None,
              *, on_step: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """执行 PPO 更新（minibatch × epochs，clip、entropy、KL 早停）。

    返回可 JSON 序列化的统计字典。
    """
    cfg = config or PPOConfig()
    torch = _torch()
    errs = batch.validate()
    if errs:
        raise ValueError("PPO 批次校验失败: " + "; ".join(errs))
    rng = np.random.default_rng(int(cfg.seed))
    base_idx = np.arange(len(batch), dtype=np.int64)
    if cfg.max_samples is not None and int(cfg.max_samples) < base_idx.size:
        base_idx = np.sort(rng.choice(base_idx, size=int(cfg.max_samples), replace=False))
    n = int(base_idx.size)
    if n == 0:
        raise ValueError("PPO 训练样本为空")
    device = torch.device(cfg.device)
    model.to(device)
    # 保持 eval（关闭 dropout）：old_logprob 是采集时 eval 前向算出的，若 PPO 前向
    # 打开 dropout 会让 ratio 起点偏离 1、approx_kl 虚高（entity 默认 dropout=0.1）。
    model.eval()
    opt = torch.optim.Adam(model.parameters(), lr=float(cfg.lr))
    mb = max(1, int(cfg.minibatch))
    epochs = max(1, int(cfg.epochs))
    logs: List[Dict[str, Any]] = []
    updates = 0
    stopped_early = False
    t0 = time.time()
    for epoch in range(epochs):
        order = rng.permutation(n)
        acc: Dict[str, List[float]] = {}
        nb = 0
        epoch_stopped = False
        for start in range(0, n, mb):
            sel = base_idx[order[start:start + mb]]
            opt.zero_grad(set_to_none=True)
            out = ppo_losses(model, batch, cfg, indices=sel)
            out["total"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(cfg.max_grad_norm))
            opt.step()
            updates += 1
            nb += 1
            step_metrics = {k: float(v.detach().cpu()) for k, v in out.items()}
            for k, v in step_metrics.items():
                acc.setdefault(k, []).append(v)
            if on_step is not None:
                on_step({"step": updates, "epoch": epoch + 1, **step_metrics})
            if int(cfg.log_every) > 0 and updates % int(cfg.log_every) == 0:
                print(f"[ppo] step {updates} total={step_metrics['total']:.4f} "
                      f"policy={step_metrics['policy_loss']:.4f} "
                      f"value={step_metrics['value_loss']:.4f} "
                      f"kl={step_metrics['approx_kl']:.5f}", flush=True)
            # 标准 PPO：逐 minibatch 监控近似 KL，超过 1.5*target 立即停止本 epoch
            if cfg.kl_early_stop and float(cfg.target_kl) > 0.0 and \
                    step_metrics["approx_kl"] > 1.5 * float(cfg.target_kl):
                stopped_early = True
                epoch_stopped = True
                break
        rec: Dict[str, Any] = {"epoch": epoch + 1, "steps": nb}
        rec.update({k: float(np.mean(v)) for k, v in acc.items()})
        rec["elapsed_s"] = time.time() - t0
        rec["kl_early_stopped"] = bool(epoch_stopped)
        logs.append(rec)
        print(f"[ppo] epoch {epoch + 1}/{epochs} total={rec['total']:.4f} "
              f"(policy={rec['policy_loss']:.4f} value={rec['value_loss']:.4f} "
              f"aux_pi={rec['aux_pi_loss']:.4f} ent={rec['entropy']:.4f} "
              f"kl={rec['approx_kl']:.5f} clip={rec['clip_frac']:.3f})", flush=True)
        if epoch_stopped:
            print(f"[ppo] KL 早停：minibatch approx_kl 超过 "
                  f"1.5*target_kl={1.5 * float(cfg.target_kl):.5f}", flush=True)
            break
    model.eval()
    elapsed = time.time() - t0
    return {
        "epochs": logs,
        "updates": int(updates),
        "samples": n,
        "seconds": float(elapsed),
        "samples_per_s": float(n * len(logs) / max(elapsed, 1e-9)),
        "stopped_early": bool(stopped_early),
        "target_kl": float(cfg.target_kl),
        "kl_early_stop": bool(cfg.kl_early_stop),
        "value_loss_mode": cfg.value_loss,
        "pi_coef": float(cfg.pi_coef),
        "config": to_jsonable(asdict(cfg)),
    }


# ══════════════════════════════════════════════════════════════════════════
# 7. MCTS 自对弈采集
# ══════════════════════════════════════════════════════════════════════════
def _normalize_pi(result: Any, mask: np.ndarray) -> Optional[np.ndarray]:
    """从 SearchResult/dict/tuple 中取 π，按 mask 归一；取不到返回 None。"""
    raw = None
    if isinstance(result, dict):
        raw = result.get("pi")
    elif hasattr(result, "pi"):
        raw = getattr(result, "pi")
    elif isinstance(result, (tuple, list)) and len(result) >= 2:
        raw = result[0]
    if raw is None:
        return None
    arr = np.asarray(raw, dtype=np.float32).reshape(-1)
    if arr.size != N_ACTIONS:
        return None
    return masked_normalize(arr, np.asarray(mask, dtype=bool))


class PPOSelfPlayPolicy(Policy):
    """PPO 采集策略：网络（+ 可选 MCTS）选动作，并记录训练所需的全部字段。

    - 行为分布按 ``CollectConfig.behavior`` 选择（net / mcts / mixed），
      ``old_logprob`` 是**实际采样分布**在该动作上的 log 概率；
    - 开了 ``search_fn`` 时，每次决策额外跑一次不完全信息 MCTS，把 visit π 记进
      ``target_pi``（供 PPO 的辅助 CE 目标使用）；
    - ``supports_pi=True``：供 ``selfplay.play_selfplay_game`` 标记 source=1。
    """

    name = "ppo_selfplay"
    supports_pi = True

    def __init__(self, model: Any, *, device: str = "cpu",
                 config: Optional[CollectConfig] = None,
                 search_fn: Optional[Callable[..., Any]] = None,
                 search_config: Any = None,
                 eval_fn: Optional[Callable[..., Any]] = None,
                 engine_backend: str = "auto", seed: int = 0,
                 norm_mean: Optional[np.ndarray] = None,
                 norm_std: Optional[np.ndarray] = None) -> None:
        self.torch = _torch()
        self.model = model
        self.device = self.torch.device(device)
        self.config = config or CollectConfig()
        # 续训 CE checkpoint 时沿用其输入标准化统计（新训练模型为 None = 原始特征）
        self.norm_mean = None if norm_mean is None else np.asarray(norm_mean, np.float32)
        self.norm_std = None if norm_std is None else np.asarray(norm_std, np.float32)
        self.search_fn = search_fn
        self.search_config = search_config
        self.eval_fn = eval_fn
        self.engine_backend = str(engine_backend)
        self.game_id = 0
        self.records: List[Dict[str, Any]] = []
        self._rng = np.random.default_rng(int(seed))
        self._n = 0
        self._turn_counts: Dict[tuple, int] = {}
        self.forced_actions = 0
        self.search_calls = 0
        self.search_failures = 0
        self.model.to(self.device)
        self.model.eval()

    def reset(self) -> None:
        # 一局开始：清空本局记录/回合计数（search/forced 计数保留，用于整次采集 meta）
        self.records = []
        self._n = 0
        self._turn_counts = {}

    # ── 网络前向（单条决策）──
    def _net_predict(self, features: np.ndarray, cards: np.ndarray,
                     mask: np.ndarray) -> Tuple[np.ndarray, float]:
        torch = self.torch
        x_arr = np.asarray(features, np.float32).reshape(-1)
        if self.norm_mean is not None:
            x_arr = x_arr - self.norm_mean
        if self.norm_std is not None:
            x_arr = x_arr / self.norm_std
        x = torch.from_numpy(np.ascontiguousarray(x_arr.reshape(1, -1))).to(self.device)
        c = torch.from_numpy(np.ascontiguousarray(
            np.asarray(cards, np.int64).reshape(1, -1))).to(self.device)
        m = torch.from_numpy(np.ascontiguousarray(
            np.asarray(mask, bool).reshape(1, -1))).to(self.device)
        with torch.no_grad():
            logits, rank_logits, _scalar = split_model_outputs(
                forward_model(self.model, x, c, m))
            value = value_from_rank_logits_torch(rank_logits)
        return logits[0].detach().cpu().numpy().astype(np.float32), float(value[0])

    def _run_search(self, game: Any, seat: int,
                    mask: np.ndarray) -> Optional[np.ndarray]:
        if self.search_fn is None:
            return None
        try:
            base_seed = int(getattr(self.search_config, "seed", 0) or 0)
        except Exception:  # noqa: BLE001
            base_seed = 0
        try:
            self.search_calls += 1
            res = self.search_fn(
                game, int(seat), config=self.search_config, eval_fn=self.eval_fn,
                engine_backend=self.engine_backend, seed=base_seed + self._n)
            return _normalize_pi(res, mask)
        except Exception:  # noqa: BLE001 - 搜索失败回退到网络行为，不中断自对弈
            self.search_failures += 1
            return None
        finally:
            self._n += 1

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        f, c = obs_arrays(game.observe(seat))
        mask = mask_from_bytes(game.legal_mask(seat))
        logits, value = self._net_predict(f, c, mask)
        p_net = masked_probs_np(logits, mask, float(self.config.temperature))
        target_pi = self._run_search(game, seat, mask)

        behavior = str(self.config.behavior).strip().lower()
        if behavior == "net" or target_pi is None:
            mu = p_net
        elif behavior == "mcts":
            mu = target_pi
        else:  # mixed: (1-eps)*π_MCTS + eps*π_net
            eps = float(np.clip(self.config.pi_epsilon, 0.0, 1.0))
            mu = masked_normalize((1.0 - eps) * target_pi + eps * p_net, mask)

        # 单回合决策数守卫：未训练网络可能陷入 Play/Cancel 循环；强制 EndTurn
        turn = int(getattr(game, "turn", -1))
        limit = int(getattr(self.config, "max_actions_per_turn", 0) or 0)
        key = (seat, turn)
        n_turn = self._turn_counts.get(key, 0) + 1
        self._turn_counts[key] = n_turn
        forced = bool(limit > 0 and n_turn > limit and bool(mask[0]))

        legal = np.flatnonzero(mask)
        if legal.size == 0:
            action = 0
            logprob = 0.0
        elif forced:
            # 守卫动作：按**行为分布下 EndTurn 的概率**记录 old_logprob（而不是 0）。
            # 否则确定性守卫会被当成 off-policy 样本，把 approx_kl 拉爆、污染 PPO 梯度；
            # 这里把守卫视为"环境约束下从行为分布强制选取 EndTurn"的工程近似。
            action = 0
            mu_forced = np.asarray(mu, dtype=np.float64).reshape(-1)
            logprob = float(math.log(max(float(mu_forced[action]), LOGPROB_FLOOR)))
            self.forced_actions += 1
        else:
            mu64 = np.maximum(np.asarray(mu, dtype=np.float64), 0.0)
            s = float(mu64.sum())
            mu64 = (mu64 / s) if s > 0 else (mask.astype(np.float64) / float(legal.size))
            action = int(self._rng.choice(N_ACTIONS, p=mu64))
            if not bool(mask[action]):  # 数值兜底：只在合法动作上取 max
                action = int(legal[int(np.argmax(mu64[legal]))])
            logprob = float(math.log(max(float(mu64[action]), LOGPROB_FLOOR)))

        self.records.append({
            "features": (f.astype(np.float32, copy=True)
                         if self.norm_mean is None else np.asarray(
                             (f - self.norm_mean) / (self.norm_std
                                                     if self.norm_std is not None else 1.0),
                             dtype=np.float32)),
            "cards": c.astype(np.int32, copy=True),
            "mask": mask.astype(bool, copy=True),
            "action": int(action),
            "old_logprob": float(logprob),
            "value": float(value),
            "target_pi": None if target_pi is None else target_pi.astype(np.float32),
            "seat": int(seat),
            "turn": int(turn),
            "game_id": int(self.game_id),
            "forced": bool(forced),
        })
        out_pi = target_pi if target_pi is not None else mu
        return Decision(int(action), np.asarray(out_pi, dtype=np.float32),
                        {"search": target_pi is not None, "policy": self.name,
                         "logprob": float(logprob), "value": float(value),
                         "forced": bool(forced)})


def _attach_rank(records: List[Dict[str, Any]], rank: int) -> None:
    """把终局名次回填到该座位本局所有决策记录。"""
    util = float(utility_from_rank([int(rank)])[0])
    for rec in records:
        rec["rank"] = int(rank)
        rec["utility"] = util


def collect_ppo_batch(model: Any, config: Optional[CollectConfig] = None, *,
                      search_fn: Optional[Callable[..., Any]] = None,
                      search_config: Any = None,
                      eval_fn: Optional[Callable[..., Any]] = None,
                      engine_backend: str = "auto", device: str = "cpu",
                      seed: int = 0, gamma: float = 1.0, lam: float = 0.95,
                      step_penalty: float = 0.0,
                      norm_mean: Optional[np.ndarray] = None,
                      norm_std: Optional[np.ndarray] = None,
                      progress: bool = False) -> Tuple[PPOBatch, Dict[str, Any]]:
    """MCTS 自对弈采集一条 PPO 轨迹批次。

    ``config.opponent="self"``：8 座自对弈（复用 ``selfplay.play_selfplay_game``）；
    ``config.opponent="bot"``：1 个学习座 vs 7 个引擎 bot。截断局整局丢弃。
    ``norm_mean/norm_std``：续训 CE checkpoint 时的输入标准化统计（None=原始特征；
    归一后的特征会直接写进 batch，PPO 更新与采集口径一致）。
    """
    cfg = config or CollectConfig()
    mode = str(cfg.opponent).strip().lower()
    if mode not in ("self", "bot"):
        raise ValueError(f"opponent 只能是 self|bot，得到 {cfg.opponent!r}")
    policy = PPOSelfPlayPolicy(
        model, device=device, config=cfg, search_fn=search_fn,
        search_config=search_config, eval_fn=eval_fn,
        engine_backend=engine_backend, seed=int(seed),
        norm_mean=norm_mean, norm_std=norm_std)
    records: List[Dict[str, Any]] = []
    games_meta: List[Dict[str, Any]] = []
    illegal = 0
    decisions = 0
    truncated = 0
    t0 = time.time()

    if mode == "self":
        from .selfplay import play_selfplay_game  # 惰性：无引擎机器也可 import 本模块

        for gi in range(int(cfg.games)):
            gid = int(cfg.game_id_offset) + gi
            policy.game_id = gid
            _samples, meta = play_selfplay_game(
                policy, seed=int(cfg.seed) + gi, game_id=gid,
                sample_stride=1, max_steps=int(cfg.max_steps))
            decisions += int(meta["decisions"])
            illegal += int(meta["illegal_actions"])
            if bool(meta["truncated"]):
                truncated += 1
            else:
                placements = list(meta["placements"])
                for seat in range(len(placements)):
                    seat_recs = [r for r in policy.records if int(r["seat"]) == seat]
                    if seat_recs:
                        _attach_rank(seat_recs, int(placements[seat]))
                records.extend(policy.records)
            meta = dict(meta)
            meta["collected_records"] = int(len(policy.records))
            games_meta.append(meta)
            if progress:
                print(f"[collect] game {gi + 1}/{cfg.games} decisions={meta['decisions']} "
                      f"truncated={meta['truncated']} records={len(policy.records)}",
                      flush=True)
    else:
        E = load_engine()
        for gi in range(int(cfg.games)):
            gid = int(cfg.game_id_offset) + gi
            policy.game_id = gid
            policy.reset()
            game = E.Game(seed=int(cfg.seed) + gi)
            steps = 0
            game_decisions = 0
            game_truncated = False
            while not game.is_over() and steps < int(cfg.max_steps):
                acted = False
                for p in range(N_PLAYERS):
                    if not game.needs_action(p):
                        continue
                    if int(p) == int(cfg.learner_seat):
                        dec = policy.decide(game, int(p))
                        mask = mask_from_bytes(game.legal_mask(int(p)))
                        action = int(dec.action)
                        if not (0 <= action < N_ACTIONS and bool(mask[action])):
                            illegal += 1
                            action = int(np.flatnonzero(mask)[0]) if mask.any() else 0
                        game.step(int(p), action)
                        game_decisions += 1
                    else:
                        game.bot_play(int(p))
                    steps += 1
                    acted = True
                    if game.is_over():
                        break
                if not acted:
                    break
            over = bool(game.is_over())
            if over:
                rank = int(list(game.placements())[int(cfg.learner_seat)])
                _attach_rank(policy.records, rank)
                records.extend(policy.records)
            else:
                truncated += 1
                game_truncated = True
            decisions += game_decisions
            games_meta.append({
                "game_id": gid, "seed": int(cfg.seed) + gi, "steps": int(steps),
                "decisions": int(game_decisions), "truncated": int(game_truncated),
                "records": int(len(policy.records)),
                "rank": (None if game_truncated
                         else int(list(game.placements())[int(cfg.learner_seat)])),
            })
            if progress:
                print(f"[collect] vs-bot game {gi + 1}/{cfg.games} "
                      f"decisions={game_decisions} truncated={game_truncated}",
                      flush=True)

    collect_meta: Dict[str, Any] = {
        "mode": "vs_bot" if mode == "bot" else "selfplay",
        "requested_games": int(cfg.games),
        "games": int(len(games_meta) - truncated),
        "truncated_games": int(truncated),
        "decisions": int(decisions),
        "illegal_actions": int(illegal),
        "seed": int(cfg.seed),
        "learner_seat": int(cfg.learner_seat),
        "behavior": str(cfg.behavior),
        "temperature": float(cfg.temperature),
        "pi_epsilon": float(cfg.pi_epsilon),
        "search_calls": int(policy.search_calls),
        "search_failures": int(policy.search_failures),
        "forced_end_turns": int(policy.forced_actions),
        "max_actions_per_turn": int(cfg.max_actions_per_turn),
        "search_enabled": bool(search_fn is not None),
        "features_normalized": bool(norm_mean is not None),
        "elapsed_s": float(time.time() - t0),
        "samples_per_game": float(len(records) / max(len(games_meta) - truncated, 1)),
        "games_meta": to_jsonable(games_meta),
    }
    if not records:
        raise RuntimeError(
            f"采集失败：{truncated}/{len(games_meta)} 局在 max_steps={int(cfg.max_steps)} "
            "内未结束（rank=0），没有可用轨迹。请增大 --max-steps、调整 --seed，或从已有 "
            "checkpoint 续训（随机网络可能陷入 Play/Cancel 循环）。")
    batch = build_batch_from_records(records, gamma=gamma, lam=lam,
                                     step_penalty=step_penalty, meta=collect_meta)
    batch.meta.update({
        "collect_seconds": float(time.time() - t0),
        "collect": {k: v for k, v in collect_meta.items() if k != "games_meta"},
    })
    return batch, batch.meta


__all__ = [
    "MASKED_LOGIT",
    "LOGPROB_FLOOR",
    "torch_available",
    "masked_log_softmax_np",
    "masked_probs_np",
    "action_logprob_np",
    "masked_log_softmax_torch",
    "masked_probs_torch",
    "value_from_rank_logits_np",
    "value_from_rank_logits_torch",
    "reward_to_go_np",
    "compute_gae",
    "clipped_surrogate",
    "normalize_advantages",
    "CollectConfig",
    "PPOConfig",
    "PPOBatch",
    "BATCH_FIELDS",
    "build_batch_from_records",
    "forward_model",
    "split_model_outputs",
    "PPOEvaluator",
    "PPOGreedyPolicy",
    "ppo_losses",
    "train_ppo",
    "PPOSelfPlayPolicy",
    "collect_ppo_batch",
]
