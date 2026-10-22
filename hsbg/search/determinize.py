"""隐藏信息 determinization v0（Phase 1 简化版）。

现状与诚实边界（对应文档 §3.6）：
- 真实/BC 轨迹的 ``runs/rl/*.jsonl`` 摘要只有 ``opponent_size``（没有对手棋盘 token/stats）；
- 引擎/planning v1 没有“注入对手隐藏棋盘”的公开 API；
- 因此 v0 只做：从真实/BC 池按 ``(turn, tier)`` 采样**战团摘要**（size），记录为
  ``WarbandSample``；**不真正改变**引擎里对手的隐藏状态（``injected_hidden=False``）。
- ``oracle=False`` 是 Phase 1 唯一允许的搜索模式；oracle 只保留给未来训练期 teacher。
- 评估必须报告 **oracle gap**（见 §3.6），不能把“采样摘要”当成真实隐藏信息。

后续（bridge-analyst / env-builder 交付后）：
- 从 Power.log 重建对手真实战团 → bank 存完整 board token/stats；
- env-builder 提供隐藏状态注入接口后，``determinize`` 才真正 ``injected_hidden=True``。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from hsbg.search.forward import EngineForwardModel

__all__ = ["WarbandSample", "WarbandBank", "DeterminizeInfo", "determinize"]


@dataclass(frozen=True)
class WarbandSample:
    """一个对手战团摘要（v0 只有 size；完整 board 待 bridge 交付）。"""

    turn: int
    tier: int
    size: int
    source: str = "jsonl"

    def as_dict(self) -> Dict[str, Any]:
        return {"turn": int(self.turn), "tier": int(self.tier),
                "size": int(self.size), "source": self.source}


@dataclass
class WarbandBank:
    """从真实/BC 轨迹 JSONL 按 (turn,tier) 建桶的战团摘要库。"""

    buckets: Dict[Tuple[int, int], List[WarbandSample]] = field(default_factory=dict)
    n_records: int = 0
    sources: List[str] = field(default_factory=list)

    @classmethod
    def from_jsonl(cls, paths: Iterable[str | Path],
                   *, max_records: int = 200_000) -> "WarbandBank":
        bank = cls()
        for p in paths:
            path = Path(p)
            if not path.exists():
                continue
            bank.sources.append(str(path))
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if bank.n_records >= max_records:
                        break
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    obs = row.get("obs")
                    if not isinstance(obs, dict):
                        continue
                    turn = obs.get("turn")
                    tier = obs.get("tier")
                    size = obs.get("opponent_size")
                    if not isinstance(turn, int) or not isinstance(tier, int):
                        continue
                    if not isinstance(size, int) or size < 0:
                        continue
                    sample = WarbandSample(turn=turn, tier=max(1, min(6, tier)),
                                           size=int(size), source=str(path.name))
                    key = (int(turn) // 2, int(sample.tier))
                    bank.buckets.setdefault(key, []).append(sample)
                    bank.n_records += 1
        return bank

    def stats(self) -> Dict[str, Any]:
        sizes = [s.size for bucket in self.buckets.values() for s in bucket]
        if not sizes:
            return {"n_records": 0, "n_buckets": 0, "sources": list(self.sources)}
        return {
            "n_records": int(self.n_records),
            "n_buckets": len(self.buckets),
            "sources": list(self.sources),
            "size_mean": float(sum(sizes) / len(sizes)),
            "size_max": int(max(sizes)),
        }

    def sample(self, turn: int, tier: int,
               rng: Optional[random.Random] = None) -> Optional[WarbandSample]:
        if not self.buckets:
            return None
        rng = rng or random.Random(0)
        tier = max(1, min(6, int(tier)))
        # 最近 turn 桶（±1 桶），同 tier 优先；找不到再放宽 tier
        turn_bucket = int(turn) // 2
        candidates: List[Tuple[int, int, WarbandSample]] = []
        for (tb, tr), rows in self.buckets.items():
            if not rows:
                continue
            dt = abs(tb - turn_bucket)
            if dt <= 1:
                candidates.append((dt, abs(tr - tier), rng.choice(rows)))
        if not candidates:
            for (tb, tr), rows in self.buckets.items():
                if rows:
                    candidates.append((abs(tb - turn_bucket), abs(tr - tier),
                                       rng.choice(rows)))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        # 在距离最近的若干条里随机选一条，避免总取同一桶
        best_d = candidates[0][0]
        pool = [c[2] for c in candidates if c[0] == best_d]
        return rng.choice(pool) if pool else None


@dataclass
class DeterminizeInfo:
    """一次 determinization 的元信息（写入 bench/报告，防泄漏/防误读）。"""

    mode: str = "summary_only_uninjected"
    injected_hidden: bool = False
    oracle: bool = False
    n_world_lines: int = 1
    n_samples: int = 0
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "injected_hidden": bool(self.injected_hidden),
            "oracle": bool(self.oracle),
            "n_world_lines": int(self.n_world_lines),
            "n_samples": int(self.n_samples),
            "note": self.note,
        }


def _supports_hidden_injection(game: Any) -> bool:
    return any(hasattr(game, name) for name in (
        "inject_opponent_board", "set_opponent_board", "inject_hidden_state",
    ))


def determinize(model: EngineForwardModel, bank: Optional[WarbandBank] = None,
                *, seed: int = 0, oracle: bool = False,
                n_world_lines: int = 1,
                ) -> Tuple[EngineForwardModel, DeterminizeInfo]:
    """返回一条世界线（clone）+ 元信息；v0 不真正注入隐藏状态。

    ``oracle=True`` 仅用于未来训练期 teacher（当前 Phase 1 默认/测试都应为 False）。
    """
    if oracle:
        return model.clone(), DeterminizeInfo(
            mode="oracle_hidden_state", injected_hidden=True, oracle=True,
            n_world_lines=1, n_samples=0,
            note="oracle 仅训练期 teacher，禁止用于评估/部署",
        )
    dup = model.clone()
    if bank is None or not bank.buckets:
        return dup, DeterminizeInfo(
            mode="none", injected_hidden=False, oracle=False,
            n_world_lines=1, n_samples=0,
            note="没有 WarbandBank；不采样隐藏信息",
        )
    rng = random.Random(int(seed))
    try:
        hero = dup.hero
        turn = int(dup.turn)
        tier = int(getattr(hero, "tavern_tier", 1) or 1)
    except Exception:  # noqa: BLE001
        return dup, DeterminizeInfo(mode="none", injected_hidden=False,
                                    oracle=False, n_world_lines=1, n_samples=0,
                                    note="hero 不可用（终局）")
    samples = 0
    for _ in range(max(1, int(n_world_lines))):
        if bank.sample(turn, tier, rng) is not None:
            samples += 1
    if _supports_hidden_injection(dup.game):
        # v0 尚不调用（接口/语义待 env-builder 确认）；保留分支供后续接入
        return dup, DeterminizeInfo(
            mode="summary_only_uninjected", injected_hidden=False, oracle=False,
            n_world_lines=n_world_lines, n_samples=samples,
            note="检测到注入接口但 v0 未启用（语义待 env-builder 确认）",
        )
    return dup, DeterminizeInfo(
        mode="summary_only_uninjected", injected_hidden=False, oracle=False,
        n_world_lines=n_world_lines, n_samples=samples,
        note="v0 仅按 (turn,tier) 采样战团摘要；未注入隐藏 board/hand（数据缺口见文档 §3.6）",
    )
