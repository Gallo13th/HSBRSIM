"""PPO 训练器（候选动作 masked softmax + 名次分布价值）。

要点
----
* **策略**：对每步的合法候选动作打分，masked softmax 采样；PPO 的
  clipped surrogate 直接作用在候选分布上（天然支持变长动作集）。
* **价值**：``distribution`` 模式下用 ``E[rank]`` 映射出的标量做 GAE，同时
  在终局步用名次交叉熵训练整条名次分布；``scalar`` 模式退化为普通回归。
* **GAE(λ)**：按并行环境分别展开；truncated 按 done 处理（近似）。
* **稳定性**：advantage 标准化、梯度裁剪、KL 早停、熵正则、value 裁剪。
* **可复现**：seed 固定环境与 torch；checkpoint 内嵌策略 config/词表/PPO
  config 与训练进度，``PPOTrainer.load`` 可续训。

主循环::

    trainer = PPOTrainer(policy, encoder, PPOConfig(device="cpu"))
    result = trainer.train(env, total_steps=3000, out_dir="runs/smoke_ppo")
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from hsbg.policy.encoder import ObservationEncoder
from hsbg.policy.model import EntityTransformerPolicy
from hsbg.train.buffer import RolloutBuffer
from hsbg.train.evaluate import PolicyAgent, evaluate_agent
from hsbg.train.logger import CSVLogger, write_json


@dataclass
class PPOConfig:
    """PPO / 训练管线超参。"""

    # ── 优化 ──
    lr: float = 3e-4
    gamma: float = 0.99
    lam: float = 0.95
    clip: float = 0.2
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    #: 分布价值头的名次交叉熵权重（仅分布价值模式生效）
    rank_ce_coef: float = 0.5
    epochs: int = 4
    minibatch_size: int = 256
    max_grad_norm: float = 0.5
    #: approx_kl 超过 ``1.5 * target_kl`` 时提前结束该轮更新（0/None 关闭）
    target_kl: Optional[float] = 0.02
    # ── 数据处理 ──
    normalize_adv: bool = True
    #: returns 标准化：会破坏分布价值 [-1,1] 尺度，默认关闭（见 buffer 文档）
    normalize_returns: bool = False
    #: 每轮 rollout 的步数（每个并行环境）
    n_steps: int = 256
    #: 奖励缩放系数（环境奖励已按 spec 设计，一般保持 1.0）
    reward_scale: float = 1.0
    # ── 运行 ──
    seed: int = 0
    device: str = "cpu"
    lr_schedule: str = "constant"  # constant | linear
    lr_final_frac: float = 0.2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PPOConfig":
        allowed = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**allowed)


class PPOTrainer:
    """在线 PPO 训练器。"""

    def __init__(
        self,
        policy: EntityTransformerPolicy,
        encoder: ObservationEncoder,
        config: Optional[PPOConfig] = None,
        *,
        device: Optional[str] = None,
    ) -> None:
        self.policy = policy
        self.encoder = encoder
        self.config = config or PPOConfig()
        self.device = torch.device(device or self.config.device)
        self.policy.to(self.device)
        self.optimizer = torch.optim.Adam(
            self.policy.parameters(), lr=self.config.lr
        )
        self._gen = torch.Generator(device="cpu")
        self._gen.manual_seed(self.config.seed)
        self._rng = np.random.default_rng(self.config.seed)
        self._ep_return: Optional[np.ndarray] = None
        self._ep_steps: Optional[np.ndarray] = None
        self._ep_invalid: Optional[np.ndarray] = None
        self._ep_returns_hist: List[float] = []
        self._ep_lengths_hist: List[int] = []
        self._ep_placements_hist: List[int] = []
        self._ep_invalid_total = 0
        #: 每个并行环境最近一次被引擎拒绝的候选：(观测指纹, 候选下标集合)
        self._banned: List[Optional[Tuple[Tuple[Any, ...], set]]] = []

    # ══════════════════════════════════════════════════════════════
    # rollout 采集
    # ══════════════════════════════════════════════════════════════
    def _reset_banned(self, num_envs: int) -> None:
        if len(self._banned) != num_envs:
            self._banned = [None] * num_envs

    def _apply_rejected_mask(
        self, batch: Dict[str, torch.Tensor], obs_keys: Sequence[Tuple[Any, ...]]
    ) -> None:
        """屏蔽同一观测下已被引擎拒绝的候选下标（防止"拒绝→同一动作"死循环）。"""
        if not self._banned:
            return
        mask = batch["cand_mask"]
        n_cand = int(mask.shape[1])
        for i, entry in enumerate(self._banned):
            if entry is None or i >= len(obs_keys):
                continue
            key, banned = entry
            if key != obs_keys[i] or not banned:
                self._banned[i] = None
                continue
            for action in banned:
                if 0 <= action < n_cand:
                    mask[i, action] = 0.0
            if float(mask[i].sum()) <= 0.0:
                # 所有候选都被拒（环境异常）：恢复单候选兜底，避免整行无动作
                mask[i] = 0.0
                mask[i, 0] = 1.0
                self._banned[i] = None

    def _remember_rejected(
        self, env_index: int, obs_key: Tuple[Any, ...], action: int
    ) -> None:
        if env_index >= len(self._banned):
            return
        entry = self._banned[env_index]
        if entry is not None and entry[0] == obs_key:
            entry[1].add(action)
        else:
            self._banned[env_index] = (obs_key, {action})

    def collect_rollout(
        self,
        env: Any,
        obs_list: Optional[Sequence[Any]] = None,
        *,
        n_steps: Optional[int] = None,
    ) -> Tuple[RolloutBuffer, List[Any], Dict[str, float]]:
        """采集 ``n_steps`` 步（每个并行环境），返回 ``(buffer, 最新观测, 统计)``。"""
        cfg = self.config
        n_steps = int(n_steps or cfg.n_steps)
        num_envs = int(getattr(env, "num_envs", len(obs_list or [])))
        if obs_list is None:
            obs_list = env.reset()
        if self._ep_return is None or len(self._ep_return) != num_envs:
            self._ep_return = np.zeros(num_envs, dtype=np.float64)
            self._ep_steps = np.zeros(num_envs, dtype=np.int64)
            self._ep_invalid = np.zeros(num_envs, dtype=np.int64)
        self._reset_banned(num_envs)
        buffer = RolloutBuffer(n_steps, num_envs, device=self.device)
        self.policy.eval()
        for _ in range(n_steps):
            obs_keys = [_obs_key(o) for o in obs_list]
            batch = self.encoder.collate(obs_list, device=self.device)
            # 防御：真环境偶尔对"候选动作"返回 invalid（引擎拒绝但状态不变）。
            # 此时同一观测会反复给出同一动作 → 屏蔽已被拒的候选下标再采样。
            self._apply_rejected_mask(batch, obs_keys)
            with torch.no_grad():
                actions, logp, values = self.policy.act(
                    batch, greedy=False, generator=self._gen
                )
            next_obs, rewards, dones, infos = env.step(actions.tolist())
            rewards = np.asarray(rewards, dtype=np.float32) * cfg.reward_scale
            buffer.add(batch, actions, logp, values, rewards, dones, infos)
            # 统计 episode 级指标
            self._ep_return += rewards
            self._ep_steps += 1
            for i, info in enumerate(infos):
                invalid = bool(info.get("invalid", False))
                if invalid:
                    self._ep_invalid[i] += 1
                    self._ep_invalid_total += 1
                    self._remember_rejected(i, obs_keys[i], int(actions[i]))
                if bool(dones[i]):
                    rank = int(info.get("rank", 0) or 0)
                    self._ep_returns_hist.append(float(self._ep_return[i]))
                    self._ep_lengths_hist.append(int(self._ep_steps[i]))
                    if rank > 0:
                        self._ep_placements_hist.append(rank)
                    self._ep_return[i] = 0.0
                    self._ep_steps[i] = 0
                    self._ep_invalid[i] = 0
                    self._banned[i] = None
            obs_list = next_obs
        # 最后一步的状态价值（用于 GAE bootstrap）
        final_batch = self.encoder.collate(obs_list, device=self.device)
        with torch.no_grad():
            _, last_values = self.policy(final_batch)
        buffer.compute_gae(last_values, gamma=cfg.gamma, lam=cfg.lam)
        if cfg.normalize_adv:
            buffer.normalize_advantages()
        if cfg.normalize_returns:
            buffer.normalize_returns()
        stats = buffer.stats()
        stats.update(
            {
                "episode_return_mean": _tail_mean(self._ep_returns_hist, 50),
                "episode_length_mean": _tail_mean(self._ep_lengths_hist, 50),
                "placement_mean": _tail_mean(self._ep_placements_hist, 50),
                "episodes_finished": float(len(self._ep_returns_hist)),
                "invalid_actions": float(self._ep_invalid_total),
                "advantage_mean": float(buffer.advantages.mean().item()) if buffer.advantages is not None else 0.0,
                "advantage_std": float(buffer.advantages.std().item()) if buffer.advantages is not None else 0.0,
            }
        )
        return buffer, list(obs_list), stats

    # ══════════════════════════════════════════════════════════════
    # 更新
    # ══════════════════════════════════════════════════════════════
    def update(self, buffer: RolloutBuffer) -> Dict[str, float]:
        """在 buffer 上做多 epoch minibatch PPO 更新。"""
        cfg = self.config
        if buffer.advantages is None or buffer.returns is None:
            raise RuntimeError("buffer 缺少 GAE 结果（请先 collect_rollout / compute_gae）")
        self.policy.train()
        num_samples = len(buffer) * buffer.num_envs
        minibatch_size = max(1, min(int(cfg.minibatch_size), num_samples))
        dist_value = self.policy.config.value_mode == "distribution"

        sums: Dict[str, float] = {
            "policy_loss": 0.0,
            "value_loss": 0.0,
            "rank_ce": 0.0,
            "entropy": 0.0,
            "approx_kl": 0.0,
            "clipfrac": 0.0,
            "grad_norm": 0.0,
            "value_abs_error": 0.0,
        }
        n_batches = 0
        n_epochs_done = 0
        early_stopped = False
        for _epoch in range(cfg.epochs):
            n_epochs_done += 1
            for mb in buffer.iterate_minibatches(
                minibatch_size, generator=self._gen
            ):
                obs_batch = mb["obs"]
                actions = mb["actions"]
                old_logp = mb["old_logp"]
                adv = mb["advantages"]
                returns = mb["returns"]
                ranks = mb["ranks"]

                if dist_value:
                    logp, entropy, values, rank_logits = self.policy.evaluate_actions(
                        obs_batch, actions, return_rank_logits=True
                    )
                else:
                    logp, entropy, values = self.policy.evaluate_actions(obs_batch, actions)
                    rank_logits = None

                # ── clipped surrogate ──
                log_ratio = logp - old_logp
                ratio = log_ratio.exp()
                surr1 = ratio * adv
                surr2 = ratio.clamp(1.0 - cfg.clip, 1.0 + cfg.clip) * adv
                policy_loss = -torch.min(surr1, surr2).mean()

                # ── 价值 ──
                value_loss = F.mse_loss(values, returns)
                if dist_value and rank_logits is not None:
                    rank_mask = ranks >= 1
                    if bool(rank_mask.any()):
                        rank_ce = F.cross_entropy(
                            rank_logits[rank_mask],
                            (ranks[rank_mask] - 1).clamp(0, rank_logits.shape[-1] - 1),
                        )
                    else:
                        rank_ce = torch.zeros((), device=values.device)
                else:
                    rank_ce = torch.zeros((), device=values.device)

                loss = (
                    policy_loss
                    + cfg.value_coef * value_loss
                    + cfg.rank_ce_coef * rank_ce
                    - cfg.entropy_coef * entropy.mean()
                )
                self.optimizer.zero_grad(set_to_none=True)
                loss.backward()
                grad_norm = torch.nn.utils.clip_grad_norm_(
                    self.policy.parameters(), cfg.max_grad_norm
                )
                self.optimizer.step()

                with torch.no_grad():
                    approx_kl = ((ratio - 1.0) - log_ratio).mean()
                    clipfrac = ((ratio - 1.0).abs() > cfg.clip).float().mean()
                sums["policy_loss"] += float(policy_loss.item())
                sums["value_loss"] += float(value_loss.item())
                sums["rank_ce"] += float(rank_ce.item())
                sums["entropy"] += float(entropy.mean().item())
                sums["approx_kl"] += float(approx_kl.item())
                sums["clipfrac"] += float(clipfrac.item())
                sums["grad_norm"] += float(grad_norm)
                sums["value_abs_error"] += float((values - returns).abs().mean().item())
                n_batches += 1
            # KL 早停（一轮 epoch 结束后检查该轮平均 KL）
            if cfg.target_kl:
                epoch_kl = sums["approx_kl"] / max(n_batches, 1)
                if epoch_kl > 1.5 * float(cfg.target_kl):
                    early_stopped = True
                    break
        stats = {k: v / max(n_batches, 1) for k, v in sums.items()}
        stats["update_epochs"] = float(n_epochs_done)
        stats["update_minibatches"] = float(n_batches)
        stats["early_stopped"] = float(early_stopped)
        stats["lr"] = float(self.optimizer.param_groups[0]["lr"])
        # 清理 buffer，避免下次误用
        buffer.reset()
        return stats

    # ══════════════════════════════════════════════════════════════
    # 主训练循环
    # ══════════════════════════════════════════════════════════════
    def train(
        self,
        env: Any,
        total_steps: int,
        *,
        out_dir: Optional[Path] = None,
        eval_env: Any = None,
        eval_every: int = 0,
        eval_games: int = 8,
        save_every: int = 0,
        verbose: bool = True,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """主循环：rollout → update → 日志 →（可选）评测 / checkpoint。

        返回 ``{"history": [...], "evals": [...], "checkpoint": path, ...}``。
        """
        if total_steps <= 0:
            raise ValueError("total_steps 必须 > 0")
        cfg = self.config
        num_envs = int(getattr(env, "num_envs", 1))
        out_dir = Path(out_dir) if out_dir is not None else None
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "train_log.csv" if out_dir else None
        eval_path = out_dir / "eval_log.csv" if out_dir else None
        csv_log = CSVLogger(log_path, **_LOG_FIELDS) if log_path else None
        eval_log = CSVLogger(eval_path, **_EVAL_FIELDS) if eval_path else None

        # 训练开始前清空 episode 统计
        self._ep_returns_hist.clear()
        self._ep_lengths_hist.clear()
        self._ep_placements_hist.clear()
        self._ep_invalid_total = 0
        self._ep_return = None
        self._banned = []

        obs_list = env.reset()
        history: List[Dict[str, Any]] = []
        evals: List[Dict[str, Any]] = []
        steps_done = 0
        started = time.time()
        final_checkpoint: Optional[Path] = None
        while steps_done < total_steps:
            remaining = total_steps - steps_done
            rollout_steps = int(min(cfg.n_steps, math.ceil(remaining / num_envs)))
            rollout_steps = max(1, rollout_steps)
            self._apply_lr_schedule(steps_done, total_steps)
            t0 = time.time()
            buffer, obs_list, rollout_stats = self.collect_rollout(
                env, obs_list, n_steps=rollout_steps
            )
            rollout_time = time.time() - t0
            t1 = time.time()
            update_stats = self.update(buffer)
            update_time = time.time() - t1
            steps_done += rollout_steps * num_envs
            row: Dict[str, Any] = {
                "step": steps_done,
                "rollout_steps": rollout_steps,
                "num_envs": num_envs,
                **rollout_stats,
                **update_stats,
                "rollout_time_s": rollout_time,
                "update_time_s": update_time,
            }
            history.append(row)
            if csv_log is not None:
                csv_log.log(row)
            if verbose:
                print(
                    f"[ppo] step={steps_done:6d} "
                    f"ret={row.get('episode_return_mean', 0.0):+.3f} "
                    f"rank={row.get('placement_mean', 0.0):.2f} "
                    f"pi={row['policy_loss']:+.4f} v={row['value_loss']:.4f} "
                    f"rank_ce={row['rank_ce']:.4f} ent={row['entropy']:.3f} "
                    f"kl={row['approx_kl']:+.4f} clip={row['clipfrac']:.3f}"
                )
            # 评测
            if eval_env is not None and eval_every and steps_done % eval_every < rollout_steps * num_envs:
                eval_row = self._run_eval(eval_env, eval_games)
                eval_row["step"] = steps_done
                evals.append(eval_row)
                if eval_log is not None:
                    eval_log.log(eval_row)
                if verbose:
                    print(f"[ppo] eval @ {steps_done}: "
                          f"mean_rank={eval_row['mean_rank']:.3f} "
                          f"win={eval_row['win_rate']:.3f} top_half={eval_row['top_half_rate']:.3f}")
            # 定期 checkpoint
            if out_dir is not None and save_every and steps_done % save_every == 0:
                final_checkpoint = self.save_checkpoint(
                    out_dir / f"policy_step_{steps_done}.pt",
                    meta=self._meta(steps_done, total_steps, extra_meta),
                )
        # ── 收尾 ──
        if out_dir is not None:
            final_checkpoint = self.save_checkpoint(
                out_dir / "policy_final.pt",
                meta=self._meta(steps_done, total_steps, extra_meta),
            )
            write_json(out_dir / "summary.json", {
                "steps": steps_done,
                "num_envs": num_envs,
                "wall_time_s": time.time() - started,
                "policy_config": self.policy.config.to_dict(),
                "ppo_config": cfg.to_dict(),
                "params": self.policy.count_parameters(),
                "history": history,
                "evals": evals,
                "checkpoint": str(final_checkpoint) if final_checkpoint else None,
                "trainer": "ppo",
            })
        else:
            from hsbg.paths import ensure_runs_dir

            final_checkpoint = self.save_checkpoint(
                ensure_runs_dir("ppo") / "policy_final.pt",
                meta=self._meta(steps_done, total_steps, extra_meta),
            )
        if csv_log is not None:
            csv_log.close()
        if eval_log is not None:
            eval_log.close()
        return {
            "history": history,
            "evals": evals,
            "steps": steps_done,
            "checkpoint": str(final_checkpoint) if final_checkpoint else None,
            "params": self.policy.count_parameters(),
            "wall_time_s": time.time() - started,
        }

    # ── 辅助 ──
    def _run_eval(self, eval_env: Any, games: int) -> Dict[str, Any]:
        agent = PolicyAgent(
            self.policy, self.encoder, device=str(self.device), greedy=True
        )
        result = evaluate_agent(agent, eval_env, games=games)
        self.policy.eval()
        return result.as_dict()

    def _apply_lr_schedule(self, steps_done: int, total_steps: int) -> None:
        cfg = self.config
        if cfg.lr_schedule != "linear":
            return
        frac = min(max(steps_done / max(total_steps, 1), 0.0), 1.0)
        lr = cfg.lr * (1.0 - (1.0 - cfg.lr_final_frac) * frac)
        for group in self.optimizer.param_groups:
            group["lr"] = lr

    def save_checkpoint(
        self,
        path: Path,
        *,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Path:
        meta = dict(meta or {})
        meta.setdefault("ppo_config", self.config.to_dict())
        meta.setdefault("params", self.policy.count_parameters())
        return self.policy.save(path, meta=meta)

    def _meta(
        self,
        steps_done: int,
        total_steps: int,
        extra: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "trainer": "ppo",
            "steps_done": int(steps_done),
            "total_steps": int(total_steps),
            "seed": int(self.config.seed),
            "device": str(self.device),
            "ppo_config": self.config.to_dict(),
            "params": self.policy.count_parameters(),
            "episode_return_mean": _tail_mean(self._ep_returns_hist, 100),
            "placement_mean": _tail_mean(self._ep_placements_hist, 100),
        }
        if extra:
            meta.update(extra)
        return meta

    @classmethod
    def load(
        cls,
        checkpoint_path: Path,
        *,
        config: Optional[PPOConfig] = None,
        device: Optional[str] = None,
    ) -> "PPOTrainer":
        """从 checkpoint 恢复策略/编码器/PPO 配置（续训入口）。"""
        policy = EntityTransformerPolicy.load(checkpoint_path, map_location="cpu")
        encoder = policy.make_encoder()
        if config is None:
            cfg_dict = (policy.meta or {}).get("ppo_config") or {}
            config = PPOConfig.from_dict(cfg_dict)
        return cls(policy, encoder, config, device=device)


# ══════════════════════════════════════════════════════════════════════
# 日志字段
# ══════════════════════════════════════════════════════════════════════

_LOG_FIELDS: Dict[str, Any] = {
    "fieldnames": [
        "step", "rollout_steps", "num_envs",
        "episode_return_mean", "episode_length_mean", "placement_mean",
        "episodes_finished", "rollout_reward_mean", "rollout_value_mean",
        "rollout_placement_mean", "invalid_actions",
        "advantage_mean", "advantage_std",
        "policy_loss", "value_loss", "rank_ce", "entropy",
        "approx_kl", "clipfrac", "grad_norm", "value_abs_error",
        "early_stopped", "update_epochs", "update_minibatches", "lr",
        "rollout_time_s", "update_time_s",
    ]
}

_EVAL_FIELDS: Dict[str, Any] = {
    "fieldnames": [
        "step", "games", "mean_rank", "win_rate", "top_half_rate",
        "mean_return", "mean_steps", "missing_rank", "timeout_games",
    ]
}


def _obs_key(obs: Any) -> Tuple[Any, ...]:
    """观测指纹（用于判断两次决策之间环境状态是否真的变了）。"""
    hero = getattr(obs, "hero", None)
    candidates = getattr(obs, "candidates", ()) or ()
    return (
        int(getattr(obs, "turn", 0) or 0),
        str(getattr(obs, "phase", "")),
        int(getattr(hero, "gold", -1)) if hero is not None else -1,
        len(candidates),
        tuple(c.signature() for c in candidates),
    )


def _tail_mean(values: Sequence[float], n: int = 50) -> float:
    if not values:
        return 0.0
    tail = list(values)[-n:]
    return float(sum(tail) / len(tail))


def train_ppo(
    env: Any,
    policy: EntityTransformerPolicy,
    encoder: ObservationEncoder,
    *,
    config: Optional[PPOConfig] = None,
    total_steps: int = 3000,
    out_dir: Optional[Path] = None,
    eval_env: Any = None,
    eval_every: int = 0,
    eval_games: int = 8,
    save_every: int = 0,
    verbose: bool = True,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """函数式入口（等价于 ``PPOTrainer(...).train(...)``）。"""
    trainer = PPOTrainer(policy, encoder, config)
    return trainer.train(
        env,
        total_steps,
        out_dir=out_dir,
        eval_env=eval_env,
        eval_every=eval_every,
        eval_games=eval_games,
        save_every=save_every,
        verbose=verbose,
        extra_meta=extra_meta,
    )


__all__ = ["PPOConfig", "PPOTrainer", "train_ppo"]
