"""脚本对手 / 教师的统一接口。

对齐 ``docs/ENV_SPEC.md`` §6：

.. code-block:: python

    class OpponentPolicy(Protocol):
        name: str
        def choose(self, game, hero, env_ctx=None) -> Optional[ActionDescriptor]:
            \"\"\"返回下一个要执行的动作（引擎层描述符）；None = 结束招募阶段。\"\"\"

对手必须是**同构**的：只通过 ``hsbg.env.driver`` 的公开 API 行动（同样的
金币/手牌/等级/目标合法性检查），禁止直接篡改棋盘或读取智能体隐藏信息。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class EnvContext:
    """传给策略的轻量上下文（可选）。

    ``zones``：驱动层的槽位视图（与观测同源）；对手策略若自带枚举会自建。
    ``env``：仅 demo/teacher 使用；脚本对手不得依赖 env 内部状态。
    ``agent_hero``：智能体英雄（策略**不得**读取其隐藏信息——目前仅用于
    判断"我是谁"以复用同一实例）。
    """

    game: Any = None
    zones: Any = None
    env: Any = None
    agent_hero: Any = None
    turn: int = 0


@runtime_checkable
class OpponentPolicy(Protocol):
    """对手策略协议（结构类型，无需继承）。"""

    name: str

    def choose(self, game: Any, hero: Any,
               ctx: Optional[EnvContext] = None) -> Optional[Any]:
        """返回下一个动作（``ActionDescriptor``），``None`` = 结束回合。"""
        ...  # pragma: no cover


def choose_option_index(policy: Any, obs: Any, game: Any = None) -> int:
    """统一「选择步」决策入口。

    - 策略若实现 ``choose_option_index(obs)``（启发式/教师）→ 用之；
    - 否则（如 :class:`RandomPolicy`）→ 用 ``game.rng`` 在合法选项中等概率
      随机（保持引擎确定性：审计/演示同 seed 可复现）。

    返回 `obs.pending_choice.options` 的下标（无选择步 → 0）。
    """
    fn = getattr(policy, "choose_option_index", None)
    if fn is not None:
        try:
            return int(fn(obs))
        except Exception:                                 # noqa: BLE001
            return 0
    pending = getattr(obs, "pending_choice", None)
    options = getattr(pending, "options", None) or ()
    if not options:
        return 0
    if game is not None and hasattr(game, "rng"):
        return int(game.rng.randint(0, len(options) - 1))
    return 0
