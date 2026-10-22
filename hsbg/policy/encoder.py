"""观测编码器：把 ``hsbg.env.spec.Observation`` 转成定长训练张量。

设计
----
1. **实体序列定长化**：观测里各区域（board/hand/tavern/trinket/quest/
   opponent/choice）按 ``ENTITY_LAYOUT`` 顺序拼成一条定长实体序列，每个实体
   分配一个**全局下标**；padding 位 ``entity_mask=0``。候选动作的
   ``src_zone/src_slot`` 由 :func:`entity_index` 映射到该全局下标，越界安全
   （返回 -1 → 候选特征 ``has_src=0``，模型用零向量表示）。
2. **卡牌词表**：``CardVocab`` 维护 ``card_id -> index``，0 号 ``<PAD>``，
   1 号 ``<UNK>``；可从 ``data/*.json`` 构建、从观测动态补充、保存/加载。
3. **纯 numpy 编码 + torch collate**：单条观测编码不依赖 torch（可在数据
   收集进程里跑）；``collate`` 负责 batch 化并在需要时转 torch。所有
   batch 张量都以 ``CANDIDATE_MAX`` 为候选维，长度不足补 mask=0。

张量约定（``collate`` 后带 batch 维 B）
---------------------------------------
========================  ==========================  ==========================
key                       shape                       说明
========================  ==========================  ==========================
``entity_card``           int64 [B, E]                卡片词表下标（0=padding）
``entity_num``            float32 [B, E, NE]          实体数值特征
``entity_mask``           float32 [B, E]              1=真实实体
``entity_zone``           int64 [B, E]                区域下标
``entity_pos``            int64 [B, E]                区域槽位下标（位置编码）
``global``                float32 [B, G]              全局标量
``cand_kind``             int64 [B, C]                动作类型下标
``cand_num``              float32 [B, C, NC]          候选数值特征
``cand_src``              int64 [B, C]                源实体全局下标（无效=0）
``cand_tgt``              int64 [B, C]                目标实体全局下标
``cand_mask``             float32 [B, C]              1=有效候选
========================  ==========================  ==========================

其中 ``E = NUM_ENTITIES``、``C = CANDIDATE_MAX``、``G/NE/NC`` 见下方常量。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from hsbg.env.spec import (
    ACTION_KIND_INDEX,
    BOARD_MAX,
    CANDIDATE_MAX,
    CARD_TYPE_ANOMALY,
    CARD_TYPE_HERO,
    CARD_TYPE_HERO_POWER,
    CARD_TYPE_MINION,
    CARD_TYPE_QUEST,
    CARD_TYPE_REWARD,
    CARD_TYPE_SPELL,
    CARD_TYPE_TRINKET,
    CARD_TYPE_UNKNOWN,
    CHOICE_OPTION_MAX,
    ENTITY_ZONES,
    HAND_MAX,
    KEYWORD_INDEX,
    NUM_ACTION_KINDS,
    NUM_KEYWORDS,
    NUM_RACES,
    OBS_DIMS,
    OPPONENT_BOARD_MAX,
    PHASE_CHOICE,
    PHASE_GAME_OVER,
    PHASE_RECRUIT,
    PLAYER_MAX,
    RACE_INDEX,
    RACES,
    TAVERN_MAX,
    TRINKET_MAX,
    ZONE_BOARD,
    ZONE_CHOICE,
    ZONE_HAND,
    ZONE_NONE,
    ZONE_OPPONENT,
    ZONE_QUEST,
    ZONE_TAVERN,
    ZONE_TRINKET,
    CandidateAction,
    EntityToken,
    Observation,
    ObsDims,
)

# ══════════════════════════════════════════════════════════════════════
# 维度常量（改这里 = 升 checkpoint 版本）
# ══════════════════════════════════════════════════════════════════════

#: 卡牌类型顺序（稳定，禁止重排）
CARD_TYPES: Tuple[str, ...] = (
    CARD_TYPE_MINION,
    CARD_TYPE_SPELL,
    CARD_TYPE_HERO,
    CARD_TYPE_HERO_POWER,
    CARD_TYPE_TRINKET,
    CARD_TYPE_QUEST,
    CARD_TYPE_REWARD,
    CARD_TYPE_ANOMALY,
    CARD_TYPE_UNKNOWN,
)
CARD_TYPE_INDEX: Dict[str, int] = {t: i for i, t in enumerate(CARD_TYPES)}
NUM_CARD_TYPES = len(CARD_TYPES)

#: 区域顺序（与 spec.ENTITY_ZONES 一致）
ZONE_INDEX: Dict[str, int] = {z: i for i, z in enumerate(ENTITY_ZONES)}
NUM_ZONES = len(ENTITY_ZONES)

#: 实体序列布局：``(zone, 该区域槽位数)``，顺序即全局下标顺序
ENTITY_LAYOUT: Tuple[Tuple[str, int], ...] = (
    (ZONE_BOARD, BOARD_MAX),
    (ZONE_HAND, HAND_MAX),
    (ZONE_TAVERN, TAVERN_MAX),
    (ZONE_TRINKET, TRINKET_MAX),
    (ZONE_QUEST, 1),
    (ZONE_OPPONENT, OPPONENT_BOARD_MAX),
    (ZONE_CHOICE, CHOICE_OPTION_MAX),
)
#: 实体序列总长度
NUM_ENTITIES = sum(n for _, n in ENTITY_LAYOUT)
#: zone -> 该区域第一个实体在序列中的全局下标
ZONE_OFFSET: Dict[str, int] = {}
_offset = 0
for _zone, _count in ENTITY_LAYOUT:
    ZONE_OFFSET[_zone] = _offset
    _offset += _count
#: zone -> 该区域槽位数（越界检查用）
ZONE_SLOTS: Dict[str, int] = {z: n for z, n in ENTITY_LAYOUT}
#: 单区域最大槽位数（位置编码 embedding 大小）
MAX_ZONE_SLOTS = max(n for _, n in ENTITY_LAYOUT)

#: ``<PAD>`` 下标
PAD_CARD_INDEX = 0
#: ``<UNK>`` 下标
UNK_CARD_INDEX = 1
#: 卡片词表特殊 token（顺序固定，index 与常量对应）
SPECIAL_TOKENS: Tuple[str, ...] = ("<PAD>", "<UNK>")


def entity_index(zone: str, slot: int) -> int:
    """``(zone, slot)`` → 实体序列全局下标；非法返回 -1（越界安全）。"""
    if slot is None or slot < 0:
        return -1
    off = ZONE_OFFSET.get(zone)
    if off is None:
        return -1
    if slot >= ZONE_SLOTS[zone]:
        return -1
    return off + int(slot)


# ── 实体数值特征布局 ──
ENTITY_FEATURE_BLOCKS: Tuple[Tuple[str, int], ...] = (
    ("atk", 1),
    ("health", 1),
    ("tier", 1),
    ("cost", 1),
    ("golden", 1),
    ("slot_frac", 1),
    ("seq_frac", 1),
    ("card_type", NUM_CARD_TYPES),
    ("zone", NUM_ZONES),
    ("race", NUM_RACES),
    ("keyword", NUM_KEYWORDS),
)
ENTITY_NUM_DIM = sum(size for _, size in ENTITY_FEATURE_BLOCKS)
ENTITY_FEATURE_OFFSET: Dict[str, int] = {}
_off = 0
for _name, _size in ENTITY_FEATURE_BLOCKS:
    ENTITY_FEATURE_OFFSET[_name] = _off
    _off += _size
assert _off == ENTITY_NUM_DIM

# ── 全局特征布局（顺序即向量顺序，禁止重排；改 = 升 checkpoint 版本）──
GLOBAL_FEATURE_NAMES: Tuple[str, ...] = (
    "turn",              # 0  回合 /15
    "gold",              # 1  金币 /12
    "tier",              # 2  酒馆等级 /6
    "health",            # 3  生命 /40
    "armor",             # 4  护甲 /20
    "upgrade_cost",      # 5  升级费用 /12
    "alive_count",       # 6  存活人数 /8
    "total_players",     # 7  总人数 /8
    "rank",              # 8  当前名次 /8
    "board_atk",         # 9  棋盘攻击和 /50
    "board_health",      # 10 棋盘生命和 /50
    "board_count",       # 11 棋盘随从数 /7
    "hand_count",        # 12 手牌数 /10
    "tavern_count",      # 13 酒馆展示数 /7
    "trinket_count",     # 14 饰品数 /2
    "has_quest",         # 15 是否有任务
    "power_usable",      # 16 英雄技能可用
    "power_cost",        # 17 英雄技能费用 /12
    "phase_recruit",     # 18
    "phase_choice",      # 19
    "phase_game_over",   # 20
    "num_candidates",    # 21 候选动作数 /64
    "tavern_tier_max",   # 22 等级上限 /6
    "lobby_mean_health", # 23 大厅平均血量 /40
    "lobby_min_health",  # 24 大厅最低血量 /40
    "lobby_alive_frac",  # 25 大厅存活比例
    "no_hero",           # 26 hero is None
    "board_power",       # 27 (atk+health)/200
    "best_tavern_tier",  # 28 酒馆最高等级 /6
    "mean_board_tier",   # 29 棋盘平均等级 /6
)
GLOBAL_DIM = len(GLOBAL_FEATURE_NAMES)
#: 全局特征名 -> 下标
GLOBAL_FEATURE_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(GLOBAL_FEATURE_NAMES)
}

# ── 候选动作数值特征布局 ──
CAND_FEATURE_BLOCKS: Tuple[Tuple[str, int], ...] = (
    ("kind", NUM_ACTION_KINDS),
    ("cost", 1),
    ("has_cost", 1),
    ("position", 1),
    ("has_position", 1),
    ("option", 1),
    ("has_option", 1),
    ("has_src", 1),
    ("has_tgt", 1),
    ("src_zone", NUM_ZONES),
    ("tgt_zone", NUM_ZONES),
    ("src_slot", 1),
    ("tgt_slot", 1),
)
CAND_NUM_DIM = sum(size for _, size in CAND_FEATURE_BLOCKS)
CAND_FEATURE_OFFSET: Dict[str, int] = {}
_off = 0
for _name, _size in CAND_FEATURE_BLOCKS:
    CAND_FEATURE_OFFSET[_name] = _off
    _off += _size
assert _off == CAND_NUM_DIM

#: 编码器张量 key（供 buffer / 数据集遍历）
ENCODED_KEYS: Tuple[str, ...] = (
    "entity_card",
    "entity_num",
    "entity_mask",
    "entity_zone",
    "entity_pos",
    "global",
    "cand_kind",
    "cand_num",
    "cand_src",
    "cand_tgt",
    "cand_mask",
)


# ══════════════════════════════════════════════════════════════════════
# 维度描述
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EncoderDims:
    """编码器张量尺寸（写进 checkpoint；与模型 config 交叉校验）。"""

    num_entities: int = NUM_ENTITIES
    entity_num_dim: int = ENTITY_NUM_DIM
    global_dim: int = GLOBAL_DIM
    cand_num_dim: int = CAND_NUM_DIM
    candidate_max: int = CANDIDATE_MAX
    num_zones: int = NUM_ZONES
    num_card_types: int = NUM_CARD_TYPES

    def as_dict(self) -> Dict[str, int]:
        return {
            "num_entities": self.num_entities,
            "entity_num_dim": self.entity_num_dim,
            "global_dim": self.global_dim,
            "cand_num_dim": self.cand_num_dim,
            "candidate_max": self.candidate_max,
            "num_zones": self.num_zones,
            "num_card_types": self.num_card_types,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EncoderDims":
        return cls(**{k: int(v) for k, v in d.items() if k in cls.__dataclass_fields__})

    def as_spec_obs_dims(self) -> ObsDims:
        """返回 ``hsbg.env.spec.ObsDims`` 视图（实际值覆盖占位默认值）。"""
        return ObsDims(
            num_card_types=self.num_card_types,
            num_zones=self.num_zones,
            num_races=NUM_RACES,
            num_keywords=NUM_KEYWORDS,
            num_action_kinds=NUM_ACTION_KINDS,
            board_max=BOARD_MAX,
            hand_max=HAND_MAX,
            tavern_max=TAVERN_MAX,
            trinket_max=TRINKET_MAX,
            opponent_max=OPPONENT_BOARD_MAX,
            candidate_max=self.candidate_max,
            entity_num_dim=self.entity_num_dim,
            global_dim=self.global_dim,
        )


#: 当前编码器尺寸
ENCODER_DIMS = EncoderDims()


# ══════════════════════════════════════════════════════════════════════
# 卡牌词表
# ══════════════════════════════════════════════════════════════════════

#: 默认读取的引擎数据文件（相对 ``hsbg.paths.DATA_DIR``）
DEFAULT_CARD_DATA_FILES: Tuple[str, ...] = (
    "bg_cards.json",
    "bg_pool_minions.json",
    "bg_pool_spells.json",
    "bg_tavern_spells.json",
    "bg_heroes.json",
    "bg_hero_powers.json",
    "bg_trinkets.json",
    "bg_quest_rewards.json",
    "bg_anomalies.json",
    "bg_dark_gifts.json",
)


class CardVocab:
    """``card_id -> index`` 词表（0=<PAD>, 1=<UNK>）。

    用法::

        vocab = CardVocab.from_data_dir()      # data/*.json 构建
        vocab = CardVocab.load("runs/vocab.json")
        idx = vocab.index("BG19_010")          # 未收录 -> <UNK>
        vocab.add("NEW_CARD")                  # 动态补充
        vocab.save("runs/vocab.json")
    """

    __slots__ = ("_ids", "_index")

    def __init__(self, card_ids: Optional[Iterable[str]] = None) -> None:
        self._ids: List[str] = list(SPECIAL_TOKENS)
        self._index: Dict[str, int] = {t: i for i, t in enumerate(SPECIAL_TOKENS)}
        if card_ids:
            self.extend(card_ids)

    # ── 构建 ──
    @classmethod
    def from_data_dir(
        cls,
        data_dir: Optional[Path] = None,
        files: Sequence[str] = DEFAULT_CARD_DATA_FILES,
    ) -> "CardVocab":
        """从 ``data/*.json`` 收集全部 ``id`` 字段构建词表。"""
        if data_dir is None:
            from hsbg.paths import DATA_DIR

            data_dir = DATA_DIR
        data_dir = Path(data_dir)
        ids: List[str] = []
        for fname in files:
            path = data_dir / fname
            if not path.exists():
                continue  # 数据缺文件时降级（只影响词表覆盖率）
            try:
                with open(path, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            for rec in _iter_records(records):
                cid = rec.get("id")
                if isinstance(cid, str) and cid:
                    ids.append(cid)
        return cls(ids)

    @classmethod
    def from_observations(
        cls,
        observations: Iterable[Observation],
        base: Optional["CardVocab"] = None,
    ) -> "CardVocab":
        """从观测动态收集 card_id（可用于真环境上"发现新卡"）。"""
        vocab = CardVocab() if base is None else base
        for obs in observations:
            vocab.extend(collect_card_ids(obs))
        return vocab

    # ── 查询/修改 ──
    def __len__(self) -> int:
        return len(self._ids)

    def __contains__(self, card_id: str) -> bool:
        return card_id in self._index

    @property
    def size(self) -> int:
        return len(self._ids)

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(self._ids)

    def index(self, card_id: str) -> int:
        """返回下标；空/未知 → ``<UNK>``（不抛异常，保证训练不崩）。"""
        if not card_id:
            return PAD_CARD_INDEX
        return self._index.get(card_id, UNK_CARD_INDEX)

    def card_id(self, index: int) -> str:
        if 0 <= index < len(self._ids):
            return self._ids[index]
        return SPECIAL_TOKENS[UNK_CARD_INDEX]

    def add(self, card_id: str) -> int:
        if not card_id:
            return PAD_CARD_INDEX
        got = self._index.get(card_id)
        if got is not None:
            return got
        idx = len(self._ids)
        self._ids.append(card_id)
        self._index[card_id] = idx
        return idx

    def extend(self, card_ids: Iterable[str]) -> int:
        """批量补充；返回新增数量。"""
        before = len(self._ids)
        for cid in card_ids:
            self.add(cid)
        return len(self._ids) - before

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CardVocab) and self._ids == other._ids

    def __repr__(self) -> str:  # pragma: no cover - 调试
        return f"CardVocab(size={len(self._ids)})"

    # ── 序列化（json，便于人工检查）──
    def to_dict(self) -> Dict[str, Any]:
        return {"version": 1, "tokens": self._ids}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CardVocab":
        ids = d.get("tokens") or d.get("ids") or []
        vocab = cls()
        # 保留特殊 token 位置一致性
        for i, token in enumerate(ids):
            if i < len(SPECIAL_TOKENS):
                if token != SPECIAL_TOKENS[i]:  # 兜底修复
                    vocab = cls()
                    vocab._ids = list(SPECIAL_TOKENS) + list(ids[len(SPECIAL_TOKENS):])
                    vocab._index = {t: i for i, t in enumerate(vocab._ids)}
                continue
            vocab.add(token)
        return vocab

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, path: Path) -> "CardVocab":
        with open(Path(path), "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def _iter_records(records: Any) -> Iterable[Dict[str, Any]]:
    """容忍 list[dict] / dict[str, dict] / dict[str, list] 多种数据形状。"""
    if isinstance(records, list):
        for rec in records:
            if isinstance(rec, dict):
                yield rec
    elif isinstance(records, dict):
        for value in records.values():
            if isinstance(value, dict):
                yield value
            elif isinstance(value, list):
                for rec in value:
                    if isinstance(rec, dict):
                        yield rec


def collect_card_ids(obs: Observation) -> Set[str]:
    """收集单条观测里出现的全部 card_id（含选择选项）。"""
    ids: Set[str] = set()

    def _add(tok: Optional[EntityToken]) -> None:
        if tok is not None and tok.card_id:
            ids.add(tok.card_id)

    for tok in obs.board:
        _add(tok)
    for tok in obs.hand:
        _add(tok)
    for tok in obs.tavern:
        _add(tok)
    for tok in obs.trinkets:
        _add(tok)
    _add(obs.quest)
    for tok in obs.opponent_board:
        _add(tok)
    if obs.pending_choice is not None:
        for tok in obs.pending_choice.options:
            _add(tok)
    if obs.hero is not None and obs.hero.hero_id:
        ids.add(obs.hero.hero_id)
    return ids


# ══════════════════════════════════════════════════════════════════════
# 观测编码器
# ══════════════════════════════════════════════════════════════════════


class ObservationEncoder:
    """``Observation`` → 定长 numpy/torch 张量。

    ``encode_obs(obs)`` 返回单条观测的 numpy 数组字典（无 batch 维）；
    ``collate(obs_list)`` 返回 batch 化 torch 张量字典（带 batch 维）。
    """

    def __init__(self, vocab: Optional[CardVocab] = None) -> None:
        self.vocab = vocab if vocab is not None else CardVocab()
        self.dims = ENCODER_DIMS

    # ── 主入口 ──
    def encode_obs(self, obs: Observation) -> Dict[str, np.ndarray]:
        dims = self.dims
        E, C = dims.num_entities, dims.candidate_max
        entity_card = np.zeros(E, dtype=np.int64)
        entity_num = np.zeros((E, dims.entity_num_dim), dtype=np.float32)
        entity_mask = np.zeros(E, dtype=np.float32)
        entity_zone = np.zeros(E, dtype=np.int64)
        entity_pos = np.zeros(E, dtype=np.int64)
        cand_kind = np.zeros(C, dtype=np.int64)
        cand_num = np.zeros((C, dims.cand_num_dim), dtype=np.float32)
        cand_src = np.zeros(C, dtype=np.int64)
        cand_tgt = np.zeros(C, dtype=np.int64)
        cand_mask = np.zeros(C, dtype=np.float32)

        # ── 实体 ──
        zone_entities: Dict[str, Sequence[EntityToken]] = {
            ZONE_BOARD: obs.board or (),
            ZONE_HAND: obs.hand or (),
            ZONE_TAVERN: obs.tavern or (),
            ZONE_TRINKET: obs.trinkets or (),
            ZONE_OPPONENT: obs.opponent_board or (),
            ZONE_QUEST: ((obs.quest,) if obs.quest is not None else ()),
            ZONE_CHOICE: (
                (obs.pending_choice.options if obs.pending_choice is not None else ())
            ),
        }
        for zone, tokens in zone_entities.items():
            off = ZONE_OFFSET[zone]
            zidx = ZONE_INDEX[zone]
            zone_slots = self._zone_slots(zone)
            for slot, tok in enumerate(tokens[:zone_slots]):
                gi = off + slot
                entity_mask[gi] = 1.0
                entity_zone[gi] = zidx
                entity_pos[gi] = min(int(tok.slot if tok.slot >= 0 else slot), MAX_ZONE_SLOTS - 1)
                entity_card[gi] = self.vocab.index(tok.card_id)
                self._fill_entity_features(
                    entity_num[gi], tok, zone=zone, slot=slot,
                    zone_slots=zone_slots, global_index=gi,
                )

        # ── 全局 ──
        global_vec = self._global_features(obs)

        # ── 候选动作 ──
        candidates = tuple(obs.candidates or ())
        n_cand = min(len(candidates), C)
        for i in range(n_cand):
            cand = candidates[i]
            cand_mask[i] = 1.0
            kind_idx = ACTION_KIND_INDEX.get(_kind_value(cand.kind), 0)
            cand_kind[i] = kind_idx
            src_idx = entity_index(cand.src_zone, cand.src_slot)
            tgt_idx = entity_index(cand.tgt_zone, cand.tgt_slot)
            # choose 动作的选项实体：option 下标 → choice 区实体
            if src_idx < 0 and cand.option is not None and cand.option >= 0:
                if _kind_value(cand.kind) == "choose":
                    src_idx = entity_index(ZONE_CHOICE, int(cand.option))
            if src_idx >= 0:
                cand_src[i] = src_idx
            if tgt_idx >= 0:
                cand_tgt[i] = tgt_idx
            self._fill_cand_features(
                cand_num[i], cand,
                src_idx=src_idx, tgt_idx=tgt_idx,
            )

        return {
            "entity_card": entity_card,
            "entity_num": entity_num,
            "entity_mask": entity_mask,
            "entity_zone": entity_zone,
            "entity_pos": entity_pos,
            "global": global_vec,
            "cand_kind": cand_kind,
            "cand_num": cand_num,
            "cand_src": cand_src,
            "cand_tgt": cand_tgt,
            "cand_mask": cand_mask,
        }

    # 兼容别名
    encode = encode_obs

    def encode_batch(self, obs_list: Sequence[Observation]) -> Dict[str, np.ndarray]:
        """把多条观测堆叠成 numpy batch（无 torch 依赖）。"""
        return stack_encoded([self.encode_obs(o) for o in obs_list])

    def collate(
        self,
        obs_list: Sequence[Observation],
        device: Any = None,
        dtype: Any = None,
    ) -> Dict[str, Any]:
        """batch 化为 torch 张量（默认 float32 / int64，CPU）。"""
        return to_torch(self.encode_batch(obs_list), device=device, dtype=dtype)

    def collate_encoded(
        self, encoded_list: Sequence[Dict[str, np.ndarray]], device: Any = None,
    ) -> Dict[str, Any]:
        """把已编码样本（``encode_obs`` 结果列表）batch 化为 torch 张量。"""
        return to_torch(stack_encoded(encoded_list), device=device)

    # ── 序列化（写进 checkpoint）──
    def to_meta(self) -> Dict[str, Any]:
        return {"dims": self.dims.as_dict(), "vocab": self.vocab.to_dict()}

    @classmethod
    def from_meta(cls, meta: Dict[str, Any]) -> "ObservationEncoder":
        vocab = CardVocab.from_dict(meta.get("vocab") or {})
        enc = cls(vocab)
        if meta.get("dims"):
            enc.dims = EncoderDims.from_dict(meta["dims"])
        return enc

    # ── 内部：特征填充 ──
    @staticmethod
    def _zone_slots(zone: str) -> int:
        for z, n in ENTITY_LAYOUT:
            if z == zone:
                return n
        return 0

    def _fill_entity_features(
        self,
        out: np.ndarray,
        tok: EntityToken,
        *,
        zone: str,
        slot: int,
        zone_slots: int,
        global_index: int,
    ) -> None:
        off = ENTITY_FEATURE_OFFSET
        out[off["atk"]] = min(max(float(tok.atk), -20.0), 200.0) / 20.0
        out[off["health"]] = min(max(float(tok.health), -20.0), 200.0) / 20.0
        out[off["tier"]] = min(max(float(tok.tier), 0.0), 7.0) / 6.0
        out[off["cost"]] = min(max(float(tok.cost), 0.0), 12.0) / 12.0
        out[off["golden"]] = 1.0 if tok.golden else 0.0
        out[off["slot_frac"]] = (slot / max(zone_slots - 1, 1)) if zone_slots > 1 else 0.0
        out[off["seq_frac"]] = global_index / max(NUM_ENTITIES - 1, 1)
        ct = CARD_TYPE_INDEX.get(tok.card_type, CARD_TYPE_INDEX[CARD_TYPE_UNKNOWN])
        out[off["card_type"] + ct] = 1.0
        z = ZONE_INDEX.get(zone)
        if z is not None:
            out[off["zone"] + z] = 1.0
        race_off = off["race"]
        races = tok.races or ()
        if not races:
            out[race_off + RACE_INDEX["none"]] = 1.0
        else:
            for r in races:
                out[race_off + RACE_INDEX.get(r, RACE_INDEX["none"])] = 1.0
        kw_off = off["keyword"]
        for kw in tok.keywords or ():
            out[kw_off + KEYWORD_INDEX.get(kw, KEYWORD_INDEX["other"])] = 1.0

    def _fill_cand_features(
        self,
        out: np.ndarray,
        cand: CandidateAction,
        *,
        src_idx: int,
        tgt_idx: int,
    ) -> None:
        off = CAND_FEATURE_OFFSET
        kind = _kind_value(cand.kind)
        k = ACTION_KIND_INDEX.get(kind, 0)
        out[off["kind"] + k] = 1.0
        cost = cand.cost
        if cost is not None and cost >= 0:
            out[off["cost"]] = min(float(cost), 12.0) / 12.0
            out[off["has_cost"]] = 1.0
        pos = cand.position
        if pos is not None and pos >= 0:
            out[off["position"]] = min(float(pos), 7.0) / 7.0
            out[off["has_position"]] = 1.0
        opt = cand.option
        if opt is not None and opt >= 0:
            out[off["option"]] = min(float(opt), 5.0) / 5.0
            out[off["has_option"]] = 1.0
        sz = ZONE_INDEX.get(cand.src_zone)
        if sz is not None:
            out[off["src_zone"] + sz] = 1.0
        tz = ZONE_INDEX.get(cand.tgt_zone)
        if tz is not None:
            out[off["tgt_zone"] + tz] = 1.0
        if cand.src_slot is not None and cand.src_slot >= 0:
            out[off["src_slot"]] = min(float(cand.src_slot), 7.0) / 7.0
        if cand.tgt_slot is not None and cand.tgt_slot >= 0:
            out[off["tgt_slot"]] = min(float(cand.tgt_slot), 7.0) / 7.0
        out[off["has_src"]] = 1.0 if src_idx >= 0 else 0.0
        out[off["has_tgt"]] = 1.0 if tgt_idx >= 0 else 0.0

    # ── 内部：全局特征 ──
    def _global_features(self, obs: Observation) -> np.ndarray:
        g = np.zeros(GLOBAL_DIM, dtype=np.float32)
        hero = obs.hero
        board = obs.board or ()
        hand = obs.hand or ()
        tavern = obs.tavern or ()
        board_atk = float(sum(t.atk for t in board))
        board_health = float(sum(t.health for t in board))
        alive = int(obs.alive_count or 0)
        total = int(obs.total_players or 0) or PLAYER_MAX

        def _set(name: str, value: float) -> None:
            g[GLOBAL_FEATURE_INDEX[name]] = float(value)

        _set("turn", min(float(obs.turn), 15.0) / 15.0)
        _set("gold", min(max(float(hero.gold if hero else 0), 0.0), 12.0) / 12.0)
        _set("tier", min(float(hero.tier if hero else 0), 6.0) / 6.0)
        _set("health", min(max(float(hero.health if hero else 0), -10.0), 40.0) / 40.0)
        _set("armor", min(max(float(hero.armor if hero else 0), 0.0), 30.0) / 20.0)
        _set("upgrade_cost",
             min(max(float(hero.upgrade_cost if hero else 0), 0.0), 12.0) / 12.0)
        _set("alive_count", min(float(alive), 8.0) / 8.0)
        _set("total_players", min(float(total), 8.0) / 8.0)
        _set("rank", min(float(obs.rank if obs.rank else 0), 8.0) / 8.0)
        _set("board_atk", min(board_atk, 50.0) / 50.0)
        _set("board_health", min(board_health, 50.0) / 50.0)
        _set("board_count", min(float(len(board)), 7.0) / 7.0)
        _set("hand_count", min(float(len(hand)), 10.0) / 10.0)
        _set("tavern_count", min(float(len(tavern)), 7.0) / 7.0)
        _set("trinket_count", min(float(len(obs.trinkets or ())), 2.0) / 2.0)
        _set("has_quest", 1.0 if obs.quest is not None else 0.0)
        _set("power_usable", 1.0 if (hero is not None and hero.power_usable) else 0.0)
        _set("power_cost",
             min(max(float(hero.power_cost if hero else 0), 0.0), 12.0) / 12.0)
        _set("phase_recruit", 1.0 if obs.phase == PHASE_RECRUIT else 0.0)
        _set("phase_choice", 1.0 if obs.phase == PHASE_CHOICE else 0.0)
        _set("phase_game_over", 1.0 if obs.phase == PHASE_GAME_OVER else 0.0)
        _set("num_candidates", min(float(len(obs.candidates or ())), 64.0) / 64.0)
        _set("tavern_tier_max",
             min(float(hero.tavern_tier_max if hero else 6), 6.0) / 6.0)
        lobby = [p for p in (obs.lobby or ()) if p.alive]
        if lobby:
            hp = [float(p.health) for p in lobby]
            _set("lobby_mean_health", min(sum(hp) / len(hp), 40.0) / 40.0)
            _set("lobby_min_health", min(min(hp), 40.0) / 40.0)
            _set("lobby_alive_frac", min(len(lobby), 8.0) / 8.0)
        _set("no_hero", 1.0 if hero is None else 0.0)
        _set("board_power", min(board_atk + board_health, 200.0) / 200.0)
        _set("best_tavern_tier",
             min(max((float(t.tier) for t in tavern), default=0.0), 6.0) / 6.0)
        _set("mean_board_tier",
             min(sum(float(t.tier) for t in board) / max(len(board), 1), 6.0) / 6.0)
        return g


# ══════════════════════════════════════════════════════════════════════
# batch 化工具
# ══════════════════════════════════════════════════════════════════════


def _kind_value(kind: Any) -> str:
    """``ActionKind`` / ``str`` 统一成 str。"""
    return getattr(kind, "value", kind) if not isinstance(kind, str) else kind


def stack_encoded(encoded_list: Sequence[Dict[str, np.ndarray]]) -> Dict[str, np.ndarray]:
    """把已编码样本堆叠成 numpy batch（第 0 维 = batch）。"""
    if not encoded_list:
        raise ValueError("stack_encoded: 空列表")
    out: Dict[str, np.ndarray] = {}
    for key in ENCODED_KEYS:
        out[key] = np.stack([sample[key] for sample in encoded_list], axis=0)
    return out


def to_torch(
    batch: Dict[str, np.ndarray],
    device: Any = None,
    dtype: Any = None,
) -> Dict[str, Any]:
    """numpy batch → torch 张量字典（整数 key 保持 int64，其余 float32）。"""
    import torch  # 延迟导入：纯 numpy 使用场景不必装 torch

    int_keys = {
        "entity_card",
        "entity_zone",
        "entity_pos",
        "cand_kind",
        "cand_src",
        "cand_tgt",
    }
    out: Dict[str, Any] = {}
    for key, arr in batch.items():
        if key in int_keys:
            t = torch.as_tensor(np.ascontiguousarray(arr, dtype=np.int64))
        else:
            t = torch.as_tensor(
                np.ascontiguousarray(arr, dtype=np.float32 if dtype is None else dtype)
            )
        if device is not None:
            t = t.to(device)
        out[key] = t
    return out


def move_batch_to(batch: Dict[str, Any], device: Any) -> Dict[str, Any]:
    """把 batch 字典里的张量搬到 device（numpy 输入就地转 torch）。"""
    import torch

    out: Dict[str, Any] = {}
    for key, value in batch.items():
        if torch.is_tensor(value):
            out[key] = value.to(device, non_blocking=True)
        else:
            out[key] = value
    return out


def batch_size(batch: Dict[str, Any]) -> int:
    """从 batch 字典推断 batch 大小。"""
    for key in ("global", "entity_card", "cand_mask"):
        if key in batch:
            return int(batch[key].shape[0])
    raise KeyError("batch 缺少可推断 batch 大小的 key")


def candidate_counts(batch: Dict[str, Any]) -> np.ndarray:
    """每个样本的有效候选数量。"""
    mask = batch["cand_mask"]
    return np.asarray(mask).sum(axis=-1).astype(np.int64)


__all__ = [
    "CardVocab",
    "ObservationEncoder",
    "EncoderDims",
    "ENCODER_DIMS",
    "ENCODED_KEYS",
    "NUM_ENTITIES",
    "ENTITY_LAYOUT",
    "ZONE_OFFSET",
    "ZONE_SLOTS",
    "MAX_ZONE_SLOTS",
    "ENTITY_NUM_DIM",
    "GLOBAL_DIM",
    "GLOBAL_FEATURE_NAMES",
    "GLOBAL_FEATURE_INDEX",
    "CAND_NUM_DIM",
    "CAND_FEATURE_OFFSET",
    "ENTITY_FEATURE_OFFSET",
    "CARD_TYPES",
    "CARD_TYPE_INDEX",
    "ZONE_INDEX",
    "PAD_CARD_INDEX",
    "UNK_CARD_INDEX",
    "SPECIAL_TOKENS",
    "entity_index",
    "collect_card_ids",
    "stack_encoded",
    "to_torch",
    "move_batch_to",
    "batch_size",
    "candidate_counts",
]
