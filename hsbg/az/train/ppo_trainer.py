"""持久 PPO trainer：同一个 Adam/调度器/RNG 跨多个 iteration。

当前 ``scripts/train_az_ppo.py`` 每个进程只调一次 ``train_ppo``，Adam 每次重建；
``train_az_ppo_loop.py`` 又用子进程循环，优化器状态无法保留。本模块提供
``PPOTrainer``：

- 持有 model / Adam / LambdaLR / numpy Generator；
- ``update(batch)`` 调用 ``train_ppo(..., optimizer=..., rng=...)``；
- ``state_dict()/load_state_dict()`` 持久化优化器、调度器、RNG 和 update 计数；
- 不建议跨进程“伪续训”：每个进程必须 load 完整 trainer state。

注意：短实验可接受每轮重置 Adam；P0 baseline 用本类。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from .ppo import PPOConfig, PPOBatch, _torch, train_ppo


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
        if state is not None:
            self.load_state_dict(state)

    def update(self, batch: PPOBatch) -> Dict[str, Any]:
        stats = train_ppo(self.model, batch, self.config,
                          optimizer=self.optimizer, rng=self.rng)
        self.scheduler.step()
        self.updates += 1
        stats["trainer_updates"] = int(self.updates)
        stats["lr"] = float(self.optimizer.param_groups[0]["lr"])
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
        }

    def load_state_dict(self, state: Dict[str, Any]) -> None:
        self.model.load_state_dict(state["model"])
        self.optimizer.load_state_dict(state["optimizer"])
        self.scheduler.load_state_dict(state["scheduler"])
        self.rng.bit_generator.state = state["rng"]
        self.updates = int(state.get("updates", 0))

    def save(self, path: str) -> str:
        import os
        torch = _torch()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        torch.save(self.state_dict(), path)
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
        return cls(model, cfg, lr_min_ratio=float(state.get("lr_min_ratio", 0.1)),
                   max_updates=int(state.get("max_updates", 100000)), state=state)


__all__ = ["PPOTrainer"]
