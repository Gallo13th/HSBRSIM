"""upgrade 子集 DPO 成对损失（最小实现，**默认不接训练主循环**）。

``scripts/quality_monitor.py`` 实测 learner 的 tier 从 turn 9 起长期停在 4，而真实
10k+ MMR 在 t9+ 会到 5–6（``docs/TIER_TARGET.md``）。本模块提供一条最小路径：把
「真实高 MMR 玩家在该局面选了 upgrade」当 chosen、「当前策略在 masked softmax 下的
argmax」当 rejected，用 one-sided DPO 直接抬高 upgrade 的 log 概率：::

    L = -log σ(β · (log π_θ(a_human|x) - log π_θ(a_argmax|x)))

范围约束：只读 ``bc_samples.jsonl.gz`` 里 ``action_type=="upgrade"`` 的样本；观测
编码**完全复用** :mod:`hsbg.az.train.bc_aux`（``load_bc_samples`` + ``bc_obs_batch``），
不重写编码、不新增观测布局、不硬编码偏移；损失只在 upgrade 样本上算，不修改模型
状态、不碰 PPO/BC/seq 的默认路径。这里没有参考模型，rejected 是当前策略自己的
argmax，所以是「自我对比」的一侧 DPO；``argmax == chosen`` 的样本没有对比信号，
跳过，整批都被跳过时返回 0（保留计算图、不产生 NaN）。torch 惰性导入。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Tuple

import numpy as np

from hsbg.az.train.bc_aux import (
    DEFAULT_BC_SAMPLES_PATH,
    DEFAULT_MMR_MIN,
    bc_obs_batch,
    load_bc_samples,
)
from hsbg.az.train.common import N_ACTIONS
from hsbg.env import action_space_std as ACT

__all__ = [
    "UPGRADE_ACTION",
    "MASKED_LOGIT",
    "UpgradeSamples",
    "load_upgrade_samples",
    "masked_policy_logprobs",
    "dpo_pair_loss",
]

#: 标准动作空间里的 Upgrade 下标（``A_UPGRADE``）。
UPGRADE_ACTION: int = int(ACT.A_UPGRADE)

#: masked softmax 的非法位填充值（与 ``hsbg.az.train.ppo.MASKED_LOGIT`` 同值）。
MASKED_LOGIT: float = -1e9

#: 诊断/批量前向的默认分块大小（避免一次 forward 吃掉过多内存）。
DEFAULT_CHUNK: int = 1024


# ══════════════════════════════════════════════════════════════════════════
# 1. 样本池：upgrade 子集
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class UpgradeSamples:
    """upgrade 子集的 SoA 样本池（编码结果 + 诊断用的原始状态）。

    ``features`` / ``cards`` / ``action_mask`` 直接来自
    :func:`hsbg.az.train.bc_aux.bc_obs_batch`（部分观测 + 近似动作掩码）；
    ``tier`` / ``turn`` / ``mmr`` 保留原始状态，供离线诊断交叉统计使用。

    为兼容任务约定的 ``(obs_features, cards, action_index)`` 元组解包，
    ``iter(batch)`` 只产出这三项；``action_mask`` 通过属性访问。
    """

    features: np.ndarray          # float32[n, 3227]
    cards: np.ndarray             # int32[n, 124]
    action_index: np.ndarray      # int64[n]（恒为 UPGRADE_ACTION）
    action_mask: np.ndarray       # bool[n, 245]（近似合法动作掩码）
    tier: np.ndarray              # int16[n]（tier_known=False 时无意义）
    turn: np.ndarray              # int16[n]
    mmr: np.ndarray               # int32[n]
    tier_known: np.ndarray        # bool[n]
    turn_known: np.ndarray        # bool[n]
    path: str = ""
    mmr_min: int = DEFAULT_MMR_MIN
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.features.shape[0])

    def take(self, indices: Any) -> "UpgradeSamples":
        """按下标切片（DPO 每步无放回抽样用）：只复制选中行，元信息照抄。"""
        idx = np.asarray(indices, dtype=np.int64).reshape(-1)
        if idx.size and int(idx.max()) >= len(self):
            raise IndexError(f"take 下标越界：{int(idx.max())} >= {len(self)}")
        return UpgradeSamples(
            features=np.ascontiguousarray(self.features[idx]),
            cards=np.ascontiguousarray(self.cards[idx]),
            action_index=np.ascontiguousarray(self.action_index[idx]),
            action_mask=np.ascontiguousarray(self.action_mask[idx]),
            tier=np.ascontiguousarray(self.tier[idx]),
            turn=np.ascontiguousarray(self.turn[idx]),
            mmr=np.ascontiguousarray(self.mmr[idx]),
            tier_known=np.ascontiguousarray(self.tier_known[idx]),
            turn_known=np.ascontiguousarray(self.turn_known[idx]),
            path=self.path, mmr_min=self.mmr_min, meta=dict(self.meta))

    def __iter__(self) -> Iterator[np.ndarray]:
        """``obs_features, cards, action_index = batch``（任务约定的三项）。"""
        return iter((self.features, self.cards, self.action_index))


def load_upgrade_samples(path: str = DEFAULT_BC_SAMPLES_PATH,
                         mmr_min: int = DEFAULT_MMR_MIN,
                         limit: Optional[int] = None) -> UpgradeSamples:
    """加载 ``action_type=="upgrade"`` 的样本（``action_index`` 恒为 3）。

    直接复用 :func:`~hsbg.az.train.bc_aux.load_bc_samples` 的白名单/MMR/合法性过滤
    与 :func:`~hsbg.az.train.bc_aux.bc_obs_batch` 的部分观测编码：
    ``action_types=("upgrade",)`` 只保留白名单里的 upgrade；``actions=(3,)`` 再按
    动作下标硬过滤，保证标签与观测一致（防御脏数据）；``limit`` 是**保留条数**上限，
    ``None`` = 全量（按文件顺序）。返回 :class:`UpgradeSamples`，并对编码结果做一次
    形状/标签自检。
    """
    mmin = int(mmr_min)
    if mmin < 0:
        raise ValueError(f"mmr_min 必须 >= 0，得到 {mmr_min!r}")
    cap = None if limit is None else max(0, int(limit))
    pool = load_bc_samples(
        path,
        actions=np.asarray([UPGRADE_ACTION], dtype=np.int64),
        mmr_min=mmin,
        limit=cap,
        action_types=("upgrade",),
    )
    batch = bc_obs_batch(pool)
    n = len(batch)
    if n and bool((pool.action_index != UPGRADE_ACTION).any()):
        raise AssertionError("upgrade 子集里出现了非 3 的动作下标：动作过滤失效")
    return UpgradeSamples(
        features=np.asarray(batch.features, dtype=np.float32),
        cards=np.asarray(batch.cards, dtype=np.int64),
        action_index=np.asarray(batch.action_index, dtype=np.int64),
        action_mask=np.asarray(batch.action_mask, dtype=bool),
        tier=np.asarray(pool.tier, dtype=np.int16),
        turn=np.asarray(pool.turn, dtype=np.int16),
        mmr=np.asarray(pool.mmr, dtype=np.int32),
        tier_known=np.asarray(pool.tier_known, dtype=bool),
        turn_known=np.asarray(pool.turn_known, dtype=bool),
        path=str(getattr(pool, "path", path) or path),
        mmr_min=mmin,
        meta={"action_type": "upgrade", "action_index": UPGRADE_ACTION},
    )


# ══════════════════════════════════════════════════════════════════════════
# 2. torch 前向工具
# ══════════════════════════════════════════════════════════════════════════
def _torch():
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("torch 不可用：DPO 损失需要 `pip install torch`") from exc
    return torch


def _accepts_mask(model: Any) -> bool:
    """``model.forward`` 是否接受 ``mask`` 形参（entity=True / tiny=False）。"""
    try:
        params = inspect.signature(model.forward).parameters
    except (TypeError, ValueError):  # pragma: no cover - 非标准 callable
        return False
    return "mask" in params


def _model_device(model: Any):
    torch = _torch()
    for obj in (getattr(model, "parameters", None), getattr(model, "buffers", None)):
        if obj is None:
            continue
        for t in obj():
            return t.device
    return torch.device("cpu")


def _policy_logits(model: Any, features: Any, cards: Any, mask: Any):
    """统一调用 tiny / entity：返回 245 维策略 logits（shape ``[B, 245]``）。"""
    out = model(features, cards, mask) if _accepts_mask(model) \
        else model(features, cards)
    logits = out[0] if isinstance(out, (tuple, list)) else out
    if not hasattr(logits, "shape") or logits.shape[-1] != N_ACTIONS:
        raise ValueError(
            f"模型输出不是 [B, {N_ACTIONS}] 策略 logits：{type(logits)!r}")
    return logits


def _masked_log_softmax(logits: Any, mask: Any):
    """非法位填 :data:`MASKED_LOGIT` 后的 log-softmax（非法位概率严格 ≈ 0）。"""
    torch = _torch()
    z = logits.float().masked_fill(~mask.bool(), float(MASKED_LOGIT))
    return torch.log_softmax(z, dim=-1)


def masked_policy_logprobs(model: Any, batch: UpgradeSamples, *,
                           device: Optional[str] = None,
                           chunk: int = DEFAULT_CHUNK) -> np.ndarray:
    """批量算 masked log-prob（numpy，``[n, 245]`` float32，不保留计算图）。

    只做诊断（``scripts/dpo_upgrade_probe.py``）；**不改变** ``model`` 的
    train/eval 状态，调用方自行 ``model.eval()``。分块前向以限制内存。
    """
    torch = _torch()
    dev = torch.device(device) if device is not None else _model_device(model)
    n = len(batch)
    out = np.empty((n, N_ACTIONS), dtype=np.float32)
    step = max(1, int(chunk))
    with torch.no_grad():
        for a in range(0, n, step):
            b = min(n, a + step)
            x = torch.from_numpy(
                np.ascontiguousarray(batch.features[a:b], dtype=np.float32)).to(dev)
            c = torch.from_numpy(
                np.ascontiguousarray(batch.cards[a:b], dtype=np.int64)).to(dev)
            m = torch.from_numpy(
                np.ascontiguousarray(batch.action_mask[a:b], dtype=bool)).to(dev)
            logp = _masked_log_softmax(_policy_logits(model, x, c, m), m)
            out[a:b] = logp.detach().cpu().numpy()
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3. DPO 成对损失
# ══════════════════════════════════════════════════════════════════════════
def dpo_pair_loss(model: Any, batch: UpgradeSamples, beta: float = 0.1,
                  *, device: Optional[str] = None) -> Tuple[Any, float]:
    """upgrade 子集的 one-sided DPO 损失。

    前向一次得到 masked log-prob：

    - ``logp_chosen`` = ``log π_θ(a=3|x)``（人类 upgrade 动作）；
    - ``logp_rejected`` = ``log π_θ(a=argmax π_θ(·|x))``（当前策略的 masked argmax；
      argmax 的**下标选择** detach，梯度仍通过两侧 log-prob 回传）；
    - 跳过 ``argmax == chosen`` 的样本（当前策略已选 upgrade，无对比信号）；
    - ``loss = -logsigmoid(beta * (logp_chosen - logp_rejected))`` 在**接受样本**上取均值。

    返回 ``(loss, accept_rate)``：``loss`` 是 torch 标量（保留计算图；整批被跳过/为空
    时返回 0 标量），``accept_rate`` 是 ``接受样本数 / 总样本数``（float，0..1）。

    约束：``beta`` 必须是有限正数；``chosen`` 必须落在该样本的 ``action_mask`` 内
    （``bc_obs_batch`` 已保证；手工构造 batch 时若越界直接 ``ValueError``）。
    """
    torch = _torch()
    F = torch.nn.functional
    b = float(beta)
    if not np.isfinite(b) or b <= 0.0:
        raise ValueError(f"beta 必须是有限正数，得到 {beta!r}")
    dev = torch.device(device) if device is not None else _model_device(model)
    n = len(batch)
    if n <= 0:
        return torch.zeros((), dtype=torch.float32), 0.0

    x = torch.from_numpy(
        np.ascontiguousarray(batch.features, dtype=np.float32)).to(dev)
    c = torch.from_numpy(
        np.ascontiguousarray(batch.cards, dtype=np.int64)).to(dev)
    m = torch.from_numpy(
        np.ascontiguousarray(batch.action_mask, dtype=bool)).to(dev)
    chosen = torch.from_numpy(
        np.ascontiguousarray(batch.action_index, dtype=np.int64)).to(dev).reshape(-1)

    if bool(((chosen < 0) | (chosen >= N_ACTIONS)).any()):
        raise ValueError(f"action_index 越界（应在 0..{N_ACTIONS - 1}）")
    if not bool(m.gather(1, chosen.view(-1, 1)).all()):
        raise ValueError("chosen 动作不在 action_mask 内：无法计算 DPO 对数概率")

    logits = _policy_logits(model, x, c, m)
    logp = _masked_log_softmax(logits, m)
    rows = torch.arange(n, device=dev)
    logp_chosen = logp[rows, chosen]
    with torch.no_grad():
        rejected = logp.argmax(dim=-1)
    accept = rejected != chosen
    n_accept = int(accept.sum().item())
    rate = float(n_accept) / float(n)
    if n_accept == 0:
        # 没有对比信号：返回 0（保留计算图，避免 backward 报错 / NaN）
        return logits.sum() * 0.0, 0.0
    logp_rej = logp[rows, rejected]
    margin = b * (logp_chosen - logp_rej)
    loss = -F.logsigmoid(margin[accept]).mean()
    return loss, rate
