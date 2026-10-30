"""换位去抖守卫（move de-bounce guard）。

**动机**：实测策略每回合换位 ~29 次，其中 74–93% 是同一动作连按；25/95 个回合
净盘面完全不变（纯空转，白耗 40 动作/回合的上限）。Move 段（196..244）有 49 个
动作，网络只要反复采同一个 ``Move(from=a,to=b)`` 就能无限刷决策，而盘面不变。

**规则**（只约束 learner 的行为分布，不改引擎、不改观测）：

1. 逆换位屏蔽：若本回合 learner **上一步**是 ``Move(from=a,to=b)``，屏蔽
   ``Move(from=b,to=a)``（撤销动作）；
2. 同动作上限：同一 ``(from,to)`` 在本回合出现 ``>= repeat_limit`` 次后屏蔽
   （默认 2 = 最多连续/累计两次）；
3. 每回合换位上限：本回合已选换位 ``>= cap`` 次后屏蔽**全部** 49 个换位动作
   （默认 3）。

实现方式：在采样**之前**把对应动作位的 mask 清 0，再让原策略在剩余合法动作上
重新归一/采样。若清 0 后**只剩 EndTurn**（或没有任何合法动作），回退 ``EndTurn``
（若合法；该决策记 ``forced``、不进 PPO 策略损失，语义 = 守卫强制结束本回合），
否则完全回退原 mask。统计写进采集 meta：

- ``move_guard_blocked_inverse`` / ``_repeat`` / ``_cap``：被清掉的合法换位**动作位**
  数（按决策累计；同一动作位只记一条规则，优先级 cap > inverse > repeat）；
- ``move_guard_forced``：清空后回退 EndTurn 的次数；
- ``move_guard_decisions`` / ``move_guard_moves``：守卫下的 learner 决策数 / 实际
  选中的换位次数（用于核对去抖效果）。

**默认关闭**（``CollectConfig.move_guard=False``）：不构造本对象、不碰 mask、
不新增 record/meta 字段 —— 与旧路径逐位等价。规则见 ``docs/MOVE_GUARD.md``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np

from hsbg.env.action_space_std import A_MOVE, N_BOARD

#: Move 段（闭开区间）：196..244。
MOVE_LO = int(A_MOVE)
MOVE_HI = MOVE_LO + int(N_BOARD) * int(N_BOARD)
N_MOVES = MOVE_HI - MOVE_LO

#: 默认参数（与 CLI ``--move-cap`` / ``--move-repeat-limit`` 一致）。
DEFAULT_MOVE_CAP = 3
DEFAULT_MOVE_REPEAT_LIMIT = 2


def is_move(action: Any) -> bool:
    """动作下标是否落在 Move 段 196..244。"""
    try:
        a = int(action)
    except (TypeError, ValueError):
        return False
    return MOVE_LO <= a < MOVE_HI


def decode_move(action: Any) -> Tuple[int, int]:
    """Move 动作下标 -> ``(from, to)``；越界抛 ValueError。"""
    a = int(action)
    if not is_move(a):
        raise ValueError(f"不是 Move 动作: {a}（合法区间 {MOVE_LO}..{MOVE_HI - 1}）")
    return divmod(a - MOVE_LO, int(N_BOARD))


def encode_move(src: Any, dst: Any) -> int:
    """``(from, to)`` -> Move 动作下标；越界抛 ValueError。"""
    s, d = int(src), int(dst)
    if not (0 <= s < int(N_BOARD) and 0 <= d < int(N_BOARD)):
        raise ValueError(f"Move 槽位越界: from={s}, to={d}（0..{int(N_BOARD) - 1}）")
    return MOVE_LO + s * int(N_BOARD) + d


@dataclass
class MoveGuardStats:
    """单次采集（或单局）的去抖计数。"""

    decisions: int = 0          #: 守卫下的 learner 决策数
    moves: int = 0              #: 守卫下实际选择的换位次数
    blocked_inverse: int = 0    #: 被逆换位规则清掉的合法动作位数
    blocked_repeat: int = 0     #: 被同动作上限规则清掉的合法动作位数
    blocked_cap: int = 0        #: 被每回合换位上限规则清掉的合法动作位数
    forced: int = 0             #: 清空后回退 EndTurn 的次数

    def add(self, other: "MoveGuardStats") -> None:
        self.decisions += int(other.decisions)
        self.moves += int(other.moves)
        self.blocked_inverse += int(other.blocked_inverse)
        self.blocked_repeat += int(other.blocked_repeat)
        self.blocked_cap += int(other.blocked_cap)
        self.forced += int(other.forced)


@dataclass
class _SeatTurn:
    """一个 ``(game_id, seat)`` 在当前回合的 learner 动作历史。"""

    turn: int
    last_action: int = -1
    moves: List[int] = field(default_factory=list)
    counts: Dict[int, int] = field(default_factory=dict)


class MoveGuard:
    """换位去抖守卫：按 ``(game_id, seat, turn)`` 维护 learner 动作历史。

    状态隔离：key 含 ``game_id`` 与 ``seat``，所以 lock-step 多局共用一个 policy
    实例（每轮一个 batch 里混着不同 game 的待决策）也互不影响；``turn`` 变化即
    自动重置该座位的回合历史。
    """

    def __init__(self, *, cap: int = DEFAULT_MOVE_CAP,
                 repeat_limit: int = DEFAULT_MOVE_REPEAT_LIMIT) -> None:
        self.cap = int(cap)
        self.repeat_limit = int(repeat_limit)
        if self.cap < 0:
            raise ValueError(f"move_cap 必须 >= 0，得到 {self.cap}")
        if self.repeat_limit < 1:
            raise ValueError(f"move_repeat_limit 必须 >= 1，得到 {self.repeat_limit}")
        self._turns: Dict[Tuple[int, int], _SeatTurn] = {}
        self.stats = MoveGuardStats()

    # -- 状态 ---------------------------------------------------------------
    def reset(self) -> None:
        """清空回合历史与统计（换一次采集 / 一次评测时调用）。"""
        self._turns.clear()
        self.stats = MoveGuardStats()

    def clear_state(self) -> None:
        """只清回合历史，保留累计统计（每局开始复用 policy 时调用）。"""
        self._turns.clear()

    def _state(self, game_id: Any, seat: Any, turn: Any) -> _SeatTurn:
        key = (int(game_id), int(seat))
        st = self._turns.get(key)
        t = int(turn)
        if st is None or st.turn != t:
            st = _SeatTurn(turn=t)
            self._turns[key] = st
        return st

    # -- 采样前：改写 mask ---------------------------------------------------
    def guarded_mask(self, mask: Any, *, game_id: Any, seat: Any, turn: Any
                     ) -> Tuple[np.ndarray, bool]:
        """返回 ``(guarded_mask, forced)``。

        ``guarded_mask`` 是原 mask 的副本（只把被禁的 Move 位清 0）；``forced=True``
        表示屏蔽后只剩 ``EndTurn``（或已无合法动作、回退 EndTurn），即守卫强制结束了
        本回合。两者都不会修改输入数组。
        """
        m = np.asarray(mask, dtype=bool)
        out = m.copy()
        self.stats.decisions += 1
        st = self._state(game_id, seat, turn)

        legal_off = np.flatnonzero(m[MOVE_LO:MOVE_HI])
        if legal_off.size == 0:
            return out, False

        cap_hit = len(st.moves) >= self.cap
        inverse = -1
        if is_move(st.last_action):
            src, dst = decode_move(st.last_action)
            if src != dst:                      # 恒等换位本就不合法，防御性跳过
                inverse = encode_move(dst, src)

        n_inv = n_rep = n_cap = 0
        for off in legal_off:
            a = MOVE_LO + int(off)
            if cap_hit:
                out[a] = False
                n_cap += 1
            elif a == inverse:
                out[a] = False
                n_inv += 1
            elif st.counts.get(a, 0) >= self.repeat_limit:
                out[a] = False
                n_rep += 1

        if not out.any():
            # 全部合法动作都是被禁换位：优先回退 EndTurn（环境确定性约束），
            # 否则完全回退原 mask（本决策不受守卫影响、也不计数）。
            if bool(m[0]):
                only = np.zeros_like(out)
                only[0] = True
                self.stats.blocked_inverse += n_inv
                self.stats.blocked_repeat += n_rep
                self.stats.blocked_cap += n_cap
                self.stats.forced += 1
                return only, True
            return m.copy(), False

        self.stats.blocked_inverse += n_inv
        self.stats.blocked_repeat += n_rep
        self.stats.blocked_cap += n_cap
        # 「剩余只剩 EndTurn」= 守卫实际上强制结束了本回合：同样按确定性约束记
        # forced（掩码退化为单点，采样分布恒为 EndTurn），并写 move_guard_forced。
        rest = np.flatnonzero(out)
        if rest.size == 1 and int(rest[0]) == 0:
            self.stats.forced += 1
            return out, True
        return out, False

    # -- 采样后：记录本回合动作 ---------------------------------------------
    def note_action(self, action: Any, *, game_id: Any, seat: Any, turn: Any) -> None:
        """记录 learner 本回合实际动作（非 Move 只更新「上一步」）。"""
        a = int(action)
        st = self._state(game_id, seat, turn)
        st.last_action = a
        if not is_move(a):
            return
        st.moves.append(a)
        st.counts[a] = st.counts.get(a, 0) + 1
        self.stats.moves += 1

    # -- meta ---------------------------------------------------------------
    def to_meta(self) -> Dict[str, Any]:
        """统计 -> 采集 meta 字段（键名与 ``docs/MOVE_GUARD.md`` 一致）。"""
        return {
            "move_guard": True,
            "move_cap": int(self.cap),
            "move_repeat_limit": int(self.repeat_limit),
            "move_guard_decisions": int(self.stats.decisions),
            "move_guard_moves": int(self.stats.moves),
            "move_guard_blocked_inverse": int(self.stats.blocked_inverse),
            "move_guard_blocked_repeat": int(self.stats.blocked_repeat),
            "move_guard_blocked_cap": int(self.stats.blocked_cap),
            "move_guard_forced": int(self.stats.forced),
        }


def aggregate_move_guard(metas: Iterable[Any]) -> Dict[str, Any]:
    """把多个 worker/game 的去抖统计汇总成 collect 段顶层字段。

    口径：计数 sum、``move_guard`` any、``move_cap``/``move_repeat_limit`` 取首个；
    没有任何一条带 ``move_guard`` 的 meta（= 默认关闭）返回 ``{}``（不新增键）。
    """
    rows = [m for m in metas if isinstance(m, dict) and m.get("move_guard")]
    if not rows:
        return {}
    first = rows[0]
    sum_keys = ("move_guard_decisions", "move_guard_moves",
                "move_guard_blocked_inverse", "move_guard_blocked_repeat",
                "move_guard_blocked_cap", "move_guard_forced")
    out: Dict[str, Any] = {
        "move_guard": True,
        "move_cap": int(first.get("move_cap", DEFAULT_MOVE_CAP)),
        "move_repeat_limit": int(first.get("move_repeat_limit",
                                           DEFAULT_MOVE_REPEAT_LIMIT)),
    }
    for key in sum_keys:
        out[key] = int(sum(int(m.get(key, 0) or 0) for m in rows))
    return out


__all__ = [
    "MOVE_LO", "MOVE_HI", "N_MOVES",
    "DEFAULT_MOVE_CAP", "DEFAULT_MOVE_REPEAT_LIMIT",
    "MoveGuard", "MoveGuardStats",
    "is_move", "decode_move", "encode_move",
    "aggregate_move_guard",
]
