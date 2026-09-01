"""批次 soc 语义测试（作业单 2026-08-21，10 张 Start of Combat 池随从）。

覆盖: BG24_500 Amber Guardian / BG26_354 Choral Mrrrglr /
BG26_805 Humming Bird / BG27_556 Diremuck Forager / BG31_999 Stitched
Salvager / BG32_330 Flighty Scout / BG32_822 Fire-forged Evoker /
BG34_142 Costume Enthusiast / BG36_245 Runic Arcanist / BG36_620
Boom-in-a-Box。

SoC 触发驱动: CombatScheduler(game,a,b)._start_of_combat_phase() 单独
驱动或完整 game.run_combat（回滚断言用）; 数值期望一律 CardDef.num()
计算。DEFERRED 卡（Flighty Scout / Boom-in-a-Box）断言其未注册
（DEFERRED 不注册契约，minions.py Tichondrius 先例）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.constants import BOARD_SIZE
from hsrl2.db import CardDB
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY, bind_all
from hsrl2.scripts.batches.batch_soc import SHINY_RING_ID
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


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def dummy(hero: Hero, health: int = 100) -> Minion:
    return make_minion("Dummy", 0, health)


def hand_minion(game: Game, hero: Hero, card_id: str,
                golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.add_to_hand(m)
    return m


def soc(game: Game, a: Hero, b: Hero) -> None:
    """单独驱动 SoC 阶段（饰品→奖励→随从→英雄技能，RULES §4.2）。"""
    CombatScheduler(game, a, b)._start_of_combat_phase()


class TestAmberGuardian(unittest.TestCase):
    """BG24_500 — Taunt; SoC: Give another friendly Dragon +{0}/+{1}
    and Divine Shield."""

    def test_soc_buffs_one_other_dragon_with_divine_shield(self):
        game = make_game(seed=200)
        a, b = game.heroes
        d = get_db().get("BG24_500")
        guardian = put(game, "BG24_500", a)
        dragon = make_minion("Dragon", 1, 5, race=Race.DRAGON)
        game.summon(a, dragon)
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        soc(game, a, b)
        self.assertEqual(dragon.atk, 1 + d.num(0))
        self.assertEqual(dragon.max_health, 5 + d.num(1))
        self.assertTrue(dragon.has(GameTag.DIVINE_SHIELD))
        # "another" / 非龙: 自身与野兽不受
        self.assertEqual(guardian.atk, d.atk)
        self.assertEqual(guardian.max_health, d.health)
        self.assertFalse(guardian.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(beast.atk, 2)
        self.assertTrue(guardian.has(GameTag.TAUNT))   # data 权威关键词

    def test_soc_no_other_dragon_fizzles(self):
        game = make_game(seed=201)
        a, b = game.heroes
        d = get_db().get("BG24_500")
        guardian = put(game, "BG24_500", a)
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        soc(game, a, b)
        self.assertEqual(beast.atk, 2)
        self.assertEqual(guardian.atk, d.atk)

    def test_soc_via_full_combat_rolls_back_afterwards(self):
        game = make_game(seed=202)
        a, b = game.heroes
        d = get_db().get("BG24_500")
        guardian = put(game, "BG24_500", a)
        dragon = make_minion("Dragon", 1, 5, race=Race.DRAGON)
        game.summon(a, dragon)
        game.run_combat(a, b)   # b 空板 → 战斗立即结束
        # RULES §3.5: SoC buff/DS 战后回滚
        self.assertEqual(dragon.atk, 1)
        self.assertEqual(dragon.has(GameTag.DIVINE_SHIELD), False)
        self.assertEqual(guardian.atk, d.atk)

    def test_golden_buffs_two_other_dragons(self):
        game = make_game(seed=203)
        a, b = game.heroes
        dg = get_db().get("BG24_500_G")
        guardian = put(game, "BG24_500", a, golden=True)
        self.assertEqual(guardian.card_id, "BG24_500_G")
        d1 = make_minion("D1", 1, 5, race=Race.DRAGON)
        d2 = make_minion("D2", 2, 6, race=Race.DRAGON)
        game.summon(a, d1)
        game.summon(a, d2)
        soc(game, a, b)
        for m in (d1, d2):
            self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(d1.atk, 1 + dg.num(0))
        self.assertEqual(d2.atk, 2 + dg.num(0))
        self.assertEqual(d1.max_health, 5 + dg.num(1))
        self.assertEqual(d2.max_health, 6 + dg.num(1))
        self.assertFalse(guardian.has(GameTag.DIVINE_SHIELD))

    def test_amalgam_counts_as_dragon(self):
        game = make_game(seed=204)
        a, b = game.heroes
        d = get_db().get("BG24_500")
        put(game, "BG24_500", a)
        amalgam = make_minion("Amal", 1, 1, race=Race.ALL)
        game.summon(a, amalgam)
        soc(game, a, b)
        self.assertEqual(amalgam.atk, 1 + d.num(0))
        self.assertTrue(amalgam.has(GameTag.DIVINE_SHIELD))


class TestChoralMrrrglr(unittest.TestCase):
    """BG26_354 — SoC: Gain the stats of all the minions in your hand."""

    def test_soc_gains_sum_of_hand_minion_stats(self):
        game = make_game(seed=205)
        a, b = game.heroes
        d = get_db().get("BG26_354")
        small = hand_minion(game, a, "BG33_323")   # Undead 2/6
        big = hand_minion(game, a, "BG27_017")     # Dragon 7/7
        spell = game.create_spell(SHINY_RING_ID, controller=a)
        a.add_to_hand(spell)                       # 法术不计入
        choral = put(game, "BG26_354", a)
        soc(game, a, b)
        sum_atk = (get_db().get(small.card_id).atk
                   + get_db().get(big.card_id).atk)
        sum_hp = (get_db().get(small.card_id).health
                  + get_db().get(big.card_id).health)
        self.assertEqual(choral.atk, d.atk + sum_atk)
        self.assertEqual(choral.max_health, d.health + sum_hp)
        # 手牌实体只读
        self.assertIn(small, a.hand)
        self.assertIn(big, a.hand)

    def test_soc_empty_hand_fizzles(self):
        game = make_game(seed=206)
        a, b = game.heroes
        d = get_db().get("BG26_354")
        choral = put(game, "BG26_354", a)
        soc(game, a, b)
        self.assertEqual(choral.atk, d.atk)
        self.assertEqual(choral.max_health, d.health)

    def test_golden_gains_twice(self):
        game = make_game(seed=207)
        a, b = game.heroes
        dg = get_db().get("BG26_354_G")
        m = hand_minion(game, a, "BG33_323")
        choral = put(game, "BG26_354", a, golden=True)
        soc(game, a, b)
        self.assertEqual(choral.atk,
                         dg.atk + 2 * get_db().get(m.card_id).atk)
        self.assertEqual(choral.max_health,
                         dg.health + 2 * get_db().get(m.card_id).health)

    def test_buff_rolls_back_after_combat(self):
        game = make_game(seed=208)
        a, b = game.heroes
        d = get_db().get("BG26_354")
        hand_minion(game, a, "BG33_323")
        choral = put(game, "BG26_354", a)
        game.run_combat(a, b)
        self.assertEqual(choral.atk, d.atk)       # 战斗内获得、战后消失
        self.assertEqual(choral.max_health, d.health)


class TestHummingBird(unittest.TestCase):
    """BG26_805 — SoC: For the rest of this combat, your Beasts have
    +1 Attack."""

    def test_soc_gives_all_beasts_plus_one_including_self(self):
        game = make_game(seed=209)
        a, b = game.heroes
        d = get_db().get("BG26_805")
        bird = put(game, "BG26_805", a)           # 自身是 Beast
        beast = make_minion("Beast", 3, 3, race=Race.BEAST)
        game.summon(a, beast)
        dragon = make_minion("Dragon", 2, 2, race=Race.DRAGON)
        game.summon(a, dragon)
        soc(game, a, b)
        self.assertEqual(bird.atk, d.atk + 1)
        self.assertEqual(beast.atk, 3 + 1)
        self.assertEqual(dragon.atk, 2)           # 非兽 +0
        self.assertEqual(bird.max_health, d.health)   # 仅攻击

    def test_midcombat_summoned_beast_gets_bonus(self):
        game = make_game(seed=210)
        a, b = game.heroes
        bird = put(game, "BG26_805", a)
        soc(game, a, b)
        game.in_combat = True                     # 手动进入战斗态
        try:
            new_beast = make_minion("NewBeast", 3, 3, race=Race.BEAST)
            game.summon(a, new_beast)
            new_dragon = make_minion("NewDragon", 2, 2, race=Race.DRAGON)
            game.summon(a, new_dragon)
        finally:
            game.in_combat = False
        self.assertEqual(new_beast.atk, 4)        # "rest of this combat"
        self.assertEqual(new_dragon.atk, 2)

    def test_dead_source_aura_stops(self):
        game = make_game(seed=211)
        a, b = game.heroes
        bird = put(game, "BG26_805", a)
        soc(game, a, b)
        game.in_combat = True
        try:
            bird.health = 0                       # 光环源阵亡 → 注销监听
            game.check_deaths()
            new_beast = make_minion("LateBeast", 3, 3, race=Race.BEAST)
            game.summon(a, new_beast)
        finally:
            game.in_combat = False
        self.assertEqual(new_beast.atk, 3)

    def test_golden_plus_two(self):
        game = make_game(seed=212)
        a, b = game.heroes
        bird = put(game, "BG26_805", a, golden=True)
        beast = make_minion("Beast", 3, 3, race=Race.BEAST)
        game.summon(a, beast)
        soc(game, a, b)
        self.assertEqual(beast.atk, 5)
        game.in_combat = True
        try:
            late = make_minion("Late", 1, 1, race=Race.ALL)   # ALL=兽
            game.summon(a, late)
        finally:
            game.in_combat = False
        self.assertEqual(late.atk, 3)

    def test_bonus_rolls_back_after_combat(self):
        game = make_game(seed=213)
        a, b = game.heroes
        d = get_db().get("BG26_805")
        bird = put(game, "BG26_805", a)
        beast = make_minion("Beast", 3, 3, race=Race.BEAST)
        game.summon(a, beast)
        game.run_combat(a, b)
        self.assertEqual(bird.atk, d.atk)
        self.assertEqual(beast.atk, 3)


class TestDiremuckForager(unittest.TestCase):
    """BG27_556 — SoC: When you have space, summon the highest-Attack
    Murloc from your hand for this combat only."""

    def test_soc_summons_highest_atk_murloc_copy(self):
        game = make_game(seed=214)
        a, b = game.heroes
        forager = put(game, "BG27_556", a)
        low = hand_minion(game, a, "BG33_140")     # Murloc 1/1
        high = hand_minion(game, a, "BG34_145")    # Murloc 7/13
        beast = hand_minion(game, a, "BG34_322")   # Beast 16/32（更高攻）
        soc(game, a, b)
        self.assertEqual(len(a.board), 2)
        copy = a.board[-1]
        self.assertEqual(copy.card_id, high.card_id)   # 最高攻 Murloc
        self.assertEqual(copy.atk, get_db().get("BG34_145").atk)
        self.assertEqual(copy.max_health,
                         get_db().get("BG34_145").health)
        # 战斗副本模型: 手牌原件全部保留
        self.assertIn(low, a.hand)
        self.assertIn(high, a.hand)
        self.assertIn(beast, a.hand)

    def test_amalgam_in_hand_counts_as_murloc(self):
        game = make_game(seed=215)
        a, b = game.heroes
        put(game, "BG27_556", a)
        murloc = hand_minion(game, a, "BG34_145")   # 7
        amalgam = hand_minion(game, a, "BG34_320")  # ALL 15/15
        soc(game, a, b)
        self.assertEqual(a.board[-1].card_id, amalgam.card_id)
        self.assertIn(murloc, a.hand)

    def test_soc_no_murloc_in_hand_fizzles(self):
        game = make_game(seed=216)
        a, b = game.heroes
        put(game, "BG27_556", a)
        hand_minion(game, a, "BG34_322")            # 仅野兽
        soc(game, a, b)
        self.assertEqual(len(a.board), 1)

    def test_soc_full_board_does_not_summon(self):
        game = make_game(seed=217)
        a, b = game.heroes
        put(game, "BG27_556", a, position=0)
        for i in range(BOARD_SIZE - 1):
            game.summon(a, make_minion(f"F{i}", 1, 1))
        self.assertTrue(a.board_full())
        high = hand_minion(game, a, "BG34_145")
        soc(game, a, b)
        self.assertEqual(len(a.board), BOARD_SIZE)
        self.assertNotIn(high, a.board)
        self.assertIn(high, a.hand)

    def test_full_board_defers_until_space_mid_combat(self):
        """Evidence: "when you have space" = 战斗内腾位延迟（30.2/33.6
        官方同款句式 + r/BobsTavern Boon of Beetles 实测）——满板 SoC
        不召，友方战死后 AFTER_ATTACK 检查点补召。"""
        game = make_game(seed=220)
        a, b = game.heroes
        put(game, "BG27_556", a, position=0)
        for i in range(BOARD_SIZE - 1):
            game.summon(a, make_minion(f"F{i}", 1, 1))
        high = hand_minion(game, a, "BG34_145")    # Murloc 7/13
        soc(game, a, b)
        self.assertEqual(len(a.board), BOARD_SIZE)  # SoC: 满板不召
        enemy = make_minion("E", 10, 10)
        game.summon(b, enemy)
        victim = a.board[1]
        CombatScheduler(game, a, b)._execute_attack(enemy, victim)
        self.assertEqual(len(a.board), BOARD_SIZE)  # 腾位后补召补齐
        self.assertEqual(a.board[-1].card_id, high.card_id)   # 副本
        self.assertIsNot(a.board[-1], high)          # 手牌原件保留
        self.assertIn(high, a.hand)

    def test_copy_vanishes_after_combat(self):
        game = make_game(seed=218)
        a, b = game.heroes
        forager = put(game, "BG27_556", a)
        high = hand_minion(game, a, "BG34_145")
        game.run_combat(a, b)
        self.assertEqual([m.card_id for m in a.board],
                         [get_db().get("BG27_556").id])   # 副本战后消失
        self.assertIn(high, a.hand)

    def test_golden_summons_two_highest(self):
        game = make_game(seed=219)
        a, b = game.heroes
        put(game, "BG27_556", a, golden=True)
        hand_minion(game, a, "BG33_140")    # Murloc 1
        hand_minion(game, a, "BG26_137")    # Murloc 6
        hand_minion(game, a, "BG34_145")    # Murloc 7
        hand_minion(game, a, "BG34_322")    # Beast 16（不计）
        soc(game, a, b)
        self.assertEqual(len(a.board), 3)
        summoned = {m.card_id for m in a.board} - {"BG27_556_G"}
        self.assertEqual(summoned, {"BG34_145", "BG26_137"})


class TestStitchedSalvager(unittest.TestCase):
    """BG31_999 — SoC: Destroy the minion to the left. Deathrattle:
    Summon an exact copy of it. (Except Stitched Salvager.)"""

    def test_soc_destroys_left_minion(self):
        game = make_game(seed=220)
        a, b = game.heroes
        victim = put(game, "BG33_140", a)         # 左
        victim.add_buff(BuffEnchant(atk=2, health=3))
        salvager = put(game, "BG31_999", a)       # 右
        soc(game, a, b)
        self.assertTrue(victim.dead)
        self.assertNotIn(victim, a.board)
        self.assertEqual([m.card_id for m in a.board], ["BG31_999"])

    def test_deathrattle_summons_exact_copy_with_buffs(self):
        game = make_game(seed=221)
        a, b = game.heroes
        vd = get_db().get("BG33_140")
        victim = put(game, "BG33_140", a)
        victim.add_buff(BuffEnchant(atk=2, health=3))
        salvager = put(game, "BG31_999", a)
        soc(game, a, b)
        salvager.health = 0
        game.check_deaths()
        self.assertEqual(len(a.board), 1)
        copy = a.board[0]
        self.assertEqual(copy.card_id, "BG33_140")
        # exact copy: 含 buff（HEALTH 重算为 max_health，game.summon 保证）
        self.assertEqual(copy.atk, vd.atk + 2)
        self.assertEqual(copy.max_health, vd.health + 3)
        self.assertEqual(copy.health, vd.health + 3)

    def test_deathrattle_summons_golden_copy_of_golden_victim(self):
        game = make_game(seed=222)
        a, b = game.heroes
        victim = put(game, "BG33_140", a, golden=True)
        salvager = put(game, "BG31_999", a)
        soc(game, a, b)
        salvager.health = 0
        game.check_deaths()
        self.assertEqual(len(a.board), 1)
        copy = a.board[0]
        self.assertEqual(copy.card_id, "BG33_140_G")
        self.assertTrue(copy.is_golden)
        self.assertEqual(copy.atk, get_db().get("BG33_140_G").atk)

    def test_soc_at_left_edge_fizzles(self):
        game = make_game(seed=223)
        a, b = game.heroes
        salvager = put(game, "BG31_999", a)       # pos 0 无左邻
        soc(game, a, b)
        self.assertEqual(len(a.board), 1)
        salvager.health = 0
        game.check_deaths()
        self.assertEqual(a.board, [])             # 无记录 → 无副本

    def test_destroyed_minions_deathrattle_triggers(self):
        game = make_game(seed=224)
        a, b = game.heroes
        # Highkeeper Ra 亡语: Get a random Tier 6 minion（进手牌）
        victim = put(game, "BG34_319", a)
        salvager = put(game, "BG31_999", a)
        soc(game, a, b)
        self.assertEqual(len(a.hand), 1)           # 左邻亡语照常触发
        self.assertEqual(a.hand[0].tech_level, 6)

    def test_no_copy_of_stitched_salvager(self):
        game = make_game(seed=225)
        a, b = game.heroes
        salv1 = put(game, "BG31_999", a)          # pos 0: 无左邻
        salv2 = put(game, "BG31_999", a)          # pos 1: 摧毁 salv1
        soc(game, a, b)
        self.assertTrue(salv1.dead)
        self.assertEqual([m.card_id for m in a.board], ["BG31_999"])
        salv2.health = 0
        game.check_deaths()
        # "(Except Stitched Salvager.)": 被毁的 Salvager 不被复制
        self.assertEqual(a.board, [])

    def test_golden_destroys_both_adjacent_and_copies_both(self):
        game = make_game(seed=226)
        a, b = game.heroes
        ld = get_db().get("BG33_140")
        rd = get_db().get("BG26_137")
        left = put(game, "BG33_140", a)
        left.add_buff(BuffEnchant(atk=1, health=1))
        salvager = put(game, "BG31_999", a, golden=True)
        right = put(game, "BG26_137", a)
        soc(game, a, b)
        self.assertTrue(left.dead)
        self.assertTrue(right.dead)
        self.assertEqual([m.card_id for m in a.board], ["BG31_999_G"])
        salvager.health = 0
        game.check_deaths()
        cards = sorted(m.card_id for m in a.board)
        self.assertEqual(cards, ["BG26_137", "BG33_140"])
        for m in a.board:
            if m.card_id == "BG33_140":
                self.assertEqual(m.atk, ld.atk + 1)
            else:
                self.assertEqual(m.atk, rd.atk)


class TestFlightyScoutDeferral(unittest.TestCase):
    """BG32_330 — 已解冻（2026-08-21，combat.py 3b 手牌 SoC 钩子）:
    实现移册 batch_consume.py（hand_soc 协议），本表仅锁定注册转移。"""

    def test_not_registered_deferred_contract(self):
        self.assertIn("BG32_330", REGISTRY)
        self.assertIn("BG32_330_G", REGISTRY)
        self.assertIsNotNone(get_db().get("BG32_330"))   # 卡定义存在


class TestFireForgedEvoker(unittest.TestCase):
    """BG32_822 — SoC: Give your Dragons +{0}/+{1}. Improves permanently
    after you cast a Tavern spell."""

    def test_soc_buffs_dragons_including_self(self):
        game = make_game(seed=227)
        a, b = game.heroes
        d = get_db().get("BG32_822")
        evoker = put(game, "BG32_822", a)
        dragon = make_minion("Dragon", 1, 5, race=Race.DRAGON)
        game.summon(a, dragon)
        mech = make_minion("Mech", 2, 2, race=Race.MECH)
        game.summon(a, mech)
        soc(game, a, b)
        self.assertEqual(evoker.atk, d.atk + d.num(0))       # 自身是龙
        self.assertEqual(evoker.max_health, d.health + d.num(1))
        self.assertEqual(dragon.atk, 1 + d.num(0))
        self.assertEqual(dragon.max_health, 5 + d.num(1))
        self.assertEqual(mech.atk, 2)

    def test_improves_after_casting_tavern_spell(self):
        game = make_game(seed=228)
        a, b = game.heroes
        d = get_db().get("BG32_822")
        evoker = put(game, "BG32_822", a)
        spell = game.create_spell("BG28_805", controller=a)  # 惰性载体
        a.add_to_hand(spell)
        self.assertTrue(game.play_spell(a, spell))   # 酒馆法术施放 1 次
        soc(game, a, b)
        self.assertEqual(evoker.atk, d.atk + d.num(0) * 2)   # M=2
        self.assertEqual(evoker.max_health, d.health + d.num(1) * 2)

    def test_improve_counter_persists_across_combat(self):
        game = make_game(seed=229)
        a, b = game.heroes
        d = get_db().get("BG32_822")
        evoker = put(game, "BG32_822", a)
        spell = game.create_spell("BG28_805", controller=a)  # 惰性载体
        a.add_to_hand(spell)
        game.play_spell(a, spell)
        game.run_combat(a, b)                          # buff 回滚
        self.assertEqual(evoker.atk, d.atk)            # SoC 增益仅本场
        soc(game, a, b)                                # 计数跨战斗保留
        self.assertEqual(evoker.atk, d.atk + d.num(0) * 2)

    def test_spellcast_while_not_in_play_does_not_improve(self):
        game = make_game(seed=230)
        a, b = game.heroes
        d = get_db().get("BG32_822")
        spell = game.create_spell(SHINY_RING_ID, controller=a)
        a.add_to_hand(spell)
        game.play_spell(a, spell)                      # Evoker 未入场
        evoker = put(game, "BG32_822", a)
        soc(game, a, b)
        self.assertEqual(evoker.atk, d.atk + d.num(0))

    def test_golden_uses_golden_values(self):
        game = make_game(seed=231)
        a, b = game.heroes
        dg = get_db().get("BG32_822_G")
        evoker = put(game, "BG32_822", a, golden=True)
        dragon = make_minion("Dragon", 1, 5, race=Race.DRAGON)
        game.summon(a, dragon)
        soc(game, a, b)
        self.assertEqual(evoker.atk, dg.atk + dg.num(0))
        self.assertEqual(dragon.max_health, 5 + dg.num(1))


class TestCostumeEnthusiast(unittest.TestCase):
    """BG34_142 — Divine Shield. SoC: Gain the Attack of the
    highest-Attack minion in your hand."""

    def test_soc_gains_highest_hand_atk(self):
        game = make_game(seed=232)
        a, b = game.heroes
        d = get_db().get("BG34_142")
        hand_minion(game, a, "BG33_323")   # atk 2
        hand_minion(game, a, "BG27_017")   # atk 7
        enthusiast = put(game, "BG34_142", a)
        soc(game, a, b)
        self.assertEqual(enthusiast.atk, d.atk + 7)
        self.assertEqual(enthusiast.max_health, d.health)   # 仅攻击
        self.assertTrue(enthusiast.has(GameTag.DIVINE_SHIELD))

    def test_spell_in_hand_ignored(self):
        game = make_game(seed=233)
        a, b = game.heroes
        d = get_db().get("BG34_142")
        spell = game.create_spell(SHINY_RING_ID, controller=a)
        a.add_to_hand(spell)
        enthusiast = put(game, "BG34_142", a)
        soc(game, a, b)
        self.assertEqual(enthusiast.atk, d.atk)

    def test_golden_gains_double(self):
        game = make_game(seed=234)
        a, b = game.heroes
        dg = get_db().get("BG34_142_G")
        hand_minion(game, a, "BG27_017")   # atk 7
        enthusiast = put(game, "BG34_142", a, golden=True)
        soc(game, a, b)
        self.assertEqual(enthusiast.atk, dg.atk + 14)

    def test_buff_rolls_back_after_combat(self):
        game = make_game(seed=235)
        a, b = game.heroes
        d = get_db().get("BG34_142")
        hand_minion(game, a, "BG27_017")
        enthusiast = put(game, "BG34_142", a)
        game.run_combat(a, b)
        self.assertEqual(enthusiast.atk, d.atk)


class TestRunicArcanist(unittest.TestCase):
    """BG36_245 — SoC: Cast Shiny Ring twice."""

    def test_soc_casts_shiny_ring_twice(self):
        game = make_game(seed=236)
        a, b = game.heroes
        d = get_db().get("BG36_245")
        ring = get_db().get(SHINY_RING_ID)
        arcanist = put(game, "BG36_245", a)
        m1 = make_minion("M1", 3, 3)
        m2 = make_minion("M2", 4, 4, race=Race.BEAST)
        game.summon(a, m1)
        game.summon(a, m2)
        soc(game, a, b)
        # "your minions"（含自身）各 +2×num
        self.assertEqual(arcanist.atk, d.atk + 2 * ring.num(0))
        self.assertEqual(arcanist.max_health, d.health + 2 * ring.num(1))
        self.assertEqual(m1.atk, 3 + 2 * ring.num(0))
        self.assertEqual(m2.max_health, 4 + 2 * ring.num(1))

    def test_cast_does_not_count_as_player_tavern_spell(self):
        game = make_game(seed=237)
        a, b = game.heroes
        put(game, "BG36_245", a)
        soc(game, a, b)
        self.assertEqual(
            a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), 0)
        self.assertEqual(
            a.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0), 0)

    def test_golden_casts_four_times(self):
        game = make_game(seed=238)
        a, b = game.heroes
        dg = get_db().get("BG36_245_G")
        ring = get_db().get(SHINY_RING_ID)
        arcanist = put(game, "BG36_245", a, golden=True)
        soc(game, a, b)
        self.assertEqual(arcanist.atk, dg.atk + 4 * ring.num(0))
        self.assertEqual(arcanist.max_health, dg.health + 4 * ring.num(1))

    def test_buff_rolls_back_after_combat(self):
        game = make_game(seed=239)
        a, b = game.heroes
        d = get_db().get("BG36_245")
        arcanist = put(game, "BG36_245", a)
        game.run_combat(a, b)
        self.assertEqual(arcanist.atk, d.atk)
        self.assertEqual(arcanist.max_health, d.health)


class TestBoomInABoxDeferral(unittest.TestCase):
    """BG36_620 — 已解冻（2026-08-21，game._active_combat 战斗对暴露）:
    实现移册 batch_consume.py，本表仅锁定注册转移。"""

    def test_not_registered_deferred_contract(self):
        self.assertIn("BG36_620", REGISTRY)
        self.assertIn("BG36_620_G", REGISTRY)
        self.assertIsNotNone(get_db().get("BG36_620"))   # 卡定义存在


class TestSocBatchRegistry(unittest.TestCase):
    """注册表健康度: 8 张 OK 卡 + 金色链完整 + bind_all 通过。"""

    IMPLEMENTED = [
        "BG24_500", "BG26_354", "BG26_805", "BG27_556", "BG31_999",
        "BG32_822", "BG34_142", "BG36_245",
    ]

    def test_registered_ids_exist_with_golden_chain(self):
        db = get_db()
        for cid in self.IMPLEMENTED:
            d = db.get(cid)
            self.assertIsNotNone(d, f"MISSING_DEF: {cid}")
            self.assertIn(cid, REGISTRY, f"MISSING_SCRIPT: {cid}")
            golden = db.golden_version(d)
            self.assertIsNotNone(golden, f"MISSING_GOLDEN: {cid}")
            self.assertIn(golden.id, REGISTRY,
                          f"MISSING_GOLDEN_SCRIPT: {cid}")
        self.assertGreaterEqual(bind_all(db), 2 * len(self.IMPLEMENTED))


if __name__ == "__main__":
    unittest.main()
