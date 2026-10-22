"""批次 trinkets5 行为层测试（20 张饰品）。

全部断言走真实引擎路径（真 on_bind 接线、真事件广播、真 run_combat/
check_deaths、真 upgrade_tavern、真 play_minion/play_spell、真池占返），
期望值一律由 `CardDef.num(0/1)` 或卡面文本字面量推导。

覆盖（SOP §16 空转测试判定法——每个效果类都有正对照）:
  - owner 隔离（2 英雄; 监听类卡都有对手活动不影响的断言）
  - 池占返平衡（随机获取类卡的池余量 -N）
  - 跨回合/一次性语义（Defensive Shell / Azeroth Model Globe /
    Goldenizer Supply / Stuffed Coin Purse）
  - 战斗内 Avenge 阶段守卫（Bird Feeder / Beetle Band）
  - 阈值与 CardDef.num 双向钉死
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Hit
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets5 as B5
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
MURLOC = "BG22_202"          # Tad 2/2 Murloc
UNDEAD = "BG25_008"          # Eternal Knight 4/2 Undead（无入场效果）
FODDER = "BG24_715"          # Patient Scout 1/1 无类型（has on_sell only）
BEAST = "BG31_803"           # Buzzing Vermin 1/1 Beast
MECH = "BG26_146"            # Lullabot 2/2 Mech
NAGA = "BG23_002"            # Shell Collector 4/3 Naga
PIRATE = "BG32_235"          # Surfing Sylvar 1/2 Pirate
ALL_MINION = "BG36_640"      # Gatekeeper Amalgam 6/6（All）
BATTLECRY_MINION = "BG26_135"  # Southsea Busker 3/1（战吼只得金，不动场面）
DEATHRATTLE_MINION = "BG26_148"  # Scrap Scraper 6/5（亡语入手随从，不动场面）
SPELL_TARGET = "BG28_507"    # Sacred Gift: 给随从圣盾（定向池法术）
SPELL_PLAIN = "BG28_800"     # Careful Investment: 下回合 +2 金（无定向）

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 70):
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def buy_trinket(game, hero, tid):
    """真实购买接线: create_entity + hero.trinkets + on_bind(ctx=hero)，
    与 game._offer_trinkets 的 resolve 路径一致。"""
    e = game.create_entity(tid, controller=hero)
    hero.trinkets.append(e)
    game.run_script_hook(e, "on_bind", ctx={"hero": hero})
    return e


def put(game, hero, card_id, position=None):
    m = game.create_minion(card_id, controller=hero)
    game.summon(hero, m, position)
    return m


def kill(game, victim):
    """招募期致死（Hit → check_deaths）。"""
    game.run_actions(Hit(victim, victim.health))


def kill_in_combat(game, victim):
    """战斗内致死——Avenge 只在 in_combat 计数（RULES §6.11）。"""
    prev = game.in_combat
    game.in_combat = True
    try:
        game.run_actions(Hit(victim, victim.health))
    finally:
        game.in_combat = prev


def tavern_spell(game, hero, card_id):
    """从池中取一张法术入手（占池，play_spell 结束会回池——收支平衡）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.add_to_hand(s)
    return s


def hand_minions(hero):
    return [e for e in hero.hand if isinstance(e, Minion)]


def hand_spells(hero):
    return [e for e in hero.hand if isinstance(e, Spell)]


def pool_sum(game, ids):
    return sum(game.minion_pool.available(i) for i in ids)


def race_pool_ids(race):
    # 类型身份集合（AC-3）: 双类型随从只需任一类型命中。
    return [d.id for d in get_db().pool_minions() if race in d.races]


def tier_pool_ids(tier):
    return [d.id for d in get_db().pool_minions() if d.tech_level == tier]


class TestRegistryState(unittest.TestCase):
    """注册面 + 文本/数据一致性（结构性，与钩子无关）。"""

    IMPLEMENTED = (
        "BG30_MagicItem_931", "BG30_MagicItem_713", "BG35_MagicItem_302",
        "BG32_MagicItem_858", "BG35_MagicItem_815", "BG32_MagicItem_304",
        "BG36_MagicItem_220", "BG32_MagicItem_864", "BG32_MagicItem_860",
        "BG35_MagicItem_711", "BG36_MagicItem_203", "BG32_MagicItem_862",
        "BG36_MagicItem_811", "BG35_MagicItem_871", "BG32_MagicItem_893",
        "BG30_MagicItem_422", "BG30_MagicItem_426", "BG30_MagicItem_425",
        "BG30_MagicItem_435", "BG35_MagicItem_814",
    )

    def test_all_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)
        self.assertEqual(len(self.IMPLEMENTED), 20)

    def test_class_binding(self):
        self.assertIs(REGISTRY["BG30_MagicItem_931"], B5.LuckyTabbyScript)
        self.assertIs(REGISTRY["BG30_MagicItem_713"], B5.BleedingHeartScript)
        self.assertIs(REGISTRY["BG35_MagicItem_302"],
                      B5.StormcoilStickerScript)
        self.assertIs(REGISTRY["BG32_MagicItem_864"], B5.BirdFeederScript)
        self.assertIs(REGISTRY["BG32_MagicItem_860"], B5.BeetleBandScript)
        self.assertIs(REGISTRY["BG35_MagicItem_711"],
                      B5.ProtectiveRingScript)
        self.assertIs(REGISTRY["BG30_MagicItem_426"],
                      B5.ColorfulCompassScript)
        self.assertIs(REGISTRY["BG35_MagicItem_814"],
                      B5.StuffedCoinPurseScript)

    def test_avenge_thresholds_match_text(self):
        db = get_db()
        # 文本 "Avenge (N)" 与类属性双向钉死
        self.assertIn("Avenge (2)", db.get("BG32_MagicItem_864").text)
        self.assertEqual(B5.BirdFeederScript.avenge_threshold, 2)
        self.assertIn("Avenge (5)", db.get("BG32_MagicItem_860").text)
        self.assertEqual(B5.BeetleBandScript.avenge_threshold, 5)

    def test_death_counter_thresholds_are_num_params(self):
        db = get_db()
        for tid in ("BG30_MagicItem_931", "BG30_MagicItem_713",
                    "BG35_MagicItem_302"):
            d = db.get(tid)
            self.assertIn("{1} friendly minions die", d.text)
            self.assertEqual(d.num(0), d.num(1))

    def test_beetle_token_matches_num_params(self):
        db = get_db()
        d = db.get("BG32_MagicItem_860")
        token = db.get(B5.BEETLE_TOKEN)
        self.assertIsNotNone(token, "Beetle token 数据链断裂")
        self.assertEqual(token.race, Race.BEAST)
        self.assertEqual((token.atk, token.health),
                         (d.num(0), d.num(1)))

    def test_colorful_compass_param_is_naga_race(self):
        d = get_db().get("BG30_MagicItem_426")
        # 文本 "{0}" 由参数替换为种族名; CardDef 参数 == Race 枚举值
        self.assertIn("{0}", d.text)
        self.assertEqual(d.num(0), int(Race.NAGA))

    def test_goldenizer_chain_and_pool_status(self):
        db = get_db()
        d = db.get("BG30_MagicItem_435")
        token = db.by_dbf(d.evolution_card_id)
        self.assertIsNotNone(token)
        self.assertIs(token, db.get("BG26_813t"))
        self.assertFalse(token.is_pool_spell)


# ══════════════════ BG30_MagicItem_931 Lucky Tabby ══════════════════

class TestLuckyTabby(unittest.TestCase):
    TID = "BG30_MagicItem_931"

    def test_threshold_deaths_grant_random_beast(self):
        g = make_game(seed=101)
        a, b = g.heroes
        threshold = get_db().get(self.TID).num(1)
        buy_trinket(g, a, self.TID)
        beast_ids = race_pool_ids(Race.BEAST)
        before = pool_sum(g, beast_ids)
        for _ in range(threshold - 1):
            kill(g, put(g, a, FODDER))
        self.assertEqual(hand_minions(a), [])
        self.assertEqual(pool_sum(g, beast_ids), before)
        kill(g, put(g, a, FODDER))
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 1)
        self.assertIn(drawn[0].race, (Race.BEAST, Race.ALL))
        self.assertEqual(pool_sum(g, beast_ids), before - 1)
        # 计数清零: 再死 threshold-1 次不再发放
        for _ in range(threshold - 1):
            kill(g, put(g, a, FODDER))
        self.assertEqual(len(hand_minions(a)), 1)

    def test_opponent_deaths_do_not_count(self):
        g = make_game(seed=102)
        a, b = g.heroes
        threshold = get_db().get(self.TID).num(1)
        buy_trinket(g, a, self.TID)
        before = pool_sum(g, race_pool_ids(Race.BEAST))
        for _ in range(threshold):
            kill(g, put(g, b, FODDER))
        self.assertEqual(hand_minions(a), [])
        self.assertEqual(pool_sum(g, race_pool_ids(Race.BEAST)), before)


# ══════════════════ BG30_MagicItem_713 Bleeding Heart ══════════════════

class TestBleedingHeart(unittest.TestCase):
    TID = "BG30_MagicItem_713"

    def test_threshold_deaths_grant_random_undead(self):
        g = make_game(seed=111)
        a, b = g.heroes
        threshold = get_db().get(self.TID).num(1)
        buy_trinket(g, a, self.TID)
        undead_ids = race_pool_ids(Race.UNDEAD)
        before = pool_sum(g, undead_ids)
        for _ in range(threshold - 1):
            kill(g, put(g, a, FODDER))
        self.assertEqual(hand_minions(a), [])
        kill(g, put(g, a, FODDER))
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 1)
        self.assertIn(drawn[0].race, (Race.UNDEAD, Race.ALL))
        self.assertEqual(pool_sum(g, undead_ids), before - 1)

    def test_opponent_deaths_do_not_count(self):
        g = make_game(seed=112)
        a, b = g.heroes
        threshold = get_db().get(self.TID).num(1)
        buy_trinket(g, a, self.TID)
        for _ in range(threshold):
            kill(g, put(g, b, FODDER))
        self.assertEqual(hand_minions(a), [])


# ══════════════════ BG35_MagicItem_302 Stormcoil Sticker ══════════════════

class TestStormcoilSticker(unittest.TestCase):
    TID = "BG35_MagicItem_302"

    def test_threshold_deaths_grant_random_mech(self):
        g = make_game(seed=121)
        a, b = g.heroes
        threshold = get_db().get(self.TID).num(1)
        buy_trinket(g, a, self.TID)
        mech_ids = race_pool_ids(Race.MECH)
        before = pool_sum(g, mech_ids)
        for _ in range(threshold - 1):
            kill(g, put(g, a, FODDER))
        self.assertEqual(hand_minions(a), [])
        kill(g, put(g, a, FODDER))
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 1)
        self.assertIn(drawn[0].race, (Race.MECH, Race.ALL))
        self.assertEqual(pool_sum(g, mech_ids), before - 1)

    def test_opponent_deaths_do_not_count(self):
        g = make_game(seed=122)
        a, b = g.heroes
        threshold = get_db().get(self.TID).num(1)
        buy_trinket(g, a, self.TID)
        for _ in range(threshold):
            kill(g, put(g, b, FODDER))
        self.assertEqual(hand_minions(a), [])


# ═══════════════ BG32_MagicItem_858 Explorer's Binoculars ═══════════════

class TestExplorersBinoculars(unittest.TestCase):
    TID = "BG32_MagicItem_858"

    def test_gets_three_tier4_minions(self):
        g = make_game(seed=131)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 3)
        for m in drawn:
            self.assertEqual(m.tech_level, 4)
        # 对手不受影响
        self.assertEqual(hand_minions(b), [])

    def test_pool_reduced_by_three(self):
        g = make_game(seed=132)
        a = g.heroes[0]
        before = pool_sum(g, tier_pool_ids(4))
        buy_trinket(g, a, self.TID)
        self.assertEqual(pool_sum(g, tier_pool_ids(4)), before - 3)


# ══════════════════ BG35_MagicItem_815 Magician's Top Hat ══════════════

class TestMagiciansTopHat(unittest.TestCase):
    TID = "BG35_MagicItem_815"

    def test_two_minions_each_from_tiers_1_2_3(self):
        g = make_game(seed=141)
        a, b = g.heroes
        before = {t: pool_sum(g, tier_pool_ids(t)) for t in (1, 2, 3)}
        buy_trinket(g, a, self.TID)
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 6)
        for t in (1, 2, 3):
            self.assertEqual(sum(1 for m in drawn if m.tech_level == t), 2)
            self.assertEqual(pool_sum(g, tier_pool_ids(t)), before[t] - 2)
        self.assertEqual(hand_minions(b), [])


# ══════════════════ BG32_MagicItem_304 Horn of Summoning ══════════════════

class TestHornOfSummoning(unittest.TestCase):
    TID = "BG32_MagicItem_304"

    def test_gets_six_distinct_tier1_minions(self):
        g = make_game(seed=151)
        a, b = g.heroes
        before = pool_sum(g, tier_pool_ids(1))
        buy_trinket(g, a, self.TID)
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 6)
        ids = [m.card_id for m in drawn]
        self.assertEqual(len(set(ids)), 6)          # "different"
        for m in drawn:
            self.assertEqual(m.tech_level, 1)
        self.assertEqual(pool_sum(g, tier_pool_ids(1)), before - 6)
        self.assertEqual(hand_minions(b), [])

    def test_pool_shortage_gives_fewer(self):
        g = make_game(seed=152)
        a = g.heroes[0]
        # 抽干除 2 个 id 外的全部 Tier 1 池
        keep = tier_pool_ids(1)[:2]
        for cid in tier_pool_ids(1):
            if cid in keep:
                continue
            while g.minion_pool.available(cid) > 0:
                g.minion_pool.acquire(cid)
        buy_trinket(g, a, self.TID)
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 2)
        self.assertEqual({m.card_id for m in drawn}, set(keep))


# ══════════════════ BG36_MagicItem_220 Glowing Crystal ══════════════════

class TestGlowingCrystal(unittest.TestCase):
    TID = "BG36_MagicItem_220"

    def test_gold_per_different_type(self):
        g = make_game(seed=161)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        put(g, a, MURLOC)
        put(g, a, UNDEAD)
        before_a, before_b = a.gold, b.gold
        g.run_script_hook(a.trinkets[0], "start_of_turn")
        self.assertEqual(a.gold, before_a + 2)
        self.assertEqual(b.gold, before_b)           # owner 隔离

    def test_all_type_minion_counts_every_race(self):
        g = make_game(seed=162)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        put(g, a, ALL_MINION)
        before = a.gold
        g.run_script_hook(a.trinkets[0], "start_of_turn")
        self.assertEqual(a.gold, before + len(B5._ALL_MINION_RACES))

    def test_no_type_board_gives_nothing(self):
        g = make_game(seed=163)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        put(g, a, FODDER)                            # 无类型
        before = a.gold
        self.assertIsNone(
            g.run_script_hook(a.trinkets[0], "start_of_turn"))
        self.assertEqual(a.gold, before)


# ══════════════════ BG32_MagicItem_864 Bird Feeder ══════════════════

class TestBirdFeeder(unittest.TestCase):
    TID = "BG32_MagicItem_864"

    def test_two_combat_deaths_buff_all_minions(self):
        g = make_game(seed=171)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        tank = put(g, a, MURLOC)                     # 2/2
        kill_in_combat(g, put(g, a, FODDER))
        self.assertEqual((tank.atk, tank.max_health), (2, 2))  # 1 死不触发
        kill_in_combat(g, put(g, a, FODDER))
        self.assertEqual((tank.atk, tank.max_health), (3, 3))

    def test_recruit_phase_death_does_not_trigger(self):
        g = make_game(seed=172)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        tank = put(g, a, MURLOC)
        kill(g, put(g, a, FODDER))
        kill(g, put(g, a, FODDER))
        self.assertEqual((tank.atk, tank.max_health), (2, 2))

    def test_opponent_deaths_do_not_trigger(self):
        g = make_game(seed=173)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        tank = put(g, a, MURLOC)
        for _ in range(2):
            kill_in_combat(g, put(g, b, FODDER))
        self.assertEqual((tank.atk, tank.max_health), (2, 2))


# ══════════════════ BG32_MagicItem_860 Beetle Band ══════════════════

class TestBeetleBand(unittest.TestCase):
    TID = "BG32_MagicItem_860"

    def test_five_combat_deaths_summon_taunt_beetle(self):
        g = make_game(seed=181)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        for _ in range(4):
            kill_in_combat(g, put(g, a, FODDER))
        beetles = [m for m in a.board if m.card_id == B5.BEETLE_TOKEN]
        self.assertEqual(beetles, [])
        kill_in_combat(g, put(g, a, FODDER))
        beetles = [m for m in a.board if m.card_id == B5.BEETLE_TOKEN]
        self.assertEqual(len(beetles), 1)
        self.assertTrue(beetles[0].has(GameTag.TAUNT))
        d = get_db().get(self.TID)
        self.assertEqual((beetles[0].atk, beetles[0].max_health),
                         (d.num(0), d.num(1)))

    def test_recruit_phase_deaths_do_not_summon(self):
        g = make_game(seed=182)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        for _ in range(5):
            kill(g, put(g, a, FODDER))
        self.assertEqual(
            [m for m in a.board if m.card_id == B5.BEETLE_TOKEN], [])

    def test_opponent_deaths_do_not_summon(self):
        g = make_game(seed=183)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        for _ in range(5):
            kill_in_combat(g, put(g, b, FODDER))
        self.assertEqual(
            [m for m in a.board if m.card_id == B5.BEETLE_TOKEN], [])


# ══════════════════ BG35_MagicItem_711 Protective Ring ══════════════════

class TestProtectiveRing(unittest.TestCase):
    TID = "BG35_MagicItem_711"

    def test_num_random_pirates_gain_divine_shield(self):
        g = make_game(seed=191)
        a, b = g.heroes
        n = get_db().get(self.TID).num(0)
        buy_trinket(g, a, self.TID)
        pirates = [put(g, a, PIRATE) for _ in range(5)]
        cat = put(g, a, MURLOC)
        b_pirate = put(g, b, PIRATE)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        granted = [m for m in pirates if m.has(GameTag.DIVINE_SHIELD)]
        self.assertEqual(len(granted), min(n, len(pirates)))
        self.assertFalse(cat.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(b_pirate.has(GameTag.DIVINE_SHIELD))

    def test_fewer_pirates_than_num_all_gain(self):
        g = make_game(seed=192)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        p1 = put(g, a, PIRATE)
        p2 = put(g, a, PIRATE)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertTrue(p1.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(p2.has(GameTag.DIVINE_SHIELD))

    def test_no_pirate_whiffs(self):
        g = make_game(seed=193)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        put(g, a, MURLOC)
        self.assertIsNone(
            g.run_script_hook(a.trinkets[0], "start_of_combat"))


# ══════════════════ BG36_MagicItem_203 Dragon Skull ══════════════════

class TestDragonSkull(unittest.TestCase):
    TID = "BG36_MagicItem_203"

    def _play(self, g, hero, card_id):
        m = g.create_minion(card_id, controller=hero)
        hero.add_to_hand(m)
        self.assertTrue(g.play_minion(hero, m))
        return m

    def test_battlecry_buffs_left_and_right_most(self):
        g = make_game(seed=201)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        left = put(g, a, MURLOC)                    # 2/2
        mid = put(g, a, UNDEAD)                     # 4/2
        played = self._play(g, a, BATTLECRY_MINION)  # 3/1 → 最右
        self.assertEqual((left.atk, left.max_health),
                         (2 + d.num(0), 2 + d.num(1)))
        self.assertEqual((played.atk, played.max_health),
                         (3 + d.num(0), 1 + d.num(1)))
        self.assertEqual((mid.atk, mid.max_health), (4, 2))

    def test_single_minion_buffed_once(self):
        g = make_game(seed=202)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        played = self._play(g, a, BATTLECRY_MINION)
        self.assertEqual((played.atk, played.max_health),
                         (3 + d.num(0), 1 + d.num(1)))

    def test_opponent_battlecry_does_not_trigger(self):
        g = make_game(seed=203)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        left = put(g, a, MURLOC)
        self._play(g, b, BATTLECRY_MINION)
        self.assertEqual((left.atk, left.max_health), (2, 2))


# ══════════════════ BG32_MagicItem_862 Unholy Sanctum ══════════════════

class TestUnholySanctum(unittest.TestCase):
    TID = "BG32_MagicItem_862"

    def test_deathrattle_buffs_right_most(self):
        g = make_game(seed=211)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        left = put(g, a, MURLOC)                    # 2/2
        dr = put(g, a, DEATHRATTLE_MINION)          # 6/5（中间）
        right = put(g, a, BEAST)                    # 1/1
        kill(g, dr)
        self.assertEqual((right.atk, right.max_health), (3, 3))
        self.assertEqual((left.atk, left.max_health), (2, 2))

    def test_opponent_deathrattle_does_not_trigger(self):
        g = make_game(seed=212)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        left = put(g, a, MURLOC)
        dr_b = put(g, b, DEATHRATTLE_MINION)
        kill(g, dr_b)
        self.assertEqual((left.atk, left.max_health), (2, 2))

    def test_empty_board_after_death_whiffs(self):
        g = make_game(seed=213)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        dr = put(g, a, DEATHRATTLE_MINION)
        kill(g, dr)
        self.assertEqual(a.board, [])


# ══════════════════ BG36_MagicItem_811 Defensive Shell ══════════════════

class TestDefensiveShell(unittest.TestCase):
    TID = "BG36_MagicItem_811"

    def _play(self, g, hero, card_id):
        m = g.create_minion(card_id, controller=hero)
        hero.add_to_hand(m)
        self.assertTrue(g.play_minion(hero, m))
        return m

    def test_only_first_minion_each_turn_gains_ds(self):
        g = make_game(seed=221)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        first = self._play(g, a, MURLOC)
        second = self._play(g, a, UNDEAD)
        self.assertTrue(first.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(second.has(GameTag.DIVINE_SHIELD))

    def test_next_turn_first_minion_gains_ds_again(self):
        g = make_game(seed=222)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        self._play(g, a, MURLOC)
        g.end_recruit_phase()               # 真实推进回合
        third = self._play(g, a, UNDEAD)
        self.assertTrue(third.has(GameTag.DIVINE_SHIELD))

    def test_opponent_play_does_not_trigger(self):
        g = make_game(seed=223)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        m = self._play(g, b, MURLOC)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))


# ══════════════════ BG35_MagicItem_871 Mama Bear Sticker ══════════════════

class TestMamaBearSticker(unittest.TestCase):
    TID = "BG35_MagicItem_871"

    def test_summoned_beast_gets_stats(self):
        g = make_game(seed=231)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        beast = put(g, a, BEAST)                    # 1/1
        cat = put(g, a, MURLOC)                     # 非野兽
        self.assertEqual((beast.atk, beast.max_health),
                         (1 + d.num(0), 1 + d.num(1)))
        self.assertEqual((cat.atk, cat.max_health), (2, 2))

    def test_future_beast_summon_covered(self):
        g = make_game(seed=232)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        later = put(g, a, BEAST)
        self.assertEqual((later.atk, later.max_health),
                         (1 + d.num(0), 1 + d.num(1)))

    def test_opponent_summon_does_not_trigger(self):
        g = make_game(seed=233)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        beast_b = put(g, b, BEAST)
        self.assertEqual((beast_b.atk, beast_b.max_health), (1, 1))


# ══════════════════ BG32_MagicItem_893 Bluegill Flippers ══════════════════

class TestBluegillFlippers(unittest.TestCase):
    TID = "BG32_MagicItem_893"

    def test_tavern_spell_buffs_leftmost_hand_and_warband(self):
        g = make_game(seed=241)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        h1 = g.create_minion(MURLOC, controller=a)
        a.add_to_hand(h1)
        h2 = g.create_minion(UNDEAD, controller=a)
        a.add_to_hand(h2)
        b1 = put(g, a, MURLOC)
        b2 = put(g, a, UNDEAD)
        spell = tavern_spell(g, a, SPELL_PLAIN)
        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual((h1.atk, h1.max_health),
                         (2 + d.num(0), 2 + d.num(1)))
        self.assertEqual((b1.atk, b1.max_health),
                         (2 + d.num(0), 2 + d.num(1)))
        self.assertEqual((h2.atk, h2.max_health), (4, 2))
        self.assertEqual((b2.atk, b2.max_health), (4, 2))

    def test_empty_hand_only_buffs_warband(self):
        g = make_game(seed=242)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        b1 = put(g, a, MURLOC)
        spell = tavern_spell(g, a, SPELL_PLAIN)
        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual((b1.atk, b1.max_health),
                         (2 + d.num(0), 2 + d.num(1)))

    def test_opponent_cast_does_not_trigger(self):
        g = make_game(seed=243)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        b1 = put(g, a, MURLOC)
        spell = tavern_spell(g, b, SPELL_PLAIN)
        self.assertTrue(g.play_spell(b, spell))
        self.assertEqual((b1.atk, b1.max_health), (2, 2))


# ══════════════════ BG30_MagicItem_422 Lorewalker Scroll ══════════════════

class TestLorewalkerScroll(unittest.TestCase):
    TID = "BG30_MagicItem_422"

    def test_spell_on_minion_buffs_target(self):
        g = make_game(seed=251)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        target = put(g, a, MURLOC)                  # 2/2
        spell = tavern_spell(g, a, SPELL_TARGET)
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertTrue(target.has(GameTag.DIVINE_SHIELD))   # 法术确实结算
        self.assertEqual((target.atk, target.max_health),
                         (2 + d.num(0), 2 + d.num(1)))

    def test_non_targeted_spell_does_not_trigger(self):
        g = make_game(seed=252)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        target = put(g, a, MURLOC)
        spell = tavern_spell(g, a, SPELL_PLAIN)
        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual((target.atk, target.max_health), (2, 2))

    def test_opponent_cast_does_not_trigger(self):
        g = make_game(seed=253)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        target = put(g, a, MURLOC)
        b_target = put(g, b, MURLOC)
        spell = tavern_spell(g, b, SPELL_TARGET)
        self.assertTrue(g.play_spell(b, spell, target=b_target))
        self.assertEqual((target.atk, target.max_health), (2, 2))


# ══════════════════ BG30_MagicItem_426 Colorful Compass ══════════════════

class TestColorfulCompass(unittest.TestCase):
    TID = "BG30_MagicItem_426"

    def test_bind_and_each_turn_get_random_naga(self):
        g = make_game(seed=261)
        a, b = g.heroes
        naga_ids = race_pool_ids(Race.NAGA)
        before = pool_sum(g, naga_ids)
        buy_trinket(g, a, self.TID)
        first = hand_minions(a)
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0].has_race(Race.NAGA))
        g.run_script_hook(a.trinkets[0], "start_of_turn")
        drawn = hand_minions(a)
        self.assertEqual(len(drawn), 2)
        for m in drawn:
            self.assertTrue(m.has_race(Race.NAGA))
        self.assertEqual(pool_sum(g, naga_ids), before - 2)
        self.assertEqual(hand_minions(b), [])

    def test_opponent_hand_unaffected(self):
        g = make_game(seed=262)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        self.assertEqual(hand_minions(b), [])


# ══════════════════ BG30_MagicItem_425 Azeroth Model Globe ══════════════

class TestAzerothModelGlobe(unittest.TestCase):
    TID = "BG30_MagicItem_425"

    def _turn_start(self, g, hero):
        g.events.fire(g, "turn_start", turn=g.turn, hero=hero)

    def test_every_two_turns_gold_and_discover(self):
        g = make_game(seed=271)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        before = a.gold
        self._turn_start(g, a)                      # 第 1 个回合: 无效果
        self.assertEqual(a.gold, before)
        self.assertEqual(g.pending_choices, [])
        self._turn_start(g, a)                      # 第 2 个回合: 触发
        self.assertEqual(a.gold, before + d.num(1))
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices[0]
        self.assertEqual(choice.owner, a)
        self.assertEqual(choice.kind, "discover_minion")
        self.assertTrue(choice.options)
        for cid in choice.options:
            self.assertEqual(get_db().get(cid).tech_level, 6)

    def test_opponent_turn_start_does_not_trigger(self):
        g = make_game(seed=272)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        before = a.gold
        self._turn_start(g, b)
        self._turn_start(g, b)
        self.assertEqual(a.gold, before)
        self.assertEqual(g.pending_choices, [])


# ══════════════════ BG30_MagicItem_435 Goldenizer Supply ══════════════════

class TestGoldenizerSupply(unittest.TestCase):
    TID = "BG30_MagicItem_435"

    def test_every_three_turns_get_goldenizer(self):
        g = make_game(seed=281)
        a, b = g.heroes
        d = get_db().get(self.TID)
        every = d.num(1)
        buy_trinket(g, a, self.TID)
        for _ in range(every - 1):
            g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(hand_spells(a), [])
        g.events.fire(g, "turn_end", turn=g.turn)
        spells = hand_spells(a)
        self.assertEqual(len(spells), 1)
        token = get_db().by_dbf(d.evolution_card_id)
        self.assertEqual(spells[0].card_id, token.id)
        self.assertFalse(get_db().get(spells[0].card_id).is_pool_spell)
        self.assertEqual(hand_spells(b), [])
        # 计数清零: 再满 every-1 次不发放
        for _ in range(every - 1):
            g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(len(hand_spells(a)), 1)


# ══════════════════ BG35_MagicItem_814 Stuffed Coin Purse ══════════════════

class TestStuffedCoinPurse(unittest.TestCase):
    TID = "BG35_MagicItem_814"

    def test_reaching_tier_six_grants_gold_once(self):
        g = make_game(seed=291)
        a, b = g.heroes
        d = get_db().get(self.TID)
        reach, gold = d.num(0), d.num(1)
        buy_trinket(g, a, self.TID)
        a.gold = 200
        # 升到 reach-1: 不发放
        while a.tavern_tier < reach - 1:
            self.assertTrue(g.upgrade_tavern(a))
        before = a.gold
        cost = max(0, a.upgrade_cost + a.get(GameTag.UPGRADE_COST_MOD, 0))
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.tavern_tier, reach)
        self.assertEqual(a.gold, before - cost + gold)
        # 一次性: 再次广播到达事件不重复发放
        now = a.gold
        g.events.fire(g, "tavern_upgraded", hero=a, tier=reach)
        self.assertEqual(a.gold, now)

    def test_opponent_upgrade_does_not_grant(self):
        g = make_game(seed=292)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        b.gold = 200
        before_a = a.gold
        while b.tavern_tier < get_db().get(self.TID).num(0):
            self.assertTrue(g.upgrade_tavern(b))
        self.assertEqual(a.gold, before_a)


if __name__ == "__main__":
    unittest.main()
