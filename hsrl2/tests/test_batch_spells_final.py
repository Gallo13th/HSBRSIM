"""批次 spells_final 池法术语义测试（作业单 2026-08-22，21 张）。

覆盖: BG33_817 Sanctify / BG33_899 Mounting Avalanche / BG34_272
Menagerie Tableware / BG34_330 Search Through Time / BG34_444 Easterly
Winds / BG34_689 Blood Gem Barrage / BG34_888 Tomb Turning / BG34_889
Brood of Nozdormu / BG34_990 Wave of Gold / BG35_149 Deepwater Clan /
BG35_912 Eonar's Favor / BG35_922 Queen's Command / BG35_951 Might of
Stormwind / BG36_624 Repair Job / BG36_880 Methodical Madness /
BG36_883 Winner's Bread / BG36_884 Weapons Forge / EBG_Spell_017 Eyes
of the Earth Mother / EBG_Spell_032 Channel the Devourer /
EBG_Spell_037 Unmasked Identity（DEFERRED 断言）/ EBG_Spell_038 Lost
Staff of Hamuul。

数值断言一律 CardDef.num()（TEST_SOP §4）。定向法术经 play_spell
（不传 target → PendingChoice(kind="spell_target")）; Discover 类走
PendingChoice(kind="discover_minion")。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.events import TAVERN_REFRESH, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
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


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def summon_plain(game: Game, hero: Hero, m: Minion,
                 position: int | None = None) -> Minion:
    game.summon(hero, m, position)
    return m


def tavern_minion(game: Game, hero: Hero, m: Minion) -> Minion:
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def cast(game: Game, hero: Hero, card_id: str,
         target=None) -> bool:
    """施放一张池法术（占池 → 入手 → play_spell）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return game.play_spell(hero, s, target=target)


def pop_choice(game: Game, kind: str):
    """取队首 PendingChoice 并断言 kind。"""
    pc = game.pending_choices.pop(0)
    assert pc.kind == kind, f"expect {kind}, got {pc.kind}"
    return pc


class TestRegistryState(unittest.TestCase):
    """批次注册面: 20 卡 OK; Unmasked Identity DEFERRED 不注册。"""

    def test_all_cards_registered(self):
        for cid in ("BG33_817", "BG33_899", "BG34_272", "BG34_330",
                    "BG34_444", "BG34_689", "BG34_888", "BG34_889",
                    "BG34_990", "BG35_149", "BG35_912", "BG35_922",
                    "BG35_951", "BG36_624", "BG36_880", "BG36_883",
                    "BG36_884", "EBG_Spell_017", "EBG_Spell_032",
                    "EBG_Spell_038"):
            self.assertIn(cid, REGISTRY)

    def test_unmasked_identity_deferred_not_registered(self):
        self.assertNotIn("EBG_Spell_037", REGISTRY)
        game = make_game()
        s = game.create_spell("EBG_Spell_037",
                              controller=game.heroes[0])
        self.assertIsNone(s.scripts)
        from hsrl2.scripts.batches.batch_spells_final import (
            UnmaskedIdentityScript,
        )
        self.assertIsNone(UnmaskedIdentityScript.on_play(s, game, {}))


class TestSanctify(unittest.TestCase):
    """BG33_817 — 圣盾随从 +{0} 攻。"""

    def test_ds_minions_get_attack(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        m1 = summon_plain(game, a, make_minion("M1", 1, 2))
        m1.set(GameTag.DIVINE_SHIELD, True)
        m2 = summon_plain(game, a, make_minion("M2", 3, 4))
        m2.set(GameTag.DIVINE_SHIELD, True)
        m3 = summon_plain(game, a, make_minion("M3", 5, 6))
        d = get_db().get("BG33_817")
        self.assertTrue(cast(game, a, "BG33_817"))
        self.assertEqual(m1.atk, 1 + d.num(0))
        self.assertEqual(m2.atk, 3 + d.num(0))
        self.assertEqual(m3.atk, 5)               # 非圣盾不动
        self.assertEqual(m1.max_health, 2)        # 基础版仅攻击
        self.assertEqual(m2.max_health, 4)
        self.assertEqual(m3.max_health, 6)

    def test_no_ds_fizzles(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        m = summon_plain(game, a, make_minion("M", 1, 2))
        self.assertTrue(cast(game, a, "BG33_817"))
        self.assertEqual(m.atk, 1)
        self.assertEqual(m.max_health, 2)


class TestMountingAvalanche(unittest.TestCase):
    """BG33_899 — 卖随从 → 属性给最左元素。"""

    def test_sell_and_buff_leftmost_elemental(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        a.gold = 5
        victim = summon_plain(game, a, make_minion("V", 5, 7))
        e1 = summon_plain(game, a,
                          make_minion("E1", 2, 2, race=Race.ELEMENTAL))
        e2 = summon_plain(game, a,
                          make_minion("E2", 4, 4, race=Race.ELEMENTAL))
        self.assertTrue(cast(game, a, "BG33_899"))
        pc = pop_choice(game, "spell_target")
        self.assertIn(victim, pc.options)
        pc.choose(pc.options.index(victim))
        self.assertNotIn(victim, a.board)        # 已卖出
        self.assertEqual(a.gold, 6)              # 出售金币
        self.assertEqual(e1.atk, 2 + 5)          # 最左元素得快照属性
        self.assertEqual(e1.max_health, 2 + 7)
        self.assertEqual(e2.atk, 4)              # 次左元素不动
        self.assertEqual(e2.max_health, 4)

    def test_sell_value_override_proves_sell_path(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        a.gold = 0
        victim = summon_plain(game, a, make_minion("V", 1, 1))
        victim.set(GameTag.SELL_VALUE, 3)
        e = summon_plain(game, a,
                         make_minion("E", 1, 1, race=Race.ELEMENTAL))
        self.assertTrue(cast(game, a, "BG33_899", target=victim))
        self.assertEqual(a.gold, 3)              # on_sell 全路径经 sell_minion

    def test_no_elemental_fizzles(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        victim = summon_plain(game, a, make_minion("V", 5, 7))
        self.assertTrue(cast(game, a, "BG33_899", target=victim))
        self.assertNotIn(victim, a.board)        # 卖仍发生
        self.assertEqual(a.board, [])

    def test_empty_board_consumes_spell(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG33_899"))
        self.assertEqual(game.pending_choices, [])


class TestMenagerieTableware(unittest.TestCase):
    """BG34_272 — 全体 +{0}/+{1} × (1+不同种族数)。"""

    def test_two_types_three_times(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        ms = [summon_plain(game, a, make_minion("Mu", 1, 1,
                                                race=Race.MURLOC))
              for _ in range(2)]
        summon_plain(game, a, make_minion("Me", 1, 1, race=Race.MECH))
        d = get_db().get("BG34_272")
        self.assertTrue(cast(game, a, "BG34_272"))
        for m in a.board:                        # 1 基础 + 2 族 = 3 次
            self.assertEqual(m.atk, 1 + 3 * d.num(0))
            self.assertEqual(m.max_health, 1 + 3 * d.num(1))

    def test_single_type_two_times(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        for _ in range(2):
            summon_plain(game, a, make_minion("Mu", 1, 1,
                                              race=Race.MURLOC))
        d = get_db().get("BG34_272")
        self.assertTrue(cast(game, a, "BG34_272"))
        for m in a.board:                        # 1 基础 + 1 族 = 2 次
            self.assertEqual(m.atk, 1 + 2 * d.num(0))
            self.assertEqual(m.max_health, 1 + 2 * d.num(1))

    def test_none_counts_as_one_type(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        for _ in range(2):
            summon_plain(game, a, make_minion("N", 1, 1))   # NONE
        d = get_db().get("BG34_272")
        self.assertTrue(cast(game, a, "BG34_272"))
        for m in a.board:                        # NONE 算 1 种
            self.assertEqual(m.atk, 1 + 2 * d.num(0))

    def test_empty_board_fizzles(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG34_272"))
        self.assertEqual(a.board, [])


class TestSearchThroughTime(unittest.TestCase):
    """BG34_330 — 发现本级随从并锁定 1 回合。"""

    def test_discover_locks_then_unlocks_next_turn(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 2)
        self.assertTrue(cast(game, a, "BG34_330"))
        pc = pop_choice(game, "discover_minion")
        self.assertTrue(pc.options)
        for opt in pc.options:
            self.assertEqual(get_db().get(opt).tech_level, 2)
        pc.choose(0)
        self.assertEqual(len(a.hand), 1)
        locked = a.hand[0]
        self.assertTrue(locked.has(GameTag.LOCKED_IN_HAND))
        self.assertFalse(game.play_minion(a, locked))   # 锁定拒绝
        # 其他英雄的回合开始不消耗解锁
        game.events.fire(game, "turn_start", turn=2, hero=game.heroes[1])
        self.assertTrue(locked.has(GameTag.LOCKED_IN_HAND))
        # 持有者下一回合开始解锁
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertFalse(locked.has(GameTag.LOCKED_IN_HAND))
        self.assertTrue(game.play_minion(a, locked))
        self.assertEqual(a.board, [locked])

    def test_pool_occupied_on_pick(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG34_330"))
        pc = pop_choice(game, "discover_minion")
        before = game.minion_pool.available(pc.options[0])
        pc.choose(0)
        self.assertEqual(game.minion_pool.available(pc.options[0]),
                         before - 1)


class TestEasterlyWinds(unittest.TestCase):
    """BG34_444 — 刷新后馆内随机随从 +{0}/+{1}（持久 this game）。"""

    def _refresh(self, game, hero):
        game.events.fire(game, TAVERN_REFRESH, hero=hero)

    def test_refresh_buffs_random_tavern_minion(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        t1 = tavern_minion(game, a, make_minion("T1", 1, 1))
        t2 = tavern_minion(game, a, make_minion("T2", 1, 1))
        d = get_db().get("BG34_444")
        self.assertTrue(cast(game, a, "BG34_444"))
        self._refresh(game, a)
        buffed = [m for m in (t1, t2)
                  if m.atk == 1 + d.num(0)
                  and m.max_health == 1 + d.num(1)]
        self.assertEqual(len(buffed), 1)

    def test_other_hero_refresh_ignored(self):
        game = make_game(seed=2)
        a, b = game.heroes
        t1 = tavern_minion(game, a, make_minion("T1", 1, 1))
        self.assertTrue(cast(game, a, "BG34_444"))
        self._refresh(game, b)
        self.assertEqual(t1.atk, 1)
        self.assertEqual(t1.max_health, 1)

    def test_persists_across_refreshes(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        t1 = tavern_minion(game, a, make_minion("T1", 1, 1))
        d = get_db().get("BG34_444")
        self.assertTrue(cast(game, a, "BG34_444"))
        self._refresh(game, a)
        self._refresh(game, a)
        self.assertEqual(t1.atk, 1 + 2 * d.num(0))
        self.assertEqual(t1.max_health, 1 + 2 * d.num(1))

    def test_empty_tavern_no_crash(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG34_444"))
        self._refresh(game, a)                   # 无随从 → 落空
        self.assertEqual(a.tavern, [])


class TestBloodGemBarrage(unittest.TestCase):
    """BG34_689 — 刷新后馆内全体 +{0}/+{1} 等值宝石（记账）。"""

    def test_refresh_gems_all_tavern_minions(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        t1 = tavern_minion(game, a, make_minion("T1", 1, 1))
        t2 = tavern_minion(game, a, make_minion("T2", 2, 2))
        gem_events = []
        game.events.register(Listener(
            event="blood_gem_played", owner=a,
            callback=lambda g, target=None, player=None, **kw:
                gem_events.append((target, player))))
        d = get_db().get("BG34_689")
        self.assertTrue(cast(game, a, "BG34_689"))
        game.events.fire(game, TAVERN_REFRESH, hero=a)
        self.assertEqual(t1.atk, 1 + d.num(0))
        self.assertEqual(t1.max_health, 1 + d.num(1))
        self.assertEqual(t2.atk, 2 + d.num(0))
        self.assertEqual(t2.max_health, 2 + d.num(1))
        for m in (t1, t2):
            self.assertTrue(any(b.gem for b in m.buffs))
            self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON, 0), 1)
        self.assertEqual(len(gem_events), 2)
        for target, player in gem_events:
            self.assertIs(player, a)
            self.assertIn(target, (t1, t2))

    def test_other_hero_refresh_ignored(self):
        game = make_game(seed=2)
        a, b = game.heroes
        t1 = tavern_minion(game, a, make_minion("T1", 1, 1))
        self.assertTrue(cast(game, a, "BG34_689"))
        game.events.fire(game, TAVERN_REFRESH, hero=b)
        self.assertEqual(t1.atk, 1)
        self.assertFalse(any(b.gem for b in t1.buffs))


class TestTombTurning(unittest.TestCase):
    """BG34_888 — 发现 Undead，本回合打出即死。"""

    def test_played_this_turn_dies(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        pre_pool = None
        self.assertTrue(cast(game, a, "BG34_888"))
        pc = pop_choice(game, "discover_minion")
        self.assertTrue(pc.options)
        for opt in pc.options:
            self.assertIn(get_db().get(opt).race,
                          (Race.UNDEAD, Race.ALL))
        picked = pc.options[0]
        pre_pool = game.minion_pool.available(picked)
        pc.choose(0)
        self.assertEqual(game.minion_pool.available(picked),
                         pre_pool - 1)            # 发现占池
        self.assertEqual(a.hand[0].card_id, picked)
        self.assertTrue(game.play_minion(a, a.hand[0]))
        self.assertEqual(a.board, [])            # 打出即死离场
        # 招募期死亡回池: 发现占 1 份、死亡还 1 份
        self.assertEqual(game.minion_pool.available(picked), pre_pool)

    def test_played_next_turn_survives(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG34_888"))
        pc = pop_choice(game, "discover_minion")
        picked = pc.options[0]
        pc.choose(0)
        game.turn += 1                           # "this turn" 已过期
        self.assertTrue(game.play_minion(a, a.hand[0]))
        self.assertEqual(len(a.board), 1)
        self.assertEqual(a.board[0].card_id, picked)


class TestBroodOfNozdormu(unittest.TestCase):
    """BG34_889 — SoC 最左随从攻击翻倍（下一场战斗，once）。"""

    def _soc(self, game, hero):
        game.events.fire(game, "start_of_combat", hero=hero)

    def test_soc_doubles_leftmost_attack(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        left = summon_plain(game, a, make_minion("L", 3, 5))
        right = summon_plain(game, a, make_minion("R", 9, 9))
        self.assertTrue(cast(game, a, "BG34_889"))
        self._soc(game, a)
        self.assertEqual(left.atk, 6)
        self.assertEqual(left.max_health, 5)     # 只翻攻击
        self.assertEqual(right.atk, 9)

    def test_once_consumed_no_repeat(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        left = summon_plain(game, a, make_minion("L", 3, 5))
        self.assertTrue(cast(game, a, "BG34_889"))
        self._soc(game, a)
        self._soc(game, a)                       # 第二场不再触发
        self.assertEqual(left.atk, 6)

    def test_opponent_soc_slot_ignored(self):
        game = make_game(seed=3)
        a, b = game.heroes
        left = summon_plain(game, a, make_minion("L", 3, 5))
        self.assertTrue(cast(game, a, "BG34_889"))
        self._soc(game, b)
        self.assertEqual(left.atk, 3)

    def test_empty_board_no_crash(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG34_889"))
        self._soc(game, a)
        self.assertEqual(a.board, [])


class TestWaveOfGold(unittest.TestCase):
    """BG34_990 — 全体 +{0}/+{1}; 金色者再一份。"""

    def test_golden_gets_double(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        golden = summon_plain(game, a, make_minion("G", 1, 1))
        golden.set(GameTag.GOLDEN, True)
        plain = summon_plain(game, a, make_minion("P", 1, 1))
        d = get_db().get("BG34_990")
        self.assertTrue(cast(game, a, "BG34_990"))
        self.assertEqual(golden.atk, 1 + 2 * d.num(0))
        self.assertEqual(golden.max_health, 1 + 2 * d.num(1))
        self.assertEqual(plain.atk, 1 + d.num(0))
        self.assertEqual(plain.max_health, 1 + d.num(1))

    def test_empty_board_fizzles(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG34_990"))
        self.assertEqual(a.board, [])


class TestDeepwaterClan(unittest.TestCase):
    """BG35_149 — 定向 +{0}/+{1}; 全体鱼人 +{0}/+{1}。"""

    def test_murloc_target_gets_both(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        m1 = summon_plain(game, a, make_minion("M1", 1, 1,
                                               race=Race.MURLOC))
        m2 = summon_plain(game, a, make_minion("M2", 1, 1,
                                               race=Race.MURLOC))
        beast = summon_plain(game, a, make_minion("B", 1, 1,
                                                  race=Race.BEAST))
        d = get_db().get("BG35_149")
        self.assertTrue(cast(game, a, "BG35_149", target=m1))
        self.assertEqual(m1.atk, 1 + 2 * d.num(0))   # 目标句 + 鱼人句
        self.assertEqual(m1.max_health, 1 + 2 * d.num(1))
        self.assertEqual(m2.atk, 1 + d.num(0))
        self.assertEqual(m2.max_health, 1 + d.num(1))
        self.assertEqual(beast.atk, 1)               # 非鱼人不吃第二句
        self.assertEqual(beast.max_health, 1)

    def test_beast_target_only_first_sentence(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        beast = summon_plain(game, a, make_minion("B", 1, 1,
                                                  race=Race.BEAST))
        murloc = summon_plain(game, a, make_minion("M", 1, 1,
                                                   race=Race.MURLOC))
        d = get_db().get("BG35_149")
        self.assertTrue(cast(game, a, "BG35_149", target=beast))
        self.assertEqual(beast.atk, 1 + d.num(0))
        self.assertEqual(murloc.atk, 1 + d.num(0))

    def test_empty_board_consumes_spell(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG35_149"))
        self.assertEqual(game.pending_choices, [])


class TestEonarsFavor(unittest.TestCase):
    """BG35_912 — 定向种族 → 酒馆该族持久 +{0}/+{1}。"""

    def test_buffs_tavern_of_target_race_now_and_persistent(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        # 馆内随从用真实池卡 id（BuffCurrentTavern 按_db CardDef 匹配）
        beast_def = get_db().get("BG26_805")            # Beast
        mech_def = get_db().get("BG26_146")             # Mech
        all_def = get_db().get("BG27_080")              # All
        tb_beast = tavern_minion(
            game, a, game.create_minion(beast_def.id, controller=a))
        tb_mech = tavern_minion(
            game, a, game.create_minion(mech_def.id, controller=a))
        tb_all = tavern_minion(
            game, a, game.create_minion(all_def.id, controller=a))
        board_beast = summon_plain(game, a, make_minion("BB", 1, 1,
                                                        race=Race.BEAST))
        d = get_db().get("BG35_912")
        self.assertTrue(cast(game, a, "BG35_912", target=board_beast))
        self.assertEqual(tb_beast.atk, beast_def.atk + d.num(0))
        self.assertEqual(tb_beast.max_health, beast_def.health + d.num(1))
        self.assertEqual(tb_all.atk, all_def.atk + d.num(0))   # Amalgam 匹配
        self.assertEqual(tb_mech.atk, mech_def.atk)            # 他族不动
        buffs = getattr(a, "tavern_buffs", [])
        self.assertEqual(len(buffs), 1)
        self.assertEqual(buffs[0].race_filter, Race.BEAST)

    def test_none_target_fizzles(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        target = summon_plain(game, a, make_minion("N", 1, 1))  # NONE
        self.assertTrue(cast(game, a, "BG35_912", target=target))
        self.assertEqual(getattr(a, "tavern_buffs", []), [])


class TestQueensCommand(unittest.TestCase):
    """BG35_922 — 全体 +{0}/+{1}; Naga 再一份。"""

    def test_naga_gets_another(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        naga = summon_plain(game, a, make_minion("N", 1, 1,
                                                 race=Race.NAGA))
        amalgam = summon_plain(game, a, make_minion("A", 1, 1,
                                                    race=Race.ALL))
        mech = summon_plain(game, a, make_minion("M", 1, 1,
                                                 race=Race.MECH))
        d = get_db().get("BG35_922")
        self.assertTrue(cast(game, a, "BG35_922"))
        self.assertEqual(naga.atk, 1 + 2 * d.num(0))
        self.assertEqual(naga.max_health, 1 + 2 * d.num(1))
        self.assertEqual(amalgam.atk, 1 + 2 * d.num(0))  # ALL 计入 Naga
        self.assertEqual(mech.atk, 1 + d.num(0))

    def test_empty_board_fizzles(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG35_922"))
        self.assertEqual(a.board, [])


class TestMightOfStormwind(unittest.TestCase):
    """BG35_951 — 随机 4 友方 +{0}/+{1}。"""

    def test_exactly_four_random_minions(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        minions = [summon_plain(game, a, make_minion(f"M{i}", 1, 1))
                   for i in range(5)]
        d = get_db().get("BG35_951")
        self.assertTrue(cast(game, a, "BG35_951"))
        buffed = [m for m in minions
                  if m.atk == 1 + d.num(0)
                  and m.max_health == 1 + d.num(1)]
        self.assertEqual(len(buffed), 4)

    def test_fewer_than_four_all_buffed(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        minions = [summon_plain(game, a, make_minion(f"M{i}", 1, 1))
                   for i in range(3)]
        d = get_db().get("BG35_951")
        self.assertTrue(cast(game, a, "BG35_951"))
        for m in minions:
            self.assertEqual(m.atk, 1 + d.num(0))

    def test_empty_board_fizzles(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG35_951"))
        self.assertEqual(a.board, [])


class TestRepairJob(unittest.TestCase):
    """BG36_624 — 定向 +{0}/+{1}。"""

    def test_target_buffed(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        tgt = summon_plain(game, a, make_minion("T", 1, 1))
        other = summon_plain(game, a, make_minion("O", 2, 2))
        d = get_db().get("BG36_624")
        self.assertTrue(cast(game, a, "BG36_624", target=tgt))
        self.assertEqual(tgt.atk, 1 + d.num(0))
        self.assertEqual(tgt.max_health, 1 + d.num(1))
        self.assertEqual(other.atk, 2)
        self.assertEqual(other.max_health, 2)

    def test_spell_target_choice_flow(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        tgt = summon_plain(game, a, make_minion("T", 1, 1))
        d = get_db().get("BG36_624")
        self.assertTrue(cast(game, a, "BG36_624"))
        pc = pop_choice(game, "spell_target")
        pc.choose(pc.options.index(tgt))
        self.assertEqual(tgt.atk, 1 + d.num(0))

    def test_empty_board_consumes_spell(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "BG36_624"))
        self.assertEqual(game.pending_choices, [])


class TestMethodicalMadness(unittest.TestCase):
    """BG36_880 — 定向恶魔吞噬 2 随机馆随从（属性+Bonus Keywords）。"""

    def test_consume_two_with_keywords(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        v1 = tavern_minion(game, a, make_minion("V1", 3, 4))
        v1.set(GameTag.TAUNT, True)
        v2 = tavern_minion(game, a, make_minion("V2", 2, 5))
        demon = summon_plain(game, a, make_minion("D", 1, 1,
                                                  race=Race.DEMON))
        self.assertTrue(cast(game, a, "BG36_880", target=demon))
        self.assertEqual(demon.atk, 1 + 3 + 2)       # 两受害者 atk 合计
        self.assertEqual(demon.max_health, 1 + 4 + 5)
        self.assertTrue(demon.has(GameTag.TAUNT))    # Bonus Keyword 移转
        self.assertEqual(a.tavern, [])               # 馆被清空

    def test_pool_released_on_consume(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        cid = next(d.id for d in get_db().pool_minions()
                   if game.minion_pool.available(d.id) > 0)
        before = game.minion_pool.available(cid)
        assert game.minion_pool.acquire(cid)     # 馆内展示占池（draw 同构）
        v = game.create_minion(cid, controller=a)
        tavern_minion(game, a, v)
        demon = summon_plain(game, a, make_minion("D", 1, 1,
                                                  race=Race.DEMON))
        # 独占随机: 馆内仅一只
        self.assertTrue(cast(game, a, "BG36_880", target=demon))
        self.assertEqual(game.minion_pool.available(cid), before)  # 回池

    def test_candidates_exclude_non_demon(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        demon = summon_plain(game, a, make_minion("D", 1, 1,
                                                  race=Race.DEMON))
        amalgam = summon_plain(game, a, make_minion("A", 1, 1,
                                                    race=Race.ALL))
        mech = summon_plain(game, a, make_minion("M", 1, 1,
                                                 race=Race.MECH))
        tavern_minion(game, a, make_minion("V", 1, 1))
        self.assertTrue(cast(game, a, "BG36_880"))
        pc = pop_choice(game, "spell_target")
        self.assertEqual(set(pc.options), {demon, amalgam})  # ALL 计入

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        demon = summon_plain(game, a, make_minion("D", 1, 1,
                                                  race=Race.DEMON))
        self.assertTrue(cast(game, a, "BG36_880", target=demon))
        self.assertEqual(demon.atk, 1)
        self.assertEqual(demon.max_health, 1)


class TestWinnersBread(unittest.TestCase):
    """BG36_883 — 即时 +{0}/+{1}; 胜→下回合开始 +{2}/+{3}。"""

    def _win_combat(self, game, winner, loser):
        result = SimpleNamespace(winner=winner, loser=loser,
                                 damage_dealt=0)
        game.events.fire(game, "combat_end", hero_a=winner,
                         hero_b=loser, result=result)

    def _run_deferred(self, game):
        for _, action in list(game.deferred_actions):
            action.do(game)
        game.deferred_actions = []

    def test_immediate_buff_and_win_second_buff(self):
        game = make_game(seed=1)
        a, b = game.heroes
        tgt = summon_plain(game, a, make_minion("T", 1, 1))
        d = get_db().get("BG36_883")
        self.assertTrue(cast(game, a, "BG36_883", target=tgt))
        self.assertEqual(tgt.atk, 1 + d.num(0))
        self.assertEqual(tgt.max_health, 1 + d.num(1))
        self._win_combat(game, a, b)
        self.assertEqual(len(game.deferred_actions), 1)
        self._run_deferred(game)                  # 下一回合开始时点
        self.assertEqual(tgt.atk, 1 + d.num(0) + d.num(2))
        self.assertEqual(tgt.max_health, 1 + d.num(1) + d.num(3))

    def test_loss_no_second_buff(self):
        game = make_game(seed=2)
        a, b = game.heroes
        tgt = summon_plain(game, a, make_minion("T", 1, 1))
        d = get_db().get("BG36_883")
        self.assertTrue(cast(game, a, "BG36_883", target=tgt))
        self._win_combat(game, b, a)              # 败
        self.assertEqual(game.deferred_actions, [])
        self.assertEqual(tgt.atk, 1 + d.num(0))

    def test_sold_target_second_buff_fizzles(self):
        game = make_game(seed=3)
        a, b = game.heroes
        tgt = summon_plain(game, a, make_minion("T", 1, 1))
        d = get_db().get("BG36_883")
        self.assertTrue(cast(game, a, "BG36_883", target=tgt))
        self._win_combat(game, a, b)
        game.sell_minion(a, tgt)                  # 下回合前卖出
        self._run_deferred(game)
        # 目标离场 → 第二段落空（原 1+num0 已随实体带走）
        self.assertEqual(tgt.atk, 1 + d.num(0))

    def test_full_cycle_win_grants_next_turn(self):
        game = make_game(seed=4)
        game.start_game()
        a, b = game.heroes
        tgt = summon_plain(game, a, make_minion("T", 10, 10))
        d = get_db().get("BG36_883")
        self.assertTrue(cast(game, a, "BG36_883", target=tgt))
        game.end_recruit_phase()                  # a 10/10 vs 空板 → 胜
        self.assertEqual(game.turn, 2)
        self.assertEqual(tgt.atk, 10 + d.num(0) + d.num(2))
        self.assertEqual(tgt.max_health, 10 + d.num(1) + d.num(3))

    def test_once_consumed(self):
        game = make_game(seed=5)
        a, b = game.heroes
        tgt = summon_plain(game, a, make_minion("T", 1, 1))
        d = get_db().get("BG36_883")
        self.assertTrue(cast(game, a, "BG36_883", target=tgt))
        self._win_combat(game, a, b)
        self._run_deferred(game)
        self._win_combat(game, a, b)              # 第二胜不再触发
        self._run_deferred(game)
        self.assertEqual(tgt.atk, 1 + d.num(0) + d.num(2))


class TestWeaponsForge(unittest.TestCase):
    """BG36_884 — Get {0} Pointy Arrows。"""

    def test_gets_three_arrows(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG36_884")
        self.assertTrue(cast(game, a, "BG36_884"))
        self.assertEqual(len(a.hand), d.num(0))
        for s in a.hand:
            self.assertIsInstance(s, Spell)
            self.assertEqual(s.card_id, "EBG_Spell_014")
        # Pointy Arrow 非池法术——spell_pool 无占用
        self.assertEqual(game.spell_pool.available("EBG_Spell_014"), 0)


class TestEyesOfTheEarthMother(unittest.TestCase):
    """EBG_Spell_017 — T≤4 友随金色化（Reno 式，无三连奖励）。"""

    def _goldenizable(self, game):
        for d in game.db.pool_minions():
            if d.tech_level <= 4 and game.db.golden_version(d) is not None:
                return game.create_minion(d.id, controller=game.heroes[0])
        self.fail("no goldenizable pool minion in data")

    def test_goldenize_keeps_buffs_no_triple_reward(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        tgt = summon_plain(game, a, self._goldenizable(game))
        base_def = game.db.get(tgt.card_id)
        golden_def = game.db.golden_version(base_def)
        from hsrl2.entity import Buff as BuffEnchant
        tgt.add_buff(BuffEnchant(atk=3, health=4))
        base_id = tgt.card_id
        self.assertTrue(cast(game, a, "EBG_Spell_017"))
        pc = pop_choice(game, "spell_target")
        self.assertIn(tgt, pc.options)
        pc.choose(pc.options.index(tgt))
        self.assertEqual(len(a.board), 1)
        new = a.board[0]
        self.assertTrue(new.is_golden)
        self.assertEqual(new.card_id, golden_def.id)
        self.assertFalse(new.has(GameTag.TRIPLE_REWARD_PENDING))
        self.assertEqual(game.pending_choices, [])    # 无三连奖励发现
        # buff 并集保留（金色卡面属性 + 原 buff; Transform 重算 max_health）
        self.assertEqual(new.atk, golden_def.atk + 3)
        self.assertEqual(new.max_health, golden_def.health + 4)

    def test_candidates_exclude_t5_and_golden(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        t5 = next(d.id for d in game.db.pool_minions()
                  if d.tech_level >= 5)
        m_t5 = summon_plain(game, a,
                            game.create_minion(t5, controller=a))
        m_ok = summon_plain(game, a, self._goldenizable(game))
        m_golden = summon_plain(game, a, self._goldenizable(game))
        m_golden.set(GameTag.GOLDEN, True)
        s = game.create_spell("EBG_Spell_017", controller=a)
        cands = s.scripts.target_candidates(s, game)
        self.assertEqual(set(cands), {m_ok})
        self.assertNotIn(m_t5, cands)

    def test_no_candidates_consumes_spell(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "EBG_Spell_017"))
        self.assertEqual(game.pending_choices, [])


class TestChannelTheDevourer(unittest.TestCase):
    """EBG_Spell_032 — 卖随从 → 属性给随机友方。"""

    def test_sell_and_random_receiver(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        a.gold = 3
        victim = summon_plain(game, a, make_minion("V", 5, 7))
        r1 = summon_plain(game, a, make_minion("R1", 1, 1))
        r2 = summon_plain(game, a, make_minion("R2", 2, 2))
        self.assertTrue(cast(game, a, "EBG_Spell_032"))
        pc = pop_choice(game, "spell_target")
        pc.choose(pc.options.index(victim))
        self.assertNotIn(victim, a.board)
        self.assertEqual(a.gold, 4)               # 出售金币
        receivers = [m for m in (r1, r2)
                     if m.atk == (1 if m is r1 else 2) + 5
                     and m.max_health == (1 if m is r1 else 2) + 7]
        self.assertEqual(len(receivers), 1)       # 恰一只获得快照属性

    def test_solo_board_sold_fizzles(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        a.gold = 3
        victim = summon_plain(game, a, make_minion("V", 5, 7))
        self.assertTrue(cast(game, a, "EBG_Spell_032", target=victim))
        self.assertEqual(a.board, [])             # 卖仍发生
        self.assertEqual(a.gold, 4)               # +1 出售金币

    def test_empty_board_consumes_spell(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        self.assertTrue(cast(game, a, "EBG_Spell_032"))
        self.assertEqual(game.pending_choices, [])


class TestLostStaffOfHamuul(unittest.TestCase):
    """EBG_Spell_038 — 定向种族 → 酒馆按该族刷新。"""

    def test_refresh_with_target_race(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        tavern_minion(game, a, make_minion("OLD1", 1, 1))
        tavern_minion(game, a, make_minion("OLD2", 2, 2))
        beast = summon_plain(game, a, make_minion("B", 1, 1,
                                                  race=Race.BEAST))
        refreshes = []
        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=a,
            callback=lambda g, hero=None, **kw: refreshes.append(hero)))
        self.assertTrue(cast(game, a, "EBG_Spell_038", target=beast))
        self.assertEqual(refreshes, [a])          # "Refresh" 计为刷新
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(minions),
                         C.TAVERN_OFFERS[a.tavern_tier])
        for m in minions:
            self.assertIn(m.race, (Race.BEAST, Race.ALL))
        # 旧馆内容（含法术位）被替换
        self.assertNotIn("TEST_OLD1", [e.card_id for e in a.tavern])

    def test_pool_conserved_on_recycle(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        cid = next(d.id for d in get_db().pool_minions()
                   if d.race != Race.BEAST
                   and game.minion_pool.available(d.id) > 0)
        before = game.minion_pool.available(cid)
        assert game.minion_pool.acquire(cid)     # 馆内展示占池（draw 同构）
        tavern_minion(game, a, game.create_minion(cid, controller=a))
        beast = summon_plain(game, a, make_minion("B", 1, 1,
                                                  race=Race.BEAST))
        self.assertTrue(cast(game, a, "EBG_Spell_038", target=beast))
        self.assertEqual(game.minion_pool.available(cid), before)  # 回池

    def test_none_target_unrestricted_refresh(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        target = summon_plain(game, a, make_minion("N", 1, 1))   # NONE
        self.assertTrue(cast(game, a, "EBG_Spell_038", target=target))
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(minions),
                         C.TAVERN_OFFERS[a.tavern_tier])   # 不限族满额

    def test_new_minions_get_registered_tavern_buffs(self):
        """刷新入馆随从应用 hero.tavern_buffs（引擎 refresh 同构）。"""
        from hsrl2.actions.tavern_buff import ApplyTavernBuff, TavernBuff
        game = make_game(seed=4)
        a = game.heroes[0]
        ApplyTavernBuff(a, TavernBuff(atk=2, health=2,
                                      race_filter=None)).do(game)
        beast = summon_plain(game, a, make_minion("B", 1, 1,
                                                  race=Race.BEAST))
        self.assertTrue(cast(game, a, "EBG_Spell_038", target=beast))
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(minions),
                         C.TAVERN_OFFERS[a.tavern_tier])
        for m in minions:                         # 新入馆即带持久 buff
            self.assertEqual(m.atk, get_db().get(m.card_id).atk + 2)
            self.assertEqual(m.max_health,
                             get_db().get(m.card_id).health + 2)


if __name__ == "__main__":
    unittest.main()
