"""批次 spells1 语义测试（作业单 2026-08-21，13 张池法术）。

覆盖: BG28_168 Shiny Ring / BG28_169 Azerite Empowerment / BG28_500
Armor Stash / BG28_503 Fortify / BG28_504 Recruit a Trainee / BG28_507
Sacred Gift / BG28_512 Enchanted Lasso / BG28_520 Tricky Trousers /
BG28_521 Planar Telescope（含 BG28_521t Consolation Coin）/ BG28_571
Hasty Excavation / BG28_573 Upper Hand / BG28_601 Cloning Conch /
BG28_603 Boon of Beetles。

驱动: game.play_spell(hero, spell, target=...)（定向法术不传 target 走
PendingChoice(kind="spell_target")）; SoC 类经 CombatScheduler.
_start_of_combat_phase 或完整 run_combat; 数值期望一律 CardDef.num()
（无模板参数的卡注明字面量来源）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.constants import BOARD_SIZE
from hsrl2.db import CardDB
from hsrl2.events import START_OF_COMBAT
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42) -> Game:
    return Game([make_hero("A"), make_hero("B")], get_db(), seed=seed)


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def put(game: Game, m: Minion, hero: Hero) -> Minion:
    m.controller = hero
    game.summon(hero, m)
    return m


def add_spell(game: Game, hero: Hero, card_id: str) -> Spell:
    """create_spell（含 REGISTRY 绑定）→ 入手。"""
    s = game.create_spell(card_id, controller=hero)
    hero.add_to_hand(s)
    return s


def soc(game: Game, a: Hero, b: Hero) -> None:
    """单独驱动 SoC 阶段（RULES §4.2 全四档）。

    引擎契约: game._active_combat 由 CombatScheduler.run 在 SoC 前设置
    （combat.py:54）——单独驱动时手动镜像该契约。
    """
    game._active_combat = (a, b)
    try:
        CombatScheduler(game, a, b)._start_of_combat_phase()
    finally:
        game._active_combat = None


def soc_listeners(game: Game) -> int:
    return len(game.events._listeners.get(START_OF_COMBAT, []))


class TestShinyRing(unittest.TestCase):
    """BG28_168 — Give your minions +{0}/+{1}."""

    def test_buffs_all_friendly_minions_with_extra(self):
        game = make_game(seed=300)
        a = game.heroes[0]
        d = get_db().get("BG28_168")
        m1 = put(game, make_minion("M1", 3, 4), a)
        m2 = put(game, make_minion("M2", 1, 1), a)
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 1)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 1)
        s = add_spell(game, a, "BG28_168")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(m1.atk, 3 + d.num(0) + 1)
        self.assertEqual(m1.max_health, 4 + d.num(1) + 1)
        self.assertEqual(m2.atk, 1 + d.num(0) + 1)
        self.assertEqual(m2.max_health, 1 + d.num(1) + 1)
        self.assertEqual(len(game.pending_choices), 0)   # 非定向全体
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 1)

    def test_empty_board_fizzles_but_consumes(self):
        game = make_game(seed=301)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_168")
        self.assertTrue(game.play_spell(a, s))
        self.assertNotIn(s, a.hand)


class TestAzeriteEmpowerment(unittest.TestCase):
    """BG28_169 — Give your minions +{0}/+{1} twice."""

    def test_applies_twice_to_all(self):
        game = make_game(seed=302)
        a = game.heroes[0]
        d = get_db().get("BG28_169")
        m = put(game, make_minion("M", 5, 6), a)
        s = add_spell(game, a, "BG28_169")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(m.atk, 5 + 2 * d.num(0))
        self.assertEqual(m.max_health, 6 + 2 * d.num(1))
        self.assertEqual(len(m.buffs), 2)   # 两次独立 buff 实体

    def test_extra_applies_per_application(self):
        game = make_game(seed=303)
        a = game.heroes[0]
        d = get_db().get("BG28_169")
        m = put(game, make_minion("M", 0, 1), a)
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 2)
        s = add_spell(game, a, "BG28_169")
        game.play_spell(a, s)
        self.assertEqual(m.atk, 2 * (d.num(0) + 2))


class TestArmorStash(unittest.TestCase):
    """BG28_500 — Set your Armor to 5.（字面量 5: CardDef 无模板参数）"""

    def test_set_overwrites_higher_armor(self):
        game = make_game(seed=304)
        a = game.heroes[0]
        a.armor = 12
        s = add_spell(game, a, "BG28_500")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a.armor, 5)

    def test_set_raises_lower_armor(self):
        game = make_game(seed=305)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_500")
        game.play_spell(a, s)
        self.assertEqual(a.armor, 5)


class TestFortify(unittest.TestCase):
    """BG28_503 — Give a minion +{1} Health and Taunt.（基础版无 {0}）"""

    def test_buffs_health_and_taunt_with_target(self):
        game = make_game(seed=306)
        a = game.heroes[0]
        d = get_db().get("BG28_503")
        m = put(game, make_minion("M", 2, 3), a)
        s = add_spell(game, a, "BG28_503")
        self.assertTrue(game.play_spell(a, s, target=m))
        self.assertEqual(m.atk, 2 + (d.num(0) if d.num(0) is not None else 0))
        self.assertEqual(m.max_health, 3 + d.num(1))
        self.assertTrue(m.has(GameTag.TAUNT))

    def test_pending_choice_flow_and_extra_health(self):
        game = make_game(seed=307)
        a = game.heroes[0]
        d = get_db().get("BG28_503")
        m = put(game, make_minion("M", 1, 1), a)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 1)
        s = add_spell(game, a, "BG28_503")
        self.assertTrue(game.play_spell(a, s))   # 无 target → 分流
        self.assertEqual(len(game.pending_choices), 1)
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "spell_target")
        self.assertIn(m, pc.options)
        pc.choose(pc.options.index(m))
        self.assertEqual(m.max_health, 1 + d.num(1) + 1)
        self.assertTrue(m.has(GameTag.TAUNT))

    def test_empty_board_spell_still_consumed(self):
        game = make_game(seed=308)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_503")
        self.assertTrue(game.play_spell(a, s))
        self.assertNotIn(s, a.hand)
        self.assertEqual(len(game.pending_choices), 0)


class TestRecruitATrainee(unittest.TestCase):
    """BG28_504 — Get a random Tier 1 minion."""

    def test_gets_tier1_minion_from_pool(self):
        import hsrl2.constants as C
        game = make_game(seed=309)
        a = game.heroes[0]
        pool = game.minion_pool
        total_before = pool.total_remaining()
        s = add_spell(game, a, "BG28_504")
        self.assertTrue(game.play_spell(a, s))
        got = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(got), 1)
        self.assertEqual(get_db().get(got[0].card_id).tech_level, 1)
        self.assertEqual(pool.total_remaining(), total_before - 1)
        tier = get_db().get(got[0].card_id).tech_level
        self.assertEqual(pool.available(got[0].card_id),
                         C.POOL_COPIES_BY_TIER[tier] - 1)


class TestSacredGift(unittest.TestCase):
    """BG28_507 — Give a minion Divine Shield."""

    def test_grants_divine_shield(self):
        game = make_game(seed=310)
        a = game.heroes[0]
        m = put(game, make_minion("M", 4, 4), a)
        s = add_spell(game, a, "BG28_507")
        self.assertTrue(game.play_spell(a, s, target=m))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))

    def test_no_target_goes_through_pending_choice(self):
        game = make_game(seed=311)
        a = game.heroes[0]
        m = put(game, make_minion("M", 4, 4), a)
        s = add_spell(game, a, "BG28_507")
        game.play_spell(a, s)
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "spell_target")
        pc.choose(pc.options.index(m))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))


class TestEnchantedLasso(unittest.TestCase):
    """BG28_512 — Steal a random minion from the Tavern."""

    def _tavern_minion(self, game, a, card_id):
        game.minion_pool.acquire(card_id)
        m = game.create_minion(card_id, controller=a)
        m.zone = Zone.TAVERN
        a.tavern.append(m)
        return m

    def test_steals_entity_without_reacquiring(self):
        game = make_game(seed=312)
        a = game.heroes[0]
        m = self._tavern_minion(game, a, "BG23_000")
        avail_before = game.minion_pool.available("BG23_000")
        s = add_spell(game, a, "BG28_512")
        self.assertTrue(game.play_spell(a, s))
        self.assertIn(m, a.hand)                 # 实体身份转移
        self.assertNotIn(m, a.tavern)
        self.assertEqual(m.zone, Zone.HAND)
        self.assertEqual(game.minion_pool.available("BG23_000"),
                         avail_before)           # 不重复占池

    def test_spells_in_tavern_not_stealable(self):
        game = make_game(seed=313)
        a = game.heroes[0]
        sp = game.create_spell("BG28_168", controller=a)
        sp.zone = Zone.TAVERN
        a.tavern.append(sp)
        s = add_spell(game, a, "BG28_512")
        self.assertTrue(game.play_spell(a, s))
        self.assertIn(sp, a.tavern)
        self.assertNotIn(sp, a.hand)

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=314)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_512")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a.hand, [])


class TestTrickyTrousers(unittest.TestCase):
    """BG28_520 — Give a minion +{0}/+{1} and Taunt. If it already has
    Taunt, remove it."""

    def test_plain_target_gains_taunt(self):
        game = make_game(seed=315)
        a = game.heroes[0]
        d = get_db().get("BG28_520")
        m = put(game, make_minion("M", 1, 2), a)
        s = add_spell(game, a, "BG28_520")
        self.assertTrue(game.play_spell(a, s, target=m))
        self.assertEqual(m.atk, 1 + d.num(0))
        self.assertEqual(m.max_health, 2 + d.num(1))
        self.assertTrue(m.has(GameTag.TAUNT))

    def test_taunt_target_loses_taunt_but_keeps_buff(self):
        from hsrl2.actions import GainKeyword
        game = make_game(seed=316)
        a = game.heroes[0]
        d = get_db().get("BG28_520")
        m = put(game, make_minion("M", 1, 2), a)
        game.run_actions(GainKeyword(m, GameTag.TAUNT))
        s = add_spell(game, a, "BG28_520")
        self.assertTrue(game.play_spell(a, s, target=m))
        self.assertEqual(m.atk, 1 + d.num(0))
        self.assertEqual(m.max_health, 2 + d.num(1))
        self.assertFalse(m.has(GameTag.TAUNT))


class TestPlanarTelescope(unittest.TestCase):
    """BG28_521 — Discover a minion of your most common type."""

    def test_discovers_most_common_race(self):
        game = make_game(seed=317)
        a = game.heroes[0]
        put(game, make_minion("Mur1", 1, 1, race=Race.MURLOC), a)
        put(game, make_minion("Mur2", 1, 1, race=Race.MURLOC), a)
        put(game, make_minion("Beast", 1, 1, race=Race.BEAST), a)
        s = add_spell(game, a, "BG28_521")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(len(game.pending_choices), 1)
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "discover_minion")
        for opt in pc.options:
            self.assertIn(get_db().get(opt).race,
                          (Race.MURLOC, Race.ALL))
        pick = pc.options[0]
        avail_before = game.minion_pool.available(pick)
        pc.choose(0)
        got = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].card_id, pick)
        self.assertEqual(game.minion_pool.available(pick), avail_before - 1)

    def test_no_race_minions_gives_consolation_coin(self):
        game = make_game(seed=318)
        a = game.heroes[0]
        put(game, make_minion("Plain", 1, 1), a)   # 无种族随从
        s = add_spell(game, a, "BG28_521")
        self.assertTrue(game.play_spell(a, s))
        coins = [c for c in a.hand if c.card_id == "BG28_521t"]
        self.assertEqual(len(coins), 1)
        gold_before = a.gold
        self.assertTrue(game.play_spell(a, coins[0]))
        self.assertEqual(a.gold, gold_before + 1)

    def test_empty_board_gives_consolation_coin(self):
        game = make_game(seed=319)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_521")
        game.play_spell(a, s)
        self.assertTrue(any(c.card_id == "BG28_521t" for c in a.hand))


class TestHastyExcavation(unittest.TestCase):
    """BG28_571 — Gain 1 Gold. This costs Health to buy instead of Gold.

    购买侧扣血 = 引擎缺口（buy_from_tavern 无 health_cost 消费），
    本测试仅覆盖施放效果。
    """

    def test_gains_one_gold(self):
        game = make_game(seed=320)
        a = game.heroes[0]
        a.gold = 3
        s = add_spell(game, a, "BG28_571")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a.gold, 4)


class TestUpperHand(unittest.TestCase):
    """BG28_573 — SoC: Set a random enemy minion's Health to 1.
    （"to 1" 文本字面量: CardDef 无模板参数）"""

    def test_soc_sets_random_enemy_health_to_1(self):
        game = make_game(seed=321)
        a, b = game.heroes
        put(game, make_minion("Friendly", 2, 5), a)
        enemy = put(game, make_minion("Enemy", 3, 7), b)
        s = add_spell(game, a, "BG28_573")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(soc_listeners(game), 1)
        soc(game, a, b)
        self.assertEqual(enemy.health, 1)
        self.assertEqual(enemy.get(GameTag.BASE_HEALTH), 1)
        self.assertEqual(enemy.atk, 3)          # 攻击不动
        self.assertEqual(
            len([m for m in game.heroes[0].board
                 if m.health == 1]), 0)         # 友方不受

    def test_listener_consumed_after_full_combat(self):
        game = make_game(seed=322)
        a, b = game.heroes
        put(game, make_minion("A1", 1, 10), a)
        put(game, make_minion("B1", 1, 10), b)
        s = add_spell(game, a, "BG28_573")
        game.play_spell(a, s)
        self.assertEqual(soc_listeners(game), 1)
        game.run_combat(a, b)
        self.assertEqual(soc_listeners(game), 0)   # once 已消耗、不复活
        game.run_combat(a, b)
        self.assertEqual(soc_listeners(game), 0)   # 第二场不再触发

    def test_empty_enemy_board_fizzles_but_consumes(self):
        game = make_game(seed=323)
        a, b = game.heroes
        put(game, make_minion("A1", 1, 5), a)
        s = add_spell(game, a, "BG28_573")
        game.play_spell(a, s)
        soc(game, a, b)
        self.assertEqual(soc_listeners(game), 0)


class TestCloningConch(unittest.TestCase):
    """BG28_601 — Get a random Murloc and a copy of it."""

    def test_gets_murloc_and_plain_copy_single_pool_copy(self):
        import hsrl2.constants as C
        game = make_game(seed=324)
        a = game.heroes[0]
        pool = game.minion_pool
        total_before = pool.total_remaining()
        s = add_spell(game, a, "BG28_601")
        self.assertTrue(game.play_spell(a, s))
        got = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0].card_id, got[1].card_id)
        self.assertIn(get_db().get(got[0].card_id).race,
                      (Race.MURLOC, Race.ALL))
        # 首份占池、副本不占: 全池总量恰好 -1
        self.assertEqual(pool.total_remaining(), total_before - 1)
        tier = get_db().get(got[0].card_id).tech_level
        self.assertEqual(pool.available(got[0].card_id),
                         C.POOL_COPIES_BY_TIER[tier] - 1)


class TestBoonOfBeetles(unittest.TestCase):
    """BG28_603 — When you have space in combat, summon two {0}/{1}
    Beetles and give them Taunt. ({2} left!)"""

    def _beetles(self, hero):
        return [m for m in hero.board if m.card_id == "BG28_603t"]

    def test_soc_summons_two_taunt_beetles_with_num_stats(self):
        game = make_game(seed=326)
        a, b = game.heroes
        d = get_db().get("BG28_603")
        put(game, make_minion("M", 1, 5), a)
        s = add_spell(game, a, "BG28_603")
        self.assertTrue(game.play_spell(a, s))
        soc(game, a, b)
        beetles = self._beetles(a)
        self.assertEqual(len(beetles), 2)
        for m in beetles:
            self.assertEqual(m.get(GameTag.BASE_ATK), d.num(0))
            self.assertEqual(m.get(GameTag.BASE_HEALTH), d.num(1))
            self.assertTrue(m.has(GameTag.TAUNT))

    def test_full_board_keeps_charge(self):
        game = make_game(seed=327)
        a, b = game.heroes
        for _ in range(BOARD_SIZE):
            put(game, make_minion("Fill", 1, 5), a)
        s = add_spell(game, a, "BG28_603")
        game.play_spell(a, s)
        soc(game, a, b)
        self.assertEqual(self._beetles(a), [])
        a.board.pop()   # 腾出空位（2 个: 供两只 Beetle）
        a.board.pop()
        soc(game, a, b)
        self.assertEqual(len(self._beetles(a)), 2)   # 次数未被板满消耗

    def test_full_board_defers_until_death_frees_space(self):
        """Evidence: r/BobsTavern 1dq54cu "It summons when there's
        space"——满板 SoC 不消耗，战斗中腾位后 AFTER_ATTACK 补召。"""
        game = make_game(seed=329)
        a, b = game.heroes
        for _ in range(BOARD_SIZE):
            put(game, make_minion("Fill", 1, 5), a)
        s = add_spell(game, a, "BG28_603")
        game.play_spell(a, s)
        soc(game, a, b)
        self.assertEqual(self._beetles(a), [])       # SoC: 满板不召
        enemy = put(game, make_minion("E", 10, 10), b)
        victim = a.board[0]
        CombatScheduler(game, a, b)._execute_attack(enemy, victim)
        self.assertEqual(len(self._beetles(a)), 1)   # 腾 1 位补 1 只
        for m in self._beetles(a):
            self.assertTrue(m.has(GameTag.TAUNT))

    def test_charges_exhaust_over_full_combats(self):
        game = make_game(seed=328)
        a, b = game.heroes
        put(game, make_minion("A1", 1, 10), a)
        put(game, make_minion("B1", 1, 10), b)
        s = add_spell(game, a, "BG28_603")
        game.play_spell(a, s)
        d = get_db().get("BG28_603")
        per_use = 2   # "summon two" 文本字面量
        expected_seq = [per_use] * d.num(2) + [0]
        for expected in expected_seq:
            game.run_combat(a, b)
            summoned = [m for m in game.combat_summon_log
                        if m.card_id == "BG28_603t"]
            self.assertEqual(len(summoned), expected)
        self.assertEqual(self._beetles(a), [])   # 战后 token 随快照消失


if __name__ == "__main__":
    unittest.main()
