"""对手场面轨迹镜像库：整局状态 + 逐回合对手动作，回放时 bot 接管兜底。

设计要点（用户 a. 方案）：
- 记录的是**整局状态**（`Game.state_json()`）而不是单座位状态 → `Game.from_json` 恢复时
  pool / eid / lobby_races / eliminated 等全局结构随状态一起回来，不存在逐座位移植的不变量问题；
- 每帧记录「该回合所有座位的动作」→ 训练时 learner 占 seat0，其余 7 席**回放轨迹动作**；
  动作在当前状态下非法（因为 learner 的行动改变了后续局面）时，该座位交回引擎 bot（bot 接管）；
- 轨迹不足（对局在 t_k 结束）时，从恢复点一直打到终局，后续回合自然由 bot 接管。

文件格式见 `scripts/capture_trajectory.py`。
"""

from __future__ import annotations

import glob
import gzip
import json
import os
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class Trajectory:
    seed: int
    placements: List[int]
    frames: List[Dict[str, Any]]
    learner_seat: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)
    path: str = ""

    @property
    def entry_turn(self) -> int:
        return int(self.frames[0]["turn"]) if self.frames else 0

    def frame_at(self, turn: int) -> Optional[Dict[str, Any]]:
        for fr in self.frames:
            if int(fr["turn"]) == int(turn):
                return fr
        return None

    def actions_at(self, turn: int) -> List[List[int]]:
        fr = self.frame_at(turn)
        return list(fr["actions"]) if fr else []

    def strength(self) -> int:
        """简单强度指标：最终名次里第 1 名的存活回合数 + 帧数（粗排用）。"""
        return len(self.frames) + (1 if self.placements else 0)


class TrajectoryPool:
    """目录式轨迹池：按 entry_turn 分桶、按强度排序采样、支持去重与滚动追加。"""

    def __init__(self, root: Optional[str] = None, *, generation_decay: float = 0.01):
        self.root = root
        self.generation_decay = float(generation_decay)
        self.items: List[Trajectory] = []
        if root:
            self.load(root)

    def load(self, root: str) -> int:
        self.root = root
        n = 0
        for path in sorted(glob.glob(os.path.join(root, "traj_*.json.gz"))):
            try:
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            if not d.get("frames"):
                continue
            self.items.append(Trajectory(seed=int(d.get("seed", 0)),
                                         placements=list(d.get("placements") or []),
                                         frames=list(d["frames"]),
                                         learner_seat=int(d.get("learner_seat", 0)),
                                         meta=dict(d.get("meta") or {}), path=path))
            n += 1
        return n

    def sample(self, rng: Optional[random.Random] = None,
               entry_turn: Optional[int] = None, tolerance: int = 2
               ) -> Optional[Trajectory]:
        """按 (帧数 + 入口回合) 选强轨迹，并对旧文件施加世代衰减。"""
        if not self.items:
            return None
        rng = rng or random.Random(0)
        cands = self.items
        if entry_turn is not None:
            cands = [t for t in self.items if abs(t.entry_turn - int(entry_turn)) <= tolerance]
            if not cands:
                cands = self.items
        newest = max(self._mtime(t) for t in cands) or 1.0

        def _score(t: Trajectory) -> float:
            age = max(0.0, (newest - self._mtime(t)) / 86400.0)   # 天
            return t.strength() * (1.0 - self.generation_decay) ** age

        cands = sorted(cands, key=_score, reverse=True)
        top = cands[:max(1, min(len(cands), 16))]
        return rng.choice(top)

    @staticmethod
    def _mtime(t: "Trajectory") -> float:
        try:
            return os.path.getmtime(t.path) if t.path else 0.0
        except OSError:
            return 0.0

    def stats(self) -> Dict[str, Any]:
        if not self.items:
            return {"size": 0}
        turns = sorted(t.entry_turn for t in self.items)
        sizes = sorted(os.path.getsize(t.path) for t in self.items if t.path)
        return {"size": len(self.items),
                "entry_turn_min": turns[0], "entry_turn_max": turns[-1],
                "file_kb_p50": round(sizes[len(sizes) // 2] / 1024.0, 1) if sizes else 0,
                "total_mb": round(sum(sizes) / 1e6, 1) if sizes else 0}


def restore_frame(game_factory: Any, traj: Trajectory, turn: Optional[int] = None) -> Tuple[Any, int]:
    """把轨迹的某一帧恢复成一局新游戏；返回 (game, turn)。

    `game_factory(state_json)` 由调用方提供（一般是 `hsbg_engine.Game.from_json`）。
    """
    fr = traj.frame_at(turn) if turn is not None else traj.frames[0]
    if fr is None:
        fr = traj.frames[0]
    game = game_factory(fr["state"])
    return game, int(fr["turn"])


__all__ = ["Trajectory", "TrajectoryPool", "restore_frame"]


class ReplayScript:
    """把一条轨迹的「逐回合动作」变成可按 (seat, turn) 顺序取用的脚本。

    用法::

        script = ReplayScript(traj)
        a = script.next_action(seat, turn)   # None = 没有记录/已用完 → 交回 bot
    """

    def __init__(self, traj: Trajectory, learner_seat: int = 0):
        self.traj = traj
        self.learner_seat = int(learner_seat)
        self._queues: Dict[Tuple[int, int], List[int]] = {}
        for fr in traj.frames:
            turn = int(fr["turn"])
            for seat, action in fr["actions"]:
                seat = int(seat)
                if seat == self.learner_seat:
                    continue
                self._queues.setdefault((seat, turn), []).append(int(action))

    def next_action(self, seat: int, turn: int) -> Optional[int]:
        q = self._queues.get((int(seat), int(turn)))
        if not q:
            return None
        return q.pop(0)

    def has_turn(self, turn: int) -> bool:
        """该回合是否还有**未取完**的动作。"""
        return any(q for k, q in self._queues.items() if k[1] == int(turn))
