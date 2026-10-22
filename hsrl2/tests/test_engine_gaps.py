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
from hsrl2.events import HERO_DAMAGE_TAKEN, Listener
from hsrl2.game import Game, GameStateError
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import CardType, GameTag, Race, Zone

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
        # 预留语义: 选中项保持预留（选项生成时已占池），不再二次扣减
        self.assertEqual(game.minion_pool.available(choice.options[0]),
                         pool_before)
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

    def test_drakkari_doubles_trinket_eot(self):
        """E1（2026-09-02 对抗审查）: "Your end of turn effects trigger
        twice" 覆盖饰品 EoT——不只是棋盘随从。"""
        game = make_game(seed=33)
        a = game.heroes[0]
        calls = []
        trinket = game.create_entity("BG30_MagicItem_984",
                                    controller=a)
        trinket.scripts = type("S", (), {
            "end_of_turn": staticmethod(
                lambda s, g, c: calls.append(1) or None)})
        a.trinkets.append(trinket)
        from hsrl2.scripts.batches.batch_doublers import (
            DrakkariEnchanterScript)
        drak = game.create_minion("BG26_ICC_901", controller=a)
        drak.scripts = DrakkariEnchanterScript
        game.summon(a, drak)
        game.end_recruit_phase()
        self.assertEqual(len(calls), 2)      # 饰品 EoT 同样翻倍

    def test_drakkari_doubles_quest_reward_eot(self):
        game = make_game(seed=34)
        a = game.heroes[0]
        calls = []
        reward = game.create_entity("BG27_Reward_502",
                                    controller=a)
        reward.scripts = type("S", (), {
            "end_of_turn": staticmethod(
                lambda s, g, c: calls.append(1) or None)})
        a.quest_rewards.append(reward)
        from hsrl2.scripts.batches.batch_doublers import (
            DrakkariEnchanterScript)
        drak = game.create_minion("BG26_ICC_901", controller=a)
        drak.scripts = DrakkariEnchanterScript
        game.summon(a, drak)
        game.end_recruit_phase()
        self.assertEqual(len(calls), 2)      # 任务奖励 EoT 同样翻倍

    def test_failed_spell_purchase_keeps_discount(self):
        """E2（2026-09-02 对抗审查）: "Your next Tavern spell costs (1)
        less" 只在购买**成交**时消耗——金币不足的失败购买不得烧掉它。"""
        game = make_game(seed=35)
        a = game.heroes[0]
        spell = game.create_spell("BG28_168", controller=a)
        spell.zone = Zone.TAVERN
        a.tavern = [spell]
        a.set(GameTag.NEXT_SPELL_COST_REDUCTION, 1)
        a.gold = 0
        self.assertFalse(game.buy_from_tavern(a, spell))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 1)
        self.assertIn(spell, a.tavern)
        # 成功购买 → 折扣消耗 + 实付 = cost−1
        base = game.db.get("BG28_168").cost
        a.gold = base
        self.assertTrue(game.buy_from_tavern(a, spell))
        self.assertEqual(a.gold, base - max(0, base - 1))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 0)

    def test_drakkari_golden_triples_eot(self):
        """金色 Drakkari = "trigger three times" → EoT ×3（随从与饰品）。"""
        game = make_game(seed=36)
        a = game.heroes[0]
        calls = []
        holder = Minion("TEST_EOT3", "E", atk=1, health=1)
        holder.scripts = type("S", (), {
            "end_of_turn": staticmethod(
                lambda s, g, c: calls.append(1) or None)})
        game.summon(a, holder)
        from hsrl2.scripts.batches.batch_doublers import (
            DrakkariEnchanterGoldenScript)
        drak = game.create_minion("BG26_ICC_901", controller=a, golden=True)
        drak.scripts = DrakkariEnchanterGoldenScript
        game.summon(a, drak)
        game.end_recruit_phase()
        self.assertEqual(len(calls), 3)


class TestExtraTriggerQuotas(unittest.TestCase):
    """RULES §6.20 — 额外触发配额（hero.extra_triggers）。

    脚本侧声明永久额度，引擎在对应触发点消费"已用次数"（每回合/每场
    战斗重置）:
      eot_extra / soc_extra（每个效果 +N）· soc_first / dr_first
      （前 N 个效果 +1）· spell_first / spellcraft_first（前 N 次施放
      +1 结算）· hp_uses（技能次数 +N）· bc_race+bc_times（种族限定战吼）
    """

    def _counter_script(self, hook, bucket):
        return type("S", (), {
            hook: staticmethod(lambda s, g, c=None, **kw:
                               bucket.append(s) or None)})

    # ── EoT / SoC ──

    def test_eot_extra_stacks_with_drakkari(self):
        game = make_game(seed=60)
        a = game.heroes[0]
        calls = []
        h = Minion("TEST_EOT", "E", atk=1, health=1)
        h.scripts = self._counter_script("end_of_turn", calls)
        game.summon(a, h)
        a.extra_triggers["eot_extra"] = 1              # Ghastly Sticker
        game.end_recruit_phase()
        self.assertEqual(len(calls), 2)                # 基础 1 + 配额 1
        calls.clear()
        from hsrl2.scripts.batches.batch_doublers import (
            DrakkariEnchanterScript)
        drak = game.create_minion("BG26_ICC_901", controller=a)
        drak.scripts = DrakkariEnchanterScript
        game.summon(a, drak)
        game.end_recruit_phase()
        self.assertEqual(len(calls), 3)                # 1 + 1 + Drakkari 1

    def test_soc_extra_and_first_quota(self):
        game = make_game(seed=61)
        a, b = game.heroes
        calls = []
        m1 = Minion("TEST_SOC1", "S1", atk=1, health=10)
        m1.scripts = self._counter_script("start_of_combat", calls)
        m2 = Minion("TEST_SOC2", "S2", atk=1, health=10)
        m2.scripts = self._counter_script("start_of_combat", calls)
        game.summon(a, m1)
        game.summon(a, m2)
        a.extra_triggers["soc_extra"] = 1              # Wind Chimes
        a.extra_triggers["soc_first"] = 1              # Promo Portrait
        game.run_combat(a, b)
        # m1: 1 + soc_extra 1 + 首个配额 1 = 3; m2: 1 + 1 = 2
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls.count(m1) if m1 in calls else 0, 3)
        calls.clear()
        # 配额按场重置: 下一场第一效果再加 1
        game.run_combat(a, b)
        self.assertEqual(len(calls), 5)

    def test_soc_first_quota_not_eaten_by_hookless_entities(self):
        """对抗审查 MAJOR（2026-09-02）: 无 `start_of_combat` 钩子的
        饰品/奖励不得消费 `soc_first` 配额——否则真正的首个 SoC 效果
        享受不到额外触发（Promo Portrait 若排在 hero.trinkets 首位）。"""
        game = make_game(seed=72)
        a, b = game.heroes
        calls = []
        noop = game.create_entity("BG30_MagicItem_984", controller=a)
        noop.scripts = type("S", (), {})            # 明确无 SoC 钩子
        a.trinkets.append(noop)
        m = Minion("TEST_SOC_FIRST", "S", atk=1, health=10)
        m.scripts = self._counter_script("start_of_combat", calls)
        game.summon(a, m)
        a.extra_triggers["soc_first"] = 1
        game.run_combat(a, b)
        self.assertEqual(len(calls), 2)             # 探针拿到配额

    def test_dr_first_quota_per_combat(self):
        game = make_game(seed=62)
        a, b = game.heroes
        calls = []
        for i in range(2):
            m = Minion(f"TEST_DR{i}", f"D{i}", atk=1, health=1)
            m.scripts = self._counter_script("deathrattle", calls)
            m.set(GameTag.DEATHRATTLE, True)
            game.summon(a, m)
        a.extra_triggers["dr_first"] = 1               # Deathly Phylactery
        game.in_combat = True
        game._active_combat = (a, b)
        try:
            for m in list(a.board):
                m.health = 0
                game._process_single_death(m)
        finally:
            game.in_combat = False
            game._active_combat = None
        self.assertEqual(len(calls), 3)                # 首个 2 次 + 次个 1 次

    def test_dr_first_not_consumed_by_non_deathrattle_death(self):
        """对抗审查 D1: 战斗中无亡语的死亡不得吃掉 `dr_first` 配额。"""
        game = make_game(seed=73)
        a, b = game.heroes
        calls = []
        vanilla = Minion("TEST_VANILLA", "V", atk=1, health=1)
        game.summon(a, vanilla)
        probe = Minion("TEST_DR_PROBE", "P", atk=1, health=1)
        probe.scripts = self._counter_script("deathrattle", calls)
        probe.set(GameTag.DEATHRATTLE, True)
        game.summon(a, probe)
        a.extra_triggers["dr_first"] = 1
        game.in_combat = True
        game._active_combat = (a, b)
        try:
            vanilla.health = 0
            game._process_single_death(vanilla)      # 无亡语 → 不消费
            probe.health = 0
            game._process_single_death(probe)        # 首个亡语 → 2 次
        finally:
            game.in_combat = False
            game._active_combat = None
        self.assertEqual(len(calls), 2)

    def test_spellcraft_spell_consumes_both_spell_quotas(self):
        """对抗审查 D2: 法术塑造法术同时属"spell" → 两个配额都可消费。"""
        game = make_game(seed=74)
        a = game.heroes[0]
        calls = []
        a.extra_triggers["spell_first"] = 1          # Replica Cathedral
        a.extra_triggers["spellcraft_first"] = 1     # Sushi Roll
        sc = game.create_spell("BG28_168", controller=a)
        sc.set(GameTag.SPELLCRAFT, True)
        sc.scripts = self._counter_script("on_play", calls)
        a.add_to_hand(sc)
        self.assertTrue(game.play_spell(a, sc))
        self.assertEqual(len(calls), 3)              # 1 + 1 + 1
        # 普通法术只吃 spell_first（已耗尽）
        s2 = game.create_spell("BG28_168", controller=a)
        s2.scripts = self._counter_script("on_play", calls)
        a.add_to_hand(s2)
        self.assertTrue(game.play_spell(a, s2))
        self.assertEqual(len(calls), 4)

    def test_global_and_race_limited_battlecry_quotas_coexist(self):
        """对抗审查 D3: 全局 bc_times 与种族限定 bc_times_race 互不干扰。"""
        game = make_game(seed=75)
        a = game.heroes[0]
        calls = []
        beast = game.create_minion("BG25_011", controller=a)
        beast.set(GameTag.RACE, Race.BEAST)
        beast.scripts = self._counter_script("battlecry", calls)
        a.add_to_hand(beast)
        a.extra_triggers["bc_times"] = 1             # Gilnean War Horn
        a.extra_triggers["bc_times_race"] = 1        # Dragon's Eye
        a.extra_triggers["bc_race"] = Race.DRAGON
        self.assertTrue(game.play_minion(a, beast))
        self.assertEqual(len(calls), 2)              # 非龙: 仅全局 +1
        calls.clear()
        dragon = game.create_minion("BG25_011", controller=a)
        dragon.set(GameTag.RACE, Race.DRAGON)
        dragon.scripts = self._counter_script("battlecry", calls)
        a.add_to_hand(dragon)
        self.assertTrue(game.play_minion(a, dragon))
        self.assertEqual(len(calls), 3)              # 龙: 全局 + 种族限定

    # ── 法术 ──

    def _spell(self, game, hero, card_id="BG28_168"):
        s = game.create_spell(card_id, controller=hero)
        hero.add_to_hand(s)
        return s

    def test_first_spell_extra_resolution_resets_each_turn(self):
        game = make_game(seed=63)
        a = game.heroes[0]
        calls = []
        a.extra_triggers["spell_first"] = 1            # Replica Cathedral
        s1 = self._spell(game, a)
        s1.scripts = self._counter_script("on_play", calls)
        self.assertTrue(game.play_spell(a, s1))
        self.assertEqual(len(calls), 2)                # 首个法术结算 2 次
        s2 = self._spell(game, a)
        s2.scripts = self._counter_script("on_play", calls)
        self.assertTrue(game.play_spell(a, s2))
        self.assertEqual(len(calls), 3)                # 第二个只 1 次
        # 下一回合配额重置
        game.turn = 2
        game._begin_recruit_for(a)
        s3 = self._spell(game, a)
        s3.scripts = self._counter_script("on_play", calls)
        self.assertTrue(game.play_spell(a, s3))
        self.assertEqual(len(calls), 5)

    def test_spellcraft_quota_is_separate(self):
        game = make_game(seed=64)
        a = game.heroes[0]
        calls = []
        a.extra_triggers["spellcraft_first"] = 1       # Sushi Roll
        sc = self._spell(game, a)
        sc.set(GameTag.SPELLCRAFT, True)
        sc.scripts = self._counter_script("on_play", calls)
        self.assertTrue(game.play_spell(a, sc))
        self.assertEqual(len(calls), 2)
        # 普通法术不吃 Spellcraft 配额
        s = self._spell(game, a)
        s.scripts = self._counter_script("on_play", calls)
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(len(calls), 3)

    # ── 英雄技能 ──

    def test_hero_power_extra_uses(self):
        from hsrl2.scripts import REGISTRY
        # 需要 db 有 power 绑定的真实英雄（TEST_HERO_* 无技能定义）
        game = Game([Hero("BG20_HERO_103", "Blackthorn"), make_hero("B")],
                    get_db(), seed=65)
        a = game.heroes[0]
        power = game.hero_power_def(a)
        self.assertIsNotNone(power)
        calls = []

        class TwoUses:
            uses_per_turn = 1

            @staticmethod
            def hero_power(hero, g, ctx):
                calls.append(1)
                return None

        # 保存/还原真实脚本（旧实现直接 `del` → 泄漏全局状态，
        # 使后续依赖该技能的测试失效; 2026-09-02 修正）
        saved = REGISTRY.get(power.id)
        REGISTRY[power.id] = TwoUses
        try:
            a.extra_triggers["hp_uses"] = 1            # Sous Chef Sticker
            a.gold = 10
            self.assertTrue(game.use_hero_power(a))
            self.assertTrue(game.use_hero_power(a))    # 配额给的第二次
            self.assertFalse(game.use_hero_power(a))   # 第三次仍不可用
            self.assertEqual(len(calls), 2)
        finally:
            if saved is None:
                REGISTRY.pop(power.id, None)
            else:
                REGISTRY[power.id] = saved

    # ── 全局亡语 / Rally 额外触发 ──

    def test_dr_extra_global_permanent(self):
        game = make_game(seed=67)
        a, b = game.heroes
        calls = []
        m = Minion("TEST_DRX", "D", atk=1, health=1)
        m.scripts = self._counter_script("deathrattle", calls)
        m.set(GameTag.DEATHRATTLE, True)
        game.summon(a, m)
        a.extra_triggers["dr_extra"] = 1               # Turbulent Tombs
        game.in_combat = True
        game._active_combat = (a, b)
        try:
            m.health = 0
            game._process_single_death(m)
        finally:
            game.in_combat = False
            game._active_combat = None
        self.assertEqual(len(calls), 2)                # 全部亡语 +1

    def _rally_count(self, quota):
        """真实战斗中 rally 钩子的调用次数（Rally 每次攻击宣告触发一次）。"""
        game = make_game(seed=68)
        a, b = game.heroes
        calls = []
        atk = Minion("TEST_RALLY", "R", atk=2, health=5)
        atk.scripts = self._counter_script("rally", calls)
        game.summon(a, atk)
        game.summon(b, Minion("TEST_DEF", "D", atk=0, health=20))
        if quota:
            a.extra_triggers["rally_extra"] = quota    # Rallying Cry
        game.run_combat(a, b)
        return len(calls)

    def test_rally_extra_doubles_each_declaration(self):
        base = self._rally_count(None)
        self.assertGreater(base, 0)                    # 正对照: 基线确有 Rally
        self.assertEqual(self._rally_count(1), base * 2)

    # ── 战吼（全局 + 种族限定） ──

    def test_global_battlecry_extra(self):
        game = make_game(seed=70)
        a = game.heroes[0]
        calls = []
        m = game.create_minion("BG25_011", controller=a)
        m.scripts = self._counter_script("battlecry", calls)
        a.add_to_hand(m)
        a.extra_triggers["bc_times"] = 1               # Gilnean War Horn
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(calls), 2)                # 不限定种族 → 全部 +1

    # ── 种族限定战吼 ──

    def test_race_limited_battlecry_extra(self):
        game = make_game(seed=66)
        a = game.heroes[0]
        calls = []
        dragon = game.create_minion("BG25_011", controller=a)
        dragon.set(GameTag.RACE, Race.DRAGON)
        dragon.scripts = self._counter_script("battlecry", calls)
        a.add_to_hand(dragon)
        other = game.create_minion("BG25_011", controller=a)
        other.set(GameTag.RACE, Race.BEAST)
        other.scripts = self._counter_script("battlecry", calls)
        a.add_to_hand(other)
        # Dragon's Eye 用**种族限定**配额（与全局 bc_times 独立——D3）
        a.extra_triggers["bc_race"] = Race.DRAGON
        a.extra_triggers["bc_times_race"] = 1
        self.assertTrue(game.play_minion(a, dragon))
        self.assertEqual(len(calls), 2)                # 龙战吼 +1
        calls.clear()
        self.assertTrue(game.play_minion(a, other))
        self.assertEqual(len(calls), 1)                # 非龙不受影响


class TestDeathReentrancy(unittest.TestCase):
    """DEATH 事件在离场之前广播 → 监听器内嵌套 check_deaths() 不得让
    同一实体被二次处理（2026-09-02 对抗审查实测: Onyxia Avenge 触发
    "死亡时召唤并立即攻击" 家族会让同一 uuid 的亡语触发两次）。"""

    def test_nested_check_deaths_does_not_double_process(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        from hsrl2.events import DEATH, Listener
        dr_calls = []
        m = Minion("TEST_DR_REENT", "D", atk=1, health=1)
        m.scripts = type("S", (), {
            "deathrattle": staticmethod(
                lambda s, g, c=None, **kw: dr_calls.append(1) or None)})
        m.set(GameTag.DEATHRATTLE, True)
        game.summon(a, m)
        # DEATH 监听器回调内重入 check_deaths（模拟"死亡时召唤+立即攻击"）
        game.events.register(Listener(
            event=DEATH, owner=a,
            callback=lambda g, **kw: g.check_deaths()))
        m.health = 0
        game.check_deaths()
        self.assertEqual(len(dr_calls), 1)          # 只结算一次
        self.assertEqual(m.zone, Zone.GRAVEYARD)


class TestHeroPowerSlots(unittest.TestCase):
    """RULES §9.5 — 第二英雄技能槽（异变/奖励授予）。

    每个技能独立的每回合/每局计数与费用；第二技能的 on_bind 在异变
    on_bind 之后补接线（`start_game` 三段顺序）。
    """

    ANOMALY = "TEST_ANOMALY_SLOT"
    SECOND = "TB_BaconShop_HP_017"   # db 在册但未注册脚本的真实技能 id

    def _game(self, seed=80):
        from hsrl2.scripts import REGISTRY
        self.assertIsNotNone(get_db().get(self.SECOND))
        game = Game([Hero("BG20_HERO_103", "Blackthorn"), make_hero("B")],
                    get_db(), seed=seed, anomaly=self.ANOMALY)
        a = game.heroes[0]
        main = game.hero_power_def(a)
        calls = {"main": [], "second": [], "wired": []}

        class MainPower:
            uses_per_turn = 1

            @staticmethod
            def hero_power(hero, g, ctx):
                calls["main"].append(1)
                return None

        class SecondPower:
            uses_per_turn = 1
            uses_per_game = 2

            @staticmethod
            def on_bind(hero, g):
                calls["wired"].append(hero)

            @staticmethod
            def hero_power(hero, g, ctx):
                calls["second"].append(1)
                return None

        class SlotAnomaly:
            @staticmethod
            def on_bind(g):
                for h in g.heroes:
                    h._second_power_id = TestHeroPowerSlots.SECOND

        patches = {main.id: MainPower, self.SECOND: SecondPower,
                   self.ANOMALY: SlotAnomaly}
        saved = {k: REGISTRY.get(k) for k in patches}
        REGISTRY.update(patches)
        return game, a, calls, patches, saved

    def _restore(self, patches, saved):
        from hsrl2.scripts import REGISTRY
        for k, v in saved.items():
            if v is None:
                REGISTRY.pop(k, None)
            else:
                REGISTRY[k] = v

    def test_two_slots_independent_counts(self):
        game, a, calls, patches, saved = self._game()
        try:
            game.start_game()
            main_id, second_id = game.hero_power_ids(a)
            self.assertIn(self.SECOND, (main_id, second_id))
            self.assertEqual(len(game.hero_power_ids(a)), 2)
            # 第二技能 on_bind 已接线（顺序: 主 → 异变 → 第二）——
            # 异变给**每个**英雄都加第二槽，故两位英雄各接线一次
            self.assertIn(a, calls["wired"])
            self.assertEqual(len(calls["wired"]), 2)
            a.gold = 20
            self.assertTrue(game.use_hero_power(a))              # 主技能
            self.assertTrue(game.use_hero_power(a,
                                                power_id=self.SECOND))
            self.assertFalse(game.use_hero_power(a))             # 主技能已用
            self.assertFalse(game.use_hero_power(a,
                                                 power_id=self.SECOND))
            self.assertEqual(len(calls["main"]), 1)
            self.assertEqual(len(calls["second"]), 1)
            self.assertEqual(a.get(GameTag.HERO_POWER_USED_THIS_TURN), 2)
            # 新回合: 清 tag 即"本回合计数归零"（Hero.clear 覆盖）
            a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
            self.assertTrue(game.use_hero_power(a))
            self.assertTrue(game.use_hero_power(a, power_id=self.SECOND))
            # 每局次数独立: 第二技能 uses_per_game=2 已耗尽
            a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
            self.assertTrue(game.use_hero_power(a))              # 主技能仍可用
            self.assertFalse(game.use_hero_power(a,
                                                 power_id=self.SECOND))
        finally:
            self._restore(patches, saved)

    def test_unknown_power_id_refused(self):
        game, a, calls, patches, saved = self._game(seed=81)
        try:
            game.start_game()
            a.gold = 20
            self.assertFalse(game.use_hero_power(a, power_id="NO_SUCH_POWER"))
            self.assertEqual(calls["main"], [])
        finally:
            self._restore(patches, saved)


class TestTrinketGrantProtocol(unittest.TestCase):
    """RULES §7.4.3 — 饰品非商店授予/替换协议 + 购买事件。

    解锁 "Get a random Trinket" / "transform into a copy of it" /
    "replace this" 族（Souvenir Stand / Trip Vouchers / Rune of
    Transmutation / Orb of the Unknown / Mystery Cube / Crystal Ball）。
    """

    LESSER = "BG30_MagicItem_984"     # Charging Staff（lesser, 在售池内）

    def _game(self, seed=90):
        from hsrl2.scripts import REGISTRY
        game = make_game(seed=seed)
        calls = []

        class Probe:
            @staticmethod
            def on_bind(source, g, ctx):
                calls.append(source.card_id)

        REGISTRY[self.LESSER] = Probe
        return game, game.heroes[0], calls

    def test_grant_runs_on_bind_and_is_idempotent(self):
        from hsrl2.scripts import REGISTRY
        game, a, calls = self._game()
        try:
            e = game.grant_trinket(a, self.LESSER)
            self.assertIsNotNone(e)
            self.assertIn(e, a.trinkets)
            self.assertEqual(calls, [self.LESSER])       # on_bind 已跑
            self.assertIsNone(game.grant_trinket(a, self.LESSER))  # 幂等
            self.assertEqual(len(a.trinkets), 1)
        finally:
            del REGISTRY[self.LESSER]

    def test_trinket_granted_event_fires(self):
        from hsrl2.events import Listener
        from hsrl2.scripts import REGISTRY
        game, a, calls = self._game(seed=91)
        seen = []
        try:
            game.events.register(Listener(
                event="trinket_granted", owner=a,
                callback=lambda g, **kw: seen.append(kw)))
            game.grant_trinket(a, self.LESSER, source="test")
            self.assertEqual(len(seen), 1)
            self.assertIs(seen[0]["hero"], a)
            self.assertEqual(seen[0]["source"], "test")
        finally:
            del REGISTRY[self.LESSER]

    def test_grant_random_respects_kind_and_excludes_granted(self):
        game, a, _ = self._game(seed=92)
        e = game.grant_random_trinket(a, kind="lesser")
        self.assertIsNotNone(e)
        d = game.db.get(e.card_id)
        self.assertEqual(d.spell_school, 11)             # lesser
        e2 = game.grant_random_trinket(a, kind="lesser")
        self.assertIsNotNone(e2)
        self.assertNotEqual(e.card_id, e2.card_id)       # 不重复

    def test_ledger_is_per_hero(self):
        """RULES §7.4.2 "a Trinket **you** already have" 是 per-player 口径:
        对手持有 X 不影响我的候选池/随机授予（2026-09-02 对抗审查修复:
        旧实现用 game 级并集，对手拿到 X 后我的池里 X 永久消失）。"""
        from hsrl2.scripts.batches.batch_trinkets9 import (
            ungranted_lesser_trinkets)
        game, a, _ = self._game(seed=93)
        b = game.heroes[1]
        pool_a = {d.id for d in ungranted_lesser_trinkets(game, a)}
        target = sorted(pool_a)[0]
        e = game.grant_trinket(b, target)
        self.assertIsNotNone(e)
        self.assertIn(target, b.trinkets_granted)
        self.assertNotIn(target, a.trinkets_granted)
        # 我的候选池仍含它，且随机授予仍可能给出（正对照）
        self.assertIn(target, {d.id for d in ungranted_lesser_trinkets(game, a)})
        # 已获得者本人再授予 → 幂等（负对照）
        self.assertIsNone(game.grant_trinket(b, target))
        self.assertIn(target, game._trinkets_granted)     # 聚合视图（观察用）

    def test_replace_trinket_swaps_entity(self):
        game, a, _ = self._game(seed=93)
        old = game.grant_trinket(a, self.LESSER)
        other = next(d.id for d in game.db.trinket_offer_pool()
                     if d.id != old.card_id
                     and d.id not in game._trinkets_granted)
        new = game.replace_trinket(a, old, other)
        self.assertNotIn(old, a.trinkets)
        self.assertIn(new, a.trinkets)

    def test_shop_purchase_fires_trinket_bought(self):
        from hsrl2.events import Listener
        game = make_game(seed=94)
        a = game.heroes[0]
        a.gold = 50
        a.set(GameTag.TAVERN_TIER, 6)
        seen = []
        game.events.register(Listener(
            event="trinket_bought", owner=a,
            callback=lambda g, **kw: seen.append(kw)))
        game._offer_trinkets(a, "lesser")
        choice = game.pending_choices.pop(0)
        choice.choose(0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "lesser")
        self.assertIn(seen[0]["trinket"], a.trinkets)


class TestTrinketCopyProtocol(unittest.TestCase):
    """RULES §7.4.3 副本条款 / §9.5 第二槽变饰品 — 复制协议。

    解锁: Souvenir Stand（`BG30_MagicItem_888`）、Crystal Ball 族
    （`BG35_Anomaly_007t`/`_008t`）——"transforms into a copy of it"
    需要**允许同一饰品两份副本**（跨局去重豁免）。
    """

    LESSER = "BG30_MagicItem_984"     # Charging Staff（已注册，在售池内）
    POWER = "BG20_HERO_103p"          # Bloodbound（已注册技能）

    def _game(self, seed=95):
        from hsrl2.scripts import REGISTRY
        game = make_game(seed=seed)
        calls = []

        class Probe:
            @staticmethod
            def on_bind(source, g, ctx):
                calls.append(source.card_id)

        self._orig = REGISTRY.get(self.LESSER)
        REGISTRY[self.LESSER] = Probe
        return game, game.heroes[0], calls

    def _cleanup(self):
        from hsrl2.scripts import REGISTRY
        if self._orig is None:
            REGISTRY.pop(self.LESSER, None)
        else:
            REGISTRY[self.LESSER] = self._orig

    def test_duplicate_grant_allows_two_live_copies(self):
        game, a, calls = self._game(seed=95)
        try:
            e1 = game.grant_trinket(a, self.LESSER)
            self.assertIsNone(game.grant_trinket(a, self.LESSER))  # 幂等
            e2 = game.grant_trinket(a, self.LESSER, duplicate=True)
            self.assertIsNotNone(e2)
            self.assertIsNot(e1, e2)
            self.assertEqual([x.card_id for x in a.trinkets],
                             [self.LESSER, self.LESSER])
            # 副本的 on_bind 也接线（两份同时生效）
            self.assertEqual(calls, [self.LESSER, self.LESSER])
        finally:
            self._cleanup()

    def test_copy_trinket_replaces_source_keeps_original_and_copy(self):
        """Souvenir Stand 形状: 持有本体 X + Stand → 复制 X（Stand 消失）。"""
        game, a, _ = self._game(seed=96)
        try:
            body = game.grant_trinket(a, self.LESSER)          # 已购本体
            stand = next(d.id for d in game.db.trinket_offer_pool()
                         if d.id != self.LESSER
                         and d.id not in game._trinkets_granted)
            stand_e = game.grant_trinket(a, stand)
            copy = game.copy_trinket(a, self.LESSER, replace=stand_e)
            self.assertNotIn(stand_e, a.trinkets)              # Stand 消失
            self.assertIn(body, a.trinkets)                    # 本体保留
            self.assertIn(copy, a.trinkets)                    # 副本存在
            self.assertEqual(
                [x.card_id for x in a.trinkets].count(self.LESSER), 2)
        finally:
            self._cleanup()

    def test_second_slot_trinket_occupies_slot_but_is_not_a_power(self):
        game, a, _ = self._game(seed=97)
        try:
            e = game.set_second_slot_trinket(a, self.LESSER)
            self.assertEqual(a._second_power_id, self.LESSER)  # 槽位被占
            self.assertIn(e, a.trinkets)                       # 实体可被扫描
            # 饰品不是技能: 不进可用技能表，也不会被误用扣费
            self.assertNotIn(self.LESSER, game.hero_power_ids(a))
            a.gold = 30
            self.assertFalse(game.use_hero_power(a, power_id=self.LESSER))
            self.assertEqual(a.gold, 30)
            # 槽位已占 → 不能再获得第二技能（fail-loud）
            with self.assertRaises(GameStateError):
                game.set_second_hero_power(a, self.POWER)
        finally:
            self._cleanup()

    def test_real_second_power_still_listed(self):
        """回归: 普通第二技能槽（HERO_POWER 卡）仍出现在可用技能表。"""
        game, a, _ = self._game(seed=98)
        try:
            game.set_second_hero_power(a, self.POWER)
            self.assertIn(self.POWER, game.hero_power_ids(a))
        finally:
            self._cleanup()


class TestRelatedCardGrant(unittest.TestCase):
    """RULES §7.4.6 — 饰品关联卡协议（"Get a <卡>" / "Cast <法术>" 族）。

    `CardDef.evolution_card_id` → `db.by_dbf` 解析关联卡（Portrait 族
    指向随从、Tome/Sticker 族指向法术）; 授予副本的池记账与 `{0}` 奖励
    副本（batch_quest_rewards4 `_grant_reward_copy`）同一口径。
    """

    PORTRAIT = "BG30_MagicItem_310"     # Get a Titus Rivendare
    PORTRAIT2 = "BG30_MagicItem_301"    # Get an Eternal Knight
    NO_RELATED = "BG30_MagicItem_407"   # Ship in a Bottle（无关联卡）

    def test_related_card_resolved_by_data_chain(self):
        game = make_game(seed=80)
        self.assertEqual(game.trinket_related_card(self.PORTRAIT).name,
                         "Titus Rivendare")
        self.assertEqual(game.trinket_related_card(self.PORTRAIT2).name,
                         "Eternal Knight")
        self.assertIsNone(game.trinket_related_card(self.NO_RELATED))
        self.assertIsNone(game.trinket_related_card("NO_SUCH_CARD"))

    def test_grant_pool_minion_acquires_and_whiffs_when_drained(self):
        game = make_game(seed=81)
        a = game.heroes[0]
        target = game.db.by_dbf(
            game.db.get(self.PORTRAIT).evolution_card_id)
        self.assertTrue(target.is_pool_minion)
        before = game.minion_pool.available(target.id)
        self.assertTrue(game.grant_trinket_related_card(a, self.PORTRAIT))
        self.assertEqual(game.minion_pool.available(target.id), before - 1)
        self.assertEqual(a.hand[-1].card_id, target.id)
        # 池抽空 → 落空（不再占用/不再给牌）
        hand_n = len(a.hand)
        while game.minion_pool.acquire(target.id):
            pass
        self.assertFalse(game.grant_trinket_related_card(a, self.PORTRAIT))
        self.assertEqual(len(a.hand), hand_n)

    def test_grant_non_pool_card_has_zero_pool_ops(self):
        """非池卡（token / 池外专属）→ 零池操作，总量不变。"""
        game = make_game(seed=82)
        a = game.heroes[0]
        token = next(d for d in game.db._by_id.values()
                     if d.card_type == CardType.MINION
                     and not d.is_pool_minion and d.tech_level <= 0)
        total_before = game.minion_pool.total_remaining()
        self.assertTrue(game.grant_card_copy_to_hand(a, token))
        self.assertEqual(a.hand[-1].card_id, token.id)
        self.assertEqual(game.minion_pool.total_remaining(), total_before)

    def test_grant_pool_spell_acquires(self):
        game = make_game(seed=83)
        a = game.heroes[0]
        spell = game.db.pool_spells()[0]
        before = game.spell_pool.available(spell.id)
        self.assertTrue(game.grant_card_copy_to_hand(a, spell))
        self.assertEqual(game.spell_pool.available(spell.id), before - 1)
        self.assertEqual(a.hand[-1].card_id, spell.id)

    def test_grant_copy_is_plain(self):
        """副本为白板（不复制任何 buff / 关键词强化）。"""
        game = make_game(seed=84)
        a = game.heroes[0]
        target = game.db.by_dbf(
            game.db.get(self.PORTRAIT).evolution_card_id)
        game.grant_trinket_related_card(a, self.PORTRAIT)
        copy = a.hand[-1]
        self.assertFalse(copy.is_golden)
        self.assertEqual(copy.atk, target.atk)
        self.assertEqual(copy.health, target.health)

    def test_unknown_card_def_whiffs(self):
        game = make_game(seed=85)
        self.assertFalse(game.grant_card_copy_to_hand(game.heroes[0], None))


class TestHeroPowerUseRefund(unittest.TestCase):
    """RULES §9.3 — 挂起期落空可回滚技能使用次数（防死技能）。"""

    POWER = "BG20_HERO_103p"        # Bloodbound（uses_per_turn=1，cost 1）

    def test_refund_restores_usability(self):
        game = Game([Hero("BG20_HERO_103", "Blackthorn"), make_hero("B")],
                    get_db(), seed=96)
        a = game.heroes[0]
        self.assertEqual(game.hero_power_def(a).id, self.POWER)
        a.gold = 30
        # Bloodbound: "Twice per turn"（uses_per_turn=2）
        self.assertTrue(game.use_hero_power(a))
        self.assertTrue(game.use_hero_power(a))
        self.assertFalse(game.use_hero_power(a))            # 本回合已用尽
        game.refund_hero_power_use(a, self.POWER)
        self.assertTrue(game.use_hero_power(a))             # 回滚后可再用
        self.assertFalse(game.use_hero_power(a))
        # 回滚不会把计数压成负数
        game.refund_hero_power_use(a, self.POWER)
        game.refund_hero_power_use(a, self.POWER)
        self.assertEqual(a._power_uses_this_turn.get(self.POWER, 0), 0)


class TestTierAura(unittest.TestCase):
    """RULES §6.19 — tier 维度光环原语（`game.add_tier_aura`）。

    "Your minions from Tier N or lower have +X/+Y"（BG30_MagicItem_843t
    Horde Keychain）——须对**任意入板路径**生效（summon / Transform /
    直接换入），而非只在 summon 时打 buff（2026-09-02 对抗审查）。
    """

    def _game(self, seed=101):
        game = make_game(seed=seed)
        a = game.heroes[0]
        src = game.create_entity("BG30_MagicItem_843t", controller=a)
        a.trinkets.append(src)
        game.add_tier_aura(src, 3, 7, 5)
        return game, a, src

    def test_aura_applies_on_summon_and_health_syncs(self):
        game, a, _src = self._game()
        m = Minion("TEST_T1", "T", atk=2, health=2)
        game.summon(a, m)
        self.assertEqual(m.atk, 9)
        self.assertEqual(m.max_health, 7)
        self.assertEqual(m.health, 7)
        # 已在场者: add_tier_aura 之后的当前血量同步（先召唤再注册）
        game2 = make_game(seed=102)
        a2 = game2.heroes[0]
        src2 = game2.create_entity("BG30_MagicItem_843t", controller=a2)
        a2.trinkets.append(src2)
        m2 = Minion("TEST_T2", "T", atk=1, health=1)
        game2.summon(a2, m2)
        self.assertEqual(m2.max_health, 1)
        game2.add_tier_aura(src2, 3, 0, 5)
        self.assertEqual(m2.max_health, 6)
        self.assertEqual(m2.health, 6)

    def test_aura_applies_after_transform(self):
        """Transform（直接改 board，不过 summon）——旧"入场打 buff"
        实现漏掉此路径。"""
        game, a, _src = self._game(seed=103)
        m = Minion("TEST_T3", "T", atk=1, health=1)
        m.set(GameTag.TECH_LEVEL, 5)
        game.summon(a, m)
        self.assertEqual(m.atk, 1)                    # T5 不在光环内
        m.set(GameTag.TECH_LEVEL, 2)                  # 变形为 T2
        self.assertEqual(m.atk, 8)
        self.assertEqual(m.max_health, 6)

    def test_aura_ignores_higher_tier_and_opponent(self):
        game, a, _src = self._game(seed=104)
        b = game.heroes[1]
        hi = Minion("TEST_T5", "H", atk=1, health=1)
        hi.set(GameTag.TECH_LEVEL, 5)
        game.summon(a, hi)
        self.assertEqual(hi.atk, 1)
        theirs = Minion("TEST_TO", "O", atk=1, health=1)
        game.summon(b, theirs)
        self.assertEqual(theirs.atk, 1)               # owner 隔离

    def test_aura_expires_when_source_leaves(self):
        game, a, src = self._game(seed=105)
        m = Minion("TEST_T6", "T", atk=1, health=1)
        game.summon(a, m)
        self.assertEqual(m.atk, 8)
        a.trinkets.remove(src)                        # 饰品被替换/移除
        self.assertEqual(m.atk, 1)                    # 光环自动失效


class TestCardGainedEvent(unittest.TestCase):
    """RULES §3.3 — hero 级 `card_gained`（"after you get a card"）。

    解锁 `BG35_MagicItem_713` Trusty Crowbar 类"获得卡牌"监听。
    """

    def test_event_fires_once_per_gain_with_owner(self):
        from hsrl2.events import Listener
        game = make_game(seed=118)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event="card_gained", owner=a,
            callback=lambda g, hero=None, card=None, **kw:
                seen.append((hero, card.card_id))))
        m = Minion("TEST_CG", "C", atk=1, health=1)
        game.pending_hand_add(a, m)
        self.assertEqual(seen, [(a, "TEST_CG")])
        # 事件按 hero 归属（owner 隔离在监听器的 condition 侧）
        m2 = Minion("TEST_CG2", "C", atk=1, health=1)
        game.pending_hand_add(b, m2)
        self.assertEqual(seen, [(a, "TEST_CG"), (b, "TEST_CG2")])
        # 带 condition 的监听器只看到本人
        mine = []
        game.events.register(Listener(
            event="card_gained", owner=a,
            condition=lambda hero=None, **kw: hero is a,
            callback=lambda g, hero=None, card=None, **kw:
                mine.append(card.card_id)))
        game.pending_hand_add(a, Minion("TEST_CG3", "C", atk=1, health=1))
        game.pending_hand_add(b, Minion("TEST_CG4", "C", atk=1, health=1))
        self.assertEqual(mine, ["TEST_CG3"])


class TestPermanentSpellcraftRule(unittest.TestCase):
    """RULES §6.13 — "Your <X>s' Spellcrafts are permanent" 规则原语。

    被动实体（饰品/奖励）注册 `add_permanent_spellcraft_rule`；生成
    Spellcraft 法术时按来源随从匹配 → 该次施放的 temporary buff 翻转为
    永久（且不再被 `_expire_at_next_turn` 回收）。
    """

    MAGE = "BG31_924"        # Thaumaturgist（Spellcraft: Give +N/+N until next turn）

    def _game(self, seed=115):
        game = make_game(seed=seed)
        a = game.heroes[0]
        src = game.create_entity("BG32_MagicItem_920", controller=a)
        a.trinkets.append(src)
        game.add_permanent_spellcraft_rule(
            a, src, lambda m: m.card_id == self.MAGE)
        return game, a, src

    def test_rule_marks_only_matching_source(self):
        game, a, _src = self._game()
        from hsrl2.spellcraft import generate_for_hero
        mage = game.create_minion(self.MAGE, controller=a)
        mage.set(GameTag.SPELLCRAFT, True)
        game.summon(a, mage)
        other = game.create_minion("BG23_000", controller=a)   # Mini Myrmidon
        other.set(GameTag.SPELLCRAFT, True)
        game.summon(a, other)
        generate_for_hero(a, game)
        spells = [c for c in a.hand if isinstance(c, Spell)]
        marks = {c.spellcraft_source_uuid:
                 getattr(c, "permanent_spellcraft", False) for c in spells}
        self.assertTrue(marks.get(mage.uuid))
        self.assertFalse(marks.get(other.uuid, False))

    def test_temporary_buff_becomes_permanent(self):
        game, a, _src = self._game(seed=116)
        from hsrl2.spellcraft import generate_for_hero
        mage = game.create_minion(self.MAGE, controller=a)
        mage.set(GameTag.SPELLCRAFT, True)
        game.summon(a, mage)
        target = game.create_minion("BG25_001", controller=a)
        game.summon(a, target)
        generate_for_hero(a, game)
        spell = next(c for c in a.hand
                     if isinstance(c, Spell)
                     and getattr(c, "spellcraft_source_uuid", None)
                     == mage.uuid)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertTrue(target._buffs)                    # 已获得 buff
        self.assertTrue(all(not b.temporary for b in target._buffs))
        # 下一回合开始不再回收（permanent）
        game._begin_recruit_for(a)
        self.assertTrue(target._buffs)
        self.assertTrue(all(not b.temporary for b in target._buffs))

    def test_rule_expires_when_source_leaves(self):
        game, a, src = self._game(seed=117)
        self.assertTrue(game._permanent_spellcraft_matches(
            a, game.create_minion(self.MAGE, controller=a)))
        a.trinkets.remove(src)
        self.assertFalse(game._permanent_spellcraft_matches(
            a, game.create_minion(self.MAGE, controller=a)))


class TestGrantCombatDeathrattle(unittest.TestCase):
    """RULES §3.5 — 战斗内授予亡语的引擎原语。

    原生亡语先结算、追加后置（Dark Gift 顺序）; `DEATHRATTLE` tag 由
    战斗快照回滚、`_script_overrides` 由 `run_combat` 统一恢复。
    """

    def _combat_with_death(self, seed, extra_fn, *, with_native=True):
        game = make_game(seed=seed)
        a, b = game.heroes
        order = []
        m = Minion("TEST_DR", "D", atk=1, health=1)

        class Native:
            @staticmethod
            def deathrattle(source, g, ctx):
                order.append("native")

        if with_native:
            m.scripts = Native
        game.summon(a, m)
        game.grant_combat_deathrattle(
            a, m, lambda s, g, c: extra_fn(order, s))
        enemy = Minion("TEST_DR_E", "E", atk=5, health=5)
        game.summon(b, enemy)
        game.run_combat(a, b)      # m（1 血）在战斗内被击杀
        return game, a, m, order

    def test_chained_order_and_post_combat_rollback(self):
        game, a, m, order = self._combat_with_death(
            112, lambda order, s: order.append("extra"))
        self.assertEqual(order, ["native", "extra"])       # 战内链式顺序
        # 战后 override 已由引擎恢复（再死亡只剩原生）
        self.assertIsNone(m._script_overrides.get("deathrattle"))
        order.clear()
        m.set(GameTag.HEALTH, 0)
        game.check_deaths()
        self.assertEqual(order, ["native"])

    def test_extra_actions_merge_with_native_result(self):
        from hsrl2.actions import GainGold
        gold = []

        def extra(order, source):
            order.append("extra")
            gold.append(source.controller.gold)

        game, a, m, order = self._combat_with_death(113, extra)
        self.assertEqual(order, ["native", "extra"])
        self.assertTrue(gold)          # 追加效果（Action）已生效

    def test_no_native_deathrattle_still_fires_extra(self):
        game, a, m, order = self._combat_with_death(
            114, lambda order, s: order.append("extra"),
            with_native=False)
        self.assertEqual(order, ["extra"])


class TestBattlecryFirstQuota(unittest.TestCase):
    """RULES §6.20 — `bc_first`: 每回合前 N 个战吼各额外触发一次。

    与 `bc_times`（永久全量）分开：脚本侧用 `bc_first` 即可实现
    "Your first N Battlecries each turn trigger an extra time"
    （War Drum），不会覆盖 Gilnean War Horn 的同 key 额度。
    """

    def test_first_n_each_turn_then_resets(self):
        game = make_game(seed=110)
        a = game.heroes[0]
        calls = []

        class Probe:
            @staticmethod
            def battlecry(source, g, ctx):
                calls.append(source.card_id)

        a.extra_triggers["bc_first"] = 1
        for _ in range(2):
            m = Minion("TEST_BC", "B", atk=1, health=1)
            m.set(GameTag.BATTLECRY, True)
            m.scripts = Probe
            a.add_to_hand(m)
            game.play_minion(a, m)
        # 本回合: 第 1 个战吼触发 2 次，第 2 个只 1 次
        self.assertEqual(len(calls), 3)
        # 下一回合重置 → 又是 2 次
        calls.clear()
        game._begin_recruit_for(a)
        m = Minion("TEST_BC2", "B", atk=1, health=1)
        m.set(GameTag.BATTLECRY, True)
        m.scripts = Probe
        a.add_to_hand(m)
        game.play_minion(a, m)
        self.assertEqual(len(calls), 2)

    def test_bc_first_times_multiplies_extra_triggers(self):
        """`bc_first_times` = 每次额外触发几次（War Drum 36.2.2
        "triggers **two** extra times" → 首个战吼共触发 3 次）。"""
        game = make_game(seed=112)
        a = game.heroes[0]
        calls = []

        class Probe:
            @staticmethod
            def battlecry(source, g, ctx):
                calls.append(1)

        a.extra_triggers["bc_first"] = 1
        a.extra_triggers["bc_first_times"] = 2
        m = Minion("TEST_BC5", "B", atk=1, health=1)
        m.set(GameTag.BATTLECRY, True)
        m.scripts = Probe
        a.add_to_hand(m)
        game.play_minion(a, m)
        self.assertEqual(len(calls), 3)          # 1 + 2 extra
        calls.clear()
        m2 = Minion("TEST_BC6", "B", atk=1, health=1)
        m2.set(GameTag.BATTLECRY, True)
        m2.scripts = Probe
        a.add_to_hand(m2)
        game.play_minion(a, m2)
        self.assertEqual(len(calls), 1)          # 每回合只 1 个战吼享额

    def test_bc_first_does_not_overwrite_bc_times(self):
        game = make_game(seed=111)
        a = game.heroes[0]
        calls = []

        class Probe:
            @staticmethod
            def battlecry(source, g, ctx):
                calls.append(1)

        a.extra_triggers["bc_times"] = 1          # 永久全量（War Horn）
        a.extra_triggers["bc_first"] = 1          # 每回合前 1 次
        m = Minion("TEST_BC3", "B", atk=1, health=1)
        m.set(GameTag.BATTLECRY, True)
        m.scripts = Probe
        a.add_to_hand(m)
        game.play_minion(a, m)
        self.assertEqual(len(calls), 3)           # 1 + bc_times 1 + bc_first 1
        calls.clear()
        m2 = Minion("TEST_BC4", "B", atk=1, health=1)
        m2.set(GameTag.BATTLECRY, True)
        m2.scripts = Probe
        a.add_to_hand(m2)
        game.play_minion(a, m2)
        self.assertEqual(len(calls), 2)           # bc_first 已用完，bc_times 仍在


class TestCastSpellEffect(unittest.TestCase):
    """RULES §6.16 注 — 效果施法（"Cast X"）统一入口。

    不经手牌/不计费/不动法术池/不广播手牌事件; 定向法术无合法目标
    落空而不抛错（避免中断回合）。
    """

    SHINY = "BG28_168"        # Shiny Ring（池法术，+攻/+血，定向?）
    SSPELL = "BG28_897"       # Tavern Dish Banana（定向 +2/+2）

    def test_cast_pool_spell_without_pool_or_hand_changes(self):
        game = make_game(seed=106)
        a = game.heroes[0]
        m = Minion("TEST_CS_T", "T", atk=1, health=1)
        game.summon(a, m)
        pool_before = game.spell_pool.available(self.SSPELL)
        hand_before = len(a.hand)
        gold_before = a.gold
        self.assertTrue(game.cast_spell_effect(a, self.SSPELL, target=m))
        self.assertEqual(game.spell_pool.available(self.SSPELL), pool_before)
        self.assertEqual(len(a.hand), hand_before)
        self.assertEqual(a.gold, gold_before)
        self.assertEqual((m.atk, m.max_health), (3, 3))     # +2/+2 生效

    def test_no_target_whiffs_without_crash(self):
        game = make_game(seed=107)
        a = game.heroes[0]
        self.assertFalse(game.cast_spell_effect(a, self.SSPELL))  # 空板

    def test_random_target_when_candidates_exist(self):
        game = make_game(seed=108)
        a = game.heroes[0]
        m = Minion("TEST_CS_T2", "T", atk=2, health=2)
        game.summon(a, m)
        self.assertTrue(game.cast_spell_effect(a, self.SSPELL))
        self.assertEqual((m.atk, m.max_health), (4, 4))

    def test_unknown_or_non_spell_card_refused(self):
        game = make_game(seed=109)
        a = game.heroes[0]
        self.assertFalse(game.cast_spell_effect(a, "NO_SUCH_CARD"))
        self.assertFalse(game.cast_spell_effect(a, "BG25_001"))  # 随从


class TestVenomousLossEvent(unittest.TestCase):
    """RULES §3.5 — Venomous 消耗 = "loses Venomous" 广播 KEYWORD_LOST。

    解锁 `BG30_MagicItem_432` Belcher Portrait（"Whenever a friendly
    minion loses Venomous, it gains +4/+4 permanently"）。旧实现只在
    内部置 `VENOMOUS_CONSUMED` tag，无任何可监听信号。
    """

    def test_venomous_kill_fires_keyword_lost(self):
        from hsrl2.events import KEYWORD_LOST, Listener
        game = make_game(seed=97)
        a, b = game.heroes
        seen = []
        game.events.register(Listener(
            event=KEYWORD_LOST, owner=a,
            callback=lambda g, minion=None, tag=None, **kw:
                seen.append((minion, tag,
                             minion.get(GameTag.VENOMOUS_CONSUMED, False)))))
        atk = Minion("TEST_VENOM_A", "VA", atk=3, health=3)
        atk.set(GameTag.VENOMOUS, True)
        vic = Minion("TEST_VENOM_D", "VD", atk=1, health=9)
        game.summon(a, atk)
        game.summon(b, vic)
        game.run_combat(a, b)
        venom_events = [x for x in seen if x[1] == GameTag.VENOMOUS]
        self.assertEqual(len(venom_events), 1)              # 恰好一次
        self.assertIs(venom_events[0][0], atk)
        # 事件触发**时**消耗标记已置位（战后棋盘复原会清除实体状态）
        self.assertTrue(venom_events[0][2])
        # 对照: 无 Venomous 的战斗不广播
        game2 = make_game(seed=98)
        a2, b2 = game2.heroes
        seen2 = []
        game2.events.register(Listener(
            event=KEYWORD_LOST, owner=a2,
            callback=lambda g, **kw: seen2.append(kw)))
        p1 = Minion("TEST_P1", "P1", atk=2, health=5)
        p2 = Minion("TEST_P2", "P2", atk=2, health=5)
        game2.summon(a2, p1)
        game2.summon(b2, p2)
        game2.run_combat(a2, b2)
        self.assertEqual(seen2, [])


class TestTrinketSpellcraftGeneration(unittest.TestCase):
    """RULES §6.13 — 饰品/任务奖励的 Spellcraft 也每回合生成法术。

    解锁 `BG30_MagicItem_429` Demonblood Gourd。旧实现只扫 `hero.board`。
    """

    GOURD = "BG30_MagicItem_429"
    SPELL = "BG30_MagicItem_429t"

    def test_trinket_generates_spellcraft_spell_each_turn(self):
        game = make_game(seed=99)
        a = game.heroes[0]
        self.assertIsNotNone(game.db.get(self.GOURD).spellcraft_id)
        e = game.grant_trinket(a, self.GOURD)
        self.assertIsNotNone(e)
        self.assertTrue(e.has(GameTag.SPELLCRAFT))       # create_entity 打标
        from hsrl2.spellcraft import generate_for_hero
        generate_for_hero(a, game)
        spells = [c for c in a.hand if isinstance(c, Spell)
                  and c.card_id == self.SPELL]
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))
        # 未使用的临时法术回合结束丢弃（正对照: 生成→丢弃闭环）
        victim = spells[0]
        game.end_recruit_phase()
        self.assertNotIn(victim, a.hand)
        self.assertEqual(victim.zone, Zone.REMOVED)

    def test_unplayed_gourd_spell_is_targeted(self):
        game = make_game(seed=100)
        a = game.heroes[0]
        game.grant_trinket(a, self.GOURD)
        from hsrl2.scripts import REGISTRY
        self.assertIsNotNone(REGISTRY.get(self.SPELL))
        d = game.db.get(self.SPELL)
        self.assertEqual(d.card_type, CardType.SPELL)


class TestSpellcraftMinionHandSurvival(unittest.TestCase):
    """RULES §6.13 — 回合结束只丢弃 **Spellcraft 法术**。

    回归（2026-09-02 对抗审查）: `create_minion` 给带 `spellcraft_id` 的
    随从也打 SPELLCRAFT tag，旧丢弃逻辑按 tag 判定 → 手牌里的法术塑造
    随从（如 BG27_514 Sea Witch Zar'jira）被当成法术销毁。
    """

    ZARJIRA = "BG27_514"        # Sea Witch Zar'jira（Spellcraft 随从）

    def test_spellcraft_minion_in_hand_survives_end_of_turn(self):
        game = make_game(seed=94)
        a = game.heroes[0]
        d = game.db.get(self.ZARJIRA)
        self.assertIsNotNone(d.spellcraft_id)           # 数据前提
        m = game.create_minion(self.ZARJIRA, controller=a)
        game.pending_hand_add(a, m)
        self.assertTrue(m.has(GameTag.SPELLCRAFT))
        game.end_recruit_phase()
        self.assertIn(m, a.hand)
        self.assertNotEqual(m.zone, Zone.REMOVED)

    def test_generated_spellcraft_spell_still_discarded(self):
        """正对照: 该随从在**棋盘上**时每回合生成的临时法术仍被丢弃。"""
        game = make_game(seed=95)
        a = game.heroes[0]
        m = game.create_minion(self.ZARJIRA, controller=a)
        m.set(GameTag.SPELLCRAFT, True)
        game.summon(a, m)
        from hsrl2.spellcraft import generate_for_hero
        generate_for_hero(a, game)
        spells = [c for c in a.hand if isinstance(c, Spell)]
        self.assertTrue(spells)                          # 已生成
        victim = spells[0]
        self.assertTrue(victim.has(GameTag.SPELLCRAFT))
        game.end_recruit_phase()
        # 未使用的临时法术被丢弃（下一回合开始会为新回合再生成一张，
        # 故断言"原实体已离手且 zone=REMOVED"而非"手牌无法术"）
        self.assertNotIn(victim, a.hand)
        self.assertEqual(victim.zone, Zone.REMOVED)


class TestPoolCandidateTierCap(unittest.TestCase):
    """RULES §2.4 修订 — 随机/发现获取的档位上限 = `max_tavern_tier`。

    2026-09-02 对抗审查: "Get a random <race> minion" 族可抽到 Tier 7
    （实测 8.7%），越出标准局（T6 封顶）可得范围; 显式 "Tier 7" 卡不受
    影响。
    """

    def test_candidates_capped_at_max_tavern_tier(self):
        from hsrl2.actions.discover import _pool_candidates
        from hsrl2.actions import GetRandomMinion
        game = make_game(seed=91)
        self.assertEqual(game.max_tavern_tier, 6)
        cands = _pool_candidates(game)
        tiers = {game.db.get(c).tech_level for c in cands}
        self.assertNotIn(7, tiers)
        self.assertIn(6, tiers)                      # 上限保留 6（正对照）
        self.assertTrue(cands)
        # 显式 Tier 7 请求仍可越档
        t7 = _pool_candidates(game, min_tier=7)
        self.assertTrue(all(game.db.get(c).tech_level == 7 for c in t7))

    def test_get_random_minion_never_grants_tier7(self):
        from hsrl2.actions import GetRandomMinion
        game = make_game(seed=92)
        a = game.heroes[0]
        for _ in range(60):
            before = len(a.hand)
            GetRandomMinion(a).do(game)
            for m in a.hand[before:]:
                self.assertLessEqual(m.tech_level, 6, m.card_id)

    def test_discover_explicit_candidates_capped(self):
        from hsrl2.actions import Discover
        game = make_game(seed=93)
        a = game.heroes[0]
        t7 = next(d.id for d in game.db.pool_minions() if d.tech_level == 7)
        t1 = next(d.id for d in game.db.pool_minions() if d.tech_level == 1)
        Discover(a, count=3, candidates=[t7, t1]).do(game)
        ch = game.pending_choices[-1]
        self.assertNotIn(t7, ch.options)
        self.assertIn(t1, ch.options)


class TestHealthPurchaseProtocol(unittest.TestCase):
    """RULES §7.4.7 — "costs Health instead of Gold to buy" 协议。

    三种来源: 卡自身 `health_cost`（Hasty Excavation）/ 实体级
    `HEALTH_BUY`（BG35_MagicItem_152）/ 英雄级本回合配额
    （BG32_MagicItem_821 恶魔、822 酒馆法术）。均为强制（不提供金币
    备选），生命不足 → 购买失败且不消费配额。
    """

    def _game(self, seed=86):
        game = make_game(seed=seed)
        return game, game.heroes[0]

    @staticmethod
    def _pool_minion(db, *, race=None):
        for d in sorted(db.pool_minions(), key=lambda x: x.id):
            if race is not None and d.race != race:
                continue
            if db.golden_version(d) is None:
                continue
            return d
        raise AssertionError("no pool minion")

    def test_minion_quota_pays_health_and_matches_race(self):
        game, a = self._game()
        demon = self._pool_minion(game.db, race=Race.DEMON)
        beast = self._pool_minion(game.db, race=Race.BEAST)
        a.set(GameTag.HEALTH_MINION_BUYS_THIS_TURN, 1)
        a.set(GameTag.HEALTH_BUY_RACE, Race.DEMON)
        a.gold, a.health = 50, 40
        # 不匹配种族 → 走金币，配额保留
        m_beast = game.inject_tavern_minion(a, beast.id)
        self.assertTrue(game.buy_from_tavern(a, m_beast))
        self.assertEqual(a.gold, 50 - (m_beast.get(GameTag.COST, 3)))
        self.assertEqual(a.health, 40)
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 1)
        # 匹配种族 → 扣生命不扣金币，配额消费
        m_demon = game.inject_tavern_minion(a, demon.id)
        cost = m_demon.get(GameTag.COST, 3)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, m_demon))
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.health, 40 - cost)
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 0)
        # 配额耗尽 → 第二只恶魔回到金币
        m_demon2 = game.inject_tavern_minion(a, demon.id)
        self.assertTrue(game.buy_from_tavern(a, m_demon2))
        self.assertEqual(a.gold, gold_before - (m_demon2.get(GameTag.COST, 3)))

    def test_spell_quota_pays_health(self):
        game, a = self._game(seed=87)
        spell = game.db.pool_spells()[0]
        a.set(GameTag.HEALTH_SPELL_BUYS_THIS_TURN, 1)
        a.gold, a.health = 50, 40
        s = game.create_spell(spell.id, controller=a)
        s.zone = Zone.TAVERN
        a.tavern.append(s)
        cost = s.get(GameTag.COST, 3)
        self.assertTrue(game.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 50)                 # 未花金币
        self.assertEqual(a.health, 40 - cost)
        self.assertEqual(a.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN), 0)

    def test_entity_tag_pays_health(self):
        game, a = self._game(seed=88)
        target = self._pool_minion(game.db)
        a.gold, a.health = 50, 40
        m = game.inject_tavern_minion(a, target.id)
        m.set(GameTag.HEALTH_BUY, True)
        cost = m.get(GameTag.COST, 3)
        self.assertTrue(game.buy_from_tavern(a, m))
        self.assertEqual(a.gold, 50)
        self.assertEqual(a.health, 40 - cost)

    def test_insufficient_health_fails_and_keeps_quota(self):
        game, a = self._game(seed=89)
        demon = self._pool_minion(game.db, race=Race.DEMON)
        a.set(GameTag.HEALTH_MINION_BUYS_THIS_TURN, 1)
        a.set(GameTag.HEALTH_BUY_RACE, Race.DEMON)
        a.gold, a.health = 50, 1                     # 生命不足（且不能致死）
        m = game.inject_tavern_minion(a, demon.id)
        self.assertFalse(game.buy_from_tavern(a, m))
        self.assertIn(m, a.tavern)                   # 未成交
        self.assertEqual(a.health, 1)
        self.assertEqual(a.gold, 50)
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 1)

    def test_free_purchase_does_not_consume_health_quota(self):
        """免费购买（cost 0）不得趁机消费生命代金配额（守卫回归）。"""
        game, a = self._game(seed=90)
        demon = self._pool_minion(game.db, race=Race.DEMON)
        a.set(GameTag.HEALTH_MINION_BUYS_THIS_TURN, 1)
        a.set(GameTag.HEALTH_BUY_RACE, Race.DEMON)
        a.set(GameTag.FREE_MINION_BUYS_THIS_TURN, 1)
        a.gold, a.health = 50, 40
        m = game.inject_tavern_minion(a, demon.id)
        self.assertTrue(game.buy_from_tavern(a, m))
        self.assertEqual(a.gold, 50)
        self.assertEqual(a.health, 40)               # 免费，未扣生命
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 1)


class TestFreePurchaseProtocol(unittest.TestCase):
    """RULES §7.4.4 — 免费购买协议（种族/关键词限定的随从、酒馆法术）。"""

    M = "BG25_001"          # Risen Rider（T1）
    SPELL = "BG28_168"      # Shiny Ring（池法术）

    def _game(self, seed=95):
        game = make_game(seed=seed)
        a = game.heroes[0]
        a.gold = 20
        return game, a

    def _tavern_minion(self, game, a, card_id=None, race=None):
        m = game.create_minion(card_id or self.M, controller=a)
        if race is not None:
            m.set(GameTag.RACE, race)
        m.zone = Zone.TAVERN
        a.tavern = [m]
        return m

    def test_free_spell_buy_costs_zero_and_decrements(self):
        game, a = self._game()
        s = game.create_spell(self.SPELL, controller=a)
        s.zone = Zone.TAVERN
        a.tavern = [s]
        a.set(GameTag.FREE_SPELL_BUYS_THIS_TURN, 1)
        self.assertTrue(game.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 20)                       # 免费
        self.assertEqual(a.get(GameTag.FREE_SPELL_BUYS_THIS_TURN), 0)
        # 第二张正常收费（正对照）
        s2 = game.create_spell(self.SPELL, controller=a)
        s2.zone = Zone.TAVERN
        a.tavern = [s2]
        self.assertTrue(game.buy_from_tavern(a, s2))
        self.assertLess(a.gold, 20)

    def test_race_limited_free_buy_only_matches_race(self):
        game, a = self._game()
        a.set(GameTag.FREE_MINION_BUYS_THIS_TURN, 1)
        a.set(GameTag.FREE_MINION_BUY_RACE, int(Race.PIRATE))
        other = self._tavern_minion(game, a, race=Race.BEAST)
        self.assertTrue(game.buy_from_tavern(a, other))
        self.assertLess(a.gold, 20)                        # 不匹配 → 收费
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 1)
        pirate = self._tavern_minion(game, a, race=Race.PIRATE)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, pirate))
        self.assertEqual(a.gold, gold_before)              # 匹配 → 免费
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 0)

    def test_keyword_limited_free_buy(self):
        game, a = self._game()
        a.set(GameTag.FREE_MINION_BUYS_THIS_TURN, 1)
        a.set(GameTag.FREE_MINION_BUY_KEYWORD,
              int(GameTag.BATTLECRY))
        plain = self._tavern_minion(game, a)
        self.assertTrue(game.buy_from_tavern(a, plain))
        self.assertLess(a.gold, 20)
        bc = self._tavern_minion(game, a)
        bc.set(GameTag.BATTLECRY, True)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, bc))
        self.assertEqual(a.gold, gold_before)

    def test_failed_free_purchase_keeps_counter(self):
        """成交才消费: 手牌满时的失败购买不得烧掉免费次数。"""
        game, a = self._game()
        a.set(GameTag.FREE_MINION_BUYS_THIS_TURN, 1)
        while not a.hand_full():
            a.add_to_hand(game.create_spell(self.SPELL, controller=a))
        m = self._tavern_minion(game, a)
        self.assertFalse(game.buy_from_tavern(a, m))
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN), 1)

    def test_two_independent_quotas_do_not_overwrite(self):
        """多来源独立配额（RULES §7.4.4 修订）: "海盗免费"与"战吼免费"
        并存时各自生效——旧单 tag 模型会退化成"海盗战吼才免费"。"""
        game, a = self._game(seed=96)
        game.set_free_minion_buys(a, 2, source="warcry",
                                  keyword=int(GameTag.BATTLECRY))
        game.set_free_minion_buys(a, 1, source="grifter",
                                  race=int(Race.PIRATE))
        self.assertEqual(game.free_minion_buys_left(a), 3)
        # 非海盗战吼 → 命中 warcry 配额（免费）
        bc = self._tavern_minion(game, a)
        bc.set(GameTag.BATTLECRY, True)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, bc))
        self.assertEqual(a.gold, gold_before)
        # 海盗（非战吼）→ 命中 grifter 配额（免费）
        pirate = self._tavern_minion(game, a, race=Race.PIRATE)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, pirate))
        self.assertEqual(a.gold, gold_before)
        # 第二个战吼仍免费（warcry 2 次额度），第三个收费
        bc2 = self._tavern_minion(game, a)
        bc2.set(GameTag.BATTLECRY, True)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, bc2))
        self.assertEqual(a.gold, gold_before)
        bc3 = self._tavern_minion(game, a)
        bc3.set(GameTag.BATTLECRY, True)
        self.assertTrue(game.buy_from_tavern(a, bc3))
        self.assertLess(a.gold, gold_before)
        self.assertEqual(game.free_minion_buys_left(a), 0)

    def test_quota_expires_next_turn(self):
        """配额仅本回合有效（跨回合自动失效，不残留）。"""
        game, a = self._game(seed=97)
        game.set_free_minion_buys(a, 1, source="warcry",
                                  keyword=int(GameTag.BATTLECRY))
        self.assertEqual(game.free_minion_buys_left(a), 1)
        game.turn += 1
        self.assertEqual(game.free_minion_buys_left(a), 0)
        bc = self._tavern_minion(game, a)
        bc.set(GameTag.BATTLECRY, True)
        gold_before = a.gold
        self.assertTrue(game.buy_from_tavern(a, bc))
        self.assertLess(a.gold, gold_before)


class TestDiscountAndSellOverrides(unittest.TestCase):
    """持久法术折扣 / 英雄级出售价 / 额外法术展示位（RULES §7.4.5）。"""

    SPELL = "BG28_168"

    def _game(self, seed=96):
        game = make_game(seed=seed)
        a = game.heroes[0]
        a.gold = 20
        return game, a, game.heroes[1]

    def test_persistent_tavern_spell_discount(self):
        game, a, b = self._game()
        base = game.db.get(self.SPELL).cost
        a.set(GameTag.TAVERN_SPELL_COST_MOD, 1)
        s = game.create_spell(self.SPELL, controller=a)
        s.zone = Zone.TAVERN
        a.tavern = [s]
        self.assertTrue(game.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 20 - max(0, base - 1))
        # 持久: 第二张仍享受折扣（正对照）
        s2 = game.create_spell(self.SPELL, controller=a)
        s2.zone = Zone.TAVERN
        a.tavern = [s2]
        self.assertTrue(game.buy_from_tavern(a, s2))
        self.assertEqual(a.gold, 20 - 2 * max(0, base - 1))

    def test_hero_level_sell_override(self):
        game, a, b = self._game()
        m = game.create_minion("BG25_001", controller=a)
        game.summon(a, m)
        a.set(GameTag.SELL_VALUE_OVERRIDE, 0)
        gold_before = a.gold
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.gold, gold_before)          # 卖 0 金
        # 实体自身 tag 优先（正对照）
        m2 = game.create_minion("BG25_001", controller=a)
        m2.set(GameTag.SELL_VALUE, 2)
        game.summon(a, m2)
        gold2 = a.gold
        self.assertTrue(game.sell_minion(a, m2))
        self.assertEqual(a.gold, gold2 + 2)

    def test_hero_level_extra_tavern_spell_slot(self):
        game, a, b = self._game()
        game.refresh_tavern(a, free=True)
        base = len([e for e in a.tavern if not isinstance(e, Minion)])
        a._tavern_spell_extra = 1
        a.gold = 20
        game.refresh_tavern(a, free=True)
        now = len([e for e in a.tavern if not isinstance(e, Minion)])
        self.assertEqual(now, base + 1)
        # 对手不受影响（hero 作用域）
        game.refresh_tavern(b, free=True)
        self.assertEqual(len([e for e in b.tavern
                              if not isinstance(e, Minion)]), base)

class TestMinionPlayedEvent(unittest.TestCase):
    """ENGINE_BACKLOG #21: `MINION_PLAYED` 由死常量变为真实生产点（2026-09-14）。

    语义: **从手牌打出**随从（含磁力吸附）→ fire `minion_played(minion=)`;
    效果召唤（`summon`）不算"打出"，不得 fire（负对照）。
    """

    def _spy(self, game):
        from hsrl2.events import MINION_PLAYED, Listener
        seen = []
        game.events.register(Listener(
            event=MINION_PLAYED, owner=None,
            callback=lambda g, **kw: seen.append(kw.get("minion"))))
        return seen

    def test_hand_play_fires_minion_played(self):
        game = make_game(seed=4242)
        a = game.heroes[0]
        seen = self._spy(game)
        m = game.create_minion("BG20_100", controller=a)
        a.hand.append(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([x.uuid for x in seen], [m.uuid])

    def test_failed_play_fires_nothing(self):
        """负对照: 打出未成功（不在手牌）→ 不得 fire（第二十五轮验证者
        指出的覆盖缺口; 战斗/失败路径不得产生事件）。"""
        game = make_game(seed=4245)
        a = game.heroes[0]
        seen = self._spy(game)
        not_in_hand = game.create_minion("BG20_100", controller=a)
        self.assertFalse(game.play_minion(a, not_in_hand))
        self.assertEqual(seen, [])

    def test_effect_summon_does_not_fire(self):
        """负对照: `summon`（效果召唤）不是"打出"。"""
        game = make_game(seed=4243)
        a = game.heroes[0]
        seen = self._spy(game)
        m = game.create_minion("BG20_100", controller=a)
        self.assertTrue(game.summon(a, m))
        self.assertEqual(seen, [])


class TestTripleMergedListenerCleanup(unittest.TestCase):
    """三连合并后必须注销被并随从的监听器（第二十七轮对抗验证发现）。

    缺陷: `check_for_triple._combine` 把被并随从移出 board/hand 并置
    `Zone.REMOVED`，但未 `events.unregister_owner` → 其监听器永久残留。
    可观察后果: 3 张 `BG28_741`（Charging Czarina）三连后，施放酒馆法术
    时金色随从被 buff +20 攻（3 个残留基础监听器各 +4 与金色自身 +8），
    正确值应为 +8。
    """

    def _play(self, game, hero, card_id):
        m = game.create_minion(card_id, controller=hero)
        hero.hand.append(m)
        assert game.play_minion(hero, m)
        return m

    def _cast(self, game, hero, card_id="BG28_810"):
        sp = game.create_spell(card_id, controller=hero)
        hero.hand.append(sp)
        assert game.play_spell(hero, sp)

    def test_merged_minions_lose_listeners(self):
        game = make_game(seed=9701)
        a = game.heroes[0]
        merged = [self._play(game, a, "BG28_741") for _ in range(2)]
        self._play(game, a, "BG28_741")                  # 第 3 张 → 三连
        golden = next(m for m in a.board if m.is_golden)
        self.assertEqual(golden.card_id, "BG28_741_G")
        owners = [l.owner for ls in game.events._listeners.values()
                  for l in ls]
        for m in merged:
            self.assertNotIn(m, a.board)
            self.assertNotIn(m, owners, "被并随从监听器未注销")

    def test_golden_buff_is_not_multi_counted(self):
        """正对照（数值）: 三连后金色只按自身 num(0)=8 生效。"""
        game = make_game(seed=9702)
        a = game.heroes[0]
        for _ in range(2):
            self._play(game, a, "BG28_741")
        self._play(game, a, "BG28_741")
        golden = next(m for m in a.board if m.is_golden)
        before = golden.atk
        self._cast(game, a)
        self.assertEqual(golden.atk - before, 8)


class TestLeavePlayListenerInvariant(unittest.TestCase):
    """离场即注销监听器（ENGINE_BACKLOG #40）——`Entity.zone` 是唯一收口。

    缺陷: 监听器生命周期原本依赖每个离场路径**显式**调用
    `events.unregister_owner`。Double Stitch（棋盘→手牌）与 Expert Aviator
    战斗副本（→REMOVED）两处漏调用 → 离场随从的 `HERO_DAMAGE_TAKEN`
    回退监听继续触发（英雄伤害被无限回退; 压测 seed 909199 冻结即此族）。
    修复: `Entity.zone` setter 在 **随从** `Zone.PLAY → 非 PLAY/非
    SETASIDE`、以及**随从从任何区域进入 `REMOVED`/`GRAVEYARD`** 时自动
    注销（后者覆盖 Malygos Arcane Alteration 的手牌→REMOVED 等从未上过
    棋盘的路径）; `Zone.SETASIDE`（复生处理期间的临时离场，同一实体稍后
    回 `Zone.PLAY` 且不重跑 `on_summon`）为例外。法术不在"任何区域→
    REMOVED"之列——法术从不进入 `PLAY`，其 owner 监听器是效果期接线
    （见 `ChillmereMosaicSpellScript` 的 `TURN_END` 清除）。
    探针实体: `BG26_174` Soul Rewinder——`on_summon` 注册
    `HERO_DAMAGE_TAKEN` 回退监听（可用英雄受伤是否被回退直接观测）。
    """

    REWINDER = "BG26_174"

    def _summon(self, game, hero):
        m = game.create_minion(self.REWINDER, controller=hero)
        assert game.summon(hero, m)
        return m

    def _owners(self, game):
        return [l.owner for l in game.events._listeners.get(
            HERO_DAMAGE_TAKEN, [])]

    def test_board_to_hand_unregisters(self):
        game = make_game(seed=9801)
        a = game.heroes[0]
        m = self._summon(game, a)
        self.assertIn(m, self._owners(game))
        a.board.remove(m)
        self.assertTrue(a.add_to_hand(m))
        self.assertEqual(m.zone, Zone.HAND)
        self.assertNotIn(m, self._owners(game))

    def test_board_to_tavern_unregisters(self):
        game = make_game(seed=9802)
        a = game.heroes[0]
        m = self._summon(game, a)
        a.board.remove(m)
        game.add_tavern_entity(a, m)
        self.assertEqual(m.zone, Zone.TAVERN)
        self.assertNotIn(m, self._owners(game))

    def test_board_to_removed_unregisters(self):
        game = make_game(seed=9803)
        a = game.heroes[0]
        m = self._summon(game, a)
        a.board.remove(m)
        m.zone = Zone.REMOVED
        self.assertNotIn(m, self._owners(game))

    def test_on_board_keeps_listener(self):
        """负对照: 未离场者监听器保留且回退仍生效。"""
        game = make_game(seed=9804)
        a = game.heroes[0]
        m = self._summon(game, a)
        self.assertIn(m, self._owners(game))
        before = (a.health, a.armor)
        a.take_damage(3)
        self.assertEqual((a.health, a.armor), before)   # 伤害被回退
        self.assertIn(m, self._owners(game))            # 监听器仍在

    def test_reborn_setaside_keeps_listener(self):
        """例外: 复生处理期间的 SETASIDE 临时离场不注销（否则复生后
        被动永久失效——`_process_single_death` 不重跑 `on_summon`）。"""
        game = make_game(seed=9805)
        a = game.heroes[0]
        m = self._summon(game, a)
        a.board.remove(m)
        m.zone = Zone.SETASIDE
        self.assertIn(m, self._owners(game))
        m.zone = Zone.PLAY
        a.board.append(m)
        self.assertIn(m, self._owners(game))

    def test_persistent_owner_listeners_unaffected(self):
        """英雄（持久身份）的监听器不因随从离场而失效; 且离场注销只移除
        **该实体为 owner** 的监听器，不误伤引用它的他者监听器。"""
        game = make_game(seed=9806)
        a = game.heroes[0]
        hero_hits = []
        game.events.register(Listener(
            event=HERO_DAMAGE_TAKEN, owner=a,
            callback=lambda g, **kw: hero_hits.append(1)))
        m = self._summon(game, a)
        a.board.remove(m)
        m.zone = Zone.REMOVED
        self.assertNotIn(m, self._owners(game))   # 随从自身监听器注销
        self.assertIn(a, self._owners(game))      # 英雄监听器保留
        a.take_damage(3)
        self.assertEqual(hero_hits, [1])

    def test_combat_transform_replay_drops_old_entity_listeners(self):
        """战斗内 Transform 的旧实体在战后重放中必须保持离场（监听器不
        被 `run_combat` 的监听器表快照复原复活）。

        真实路径: 真实 `summon`（Rewinder 注册 `HERO_DAMAGE_TAKEN`）→
        真实 `run_combat`（`start_of_combat` 真实广播内执行真实
        `Transform` action）→ 战后重放把新实体换回棋盘。
        断言: 旧实体 `zone=REMOVED`、不在棋盘、监听器已注销。
        变异探针: 去掉战后重放里的 `old.zone = Zone.REMOVED` → 旧实体
        zone 停在 `PLAY`（静默第三态）且监听器被快照复原。
        """
        from hsrl2.actions.stats import Transform
        from hsrl2.events import START_OF_COMBAT
        game = make_game(seed=9808)
        a, b = game.heroes
        rewinder = self._summon(game, a)
        game.summon(b, game.create_minion("BG20_100", controller=b))
        self.assertIn(rewinder, self._owners(game))

        def do_transform(g, **kw):
            Transform(rewinder, "BG20_100").do(g)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            condition=lambda hero=None, **kw: hero is a,
            callback=do_transform))
        game.run_combat(a, b)
        self.assertNotIn(rewinder, a.board)
        self.assertEqual(rewinder.zone, Zone.REMOVED)
        self.assertNotIn(rewinder, self._owners(game))
        self.assertIn("BG20_100", [m.card_id for m in a.board])

    def test_combat_restore_does_not_resurrect_removed_listener(self):
        """监听器表快照复原不得为**战斗期间永久离场**的随从复活监听器。

        真实路径: 真实 `apply_dark_gift`（`DG.DEXTERITY_SMALL` →
        `_make_card_played_gift` 注册 `card_played owner=随从`）施加于
        手牌随从 → 真实 `run_combat`（`start_of_combat` 广播中该实体
        离场 `zone=REMOVED`，且它不在 `board_before` → 棋盘复原不会
        救回它）。
        断言: 战后该实体仍在 `REMOVED` 且其监听器未被复原。
        变异探针: 去掉 `run_combat` finally 的离场收口 → 监听器被
        `events_snapshot` 复活（`card_played` 表里出现 REMOVED owner）。
        """
        from hsrl2 import darkgifts as DG
        from hsrl2.events import START_OF_COMBAT
        game = make_game(seed=9809)
        a, b = game.heroes
        game.summon(a, game.create_minion("BG20_100", controller=a))
        game.summon(b, game.create_minion("BG20_100", controller=b))
        ghost = game.create_minion("BG26_174", controller=a)
        self.assertTrue(a.add_to_hand(ghost))
        game.apply_dark_gift(ghost, DG.DEXTERITY_SMALL)
        card_played_owners = [l.owner for l in
                              game.events._listeners.get("card_played", [])]
        self.assertIn(ghost, card_played_owners)

        def remove_ghost(g, **kw):
            ghost.zone = Zone.REMOVED

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            condition=lambda hero=None, **kw: hero is a,
            callback=remove_ghost))
        game.run_combat(a, b)
        self.assertEqual(ghost.zone, Zone.REMOVED)
        self.assertNotIn(ghost, [l.owner for l in
                                 game.events._listeners.get(
                                     "card_played", [])])

    def test_survives_combat_listener_dropped_when_owner_left_play(self):
        """`survives_combat` × 战后离场收口: 即使监听器被标记为**跨战斗
        持久**（`EventBus.persistent_bind_scope`——`Game.run_on_bind` 使用的
        同一接线作用域），只要其 owner 在战斗结束时是 `REMOVED`/
        `GRAVEYARD` 的**随从**，`run_combat` 的战后离场收口仍须丢弃它。

        契约裁定: `survives_combat` 的语义是"**快照回滚**不得抹掉战斗内
        接线的持久监听器"（ENGINE_BACKLOG #30/#31/#32），**不是**"已永久
        离场实体的监听器可以复活"。故 `finally` 中的离场收口（`_gone`）
        优先于 `_kept` 的重新挂回。

        真实路径: 真实 `run_combat`; 战斗开始时（真实 `start_of_combat`
        广播内）手牌随从被永久移入 `REMOVED`，随后在真实
        `persistent_bind_scope` 内注册 `AFTER_ATTACK` 监听（owner=该随从）
        ——它不在战前快照中，只可能因 `survives_combat` 被 `_kept` 重新
        挂回。断言: 战后该监听器不存在。
        正对照: 同一 `start_of_combat` 广播内、同一作用域机制为**未离场**
        的接收英雄注册的持久接线必须存活——证明"attach 机制在跑"，使
        离场随从监听器的缺失只能归因于 `_gone` 收口（防测试空洞）。
        变异探针: 去掉 `run_combat` finally 的离场收口（`_gone` 循环）→
        随从监听器被 `_kept` 复活 → 断言失败。

        注: 生产环境 `persistent_bind_scope` 目前只以饰品/任务奖励/英雄
        为身份（`run_on_bind`），故"随从 owner + `survives_combat`"是该
        作用域 API 的直接用法（本测试即用它构造边界）; 收口本身是该 API
        的不变量。
        """
        from hsrl2.events import AFTER_ATTACK, START_OF_COMBAT
        game = make_game(seed=9810)
        a, b = game.heroes
        game.summon(a, game.create_minion("BG20_100", controller=a))
        game.summon(b, game.create_minion("BG20_100", controller=b))
        ghost = game.create_minion("BG26_174", controller=a)
        self.assertTrue(a.add_to_hand(ghost))

        def arm(g, **kw):
            ghost.zone = Zone.REMOVED
            with g.events.persistent_bind_scope(ghost):
                g.events.register(Listener(event=AFTER_ATTACK, owner=ghost,
                                           callback=lambda *x, **y: None))
            # 正对照: 同一作用域机制为未离场的英雄接线 → 必须存活
            with g.events.persistent_bind_scope(a):
                g.events.register(Listener(event=AFTER_ATTACK, owner=a,
                                           callback=lambda *x, **y: None))

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            condition=lambda hero=None, **kw: hero is a,
            callback=arm))
        game.run_combat(a, b)
        self.assertEqual(ghost.zone, Zone.REMOVED)
        owners = [l.owner for l in game.events._listeners.get(AFTER_ATTACK, [])]
        self.assertNotIn(ghost, owners,
                         "survives_combat 监听器在 owner 离场后复活")
        self.assertIn(a, owners, "持久接线机制未生效（正对照失败）")


class TestCombatGrantedListenerSurvival(unittest.TestCase):
    """战斗内授予的持久实体监听器必须在战后存活（ENGINE_BACKLOG #30）。

    缺陷: `run_combat` 的 finally 用战前快照整体覆盖监听器表 →
    战斗内授予的饰品/任务奖励在 `on_bind` 注册的监听器被静默抹掉，
    其效果永久失效（20 局随机对局中 43/90 次任务完成发生在战斗内）。
    修复: 快照回滚后重新挂回"战斗内新增且 owner 为持久实体
    （hero.trinkets / hero.quest_rewards）"的监听器。
    """

    def _combat(self, game, a, b):
        m = game.create_minion("BG20_100", controller=a)
        game.summon(a, m)
        o = game.create_minion("BG20_100", controller=b)
        game.summon(b, o)
        m.set(GameTag.ATK, 10)         # 保证发生攻击且有随从死亡
        m.set(GameTag.HEALTH, 10)
        o.set(GameTag.ATK, 0)
        o.set(GameTag.HEALTH, 1)
        game.run_combat(a, b, alive_count=2)
        return m, o

    def test_trinket_granted_mid_combat_keeps_listeners(self):
        from hsrl2.events import Listener
        game = make_game(seed=9801)
        a, b = game.heroes
        granted = []

        def hook(g, **kw):
            if not granted:
                granted.append(True)
                g.grant_trinket(a, "BG32_MagicItem_830")

        from hsrl2.events import AFTER_ATTACK
        game.events.register(Listener(event=AFTER_ATTACK, owner=None,
                                      callback=hook))
        self._combat(game, a, b)
        self.assertTrue(granted, "战斗内未成功授予饰品（前置条件）")
        trinket = a.trinkets[-1]
        owners = [l.owner for ls in game.events._listeners.values() for l in ls]
        self.assertIn(trinket, owners, "战斗内授予的饰品监听器被快照抹掉")

    def test_preexisting_trinket_combat_scoped_listener_dropped(self):
        """负对照（第二十九轮对抗验证发现）: **战前已存在**的持久实体在
        战斗内注册的监听器仍是战斗作用域, 必须随快照丢弃——否则
        `BG32_MagicItem_960`（Crocheted Sungill, start_of_combat 时注册
        `AFTER_ATTACK` owner=trinket）会逐场累积（实测 1→2→…）。"""
        from hsrl2.events import AFTER_ATTACK
        game = make_game(seed=9803)
        a, b = game.heroes
        game.grant_trinket(a, "BG32_MagicItem_960")
        for _ in range(7):
            m = game.create_minion("BG20_100", controller=a)
            game.summon(a, m)
        a.hand.append(game.create_minion("BG20_100", controller=a))
        m2 = game.create_minion("BG20_100", controller=b)
        game.summon(b, m2)
        game.run_combat(a, b, alive_count=2)
        first = len(game.events._listeners.get(AFTER_ATTACK, []))
        game.run_combat(a, b, alive_count=2)
        second = len(game.events._listeners.get(AFTER_ATTACK, []))
        self.assertEqual((first, second), (0, 0),
                         "战前持久实体的战斗作用域监听器发生累积")

    def test_power_wired_mid_combat_keeps_listeners(self):
        """#31: 战斗内**接线**的英雄技能（on_bind 期注册的监听器）必须在
        战后存活——Lord Jaraxxus 跨 150 伤害时替换技能并接线 Nether
        Portal（`TURN_START owner=hero`），此前被快照抹掉 → 技能永久
        失效。"""
        from hsrl2.events import Listener, AFTER_ATTACK
        game = make_game(seed=9804)
        a, b = game.heroes
        wired = []

        def hook(g, **kw):
            if not wired:
                wired.append(True)
                g.wire_hero_power_on_bind(a, "TB_BaconShop_HP_036t")

        game.events.register(Listener(event=AFTER_ATTACK, owner=None,
                                      callback=hook))
        before = sum(1 for ls in game.events._listeners.values()
                     for l in ls if l.owner is a)
        self._combat(game, a, b)
        self.assertTrue(wired, "战斗内未接线技能（前置条件）")
        after = sum(1 for ls in game.events._listeners.values()
                    for l in ls if l.owner is a)
        self.assertGreater(after, before, "战斗内接线的技能监听器被快照抹掉")

    def test_raw_hero_owned_listener_mid_combat_still_dropped(self):
        """负对照: 战斗内**直接**注册的 Hero-owned 监听器（非 on_bind
        接线）仍随快照丢弃。"""
        from hsrl2.events import Listener, AFTER_ATTACK
        game = make_game(seed=9805)
        a, b = game.heroes
        seen = []

        def hook(g, **kw):
            if not seen:
                seen.append(True)
                g.events.register(Listener(event=AFTER_ATTACK, owner=a,
                                           callback=lambda *x, **y: None))

        game.events.register(Listener(event=AFTER_ATTACK, owner=None,
                                      callback=hook))
        before = sum(1 for ls in game.events._listeners.values()
                     for l in ls if l.owner is a)
        self._combat(game, a, b)
        self.assertTrue(seen, "战斗内未注册监听器（前置条件）")
        after = sum(1 for ls in game.events._listeners.values()
                    for l in ls if l.owner is a)
        self.assertEqual(after, before, "战斗作用域 Hero 监听器未丢弃")

    def test_jaraxxus_real_card_nether_portal_survives(self):
        """#31a **真实卡**: Lord Jaraxxus 战斗内跨 150 伤害 → 替换技能并
        接线 Nether Portal（`TURN_START owner=hero`）; 其监听器必须战后
        存活且两场战斗不累积（对抗验证: 修复前与 HEAD^ 均丢失 → 技能
        永久失效）。"""
        import hsrl2.scripts  # noqa: F401
        game = Game([Hero("TB_BaconShop_HERO_37", "J"),
                     Hero("TEST_H_B", "B")], get_db(), seed=9806)
        game.start_game()
        a, b = game.heroes
        before = sum(1 for ls in game.events._listeners.values()
                     for l in ls if l.owner is a)
        m = game.create_minion("BG20_100", controller=a)
        game.summon(a, m)
        m.set(GameTag.ATK, 200)          # 一场战斗内跨过 150 伤害阈值
        m.set(GameTag.BASE_ATK, 200)
        o = game.create_minion("BG20_100", controller=b)
        game.summon(b, o)
        o.set(GameTag.ATK, 0)
        o.set(GameTag.BASE_ATK, 0)
        o.set(GameTag.HEALTH, 500)
        o.set(GameTag.MAX_HEALTH, 500)
        game.run_combat(a, b, alive_count=2)
        self.assertEqual(game.hero_power_def(a).id, "TB_BaconShop_HP_036t",
                         "未触发技能替换（前置条件）")
        after1 = sum(1 for ls in game.events._listeners.values()
                     for l in ls if l.owner is a)
        self.assertGreater(after1, before, "Nether Portal 监听器被快照抹掉")
        game.run_combat(a, b, alive_count=2)
        after2 = sum(1 for ls in game.events._listeners.values()
                     for l in ls if l.owner is a)
        self.assertEqual(after2, after1, "监听器跨战斗累积")

    def test_combat_scoped_listener_still_dropped(self):
        """负对照: 战斗内注册的**非持久**监听器仍随快照丢弃。"""
        from hsrl2.events import Listener
        game = make_game(seed=9802)
        a, b = game.heroes
        seen = []

        def hook(g, **kw):
            if not seen:
                seen.append(True)
                g.events.register(Listener(event=AFTER_ATTACK, owner=None,
                                           callback=lambda *a, **k: None))

        from hsrl2.events import AFTER_ATTACK
        game.events.register(Listener(event=AFTER_ATTACK, owner=None,
                                      callback=hook))
        before = len(game.events._listeners.get(AFTER_ATTACK, []))
        self._combat(game, a, b)
        after = len(game.events._listeners.get(AFTER_ATTACK, []))
        self.assertEqual(after, before, "战斗作用域监听器未随快照丢弃")

    # ── ENGINE_BACKLOG #32: 显式接线作用域（取代全局 grant_depth） ──

    def _grant_in_combat_with_related_minion(self, seed):
        """真实路径前置: 战斗内 `grant_trinket(BG32_MagicItem_830)`。

        Felemental Portrait 的 `on_bind` 经数据链 `evolution_card_id=
        97553` 交付 `BG25_041`（`grant_card_copy_to_hand` → `create_minion`
        → 广播 `entity_created`）——返回 `(game, a, b, granted)`; 调用方
        再注册 `entity_created` 监听器，即可在 **on_bind 窗口内部**
        注册探针监听器。
        """
        from hsrl2.events import Listener, AFTER_ATTACK
        game = make_game(seed=seed)
        a, b = game.heroes
        granted: list = []

        def hook(g, **kw):
            if not granted:
                granted.append(True)
                g.grant_trinket(a, "BG32_MagicItem_830")

        game.events.register(Listener(event=AFTER_ATTACK, owner=None,
                                      callback=hook))
        return game, a, b, granted

    def test_transitive_summon_listener_inside_bind_window_dropped(self):
        """#32a 正对照: `on_bind` 窗口内的**传递性**注册不得持久。

        场景（真实 API 驱动）: 战斗内 `grant_trinket`（真实 `run_on_bind`
        作用域）→ on_bind 交付 `BG25_041` 时 `entity_created` 触发 →
        在窗口内 `summon` 真实 `BG31_843` Meteorite Crasher（其
        `on_summon` 注册 `MINION_SOLD owner=随从`）。该随从是 on_bind
        副作用召唤的临时实体（不在 `board_before`）→ 战后必须离场,
        其监听器必须随快照丢弃。

        旧实现（全局 `grant_depth`）把窗口内**一切**注册标记为持久 →
        该监听器错误存活（HEAD 实测 True/True）。新作用域只按 owner
        身份标记（绑定实体 + 接收英雄）→ 随从被排除。
        """
        from hsrl2.events import Listener, MINION_SOLD
        game, a, b, granted = self._grant_in_combat_with_related_minion(9820)
        summoned: list = []

        def on_created(g, entity=None, **kw):
            if summoned:
                return
            if isinstance(entity, Minion) and entity.card_id == "BG25_041":
                mc = g.create_minion("BG31_843", controller=a)
                if mc is not None and g.summon(a, mc):
                    summoned.append(mc)

        game.events.register(Listener(event="entity_created", owner=None,
                                      callback=on_created))
        self._combat(game, a, b)
        self.assertTrue(granted, "战斗内未成功授予饰品（前置条件）")
        self.assertTrue(summoned, "on_bind 窗口内未发生传递性召唤（前置条件）")
        trinket = a.trinkets[-1]
        tl = [l for ls in game.events._listeners.values() for l in ls
              if l.owner is trinket]
        mc = summoned[0]
        ml = [l for ls in game.events._listeners.values() for l in ls
              if l.owner is mc]
        self.assertTrue(tl, "绑定实体自身的监听器被快照抹掉（正对照失败）")
        self.assertEqual(ml, [],
                         "on_bind 窗口内传递性注册的临时随从监听器被误判持久")
        self.assertEqual(game.events._listeners.get(MINION_SOLD, []), [],
                         "临时随从的 minion_sold 监听器残留")

    def test_late_callback_registration_owned_by_new_entity_dropped(self):
        """#32b 契约: 持久性由**注册时机**（`on_bind` 作用域）决定, 而非
        owner 身份。

        新授予实体在 `on_bind` **返回之后**（同一场战斗内）注册的监听器
        ——即使 owner 是该新实体——仍属战斗作用域并随快照丢弃。依据 =
        `run_combat` 的监听器表快照契约（战斗内注册/注销不延续）与
        Sungill 负对照（战斗作用域注册不得跨场累积）: 若改按 owner 保留
        （HEAD^ 旧行为）, 任何"每场注册一次"的回调都会在新实体上逐场
        累积。同 owner 的 `on_bind` 内注册仍存活（差异只在时机）——
        当前无生产卡实例走此路径; 未来若有卡需要, 须显式 opt-in 而非
        引擎按 owner 猜测。
        """
        from hsrl2.events import Listener, AFTER_ATTACK
        game = make_game(seed=9821)
        a, b = game.heroes
        granted, late = [], []

        def hook(g, **kw):
            if granted:
                return
            granted.append(True)
            t = g.grant_trinket(a, "BG32_MagicItem_830")
            # run_on_bind 已返回 → 不在持久接线作用域内
            l = Listener(event=AFTER_ATTACK, owner=t,
                         callback=lambda *x, **y: None)
            late.append(l)
            g.events.register(l)

        game.events.register(Listener(event=AFTER_ATTACK, owner=None,
                                      callback=hook))
        self._combat(game, a, b)
        self.assertTrue(granted, "前置条件")
        live = {id(l) for ls in game.events._listeners.values() for l in ls}
        self.assertNotIn(id(late[0]), live,
                         "on_bind 窗口外的注册（owner=新实体）未随快照丢弃")
        trinket = a.trinkets[-1]
        self.assertTrue(any(l.owner is trinket
                            for ls in game.events._listeners.values()
                            for l in ls),
                        "on_bind 内注册的监听器应存活（同 owner 对照）")

    def test_survivor_set_is_bind_owners_by_identity(self):
        """#32 身份判定: 作用域内注册的监听器**只有 owner 按 `is` 命中
        "绑定实体 / 接收英雄"** 才持久。

        用 `__eq__` 对绑定实体返回 True 的**值等价代理**做对照: 按值
        相等判定（`owner in scope`）会误标记它; 按身份判定则丢弃。另含
        同窗口内注册的无关英雄（owner=b）负对照。断言存活集合**恰好**
        是 {绑定实体, 接收英雄} 两个探针。
        """
        from hsrl2.events import Listener, AFTER_ATTACK
        game, a, b, granted = self._grant_in_combat_with_related_minion(9822)
        probes: dict = {}

        class _ValueEqualProxy:
            """`==` 绑定实体为 True、`is` 为 False 的代理 owner。"""

            def __init__(self, target):
                self._target = target

            def __eq__(self, other):
                return other is self._target

            def __hash__(self):
                return id(self._target)

        def on_created(g, entity=None, **kw):
            if probes:
                return
            if isinstance(entity, Minion) and entity.card_id == "BG25_041":
                t = a.trinkets[-1]      # 正在 on_bind 的绑定实体
                for key, owner in (("bound", t), ("hero", a),
                                   ("proxy", _ValueEqualProxy(t)),
                                   ("other", b)):
                    l = Listener(event=AFTER_ATTACK, owner=owner,
                                 callback=lambda *x, **y: None)
                    probes[key] = l
                    g.events.register(l)

        game.events.register(Listener(event="entity_created", owner=None,
                                      callback=on_created))
        self._combat(game, a, b)
        self.assertTrue(granted and len(probes) == 4, "前置条件")
        live = {id(l) for ls in game.events._listeners.values() for l in ls}
        survivors = {k for k, l in probes.items() if id(l) in live}
        self.assertEqual(
            survivors, {"bound", "hero"},
            "存活集合不等于绑定实体 + 接收英雄（身份判定/值相等泄漏）")
