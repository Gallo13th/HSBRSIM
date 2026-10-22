"""批次 trinkets2 语义测试（20 张饰品 + 1 张 Spellcraft 法术 token）。

行为层断言（真实路径: 绑定饰品 → 真事件/真战斗/真刷新/真施法）:
  - 847 Goblin Wallet       EoT → income_cap 抬升且真实基础收入封顶生效
  - 403 Ironforge Anvil     SoC → 无类型随从 ×3，有类型不变; 战后回滚
  - 414/414t Kodo Pouch     真实买随从/买酒馆法术 → 恰好 2 个随从 +2/+1
                            （414t +4/+4）; 对手购买不触发
  - 437 Staff of the Scourge 第 5 次友方死亡触发 Reborn 且计数清零;
                            对手死亡不计数
  - 542 Emerald Dreamcatcher SoC → 龙攻击力 = 战团最高（非龙最高计入）
  - 427/427t Tiger Carving  受伤者被排除; 真 run_combat 后永久保留
  - 900/900t Dragonwing     打随从/打法术各触发; 随机 1 条龙 +num
  - 970/970t Valorous       SoC 全体 +2/+2（970t +6/+6）; 战后回滚
  - 925 Ceremonial Sword    攻击宣告 +4 攻计入本次伤害快照
  - 270/270t Wicked Tome    Avenge 达标写 TAVERN_SPELL_EXTRA_ATK/HEALTH
                            且 tavern_spell_buff 出口实际增幅
  - 544/544t Nomi Sticker   打出元素 → 馆内元素即时 buff + 持久面生效
  - 547/547t Comfy Coffin   施放酒馆法术 → 亡灵 race_aura 叠加（含新手）
  - 714/714t Precious Pearl 绑定即得 Spellcraft 法术; 施放 +30/+30;
                            下一招募阶段回落; 未用法术回合结束丢弃
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_trinkets2 import (
    ComfyCoffinGreaterScript,
    ComfyCoffinScript,
    StaffOfTheScourgeScript,
    WickedTomeGreaterScript,
    WickedTomeScript,
)
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
TYPO_LESS = "BG27_002"        # Oozeling Gladiator 2/2 —— 无类型
TYPO_LESS_B = "BG24_715"      # Patient Scout 1/1 —— 无类型
MURLOC = "BG22_202"           # Tad 2/2 —— Murloc（无死亡效果）
UNDEAD = "BG25_008"           # Eternal Knight 4/2 —— Undead（无 Reborn）
DRAGON = "BG26_963"           # Electric Synthesizer 3/4 —— Dragon
ELEMENTAL_A = "BG31_816"      # Fire Baller 4/3 —— Elemental（仅 on_sell）
ELEMENTAL_B = "BG31_818"      # Snow Baller 3/4 —— Elemental（仅 on_sell）
POOL_SPELL = "BG28_800"       # Careful Investment（酒馆法术，无目标，不动场面）

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 60):
    # 无被动英雄（TEST_H_* 无 hero power 定义）——排除英雄被动对战斗/
    # 事件的干扰，保证断言只反映被测饰品（Deathwing 等 SoC 被动会改
    # 攻击力，曾掩盖真实数值）
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def buy_trinket(game, hero, tid):
    """真实购买接线: create_entity + hero.trinkets + on_bind(ctx=hero)，
    与 game._offer_trinkets 的 resolve 路径一致。"""
    e = game.create_entity(tid, controller=hero)
    hero.trinkets.append(e)
    game.run_script_hook(e, "on_bind", ctx={"hero": hero})
    return e


def board_stats(minions):
    return sorted((m.atk, m.max_health) for m in minions)


class TestRegistry(unittest.TestCase):
    IMPLEMENTED = (
        "BG30_MagicItem_847", "BG30_MagicItem_403",
        "BG30_MagicItem_414", "BG30_MagicItem_414t",
        "BG30_MagicItem_437", "BG30_MagicItem_542",
        "BG30_MagicItem_427", "BG30_MagicItem_427t",
        "BG30_MagicItem_900", "BG30_MagicItem_900t",
        "BG30_MagicItem_970", "BG30_MagicItem_970t",
        "BG30_MagicItem_925", "BG32_MagicItem_270",
        "BG32_MagicItem_270t", "BG30_MagicItem_544",
        "BG30_MagicItem_544t", "BG30_MagicItem_547",
        "BG30_MagicItem_547t", "BG30_MagicItem_714",
        "BG30_MagicItem_714t",          # Harvested Pearl（Spellcraft token）
    )

    def test_all_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)
        self.assertEqual(len(self.IMPLEMENTED), 21)

    def test_avenge_thresholds_match_data_or_text(self):
        db = get_db()
        self.assertEqual(StaffOfTheScourgeScript.avenge_threshold, 5)
        self.assertIn("Avenge (5)", db.get("BG30_MagicItem_437").text)
        self.assertEqual(WickedTomeScript.avenge_threshold, 3)
        self.assertIn("Avenge (3)", db.get("BG32_MagicItem_270").text)
        # 270t 阈值来自模板参数 {0}——类属性必须与 CardDef.num(0) 一致
        self.assertEqual(WickedTomeGreaterScript.avenge_threshold,
                         db.get("BG32_MagicItem_270t").num(0))


class TestGoblinWallet(unittest.TestCase):
    TID = "BG30_MagicItem_847"

    def test_eot_raises_income_cap_used_by_recruit_gold(self):
        g = make_game(seed=101)
        a, b = g.heroes
        self.assertEqual(a.income_cap, 10)
        t = buy_trinket(g, a, self.TID)

        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(a.get(GameTag.INCOME_CAP_BONUS), 1)
        self.assertEqual(a.income_cap, 11)

        # 真实读取点: 基础收入按 income_cap 封顶（g.turn 20 → 3+19=22 > 11）
        g.turn = 20
        g._begin_recruit_for(a)
        self.assertEqual(a.gold, 11)

        # owner 隔离: 对手 hero 不受影响
        self.assertEqual(b.income_cap, 10)
        self.assertEqual(b.get(GameTag.INCOME_CAP_BONUS, 0), 0)

    def test_repeats_every_turn(self):
        g = make_game(seed=102)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        for _ in range(3):
            g.run_script_hook(t, "end_of_turn")
        self.assertEqual(a.income_cap, 13)


class TestIronforgeAnvil(unittest.TestCase):
    TID = "BG30_MagicItem_403"

    def test_soc_triples_typeless_only(self):
        g = make_game(seed=103)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        # 37.0（255130）把 BG27_002 Oozeling Gladiator 重新归为 ABERRATION
        # ——不再是无类型卡。用引擎构造的无类型随从（不受卡池轮换影响）:
        typeless = Minion("TEST_TYPO", "Typeless", atk=2, health=2)
        murloc = g.create_minion(MURLOC, controller=a)          # 2/2
        g.summon(a, typeless, 0)
        g.summon(a, murloc, 1)
        g.run_actions(Buff(typeless, atk=1, health=2))          # 3/4 → ×3 = 9/12

        g.run_script_hook(t, "start_of_combat")

        self.assertEqual((typeless.atk, typeless.max_health), (9, 12))
        self.assertEqual((murloc.atk, murloc.max_health), (2, 2))

    def test_soc_buff_reverts_after_real_combat(self):
        g = make_game(seed=104)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        # 同上: 无类型身份必须来自引擎构造（BG27_002 已是 ABERRATION）
        m = Minion("TEST_TYPO", "Typeless", atk=2, health=2)
        g.summon(a, m, 0)
        enemy = g.create_minion(MURLOC, controller=b)
        g.summon(b, enemy, 0)

        g.run_combat(a, b)

        # RULES §3.5: 战斗阶段 buff 战后消失
        self.assertEqual((m.atk, m.max_health), (2, 2))


class TestKodoLeatherPouch(unittest.TestCase):
    TID = "BG30_MagicItem_414"
    TID_G = "BG30_MagicItem_414t"

    def _setup(self, g, a, tid):
        buy_trinket(g, a, tid)
        ms = [g.create_minion(MURLOC, controller=a) for _ in range(3)]
        for i, m in enumerate(ms):
            g.summon(a, m, i)
        return ms

    def _buy_minion(self, g, a):
        buy = g.create_minion("BG25_806", controller=a)
        buy.zone = Zone.TAVERN
        a.tavern.append(buy)
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, buy))

    def _buy_spell(self, g, a):
        spell = g.create_spell(POOL_SPELL, controller=a)
        spell.zone = Zone.TAVERN
        a.tavern.append(spell)
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, spell))

    def test_buy_minion_buffs_exactly_two(self):
        g = make_game(seed=105)
        a, b = g.heroes
        ms = self._setup(g, a, self.TID)
        self._buy_minion(g, a)
        self.assertEqual(board_stats(ms), [(2, 2), (4, 3), (4, 3)])
        # 总量证明: 恰好两份 +2/+1
        self.assertEqual(sum(m.atk for m in ms), 2 * 3 + 2 * 2)
        self.assertEqual(sum(m.max_health for m in ms), 2 * 3 + 2 * 1)

    def test_buy_tavern_spell_also_triggers(self):
        g = make_game(seed=106)
        a = g.heroes[0]
        ms = self._setup(g, a, self.TID)
        self._buy_spell(g, a)
        self.assertEqual(board_stats(ms), [(2, 2), (4, 3), (4, 3)])

    def test_opponent_purchase_does_not_trigger(self):
        g = make_game(seed=107)
        a, b = g.heroes
        ms = self._setup(g, a, self.TID)
        # 对手买随从（b 的 tavern）
        buy = g.create_minion("BG25_806", controller=b)
        buy.zone = Zone.TAVERN
        b.tavern.append(buy)
        b.gold = 10
        self.assertTrue(g.buy_from_tavern(b, buy))
        self.assertEqual(board_stats(ms), [(2, 2), (2, 2), (2, 2)])

    def test_greater_pouch_buffs_four_four(self):
        g = make_game(seed=108)
        a = g.heroes[0]
        ms = self._setup(g, a, self.TID_G)
        self._buy_minion(g, a)
        self.assertEqual(board_stats(ms), [(2, 2), (6, 6), (6, 6)])


class TestStaffOfTheScourge(unittest.TestCase):
    TID = "BG30_MagicItem_437"

    def _kill(self, g, a, hero=None):
        victim = g.create_minion(MURLOC, controller=hero or a)
        g.summon(hero or a, victim)
        victim.health = 0
        # Avenge 仅战斗内计数（RULES §6.11）
        prev = g.in_combat
        g.in_combat = True
        try:
            g._process_single_death(victim)
        finally:
            g.in_combat = prev

    def test_fifth_friendly_death_grants_reborn_and_resets(self):
        g = make_game(seed=109)
        a, b = g.heroes
        t = buy_trinket(g, a, self.TID)
        undead = g.create_minion(UNDEAD, controller=a)
        g.summon(a, undead, 0)

        for _ in range(4):
            self._kill(g, a)
        self.assertFalse(undead.has(GameTag.REBORN))
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 4)

        self._kill(g, a)                       # 第 5 次 → 触发
        self.assertTrue(undead.has(GameTag.REBORN))
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 0)

        # 计数清零后重新累积: 第 6-9 次不触发（无状态残留）
        undead.clear(GameTag.REBORN)
        for _ in range(4):
            self._kill(g, a)
        self.assertFalse(undead.has(GameTag.REBORN))
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 4)

    def test_no_undead_whiffs(self):
        g = make_game(seed=110)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        murloc = g.create_minion(MURLOC, controller=a)
        g.summon(a, murloc, 0)
        for _ in range(5):
            self._kill(g, a)
        self.assertFalse(murloc.has(GameTag.REBORN))
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 0)

    def test_opponent_deaths_do_not_count(self):
        g = make_game(seed=111)
        a, b = g.heroes
        t = buy_trinket(g, a, self.TID)
        undead = g.create_minion(UNDEAD, controller=a)
        g.summon(a, undead, 0)
        for _ in range(5):
            self._kill(g, a, hero=b)           # 对手随从死亡
        self.assertFalse(undead.has(GameTag.REBORN))
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 0)


class TestEmeraldDreamcatcher(unittest.TestCase):
    TID = "BG30_MagicItem_542"

    def test_sets_dragon_attack_to_warband_highest(self):
        g = make_game(seed=112)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        dragon = g.create_minion(DRAGON, controller=a)        # 3/4
        murloc = g.create_minion(MURLOC, controller=a)         # 2/2
        g.summon(a, dragon, 0)
        g.summon(a, murloc, 1)
        g.run_actions(Buff(murloc, atk=6, health=0))           # 8/2 → 战团最高

        g.run_script_hook(t, "start_of_combat")

        self.assertEqual(dragon.atk, 8)
        self.assertEqual(dragon.max_health, 4)                 # 只改攻击力
        self.assertEqual((murloc.atk, murloc.max_health), (8, 2))

    def test_already_highest_dragon_unchanged(self):
        g = make_game(seed=113)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        dragon = g.create_minion(DRAGON, controller=a)
        g.summon(a, dragon, 0)
        g.run_actions(Buff(dragon, atk=5, health=0))           # 8/4 自身最高
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(dragon.atk, 8)

    def test_empty_board_whiffs(self):
        g = make_game(seed=114)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        self.assertIsNone(g.run_script_hook(t, "start_of_combat"))


class TestTigerCarving(unittest.TestCase):
    TID = "BG30_MagicItem_427"
    TID_G = "BG30_MagicItem_427t"

    def test_recruit_damage_buffs_another_only(self):
        g = make_game(seed=115)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        victim = g.create_minion(MURLOC, controller=a)
        other = g.create_minion(MURLOC, controller=a)
        g.summon(a, victim, 0)
        g.summon(a, other, 1)

        g.events.fire(g, "damage", minion=victim, amount=1, source=None)
        self.assertEqual((victim.atk, victim.max_health), (2, 2))
        self.assertEqual((other.atk, other.max_health),
                         (2 + d.num(0), 2 + d.num(1)))

    def test_greater_carving_values(self):
        g = make_game(seed=116)
        a = g.heroes[0]
        d = get_db().get(self.TID_G)
        buy_trinket(g, a, self.TID_G)
        victim = g.create_minion(MURLOC, controller=a)
        other = g.create_minion(MURLOC, controller=a)
        g.summon(a, victim, 0)
        g.summon(a, other, 1)
        g.events.fire(g, "damage", minion=victim, amount=2, source=None)
        self.assertEqual((other.atk, other.max_health),
                         (2 + d.num(0), 2 + d.num(1)))
        self.assertEqual((victim.atk, victim.max_health), (2, 2))

    def test_shield_zero_damage_does_not_trigger(self):
        g = make_game(seed=117)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        victim = g.create_minion(MURLOC, controller=a)
        other = g.create_minion(MURLOC, controller=a)
        g.summon(a, victim, 0)
        g.summon(a, other, 1)
        g.events.fire(g, "damage", minion=victim, amount=0, source=None)
        self.assertEqual((other.atk, other.max_health), (2, 2))

    def test_opponent_minion_damage_does_not_trigger(self):
        g = make_game(seed=118)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        own = g.create_minion(MURLOC, controller=a)
        g.summon(a, own, 0)
        enemy = g.create_minion(MURLOC, controller=b)
        g.summon(b, enemy, 0)
        g.events.fire(g, "damage", minion=enemy, amount=3, source=None)
        self.assertEqual((own.atk, own.max_health), (2, 2))

    def test_combat_grant_persists_after_snapshot_restore(self):
        """真 end_recruit_phase（run_combat + COMBAT_END）: 战斗内受伤触发
        → 战后快照回滚 → COMBAT_END 重放为永久（"permanently"）。"""
        g = make_game(seed=119)
        a, b = g.heroes
        d = get_db().get(self.TID)
        atk, hp = d.num(0), d.num(1)
        buy_trinket(g, a, self.TID)
        m1 = g.create_minion(MURLOC, controller=a)             # 2/2
        m2 = g.create_minion(MURLOC, controller=a)             # 2/2
        g.summon(a, m1, 0)
        g.summon(a, m2, 1)
        big = g.create_minion(MURLOC, controller=b)            # 2/2 → 5/20
        g.run_actions(Buff(big, atk=3, health=18))
        g.summon(b, big, 0)

        g.end_recruit_phase()

        # 受伤者是先死的那个 → 另一个获一份永久 +atk/+hp; 之后受伤者
        # 是最后一个友方 → 落空。恰好一份永久增益。
        self.assertEqual(board_stats(a.board),
                         sorted([(2, 2), (2 + atk, 2 + hp)]))

    def test_persist_minion_not_double_counted(self):
        """Tarecgosa（PERSIST_COMBAT_CHANGES）已由引擎持久化战斗增益 →
        Tiger 的 COMBAT_END 重放必须跳过（否则同一份增益双计）。"""
        g = make_game(seed=147)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        victim = g.create_minion(MURLOC, controller=a)          # 2/2
        tarec = g.create_minion("BG21_015", controller=a)       # 4/4 Dragon
        g.summon(a, victim, 0)
        g.summon(a, tarec, 1)                                   # on_summon → PERSIST
        self.assertTrue(tarec.has(GameTag.PERSIST_COMBAT_CHANGES))
        big = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(big, atk=3, health=18))
        g.summon(b, big, 0)

        g.end_recruit_phase()

        self.assertEqual((tarec.atk, tarec.max_health),
                         (4 + d.num(0), 4 + d.num(1)))

    def test_poet_adjacent_dragon_not_double_counted(self):
        """相邻 Persistent Poet 的龙已由引擎 poet_persist 保留战斗增益 →
        重放跳过（否则双计）。"""
        g = make_game(seed=148)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        poet = g.create_minion("BG29_813", controller=a)        # 2/3 Poet
        poet.clear(GameTag.DIVINE_SHIELD)   # 隔离: 让 Poet 首次受伤即死
        dragon = g.create_minion(DRAGON, controller=a)          # 3/4 Dragon
        g.summon(a, poet, 0)
        g.summon(a, dragon, 1)
        self.assertTrue(poet.has(GameTag.ADJACENT_PERSIST_SOURCE))
        big = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(big, atk=3, health=18))
        g.summon(b, big, 0)

        g.end_recruit_phase()

        self.assertEqual((dragon.atk, dragon.max_health),
                         (3 + d.num(0), 4 + d.num(1)))


class TestDragonwingGlider(unittest.TestCase):
    TID = "BG30_MagicItem_900"
    TID_G = "BG30_MagicItem_900t"

    def test_play_minion_buffs_random_dragon(self):
        g = make_game(seed=120)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        dragon = g.create_minion(DRAGON, controller=a)         # 3/4
        g.summon(a, dragon, 0)
        card = g.create_minion(MURLOC, controller=a)
        a.add_to_hand(card)
        self.assertTrue(g.play_minion(a, card))
        self.assertEqual((dragon.atk, dragon.max_health),
                         (3 + d.num(0), 4 + d.num(1)))

    def test_play_tavern_spell_also_triggers(self):
        g = make_game(seed=121)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        dragon = g.create_minion(DRAGON, controller=a)
        g.summon(a, dragon, 0)
        spell = g.create_spell(POOL_SPELL, controller=a)
        a.add_to_hand(spell)
        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual((dragon.atk, dragon.max_health),
                         (3 + d.num(0), 4 + d.num(1)))

    def test_no_dragon_whiffs(self):
        g = make_game(seed=122)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        card = g.create_minion(MURLOC, controller=a)
        a.add_to_hand(card)
        self.assertTrue(g.play_minion(a, card))
        self.assertEqual((card.atk, card.max_health), (2, 2))

    def test_opponent_play_does_not_trigger(self):
        g = make_game(seed=123)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        dragon = g.create_minion(DRAGON, controller=a)
        g.summon(a, dragon, 0)
        card = g.create_minion(MURLOC, controller=b)
        b.add_to_hand(card)
        self.assertTrue(g.play_minion(b, card))
        self.assertEqual((dragon.atk, dragon.max_health), (3, 4))

    def test_greater_glider_values(self):
        g = make_game(seed=124)
        a = g.heroes[0]
        d = get_db().get(self.TID_G)
        buy_trinket(g, a, self.TID_G)
        dragon = g.create_minion(DRAGON, controller=a)
        g.summon(a, dragon, 0)
        card = g.create_minion(MURLOC, controller=a)
        a.add_to_hand(card)
        self.assertTrue(g.play_minion(a, card))
        self.assertEqual((dragon.atk, dragon.max_health),
                         (3 + d.num(0), 4 + d.num(1)))
        self.assertNotEqual(d.num(0), get_db().get(self.TID).num(0))


class TestValorousMedallion(unittest.TestCase):
    TID = "BG30_MagicItem_970"
    TID_G = "BG30_MagicItem_970t"

    def test_soc_buffs_all_minions(self):
        g = make_game(seed=125)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        m1 = g.create_minion(MURLOC, controller=a)
        m2 = g.create_minion(TYPO_LESS_B, controller=a)
        g.summon(a, m1, 0)
        g.summon(a, m2, 1)
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(board_stats((m1, m2)), [(3, 3), (4, 4)])

    def test_combat_buff_reverts(self):
        g = make_game(seed=126)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        m = g.create_minion(MURLOC, controller=a)
        g.summon(a, m, 0)
        enemy = g.create_minion(TYPO_LESS_B, controller=b)
        g.summon(b, enemy, 0)
        g.run_combat(a, b)
        self.assertEqual((m.atk, m.max_health), (2, 2))

    def test_greater_medallion_six_six(self):
        g = make_game(seed=127)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID_G)
        m = g.create_minion(MURLOC, controller=a)
        g.summon(a, m, 0)
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual((m.atk, m.max_health), (8, 8))


class TestCeremonialSword(unittest.TestCase):
    TID = "BG30_MagicItem_925"

    def test_attack_bonus_applies_before_damage_snapshot(self):
        g = make_game(seed=128)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        attacker = g.create_minion(MURLOC, controller=a)       # 2/2
        g.run_actions(Buff(attacker, atk=0, health=10))        # 2/12
        g.summon(a, attacker, 0)
        tank = g.create_minion(MURLOC, controller=b)           # 2/2
        g.run_actions(Buff(tank, atk=0, health=18))            # 2/20
        g.summon(b, tank, 0)

        CombatScheduler(g, a, b)._execute_attack(attacker, tank)

        self.assertEqual(attacker.atk, 6)                      # 2 + 4
        self.assertEqual(tank.health, 20 - 6)                  # 本击已含 +4
        self.assertEqual(attacker.health, 12 - 2)

    def test_opponent_attacker_not_buffed(self):
        g = make_game(seed=129)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        target = g.create_minion(MURLOC, controller=a)
        g.run_actions(Buff(target, atk=0, health=18))
        g.summon(a, target, 0)
        attacker = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(attacker, atk=0, health=10))
        g.summon(b, attacker, 0)
        CombatScheduler(g, b, a)._execute_attack(attacker, target)
        self.assertEqual(attacker.atk, 2)                      # 未获 +4
        self.assertEqual(target.health, 20 - 2)


class TestWickedTome(unittest.TestCase):
    TID = "BG32_MagicItem_270"
    TID_G = "BG32_MagicItem_270t"

    def _kill(self, g, a):
        m = g.create_minion(MURLOC, controller=a)
        g.summon(a, m)
        m.health = 0
        # Avenge 仅战斗内计数（RULES §6.11）
        prev = g.in_combat
        g.in_combat = True
        try:
            g._process_single_death(m)
        finally:
            g.in_combat = prev

    def test_avenge_three_writes_extra_attack_and_consumes(self):
        g = make_game(seed=130)
        a, b = g.heroes
        t = buy_trinket(g, a, self.TID)
        self._kill(g, a)
        self._kill(g, a)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 2)

        self._kill(g, a)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 1)
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 0)

        # 消费点: racefx.tavern_spell_buff 出口实际多给 +1 攻
        target = g.create_minion(MURLOC, controller=a)
        g.summon(a, target, 0)
        g.run_actions(tavern_spell_buff(target, 2, 2))
        self.assertEqual((target.atk, target.max_health), (2 + 3, 2 + 2))

        # owner 隔离: 对手 tag 不变
        self.assertEqual(b.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)

    def test_accumulates_across_triggers(self):
        g = make_game(seed=131)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        for _ in range(6):
            self._kill(g, a)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 2)

    def test_greater_tome_adds_attack_and_health(self):
        g = make_game(seed=132)
        a, b = g.heroes
        d = get_db().get(self.TID_G)
        t = buy_trinket(g, a, self.TID_G)
        for _ in range(d.num(0)):
            self._kill(g, a)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), d.num(1))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), d.num(2))
        self.assertEqual(t.get(GameTag.AVENGE_COUNTER, 0), 0)
        self.assertEqual(b.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)


class TestNomiSticker(unittest.TestCase):
    TID = "BG30_MagicItem_544"
    TID_G = "BG30_MagicItem_544t"

    def _tavern_pair(self, g, a):
        ele = g.create_minion(ELEMENTAL_A, controller=a)       # 4/3
        ele.zone = Zone.TAVERN
        a.tavern.append(ele)
        non = g.create_minion(MURLOC, controller=a)            # 2/2
        non.zone = Zone.TAVERN
        a.tavern.append(non)
        return ele, non

    def _play_elemental(self, g, a):
        card = g.create_minion(ELEMENTAL_B, controller=a)      # 3/4
        a.add_to_hand(card)
        self.assertTrue(g.play_minion(a, card))
        return card

    def test_play_elemental_buffs_tavern_elementals_now(self):
        g = make_game(seed=133)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        ele, non = self._tavern_pair(g, a)

        self._play_elemental(g, a)

        self.assertEqual((ele.atk, ele.max_health),
                         (4 + d.num(0), 3 + d.num(1)))
        self.assertEqual((non.atk, non.max_health), (2, 2))
        # 持久面登记一条（"this game"）
        self.assertEqual(len(a.tavern_buffs), 1)
        self.assertEqual((a.tavern_buffs[0].atk, a.tavern_buffs[0].health),
                         (d.num(0), d.num(1)))

    def test_persistent_aura_applies_to_new_tavern_elementals(self):
        g = make_game(seed=134)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        self._play_elemental(g, a)                             # +num 光环一次

        a.set(GameTag.TAVERN_TIER, 4)
        g.refresh_tavern(a, auto=True, races={Race.ELEMENTAL})
        drawn = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(drawn)
        for m in drawn:
            base = get_db().get(m.card_id)
            # 多类型身份: 元素过滤可命中"主类型非元素但带 ELEMENTAL 身份"的
            # 双类型随从（如 BG34_500 Flaming Enforcer = DEMON+ELEMENTAL）,
            # 因此用 has_race（类型身份集合）而非单值 m.race。
            self.assertTrue(m.has_race(Race.ELEMENTAL), m.card_id)
            self.assertEqual((m.atk, m.max_health),
                             (base.atk + d.num(0), base.health + d.num(1)))

    def test_non_elemental_play_does_not_trigger(self):
        g = make_game(seed=135)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        ele, _ = self._tavern_pair(g, a)
        card = g.create_minion(MURLOC, controller=a)
        a.add_to_hand(card)
        self.assertTrue(g.play_minion(a, card))
        self.assertEqual((ele.atk, ele.max_health), (4, 3))
        self.assertEqual(getattr(a, "tavern_buffs", []), [])

    def test_opponent_elemental_play_does_not_trigger(self):
        g = make_game(seed=136)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        ele, _ = self._tavern_pair(g, a)
        card = g.create_minion(ELEMENTAL_B, controller=b)
        b.add_to_hand(card)
        self.assertTrue(g.play_minion(b, card))
        self.assertEqual((ele.atk, ele.max_health), (4, 3))

    def test_greater_sticker_values(self):
        g = make_game(seed=137)
        a = g.heroes[0]
        d = get_db().get(self.TID_G)
        buy_trinket(g, a, self.TID_G)
        ele, _ = self._tavern_pair(g, a)
        self._play_elemental(g, a)
        self.assertEqual((ele.atk, ele.max_health),
                         (4 + d.num(0), 3 + d.num(1)))


class TestComfyCoffin(unittest.TestCase):
    TID = "BG30_MagicItem_547"
    TID_G = "BG30_MagicItem_547t"

    def _cast_tavern_spell(self, g, hero):
        spell = g.create_spell(POOL_SPELL, controller=hero)
        hero.add_to_hand(spell)
        self.assertTrue(g.play_spell(hero, spell))

    def test_tavern_spell_stacks_undead_attack_aura(self):
        g = make_game(seed=138)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        undead = g.create_minion(UNDEAD, controller=a)         # 4/2
        g.summon(a, undead, 0)

        self._cast_tavern_spell(g, a)

        self.assertEqual(getattr(a, "race_auras", {}).get(Race.UNDEAD), (1, 0))
        self.assertEqual(undead.atk, 5)                        # 4 + 1（光环）
        self.assertEqual(undead.max_health, 2)

        # 叠加: 第二次施放 → +2，且"wherever they are"覆盖新入场者
        self._cast_tavern_spell(g, a)
        self.assertEqual(getattr(a, "race_auras", {})[Race.UNDEAD], (2, 0))
        newcomer = g.create_minion(UNDEAD, controller=a)
        g.summon(a, newcomer, 1)
        self.assertEqual(newcomer.atk, 6)                      # 4 + 2

    def test_non_undead_unaffected(self):
        g = make_game(seed=139)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        murloc = g.create_minion(MURLOC, controller=a)
        g.summon(a, murloc, 0)
        self._cast_tavern_spell(g, a)
        self.assertEqual(murloc.atk, 2)

    def test_opponent_cast_does_not_trigger(self):
        g = make_game(seed=140)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        undead = g.create_minion(UNDEAD, controller=a)
        g.summon(a, undead, 0)
        self._cast_tavern_spell(g, b)
        self.assertEqual(getattr(a, "race_auras", {}), {})
        self.assertEqual(undead.atk, 4)

    def test_greater_coffin_two_attack(self):
        g = make_game(seed=141)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID_G)
        undead = g.create_minion(UNDEAD, controller=a)
        g.summon(a, undead, 0)
        self._cast_tavern_spell(g, a)
        self.assertEqual(getattr(a, "race_auras", {})[Race.UNDEAD], (2, 0))
        self.assertEqual(undead.atk, 6)


class TestPreciousPearl(unittest.TestCase):
    TID = "BG30_MagicItem_714"
    SPELL = "BG30_MagicItem_714t"

    def test_bind_grants_spellcraft_spell_with_tag(self):
        g = make_game(seed=142)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        got = [e for e in a.hand if e.card_id == self.SPELL]
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].has(GameTag.SPELLCRAFT))
        self.assertEqual([e.card_id for e in b.hand], [])

    def test_spell_discarded_at_eot_and_regenerated(self):
        g = make_game(seed=143)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        self.assertEqual(
            [e.card_id for e in a.hand].count(self.SPELL), 1)
        g.end_recruit_phase()                                  # EoT 丢弃 + 次回合再生成
        self.assertEqual(
            [e.card_id for e in a.hand].count(self.SPELL), 1)

    def test_cast_buffs_and_expires_next_recruit_phase(self):
        g = make_game(seed=144)
        a = g.heroes[0]
        d = get_db().get(self.SPELL)
        buy_trinket(g, a, self.TID)
        spell = next(e for e in a.hand if e.card_id == self.SPELL)
        target = g.create_minion(MURLOC, controller=a)
        g.summon(a, target, 0)

        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.max_health), (32, 32))
        self.assertTrue(spell.has(GameTag.SPELLCRAFT))
        self.assertIsNotNone(d)                                # 数据存在（无模板参数）

        g._begin_recruit_for(a)                                # 下一招募阶段开始
        self.assertEqual((target.atk, target.max_health), (2, 2))

    def test_needs_target_creates_pending_choice(self):
        g = make_game(seed=145)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        spell = next(e for e in a.hand if e.card_id == self.SPELL)
        target = g.create_minion(MURLOC, controller=a)
        g.summon(a, target, 0)

        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual(len(g.pending_choices), 1)
        self.assertEqual(g.pending_choices[0].kind, "spell_target")
        g.pending_choices.pop(0).choose(0)                     # 选定唯一候选
        self.assertEqual((target.atk, target.max_health), (32, 32))

    def test_no_target_available_whiffs_but_spell_consumed(self):
        g = make_game(seed=146)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        spell = next(e for e in a.hand if e.card_id == self.SPELL)
        self.assertTrue(g.play_spell(a, spell))                # 无候选 → 落空
        self.assertEqual(g.pending_choices, [])
        self.assertNotIn(spell, a.hand)


if __name__ == "__main__":
    unittest.main()
