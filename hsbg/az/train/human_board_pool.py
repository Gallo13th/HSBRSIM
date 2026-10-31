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

**保真度（2026-10-31 新增，默认 ``board`` 逐位不变）**：``inject_turn`` /
:func:`inject_all` 新增 ``fidelity ∈ {board, hand, full}``。``board`` 走原
``Game.inject_board``（board-only，逐位等价旧行为）；``hand`` / ``full`` 走
:func:`hsbg.az.train.human_obs_full.inject_quasi_state`
（→ ``Game.apply_turn_snapshots``，Python 侧封装，Rust 零改动），把**手牌 / 可推断
counters（关键词位、金身、圣盾层数、tavern tier）**一起注入。这需要**准完整库**
``data/real_library/library_real_quasi_full.jsonl``（``scripts/build_fidelity_library.py``
生成）；旧 board-only 库在 hand/full 档会退化为 board-only 并计 ``payload_missing``。
见 ``docs/FIDELITY_INJECTION.md``。

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


def _opt_int(value: Any) -> Optional[int]:
    """``None`` / 非法值 -> ``None``；否则 ``int``（payload 透传，不做语义校验）。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    #: 准完整 payload（``hand`` / ``counters`` / ``tier`` / ``availability``）；
    #: 旧 board-only 库为 ``None``（hand/full 档会退化为 board-only）。
    payload: Optional[Dict[str, Any]] = None
    #: 手牌数量（payload 缺失时为 0）与观测到的 tavern tier。
    hand_n: int = 0
    tier: Optional[int] = None

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
        #: 带准完整 payload（``board_detail``）的行数；hand/full 档必须 > 0。
        self.payload_kept = 0
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
                if isinstance(hb.payload, dict):
                    self.payload_kept += 1
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
            # 兼容两种行格式：``{"card","atk","hp","position"}``（旧库）与
            # ``[card, atk, hp]``（``library_real_quasi_full.jsonl`` 的扁平板）。
            if isinstance(m, dict):
                try:
                    card = int(m["card"])
                    atk = int(m["atk"])
                    hp = int(m["hp"])
                except (KeyError, TypeError, ValueError):
                    self._drop("bad_entry")
                    return None
                pos = m.get("position", i + 1)
            elif isinstance(m, (list, tuple)) and len(m) >= 3:
                try:
                    card, atk, hp = int(m[0]), int(m[1]), int(m[2])
                except (TypeError, ValueError):
                    self._drop("bad_entry")
                    return None
                pos = m[3] if len(m) > 3 else i + 1
            else:
                self._drop("bad_entry")
                return None
            if card <= 0 or atk < 0 or hp <= 0:
                self._drop("bad_stats")
                return None
            if atk + hp > self.max_minion_stat:
                self._drop("stat_outlier")
                return None
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
        flat = [[int(c), int(a), int(h)] for (_p, c, a, h) in entries]
        payload = self._row_to_payload(row, turn, flat)
        return HumanBoard(turn=turn, strength=strength, board=flat,
                          game_id=str(row.get("game_id", "")),
                          hero=(int(row["hero"]) if row.get("hero") is not None else None),
                          payload=payload,
                          hand_n=(len(payload.get("hand") or []) if payload else 0),
                          tier=(payload.get("tier") if payload else None))

    def _row_to_payload(self, row: Dict[str, Any], turn: int,
                        flat: List[List[int]]) -> Optional[Dict[str, Any]]:
        """准完整库行 -> payload（``board_detail`` 存在时）；旧库返回 ``None``。

        payload 键：``board / board_flat / hand / hand_available / tier /
        gold / hero_hp / main_placement / availability / source``。

        ``gold`` / ``hero_hp`` / ``main_placement`` **有字段才带值**：
        10k+ 准完整库没有这三个字段 -> ``None``（与旧的 ``"gold": None`` 逐位一致）；
        Firestone 近期库带齐 -> full 档注入时 gold 会一起写回目标座位。
        """
        detail = row.get("board_detail")
        if not isinstance(detail, list) or len(detail) != len(flat):
            return None
        board: List[Dict[str, Any]] = []
        for i, (m, f) in enumerate(zip(detail, flat)):
            if not isinstance(m, dict):
                return None
            try:
                board.append({
                    "card": int(m.get("card", f[0])),
                    "atk": int(m.get("atk", f[1])),
                    "hp": int(m.get("hp", f[2])),
                    "golden": bool(m.get("golden")),
                    "kw": int(m.get("kw") or 0),
                    "bonus_kw": int(m.get("bonus_kw") or 0),
                    "shield_max": int(m.get("shield_max") or 1),
                    "position": i + 1,
                })
            except (TypeError, ValueError):
                return None
        hand = row.get("hand")
        hand = [dict(x) for x in hand] if isinstance(hand, list) else []
        try:
            tier = int(row["tier"]) if row.get("tier") is not None else None
        except (TypeError, ValueError):
            tier = None
        av = row.get("availability")
        return {
            "schema": row.get("schema") or "hsbg.human_state_quasi_full",
            "schema_version": int(row.get("schema_version") or 1),
            "turn": int(turn),
            "board": board,
            "board_flat": [list(x) for x in flat],
            "hand": hand,
            "hand_available": bool(row.get("hand_available")),
            "tier": tier,
            # 以下三字段**有字段才带值**：准完整 10k+ 库没有 gold / hero_hp /
            # main_placement，取到 None 时与旧行为逐位一致；Firestone 库带齐时
            # full 档会把 gold 一起写回（`human_obs_full.inject_quasi_state`）。
            "gold": _opt_int(row.get("gold")),
            "hero_hp": _opt_int(row.get("hero_hp")),
            "main_placement": _opt_int(row.get("main_placement")),
            "availability": dict(av) if isinstance(av, dict) else {},
            "source": str(row.get("source") or SOURCE),
        }

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

    def _pick(self, turn: int, rng: Optional[random.Random],
              mode: Optional[str]) -> Optional[HumanBoard]:
        """分位采样选中的那一条 :class:`HumanBoard`（**唯一**的 RNG 消费点）。

        ``sample`` / ``sample_payload`` 都只调用它一次，因此 board 与 hand/full
        两档消耗的 RNG 序列**完全相同**（换档不改变座位/难度分布）。
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
            return ordered[-1]
        q = SAMPLE_PERCENTILES.get(m)
        if q is None:
            # 未知模式退化为均匀随机（与 mirror 一致）。
            return cands[r.randrange(len(cands))]
        ordered, strengths = self._sorted_bucket(bucket_turn, cands)
        target = strengths[_percentile_index(q, len(strengths))]
        lo = bisect.bisect_left(strengths, target)
        hi = bisect.bisect_right(strengths, target)
        return ordered[lo + r.randrange(max(1, hi - lo))]

    def sample(self, turn: int, rng: Optional[random.Random] = None,
               mode: Optional[str] = None) -> Optional[List[List[int]]]:
        """取 ``turn`` 桶内按 ``mode`` 分位的一条战团（``None`` = 该回合完全没数据）。

        ``mode=None`` 用池的 ``sample_mode``；``"auto"`` 走 :func:`sample_mode_for_turn`。
        分位算法与 ``MirrorSnapshotPool.get`` 一致：按 strength 升序的最近秩，同强度随机抽。
        热路径 O(log n)：每回合每座位一次调用，桶有几百条时不重排、不线性扫描。
        """
        pick = self._pick(turn, rng, mode)
        return None if pick is None else [list(x) for x in pick.board]

    def sample_payload(self, turn: int, rng: Optional[random.Random] = None,
                       mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """同 :meth:`sample` 的分位选择，但返回**准完整 payload**（旧库返回 ``None``）。"""
        pick = self._pick(turn, rng, mode)
        if pick is None:
            return None
        if not isinstance(pick.payload, dict):
            # 旧 board-only 库：返回 has_detail=False，调用方退化到 inject_board
            # （单次 RNG 抽取不变，因此换档不改变座位/难度分布）。
            return {"turn": int(turn), "board": [], "board_flat": [list(x) for x in pick.board],
                    "hand": [], "hand_available": False, "tier": pick.tier, "gold": None,
                    "availability": {}, "has_detail": False,
                    "source": SOURCE}
        out = dict(pick.payload)
        out["has_detail"] = True
        out["board"] = [dict(b) for b in (pick.payload.get("board") or [])]
        out["board_flat"] = [list(x) for x in (pick.payload.get("board_flat")
                                              or pick.board)]
        out["hand"] = [dict(h) for h in (pick.payload.get("hand") or [])]
        out["availability"] = dict(pick.payload.get("availability") or {})
        return out

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
            "payload_rows": int(self.payload_kept),
            "fidelity_detail": ("quasi_full" if self.payload_kept else "board_only"),
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
    #: 保真度档位（``board`` / ``hand`` / ``full``）；board 档其余计数恒为 0。
    fidelity: str = "board"
    hand_applied: int = 0       # 成功注入手牌的座位数
    counters_applied: int = 0   # 成功注入可推断 counters 的座位数
    full_applied: int = 0       # 走 apply_turn_snapshots 成功的座位数
    payload_missing: int = 0    # hand/full 档但库行没有 payload -> 退化 board-only
    hand_unavailable: int = 0   # payload 里手牌不可得（对手视角 / 未揭示）
    counters_unavailable: int = 0
    unavailable_fields: Dict[str, int] = field(default_factory=dict)
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
        if other.fidelity != "board" or not self.fidelity:
            self.fidelity = other.fidelity
        self.hand_applied += int(other.hand_applied)
        self.counters_applied += int(other.counters_applied)
        self.full_applied += int(other.full_applied)
        self.payload_missing += int(other.payload_missing)
        self.hand_unavailable += int(other.hand_unavailable)
        self.counters_unavailable += int(other.counters_unavailable)
        for k, v in (other.unavailable_fields or {}).items():
            self.unavailable_fields[str(k)] = int(self.unavailable_fields.get(str(k), 0)) + int(v)
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
            # 保真度（board/hand/full）与逐字段可得性：history.jsonl 直接读这些键。
            "human_board_fidelity": str(self.fidelity or "board"),
            "human_board_hand_applied": int(self.hand_applied),
            "human_board_counters_applied": int(self.counters_applied),
            "human_board_full_applied": int(self.full_applied),
            "human_board_payload_missing": int(self.payload_missing),
            "human_board_hand_unavailable": int(self.hand_unavailable),
            "human_board_counters_unavailable": int(self.counters_unavailable),
            "human_board_unavailable_fields": {
                str(k): int(v) for k, v in sorted(self.unavailable_fields.items())},
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


#: 保真度档位（训练 ``--human-board-fidelity``）。
FIDELITIES = ("board", "hand", "full")


def inject_turn(game: Any, pool: HumanBoardPool, turn: int, *,
                seats_count: int = 2, p: float = 1.0,
                rng: Optional[random.Random] = None, learner_seat: int = 0,
                stats: Optional[HumanBoardStats] = None,
                mirror_seats: Sequence[int] = (),
                num_players: int = 8,
                set_tier: bool = True,
                tier_fn: Optional[Any] = None,
                seats: Optional[Sequence[int]] = None,
                fidelity: str = "board") -> HumanBoardStats:
    """新回合开始（任何座位行动前）给随机 N 个非 learner 座位注入人类战团。

    - 座位：``seats`` 给定时用它（固定座位，便于复现）；否则用 :func:`random_seats`
      从全部非 learner 座位随机抽 ``seats_count`` 个；
    - 每个座位独立掷 ``p``；命中后 ``attempt += 1``；缺数据 -> ``missing``；
    - **优先级**：``mirror_seats`` 里的座位本回合已被镜像快照占用（引擎里
      ``ended_turn=true``），直接跳过并记 ``skipped_by_mirror``；
    - ``fidelity="board"``（**默认**）：每个座位一次 ``Game.inject_board``（board-only，
      事务性），行为与旧版**逐位等价**（RNG / 状态 / meta 旧键都不变）；
    - ``fidelity="hand"`` / ``"full"``：走
      :func:`hsbg.az.train.human_obs_full.inject_quasi_state`
      （``Game.apply_turn_snapshots`` + ``ended_turn`` 复位），把手牌 / 可推断 counters
      一起注入；库行没有 payload 时退化 board-only 并记 ``payload_missing``；
    - 拒绝只记 ``rejected``，该座位保持原状态；
    - ``set_tier``：是否同时写入 :func:`turn_tier` 派生 tier（默认 True；full 档优先用
      观测到的 tavern tier）；``tier_fn`` 可覆盖派生函数。
    """
    st = stats if stats is not None else HumanBoardStats()
    fid = str(fidelity or "board").strip().lower()
    if fid not in FIDELITIES:
        fid = "board"
    st.fidelity = fid
    r = rng or random
    prob = max(0.0, min(1.0, float(p)))
    mirror_set = {int(s) for s in mirror_seats}
    seat_list = ([int(s) for s in seats] if seats is not None
                 else random_seats(int(seats_count), r, num_players, learner_seat))
    tier_of = tier_fn or turn_tier
    if fid != "board":
        from .human_obs_full import inject_quasi_state   # noqa: PLC0415
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
        payload: Optional[Dict[str, Any]] = None
        if fid == "board":
            try:
                board = pool.sample(int(turn), rng=r)
            except BaseException:  # noqa: BLE001 - 数据问题 -> 该座位保持 bot
                st.errors += 1
                st.last_rejected.append([-1, "sample_error"])
                continue
        else:
            try:
                payload = pool.sample_payload(int(turn), rng=r)
            except BaseException:  # noqa: BLE001
                st.errors += 1
                st.last_rejected.append([-1, "sample_error"])
                continue
            if payload is None:
                st.missing += 1
                continue
            board = payload.get("board_flat") or []
            if not payload.get("has_detail", False):
                st.payload_missing += 1
        if int(getattr(pool, "nearest_fallbacks", 0)) > before_fallback:
            st.nearest_bucket += 1
        if not board:
            st.missing += 1
            continue
        tier = int(tier_of(int(turn))) if set_tier else None
        if tier is not None and not (1 <= tier <= 7):
            tier = None
        # ---- hand / full：准完整注入（Python 侧封装，失败退化不改状态） ----
        if fid != "board" and bool(payload.get("has_detail", False)):
            if not set_tier:
                payload = dict(payload)
                payload["tier"] = None
            try:
                rep = inject_quasi_state(
                    game, seat, payload, fid, reset_ended=True,
                    tier_fn=(tier_of if set_tier else None))
            except BaseException as exc:  # noqa: BLE001 - 引擎异常 -> 该座位保持 bot
                st.errors += 1
                st.last_rejected.append([seat, repr(exc)[:200]])
                continue
            if bool(rep.get("applied")):
                st.applied += 1
                st.full_applied += 1
                if bool(rep.get("hand_applied")):
                    st.hand_applied += 1
                elif payload.get("hand_available") is False:
                    st.hand_unavailable += 1
                if bool(rep.get("counters_applied")):
                    st.counters_applied += 1
                else:
                    st.counters_unavailable += 1
                for f in (rep.get("unavailable_fields") or ()):
                    st.unavailable_fields[str(f)] = int(
                        st.unavailable_fields.get(str(f), 0)) + 1
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
            continue
        # ---- board-only（默认档；也是旧库/无 payload 的退化路径） ----
        try:
            rep = game.inject_board(seat, [list(x) for x in board], tier)
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
    "FIDELITIES", "MAX_BOARD", "MAX_BOARD_STRENGTH", "MAX_MINION_STAT", "SAMPLE_MODES",
    "SAMPLE_PERCENTILES", "SOURCE", "TURN_SCHEDULE", "TURN_TIER",
    "HumanBoard", "HumanBoardPool", "HumanBoardStats", "inject_turn",
    "load_pool", "minion_cids", "random_seats", "sample_mode_for_turn",
    "turn_tier",
]
