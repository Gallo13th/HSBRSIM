"""``hsbg.backends`` —— 可选/参照模拟后端（目前只有 TavernGym）。

默认后端仍是 ``hsbg.env.BattlegroundsEnv``（vendored ``hsrl2`` 引擎，数据基线
37.0.0.255130，机制精度权威）。本包提供**第二套引擎**的 ``EnvLike`` 适配器，
用于交叉验证、吞吐基准与"独立实现参照"，不参与默认训练/评测路径。

导出
----
* :class:`TavernGymEnv` —— AutoTavern 项目 Rust 引擎（TavernGym 1.0.0，
  游戏数据 36.6.3.253932）的单座 ``EnvLike`` 适配器；
* :func:`make_taverngym_env` —— 便捷工厂；
* :func:`taverngym_available` —— 依赖是否可用（pip 包是否已安装）；
* :data:`BACKEND_NAME` —— ``"taverngym"``。

用法::

    from hsbg.backends import TavernGymEnv
    from hsbg.rl.api import run_episode
    from hsbg.rl.policies import RandomPolicy

    env = TavernGymEnv(seed=0)
    obs = env.reset(seed=0)
    rec = run_episode(env, RandomPolicy(seed=0), seed=0, max_steps=400)

设计约束（详见 ``docs/TAVERNGYM_BACKEND.md``）：

1. **已注册进 ``hsbg.rl`` 工厂、默认不启用**：``hsbg.rl.envs.BACKENDS`` 含
   ``"taverngym"``（``make_env(backend="taverngym")``，惰性导入本包），
   ``collector``/``evaluate`` 的 ``--backend`` 也支持；但默认后端仍是
   ``hsrl2``（``make_env()`` ≡ ``make_env(backend="hsrl2")``），既有
   CLI/测试行为不变。
2. 观测/动作/奖励全部对齐 ``hsbg.env.spec``；与 ``hsrl2`` 后端的差异（卡池、
   动作空间 245 维、观测槽位上限等）在模块 docstring 与文档中逐条列出。
3. 不引入新的第三方依赖：只用 ``taverngym``（可选安装）与 ``numpy``。
"""

from __future__ import annotations

from .taverngym_env import (
    BACKEND_NAME,
    TavernGymEnv,
    make_taverngym_env,
    taverngym_available,
)

__all__ = [
    "BACKEND_NAME",
    "TavernGymEnv",
    "make_taverngym_env",
    "taverngym_available",
]
