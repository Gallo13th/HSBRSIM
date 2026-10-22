"""计划搜索用的 RNG 状态接口（不改引擎；封装 ``GameRNG`` 内部状态）。

引擎 ``GameRNG`` 由 ``random.Random`` + ``decisions`` 日志组成；AlphaZero 的
chance node（洗牌/发现/随机目标）需要：

- ``get_state(rng)`` / ``set_state(rng, state)``：快照/恢复随机流；
- ``fork(rng, seed=None)``：派生**独立**随机流（同状态 → 同未来；给 seed → 新流）。

成本实测（8 人局第 5 回合、404 条 decisions）：get_state ~0.009ms、
set_state ~0.001ms、fork ~0.012ms，远低于 0.05ms 目标（见
``scripts/bench_planning.py``）。

**注意**：直接读 ``rng._rng`` 是引擎私有属性；若未来 `hsrl2.rng` 增加公开
get_state/set_state，本模块改为委托即可（不影响调用方）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from hsrl2.rng import GameRNG

__all__ = ["get_state", "set_state", "fork", "state_equal"]


def get_state(rng: GameRNG, *, copy_decisions: bool = True) -> Dict[str, Any]:
    """返回 RNG 完整状态（可 pickle 的纯数据）。

    ``copy_decisions=False`` 可跳过 decisions 日志（不改随机流；搜索分支
    无需日志时更快）。
    """
    return {
        "seed": int(getattr(rng, "seed_value", 0)),
        "random_state": rng._rng.getstate(),
        "decisions": tuple(rng.decisions) if copy_decisions else (),
    }


def set_state(rng: GameRNG, state: Dict[str, Any]) -> None:
    """把 :func:`get_state` 的结果写回 RNG（原地）。"""
    rng.seed_value = int(state.get("seed", 0))
    rng._rng.setstate(state["random_state"])
    rng.decisions = list(state.get("decisions", ()))


def fork(rng: GameRNG, *, seed: Optional[int] = None,
         copy_decisions: bool = True) -> GameRNG:
    """派生独立 RNG。

    - ``seed=None``：**复制当前随机流状态**（`fork() 后两个 RNG 下一次
      random() 相同`，然后各自独立推进）；
    - ``seed=int``：以该 seed 新建随机流（decisions 清空），用于 chance node
      独立分支。

    返回新的 ``GameRNG``（不与原对象共享 ``random.Random``）。
    """
    cloned = GameRNG(int(seed) if seed is not None else int(
        getattr(rng, "seed_value", 0)))
    if seed is None:
        cloned._rng.setstate(rng._rng.getstate())
        if copy_decisions:
            cloned.decisions = list(rng.decisions)
    return cloned


def state_equal(a: GameRNG, b: GameRNG) -> bool:
    """两个 RNG 的随机流状态是否一致（用于确定性断言）。"""
    return (int(getattr(a, "seed_value", 0)) == int(getattr(b, "seed_value", 0))
            and a._rng.getstate() == b._rng.getstate()
            and list(a.decisions) == list(b.decisions))
