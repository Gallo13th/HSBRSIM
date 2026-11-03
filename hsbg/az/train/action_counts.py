"""动作分类/计数：训练侧（batch.actions）与评估侧（collector turns.actions）共用同一口径。

约定（与 hsbg/env/action_space_std 一致）：
- 0 = end_turn；1 = refresh(roll)；2 = freeze；3 = upgrade；8..15 = buy slot；
- 16..23 = sell slot；30..45 = choose；45 = hero power（本仓库扩展段）；46.. = play。
"""
from __future__ import annotations

from typing import Dict, Iterable

A_END = 0
A_REFRESH = 1
A_FREEZE = 2
A_UPGRADE = 3
A_BUY = 8
N_SHOP = 8
A_SELL = 16
N_BOARD = 8
A_CHOOSE = 30
N_CHOICE = 16
A_HERO_POWER = 4  # 英雄技能槽（主槽；真实动作空间为 4/5，不是 45）
A_PLAY = 46


def classify(a: int) -> str:
    """把动作 id 归到一个类别；未知返回 ``other``。"""
    a = int(a)
    if a == A_REFRESH:
        return "roll"
    if a == A_UPGRADE:
        return "upgrade"
    if A_BUY <= a < A_BUY + N_SHOP:
        return "buy"
    if A_SELL <= a < A_SELL + N_BOARD:
        return "sell"
    if A_CHOOSE <= a < A_CHOOSE + N_CHOICE:
        return "choose"
    if a == A_HERO_POWER:
        return "hero_power"
    if a >= A_PLAY:
        return "play"
    if a == A_END:
        return "end"
    if a == A_FREEZE:
        return "freeze"
    return "other"


def count_actions(actions: Iterable[int]) -> Dict[str, int]:
    """对一串动作 id 计数（两侧统一入口）。"""
    out: Dict[str, int] = {}
    for x in actions:
        k = classify(int(x))
        out[k] = out.get(k, 0) + 1
    return out
