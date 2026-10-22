"""批次 quest_rewards 语义测试（2026-09-01 维修, 41 注册项）。

覆盖: owner 隔离（多英雄 SoC/事件）、跨回合一次性、纯副本、临时属性
过期、池占返、奇偶光环入馆/交换、Discover 法术分支、Destroy 语义。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import BLOOD_GEM_VARIANTS
import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 50, n_heroes: int = 2):
    # 无英雄技能脚本的测试英雄——避免被动（Deathwing 等）污染
    # combat_end / EoT 断言
    g = Game([Hero("TEST_H_" + chr(65 + i), chr(65 + i))
              for i in range(n_heroes)], get_db(), seed=seed)
    g.start_game()
    return g


def grant(game, hero, rid):
    e = game.create_entity(rid, controller=hero)
    hero.quest_rewards.append(e)
    game.run_script_hook(e, "on_bind", ctx={"hero": hero})
    return e


def minion_id(name: str) -> str:
    """按名字在池随从 DB 中查 id（禁止凭记忆写 id）。"""
    for d in get_db().pool_minions():
        if d.name == name:
            return d.id
    raise KeyError(name)


def spell_def(cost_min=None, cost_max=None):
    for d in get_db().pool_spells():
        c = d.cost or 0
        if cost_min is not None and c < cost_min:
            continue
        if cost_max is not None and c > cost_max:
            continue
        return d
    raise KeyError((cost_min, cost_max))


def clear_tavern(game, hero):
    """清空酒馆并正确回池（测试用的确定性起点）。"""
    for e in list(hero.tavern):
        if isinstance(e, Minion):
            game.minion_pool.release(
                e.get(GameTag.TRIPLE_BASE_CARD_ID, None) or e.card_id, 1)
        else:
            game.spell_pool.release(e.card_id)
    hero.tavern.clear()


def tavern_m(game, hero, cid):
    m = game.create_minion(cid, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


class TestRegistry(unittest.TestCase):
    def test_ok_count(self):
        # 精确钉住注册数（防漏注册/误撤注册静默通过）
        from hsrl2.tags import CardType as _CT
        total = [d.id for d in get_db()._by_id.values()
                 if d.card_type == _CT.BACON_QUEST_REWARD
                 and not d.is_golden_def]
        self.assertEqual(len(total), 73)
        registered = [cid for cid in total if cid in REGISTRY]
        # 42 (batch_quest_rewards) + 5 Avenge/Timeline 奖励
        # (batch_quest_rewards2: BG27/28/33 的五个 card_type=40 id)
        # + batch_quest_rewards3（跨批次新增时同步本数字——钉住值用于
        # 捕获"漏注册/误撤注册静默通过"，故新增批次后必须显式更新）
        # + batch_quest_rewards4（"Get a copy of '{0}'" 族 5 张）
        # + batch_quest_rewards5（第二英雄技能槽 1 张: BG33_Reward_017）
        # + batch_discount_misc（Beyond the Mirage 1 张）
        # + batch_hero_rewards_final（并行在飞批次 2 张:
        #   BG24_Reward_113 Ritual Dagger / BG33_Reward_011 Magicfin Relic
        #   ——该批注册后本钉住值必须同步，故 64 → 66）
        # + batch_quest_rewards6（BG27_Reward_812 / BG28_Reward_501）
        # + batch_quest_rewards7（BG24_Reward_719）→ 66 → 69
        # + batch_quest_rewards8（BG24_Reward_362 Essence of Zerus）→ 70
        self.assertEqual(len(registered), 70)

    def test_321t_is_distinct_odd_variant(self):
        self.assertIsNot(REGISTRY["BG24_Reward_321"],
                         REGISTRY["BG24_Reward_321t"])

    def test_norgannon_unlocks_tier7_and_free_upgrade(self):
        """R010: T7 解锁 + 下回合免费升级一次。"""
        g = make_game(seed=51)
        a = g.heroes[0]
        self.assertEqual(g.max_tavern_tier, 6)
        grant(g, a, "BG33_Reward_010")
        self.assertEqual(g.max_tavern_tier, 7)
        tier_before = a.tavern_tier
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(a.tavern_tier, tier_before + 1)
        # once: 再触发不重复升级
        g.events.fire(g, "turn_start", turn=3, hero=a)
        self.assertEqual(a.tavern_tier, tier_before + 1)


class TestR109StolenGold(unittest.TestCase):
    def test_soc_only_affects_owner(self):
        g = make_game()
        a, b = g.heroes
        for hero in (a, b):
            for cid in ("BG20_100", "BG20_101", "BG22_202"):
                g.summon(hero, g.create_minion(cid, controller=hero))
        grant(g, a, "BG24_Reward_109")
        # 对手 SoC 不得触发本奖励（恒真 guard 缺陷回归）
        g.events.fire(g, "start_of_combat", hero=b)
        self.assertFalse(any(m.is_golden for m in a.board))
        self.assertFalse(any(m.is_golden for m in b.board))
        g.events.fire(g, "start_of_combat", hero=a)
        self.assertTrue(a.board[0].is_golden)
        self.assertFalse(a.board[1].is_golden)
        self.assertTrue(a.board[-1].is_golden)
        self.assertFalse(any(m.is_golden for m in b.board))


class TestR111EvilTwin(unittest.TestCase):
    def test_soc_only_owner_and_copies_highest_health(self):
        g = make_game()
        a, b = g.heroes
        g.summon(a, g.create_minion("BG22_202", controller=a))
        high = g.create_minion("BG20_101", controller=a)
        g.summon(a, high)
        high.add_buff(Enchant(atk=0, health=6))
        grant(g, a, "BG24_Reward_111")
        g.events.fire(g, "start_of_combat", hero=b)
        self.assertEqual(len(b.board), 0)
        self.assertEqual(len(a.board), 2)
        g.events.fire(g, "start_of_combat", hero=a)
        self.assertEqual(len(a.board), 3)
        copy = a.board[-1]
        self.assertEqual(copy.card_id, "BG20_101")
        self.assertEqual(copy.max_health, high.max_health)


class TestR115TheotarsParasol(unittest.TestCase):
    def test_rightmost_stealth_health(self):
        g = make_game()
        a = g.heroes[0]
        m1 = g.create_minion("BG25_001", controller=a)
        m2 = g.create_minion("BG25_001", controller=a)
        g.summon(a, m1)
        g.summon(a, m2)
        grant(g, a, "BG24_Reward_115")
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertTrue(m2.has(GameTag.STEALTH))
        self.assertEqual(m2.max_health, 1 + 8)

    def test_health_is_permanent_and_stealth_expires_only_owner(self):
        g = make_game()
        a, b = g.heroes
        m = g.create_minion("BG25_001", controller=a)
        g.summon(a, m)
        grant(g, a, "BG24_Reward_115")
        g.events.fire(g, "turn_end", turn=g.turn)
        # +8 Health 是永久附魔（temporary 惰性缺陷回归）
        self.assertTrue(all(not x.temporary for x in m._buffs))
        g.events.fire(g, "turn_start", turn=2, hero=b)
        self.assertTrue(m.has(GameTag.STEALTH))
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertFalse(m.has(GameTag.STEALTH))


class TestR123ExquisiteConch(unittest.TestCase):
    def test_other_hero_battlecry_does_not_consume(self):
        g = make_game()
        a, b = g.heroes
        bm = g.create_minion("BG20_100", controller=b)
        g.summon(b, bm)
        am = g.create_minion("BG20_100", controller=a)
        g.summon(a, am)
        grant(g, a, "BG24_Reward_123")
        g.events.fire(g, "battlecry_trigger", minion=bm)
        self.assertFalse(a._r123_used)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)
        g.events.fire(g, "battlecry_trigger", minion=am)
        self.assertTrue(a._r123_used)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 2)
        g.events.fire(g, "battlecry_trigger", minion=am)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 2)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        g.events.fire(g, "battlecry_trigger", minion=am)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 4)


class TestR129SecretSinstone(unittest.TestCase):
    def test_spell_option_creates_spell_copy(self):
        g = make_game()
        a = g.heroes[0]
        sdef = spell_def()
        grant(g, a, "BG24_Reward_129")
        g.events.fire(g, "card_discovered", kind="discover_spell",
                      hero=a, option=sdef.id)
        self.assertTrue(a.hand)
        self.assertIsInstance(a.hand[-1], Spell)
        self.assertEqual(a.hand[-1].card_id, sdef.id)

    def test_minion_option_creates_minion_copy(self):
        g = make_game()
        a = g.heroes[0]
        grant(g, a, "BG24_Reward_129")
        g.events.fire(g, "card_discovered", kind="discover_minion",
                      hero=a, option="BG20_101")
        self.assertIsInstance(a.hand[-1], Minion)
        self.assertEqual(a.hand[-1].card_id, "BG20_101")

    def test_other_hero_ignored(self):
        g = make_game()
        a, b = g.heroes
        grant(g, a, "BG24_Reward_129")
        g.events.fire(g, "card_discovered", kind="discover_minion",
                      hero=b, option="BG20_101")
        self.assertEqual(a.hand, [])

    def test_dark_gift_option_not_copied(self):
        # dark_gift 选项是 card_type=5 的非卡牌效果实体（不得造伪法术）
        gift_id = get_db().dark_gifts()[0].id
        g = make_game()
        a = g.heroes[0]
        grant(g, a, "BG24_Reward_129")
        g.events.fire(g, "card_discovered", kind="dark_gift",
                      hero=a, option=gift_id)
        self.assertEqual(a.hand, [])


class TestR138VictimsSpecter(unittest.TestCase):
    def test_plain_copy_strips_buffs_and_golden(self):
        g = make_game()
        a, b = g.heroes
        d = get_db().get("BG20_101")
        m = g.create_minion("BG20_101", controller=a, golden=True)
        m.add_buff(Enchant(atk=3, health=3))
        g.combat_death_log = [m]
        grant(g, a, "BG24_Reward_138")
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result=None)
        self.assertTrue(a.hand)
        cp = a.hand[-1]
        self.assertIsInstance(cp, Minion)
        self.assertFalse(cp.is_golden)
        self.assertEqual(cp.card_id, d.id)
        self.assertEqual(cp.atk, d.atk)
        self.assertEqual(cp.max_health, d.health)

    def test_unrelated_combat_ignored(self):
        g = make_game()
        a, b = g.heroes
        m = g.create_minion("BG20_101", controller=a)
        g.combat_death_log = [m]
        grant(g, a, "BG24_Reward_138")
        g.events.fire(g, "combat_end", hero_a=b, hero_b=b, result=None)
        self.assertEqual(a.hand, [])


class TestR308TealTigerSapphire(unittest.TestCase):
    def test_survivor_gains_once_per_refresh(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        m = tavern_m(g, a, "BG20_101")
        base_atk, base_hp = m.atk, m.max_health
        grant(g, a, "BG24_Reward_308")
        g.events.fire(g, "tavern_refresh", hero=a)
        g.events.fire(g, "tavern_refresh", hero=a)
        # 两次刷新幸存 → 累计 +2（而非旧实现的 +3）
        self.assertEqual(m.atk, base_atk + 2)
        self.assertEqual(m.max_health, base_hp + 2)

    def test_other_hero_refresh_ignored(self):
        g = make_game()
        a, b = g.heroes
        clear_tavern(g, a)
        m = tavern_m(g, a, "BG20_101")
        base = m.atk
        grant(g, a, "BG24_Reward_308")
        g.events.fire(g, "tavern_refresh", hero=b)
        self.assertEqual(m.atk, base)


class TestR309DevilsInTheDetails(unittest.TestCase):
    def test_two_consumes_pool_return_and_no_stale_candidate(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        left = g.create_minion("BG22_202", controller=a)
        right = g.create_minion("BG22_202", controller=a)
        g.summon(a, left)
        g.summon(a, right)
        for cid in ("BG20_100", "BG20_101"):
            self.assertTrue(g.minion_pool.acquire(cid))
            tavern_m(g, a, cid)
        avail0 = (g.minion_pool.available("BG20_100")
                  + g.minion_pool.available("BG20_101"))
        atk0 = left.atk + right.atk
        grant(g, a, "BG24_Reward_309")
        g.events.fire(g, "turn_end", turn=1)
        self.assertEqual(a.tavern, [])
        self.assertGreater(left.atk + right.atk, atk0)
        # 被吞噬的酒馆随从回池（池泄漏缺陷回归）
        self.assertEqual(g.minion_pool.available("BG20_100")
                         + g.minion_pool.available("BG20_101"), avail0 + 2)
        # 第二次 board-end 不得因陈旧候选抛 ValueError
        g.events.fire(g, "turn_end", turn=1)


class TestR311AnotherHiddenBody(unittest.TestCase):
    def test_discover_happens_once_at_bind(self):
        g = make_game()
        a = g.heroes[0]
        self.assertEqual(g.pending_choices, [])
        grant(g, a, "BG24_Reward_311")
        self.assertEqual(len(g.pending_choices), 1)
        c = g.pending_choices[0]
        self.assertEqual(c.kind, "discover_minion")
        # Discover 选项数 = 引擎默认 3（`num(0)` 不是选项数——
        # 2026-09-01 对抗审计修正 count=1 单选退化）
        self.assertEqual(len(c.options), 3)
        for opt in c.options:
            self.assertEqual(get_db().get(opt).tech_level, a.tavern_tier)
        # 无时机子句 → 不得每回合重复（时机缺陷回归）
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(len(g.pending_choices), 1)


class TestR312StaffOfOrigination(unittest.TestCase):
    def test_soc_buff_expires_at_own_combat_end(self):
        g = make_game()
        a, b = g.heroes
        m = g.create_minion("BG22_202", controller=a)
        g.summon(a, m)
        base = m.atk
        grant(g, a, "BG24_Reward_312")
        g.events.fire(g, "start_of_combat", hero=a)
        self.assertEqual(m.atk, base + 12)
        g.events.fire(g, "start_of_combat", hero=b)
        self.assertEqual(m.atk, base + 12)     # 对手 SoC 不叠加
        g.events.fire(g, "combat_end", hero_a=b, hero_b=b, result=None)
        self.assertEqual(m.atk, base + 12)     # 他人战斗不触发过期
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result=None)
        self.assertEqual(m.atk, base)          # 战斗结束精确过期


class TestR321AlterEgo(unittest.TestCase):
    def test_even_aura_applies_then_swaps_to_odd(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        even = tavern_m(g, a, minion_id("Roadboar"))          # T2
        odd = tavern_m(g, a, minion_id("Razorfen Geomancer"))  # T1
        e_atk, o_atk = even.atk, odd.atk
        grant(g, a, "BG24_Reward_321")
        self.assertEqual(even.atk, e_atk + 7)
        self.assertEqual(odd.atk, o_atk)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(even.atk, e_atk)      # 交换后移除旧光环
        self.assertEqual(odd.atk, o_atk + 7)

    def test_321t_is_odd_and_new_entries_get_aura(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        odd = tavern_m(g, a, minion_id("Razorfen Geomancer"))
        grant(g, a, "BG24_Reward_321t")
        self.assertEqual(odd.atk, 2 + 7)
        new_even = tavern_m(g, a, minion_id("Bonker"))       # T4
        g.events.fire(g, "tavern_refresh", hero=a)
        self.assertEqual(new_even.atk, 2)      # 奇数档位 → 偶数不入馆光环
        new_odd = tavern_m(g, a, minion_id("Deep-Sea Angler"))  # T3
        g.events.fire(g, "tavern_refresh", hero=a)
        self.assertEqual(new_odd.atk, 2 + 7)


class TestR331MenagerieMayhem(unittest.TestCase):
    def test_eot_per_type(self):
        g = make_game()
        a = g.heroes[0]
        m1 = g.create_minion("BG25_001", controller=a)   # Beast
        g.summon(a, m1)
        grant(g, a, "BG24_Reward_331")
        g.events.fire(g, "turn_end", turn=g.turn)
        buffs = sum(b.atk for b in m1._buffs)
        self.assertEqual(buffs, 1)

    def test_amalgam_counts_as_a_type(self):
        g = make_game()
        a = g.heroes[0]
        m = g.create_minion("BG27_080", controller=a)    # Race.ALL
        g.summon(a, m)
        grant(g, a, "BG24_Reward_331")
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(m.atk, 3 + 1)


class TestR350(unittest.TestCase):
    def test_triple_threshold_2(self):
        g = make_game()
        a = g.heroes[0]
        grant(g, a, "BG24_Reward_350")
        self.assertEqual(a.get(GameTag.TRIPLE_THRESHOLD), 2)


class TestR361HiddenTreasureVault(unittest.TestCase):
    def test_starts_at_num0_and_improves(self):
        g = make_game()
        a = g.heroes[0]
        base = get_db().get("BG24_Reward_361").num(0)
        grant(g, a, "BG24_Reward_361")
        g0 = a.gold
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(a.gold, g0 + base)          # 首回合 = num(0)
        g.events.fire(g, "turn_start", turn=3, hero=a)
        self.assertEqual(a.gold, g0 + base + 2 * base)  # 每回合 +num(0)


class TestR363EtherealEvidence(unittest.TestCase):
    def test_exactly_two_options_no_skip(self):
        g = make_game()
        a = g.heroes[0]
        grant(g, a, "BG24_Reward_363")
        g.events.fire(g, "turn_start", turn=2, hero=a)
        ch = [c for c in g.pending_choices if c.kind == "reward_replace"]
        self.assertEqual(len(ch), 1)
        opts = ch[0].options
        self.assertEqual(len(opts), 2)
        self.assertNotIn(None, opts)
        for o in opts:
            self.assertTrue(o.startswith("BG24_Reward_"))
            self.assertNotEqual(o, "BG24_Reward_363")

    def test_new_choice_replaces_previous(self):
        g = make_game()
        a = g.heroes[0]
        src = grant(g, a, "BG24_Reward_363")
        g.events.fire(g, "turn_start", turn=2, hero=a)
        ch = [c for c in g.pending_choices if c.kind == "reward_replace"][-1]
        ch.choose(0)
        first = a._r363_current
        self.assertIn(first, a.quest_rewards)
        self.assertIn(src, a.quest_rewards)
        g.events.fire(g, "turn_start", turn=3, hero=a)
        ch = [c for c in g.pending_choices if c.kind == "reward_replace"][-1]
        ch.choose(0)
        self.assertNotIn(first, a.quest_rewards)     # 旧奖励被替换
        self.assertIn(a._r363_current, a.quest_rewards)
        self.assertIn(src, a.quest_rewards)          # 本源持续每回合触发


class TestR364VolatileVenom(unittest.TestCase):
    def test_attack_destroys_through_divine_shield(self):
        g = make_game()
        a = g.heroes[0]
        m = g.create_minion(minion_id("Tad"), controller=a)
        g.summon(a, m)
        m.set(GameTag.DIVINE_SHIELD, True)
        grant(g, a, "BG24_Reward_364")
        self.assertEqual(m.atk, 2 + 7)
        g.events.fire(g, "after_attack", attacker=m, defender=m,
                      excess_damage=0, defender_hp_before=1)
        self.assertTrue(m.dead)
        self.assertNotIn(m, a.board)
        # Destroy 无视圣盾（圣盾未被伤害消耗）
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))


class TestR708BloodGoblet(unittest.TestCase):
    def test_attack_equals_missing_health(self):
        g = make_game()
        a = g.heroes[0]
        a.health = C.HERO_BASE_HEALTH - 7
        m = g.create_minion("BG22_202", controller=a)
        g.summon(a, m)
        atk0 = m.atk
        grant(g, a, "BG24_Reward_708")
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(m.atk, atk0 + 7)

    def test_full_health_no_buff(self):
        g = make_game()
        a = g.heroes[0]
        m = g.create_minion("BG22_202", controller=a)
        g.summon(a, m)
        atk0 = m.atk
        grant(g, a, "BG24_Reward_708")
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(m.atk, atk0)


class TestR806DoppelgangersLocket(unittest.TestCase):
    def test_discovers_from_opponent_warband_keeps_enchantments(self):
        g = make_game()
        a, b = g.heroes
        enemy = g.create_minion("BG20_101", controller=b)
        enemy.add_buff(Enchant(atk=3, health=3))
        # "your last opponent's warband" → last_opponent_warband 的数据面
        # （RULES §4.8a: 上一场战斗的战前战团快照）
        g._last_opponent_board = {a: [enemy], b: [enemy]}
        grant(g, a, "BG27_Reward_806")
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result=None)
        ch = [c for c in g.pending_choices if c.kind == "discover_minion"]
        self.assertEqual(len(ch), 1)
        self.assertIn(enemy, ch[0].options)
        ch[0].choose(0)
        cp = a.hand[-1]
        self.assertIsInstance(cp, Minion)
        self.assertEqual(cp.card_id, "BG20_101")
        self.assertEqual(cp.atk, 2 + 3)

    def test_unrelated_combat_no_offer(self):
        g = make_game()
        a, b = g.heroes
        g._last_opponent_board = {a: [], b: []}
        grant(g, a, "BG27_Reward_806")
        g.events.fire(g, "combat_end", hero_a=b, hero_b=b, result=None)
        self.assertEqual(g.pending_choices, [])


class TestR810MapOfTheUnknown(unittest.TestCase):
    def test_pre_play_type_set(self):
        g = make_game()
        a = g.heroes[0]
        undead = g.create_minion(minion_id("Risen Rider"), controller=a)
        g.summon(a, undead)
        murloc = g.create_minion(minion_id("Tad"), controller=a)
        g.summon(a, murloc)
        u_atk = undead.atk
        grant(g, a, "BG27_Reward_810")
        g.events.fire(g, "card_played", card=murloc, target=None)
        self.assertEqual(undead.atk, u_atk + 2)
        self.assertEqual(murloc.atk, 2)     # 刚打出者不给（新类型）

    def test_same_type_no_trigger(self):
        g = make_game()
        a = g.heroes[0]
        undead = g.create_minion(minion_id("Risen Rider"), controller=a)
        g.summon(a, undead)
        grant(g, a, "BG27_Reward_810")
        second = g.create_minion(minion_id("Risen Rider"), controller=a)
        g.summon(a, second)
        u_atk = undead.atk
        g.events.fire(g, "card_played", card=second, target=None)
        self.assertEqual(undead.atk, u_atk)


class TestR811(unittest.TestCase):
    def test_minions_cost_2(self):
        g = make_game()
        a = g.heroes[0]
        grant(g, a, "BG27_Reward_811")
        self.assertEqual(a.get(GameTag.TAVERN_MINION_COST_OVERRIDE), 2)


class TestR815EndlessBloodMoon(unittest.TestCase):
    def test_bonus_and_two_gems_per_turn(self):
        g = make_game()
        a = g.heroes[0]
        gem_id = BLOOD_GEM_VARIANTS[None]
        grant(g, a, "BG27_Reward_815")
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH), 1)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        gems = [c for c in a.hand if c.card_id == gem_id]
        self.assertEqual(len(gems), 2)


class TestR502tSplittingScroll(unittest.TestCase):
    def test_expensive_spell_gets_extra_copy(self):
        g = make_game()
        a = g.heroes[0]
        sdef = spell_def(cost_min=3)
        s = g.create_spell(sdef.id, controller=a)
        a.add_to_hand(s)
        grant(g, a, "BG28_Reward_502")
        g.events.fire(g, "spell_bought", spell=s, hero=a)
        copies = [c for c in a.hand if c.card_id == sdef.id]
        self.assertEqual(len(copies), 2)

    def test_cheap_spell_no_copy(self):
        g = make_game()
        a = g.heroes[0]
        sdef = spell_def(cost_max=2)
        s = g.create_spell(sdef.id, controller=a)
        a.add_to_hand(s)
        grant(g, a, "BG28_Reward_502")
        g.events.fire(g, "spell_bought", spell=s, hero=a)
        copies = [c for c in a.hand if c.card_id == sdef.id]
        self.assertEqual(len(copies), 1)

    def test_other_hero_ignored(self):
        g = make_game()
        a, b = g.heroes
        sdef = spell_def(cost_min=3)
        s = g.create_spell(sdef.id, controller=b)
        b.add_to_hand(s)
        grant(g, a, "BG28_Reward_502")
        g.events.fire(g, "spell_bought", spell=s, hero=b)
        self.assertEqual(a.hand, [])


class TestR506DoubleHeadedReward(unittest.TestCase):
    def test_first_buy_plain_copy_then_once_per_turn(self):
        g = make_game()
        a = g.heroes[0]
        d = get_db().get("BG20_101")
        m = g.create_minion("BG20_101", controller=a, golden=True)
        m.add_buff(Enchant(atk=3, health=3))
        grant(g, a, "BG28_Reward_506")
        g.events.fire(g, "minion_bought", minion=m)
        self.assertEqual(len(a.hand), 1)
        cp = a.hand[0]
        self.assertIsInstance(cp, Minion)
        self.assertFalse(cp.is_golden)
        self.assertEqual(cp.card_id, d.id)
        self.assertEqual(cp.atk, d.atk)
        g.events.fire(g, "minion_bought", minion=m)
        self.assertEqual(len(a.hand), 1)     # 每回合一次
        g.events.fire(g, "turn_start", turn=2, hero=a)
        g.events.fire(g, "minion_bought", minion=m)
        self.assertEqual(len(a.hand), 2)     # 新回合重置


class TestR508GiftOfTheGoldenKobold(unittest.TestCase):
    def test_threshold_from_data_skips_golden(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        need = get_db().get("BG28_Reward_508").num(0)
        already = g.create_minion("BG20_104", controller=a, golden=True)
        low = g.create_minion("BG20_100", controller=a)
        a.tavern += [already, low]
        grant(g, a, "BG28_Reward_508")
        for _ in range(need):
            g.events.fire(g, "tavern_refresh", hero=a)
        # 已是金色者被跳过 → 非金的最低 tier 幸运获得
        self.assertTrue(low.is_golden)


class TestR514UntamedSorcery(unittest.TestCase):
    def test_casts_spells_on_turn_start(self):
        g = make_game(seed=7)
        a = g.heroes[0]
        g.summon(a, g.create_minion("BG22_202", controller=a))
        before = g.spell_pool.total_remaining()
        grant(g, a, "BG28_Reward_514")
        g.events.fire(g, "turn_start", turn=2, hero=a)
        # 文本 "cast 5 random Tavern spells"——精确 5，非 >=1
        self.assertEqual(
            a.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0), 5)
        # 不得池膨胀（acquire/release 配平；获取类法术只会消耗）
        self.assertLessEqual(g.spell_pool.total_remaining(), before)

    def test_empty_board_does_not_crash(self):
        g = make_game(seed=3)
        a = g.heroes[0]
        before = g.spell_pool.total_remaining()
        grant(g, a, "BG28_Reward_514")
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertLessEqual(g.spell_pool.total_remaining(), before)


class TestR515StashOfTheScribe(unittest.TestCase):
    def test_gets_three_spells_and_occupies_pool(self):
        g = make_game(seed=11)
        a = g.heroes[0]
        before = g.spell_pool.total_remaining()
        grant(g, a, "BG28_Reward_515")
        g.events.fire(g, "turn_start", turn=2, hero=a)
        spells = [c for c in a.hand if isinstance(c, Spell)]
        self.assertEqual(len(spells), 3)
        self.assertEqual(before - g.spell_pool.total_remaining(), 3)


class TestR013GoldenForge(unittest.TestCase):
    def test_turn_start_goldenizes_highest_non_golden(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        already = g.create_minion("BG20_104", controller=a, golden=True)
        low = g.create_minion("BG20_100", controller=a)
        a.tavern += [already, low]
        grant(g, a, "BG33_Reward_013")
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertTrue(low.is_golden)


class TestR012(unittest.TestCase):
    def test_gold_and_cap(self):
        g = make_game()
        a = g.heroes[0]
        gold_before = a.gold
        grant(g, a, "BG33_Reward_012")
        self.assertEqual(a.gold, gold_before + 5)
        self.assertEqual(a.income_cap, 10 + 5)


class TestR014QuaintBoutique(unittest.TestCase):
    def test_next_turn_once_and_owner_scoped(self):
        g = make_game()
        a, b = g.heroes
        grant(g, a, "BG33_Reward_014")
        g0 = a.gold
        g.events.fire(g, "turn_start", turn=2, hero=b)
        self.assertEqual(a.gold, g0)          # 他人回合不消耗 once
        self.assertFalse(any(c.kind == "trinket_offer"
                             for c in g.pending_choices))
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(a.gold, g0 + 4)
        self.assertTrue(any(c.kind == "trinket_offer"
                            for c in g.pending_choices))
        g.events.fire(g, "turn_start", turn=3, hero=a)
        self.assertEqual(a.gold, g0 + 4)      # 一次性


class TestR015JumboWarehouse(unittest.TestCase):
    def test_next_turn_once_greater_offer(self):
        g = make_game()
        a, b = g.heroes
        grant(g, a, "BG33_Reward_015")
        g0 = a.gold
        g.events.fire(g, "turn_start", turn=2, hero=b)
        self.assertEqual(a.gold, g0)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(a.gold, g0 + 4)
        self.assertTrue(any(c.kind == "trinket_offer"
                            for c in g.pending_choices))
        g.events.fire(g, "turn_start", turn=3, hero=a)
        self.assertEqual(a.gold, g0 + 4)


class TestR125(unittest.TestCase):
    def test_minions_plus4_atk(self):
        g = make_game()
        a = g.heroes[0]
        m = g.create_minion("BG25_001", controller=a)
        g.summon(a, m)
        grant(g, a, "BG24_Reward_125")
        self.assertEqual(m.atk, 2 + 4)


class TestR107TwoBattlecries(unittest.TestCase):
    def test_eot_triggers_two_friendly_battlecries(self):
        g = make_game()
        a = g.heroes[0]
        for _ in range(3):
            g.summon(a, g.create_minion("BG20_100", controller=a))
        grant(g, a, "BG24_Reward_107")
        g.events.fire(g, "turn_end", turn=1)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 2)


class TestR128TavernRefreshBuff(unittest.TestCase):
    def test_random_tavern_minion_gets_stats_and_shield(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        m = tavern_m(g, a, "BG22_202")
        grant(g, a, "BG24_Reward_128")
        g.events.fire(g, "tavern_refresh", hero=a)
        self.assertEqual(m.atk, 2 + 6)
        self.assertEqual(m.max_health, 2 + 6)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))


class TestR131HandBuff(unittest.TestCase):
    def test_start_of_turn_buffs_hand_minion(self):
        g = make_game()
        a = g.heroes[0]
        m = g.create_minion("BG22_202", controller=a)
        a.add_to_hand(m)
        grant(g, a, "BG24_Reward_131")
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(m.atk, 2 + 12)
        self.assertEqual(m.max_health, 2 + 12)


class TestR136LowTierBuff(unittest.TestCase):
    def test_eot_buffs_up_to_three_low_tier_minions(self):
        g = make_game()
        a = g.heroes[0]
        ms = [g.create_minion("BG22_202", controller=a) for _ in range(3)]
        for m in ms:
            g.summon(a, m)
        grant(g, a, "BG24_Reward_136")
        g.events.fire(g, "turn_end", turn=1)
        for m in ms:
            self.assertEqual(m.atk, 2 + 3)


class TestR305SellStatsToTavern(unittest.TestCase):
    def test_sold_minion_stats_go_to_tavern_minion(self):
        g = make_game()
        a = g.heroes[0]
        clear_tavern(g, a)
        target = tavern_m(g, a, "BG22_202")
        t_atk, t_hp = target.atk, target.max_health
        sold = g.create_minion("BG20_101", controller=a)
        sold.add_buff(Enchant(atk=3, health=3))
        grant(g, a, "BG24_Reward_305")
        g.events.fire(g, "minion_sold", minion=sold)
        self.assertEqual(target.atk, t_atk + sold.atk)
        self.assertEqual(target.max_health, t_hp + sold.max_health)


class TestR503BuyStatsToFriendly(unittest.TestCase):
    def test_bought_minion_stats_go_to_random_friendly(self):
        g = make_game()
        a = g.heroes[0]
        target = g.create_minion("BG22_202", controller=a)
        g.summon(a, target)
        bought = g.create_minion("BG20_101", controller=a)
        bought.add_buff(Enchant(atk=2, health=2))
        grant(g, a, "BG27_Reward_503")
        g.events.fire(g, "minion_bought", minion=bought)
        self.assertEqual(target.atk, 2 + bought.atk)


class TestR712PlaySameTier(unittest.TestCase):
    def test_two_others_of_same_tier_get_plus4(self):
        g = make_game()
        a = g.heroes[0]
        others = [g.create_minion("BG22_202", controller=a) for _ in range(2)]
        for m in others:
            g.summon(a, m)
        played = g.create_minion("BG22_202", controller=a)
        g.summon(a, played)
        grant(g, a, "BG24_Reward_712")
        g.events.fire(g, "card_played", card=played, target=None)
        for m in others:
            self.assertEqual(m.atk, 2 + 4)
        self.assertEqual(played.atk, 2)


class TestR804NoTauntBuff(unittest.TestCase):
    def test_non_taunt_gets_per_taunt(self):
        g = make_game()
        a = g.heroes[0]
        taunt = g.create_minion("BG27_080", controller=a)   # Taunt
        g.summon(a, taunt)
        plain = g.create_minion("BG22_202", controller=a)
        g.summon(a, plain)
        grant(g, a, "BG27_Reward_804")
        g.events.fire(g, "turn_end", turn=1)
        self.assertEqual(plain.atk, 2 + 1)
        self.assertEqual(plain.max_health, 2 + 2)
        self.assertEqual(taunt.atk, 3)      # 嘲讽自身不受益


class TestR003DivineShield(unittest.TestCase):
    def test_soc_leftmost_gains_divine_shield(self):
        g = make_game()
        a = g.heroes[0]
        left = g.create_minion("BG22_202", controller=a)
        right = g.create_minion("BG20_100", controller=a)
        g.summon(a, left)
        g.summon(a, right)
        grant(g, a, "BG33_Reward_003")
        g.events.fire(g, "start_of_combat", hero=a)
        self.assertTrue(left.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(right.has(GameTag.DIVINE_SHIELD))


if __name__ == "__main__":
    unittest.main()
