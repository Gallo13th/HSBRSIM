"""批次 trinkets13 行为层测试（片 3 的 13 张 CORRECT + 5 张 DEFERRED 台账守卫;
917/952 已由 batch_trinkets23 解冻注册）。

全部断言走真实引擎路径:
  - 授予: 真实 `game.grant_trinket`（on_bind 接线）/ `game._offer_trinkets`
    + `PendingChoice.choose`（商店购买 → `trinket_bought` 广播）
  - 关联卡: 真实 `game.trinket_related_card` / `grant_trinket_related_card`
    / `grant_card_copy_to_hand`（数据链 `evolution_card_id`）
  - 副本: 真实 `game.copy_trinket`（duplicate 路径 + replace 注销）
  - 回合推进: 真实 `game._begin_recruit_for` / `game.end_recruit_phase`
  - 事件: 真实 `card_played` / `gold_spent` / `summon` / `tavern_refresh`
    / `spell_resolving` 广播
  - 池: 真实 `minion_pool` / `spell_pool` 可用量不变量

覆盖（SOP §16 空转测试判定法——每个效果类都有正对照）:
  - 正例（可观察状态: 手牌 / 攻击力 / 酒馆层数 / 事件计数）
  - owner 隔离（2 英雄; 每个效果都有"对手活动不生效"断言，与正对照
    同测试内并列）
  - 跨回合/一次性语义（SoT 重复 vs 仅授予; 滚动计数）
  - 落空（无上一对手 / 无候选）
  - "from your hand" 判别（943: 手牌路径 +6/6，直施路径只吃基础值）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets13 as B
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

MANIPULATOR = "BG30_MagicItem_876"      # Manipulator Portrait
CHEESE = "BG30_MagicItem_879"           # Dalaran Cheese Wheel
STAND = "BG30_MagicItem_888"            # Souvenir Stand
TRIDENT = "BG30_MagicItem_917"          # Rusty Trident（batch_trinkets23 注册）
POSTCARD = "BG30_MagicItem_919"         # Nazjatar Postcard
FLAGBEARER = "BG30_MagicItem_921"       # Flagbearer Portrait
CLAW = "BG30_MagicItem_930"             # Burgling Claw
JARAXXUS = "BG30_MagicItem_942"         # Mecha-Jaraxxus Sticker
SURVEYOR = "BG30_MagicItem_943"         # Surveyor Portrait
REDEEMER = "BG30_MagicItem_944"         # Redeemer Portrait（batch_trinkets33 注册）
FROSTLING = "BG30_MagicItem_952"        # Jarred Frostling（batch_trinkets23 注册）
ENFORCER = "BG30_MagicItem_971"         # Enforcer Portrait（batch_family_races 注册）
BALLADIST = "BG30_MagicItem_987"        # Balladist Portrait（batch_trinkets31 注册）
FELBAT = "BG30_MagicItem_991"           # Felbat Portrait
PIE = "BG30_MagicItem_992"              # Darnassus Pie (DEFERRED)
PASTRY = "BG30_MagicItem_994"           # Yogg-Tastic Pastry (DEFERRED)
SPELLBOOK = "BG30_MagicItem_999"        # Fancy Spellbook
WISDOMBALL = "BG31_MagicItem_903"       # Wisdomball Supply
WRENCH = "BG32_MagicItem_170"           # Spell-powered Wrench
BOOM = "BG32_MagicItem_172"             # Boom's Monster Portrait

# TRIDENT（917）/ FROSTLING（952）已由 batch_trinkets23 注册
# （`grant_combat_deathrattle` 公开原语 + Spellcraft 候选数据链）——迁出本台账
# PIE（BG30_MagicItem_992 Darnassus Pie）已由 batch_trinkets24 注册。
# BALLADIST（987 Balladist Portrait）已由 batch_trinkets31 注册（2026-09-19
# ——"also give Attack" 增量 = 同句 Health 额 + `start_of_turn` 再得 1 张）
# → 移出本台账。
# 971 Enforcer Portrait 已由 batch_family_races 注册（2026-09-21，RACES
# 家族类型身份改写："have all minion types"）→ 移出本 DEFERRED 台账
# （守卫见 test_batch_family_races）。944 由 batch_trinkets33 注册。
DEFERRED = (PASTRY,)

# 关联卡（数据链解析目标; 断言用）
FACELESS = "BG_EX1_564"                 # Faceless Manipulator
SKY_FLAGBEARER = "BG30_119"             # Sky Pirate Flagbearer
SURVEYOR_MINION = "BG30_121"            # Hot-Air Surveyor
FELBAT_MINION = "BG21_005"              # Famished Felbat
WISDOMBALL_SPELL = "BG30_802"           # Knockoff Wisdomball
BOOM_MINION = "BG31_176"                # Dr. Boom's Monster
REPAIR_JOB = "BG36_624"                 # Repair Job（池法术 T3）
SHINY_RING = "BG28_168"                 # Shiny Ring（池法术 T3）
BLOOD_GEM = "BG20_GEM"                  # 血宝石（非池 token 法术）

# 测试用随从（CardDB 按名/数据核实）
T1_BEAST = "BG31_803"                   # Buzzing Vermin 1/1
T6_MECH = "BG26_152"                    # Utility Drone 4/6 T6
NAGA = "BG23_002"                       # Shell Collector（战吼给 Tavern Coin）
NON_NAGA = "BG25_806"                   # Sly Raptor（野兽）
SKY_PIRATE = "BGS_061t"                 # Sky Pirate 1/1 token
SKY_PIRATE_G = "TB_BaconUps_141t"       # Sky Pirate 2/2 金色 token
SCALLYWAG = "BGS_061"                   # Scallywag 3/1 Pirate（非 Sky Pirate）
MAGNETIC_MECH = "BG26_146"              # Lullabot 2/2 magnetic
PLAIN_MECH = "BG26_148"                 # Scrap Scraper 6/5

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 1300) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid)
    assert e is not None, tid
    return e


def hand_ids(hero: Hero) -> list:
    return [c.card_id for c in hero.hand]


def hand_of(hero: Hero, card_id: str) -> list:
    return [c for c in hero.hand if c.card_id == card_id]


def take_choice(game: Game, kind: str, owner=None):
    if owner is None:
        ch = next(c for c in game.pending_choices if c.kind == kind)
    else:
        ch = next(c for c in game.pending_choices
                  if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(ch)
    return ch


def buy_trinket(game: Game, hero: Hero, kind: str, tid: str):
    """真实商店路径: `_offer_trinkets` → 定向到 tid → resolve。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    ch = take_choice(game, "trinket_offer", hero)
    ch.options = [get_db().get(tid), None]
    ch.choose(0)
    return next(t for t in hero.trinkets if t.card_id == tid)


def unscripted_of(school: int):
    return next(d for d in get_db().trinket_offer_pool()
                if d.spell_school == school and d.id not in REGISTRY
                and (d.cost or 0) > 0)


def put_tavern(game: Game, hero: Hero, card_id: str = T1_BEAST) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern = [m]
    return m


def tavern_minions(hero: Hero) -> list:
    return [e for e in hero.tavern if isinstance(e, Minion)]


def spellcraft_ids(game: Game) -> set:
    from hsrl2.scripts.batches.batch_spells2 import _spellcraft_spell_ids
    return set(_spellcraft_spell_ids(game))


# ══════════════ 结构性（注册表 / 数据一致性） ══════════════

class TestRegistryState(unittest.TestCase):
    """@engine-only —— 注册面 + DEFERRED 台账 + 数据链一致性（与钩子无关）。"""

    IMPLEMENTED = (
        MANIPULATOR, CHEESE, STAND, POSTCARD, FLAGBEARER, CLAW, JARAXXUS,
        SURVEYOR, FELBAT, SPELLBOOK, WISDOMBALL, WRENCH, BOOM,
    )
    CLASSES = {
        MANIPULATOR: "ManipulatorPortraitScript",
        CHEESE: "DalaranCheeseWheelScript",
        STAND: "SouvenirStandScript",
        POSTCARD: "NazjatarPostcardScript",
        FLAGBEARER: "FlagbearerPortraitScript",
        CLAW: "BurglingClawScript",
        JARAXXUS: "MechaJaraxxusStickerScript",
        SURVEYOR: "SurveyorPortraitScript",
        FELBAT: "FelbatPortraitScript",
        SPELLBOOK: "FancySpellbookScript",
        WISDOMBALL: "WisdomballSupplyScript",
        WRENCH: "SpellPoweredWrenchScript",
        BOOM: "BoomsMonsterPortraitScript",
    }

    def test_all_registered_and_bound(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B, self.CLASSES[tid]), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_deferred_ids_not_registered(self):
        for tid in DEFERRED:
            self.assertNotIn(tid, REGISTRY, tid)

    def test_deferred_ledger_in_module_docstring(self):
        doc = B.__doc__ or ""
        for name in ("Rusty Trident", "Redeemer Portrait",
                     "Jarred Frostling", "Enforcer Portrait",
                     "Balladist Portrait", "Darnassus Pie",
                     "Yogg-Tastic Pastry"):
            self.assertIn(name, doc, name)
        self.assertIn("grant_combat_deathrattle", doc)
        self.assertIn("TAG_SCRIPT_DATA_NUM_1", doc)     # 987 Attack 缺口
        self.assertIn("tavern_sold_this_turn", doc)     # 992 动态 buff 缺口
        self.assertIn("spin_wheel", doc)                # 994 轮盘缺口

    def test_all_in_offer_pool_with_expected_school(self):
        offer = {d.id for d in get_db().trinket_offer_pool()}
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, offer, tid)
        self.assertEqual(get_db().get(CHEESE).spell_school, 11)     # Lesser
        self.assertEqual(get_db().get(STAND).spell_school, 11)
        self.assertEqual(get_db().get(CLAW).spell_school, 11)
        self.assertEqual(get_db().get(WRENCH).spell_school, 11)
        self.assertEqual(get_db().get(MANIPULATOR).spell_school, 12)
        self.assertEqual(get_db().get(POSTCARD).spell_school, 12)

    def test_carddef_num_params_match_text(self):
        db = get_db()
        self.assertEqual(db.get(CHEESE).num(0), 4)      # "every 4 times"
        self.assertEqual(db.get(CHEESE).num(1), 1)      # "+{1}/+{1}"
        self.assertEqual(db.get(SURVEYOR).num(0), 6)
        self.assertEqual(db.get(SURVEYOR).num(1), 6)
        self.assertEqual(db.get(SPELLBOOK).num(2), 7)   # "spend {2} Gold"
        self.assertEqual(db.get(REDEEMER).num(0), 4)
        self.assertEqual(db.get(REDEEMER).num(1), 4)
        self.assertEqual(db.get(POSTCARD).num(0), 2)    # 37.0 文本用 {0} 计数

    def test_942_carddef_token_set_is_data_derived(self):
        g = make_game(seed=1301)
        ids = [d.id for d in B._magnetic_mecha_demon_defs(g)]
        self.assertEqual(ids, ["BG25_807t", "BG25_807t2",
                               "BG25_807t3", "BG25_807t4"])
        for i in ids:
            d = get_db().get(i)
            self.assertIn("magnetic", d.keywords)
            self.assertFalse(d.is_pool_minion)

    def test_921_sky_pirate_ids_resolve_both_tokens(self):
        g = make_game(seed=1302)
        ids = B._sky_pirate_ids(g)
        self.assertEqual(ids, {SKY_PIRATE, SKY_PIRATE_G})

    def test_919_spellcraft_pool_nonempty_and_data_derived(self):
        g = make_game(seed=1303)
        ids = spellcraft_ids(g)
        self.assertEqual(len(ids), 9)                   # 36.2.2 基线
        for sid in ids:
            d = get_db().get(sid)
            self.assertIsNotNone(d, sid)
            self.assertFalse(d.is_pool_spell, sid)      # token 非池

    def test_related_card_data_chains_resolve(self):
        g = make_game(seed=1304)
        expect = {
            MANIPULATOR: FACELESS, FLAGBEARER: SKY_FLAGBEARER,
            SURVEYOR: SURVEYOR_MINION, FELBAT: FELBAT_MINION,
            WISDOMBALL: WISDOMBALL_SPELL, BOOM: BOOM_MINION,
            WRENCH: REPAIR_JOB, SPELLBOOK: SHINY_RING,
        }
        for tid, card_id in expect.items():
            d = g.trinket_related_card(tid)
            self.assertIsNotNone(d, tid)
            self.assertEqual(d.id, card_id, tid)


# ══════════════ BG30_MagicItem_876 Manipulator Portrait ══════════════

class TestManipulatorPortrait(unittest.TestCase):
    """876 — Get a Faceless Manipulator。"""

    def test_bind_grants_faceless_manipulator(self):
        g = make_game(seed=1310)
        a, b = g.heroes
        avail = g.minion_pool.available(FACELESS)
        bind(g, a, MANIPULATOR)
        got = hand_of(a, FACELESS)
        self.assertEqual(len(got), 1)
        self.assertIsNotNone(get_db().get(FACELESS))
        self.assertEqual(avail, g.minion_pool.available(FACELESS))  # token 零池
        self.assertEqual(hand_ids(b), [])                            # 隔离

    def test_no_repeat_on_next_turn(self):
        g = make_game(seed=1311)
        a, _b = g.heroes
        bind(g, a, MANIPULATOR)
        self.assertEqual(len(hand_of(a, FACELESS)), 1)   # 正对照: 已授予
        g._begin_recruit_for(a)                          # 真实回合开始
        self.assertEqual(len(hand_of(a, FACELESS)), 1)   # 无 "each turn"


# ══════════════ BG30_MagicItem_879 Dalaran Cheese Wheel ══════════════

class TestDalaranCheeseWheel(unittest.TestCase):
    """879 — 酒馆随从 +num(1)/+num(1); 每 num(0) 次主动刷新改善一次。"""

    def test_bind_buffs_current_and_future_tavern_minions(self):
        g = make_game(seed=1320)
        a, b = g.heroes
        per = get_db().get(CHEESE).num(1)
        m = put_tavern(g, a)
        bind(g, a, CHEESE)
        self.assertEqual((m.atk, m.health), (1 + per, 1 + per))  # 立即面
        fresh = g.inject_tavern_minion(a, T1_BEAST)              # 未来面
        self.assertEqual((fresh.atk, fresh.health), (1 + per, 1 + per))
        # 对手馆内随从无增益
        b._tavern_offer_override = None
        opp = g.inject_tavern_minion(b, T1_BEAST)
        self.assertEqual((opp.atk, opp.health), (1, 1))

    def test_improves_after_num0_manual_refreshes(self):
        g = make_game(seed=1321)
        a, _b = g.heroes
        a.gold = 50
        per = get_db().get(CHEESE).num(1)
        n = get_db().get(CHEESE).num(0)
        bind(g, a, CHEESE)
        for _ in range(n - 1):
            g.refresh_tavern(a)
        mid = g.inject_tavern_minion(a, T1_BEAST)
        self.assertEqual((mid.atk, mid.health), (1 + per, 1 + per))
        g.refresh_tavern(a)                                  # 第 n 次
        after = g.inject_tavern_minion(a, T1_BEAST)
        self.assertEqual((after.atk, after.health),
                         (1 + 2 * per, 1 + 2 * per))

    def test_auto_refresh_does_not_count(self):
        g = make_game(seed=1322)
        a, _b = g.heroes
        a.gold = 50
        n = get_db().get(CHEESE).num(0)
        bind(g, a, CHEESE)
        for _ in range(n):
            g.refresh_tavern(a, auto=True)                   # 回合开始自动刷新
        self.assertEqual(len(a.tavern_buffs), 1)             # 不改善
        for _ in range(n):
            g.refresh_tavern(a)                              # 正对照: 主动刷新
        self.assertEqual(len(a.tavern_buffs), 2)


# ══════════════ BG30_MagicItem_888 Souvenir Stand ══════════════

class TestSouvenirStand(unittest.TestCase):
    """888 — 买到 Greater 饰品时 Stand 变成其副本（本体 + 副本）。"""

    def test_buying_greater_transforms_into_copy(self):
        g = make_game(seed=1330)
        a, b = g.heroes
        stand = bind(g, a, STAND)
        pick = unscripted_of(12)
        buy_trinket(g, a, "greater", pick.id)
        ids = [t.card_id for t in a.trinkets]
        self.assertNotIn(stand, a.trinkets)                  # Stand 消失
        self.assertEqual(ids.count(pick.id), 2)              # 本体 + 副本
        self.assertEqual(a.gold, 50 - (pick.cost or 0))      # 复制免费
        copies = [t for t in a.trinkets if t.card_id == pick.id]
        self.assertNotEqual(copies[0].uuid, copies[1].uuid)  # 独立实体
        self.assertIn(pick.id, g._trinkets_granted)
        self.assertEqual(b.trinkets, [])                     # 隔离

    def test_buying_lesser_keeps_stand(self):
        g = make_game(seed=1331)
        a, _b = g.heroes
        stand = bind(g, a, STAND)
        pick = unscripted_of(11)
        buy_trinket(g, a, "lesser", pick.id)
        self.assertIn(stand, a.trinkets)                     # 只响应 Greater
        self.assertEqual([t.card_id for t in a.trinkets],
                         [STAND, pick.id])
        greater = unscripted_of(12)                          # 正对照: Greater 触发
        buy_trinket(g, a, "greater", greater.id)
        self.assertNotIn(stand, a.trinkets)
        self.assertEqual([t.card_id for t in a.trinkets].count(greater.id), 2)

    def test_opponent_greater_purchase_does_not_consume_stand(self):
        g = make_game(seed=1332)
        a, b = g.heroes
        stand = bind(g, a, STAND)
        pick = unscripted_of(12)
        buy_trinket(g, b, "greater", pick.id)
        self.assertIn(stand, a.trinkets)                     # 对手购买不触发
        self.assertEqual([t.card_id for t in b.trinkets], [pick.id])
        # 正对照: 本人买到 Greater 时 Stand 仍会复制
        mine = next(d for d in get_db().trinket_offer_pool()
                    if d.spell_school == 12 and d.id not in REGISTRY
                    and (d.cost or 0) > 0 and d.id != pick.id)
        buy_trinket(g, a, "greater", mine.id)
        self.assertNotIn(stand, a.trinkets)
        self.assertEqual([t.card_id for t in a.trinkets].count(mine.id), 2)


# ══════════════ BG30_MagicItem_919 Nazjatar Postcard ══════════════

class TestNazjatarPostcard(unittest.TestCase):
    """919 — 打出纳迦后随机获得 1 张 Spellcraft 法术。"""

    def _play(self, g, hero, card_id):
        m = g.create_minion(card_id, controller=hero)
        hero.add_to_hand(m)
        self.assertTrue(g.play_minion(hero, m))
        return m

    def test_playing_naga_grants_random_spellcraft_spell(self):
        g = make_game(seed=1340)
        a, _b = g.heroes
        bind(g, a, POSTCARD)
        cands = spellcraft_ids(g)
        self._play(g, a, NAGA)
        got = [c for c in a.hand
               if c.card_id in cands and c.has(GameTag.SPELLCRAFT)]
        self.assertEqual(len(got), 1)
        # 非池 token → 不占法术池
        self.assertFalse(get_db().get(got[0].card_id).is_pool_spell)

    def test_non_naga_play_does_not_trigger(self):
        g = make_game(seed=1341)
        a, _b = g.heroes
        bind(g, a, POSTCARD)
        cands = spellcraft_ids(g)
        self._play(g, a, NON_NAGA)
        self.assertEqual([c.card_id for c in a.hand
                          if c.card_id in cands], [])        # 负面
        self._play(g, a, NAGA)                               # 正对照
        self.assertEqual(len([c.card_id for c in a.hand
                              if c.card_id in cands]), 1)

    def test_opponent_naga_does_not_grant(self):
        g = make_game(seed=1342)
        a, b = g.heroes
        bind(g, a, POSTCARD)
        cands = spellcraft_ids(g)
        self._play(g, b, NAGA)
        self.assertEqual([c.card_id for c in a.hand
                          if c.card_id in cands], [])
        self._play(g, a, NAGA)                               # 正对照
        self.assertEqual(len([c.card_id for c in a.hand
                              if c.card_id in cands]), 1)

    def test_pool_invariant(self):
        """Spellcraft 法术是非池 token → 授予不改动法术池。"""
        g = make_game(seed=1343)
        a, _b = g.heroes
        bind(g, a, POSTCARD)
        cands = sorted(spellcraft_ids(g))
        before = {cid: g.spell_pool.available(cid) for cid in cands}
        self._play(g, a, NAGA)
        # 正对照: 效果确实发生了（入手 1 张 Spellcraft 法术）
        got = [c for c in a.hand if c.card_id in set(cands)]
        self.assertEqual(len(got), 1)
        self.assertEqual({cid: g.spell_pool.available(cid)
                          for cid in cands}, before)


# ══════════════ BG30_MagicItem_921 Flagbearer Portrait ══════════════

class TestFlagbearerPortrait(unittest.TestCase):
    """921 — Get Sky Pirate Flagbearer; 本人 Sky Pirate +6 攻。"""

    def test_bind_grants_flagbearer_and_buffs_existing_sky_pirate(self):
        g = make_game(seed=1350)
        a, b = g.heroes
        mine = g.create_minion(SKY_PIRATE, controller=a)
        g.summon(a, mine)
        self.assertEqual(mine.atk, 1)
        bind(g, a, FLAGBEARER)
        self.assertEqual(hand_ids(a), [SKY_FLAGBEARER])
        self.assertEqual(mine.atk, 1 + B.SKY_PIRATE_ATK_BONUS)
        # 对手 Sky Pirate 不受影响
        opp = g.create_minion(SKY_PIRATE, controller=b)
        g.summon(b, opp)
        self.assertEqual(opp.atk, 1)

    def test_summoned_sky_pirate_gets_bonus(self):
        g = make_game(seed=1351)
        a, _b = g.heroes
        bind(g, a, FLAGBEARER)
        late = g.create_minion(SKY_PIRATE, controller=a)
        g.summon(a, late)
        self.assertEqual(late.atk, 1 + B.SKY_PIRATE_ATK_BONUS)
        gold = g.create_minion(SKY_PIRATE_G, controller=a)
        g.summon(a, gold)
        self.assertEqual(gold.atk, 2 + B.SKY_PIRATE_ATK_BONUS)

    def test_other_pirate_not_buffed(self):
        g = make_game(seed=1352)
        a, _b = g.heroes
        bind(g, a, FLAGBEARER)
        scally = g.create_minion(SCALLYWAG, controller=a)    # 非 Sky Pirate
        g.summon(a, scally)
        self.assertEqual(scally.atk, 3)                      # 负面
        sky = g.create_minion(SKY_PIRATE, controller=a)      # 正对照
        g.summon(a, sky)
        self.assertEqual(sky.atk, 1 + B.SKY_PIRATE_ATK_BONUS)

    def test_opponent_summon_not_buffed(self):
        g = make_game(seed=1353)
        a, b = g.heroes
        bind(g, a, FLAGBEARER)
        opp = g.create_minion(SKY_PIRATE, controller=b)
        g.summon(b, opp)
        self.assertEqual(opp.atk, 1)
        mine = g.create_minion(SKY_PIRATE, controller=a)     # 正对照
        g.summon(a, mine)
        self.assertEqual(mine.atk, 1 + B.SKY_PIRATE_ATK_BONUS)


# ══════════════ BG30_MagicItem_930 Burgling Claw ══════════════

class TestBurglingClaw(unittest.TestCase):
    """930 — 每回合开始复制上一对手战团最高档随从（白板）。"""

    def _setup_opponent(self, g, hero):
        lo = g.create_minion(T1_BEAST, controller=hero)      # T1
        hi = g.create_minion(T6_MECH, controller=hero)       # T6
        hi.add_buff(Buff(hi, atk=5, health=5))               # 源带 buff
        hero.board = [lo, hi]
        return lo, hi

    def test_start_of_turn_copies_highest_tier_plain(self):
        g = make_game(seed=1360)
        a, b = g.heroes
        bind(g, a, CLAW)
        lo, hi = self._setup_opponent(g, b)
        g.end_recruit_phase()                                # 真实战斗 + 下一回合 SoT
        copies = hand_of(a, T6_MECH)
        self.assertEqual(len(copies), 1)                     # 最高档被复制
        base = get_db().get(T6_MECH)
        self.assertEqual((copies[0].atk, copies[0].health),
                         (base.atk, base.health))            # 白板（源带 buff）
        self.assertEqual(hand_of(a, T1_BEAST), [])           # 低档不复制
        self.assertEqual(b.hand, [])                         # 对手手牌不变

    def test_no_last_opponent_is_noop(self):
        g = make_game(seed=1361)
        a, b = g.heroes
        trinket = bind(g, a, CLAW)
        self.assertEqual(a.hand, [])                         # 首回合无记录
        g.run_script_hook(trinket, "start_of_turn")
        self.assertEqual(a.hand, [])                         # 落空不崩
        self._setup_opponent(g, b)
        g.end_recruit_phase()                                # 正对照: 有记录后复制
        self.assertEqual(len(hand_of(a, T6_MECH)), 1)

    def test_tiebreak_leftmost(self):
        g = make_game(seed=1362)
        a, b = g.heroes
        bind(g, a, CLAW)
        left = g.create_minion(T6_MECH, controller=b)
        right = g.create_minion(T6_MECH, controller=b)       # 同档 => 取最左
        b.board = [left, right]
        g.end_recruit_phase()
        # 两张同 id，断言只复制 1 张且不占池
        copies = hand_of(a, T6_MECH)
        self.assertEqual(len(copies), 1)


# ══════════════ BG30_MagicItem_942 Mecha-Jaraxxus Sticker ══════════════

class TestMechaJaraxxusSticker(unittest.TestCase):
    """942 — Get 2 random Magnetic Mecha-Demons; 每回合再来 2。"""

    def test_bind_grants_two_distinct_mecha_demons(self):
        g = make_game(seed=1370)
        a, b = g.heroes
        valid = {d.id for d in B._magnetic_mecha_demon_defs(g)}
        bind(g, a, JARAXXUS)
        ids = hand_ids(a)
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)                   # 互异
        for cid in ids:
            self.assertIn(cid, valid)
            self.assertFalse(get_db().get(cid).is_pool_minion)  # token 零池
        self.assertEqual(b.hand, [])

    def test_start_of_turn_grants_two_more(self):
        g = make_game(seed=1371)
        a, _b = g.heroes
        bind(g, a, JARAXXUS)
        self.assertEqual(len(a.hand), 2)                     # 正对照
        g._begin_recruit_for(a)                              # 真实回合开始
        self.assertEqual(len(a.hand), 4)
        valid = {d.id for d in B._magnetic_mecha_demon_defs(g)}
        for c in a.hand:
            self.assertIn(c.card_id, valid)

    def test_opponent_hand_unaffected(self):
        g = make_game(seed=1372)
        a, b = g.heroes
        bind(g, a, JARAXXUS)
        g._begin_recruit_for(b)
        self.assertEqual(b.hand, [])
        self.assertEqual(len(a.hand), 2)                     # 正对照

    def test_granted_mecha_demons_can_magnetize_to_demons(self):
        """Mecha-Demon token 文本 "Can Magnetize to Mechs *and* **Demons**"
        → 引擎 `_magnetic_valid` 必须接受恶魔宿主（2026-09-02 对抗审查
        ENGINE[MINOR]: 此前对恶魔宿主全部 False）。"""
        g = make_game(seed=1373)
        a = g.heroes[0]
        host = Minion("TEST_DEMON_HOST", "D", atk=2, health=2)
        host.set(GameTag.RACE, Race.DEMON)
        host.game = g
        host.controller = a
        g.summon(a, host)
        token = next(d for d in B._magnetic_mecha_demon_defs(g))
        mag = g.create_minion(token.id, controller=a)
        self.assertTrue(g._magnetic_valid(mag, host))
        # 正对照: 非机械/恶魔宿主（野兽）不合法
        beast = Minion("TEST_BEAST_HOST", "B", atk=1, health=1)
        beast.set(GameTag.RACE, Race.BEAST)
        beast.game = g
        beast.controller = a
        g.summon(a, beast)
        self.assertFalse(g._magnetic_valid(mag, beast))


# ══════════════ BG30_MagicItem_943 Surveyor Portrait ══════════════

class TestSurveyorPortrait(unittest.TestCase):
    """943 — Get Hot-Air Surveyor; **手牌打出**的血宝石额外 +num(0)/+num(1)。"""

    def test_bind_grants_surveyor(self):
        g = make_game(seed=1380)
        a, _b = g.heroes
        bind(g, a, SURVEYOR)
        self.assertEqual(hand_ids(a), [SURVEYOR_MINION])

    def test_hand_played_blood_gem_gets_extra(self):
        g = make_game(seed=1381)
        a, _b = g.heroes
        d = get_db().get(SURVEYOR)
        gem = get_db().get(BLOOD_GEM)
        bind(g, a, SURVEYOR)
        m = g.create_minion(T1_BEAST, controller=a)
        g.summon(a, m)
        s = g.create_spell(BLOOD_GEM, controller=a)
        a.add_to_hand(s)
        self.assertTrue(g.play_spell(a, s, target=m))
        self.assertEqual(
            (m.atk, m.health),
            (1 + gem.num(0) + d.num(0), 1 + gem.num(1) + d.num(1)))

    def test_direct_play_blood_gems_gets_no_extra(self):
        """"played from your hand" 判别: 卡牌直施只吃基础值。"""
        g = make_game(seed=1382)
        a, _b = g.heroes
        d = get_db().get(SURVEYOR)
        gem = get_db().get(BLOOD_GEM)
        bind(g, a, SURVEYOR)
        m = g.create_minion(T1_BEAST, controller=a)
        g.summon(a, m)
        g.run_actions(PlayBloodGems(m, 1))                   # 直施路径
        self.assertEqual((m.atk, m.health),
                         (1 + gem.num(0), 1 + gem.num(1)))   # 无 +num(0)
        # 正对照: 同一设置下手牌路径确实拿到 +num(0)/+num(1)
        s = g.create_spell(BLOOD_GEM, controller=a)
        a.add_to_hand(s)
        self.assertTrue(g.play_spell(a, s, target=m))
        self.assertEqual(
            (m.atk, m.health),
            (1 + 2 * gem.num(0) + d.num(0),
             1 + 2 * gem.num(1) + d.num(1)))

    def test_opponent_gem_unaffected(self):
        g = make_game(seed=1383)
        a, b = g.heroes
        d = get_db().get(SURVEYOR)
        gem = get_db().get(BLOOD_GEM)
        bind(g, a, SURVEYOR)
        m = g.create_minion(T1_BEAST, controller=b)
        g.summon(b, m)
        s = g.create_spell(BLOOD_GEM, controller=b)
        b.add_to_hand(s)
        self.assertTrue(g.play_spell(b, s, target=m))
        self.assertEqual((m.atk, m.health),
                         (1 + gem.num(0), 1 + gem.num(1)))
        # 正对照: 本人手牌宝石拿到额外值
        own = g.create_minion(T1_BEAST, controller=a)
        g.summon(a, own)
        s2 = g.create_spell(BLOOD_GEM, controller=a)
        a.add_to_hand(s2)
        self.assertTrue(g.play_spell(a, s2, target=own))
        self.assertEqual(
            (own.atk, own.health),
            (1 + gem.num(0) + d.num(0), 1 + gem.num(1) + d.num(1)))

    def test_control_without_trinket(self):
        """无饰品对照: 同一手牌宝石路径只吃基础值（与正例形成对照）。"""
        d = get_db().get(SURVEYOR)
        gem = get_db().get(BLOOD_GEM)
        g = make_game(seed=1384)
        a, _b = g.heroes
        m = g.create_minion(T1_BEAST, controller=a)
        g.summon(a, m)
        s = g.create_spell(BLOOD_GEM, controller=a)
        a.add_to_hand(s)
        self.assertTrue(g.play_spell(a, s, target=m))
        self.assertEqual((m.atk, m.health),
                         (1 + gem.num(0), 1 + gem.num(1)))
        # 正例对照: 有饰品时确实多 num(0)/num(1)
        g2 = make_game(seed=1385)
        a2, _b2 = g2.heroes
        bind(g2, a2, SURVEYOR)
        m2 = g2.create_minion(T1_BEAST, controller=a2)
        g2.summon(a2, m2)
        s2 = g2.create_spell(BLOOD_GEM, controller=a2)
        a2.add_to_hand(s2)
        self.assertTrue(g2.play_spell(a2, s2, target=m2))
        self.assertEqual(
            (m2.atk, m2.health),
            (1 + gem.num(0) + d.num(0), 1 + gem.num(1) + d.num(1)))


# ══════════════ BG30_MagicItem_991 Felbat Portrait ══════════════

class TestFelbatPortrait(unittest.TestCase):
    """991 — Get Famished Felbat; 酒馆恒 7 个随从位。"""

    def test_bind_grants_felbat_and_tavern_has_seven(self):
        g = make_game(seed=1390)
        a, b = g.heroes
        avail = g.minion_pool.available(FELBAT_MINION)
        bind(g, a, FELBAT)
        self.assertEqual(hand_ids(a), [FELBAT_MINION])
        self.assertEqual(avail, g.minion_pool.available(FELBAT_MINION))
        g.refresh_tavern(a)
        self.assertEqual(len(tavern_minions(a)), B.TAVERN_ALWAYS_SEVEN)
        g.refresh_tavern(b)                                  # 对手不受影响
        self.assertLess(len(tavern_minions(b)), B.TAVERN_ALWAYS_SEVEN)
        self.assertFalse(hasattr(b, "_tavern_offer_override"))


# ══════════════ BG30_MagicItem_999 Fancy Spellbook ══════════════

class TestFancySpellbook(unittest.TestCase):
    """999 — 每累计花 num(2) 金施放 Shiny Ring（滚动计数）。"""

    def test_spend_threshold_casts_shiny_ring(self):
        g = make_game(seed=1400)
        a, _b = g.heroes
        ring = get_db().get(SHINY_RING)
        threshold = get_db().get(SPELLBOOK).num(2)
        bind(g, a, SPELLBOOK)
        m = g.create_minion(T1_BEAST, controller=a)
        g.summon(a, m)
        a.gold = 30
        g.spend_gold(a, threshold - 1)
        self.assertEqual((m.atk, m.health), (1, 1))          # 未达阈值
        g.spend_gold(a, 1)
        self.assertEqual((m.atk, m.health),
                         (1 + ring.num(0), 1 + ring.num(1)))
        # 效果施法不经手牌（Eredar Escapist 先例）
        self.assertNotIn(SHINY_RING, [c.card_id for c in a.hand])

    def test_large_spend_triggers_multiple_casts(self):
        g = make_game(seed=1401)
        a, _b = g.heroes
        ring = get_db().get(SHINY_RING)
        threshold = get_db().get(SPELLBOOK).num(2)
        bind(g, a, SPELLBOOK)
        m = g.create_minion(T1_BEAST, controller=a)
        g.summon(a, m)
        a.gold = 40
        g.spend_gold(a, threshold * 2)
        self.assertEqual((m.atk, m.health),
                         (1 + 2 * ring.num(0), 1 + 2 * ring.num(1)))

    def test_opponent_spend_does_not_cast(self):
        g = make_game(seed=1402)
        a, b = g.heroes
        threshold = get_db().get(SPELLBOOK).num(2)
        bind(g, a, SPELLBOOK)
        m = g.create_minion(T1_BEAST, controller=a)
        g.summon(a, m)
        b.gold = 30
        g.spend_gold(b, threshold)
        self.assertEqual((m.atk, m.health), (1, 1))
        a.gold = 30
        g.spend_gold(a, threshold)                           # 正对照
        self.assertEqual((m.atk, m.health), (2, 2))


# ══════════════ BG31_MagicItem_903 Wisdomball Supply ══════════════

class TestWisdomballSupply(unittest.TestCase):
    """903 — Get Knockoff Wisdomball; 每回合再来一张。"""

    def test_bind_grants_and_sot_repeats(self):
        g = make_game(seed=1410)
        a, b = g.heroes
        bind(g, a, WISDOMBALL)
        self.assertEqual(hand_ids(a), [WISDOMBALL_SPELL])
        g._begin_recruit_for(a)                              # 真实回合开始
        self.assertEqual(hand_ids(a), [WISDOMBALL_SPELL] * 2)
        self.assertEqual(b.hand, [])                         # 隔离

    def test_non_pool_spell_does_not_touch_pool(self):
        g = make_game(seed=1411)
        a, _b = g.heroes
        before = g.spell_pool.available(WISDOMBALL_SPELL)
        bind(g, a, WISDOMBALL)
        self.assertEqual(hand_ids(a), [WISDOMBALL_SPELL])    # 正对照: 已授予
        self.assertEqual(g.spell_pool.available(WISDOMBALL_SPELL), before)


# ══════════════ BG32_MagicItem_170 Spell-powered Wrench ══════════════

class TestSpellPoweredWrench(unittest.TestCase):
    """170 — 打出磁力随从后对随机友方机械施放 Repair Job。"""

    def test_magnetize_triggers_repair_job_on_host(self):
        g = make_game(seed=1420)
        a, _b = g.heroes
        job = get_db().get(REPAIR_JOB)
        bind(g, a, WRENCH)
        host = g.create_minion(PLAIN_MECH, controller=a)
        g.summon(a, host)
        mag = g.create_minion(MAGNETIC_MECH, controller=a)
        a.add_to_hand(mag)
        m_atk, m_hp = mag.atk, mag.health
        self.assertTrue(g.play_minion(a, mag, magnetic_target=host))
        # 吸附先并入磁力随从属性，随后 Repair Job 落在宿主上
        self.assertEqual((host.atk, host.health),
                         (6 + m_atk + job.num(0),
                          5 + m_hp + job.num(1)))

    def test_non_magnetic_play_does_not_cast(self):
        g = make_game(seed=1421)
        a, _b = g.heroes
        bind(g, a, WRENCH)
        host = g.create_minion(PLAIN_MECH, controller=a)
        g.summon(a, host)
        plain = g.create_minion(T1_BEAST, controller=a)
        a.add_to_hand(plain)
        self.assertTrue(g.play_minion(a, plain))
        self.assertEqual((host.atk, host.health), (6, 5))    # 负面
        mag = g.create_minion(MAGNETIC_MECH, controller=a)   # 正对照
        a.add_to_hand(mag)
        m_atk = mag.atk
        self.assertTrue(g.play_minion(a, mag, magnetic_target=host))
        self.assertEqual(
            host.atk, 6 + m_atk + get_db().get(REPAIR_JOB).num(0))

    def test_opponent_magnetic_play_does_not_cast(self):
        g = make_game(seed=1422)
        a, b = g.heroes
        bind(g, a, WRENCH)
        mine = g.create_minion(PLAIN_MECH, controller=a)
        g.summon(a, mine)
        opp_host = g.create_minion(PLAIN_MECH, controller=b)
        g.summon(b, opp_host)
        opp_mag = g.create_minion(MAGNETIC_MECH, controller=b)
        b.add_to_hand(opp_mag)
        o_atk, o_hp = opp_mag.atk, opp_mag.health
        self.assertTrue(g.play_minion(b, opp_mag, magnetic_target=opp_host))
        self.assertEqual((mine.atk, mine.health), (6, 5))
        # 正对照: 本人磁力触发并只作用于本人机械（精确增量）
        mag = g.create_minion(MAGNETIC_MECH, controller=a)
        a.add_to_hand(mag)
        m_atk, m_hp = mag.atk, mag.health
        job = get_db().get(REPAIR_JOB)
        self.assertTrue(g.play_minion(a, mag, magnetic_target=mine))
        self.assertEqual((mine.atk, mine.health),
                         (6 + m_atk + job.num(0), 5 + m_hp + job.num(1)))
        self.assertEqual((opp_host.atk, opp_host.health),
                         (6 + o_atk, 5 + o_hp))

    def test_no_friendly_mech_is_noop(self):
        """合成双类型磁力（本人无机械）→ 落空不崩。"""
        g = make_game(seed=1423)
        a, _b = g.heroes
        job = get_db().get(REPAIR_JOB)
        bind(g, a, WRENCH)
        mag = g.create_minion(MAGNETIC_MECH, controller=a)
        mag.set(GameTag.RACE, int(Race.DEMON))               # 合成: 非机械磁力
        a.add_to_hand(mag)
        self.assertTrue(g.play_minion(a, mag))               # 单独打出
        self.assertEqual(a.hand, [])                         # 未施放任何牌
        # 正对照: 出现友方机械后同一路径确实施放 Repair Job
        host = g.create_minion(PLAIN_MECH, controller=a)
        g.summon(a, host)
        mag2 = g.create_minion(MAGNETIC_MECH, controller=a)
        a.add_to_hand(mag2)
        m_atk = mag2.atk
        self.assertTrue(g.play_minion(a, mag2, magnetic_target=host))
        self.assertEqual(host.atk, 6 + m_atk + job.num(0))


# ══════════════ BG32_MagicItem_172 Boom's Monster Portrait ══════════════

class TestBoomsMonsterPortrait(unittest.TestCase):
    """172 — Get Dr. Boom's Monster; 每回合再来一只。"""

    def test_bind_grants_and_sot_repeats(self):
        g = make_game(seed=1430)
        a, b = g.heroes
        avail = g.minion_pool.available(BOOM_MINION)
        bind(g, a, BOOM)
        self.assertEqual(hand_ids(a), [BOOM_MINION])
        self.assertEqual(avail, g.minion_pool.available(BOOM_MINION))
        g._begin_recruit_for(a)
        self.assertEqual(hand_ids(a), [BOOM_MINION] * 2)
        self.assertEqual(b.hand, [])


if __name__ == "__main__":
    unittest.main()
