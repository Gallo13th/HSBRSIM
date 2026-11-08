"""经济（金币）课程：把「金币收入 ×mult」作为课程第一阶段。

背景（`runs/ceiling_probe/REPORT.md` §2/§3）：真实经济下「只买身材」的脚本/训练策略
在 t12 只有真实人类 p50 的 4–13%；而同一套施法缩放脚本在 **∞ 金币** 下能到 41%
（p50 1843），p90 = 1.35× 真实 p50。差距不是机制缺失，而是真实经济的买牌节奏
（3 金/张）走不到「法术→酒馆永久 buff」的缩放链路。本模块实现最小经济课程：

- ``none``：关闭（默认）——采集侧完全不碰金币，逐位等价旧路径；
- ``warmup``：训练开始时给 learner 的**金币收入** ×``mult``，在
  ``anneal_decisions`` 个决策内线性降到 1.0（题面口径）；
- ``anneal``：先按 ``mult`` 保持 ``anneal_decisions`` 个决策，再用同样长的时间
  线性降到 1.0（长课程；warmup 阶段结束后继续 anneal 用）。

「金币收入 ×mult」只放大**本回合新收入**，不放大上回合结余：采集侧在每回合开始
记录「上一回合结束时的结余 carry」，本回合实际金币 = carry + (当前金币 - carry)×mult。
这样 10 金/回合 → 30 金/回合（不是指数膨胀），且默认 ``mult=1.0`` 时公式恒等。

实现位置：``parallel_collect.collect_ppo_lockstep``（训练主路径）与
``ppo.collect_ppo_batch``（串行/线程采集路径）。引擎侧不改 Rust：用
``Game.debug({"cmd":"set_player","p":seat,"gold":N})`` 设置金币。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

#: 合法课程阶段
STAGES = ("none", "warmup", "anneal")

#: 默认 anneal 窗口（decisions）
DEFAULT_ANNEAL_DECISIONS = 10_000_000.0


def normalize_stage(stage: Any) -> str:
    """规范化阶段名；非法值直接报错（不静默降级）。"""
    s = str(stage or "none").strip().lower()
    if s not in STAGES:
        raise ValueError(f"curriculum_stage 只能是 {STAGES}，得到 {stage!r}")
    return s


def validate_gold_mult(mult: Any) -> float:
    """金币倍数：必须有限且 >= 1.0（<1 不是「加钱课程」）。"""
    try:
        m = float(mult)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"curriculum_gold_mult 必须是数字，得到 {mult!r}") from exc
    if not math.isfinite(m) or m < 1.0:
        raise ValueError(f"curriculum_gold_mult 必须有限且 >= 1.0，得到 {mult!r}")
    return m


def validate_anneal_decisions(n: Any) -> float:
    """anneal 窗口必须有限且 > 0。"""
    try:
        v = float(n)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"curriculum_anneal_decisions 必须是数字，得到 {n!r}") from exc
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"curriculum_anneal_decisions 必须有限且 > 0，得到 {n!r}")
    return v


def anneal_progress(decisions: float, anneal_decisions: float) -> float:
    """课程进度：0 = 起点，1 = 已完全退火到真实经济（clamp）。"""
    d = max(0.0, float(decisions))
    w = max(1e-9, float(anneal_decisions))
    return max(0.0, min(1.0, d / w))


def gold_mult_at(decisions: float, *, stage: Any = "none",
                 mult: float = 1.0,
                 anneal_decisions: float = DEFAULT_ANNEAL_DECISIONS) -> float:
    """按**累计 decisions** 求当前金币收入倍数（确定性、无状态）。

    - ``none`` -> 1.0（无论其它参数）；
    - ``warmup`` -> ``1 + (mult-1) * (1 - progress)``（progress 在
      ``anneal_decisions`` 内从 0 到 1；结束恒 1.0）；
    - ``anneal`` -> 前一半窗口保持 ``mult``，后一半线性降到 1.0。

    ``decisions`` / ``anneal_decisions`` 的边界都在函数内 clamp，不抛异常。
    """
    st = normalize_stage(stage)
    if st == "none":
        return 1.0
    m = validate_gold_mult(mult)
    w = validate_anneal_decisions(anneal_decisions)
    if m == 1.0:
        return 1.0
    p = anneal_progress(decisions, w)
    if st == "warmup":
        return float(1.0 + (m - 1.0) * (1.0 - p))
    # anneal：前半保持，后半退火
    tail = max(0.0, (p - 0.5) * 2.0)
    return float(m - (m - 1.0) * min(1.0, tail))


def curriculum_schedule(*, stage: Any = "none", mult: float = 1.0,
                        anneal_decisions: float = DEFAULT_ANNEAL_DECISIONS
                        ) -> Dict[str, Any]:
    """训练入口用的规范化配置（非法值在启动期报错）。"""
    st = normalize_stage(stage)
    return {
        "curriculum_stage": st,
        "curriculum_gold_mult": validate_gold_mult(mult),
        "curriculum_anneal_decisions": validate_anneal_decisions(anneal_decisions),
    }


def gold_for_turn(*, gold_now: int, carry: int, mult: float) -> int:
    """本回合开始时的实际金币 = carry + (gold_now - carry) * mult。

    ``gold_now`` 是引擎在回合开始后给出的「结余 + 本回合收入」；``carry`` 是上一回合
    结束时（learner 最后一次行动后）的金币结余。``mult=1`` 时逐位返回 ``gold_now``。
    ``gold_now < carry``（异常/其它效果）时按 0 收入处理，只保留 carry。
    """
    g = int(gold_now)
    c = max(0, int(carry))
    m = validate_gold_mult(mult)
    if m == 1.0:
        return g
    income = max(0, g - c)
    return int(c + int(round(float(income) * m)))


def apply_turn_gold(game: Any, seat: int, *, carry: int, mult: float,
                    gold_now: Optional[int] = None) -> Dict[str, int]:
    """把 learner 本回合金币设成 ``gold_for_turn``；返回统计（不改变引擎默认行为）。

    ``mult=1.0`` 时**不调用** ``game.debug``，也不读 ``player_json``（逐位等价）。
    调用方负责只在「新回合开始、learner 第一次决策前」调用一次。
    """
    import json

    if float(mult) == 1.0:
        return {"applied": 0, "gold_before": 0, "gold_after": 0, "extra": 0}
    pj = json.loads(game.player_json(int(seat)))
    before = int(pj.get("gold") or 0) if gold_now is None else int(gold_now)
    after = gold_for_turn(gold_now=before, carry=int(carry), mult=float(mult))
    if after != before:
        game.debug(json.dumps({"cmd": "set_player", "p": int(seat), "gold": int(after)}))
    return {"applied": 1, "gold_before": before, "gold_after": int(after),
            "extra": int(after - before)}


__all__ = [
    "STAGES", "DEFAULT_ANNEAL_DECISIONS", "normalize_stage", "validate_gold_mult",
    "validate_anneal_decisions", "anneal_progress", "gold_mult_at",
    "curriculum_schedule", "gold_for_turn", "apply_turn_gold",
]
