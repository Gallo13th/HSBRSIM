"""复利链条**核心牌先验**（训练/采集期的软偏置，**默认关**）。

动机
====
用户洞察（见 ``docs/COMPOUND_CHAINS.md``）：酒馆战棋的强度来自**复利链条**——
「乘数效应」（``double`` / ``twice`` / ``for each`` / ``each time``）与「几何级数/累加」
（``permanently`` / ``this game`` / ``an extra +1/+1`` / ``consume`` / ``grow``）。
``scripts/mine_compound_cards.py`` 已经从卡牌文本里挖出这些牌并按流派整理成
**核心牌集**（``data/scaling/compound_cards.json`` 的 ``core.by_tribe`` /
``core.by_archetype`` / ``core.global`` + ``common_ids``）。

本模块把这份先验变成**动作 logit 上的偏置**：

- ``coef = --compound-prior-coef``（默认 0）：买/选到「**当前流派**的核心牌」时
  ``+coef``（**只加不减**，不屏蔽任何动作）；
- ``penalty = --archetype-background-penalty``（默认 0）：买/选到「**其他流派**的核心牌」
  时 ``-penalty`` —— 把非公用牌拉到背景权重（``common_ids`` 里的公用牌/融合怪**永不惩罚**）。

两条都是**软**偏置：动作集合、mask、观测都不变，PPO 仍可自由偏离。``coef=0 且
penalty=0`` 时不构造任何对象 → 与旧路径**逐位等价**。

流派判定（优先级）
==================
1. ``archetype`` 参数显式指定（``"beast"`` / ``"demon_boost_shop"``，评测/受控实验用）；
2. 现有两段式分类器 ``data/archetype/archetype_model.npz``（与
   :mod:`hsbg.az.train.archetype_bias` **共用**同一套特征构造
   :func:`parse_obs` / :class:`ArchetypeHistory`）：``max(p_arch) >= min_prob`` 且非
   ``other`` → 头部流派；否则 ``max(p_tribe) >= min_prob`` → 种族族；
3. 退化：**场上/手牌最多种族**（只看己方观测，无模型也能跑）。

偏置落点（动作空间）
====================
- ``Buy 8..15``：酒馆槽位的卡 id（``cards[SLICE_CARD_SHOP]``）；
- ``Choose 30..45``：发现/抉择/饰品选项的卡 id（``cards[SLICE_CARD_CHOICES]``）；
- 其它动作（升 tier / roll / 卖 / 换位 / EndTurn）**不偏置**——先验只管「买什么」，
  节奏由 PPO 自己学（``archetype_bias`` 那套偏好表仍负责节奏）。

泄漏边界
========
只用**本座位**的 ``observe(seat)`` 数组（features / cards / mask）+ 己方历史动作 +
离线挖出来的卡表。禁止对手手牌、本局结果、评测面板。``card_index_of`` 是引擎的
卡牌下标 → 卡 id（``hsbg_engine.card_info``）。

统计（meta）
============
:meth:`CompoundPrior.to_meta` 输出 ``compound_prior`` / ``compound_coef`` /
``compound_detected`` / ``compound_pos_actions`` / ``compound_neg_actions`` /
``compound_archetype`` 等字段，聚合用 :func:`aggregate_compound_prior`。

确定性
======
``bias()`` 是 ``(features, cards, mask, 历史修订号)`` 的纯函数（无随机、无时间）；
同一输入两次调用逐位相同（见 ``tests/test_compound_prior.py``）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

from hsbg.env.action_space_std import (
    A_BUY,
    A_CHOOSE,
    N_CHOICE,
    N_SHOP,
)
from hsbg.env.obs_std import (
    N_ACTIONS,
    OBS_CARDS,
    SLICE_CARD_CHOICES,
    SLICE_CARD_SHOP,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
DEFAULT_COMPOUND = os.path.join(ROOT, "data", "scaling", "compound_cards.json")
DEFAULT_TABLE = os.path.join(ROOT, "data", "archetype", "archetype_table.json")
DEFAULT_MODEL = os.path.join(ROOT, "data", "archetype", "archetype_model.npz")

#: 单动作 bias 上限（× coef / penalty）；买/选每个槽位最多一张卡，所以通常就是 ±1。
MAX_TOTAL = 1.0


# ══════════════════════════════════════════════════════════════════════════
# 1. 核心牌集（读 compound_cards.json）
# ══════════════════════════════════════════════════════════════════════════
def load_compound(path: str = DEFAULT_COMPOUND) -> Dict[str, Any]:
    """读 ``compound_cards.json`` 并校验关键字段（缺字段直接报错，不静默兜底）。"""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError(f"复利卡表格式非法（不是 dict）: {path}")
    core = d.get("core")
    if not isinstance(core, dict) or not core.get("by_tribe"):
        raise ValueError(f"复利卡表缺 core.by_tribe: {path}（先跑 "
                         f"python scripts/mine_compound_cards.py）")
    return d


@dataclass
class CoreSets:
    """核心牌集（已展开成 ``id -> 元信息``，便于 O(1) 判定）。"""

    by_tribe: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    by_archetype: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    global_ids: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    common_ids: set = field(default_factory=set)
    #: 所有组里出现过的 id（背景惩罚的候选池）
    all_ids: set = field(default_factory=set)

    def core_of(self, name: str) -> Optional[Dict[str, Dict[str, Any]]]:
        """按名字取核心集：先头部流派，再种族（大小写不敏感），否则 ``None``。"""
        if not name:
            return None
        n = str(name)
        if n in self.by_archetype:
            return self.by_archetype[n]
        for key in (n.upper(), n.lower(), n):
            if key in self.by_tribe:
                return self.by_tribe[key]
        return None

    def names(self) -> Dict[str, List[str]]:
        return {"tribes": sorted(self.by_tribe),
                "archetypes": sorted(self.by_archetype)}


def build_core_sets(payload: Dict[str, Any]) -> CoreSets:
    """``compound_cards.json`` → :class:`CoreSets`（``core.by_x`` 的 list → dict）。"""
    core = payload.get("core") or {}
    cs = CoreSets()
    for tribe, rows in (core.get("by_tribe") or {}).items():
        cs.by_tribe[str(tribe)] = {str(x["id"]): dict(x) for x in rows}
    for arch, node in (core.get("by_archetype") or {}).items():
        cs.by_archetype[str(arch)] = {str(x["id"]): dict(x)
                                     for x in (node.get("core") or ())}
    cs.global_ids = {str(x["id"]): dict(x) for x in (core.get("global") or ())}
    cs.common_ids = {str(x) for x in (core.get("common_ids") or ())}
    all_ids = set(cs.global_ids)
    for rows in cs.by_tribe.values():
        all_ids |= set(rows)
    for rows in cs.by_archetype.values():
        all_ids |= set(rows)
    cs.all_ids = all_ids
    return cs


# ══════════════════════════════════════════════════════════════════════════
# 2. 观察解析（与 archetype_bias 共用口径）
# ══════════════════════════════════════════════════════════════════════════
def _lazy_ab():
    """惰性导入 :mod:`archetype_bias`（避免无 numpy/模型时拖慢 import）。"""
    from hsbg.az.train import archetype_bias as AB
    return AB


def shop_card_slots(cards: Any) -> List[str]:
    """观测 cards 块 → 8 个酒馆槽位的卡 id 下标（``0`` = 空）。"""
    c = np.asarray(cards).reshape(-1)
    out: List[str] = []
    for slot in range(N_SHOP):
        try:
            idx = int(c[SLICE_CARD_SHOP.start + slot])
        except Exception:  # noqa: BLE001 - cards 维度不足：按空槽处理
            idx = 0
        out.append(str(idx) if idx > 0 else "")
    return out


def choose_option_slots(cards: Any) -> List[str]:
    """观测 cards 块 → 16 个 Choose 选项的卡 id 下标（``0`` = 空）。"""
    c = np.asarray(cards).reshape(-1)
    out: List[str] = []
    for j in range(N_CHOICE):
        try:
            idx = int(c[SLICE_CARD_CHOICES.start + j])
        except Exception:  # noqa: BLE001
            idx = 0
        out.append(str(idx) if idx > 0 else "")
    return out


def majority_tribe(features: Any) -> str:
    """**退化**流派判定：场上（权重 2）+ 手牌（权重 1）出现最多的种族 → ``"BEAST"`` 等。

    没有任何种族信息时返回 ``""``（调用方退回 ``core.global``）。
    """
    AB = _lazy_ab()
    obs = AB.parse_obs(features, np.zeros(OBS_CARDS, dtype=np.int64))
    score = np.asarray(obs.board_tribes, dtype=np.float64) * 2.0 + \
        np.asarray(obs.hand_tribes, dtype=np.float64).sum(axis=0)
    if float(score.max()) <= 0.0:
        return ""
    i = int(np.argmax(score))
    return str(AB.TRIBES[i]).upper()


# ══════════════════════════════════════════════════════════════════════════
# 3. 统计
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class CompoundPriorStats:
    decisions: int = 0          #: 跑过偏置器的决策数
    detected: int = 0           #: 流派判定成功的决策数（含 forced/fallback）
    applied: int = 0            #: 至少给一个动作加了 bias 的决策数
    pos_actions: int = 0        #: 拿到正 bias 的 (决策, 动作位) 数
    neg_actions: int = 0        #: 拿到负 bias 的 (决策, 动作位) 数
    bias_sum: float = 0.0
    lvl_forced: int = 0
    lvl_archetype: int = 0
    lvl_tribe_model: int = 0
    lvl_majority: int = 0
    lvl_global: int = 0
    name_counts: Dict[str, int] = field(default_factory=dict)

    def add(self, other: "CompoundPriorStats") -> None:
        self.decisions += int(other.decisions)
        self.detected += int(other.detected)
        self.applied += int(other.applied)
        self.pos_actions += int(other.pos_actions)
        self.neg_actions += int(other.neg_actions)
        self.bias_sum += float(other.bias_sum)
        self.lvl_forced += int(other.lvl_forced)
        self.lvl_archetype += int(other.lvl_archetype)
        self.lvl_tribe_model += int(other.lvl_tribe_model)
        self.lvl_majority += int(other.lvl_majority)
        self.lvl_global += int(other.lvl_global)
        for k, v in (other.name_counts or {}).items():
            self.name_counts[str(k)] = self.name_counts.get(str(k), 0) + int(v)


def _top_name(counts: Dict[str, int]) -> str:
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))[0][0]


# ══════════════════════════════════════════════════════════════════════════
# 4. 偏置器
# ══════════════════════════════════════════════════════════════════════════
class CompoundPrior:
    """核心牌先验：流派判定 → 核心牌集 → 买/选动作的非对称 logit 偏置。

    ``coef<=0 且 penalty<=0`` 时构造出来也不做事（:attr:`enabled` = False，
    :meth:`bias` 恒返回 ``None``）；生产路径上**不构造**本对象即逐位等价旧行为。
    """

    def __init__(self, *, coef: float = 0.0, background_penalty: float = 0.0,
                 compound_path: str = DEFAULT_COMPOUND,
                 table_path: str = DEFAULT_TABLE,
                 model_path: str = DEFAULT_MODEL,
                 archetype: str = "",
                 min_prob: float = 0.6,
                 max_bias: float = MAX_TOTAL,
                 scale_by_score: bool = False,
                 use_model: bool = True,
                 card_index_of: Optional[Callable[[int], str]] = None) -> None:
        self.coef = max(0.0, float(coef))
        self.penalty = max(0.0, float(background_penalty))
        self.enabled = bool(self.coef > 0.0 or self.penalty > 0.0)
        self.compound_path = str(compound_path)
        self.table_path = str(table_path)
        self.model_path = str(model_path)
        self.forced = str(archetype or "")
        self.min_prob = float(min_prob)
        self.max_bias = float(max_bias)
        self.scale_by_score = bool(scale_by_score)
        self._payload = load_compound(compound_path) if self.enabled else {}
        self.core = build_core_sets(self._payload) if self.enabled else CoreSets()
        self.stats = CompoundPriorStats()
        self._card_index_of = card_index_of
        self._card_cache: Dict[int, str] = {}
        #: 分类器（缺失时自动退化到「场上/手牌最多种族」）
        self._tribe_model = None
        self._arch_model = None
        self._hero_vocab: List[str] = []
        self._hero_index: Dict[str, int] = {}
        self._hist = None
        self.detector_ok = False
        #: ``detect`` 的幂等键（同一输入不重复写历史）
        self._last_key: Any = None
        if self.enabled and bool(use_model) and not self.forced:
            try:
                AB = _lazy_ab()
                tribe, arch, hero_vocab, _meta = AB.load_models(self.model_path)
                self._tribe_model, self._arch_model = tribe, arch
                self._hero_vocab = list(hero_vocab)
                self._hero_index = {str(h): i for i, h in enumerate(self._hero_vocab)}
                self._hist = AB.ArchetypeHistory()
                self.detector_ok = True
            except Exception:  # noqa: BLE001 - 模型缺失/版本不符：退化到最多种族
                self.detector_ok = False
                self._hist = None

    # -- 卡 id 解析 ---------------------------------------------------------
    def card_id_of(self, index: Any) -> str:
        i = int(index)
        got = self._card_cache.get(i)
        if got is not None:
            return got
        cid = ""
        if self._card_index_of is not None:
            try:
                cid = str(self._card_index_of(i) or "")
            except Exception:  # noqa: BLE001
                cid = ""
        self._card_cache[i] = cid
        return cid

    # -- 生命周期 -----------------------------------------------------------
    def reset(self) -> None:
        if self._hist is not None:
            self._hist.reset()
        self.stats = CompoundPriorStats()

    def clear_state(self) -> None:
        """清逐局历史、保留累计统计（每局开始复用同一个偏置器时调用）。"""
        if self._hist is not None:
            self._hist.clear_state()

    def note_action(self, action: Any, *, game_id: Any, seat: Any) -> None:
        """记录己方实际动作（分类器的历史特征用；与 archetype_bias 同口径）。"""
        if self._hist is not None:
            self._hist.note_action(game_id, seat, action)

    # -- 流派判定 -----------------------------------------------------------
    def detect(self, features: Any, cards: Any, *, game_id: Any = 0,
               seat: Any = 0) -> Tuple[str, float, str]:
        """→ ``(流派名, 置信度, 来源)``；来源 ∈ forced/archetype/tribe_model/majority/global。

        幂等：同一 ``(game_id, seat, features, cards)`` 重复调用**不会**重复写历史
        （``ArchetypeHistory.observe`` 只在输入指纹变化时执行），因此
        :meth:`bias` 对同一决策重复调用逐位相同（单测覆盖）。
        """
        if self.forced:
            return self.forced, 1.0, "forced"
        if self.detector_ok and self._hist is not None:
            AB = _lazy_ab()
            obs = AB.parse_obs(features, cards, hero_id_of=self.card_id_of)
            f32 = np.asarray(features, dtype=np.float32)
            key = (int(game_id), int(seat), hash(f32.tobytes()),
                   hash(np.asarray(cards).astype(np.int64).tobytes()))
            if key != self._last_key:
                self._hist.observe(game_id, seat, obs)
                self._last_key = key
            try:
                x = self._hist.vector(game_id, seat, obs, hero_vocab=self._hero_vocab,
                                      hero_index=self._hero_index)
                p_a = self._arch_model.probs(x)[0]
                p_t = self._tribe_model.probs(x)[0]
                i_a, i_t = int(np.argmax(p_a)), int(np.argmax(p_t))
                name_a = str(self._arch_model.classes[i_a])
                prob_a = float(p_a[i_a])
                name_t = str(self._tribe_model.classes[i_t])
                prob_t = float(p_t[i_t])
                if name_a != "other" and prob_a >= self.min_prob \
                        and self.core.core_of(name_a) is not None:
                    return name_a, prob_a, "archetype"
                if prob_t >= self.min_prob and self.core.core_of(name_t) is not None:
                    return name_t.upper(), prob_t, "tribe_model"
            except Exception:  # noqa: BLE001 - 分类器失败 → 退化
                pass
        tribe = majority_tribe(features) if self.core.by_tribe else ""
        if tribe and self.core.core_of(tribe) is not None:
            return tribe, 1.0, "majority"
        return "", 0.0, "global"

    # -- 主入口 -------------------------------------------------------------
    def _weight(self, meta: Dict[str, Any]) -> float:
        """单张核心牌的偏置幅度（flat=1.0；score 模式按分数归一）。"""
        if not self.scale_by_score:
            return 1.0
        top = max((float(x.get("score") or 0.0) for rows in self.core.by_tribe.values()
                   for x in rows.values()), default=0.0)
        s = float(meta.get("score") or 0.0)
        return float(min(1.0, s / top)) if top > 0.0 else 1.0

    def bias(self, features: Any, cards: Any, mask: Any, *, game_id: Any = 0,
             seat: Any = 0) -> Optional[np.ndarray]:
        """当前决策的 245 维 bias（无偏置返回 ``None``）；同时更新统计。

        只给**合法**的 Buy / Choose 位写值：命中所属流派核心牌 → ``+coef``；
        命中其它流派核心牌且**不在 ``common_ids``** → ``-penalty``。
        """
        if not self.enabled:
            return None
        self.stats.decisions += 1
        name, prob, level = self.detect(features, cards, game_id=game_id, seat=seat)
        core = self.core.core_of(name) if name else None
        if core is None:
            core = self.core.global_ids
            level = "global"
        if not core:
            self.stats.lvl_global += 1
            return None
        self.stats.detected += 1
        self.stats.lvl_forced += int(level == "forced")
        self.stats.lvl_archetype += int(level == "archetype")
        self.stats.lvl_tribe_model += int(level == "tribe_model")
        self.stats.lvl_majority += int(level == "majority")
        self.stats.lvl_global += int(level == "global")
        if name:
            self.stats.name_counts[str(name)] = self.stats.name_counts.get(str(name), 0) + 1

        bias = np.zeros(int(N_ACTIONS), dtype=np.float32)
        c = float(self.coef)
        p = float(self.penalty)
        in_core = set(core)
        others = (self.core.all_ids - in_core - self.core.common_ids) if p > 0.0 else set()

        def _hit(cid: str) -> Tuple[float, str]:
            """卡 id → (偏置, 'pos'|'neg'|'')。"""
            if not cid:
                return 0.0, ""
            if cid in core:
                if c <= 0.0:
                    return 0.0, ""
                return c * self._weight(core[cid]), "pos"
            if cid in others:
                return -p, "neg"
            return 0.0, ""

        # Buy 8..15（酒馆槽位）
        shop = shop_card_slots(cards)
        n_pos = n_neg = 0
        tot = 0.0
        for slot, raw in enumerate(shop):
            if not raw:
                continue
            cid = self.card_id_of(int(raw))
            v, kind = _hit(cid)
            if v == 0.0:
                continue
            bias[int(A_BUY) + slot] += float(v)
            tot += float(v)
            n_pos += int(kind == "pos")
            n_neg += int(kind == "neg")
        # Choose 30..45（发现/抉择/饰品选项）
        for j, raw in enumerate(choose_option_slots(cards)):
            if not raw:
                continue
            cid = self.card_id_of(int(raw))
            v, kind = _hit(cid)
            if v == 0.0:
                continue
            bias[int(A_CHOOSE) + j] += float(v)
            tot += float(v)
            n_pos += int(kind == "pos")
            n_neg += int(kind == "neg")

        # 非法位清零（本来会被 masked softmax 归零；清零让统计/单测口径干净）
        m = np.asarray(mask, dtype=bool).reshape(-1)
        if m.size != bias.size:
            raise ValueError(f"mask 维度 {m.size} != {bias.size}")
        bias[~m] = 0.0
        # 上限：正向 <= coef*MAX_TOTAL，负向 >= -penalty*MAX_TOTAL
        np.clip(bias, -p * self.max_bias, c * self.max_bias, out=bias)
        if n_pos or n_neg:
            self.stats.applied += 1
            self.stats.pos_actions += int(n_pos)
            self.stats.neg_actions += int(n_neg)
            self.stats.bias_sum += float(tot)
            return bias
        return None

    # -- meta ---------------------------------------------------------------
    def to_meta(self) -> Dict[str, Any]:
        s = self.stats
        return {
            "compound_prior": True,
            "compound_coef": float(self.coef),
            "compound_background_penalty": float(self.penalty),
            "compound_table": os.path.basename(self.compound_path),
            "compound_forced_archetype": str(self.forced),
            "compound_decisions": int(s.decisions),
            "compound_detected": int(s.detected),
            "compound_applied": int(s.applied),
            "compound_pos_actions": int(s.pos_actions),
            "compound_neg_actions": int(s.neg_actions),
            "compound_bias_sum": float(s.bias_sum),
            "compound_archetype": _top_name(s.name_counts),
            "compound_archetypes": {str(k): int(v) for k, v in
                                    sorted(s.name_counts.items())},
            "compound_level_forced": int(s.lvl_forced),
            "compound_level_archetype": int(s.lvl_archetype),
            "compound_level_tribe_model": int(s.lvl_tribe_model),
            "compound_level_majority": int(s.lvl_majority),
            "compound_level_global": int(s.lvl_global),
        }

    def summary(self) -> Dict[str, Any]:
        """启动期写进 history 的摘要（不含逐决策统计）。"""
        counts = (self._payload.get("meta") or {}).get("counts") or {}
        return {
            "coef": float(self.coef),
            "background_penalty": float(self.penalty),
            "forced": str(self.forced),
            "detector": ("forced" if self.forced else
                         ("model" if self.detector_ok else "majority")),
            "compound_path": self.compound_path,
            "n_tribes": len(self.core.by_tribe),
            "n_archetypes": len(self.core.by_archetype),
            "n_global": len(self.core.global_ids),
            "n_common": len(self.core.common_ids),
            "n_all_ids": len(self.core.all_ids),
            "cards_mined": int(counts.get("mined_total", 0) or 0),
        }


def aggregate_compound_prior(metas: Iterable[Any]) -> Dict[str, Any]:
    """把多 worker/多局的 ``to_meta()`` 汇总（没有任何条目时返回 ``{}``）。"""
    rows = [m for m in metas if isinstance(m, dict) and m.get("compound_prior")]
    if not rows:
        return {}
    first = rows[0]
    sum_keys = ("compound_decisions", "compound_detected", "compound_applied",
                "compound_pos_actions", "compound_neg_actions",
                "compound_level_forced", "compound_level_archetype",
                "compound_level_tribe_model", "compound_level_majority",
                "compound_level_global")
    out: Dict[str, Any] = {
        "compound_prior": True,
        "compound_coef": float(first.get("compound_coef", 0.0) or 0.0),
        "compound_background_penalty": float(
            first.get("compound_background_penalty", 0.0) or 0.0),
        "compound_forced_archetype": str(first.get("compound_forced_archetype", "") or ""),
        "compound_table": str(first.get("compound_table", "") or ""),
    }
    for key in sum_keys:
        out[key] = int(sum(int(m.get(key, 0) or 0) for m in rows))
    names: Dict[str, int] = {}
    for m in rows:
        for k, v in (m.get("compound_archetypes") or {}).items():
            names[str(k)] = names.get(str(k), 0) + int(v)
    out["compound_archetypes"] = names
    out["compound_archetype"] = _top_name(names)
    out["compound_bias_sum"] = float(sum(float(m.get("compound_bias_sum", 0.0) or 0.0)
                                        for m in rows))
    return out


def engine_card_id_lookup() -> Optional[Callable[[int], str]]:
    """``hsbg_engine.card_info`` → ``index -> card_id``（引擎缺失返回 ``None``）。"""
    try:
        import hsbg_engine as E  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    def _lookup(idx: int) -> str:
        try:
            return str(E.card_info(int(idx))[0] or "")
        except Exception:  # noqa: BLE001
            return ""

    return _lookup


def core_ids_for(name: str, *, path: str = DEFAULT_COMPOUND) -> List[str]:
    """便捷函数：取某个流派（种族/头部流派）的核心牌 id 列表（评测用）。"""
    cs = build_core_sets(load_compound(path))
    rows = cs.core_of(name)
    if rows is None:
        return sorted(cs.global_ids)
    return sorted(rows)


def all_core_ids(*, path: str = DEFAULT_COMPOUND) -> List[str]:
    cs = build_core_sets(load_compound(path))
    return sorted(cs.all_ids)


__all__ = [
    "DEFAULT_COMPOUND", "DEFAULT_TABLE", "DEFAULT_MODEL", "MAX_TOTAL",
    "load_compound", "CoreSets", "build_core_sets",
    "shop_card_slots", "choose_option_slots", "majority_tribe",
    "CompoundPriorStats", "CompoundPrior",
    "aggregate_compound_prior", "engine_card_id_lookup",
    "core_ids_for", "all_core_ids",
]
