"""RL 环境层（契约见 ``hsbg/env/spec.py`` 与 ``docs/ENV_SPEC.md``）。

公开入口::

    from hsbg.env import BattlegroundsEnv, EnvConfig, RewardConfig
    from hsbg.env.vec_env import VecEnv, SyncVecEnv

``game_env`` / ``vec_env`` 依赖 ``hsbg.agents``，而代理策略需要
``hsbg.env.driver`` —— 为避免包初始化期的循环导入，重对象（环境类、向量化）
通过 PEP 562 模块 ``__getattr__`` **惰性导入**；轻量契约（spec/driver/
observation）仍即时导入。
"""

from __future__ import annotations

# 契约（无引擎依赖）必须最先导入
from hsbg.env.spec import (  # noqa: F401
    ACTION_KIND_INDEX,
    BOARD_MAX,
    CANDIDATE_MAX,
    DEFAULT_ENV_CONFIG,
    ENTITY_ZONES,
    HAND_MAX,
    KEYWORD_INDEX,
    KEYWORDS,
    NUM_ACTION_KINDS,
    NUM_KEYWORDS,
    NUM_RACES,
    OBS_DIMS,
    OPPONENT_BOARD_MAX,
    PLAYER_MAX,
    RACE_INDEX,
    RACES,
    TAVERN_MAX,
    TRINKET_MAX,
    ActionKind,
    CandidateAction,
    EntityToken,
    EnvConfig,
    HeroToken,
    LobbyPlayer,
    Observation,
    ObsDims,
    PendingChoice,
    RewardConfig,
    StepResult,
)
from hsbg.env.driver import (  # noqa: F401
    ActionDescriptor,
    ApplyResult,
    ChoiceQueue,
    StepActions,
    Zones,
    apply_action,
    collect_zones,
    default_pick_index,
    enumerate_actions,
    enumerate_choice,
    enumerate_step,
    get_card_db,
    resolve_pending_choices,
)
from hsbg.env.observation import (  # noqa: F401
    build_extra_state,
    build_observation,
    entity_token,
)

__all__ = [
    "BattlegroundsEnv",
    "SyncVecEnv",
    "VecEnv",
    "EnvConfig",
    "RewardConfig",
    "Observation",
    "EntityToken",
    "HeroToken",
    "LobbyPlayer",
    "PendingChoice",
    "CandidateAction",
    "ActionKind",
    "StepResult",
    "OBS_DIMS",
    "CANDIDATE_MAX",
    "ActionDescriptor",
    "ApplyResult",
    "StepActions",
    "Zones",
    "ChoiceQueue",
    "enumerate_actions",
    "enumerate_choice",
    "enumerate_step",
    "apply_action",
    "collect_zones",
    "resolve_pending_choices",
    "default_pick_index",
    "get_card_db",
    "build_observation",
    "build_extra_state",
    "entity_token",
]

#: 惰性导入表：名字 → 所属模块
_LAZY_EXPORTS = {
    "BattlegroundsEnv": "hsbg.env.game_env",
    "SyncVecEnv": "hsbg.env.vec_env",
    "VecEnv": "hsbg.env.vec_env",
}


def __getattr__(name: str):
    """PEP 562：按需导入环境/向量化类（避免与 hsbg.agents 循环导入）。"""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():                                            # pragma: no cover
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
