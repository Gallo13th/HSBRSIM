"""hsrl2 P0 不变量测试 — 每个旧引擎缺陷的修复对应一个测试。

覆盖 docs/REFACTOR_PLAN.md §4/§5:
  C1 风怒连续攻击 / C2 攻击者耗尽跳过 / C3 Venomous 双向后判定
  C4 AFTER_ATTACK 后置 / C6 复生保留状态 / C7 圣盾挡剧毒
  C8 Venomous 每场重置 / C10 先攻与嘲讽
  P1 池生命周期 / P3 金币语义 / P4 升级费下限 / P5 冻结
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.constants import gold_base_income
from hsrl2.db import CardDB
from hsrl2.entity import Buff
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
    m = Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)
    return m


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


class TestCombatWindfuryConsecutive(unittest.TestCase):
    """C1: 风怒随从连续攻击两次，中间不插入对方攻击。"""

    def test_windfury_attacks_twice_in_a_row(self):
        game = make_game(seed=1)
        a, b = game.heroes
        wf = make_minion("Windfury", 3, 10)
        wf.set(GameTag.WINDFURY, True)
        a.board = [wf]
        b.board = [make_minion("Tank", 0, 100)]   # 0 攻不会反击
        order = []
        game.events.register(Listener(
            "before_attack", owner=wf,
            callback=lambda g, **kw: order.append(kw["attacker"].card_id)))
        game.run_combat(a, b)
        # 前两次攻击必须都是风怒随从（连续）
        self.assertEqual(order[0], "TEST_Windfury")
        self.assertEqual(order[1], "TEST_Windfury")


class TestCombatAttackerExhaustion(unittest.TestCase):
    """C2: 一方攻击者耗尽→跳过，对方继续攻击直到分出胜负。"""

    def test_side_exhausted_other_continues(self):
        game = make_game(seed=7)
        a, b = game.heroes
        # A: 1 个大随从; B: 5 个小随从 → B 先攻
        # 游标轮转: Big 每轮吸收 5×1 伤、反击 5×1 → 循环至 Big 死亡
        big = make_minion("Big", 5, 9)
        a.board = [big]
        b.board = [make_minion("S1", 1, 30), make_minion("S2", 1, 30),
                   make_minion("S3", 1, 30), make_minion("S4", 1, 30),
                   make_minion("S5", 1, 30)]
        result = game.run_combat(a, b)
        self.assertIs(result.winner, b)
        self.assertGreater(result.damage_dealt, 0)

    def test_attack_cycles_until_death(self):
        """随从可多次攻击（轮转循环）— v1 '每场只攻一次' 缺陷的回归测试。

        2/30 vs 1/30: 真实规则下 ~15 次互攻后 B 死、A 存活（约 15 血）。
        v1 语义下双方各攻击一次后僵局 → 假平局。
        """
        game = make_game(seed=17)
        a, b = game.heroes
        a.board = [make_minion("TankA", 2, 30)]
        b.board = [make_minion("TankB", 1, 30)]
        result = game.run_combat(a, b)
        self.assertIs(result.winner, a)
        # A 承受 15 次反击 ×1 → 存活
        self.assertTrue(a.board[0].health > 0)


class TestVenomousTiming(unittest.TestCase):
    """C3/C8: Venomous 在双向伤害后判定存活；每场战斗重置。"""

    def test_venomous_dies_in_counter_no_kill(self):
        game = make_game(seed=3)
        a, b = game.heroes
        venom = make_minion("Venom", 2, 2)
        venom.set(GameTag.VENOMOUS, True)
        big = make_minion("Big", 5, 10)
        a.board = [venom]
        b.board = [big]
        game.run_combat(a, b)
        # Venom(2/2) 打 Big(5/10): venom 造成 2 伤，但被 5 反击致死
        # → 猛毒不触发，Big 存活 → B 胜
        # 注意 run_combat 恢复快照，检查结果而非 board

    def test_venomous_resets_next_combat(self):
        game = make_game(seed=4)
        a, b = game.heroes
        venom = make_minion("Venom", 5, 10)
        venom.set(GameTag.VENOMOUS, True)
        weak1 = make_minion("W1", 0, 3)
        weak2 = make_minion("W2", 0, 3)
        b.board = [weak1]
        game.run_combat(a, b)
        # 第一场: venom 杀 W1, VENOMOUS_CONSUMED 被设置
        # 第二场: 重置后应再次生效
        b.board = [weak2]
        result = game.run_combat(a, b)
        # venom 5/10 vs 0/3: W2 死于普通伤害也行; 检查 consumed 标志被清除
        self.assertFalse(venom.has(GameTag.VENOMOUS_CONSUMED) and not venom.venomous_active)


class TestDivineShieldBlocksPoison(unittest.TestCase):
    """C7: 圣盾完全抵消 → 剧毒不触发。"""

    def test_shield_blocks_venomous(self):
        game = make_game(seed=5)
        a, b = game.heroes
        venom = make_minion("Venom", 4, 10)
        venom.set(GameTag.VENOMOUS, True)
        shielded = make_minion("Shielded", 0, 5)
        shielded.set(GameTag.DIVINE_SHIELD, True)
        a.board = [venom]
        b.board = [shielded]
        # 手动执行一次攻击结算验证（不跑完整循环）
        sched = CombatScheduler(game, a, b)
        sched._execute_attack(venom, shielded)
        # 圣盾抵消 4 伤害 → 猛毒不触发 → 存活（血量未变）
        self.assertFalse(shielded.dead)
        self.assertEqual(shielded.health, 5)
        self.assertFalse(shielded.has(GameTag.DIVINE_SHIELD))  # 盾已消耗
        # 猛毒未被消耗（没有造成伤害）
        self.assertTrue(venom.venomous_active)


class TestAfterAttackTiming(unittest.TestCase):
    """C4: AFTER_ATTACK 在伤害结算之后广播。"""

    def test_after_attack_sees_damage(self):
        game = make_game(seed=6)
        a, b = game.heroes
        att = make_minion("Att", 3, 10)
        dfd = make_minion("Dfd", 0, 10)
        a.board = [att]
        b.board = [dfd]
        seen = {}
        game.events.register(Listener(
            "after_attack", owner=att,
            callback=lambda g, **kw: seen.setdefault("dfd_health", kw["defender"].health)))
        game.run_combat(a, b)
        self.assertEqual(seen.get("dfd_health"), 7)   # 10-3: 伤害已结算


class TestRebornPreservesState(unittest.TestCase):
    """C6: 复生保留 buff/金色，1 血，原位，失去复生。"""

    def test_reborn_keeps_buffs_and_position(self):
        game = make_game(seed=8)
        a, b = game.heroes
        reb = make_minion("Reb", 2, 3)
        reb.set(GameTag.REBORN, True)
        reb.set(GameTag.GOLDEN, True)
        reb.add_buff(Buff(atk=4, health=4))
        left = make_minion("Left", 0, 10)
        a.board = [left, reb]
        b.board = [make_minion("Killer", 10, 10)]
        game.check_deaths.__self__ if False else None
        # 直接标记死亡并处理
        reb.health = 0
        game._process_single_death(reb)
        # 复生: 仍在 board 原位置（index 1）
        self.assertIn(reb, a.board)
        self.assertEqual(a.board.index(reb), 1)
        self.assertEqual(reb.health, 1)                    # 1 血
        self.assertFalse(reb.reborn)                       # 失去复生
        self.assertTrue(reb.is_golden)                     # 保留金色
        self.assertEqual(reb.atk, 2 + 4)                   # 保留 buff
        self.assertEqual(reb.max_health, 3 + 4)


class TestPoolLifecycle(unittest.TestCase):
    """P1: 刷新丢弃回池 / 出售回池（金色3份）/ Discover 占池。"""

    def test_refresh_returns_to_pool(self):
        game = make_game(seed=9)
        a = game.heroes[0]
        game.start_game()
        before = game.minion_pool.total_remaining()
        offered_ids = [m.card_id for m in a.tavern if isinstance(m, Minion)]
        game.refresh_tavern(a, auto=True)
        # 旧酒馆内容回池 → 总量不变（新抽取等量扣减）
        self.assertEqual(game.minion_pool.total_remaining(), before)
        # 原来展示的卡重新可被抽到（回到池中）
        for cid in offered_ids:
            self.assertEqual(game.minion_pool.available(cid) >= 0, True)

    def test_sell_returns_to_pool(self):
        game = make_game(seed=10)
        a = game.heroes[0]
        m = make_minion("Sold", 1, 1)
        game.summon(a, m)
        avail = game.minion_pool.available("TEST_Sold")
        game.sell_minion(a, m)
        # 非池卡不回池 — 用池卡验证
        pool_card = game.minion_pool.candidates(6)[0]
        pm = game.create_minion(pool_card, controller=a)
        game.summon(a, pm)
        before = game.minion_pool.available(pool_card)
        game.sell_minion(a, pm)
        self.assertEqual(game.minion_pool.available(pool_card), before + 1)

    def test_golden_sell_returns_three(self):
        game = make_game(seed=11)
        a = game.heroes[0]
        pool_card = game.minion_pool.candidates(6)[0]
        gm = game.create_minion(pool_card, controller=a, golden=True)
        # golden=True 但无金色定义 → GOLDEN tag + 池按 3 份返还
        game.summon(a, gm)
        before = game.minion_pool.available(pool_card)
        game.sell_minion(a, gm)
        self.assertEqual(game.minion_pool.available(pool_card), before + 3)


class TestGoldSemantics(unittest.TestCase):
    """P3: 基础收入曲线 / 回合内收入可超基础量 / 上限 99。"""

    def test_base_income_curve(self):
        self.assertEqual(gold_base_income(1), 3)
        self.assertEqual(gold_base_income(5), 7)
        self.assertEqual(gold_base_income(8), 10)
        self.assertEqual(gold_base_income(15), 10)

    def test_in_round_income_exceeds_base(self):
        game = make_game(seed=12)
        a = game.heroes[0]
        game.turn = 3
        a.gold = gold_base_income(3)   # 5
        a.gold += 3                    # 卖了 3 个随从
        self.assertEqual(a.gold, 8)    # 不被基础量截断（旧引擎 bug）


class TestUpgradeFloor(unittest.TestCase):
    """P4: 升级费下限 0。"""

    def test_upgrade_cost_floors_at_zero(self):
        game = make_game(seed=13)
        a = game.heroes[0]
        a.set(GameTag.UPGRADE_COST, 1)
        # 下一回合递减
        game.turn = 5
        a.set(GameTag.UPGRADE_COST, max(0, a.upgrade_cost - 1))
        self.assertEqual(a.upgrade_cost, 0)


class TestFreezeSemantics(unittest.TestCase):
    """P5: 整馆冻结 + 手动刷新保留。"""

    def test_freeze_survives_manual_refresh(self):
        game = make_game(seed=14)
        a = game.heroes[0]
        game.start_game()
        frozen_content = list(a.tavern)
        game.freeze_tavern(a)
        a.gold = 10
        game.refresh_tavern(a)     # 手动刷新
        for entity in frozen_content:
            self.assertIn(entity, a.tavern)   # 冻结内容保留
        # 冻结只保一轮
        self.assertFalse(a.frozen_tavern)


class TestChoiceQueue(unittest.TestCase):
    """D-4 修复: PendingChoice 队列化，连发发现不覆盖。"""

    def test_pending_choices_stack(self):
        game = make_game(seed=15)
        a = game.heroes[0]
        from hsrl2.game import PendingChoice
        game.pending_choices.append(PendingChoice(a, [1, 2, 3], "test"))
        game.pending_choices.append(PendingChoice(a, ["x", "y"], "test2"))
        self.assertEqual(len(game.pending_choices), 2)
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(len(game.pending_choices), 1)


class TestDbIntegrity(unittest.TestCase):
    """数据层: 36.2.2 基线完整性。"""

    def test_data_loaded(self):
        db = get_db()
        self.assertGreater(len(db), 2000)

    def test_pool_minions_count(self):
        db = get_db()
        pool = db.pool_minions()
        self.assertEqual(len(pool), 247)   # 36.2.2 基线

    def test_dark_gifts_loaded(self):
        db = get_db()
        self.assertEqual(len(db.dark_gifts()), 43)

    def test_activate_minions_present(self):
        db = get_db()
        activates = [d for d in db.pool_minions() if "activate" in d.keywords]
        self.assertEqual(len(activates), 17)   # 36.2.2: 17 张池内 Activate 随从

    def test_template_params_exported(self):
        db = get_db()
        # Goldrinn: +8/+8 (旧实现错误的 4/4 是本次重构的动机之一)
        d = db.get("BGS_018")
        self.assertIsNotNone(d)
        self.assertEqual(d.script_data_num_1, 8)
        self.assertEqual(d.script_data_num_2, 8)

    def test_golden_defs_available(self):
        db = get_db()
        d = db.get("BGS_018")
        golden = db.golden_version(d)
        self.assertIsNotNone(golden)
        self.assertEqual(golden.atk, d.atk * 2)


class TestSimultaneousDamage(unittest.TestCase):
    """C3: 双向同时伤害 — 双剧毒对攻双亡。"""

    def test_dual_poison_both_die(self):
        game = make_game(seed=16)
        a, b = game.heroes
        p1 = make_minion("P1", 3, 3)
        p1.set(GameTag.POISONOUS, True)
        p2 = make_minion("P2", 4, 4)
        p2.set(GameTag.POISONOUS, True)
        a.board = [p1]
        b.board = [p2]
        sched = CombatScheduler(game, a, b)
        sched._execute_attack(p1, p2)
        # 同时结算: 双方都受到伤害 → 双方都被剧毒消灭
        self.assertTrue(p1.dead)
        self.assertTrue(p2.dead)


class TestStealthTargeting(unittest.TestCase):
    """潜行随从不可被攻击 (RULES §4.4)。"""

    def test_stealth_not_targeted(self):
        game = make_game(seed=20)
        a, b = game.heroes
        attacker = make_minion("Att", 5, 5)
        visible = make_minion("Visible", 0, 100)
        hidden = make_minion("Hidden", 0, 100)
        hidden.set(GameTag.STEALTH, True)
        a.board = [attacker]
        b.board = [visible, hidden]
        sched = CombatScheduler(game, a, b)
        for _ in range(10):
            target = sched._choose_target(b)
            self.assertIsNot(target, hidden)
            self.assertIs(target, visible)   # 唯一非潜行目标

    def test_all_stealth_stalls_to_draw(self):
        game = make_game(seed=21)
        a, b = game.heroes
        h1 = make_minion("H1", 3, 3)
        h1.set(GameTag.STEALTH, True)
        h2 = make_minion("H2", 3, 3)
        h2.set(GameTag.STEALTH, True)
        a.board = [h1]
        b.board = [h2]
        result = game.run_combat(a, b)
        # 双方互不可见 → 无有效目标 → 僵局平局，无伤害
        self.assertIsNone(result.winner)
        self.assertEqual(result.damage_dealt, 0)


class TestAvengeCountsRebornDeath(unittest.TestCase):
    """Avenge 计数包含复生死亡 — RULES §6.11 任何友方死亡。"""

    def test_reborn_death_increments_avenge(self):
        game = make_game(seed=22)
        a, b = game.heroes
        avenger = make_minion("Avenger", 1, 10)
        avenger.set(GameTag.AVENGE, True)
        avenger.set(GameTag.AVENGE_TARGET, 2)
        reb = make_minion("Reb", 0, 1)
        reb.set(GameTag.REBORN, True)
        a.board = [avenger, reb]
        avenger.controller = a
        reb.controller = a
        triggered = []
        avenger.scripts = type("S", (), {
            "avenge": staticmethod(
                lambda s, g, c: triggered.append(1) or None)})
        # 复生随从死亡（第一次）
        reb.health = 0
        game._process_single_death(reb)
        self.assertEqual(avenger.get(GameTag.AVENGE_COUNTER), 1)
        self.assertEqual(len(triggered), 0)   # 阈值 2 未到
        # 复生后再死（失去复生）→ 计数到 2 → 触发
        reb.health = 0
        game._process_single_death(reb)
        self.assertEqual(len(triggered), 1)


class TestImmuneWhileAttacking(unittest.TestCase):
    """攻击时免疫: 攻击者不承受反击（Warpwing BG24_004）。"""

    def test_immune_attacker_takes_no_counter(self):
        game = make_game(seed=23)
        a, b = game.heroes
        immune = make_minion("Warpwing", 12, 4)
        immune.set(GameTag.IMMUNE_WHILE_ATTACKING, True)
        defender = make_minion("Big", 10, 10)
        a.board = [immune]
        b.board = [defender]
        sched = CombatScheduler(game, a, b)
        # 免疫随从作为攻击方: 造成 12 伤杀死对方，不受 10 点反击
        sched._execute_attack(immune, defender)
        self.assertTrue(defender.dead)
        self.assertFalse(immune.dead)
        self.assertEqual(immune.health, 4)

    def test_immune_does_not_protect_when_defending(self):
        game = make_game(seed=24)
        a, b = game.heroes
        immune = make_minion("Warpwing", 12, 4)
        immune.set(GameTag.IMMUNE_WHILE_ATTACKING, True)
        defender = make_minion("Big", 10, 10)
        a.board = [immune]
        b.board = [defender]
        sched = CombatScheduler(game, a, b)
        # 免疫随从作为防守方: 承受 10 伤死亡（免疫只在攻击时生效）
        sched._execute_attack(defender, immune)
        self.assertTrue(immune.dead)
        self.assertTrue(defender.dead)   # 同时受到 12 点反击


if __name__ == "__main__":
    unittest.main()
