"""批次 trinkets23 行为层测试（解冻 4 张饰品: 713 / 917 / 952 / 920）。

全部断言走真实引擎路径:
  - 购买: 真实 `game._offer_trinkets` + `PendingChoice.choose`
    （resolve 扣费 → `hero.trinkets` → `run_script_hook(on_bind)`）
  - SoC: 真实 `game.run_combat(a, b)`（读到 SoC 结算后状态的探针 =
    `START_OF_COMBAT` 事件——引擎在饰品/奖励/随从 SoC 钩子**之后**广播）
  - 死亡: 真实 `game._process_single_death`（战斗内 `in_combat=True`）
  - 入手: 真实 `game.buy_from_tavern` / `hero.add_to_hand`
    （`card_gained` 广播路径，RULES §7.4.6b）
  - 回合推进: 真实 `game._begin_recruit_for`（TURN_START 过期窗口）
  - Spellcraft: 真实 `game.play_minion`（on_summon 生成）+
    `game.play_spell` + `spellcraft.generate_for_hero`
  - 池: `minion_pool.available` 前后差

覆盖（SOP §16 空转测试判定法）:
  - 每个效果类都有**正对照**（同 setup 无饰品 / 不满足条件的负例后补
    有效果路径确实发生）
  - owner 隔离（两英雄: 对手活动不产生本人效果）
  - 跨回合 / 一次性语义（战斗快照回滚、override 恢复、永久附魔不回收）
  - 落空不消耗资源（空板 / 空候选 / 池抽干 → 无副作用，且规则仍注册）
  - 副本条款（两份副本各触发一次，实例私有状态不串号——模式 35）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import START_OF_COMBAT, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race
from hsrl2.spell import Spell

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
PIRATE = "BG26_810"      # Gunpowder Courier 2/6 T4 海盗（无关键词）
BEAST = "BG26_802"       # Banana Slamma 3/6 T4 野兽（无关键词）
NAGA_A = "BG23_000"      # Mini-Myrmidon 1/4 T1 纳迦（Spellcraft 来源）
NAGA_B = "BG23_004"      # Deep-Sea Angler 2/3 T3 纳迦
ELEM_A = "BG31_816"      # Fire Baller 4/3 T2 元素
ELEM_B = "BG31_818"      # Snow Baller 3/4 T2 元素
ELEM_C = "BG31_843"      # Meteorite Crasher 4/4 T3 元素
AMALGAM = "BG36_640"     # Gatekeeper Amalgam 6/6 T6（Race.ALL 融合怪）
THAUM = "BG31_924"       # Thaumaturgist 1/2 T2 纳迦（Spellcraft）
THAUM_G = "BG31_924_G"   # 金色 Thaumaturgist
THAUM_SPELL = "BG31_924t"
THAUM_SPELL_G = "BG31_924_Gt"
FROSTLING = "BG26_537"   # Flourishing Frostling（非池 token 2/1）
ENEMY = "BG25_013"       # Rot Hide Gnoll 1/4 亡灵（坦克用）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def offer_and_buy(game: Game, hero: Hero, tid: str, kind: str):
    """真实饰品商店路径: _offer_trinkets → PendingChoice → resolve。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def put(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def soc_snapshot(game: Game, hero: Hero, fn) -> dict:
    """注册 SoC 后观测器（START_OF_COMBAT 每英雄各广播一次 → 按 hero 过滤）。"""
    seen: dict = {}

    def cb(g, hero=None, _h=hero, **kw):
        if hero is _h:
            seen["v"] = fn()

    game.events.register(Listener(event=START_OF_COMBAT, owner=hero,
                                  callback=cb))
    return seen


def death_in_combat(game: Game, victim: Minion) -> None:
    """战斗内直接驱动死亡处理（真实 `_process_single_death` 路径）。"""
    prev = game.in_combat
    game.in_combat = True
    try:
        victim.set(GameTag.HEALTH, 0)
        game._process_single_death(victim)
    finally:
        game.in_combat = prev


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


def spellcraft_ids(game: Game) -> set:
    from hsrl2.scripts.batches.batch_spells2 import _spellcraft_spell_ids
    return set(_spellcraft_spell_ids(game))


def stock_tavern_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    """把一张随从放进酒馆展示区（真实 `buy_from_tavern` 路径用）。"""
    m = game.create_minion(card_id, controller=hero)
    m.zone = 3
    hero.tavern.append(m)
    return m


# ══════════════ 注册表 / 数据链守卫 ══════════════

class TestRegistryState(unittest.TestCase):
    """注册面 + 卡定义/数据链一致性（结构性——与脚本钩子无关）。

    @engine-only: 本类断言注册表/数据链，钩子 no-op 后仍通过属预期。
    """

    IMPLEMENTED = ("BG35_MagicItem_713", "BG30_MagicItem_917",
                   "BG30_MagicItem_952", "BG32_MagicItem_920")
    KIND = {"BG35_MagicItem_713": "greater", "BG30_MagicItem_917": "lesser",
            "BG30_MagicItem_952": "greater",
            "BG32_MagicItem_920": "greater"}

    def test_all_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_offer_pool_membership_and_kind(self):
        db = get_db()
        offer_ids = {d.id for d in db.trinket_offer_pool()}
        for tid, kind in self.KIND.items():
            self.assertIn(tid, offer_ids, tid)
            self.assertEqual(db.get(tid).spell_school,
                             11 if kind == "lesser" else 12, tid)

    def test_carddef_params_pinned(self):
        db = get_db()
        d = db.get("BG35_MagicItem_713")
        self.assertEqual((d.num(0), d.num(1)), (16, 16))   # 37.0: 12/12→16/16
        for tid in ("BG30_MagicItem_917", "BG30_MagicItem_952",
                    "BG32_MagicItem_920"):
            self.assertTrue(all(db.get(tid).num(i) is None
                                for i in range(4)), tid)

    def test_evolution_data_chain(self):
        db = get_db()
        # 952 → Flourishing Frostling（非池 token）
        d = db.get("BG30_MagicItem_952")
        token = db.by_dbf(d.evolution_card_id)
        self.assertEqual(token.id, FROSTLING)
        self.assertFalse(token.is_pool_minion)
        # 920 → Thaumaturgist（池随从），金色链齐全
        d = db.get("BG32_MagicItem_920")
        self.assertEqual(db.by_dbf(d.evolution_card_id).id, THAUM)
        self.assertTrue(db.get(THAUM).is_pool_minion)
        # 713 不是交付卡（授予附魔）→ 无关联卡数据链
        self.assertIsNone(db.get("BG35_MagicItem_713").evolution_card_id)

    def test_payload_scripts_registered(self):
        for cid in (THAUM, THAUM_G, THAUM_SPELL, THAUM_SPELL_G):
            self.assertIn(cid, REGISTRY, cid)

    def test_spellcraft_candidate_pool_available(self):
        """917 的"随机 Spellcraft 法术"候选集非空（解冻依据核实）。"""
        g = make_game(seed=5900)
        cands = spellcraft_ids(g)
        self.assertIn(THAUM_SPELL, cands)
        self.assertGreaterEqual(len(cands), 5)


# ══════════════ BG35_MagicItem_713 Trusty Crowbar ══════════════

class TestTrustyCrowbar(unittest.TestCase):
    TID = "BG35_MagicItem_713"

    def test_buying_pirate_buffs_left_most(self):
        db = get_db()
        g = make_game(seed=7001)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        left = put(g, a, g.create_minion(BEAST, controller=a))
        right = put(g, a, g.create_minion(NAGA_A, controller=a))
        a.gold = 20
        stock_tavern_minion(g, a, PIRATE)
        self.assertTrue(g.buy_from_tavern(a, a.tavern[-1]))
        d = db.get(self.TID)
        self.assertEqual(left.atk, db.get(BEAST).atk + d.num(0))
        self.assertEqual(left.max_health,
                         db.get(BEAST).health + d.num(1))
        self.assertEqual(right.atk, db.get(NAGA_A).atk)   # 非最左不动

    def test_non_pirate_gain_does_not_trigger(self):
        g = make_game(seed=7002)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        left = put(g, a, g.create_minion(BEAST, controller=a))
        base = left.atk
        a.gold = 20
        stock_tavern_minion(g, a, BEAST)                  # 买野兽
        self.assertTrue(g.buy_from_tavern(a, a.tavern[-1]))
        self.assertEqual(left.atk, base)
        # 正对照: 同一 setup 买海盗确实 +num(0)
        stock_tavern_minion(g, a, PIRATE)
        self.assertTrue(g.buy_from_tavern(a, a.tavern[-1]))
        self.assertEqual(left.atk, base + get_db().get(self.TID).num(0))

    def test_amalgam_counts_as_pirate(self):
        g = make_game(seed=7003)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        left = put(g, a, g.create_minion(BEAST, controller=a))
        base = left.atk
        g.pending_hand_add(a, g.create_minion(AMALGAM, controller=a))
        self.assertEqual(left.atk, base + get_db().get(self.TID).num(0))

    def test_owner_isolation(self):
        g = make_game(seed=7004)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        mine = put(g, a, g.create_minion(BEAST, controller=a))
        base = mine.atk
        g.pending_hand_add(b, g.create_minion(PIRATE, controller=b))
        self.assertEqual(mine.atk, base)                  # 对手获得不触发
        g.pending_hand_add(a, g.create_minion(PIRATE, controller=a))
        self.assertEqual(mine.atk, base + get_db().get(self.TID).num(0))

    def test_empty_board_fizzles_without_consuming_gain(self):
        g = make_game(seed=7005)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        a.hand.clear()
        self.assertTrue(g.pending_hand_add(a, g.create_minion(PIRATE,
                                                              controller=a)))
        self.assertEqual(hand_ids(a), [PIRATE])           # 卡照常入手

    def test_buff_is_permanent_across_turn(self):
        g = make_game(seed=7006)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        left = put(g, a, g.create_minion(BEAST, controller=a))
        d = get_db().get(self.TID)
        buffs_before = len(left._buffs)
        g.pending_hand_add(a, g.create_minion(PIRATE, controller=a))
        self.assertEqual(len(left._buffs), buffs_before + 1)
        self.assertTrue(all(not b.temporary for b in left._buffs))
        atk_after = left.atk
        g._begin_recruit_for(a)
        self.assertEqual(left.atk, atk_after)             # 跨回合不回收

    def test_duplicate_copies_each_trigger(self):
        g = make_game(seed=7007)
        a = g.heroes[0]
        g.grant_trinket(a, self.TID, source="test")
        g.grant_trinket(a, self.TID, source="test", duplicate=True)
        self.assertEqual(len(a.trinkets), 2)
        left = put(g, a, g.create_minion(BEAST, controller=a))
        base = left.atk
        d = get_db().get(self.TID)
        g.pending_hand_add(a, g.create_minion(PIRATE, controller=a))
        self.assertEqual(left.atk, base + 2 * d.num(0))   # 两份各一次

    def test_control_without_trinket_untouched(self):
        g = make_game(seed=7008)
        a = g.heroes[0]
        left = put(g, a, g.create_minion(BEAST, controller=a))
        base = left.atk
        g.pending_hand_add(a, g.create_minion(PIRATE, controller=a))
        self.assertEqual(left.atk, base)


# ══════════════ BG30_MagicItem_917 Rusty Trident ══════════════

class TestRustyTrident(unittest.TestCase):
    TID = "BG30_MagicItem_917"

    def test_soc_grants_deathrattle_to_own_nagas_only(self):
        g = make_game(seed=7101)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        mine = put(g, a, g.create_minion(NAGA_A, controller=a))
        theirs = put(g, b, g.create_minion(NAGA_B, controller=b))
        seen = soc_snapshot(g, a, lambda: (mine.has(GameTag.DEATHRATTLE),
                                           theirs.has(GameTag.DEATHRATTLE)))
        g.run_combat(a, b)
        self.assertEqual(seen.get("v"), (True, False))

    def test_amalgam_counts_as_naga(self):
        g = make_game(seed=7102)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        amalgam = put(g, a, g.create_minion(AMALGAM, controller=a))
        seen = soc_snapshot(g, a,
                            lambda: amalgam.has(GameTag.DEATHRATTLE))
        g.run_combat(a, g.heroes[1])
        self.assertTrue(seen.get("v"))

    def test_no_naga_fizzles_then_positive_contrast(self):
        g = make_game(seed=7103)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        beast = put(g, a, g.create_minion(BEAST, controller=a))
        seen = soc_snapshot(g, a, lambda: beast.has(GameTag.DEATHRATTLE))
        g.run_combat(a, g.heroes[1])
        self.assertFalse(seen.get("v"))
        # 正对照: 放入纳迦后同一饰品确实授予
        naga = put(g, a, g.create_minion(NAGA_A, controller=a))
        seen2 = soc_snapshot(g, a, lambda: naga.has(GameTag.DEATHRATTLE))
        g.run_combat(a, g.heroes[1])
        self.assertTrue(seen2.get("v"))

    def test_deathrattle_gets_random_spellcraft_spell(self):
        g = make_game(seed=7104)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "lesser")
        naga = put(g, a, g.create_minion(NAGA_A, controller=a))
        put(g, b, g.create_minion(ENEMY, controller=b))
        a.hand.clear()
        g.in_combat = True
        g._active_combat = (a, b)
        g.run_script_hook(trinket, "start_of_combat")
        cands = spellcraft_ids(g)
        death_in_combat(g, naga)
        spells = [e for e in a.hand if e.has(GameTag.SPELLCRAFT)]
        self.assertEqual(len(spells), 1)
        self.assertIn(spells[0].card_id, cands)

    def test_grant_restored_after_combat(self):
        g = make_game(seed=7105)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        naga = put(g, a, g.create_minion(NAGA_A, controller=a))
        naga.set(GameTag.BASE_HEALTH, 30)
        naga.set(GameTag.HEALTH, 30)
        self.assertEqual(naga._script_overrides, {})
        seen = soc_snapshot(g, a, lambda: bool(naga._script_overrides))
        g.run_combat(a, b)
        self.assertTrue(seen.get("v"))                   # 战内已授予
        self.assertEqual(naga._script_overrides, {})     # 战后已恢复
        self.assertFalse(naga.has(GameTag.DEATHRATTLE))
        a.hand.clear()
        death_in_combat(g, naga)                         # 战后死亡不再产出
        self.assertEqual([e for e in a.hand
                          if e.has(GameTag.SPELLCRAFT)], [])

    def test_duplicate_copies_grant_twice(self):
        g = make_game(seed=7106)
        a, b = g.heroes
        trinket = g.grant_trinket(a, self.TID, source="test")
        g.grant_trinket(a, self.TID, source="test", duplicate=True)
        self.assertEqual(len(a.trinkets), 2)
        naga = put(g, a, g.create_minion(NAGA_A, controller=a))
        put(g, b, g.create_minion(ENEMY, controller=b))
        a.hand.clear()
        g.in_combat = True
        g._active_combat = (a, b)
        for t in a.trinkets:                             # 引擎逐饰品分发 SoC
            g.run_script_hook(t, "start_of_combat")
        self.assertIs(trinket, a.trinkets[0])
        death_in_combat(g, naga)
        spells = [e for e in a.hand if e.has(GameTag.SPELLCRAFT)]
        self.assertEqual(len(spells), 2)                 # 两份各一张

    def test_control_without_trinket_no_grant(self):
        g = make_game(seed=7107)
        a, b = g.heroes
        naga = put(g, a, g.create_minion(NAGA_A, controller=a))
        put(g, b, g.create_minion(ENEMY, controller=b))
        a.hand.clear()
        g.in_combat = True
        g._active_combat = (a, b)
        death_in_combat(g, naga)
        self.assertEqual([e for e in a.hand
                          if e.has(GameTag.SPELLCRAFT)], [])


# ══════════════ BG30_MagicItem_952 Jarred Frostling ══════════════

class TestJarredFrostling(unittest.TestCase):
    TID = "BG30_MagicItem_952"

    def test_soc_grants_to_two_random_friendly_elementals(self):
        g = make_game(seed=7201)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        mine = [put(g, a, g.create_minion(cid, controller=a))
                for cid in (ELEM_A, ELEM_B, ELEM_C)]
        theirs = put(g, b, g.create_minion(ELEM_A, controller=b))
        seen = soc_snapshot(
            g, a, lambda: ([m.has(GameTag.DEATHRATTLE) for m in mine],
                           theirs.has(GameTag.DEATHRATTLE)))
        g.run_combat(a, b)
        granted, enemy = seen.get("v")
        self.assertEqual(sum(1 for x in granted if x), 2)
        self.assertFalse(enemy)

    def test_single_elemental_receives_it(self):
        g = make_game(seed=7202)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        elem = put(g, a, g.create_minion(ELEM_A, controller=a))
        seen = soc_snapshot(g, a, lambda: elem.has(GameTag.DEATHRATTLE))
        g.run_combat(a, g.heroes[1])
        self.assertTrue(seen.get("v"))

    def test_no_elemental_fizzles_then_positive_contrast(self):
        g = make_game(seed=7203)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        beast = put(g, a, g.create_minion(BEAST, controller=a))
        seen = soc_snapshot(g, a, lambda: beast.has(GameTag.DEATHRATTLE))
        g.run_combat(a, g.heroes[1])
        self.assertFalse(seen.get("v"))
        elem = put(g, a, g.create_minion(ELEM_A, controller=a))
        seen2 = soc_snapshot(g, a, lambda: elem.has(GameTag.DEATHRATTLE))
        g.run_combat(a, g.heroes[1])
        self.assertTrue(seen2.get("v"))

    def test_deathrattle_summons_flourishing_frostling(self):
        g = make_game(seed=7204)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "greater")
        elem = put(g, a, g.create_minion(ELEM_A, controller=a))
        put(g, b, g.create_minion(ENEMY, controller=b))
        g.in_combat = True
        g._active_combat = (a, b)
        g.run_script_hook(trinket, "start_of_combat")
        self.assertTrue(elem.has(GameTag.DEATHRATTLE))
        death_in_combat(g, elem)
        tokens = [m for m in g.combat_summon_log if m.card_id == FROSTLING]
        self.assertEqual(len(tokens), 1)
        self.assertIs(tokens[0].controller, a)

    def test_grant_restored_after_combat(self):
        g = make_game(seed=7205)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        elem = put(g, a, g.create_minion(ELEM_A, controller=a))
        self.assertEqual(elem._script_overrides, {})
        seen = soc_snapshot(g, a, lambda: bool(elem._script_overrides))
        g.run_combat(a, b)
        self.assertTrue(seen.get("v"))
        self.assertEqual(elem._script_overrides, {})
        self.assertFalse(elem.has(GameTag.DEATHRATTLE))
        death_in_combat(g, elem)
        self.assertEqual([m for m in g.combat_summon_log
                          if m.card_id == FROSTLING], [])

    def test_duplicate_copies_grant_twice(self):
        g = make_game(seed=7206)
        a, b = g.heroes
        trinket = g.grant_trinket(a, self.TID, source="test")
        g.grant_trinket(a, self.TID, source="test", duplicate=True)
        elem = put(g, a, g.create_minion(ELEM_A, controller=a))
        put(g, b, g.create_minion(ENEMY, controller=b))
        g.in_combat = True
        g._active_combat = (a, b)
        for t in a.trinkets:                             # 引擎逐饰品分发 SoC
            g.run_script_hook(t, "start_of_combat")
        self.assertIs(trinket, a.trinkets[0])
        death_in_combat(g, elem)
        tokens = [m for m in g.combat_summon_log if m.card_id == FROSTLING]
        self.assertEqual(len(tokens), 2)

    def test_control_without_trinket_no_grant(self):
        g = make_game(seed=7207)
        a, b = g.heroes
        elem = put(g, a, g.create_minion(ELEM_A, controller=a))
        put(g, b, g.create_minion(ENEMY, controller=b))
        death_in_combat(g, elem)
        self.assertEqual([m for m in g.combat_summon_log
                          if m.card_id == FROSTLING], [])


# ══════════════ BG32_MagicItem_920 Thaumaturgist Portrait ══════════════

class TestThaumaturgistPortrait(unittest.TestCase):
    TID = "BG32_MagicItem_920"

    def _play_thaumaturgist(self, game, hero, card_id=THAUM):
        """打出萨满（真实 play_minion → on_summon 生成第一张法术）。"""
        hero.gold = 30
        m = game.create_minion(card_id, controller=hero)
        game.summon(hero, m)
        return m

    def _spell_in_hand(self, hero, card_id=THAUM_SPELL):
        spells = [e for e in hero.hand
                  if isinstance(e, Spell) and e.card_id == card_id]
        assert spells, [e.card_id for e in hero.hand]
        return spells[0]

    def test_bind_grants_thaumaturgist_and_consumes_pool(self):
        g = make_game(seed=7301)
        a = g.heroes[0]
        before = g.minion_pool.available(THAUM)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(hand_ids(a).count(THAUM), 1)
        self.assertEqual(g.minion_pool.available(THAUM), before - 1)
        self.assertEqual(len(a.permanent_spellcraft_rules), 1)

    def test_exhausted_pool_fizzles_but_rule_still_registered(self):
        g = make_game(seed=7302)
        a = g.heroes[0]
        while g.minion_pool.available(THAUM) > 0:
            g.minion_pool.acquire(THAUM)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(hand_ids(a).count(THAUM), 0)     # 落空
        self.assertEqual(len(a.permanent_spellcraft_rules), 1)
        # 正对照: 规则仍生效（池空不影响永久化条款）
        m = self._play_thaumaturgist(g, a)
        spell = self._spell_in_hand(a)
        self.assertTrue(getattr(spell, "permanent_spellcraft", False))
        self.assertTrue(any(r[1](m) for r in a.permanent_spellcraft_rules))

    def test_spellcraft_from_thaumaturgist_is_permanent(self):
        g = make_game(seed=7303)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        mage = self._play_thaumaturgist(g, a)
        target = put(g, a, g.create_minion(BEAST, controller=a))
        spell = self._spell_in_hand(a)
        self.assertTrue(getattr(spell, "permanent_spellcraft", False))
        base = target.atk
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertGreater(target.atk, base)
        self.assertTrue(target._buffs)
        self.assertTrue(all(not b.temporary for b in target._buffs))
        atk_after = target.atk
        g._begin_recruit_for(a)                          # 下一招募阶段
        self.assertEqual(target.atk, atk_after)          # 不回收
        self.assertTrue(target._buffs)
        self.assertIsNotNone(mage)                       # 来源仍在场

    def test_without_trinket_spellcraft_expires(self):
        """负对照: 无饰品时同一法术是 temporary 且下一回合被回收。"""
        g = make_game(seed=7304)
        a = g.heroes[0]
        self._play_thaumaturgist(g, a)
        target = put(g, a, g.create_minion(BEAST, controller=a))
        spell = self._spell_in_hand(a)
        self.assertFalse(getattr(spell, "permanent_spellcraft", False))
        base = target.atk
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertEqual(target.atk, base + 1)
        g._begin_recruit_for(a)
        self.assertEqual(target.atk, base)               # 已回收

    def test_other_spellcraft_source_not_marked(self):
        g = make_game(seed=7305)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        self._play_thaumaturgist(g, a, card_id=NAGA_A)   # 非萨满 Spellcraft
        spells = [e for e in a.hand
                  if isinstance(e, Spell) and e.has(GameTag.SPELLCRAFT)]
        self.assertEqual(len(spells), 1)
        self.assertFalse(getattr(spells[0], "permanent_spellcraft", False))

    def test_golden_thaumaturgist_matches(self):
        g = make_game(seed=7306)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        self._play_thaumaturgist(g, a, card_id=THAUM_G)
        spell = self._spell_in_hand(a, THAUM_SPELL_G)
        self.assertTrue(getattr(spell, "permanent_spellcraft", False))

    def test_rule_expires_when_trinket_leaves(self):
        g = make_game(seed=7307)
        a = g.heroes[0]
        trinket = offer_and_buy(g, a, self.TID, "greater")
        mage = g.create_minion(THAUM, controller=a)
        self.assertTrue(g._permanent_spellcraft_matches(a, mage))
        a.trinkets.remove(trinket)
        self.assertFalse(g._permanent_spellcraft_matches(a, mage))

    def test_owner_isolation(self):
        g = make_game(seed=7308)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        self._play_thaumaturgist(g, b)
        spells = [e for e in b.hand
                  if isinstance(e, Spell) and e.has(GameTag.SPELLCRAFT)]
        self.assertTrue(spells)
        for s in spells:
            self.assertFalse(getattr(s, "permanent_spellcraft", False))

    def test_duplicate_copies_grant_two_and_rules_do_not_cross(self):
        g = make_game(seed=7309)
        a = g.heroes[0]
        g.grant_trinket(a, self.TID, source="test")
        g.grant_trinket(a, self.TID, source="test", duplicate=True)
        self.assertEqual(hand_ids(a).count(THAUM), 2)
        self.assertEqual(len(a.permanent_spellcraft_rules), 2)
        # 两份副本的规则各自独立 — 移除一份后另一份仍生效
        a.trinkets.pop(0)
        mage = g.create_minion(THAUM, controller=a)
        self.assertTrue(g._permanent_spellcraft_matches(a, mage))


if __name__ == "__main__":
    unittest.main()
