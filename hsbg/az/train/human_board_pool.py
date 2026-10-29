"""人类战团（board-only）注入库：把 10k+ MMR 观测里的**战团**注入某个 bot 座位。

设计：``docs/HUMAN_BOARD_OPPONENT.md``。本模块只依赖 ``hsbg_engine``（不需要 torch），
因此采集/注入/冒烟都能在没有 GPU 的机器上跑。

**数据来源**：``data/real_library/library_real_degraded.jsonl``（4,284 行真实 10k+ MMR
观测帧，字段 ``turn / strength / board:[{card, atk, hp, position}] / hero / game_id ...``）。
每行是某个座位在 **recruit 阶段末（combat 之前）** 的战团。

**近似边界（必须如实标注）**：真实观测**没有**共享池差量、也没有完整的 hidden counters，
所以本库只做 ``source=human_board_approx`` 的 **board-only 近似**：

- 只取 ``board``（按 ``position`` 排序）→ ``[[card, atk, hp], ...]``；
- 不还原 hand / shop / gold / 池占用 / 英雄技能计数；引擎侧注入时新随从 ``pool_copies=0``
  （不占共享池），旧 board 的持有量归还共享池；
- 因此**不能**声称这是忠实的对手状态，只能当作「该回合强度分位的战团模板」。

**分桶与采样**：按 ``turn`` 分桶，桶内按 ``strength = Σ(atk+hp)`` 升序取**最近秩分位**
（``p50`` / ``p75`` / ``p90`` / ``max``），与 ``MirrorSnapshotPool`` 完全同一套算法；
同强度的多条用 ``rng`` 随机抽（避免总取上限）。默认 ``sample="auto"`` 走**难度曲线**：
``turn<=8 → p50``、``9..12 → p75``、``>=13 → p90``（见 :func:`sample_mode_for_turn`）。

**过滤**（保守，宁可少用也不把脏帧带进对局）：空战团、``len(board)>7``、非整数卡、
``atk<0`` / ``hp<=0``、单随从 ``atk+hp > 100_000``、战团 ``Σ(atk+hp) > 250_000``、
卡表里不是 minion 的卡。后两条针对观测里的**极端离群值**（例如单个随从 128,981/128,920）：
它们几乎肯定不是合法战团数值，会把难度曲线拉爆。
"""

from __future__ import annotations

import bisect
import json
import math
import os
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 注入来源标记：写进采集 meta / 文档，明确「这不是忠实对手状态」。
SOURCE = "human_board_approx"

#: 桶内分位（与 ``mirror_snapshots.SAMPLE_PERCENTILES`` 一致）。
SAMPLE_PERCENTILES = {"p50": 0.50, "p75": 0.75, "p90": 0.90}
#: ``auto`` = 按回合走难度曲线；其余为固定分位。
SAMPLE_MODES = ("auto", "p50", "p75", "p90", "max")

#: 难度曲线（turn 上界 -> 分位）：t<=8 p50、9..12 p75、t>=13 p90。
TURN_SCHEDULE: Tuple[Tuple[Optional[int], str], ...] = ((8, "p50"), (12, "p75"), (None, "p90"))

#: 引擎棋盘上限（与 ``RulesConfig::board_size`` 默认值一致）。
MAX_BOARD = 7
#: 单随从 ``atk+hp`` 上限：超过即视为观测离群值（脏帧），丢掉整行。
MAX_MINION_STAT = 100_000
#: 战团总强度上限：同上。
MAX_BOARD_STRENGTH = 250_000

#: 回合 -> 派生的酒馆等级（人类数据里**没有** tier 字段，这里按 BG 常规升级节奏近似）。
#: 上限 6：tier 7 需要 Norgannon 奖励（``Player::tier7``），不在这里凭空解锁。
TURN_TIER: Dict[int, int] = {
    1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 5, 8: 5, 9: 6, 10: 6,
}


# ────────────────────────── 分位 / 难度曲线 ──────────────────────────


def sample_mode_for_turn(turn: int) -> str:
    """难度曲线：``turn<=8 -> p50``、``9..12 -> p75``、``>=13 -> p90``。

    理由见文档：校准显示 t10 之后我们的快照库 p50 只有真实值的 1/2.8、t15 只有 1/25，
    早期（t<=8）我们的库并不弱（p50 比值 0.4–1.4），所以早期用中位、后期逐档加难。
    """
    t = int(turn)
    for bound, mode in TURN_SCHEDULE:
        if bound is None or t <= int(bound):
            return str(mode)
    return "p90"


def turn_tier(turn: int) -> int:
    """按回合近似酒馆等级（人类数据没有 tier 字段；上限 6）。"""
    t = int(turn)
    if t in TURN_TIER:
        return TURN_TIER[t]
    return 6


def _percentile_index(q: float, n: int) -> int:
    """最近秩分位下标（与 ``MirrorSnapshotPool.get`` 同一公式）。"""
    if n <= 1:
        return 0
    return min(n - 1, max(0, int(math.floor(float(q) * (n - 1) + 0.5))))


# ────────────────────────── 卡表校验（可选） ──────────────────────────

_MINION_CIDS: Optional[set] = None


def minion_cids() -> Optional[set]:
    """卡表里 ``kind == minion`` 的 cid 集合；引擎不可用时返回 ``None``（跳过该过滤）。"""
    global _MINION_CIDS
    if _MINION_CIDS is not None:
        return _MINION_CIDS
    try:
        import hsbg_engine as E

        out = set()
        for row in json.loads(E.catalog_json()):
            cid = row.get("cid")
            if cid is None:
                continue
            if str(row.get("kind", "")).strip().lower() == "minion":
                out.add(int(cid))
        _MINION_CIDS = out
    except BaseException:  # noqa: BLE001 - 无引擎时退化为「不做卡表过滤」
        _MINION_CIDS = None
    return _MINION_CIDS


# ────────────────────────── 数据模型 ──────────────────────────


@dataclass
class HumanBoard:
    """一条可注入的人类战团：``board`` 为按位置的 ``[(card, atk, hp), ...]``。"""

    turn: int
    strength: int
    board: List[List[int]] = field(default_factory=list)
    game_id: str = ""
    hero: Optional[int] = None

    def to_json(self) -> Dict[str, Any]:
        return {"turn": int(self.turn), "strength": int(self.strength),
                "board": [list(m) for m in self.board],
                "game_id": str(self.game_id), "hero": self.hero,
                "source": SOURCE}


class HumanBoardPool:
    """按 ``turn`` 分桶的人类战团池（JSONL 读取 + 分位采样）。"""

    def __init__(self, path: Optional[str] = None, *, sample: str = "auto",
                 max_board: int = MAX_BOARD,
                 max_minion_stat: int = MAX_MINION_STAT,
                 max_board_strength: int = MAX_BOARD_STRENGTH,
                 check_cards: bool = True):
        self.path = str(path) if path else ""
        #: ``turn -> [HumanBoard]``（载入顺序，采样时按 strength 排序）
        self.index: Dict[int, List[HumanBoard]] = {}
        self.sample_mode = str(sample or "auto").strip().lower()
        if self.sample_mode not in SAMPLE_MODES:
            self.sample_mode = "auto"
        self.max_board = int(max_board)
        self.max_minion_stat = int(max_minion_stat)
        self.max_board_strength = int(max_board_strength)
        self.check_cards = bool(check_cards)
        self.rows = 0
        self.kept = 0
        self.bad_lines = 0
        #: 过滤计数：``{"empty_board": 4, "board_over_7": 12, ...}``
        self.filtered: Dict[str, int] = {}
        self.nearest_fallbacks = 0
        #: 每个 turn 桶按 strength 升序的缓存（采样热路径：每回合每座位一次调用，
        #: 桶有几百条时不能每次重排）。
        self._sorted: Dict[int, List[HumanBoard]] = {}
        if self.path:
            self.load(self.path)

    # ---- 读取 ----
    def _drop(self, reason: str) -> None:
        self.filtered[reason] = self.filtered.get(reason, 0) + 1

    def load(self, path: str) -> int:
        """读取 JSONL（增量载入；返回本次新增的可用战团数）。"""
        self.path = str(path)
        added = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                self.rows += 1
                try:
                    row = json.loads(line)
                except BaseException:  # noqa: BLE001
                    self.bad_lines += 1
                    continue
                hb = self._row_to_board(row)
                if hb is None:
                    continue
                self.index.setdefault(int(hb.turn), []).append(hb)
                self._sorted.pop(int(hb.turn), None)   # 桶内容变了，缓存失效
                added += 1
        self.kept += added
        return added

    def _row_to_board(self, row: Dict[str, Any]) -> Optional[HumanBoard]:
        """单行 -> :class:`HumanBoard`（不合法返回 None 并计数）。"""
        try:
            turn = int(row.get("turn", 0))
        except BaseException:  # noqa: BLE001
            self._drop("bad_turn")
            return None
        if turn <= 0:
            self._drop("bad_turn")
            return None
        raw = row.get("board")
        if not isinstance(raw, list):
            self._drop("bad_board")
            return None
        if not raw:
            self._drop("empty_board")
            return None
        if len(raw) > self.max_board:
            self._drop("board_over_7")
            return None
        entries: List[Tuple[int, int, int, int]] = []
        for i, m in enumerate(raw):
            if not isinstance(m, dict):
                self._drop("bad_entry")
                return None
            try:
                card = int(m["card"])
                atk = int(m["atk"])
                hp = int(m["hp"])
            except (KeyError, TypeError, ValueError):
                self._drop("bad_entry")
                return None
            if card <= 0 or atk < 0 or hp <= 0:
                self._drop("bad_stats")
                return None
            if atk + hp > self.max_minion_stat:
                self._drop("stat_outlier")
                return None
            pos = m.get("position", i + 1)
            try:
                pos = int(pos)
            except (TypeError, ValueError):
                pos = i + 1
            entries.append((pos, card, atk, hp))
        strength = sum(e[2] + e[3] for e in entries)
        if strength > self.max_board_strength:
            self._drop("strength_outlier")
            return None
        try:
            claimed = int(row["strength"]) if row.get("strength") is not None else strength
        except (TypeError, ValueError):
            claimed = strength
        if claimed != strength:
            # 观测里的 strength 与 Σ(atk+hp) 不一致：以实际战团为准（仅打点）。
            self._drop("strength_mismatch")
        mc = minion_cids() if self.check_cards else None
        if mc is not None and any(int(e[1]) not in mc for e in entries):
            self._drop("not_minion")
            return None
        # position 升序（同 position/缺失时保持原顺序）；输出 [[card, atk, hp], ...]。
        entries.sort(key=lambda e: (e[0],))
        return HumanBoard(turn=turn, strength=strength,
                          board=[[int(c), int(a), int(h)] for (_p, c, a, h) in entries],
                          game_id=str(row.get("game_id", "")),
                          hero=(int(row["hero"]) if row.get("hero") is not None else None))

    # ---- 采样 ----
    def has(self, turn: int) -> bool:
        return bool(self.index.get(int(turn)))

    def turns(self) -> List[int]:
        return sorted(self.index)

    def _bucket(self, turn: int) -> Optional[Tuple[int, List[HumanBoard]]]:
        """取桶 ``(bucket_turn, boards)``；该回合没有数据时退化为**最近回合**（夹到端点）。"""
        t = int(turn)
        cands = self.index.get(t)
        if cands:
            return t, cands
        turns = self.turns()
        if not turns:
            return None
        if t < turns[0]:
            near = turns[0]
        elif t > turns[-1]:
            near = turns[-1]
        else:
            near = min(turns, key=lambda x: (abs(x - t), x))
        self.nearest_fallbacks += 1
        return near, self.index.get(near) or []

    def _sorted_bucket(self, bucket_turn: int,
                       cands: List[HumanBoard]) -> Tuple[List[HumanBoard], List[int]]:
        """按 strength 升序的桶 + 对应的 strength 数组（缓存；``load`` 时失效）。"""
        key = int(bucket_turn)
        out = self._sorted.get(key)
        if out is None or len(out[0]) != len(cands):
            ordered = sorted(cands, key=lambda b: b.strength)
            out = (ordered, [b.strength for b in ordered])
            self._sorted[key] = out
        return out

    def sample(self, turn: int, rng: Optional[random.Random] = None,
               mode: Optional[str] = None) -> Optional[List[List[int]]]:
        """取 ``turn`` 桶内按 ``mode`` 分位的一条战团（``None`` = 该回合完全没数据）。

        ``mode=None`` 用池的 ``sample_mode``；``"auto"`` 走 :func:`sample_mode_for_turn`。
        分位算法与 ``MirrorSnapshotPool.get`` 一致：按 strength 升序的最近秩，同强度随机抽。
        热路径 O(log n)：每回合每座位一次调用，桶有几百条时不重排、不线性扫描。
        """
        hit = self._bucket(turn)
        if hit is None:
            return None
        bucket_turn, cands = hit
        if not cands:
            return None
        m = str(mode or self.sample_mode or "auto").strip().lower()
        if m == "auto":
            m = sample_mode_for_turn(turn)
        r = rng or random
        if m == "max":
            ordered, _ = self._sorted_bucket(bucket_turn, cands)
            return [list(x) for x in ordered[-1].board]
        q = SAMPLE_PERCENTILES.get(m)
        if q is None:
            # 未知模式退化为均匀随机（与 mirror 一致）。
            return [list(x) for x in cands[r.randrange(len(cands))].board]
        ordered, strengths = self._sorted_bucket(bucket_turn, cands)
        target = strengths[_percentile_index(q, len(strengths))]
        lo = bisect.bisect_left(strengths, target)
        hi = bisect.bisect_right(strengths, target)
        pick = ordered[lo + r.randrange(max(1, hi - lo))]
        return [list(x) for x in pick.board]

    # ---- 统计 ----
    def stats(self) -> Dict[str, Any]:
        """池的结构化摘要（日志 / meta / 文档数字核对用）。"""
        turns = self.turns()
        per_turn: Dict[int, Dict[str, Any]] = {}
        for t in turns:
            vals = sorted(b.strength for b in self.index[t])
            n = len(vals)

            def _p(q: float, _v: List[int] = vals) -> int:
                return int(_v[_percentile_index(q, len(_v))])

            per_turn[int(t)] = {"n": n, "p50": _p(0.5), "p75": _p(0.75),
                                "p90": _p(0.9), "max": int(vals[-1])}
        return {
            "path": self.path,
            "source": SOURCE,
            "sample": self.sample_mode,
            "rows": int(self.rows),
            "kept": int(self.kept),
            "bad_lines": int(self.bad_lines),
            "filtered": {str(k): int(v) for k, v in sorted(self.filtered.items())},
            "turns": [int(t) for t in turns],
            "turn_min": (turns[0] if turns else 0),
            "turn_max": (turns[-1] if turns else 0),
            "boards": int(sum(len(v) for v in self.index.values())),
            "per_turn": per_turn,
            "schedule": {str(b): m for b, m in TURN_SCHEDULE},
            "max_minion_stat": int(self.max_minion_stat),
            "max_board_strength": int(self.max_board_strength),
        }


def load_pool(path: Optional[str], *, sample: str = "auto",
              **kw: Any) -> Optional[HumanBoardPool]:
    """便捷入口：``path`` 为空 / 不存在 / 文件为空时返回 ``None``（调用方退回纯 bot）。"""
    if not path:
        return None
    if not os.path.isfile(str(path)):
        return None
    pool = HumanBoardPool(str(path), sample=sample, **kw)
    return pool if pool.kept else None


# ────────────────────────── 训练侧注入驱动 ──────────────────────────


@dataclass
class HumanBoardStats:
    """一次/多局人类战团注入的计数（写进采集 meta）。"""

    attempt: int = 0            # 概率命中并尝试注入的座位数
    applied: int = 0            # 引擎成功替换的座位数
    rejected: int = 0           # 引擎拒绝的座位数（fail-closed，状态未变）
    missing: int = 0            # 该回合没有任何可用战团
    skipped_by_mirror: int = 0  # 同座位同回合已被镜像快照占用（优先级：镜像 > 人类）
    errors: int = 0             # Python 侧异常（引擎/数据问题）
    pool_unbalanced: int = 0    # 注入后 pool_balance 不守恒的次数（应为 0）
    nearest_bucket: int = 0     # 采样退化为最近回合的次数（回合超出数据范围）
    tier_set: int = 0           # 同时写入派生 tier 的次数
    last_rejected: List[List[Any]] = field(default_factory=list)
    rejected_by_reason: Dict[str, int] = field(default_factory=dict)

    def add(self, other: "HumanBoardStats") -> None:
        self.attempt += other.attempt
        self.applied += other.applied
        self.rejected += other.rejected
        self.missing += other.missing
        self.skipped_by_mirror += other.skipped_by_mirror
        self.errors += other.errors
        self.pool_unbalanced += other.pool_unbalanced
        self.nearest_bucket += other.nearest_bucket
        self.tier_set += other.tier_set
        for k, v in other.rejected_by_reason.items():
            self.rejected_by_reason[k] = self.rejected_by_reason.get(k, 0) + int(v)
        for r in other.last_rejected[:4]:
            if len(self.last_rejected) < 16:
                self.last_rejected.append(list(r))

    def to_meta(self) -> Dict[str, Any]:
        return {
            "human_board_source": SOURCE,
            "human_board_attempt": int(self.attempt),
            "human_board_applied": int(self.applied),
            "human_board_rejected": int(self.rejected),
            "human_board_missing": int(self.missing),
            "human_board_skipped_by_mirror": int(self.skipped_by_mirror),
            "human_board_errors": int(self.errors),
            "human_board_pool_unbalanced": int(self.pool_unbalanced),
            "human_board_nearest_bucket": int(self.nearest_bucket),
            "human_board_tier_set": int(self.tier_set),
            "human_board_last_rejected": [list(x) for x in self.last_rejected],
            "human_board_rejected_by_reason": {
                str(k): int(v) for k, v in sorted(self.rejected_by_reason.items())},
        }


def _reject_class(reason: Any) -> str:
    """引擎拒绝原因归类（``"pending_choice(1)"`` -> ``"pending_choice"``）。"""
    txt = str(reason or "").strip()
    for sep in ("(", ":"):
        if sep in txt:
            txt = txt.split(sep, 1)[0]
    return txt.strip() or "unknown"


def random_seats(count: int, rng: Optional[random.Random] = None,
                 num_players: int = 8, learner_seat: int = 0) -> List[int]:
    """从全部非 learner 座位里不放回随机抽 ``count`` 个（升序；``count`` 超出则取全部）。"""
    pool = [s for s in range(int(num_players)) if s != int(learner_seat)]
    k = max(0, min(int(count), len(pool)))
    if k <= 0:
        return []
    r = rng or random
    return sorted(r.sample(pool, k))


def inject_turn(game: Any, pool: HumanBoardPool, turn: int, *,
                seats_count: int = 2, p: float = 1.0,
                rng: Optional[random.Random] = None, learner_seat: int = 0,
                stats: Optional[HumanBoardStats] = None,
                mirror_seats: Sequence[int] = (),
                num_players: int = 8,
                set_tier: bool = True,
                tier_fn: Optional[Any] = None,
                seats: Optional[Sequence[int]] = None) -> HumanBoardStats:
    """新回合开始（任何座位行动前）给随机 N 个非 learner 座位注入人类战团。

    - 座位：``seats`` 给定时用它（固定座位，便于复现）；否则用 :func:`random_seats`
      从全部非 learner 座位随机抽 ``seats_count`` 个；
    - 每个座位独立掷 ``p``；命中后 ``attempt += 1``；缺数据 -> ``missing``；
    - **优先级**：``mirror_seats`` 里的座位本回合已被镜像快照占用（引擎里
      ``ended_turn=true``），直接跳过并记 ``skipped_by_mirror``；
    - 引擎侧每个座位一次 ``Game.inject_board`` 调用（board-only，事务性）；
      拒绝只记 ``rejected``，该座位保持原状态；
    - ``set_tier``：是否同时写入 :func:`turn_tier` 派生 tier（默认 True）；``tier_fn``
      可覆盖派生函数。
    """
    st = stats if stats is not None else HumanBoardStats()
    r = rng or random
    prob = max(0.0, min(1.0, float(p)))
    mirror_set = {int(s) for s in mirror_seats}
    seat_list = ([int(s) for s in seats] if seats is not None
                 else random_seats(int(seats_count), r, num_players, learner_seat))
    tier_of = tier_fn or turn_tier
    for seat in seat_list:
        seat = int(seat)
        if seat == int(learner_seat):
            continue
        if seat in mirror_set:
            st.skipped_by_mirror += 1
            continue
        if prob < 1.0 and r.random() >= prob:
            continue
        st.attempt += 1
        before_fallback = int(getattr(pool, "nearest_fallbacks", 0))
        try:
            board = pool.sample(int(turn), rng=r)
        except BaseException:  # noqa: BLE001 - 数据问题 -> 该座位保持 bot
            st.errors += 1
            st.last_rejected.append([-1, "sample_error"])
            continue
        if int(getattr(pool, "nearest_fallbacks", 0)) > before_fallback:
            st.nearest_bucket += 1
        if not board:
            st.missing += 1
            continue
        tier = int(tier_of(int(turn))) if set_tier else None
        if tier is not None and not (1 <= tier <= 7):
            tier = None
        try:
            rep = game.inject_board(seat, board, tier)
        except BaseException as exc:  # noqa: BLE001 - 引擎异常 -> 该座位保持 bot
            st.errors += 1
            st.last_rejected.append([seat, repr(exc)[:200]])
            continue
        if bool(rep.get("applied")):
            st.applied += 1
            if tier is not None:
                st.tier_set += 1
            if not bool(rep.get("pool_balance_ok", True)):
                st.pool_unbalanced += 1
        else:
            st.rejected += 1
            cls = _reject_class(rep.get("reason"))
            st.rejected_by_reason[cls] = st.rejected_by_reason.get(cls, 0) + 1
            if len(st.last_rejected) < 16:
                st.last_rejected.append([seat, str(rep.get("reason"))[:200]])
    return st


__all__ = [
    "MAX_BOARD", "MAX_BOARD_STRENGTH", "MAX_MINION_STAT", "SAMPLE_MODES",
    "SAMPLE_PERCENTILES", "SOURCE", "TURN_SCHEDULE", "TURN_TIER",
    "HumanBoard", "HumanBoardPool", "HumanBoardStats", "inject_turn",
    "load_pool", "minion_cids", "random_seats", "sample_mode_for_turn",
    "turn_tier",
]
