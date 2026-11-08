"""对局镜像库（library seats）：采集、分档抽样、注入。

背景：AutoTavern 论文的训练对手不是 bot/自对弈，而是 7 个 **library seat**——每回合
从「按真人统计校准的牌面库」里抽一条 entry 作为该座位的当前牌面（含手牌/隐藏计数），
论文称这是最大单项收益（吃鸡率 20.9%→27.2%，同预算）。我们没有真人数据，因此用
**我们自己对局中冠军座位的牌面**做库（用户方案：镜像冠军对手的当前回合）。

本模块只做三件事，且都可单独测试：

1. ``capture_turn``：在一局游戏的「招募阶段结束」时刻，把每个座位的牌面抽成一条 entry
   （card id / atk / hp / golden / keywords / 手牌张数 / 血量 / tier）；
2. ``BoardLibrary``：按 ``(turn, 强度档)`` 建索引；``sample(turn, rng, target_strength)``
   按目标强度曲线抽 entry；可 gzip-jsonl 存取；
3. ``inject_board``：用引擎 debug 命令把一条 entry 覆写进某个座位（``clear_zone`` +
   ``add_minion`` + ``edit_minion``），供 collect 的 library 对手模式使用。

已知限制（写进报告，别当成完整实现）：

- 只还原**牌面**（手牌/酒馆/任务/饰品/技能计数不还原）。论文的 library entry 还带手牌和
  隐藏计数；我们缺人类统计，先用牌面近似，后续可用 ``set_player``/``add_spell`` 补齐；
- 注入用 ``add_minion`` 建卡 + ``edit_minion`` 改数值/关键词；卡牌自带的静态机制由引擎按
  card id 重建，**只有「被 buff 后才有的额外关键词」依赖 edit_minion 显式写回**；
- 强度档用 ``sum(atk+hp)``（warband 总攻防）；论文用的是分回合强度曲线，后续可替换；
- golden 随从注入后引擎会规范化成 ``...t_G`` 变体，卡 id 字符串可能不同，但 atk/hp/
  关键词一致（测试按去掉 ``t_G`` 后缀比对）。
"""

from __future__ import annotations

import gzip
import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

# 与 rust/crates/hsbg-engine/src/types.rs `Kw::NAMES` 一一对应（bit = 下标）
KW_NAMES: List[str] = [
    "TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS", "POISONOUS",
    "STEALTH", "MAGNETIC", "MEGA_WINDFURY", "CLEAVE", "IMMUNE", "IMMUNE_ATTACKING",
]


def kw_names(bits: int) -> List[str]:
    return [n for i, n in enumerate(KW_NAMES) if int(bits) & (1 << i)]


@dataclass
class BoardEntry:
    """某个座位在某一回合结束时的牌面（一条 library entry）。"""

    turn: int
    seat: int
    hero: int
    tier: int
    health: int
    board: List[Dict[str, Any]]   # [{card(str), atk, hp, golden, kw:[names]}]
    hand: int = 0                 # 手牌张数（暂不还原内容）
    placement: int = 0            # 该局最终名次（1=冠军；0=未知）

    @property
    def strength(self) -> int:
        return sum(int(m["atk"]) + int(m["hp"]) for m in self.board)

    def to_json(self) -> Dict[str, Any]:
        return {"turn": self.turn, "seat": self.seat, "hero": self.hero,
                "tier": self.tier, "health": self.health, "board": self.board,
                "hand": self.hand, "placement": self.placement,
                "strength": self.strength}


def _card_str(engine: Any, cid: int) -> str:
    return str(engine.card_info(int(cid))[0])


def capture_turn(engine: Any, game: Any, state: Optional[Dict[str, Any]] = None,
                 placement_by_seat: Optional[Dict[int, int]] = None
                 ) -> List[BoardEntry]:
    """在「招募结束」时刻抽 8 条 entry（用一次 state_json）。"""
    st = state if state is not None else json.loads(game.state_json())
    turn = int(st.get("turn", 0))
    out: List[BoardEntry] = []
    for idx, p in enumerate(st.get("players", [])):
        if not p.get("alive", True):
            continue
        board = []
        for m in p.get("board", []):
            cid = int(m["card"])
            try:
                card = _card_str(engine, cid)
            except Exception:  # noqa: BLE001 - 未知卡（不应发生）跳过
                continue
            board.append({"card": card, "atk": int(m["atk"]), "hp": int(m["hp"]),
                          "golden": bool(m.get("golden", False)),
                          "kw": kw_names(int(m.get("kw", 0)))})
        out.append(BoardEntry(
            turn=turn, seat=int(idx), hero=int(p.get("hero", 0)),
            tier=int(p.get("tier", 1)), health=int(p.get("health", 0)),
            board=board, hand=len(p.get("hand", [])),
            placement=int((placement_by_seat or {}).get(int(idx), 0))))
    return out


class BoardLibrary:
    """按 (turn, 强度档) 索引的牌面库。"""

    def __init__(self, entries: Optional[Iterable[BoardEntry]] = None,
                 bucket: int = 8) -> None:
        self.entries: List[BoardEntry] = list(entries or [])
        self.bucket = max(1, int(bucket))

    # -- 构建 ---------------------------------------------------------------
    def add(self, entries: Iterable[BoardEntry]) -> None:
        self.entries.extend(entries)

    def add_game(self, entries: Sequence[BoardEntry], placement_by_seat: Dict[int, int]
                 ) -> None:
        for e in entries:
            e.placement = int(placement_by_seat.get(e.seat, 0))
        self.add(entries)

    def filter_champions(self, keep_placements: Sequence[int] = (1,)) -> "BoardLibrary":
        keep = {int(x) for x in keep_placements}
        return BoardLibrary([e for e in self.entries if e.placement in keep],
                            bucket=self.bucket)

    # -- 抽样 ---------------------------------------------------------------
    def _bucket_of(self, strength: int) -> int:
        return int(strength) // self.bucket

    def index(self) -> Dict[tuple, List[int]]:
        idx: Dict[tuple, List[int]] = {}
        for i, e in enumerate(self.entries):
            idx.setdefault((e.turn, self._bucket_of(e.strength)), []).append(i)
        return idx

    def sample(self, turn: int, rng: random.Random, target_strength: Optional[int] = None,
               fallback_turn_window: int = 1) -> Optional[BoardEntry]:
        """按目标强度抽一条；没有精确匹配时放宽到相邻回合 / 相邻强度档。"""
        if not self.entries:
            return None
        def _collect(t_lo: int, t_hi: int, s_lo: int, s_hi: int) -> List[int]:
            out = []
            for i, e in enumerate(self.entries):
                if t_lo <= e.turn <= t_hi and s_lo <= e.strength <= s_hi:
                    out.append(i)
            return out
        b = self._bucket_of(int(target_strength)) if target_strength is not None else None
        for window in range(0, int(fallback_turn_window) + 1):
            for sb in (0, 1, 2) if b is not None else (0,):
                if b is None:
                    cand = _collect(turn - window, turn + window, -10 ** 9, 10 ** 9)
                else:
                    lo = (b - sb) * self.bucket
                    hi = (b + sb + 1) * self.bucket - 1
                    cand = _collect(turn - window, turn + window, lo, hi)
                if cand:
                    return self.entries[cand[rng.randrange(len(cand))]]
        return self.entries[rng.randrange(len(self.entries))]

    # -- 存取 ---------------------------------------------------------------
    def save(self, path: str) -> str:
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")
        return path

    @classmethod
    def load(cls, path: str, bucket: int = 8) -> "BoardLibrary":
        lib = cls(bucket=bucket)
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                lib.entries.append(BoardEntry(
                    turn=int(d["turn"]), seat=int(d["seat"]), hero=int(d["hero"]),
                    tier=int(d["tier"]), health=int(d["health"]),
                    board=list(d["board"]), hand=int(d.get("hand", 0)),
                    placement=int(d.get("placement", 0))))
        return lib

    def stats(self) -> Dict[str, Any]:
        per_turn: Dict[int, int] = {}
        strengths = []
        for e in self.entries:
            per_turn[e.turn] = per_turn.get(e.turn, 0) + 1
            strengths.append(e.strength)
        strengths.sort()
        return {"n": len(self.entries), "bucket": self.bucket,
                "turns": dict(sorted(per_turn.items())),
                "strength_p50": strengths[len(strengths) // 2] if strengths else 0,
                "strength_p90": strengths[int(len(strengths) * 0.9)] if strengths else 0}


# ---------------------------------------------------------------------------
# 注入
# ---------------------------------------------------------------------------
def inject_board(game: Any, seat: int, entry: BoardEntry) -> int:
    """把 entry 的牌面写入 seat（清空 board 后逐张 add_minion + edit_minion）。

    返回注入的随从数。要求 game 是 ``hsbg_engine.Game``（debug 命令可用）。
    """
    game.debug(json.dumps({"cmd": "clear_zone", "p": int(seat), "zone": "board"}))
    game.debug(json.dumps({"cmd": "set_player", "p": int(seat),
                           "health": int(entry.health), "tier": int(entry.tier)}))
    n = 0
    for i, m in enumerate(entry.board):
        cid = str(m["card"])
        # 引擎的 golden 命名带 `_G` 后缀；add_minion 会再套一次 golden 变换，必须先剥掉
        base = cid[:-2] if cid.endswith("_G") else cid
        game.debug(json.dumps({
            "cmd": "add_minion", "p": int(seat), "zone": "board",
            "card": base, "pos": i,
            "golden": bool(m.get("golden", False)),
            "atk": int(m["atk"]), "hp": int(m["hp"])}))
        names = list(m.get("kw") or [])
        if names:
            game.debug(json.dumps({
                "cmd": "edit_minion", "p": int(seat), "zone": "board", "index": i,
                "keywords": names,
                "atk": int(m["atk"]), "hp": int(m["hp"]),
                "golden": bool(m.get("golden", False))}))
        n += 1
    return n


def base_card(card: str) -> str:
    """把 golden 变体 id 归一成注入用的基础 id（剥掉 `_G`；`...t_G` 亦剥）。"""
    c = str(card)
    for suf in ("_G", "t_G"):
        if c.endswith(suf):
            return c[: -len(suf)]
    return c


def board_signature(state_player: Dict[str, Any]) -> List[tuple]:
    """(card, atk, hp, golden, kw) 元组列表，用于注入前后对拍。"""
    return [(int(m["card"]), int(m["atk"]), int(m["hp"]), bool(m.get("golden", False)),
             int(m.get("kw", 0))) for m in state_player.get("board", [])]


__all__ = ["BoardEntry", "BoardLibrary", "capture_turn", "inject_board",
           "board_signature", "base_card", "kw_names", "KW_NAMES"]
