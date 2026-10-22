"""批次 trinkets6 行为层测试（8 张"额外触发配额"饰品，RULES §6.20）。

全部断言走真实引擎路径:
  - 购买: 真实 `game._offer_trinkets` 三选一 + PendingChoice.choose
    （resolve 回调扣费 → hero.trinkets → run_script_hook(on_bind)）
  - EoT: 真实 `game.end_recruit_phase()`
  - SoC / 战斗: 真实 `game.run_combat(a, b)`（战斗内探针读 SoC 结算后的
    场面）
  - 亡语: 真实 `game._process_single_death`（战斗内）
  - 法术: 真实 `game.play_spell`（带 on_play 探针计数结算次数）
  - 战吼: 真实 `game.play_minion`
  - 英雄技能: 真实 `game.use_hero_power`
  - Discover: 真实 `Discover` Action 的预留/释放池记账

覆盖（SOP §16 空转测试判定法——每个效果类都有正对照 + 无饰品对照）:
  - owner 隔离（2 英雄; 每个配额都有"对手活动不生效"断言）
  - 每回合/每场战斗重置语义（spell_first / spellcraft_first / soc_first /
    dr_first）
  - 叠加（Drakkari 与 eot_extra 累加）
  - 池占返（Deathly Phylactery 发现预留/resolve、Sushi Roll 池法术）
  - 配额值与 CardDef.num(0) 双向钉死
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from hsrl2.actions import Hit
from hsrl2.db import CardDB
from hsrl2.events import START_OF_COMBAT, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets6 as B6
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
DRAGON_BATTLECRY = "BG26_963"    # Electric Synthesizer 3/4 T2 龙（战吼）
NONDRAGON_BATTLECRY = "BG26_135"  # Southsea Busker 3/1 无类型（战吼）
VALOROUS_MEDALLION = "BG30_MagicItem_970"  # SoC: 你的随从 +2/+2（Lesser）
MURLOC = "BG22_202"              # Tad 2/2 鱼人
SPELL_PLAIN = "BG28_800"         # Careful Investment（池法术，无定向）
BLACKTHORN_HERO = "BG20_HERO_103"  # 真实英雄（技能 BG20_HERO_103p）
BLACKTHORN_POWER = "BG20_HERO_103p"

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 700):
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def offer_and_buy(game, hero, tid: str, kind: str):
    """真实饰品商店路径: _offer_trinkets → PendingChoice → resolve。

    档位由调用方给定（lesser=11 / greater=12，`CardDef.spell_school`）。
    为让目标饰品必然可选，把 offer 的 options 收敛为 [目标 CardDef]，
    resolve 回调本身是引擎真实实现（扣费 / `_trinkets_granted` /
    `hero.trinkets.append` / `run_script_hook(on_bind, ctx={"hero":...})`）。
    """
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def probe(scripts: dict):
    """构造带指定钩子的探针脚本类（调用次数记录到方案给定的 bucket）。"""
    return type("Probe", (), dict(scripts))


def probe_minion(hook: str, bucket: list, *, atk=1, health=5) -> Minion:
    m = Minion(f"PROBE_{hook}", "P", atk=atk, health=health)
    m.scripts = probe({
        hook: staticmethod(lambda s, g, c=None, **kw: bucket.append(s) or None)})
    return m


def put(game, hero, m: Minion):
    game.summon(hero, m)
    return m


def tavern_spell(game, hero, card_id=SPELL_PLAIN, *, spellcraft=False):
    """从池中取一张法术入手（占池；play_spell 结束回池——收支平衡）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.add_to_hand(s)
    if spellcraft:
        s.set(GameTag.SPELLCRAFT, True)
    return s


def spell_probe(game, hero, calls, *, spellcraft=False):
    s = tavern_spell(game, hero, spellcraft=spellcraft)
    s.scripts = probe({
        "on_play": staticmethod(
            lambda ss, g, c=None, **kw: calls.append(ss) or None)})
    return s


def kill_in_combat(game, victim):
    """战斗内致死（`_process_single_death` 真实路径，dr_first 阶段守卫）。"""
    prev = game.in_combat
    game.in_combat = True
    try:
        game.run_actions(Hit(victim, victim.health))
    finally:
        game.in_combat = prev


def process_death_in_combat(game, hero_b, victim):
    """战斗内直接驱动死亡处理（engine_gaps 同款真实路径）。"""
    game.in_combat = True
    game._active_combat = (victim.controller, hero_b)
    try:
        victim.health = 0
        game._process_single_death(victim)
    finally:
        game.in_combat = False
        game._active_combat = None


def deathrattle_pool_sum(game):
    """全部池内亡语随从的剩余副本总数（发现预留/resolve 的池账）。"""
    all_ids = [d.id for d in get_db().pool_minions()
               if "deathrattle" in d.keywords]
    return sum(game.minion_pool.available(i) for i in all_ids)


class TestRegistryState(unittest.TestCase):
    """注册面 + 文本/数据一致性（结构性，与钩子无关）。"""

    IMPLEMENTED = (
        "BG32_MagicItem_367", "BG32_MagicItem_365", "BG30_MagicItem_918",
        "BG30_MagicItem_700", "BG30_MagicItem_434", "BG30_MagicItem_920",
        "BG36_MagicItem_215", "BG35_MagicItem_801",
    )
    # 配额 key 与 RULES §6.20 的声明面双向钉死
    QUOTA_KEYS = {
        "BG32_MagicItem_367": "eot_extra",
        "BG32_MagicItem_365": "soc_extra",
        "BG30_MagicItem_918": "soc_first",
        "BG30_MagicItem_700": "dr_first",
        "BG30_MagicItem_434": "spell_first",
        "BG30_MagicItem_920": "spellcraft_first",
        "BG36_MagicItem_215": "bc_times_race",
        "BG35_MagicItem_801": "hp_uses",
    }
    KIND = {
        "BG32_MagicItem_367": "greater",
        "BG32_MagicItem_365": "greater",
        "BG30_MagicItem_918": "greater",
        "BG30_MagicItem_700": "lesser",
        "BG30_MagicItem_434": "lesser",
        "BG30_MagicItem_920": "greater",
        "BG36_MagicItem_215": "greater",
        "BG35_MagicItem_801": "lesser",
    }

    def test_all_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)
        self.assertEqual(len(self.IMPLEMENTED), 8)

    def test_class_binding(self):
        self.assertIs(REGISTRY["BG32_MagicItem_367"],
                      B6.GhastlyStickerScript)
        self.assertIs(REGISTRY["BG32_MagicItem_365"],
                      B6.ValdrakkenWindChimesScript)
        self.assertIs(REGISTRY["BG30_MagicItem_918"],
                      B6.PromoPortraitScript)
        self.assertIs(REGISTRY["BG30_MagicItem_700"],
                      B6.DeathlyPhylacteryScript)
        self.assertIs(REGISTRY["BG30_MagicItem_434"],
                      B6.ReplicaCathedralScript)
        self.assertIs(REGISTRY["BG30_MagicItem_920"],
                      B6.SpitescaleSushiRollScript)
        self.assertIs(REGISTRY["BG36_MagicItem_215"], B6.DragonsEyeScript)
        self.assertIs(REGISTRY["BG35_MagicItem_801"],
                      B6.SousChefStickerScript)

    def test_quota_key_set_matches_rules_table(self):
        db = get_db()
        expected = set(self.QUOTA_KEYS.values()) | {"bc_race"}
        declared = set()
        for tid in self.IMPLEMENTED:
            game = make_game(seed=777)
            hero = game.heroes[0]
            offer_and_buy(game, hero, tid, self.KIND[tid])
            declared |= set(hero.extra_triggers)
        self.assertEqual(declared, expected, declared)

    def test_promo_portrait_grants_prized_promo_drake(self):
        db = get_db()
        d = db.get("BG30_MagicItem_918")
        self.assertIsNotNone(d.evolution_card_id)
        token = db.by_dbf(d.evolution_card_id)
        self.assertIsNotNone(token)
        self.assertEqual(token.id, "BG21_014")
        self.assertEqual(token.name, "Prized Promo-Drake")
        self.assertFalse(token.is_pool_minion)

    def test_sushi_roll_grants_pool_spell(self):
        db = get_db()
        d = db.get("BG30_MagicItem_920")
        token = db.by_dbf(d.evolution_card_id)
        self.assertIsNotNone(token)
        self.assertEqual(token.id, "BG28_606")
        self.assertTrue(token.is_pool_spell)
        self.assertEqual(d.num(0), 2)          # "first two"

    def test_replica_cathedral_num_param_is_one(self):
        d = get_db().get("BG30_MagicItem_434")
        self.assertEqual(d.num(0), 1)
        self.assertIn("first spell each turn", d.text)

    def test_deathrattle_candidates_are_pool_deathrattles(self):
        g = make_game(seed=778)
        cands = B6._deathrattle_candidates(g)
        self.assertTrue(cands)
        db = get_db()
        for cid in cands:
            self.assertIn("deathrattle", db.get(cid).keywords)
            self.assertGreater(g.minion_pool.available(cid), 0)

    def test_all_in_offer_pool_at_declared_tier(self):
        db = get_db()
        offer_ids = {d.id for d in db.trinket_offer_pool()}
        for tid, kind in self.KIND.items():
            self.assertIn(tid, offer_ids, tid)
            school = 11 if kind == "lesser" else 12
            self.assertEqual(db.get(tid).spell_school, school, tid)


# ══════════════════ BG32_MagicItem_367 Ghastly Sticker ══════════════════

class TestGhastlySticker(unittest.TestCase):
    TID = "BG32_MagicItem_367"

    def test_eot_effects_trigger_extra_time(self):
        g = make_game(seed=801)
        a, b = g.heroes
        calls = []
        put(g, a, probe_minion("end_of_turn", calls))
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(a.extra_triggers["eot_extra"], 1)
        g.end_recruit_phase()
        self.assertEqual(len(calls), 2)          # 基础 1 + 配额 1

    def test_control_without_trinket(self):
        g = make_game(seed=802)
        a = g.heroes[0]
        calls = []
        put(g, a, probe_minion("end_of_turn", calls))
        g.end_recruit_phase()
        self.assertEqual(len(calls), 1)          # 无饰品 = 基线 1

    def test_stacks_with_drakkari(self):
        from hsrl2.scripts.batches.batch_doublers import (
            DrakkariEnchanterScript)
        g = make_game(seed=803)
        a = g.heroes[0]
        calls = []
        put(g, a, probe_minion("end_of_turn", calls))
        drak = g.create_minion("BG26_ICC_901", controller=a)
        drak.scripts = DrakkariEnchanterScript
        put(g, a, drak)
        offer_and_buy(g, a, self.TID, "greater")
        g.end_recruit_phase()
        # 1 基础 + 1 配额 + 1 Drakkari = 3
        self.assertEqual(len(calls), 3)

    def test_opponent_eot_not_doubled(self):
        g = make_game(seed=804)
        a, b = g.heroes
        calls = []
        put(g, b, probe_minion("end_of_turn", calls))
        offer_and_buy(g, a, self.TID, "greater")
        g.end_recruit_phase()
        self.assertEqual(len(calls), 1)          # owner 隔离


# ══════════════ BG32_MagicItem_365 Valdrakken Wind Chimes ══════════════

class TestValdrakkenWindChimes(unittest.TestCase):
    TID = "BG32_MagicItem_365"

    def test_soc_effects_trigger_extra_time(self):
        g = make_game(seed=811)
        a, b = g.heroes
        calls = []
        put(g, a, probe_minion("start_of_combat", calls, health=50))
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(a.extra_triggers["soc_extra"], 1)
        g.run_combat(a, b)
        self.assertEqual(len(calls), 2)          # 每个 SoC 效果 +1

    def test_control_without_trinket(self):
        g = make_game(seed=812)
        a, b = g.heroes
        calls = []
        put(g, a, probe_minion("start_of_combat", calls, health=50))
        g.run_combat(a, b)
        self.assertEqual(len(calls), 1)

    def test_quota_persists_across_combats(self):
        g = make_game(seed=813)
        a, b = g.heroes
        calls = []
        m = probe_minion("start_of_combat", calls, health=50)
        put(g, a, m)
        offer_and_buy(g, a, self.TID, "greater")
        g.run_combat(a, b)
        g.run_combat(a, b)
        self.assertEqual(len(calls), 4)          # soc_extra 是永久额度

    def test_opponent_soc_not_doubled(self):
        g = make_game(seed=814)
        a, b = g.heroes
        calls = []
        put(g, b, probe_minion("start_of_combat", calls, health=50))
        offer_and_buy(g, a, self.TID, "greater")
        g.run_combat(a, b)
        self.assertEqual(len(calls), 1)          # owner 隔离


# ══════════════════ BG30_MagicItem_918 Promo Portrait ══════════════════

class TestPromoPortrait(unittest.TestCase):
    TID = "BG30_MagicItem_918"

    def _play_out_soc(self, seed, with_promo):
        """真实战斗内读取 SoC 结算后的场面（战斗后回滚，故用事件探针）。"""
        g = make_game(seed=seed)
        a, b = g.heroes
        offer_and_buy(g, a, VALOROUS_MEDALLION, "lesser")
        if with_promo:
            offer_and_buy(g, a, self.TID, "greater")
        m = g.create_minion(MURLOC, controller=a)   # 2/2
        put(g, a, m)
        seen = []
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            callback=lambda gg, hero=None, **kw:
                seen.append(m.atk) if hero is a else None))
        g.run_combat(a, b)
        return seen[-1]

    def test_bind_grants_prized_promo_drake(self):
        g = make_game(seed=821)
        a, b = g.heroes
        before = g.minion_pool.available("BG21_014")
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual([e.card_id for e in a.hand], ["BG21_014"])
        # token 语义: 非池随从，占池量不变
        self.assertEqual(g.minion_pool.available("BG21_014"), before)
        self.assertEqual(b.hand, [])
        self.assertEqual(a.extra_triggers["soc_first"], 1)

    def test_first_soc_effect_triggers_twice(self):
        # 控制: Valorous Medallion 单独 → 2/2 + 2/2 = 4
        self.assertEqual(self._play_out_soc(822, with_promo=False), 4)
        # Promo Portrait 排在后面的真实 SoC 效果 → 额外触发 1 次 = +4/4
        self.assertEqual(self._play_out_soc(823, with_promo=True), 6)

    def test_quota_resets_each_combat(self):
        g = make_game(seed=824)
        a, b = g.heroes
        offer_and_buy(g, a, VALOROUS_MEDALLION, "lesser")
        offer_and_buy(g, a, self.TID, "greater")
        m = g.create_minion(MURLOC, controller=a)
        put(g, a, m)
        seen = []
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            callback=lambda gg, hero=None, **kw:
                seen.append(m.atk) if hero is a else None))
        g.run_combat(a, b)
        g.run_combat(a, b)
        # 两场战斗各吃一次配额（每场重置）→ 两次都读到 6
        self.assertEqual(seen, [6, 6])

    def test_opponent_soc_not_doubled(self):
        g = make_game(seed=825)
        a, b = g.heroes
        calls = []
        put(g, b, probe_minion("start_of_combat", calls, health=50))
        offer_and_buy(g, a, self.TID, "greater")
        g.run_combat(a, b)
        self.assertEqual(len(calls), 1)          # owner 隔离


# ══════════════════ BG30_MagicItem_700 Deathly Phylactery ══════════════════

class TestDeathlyPhylactery(unittest.TestCase):
    TID = "BG30_MagicItem_700"

    def test_discover_offers_deathrattle_minions(self):
        g = make_game(seed=831)
        a, b = g.heroes
        before = deathrattle_pool_sum(g)
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices[0]
        self.assertEqual(choice.owner, a)
        self.assertEqual(choice.kind, "discover_minion")
        self.assertEqual(len(choice.options), 3)
        for cid in choice.options:
            self.assertIn("deathrattle", get_db().get(cid).keywords)
        # 预留语义: 选项生成即占池
        self.assertEqual(deathrattle_pool_sum(g), before - 3)
        self.assertEqual(a.extra_triggers["dr_first"], 1)

    def test_choose_grants_pick_and_releases_others(self):
        g = make_game(seed=832)
        a, b = g.heroes
        before = deathrattle_pool_sum(g)
        offer_and_buy(g, a, self.TID, "lesser")
        choice = g.pending_choices[0]
        pick = choice.options[1]
        choice.choose(1)
        self.assertEqual([e.card_id for e in a.hand], [pick])
        self.assertIn("deathrattle", get_db().get(pick).keywords)
        # 净账: 选中 1 份入手（未选项回池）
        self.assertEqual(deathrattle_pool_sum(g), before - 1)
        self.assertEqual(b.hand, [])

    def test_first_deathrattle_each_combat_extra(self):
        g = make_game(seed=833)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        g.pending_choices.clear()
        calls = []
        m1 = probe_minion("deathrattle", calls)
        m1.set(GameTag.DEATHRATTLE, True)
        put(g, a, m1)
        m2 = probe_minion("deathrattle", calls)
        m2.set(GameTag.DEATHRATTLE, True)
        put(g, a, m2)
        process_death_in_combat(g, b, m1)
        process_death_in_combat(g, b, m2)
        self.assertEqual(calls.count(m1), 2)     # 第一个亡语 +1 次
        self.assertEqual(calls.count(m2), 1)     # 第二个不再吃配额

    def test_control_without_trinket(self):
        g = make_game(seed=834)
        a, b = g.heroes
        calls = []
        m1 = probe_minion("deathrattle", calls)
        m1.set(GameTag.DEATHRATTLE, True)
        put(g, a, m1)
        process_death_in_combat(g, b, m1)
        self.assertEqual(calls.count(m1), 1)

    def test_recruit_phase_death_does_not_consume_quota(self):
        g = make_game(seed=835)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        g.pending_choices.clear()
        calls = []
        m = probe_minion("deathrattle", calls)
        m.set(GameTag.DEATHRATTLE, True)
        put(g, a, m)
        g.run_actions(Hit(m, m.health))          # 招募期死亡（in_combat=False）
        self.assertEqual(calls.count(m), 1)
        self.assertEqual(a.extra_trigger_used.get("dr_first", 0), 0)

    def test_quota_resets_each_combat(self):
        g = make_game(seed=836)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        g.pending_choices.clear()
        calls = []
        m1 = probe_minion("deathrattle", calls)
        m1.set(GameTag.DEATHRATTLE, True)
        put(g, a, m1)
        process_death_in_combat(g, b, m1)
        self.assertEqual(calls.count(m1), 2)
        g.run_combat(a, b)                       # 真实战斗 → 每场重置配额
        m2 = probe_minion("deathrattle", calls)
        m2.set(GameTag.DEATHRATTLE, True)
        put(g, a, m2)
        process_death_in_combat(g, b, m2)
        self.assertEqual(calls.count(m2), 2)     # 新一场的第一个亡语再 +1


# ══════════════════ BG30_MagicItem_434 Replica Cathedral ══════════════════

class TestReplicaCathedral(unittest.TestCase):
    TID = "BG30_MagicItem_434"

    def test_first_spell_casts_extra_time(self):
        g = make_game(seed=841)
        a = g.heroes[0]
        calls = []
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(a.extra_triggers["spell_first"], 1)
        self.assertTrue(g.play_spell(a, spell_probe(g, a, calls)))
        self.assertEqual(len(calls), 2)          # 首个法术结算 2 次
        self.assertTrue(g.play_spell(a, spell_probe(g, a, calls)))
        self.assertEqual(len(calls), 3)          # 第二个只 1 次

    def test_control_without_trinket(self):
        g = make_game(seed=842)
        a = g.heroes[0]
        calls = []
        self.assertTrue(g.play_spell(a, spell_probe(g, a, calls)))
        self.assertEqual(len(calls), 1)

    def test_quota_resets_next_turn(self):
        g = make_game(seed=843)
        a = g.heroes[0]
        calls = []
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertTrue(g.play_spell(a, spell_probe(g, a, calls)))
        self.assertEqual(len(calls), 2)
        g.end_recruit_phase()                    # 真实推进回合
        self.assertTrue(g.play_spell(a, spell_probe(g, a, calls)))
        self.assertEqual(len(calls), 4)          # 下回合首个再 2 次

    def test_opponent_spell_not_affected(self):
        g = make_game(seed=844)
        a, b = g.heroes
        calls = []
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertTrue(g.play_spell(b, spell_probe(g, b, calls)))
        self.assertEqual(len(calls), 1)          # owner 隔离
        self.assertEqual(a.extra_trigger_used.get("spell_first", 0), 0)


# ══════════════════ BG30_MagicItem_920 Spitescale Sushi Roll ══════════════════

class TestSpitescaleSushiRoll(unittest.TestCase):
    TID = "BG30_MagicItem_920"

    def test_bind_grants_spitescale_special(self):
        g = make_game(seed=851)
        a, b = g.heroes
        before = g.spell_pool.available("BG28_606")
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual([e.card_id for e in a.hand], ["BG28_606"])
        self.assertIsInstance(a.hand[0], Spell)
        # 池法术: 入手即占池（打出时回池）
        self.assertEqual(g.spell_pool.available("BG28_606"), before - 1)
        self.assertEqual(a.extra_triggers["spellcraft_first"],
                         get_db().get(self.TID).num(0))
        self.assertEqual(b.hand, [])

    def test_first_two_spellcraft_spells_extra(self):
        g = make_game(seed=852)
        a = g.heroes[0]
        calls = []
        offer_and_buy(g, a, self.TID, "greater")
        for _ in range(3):
            self.assertTrue(g.play_spell(
                a, spell_probe(g, a, calls, spellcraft=True)))
        self.assertEqual(len(calls), 5)          # 2 + 2 + 1

    def test_plain_spell_does_not_consume_spellcraft_quota(self):
        g = make_game(seed=853)
        a = g.heroes[0]
        calls = []
        offer_and_buy(g, a, self.TID, "greater")
        self.assertTrue(g.play_spell(a, spell_probe(g, a, calls)))
        self.assertEqual(len(calls), 1)          # 普通法术走 spell_first
        self.assertEqual(a.extra_trigger_used.get("spellcraft_first", 0), 0)
        self.assertTrue(g.play_spell(
            a, spell_probe(g, a, calls, spellcraft=True)))
        self.assertEqual(len(calls), 3)          # Spellcraft 仍吃满配额

    def test_quota_resets_next_turn(self):
        g = make_game(seed=854)
        a = g.heroes[0]
        calls = []
        offer_and_buy(g, a, self.TID, "greater")
        for _ in range(2):
            self.assertTrue(g.play_spell(
                a, spell_probe(g, a, calls, spellcraft=True)))
        self.assertEqual(len(calls), 4)
        g.end_recruit_phase()
        self.assertTrue(g.play_spell(
            a, spell_probe(g, a, calls, spellcraft=True)))
        self.assertEqual(len(calls), 6)          # 下回合前两个重新吃配额

    def test_opponent_spellcraft_not_affected(self):
        g = make_game(seed=855)
        a, b = g.heroes
        calls = []
        offer_and_buy(g, a, self.TID, "greater")
        self.assertTrue(g.play_spell(
            b, spell_probe(g, b, calls, spellcraft=True)))
        self.assertEqual(len(calls), 1)          # owner 隔离
        self.assertEqual(a.extra_trigger_used.get("spellcraft_first", 0), 0)


# ══════════════════ BG36_MagicItem_215 Dragon's Eye ══════════════════

class TestDragonsEye(unittest.TestCase):
    TID = "BG36_MagicItem_215"

    def _play(self, g, hero, card_id, calls):
        m = g.create_minion(card_id, controller=hero)
        m.scripts = probe({
            "battlecry": staticmethod(
                lambda s, gg, c=None, **kw: calls.append(s) or None)})
        hero.add_to_hand(m)
        self.assertTrue(g.play_minion(hero, m))
        return m

    def test_dragon_battlecry_triggers_extra(self):
        g = make_game(seed=861)
        a = g.heroes[0]
        calls = []
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(a.extra_triggers["bc_times_race"], 1)
        self.assertEqual(a.extra_triggers["bc_race"], Race.DRAGON)
        self._play(g, a, DRAGON_BATTLECRY, calls)
        self.assertEqual(len(calls), 2)          # 龙战吼 +1

    def test_non_dragon_battlecry_not_affected(self):
        g = make_game(seed=862)
        a = g.heroes[0]
        calls = []
        offer_and_buy(g, a, self.TID, "greater")
        self._play(g, a, NONDRAGON_BATTLECRY, calls)
        self.assertEqual(len(calls), 1)          # 仅龙

    def test_control_without_trinket(self):
        g = make_game(seed=863)
        a = g.heroes[0]
        calls = []
        self._play(g, a, DRAGON_BATTLECRY, calls)
        self.assertEqual(len(calls), 1)

    def test_opponent_dragon_not_affected(self):
        g = make_game(seed=864)
        a, b = g.heroes
        calls = []
        offer_and_buy(g, a, self.TID, "greater")
        self._play(g, b, DRAGON_BATTLECRY, calls)
        self.assertEqual(len(calls), 1)          # owner 隔离


# ══════════════════ BG35_MagicItem_801 Sous Chef Sticker ══════════════════

class _FreePower:
    """技能探针: 0 费、每回合 1 次——让 hp_uses 与 +1 金都可精确观测。"""

    uses_per_turn = 1

    @staticmethod
    def cost_override(hero, game):
        return 0

    @staticmethod
    def hero_power(hero, game, ctx):
        return None


def make_power_game(seed: int):
    g = Game([Hero(BLACKTHORN_HERO, "A"), Hero(BLACKTHORN_HERO, "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


class TestSousChefSticker(unittest.TestCase):
    TID = "BG35_MagicItem_801"

    def test_extra_hero_power_use_and_gold(self):
        with patch.dict(REGISTRY, {BLACKTHORN_POWER: _FreePower}):
            g = make_power_game(seed=871)
            a, b = g.heroes
            offer_and_buy(g, a, self.TID, "lesser")
            self.assertEqual(a.extra_triggers["hp_uses"], 1)
            a.gold = 10
            self.assertTrue(g.use_hero_power(a))
            self.assertEqual(a.gold, 11)         # 技能后 +1 金
            self.assertTrue(g.use_hero_power(a))  # 配额给的第二次
            self.assertEqual(a.gold, 12)
            self.assertFalse(g.use_hero_power(a))  # 第三次不可用
            self.assertEqual(a.gold, 12)

    def test_control_without_trinket(self):
        with patch.dict(REGISTRY, {BLACKTHORN_POWER: _FreePower}):
            g = make_power_game(seed=872)
            a = g.heroes[0]
            a.gold = 10
            self.assertTrue(g.use_hero_power(a))
            self.assertEqual(a.gold, 10)         # 无饰品: 0 费 0 收益
            self.assertFalse(g.use_hero_power(a))  # 基线每回合 1 次

    def test_opponent_power_use_does_not_grant(self):
        with patch.dict(REGISTRY, {BLACKTHORN_POWER: _FreePower}):
            g = make_power_game(seed=873)
            a, b = g.heroes
            offer_and_buy(g, a, self.TID, "lesser")
            a.gold = 10
            b.gold = 10
            self.assertTrue(g.use_hero_power(b))
            self.assertEqual(b.gold, 10)         # 对手 0 费无收益
            self.assertEqual(a.gold, 10)         # owner 隔离: 本人不加金
            # 本人配额未被对手消耗: 自己仍可用 2 次并各 +1 金
            self.assertTrue(g.use_hero_power(a))
            self.assertTrue(g.use_hero_power(a))
            self.assertEqual(a.gold, 12)


if __name__ == "__main__":
    unittest.main()
