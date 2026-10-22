"""批次 trinkets28 行为层测试（3 张注册饰品 + 15 张 DEFERRED 台账守卫,
作业单 2026-09-14）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线; 副本条款用
    `duplicate=True`）
  - 金币收入: `hero.gold` setter（回合收入经真实 `_begin_recruit_for` /
    真实 `game.sell_minion` / 真实 `GainGold` action 三条路径）
  - 刷新: 真实 `game.refresh_tavern`（主动）/ `_begin_recruit_for` 的
    `auto=True`（自动）/ 真实 `game.end_recruit_phase`（跨回合）
  - 交付: `game.grant_card_copy_to_hand`（金色独立卡定义 + 池记账 +
    满手入队）
  - 战斗: 真实 `game.run_combat` / `end_recruit_phase`，战斗内状态用
    `start_of_combat` 事件探针读取（SoC 钩子之后广播）；战后持久性读
    `hero.board[i]`（`Transform` 换实体，旧引用失效）

覆盖（SOP §16 空转测试判定法 + 作业单测试矩阵）:
  - 每个行为测试至少一条**正效果**断言，且负/正对照在**同一方法内**
    （350: 回合收入 / 售卖 / `GainGold` 三路径; 366: 主动 vs 自动刷新;
    419: 有/无饰品对照）;
  - owner 隔离（2 英雄，对手收入/对手刷新/对手龙不触发）;
  - 一次性（350 `Once per game`）/ 每回合（366 充能重置）/ 跨回合
    （真实 `end_recruit_phase`）;
  - 落空不消耗资源（350 Tier 5 池清空 → 不交付且不消耗 once;
    419 无龙 → 落空且池不变）;
  - 池占返配平（350 交付占池 1 份 + `GILDED_NOT_TRIPLED` 出售回池 1 份;
    419 金色化后出售回池 1 份）;
  - 满手队列（350 满手 → `pending_hand_queue` 入队金色副本）;
  - 两份副本（350 各交付一次 / 366 充能叠加 / 419 各金色化一只）;
  - 同 seed 确定性（三张卡各一条）;
  - 禁止弱断言: 断言 `assertEqual` 钉死身份/数值/Tier 集合。

作业单测试矩阵中**不适用**的条目（本批三张卡的效果域决定）:
  - `len(options) == N`（Discover 选项数）: 350 是 `game.rng` 随机获取
    （无选项集），366/419 无发现——均不产生 `PendingChoice`;
  - 双施（`SPELL_DOUBLER` / `spell_first`）与 Titus（亡语翻倍）: 三张卡
    都不施放法术、不产生亡语——不适用。
  上述两条已在模块 docstring 留档，而非以空转测试冒充覆盖。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.economy import GainGold
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 本批 id（CardDB 按名核实——禁止凭记忆写）
SPLINTER_OF_AURUM = "BG32_MagicItem_350"
GUIDING_CANDLE = "BG32_MagicItem_366"
YULON_STICKER = "BG32_MagicItem_419"

CORRECT_IDS = [SPLINTER_OF_AURUM, GUIDING_CANDLE, YULON_STICKER]

# 971 Enforcer / 179 Drakkari Portrait 已由 batch_family_races 注册
# （2026-09-21，RACES 家族类型身份改写）→ 移出本 DEFERRED 台账
# （守卫见 test_batch_family_races）。
DEFERRED_IDS = [
    "BG30_MagicItem_994",   # Yogg-Tastic Pastry — Wheel of Yogg-Saron
    "BG32_MagicItem_300",   # Putricide Sticker — Craft 合成链
    "BG32_MagicItem_806",   # Battlecruiser Portrait — Upgrade 子系统
    "BG32_MagicItem_809",   # Gem Donation — "plays its Blood Gems" 无权威
]
# 已由 batch_trinkets30 注册（2026-09-15: PERSIST_BONUS_ONLY +
# PERSIST_COMBAT_CHANGES 战斗持久化通道）——迁出 DEFERRED 台账，
# 仍计入本批 18 张作业范围
MIGRATED_IDS = [
    "BG32_MagicItem_417",   # Tarecgosa Sticker
    "BG30_MagicItem_944",   # Redeemer Portrait（batch_trinkets33，2026-09-13）
    "BG32_MagicItem_274",   # Bristlebach Portrait（batch_trinkets34，2026-09-13）
    "BG32_MagicItem_804",   # Selfless Portrait（batch_trinkets35，2026-09-13）
    "BG32_MagicItem_803",   # Macaw Portrait（batch_trinkets36，2026-09-13）
    # A 组 4 张由 batch_trinkets31 注册（2026-09-19——owner 权威序:
    # wiki 页无 Notes → 卡面天然语言 "also give X" 增量 = 同句既有量）
    "BG30_MagicItem_868",   # Rewinder Portrait
    "BG30_MagicItem_869",   # Felblood Portrait
    "BG30_MagicItem_987",   # Balladist Portrait
    "BG32_MagicItem_283",   # Czarina Portrait
    # RACES 家族类型身份改写由 batch_family_races 注册（2026-09-21）
    "BG30_MagicItem_971",   # Enforcer Portrait
    "BG32_MagicItem_179",   # Drakkari Portrait
]

# 测试用随从（CardDB 数据核实 36.2.2）
T1_BEAST = "BG31_803"       # Buzzing Vermin 1/1 T1 野兽（池; 售卖填充）
DRAGON_T3 = "BG24_500"      # Amber Guardian T3 龙（池）
DRAGON_T6 = "BG24_004"      # Warpwing T6 龙（池）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 2801) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def num_of(card_id: str, index: int):
    return get_db().get(card_id).num(index)


def bind(game: Game, hero: Hero, tid: str, duplicate: bool = False):
    e = game.grant_trinket(hero, tid, duplicate=duplicate)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str):
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def golden_minions(hero: Hero) -> list:
    """手牌中的金色随从（按打出顺序）。"""
    return [c for c in hero.hand
            if hasattr(c, "is_golden") and c.is_golden]


def tavern_minions(hero: Hero):
    from hsrl2.minion import Minion
    return [e for e in hero.tavern if isinstance(e, Minion)]


def tavern_tiers(hero: Hero) -> list:
    return sorted(m.tech_level for m in tavern_minions(hero))


def drain_tier5_pool(game: Game) -> dict:
    """把 Tier 5 随从池抽干，返回 {card_id: 已抽出份数}（用于恢复）。"""
    drained: dict = {}
    for d in game.db.pool_minions():
        if d.tech_level != 5:
            continue
        n = 0
        while game.minion_pool.available(d.id) > 0:
            assert game.minion_pool.acquire(d.id)
            n += 1
        drained[d.id] = n
    return drained


def restore_pool(game: Game, drained: dict) -> None:
    for card_id, n in drained.items():
        game.minion_pool.release(card_id, n)


# ══════════════════ 台账守卫（结构性——与钩子无关） ══════════════════


class TestRegistryLedger(unittest.TestCase):
    """@engine-only —— 注册表 / 卡定义 / DEFERRED 台账一致性。"""

    def test_registry_contains_correct_ids(self):
        for tid in CORRECT_IDS:
            self.assertIn(tid, REGISTRY, f"{tid} 未注册")
            self.assertIsNotNone(get_db().get(tid))
        # 本批 2 张 CORRECT 均应为商店可提供成员
        offer = {d.id for d in get_db().trinket_offer_pool()}
        for tid in CORRECT_IDS:
            self.assertIn(tid, offer, f"{tid} 不在商店提供池")

    def test_deferred_ids_unregistered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNotNone(get_db().get(tid), f"{tid} 定义缺失")
            self.assertNotIn(tid, REGISTRY, f"{tid} 仍被注册（DEFERRED）")
        # 本批 id 集合互斥且恰好 18 张
        self.assertEqual(len(CORRECT_IDS) + len(DEFERRED_IDS)
                         + len(MIGRATED_IDS), 18)
        self.assertEqual(set(CORRECT_IDS) & set(DEFERRED_IDS), set())
        self.assertEqual(set(CORRECT_IDS) & set(MIGRATED_IDS), set())
        self.assertEqual(set(DEFERRED_IDS) & set(MIGRATED_IDS), set())

    def test_deferred_ids_are_offer_pool_members(self):
        offer = {d.id for d in get_db().trinket_offer_pool()}
        self.assertEqual(sorted(set(DEFERRED_IDS) - offer), [])
        self.assertEqual(sorted(set(MIGRATED_IDS) - offer), [])

    def test_registry_offer_pool_membership_all_18(self):
        offer = {d.id for d in get_db().trinket_offer_pool()}
        self.assertEqual(
            sorted((set(CORRECT_IDS) | set(DEFERRED_IDS)
                    | set(MIGRATED_IDS)) - offer), [])

    def test_carddef_num_matches_text_params(self):
        # 数值权威双向钉死（文本占位符 → CardDef.num）
        self.assertEqual(num_of(SPLINTER_OF_AURUM, 1), 15)   # "{1} Gold"
        self.assertEqual([num_of(SPLINTER_OF_AURUM, i) for i in (0, 2, 3)],
                         [None, None, None])
        self.assertEqual(num_of(GUIDING_CANDLE, 0), 2)       # "first {0}"
        self.assertEqual([num_of(GUIDING_CANDLE, i) for i in (1, 2, 3)],
                         [None, None, None])
        self.assertEqual([num_of("BG30_MagicItem_944", i) for i in range(2)],
                         [4, 4])
        self.assertEqual(num_of("BG32_MagicItem_300", 0), 2)


# ══════════════════ BG32_MagicItem_350 Splinter of Aurum ══════════════


class TestSplinterOfAurum(unittest.TestCase):
    """BG32_MagicItem_350 — 金币达到 num(1)=15 时得一张随机金色 T5
    （每局一次；金币增加观察点覆盖三条收入路径）。"""

    TID = SPLINTER_OF_AURUM

    def test_turn_income_path_grants_one_golden_t5_once_per_game(self):
        """回合收入路径（真实 `_begin_recruit_for` 基础收入）。"""
        g = make_game(seed=2801)
        a = g.heroes[0]
        bind(g, a, self.TID)
        a.gold = 0
        a.set(GameTag.INCOME_CAP_BONUS, 20)   # income_cap 10+20=30
        g.turn = 13                           # 基础收入 = min(3+12, 30) = 15
        g._begin_recruit_for(a)
        self.assertEqual(a.gold, 15)                     # 收入确实到 15
        cards = golden_minions(a)
        self.assertEqual(len(cards), 1)                  # 正效果: 恰好一张
        d = get_db().get(cards[0].card_id)
        self.assertEqual(d.tech_level, 5)                # 恰好 Tier 5
        self.assertTrue(cards[0].has(GameTag.GILDED_NOT_TRIPLED))
        # "一次获得的金币只触发一次" + Once per game: 再收入不再交付
        GainGold(a, 20).do(g)
        self.assertEqual(len(golden_minions(a)), 1)
        # 负对照（同方法内）: 无饰品 + 同一收入路径 → 一张都不给
        g2 = make_game(seed=2801)
        a2 = g2.heroes[0]
        a2.gold = 0
        a2.set(GameTag.INCOME_CAP_BONUS, 20)
        g2.turn = 13
        g2._begin_recruit_for(a2)
        self.assertEqual(a2.gold, 15)
        self.assertEqual(golden_minions(a2), [])

    def test_sell_path_triggers_at_exact_threshold(self):
        """售卖路径（`game.sell_minion` 的 `hero.gold += 1`）。"""
        g = make_game(seed=2802)
        a = g.heroes[0]
        bind(g, a, self.TID)
        a.gold = 14
        victim = put(g, a, T1_BEAST)
        self.assertTrue(g.sell_minion(a, victim))
        self.assertEqual(a.gold, 15)                     # 14 + 售卖 1
        self.assertEqual(len(golden_minions(a)), 1)
        # 负对照: 无饰品 → 同样 14 金 + 售卖 → 手牌仍空
        g2 = make_game(seed=2802)
        a2 = g2.heroes[0]
        a2.gold = 14
        victim2 = put(g2, a2, T1_BEAST)
        self.assertTrue(g2.sell_minion(a2, victim2))
        self.assertEqual(a2.gold, 15)
        self.assertEqual(golden_minions(a2), [])

    def test_gain_gold_action_path_threshold_and_single_trigger(self):
        """`GainGold` path: 14 金不触发、+1 触发、再 +N 不重复。"""
        g = make_game(seed=2803)
        a = g.heroes[0]
        bind(g, a, self.TID)
        a.gold = 0
        GainGold(a, 14).do(g)
        self.assertEqual(a.gold, 14)
        self.assertEqual(golden_minions(a), [])          # 阈值未到
        GainGold(a, 1).do(g)
        self.assertEqual(a.gold, 15)
        self.assertEqual(len(golden_minions(a)), 1)      # 恰好达到
        GainGold(a, 5).do(g)
        self.assertEqual(a.gold, 20)
        self.assertEqual(len(golden_minions(a)), 1)      # 一次性
        # 负对照: 无饰品 → 30 金也不给
        g2 = make_game(seed=2803)
        a2 = g2.heroes[0]
        a2.gold = 0
        GainGold(a2, 30).do(g2)
        self.assertEqual(a2.gold, 30)
        self.assertEqual(golden_minions(a2), [])

    def test_owner_isolation_opponent_gold_does_not_trigger(self):
        g = make_game(seed=2804)
        a, b = g.heroes
        e = bind(g, a, self.TID)
        b.gold = 0
        GainGold(b, 15).do(g)                            # 对手收入
        self.assertEqual(golden_minions(a), [])          # 本人不触发
        self.assertEqual(golden_minions(b), [])
        self.assertFalse(e._splinter_used)               # 额度未消耗
        a.gold = 0
        GainGold(a, 15).do(g)                            # 本人收入
        self.assertEqual(len(golden_minions(a)), 1)
        self.assertEqual(golden_minions(b), [])          # 对手不获得

    def test_pool_accounting_and_gilded_not_tripled(self):
        """池占返配平: 交付占 1 份; 出售金色副本回池 1 份（非 3 份）。"""
        g = make_game(seed=2805)
        a = g.heroes[0]
        bind(g, a, self.TID)
        a.gold = 0
        GainGold(a, 15).do(g)
        copy = golden_minions(a)[0]
        base_id = copy.get(GameTag.TRIPLE_BASE_CARD_ID, None) \
            or copy.card_id
        self.assertEqual(copy.card_id,
                         get_db().golden_version(get_db().get(base_id)).id)
        # 交付占池 1 份（不可再凭空产生）
        self.assertEqual(g.minion_pool.available(base_id),
                         g.minion_pool.available(base_id))
        avail_after = g.minion_pool.available(base_id)
        # 出售副本 → 回池恰好 1 份（GILDED_NOT_TRIPLED，非 3 份）
        self.assertTrue(g.sell_minion(a, copy))
        self.assertEqual(g.minion_pool.available(base_id), avail_after + 1)
        # 正对照: 交付确实从池里扣过 — 用全新对局同 seed 比较
        g2 = make_game(seed=2805)
        a2 = g2.heroes[0]
        bind(g2, a2, self.TID)
        a2.gold = 0
        GainGold(a2, 15).do(g2)
        copy2 = golden_minions(a2)[0]
        base2 = copy2.get(GameTag.TRIPLE_BASE_CARD_ID, None) \
            or copy2.card_id
        self.assertEqual(base2, base_id)                 # 同 seed 同选择
        self.assertEqual(g2.minion_pool.available(base2), avail_after)

    def test_full_hand_queues_golden_copy_instead_of_dropping(self):
        g = make_game(seed=2806)
        a = g.heroes[0]
        bind(g, a, self.TID)
        while len(a.hand) < 10:
            a.hand.append(g.create_minion(T1_BEAST, controller=a))
        self.assertEqual(len(a.hand), 10)
        queued_before = len(g.pending_hand_queue)
        a.gold = 0
        GainGold(a, 15).do(g)
        self.assertEqual(len(a.hand), 10)                # 未溢出
        self.assertEqual(len(g.pending_hand_queue), queued_before + 1)
        _, queued = g.pending_hand_queue[-1]
        self.assertTrue(queued.is_golden)
        self.assertEqual(get_db().get(queued.card_id).tech_level, 5)

    def test_empty_tier5_pool_fizzles_without_spending_once(self):
        g = make_game(seed=2807)
        a = g.heroes[0]
        e = bind(g, a, self.TID)
        drained = drain_tier5_pool(g)
        a.gold = 0
        GainGold(a, 15).do(g)
        self.assertEqual(a.gold, 15)
        self.assertEqual(golden_minions(a), [])          # 池空 → 落空
        self.assertFalse(e._splinter_used)               # 不消耗额度
        restore_pool(g, drained)
        GainGold(a, 1).do(g)                             # 条件仍满足
        self.assertEqual(len(golden_minions(a)), 1)      # 回池后交付
        self.assertTrue(e._splinter_used)

    def test_two_copies_each_deliver_once(self):
        g = make_game(seed=2808)
        a = g.heroes[0]
        bind(g, a, self.TID)
        bind(g, a, self.TID, duplicate=True)
        a.gold = 0
        GainGold(a, 15).do(g)
        self.assertEqual(len(golden_minions(a)), 2)      # 两份副本各一次
        GainGold(a, 20).do(g)
        self.assertEqual(len(golden_minions(a)), 2)      # 不再追加

    def test_same_seed_deterministic(self):
        picks = []
        for _ in range(2):
            g = make_game(seed=2899)
            a = g.heroes[0]
            bind(g, a, self.TID)
            a.gold = 0
            GainGold(a, 15).do(g)
            picks.append(golden_minions(a)[0].card_id)
        self.assertEqual(picks[0], picks[1])


# ══════════════════ BG32_MagicItem_366 Guiding Candle ══════════════


class TestGuidingCandle(unittest.TestCase):
    """BG32_MagicItem_366 — 每回合前 num(0)=2 次**主动**刷新只出 T6。"""

    TID = GUIDING_CANDLE

    def _prep(self, seed: int = 2810):
        g = make_game(seed=seed)
        a, b = g.heroes
        e = bind(g, a, self.TID)
        a.set(GameTag.TAVERN_TIER, 4)     # 常规刷新上界 = 4（T6 必为效果）
        a.gold = 50
        return g, a, b, e

    def test_first_two_manual_refreshes_tier6_then_normal(self):
        g, a, b, e = self._prep(seed=2810)
        g.refresh_tavern(a)                          # 主动刷新 #1
        self.assertEqual(tavern_tiers(a), [6] * len(tavern_minions(a)))
        self.assertTrue(tavern_minions(a))
        self.assertEqual(e._candle_left, 1)
        self.assertEqual(a.get(GameTag.TAVERN_OFFER_TIER_EXACT, 0), 6)
        g.refresh_tavern(a)                          # 主动刷新 #2
        self.assertEqual(tavern_tiers(a), [6] * len(tavern_minions(a)))
        self.assertEqual(e._candle_left, 0)
        self.assertEqual(a.get(GameTag.TAVERN_OFFER_TIER_EXACT, 0), 0)
        g.refresh_tavern(a)                          # 主动刷新 #3 → 常规
        tiers = tavern_tiers(a)
        self.assertTrue(tiers)
        self.assertNotIn(6, tiers)
        self.assertTrue(all(t <= 4 for t in tiers))
        # 负对照（同方法内）: 无饰品 + 同等级 → 首次刷新即常规（无 T6）
        g2 = make_game(seed=2810)
        a2 = g2.heroes[0]
        a2.set(GameTag.TAVERN_TIER, 4)
        a2.gold = 50
        g2.refresh_tavern(a2)
        self.assertNotIn(6, tavern_tiers(a2))

    def test_auto_refresh_not_counted_and_not_restricted(self):
        """回合开始的自动刷新既不被改写、也不消耗充能。"""
        g, a, b, e = self._prep(seed=2811)
        g.turn = 2
        g._begin_recruit_for(a)                      # SoT → auto 刷新
        auto_tiers = tavern_tiers(a)
        self.assertTrue(auto_tiers)
        self.assertNotIn(6, auto_tiers)              # 自动刷新未被改写
        self.assertTrue(all(t <= 4 for t in auto_tiers))
        # 自动刷新没有消耗充能: 之后两次主动刷新仍全 T6
        g.refresh_tavern(a)
        self.assertEqual(tavern_tiers(a), [6] * len(tavern_minions(a)))
        g.refresh_tavern(a)
        self.assertEqual(tavern_tiers(a), [6] * len(tavern_minions(a)))
        self.assertEqual(e._candle_left, 0)
        g.refresh_tavern(a)
        self.assertNotIn(6, tavern_tiers(a))

    def test_owner_isolation(self):
        g, a, b, e = self._prep(seed=2812)
        b.set(GameTag.TAVERN_TIER, 4)
        b.gold = 50
        b.set(GameTag.TAVERN_OFFER_TIER_EXACT, 0)
        g.refresh_tavern(b)                          # 对手主动刷新
        self.assertNotIn(6, tavern_tiers(b))         # 对手不受影响
        self.assertEqual(b.get(GameTag.TAVERN_OFFER_TIER_EXACT, 0), 0)
        self.assertEqual(e._candle_left, 2)          # 本人充能未动
        g.refresh_tavern(a)                          # 本人刷新
        self.assertEqual(tavern_tiers(a), [6] * len(tavern_minions(a)))
        self.assertNotIn(6, tavern_tiers(b))

    def test_cross_turn_recharges_two(self):
        g, a, b, e = self._prep(seed=2813)
        g.refresh_tavern(a)
        g.refresh_tavern(a)
        self.assertEqual(e._candle_left, 0)
        a.board.clear()
        b.board.clear()
        g.end_recruit_phase()                        # 跨回合: turn 2 自动刷新
        self.assertNotIn(6, tavern_tiers(a))         # 新回合自动刷新常规
        self.assertEqual(e._candle_left, 2)          # 充能已重置
        g.refresh_tavern(a)
        self.assertEqual(tavern_tiers(a), [6] * len(tavern_minions(a)))
        g.refresh_tavern(a)
        self.assertEqual(tavern_tiers(a), [6] * len(tavern_minions(a)))

    def test_duplicate_copies_stack_charges(self):
        g = make_game(seed=2814)
        a = g.heroes[0]
        e1 = bind(g, a, self.TID)
        e2 = bind(g, a, self.TID, duplicate=True)
        a.set(GameTag.TAVERN_TIER, 4)
        a.gold = 50
        self.assertEqual(e1._candle_left, 4)         # 2 份副本 × num(0)=2
        self.assertFalse(hasattr(e2, "_candle_left"))  # 非协调者
        for _ in range(4):
            g.refresh_tavern(a)
            self.assertEqual(tavern_tiers(a),
                             [6] * len(tavern_minions(a)))
        self.assertEqual(e1._candle_left, 0)
        g.refresh_tavern(a)                          # 第 5 次 → 常规
        self.assertNotIn(6, tavern_tiers(a))

    def test_same_seed_deterministic_refresh(self):
        contents = []
        for _ in range(2):
            g = make_game(seed=2898)
            a = g.heroes[0]
            bind(g, a, self.TID)
            a.set(GameTag.TAVERN_TIER, 4)
            a.gold = 50
            g.refresh_tavern(a)
            # 正效果先行断言（否则本测试对"效果是否存在"零信息量）
            self.assertEqual(tavern_tiers(a),
                             [6] * len(tavern_minions(a)))
            contents.append([m.card_id for m in tavern_minions(a)])
        self.assertEqual(contents[0], contents[1])


# ══════════════════ BG32_MagicItem_419 Yu'lon Sticker ══════════════════


class TestYulonSticker(unittest.TestCase):
    """BG32_MagicItem_419 — SoC: 最高 Tier 的龙变金，且**跨战斗持久**。

    注: `Transform` 金色化会**替换实体**（旧实体 zone=REMOVED）——断言
    一律读 `hero.board[i]`（原地替换 + 战后原位重放，索引稳定），不能
    用入场时捕获的旧实体引用（那是 SOP §16c "重放/转移后读旧引用" 的
    同族陷阱）。
    """

    TID = YULON_STICKER

    @staticmethod
    def _probe(game, target_hero, fn):
        """在真实战斗的 SoC 之后（`start_of_combat` 事件）采集状态。"""
        out: list = []

        def cb(g, hero=None, _h=target_hero, **kw):
            if hero is not _h:
                return
            out.append(fn(g))

        game.events.register(Listener(event="start_of_combat", owner=game,
                                      callback=cb))
        return out

    @staticmethod
    def _golden_ids(hero):
        return [m.card_id for m in hero.board if m.is_golden]

    def test_soc_goldenizes_highest_tier_dragon_and_persists(self):
        g = make_game(seed=2820)
        a, b = g.heroes
        put(g, a, DRAGON_T3)                     # board[0]
        put(g, a, DRAGON_T6)                     # board[1]
        bind(g, a, self.TID)
        during = self._probe(
            g, a, lambda gg: [m.is_golden for m in a.board])
        g.run_combat(a, b)
        self.assertEqual(during, [[False, True]])        # SoC 内 T6 变金
        # 战后持久（本卡迁移的核心契约——旧实现被棋盘快照回滚）
        high = a.board[1]
        self.assertTrue(high.is_golden)
        self.assertFalse(a.board[0].is_golden)
        d6 = get_db().get(DRAGON_T6)
        self.assertEqual(high.card_id, get_db().golden_version(d6).id)
        self.assertEqual(high.get(GameTag.TRIPLE_BASE_CARD_ID), DRAGON_T6)
        self.assertTrue(high.has(GameTag.GILDED_NOT_TRIPLED))
        # 负对照（同方法内）: 无饰品 → 同一 setup 无金色
        g2 = make_game(seed=2820)
        a2, b2 = g2.heroes
        put(g2, a2, DRAGON_T6)
        g2.run_combat(a2, b2)
        self.assertEqual(self._golden_ids(a2), [])

    def test_owner_isolation_opponent_dragon_untouched(self):
        g = make_game(seed=2821)
        a, b = g.heroes
        put(g, a, DRAGON_T3)
        put(g, b, DRAGON_T6)
        bind(g, a, self.TID)
        g.run_combat(a, b)
        self.assertTrue(a.board[0].is_golden)            # 本人最高档变金
        self.assertFalse(b.board[0].is_golden)           # 对手不受影响
        self.assertEqual(b.board[0].card_id, DRAGON_T6)

    def test_tie_breaks_leftmost(self):
        g = make_game(seed=2822)
        a, b = g.heroes
        put(g, a, DRAGON_T6)                             # board[0] 最左
        put(g, a, DRAGON_T6)                             # board[1]
        bind(g, a, self.TID)
        g.run_combat(a, b)
        self.assertTrue(a.board[0].is_golden)            # 并列取最左
        self.assertFalse(a.board[1].is_golden)
        self.assertEqual(a.board[1].card_id, DRAGON_T6)

    def test_already_golden_excluded(self):
        g = make_game(seed=2823)
        a, b = g.heroes
        gd = get_db().golden_version(get_db().get(DRAGON_T6))
        golden = g.create_minion(DRAGON_T6, controller=a, golden=True)
        self.assertTrue(g.summon(a, golden))             # board[0] 已金色
        put(g, a, DRAGON_T3)                             # board[1]
        bind(g, a, self.TID)
        g.run_combat(a, b)
        # 已金色者不再重复；最高档的**非金**龙（T3）入选
        self.assertEqual(a.board[0].card_id, gd.id)      # 未再变身
        self.assertTrue(a.board[1].is_golden)
        self.assertEqual(a.board[1].get(GameTag.TRIPLE_BASE_CARD_ID),
                         DRAGON_T3)

    def test_empty_dragon_board_fizzles_and_pool_unchanged(self):
        g = make_game(seed=2824)
        a, b = g.heroes
        put(g, a, T1_BEAST)
        bind(g, a, self.TID)
        avail = g.minion_pool.available(DRAGON_T6)
        g.run_combat(a, b)
        self.assertFalse(a.board[0].is_golden)           # 无龙 → 落空
        self.assertEqual(g.minion_pool.available(DRAGON_T6), avail)

    def test_two_copies_goldenize_two_dragons(self):
        g = make_game(seed=2825)
        a, b = g.heroes
        put(g, a, DRAGON_T6)                             # board[0]
        put(g, a, DRAGON_T3)                             # board[1]
        bind(g, a, self.TID)
        bind(g, a, self.TID, duplicate=True)
        g.run_combat(a, b)
        self.assertTrue(a.board[0].is_golden)            # 副本 1 → T6
        self.assertTrue(a.board[1].is_golden)            # 副本 2 → T3
        self.assertEqual(len(self._golden_ids(a)), 2)

    def test_gilded_not_tripled_sell_returns_one_copy(self):
        # 37.0: Warpwing（BG24_004）退出池内随从 → 池账本单测改用池内
        # T6 龙 Heroic Broodmother（BG36_849；同档同种族）。
        dragon_t6 = "BG36_849"
        g = make_game(seed=2826)
        a, b = g.heroes
        avail0 = g.minion_pool.available(dragon_t6)
        g.minion_pool.acquire(dragon_t6)                 # 模拟入池取得
        put(g, a, dragon_t6)
        bind(g, a, self.TID)
        g.run_combat(a, b)
        self.assertTrue(a.board[0].is_golden)
        self.assertEqual(g.minion_pool.available(dragon_t6), avail0 - 1)
        g.gold = 0
        self.assertTrue(g.sell_minion(a, a.board[0]))    # 出售 → 回池 1 份
        self.assertEqual(g.minion_pool.available(dragon_t6), avail0)

    def test_second_combat_goldenizes_next_dragon(self):
        g = make_game(seed=2827)
        a, b = g.heroes
        put(g, a, DRAGON_T6)
        put(g, a, DRAGON_T3)
        bind(g, a, self.TID)
        g.run_combat(a, b)
        self.assertTrue(a.board[0].is_golden)
        self.assertFalse(a.board[1].is_golden)
        g.run_combat(a, b)                               # 第二场战斗
        self.assertTrue(a.board[0].is_golden)            # 第一只保持金色
        self.assertTrue(a.board[1].is_golden)            # 继续金色化剩余

    def test_engine_dispatched_via_end_recruit_phase(self):
        g = make_game(seed=2828)
        a, b = g.heroes
        put(g, a, DRAGON_T6)
        bind(g, a, self.TID)
        g.end_recruit_phase()                            # 真实回合推进
        self.assertTrue(a.board[0].is_golden)
        d6 = get_db().get(DRAGON_T6)
        self.assertEqual(a.board[0].card_id,
                         get_db().golden_version(d6).id)

    def test_same_seed_deterministic_target(self):
        picks = []
        for _ in range(2):
            g = make_game(seed=2897)
            a, b = g.heroes
            put(g, a, DRAGON_T3)
            put(g, a, DRAGON_T6)
            bind(g, a, self.TID)
            g.run_combat(a, b)
            picks.append(self._golden_ids(a))
        self.assertEqual(picks[0], picks[1])


if __name__ == "__main__":
    unittest.main()
