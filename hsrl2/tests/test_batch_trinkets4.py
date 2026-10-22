"""批次 trinkets4 语义测试（4 张饰品，主线实现 2026-09-02）。

行为层断言（真实路径: 绑定饰品 → 真实打出/血宝石/战斗/事件）:
  - 914 Nerglish Phrasebook  打出随从 → 手牌最左**随从** +3/+3;
                             对手打出/本人打法术不触发
  - 988 Great Boar Sticker   入手 3 颗血宝石; 施放数值 = 基础 + num 参数
  - 864 Gilnean Thorned Rose Avenge(num(0)): 存活随从 +num(1)/+num(2)
                             并各受 1 伤; 招募期死亡不触发
  - 923 Elementium Chest     每场战斗每 2 个友方海盗攻击 → 下回合 +1 金;
                             非海盗/招募期不计数; combat_end 清零
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.db import CardDB
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_trinkets4 import T864
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

TYPO_LESS = "BG27_002"        # Oozeling Gladiator 2/2 —— 无类型/无脚本
MURLOC = "BG22_202"           # Tad 2/2 —— Murloc（无死亡/攻击效果）
BLOOD_GEM = "BG20_GEM"         # Blood Gem（token 法术; CardDB 按名核实）

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 60):
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def buy_trinket(game, hero, tid):
    e = game.create_entity(tid, controller=hero)
    hero.trinkets.append(e)
    game.run_script_hook(e, "on_bind", ctx={"hero": hero})
    return e


class TestRegistry(unittest.TestCase):
    IMPLEMENTED = ("BG30_MagicItem_914", "BG30_MagicItem_988",
                   "BG30_MagicItem_864", "BG30_MagicItem_923")

    def test_all_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)
        self.assertEqual(len(self.IMPLEMENTED), 4)


class TestNerglishPhrasebook(unittest.TestCase):
    TID = "BG30_MagicItem_914"

    def test_buffs_leftmost_hand_minion(self):
        g = make_game(seed=201)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        # 手牌: 法术（更左）→ 随从（目标）
        spell = g.create_spell("BG28_800", controller=a)
        a.hand.append(spell)
        target = g.create_minion(MURLOC, controller=a)
        a.hand.append(target)
        other = g.create_minion(MURLOC, controller=a)   # 更右的随从不应被 buff
        a.hand.append(other)
        played = g.create_minion(TYPO_LESS, controller=a)
        a.hand.append(played)
        self.assertTrue(g.play_minion(a, played))
        self.assertEqual((target.atk, target.max_health), (5, 5))  # 2/2 +3/+3
        self.assertEqual((other.atk, other.max_health), (2, 2))

    def test_opponent_play_does_not_trigger(self):
        g = make_game(seed=202)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        target = g.create_minion(MURLOC, controller=a)
        a.hand.append(target)
        played = g.create_minion(TYPO_LESS, controller=b)
        b.hand.append(played)
        self.assertTrue(g.play_minion(b, played))
        self.assertEqual((target.atk, target.max_health), (2, 2))

    def test_spell_play_does_not_trigger(self):
        g = make_game(seed=203)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        target = g.create_minion(MURLOC, controller=a)
        a.hand.append(target)
        s = g.create_spell("BG28_800", controller=a)
        a.hand.append(s)
        a.gold = 10
        self.assertTrue(g.play_spell(a, s))
        self.assertEqual((target.atk, target.max_health), (2, 2))


class TestGreatBoarSticker(unittest.TestCase):
    TID = "BG30_MagicItem_988"

    def test_three_gems_and_bonus(self):
        g = make_game(seed=204)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        self.assertEqual(
            sum(1 for e in a.hand if e.card_id == BLOOD_GEM), 3)
        m = g.create_minion(MURLOC, controller=a)
        g.summon(a, m)
        base = (m.atk, m.max_health)
        g.run_actions(PlayBloodGems(m, 1))
        # 1 颗血宝石 = 基础 +1/+1 + 英雄加成 num(0)/num(1)
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 1 + d.num(0), base[1] + 1 + d.num(1)))

    def test_opponent_unaffected(self):
        g = make_game(seed=205)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        self.assertEqual(b.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 0)
        self.assertEqual(b.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 0)


class TestGilneanThornedRose(unittest.TestCase):
    TID = "BG30_MagicItem_864"

    def test_threshold_matches_data(self):
        self.assertEqual(T864.avenge_threshold,
                         get_db().get(self.TID).num(0))

    def test_avenge_buffs_and_damages_survivors(self):
        g = make_game(seed=206)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        ms = []
        for _ in range(4):
            m = g.create_minion(MURLOC, controller=a)
            g.summon(a, m)
            m.add_buff(BuffEnchant(health=50))     # 防 1 伤致死，聚焦断言
            ms.append(m)
        survivor = ms[3]
        prev = g.in_combat
        g.in_combat = True
        try:
            for m in ms[:3]:
                m.set(GameTag.HEALTH, 0)
                g._process_single_death(m)
        finally:
            g.in_combat = prev
        base_atk, base_max = 2, 52
        self.assertFalse(survivor.dead)
        self.assertEqual(survivor.atk, base_atk + d.num(1))
        self.assertEqual(survivor.max_health, base_max + d.num(2))
        self.assertEqual(survivor.health, base_max + d.num(2) - 1)  # 受伤 1

    def test_recruit_phase_deaths_do_not_trigger(self):
        g = make_game(seed=207)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        survivor = g.create_minion(MURLOC, controller=a)
        g.summon(a, survivor)
        survivor.add_buff(BuffEnchant(health=50))
        dead = []
        for _ in range(3):
            m = g.create_minion(MURLOC, controller=a)
            g.summon(a, m)
            dead.append(m)
        for m in dead:
            m.set(GameTag.HEALTH, 0)
            g._process_single_death(m)     # 招募期（in_combat False）
        self.assertEqual((survivor.atk, survivor.max_health), (2, 52))


class TestElementiumChest(unittest.TestCase):
    TID = "BG30_MagicItem_923"

    def _attack(self, g, attacker):
        g.events.fire(g, "after_attack", attacker=attacker, defender=None)

    def test_two_pirate_attacks_grant_gold_next_turn(self):
        g = make_game(seed=208)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        pirate = g.create_minion(MURLOC, controller=a)
        g.summon(a, pirate)
        pirate.set(GameTag.RACE, Race.PIRATE)
        prev = g.in_combat
        g.in_combat = True
        try:
            for _ in range(d.num(0)):
                self._attack(g, pirate)
        finally:
            g.in_combat = prev
        a.gold = 0
        g._begin_recruit_for(a)
        self.assertEqual(a.gold,
                         C.gold_base_income(g.turn, a.income_cap) + 1)

    def test_non_pirate_and_recruit_phase_do_not_count(self):
        g = make_game(seed=209)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        murloc = g.create_minion(MURLOC, controller=a)
        g.summon(a, murloc)
        g.in_combat = True
        try:
            for _ in range(d.num(0)):
                self._attack(g, murloc)        # 非海盗
        finally:
            g.in_combat = False
        pirate = g.create_minion(MURLOC, controller=a)
        g.summon(a, pirate)
        pirate.set(GameTag.RACE, Race.PIRATE)
        self._attack(g, pirate)                # 招募期（in_combat False）
        a.gold = 0
        g._begin_recruit_for(a)
        self.assertEqual(a.gold, C.gold_base_income(g.turn, a.income_cap))

    def test_combat_end_resets_counter(self):
        g = make_game(seed=210)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        pirate = g.create_minion(MURLOC, controller=a)
        g.summon(a, pirate)
        pirate.set(GameTag.RACE, Race.PIRATE)
        g.in_combat = True
        try:
            self._attack(g, pirate)            # 1/2
        finally:
            g.in_combat = False
        g.events.fire(g, "combat_end", hero_a=a, hero_b=None, result=None)
        g.in_combat = True
        try:
            self._attack(g, pirate)            # 清零后重新 1/2
        finally:
            g.in_combat = False
        a.gold = 0
        g._begin_recruit_for(a)
        self.assertEqual(a.gold, C.gold_base_income(g.turn, a.income_cap))


if __name__ == "__main__":
    unittest.main()
