"""``hsbg.backends`` — AutoTavern Rust 主后端（AutoTavern fork 的 ``hsbg_engine``）。

项目已停用 ``hsrl2`` 运行时；本包提供唯一的 ``EnvLike`` 适配器
:class:`TavernGymEnv`（别名 :data:`RustEngineEnv` / :data:`AutoTavernEnv`），
把 ``hsbg_engine.Game``（245 动作/固定官方观测）包装成 ``hsbg.env.spec`` 的
实体 token 观测与候选动作接口。

导出：``TavernGymEnv`` / ``RustEngineEnv`` / ``AutoTavernEnv`` /
``make_taverngym_env`` / ``taverngym_available`` / ``BACKEND_NAME``。
"""

from __future__ import annotations

from .taverngym_env import (
    BACKEND_NAME,
    TavernGymEnv,
    make_taverngym_env,
    taverngym_available,
)

#: 兼容别名：主引擎是 AutoTavern fork 的 Rust hsbg_engine。
RustEngineEnv = TavernGymEnv
AutoTavernEnv = TavernGymEnv

__all__ = [
    "BACKEND_NAME",
    "AutoTavernEnv",
    "RustEngineEnv",
    "TavernGymEnv",
    "make_taverngym_env",
    "taverngym_available",
]
