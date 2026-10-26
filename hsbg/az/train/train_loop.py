"""初期 AZ 训练入口：策略 CE(π) + 名次价值 CE(rank)。

- 目标函数与 docs/AZ_MCTS_SELFPLAY_DESIGN.md §4.3/§4.4 一致：
  ``L = CE(π_search, softmax(policy_logits)) + λ * CE(rank, softmax(rank_logits))``；
- 输入标准化统计（mean/std）从训练集估计并随 checkpoint 保存；
- 输出每 epoch loss、样本/秒（吞吐）、总耗时；最后做一次监督评估
  （value-rank 相关、policy top-1 与 π 一致率、掩码合法性）。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import numpy as np

from .common import N_ACTIONS, N_PLAYERS, RANK_UTILITY, masked_normalize
from .data import AZDataset
from .model import feature_stats

#: 训练只用已知名次样本（rank 1..8）；截断/未知名次样本不参与价值监督。
def _usable_mask(ds: AZDataset) -> np.ndarray:
    ranks = ds.arrays["ranks"].astype(np.int64)
    return (ranks >= 1) & (ranks <= N_PLAYERS)


def train_policy_value(model: Any, ds: AZDataset, *, epochs: int = 2, batch_size: int = 256,
                       lr: float = 1e-3, device: str = "cpu", seed: int = 0,
                       value_weight: float = 1.0, max_samples: Optional[int] = None,
                       log_every: int = 0) -> Dict[str, Any]:
    """监督训练一个 epoch 数很少的初始化网络（smoke 级）。

    返回 ``{"epochs": [...], "samples": n, "seconds": s, "samples_per_s": q,
    "norm_mean": ndarray, "norm_std": ndarray, "loss_first"/"loss_last": ...}``。
    """
    import torch
    import torch.nn.functional as F

    usable = np.flatnonzero(_usable_mask(ds))
    if usable.size == 0:
        raise ValueError("数据集中没有可用样本（ranks 全为 0）")
    if max_samples is not None and usable.size > int(max_samples):
        rng0 = np.random.default_rng(seed)
        usable = rng0.choice(usable, size=int(max_samples), replace=False)
    features = ds.arrays["features"][usable]
    masks = ds.arrays["masks"][usable].astype(bool)
    pi = ds.arrays["pi"][usable].astype(np.float32)
    ranks = ds.arrays["ranks"][usable].astype(np.int64)

    norm_mean, norm_std = feature_stats(features)
    x_all = (features - norm_mean) / norm_std

    dev = torch.device(device)
    model.to(dev)
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=float(lr))
    rng = np.random.default_rng(seed)
    n = int(usable.size)

    logs = []
    t_start = time.time()
    total_steps = 0
    for epoch in range(int(epochs)):
        order = rng.permutation(n)
        ep_loss = 0.0
        ep_policy = 0.0
        ep_value = 0.0
        nb = 0
        for start in range(0, n, int(batch_size)):
            sel = order[start:start + int(batch_size)]
            x = torch.from_numpy(np.ascontiguousarray(x_all[sel])).to(dev)
            target_pi = torch.from_numpy(np.ascontiguousarray(pi[sel])).to(dev)
            target_rank = torch.from_numpy(ranks[sel] - 1).to(dev)
            m = torch.from_numpy(np.ascontiguousarray(masks[sel])).to(dev)
            opt.zero_grad(set_to_none=True)
            plog, rlog = model(x)
            logp = F.log_softmax(plog, dim=-1)
            # 只在合法动作上算 CE（pi 在非法位为 0，mask 后归一）
            logp = torch.where(m, logp, torch.full_like(logp, -1e9))
            target = torch.where(m, target_pi, torch.zeros_like(target_pi))
            target = target / target.sum(dim=-1, keepdim=True).clamp_min(1e-8)
            loss_p = -(target * logp).sum(dim=-1).mean()
            loss_v = F.cross_entropy(rlog, target_rank)
            loss = loss_p + float(value_weight) * loss_v
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            ep_loss += float(loss.item())
            ep_policy += float(loss_p.item())
            ep_value += float(loss_v.item())
            nb += 1
            total_steps += 1
            if log_every and total_steps % int(log_every) == 0:
                print(f"[train] step {total_steps} loss={float(loss.item()):.4f}", flush=True)
        elapsed = time.time() - t_start
        rec = {
            "epoch": epoch + 1,
            "loss": ep_loss / max(nb, 1),
            "policy_loss": ep_policy / max(nb, 1),
            "value_loss": ep_value / max(nb, 1),
            "samples": n,
            "steps": nb,
            "elapsed_s": elapsed,
            "samples_per_s": float(n * (epoch + 1) / max(elapsed, 1e-9)),
        }
        logs.append(rec)
        print(f"[train] epoch {epoch+1}/{epochs} loss={rec['loss']:.4f} "
              f"(policy={rec['policy_loss']:.4f} value={rec['value_loss']:.4f}) "
              f"{rec['samples_per_s']:.0f} samples/s", flush=True)
    model.eval()
    total_s = time.time() - t_start
    return {
        "epochs": logs,
        "samples": n,
        "seconds": total_s,
        "samples_per_s": float(n * max(int(epochs), 1) / max(total_s, 1e-9)),
        "loss_first": logs[0]["loss"] if logs else None,
        "loss_last": logs[-1]["loss"] if logs else None,
        "norm_mean": norm_mean,
        "norm_std": norm_std,
        "train_indices": usable,
    }


def evaluate_supervised(model: Any, ds: AZDataset, *, norm_mean: Optional[np.ndarray] = None,
                        norm_std: Optional[np.ndarray] = None, device: str = "cpu",
                        batch_size: int = 512, limit: int = 20000) -> Dict[str, Any]:
    """监督评估：value-rank 相关、policy top-1 与搜索 π 一致率、合法率、熵。"""
    import torch

    usable = np.flatnonzero(_usable_mask(ds))
    if usable.size == 0:
        return {"samples": 0}
    if usable.size > limit:
        usable = usable[np.linspace(0, usable.size - 1, int(limit)).astype(np.int64)]
    features = ds.arrays["features"][usable]
    masks = ds.arrays["masks"][usable].astype(bool)
    pi = ds.arrays["pi"][usable].astype(np.float32)
    ranks = ds.arrays["ranks"][usable].astype(np.int64)
    if norm_mean is None:
        norm_mean, norm_std = feature_stats(features)
    x_all = (features - norm_mean) / norm_std
    dev = torch.device(device)
    model.to(dev)
    model.eval()
    preds_v: list = []
    agree, total = 0, 0
    with torch.no_grad():
        for start in range(0, len(usable), int(batch_size)):
            x = torch.from_numpy(np.ascontiguousarray(x_all[start:start + int(batch_size)])).to(dev)
            plog, rlog = model(x)
            plog = plog.detach().cpu().numpy()
            rlog = rlog.detach().cpu().numpy()
            m = masks[start:start + int(batch_size)]
            z = rlog - rlog.max(axis=-1, keepdims=True)
            p = np.exp(z)
            p = p / p.sum(axis=-1, keepdims=True)
            preds_v.append((p * RANK_UTILITY.astype(np.float64)).sum(axis=-1))
            for i in range(plog.shape[0]):
                pv = masked_normalize(plog[i], m[i])
                if int(np.argmax(pv)) == int(np.argmax(pi[start + i])):
                    agree += 1
                total += 1
    pred_v = np.concatenate(preds_v)
    util = ds.arrays["utility"][usable]
    corr = float(np.corrcoef(pred_v, util)[0, 1]) if len(pred_v) > 2 else None
    return {
        "samples": int(total),
        "value_rank_corr": corr,
        "policy_top1_agreement": float(agree / max(total, 1)),
        "pred_value_mean": float(np.mean(pred_v)),
        "target_utility_mean": float(np.mean(util)),
        "pred_value_min": float(np.min(pred_v)),
        "pred_value_max": float(np.max(pred_v)),
    }


__all__ = ["train_policy_value", "evaluate_supervised"]
