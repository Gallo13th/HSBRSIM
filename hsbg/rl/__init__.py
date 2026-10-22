"""``hsbg.rl`` — 强化学习接口层（稳定协议 / Gymnasium 包装 / 并发采集 / 评测）。

层次::

    hsbg.env（单环境五元组）
        │
        ▼
    hsbg.rl.api        # Policy / EnvLike 协议、Transition / EpisodeRecord、run_episode
        ├── hsbg.rl.policies   # random / heuristic / callable / checkpoint 策略
        ├── hsbg.rl.envs       # real / mock 环境工厂
        ├── hsbg.rl.gym_wrapper# Gymnasium 兼容（可选依赖 gymnasium）
        ├── hsbg.rl.collector  # 多进程采集 → JSONL（断点续采）
        └── hsbg.rl.evaluate   # 多进程评测（复用 hsbg.eval 指标）
        │
        ▼
    hsbg.train（后续训练：PPO/BC 从 collector 产物读取）

``gym_wrapper`` 依赖可选的 ``gymnasium``，因此惰性导入；其余模块只依赖
``hsbg.env.spec`` / numpy / 标准库。
"""

from __future__ import annotations

from typing import Any

from hsbg.rl.api import (
    API_VERSION,
    OBS_VERSION,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    EpisodeRecord,
    EnvLike,
    Policy,
    Transition,
    candidate_index,
    error_record,
    fallback_index,
    header_record,
    obs_digest,
    obs_summary,
    resolve_action,
    run_episode,
    validate_record,
)
from hsbg.rl.envs import (
    BACKENDS,
    MockBattlegroundsEnv,
    env_backend_name,
    make_env,
    real_env_available,
)
from hsbg.rl.policies import (
    BUILTIN_NAMES,
    BasePolicy,
    CallableAdapter,
    CheckpointPolicy,
    EndTurnPolicy,
    FirstLegalPolicy,
    HeuristicPolicy,
    PolicyAdapter,
    RandomPolicy,
    TeacherPolicy,
    as_policy,
    describe_policy,
    ensure_picklable,
    heuristic_score,
    is_picklable,
    make_policy,
    policy_requires_engine,
)

__all__ = [
    # api
    "SCHEMA_VERSION",
    "API_VERSION",
    "OBS_VERSION",
    "REQUIRED_FIELDS",
    "Policy",
    "EnvLike",
    "Transition",
    "EpisodeRecord",
    "candidate_index",
    "fallback_index",
    "resolve_action",
    "obs_summary",
    "obs_digest",
    "header_record",
    "error_record",
    "run_episode",
    "validate_record",
    # envs
    "BACKENDS",
    "MockBattlegroundsEnv",
    "make_env",
    "env_backend_name",
    "real_env_available",
    # policies
    "BUILTIN_NAMES",
    "BasePolicy",
    "RandomPolicy",
    "FirstLegalPolicy",
    "EndTurnPolicy",
    "HeuristicPolicy",
    "TeacherPolicy",
    "CallableAdapter",
    "PolicyAdapter",
    "CheckpointPolicy",
    "as_policy",
    "make_policy",
    "describe_policy",
    "policy_requires_engine",
    "heuristic_score",
    "is_picklable",
    "ensure_picklable",
    # gym / collector / evaluate（惰性）
    "GymBattlegroundsEnv",
    "make_gym_env",
    "gymnasium_available",
    "collect_trajectories",
    "collect_rollouts",
    "CollectStats",
    "evaluate",
    "EvalSummary",
    "evaluate_many",
]

#: 惰性导出：gym（可选依赖）/ collector / evaluate（方便按需导入）
_LAZY_EXPORTS = {
    "GymBattlegroundsEnv": "hsbg.rl.gym_wrapper",
    "make_gym_env": "hsbg.rl.gym_wrapper",
    "gymnasium_available": "hsbg.rl.gym_wrapper",
    "RecordEpisode": "hsbg.rl.gym_wrapper",
    "TimeLimit": "hsbg.rl.gym_wrapper",
    "AutoResetWrapper": "hsbg.rl.gym_wrapper",
    "collect_trajectories": "hsbg.rl.collector",
    "collect_rollouts": "hsbg.rl.collector",
    "CollectStats": "hsbg.rl.collector",
    "evaluate": "hsbg.rl.evaluate",
    "EvalSummary": "hsbg.rl.evaluate",
    "evaluate_many": "hsbg.rl.evaluate",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:  # pragma: no cover
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
