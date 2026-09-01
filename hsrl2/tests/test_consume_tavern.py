"""吞噬（Consume/Fodder）+ 酒馆持久 Buff 测试。

覆盖:
  1. ConsumeMinion 三来源（酒馆/手牌/棋盘）:
     - 属性获得用 atk / **max_health**（属性值非当前血——v1 教训，
       受损受害者验证）
     - 池记账: 酒馆/手牌来源回池（available +1）; 棋盘来源不回池
       （RULES §2.3 回池路径列举: 出售/金色/磁力/淘汰——吞噬不在列）
     - 棋盘吞噬不是死亡: 亡语不触发、无 "death" 事件、board 移除
  2. ConsumeRandomTavernMinion: 固定 seed 确定性; 空酒馆落空
  3. TavernBuff.matches: race/min_tier/max_tier 组合 + Amalgam 规则
  4. ApplyTavernBuff（持久记录）/ BuffCurrentTavern（立即生效）
数值断言全部从 db 的 CardDef 取（零硬编码）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.consume import (CONSUME_EVENT, ConsumeMinion,
                                   ConsumeRandomTavernMinion)
from hsrl2.actions.tavern_buff import (ApplyTavernBuff, BuffCurrentTavern,
                                       TavernBuff)
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game, GameStateError
from hsrl2.hero import Hero
from hsrl2.tags import Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEMON_CARD_ID = "BG21_004"          # Insatiable Ur'zul（consume 源卡）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str) -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42) -> Game:
    return Game([make_hero("A"), make_hero("B")], get_db(), seed=seed)


def find_def(race: Race | None = None, tier: int | None = None,
             min_health: int | None = None):
    """按种族/tier/血量找池卡（排除 battlecry/deathrattle——无脚本副作用）。"""
    for d in sorted(get_db().pool_minions(), key=lambda x: x.id):
        if race is not None and d.race != race:
            continue
        if tier is not None and d.tech_level != tier:
            continue
        if min_health is not None and d.health < min_health:
            continue
        if "battlecry" in d.keywords or "deathrattle" in d.keywords:
            continue
        return d
    raise AssertionError(f"no pool def: race={race} tier={tier} "
                         f"min_health={min_health}")


def put_in_tavern(game: Game, hero: Hero, card_id: str):
    """占池后放入酒馆（模拟 draw_tavern 的池记账）。"""
    assert game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def put_in_hand(game: Game, hero: Hero, card_id: str):
    """占池后放入手牌（模拟 buy_from_tavern 的池记账）。"""
    assert game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.HAND
    hero.hand.append(m)
    return m


class TestConsumeMinion(unittest.TestCase):
    def _demon(self, game: Game, hero: Hero):
        return game.create_minion(DEMON_CARD_ID, controller=hero)

    def test_tavern_source_gains_stats_and_returns_to_pool(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        dd = get_db().get(DEMON_CARD_ID)
        demon = self._demon(game, a)
        game.summon(a, demon)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)
        # 受损害: 当前血 1 < max_health —— 恶魔必须获得属性值 (v1 教训)
        victim.health = 1
        avail_before = game.minion_pool.available(vd.id)

        game.run_actions(ConsumeMinion(demon, victim))

        self.assertEqual(demon.atk, dd.atk + vd.atk)
        self.assertEqual(demon.max_health, dd.health + vd.health)
        self.assertEqual(demon.health, dd.health + vd.health)
        self.assertNotIn(victim, a.tavern)
        self.assertEqual(len(a.tavern), 0)
        self.assertEqual(victim.zone, Zone.REMOVED)
        self.assertEqual(game.minion_pool.available(vd.id), avail_before + 1)

    def test_hand_source_gains_stats_and_returns_to_pool(self):
        game = make_game(seed=22)
        a = game.heroes[0]
        dd = get_db().get(DEMON_CARD_ID)
        demon = self._demon(game, a)
        game.summon(a, demon)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_hand(game, a, vd.id)
        avail_before = game.minion_pool.available(vd.id)

        game.run_actions(ConsumeMinion(demon, victim))

        self.assertEqual(demon.atk, dd.atk + vd.atk)
        self.assertEqual(demon.max_health, dd.health + vd.health)
        self.assertNotIn(victim, a.hand)
        self.assertEqual(len(a.hand), 0)
        self.assertEqual(victim.zone, Zone.REMOVED)
        self.assertEqual(game.minion_pool.available(vd.id), avail_before + 1)

    def test_board_source_no_deathrattle_no_death_event_no_pool_return(self):
        game = make_game(seed=23)
        a = game.heroes[0]
        dd = get_db().get(DEMON_CARD_ID)
        demon = self._demon(game, a)
        game.summon(a, demon)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        assert game.minion_pool.acquire(vd.id)      # 购买占池
        victim = game.create_minion(vd.id, controller=a)
        game.summon(a, victim)
        avail_before = game.minion_pool.available(vd.id)

        # 假亡语脚本 + death 事件计数（吞噬≠死亡: 两者都必须保持 0）
        dr_calls = []
        victim.set_script_override(
            "deathrattle", lambda s, g, c: dr_calls.append(1))
        deaths = []
        game.events.register(Listener(
            event="death", owner=demon,
            callback=lambda g, **kw: deaths.append(kw.get("minion"))))
        consumes = []
        game.events.register(Listener(
            event=CONSUME_EVENT, owner=demon,
            callback=lambda g, **kw: consumes.append(kw.get("minion"))))

        game.run_actions(ConsumeMinion(demon, victim))

        self.assertEqual(dr_calls, [])              # 不触发亡语
        self.assertEqual(deaths, [])                # 无死亡事件
        self.assertEqual(consumes, [victim])        # consume 事件照常广播
        self.assertNotIn(victim, a.board)           # board 移除
        self.assertEqual(victim.zone, Zone.REMOVED)
        self.assertNotIn(victim, a.graveyard)
        # 不回池: RULES §2.3 回池路径（出售/金色/磁力/淘汰）不含吞噬
        self.assertEqual(game.minion_pool.available(vd.id), avail_before)
        self.assertEqual(demon.atk, dd.atk + vd.atk)
        self.assertEqual(demon.max_health, dd.health + vd.health)

    def test_contract_violations_raise(self):
        game = make_game(seed=24)
        a = game.heroes[0]
        demon = self._demon(game, a)
        game.summon(a, demon)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)
        with self.assertRaises(GameStateError):
            ConsumeMinion(demon, demon).do(game)          # 不能吞噬自己
        dead = put_in_tavern(game, a, vd.id)
        dead.health = 0
        with self.assertRaises(GameStateError):
            ConsumeMinion(demon, dead).do(game)           # 不能吞噬死者
        stranger = game.create_minion(vd.id, controller=a)
        stranger.zone = Zone.REMOVED
        with self.assertRaises(GameStateError):
            ConsumeMinion(demon, stranger).do(game)       # 不可吞噬区域


class TestConsumeRandomTavernMinion(unittest.TestCase):
    def test_deterministic_with_fixed_seed(self):
        game = make_game(seed=99)
        a = game.heroes[0]
        dd = get_db().get(DEMON_CARD_ID)
        demon = game.create_minion(DEMON_CARD_ID, controller=a)
        game.summon(a, demon)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)
        avail_before = game.minion_pool.available(vd.id)

        game.run_actions(ConsumeRandomTavernMinion(demon))

        self.assertEqual(demon.atk, dd.atk + vd.atk)
        self.assertEqual(demon.max_health, dd.health + vd.health)
        self.assertEqual(len(a.tavern), 0)
        self.assertEqual(game.minion_pool.available(vd.id), avail_before + 1)
        self.assertTrue(any(label == "consume_random_tavern"
                            for label, _ in game.rng.decisions))

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=100)
        a = game.heroes[0]
        dd = get_db().get(DEMON_CARD_ID)
        demon = game.create_minion(DEMON_CARD_ID, controller=a)
        game.summon(a, demon)
        self.assertEqual(a.tavern, [])

        game.run_actions(ConsumeRandomTavernMinion(demon))   # 不抛异常

        self.assertEqual(demon.atk, dd.atk)
        self.assertEqual(demon.max_health, dd.health)


class TestTavernBuffMatches(unittest.TestCase):
    def test_race_and_tier_combinations(self):
        beast1 = find_def(race=Race.BEAST, tier=1, min_health=3)
        beast2 = find_def(race=Race.BEAST, tier=2)
        beast4 = find_def(race=Race.BEAST, tier=4)
        naga1 = find_def(race=Race.NAGA, tier=1)
        all4 = next(d for d in get_db().pool_minions()
                    if d.race == Race.ALL)          # Amalgam

        b = TavernBuff(atk=1, health=1, race_filter=Race.BEAST,
                       min_tier=2, max_tier=3)
        self.assertTrue(b.matches(beast2))          # 命中
        self.assertFalse(b.matches(beast1))         # min_tier 排除
        self.assertFalse(b.matches(beast4))         # max_tier 排除
        self.assertFalse(b.matches(naga1))          # race 排除
        # Amalgam 匹配任何 race_filter，但仍受 tier 约束（all4 为 T4）
        self.assertFalse(b.matches(all4))
        self.assertTrue(TavernBuff(race_filter=Race.BEAST).matches(all4))
        self.assertTrue(TavernBuff(race_filter=Race.NAGA).matches(all4))

        no_filter = TavernBuff(atk=2)
        for d in (beast1, beast2, beast4, naga1, all4):
            self.assertTrue(no_filter.matches(d))   # 无过滤全匹配

        self.assertTrue(TavernBuff(min_tier=2).matches(beast4))
        self.assertFalse(TavernBuff(min_tier=5).matches(beast4))
        self.assertTrue(TavernBuff(max_tier=3).matches(beast1))
        self.assertFalse(TavernBuff(max_tier=3).matches(beast4))
        # 无种族 def 不匹配任何 race_filter（与 discover 过滤一致）
        raceless = find_def(race=Race.NONE, tier=1)
        self.assertFalse(TavernBuff(race_filter=Race.BEAST).matches(raceless))


class TestApplyAndBuffCurrentTavern(unittest.TestCase):
    def test_apply_records_persistently_without_immediate_effect(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        bd = find_def(race=Race.BEAST, tier=1, min_health=3)
        m = put_in_tavern(game, a, bd.id)

        buff = TavernBuff(atk=1, health=2, race_filter=Race.BEAST,
                          source_id="TEST_SOURCE")
        game.run_actions(ApplyTavernBuff(a, buff))

        self.assertEqual(a.tavern_buffs, [buff])    # 持久记录存在
        self.assertEqual(m.atk, bd.atk)             # 仅记录、不立即生效
        self.assertEqual(m.max_health, bd.health)

    def test_buff_current_tavern_immediate_effect(self):
        game = make_game(seed=32)
        a = game.heroes[0]
        bd = find_def(race=Race.BEAST, tier=1, min_health=3)
        nd = find_def(race=Race.NAGA, tier=1)
        beast = put_in_tavern(game, a, bd.id)
        naga = put_in_tavern(game, a, nd.id)

        buff = TavernBuff(atk=1, health=2, race_filter=Race.BEAST,
                          source_id="TEST_SOURCE")
        game.run_actions(BuffCurrentTavern(a, buff))

        self.assertEqual(beast.atk, bd.atk + 1)
        self.assertEqual(beast.max_health, bd.health + 2)
        self.assertEqual(beast.health, bd.health + 2)   # add_buff 同步当前血
        self.assertEqual(naga.atk, nd.atk)              # 不匹配不受影响
        self.assertEqual(naga.max_health, nd.health)
        self.assertFalse(getattr(a, "tavern_buffs", None))  # 无持久记录

    def test_apply_plus_buff_current(self):
        game = make_game(seed=33)
        a = game.heroes[0]
        bd = find_def(race=Race.BEAST, tier=1, min_health=3)
        beast = put_in_tavern(game, a, bd.id)

        buff = TavernBuff(atk=3, health=3, race_filter=Race.BEAST)
        game.run_actions([ApplyTavernBuff(a, buff), BuffCurrentTavern(a, buff)])

        self.assertEqual(beast.atk, bd.atk + 3)     # 立即生效
        self.assertEqual(beast.max_health, bd.health + 3)
        self.assertEqual(a.tavern_buffs, [buff])    # + 持久记录

    def test_refresh_tavern_applies_persistent_buffs_engine_gap(self):
        """持久酒馆 Buff 挂接（主线已接线 game.refresh_tavern:
        新入馆随从应用 hero.tavern_buffs 匹配项; 冻结保留项不重复应用）。"""
        game = make_game(seed=34)
        a = game.heroes[0]
        bd = find_def(race=Race.BEAST, tier=1, min_health=3)
        buff = TavernBuff(atk=1, health=1, race_filter=Race.BEAST)
        game.run_actions(ApplyTavernBuff(a, buff))
        game.refresh_tavern(a, auto=True)
        beasts = [m for m in a.tavern
                  if get_db().get(m.card_id).race == Race.BEAST]
        self.assertTrue(beasts)
        for m in beasts:
            d = get_db().get(m.card_id)
            self.assertEqual(m.atk, d.atk + 1)
            self.assertEqual(m.max_health, d.health + 1)


if __name__ == "__main__":
    unittest.main()
