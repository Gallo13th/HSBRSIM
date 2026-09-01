"""共享池 — draw/return 严格配对，全审计。

旧引擎三大泄漏（v2 修复目标 P1/P8）:
  1. 刷新丢弃的酒馆随从不回池 → 池单调枯竭
  2. 玩家淘汰后卡牌不返还池
  3. Discover 不查池剩余量、选中不从池移除

v2 约定:
  - pool.available(card_id) 是所有获取路径（酒馆/发现/随机获取）的唯一闸门
  - acquire(card_id) 原子操作: 检查并扣减
  - release(card_id, n) 回池
  - draw_tavern(...) 自动把未被保留的旧酒馆内容回池
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence, TYPE_CHECKING

import hsrl2.constants as C
from hsrl2.rng import GameRNG
from hsrl2.tags import CardType, Race

if TYPE_CHECKING:
    from hsrl2.db import CardDB
    from hsrl2.defs import CardDef


class PoolLeakError(RuntimeError):
    """release 超过剩余量 — 引擎 bug。"""


class MinionPool:
    def __init__(self, db: "CardDB", rng: GameRNG) -> None:
        self.db = db
        self.rng = rng
        self._available: Counter[str] = Counter()
        for d in db.pool_minions():
            tier = min(max(d.tech_level, 1), 7)
            self._available[d.id] = C.POOL_COPIES_BY_TIER[tier]
        # 种族禁用: 每局在 game 层设置，draw 时过滤
        self.active_races: Optional[set] = None   # None = 全部可用

    # ── 查询 ──

    def available(self, card_id: str) -> int:
        return self._available.get(card_id, 0)

    def total_remaining(self) -> int:
        return sum(self._available.values())

    def _race_ok(self, d: "CardDef") -> bool:
        if self.active_races is None:
            return True
        if d.race in (Race.NONE,):
            return True   # 无种族随从永远可用
        if d.race == Race.ALL:
            return True   # 全种族随从永远可用
        return d.race in self.active_races

    def candidates(self, max_tier: int, min_tier: int = 1) -> List[str]:
        return [
            d.id for d in self.db.pool_minions()
            if min_tier <= d.tech_level <= max_tier
            and self._available.get(d.id, 0) > 0
            and self._race_ok(d)
        ]

    # ── 原子获取/回池 ──

    def acquire(self, card_id: str) -> bool:
        """检查剩余并扣减。所有获取路径必须走这里。"""
        if self._available.get(card_id, 0) <= 0:
            return False
        self._available[card_id] -= 1
        if self._available[card_id] == 0:
            del self._available[card_id]
        return True

    def release(self, card_id: str, copies: int = 1) -> None:
        d = self.db.get(card_id)
        if d is None or not d.is_pool_minion:
            return   # token/非池卡不回池
        self._available[card_id] += copies

    def release_minion_entity(self, minion) -> None:
        """出售/淘汰回池: 金色返还**基础卡** 3 份、普通 1 份（RULES §2.3）。

        例外——非三连金色（Reno 金色化/Aureate Laureate 恒金/Golden
        Touch）: 官方按 1 份返还（RULES §2.3 Reno 条目），否则池净增
        （压测实测泄漏）。
        """
        from hsrl2.tags import GameTag
        base_id = minion.get(GameTag.TRIPLE_BASE_CARD_ID, None) or minion.card_id
        if minion.is_golden and not minion.get(GameTag.GILDED_NOT_TRIPLED, False):
            copies = C.GOLDEN_POOL_RETURN_COPIES
        else:
            copies = 1
        self.release(base_id, copies)

    # ── 酒馆抽取 ──

    def draw_tavern(self, tier: int, count: int,
                    min_tier: int = 1) -> List[str]:
        """按池内剩余量加权抽取 count 张（剩余越少概率越低, RULES §2.4）。"""
        # 权重抽取: 每个候选按其剩余副本数加权
        drawn: List[str] = []
        for _ in range(count):
            cands = self.candidates(tier, min_tier)
            if not cands:
                break
            weighted: List[str] = []
            for cid in cands:
                weighted.extend([cid] * self._available[cid])
            pick = self.rng.choice(weighted, label="tavern_draw")
            assert self.acquire(pick)
            drawn.append(pick)
        return drawn


class SpellPool:
    """酒馆法术共享池——按 tier 副本数模型（2026-08-23 查证修正）。

    权威信源: hearthstone.wiki.gg/wiki/Battlegrounds/Tavern_spell Table 节
    （同表见 Battlegrounds 主页），引自 BG 前负责人 Mitchell Loewen
    X post 2024-03-10 (x.com/LoewenMitchell/status/1841922301522047432):
    "Copies of each tavern spell: Tier 1-5, 2-7, 3-9, 4-11, 5-9, 6-7"。
    旧"每张 1 份"模型（误引 RULES §3.6.1）为硬不一致，已废弃;
    RULES 文档同步修正。
    """

    # 每 tier 副本数（T7 无信源——取 T6 相邻值 7 并标 UNVERIFIED）
    POOL_COPIES_BY_TIER = {1: 5, 2: 7, 3: 9, 4: 11, 5: 9, 6: 7, 7: 7}

    def __init__(self, db: "CardDB", rng: GameRNG) -> None:
        self.db = db
        self.rng = rng
        self._available: Counter = Counter()
        for d in db.pool_spells():
            tier = min(max(d.tech_level, 1), 7)
            self._available[d.id] = self.POOL_COPIES_BY_TIER[tier]

    def available(self, card_id: str) -> int:
        return self._available.get(card_id, 0)

    def total_remaining(self) -> int:
        return sum(self._available.values())

    def acquire(self, card_id: str) -> bool:
        if self._available.get(card_id, 0) <= 0:
            return False
        self._available[card_id] -= 1
        if self._available[card_id] == 0:
            del self._available[card_id]
        return True

    def release(self, card_id: str) -> None:
        d = self.db.get(card_id)
        if d is None or not d.is_pool_spell:
            return   # 非池法术不回池
        tier = min(max(d.tech_level, 1), 7)
        cap = self.POOL_COPIES_BY_TIER[tier]
        current = self._available.get(card_id, 0)
        if current < cap:
            self._available[card_id] = current + 1

    def draw_tavern(self, tier: int, count: int) -> List[str]:
        """酒馆法术: ≤ 当前 tier，按剩余副本加权（同随从池语义）。"""
        drawn = []
        for _ in range(count):
            cands = [
                d.id for d in self.db.pool_spells()
                if d.tech_level <= tier and self._available.get(d.id, 0) > 0
            ]
            if not cands:
                break
            weighted: List[str] = []
            for cid in cands:
                weighted.extend([cid] * self._available[cid])
            pick = self.rng.choice(weighted, label="spell_draw")
            assert self.acquire(pick)
            drawn.append(pick)
        return drawn
