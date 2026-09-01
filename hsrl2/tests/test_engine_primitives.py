"""引擎原语收口测试——12 项新引擎能力的回归验证。

覆盖: GOLDEN_MINIONS_PLAYED / on_enter_hand / 替代三连 / 健康刷新 /
card_discovered / spell_resolving+永久化 / SPELL_DOUBLER 双施 /
buff_applied / ENCHANT_IMMUNE / Poet 相邻持久 / 上局战斗结果 /
execute_immediate_attack / 死亡簿记 / gem 标记与窃取 / Bounty 常量。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import (PlayBloodGems, StealBloodGems,
                                    random_bounty_card_id)
from hsrl2.actions.stats import Buff
from hsrl2.combat import execute_immediate_attack
from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed=42, n=2) -> Game:
    heroes = [Hero(chr(ord("A") + i), chr(ord("A") + i)) for i in range(n)]
    import hsrl2.scripts  # noqa
    return Game(heroes, get_db(), seed=seed)


def find_plain(db, tier=None, race=None):
    for d in sorted(db.pool_minions(), key=lambda x: x.id):
        if db.golden_version(d) is None:
            continue
        if tier is not None and d.tech_level != tier:
            continue
        if race is not None and d.race != race:
            continue
        if "battlecry" in d.keywords:
            continue
        return d
    raise AssertionError


class TestGoldenPlayedCounter(unittest.TestCase):
    def test_golden_and_triple_golden_counted(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = find_plain(get_db())
        g = game.create_minion(d.id, controller=a, golden=True)
        a.hand.append(g)
        g.zone = Zone.HAND
        game.play_minion(a, g)
        self.assertEqual(a.get(GameTag.GOLDEN_MINIONS_PLAYED), 1)
        m2 = game.create_minion(d.id, controller=a)
        a.hand.append(m2)
        m2.zone = Zone.HAND
        game.play_minion(a, m2)
        self.assertEqual(a.get(GameTag.GOLDEN_MINIONS_PLAYED), 1)  # 非金不加


class TestOnEnterHand(unittest.TestCase):
    def test_hook_fires_on_add_to_hand(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        seen = []
        m = Minion("TEST_X", "X", atk=1, health=1)
        m.game = game
        m.scripts = type("S", (), {
            "on_enter_hand": staticmethod(
                lambda s, g, c: seen.append(1) or None)})
        a.add_to_hand(m)
        self.assertEqual(seen, [1])


class TestElementalSurpriseSubstitution(unittest.TestCase):
    """（对抗审查: 原三条退化恒真——重写为精确断言，非 175 元素驱动）"""

    def _other_elem(self, db):
        cands = [d for d in db.pool_minions()
                 if d.race == Race.ELEMENTAL and d.id != "BG26_175"
                 and db.golden_version(d) is not None
                 and "battlecry" not in d.keywords]
        return sorted(cands, key=lambda x: x.id)[0]

    def test_two_elem_copies_plus_surprise_combines_to_elem_golden(self):
        """2×同名元素 + 1×175 → 金色 = 该元素的golden（wiki: "using
        Elemental of Surprise to triple Marine Matriarch"）。"""
        game = make_game(seed=3)
        a = game.heroes[0]
        db = get_db()
        elem = self._other_elem(db)
        for _ in range(2):
            m = game.create_minion(elem.id, controller=a)
            a.hand.append(m)
            m.zone = Zone.HAND
        surprise = game.create_minion("BG26_175", controller=a)
        a.hand.append(surprise)
        surprise.zone = Zone.HAND
        game.check_for_triple(a, surprise)
        goldens = [m for m in a.hand
                   if isinstance(m, Minion) and m.is_golden]
        self.assertEqual(len(goldens), 1)
        self.assertEqual(goldens[0].card_id,
                         db.golden_version(db.get(elem.id)).id)

    def test_no_substitution_without_surprise(self):
        """2×元素 + 1×其他元素（无 175）不合成。"""
        game = make_game(seed=5)
        a = game.heroes[0]
        db = get_db()
        elem = self._other_elem(db)
        for _ in range(2):
            m = game.create_minion(elem.id, controller=a)
            a.hand.append(m)
            m.zone = Zone.HAND
        other = find_plain(db)
        sub = game.create_minion(other.id, controller=a)
        a.hand.append(sub)
        sub.zone = Zone.HAND
        game.check_for_triple(a, sub)
        self.assertFalse(any(m.is_golden for m in a.hand))
        self.assertEqual(len(a.hand), 3)   # 三张原样保留


class TestHealthRefreshes(unittest.TestCase):
    def test_malchezaar_protocol(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        game.start_game()
        a.set(GameTag.HEALTH_REFRESHES_LEFT, 2)
        a.gold = 10
        hp0 = a.health + a.armor
        game.refresh_tavern(a, auto=False)   # 第 1 次: 扣血不扣金
        self.assertEqual(a.gold, 10)
        self.assertEqual(a.health + a.armor, hp0 - 1)
        game.refresh_tavern(a, auto=False)   # 第 2 次: 扣血
        self.assertEqual(a.gold, 10)
        game.refresh_tavern(a, auto=False)   # 第 3 次: 用尽 → 金币
        self.assertEqual(a.gold, 9)


class TestCardDiscoveredEvent(unittest.TestCase):
    def test_discover_choice_fires_event(self):
        game = make_game(seed=7)
        a = game.heroes[0]
        seen = []
        game.events.register(Listener(
            "card_discovered", owner=a,
            callback=lambda g, **kw: seen.append(kw.get("kind"))))
        from hsrl2.actions.discover import Discover
        game.run_actions(Discover(a, count=3, kind="discover_minion"))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(seen, ["discover_minion"])


class TestSpellPermanenceInterception(unittest.TestCase):
    def test_permanence_flips_temporary_buff(self):
        game = make_game(seed=8)
        a = game.heroes[0]
        m = Minion("TEST_T", "T", atk=1, health=5)
        m.game = game
        m.controller = a
        # 模拟 Lava Lurker 脚本行为: spell_resolving 时设置 pending
        def on_resolving(g, spell=None, target=None, cast_no=0, **kw):
            if target is m:
                g._permanence_pending = m.uuid
        game.events.register(Listener(
            "spell_resolving", owner=a, callback=on_resolving))
        m.add_buff(Enchant(atk=2, temporary=True))
        # 非法术路径的 temporary buff 不受影响
        self.assertTrue(any(b.temporary for b in m.buffs))
        game._permanence_pending = m.uuid
        m.add_buff(Enchant(atk=3, temporary=True))
        game._permanence_pending = None
        temps = [b for b in m.buffs if b.temporary]
        self.assertEqual(len(temps), 1)      # 仅第一份保持 temporary
        self.assertEqual(m.atk, 1 + 2 + 3)


class TestSpellDoubler(unittest.TestCase):
    def test_targeted_friendly_spell_casts_twice(self):
        game = make_game(seed=9)
        a = game.heroes[0]
        balinda = Minion("TEST_BAL", "B", atk=1, health=1)
        balinda.game = game
        balinda.controller = a
        balinda.set(GameTag.SPELL_DOUBLER, True)
        game.summon(a, balinda)
        target = Minion("TEST_TGT", "T", atk=2, health=2)
        game.summon(a, target)
        # 构造一个已注册的定向法术: Tavern Dish Banana (+2/+2)
        spell = game.create_spell("BG28_897", controller=a)
        d = get_db().get("BG28_897")
        a.hand.append(spell)
        spell.zone = Zone.HAND
        game.play_spell(a, spell, target=target)
        self.assertEqual(target.atk, 2 + d.num(0) * 2)   # 双施
        self.assertEqual(target.max_health, 2 + d.num(1) * 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 2)


class TestBuffAppliedEvent(unittest.TestCase):
    def test_event_fires_with_target_and_buff(self):
        game = make_game(seed=10)
        a = game.heroes[0]
        seen = []
        m = Minion("TEST_E", "E", atk=1, health=1)
        game.summon(a, m)
        game.events.register(Listener(
            "buff_applied", owner=a,
            callback=lambda g, target=None, buff=None, **kw:
                seen.append((target, buff.atk))))
        game.run_actions(Buff(m, atk=5, health=5))
        self.assertEqual(seen, [(m, 5)])


class TestEnchantImmune(unittest.TestCase):
    def test_fishbait_cannot_gain_stats(self):
        game = make_game(seed=11)
        a = game.heroes[0]
        m = Minion("TEST_FISH", "Fishbait", atk=0, health=1)
        game.summon(a, m)
        m.set(GameTag.ENCHANT_IMMUNE, True)
        game.run_actions(Buff(m, atk=99, health=99))
        self.assertEqual(m.atk, 0)
        self.assertEqual(m.max_health, 1)
        self.assertEqual(m.buffs, [])          # 正值增益被拒


class TestPoetAdjacentPersist(unittest.TestCase):
    def test_poet_engine_branch_direct(self):
        """直接驱动 run_combat 的恢复分支验证 Poet 持久化。"""
        game = make_game(seed=13)
        a, b = game.heroes
        poet = Minion("TEST_POET2", "P2", atk=1, health=50)
        poet.set(GameTag.ADJACENT_PERSIST_SOURCE, True)
        poet.set(GameTag.DIVINE_SHIELD, True)
        dragon = Minion("TEST_DRG2", "D2", atk=2, health=50,
                        race=Race.DRAGON)
        game.summon(a, dragon)
        game.summon(a, poet)
        big = Minion("TEST_BIG2", "B2", atk=4, health=60)
        game.summon(b, big)
        # SoC 注入战斗内增益（start_of_combat 钩子在战斗内触发）
        dragon.scripts = type("S", (), {
            "start_of_combat": staticmethod(
                lambda s, g, c: Buff(s, atk=3, health=3))})
        game.run_combat(a, b)
        # dragon 相邻 Poet → 战斗增益保留（2+3 攻）; Poet 非龙自身不保持
        self.assertEqual(dragon.atk, 2 + 3)
        self.assertEqual(dragon.max_health, 50 + 3)


class TestLastCombatResult(unittest.TestCase):
    def test_results_recorded(self):
        game = make_game(seed=14)
        a, b = game.heroes
        game.summon(a, Minion("TEST_W", "W", atk=10, health=10))
        game.summon(b, Minion("TEST_L", "L", atk=1, health=1))
        game.run_combat(a, b)
        self.assertEqual(a._last_combat_result, "win")
        self.assertEqual(b._last_combat_result, "loss")


class TestExecuteImmediateAttack(unittest.TestCase):
    def test_immediate_attack_full_semantics(self):
        game = make_game(seed=15)
        a, b = game.heroes
        attacker = Minion("TEST_IA", "IA", atk=5, health=5)
        defender = Minion("TEST_ID", "ID", atk=3, health=8)
        game.summon(a, attacker)
        game.summon(b, defender)
        execute_immediate_attack(game, attacker, defender)
        self.assertEqual(defender.health, 3)    # 8-5
        self.assertEqual(attacker.health, 2)    # 5-3 反击


class TestDeathsByCardId(unittest.TestCase):
    def test_ledger_counts_recruit_deaths(self):
        game = make_game(seed=16)
        a = game.heroes[0]
        m = game.create_minion("BG25_008", controller=a)
        game.summon(a, m)
        m.health = 0
        game.check_deaths()
        self.assertEqual(a.deaths_by_card_id.get("BG25_008"), 1)


class TestGemMarkingAndSteal(unittest.TestCase):
    def test_steal_moves_gem_buffs_only(self):
        game = make_game(seed=17)
        a = game.heroes[0]
        victim = Minion("TEST_V", "V", atk=1, health=10)
        thief = Minion("TEST_TH", "T", atk=1, health=10)
        game.summon(a, victim)
        game.summon(a, thief)
        game.run_actions(PlayBloodGems(victim, 3))
        game.run_actions(Buff(victim, atk=7))          # 非宝石 buff
        self.assertEqual(victim.get(GameTag.GEMS_PLAYED_ON), 3)
        game.run_actions(StealBloodGems(thief, victim))
        gem_buffs_v = [b for b in victim.buffs if b.gem]
        gem_buffs_t = [b for b in thief.buffs if b.gem]
        self.assertEqual(len(gem_buffs_v), 0)          # 宝石全被偷
        self.assertEqual(len(gem_buffs_t), 3)
        self.assertEqual(victim.get(GameTag.GEMS_PLAYED_ON), 0)
        self.assertEqual(thief.get(GameTag.GEMS_PLAYED_ON), 3)
        self.assertEqual(victim.atk, 1 + 7)            # 非宝石 buff 保留

    def test_hand_played_gem_accounted(self):
        game = make_game(seed=18)
        a = game.heroes[0]
        m = Minion("TEST_G", "G", atk=1, health=10)
        game.summon(a, m)
        gem = game.create_spell("BG20_GEM", controller=a)
        a.hand.append(gem)
        gem.zone = Zone.HAND
        game.play_spell(a, gem, target=m)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 1)
        self.assertTrue(any(b.gem for b in m.buffs))


class TestBountyPool(unittest.TestCase):
    def test_bounty_ids_valid(self):
        db = get_db()
        import hsrl2.constants as C
        for cid in C.BOUNTY_SPELL_IDS:
            d = db.get(cid)
            self.assertIsNotNone(d, cid)
            self.assertTrue(d.is_pool_spell, cid)
            self.assertIn("Bounty", d.name)

    def test_random_bounty(self):
        game = make_game(seed=19)
        cid = random_bounty_card_id(game)
        self.assertIn(cid, {"BG33_811", "BG33_812", "BG33_813",
                            "BG33_814", "BG33_815"})


if __name__ == "__main__":
    unittest.main()


class TestAdversarialFixes(unittest.TestCase):
    """对抗审查（2026-08-22）7 项必修的回归。"""

    def test_bug1_triple_wiring_discover_and_random(self):
        """获取/发现路径自动三连（曾只接购买路径）。"""
        from hsrl2.actions.discover import Discover, GetRandomMinion
        game = make_game(seed=30)
        a = game.heroes[0]
        d = find_plain(get_db())
        # GetRandomMinion ×3 同卡不可控——用 Discover 定向
        for _ in range(3):
            game.run_actions(Discover(a, count=3,
                                      candidates=[d.id],
                                      kind="discover_minion"))
            game.pending_choices.pop(0).choose(0)
        self.assertEqual(len([m for m in a.hand
                              if m.card_id == d.id and not m.is_golden]), 0)
        self.assertTrue(any(m.is_golden for m in a.hand))

    def test_bug2_substitution_arrival_order(self):
        """元素先到 + 2×Surprise 后到也合成（全池重扫）。"""
        game = make_game(seed=31)
        a = game.heroes[0]
        # 用两张 BG26_175 + 一张其他元素（非 175，避免退化为普通路径）
        s1 = game.create_minion("BG26_175", controller=a)
        s2 = game.create_minion("BG26_175", controller=a)
        elem = find_plain(get_db(), race=Race.ELEMENTAL)
        if elem.id == "BG26_175":
            self.skipTest("no other elemental")
        for m in (s1, s2, elem):
            pass
        # 其他元素**先**在手（到达顺序与合成方向相反）
        e = game.create_minion(elem.id, controller=a)
        a.hand.append(e)
        e.zone = Zone.HAND
        # 第二张 175 到达触发
        a.hand.append(s1)
        s1.zone = Zone.HAND
        game.check_for_triple(a, s1)
        # 未达 3 份（1×175+1×elem）不合成
        if not any(m.is_golden for m in a.hand):
            # 第三份 175 到达 → 2×175 + 1×elem 合成
            a.hand.append(s2)
            s2.zone = Zone.HAND
            game.check_for_triple(a, s2)
        goldens = [m for m in a.hand
                   if isinstance(m, Minion) and m.is_golden]
        self.assertEqual(len(goldens), 1)
        self.assertEqual(goldens[0].card_id, "BG26_175_G")
        # 参与者全部消耗
        self.assertEqual(
            len([m for m in a.hand if m.card_id == elem.id]), 0)

    def test_bug3_gift_double_stats(self):
        """Tarecgosa gift: 战斗属性增益 ×2 保留。"""
        game = make_game(seed=32)
        a, b = game.heroes
        m = Minion("TEST_TD", "TD", atk=2, health=10)
        game.summon(a, m)
        m.set(GameTag.PERSIST_COMBAT_CHANGES, True)
        m.set(GameTag.PERSIST_DOUBLE, True)
        big = Minion("TEST_TB", "TB", atk=3, health=60)
        game.summon(b, big)
        m.scripts = type("S", (), {
            "start_of_combat": staticmethod(
                lambda s, g, c: Buff(s, atk=3, health=4))})
        game.run_combat(a, b)
        self.assertEqual(m.atk, 2 + 3 * 2)          # double
        self.assertEqual(m.max_health, 10 + 4 * 2)

    def test_bug3_plain_persist_single(self):
        """池卡 Tarecgosa 语义（PERSIST 无 DOUBLE）: 1× 保留。"""
        game = make_game(seed=33)
        a, b = game.heroes
        m = Minion("TEST_TP", "TP", atk=2, health=10)
        game.summon(a, m)
        m.set(GameTag.PERSIST_COMBAT_CHANGES, True)   # 无 DOUBLE
        big = Minion("TEST_TB2", "TB2", atk=3, health=60)
        game.summon(b, big)
        m.scripts = type("S", (), {
            "start_of_combat": staticmethod(
                lambda s, g, c: Buff(s, atk=3, health=4))})
        game.run_combat(a, b)
        self.assertEqual(m.atk, 2 + 3)
        self.assertEqual(m.max_health, 10 + 4)

    def test_bug3_golden_poet_double(self):
        """金色 Poet: 相邻龙战斗增益 ×2。"""
        game = make_game(seed=34)
        a, b = game.heroes
        poet = Minion("TEST_GP", "GP", atk=1, health=50)
        poet.set(GameTag.ADJACENT_PERSIST_SOURCE, True)
        poet.set(GameTag.GOLDEN, True)
        poet.set(GameTag.DIVINE_SHIELD, True)
        dragon = Minion("TEST_GD", "GD", atk=2, health=50, race=Race.DRAGON)
        game.summon(a, dragon)
        game.summon(a, poet)
        big = Minion("TEST_GB", "GB", atk=3, health=80)
        game.summon(b, big)
        dragon.scripts = type("S", (), {
            "start_of_combat": staticmethod(
                lambda s, g, c: Buff(s, atk=3, health=3))})
        game.run_combat(a, b)
        self.assertEqual(dragon.atk, 2 + 3 * 2)       # 金色 Poet double
        self.assertEqual(dragon.max_health, 50 + 3 * 2)

    def test_bug4_eventbus_unregister_mid_fire(self):
        """回调内注销的其他监听器本次不再分发; once 消费正常触发。"""
        game = make_game(seed=35)
        a = game.heroes[0]
        calls = []
        m1 = Minion("TEST_M1", "M1", atk=1, health=1)
        m2 = Minion("TEST_M2", "M2", atk=1, health=1)
        game.summon(a, m1)
        game.summon(a, m2)

        def cb1(g, **kw):
            calls.append("m1")
            game.events.unregister_owner(m2)   # 注销 m2 的监听器

        game.events.register(Listener(
            "death", owner=m1, callback=cb1))
        game.events.register(Listener(
            "death", owner=m2,
            callback=lambda g, **kw: calls.append("m2-after-unregister")))
        once_fired = []
        game.events.register(Listener(
            "death", owner=a, once=True,
            callback=lambda g, **kw: once_fired.append(1)))
        m1.health = 0
        game.check_deaths()
        self.assertIn("m1", calls)
        self.assertNotIn("m2-after-unregister", calls)   # 注销即失效
        self.assertEqual(once_fired, [1])                # once 正常触发

    def test_bug5_steal_clamps_health(self):
        """窃取宝石后受害者当前血 clamp 到新上限。"""
        game = make_game(seed=36)
        a = game.heroes[0]
        victim = Minion("TEST_SV", "SV", atk=1, health=5)
        thief = Minion("TEST_ST", "ST", atk=1, health=20)
        game.summon(a, victim)
        game.summon(a, thief)
        game.run_actions(PlayBloodGems(victim, 3))       # +3 生命
        self.assertEqual(victim.max_health, 8)
        self.assertEqual(victim.health, 8)
        game.run_actions(StealBloodGems(thief, victim))
        self.assertEqual(victim.max_health, 5)
        self.assertEqual(victim.health, 5)               # clamp

    def test_bug6_frozen_tavern_no_spell_inflation(self):
        """冻结含法术的馆连续刷新不膨胀。"""
        game = make_game(seed=37)
        a = game.heroes[0]
        game.start_game()
        game.freeze_tavern(a)
        for _ in range(3):
            game.refresh_tavern(a, auto=True)   # 连续冻结刷新
            game.freeze_tavern(a)
        spells = [e for e in a.tavern if not isinstance(e, Minion)]
        self.assertLessEqual(len(spells), 1)    # 恒 1（不 +1/回合）

    def test_bug7_golden_doublers_triple(self):
        """金色 doubler ×3（Balinda 金三施 / 金色 Brann 战吼 ×3）。"""
        game = make_game(seed=38)
        a = game.heroes[0]
        balinda = Minion("TEST_BA", "BA", atk=1, health=1)
        balinda.set(GameTag.SPELL_DOUBLER, True)
        balinda.set(GameTag.GOLDEN, True)
        game.summon(a, balinda)
        target = Minion("TEST_BT", "BT", atk=2, health=2)
        game.summon(a, target)
        spell = game.create_spell("BG28_897", controller=a)
        d = get_db().get("BG28_897")
        a.hand.append(spell)
        spell.zone = Zone.HAND
        game.play_spell(a, spell, target=target)
        self.assertEqual(target.atk, 2 + d.num(0) * 3)   # 三施
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 3)

    def test_health_refresh_survival_guard(self):
        """血量不足以支付刷新时回落金币路径。"""
        game = make_game(seed=39)
        a = game.heroes[0]
        game.start_game()
        a.set(GameTag.HEALTH_REFRESHES_LEFT, 2)
        a.armor = 0
        a.health = 1
        a.gold = 5
        game.refresh_tavern(a, auto=False)
        self.assertEqual(a.health, 1)      # 未被扣死
        self.assertEqual(a.gold, 4)        # 走了金币

    def test_play_path_triple_combines_after_battlecry(self):
        """打出第 3 张（2 在手）→ 战吼结算后合成、金色上场。"""
        game = make_game(seed=40)
        a = game.heroes[0]
        d = find_plain(get_db())
        for _ in range(2):
            m = game.create_minion(d.id, controller=a)
            a.hand.append(m)
            m.zone = Zone.HAND
        third = game.create_minion(d.id, controller=a)
        a.hand.append(third)
        third.zone = Zone.HAND
        game.play_minion(a, third)
        self.assertEqual(len(a.board), 1)
        self.assertTrue(a.board[0].is_golden)
        self.assertEqual(a.board[0].card_id,
                         get_db().golden_version(d).id)
        self.assertEqual(len(a.hand), 0)   # 两张手牌参与者已消耗


class TestHeroPowerWiring(unittest.TestCase):
    """英雄技能引擎接线: on_bind 开局自动 / turn_end 广播 / available 协议。"""

    REAL_HERO = "BG20_HERO_103"   # Blackthorn（db 有 power 绑定）

    def _game_with_real_hero(self, seed):
        from hsrl2.hero import Hero as HeroCls
        h = HeroCls(self.REAL_HERO, "Blackthorn")
        game = make_game(seed)
        game.heroes[0] = h
        h.game = game
        return game

    def test_start_game_binds_passive(self):
        game = self._game_with_real_hero(50)
        a = game.heroes[0]
        bound = []

        class FakePassive:
            passive = True
            @staticmethod
            def on_bind(hero, game_):
                bound.append(hero)

        from hsrl2.scripts import REGISTRY
        power = game.hero_power_def(a)
        self.assertIsNotNone(power, "test hero needs a bound power")
        REGISTRY[power.id] = FakePassive
        try:
            game.start_game()
            self.assertIn(a, bound)          # 开局自动接线
            # 被动不可主动使用
            self.assertFalse(game.use_hero_power(a))
        finally:
            del REGISTRY[power.id]

    def test_available_protocol_gates_use(self):
        game = self._game_with_real_hero(51)
        a = game.heroes[0]
        power = game.hero_power_def(a)

        class GatedActive:
            uses_per_turn = 1
            available = staticmethod(lambda hero, g: hero.gold >= 5)
            hero_power = staticmethod(lambda hero, g, ctx: None)

        from hsrl2.scripts import REGISTRY
        REGISTRY[power.id] = GatedActive
        try:
            game.start_game()
            a.gold = 3
            self.assertFalse(game.use_hero_power(a))   # 门槛拒绝
            a.gold = 6
            self.assertTrue(game.use_hero_power(a))    # 达标可用
        finally:
            del REGISTRY[power.id]

    def test_turn_end_event_fires(self):
        game = make_game(seed=52)
        fired = []
        game.start_game()
        game.events.register(Listener(
            "turn_end", owner=game.heroes[0],
            callback=lambda g, turn=0, **kw: fired.append(turn)))
        game.end_recruit_phase()
        self.assertEqual(fired, [1])


class TestCombatDamageTiming(unittest.TestCase):
    """官方伤害时序（2026-08-22 修正）: 战败伤害施加于战后棋盘。

    结构性推论: 战败方棋盘必然全灭（战斗结束条件）→ 败方随从的
    hero_damage_taken 监听器（Soul Rewinder 家族）不可能由战败伤害
    触发——"带 Rewinder 不死"是引擎时序 bug，非官方行为。
    """

    def test_soul_rewinder_does_not_rewind_combat_loss(self):
        game = make_game(seed=60)
        a, b = game.heroes
        rewinder = game.create_minion("BG26_174", controller=a)
        game.summon(a, rewinder)
        killer = Minion("TEST_K", "K", atk=30, health=30)
        game.summon(b, killer)
        game.run_combat(a, b)
        self.assertTrue(a.health < 30)     # 战败伤害不被回溯

    def test_soul_rewinder_rewinds_recruit_damage_fully(self):
        game = make_game(seed=61)
        a = game.heroes[0]
        rewinder = game.create_minion("BG26_174", controller=a)
        game.summon(a, rewinder)
        a.armor = 5
        base_hp = rewinder.max_health
        a.take_damage(3)                  # 护甲吸收 3
        self.assertEqual(a.health, 30)    # 生命未动
        self.assertEqual(a.armor, 5)      # 护甲全额回溯（逐实例 Rewind）
        self.assertEqual(rewinder.max_health, base_hp + 1)  # +1 Health

    def test_winner_side_takes_no_damage(self):
        game = make_game(seed=62)
        a, b = game.heroes
        game.summon(a, Minion("TEST_W", "W", atk=30, health=30))
        game.run_combat(a, b)
        self.assertEqual(a.health, 30)          # 胜方不掉血
        # 败方伤害 = tier1 + 30/30 随从 tier1 = 2（空板即败）
        self.assertEqual(b.health, 28)


class TestHeroPowerEngineV2(unittest.TestCase):
    """英雄技能引擎 v2: 动态费/替换/双目标/每局次数/下一对手。"""

    REAL_HERO = "BG20_HERO_103"

    def _game(self, seed=70):
        from hsrl2.hero import Hero as HeroCls
        h = HeroCls(self.REAL_HERO, "Blackthorn")
        game = make_game(seed)
        game.heroes[0] = h
        h.game = game
        return game

    def test_cost_override(self):
        game = self._game(seed=71)
        a = game.heroes[0]
        power = game.hero_power_def(a)
        from hsrl2.scripts import REGISTRY
        from hsrl2.tags import GameTag as GT
        calls = []

        class CostlyPower:
            uses_per_turn = 2
            cost_override = staticmethod(lambda hero, g: 2 + len(calls))
            hero_power = staticmethod(lambda hero, g, ctx:
                                      calls.append(1) or None)

        REGISTRY[power.id] = CostlyPower
        try:
            game.start_game()
            a.gold = 5
            self.assertTrue(game.use_hero_power(a))    # cost 2
            self.assertEqual(a.gold, 3)
            self.assertTrue(game.use_hero_power(a))    # cost 3（递增）
            self.assertEqual(a.gold, 0)
            self.assertFalse(game.use_hero_power(a))   # 金币不足
        finally:
            del REGISTRY[power.id]

    def test_replace_hero_power_resets_uses(self):
        game = self._game(seed=72)
        a = game.heroes[0]
        power = game.hero_power_def(a)
        from hsrl2.scripts import REGISTRY
        from hsrl2.tags import GameTag as GT

        class SimplePower:
            uses_per_turn = 1
            hero_power = staticmethod(lambda hero, g, ctx: None)

        class Replacement:
            uses_per_turn = 1
            hero_power = staticmethod(lambda hero, g, ctx: None)

        REGISTRY[power.id] = SimplePower
        # 固定选一个 db 在册的 power id 做替换目标（Cleanse 风格——
        # 任意真实 id 即可，脚本替换后动态注册）
        other = "TB_BaconShop_HP_035"   # Patchwerk power（未注册脚本）
        REGISTRY[other] = Replacement
        try:
            game.start_game()
            a.gold = 5
            self.assertTrue(game.use_hero_power(a))
            self.assertFalse(game.use_hero_power(a))   # 本回合已用
            game.replace_hero_power(a, other)
            self.assertEqual(game.hero_power_def(a).id, other)
            self.assertTrue(game.use_hero_power(a))    # 替换重置次数
            self.assertEqual(a.get(GT.HERO_POWER_USED_THIS_TURN), 1)
        finally:
            del REGISTRY[power.id]
            del REGISTRY[other]

    def test_uses_per_game(self):
        game = self._game(seed=73)
        a = game.heroes[0]
        power = game.hero_power_def(a)
        from hsrl2.scripts import REGISTRY
        from hsrl2.tags import GameTag as GT

        class OncePerGame:
            uses_per_turn = 5
            uses_per_game = 1
            hero_power = staticmethod(lambda hero, g, ctx: None)

        REGISTRY[power.id] = OncePerGame
        try:
            game.start_game()
            a.gold = 10
            self.assertTrue(game.use_hero_power(a))
            a.clear(GT.HERO_POWER_USED_THIS_TURN)
            self.assertFalse(game.use_hero_power(a))   # 每局 1 次耗尽
        finally:
            del REGISTRY[power.id]

    def test_dual_target_chain(self):
        game = self._game(seed=74)
        a = game.heroes[0]
        power = game.hero_power_def(a)
        from hsrl2.scripts import REGISTRY
        m1 = Minion("TEST_D1", "D1", atk=1, health=1)
        m2 = Minion("TEST_D2", "D2", atk=1, health=1)
        game.summon(a, m1)
        game.summon(a, m2)
        picked = []

        class DualPower:
            needs_target = True
            target_count = 2

            @staticmethod
            def target_candidates(hero, g):
                return [m for m in hero.board if not m.dead]

            @staticmethod
            def hero_power(hero, g, ctx):
                picked.append(ctx["target"])
                return None

        REGISTRY[power.id] = DualPower
        try:
            game.start_game()
            a.gold = 5
            self.assertTrue(game.use_hero_power(a))
            self.assertEqual(len(game.pending_choices), 1)
            game.pending_choices.pop(0).choose(0)   # 第一个目标
            self.assertEqual(len(game.pending_choices), 1)
            game.pending_choices.pop(0).choose(0)   # 第二个目标
            self.assertEqual(len(picked), 1)
            self.assertEqual(len(picked[0]), 2)     # 双目标列表
        finally:
            del REGISTRY[power.id]

    def test_next_opponent_warband(self):
        game = self._game(seed=75)
        a, b = game.heroes
        game.start_game()
        game.summon(b, Minion("TEST_NO", "NO", atk=3, health=3))
        game.end_recruit_phase()   # 打完一场（配对快照记录）
        snap = game.next_opponent_warband(a)
        self.assertIsNotNone(snap)
        self.assertTrue(any(m.name == "NO" for m in snap))


if __name__ == "__main__":
    unittest.main()


class TestEconomyOverrideHooks(unittest.TestCase):
    """经济覆写钩子: 购费/刷新费/升级费/展示数/双份三连/跳回合。
    解锁 Millhouse/Sindragosa/Aranna/Clocksworth/Faelin/A.F.Kay。"""

    def _tavern(self, game, hero, card_id="BG25_001"):
        m = game.create_minion(card_id, controller=hero)
        m.zone = Zone.TAVERN
        hero.tavern.append(m)
        return m

    def test_minion_cost_override_and_free_buy(self):
        game = make_game(seed=80)
        a = game.heroes[0]
        game.start_game()
        m = self._tavern(game, a)
        a.gold = 10
        # 平价覆盖（Sindragosa/Millhouse: cost 2）
        a.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 2)
        self.assertTrue(game.buy_from_tavern(a, m))
        self.assertEqual(a.gold, 8)
        # 首买免费（Aranna: 每回合第一只免费）
        m2 = self._tavern(game, a)
        a.set(GameTag.FREE_MINION_BUYS_THIS_TURN, 1)
        self.assertTrue(game.buy_from_tavern(a, m2))
        self.assertEqual(a.gold, 8)
        m3 = self._tavern(game, a)
        self.assertTrue(game.buy_from_tavern(a, m3))
        self.assertEqual(a.gold, 6)   # 免费次数已耗

    def test_refresh_and_upgrade_cost_override(self):
        game = make_game(seed=81)
        a = game.heroes[0]
        game.start_game()
        a.gold = 10
        a.set(GameTag.REFRESH_COST_OVERRIDE, 2)   # Millhouse
        game.refresh_tavern(a)
        self.assertEqual(a.gold, 8)
        a.set(GameTag.UPGRADE_COST_MOD, 1)        # Millhouse 升级+1
        base = a.upgrade_cost
        self.assertTrue(game.upgrade_tavern(a))
        self.assertEqual(a.gold, 8 - base - 1)

    def test_tavern_offer_mod(self):
        game = make_game(seed=82)
        a = game.heroes[0]
        game.start_game()
        a.set(GameTag.TAVERN_OFFER_MOD, -1)       # Sindragosa 少一只
        game.refresh_tavern(a)
        offers = len(a.tavern)
        a.clear(GameTag.TAVERN_OFFER_MOD)
        game.refresh_tavern(a)
        self.assertEqual(len(a.tavern), offers + 1)

    def test_double_triple_and_coin_reward(self):
        game = make_game(seed=83)
        a = game.heroes[0]
        game.start_game()
        a.set(GameTag.TRIPLE_THRESHOLD, 2)        # Clocksworth
        a.set(GameTag.TRIPLE_REWARD_COINS, 2)     # 奖励=2 金币币
        m1 = game.create_minion("BG25_001", controller=a)
        m2 = game.create_minion("BG25_001", controller=a)
        gold_before = a.gold
        hand_before = len(a.hand)
        a.add_to_hand(m1)
        game.check_for_triple(a, m1)
        self.assertEqual(len([m for m in a.hand if not m.is_golden]), 1)
        a.add_to_hand(m2)
        game.check_for_triple(a, m2)
        goldens = [m for m in a.hand
                   if isinstance(m, Minion) and m.is_golden]
        self.assertEqual(len(goldens), 1)   # 2 份即合
        # 奖励替代: 不弹三连发现，而是 2 张 Tavern Coin 入手
        coins = [c for c in a.hand
                 if getattr(c, "card_id", "") == "BG28_810"]
        self.assertEqual(len(coins), 2)
        self.assertFalse(any(c.kind.startswith("discover")
                             for c in game.pending_choices))

    def test_turn_skipped_gates_actions(self):
        game = make_game(seed=84)
        a = game.heroes[0]
        game.start_game()
        a.set(GameTag.TURN_SKIPPED, True)         # Faelin/A.F.Kay
        m = self._tavern(game, a)
        a.gold = 10
        self.assertFalse(game.buy_from_tavern(a, m))
        self.assertFalse(game.upgrade_tavern(a))
        game.end_recruit_phase()                   # 下回合解除
        self.assertFalse(a.get(GameTag.TURN_SKIPPED, False))
        m2 = self._tavern(game, a)
        self.assertTrue(game.buy_from_tavern(a, m2))
