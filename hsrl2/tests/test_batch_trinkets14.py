"""批次 trinkets14 行为层测试（9 张 CORRECT + 11 张 DEFERRED 台账守卫）。

全部断言走真实引擎路径:
  - 授予: 真实 `game.grant_trinket`（on_bind 接线）
  - 事件: 真实 `before_attack`（直接 fire 与 `recruit_phase_attack` 同一
    广播点）/ `gold_spent`（`spend_gold`）/ `minion_bought`
    （`buy_from_tavern`）/ `spell_resolving`（`play_spell`）/
    `card_discovered`（`PendingChoice.choose`）/ `turn_start`
    （`_begin_recruit_for`）
  - 回合推进: 真实 `game._begin_recruit_for`
  - 池: 真实 `minion_pool.available` / `acquire` / `release`

覆盖（SOP §16 空转测试判定法——每个效果类都有**同测试内正对照**）:
  - 正例（可观察状态: 攻击力 / 手牌 / 圣盾 tag / 池可用量）
  - owner 隔离（2 英雄; 对手活动不生效与本人生效并列断言）
  - 跨回合/一次性语义（每回合首次购买 / 每局 num(2) 上限 / "until next
    turn" 过期 / SoT 重复）
  - 落空（池空 / 无候选 / 空板）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import GetBloodGems, PlayBloodGems
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets14 as B
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

KIBBLE = "BG32_MagicItem_200"           # All-Purpose Kibble
SCALE = "BG32_MagicItem_230"            # Extravagant Scale
CANNON = "BG32_MagicItem_232"           # Shark Cannon
BATTERIES = "BG32_MagicItem_278"        # Reusable Batteries
STICKER = "BG32_MagicItem_279"          # Tough Tusk Sticker
DRILL = "BG32_MagicItem_282"            # Turbocharged Drill
FACTORY = "BG32_MagicItem_361"          # Portable Factory
HEARTH = "BG32_MagicItem_362"           # Innkeeper's Hearth
POET = "BG32_MagicItem_364"             # Poet Portrait

DRAKKARI = "BG32_MagicItem_179"         # Drakkari Portrait（batch_family_races 注册）
KELTHUZAD = "BG32_MagicItem_204"        # Kel'Thuzad Portrait (DEFERRED)
MAWCASTER = "BG32_MagicItem_205"        # Maw Caster Portrait (DEFERRED)
BRISTLEBACH = "BG32_MagicItem_274"      # Bristlebach Portrait（已由 batch_trinkets34 注册）
SHRINE = "BG32_MagicItem_280"           # Eclectic Shrine (DEFERRED)
CZARINA = "BG32_MagicItem_283"          # Czarina Portrait（batch_trinkets31 注册）
CAPE = "BG32_MagicItem_286"             # Lavish Cape (DEFERRED)
PUTRICIDE = "BG32_MagicItem_300"        # Putricide Sticker (DEFERRED)
SPLINTER = "BG32_MagicItem_350"         # Splinter of Aurum（已由 batch_trinkets28 注册）
CANDLE = "BG32_MagicItem_366"           # Guiding Candle（已由 batch_trinkets28 注册）
WARDRUM = "BG32_MagicItem_416"          # War Drum (DEFERRED)

# CAPE（286 Lavish Cape）与 WARDRUM（416 War Drum）已由 batch_trinkets21
# 注册（`cast_spell_effect` + 只读酒馆法术候选 / `bc_first`+`bc_first_times`
# 二维配额）——两者迁出本台账
# 204 Kel'Thuzad / 205 Maw Caster / 280 Eclectic Shrine 已由
# batch_trinkets24 注册（destroy 统一入口 + 新原语落地）→ 移出守卫。
# SPLINTER（350 Splinter of Aurum）/ CANDLE（366 Guiding Candle）已由
# batch_trinkets28 注册（`gold_gained` 观察点 / `TAVERN_OFFER_TIER_EXACT`
# 精确档位读取点）→ 移出守卫。
# BRISTLEBACH（274 Bristlebach Portrait）已由 batch_trinkets34 注册
# （2026-09-13，`hero.family_flags` 家族行为开关通道）→ 移出守卫
# CZARINA（283）已由 batch_trinkets31 注册（2026-09-19——"also give
# Health" 增量 = 同句 num(0) Attack 额 + `FLAG_CZARINA_ALSO_HEALTH`）
# → 移出守卫（仍 DEFERRED 的 PUTRICIDE 保留）。
# 179 Drakkari Portrait 已由 batch_family_races 注册（2026-09-21，RACES
# 家族类型身份改写）→ 移出本 DEFERRED 台账（守卫见 test_batch_family_races）。
DEFERRED = (PUTRICIDE,)

# 关联卡（数据链解析目标; 断言用）
TIME_WARPED_POET = "BG34_Giant_314"     # 未注册、非池（§7.4.6 Get a X）

# 测试用随从（CardDB 数据核实 36.2.2）
T1_BEAST = "BG31_803"                   # Buzzing Vermin 1/1 野兽
T1_MECH = "BG26_146"                    # Lullabot 2/2 磁力机械
PIRATE = "BGS_061"                      # Scallywag 3/1 海盗（非池 token）
UTILITY_DRONE = "BG26_152"              # Utility Drone 4/6 机械
SATELLITE = "BG31_171t"                 # Satellite token 6/6（生成参数覆盖）
BLOOD_GEM = "BG20_GEM"                  # 血宝石（非池 token 法术）
T1_BEAST_ATK = 1                        # BG31_803 Buzzing Vermin（数据核实）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 1400) -> Game:
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


def put_board(game: Game, hero: Hero, card_id: str):
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.PLAY
    hero.board.append(m)
    return m


def buy(game: Game, hero: Hero, card_id: str):
    """真实购买路径（tavern 注入 + buy_from_tavern）。"""
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern = [m]
    hero.gold = 50
    assert game.buy_from_tavern(hero, m)
    return m


def take_choice_prefix(game: Game, kind_prefix: str, owner=None):
    """按 kind **前缀**取选择（Portable Factory 用实例级 kind 防副本串号）。"""
    ch = next(c for c in game.pending_choices
              if c.kind.startswith(kind_prefix)
              and (owner is None or c.owner is owner))
    game.pending_choices.remove(ch)
    return ch


def take_choice(game: Game, kind: str, owner=None):
    if owner is None:
        ch = next(c for c in game.pending_choices if c.kind == kind)
    else:
        ch = next(c for c in game.pending_choices
                  if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(ch)
    return ch


def give_gem(game: Game, hero: Hero) -> None:
    game.run_actions(GetBloodGems(hero, 1))


# ══════════════ 结构性（注册表 / 数据一致性 / DEFERRED 台账） ══════════════

class TestRegistryState(unittest.TestCase):
    """@engine-only —— 注册面 + DEFERRED 台账 + 数据链（与钩子无关）。"""

    IMPLEMENTED = (KIBBLE, SCALE, CANNON, BATTERIES, STICKER, DRILL,
                   FACTORY, HEARTH, POET)
    CLASSES = {
        KIBBLE: "AllPurposeKibbleScript",
        SCALE: "ExtravagantScaleScript",
        CANNON: "SharkCannonScript",
        BATTERIES: "ReusableBatteriesScript",
        STICKER: "ToughTuskStickerScript",
        DRILL: "TurbochargedDrillScript",
        FACTORY: "PortableFactoryScript",
        HEARTH: "InnkeepersHearthScript",
        POET: "PoetPortraitScript",
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
        for name in ("Drakkari Portrait", "Kel'Thuzad Portrait",
                     "Maw Caster Portrait", "Bristlebach Portrait",
                     "Eclectic Shrine", "Czarina Portrait", "Lavish Cape",
                     "Putricide Sticker", "Splinter of Aurum",
                     "Guiding Candle", "War Drum"):
            self.assertIn(name, doc, name)
        self.assertIn("minion_destroyed", doc)          # 204/205 缺口
        # 286/416 已于 2026-09-02 解锁（batch_trinkets21）——台账改标"已解锁"
        self.assertIn("cast_spell_effect", doc)
        self.assertIn("bc_first", doc)
        self.assertIn("_tavern_offer_tier_exact", doc)  # 366 缺口
        self.assertIn("bc_first", doc)                  # 416 缺口
        self.assertIn("gold_gained", doc)               # 350 缺口
        self.assertIn("RACES", doc)                     # 179 缺口

    def test_all_in_offer_pool_with_expected_school(self):
        offer = {d.id for d in get_db().trinket_offer_pool()}
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, offer, tid)
        for tid in (KIBBLE, SCALE, CANNON, DRILL, POET):
            self.assertEqual(get_db().get(tid).spell_school, 12, tid)
        for tid in (BATTERIES, STICKER, FACTORY, HEARTH):
            self.assertEqual(get_db().get(tid).spell_school, 11, tid)

    def test_carddef_num_params_match_text(self):
        db = get_db()
        self.assertEqual(db.get(KIBBLE).num(0), 3)   # 37.0: 2→3      # "+{0} Attack"
        self.assertEqual(db.get(SCALE).num(0), 20)      # "spend 20 Gold"
        self.assertEqual(db.get(SCALE).num(2), 2)       # "Twice per game"
        self.assertEqual(db.get(CANNON).num(0), 7)      # 37.0: 10→7（显示值）
        self.assertEqual(db.get(CANNON).num(2), 1)      # "+{2}/+{2}"
        self.assertEqual(db.get(FACTORY).cost, 5)       # 37.0: cost 6→5
        self.assertIsNone(db.get(FACTORY).num(0))
        self.assertIsNone(db.get(HEARTH).num(0))        # 12/12 是字面量
        self.assertEqual(db.get(DRILL).num(0), 5)       # "Get {0} different"
        self.assertIsNone(db.get(POET).num(0))

    def test_poet_related_card_chain_resolves(self):
        g = make_game(seed=1401)
        d = g.trinket_related_card(POET)
        self.assertIsNotNone(d)
        self.assertEqual(d.id, TIME_WARPED_POET)
        self.assertFalse(d.is_pool_minion)              # 非池 → 零池操作
        self.assertNotIn(TIME_WARPED_POET, REGISTRY)    # 台账: 未迁移

    def test_drill_candidates_data_derived(self):
        g = make_game(seed=1402)
        ids = B._magnetic_mech_candidates(g)
        self.assertTrue(ids)
        self.assertEqual(ids, sorted(ids))
        for cid in ids:
            d = get_db().get(cid)
            self.assertIn("magnetic", d.keywords, cid)
            self.assertIn(d.race, (Race.MECH, Race.ALL), cid)
            self.assertTrue(d.is_pool_minion, cid)


# ══════════════ BG32_MagicItem_200 All-Purpose Kibble ══════════════

class TestAllPurposeKibble(unittest.TestCase):
    """200 — 友方野兽攻击 +num(0) 攻击并永久 improve。"""

    def test_first_attack_and_improve(self):
        g = make_game(seed=1410)
        a, b = g.heroes
        n0 = get_db().get(KIBBLE).num(0)
        bind(g, a, KIBBLE)
        beast = put_board(g, a, T1_BEAST)
        base = beast.atk
        g.events.fire(g, "before_attack", attacker=beast, defender=None)
        self.assertEqual(beast.atk, base + n0)           # 首次 = 印面值
        g.events.fire(g, "before_attack", attacker=beast, defender=None)
        # improve 后第二次增量为 2×num(0) → 累计 +3×num(0)
        self.assertEqual(beast.atk, base + 3 * n0)

    def test_non_beast_attacker_not_buffed(self):
        g = make_game(seed=1411)
        a, _b = g.heroes
        n0 = get_db().get(KIBBLE).num(0)
        bind(g, a, KIBBLE)
        beast = put_board(g, a, T1_BEAST)
        mech = put_board(g, a, T1_MECH)
        mech_base = mech.atk
        g.events.fire(g, "before_attack", attacker=mech, defender=None)
        self.assertEqual(mech.atk, mech_base)            # 非野兽不触发
        g.events.fire(g, "before_attack", attacker=beast, defender=None)
        self.assertEqual(beast.atk, T1_BEAST_ATK + n0)   # 正对照: 野兽受益

    def test_opponent_beast_attack_ignored_and_bonus_not_advanced(self):
        g = make_game(seed=1412)
        a, b = g.heroes
        n0 = get_db().get(KIBBLE).num(0)
        bind(g, a, KIBBLE)
        mine = put_board(g, a, T1_BEAST)
        theirs = put_board(g, b, T1_BEAST)
        g.events.fire(g, "before_attack", attacker=theirs, defender=None)
        self.assertEqual(theirs.atk, T1_BEAST_ATK)       # 对手不获益
        g.events.fire(g, "before_attack", attacker=mine, defender=None)
        self.assertEqual(mine.atk, T1_BEAST_ATK + n0)    # bonus 未被推进


# ══════════════ BG32_MagicItem_230 Extravagant Scale ══════════════

class TestExtravagantScale(unittest.TestCase):
    """230 — 累计花 num(0) 金翻倍攻击; 每局 num(2) 次。"""

    def test_threshold_doubles_and_capped_at_num2(self):
        g = make_game(seed=1420)
        a, _b = g.heroes
        d = get_db().get(SCALE)
        uses = d.num(2)
        bind(g, a, SCALE)
        m = put_board(g, a, T1_BEAST)
        a.gold = 99
        g.spend_gold(a, d.num(0) - 1)
        self.assertEqual(m.atk, T1_BEAST_ATK)            # 未达阈值
        g.spend_gold(a, 1)
        self.assertEqual(m.atk, 2 * T1_BEAST_ATK)        # 第 1 次翻倍
        for _ in range(uses - 1):
            g.spend_gold(a, d.num(0))
        self.assertEqual(m.atk, 4 * T1_BEAST_ATK)        # 第 2 次翻倍
        g.spend_gold(a, d.num(0))                         # 超上限
        self.assertEqual(m.atk, 4 * T1_BEAST_ATK)        # 硬上限拦下

    def test_opponent_spending_ignored(self):
        g = make_game(seed=1421)
        a, b = g.heroes
        d = get_db().get(SCALE)
        bind(g, a, SCALE)
        mine = put_board(g, a, T1_BEAST)
        b.gold = 99
        g.spend_gold(b, d.num(0))
        self.assertEqual(mine.atk, T1_BEAST_ATK)         # 对手支出不触发
        a.gold = 99
        g.spend_gold(a, d.num(0))
        self.assertEqual(mine.atk, 2 * T1_BEAST_ATK)     # 正对照

    def test_empty_board_then_summon_still_counts_uses(self):
        g = make_game(seed=1422)
        a, _b = g.heroes
        d = get_db().get(SCALE)
        bind(g, a, SCALE)
        a.gold = 99
        g.spend_gold(a, d.num(0))                         # 空板: 落空不报错
        m = put_board(g, a, T1_BEAST)
        g.spend_gold(a, d.num(0))
        self.assertEqual(m.atk, 2 * T1_BEAST_ATK)        # 正对照: 仍可触发


# ══════════════ BG32_MagicItem_232 Shark Cannon ══════════════

class TestSharkCannon(unittest.TestCase):
    """232 — 累计花 num(0) 金: 海盗 +num(2)/+num(2) 并 improve。"""

    def test_threshold_buffs_pirates_then_improves(self):
        g = make_game(seed=1430)
        a, _b = g.heroes
        d = get_db().get(CANNON)
        step = d.num(2)
        bind(g, a, CANNON)
        pirate = put_board(g, a, PIRATE)
        other = put_board(g, a, T1_BEAST)
        p_atk, p_hp = pirate.atk, pirate.max_health
        o_atk = other.atk
        a.gold = 99
        g.spend_gold(a, d.num(0) - 1)
        self.assertEqual((pirate.atk, pirate.max_health), (p_atk, p_hp))
        g.spend_gold(a, 1)
        self.assertEqual((pirate.atk, pirate.max_health),
                         (p_atk + step, p_hp + step))    # 第 1 轮
        self.assertEqual(other.atk, o_atk)               # 非海盗不变
        g.spend_gold(a, d.num(0))
        self.assertEqual((pirate.atk, pirate.max_health),
                         (p_atk + 3 * step, p_hp + 3 * step))  # improve

    def test_single_large_spend_crosses_boundaries(self):
        g = make_game(seed=1431)
        a, _b = g.heroes
        d = get_db().get(CANNON)
        step = d.num(2)
        bind(g, a, CANNON)
        p = put_board(g, a, PIRATE)
        base = p.atk
        a.gold = 99
        g.spend_gold(a, 2 * d.num(0))                    # 一次跨两轮
        self.assertEqual(p.atk, base + step + 2 * step)

    def test_no_pirates_still_improves(self):
        g = make_game(seed=1432)
        a, _b = g.heroes
        d = get_db().get(CANNON)
        step = d.num(2)
        bind(g, a, CANNON)
        a.gold = 99
        g.spend_gold(a, d.num(0))                        # 无海盗: 落空
        p = put_board(g, a, PIRATE)
        base = p.atk
        g.spend_gold(a, d.num(0))
        self.assertEqual(p.atk, base + 2 * step)         # improve 已推进

    def test_opponent_spending_ignored(self):
        g = make_game(seed=1433)
        a, b = g.heroes
        d = get_db().get(CANNON)
        bind(g, a, CANNON)
        p = put_board(g, a, PIRATE)
        base = p.atk
        b.gold = 99
        g.spend_gold(b, d.num(0))
        self.assertEqual(p.atk, base)
        a.gold = 99
        g.spend_gold(a, d.num(0))
        self.assertEqual(p.atk, base + d.num(2))         # 正对照


# ══════════════ BG32_MagicItem_278 Reusable Batteries ══════════════

class TestReusableBatteries(unittest.TestCase):
    """278 — 每回合首次买随从获得同属性 Magnetic Satellite。"""

    def test_first_buy_grants_satellite_with_purchased_stats(self):
        g = make_game(seed=1440)
        a, b = g.heroes
        bind(g, a, BATTERIES)
        bought = buy(g, a, UTILITY_DRONE)
        sats = hand_of(a, SATELLITE)
        self.assertEqual(len(sats), 1)
        self.assertEqual((sats[0].atk, sats[0].max_health),
                         (bought.atk, bought.max_health))
        self.assertIn("magnetic", get_db().get(SATELLITE).keywords)
        self.assertEqual(hand_ids(b), [])                # 对手无

    def test_only_once_per_turn_then_resets(self):
        g = make_game(seed=1441)
        a, _b = g.heroes
        bind(g, a, BATTERIES)
        buy(g, a, UTILITY_DRONE)
        self.assertEqual(len(hand_of(a, SATELLITE)), 1)
        buy(g, a, T1_MECH)
        self.assertEqual(len(hand_of(a, SATELLITE)), 1)  # 同回合不再授予
        g.turn += 1
        g._begin_recruit_for(a)                          # 真实回合开始
        buy(g, a, T1_MECH)
        self.assertEqual(len(hand_of(a, SATELLITE)), 2)  # 下回合恢复

    def test_opponent_buy_does_not_grant(self):
        g = make_game(seed=1442)
        a, b = g.heroes
        bind(g, a, BATTERIES)
        buy(g, b, UTILITY_DRONE)
        self.assertEqual(hand_of(a, SATELLITE), [])
        buy(g, a, UTILITY_DRONE)
        self.assertEqual(len(hand_of(a, SATELLITE)), 1)  # 正对照

    def test_token_does_not_consume_minion_pool(self):
        g = make_game(seed=1443)
        a, _b = g.heroes
        before = g.minion_pool.available(SATELLITE)
        bind(g, a, BATTERIES)
        bought = buy(g, a, UTILITY_DRONE)
        sat = hand_of(a, SATELLITE)
        self.assertEqual(len(sat), 1)                    # 正对照: 已授予
        self.assertEqual((sat[0].atk, sat[0].max_health),
                         (bought.atk, bought.max_health))
        self.assertEqual(g.minion_pool.available(SATELLITE), before)

    def test_satellite_uses_tavern_buffed_stats(self):
        g = make_game(seed=1444)
        a, _b = g.heroes
        bind(g, a, BATTERIES)
        m = g.create_minion(UTILITY_DRONE, controller=a)
        m.zone = Zone.TAVERN
        g.run_actions(Buff(m, atk=3, health=3))
        a.tavern = [m]
        a.gold = 50
        self.assertTrue(g.buy_from_tavern(a, m))
        sat = hand_of(a, SATELLITE)[0]
        self.assertEqual((sat.atk, sat.max_health),
                         (m.atk, m.max_health))


# ══════════════ BG32_MagicItem_279 Tough Tusk Sticker ══════════════

class TestToughTuskSticker(unittest.TestCase):
    """279 — 手牌血宝石给目标圣盾直到下回合。"""

    def test_hand_played_gem_grants_ds_until_next_turn(self):
        g = make_game(seed=1450)
        a, _b = g.heroes
        bind(g, a, STICKER)
        m = put_board(g, a, T1_BEAST)
        give_gem(g, a)
        gem = hand_of(a, BLOOD_GEM)[0]
        self.assertTrue(g.play_spell(a, gem, target=m))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        g.turn += 1
        g._begin_recruit_for(a)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))   # until next turn

    def test_direct_played_gem_does_not_grant_ds(self):
        g = make_game(seed=1451)
        a, _b = g.heroes
        bind(g, a, STICKER)
        m = put_board(g, a, T1_BEAST)
        g.run_actions(PlayBloodGems(m, 1))               # 直施路径
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))
        give_gem(g, a)
        gem = hand_of(a, BLOOD_GEM)[0]
        self.assertTrue(g.play_spell(a, gem, target=m))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))    # 正对照: 手牌路径

    def test_pre_existing_ds_survives_expiry(self):
        g = make_game(seed=1452)
        a, _b = g.heroes
        bind(g, a, STICKER)
        m = put_board(g, a, T1_BEAST)
        m.set(GameTag.DIVINE_SHIELD, True)               # 自带圣盾
        plain = put_board(g, a, T1_MECH)                 # 正对照: 无圣盾
        give_gem(g, a)
        gems = hand_of(a, BLOOD_GEM)
        g.play_spell(a, gems[0], target=m)
        give_gem(g, a)
        g.play_spell(a, hand_of(a, BLOOD_GEM)[0], target=plain)
        self.assertTrue(plain.has(GameTag.DIVINE_SHIELD))  # 授予确实发生
        g.turn += 1
        g._begin_recruit_for(a)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))    # 不误删永久
        self.assertFalse(plain.has(GameTag.DIVINE_SHIELD))  # 本卡授予的过期

    def test_opponent_gem_does_not_shield_own_minion(self):
        g = make_game(seed=1453)
        a, b = g.heroes
        bind(g, a, STICKER)
        mine = put_board(g, a, T1_BEAST)
        theirs = put_board(g, b, T1_BEAST)
        give_gem(g, b)
        gem = hand_of(b, BLOOD_GEM)[0]
        self.assertTrue(g.play_spell(b, gem, target=theirs))
        self.assertFalse(mine.has(GameTag.DIVINE_SHIELD))  # owner 隔离
        give_gem(g, a)
        mine_gem = hand_of(a, BLOOD_GEM)[0]
        self.assertTrue(g.play_spell(a, mine_gem, target=mine))
        self.assertTrue(mine.has(GameTag.DIVINE_SHIELD))   # 正对照


# ══════════════ BG32_MagicItem_282 Turbocharged Drill ══════════════

class TestTurbochargedDrill(unittest.TestCase):
    """282 — Get num(0) 张互异 Magnetic Mech（任意档位，占池）。"""

    def test_grants_distinct_magnetic_mechs_and_consumes_pool(self):
        g = make_game(seed=1460)
        a, b = g.heroes
        n0 = get_db().get(DRILL).num(0)
        before = {d.id: g.minion_pool.available(d.id)
                  for d in get_db().pool_minions()
                  if "magnetic" in d.keywords}
        bind(g, a, DRILL)
        got = [c.card_id for c in a.hand]
        self.assertEqual(len(got), n0)
        self.assertEqual(len(set(got)), n0)              # different
        for cid in got:
            d = get_db().get(cid)
            self.assertIn("magnetic", d.keywords, cid)
            self.assertIn(d.race, (Race.MECH, Race.ALL), cid)
            self.assertEqual(g.minion_pool.available(cid),
                             before[cid] - 1, cid)       # 占池
        self.assertEqual(hand_ids(b), [])                # owner 隔离

    def test_no_candidates_no_grant(self):
        g = make_game(seed=1461)
        a, _b = g.heroes
        g.minion_pool.active_races = {Race.BEAST}        # 机械全禁用
        bind(g, a, DRILL)
        self.assertEqual(hand_ids(a), [])
        g.minion_pool.active_races = None
        g.grant_trinket(a, DRILL, duplicate=True)        # 正对照: 有候选
        self.assertEqual(len(a.hand), get_db().get(DRILL).num(0))


# ══════════════ BG32_MagicItem_361 Portable Factory ══════════════

class TestPortableFactory(unittest.TestCase):
    """361 — Discover 带类型 T4 随从; 每回合再得一张同卡。"""

    def test_discover_options_are_typed_tier4_and_pick_granted(self):
        g = make_game(seed=1470)
        a, _b = g.heroes
        bind(g, a, FACTORY)
        ch = take_choice_prefix(g, B.PORTABLE_FACTORY_KIND, a)
        self.assertEqual(len(ch.options), 3)
        for cid in ch.options:
            d = get_db().get(cid)
            self.assertEqual(d.tech_level, 4, cid)
            self.assertNotEqual(d.race, Race.NONE, cid)  # "with a type"
        pick = ch.options[0]
        ch.choose(0)
        self.assertEqual(hand_ids(a), [pick])

    def test_start_of_turn_grants_another_copy(self):
        g = make_game(seed=1471)
        a, b = g.heroes
        bind(g, a, FACTORY)
        ch = take_choice_prefix(g, B.PORTABLE_FACTORY_KIND, a)
        pick = ch.options[0]
        ch.choose(0)
        before = g.minion_pool.available(pick)
        g._begin_recruit_for(a)
        self.assertEqual(len(hand_of(a, pick)), 2)  # 再得一张
        self.assertEqual(g.minion_pool.available(pick), before - 1)
        self.assertEqual(hand_ids(b), [])                # owner 隔离

    def test_two_copies_track_their_own_pick(self):
        """两份副本（副本条款 / Crystal Ball）**各自**只认自己开出的发现
        （2026-09-02 对抗审查 MAJOR: 旧的共用 kind 让两份 pick 互相覆盖
        → 都发最后一张、手牌三张同名误合成金色）。"""
        g = make_game(seed=1473)
        a, _b = g.heroes
        e1 = bind(g, a, FACTORY)
        e2 = g.grant_trinket(a, FACTORY, duplicate=True)   # 副本
        self.assertIsNotNone(e2)
        ch1 = take_choice_prefix(g, B.PORTABLE_FACTORY_KIND, a)
        p1 = ch1.options[0]
        ch1.choose(0)
        ch2 = take_choice_prefix(g, B.PORTABLE_FACTORY_KIND, a)
        # 两份副本的选项池独立（各 3 项，互不共用选择对象）
        self.assertIsNot(ch1, ch2)
        p2 = next(cid for cid in ch2.options if cid != p1)
        ch2.choose(ch2.options.index(p2))
        self.assertEqual(e1._portable_factory_pick, p1)
        self.assertEqual(e2._portable_factory_pick, p2)
        # 各自 SoT 授予自己的 pick（互不串号）
        g._begin_recruit_for(a)
        self.assertEqual(len(hand_of(a, p1)), 2)
        self.assertEqual(len(hand_of(a, p2)), 2)
        self.assertEqual(len([m for m in a.hand
                              if m.card_id == p1 and m.is_golden]), 0)

    def test_start_of_turn_without_pick_is_noop(self):
        g = make_game(seed=1472)
        a, _b = g.heroes
        bind(g, a, FACTORY)
        g._begin_recruit_for(a)                          # 未选择
        self.assertEqual(hand_ids(a), [])
        ch = take_choice_prefix(g, B.PORTABLE_FACTORY_KIND, a)  # 正对照: 选择后
        pick = ch.options[0]
        ch.choose(0)
        g._begin_recruit_for(a)
        self.assertEqual(len(hand_of(a, pick)), 2)


# ══════════════ BG32_MagicItem_362 Innkeeper's Hearth ══════════════

class TestInnkeepersHearth(unittest.TestCase):
    """362 — Discover 本档随从并把属性设为 12/12。"""

    def test_discover_own_tier_and_stats_set(self):
        g = make_game(seed=1480)
        a, b = g.heroes
        a.set(GameTag.TAVERN_TIER, 4)
        bind(g, a, HEARTH)
        ch = take_choice(g, B.INNKEEPERS_HEARTH_KIND, a)
        self.assertEqual(len(ch.options), 3)
        for cid in ch.options:
            self.assertEqual(get_db().get(cid).tech_level, 4, cid)
        pick = ch.options[0]
        ch.choose(0)
        m = hand_of(a, pick)[0]
        self.assertEqual((m.atk, m.max_health),
                         (B.INNKEEPERS_HEARTH_STAT,
                          B.INNKEEPERS_HEARTH_STAT))
        self.assertEqual(len(m.buffs), 0)                # 覆盖式设定
        self.assertEqual(hand_ids(b), [])                # owner 隔离

    def test_unpicked_options_released_to_pool(self):
        g = make_game(seed=1481)
        a, _b = g.heroes
        a.set(GameTag.TAVERN_TIER, 4)
        pre = {cid: g.minion_pool.available(cid)
               for cid in B._pool_candidates(g, min_tier=4, max_tier=4)}
        bind(g, a, HEARTH)
        ch = take_choice(g, B.INNKEEPERS_HEARTH_KIND, a)
        opts = list(ch.options)
        ch.choose(0)
        # 选中项: 池副本被消耗（随从已入手）; 未选项: 回池复原
        self.assertEqual(g.minion_pool.available(opts[0]), pre[opts[0]] - 1)
        for cid in opts[1:]:
            self.assertEqual(g.minion_pool.available(cid), pre[cid])

    def test_empty_tier_pool_produces_no_choice(self):
        g = make_game(seed=1482)
        a, b = g.heroes
        a.set(GameTag.TAVERN_TIER, 4)
        b.set(GameTag.TAVERN_TIER, 4)
        bind(g, b, HEARTH)                               # 正对照: 池非空
        self.assertTrue([c for c in g.pending_choices
                         if c.kind == B.INNKEEPERS_HEARTH_KIND])
        for cid in list(B._pool_candidates(g, min_tier=4, max_tier=4)):
            while g.minion_pool.available(cid):
                g.minion_pool.acquire(cid)
        n_choices = len(g.pending_choices)
        bind(g, a, HEARTH)                               # 池空 → 不产生选择
        self.assertEqual(
            [c for c in g.pending_choices
             if c.kind == B.INNKEEPERS_HEARTH_KIND
             and c.owner is a], [])
        self.assertEqual(len(g.pending_choices), n_choices)
        self.assertEqual(hand_ids(a), [])


# ══════════════ BG32_MagicItem_364 Poet Portrait ══════════════

class TestPoetPortrait(unittest.TestCase):
    """364 — Get a Timewarped Poet（关联卡未迁移，不阻塞交付）。"""

    def test_bind_grants_timewarped_poet(self):
        g = make_game(seed=1490)
        a, b = g.heroes
        before = g.minion_pool.available(TIME_WARPED_POET)
        bind(g, a, POET)
        self.assertEqual(len(hand_of(a, TIME_WARPED_POET)), 1)
        self.assertEqual(g.minion_pool.available(TIME_WARPED_POET), before)
        self.assertEqual(hand_ids(b), [])

    def test_no_repeat_on_next_turn(self):
        g = make_game(seed=1491)
        a, _b = g.heroes
        bind(g, a, POET)
        g._begin_recruit_for(a)
        self.assertEqual(len(hand_of(a, TIME_WARPED_POET)), 1)


if __name__ == "__main__":
    unittest.main()
