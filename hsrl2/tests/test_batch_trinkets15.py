"""批次 trinkets15 行为层测试（9 张注册饰品 + 11 张 DEFERRED 台账, 2026-09-11）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）
  - 商店: `game._offer_trinkets` 三选一 + PendingChoice.choose（1 例）
  - SoT/EoT: `game.run_script_hook(trinket, "start_of_turn"/"end_of_turn")`
    （引擎真实分发点）+ `game.end_recruit_phase()` 集成曲线
  - 买/卖: 真实 `game.buy_from_tavern` / `game.sell_minion`
  - 法术: 真实 `game.play_spell`（池法术与 hand-played 血宝石两路径）
  - 攻击/战斗: 真实 `game.run_combat`
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法）: 每个测试方法至少一条**正效果**断言
（多数与同 setup 的无饰品对照写在同一方法内）; owner 隔离（2 英雄）;
跨回合一次性/重置语义; 满手排队 / 空场落空; CardDef.num 双向钉死。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets15 as B15
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id）
DEMON = "BGS_004"              # Wrath Weaver T1 恶魔（池）
NON_DEMON = "BG31_803"         # Buzzing Vermin T1 野兽（池）
DRAGON_T3 = "BG24_500"         # Amber Guardian T3 龙（池）
DRAGON_T6 = "BG24_004"         # Warpwing T6 龙（池）
SPELL_STATS_ALL = "BG28_168"   # Shiny Ring（Give your minions +1/+1）
SPELL_T3 = "BG28_168"          # 池法术 T3（Rendle 档位比较用）
GEM = "BG20_GEM"               # 香草血宝石（非池法术）

# 本批 id
WORLD_MAP = "BG32_MagicItem_428"
HEART = "BG32_MagicItem_801"
CURATOR = "BG32_MagicItem_807"
EARRINGS = "BG32_MagicItem_808"
RENDLE = "BG32_MagicItem_817"
PILGRIMP = "BG32_MagicItem_821"
BAZAAR = "BG32_MagicItem_822"
WINDFALL = "BG32_MagicItem_832"
ALTAR = "BG32_MagicItem_844"

DELETED_417 = "BG32_MagicItem_417"   # Tarecgosa Sticker（已由 batch_trinkets30 注册）
DELETED_419 = "BG32_MagicItem_419"   # Yu'lon Sticker（已由 batch_trinkets28 注册）
# BG32_MagicItem_802 Fountain Pen 已由 batch_trinkets24 注册
# （ELEMENTAL_EXTRA_* 消费点收口，commit 44a9af0 + 本轮全族接线）。
# BG32_MagicItem_419 已由 batch_trinkets28 注册（引擎 `_combat_transforms`
# 战斗内 Transform 持久化，提交 5cc6666）→ 移出守卫。
# BG32_MagicItem_417 已由 batch_trinkets30 注册（PERSIST_BONUS_ONLY +
# PERSIST_COMBAT_CHANGES 战斗持久化通道，2026-09-15）→ 移出 DEFERRED 守卫。
# BG32_MagicItem_830 已由 batch_trinkets31 注册（家族 give 额外持久酒馆
# Buff 镜像原语，2026-09-15）→ 移出 DEFERRED 守卫。
# BG32_MagicItem_804 Selfless Portrait 已由 batch_trinkets35 注册
# （2026-09-13，RULES §7.4.17 条件化战吼协议）→ 移出 DEFERRED 守卫。
# BG32_MagicItem_803 Macaw Portrait 已由 batch_trinkets36 注册
# （2026-09-13，RULES §7.4.17 条件化战吼第二消费者）→ 移出 DEFERRED 守卫。
# BG32_MagicItem_820 Impulsive Portrait 已由 batch_trinkets39 注册
# （2026-09-18——RULES §7.4.16 `family_flags` 目标集合改写 + 6/6 覆盖式
# 交付；both-vs-split 口径按 wiki 无 Notes → 卡面天然语言裁定为"全额
# 逐目标"）→ 移出 DEFERRED 守卫。
# BG32_MagicItem_824 Implicator Portrait 已由 batch_trinkets31 注册
# （2026-09-19——"Your Demons always consume the highest-Health minion in
# the Tavern" = `hero.consume_policies` + `Game.pick_consume_victim` 读取点）
# → 移出 DEFERRED 守卫。
DEFERRED = (
    "BG32_MagicItem_806", "BG32_MagicItem_809",
    "BG32_MagicItem_823",
)

WINDFALL_TOKEN = "BG31_817"                    # 关联卡（非池 token）
GOLDEN_MISHMASH = "TB_BaconShop_HERO_33_Buddy_G"
MISHMASH_BASE = "TB_BaconShop_HERO_33_Buddy"
AMALGAM = "TB_BaconShop_HP_033t"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 700) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def empty_tavern(hero: Hero) -> None:
    hero.tavern.clear()


def put_tavern_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def put_tavern_spell(game: Game, hero: Hero, card_id: str) -> Spell:
    s = game.create_spell(card_id, controller=hero)
    s.zone = Zone.TAVERN
    hero.tavern.append(s)
    return s


def cast_pool_spell(game: Game, hero: Hero, card_id: str,
                    target=None) -> Spell:
    """真实施放池法术（占池 → 入手 → play_spell；结束后回池）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    assert hero.add_to_hand(s)
    assert game.play_spell(hero, s, target=target)
    return s


def cast_custom_spell(game: Game, hero: Hero, card_id: str, *,
                      spellcraft: bool = False, target=None) -> Spell:
    """施放非池法术（血宝石 / 标记 Spellcraft 的测试法术）。"""
    s = game.create_spell(card_id, controller=hero)
    if spellcraft:
        s.set(GameTag.SPELLCRAFT, True)
    assert hero.add_to_hand(s)
    assert game.play_spell(hero, s, target=target)
    return s


def drain(game: Game, card_id: str) -> int:
    n = 0
    while game.minion_pool.acquire(card_id):
        n += 1
    return n


def minion_hand(game: Game, hero: Hero):
    return [e for e in hero.hand if isinstance(e, Minion)]


# ══════════════════ BG32_MagicItem_428 Worn Treasure Map ══════════════════


class TestWornTreasureMap(unittest.TestCase):
    """28 — In two turns, gain 10 Gold. (Once per game.)"""

    def test_gold_after_num0_start_of_turns(self):
        g = make_game(seed=1101)
        a, b = g.heroes
        t = bind(g, a, WORLD_MAP)
        d = get_db().get(WORLD_MAP)
        a.gold = 0
        # 第 1 次 SoT: 未到 num(0) → 不加金（正对照在第 2 次）
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(a.gold, 0)
        self.assertEqual(getattr(t, "_worn_map_left"), d.num(0) - 1)
        g.run_script_hook(t, "start_of_turn")   # 第 num(0) 次
        self.assertEqual(a.gold, 10)
        self.assertTrue(getattr(t, "_worn_map_done"))
        # once per game: 第 3 次不再加
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(a.gold, 10)

    def test_owner_isolation(self):
        g = make_game(seed=1102)
        a, b = g.heroes
        t = bind(g, a, WORLD_MAP)
        a.gold = 0
        b.gold = 0
        g.run_script_hook(t, "start_of_turn")
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(a.gold, 10)
        self.assertEqual(b.gold, 0)

    def test_real_turn_curve_matches_control(self):
        """真实 end_recruit_phase 曲线: 带饰品比无饰品恰多 10 金。"""
        g1 = make_game(seed=1104)
        a1 = g1.heroes[0]
        bind(g1, a1, WORLD_MAP)
        g2 = make_game(seed=1104)
        a2 = g2.heroes[0]
        for _ in range(2):
            g1.end_recruit_phase()
            g2.end_recruit_phase()
        self.assertEqual(a1.gold, a2.gold + 10)
        # 第 3 回合不再多拿
        g1.end_recruit_phase()
        g2.end_recruit_phase()
        self.assertEqual(a1.gold, a2.gold)


# ══════════════════ BG32_MagicItem_801 Heart of the Forest ══════════════


class TestHeartOfTheForest(unittest.TestCase):
    """801 — Tavern spells give an extra +{1}/+{2}; each num(0) spells
    improve this."""

    def test_bind_bumps_extra_and_spell_uses_it(self):
        g = make_game(seed=1201)
        a = g.heroes[0]
        d = get_db().get(HEART)
        bind(g, a, HEART)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(1))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), d.num(2))
        m = put(g, a, g.create_minion(NON_DEMON, controller=a))
        atk0, hp0 = m.atk, m.max_health
        cast_pool_spell(g, a, SPELL_STATS_ALL)
        # Shiny Ring 基础 +1/+1 + 饰品额外 num(1)/num(2)
        self.assertEqual(m.atk, atk0 + 1 + d.num(1))
        self.assertEqual(m.max_health, hp0 + 1 + d.num(2))

    def test_no_trinket_control_and_positive(self):
        g = make_game(seed=1202)
        a = g.heroes[0]
        m = put(g, a, g.create_minion(NON_DEMON, controller=a))
        atk0, hp0 = m.atk, m.max_health
        cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(m.atk, atk0 + 1)
        self.assertEqual(m.max_health, hp0 + 1)
        # 正对照: 同 seed 带饰品 → 同一法术多给 num(1)/num(2)
        g2 = make_game(seed=1202)
        a2 = g2.heroes[0]
        d = get_db().get(HEART)
        bind(g2, a2, HEART)
        m2 = put(g2, a2, g2.create_minion(NON_DEMON, controller=a2))
        b_atk, b_hp = m2.atk, m2.max_health
        cast_pool_spell(g2, a2, SPELL_STATS_ALL)
        self.assertEqual(m2.atk, b_atk + 1 + d.num(1))
        self.assertEqual(m2.max_health, b_hp + 1 + d.num(2))

    def test_improve_after_threshold_rolls(self):
        g = make_game(seed=1203)
        a = g.heroes[0]
        d = get_db().get(HEART)
        bind(g, a, HEART)
        base_atk = d.num(1)
        base_hp = d.num(2)
        for _ in range(d.num(0) - 1):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), base_atk)
        cast_pool_spell(g, a, SPELL_STATS_ALL)          # 第 num(0) 个
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK),
                         base_atk * 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH),
                         base_hp * 2)
        # 滚动: 再满 num(0) 个再提升一档
        for _ in range(d.num(0)):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK),
                         base_atk * 3)

    def test_only_tavern_spells_count(self):
        """非池法术（标记 Spellcraft 的血宝石）不计入。"""
        g = make_game(seed=1204)
        a = g.heroes[0]
        d = get_db().get(HEART)
        bind(g, a, HEART)
        base_atk = d.num(1)
        for _ in range(d.num(0) - 1):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        m = put(g, a, g.create_minion(NON_DEMON, controller=a))
        cast_custom_spell(g, a, GEM, spellcraft=True, target=m)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), base_atk)
        # 下一个池法术恰好吃满阈值 → 证明血宝石未被计数
        cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK),
                         base_atk * 2)

    def test_owner_isolation(self):
        g = make_game(seed=1205)
        a, b = g.heroes
        d = get_db().get(HEART)
        bind(g, a, HEART)
        for _ in range(d.num(0)):
            cast_pool_spell(g, b, SPELL_STATS_ALL)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(1))
        for _ in range(d.num(0)):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK),
                         d.num(1) * 2)


# ══════════════════ BG32_MagicItem_807 Curator Sticker ══════════════════


class TestCuratorSticker(unittest.TestCase):
    """807 — Get a Golden Mishmash and a {0}/{0} Amalgam with Venomous."""

    def test_bind_grants_golden_mishmash_and_amalgam(self):
        g = make_game(seed=1301)
        a = g.heroes[0]
        d = get_db().get(CURATOR)
        bind(g, a, CURATOR)
        cards = minion_hand(g, a)
        self.assertEqual(len(cards), 2)
        by_id = {m.card_id: m for m in cards}
        self.assertIn(GOLDEN_MISHMASH, by_id)
        self.assertIn(AMALGAM, by_id)
        mish, am = by_id[GOLDEN_MISHMASH], by_id[AMALGAM]
        gd = get_db().get(GOLDEN_MISHMASH)
        # 金色实体: GOLDEN tag + 基础卡 id + 金色属性
        self.assertTrue(mish.is_golden)
        self.assertTrue(mish.has(GameTag.GOLDEN))
        self.assertEqual(mish.get(GameTag.TRIPLE_BASE_CARD_ID), MISHMASH_BASE)
        self.assertTrue(mish.has(GameTag.GILDED_NOT_TRIPLED))
        self.assertEqual((mish.atk, mish.max_health),
                         (gd.atk, gd.health))
        # Amalgam: num(0)/num(0) + Venomous + 全类型
        self.assertEqual((am.atk, am.max_health), (d.num(0), d.num(0)))
        self.assertEqual(am.get(GameTag.BASE_ATK), d.num(0))
        self.assertTrue(am.has(GameTag.VENOMOUS))
        self.assertEqual(am.race, Race.ALL)

    def test_tokens_do_not_touch_pool(self):
        g = make_game(seed=1302)
        a = g.heroes[0]
        before_minion = g.minion_pool.available(GOLDEN_MISHMASH)
        before_spell = g.spell_pool.available(SPELL_STATS_ALL)
        bind(g, a, CURATOR)
        self.assertEqual(g.minion_pool.available(GOLDEN_MISHMASH),
                         before_minion)
        self.assertEqual(g.spell_pool.available(SPELL_STATS_ALL),
                         before_spell)
        # 正对照: 绑定确实交付两张 token（非空转）
        self.assertEqual(sorted(m.card_id for m in minion_hand(g, a)),
                         sorted([GOLDEN_MISHMASH, AMALGAM]))
        # 且池随从获取确实会改变池计数（池原语有效）
        self.assertGreater(g.minion_pool.available(NON_DEMON), 0)

    def test_owner_isolation(self):
        g = make_game(seed=1303)
        a, b = g.heroes
        bind(g, a, CURATOR)
        self.assertEqual(minion_hand(g, b), [])
        self.assertEqual(len(minion_hand(g, a)), 2)

    def test_hand_full_queues_both(self):
        g = make_game(seed=1304)
        a = g.heroes[0]
        # 填满手牌
        while not a.hand_full():
            a.hand.append(g.create_minion(NON_DEMON, controller=a))
        before_n = len(a.hand)
        bind(g, a, CURATOR)
        queued = [e.card_id for h, e in g.pending_hand_queue if h is a]
        self.assertIn(GOLDEN_MISHMASH, queued)
        self.assertIn(AMALGAM, queued)
        self.assertEqual(len(a.hand), before_n)   # 未挤进满手

    def test_related_chain_resolves_golden(self):
        g = make_game(seed=1305)
        a = g.heroes[0]
        d = g.trinket_related_card(CURATOR)
        self.assertIsNotNone(d)
        self.assertEqual(d.id, GOLDEN_MISHMASH)
        self.assertTrue(d.is_golden_def)
        self.assertEqual(g.db.by_dbf(d.triple_base_id).id, MISHMASH_BASE)
        bind(g, a, CURATOR)
        self.assertEqual(minion_hand(g, a)[0].card_id, GOLDEN_MISHMASH)


# ══════════════════ BG32_MagicItem_808 Bloodbound Earrings ══════════════


class TestBloodboundEarrings(unittest.TestCase):
    """808 — After you cast {1} spells, play a Blood Gem on all your
    minions."""

    def _minion(self, g, a):
        return put(g, a, g.create_minion(NON_DEMON, controller=a))

    def test_threshold_plays_gem_on_all(self):
        g = make_game(seed=1401)
        a = g.heroes[0]
        d = get_db().get(EARRINGS)
        bind(g, a, EARRINGS)
        m1 = self._minion(g, a)
        m2 = self._minion(g, a)
        a1, h1 = m1.atk, m1.max_health
        a2, h2 = m2.atk, m2.max_health
        for _ in range(d.num(1) - 1):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        # Shiny Ring 已给 +1/+1（不含血宝石）; 阈值未到无宝石
        self.assertEqual(m1.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        cast_pool_spell(g, a, SPELL_STATS_ALL)      # 第 num(1) 个
        self.assertEqual(m1.get(GameTag.GEMS_PLAYED_ON), 1)
        self.assertEqual(m2.get(GameTag.GEMS_PLAYED_ON), 1)
        gem = get_db().get(GEM)
        # 宝石 += num(0)/num(1)（本回合 Shiny Ring num(1) 次 +1/+1 已在）
        self.assertEqual(m1.atk, a1 + d.num(1) + gem.num(0))
        self.assertEqual(m1.max_health, h1 + d.num(1) + gem.num(1))
        self.assertEqual(m2.atk, a2 + d.num(1) + gem.num(0))
        self.assertEqual(m2.max_health, h2 + d.num(1) + gem.num(1))

    def test_no_trinket_control_and_positive(self):
        g = make_game(seed=1402)
        a = g.heroes[0]
        d = get_db().get(EARRINGS)
        m = self._minion(g, a)
        for _ in range(d.num(1)):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        # 正对照: 同 seed 带饰品 → 阈值触发血宝石
        g2 = make_game(seed=1402)
        a2 = g2.heroes[0]
        bind(g2, a2, EARRINGS)
        m2 = self._minion(g2, a2)
        for _ in range(d.num(1)):
            cast_pool_spell(g2, a2, SPELL_STATS_ALL)
        self.assertEqual(m2.get(GameTag.GEMS_PLAYED_ON), 1)

    def test_rolling_threshold(self):
        g = make_game(seed=1403)
        a = g.heroes[0]
        d = get_db().get(EARRINGS)
        bind(g, a, EARRINGS)
        m = self._minion(g, a)
        for _ in range(d.num(1)):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 1)
        for _ in range(d.num(1)):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 2)

    def test_spellcraft_counts_but_direct_gems_do_not(self):
        g = make_game(seed=1404)
        a = g.heroes[0]
        d = get_db().get(EARRINGS)
        bind(g, a, EARRINGS)
        m = self._minion(g, a)
        for _ in range(d.num(1) - 1):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        # 直施血宝石（PlayBloodGems 路径）不触发 card_played → 不计
        from hsrl2.actions.bloodgem import PlayBloodGems
        g.run_actions(PlayBloodGems(m, count=1, source=a))
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 1)
        # 标记 Spellcraft 的非池法术计数（cast a spell 全域）
        cast_custom_spell(g, a, GEM, spellcraft=True, target=m)
        # 直施宝石 1 + 手牌打出宝石本体 1 + 阈值触发追加 1 = 3
        # （若无 cast 计数，此处只会有 2——该断言即计数生效的正证据）
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 3)

    def test_double_cast_counts_each_cast(self):
        """双施按 **cast** 计: 2 次打出 × 双施（SPELL_DOUBLER）= 4 次施放。

        旧实现监听 `card_played`（每次**打出**只广播一次）→ 只计 2 次
        → 阈值 num(1)=4 未达、零宝石; 本条即证伪旧实现。
        """
        g = make_game(seed=1407)
        a = g.heroes[0]
        d = get_db().get(EARRINGS)
        bind(g, a, EARRINGS)
        target = self._minion(g, a)
        doubler = self._minion(g, a)
        doubler.set(GameTag.SPELL_DOUBLER, True)
        for _ in range(d.num(1) // 2):          # 2 次打出，每次双施
            cast_pool_spell(g, a, SPELL_STATS_ALL, target=target)
        self.assertEqual(target.get(GameTag.GEMS_PLAYED_ON), 1)
        self.assertEqual(doubler.get(GameTag.GEMS_PLAYED_ON), 1)

    def test_owner_isolation(self):
        g = make_game(seed=1405)
        a, b = g.heroes
        d = get_db().get(EARRINGS)
        bind(g, a, EARRINGS)
        m = self._minion(g, a)
        for _ in range(d.num(1)):
            cast_pool_spell(g, b, SPELL_STATS_ALL)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        for _ in range(d.num(1)):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 1)

    def test_empty_board_resets_counter(self):
        g = make_game(seed=1406)
        a = g.heroes[0]
        d = get_db().get(EARRINGS)
        bind(g, a, EARRINGS)
        for _ in range(d.num(1)):
            cast_pool_spell(g, a, SPELL_STATS_ALL)   # 空板: 落空但不报错
        m = self._minion(g, a)
        for _ in range(d.num(1) - 1):
            cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        cast_pool_spell(g, a, SPELL_STATS_ALL)
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 1)


# ══════════════════ BG32_MagicItem_817 Rendle Sticker ══════════════════


class TestRendleSticker(unittest.TestCase):
    """817 — Steal the highest-Tier card from the Tavern; repeat at EoT."""

    def test_bind_steals_highest_tier(self):
        g = make_game(seed=1501)
        a = g.heroes[0]
        empty_tavern(a)
        put_tavern_minion(g, a, NON_DEMON)      # T1
        put_tavern_minion(g, a, DEMON)          # T1
        high = put_tavern_minion(g, a, DRAGON_T3)   # T3 最高
        before_pool = g.minion_pool.available(DRAGON_T3)
        bind(g, a, RENDLE)
        self.assertIn(high, a.hand)
        self.assertNotIn(high, a.tavern)
        self.assertEqual(g.minion_pool.available(DRAGON_T3), before_pool)
        self.assertEqual(len(minion_hand(g, a)), 1)

    def test_tie_takes_leftmost(self):
        g = make_game(seed=1502)
        a = g.heroes[0]
        # 同档两条 T3: 取最左
        empty_tavern(a)
        left = put_tavern_minion(g, a, DRAGON_T3)
        right = put_tavern_minion(g, a, DRAGON_T3)
        bind(g, a, RENDLE)
        self.assertIn(left, a.hand)
        self.assertIn(right, a.tavern)

    def test_spell_can_be_stolen(self):
        g = make_game(seed=1503)
        a = g.heroes[0]
        empty_tavern(a)
        put_tavern_minion(g, a, NON_DEMON)          # T1
        sp = put_tavern_spell(g, a, SPELL_T3)       # T3 法术
        bind(g, a, RENDLE)
        self.assertIn(sp, a.hand)
        self.assertNotIn(sp, a.tavern)

    def test_end_of_turn_repeats(self):
        g = make_game(seed=1504)
        a = g.heroes[0]
        empty_tavern(a)
        put_tavern_minion(g, a, NON_DEMON)
        put_tavern_minion(g, a, DRAGON_T3)
        put_tavern_minion(g, a, DEMON)
        t = bind(g, a, RENDLE)
        self.assertEqual(len(minion_hand(g, a)), 1)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(len(minion_hand(g, a)), 2)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(len(minion_hand(g, a)), 3)

    def test_empty_tavern_and_full_hand_noop(self):
        g = make_game(seed=1505)
        a = g.heroes[0]
        empty_tavern(a)
        bind(g, a, RENDLE)                       # 空馆: 落空不崩
        self.assertEqual(minion_hand(g, a), [])
        put_tavern_minion(g, a, DRAGON_T3)
        while not a.hand_full():
            a.hand.append(g.create_minion(NON_DEMON, controller=a))
        t = a.trinkets[-1]
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(len(a.tavern), 1)       # 满手: 馆内卡保留
        # 正对照: 腾出手牌后同一 EoT 立刻偷走该卡
        a.hand.clear()
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(len(a.tavern), 0)
        self.assertEqual(len(minion_hand(g, a)), 1)

    def test_owner_isolation(self):
        g = make_game(seed=1506)
        a, b = g.heroes
        empty_tavern(a)
        empty_tavern(b)
        put_tavern_minion(g, a, DRAGON_T3)
        b_card = put_tavern_minion(g, b, DRAGON_T6)
        bind(g, a, RENDLE)
        self.assertIn(b_card, b.tavern)
        self.assertEqual(minion_hand(g, b), [])
        self.assertEqual(len(minion_hand(g, a)), 1)

    def test_steal_completes_a_triple(self):
        g = make_game(seed=1507)
        a = g.heroes[0]
        empty_tavern(a)
        for _ in range(2):
            a.hand.append(g.create_minion(NON_DEMON, controller=a))
        put_tavern_minion(g, a, NON_DEMON)      # 第三份在馆内
        bind(g, a, RENDLE)
        goldens = [m for m in a.hand if m.is_golden]
        self.assertEqual(len(goldens), 1)
        gd = get_db().golden_version(get_db().get(NON_DEMON))
        self.assertEqual(goldens[0].card_id, gd.id)


# ══════════════════ BG32_MagicItem_821 Pilgrimp Sticker ══════════════════


class TestPilgrimpSticker(unittest.TestCase):
    """821 — One Demon each turn costs Health instead of Gold."""

    def test_arm_tags(self):
        g = make_game(seed=1601)
        a = g.heroes[0]
        d = get_db().get(PILGRIMP)
        bind(g, a, PILGRIMP)
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN),
                         d.num(0))
        self.assertEqual(a.get(GameTag.HEALTH_BUY_RACE), Race.DEMON)

    def test_first_demon_paid_with_health(self):
        g = make_game(seed=1602)
        a = g.heroes[0]
        bind(g, a, PILGRIMP)
        m = put_tavern_minion(g, a, DEMON)
        a.health = 20
        a.gold = 10
        cost = m.get(GameTag.COST, 3)
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertEqual(a.health, 20 - cost)
        self.assertEqual(a.gold, 10)
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 0)

    def test_second_demon_costs_gold(self):
        g = make_game(seed=1603)
        a = g.heroes[0]
        bind(g, a, PILGRIMP)
        m1 = put_tavern_minion(g, a, DEMON)
        m2 = put_tavern_minion(g, a, DEMON)
        a.health = 20
        a.gold = 10
        cost = m1.get(GameTag.COST, 3)
        self.assertTrue(g.buy_from_tavern(a, m1))
        self.assertTrue(g.buy_from_tavern(a, m2))
        self.assertEqual(a.health, 20 - cost)   # 第二次走金币
        self.assertEqual(a.gold, 10 - cost)

    def test_non_demon_uses_gold_and_keeps_quota(self):
        g = make_game(seed=1604)
        a = g.heroes[0]
        bind(g, a, PILGRIMP)
        m = put_tavern_minion(g, a, NON_DEMON)
        a.health = 20
        a.gold = 10
        cost = m.get(GameTag.COST, 3)
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertEqual(a.health, 20)
        self.assertEqual(a.gold, 10 - cost)
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 1)

    def test_insufficient_health_fails_and_keeps_quota(self):
        g = make_game(seed=1605)
        a = g.heroes[0]
        bind(g, a, PILGRIMP)
        m = put_tavern_minion(g, a, DEMON)
        a.health = 2
        a.gold = 10
        self.assertFalse(g.buy_from_tavern(a, m))
        self.assertEqual(a.health, 2)
        self.assertIn(m, a.tavern)
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 1)

    def test_turn_reset_and_owner_isolation(self):
        g = make_game(seed=1606)
        a, b = g.heroes
        bind(g, a, PILGRIMP)
        m = put_tavern_minion(g, a, DEMON)
        a.health = 30
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN), 0)
        # 对手买恶魔不受影响（走金币）
        mb = put_tavern_minion(g, b, DEMON)
        b.gold = 10
        b.health = 30
        self.assertTrue(g.buy_from_tavern(b, mb))
        self.assertEqual(b.health, 30)
        # 真实推进回合 → SoT 重置配额
        g.end_recruit_phase()
        self.assertEqual(a.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN),
                         get_db().get(PILGRIMP).num(0))


# ══════════════════ BG32_MagicItem_822 Bazaar Sticker ══════════════════


class TestBazaarSticker(unittest.TestCase):
    """822 — One Tavern spell each turn costs Health instead of Gold."""

    def test_arm_tag(self):
        g = make_game(seed=1701)
        a = g.heroes[0]
        d = get_db().get(BAZAAR)
        bind(g, a, BAZAAR)
        self.assertEqual(a.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN),
                         d.num(0))

    def test_first_spell_paid_with_health(self):
        g = make_game(seed=1702)
        a = g.heroes[0]
        bind(g, a, BAZAAR)
        s = put_tavern_spell(g, a, SPELL_STATS_ALL)
        a.health = 20
        a.gold = 10
        cost = s.get(GameTag.COST)
        self.assertTrue(g.buy_from_tavern(a, s))
        self.assertEqual(a.health, 20 - cost)
        self.assertEqual(a.gold, 10)
        self.assertEqual(a.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN), 0)

    def test_second_spell_costs_gold(self):
        g = make_game(seed=1703)
        a = g.heroes[0]
        bind(g, a, BAZAAR)
        s1 = put_tavern_spell(g, a, SPELL_STATS_ALL)
        s2 = put_tavern_spell(g, a, SPELL_STATS_ALL)
        a.health = 20
        a.gold = 10
        cost = s1.get(GameTag.COST)
        self.assertTrue(g.buy_from_tavern(a, s1))
        self.assertTrue(g.buy_from_tavern(a, s2))
        self.assertEqual(a.health, 20 - cost)
        self.assertEqual(a.gold, 10 - cost)

    def test_minion_does_not_consume_spell_quota(self):
        g = make_game(seed=1704)
        a = g.heroes[0]
        bind(g, a, BAZAAR)
        m = put_tavern_minion(g, a, NON_DEMON)
        a.health = 20
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertEqual(a.health, 20)
        self.assertEqual(a.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN), 1)
        # 正对照: 随后的法术仍以生命支付
        s = put_tavern_spell(g, a, SPELL_STATS_ALL)
        cost = s.get(GameTag.COST)
        self.assertTrue(g.buy_from_tavern(a, s))
        self.assertEqual(a.health, 20 - cost)

    def test_insufficient_health_fails_and_keeps_quota(self):
        g = make_game(seed=1705)
        a = g.heroes[0]
        bind(g, a, BAZAAR)
        s = put_tavern_spell(g, a, SPELL_STATS_ALL)
        a.health = 2
        a.gold = 10
        self.assertFalse(g.buy_from_tavern(a, s))
        self.assertEqual(a.health, 2)
        self.assertEqual(a.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN), 1)

    def test_turn_reset_and_owner_isolation(self):
        g = make_game(seed=1706)
        a, b = g.heroes
        bind(g, a, BAZAAR)
        sa = put_tavern_spell(g, a, SPELL_STATS_ALL)
        a.health = 30
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, sa))
        self.assertEqual(a.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN), 0)
        sb = put_tavern_spell(g, b, SPELL_STATS_ALL)
        b.health = 30
        b.gold = 10
        self.assertTrue(g.buy_from_tavern(b, sb))
        self.assertEqual(b.health, 30)          # 对手走金币
        g.end_recruit_phase()
        self.assertEqual(a.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN),
                         get_db().get(BAZAAR).num(0))


# ══════════════════ BG32_MagicItem_832 Windfall Portrait ══════════════


class TestWindfallPortrait(unittest.TestCase):
    """832 — EoT: get a Windfall Tornado and give it +{0}/{0}
    (improved by each minion you've sold this turn)."""

    def test_eot_grants_buffed_tornado(self):
        g = make_game(seed=1801)
        a = g.heroes[0]
        d = get_db().get(WINDFALL)
        t = bind(g, a, WINDFALL)
        g.run_script_hook(t, "end_of_turn")
        cards = minion_hand(g, a)
        self.assertEqual(len(cards), 1)
        m = cards[0]
        self.assertEqual(m.card_id, WINDFALL_TOKEN)
        base = get_db().get(WINDFALL_TOKEN)
        self.assertEqual(m.atk, base.atk + d.num(0))
        self.assertEqual(m.max_health, base.health + d.num(0))

    def test_improved_by_minions_sold_this_turn(self):
        g = make_game(seed=1802)
        a = g.heroes[0]
        d = get_db().get(WINDFALL)
        t = bind(g, a, WINDFALL)
        for _ in range(2):
            m = put(g, a, g.create_minion(NON_DEMON, controller=a))
            self.assertTrue(g.sell_minion(a, m))
        g.run_script_hook(t, "end_of_turn")
        m = minion_hand(g, a)[-1]
        base = get_db().get(WINDFALL_TOKEN)
        self.assertEqual(m.atk, base.atk + d.num(0) * 3)
        self.assertEqual(m.max_health, base.health + d.num(0) * 3)

    def test_sold_count_resets_next_turn(self):
        g = make_game(seed=1803)
        a = g.heroes[0]
        d = get_db().get(WINDFALL)
        t = bind(g, a, WINDFALL)
        for _ in range(2):
            m = put(g, a, g.create_minion(NON_DEMON, controller=a))
            g.sell_minion(a, m)
        g.end_recruit_phase()                   # 真实推进: EoT + 新回合
        g.run_script_hook(t, "end_of_turn")     # 新回合售 0
        m = minion_hand(g, a)[-1]
        base = get_db().get(WINDFALL_TOKEN)
        self.assertEqual(m.atk, base.atk + d.num(0))

    def test_opponent_sales_not_counted(self):
        g = make_game(seed=1804)
        a, b = g.heroes
        d = get_db().get(WINDFALL)
        t = bind(g, a, WINDFALL)
        for _ in range(3):
            m = put(g, b, g.create_minion(NON_DEMON, controller=b))
            g.sell_minion(b, m)
        g.run_script_hook(t, "end_of_turn")
        m = minion_hand(g, a)[-1]
        base = get_db().get(WINDFALL_TOKEN)
        self.assertEqual(m.atk, base.atk + d.num(0))

    def test_token_not_from_pool_and_owner_isolation(self):
        g = make_game(seed=1805)
        a, b = g.heroes
        t = bind(g, a, WINDFALL)
        before = g.minion_pool.available(WINDFALL_TOKEN)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(g.minion_pool.available(WINDFALL_TOKEN), before)
        self.assertEqual(minion_hand(g, b), [])
        self.assertEqual(len(minion_hand(g, a)), 1)

    def test_related_chain_and_eot_delivery(self):
        g = make_game(seed=1806)
        a = g.heroes[0]
        d = g.trinket_related_card(WINDFALL)
        self.assertIsNotNone(d)
        self.assertEqual(d.id, WINDFALL_TOKEN)
        self.assertFalse(d.is_pool_minion)
        t = bind(g, a, WINDFALL)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual([m.card_id for m in minion_hand(g, a)],
                         [WINDFALL_TOKEN])


# ══════════════════ BG32_MagicItem_844 Sacrificial Altar ══════════════


class TestSacrificialAltar(unittest.TestCase):
    """844 — Remove all your minions. Gain 3 Gold for each removed."""

    def test_removes_all_and_gains_gold(self):
        g = make_game(seed=1901)
        a = g.heroes[0]
        ms = [put(g, a, g.create_minion(cid, controller=a))
              for cid in (NON_DEMON, DRAGON_T3)]
        a.gold = 0
        bind(g, a, ALTAR)
        self.assertEqual(a.board, [])
        self.assertEqual(a.gold, 3 * len(ms))
        for m in ms:
            self.assertEqual(m.zone, Zone.REMOVED)
            self.assertFalse(m.dead)

    def test_no_death_processing_and_no_pool_return(self):
        g = make_game(seed=1902)
        a = g.heroes[0]
        m = put(g, a, g.create_minion(NON_DEMON, controller=a))
        before = g.minion_pool.available(NON_DEMON)
        a.gold = 0
        bind(g, a, ALTAR)
        self.assertEqual(a.board, [])             # 确实被移除（正证据）
        self.assertEqual(a.gold, 3)
        self.assertFalse(m.dead)
        self.assertEqual(g.minion_pool.available(NON_DEMON), before)
        # 正对照: sell_minion 会回池（证明池断言非空转）
        m2 = put(g, a, g.create_minion(NON_DEMON, controller=a))
        g.minion_pool.acquire(NON_DEMON)
        self.assertTrue(g.sell_minion(a, m2))
        self.assertEqual(g.minion_pool.available(NON_DEMON), before)

    def test_empty_board_noop_and_positive(self):
        g = make_game(seed=1903)
        a = g.heroes[0]
        a.gold = 0
        bind(g, a, ALTAR)
        self.assertEqual(a.gold, 0)
        self.assertEqual(a.board, [])
        # 正对照: 有随从时同钩子移除并给金
        g2 = make_game(seed=1903)
        a2 = g2.heroes[0]
        put(g2, a2, g2.create_minion(NON_DEMON, controller=a2))
        a2.gold = 0
        bind(g2, a2, ALTAR)
        self.assertEqual(a2.board, [])
        self.assertEqual(a2.gold, 3)

    def test_owner_isolation(self):
        g = make_game(seed=1904)
        a, b = g.heroes
        bm = put(g, b, g.create_minion(NON_DEMON, controller=b))
        put(g, a, g.create_minion(NON_DEMON, controller=a))
        bind(g, a, ALTAR)
        self.assertEqual(a.board, [])
        self.assertIn(bm, b.board)

    def test_shop_path_binds_effect(self):
        g = make_game(seed=1905)
        a = g.heroes[0]
        put(g, a, g.create_minion(NON_DEMON, controller=a))
        put(g, a, g.create_minion(DRAGON_T3, controller=a))
        a.gold = 50
        g._offer_trinkets(a, "lesser")
        choice = g.pending_choices.pop(0)
        choice.options = [get_db().get(ALTAR)]
        choice.choose(0)
        self.assertIn(ALTAR, a.trinkets_granted)
        self.assertEqual(a.board, [])
        self.assertEqual(a.gold, 50 - get_db().get(ALTAR).cost + 6)


# ══════════════════ 结构性 / 台账 ══════════════════


class TestBatch15Structural(unittest.TestCase):
    """@engine-only — 注册表 / offer 池档位 / 参数 / DEFERRED 台账守卫。

    结构性断言：钩子 no-op 后仍应通过（登记为引擎数据通道检查）。
    """

    IMPLEMENTED = {
        WORLD_MAP: "WornTreasureMapScript",
        HEART: "HeartOfTheForestScript",
        CURATOR: "CuratorStickerScript",
        EARRINGS: "BloodboundEarringsScript",
        RENDLE: "RendleStickerScript",
        PILGRIMP: "PilgrimpStickerScript",
        BAZAAR: "BazaarStickerScript",
        WINDFALL: "WindfallPortraitScript",
        ALTAR: "SacrificialAltarScript",
    }

    def test_all_registered_and_bound(self):
        self.assertEqual(len(self.IMPLEMENTED), 9)
        for tid, cls in self.IMPLEMENTED.items():
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B15, cls), tid)

    def test_deferred_not_registered(self):
        for tid in DEFERRED:
            self.assertNotIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_pool_membership_at_declared_tier(self):
        db = get_db()
        pool = {d.id for d in db.trinket_offer_pool()}
        tiers = {tid: 11 for tid in self.IMPLEMENTED}
        tiers[CURATOR] = 12          # Curator Sticker 是 Greater（数据核实）
        for tid, school in tiers.items():
            self.assertIn(tid, pool, tid)
            self.assertEqual(db.get(tid).spell_school, school, tid)

    def test_num_matches_text_pinned(self):
        db = get_db()
        self.assertEqual(db.get(WORLD_MAP).num(0), 2)
        self.assertEqual((db.get(HEART).num(0), db.get(HEART).num(1),
                          db.get(HEART).num(2)), (5, 1, 1))
        self.assertEqual(db.get(CURATOR).num(0), 10)
        self.assertEqual((db.get(EARRINGS).num(0), db.get(EARRINGS).num(1)),
                         (4, 4))
        self.assertEqual(db.get(PILGRIMP).num(0), 1)
        self.assertEqual(db.get(BAZAAR).num(0), 1)
        self.assertEqual(db.get(WINDFALL).num(0), 1)

    def test_curator_second_token_carddef_lookup(self):
        d = get_db().get(AMALGAM)
        self.assertIsNotNone(d)
        self.assertIn("venomous", d.keywords)
        self.assertEqual(d.race, Race.ALL)
        self.assertFalse(d.is_pool_minion)

    def test_419_soc_transform_now_persists(self):
        """Yu'lon 的 SoC 金色化**现在跨战斗持久**（2026-09-02 引擎原语
        `_combat_transforms` 战后重放; RULES §3.5 例外）——旧断言
        "被快照回滚" 已过时，本测试改为验证新契约（419 可迁移）。"""
        g = make_game(seed=1906)
        a, b = g.heroes
        put(g, a, g.create_minion(DRAGON_T3, controller=a))
        put(g, a, g.create_minion(DRAGON_T6, controller=a))
        from hsrl2.scripts.batches.batch_battlecry import _goldenize
        seen = {}

        def probe_soc(s, gg, c=None, **kw):
            dragons = [m for m in s.controller.board
                       if m.race in (Race.DRAGON, Race.ALL)
                       and not m.is_golden]
            best = max(dragons, key=lambda m: m.tech_level)
            _goldenize(gg, best)               # 模拟 419 的 SoC 效果
            seen["during"] = [m.is_golden for m in s.controller.board]

        probe = g.create_minion(NON_DEMON, controller=a)
        probe.scripts = type("P", (), {
            "start_of_combat": staticmethod(probe_soc)})()
        put(g, a, probe)
        g.run_combat(a, b)
        # SoC 内确实成功金色化（正证据）
        self.assertIn(True, seen["during"])
        # 战后重放: 金色化保留（旧实现此处为 False）
        golden = [m for m in a.board if m.is_golden]
        self.assertEqual(len(golden), 1)
        self.assertEqual(golden[0].get(GameTag.TRIPLE_BASE_CARD_ID),
                         DRAGON_T6)
        self.assertEqual(golden[0].card_id,
                         get_db().golden_version(
                             get_db().get(DRAGON_T6)).id)


if __name__ == "__main__":
    unittest.main()
