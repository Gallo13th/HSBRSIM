"""批次 1 卡牌语义测试（作业单 2026-08-21，10 张 + TriggerBattlecry）
+ 批次 1b（5 张，依赖就绪后实现）。

覆盖: BG36_509 Private Investigator / BG29_810 Thousandth Paper Drake /
BG26_963 Electric Synthesizer / BG31_843 Meteorite Crasher /
BG29_888 Glim Guardian / BG36_701 Kelp Keeper / BG30_102 One-Amalgam
Tour Group / BG36_206 Snarky Shark / BG36_521 Locked-up Mutineer
（含金色）+ actions.TriggerBattlecry。
DEFERRED 卡: 占位守护测试（未注册即正确状态）。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）；无模板参数的卡用
文本字面量并注明。金色战吼模型: 引擎触发 2 次 × 基础值 = 金色文本总额。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import actions
from hsrl2.combat import CombatScheduler
from hsrl2.constants import MINION_SELL_VALUE, gold_base_income
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY, bind_all
from hsrl2.scripts.minions import TichondriusScript
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# UNPLAYABLE 潜伏 bug 已由主线修复（play_minion/play_spell 改用
# CardDef.unplayable），原测试内临时 shim 已移除。

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
    """创建随从 → 绑定 REGISTRY 脚本 → 召唤（含 on_summon 注册）。

    引擎缺口: game.create_minion 尚未自动查 REGISTRY 绑定 scripts
    （见批次报告），测试内显式绑定；golden=True 时实体 card_id 即
    金色卡 id，按 id 查 REGISTRY 自动命中金色注册类。
    """
    m = game.create_minion(card_id, controller=hero, golden=golden)
    m.scripts = REGISTRY.get(m.card_id)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


class TestPrivateInvestigator(unittest.TestCase):
    """BG36_509 Private Investigator — Activate(1): Gain {1} Gold next turn."""

    def test_activate_gains_gold_next_turn(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        d = get_db().get("BG36_509")
        a.gold = 10
        pi = put(game, "BG36_509", a)
        self.assertTrue(game.use_activate(a, pi))
        self.assertEqual(a.gold, 10 - d.activate_cost)
        game.turn = 5
        game._begin_recruit_for(a)
        # 延迟 GainGold 在基础收入重置之后叠加（game._begin_recruit_for 顺序）
        self.assertEqual(a.gold, gold_base_income(5) + d.num(1))

    def test_activate_once_per_turn_and_cost_check(self):
        game = make_game(seed=43)
        a = game.heroes[0]
        pi = put(game, "BG36_509", a)
        a.gold = 0
        self.assertFalse(game.use_activate(a, pi))   # 金币不足拒绝
        a.gold = 10
        self.assertTrue(game.use_activate(a, pi))
        self.assertFalse(game.use_activate(a, pi))   # 同回合第二次
        plain = make_minion("Plain", 1, 1)
        game.summon(a, plain)
        self.assertFalse(game.use_activate(a, plain))  # 非 Activate 随从

    def test_golden_activate_gains_golden_amount(self):
        game = make_game(seed=44)
        a = game.heroes[0]
        dg = get_db().get("BG36_509_G")
        pi = put(game, "BG36_509", a, golden=True)
        self.assertEqual(pi.card_id, "BG36_509_G")
        a.gold = 10
        self.assertTrue(game.use_activate(a, pi))
        game.turn = 3
        game._begin_recruit_for(a)
        self.assertEqual(a.gold, gold_base_income(3) + dg.num(1))


class TestThousandthPaperDrake(unittest.TestCase):
    """BG29_810 Thousandth Paper Drake — SoC: left-most Dragon +1/+2 & Windfury."""

    def test_soc_buffs_leftmost_dragon_only(self):
        game = make_game(seed=45)
        a = game.heroes[0]
        left = put(game, "BG29_810", a, position=0)          # 最左龙=自身
        right_dragon = make_minion("RD", 2, 2, race=Race.DRAGON)
        game.summon(a, right_dragon)
        beast = make_minion("Beast", 3, 3, race=Race.BEAST)
        game.summon(a, beast)
        game.run_script_hook(left, "start_of_combat")
        # +1/+2 为文本字面量（CardDef 无模板参数）
        self.assertEqual(left.atk, 2 + 1)
        self.assertEqual(left.max_health, 3 + 2)
        self.assertTrue(left.has(GameTag.WINDFURY))
        self.assertEqual(right_dragon.atk, 2)
        self.assertFalse(right_dragon.has(GameTag.WINDFURY))
        self.assertEqual(beast.atk, 3)

    def test_soc_no_dragons_no_effect(self):
        game = make_game(seed=46)
        a = game.heroes[0]
        beast = make_minion("Beast", 3, 3, race=Race.BEAST)
        game.summon(a, beast)
        drake = put(game, "BG29_810", a)   # 场上唯一龙是 drake 自身 → 仍是最左龙
        game.run_script_hook(drake, "start_of_combat")
        self.assertEqual(beast.atk, 3)
        self.assertTrue(drake.has(GameTag.WINDFURY))  # 自身即目标

    def test_golden_soc_buffs_two_leftmost_dragons(self):
        game = make_game(seed=47)
        a = game.heroes[0]
        d1 = make_minion("D1", 1, 1, race=Race.DRAGON)
        d2 = make_minion("D2", 2, 2, race=Race.DRAGON)
        d3 = make_minion("D3", 3, 3, race=Race.DRAGON)
        for m in (d1, d2, d3):
            game.summon(a, m)
        drake = put(game, "BG29_810", a, golden=True)
        game.run_script_hook(drake, "start_of_combat")
        for m in (d1, d2):
            self.assertEqual(m.atk, m.get(GameTag.BASE_ATK) + 1)
            self.assertEqual(m.max_health, m.get(GameTag.BASE_HEALTH) + 2)
            self.assertTrue(m.has(GameTag.WINDFURY))
        self.assertEqual(d3.atk, 3)
        self.assertFalse(d3.has(GameTag.WINDFURY))

    def test_soc_effect_rolled_back_after_combat(self):
        game = make_game(seed=48)
        a, b = game.heroes
        dragon = make_minion("D", 5, 5, race=Race.DRAGON)
        game.summon(a, dragon)
        put(game, "BG29_810", a, position=1)
        game.run_combat(a, b)   # b 空棋盘 → 平局；SoC 已触发
        self.assertEqual(dragon.atk, 5)               # RULES §3.5 快照恢复
        self.assertEqual(dragon.max_health, 5)
        self.assertFalse(dragon.has(GameTag.WINDFURY))


class TestElectricSynthesizer(unittest.TestCase):
    """BG26_963 Electric Synthesizer — Battlecry and SoC: other Dragons +1/+1."""

    def _setup_board(self, game, hero):
        dragon = make_minion("D", 4, 4, race=Race.DRAGON)
        mech = make_minion("M", 2, 2, race=Race.MECH)
        game.summon(hero, dragon)
        game.summon(hero, mech)
        synth = game.create_minion("BG26_963", controller=hero)
        synth.scripts = REGISTRY["BG26_963"]
        hero.add_to_hand(synth)
        return dragon, mech, synth

    def test_battlecry_buffs_other_dragons_only(self):
        game = make_game(seed=49)
        a = game.heroes[0]
        dragon, mech, synth = self._setup_board(game, a)
        self.assertTrue(game.play_minion(a, synth, position=2))
        self.assertEqual(dragon.atk, 4 + 1)      # 文本字面量 +1/+1
        self.assertEqual(dragon.max_health, 4 + 1)
        self.assertEqual(mech.atk, 2)
        self.assertEqual(synth.atk, 3)           # 不含自身

    def test_battlecry_golden_total_matches_golden_text(self):
        game = make_game(seed=50)
        a = game.heroes[0]
        dragon = make_minion("D", 4, 4, race=Race.DRAGON)
        game.summon(a, dragon)
        synth = game.create_minion("BG26_963", controller=a, golden=True)
        synth.scripts = REGISTRY["BG26_963_G"]
        a.add_to_hand(synth)
        self.assertTrue(game.play_minion(a, synth, position=1))
        # 引擎金色战吼触发 2 次 × 基础值(+1/+1) = 金色文本总额 +2/+2
        self.assertEqual(dragon.atk, 4 + 2)
        self.assertEqual(dragon.max_health, 4 + 2)

    def test_battlecry_brann_doubles(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        dragon, mech, synth = self._setup_board(game, a)
        brann = make_minion("Brann", 2, 4)
        brann.set(GameTag.BATTLECRY_DOUBLER, True)
        game.summon(a, brann)
        self.assertTrue(game.play_minion(a, synth, position=3))
        self.assertEqual(dragon.atk, 4 + 2)      # 2 次触发

    def test_soc_buffs_other_dragons(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        dragon = make_minion("D", 4, 4, race=Race.DRAGON)
        mech = make_minion("M", 2, 2, race=Race.MECH)
        game.summon(a, dragon)
        game.summon(a, mech)
        synth = put(game, "BG26_963", a, position=2)
        game.run_script_hook(synth, "start_of_combat")
        self.assertEqual(dragon.atk, 4 + 1)
        self.assertEqual(mech.atk, 2)

    def test_golden_soc_uses_golden_values(self):
        game = make_game(seed=53)
        a = game.heroes[0]
        dragon = make_minion("D", 4, 4, race=Race.DRAGON)
        game.summon(a, dragon)
        synth = put(game, "BG26_963", a, golden=True)
        game.run_script_hook(synth, "start_of_combat")
        self.assertEqual(dragon.atk, 4 + 2)      # 金色 SoC 单次触发 +2/+2
        self.assertEqual(dragon.max_health, 4 + 2)


class TestMeteoriteCrasher(unittest.TestCase):
    """BG31_843 Meteorite Crasher — After you sell an Elemental, gain +{0}/+{1}."""

    def test_sell_elemental_buffs_crasher(self):
        game = make_game(seed=54)
        a = game.heroes[0]
        d = get_db().get("BG31_843")
        crasher = put(game, "BG31_843", a)
        elem = make_minion("Elem", 1, 1, race=Race.ELEMENTAL)
        game.summon(a, elem)
        self.assertTrue(game.sell_minion(a, elem))
        self.assertEqual(crasher.atk, 4 + d.num(0))
        self.assertEqual(crasher.max_health, 4 + d.num(1))

    def test_sell_nonelemental_or_opponent_elemental_no_buff(self):
        game = make_game(seed=55)
        a, b = game.heroes
        crasher = put(game, "BG31_843", a)
        beast = make_minion("B", 1, 1, race=Race.BEAST)
        game.summon(a, beast)
        game.sell_minion(a, beast)
        opp_elem = make_minion("OE", 1, 1, race=Race.ELEMENTAL)
        game.summon(b, opp_elem)
        game.sell_minion(b, opp_elem)
        self.assertEqual(crasher.atk, 4)
        self.assertEqual(crasher.max_health, 4)

    def test_amalgam_counts_as_elemental(self):
        game = make_game(seed=56)
        a = game.heroes[0]
        d = get_db().get("BG31_843")
        crasher = put(game, "BG31_843", a)
        amalgam = make_minion("Amal", 1, 1, race=Race.ALL)
        game.summon(a, amalgam)
        game.sell_minion(a, amalgam)
        self.assertEqual(crasher.atk, 4 + d.num(0))   # ALL 视为所有种族

    def test_golden_buffs_twice(self):
        game = make_game(seed=57)
        a = game.heroes[0]
        d = get_db().get("BG31_843_G")
        crasher = put(game, "BG31_843", a, golden=True)
        elem = make_minion("Elem", 1, 1, race=Race.ELEMENTAL)
        game.summon(a, elem)
        game.sell_minion(a, elem)
        self.assertEqual(len(crasher.buffs), 2)               # "twice" = 2 实例
        self.assertEqual(crasher.atk, 8 + d.num(0) * 2)
        self.assertEqual(crasher.max_health, 8 + d.num(1) * 2)

    def test_listener_unregistered_after_sell(self):
        game = make_game(seed=58)
        a = game.heroes[0]
        crasher = put(game, "BG31_843", a)
        game.sell_minion(a, crasher)     # 出售自身（Elemental）→ 触发后离场
        elem = make_minion("Elem2", 1, 1, race=Race.ELEMENTAL)
        game.summon(a, elem)
        game.sell_minion(a, elem)
        remaining = [l for ls in game.events._listeners.values() for l in ls
                     if l.owner is crasher]
        self.assertEqual(remaining, [])  # 离场自动注销


class TestGlimGuardian(unittest.TestCase):
    """BG29_888 Glim Guardian — Rally: Gain +{0} Attack."""

    def test_rally_gains_attack_and_applies_to_current_attack(self):
        game = make_game(seed=59)
        a, b = game.heroes
        d = get_db().get("BG29_888")
        glim = put(game, "BG29_888", a)
        dummy = make_minion("Dummy", 0, 10)
        game.summon(b, dummy)
        CombatScheduler(game, a, b)._execute_attack(glim, dummy)
        self.assertEqual(glim.atk, 1 + d.num(0))
        # Rally 先于伤害结算（RULES §6.16）→ 本次攻击伤害已含增益
        self.assertEqual(dummy.health, 10 - (1 + d.num(0)))

    def test_golden_rally_gains_golden_amount(self):
        game = make_game(seed=60)
        a = game.heroes[0]
        dg = get_db().get("BG29_888_G")
        glim = put(game, "BG29_888", a, golden=True)
        dummy = make_minion("Dummy", 0, 10)
        game.summon(a, dummy)
        game.run_script_hook(glim, "rally", ctx={"target": dummy})
        self.assertEqual(glim.atk, 2 + dg.num(0))


class TestTriggerBattlecry(unittest.TestCase):
    """actions.TriggerBattlecry — 单次重触发 / Brann 翻倍 / 计数与广播。"""

    def _setup(self, game, hero, with_brann: bool):
        dragon = make_minion("D", 4, 4, race=Race.DRAGON)
        game.summon(hero, dragon)
        synth = put(game, "BG26_963", hero)
        if with_brann:
            brann = make_minion("Brann", 2, 4)
            brann.set(GameTag.BATTLECRY_DOUBLER, True)
            game.summon(hero, brann)
        seen = []
        game.events.register(Listener(
            "battlecry_trigger", owner=dragon,
            callback=lambda g, **kw: seen.append(kw["minion"])))
        return dragon, synth, seen

    def test_retriggers_battlecry_once_with_counter_and_event(self):
        game = make_game(seed=61)
        a = game.heroes[0]
        dragon, synth, seen = self._setup(game, a, with_brann=False)
        game.run_actions(actions.TriggerBattlecry(synth))
        self.assertEqual(dragon.atk, 4 + 1)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES), 1)
        self.assertEqual(seen, [synth])

    def test_brann_doubles_retrigger(self):
        game = make_game(seed=62)
        a = game.heroes[0]
        dragon, synth, seen = self._setup(game, a, with_brann=True)
        game.run_actions(actions.TriggerBattlecry(synth))
        self.assertEqual(dragon.atk, 4 + 2)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES), 2)
        self.assertEqual(len(seen), 2)

    def test_silenced_target_no_effect(self):
        game = make_game(seed=63)
        a = game.heroes[0]
        dragon, synth, _ = self._setup(game, a, with_brann=False)
        synth.set(GameTag.SILENCED, True)
        game.run_actions(actions.TriggerBattlecry(synth))
        self.assertEqual(dragon.atk, 4)    # 沉默 → call_script 无效果


class TestDeferredAndAmbiguous(unittest.TestCase):
    """DEFERRED 卡: 未注册即正确状态（注册表 = 可用实现）。"""

    def test_tichondrius_now_registered_after_timing_fix(self):
        # 已实现并注册（2026-08-21 主线修复: loser.take_damage 移至快照
        # 恢复之后 + 事件监听器表随战斗快照恢复，见 TestTichondrius）
        self.assertIn("BG26_523", REGISTRY)
        self.assertIsNotNone(TichondriusScript.__doc__)


# ══════════════════ 批次 1b（作业单 2026-08-21，依赖就绪后实现） ══════════════════


class TestKelpKeeperActivate(unittest.TestCase):
    """BG36_701 Kelp Keeper — Activate(1): Trigger a friendly minion's
    Battlecry（主线终裁: wiki [Targeted] 标签 → PendingChoice 建模玩家
    选择，自动化层经 pending_choices 决策）。"""

    def _board(self, game, hero):
        # BG26_963 Electric Synthesizer 战吼 = 其他龙 +1/+1（已注册脚本，
        # 作为可观测战吼）；单候选场景下选择唯一（TEST_SOP §5）
        dragon = make_minion("D", 4, 4, race=Race.DRAGON)
        game.summon(hero, dragon)
        synth = put(game, "BG26_963", hero)
        return dragon, synth

    def _resolve_pending(self, game):
        choice = game.pending_choices.pop(0)
        choice.choose(0)   # 单候选 → index 0

    def test_activate_triggers_single_battlecry_candidate(self):
        game = make_game(seed=70)
        a = game.heroes[0]
        d = get_db().get("BG36_701")
        dragon, synth = self._board(game, a)
        kelp = put(game, "BG36_701", a)
        a.gold = 10
        gold_before = a.gold
        self.assertTrue(game.use_activate(a, kelp))
        self.assertEqual(a.gold, gold_before - d.activate_cost)  # num(0)=1
        self.assertEqual(len(game.pending_choices), 1)
        self.assertEqual(game.pending_choices[0].kind, "activate_target")
        self._resolve_pending(game)
        self.assertEqual(dragon.atk, 4 + 1)   # 唯一 BATTLECRY 候选 = synth
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES), 1)

    def test_activate_without_candidates_no_effect_no_crash(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        plain = make_minion("Plain", 2, 2)    # 无 BATTLECRY 关键词
        game.summon(a, plain)
        kelp = put(game, "BG36_701", a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, kelp))   # 费用照扣、无效果不崩
        self.assertEqual(len(game.pending_choices), 0)   # 无候选无选择
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)
        self.assertEqual(plain.atk, 2)

    def test_golden_activate_triggers_twice(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        dragon, synth = self._board(game, a)
        kelp = put(game, "BG36_701", a, golden=True)
        self.assertEqual(kelp.card_id, "BG36_701_G")
        a.gold = 10
        self.assertTrue(game.use_activate(a, kelp))
        # "twice" = 选定目标战吼 ×2；单候选 → 同一目标 2 次战吼
        self._resolve_pending(game)
        self.assertEqual(dragon.atk, 4 + 2)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES), 2)


class TestOneAmalgamTourGroup(unittest.TestCase):
    """BG30_102 — Whenever you play a card, give friendly minions of its
    Tier or lower +{0}/+{1}. "its Tier" 取 CardDef.tech_level
    （法术同样带 tier 1-7，数据核实见脚本 docstring）。"""

    def test_play_minion_buffs_tier_or_lower_including_played(self):
        game = make_game(seed=73)
        a = game.heroes[0]
        d = get_db().get("BG30_102")
        played_def = get_db().get("BG25_010")   # Handless Forsaken T3（仅亡语，
        tg = put(game, "BG30_102", a)           # 打出时无副作用）
        low = make_minion("Low", 1, 1, tech_level=3)
        high = make_minion("High", 6, 6, tech_level=5)
        game.summon(a, low)
        game.summon(a, high)
        t3 = game.create_minion("BG25_010", controller=a)   # 真实卡（db 可查 tier）
        a.add_to_hand(t3)
        self.assertTrue(game.play_minion(a, t3))
        self.assertEqual(low.atk, 1 + d.num(0))             # tier 3 ≤ 3 达标
        self.assertEqual(low.max_health, 1 + d.num(1))
        self.assertEqual(t3.atk, played_def.atk + d.num(0))   # 打出者自身达标
        self.assertEqual(t3.max_health, played_def.health + d.num(1))
        self.assertEqual(high.atk, 6)                       # tier 5 > 3 不达标
        self.assertEqual(high.max_health, 6)
        self.assertEqual(tg.atk, 6)                         # tier 6 > 3 不达标

    def test_play_spell_uses_spell_tier(self):
        game = make_game(seed=74)
        a = game.heroes[0]
        d = get_db().get("BG30_102")
        put(game, "BG30_102", a)
        t1 = make_minion("T1", 1, 1, tech_level=1)
        t2 = make_minion("T2", 2, 2, tech_level=2)
        game.summon(a, t1)
        game.summon(a, t2)
        spell_def = get_db().get("BG28_810")                # Tavern Coin（非定向——Fortify 已脚本化需目标）
        self.assertEqual(spell_def.tech_level, 1)
        spell = game.create_spell("BG28_810", controller=a)
        a.add_to_hand(spell)
        self.assertTrue(game.play_spell(a, spell))
        self.assertEqual(t1.atk, 1 + d.num(0))              # tier 1 ≤ 法术 tier 1
        self.assertEqual(t1.max_health, 1 + d.num(1))
        self.assertEqual(t2.atk, 2)                         # tier 2 > 1 不达标

    def test_opponent_play_does_not_trigger(self):
        game = make_game(seed=75)
        a, b = game.heroes
        put(game, "BG30_102", a)
        low = make_minion("Low", 1, 1, tech_level=1)
        game.summon(a, low)
        opp = make_minion("Opp", 2, 2, tech_level=1)
        b.add_to_hand(opp)
        self.assertTrue(game.play_minion(b, opp))
        self.assertEqual(low.atk, 1)                        # 对手打出 → 不触发

    def test_golden_uses_golden_values(self):
        game = make_game(seed=76)
        a = game.heroes[0]
        dg = get_db().get("BG30_102_G")
        played_def = get_db().get("BG21_015")   # Tarecgosa T2（无关键词）
        put(game, "BG30_102", a, golden=True)
        low = make_minion("Low", 1, 1, tech_level=2)
        game.summon(a, low)
        t2 = game.create_minion("BG21_015", controller=a)
        a.add_to_hand(t2)
        self.assertTrue(game.play_minion(a, t2))
        self.assertEqual(low.atk, 1 + dg.num(0))            # 金色 +4/+2
        self.assertEqual(low.max_health, 1 + dg.num(1))
        self.assertEqual(t2.atk, played_def.atk + dg.num(0))

    def test_listener_unregistered_after_sell(self):
        game = make_game(seed=77)
        a = game.heroes[0]
        tg = put(game, "BG30_102", a)
        self.assertTrue(game.sell_minion(a, tg))
        remaining = [l for ls in game.events._listeners.values() for l in ls
                     if l.owner is tg]
        self.assertEqual(remaining, [])                     # 离场自动注销


class TestSnarkyShark(unittest.TestCase):
    """BG36_206 — When you sell this, Refresh the Tavern with a Fishbait.
    Your left-most Beast attacks it."""

    def test_sell_refreshes_free_and_places_fishbait(self):
        game = make_game(seed=78)
        a = game.heroes[0]
        shark = put(game, "BG36_206", a)    # 鲨鱼自身是 Beast（race=20）
        a.gold = 10
        gold_before = a.gold
        self.assertTrue(game.sell_minion(a, shark))
        # 效果刷新免费: 金币变化 = 仅出售返还
        self.assertEqual(a.gold, gold_before + MINION_SELL_VALUE)
        # 无其他 Beast（已售鲨鱼排除）→ Fishbait 留在酒馆
        fish = [e for e in a.tavern if e.card_id == "BG36_205"]
        self.assertEqual(len(fish), 1)
        self.assertEqual(fish[0].zone, Zone.TAVERN)
        self.assertEqual(fish[0].health, get_db().get("BG36_205").health)
        # 被替换者=未购买 → 回池: 酒馆随从数 = 本 tier 展示数（未净增）
        from hsrl2.constants import TAVERN_OFFERS
        minions_in_tavern = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(minions_in_tavern),
                         TAVERN_OFFERS[a.tavern_tier])

    @staticmethod
    def _capture_fishbait(game, hero):
        # on_sell 内部完成刷新+攻击，事后 Fishbait 可能已被击杀移出酒馆
        # ——用 entity_created 事件捕获实体再断言（TEST_SOP §5 确定性）
        created = []
        game.events.register(Listener(
            "entity_created", owner=hero,
            callback=lambda g, entity=None, **kw: created.append(entity)))
        return created

    def test_sold_shark_is_not_the_attacker(self):
        game = make_game(seed=79)
        a = game.heroes[0]
        shark = put(game, "BG36_206", a, position=0)        # 最左 Beast = 鲨鱼
        beast = make_minion("Beast", 5, 5, race=Race.BEAST)
        game.summon(a, beast, 1)
        created = self._capture_fishbait(game, a)
        game.sell_minion(a, shark)
        fish = [e for e in created if e.card_id == "BG36_205"]
        self.assertEqual(len(fish), 1)
        # 攻击者 = 右侧 beast（已售鲨鱼被排除）; Fishbait 0/1 被 5 攻击致死
        self.assertNotIn(fish[0], a.tavern)
        self.assertEqual(fish[0].zone, Zone.REMOVED)
        self.assertIs(fish[0].get(GameTag.KILLER), beast)
        self.assertTrue(beast in a.board and not beast.dead)

    def test_amalgam_beast_counts_as_leftmost(self):
        game = make_game(seed=80)
        a = game.heroes[0]
        amalgam = make_minion("Amal", 5, 5, race=Race.ALL)  # ALL 视为野兽
        game.summon(a, amalgam, 0)
        shark = put(game, "BG36_206", a, position=1)
        created = self._capture_fishbait(game, a)
        game.sell_minion(a, shark)
        fish = [e for e in created if e.card_id == "BG36_205"]
        self.assertEqual(len(fish), 1)
        self.assertIs(fish[0].get(GameTag.KILLER), amalgam)  # 最左 ALL 攻击

    def test_golden_shark_places_golden_fishbait(self):
        game = make_game(seed=81)
        a = game.heroes[0]
        shark = put(game, "BG36_206", a, golden=True)
        game.sell_minion(a, shark)
        fish = [e for e in a.tavern if e.card_id == "BG36_205_G"]
        self.assertEqual(len(fish), 1)                      # 金色 Fishbait
        self.assertEqual(fish[0].health,
                         get_db().get("BG36_205_G").health)


class TestLockedUpMutineer(unittest.TestCase):
    """BG36_521 — DR: Get a Lockbox. If you already have one, it opens {0}
    turn(s) sooner instead."""

    def test_deathrattle_gets_lockbox(self):
        game = make_game(seed=82)
        a = game.heroes[0]
        mut = put(game, "BG36_521", a)
        mut.health = 0
        game.check_deaths()
        boxes = [c for c in a.hand if c.card_id == "BG36_520t"]
        self.assertEqual(len(boxes), 1)
        ld = get_db().get("BG36_520t")
        self.assertEqual(boxes[0].get(GameTag.LOCKBOX_TURNS_LEFT), ld.num(0))

    def test_deathrattle_existing_lockbox_opens_sooner(self):
        game = make_game(seed=83)
        a = game.heroes[0]
        d = get_db().get("BG36_521")
        ld = get_db().get("BG36_520t")
        lb = game.create_spell("BG36_520t", controller=a)
        a.add_to_hand(lb)
        mut = put(game, "BG36_521", a)
        mut.health = 0
        game.check_deaths()
        # early 路径: 倒计时 -num(0)，未归零 → Lockbox 仍在手、不新增
        self.assertEqual(lb.get(GameTag.LOCKBOX_TURNS_LEFT),
                         ld.num(0) - d.num(0))
        self.assertIn(lb, a.hand)
        self.assertEqual([c for c in a.hand if c.card_id == "BG36_520t"],
                         [lb])

    def test_golden_existing_lockbox_opens_two_sooner(self):
        game = make_game(seed=84)
        a = game.heroes[0]
        dg = get_db().get("BG36_521_G")
        ld = get_db().get("BG36_520t")
        lb = game.create_spell("BG36_520t", controller=a)
        a.add_to_hand(lb)
        mut = put(game, "BG36_521", a, golden=True)
        mut.health = 0
        game.check_deaths()
        self.assertEqual(lb.get(GameTag.LOCKBOX_TURNS_LEFT),
                         ld.num(0) - dg.num(0))             # 5 - 2 = 3

    def test_no_lockbox_when_mutineer_alive(self):
        game = make_game(seed=85)
        a = game.heroes[0]
        put(game, "BG36_521", a)                            # 未死亡 → 不触发
        self.assertEqual(
            [c for c in a.hand if c.card_id == "BG36_520t"], [])


class TestRegistryEntries(unittest.TestCase):
    """注册表健康度: 卡定义存在 / 金色链完整 / bind_all 通过（CARD_ENTRY_SOP §2）。"""

    IMPLEMENTED = [
        "BG36_509", "BG29_810", "BG26_963", "BG31_843", "BG29_888",
        "BG36_701", "BG30_102", "BG36_206", "BG36_521",
    ]

    def test_registered_ids_exist_with_golden_chain(self):
        db = get_db()
        for cid in self.IMPLEMENTED:
            d = db.get(cid)
            self.assertIsNotNone(d)
            self.assertIn(cid, REGISTRY)
            golden = db.golden_version(d)
            self.assertIsNotNone(golden, f"MISSING_GOLDEN: {cid}")
            self.assertIn(golden.id, REGISTRY)
        self.assertGreaterEqual(bind_all(db), 2 * len(self.IMPLEMENTED))


if __name__ == "__main__":
    unittest.main()


class TestTichondrius(unittest.TestCase):
    """BG26_523 — After your hero takes damage, give your Demons +{0}/+{1}.

    依赖链验证: HERO_DAMAGE_TAKEN fire + 战后施伤（快照恢复后）+
    监听器表战斗快照恢复。
    """

    def test_hero_damage_buffs_demons(self):
        game = make_game(seed=80)
        a, b = game.heroes
        d = get_db().get("BG26_523")
        demon = make_minion("Demon", 2, 2, race=Race.DEMON)
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, demon)
        game.summon(a, beast)
        tich = put(game, "BG26_523", a)          # on_summon 注册监听器
        atk0, hp0 = demon.atk, demon.health
        a.take_damage(3)                          # 招募期受伤（无护甲）
        self.assertEqual(demon.atk, atk0 + d.num(0))
        self.assertEqual(demon.health, hp0 + d.num(1))
        self.assertEqual(beast.atk, 2)            # 非恶魔不受

    def test_died_in_combat_does_not_trigger(self):
        """官方伤害时序（2026-08-22 修正）: 战败伤害施加在**战后棋盘**——
        战死的 Tichondrius 在墓地、监听器已注销 → 不触发; 恶魔无增益。
        其监听器随复活回归供未来回合使用。"""
        game = make_game(seed=81)
        a, b = game.heroes
        d = get_db().get("BG26_523")
        demon = make_minion("Demon", 1, 1, race=Race.DEMON)
        game.summon(a, demon)
        tich = put(game, "BG26_523", a)
        killer = make_minion("Killer", 10, 10)
        game.summon(b, killer)
        game.run_combat(a, b)
        self.assertTrue(a.health < 30)            # 伤害照常结算
        self.assertEqual(demon.atk, 1)            # 战死者不触发
        self.assertEqual(demon.health, 1)
        # 复活后监听器回归: 招募期受伤正常触发
        a.take_damage(2)
        self.assertEqual(demon.atk, 1 + d.num(0))

    def test_combat_loss_never_triggers_minion_hero_damage_listeners(self):
        """结构性事实（战斗结束条件推导）: 战败方棋盘必然全灭——
        战败伤害时败方随从监听器全部缺席，hero_damage_taken 随从触发器
        （Tichondrius/Soul Rewinder 家族）不可能由战败伤害触发。
        其官方定位 = 招募期扣血联动（健康购买/自伤技能/法术）。
        本测试钉死该不变量。"""
        from hsrl2.events import Listener
        game = make_game(seed=82)
        a, b = game.heroes
        fired_while_board_nonempty = []
        tich = put(game, "BG26_523", a)
        killer = make_minion("Killer", 30, 30)
        game.summon(b, killer)
        game.run_combat(a, b)
        self.assertTrue(a.health < 30)            # 伤害照常
        self.assertEqual(tich.atk, 3)             # 无任何触发（已全灭）
        # 招募期扣血（英雄技能/健康购买路径模拟）→ 正常触发
        a.take_damage(2)
        d = get_db().get("BG26_523")
        self.assertEqual(tich.atk, 3 + d.num(0))  # 复活后监听器在册
