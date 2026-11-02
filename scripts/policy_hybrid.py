#!/usr/bin/env python3
"""混合策略：按回合区间在「模型（greedy/采样）」与「阵容脚本」之间切换。

用法（在 human_panel_eval.py / quality_monitor.py 里加 ``--handover-spec``）::

  --handover-spec "t0-8:model,t9-15:script"    # hybrid@t9
  --handover-spec "t0-10:model,t11-15:script"  # hybrid@t11

脚本侧复用 ``scripts/comp_scripts.py`` 的 CompPolicy（``--comp auto``：按当前盘面选最匹配套）。
纯推理、无训练；两段共用同一局（金币/tier/盘面完全继承）。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, List, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hsbg.az.train.common import mask_from_bytes  # noqa: E402
import comp_scripts as CS  # noqa: E402


class _D:
    __slots__ = ("action",)

    def __init__(self, a: int) -> None:
        self.action = int(a)


def parse_spec(spec: str) -> List[Tuple[int, int, str]]:
    out = []
    for part in str(spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        rng, who = part.split(":")
        lo, hi = rng.replace("t", "").split("-")
        out.append((int(lo), int(hi), str(who).strip()))
    return out or [(0, 99, "model")]


class ScriptAdapter:
    """把 comp_scripts.CompPolicy.act(view, mask) 适配成 decide(game, seat)。"""

    def __init__(self, spec: str = "auto", seed: int = 0) -> None:
        s = CS.COMPS.get(str(spec).strip()) if str(spec).strip().upper() in CS.COMPS else None
        self.pol = CS.CompPolicy(s, auto=(s is None), seed=int(seed))
        self.ho_stats = {"decisions": 0}

    def reset(self) -> None:
        self.ho_stats = {"decisions": 0}

    def decide(self, game: Any, seat: int = 0):
        v = json.loads(game.view(int(seat)))
        mask = mask_from_bytes(game.legal_mask(int(seat)))
        self.ho_stats["decisions"] += 1
        return _D(self.pol.act(v, mask))


class HybridPolicy:
    """按引擎 turn 切换：``model`` 段用净策略，``script`` 段用 CompPolicy。"""

    def __init__(self, model_policy: Any, script: ScriptAdapter, spec: str) -> None:
        self.model = model_policy
        self.script = script
        self.spec = parse_spec(spec)
        self.ho_stats = {"decisions": 0, "model_decisions": 0, "script_decisions": 0}

    def _who(self, turn: int) -> str:
        for lo, hi, who in self.spec:
            if lo <= int(turn) <= hi:
                return who
        return "model"

    def reset(self) -> None:
        self.model.reset()
        self.script.reset()
        self.ho_stats = {"decisions": 0, "model_decisions": 0, "script_decisions": 0}

    def decide(self, game: Any, seat: int = 0):
        t = int(getattr(game, "turn", 0))
        self.ho_stats["decisions"] += 1
        if self._who(t) == "script":
            self.ho_stats["script_decisions"] += 1
            return self.script.decide(game, seat)
        self.ho_stats["model_decisions"] += 1
        return self.model.decide(game, seat)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.model, name)