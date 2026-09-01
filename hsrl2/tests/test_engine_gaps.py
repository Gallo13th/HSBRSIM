"""三连 / 定向战吼 / Choose One / 磁力吸附 — 引擎核心机制测试。

三连 (RULES §10):
  - 3 副本（手牌/棋盘混合）自动合成金色
  - 金色 = 独立卡定义（数值来自金色 CardDef，禁止 ×2 近似）
  - buff 并集保留; 场上合成→金色上场+立即奖励; 手牌合成→金色入手
    打出时发奖励
  - 奖励 = Discover tier+1（T6→T6），池感知
定向战吼: needs_target 声明 → PendingChoice; 无候选战吼落空仍入场
磁力 (RULES §6.14): 属性/关键词并入宿主 + 亡语栈叠
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff
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


def make_hero(name: str) -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, n: int = 2) -> Game:
    heroes = [make_hero(chr(ord("A") + i)) for i in range(n)]
    import hsrl2.scripts  # noqa: F401  注册脚本
    return Game(heroes, get_db(), seed=seed)


def find_pool_card(db, *, tier=None, battlecry=False, no_battlecry=False):
    for d in sorted(db.pool_minions(), key=lambda x: x.id):
        if tier is not None and d.tech_level != tier:
            continue
        if battlecry and "battlecry" not in d.keywords:
            continue
        if no_battlecry and "battlecry" in d.keywords:
            continue
        if db.golden_version(d) is None:
            continue
        return d
    raise AssertionError("no matching pool card")


class TestTriple(unittest.TestCase):
    def _buy_copies(self, game, hero, card_id, n):
        for _ in range(n):
            m = game.create_minion(card_id, controller=hero)
            hero.hand.append(m)
            m.zone = Zone.HAND
            game.check_for_triple(hero, m)

    def test_hand_triple_combines_to_golden_def(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        self._buy_copies(game, a, d.id, 3)
        goldens = [m for m in a.hand if m.is_golden]
        self.assertEqual(len(goldens), 1)
        self.assertEqual(len(a.hand), 1)
        g = goldens[0]
        gd = get_db().golden_version(d)
        # 金色 = 独立卡定义（数值非 ×2 近似——用金色 def 断言）
        self.assertEqual(g.atk, gd.atk)
        self.assertEqual(g.max_health, gd.health)
        self.assertTrue(g.has(GameTag.TRIPLE_REWARD_PENDING))

    def test_board_triple_immediate_reward(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        # 2 张上场，第 3 张入手触发
        for _ in range(2):
            m = game.create_minion(d.id, controller=a)
            game.summon(a, m)
        third = game.create_minion(d.id, controller=a)
        a.hand.append(third)
        third.zone = Zone.HAND
        game.check_for_triple(a, third)
        # 场上合成: 金色在棋盘、奖励立即发放（PendingChoice 入队）
        self.assertEqual(len(a.board), 1)
        self.assertTrue(a.board[0].is_golden)
        kinds = [c.kind for c in game.pending_choices]
        self.assertIn("triple_reward", kinds)

    def test_triple_reward_discovers_tier_plus_one(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        d = find_pool_card(get_db(), tier=2, no_battlecry=True)
        for _ in range(2):
            m = game.create_minion(d.id, controller=a)
            game.summon(a, m)
        third = game.create_minion(d.id, controller=a)
        a.hand.append(third)
        third.zone = Zone.HAND
        game.check_for_triple(a, third)
        choice = next(c for c in game.pending_choices
                      if c.kind == "triple_reward")
        for opt in choice.options:
            self.assertEqual(get_db().get(opt).tech_level, 3)   # T2→T3
        pool_before = game.minion_pool.available(choice.options[0])
        choice.choose(0)
        self.assertEqual(game.minion_pool.available(choice.options[0]),
                         pool_before - 1)   # 占池
        self.assertIn(a.hand[-1].card_id, [choice.options[0]])

    def test_triple_preserves_all_buffs(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        m1 = game.create_minion(d.id, controller=a)
        m1.add_buff(Buff(atk=5, health=3))
        game.summon(a, m1)
        m2 = game.create_minion(d.id, controller=a)
        game.summon(a, m2)
        third = game.create_minion(d.id, controller=a)
        third.add_buff(Buff(atk=2, health=2))
        a.hand.append(third)
        third.zone = Zone.HAND
        game.check_for_triple(a, third)
        g = a.board[0]
        gd = get_db().golden_version(d)
        # 金色基础 + 全部参与副本 buff（5+2 攻 / 3+2 血）
        self.assertEqual(g.atk, gd.atk + 7)
        self.assertEqual(g.max_health, gd.health + 5)

    def test_golden_play_releases_triple_reward(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        self._buy_copies(game, a, d.id, 3)
        g = a.hand[0]
        self.assertTrue(game.play_minion(a, g))
        kinds = [c.kind for c in game.pending_choices]
        self.assertIn("triple_reward", kinds)

    def test_no_triple_below_three(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        self._buy_copies(game, a, d.id, 2)
        self.assertEqual(len(a.hand), 2)   # 不合成


class TestTargetedBattlecry(unittest.TestCase):
    def test_needs_target_defers_to_pending_choice(self):
        game = make_game(seed=7)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        m = game.create_minion(d.id, controller=a)
        # 注入定向战吼脚本协议
        buffed = []
        m.scripts = type("S", (), {
            "needs_target": True,
            "battlecry": staticmethod(
                lambda s, g, c: buffed.append(c["target"].uuid) or None),
        })
        a.hand.append(m)
        m.zone = Zone.HAND
        t1 = game.create_minion(d.id, controller=a)
        game.summon(a, t1)
        self.assertTrue(game.play_minion(a, m))
        # 官方顺序: 随从**先入场**（战吼可以自身为目标），选择后结算
        self.assertEqual(len(game.pending_choices), 1)
        self.assertEqual(game.pending_choices[0].kind, "battlecry_target")
        self.assertEqual(len(a.board), 2)
        self.assertEqual(buffed, [])
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(buffed, [t1.uuid])   # 选定后战吼以 ctx.target 触发

    def test_no_candidates_bc_fizzles_minion_still_played(self):
        game = make_game(seed=8)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        m = game.create_minion(d.id, controller=a)
        m.scripts = type("S", (), {
            "needs_target": True,
            "target_candidates": staticmethod(lambda s, g: []),
            "battlecry": staticmethod(lambda s, g, c: None),
        })
        a.hand.append(m)
        m.zone = Zone.HAND
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(game.pending_choices), 0)   # 无候选无选择
        self.assertEqual(len(a.board), 1)                # 随从照常入场

    def test_explicit_target_plays_directly(self):
        game = make_game(seed=9)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        m = game.create_minion(d.id, controller=a)
        seen = []
        m.scripts = type("S", (), {
            "needs_target": True,
            "battlecry": staticmethod(
                lambda s, g, c: seen.append(c["target"].uuid) or None),
        })
        a.hand.append(m)
        m.zone = Zone.HAND
        t = game.create_minion(d.id, controller=a)
        game.summon(a, t)
        self.assertTrue(game.play_minion(a, m, target=t))
        self.assertEqual(len(game.pending_choices), 0)
        self.assertEqual(seen, [t.uuid])


class TestChooseOne(unittest.TestCase):
    def test_choose_one_defers_and_passes_key(self):
        game = make_game(seed=10)
        a = game.heroes[0]
        d = find_pool_card(get_db(), no_battlecry=True)
        m = game.create_minion(d.id, controller=a)
        chosen = []
        # BG 的 Choose One 均为战吼类效果——钩子为 battlecry，ctx 带 choose
        m.scripts = type("S", (), {
            "choose_options": [("left", "Left"), ("right", "Right")],
            "battlecry": staticmethod(
                lambda s, g, c: chosen.append(c["choose"]) or None),
        })
        a.hand.append(m)
        m.zone = Zone.HAND
        self.assertTrue(game.play_minion(a, m))
        # 官方顺序: 先入场再选择
        self.assertEqual(len(a.board), 1)
        self.assertEqual(game.pending_choices[0].kind, "choose_one")
        self.assertEqual(game.pending_choices[0].options, ["left", "right"])
        game.pending_choices.pop(0).choose(1)
        self.assertEqual(chosen, ["right"])


class TestMagnetic(unittest.TestCase):
    def _magnetic_pair(self, game, hero):
        db = get_db()
        mechs = [d for d in db.pool_minions()
                 if "magnetic" in d.keywords and db.golden_version(d)]
        self.assertTrue(mechs, "data must contain magnetic pool minions")
        mag = game.create_minion(mechs[0].id, controller=hero)
        host = Minion("TEST_HOST", "Host", atk=1, health=1, race=Race.MECH)
        game.summon(hero, host)
        return mag, host, mechs[0]

    def test_attach_merges_stats_and_keywords(self):
        game = make_game(seed=11)
        a = game.heroes[0]
        mag, host, md = self._magnetic_pair(game, a)
        a.hand.append(mag)
        mag.zone = Zone.HAND
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        self.assertEqual(host.atk, 1 + md.atk)
        self.assertEqual(host.max_health, 1 + md.health)
        self.assertEqual(len(a.board), 1)          # 吸附不占新格
        self.assertEqual(mag.zone, Zone.REMOVED)

    def test_magnetic_requires_mech_target(self):
        game = make_game(seed=12)
        a = game.heroes[0]
        mag, _, _ = self._magnetic_pair(game, a)
        beast = Minion("TEST_BEAST", "Beast", atk=1, health=1, race=Race.BEAST)
        game.summon(a, beast)
        a.hand.append(mag)
        mag.zone = Zone.HAND
        self.assertFalse(game.play_minion(a, mag, magnetic_target=beast))

    def test_magnetic_deathrattle_stacks_on_host_death(self):
        game = make_game(seed=13)
        a = game.heroes[0]
        mag, host, md = self._magnetic_pair(game, a)
        a.hand.append(mag)
        mag.zone = Zone.HAND
        game.play_minion(a, mag, magnetic_target=host)
        # 效果合并登记: 栈含磁力卡 id; 宿主 DEATHRATTLE 标志仅当磁力卡
        # 或宿主自身带亡语; 宿主死亡时 COUNTER_DEATHRATTLES 按宿主+附件计数
        self.assertIn(mag.card_id, game._magnetic_stack[host.uuid])
        if "deathrattle" in md.keywords:
            self.assertTrue(host.has(GameTag.DEATHRATTLE))
        # 死亡时计数: 宿主无亡语 + 磁力卡无亡语 → 0; 有则 1+附件数
        host.health = 0
        game._process_single_death(host)
        expected = (1 if "deathrattle" in md.keywords else 0)
        self.assertEqual(a.get(GameTag.COUNTER_DEATHRATTLES, 0), expected)


class TestOnceListenerCombatSnapshot(unittest.TestCase):
    def test_fired_once_listener_not_resurrected(self):
        from hsrl2.events import Listener
        game = make_game(seed=14)
        a, b = game.heroes
        fired = []
        anchor = game.create_minion(find_pool_card(
            get_db(), no_battlecry=True).id, controller=a)
        game.summon(a, anchor)
        game.events.register(Listener(
            "before_attack", owner=anchor, once=True,
            callback=lambda g, **kw: fired.append(1)))
        big = Minion("TEST_B", "B", atk=9, health=9)
        game.summon(b, big)
        game.run_combat(a, b)
        once_count = sum(1 for l in game.events._listeners.get(
            "before_attack", []) if l.once)
        self.assertEqual(once_count, 0)   # 战斗内已触发的 once 不复活


if __name__ == "__main__":
    unittest.main()


class TestDoublerAuras(unittest.TestCase):
    """Brann / Drakkari / Titus——光环随宿主离场失效（棋盘扫描式）。"""

    def _pool_card_with_bc(self, db):
        for d in sorted(db.pool_minions(), key=lambda x: x.id):
            if "battlecry" in d.keywords and db.golden_version(d):
                return d
        raise AssertionError

    def test_brann_doubles_battlecry_and_expires(self):
        game = make_game(seed=30)
        a = game.heroes[0]
        d = self._pool_card_with_bc(get_db())
        target = game.create_minion(d.id, controller=a)
        a.hand.append(target)
        target.zone = Zone.HAND
        game.play_minion(a, target)          # 无 Brann: 1 次
        base_calls = a.get(GameTag.COUNTER_BATTLECRIES, 0)
        self.assertEqual(base_calls, 1)
        # Brann 入场 → 再打一张: 2 次
        from hsrl2.scripts.batches.batch_doublers import BrannBronzebeardScript
        brann = game.create_minion("BG_LOE_077", controller=a)
        brann.scripts = BrannBronzebeardScript
        game.summon(a, brann)
        t2 = game.create_minion(d.id, controller=a)
        a.hand.append(t2)
        t2.zone = Zone.HAND
        game.play_minion(a, t2)
        self.assertEqual(
            a.get(GameTag.COUNTER_BATTLECRIES, 0) - base_calls, 2)
        # Brann 出售 → 光环失效
        game.sell_minion(a, brann)
        t3 = game.create_minion(d.id, controller=a)
        a.hand.append(t3)
        t3.zone = Zone.HAND
        calls_before = a.get(GameTag.COUNTER_BATTLECRIES, 0)
        game.play_minion(a, t3)
        self.assertEqual(
            a.get(GameTag.COUNTER_BATTLECRIES, 0) - calls_before, 1)

    def test_titus_doubles_deathrattle(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        triggers = []
        dr_holder = Minion("TEST_DR_H", "H", atk=1, health=1)
        dr_holder.scripts = type("S", (), {
            "deathrattle": staticmethod(
                lambda s, g, c: triggers.append(1) or None)})
        game.summon(a, dr_holder)
        from hsrl2.scripts.batches.batch_doublers import TitusRivendareScript
        titus = game.create_minion("BG25_354", controller=a)
        titus.scripts = TitusRivendareScript
        game.summon(a, titus)
        dr_holder.health = 0
        game.check_deaths()
        self.assertEqual(len(triggers), 2)   # Titus 翻倍

    def test_drakkari_doubles_eot(self):
        game = make_game(seed=32)
        a = game.heroes[0]
        calls = []
        holder = Minion("TEST_EOT", "E", atk=1, health=1)
        holder.scripts = type("S", (), {
            "end_of_turn": staticmethod(
                lambda s, g, c: calls.append(1) or None)})
        game.summon(a, holder)
        from hsrl2.scripts.batches.batch_doublers import (
            DrakkariEnchanterScript, DrakkariEnchanterGoldenScript)
        drak = game.create_minion("BG26_ICC_901", controller=a)
        drak.scripts = DrakkariEnchanterScript
        game.summon(a, drak)
        game.end_recruit_phase()
        self.assertEqual(len(calls), 2)      # Drakkari 翻倍
