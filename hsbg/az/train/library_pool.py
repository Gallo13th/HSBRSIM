"""镜像对手库（M2/M3 的数据层）：精确状态 JSONL + 按 turn/强度采样 + 滚动更新。

与旧的 `hsbg/az/library.py` 的区别：
- 存的是引擎的 **完整 player 状态 JSON**（`Game.player_json(seat)`），用
  `Game.set_player_from_json` 精确注入；旧实现只存牌面且卡 id 会被 golden 归一化改写；
- 带质量门与世代信息，支持随训练滚动追加。

存储格式（JSONL，一行一条）::

    {"player": {...}, "turn": 12, "placement": 1, "strength": 88,
     "checkpoint": "runs/az_entity_s3/model.pt", "source": "eval", "created_iter": 240,
     "signature": "12:...", "game_seed": 12345, "seat": 3}
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def board_strength(player: Dict[str, Any]) -> int:
    """牌面强度：Σ(atk+hp)（注入/采样排序用）。"""
    return sum(int(m.get("atk", 0)) + int(m.get("hp", 0))
               for m in player.get("board", []))


def board_signature(player: Dict[str, Any]) -> str:
    """牌面签名：卡 id（原始）+ atk/hp/golden，用于去重。"""
    items = [(int(m.get("card", -1)), int(m.get("atk", 0)), int(m.get("hp", 0)),
              bool(m.get("golden", False))) for m in player.get("board", [])]
    return "|".join(f"{c}:{a}:{h}:{int(g)}" for c, a, h, g in items)


@dataclass
class LibraryEntry:
    player: Dict[str, Any]
    turn: int
    placement: int
    strength: int
    checkpoint: str = ""
    source: str = "eval"
    created_iter: int = 0
    game_seed: int = 0
    seat: int = 0

    @property
    def signature(self) -> str:
        return f"t{self.turn}:" + board_signature(self.player)

    def to_json(self) -> Dict[str, Any]:
        return {"player": self.player, "turn": int(self.turn),
                "placement": int(self.placement), "strength": int(self.strength),
                "checkpoint": self.checkpoint, "source": self.source,
                "created_iter": int(self.created_iter), "game_seed": int(self.game_seed),
                "seat": int(self.seat), "signature": self.signature}

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> "LibraryEntry":
        return cls(player=d["player"], turn=int(d["turn"]), placement=int(d["placement"]),
                   strength=int(d.get("strength", 0)), checkpoint=str(d.get("checkpoint", "")),
                   source=str(d.get("source", "eval")),
                   created_iter=int(d.get("created_iter", 0)),
                   game_seed=int(d.get("game_seed", 0)), seat=int(d.get("seat", 0)))


class LibraryPool:
    """按 turn 分桶的对手牌面池；支持去重、质量门、世代衰减与滚动追加。"""

    def __init__(self, path: Optional[str] = None, *, bucket: int = 1,
                 min_turn: int = 8, max_placement: int = 2, min_board: int = 4):
        self.path = path
        self.bucket = max(1, int(bucket))
        self.min_turn = int(min_turn)
        self.max_placement = int(max_placement)
        self.min_board = int(min_board)
        self.entries: List[LibraryEntry] = []
        self._seen: set = set()
        if path and os.path.isfile(path):
            self.load(path)

    # ---- 写入 ----
    def accepts(self, entry: LibraryEntry) -> bool:
        if entry.placement < 1 or entry.placement > self.max_placement:
            return False
        if entry.turn < self.min_turn:
            return False
        if len(entry.player.get("board", [])) < self.min_board:
            return False
        if entry.strength <= 0:
            entry.strength = board_strength(entry.player)
        return entry.strength > 0

    def add(self, entry: LibraryEntry) -> bool:
        if not self.accepts(entry):
            return False
        sig = entry.signature
        if sig in self._seen:
            return False
        self._seen.add(sig)
        self.entries.append(entry)
        return True

    def add_many(self, items: Iterable[LibraryEntry]) -> int:
        n = 0
        for e in items:
            n += int(self.add(e))
        return n

    # ---- 采样 ----
    def _bucket_of(self, turn: int) -> int:
        return int(turn) // self.bucket

    def sample(self, turn: int, rng: Optional[random.Random] = None,
               target_strength: Optional[int] = None,
               tolerance: int = 1) -> Optional[LibraryEntry]:
        """取 turn 桶相近（±tolerance 桶）里最强的牌面；没有则返回 None。"""
        rng = rng or random
        b = self._bucket_of(turn)
        cands = [e for e in self.entries
                 if abs(self._bucket_of(e.turn) - b) <= max(0, int(tolerance))]
        if not cands:
            return None
        if target_strength is not None:
            cands.sort(key=lambda e: abs(e.strength - int(target_strength)))
            return cands[0]
        cands.sort(key=lambda e: e.strength, reverse=True)
        return cands[0]

    # ---- 持久化 ----
    def load(self, path: str) -> int:
        n = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = LibraryEntry.from_json(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
                if self.add(e):
                    n += 1
        self.path = path
        return n

    def save(self, path: Optional[str] = None) -> str:
        path = path or self.path
        if not path:
            raise ValueError("LibraryPool 没有 path")
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        self.path = path
        return path

    # ---- 统计 ----
    def stats(self) -> Dict[str, Any]:
        if not self.entries:
            return {"size": 0}
        strengths = sorted(e.strength for e in self.entries)
        turns = sorted(e.turn for e in self.entries)

        def _pct(xs: Sequence[int], q: float) -> int:
            return int(xs[min(len(xs) - 1, int(q * (len(xs) - 1)))])

        by_turn: Dict[int, int] = {}
        for e in self.entries:
            by_turn[self._bucket_of(e.turn)] = by_turn.get(self._bucket_of(e.turn), 0) + 1
        return {"size": len(self.entries),
                "strength_p50": _pct(strengths, 0.5), "strength_p90": _pct(strengths, 0.9),
                "turn_min": turns[0], "turn_max": turns[-1],
                "buckets": dict(sorted(by_turn.items()))}


def capture_from_game(game: Any, *, checkpoint: str = "", source: str = "eval",
                      created_iter: int = 0, game_seed: int = 0,
                      turns: Sequence[int] = (8, 10, 12, 15, 18),
                      seats: Optional[Sequence[int]] = None) -> List[LibraryEntry]:
    """从一局已结束的对局里采集「强座位」的完整状态。

    注意：必须在**对局进行中**按 turn 抓取（结束后状态已清空），见
    `scripts/capture_library.py` 的用法。
    """
    raise NotImplementedError("按 turn 抓取请用 scripts/capture_library.py")


__all__ = ["LibraryEntry", "LibraryPool", "board_strength", "board_signature",
           "capture_from_game"]
