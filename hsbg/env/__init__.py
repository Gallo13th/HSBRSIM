"""AutoTavern 标准环境 profile。

只保留两套冻结契约：

* ``action_space_std``：245 个离散动作（前 245 与 AutoTavern 逐位一致，扩展段 29 个）；
* ``obs_std``：3227 floats + 124 cards 的玩家视角观测与只读块解码。

模拟器本身在 ``hsbg_engine``（``rust/``）；搜索/训练直接通过
``hsbg.az.env_api`` 调用引擎，不再经过 legacy 候选动作/实体 token 层。
"""

from __future__ import annotations

from hsbg.env import action_space_std, obs_std

__all__ = ["action_space_std", "obs_std"]
