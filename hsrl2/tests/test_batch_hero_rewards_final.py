"""批次 hero_rewards_final 语义测试（2 张 CORRECT 任务奖励 + 台账守卫）。

行为层断言（全部走真实路径: `complete_quest` 发放 → 真实
`_begin_recruit_for` SoT 分发 / 真实 `run_combat` + `combat_end` 广播）:
  - BG24_Reward_113 Ritual Dagger  亡语随从战死后（棋盘复原后）永久
                                   +5/+5; 无亡语随从战死不沾（同方法负
                                   对照）; 对手亡语随从战死不沾
                                   （owner 隔离 + 正对照同方法）; 存活
                                   亡语随从不沾; 每场战斗各触发一次
                                   （第二场累计 +10）; 未参战的
                                   combat_end（hero 不在对中）不结算;
                                   未获奖励的英雄不触发
  - BG33_Reward_011 Magicfin Relic 真实 SoT → 入手恰 1 张 `BG33_890t`
                                   且零池记账; 恰 1 个本人
                                   kind=discover_tavern_spell 选择、
                                   `len(options)==3` 且互异、均为池法术
                                   且 tier ≤ 酒馆等级、选项均已预留;
                                   resolve 后 token `_taught_spell_id` ==
                                   所选、选中保留占池、未选项回池; 被教
                                   Shiny Ring 的 token 打出时全体随从
                                   +num(0)/+num(1)（teach 端到端）;
                                   对手无奖励不触发（owner 隔离）;
                                   每回合再入手一张; 池耗尽仍入手 token
                                   且本次落空（正对照: 有候选即产出选择）;
                                   同 seed 确定性

台账守卫（结构性, `@engine-only`）: 本批 15 张英雄技能 + 7 张任务奖励
DEFERRED 全部未注册; 2 张 CORRECT 已注册; token 数据链核实。

真实路径说明: `combat_end` 由 `end_recruit_phase` 在棋盘复原**之后**
广播（game.py:2298），`run_combat` 本身不广播——测试按引擎同一口径
`run_combat` + `events.fire("combat_end", ...)` 驱动（同
test_batch_quest_rewards.py::TestR138VictimsSpecter 既有约定）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.game import Game, GameStateError
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_hero_rewards_final import (
    _MAGICFIN_APPRENTICE,
    _MAGICFIN_RELIC,
    _RITUAL_DAGGER,
)
from hsrl2.tags import CardType, GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有池卡（CardDef 核实; 无死亡/入场副作用）
DR_MINION = "BG28_300"     # Harmless Bonehead 1/1 T1 Deathrattle
PLAIN_MINION = "BG22_202"  # Tad 2/2 T2（无亡语/无战斗效果）
BIG_MINION = "BG21_004"    # Insatiable Ur'zul 4/6 T5（纯 Taunt，白板体型）
SHINY_RING = "BG28_168"    # Shiny Ring: Give your minions +{0}/+{1}

IMPLEMENTED = (
    _RITUAL_DAGGER,
    _MAGICFIN_RELIC,
)

# 本批 DEFERRED 台账（模块 docstring 逐条 Status/Dependency/Path）——
# 全部保持未注册（SOP §6b 二态铁律）
DEFERRED_HERO_POWERS = (
    "BG20_HERO_202p",       # Master Nguyen Power of the Storm
    "BG20_HERO_242p",       # Guff Runetotem Natural Balance
    "BG20_HERO_283p",       # Galewing Dungar's Gryphon
    "BG21_HERO_000p",       # Cariel Roame Conviction
    "BG24_HERO_100p",       # Sire Denathrius Whodunit?
    "BG25_HERO_100p",       # Professor Putricide Build-An-Undead
    "BG31_HERO_801p",       # Jim Raynor Lift Off
    "BG31_HERO_811p",       # Kerrigan Spawning Pool
    "BG33_HERO_001p_ALT",   # Loh, the Living Legend Heroic Inspiration
    "BG34_HERO_000p",       # Murozond Alternate Timeline
    "BG34_HERO_004p",       # Morchie Warped Conflux
    "BG35_HERO_001p",       # Genn Greymane King of Duality
    "TB_BaconShop_HP_020",  # Akazamzarak Prestidigitation
    "TB_BaconShop_HP_101",  # Silas Darkmoon Come One, Come All!
    "TB_BaconShop_HP_106",  # Tickatus Prize Wall
)

DEFERRED_QUEST_REWARDS = (
    "BG24_Reward_135",      # Yogg-tastic Tasties
    "BG24_Reward_313",      # Wondrous Wisdomball
    "BG27_Anomaly_555t",    # No Place Like Holmes
)
# 已迁出（2026-09-13）: BG24_Reward_719 → batch_quest_rewards7;
# BG27_Reward_812 / BG28_Reward_501 → batch_quest_rewards6。
# 已迁出（2026-09-18 第四十九轮）: BG24_Reward_362 Essence of Zerus →
# batch_quest_rewards8（载荷 BGS_029 一并注册; wiki 权威见该批 docstring）。

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900):
    """无被动英雄（TEST_H_* 无英雄技能定义）——排除英雄被动干扰。"""
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def grant_quest_reward(game, hero, rid):
    """真实发放路径: hero._quest_reward_id + game.complete_quest。"""
    hero._quest_reward_id = rid
    game.complete_quest(hero)


def put(game, hero, card_id, position=None):
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m, position)
    return m


def fire_combat_end(game, hero_a, hero_b):
    game.events.fire(game, "combat_end", hero_a=hero_a, hero_b=hero_b,
                     result=None)


# ══════════════════ BG24_Reward_113 Ritual Dagger ══════════════════


class TestRitualDagger(unittest.TestCase):
    """BG24_Reward_113 — 友方亡语随从战死后永久 +5/+5。"""

    def test_deathrattle_death_buffs_restored_minion_with_control(self):
        """真实 run_combat: 亡语随从战死 +5/+5; 无亡语随从战死不变。"""
        g = make_game(seed=1301)
        a, b = g.heroes
        grant_quest_reward(g, a, _RITUAL_DAGGER)
        dr = put(g, a, DR_MINION, 0)
        plain = put(g, a, PLAIN_MINION, 1)
        enemy = put(g, b, BIG_MINION, 0)
        enemy.add_buff(Enchant(atk=40, health=40))
        dr_base = (dr.atk, dr.max_health)
        plain_base = (plain.atk, plain.max_health)
        self.assertTrue(dr.has(GameTag.DEATHRATTLE))
        self.assertFalse(plain.has(GameTag.DEATHRATTLE))

        g.run_combat(a, b)
        fire_combat_end(g, a, b)

        # 棋盘复原: 战死者以同一实体对象回到棋盘
        self.assertIn(dr, a.board)
        self.assertIn(plain, a.board)
        self.assertEqual((dr.atk, dr.max_health),
                         (dr_base[0] + 5, dr_base[1] + 5))     # 正效果
        self.assertEqual((plain.atk, plain.max_health), plain_base)  # 负对照

    def test_owner_isolation_opponent_deathrattle_untouched(self):
        """对手亡语随从战死不沾; 本人亡语随从战死沾（同方法正对照）。"""
        g = make_game(seed=1302)
        a, b = g.heroes
        grant_quest_reward(g, a, _RITUAL_DAGGER)
        a_dr = put(g, a, DR_MINION, 0)
        b_dr = put(g, b, DR_MINION, 0)
        b_big = put(g, b, BIG_MINION, 1)
        b_big.add_buff(Enchant(atk=40, health=40))
        a_base = (a_dr.atk, a_dr.max_health)
        b_base = (b_dr.atk, b_dr.max_health)

        g.run_combat(a, b)
        fire_combat_end(g, a, b)

        self.assertIn(a_dr, a.board)
        self.assertIn(b_dr, b.board)
        self.assertEqual((a_dr.atk, a_dr.max_health),
                         (a_base[0] + 5, a_base[1] + 5))    # 本人: 正效果
        self.assertEqual((b_dr.atk, b_dr.max_health), b_base)  # 对手: 隔离

        # 未参战的 combat_end（hero 不在对中）不重复结算
        fire_combat_end(g, b, b)
        self.assertEqual((a_dr.atk, a_dr.max_health),
                         (a_base[0] + 5, a_base[1] + 5))

    def test_survivor_and_hero_without_reward_untouched(self):
        """存活亡语随从不沾; 未获奖励英雄的亡语随从战死不沾。"""
        g = make_game(seed=1303)
        a, b = g.heroes
        grant_quest_reward(g, a, _RITUAL_DAGGER)
        # A: 1/1 亡语随从（左首位 → 本轮攻击并战死，正对照）+
        #    巨型亡语随从（存活，负对照）
        dies = put(g, a, DR_MINION, 0)
        survivor = put(g, a, DR_MINION, 1)
        survivor.add_buff(Enchant(atk=30, health=30))
        # B: 单只中型随从（杀死 1/1、被 survivor 击杀）
        big = put(g, b, BIG_MINION, 0)
        big.add_buff(Enchant(atk=10, health=20))   # 14/26
        surv_base = (survivor.atk, survivor.max_health)
        dies_base = (dies.atk, dies.max_health)

        g.run_combat(a, b)
        fire_combat_end(g, a, b)

        self.assertIn(dies, a.board)
        self.assertEqual((dies.atk, dies.max_health),
                         (dies_base[0] + 5, dies_base[1] + 5))   # 正效果
        self.assertEqual((survivor.atk, survivor.max_health), surv_base)

        # 未获奖励的英雄: 其亡语随从战死不变（owner 隔离的第二面）
        g2 = make_game(seed=1304)
        a2, b2 = g2.heroes
        b2_dr = put(g2, b2, DR_MINION, 0)
        a2_big = put(g2, a2, BIG_MINION, 0)
        a2_big.add_buff(Enchant(atk=40, health=40))
        b2_base = (b2_dr.atk, b2_dr.max_health)
        g2.run_combat(a2, b2)
        fire_combat_end(g2, a2, b2)
        self.assertEqual((b2_dr.atk, b2_dr.max_health), b2_base)

    def test_buff_accumulates_each_combat(self):
        """每场战斗各触发一次: 第二场后累计 +10/+10。"""
        g = make_game(seed=1305)
        a, b = g.heroes
        grant_quest_reward(g, a, _RITUAL_DAGGER)
        dr = put(g, a, DR_MINION, 0)
        big = put(g, b, BIG_MINION, 0)
        big.add_buff(Enchant(atk=40, health=40))
        base = (dr.atk, dr.max_health)

        g.run_combat(a, b)
        fire_combat_end(g, a, b)
        self.assertEqual((dr.atk, dr.max_health),
                         (base[0] + 5, base[1] + 5))

        g.run_combat(a, b)
        fire_combat_end(g, a, b)
        self.assertEqual((dr.atk, dr.max_health),
                         (base[0] + 10, base[1] + 10))


# ══════════════════ BG33_Reward_011 Magicfin Relic ══════════════════


def _relic_tokens(hero):
    return [c for c in hero.hand
            if isinstance(c, Minion) and c.card_id == _MAGICFIN_APPRENTICE]


def _discover_choices(game, owner=None):
    return [c for c in game.pending_choices
            if c.kind == "discover_tavern_spell"
            and (owner is None or c.owner is owner)]


def _fire_reward_sot(game, hero):
    """引擎分发原语: `_begin_recruit_for` 对 quest_rewards 的同一调用
    （game.py:278 `run_script_hook(reward, "start_of_turn")`）。"""
    for reward in list(hero.quest_rewards):
        game.run_script_hook(reward, "start_of_turn")


def _sot_turn(game, hero, turn=2):
    """真实回合开始（含酒馆刷新/回合计数）——验证引擎接线。"""
    game.pending_choices.clear()
    game.turn = turn
    game._begin_recruit_for(hero)


class TestMagicfinRelic(unittest.TestCase):
    """BG33_Reward_011 — SoT 入手 1/1 Murloc 并 Discover 酒馆法术教它。"""

    def test_start_of_turn_grants_murloc_and_discovers_spell(self):
        g = make_game(seed=1401)
        a, _ = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)
        before = {d.id: g.spell_pool.available(d.id)
                  for d in get_db().pool_spells()}
        g.pending_choices.clear()

        _fire_reward_sot(g, a)

        toks = _relic_tokens(a)
        self.assertEqual(len(toks), 1)
        token = toks[0]
        self.assertEqual(token.zone, Zone.HAND)
        self.assertEqual((token.atk, token.max_health), (1, 1))
        self.assertEqual(token.race, Race.MURLOC)
        # 非池卡: 不占随从池、不参与三连
        self.assertFalse(get_db().get(_MAGICFIN_APPRENTICE).is_pool_minion)

        choices = _discover_choices(g, a)
        self.assertEqual(len(choices), 1)
        ch = choices[0]
        self.assertIs(ch.owner, a)
        self.assertEqual(len(ch.options), 3)              # Discover 三选一
        self.assertEqual(len(set(ch.options)), 3)
        for cid in ch.options:
            d = get_db().get(cid)
            self.assertTrue(d.is_pool_spell, cid)
            self.assertLessEqual(d.tech_level, a.tavern_tier, cid)
            # 预留语义: 选项生成即占池 1 份
            self.assertEqual(g.spell_pool.available(cid), before[cid] - 1, cid)

    def test_resolve_teaches_spell_and_balances_pool(self):
        """resolve → 教法术; 选中保留占池、未选项回池。"""
        g = make_game(seed=1402)
        a, _ = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)
        before = {d.id: g.spell_pool.available(d.id)
                  for d in get_db().pool_spells()}
        g.pending_choices.clear()

        _fire_reward_sot(g, a)

        token = _relic_tokens(a)[0]
        ch = _discover_choices(g, a)[0]
        pick_index = 1
        pick = ch.options[pick_index]
        others = [c for c in ch.options if c != pick]

        ch.choose(pick_index)

        self.assertEqual(token._taught_spell_id, pick)
        self.assertEqual(g.spell_pool.available(pick), before[pick] - 1)
        for cid in others:
            self.assertEqual(g.spell_pool.available(cid), before[cid])

    def test_stale_pick_releases_reservations_and_raises(self):
        """陈旧/非法选择释放全部预留并 fail-loud（2026-09-13 证伪）。"""
        g = make_game(seed=1404)
        a, _ = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)
        before = {d.id: g.spell_pool.available(d.id)
                  for d in get_db().pool_spells()}
        g.pending_choices.clear()
        _fire_reward_sot(g, a)
        ch = _discover_choices(g, a)[0]
        with self.assertRaises(GameStateError):
            ch.resolve_callback("TOTALLY_STALE")
        for cid in ch.options:                 # 预留全部归还（零泄漏）
            self.assertEqual(g.spell_pool.available(cid), before[cid])

    def test_double_resolve_is_idempotent(self):
        """重复结算不得二次释放未选项（否则每次 +1 幻影副本）。"""
        g = make_game(seed=1405)
        a, _ = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)
        before = {d.id: g.spell_pool.available(d.id)
                  for d in get_db().pool_spells()}
        g.pending_choices.clear()
        _fire_reward_sot(g, a)
        ch = _discover_choices(g, a)[0]
        pick = ch.options[0]
        others = [c for c in ch.options if c != pick]
        ch.choose(0)
        ch.choose(0)                            # 出契约的二次结算
        self.assertEqual(g.spell_pool.available(pick), before[pick] - 1)
        for cid in others:
            self.assertEqual(g.spell_pool.available(cid), before[cid])

    def test_taught_spell_is_cast_by_token(self):
        """teach 端到端: 打出被教 Shiny Ring 的 token → 全体随从增益。"""
        g = make_game(seed=1403)
        a, _ = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)
        g.pending_choices.clear()
        _fire_reward_sot(g, a)
        token = _relic_tokens(a)[0]
        g.pending_choices.clear()
        token._taught_spell_id = SHINY_RING     # teach 数据通道（同 Mycologist）
        friend = put(g, a, PLAIN_MINION, 0)
        base = (friend.atk, friend.max_health)
        d = get_db().get(SHINY_RING)
        self.assertTrue(d.is_pool_spell)

        self.assertTrue(g.play_minion(a, token))

        self.assertEqual((friend.atk, friend.max_health),
                         (base[0] + d.num(0), base[1] + d.num(1)))
        # 学徒本体也吃到（"your minions" 含自身）
        self.assertEqual((token.atk, token.max_health),
                         (1 + d.num(0), 1 + d.num(1)))

    def test_opponent_isolation_and_every_turn(self):
        """对手无奖励不触发; 本人每回合再入手一张（真实回合路径）。"""
        g = make_game(seed=1404)
        a, b = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)

        _sot_turn(g, a, turn=2)
        self.assertEqual(len(_relic_tokens(a)), 1)
        self.assertEqual(len(_discover_choices(g, a)), 1)

        _sot_turn(g, b, turn=2)                   # 对手 SoT: 无奖励
        self.assertEqual(_relic_tokens(b), [])
        self.assertEqual(_discover_choices(g, b), [])
        self.assertEqual(len(_relic_tokens(a)), 1)

        _sot_turn(g, a, turn=3)                   # 第二回合本人
        self.assertEqual(len(_relic_tokens(a)), 2)
        self.assertEqual(len(_discover_choices(g, a)), 1)

    def test_pool_exhausted_still_grants_murloc(self):
        """池耗尽: Murloc 照常入手、本次 Discover 落空（不消耗）。"""
        g = make_game(seed=1405)
        a, _ = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)
        g.pending_choices.clear()
        for d in get_db().pool_spells():
            while g.spell_pool.available(d.id) > 0:
                g.spell_pool.acquire(d.id)
        self.assertEqual(g.spell_pool.total_remaining(), 0)

        _fire_reward_sot(g, a)

        self.assertEqual(len(_relic_tokens(a)), 1)
        self.assertEqual(_discover_choices(g, a), [])

        # 正对照: 放回一张 **本档位** 池法术 → 同一技能确实产出选择
        sid = next(d.id for d in get_db().pool_spells()
                   if d.tech_level <= a.tavern_tier)
        g.spell_pool.release(sid)
        _fire_reward_sot(g, a)
        choices = _discover_choices(g, a)
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].options, [sid])
        self.assertEqual(len(_relic_tokens(a)), 2)
        self.assertEqual(g.spell_pool.available(sid), 0)

    def test_same_seed_deterministic(self):
        def run(seed):
            g = make_game(seed=seed)
            a, _ = g.heroes
            grant_quest_reward(g, a, _MAGICFIN_RELIC)
            g.pending_choices.clear()
            _fire_reward_sot(g, a)
            ch = _discover_choices(g, a)[0]
            return (len(_relic_tokens(a)), tuple(ch.options))

        self.assertEqual(run(77), run(77))
        self.assertEqual(len(run(77)[1]), 3)

    def test_reward_removed_no_further_effect(self):
        """负对照: 奖励实体移除后同一英雄 SoT 不再产出 token/选择。"""
        g = make_game(seed=1406)
        a, b = g.heroes
        grant_quest_reward(g, a, _MAGICFIN_RELIC)
        g.pending_choices.clear()
        _fire_reward_sot(g, a)
        self.assertEqual(len(_relic_tokens(a)), 1)
        self.assertEqual(len(_discover_choices(g, a)), 1)

        a.quest_rewards.clear()
        g.pending_choices.clear()
        _fire_reward_sot(g, a)
        self.assertEqual(len(_relic_tokens(a)), 1)
        self.assertEqual(_discover_choices(g, a), [])
        self.assertEqual(_discover_choices(g, b), [])


# ══════════════════ 台账 / 注册表守卫 ══════════════════


class TestRegistryAndDeferredLedger(unittest.TestCase):
    """@engine-only — 注册表与 DEFERRED 台账结构性守卫（与脚本钩子无关）。"""

    def test_correct_ids_registered(self):
        for rid in IMPLEMENTED:
            self.assertIn(rid, REGISTRY, rid)
            self.assertIsNotNone(get_db().get(rid), rid)
        self.assertEqual(len(IMPLEMENTED), 2)

    def test_deferred_hero_powers_not_registered(self):
        for rid in DEFERRED_HERO_POWERS:
            self.assertIsNotNone(get_db().get(rid), rid)
            self.assertNotIn(rid, REGISTRY, rid)
        self.assertEqual(len(DEFERRED_HERO_POWERS), 15)

    def test_deferred_quest_rewards_not_registered(self):
        for rid in DEFERRED_QUEST_REWARDS:
            self.assertIsNotNone(get_db().get(rid), rid)
            self.assertNotIn(rid, REGISTRY, rid)
        # 2026-09-18 batch_quest_rewards8 迁出 362 → 4 → 3
        self.assertEqual(len(DEFERRED_QUEST_REWARDS), 3)

    def test_deferred_categories_match_scope(self):
        db = get_db()
        for rid in DEFERRED_HERO_POWERS:
            self.assertEqual(db.get(rid).card_type, CardType.HERO_POWER, rid)
        for rid in DEFERRED_QUEST_REWARDS:
            self.assertEqual(db.get(rid).card_type,
                             CardType.BACON_QUEST_REWARD, rid)
        for rid in IMPLEMENTED:
            self.assertEqual(db.get(rid).card_type,
                             CardType.BACON_QUEST_REWARD, rid)

    def test_magicfin_token_data_chain(self):
        d = get_db().get(_MAGICFIN_APPRENTICE)
        self.assertIsNotNone(d)
        self.assertEqual(d.name, "Magicfin Apprentice")
        self.assertEqual((d.atk, d.health), (1, 1))
        self.assertEqual(d.race, Race.MURLOC)
        self.assertFalse(d.is_pool_minion)

    def test_ritual_dagger_text_matches_engine_value(self):
        d = get_db().get(_RITUAL_DAGGER)
        self.assertIn("+5/+5", d.text)
        self.assertIn("Deathrattle", d.text)
        # 数值为文本字面量（CardDef 无模板参数）——SOP §3
        self.assertIsNone(d.num(0))
