"""hsrl2/actions 动作包测试 — 每个 Action 的语义正例 + 池记账断言。

覆盖: Buff/GainKeyword/LoseKeyword/Transform/Summon/SummonPlainCopy/
GainGold/ScheduleNextTurn/Hit/GetRandomMinion/Discover。
池约束依据 RULES §2.3/§2.4/§3.3/§6.18。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import actions
from hsrl2.constants import HAND_SIZE, POOL_COPIES_BY_TIER, gold_base_income
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def pool_ids() -> list:
    return [d.id for d in get_db().pool_minions()]


def golden_t1_defs() -> list:
    return [d for d in get_db().pool_minions()
            if d.tech_level == 1 and get_db().golden_version(d) is not None]


class TestBuffAction(unittest.TestCase):
    """Buff: temporary buff 存在且 clear_temporary_buffs 后消失; 永久不受影响。"""

    def test_temporary_buff_added_and_cleared(self):
        game = make_game(seed=31)
        m = make_minion("Buffed", 1, 1)
        game.run_actions(actions.Buff(m, 2, 3, temporary=True))
        self.assertEqual(len(m.buffs), 1)
        self.assertTrue(m.buffs[0].temporary)
        self.assertEqual(m.atk, 3)
        self.assertEqual(m.health, 4)          # add_buff 同步加血
        m.clear_temporary_buffs()
        self.assertEqual(m.buffs, [])
        self.assertEqual(m.atk, 1)

    def test_permanent_buff_survives_temporary_clear(self):
        game = make_game(seed=32)
        m = make_minion("Keep", 2, 2)
        game.run_actions([actions.Buff(m, 1, 1),
                          actions.Buff(m, 5, 5, temporary=True)])
        m.clear_temporary_buffs()
        self.assertEqual(len(m.buffs), 1)
        self.assertEqual(m.atk, 3)


class TestKeywordActions(unittest.TestCase):
    """GainKeyword/LoseKeyword: tag 变化 + 事件触发。"""

    def test_gain_keyword_fires_event(self):
        game = make_game(seed=33)
        m = make_minion("Kw", 1, 1)
        game.summon(game.heroes[0], m)
        seen = []
        game.events.register(Listener(
            "keyword_gained", owner=m,
            callback=lambda g, **kw: seen.append((kw["minion"], kw["tag"]))))
        game.run_actions(actions.GainKeyword(m, GameTag.TAUNT))
        self.assertTrue(m.has(GameTag.TAUNT))
        self.assertEqual(seen, [(m, GameTag.TAUNT)])

    def test_lose_keyword_fires_event(self):
        game = make_game(seed=34)
        m = make_minion("Kw", 1, 1)
        m.set(GameTag.TAUNT, True)
        seen = []
        game.events.register(Listener(
            "keyword_lost", owner=m,
            callback=lambda g, **kw: seen.append((kw["minion"], kw["tag"]))))
        game.run_actions(actions.LoseKeyword(m, GameTag.TAUNT))
        self.assertFalse(m.has(GameTag.TAUNT))
        self.assertEqual(seen, [(m, GameTag.TAUNT)])

    def test_lose_divine_shield_fires_both_events(self):
        game = make_game(seed=35)
        m = make_minion("Shield", 1, 1)
        m.set(GameTag.DIVINE_SHIELD, True)
        lost, shield_lost = [], []
        game.events.register(Listener(
            "keyword_lost", owner=m,
            callback=lambda g, **kw: lost.append(kw["tag"])))
        game.events.register(Listener(
            "divine_shield_lost", owner=m,
            callback=lambda g, **kw: shield_lost.append(kw["minion"])))
        game.run_actions(actions.LoseKeyword(m, GameTag.DIVINE_SHIELD))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(lost, [GameTag.DIVINE_SHIELD])
        self.assertEqual(shield_lost, [m])

    def test_lose_taunt_does_not_fire_divine_shield_lost(self):
        game = make_game(seed=36)
        m = make_minion("Plain", 1, 1)
        m.set(GameTag.TAUNT, True)
        shield_lost = []
        game.events.register(Listener(
            "divine_shield_lost", owner=m,
            callback=lambda g, **kw: shield_lost.append(kw["minion"])))
        game.run_actions(actions.LoseKeyword(m, GameTag.TAUNT))
        self.assertEqual(shield_lost, [])


class TestTransform(unittest.TestCase):
    """Transform: 保留 buff/金色/位置; keep_buffs=False 清 buff; 旧实体移除。"""

    def test_transform_keeps_buffs_golden_position(self):
        game = make_game(seed=37)
        a = game.heroes[0]
        src, dst = golden_t1_defs()[:2]
        gdst = get_db().golden_version(dst)
        target = game.create_minion(src.id, controller=a, golden=True)
        blocker = make_minion("Blocker", 0, 5)
        game.summon(a, blocker)
        game.summon(a, target)
        game.run_actions(actions.Buff(target, 2, 3))
        events = []
        game.events.register(Listener(
            "transform", owner=a,
            callback=lambda g, **kw: events.append((kw["old"], kw["new"]))))
        game.run_actions(actions.Transform(target, dst.id))

        self.assertEqual(len(a.board), 2)
        new = a.board[1]
        self.assertIs(a.board[0], blocker)          # 位置保留: 仍在 index 1
        self.assertIsNot(new, target)
        self.assertEqual(new.card_id, gdst.id)      # 金色卡定义
        self.assertTrue(new.is_golden)
        self.assertEqual(new.atk, gdst.atk + 2)     # buff 转移
        self.assertEqual(new.health, gdst.health + 3)
        self.assertEqual(new.health, new.max_health)  # 重算不加血
        self.assertEqual(target.zone, Zone.REMOVED)
        self.assertNotIn(target, a.board)
        self.assertEqual(events, [(target, new)])

    def test_transform_without_buffs_is_plain(self):
        game = make_game(seed=38)
        a = game.heroes[0]
        src, dst = golden_t1_defs()[:2]
        gsrc = get_db().golden_version(src)
        target = game.create_minion(dst.id, controller=a, golden=True)
        game.summon(a, target)
        game.run_actions(actions.Buff(target, 4, 4))
        game.run_actions(actions.Transform(target, src.id, keep_buffs=False))
        new = a.board[0]
        self.assertEqual(new.buffs, [])
        self.assertTrue(new.is_golden)
        self.assertEqual(new.card_id, gsrc.id)
        self.assertEqual(new.atk, gsrc.atk)
        self.assertEqual(new.health, gsrc.health)

    def test_transform_unregisters_old_entity_listeners(self):
        game = make_game(seed=39)
        a = game.heroes[0]
        src, dst = golden_t1_defs()[:2]
        target = game.create_minion(src.id, controller=a)
        game.summon(a, target)
        hits = []
        game.events.register(Listener(
            "tavern_refresh", owner=target,
            callback=lambda g, **kw: hits.append(1)))
        game.run_actions(actions.Transform(target, dst.id))
        game.events.fire(game, "tavern_refresh")
        self.assertEqual(hits, [])                  # 光环生命周期终止


class TestSummonActions(unittest.TestCase):
    """Summon(token 不占池) / SummonPlainCopy(金色→金色白板)。"""

    def test_summon_token_does_not_consume_pool(self):
        game = make_game(seed=40)
        a = game.heroes[0]
        card = golden_t1_defs()[0]
        before = game.minion_pool.available(card.id)
        game.run_actions(actions.Summon(a, card.id))
        self.assertEqual(len(a.board), 1)
        self.assertEqual(a.board[0].card_id, card.id)
        self.assertEqual(game.minion_pool.available(card.id), before)

    def test_plain_copy_of_golden_is_golden_without_buffs(self):
        game = make_game(seed=41)
        a = game.heroes[0]
        base = golden_t1_defs()[0]
        gdef = get_db().golden_version(base)
        gm = game.create_minion(base.id, controller=a, golden=True)
        game.summon(a, gm)
        game.run_actions(actions.Buff(gm, 3, 3))
        game.run_actions(actions.SummonPlainCopy(gm))
        self.assertEqual(len(a.board), 2)
        copy = a.board[1]
        self.assertTrue(copy.is_golden)
        self.assertEqual(copy.card_id, gdef.id)
        self.assertEqual(copy.buffs, [])
        self.assertEqual(copy.atk, gdef.atk)
        self.assertEqual(copy.health, gdef.health)

    def test_plain_copy_of_buffed_non_golden(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        base = golden_t1_defs()[0]
        m = game.create_minion(base.id, controller=a)
        game.summon(a, m)
        game.run_actions(actions.Buff(m, 5, 5))
        game.run_actions(actions.SummonPlainCopy(m))
        copy = a.board[1]
        self.assertFalse(copy.is_golden)
        self.assertEqual(copy.card_id, base.id)
        self.assertEqual(copy.buffs, [])
        self.assertEqual(copy.atk, base.atk)


class TestHit(unittest.TestCase):
    """Hit: 伤害结算 + 死亡处理（亡语触发）+ damage 事件。"""

    def test_hit_lethal_triggers_deathrattle(self):
        game = make_game(seed=43)
        a = game.heroes[0]
        victim = make_minion("Vic", 1, 2)
        game.summon(a, victim)
        fired = []
        victim.scripts = type("S", (), {
            "deathrattle": staticmethod(
                lambda s, g, c: fired.append(1) or None)})
        attacker = make_minion("Att", 5, 5)
        seen = []
        game.events.register(Listener(
            "damage", owner=attacker,
            callback=lambda g, **kw: seen.append(
                (kw["minion"], kw["amount"], kw["source"]))))
        game.run_actions(actions.Hit(victim, 5, source=attacker))
        self.assertTrue(victim.dead)
        self.assertEqual(victim.zone, Zone.GRAVEYARD)
        self.assertNotIn(victim, a.board)
        self.assertEqual(fired, [1])                # 亡语经 check_deaths 触发
        self.assertEqual(seen, [(victim, 5, attacker)])

    def test_hit_nonlethal_stays_on_board(self):
        game = make_game(seed=44)
        a = game.heroes[0]
        m = make_minion("Tough", 2, 8)
        game.summon(a, m)
        game.run_actions(actions.Hit(m, 3))
        self.assertEqual(m.health, 5)
        self.assertFalse(m.dead)
        self.assertEqual(m.zone, Zone.PLAY)
        self.assertIn(m, a.board)

    def test_hit_divine_shield_absorbs_and_reports_zero(self):
        game = make_game(seed=45)
        a = game.heroes[0]
        m = make_minion("Shielded", 1, 4)
        m.set(GameTag.DIVINE_SHIELD, True)
        game.summon(a, m)
        seen = []
        game.events.register(Listener(
            "damage", owner=a,
            callback=lambda g, **kw: seen.append(kw["amount"])))
        game.run_actions(actions.Hit(m, 3))
        self.assertEqual(m.health, 4)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(m.dead)
        self.assertEqual(seen, [0])                 # actual = 0


class TestGetRandomMinion(unittest.TestCase):
    """GetRandomMinion: 占池/种族过滤(Amalgam)/池空落空/满手排队。"""

    def test_acquires_from_pool_into_hand(self):
        game = make_game(seed=46)
        a = game.heroes[0]
        before_total = game.minion_pool.total_remaining()
        game.run_actions(actions.GetRandomMinion(a))
        self.assertEqual(len(a.hand), 1)
        m = a.hand[0]
        copies = POOL_COPIES_BY_TIER[min(max(m.tech_level, 1), 7)]
        self.assertEqual(game.minion_pool.available(m.card_id), copies - 1)
        self.assertEqual(game.minion_pool.total_remaining(), before_total - 1)

    def test_race_query_matches_all_race_card(self):
        game = make_game(seed=47)
        a = game.heroes[0]
        amalgam = next(d.id for d in get_db().pool_minions()
                       if d.race == Race.ALL)
        others = [i for i in pool_ids() if i != amalgam]
        game.run_actions(actions.GetRandomMinion(
            a, race=Race.BEAST, exclude=others))
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(a.hand[0].card_id, amalgam)   # ALL 匹配任何种族查询

    def test_race_query_excludes_other_races(self):
        game = make_game(seed=48)
        a = game.heroes[0]
        nonbeast = next(d.id for d in get_db().pool_minions()
                        if d.race not in (Race.BEAST, Race.ALL))
        others = [i for i in pool_ids() if i != nonbeast]
        game.run_actions(actions.GetRandomMinion(
            a, race=Race.BEAST, exclude=others))
        self.assertEqual(a.hand, [])

    def test_empty_candidates_noop_no_exception(self):
        game = make_game(seed=49)
        a = game.heroes[0]
        total = game.minion_pool.total_remaining()
        game.run_actions(actions.GetRandomMinion(a, exclude=pool_ids()))
        self.assertEqual(a.hand, [])
        self.assertEqual(game.minion_pool.total_remaining(), total)

    def test_full_hand_goes_to_pending_queue(self):
        game = make_game(seed=50)
        a = game.heroes[0]
        a.hand = [make_minion(f"h{i}", 0, 1) for i in range(HAND_SIZE)]
        total = game.minion_pool.total_remaining()
        game.run_actions(actions.GetRandomMinion(a))
        self.assertEqual(len(a.hand), HAND_SIZE)
        self.assertEqual(len(game.pending_hand_queue), 1)
        h, m = game.pending_hand_queue[0]
        self.assertIs(h, a)
        self.assertIsInstance(m, Minion)
        self.assertEqual(game.minion_pool.total_remaining(), total - 1)


class TestDiscover(unittest.TestCase):
    """Discover: PendingChoice 队列化/resolve 占池入手/候选不足/池量过滤。"""

    def test_two_discovers_queue_without_overwrite(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        game.run_actions(actions.Discover(a))
        game.run_actions(actions.Discover(a))
        self.assertEqual(len(game.pending_choices), 2)

    def test_resolve_acquires_pool_copy_and_adds_to_hand(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        game.run_actions(actions.Discover(a))
        self.assertEqual(len(a.hand), 0)
        pc = game.pending_choices.pop(0)
        pick = pc.options[0]
        before = game.minion_pool.available(pick)
        pc.choose(0)
        self.assertEqual(game.minion_pool.available(pick), before - 1)
        self.assertTrue(any(e.card_id == pick for e in a.hand))
        self.assertEqual(len(game.pending_choices), 0)

    def test_fewer_candidates_gives_all(self):
        game = make_game(seed=53)
        a = game.heroes[0]
        game.run_actions(actions.Discover(a, count=3,
                                          candidates=["X1", "X2"]))
        self.assertEqual(len(game.pending_choices), 1)
        self.assertEqual(len(game.pending_choices[0].options), 2)

    def test_options_filtered_by_pool_availability(self):
        game = make_game(seed=54)
        a = game.heroes[0]
        t1 = [d.id for d in get_db().pool_minions() if d.tech_level == 1]
        x, y = t1[0], t1[1]
        while game.minion_pool.acquire(x):     # 抽干 x 的全部副本
            pass
        for other in t1[2:]:                   # 抽干其余 tier-1 候选
            while game.minion_pool.acquire(other):
                pass
        game.run_actions(actions.Discover(a, count=3, min_tier=1, max_tier=1))
        pc = game.pending_choices.pop(0)
        self.assertEqual(pc.options, [y])      # 池空的 x 不出现在选项中


class TestEconomyActions(unittest.TestCase):
    """GainGold / ScheduleNextTurn。"""

    def test_gain_gold_adds_amount(self):
        game = make_game(seed=55)
        a = game.heroes[0]
        a.gold = 5
        game.run_actions(actions.GainGold(a, 3))
        self.assertEqual(a.gold, 8)

    def test_gain_gold_caps_at_99(self):
        game = make_game(seed=56)
        a = game.heroes[0]
        a.gold = 98
        game.run_actions(actions.GainGold(a, 5))
        self.assertEqual(a.gold, 99)

    def test_schedule_next_turn_executes_at_next_recruit(self):
        game = make_game(seed=57)
        a = game.heroes[0]
        game.run_actions(actions.ScheduleNextTurn(a, actions.GainGold(a, 4)))
        self.assertEqual(len(game.deferred_actions), 1)
        game.turn = 2
        game._begin_recruit_for(a)
        self.assertEqual(len(game.deferred_actions), 0)
        game.queue.resolve(game)
        self.assertEqual(a.gold, gold_base_income(2) + 4)


if __name__ == "__main__":
    unittest.main()
