"""动作序列辅助任务（turn 内动作 multi-hot 预测）的标签构造与权重 ramp（纯函数）。

设计/动机/已知局限见 ``docs/ACTION_SEQUENCE_AUX.md``。本模块只依赖 numpy
（BCE 部分惰性导入 torch），供三个位置共用：

1. **标签（采集/打包侧）**：``seq_targets_from_records`` 把「同一 ``(game_id, seat, turn)``
   的所有决策动作」聚合成 ``multi-hot(245) uint8``。这与「回合结束时把该回合动作回填给该
   回合所有 record」在语义上完全等价（每个回合的动作集合 == 该回合所有 record 的 action
   集合），但用 numpy 向量化在**打包阶段一次算完**，因此采集热路径零额外开销；
2. **权重 ramp（训练循环）**：``parse_coef_ramp("0.02@0,0.05@0.5")`` +
   ``ramp_coef(points, progress)`` / ``SeqCoefSchedule``：按累计 decisions 比例线性插值；
3. **损失（torch 侧）**：``seq_bce_loss`` = ``BCEWithLogits``，只在给定权重行上平均。

约束：默认关闭时（``seq_coef=0``）本模块的函数不会在 records→batch→loss 路径上被调用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .common import N_ACTIONS

#: 批次/records 里的标签键名（multi-hot uint8，形状 ``[n, 245]``）
SEQ_TARGET_KEY = "seq_target"

#: ramp 控制点：``[(progress, coef), ...]``，progress ∈ [0,1]，按 progress 升序
RampPoints = List[Tuple[float, float]]


# ══════════════════════════════════════════════════════════════════════════
# 1. 标签：turn 内动作 multi-hot(245) uint8
# ══════════════════════════════════════════════════════════════════════════
def seq_targets_from_records(records: Sequence[Dict[str, Any]], *,
                             n_actions: int = N_ACTIONS) -> np.ndarray:
    """决策记录 -> ``multi-hot(245) uint8``：该 seat 在该 turn 内**实际执行过的动作**。

    标签定义：对样本 ``(seat s, turn T)``，第 ``a`` 位为 1 当且仅当该 seat 在 turn T 内
    （含当前这一步及其后到回合结束）执行过动作 ``a``。因为每个决策恰好产生一条 record
    且 record 自带 ``(game_id, seat, turn, action)``，标签 = 同组 record 的 action 集合。

    参数：``records`` 每条至少含 ``game_id`` / ``seat`` / ``action``；``turn`` 缺失记 ``-1``
    （此时分组退化为「整局」，见文档「已知局限」）。

    返回 ``uint8[n, 245]``（n = 0 时返回空数组）。非法动作下标（越界）直接报错，避免
    静默把标签写到错误位。
    """
    n = len(records)
    out = np.zeros((n, int(n_actions)), dtype=np.uint8)
    if n == 0:
        return out
    gid = np.fromiter((int(r["game_id"]) for r in records), dtype=np.int64, count=n)
    seat = np.fromiter((int(r["seat"]) for r in records), dtype=np.int64, count=n)
    turn = np.fromiter((int(r.get("turn", -1)) for r in records), dtype=np.int64, count=n)
    act = np.fromiter((int(r["action"]) for r in records), dtype=np.int64, count=n)
    if act.min() < 0 or act.max() >= int(n_actions):
        raise ValueError(f"record 内动作下标越界（应 0..{int(n_actions) - 1}）")
    # (game_id, seat, turn) -> 组 id（同一回合 = 同一组；组内所有 record 共享同一标签）
    key = np.stack([gid, seat, turn], axis=1)
    _uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    n_groups = int(inv.max()) + 1
    bits = np.zeros(n_groups * int(n_actions), dtype=np.uint8)
    bits[inv * int(n_actions) + act] = 1
    return bits.reshape(n_groups, int(n_actions))[inv]


def seq_targets_from_packed(packed: Dict[str, np.ndarray], *,
                            n_actions: int = N_ACTIONS) -> np.ndarray:
    """SoA 数组（``pack_records_arrays`` 的输出）-> multi-hot 标签（向量化版本）。"""
    n = int(len(np.asarray(packed["actions"])))
    out = np.zeros((n, int(n_actions)), dtype=np.uint8)
    if n == 0:
        return out
    gid = np.asarray(packed["game_ids"], dtype=np.int64)
    seat = np.asarray(packed["seats"], dtype=np.int64)
    turn = (np.asarray(packed["turns"], dtype=np.int64)
            if "turns" in packed else np.full(n, -1, dtype=np.int64))
    act = np.asarray(packed["actions"], dtype=np.int64)
    if act.min() < 0 or act.max() >= int(n_actions):
        raise ValueError(f"packed 内动作下标越界（应 0..{int(n_actions) - 1}）")
    key = np.stack([gid, seat, turn], axis=1)
    _uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    n_groups = int(inv.max()) + 1
    bits = np.zeros(n_groups * int(n_actions), dtype=np.uint8)
    bits[inv * int(n_actions) + act] = 1
    return bits.reshape(n_groups, int(n_actions))[inv]


# ══════════════════════════════════════════════════════════════════════════
# 2. 权重 ramp（按 decisions 比例的线性插值）
# ══════════════════════════════════════════════════════════════════════════
def parse_coef_ramp(spec: str) -> RampPoints:
    """解析 ``"0.02@0,0.05@0.5"`` -> ``[(0.0, 0.02), (0.5, 0.05)]``。

    - ``@`` 左侧是系数（>=0 的有限数），右侧是**进度**（0..1 的有限数）；
    - 允许乱序，内部按进度排序；同一进度重复出现时保留**后面**的值；
    - 空串 -> ``[]``（= 不用 ramp，走常数系数）；语法/取值错误时抛 ``ValueError``。
    """
    text = str(spec or "").strip()
    if not text:
        return []
    points: RampPoints = []
    for chunk in text.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        if "@" not in piece:
            raise ValueError(f"seq-coef-ramp 项缺少 '@'：{piece!r}（应为 coef@progress）")
        coef_s, frac_s = piece.split("@", 1)
        try:
            coef = float(coef_s)
            frac = float(frac_s)
        except ValueError as exc:
            raise ValueError(f"seq-coef-ramp 项无法解析为浮点：{piece!r}") from exc
        if not math.isfinite(coef) or coef < 0.0:
            raise ValueError(f"seq-coef-ramp 系数必须是非负有限数：{piece!r}")
        if not math.isfinite(frac) or not (0.0 <= frac <= 1.0):
            raise ValueError(f"seq-coef-ramp 进度必须在 [0,1]：{piece!r}")
        points.append((float(frac), float(coef)))
    if not points:
        raise ValueError("seq-coef-ramp 没有任何有效控制点")
    points.sort(key=lambda p: p[0])
    merged: RampPoints = []
    for frac, coef in points:
        if merged and abs(merged[-1][0] - frac) <= 1e-12:
            merged[-1] = (float(frac), float(coef))
        else:
            merged.append((float(frac), float(coef)))
    return merged


def format_coef_ramp(points: Sequence[Tuple[float, float]]) -> str:
    """``[(0.0, 0.02), (0.5, 0.05)]`` -> ``"0.02@0.000,0.05@0.500"``（日志/报告用）。"""
    return ",".join(f"{float(c):g}@{float(f):.3f}" for f, c in points)


def ramp_coef(points: Sequence[Tuple[float, float]], progress: float) -> float:
    """线性 ramp：``progress`` 落在相邻控制点之间时按比例插值，两端 clamp。

    - ``points`` 为空 -> 0.0（调用方应改用常数系数）；
    - ``progress <= 第一个点`` -> 第一个点的系数；``>= 最后一个点`` -> 最后一个点的系数；
    - ``progress`` 非有限时按 0.0 处理（避免 NaN 污染损失）。
    """
    if not points:
        return 0.0
    p = float(progress)
    if not math.isfinite(p):
        p = 0.0
    p = min(1.0, max(0.0, p))
    if p <= points[0][0]:
        return float(points[0][1])
    if p >= points[-1][0]:
        return float(points[-1][1])
    for (f0, c0), (f1, c1) in zip(points[:-1], points[1:]):
        if f0 <= p <= f1:
            span = f1 - f0
            if span <= 1e-12:
                return float(c1)
            return float(c0 + (c1 - c0) * (p - f0) / span)
    return float(points[-1][1])


def resolve_coef(base_coef: float, points: Sequence[Tuple[float, float]],
                 progress: float) -> float:
    """有 ramp 用 ramp，否则用常数系数 ``base_coef``（>=0）。"""
    if points:
        return ramp_coef(points, progress)
    return max(0.0, float(base_coef))


@dataclass
class SeqCoefSchedule:
    """``--seq-coef`` / ``--seq-coef-ramp`` 的训练循环封装（按累计 decisions 取系数）。

    ``total_decisions`` 是 ramp 100% 进度对应的累计 decisions 预算；<=0 时进度恒为 0
    （停留在第一个控制点），并在 :meth:`describe` 里标注，避免静默按错误进度 ramp。
    """

    points: RampPoints = field(default_factory=list)
    base_coef: float = 0.0
    total_decisions: float = 0.0

    @classmethod
    def from_spec(cls, base_coef: float = 0.0, spec: str = "",
                  total_decisions: float = 0.0) -> "SeqCoefSchedule":
        return cls(points=parse_coef_ramp(spec), base_coef=float(base_coef),
                   total_decisions=float(total_decisions))

    @property
    def enabled(self) -> bool:
        """是否启用：常数系数 > 0，或 ramp 里存在正系数。"""
        if float(self.base_coef) > 0.0:
            return True
        return any(float(c) > 0.0 for _f, c in self.points)

    def progress(self, cum_decisions: float) -> float:
        total = float(self.total_decisions)
        if total <= 0.0:
            return 0.0
        cum = float(cum_decisions)
        if not math.isfinite(cum) or cum <= 0.0:
            return 0.0
        return min(1.0, cum / total)

    def coef(self, cum_decisions: float = 0.0) -> float:
        """当前 iteration 应使用的系数（按累计 decisions 的进度插值）。"""
        return resolve_coef(self.base_coef, self.points, self.progress(cum_decisions))

    def describe(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "base_coef": float(self.base_coef),
            "ramp": format_coef_ramp(self.points),
            "ramp_total_decisions": float(self.total_decisions),
            "ramp_progress_at_zero": bool(self.points) and float(self.total_decisions) <= 0.0,
        }


# ══════════════════════════════════════════════════════════════════════════
# 3. 损失：BCEWithLogits（只对给定权重行平均）
# ══════════════════════════════════════════════════════════════════════════
def seq_bce_loss(seq_logits: Any, seq_target: Any, weight: Any = None):
    """``BCEWithLogits(seq_logits, seq_target)`` 的加权均值（torch 张量，惰性导入 torch）。

    - 先对每个样本的 245 维取均值（多标签 CE 的常规做法），再按 ``weight``（0/1 或实数）
      对样本加权平均；``weight`` 为 None 时对整批平均；
    - 权重全 0 时返回 0（不产生 NaN）。
    """
    import torch
    import torch.nn.functional as F

    per = F.binary_cross_entropy_with_logits(
        seq_logits.float(), seq_target.float(), reduction="none").mean(dim=-1)
    if weight is None:
        return per.mean()
    w = weight.to(per.dtype).clamp_min(0.0)
    denom = w.sum().clamp_min(1.0)
    return (per * w).sum() / denom


__all__ = [
    "SEQ_TARGET_KEY",
    "RampPoints",
    "seq_targets_from_records",
    "seq_targets_from_packed",
    "parse_coef_ramp",
    "format_coef_ramp",
    "ramp_coef",
    "resolve_coef",
    "SeqCoefSchedule",
    "seq_bce_loss",
]
