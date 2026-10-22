"""批次 trinkets27 行为层测试（3 张注册饰品 + 7 张 DEFERRED 台账守卫，
作业单 2026-09-14；原 15 张 DEFERRED，2026-09-18 复核收敛）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线; 副本条款用
    `duplicate=True`）
  - 刷新 / 展示位: 真实 `game.refresh_tavern`（档位协议读取点）
  - 施法: 真实 `game.play_spell`（`spell_resolving` / `spell_resolved`
    两个时点均在生产路径广播——RULES §7.4.12）
  - 购买 / 以生命代金: 真实 `game.buy_from_tavern`（`HEALTH_BUY` 实体
    标记的唯一消费点）
  - 池: `minion_pool.total_remaining()` / `available()`
  - 跨回合: 真实 `game.end_recruit_phase`（回合开始自动刷新走同一
    `refresh_tavern`；监听器随回合存续）

覆盖（SOP §16 空转测试判定法）: 每个行为测试方法至少含一条**正效果**
断言，负/正对照写在**同一方法内**；owner 隔离（2 英雄）; 跨回合与
一次性语义; 落空不消耗资源; 池占返配平（含金馆 `GILDED_NOT_TRIPLED`）;
满手 `pending_hand_queue`; 副本条款（两份）; 同 seed 确定性;
`CardDef.num` 双向钉死; 无弱断言（一律 `assertEqual` 钉死数值/身份，
禁 `>= 1`）。

**本批无 Discover / 无亡语 / 无战斗内钩子**——因此
"Discover `len(options) == N`"、"Titus 亡语倍率"、"战斗内 SoC"三类
通用覆盖项在本批**不适用**（3 张 CORRECT 卡分别是展示位协议、
`spell_resolved` 后置被动、购买计数）；不存在被跳过的同类卡。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 本批 id（CardDB 按名核实——禁止凭记忆写）
INNKEEPERS_STEIN = "BG30_MagicItem_423"
GLOWSCALE_PORTRAIT = "BG30_MagicItem_548"
EYE_OF_SARGERAS = "BG30_MagicItem_701"

DEFERRED_IDS = [
    "BG30_MagicItem_402",   # Conductor Portrait — 弃牌系统缺失
    "BG30_MagicItem_416",   # Token of the Old Gods — 两段定向选择链
    "BG30_MagicItem_431",   # Azerite Portrait — 载荷 + 卡家族追加效果
    "BG30_MagicItem_707",   # Tickatus Sticker — Darkmoon Prize 卡池
    "BG30_MagicItem_711",   # Marine Signet — improve 档位增量权威
]
# 418 Bronzebeard / 825 Smuggler Portrait 已由 batch_family_races 注册
# （2026-09-21，RACES 家族类型身份改写 + Tavern/Discover 作用域）
# → 移出本 DEFERRED 台账（守卫见 test_batch_family_races）。

# 803 Kaboom Bot Portrait 已由 batch_trinkets39 注册（2026-09-18——家族
# 亡语伤害加成读取点 RULES §7.4.16 `family_flags` + 金色逐实例 +10 口径
# 按 wiki 无 Notes → 卡面天然语言）→ 移出本 DEFERRED 台账

# 777 Goose Portrait 已由 batch_goose_lucky_egg 注册（2026-09-17——
# 次生载荷 `BG30_104`/`_G` 由本批补齐）→ 移出本 DEFERRED 台账
# （守卫见 test_batch_goose_lucky_egg）

# 440 Boom Controller / 804 Ancient Wishbone / 822 Twin Sky Lanterns 已由
# batch_trinkets32 注册（2026-09-15）→ 移出本 DEFERRED 台账
CORRECT_IDS = [INNKEEPERS_STEIN, GLOWSCALE_PORTRAIT, EYE_OF_SARGERAS]

# 关联卡 / 测试用既有卡（CardDB 按名核实）
TIMEWARPED_GLOWSCALE = "BG34_Giant_035"    # 548 载荷（token, T5）
RUSHING_WINDS = "BG33_Reward_006t"         # Spellcraft 法术（给圣盾，无属性）
MINI_TRIDENT = "BG23_000t"                 # Spellcraft 法术（+2 攻击）
DUMMY = "BG25_013"                         # Rot Hide Gnoll 1/4 T1（无触发）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 2701) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str, duplicate: bool = False):
    e = game.grant_trinket(hero, tid, duplicate=duplicate)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def pool_total(game: Game) -> int:
    return game.minion_pool.total_remaining()


def clear_tavern(game: Game, hero: Hero) -> None:
    """把当前展示区内容原样回池并清空（用于精确测量"本次刷新抽了几张"）。"""
    for e in list(hero.tavern):
        if isinstance(e, Minion):
            base = e.get(GameTag.TRIPLE_BASE_CARD_ID, None) or e.card_id
            game.minion_pool.release(base, 1)
        else:
            game.spell_pool.release(e.card_id)
    hero.tavern.clear()


def tavern_minions(hero: Hero):
    return [e for e in hero.tavern if isinstance(e, Minion)]


def give_spell(game: Game, hero: Hero, card_id: str,
               spellcraft: bool) -> object:
    """造一张入手法术（`spellcraft=True` 时打上法术塑造 tag——引擎在
    `spellcraft.generate_for_hero` / `create_spell` 生成路径上打同一 tag）。"""
    s = game.create_spell(card_id, controller=hero)
    assert s is not None
    if spellcraft:
        s.set(GameTag.SPELLCRAFT, True)
    hero.hand.append(s)
    return s


def set_health(hero: Hero, hp: int) -> None:
    hero.set(GameTag.HEALTH2, hp)
    hero.set(GameTag.BASE_HEALTH, hp)


def buy_first_minion(game: Game, hero: Hero) -> bool:
    mins = tavern_minions(hero)
    assert mins, "酒馆无随从"
    return game.buy_from_tavern(hero, mins[0])


def buy_first_spell(game: Game, hero: Hero) -> bool:
    spells = [e for e in hero.tavern if not isinstance(e, Minion)]
    assert spells, "酒馆无法术"
    return game.buy_from_tavern(hero, spells[0])


# ══════════════ 注册表 / DEFERRED 台账（结构性） ══════════════


class TestRegistryLedger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链守卫。

    这些断言与脚本钩子无关（把钩子换成 no-op 仍应通过）——按 SOP §16
    末段显式标注，避免被空转审计误判为"行为测试空转"。
    """

    def test_all_registered(self):
        self.assertEqual(len(CORRECT_IDS), 3)
        for tid in CORRECT_IDS:
            self.assertIsNotNone(REGISTRY.get(tid), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_deferred_not_registered(self):
        # 439 Designer Eyepatch 已由 batch_misc_final 注册（2026-09-02）
        # 828/777/803 已注册迁出; 418/825 已由 batch_family_races 注册
        # （2026-09-21）→ 7 降为 5
        self.assertEqual(len(DEFERRED_IDS), 5)
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_num_params_match_carddef(self):
        db = get_db()
        self.assertEqual((db.get(GLOWSCALE_PORTRAIT).num(0),
                          db.get(GLOWSCALE_PORTRAIT).num(1)), (3, 3))
        self.assertEqual(db.get(EYE_OF_SARGERAS).num(0), 3)
        for i in range(4):
            self.assertIsNone(db.get(INNKEEPERS_STEIN).num(i), i)

    def test_related_card_data_chain(self):
        db = get_db()
        self.assertEqual(
            db.by_dbf(db.get(GLOWSCALE_PORTRAIT).evolution_card_id).id,
            TIMEWARPED_GLOWSCALE)
        # 423 / 701 不交付卡牌 → 数据链为空（脚本亦不读取）
        self.assertIsNone(db.get(INNKEEPERS_STEIN).evolution_card_id)
        self.assertIsNone(db.get(EYE_OF_SARGERAS).evolution_card_id)

    def test_deferred_ids_are_offer_pool_members(self):
        pool = {d.id for d in get_db().trinket_offer_pool()}
        for tid in CORRECT_IDS + DEFERRED_IDS:
            self.assertIn(tid, pool, tid)


# ══════════════ BG30_MagicItem_423 Innkeeper's Stein ══════════════


class TestInnkeepersStein(unittest.TestCase):
    """展示位档位协议（RULES §7.4.13）——额外 1 个"高一档"随从位。"""

    def test_extra_higher_tier_slot_on_refresh(self):
        """正对照（无饰品）与正例（有饰品）**同一方法内**对照。"""
        tier = 3
        plain = make_game(seed=2701)
        a0 = plain.heroes[0]
        a0.set(GameTag.TAVERN_TIER, tier)
        a0.gold = 40
        clear_tavern(plain, a0)
        plain.refresh_tavern(a0, free=True)
        base_tiers = sorted(m.tech_level for m in tavern_minions(a0))
        self.assertEqual(len(base_tiers), C.TAVERN_OFFERS[tier])
        self.assertEqual([t for t in base_tiers if t > tier], [])

        g = make_game(seed=2701)
        a = g.heroes[0]
        bind(g, a, INNKEEPERS_STEIN)
        a.set(GameTag.TAVERN_TIER, tier)
        a.gold = 40
        clear_tavern(g, a)
        g.refresh_tavern(a, free=True)
        tiers = sorted(m.tech_level for m in tavern_minions(a))
        self.assertEqual(len(tiers), C.TAVERN_OFFERS[tier] + 1)
        # 恰好多出**一个** tier+1 的展示位
        self.assertEqual(tiers.count(tier + 1), 1)
        self.assertEqual([t for t in tiers if t > tier + 1], [])

    def test_owner_isolation(self):
        g = make_game(seed=2702)
        a, b = g.heroes
        bind(g, a, INNKEEPERS_STEIN)
        for h in (a, b):
            h.set(GameTag.TAVERN_TIER, 3)
            h.gold = 40
            clear_tavern(g, h)
        g.refresh_tavern(b, free=True)
        b_tiers = sorted(m.tech_level for m in tavern_minions(b))
        self.assertEqual(len(b_tiers), C.TAVERN_OFFERS[3])
        self.assertEqual([t for t in b_tiers if t > 3], [])
        # 正对照: 绑定者的下一次刷新确实多出越档位
        g.refresh_tavern(a, free=True)
        a_tiers = sorted(m.tech_level for m in tavern_minions(a))
        self.assertEqual(len(a_tiers), C.TAVERN_OFFERS[3] + 1)
        self.assertEqual(a_tiers.count(4), 1)

    def test_tier_five_gives_tier_six(self):
        g = make_game(seed=2703)
        a = g.heroes[0]
        bind(g, a, INNKEEPERS_STEIN)
        a.set(GameTag.TAVERN_TIER, 5)
        a.gold = 40
        clear_tavern(g, a)
        g.refresh_tavern(a, free=True)
        tiers = sorted(m.tech_level for m in tavern_minions(a))
        self.assertEqual(len(tiers), C.TAVERN_OFFERS[5] + 1)
        self.assertEqual(tiers.count(6), 1)

    def test_capped_at_max_tavern_tier(self):
        """酒馆等级 6（上限档）: 额外位仍存在但封顶 `max_tavern_tier`，
        绝不越 T7（引擎缺省 `min(tavern_tier + 1, max_tavern_tier)`）。"""
        g = make_game(seed=2704)
        a = g.heroes[0]
        bind(g, a, INNKEEPERS_STEIN)
        a.set(GameTag.TAVERN_TIER, 6)
        a.gold = 40
        clear_tavern(g, a)
        g.refresh_tavern(a, free=True)
        tiers = sorted(m.tech_level for m in tavern_minions(a))
        self.assertEqual(len(tiers), C.TAVERN_OFFERS[6] + 1)
        self.assertEqual([t for t in tiers if t > g.max_tavern_tier], [])
        self.assertNotIn(g.max_tavern_tier + 1, tiers)

    def test_two_copies_give_two_extra_slots(self):
        g = make_game(seed=2705)
        a = g.heroes[0]
        bind(g, a, INNKEEPERS_STEIN)
        bind(g, a, INNKEEPERS_STEIN, duplicate=True)
        a.set(GameTag.TAVERN_TIER, 3)
        a.gold = 40
        clear_tavern(g, a)
        g.refresh_tavern(a, free=True)
        tiers = sorted(m.tech_level for m in tavern_minions(a))
        self.assertEqual(len(tiers), C.TAVERN_OFFERS[3] + 2)
        self.assertEqual(tiers.count(4), 2)

    def test_pool_accounting_matches_extra_draw(self):
        """池占返配平: 清空展示区后，本次刷新恰好占池
        `TAVERN_OFFERS[tier]`（正对照）+ 1（额外位）。"""
        tier = 3
        plain = make_game(seed=2706)
        a0 = plain.heroes[0]
        a0.set(GameTag.TAVERN_TIER, tier)
        a0.gold = 40
        clear_tavern(plain, a0)
        p0 = pool_total(plain)
        plain.refresh_tavern(a0, free=True)
        plain_drawn = p0 - pool_total(plain)
        self.assertEqual(plain_drawn, C.TAVERN_OFFERS[tier])

        g = make_game(seed=2706)
        a = g.heroes[0]
        bind(g, a, INNKEEPERS_STEIN)
        a.set(GameTag.TAVERN_TIER, tier)
        a.gold = 40
        clear_tavern(g, a)
        p1 = pool_total(g)
        g.refresh_tavern(a, free=True)
        drawn = p1 - pool_total(g)
        self.assertEqual(drawn, C.TAVERN_OFFERS[tier] + 1)
        # 再次刷新: 旧内容回池 + 新内容占池 → 净变化 0（无泄漏）
        p2 = pool_total(g)
        g.refresh_tavern(a, free=True)
        self.assertEqual(p2 - pool_total(g), 0)

    def test_golden_arena_extra_slot_is_gilded_not_tripled(self):
        """金馆（The Golden Arena）下额外位同样走金色化分支，且按
        `GILDED_NOT_TRIPLED` 记账（非三连金——RULES §2.3/§7.4.13）。"""
        g = make_game(seed=2707)
        a = g.heroes[0]
        bind(g, a, INNKEEPERS_STEIN)
        g._tavern_golden = True
        a.set(GameTag.TAVERN_TIER, 3)
        a.gold = 40
        clear_tavern(g, a)
        p0 = pool_total(g)
        g.refresh_tavern(a, free=True)
        extra = [m for m in tavern_minions(a) if m.tech_level == 4]
        self.assertEqual(len(extra), 1)
        self.assertTrue(extra[0].is_golden)
        self.assertTrue(extra[0].get(GameTag.GILDED_NOT_TRIPLED, False))
        # 每个展示位仍只占池 1 份（金色本体不额外扣池）
        self.assertEqual(p0 - pool_total(g), C.TAVERN_OFFERS[3] + 1)

    def test_persists_across_recruit_turn(self):
        g = make_game(seed=2708)
        a = g.heroes[0]
        bind(g, a, INNKEEPERS_STEIN)
        a.set(GameTag.TAVERN_TIER, 3)
        g.end_recruit_phase()
        self.assertEqual(g.turn, 2)
        tiers = sorted(m.tech_level for m in tavern_minions(a))
        self.assertEqual(tiers.count(a.tavern_tier + 1), 1)

    def test_same_seed_deterministic(self):
        def run(seed):
            g = make_game(seed=seed)
            a = g.heroes[0]
            bind(g, a, INNKEEPERS_STEIN)
            a.set(GameTag.TAVERN_TIER, 3)
            a.gold = 40
            clear_tavern(g, a)
            g.refresh_tavern(a, free=True)
            return [(m.card_id, m.tech_level) for m in tavern_minions(a)]
        self.assertEqual(run(2709), run(2709))
        self.assertEqual(len(run(2709)), C.TAVERN_OFFERS[3] + 1)


# ══════════════ BG30_MagicItem_548 Glowscale Portrait ══════════════


class TestGlowscalePortrait(unittest.TestCase):
    """`spell_resolved` 后置施法被动（RULES §7.4.10/§7.4.12）。"""

    def test_bind_grants_payload_and_pool_balance(self):
        g = make_game(seed=2711)
        a = g.heroes[0]
        p0 = pool_total(g)
        hand0 = [e.card_id for e in a.hand]
        bind(g, a, GLOWSCALE_PORTRAIT)
        self.assertEqual([e.card_id for e in a.hand],
                         hand0 + [TIMEWARPED_GLOWSCALE])
        # token → 零池操作（RULES §2.3/§7.4.6）
        self.assertEqual(pool_total(g), p0)
        # 负对照: 同一 setup 无饰品 → 手牌不变
        g2 = make_game(seed=2711)
        a2 = g2.heroes[0]
        self.assertNotIn(TIMEWARPED_GLOWSCALE, [e.card_id for e in a2.hand])

    def test_after_cast_buffs_divine_shield_minions(self):
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2712)
        a = g.heroes[0]
        bind(g, a, GLOWSCALE_PORTRAIT)
        ds = put(g, a, DUMMY)
        ds.set(GameTag.DIVINE_SHIELD, True)
        plain = put(g, a, DUMMY)
        # 用**不授予圣盾**的法术塑造法术（Mini-Trident: +2 攻击直到下回合）
        # ——否则目标会因本次施放获得圣盾而被本次加成命中（见后置语义测试）
        spell = give_spell(g, a, MINI_TRIDENT, spellcraft=True)
        self.assertTrue(g.play_spell(a, spell, target=plain))
        # 带圣盾者 +num(0)/+num(1)，不带者只吃法术自身效果（同方法负对照）
        self.assertEqual((ds.atk, ds.health),
                         (get_db().get(DUMMY).atk + d.num(0),
                          get_db().get(DUMMY).health + d.num(1)))
        self.assertFalse(plain.has(GameTag.DIVINE_SHIELD))
        self.assertEqual((plain.atk, plain.health),
                         (get_db().get(DUMMY).atk + 2,
                          get_db().get(DUMMY).health))
        # 无饰品对照: 同操作不改任何属性
        g2 = make_game(seed=2712)
        a2 = g2.heroes[0]
        ds2 = put(g2, a2, DUMMY)
        ds2.set(GameTag.DIVINE_SHIELD, True)
        pl2 = put(g2, a2, DUMMY)
        spell2 = give_spell(g2, a2, MINI_TRIDENT, spellcraft=True)
        g2.play_spell(a2, spell2, target=pl2)
        self.assertEqual((ds2.atk, ds2.health),
                         (get_db().get(DUMMY).atk,
                          get_db().get(DUMMY).health))

    def test_after_cast_is_post_resolution(self):
        """证伪探针: 本次施放**刚给出**圣盾的随从也吃到本次加成
        （`spell_resolving` 前置实现不成立——RULES §7.4.12）。"""
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2713)
        a = g.heroes[0]
        bind(g, a, GLOWSCALE_PORTRAIT)
        target = put(g, a, DUMMY)
        self.assertFalse(target.has(GameTag.DIVINE_SHIELD))
        spell = give_spell(g, a, RUSHING_WINDS, spellcraft=True)
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertTrue(target.has(GameTag.DIVINE_SHIELD))
        self.assertEqual((target.atk, target.health),
                         (get_db().get(DUMMY).atk + d.num(0),
                          get_db().get(DUMMY).health + d.num(1)))

    def test_non_spellcraft_spell_does_not_trigger(self):
        """同一方法内正负对照: 同一张法术带/不带 SPELLCRAFT tag。"""
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2714)
        a = g.heroes[0]
        bind(g, a, GLOWSCALE_PORTRAIT)
        ds = put(g, a, DUMMY)
        ds.set(GameTag.DIVINE_SHIELD, True)
        # 负例: 不打 SPELLCRAFT tag
        plain_spell = give_spell(g, a, RUSHING_WINDS, spellcraft=False)
        self.assertFalse(plain_spell.has(GameTag.SPELLCRAFT))
        self.assertTrue(g.play_spell(a, plain_spell, target=ds))
        self.assertEqual((ds.atk, ds.health),
                         (get_db().get(DUMMY).atk,
                          get_db().get(DUMMY).health))
        # 正例: 同一法术打上 tag
        craft_spell = give_spell(g, a, RUSHING_WINDS, spellcraft=True)
        self.assertTrue(g.play_spell(a, craft_spell, target=ds))
        self.assertEqual((ds.atk, ds.health),
                         (get_db().get(DUMMY).atk + d.num(0),
                          get_db().get(DUMMY).health + d.num(1)))

    def test_owner_isolation(self):
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2715)
        a, b = g.heroes
        bind(g, a, GLOWSCALE_PORTRAIT)
        a_ds = put(g, a, DUMMY)
        a_ds.set(GameTag.DIVINE_SHIELD, True)
        b_ds = put(g, b, DUMMY)
        b_ds.set(GameTag.DIVINE_SHIELD, True)
        # A 施放: A 的圣盾随从被加成; B 的圣盾随从不变（owner 隔离）
        spell = give_spell(g, a, MINI_TRIDENT, spellcraft=True)
        self.assertTrue(g.play_spell(a, spell, target=a_ds))
        self.assertEqual((b_ds.atk, b_ds.health),
                         (get_db().get(DUMMY).atk,
                          get_db().get(DUMMY).health))
        self.assertEqual((a_ds.atk, a_ds.health),
                         (get_db().get(DUMMY).atk + 2 + d.num(0),
                          get_db().get(DUMMY).health + d.num(1)))
        # 正对照: B 也持有饰品后，**只有 B 自己施放**才触发 B 的饰品
        bind(g, b, GLOWSCALE_PORTRAIT)
        b_plain = put(g, b, DUMMY)
        spell_b = give_spell(g, b, MINI_TRIDENT, spellcraft=True)
        self.assertTrue(g.play_spell(g.heroes[1], spell_b, target=b_plain))
        self.assertEqual(b_plain.atk, get_db().get(DUMMY).atk + 2)
        self.assertEqual(b_plain.health, get_db().get(DUMMY).health)
        self.assertEqual((b_ds.atk, b_ds.health),
                         (get_db().get(DUMMY).atk + d.num(0),
                          get_db().get(DUMMY).health + d.num(1)))
        # A 的随从不再因 B 的施放变化
        self.assertEqual((a_ds.atk, a_ds.health),
                         (get_db().get(DUMMY).atk + 2 + d.num(0),
                          get_db().get(DUMMY).health + d.num(1)))

    def test_double_cast_triggers_per_cast(self):
        """双施（棋盘 `SPELL_DOUBLER`）按**施放次数**各结算一次。"""
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2716)
        a = g.heroes[0]
        bind(g, a, GLOWSCALE_PORTRAIT)
        target = put(g, a, DUMMY)
        doubler = put(g, a, DUMMY)
        doubler.set(GameTag.SPELL_DOUBLER, True)
        spell = give_spell(g, a, RUSHING_WINDS, spellcraft=True)
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.health),
                         (get_db().get(DUMMY).atk + 2 * d.num(0),
                          get_db().get(DUMMY).health + 2 * d.num(1)))
        # 无 doubler 对照: 只结算一次
        g2 = make_game(seed=2716)
        a2 = g2.heroes[0]
        bind(g2, a2, GLOWSCALE_PORTRAIT)
        t2 = put(g2, a2, DUMMY)
        spell2 = give_spell(g2, a2, RUSHING_WINDS, spellcraft=True)
        g2.play_spell(a2, spell2, target=t2)
        self.assertEqual(t2.atk, get_db().get(DUMMY).atk + d.num(0))

    def test_no_divine_shield_minions_is_noop(self):
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2717)
        a = g.heroes[0]
        bind(g, a, GLOWSCALE_PORTRAIT)
        target = put(g, a, DUMMY)
        spell = give_spell(g, a, MINI_TRIDENT, spellcraft=True)
        before = (target.atk, target.health)
        self.assertTrue(g.play_spell(a, spell, target=target))
        # 无圣盾随从 → 本卡不产生任何加成（法术自身效果照常）
        self.assertEqual((target.atk, target.health),
                         (before[0] + 2, before[1]))
        self.assertFalse(target.has(GameTag.DIVINE_SHIELD))
        # 正对照（同一方法内）: 给同一目标圣盾后再次施放 → 确实 +num(0)/+num(1)
        target.set(GameTag.DIVINE_SHIELD, True)
        spell2 = give_spell(g, a, MINI_TRIDENT, spellcraft=True)
        self.assertTrue(g.play_spell(a, spell2, target=target))
        self.assertEqual((target.atk, target.health),
                         (before[0] + 2 + 2 + d.num(0),
                          before[1] + d.num(1)))

    def test_two_copies_stack(self):
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2718)
        a = g.heroes[0]
        bind(g, a, GLOWSCALE_PORTRAIT)
        bind(g, a, GLOWSCALE_PORTRAIT, duplicate=True)
        self.assertEqual(len(a.trinkets), 2)
        ds = put(g, a, DUMMY)
        ds.set(GameTag.DIVINE_SHIELD, True)
        spell = give_spell(g, a, RUSHING_WINDS, spellcraft=True)
        self.assertTrue(g.play_spell(a, spell, target=ds))
        self.assertEqual((ds.atk, ds.health),
                         (get_db().get(DUMMY).atk + 2 * d.num(0),
                          get_db().get(DUMMY).health + 2 * d.num(1)))

    def test_full_hand_queues_payload(self):
        g = make_game(seed=2719)
        a = g.heroes[0]
        while not a.hand_full():
            a.hand.append(g.create_minion(DUMMY, controller=a))
        self.assertTrue(a.hand_full())
        self.assertEqual(len(g.pending_hand_queue), 0)
        bind(g, a, GLOWSCALE_PORTRAIT)
        # 满手 → 副本进等待队列（必然交付，不销毁——RULES §3.3/§7.4.6）
        self.assertEqual(len(g.pending_hand_queue), 1)
        hero, entity = g.pending_hand_queue[0]
        self.assertIs(hero, a)
        self.assertEqual(entity.card_id, TIMEWARPED_GLOWSCALE)

    def test_listener_persists_across_recruit_turn(self):
        d = get_db().get(GLOWSCALE_PORTRAIT)
        g = make_game(seed=2720)
        a = g.heroes[0]
        bind(g, a, GLOWSCALE_PORTRAIT)
        g.end_recruit_phase()
        self.assertEqual(g.turn, 2)
        ds = put(g, a, DUMMY)
        ds.set(GameTag.DIVINE_SHIELD, True)
        spell = give_spell(g, a, RUSHING_WINDS, spellcraft=True)
        self.assertTrue(g.play_spell(a, spell, target=ds))
        self.assertEqual(ds.atk, get_db().get(DUMMY).atk + d.num(0))


# ══════════════ BG30_MagicItem_701 The Eye of Sargeras ══════════════


class TestEyeOfSargeras(unittest.TestCase):
    """以生命代金购买（实体级 `HEALTH_BUY`，RULES §7.4.7 来源 2）。"""

    @staticmethod
    def _setup(seed: int, *, tier: int = 3, gold: int = 60,
               hp: int = 60, bind_trinket: bool = True,
               duplicates: int = 1):
        g = make_game(seed=seed)
        a = g.heroes[0]
        for i in range(duplicates):
            if bind_trinket:
                bind(g, a, EYE_OF_SARGERAS, duplicate=bool(i))
        a.gold = gold
        set_health(a, hp)
        a.set(GameTag.TAVERN_TIER, tier)
        clear_tavern(g, a)
        g.refresh_tavern(a, free=True)
        return g, a

    @staticmethod
    def _buy_three(g, a):
        """买满 3 张（此时应武装——第 4 张以生命支付）。"""
        costs = []
        for _ in range(3):
            mins = tavern_minions(a)
            assert mins, "酒馆随从不足"
            cost = mins[0].get(GameTag.COST, C.MINION_BUY_COST)
            assert g.buy_from_tavern(a, mins[0])
            costs.append(cost)
        return costs

    def test_fourth_purchase_costs_health(self):
        g, a = self._setup(seed=2731)
        set_health(a, 60)
        gold0 = a.gold
        costs = self._buy_three(g, a)
        self.assertEqual(a.gold, gold0 - sum(costs))     # 前 3 张扣金币
        hp_before = a.health
        gold_before = a.gold
        target = tavern_minions(a)[0]
        cost = target.get(GameTag.COST, C.MINION_BUY_COST)
        self.assertTrue(g.buy_from_tavern(a, target))
        # 第 4 张: 金币不变、生命 −= 金币价（"instead of Gold"）
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.health, hp_before - cost)

    def test_fifth_purchase_returns_to_gold_and_marks_cleared(self):
        g, a = self._setup(seed=2732)
        set_health(a, 60)
        self._buy_three(g, a)
        fourth = tavern_minions(a)[0]
        fourth_cost = fourth.get(GameTag.COST, C.MINION_BUY_COST)
        hp_before = a.health
        gold_before = a.gold
        self.assertTrue(g.buy_from_tavern(a, fourth))     # 第 4 张（生命）
        # 正效果: 第 4 张确实以生命支付（本卡的武装/支付链真的跑过）
        self.assertEqual(a.health, hp_before - fourth_cost)
        self.assertEqual(a.gold, gold_before)
        # 解除武装: 馆内剩余实体不再带 HEALTH_BUY（逐一钉死）
        remaining = list(a.tavern)
        self.assertTrue(remaining)
        self.assertEqual([e.get(GameTag.HEALTH_BUY, False)
                          for e in remaining], [False] * len(remaining))
        g.refresh_tavern(a, free=True)
        gold_before = a.gold
        hp_before = a.health
        target = tavern_minions(a)[0]
        cost = target.get(GameTag.COST, C.MINION_BUY_COST)
        self.assertTrue(g.buy_from_tavern(a, target))
        self.assertEqual(a.gold, gold_before - cost)     # 第 5 张回到金币
        self.assertEqual(a.health, hp_before)

    def test_counter_persists_across_turns(self):
        g, a = self._setup(seed=2733)
        set_health(a, 60)
        for _ in range(2):
            self.assertTrue(buy_first_minion(g, a))
        g.end_recruit_phase()
        self.assertEqual(g.turn, 2)
        # 第 3 张（新回合，馆内容为自动刷新后的新实体 → 入馆补标）
        self.assertTrue(buy_first_minion(g, a))
        self.assertTrue(all(e.get(GameTag.HEALTH_BUY, False)
                            for e in a.tavern))
        gold_before = a.gold
        hp_before = a.health
        target = tavern_minions(a)[0]
        cost = target.get(GameTag.COST, C.MINION_BUY_COST)
        self.assertTrue(g.buy_from_tavern(a, target))
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.health, hp_before - cost)

    def test_spell_purchase_counts(self):
        g, a = self._setup(seed=2734)
        set_health(a, 60)
        self._buy_three(g, a)
        spells = [e for e in a.tavern if not isinstance(e, Minion)]
        self.assertTrue(spells, "酒馆无法术")
        self.assertTrue(spells[0].get(GameTag.HEALTH_BUY, False))
        cost = spells[0].get(GameTag.COST, C.MINION_BUY_COST)
        gold_before = a.gold
        hp_before = a.health
        self.assertTrue(g.buy_from_tavern(a, spells[0]))
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.health, hp_before - cost)

    def test_insufficient_health_fails_without_consuming(self):
        g, a = self._setup(seed=2735)
        set_health(a, 60)
        self._buy_three(g, a)
        set_health(a, 1)                    # 生命 + 护甲 ≤ 价格
        target = tavern_minions(a)[0]
        gold_before = a.gold
        self.assertFalse(g.buy_from_tavern(a, target))
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.health, 1)
        self.assertTrue(target.get(GameTag.HEALTH_BUY, False))   # 标记保留
        # 足量后同一张卡仍以生命支付（落空不消耗）
        set_health(a, 60)
        cost = target.get(GameTag.COST, C.MINION_BUY_COST)
        gold_before = a.gold
        self.assertTrue(g.buy_from_tavern(a, target))
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.health, 60 - cost)

    def test_owner_isolation(self):
        g, a = self._setup(seed=2736)
        b = g.heroes[1]
        b.gold = 60
        set_health(b, 60)
        b.set(GameTag.TAVERN_TIER, 3)
        clear_tavern(g, b)
        g.refresh_tavern(b, free=True)
        # 对手酒馆实体从未被打标
        self.assertTrue(b.tavern)
        self.assertEqual([e.get(GameTag.HEALTH_BUY, False) for e in b.tavern],
                         [False] * len(b.tavern))
        for _ in range(3):
            self.assertTrue(buy_first_minion(g, b))
        # A 的计数不被 B 的购买推进: A 买 3 张后才武装
        self.assertTrue(a.tavern)
        self.assertEqual([e.get(GameTag.HEALTH_BUY, False) for e in a.tavern],
                         [False] * len(a.tavern))
        self._buy_three(g, a)
        self.assertTrue(all(e.get(GameTag.HEALTH_BUY, False)
                            for e in tavern_minions(a)))
        # B 的第 4 张仍按金币（对手不受本人饰品影响）
        gold_before = b.gold
        hp_before = b.health
        self.assertTrue(buy_first_minion(g, b))
        self.assertLess(b.gold, gold_before)
        self.assertEqual(b.health, hp_before)

    def test_does_not_clear_other_source_mark(self):
        """另一来源预先设的 `HEALTH_BUY` 不被本人解除武装清除
        （SOP §16b item 28/29——多来源状态不得互相覆盖）。"""
        g, a = self._setup(seed=2737)
        set_health(a, 60)
        spells = [e for e in a.tavern if not isinstance(e, Minion)]
        self.assertTrue(spells)
        other = spells[0]           # 法术不会被 `buy_first_minion` 买走
        other.set(GameTag.HEALTH_BUY, True)
        self._buy_three(g, a)
        hp_before = a.health
        self.assertTrue(buy_first_minion(g, a))          # 第 4 张 → 解除武装
        # 正效果先证: 本卡的支付链确实跑过（否则"标记仍在"无信息量）
        self.assertEqual(a.health, hp_before - 3)
        self.assertIn(other, a.tavern)
        self.assertTrue(other.get(GameTag.HEALTH_BUY, False))

    def test_two_copies_single_health_payment_per_cycle(self):
        d = get_db().get(EYE_OF_SARGERAS)
        g, a = self._setup(seed=2738, duplicates=2)
        self.assertEqual(len(a.trinkets), 2)
        self.assertEqual(d.num(0), 3)
        set_health(a, 60)
        gold_before = a.gold
        self._buy_three(g, a)
        hp_before = a.health
        self.assertTrue(buy_first_minion(g, a))          # 第 4 张: 一次生命
        self.assertEqual(a.health, hp_before - 3)
        self.assertNotEqual(a.gold, gold_before)
        # 再买 3 张（金币），第 8 张再次生命支付——两份副本不叠加
        g.refresh_tavern(a, free=True)
        self._buy_three(g, a)
        self.assertTrue(a.tavern)
        self.assertEqual([e.get(GameTag.HEALTH_BUY, False) for e in a.tavern],
                         [True] * len(a.tavern))
        hp_before = a.health
        gold_before = a.gold
        self.assertTrue(buy_first_minion(g, a))
        self.assertEqual(a.gold, gold_before)
        self.assertEqual(a.health, hp_before - 3)


if __name__ == "__main__":
    unittest.main()
