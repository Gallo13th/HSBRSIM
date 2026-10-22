"""共享池 — draw/return 严格配对，全审计。

旧引擎三大泄漏（v2 修复目标 P1/P8）:
  1. 刷新丢弃的酒馆随从不回池 → 池单调枯竭
  2. 玩家淘汰后卡牌不返还池
  3. Discover 不查池剩余量、选中不从池移除

v2 约定:
  - pool.available(card_id) 是所有获取路径（酒馆/发现/随机获取）的唯一闸门
  - acquire(card_id) 原子操作: 检查并扣减
  - release(card_id, n) 回池
  - purge(card_id) **永久**移除（Emergency Landing 族; 本局不可逆，
    `release`/`ensure_available` 均拒绝回池，RULES §2.3）
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
        # 池注入的当前池外随从（异变 "Cap'n Hoggarr is in the minion
        # pool" 类）——注入后参与抽取；回池仅在注入有效期内成立
        self._injected: set = set()
        # **永久移除**的卡（Emergency Landing `BG31_Anomaly_117` 族）:
        # purge 后不再进入池——`available` 恒 0、`candidates` 不列出、
        # `release`/`ensure_available` 拒绝回池（"permanently" 语义）
        self._purged: set = set()

    # ── 查询 ──

    def available(self, card_id: str) -> int:
        if card_id in self._purged:
            return 0
        return self._available.get(card_id, 0)

    def is_purged(self, card_id: str) -> bool:
        """该卡是否已被永久移出池（不可再获得副本）。"""
        return card_id in self._purged

    def total_remaining(self) -> int:
        return sum(self._available.values())

    def _race_ok(self, d: "CardDef") -> bool:
        if self.active_races is None:
            return True
        if d.race in (Race.NONE,):
            return True   # 无种族随从永远可用
        if d.race == Race.ALL:
            return True   # 全种族随从永远可用
        # 类型身份集合（AC-3）——双类型随从只需**任一**类型在当局即可
        # 入池（wiki `Multi-type minion` revid 855346 "Multi-types are
        # always additions, never exclusions."）。
        return bool(d.races & self.active_races)

    def candidates(self, max_tier: int, min_tier: int = 1,
                   races: Optional[set] = None,
                   keywords: Optional[set] = None,
                   tiers: Optional[set] = None,
                   race_of=None) -> List[str]:
        """按剩余副本 > 0 的实体定义枚举候选。

        以 `_available` 为准（而非 `db.pool_minions()`）——这样
        `ensure_available` 注入的池外随从（Cap'n Hoggarr）也能被抽到。

        `tiers` = **存在档白名单**（异变 101/102 "Only Tavern Tiers …
        exist."）; None = 不过滤（标准局沿用连续区间语义）。非存在档的
        随从在当局不存在，故不得成为任何抽取/展示候选。

        `race_of` = 可选 `CardDef -> frozenset[Race]`，给出**该英雄视角**
        的类型身份（含家族类型改写，`Game.effective_races`）。默认 None →
        数据身份 `CardDef.races`。
        """
        out: List[str] = []
        for card_id, n in self._available.items():
            if n <= 0 or card_id in self._purged:
                continue
            d = self.db.get(card_id)
            if d is None or d.card_type != CardType.MINION:
                continue
            if not (min_tier <= d.tech_level <= max_tier):
                continue
            if tiers is not None and d.tech_level not in tiers:
                continue
            if not self._race_ok(d):
                continue
            if races is not None:
                identity = race_of(d) if race_of is not None else d.races
                # 集合语义: `races` 白名单与身份集合相交即命中。旧调用方
                # 常把 `Race.ALL` 塞进白名单（`refresh_tavern` 的
                # `race_filter`）——ALL 已在身份集合中展开为全 10 族，
                # 白名单里的 ALL 不再需要; 但仍保留旧哨兵语义
                # （`races == {Race.ALL}` 时只命中 ALL 本体）。
                allow = set(races)
                all_def_ok = Race.ALL in allow
                allow.discard(Race.ALL)
                if (not (identity & allow)
                        and not (all_def_ok and d.race == Race.ALL)):
                    continue
            # 关键词白名单（"Refresh with **Battlecry** minions" /
            # "offers an extra **Magnetic** Mech"——743/755）
            if keywords is not None and not (d.keywords & keywords):
                continue
            out.append(card_id)
        return out

    # ── 原子获取/回池 ──

    def ensure_available(self, card_id: str, copies: int = 1) -> bool:
        """池注入: 保证 card_id 有可用副本（异变 Only Pirates "Cap'n
        Hoggarr is in the minion pool"）。

        允许**当前池外**的随从（BGS_072 已退出 36.2 池定义，但该异变
        明示其存在于池中）——token（tech_level≤0）不可注入。
        """
        if card_id in self._purged:
            return False          # 永久移除的卡不可注入
        if self._available.get(card_id, 0) > 0:
            return True
        d = self.db.get(card_id)
        if d is None or d.card_type != CardType.MINION or d.tech_level <= 0:
            return False
        self._available[card_id] = copies
        self._injected.add(card_id)
        return True

    def purge(self, card_id: str) -> int:
        """**永久移除**该卡在池中的全部剩余副本（Emergency Landing 族）。

        "Permanently remove all copies of it from your pool"（Eject!
        `BG31_Anomaly_117t`）——与 `acquire`/`release` 的临时扣减不同:
        被 purge 的卡从此**不再进入池**（`available` 恒 0、`candidates`
        不列出、`release`/`ensure_available` 拒绝回池），本局不可逆。

        返回移除的剩余副本数（观测/测试用）。已抽出的副本（酒馆展示位
        / 棋盘 / 手牌）不受影响——它们不在池内；其后续 `release`
        （出售/淘汰）亦被拒绝，故不会回归池。

        未知 id / 非随从卡不在池记账域 → 返回 0 且**不标记**（幂等，
        不报错）; 剩余副本本已为 0 的已知随从卡照常标记（"permanently"
        必须覆盖"当前恰好抽干"的卡）。
        """
        d = self.db.get(card_id)
        if d is None or d.card_type != CardType.MINION:
            return 0
        removed = self._available.pop(card_id, 0)
        self._purged.add(card_id)
        self._injected.discard(card_id)
        return removed

    def acquire(self, card_id: str) -> bool:
        """检查剩余并扣减。所有获取路径必须走这里。"""
        if card_id in self._purged:
            return False
        if self._available.get(card_id, 0) <= 0:
            return False
        self._available[card_id] -= 1
        if self._available[card_id] == 0:
            del self._available[card_id]
        return True

    def release(self, card_id: str, copies: int = 1) -> None:
        if card_id in self._purged:
            return   # 永久移除 → 不回池
        d = self.db.get(card_id)
        if d is None or d.card_type != CardType.MINION:
            return   # token 不回池
        if not d.is_pool_minion and card_id not in self._injected:
            return   # 池外卡（未注入态）不回池
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
                    min_tier: int = 1,
                    races: Optional[set] = None,
                    keywords: Optional[set] = None,
                    tiers: Optional[set] = None,
                    race_of=None) -> List[str]:
        """按池内剩余量加权抽取 count 张（剩余越少概率越低, RULES §2.4）。

        `tiers` 透传 `candidates` 的存在档白名单（异变 101/102）。
        `race_of` 透传 `candidates` 的英雄视角类型身份（家族改写）。
        """
        # 权重抽取: 每个候选按其剩余副本数加权
        drawn: List[str] = []
        for _ in range(count):
            cands = self.candidates(tier, min_tier, races=races,
                                    keywords=keywords, tiers=tiers,
                                    race_of=race_of)
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

    def ensure_available(self, card_id: str) -> bool:
        """池注入: 保证 card_id 有可用副本（异变 Only Pirates "Cap'n
        Hoggarr is in the pool"——不在池定义时按 1 份注入）。"""
        if self._available.get(card_id, 0) > 0:
            return True
        d = self.db.get(card_id)
        if d is None or not d.is_pool_spell:
            return False
        self._available[card_id] = 1
        return True

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

    def draw_tavern(self, tier: int, count: int,
                    tiers: Optional[set] = None) -> List[str]:
        """酒馆法术: ≤ 当前 tier，按剩余副本加权（同随从池语义）。

        `tiers` = 存在档白名单（异变 101/102——酒馆法术的 Tier 即
        Tavern Tier）; None = 不过滤。
        """
        drawn = []
        for _ in range(count):
            cands = [
                d.id for d in self.db.pool_spells()
                if d.tech_level <= tier and self._available.get(d.id, 0) > 0
                and (tiers is None or d.tech_level in tiers)
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
