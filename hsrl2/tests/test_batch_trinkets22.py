"""批次 trinkets22 行为层测试（12 张注册饰品 + 3 张 DEFERRED 台账守卫,
作业单 2026-09-13）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线; 副本条款用
    `duplicate=True`）
  - 施放: 真实 `game.play_spell`（池法术经 `spell_pool.acquire` 入手，
    施放后引擎自动 release）；定向法术传显式 target
  - 回合: 真实 `game.end_recruit_phase`（EoT / 下回合 SoT）
  - 监听: `game.run_script_hook(t, "end_of_turn" / "start_of_turn")`
  - 吞噬: 真实 `ConsumeMinion(...).do(game)`（含事件广播与回池）

覆盖（SOP §16 空转测试判定法）: 每个行为测试至少含一条**正效果**断言
（正/负对照同方法内），owner 隔离（2 英雄），跨回合语义，落空不消耗
资源，RNG 确定性（同 seed 可复现），副本条款，CardDef.num 双向钉死。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import constants as C
from hsrl2.actions.consume import ConsumeMinion
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 本批 id（CardDB 按名核实——禁止凭记忆写 id）
ESCAPEE_PORTRAIT = "BG36_MagicItem_363"
MALDRAXXUS_DAGGER = "BG36_MagicItem_370"
HONEYCOMB_RING = "BG36_MagicItem_371"
SPHERE_OF_MEMORY = "BG36_MagicItem_372"
BALLER_PORTRAIT = "BG36_MagicItem_390"
DEMONIC_BLOODLETTER = "BG36_MagicItem_800"
CONSUMING_CLAW = "BG36_MagicItem_801"
INDUCTIVE_GYROBLADE = "BG36_MagicItem_810"
INDUCTIVE_GYROBLADE_T = "BG36_MagicItem_810t"
EMERGENCY_GEARBLADE = "BG36_MagicItem_812"
FLIGHTY_PORTRAIT = "BG36_MagicItem_820"
BLOODFURY_SHIELD = "BG36_MagicItem_830"
FELSTEEL_CLEAVER = "BG36_MagicItem_831"

# 测试用既有卡（按名核实）
FIRE_BALLER = "BG31_816"
SNOW_BALLER = "BG31_818"
FLIGHTY_SCOUT = "BG32_330"
SATELLITE = "BG31_171t"
REPAIR_JOB = "BG36_624"
INSATIABLE_URZUL = "BG21_004"      # Demon（race=DEMON），仅 CARD_PLAYED 监听
TAD = "BG22_202"                   # Murloc（race=MURLOC），仅 on_sell
SLY_RAPTOR = "BG25_806"            # Beast（race=BEAST），仅 deathrattle
ROT_HIDE_GNOLL = "BG25_013"        # Undead（race=UNDEAD），无钩子
AUTO_ASSEMBLER = "BG32_172"        # Mech（race=MECH），纯关键词
SIRENS_SONG = "BG27_514t"          # Spellcraft 法术: 以**酒馆随从**为定向目标
BANANA = "BG28_897"                # 池法术: Give a minion +{0}/+{1}（定向）
ARMOR_STASH = "BG28_500"           # 池法术: 无目标（Set your Armor to 5）
BLOOD_GEM = "BG20_GEM"             # 血宝石（非池法术: 不广播 tavern_spell_cast）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 920) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str, duplicate: bool = False):
    e = game.grant_trinket(hero, tid, duplicate=duplicate)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def tavern_put(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def play_pool_spell(game: Game, hero: Hero, card_id: str, target=None):
    """真实"购买并施放"池法术: acquire → 入手 → play_spell（施放后回池）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    s.zone = Zone.HAND
    hero.hand.append(s)
    assert game.play_spell(hero, s, target=target)
    return s


def hand_ids(hero: Hero) -> list:
    return [c.card_id for c in hero.hand]


def choices_of(game: Game, kind: str) -> list:
    return [c for c in game.pending_choices if c.kind == kind]


def num_of(card_id: str, index: int) -> int:
    """CardDef 模板参数（卡面 {0}/{1} 占位符的权威）。"""
    return get_db().get(card_id).num(index)


def atk_of(card_id: str) -> int:
    """CardDef 攻击（随从: atk 字段——随从无 {0} 占位符）。"""
    return get_db().get(card_id).atk


def hp_of(card_id: str) -> int:
    """CardDef 生命（随从: health 字段——属性值快照口径）。"""
    return get_db().get(card_id).health


# ══════════════ BG36_MagicItem_363 Escapee Portrait ══════════════


class TestEscapeePortrait(unittest.TestCase):
    """Get a Golden Enterprising Escapee. Your Lockboxes open {0} sooner."""

    def test_bind_grants_golden_escapee(self):
        g = make_game(2201)
        a, b = g.heroes
        gd = g.trinket_related_card(ESCAPEE_PORTRAIT)
        self.assertTrue(gd.is_golden_def)
        bind(g, a, ESCAPEE_PORTRAIT)
        got = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(got), 1)
        m = got[0]
        self.assertEqual(m.card_id, gd.id)
        self.assertTrue(m.is_golden)                          # GOLDEN tag
        self.assertEqual(m.get(GameTag.TRIPLE_BASE_CARD_ID), "BG36_523")
        self.assertEqual((m.atk, m.max_health), (gd.atk, gd.health))
        self.assertEqual([c.card_id for c in b.hand], [])     # owner 隔离

    def test_lockbox_opens_sooner(self):
        g = make_game(2202)
        a, b = g.heroes
        step = num_of(ESCAPEE_PORTRAIT, 0)
        base = num_of(C.LOCKBOX_CARD_ID, 0)
        self.assertIsNotNone(step)
        bind(g, a, ESCAPEE_PORTRAIT)
        lock = g.create_spell(C.LOCKBOX_CARD_ID, controller=a)
        g.pending_hand_add(a, lock)
        self.assertEqual(lock.get(GameTag.LOCKBOX_TURNS_LEFT),
                         base - step)                          # 正效果
        # 正对照: 无饰品 → 全量倒计时
        g2 = make_game(2202)
        a2 = g2.heroes[0]
        lock2 = g2.create_spell(C.LOCKBOX_CARD_ID, controller=a2)
        g2.pending_hand_add(a2, lock2)
        self.assertEqual(lock2.get(GameTag.LOCKBOX_TURNS_LEFT), base)

    def test_pre_existing_lockbox_not_retroactive(self):
        """已有 Lockbox 不被追溯（文本只修饰**此后**入手者）。"""
        g = make_game(2207)
        a, b = g.heroes
        step = num_of(ESCAPEE_PORTRAIT, 0)
        base = num_of(C.LOCKBOX_CARD_ID, 0)
        lock = g.create_spell(C.LOCKBOX_CARD_ID, controller=a)
        g.pending_hand_add(a, lock)
        bind(g, a, ESCAPEE_PORTRAIT)
        self.assertEqual(lock.get(GameTag.LOCKBOX_TURNS_LEFT), base)
        a.hand.remove(lock)                                     # 清掉旧 Lockbox
        lock2 = g.create_spell(C.LOCKBOX_CARD_ID, controller=a)
        g.pending_hand_add(a, lock2)
        self.assertEqual(lock2.get(GameTag.LOCKBOX_TURNS_LEFT),
                         base - step)                           # 正对照

    def test_opponent_lockbox_not_shortened(self):
        g = make_game(2203)
        a, b = g.heroes
        step = num_of(ESCAPEE_PORTRAIT, 0)
        base = num_of(C.LOCKBOX_CARD_ID, 0)
        bind(g, a, ESCAPEE_PORTRAIT)
        lock_b = g.create_spell(C.LOCKBOX_CARD_ID, controller=b)
        g.pending_hand_add(b, lock_b)
        self.assertEqual(lock_b.get(GameTag.LOCKBOX_TURNS_LEFT), base)
        lock_a = g.create_spell(C.LOCKBOX_CARD_ID, controller=a)
        g.pending_hand_add(a, lock_a)
        self.assertEqual(lock_a.get(GameTag.LOCKBOX_TURNS_LEFT),
                         base - step)                          # 本人照常

    def test_two_copies_stack(self):
        g = make_game(2204)
        a, b = g.heroes
        step = num_of(ESCAPEE_PORTRAIT, 0)
        base = num_of(C.LOCKBOX_CARD_ID, 0)
        bind(g, a, ESCAPEE_PORTRAIT)
        bind(g, a, ESCAPEE_PORTRAIT, duplicate=True)
        self.assertEqual(len(a.trinkets), 2)
        lock = g.create_spell(C.LOCKBOX_CARD_ID, controller=a)
        g.pending_hand_add(a, lock)
        self.assertEqual(lock.get(GameTag.LOCKBOX_TURNS_LEFT),
                         base - 2 * step)

    def test_lockbox_zero_countdown_opens(self):
        """减到 0 → 立即开启（`open_lockbox_early` 契约）。"""
        g = make_game(2205)
        a, b = g.heroes
        bind(g, a, ESCAPEE_PORTRAIT)
        lock = g.create_spell(C.LOCKBOX_CARD_ID, controller=a)
        lock.set(GameTag.LOCKBOX_TURNS_LEFT, 1)
        g.pending_hand_add(a, lock)
        self.assertNotIn(lock, a.hand)                         # 已开启
        self.assertTrue(any(isinstance(c, Minion) and c.is_golden
                            for c in a.hand))                  # 产物为金


# ══════════════ BG36_MagicItem_370 Maldraxxus Dagger ══════════════


class TestMaldraxxusDagger(unittest.TestCase):
    """Discover a plain copy of a warband minion with a Dark Gift; repeat."""

    def _choices(self, g: Game) -> list:
        return choices_of(g, "dark_gift")

    def test_bind_offers_warband_copies(self):
        g = make_game(2210)
        a, b = g.heroes
        put(g, a, ROT_HIDE_GNOLL)
        put(g, a, TAD)
        self.assertEqual(self._choices(g), [])
        bind(g, a, MALDRAXXUS_DAGGER)
        ch = self._choices(g)
        self.assertEqual(len(ch), 1)
        self.assertIs(ch[0].owner, a)
        cands = {cid for cid, _gift in ch[0].options}
        self.assertEqual(cands, {ROT_HIDE_GNOLL, TAD})
        gifts = [gid for _cid, gid in ch[0].options]
        self.assertEqual(len(gifts), len(set(gifts)))          # 互不相同发牌

    def test_pick_delivers_plain_copy_with_gift(self):
        g = make_game(2211)
        a, b = g.heroes
        put(g, a, ROT_HIDE_GNOLL)
        bind(g, a, MALDRAXXUS_DAGGER)
        ch = self._choices(g).pop(0)
        cid, gift = ch.options[0]
        ch.choose(0)
        got = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(got), 1)
        m = got[0]
        self.assertEqual(m.card_id, cid)
        self.assertEqual(m.get(GameTag.DARK_GIFT), gift)
        self.assertFalse(m.is_golden)
        self.assertEqual(m.buffs, [])                          # plain（无附魔）

    def test_golden_warband_minion_copied_as_plain_base(self):
        g = make_game(2212)
        a, b = g.heroes
        put(g, a, TAD, golden=True)
        bind(g, a, MALDRAXXUS_DAGGER)
        ch = self._choices(g).pop(0)
        self.assertEqual([cid for cid, _ in ch.options], [TAD])
        ch.choose(0)
        m = [c for c in a.hand if isinstance(c, Minion)][0]
        self.assertEqual(m.card_id, TAD)
        self.assertFalse(m.is_golden)                          # plain = 非金

    def test_empty_board_whiffs_then_positive_control(self):
        g = make_game(2213)
        a, b = g.heroes
        t = bind(g, a, MALDRAXXUS_DAGGER)
        self.assertEqual(self._choices(g), [])
        self.assertEqual(len(a.hand), 0)
        put(g, a, TAD)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(self._choices(g)), 1)              # 正对照

    def test_opponent_board_not_in_candidates(self):
        g = make_game(2214)
        a, b = g.heroes
        put(g, b, ROT_HIDE_GNOLL)
        put(g, b, TAD)
        bind(g, a, MALDRAXXUS_DAGGER)
        self.assertEqual(self._choices(g), [])                  # 对手不计入
        put(g, a, SLY_RAPTOR)
        g.run_script_hook(a.trinkets[0], "start_of_turn")
        ch = self._choices(g)
        self.assertEqual(len(ch), 1)
        self.assertEqual({cid for cid, _ in ch[0].options}, {SLY_RAPTOR})

    def test_no_pool_consumption(self):
        g = make_game(2215)
        a, b = g.heroes
        put(g, a, TAD)
        before = g.minion_pool.available(TAD)
        bind(g, a, MALDRAXXUS_DAGGER)
        ch = self._choices(g).pop(0)
        ch.choose(0)
        self.assertEqual(g.minion_pool.available(TAD), before)  # 副本不占池

    def test_real_turn_advance_repeats(self):
        g = make_game(2216)
        a, b = g.heroes
        put(g, a, TAD)
        bind(g, a, MALDRAXXUS_DAGGER)
        self.assertEqual(len(self._choices(g)), 1)
        for ch in list(self._choices(g)):
            g.pending_choices.remove(ch)
        g.end_recruit_phase()
        self.assertEqual(len(self._choices(g)), 1)              # 每回合重复

    def test_seed_reproducible_options(self):
        def seq(seed):
            g = make_game(seed)
            a = g.heroes[0]
            put(g, a, TAD)
            put(g, a, ROT_HIDE_GNOLL)
            put(g, a, SLY_RAPTOR)
            bind(g, a, MALDRAXXUS_DAGGER)
            ch = choices_of(g, "dark_gift")[0]
            return [(cid, gid) for cid, gid in ch.options]

        s1, s2 = seq(2217), seq(2217)
        self.assertEqual(len(s1), 3)
        self.assertEqual(s1, s2)


# ══════════════ BG36_MagicItem_371 Honeycomb Ring ══════════════


class TestHoneycombRing(unittest.TestCase):
    """Tavern spells give an extra +{0}/+{1}; improve this turn only."""

    def _extra(self, hero):
        return (hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0),
                hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0))

    def test_bind_sets_base_extra(self):
        g = make_game(2220)
        a, b = g.heroes
        bind(g, a, HONEYCOMB_RING)
        self.assertEqual(self._extra(a),
                         (num_of(HONEYCOMB_RING, 0),
                          num_of(HONEYCOMB_RING, 1)))
        self.assertEqual(self._extra(b), (0, 0))                # owner 隔离

    def test_spell_on_minion_buffs_and_improves(self):
        g = make_game(2221)
        a, b = g.heroes
        target = put(g, a, TAD)
        bind(g, a, HONEYCOMB_RING)
        atk0, hp0 = num_of(BANANA, 0), num_of(BANANA, 1)
        step_a = num_of(HONEYCOMB_RING, 0)                     # CardDef 权威
        step_h = num_of(HONEYCOMB_RING, 1)
        # 第 1 次施放: 自身的 improve 在**之后**结算 → 只吃基准 extra
        play_pool_spell(g, a, BANANA, target=target)
        self.assertEqual((target.atk, target.max_health),
                         (atk_of(TAD) + atk0 + step_a,
                          hp_of(TAD) + hp0 + step_h))
        self.assertEqual(self._extra(a), (2 * step_a, 2 * step_h))
        # 第 2 次施放: 吃「基准 + 本回合已 improve」的 extra
        target2 = put(g, a, SLY_RAPTOR)
        play_pool_spell(g, a, BANANA, target=target2)
        self.assertEqual((target2.atk, target2.max_health),
                         (atk_of(SLY_RAPTOR) + atk0 + 2 * step_a,
                          hp_of(SLY_RAPTOR) + hp0 + 2 * step_h))

    def test_spell_without_minion_target_no_improve(self):
        g = make_game(2222)
        a, b = g.heroes
        put(g, a, TAD)
        bind(g, a, HONEYCOMB_RING)
        before = self._extra(a)
        play_pool_spell(g, a, ARMOR_STASH)                      # 无目标
        self.assertEqual(self._extra(a), before)
        play_pool_spell(g, a, BANANA, target=a.board[0])
        self.assertNotEqual(self._extra(a), before)             # 正对照

    def test_temporary_part_expires_next_turn(self):
        g = make_game(2223)
        a, b = g.heroes
        target = put(g, a, TAD)
        t = bind(g, a, HONEYCOMB_RING)
        base = self._extra(a)
        play_pool_spell(g, a, BANANA, target=target)
        self.assertGreater(self._extra(a)[0], base[0])
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(self._extra(a), base)                  # 临时面清除
        self.assertEqual(self._extra(b), (0, 0))

    def test_opponent_cast_not_counted(self):
        g = make_game(2224)
        a, b = g.heroes
        bind(g, a, HONEYCOMB_RING)
        tgt_b = put(g, b, TAD)
        before = self._extra(a)
        play_pool_spell(g, b, BANANA, target=tgt_b)
        self.assertEqual(self._extra(a), before)
        self.assertEqual(self._extra(b), (0, 0))
        play_pool_spell(g, a, BANANA, target=put(g, a, TAD))
        self.assertNotEqual(self._extra(a), before)             # 正对照

    def test_two_copies_stack(self):
        g = make_game(2225)
        a, b = g.heroes
        bind(g, a, HONEYCOMB_RING)
        bind(g, a, HONEYCOMB_RING, duplicate=True)
        step_a, step_h = num_of(HONEYCOMB_RING, 0), \
            num_of(HONEYCOMB_RING, 1)
        self.assertEqual(self._extra(a), (2 * step_a, 2 * step_h))
        play_pool_spell(g, a, BANANA, target=put(g, a, TAD))
        self.assertEqual(self._extra(a), (4 * step_a, 4 * step_h))

    def test_real_turn_advance_clears_temporary(self):
        g = make_game(2226)
        a, b = g.heroes
        target = put(g, a, TAD)
        bind(g, a, HONEYCOMB_RING)
        base = self._extra(a)
        play_pool_spell(g, a, BANANA, target=target)
        self.assertNotEqual(self._extra(a), base)
        g.end_recruit_phase()
        self.assertGreaterEqual(g.turn, 2)
        self.assertEqual(self._extra(a), base)


# ══════════════ BG36_MagicItem_372 Sphere of Memory ══════════════


class TestSphereOfMemory(unittest.TestCase):
    """EoT: get {0} copies of the last Tavern spell you cast."""

    def test_eot_gets_copies_of_last_spell(self):
        g = make_game(2230)
        a, b = g.heroes
        n = num_of(SPHERE_OF_MEMORY, 0)
        t = bind(g, a, SPHERE_OF_MEMORY)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(hand_ids(a), [])
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(hand_ids(a), [ARMOR_STASH] * n)

    def test_no_cast_whiffs_then_positive_control(self):
        g = make_game(2231)
        a, b = g.heroes
        t = bind(g, a, SPHERE_OF_MEMORY)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(hand_ids(a), [])                       # 落空
        play_pool_spell(g, a, ARMOR_STASH)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(len(hand_ids(a)), num_of(SPHERE_OF_MEMORY, 0))

    def test_pool_untouched_by_copies(self):
        g = make_game(2232)
        a, b = g.heroes
        t = bind(g, a, SPHERE_OF_MEMORY)
        play_pool_spell(g, a, ARMOR_STASH)
        cap = g.spell_pool.available(ARMOR_STASH)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(len(hand_ids(a)), num_of(SPHERE_OF_MEMORY, 0))
        self.assertEqual(g.spell_pool.available(ARMOR_STASH), cap)

    def test_opponent_cast_not_recorded(self):
        g = make_game(2233)
        a, b = g.heroes
        t = bind(g, a, SPHERE_OF_MEMORY)
        play_pool_spell(g, b, ARMOR_STASH)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(hand_ids(a), [])                       # 对手施法不记
        play_pool_spell(g, a, ARMOR_STASH)
        g.run_script_hook(t, "end_of_turn")
        self.assertNotEqual(hand_ids(a), [])                    # 正对照

    def test_last_cast_wins(self):
        g = make_game(2234)
        a, b = g.heroes
        t = bind(g, a, SPHERE_OF_MEMORY)
        play_pool_spell(g, a, ARMOR_STASH)
        play_pool_spell(g, a, BANANA, target=put(g, a, TAD))
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(set(hand_ids(a)), {BANANA})

    def test_real_turn_advance_triggers_eot(self):
        g = make_game(2235)
        a, b = g.heroes
        bind(g, a, SPHERE_OF_MEMORY)
        play_pool_spell(g, a, ARMOR_STASH)
        g.end_recruit_phase()
        self.assertEqual(hand_ids(a).count(ARMOR_STASH),
                         num_of(SPHERE_OF_MEMORY, 0))

    def test_two_copies_each_grant(self):
        g = make_game(2236)
        a, b = g.heroes
        bind(g, a, SPHERE_OF_MEMORY)
        play_pool_spell(g, a, ARMOR_STASH)
        bind(g, a, SPHERE_OF_MEMORY, duplicate=True)
        for t in list(a.trinkets):
            g.run_script_hook(t, "end_of_turn")
        self.assertEqual(hand_ids(a).count(ARMOR_STASH),
                         2 * num_of(SPHERE_OF_MEMORY, 0))


# ══════════════ BG36_MagicItem_390 Baller Portrait ══════════════


class TestBallerPortrait(unittest.TestCase):
    """Get a Fire Baller or a Snow Baller; repeat at the start of each turn."""

    def _drain(self, g: Game, card_id: str) -> int:
        n = 0
        while g.minion_pool.acquire(card_id):
            n += 1
        return n

    def test_bind_grants_one_baller(self):
        g = make_game(2240)
        a, b = g.heroes
        before = {FIRE_BALLER: g.minion_pool.available(FIRE_BALLER),
                  SNOW_BALLER: g.minion_pool.available(SNOW_BALLER)}
        bind(g, a, BALLER_PORTRAIT)
        ids = hand_ids(a)
        self.assertEqual(len(ids), 1)
        self.assertIn(ids[0], (FIRE_BALLER, SNOW_BALLER))
        self.assertEqual(g.minion_pool.available(ids[0]),
                         before[ids[0]] - 1)                     # 池随从占池
        self.assertEqual(hand_ids(b), [])

    def test_start_of_turn_and_real_turn_repeat(self):
        g = make_game(2241)
        a, b = g.heroes
        t = bind(g, a, BALLER_PORTRAIT)
        self.assertEqual(len(hand_ids(a)), 1)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(hand_ids(a)), 2)
        g.end_recruit_phase()
        self.assertEqual(len(hand_ids(a)), 3)                   # 真实换回合

    def test_both_pools_empty_whiffs_then_positive_control(self):
        g = make_game(2242)
        a, b = g.heroes
        self._drain(g, FIRE_BALLER)
        self._drain(g, SNOW_BALLER)
        t = bind(g, a, BALLER_PORTRAIT)
        self.assertEqual(hand_ids(a), [])                       # 落空
        self.assertTrue(g.minion_pool.ensure_available(FIRE_BALLER))
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(hand_ids(a), [FIRE_BALLER])            # 正对照

    def test_opponent_hand_untouched(self):
        g = make_game(2243)
        a, b = g.heroes
        bind(g, a, BALLER_PORTRAIT)
        self.assertEqual(hand_ids(b), [])
        self.assertEqual(len(hand_ids(a)), 1)

    def test_seed_reproducible(self):
        def pick(seed):
            g = make_game(seed)
            a = g.heroes[0]
            bind(g, a, BALLER_PORTRAIT)
            return hand_ids(a)[0]

        self.assertEqual(pick(2244), pick(2244))

    def test_two_copies_each_grant(self):
        g = make_game(2245)
        a, b = g.heroes
        bind(g, a, BALLER_PORTRAIT)
        bind(g, a, BALLER_PORTRAIT, duplicate=True)
        self.assertEqual(len(hand_ids(a)), 2)


# ══════════════ BG36_MagicItem_800 Demonic Bloodletter ══════════════


class TestDemonicBloodletter(unittest.TestCase):
    """Cast a Tavern spell → give minions in the Tavern +{0}/+{1} this game."""

    def test_cast_buffs_tavern_now_and_persists(self):
        g = make_game(2250)
        a, b = g.heroes
        m = tavern_put(g, a, TAD)
        da, dh = num_of(DEMONIC_BLOODLETTER, 0), \
            num_of(DEMONIC_BLOODLETTER, 1)
        bind(g, a, DEMONIC_BLOODLETTER)
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 0)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual((m.atk, m.max_health),
                         (atk_of(TAD) + da, hp_of(TAD) + dh))
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 1)
        # 持久面: 刷新后新入馆随从自动继承（"this game"）
        g.refresh_tavern(a)
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(minions)
        for e in minions:
            d = get_db().get(e.card_id)
            self.assertEqual((e.atk, e.max_health),
                             (d.atk + da, d.health + dh), e.card_id)

    def test_without_trinket_refresh_has_no_bonus(self):
        g = make_game(2251)
        a, b = g.heroes
        g.refresh_tavern(a)
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(minions)
        for e in minions:
            d = get_db().get(e.card_id)
            self.assertEqual((e.atk, e.max_health), (d.atk, d.health))
        # 正对照: 绑定 + 施放后同一次刷新 → 每个随从都带 +num
        da, dh = num_of(DEMONIC_BLOODLETTER, 0), \
            num_of(DEMONIC_BLOODLETTER, 1)
        g2 = make_game(2251)
        a2 = g2.heroes[0]
        bind(g2, a2, DEMONIC_BLOODLETTER)
        play_pool_spell(g2, a2, ARMOR_STASH)
        g2.refresh_tavern(a2)
        minions2 = [e for e in a2.tavern if isinstance(e, Minion)]
        self.assertTrue(minions2)
        for e in minions2:
            d = get_db().get(e.card_id)
            self.assertEqual((e.atk, e.max_health),
                             (d.atk + da, d.health + dh))

    def test_opponent_isolation(self):
        g = make_game(2252)
        a, b = g.heroes
        m_b = tavern_put(g, b, TAD)
        bind(g, a, DEMONIC_BLOODLETTER)
        play_pool_spell(g, b, ARMOR_STASH)
        self.assertEqual((m_b.atk, m_b.max_health),
                         (atk_of(TAD), hp_of(TAD)))
        self.assertEqual(len(getattr(b, "tavern_buffs", [])), 0)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 1)                # 正对照

    def test_non_pool_spell_no_trigger(self):
        g = make_game(2253)
        a, b = g.heroes
        bind(g, a, DEMONIC_BLOODLETTER)
        gem = g.create_spell(BLOOD_GEM, controller=a)
        a.hand.append(gem)
        gem.zone = Zone.HAND
        g.play_spell(a, gem, target=put(g, a, TAD))             # 非池法术
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 0)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 1)                # 正对照

    def test_two_copies_stack(self):
        g = make_game(2254)
        a, b = g.heroes
        m = tavern_put(g, a, TAD)
        da, dh = num_of(DEMONIC_BLOODLETTER, 0), \
            num_of(DEMONIC_BLOODLETTER, 1)
        bind(g, a, DEMONIC_BLOODLETTER)
        bind(g, a, DEMONIC_BLOODLETTER, duplicate=True)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual((m.atk, m.max_health),
                         (atk_of(TAD) + 2 * da,
                          hp_of(TAD) + 2 * dh))
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 2)


# ══════════════ BG36_MagicItem_801 Consuming Claw ══════════════


class TestConsumingClaw(unittest.TestCase):
    """Friendly Demon consumes → also gains victim's Bonus Keywords and +{0}/+{1}."""

    def _setup(self, seed, with_trinket=True):
        g = make_game(seed)
        a, b = g.heroes
        demon = put(g, a, INSATIABLE_URZUL)
        victim = tavern_put(g, a, TAD)
        victim.set(GameTag.DIVINE_SHIELD, True)
        victim.set(GameTag.WINDFURY, True)
        if with_trinket:
            bind(g, a, CONSUMING_CLAW)
        return g, a, b, demon, victim

    def test_consume_grants_keywords_and_stats(self):
        g, a, b, demon, victim = self._setup(2260)
        da, dh = num_of(CONSUMING_CLAW, 0), num_of(CONSUMING_CLAW, 1)
        base_atk, base_hp = demon.atk, demon.max_health
        ConsumeMinion(demon, victim).do(g)
        self.assertTrue(demon.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(demon.has(GameTag.WINDFURY))
        self.assertEqual(demon.atk,
                         base_atk + atk_of(TAD) + da)
        self.assertEqual(demon.max_health,
                         base_hp + hp_of(TAD) + dh)

    def test_without_trinket_only_stats(self):
        g, a, b, demon, victim = self._setup(2261, with_trinket=False)
        base_atk = demon.atk
        ConsumeMinion(demon, victim).do(g)
        self.assertFalse(demon.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(demon.has(GameTag.WINDFURY))
        self.assertEqual(demon.atk, base_atk + atk_of(TAD))
        # 正对照: 同 setup + 饰品 → 关键词与 +num 都到位
        g2, a2, b2, demon2, victim2 = self._setup(2261, with_trinket=True)
        dbase = demon2.atk
        ConsumeMinion(demon2, victim2).do(g2)
        self.assertTrue(demon2.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(demon2.atk, dbase + atk_of(TAD)
                         + num_of(CONSUMING_CLAW, 0))

    def test_victim_without_keywords_only_stats(self):
        g = make_game(2262)
        a, b = g.heroes
        demon = put(g, a, INSATIABLE_URZUL)
        victim = tavern_put(g, a, ROT_HIDE_GNOLL)               # 无该集关键词
        bind(g, a, CONSUMING_CLAW)
        base_atk = demon.atk
        ConsumeMinion(demon, victim).do(g)
        self.assertEqual(demon.atk,
                         base_atk + atk_of(ROT_HIDE_GNOLL)
                         + num_of(CONSUMING_CLAW, 0))
        for tag in (GameTag.DIVINE_SHIELD, GameTag.WINDFURY):
            self.assertFalse(demon.has(tag))

    def test_non_demon_consumer_no_trigger(self):
        g = make_game(2263)
        a, b = g.heroes
        consumer = put(g, a, ROT_HIDE_GNOLL)                    # 非 Demon
        victim = tavern_put(g, a, TAD)
        victim.set(GameTag.DIVINE_SHIELD, True)
        bind(g, a, CONSUMING_CLAW)
        base_atk = consumer.atk
        ConsumeMinion(consumer, victim).do(g)
        self.assertFalse(consumer.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(consumer.atk,
                         base_atk + atk_of(TAD))             # 只有基础吞噬
        # 正对照: 同 setup 换成 Demon 消费者 → 关键词 + num 都到位
        demon = put(g, a, INSATIABLE_URZUL)
        victim2 = tavern_put(g, a, TAD)
        victim2.set(GameTag.DIVINE_SHIELD, True)
        dbase = demon.atk
        ConsumeMinion(demon, victim2).do(g)
        self.assertTrue(demon.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(demon.atk, dbase + atk_of(TAD)
                         + num_of(CONSUMING_CLAW, 0))

    def test_opponent_demon_no_trigger(self):
        g = make_game(2264)
        a, b = g.heroes
        demon_b = put(g, b, INSATIABLE_URZUL)
        victim_b = tavern_put(g, b, TAD)
        victim_b.set(GameTag.DIVINE_SHIELD, True)
        bind(g, a, CONSUMING_CLAW)
        base_atk = demon_b.atk
        ConsumeMinion(demon_b, victim_b).do(g)
        self.assertFalse(demon_b.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(demon_b.atk, base_atk + atk_of(TAD))
        # 正对照: 本人 Demon 吞噬同样受害者 → 关键词 + num 到位
        demon_a = put(g, a, INSATIABLE_URZUL)
        victim_a = tavern_put(g, a, TAD)
        victim_a.set(GameTag.DIVINE_SHIELD, True)
        abase = demon_a.atk
        ConsumeMinion(demon_a, victim_a).do(g)
        self.assertTrue(demon_a.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(demon_a.atk, abase + atk_of(TAD)
                         + num_of(CONSUMING_CLAW, 0))

    def test_two_copies_stack(self):
        g, a, b, demon, victim = self._setup(2265)
        bind(g, a, CONSUMING_CLAW, duplicate=True)
        da, dh = num_of(CONSUMING_CLAW, 0), num_of(CONSUMING_CLAW, 1)
        base_atk, base_hp = demon.atk, demon.max_health
        ConsumeMinion(demon, victim).do(g)
        self.assertEqual(demon.atk,
                         base_atk + atk_of(TAD) + 2 * da)
        self.assertEqual(demon.max_health,
                         base_hp + hp_of(TAD) + 2 * dh)


# ══════════════ BG36_MagicItem_810 Inductive Gyroblade ══════════════


class TestInductiveGyroblade(unittest.TestCase):
    """EoT: get a {0}/{1} Magnetic Satellite, improved per Tavern spell
    cast this turn."""

    def _satellites(self, hero):
        return [c for c in hero.hand
                if isinstance(c, Minion) and c.card_id == SATELLITE]

    def test_zero_spells_gives_printed_size(self):
        g = make_game(2270)
        a, b = g.heroes
        t = bind(g, a, INDUCTIVE_GYROBLADE)
        g.run_script_hook(t, "end_of_turn")
        sats = self._satellites(a)
        self.assertEqual(len(sats), 1)
        self.assertEqual((sats[0].atk, sats[0].max_health),
                         (num_of(INDUCTIVE_GYROBLADE, 0),
                          num_of(INDUCTIVE_GYROBLADE, 1)))
        self.assertTrue(sats[0].has(GameTag.MAGNETIC))

    def test_each_tavern_spell_improves(self):
        g = make_game(2271)
        a, b = g.heroes
        t = bind(g, a, INDUCTIVE_GYROBLADE)
        n = 3
        for _ in range(n):
            play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN), n)
        g.run_script_hook(t, "end_of_turn")
        sat = self._satellites(a)[0]
        self.assertEqual((sat.atk, sat.max_health),
                         (num_of(INDUCTIVE_GYROBLADE, 0) * (1 + n),
                          num_of(INDUCTIVE_GYROBLADE, 1) * (1 + n)))

    def test_non_pool_spell_does_not_improve(self):
        g = make_game(2272)
        a, b = g.heroes
        t = bind(g, a, INDUCTIVE_GYROBLADE)
        gem = g.create_spell(BLOOD_GEM, controller=a)
        a.hand.append(gem)
        gem.zone = Zone.HAND
        g.play_spell(a, gem, target=put(g, a, TAD))             # 血宝石非池
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0), 0)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(self._satellites(a)[0].atk,
                         num_of(INDUCTIVE_GYROBLADE, 0))        # 基础尺寸

    def test_token_does_not_touch_pool(self):
        g = make_game(2273)
        a, b = g.heroes
        before = g.minion_pool.total_remaining()
        t = bind(g, a, INDUCTIVE_GYROBLADE)
        g.run_script_hook(t, "end_of_turn")
        sats = self._satellites(a)
        self.assertEqual(len(sats), 1)                          # 正效果
        self.assertEqual(sats[0].atk, num_of(INDUCTIVE_GYROBLADE, 0))
        self.assertEqual(g.minion_pool.total_remaining(), before)

    def test_real_turn_advance_and_counter_reset(self):
        g = make_game(2274)
        a, b = g.heroes
        bind(g, a, INDUCTIVE_GYROBLADE)
        play_pool_spell(g, a, ARMOR_STASH)
        play_pool_spell(g, a, ARMOR_STASH)
        g.end_recruit_phase()                                   # 本回合 EoT
        improved = self._satellites(a)[0]
        self.assertEqual(improved.atk,
                         num_of(INDUCTIVE_GYROBLADE, 0) * 3)
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0), 0)
        g.end_recruit_phase()                                   # 下回合无施放
        newest = self._satellites(a)[-1]
        self.assertEqual(newest.atk, num_of(INDUCTIVE_GYROBLADE, 0))

    def test_upgrade_variant_uses_own_nums(self):
        g = make_game(2275)
        a, b = g.heroes
        t = bind(g, a, INDUCTIVE_GYROBLADE_T)
        g.run_script_hook(t, "end_of_turn")
        sat = self._satellites(a)[0]
        self.assertEqual((sat.atk, sat.max_health),
                         (num_of(INDUCTIVE_GYROBLADE_T, 0),
                          num_of(INDUCTIVE_GYROBLADE_T, 1)))
        self.assertEqual(num_of(INDUCTIVE_GYROBLADE_T, 0), 12)   # 37.0: 8→12

    def test_two_copies_each_grant(self):
        g = make_game(2276)
        a, b = g.heroes
        bind(g, a, INDUCTIVE_GYROBLADE)
        bind(g, a, INDUCTIVE_GYROBLADE, duplicate=True)
        for t in list(a.trinkets):
            g.run_script_hook(t, "end_of_turn")
        self.assertEqual(len(self._satellites(a)), 2)


# ══════════════ BG36_MagicItem_812 Emergency Gearblade ══════════════


class TestEmergencyGearblade(unittest.TestCase):
    """EoT: cast Repair Job on your left-most Mech."""

    def test_eot_buffs_leftmost_mech_only(self):
        g = make_game(2280)
        a, b = g.heroes
        beast = put(g, a, SLY_RAPTOR)
        m1 = put(g, a, AUTO_ASSEMBLER)
        m2 = put(g, a, AUTO_ASSEMBLER)
        base = {m: (m.atk, m.max_health) for m in (beast, m1, m2)}
        t = bind(g, a, EMERGENCY_GEARBLADE)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual((m1.atk, m1.max_health),
                         (base[m1][0] + num_of(REPAIR_JOB, 0),
                          base[m1][1] + num_of(REPAIR_JOB, 1)))
        self.assertEqual((m2.atk, m2.max_health), base[m2])
        self.assertEqual((beast.atk, beast.max_health), base[beast])

    def test_without_trinket_no_buff(self):
        g = make_game(2281)
        a, b = g.heroes
        m1 = put(g, a, AUTO_ASSEMBLER)
        self.assertEqual(m1.atk, atk_of(AUTO_ASSEMBLER))
        # 正对照: 同 setup 绑定饰品 → 效果发生
        g2 = make_game(2281)
        a2 = g2.heroes[0]
        m = put(g2, a2, AUTO_ASSEMBLER)
        t = bind(g2, a2, EMERGENCY_GEARBLADE)
        g2.run_script_hook(t, "end_of_turn")
        self.assertEqual(m.atk, atk_of(AUTO_ASSEMBLER)
                         + num_of(REPAIR_JOB, 0))

    def test_no_mech_whiffs(self):
        g = make_game(2282)
        a, b = g.heroes
        beast = put(g, a, SLY_RAPTOR)
        t = bind(g, a, EMERGENCY_GEARBLADE)
        before = (beast.atk, beast.max_health)
        gold0, hand0 = a.gold, len(a.hand)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual((beast.atk, beast.max_health), before)
        self.assertEqual((a.gold, len(a.hand)), (gold0, hand0))
        put(g, a, AUTO_ASSEMBLER)
        g.run_script_hook(t, "end_of_turn")
        mech = [m for m in a.board if m.race in (Race.MECH, Race.ALL)][0]
        self.assertGreater(mech.atk, atk_of(AUTO_ASSEMBLER))  # 正对照

    def test_effect_cast_touches_no_pool_or_gold(self):
        g = make_game(2283)
        a, b = g.heroes
        put(g, a, AUTO_ASSEMBLER)
        t = bind(g, a, EMERGENCY_GEARBLADE)
        cap = g.spell_pool.available(REPAIR_JOB)
        gold0, hand0 = a.gold, len(a.hand)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(g.spell_pool.available(REPAIR_JOB), cap)
        self.assertEqual((a.gold, len(a.hand)), (gold0, hand0))
        self.assertGreater(a.board[0].atk, atk_of(AUTO_ASSEMBLER))  # 正效果

    def test_real_turn_advance(self):
        g = make_game(2284)
        a, b = g.heroes
        m = put(g, a, AUTO_ASSEMBLER)
        bind(g, a, EMERGENCY_GEARBLADE)
        g.end_recruit_phase()
        self.assertEqual(m.atk, atk_of(AUTO_ASSEMBLER)
                         + num_of(REPAIR_JOB, 0))

    def test_opponent_board_untouched(self):
        g = make_game(2285)
        a, b = g.heroes
        m_b = put(g, b, AUTO_ASSEMBLER)
        own = put(g, a, AUTO_ASSEMBLER)   # 本人棋盘唯一（最左）机械
        t = bind(g, a, EMERGENCY_GEARBLADE)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(m_b.atk, atk_of(AUTO_ASSEMBLER))
        self.assertEqual(own.atk, atk_of(AUTO_ASSEMBLER)
                         + num_of(REPAIR_JOB, 0))               # 正对照

    def test_two_copies_stack(self):
        g = make_game(2286)
        a, b = g.heroes
        m = put(g, a, AUTO_ASSEMBLER)
        bind(g, a, EMERGENCY_GEARBLADE)
        bind(g, a, EMERGENCY_GEARBLADE, duplicate=True)
        for t in list(a.trinkets):
            g.run_script_hook(t, "end_of_turn")
        self.assertEqual(m.atk, atk_of(AUTO_ASSEMBLER)
                         + 2 * num_of(REPAIR_JOB, 0))


# ══════════════ BG36_MagicItem_820 Flighty Portrait ══════════════


class TestFlightyPortrait(unittest.TestCase):
    """Get a Flighty Scout; Tavern spell → +{0}/+{1} to Flighty Scouts in
    hand and warband."""

    def test_bind_grants_scout_and_pool_occupied(self):
        g = make_game(2290)
        a, b = g.heroes
        before = g.minion_pool.available(FLIGHTY_SCOUT)
        bind(g, a, FLIGHTY_PORTRAIT)
        self.assertEqual(hand_ids(a), [FLIGHTY_SCOUT])
        self.assertEqual(g.minion_pool.available(FLIGHTY_SCOUT), before - 1)

    def test_cast_buffs_scouts_in_hand_and_warband(self):
        g = make_game(2291)
        a, b = g.heroes
        board_scout = put(g, a, FLIGHTY_SCOUT)
        other = put(g, a, SLY_RAPTOR)
        bind(g, a, FLIGHTY_PORTRAIT)
        hand_scout = [c for c in a.hand
                      if c.card_id == FLIGHTY_SCOUT][0]
        da, dh = num_of(FLIGHTY_PORTRAIT, 0), \
            num_of(FLIGHTY_PORTRAIT, 1)
        b_atk, b_hp = board_scout.atk, board_scout.max_health
        h_atk, h_hp = hand_scout.atk, hand_scout.max_health
        o_atk, o_hp = other.atk, other.max_health
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual((board_scout.atk, board_scout.max_health),
                         (b_atk + da, b_hp + dh))
        self.assertEqual((hand_scout.atk, hand_scout.max_health),
                         (h_atk + da, h_hp + dh))
        self.assertEqual((other.atk, other.max_health), (o_atk, o_hp))

    def test_golden_scout_counts(self):
        g = make_game(2292)
        a, b = g.heroes
        gold_scout = put(g, a, FLIGHTY_SCOUT, golden=True)
        bind(g, a, FLIGHTY_PORTRAIT)
        da = num_of(FLIGHTY_PORTRAIT, 0)
        base = gold_scout.atk
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(gold_scout.atk, base + da)

    def test_opponent_isolation(self):
        g = make_game(2293)
        a, b = g.heroes
        scout_b = put(g, b, FLIGHTY_SCOUT)
        bind(g, a, FLIGHTY_PORTRAIT)
        base_b = scout_b.atk
        play_pool_spell(g, b, ARMOR_STASH)                      # 对手施法
        self.assertEqual(scout_b.atk, base_b)
        play_pool_spell(g, a, ARMOR_STASH)
        scout_a = put(g, a, FLIGHTY_SCOUT)
        # 正对照: 本人再施法 → 本人棋盘 scout 增益
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertGreater(scout_a.atk, atk_of(FLIGHTY_SCOUT))
        self.assertEqual(scout_b.atk, base_b)

    def test_non_pool_spell_no_trigger(self):
        g = make_game(2294)
        a, b = g.heroes
        scout = put(g, a, FLIGHTY_SCOUT)
        bind(g, a, FLIGHTY_PORTRAIT)
        base = scout.atk
        gem = g.create_spell(BLOOD_GEM, controller=a)
        a.hand.append(gem)
        gem.zone = Zone.HAND
        g.play_spell(a, gem, target=put(g, a, TAD))
        self.assertEqual(scout.atk, base)                       # 非池不触发
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertGreater(scout.atk, base)                     # 正对照

    def test_listener_persists_across_turns(self):
        g = make_game(2295)
        a, b = g.heroes
        scout = put(g, a, FLIGHTY_SCOUT)
        base = scout.atk
        bind(g, a, FLIGHTY_PORTRAIT)
        g.end_recruit_phase()
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertGreater(scout.atk, base)

    def test_two_copies_stack(self):
        g = make_game(2296)
        a, b = g.heroes
        da = num_of(FLIGHTY_PORTRAIT, 0)
        bind(g, a, FLIGHTY_PORTRAIT)
        bind(g, a, FLIGHTY_PORTRAIT, duplicate=True)
        scouts = [c for c in a.hand if c.card_id == FLIGHTY_SCOUT]
        self.assertEqual(len(scouts), 2)
        base = [c.atk for c in scouts]
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual([c.atk for c in scouts],
                         [x + 2 * da for x in base])


# ══════════════ BG36_MagicItem_830 Bloodfury Shield ══════════════


class TestBloodfuryShield(unittest.TestCase):
    """Cast a Tavern spell → add a Fodder to your next Refresh."""

    def _fodder_count(self, hero) -> int:
        return sum(1 for e in hero.tavern
                   if getattr(e, "card_id", None) == C.FODDER_CARD_ID)

    def test_cast_queues_fodder_for_next_refresh(self):
        g = make_game(2300)
        a, b = g.heroes
        bind(g, a, BLOODFURY_SHIELD)
        self.assertEqual(g._fodder_refresh_pending.get(a), None)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(g._fodder_refresh_pending.get(a), (1, 1))
        g.refresh_tavern(a)
        self.assertEqual(self._fodder_count(a), 1)
        self.assertNotIn(a, g._fodder_refresh_pending)          # 额度用尽

    def test_without_trinket_no_fodder(self):
        g = make_game(2301)
        a, b = g.heroes
        play_pool_spell(g, a, ARMOR_STASH)
        g.refresh_tavern(a)
        self.assertEqual(self._fodder_count(a), 0)
        # 正对照
        g2 = make_game(2301)
        a2 = g2.heroes[0]
        bind(g2, a2, BLOODFURY_SHIELD)
        play_pool_spell(g2, a2, ARMOR_STASH)
        g2.refresh_tavern(a2)
        self.assertEqual(self._fodder_count(a2), 1)

    def test_two_casts_two_refreshes(self):
        g = make_game(2302)
        a, b = g.heroes
        bind(g, a, BLOODFURY_SHIELD)
        play_pool_spell(g, a, ARMOR_STASH)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(g._fodder_refresh_pending.get(a), (2, 1))
        g.refresh_tavern(a)
        f1 = [e for e in a.tavern if e.card_id == C.FODDER_CARD_ID]
        self.assertEqual(len(f1), 1)                            # 每刷新 1 枚
        self.assertEqual(g._fodder_refresh_pending.get(a), (1, 1))
        g.refresh_tavern(a)
        self.assertNotIn(a, g._fodder_refresh_pending)          # 额度用尽
        f2 = [e for e in a.tavern if e.card_id == C.FODDER_CARD_ID]
        self.assertEqual(len(f2), 1)                            # 第二次刷新
        self.assertIsNot(f2[0], f1[0])                          # 是新的一枚
        g.refresh_tavern(a)
        self.assertEqual(self._fodder_count(a), 0)              # 额度不再产出

    def test_opponent_cast_not_counted(self):
        g = make_game(2303)
        a, b = g.heroes
        bind(g, a, BLOODFURY_SHIELD)
        play_pool_spell(g, b, ARMOR_STASH)
        self.assertIsNone(g._fodder_refresh_pending.get(a))
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(g._fodder_refresh_pending.get(a), (1, 1))

    def test_non_pool_spell_no_trigger(self):
        g = make_game(2304)
        a, b = g.heroes
        bind(g, a, BLOODFURY_SHIELD)
        gem = g.create_spell(BLOOD_GEM, controller=a)
        a.hand.append(gem)
        gem.zone = Zone.HAND
        g.play_spell(a, gem, target=put(g, a, TAD))
        self.assertIsNone(g._fodder_refresh_pending.get(a))
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(g._fodder_refresh_pending.get(a), (1, 1))

    def test_two_copies_stack(self):
        g = make_game(2305)
        a, b = g.heroes
        bind(g, a, BLOODFURY_SHIELD)
        bind(g, a, BLOODFURY_SHIELD, duplicate=True)
        play_pool_spell(g, a, ARMOR_STASH)
        self.assertEqual(g._fodder_refresh_pending.get(a), (2, 1))


# ══════════════ BG36_MagicItem_831 Felsteel Cleaver ══════════════


class TestFelsteelCleaver(unittest.TestCase):
    """Spell on a Tavern minion → a random friendly minion consumes it."""

    def _play_sirens_song(self, g: Game, hero: Hero, target) -> None:
        s = g.create_spell(SIRENS_SONG, controller=hero)
        s.zone = Zone.HAND
        hero.hand.append(s)
        assert g.play_spell(hero, s, target=target)

    def test_spell_on_tavern_minion_triggers_consume(self):
        g = make_game(2310)
        a, b = g.heroes
        consumer = put(g, a, ROT_HIDE_GNOLL)
        victim = tavern_put(g, a, TAD)
        bind(g, a, FELSTEEL_CLEAVER)
        base_atk, base_hp = consumer.atk, consumer.max_health
        self._play_sirens_song(g, a, victim)
        self.assertNotIn(victim, a.tavern)                      # 被吞噬
        self.assertEqual((consumer.atk, consumer.max_health),
                         (base_atk + atk_of(TAD),
                          base_hp + hp_of(TAD)))

    def test_without_trinket_victim_survives(self):
        g = make_game(2311)
        a, b = g.heroes
        consumer = put(g, a, ROT_HIDE_GNOLL)
        victim = tavern_put(g, a, TAD)
        base_atk = consumer.atk
        self._play_sirens_song(g, a, victim)
        self.assertIn(victim, a.tavern)                         # 仍在馆内
        self.assertEqual(consumer.atk, base_atk)
        # 正对照: 同 setup 绑定饰品 → 被吞噬
        g2 = make_game(2311)
        a2 = g2.heroes[0]
        c2 = put(g2, a2, ROT_HIDE_GNOLL)
        v2 = tavern_put(g2, a2, TAD)
        bind(g2, a2, FELSTEEL_CLEAVER)
        base2 = c2.atk
        self._play_sirens_song(g2, a2, v2)
        self.assertNotIn(v2, a2.tavern)
        self.assertEqual(c2.atk, base2 + atk_of(TAD))

    def test_spell_on_board_minion_no_trigger(self):
        g = make_game(2312)
        a, b = g.heroes
        consumer = put(g, a, ROT_HIDE_GNOLL)   # 棋盘唯一随从（随机消费者）
        bind(g, a, FELSTEEL_CLEAVER)
        base_atk = consumer.atk
        s = g.create_spell(BANANA, controller=a)
        s.zone = Zone.HAND
        a.hand.append(s)
        g.play_spell(a, s, target=consumer)                     # 目标是棋盘随从
        self.assertEqual(consumer.atk, base_atk + num_of(BANANA, 0))
        self.assertIn(consumer, a.board)
        # 正对照: 同为定向法术、目标换成酒馆随从 → 吞噬发生
        before = consumer.atk
        victim = tavern_put(g, a, TAD)
        self._play_sirens_song(g, a, victim)
        self.assertNotIn(victim, a.tavern)
        self.assertEqual(consumer.atk, before + atk_of(TAD))

    def test_empty_board_whiffs(self):
        g = make_game(2313)
        a, b = g.heroes
        victim = tavern_put(g, a, TAD)
        bind(g, a, FELSTEEL_CLEAVER)
        self._play_sirens_song(g, a, victim)
        self.assertIn(victim, a.tavern)                         # 无 consumer
        # 正对照: 有 consumer → 吞噬
        put(g, a, ROT_HIDE_GNOLL)
        self._play_sirens_song(g, a, victim)
        self.assertNotIn(victim, a.tavern)

    def test_opponent_spell_no_trigger(self):
        g = make_game(2314)
        a, b = g.heroes
        consumer = put(g, a, ROT_HIDE_GNOLL)
        victim_b = tavern_put(g, b, TAD)
        bind(g, a, FELSTEEL_CLEAVER)
        base_atk = consumer.atk
        self._play_sirens_song(g, b, victim_b)
        self.assertIn(victim_b, b.tavern)
        self.assertEqual(consumer.atk, base_atk)
        # 正对照: 本人施放同样法术 → 本人酒馆受害者被吞噬
        victim_a = tavern_put(g, a, TAD)
        self._play_sirens_song(g, a, victim_a)
        self.assertNotIn(victim_a, a.tavern)
        self.assertEqual(consumer.atk, base_atk + atk_of(TAD))

    def test_victim_returns_to_pool(self):
        g = make_game(2315)
        a, b = g.heroes
        put(g, a, ROT_HIDE_GNOLL)
        bind(g, a, FELSTEEL_CLEAVER)
        g.refresh_tavern(a)
        victim = [e for e in a.tavern if isinstance(e, Minion)][0]
        cid = victim.card_id
        before = g.minion_pool.available(cid)
        self._play_sirens_song(g, a, victim)
        self.assertNotIn(victim, a.tavern)
        self.assertEqual(g.minion_pool.available(cid), before + 1)

    def test_two_copies_consume_once(self):
        """两份副本: 同一受害者只能被吞噬一次（第二份落空, 不崩溃）。"""
        g = make_game(2316)
        a, b = g.heroes
        consumer = put(g, a, ROT_HIDE_GNOLL)
        victim = tavern_put(g, a, TAD)
        bind(g, a, FELSTEEL_CLEAVER)
        bind(g, a, FELSTEEL_CLEAVER, duplicate=True)
        base_atk = consumer.atk
        self._play_sirens_song(g, a, victim)
        self.assertNotIn(victim, a.tavern)
        self.assertEqual(consumer.atk, base_atk + atk_of(TAD))


# ══════════════ 注册表 / 台账守卫（结构性） ══════════════


class TestRegistryLedger(unittest.TestCase):
    """注册表、台账与引擎数据/文本证据（结构性——与钩子无关）。
    @engine-only
    """

    REGISTERED = {
        "BG36_MagicItem_363": "EscapeePortraitScript",
        "BG36_MagicItem_370": "MaldraxxusDaggerScript",
        "BG36_MagicItem_371": "HoneycombRingScript",
        "BG36_MagicItem_372": "SphereOfMemoryScript",
        "BG36_MagicItem_390": "BallerPortraitScript",
        "BG36_MagicItem_800": "DemonicBloodletterScript",
        "BG36_MagicItem_801": "ConsumingClawScript",
        "BG36_MagicItem_810": "InductiveGyrobladeScript",
        "BG36_MagicItem_810t": "InductiveGyrobladeScript",
        "BG36_MagicItem_812": "EmergencyGearbladeScript",
        "BG36_MagicItem_820": "FlightyPortraitScript",
        "BG36_MagicItem_830": "BloodfuryShieldScript",
        "BG36_MagicItem_831": "FelsteelCleaverScript",
    }
    # 380 Amplifying Essence / 841 Assembler Portrait 已由 batch_trinkets26
    # 注册（ELEMENTAL_EXTRA_* 消费点全族接线 + `_magnetic_stack` 战斗恢复）;
    # 362 Cyclist Portrait 已由 batch_trinkets31 注册（2026-09-18:
    # `Buff(persist=True)` 按来源跨战斗持久化 + `Game.add_persist_source`）。
    DEFERRED = ["BG36_MagicItem_373"]

    def test_implemented_registered(self):
        for cid, cls in self.REGISTERED.items():
            self.assertIn(cid, REGISTRY)
            self.assertEqual(REGISTRY[cid].__name__, cls, cid)

    def test_deferred_not_registered(self):
        for cid in self.DEFERRED:
            self.assertNotIn(cid, REGISTRY, cid)
            d = get_db().get(cid)
            self.assertIsNotNone(d, cid)
            self.assertTrue(d.name)

    def test_offer_pool_membership(self):
        pool = {d.id for d in get_db().trinket_offer_pool()}
        for cid in self.REGISTERED:
            if cid.endswith("t"):
                continue                    # 升级变体不进商店池
            self.assertIn(cid, pool, cid)
        self.assertNotIn("BG36_MagicItem_810t", pool)

    def test_tier_school_matches_ledger(self):
        school = {cid: get_db().get(cid).spell_school
                  for cid in list(self.REGISTERED) + self.DEFERRED}
        lesser = {"BG36_MagicItem_390", "BG36_MagicItem_800",
                  "BG36_MagicItem_801", "BG36_MagicItem_810",
                  "BG36_MagicItem_812", "BG36_MagicItem_820"}
        for cid, sc in school.items():
            self.assertEqual(sc, 11 if cid in lesser else 12, cid)

    def test_carddef_params(self):
        db = get_db()
        self.assertEqual(db.get("BG36_MagicItem_363").num(0), 1)
        self.assertEqual(db.get("BG36_MagicItem_371").num(0), 1)
        self.assertEqual(db.get("BG36_MagicItem_371").num(1), 1)
        self.assertEqual(db.get("BG36_MagicItem_372").num(0), 3)
        self.assertEqual(db.get("BG36_MagicItem_800").num(0), 1)
        self.assertEqual(db.get("BG36_MagicItem_800").num(1), 1)
        self.assertEqual(db.get("BG36_MagicItem_801").num(0), 5)
        self.assertEqual(db.get("BG36_MagicItem_801").num(1), 5)
        self.assertEqual(db.get("BG36_MagicItem_810").num(0), 4)
        self.assertEqual(db.get("BG36_MagicItem_810").num(1), 4)
        self.assertEqual(db.get("BG36_MagicItem_810t").num(0), 12)   # 37.0: 8→12
        self.assertEqual(db.get("BG36_MagicItem_820").num(0), 3)
        self.assertEqual(db.get("BG36_MagicItem_820").num(1), 3)
        self.assertEqual(db.get("BG36_MagicItem_380").num(0), 5)
        self.assertEqual(db.get("BG36_MagicItem_380").num(1), 1)
        self.assertEqual(db.get("BG36_MagicItem_380").num(2), 1)
        self.assertEqual(db.get("BG36_MagicItem_373").num(0), 1)
        self.assertEqual(db.get("BG36_MagicItem_373").num(1), 2)

    def test_card_text_matches_carddef(self):
        db = get_db()
        self.assertIn("Your Lockboxes", db.get("BG36_MagicItem_363").text)
        # 37.0 官方文本换行把 "Dark Gift" 拆成 "Dark\nGift"
        self.assertIn("Dark Gift",
                      " ".join(db.get("BG36_MagicItem_370").text.split()))
        self.assertIn("improve for this turn only",
                      db.get("BG36_MagicItem_371").text)
        self.assertIn("last", db.get("BG36_MagicItem_372").text)
        self.assertIn("Fire Baller or a", db.get("BG36_MagicItem_390").text)
        self.assertIn("this game", db.get("BG36_MagicItem_800").text)
        self.assertIn("Bonus Keyword", db.get("BG36_MagicItem_801").text)
        self.assertIn("Magnetic", db.get("BG36_MagicItem_810").text)
        self.assertIn("Repair Job", db.get("BG36_MagicItem_812").text)
        self.assertIn("Flighty Scouts", db.get("BG36_MagicItem_820").text)
        self.assertIn("Fodder", db.get("BG36_MagicItem_830").text)
        self.assertIn("Tavern minion", db.get("BG36_MagicItem_831").text)
        self.assertIn("permanent stats", db.get("BG36_MagicItem_362").text)
        self.assertIn("different", db.get("BG36_MagicItem_373").text)
        self.assertIn("improve this", db.get("BG36_MagicItem_380").text)
        self.assertIn("Magnetize", db.get("BG36_MagicItem_841").text)

    def test_related_card_data_chain(self):
        db = get_db()
        g = make_game(2399)
        self.assertEqual(g.trinket_related_card(EMERGENCY_GEARBLADE).id,
                         REPAIR_JOB)
        self.assertEqual(g.trinket_related_card(FLIGHTY_PORTRAIT).id,
                         FLIGHTY_SCOUT)
        self.assertEqual(g.trinket_related_card(ESCAPEE_PORTRAIT).id,
                         "BG36_523_G")
        self.assertEqual(g.trinket_related_card(BALLER_PORTRAIT).id,
                         FIRE_BALLER)
        self.assertEqual(db.get(SNOW_BALLER).name, "Snow Baller")
        self.assertEqual(db.get(SATELLITE).name, "Satellite")
        self.assertEqual(db.get(REPAIR_JOB).card_type.name, "BACON_SPELL")


if __name__ == "__main__":
    unittest.main()
