"""``hsbg.train`` — BC / PPO 训练管线与向量环境适配。

* :mod:`hsbg.train.vec_env`  —— VecEnv 协议 + ``SyncVecEnv`` + ``MockVecEnv``
* :mod:`hsbg.train.buffer`   —— PPO rollout buffer + GAE(λ)
* :mod:`hsbg.train.ppo`      —— ``PPOTrainer`` / ``train_ppo``
* :mod:`hsbg.train.bc`       —— BC 数据集 / ``BCTrainer`` / ``train_bc``
* :mod:`hsbg.train.evaluate` —— 策略与基线评测
* :mod:`hsbg.train.logger`   —— CSV / JSON 日志

torch 相关模块（buffer/ppo/bc）使用惰性导出，方便只用到 vec_env 的场景。
"""

from __future__ import annotations

from typing import Any

from hsbg.train.evaluate import (
    Agent,
    EvalResult,
    HeuristicAgent,
    PolicyAgent,
    RandomAgent,
    evaluate_agent,
    evaluate_policy,
    make_agent,
)
from hsbg.train.logger import CSVLogger, format_metrics_table, read_json, write_json
from hsbg.train.vec_env import (
    MockVecEnv,
    SyncVecEnv,
    VecEnv,
    is_vec_env,
    make_vec_env,
    normalize_step_result,
    placement_to_reward,
    try_make_real_vec_env,
)

#: 惰性导出（依赖 torch）
_LAZY_EXPORTS = {
    "RolloutBuffer",
    "PPOConfig",
    "PPOTrainer",
    "train_ppo",
    "BCDataset",
    "BCConfig",
    "BCTrainer",
    "collect_bc_dataset",
    "make_policy_teacher",
    "train_bc",
}

__all__ = [
    "VecEnv",
    "is_vec_env",
    "SyncVecEnv",
    "MockVecEnv",
    "make_vec_env",
    "try_make_real_vec_env",
    "normalize_step_result",
    "placement_to_reward",
    "Agent",
    "PolicyAgent",
    "RandomAgent",
    "HeuristicAgent",
    "make_agent",
    "EvalResult",
    "evaluate_agent",
    "evaluate_policy",
    "CSVLogger",
    "write_json",
    "read_json",
    "format_metrics_table",
    "RolloutBuffer",
    "PPOConfig",
    "PPOTrainer",
    "train_ppo",
    "BCDataset",
    "BCConfig",
    "BCTrainer",
    "collect_bc_dataset",
    "make_policy_teacher",
    "train_bc",
]


def __getattr__(name: str) -> Any:
    if name in ("RolloutBuffer",):
        from hsbg.train import buffer

        return getattr(buffer, name)
    if name in ("PPOConfig", "PPOTrainer", "train_ppo"):
        from hsbg.train import ppo

        return getattr(ppo, name)
    if name in (
        "BCDataset",
        "BCConfig",
        "BCTrainer",
        "collect_bc_dataset",
        "make_policy_teacher",
        "train_bc",
    ):
        from hsbg.train import bc

        return getattr(bc, name)
    raise AttributeError(f"module 'hsbg.train' has no attribute {name!r}")
