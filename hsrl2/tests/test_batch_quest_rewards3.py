"""批次 quest_rewards3 语义测试（16 个 id / 10 张奖励 + 6 张 token 法术）。

行为层断言（全部走真实路径: `complete_quest` 发放 → 真实
`_begin_recruit_for` / `buy_from_tavern` / `run_combat` /
`_process_single_death` / `play_spell`）:
  - 134 Friends Along the Way  真实 SoT → 手牌 +2 纳迦（race 由
                               CardDef.num(0)=92 解析）; 直接 hook 恰好
                               占池 2 份; 每回合再 +2; 对手手牌不沾
  - 306 Cooked Book            真实买入两次 → +num(0)/num(1) 后
                               improve（第二只翻倍）; 第一只不再变化;
                               对手买入不触发
  - 310 Partner in Crime       真实 complete_quest → 本英雄 `_Buddy_G`
                               （金色独立卡定义/基础 id）; 零池操作;
                               无伙伴英雄落空（正对照配对）
  - 715 Enhance-a-matic        真实 SoT → 手牌 +1 张 token（∈ 4 张）;
                               非池法术零池记账; 每回合各一次;
                               4 张 token 各自打出后 +5/+5 且获关键词
  - 718 Kidnap Sack            on_bind + SoT 各发一张 Spellcraft 法术
                               （带 SPELLCRAFT tag）; token 打出后把
                               酒馆卡移入手中且池记账不变; 金色/对手
                               酒馆卡不可选
  - 505 Tumbling Disaster      战斗中召唤 +1/+1、招募期召唤不吃;
                               Avenge(4) 永久 improve 为 2（后续召唤
                               +2/+2）; 真实 run_combat 内 4 死即触发;
                               对手召唤不沾
  - 509 Smelting Chamber       SoT 使 Tier @ 随从金色化（金色独立卡
                               定义）并 improve（下一回合目标档 +1）;
                               已金者跳过; 无候选仍推进（正对照）;
                               对手棋盘不变
  - 513 Open Auditions         真实 SoT → 恰好 1 个三选一 Buddy 发现;
                               选定入手且零池操作; 对手回合无选择
  - 006 Rushing Winds          on_bind + SoT 各发一张 Spellcraft 法术;
                               打出后定向目标获 Windfury + Divine Shield
  - 020 Perpetual Incantation  真实池法术 BG28_897 在绑定者手中 +4/+3、
                               未绑定者 +2/+2（owner 隔离）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.actions.discover import _pool_candidates
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_quest_rewards3 import (
    ENHANCED_PART_IDS,
    _ENHANCED_PART_KEYWORDS,
    KIDNAP_SACK_SPELL_ID,
    RUSHING_WINDS_SPELL_ID,
)
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有池卡（CardDef 核实; 无死亡/入场副作用）
T1_MINION = "BG20_100"        # Razorfen Geomancer 2/1 T1
T2_MINION = "BG22_202"        # Tad 2/2 T2
BANANA = "BG28_897"           # Tavern Dish Banana: 定向 +2/+2 酒馆法术
BUDDY_HERO = "BG20_HERO_100"  # Rokara（companion_id=77876）
NO_BUDDY_HERO = "BG34_HERO_000"   # Murozond, Unbounded（无伙伴）

IMPLEMENTED = (
    "BG24_Reward_134", "BG24_Reward_306", "BG24_Reward_310",
    "BG24_Reward_715", "BG24_Reward_715t", "BG24_Reward_715t2",
    "BG24_Reward_715t3", "BG24_Reward_715t4",
    "BG24_Reward_718", "BG24_Reward_718t",
    "BG28_Reward_505", "BG28_Reward_509", "BG28_Reward_513",
    "BG33_Reward_006", "BG33_Reward_006t", "BG33_Reward_020",
)

DEFERRED = (
    "BG24_Reward_135",
    "BG24_Reward_313",
    "BG27_Anomaly_555t",
)
# batch_quest_rewards4 已实现原 DEFERRED 中的 "Get a copy of '{0}'" 族 5 张
# （BG24_Reward_130 / BG27_Reward_802 / BG27_Reward_803 / BG28_Reward_510 /
#  BG33_Reward_021）——数据层 reward_dbf_id 落地后迁出本台账。
# batch_quest_rewards5 已实现 BG33_Reward_017（第二英雄技能槽，RULES §9.5）。
# batch_hero_rewards_final 已实现 BG24_Reward_113 / BG33_Reward_011
# ——迁出本台账（9 → 7）。
# batch_quest_rewards6（812/501）+ batch_quest_rewards7（719）已实现
# ——迁出本台账（7 → 4）。
# batch_quest_rewards8（2026-09-18）已实现 BG24_Reward_362 + 载荷 BGS_029
# ——迁出本台账（4 → 3; 余下 135/313/555t 的权威缺口见 QUEST_DEFERRED_SPEC §6）。

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 70):
    # 无被动英雄（TEST_H_* 无英雄技能定义）——排除英雄被动干扰
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def make_buddy_game(seed: int = 70):
    """真实英雄（伙伴数据链）; 不 start_game——排除英雄被动干扰。"""
    return Game([Hero(BUDDY_HERO, "Rokara"), Hero(NO_BUDDY_HERO, "Murozond")],
                get_db(), seed=seed)


def grant_quest_reward(game, hero, rid):
    """真实发放路径: hero._quest_reward_id + game.complete_quest。"""
    hero._quest_reward_id = rid
    game.complete_quest(hero)
    return hero.quest_rewards[-1]


def pool_minion_total(game):
    return sum(game.minion_pool.available(d.id) for d in game.db.pool_minions())


def pool_spell_total(game):
    return sum(game.spell_pool.available(d.id) for d in game.db.pool_spells())


def make_spell(game, hero, card_id):
    s = game.create_spell(card_id, controller=hero)
    hero.add_to_hand(s)
    return s


def kill_friendly(game, hero, n=1):
    """战斗上下文内处理 n 次友方死亡（真实 _process_single_death）。"""
    prev_in = game.in_combat
    prev_ac = game._active_combat
    game.in_combat = True
    if prev_ac is None:
        game._active_combat = (game.heroes[0], game.heroes[1])
    try:
        for _ in range(n):
            m = game.create_minion(T2_MINION, controller=hero)
            game.summon(hero, m)
            m.health = 0
            game._process_single_death(m)
    finally:
        game.in_combat = prev_in
        game._active_combat = prev_ac


# ══════════════════ 注册表 / 台账 ══════════════════

class TestRegistry(unittest.TestCase):
    def test_all_16_ids_registered(self):
        for rid in IMPLEMENTED:
            self.assertIn(rid, REGISTRY, rid)
            self.assertIsNotNone(get_db().get(rid), rid)
        self.assertEqual(len(IMPLEMENTED), 16)

    def test_deferred_ids_not_registered(self):
        for rid in DEFERRED:
            self.assertNotIn(rid, REGISTRY, rid)
        # 2026-09-18 batch_quest_rewards8 迁出 362 → 4 → 3
        self.assertEqual(len(DEFERRED), 3)
                                             #     （R113 / R011）
                                             # -3: quest_rewards6/7（812/501/719）

    def test_card_text_matches_avenge_threshold(self):
        text = get_db().get("BG28_Reward_505").text
        script = REGISTRY["BG28_Reward_505"]
        self.assertEqual(script.avenge_threshold, 4)
        self.assertIn("Avenge (4)", text)

    def test_token_spells_is_targeted(self):
        for rid in (KIDNAP_SACK_SPELL_ID, RUSHING_WINDS_SPELL_ID,
                    *ENHANCED_PART_IDS):
            self.assertTrue(getattr(REGISTRY[rid], "needs_target"), rid)


# ══════════════════ BG24_Reward_134 ══════════════════

class TestFriendsAlongTheWay(unittest.TestCase):
    RID = "BG24_Reward_134"

    def test_start_of_turn_grants_two_naga(self):
        g = make_game(seed=100)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        before = set(a.hand)
        g._begin_recruit_for(a)                 # 引擎真实 SoT 分发
        gained = [e for e in a.hand if e not in before]
        self.assertEqual(len(gained), 2)        # "2 random {0}"
        for m in gained:
            self.assertIsInstance(m, Minion)
            self.assertIn(m.race, (Race.NAGA, Race.ALL))
        self.assertEqual(b.hand, [])            # owner 隔离

    def test_hook_occupies_exactly_two_pool_copies(self):
        g = make_game(seed=101)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        cands = _pool_candidates(g, race=Race.NAGA)
        self.assertTrue(cands)
        before = sum(g.minion_pool.available(c) for c in cands)
        g.run_script_hook(reward, "start_of_turn")
        gained = [e for e in a.hand if isinstance(e, Minion)]
        self.assertEqual(len(gained), 2)
        after = sum(g.minion_pool.available(c) for c in cands)
        self.assertEqual(before - after, 2)     # 占池（RULES §2.3）

    def test_every_turn_and_owner_isolation(self):
        g = make_game(seed=102)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        g.run_script_hook(reward, "start_of_turn")
        g.run_script_hook(reward, "start_of_turn")
        self.assertEqual(len(a.hand), 4)        # 每次触发各 2 张
        g._begin_recruit_for(b)                 # 对手回合: 奖励不在 b 列表
        self.assertEqual([e for e in b.hand
                          if getattr(e, "race", None) in
                          (Race.NAGA, Race.ALL)], [])
        self.assertEqual(len(a.hand), 4)        # 对手回合不消耗本方奖励


# ══════════════════ BG24_Reward_306 Cooked Book ══════════════════

class TestCookedBook(unittest.TestCase):
    RID = "BG24_Reward_306"

    def _two_tavern_minions(self, g, hero):
        g.refresh_tavern(hero, free=True)
        by_id = {}
        for e in hero.tavern:
            if isinstance(e, Minion):
                by_id.setdefault(e.card_id, e)
        picks = list(by_id.values())
        self.assertGreaterEqual(len(picks), 2)
        return picks[0], picks[1]

    def test_buy_buffs_and_improves_each_purchase(self):
        g = make_game(seed=110)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        a.gold = 30
        m1, m2 = self._two_tavern_minions(g, a)
        d1, d2 = get_db().get(m1.card_id), get_db().get(m2.card_id)

        self.assertTrue(g.buy_from_tavern(a, m1))       # 真实购买路径
        self.assertEqual((m1.atk - d1.atk, m1.max_health - d1.health), (2, 2))
        self.assertTrue(g.buy_from_tavern(a, m2))
        # "improve this" → 第二次增量 = 2×num（+4/+4）
        self.assertEqual((m2.atk - d2.atk, m2.max_health - d2.health), (4, 4))
        # 已买入者不再变化
        self.assertEqual((m1.atk - d1.atk, m1.max_health - d1.health), (2, 2))

    def test_owner_isolation(self):
        g = make_game(seed=111)
        a, b = g.heroes
        grant_quest_reward(g, b, self.RID)              # 奖励挂 b
        a.gold = 30
        m1, _ = self._two_tavern_minions(g, a)
        d1 = get_db().get(m1.card_id)
        self.assertTrue(g.buy_from_tavern(a, m1))       # a 买 → 不触发
        self.assertEqual((m1.atk, m1.max_health), (d1.atk, d1.health))
        # 正对照: b 买 → 触发
        g.refresh_tavern(b, free=True)
        b.gold = 30
        mb = [e for e in b.tavern if isinstance(e, Minion)][0]
        db_ = get_db().get(mb.card_id)
        self.assertTrue(g.buy_from_tavern(b, mb))
        self.assertEqual((mb.atk - db_.atk, mb.max_health - db_.health), (2, 2))


# ══════════════════ BG24_Reward_310 Partner in Crime ══════════════════

class TestPartnerInCrime(unittest.TestCase):
    RID = "BG24_Reward_310"

    def test_grants_own_golden_buddy(self):
        g = make_buddy_game(seed=120)
        a, b = g.heroes
        hero_def = get_db().get(a.card_id)
        buddy = get_db().by_dbf(hero_def.companion_id)
        golden = get_db().golden_version(buddy)
        self.assertIsNotNone(golden)
        self.assertFalse(buddy.is_pool_minion)          # 伙伴不在池（RULES §9.4）

        before = pool_minion_total(g)
        grant_quest_reward(g, a, self.RID)
        buddies = [e for e in a.hand
                   if isinstance(e, Minion) and e.card_id == golden.id]
        self.assertEqual(len(buddies), 1)
        m = buddies[0]
        self.assertTrue(m.is_golden)
        self.assertEqual((m.atk, m.max_health), (golden.atk, golden.health))
        self.assertEqual(m.get(GameTag.TRIPLE_BASE_CARD_ID), buddy.id)
        self.assertEqual(pool_minion_total(g), before)  # 零池操作
        self.assertEqual(b.hand, [])                    # owner 隔离

    def test_hero_without_buddy_fizzles_with_positive_control(self):
        g = make_buddy_game(seed=121)
        a, b = g.heroes
        self.assertIsNone(get_db().get(b.card_id).companion_id)
        grant_quest_reward(g, b, self.RID)
        self.assertEqual(b.hand, [])                    # 落空
        grant_quest_reward(g, a, self.RID)              # 正对照
        self.assertEqual(len(a.hand), 1)


# ══════════════════ BG24_Reward_715 Enhance-a-matic ══════════════════

class TestEnhanceAMatic(unittest.TestCase):
    RID = "BG24_Reward_715"

    def test_sot_grants_one_random_part_each_turn(self):
        g = make_game(seed=130)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        g._begin_recruit_for(a)
        parts = [e for e in a.hand if e.card_id in ENHANCED_PART_IDS]
        self.assertEqual(len(parts), 1)
        self.assertIsInstance(parts[0], Spell)
        self.assertEqual(b.hand, [])                    # owner 隔离
        g._begin_recruit_for(a)                         # 每回合各一次
        parts = [e for e in a.hand if e.card_id in ENHANCED_PART_IDS]
        self.assertEqual(len(parts), 2)

    def test_part_is_non_pool_spell_zero_pool_accounting(self):
        g = make_game(seed=131)
        a = g.heroes[0]
        reward = grant_quest_reward(g, a, self.RID)
        before = pool_spell_total(g)
        g.run_script_hook(reward, "start_of_turn")
        parts = [e for e in a.hand if e.card_id in ENHANCED_PART_IDS]
        self.assertEqual(len(parts), 1)
        self.assertFalse(get_db().get(parts[0].card_id).is_pool_spell)
        self.assertEqual(pool_spell_total(g), before)


class TestEnhancedParts(unittest.TestCase):
    def test_each_part_buffs_and_grants_its_keyword(self):
        d = get_db().get(T2_MINION)
        for cid, keyword in _ENHANCED_PART_KEYWORDS.items():
            with self.subTest(cid=cid):
                g = make_game(seed=140)
                a = g.heroes[0]
                target = g.create_minion(T2_MINION, controller=a)
                g.summon(a, target)
                spell = make_spell(g, a, cid)
                self.assertTrue(g.play_spell(a, spell))
                choice = g.pending_choices.pop(0)
                self.assertEqual(choice.kind, "spell_target")
                choice.choose(0)
                self.assertEqual(target.atk, d.atk + 5)
                self.assertEqual(target.max_health, d.health + 5)
                self.assertTrue(target.has(keyword), cid)

    def test_no_candidate_fizzles_with_positive_control(self):
        g = make_game(seed=141)
        a = g.heroes[0]
        spell = make_spell(g, a, ENHANCED_PART_IDS[0])
        self.assertTrue(g.play_spell(a, spell))         # 空板: 无候选
        self.assertEqual(g.pending_choices, [])
        self.assertNotIn(spell, a.hand)                 # 法术照常消耗
        # 正对照: 同 setup 有随从 → 效果发生
        d = get_db().get(T2_MINION)
        target = g.create_minion(T2_MINION, controller=a)
        g.summon(a, target)
        spell2 = make_spell(g, a, ENHANCED_PART_IDS[0])
        self.assertTrue(g.play_spell(a, spell2))
        g.pending_choices.pop(0).choose(0)
        self.assertEqual(target.atk, d.atk + 5)
        self.assertTrue(target.has(GameTag.TAUNT))


# ══════════════════ BG28_Reward_505 Tumbling Disaster ══════════════════

class TestTumblingDisaster(unittest.TestCase):
    RID = "BG28_Reward_505"

    def test_in_combat_summon_buffed_recruit_summon_not(self):
        g = make_game(seed=150)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        out = g.create_minion(T2_MINION, controller=a)
        g.summon(a, out)                                # 招募期召唤
        self.assertEqual((out.atk, out.max_health), (2, 2))
        g.in_combat = True
        try:
            inc = g.create_minion(T2_MINION, controller=a)
            g.summon(a, inc)                            # 战斗内召唤
        finally:
            g.in_combat = False
        self.assertEqual((inc.atk, inc.max_health), (3, 3))   # +@ = num(0)

    def test_avenge_four_improves_permanently(self):
        g = make_game(seed=151)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        self.assertEqual(reward._tumbling_bonus, 1)
        kill_friendly(g, a, 3)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 3)
        self.assertEqual(reward._tumbling_bonus, 1)     # 未达标不 improve
        kill_friendly(g, a, 1)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 0)
        self.assertEqual(reward._tumbling_bonus, 2)     # Avenge(4) → 永久 +1
        g.in_combat = True
        try:
            inc = g.create_minion(T2_MINION, controller=a)
            g.summon(a, inc)
        finally:
            g.in_combat = False
        self.assertEqual((inc.atk, inc.max_health), (4, 4))   # +2/+2

    def test_real_combat_avenge_improves(self):
        g = make_game(seed=152)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        for _ in range(5):
            f = g.create_minion(T2_MINION, controller=a)
            g.run_actions(Buff(f, atk=-2, health=-1))   # 0/1 饲料（不还手）
            g.summon(a, f)
        tank = g.create_minion(T2_MINION, controller=b)
        g.run_actions(Buff(tank, atk=8, health=8))      # 10/10
        g.summon(b, tank)
        g.run_combat(a, b)                              # 真实战斗
        self.assertEqual(reward._tumbling_bonus, 2)     # 4 死 → Avenge(4)
        self.assertEqual(reward.get(GameTag.AVENGE_COUNTER, 0), 1)

    def test_owner_isolation(self):
        g = make_game(seed=153)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        g.in_combat = True
        try:
            enemy = g.create_minion(T2_MINION, controller=b)
            g.summon(b, enemy)
            own = g.create_minion(T2_MINION, controller=a)
            g.summon(a, own)
        finally:
            g.in_combat = False
        self.assertEqual((enemy.atk, enemy.max_health), (2, 2))   # 对手不沾
        self.assertEqual((own.atk, own.max_health), (3, 3))       # 正对照


# ══════════════════ BG28_Reward_509 Smelting Chamber ══════════════════

class TestSmeltingChamber(unittest.TestCase):
    RID = "BG28_Reward_509"

    def test_sot_goldenizes_tier_and_improves(self):
        g = make_game(seed=160)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        self.assertEqual(reward._smelting_tier, 1)
        t1 = g.create_minion(T1_MINION, controller=a)
        g.summon(a, t1)
        t2 = g.create_minion(T2_MINION, controller=a)
        g.summon(a, t2)
        gd1 = get_db().golden_version(get_db().get(T1_MINION))

        g.run_script_hook(reward, "start_of_turn")
        self.assertTrue(t1.is_golden)                    # 恰好 Tier 1
        self.assertEqual(t1.get(GameTag.CARD_ID), gd1.id)
        self.assertEqual(t1.max_health, gd1.health)
        self.assertFalse(t2.is_golden)                   # 其他档不动
        self.assertEqual(reward._smelting_tier, 2)       # improve

        gd2 = get_db().golden_version(get_db().get(T2_MINION))
        g.run_script_hook(reward, "start_of_turn")       # 目标档推进到 2
        self.assertTrue(t2.is_golden)
        self.assertEqual(t2.get(GameTag.CARD_ID), gd2.id)
        self.assertTrue(t1.is_golden)                    # 已金者保持
        self.assertEqual(b.board, [])                    # owner 隔离

    def test_already_golden_skipped_with_positive_control(self):
        g = make_game(seed=161)
        a = g.heroes[0]
        reward = grant_quest_reward(g, a, self.RID)
        gold = g.create_minion(T1_MINION, controller=a, golden=True)
        g.summon(a, gold)
        base_id = gold.get(GameTag.TRIPLE_BASE_CARD_ID)
        g.run_script_hook(reward, "start_of_turn")
        self.assertEqual(gold.get(GameTag.TRIPLE_BASE_CARD_ID), base_id)
        # 正对照: 同 tier 的非金随从会被金色化
        plain = g.create_minion(T1_MINION, controller=a)
        g.summon(a, plain)
        reward._smelting_tier = 1
        g.run_script_hook(reward, "start_of_turn")
        self.assertTrue(plain.is_golden)

    def test_whiff_still_improves_tier(self):
        g = make_game(seed=162)
        a = g.heroes[0]
        reward = grant_quest_reward(g, a, self.RID)
        t2 = g.create_minion(T2_MINION, controller=a)
        g.summon(a, t2)
        g.run_script_hook(reward, "start_of_turn")       # 无 T1 → 落空
        self.assertFalse(t2.is_golden)
        self.assertEqual(reward._smelting_tier, 2)       # improve 仍推进
        g.run_script_hook(reward, "start_of_turn")       # 现在命中 T2
        self.assertTrue(t2.is_golden)

    def test_real_sot_dispatch_goldenizes(self):
        g = make_game(seed=163)
        a = g.heroes[0]
        grant_quest_reward(g, a, self.RID)
        t1 = g.create_minion(T1_MINION, controller=a)
        g.summon(a, t1)
        g._begin_recruit_for(a)                          # 引擎真实分发
        self.assertTrue(t1.is_golden)


# ══════════════════ BG28_Reward_513 Open Auditions ══════════════════

class TestOpenAuditions(unittest.TestCase):
    RID = "BG28_Reward_513"

    def test_sot_offers_exactly_one_buddy_discover(self):
        g = make_game(seed=170)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        g._begin_recruit_for(a)
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices.pop(0)
        self.assertEqual(choice.kind, "discover_minion")
        self.assertEqual(len(choice.options), 3)         # "Discover" 三选一
        for o in choice.options:
            self.assertTrue(o.endswith("_Buddy"), o)
            self.assertFalse(o.endswith("_Buddy_G"), o)  # 排除金色版
        pick = choice.options[0]
        choice.choose(0)
        self.assertEqual(len(a.hand), 1)
        self.assertIsInstance(a.hand[0], Minion)
        self.assertEqual(a.hand[0].card_id, pick)
        self.assertEqual(b.hand, [])                     # owner 隔离

    def test_buddy_discover_is_zero_pool_operation(self):
        g = make_game(seed=171)
        a = g.heroes[0]
        reward = grant_quest_reward(g, a, self.RID)
        g.run_script_hook(reward, "start_of_turn")
        choice = g.pending_choices.pop(0)
        before = {cid: g.minion_pool.available(cid) for cid in choice.options}
        choice.choose(0)
        for cid, n in before.items():
            self.assertEqual(g.minion_pool.available(cid), n)  # 伙伴不在池

    def test_only_owner_turn_produces_choice(self):
        g = make_game(seed=172)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        g._begin_recruit_for(b)                          # 对手回合
        self.assertEqual(g.pending_choices, [])
        self.assertEqual(b.hand, [])
        g._begin_recruit_for(a)                          # 正对照
        self.assertEqual(len(g.pending_choices), 1)
        self.assertEqual(g.pending_choices[0].owner, a)


# ══════════════════ BG33_Reward_006 Rushing Winds ══════════════════

class TestRushingWinds(unittest.TestCase):
    RID = "BG33_Reward_006"

    def test_spellcraft_granted_on_bind_and_each_turn(self):
        g = make_game(seed=180)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        granted = [e for e in a.hand if e.card_id == RUSHING_WINDS_SPELL_ID]
        self.assertEqual(len(granted), 1)                # 获得即得第一张
        self.assertIsInstance(granted[0], Spell)
        self.assertTrue(granted[0].has(GameTag.SPELLCRAFT))
        g._begin_recruit_for(a)   # 真实回合开始（引擎生成第二张）
        granted = [e for e in a.hand if e.card_id == RUSHING_WINDS_SPELL_ID]
        self.assertEqual(len(granted), 2)
        self.assertEqual(b.hand, [])                     # owner 隔离

    def test_spell_grants_windfury_and_divine_shield(self):
        g = make_game(seed=181)
        a = g.heroes[0]
        grant_quest_reward(g, a, self.RID)
        target = g.create_minion(T2_MINION, controller=a)
        g.summon(a, target)
        spell = [e for e in a.hand
                 if e.card_id == RUSHING_WINDS_SPELL_ID][0]
        self.assertTrue(g.play_spell(a, spell))
        choice = g.pending_choices.pop(0)
        self.assertEqual(choice.kind, "spell_target")
        self.assertEqual(choice.options, [target])
        choice.choose(0)
        self.assertTrue(target.has(GameTag.WINDFURY))
        self.assertTrue(target.has(GameTag.DIVINE_SHIELD))

    def test_no_target_fizzles_with_positive_control(self):
        g = make_game(seed=182)
        a = g.heroes[0]
        reward = grant_quest_reward(g, a, self.RID)
        spell = [e for e in a.hand
                 if e.card_id == RUSHING_WINDS_SPELL_ID][0]
        self.assertTrue(g.play_spell(a, spell))          # 空板
        self.assertEqual(g.pending_choices, [])
        self.assertNotIn(spell, a.hand)
        # 正对照: 同 setup 有随从 + 再取一张 Spellcraft 法术 → 效果发生
        target = g.create_minion(T2_MINION, controller=a)
        g.summon(a, target)
        g._begin_recruit_for(a)                          # 引擎再发一张
        spell2 = [e for e in a.hand
                  if e.card_id == RUSHING_WINDS_SPELL_ID][0]
        self.assertTrue(g.play_spell(a, spell2))
        g.pending_choices.pop(0).choose(0)
        self.assertTrue(target.has(GameTag.WINDFURY))
        self.assertTrue(target.has(GameTag.DIVINE_SHIELD))


# ══════════════════ BG33_Reward_020 Perpetual Incantation ══════════════════

class TestPerpetualIncantation(unittest.TestCase):
    RID = "BG33_Reward_020"

    def test_extra_stats_on_real_tavern_spell(self):
        g = make_game(seed=190)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), 1)
        d = get_db().get(T2_MINION)
        target = g.create_minion(T2_MINION, controller=a)
        g.summon(a, target)
        spell = make_spell(g, a, BANANA)                 # 文本 +2/+2
        self.assertTrue(g.play_spell(a, spell))
        g.pending_choices.pop(0).choose(0)
        # 基础 +2/+2 → 绑定者 +4/+3
        self.assertEqual(target.atk, d.atk + 4)
        self.assertEqual(target.max_health, d.health + 3)

    def test_owner_isolation(self):
        g = make_game(seed=191)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        self.assertEqual(b.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)
        self.assertEqual(b.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), 0)
        d = get_db().get(T2_MINION)
        # 正对照（同 setup 同法术）: 绑定者 +4/+3
        own = g.create_minion(T2_MINION, controller=a)
        g.summon(a, own)
        spell_a = make_spell(g, a, BANANA)
        self.assertTrue(g.play_spell(a, spell_a))
        g.pending_choices.pop(0).choose(0)
        self.assertEqual(own.atk, d.atk + 4)
        self.assertEqual(own.max_health, d.health + 3)
        # 负对照: 未绑定者同一法术仍为 +2/+2
        target = g.create_minion(T2_MINION, controller=b)
        g.summon(b, target)
        spell = make_spell(g, b, BANANA)
        self.assertTrue(g.play_spell(b, spell))
        g.pending_choices.pop(0).choose(0)
        self.assertEqual(target.atk, d.atk + 2)
        self.assertEqual(target.max_health, d.health + 2)

    def test_repeated_acquisition_stacks(self):
        g = make_game(seed=192)
        a = g.heroes[0]
        grant_quest_reward(g, a, self.RID)
        grant_quest_reward(g, a, self.RID)               # "earned endlessly"
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 4)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), 2)


# ══════════════════ BG24_Reward_718 Kidnap Sack ══════════════════

class TestKidnapSack(unittest.TestCase):
    RID = "BG24_Reward_718"

    def test_spellcraft_granted_on_bind_and_each_turn(self):
        g = make_game(seed=200)
        a, b = g.heroes
        reward = grant_quest_reward(g, a, self.RID)
        granted = [e for e in a.hand if e.card_id == KIDNAP_SACK_SPELL_ID]
        self.assertEqual(len(granted), 1)
        self.assertTrue(granted[0].has(GameTag.SPELLCRAFT))
        g._begin_recruit_for(a)   # 真实回合开始（引擎 generate_for_hero 生成）
        granted = [e for e in a.hand if e.card_id == KIDNAP_SACK_SPELL_ID]
        self.assertEqual(len(granted), 2)
        self.assertEqual(b.hand, [])

    def test_move_tavern_card_to_hand_without_pool_accounting(self):
        g = make_game(seed=201)
        a = g.heroes[0]
        grant_quest_reward(g, a, self.RID)
        g.refresh_tavern(a, free=True)
        target = [e for e in a.tavern if isinstance(e, Minion)][0]
        avail_before = g.minion_pool.available(target.card_id)
        spell = [e for e in a.hand
                 if e.card_id == KIDNAP_SACK_SPELL_ID][0]
        self.assertTrue(g.play_spell(a, spell))
        choice = g.pending_choices.pop(0)
        self.assertEqual(choice.kind, "spell_target")
        self.assertIn(target, choice.options)
        choice.choose(choice.options.index(target))
        self.assertIn(target, a.hand)                    # "Move it to your hand"
        self.assertNotIn(target, a.tavern)
        self.assertEqual(target.zone, Zone.HAND)
        # 池记账不变（移入手中等价于买入，非 acquire/release）
        self.assertEqual(g.minion_pool.available(target.card_id), avail_before)

    def test_golden_and_enemy_tavern_cards_not_candidates(self):
        g = make_game(seed=202)
        a, b = g.heroes
        grant_quest_reward(g, a, self.RID)
        g.refresh_tavern(a, free=True)
        g.refresh_tavern(b, free=True)
        plain = [e for e in a.tavern if isinstance(e, Minion)][0]
        golden = g.create_minion(T2_MINION, controller=a, golden=True)
        golden.zone = Zone.TAVERN
        a.tavern.append(golden)
        enemy = [e for e in b.tavern if isinstance(e, Minion)][0]
        spell = [e for e in a.hand
                 if e.card_id == KIDNAP_SACK_SPELL_ID][0]
        self.assertTrue(g.play_spell(a, spell))
        choice = g.pending_choices.pop(0)
        self.assertIn(plain, choice.options)
        self.assertNotIn(golden, choice.options)         # "non-Golden card"
        self.assertNotIn(enemy, choice.options)          # 对手酒馆不可选
        # 正对照: 非金目标确实能被移走
        choice.choose(choice.options.index(plain))
        self.assertIn(plain, a.hand)
        self.assertIn(golden, a.tavern)                  # 金色卡留在酒馆


if __name__ == "__main__":
    unittest.main()
