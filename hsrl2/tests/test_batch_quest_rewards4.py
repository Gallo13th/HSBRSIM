"""批次 quest_rewards4 语义测试（5 张 "Get a copy of '{0}'" 族）。

全部走真实路径: `hero._quest_reward_id = rid` + `game.complete_quest(hero)`
（on_bind 分发），随后用**真实触发器**验证第二句额外触发:
  - BG24_Reward_130 Ghastly Mask   真实 `end_recruit_phase` → 棋盘探针
                                    EoT 钩子 2 次（基线 1 + eot_extra 1）
  - BG27_Reward_802 Gilnean War Horn 真实 `play_minion` → 探针战吼 2 次
  - BG27_Reward_803 Turbulent Tombs  真实 `_process_single_death`（战斗内）
                                    → 探针亡语 2 次; 池占 1 份; 池空落空
                                    但配额仍生效（正对照）
  - BG33_Reward_021 Rallying Cry     真实 `run_combat` → rally 钩子次数
                                    为无配额基线（奖励挂对手）的 2 倍
  - BG28_Reward_510 Secret Culprit   授予 = `Db.by_dbf(reward_dbf_id)`
                                    （BG27_518 Moira Bronzebeard, T7）;
                                    白板副本; 零池操作; 不解锁 T7
每个类的**副本身份/池delta** 断言与 **额外触发** 断言并存——
把该类 on_bind 换成 no-op 后全部失败（非空转; SOP §16）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

IMPLEMENTED = (
    "BG24_Reward_130", "BG27_Reward_802", "BG27_Reward_803",
    "BG33_Reward_021", "BG28_Reward_510",
)
DEFERRED = ()
# batch_hero_rewards_final 已实现 BG24_Reward_113——迁出本台账（2 → 1）。
# batch_quest_rewards7 已实现 BG24_Reward_719（临时金色原语）——迁出（1 → 0）。

# 探针/测试用随从（CardDef 核实; 无死亡/入场副作用）
PROBE_ID = "BG25_011"


_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 200):
    # 无英雄技能脚本的测试英雄——排除被动（Deathwing 等）污染
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def grant_quest_reward(game, hero, rid):
    """真实发放路径: hero._quest_reward_id + game.complete_quest。"""
    hero._quest_reward_id = rid
    game.complete_quest(hero)
    return hero.quest_rewards[-1]


def expected_target(rid):
    """`{0}` 指向的卡——运行时经 reward_dbf_id 解析（禁止硬编码）。"""
    d = get_db().get(rid)
    return get_db().by_dbf(d.reward_dbf_id)


def pool_minion_total(game):
    return sum(game.minion_pool.available(d.id)
               for d in game.db.pool_minions())


def hand_minions(hero):
    return [e for e in hero.hand if isinstance(e, Minion)]


def probe_script(hook, bucket):
    """带指定钩子的探针脚本类（每次触发向 bucket 记录一次）。"""
    return type("_Probe", (), {
        hook: staticmethod(
            lambda s, g, c=None, **kw: bucket.append(s) or None)})


def add_probe(game, hero, hook, bucket, *, atk=0, health=10):
    m = Minion("TEST_PROBE", "P", atk=atk, health=health)
    m.scripts = probe_script(hook, bucket)
    game.summon(hero, m)
    return m


def assert_plain_copy(test, hero, target):
    """授予物 = 恰一张 target 的**白板**副本。"""
    got = hand_minions(hero)
    test.assertEqual([m.card_id for m in got], [target.id])
    m = got[0]
    test.assertFalse(m.is_golden)
    test.assertEqual((m.atk, m.max_health), (target.atk, target.health))
    test.assertEqual(list(m._buffs), [])       # 无附魔
    test.assertEqual(m.zone, Zone.HAND)
    return m


# ══════════════════ 注册表 / 台账 ══════════════════

class TestRegistry(unittest.TestCase):
    def test_implemented_ids_registered_and_have_reward_target(self):
        for rid in IMPLEMENTED:
            self.assertIn(rid, REGISTRY, rid)
            d = get_db().get(rid)
            self.assertIsNotNone(d, rid)
            self.assertIsNotNone(d.reward_dbf_id, rid)
            target = get_db().by_dbf(d.reward_dbf_id)
            self.assertIsNotNone(target, rid)
        self.assertEqual(len(IMPLEMENTED), 5)

    def test_deferred_ids_not_registered(self):
        for rid in DEFERRED:
            self.assertNotIn(rid, REGISTRY, rid)
        self.assertEqual(len(DEFERRED), 0)   # -1: batch_hero_rewards_final (R113)
                                             # -1: batch_quest_rewards7 (719)

    def test_each_reward_target_is_distinct_minion(self):
        """5 张奖励的 {0} 是 5 张**不同**的随从（tag 2673 逐卡固定）。"""
        ids = {expected_target(r).id for r in IMPLEMENTED}
        self.assertEqual(len(ids), 5)
        for rid in IMPLEMENTED:
            self.assertTrue(expected_target(rid).is_minion, rid)


# ══════════════════ BG24_Reward_130 Ghastly Mask ══════════════════

class TestGhastlyMask(unittest.TestCase):
    RID = "BG24_Reward_130"

    def test_grants_plain_copy_of_reward_card_zero_pool(self):
        g = make_game(seed=200)
        a, b = g.heroes
        target = expected_target(self.RID)
        self.assertFalse(target.is_pool_minion)      # 池外轮换卡
        before = pool_minion_total(g)
        grant_quest_reward(g, a, self.RID)
        assert_plain_copy(self, a, target)
        self.assertEqual(pool_minion_total(g), before)   # 零池操作
        self.assertEqual(b.hand, [])                     # owner 隔离

    def test_eot_extra_triggers_own_eot_twice(self):
        g = make_game(seed=201)
        a, b = g.heroes
        calls_a, calls_b = [], []
        add_probe(g, a, "end_of_turn", calls_a)
        add_probe(g, b, "end_of_turn", calls_b)
        grant_quest_reward(g, a, self.RID)
        self.assertEqual(a.extra_trigger("eot_extra"), 1)
        g.end_recruit_phase()                        # 真实 EoT 分发
        self.assertEqual(len(calls_a), 2)            # 基线 1 + 配额 1
        self.assertEqual(len(calls_b), 1)            # owner 隔离

    def test_eot_extra_needs_reward_and_fires_twice(self):
        """负/正对照同测: 无奖励 → 1 次; 绑定奖励后 → 2 次。"""
        g = make_game(seed=202)
        a = g.heroes[0]
        calls = []
        add_probe(g, a, "end_of_turn", calls)
        self.assertEqual(a.extra_trigger("eot_extra"), 0)
        g.end_recruit_phase()
        self.assertEqual(len(calls), 1)              # 负对照: 基线 1 次
        grant_quest_reward(g, a, self.RID)
        self.assertEqual(a.extra_trigger("eot_extra"), 1)
        g.end_recruit_phase()
        self.assertEqual(len(calls) - 1, 2)          # 正对照: 配额后 2 次


# ══════════════════ BG27_Reward_802 Gilnean War Horn ══════════════════

class TestGilneanWarHorn(unittest.TestCase):
    RID = "BG27_Reward_802"

    def test_grants_plain_copy_of_reward_card_zero_pool(self):
        g = make_game(seed=210)
        a, b = g.heroes
        target = expected_target(self.RID)
        self.assertFalse(target.is_pool_minion)
        before = pool_minion_total(g)
        grant_quest_reward(g, a, self.RID)
        assert_plain_copy(self, a, target)
        self.assertEqual(pool_minion_total(g), before)
        self.assertEqual(b.hand, [])

    def test_bc_times_triggers_own_battlecry_twice(self):
        g = make_game(seed=211)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        self.assertEqual(a.extra_trigger("bc_times"), 1)
        self.assertEqual(a.extra_triggers.get("bc_race"), None)

        calls_a, calls_b = [], []
        for hero, bucket in ((a, calls_a), (b, calls_b)):
            m = g.create_minion(PROBE_ID, controller=hero)
            m.scripts = probe_script("battlecry", bucket)
            hero.add_to_hand(m)
        ma = [m for m in a.hand if m.card_id == PROBE_ID][0]
        mb = [m for m in b.hand if m.card_id == PROBE_ID][0]
        self.assertTrue(g.play_minion(a, ma))        # 真实打出
        self.assertTrue(g.play_minion(b, mb))
        self.assertEqual(len(calls_a), 2)            # 基线 1 + 配额 1
        self.assertEqual(len(calls_b), 1)            # owner 隔离


# ══════════════════ BG27_Reward_803 Turbulent Tombs ══════════════════

class TestTurbulentTombs(unittest.TestCase):
    RID = "BG27_Reward_803"

    def test_grants_pool_copy_and_occupies_one_pool_copies(self):
        g = make_game(seed=220)
        a, b = g.heroes
        target = expected_target(self.RID)
        self.assertTrue(target.is_pool_minion)       # T6 池随从
        before = g.minion_pool.available(target.id)
        grant_quest_reward(g, a, self.RID)
        m = assert_plain_copy(self, a, target)
        self.assertEqual(g.minion_pool.available(target.id), before - 1)
        self.assertEqual(b.hand, [])
        # 出售授予的副本 → 池配平（acquire/release 对称）
        self.assertTrue(g.sell_minion(a, m))
        self.assertEqual(g.minion_pool.available(target.id), before)

    def test_pool_exhausted_fizzles_copy_but_quota_still_applies(self):
        g = make_game(seed=221)
        a = g.heroes[0]
        target = expected_target(self.RID)
        while g.minion_pool.acquire(target.id):       # 抽干该卡池
            pass
        self.assertEqual(g.minion_pool.available(target.id), 0)
        grant_quest_reward(g, a, self.RID)
        self.assertEqual(hand_minions(a), [])         # 副本落空（RULES §2.4）
        self.assertEqual(a.extra_trigger("dr_extra"), 1)   # 第二句独立生效
        # 正对照: 池有余时确实入手
        g2 = make_game(seed=222)
        a2 = g2.heroes[0]
        self.assertGreater(g2.minion_pool.available(target.id), 0)
        grant_quest_reward(g2, a2, self.RID)
        self.assertEqual(len(hand_minions(a2)), 1)

    def test_dr_extra_triggers_own_deathrattle_twice(self):
        g = make_game(seed=223)
        a, b = g.heroes
        calls_a, calls_b = [], []
        ma = Minion("TEST_DR_A", "D", atk=0, health=1)
        ma.scripts = probe_script("deathrattle", calls_a)
        ma.set(GameTag.DEATHRATTLE, True)
        g.summon(a, ma)
        mb = Minion("TEST_DR_B", "D", atk=0, health=1)
        mb.scripts = probe_script("deathrattle", calls_b)
        mb.set(GameTag.DEATHRATTLE, True)
        g.summon(b, mb)
        grant_quest_reward(g, a, self.RID)
        g.in_combat = True
        g._active_combat = (a, b)
        try:
            for m in (ma, mb):
                m.health = 0
                g._process_single_death(m)
        finally:
            g.in_combat = False
            g._active_combat = None
        self.assertEqual(len(calls_a), 2)             # 全部亡语 +1
        self.assertEqual(len(calls_b), 1)             # owner 隔离


# ══════════════════ BG33_Reward_021 Rallying Cry ══════════════════

class TestRallyingCry(unittest.TestCase):
    RID = "BG33_Reward_021"

    def test_grants_plain_copy_of_reward_card_zero_pool(self):
        g = make_game(seed=230)
        a, b = g.heroes
        target = expected_target(self.RID)
        self.assertFalse(target.is_pool_minion)
        before = pool_minion_total(g)
        grant_quest_reward(g, a, self.RID)
        assert_plain_copy(self, a, target)
        self.assertEqual(pool_minion_total(g), before)
        self.assertEqual(b.hand, [])

    def _rally_count(self, seed, reward_on):
        """真实 run_combat 下 A 的 rally 探针触发次数。

        reward_on: None=不发奖励（基线） / "a"=奖励挂 A / "b"=奖励挂 B。
        奖励 on_bind 不消耗 rng → 三种 setup 的同 seed 战斗序列一致，
        可直接做倍数对比（正对照）。
        """
        g = make_game(seed=seed)
        a, b = g.heroes
        calls = []
        atk = Minion("TEST_RALLY", "R", atk=2, health=5)
        atk.scripts = probe_script("rally", calls)
        g.summon(a, atk)
        g.summon(b, Minion("TEST_DEF", "D", atk=0, health=20))
        if reward_on == "a":
            grant_quest_reward(g, a, self.RID)
        elif reward_on == "b":
            grant_quest_reward(g, b, self.RID)
        g.run_combat(a, b)
        return len(calls)

    def test_rally_extra_doubles_each_declaration(self):
        base = self._rally_count(seed=231, reward_on=None)
        self.assertGreater(base, 0)                   # 正对照: 基线确有 Rally
        # 确定性正对照: 同 setup 重跑得同值（排除噪声）
        self.assertEqual(self._rally_count(seed=231, reward_on=None), base)
        self.assertEqual(self._rally_count(seed=231, reward_on="a"),
                         base * 2)                    # 配额 1 → 每次 +1 次

    def test_owner_isolation_with_positive_control(self):
        base = self._rally_count(seed=232, reward_on=None)
        self.assertGreater(base, 0)
        # 负对照: 奖励挂 B → A 的 rally 不受影响（配额属 B）
        self.assertEqual(self._rally_count(seed=232, reward_on="b"), base)
        # 正对照: 奖励挂 A → A 的 rally 每次 +1 次声明
        self.assertEqual(self._rally_count(seed=232, reward_on="a"),
                         base * 2)


# ══════════════════ BG28_Reward_510 Secret Culprit ══════════════════

class TestSecretCulprit(unittest.TestCase):
    RID = "BG28_Reward_510"

    def test_grants_the_tier7_reward_card_as_plain_copy(self):
        g = make_game(seed=240)
        a, b = g.heroes
        d = get_db().get(self.RID)
        target = get_db().by_dbf(d.reward_dbf_id)
        self.assertEqual(target.id, "BG27_518")       # Moira Bronzebeard
        self.assertEqual(target.tech_level, 7)
        self.assertFalse(target.is_pool_minion)       # 奖励专属（池外）
        before = pool_minion_total(g)
        max_tier_before = g.max_tavern_tier
        grant_quest_reward(g, a, self.RID)
        assert_plain_copy(self, a, target)
        self.assertEqual(pool_minion_total(g), before)     # 零池操作
        self.assertEqual(b.hand, [])                       # owner 隔离
        # "from Tier 7" 是档位描述——授予 T7 卡**不**依赖 T7 解锁
        self.assertEqual(g.max_tavern_tier, max_tier_before)

    def test_copy_identity_follows_reward_dbf_id_not_hardcoded(self):
        """授予物身份 = by_dbf(reward_dbf_id)（正对照: 与 130 的 {0} 不同）。"""
        g = make_game(seed=241)
        a = g.heroes[0]
        grant_quest_reward(g, a, self.RID)
        mine = hand_minions(a)[0].card_id
        self.assertEqual(mine, expected_target(self.RID).id)
        other = expected_target("BG24_Reward_130").id
        self.assertNotEqual(mine, other)
        self.assertNotEqual(other, self.RID)

    def test_target_resolved_at_runtime_from_reward_dbf_id(self):
        """**运行时解析**证据: 改写 `CardDef.reward_dbf_id` → 授予物随之改
        变。旧版只断言"授予物 == 期望 id"——把 `_reward_target` 换成
        {rid: card_id} 硬编码映射后旧测试仍全绿（2026-09-13 对抗验证），
        本测试是唯一能捕获硬编码的形态。
        """
        src = get_db().get(self.RID)
        alt = get_db().get("BG27_Reward_802")          # 另一张 {0} 奖励
        self.assertNotEqual(src.reward_dbf_id, alt.reward_dbf_id)
        saved = src.reward_dbf_id
        object.__setattr__(src, "reward_dbf_id", alt.reward_dbf_id)
        try:
            g = make_game(seed=243)
            a = g.heroes[0]
            grant_quest_reward(g, a, self.RID)
            mine = hand_minions(a)[0].card_id
            self.assertEqual(mine, expected_target("BG27_Reward_802").id)
        finally:
            object.__setattr__(src, "reward_dbf_id", saved)
        # 还原后回到本卡 {0}（正对照）
        g2 = make_game(seed=244)
        a2 = g2.heroes[0]
        grant_quest_reward(g2, a2, self.RID)
        self.assertEqual(hand_minions(a2)[0].card_id,
                         get_db().by_dbf(saved).id)

    def test_positive_control_pool_card_grant_moves_pool(self):
        """对照 Turbulent Tombs（池卡）: 授予确实扣池 1 份。"""
        g = make_game(seed=242)
        a = g.heroes[0]
        pool_target = expected_target("BG27_Reward_803")
        before = g.minion_pool.available(pool_target.id)
        grant_quest_reward(g, a, "BG27_Reward_803")
        self.assertEqual(g.minion_pool.available(pool_target.id), before - 1)


if __name__ == "__main__":
    unittest.main()
