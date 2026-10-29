"""回合末场面快照镜像库（引擎 `Game.apply_turn_snapshots` 的数据层 + 训练侧注入驱动）。

设计：``docs/MIRROR_SNAPSHOT_DESIGN.md``。本模块只依赖 ``hsbg_engine``（不需要 torch），
因此采集/注入/冒烟都能在没有 GPU 的机器上跑。

**帧的定义**：轨迹座位 ``s`` 在回合 ``T`` 的快照 = 该座位所有动作已完成、EOT effects
已运行、pending 已解决、``ended_turn=true``，且 **combat 尚未开始** 时的 ``Player`` 状态。
采集端用「clone + 阻止推进」拿到这个时刻（见 :func:`capture_eot`）。

**文件格式**（每局一个 ``snap_<seed:08d>.json.gz``）::

    {"schema": "hsbg.mirror_snapshots", "schema_version": 1,
     "created": "2026-10-29T...", "engine": {"version": ..., "game_version": ...},
     "meta": {"checkpoint": ..., "from_turn": 6, "driver": "model"},
     "frames": [
        {"turn": 8, "seat": 3, "source_game_seed": 810000,
         "stage": "recruitment_end_before_combat", "pool_mode": "unknown",
         "player": {<Player JSON>}, "held_pool_parts": [[cid, copies], ...],
         "frame_sha256": "<sha256(player_json)>"}, ...]}

``held_pool_parts`` 是该座位在共享池里的占用 ``H(P, c)``（设计 §4.1），只为将来严格的
``pool_delta_known`` 模式留数据；当前注入走 ``pool_delta_unknown``（不扣共享池）。

**注入窗口**：新回合开始后、任何座位行动前（``g.turn`` 变化后立刻调用
:func:`inject_turn`）。被注入的座位在引擎里被置 ``ended_turn=true``，本回合不再行动。

**缺帧/失败策略**：缺帧跳过（``missing``），引擎拒绝的座位（``rejected``）与缺帧一起计入
``fallback``（该座位本回合仍由 bot 行为兜底）。绝不拿其它座位/其它回合的帧替代。
"""

from __future__ import annotations

import glob
import gzip
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 文件 schema 名与版本（与引擎 ``SNAPSHOT_SCHEMA_VERSION`` 一致；采集端写入）。
SCHEMA = "hsbg.mirror_snapshots"
SCHEMA_VERSION = 1
#: 帧的阶段标记：EOT 完成、combat 之前（唯一合法阶段）。
STAGE_EOT = "recruitment_end_before_combat"


# ────────────────────────── Player JSON 工具 ──────────────────────────


def _item_minion(item: Any) -> Optional[Dict[str, Any]]:
    """``Item::Minion`` 的 JSON（serde 外部标记：``{"Minion": {...}}``），否则 None。"""
    if isinstance(item, dict):
        m = item.get("Minion")
        if isinstance(m, dict):
            return m
    return None


def player_zones(player: Dict[str, Any]) -> List[Dict[str, Any]]:
    """被快照注入替换的四个区域里的全部 minion（board/hand/shop/hand_queue）。"""
    out: List[Dict[str, Any]] = []
    out.extend(player.get("board") or [])
    for h in player.get("hand") or []:
        m = _item_minion((h or {}).get("item"))
        if m is not None:
            out.append(m)
    for s in player.get("shop") or []:
        m = _item_minion((s or {}).get("item"))
        if m is not None:
            out.append(m)
    for it in player.get("hand_queue") or []:
        m = _item_minion(it)
        if m is not None:
            out.append(m)
    return out


def board_strength(player: Dict[str, Any]) -> int:
    """牌面强度 Σ(atk+hp)（采样/排序用，与 ``library_pool.board_strength`` 同义）。"""
    return sum(
        int(m.get("atk", 0)) + int(m.get("hp", 0))
        for m in (player.get("board") or [])
    )


_NORMAL_CACHE: Optional[Dict[int, int]] = None


def normal_card_map() -> Dict[int, int]:
    """``cid -> 普通（非金色）版本的 cid``；卡表缺失/无 normal 时映射到自身。

    `catalog_json()` 里 ``normal_id`` 是**字符串卡 id**（如 ``"BG19_010"``），这里换成
    ``CardId``（引擎内部 int）。
    """
    global _NORMAL_CACHE
    if _NORMAL_CACHE is not None:
        return _NORMAL_CACHE
    out: Dict[int, int] = {}
    try:
        import hsbg_engine as E

        rows = json.loads(E.catalog_json())
        id_to_cid = {str(c.get("id")): int(c.get("cid")) for c in rows
                     if c.get("cid") is not None}
        for c in rows:
            cid = c.get("cid")
            if cid is None:
                continue
            cid = int(cid)
            n = c.get("normal_id")
            out[cid] = int(id_to_cid.get(str(n), cid)) if n else cid
    except BaseException:  # noqa: BLE001 - 无引擎时退化为恒等映射
        out = {}
    _NORMAL_CACHE = out
    return out


def held_pool_parts(player: Dict[str, Any],
                    normal_map: Optional[Dict[int, int]] = None) -> List[List[int]]:
    """``H(P, c)``：该 Player 在共享池里实际占用的副本，``[[cid, copies], ...]``（升序）。

    语义见设计 §4.1：``pool_copies`` 为空则按普通卡计；有 ``pool_parts``（异种三连）则按
    parts 逐项计；``pool_copies=0`` 的实体一份都不占。
    """
    nm = normal_map if normal_map is not None else normal_card_map()
    acc: Dict[int, int] = {}
    for m in player_zones(player):
        copies = int(m.get("pool_copies", 0) or 0)
        if copies <= 0:
            continue
        parts = m.get("pool_parts") or []
        if parts:
            for pair in parts:
                c, n = int(pair[0]), int(pair[1])
                acc[c] = acc.get(c, 0) + n
        else:
            c = int(m.get("card", -1))
            c = int(nm.get(c, c))
            acc[c] = acc.get(c, 0) + copies
    return [[c, n] for c, n in sorted(acc.items()) if n]


# ────────────────────────── 采集（轨迹 -> 快照帧） ──────────────────────────


def _blocker_seat(game: Any, seat: int) -> Optional[int]:
    """找一个「已结束回合」的其它存活座位，把它的 ``ended_turn`` 改回 False 以阻止推进。

    引擎只有在**所有**存活座位都 ``ended_turn`` 时才开打；把一个已结束的座位标记回未结束，
    就能让 ``end_turn(seat)`` 只跑 EOT 效果而不进入 combat。找不到（``seat`` 是本回合第一个
    结束的座位）时返回 None——那种情况下本来也不会触发 combat。
    """
    for q in range(int(game.num_players)):
        if q == seat:
            continue
        try:
            pj = json.loads(game.player_json(q))
        except BaseException:  # noqa: BLE001
            continue
        if bool(pj.get("alive")) and bool(pj.get("ended_turn")):
            return q
    return None


def capture_eot(game: Any, seat: int, *, action: int = 0,
                normal_map: Optional[Dict[int, int]] = None) -> Optional[Dict[str, Any]]:
    """取 ``seat`` 的「EOT 完成、combat 之前」帧（**不改动** ``game``）。

    做法：先 clone 整局（含 RNG），在 clone 上把一个已结束座位的 ``ended_turn`` 标记回
    False 以阻止 ``fight_when_all_ended`` 推进，然后在 clone 上执行同一个 EndTurn 动作。
    返回帧 dict；若 clone 仍然推进了回合（例如有人血量归零触发淘汰/开打）则返回 None，
    调用方按「缺帧」计数（绝不把 combat 后的状态冒充 EOT 帧）。
    """
    before_turn = int(game.turn)
    clone = game.copy()
    q = _blocker_seat(clone, seat)
    if q is not None:
        pj = json.loads(clone.player_json(q))
        pj["ended_turn"] = False
        clone.set_player_from_json(q, json.dumps(pj), True, False)
    clone.step(int(seat), int(action))
    if int(clone.turn) != before_turn:
        return None
    player = json.loads(clone.player_json(int(seat)))
    if not bool(player.get("ended_turn")):
        return None
    player_json = json.dumps(player, ensure_ascii=False)
    return {
        "turn": int(before_turn),
        "seat": int(seat),
        "stage": STAGE_EOT,
        "pool_mode": "unknown",
        "player": player,
        "held_pool_parts": held_pool_parts(player, normal_map),
        "frame_sha256": hashlib.sha256(player_json.encode("utf-8")).hexdigest(),
    }


def snapshot_file_record(frames: Sequence[Dict[str, Any]], *, seed: int = 0,
                         learner_seat: int = 0, meta: Optional[Dict[str, Any]] = None,
                         engine: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """一局快照文件的完整内容（schema 头 + 帧）。"""
    rec = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "engine": dict(engine or {}),
        "meta": {"seed": int(seed), "learner_seat": int(learner_seat),
                 **dict(meta or {})},
        "frames": [
            {**{"source_game_seed": int(seed)}, **dict(fr)} for fr in frames
        ],
    }
    return rec


def write_snapshot_file(path: str, frames: Sequence[Dict[str, Any]], **kw: Any) -> str:
    """写 ``snap_*.json.gz``（父目录自动创建）；返回路径。"""
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    rec = snapshot_file_record(frames, **kw)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    return path


def engine_stamp() -> Dict[str, Any]:
    """写进文件头的引擎/数据版本，便于跨版本审计（缺引擎时为空）。"""
    try:
        import hsbg_engine as E

        return {"version": str(E.version()), "game_version": str(E.game_version()),
                "server_rules_version": str(E.server_rules_version()),
                "schema_version": int(E.snapshot_schema_version())}
    except BaseException:  # noqa: BLE001
        return {}


# ────────────────────────── 读取 / 采样 ──────────────────────────


@dataclass
class SnapshotFrame:
    """一帧回合末场面（``player`` 是引擎 ``Player`` JSON）。"""

    turn: int
    seat: int
    player: Dict[str, Any]
    held_pool_parts: List[List[int]] = field(default_factory=list)
    source_game_seed: int = 0
    pool_mode: str = "unknown"
    stage: str = STAGE_EOT
    path: str = ""
    strength: int = 0

    def __post_init__(self) -> None:
        if not self.strength:
            self.strength = board_strength(self.player)

    @property
    def player_json(self) -> str:
        return json.dumps(self.player, ensure_ascii=False)

    def to_json(self) -> Dict[str, Any]:
        return {"turn": int(self.turn), "seat": int(self.seat), "player": self.player,
                "held_pool_parts": self.held_pool_parts,
                "source_game_seed": int(self.source_game_seed),
                "pool_mode": self.pool_mode, "stage": self.stage}


class MirrorSnapshotPool:
    """目录式快照池：按 ``(turn, seat)`` 建索引，支持同一帧多来源抽样。"""

    def __init__(self, root: Optional[str] = None, *, sample: str = "strong"):
        self.root = root
        #: ``(turn, seat) -> [SnapshotFrame]``
        self.index: Dict[Tuple[int, int], List[SnapshotFrame]] = {}
        self.sample_mode = str(sample)
        self.files = 0
        self.frames = 0
        self.bad_files = 0
        self.schema_versions: Dict[int, int] = {}
        if root:
            self.load(root)

    # ---- 读取 ----
    def load(self, root: str) -> int:
        """读取 ``root/snap_*.json.gz``；返回载入的帧数（坏文件跳过并计数）。"""
        self.root = root
        for path in sorted(glob.glob(os.path.join(root, "snap_*.json.gz"))):
            try:
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    d = json.load(f)
            except BaseException:  # noqa: BLE001
                self.bad_files += 1
                continue
            if str(d.get("schema", SCHEMA)) != SCHEMA:
                self.bad_files += 1
                continue
            ver = int(d.get("schema_version", 0))
            self.schema_versions[ver] = self.schema_versions.get(ver, 0) + 1
            if ver != SCHEMA_VERSION:
                # 版本不兼容：拒绝（卡下标/字段语义可能已变）。
                self.bad_files += 1
                continue
            n = 0
            for fr in d.get("frames") or []:
                player = fr.get("player")
                if isinstance(player, str):            # 兼容「player 存成字符串」的写法
                    try:
                        player = json.loads(player)
                    except BaseException:  # noqa: BLE001
                        continue
                if not isinstance(player, dict) or "board" not in player:
                    continue
                if str(fr.get("stage", STAGE_EOT)) != STAGE_EOT:
                    continue
                frame = SnapshotFrame(
                    turn=int(fr.get("turn", 0)), seat=int(fr.get("seat", 0)),
                    player=player,
                    held_pool_parts=list(fr.get("held_pool_parts") or []),
                    source_game_seed=int(fr.get("source_game_seed",
                                                d.get("meta", {}).get("seed", 0))),
                    pool_mode=str(fr.get("pool_mode", "unknown")),
                    stage=str(fr.get("stage", STAGE_EOT)), path=path)
                if frame.turn <= 0:
                    continue
                self.index.setdefault((frame.turn, frame.seat), []).append(frame)
                n += 1
            self.frames += n
            self.files += 1
        return self.frames

    # ---- 采样 ----
    def has(self, turn: int, seat: int) -> bool:
        return bool(self.index.get((int(turn), int(seat))))

    def get(self, turn: int, seat: int,
            rng: Optional[random.Random] = None) -> Optional[SnapshotFrame]:
        """取 ``(turn, seat)`` 的帧；同键多来源时按 ``sample_mode`` 选（缺帧返回 None）。"""
        cands = self.index.get((int(turn), int(seat)))
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        if self.sample_mode == "strong":
            return max(cands, key=lambda f: f.strength)
        if self.sample_mode == "weak":
            return min(cands, key=lambda f: f.strength)
        r = rng or random
        return cands[r.randrange(len(cands))]

    def turns(self) -> List[int]:
        return sorted({t for t, _ in self.index})

    def stats(self) -> Dict[str, Any]:
        if not self.index:
            return {"files": self.files, "frames": 0, "keys": 0}
        turns = self.turns()
        seats = sorted({s for _, s in self.index})
        per_key = [len(v) for v in self.index.values()]
        return {"files": int(self.files), "frames": int(self.frames),
                "bad_files": int(self.bad_files), "keys": len(self.index),
                "turn_min": turns[0], "turn_max": turns[-1], "seats": seats,
                "frames_per_key_p50": sorted(per_key)[len(per_key) // 2],
                "schema_versions": dict(self.schema_versions)}


# ────────────────────────── 训练侧注入驱动 ──────────────────────────


@dataclass
class MirrorStats:
    """一次/多局注入的计数（写进采集 meta）。"""

    attempt: int = 0        # 概率命中并尝试注入的 (seat, turn) 数
    applied: int = 0        # 引擎成功替换的座位数
    rejected: int = 0       # 引擎拒绝的座位数（fail-closed，状态未变）
    missing: int = 0        # 缺帧数
    fallback: int = 0       # 退回 bot 行为的座位数（= missing + rejected + errors）
    errors: int = 0         # Python 侧异常（引擎/数据问题）
    pool_unbalanced: int = 0        # 注入后 pool_balance 不守恒的次数
    pool_species_unbalanced: int = 0  # 注入后逐物种不守恒的次数
    last_rejected: List[List[Any]] = field(default_factory=list)

    def add(self, other: "MirrorStats") -> None:
        self.attempt += other.attempt
        self.applied += other.applied
        self.rejected += other.rejected
        self.missing += other.missing
        self.fallback += other.fallback
        self.errors += other.errors
        self.pool_unbalanced += other.pool_unbalanced
        self.pool_species_unbalanced += other.pool_species_unbalanced
        for r in other.last_rejected[:4]:
            if len(self.last_rejected) < 16:
                self.last_rejected.append(list(r))

    def to_meta(self) -> Dict[str, Any]:
        return {"mirror_attempt": int(self.attempt), "mirror_applied": int(self.applied),
                "mirror_rejected": int(self.rejected), "mirror_missing": int(self.missing),
                "mirror_fallback": int(self.fallback), "mirror_errors": int(self.errors),
                "mirror_pool_unbalanced": int(self.pool_unbalanced),
                "mirror_pool_species_unbalanced": int(self.pool_species_unbalanced),
                "mirror_last_rejected": [list(x) for x in self.last_rejected]}


def mirror_seats(count: int, num_players: int = 8, learner_seat: int = 0) -> List[int]:
    """``--mirror-seats N`` -> 目标座位列表 ``1..N``（排除 learner、越界座位）。"""
    out: List[int] = []
    for s in range(1, int(count) + 1):
        if s >= int(num_players) or s == int(learner_seat):
            continue
        out.append(s)
    return out


def inject_turn(game: Any, pool: MirrorSnapshotPool, turn: int, *,
                seats: Sequence[int], p: float = 1.0,
                rng: Optional[random.Random] = None, learner_seat: int = 0,
                stats: Optional[MirrorStats] = None,
                advance: Optional[bool] = None) -> MirrorStats:
    """新回合开始（任何座位行动前）按概率给 ``seats`` 注入该 ``turn`` 的快照。

    - 每个座位独立掷 ``p``；缺帧 -> ``missing``；引擎拒绝 -> ``rejected``；
    - 整批只调用一次 ``apply_turn_snapshots``（``advance`` 透传给引擎）；
    - 被注入的座位在引擎里 ``ended_turn=true``，本回合不再行动（不消耗 bot 动作）。
    """
    st = stats if stats is not None else MirrorStats()
    r = rng or random
    prob = max(0.0, min(1.0, float(p)))
    snaps: List[List[Any]] = []
    used: List[int] = []
    for seat in seats:
        seat = int(seat)
        if seat == int(learner_seat):
            continue
        if prob < 1.0 and r.random() >= prob:
            continue
        st.attempt += 1
        try:
            frame = pool.get(int(turn), seat, rng=r)
        except BaseException:  # noqa: BLE001
            frame = None
            st.errors += 1
        if frame is None:
            st.missing += 1
            st.fallback += 1
            continue
        snaps.append([seat, frame.player_json])
        used.append(seat)
    if not snaps:
        return st
    try:
        rep = game.apply_turn_snapshots(snaps, advance)
    except BaseException as exc:  # noqa: BLE001 - 引擎异常 -> 全部退回 bot
        st.errors += 1
        st.fallback += len(snaps)
        st.last_rejected.append([-1, repr(exc)[:200]])
        return st
    st.applied += int(rep.get("applied", 0))
    rejected = rep.get("rejected") or []
    st.rejected += len(rejected)
    st.fallback += len(rejected)
    for item in rejected[:4]:
        if len(st.last_rejected) < 16:
            st.last_rejected.append([int(item[0]), str(item[1])[:200]])
    if not bool(rep.get("pool_balance_ok", True)):
        st.pool_unbalanced += 1
    if not bool(rep.get("pool_species_ok", True)):
        st.pool_species_unbalanced += 1
    return st


def load_pool(root: Optional[str], *, sample: str = "strong") -> Optional[MirrorSnapshotPool]:
    """便捷入口：``root`` 为空/不存在/无帧时返回 None（调用方按纯 bot 行为继续）。"""
    if not root:
        return None
    if not os.path.isdir(str(root)):
        return None
    pool = MirrorSnapshotPool(str(root), sample=sample)
    return pool if pool.frames else None


__all__ = [
    "SCHEMA", "SCHEMA_VERSION", "STAGE_EOT", "SnapshotFrame", "MirrorSnapshotPool",
    "MirrorStats", "board_strength", "capture_eot", "engine_stamp", "held_pool_parts",
    "inject_turn", "load_pool", "mirror_seats", "normal_card_map", "player_zones",
    "snapshot_file_record", "write_snapshot_file",
]
