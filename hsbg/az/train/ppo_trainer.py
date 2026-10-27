"""持久 PPO trainer：同一个 Adam/调度器/RNG 跨多个 iteration。

当前 ``scripts/train_az_ppo.py`` 每个进程只调一次 ``train_ppo``，Adam 每次重建；
``train_az_ppo_loop.py`` 又用子进程循环，优化器状态无法保留。本模块提供
``PPOTrainer``：

- 持有 model / Adam / LambdaLR / numpy Generator；
- ``update(batch)`` 调用 ``train_ppo(..., optimizer=..., rng=...)``；
- ``state_dict()/load_state_dict()`` 持久化优化器、调度器、RNG 和 update 计数；
- **KL anchor**：``set_anchor()`` 冻结 stage 起点策略，``config.anchor_coef`` > 0 时
  在损失里加 ``β·KL(π_θ ‖ π_anchor)``（AutoTavern 论文 Table 7：β=0.1，前 100 个
  iteration）。anchor 分布对整个 batch 只算一次（no_grad），再按 minibatch 切片，
  因此额外开销 ≈ 每 iteration 一次前向，而不是每个 minibatch 一次；
- 不建议跨进程“伪续训”：每个进程必须 load 完整 trainer state。

注意：短实验可接受每轮重置 Adam；P0 baseline 用本类。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

import numpy as np

from .ppo import (PPOConfig, PPOBatch, _torch, forward_model,
                  masked_log_softmax_torch, split_model_outputs, train_ppo)


class PPOTrainer:
    """单模型、单 learner 的持久 PPO 更新器。"""

    def __init__(self, model: Any, config: Optional[PPOConfig] = None, *,
                 lr_min_ratio: float = 0.1, max_updates: int = 100000,
                 state: Optional[Dict[str, Any]] = None):
        torch = _torch()
        self.model = model
        self.config = config or PPOConfig()
        self.device = torch.device(self.config.device)
        self.model.to(self.device)
        self.model.eval()
        self.lr_min_ratio = float(lr_min_ratio)
        self.max_updates = max(1, int(max_updates))
        self.optimizer = torch.optim.Adam(
            self.model.parameters(), lr=float(self.config.lr))
        self.scheduler = torch.optim.lr_scheduler.LambdaLR(
            self.optimizer,
            lr_lambda=lambda step: max(
                self.lr_min_ratio,
                1.0 - (1.0 - self.lr_min_ratio) * float(step) / float(self.max_updates)),
        )
        self.rng = np.random.default_rng(int(self.config.seed))
        self.updates = 0
        self.extra: Dict[str, Any] = {}
        #: KL anchor（stage 起点策略的冻结副本）；由 ``set_anchor()`` 建立
        self.anchor_model: Optional[Any] = None
        if state is not None:
            self.load_state_dict(state)

    # -- KL anchor ---------------------------------------------------------
    def set_anchor(self) -> None:
        """把当前策略冻结为 stage 起点 anchor（不参与梯度、不进 optimizer）。"""
        torch = _torch()
        self.anchor_model = copy.deepcopy(self.model).to(self.device)
        self.anchor_model.eval()
        for p in self.anchor_model.parameters():
            p.requires_grad_(False)
        self.extra["anchor_set"] = True

    def clear_anchor(self) -> None:
        self.anchor_model = None
        self.extra["anchor_set"] = False

    def _anchor_logp(self, batch: PPOBatch, chunk: int = 4096) -> Any:
        """整个 batch 上的 anchor masked log-prob，形状 ``[n, 245]``（no_grad）。"""
        torch = _torch()
        if self.anchor_model is None:
            raise RuntimeError("anchor_coef>0 但未 set_anchor()")
        outs = []
        device = self.device
        with torch.no_grad():
            for start in range(0, len(batch), int(chunk)):
                sl = slice(start, start + int(chunk))
                x = torch.from_numpy(
                    np.ascontiguousarray(batch.features[sl].astype(np.float32))).to(device)
                c = torch.from_numpy(
                    np.ascontiguousarray(batch.cards[sl].astype(np.int64))).to(device)
                m = torch.from_numpy(
                    np.ascontiguousarray(batch.masks[sl].astype(bool))).to(device)
                out = forward_model(self.anchor_model, x, c, m)
                logits, _rank_logits, _scalar = split_model_outputs(out)
                outs.append(masked_log_softmax_torch(logits, m))
        return torch.cat(outs, dim=0) if len(outs) > 1 else outs[0]

    # -- update ------------------------------------------------------------
    def update(self, batch: PPOBatch) -> Dict[str, Any]:
        anchor_logp = None
        if float(self.config.anchor_coef) > 0.0:
            anchor_logp = self._anchor_logp(batch)
        stats = train_ppo(self.model, batch, self.config,
                          optimizer=self.optimizer, rng=self.rng,
                          anchor_logp=anchor_logp)
        self.scheduler.step()
        self.updates += 1
        stats["trainer_updates"] = int(self.updates)
        stats["lr"] = float(self.optimizer.param_groups[0]["lr"])
        stats["anchor_coef"] = float(self.config.anchor_coef)
        return stats

    def state_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "scheduler": self.scheduler.state_dict(),
            "rng": self.rng.bit_generator.state,
            "updates": int(self.updates),
            "lr_min_ratio": float(self.lr_min_ratio),
            "max_updates": int(self.max_updates),
            "config": dict(self.config.__dict__),
            "extra": dict(self.extra),
        }

    def load_state_dict(self, state: Dict[str, Any]) -> None:
        self.model.load_state_dict(state["model"])
        self.optimizer.load_state_dict(state["optimizer"])
        # 恢复 scheduler 的超参后再重建，避免新实例参数覆盖旧 schedule
        self.lr_min_ratio = float(state.get("lr_min_ratio", self.lr_min_ratio))
        self.max_updates = int(state.get("max_updates", self.max_updates))
        torch = _torch()
        self.scheduler = torch.optim.lr_scheduler.LambdaLR(
            self.optimizer,
            lr_lambda=lambda step: max(
                self.lr_min_ratio,
                1.0 - (1.0 - self.lr_min_ratio) * float(step) / float(self.max_updates)),
        )
        self.scheduler.load_state_dict(state["scheduler"])
        # LambdaLR.load_state_dict 只恢复 last_epoch，不会重算 lr；显式对齐
        for group, lr in zip(self.optimizer.param_groups, self.scheduler.get_last_lr()):
            group["lr"] = float(lr)
        self.rng.bit_generator.state = state["rng"]
        self.updates = int(state.get("updates", 0))
        self.extra = dict(state.get("extra") or {})

    def save(self, path: str) -> str:
        import os
        torch = _torch()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        tmp = path + ".tmp"
        torch.save(self.state_dict(), tmp)
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, model: Any, path: str, config: Optional[PPOConfig] = None, *,
             device: str = "cpu") -> "PPOTrainer":
        torch = _torch()
        try:
            state = torch.load(path, map_location=device, weights_only=False)
        except TypeError:  # torch < 2.0
            state = torch.load(path, map_location=device)
        cfg = config or PPOConfig(**state.get("config", {}))
        cfg.device = str(device)
        return cls(model, cfg, lr_min_ratio=float(state.get("lr_min_ratio", 0.1)),
                   max_updates=int(state.get("max_updates", 100000)), state=state)


__all__ = ["PPOTrainer"]
