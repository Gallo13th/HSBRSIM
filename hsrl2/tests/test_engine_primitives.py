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
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.actions.stats import Buff
from hsrl2.combat import execute_immediate_attack
from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.events import Listener
from hsrl2.game import (BONUS_KEYWORD_TAGS, Game, GameStateError,
                        PendingChoice)
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType, GameTag, Race, Zone

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
        """Bounty 是池法术 → 帮助函数必须占池（每张 1 份; 2026-09-02
        对抗审查修正了"不占池"的错误注记，并防消费者漏记账）。"""
        game = make_game(seed=19)
        before = {cid: game.spell_pool.available(cid)
                  for cid in ("BG33_811", "BG33_812", "BG33_813",
                              "BG33_814", "BG33_815")}
        cid = random_bounty_card_id(game)
        self.assertIn(cid, before)
        self.assertEqual(game.spell_pool.available(cid), before[cid] - 1)
        # 正对照: 全部耗尽 → None（不静默返回池外卡）
        for c in before:
            game.spell_pool._available[c] = 0
        self.assertIsNone(random_bounty_card_id(game))


class TestTriggerDeathrattleEntry(unittest.TestCase):
    """`Game.trigger_deathrattle` 统一入口（RULES §6.20）。

    "Trigger a Deathrattle" 与真实亡语等价: Titus 倍率 / dr_extra /
    dr_first 全部生效，并计入 `COUNTER_DEATHRATTLES` + 广播
    `deathrattle_trigger`。旧实现各脚本直调 `run_script_hook` → 绕开
    全部配额（2026-09-02 对抗审查证伪 BG36_MagicItem_208t）。
    """

    TITUS = "BG25_354"          # Titus Rivendare（DEATHRATTLE_DOUBLER）

    def test_titus_doubles_triggered_deathrattle(self):
        game = make_game(seed=11)
        a, b = game.heroes
        calls = []

        class Probe:
            @staticmethod
            def deathrattle(source, g, ctx=None):
                calls.append(source)

        target = Minion("TEST_DR", "DR", atk=1, health=1)
        target.game = game
        target.controller = a
        target.scripts = Probe
        target.set(GameTag.DEATHRATTLE, True)
        game.summon(a, target)
        # 无 Titus → 1 次
        self.assertEqual(game.trigger_deathrattle(target), 1)
        self.assertEqual(len(calls), 1)
        # Titus 在场 → 2 次（DEATHRATTLE_DOUBLER 光环）
        from hsrl2.scripts.batches.batch_doublers import TitusRivendareScript
        titus = game.create_minion(self.TITUS, controller=a)
        titus.scripts = TitusRivendareScript
        game.summon(a, titus)
        self.assertTrue(titus.has(GameTag.DEATHRATTLE_DOUBLER))
        self.assertEqual(game.trigger_deathrattle(target), 2)
        self.assertEqual(len(calls), 3)

    def test_transform_reruns_passive_init(self):
        """Transform 换卡面后**被动**能力立即生效（RULES §6.21）。

        旧实现只替换实体、不重跑被动初始化 → 变身成 Titus/Drakkari/
        Groundbreaker 的实体完全空转（2026-09-02 对抗审查证伪
        BG35_MagicItem_924 场景）。
        """
        game = make_game(seed=21)
        a, b = game.heroes
        from hsrl2.actions.stats import Transform
        m = game.create_minion("BG25_001", controller=a)
        game.summon(a, m)
        self.assertFalse(m.has(GameTag.DEATHRATTLE_DOUBLER))
        game.run_actions(Transform(m, self.TITUS))
        new = [x for x in a.board if x.card_id == self.TITUS][0]
        self.assertTrue(new.has(GameTag.DEATHRATTLE_DOUBLER))

    def test_counts_trigger_and_fires_event(self):
        game = make_game(seed=12)
        a, b = game.heroes
        seen = []

        class Probe:
            @staticmethod
            def deathrattle(source, g, ctx=None):
                pass

        target = Minion("TEST_DR2", "DR2", atk=1, health=1)
        target.game = game
        target.controller = a
        target.scripts = Probe
        target.set(GameTag.DEATHRATTLE, True)
        game.summon(a, target)
        game.events.register(Listener(event="deathrattle_trigger",
                                      owner=a,
                                      callback=lambda g, minion=None,
                                      **kw: seen.append(minion)))
        before = a.get(GameTag.COUNTER_DEATHRATTLES, 0)
        game.trigger_deathrattle(target, hero=a)
        self.assertEqual(a.get(GameTag.COUNTER_DEATHRATTLES, 0), before + 1)
        self.assertEqual(seen, [target])

    def test_real_death_path_applies_titus(self):
        """真实死亡路径与统一入口同源（`_process_single_death`）。"""
        game = make_game(seed=13)
        a, b = game.heroes
        calls = []

        class Probe:
            @staticmethod
            def deathrattle(source, g, ctx=None):
                calls.append(source)

        from hsrl2.scripts.batches.batch_doublers import TitusRivendareScript
        titus = game.create_minion(self.TITUS, controller=a)
        titus.scripts = TitusRivendareScript
        game.summon(a, titus)
        m = game.create_minion("BG25_001", controller=a)
        game.summon(a, m)
        m.scripts = Probe
        m.set(GameTag.DEATHRATTLE, True)
        m.set(GameTag.HEALTH, 0)
        game._process_single_death(m)
        self.assertEqual(len(calls), 2)          # Titus ×2
        self.assertEqual(a.get(GameTag.COUNTER_DEATHRATTLES, 0), 1)


class TestMagneticCombatRestore(unittest.TestCase):
    """战斗内磁力吸附不延续到招募阶段（RULES §3.5/§6.14）。

    旧实现 `_magnetic_stack` 不入 `run_combat` 快照 → SoC 吸附
    （Assembler Portrait `BG36_MagicItem_841` 家族）每场战斗重复追加、
    亡语/钩子栈无界累积（2026-09-02 对抗审查上报缺口）。
    """

    def test_combat_attach_is_rolled_back(self):
        game = make_game(seed=31)
        a, b = game.heroes
        db = get_db()
        mechs = [d for d in db.pool_minions() if "magnetic" in d.keywords]
        self.assertTrue(mechs)
        host = Minion("TEST_HOST", "Host", atk=3, health=3, race=Race.MECH)
        game.summon(a, host)
        mag = game.create_minion(mechs[0].id, controller=a)
        during = {}

        def soc(g, hero=None, **kw):
            if hero is not a:
                return
            g.attach_magnetic(a, mag, host)
            during["stack"] = list(g._magnetic_stack.get(host.uuid, []))

        game.events.register(Listener(event="start_of_combat", owner=a,
                                      callback=soc))
        game.run_combat(a, b)
        # 战斗内确实吸附（探针证明路径发生）
        self.assertEqual(during["stack"], [mechs[0].id])
        # 战后恢复: 招募期不残留战斗内附件
        self.assertEqual(game._magnetic_stack.get(host.uuid, []), [])
        self.assertEqual(host.atk, 3)
        self.assertEqual(host.max_health, 3)


class TestDestroyMinionEntry(unittest.TestCase):
    """`Game.destroy_minion` 统一摧毁入口（RULES §7.4.11）。

    "After/Whenever **you destroy** a minion outside combat"
    （Kel'Thuzad Portrait `BG32_MagicItem_204` / Maw Caster Portrait
    `BG32_MagicItem_205`）的唯一观察点；旧实现各处直接 `health = 0`，
    `death` 事件无施动者、无法区分摧毁与战斗/自伤死亡。
    """

    def test_broadcasts_with_actor_and_combat_flag(self):
        game = make_game(seed=41)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="minion_destroyed", owner=a,
            callback=lambda g, hero=None, minion=None, source=None,
            in_combat=None, **kw: seen.append(
                (hero, minion, in_combat))))
        victim = game.create_minion("BG25_013", controller=b)  # 无关键词
        game.summon(b, victim)
        self.assertTrue(game.destroy_minion(victim, hero=a, source=a))
        self.assertEqual(len(seen), 1)
        hero, minion, in_combat = seen[0]
        self.assertIs(hero, a)                 # 施动方 = A（不是随从主人）
        self.assertIs(minion, victim)
        self.assertFalse(in_combat)
        self.assertTrue(victim.dead)
        self.assertNotIn(victim, b.board)      # 完整死亡链（离场 + 回池）

    def test_no_event_when_already_dead_or_off_board(self):
        game = make_game(seed=42)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="minion_destroyed", owner=a,
            callback=lambda g, **kw: seen.append(1)))
        m = game.create_minion("BG25_013", controller=a)
        game.summon(a, m)
        self.assertTrue(game.destroy_minion(m, hero=a))    # 首次摧毁
        self.assertFalse(game.destroy_minion(m, hero=a))   # 已死 → no-op
        self.assertEqual(len(seen), 1)

    def test_default_actor_from_source_controller(self):
        game = make_game(seed=43)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="minion_destroyed", owner=a,
            callback=lambda g, hero=None, **kw:
                seen.append(hero) if hero is a else None))
        src = game.create_minion("BG25_013", controller=a)
        game.summon(a, src)
        victim = game.create_minion("BG25_013", controller=b)
        game.summon(b, victim)
        game.destroy_minion(victim, source=src)
        self.assertEqual(seen, [a])            # source.controller 兜底


class TestGoldGainedObservation(unittest.TestCase):
    """`gold_gained` 观察点（hero.gold setter 覆盖全部收入路径）。

    "After you gain Gold"（`BG32_MagicItem_350` Splinter of Aurum）此前
    无生产点（只有 `gold_spent`）。
    """

    def test_fires_on_increase_only(self):
        game = make_game(seed=51)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="gold_gained", owner=a,
            callback=lambda g, hero=None, amount=None, **kw:
                seen.append((hero, amount))))
        a.gold += 5
        self.assertEqual(seen, [(a, 5)])
        a.gold -= 3                       # 减少不广播
        self.assertEqual(len(seen), 1)
        a.gold += 2
        self.assertEqual(seen[-1], (a, 2))

    def test_gold_hold_cap_clips_amount(self):
        """99 上限截断后的实际增量才是 amount（溢出不算获得）。"""
        game = make_game(seed=52)
        a, b = game.heroes
        a.gold = 98
        seen = []
        game.events.register(Listener(
            event="gold_gained", owner=a,
            callback=lambda g, amount=None, **kw: seen.append(amount)))
        a.gold += 10
        self.assertEqual(a.gold, 99)
        self.assertEqual(seen, [1])

    def test_sell_and_gain_gold_action_fire(self):
        from hsrl2.actions.economy import GainGold
        game = make_game(seed=53)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="gold_gained", owner=a,
            callback=lambda g, amount=None, **kw: seen.append(amount)))
        GainGold(a, 3).do(game)
        m = game.create_minion("BG25_013", controller=a)
        game.summon(a, m)
        before = len(seen)
        self.assertTrue(game.sell_minion(a, m))       # 售卖收入
        self.assertEqual(seen[0], 3)
        self.assertGreater(len(seen), before)


class TestMinionsSoldThisTurn(unittest.TestCase):
    """`MINIONS_SOLD_THIS_TURN`（hero 级，每回合清零）。"""

    def test_counts_and_resets(self):
        game = make_game(seed=61)
        a, b = game.heroes
        for _ in range(2):
            m = game.create_minion("BG25_013", controller=a)
            game.summon(a, m)
            self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.get(GameTag.MINIONS_SOLD_THIS_TURN, 0), 2)
        game._begin_recruit_for(a)
        self.assertEqual(a.get(GameTag.MINIONS_SOLD_THIS_TURN, 0), 0)

    def test_opponent_isolated(self):
        game = make_game(seed=62)
        a, b = game.heroes
        m = game.create_minion("BG25_013", controller=a)
        game.summon(a, m)
        game.sell_minion(a, m)
        self.assertEqual(b.get(GameTag.MINIONS_SOLD_THIS_TURN, 0), 0)


class TestTavernOfferTierHooks(unittest.TestCase):
    """精确档位展示位 / 额外高一档位（Guiding Candle / Innkeeper's Stein）。

    旧实现只有"通用加位"（`TAVERN_OFFER_MOD`）与抽取上界 =
    `hero.tavern_tier` → 无法表达"只出 Tier N"或"额外的更高档位"。
    """

    def test_exact_tier_all_slots(self):
        game = make_game(seed=71)
        a, b = game.heroes
        a.gold = 30
        a.set(GameTag.TAVERN_TIER, 3)
        a.set(GameTag.TAVERN_OFFER_TIER_EXACT, 6)
        game.refresh_tavern(a)
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(mins)
        for m in mins:
            self.assertEqual(m.tech_level, 6, m.card_id)

    def test_extra_higher_tier_slot(self):
        game = make_game(seed=72)
        a, b = game.heroes
        a.gold = 30
        a.set(GameTag.TAVERN_TIER, 2)
        a.set(GameTag.TAVERN_EXTRA_TIER_SLOTS, 1)
        game.refresh_tavern(a)
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        tiers = [m.tech_level for m in mins]
        # 恰好多出 1 个 T3（= tavern_tier + 1）
        self.assertEqual(tiers.count(3), 1)
        base = len([t for t in tiers if t <= 2])
        self.assertEqual(base, len(tiers) - 1)

    def test_exact_tier_overrides_elven_elite(self):
        game = make_game(seed=73)
        a, b = game.heroes
        a.gold = 30
        a.set(GameTag.TAVERN_TIER, 4)
        a._tavern_offer_tier_only = True
        a.set(GameTag.TAVERN_OFFER_TIER_EXACT, 5)
        game.refresh_tavern(a)
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(mins)
        for m in mins:
            self.assertEqual(m.tech_level, 5, m.card_id)


class TestCombatTransformPersistence(unittest.TestCase):
    """战斗内 Transform 战后重放（RULES §3.5 例外）。

    "Start of Combat: Make your highest-Tier Dragon Golden"（Yu'lon
    Sticker `BG32_MagicItem_419`）是**永久卡身份变更**，不能随战斗棋盘
    复原一起回滚；旧实现 `hero.board = list(board_before[hero])` 会丢掉
    变身实体。
    """

    def test_soc_transform_persists_after_combat(self):
        from hsrl2.actions.stats import Transform
        from hsrl2.scripts.batches.batch_battlecry import _goldenize
        game = make_game(seed=81)
        a, b = game.heroes
        dragon = game.create_minion("BG32_236", controller=a)   # 池随从
        game.summon(a, dragon)
        golden = get_db().golden_version(get_db().get("BG32_236"))
        self.assertIsNotNone(golden)

        def soc(g, hero=None, **kw):
            if hero is a and dragon in a.board and not dragon.dead:
                _goldenize(g, dragon)

        game.events.register(Listener(event="start_of_combat", owner=a,
                                      callback=soc))
        game.run_combat(a, b)
        # 战后棋盘里应是金色实体（旧实现恢复为原非金实体）
        ids = [m.card_id for m in a.board]
        self.assertIn(golden.id, ids)
        self.assertNotIn("BG32_236", ids)
        new = next(m for m in a.board if m.card_id == golden.id)
        self.assertTrue(new.is_golden)
        self.assertEqual(new.get(GameTag.TRIPLE_BASE_CARD_ID), "BG32_236")
        self.assertTrue(new.has(GameTag.GILDED_NOT_TRIPLED))
        self.assertFalse(new.dead)
        self.assertEqual(new.zone, Zone.PLAY)
        # 出售回池按 1 份基础卡（Reno 口径）
        before = game.minion_pool.available("BG32_236")
        for m in list(a.board):
            game.sell_minion(a, m)
        self.assertEqual(game.minion_pool.available("BG32_236"), before + 1)

    def test_recruit_transform_unaffected(self):
        """招募期 Transform 不受影响（非战斗路径）。"""
        from hsrl2.actions.stats import Transform
        game = make_game(seed=82)
        a, b = game.heroes
        m = game.create_minion("BG32_236", controller=a)
        game.summon(a, m)
        golden = get_db().golden_version(get_db().get("BG32_236"))
        game.run_actions(Transform(m, golden.id))
        self.assertIn(golden.id, [x.card_id for x in a.board])
        self.assertEqual(game._combat_transforms, [])


class TestConsumeEventPayload(unittest.TestCase):
    """`minion_consumed` 载荷（区域 + 属性快照）——RULES §6.14 补充。

    "After 2 minions **in the Tavern** are consumed"（Statue of Hir'eek
    `BG32_MagicItem_902`）需要 `from_tavern=`; "also give **the stats** to
    their neighbors"（Flaming Portrait `BG35_MagicItem_156`）需要
    `stats_atk/stats_health=`（吞噬瞬间快照）。
    """

    def test_tavern_consume_payload(self):
        from hsrl2.actions.consume import ConsumeMinion
        game = make_game(seed=91)
        a, b = game.heroes
        demon = game.create_minion("BG25_013", controller=a)
        game.summon(a, demon)
        a.tavern.clear()
        victim = game.create_minion("BG25_001", controller=a)
        victim.zone = Zone.TAVERN
        a.tavern.append(victim)
        seen = []
        game.events.register(Listener(
            event="minion_consumed", owner=a,
            callback=lambda g, **kw: seen.append(kw)))
        ConsumeMinion(demon, victim).do(game)
        self.assertEqual(len(seen), 1)
        kw = seen[0]
        self.assertIs(kw["demon"], demon)
        self.assertIs(kw["consumer"], demon)
        self.assertIs(kw["minion"], victim)
        self.assertTrue(kw["from_tavern"])
        # BG25_001 Risen Rider 2/1 → 快照 (2,1)
        self.assertEqual((kw["stats_atk"], kw["stats_health"]),
                         (2, 1))
        self.assertEqual(demon.atk, 1 + 2)
        self.assertEqual(demon.max_health, 4 + 1)

    def test_board_consume_not_from_tavern(self):
        from hsrl2.actions.consume import ConsumeMinion
        game = make_game(seed=92)
        a, b = game.heroes
        demon = game.create_minion("BG25_013", controller=a)
        game.summon(a, demon)
        victim = game.create_minion("BG25_001", controller=a)
        game.summon(a, victim)
        self.assertEqual(victim.max_health, 1)
        victim.add_buff(Enchant(atk=2, health=3))
        seen = []
        game.events.register(Listener(
            event="minion_consumed", owner=a,
            callback=lambda g, **kw: seen.append(kw)))
        ConsumeMinion(demon, victim).do(game)
        kw = seen[0]
        self.assertFalse(kw["from_tavern"])
        # 快照 = 吞噬瞬间的 (atk, max_health)（base + buff）——BG25_001
        # 2/1 + Buff(2,3) = 4/4
        self.assertEqual((kw["stats_atk"], kw["stats_health"]), (4, 4))


class TestSmallReadPoints(unittest.TestCase):
    """三个小读取点: 盘外 CHOOSE_BOTH / 下一饰品档位 / 己方 Rally 全触发。"""

    def test_choose_both_hero_level(self):
        """"Your Choose One cards have both effects combined"（308）——
        hero 级 CHOOSE_BOTH 让 Choose One 随从跳过选择取双效。"""
        game = make_game(seed=101)
        a, b = game.heroes
        a.set(GameTag.CHOOSE_BOTH, True)
        chooser = None
        for cid, cls in REGISTRY.items():
            if getattr(cls, "choose_options", None):
                d = get_db().get(cid)
                if d is not None and d.card_type == CardType.MINION:
                    chooser = cid
                    break
        self.assertIsNotNone(chooser, "数据中应有 Choose One 随从")
        m = game.create_minion(chooser, controller=a)
        a.hand.append(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.pending_choices, [])   # 不产生选择
        # 负对照: 无 hero 级 tag → 产生选择
        game2 = make_game(seed=101)
        a2 = game2.heroes[0]
        m2 = game2.create_minion(chooser, controller=a2)
        a2.hand.append(m2)
        game2.play_minion(a2, m2)
        self.assertTrue(game2.pending_choices)

    def test_next_trinket_kind_override(self):
        """"Your next Trinket is a Lesser Trinket"（818）hero 级覆写读取点。"""
        game = make_game(seed=102)
        a, b = game.heroes
        a._next_trinket_kind = "lesser"
        game._offer_trinkets(a, "greater")           # 被覆写为 lesser
        self.assertIsNone(a._next_trinket_kind)      # 消费即清
        choice = game.pending_choices[-1]
        checked = 0
        for opt in choice.options:
            if isinstance(opt, str):
                d = get_db().get(opt)
            elif getattr(opt, "spell_school", None) is not None:
                d = opt                              # 直接给 CardDef
            else:
                d = get_db().get(getattr(opt, "card_id", None))
            if d is None or not d.spell_school:
                continue                             # "放弃" / 无类型
            self.assertEqual(d.spell_school, 11, d.id)
            checked += 1
        self.assertGreater(checked, 0)

    def test_trigger_friendly_rallies(self):
        """"At the end of your turn, trigger all friendly Rallies"（214）。"""
        game = make_game(seed=103)
        a, b = game.heroes
        calls = []

        class RallyProbe:
            @staticmethod
            def rally(source, g, ctx=None):
                calls.append(source)

        m = Minion("TEST_RALLY", "R", atk=1, health=1)
        m.game = game
        m.controller = a
        m.scripts = RallyProbe
        game.summon(a, m)
        plain = game.create_minion("BG25_013", controller=a)  # 无 rally
        game.summon(a, plain)
        self.assertEqual(len(a.board), 2)
        self.assertEqual(game.trigger_friendly_rallies(a), 1)
        self.assertEqual(calls, [m])
        # rally_extra 配额同样生效
        a.extra_triggers["rally_extra"] = 1
        calls.clear()
        game.trigger_friendly_rallies(a)
        self.assertEqual(len(calls), 2)


class TestCardAuraAndCombatHooks(unittest.TestCase):
    """卡家族光环 / 最后随从死亡 / 复制战团刷新（2026-09-02 原语）。"""

    def test_card_family_aura_wherever_and_incremental(self):
        """`add_card_aura`: "your <家族> have +X/+Y this game"——
        任意区域生效、增量式、source 离场失效。"""
        game = make_game(seed=111)
        a, b = game.heroes
        src = game.create_entity("BG30_MagicItem_437", controller=a)
        a.trinkets.append(src)
        on_board = game.create_minion("BG25_008", controller=a)   # Eternal Knight
        game.summon(a, on_board)
        in_hand = game.create_minion("BG25_008", controller=a)
        a.hand.append(in_hand)
        base_b, base_h = on_board.atk, on_board.max_health
        game.add_card_aura(src, {"BG25_008"}, atk=3, health=3)
        self.assertEqual((on_board.atk, on_board.max_health),
                         (base_b + 3, base_h + 3))
        ek = get_db().get("BG25_008")
        self.assertEqual((in_hand.atk, in_hand.max_health),
                         (ek.atk + 3, ek.health + 3))   # 手牌同样生效
        # 增量式: 再 +1/+1
        game.add_card_aura(src, {"BG25_008"}, atk=4, health=4)
        self.assertEqual((on_board.atk, on_board.max_health),
                         (base_b + 4, base_h + 4))
        # 非家族卡不受影响（负对照）+ 金色按基础 id 匹配
        other = game.create_minion("BG25_013", controller=a)
        game.summon(a, other)
        self.assertEqual(other.atk, 1)
        gold = game.create_minion("BG25_008", controller=a, golden=True)
        game.summon(a, gold)
        self.assertEqual(gold.max_health,
                         get_db().get("BG25_008_G").health + 4)
        # source 离场 → 失效
        a.trinkets.remove(src)
        self.assertEqual(on_board.atk, base_b)

    def test_last_minion_died_once_per_combat(self):
        game = make_game(seed=112)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="last_minion_died", owner=a,
            callback=lambda g, hero=None, **kw: seen.append(hero) if hero is a else None))
        m = game.create_minion("BG25_013", controller=a)
        game.summon(a, m)
        game.in_combat = True
        m.set(GameTag.HEALTH, 0)
        game.check_deaths()
        self.assertEqual(seen, [a])
        # 本场战斗再次清空 → 不再触发（"each combat"一次）
        m2 = game.create_minion("BG25_013", controller=a)
        game.summon(a, m2)
        m2.set(GameTag.HEALTH, 0)
        game.check_deaths()
        self.assertEqual(seen, [a])
        # 下一场战斗重置
        game._last_minion_fired = set()
        m3 = game.create_minion("BG25_013", controller=a)
        game.summon(a, m3)
        m3.set(GameTag.HEALTH, 0)
        game.check_deaths()
        self.assertEqual(seen, [a, a])
        game.in_combat = False

    def test_combat_death_snapshots_recorded(self):
        game = make_game(seed=114)
        a, b = game.heroes
        m = game.create_minion("BG32_340", controller=a)   # Maw Caster（亡灵 T4）
        game.summon(a, m)
        m.add_buff(Enchant(atk=2, health=3))
        game.in_combat = True
        m.set(GameTag.HEALTH, 0)
        game.check_deaths()
        snaps = a._combat_dead_snaps
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["card_id"], "BG32_340")
        self.assertEqual((snaps[0]["atk"], snaps[0]["max_health"]), (6, 8))
        game.in_combat = False

    def test_golden_falls_back_to_base_script(self):
        """金色无独立脚本时回落基础卡脚本（ENGINE_BACKLOG §B15）。"""
        game = make_game(seed=122)
        a, b = game.heroes
        # 金色 token（本体 BGS_012 已注册、金色变体无独立脚本）
        m = game.create_minion("TB_BaconUps_087", controller=a)
        self.assertIsNotNone(m.scripts,
                             "金色 token 未回落到基础卡脚本")
        self.assertIs(m.scripts, REGISTRY["BGS_012"])
        # 基础卡脚本自身仍正常（负对照: 非金色 id）
        base = game.create_minion("BGS_012", controller=a)
        self.assertIs(base.scripts, REGISTRY["BGS_012"])
        # 有独立脚本的金色 token **不**回落（2026-09-13: 金色 Fish of
        # N'Zoth "twice" 文本由 GoldenFishOfNZothScript 覆写次数）
        fish = game.create_minion("TB_BaconUps_307", controller=a)
        self.assertIs(REGISTRY["TB_BaconUps_307"].__name__,
                      "GoldenFishOfNZothScript")
        self.assertIs(fish.scripts, REGISTRY["TB_BaconUps_307"])
        self.assertIs(fish.scripts.__mro__[1], REGISTRY["TB_BaconShop_HP_105t"])

    def test_hp_times_doubles_hero_power_effect(self):
        """"Your Hero Power **triggers twice**"（804 Ancient Wishbone）——
        一次使用结算两次（`hp_uses` 是"多使用几次"，两者独立）。"""
        from hsrl2.scripts.registry import register as _register
        from hsrl2.scripts import REGISTRY as _REG
        calls = []

        class ProbePower:
            @staticmethod
            def hero_power(hero, game, ctx=None):
                calls.append(hero)

        pid = "BG20_HERO_100p"        # 真实英雄技能卡（CardDef 齐备）
        orig = _REG.get(pid)
        _REG[pid] = ProbePower
        try:
            game = make_game(seed=120)
            a, b = game.heroes
            a._second_power_id = None
            game.hero_power_ids = lambda hero: [pid]      # type: ignore
            a.gold = 30
            self.assertTrue(game.use_hero_power(a))
            self.assertEqual(len(calls), 1)                # 基准 1 次
            calls.clear()
            a.extra_triggers["hp_times"] = 1               # "triggers twice"
            a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
            self.assertTrue(game.use_hero_power(a))
            self.assertEqual(len(calls), 2)
        finally:
            if orig is not None:
                _REG[pid] = orig
            else:
                _REG.pop(pid, None)

    def test_combat_slot_freed_event(self):
        """"When you have space, ..."（440/822）观察点。"""
        game = make_game(seed=121)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="combat_slot_freed", owner=a,
            callback=lambda g, hero=None, **kw:
                seen.append(hero) if hero is a else None))
        m = game.create_minion("BG25_013", controller=a)
        game.summon(a, m)
        game.in_combat = True
        m.set(GameTag.HEALTH, 0)
        game.check_deaths()
        self.assertEqual(seen, [a])
        game.in_combat = False
        # 招募期死亡不广播（负对照）
        m2 = game.create_minion("BG25_013", controller=a)
        game.summon(a, m2)
        m2.set(GameTag.HEALTH, 0)
        game.check_deaths()
        self.assertEqual(seen, [a])

    def test_minion_triggered_observation(self):
        """"Whenever your <X> **trigger**" 观察点（156 Flaming Portrait 用）。"""
        game = make_game(seed=119)
        a, b = game.heroes
        seen = []

        class Probe:
            @staticmethod
            def end_of_turn(source, g, ctx=None):
                pass

        m = Minion("TEST_TRIG", "T", atk=1, health=1)
        m.game = game
        m.controller = a
        m.scripts = Probe
        game.summon(a, m)
        game.events.register(Listener(
            event="minion_triggered",
            owner=a,
            callback=lambda g, minion=None, hook=None, **kw:
                seen.append((minion, hook))))
        game.run_script_hook(m, "end_of_turn")
        self.assertEqual(seen, [(m, "end_of_turn")])
        # 无脚本实体（白板）也广播（"trigger" 语义 = 钩子分发尝试）
        plain = game.create_minion("BG25_013", controller=a)
        game.summon(a, plain)
        game.run_script_hook(plain, "end_of_turn")
        self.assertEqual(seen[-1], (plain, "end_of_turn"))

    def test_per_race_triple_threshold(self):
        """"You only need 2 copies of a **Pirate** to make it Golden"
        （Designer Eyepatch BG30_MagicItem_439）——按种族的三连阈值。"""
        game = make_game(seed=118)
        a, b = game.heroes
        pid = next(d.id for d in sorted(get_db().pool_minions(),
                                        key=lambda d: d.id)
                   if d.race == Race.PIRATE
                   and get_db().golden_version(d) is not None)

        def two_copies(hero):
            for _ in range(2):
                m = game.create_minion(pid, controller=hero)
                hero.hand.append(m)
                m.zone = Zone.HAND
            return hero.hand[-1]

        last = two_copies(a)
        a.triple_threshold_race = {Race.PIRATE: 2}
        game.check_for_triple(a, last)
        self.assertEqual(len([x for x in a.hand if x.is_golden]), 1)
        # 负对照: 无该阈值 → 2 张不合成
        last_b = two_copies(b)
        game.check_for_triple(b, last_b)
        self.assertEqual([x for x in b.hand if x.is_golden], [])

    def test_bonus_keyword_domain_and_persist_only(self):
        """Bonus Keyword = 官方 6 集（RULES §9.6）; 417 的持久化只保留这 6 张。"""
        from hsrl2.game import _PERSIST_KEYWORD_TAGS
        game = make_game(seed=117)
        a, b = game.heroes
        m = game.create_minion("BG25_013", controller=a)
        game.summon(a, m)
        game.grant_bonus_keyword(m, GameTag.TAUNT)
        self.assertTrue(m.has(GameTag.TAUNT))
        self.assertIn(GameTag.TAUNT, m.get(GameTag.BONUS_KEYWORDS))
        with self.assertRaises(GameStateError):
            game.grant_bonus_keyword(m, GameTag.POISONOUS)   # 非六集 → fail-loud
        self.assertIn(game.random_bonus_keyword(), BONUS_KEYWORD_TAGS)
        self.assertEqual(set(game._persist_keyword_tags(m)),
                         set(_PERSIST_KEYWORD_TAGS))          # 默认 8 集
        m.set(GameTag.PERSIST_BONUS_ONLY, True)
        self.assertEqual(set(game._persist_keyword_tags(m)),
                         set(BONUS_KEYWORD_TAGS))             # 417 → 6 集
        self.assertNotIn(GameTag.POISONOUS,
                         game._persist_keyword_tags(m))

    def test_keyword_refresh_and_extra_keyword_slots(self):
        """"Refresh the Tavern with **Battlecry** minions"（755）与
        "offers an extra **Magnetic** Mech"（743 第二条款）。"""
        from hsrl2.tags import CardType as _CT
        game = make_game(seed=115)
        a, b = game.heroes
        a.gold = 30
        a.set(GameTag.TAVERN_TIER, 5)
        game.refresh_tavern(a, keywords={"battlecry"})
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(mins)
        for m in mins:
            self.assertIn("battlecry",
                          get_db().get(m.card_id).keywords, m.card_id)
        # 额外关键词位（磁力机械）
        src = game.create_entity("BG35_MagicItem_743", controller=a)
        a.trinkets.append(src)
        a._tavern_extra_keyword.append((src, {"magnetic"}, 1))
        game.refresh_tavern(a, keywords={"battlecry"})
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        magnet = [m for m in mins
                  if "magnetic" in get_db().get(m.card_id).keywords]
        self.assertEqual(len(magnet), 1, [m.card_id for m in mins])

    def test_tavern_cost_rules(self):
        """"Magnetic Mechs cost (2)"——条件化购买价（743 第一条款）。"""
        game = make_game(seed=116)
        a, b = game.heroes
        a.gold = 30
        src = game.create_entity("BG35_MagicItem_743", controller=a)
        a.trinkets.append(src)
        a._tavern_cost_rules.append(
            (src, lambda e: "magnetic" in get_db().get(e.card_id).keywords, 2))
        # 磁力机械 → 2 金; 非磁力 → 3 金
        mech = next(d for d in sorted(get_db().pool_minions(),
                                      key=lambda d: d.id)
                    if "magnetic" in d.keywords and d.tech_level <= 3)
        a.tavern.clear()
        m = game.create_minion(mech.id, controller=a)
        game.add_tavern_entity(a, m)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, m))
        self.assertEqual(gold_before - a.gold, 2)
        plain = next(d for d in sorted(get_db().pool_minions(),
                                       key=lambda d: d.id)
                     if not d.keywords and d.tech_level <= 3)
        m2 = game.create_minion(plain.id, controller=a)
        game.add_tavern_entity(a, m2)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, m2))
        self.assertEqual(gold_before - a.gold, 3)

    def test_copies_of_warband_refresh(self):
        """"a free Refresh that contains plain copies of minions in your
        warband"（Warband Whistle BG35_MagicItem_930）。"""
        game = make_game(seed=113)
        a, b = game.heroes
        a.gold = 30
        m = game.create_minion("BG25_001", controller=a)
        game.summon(a, m)
        m.add_buff(Enchant(atk=5, health=5))
        before = game.minion_pool.available("BG25_001")
        game.refresh_tavern(a, free=True, copies_of_warband=True)
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual([x.card_id for x in mins], ["BG25_001"])
        self.assertEqual((mins[0].atk, mins[0].max_health), (2, 1))  # 白板
        self.assertEqual(game.minion_pool.available("BG25_001"), before)


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
        # 37.0: 官方文本 "give this +{2} Health"（num(2)=2; 36.2.2 字面量 +1）
        self.assertEqual(rewinder.max_health,
                         base_hp + get_db().get("BG26_174").num(2))

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


class TestDiscoverGoldenPoolAccounting(unittest.TestCase):
    """Discover(golden=True) 的池记账（2026-09-02 对抗审查 N1）。

    选项生成时每个选项 acquire 1 份基础副本；授予的金色本体只占 1 份，
    因此必须带 GILDED_NOT_TRIPLED（出售/淘汰回池 1 份）——否则
    "扣 1 返 3" 每次净泄漏 2 份基础副本（Treasure Hoard 异变实测
    12 → 卖后 15）。
    """

    def test_golden_discover_keeps_pool_balanced(self):
        from hsrl2.actions.discover import Discover
        game = make_game(seed=91, n=2)
        a = game.heroes[0]
        game.start_game()
        find_plain(get_db(), tier=1)     # 池非空前提（选项集合由 Discover 内定）
        # 37.0 池内容变化会改变 Discover 选项 → 以**整池快照**为基准，
        # 不假设选项 == 某个预取卡（旧实现的隐式耦合）。
        before_all = dict(game.minion_pool._available)
        game.run_actions(Discover(a, min_tier=1, max_tier=1, count=1,
                                  golden=True))
        choice = game.pending_choices.pop(0)
        pick = choice.options[0]
        before = before_all.get(pick, 0)
        acquired_once = game.minion_pool.available(pick)
        self.assertEqual(acquired_once, before - 1)      # 预留 1 份
        choice.choose(0)
        self.assertEqual(game.minion_pool.available(pick), acquired_once)
        got = [x for x in a.hand if isinstance(x, Minion)]
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].is_golden)
        self.assertTrue(got[0].get(GameTag.GILDED_NOT_TRIPLED, False))
        self.assertTrue(game.sell_minion(a, got[0]))
        # 回池恰好 1 份（= 预留的那份），池回到 Reserve 前水平
        self.assertEqual(game.minion_pool.available(pick), before)


class TestOpponentReferences(unittest.TestCase):
    """RULES §4.8a — 配对在招募期开始即确定; 下一对手/上一对手是两个
    不同引用（Scabbs / Tess / Holmes 三张卡的数据文本要求）。"""

    N = 4

    def _game(self, seed=80):
        game = make_game(seed=seed, n=self.N)
        for h in game.heroes:
            game.summon(h, Minion("TEST_" + h.card_id, h.card_id,
                                  atk=2, health=2))
        return game

    def test_pairing_known_during_recruit(self):
        game = self._game()
        game.start_game()
        self.assertEqual(game.turn, 1)
        nxt = [game.next_opponent(h) for h in game.heroes]
        self.assertTrue(all(o is not None for o in nxt))
        # 配对是对称的且无自配
        for h, o in zip(game.heroes, nxt):
            self.assertIsNot(h, o)
            self.assertIs(game.next_opponent(o), h)
        # 战团 = 对手当前棋盘
        for h, o in zip(game.heroes, nxt):
            self.assertEqual({id(m) for m in game.next_opponent_warband(h)},
                             {id(m) for m in o.board})

    def test_declared_next_opponent_is_the_one_actually_fought(self):
        game = self._game(seed=81)
        game.start_game()
        declared = {h: game.next_opponent(h) for h in game.heroes}
        game.end_recruit_phase()
        for h, opp in declared.items():
            self.assertIs(game.last_opponent(h), opp)   # 打的就是预告的对手
            self.assertIs(game.combat_memory[h][-1], opp)

    def test_next_and_last_opponent_differ_across_turns(self):
        game = self._game(seed=82)
        game.start_game()
        turn1 = {h: game.next_opponent(h) for h in game.heroes}
        game.end_recruit_phase()                 # 战斗 + turn → 2
        # 第 2 招募期: last = 上回合对手; next = 本回合新配对
        for h in game.heroes:
            self.assertIs(game.last_opponent(h), turn1[h])
        turn2 = {h: game.next_opponent(h) for h in game.heroes}
        # 对手回避: 连续两回合不会重复同一对手（4 人局 RULES §4.8）
        for h in game.heroes:
            self.assertIsNot(turn2[h], turn1[h])
            self.assertIsNot(game.next_opponent_warband(h), None)
        game.end_recruit_phase()
        for h in game.heroes:
            self.assertIs(game.last_opponent(h), turn2[h])

    def test_last_opponent_warband_is_frozen_precombat_snapshot(self):
        game = self._game(seed=83)
        game.start_game()
        declared = {h: game.next_opponent(h) for h in game.heroes}
        game.end_recruit_phase()
        a = game.heroes[0]
        opp = declared[a]
        snap = game.last_opponent_warband(a)
        self.assertIsNotNone(snap)
        # 快照 = 对手战前战团（shallow copy: 实体同一批）
        self.assertEqual([id(m) for m in snap],
                         [id(m) for m in opp.last_combat_board])
        # 对手后续买人（棋盘变化）不影响已记录快照
        game.summon(opp, Minion("TEST_LATE", "LATE", atk=9, health=9))
        self.assertEqual([id(m) for m in game.last_opponent_warband(a)],
                         [id(m) for m in snap])

    def test_ghost_combat_has_last_warband_but_no_hero_reference(self):
        game = make_game(seed=84, n=3)
        for h in game.heroes:
            game.summon(h, Minion("TEST_" + h.card_id, h.card_id,
                                  atk=2, health=2))
        # 制造一个幽灵记录（敌手淘汰）后进入奇数人幽灵战
        game.ghost_records.append({
            "board": [Minion("TEST_GHOST", "Ghost", atk=2, health=2)],
            "tavern_tier": 3, "name": "Ghost"})
        hero = game.heroes[0]
        game.fought_ghost_last = False
        game.run_ghost_combat(hero)
        self.assertIsNone(game.last_opponent(hero))          # 幽灵无 Hero
        snap = game.last_opponent_warband(hero)
        self.assertIsNotNone(snap)                            # 但战团在
        self.assertEqual(len(snap), 1)
        self.assertIsNone(game.next_opponent(hero))           # 未配对


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


class TestQuestTrinketAnomalySystems(unittest.TestCase):
    """任务/饰品/异变三系统引擎。"""

    def _game(self, seed=90):
        game = make_game(seed)
        game.start_game()
        return game

    def test_quest_offer_turn4(self):
        game = make_game(seed=90)
        a = game.heroes[0]
        game.start_game()
        # 推进到 turn 4
        while game.turn < 4 and not game.finished:
            game.end_recruit_phase()
        offers = [c for c in game.pending_choices
                  if c.kind == "quest_offer" and c.owner is a]
        self.assertEqual(len(offers), 1)
        pair = offers[0].options[0]
        # 2026-09-18: 候选池 = 全部已注册任务（含 BG27_/BG28_ 同族）——
        # 旧断言写死 `BG24_Quest_` 前缀已过期，见 `Game.quest_offer_pool`。
        self.assertIn(pair[0], {d.id for d in game.quest_offer_pool()})
        self.assertTrue(pair[1].startswith("BG24_Reward_"))
        # 选择后 quest 绑定 + on_bind 触发
        offers[0].choose(0)
        self.assertIsNotNone(a.quest)
        self.assertEqual(a.quest.card_id, pair[0])

    def test_complete_quest_grants_reward(self):
        game = make_game(seed=91)
        a = game.heroes[0]
        game.start_game()
        while game.turn < 4 and not game.finished:
            game.end_recruit_phase()
        offers = [c for c in game.pending_choices
                  if c.kind == "quest_offer" and c.owner is a]
        pair = offers[0].options[0]
        offers[0].choose(0)
        rid = a._quest_reward_id
        self.assertTrue(rid.startswith("BG24_Reward_"))
        game.complete_quest(a)
        self.assertEqual(len(a.quest_rewards), 1)
        self.assertEqual(a.quest_rewards[0].card_id, rid)
        self.assertIsNone(a._quest_reward_id)

    def test_trinket_offer_turn6(self):
        import hsrl2.constants as C
        game = make_game(seed=92)
        a = game.heroes[0]
        game.start_game()
        while game.turn < 6 and not game.finished:
            game.end_recruit_phase()
        offers = [c for c in game.pending_choices
                  if c.kind == "trinket_offer" and c.owner is a]
        self.assertEqual(len(offers), 1)
        opts = offers[0].options
        # TRINKET_CHOICES 选 + 放弃（官方 Developer Insights "Updated
        # Trinket Rules": 每次提供 **4** 张）
        self.assertEqual(len(opts), C.TRINKET_CHOICES + 1)
        self.assertIsNone(opts[-1])
        for o in opts[:-1]:
            self.assertEqual(o.card_type, 44)
        # 保证: ≥1 无类型 + ≥1 费≤2（若池满足）
        subsets = [game._trinket_subsets(o) for o in opts[:-1]]
        self.assertTrue(any(not s for s in subsets))
        self.assertTrue(any((o.cost or 0) <= 2 for o in opts[:-1]))
        gold_before = a.gold
        cost = opts[0].cost or 0
        offers[0].choose(0)
        self.assertEqual(a.gold, gold_before - cost)
        self.assertEqual(len(a.trinkets), 1)
        self.assertEqual(a.trinkets[0].card_id, opts[0].id)
        # 不重复: 再次 offer 不含已获得
        game._offer_trinkets(a, "lesser")
        offers2 = [c for c in game.pending_choices
                   if c.kind == "trinket_offer"][-1]
        self.assertNotIn(opts[0].id,
                         [o.id for o in offers2.options if o is not None])

    def test_trinket_decline(self):
        game = make_game(seed=93)
        a = game.heroes[0]
        game.start_game()
        while game.turn < 6 and not game.finished:
            game.end_recruit_phase()
        offers = [c for c in game.pending_choices
                  if c.kind == "trinket_offer" and c.owner is a]
        offers[0].choose(offers[0].options.index(None))   # 放弃
        self.assertEqual(len(a.trinkets), 0)

    def test_greater_trinket_offered_turn9(self):
        """回归: T6 lesser offer 后 T9 greater 仍须发放。

        旧实现 `hero not in _trinket_offered` 按英雄记账——T6 之后
        Greater 永不提供。
        """
        game = make_game(seed=101)
        a = game.heroes[0]
        game.start_game()
        while game.turn < 9 and not game.finished:
            game.end_recruit_phase()
        kinds = [c for c in game.pending_choices
                 if c.kind == "trinket_offer" and c.owner is a]
        self.assertEqual(len(kinds), 2)
        self.assertIn((a, "lesser"), game._trinket_offered)
        self.assertIn((a, "greater"), game._trinket_offered)

    def test_early_greater_trinket(self):
        """T271 Ornate Clock: `_trinket_early["greater"]` 次回合触发。"""
        game = make_game(seed=102)
        a = game.heroes[0]
        game.start_game()
        while game.turn < 6 and not game.finished:
            game.end_recruit_phase()
        a._trinket_early = {"greater": game.turn + 1}
        n_before = len(game.pending_choices)
        game.end_recruit_phase()      # turn 6 → 7
        new_offers = [c for c in game.pending_choices[n_before:]
                      if c.kind == "trinket_offer" and c.owner is a]
        self.assertEqual(len(new_offers), 1)
        self.assertIn((a, "greater"), game._trinket_offered)

    def test_anomaly_apply(self):
        from hsrl2.scripts import REGISTRY

        class TestAnomaly:
            @staticmethod
            def on_bind(game):
                for h in game.heroes:
                    h.income_bonus = getattr(h, "income_bonus", 0) + 3

        REGISTRY["TEST_ANOMALY_X"] = TestAnomaly
        try:
            game = Game([Hero("TB_BaconShop_HERO_52", "A"),
                         Hero("TB_BaconShop_HERO_34", "B")],
                        get_db(), seed=94,
                        anomaly="TEST_ANOMALY_X")
            game.start_game()
            for h in game.heroes:
                self.assertEqual(getattr(h, "income_bonus", 0), 3)
            self.assertEqual(game.anomaly, "TEST_ANOMALY_X")
        finally:
            del REGISTRY["TEST_ANOMALY_X"]


class TestPoolInjectionAndPerGameMaxTier(unittest.TestCase):
    """2026-09-01 引擎新增: 池外卡注入 / 每局 T7 / 刷新种族过滤。"""

    def _game(self, seed=95):
        game = make_game(seed)
        game.start_game()
        return game

    def test_inject_non_pool_minion_drawable_and_releasable(self):
        """ensure_available 支持池外随从，注入后可抽且回池有效。"""
        from hsrl2.tags import CardType, Race
        game = self._game()
        pool = game.minion_pool
        d = get_db().get("BGS_072")            # Cap'n Hoggarr（非池定义）
        self.assertIsNotNone(d)
        self.assertEqual(d.name, "Cap'n Hoggarr")
        self.assertFalse(d.is_pool_minion)
        self.assertEqual(pool.available("BGS_072"), 0)
        self.assertTrue(pool.ensure_available("BGS_072"))
        self.assertGreater(pool.available("BGS_072"), 0)
        self.assertIn("BGS_072",
                      pool.candidates(7, 1, races={Race.PIRATE, Race.ALL}))
        self.assertTrue(pool.acquire("BGS_072"))
        pool.release("BGS_072", 1)             # 注入态可回池
        self.assertGreater(pool.available("BGS_072"), 0)
        # token（tech_level<=0）不可注入
        token = next(x for x in get_db()._by_id.values()
                     if x.card_type == CardType.MINION and x.tech_level <= 0)
        self.assertFalse(pool.ensure_available(token.id))

    def test_per_game_max_tier_isolated(self):
        """max_tavern_tier 是**每局**状态——不得污染其他 Game 实例。

        回归: 旧判据 `next_tier > MAX + 1` 允许标准局升到 T7
        （TAVERN_MAX_TIER=6 文档为"常规上限，T7 仅特殊效果可达"）。
        """
        import hsrl2.constants as C
        g7 = self._game(seed=96)
        g7.max_tavern_tier = 7
        a = g7.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        a.set(GameTag.UPGRADE_COST, 1)
        a.gold = 50
        self.assertTrue(g7.upgrade_tavern(a))
        self.assertEqual(a.tavern_tier, 7)
        self.assertEqual(C.TAVERN_MAX_TIER, 6)
        g6 = self._game(seed=97)
        b = g6.heroes[0]
        b.set(GameTag.TAVERN_TIER, 6)
        b.set(GameTag.UPGRADE_COST, 1)
        b.gold = 50
        self.assertFalse(g6.upgrade_tavern(b))   # 标准局 T7 不存在
        self.assertEqual(b.tavern_tier, 6)

    def test_refresh_races_filter(self):
        """refresh_tavern(races=) 只抽白名单种族（+ALL）。"""
        from hsrl2.tags import Race
        game = self._game(seed=98)
        a = game.heroes[0]
        a.gold = 50
        game.refresh_tavern(a, auto=True, races={Race.BEAST, Race.ALL})
        minions = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(minions)
        self.assertTrue(all(m.race in (Race.BEAST, Race.ALL) for m in minions))

    def test_notype_is_all_global(self):
        """_notype_is_all 在 create_minion 生效（非仅酒馆抽取）。"""
        from hsrl2.tags import CardType, Race
        game = self._game(seed=99)
        game._notype_is_all = True
        d = next(x for x in get_db()._by_id.values()
                 if x.card_type == CardType.MINION and x.race == Race.NONE
                 and x.tech_level > 0)
        m = game.create_minion(d.id, controller=game.heroes[0])
        self.assertEqual(m.race, Race.ALL)

    def test_hero_max_health(self):
        """Hero.max_health = 基础生命（"regain X Health" 封顶依据）。

        回归: Hero 此前只设 HEALTH2，BASE_HEALTH 未设 → max_health 恒 0。
        """
        import hsrl2.constants as C
        game = self._game(seed=100)
        for h in game.heroes:
            self.assertEqual(h.max_health, C.HERO_BASE_HEALTH)

    def test_tag_values_not_aliased(self):
        """GameTag 值不得意外别名（XML enumID 唯一）。

        回归: `IMMUNE = 49` 与 `ZONE = 49` 同值 → IntEnum 别名化，
        `m.has(GameTag.IMMUNE)` 恒真（探针与脚本都会被误导）。
        XML 权威: IMMUNE = 240。
        """
        from hsrl2.tags import GameTag
        self.assertEqual(int(GameTag.IMMUNE), 240)
        self.assertNotEqual(int(GameTag.IMMUNE), int(GameTag.ZONE))
        self.assertIsNot(GameTag.IMMUNE, GameTag.ZONE)
        # 关键标签两两不同值（防未来新增时再次撞号）
        key = [GameTag.ZONE, GameTag.IMMUNE, GameTag.DIVINE_SHIELD,
               GameTag.TAUNT, GameTag.STEALTH, GameTag.ATK, GameTag.HEALTH]
        self.assertEqual(len({int(t) for t in key}), len(key))

    def test_trinket_offer_tier_pool(self):
        """饰品商店按档位过滤: Lesser=spell_school 11 / Greater=12。

        回归（2026-09-01 对抗审计）: `_offer_trinkets` 忽略 kind →
        T6 混入 Greater、T9 混入 Lesser；且升级变体（t 后缀且有同名本体）
        不该出现在商店。
        """
        game = self._game(seed=130)
        a = game.heroes[0]
        game._offer_trinkets(a, "lesser")
        lesser = [c for c in game.pending_choices
                  if c.kind == "trinket_offer"][-1]
        self.assertTrue(lesser.options[:-1])
        for d in lesser.options[:-1]:
            self.assertEqual(d.spell_school, 11)
        game._offer_trinkets(a, "greater")
        greater = [c for c in game.pending_choices
                   if c.kind == "trinket_offer"][-1]
        self.assertTrue(greater.options[:-1])
        for d in greater.options[:-1]:
            self.assertEqual(d.spell_school, 12)
        # 升级变体（同名本体存在）不进商店池
        pool_ids = {d.id for d in get_db().trinket_offer_pool()}
        self.assertIn("BG30_MagicItem_414", pool_ids)
        self.assertNotIn("BG30_MagicItem_414t", pool_ids)

    def test_minion_level_freeze_survives_refresh(self):
        """实体级 FROZEN: 单卡冻结跨刷新保留（其余回池），冻结只保留一轮。

        支撑 "Freeze a minion" 类效果（整馆冻结是 hero 级 FROZEN）。
        """
        game = self._game(seed=150)
        a = game.heroes[0]
        a.gold = 50
        game.refresh_tavern(a, auto=True)
        minions = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertGreaterEqual(len(minions), 2)
        frozen = minions[0]
        frozen.set(GameTag.FROZEN, True)
        others = [m for m in minions[1:]]
        game.refresh_tavern(a, auto=True)
        self.assertIn(frozen, a.tavern)
        self.assertFalse(frozen.has(GameTag.FROZEN))   # 只保留一轮
        self.assertTrue(all(m not in a.tavern for m in others))

    def test_race_all_aura_covers_typeless(self):
        """Race.ALL 光环命中所有随从（含无类型）——Feral Talisman 语义。

        回归: `_aura_atk/_aura_health` 曾对 race==NONE 提前返回 0，
        "Your minions have +X/+Y" 漏掉无类型随从。
        """
        from hsrl2.actions.racefx import ApplyRaceAura
        game = self._game(seed=160)
        a = game.heroes[0]
        typo = game.create_minion("BG27_002", controller=a)     # 无类型 2/2
        game.summon(a, typo)
        murloc = game.create_minion("BG22_202", controller=a)   # Murloc 2/2
        game.summon(a, murloc)
        game.run_actions(ApplyRaceAura(a, Race.ALL, 2, 1))
        self.assertEqual((typo.atk, typo.max_health), (4, 3))
        self.assertEqual((murloc.atk, murloc.max_health), (4, 3))
        # 种族限定光环仍不命中无类型
        game2 = self._game(seed=161)
        a2 = game2.heroes[0]
        typo2 = game2.create_minion("BG27_002", controller=a2)
        game2.summon(a2, typo2)
        game2.run_actions(ApplyRaceAura(a2, Race.BEAST, 5, 5))
        self.assertEqual((typo2.atk, typo2.max_health), (2, 2))

    def test_hero_tavern_offer_override_owner_scoped(self):
        """hero 级展示数覆写只影响本人酒馆（对手不受污染）。"""
        game = self._game(seed=162)
        a, b = game.heroes
        a._tavern_offer_override = 7
        a.gold = 50
        b.gold = 50
        game.refresh_tavern(a, auto=True)
        game.refresh_tavern(b, auto=True)
        a_minions = [m for m in a.tavern if isinstance(m, Minion)]
        b_minions = [m for m in b.tavern if isinstance(m, Minion)]
        self.assertEqual(len(a_minions), 7)
        self.assertNotEqual(len(b_minions), 7)

    def test_bacon_spell_card_type(self):
        """酒馆法术 card_type=42（此前解析为 INVALID）。"""
        from hsrl2.tags import CardType
        self.assertEqual(int(CardType.BACON_SPELL), 42)
        spells = get_db().pool_spells()
        self.assertTrue(spells)
        self.assertTrue(all(d.card_type == CardType.BACON_SPELL
                            for d in spells))

    def test_avenge_counter_resets_at_combat_start(self):
        """Avenge 计数每场清零（RULES §6.11）——随从 + 饰品/奖励实体。

        回归: 计数器从不重置 → 跨战斗累积（第二次战斗提前触发）。
        """
        from hsrl2.combat import CombatScheduler
        game = self._game(seed=120)
        a, b = game.heroes
        m = game.create_minion("BG25_001", controller=a)
        game.summon(a, m)
        m.set(GameTag.AVENGE, True)
        m.set(GameTag.AVENGE_TARGET, 3)
        m.set(GameTag.AVENGE_COUNTER, 2)
        e = game.create_entity("BG30_MagicItem_437", controller=a)
        a.trinkets.append(e)
        e.set(GameTag.AVENGE_COUNTER, 4)
        CombatScheduler(game, a, b).run()
        self.assertEqual(m.get(GameTag.AVENGE_COUNTER, 0), 0)
        self.assertEqual(e.get(GameTag.AVENGE_COUNTER, 0), 0)

    def test_trinket_avenge_counting(self):
        """Avenge 计数覆盖饰品实体（脚本以 avenge_threshold 声明阈值）。

        回归: 旧实现只扫 hero.board → 饰品/任务奖励上的 Avenge 卡
        （BG30_MagicItem_437 / BG32_MagicItem_270 等）注册即 no-op。
        且仅**战斗内**计数（`_active_combat` 守卫）。
        """
        game = self._game(seed=110)
        a, b = game.heroes
        calls = []

        class FakeTrinket:
            avenge_threshold = 2

            @staticmethod
            def avenge(source, game, ctx):
                calls.append(source)

        e = game.create_entity("BG30_MagicItem_437", controller=a)
        e.scripts = FakeTrinket
        a.trinkets.append(e)

        def kill(combat: bool):
            m = game.create_minion("BG25_001", controller=a)
            game.summon(a, m)
            m.set(GameTag.HEALTH, 0)
            if combat:
                game._active_combat = (a, b)
            game._process_single_death(m)
            game._active_combat = None

        kill(combat=False)
        kill(combat=False)
        self.assertEqual(len(calls), 0)     # 招募期死亡不计
        self.assertEqual(e.get(GameTag.AVENGE_COUNTER, 0), 0)

        kill(combat=True)
        self.assertEqual(len(calls), 0)     # 战斗内 1/2
        kill(combat=True)
        self.assertEqual(len(calls), 1)     # 2/2 → 触发并清零
        kill(combat=True)
        self.assertEqual(len(calls), 1)     # 重新计数 1/2


class TestTavernSpellExtraCast(unittest.TestCase):
    """RULES §7.4.14 — "Your Tavern spells cast an extra time"
    (`hero.extra_triggers["tavern_spell_extra_cast"]`, BG28_Reward_501).
    """

    def test_pool_spell_casts_one_extra_time(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        target = Minion("TEST_TEC_T", "T", atk=2, health=2)
        game.summon(a, target)
        a.extra_triggers["tavern_spell_extra_cast"] = 1
        d = get_db().get("BG28_897")
        spell = game.create_spell("BG28_897", controller=a)
        a.hand.append(spell)
        spell.zone = Zone.HAND
        game.play_spell(a, spell, target=target)
        self.assertEqual(target.atk, 2 + d.num(0) * 2)       # 双施
        self.assertEqual(target.max_health, 2 + d.num(1) * 2)

    def test_quota_is_permanent_not_first_only(self):
        """额度是 hero 级**永久**声明——同回合第二个酒馆法术仍双施。"""
        game = make_game(seed=22)
        a = game.heroes[0]
        a.extra_triggers["tavern_spell_extra_cast"] = 1
        d = get_db().get("BG28_897")
        for _ in range(2):
            t = Minion("TEST_TEC_M", "M", atk=1, health=1)
            game.summon(a, t)
            s = game.create_spell("BG28_897", controller=a)
            a.hand.append(s)
            s.zone = Zone.HAND
            game.play_spell(a, s, target=t)
            self.assertEqual(t.atk, 1 + d.num(0) * 2)

    def test_non_pool_spell_not_doubled(self):
        """门禁 = `is_pool_spell`: 生成类法术（Lantern Light）不受影响。"""
        game = make_game(seed=23)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        target = Minion("TEST_TEC_N", "N", atk=2, health=2)
        game.summon(a, target)
        a.extra_triggers["tavern_spell_extra_cast"] = 1
        d = get_db().get("BG28_885")
        self.assertFalse(d.is_pool_spell)
        spell = game.create_spell("BG28_885", controller=a)
        a.hand.append(spell)
        spell.zone = Zone.HAND
        game.play_spell(a, spell, target=target)
        self.assertEqual(target.atk, 2 + 6)                  # 单次（+tier）
        self.assertEqual(target.max_health, 2 + 6)

    def test_stacks_with_spell_first_quota(self):
        """与 `spell_first`（Replica Cathedral）独立叠加（3 次）。"""
        game = make_game(seed=24)
        a = game.heroes[0]
        target = Minion("TEST_TEC_S", "S", atk=1, health=1)
        game.summon(a, target)
        a.extra_triggers["tavern_spell_extra_cast"] = 1
        a.extra_triggers["spell_first"] = 1
        d = get_db().get("BG28_897")
        spell = game.create_spell("BG28_897", controller=a)
        a.hand.append(spell)
        spell.zone = Zone.HAND
        game.play_spell(a, spell, target=target)
        self.assertEqual(target.atk, 1 + d.num(0) * 3)


class TestTavernRaceGuarantee(unittest.TestCase):
    """RULES §7.4.14 — per-slot race guarantee
    (`hero._tavern_race_guarantee = (race, n)`, BG27_Reward_812).
    """

    @staticmethod
    def _naga_eligible(m: Minion) -> bool:
        # 多类型身份（AC-3）: NAGA per-race tag 命中即合格; ALL 已展开为全族。
        return m.has_race(Race.NAGA)

    def test_first_slots_are_guaranteed_race(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        a._tavern_race_guarantee = (Race.NAGA, 2)
        game.refresh_tavern(a, free=True)
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertGreaterEqual(len(minions), 2)
        # 前两位**专供**（drawn_ids = guaranteed + rest 的顺序）
        self.assertTrue(self._naga_eligible(minions[0]))
        self.assertTrue(self._naga_eligible(minions[1]))

    def test_hero_scope_does_not_leak_to_opponent(self):
        game = make_game(seed=32)
        a, b = game.heroes
        for h in (a, b):
            h.set(GameTag.TAVERN_TIER, 6)
        a._tavern_race_guarantee = (Race.NAGA, 99)   # 全部随从位保证
        game.refresh_tavern(a, free=True)
        game.refresh_tavern(b, free=True)
        a_minions = [e for e in a.tavern if isinstance(e, Minion)]
        b_minions = [e for e in b.tavern if isinstance(e, Minion)]
        self.assertTrue(a_minions)
        self.assertTrue(all(self._naga_eligible(m) for m in a_minions))
        # 固定种子确定性: 对手酒馆至少有 1 个非纳迦
        self.assertTrue(any(not self._naga_eligible(m) for m in b_minions))

    def test_pool_exhaustion_degrades_without_injection(self):
        """保证种族在当前档位无可用副本 → 该位回落通用池，不注入。"""
        game = make_game(seed=33)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 1)          # 无 Race.ALL 随从在 T1
        a._tavern_race_guarantee = (Race.ALL, 2)
        game.refresh_tavern(a, free=True)
        from hsrl2 import constants as C
        expect = C.TAVERN_OFFERS.get(1, 6)
        self.assertEqual(len([e for e in a.tavern
                              if isinstance(e, Minion)]), expect)

    def test_guarantee_respects_tavern_tier_ceiling(self):
        """保证位同样受展示档位约束——只从 ≤ 酒馆等级抽取。"""
        game = make_game(seed=34)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 2)
        a._tavern_race_guarantee = (Race.NAGA, 2)
        game.refresh_tavern(a, free=True)
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(all(m.tech_level <= 2 for m in minions))


class TestTemporaryGolden(unittest.TestCase):
    """RULES §7.4.14 — "Make a friendly minion Golden until next turn"
    (`Game.make_golden_until_next_turn`, BG24_Reward_719t).
    """

    def test_golden_then_reverts_next_turn(self):
        game = make_game(seed=41)
        a = game.heroes[0]
        d = find_plain(get_db())
        g = get_db().golden_version(d)
        m = game.create_minion(d.id, controller=a)
        game.summon(a, m)
        self.assertTrue(game.make_golden_until_next_turn(m))
        gold = a.board[0]
        self.assertTrue(gold.is_golden)
        self.assertEqual(gold.card_id, g.id)
        self.assertEqual(gold.atk, g.atk)
        self.assertTrue(gold.get(GameTag.GILDED_NOT_TRIPLED))
        # 其它英雄的 turn_start 不回滚
        game.events.fire(game, "turn_start", turn=2, hero=game.heroes[1])
        self.assertTrue(a.board[0].is_golden)
        # 控制者下回合开始 → 回滚为非金
        game.events.fire(game, "turn_start", turn=2, hero=a)
        back = a.board[0]
        self.assertFalse(back.is_golden)
        self.assertEqual(back.card_id, d.id)
        self.assertEqual(back.atk, d.atk)

    def test_buffs_preserved_both_ways(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        d = find_plain(get_db())
        g = get_db().golden_version(d)
        m = game.create_minion(d.id, controller=a)
        game.summon(a, m)
        game.run_actions(Buff(m, atk=3, health=3))
        game.make_golden_until_next_turn(m)
        self.assertEqual(a.board[0].atk, g.atk + 3)
        self.assertEqual(a.board[0].max_health, g.health + 3)
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertEqual(a.board[0].atk, d.atk + 3)
        self.assertEqual(a.board[0].max_health, d.health + 3)

    def test_already_golden_is_noop(self):
        game = make_game(seed=43)
        a = game.heroes[0]
        d = find_plain(get_db())
        g = get_db().golden_version(d)
        m = game.create_minion(d.id, controller=a, golden=True)
        game.summon(a, m)
        self.assertTrue(game.make_golden_until_next_turn(m))
        self.assertEqual(a.board[0].card_id, g.id)
        # 无回滚登记: 下回合仍为金色
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertTrue(a.board[0].is_golden)

    def test_offboard_target_whiffs(self):
        game = make_game(seed=44)
        a = game.heroes[0]
        d = find_plain(get_db())
        m = game.create_minion(d.id, controller=a)
        self.assertFalse(game.make_golden_until_next_turn(m))


class TestSnapshotAuraExclusion(unittest.TestCase):
    """RULES §6.19/§7.4.10b — "exact copy"/"maximum stats" 快照口径
    = base + 附魔（**不含光环**）；实时光环由新实体重算，不得双计
    （2026-09-13 对抗验证 MAJOR）。
    """

    def _mech(self, game, hero):
        d = next(x for x in get_db().pool_minions()
                 if x.race == Race.MECH
                 and get_db().golden_version(x) is not None)
        m = game.create_minion(d.id, controller=hero)
        game.summon(hero, m)
        return d, m

    def test_stats_without_aura_excludes_race_and_card_auras(self):
        game = make_game(seed=45)
        a = game.heroes[0]
        d, m = self._mech(game, a)
        self.assertEqual(m.stats_without_aura(), (d.atk, d.health))
        # 种族光环 +2/+2: `atk`/`max_health` 含光环，`stats_without_aura` 不含
        game.run_actions(ApplyRaceAura(a, Race.MECH, 2, 2))
        self.assertEqual((m.atk, m.max_health), (d.atk + 2, d.health + 2))
        self.assertEqual(m.stats_without_aura(), (d.atk, d.health))
        # 附魔计入（base + 附魔），光环仍排除
        game.run_actions(Buff(m, atk=3, health=1))
        self.assertEqual(m.stats_without_aura(), (d.atk + 3, d.health + 1))
        self.assertEqual((m.atk, m.max_health),
                         (d.atk + 5, d.health + 3))

    def test_combat_dead_snap_excludes_aura(self):
        game = make_game(seed=46)
        a = game.heroes[0]
        d, m = self._mech(game, a)
        game.run_actions([ApplyRaceAura(a, Race.MECH, 4, 4),
                          Buff(m, atk=1, health=1)])
        prev = game.in_combat
        game.in_combat = True
        try:
            game._record_combat_dead_snap(m, a)
        finally:
            game.in_combat = prev
        snap = a._combat_dead_snaps[0]
        # 死亡瞬间最终值 = base + 附魔 + 光环
        self.assertEqual((m.atk, m.max_health), (d.atk + 5, d.health + 5))
        # 快照 = base + 附魔（光环留给新实体重算）
        self.assertEqual((snap["atk"], snap["max_health"]),
                         (d.atk + 1, d.health + 1))
        # 消费者按快照重建基础值 → 实时光环重算后 == 死亡瞬间值
        rebuilt = game.create_minion(snap["card_id"], controller=a)
        rebuilt.set(GameTag.BASE_ATK, snap["atk"] - sum(
            b.atk for b in snap["buffs"]))
        rebuilt.set(GameTag.BASE_HEALTH, snap["max_health"] - sum(
            b.health for b in snap["buffs"]))
        for b in snap["buffs"]:
            rebuilt.add_buff(Enchant(atk=b.atk, health=b.health))
        game.summon(a, rebuilt)
        self.assertEqual((rebuilt.atk, rebuilt.max_health),
                         (m.atk, m.max_health))


class TestCardDiscoveredBoundary(unittest.TestCase):
    """`card_discovered` 不覆盖非卡牌选择（英雄技能三选一）——"After you
    Discover a **card**"（Hooktusk `BG36_344`）不得被技能发现误触发
    （2026-09-13 对抗验证: Cosmic Reward / Finley 选项令海盗白加 buff）。"""

    def test_hero_power_discover_does_not_fire_card_discovered(self):
        game = make_game(seed=49)
        a = game.heroes[0]
        seen = []
        game.events.register(Listener(
            event="card_discovered", owner=a,
            callback=lambda g, **kw: seen.append(kw)))
        game.pending_choices.append(PendingChoice(
            a, ["TB_BaconShop_HP_064", "BG28_HERO_801p"],
            "discover_hero_power"))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(seen, [])
        # 正对照: 真正的卡牌发现照常广播（option = 卡 id）
        game.pending_choices.append(PendingChoice(
            a, ["BGS_009", "BGS_043"], "discover_minion"))
        game.pending_choices.pop(0).choose(1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].get("option"), "BGS_043")
        self.assertEqual(seen[0].get("kind"), "discover_minion")


class TestDeathrattleCounterHookOnly(unittest.TestCase):
    """`trigger_deathrattle` 的计数/广播资格 = DEATHRATTLE tag **或**
    `deathrattle` 钩子（2026-09-13 对抗验证: 只有钩子的 Fish of N'Zoth
    效果已结算却不计数 → Falling Sky Golem / Death's Embrace 少计）。"""

    def test_hook_only_deathrattle_counts(self):
        game = make_game(seed=48)
        a = game.heroes[0]
        fish = game.create_minion("TB_BaconShop_HP_105t", controller=a)
        self.assertTrue(game.summon(a, fish))
        self.assertFalse(fish.has(GameTag.DEATHRATTLE))   # 无 tag，只有钩子
        self.assertTrue(game._has_deathrattle_hook(fish))
        before = a.get(GameTag.COUNTER_DEATHRATTLES, 0)
        game.trigger_deathrattle(fish)
        self.assertEqual(a.get(GameTag.COUNTER_DEATHRATTLES, 0),
                         before + 1)
        # 负对照: 无 tag 且无钩子的实体不计
        plain = game.create_minion("BG25_011", controller=a)
        game.summon(a, plain)
        self.assertFalse(game._has_deathrattle_hook(plain))
        n = a.get(GameTag.COUNTER_DEATHRATTLES, 0)
        game.trigger_deathrattle(plain)
        self.assertEqual(a.get(GameTag.COUNTER_DEATHRATTLES, 0), n)


class TestGiverBonusChannel(unittest.TestCase):
    """`hero.giver_bonus_rules` 家族给予者加成通道（RULES §7.4.15）。"""

    def test_accumulates_and_normalizes_golden(self):
        game = make_game(seed=50)
        a, b = game.heroes
        self.assertEqual(game.giver_bonus(a, "BG28_551"),
                         {"atk": 0, "health": 0, "copies": 0})
        game.add_giver_bonus(a, "BG28_551", atk=4, health=4)
        game.add_giver_bonus(a, "BG28_551_G", atk=1)     # 金色归一到基础
        self.assertEqual(game.giver_bonus(a, "BG28_551"),
                         {"atk": 5, "health": 4, "copies": 0})
        self.assertEqual(game.giver_bonus(a, "BG28_551_G"),
                         {"atk": 5, "health": 4, "copies": 0})
        # owner 隔离: B 无加成
        self.assertEqual(game.giver_bonus(b, "BG28_551"),
                         {"atk": 0, "health": 0, "copies": 0})
        # 读点是副本（改它不污染 hero 状态）
        game.giver_bonus(a, "BG28_551")["atk"] = 99
        self.assertEqual(game.giver_bonus(a, "BG28_551")["atk"], 5)

    def test_copies_accumulate(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        game.add_giver_bonus(a, "BG26_505", copies=1)
        game.add_giver_bonus(a, "BG26_505", copies=2)
        self.assertEqual(game.giver_bonus(a, "BG26_505")["copies"], 3)

    def test_source_liveness_gate(self):
        """`source` 离场 → 规则失效（同 `_card_aura_active` 口径）。"""
        game = make_game(seed=52)
        a = game.heroes[0]
        src = object()
        a.trinkets.append(src)
        game.add_giver_bonus(a, "BG28_551", atk=4, source=src)
        self.assertEqual(game.giver_bonus(a, "BG28_551")["atk"], 4)
        a.trinkets.remove(src)                  # 饰品被替换/移除
        self.assertEqual(game.giver_bonus(a, "BG28_551"),
                         {"atk": 0, "health": 0, "copies": 0})
        a.trinkets.append(src)                  # 回到场 → 规则复活
        self.assertEqual(game.giver_bonus(a, "BG28_551")["atk"], 4)

    def test_bad_inputs_fail_loud(self):
        game = make_game(seed=53)
        a = game.heroes[0]
        with self.assertRaises(GameStateError):
            game.add_giver_bonus(a, None, atk=1)
        with self.assertRaises(GameStateError):
            game.add_giver_bonus(None, "BG28_551", atk=1)
        with self.assertRaises(GameStateError):
            game.giver_bonus(None, "BG28_551")


class TestFamilyFlagChannel(unittest.TestCase):
    """`hero.family_flags` 家族行为开关通道（RULES §7.4.16）。"""

    def test_golden_normalization_and_owner_isolation(self):
        game = make_game(seed=60)
        a, b = game.heroes
        self.assertFalse(game.family_flag(a, "BG26_157", "flag_x"))
        game.add_family_flag(a, "BG26_157", "flag_x")
        self.assertTrue(game.family_flag(a, "BG26_157", "flag_x"))
        # 金色按基础卡 id 归一: 双向命中
        self.assertTrue(game.family_flag(a, "BG26_157_G", "flag_x"))
        game.add_family_flag(a, "BG26_157_G", "flag_y")
        self.assertTrue(game.family_flag(a, "BG26_157", "flag_y"))
        # 开关名精确匹配（不同开关互不串味）
        self.assertFalse(game.family_flag(a, "BG26_157", "flag_z"))
        # 卡家族精确匹配（同开关名不同卡不命中）
        self.assertFalse(game.family_flag(a, "BG28_551", "flag_x"))
        # owner 隔离: B 无开关
        self.assertFalse(game.family_flag(b, "BG26_157", "flag_x"))

    def test_source_liveness_gate(self):
        """`source` 离场 → 开关失效; 回到场 → 复活（§7.4.16 生效期）。"""
        game = make_game(seed=61)
        a = game.heroes[0]
        src = object()
        a.trinkets.append(src)
        game.add_family_flag(a, "BG26_157", "scope_all", source=src)
        self.assertTrue(game.family_flag(a, "BG26_157", "scope_all"))
        a.trinkets.remove(src)
        self.assertFalse(game.family_flag(a, "BG26_157", "scope_all"))
        a.trinkets.append(src)
        self.assertTrue(game.family_flag(a, "BG26_157", "scope_all"))
        # source=None = 永久规则（测试/引擎直写）
        game.add_family_flag(a, "BG26_157", "always_on")
        a.trinkets.remove(src)
        self.assertTrue(game.family_flag(a, "BG26_157", "always_on"))

    def test_source_liveness_covers_board_and_quest_rewards(self):
        """生效期与 §7.4.15 同口径: 棋盘实体与任务奖励实体同样计入。"""
        game = make_game(seed=63)
        a = game.heroes[0]
        on_board = object()
        a.board.append(on_board)
        game.add_family_flag(a, "BG26_157", "from_board", source=on_board)
        self.assertTrue(game.family_flag(a, "BG26_157", "from_board"))
        a.board.remove(on_board)
        self.assertFalse(game.family_flag(a, "BG26_157", "from_board"))
        reward = object()
        a.quest_rewards.append(reward)
        game.add_family_flag(a, "BG26_157", "from_reward", source=reward)
        self.assertTrue(game.family_flag(a, "BG26_157", "from_reward"))
        a.quest_rewards.remove(reward)
        self.assertFalse(game.family_flag(a, "BG26_157", "from_reward"))

    def test_bad_inputs_fail_loud(self):
        """拼写/类型错误 fail-loud——禁止静默 False（漏开关 = 静默半实现）。"""
        game = make_game(seed=62)
        a = game.heroes[0]
        with self.assertRaises(GameStateError):
            game.add_family_flag(None, "BG26_157", "f")
        with self.assertRaises(GameStateError):
            game.add_family_flag(a, None, "f")
        with self.assertRaises(GameStateError):
            game.add_family_flag(a, "BG26_157", "")
        with self.assertRaises(GameStateError):
            game.add_family_flag(a, "BG26_157", None)
        with self.assertRaises(GameStateError):
            game.family_flag(None, "BG26_157", "f")
        with self.assertRaises(GameStateError):
            game.family_flag(a, "BG26_157", "")
        # 读点同样校验 card_id（2026-09-13 对抗验证 MINOR: 曾静默 False）
        with self.assertRaises(GameStateError):
            game.family_flag(a, None, "f")
        with self.assertRaises(GameStateError):
            game.family_flag(a, "", "f")
        with self.assertRaises(GameStateError):
            game.family_flag(a, 123, "f")
        with self.assertRaises(GameStateError):
            game.family_flag(a, "BG26_157", None)


class TestConsumePolicyChannel(unittest.TestCase):
    """`hero.consume_policies` 吞噬目标策略通道（RULES §7.4.16b）。

    文本族: "Your **Demons** always consume the **highest-Health** minion
    in the Tavern"（Implicator Portrait `BG32_MagicItem_824`）。
    """

    @staticmethod
    def _pairs(game, hero, hi=9, lo=1):
        hi_m = Minion("TEST_HI", "HI", atk=1, health=hi)
        lo_m = Minion("TEST_LO", "LO", atk=1, health=lo)
        return [lo_m, hi_m], hi_m, lo_m

    def test_default_off_and_owner_isolation(self):
        game = make_game(seed=70)
        a, b = game.heroes
        self.assertIsNone(game.consume_policy(a))
        game.add_consume_policy(a, "highest_health")
        self.assertEqual(game.consume_policy(a), "highest_health")
        self.assertIsNone(game.consume_policy(b))

    def test_pick_victim_highest_for_own_demon(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        game.add_consume_policy(a, "highest_health")
        demon = game.create_minion("BG21_004", controller=a)
        cands, hi, lo = self._pairs(game, a)
        self.assertIs(game.pick_consume_victim(
            demon, cands, label="t"), hi)

    def test_pick_victim_random_without_policy_or_for_non_demon(self):
        from hsrl2.actions.consume import CONSUME_POLICY_HIGHEST_HEALTH
        # 无策略 → 随机（40 seed 两种结果都出现）
        out = set()
        for seed in range(1, 41):
            g = make_game(seed=seed)
            h = g.heroes[0]
            demon = g.create_minion("BG21_004", controller=h)
            cands, hi, lo = self._pairs(g, h)
            out.add("hi" if g.pick_consume_victim(
                demon, cands, label="t") is hi else "lo")
        self.assertEqual(out, {"hi", "lo"})
        # 有策略但消费者非恶魔 → 同样随机（"Your Demons" 范围）
        out2 = set()
        for seed in range(1, 41):
            g = make_game(seed=seed)
            h = g.heroes[0]
            g.add_consume_policy(h, CONSUME_POLICY_HIGHEST_HEALTH)
            beast = g.create_minion("BG31_803", controller=h)
            cands, hi, lo = self._pairs(g, h)
            out2.add("hi" if g.pick_consume_victim(
                beast, cands, label="t") is hi else "lo")
        self.assertEqual(out2, {"hi", "lo"})

    def test_source_liveness_gate(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        src = object()
        a.trinkets.append(src)
        game.add_consume_policy(a, "highest_health", source=src)
        self.assertEqual(game.consume_policy(a), "highest_health")
        a.trinkets.remove(src)
        self.assertIsNone(game.consume_policy(a))
        a.trinkets.append(src)
        self.assertEqual(game.consume_policy(a), "highest_health")
        # source=None = 永久规则（测试/引擎直写）
        game.add_consume_policy(a, "highest_health")
        a.trinkets.remove(src)
        self.assertEqual(game.consume_policy(a), "highest_health")

    def test_bad_inputs_fail_loud(self):
        game = make_game(seed=73)
        a = game.heroes[0]
        with self.assertRaises(GameStateError):
            game.add_consume_policy(None, "highest_health")
        with self.assertRaises(GameStateError):
            game.add_consume_policy(a, "")
        with self.assertRaises(GameStateError):
            game.add_consume_policy(a, None)
        with self.assertRaises(GameStateError):
            game.consume_policy(None)


class TestConditionalBattlecryChannel(unittest.TestCase):
    """条件化战吼（RULES §7.4.17）——`battlecry_flag` + `has_battlecry`。"""

    def _fake(self, flag):
        import types
        return types.SimpleNamespace(battlecry=lambda *a, **k: None,
                                     battlecry_flag=flag)

    def test_gate_follows_flag_and_source(self):
        g = make_game(seed=71)
        a, b = g.heroes
        m = g.create_minion("BG26_157", controller=a)
        m.scripts = self._fake("f_cond")
        src = object()
        self.assertFalse(g.has_battlecry(m))
        self.assertFalse(g.granted_battlecry(m))
        a.trinkets.append(src)
        g.add_family_flag(a, m.card_id, "f_cond", source=src)
        self.assertTrue(g.granted_battlecry(m))
        self.assertTrue(g.has_battlecry(m))
        self.assertTrue(g._has_battlecry_hook(m))       # 兼容别名
        a.trinkets.remove(src)
        self.assertFalse(g.granted_battlecry(m))
        self.assertFalse(g.has_battlecry(m))
        self.assertFalse(g.has_battlecry(
            g.create_minion("BG26_157", controller=b)))  # owner 隔离

    def test_unconditional_script_hook_unaffected(self):
        """无 `battlecry_flag` 的脚本钩子照旧算"有战吼"（行为不变）。"""
        g = make_game(seed=72)
        a, _b = g.heroes
        m = g.create_minion("BG26_157", controller=a)
        m.scripts = self._fake(None)
        self.assertTrue(g.has_battlecry(m))
        self.assertFalse(g.granted_battlecry(m))

    def test_script_override_counts_as_unconditional(self):
        """实体级 `set_script_override("battlecry", …)` 也是真战吼来源
        （2026-09-13 对抗验证 MINOR: `TriggerBattlecry` 门禁不得静默挡掉）。"""
        g = make_game(seed=74)
        a, _b = g.heroes
        m = g.create_minion("BG26_157", controller=a)
        m.scripts = self._fake(None)
        m.scripts.battlecry = None                 # 脚本侧无钩子
        self.assertFalse(g.has_battlecry(m))
        m.set_script_override("battlecry", lambda *x, **k: None)
        self.assertTrue(g.has_battlecry(m))

    def test_magnetic_attachment_conditional_flag(self):
        """磁力附件的条件化战吼按**附件卡 id** 查同一 hero 的开关
        （2026-09-13 对抗验证 MINOR 补齐: 此前带 flag 的附件被一律忽略）。"""
        from hsrl2.scripts import REGISTRY
        g = make_game(seed=75)
        a, _b = g.heroes
        host = g.create_minion("BG26_157", controller=a)
        aid = "TEST_MAGNET_ATTACH"
        cls = type("FakeAttach", (), {"battlecry": staticmethod(lambda *x: None),
                                     "battlecry_flag": "attach_flag"})
        had = REGISTRY.get(aid)
        REGISTRY[aid] = cls
        try:
            g._magnetic_stack[host.uuid] = [aid]
            self.assertFalse(g.has_battlecry(host))     # 开关未写
            src = object()
            a.trinkets.append(src)
            g.add_family_flag(a, aid, "attach_flag", source=src)
            self.assertTrue(g.has_battlecry(host))      # 开关生效
            a.trinkets.remove(src)
            self.assertFalse(g.has_battlecry(host))
        finally:
            if had is None:
                REGISTRY.pop(aid, None)
            else:
                REGISTRY[aid] = had
            g._magnetic_stack.pop(host.uuid, None)

    def test_keyword_tag_still_wins(self):
        g = make_game(seed=73)
        a, _b = g.heroes
        m = g.create_minion("BG26_157", controller=a)
        m.set(GameTag.BATTLECRY, True)
        m.scripts = self._fake("f_off")
        self.assertTrue(g.has_battlecry(m))     # tag 通道无条件
        self.assertFalse(g.granted_battlecry(m))


class TestMinionPoolPurge(unittest.TestCase):
    """`MinionPool.purge` 单元级（引擎原语契约）。"""

    def test_purge_blocks_every_path(self):
        g = make_game(seed=57)
        pool = g.minion_pool
        cid = next(c for c in pool.candidates(max_tier=7)
                   if pool.available(c) > 0)
        n = pool.available(cid)
        self.assertGreater(n, 0)
        self.assertEqual(pool.purge(cid), n)
        self.assertTrue(pool.is_purged(cid))
        self.assertEqual(pool.available(cid), 0)
        self.assertNotIn(cid, pool.candidates(max_tier=7))
        self.assertFalse(pool.acquire(cid))
        self.assertFalse(pool.ensure_available(cid))
        pool.release(cid, 3)
        self.assertEqual(pool.available(cid), 0)

    def test_purge_idempotent(self):
        g = make_game(seed=57)
        pool = g.minion_pool
        cid = next(c for c in pool.candidates(max_tier=7)
                   if pool.available(c) > 0)
        self.assertGreater(pool.purge(cid), 0)
        self.assertEqual(pool.purge(cid), 0)              # 第二次 no-op
        self.assertTrue(pool.is_purged(cid))

    def test_release_minion_entity_refused_after_purge(self):
        g = make_game(seed=57)
        pool = g.minion_pool
        cid = next(c for c in pool.candidates(max_tier=7)
                   if pool.available(c) > 0)
        m = g.create_minion(cid, controller=g.heroes[0])
        pool.purge(cid)
        pool.release_minion_entity(m)
        self.assertEqual(pool.available(cid), 0)

    def test_non_pooled_family_is_not_collateral(self):
        """purge 只作用于本卡 id（金色定义/同族其它卡不连带）。"""
        g = make_game(seed=57)
        pool = g.minion_pool
        cid = next(c for c in pool.candidates(max_tier=7)
                   if pool.available(c) > 0)
        d = get_db().get(cid)
        gv = get_db().golden_version(d)
        if gv is None:
            self.skipTest("该卡无金色定义")
        pool.purge(cid)
        self.assertFalse(pool.is_purged(gv.id))

    def test_unknown_or_non_minion_id_is_not_marked(self):
        """池记账域外（未知 id / 法术）→ 返回 0 且不标记（契约卫生）。"""
        g = make_game(seed=57)
        pool = g.minion_pool
        self.assertEqual(pool.purge("NO_SUCH_CARD"), 0)
        self.assertFalse(pool.is_purged("NO_SUCH_CARD"))
        spell = get_db().pool_spells()[0].id
        self.assertEqual(pool.purge(spell), 0)
        self.assertFalse(pool.is_purged(spell))
        self.assertFalse(pool.acquire(spell))             # 本就非随从池

    def test_fully_drawn_card_is_still_marked(self):
        """剩余副本为 0 的已知随从仍须标记（"permanently" 覆盖抽干态）。"""
        g = make_game(seed=57)
        pool = g.minion_pool
        cid = next(c for c in pool.candidates(max_tier=7)
                   if pool.available(c) > 0)
        while pool.available(cid) > 0:
            self.assertTrue(pool.acquire(cid))
        self.assertEqual(pool.purge(cid), 0)              # 已抽干
        self.assertTrue(pool.is_purged(cid))
        pool.release(cid, 3)
        self.assertEqual(pool.available(cid), 0)
        self.assertFalse(pool.ensure_available(cid))


class TestHeroPowerPendingQuota(unittest.TestCase):
    """挂起路径的次数配额复查（2026-09-13 对抗验证 MAJOR）。

    定向技能在目标选择**挂起期间**可再次发起 `use_hero_power`；计数在
    结算点才发生，故 N 个挂起结算会全部通过 → `uses_per_turn=2` 被叠加
    成 N 次。修复 = `_finish_hero_power` 结算时复查配额（与金币/目标
    复查同构），超额作废（不扣费、不计数、无效果）。
    """

    EJECT = "BG31_Anomaly_117t"

    def _game(self):
        heroes = [Hero("BG20_HERO_103", "A"), Hero("BG20_HERO_103", "B")]
        game = Game(heroes, get_db(), seed=61)
        game.start_game()
        a = game.heroes[0]
        game.set_second_hero_power(a, self.EJECT)
        return game, a

    def test_pending_target_uses_cannot_exceed_per_turn(self):
        game, a = self._game()
        queued = 5
        for _ in range(queued):
            self.assertTrue(game.use_hero_power(a, power_id=self.EJECT))
        self.assertEqual(len(game.pending_choices), queued)
        self.assertEqual(a._power_uses_this_turn.get(self.EJECT, 0), 0)
        while game.pending_choices:
            game.pending_choices.pop(0).choose(0)
        # 只有 uses_per_turn=2 次真正结算（其余被复查作废）
        self.assertEqual(a._power_uses_this_turn.get(self.EJECT, 0), 2)
        # 作废的结算不扣费（cost=0 本就免费；此处验证未产生额外效果）
        self.assertEqual(a.gold, game.heroes[1].gold)

    def test_next_turn_quota_restored(self):
        game, a = self._game()
        for _ in range(2):
            self.assertTrue(game.use_hero_power(a, power_id=self.EJECT))
            while game.pending_choices:
                game.pending_choices.pop(0).choose(0)
        self.assertFalse(game.use_hero_power(a, power_id=self.EJECT))
        game.turn += 1
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        self.assertTrue(game.use_hero_power(a, power_id=self.EJECT))


if __name__ == "__main__":
    unittest.main()


def test_consume_policy_unknown_kind_fails_loud():
    """未关闭集合的 kind（拼写错误）必须 fail-loud, 不得静默降级为均匀
    随机（对抗验证实测: 旧实现接受任意非空串且全量套件察觉不到）。"""
    game = make_game(seed=74)
    a = game.heroes[0]
    with unittest.TestCase().assertRaises(GameStateError):
        game.add_consume_policy(a, "highest_healht")     # 拼写错误
    assert game.consume_policy(a) is None


def test_consume_policy_damaged_candidate_uses_max_health():
    """策略按 `max_health`（受伤的 11 血随从仍优先于满血 6/6）——对抗
    验证: 把比较换成 `health` 时全量套件原本 4037 全绿。"""
    from hsrl2.actions.consume import CONSUME_POLICY_HIGHEST_HEALTH
    game = make_game(seed=75)
    a = game.heroes[0]
    game.add_consume_policy(a, CONSUME_POLICY_HIGHEST_HEALTH)
    demon = game.create_minion("BG21_004", controller=a)
    big = Minion("TEST_BIG", "BIG", atk=1, health=11)
    big.health = 1                              # 当前血 1 / 上限 11
    small = Minion("TEST_SMALL", "SMALL", atk=1, health=6)
    assert game.pick_consume_victim(demon, [small, big], label="t") is big


def test_consume_policy_race_all_amalgam_included():
    """"Your Demons" 含 Race.ALL（万能型）: 真实 BG24_017 万能随从必须
    享有策略。

    变异敏感（对抗验证: 去掉 `Race.ALL` 后旧断言因 seed 76 双候选恰好
    抽到高值而仍全绿）:
      - 5 个**血量互异**的候选 × 多种候选顺序 → 策略下**每一次**都必须
        取最大值 9; 均匀随机无法对全部排列都返回最大值。
      - seed-matched 非万能（Race.NONE）对照: 同 seed 的均匀随机抽到
        **非**最大值 → 去掉 Race.ALL 后万能随从走同一均匀路径必返回
        该非最大值, 断言随即失败。
    """
    from hsrl2.actions.consume import CONSUME_POLICY_HIGHEST_HEALTH
    specs = [("A", 1), ("B", 4), ("C", 2), ("D", 9), ("E", 6)]
    orders = [specs, list(reversed(specs))] + [
        specs[i:] + specs[:i] for i in range(1, len(specs))]
    game = make_game(seed=76)
    a = game.heroes[0]
    game.add_consume_policy(a, CONSUME_POLICY_HIGHEST_HEALTH)
    amalgam = game.create_minion("BG24_017", controller=a)
    assert amalgam.race == Race.ALL
    # 候选顺序无关性: 策略下任何排列都取唯一最大值 9
    for order in orders:
        cands = [Minion(f"TEST_{n}", n, atk=1, health=h) for n, h in order]
        victim = game.pick_consume_victim(amalgam, cands, label="t")
        assert victim.max_health == 9, (order, victim.max_health)
    # seed-matched 非万能对照: 均匀随机**不**取最大值（未被策略接管）
    control = make_game(seed=76)
    b = control.heroes[0]
    control.add_consume_policy(b, CONSUME_POLICY_HIGHEST_HEALTH)
    plain = Minion("TEST_PLAIN", "PLAIN", atk=1, health=3)
    plain.controller = b
    assert plain.race not in (Race.DEMON, Race.ALL)
    ctrl_cands = [Minion(f"TEST_{n}", n, atk=1, health=h) for n, h in specs]
    ctrl = control.pick_consume_victim(plain, ctrl_cands, label="t")
    assert ctrl.max_health != 9
def test_family_races_is_additive_not_replacement():
    """F1 回归: 家族类型改写必须是**并集**（"additions, never
    exclusions", wiki `Multi-type minion` revid 855346）。构造: 无类型
    随从在 Incubation Mutation（`_notype_is_all`）下拥有全 10 族, 加上
    Smuggler Portrait 后仍须保有全部类型（此前实现为替换 → 只剩 1 类）。
    """
    import hsrl2.scripts  # noqa: F401  注册脚本
    from hsrl2.db import CardDB
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.tags import STANDARD_RACES

    db = CardDB.load(DATA_DIR)
    game = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")], db, seed=4242)
    game.start_game()
    a = game.heroes[0]
    game._notype_is_all = True                      # Incubation Mutation
    whelp = game.create_minion("BG21_013", controller=a)
    game.summon(a, whelp)
    before = whelp.races
    assert before == frozenset(STANDARD_RACES), before
    game.grant_trinket(a, "BG30_MagicItem_825")     # Smuggler Portrait
    after = whelp.races
    assert after >= before, f"家族改写削减了类型: {sorted(before)} -> {sorted(after)}"
    assert after == frozenset(STANDARD_RACES), after


def test_stormbringer_counts_dualtype_and_portrait_dragons():
    """F2 回归: 注册卡 Stormbringer `BG26_966` 的 "friendly Dragon"
    过滤必须读**类型身份集合**（`Minion.has_race`），旧的单值
    `minion.race not in (DRAGON, ALL)` 会漏掉:

      (a) 双类型 `BG27_005` Timecap'n Hooktail（CARDRACE=PIRATE,
          per-race DRAGON tag）——wiki `Minion` revid 817925
          "these minions benefit from the effects of both types";
      (b) Smuggler Portrait（`BG30_MagicItem_825`）家族改写下的
          Whelp Smuggler（数据无类型 → 身份 {DRAGON}）——wiki
          Patch 30.2.0.205267 revid 814123 官方 Dev Comment。

    基础单类型龙 `BG25_027` 为对照（旧实现已触发 → 证明测试观察的是
    "漏掉的身份"，不是整体失效）。真实路径: `Game.summon`（on_summon
    接线）+ `run_actions(Buff)` + `grant_trinket`。
    """
    game = make_game(seed=900)
    a = game.heroes[0]
    storm = game.create_minion("BG26_966", controller=a)
    game.summon(a, storm)
    # 对照: 基础单类型龙（旧实现已触发）
    plain = game.create_minion("BG25_027", controller=a)
    game.summon(a, plain)
    self_base = storm.atk
    game.run_actions(Buff(plain, atk=4))
    assert storm.atk == self_base + 4, ("base dragon control", storm.atk)
    # (a) 双类型（CARDRACE 主类型 = PIRATE, DRAGON 为次类型）
    dual = game.create_minion("BG27_005", controller=a)
    game.summon(a, dual)
    assert dual.race == Race.PIRATE and dual.has_race(Race.DRAGON), dual.races
    base = storm.atk
    game.run_actions(Buff(dual, atk=4))
    assert storm.atk == base + 4, ("dual-type dragon missed", storm.atk)
    # (b) 家族 Portrait 改写: 数据无类型 Whelp → 身份 {DRAGON}
    whelp = game.create_minion("BG21_013", controller=a)
    game.summon(a, whelp)
    assert whelp.races == frozenset(), whelp.races
    game.grant_trinket(a, "BG30_MagicItem_825")     # Smuggler Portrait
    assert whelp.races == frozenset({Race.DRAGON}), whelp.races
    base = storm.atk
    game.run_actions(Buff(whelp, atk=3))
    assert storm.atk == base + 3, ("portrait dragon missed", storm.atk)
