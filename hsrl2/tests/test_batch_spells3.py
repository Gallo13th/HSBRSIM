"""批次 spells3 语义测试（作业单 2026-08-21，13 张池法术）。

覆盖: BG28_882 Contracted Corpse / BG28_884 Overconfidence / BG28_886
Staff of Enrichment / BG28_888 Misplaced Tea Set / BG28_897 Tavern Dish
Banana / BG28_966 Them Apples / BG28_GIL_836 Hired Headhunter /
BG30_804 Robust Evolution / BG31_819 Temperature Shift / BG31_880
Alliance Flag。
OUT_OF_SCOPE（Duos-only）: BG31_242 / BG31_243 / BG31_244 —— 不注册
即正确状态（守护测试）。

驱动: game.play_spell(hero, spell, target=...)（定向法术不传 target 走
PendingChoice(kind="spell_target")）; Overconfidence 经完整回合周期
end_recruit_phase → 战斗 → 下一招募阶段。数值期望一律 CardDef.num()
（无模板参数的卡注明字面量来源）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.entity import Buff
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
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


def pool_def(tier: int) -> "CardDef":
    """确定性取一张指定 tier 的池随从定义（id 字典序首个）。"""
    for d in sorted(get_db().pool_minions(), key=lambda x: x.id):
        if d.tech_level == tier:
            return d
    raise AssertionError(f"no pool minion of tier {tier}")


class TestRegistryState(unittest.TestCase):
    """批次注册面: 10 卡 OK; 3 张 Duos-only OUT_OF_SCOPE 不注册。"""

    def test_all_ok_cards_registered(self):
        for cid in ("BG28_882", "BG28_884", "BG28_886", "BG28_888",
                    "BG28_897", "BG28_966", "BG28_GIL_836", "BG30_804",
                    "BG31_819", "BG31_880"):
            self.assertIn(cid, REGISTRY)

    def test_duos_only_cards_not_registered(self):
        # Bargain Bundle / Portal in a Fountain / Portal in a Crystal
        # —— wiki 核实 "available in Duos games only" → OUT_OF_SCOPE
        for cid in ("BG31_242", "BG31_243", "BG31_244"):
            self.assertNotIn(cid, REGISTRY)


class TestContractedCorpse(unittest.TestCase):
    """BG28_882 — Discover a Deathrattle minion."""

    def test_discover_options_all_deathrattle_and_pool_acquired(self):
        game = make_game(seed=50)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_882")
        self.assertTrue(game.play_spell(a, s))
        pc = game.pending_choices[-1]
        self.assertEqual(pc.kind, "discover_minion")
        self.assertTrue(pc.options)
        for cid in pc.options:
            self.assertIn("deathrattle", get_db().get(cid).keywords)
        pick = pc.options[0]
        before = game.minion_pool.available(pick)
        pc.choose(0)
        self.assertEqual(a.hand[-1].card_id, pick)
        self.assertEqual(game.minion_pool.available(pick), before - 1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 1)


class TestOverconfidence(unittest.TestCase):
    """BG28_884 — If you win your next combat, gain 3 Gold. If you tie,
    gain 1.（win=3 / tie=1 文本字面量）"""

    def _play(self, game, hero):
        s = add_spell(game, hero, "BG28_884")
        self.assertTrue(game.play_spell(hero, s))

    def test_win_gains_3_on_base_income_next_turn(self):
        game = make_game(seed=51)
        game.start_game()
        a, b = game.heroes
        self._play(game, a)
        put(game, make_minion("W", 1, 1), a)          # a 有随从，b 空板
        game.end_recruit_phase()
        self.assertEqual(game.turn, 2)
        self.assertEqual(a.gold, C.gold_base_income(2) + 3)

    def test_win_consumed_no_repeat_next_combat(self):
        game = make_game(seed=52)
        game.start_game()
        a = game.heroes[0]
        self._play(game, a)
        put(game, make_minion("W", 1, 1), a)
        game.end_recruit_phase()                       # turn 2: +3 已领
        self.assertEqual(a.gold, C.gold_base_income(2) + 3)
        game.end_recruit_phase()                       # 再胜——监听器已消耗
        self.assertEqual(a.gold, C.gold_base_income(3))

    def test_tie_gains_1(self):
        game = make_game(seed=53)
        game.start_game()
        a = game.heroes[0]
        self._play(game, a)                            # 双方空板 → 平局
        game.end_recruit_phase()
        self.assertEqual(a.gold, C.gold_base_income(2) + 1)

    def test_loss_gains_nothing(self):
        game = make_game(seed=54)
        game.start_game()
        a, b = game.heroes
        self._play(game, a)
        put(game, make_minion("L", 1, 1), b)           # b 胜，a 败
        game.end_recruit_phase()
        self.assertEqual(a.gold, C.gold_base_income(2))

    def test_other_players_combat_does_not_consume(self):
        game = make_game(seed=55)
        game.start_game()
        a = game.heroes[0]
        self._play(game, a)
        # 他人战斗（a 未参战）—— condition 不满足，once 保留
        other_a, other_b = make_hero("X"), make_hero("Y")
        other_a.game = game
        other_b.game = game

        class _R:   # 仅事件形状（winner/loser）
            winner = other_a
            loser = other_b
        game.events.fire(game, "combat_end", hero_a=other_a,
                         hero_b=other_b, result=_R())
        self.assertTrue(any(
            l.owner is a for l in game.events._listeners.get("combat_end", [])))


class TestStaffOfEnrichment(unittest.TestCase):
    """BG28_886 — Give minions in the Tavern +{0}/+{1} this game."""

    def test_current_tavern_buffed_and_persistent(self):
        game = make_game(seed=56)
        game.start_game()
        a = game.heroes[0]
        d = get_db().get("BG28_886")
        tavern_minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(tavern_minions)
        s = add_spell(game, a, "BG28_886")
        self.assertTrue(game.play_spell(a, s))
        for m in tavern_minions:
            base = get_db().get(m.card_id)
            self.assertEqual(m.atk, base.atk + d.num(0))
            self.assertEqual(m.max_health, base.health + d.num(1))
        # 持久登记存在
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 1)

    def test_refresh_applies_to_new_minions_and_extra_snapshot(self):
        game = make_game(seed=57)
        game.start_game()
        a = game.heroes[0]
        d = get_db().get("BG28_886")
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 1)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 1)
        s = add_spell(game, a, "BG28_886")
        self.assertTrue(game.play_spell(a, s))
        a.gold = 10
        game.refresh_tavern(a)
        new_minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(new_minions)
        for m in new_minions:
            base = get_db().get(m.card_id)
            # 施放时快照: num + extra（两面一致）
            self.assertEqual(m.atk, base.atk + d.num(0) + 1)
            self.assertEqual(m.max_health, base.health + d.num(1) + 1)


class TestMisplacedTeaSet(unittest.TestCase):
    """BG28_888 — Give a friendly minion of each type +{0}/+{1}."""

    def test_two_same_race_one_pick_per_unique_race(self):
        game = make_game(seed=58)
        a = game.heroes[0]
        d = get_db().get("BG28_888")
        m1 = put(game, make_minion("M1", 1, 1, race=Race.MURLOC), a)
        m2 = put(game, make_minion("M2", 1, 1, race=Race.MURLOC), a)
        m3 = put(game, make_minion("M3", 1, 1, race=Race.MECH), a)
        s = add_spell(game, a, "BG28_888")
        self.assertTrue(game.play_spell(a, s))
        # 10 族各族独立选取: MURLOC 二选一 + MECH + 其余 8 族无候选
        # → 恰 2 次 buff（每次 num(0)/num(1)）
        self.assertEqual(len(game.pending_choices), 0)
        total_atk = (m1.atk - 1) + (m2.atk - 1) + (m3.atk - 1)
        total_hp = ((m1.max_health - 1) + (m2.max_health - 1)
                    + (m3.max_health - 1))
        self.assertEqual(total_atk, 2 * d.num(0))
        self.assertEqual(total_hp, 2 * d.num(1))
        buffed = [m for m in (m1, m2, m3)
                  if m.atk == 1 + d.num(0)]
        self.assertEqual(len(buffed), 2)   # MURLOC 二选一 + MECH
        self.assertIn(m3, buffed)

    def test_amalgam_counts_as_every_type(self):
        """Evidence: r/BobsTavern 1vkv7h6——每族独立选取，Amalgam 对
        每族合格且可被多族重复命中（2026-08-23 修正读法）。"""
        game = make_game(seed=59)
        a = game.heroes[0]
        d = get_db().get("BG28_888")
        am = put(game, make_minion("AM", 1, 1, race=Race.ALL), a)
        s = add_spell(game, a, "BG28_888")
        self.assertTrue(game.play_spell(a, s))
        # 单只 Amalgam = 每个种族的合格候选 → 10 份 buff
        self.assertEqual(am.atk, 1 + 10 * d.num(0))
        self.assertEqual(am.max_health, 1 + 10 * d.num(1))

    def test_amalgam_eligible_for_other_race_pick(self):
        game = make_game(seed=60)
        a = game.heroes[0]
        d = get_db().get("BG28_888")
        am = put(game, make_minion("AM", 1, 1, race=Race.ALL), a)
        dr = put(game, make_minion("DR", 1, 1, race=Race.DRAGON), a)
        s = add_spell(game, a, "BG28_888")
        self.assertTrue(game.play_spell(a, s))
        # 10 族: DRAGON 查询 → dr 或 am（随机）; 其余 9 族仅 am 合格
        self.assertEqual(am.atk + dr.atk, 2 + 10 * d.num(0))
        self.assertIn(dr.atk, (1, 1 + d.num(0)))


class TestTavernDishBanana(unittest.TestCase):
    """BG28_897 — Give a minion +{0}/+{1}（定向）。"""

    def test_targeted_buff_via_pending_choice_with_extra(self):
        game = make_game(seed=61)
        a = game.heroes[0]
        d = get_db().get("BG28_897")
        m = put(game, make_minion("T", 2, 3), a)
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 1)
        s = add_spell(game, a, "BG28_897")
        self.assertTrue(game.play_spell(a, s))       # 无 target → 选择
        pc = game.pending_choices[-1]
        self.assertEqual(pc.kind, "spell_target")
        self.assertEqual(pc.options, [m])
        pc.choose(0)
        self.assertEqual(m.atk, 2 + d.num(0) + 1)
        self.assertEqual(m.max_health, 3 + d.num(1))

    def test_empty_board_fizzles_but_consumes(self):
        game = make_game(seed=62)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_897")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 1)


class TestThemApples(unittest.TestCase):
    """BG28_966 — Give minions in the Tavern +{0}/+{1}（一次性）。"""

    def test_current_tavern_buffed_once_not_persistent(self):
        game = make_game(seed=63)
        game.start_game()
        a = game.heroes[0]
        d = get_db().get("BG28_966")
        tavern_minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(tavern_minions)
        s = add_spell(game, a, "BG28_966")
        self.assertTrue(game.play_spell(a, s))
        for m in tavern_minions:
            base = get_db().get(m.card_id)
            self.assertEqual(m.atk, base.atk + d.num(0))
            self.assertEqual(m.max_health, base.health + d.num(1))
        # 非持久: 刷新后新入馆不 buff
        self.assertEqual(getattr(a, "tavern_buffs", []), [])
        a.gold = 10
        game.refresh_tavern(a)
        new_minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(new_minions)
        for m in new_minions:
            base = get_db().get(m.card_id)
            self.assertEqual(m.atk, base.atk)
            self.assertEqual(m.max_health, base.health)


class TestHiredHeadhunter(unittest.TestCase):
    """BG28_GIL_836 — Discover a Battlecry minion."""

    def test_discover_options_all_battlecry(self):
        game = make_game(seed=64)
        a = game.heroes[0]
        s = add_spell(game, a, "BG28_GIL_836")
        self.assertTrue(game.play_spell(a, s))
        pc = game.pending_choices[-1]
        self.assertEqual(pc.kind, "discover_minion")
        self.assertTrue(pc.options)
        for cid in pc.options:
            self.assertIn("battlecry", get_db().get(cid).keywords)
        pick = pc.options[0]
        pc.choose(0)
        self.assertEqual(a.hand[-1].card_id, pick)


class TestRobustEvolution(unittest.TestCase):
    """BG30_804 — Choose a minion. Transform it into a random minion of a
    higher Tier（= 恰好 +1，多语言 locale 裁定）. It keeps its stats."""

    def test_transform_tier_plus_one_keeps_stats_and_acquires(self):
        game = make_game(seed=65)
        a = game.heroes[0]
        t1 = pool_def(1)
        target = game.create_minion(t1.id, controller=a)
        game.summon(a, target)
        target.add_buff(Buff(2, 3, source_id="test"))  # 旧值 = T1 卡 + 2/3
        old_atk, old_hp, old_max = target.atk, target.health, target.max_health
        tier2_avail = {cid: game.minion_pool.available(cid)
                       for cid in game.minion_pool.candidates(2, 2)}
        s = add_spell(game, a, "BG30_804")
        self.assertTrue(game.play_spell(a, s, target=target))
        new = a.board[0]
        self.assertIsNot(new, target)
        self.assertEqual(new.tech_level, 2)
        self.assertIn(new.card_id, tier2_avail)
        self.assertEqual(new.atk, old_atk)
        self.assertEqual(new.max_health, old_max)
        self.assertEqual(new.health, old_hp)
        self.assertEqual(game.minion_pool.available(new.card_id),
                         tier2_avail[new.card_id] - 1)

    def test_tier6_target_reaches_tier7(self):
        game = make_game(seed=66)
        a = game.heroes[0]
        t6 = pool_def(6)
        target = game.create_minion(t6.id, controller=a)
        game.summon(a, target)
        s = add_spell(game, a, "BG30_804")
        self.assertTrue(game.play_spell(a, s, target=target))
        self.assertEqual(a.board[0].tech_level, 7)

    def test_golden_target_golden_result_acquires_three(self):
        game = make_game(seed=67)
        a = game.heroes[0]
        t1 = pool_def(1)
        target = game.create_minion(t1.id, controller=a, golden=True)
        game.summon(a, target)
        tier2_avail = {cid: game.minion_pool.available(cid)
                       for cid in game.minion_pool.candidates(2, 2)}
        s = add_spell(game, a, "BG30_804")
        self.assertTrue(game.play_spell(a, s, target=target))
        new = a.board[0]
        self.assertTrue(new.is_golden)
        # Transform 金色结果以金色卡定义创建——池记账在基础卡上
        new_def = game.db.get(new.card_id)
        base_id = game.db.by_dbf(new_def.triple_base_id).id
        self.assertIn(base_id, tier2_avail)
        taken = min(3, tier2_avail[base_id])
        self.assertEqual(game.minion_pool.available(base_id),
                         tier2_avail[base_id] - taken)

    def test_empty_board_fizzles_but_consumes(self):
        game = make_game(seed=68)
        a = game.heroes[0]
        s = add_spell(game, a, "BG30_804")
        self.assertTrue(game.play_spell(a, s))       # 无候选 → 落空消耗
        self.assertEqual(len(a.board), 0)


class TestTemperatureShift(unittest.TestCase):
    """BG31_819 — Get a Fire Baller and a Snow Baller."""

    def test_gets_both_ballers_from_pool(self):
        game = make_game(seed=69)
        a = game.heroes[0]
        fire = "BG31_816"
        snow = "BG31_818"
        before = (game.minion_pool.available(fire),
                  game.minion_pool.available(snow))
        s = add_spell(game, a, "BG31_819")
        self.assertTrue(game.play_spell(a, s))
        got = [m.card_id for m in a.hand if isinstance(m, Minion)]
        self.assertEqual(sorted(got), sorted([fire, snow]))
        self.assertEqual(game.minion_pool.available(fire), before[0] - 1)
        self.assertEqual(game.minion_pool.available(snow), before[1] - 1)
        # 两卡自身脚本已注册（Improve 家族联动可用）
        self.assertIn(fire, REGISTRY)
        self.assertIn(snow, REGISTRY)


class TestAllianceFlag(unittest.TestCase):
    """BG31_880 — Choose One: Give a minion +{0}/+{1}; or +{2}/+{3}."""

    def _play_targeted(self, game, hero, m):
        s = add_spell(game, hero, "BG31_880")
        self.assertTrue(game.play_spell(hero, s, target=m))
        pc = game.pending_choices[-1]
        self.assertEqual(pc.kind, "choose_one")
        return pc

    def test_first_option_gives_num0_num1(self):
        game = make_game(seed=70)
        a = game.heroes[0]
        d = get_db().get("BG31_880")
        m = put(game, make_minion("F", 1, 1), a)
        pc = self._play_targeted(game, a, m)
        pc.choose(0)
        self.assertEqual(m.atk, 1 + d.num(0))
        self.assertEqual(m.max_health, 1 + d.num(1))

    def test_second_option_gives_num2_num3(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        d = get_db().get("BG31_880")
        m = put(game, make_minion("S", 1, 1), a)
        pc = self._play_targeted(game, a, m)
        pc.choose(1)
        self.assertEqual(m.atk, 1 + d.num(2))
        self.assertEqual(m.max_health, 1 + d.num(3))

    def test_no_target_no_branch_choice(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        s = add_spell(game, a, "BG31_880")
        self.assertTrue(game.play_spell(a, s))       # 空板 → 落空消耗
        self.assertEqual(len(game.pending_choices), 0)


if __name__ == "__main__":
    unittest.main()
