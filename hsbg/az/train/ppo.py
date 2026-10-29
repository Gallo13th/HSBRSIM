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

import contextlib
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
from .seq_aux import (
    SEQ_TARGET_KEY,
    parse_coef_ramp,
    seq_bce_loss,
    seq_targets_from_records,
)

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


def clipped_surrogate(ratio: Any, advantages: Any, clip: float,
                      weight: Any = None):
    """PPO clip 目标：``-mean(min(r*A, clip(r,1±ε)*A))`` 与裁剪比例。

    ``weight`` 可选（0/1 或实数）：用于把确定性守卫样本（forced EndTurn）
    从策略梯度中排除，同时保留 value/critic 链。返回 ``(loss, clipped_fraction)``。
    """
    torch = _torch()
    eps = float(clip)
    if eps <= 0.0:
        raise ValueError(f"clip 必须 > 0，得到 {clip!r}")
    unclipped = ratio * advantages
    clipped = torch.clamp(ratio, 1.0 - eps, 1.0 + eps) * advantages
    per = -torch.min(unclipped, clipped)
    frac_per = ((ratio < 1.0 - eps) | (ratio > 1.0 + eps)).to(ratio.dtype)
    if weight is None:
        return per.mean(), frac_per.mean()
    w = weight.to(per.dtype).clamp_min(0.0)
    denom = w.sum().clamp_min(1e-8)
    return (per * w).sum() / denom, (frac_per * w).sum() / denom


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
    #: self=8 座自对弈；bot=1 学习座 vs 7 引擎 bot；
    #: weak=1 学习座 vs 7 个弱随机/结束回合混合对手（冷启动课程）
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
    #: worker 侧采样（L2）：sims=0 + behavior=net 时跳过 245 维 prior 回传。
    fast_act: bool = True
    #: lock-step 批量 actor：每 worker 内 N 局同步推进（每轮一次批量前向）。
    lockstep: bool = False
    #: Rust 全采集器（BatchEnv 驱动，引擎/观测/记录全在 Rust）。
    rust_collector: bool = False
    #: Rust 采集器内部引擎并行线程数（BatchEnv threads）。
    rc_threads: int = 8
    #: 采集/评测时叶前向精度：off=fp32；bf16=CUDA autocast（实测 collect 约 -5%）。
    leaf_amp: str = "off"
    #: 采集/评测叶前向用 torch.compile（实测 B=64 forward 5.4→0.7 ms）。
    leaf_compile: bool = False
    #: 镜像对手库：JSONL 路径（空=不用）与每回合每 bot 座位的注入概率。
    library_pool: str = ""
    library_p: float = 0.0
    #: 对手场面轨迹镜像库（目录）；trajectory_p=每局被轨迹替换的概率
    trajectory_pool: str = ""
    trajectory_p: float = 0.0
    #: 回合末场面快照镜像库（目录）、镜像座位数（给 seat 1..N 注入）与每座位每回合注入概率。
    #: 默认关闭（mirror_p=0）：走引擎 `Game.apply_turn_snapshots`，见
    #: docs/MIRROR_SNAPSHOT_DESIGN.md 与 hsbg/az/train/mirror_snapshots.py。
    mirror_snaps: str = ""
    mirror_seats: int = 0
    mirror_p: float = 0.0
    #: 桶内采样模式：p50/p75/p90（分位课程，默认）、max（旧 strong 别名）/weak/random。
    mirror_sample: str = "p50"
    #: 线性 p ramp（例如 "0.1@0,0.25@0.3,0.25@1.0"）：空=用固定 mirror_p。
    #: 训练入口按 iteration 求值后写入 mirror_p，本字段只透传/记录。
    mirror_p_ramp: str = ""
    #: True=每个回合从全部非 learner 座位随机抽 mirror_seats 个（课程模式）；默认 False。
    mirror_seat_random: bool = False
    #: 冻结对手模型（分裂模型/自对弈的对手）：空=引擎 bot；给 checkpoint 则 bot 座位由它驱动
    frozen_opponent: str = ""
    #: 由冻结对手模型驱动的 bot 座位数（0=全 bot，7=全部 7 席；1–2 性价比最高）
    frozen_seats: int = 0
    #: 批量叶服务器的聚批等待窗口（ms）。单客户端（lockstep/rust collector）应设很小。
    leaf_wait_ms: float = 2.0
    #: 动作序列辅助任务：采集侧是否产出 turn 内动作 multi-hot 标签（``seq_target``）。
    #: **默认 False = 不产出、不占内存**（records→batch→loss 与旧路径完全一致）；
    #: 打开后 batch 会多 ``[n,245] uint8`` 标签，见 docs/ACTION_SEQUENCE_AUX.md。
    seq_aux: bool = False


#: ``compile_train`` 取值 -> ``torch.compile`` 模式（0=关闭，不在表内）。
_COMPILE_TRAIN_MODES = {1: "default", 2: "max-autotune"}


def compile_train_mode(value: Any) -> int:
    """规范化 ``PPOConfig.compile_train``：``True→1``、``False→0``，只接受 0|1|2。"""
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        mode = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"compile_train 只能是 0|1|2，得到 {value!r}") from exc
    if mode != 0 and mode not in _COMPILE_TRAIN_MODES:
        raise ValueError(f"compile_train 只能是 0|1|2，得到 {value!r}")
    return mode


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
    #: 动作序列辅助任务权重（turn 内动作 multi-hot 的 BCEWithLogits）；
    #: **0 = 关闭（默认）**：不构建 seq 头、不算 seq loss、stats 里不出现 seq 字段。
    #: 需要模型带 seq 头（``build_net(..., seq_head=True)``）且 batch 有 ``seq_target``。
    seq_coef: float = 0.0
    #: 权重 ramp 规格（``"0.02@0,0.05@0.5"``，按 decisions 进度线性插值）；由训练循环
    #: 每个 iteration 用它算出实际的 ``seq_coef`` 后写回本字段。空 = 用常数 ``seq_coef``。
    seq_coef_ramp: str = ""
    #: KL anchor 到 stage 起点的系数 β（论文 Table 7：0.1，前 100 个 iteration 后放开）。
    #: >0 时必须由 trainer 提供 anchor 分布（见 PPOTrainer.set_anchor）。
    anchor_coef: float = 0.0
    #: 梯度累积：minibatch 是微批大小，grad_accum 个微批 = 一个有效 minibatch。
    #: 论文有效 minibatch = 8192；显存不够时用 e.g. minibatch=2048, grad_accum=4。
    grad_accum: int = 1
    #: worker 侧采样：sims=0 + behavior=net 时跳过 245 维 prior 回传（L2）。
    fast_act: bool = True
    #: 前向/反向精度：off=fp32；bf16=CUDA autocast(bfloat16)（实测 2.03×）。
    #: 主干在 bf16 下前向，loss/KL/entropy 计算强制回到 fp32（见 ppo_losses）。
    amp: str = "off"
    #: 训练侧 ``torch.compile``（**只** learner 的 forward+backward）：
    #: 0=关闭（默认）、1=``mode="default"``、2=``mode="max-autotune"``。
    #: ``dynamic=False``（特征/动作/minibatch 形状固定）；同时编译 anchor 参考前向并
    #: 打开 TF32（与 ``--leaf-compile`` 同一做法）。编译/运行失败自动回退 eager 并打印
    #: 一次 warn，不会中断训练。叶前向（PPOEvaluator / BatchLeafServer / 自对弈）
    #: 与评测路径完全不经过本开关，见 ``docs/TRAINING_COMPILE.md``。
    compile_train: int = 0
    #: anchor 参考前向（``PPOTrainer._anchor_logp``）的精度：False=fp32（旧行为）；
    #: True=与 ``amp`` 相同的 autocast 精度（bf16 时实测约 1.8×）。只影响 KL 正则项
    #: 的参考分布，不影响策略/价值主干前向。
    anchor_amp: bool = False
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
        self.compile_train = compile_train_mode(self.compile_train)
        self.anchor_amp = bool(self.anchor_amp)
        # 早失败：ramp 规格写错时不要等到训练循环里才炸
        if str(self.seq_coef_ramp or "").strip():
            parse_coef_ramp(self.seq_coef_ramp)
        if float(self.seq_coef) < 0.0:
            raise ValueError(f"seq_coef 必须 >= 0，得到 {self.seq_coef!r}")


# ══════════════════════════════════════════════════════════════════════════
# 4. 轨迹批次
# ══════════════════════════════════════════════════════════════════════════
#: 批次字段（保存/加载顺序）。注意：这些都是**必填**基础字段；可选的
#: ``seq_target``（动作序列辅助标签）只在启用 ``seq_aux`` 时出现，由
#: ``save()/load()`` 作为扩展字段处理，因此关闭时 npz 与旧版本逐字节一致。
BATCH_FIELDS: Tuple[str, ...] = (
    "features", "cards", "masks", "actions", "old_logprobs", "values", "rewards",
    "dones", "advantages", "returns", "seats", "game_ids", "ranks", "turns",
    "target_pi", "has_pi", "episode_ids", "forced",
)

#: 可选扩展字段（存在才写/读 npz）：动作序列辅助任务标签。
BATCH_OPTIONAL_FIELDS: Tuple[str, ...] = (SEQ_TARGET_KEY,)


@dataclass
class PPOBatch:
    """一条 PPO 轨迹批次（按 episode 分组、含 GAE）。

    数组形状（n = 样本数）::

        features f32[n,3227]  cards int16[n,124]  masks bool[n,245]
        actions int64[n]      old_logprobs f32[n] values f32[n]
        rewards f32[n]        dones f32[n]        advantages/returns f32[n]
        seats int32[n]        game_ids int64[n]   ranks int64[n]  turns int32[n]
        target_pi f32[n,245]  has_pi bool[n]      episode_ids int32[n]
        forced bool[n]（确定性守卫样本：只参与 value/critic，不参与 policy/aux）
        seq_target uint8[n,245]（可选：turn 内动作 multi-hot；启用 seq 辅助任务时才有）
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
    forced: Optional[np.ndarray] = None
    #: 动作序列辅助标签（multi-hot uint8[n,245]）；None = 未启用（默认）
    seq_target: Optional[np.ndarray] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.forced is None:
            self.forced = np.zeros(len(self.actions), dtype=bool)
        else:
            self.forced = np.asarray(self.forced, dtype=bool).reshape(-1)
        if self.seq_target is not None:
            self.seq_target = np.asarray(self.seq_target, dtype=np.uint8)

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
            "has_pi": (n,), "episode_ids": (n,), "forced": (n,),
        }
        for name, shape in expected.items():
            arr = getattr(self, name)
            if tuple(arr.shape) != shape:
                errs.append(f"{name}: shape {tuple(arr.shape)} != {shape}")
        if self.seq_target is not None:
            st = np.asarray(self.seq_target)
            if tuple(st.shape) != (n, N_ACTIONS):
                errs.append(f"seq_target: shape {tuple(st.shape)} != {(n, N_ACTIONS)}")
            elif n:
                if not np.isin(st, (0, 1)).all():
                    errs.append("seq_target 必须是 0/1 multi-hot")
                # 标签必须包含本步实际执行的动作（turn 内动作集合的定义）
                a_chk = self.actions.astype(np.int64)
                if bool(((a_chk >= 0) & (a_chk < N_ACTIONS)).all()):
                    got = st[np.arange(n), a_chk]
                    if not bool((got == 1).all()):
                        errs.append(
                            f"{int((got != 1).sum())} 条样本的 seq_target 未标本步动作")
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
        if not np.isin(self.forced.astype(np.int64), (0, 1)).all():
            errs.append("forced 必须为 0/1")
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
        """批次质量摘要（进 JSON 报告，不含大数组）；seq 字段只在启用时出现。"""
        n = len(self)
        if n == 0:
            return {"samples": 0}
        m = self.masks.astype(bool)
        a = self.actions.astype(np.int64)
        hp = self.has_pi.astype(bool)
        out = {
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
        if self.seq_target is not None:
            st = np.asarray(self.seq_target)
            out["seq_target_rate"] = float((st.sum(axis=1) > 0).mean()) if st.size else 0.0
            out["seq_target_density"] = float(st.sum() / max(st.shape[0] * st.shape[1], 1))
        return out

    # ── 存储 ──
    def save(self, path: str) -> str:
        """保存为 npz（基础数组 + 可选扩展数组 + meta json）。

        ``seq_target`` 只在启用动作序列辅助任务时写入，因此关闭时 npz 内容与旧版本一致。
        """
        path = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        payload = {f"arr_{k}": getattr(self, k) for k in BATCH_FIELDS}
        for k in BATCH_OPTIONAL_FIELDS:
            arr = getattr(self, k, None)
            if arr is not None:
                payload[f"arr_{k}"] = arr
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
            for k in BATCH_OPTIONAL_FIELDS:
                if f"arr_{k}" in z:
                    arrays[k] = np.asarray(z[f"arr_{k}"])
            meta = json.loads(str(z["meta_json"])) if "meta_json" in z else {}
        return cls(meta=meta, **arrays)


def _group_order(records: List[Dict[str, Any]]) -> List[int]:
    """按 (game_id, seat) 稳定排序的索引：同座位内保持决策时序。"""
    keys = [(int(r["game_id"]), int(r["seat"])) for r in records]
    return sorted(range(len(records)), key=lambda i: keys[i])


def build_batch_from_records(records: List[Dict[str, Any]], *,
                             gamma: float = 1.0, lam: float = 0.95,
                             step_penalty: float = 0.0,
                             meta: Optional[Dict[str, Any]] = None,
                             seq_aux: bool = False) -> PPOBatch:
    """把决策记录列表整理成 ``PPOBatch``（奖励/GAE 均已计算）。

    ``records`` 每条至少包含::

        features[3227], cards[124], mask[245], action, old_logprob, value,
        rank(1..8), seat, game_id, turn; 可选 target_pi[245]（MCTS visit π）。

    rank=0（截断/未知）的样本丢弃。奖励：每步 ``-step_penalty``，该座位 episode
    末步再加终局 ``u(rank)``；``done`` 只在该座位末步为 1。

    ``seq_aux=True`` 时额外产出动作序列辅助标签 ``seq_target``（uint8[n,245]，
    该 seat 在该 turn 内实际执行过的动作 multi-hot，见 ``seq_aux.py``）；默认 False
    时批次字段与旧版本完全一致（零影响）。
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

    forced = np.asarray([bool(r.get("forced", False)) for r in recs], dtype=bool)
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
        if s > 1e-8 and not bool(forced[i]):
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
    # 动作序列辅助标签：同 (game_id, seat, turn) 的动作集合 = multi-hot(245) uint8。
    # 只在 seq_aux=True 时构造（默认关闭 -> 批次字段/内存与旧路径完全一致）。
    seq_target = (seq_targets_from_records(recs) if seq_aux else None)
    if seq_target is not None:
        merged_meta["seq_aux"] = True
    return PPOBatch(
        features=features, cards=cards, masks=masks, actions=actions,
        old_logprobs=old_logprobs, values=values, rewards=rewards, dones=dones,
        advantages=advantages, returns=returns, seats=seats, game_ids=game_ids,
        ranks=ranks, turns=turns, target_pi=target_pi, has_pi=has_pi,
        episode_ids=episode_ids, forced=forced, seq_target=seq_target,
        meta=merged_meta)


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


def forward_model_aux(model: Any, features: Any, cards: Any, mask: Any = None):
    """带动作序列辅助头的统一前向：``(logits, rank_logits, scalar|None, seq_logits|None)``。

    模型提供 ``forward_aux``（tiny/entity 在 ``seq_head=True`` 时都提供）时一次前向同时
    拿到主头与 seq 头；否则退回 ``forward_model`` + ``split_model_outputs``（seq 为 None）。
    只有 ``seq_coef>0`` 的损失路径会调用它，默认关闭时前向路径完全不变。
    """
    fn = getattr(model, "forward_aux", None)
    if fn is not None:
        out = fn(features, cards, mask) if _accepts_mask_aux(model) else fn(features, cards)
        if not isinstance(out, (tuple, list)) or len(out) != 4:
            raise ValueError("forward_aux 必须返回 (logits, rank_logits, value|None, seq|None)")
        return out[0], out[1], out[2], out[3]
    logits, rank_logits, scalar = split_model_outputs(
        forward_model(model, features, cards, mask))
    return logits, rank_logits, scalar, None


def _accepts_mask_aux(model: Any) -> bool:
    """``forward_aux`` 是否吃 mask（tiny 的 forward_aux(features, cards=None, mask=None)）。"""
    import inspect

    fn = getattr(model, "forward_aux", None)
    if fn is None:
        return False
    try:
        return "mask" in inspect.signature(fn).parameters
    except (TypeError, ValueError):  # pragma: no cover - 内建 forward
        return False


def policy_values(model: Any, features: Any, cards: Any, mask: Any):
    """带掩码前向 -> ``(masked_probs, rank_logits, critic_value)``（torch 张量）。"""
    logits, rank_logits, _scalar = split_model_outputs(
        forward_model(model, features, cards, mask))
    return masked_probs_torch(logits, mask), rank_logits


class PPOEvaluator:
    """单条/批量叶前向。``use_compile=True`` 时对 forward 做 torch.compile（mode=reduce-overhead）。"""
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

    @staticmethod
    def _pad_bucket(n: int, buckets=(32, 64, 128, 256, 512)) -> int:
        for b in buckets:
            if n <= b:
                return b
        return int(math.ceil(n / 512.0) * 512)

    def enable_compile(self) -> None:
        """把前向包成 torch.compile（幂等）。TF32 也在这里打开。"""
        if getattr(self, "_compiled", False):
            return
        try:
            torch = self.torch
            torch.set_float32_matmul_precision("high")
            self._fwd = torch.compile(self.model, mode="reduce-overhead", fullgraph=False)
            self._compiled = True
        except Exception:  # noqa: BLE001 - 编译失败则保持 eager
            self._compiled = False

    def logits(self, features: np.ndarray, cards: Any = None,
               mask: Any = None) -> Tuple[np.ndarray, np.ndarray]:
        """批量前向 -> ``(policy_logits, rank_logits)``（amp=bf16 时前向走 autocast）。"""
        torch = self.torch
        x = self._normalize(np.atleast_2d(features))
        c = np.zeros((x.shape[0], OBS_CARDS), dtype=np.int64) if cards is None \
            else np.atleast_2d(np.asarray(cards, dtype=np.int64))
        m = None if mask is None else torch.from_numpy(
            np.ascontiguousarray(np.atleast_2d(np.asarray(mask, dtype=bool)))).to(self.device)
        with torch.no_grad():
            xt = torch.from_numpy(np.ascontiguousarray(x)).to(self.device)
            ct = torch.from_numpy(np.ascontiguousarray(c)).to(self.device)
            amp = str(getattr(self, "amp", "off")).lower() in ("bf16", "bfloat16")
            net = getattr(self, "_fwd", None) or self.model
            pad_to = self._pad_bucket(xt.shape[0]) if getattr(self, "_compiled", False) else 0
            if pad_to > xt.shape[0]:
                # 动态形状会让 CUDA graph 数量爆炸：把行数 pad 到固定桶再切片
                def _pad(t, fill):
                    if t.shape[0] == pad_to:
                        return t
                    extra = torch.zeros((pad_to - t.shape[0],) + tuple(t.shape[1:]),
                                        dtype=t.dtype, device=t.device)
                    return torch.cat([t, extra], dim=0)
                xt = _pad(xt, 0.0)
                ct = _pad(ct, 0)
                m = _pad(m, False)
            if amp and str(self.device).startswith("cuda"):
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    out = forward_model(net, xt, ct, m)
            else:
                out = forward_model(net, xt, ct, m)
            plog, rlog, _ = split_model_outputs(out)
        n = int(np.atleast_2d(np.asarray(x)).shape[0])
        plog = plog[:n]
        rlog = rlog[:n]
        return plog.float().detach().cpu().numpy(), rlog.float().detach().cpu().numpy()

    def fused_act(self, features: np.ndarray, cards: Any, mask: Any,
                  temperatures: Any = None, seed: int = 0):
        """一次 GPU pass：前向 + masked softmax + multinomial 采样 + value。

        与 ``logits()`` + 调用方采样相比，少一次 GPU→CPU→GPU 往返与同步，
        batch 采集（每轮 16–256 行）能省 2–3 ms/轮。
        返回 ``(actions int64[k], logprobs f32[k], values f32[k])``。
        """
        torch = self.torch
        x = self._normalize(np.atleast_2d(features))
        c = (np.zeros((x.shape[0], OBS_CARDS), dtype=np.int64) if cards is None
             else np.atleast_2d(np.asarray(cards, dtype=np.int64)))
        m_np = np.atleast_2d(np.asarray(mask, dtype=bool))
        dev = torch.device(self.device)
        with torch.no_grad():
            xt = torch.from_numpy(np.ascontiguousarray(x)).to(dev)
            ct = torch.from_numpy(np.ascontiguousarray(c)).to(dev)
            mt = torch.from_numpy(np.ascontiguousarray(m_np)).to(dev)
            out = forward_model(self.model, xt, ct, mt)
            plog, rlog, _ = split_model_outputs(out)
            if temperatures is None:
                t = float(self.temperature)
            else:
                tv = np.asarray(temperatures, dtype=np.float32)
                if not np.all(np.isfinite(tv)) or float(np.min(tv)) <= 0.0:
                    raise ValueError("温度非法（必须 >0 且有限）")
                t = torch.from_numpy(tv).to(dev).unsqueeze(1)
            if not bool(m_np.any(axis=1).all()):
                raise ValueError("存在无合法动作的行（mask 全 False）")
            probs = masked_log_softmax_torch(plog.float() / t, mt).exp()
            vals = value_from_rank_logits_torch(rlog.float())
            g = torch.Generator(device=dev).manual_seed(int(seed))
            idx = torch.multinomial(probs, 1, generator=g).squeeze(1)
            lps = probs.gather(1, idx.unsqueeze(1)).squeeze(1).clamp_min(1e-12).log()
        return (idx.detach().cpu().numpy().astype(np.int64),
                lps.detach().cpu().numpy().astype(np.float32),
                vals.detach().cpu().numpy().astype(np.float32))

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
# 5b. 训练侧编译（torch.compile 只包 learner 的 forward/backward）
# ══════════════════════════════════════════════════════════════════════════
class TrainForward:
    """learner 侧训练前向的 ``torch.compile`` 包装（失败自动回退 eager）。

    **只**包装 ``model.forward`` / ``model.forward_aux``：``torch.compile`` 走
    AOTAutograd，一次把 **forward + backward** 都编成静态图（梯度仍写回原
    ``model.parameters().grad``）。本类不替换 model 对象，因此 optimizer /
    state_dict / checkpoint / EMA 全部不受影响；叶前向（``PPOEvaluator``、
    BatchLeafServer、自对弈）用的是别的对象，**完全不会**经过这里。

    关键约束（与历史 leaf 侧 compile 失败的差异，见 docs/TRAINING_COMPILE.md）：

    - ``dynamic=False``：feature ``[B, 3227]``、cards ``[B, 124]``、mask ``[B, 245]``
      与 minibatch ``B`` 都是固定形状 → 只生成一张静态图；leaf 侧当年是动态 batch
      + 每步不同 B，才炸成 51 张 CUDA graph；
    - 只有 ``B == minibatch`` 走编译图，尾批（``B < minibatch``）走 eager，避免
      每个 iteration 的尾批形状触发重编译；
    - ``torch.compile`` 抛错 / warmup 抛错 / 运行期抛错 → 打印一次 warn、永久回退
      eager（训练继续，不崩）；
    - warmup 用固定形状的零张量跑一次 forward+backward（梯度随后清零），把编译
      开销挪到训练开始前（计时之外），首个 iteration 不会突然慢几十秒。

    用法::

        tf = build_train_forward(model, cfg)      # cfg.compile_train>0 时非 None
        loss = ppo_losses(..., train_forward=tf)
    """

    def __init__(self, model: Any, mode: int = 1, *, minibatch: int = 0,
                 device: str = "cpu", use_amp: bool = False) -> None:
        torch = _torch()
        self.torch = torch
        self.model = model
        self.mode = compile_train_mode(mode)
        self.minibatch = int(minibatch or 0)
        self.device = torch.device(device)
        self.use_amp = bool(use_amp) and self.device.type == "cuda"
        # 缓存「是否吃 mask」：compile 之后 OptimizedModule.forward 的签名是 (*args,
        # **kwargs)，不能再靠 inspect 判断，必须用编译前的原模型签名。
        self.accepts_mask = _accepts_mask(model)
        self.accepts_mask_aux = _accepts_mask_aux(model)
        self.has_aux = getattr(model, "forward_aux", None) is not None
        self._main_fn: Any = None
        self._aux_fn: Any = None
        self.main_compiled = False
        self.aux_compiled = False
        self.warnings: List[str] = []
        self.eager_calls = 0
        self.compiled_calls = 0
        self.warmup_seconds = 0.0

    # ── eager 原路径（与 forward_model / forward_model_aux 逐位一致）────────
    def _raw_main(self, x: Any, c: Any, m: Any):
        if self.accepts_mask:
            return self.model(x, c, m)
        return self.model(x, c)

    def _raw_aux(self, x: Any, c: Any, m: Any):
        fn = getattr(self.model, "forward_aux", None)
        if fn is None:  # 无 seq 头：等价于 forward_model_aux 的回退分支
            logits, rank_logits, scalar = split_model_outputs(self._raw_main(x, c, m))
            return logits, rank_logits, scalar, None
        if self.accepts_mask_aux:
            return fn(x, c, m)
        return fn(x, c)

    # ── 编译 / warmup ─────────────────────────────────────────────────────
    def _warn(self, kind: str, exc: BaseException) -> None:
        msg = (f"torch.compile 训练前向（{kind}）不可用，自动回退 eager："
               f"{type(exc).__name__}: {exc}")
        if msg not in self.warnings:
            self.warnings.append(msg)
            print(f"[ppo][warn] {msg}", flush=True)

    def _zero_grads(self) -> None:
        for p in self.model.parameters():
            if p.grad is not None:
                p.grad = None

    def _warm_one(self, kind: str, x: Any, c: Any, m: Any,
                  backward: bool = True) -> bool:
        torch = self.torch
        fn_raw = self._raw_main if kind == "main" else self._raw_aux
        try:
            mode = _COMPILE_TRAIN_MODES[self.mode]
            fn = torch.compile(fn_raw, mode=mode, dynamic=False, fullgraph=False)
            amp_ctx = (torch.autocast("cuda", dtype=torch.bfloat16)
                       if self.use_amp else contextlib.nullcontext())
            with amp_ctx:
                out = fn(x, c, m)
            tensors = [t for t in out if torch.is_tensor(t)]
            if not tensors:
                raise RuntimeError("训练前向没有返回任何张量")
            if backward:
                # 有 backward 才会触发 AOTAutograd 编译反向图
                loss = sum(t.float().sum() for t in tensors)
                loss.backward()
        except Exception as exc:  # noqa: BLE001 - 编译/运行失败一律回退 eager
            self._warn(kind, exc)
            self._zero_grads()
            return False
        self._zero_grads()
        if kind == "main":
            self._main_fn, self.main_compiled = fn, True
        else:
            self._aux_fn, self.aux_compiled = fn, True
        return True

    def warmup(self, *, need_aux: bool = False, batch_size: Optional[int] = None,
               backward: bool = True, verbose: bool = True) -> "TrainForward":
        """固定形状 warmup（forward+backward 各一次）：把编译开销挪到训练计时之外。"""
        torch = self.torch
        t0 = time.time()
        # torch.compile 与训练同口径：保持 eval（dropout 关闭）与固定 batch 形状
        self.model.eval()
        if self.device.type == "cuda":
            # 与 leaf_compile 一致：fp32 matmul 走 TF32（锚点参考前向明显受益；
            # amp=bf16 时训练主干本来就是 bf16，不受影响）
            torch.set_float32_matmul_precision("high")
        mb = max(1, int(batch_size or self.minibatch or 1))
        d = self.device
        warm = (torch.zeros((mb, OBS_FLOATS), dtype=torch.float32, device=d),
                torch.zeros((mb, OBS_CARDS), dtype=torch.long, device=d),
                torch.ones((mb, N_ACTIONS), dtype=torch.bool, device=d))
        self._warm_one("main", *warm, backward=backward)
        if need_aux:
            if self.has_aux:
                self._warm_one("aux", *warm, backward=backward)
            else:
                self._warn("aux", RuntimeError("模型没有 forward_aux，seq 路径保持 eager"))
        self.warmup_seconds = time.time() - t0
        if verbose:
            print(f"[ppo] train compile mode={self.mode} "
                  f"main={'on' if self.main_compiled else 'eager'} "
                  f"aux={'on' if self.aux_compiled else ('eager' if need_aux else 'off')} "
                  f"warmup={self.warmup_seconds:.1f}s"
                  + (f" warnings={len(self.warnings)}" if self.warnings else ""),
                  flush=True)
        return self

    # ── 训练调用入口 ───────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return bool(self.main_compiled or self.aux_compiled)

    def _size_ok(self, n: int) -> bool:
        return self.minibatch <= 0 or int(n) == self.minibatch

    def _call(self, kind: str, x: Any, c: Any, m: Any):
        compiled = self.main_compiled if kind == "main" else self.aux_compiled
        if compiled and self._size_ok(int(x.shape[0])):
            fn = self._main_fn if kind == "main" else self._aux_fn
            try:
                self.compiled_calls += 1
                return fn(x, c, m)
            except Exception as exc:  # noqa: BLE001 - 运行期失败同样回退 eager
                self._warn(kind, exc)
                if kind == "main":
                    self.main_compiled, self._main_fn = False, None
                else:
                    self.aux_compiled, self._aux_fn = False, None
        self.eager_calls += 1
        return self._raw_main(x, c, m) if kind == "main" else self._raw_aux(x, c, m)

    def main(self, x: Any, c: Any, m: Any):
        """训练主前向 ``(logits, rank_logits[, value])``。"""
        return self._call("main", x, c, m)

    def aux(self, x: Any, c: Any, m: Any):
        """训练辅前向 ``(logits, rank_logits, value|None, seq_logits|None)``。"""
        return self._call("aux", x, c, m)

    def describe(self) -> Dict[str, Any]:
        """进 stats 的诊断信息（可 JSON 序列化）。"""
        return {
            "mode": int(self.mode),
            "active": bool(self.active),
            "main_compiled": bool(self.main_compiled),
            "aux_compiled": bool(self.aux_compiled),
            "warmup_s": round(float(self.warmup_seconds), 3),
            "compiled_calls": int(self.compiled_calls),
            "eager_calls": int(self.eager_calls),
            "warnings": list(self.warnings),
        }


def build_train_forward(model: Any, config: Any = None, *,
                        minibatch: Optional[int] = None,
                        warmup: bool = True, need_aux: Optional[bool] = None,
                        use_amp: Optional[bool] = None,
                        warmup_backward: bool = True,
                        verbose: bool = True) -> Optional[TrainForward]:
    """按 ``PPOConfig.compile_train`` 构建训练侧编译包装；0=返回 ``None``（纯 eager）。

    ``need_aux`` 默认由 ``seq_coef>0`` 或 ``seq_coef_ramp`` 非空推断（seq 辅助任务路径
    走 ``forward_aux``，需要单独编译）。``minibatch``/``use_amp`` 可覆盖配置（anchor 参考
    前向用固定 chunk + 自己的精度口径）；``warmup_backward=False`` 用于 no_grad 的
    anchor 参考前向（只编 forward 图）。
    """
    cfg = config if config is not None else PPOConfig()
    mode = compile_train_mode(getattr(cfg, "compile_train", 0))
    if mode <= 0:
        return None
    if need_aux is None:
        need_aux = (float(getattr(cfg, "seq_coef", 0.0) or 0.0) > 0.0
                    or bool(str(getattr(cfg, "seq_coef_ramp", "") or "").strip()))
    if use_amp is None:
        amp = str(getattr(cfg, "amp", "off")).strip().lower()
        use_amp = amp in ("bf16", "bfloat16")
    tf = TrainForward(
        model, mode=mode,
        minibatch=(int(minibatch) if minibatch is not None
                   else int(getattr(cfg, "minibatch", 0) or 0)),
        device=str(getattr(cfg, "device", "cpu")),
        use_amp=bool(use_amp))
    if warmup:
        tf.warmup(need_aux=bool(need_aux), backward=bool(warmup_backward),
                  verbose=verbose)
    return tf


# ══════════════════════════════════════════════════════════════════════════
# 6. PPO loss / 训练
# ══════════════════════════════════════════════════════════════════════════
def ppo_losses(model: Any, batch: PPOBatch, config: PPOConfig,
               indices: Optional[np.ndarray] = None,
               anchor_logp: Any = None,
               train_forward: Optional[TrainForward] = None) -> Dict[str, Any]:
    """计算一个 minibatch 的 PPO 损失（返回 torch 张量字典）。

    - policy: ``-min(r*A, clip(r,1±ε)*A).mean()``；
    - value: ``rank``（名次 CE）或 ``mse``（``E[u(rank)]`` vs returns）；
    - aux: ``pi_coef * CE(π_MCTS, π_θ)``（仅 ``has_pi`` 样本）；
    - seq（动作序列辅助任务，默认关闭）: ``seq_coef * BCEWithLogits(seq_logits, seq_target)``，
      只在 ``valid & ~forced`` 且标签非空的样本上平均；
    - entropy: masked 策略熵（鼓励探索）；
    - anchor: ``anchor_coef * KL(π_θ ‖ π_anchor)``（``anchor_logp`` 为 stage 起点在整批
      样本上的 masked log-prob，形状 ``[len(batch), 245]``）；
    - 非法动作：logits 在 loss 内重新 masked，概率严格 0（``illegal_prob_max`` 可验证）；
    - ``train_forward``：``TrainForward``（``compile_train>0`` 时传入）；前向走编译图，
      否则与旧版本一致走 ``forward_model`` / ``forward_model_aux``。
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
    forced = torch.from_numpy(
        np.ascontiguousarray(batch.forced[idx].astype(bool))).to(dev)
    valid = (~forced).to(torch.float32)
    if config.normalize_advantage:
        # 只在 valid（非 forced）子集上估均值/方差：forced 是环境确定性守卫，
        # 不应影响策略侧 advant 的尺度（否则会间接改变 policy 梯度）
        n_valid = valid.sum().clamp_min(1.0)
        vmean = (adv * valid).sum() / n_valid
        vvar = (((adv - vmean) ** 2) * valid).sum() / n_valid
        adv = (adv - vmean) / vvar.sqrt().clamp_min(1e-8)

    # 动作序列辅助任务（默认关闭）：只有 seq_coef>0 才走 forward_aux 取 seq logits，
    # 否则前向调用链与旧版本完全一致（byte-identical）。
    seq_coef = float(getattr(config, "seq_coef", 0.0) or 0.0)
    seq_logits = None
    if seq_coef > 0.0:
        if train_forward is not None:
            _l, _r, _s, seq_logits = train_forward.aux(x, c, m)
        else:
            _l, _r, _s, seq_logits = forward_model_aux(model, x, c, m)
        logits, rank_logits, scalar_value = _l, _r, _s
    else:
        if train_forward is not None:
            out = train_forward.main(x, c, m)
        else:
            out = forward_model(model, x, c, m)
        logits, rank_logits, scalar_value = split_model_outputs(out)
    # 无论是否 autocast，loss 侧一律 fp32：KL/entropy/cross_entropy 的数值稳定性依赖它
    logits = logits.float()
    rank_logits = rank_logits.float()
    if scalar_value is not None:
        scalar_value = scalar_value.float()
    logp = masked_log_softmax_torch(logits, m)
    action_logp = logp.gather(1, actions.unsqueeze(1)).squeeze(1)
    ratio = torch.exp(action_logp - old_logp)
    policy_loss, clip_frac = clipped_surrogate(ratio, adv, config.clip, weight=valid)

    probs = logp.exp()
    safe_logp = torch.where(m, logp, torch.zeros_like(logp))
    entropy_all = -(probs * safe_logp).sum(dim=-1)
    entropy = (entropy_all * valid).sum() / valid.sum().clamp_min(1.0)

    value_pred = value_from_rank_logits_torch(rank_logits)
    if config.value_loss == "rank":
        value_loss = F.cross_entropy(rank_logits, (ranks - 1).clamp(0, N_RANKS - 1))
    else:
        value_loss = F.mse_loss(value_pred, returns_t)
    if scalar_value is not None and float(config.value_head_coef) > 0.0:
        value_loss = value_loss + float(config.value_head_coef) * F.mse_loss(
            scalar_value, returns_t)

    aux_mask = has_pi & (valid > 0)   # forced 样本不参与 aux policy（与主 policy loss 一致）
    if bool(aux_mask.any()) and float(config.pi_coef) > 0.0:
        aux_all = -(target_pi * safe_logp).sum(dim=-1)
        aux_pi_loss = aux_all[aux_mask].mean()
    else:
        aux_pi_loss = torch.zeros((), device=dev)

    # ── 动作序列辅助头（turn 内动作 multi-hot 的 BCEWithLogits）────────────────
    # 只在 seq_coef>0 且模型带 seq 头、批次带 seq_target 时计算；只对 valid（~forced）
    # 且标签非空的行平均。默认关闭时既不前向 seq 头、也不往 total 里加任何项。
    seq_loss = None
    if seq_coef > 0.0:
        target_np = getattr(batch, "seq_target", None)
        if seq_logits is not None and target_np is not None:
            tgt = torch.from_numpy(np.ascontiguousarray(
                np.asarray(target_np)[idx].astype(np.float32))).to(dev)
            has_target = (tgt.sum(dim=-1) > 0).to(torch.float32)
            seq_loss = seq_bce_loss(seq_logits, tgt, weight=valid * has_target)
        else:
            # 缺标签（如 Rust 采集器未产出）或模型未建 seq 头：记 0，不制造假梯度
            seq_loss = torch.zeros((), device=dev)

    total = (policy_loss + float(config.value_coef) * value_loss
             + float(config.pi_coef) * aux_pi_loss
             - float(config.entropy_coef) * entropy)
    if seq_loss is not None:
        total = total + seq_coef * seq_loss
    anchor_kl = torch.zeros((), device=dev)
    beta = float(config.anchor_coef)
    if beta > 0.0 and anchor_logp is not None:
        # KL(π_θ ‖ π_anchor) = Σ_a π_θ(a) · (log π_θ(a) − log π_anchor(a))，只对合法动作求和
        a_lp = anchor_logp[idx] if anchor_logp.shape[0] > idx.max() else anchor_logp
        a_safe = torch.where(m, a_lp, torch.zeros_like(a_lp))
        kl_all = (probs * (safe_logp - a_safe)).sum(dim=-1)
        anchor_kl = (kl_all * valid).sum() / valid.sum().clamp_min(1.0)
        total = total + beta * anchor_kl
    approx_kl = ((old_logp - action_logp) * valid).sum() / valid.sum().clamp_min(1.0)
    illegal_prob_max = (probs * (~m).to(probs.dtype)).max()
    result = {
        "total": total,
        "policy_loss": policy_loss,
        "value_loss": value_loss,
        "aux_pi_loss": aux_pi_loss,
        "anchor_kl": anchor_kl,
        "entropy": entropy,
        "approx_kl": approx_kl,
        "clip_frac": clip_frac,
        "ratio_mean": (ratio * valid).sum() / valid.sum().clamp_min(1.0),
        "illegal_prob_max": illegal_prob_max,
        "adv_mean": adv.mean(),
        "value_pred_mean": value_pred.mean(),
    }
    # 默认关闭时不出现该键（保持 stats/日志与旧版本逐字节一致）
    if seq_loss is not None:
        result["seq_loss"] = seq_loss
    return result


def train_ppo(model: Any, batch: PPOBatch, config: Optional[PPOConfig] = None,
              *, on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
              optimizer: Any = None, rng: Optional[np.random.Generator] = None,
              anchor_logp: Any = None,
              train_forward: Optional[TrainForward] = None) -> Dict[str, Any]:
    """执行 PPO 更新（minibatch × epochs，clip、entropy、KL 早停）。

    ``train_forward``：复用外部构建的 ``TrainForward``（``PPOTrainer`` 在启动时构建并
    warmup，避免把编译开销算进第一个 iteration）；为 ``None`` 且
    ``config.compile_train>0`` 时在此处构建 + warmup。

    返回可 JSON 序列化的统计字典。
    """
    cfg = config or PPOConfig()
    torch = _torch()
    errs = batch.validate()
    if errs:
        raise ValueError("PPO 批次校验失败: " + "; ".join(errs))
    rng = rng if rng is not None else np.random.default_rng(int(cfg.seed))
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
    # 训练侧编译：默认在第一个 minibatch 前构建 + 固定形状 warmup（编译开销不在
    # minibatch 循环里）；PPOTrainer 会传入启动时已 warmup 的同一个对象。
    if train_forward is None and compile_train_mode(getattr(cfg, "compile_train", 0)) > 0:
        train_forward = build_train_forward(model, cfg)
    if optimizer is not None:
        model_ids = {id(p) for p in model.parameters()}
        opt_ids = {id(p) for group in optimizer.param_groups for p in group["params"]}
        if not opt_ids.issubset(model_ids):
            raise ValueError("外部 optimizer 含不属于当前 model 的参数")
    opt = (optimizer if optimizer is not None
           else torch.optim.Adam(model.parameters(), lr=float(cfg.lr)))
    mb = max(1, int(cfg.minibatch))
    epochs = max(1, int(cfg.epochs))
    logs: List[Dict[str, Any]] = []
    updates = 0
    processed = 0
    stopped_early = False
    t0 = time.time()
    # 梯度累积：minibatch 是**微批**大小，grad_accum 个微批 = 一个有效 minibatch（论文 8192）
    accum = max(1, int(getattr(cfg, "grad_accum", 1)))
    eff = mb * accum
    amp_mode = str(getattr(cfg, "amp", "off")).strip().lower()
    use_amp = amp_mode in ("bf16", "bfloat16") and device.type == "cuda"
    for epoch in range(epochs):
        order = rng.permutation(n)
        acc: Dict[str, List[float]] = {}
        nb = 0
        epoch_stopped = False
        for start in range(0, n, eff):
            slices = [(start + j * mb, min(start + (j + 1) * mb, n))
                      for j in range(accum)]
            slices = [(a, b) for a, b in slices if a < b]
            if not slices:
                break
            opt.zero_grad(set_to_none=True)
            step_metrics: Dict[str, float] = {}
            served = 0
            for a, b in slices:
                sel = base_idx[order[a:b]]
                if use_amp:
                    with torch.autocast("cuda", dtype=torch.bfloat16):
                        out = ppo_losses(model, batch, cfg, indices=sel,
                                         anchor_logp=anchor_logp,
                                         train_forward=train_forward)
                else:
                    out = ppo_losses(model, batch, cfg, indices=sel,
                                     anchor_logp=anchor_logp,
                                     train_forward=train_forward)
                (out["total"] / float(len(slices))).backward()
                served += int(sel.size)
                for k, v in out.items():
                    step_metrics[k] = (step_metrics.get(k, 0.0)
                                       + float(v.detach().cpu()) / float(len(slices)))
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(cfg.max_grad_norm))
            for k, v in step_metrics.items():
                acc.setdefault(k, []).append(v)
            if on_step is not None:
                on_step({"step": updates, "epoch": epoch + 1, **step_metrics})
            if int(cfg.log_every) > 0 and updates % int(cfg.log_every) == 0:
                print(f"[ppo] step {updates} total={step_metrics['total']:.4f} "
                      f"policy={step_metrics['policy_loss']:.4f} "
                      f"value={step_metrics['value_loss']:.4f} "
                      f"kl={step_metrics['approx_kl']:.5f}", flush=True)
            # 标准 PPO：逐有效 minibatch 监控近似 KL；超阈的这一步不执行更新
            if cfg.kl_early_stop and float(cfg.target_kl) > 0.0 and \
                    step_metrics["approx_kl"] > 1.5 * float(cfg.target_kl):
                stopped_early = True
                epoch_stopped = True
                break
            opt.step()
            updates += 1
            processed += int(served)
            nb += 1
        rec: Dict[str, Any] = {"epoch": epoch + 1, "steps": nb}
        rec.update({k: float(np.mean(v)) for k, v in acc.items()})
        rec["elapsed_s"] = time.time() - t0
        rec["kl_early_stopped"] = bool(epoch_stopped)
        logs.append(rec)
        # seq=... 只在启用动作序列辅助任务时出现（默认关闭 -> 日志行与旧版逐字节一致）
        seq_note = f" seq={rec['seq_loss']:.4f}" if "seq_loss" in rec else ""
        print(f"[ppo] epoch {epoch + 1}/{epochs} total={rec['total']:.4f} "
              f"(policy={rec['policy_loss']:.4f} value={rec['value_loss']:.4f} "
              f"aux_pi={rec['aux_pi_loss']:.4f} ent={rec['entropy']:.4f} "
              f"kl={rec['approx_kl']:.5f} clip={rec['clip_frac']:.3f}){seq_note}",
              flush=True)
        if epoch_stopped:
            print(f"[ppo] KL 早停：minibatch approx_kl 超过 "
                  f"1.5*target_kl={1.5 * float(cfg.target_kl):.5f}", flush=True)
            break
    model.eval()
    elapsed = time.time() - t0
    stats: Dict[str, Any] = {
        "epochs": logs,
        "updates": int(updates),
        "samples": n,
        "processed_samples": int(processed),
        "forced_samples": int(np.asarray(batch.forced, dtype=bool).sum()),
        "seconds": float(elapsed),
        "samples_per_s": float(processed / max(elapsed, 1e-9)),
        "stopped_early": bool(stopped_early),
        "target_kl": float(cfg.target_kl),
        "kl_early_stop": bool(cfg.kl_early_stop),
        "value_loss_mode": cfg.value_loss,
        "pi_coef": float(cfg.pi_coef),
        "amp": str(getattr(cfg, "amp", "off")),
        "compile_train": int(getattr(cfg, "compile_train", 0) or 0),
        "compile_active": bool(train_forward is not None and train_forward.active),
        "cuda_peak_mb": (round(torch.cuda.max_memory_allocated(device) / 2 ** 20, 1)
                         if device.type == "cuda" else None),
        "config": to_jsonable(asdict(cfg)),
    }
    if train_forward is not None:
        # 编译诊断：是否真的走上编译图 / warmup 耗时 / 回退原因（无编译时不出该键）
        stats["compile"] = train_forward.describe()
    # 动作序列辅助任务：只有「当前系数>0 或配置了 ramp」才出现，
    # 且关闭（默认）时连 config 回显里的两个 seq 键也去掉 -> stats 与旧版逐字节一致。
    seq_points = parse_coef_ramp(str(getattr(cfg, "seq_coef_ramp", "") or ""))
    seq_on = float(getattr(cfg, "seq_coef", 0.0) or 0.0) > 0.0 or bool(seq_points)
    if seq_on:
        stats["seq_coef"] = float(getattr(cfg, "seq_coef", 0.0) or 0.0)
        stats["seq_coef_ramp"] = str(getattr(cfg, "seq_coef_ramp", "") or "")
        stats["seq_loss"] = float(np.mean([r.get("seq_loss", 0.0) for r in logs]))
    else:
        cfg_echo = stats.get("config")
        if isinstance(cfg_echo, dict):
            cfg_echo.pop("seq_coef", None)
            cfg_echo.pop("seq_coef_ramp", None)
    return stats


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
                 norm_std: Optional[np.ndarray] = None,
                 move_model: bool = True) -> None:
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
        if move_model:
            self.model.to(self.device)
        self.model.eval()

    def reset(self) -> None:
        # 一局开始：清空本局记录/回合计数（search/forced 计数保留，用于整次采集 meta）
        self.records = []
        self._n = 0
        self._turn_counts = {}

    def reseed(self, seed: int) -> None:
        """每局固定 RNG：并行/串行都按 seed+game_id 重建，保证可复现。"""
        self._rng = np.random.default_rng(int(seed))

    # ── 网络前向（单条决策）──
    def _net_predict(self, features: np.ndarray, cards: np.ndarray,
                     mask: np.ndarray, seat: int = 0) -> Tuple[np.ndarray, float]:
        # 如果注入 eval_fn（例如共享 BatchPPOEvaluator），网络决策也走批量叶服务；
        # 否则退化为单条 model 前向。
        if self.eval_fn is not None:
            prior, value = self.eval_fn(np.asarray(features, np.float32),
                                        np.asarray(cards, np.int64),
                                        np.asarray(mask, bool), int(seat))
            p = np.asarray(prior, dtype=np.float64).reshape(-1)
            p = p / max(float(p.sum()), 1e-12)
            logits = np.log(np.maximum(p, 1e-12)).astype(np.float32)
            return logits, float(value)
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

    def _can_fast_act(self) -> bool:
        """sims=0 + behavior=net + evaluator 支持 worker 侧采样 → 可跳过 245 维 prior。"""
        return (bool(getattr(self.config, "fast_act", True))
                and self.search_fn is None
                and str(self.config.behavior).strip().lower() == "net"
                and hasattr(self.eval_fn, "act")
                and float(self.config.temperature) > 0.0)

    def _observe(self, game: Any, seat: int):
        """取观测与合法动作掩码（与 decide 一致）。"""
        f, c = obs_arrays(game.observe(int(seat)))
        mask = mask_from_bytes(game.legal_mask(int(seat)))
        return f, c, mask

    def _finish(self, game: Any, seat: int, f: Any, c: Any, mask: Any, *,
                action: int, logprob: float, value: float,
                target_pi: Optional[np.ndarray], out_pi: Optional[np.ndarray]) -> Decision:
        """收尾：回合守卫 → 写 record → 构造 Decision（decide/decide_batch 共用）。"""
        seat = int(seat)
        turn = int(getattr(game, "turn", -1))
        limit = int(getattr(self.config, "max_actions_per_turn", 0) or 0)
        # 守卫计数必须按「局」隔离：lock-step 下同一个 policy 服务多局
        key = (int(self.game_id), seat, turn)
        n_turn = self._turn_counts.get(key, 0) + 1
        self._turn_counts[key] = n_turn
        forced = bool(limit > 0 and n_turn > limit and bool(mask[0]))

        legal = np.flatnonzero(mask)
        if legal.size == 0:
            action, logprob = 0, 0.0
        elif forced:
            # 守卫动作是**环境确定性约束**（delta 在 EndTurn 上），不是行为分布采样。
            # 记录 logprob=0 且 forced=True；PPO 的策略/aux loss 会排除这些样本，
            # 只保留 value/critic/回报链，避免伪造 on-policy ratio。
            action, logprob = 0, 0.0
            self.forced_actions += 1
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
            "seat": seat,
            "turn": turn,
            "game_id": int(self.game_id),
            "forced": bool(forced),
        })
        if out_pi is None:
            out_pi = (target_pi if target_pi is not None
                      else mask.astype(np.float32) / max(float(mask.sum()), 1.0))
        return Decision(int(action), np.asarray(out_pi, dtype=np.float32),
                        {"search": target_pi is not None, "policy": self.name,
                         "logprob": float(logprob), "value": float(value),
                         "forced": bool(forced)})

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        f, c, mask = self._observe(game, seat)
        if self._can_fast_act():
            # worker 侧采样：省掉 prior 回传 + 调用方 numpy softmax/采样
            seed = int(self._rng.integers(0, 2 ** 63 - 1))
            a, lp, value = self.eval_fn.act(f, c, mask,
                                            float(self.config.temperature), seed)
            return self._finish(game, seat, f, c, mask, action=int(a), logprob=float(lp),
                                value=float(value), target_pi=None, out_pi=None)

        logits, value = self._net_predict(f, c, mask, seat)
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
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            action, logprob = 0, 0.0
        else:
            mu64 = np.maximum(np.asarray(mu, dtype=np.float64), 0.0)
            s = float(mu64.sum())
            mu64 = (mu64 / s) if s > 0 else (mask.astype(np.float64) / float(legal.size))
            action = int(self._rng.choice(N_ACTIONS, p=mu64))
            if not bool(mask[action]):  # 数值兜底：只在合法动作上取 max
                action = int(legal[int(np.argmax(mu64[legal]))])
            logprob = float(math.log(max(float(mu64[action]), LOGPROB_FLOOR)))
        return self._finish(game, seat, f, c, mask, action=action, logprob=logprob,
                            value=float(value), target_pi=target_pi, out_pi=mu)

    def decide_batch(self, pairs: Sequence[Any]) -> List[Decision]:
        """lock-step：对若干 ``(game, seat)`` 一次批量前向，再逐个收尾。"""
        items = []
        for it in pairs:
            if len(it) == 3:
                items.append((it[0], int(it[1]), int(it[2])))
            else:
                items.append((it[0], int(it[1]), None))
        out: List[Decision] = []
        if not items:
            return out
        if not (self._can_fast_act() and hasattr(self.eval_fn, "act_batch")):
            res = []
            for g, s, gid in items:
                if gid is not None:
                    self.game_id = int(gid)
                res.append(self.decide(g, s))
            return res
        prepared = []
        for g, s, gid in items:
            f, c, mask = self._observe(g, s)
            prepared.append((g, s, gid, f, c, mask))
        F = np.stack([p[3] for p in prepared]).astype(np.float32, copy=False)
        C = np.stack([p[4] for p in prepared]).astype(np.int64, copy=False)
        M = np.stack([p[5] for p in prepared]).astype(bool, copy=False)
        seed = int(self._rng.integers(0, 2 ** 63 - 1))
        acts, lps, vals = self.eval_fn.act_batch(F, C, M,
                                                 float(self.config.temperature), seed)
        for i, (g, s, gid, f, c, mask) in enumerate(prepared):
            if gid is not None:
                self.game_id = int(gid)
            out.append(self._finish(g, s, f, c, mask, action=int(acts[i]),
                                    logprob=float(lps[i]), value=float(vals[i]),
                                    target_pi=None, out_pi=None))
        return out


def _attach_rank(records: List[Dict[str, Any]], rank: int) -> None:
    """把终局名次回填到该座位本局所有决策记录。"""
    util = float(utility_from_rank([int(rank)])[0])
    for rec in records:
        rec["rank"] = int(rank)
        rec["utility"] = util


def _weak_bot_action(game: Any, seat: int, rng: np.random.Generator) -> int:
    """弱对手：30% 合法 EndTurn（若可用），否则随机合法动作。

    只用于 C0 冷启动课程；主评测仍是对完整引擎 bot。
    """
    mask = mask_from_bytes(game.legal_mask(int(seat)))
    legal = np.flatnonzero(mask)
    if legal.size == 0:
        return 0
    if bool(mask[0]) and float(rng.random()) < 0.90:
        return 0
    return int(legal[int(rng.integers(0, legal.size))])


def pack_records_arrays(records: Sequence[Dict[str, Any]],
                        *, seq_aux: bool = False) -> Dict[str, np.ndarray]:
    """records(list[dict]) → SoA 数组（L3：一次性 stack，供 npz 传输）。

    ``seq_aux=True`` 时额外产出 ``seq_target``（uint8[n,245] multi-hot）；默认 False
    时返回的字段集合与旧版本完全一致。
    """
    n = len(records)
    f0 = records[0]["features"]
    has_pi = any(r.get("target_pi") is not None for r in records)
    out = {
        "features": np.empty((n, f0.size), dtype=np.float32),
        "cards": np.empty((n, np.asarray(records[0]["cards"]).size), dtype=np.int16),
        "masks": np.empty((n, np.asarray(records[0]["mask"]).size), dtype=bool),
        "actions": np.empty(n, dtype=np.int64),
        "old_logprobs": np.empty(n, dtype=np.float32),
        "values": np.empty(n, dtype=np.float32),
        "ranks": np.empty(n, dtype=np.int64),
        "seats": np.empty(n, dtype=np.int32),
        "game_ids": np.empty(n, dtype=np.int64),
        "turns": np.empty(n, dtype=np.int32),
        "forced": np.empty(n, dtype=bool),
        "has_pi": np.zeros(n, dtype=bool),
    }
    if has_pi:
        out["target_pi"] = np.zeros((n, np.asarray(records[0]["mask"]).size), dtype=np.float32)
    for i, r in enumerate(records):
        out["features"][i] = r["features"]
        out["cards"][i] = np.asarray(r["cards"], dtype=np.int16)
        out["masks"][i] = np.asarray(r["mask"], dtype=bool)
        out["actions"][i] = int(r["action"])
        out["old_logprobs"][i] = float(r["old_logprob"])
        out["values"][i] = float(r["value"])
        out["ranks"][i] = int(r.get("rank", -1))
        out["seats"][i] = int(r["seat"])
        out["game_ids"][i] = int(r["game_id"])
        out["turns"][i] = int(r.get("turn", -1))
        out["forced"][i] = bool(r.get("forced", False))
        pi = r.get("target_pi")
        if pi is not None and has_pi and not out["forced"][i]:
            pi = np.asarray(pi, dtype=np.float32).reshape(-1)
            m_i = out["masks"][i].astype(np.float32)
            if pi.size == m_i.size:                 # 与 records 侧一致：非法清零 + 归一
                pi = pi * m_i
                s_pi = float(pi.sum())
                pi = pi / s_pi if s_pi > 1e-8 else (m_i / max(float(m_i.sum()), 1.0))
                out["has_pi"][i] = True
                out["target_pi"][i] = pi
    if seq_aux:
        # 动作序列辅助标签：同一 (game_id, seat, turn) 的动作集合（向量化一次算完）
        out[SEQ_TARGET_KEY] = seq_targets_from_records(records)
    return out


def build_batch_from_arrays(packed: Dict[str, np.ndarray], *, gamma: float = 1.0,
                            lam: float = 0.95, step_penalty: float = 0.0,
                            meta: Optional[Dict[str, Any]] = None) -> "PPOBatch":
    """SoA 数组 → PPOBatch（与 ``build_batch_from_records`` 等价，但零 dict）。

    可选字段 ``seq_target``（动作序列辅助标签）存在且形状正确时透传给批次；
    缺字段/形状不符时批次 ``seq_target=None``（= 该批次不参与 seq 辅助损失）。
    """
    n0 = len(np.asarray(packed["ranks"]))
    # 丢掉形状与样本数不匹配的字段（例如无 MCTS 时的空 target_pi）
    packed = {k: v for k, v in packed.items()
              if np.ndim(v) > 0 and len(np.asarray(v)) == n0}
    ranks = np.asarray(packed["ranks"])
    valid = (ranks >= 1) & (ranks <= N_RANKS)
    dropped = int((~valid).sum())
    if not bool(valid.all()):
        packed = {k: v[valid] for k, v in packed.items()}
    game_ids = np.asarray(packed["game_ids"])
    seats = np.asarray(packed["seats"])
    turns = np.asarray(packed["turns"])
    # 与 ``_group_order`` 完全一致：按 (game_id, seat) **稳定**排序，局内保持原时序
    key = game_ids.astype(np.int64) * np.int64(256) + seats.astype(np.int64)
    order = np.argsort(key, kind="stable")
    t = {k: v[order] for k, v in packed.items()}
    n = int(order.size)
    if n == 0:
        raise ValueError("build_batch_from_arrays: 没有有效样本")
    game_ids, seats, turns = t["game_ids"], t["seats"], t["turns"]
    values = t["values"]

    rewards = np.full(n, -float(step_penalty), dtype=np.float32)
    dones = np.zeros(n, dtype=np.float32)
    episode_ids = np.zeros(n, dtype=np.int32)
    key_change = np.empty(n, dtype=bool)
    key_change[0] = True
    key_change[1:] = (game_ids[1:] != game_ids[:-1]) | (seats[1:] != seats[:-1])
    ep_index = np.cumsum(key_change) - 1
    episode_ids[:] = ep_index
    ep = int(ep_index[-1] + 1)
    last_of_ep = np.empty(n, dtype=bool)
    last_of_ep[:-1] = key_change[1:]
    last_of_ep[-1] = True
    util = utility_from_rank(ranks[valid][order])
    rewards[last_of_ep] = np.asarray(util, dtype=np.float32)[last_of_ep] - float(step_penalty)
    dones[last_of_ep] = 1.0

    advantages, returns = compute_gae(rewards, values, dones, gamma=gamma, lam=lam)
    merged_meta: Dict[str, Any] = dict(meta or {})
    merged_meta.update({"gamma": float(gamma), "lam": float(lam),
                        "step_penalty": float(step_penalty),
                        "dropped_unknown_rank": dropped, "episodes": int(ep)})
    # 动作序列辅助标签：有则透传（缺字段/形状不符 -> None，不报错）
    seq_target = t.get(SEQ_TARGET_KEY)
    if seq_target is not None:
        seq_target = np.asarray(seq_target, dtype=np.uint8)
        if seq_target.shape != (n, N_ACTIONS):
            seq_target = None
        else:
            merged_meta["seq_aux"] = True
    return PPOBatch(
        features=t["features"], cards=t["cards"], masks=t["masks"],
        actions=t["actions"], old_logprobs=t["old_logprobs"], values=values,
        rewards=rewards, dones=dones, advantages=advantages, returns=returns,
        seats=seats.astype(np.int32), game_ids=game_ids.astype(np.int64),
        ranks=ranks[valid][order].astype(np.int64), turns=turns.astype(np.int32),
        target_pi=(lambda tp: tp if (tp is not None and np.asarray(tp).shape == (n, N_ACTIONS))
                   else np.zeros((n, N_ACTIONS), dtype=np.float32))(t.get("target_pi")),
        has_pi=(lambda hp: hp if (hp is not None and np.asarray(hp).shape == (n,))
                else np.zeros(n, dtype=bool))(t.get("has_pi")),
        episode_ids=episode_ids, forced=t["forced"], seq_target=seq_target,
        meta=merged_meta)


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
    if mode not in ("self", "bot", "weak"):
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
            policy.reseed(int(cfg.seed) + gi)
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
        weak_rng = np.random.default_rng(int(cfg.seed))
        for gi in range(int(cfg.games)):
            gid = int(cfg.game_id_offset) + gi
            policy.game_id = gid
            policy.reseed(int(cfg.seed) + gi)
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
                    elif mode == "weak":
                        game.step(int(p), _weak_bot_action(game, int(p), weak_rng))
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
        "mode": ("vs_bot" if mode == "bot" else ("vs_weak" if mode == "weak" else "selfplay")),
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
                                     step_penalty=step_penalty, meta=collect_meta,
                                     seq_aux=bool(cfg.seq_aux))
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
    "BATCH_OPTIONAL_FIELDS",
    "build_batch_from_records",
    "pack_records_arrays",
    "build_batch_from_arrays",
    "forward_model",
    "forward_model_aux",
    "split_model_outputs",
    "TrainForward",
    "build_train_forward",
    "compile_train_mode",
    "PPOEvaluator",
    "PPOGreedyPolicy",
    "ppo_losses",
    "train_ppo",
    "PPOSelfPlayPolicy",
    "collect_ppo_batch",
]
