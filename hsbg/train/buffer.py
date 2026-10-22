"""PPO rollout 缓冲 + GAE(λ) + minibatch 迭代。

张量布局：``[T, B, ...]``（T=rollout 步数，B=并行环境数），存储的是**编码后
的观测 batch**（``hsbg.policy.encoder.ENCODED_KEYS``），因此更新阶段不需要
重新编码观测，也天然支持变长候选（统一 padding 到 ``CANDIDATE_MAX``）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

import numpy as np
import torch

from hsbg.policy.encoder import ENCODED_KEYS

#: 终局名次缺失时的填充值
NO_RANK = -1


class RolloutBuffer:
    """按时间步存储 rollout 数据，并提供 GAE 与 minibatch 迭代。

    用法::

        buf = RolloutBuffer(n_steps, num_envs, device)
        for _ in range(n_steps):
            buf.add(obs_batch, actions, logp, values, rewards, dones, infos)
        buf.compute_gae(last_values, gamma, lam)
        buf.normalize_advantages()
        for mb in buf.iterate_minibatches(256):
            ...  # mb["obs"], mb["actions"], mb["old_logp"], mb["advantages"], ...
    """

    def __init__(self, n_steps: int, num_envs: int, device: Any = "cpu") -> None:
        self.n_steps = int(n_steps)
        self.num_envs = int(num_envs)
        self.device = torch.device(device)
        self._obs: List[Dict[str, torch.Tensor]] = []
        self._actions: List[torch.Tensor] = []
        self._logp: List[torch.Tensor] = []
        self._values: List[torch.Tensor] = []
        self._rewards: List[torch.Tensor] = []
        self._dones: List[torch.Tensor] = []
        self._ranks: List[torch.Tensor] = []
        self.advantages: Optional[torch.Tensor] = None
        self.returns: Optional[torch.Tensor] = None

    # ── 采集 ──
    def add(
        self,
        obs_batch: Dict[str, torch.Tensor],
        actions: torch.Tensor,
        logp: torch.Tensor,
        values: torch.Tensor,
        rewards: np.ndarray,
        dones: np.ndarray,
        infos: List[Dict[str, Any]],
    ) -> None:
        """存入一步数据（``infos`` 里取 ``rank`` 作为终局名次分类标签）。"""
        dev = self.device
        self._obs.append({k: obs_batch[k] for k in ENCODED_KEYS})
        self._actions.append(actions.detach().to(dev).long().reshape(-1))
        self._logp.append(logp.detach().to(dev).float().reshape(-1))
        self._values.append(values.detach().to(dev).float().reshape(-1))
        self._rewards.append(torch.as_tensor(np.asarray(rewards, dtype=np.float32), device=dev))
        self._dones.append(torch.as_tensor(np.asarray(dones, dtype=np.float32), device=dev))
        ranks = torch.full((self.num_envs,), NO_RANK, dtype=torch.long, device=dev)
        for i, info in enumerate(infos):
            if bool(dones[i]):
                rank = info.get("rank", NO_RANK)
                try:
                    rank = int(rank)
                except (TypeError, ValueError):
                    rank = NO_RANK
                if 1 <= rank <= 64:
                    ranks[i] = rank
        self._ranks.append(ranks)

    def __len__(self) -> int:
        return len(self._actions)

    @property
    def full(self) -> bool:
        return len(self) >= self.n_steps

    def reset(self) -> None:
        self._obs.clear()
        self._actions.clear()
        self._logp.clear()
        self._values.clear()
        self._rewards.clear()
        self._dones.clear()
        self._ranks.clear()
        self.advantages = None
        self.returns = None

    # ── GAE ──
    def compute_gae(
        self,
        last_values: torch.Tensor,
        gamma: float = 0.99,
        lam: float = 0.95,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """GAE(λ)。返回 ``(advantages[T,B], returns[T,B])``。

        ``dones`` 同时覆盖 terminated/truncated：truncated 不做 bootstrap
        （向量环境 auto-reset 后拿不到终局观测，按 done 处理是常见近似）。
        """
        T = len(self)
        if T == 0:
            raise RuntimeError("RolloutBuffer 为空，无法计算 GAE")
        rewards = torch.stack(self._rewards, dim=0)
        values = torch.stack(self._values, dim=0)
        dones = torch.stack(self._dones, dim=0)
        last_values = last_values.detach().to(self.device).float().reshape(-1)
        adv = torch.zeros_like(values)
        gae = torch.zeros(self.num_envs, device=self.device, dtype=torch.float32)
        for t in reversed(range(T)):
            next_values = last_values if t == T - 1 else values[t + 1]
            nonterminal = 1.0 - dones[t]
            delta = rewards[t] + gamma * next_values * nonterminal - values[t]
            gae = delta + gamma * lam * nonterminal * gae
            adv[t] = gae
        self.advantages = adv
        self.returns = adv + values
        return adv, self.returns

    def normalize_advantages(self, eps: float = 1e-8) -> None:
        if self.advantages is None:
            raise RuntimeError("请先 compute_gae")
        adv = self.advantages
        self.advantages = (adv - adv.mean()) / (adv.std(unbiased=False) + eps)

    def normalize_returns(self, eps: float = 1e-8) -> None:
        """把 returns 标准化成 ~N(0,1)。

        注意：分布价值头的 value 被限制在 ``[-1, 1]``（期望名次映射），对
        returns 做标准化会破坏这个尺度，训练侧默认**关闭**。
        """
        if self.returns is None:
            raise RuntimeError("请先 compute_gae")
        ret = self.returns
        self.returns = (ret - ret.mean()) / (ret.std(unbiased=False) + eps)

    # ── 迭代 ──
    def flatten(self) -> Dict[str, Any]:
        """``[T,B,...]`` → ``[T*B,...]``（只做 reshape，不复制数据）。"""
        if len(self) == 0:
            raise RuntimeError("RolloutBuffer 为空")
        T, B = len(self), self.num_envs
        obs: Dict[str, torch.Tensor] = {}
        for key in ENCODED_KEYS:
            stacked = torch.stack([step[key] for step in self._obs], dim=0)
            obs[key] = stacked.reshape((T * B,) + tuple(stacked.shape[2:]))
        out: Dict[str, Any] = {
            "obs": obs,
            "actions": torch.stack(self._actions, dim=0).reshape(T * B),
            "old_logp": torch.stack(self._logp, dim=0).reshape(T * B),
            "old_values": torch.stack(self._values, dim=0).reshape(T * B),
            "rewards": torch.stack(self._rewards, dim=0).reshape(T * B),
            "dones": torch.stack(self._dones, dim=0).reshape(T * B),
            "ranks": torch.stack(self._ranks, dim=0).reshape(T * B),
        }
        if self.advantages is not None:
            out["advantages"] = self.advantages.reshape(T * B)
        if self.returns is not None:
            out["returns"] = self.returns.reshape(T * B)
        return out

    def sample_indices(
        self,
        minibatch_size: int,
        generator: Optional[torch.Generator] = None,
    ) -> Iterator[torch.Tensor]:
        """按随机顺序产出 minibatch 下标。"""
        total = len(self) * self.num_envs
        minibatch_size = max(1, int(minibatch_size))
        # 2026-10-18 Lead 修复: torch.Generator 的设备必须与 randperm 一致。
        # 训练侧随机数生成器通常固定在 CPU（seed_everything 保证可复现），
        # 而 buffer 在 CUDA 上；在任何设备上生成排列再移到 buffer 设备即可
        # （排列只用于索引，语义与设备无关）。
        if generator is None:
            perm = torch.randperm(total, device=self.device)
        else:
            perm = torch.randperm(total, generator=generator).to(self.device)
        for start in range(0, total, minibatch_size):
            yield perm[start : start + minibatch_size]

    def iterate_minibatches(
        self,
        minibatch_size: int,
        generator: Optional[torch.Generator] = None,
    ) -> Iterator[Dict[str, Any]]:
        """产出 ``{"obs", "actions", "old_logp", "advantages", "returns", "ranks"}``。"""
        data = self.flatten()
        for idx in self.sample_indices(minibatch_size, generator=generator):
            yield {
                "obs": {k: v[idx] for k, v in data["obs"].items()},
                "actions": data["actions"][idx],
                "old_logp": data["old_logp"][idx],
                "old_values": data["old_values"][idx],
                "advantages": data["advantages"][idx],
                "returns": data["returns"][idx],
                "ranks": data["ranks"][idx],
            }

    def stats(self) -> Dict[str, float]:
        """rollout 层面的简单统计（日志用）。"""
        if len(self) == 0:
            return {}
        rewards = torch.stack(self._rewards, dim=0)
        values = torch.stack(self._values, dim=0)
        dones = torch.stack(self._dones, dim=0)
        ranks = torch.stack(self._ranks, dim=0)
        done_mask = ranks >= 1
        placement = ranks[done_mask].float()
        return {
            "rollout_reward_mean": float(rewards.mean().item()),
            "rollout_value_mean": float(values.mean().item()),
            "rollout_done_frac": float(dones.mean().item()),
            "rollout_placement_mean": float(placement.mean().item()) if placement.numel() else 0.0,
            "rollout_episodes": int(done_mask.sum().item()),
        }

    def to_pickle_dict(self) -> Dict[str, Any]:
        """导出成可 pickle 的 dict（调试/离线分析用，不用于长期存储格式）。"""
        data = self.flatten()
        return {k: (v if not isinstance(v, dict) else v) for k, v in data.items()}


__all__ = ["RolloutBuffer", "NO_RANK"]
