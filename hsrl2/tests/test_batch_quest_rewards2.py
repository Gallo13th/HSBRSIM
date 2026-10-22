"""批次 quest_rewards2 语义测试（6 个 id / 5 张奖励 + 1 法术 token）。

行为层断言（真实路径: complete_quest 发放 → 真战斗/真死亡处理/真刷新/
真施法）:
  - 502 Boom Squad           真实 run_combat 内第 3 次友方死亡 → 敌方
                             最高 max_health 随从恰好 -10（damage 事件）;
                             同一战斗内再死不再触发
  - 504 Cycle of Energy      第 3 次友方死亡 → 手牌 +1 张池法术且池可用
                             数 -1; 第 2 次不触发; 对手手牌不变
  - 518 Stable Amalgamation  第 7 次友方死亡 → 50/50 全种族 Amalgam 入场;
                             第 6 次不触发; 满场（board_full）不召唤
  - 004 Grim Freshener       第 2 次友方死亡 → FREE_REFRESH_REMAINING=1;
                             真实手动刷新 0 金且次数归 0; 对手不沾
  - 504 Timeline Acceleration _begin_recruit_for 真实 SoT 分发 → 手牌
                             恰好 2 张 Accelerator; 再触发 +2
  - 504t Accelerator         定向变形 = 恰好高一级的随机池随从、占池
                             （金色 3 份）、保留附魔/金色; T6 目标上限
                             档 T6; 无候选落空
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.actions.discover import _pool_candidates
import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_quest_rewards2 import (
    ACCELERATOR_ID,
    AMALGAM_TOKEN_ID,
    AcceleratorScript,
    BoomSquadScript,
    CycleOfEnergyScript,
    GrimFreshenerScript,
    StableAmalgamationScript,
    TimelineAccelerationScript,
)
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有池卡（按 tier 选取，CardDef 核实; 无死亡/入场副作用）
#   BG22_202 Tad 2/2 T2（通用素材）; BG20_100 Razorfen Geomancer 2/1 T1
#   BG23_017 Sanguine Champion 9/3 T6
MURLOC = "BG22_202"
T1_MINION = "BG20_100"
T6_MINION = "BG23_017"

AVENGE_CARDS = (
    "BG27_Reward_502", "BG28_Reward_504", "BG28_Reward_518",
    "BG33_Reward_004",
)

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 70):
    # 无被动英雄（TEST_H_* 无英雄技能定义）——排除英雄被动对战斗/事件
    # 的干扰，保证断言只反映被测奖励
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def grant_quest_reward(game, hero, rid):
    """真实发放路径: hero._quest_reward_id + game.complete_quest。"""
    hero._quest_reward_id = rid
    game.complete_quest(hero)
    return hero.quest_rewards[-1]


def capture_damage(game, owner):
    """注册 damage 事件探针（minion=, amount=）；返回记录列表。"""
    hits = []

    def on_damage(g, minion=None, amount=0, source=None, **kw):
        hits.append((minion, amount))

    game.events.register(Listener(event="damage", owner=owner,
                                  callback=on_damage))
    return hits


def slay_in_combat(game, minion):
    """在战斗上下文内处理一次友方死亡（引擎仅战斗内计数 Avenge）。

    game._active_combat 置为全局双人对（combat.py CombatScheduler.run
    的真实形状），供 Boom Squad 定位对手。
    """
    minion.health = 0
    prev_in = game.in_combat
    prev_ac = game._active_combat
    game.in_combat = True
    if prev_ac is None:
        game._active_combat = (game.heroes[0], game.heroes[1])
    try:
        game._process_single_death(minion)
    finally:
        game.in_combat = prev_in
        game._active_combat = prev_ac


def summon_fodder(game, hero):
    """召唤一只 2/2 饲料并返回（后续 slay_in_combat 用）。"""
    m = game.create_minion(MURLOC, controller=hero)
    game.summon(hero, m)
    return m


def kill_fodder(game, hero, n):
    """连续 n 次友方死亡（战斗上下文）。"""
    for _ in range(n):
        slay_in_combat(game, summon_fodder(game, hero))


def pool_spell_total(game):
    return sum(game.spell_pool.available(d.id) for d in game.db.pool_spells())


def make_accelerator_spell(game, hero):
    spell = game.create_spell(ACCELERATOR_ID, controller=hero)
    hero.add_to_hand(spell)
    return spell


# ══════════════════ 注册表 ══════════════════

class TestRegistry(unittest.TestCase):
    IMPLEMENTED = (
        "BG27_Reward_502", "BG28_Reward_504", "BG28_Reward_518",
        "BG33_Reward_004", "BG27_Reward_504", "BG27_Reward_504t",
    )

    def test_all_registered(self):
        for rid in self.IMPLEMENTED:
            self.assertIn(rid, REGISTRY, rid)
            self.assertIsNotNone(get_db().get(rid), rid)
        self.assertEqual(len(self.IMPLEMENTED), 6)

    def test_avenge_thresholds_match_card_text(self):
        db = get_db()
        cases = (
            (BoomSquadScript, "BG27_Reward_502", 3),
            (CycleOfEnergyScript, "BG28_Reward_504", 3),
            (StableAmalgamationScript, "BG28_Reward_518", 7),
            (GrimFreshenerScript, "BG33_Reward_004", 2),
        )
        for cls, rid, threshold in cases:
            # 阈值来自文本字面量（CardDef 无模板参数——data 仅标
            # avenge=true）: 与文本 "Avenge (N)" 双向钉死
            self.assertEqual(cls.avenge_threshold, threshold, rid)
            self.assertIn(f"Avenge ({threshold})", db.get(rid).text, rid)

    def test_accelerator_is_targeted_spell(self):
        self.assertTrue(AcceleratorScript.needs_target)

    def test_timeline_defines_registered_sot_hook(self):
        self.assertTrue(callable(
            getattr(TimelineAccelerationScript, "start_of_turn", None)))


# ══════════════════ BG27_Reward_502 Boom Squad ══════════════════

class TestBoomSquad(unittest.TestCase):
    RID = "BG27_Reward_502"

    def _setup_real_combat(self, seed=200):
        """真实战斗: a 方 3× 0/1 饲料（0 攻 → 永不攻击、只被挨打），
        b 方 1× 1/100 坦克（max_health 100 唯一最高）+ 1× 1/2 小兵。"""
        g = make_game(seed=seed)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        for _ in range(3):
            fodder = g.create_minion(MURLOC, controller=a)
            g.run_actions(Buff(fodder, atk=-2, health=-1))   # 0/1
            g.summon(a, fodder)
        tank = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(tank, atk=-1, health=98))        # 1/100
        g.summon(b, tank)
        small = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(small, atk=-1, health=0))        # 1/2
        g.summon(b, small)
        return g, a, b, reward, tank, small

    def test_third_friendly_death_hits_highest_health_enemy(self):
        g, a, b, reward, tank, small = self._setup_real_combat()
        hits = capture_damage(g, reward)
        g.run_combat(a, b)
        ten = [(m, amt) for m, amt in hits if amt == 10]
        # 恰好一次 10 伤，且目标是敌方唯一最高 max_health 者（坦克）
        self.assertEqual(len(ten), 1)
        self.assertIs(ten[0][0], tank)
        self.assertEqual(tank.max_health, 100)          # 快照口径选键
        self.assertTrue(small.max_health < tank.max_health)
        # 计数触发后清零（引擎 game.py:1612-1616）
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)

    def test_two_deaths_do_not_trigger(self):
        g = make_game(seed=201)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        tank = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(tank, atk=0, health=48))         # 0/50
        g.summon(b, tank)
        hits = capture_damage(g, reward)
        kill_fodder(g, a, 2)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 2)
        self.assertEqual([h for h in hits if h[1] == 10], [])
        # 第 3 次达标 → 恰好在第 3 次触发
        slay_in_combat(g, summon_fodder(g, a))
        ten = [h for h in hits if h[1] == 10]
        self.assertEqual(len(ten), 1)
        self.assertIs(ten[0][0], tank)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)

    def test_picks_by_current_health_not_max_health(self):
        """对抗审查证伪修复: "highest-Health" = 当前生命（HS 术语/
        多语言佐证），不是 max_health——上限高但被打残的随从不得优先。"""
        g = make_game(seed=205)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        for _ in range(3):
            fodder = g.create_minion(MURLOC, controller=a)
            g.run_actions(Buff(fodder, atk=-2, health=-1))   # 0/1
            g.summon(a, fodder)
        wounded = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(wounded, atk=-1, health=98))      # 1/100 上限
        g.summon(b, wounded)
        wounded.set(GameTag.HEALTH, 1)                       # 当前血 1
        healthy = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(healthy, atk=-1, health=48))      # 1/50 满血
        g.summon(b, healthy)
        self.assertGreater(wounded.max_health, healthy.max_health)
        self.assertLess(wounded.health, healthy.health)
        hits = capture_damage(g, reward)
        g.run_combat(a, b)
        ten = [(m, amt) for m, amt in hits if amt == 10]
        self.assertEqual(len(ten), 1)
        self.assertIs(ten[0][0], healthy)                    # 当前生命最高者

    def test_no_active_combat_pair_fizzles(self):
        """无战斗对（_active_combat=None）→ 无法定位对手，落空。"""
        g = make_game(seed=202)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        tank = g.create_minion(MURLOC, controller=b)
        g.run_actions(Buff(tank, atk=0, health=48))
        g.summon(b, tank)
        hits = capture_damage(g, reward)
        for _ in range(3):
            m = summon_fodder(g, a)
            m.health = 0
            prev = g.in_combat
            g.in_combat = True            # 计数成立但无战斗对
            try:
                g._process_single_death(m)
            finally:
                g.in_combat = prev
        self.assertEqual([h for h in hits if h[1] == 10], [])
        self.assertEqual(tank.health, tank.max_health)
        # 正对照: 同一 setup 挂上战斗对后，第 3 次死亡必须触发
        # （证明上面"落空"来自 _active_combat 缺失，而非 hook 根本不跑）
        reward.set(GameTag.AVENGE_COUNTER, 0)
        g._active_combat = (a, b)
        try:
            for _ in range(3):
                m = summon_fodder(g, a)
                m.health = 0
                prev = g.in_combat
                g.in_combat = True
                try:
                    g._process_single_death(m)
                finally:
                    g.in_combat = prev
        finally:
            g._active_combat = None
        ten = [h for h in hits if h[1] == 10]
        self.assertEqual(len(ten), 1)
        self.assertIs(ten[0][0], tank)

    def test_owner_isolation_enemy_deaths_do_not_trigger(self):
        g = make_game(seed=203)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        own_tank = g.create_minion(MURLOC, controller=a)
        g.run_actions(Buff(own_tank, atk=0, health=98))     # 0/100 本方
        g.summon(a, own_tank)
        enemy_tank = g.create_minion(MURLOC, controller=b)  # 敌方靶子
        g.run_actions(Buff(enemy_tank, atk=0, health=48))   # 0/50
        g.summon(b, enemy_tank)
        hits = capture_damage(g, reward)
        kill_fodder(g, b, 3)                                # 对手方 3 死
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)
        self.assertEqual([h for h in hits if h[1] == 10], [])
        self.assertEqual(own_tank.health, own_tank.max_health)
        self.assertEqual(enemy_tank.health, enemy_tank.max_health)
        # 正对照: 本方 3 死必须触发（证明 owner 判定而非 hook 失效）
        kill_fodder(g, a, 3)
        ten = [h for h in hits if h[1] == 10]
        self.assertEqual(len(ten), 1)
        self.assertIs(ten[0][0], enemy_tank)


# ══════════════════ BG28_Reward_504 Cycle of Energy ══════════════════

class TestCycleOfEnergy(unittest.TestCase):
    RID = "BG28_Reward_504"

    def test_third_death_grants_pool_spell_and_occupies_pool(self):
        g = make_game(seed=210)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        pool_ids = {d.id for d in g.db.pool_spells()}
        before = pool_spell_total(g)
        hand_before = list(a.hand)

        kill_fodder(g, a, 2)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 2)
        self.assertEqual(list(a.hand), hand_before)         # 未达标不发放

        kill_fodder(g, a, 1)
        gained = [e for e in a.hand if e not in hand_before]
        self.assertEqual(len(gained), 1)
        self.assertIsInstance(gained[0], Spell)
        self.assertIn(gained[0].card_id, pool_ids)          # "Tavern spell"
        self.assertEqual(pool_spell_total(g), before - 1)   # 占池 1 份
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)
        # owner 隔离: 对手手牌不变
        self.assertEqual(len(b.hand), 0)

    def test_only_owner_receives_spell(self):
        g = make_game(seed=211)
        a, b = g.heroes
        reward = grant_quest_reward(g, b, self.RID)         # 奖励挂 b
        kill_fodder(g, a, 3)                                # a 方死亡
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)
        self.assertEqual(len(b.hand), 0)
        kill_fodder(g, b, 3)
        self.assertEqual(len(b.hand), 1)
        self.assertEqual(len(a.hand), 0)


# ══════════════════ BG28_Reward_518 Stable Amalgamation ══════════════════

class TestStableAmalgamation(unittest.TestCase):
    RID = "BG28_Reward_518"

    def test_seventh_death_summons_50_50_amalgam(self):
        g = make_game(seed=220)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        token_def = get_db().get(AMALGAM_TOKEN_ID)
        self.assertEqual((token_def.atk, token_def.health), (50, 50))
        self.assertEqual(token_def.race, Race.ALL)
        self.assertFalse(token_def.is_pool_minion)          # token 不占池

        kill_fodder(g, a, 6)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 6)
        self.assertEqual(len(a.board), 0)                   # 第 6 次不召唤

        kill_fodder(g, a, 1)
        tokens = [m for m in a.board
                  if m.card_id == AMALGAM_TOKEN_ID]
        self.assertEqual(len(tokens), 1)
        token = tokens[0]
        self.assertEqual(token.atk, token_def.atk)          # 50
        self.assertEqual(token.max_health, token_def.health)  # 50
        self.assertEqual(token.health, token_def.health)
        self.assertEqual(token.race, Race.ALL)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)
        # owner 隔离
        self.assertEqual(len(b.board), 0)

    def test_full_board_skips_summon_until_space(self):
        g = make_game(seed=221)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        for _ in range(C.BOARD_SIZE):
            g.summon(a, g.create_minion(MURLOC, controller=a))
        self.assertTrue(a.board_full())
        g.run_script_hook(reward, "avenge")                 # 直接触发钩子
        self.assertEqual(len(a.board), C.BOARD_SIZE)
        self.assertEqual([m for m in a.board
                          if m.card_id == AMALGAM_TOKEN_ID], [])
        # 让出一个板位 → 条件成立，正常召唤
        a.board.pop(0)
        g.run_script_hook(reward, "avenge")
        tokens = [m for m in a.board if m.card_id == AMALGAM_TOKEN_ID]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].max_health, 50)


# ══════════════════ BG33_Reward_004 Grim Freshener ══════════════════

class TestGrimFreshener(unittest.TestCase):
    RID = "BG33_Reward_004"

    def test_second_death_grants_free_refresh_consumed_by_refresh(self):
        g = make_game(seed=230)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        a.gold = 10

        kill_fodder(g, a, 1)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 1)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)

        kill_fodder(g, a, 1)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 1)

        # 真实读取点: 手动刷新优先消耗免费次数（game.refresh_tavern）
        gold_before = a.gold
        g.refresh_tavern(a)
        self.assertEqual(a.gold, gold_before)               # 0 金
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)
        # 次数耗尽 → 回落金币
        g.refresh_tavern(a)
        self.assertEqual(a.gold, gold_before - C.REFRESH_COST)

    def test_accumulates_and_owner_isolated(self):
        g = make_game(seed=231)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        kill_fodder(g, a, 4)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 2)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)
        self.assertEqual(b.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)


# ══════════════════ BG27_Reward_504 Timeline Acceleration ══════════════════

class TestTimelineAcceleration(unittest.TestCase):
    RID = "BG27_Reward_504"

    def test_start_of_turn_grants_two_accelerators(self):
        g = make_game(seed=240)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        pool_before = pool_spell_total(g)

        g._begin_recruit_for(a)          # 引擎真实 SoT 分发（game.py:223-228）
        accs = [e for e in a.hand if e.card_id == ACCELERATOR_ID]
        self.assertEqual(len(accs), 2)                      # "two Accelerators"
        self.assertTrue(all(isinstance(e, Spell) for e in accs))
        # 非池法术不占池（SOP §3 token 语义）
        self.assertEqual(pool_spell_total(g), pool_before)

        g._begin_recruit_for(a)
        accs = [e for e in a.hand if e.card_id == ACCELERATOR_ID]
        self.assertEqual(len(accs), 4)                      # 每回合各一次
        # owner 隔离: 对手手牌不变
        self.assertEqual([e for e in b.hand
                          if e.card_id == ACCELERATOR_ID], [])

    def test_reward_only_fires_for_its_owner_turn(self):
        g = make_game(seed=241)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        g._begin_recruit_for(b)          # 对手回合: 奖励不在 b 的列表
        self.assertEqual([e for e in b.hand
                          if e.card_id == ACCELERATOR_ID], [])
        self.assertEqual([e for e in a.hand
                          if e.card_id == ACCELERATOR_ID], [])


# ══════════════════ BG27_Reward_504t Accelerator ══════════════════

class TestAccelerator(unittest.TestCase):
    TID = ACCELERATOR_ID

    def test_transforms_into_next_tier_and_occupies_pool(self):
        g = make_game(seed=250)
        a, b = g.heroes
        target = g.create_minion(T1_MINION, controller=a)
        target.add_buff(Enchant(atk=2, health=2))           # 附魔保留探针
        g.summon(a, target, 0)
        self.assertEqual(target.tech_level, 1)
        avail_before = {cid: g.minion_pool.available(cid)
                        for cid in _pool_candidates(g, min_tier=2, max_tier=2)}
        spell = make_accelerator_spell(g, a)

        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices.pop(0)
        self.assertEqual(choice.kind, "spell_target")
        self.assertEqual(choice.options, [target])          # 友方存活候选
        choice.choose(0)

        new = a.board[0]
        self.assertIsNot(new, target)
        self.assertEqual(target.zone.name, "REMOVED")
        self.assertEqual(new.tech_level, 2)                 # 恰好高一级
        cands_t2 = set(_pool_candidates(g, min_tier=2, max_tier=2))
        self.assertIn(new.card_id, cands_t2)
        d = get_db().get(new.card_id)
        self.assertEqual((new.atk, new.max_health),
                         (d.atk + 2, d.health + 2))         # 附魔保留
        self.assertFalse(new.is_golden)
        self.assertNotIn(spell, a.hand)                     # 法术已消耗
        # 普通目标占池恰好 1 份（P2）
        self.assertEqual(avail_before[new.card_id]
                         - g.minion_pool.available(new.card_id), 1)

    def test_golden_target_stays_golden_and_occupies_three(self):
        g = make_game(seed=251)
        a = g.heroes[0]
        target = g.create_minion(T1_MINION, controller=a, golden=True)
        self.assertTrue(target.is_golden)
        g.summon(a, target, 0)
        avail_before = {cid: g.minion_pool.available(cid)
                        for cid in _pool_candidates(g, min_tier=2, max_tier=2)}
        spell = make_accelerator_spell(g, a)

        g.play_spell(a, spell)
        g.pending_choices.pop(0).choose(0)

        new = a.board[0]
        self.assertTrue(new.is_golden)                      # Transform 保金色
        self.assertEqual(new.tech_level, 2)
        # 金色产物 card_id = 金色独立卡定义（db.golden_version）
        new_def = get_db().get(new.card_id)
        self.assertTrue(new_def.is_golden_def)
        self.assertEqual(new.max_health, new_def.health)
        # 占池按**基础**卡 id 记账（acquire 的是 _pool_candidates 的 id）
        base_id = new.get(GameTag.TRIPLE_BASE_CARD_ID)
        self.assertEqual(base_id,
                         get_db().by_dbf(new_def.triple_base_id).id)
        self.assertEqual(avail_before[base_id]
                         - g.minion_pool.available(base_id), 3)

    def test_partial_pool_golden_target_does_not_leak(self):
        """对抗审查 N3: 池里只剩 1 份新卡时，金色 target 的产物必须打
        GILDED_NOT_TRIPLED（扣 1 份 → 回 1 份），否则净泄漏 2 份。"""
        from collections import Counter
        g = make_game(seed=255)
        a = g.heroes[0]
        target = g.create_minion(T1_MINION, controller=a, golden=True)
        g.summon(a, target, 0)
        t2 = _pool_candidates(g, min_tier=2, max_tier=2)
        g.minion_pool._available = Counter({cid: 1 for cid in t2})
        spell = make_accelerator_spell(g, a)
        g.play_spell(a, spell)
        g.pending_choices.pop(0).choose(0)
        new = a.board[0]
        base_id = new.get(GameTag.TRIPLE_BASE_CARD_ID)
        self.assertTrue(new.is_golden)
        self.assertEqual(g.minion_pool.available(base_id), 0)   # 扣 1 份
        self.assertTrue(new.get(GameTag.GILDED_NOT_TRIPLED, False))
        self.assertTrue(g.sell_minion(a, new))
        self.assertEqual(g.minion_pool.available(base_id), 1)   # 只回 1 份

    def test_target_at_max_tier_caps_at_max_tavern_tier(self):
        g = make_game(seed=252)
        a = g.heroes[0]
        self.assertEqual(g.max_tavern_tier, 6)
        target = g.create_minion(T6_MINION, controller=a)
        g.summon(a, target, 0)
        self.assertEqual(target.tech_level, 6)
        avail_before = {cid: g.minion_pool.available(cid)
                        for cid in _pool_candidates(g, min_tier=6,
                                                   max_tier=6)}
        spell = make_accelerator_spell(g, a)
        g.play_spell(a, spell)
        g.pending_choices.pop(0).choose(0)
        new = a.board[0]
        self.assertEqual(new.tech_level, g.max_tavern_tier)  # 上限档
        # 非空断言（对抗审查: 旧版只重读 tier 6，hook no-op 也能过）:
        # 变形真的发生 + 新卡来自 T6 池 + 恰好占 1 份池副本
        self.assertIsNot(new, target)
        self.assertEqual(target.zone.name, "REMOVED")
        self.assertIn(new.card_id, avail_before)
        self.assertEqual(avail_before[new.card_id]
                         - g.minion_pool.available(new.card_id), 1)

    def test_no_target_candidate_consumes_spell_without_transform(self):
        g = make_game(seed=253)
        a, b = g.heroes
        enemy = g.create_minion(MURLOC, controller=b)
        g.summon(b, enemy, 0)                               # 仅对手有随从
        spell = make_accelerator_spell(g, a)
        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual(g.pending_choices, [])             # 无友方候选
        self.assertEqual(len(a.board), 0)
        self.assertNotIn(spell, a.hand)                     # 法术照常消耗
        self.assertEqual(b.board[0], enemy)                 # 对手不受影响
        # 正对照（对抗审查: no-op 也能过 → 必须证明同 setup 下有效果路径）:
        # 给本方一个随从后再打一张 → 出现目标选择且变形发生
        own = g.create_minion(T1_MINION, controller=a)
        g.summon(a, own, 0)
        spell2 = make_accelerator_spell(g, a)
        self.assertTrue(g.play_spell(a, spell2))
        self.assertEqual(len(g.pending_choices), 1)
        g.pending_choices.pop(0).choose(0)
        self.assertIsNot(a.board[0], own)
        self.assertEqual(a.board[0].tech_level, 2)

    def test_owner_isolation_only_targets_own_board(self):
        g = make_game(seed=254)
        a, b = g.heroes
        own = g.create_minion(T1_MINION, controller=a)
        g.summon(a, own, 0)
        enemy = g.create_minion(MURLOC, controller=b)
        g.summon(b, enemy, 0)
        spell = make_accelerator_spell(g, a)
        g.play_spell(a, spell)
        choice = g.pending_choices.pop(0)
        self.assertEqual(choice.options, [own])             # 敌方不可选
        choice.choose(0)
        self.assertTrue(all(m.controller is a for m in a.board))
        # 非空断言: 本方目标真的被变形（no-op 下这两条会失败）
        self.assertIsNot(a.board[0], own)
        self.assertEqual(own.zone.name, "REMOVED")
        self.assertEqual(a.board[0].tech_level, 2)
        self.assertEqual(b.board, [enemy])                  # 敌方实体不变
        self.assertEqual(b.board, [enemy])                  # 对手棋盘不变
        self.assertEqual(enemy.tech_level, 2)


if __name__ == "__main__":
    unittest.main()
