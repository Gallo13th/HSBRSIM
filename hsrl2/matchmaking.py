"""8 人配对 — 纯函数 (RULES §4.8 + 附录配对规则)。

规则依据 (docs/BATTLEGROUNDS_RULES.md §4.8):
  - 每回合存活玩家两两配对进行战斗
  - 避免与最近 2 个对手重复配对（官方重复回避语义）
  - 奇数存活玩家时余 1 人，由调用方安排幽灵（Kel'Thuzad）战斗

实现说明（与作业单贪心草图的差异，为满足"最近对手回避生效"）:
  单轮贪心存在尾部强制——p 被处理时若剩余者恰好全是 p 的最近对手，
  "放开限制重选"会制造连续重复对手（官方 MM 不允许，可行时必回避）。
  因此保留作业单的贪心为单次尝试，外层最多重洗 _MAX_PAIRING_ATTEMPTS 次，
  直到形成零回避违规的配对；全部尝试仍有违规时取违规最少的一组
  （放开限制的兜底语义）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from hsrl2.hero import Hero
    from hsrl2.rng import GameRNG

_MAX_PAIRING_ATTEMPTS = 50


def _violates(p1: "Hero", p2: "Hero",
              opponent_history: Dict["Hero", List["Hero"]]) -> bool:
    """p1/p2 互为对方最近 2 个对手之一 → 回避违规。"""
    if p2 in opponent_history.get(p1, [])[-2:]:
        return True
    if p1 in opponent_history.get(p2, [])[-2:]:
        return True
    return False


def _greedy(order: List["Hero"], rng: "GameRNG",
            opponent_history: Dict["Hero", List["Hero"]]
            ) -> Tuple[List[Tuple["Hero", "Hero"]], Optional["Hero"]]:
    """单轮贪心 (作业单算法): 依序取未配对者 p，排除 p 的最近 2 个对手，
    rng.choice；全部被排除时放开限制重选；奇数人返回 leftover。"""
    pairs: List[Tuple["Hero", "Hero"]] = []
    leftover: Optional["Hero"] = None
    remaining = list(order)
    while remaining:
        p = remaining.pop(0)
        recent = list(opponent_history.get(p, [])[-2:])
        candidates = [q for q in remaining if q not in recent]
        if not candidates and remaining:
            # p 的最近 2 个对手覆盖了全部剩余者 → 放开回避限制 (RULES §4.8)
            candidates = list(remaining)
        if not candidates:
            leftover = p
            break
        q = rng.choice(candidates, label="matchmaking_pair")
        remaining.remove(q)
        pairs.append((p, q))
    return pairs, leftover


def pair_players(alive: List["Hero"], rng: "GameRNG",
                 opponent_history: Dict["Hero", List["Hero"]]
                 ) -> Tuple[List[Tuple["Hero", "Hero"]], Optional["Hero"]]:
    """配对存活玩家。返回 (pairs, leftover)。

    算法 (RULES §4.8):
      1. rng.shuffle 洗牌 alive（随机配对序）
      2. 贪心配对，排除每个 p 的最近 2 个对手
      3. 形成的配对含回避违规时重洗重试（≤ _MAX_PAIRING_ATTEMPTS 次），
         取违规最少的结果 — 官方"可行时必回避连续重复对手"
      4. 奇数人: 最后剩 1 人为 leftover（由调用方安排幽灵战）
      5. 配对完成后把对手互相 append 进 opponent_history，各保留最近 2 个

    纯函数: 不修改 game 状态，只写 opponent_history（调用方传入的簿记）。
    """
    players = list(alive)
    best: Optional[Tuple[List[Tuple["Hero", "Hero"]], Optional["Hero"], int]] = None
    for _ in range(_MAX_PAIRING_ATTEMPTS):
        order = list(players)
        rng.shuffle(order, label="matchmaking_shuffle")
        pairs, leftover = _greedy(order, rng, opponent_history)
        violations = sum(1 for p1, p2 in pairs
                         if _violates(p1, p2, opponent_history))
        if violations == 0:
            best = (pairs, leftover, 0)
            break
        if best is None or violations < best[2]:
            best = (pairs, leftover, violations)
    pairs, leftover, _ = best
    for p1, p2 in pairs:
        opponent_history.setdefault(p1, []).append(p2)
        opponent_history.setdefault(p2, []).append(p1)
        opponent_history[p1] = opponent_history[p1][-2:]
        opponent_history[p2] = opponent_history[p2][-2:]
    return pairs, leftover
