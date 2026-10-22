"""批次 anomalies 语义测试（2026-09-01, 42 注册项）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def game_with(anomaly: str, seed: int = 40) -> Game:
    g = Game([Hero("TB_BaconShop_HERO_52", "A"),
              Hero("TB_BaconShop_HERO_52", "B")],
             get_db(), seed=seed, anomaly=anomaly)
    g.start_game()
    return g


class TestRegistry(unittest.TestCase):
    def test_count_and_anon(self):
        an = [k for k in REGISTRY if "Anomaly" in k]
        self.assertGreaterEqual(len(an), 40)

    def test_deferred_unregistered(self):
        # BG27_Anomaly_556 Valuation Inflation — DEFERRED（SOP §6b）
        self.assertNotIn("BG27_Anomaly_556", REGISTRY)


class TestMoneyMatch(unittest.TestCase):
    def test_start_10_gold(self):
        g = game_with("BG27_Anomaly_000")
        for h in g.heroes:
            self.assertEqual(h.gold, 10)


class TestTierStart(unittest.TestCase):
    def test_start_tier2(self):
        g = game_with("BG27_Anomaly_001")
        for h in g.heroes:
            self.assertEqual(h.tavern_tier, 2)


class TestOneDamage(unittest.TestCase):
    def test_cap_1_and_5hp(self):
        g = game_with("BG27_Anomaly_006")
        h = g.heroes[0]
        self.assertEqual(h.health, 5)
        h.armor = 0
        h.take_damage(7)
        self.assertEqual(h.health, 4)


class TestOnlyRace(unittest.TestCase):
    def test_beast_only(self):
        g = game_with("BG27_Anomaly_104t")
        a = g.heroes[0]
        tavern = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(tavern)
        for m in tavern:
            self.assertIn(m.race, (Race.BEAST, Race.ALL))


class TestAllGolden(unittest.TestCase):
    def test_golden_tavern_no_reward(self):
        g = game_with("BG27_Anomaly_801")
        a = g.heroes[0]
        tavern = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(any(m.is_golden for m in tavern))
        self.assertTrue(a.get(GameTag.TRIPLE_NO_REWARD, False))


class TestStartDamage25(unittest.TestCase):
    def test_25_damage(self):
        g = game_with("BG27_Anomaly_714")
        for h in g.heroes:
            self.assertEqual(h.health + h.armor, 5)   # 30-25


class TestExtraBCDR(unittest.TestCase):
    def test_flag(self):
        g = game_with("BG27_Anomaly_802")
        self.assertTrue(g._extra_bc_dr)


class TestRepairs2026_09_01(unittest.TestCase):
    """2026-09-01 主线维修的回归断言（每项对应审计/文本依据）。"""

    def test_money_match_gold_per_hero(self):
        """Money Match: 每个英雄 10 金（监听条件 h 一致性）。"""
        g = game_with("BG27_Anomaly_000")
        for h in g.heroes:
            self.assertEqual(h.gold, 10)

    def test_tier7_no_global_constant_pollution(self):
        """Secrets of Norgannon: 每局 T7, 不得改写模块常量。"""
        import hsrl2.constants as C
        g = game_with("BG27_Anomaly_504")
        self.assertEqual(g.max_tavern_tier, 7)
        self.assertEqual(C.TAVERN_MAX_TIER, 6)   # 跨局污染回归
        g2 = game_with("BG27_Anomaly_000")
        self.assertEqual(g2.max_tavern_tier, 6)

    def test_tier3_first_shop_all_tier3(self):
        """Temperance of Aman'Thul: 首店全 T3; 之后回落。"""
        g = game_with("BG27_Anomaly_501")
        a = g.heroes[0]
        first = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(first)
        self.assertTrue(all(m.tech_level == 3 for m in first))
        a.gold = 50
        g.refresh_tavern(a, auto=True)
        # 回落: 后续商店可出现 ≤3（不必全 3）
        self.assertEqual(getattr(a, "_tavern_min_tier", 1), 1)

    def test_elven_elite_tier_only(self):
        """Elven Elite: 酒馆只提供与酒馆等级同 tier 的随从。"""
        g = game_with("BG31_Anomaly_111")
        a = g.heroes[0]
        a.set(GameTag.TAVERN_TIER, 3)
        a.gold = 50
        g.refresh_tavern(a, auto=True)
        minions = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(minions)
        self.assertTrue(all(m.tech_level == 3 for m in minions))

    def test_overseers_orb_refresh_race(self):
        """Overseer's Orb: 升级后按 most-common type 刷新。"""
        g = game_with("BG27_Anomaly_718")
        a = g.heroes[0]
        # 用真实野兽卡铺场
        beast = next(d for d in get_db().pool_minions()
                     if d.race == Race.BEAST and d.tech_level == 1)
        a.board = [g.create_minion(beast.id, controller=a) for _ in range(2)]
        a.gold = 50
        a.set(GameTag.TAVERN_TIER, 3)
        g.upgrade_tavern(a)
        minions = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(minions)
        # 类型身份集合（AC-3）: 双类型野兽身份同样合格。
        self.assertTrue(all(m.has_race(Race.BEAST) for m in minions))

    def test_golganneth_refresh_after_buy(self):
        """Golganneth's Tempest: 禁手动刷新 + 买牌后自动刷新。"""
        g = game_with("BG27_Anomaly_900")
        a = g.heroes[0]
        a.gold = 50
        before = list(a.tavern)
        g.refresh_tavern(a)                      # 手动刷新被禁
        self.assertEqual(a.tavern, before)
        t = [m for m in a.tavern if isinstance(m, Minion)][0]
        ok = g.buy_from_tavern(a, t)
        self.assertTrue(ok)
        # 买后自动刷新: 酒馆重抽（仍在池外旧内容回池）
        self.assertNotIn(t, a.tavern)

    def test_golden_arena_stats_doubled(self):
        """The Golden Arena: 酒馆金卡 = 金卡本体（属性翻倍）。"""
        g = game_with("BG27_Anomaly_801")
        a = g.heroes[0]
        minions = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(minions)
        self.assertTrue(all(m.is_golden for m in minions))
        for m in minions:
            gd = get_db().get(m.card_id)          # 金色 CardDef 本体
            base = get_db().by_dbf(gd.triple_base_id)
            self.assertIsNotNone(base)
            # 37.0: 金色形态 = 金色 CardDef（官方规则：金色可升级效果而非
            # 必翻倍属性——如新卡 BG36_360 Dark Paradox 金色同为 1/1）；
            # 旧断言 "== 基础 ×2" 只对传统金色成立，违反数据权威。
            self.assertEqual((m.atk, m.max_health),
                             (gd.atk, gd.health), m.card_id)
            self.assertTrue(m.get(GameTag.GILDED_NOT_TRIPLED, False))

    def test_pirate_anomaly_injects_hoggarr(self):
        """Oops, All Pirates!: Cap'n Hoggarr (BGS_072) 入池且可被抽。"""
        g = game_with("BG27_Anomaly_104t10")
        pool = g.minion_pool
        self.assertGreater(pool.available("BGS_072"), 0)
        self.assertIn("BGS_072",
                      pool.candidates(7, 1, races={Race.PIRATE, Race.ALL}))
        a = g.heroes[0]
        self.assertTrue(all(m.race in (Race.PIRATE, Race.ALL)
                            for m in a.tavern if isinstance(m, Minion)))

    def test_scouts_honor_patient_scout(self):
        """Scout's Honor: 开局的金色 Patient Scout 应为 BG24_715。"""
        g = game_with("BG31_Anomaly_120")
        a = g.heroes[0]
        board = [m for m in a.board]
        self.assertEqual(len(board), 1)
        self.assertEqual(board[0].card_id, "BG24_715_G")
        self.assertTrue(board[0].is_golden)

    def test_blessed_or_blighted_reborn(self):
        """Blessed or Blighted: 最左圣盾 / 最右复生（不是 +20/+20）。"""
        from hsrl2.combat import CombatScheduler
        g = game_with("BG27_Anomaly_726")
        a = g.heroes[0]
        left = g.create_minion("BG25_001", controller=a)
        right = g.create_minion("BG25_001", controller=a)
        g.summon(a, left, 0)
        g.summon(a, right, 1)
        CombatScheduler(g, a, g.heroes[1])._start_of_combat_phase()
        self.assertTrue(left.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(right.has(GameTag.REBORN))
        self.assertFalse(right.has(GameTag.DIVINE_SHIELD))

    def test_gladiators_spoils_lower_tier(self):
        """Gladiator's Spoils: 非胜 → 低一 tier 随机随从。"""
        g = game_with("BG27_Anomaly_715")
        a = g.heroes[0]
        a.set(GameTag.TAVERN_TIER, 3)
        a._last_combat_result = "loss"
        g.events.fire(g, "combat_end", hero_a=a, hero_b=g.heroes[1],
                      result=None)
        tiers = [m.tech_level for m in a.hand if isinstance(m, Minion)]
        self.assertTrue(tiers)
        self.assertTrue(all(t == 2 for t in tiers))

    def test_everythings_on_fire_heal_cap(self):
        """Everything's on Fire!: 回血封顶 30（不是 40）。"""
        from hsrl2.events import HERO_ELIMINATED
        g = game_with("BG27_Anomaly_714")
        a, b = g.heroes[0], g.heroes[1]
        a.health = 29
        g.events.fire(g, HERO_ELIMINATED, hero=b)
        self.assertEqual(a.health, 30)

    def test_incubation_mutation_global(self):
        """Incubation Mutation: 无类型随从在任何区域都是全类型。"""
        g = game_with("BG31_Anomaly_112")
        # 找一个无种族随从
        d = next(d for d in get_db()._by_id.values()
                 if d.card_type.name == "MINION" and d.race == Race.NONE
                 and d.tech_level > 0)
        m = g.create_minion(d.id, controller=g.heroes[0])
        self.assertEqual(m.race, Race.ALL)

    def test_dark_gifts_baseline_already_on(self):
        """Dark Gifts! 异变与 S14 基线同文——use_dark_gift 恒可用。"""
        import hsrl2.constants as C
        g = game_with("BG36_Anomaly_002")
        a = g.heroes[0]
        self.assertEqual(C.DARK_GIFT_START_TURN, 3)
        while g.turn < 3:
            g.end_recruit_phase()
        a.gold = 20
        self.assertTrue(g.use_dark_gift(a))


if __name__ == "__main__":
    unittest.main()
