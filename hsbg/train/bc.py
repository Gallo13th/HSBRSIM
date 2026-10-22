"""行为克隆（BC）：数据集收集 + 监督训练。

用法概览
--------
::

    from hsbg.train.bc import collect_bc_dataset, BCTrainer, BCConfig, make_policy_teacher
    dataset = collect_bc_dataset(env, teacher=make_policy_teacher(policy, encoder), episodes=8)
    trainer = BCTrainer(policy, encoder, BCConfig(epochs=5))
    result = trainer.fit(dataset, val_frac=0.2)

教师（teacher）可以是：

* ``callable(Observation) -> int`` —— 单条观测返回候选下标；
* 任何实现 ``act(obs_list) -> List[int]`` 的对象（见 ``hsbg.train.evaluate``）；
* ``None`` → 退化为 :class:`hsbg.train.evaluate.HeuristicAgent`（候选级启发式）。

注意：``hsbg.agents.registry.make_opponent('heuristic')`` 是**引擎级**对手
（输入 game/hero），不能直接用于观测级 BC；若要用它当教师，需要环境层提供
"观测 → 动作" 的适配（Lead 集成时确认）。
"""

from __future__ import annotations

import pickle
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import torch
import torch.nn.functional as F

from hsbg.env.spec import CANDIDATE_MAX, Observation
from hsbg.policy.encoder import ENCODED_KEYS, ObservationEncoder
from hsbg.policy.model import EntityTransformerPolicy
from hsbg.train.evaluate import HeuristicAgent, PolicyAgent
from hsbg.train.logger import CSVLogger, format_metrics_table, write_json

#: 数据集文件格式版本
DATASET_VERSION = 1


# ══════════════════════════════════════════════════════════════════════
# 数据集
# ══════════════════════════════════════════════════════════════════════


@dataclass
class BCDataset:
    """教师示范数据集：``(Observation, 候选动作下标)`` + 所属 episode 的终局名次。"""

    samples: List[Tuple[Observation, int]] = field(default_factory=list)
    #: 每个样本所在 episode 的终局名次（1 起；-1 = 未知），用于可选价值监督
    ranks: List[int] = field(default_factory=list)
    #: 每个样本所属 episode 编号（用于按 episode 划分验证集）
    episode_ids: List[int] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    # ── 基本操作 ──
    def add(
        self,
        obs: Observation,
        action: int,
        *,
        rank: int = -1,
        episode_id: int = 0,
    ) -> None:
        self.samples.append((obs, int(action)))
        self.ranks.append(int(rank))
        self.episode_ids.append(int(episode_id))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Tuple[Observation, int]:
        return self.samples[idx]

    def num_episodes(self) -> int:
        return len(set(self.episode_ids))

    def subset(self, indices: Sequence[int]) -> "BCDataset":
        return BCDataset(
            samples=[self.samples[i] for i in indices],
            ranks=[self.ranks[i] for i in indices],
            episode_ids=[self.episode_ids[i] for i in indices],
            meta=dict(self.meta),
        )

    def split_by_episode(
        self, val_frac: float = 0.2, seed: int = 0
    ) -> Tuple["BCDataset", "BCDataset"]:
        """按 episode 划分训练/验证（避免同局数据泄漏）。"""
        episodes = sorted(set(self.episode_ids))
        if len(episodes) <= 1:
            n_val = max(1, int(round(len(self) * val_frac)))
            idx = np.arange(len(self))
            rng = np.random.default_rng(seed)
            rng.shuffle(idx)
            val_idx = set(int(i) for i in idx[:n_val])
            train_idx = [i for i in range(len(self)) if i not in val_idx]
            return self.subset(train_idx), self.subset(sorted(val_idx))
        rng = np.random.default_rng(seed)
        perm = list(episodes)
        rng.shuffle(perm)
        n_val = max(1, int(round(len(perm) * val_frac)))
        n_val = min(n_val, len(perm) - 1)
        val_eps = set(perm[:n_val])
        train_idx = [i for i, e in enumerate(self.episode_ids) if e not in val_eps]
        val_idx = [i for i, e in enumerate(self.episode_ids) if e in val_eps]
        return self.subset(train_idx), self.subset(val_idx)

    # ── 统计 ──
    def random_accuracy(self) -> float:
        """随机猜的期望准确率（每步 1/有效候选数 的均值）。"""
        if not self:
            return 0.0
        total = 0.0
        for obs, _ in self.samples:
            n = max(min(len(obs.candidates or ()), CANDIDATE_MAX), 1)
            total += 1.0 / n
        return total / len(self)

    def action_kind_histogram(self) -> Dict[str, int]:
        hist: Dict[str, int] = {}
        for obs, action in self.samples:
            cands = obs.candidates or ()
            if 0 <= action < len(cands):
                kind = getattr(cands[action].kind, "value", cands[action].kind)
                hist[str(kind)] = hist.get(str(kind), 0) + 1
        return hist

    # ── 序列化（pickle：观测是纯数据，可跨进程）──
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": DATASET_VERSION,
            "samples": self.samples,
            "ranks": self.ranks,
            "episode_ids": self.episode_ids,
            "meta": self.meta,
        }

    def save(self, path: Union[str, Path]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self.to_dict(), f, protocol=pickle.HIGHEST_PROTOCOL)
        return path

    @classmethod
    def load(cls, path: Union[str, Path]) -> "BCDataset":
        with open(Path(path), "rb") as f:
            data = pickle.load(f)
        if isinstance(data, BCDataset):  # 兼容旧格式
            return data
        if not isinstance(data, dict) or "samples" not in data:
            raise ValueError(f"{path} 不是有效的 BC 数据集")
        ds = cls(
            samples=[(obs, int(a)) for obs, a in data["samples"]],
            ranks=[int(r) for r in data.get("ranks") or [-1] * len(data["samples"])],
            episode_ids=[int(e) for e in data.get("episode_ids") or [0] * len(data["samples"])],
            meta=dict(data.get("meta") or {}),
        )
        return ds

    # ── 张量化 ──
    def encoded(self, encoder: ObservationEncoder) -> Dict[str, torch.Tensor]:
        """把整个数据集编码成 CPU torch 张量（训练前一次完成）。"""
        if not self:
            raise ValueError("空数据集")
        batch = encoder.encode_batch([obs for obs, _ in self.samples])
        out: Dict[str, torch.Tensor] = {}
        from hsbg.policy.encoder import to_torch

        out.update(to_torch(batch))
        out["actions"] = torch.as_tensor(
            np.asarray([a for _, a in self.samples], dtype=np.int64)
        )
        out["ranks"] = torch.as_tensor(np.asarray(self.ranks, dtype=np.int64))
        out["num_candidates"] = out["cand_mask"].sum(dim=-1).long()
        # 防御：数据集里偶尔有越界/0 候选样本 → 修正为 0 号，保证 CE 不炸
        valid = out["actions"] < out["num_candidates"].clamp_min(1)
        out["actions"] = torch.where(valid, out["actions"], torch.zeros_like(out["actions"]))
        return out


# ══════════════════════════════════════════════════════════════════════
# 数据收集
# ══════════════════════════════════════════════════════════════════════


def make_policy_teacher(
    policy: EntityTransformerPolicy,
    encoder: ObservationEncoder,
    *,
    device: str = "cpu",
    greedy: bool = True,
) -> PolicyAgent:
    """把已训练策略包装成 BC 教师（用于自蒸馏 / 迭代 BC）。"""
    return PolicyAgent(policy, encoder, device=device, greedy=greedy, name="policy_teacher")


def _teacher_actions(teacher: Any, obs_list: Sequence[Observation]) -> List[int]:
    """把教师统一成 ``List[int]``。"""
    if hasattr(teacher, "act"):
        return [int(a) for a in teacher.act(obs_list)]
    if hasattr(teacher, "choose"):
        return [int(teacher.choose(obs)) for obs in obs_list]
    if callable(teacher):
        return [int(teacher(obs)) for obs in obs_list]
    raise TypeError(f"不支持的教师类型: {type(teacher)!r}")


def collect_bc_dataset(
    env: Any,
    teacher: Any = None,
    episodes: int = 8,
    *,
    max_steps: int = 20000,
    num_players: int = 8,
    seed: Optional[int] = None,
) -> BCDataset:
    """用教师策略在环境中采样 ``episodes`` 局，返回示范数据集。

    ``env`` 需符合 VecEnv 协议（``reset/step/close``，自动 reset）。
    """
    if episodes <= 0:
        raise ValueError("episodes 必须 >= 1")
    if teacher is None:
        teacher = HeuristicAgent(seed=seed or 0)
    reset_teacher = getattr(teacher, "reset", None)
    if callable(reset_teacher):
        reset_teacher()
    dataset = BCDataset(meta={"teacher": getattr(teacher, "name", type(teacher).__name__),
                              "episodes_requested": episodes})
    if seed is not None:
        setter = getattr(env, "seed", None)
        if callable(setter):
            try:
                setter(seed)
            except Exception:
                pass
    obs_list = env.reset()
    num_envs = int(getattr(env, "num_envs", len(obs_list)))
    # 每个 env 当前 episode 已收集的样本下标（终局时回填名次）
    pending: List[List[int]] = [[] for _ in range(num_envs)]
    next_episode_id = 0
    episode_ids = np.zeros(num_envs, dtype=np.int64)
    for i in range(num_envs):
        episode_ids[i] = next_episode_id
        next_episode_id += 1
    done_episodes = 0
    steps = 0
    while done_episodes < episodes and steps < max_steps:
        actions = _teacher_actions(teacher, obs_list)
        n = min(len(actions), num_envs)
        for i in range(n):
            obs = obs_list[i]
            n_cand = len(obs.candidates or ())
            action = int(actions[i])
            if n_cand == 0:
                continue
            action = min(max(action, 0), n_cand - 1)
            dataset.add(obs, action, rank=-1, episode_id=int(episode_ids[i]))
            pending[i].append(len(dataset) - 1)
        next_obs, _rewards, dones, infos = env.step(actions)
        steps += 1
        for i in range(num_envs):
            if not bool(dones[i]):
                continue
            info = infos[i] if i < len(infos) else {}
            rank = int(info.get("rank", 0) or 0)
            for idx in pending[i]:
                dataset.ranks[idx] = rank
            pending[i] = []
            episode_ids[i] = next_episode_id
            next_episode_id += 1
            done_episodes += 1
        obs_list = next_obs
    dataset.meta.update(
        {
            "episodes_collected": done_episodes,
            "samples": len(dataset),
            "steps": steps,
            "num_players": num_players,
            "action_kinds": dataset.action_kind_histogram(),
        }
    )
    return dataset


# ══════════════════════════════════════════════════════════════════════
# BC 训练
# ══════════════════════════════════════════════════════════════════════


@dataclass
class BCConfig:
    """BC 训练超参。"""

    lr: float = 3e-4
    epochs: int = 10
    batch_size: int = 64
    weight_decay: float = 0.0
    max_grad_norm: float = 0.5
    #: 终局名次交叉熵权重（分布价值头；0 关闭）
    rank_ce_coef: float = 0.1
    seed: int = 0
    device: str = "cpu"
    val_frac: float = 0.2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BCConfig":
        allowed = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**allowed)


class BCTrainer:
    """行为克隆训练器：候选 masked 交叉熵（+ 可选名次分布交叉熵）。"""

    def __init__(
        self,
        policy: EntityTransformerPolicy,
        encoder: ObservationEncoder,
        config: Optional[BCConfig] = None,
        *,
        device: Optional[str] = None,
    ) -> None:
        self.policy = policy
        self.encoder = encoder
        self.config = config or BCConfig()
        self.device = torch.device(device or self.config.device)
        self.policy.to(self.device)
        self.optimizer = torch.optim.Adam(
            self.policy.parameters(),
            lr=self.config.lr,
            weight_decay=self.config.weight_decay,
        )
        self._gen = torch.Generator(device="cpu")
        self._gen.manual_seed(self.config.seed)

    # ── 训练 ──
    def fit(
        self,
        dataset: BCDataset,
        *,
        val_dataset: Optional[BCDataset] = None,
        val_frac: Optional[float] = None,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """训练并返回 ``{"history": [...], "val_accuracy": ..., ...}``。"""
        cfg = self.config
        if len(dataset) == 0:
            raise ValueError("训练集为空")
        if val_dataset is None:
            val_frac = cfg.val_frac if val_frac is None else val_frac
            train_ds, val_ds = dataset.split_by_episode(val_frac=val_frac, seed=cfg.seed)
        else:
            train_ds, val_ds = dataset, val_dataset
        train_data = train_ds.encoded(self.encoder)
        val_data = val_ds.encoded(self.encoder) if len(val_ds) else None
        random_baseline = val_ds.random_accuracy() if len(val_ds) else train_ds.random_accuracy()

        n_train = train_data["actions"].shape[0]
        history: List[Dict[str, Any]] = []
        started = time.time()
        best_acc = -1.0
        for epoch in range(1, cfg.epochs + 1):
            self.policy.train()
            perm = torch.randperm(n_train, generator=self._gen)
            epoch_loss = 0.0
            epoch_ce = 0.0
            epoch_rank_ce = 0.0
            epoch_correct = 0.0
            n_batches = 0
            for start in range(0, n_train, cfg.batch_size):
                idx = perm[start : start + cfg.batch_size]
                obs_batch = {
                    k: train_data[k][idx] for k in ENCODED_KEYS
                }
                obs_batch = {k: v.to(self.device) for k, v in obs_batch.items()}
                actions = train_data["actions"][idx].to(self.device)
                ranks = train_data["ranks"][idx].to(self.device)
                out = self.policy.forward_full(obs_batch)
                logits = out["logits"]
                ce = F.cross_entropy(logits, actions)
                rank_ce = torch.zeros((), device=self.device)
                if cfg.rank_ce_coef > 0 and self.policy.config.value_mode == "distribution":
                    rank_mask = ranks >= 1
                    if bool(rank_mask.any()):
                        rank_logits = out["rank_logits"]
                        rank_ce = F.cross_entropy(
                            rank_logits[rank_mask],
                            (ranks[rank_mask] - 1).clamp(
                                0, self.policy.config.num_players - 1
                            ),
                        )
                loss = ce + cfg.rank_ce_coef * rank_ce
                self.optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), cfg.max_grad_norm)
                self.optimizer.step()
                with torch.no_grad():
                    pred = logits.argmax(dim=-1)
                    epoch_correct += float((pred == actions).float().mean().item())
                epoch_loss += float(loss.item())
                epoch_ce += float(ce.item())
                epoch_rank_ce += float(rank_ce.item())
                n_batches += 1
            row: Dict[str, Any] = {
                "epoch": epoch,
                "train_loss": epoch_loss / max(n_batches, 1),
                "train_ce": epoch_ce / max(n_batches, 1),
                "train_rank_ce": epoch_rank_ce / max(n_batches, 1),
                "train_accuracy": epoch_correct / max(n_batches, 1),
            }
            if val_data is not None:
                val_metrics = self.evaluate_encoded(val_data)
                row.update(
                    {
                        "val_loss": val_metrics["loss"],
                        "val_accuracy": val_metrics["accuracy"],
                        "val_random_baseline": random_baseline,
                    }
                )
                best_acc = max(best_acc, val_metrics["accuracy"])
            history.append(row)
            if verbose:
                extra = (
                    f" val_loss={row.get('val_loss', float('nan')):.4f}"
                    f" val_acc={row.get('val_accuracy', float('nan')):.3f}"
                    f" (random={random_baseline:.3f})"
                    if "val_accuracy" in row else ""
                )
                print(
                    f"[bc] epoch={epoch:3d} loss={row['train_loss']:.4f} "
                    f"ce={row['train_ce']:.4f} acc={row['train_accuracy']:.3f}{extra}"
                )
        result = {
            "history": history,
            "random_baseline": random_baseline,
            "val_accuracy": best_acc,
            "train_samples": n_train,
            "val_samples": len(val_ds),
            "epochs": cfg.epochs,
            "wall_time_s": time.time() - started,
        }
        if verbose:
            print(format_metrics_table(
                [{"epoch": r["epoch"], "loss": f"{r['train_loss']:.4f}",
                  "acc": f"{r['train_accuracy']:.3f}",
                  **({"val_acc": f"{r['val_accuracy']:.3f}"} if "val_accuracy" in r else {})}
                 for r in history]))
        return result

    @torch.no_grad()
    def evaluate_encoded(
        self, data: Dict[str, torch.Tensor], chunk_size: int = 512
    ) -> Dict[str, float]:
        """在已编码数据集上算 loss/accuracy（验证集用；分块避免一次性前向过大）。"""
        self.policy.eval()
        actions_all = data["actions"]
        n = int(actions_all.shape[0])
        if n == 0:
            return {"loss": 0.0, "accuracy": 0.0}
        total_loss = 0.0
        total_correct = 0.0
        for start in range(0, n, chunk_size):
            end = min(start + chunk_size, n)
            obs_batch = {
                k: data[k][start:end].to(self.device) for k in ENCODED_KEYS
            }
            actions = actions_all[start:end].to(self.device)
            logits, _ = self.policy(obs_batch)
            loss = F.cross_entropy(logits, actions)
            pred = logits.argmax(dim=-1)
            total_loss += float(loss.item()) * (end - start)
            total_correct += float((pred == actions).float().sum().item())
        return {"loss": total_loss / n, "accuracy": total_correct / n}

    @torch.no_grad()
    def evaluate_dataset(self, dataset: BCDataset) -> Dict[str, float]:
        return self.evaluate_encoded(dataset.encoded(self.encoder))

    # ── checkpoint ──
    def save_checkpoint(
        self,
        path: Union[str, Path],
        *,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Path:
        meta = dict(meta or {})
        meta.setdefault("trainer", "bc")
        meta.setdefault("bc_config", self.config.to_dict())
        meta.setdefault("params", self.policy.count_parameters())
        return self.policy.save(path, meta=meta)

    @classmethod
    def load(
        cls,
        checkpoint_path: Union[str, Path],
        *,
        config: Optional[BCConfig] = None,
        device: Optional[str] = None,
    ) -> "BCTrainer":
        policy = EntityTransformerPolicy.load(checkpoint_path, map_location="cpu")
        encoder = policy.make_encoder()
        if config is None:
            config = BCConfig.from_dict((policy.meta or {}).get("bc_config") or {})
        return cls(policy, encoder, config, device=device)


# ══════════════════════════════════════════════════════════════════════
# 一站式流程
# ══════════════════════════════════════════════════════════════════════


def train_bc(
    env: Any,
    policy: EntityTransformerPolicy,
    encoder: ObservationEncoder,
    *,
    teacher: Any = None,
    episodes: int = 8,
    config: Optional[BCConfig] = None,
    out_dir: Optional[Union[str, Path]] = None,
    verbose: bool = True,
    save_dataset: bool = True,
) -> Dict[str, Any]:
    """收集 → 训练 → 保存 checkpoint/数据集/日志的一站式 BC。"""
    config = config or BCConfig()
    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)
    started = time.time()
    dataset = collect_bc_dataset(env, teacher, episodes)
    if verbose:
        print(f"[bc] dataset: {len(dataset)} samples / {dataset.num_episodes()} episodes, "
              f"random_acc={dataset.random_accuracy():.3f}, "
              f"kinds={dataset.action_kind_histogram()}")
    trainer = BCTrainer(policy, encoder, config)
    result = trainer.fit(dataset, verbose=verbose)
    checkpoint: Optional[Path] = None
    dataset_path: Optional[Path] = None
    if out_path is not None:
        checkpoint = trainer.save_checkpoint(
            out_path / "policy_bc.pt",
            meta={
                "dataset_size": len(dataset),
                "episodes": dataset.num_episodes(),
                "random_baseline": result["random_baseline"],
                "val_accuracy": result["val_accuracy"],
            },
        )
        if save_dataset:
            dataset_path = dataset.save(out_path / "bc_dataset.pkl")
        log = CSVLogger(out_path / "bc_train_log.csv", fieldnames=list(result["history"][0].keys()))
        for row in result["history"]:
            log.log(row)
        log.close()
        write_json(
            out_path / "summary.json",
            {
                "trainer": "bc",
                "episodes": episodes,
                "dataset_samples": len(dataset),
                "dataset_episodes": dataset.num_episodes(),
                "random_baseline": result["random_baseline"],
                "val_accuracy": result["val_accuracy"],
                "history": result["history"],
                "policy_config": policy.config.to_dict(),
                "bc_config": config.to_dict(),
                "params": policy.count_parameters(),
                "checkpoint": str(checkpoint) if checkpoint else None,
                "dataset": str(dataset_path) if dataset_path else None,
                "wall_time_s": time.time() - started,
            },
        )
    result.update(
        {
            "dataset": dataset,
            "checkpoint": str(checkpoint) if checkpoint else None,
            "dataset_path": str(dataset_path) if dataset_path else None,
            "trainer": trainer,
        }
    )
    return result


__all__ = [
    "BCDataset",
    "BCConfig",
    "BCTrainer",
    "collect_bc_dataset",
    "make_policy_teacher",
    "train_bc",
    "DATASET_VERSION",
]
