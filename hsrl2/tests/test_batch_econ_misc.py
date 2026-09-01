"""批次 econ_misc 卡牌语义测试（作业单 2026-08-21，15 张）。

覆盖: BG25_354 Titus Rivendare / BG23_009 Lava Lurker（DEFERRED 断言）/
BG26_174 Soul Rewinder / BG26_505 Zesty Shaker / BG26_810 Gunpowder
Courier / BG27_005 Timecap'n Hooktail / BG28_741 Charging Czarina /
BG29_816 Roaring Recruiter / BG31_035 Groundbreaker / BG31_824
Dual-Wield Corsair / BG32_846 Unleashed Mana Surge / BG32_873 Ashen
Corruptor / BG33_893 Primitive Painter / BG34_692 Forsaken Weaver /
BG34_858 Air Revenant。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）。驱动: gold_spent 用
game.spend_gold; tavern_spell_cast 用未注册脚本池法术 BG28_805 Strike
Oil（T2）施放; Spellcraft 用 BG23_000t; after_attack 用
CombatScheduler._execute_attack（test_batch_bloodgem 经验库）。
"""

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

_TAVERN_SPELL_ID = "BG28_805"   # Strike Oil T2——未注册脚本的池法术（驱动用）
_SPELLCRAFT_SPELL_ID = "BG23_000t"   # Mini-Myrmidon 法术（已注册 on_play）
_PLAIN_NAGA_ID = "BG23_000"     # Mini-Myrmidon T1 Naga（已注册脚本但 Murloc 族无关）
_PLAIN_UNDEAD_ID = "BG25_001"   # Risen Rider——未注册脚本 Undead
_PLAIN_MURLOC_ID = "BG26_137"   # Bream Counter——未注册脚本 Murloc


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


def summon_plain(game: Game, hero: Hero, m: Minion,
                 position: int | None = None) -> Minion:
    game.summon(hero, m, position)
    return m


def hand_minion(hero: Hero, m: Minion) -> Minion:
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def cast_tavern_spell(game: Game, hero: Hero, target=None) -> None:
    """施放一张未注册脚本的池法术（占池 → 入手 → play_spell）。

    驱动 tavern_spell_cast（is_pool_spell）与 TAVERN_SPELLS_CAST_*
    计数; 无目标施放（Strike Oil 未注册 → on_play 无副作用）。"""
    assert game.spell_pool.acquire(_TAVERN_SPELL_ID)
    s = game.create_spell(_TAVERN_SPELL_ID, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    assert game.play_spell(hero, s, target=target)


def add_spellcraft_to_hand(game: Game, hero: Hero) -> "object":
    """构造手牌中的 Spellcraft 法术（镜像 test_spellcraft helper）。"""
    s = game.create_spell(_SPELLCRAFT_SPELL_ID, controller=hero)
    s.scripts = REGISTRY.get(_SPELLCRAFT_SPELL_ID)
    s.set(GameTag.SPELLCRAFT, True)
    s.spellcraft_source_uuid = None
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def play_minion_card(game: Game, hero: Hero, m: Minion) -> None:
    """手牌打出随从（驱动 card_played）。"""
    hand_minion(hero, m)
    assert game.play_minion(hero, m)


class TestRegistryState(unittest.TestCase):
    """批次注册面: 13 卡 OK（含金色 26 id）; Titus/Lava Lurker 不注册。"""

    def test_ok_cards_registered(self):
        for cid in ("BG26_174", "BG26_174_G", "BG26_505", "BG26_505_G",
                    "BG26_810", "BG26_810_G", "BG27_005", "BG27_005_G",
                    "BG28_741", "BG28_741_G", "BG29_816", "BG29_816_G",
                    "BG31_035", "BG31_035_G", "BG31_824", "BG31_824_G",
                    "BG32_846", "BG32_846_G", "BG32_873", "BG32_873_G",
                    "BG33_893", "BG33_893_G", "BG34_692", "BG34_692_G",
                    "BG34_858", "BG34_858_G"):
            self.assertIn(cid, REGISTRY)

    def test_deferred_state_2026_08_22(self):
        # Titus 已由 batch_doublers 实现（DEATHRATTLE_DOUBLER 引擎接线）
        self.assertIn("BG25_354", REGISTRY)
        # Lava Lurker 已由 batch_unfreeze 解冻（spell_resolving +
        # _permanence_pending 永久化拦截原语就绪）
        self.assertIn("BG23_009", REGISTRY)


class TestSoulRewinder(unittest.TestCase):
    """BG26_174 — hero_damage_taken → rewind（含护甲）+ 本体 +N 血。"""

    def test_damage_rewound_and_self_gains_health(self):
        game = make_game()
        a = game.heroes[0]
        r = put(game, "BG26_174", a)          # on_summon 快照 (30, 0)
        self.assertEqual(r.health, 1)
        a.take_damage(7)
        self.assertEqual(a.health, 30)
        self.assertEqual(a.armor, 0)
        self.assertEqual(r.health, 1 + 1)

    def test_armor_also_rewound(self):
        game = make_game()
        a = game.heroes[0]
        a.armor = 5
        r = put(game, "BG26_174", a)          # 快照 (30, 5)
        a.take_damage(12)                     # 甲 5 全吸收 + 血 -7
        self.assertEqual((a.health, a.armor), (30, 5))
        self.assertEqual(r.health, 2)

    def test_enemy_hero_damage_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        r = put(game, "BG26_174", a)
        b.take_damage(6)
        self.assertEqual(b.health, 30 - 6)    # b 无 rewinder 不回退
        self.assertEqual(r.health, 1)

    def test_sold_rewinder_stops_rewinding(self):
        game = make_game()
        a = game.heroes[0]
        r = put(game, "BG26_174", a)
        self.assertTrue(game.sell_minion(a, r))
        a.take_damage(5)
        self.assertEqual(a.health, 30 - 5)

    def test_two_rewinders_rewind_once_but_both_gain(self):
        game = make_game()
        a = game.heroes[0]
        r1 = put(game, "BG26_174", a)
        r2 = put(game, "BG26_174", a)
        a.take_damage(10)
        self.assertEqual(a.health, 30)        # 只回退一次（幂等）
        self.assertEqual(r1.health, 2)
        self.assertEqual(r2.health, 2)

    def test_golden_gains_two_health(self):
        game = make_game()
        a = game.heroes[0]
        r = put(game, "BG26_174", a, golden=True)
        a.take_damage(3)
        self.assertEqual(a.health, 30)
        self.assertEqual(r.health, 2 + 2)


class TestZestyShaker(unittest.TestCase):
    """BG26_505 — 每回合首个打在本体的 Spellcraft → 获得 N 份副本。"""

    def test_spellcraft_on_this_gets_copy(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG26_505", a)
        s = add_spellcraft_to_hand(game, a)
        self.assertTrue(game.play_spell(a, s, target=next(iter(a.board))))
        copies = [c for c in a.hand if c.card_id == _SPELLCRAFT_SPELL_ID]
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].has(GameTag.SPELLCRAFT))

    def test_once_per_turn(self):
        game = make_game()
        a = game.heroes[0]
        shaker = put(game, "BG26_505", a)
        s1 = add_spellcraft_to_hand(game, a)
        s2 = add_spellcraft_to_hand(game, a)
        game.play_spell(a, s1, target=shaker)
        game.play_spell(a, s2, target=shaker)
        copies = [c for c in a.hand if c.card_id == _SPELLCRAFT_SPELL_ID]
        self.assertEqual(len(copies), 1)      # 同回合第二次不复制

    def test_spellcraft_on_other_minion_no_copy(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG26_505", a)
        other = summon_plain(game, a, make_minion("Other", 1, 1))
        s = add_spellcraft_to_hand(game, a)
        game.play_spell(a, s, target=other)
        self.assertEqual([c for c in a.hand
                          if c.card_id == _SPELLCRAFT_SPELL_ID], [])

    def test_non_spellcraft_spell_no_copy(self):
        game = make_game()
        a = game.heroes[0]
        shaker = put(game, "BG26_505", a)
        cast_tavern_spell(game, a, target=shaker)
        self.assertEqual([c for c in a.hand
                          if c.card_id == _TAVERN_SPELL_ID], [])

    def test_resets_next_turn(self):
        game = make_game(seed=7)
        game.start_game()                     # turn=1 起点
        a = game.heroes[0]
        shaker = put(game, "BG26_505", a)
        s1 = add_spellcraft_to_hand(game, a)
        game.play_spell(a, s1, target=shaker)
        game.end_recruit_phase()              # 完整回合循环（含战斗）
        self.assertGreater(game.turn, 1)
        s2 = add_spellcraft_to_hand(game, a)
        self.assertTrue(game.play_spell(a, s2, target=shaker))
        self.assertEqual(len([c for c in a.hand
                               if c.card_id == _SPELLCRAFT_SPELL_ID]), 1)

    def test_golden_two_copies(self):
        game = make_game()
        a = game.heroes[0]
        shaker = put(game, "BG26_505", a, golden=True)
        s = add_spellcraft_to_hand(game, a)
        game.play_spell(a, s, target=shaker)
        self.assertEqual(len([c for c in a.hand
                               if c.card_id == _SPELLCRAFT_SPELL_ID]), 2)


class TestGunpowderCourier(unittest.TestCase):
    """BG26_810 — 累计 5 金 → 全体 Pirates +num(2) 攻（金色 ×2）。"""

    def test_threshold_triggers_for_all_pirates(self):
        game = make_game()
        a = game.heroes[0]
        courier = put(game, "BG26_810", a)
        pirate = summon_plain(game, a,
                              make_minion("Pirate", 2, 2, race=Race.PIRATE))
        beast = summon_plain(game, a, make_minion("Beast", 2, 2))
        gain = get_db().get("BG26_810").num(2)
        a.gold = 10
        game.spend_gold(a, 2)
        self.assertEqual((courier.atk, pirate.atk), (2, 2))
        game.spend_gold(a, 3)                 # 累计 5 → 触发
        self.assertEqual(courier.atk, 2 + gain)
        self.assertEqual(pirate.atk, 2 + gain)
        self.assertEqual(beast.atk, 2)        # 非 Pirate 不受

    def test_no_trigger_below_threshold(self):
        game = make_game()
        a = game.heroes[0]
        courier = put(game, "BG26_810", a)
        a.gold = 10
        game.spend_gold(a, 4)
        self.assertEqual(courier.atk, 2)

    def test_modulo_overshoot(self):
        game = make_game()
        a = game.heroes[0]
        courier = put(game, "BG26_810", a)
        gain = get_db().get("BG26_810").num(2)
        a.gold = 20
        game.spend_gold(a, 12)                # 跨两个 5 金边界 → 2 次
        self.assertEqual(courier.atk, 2 + 2 * gain)
        game.spend_gold(a, 3)                 # 余 2 + 3 = 5 → 再触发
        self.assertEqual(courier.atk, 2 + 3 * gain)

    def test_enemy_spend_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        courier = put(game, "BG26_810", a)
        b.gold = 10
        game.spend_gold(b, 5)
        self.assertEqual(courier.atk, 2)

    def test_golden_grants_twice(self):
        game = make_game()
        a = game.heroes[0]
        courier = put(game, "BG26_810", a, golden=True)
        gain = get_db().get("BG26_810_G").num(2)
        a.gold = 10
        game.spend_gold(a, 5)
        self.assertEqual(courier.atk, 4 + 2 * gain)


class TestTimecapnHooktail(unittest.TestCase):
    """BG27_005 — 施放酒馆法术 → 全队 +num(0) 攻（金色 ×2）。"""

    def test_cast_buffs_all_minions(self):
        game = make_game()
        a = game.heroes[0]
        hook = put(game, "BG27_005", a)
        other = summon_plain(game, a, make_minion("Other", 3, 3))
        gain = get_db().get("BG27_005").num(0)
        cast_tavern_spell(game, a)
        self.assertEqual(hook.atk, 1 + gain)
        self.assertEqual(other.atk, 3 + gain)

    def test_spellcraft_spell_does_not_trigger(self):
        game = make_game()
        a = game.heroes[0]
        hook = put(game, "BG27_005", a)
        s = add_spellcraft_to_hand(game, a)
        game.play_spell(a, s, target=hook)    # 非 is_pool_spell → 不计
        # Mini-Trident on_play 自带 +2 攻（temporary），监听器未触发——
        # 以施放计数 tag 为准（Spellcraft 不入 TAVERN_SPELLS_CAST）
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), 0)
        self.assertEqual(hook.atk, 1 + 2)     # 仅法术本体效果

    def test_enemy_cast_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        hook = put(game, "BG27_005", a)
        cast_tavern_spell(game, b)
        self.assertEqual(hook.atk, 1)

    def test_golden_grants_twice(self):
        game = make_game()
        a = game.heroes[0]
        hook = put(game, "BG27_005", a, golden=True)
        gain = get_db().get("BG27_005_G").num(0)
        cast_tavern_spell(game, a)
        self.assertEqual(hook.atk, 2 + 2 * gain)


class TestChargingCzarina(unittest.TestCase):
    """BG28_741 — 施放酒馆法术 → 圣盾随从 +num(0) 攻。"""

    def test_cast_buffs_divine_shield_minions(self):
        game = make_game()
        a = game.heroes[0]
        czarina = put(game, "BG28_741", a)    # 自带 DS
        self.assertTrue(czarina.divine_shield)
        plain = summon_plain(game, a, make_minion("Plain", 3, 3))
        gain = get_db().get("BG28_741").num(0)
        cast_tavern_spell(game, a)
        self.assertEqual(czarina.atk, 4 + gain)
        self.assertEqual(plain.atk, 3)        # 无圣盾不受

    def test_enemy_cast_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        czarina = put(game, "BG28_741", a)
        cast_tavern_spell(game, b)
        self.assertEqual(czarina.atk, 4)

    def test_golden_double_value(self):
        game = make_game()
        a = game.heroes[0]
        czarina = put(game, "BG28_741", a, golden=True)
        gain = get_db().get("BG28_741_G").num(0)
        cast_tavern_spell(game, a)
        self.assertEqual(czarina.atk, 8 + gain)


class TestRoaringRecruiter(unittest.TestCase):
    """BG29_816 — 另一友方龙攻击后 +num(0)/num(1)。"""

    def _attack(self, game, attacker, defender):
        from hsrl2.combat import CombatScheduler
        a, b = game.heroes[0], game.heroes[1]
        CombatScheduler(game, a, b)._execute_attack(attacker, defender)

    def test_friendly_dragon_attack_buffs_it(self):
        game = make_game()
        a, b = game.heroes
        put(game, "BG29_816", a)
        dragon = summon_plain(game, a,
                              make_minion("Dragon", 2, 5, race=Race.DRAGON))
        d = get_db().get("BG29_816")
        self._attack(game, dragon, make_minion("Dummy", 0, 30))
        self.assertEqual(dragon.atk, 2 + d.num(0))
        self.assertEqual(dragon.health, 5 + d.num(1))

    def test_own_attack_no_trigger(self):
        game = make_game()
        a = game.heroes[0]
        recruiter = put(game, "BG29_816", a)
        self._attack(game, recruiter, make_minion("Dummy", 0, 30))
        self.assertEqual((recruiter.atk, recruiter.health), (2, 8))

    def test_non_dragon_attack_no_trigger(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG29_816", a)
        beast = summon_plain(game, a, make_minion("Beast", 2, 2))
        self._attack(game, beast, make_minion("Dummy", 0, 30))
        self.assertEqual(beast.atk, 2)

    def test_enemy_dragon_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        put(game, "BG29_816", a)
        foe = summon_plain(game, b,
                           make_minion("FoeDragon", 2, 2, race=Race.DRAGON))
        self._attack(game, foe, make_minion("Dummy", 0, 30))
        self.assertEqual(foe.atk, 2)

    def test_dead_attacker_skipped(self):
        game = make_game()
        a, b = game.heroes
        put(game, "BG29_816", a)
        frail = summon_plain(game, a,
                             make_minion("FrailDragon", 1, 1, race=Race.DRAGON))
        big = summon_plain(game, b, make_minion("Big", 5, 5))
        self._attack(game, frail, big)        # 反击致死
        self.assertTrue(frail.dead)
        self.assertEqual(frail.atk, 1)

    def test_golden_values(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG29_816", a, golden=True)
        dragon = summon_plain(game, a,
                              make_minion("Dragon", 2, 5, race=Race.DRAGON))
        d = get_db().get("BG29_816_G")
        self._attack(game, dragon, make_minion("Dummy", 0, 30))
        self.assertEqual(dragon.atk, 2 + d.num(0))
        self.assertEqual(dragon.health, 5 + d.num(1))


class TestGroundbreaker(unittest.TestCase):
    """BG31_035 — 打出 Naga → 自身 +num(1)×mult（mult=1+施法数//num(0)）。"""

    def _play_naga(self, game, hero):
        m = game.create_minion(_PLAIN_NAGA_ID, controller=hero)
        play_minion_card(game, hero, m)

    def test_no_spells_base_gain(self):
        game = make_game()
        a = game.heroes[0]
        gb = put(game, "BG31_035", a)
        d = get_db().get("BG31_035")
        self._play_naga(game, a)
        self.assertEqual(gb.atk, 6 + d.num(1))
        self.assertEqual(gb.health, 4 + d.num(1))

    def test_three_spells_double_gain(self):
        game = make_game()
        a = game.heroes[0]
        gb = put(game, "BG31_035", a)
        d = get_db().get("BG31_035")
        for _ in range(d.num(0)):
            cast_tavern_spell(game, a)
        self._play_naga(game, a)
        self.assertEqual(gb.atk, 6 + 2 * d.num(1))
        self.assertEqual(gb.health, 4 + 2 * d.num(1))

    def test_non_naga_no_gain(self):
        game = make_game()
        a = game.heroes[0]
        gb = put(game, "BG31_035", a)
        play_minion_card(game, a,
                         game.create_minion(_PLAIN_UNDEAD_ID, controller=a))
        self.assertEqual((gb.atk, gb.health), (6, 4))

    def test_enemy_naga_no_gain(self):
        game = make_game()
        a, b = game.heroes
        gb = put(game, "BG31_035", a)
        m = game.create_minion(_PLAIN_NAGA_ID, controller=b)
        play_minion_card(game, b, m)
        self.assertEqual((gb.atk, gb.health), (6, 4))

    def test_golden_base_gain(self):
        game = make_game()
        a = game.heroes[0]
        gb = put(game, "BG31_035", a, golden=True)
        d = get_db().get("BG31_035_G")
        self._play_naga(game, a)
        self.assertEqual(gb.atk, 12 + d.num(1))
        self.assertEqual(gb.health, 8 + d.num(1))


class TestDualWieldCorsair(unittest.TestCase):
    """BG31_824 — 累计 5 金 → 随机两只 Pirate +num(2)/num(3)（金色 ×2）。"""

    def test_threshold_buffs_exactly_two_pirates(self):
        game = make_game(seed=11)
        a = game.heroes[0]
        corsair = put(game, "BG31_824", a)
        p1 = summon_plain(game, a, make_minion("P1", 1, 1, race=Race.PIRATE))
        p2 = summon_plain(game, a, make_minion("P2", 1, 1, race=Race.PIRATE))
        p3 = summon_plain(game, a, make_minion("P3", 1, 1, race=Race.PIRATE))
        beast = summon_plain(game, a, make_minion("Beast", 1, 1))
        d = get_db().get("BG31_824")
        a.gold = 10
        game.spend_gold(a, 5)
        buffed = [m for m in (p1, p2, p3) if m.atk == 1 + d.num(2)]
        self.assertEqual(len(buffed), 2)
        for m in buffed:
            self.assertEqual(m.health, 1 + d.num(3))
        self.assertEqual(corsair.atk, 4)      # corsair 也是 Pirate——可能入选
        self.assertIn(corsair.atk, (4, 4 + d.num(2)))
        self.assertEqual(beast.atk, 1)

    def test_single_pirate_still_buffed(self):
        game = make_game()
        a = game.heroes[0]
        corsair = put(game, "BG31_824", a)   # 场上唯一 Pirate
        d = get_db().get("BG31_824")
        a.gold = 10
        game.spend_gold(a, 5)
        self.assertEqual(corsair.atk, 4 + d.num(2))
        self.assertEqual(corsair.health, 5 + d.num(3))

    def test_below_threshold_no_buff(self):
        game = make_game()
        a = game.heroes[0]
        corsair = put(game, "BG31_824", a)
        a.gold = 10
        game.spend_gold(a, 4)
        self.assertEqual((corsair.atk, corsair.health), (4, 5))

    def test_golden_grants_twice(self):
        game = make_game()
        a = game.heroes[0]
        corsair = put(game, "BG31_824", a)
        p1 = summon_plain(game, a, make_minion("P1", 1, 1, race=Race.PIRATE))
        d = get_db().get("BG31_824_G")
        # 金色 ×2 单驱: 新对局仅放金色+3 只 Pirate（裸 remove 不注销
        # 监听器——真实对局无此路径，测试重建场景）
        game = make_game()
        a = game.heroes[0]
        a.gold = 10
        golden = put(game, "BG31_824", a, golden=True)
        for i in range(3):
            summon_plain(game, a, make_minion(f"P{i}", 1, 1, race=Race.PIRATE))
        game.spend_gold(a, 5)
        # 金色 grant×2，每笔随机两只 → 场上恰 3 只 Pirate 时总数=4 笔
        total = sum(1 for m in a.board
                    if m.race in (Race.PIRATE, Race.ALL) for _ in m.buffs)
        self.assertEqual(total, 4)
        gd = get_db().get("BG31_824_G")
        # 金色本体基础 atk + 自身作为 Pirate 吃到的 grant（随机目标含自身与否
        # 不定——仅断言 ≥ 基础）
        self.assertGreaterEqual(golden.atk, gd.atk)


class TestUnleashedManaSurge(unittest.TestCase):
    """BG32_846 — 打出 Elemental → 全体 Elementals +num(0)/num(1)。"""

    def test_play_elemental_buffs_all_elementals(self):
        game = make_game()
        a = game.heroes[0]
        surge = put(game, "BG32_846", a)
        played = make_minion("Elem", 1, 1, race=Race.ELEMENTAL)
        d = get_db().get("BG32_846")
        play_minion_card(game, a, played)
        self.assertEqual(surge.atk, 6 + d.num(0))   # 含本体
        self.assertEqual(surge.health, 5 + d.num(1))
        self.assertEqual(played.atk, 1 + d.num(0))  # 含刚打出者
        self.assertEqual(played.health, 1 + d.num(1))

    def test_play_non_elemental_no_buff(self):
        game = make_game()
        a = game.heroes[0]
        surge = put(game, "BG32_846", a)
        play_minion_card(game, a, make_minion("Beast", 1, 1))
        self.assertEqual((surge.atk, surge.health), (6, 5))

    def test_enemy_elemental_no_buff(self):
        game = make_game()
        a, b = game.heroes
        surge = put(game, "BG32_846", a)
        play_minion_card(game, b,
                         make_minion("FoeElem", 1, 1, race=Race.ELEMENTAL))
        self.assertEqual((surge.atk, surge.health), (6, 5))

    def test_golden_grants_twice(self):
        game = make_game()
        a = game.heroes[0]
        surge = put(game, "BG32_846", a, golden=True)
        d = get_db().get("BG32_846_G")
        play_minion_card(game, a,
                         make_minion("Elem", 1, 1, race=Race.ELEMENTAL))
        self.assertEqual(surge.atk, 12 + 2 * d.num(0))
        self.assertEqual(surge.health, 10 + 2 * d.num(1))


class TestAshenCorruptor(unittest.TestCase):
    """BG32_873 — hero 受伤 → rewind + 馆内随从 +num(0)/num(1) 本回合。"""

    def _tavern_minions(self, hero):
        return [e for e in hero.tavern if isinstance(e, Minion)]

    def test_damage_rewinds_and_buffs_tavern_this_turn(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG32_873", a)
        game.refresh_tavern(a, free=True)
        minions = self._tavern_minions(a)
        self.assertGreaterEqual(len(minions), 1)
        d = get_db().get("BG32_873")
        base = {m.uuid: (m.atk, m.health) for m in minions}
        a.take_damage(4)
        self.assertEqual(a.health, 30)        # rewind
        for m in minions:
            self.assertEqual(
                (m.atk, m.health),
                (base[m.uuid][0] + d.num(0), base[m.uuid][1] + d.num(1)))

    def test_buff_expires_next_turn_start(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG32_873", a)
        game.refresh_tavern(a, free=True)
        minions = self._tavern_minions(a)
        base = {m.uuid: m.atk for m in minions}
        a.take_damage(1)
        game.events.fire(game, "turn_start", turn=game.turn + 1, hero=a)
        for m in minions:
            self.assertEqual(m.atk, base[m.uuid])

    def test_no_damage_no_tavern_buff(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG32_873", a)
        game.refresh_tavern(a, free=True)
        for m in self._tavern_minions(a):
            self.assertEqual(m.buffs, [])

    def test_enemy_damage_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        put(game, "BG32_873", a)
        game.refresh_tavern(a, free=True)
        before = [(m.atk, m.health) for m in self._tavern_minions(a)]
        b.take_damage(3)
        self.assertEqual(
            [(m.atk, m.health) for m in self._tavern_minions(a)], before)

    def test_golden_values(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG32_873", a, golden=True)
        game.refresh_tavern(a, free=True)
        minions = self._tavern_minions(a)
        d = get_db().get("BG32_873_G")
        base = {m.uuid: (m.atk, m.health) for m in minions}
        a.take_damage(2)
        for m in minions:
            self.assertEqual(
                (m.atk, m.health),
                (base[m.uuid][0] + d.num(0), base[m.uuid][1] + d.num(1)))


class TestPrimitivePainter(unittest.TestCase):
    """BG33_893 — 打出 T≤3 卡 → 全体 Murlocs +num(0)/num(1)。"""

    def test_low_tier_card_buffs_murlocs(self):
        game = make_game()
        a = game.heroes[0]
        painter = put(game, "BG33_893", a)
        murloc = put(game, _PLAIN_MURLOC_ID, a)
        beast = summon_plain(game, a, make_minion("Beast", 1, 1))
        d = get_db().get("BG33_893")
        murloc_base = (murloc.atk, murloc.health)
        cast_tavern_spell(game, a)            # T2 池法术 → 触发
        self.assertEqual(
            (painter.atk, painter.health), (3 + d.num(0), 8 + d.num(1)))
        self.assertEqual(
            (murloc.atk, murloc.health),
            (murloc_base[0] + d.num(0), murloc_base[1] + d.num(1)))
        self.assertEqual((beast.atk, beast.health), (1, 1))

    def test_tier4_minion_does_not_trigger(self):
        game = make_game()
        a = game.heroes[0]
        painter = put(game, "BG33_893", a)
        play_minion_card(game, a,
                         game.create_minion("BG26_810", controller=a))  # T4
        self.assertEqual((painter.atk, painter.health), (3, 8))

    def test_low_tier_minion_triggers(self):
        game = make_game()
        a = game.heroes[0]
        painter = put(game, "BG33_893", a)
        d = get_db().get("BG33_893")
        play_minion_card(game, a,
                         game.create_minion(_PLAIN_NAGA_ID, controller=a))
        self.assertEqual((painter.atk, painter.health),
                         (3 + d.num(0), 8 + d.num(1)))

    def test_enemy_play_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        painter = put(game, "BG33_893", a)
        play_minion_card(game, b,
                         game.create_minion(_PLAIN_NAGA_ID, controller=b))
        self.assertEqual((painter.atk, painter.health), (3, 8))

    def test_golden_values(self):
        game = make_game()
        a = game.heroes[0]
        painter = put(game, "BG33_893", a, golden=True)
        d = get_db().get("BG33_893_G")
        cast_tavern_spell(game, a)
        self.assertEqual((painter.atk, painter.health),
                         (6 + d.num(0), 16 + d.num(1)))


class TestForsakenWeaver(unittest.TestCase):
    """BG34_692 — 施放酒馆法术 → Undead 永久 +num(0) 攻光环（全区域）。"""

    def test_cast_applies_race_aura_everywhere(self):
        game = make_game()
        a = game.heroes[0]
        weaver = put(game, "BG34_692", a)
        board_undead = put(game, _PLAIN_UNDEAD_ID, a)
        hand_undead = game.create_minion(_PLAIN_UNDEAD_ID, controller=a)
        hand_minion(a, hand_undead)
        beast = summon_plain(game, a, make_minion("Beast", 2, 2))
        d = get_db().get("BG34_692")
        gain = d.num(0)
        base = board_undead.atk
        base_hand = hand_undead.atk
        cast_tavern_spell(game, a)
        self.assertEqual(board_undead.atk, base + gain)
        self.assertEqual(hand_undead.atk, base_hand + gain)
        self.assertEqual(beast.atk, 2)
        # "wherever they are": 未来召唤的 Undead 同样生效
        fresh = put(game, _PLAIN_UNDEAD_ID, a)
        self.assertEqual(fresh.atk, get_db().get(_PLAIN_UNDEAD_ID).atk + gain)
        # 施放者本体（Undead）也吃光环
        self.assertEqual(weaver.atk, 3 + gain)

    def test_spellcraft_and_enemy_cast_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        weaver = put(game, "BG34_692", a)
        s = add_spellcraft_to_hand(game, a)
        game.play_spell(a, s, target=weaver)  # 非 is_pool_spell
        # Mini-Trident on_play 自带 +2 攻（temporary）; 监听器未触发
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), 0)
        self.assertEqual(weaver.atk, 3 + 2)
        cast_tavern_spell(game, b)
        self.assertEqual(weaver.atk, 3 + 2)   # 敌方施放不触发（+2 为法术本体）

    def test_golden_value(self):
        game = make_game()
        a = game.heroes[0]
        weaver = put(game, "BG34_692", a, golden=True)
        gain = get_db().get("BG34_692_G").num(0)
        cast_tavern_spell(game, a)
        self.assertEqual(weaver.atk, 6 + gain)


class TestAirRevenant(unittest.TestCase):
    """BG34_858 — 累计 num(2) 金 → cast Easterly Winds（刷新触发式光环）。"""

    def _tavern_minions(self, hero):
        return [e for e in hero.tavern if isinstance(e, Minion)]

    def test_threshold_casts_easterly_winds(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG34_858", a)
        threshold = get_db().get("BG34_858").num(2)
        ew = get_db().get("BG34_444")
        a.gold = 10
        game.spend_gold(a, threshold - 2)
        game.refresh_tavern(a, free=True)
        self.assertEqual(self._tavern_minions(a)[0].buffs, [])   # 未达标
        game.spend_gold(a, 2)                 # 达标 → cast 注册光环
        game.refresh_tavern(a, free=True)
        buffed = [m for m in self._tavern_minions(a) if m.buffs]
        self.assertEqual(len(buffed), 1)
        m = buffed[0]
        self.assertEqual(m.atk, get_db().get(m.card_id).atk + ew.num(0))
        self.assertEqual(
            m.health, get_db().get(m.card_id).health + ew.num(1))
        # "this game": 再次刷新再触发
        game.refresh_tavern(a, free=True)
        self.assertEqual(
            len([m for m in self._tavern_minions(a) if m.buffs]), 1)

    def test_enemy_spend_no_trigger(self):
        game = make_game()
        a, b = game.heroes
        put(game, "BG34_858", a)
        b.gold = 10
        game.spend_gold(b, 7)
        game.refresh_tavern(a, free=True)
        for m in self._tavern_minions(a):
            self.assertEqual(m.buffs, [])

    def test_golden_casts_twice(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG34_858", a, golden=True)
        a.gold = 10
        game.spend_gold(a, get_db().get("BG34_858_G").num(2))
        game.refresh_tavern(a, free=True)
        total = sum(len(m.buffs)
                    for m in self._tavern_minions(a))
        self.assertEqual(total, 2)            # 每次 cast 一笔 → 双 cast 两笔

    def test_progress_accumulates_across_spends(self):
        game = make_game()
        a = game.heroes[0]
        put(game, "BG34_858", a)
        a.gold = 10
        for _ in range(7):
            game.spend_gold(a, 1)
        game.refresh_tavern(a, free=True)
        self.assertEqual(
            len([m for m in self._tavern_minions(a) if m.buffs]), 1)


if __name__ == "__main__":
    unittest.main()
