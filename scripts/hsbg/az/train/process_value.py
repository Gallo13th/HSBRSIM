"""过程价值（process value）：给「终局名次对 t12 缩放无梯度」补辅助监督。

题面（`runs/ceiling_probe/REPORT.md` §3）：终局名次奖励对 t12 的缩放行为没有梯度；
需要**过程目标**。本模块定义三个可从引擎状态直接读取的过程量（默认关闭）：

1. ``tavern_buff`` = 酒馆随从的「本局永久 buff」总和（``shop[].breakdown.
   this_game_bonus`` 的 atk+hp 逐张累加）；
2. ``spells_cast`` = 本局施法次数（``player.stats.spells_cast``）；
3. ``consume`` = 本局 consume 事件计数（需要 ``Game.set_record_log(True)`` 后数
   ``g.log()`` 里的 ``" consumes "`` 行；不可得时为 0）。

三个目标都做 ``log1p`` 压缩后作为**辅助价值头**的回归标签（3 维）。损失只在
目标可得的样本上算；``process_value_coef=0``（默认）时不建头、不读日志、不算
损失、不改前向 —— 与旧路径逐位等价。

为什么与 ``strength_head`` 分开：``strength_head`` 预测的是 t+3 战团强度增量
（终局结果代理），已被证对策略无用；这里预测的是**过程量本身**（缩放动作的
直接可观测产出），只经辅助损失回传 trunk，不进入策略 logits / 价值备份。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 过程目标维度
N_PROCESS = 3

#: 日志里的 consume 事件前缀（`finish_consume` 的 log 文案："... consumes ..."）
CONSUME_TOKEN = " consumes "


def tavern_perm_buff(player: Dict[str, Any]) -> int:
    """酒馆随从的永久（本局）buff 总和：Σ shop[i].breakdown.this_game_bonus。"""
    total = 0
    for item in player.get("shop") or []:
        if not isinstance(item, dict) or not (
                str(item.get("type") or "") == "minion" or "atk" in item):
            continue
        bd = item.get("breakdown") or {}
        bonus = bd.get("this_game_bonus") if isinstance(bd, dict) else None
        if isinstance(bonus, (list, tuple)) and len(bonus) >= 2:
            total += int(bonus[0] or 0) + int(bonus[1] or 0)
        else:
            # 退化：当前身材 - 基础身材（仍只统计酒馆随从）
            total += max(0, int(item.get("atk") or 0) - int(item.get("base_atk") or 0))
            total += max(0, int(item.get("hp") or 0) - int(item.get("base_hp") or 0))
    return int(total)


def consume_count(log: Optional[Sequence[str]], prev: int = 0) -> int:
    """日志里的 consume 事件累计数（``prev`` 用于增量缓存）。"""
    if not log:
        return int(prev)
    n = 0
    for line in log:
        if CONSUME_TOKEN in str(line):
            n += 1
    return int(max(prev, n))


def process_target(player: Dict[str, Any], *,
                   consume: int = 0) -> List[float]:
    """状态 -> 3 维过程目标（log1p 压缩；确定性、无副作用）。"""
    stats = player.get("stats") or {}
    try:
        casts = int(stats.get("spells_cast") or 0)
    except (TypeError, ValueError):
        casts = 0
    return [
        float(math.log1p(max(0, tavern_perm_buff(player)))),
        float(math.log1p(max(0, casts))),
        float(math.log1p(max(0, int(consume)))),
    ]


def process_available(player: Optional[Dict[str, Any]]) -> bool:
    """目标是否可得：recruit 阶段 learner 必须有 player JSON + stats。"""
    return isinstance(player, dict) and isinstance(player.get("stats"), dict)


def process_value_loss(pred: Any, targets: Any, mask: Any) -> Dict[str, Any]:
    """带掩码的 3 维 MSE；``mask`` 为 1 的行才参与平均（torch 张量输入）。"""
    import torch
    import torch.nn.functional as F

    p = pred.float()
    t = targets.float()
    v = mask.float().reshape(-1, 1)
    mse_all = (p - t) ** 2
    denom = v.sum().clamp_min(1.0) * float(t.shape[-1] if t.ndim > 1 else 1)
    loss = (mse_all * v).sum() / denom
    with torch.no_grad():
        n = float(v.sum().item())
        per = (mse_all * v).sum(dim=0) / v.sum().clamp_min(1.0)
    return {"loss": loss, "n": n,
            "mse_tavern": float(per[0].item()) if per.numel() > 0 else 0.0,
            "mse_casts": float(per[1].item()) if per.numel() > 1 else 0.0,
            "mse_consume": float(per[2].item()) if per.numel() > 2 else 0.0}


__all__ = [
    "N_PROCESS", "CONSUME_TOKEN", "tavern_perm_buff", "consume_count",
    "process_target", "process_available", "process_value_loss",
]
