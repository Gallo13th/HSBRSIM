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

from hsbg.az.train.game_rules import game_config_json as _game_cfg
from hsbg.eval.metrics import game_weights  # 长强局加权（仅 --game-weight-mode != none）

import contextlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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
from .bc_aux import (
    DEFAULT_BC_SAMPLES_PATH,
    DEFAULT_BC_CARD_WEIGHT,
    DEFAULT_BC_TYPE_WEIGHT,
    BC_ACTION_TYPES,
    BC_OBS_LAYOUT,
    BCObsBatch,
    bc_hier_loss,
    bc_obs_batch,
    bc_pool_summary,
    load_bc_samples,
    parse_bc_coef_ramp,
)
from .seq_aux import (
    SEQ_TARGET_KEY,
    parse_coef_ramp,
    seq_bce_loss,
    seq_targets_from_records,
)
from .dpo_upgrade import UpgradeSamples, dpo_pair_loss
from .move_guard import (MoveGuard, DEFAULT_MOVE_CAP,
                         DEFAULT_MOVE_REPEAT_LIMIT, aggregate_move_guard)
from .archetype_bias import (ArchetypeBias, aggregate_archetype_bias,
                             engine_card_id_lookup, DEFAULT_TABLE as ARCH_TABLE,
                             DEFAULT_MODEL as ARCH_MODEL)
from .reward_shaping import RewardShaper
from .tier_target import TierTargetTracker, aggregate_tier_target
from .power_trace import compact_diagnostics, compute_credit
from .process_value import process_value_loss
from .forced_upgrade import ForcedUpgradeGuard
from .comp_buy import CompBuyBias
from .process_value import consume_count as _consume_count
from .process_value import process_target as _process_target
from .curriculum import apply_turn_gold as _apply_turn_gold
from .scaling_teacher import ScalingTeacher as _ScalingTeacher
from .scaling_teacher import in_scaling_window as _in_scaling_window

# ── 数值边界 ──────────────────────────────────────────────────────────────
#: torch 侧非法 logits 的填充值（float32 下 ``exp(-1e30)=0``，避免 -inf 制造 NaN 梯度）。
MASKED_LOGIT = -1e30
#: logprob 下限（行为分布采样时防 log(0)）。
LOGPROB_FLOOR = 1e-12

#: 战团强度 Σ 在标准观测里的位置（board 块 7×31，atk/hp 已 /10）。
BOARD_SLICE = slice(68, 285)
BOARD_N, BOARD_F = 7, 31
STRENGTH_LOG_REF = 30000.0


def log_strength_from_features(features: Any) -> np.ndarray:
    """features[n,3227] → ``L(Σ) = log1p(Σ)/log1p(30000)``（与沙盒/叶值同一曲线）。

    只用于「0.7·强度 + 0.3·名次」的终局强度项；要求 features 是**原始编码**
    （未做输入标准化）。Σ 用 ``docs/ECONOMY_SANDBOX.md`` §1 的 board 块口径：
    ``board[i,0] > 0.5`` 表示有随从，atk/hp 乘以 10 还原。
    """
    arr = np.asarray(features, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    b = arr[:, BOARD_SLICE].reshape(arr.shape[0], BOARD_N, BOARD_F)
    present = b[:, :, 0] > 0.5
    sig = np.where(present, b[:, :, 1] + b[:, :, 2], 0.0).sum(axis=1) * 10.0
    return np.log1p(np.maximum(sig, 0.0)) / np.log1p(float(STRENGTH_LOG_REF))


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
    #: ── 搜索作为行为策略（μ=(1−ε)π+ε·π_search；默认 0 = 关闭、逐位等价旧路径）──
    #: 见 ``hsbg/az/train/behavior_mix.py`` 与 ``docs/BEHAVIOR_MIX_PPO.md``。
    #: 关键决策点以概率 ``behavior_mix_eps`` 用 ``InferSearcher`` 的 π_search 采样；
    #: records 额外写 ``logp_mu``/``logp_pi``，PPO 的 ratio 分母改用 ``logp_mu``。
    behavior_mix_eps: float = 0.0
    #: 关键决策口径（``carrier_or_spell`` / ``any`` / 逗号组合）
    behavior_mix_when: str = "carrier_or_spell"
    #: 每回合最多搜索几次（<=0 不限；默认 6，与 s17 的 t6 口径一致）
    behavior_mix_max_per_turn: int = 6
    #: 根候选数（π top-k 非 Move）
    behavior_mix_topk: int = 8
    #: 叶值 horizon（1 = 本回合末）
    behavior_mix_turns: int = 1
    #: 单次搜索墙钟上限 ms（0 = 不限）；超时回退按 π 采样
    behavior_mix_max_ms: float = 500.0
    #: 1=精确模式（每个关键决策都搜索 → logp_mu 在全部分支精确）；0=只在 ε 命中时搜索
    behavior_mix_exact: int = 1
    #: ── per-episode 长强加权（``--game-weight-mode``）──
    #: ``none``（默认）= 关闭（旧路径逐位等价）；``adv`` = 每局按 (对局长度, 对手最强盘面)
    #: 算权重（``hsbg.eval.metrics.game_weights``，均值归一到 1），只缩放 advantage。
    game_weight_mode: str = "none"
    game_weight_alpha: float = 0.5
    game_weight_beta: float = 0.5
    game_weight_floor: float = 0.5
    game_weight_cap: float = 2.0
    step_penalty: float = 0.0      # 每决策小惩罚（进入 reward）
    #: 单座位单回合决策数上限（超过且 EndTurn 合法则强制结束回合；0=关闭）。
    #: 未训练网络容易陷入 Play/Cancel 循环，默认 40 保证采集/评测能走到终局。
    max_actions_per_turn: int = 40
    #: ── 换位去抖守卫（默认关闭；见 docs/MOVE_GUARD.md）──
    #: True=采样前清掉「逆换位 / 重复超限 / 本回合换位超 cap」的 Move 动作位，
    #: 再按剩余合法动作采样。**默认 False = 不构造守卫、不碰 mask、不新增
    #: record/meta 字段，与旧路径逐位等价。**
    move_guard: bool = False
    #: 每回合换位次数上限（>=cap 后屏蔽全部 49 个 Move；0=本回合禁止换位）。
    move_cap: int = DEFAULT_MOVE_CAP
    #: 同一 ``(from,to)`` 本回合出现 >= 该次数后屏蔽（1=不允许重复）。
    move_repeat_limit: int = DEFAULT_MOVE_REPEAT_LIMIT
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
    #: 人类战团（board-only）注入库：``data/real_library/library_real_degraded.jsonl``
    #: （空=不用）。只替换 board + 派生 tier，见 docs/HUMAN_BOARD_OPPONENT.md。
    human_boards: str = ""
    #: 每个候选座位每回合的注入概率（默认 0=关闭，零影响）。
    human_board_p: float = 0.0
    #: 每回合随机选的座位数（从全部非 learner 座位里抽）。
    human_board_seats: int = 2
    #: 桶内分位：auto=按 turn 走难度曲线（t<=8 p50 / 9..12 p75 / t>=13 p90）；
    #: 也接受 p50/p75/p90/max 固定分位。
    human_board_sample: str = "auto"
    #: True=同时写入按 turn 派生的酒馆等级（人类数据没有 tier 字段）。
    human_board_set_tier: bool = True
    #: 人类战团保真度：``board``（默认，board-only，逐位等价旧行为）/
    #: ``hand``（board+手牌）/ ``full``（board+hand+可推断 counters）。hand/full 需要
    #: 准完整库 ``data/real_library/library_real_quasi_full.jsonl``；见
    #: ``docs/FIDELITY_INJECTION.md``。
    human_board_fidelity: str = "board"
    #: 人类战团注入**快速路径**（``full``/``hand`` 档有效）：缓存 payload 注入视图
    #: （每个库行只解析一次）+ orjson 编解码 + ``ended_turn`` 字符串替换。
    #: **默认 False = 逐位等价旧行为**；开启后同 seed 动作序列/状态也完全相同
    #: （见 ``tests/test_fast_injection.py`` 与 docs/FIDELITY_INJECTION.md）。
    human_board_fast_inject: bool = False
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
    #: ── 势函数奖励塑形（默认关闭；见 docs/REWARD_SHAPING.md）──
    #: λ：塑形系数。**0 = 关闭**：不读状态、不写 record，采集/打包/GAE 与旧路径逐位一致。
    shaping_coef: float = 0.0
    #: 塑形折扣 γ_s；**None（默认）= 跟随训练 γ**（``PPOConfig.gamma``，当前 1.0）。
    #: 只有 γ_s 与训练 γ 严格相等时 F 才逐决策望远镜（整局和 = −c·Φ0，与策略无关）；
    #: 显式设成不一致的值会在启动期警告并记录 ``reward_shaping_bias_sum``。
    shaping_gamma: Optional[float] = None
    #: Φ(s) = shaping_w_str * Σ(atk+hp) + shaping_w_tier * TIER_BONUS[tier]
    shaping_w_str: float = 1.0
    shaping_w_tier: float = 0.5
    #: 塑形势的强度口径：``sigma``（默认，原始 Σ）/ ``log_strength``（L(Σ)，
    #: 整局望远镜求和 = shaping_coef·L(Σ_T)，与沙盒/叶值同一曲线）。
    shaping_mode: str = "sigma"
    #: 逗号分隔的 tier 奖励表，**按 tier 直接索引**（索引 0 为占位；越界按 0）。
    shaping_tier_bonus: str = "0,0,20,60,150,400,900"
    #: ── 等级进度奖励（tier-target，默认关闭；见 docs/TIER_TARGET.md）──
    #: 系数：**0 = 关闭**（不读状态、不写 record、不新增 meta 键，旧路径逐位一致）。
    #: 非 0 时在 learner 每个新回合起点按 ``tier_target_table`` 检查 tier：
    #: 未达标扣 ``coef*tier_penalty``，首次达标一次性加 ``coef*tier_bonus``。
    #: 未达标惩罚是否均分到整回合（默认 False = 只在回合第一条 decision 扣）
    #: 强制升本守卫（默认 False）：买得起「升级 + 最便宜商品」时只允许升级。
    forced_upgrade: bool = False
    forced_upgrade_margin: float = 0.0
    #: **复利买卡偏置**（B11）：商店里出现 `data/comp_cards.json` 的目标卡时，屏蔽其它购买
    #: （并禁止卖掉已上场核心），让轨迹里充满"买到核心之后怎么滚"的数据。0=关闭。
    comp_buy_bias: float = 0.0
    #: 目标卡规格文件（默认 data/comp_cards.json）
    comp_cards: str = ""
    #: 条件式买卡规则参数（B11 v2）：同一张核心卡最多囤几张、血量下限、开局血量门槛、后期回合
    comp_buy_max_copies: int = 3
    comp_buy_health_floor: float = 12.0
    comp_buy_opening_health: float = 20.0
    comp_buy_late_turn: int = 17
    #: 强制升本的**上限本数**：当前 tier >= 该值后不再强制（默认 5；<=0 = 不限）
    forced_upgrade_max_tier: int = 5
    tier_spread: bool = False
    tier_target_coef: float = 0.0
    #: 未达标惩罚（乘 coef；默认 0.02 ≈ 名次效用全距 2.0 的 1%）。
    tier_penalty: float = 0.02
    #: 达标一次性奖励（乘 coef；默认 0.15 ≈ 名次效用全距的 7.5%）。
    tier_bonus: float = 0.15
    #: 目标曲线 ``turn:tier``（逗号分隔），默认 ``7:4,9:5,12:6``。
    tier_target_table: str = "7:4,9:5,12:6"
    #: ── 流派（archetype）软偏置（默认关闭；见 docs/ARCHETYPE_BIAS.md）──
    #: 系数：**0 = 关闭**（不构造对象、不碰 logits、不新增 meta 键，旧路径逐位等价）。
    #: 建议 0.5–2.0：对「当前流派在当前 turn 的偏好动作」加 ``coef * 相对增益`` 的 logit，
    #: **只加不减、不屏蔽任何合法动作**（PPO 仍可偏离）。
    archetype_bias_coef: float = 0.0
    #: 检测置信度门槛：只有 ``max_prob >= 该值`` 才偏置（低置信 → 不偏置，默认 0.6）。
    archetype_min_prob: float = 0.6
    #: 流派特征的**输入哈希缓存**（默认关）：同一 ``(features, cards, mask, 历史修订号)``
    #: 只算一次；输出与不缓存逐位相同。实测命中率 ≈0（每决策特征都会变），默认关闭。
    archetype_cache: bool = False
    #: 偏好表 / 分类器模型路径（空 = 默认 ``data/archetype/*``）。
    archetype_table: str = ""
    archetype_model: str = ""
    #: ── 复利结构选牌先验（collect 侧，纯 obs；默认 0 = 不构造对象 ⇒ 逐位等价）──
    #: Discover：pending 是三连奖励 3 选 1 时，对「选项含放大器/引擎卡」的 choose 位加该常数。
    collect_discover_bias: float = 0.0
    #: Triple：商店里能凑三连（已持 2 张）的 buy 位 +2×该值、能凑对子（1 张）+1×该值。
    collect_triple_bias: float = 0.0
    #: s42：商店出现"链四卡"时对对应 buy 位加的偏置（默认 0 = 关；只对合法位）
    collect_chain_buy_bias: float = 0.0
    #: s49：伴生卡 id 列表（逗号分隔；空 = 用默认四卡）
    collect_chain_ids: str = ""
    #: s49：t8-9 的 reroll 动作偏置（0 = 关）
    collect_reroll_bias_t8t9: float = 0.0
    #: 记录行为策略 logprob（配合 collect 侧 bias）：写 logp_mu=log μ(a)（PPO ratio 分母）
    #: 与 logp_pi=log π(a)（KL/approx_kl 口径）。默认 0 = 不写字段（逐位等价）。
    record_logp_mu: int = 0
    #: ── 经济（金币）课程（默认 none + 1.0 = 逐位等价；见 docs/CURRICULUM_SCALING.md）──
    #: 阶段名（none/warmup/anneal）只用于 meta/history 记录；采集侧真正用的是
    #: ``curriculum_gold_mult``（训练入口按累计 decisions 求值后的**当前**倍数）。
    curriculum_stage: str = "none"
    #: 当前 iteration 生效的金币收入倍数；1.0 = 完全不碰金币（逐位等价）。
    curriculum_gold_mult: float = 1.0
    #: 在线缩放教师 DAgger：True 时在「gold>=10 且 tier>=4」的决策上写
    #: ``teacher_action``（-1 = 本决策无标签）；默认 False = 不查教师、不新增字段。
    teacher_bc: bool = False
    #: 过程价值辅助标签：True 时每决策写 ``process_target``（酒馆永久 buff /
    #: 施法数 / consume 数，log1p）；默认 False = 不读日志、不新增字段。
    process_value: bool = False


# ══════════════════════════════════════════════════════════════════════════
# 4b. 对手强度课程（human-board 席数/概率/分位按累计 learner decisions 爬坡）
#
# 动机（docs/BOARD_RAMP.md）：s15 的训练分布是「5 席 × p0.9（fidelity=full）」，
# 200 局 tier 分布 t1..t6 = 822/706/483/96/3/3 回合 —— 模型整局停在 tier1–3；
# 规则教师（scripts/carrier_teacher.py）在同分布下 0/200 局活到 t12，在 7-bot
# 宽松分布下能活到 t12。载体（11 张施法成长随从）多在 tier4–6，所以「对手太强
# → 活不到后期 → 学不到缩放」。对策：先降对手强度（少座位 / 低注入概率 / 低分位），
# 按**累计 learner decisions** 逐步加回。
#
# **默认（空 spec + adaptive=0）是恒等映射**：``state()`` 原样返回 CLI 的
# seats/p/sample，训练入口写回 CollectConfig 的也是同一组值 -> 与旧路径逐位等价。
# ══════════════════════════════════════════════════════════════════════════

#: 席数/p 的插值方式：``step``=分段常数（默认，档位边界突变）；
#: ``linear``=段内线性插值（seats 四舍五入、p 连续），用于平滑过渡实验。
BOARD_RAMP_MODES: Tuple[str, ...] = ("step", "linear")
#: 分位课程允许的取值（与 ``CollectConfig.human_board_sample`` 同口径）。
BOARD_RAMP_QUANTILES: Tuple[str, ...] = ("auto", "p50", "p75", "p90", "max")
#: 「存活到 t12」的回合阈值（回合号，与 ``records["turn"]`` 同口径）。
BOARD_RAMP_SURVIVE_TURN = 12
#: ``tier>=4`` 的**代理**回合阈值：tier_target 曲线是 ``7:4,9:5,12:6``，
#: 第 7 回合该到 tier4，这里保守取 8（没有直接 tier 观测时的替代口径）。
BOARD_RAMP_TIER4_PROXY_TURN = 8
#: 自适应门控默认阈值：存活到 t12 >= 0.25 **且** tier>=4 >= 0.30 才提前升档。
BOARD_RAMP_SURVIVE_THRESHOLD = 0.25
BOARD_RAMP_TIER4_THRESHOLD = 0.30
#: 不达标时把下一档推迟的 decisions（默认 2M）。
BOARD_RAMP_DELAY_DECISIONS = 2_000_000.0
#: 门控的「强制结束回合」上限（每局均值）：超过它说明「活到 t12」很可能是**动作上限
#: 强制结束回合**刷出来的假存活（模型在 Play/Cancel 循环里），此时不允许提前升档。
#: 参考值：s15 真实采集 ≈ 0.16 次/局；短跑 band0 ≈ 7 次/局仍属正常。
BOARD_RAMP_MAX_FORCED_PER_GAME = 12.0
#: decisions 字面量后缀（``"10M"`` / ``"500K"`` / ``"1B"``）。
_DECISIONS_UNITS = {"": 1.0, "k": 1e3, "m": 1e6, "b": 1e9}


def parse_decisions(value: Any) -> float:
    """解析 decisions 字面量：``"2000000"`` / ``"2M"`` / ``"500K"`` / ``"1.5B"``。

    纯函数；非法输入抛 ``ValueError``（训练入口启动期 fail-fast）。负数 / NaN / inf
    一律拒绝。``bool`` 也拒绝（避免 ``True`` 被当成 1.0 的静默 bug）。
    """
    if isinstance(value, bool):
        raise ValueError(f"decisions 必须是数字，不能是 bool: {value!r}")
    if isinstance(value, (int, float)):
        d = float(value)
    else:
        text = str(value).strip().replace("_", "")
        if not text:
            raise ValueError("decisions 不能为空")
        suffix = text[-1].lower()
        if suffix in _DECISIONS_UNITS and suffix:
            num, unit = text[:-1], suffix
        else:
            num, unit = text, ""
        try:
            d = float(num)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"非法 decisions 字面量: {value!r}") from exc
        d *= _DECISIONS_UNITS[unit]
    if not math.isfinite(d) or d < 0.0:
        raise ValueError(f"decisions 必须是有限非负数: {value!r}")
    return float(d)


def parse_board_ramp(spec: Any) -> List[Tuple[float, int, float]]:
    """解析 ``"0:1:0.30,10M:2:0.50"`` -> ``[(decisions, seats, p), ...]``（按 decisions 升序）。

    - 片段格式 ``decisions:seats:p``；decisions 支持 ``K`` / ``M`` / ``B`` 后缀；
    - seats 必须是 ``1..N_PLAYERS-1`` 的整数；p 必须是 ``[0, 1]`` 的有限小数；
    - 空字符串 / ``None`` -> ``[]``（课程关闭）；
    - decisions 重复 -> ``ValueError``（档位边界必须唯一）；
    - 首个控制点不要求是 0：早于它时取第一档（与 ``ramp_p`` 同语义）。
    """
    if spec is None:
        return []
    text = str(spec).strip()
    if not text:
        return []
    pts: List[Tuple[float, int, float]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        fields = part.split(":")
        if len(fields) != 3:
            raise ValueError(
                f"board-ramp 片段应为 decisions:seats:p，得到 {part!r}")
        d_txt, s_txt, p_txt = (f.strip() for f in fields)
        d = parse_decisions(d_txt)
        try:
            seats = int(s_txt)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"board-ramp seats 必须是整数: {part!r}") from exc
        try:
            p = float(p_txt)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"board-ramp p 必须是 0..1 的小数: {part!r}") from exc
        if not (1 <= seats <= N_PLAYERS - 1):
            raise ValueError(
                f"board-ramp seats 必须在 1..{N_PLAYERS - 1}: {part!r}")
        if not math.isfinite(p) or not (0.0 <= p <= 1.0):
            raise ValueError(f"board-ramp p 越界 [0,1]: {part!r}")
        pts.append((d, int(seats), float(p)))
    pts.sort(key=lambda z: z[0])
    for (d0, _s0, _p0), (d1, _s1, _p1) in zip(pts, pts[1:]):
        if d1 == d0:
            raise ValueError(f"board-ramp 控制点 decisions 必须严格递增: {spec!r}")
    return pts


def parse_quantile_ramp(spec: Any) -> List[Tuple[float, str]]:
    """解析 ``"0:p75,20M:p90"`` -> ``[(decisions, quantile), ...]``（按 decisions 升序）。

    取值限 :data:`BOARD_RAMP_QUANTILES`（auto/p50/p75/p90/max）；分位是**类别**，
    只做分段常数，不做线性插值。空字符串 -> ``[]``（分位不变）。
    """
    if spec is None:
        return []
    text = str(spec).strip()
    if not text:
        return []
    pts: List[Tuple[float, str]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"quantile-ramp 片段应为 decisions:quantile，得到 {part!r}")
        d_txt, q_txt = part.split(":", 1)
        d = parse_decisions(d_txt.strip())
        q = str(q_txt).strip().lower()
        if q not in BOARD_RAMP_QUANTILES:
            raise ValueError(
                f"quantile-ramp 取值必须是 {BOARD_RAMP_QUANTILES} 之一: {part!r}")
        pts.append((d, q))
    pts.sort(key=lambda z: z[0])
    for (d0, _q0), (d1, _q1) in zip(pts, pts[1:]):
        if d1 == d0:
            raise ValueError(
                f"quantile-ramp 控制点 decisions 必须严格递增: {spec!r}")
    return pts


def _ramp_index(points: Sequence[Any], x: float) -> int:
    """分段常数档位下标：最后一个 ``decisions <= x`` 的控制点（早于首个取 0）。"""
    idx = 0
    for i, point in enumerate(points):
        if float(x) >= float(point[0]):
            idx = i
    return int(idx)


def _round_half_up(value: float) -> int:
    """四舍五入到整数（不用 Python 的银行家舍入，保证 1.5 -> 2 / 2.5 -> 3）。"""
    return int(math.floor(float(value) + 0.5))


def board_ramp_at(decisions: Any, points: Sequence[Tuple[float, int, float]], *,
                  mode: str = "step") -> Tuple[int, float]:
    """求 ``(seats, p)``：``step`` 分段常数 / ``linear`` 段内线性插值。

    - 早于首个控制点 -> 第一档；晚于末个 -> 最后一档（边界外保持）；
    - ``linear`` 时 seats 线性插值后四舍五入并夹到 ``1..N_PLAYERS-1``，p 连续插值；
    - 空 points -> ``ValueError``（调用方应先判断是否启用课程）。
    """
    if not points:
        raise ValueError("board-ramp 控制点为空")
    m = str(mode or "step").strip().lower()
    if m not in BOARD_RAMP_MODES:
        raise ValueError(f"ramp mode 必须是 {BOARD_RAMP_MODES} 之一: {mode!r}")
    x = float(decisions)
    if x <= float(points[0][0]):
        return int(points[0][1]), float(points[0][2])
    if x >= float(points[-1][0]):
        return int(points[-1][1]), float(points[-1][2])
    if m == "step":
        idx = _ramp_index(points, x)
        return int(points[idx][1]), float(points[idx][2])
    for (x0, s0, p0), (x1, s1, p1) in zip(points, points[1:]):
        if float(x0) <= x < float(x1):     # 右端属于下一段（边界不重复计入）
            t = 0.0 if float(x1) == float(x0) else (x - float(x0)) / (float(x1) - float(x0))
            seats = _round_half_up(float(s0) + (float(s1) - float(s0)) * t)
            seats = min(N_PLAYERS - 1, max(1, int(seats)))
            return int(seats), float(p0 + (p1 - p0) * t)
    idx = _ramp_index(points, x)
    return int(points[idx][1]), float(points[idx][2])


def quantile_ramp_at(decisions: Any, points: Sequence[Tuple[float, str]]) -> str:
    """分段常数求分位（类别，不插值）；空 points -> ``ValueError``。"""
    if not points:
        raise ValueError("quantile-ramp 控制点为空")
    return str(points[_ramp_index(points, float(decisions))][1])


@dataclass
class BoardRampState:
    """某一累计 decisions 下**实际生效**的对手强度（训练入口写进 collect 配置）。"""

    seats: int
    p: float
    sample: str
    #: 求值用的 ramp 输入（= 累计 decisions + start - delay，且单调不减）。
    decisions: float
    #: 当前档位下标（无 ramp 时恒 0）与档位总数（无 ramp 时 0）。
    band: int
    bands: int
    mode: str
    adaptive: bool
    early_advances: int
    delay_decisions: float
    start_decisions: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        """history 用的扁平 dict（见 :func:`board_ramp_history`）。"""
        return {"seats": int(self.seats), "p": round(float(self.p), 6),
                "sample": str(self.sample), "band": int(self.band),
                "bands": int(self.bands), "mode": str(self.mode),
                "adaptive": bool(self.adaptive),
                "decisions": int(round(float(self.decisions))),
                "early_advances": int(self.early_advances),
                "delay_decisions": int(round(float(self.delay_decisions))),
                "start_decisions": int(round(float(self.start_decisions)))}


class BoardRampController:
    """对手强度课程控制器：``state()`` 求值 + ``observe()`` 自适应门控。

    - ``state(decisions)`` 是**唯一**的生效值来源（训练入口每 iteration 调用一次，
      把返回的 ``seats/p/sample`` 写进 CollectConfig）；
    - 没有 spec 时恒等映射（返回构造时的 ``base_*``，不新增任何行为）；
    - ``adaptive=1`` 时 ``observe()`` 用最近 ``window`` 个 iteration 的门控指标
      （``survive_t12`` / ``tier_ge4`` 均值）决定：**提前升档**（连续达标 -> 档位 +1）
      或**推迟**（不达标 -> 后续控制点整体后移 ``delay_decisions``，每档最多一次）；
    - 单调性：内部 x 只增不减，推迟也不会让档位回落；早期升档记在 ``band_floor``，
      因此 schedule 追上后不会重复跳档。
    """

    def __init__(self, spec: Any = "", *, mode: str = "step",
                 quantile_spec: Any = "", adaptive: bool = False,
                 base_seats: int = 2, base_p: float = 0.0,
                 base_sample: str = "auto", window: int = 5,
                 survive_threshold: float = BOARD_RAMP_SURVIVE_THRESHOLD,
                 tier4_threshold: float = BOARD_RAMP_TIER4_THRESHOLD,
                 max_forced_per_game: float = BOARD_RAMP_MAX_FORCED_PER_GAME,
                 delay_decisions: Any = BOARD_RAMP_DELAY_DECISIONS,
                 start_decisions: Any = 0.0) -> None:
        self.spec = "" if spec is None else str(spec).strip()
        self.quantile_spec = ("" if quantile_spec is None
                              else str(quantile_spec).strip())
        self.mode = str(mode or "step").strip().lower()
        if self.mode not in BOARD_RAMP_MODES:
            raise ValueError(f"ramp mode 必须是 {BOARD_RAMP_MODES} 之一: {mode!r}")
        self.board_points = parse_board_ramp(self.spec)
        self.quantile_points = parse_quantile_ramp(self.quantile_spec)
        self.adaptive = bool(adaptive)
        self.base_seats = int(base_seats)
        self.base_p = float(base_p)
        self.base_sample = str(base_sample or "auto")
        self.window = max(1, int(window))
        self.survive_threshold = float(survive_threshold)
        self.tier4_threshold = float(tier4_threshold)
        self.max_forced_per_game = float(max_forced_per_game)
        self._delay_step = float(parse_decisions(delay_decisions))
        self.start_decisions = float(parse_decisions(start_decisions))
        if not (0.0 <= self.survive_threshold <= 1.0):
            raise ValueError("ramp survive threshold 必须在 [0,1] 内")
        if not (0.0 <= self.tier4_threshold <= 1.0):
            raise ValueError("ramp tier4 threshold 必须在 [0,1] 内")
        if not (self.max_forced_per_game >= 0.0):
            raise ValueError("ramp max_forced_per_game 必须 >= 0")
        if self.base_sample not in BOARD_RAMP_QUANTILES:
            raise ValueError(
                f"base sample 必须是 {BOARD_RAMP_QUANTILES} 之一: {base_sample!r}")
        self._x_max = 0.0
        self._band_floor = 0
        self._delay = 0.0
        self._early = 0
        self._iters_since_change = 0
        self._delayed_bands: set = set()
        self._window: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []

    # ---- 只读属性 ----
    @property
    def enabled(self) -> bool:
        """是否配置了任何 ramp（False = 完全恒等映射）。"""
        return bool(self.board_points or self.quantile_points)

    @property
    def bands(self) -> int:
        return int(len(self.board_points) or len(self.quantile_points))

    @property
    def delay_decisions(self) -> float:
        return float(self._delay)

    @property
    def early_advances(self) -> int:
        return int(self._early)

    def max_p(self) -> float:
        """课程里出现过的最大注入概率（启动期据此判断「是否需要人类战团库」）。"""
        if self.board_points:
            return float(max(p for _d, _s, p in self.board_points))
        return float(self.base_p)

    # ---- 求值 ----
    def _advance(self, decisions: Any) -> float:
        x = float(decisions) + float(self.start_decisions) - float(self._delay)
        if not math.isfinite(x):
            x = 0.0
        x = max(x, float(self._x_max), 0.0)
        self._x_max = float(x)
        return float(x)

    def _band_of(self, points: Sequence[Any], x: float) -> int:
        n = len(points)
        if n <= 0:
            return 0
        sched = _ramp_index(points, x)
        if not self.adaptive:
            return int(min(max(sched, 0), n - 1))
        return int(min(max(sched, self._band_floor, 0), n - 1))

    def state(self, decisions: Any) -> BoardRampState:
        """求本 iteration 生效的 ``(seats, p, sample)``（纯查表 + 单调 x 记忆）。"""
        x = self._advance(decisions)
        pts = self.board_points if self.board_points else self.quantile_points
        band = self._band_of(pts, x) if pts else 0
        if self.board_points:
            if band > _ramp_index(self.board_points, x):
                seats, p = (int(self.board_points[band][1]),
                            float(self.board_points[band][2]))
            else:
                seats, p = board_ramp_at(x, self.board_points, mode=self.mode)
        else:
            seats, p = int(self.base_seats), float(self.base_p)
        if self.quantile_points:
            qband = self._band_of(self.quantile_points, x)
            sample = str(self.quantile_points[qband][1])
        else:
            sample = str(self.base_sample)
        return BoardRampState(
            seats=int(seats), p=float(p), sample=str(sample), decisions=float(x),
            band=int(band), bands=int(self.bands), mode=str(self.mode),
            adaptive=bool(self.adaptive), early_advances=int(self._early),
            delay_decisions=float(self._delay),
            start_decisions=float(self.start_decisions))

    # ---- 自适应门控 ----
    def observe(self, iter_index: Any, decisions: Any,
                metrics: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """记录一个 iteration 的门控指标并决定提前/推迟；返回本次事件列表。

        ``adaptive=0`` 或没有 ramp 时恒返回 ``[]``（不做任何状态变更）。
        """
        if not (self.adaptive and self.enabled):
            return []
        m = metrics if isinstance(metrics, dict) else {}
        surv = _ramp_number(m.get("survive_t12"))
        tier4 = _ramp_number(m.get("tier_ge4"))
        forced = _ramp_number(m.get("forced_per_game"))
        self._window.append({"iter": int(iter_index),
                             "survive_t12": float(0.0 if surv is None else surv),
                             "tier_ge4": float(0.0 if tier4 is None else tier4),
                             "forced_per_game": float(0.0 if forced is None else forced)})
        if len(self._window) > self.window:
            self._window = self._window[-int(self.window):]
        self._iters_since_change += 1
        st = self.state(decisions)
        n = int(st.bands)
        if n <= 1 or int(st.band) >= n - 1:
            return []
        if len(self._window) < self.window or self._iters_since_change < self.window:
            return []
        w = self._window
        s_mean = sum(float(r["survive_t12"]) for r in w) / len(w)
        t_mean = sum(float(r["tier_ge4"]) for r in w) / len(w)
        f_mean = sum(float(r["forced_per_game"]) for r in w) / len(w)
        # 强制结束回合过多 = 存活是「动作上限」刷出来的假象 -> 不算达标（宁可推迟）
        inflated = f_mean > float(self.max_forced_per_game)
        good = (s_mean >= float(self.survive_threshold)
                and t_mean >= float(self.tier4_threshold) and not inflated)
        events: List[Dict[str, Any]] = []
        if good:
            self._band_floor = int(st.band) + 1
            self._early += 1
            self._iters_since_change = 0
            events.append({
                "iter": int(iter_index), "event": "early",
                "from_band": int(st.band), "to_band": int(self._band_floor),
                "decisions": int(round(float(st.decisions))),
                "survive_t12": round(s_mean, 4), "tier_ge4": round(t_mean, 4),
                "forced_per_game": round(f_mean, 3)})
        elif int(st.band) not in self._delayed_bands:
            self._delayed_bands.add(int(st.band))
            self._delay += float(self._delay_step)
            self._iters_since_change = 0
            events.append({
                "iter": int(iter_index), "event": "delay",
                "band": int(st.band),
                "decisions": int(round(float(st.decisions))),
                "delay_decisions": int(round(float(self._delay))),
                "survive_t12": round(s_mean, 4), "tier_ge4": round(t_mean, 4),
                "forced_per_game": round(f_mean, 3)})
        for ev in events:
            self.events.append(dict(ev))
        return events

    def window_summary(self) -> Dict[str, Any]:
        """最近 ``window`` 个 iteration 的门控均值（history 可观测性用）。"""
        w = self._window
        if not w:
            return {"iters": 0, "window": int(self.window),
                    "survive_t12_mean": None, "tier_ge4_mean": None,
                    "forced_per_game_mean": None}
        return {"iters": len(w), "window": int(self.window),
                "survive_t12_mean": round(
                    sum(float(r["survive_t12"]) for r in w) / len(w), 4),
                "tier_ge4_mean": round(
                    sum(float(r["tier_ge4"]) for r in w) / len(w), 4),
                "forced_per_game_mean": round(
                    sum(float(r["forced_per_game"]) for r in w) / len(w), 3)}

    def describe(self) -> Dict[str, Any]:
        """课程配置摘要（启动打印 / summary.json 用）。"""
        return {
            "spec": self.spec, "quantile_spec": self.quantile_spec,
            "mode": self.mode, "bands": int(self.bands),
            "adaptive": bool(self.adaptive), "window": int(self.window),
            "survive_threshold": float(self.survive_threshold),
            "tier4_threshold": float(self.tier4_threshold),
            "max_forced_per_game": float(self.max_forced_per_game),
            "delay_decisions": int(round(float(self._delay_step))),
            "start_decisions": int(round(float(self.start_decisions))),
            "base_seats": int(self.base_seats), "base_p": float(self.base_p),
            "base_sample": str(self.base_sample),
            "points": [[int(round(d)), int(s), float(p)]
                       for d, s, p in self.board_points],
            "quantile_points": [[int(round(d)), str(q)]
                                for d, q in self.quantile_points],
        }


def _ramp_number(value: Any) -> Optional[float]:
    """可当 0..1 比例的数值（bool/str/numpy 标量都试一下），其它返回 None。"""
    if isinstance(value, bool):
        return float(value)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return float(out)


def ramp_progress_metrics(
        turns: Any, game_ids: Any = None, *,
        collect_meta: Optional[Dict[str, Any]] = None,
        quality: Optional[Dict[str, Any]] = None,
        survive_turn: int = BOARD_RAMP_SURVIVE_TURN,
        tier4_proxy_turn: int = BOARD_RAMP_TIER4_PROXY_TURN) -> Dict[str, Any]:
    """本 iteration 的自适应门控指标：``survive_t12`` / ``tier_ge4``（均在 0..1）。

    口径优先级（高 -> 低）：

    1. ``quality``：离线质量统计（``scripts/quality_monitor.py`` 的
       ``survive_t12_ratio`` / ``tier_ge4_ratio``），**真实 tier 观测**；
    2. ``collect_meta``：采集 meta 里的同名键（顶层或嵌套 ``collect``）；
    3. **轨迹代理**：``turns`` 只记录 learner 决策回合，按 ``game_ids`` 取每局最大
       turn。``survive_t12 = mean(max_turn >= 12)``；``tier>=4`` 没有直接观测，按
       tier_target 曲线（7:4 / 9:5 / 12:6）用 ``max_turn >= 8`` 代理（保守一回合）。

    代理不读引擎、不加采集开销；``source`` 记录实际口径，历史里可直接核对。
    """
    turns_arr = np.asarray([] if turns is None else turns).reshape(-1)
    gids = None if game_ids is None else np.asarray(game_ids).reshape(-1)
    max_turn: List[float] = []
    if int(turns_arr.size) and gids is not None and int(gids.size) == int(turns_arr.size):
        t_f = turns_arr.astype(np.float64, copy=False)
        for g in np.unique(gids):
            max_turn.append(float(t_f[gids == g].max()))
    elif int(turns_arr.size):
        max_turn = [float(turns_arr.astype(np.float64, copy=False).max())]
    out: Dict[str, Any] = {"games": int(len(max_turn)),
                           "records": int(turns_arr.size),
                           "survive_turn": int(survive_turn),
                           "tier4_proxy_turn": int(tier4_proxy_turn),
                           "source": "batch"}
    if max_turn:
        mt = np.asarray(max_turn, dtype=np.float64)
        out["max_turn_p50"] = float(np.percentile(mt, 50))
        out["max_turn_mean"] = float(mt.mean())
        out["survive_t12"] = float(np.mean(mt >= float(survive_turn)))
        out["tier_ge4"] = float(np.mean(mt >= float(tier4_proxy_turn)))
    else:
        out.update({"max_turn_p50": 0.0, "max_turn_mean": 0.0,
                    "survive_t12": 0.0, "tier_ge4": 0.0})
    meta_src: Dict[str, Any] = {}
    if isinstance(collect_meta, dict):
        inner = collect_meta.get("collect")
        meta_src = inner if isinstance(inner, dict) else collect_meta
    for src, name in ((meta_src, "collect_meta"), (quality, "quality")):
        if not isinstance(src, dict):
            continue
        s_val = _ramp_number(src.get("survive_t12_ratio",
                                     src.get("survive_t12")))
        t_val = _ramp_number(src.get("tier_ge4_ratio", src.get("tier_ge4")))
        if s_val is not None:
            out["survive_t12"] = float(min(1.0, max(0.0, s_val)))
            out["source"] = name
        if t_val is not None:
            out["tier_ge4"] = float(min(1.0, max(0.0, t_val)))
            out["source"] = name
    forced = _ramp_number(meta_src.get("forced_end_turns")) if isinstance(
        meta_src, dict) else None
    out["forced_end_turns"] = int(forced or 0)
    out["forced_per_game"] = (float(out["forced_end_turns"]) / out["games"]
                              if out.get("games") else 0.0)
    return out


def board_ramp_history(state: BoardRampState, *,
                       spec: Any = "", quantile_spec: Any = "",
                       mode: str = "step", adaptive: bool = False,
                       events: Optional[Sequence[Dict[str, Any]]] = None
                       ) -> Dict[str, Any]:
    """history.jsonl 每行的 ``human_board`` 段：**实际生效**的 seats/p/sample + 档位。"""
    rec = dict(state.as_dict())
    rec.update({
        "mode": str(mode or state.mode),
        "adaptive": bool(adaptive),
        "ramp": "" if spec is None else str(spec).strip(),
        "quantile_ramp": "" if quantile_spec is None else str(quantile_spec).strip(),
        "events": [dict(e) for e in (events or [])],
    })
    return rec


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
    #: 终局名次效用的系数（默认 1.0 = 旧行为）。用于「0.7·强度 + 0.3·名次」这类
    #: 混合奖励：强度项走势函数塑形（``shaping_mode=log_strength``），名次项乘本系数。
    rank_utility_coef: float = 1.0
    #: 终局强度奖励系数（默认 0 = 关闭）：末步额外加 ``coef·L(Σ_末决策)``。
    #: 与 ``rank_utility_coef`` 一起构成「0.7·强度 + 0.3·名次」的目标奖励。
    terminal_strength_coef: float = 0.0

    entropy_coef: float = 0.01
    value_coef: float = 0.5
    #: MCTS visit π 辅助交叉熵权重 alpha（0 = 关闭，退化为纯 PPO）
    pi_coef: float = 0.5
    #: ── 搜索行为混合 μ=(1−ε)π+ε·π_search（只用于 stats 回显/诊断）──
    #: 采集侧由 ``CollectConfig.behavior_mix_*`` 控制；这里只是把同一组值回显进
    #: ``stats["config"]`` 并参与 ``stats["behavior_mix"]``（eps=0 时整组键会被移除）。
    behavior_mix_eps: float = 0.0
    behavior_mix_when: str = "carrier_or_spell"
    behavior_mix_max_per_turn: int = 6
    behavior_mix_topk: int = 8
    behavior_mix_turns: int = 1
    behavior_mix_max_ms: float = 500.0
    behavior_mix_exact: int = 1
    #: 动作序列辅助任务权重（turn 内动作 multi-hot 的 BCEWithLogits）；
    #: **0 = 关闭（默认）**：不构建 seq 头、不算 seq loss、stats 里不出现 seq 字段。
    #: 需要模型带 seq 头（``build_net(..., seq_head=True)``）且 batch 有 ``seq_target``。
    seq_coef: float = 0.0
    #: 权重 ramp 规格（``"0.02@0,0.05@0.5"``，按 decisions 进度线性插值）；由训练循环
    #: 每个 iteration 用它算出实际的 ``seq_coef`` 后写回本字段。空 = 用常数 ``seq_coef``。
    seq_coef_ramp: str = ""
    #: 真实人类对局（Firestone 回放）BC 辅助正则（形态 A：小权重辅助 CE）。
    #: **0 = 关闭（默认）**：不加载 BC 池、不编码、不采样、不算 loss，stats 里不出现
    #: ``bc_*`` 字段（与旧版本等价）。>0 时每个 minibatch 额外抽 ``bc_batch`` 条，
    #: 与 PPO 同一次 backward 相加：``total = ppo + seq + bc_coef * bc_ce``。
    bc_coef: float = 0.0
    #: BC 系数 ramp（与 ``seq_coef_ramp`` 同语法，直接复用 ``parse_coef_ramp``）；
    #: 由训练入口按累计 decisions 求值后写回 ``bc_coef``。空 = 用常数 ``bc_coef``。
    bc_coef_ramp: str = ""
    #: BC 样本 MMR 下限（低于该值直接丢弃）；默认 6000（人类中位约 6280）。
    bc_mmr_min: int = 6000
    #: MMR 线性增强（可选）：1.0=所有 mmr>=bc_mmr_min 权重相同；>1 时在
    #: [bc_mmr_min, 8000] 上从 1.0 线性升到该值（6000–8000 线性增强）。
    bc_mmr_boost: float = 1.0
    #: 稀有动作类别权重覆盖（``{"upgrade": 4.0, "hero_power": 2.0}``）：
    #: 在 class-balanced 权重之上再乘。空（默认）= 现状、零影响。
    bc_class_weights: Dict[str, float] = field(default_factory=dict)
    #: BC 样本 JSONL(.gz) 路径；空 = 用仓库默认
    #: ``data/firestone_bc/bc_samples.jsonl.gz``。
    bc_samples_path: str = ""
    #: 每个 PPO（微）minibatch 抽取并编码的 BC 样本数。
    #: 默认 128（原 256）：BC 前向与 PPO 主前向同图编译时，128 的固定形状更省时，
    #: 且实测分层 BC loss 与 256 无实质差异（见 docs/BC_AUX.md §12）。
    bc_batch: int = 128
    #: BC 采样周期：1=每个 PPO 微批都算（默认）；N>1 时每 N 个微批算一次 BC，
    #: 同时把该步的 BC 权重乘 N 以保持等效平均权重（``bc_coef * N``）。
    #: 跳过步完全不前向 ``forward_bc``、不占显存带宽，其他损失项逐位不变。
    bc_every: int = 1
    #: 分层 BC 的类型级 CE 权重（245 动作 logits 按类型 log-sum-exp 聚合后的 9 类 CE）。
    bc_type_weight: float = DEFAULT_BC_TYPE_WEIGHT
    #: 分层 BC 的卡牌身份级 CE 权重（buy/play 样本上的 3983 类 ``card_head``）；
    #: 0 = 不训练/不使用卡牌头（此时也不需要 ``bc_card_head``）。
    bc_card_weight: float = DEFAULT_BC_CARD_WEIGHT
    #: ``compile_train>0`` 时是否也把 BC 批次（固定 ``bc_batch`` 形状）单独编译。
    #: 1=编（默认，见 docs/TRAINING_COMPILE.md）；0=BC 保持 eager（A/B 基线）。
    bc_compile: int = 1
    #: upgrade 子集 one-sided DPO 正则（自我对比：chosen=人类 upgrade 动作，
    #: rejected=当前策略 masked argmax；见 docs/DPO_UPGRADE.md）。
    #: **0 = 关闭（默认）**：不加载 upgrade 池、不采样、不算 loss，stats 里不出现
    #: ``dpo_*`` 字段（与未接 DPO 的旧版本逐位等价）。>0 时每 ``dpo_every`` 个
    #: iteration 抽 ``dpo_batch`` 条 upgrade 样本，把 ``dpo_coef * dpo_pair_loss``
    #: 加进与 PPO 同一次 backward（``total += dpo_coef * dpo_loss``）。
    dpo_coef: float = 0.0
    #: one-sided DPO 的温度 β：``-logsigmoid(β·(logp_chosen − logp_rejected))``。
    #: 必须有限且 > 0（``dpo_pair_loss`` 的约束）。
    dpo_beta: float = 0.1
    #: 每个 DPO 步抽样的 upgrade 样本数（无放回）。
    dpo_batch: int = 128
    #: DPO 周期（按 **iteration** 计，不是按 PPO 微批）：每 N 个 iteration 做一次，
    #: 其余 iteration 完全不算 DPO（系数不做周期折算：开启步就是 ``dpo_coef``，
    #: 因此平均梯度占比 ≈ ``dpo_coef / dpo_every``；与 ``bc_every`` 的折算语义不同）。
    dpo_every: int = 4
    #: upgrade 样本池路径（默认仓库 ``data/firestone_bc/bc_samples.jsonl.gz``）：
    #: 只读 ``action_type=="upgrade"`` 的行（见 :mod:`hsbg.az.train.dpo_upgrade`）。
    dpo_samples: str = "data/firestone_bc/bc_samples.jsonl.gz"
    #: **场面题**监督（``docs/RESEARCH_PLAN_V2.md`` §4.1 / ``docs/BOARD_PROBLEMS.md``）：
    #: 在自对弈关键局面（每回合起点 + 决策分叉点）上用人类参考动作分布做 soft-label CE。
    #: **0 = 关闭（默认）**：不加载题目池、不采样、不前向新头、stats 里不出现
    #: ``problem_*`` 字段（与旧版逐位等价）。>0 时每个 iteration 抽 ``problem_batch``
    #: 道题，把 ``problem_bc_coef * CE_soft`` 加进同一次 backward。
    problem_bc_coef: float = 0.0
    #: 每 ``problem_every`` 个 iteration 抽一批题目（与 ``dpo_every`` 同语义：不做周期
    #: 折算，开步系数就是配置值，因此平均梯度占比 ≈ ``coef / every``）。
    problem_bc_every: int = 1
    #: 一批题目的行数（``problem_bc_coef`` 与 ``strength_aux_coef`` 共用同一批 + 同一次
    #: 前向，所以 B/C/D 三臂的题目状态完全一致）。
    problem_batch: int = 128
    #: 题目池路径（``scripts/build_board_problems.py`` 产出的 problems.jsonl）。
    problem_pool_path: str = ""
    #: **题目 turn 加权**（默认空 = 不加权，逐位等价）：``"10:2,12:3,14:4,15:4"``。
    #: 按题目 ``turn`` 给 soft-CE 加权（未列出的 turn 权重 1；权重 0 = 该 turn 的题从
    #: 池里剔除）。动机：``runs/plots/strength_stages.md`` 显示 t12 之后强度比几乎不变，
    #: 而参考解 52% 是 t6–t12 的升本 —— 把有限梯度从「升本」推到「后期做大随从」。
    #: 非法语法在构造期抛 ``ValueError``（不静默降级）。
    problem_turn_weight: str = ""
    #: **题目强度增量过滤**（默认 0 = 不过滤）：只保留
    #: ``label.strength_delta >= 阈值``（t+3 归一化强度增量 ``log1p(after)-log1p(before)``，
    #: 存活题 mean 1.231 / std 0.734）的题；过滤计数进 history 的
    #: ``problem_pool_dropped_by_delta``。必须有限且 >= 0。
    problem_min_strength_delta: float = 0.0
    #: **终局强度辅助头**（B10，entity 的 ``ceiling_head``）：从状态预测该局**终局**
    #: 盘面强度 ``log1p(Σatk+hp)``；用真实对局结果做监督（同一局所有决策共享目标）。
    #: 默认 0 = 关闭（前向/损失与旧版逐位一致）。每个 minibatch 只在前 256 行上算，
    #: 成本约为一次小前向。
    ceiling_aux_coef: float = 0.0

    #: **强度辅助头**（entity 的 ``strength_head``）：从状态预测 t+3 **战团强度增量**
    #: ``log1p(after)-log1p(before)``（z-score 回归）+ tier+1 是否达成（二分类）。
    #: **0 = 关闭（默认）**：不建头、
    #: 不前向、不算 loss、不改 checkpoint（旧 ckpt 自动无头）。
    strength_aux_coef: float = 0.0
    #: 强度辅助头的采样周期（按 iteration；与 ``problem_bc_every`` 独立）。
    strength_aux_every: int = 1
    #: tier+1 BCE 的正样本权重（默认 1.0；up 率偏低时可调大）。
    strength_tier_pos_weight: float = 1.0
    #: KL anchor 到 stage 起点的系数 β（论文 Table 7：0.1，前 100 个 iteration 后放开）。
    #: >0 时必须由 trainer 提供 anchor 分布（见 PPOTrainer.set_anchor）。
    anchor_coef: float = 0.0
    #: 在线缩放教师 DAgger 的 CE 系数（0=关闭，默认）。>0 时需要采集侧产出
    #: ``teacher_action``（``CollectConfig.teacher_bc=True``），CE 只在有标签的样本上算。
    teacher_bc_coef: float = 0.0
    #: 复利结构辅助 BC（0=关闭，默认）：在「Discover 选项含放大器/引擎卡」与
    #: 「商店能凑三连/对子的 buy 位」上加辅助交叉熵；标签由训练入口写入 batch
    #: （`discover_bc_idx/w`、`triple_bc_action/w`），**行为策略保持无偏**。
    discover_bc_coef: float = 0.0
    triple_bc_coef: float = 0.0
    # epoch 内自适应辅助系数；0 关闭，scale 跨 update 保留且不影响 warmup。
    bc_guard_ratio: float = 0.0
    discover_bc_scale: float = 1.0
    triple_bc_scale: float = 1.0
    #: 升级曲线辅助 BC（默认 0 = 不执行；guard 与 discover/triple 同一机制）
    upgrade_bc_coef: float = 0.0
    upgrade_bc_scale: float = 1.0
    #: upgrade BC 单独的 guard ratio：<0 表示沿用 bc_guard_ratio；0 = 不走 guard（固定系数）
    upgrade_bc_guard_ratio: float = -1.0
    #: 辅助 BC 的 CE **归一化**（除以合法动作数的 log；默认 False = 原始 CE）
    bc_ce_norm: bool = False
    #: 过程价值辅助头系数（0=关闭，默认）：预测 log1p(酒馆永久 buff 总和) /
    #: log1p(施法数) / log1p(consume 数)，只在目标可得的样本上算 MSE。
    process_value_coef: float = 0.0
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
    #: ── 信用分配（§B，默认 gae = 旧路径逐位等价）──
    #: ``gae`` | ``power`` | ``geom``。只有 != gae 时才改 advantage 核；
    #: gae 路径仍调用旧 ``compute_gae``，不新增 records/meta 键。
    adv_estimator: str = "gae"
    #: 幂率核 ``w_l=(1+l/κ)^(−α)`` 的参数（默认关闭时不影响任何计算）。
    power_alpha: float = 0.5
    power_kappa: float = 3.0
    #: horizon 归一化（§B.1）。离线诊断显示 normalize=1 会把早期 |A| 压成 ~1/L，
    #: 实际 A/B 建议用 0（PPO loss 内仍会做全局 advantage normalization）。
    power_normalize: bool = True
    #: lag 截断（0=不截断）。
    power_cutoff: int = 0
    #: ``decision`` | ``turn``；turn 模式使用未来 elapsed turn 的 SMDP 折扣。
    credit_timebase: str = "decision"
    #: 动作条件 baseline 安全边界：**actor baseline 只用 V(s)**，默认 0。
    #: 非 0 直接报错（Q(s,a) 只允许进 critic/TD loss，不能直接当 PG baseline）。
    baseline_action_dependent: int = 0
    max_grad_norm: float = 0.5
    device: str = "cpu"
    seed: int = 0
    max_samples: Optional[int] = None
    log_every: int = 0

    def __post_init__(self) -> None:
        mode = str(self.value_loss).strip().lower()
        if mode not in ("rank", "mse"):
            raise ValueError(f"value_loss 只能是 rank|mse，得到 {self.value_loss!r}")
        # ── 信用分配（§B）：默认 gae；非法参数在构造期早失败 ──
        self.adv_estimator = str(self.adv_estimator).strip().lower()
        if self.adv_estimator not in ("gae", "power", "geom"):
            raise ValueError(
                f"adv_estimator 只能是 gae|power|geom，得到 {self.adv_estimator!r}")
        if int(self.baseline_action_dependent) != 0:
            raise ValueError(
                "baseline_action_dependent 必须为 0：动作条件 Q(s,a) 只允许进 "
                "critic/TD loss 与 A=Q−V；直接当 actor baseline 有偏（§B.3）")
        if self.adv_estimator in ("power", "geom"):
            if not math.isfinite(float(self.power_alpha)) or float(self.power_alpha) < 0.0:
                raise ValueError(f"power_alpha 必须 >= 0，得到 {self.power_alpha!r}")
            if not math.isfinite(float(self.power_kappa)) or float(self.power_kappa) <= 0.0:
                raise ValueError(f"power_kappa 必须 > 0，得到 {self.power_kappa!r}")
            if int(self.power_cutoff) < 0:
                raise ValueError(f"power_cutoff 必须 >= 0，得到 {self.power_cutoff!r}")
        self.credit_timebase = str(self.credit_timebase).strip().lower()
        if self.credit_timebase not in ("decision", "turn"):
            raise ValueError(
                f"credit_timebase 只能是 decision|turn，得到 {self.credit_timebase!r}")
        if self.credit_timebase == "turn" and self.adv_estimator == "gae":
            raise ValueError("credit_timebase=turn 需要 adv_estimator=power|geom")
        self.value_loss = mode
        self.compile_train = compile_train_mode(self.compile_train)
        self.anchor_amp = bool(self.anchor_amp)
        self.bc_compile = bool(int(self.bc_compile))
        # 早失败：ramp 规格写错时不要等到训练循环里才炸
        if str(self.seq_coef_ramp or "").strip():
            parse_coef_ramp(self.seq_coef_ramp)
        if float(self.seq_coef) < 0.0:
            raise ValueError(f"seq_coef 必须 >= 0，得到 {self.seq_coef!r}")
        # BC 辅助正则（默认关闭）：同样在构造期校验 ramp/系数
        if str(self.bc_coef_ramp or "").strip():
            parse_bc_coef_ramp(self.bc_coef_ramp)
        if float(self.bc_coef) < 0.0:
            raise ValueError(f"bc_coef 必须 >= 0，得到 {self.bc_coef!r}")
        if int(self.bc_batch) <= 0:
            raise ValueError(f"bc_batch 必须 > 0，得到 {self.bc_batch!r}")
        if int(self.bc_every) <= 0:
            raise ValueError(f"bc_every 必须 >= 1，得到 {self.bc_every!r}")
        if int(self.bc_mmr_min) < 0:
            raise ValueError(f"bc_mmr_min 必须 >= 0，得到 {self.bc_mmr_min!r}")
        if float(self.bc_mmr_boost) < 1.0:
            raise ValueError(
                f"bc_mmr_boost 必须 >= 1，得到 {self.bc_mmr_boost!r}")
        # 稀有动作类别权重覆盖：键必须在 9 类白名单内，值有限且 > 0
        for _name, _value in dict(self.bc_class_weights or {}).items():
            if str(_name) not in BC_ACTION_TYPES:
                raise ValueError(
                    f"bc_class_weights 含未知类别 {_name!r}；可选: {BC_ACTION_TYPES}")
            _v = float(_value)
            if not math.isfinite(_v) or _v <= 0.0:
                raise ValueError(
                    f"bc_class_weights[{_name!r}] 必须是有限正数，得到 {_v!r}")
        self.bc_class_weights = {
            str(k): float(v) for k, v in dict(self.bc_class_weights or {}).items()}
        if float(self.bc_type_weight) < 0.0:
            raise ValueError(
                f"bc_type_weight 必须 >= 0，得到 {self.bc_type_weight!r}")
        if float(self.bc_card_weight) < 0.0:
            raise ValueError(
                f"bc_card_weight 必须 >= 0，得到 {self.bc_card_weight!r}")
        # upgrade DPO（默认关闭）：构造期校验系数/β/批量/周期
        if not math.isfinite(float(self.dpo_coef)) or float(self.dpo_coef) < 0.0:
            raise ValueError(f"dpo_coef 必须 >= 0，得到 {self.dpo_coef!r}")
        if not math.isfinite(float(self.dpo_beta)) or float(self.dpo_beta) <= 0.0:
            raise ValueError(f"dpo_beta 必须是有限正数，得到 {self.dpo_beta!r}")
        if int(self.dpo_batch) <= 0:
            raise ValueError(f"dpo_batch 必须 > 0，得到 {self.dpo_batch!r}")
        if int(self.dpo_every) <= 0:
            raise ValueError(f"dpo_every 必须 >= 1，得到 {self.dpo_every!r}")
        # 场面题监督 / 强度辅助头（默认关闭）：构造期校验系数/批量/周期
        for _name in ("problem_bc_coef", "strength_aux_coef"):
            _v = float(getattr(self, _name) or 0.0)
            if not math.isfinite(_v) or _v < 0.0:
                raise ValueError(f"{_name} 必须 >= 0，得到 {_v!r}")
        # 缩放教师 DAgger / 过程价值辅助（默认关闭）：系数必须有限且 >= 0
        for _name in ("teacher_bc_coef", "process_value_coef"):
            _v = float(getattr(self, _name) or 0.0)
            if not math.isfinite(_v) or _v < 0.0:
                raise ValueError(f"{_name} 必须 >= 0，得到 {_v!r}")
        _ruc = float(getattr(self, "rank_utility_coef", 1.0) or 0.0)
        if not math.isfinite(_ruc) or _ruc < 0.0:
            raise ValueError(f"rank_utility_coef 必须 >= 0，得到 {_ruc!r}")
        _tsc = float(getattr(self, "terminal_strength_coef", 0.0) or 0.0)
        if not math.isfinite(_tsc) or _tsc < 0.0:
            raise ValueError(f"terminal_strength_coef 必须 >= 0，得到 {_tsc!r}")
        for _name in ("problem_bc_every", "strength_aux_every", "problem_batch"):
            if int(getattr(self, _name) or 0) <= 0:
                raise ValueError(f"{_name} 必须 >= 1，得到 {getattr(self, _name)!r}")
        if not math.isfinite(float(self.strength_tier_pos_weight)) or \
                float(self.strength_tier_pos_weight) <= 0.0:
            raise ValueError("strength_tier_pos_weight 必须是有限正数，得到 "
                             f"{self.strength_tier_pos_weight!r}")
        # 题目池开关（默认关闭）：turn 权重语法与强度增量阈值**构造期校验**
        thr = float(self.problem_min_strength_delta)
        if not math.isfinite(thr) or thr < 0.0:
            raise ValueError(
                f"problem_min_strength_delta 必须有限且 >= 0，得到 "
                f"{self.problem_min_strength_delta!r}")
        if str(self.problem_turn_weight or "").strip():
            from .board_problems import parse_turn_weights  # noqa: PLC0415
            parse_turn_weights(self.problem_turn_weight)  # 非法语法直接 ValueError


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
BATCH_OPTIONAL_FIELDS: Tuple[str, ...] = (
    SEQ_TARGET_KEY, "teacher_action", "process_target",
    #: 搜索行为混合（μ=(1−ε)π+ε·π_search）的 logprob：存在才写/读 npz。
    "behavior_logprobs", "pi_logprobs")


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
    #: 在线缩放教师标签 int16[n]（-1 = 无标签）；None = 未启用（默认）
    teacher_action: Optional[np.ndarray] = None
    #: 过程价值目标 f32[n,3]（log1p：酒馆永久 buff / 施法数 / consume 数；
    #: 不可得行为 NaN）；None = 未启用（默认）
    process_target: Optional[np.ndarray] = None
    #: 搜索行为策略 μ 的 logprob f32[n]（``log((1−ε)π+ε·π_search)``）。启用时 PPO 的
    #: ratio 分母用它；None = 未启用（默认）= 用 ``old_logprobs``（π_old）。
    behavior_logprobs: Optional[np.ndarray] = None
    #: 同一动作在 π（采集策略）下的 logprob f32[n]；KL/approx_kl 口径用。None = 未启用。
    pi_logprobs: Optional[np.ndarray] = None
    #: 该局**终局盘面强度** log1p(Σatk+hp) f32[n]（B10 的"上限"辅助头目标 0）；
    #: 同一局所有决策共享同一个值。None = 未启用（默认）
    final_strength: Optional[np.ndarray] = None
    #: 该局**终局 tier / 6** f32[n]（B10 的"上限"辅助头目标 1）。None = 未启用
    final_tier: Optional[np.ndarray] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.forced is None:
            self.forced = np.zeros(len(self.actions), dtype=bool)
        else:
            self.forced = np.asarray(self.forced, dtype=bool).reshape(-1)
        if self.seq_target is not None:
            self.seq_target = np.asarray(self.seq_target, dtype=np.uint8)
        if self.teacher_action is not None:
            self.teacher_action = np.asarray(self.teacher_action, dtype=np.int16).reshape(-1)
        if self.process_target is not None:
            self.process_target = np.asarray(self.process_target, dtype=np.float32)
        if self.final_strength is not None:
            self.final_strength = np.asarray(
                self.final_strength, dtype=np.float32).reshape(-1)
        if self.final_tier is not None:
            self.final_tier = np.asarray(
                self.final_tier, dtype=np.float32).reshape(-1)
        if self.behavior_logprobs is not None:
            self.behavior_logprobs = np.asarray(
                self.behavior_logprobs, dtype=np.float32).reshape(-1)
        if self.pi_logprobs is not None:
            self.pi_logprobs = np.asarray(
                self.pi_logprobs, dtype=np.float32).reshape(-1)

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
        if self.teacher_action is not None:
            ta = np.asarray(self.teacher_action).reshape(-1)
            if ta.size != n:
                errs.append(f"teacher_action: len {ta.size} != {n}")
            elif n:
                bad = (ta < -1) | (ta >= N_ACTIONS)
                if bad.any():
                    errs.append(f"teacher_action 越界: {int(bad.sum())} 条")
                else:
                    ok = ta >= 0
                    legal = self.masks[np.arange(n)[ok], ta[ok].astype(np.int64)]
                    if not bool(legal.all()):
                        errs.append("teacher_action 含非法动作")
        if self.process_target is not None:
            pt = np.asarray(self.process_target)
            if tuple(pt.shape) != (n, 3):
                errs.append(f"process_target: shape {tuple(pt.shape)} != {(n, 3)}")
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
        if self.behavior_logprobs is not None:
            bl = np.asarray(self.behavior_logprobs).reshape(-1)
            if bl.size != n:
                errs.append(f"behavior_logprobs: len {bl.size} != {n}")
            elif not np.isfinite(bl).all():
                errs.append("behavior_logprobs 含 NaN/Inf")
        if self.pi_logprobs is not None:
            pl = np.asarray(self.pi_logprobs).reshape(-1)
            if pl.size != n:
                errs.append(f"pi_logprobs: len {pl.size} != {n}")
            elif not np.isfinite(pl).all():
                errs.append("pi_logprobs 含 NaN/Inf")
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
        if self.behavior_logprobs is not None:
            # 搜索行为混合：IS 权重 r=π/μ 的分布（原始权重，不含 clip），报告 ESS
            bl = np.asarray(self.behavior_logprobs, dtype=np.float64)
            valid = ~np.asarray(self.forced, dtype=bool)
            if valid.any():
                lw = np.asarray(self.old_logprobs, dtype=np.float64)[valid] - bl[valid]
                w = np.exp(np.clip(lw, -50.0, 50.0))
                sw = float(w.sum())
                out["behavior_mix"] = {
                    "rate": float(valid.mean()),
                    "logp_mu_mean": float(bl[valid].mean()),
                    "logp_pi_mean": float(np.asarray(
                        self.old_logprobs, dtype=np.float64)[valid].mean()),
                    "weight_mean": sw / max(int(valid.sum()), 1),
                    "weight_max": float(w.max()) if w.size else 0.0,
                    "weight_p50": float(np.median(w)) if w.size else 0.0,
                    "weight_p95": float(np.percentile(w, 95)) if w.size else 0.0,
                    "ess_ratio": (sw * sw / max(float((w * w).sum()), 1e-12)
                                  / max(int(valid.sum()), 1)),
                }
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


def _episode_advantage_weights(game_ids: Any, seats: Any, turns: Any,
                               strengths: Any, *, alpha: float = 0.5,
                               beta: float = 0.5, floor: float = 0.5,
                               cap: float = 2.0) -> Tuple[np.ndarray, Dict[str, Any]]:
    """按 episode（game_id, seat）算「对局长度 + 对手强度」权重（均值归一到 1）。

    - 长度 = 该局最大 turn；强度 = 该局对手最强盘面 Σ（采集端挂在每条记录的
      ``game_bot_strength`` 上）。
    - 权重规则完全复用 ``hsbg.eval.metrics.game_weights``（评测口径），保证训练/评测一致。
    - 返回 (per-decision 权重, 统计 dict)；mode 关闭时调用方不会进这里。
    """
    gid = np.asarray(game_ids, dtype=np.int64).reshape(-1)
    sea = np.asarray(seats, dtype=np.int64).reshape(-1)
    trn = np.asarray(turns, dtype=np.float32).reshape(-1)
    strg = np.asarray(strengths, dtype=np.float32).reshape(-1)
    n = int(gid.size)
    if n == 0 or sea.size != n or trn.size != n or strg.size != n:
        return np.ones(max(n, 0), dtype=np.float32), {"n_episodes": 0, "skipped": 1}
    key = gid * np.int64(256) + sea
    change = np.empty(n, dtype=bool)
    change[0] = True
    change[1:] = key[1:] != key[:-1]
    ep_index = np.cumsum(change) - 1
    n_ep = int(ep_index[-1]) + 1
    ep_turns = np.zeros(n_ep, dtype=np.float64)
    ep_str = np.zeros(n_ep, dtype=np.float64)
    np.maximum.at(ep_turns, ep_index, trn.astype(np.float64))
    np.maximum.at(ep_str, ep_index, strg.astype(np.float64))
    w = np.asarray(game_weights(ep_turns.tolist(), ep_str.tolist(),
                                alpha=float(alpha), beta=float(beta),
                                floor=float(floor), cap=float(cap)),
                   dtype=np.float32)
    stats = {
        "mode": "adv", "n_episodes": int(n_ep),
        "alpha": float(alpha), "beta": float(beta),
        "floor": float(floor), "cap": float(cap),
        "w_mean": float(w.mean()), "w_min": float(w.min()), "w_max": float(w.max()),
        "turns_p50": float(np.median(ep_turns)),
        "strength_p50": float(np.median(ep_str)),
        "strength_all_zero": bool(float(ep_str.max()) <= 0.0),
    }
    return w[ep_index].astype(np.float32), stats


def build_batch_from_records(records: List[Dict[str, Any]], *,
                             gamma: float = 1.0, lam: float = 0.95,
                             step_penalty: float = 0.0,
                             meta: Optional[Dict[str, Any]] = None,
                             seq_aux: bool = False,
                             adv_estimator: str = "gae",
                             power_alpha: float = 0.5,
                             power_kappa: float = 3.0,
                             power_normalize: bool = True,
                             power_cutoff: int = 0,
                             credit_timebase: str = "decision",
                             rank_utility_coef: float = 1.0,
                             terminal_strength_coef: float = 0.0,
                             game_weight_mode: str = "none",
                             game_weight_alpha: float = 0.5,
                             game_weight_beta: float = 0.5,
                             game_weight_floor: float = 0.5,
                             game_weight_cap: float = 2.0) -> PPOBatch:
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
    _gstrength = np.asarray([float(r.get("game_bot_strength", 0.0) or 0.0)
                              for r in recs], dtype=np.float32)

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

    # 按 episode（game_id, seat 已连续）写 reward/done。
    # 可选逐决策 reward（势函数塑形）作为基础项；缺字段时与旧路径逐位一致。
    has_reward = any("reward" in r for r in recs)
    rewards = np.full(n, -float(step_penalty), dtype=np.float32)
    if has_reward:
        rewards += np.asarray([float(r.get("reward", 0.0)) for r in recs],
                              dtype=np.float32)
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
        rewards[last] = (float(rank_utility_coef)
                         * float(utility_from_rank([int(ranks[last])])[0])
                         - float(step_penalty))
        if float(terminal_strength_coef) != 0.0:
            rewards[last] += (float(terminal_strength_coef)
                              * float(log_strength_from_features(
                                  features[last:last + 1])[0]))
        if has_reward:
            rewards[last] += float(recs[last].get("reward", 0.0))
        dones[last] = 1.0
        ep += 1
        start = end

    advantages, returns = compute_gae(rewards, values, dones, gamma=gamma, lam=lam)
    merged_meta: Dict[str, Any] = dict(meta or {})
    merged_meta.update({
        "gamma": float(gamma), "lam": float(lam), "step_penalty": float(step_penalty),
        "dropped_unknown_rank": int(dropped), "episodes": int(ep),
    })
    adv_mode = str(adv_estimator).strip().lower()
    if adv_mode not in ("gae", "", "geom", "power"):
        raise ValueError(f"adv_estimator 只能是 gae|power|geom，得到 {adv_estimator!r}")
    if adv_mode not in ("gae", ""):
        # 幂率/几何核：替换 GAE 内部时间核；GAE 默认路径完全不进这里，
        # records/meta 与旧版逐位一致（见 docs/CREDIT_ASSIGNMENT.md）。
        mode = "geom" if adv_mode == "geom" else "power"
        advantages, returns, _diag = compute_credit(
            rewards, values, dones, mode=mode, gamma=float(gamma),
            lam=float(lam), alpha=float(power_alpha),
            kappa=float(power_kappa), cutoff=int(power_cutoff),
            normalize=bool(power_normalize),
            timebase=str(credit_timebase), turns=turns)
        merged_meta.update({
            "adv_estimator": mode,
            "credit": compact_diagnostics(_diag),
        })
    # 动作序列辅助标签：同 (game_id, seat, turn) 的动作集合 = multi-hot(245) uint8。
    # 只在 seq_aux=True 时构造（默认关闭 -> 批次字段/内存与旧路径完全一致）。
    seq_target = (seq_targets_from_records(recs) if seq_aux else None)
    if seq_target is not None:
        merged_meta["seq_aux"] = True
    # 在线缩放教师标签 / 过程价值目标（记录里出现才产出；默认关闭 -> None）
    teacher_action = None
    if any("teacher_action" in r for r in recs):
        teacher_action = np.asarray(
            [int(r.get("teacher_action", -1)) for r in recs], dtype=np.int16)
        merged_meta["teacher_aux"] = True
    process_target = None
    if any("process_target" in r for r in recs):
        rows = []
        for r in recs:
            pt = r.get("process_target")
            if pt is None:
                rows.append([np.nan, np.nan, np.nan])
            else:
                rows.append([float(x) for x in np.asarray(pt, dtype=np.float32).reshape(3)])
        process_target = np.asarray(rows, dtype=np.float32)
        merged_meta["process_aux"] = True
    # 搜索行为混合（μ=(1−ε)π+ε·π_search）：记录里有 logp_mu 才产出
    behavior_logprobs = None
    pi_logprobs = None
    if any("logp_mu" in r for r in recs):
        behavior_logprobs = np.asarray(
            [float(r.get("logp_mu", r["old_logprob"])) for r in recs], dtype=np.float32)
        pi_logprobs = np.asarray(
            [float(r.get("logp_pi", r["old_logprob"])) for r in recs], dtype=np.float32)
        merged_meta["behavior_mix"] = True
    if str(game_weight_mode) != "none":
        _w, _wstats = _episode_advantage_weights(
            game_ids, seats, turns, _gstrength,
            alpha=float(game_weight_alpha), beta=float(game_weight_beta),
            floor=float(game_weight_floor), cap=float(game_weight_cap))
        advantages = (np.asarray(advantages, dtype=np.float32) * _w).astype(np.float32)
        merged_meta["game_weight"] = _wstats
    return PPOBatch(
        features=features, cards=cards, masks=masks, actions=actions,
        old_logprobs=old_logprobs, values=values, rewards=rewards, dones=dones,
        advantages=advantages, returns=returns, seats=seats, game_ids=game_ids,
        ranks=ranks, turns=turns, target_pi=target_pi, has_pi=has_pi,
        episode_ids=episode_ids, forced=forced, seq_target=seq_target,
        teacher_action=teacher_action, process_target=process_target,
        behavior_logprobs=behavior_logprobs, pi_logprobs=pi_logprobs,
        final_strength=(
            np.asarray([float(r.get("final_strength", 0.0) or 0.0) for r in recs],
                       dtype=np.float32)
            if any("final_strength" in r for r in recs) else None),
        final_tier=(
            np.asarray([float(r.get("final_tier", 0.0) or 0.0) for r in recs],
                       dtype=np.float32)
            if any("final_tier" in r for r in recs) else None),
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


def forward_bc_model(model: Any, features: Any, cards: Any, mask: Any = None):
    """分层 BC 的一次前向：``(policy_logits, card_logits|None)``。

    优先走模型的 ``forward_bc``（tiny/entity 都有；一次 forward 同时出两个头）；
    老模型/测试替身没有该方法时退回 ``forward_model``（card_logits=None，只算类型级）。
    只有 ``bc_coef>0`` 的分支调用它，默认关闭时前向路径完全不变。
    """
    fn = getattr(model, "forward_bc", None)
    if fn is not None:
        out = fn(features, cards, mask) if _accepts_mask_aux(model, "forward_bc") \
            else fn(features, cards)
        if not isinstance(out, (tuple, list)) or len(out) != 2:
            raise ValueError("forward_bc 必须返回 (policy_logits, card_logits|None)")
        return out[0], out[1]
    logits, _rank_logits, _scalar = split_model_outputs(
        forward_model(model, features, cards, mask))
    return logits, None


def forward_problem_model(model: Any, features: Any, cards: Any, mask: Any = None):
    """场面题的一次前向：``(policy_logits, strength_pred|None)``。

    优先走模型的 ``forward_problem``（entity 带 ``strength_head`` 时提供；一次 forward
    同时出策略头与强度头）。老模型/测试替身没有该方法时退回 ``forward_model``
    （``strength_pred=None``，只有 ``problem_bc_coef>0`` 时仍可用）。
    只有 ``problem_bc_coef>0`` 或 ``strength_aux_coef>0`` 的分支调用它。
    """
    fn = getattr(model, "forward_problem", None)
    if fn is not None:
        out = fn(features, cards, mask) if _accepts_mask_aux(model, "forward_problem") \
            else fn(features, cards)
        if not isinstance(out, (tuple, list)) or len(out) != 2:
            raise ValueError("forward_problem 必须返回 (policy_logits, strength_pred|None)")
        return out[0], out[1]
    logits, _rank_logits, _scalar = split_model_outputs(
        forward_model(model, features, cards, mask))
    return logits, None


def forward_process_model(model: Any, features: Any, cards: Any, mask: Any = None):
    """过程价值头的一次前向：``(policy_logits, process_pred|None)``。

    优先走模型的 ``forward_process``（entity 带 ``process_head`` 时提供；一次 forward
    同时出策略头与过程头）。老模型/测试替身没有该方法时退回 ``forward_model``
    （``process_pred=None``）。只有 ``process_value_coef>0`` 的分支调用它。

    **不影响策略前向**：``forward()`` / ``forward_aux()`` / ``forward_bc()`` /
    ``forward_problem()`` 的返回值与不带该头时完全一致。
    """
    fn = getattr(model, "forward_process", None)
    if fn is not None:
        out = fn(features, cards, mask) if _accepts_mask_aux(model, "forward_process") \
            else fn(features, cards)
        if not isinstance(out, (tuple, list)) or len(out) != 2:
            raise ValueError("forward_process 必须返回 (policy_logits, process_pred|None)")
        return out[0], out[1]
    logits, _rank_logits, _scalar = split_model_outputs(
        forward_model(model, features, cards, mask))
    return logits, None


def _accepts_mask_aux(model: Any, name: str = "forward_aux") -> bool:
    """``forward_aux``/``forward_bc`` 是否吃 mask（tiny/entity 都接受 ``mask``）。"""
    import inspect

    fn = getattr(model, name, None)
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
                 device: str = "cpu", use_amp: bool = False,
                 bc_batch: int = 0) -> None:
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
        self.accepts_mask_bc = _accepts_mask_aux(model, "forward_bc")
        self.has_aux = getattr(model, "forward_aux", None) is not None
        self.has_bc = getattr(model, "forward_bc", None) is not None
        self._main_fn: Any = None
        self._aux_fn: Any = None
        self._bc_fn: Any = None
        self.main_compiled = False
        self.aux_compiled = False
        self.bc_compiled = False
        #: BC 编译图的固定 batch（= ``bc_batch``；0=未知，任何形状都走 eager）
        self.bc_size = int(bc_batch or 0)
        self.warnings: List[str] = []
        self.eager_calls = 0
        self.compiled_calls = 0
        self.bc_calls = 0
        self.bc_eager_calls = 0
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

    def _raw_bc(self, x: Any, c: Any, m: Any):
        """eager 版 ``forward_bc``（与 ``forward_bc_model`` 的分支逐位一致）。"""
        fn = getattr(self.model, "forward_bc", None)
        if fn is None:  # 老模型/测试替身：只有类型级（card_logits=None）
            logits, _rank_logits, _scalar = split_model_outputs(self._raw_main(x, c, m))
            return logits, None
        if self.accepts_mask_bc:
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
        fn_raw = {"main": self._raw_main, "aux": self._raw_aux,
                  "bc": self._raw_bc}[kind]
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
        elif kind == "bc":
            self._bc_fn, self.bc_compiled = fn, True
        else:
            self._aux_fn, self.aux_compiled = fn, True
        return True

    def warmup(self, *, need_aux: bool = False, need_bc: bool = False,
               batch_size: Optional[int] = None,
               bc_batch: Optional[int] = None,
               backward: bool = True, verbose: bool = True) -> "TrainForward":
        """固定形状 warmup（forward+backward 各一次）：把编译开销挪到训练计时之外。

        ``need_bc=True`` 时额外为 BC 批次（固定 ``bc_batch`` 形状）编一张独立图：
        BC 批次通常远小于 PPO minibatch（128 vs 1024），复用主图会触发重编译。
        """
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
        if need_bc:
            bmb = max(1, int(bc_batch or self.bc_size or 1))
            if not self.has_bc:
                self._warn("bc", RuntimeError(
                    "模型没有 forward_bc，BC 路径保持 eager（只算类型级）"))
            else:
                bc_warm = (torch.zeros((bmb, OBS_FLOATS), dtype=torch.float32, device=d),
                           torch.zeros((bmb, OBS_CARDS), dtype=torch.long, device=d),
                           torch.ones((bmb, N_ACTIONS), dtype=torch.bool, device=d))
                if self._warm_one("bc", *bc_warm, backward=backward):
                    self.bc_size = bmb
        self.warmup_seconds = time.time() - t0
        if verbose:
            print(f"[ppo] train compile mode={self.mode} "
                  f"main={'on' if self.main_compiled else 'eager'} "
                  f"aux={'on' if self.aux_compiled else ('eager' if need_aux else 'off')} "
                  f"bc={'on' if self.bc_compiled else ('eager' if need_bc else 'off')}"
                  f"{f'(B={self.bc_size})' if self.bc_compiled else ''} "
                  f"warmup={self.warmup_seconds:.1f}s"
                  + (f" warnings={len(self.warnings)}" if self.warnings else ""),
                  flush=True)
        return self

    # ── 训练调用入口 ───────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return bool(self.main_compiled or self.aux_compiled or self.bc_compiled)

    def _size_ok(self, n: int, kind: str = "main") -> bool:
        want = self.bc_size if kind == "bc" else self.minibatch
        return want <= 0 or int(n) == want

    def _call(self, kind: str, x: Any, c: Any, m: Any):
        if kind == "main":
            compiled, fn, raw = self.main_compiled, self._main_fn, self._raw_main
        elif kind == "aux":
            compiled, fn, raw = self.aux_compiled, self._aux_fn, self._raw_aux
        else:
            compiled, fn, raw = self.bc_compiled, self._bc_fn, self._raw_bc
        if compiled and self._size_ok(int(x.shape[0]), kind):
            try:
                if kind == "bc":
                    self.bc_calls += 1
                else:
                    self.compiled_calls += 1
                return fn(x, c, m)
            except Exception as exc:  # noqa: BLE001 - 运行期失败同样回退 eager
                self._warn(kind, exc)
                if kind == "main":
                    self.main_compiled, self._main_fn = False, None
                elif kind == "aux":
                    self.aux_compiled, self._aux_fn = False, None
                else:
                    self.bc_compiled, self._bc_fn = False, None
        if kind == "bc":
            self.bc_eager_calls += 1
        else:
            self.eager_calls += 1
        return raw(x, c, m)

    def main(self, x: Any, c: Any, m: Any):
        """训练主前向 ``(logits, rank_logits[, value])``。"""
        return self._call("main", x, c, m)

    def aux(self, x: Any, c: Any, m: Any):
        """训练辅前向 ``(logits, rank_logits, value|None, seq_logits|None)``。"""
        return self._call("aux", x, c, m)

    def bc(self, x: Any, c: Any, m: Any):
        """分层 BC 前向 ``(policy_logits, card_logits|None)``（独立固定形状图）。"""
        return self._call("bc", x, c, m)

    def describe(self) -> Dict[str, Any]:
        """进 stats 的诊断信息（可 JSON 序列化）。"""
        return {
            "mode": int(self.mode),
            "active": bool(self.active),
            "main_compiled": bool(self.main_compiled),
            "aux_compiled": bool(self.aux_compiled),
            "bc_compiled": bool(self.bc_compiled),
            "bc_batch": int(self.bc_size),
            "warmup_s": round(float(self.warmup_seconds), 3),
            "compiled_calls": int(self.compiled_calls),
            "eager_calls": int(self.eager_calls),
            "bc_calls": int(self.bc_calls),
            "bc_eager_calls": int(self.bc_eager_calls),
            "warnings": list(self.warnings),
        }


def build_train_forward(model: Any, config: Any = None, *,
                        minibatch: Optional[int] = None,
                        warmup: bool = True, need_aux: Optional[bool] = None,
                        need_bc: Optional[bool] = None,
                        bc_batch: Optional[int] = None,
                        use_amp: Optional[bool] = None,
                        warmup_backward: bool = True,
                        verbose: bool = True) -> Optional[TrainForward]:
    """按 ``PPOConfig.compile_train`` 构建训练侧编译包装；0=返回 ``None``（纯 eager）。

    ``need_aux`` 默认由 ``seq_coef>0`` 或 ``seq_coef_ramp`` 非空推断（seq 辅助任务路径
    走 ``forward_aux``，需要单独编译）。``need_bc`` 默认由 ``bc_coef>0`` 或
    ``bc_coef_ramp`` 非空推断，并按 ``bc_batch`` 固定形状单独编译一张 BC 图。
    ``minibatch``/``use_amp`` 可覆盖配置（anchor 参考前向用固定 chunk + 自己的精度
    口径）；``warmup_backward=False`` 用于 no_grad 的 anchor 参考前向（只编 forward 图）。
    """
    cfg = config if config is not None else PPOConfig()
    mode = compile_train_mode(getattr(cfg, "compile_train", 0))
    if mode <= 0:
        return None
    if need_aux is None:
        need_aux = (float(getattr(cfg, "seq_coef", 0.0) or 0.0) > 0.0
                    or bool(str(getattr(cfg, "seq_coef_ramp", "") or "").strip()))
    if need_bc is None:
        bc_on = (float(getattr(cfg, "bc_coef", 0.0) or 0.0) > 0.0
                 or bool(str(getattr(cfg, "bc_coef_ramp", "") or "").strip()))
        need_bc = bool(bc_on and int(getattr(cfg, "bc_batch", 0) or 0) > 0
                       and bool(getattr(cfg, "bc_compile", True)))
    if use_amp is None:
        amp = str(getattr(cfg, "amp", "off")).strip().lower()
        use_amp = amp in ("bf16", "bfloat16")
    bsz = (int(bc_batch) if bc_batch is not None
           else int(getattr(cfg, "bc_batch", 0) or 0))
    tf = TrainForward(
        model, mode=mode,
        minibatch=(int(minibatch) if minibatch is not None
                   else int(getattr(cfg, "minibatch", 0) or 0)),
        device=str(getattr(cfg, "device", "cpu")),
        use_amp=bool(use_amp), bc_batch=bsz)
    if warmup:
        tf.warmup(need_aux=bool(need_aux), need_bc=bool(need_bc),
                  bc_batch=bsz, backward=bool(warmup_backward),
                  verbose=verbose)
    return tf


# ══════════════════════════════════════════════════════════════════════════
# 6. PPO loss / 训练
# ══════════════════════════════════════════════════════════════════════════
def replication_bc_ce(logp, mask, indices, weights, valid, *, normalize=False,
                      row_weight=False):
    """合法目标上的加权 -log p；可选除以 log(合法动作数)，均匀策略基线为 1。

    不除以选项数：那会随动作空间增大任意缩小梯度。Discover 行内归一化目标价值，
    triple 则保留行间 2:1 权重；非法/越界/forced 标签均不参与。
    """
    torch = _torch()
    inside = (indices >= 0) & (indices < logp.shape[1])
    safe = indices.clamp(0, logp.shape[1] - 1)
    legal = inside & mask.gather(1, safe)
    w = torch.where(legal & torch.isfinite(weights), weights.clamp_min(0),
                    torch.zeros_like(weights))
    mass = w.sum(dim=1)
    rows = (mass > 0) & (valid > 0)
    count = int(rows.sum().item())
    if not count:
        return logp.sum() * 0.0, 0
    selected = logp.gather(1, safe)
    per = -(selected * w).sum(dim=1) / mass.clamp_min(1e-8)
    if normalize:
        per = per / mask.sum(dim=1).clamp_min(2).to(logp.dtype).log()
    rw = mass[rows] if row_weight else torch.ones_like(mass[rows])
    return (per[rows] * rw).sum() / rw.sum(), count


def replication_bc_guard(coef, bc_loss, policy_loss, *, ratio=0.3, eps=1e-8):
    """每 epoch 调整一次；PPO surrogate 可为负，因此比较其绝对量级。"""
    if coef <= 0 or ratio <= 0:
        return float(coef), 0.0
    r = float(coef) * max(0.0, float(bc_loss)) / max(abs(float(policy_loss)), eps)
    if r > ratio:
        coef = max(1e-6, coef * 0.5)
    elif r < 0.05:
        coef = min(1e-3, coef * 1.5)
    return float(coef), r


def ppo_losses(model: Any, batch: PPOBatch, config: PPOConfig,
               indices: Optional[np.ndarray] = None,
               anchor_logp: Any = None,
               train_forward: Optional[TrainForward] = None,
               bc_batch: Optional[BCObsBatch] = None,
               bc_coef_override: Optional[float] = None,
               dpo_batch: Optional[UpgradeSamples] = None,
               dpo_coef_override: Optional[float] = None,
               problem_batch: Optional[Any] = None,
               problem_bc_coef_override: Optional[float] = None,
               strength_aux_coef_override: Optional[float] = None
               ) -> Dict[str, Any]:
    """计算一个 minibatch 的 PPO 损失（返回 torch 张量字典）。

    - policy: ``-min(r*A, clip(r,1±ε)*A).mean()``；
    - value: ``rank``（名次 CE）或 ``mse``（``E[u(rank)]`` vs returns）；
    - aux: ``pi_coef * CE(π_MCTS, π_θ)``（仅 ``has_pi`` 样本）；
    - seq（动作序列辅助任务，默认关闭）: ``seq_coef * BCEWithLogits(seq_logits, seq_target)``，
      只在 ``valid & ~forced`` 且标签非空的样本上平均；
    - entropy: masked 策略熵（鼓励探索）；
    - anchor: ``anchor_coef * KL(π_θ ‖ π_anchor)``（``anchor_logp`` 为 stage 起点在整批
      样本上的 masked log-prob，形状 ``[len(batch), 245]``）；
    - 场面题 soft-label CE（默认关闭）: ``problem_bc_coef * CE_soft``，只在题目状态上算；
    - 强度辅助头（默认关闭）: ``strength_aux_coef * (MSE_z + BCE_tier)``；
      两项共用 ``problem_batch`` 的同一次 ``forward_problem``；由 ``train_ppo`` 只在本次
      update 的第一个微批组传入一次（与 DPO 同模式，系数乘 len(slices) 抵消平均）；
    - upgrade DPO（默认关闭）: ``dpo_coef * dpo_pair_loss(model, dpo_batch, beta)``，
      ``dpo_batch`` 由 ``train_ppo`` 只在本次 update 的第一个微批组传入一次；
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
    # KL/approx_kl 口径：有 pi_logprobs（collect 侧 bias）时用无偏 π(a)，不用行为 μ(a)；
    # 默认 None -> 与旧路径逐位一致。
    kl_logp = old_logp
    if getattr(batch, "pi_logprobs", None) is not None:
        kl_logp = torch.from_numpy(np.ascontiguousarray(
            batch.pi_logprobs[idx].astype(np.float32))).to(dev)
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
    # ── 行为策略是 μ=(1−ε)π+ε·π_search 时，ratio 的分母必须是 μ 的 logprob ──
    # 用 π_old 作分母会得到 E_{a~μ}[(π/π_old)Â] ≠ E_{a~π}[Â]（docs/SEARCH_DISTILL_THEORY §4.5）。
    # 默认 ``behavior_logprobs is None`` → 逐位等于旧路径（分母 = old_logprobs）。
    behav_logp = old_logp
    _bl = getattr(batch, "behavior_logprobs", None)
    if _bl is not None:
        behav_logp = torch.from_numpy(
            np.ascontiguousarray(np.asarray(_bl)[idx].astype(np.float32))).to(dev)
    ratio = torch.exp(action_logp - behav_logp)
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

    # ── B10：终局强度辅助头（默认 0 = 整段不执行）────────────────────────────
    # 目标 = 该局终局 log1p(Σatk+hp)（同一局所有决策共享）。只在 minibatch 的前
    # ``_CEIL_ROWS`` 行上前向一次小批量，避免把 trunk 前向翻倍。
    ceiling_coef = float(getattr(config, "ceiling_aux_coef", 0.0) or 0.0)
    ceiling_loss = None
    ceiling_n = 0
    ceiling_term = 0.0
    if ceiling_coef > 0.0:
        _fs_np = getattr(batch, "final_strength", None)
        if _fs_np is not None:
            _CEIL_ROWS = 256
            _ci = idx[:_CEIL_ROWS] if idx.size > _CEIL_ROWS else idx
            _fs = torch.from_numpy(np.ascontiguousarray(
                np.asarray(_fs_np)[_ci].astype(np.float32))).to(dev)
            if bool(torch.isfinite(_fs).all()) and float(_fs.abs().sum()) > 0.0:
                from .entity_model import forward_ceiling_model  # noqa: PLC0415
                _xc = torch.from_numpy(np.ascontiguousarray(
                    batch.features[_ci].astype(np.float32))).to(dev)
                _cc = torch.from_numpy(np.ascontiguousarray(
                    batch.cards[_ci].astype(np.int64))).to(dev)
                _mc = torch.from_numpy(np.ascontiguousarray(
                    batch.masks[_ci].astype(bool))).to(dev)
                _cl, _cp = forward_ceiling_model(model, _xc, _cc, _mc)
                if _cp is not None:
                    _cp = _cp.reshape(int(_fs.numel()), -1)
                    ceiling_loss = F.smooth_l1_loss(_cp[:, 0], _fs)
                    _ft_np = getattr(batch, "final_tier", None)
                    if _ft_np is not None and _cp.shape[1] > 1:
                        _ft = torch.from_numpy(np.ascontiguousarray(
                            np.asarray(_ft_np)[_ci].astype(np.float32))).to(dev)
                        if bool(torch.isfinite(_ft).all()):
                            ceiling_loss = ceiling_loss + F.smooth_l1_loss(_cp[:, 1], _ft)
                    ceiling_term = ceiling_coef * ceiling_loss
                    ceiling_n = int(_fs.numel())

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
    if ceiling_loss is not None:
        total = total + ceiling_term
    if seq_loss is not None:
        total = total + seq_coef * seq_loss
    # ── 在线缩放教师 DAgger（默认 teacher_bc_coef=0 时整段不执行）────────────
    # 只在采集侧写了 teacher_action（gold>=10 & tier>=4 窗口）的样本上做 CE；
    # forced 样本（环境守卫）与无标签样本（-1）一律排除。策略 logits 已 masked。
    teacher_bc_coef = float(getattr(config, "teacher_bc_coef", 0.0) or 0.0)
    teacher_loss = None
    teacher_n = 0
    discover_bc_loss = None
    discover_bc_n = 0
    triple_bc_loss = None
    triple_bc_n = 0
    if teacher_bc_coef > 0.0:
        ta_np = getattr(batch, "teacher_action", None)
        if ta_np is not None:
            ta = torch.from_numpy(
                np.ascontiguousarray(np.asarray(ta_np)[idx].astype(np.int64))).to(dev)
            has_t = (ta >= 0) & (valid > 0)
            teacher_n = int(has_t.sum().item())
            if teacher_n > 0:
                teacher_loss = F.cross_entropy(logits[has_t], ta[has_t])
                total = total + teacher_bc_coef * teacher_loss
    # ── 复利结构辅助 BC（Discover 选牌 / 三连 buy；默认 0 = 整段不执行）─────────
    # 标签由训练入口写入 batch（`discover_bc_idx/w`、`triple_bc_action/w`）：
    # 行为策略保持无偏（on-policy 前提不破），只把"含放大器/引擎卡的 Discover 选项"与
    # "能凑三连/对子的 buy 位"当教师，用交叉熵把这种选择**学进权重**。
    _dbc = float(config.discover_bc_coef) * float(config.discover_bc_scale)
    _tbc = float(config.triple_bc_coef) * float(config.triple_bc_scale)
    # 使用 PPO 同一份 masked logp；即使外部标签损坏也不能给非法位梯度。
    if _dbc > 0.0:
        _di, _dw = getattr(batch, "discover_bc_idx", None), getattr(batch, "discover_bc_w", None)
        if _di is not None and _dw is not None:
            _i = torch.as_tensor(np.asarray(_di)[idx], dtype=torch.long, device=dev)
            _w = torch.as_tensor(np.asarray(_dw)[idx], dtype=torch.float32, device=dev)
            _ce, discover_bc_n = replication_bc_ce(logp, m, _i, _w, valid,
                                                   normalize=config.bc_ce_norm)
            if discover_bc_n:
                total = total + _dbc * _ce
                discover_bc_loss = _ce.detach()
    if _tbc > 0.0:
        _ta = getattr(batch, "triple_bc_action", None)
        if _ta is not None:
            _tv = torch.as_tensor(np.asarray(_ta)[idx], dtype=torch.long, device=dev)
            _tw = getattr(batch, "triple_bc_w", None)
            _tw = (torch.ones_like(_tv, dtype=torch.float32) if _tw is None else
                   torch.as_tensor(np.asarray(_tw)[idx], dtype=torch.float32, device=dev))
            _ce_t, triple_bc_n = replication_bc_ce(logp, m, _tv[:, None], _tw[:, None],
                                                   valid, normalize=config.bc_ce_norm,
                                                   row_weight=True)
            if triple_bc_n:
                total = total + _tbc * _ce_t
                triple_bc_loss = _ce_t.detach()
    upgrade_bc_loss = None
    upgrade_bc_n = 0
    _ubc = (float(getattr(config, "upgrade_bc_coef", 0.0) or 0.0)
            * float(getattr(config, "upgrade_bc_scale", 1.0) or 1.0))
    if _ubc > 0.0:
        _ua = getattr(batch, "upgrade_bc_action", None)
        if _ua is not None:
            _uv = torch.as_tensor(np.asarray(_ua)[idx], dtype=torch.long, device=dev)
            _uw = getattr(batch, "upgrade_bc_w", None)
            _uw = (torch.ones_like(_uv, dtype=torch.float32) if _uw is None else
                   torch.as_tensor(np.asarray(_uw)[idx], dtype=torch.float32, device=dev))
            _ce_u, upgrade_bc_n = replication_bc_ce(logp, m, _uv[:, None], _uw[:, None],
                                                    valid, normalize=config.bc_ce_norm,
                                                    row_weight=True)
            if upgrade_bc_n:
                total = total + _ubc * _ce_u
                upgrade_bc_loss = _ce_u.detach()
    # ── 过程价值辅助头（默认 process_value_coef=0 时整段不执行）──────────────
    # 独立前向（forward_process），不改变策略/价值主干前向的输出；目标 NaN = 不可得，
    # 只在 (available & valid) 样本上算 MSE。梯度经辅助损失回传 trunk。
    process_coef = float(getattr(config, "process_value_coef", 0.0) or 0.0)
    process_stats: Dict[str, Any] = {}
    if process_coef > 0.0:
        pt_np = getattr(batch, "process_target", None)
        if pt_np is not None:
            pt_rows = np.asarray(pt_np)[idx].astype(np.float32).reshape(len(idx), 3)
            avail_np = np.isfinite(pt_rows).all(axis=1)
            if bool(avail_np.any()):
                _p_logits, pred = forward_process_model(model, x, c, m)
                if pred is None:
                    raise RuntimeError(
                        "process_value_coef>0 但模型没有 process_head："
                        "请用 attach_process_head() 或 build_net(..., process_head=True)")
                pt = torch.from_numpy(np.ascontiguousarray(
                    np.nan_to_num(pt_rows, nan=0.0))).to(dev)
                avail = torch.from_numpy(avail_np).to(dev) & (valid > 0)
                pv = process_value_loss(pred, pt, avail)
                total = total + process_coef * pv["loss"]
                process_stats = {
                    "process_value_loss": pv["loss"].detach(),
                    "process_tavern_mse": torch.as_tensor(pv["mse_tavern"], device=dev),
                    "process_casts_mse": torch.as_tensor(pv["mse_casts"], device=dev),
                    "process_consume_mse": torch.as_tensor(pv["mse_consume"], device=dev),
                    "process_samples": torch.as_tensor(pv["n"], device=dev),
                    "process_coef": torch.as_tensor(float(process_coef), device=dev),
                }
    # ── 真实人类 BC 辅助正则（分层目标；默认 bc_coef=0 时整段不执行）─────────
    # 每个 PPO minibatch 用同一个 model、同一张图做一次额外 forward（forward_bc）：
    #   类型级：245 动作 logits -> 9 类 log-sum-exp 聚合 -> CE(action_type)
    #   卡牌级：card_head(3983) 在 buy/play 样本上 CE(card_id 映射标签)
    # 两层加权后乘 bc_coef 直接加进 total,因此与 PPO/seq 共享同一次 backward。
    # ``bc_coef_override``：``bc_every>1`` 时由 train_ppo 传入 ``bc_coef * bc_every``，
    # 只在真正做 BC 的步上生效（跳过步不传 bc_batch,本段整体不执行）。
    bc_coef = (float(getattr(config, "bc_coef", 0.0) or 0.0)
               if bc_coef_override is None else float(bc_coef_override))
    bc_loss = None
    bc_type_ce = None
    bc_card_ce = None
    bc_n = 0
    if bc_coef > 0.0 and bc_batch is not None and len(bc_batch) > 0:
        bc_n = int(len(bc_batch))
        bx = torch.from_numpy(np.ascontiguousarray(
            bc_batch.features.astype(np.float32))).to(dev)
        bc_cards = torch.from_numpy(np.ascontiguousarray(
            bc_batch.cards.astype(np.int64))).to(dev)
        bc_m = torch.from_numpy(np.ascontiguousarray(
            bc_batch.action_mask.astype(bool))).to(dev)
        bc_cls = torch.from_numpy(np.ascontiguousarray(
            bc_batch.class_ids.astype(np.int64))).to(dev)
        bc_w = torch.from_numpy(np.ascontiguousarray(
            bc_batch.weights.astype(np.float32))).to(dev)
        bc_tids = torch.from_numpy(np.ascontiguousarray(
            bc_batch.type_ids.astype(np.int64))).to(dev)
        bc_card_tgt = torch.from_numpy(np.ascontiguousarray(
            bc_batch.card_target.astype(np.int64))).to(dev)
        bc_card_ok = torch.from_numpy(np.ascontiguousarray(
            bc_batch.card_valid.astype(bool))).to(dev)
        bc_policy_logits, bc_card_logits = (
            train_forward.bc(bx, bc_cards, bc_m) if train_forward is not None
            else forward_bc_model(model, bx, bc_cards, bc_m))
        bc_policy_logits = bc_policy_logits.float()
        if bc_card_logits is not None:
            bc_card_logits = bc_card_logits.float()
        hier = bc_hier_loss(
            bc_policy_logits, bc_tids, bc_cls, action_mask=bc_m,
            card_logits=bc_card_logits, card_target=bc_card_tgt,
            card_valid=bc_card_ok, weights=bc_w,
            class_counts=bc_batch.class_counts,
            class_weight=getattr(bc_batch, "class_weight", None),
            type_weight=float(getattr(config, "bc_type_weight",
                                    DEFAULT_BC_TYPE_WEIGHT) or 0.0),
            card_weight=float(getattr(config, "bc_card_weight",
                                    DEFAULT_BC_CARD_WEIGHT) or 0.0))
        bc_loss = hier["loss"]
        bc_type_ce = hier["type_loss"]
        bc_card_ce = hier["card_loss"]
        total = total + bc_coef * bc_loss
    # ── upgrade 子集 one-sided DPO（默认 dpo_coef=0 时整段不执行）─────────────────
    # chosen=人类 upgrade 动作，rejected=当前策略 masked argmax（自对比，无参考模型）。
    # ``dpo_batch`` 由 ``train_ppo`` 只在「本次 update 的第一个微批组」传入一次，
    # 因此一次 iteration 只算一次 DPO（iteration 级 ``dpo_every`` 在 trainer 里判定）。
    dpo_coef = (float(getattr(config, "dpo_coef", 0.0) or 0.0)
                if dpo_coef_override is None else float(dpo_coef_override))
    dpo_loss = None
    dpo_accept: Optional[float] = None
    dpo_n = 0
    if dpo_coef > 0.0 and dpo_batch is not None and len(dpo_batch) > 0:
        dpo_n = int(len(dpo_batch))
        dpo_loss, dpo_accept = dpo_pair_loss(
            model, dpo_batch,
            float(getattr(config, "dpo_beta", 0.1) or 0.1), device=str(dev))
        dpo_term = dpo_coef * dpo_loss
        total = total + dpo_term
    else:
        dpo_term = None
    # ── 场面题：soft-label CE + 强度辅助头（默认关闭时整段不执行）────────────
    # 一次 forward_problem 同时出策略 logits 与强度头预测；两个系数各自独立，
    # 所以 B（只强度头）/C（只题目 CE）/D（都开）三臂共用同一批题目状态。
    problem_bc_coef = (float(getattr(config, "problem_bc_coef", 0.0) or 0.0)
                       if problem_bc_coef_override is None
                       else float(problem_bc_coef_override))
    strength_coef = (float(getattr(config, "strength_aux_coef", 0.0) or 0.0)
                     if strength_aux_coef_override is None
                     else float(strength_aux_coef_override))
    problem_term = None
    problem_stats: Dict[str, Any] = {}
    if ((problem_bc_coef > 0.0 or strength_coef > 0.0)
            and problem_batch is not None and len(problem_batch) > 0):
        from .board_problems import problem_bc_soft_ce, strength_aux_loss  # noqa: PLC0415
        px = torch.from_numpy(np.ascontiguousarray(
            problem_batch.features.astype(np.float32))).to(dev)
        pc = torch.from_numpy(np.ascontiguousarray(
            problem_batch.cards.astype(np.int64))).to(dev)
        pm = torch.from_numpy(np.ascontiguousarray(
            problem_batch.mask.astype(bool))).to(dev)
        p_logits, p_pred = forward_problem_model(model, px, pc, pm)
        problem_term = torch.zeros((), device=dev)
        if problem_bc_coef > 0.0:
            pbc = problem_bc_soft_ce(p_logits, problem_batch)
            problem_term = problem_term + problem_bc_coef * pbc["loss"]
            problem_stats["problem_bc_loss"] = pbc["loss"].detach()
            problem_stats["problem_bc_top1_acc"] = pbc["top1_acc"]
            problem_stats["problem_policy_in_ref"] = pbc["policy_in_ref"]
            problem_stats["problem_n"] = torch.as_tensor(float(pbc["n"]), device=dev)
            problem_stats["problem_coef"] = torch.as_tensor(
                float(problem_bc_coef), device=dev)
        if strength_coef > 0.0:
            if p_pred is None:
                raise RuntimeError(
                    "strength_aux_coef>0 但模型没有 strength_head："
                    "请用 attach_strength_head() 或 build_net(..., strength_head=True)")
            paux = strength_aux_loss(
                p_pred, problem_batch,
                pos_weight=float(getattr(config, "strength_tier_pos_weight", 1.0)
                                 or 1.0))
            problem_term = problem_term + strength_coef * paux["loss"]
            problem_stats["strength_aux_loss"] = paux["loss"].detach()
            problem_stats["strength_mse"] = paux["mse"]
            problem_stats["strength_bce"] = paux["bce"]
            problem_stats["strength_tier_acc"] = paux["tier_up_acc"]
            problem_stats["strength_n"] = torch.as_tensor(
                float(paux["n"]), device=dev)
            problem_stats["strength_coef"] = torch.as_tensor(
                float(strength_coef), device=dev)
        total = total + problem_term
    anchor_kl = torch.zeros((), device=dev)
    beta = float(config.anchor_coef)
    if beta > 0.0 and anchor_logp is not None:
        # KL(π_θ ‖ π_anchor) = Σ_a π_θ(a) · (log π_θ(a) − log π_anchor(a))，只对合法动作求和
        a_lp = anchor_logp[idx] if anchor_logp.shape[0] > idx.max() else anchor_logp
        a_safe = torch.where(m, a_lp, torch.zeros_like(a_lp))
        kl_all = (probs * (safe_logp - a_safe)).sum(dim=-1)
        anchor_kl = (kl_all * valid).sum() / valid.sum().clamp_min(1.0)
        total = total + beta * anchor_kl
    approx_kl = ((kl_logp - action_logp) * valid).sum() / valid.sum().clamp_min(1.0)
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
    # 在线缩放教师 DAgger：只有真的算了 CE 才出现（默认关闭 -> 结构不变）
    if teacher_loss is not None:
        result["teacher_bc_loss"] = teacher_loss.detach()
        result["teacher_bc_coef"] = torch.as_tensor(float(teacher_bc_coef), device=dev)
        result["teacher_samples"] = torch.as_tensor(float(teacher_n), device=dev)
    # 复利结构辅助 BC：只有真的算了 CE 才出现（默认关闭 -> 结构不变）
    if discover_bc_loss is not None:
        result["discover_bc_loss"] = discover_bc_loss
        result["discover_bc_coef"] = torch.as_tensor(float(_dbc), device=dev)
        result["discover_bc_samples"] = torch.as_tensor(float(discover_bc_n), device=dev)
    if triple_bc_loss is not None:
        result["triple_bc_loss"] = triple_bc_loss
        result["triple_bc_coef"] = torch.as_tensor(float(_tbc), device=dev)
        result["triple_bc_samples"] = torch.as_tensor(float(triple_bc_n), device=dev)
    if upgrade_bc_loss is not None:
        result["upgrade_bc_loss"] = upgrade_bc_loss
        result["upgrade_bc_coef"] = torch.as_tensor(float(_ubc), device=dev)
        result["upgrade_bc_samples"] = torch.as_tensor(float(upgrade_bc_n), device=dev)
    # B10 终局强度辅助头：只有真的算了才出现（默认关闭 -> 结构不变）
    if ceiling_loss is not None:
        result["ceiling_aux_loss"] = ceiling_loss.detach()
        result["ceiling_aux_coef"] = torch.as_tensor(float(ceiling_coef), device=dev)
        result["ceiling_rows"] = torch.as_tensor(float(ceiling_n), device=dev)
    # 过程价值辅助头：只有真的算了 MSE 才出现（默认关闭 -> 结构不变）
    if process_stats:
        result.update(process_stats)
    # BC 辅助正则：只有 bc_coef>0 才出现；bc_coef=0 时 stats 结构与旧版一致
    if bc_loss is not None:
        result["bc_loss"] = bc_loss.detach()
        if bc_type_ce is not None:
            result["bc_type_loss"] = bc_type_ce.detach()
        if bc_card_ce is not None:
            result["bc_card_loss"] = bc_card_ce.detach()
        result["bc_coef"] = torch.as_tensor(bc_coef, device=dev)
        result["bc_samples"] = torch.as_tensor(float(bc_n), device=dev)
    # upgrade DPO：只有 dpo_coef>0 且真的抽到样本才出现（默认关闭 -> 结构不变）
    if dpo_loss is not None:
        result["dpo_loss"] = dpo_loss.detach()
        # 记**配置系数**（而非含 grad_accum 补偿的有效系数），与 iteration 日志口径一致
        result["dpo_coef"] = torch.as_tensor(
            float(getattr(config, "dpo_coef", 0.0) or 0.0), device=dev)
        result["dpo_accept_rate"] = torch.as_tensor(
            float(dpo_accept or 0.0), device=dev)
        result["dpo_samples"] = torch.as_tensor(float(dpo_n), device=dev)
    # 场面题 / 强度辅助头：只有真的算出损失才出现（默认关闭 -> 结构不变）
    if problem_term is not None:
        result.update(problem_stats)
    return result


def train_ppo(model: Any, batch: PPOBatch, config: Optional[PPOConfig] = None,
              *, on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
              optimizer: Any = None, rng: Optional[np.random.Generator] = None,
              anchor_logp: Any = None,
              train_forward: Optional[TrainForward] = None,
              bc_pool: Any = None,
              bc_rng: Optional[np.random.Generator] = None,
              dpo_batch: Optional[UpgradeSamples] = None,
              problem_batch: Optional[Any] = None,
              problem_bc_coef: Optional[float] = None,
              strength_aux_coef: Optional[float] = None) -> Dict[str, Any]:
    """执行 PPO 更新（minibatch × epochs，clip、entropy、KL 早停）。

    ``train_forward``：复用外部构建的 ``TrainForward``（``PPOTrainer`` 在启动时构建并
    warmup，避免把编译开销算进第一个 iteration）；为 ``None`` 且
    ``config.compile_train>0`` 时在此处构建 + warmup。
    ``bc_rng``：BC 采样专用 Generator（``PPOTrainer`` 跨 iteration 持有）；
    None 时按 ``cfg.seed`` 新建（独立于 ``rng``，不影响 PPO 采样序列）。
    ``dpo_batch``：upgrade 池里抽好的一批样本（``PPOTrainer`` 按 iteration 周期决定
    是否传入）；非空且 ``dpo_coef>0`` 时在本次 update 的**第一个微批组**把
    ``dpo_coef * dpo_pair_loss`` 加进 total，与 PPO 同一次 backward。

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
    # ── BC 池（默认关闭）：优先用外部预加载的池；否则按配置惰性加载一次 ──
    bc_points = parse_bc_coef_ramp(str(getattr(cfg, "bc_coef_ramp", "") or ""))
    bc_wanted = (float(getattr(cfg, "bc_coef", 0.0) or 0.0) > 0.0
                 or bool(bc_points))
    if bc_wanted and bc_pool is None:
        path = str(getattr(cfg, "bc_samples_path", "") or DEFAULT_BC_SAMPLES_PATH)
        try:
            pool = load_bc_samples(
                path, mmr_min=int(getattr(cfg, "bc_mmr_min", 6000)),
                mmr_boost=float(getattr(cfg, "bc_mmr_boost", 1.0)),
                class_weight_overrides=getattr(cfg, "bc_class_weights", None))
            if len(pool) == 0:
                raise ValueError("BC 样本池为空（白名单/MMR 过滤后 0 条）")
            bc_pool = pool
        except Exception as exc:  # noqa: BLE001 - BC 是可选正则，失败不能中断训练
            print(f"[ppo][warn] BC 辅助正则加载失败，自动关闭 bc_coef=0："
                  f"{type(exc).__name__}: {exc}", flush=True)
            cfg.bc_coef = 0.0
            cfg.bc_coef_ramp = ""
            bc_pool = None
            bc_wanted = False
    if bc_wanted and bc_pool is not None and len(bc_pool) == 0:
        print("[ppo][warn] BC 样本池为空，自动关闭 bc_coef=0", flush=True)
        cfg.bc_coef = 0.0
        cfg.bc_coef_ramp = ""
        bc_pool = None
        bc_wanted = False
    bc_active = bool(bc_wanted and float(getattr(cfg, "bc_coef", 0.0) or 0.0) > 0.0
                     and bc_pool is not None and len(bc_pool) > 0)
    # ``bc_every``：每 N 个 PPO 微批做一次 BC，并把该步权重乘 N 保持等效平均权重。
    # BC 采样用**独立 RNG**：跳过/开启 BC 都不会改变 PPO 的 permutation/采样序列，
    # 因此 bc_coef=0 与 bc_every>1 的跳过路径对其他指标严格无影响。
    bc_every = max(1, int(getattr(cfg, "bc_every", 1) or 1))
    bc_step = 0
    bc_done = 0
    if bc_rng is None:
        bc_rng = np.random.default_rng([int(getattr(cfg, "seed", 0) or 0), 0xBC])
    # upgrade DPO（默认关闭）：dpo_batch 由 PPOTrainer 按 iteration 周期传入；
    # 这里只负责「一次 update 只加一次」与抵消梯度累积的平均（见下方 total/len(slices)）。
    dpo_on = bool(dpo_batch is not None and len(dpo_batch) > 0
                  and float(getattr(cfg, "dpo_coef", 0.0) or 0.0) > 0.0)
    # 场面题 / 强度辅助头（默认关闭）：由 PPOTrainer 按周期传入一批题目 + **本次该生效**
    # 的两个系数（周期门控在 trainer 里做：跳过步传 0）；None = 用 config 里的值。
    # 两个系数分开传，因此 B（只强度头）/C（只题目 CE）/D（都开）共用同一批题目状态。
    pbc_cfg = (float(getattr(cfg, "problem_bc_coef", 0.0) or 0.0)
               if problem_bc_coef is None else float(problem_bc_coef))
    saux_cfg = (float(getattr(cfg, "strength_aux_coef", 0.0) or 0.0)
                if strength_aux_coef is None else float(strength_aux_coef))
    problem_on = bool(problem_batch is not None and len(problem_batch) > 0
                      and (pbc_cfg > 0.0 or saux_cfg > 0.0))
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
    # 本次 update 的微批总数（与循环里 slices 的个数一致）：epochs × ceil(n/minibatch)。
    # 每 N 个微批做一次 BC -> 实际 BC 步数；系数按「总权重不变」精确折算：
    #   n_bc * bc_coef_eff == m_total * bc_coef
    # 因此 N 不整除 m_total 时也不会多算 BC 权重（N=16、m_total=40 -> 40/3×coef）。
    _m_total = int(epochs) * int(math.ceil(n / float(mb)))
    _bc_n_steps = (int(math.ceil(_m_total / float(bc_every))) if bc_active else 0)
    bc_coef_eff = (float(getattr(cfg, "bc_coef", 0.0) or 0.0)
                   * float(_m_total) / float(max(1, _bc_n_steps))) if bc_active else 0.0
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
            step_counts: Dict[str, int] = {}
            served = 0
            for j, (a, b) in enumerate(slices):
                sel = base_idx[order[a:b]]
                bc_batch = None
                do_bc = False
                if bc_active:
                    do_bc = (bc_step % bc_every) == 0
                    bc_step += 1
                    if do_bc:
                        bc_done += 1
                        k = min(int(cfg.bc_batch), len(bc_pool))
                        bc_sel = bc_rng.choice(len(bc_pool), size=k, replace=False)
                        bc_batch = bc_obs_batch(bc_pool, BC_OBS_LAYOUT,
                                                indices=bc_sel)
                # upgrade DPO：只在本次 update 的第一个微批组、第 0 个微批加一次；
                # 系数乘 len(slices) 抵消下面的 total/len(slices) 平均，使等效梯度
                # 恰好是 dpo_coef * L_dpo（与 PPO 共享同一次 backward）。
                dpo_this = None
                dpo_coef_this = None
                if dpo_on and updates == 0 and start == 0 and j == 0:
                    dpo_this = dpo_batch
                    dpo_coef_this = float(cfg.dpo_coef) * float(len(slices))
                # 场面题：同样只在第一个微批组的第 0 个微批加一次；系数乘 len(slices)
                # 抵消下面的 total/len(slices) 平均（等效梯度 = coef * L_problem）。
                problem_this = None
                pbc_coef_this = None
                saux_coef_this = None
                if problem_on and updates == 0 and start == 0 and j == 0:
                    problem_this = problem_batch
                    pbc_coef_this = float(pbc_cfg) * float(len(slices))
                    saux_coef_this = float(saux_cfg) * float(len(slices))
                if use_amp:
                    with torch.autocast("cuda", dtype=torch.bfloat16):
                        out = ppo_losses(model, batch, cfg, indices=sel,
                                         anchor_logp=anchor_logp,
                                         train_forward=train_forward,
                                         bc_batch=bc_batch,
                                         bc_coef_override=bc_coef_eff,
                                         dpo_batch=dpo_this,
                                         dpo_coef_override=dpo_coef_this,
                                         problem_batch=problem_this,
                                         problem_bc_coef_override=pbc_coef_this,
                                         strength_aux_coef_override=saux_coef_this)
                else:
                    out = ppo_losses(model, batch, cfg, indices=sel,
                                     anchor_logp=anchor_logp,
                                     train_forward=train_forward,
                                     bc_batch=bc_batch,
                                     bc_coef_override=bc_coef_eff,
                                     dpo_batch=dpo_this,
                                     dpo_coef_override=dpo_coef_this,
                                     problem_batch=problem_this,
                                     problem_bc_coef_override=pbc_coef_this,
                                     strength_aux_coef_override=saux_coef_this)
                (out["total"] / float(len(slices))).backward()
                served += int(sel.size)
                for k, v in out.items():
                    step_metrics[k] = (step_metrics.get(k, 0.0)
                                       + float(v.detach().cpu()))
                    step_counts[k] = step_counts.get(k, 0) + 1
            # 按「该键实际出现的微批数」平均：bc_every>1 时 bc_* 只在 BC 步出现，
            # 不能被跳过步稀释；其他键每个微批都有，结果与旧版逐位一致。
            step_metrics = {k: v / float(step_counts[k])
                            for k, v in step_metrics.items()}
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(cfg.max_grad_norm))
            for k, v in step_metrics.items():
                acc.setdefault(k, []).append(v)
            if on_step is not None:
                on_step({"step": updates, "epoch": epoch + 1, **step_metrics})
            if int(cfg.log_every) > 0 and updates % int(cfg.log_every) == 0:
                bc_note = (f" bc={step_metrics['bc_loss']:.4f}"
                           f" bc_type={step_metrics.get('bc_type_loss', 0.0):.4f}"
                           f" bc_card={step_metrics.get('bc_card_loss', 0.0):.4f}"
                           f" bc_coef={step_metrics['bc_coef']:.4g}"
                           if "bc_loss" in step_metrics else "")
                print(f"[ppo] step {updates} total={step_metrics['total']:.4f} "
                      f"policy={step_metrics['policy_loss']:.4f} "
                      f"value={step_metrics['value_loss']:.4f} "
                      f"kl={step_metrics['approx_kl']:.5f}{bc_note}", flush=True)
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
        # 当前 epoch 已用的有效系数与比率；调整只作用下一 epoch/update。
        _ratios, _scales = [], []
        for _side in ("discover", "triple", "upgrade"):
            _key = _side + "_bc"
            if _key + "_loss" not in rec:
                continue
            _base = float(getattr(cfg, _key + "_coef"))
            _scale = float(getattr(cfg, _key + "_scale"))
            _eff = _base * _scale
            _ratio = float(getattr(cfg, "bc_guard_ratio", 0.0) or 0.0)
            if _side == "upgrade":
                _ur = getattr(cfg, "upgrade_bc_guard_ratio", -1.0)
                _ur = -1.0 if _ur is None else float(_ur)
                if _ur >= 0.0:
                    _ratio = _ur
            _new, _r = replication_bc_guard(_eff, rec[_key + "_loss"],
                                            rec["policy_loss"], ratio=_ratio)
            rec[_key + "_scale"] = _scale
            rec[_key + "_r"] = _r
            rec[_key + "_next_coef"] = _new
            _ratios.append(_r)
            _scales.append(_scale)
            if _ratio > 0 and _base > 0:
                setattr(cfg, _key + "_scale", _new / _base)
        if _ratios:
            rec["bc_scale"] = max(_scales)
            rec["r"] = sum(_ratios)
        rec["elapsed_s"] = time.time() - t0
        rec["kl_early_stopped"] = bool(epoch_stopped)
        logs.append(rec)
        # seq=... / bc=... 只在启用对应辅助任务时出现（默认关闭 -> 日志行与旧版逐字节一致）
        seq_note = f" seq={rec['seq_loss']:.4f}" if "seq_loss" in rec else ""
        bc_note = (f" bc={rec['bc_loss']:.4f} bc_type={rec.get('bc_type_loss', 0.0):.4f}"
                   f" bc_card={rec.get('bc_card_loss', 0.0):.4f}"
                   f" bc_coef={rec['bc_coef']:.4g}"
                   f" bc_samples={rec['bc_samples']:.0f}"
                   if "bc_loss" in rec else "")
        dpo_note = (f" dpo={rec['dpo_loss']:.4f}"
                    f" dpo_acc={rec['dpo_accept_rate']:.3f}"
                    f" dpo_coef={rec['dpo_coef']:.4g}"
                    f" dpo_n={rec['dpo_samples']:.0f}"
                    if "dpo_loss" in rec else "")
        prob_note = ""
        if "problem_bc_loss" in rec:
            prob_note += (f" pbc={rec['problem_bc_loss']:.4f}"
                          f" pbc_top1={rec.get('problem_bc_top1_acc', 0.0):.3f}")
        if "strength_aux_loss" in rec:
            prob_note += (f" saux={rec['strength_aux_loss']:.4f}"
                          f" s_mse={rec.get('strength_mse', 0.0):.4f}"
                          f" s_bce={rec.get('strength_bce', 0.0):.4f}")
        if "teacher_bc_loss" in rec:
            prob_note += (f" teach={rec['teacher_bc_loss']:.4f}"
                          f" teach_n={rec.get('teacher_samples', 0.0):.0f}")
        if "process_value_loss" in rec:
            prob_note += (f" proc={rec['process_value_loss']:.4f}"
                          f" proc_n={rec.get('process_samples', 0.0):.0f}")
        if "discover_bc_loss" in rec:
            prob_note += (f" dbc={rec['discover_bc_loss']:.4f}"
                          f" dbc_n={rec.get('discover_bc_samples', 0.0):.0f}")
        if "triple_bc_loss" in rec:
            prob_note += (f" tbc={rec['triple_bc_loss']:.4f}"
                          f" tbc_n={rec.get('triple_bc_samples', 0.0):.0f}")
        print(f"[ppo] epoch {epoch + 1}/{epochs} total={rec['total']:.4f} "
              f"(policy={rec['policy_loss']:.4f} value={rec['value_loss']:.4f} "
              f"aux_pi={rec['aux_pi_loss']:.4f} ent={rec['entropy']:.4f} "
              f"kl={rec['approx_kl']:.5f} clip={rec['clip_frac']:.3f}){seq_note}"
              f"{bc_note}{dpo_note}{prob_note}",
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
    # 提升 epoch 指标，供训练入口/history 使用；缺标签的 epoch 不以 0 稀释。
    for _key in ("policy_loss", "discover_bc_loss", "triple_bc_loss", "upgrade_bc_loss",
                 "ceiling_aux_loss", "ceiling_aux_coef", "ceiling_rows",
                 "bc_scale", "r",
                 "discover_bc_scale", "triple_bc_scale", "upgrade_bc_scale",
                 "discover_bc_r", "triple_bc_r", "upgrade_bc_r",
                 "discover_bc_coef", "triple_bc_coef", "upgrade_bc_coef",
                 "discover_bc_next_coef", "triple_bc_next_coef", "upgrade_bc_next_coef"):
        _vals = [rec[_key] for rec in logs if _key in rec]
        if _vals:
            stats[_key] = float(np.mean(_vals))
    # 搜索行为混合（μ=(1−ε)π+ε·π_search）：批次带 behavior_logprobs 时才出该键。
    # ``w = exp(logp_pi − logp_mu)`` 就是「π 未更新时」的 IS 权重/ratio 起点：
    # 未混合样本恒为 1（ratio 起点=1 的自检口径），搜索混合样本按 1/ε 上界放大。
    _bl_all = getattr(batch, "behavior_logprobs", None)
    if _bl_all is not None:
        _forced = np.asarray(batch.forced, dtype=bool)
        _valid = ~_forced
        _bl = np.asarray(_bl_all, dtype=np.float64)
        _olp = np.asarray(batch.old_logprobs, dtype=np.float64)
        if _valid.any():
            _lw = np.clip(_olp[_valid] - _bl[_valid], -50.0, 50.0)
            _w = np.exp(_lw)
            _sw = float(_w.sum())
            _mixed = _bl[_valid] < (_olp[_valid] - 1e-9)
            stats["behavior_mix"] = {
                "rate": float(_valid.mean()),
                "mixed_rate": float(_mixed.mean()) if _mixed.size else 0.0,
                "logp_pi_mean": float(_olp[_valid].mean()),
                "logp_mu_mean": float(_bl[_valid].mean()),
                "mean_pi_minus_mu": float((_olp[_valid] - _bl[_valid]).mean()),
                "weight_mean": _sw / max(int(_valid.sum()), 1),
                "weight_p50": float(np.median(_w)),
                "weight_p95": float(np.percentile(_w, 95)),
                "weight_max": float(_w.max()),
                "weight_min": float(_w.min()),
                "ess_ratio": (_sw * _sw / max(float((_w * _w).sum()), 1e-12)
                              / max(int(_valid.sum()), 1)),
                "eps": float(getattr(cfg, "behavior_mix_eps", 0.0) or 0.0),
                "when": str(getattr(cfg, "behavior_mix_when", "") or ""),
                "max_per_turn": int(getattr(cfg, "behavior_mix_max_per_turn", 0) or 0),
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
    # BC 辅助正则：只有真的算出 bc_loss 才写 stats；bc_coef=0（默认）时连 config
    # 回显里的 bc_* 键也去掉，保证与未接 BC 的旧版本结构一致。
    bc_on = any("bc_loss" in r for r in logs)
    if bc_on:
        stats["bc_loss"] = float(np.mean([r.get("bc_loss", 0.0) for r in logs]))
        stats["bc_type_loss"] = float(np.mean(
            [r.get("bc_type_loss", 0.0) for r in logs]))
        stats["bc_card_loss"] = float(np.mean(
            [r.get("bc_card_loss", 0.0) for r in logs]))
        stats["bc_coef"] = float(getattr(cfg, "bc_coef", 0.0) or 0.0)
        stats["bc_coef_effective"] = float(bc_coef_eff)
        stats["bc_every"] = int(bc_every)
        stats["bc_steps"] = int(bc_done)
        stats["bc_type_weight"] = float(
            getattr(cfg, "bc_type_weight", DEFAULT_BC_TYPE_WEIGHT) or 0.0)
        stats["bc_card_weight"] = float(
            getattr(cfg, "bc_card_weight", DEFAULT_BC_CARD_WEIGHT) or 0.0)
        _bcw = dict(getattr(cfg, "bc_class_weights", {}) or {})
        if _bcw:  # 空覆盖（默认）= 不新增 stats 键，保持旧结构
            stats["bc_class_weights"] = _bcw
        stats["bc_samples"] = float(np.mean(
            [r.get("bc_samples", 0.0) for r in logs]))
        stats["bc_pool_samples"] = int(len(bc_pool)) if bc_pool is not None else 0
        if bc_pool is not None:
            stats["bc_pool"] = bc_pool_summary(bc_pool)
    else:
        cfg_echo = stats.get("config")
        if isinstance(cfg_echo, dict):
            for key in ("bc_coef", "bc_coef_ramp", "bc_mmr_min", "bc_mmr_boost",
                        "bc_samples_path", "bc_batch", "bc_every", "bc_compile",
                        "bc_type_weight", "bc_card_weight", "bc_class_weights"):
                cfg_echo.pop(key, None)
    # upgrade DPO：只有真的算出 dpo_loss 才写 stats；dpo_coef=0（默认）时连 config
    # 回显里的 dpo_* 键也去掉，保证与未接 DPO 的旧版本结构逐字节一致。
    _dpo_recs = [r for r in logs if "dpo_loss" in r]
    if _dpo_recs:
        stats["dpo_loss"] = float(np.mean([r["dpo_loss"] for r in _dpo_recs]))
        stats["dpo_coef"] = float(getattr(cfg, "dpo_coef", 0.0) or 0.0)
        stats["dpo_accept_rate"] = float(np.mean(
            [r.get("dpo_accept_rate", 0.0) for r in _dpo_recs]))
        stats["dpo_samples"] = float(np.mean(
            [r.get("dpo_samples", 0.0) for r in _dpo_recs]))
        stats["dpo_beta"] = float(getattr(cfg, "dpo_beta", 0.1) or 0.1)
        stats["dpo_every"] = int(getattr(cfg, "dpo_every", 1) or 1)
        stats["dpo_steps"] = int(len(_dpo_recs))
        if dpo_batch is not None:
            stats["dpo_batch_size"] = int(len(dpo_batch))
    else:
        cfg_echo = stats.get("config")
        if isinstance(cfg_echo, dict):
            for key in ("dpo_coef", "dpo_beta", "dpo_batch", "dpo_every",
                        "dpo_samples"):
                cfg_echo.pop(key, None)
    # 场面题 / 强度辅助头：只有真的算出损失才写 stats；默认关闭时连 config 回显里的
    # 新键也去掉，保证与未接本功能的旧版本结构逐字节一致。
    _pbc_recs = [r for r in logs if "problem_bc_loss" in r]
    _saux_recs = [r for r in logs if "strength_aux_loss" in r]
    if _pbc_recs:
        stats["problem_bc_loss"] = float(np.mean(
            [r["problem_bc_loss"] for r in _pbc_recs]))
        stats["problem_bc_top1_acc"] = float(np.mean(
            [r.get("problem_bc_top1_acc", 0.0) for r in _pbc_recs]))
        stats["problem_policy_in_ref"] = float(np.mean(
            [r.get("problem_policy_in_ref", 0.0) for r in _pbc_recs]))
        stats["problem_bc_coef"] = float(getattr(cfg, "problem_bc_coef", 0.0) or 0.0)
        stats["problem_bc_every"] = int(getattr(cfg, "problem_bc_every", 1) or 1)
        stats["problem_bc_steps"] = int(len(_pbc_recs))
        stats["problem_batch"] = float(np.mean(
            [r.get("problem_n", 0.0) for r in _pbc_recs]))
    if _saux_recs:
        stats["strength_aux_loss"] = float(np.mean(
            [r["strength_aux_loss"] for r in _saux_recs]))
        stats["strength_mse"] = float(np.mean(
            [r.get("strength_mse", 0.0) for r in _saux_recs]))
        stats["strength_bce"] = float(np.mean(
            [r.get("strength_bce", 0.0) for r in _saux_recs]))
        stats["strength_tier_acc"] = float(np.mean(
            [r.get("strength_tier_acc", 0.0) for r in _saux_recs]))
        stats["strength_aux_coef"] = float(
            getattr(cfg, "strength_aux_coef", 0.0) or 0.0)
        stats["strength_aux_every"] = int(
            getattr(cfg, "strength_aux_every", 1) or 1)
        stats["strength_aux_steps"] = int(len(_saux_recs))
        stats["strength_batch"] = float(np.mean(
            [r.get("strength_n", 0.0) for r in _saux_recs]))
    if _pbc_recs or _saux_recs:
        stats["problem_min_strength_delta"] = float(
            getattr(cfg, "problem_min_strength_delta", 0.0) or 0.0)
        stats["problem_turn_weight"] = str(
            getattr(cfg, "problem_turn_weight", "") or "")
    if not (_pbc_recs or _saux_recs):
        cfg_echo = stats.get("config")
        if isinstance(cfg_echo, dict):
            for key in ("problem_bc_coef", "problem_bc_every", "problem_batch",
                        "problem_pool_path", "strength_aux_coef",
                        "strength_aux_every", "strength_tier_pos_weight",
                        "problem_turn_weight", "problem_min_strength_delta"):
                cfg_echo.pop(key, None)
    # 在线缩放教师 / 过程价值：只有真的算出损失才写 stats；默认关闭时连 config
    # 回显里的新键也去掉，保证与旧版本结构逐字节一致。
    _teach_recs = [r for r in logs if "teacher_bc_loss" in r]
    if _teach_recs:
        stats["teacher_bc_loss"] = float(np.mean(
            [r["teacher_bc_loss"] for r in _teach_recs]))
        stats["teacher_bc_coef"] = float(
            getattr(cfg, "teacher_bc_coef", 0.0) or 0.0)
        stats["teacher_samples"] = float(np.mean(
            [r.get("teacher_samples", 0.0) for r in _teach_recs]))
        stats["teacher_steps"] = int(len(_teach_recs))
    else:
        cfg_echo = stats.get("config")
        if isinstance(cfg_echo, dict):
            for key in ("teacher_bc_coef",):
                cfg_echo.pop(key, None)
    _proc_recs = [r for r in logs if "process_value_loss" in r]
    if _proc_recs:
        stats["process_value_loss"] = float(np.mean(
            [r["process_value_loss"] for r in _proc_recs]))
        stats["process_tavern_mse"] = float(np.mean(
            [r.get("process_tavern_mse", 0.0) for r in _proc_recs]))
        stats["process_casts_mse"] = float(np.mean(
            [r.get("process_casts_mse", 0.0) for r in _proc_recs]))
        stats["process_consume_mse"] = float(np.mean(
            [r.get("process_consume_mse", 0.0) for r in _proc_recs]))
        stats["process_value_coef"] = float(
            getattr(cfg, "process_value_coef", 0.0) or 0.0)
        stats["process_samples"] = float(np.mean(
            [r.get("process_samples", 0.0) for r in _proc_recs]))
        stats["process_steps"] = int(len(_proc_recs))
    else:
        cfg_echo = stats.get("config")
        if isinstance(cfg_echo, dict):
            for key in ("process_value_coef",):
                cfg_echo.pop(key, None)
    # 搜索行为混合（默认 eps=0 时连 config 回显里的新键也去掉，保持旧结构）
    if float(getattr(cfg, "behavior_mix_eps", 0.0) or 0.0) <= 0.0:
        cfg_echo = stats.get("config")
        if isinstance(cfg_echo, dict):
            for key in ("behavior_mix_eps", "behavior_mix_when",
                        "behavior_mix_max_per_turn", "behavior_mix_topk",
                        "behavior_mix_turns", "behavior_mix_max_ms",
                        "behavior_mix_exact"):
                cfg_echo.pop(key, None)
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


#: 复利结构先验的目标卡（放大器 + 引擎卡；与 docs/CHAIN_FUNNEL.md §7 同口径）
_REP_AMP_IDS = frozenset({
    "BG25_354", "BG25_354_G", "BG26_ICC_901", "BG26_ICC_901_G",
    "BG36_640", "BG36_640_G",
})
_REP_ENGINE_IDS = frozenset({
    "BG36_762", "BG36_762_G", "BG28_633", "BG28_633_G",
    "BG36_704", "BG36_704_G", "BG_LOE_077", "BG_LOE_077_G",
})


def _rep_card_flags() -> Dict[int, Tuple[int, int, int]]:
    """``cid → (is_golden, tier, target_kind)，target_kind：0 非目标/1 引擎/2 放大器``（引擎 catalog 顺序；失败返回空表）。"""
    try:
        import json as _json
        eng = load_engine()
        cat = _json.loads(eng.catalog_json())
    except BaseException:  # noqa: BLE001 - 引擎缺失时先验退化为空
        return {}
    out: Dict[int, Tuple[int, int, int]] = {}
    for c in cat:
        try:
            cid = int(c["cid"])
        except (KeyError, TypeError, ValueError):
            continue
        sid = str(c.get("id") or "")
        is_golden = 1 if sid.endswith("_G") else 0
        tier = int(c.get("tier") or 0)
        is_target = 2 if sid in _REP_AMP_IDS else (1 if sid in _REP_ENGINE_IDS else 0)
        out[cid] = (is_golden, tier, is_target)
    return out


class _ReplicationBias:
    """复利结构选牌先验（**collect 侧**，纯 obs ⇒ 零额外 I/O；默认不构造）。

    - **Discover**：``cards[card_choices]`` 是三连奖励 3 选 1 的候选时，对「候选含放大器/
      引擎卡」的 ``choose`` 位加 ``discover_w``（只加不减、只对合法位）；
    - **Triple**：商店里能凑三连（已持 2 张同名非金）的 ``buy`` 位 +``2*triple_w``；
      能凑对子（已持 1 张）+``triple_w``。

    两个系数都 <=0 时**不构造对象** ⇒ 采样路径逐位等价。
    """

    def __init__(self, discover_w: float = 0.0, triple_w: float = 0.0,
                 chain_w: float = 0.0, chain_ids: str = "",
                 reroll_bias_t8t9: float = 0.0) -> None:
        from hsbg.env.action_space_std import (A_BUY as _A_BUY, A_CHOOSE as _A_CHOOSE,
                                               N_CHOICE as _N_CHOICE, N_SHOP as _N_SHOP)
        from hsbg.env.obs_std import (SLICE_CARD_BOARD, SLICE_CARD_CHOICES,
                                      SLICE_CARD_HAND, SLICE_CARD_SHOP)
        self.discover_w = float(discover_w)
        self.triple_w = float(triple_w)
        self.chain_w = float(chain_w)
        self._chain_ids: set = set()
        self._cid2id: dict = {}
        if self.chain_w > 0.0:
            try:
                import hsbg_engine as _E2
                self._cid2id = {int(cc["cid"]): str(cc["id"])
                                for cc in json.loads(_E2.catalog_json())}
            except BaseException:  # noqa: BLE001
                self._cid2id = {}
            self._chain_ids = (set(str(x).strip() for x in str(chain_ids).split(",") if x.strip())
                               or {"BG21_015", "BG29_813", "BG36_245", "BG36_640"})
            self.reroll_bias_t8t9 = float(reroll_bias_t8t9)
        self._A_BUY = int(_A_BUY)
        self._A_CHOOSE = int(_A_CHOOSE)
        self._N_SHOP = int(_N_SHOP)
        self._N_CHOICE = int(_N_CHOICE)
        self._sl_board = SLICE_CARD_BOARD
        self._sl_hand = SLICE_CARD_HAND
        self._sl_shop = SLICE_CARD_SHOP
        self._sl_choices = SLICE_CARD_CHOICES
        self._flags = _rep_card_flags() if (self.discover_w > 0.0) else {}
        self.stats = {"discover_biased": 0, "triple_biased": 0, "pair_biased": 0}

    def _f(self, cid: int) -> Tuple[int, int, int]:
        return self._flags.get(int(cid), (0, 0, 0))

    def bias(self, features: Any, cards: Any, mask: Any, *,
             game_id: Any = None, seat: Any = None) -> Optional[np.ndarray]:
        m = np.asarray(mask, dtype=bool).reshape(-1)
        if m.size != N_ACTIONS:
            return None
        cc = np.asarray(cards).reshape(-1)
        v = None
        if self.discover_w > 0.0 and bool(m[self._A_CHOOSE:self._A_CHOOSE + self._N_CHOICE].any()):
            base = self._sl_choices.start
            for i in range(self._N_CHOICE):
                a = self._A_CHOOSE + i
                if not m[a]:
                    continue
                idx = base + i
                if idx >= cc.size:
                    break
                cid = int(cc[idx]) - 1
                if cid < 0:
                    continue
                if self._f(cid)[2]:
                    if v is None:
                        v = np.zeros(N_ACTIONS, dtype=np.float32)
                    v[a] += float(self.discover_w)
                    self.stats["discover_biased"] += 1
        if self.triple_w > 0.0 and bool(m[self._A_BUY:self._A_BUY + self._N_SHOP].any()):
            own: Dict[int, int] = {}
            for sl in (self._sl_board, self._sl_hand):
                for j in range(sl.start, min(sl.stop, cc.size)):
                    cid = int(cc[j]) - 1
                    if cid >= 0 and not self._f(cid)[0]:
                        own[cid] = own.get(cid, 0) + 1
            base = self._sl_shop.start
            for slot in range(self._N_SHOP):
                a = self._A_BUY + slot
                if not m[a]:
                    continue
                idx = base + slot
                if idx >= cc.size:
                    break
                cid = int(cc[idx]) - 1
                if cid < 0:
                    continue
                cnt = own.get(cid, 0)
                if cnt >= 2:
                    if v is None:
                        v = np.zeros(N_ACTIONS, dtype=np.float32)
                    v[a] += 2.0 * float(self.triple_w)
                    self.stats["triple_biased"] += 1
                elif cnt == 1:
                    if v is None:
                        v = np.zeros(N_ACTIONS, dtype=np.float32)
                    v[a] += float(self.triple_w)
                    self.stats["pair_biased"] += 1
        if self.chain_w > 0.0 and bool(m[self._A_BUY:self._A_BUY + self._N_SHOP].any()):
            base = self._sl_shop.start
            for slot in range(self._N_SHOP):
                a = self._A_BUY + slot
                if not m[a]:
                    continue
                idx = base + slot
                if idx >= cc.size:
                    break
                cid = int(cc[idx]) - 1
                if cid < 0:
                    continue
                sid = self._cid2id.get(cid, "")
                if not sid:
                    continue
                if sid.endswith("_G"):
                    sid = sid[:-2]
                if sid in self._chain_ids:
                    if v is None:
                        v = np.zeros(N_ACTIONS, dtype=np.float32)
                    v[a] += float(self.chain_w)
                    self.stats["chain_biased"] = self.stats.get("chain_biased", 0) + 1
        if float(getattr(self, "reroll_bias_t8t9", 0.0)) > 0.0 and bool(m[1]):
            try:
                from hsbg.env.obs_std import GLOBAL_FIELD_INDEX as _GFI
                fv = np.asarray(features, dtype=np.float32).reshape(-1)
                turn = int(round(float(fv[_GFI["turn"]]) * 20.0))
            except BaseException:  # noqa: BLE001
                turn = -1
            if turn in (8, 9):
                if v is None:
                    v = np.zeros(N_ACTIONS, dtype=np.float32)
                v[1] += float(self.reroll_bias_t8t9)
                self.stats["reroll_biased"] = self.stats.get("reroll_biased", 0) + 1
        return v


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
                 move_model: bool = True,
                 behavior_mix: Any = None) -> None:
        self.torch = _torch()
        self.model = model
        self.device = self.torch.device(device)
        self.config = config or CollectConfig()
        # 搜索作为行为策略的混合器（``BehaviorMixer``；None = 关闭，逐位等价旧路径）
        self._mix = behavior_mix
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
        # 换位去抖守卫（默认关闭 -> 不构造对象、零开销；见 docs/MOVE_GUARD.md）
        # 强制升本守卫（默认关闭 -> 恒等，逐位不变）
        self._fguard = ForcedUpgradeGuard(self.config)
        self._cguard = CompBuyBias(self.config)
        self._guard = (MoveGuard(cap=int(getattr(self.config, "move_cap",
                                                 DEFAULT_MOVE_CAP)),
                                 repeat_limit=int(getattr(
                                     self.config, "move_repeat_limit",
                                     DEFAULT_MOVE_REPEAT_LIMIT)))
                       if bool(getattr(self.config, "move_guard", False)) else None)
        # 流派软偏置（默认 coef=0 -> 不构造对象、零开销；见 docs/ARCHETYPE_BIAS.md）
        self._abias = None
        _ab_coef = float(getattr(self.config, "archetype_bias_coef", 0.0) or 0.0)
        if _ab_coef > 0.0:
            self._abias = ArchetypeBias(
                table_path=(str(getattr(self.config, "archetype_table", "") or "")
                            or ARCH_TABLE),
                model_path=(str(getattr(self.config, "archetype_model", "") or "")
                            or ARCH_MODEL),
                coef=_ab_coef,
                min_prob=float(getattr(self.config, "archetype_min_prob", 0.6) or 0.6),
                # 输入哈希缓存（默认关；命中率实测≈0，见 docs/PERF_COLLECT.md）
                cache=bool(getattr(self.config, "archetype_cache", False)),
                # 卡牌下标 → 卡 id（top_cards 分项用；引擎缺失时退化为不带卡牌分项）
                card_index_of=engine_card_id_lookup())
        # 复利结构选牌先验（默认 0 -> 不构造对象、零开销）
        _rep_dw = float(getattr(self.config, "collect_discover_bias", 0.0) or 0.0)
        _rep_tw = float(getattr(self.config, "collect_triple_bias", 0.0) or 0.0)
        _rep_cw = float(getattr(self.config, "collect_chain_buy_bias", 0.0) or 0.0)
        _rep_ids = str(getattr(self.config, "collect_chain_ids", "") or "")
        _rep_rb = float(getattr(self.config, "collect_reroll_bias_t8t9", 0.0) or 0.0)
        self._rep_bias = (_ReplicationBias(_rep_dw, _rep_tw, chain_w=_rep_cw,
                                           chain_ids=_rep_ids, reroll_bias_t8t9=_rep_rb)
                          if (_rep_dw > 0.0 or _rep_tw > 0.0 or _rep_cw > 0.0
                              or _rep_rb > 0.0) else None)
        if move_model:
            self.model.to(self.device)
        self.model.eval()

    def reset(self) -> None:
        # 一局开始：清空本局记录/回合计数（search/forced 计数保留，用于整次采集 meta）
        self.records = []
        self._n = 0
        self._turn_counts = {}
        # 守卫的**累计统计**跨局保留（采集 meta 需要整次采集的汇总）；
        # 只清「本回合已选动作」历史（key 本身含 game_id，状态天然按局隔离）。
        if self._guard is not None:
            self._guard.clear_state()
        if self._abias is not None:
            self._abias.clear_state()

    def move_guard_meta(self) -> Dict[str, Any]:
        """守卫统计（默认关闭 -> ``{}``，不新增 meta 键）。"""
        return {} if self._guard is None else self._guard.to_meta()

    def behavior_mix_meta(self) -> Dict[str, Any]:
        """搜索行为混合统计（未启用 -> ``{}``，不新增 meta 键）。"""
        return {} if self._mix is None else self._mix.stats()

    def archetype_bias_meta(self) -> Dict[str, Any]:
        """流派偏置统计（默认关闭 -> ``{}``，不新增 meta 键）。"""
        if self._abias is None:
            return {}
        out = self._abias.to_meta()
        if bool(getattr(self._abias, "cache_enabled", False)):
            out.update(self._abias.cache_meta())
        return out

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
        if self._fguard is not None and self._fguard.enabled:
            mask, _forced = self._fguard.rewrite(f, mask)
        if self._cguard is not None and self._cguard.enabled:
            mask, _biased = self._cguard.rewrite(f, c, mask)
        return f, c, mask

    def _turn_is_forced(self, game: Any, seat: int, mask: Any) -> bool:
        """本次决策是否会被「回合动作数上限」强制 EndTurn（与 ``_finish`` 同一判据）。

        搜索行为混合必须在**采样前**知道这件事：forced 决策不是行为分布采样，
        不该消耗一次搜索（也不该被记成 μ 的样本）。
        """
        limit = int(getattr(self.config, "max_actions_per_turn", 0) or 0)
        if limit <= 0 or not bool(mask[0]):
            return False
        key = (int(self.game_id), int(seat), int(getattr(game, "turn", -1)))
        return bool(self._turn_counts.get(key, 0) + 1 > limit)

    def _finish(self, game: Any, seat: int, f: Any, c: Any, mask: Any, *,
                action: int, logprob: float, value: float,
                target_pi: Optional[np.ndarray], out_pi: Optional[np.ndarray],
                guard_forced: bool = False,
                logp_mu: Optional[float] = None,
                logp_pi: Optional[float] = None,
                action_source: str = "pi") -> Decision:
        """收尾：回合守卫 → 写 record → 构造 Decision（decide/decide_batch 共用）。

        ``guard_forced=True``：换位守卫把合法动作清空后回退到 EndTurn（``mask`` 此时
        只剩 EndTurn），与回合数守卫同样按「环境确定性约束」记 ``forced``/logprob=0。

        ``logp_mu`` / ``logp_pi``：搜索行为混合（``behavior_mix``）专用。
        ``logp_pi`` = log π(a)（该动作在 π 下的对数概率，PPO 用它算 KL/approx_kl），
        ``logp_mu`` = log μ(a) = log((1−ε)π(a)+ε·π_search(a))（PPO 的 ratio 分母）。
        只有启用混合时才写这两个 record 字段（默认关闭 → record 字段集合不变）。
        """
        seat = int(seat)
        turn = int(getattr(game, "turn", -1))
        limit = int(getattr(self.config, "max_actions_per_turn", 0) or 0)
        # 守卫计数必须按「局」隔离：lock-step 下同一个 policy 服务多局
        key = (int(self.game_id), seat, turn)
        n_turn = self._turn_counts.get(key, 0) + 1
        self._turn_counts[key] = n_turn
        forced_turn = bool(limit > 0 and n_turn > limit and bool(mask[0]))
        forced = bool(forced_turn or guard_forced)

        legal = np.flatnonzero(mask)
        if legal.size == 0:
            action, logprob = 0, 0.0
        elif forced:
            # 守卫动作是**环境确定性约束**（delta 在 EndTurn 上），不是行为分布采样。
            # 记录 logprob=0 且 forced=True；PPO 的策略/aux loss 会排除这些样本，
            # 只保留 value/critic/回报链，避免伪造 on-policy ratio。
            action, logprob = 0, 0.0
            if forced_turn:
                self.forced_actions += 1
        if self._guard is not None:
            # 记录「实际执行」的动作：EndTurn/其它动作只更新 last_action，
            # Move 才计入本回合换位历史（供下一决策计算逆换位/重复/cap）。
            self._guard.note_action(action, game_id=self.game_id,
                                    seat=seat, turn=turn)
        if self._abias is not None:
            # 流派特征用的己方动作历史（只统计人类口径动作；机械动作不计）
            self._abias.note_action(action, game_id=self.game_id, seat=seat)
        rec: Dict[str, Any] = {
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
        }
        if ((self._mix is not None and self._mix.enabled)
                or int(getattr(self.config, "record_logp_mu", 0) or 0) > 0):
            # 搜索行为混合 / collect 侧采样 bias：μ 的 logprob（ratio 分母）与 π 的 logprob（KL 口径）。
            # 未混合/搜索失败的决策两者都等于按 π 采样的 logprob。
            _lp_pi = float(logprob) if logp_pi is None else float(logp_pi)
            _lp_mu = _lp_pi if logp_mu is None else float(logp_mu)
            rec["logp_pi"] = _lp_pi
            rec["logp_mu"] = _lp_mu
            rec["action_source"] = ("forced" if forced else str(action_source))
        self.records.append(rec)
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
        guard_forced = False
        if self._guard is not None:
            # 采样前改写 mask：被禁的 Move 位置 0；空掩码回退 EndTurn/原 mask。
            mask, guard_forced = self._guard.guarded_mask(
                mask, game_id=self.game_id, seat=seat,
                turn=int(getattr(game, "turn", -1)))
        # 流派软偏置：先用可见观测 + 己方动作历史做检测，拿到 245 维非负 bias。
        abias = (self._abias.bias(f, c, mask, game_id=self.game_id, seat=seat)
                 if self._abias is not None else None)
        # 复利结构先验（默认关闭 -> self._rep_bias 为 None -> 完全没这一支）
        if self._rep_bias is not None:
            _rb = self._rep_bias.bias(f, c, mask, game_id=self.game_id, seat=seat)
            if _rb is not None:
                abias = _rb if abias is None else (np.asarray(abias, np.float32) + _rb)
        if self._can_fast_act():
            # worker 侧采样：省掉 prior 回传 + 调用方 numpy softmax/采样
            seed = int(self._rng.integers(0, 2 ** 63 - 1))
            _lp_pi_ret = None
            if abias is None:
                # 关闭时**不传** bias 关键字：兼容旧 eval_fn 签名（逐位等价旧路径）
                a, lp, value = self.eval_fn.act(f, c, mask,
                                                float(self.config.temperature), seed)
            else:
                if (int(getattr(self.config, "record_logp_mu", 0) or 0) > 0
                        and hasattr(self.eval_fn, "act_mu_pi")):
                    a, lp, _pi_lp, value = self.eval_fn.act_mu_pi(
                        f, c, mask, float(self.config.temperature), seed, bias=abias)
                    _lp_pi_ret = float(_pi_lp)
                else:
                    a, lp, value = self.eval_fn.act(f, c, mask,
                                                    float(self.config.temperature), seed,
                                                    bias=abias)
            # 搜索作为行为策略（默认关闭）：fast-act 路径同样在采样后混合
            mix = None
            if (self._mix is not None and self._mix.enabled and not guard_forced
                    and bool(np.asarray(mask, dtype=bool).any())
                    and not self._turn_is_forced(game, seat, mask)):
                mix = self._mix.propose(
                    game, seat, self.game_id, action=int(a), logprob=float(lp),
                    f=f, c=c, mask=mask,
                    temperature=float(self.config.temperature), rng=self._rng)
            if mix is not None:
                a, lp = int(mix.action), float(mix.logp_pi)
            _lmu = None if mix is None else mix.logp_mu
            _lpi = None if mix is None else mix.logp_pi
            if mix is None and abias is not None and _lp_pi_ret is not None:
                _lmu, _lpi = float(lp), float(_lp_pi_ret)
            return self._finish(game, seat, f, c, mask, action=int(a),
                                logprob=float(lp),
                                value=float(value), target_pi=None, out_pi=None,
                                guard_forced=guard_forced,
                                logp_mu=_lmu,
                                logp_pi=_lpi,
                                action_source=(("search_mix" if mix.used_search
                                                else "pi_mix") if mix is not None
                                               else "pi"))

        logits, value = self._net_predict(f, c, mask, seat)
        if abias is not None:
            # 与 worker 侧同口径：logits + bias 后再 masked softmax / 温度
            logits = np.asarray(logits, dtype=np.float32) + abias
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
        # ── 搜索作为行为策略：以概率 ε 换成 μ=(1−ε)π+ε·π_search 采样 ──
        mix = None
        if (self._mix is not None and self._mix.enabled and not guard_forced
                and legal.size > 0
                and not self._turn_is_forced(game, seat, mask)):
            mix = self._mix.propose(
                game, seat, self.game_id, action=int(action),
                logprob=float(logprob), f=f, c=c, mask=mask,
                temperature=float(self.config.temperature), rng=self._rng)
        if mix is not None:
            action, logprob = int(mix.action), float(mix.logp_pi)
        return self._finish(game, seat, f, c, mask, action=action, logprob=logprob,
                            value=float(value), target_pi=target_pi, out_pi=mu,
                            guard_forced=guard_forced,
                            logp_mu=(None if mix is None else mix.logp_mu),
                            logp_pi=(None if mix is None else mix.logp_pi),
                            action_source=(("search_mix" if mix.used_search
                                            else "pi_mix") if mix is not None
                                           else "pi"))

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
            if gid is not None:
                self.game_id = int(gid)
            f, c, mask = self._observe(g, s)
            guard_forced = False
            if self._guard is not None:
                # 必须先按本行自己的 game_id 取历史，不能等批量采样后统一赋值
                mask, guard_forced = self._guard.guarded_mask(
                    mask, game_id=self.game_id, seat=s,
                    turn=int(getattr(g, "turn", -1)))
            abias = (self._abias.bias(f, c, mask, game_id=self.game_id, seat=s)
                     if self._abias is not None else None)
            if self._rep_bias is not None:
                _rb = self._rep_bias.bias(f, c, mask, game_id=self.game_id, seat=s)
                if _rb is not None:
                    abias = _rb if abias is None else (np.asarray(abias, np.float32) + _rb)
            prepared.append((g, s, gid, f, c, mask, guard_forced, abias))
        F = np.stack([p[3] for p in prepared]).astype(np.float32, copy=False)
        C = np.stack([p[4] for p in prepared]).astype(np.int64, copy=False)
        M = np.stack([p[5] for p in prepared]).astype(bool, copy=False)
        B = None
        if any(p[7] is not None for p in prepared):
            # 只有一部分行需要偏置时也整批传（未命中的行是全 0，等价于不加）
            B = np.zeros((len(prepared), N_ACTIONS), dtype=np.float32)
            for i, p in enumerate(prepared):
                if p[7] is not None:
                    B[i] = p[7]
        seed = int(self._rng.integers(0, 2 ** 63 - 1))
        lps_pi = None
        if B is None:
            # 关闭时**不传** bias 关键字：兼容旧 eval_fn 签名（逐位等价旧路径）
            acts, lps, vals = self.eval_fn.act_batch(F, C, M,
                                                     float(self.config.temperature), seed)
        elif (int(getattr(self.config, "record_logp_mu", 0) or 0) > 0
                and hasattr(self.eval_fn, "act_batch_mu_pi")):
            acts, lps, lps_pi, vals = self.eval_fn.act_batch_mu_pi(
                F, C, M, float(self.config.temperature), seed, bias=B)
        else:
            acts, lps, vals = self.eval_fn.act_batch(F, C, M,
                                                     float(self.config.temperature), seed,
                                                     bias=B)
        for i, (g, s, gid, f, c, mask, gf, _ab) in enumerate(prepared):
            if gid is not None:
                self.game_id = int(gid)
            a_i, lp_i = int(acts[i]), float(lps[i])
            _lmu_i = None if lps_pi is None else float(lps[i])
            _lpi_i = None if lps_pi is None else float(lps_pi[i])
            # 搜索作为行为策略（默认关闭）：只在非 forced 的关键决策上混合
            mix = None
            if (self._mix is not None and self._mix.enabled and not gf
                    and not self._turn_is_forced(g, s, mask)):
                mix = self._mix.propose(
                    g, s, self.game_id, action=a_i, logprob=lp_i, f=f, c=c,
                    mask=mask, temperature=float(self.config.temperature),
                    rng=self._rng)
            if mix is not None:
                a_i, lp_i = int(mix.action), float(mix.logp_pi)
            if mix is not None:
                _mu_fin, _pi_fin = mix.logp_mu, mix.logp_pi
            else:
                _mu_fin, _pi_fin = _lmu_i, _lpi_i
            out.append(self._finish(g, s, f, c, mask, action=a_i,
                                    logprob=float(lp_i),
                                    value=float(vals[i]), target_pi=None, out_pi=None,
                                    guard_forced=gf,
                                    logp_mu=_mu_fin,
                                    logp_pi=_pi_fin,
                                    action_source=(("search_mix"
                                                    if mix.used_search else "pi_mix")
                                                   if mix is not None else "pi")))
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
        "game_bot_strength": np.zeros(n, dtype=np.float32),
        "final_strength": np.zeros(n, dtype=np.float32),
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
        out["game_bot_strength"][i] = float(r.get("game_bot_strength", 0.0) or 0.0)
        out["final_strength"][i] = float(r.get("final_strength", 0.0) or 0.0)
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
    if any("reward" in r for r in records):
        # 势函数塑形的逐决策基础奖励（可选字段：默认关闭时输出键集合与旧版一致）
        out["rewards"] = np.asarray([float(r.get("reward", 0.0)) for r in records],
                                    dtype=np.float32)
    if any("teacher_action" in r for r in records):
        # 在线缩放教师标签（-1 = 本决策无标签；默认关闭时不产出）
        out["teacher_action"] = np.asarray(
            [int(r.get("teacher_action", -1)) for r in records], dtype=np.int16)
    if any("process_target" in r for r in records):
        # 过程价值目标 [n,3]（不可得为 NaN；默认关闭时不产出）
        rows = []
        for r in records:
            pt = r.get("process_target")
            if pt is None:
                rows.append([np.nan, np.nan, np.nan])
            else:
                rows.append([float(x) for x in np.asarray(pt, dtype=np.float32).reshape(3)])
        out["process_target"] = np.asarray(rows, dtype=np.float32)
    if any("logp_mu" in r for r in records):
        # 搜索行为混合（μ=(1−ε)π+ε·π_search）：ratio 分母 / KL 口径（默认关闭时不产出）
        out["behavior_logprobs"] = np.asarray(
            [float(r.get("logp_mu", r["old_logprob"])) for r in records],
            dtype=np.float32)
        out["pi_logprobs"] = np.asarray(
            [float(r.get("logp_pi", r["old_logprob"])) for r in records],
            dtype=np.float32)
    if seq_aux:
        # 动作序列辅助标签：同一 (game_id, seat, turn) 的动作集合（向量化一次算完）
        out[SEQ_TARGET_KEY] = seq_targets_from_records(records)
    return out


def build_batch_from_arrays(packed: Dict[str, np.ndarray], *, gamma: float = 1.0,
                            lam: float = 0.95, step_penalty: float = 0.0,
                            meta: Optional[Dict[str, Any]] = None,
                            adv_estimator: str = "gae",
                            power_alpha: float = 0.5,
                            power_kappa: float = 3.0,
                            power_normalize: bool = True,
                            power_cutoff: int = 0,
                            credit_timebase: str = "decision",
                            rank_utility_coef: float = 1.0,
                            terminal_strength_coef: float = 0.0,
                            game_weight_mode: str = "none",
                            game_weight_alpha: float = 0.5,
                            game_weight_beta: float = 0.5,
                            game_weight_floor: float = 0.5,
                            game_weight_cap: float = 2.0) -> "PPOBatch":
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

    ## 可选：``rewards`` = 逐决策基础奖励（势函数塑形）。只在**未构建**的 packed 上消费；
    ## 已含 advantages 的批次字典里 ``rewards`` 是最终奖励，不能当基础项重复相加。
    base_reward = None
    if "advantages" not in packed:
        base_reward = t.pop("rewards", None)
        if base_reward is not None:
            base_reward = np.asarray(base_reward, dtype=np.float32).reshape(-1)
            if base_reward.size != n:
                base_reward = None
    rewards = np.full(n, -float(step_penalty), dtype=np.float32)
    if base_reward is not None:
        rewards += base_reward
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
    rewards[last_of_ep] = (float(rank_utility_coef)
                           * np.asarray(util, dtype=np.float32)[last_of_ep]
                           - float(step_penalty))
    if float(terminal_strength_coef) != 0.0:
        _ls = log_strength_from_features(t["features"])
        rewards[last_of_ep] += (float(terminal_strength_coef)
                                * _ls[last_of_ep].astype(np.float32))
    if base_reward is not None:
        rewards[last_of_ep] += base_reward[last_of_ep]
    dones[last_of_ep] = 1.0

    advantages, returns = compute_gae(rewards, values, dones, gamma=gamma, lam=lam)
    merged_meta: Dict[str, Any] = dict(meta or {})
    merged_meta.update({"gamma": float(gamma), "lam": float(lam),
                        "step_penalty": float(step_penalty),
                        "dropped_unknown_rank": dropped, "episodes": int(ep)})
    adv_mode = str(adv_estimator).strip().lower()
    if adv_mode not in ("gae", "", "geom", "power"):
        raise ValueError(f"adv_estimator 只能是 gae|power|geom，得到 {adv_estimator!r}")
    if adv_mode not in ("gae", ""):
        # 与 build_batch_from_records 同一分支：默认 gae 不进这里（逐位等价）。
        mode = "geom" if adv_mode == "geom" else "power"
        advantages, returns, _diag = compute_credit(
            rewards, values, dones, mode=mode, gamma=float(gamma),
            lam=float(lam), alpha=float(power_alpha),
            kappa=float(power_kappa), cutoff=int(power_cutoff),
            normalize=bool(power_normalize),
            timebase=str(credit_timebase), turns=turns)
        merged_meta.update({
            "adv_estimator": mode,
            "credit": compact_diagnostics(_diag),
        })
    # 动作序列辅助标签：有则透传（缺字段/形状不符 -> None，不报错）
    seq_target = t.get(SEQ_TARGET_KEY)
    if seq_target is not None:
        seq_target = np.asarray(seq_target, dtype=np.uint8)
        if seq_target.shape != (n, N_ACTIONS):
            seq_target = None
        else:
            merged_meta["seq_aux"] = True
    # 在线缩放教师标签 / 过程价值目标：有则透传（缺字段/形状不符 -> None）
    teacher_action = t.get("teacher_action")
    if teacher_action is not None:
        teacher_action = np.asarray(teacher_action, dtype=np.int16).reshape(-1)
        if teacher_action.size != n:
            teacher_action = None
        else:
            merged_meta["teacher_aux"] = True
    process_target = t.get("process_target")
    if process_target is not None:
        process_target = np.asarray(process_target, dtype=np.float32)
        if tuple(process_target.shape) != (n, 3):
            process_target = None
        else:
            merged_meta["process_aux"] = True
    # 搜索行为混合：有则透传（缺字段/形状不符 -> None，ratio 退回 π_old）
    _bl = t.pop("behavior_logprobs", None)
    _pl = t.pop("pi_logprobs", None)
    behavior_logprobs = None
    pi_logprobs = None
    if _bl is not None:
        _a = np.asarray(_bl, dtype=np.float32).reshape(-1)
        if _a.size == n:
            behavior_logprobs = _a
            merged_meta["behavior_mix"] = True
    if _pl is not None:
        _a = np.asarray(_pl, dtype=np.float32).reshape(-1)
        if _a.size == n:
            pi_logprobs = _a
    if str(game_weight_mode) != "none":
        _gs = t.get("game_bot_strength")
        _gs_arr = (np.asarray(_gs, dtype=np.float32).reshape(-1)
                   if _gs is not None and np.asarray(_gs).size == n else None)
        if _gs_arr is None:
            merged_meta["game_weight_missing_strength"] = True
            _gs_arr = np.zeros(n, dtype=np.float32)
        _w, _wstats = _episode_advantage_weights(
            game_ids, seats, turns, _gs_arr,
            alpha=float(game_weight_alpha), beta=float(game_weight_beta),
            floor=float(game_weight_floor), cap=float(game_weight_cap))
        advantages = (np.asarray(advantages, dtype=np.float32) * _w).astype(np.float32)
        merged_meta["game_weight"] = _wstats
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
        teacher_action=teacher_action, process_target=process_target,
        behavior_logprobs=behavior_logprobs, pi_logprobs=pi_logprobs,
        final_strength=(lambda fs: None if fs is None else
                        np.asarray(fs, dtype=np.float32).reshape(-1)
                        if np.asarray(fs).size == n else None)(
                            t.get("final_strength")),
        final_tier=(lambda ft: None if ft is None else
                    np.asarray(ft, dtype=np.float32).reshape(-1)
                    if np.asarray(ft).size == n else None)(
                        t.get("final_tier")),
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
                      progress: bool = False,
                      adv_estimator: str = "gae",
                      power_alpha: float = 0.5,
                      power_kappa: float = 3.0,
                      power_normalize: bool = True,
                      power_cutoff: int = 0,
                      credit_timebase: str = "decision",
                      rank_utility_coef: float = 1.0,
                      terminal_strength_coef: float = 0.0) -> Tuple[PPOBatch, Dict[str, Any]]:
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
    shaper = RewardShaper(cfg, gamma=gamma)
    tier_tracker = TierTargetTracker(cfg)

    if mode == "self":
        if shaper.enabled:
            raise ValueError(
                "奖励塑形只支持 opponent=bot|weak（单 learner seat）；"
                "self 模式（8 座都是 learner）请设 shaping_coef=0")
        if tier_tracker.enabled:
            raise ValueError(
                "等级进度奖励只支持 opponent=bot|weak（单 learner seat）；"
                "self 模式（8 座都是 learner）请设 tier_target_coef=0")
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
        _curr_mult = float(getattr(cfg, "curriculum_gold_mult", 1.0) or 1.0)
        _teacher_on = bool(getattr(cfg, "teacher_bc", False))
        _process_on = bool(getattr(cfg, "process_value", False))
        _teacher = _ScalingTeacher() if _teacher_on else None
        for gi in range(int(cfg.games)):
            gid = int(cfg.game_id_offset) + gi
            policy.game_id = gid
            policy.reseed(int(cfg.seed) + gi)
            policy.reset()
            game = E.Game(seed=int(cfg.seed) + gi, config_json=_game_cfg())
            if _process_on:
                # consume 计数来自引擎事件日志；只在过程价值开启时打开（默认关闭零影响）
                game.set_record_log(True)
            tracker = TierTargetTracker(cfg)      # 每局独立状态（claimed/evaluated 隔离）
            steps = 0
            game_decisions = 0
            game_truncated = False
            rec_prev: Optional[int] = None
            phi_prev = 0.0
            _cur_turn = -1            # 经济课程：当前已应用金币倍数的回合
            _carry = 0                # 上一回合结束时 learner 的金币结余
            _consume_seen = 0         # consume 日志增量缓存
            while not game.is_over() and steps < int(cfg.max_steps):
                acted = False
                for p in range(N_PLAYERS):
                    if not game.needs_action(p):
                        continue
                    if int(p) == int(cfg.learner_seat):
                        # 经济课程：新回合第一次 learner 决策前放大「本回合收入」
                        if _curr_mult != 1.0 and int(game.turn) != _cur_turn:
                            _cur_turn = int(game.turn)
                            _apply_turn_gold(game, int(p), carry=_carry,
                                             mult=_curr_mult)
                        teacher_a = -1
                        process_t = None
                        if _teacher_on:
                            _view = json.loads(game.view(int(p)))
                            _me = _view.get("me") or {}
                            if _in_scaling_window(_me.get("gold"), _me.get("tier")):
                                teacher_a = int(_teacher.act_view(_view))
                        if _process_on:
                            _pj = json.loads(game.player_json(int(p)))
                            if isinstance(_pj.get("stats"), dict):
                                _consume_seen = _consume_count(game.log(), _consume_seen)
                                process_t = _process_target(
                                    _pj, consume=_consume_seen)
                        # 等级进度奖励：本回合第一条 decision 前检查一次 tier
                        tier_delta = tracker.observe(game, int(p))
                        phi_now = 0.0
                        if shaper.enabled:
                            phi_now = shaper.potential(game, int(p))
                            if rec_prev is not None:
                                shaper.attach(policy.records, rec_prev, gid,
                                              phi_prev, phi_now)
                        dec = policy.decide(game, int(p))
                        _rec = policy.records[-1]
                        if _teacher_on:
                            _rec["teacher_action"] = int(teacher_a)
                        if _process_on:
                            _rec["process_target"] = process_t
                        mask = mask_from_bytes(game.legal_mask(int(p)))
                        action = int(dec.action)
                        if not (0 <= action < N_ACTIONS and bool(mask[action])):
                            illegal += 1
                            action = int(np.flatnonzero(mask)[0]) if mask.any() else 0
                        game.step(int(p), action)
                        if _curr_mult != 1.0:
                            _carry = int(json.loads(game.player_json(int(p))).get(
                                "gold") or 0)
                        if shaper.enabled:
                            rec_prev = len(policy.records) - 1
                            phi_prev = phi_now
                        if tier_delta:
                            tracker.queue(len(policy.records) - 1, gid, tier_delta)
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
            if shaper.enabled and rec_prev is not None:
                # 局末/截断：Φ(terminal)=0。
                shaper.attach(policy.records, rec_prev, gid, phi_prev, 0.0)
            # tier-target 增量统一在势函数回填之后叠加（避免覆盖写互相踩）
            tracker.flush(policy.records)
            over = bool(game.is_over())
            if over:
                rank = int(list(game.placements())[int(cfg.learner_seat)])
                _attach_rank(policy.records, rank)
                # B10：终局盘面强度 log1p(Σatk+hp)（同一局所有记录共享）
                try:
                    _pj = json.loads(game.player_json(int(cfg.learner_seat)))
                    _fs = float(np.log1p(sum(
                        int(m.get("atk") or 0) + int(m.get("hp") or 0)
                        for m in (_pj.get("board") or []))))
                    for _r in policy.records:
                        _r["final_strength"] = float(_fs)
                except BaseException:  # noqa: BLE001 - 目标不可得不挂
                    pass
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
            games_meta[-1].update(tracker.stats())
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
        "curriculum_stage": str(getattr(cfg, "curriculum_stage", "none")),
        "curriculum_gold_mult": float(getattr(cfg, "curriculum_gold_mult", 1.0)),
        "teacher_bc": bool(getattr(cfg, "teacher_bc", False)),
        "process_value": bool(getattr(cfg, "process_value", False)),
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
    # 势函数塑形统计（默认关闭 -> 空 dict，不新增键）。
    collect_meta.update(shaper.stats(elapsed_s=float(time.time() - t0)))
    # 等级进度奖励统计（默认关闭 -> 空 dict，不新增键）。
    collect_meta.update(aggregate_tier_target(games_meta))
    # 换位去抖守卫统计（默认关闭 -> 空 dict，不新增键）。
    collect_meta.update(policy.move_guard_meta())
    # 流派软偏置统计（默认关闭 -> 空 dict，不新增键）。
    collect_meta.update(policy.archetype_bias_meta())
    if not records:
        raise RuntimeError(
            f"采集失败：{truncated}/{len(games_meta)} 局在 max_steps={int(cfg.max_steps)} "
            "内未结束（rank=0），没有可用轨迹。请增大 --max-steps、调整 --seed，或从已有 "
            "checkpoint 续训（随机网络可能陷入 Play/Cancel 循环）。")
    batch = build_batch_from_records(records, gamma=gamma, lam=lam,
                                     step_penalty=step_penalty, meta=collect_meta,
                                     seq_aux=bool(cfg.seq_aux),
                                     adv_estimator=adv_estimator,
                                     power_alpha=power_alpha,
                                     power_kappa=power_kappa,
                                     power_normalize=power_normalize,
                                     power_cutoff=power_cutoff,
                                     credit_timebase=credit_timebase,
                                     rank_utility_coef=rank_utility_coef,
                                     terminal_strength_coef=terminal_strength_coef)
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
    "aggregate_archetype_bias",
    # ── 对手强度课程（docs/BOARD_RAMP.md）──
    "BOARD_RAMP_MODES",
    "BOARD_RAMP_QUANTILES",
    "BOARD_RAMP_SURVIVE_TURN",
    "BOARD_RAMP_TIER4_PROXY_TURN",
    "BOARD_RAMP_SURVIVE_THRESHOLD",
    "BOARD_RAMP_TIER4_THRESHOLD",
    "BOARD_RAMP_DELAY_DECISIONS",
    "BOARD_RAMP_MAX_FORCED_PER_GAME",
    "parse_decisions",
    "parse_board_ramp",
    "parse_quantile_ramp",
    "board_ramp_at",
    "quantile_ramp_at",
    "BoardRampState",
    "BoardRampController",
    "ramp_progress_metrics",
    "board_ramp_history",
]
