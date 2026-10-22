"""批次 trinkets24 行为层测试（5 张饰品注册 + 15 张 DEFERRED 台账守卫）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）
  - 关联卡授予: `game.grant_trinket_related_card` /
    `grant_card_copy_to_hand`（RULES §7.4.6）
  - 摧毁: `game.destroy_minion`（唯一广播 `minion_destroyed` 的入口
    ——RULES §7.4.11）+ 真实 Maw Caster 战吼路径
  - 回合钩子: `game.run_script_hook(trinket, "start_of_turn"/
    "start_of_combat")`（引擎 `_begin_recruit_for` / CombatScheduler 的
    实际调用形态）与真实 `game.end_recruit_phase()`（跨回合语义）
  - 战斗: 真实 `game.run_combat` + 战斗内 `start_of_combat` 探针
    （SoC 增益战后被快照复原，RULES §3.5）
  - 出售: 真实 `game.sell_minion`（`minion_sold` 广播）
  - 入馆: `game.add_tavern_entity`（RULES §7.4.9 统一入口）
  - 施放/打出: 真实 `game.play_minion`（元素 give-stats 消费点
    `racefx.elemental_give_bonus` 的端到端对照: Dancing Barnstormer /
    Champion of Sargeras）
  - 池: `minion_pool.available` 前后差

覆盖（SOP §16 空转测试判定法）: 每个测试方法至少含一条**正效果**断言
（负对照与正对照同方法内），owner 隔离（2 英雄），跨回合语义，
池空/无候选/无存活目标落空，副本（duplicate）叠加，CardDef.num 双向
钉死，随机同 seed 可复现。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id）
MURLOC_T2 = "BG22_202"        # Tad 2/2 T2 鱼人（池）
BEAST_T3 = "BG26_805"         # Humming Bird T2 野兽（池; 37.0 轮换后 Sly Raptor 已出池）
MECH_T2 = "BG31_816"          # Fire Baller 4/3 T2 机械（池）
ELEMENTAL_T1 = "BGS_127"      # Molten Rock 3/3 T1 元素（池）
ELEMENTAL_T3 = "BG31_843"     # Meteorite Crasher 4/4 T3 元素（池）
AMALGAM = "BG_GIL_681"        # Nightmare Amalgam（Race.ALL，非池）
PLAYER_UNDEAD = "BG25_008"    # Eternal Knight 4/2 T2 亡灵（池）
MAW_CASTER = "BG32_340"       # Maw Caster 4/5 T4 亡灵（池，战吼 Destroy）
ARCHLICH = "BG28_308"         # Archlich Kel'Thuzad（非池；数据链载荷）
BARNSTORMER = "BG26_162"      # Dancing Barnstormer（元素，战吼 give-stats）
CHAMPION = "BG27_016"         # Champion of Sargeras（无种族 give-stats）

# 本批 id
KELTHUZAD = "BG32_MagicItem_204"
MAW_CASTER_PORTRAIT = "BG32_MagicItem_205"
ECLECTIC = "BG32_MagicItem_280"
FOUNTAIN_PEN = "BG32_MagicItem_802"
DARNASSUS_PIE = "BG30_MagicItem_992"

IMPLEMENTED = (KELTHUZAD, MAW_CASTER_PORTRAIT, ECLECTIC, FOUNTAIN_PEN,
               DARNASSUS_PIE)

# DEFERRED（不注册；台账见 batch_trinkets24 模块 docstring）
# BG32_MagicItem_350 Splinter of Aurum / BG32_MagicItem_366 Guiding Candle
# 已由 batch_trinkets28 注册（`gold_gained` 观察点 / `TAVERN_OFFER_TIER_
# EXACT` 精确档位读取点）→ 移出守卫。
# BG32_MagicItem_419 Yu'lon Sticker 已由 batch_trinkets28 注册
# （战斗内 Transform 持久化，2026-09-02 引擎原语）。
# BG32_MagicItem_417 Tarecgosa Sticker 已由 batch_trinkets30 注册
# （2026-09-15: PERSIST_BONUS_ONLY + PERSIST_COMBAT_CHANGES）→ 移出本台账。
# BG32_MagicItem_804 Selfless Portrait 已由 batch_trinkets35 注册
# （2026-09-13，RULES §7.4.17 条件化战吼协议）→ 移出本台账。
# BG32_MagicItem_803 Macaw Portrait 已由 batch_trinkets36 注册
# （2026-09-13，RULES §7.4.17 条件化战吼第二消费者）→ 移出本台账。
# 987 Balladist / 283 Czarina 已由 batch_trinkets31 注册（2026-09-19——
# owner 权威序: wiki 页无 Notes → 卡面天然语言 "also give X" 增量 =
# 同句既有量）→ 移出本台账。
# 971 Enforcer / 179 Drakkari Portrait 已由 batch_family_races 注册
# （2026-09-21，RACES 家族类型身份改写）→ 移出本 DEFERRED 台账
# （守卫见 test_batch_family_races）。
DEFERRED = (
    "BG30_MagicItem_994",   # Yogg-Tastic Pastry — Wheel 子系统
    "BG32_MagicItem_300",   # Putricide Sticker — Craft 子系统
    "BG32_MagicItem_806",   # Battlecruiser Portrait — Upgrade 子系统
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 2400) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str, position=None) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m, position)
    return m


def put_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    """按池记账把一只随从放进酒馆（官方刷新路径同款手势）。"""
    game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


def num(card_id: str, index: int) -> int:
    v = get_db().get(card_id).num(index)
    assert v is not None, f"{card_id}.num({index}) missing"
    return v


class InCombat:
    """手动进入战斗态的上下文管理器（test_batch_trinkets20 先例）。"""

    def __init__(self, game: Game):
        self.game = game

    def __enter__(self):
        self.game.in_combat = True
        return self.game

    def __exit__(self, *exc):
        self.game.in_combat = False
        return False


# ══════════════ BG32_MagicItem_204 Kel'Thuzad Portrait ══════════════


class TestKelThuzadPortrait(unittest.TestCase):
    """204 — 战斗外摧毁一个随从后，全体己方随从 +2/+2。"""

    TID = KELTHUZAD

    def test_bind_grants_archlich_without_pool_change(self):
        g = make_game(2041)
        a, b = g.heroes
        self.assertFalse(get_db().get(ARCHLICH).is_pool_minion)
        pool_before = g.minion_pool.available(MURLOC_T2)
        bind(g, a, self.TID)
        self.assertEqual(hand_ids(a), [ARCHLICH])
        self.assertEqual(hand_ids(b), [])
        self.assertEqual(g.minion_pool.available(MURLOC_T2), pool_before)
        # 负对照: 未绑定饰品时不交付
        g2 = make_game(2041)
        self.assertEqual(hand_ids(g2.heroes[0]), [])

    def test_destroy_outside_combat_buffs_all_friendly(self):
        g = make_game(2042)
        a, b = g.heroes
        bind(g, a, self.TID)
        m1 = put(g, a, MURLOC_T2)
        m2 = put(g, a, BEAST_T3)
        victim = put(g, a, MECH_T2)
        before = [(m1.atk, m1.max_health), (m2.atk, m2.max_health)]
        self.assertTrue(g.destroy_minion(victim, hero=a))
        self.assertTrue(victim.dead)
        self.assertEqual((m1.atk, m1.max_health),
                         (before[0][0] + 2, before[0][1] + 2))
        self.assertEqual((m2.atk, m2.max_health),
                         (before[1][0] + 2, before[1][1] + 2))
        # 负对照: 无饰品时同一摧毁不加成
        g2 = make_game(2042)
        a2, b2 = g2.heroes
        m = put(g2, a2, MURLOC_T2)
        v = put(g2, a2, MECH_T2)
        g2.destroy_minion(v, hero=a2)
        self.assertEqual((m.atk, m.max_health),
                         (get_db().get(MURLOC_T2).atk,
                          get_db().get(MURLOC_T2).health))

    def test_in_combat_destroy_not_triggered(self):
        g = make_game(2043)
        a, b = g.heroes
        bind(g, a, self.TID)
        m = put(g, a, MURLOC_T2)
        base = (m.atk, m.max_health)
        with InCombat(g):
            v = put(g, a, MECH_T2)
            g.destroy_minion(v, hero=a)
        self.assertEqual((m.atk, m.max_health), base)      # "outside combat"
        # 正对照: 战斗外同一步骤加成
        v2 = put(g, a, BEAST_T3)
        g.destroy_minion(v2, hero=a)
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 2, base[1] + 2))

    def test_opponent_actor_not_triggered(self):
        g = make_game(2044)
        a, b = g.heroes
        bind(g, a, self.TID)
        m = put(g, a, MURLOC_T2)
        base = (m.atk, m.max_health)
        v = put(g, b, MECH_T2)
        g.destroy_minion(v, hero=b)                  # "you destroy" 过滤
        self.assertEqual((m.atk, m.max_health), base)
        # 正对照: 本人施动
        v2 = put(g, a, BEAST_T3)
        g.destroy_minion(v2, hero=a)
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 2, base[1] + 2))

    def test_whiff_without_living_minions_then_recovers(self):
        g = make_game(2045)
        a, b = g.heroes
        bind(g, a, self.TID)
        only = put(g, a, MECH_T2)
        self.assertTrue(g.destroy_minion(only, hero=a))   # 无存活目标
        self.assertEqual(a.board, [])                     # 落空不报错
        m = put(g, a, MURLOC_T2)                          # 正对照: 恢复
        v = put(g, a, BEAST_T3)
        base = (m.atk, m.max_health)
        g.destroy_minion(v, hero=a)
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 2, base[1] + 2))

    def test_dead_entity_destroy_is_noop(self):
        g = make_game(2046)
        a, b = g.heroes
        bind(g, a, self.TID)
        m = put(g, a, MURLOC_T2)
        base = (m.atk, m.max_health)
        dead = put(g, a, MECH_T2)
        g.destroy_minion(dead, hero=a)
        after_first = (m.atk, m.max_health)
        self.assertFalse(g.destroy_minion(dead, hero=a))   # 已死 → no-op
        self.assertEqual((m.atk, m.max_health), after_first)
        self.assertEqual(after_first, (base[0] + 2, base[1] + 2))

    def test_duplicate_trinket_stacks(self):
        g = make_game(2047)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertIsNotNone(g.grant_trinket(a, self.TID, duplicate=True))
        m = put(g, a, MURLOC_T2)
        base = (m.atk, m.max_health)
        v = put(g, a, MECH_T2)
        g.destroy_minion(v, hero=a)
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 4, base[1] + 4))   # 两份副本各 +2/+2

    def test_listener_persists_across_turn(self):
        g = make_game(2048)
        a, b = g.heroes
        bind(g, a, self.TID)
        put(g, a, ELEMENTAL_T1)
        put(g, b, ELEMENTAL_T1)
        g.end_recruit_phase()                    # 真实跨回合
        m = put(g, a, MURLOC_T2)
        base = (m.atk, m.max_health)
        v = put(g, a, MECH_T2)
        g.destroy_minion(v, hero=a)
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + 2, base[1] + 2))

    def test_full_hand_queues_copy(self):
        g = make_game(2049)
        a, b = g.heroes
        while len(a.hand) < 10:
            a.hand.append(g.create_spell("BG28_168", controller=a))
        bind(g, a, self.TID)
        queued = [e for h, e in g.pending_hand_queue
                  if h is a and e.card_id == ARCHLICH]
        self.assertEqual(len(queued), 1)
        self.assertEqual(hand_ids(a), ["BG28_168"] * 10)


# ══════════════ BG32_MagicItem_205 Maw Caster Portrait ══════════════


class TestMawCasterPortrait(unittest.TestCase):
    """205 — 战斗外摧毁一个随从后获得 num(0) 金。"""

    TID = MAW_CASTER_PORTRAIT

    def test_bind_grants_maw_caster_and_consumes_pool(self):
        g = make_game(2051)
        a, b = g.heroes
        before = g.minion_pool.available(MAW_CASTER)
        bind(g, a, self.TID)
        self.assertEqual(hand_ids(a), [MAW_CASTER])
        self.assertEqual(g.minion_pool.available(MAW_CASTER), before - 1)
        self.assertEqual(hand_ids(b), [])
        # 负对照: 无饰品不交付、不占池
        g2 = make_game(2051)
        self.assertEqual(hand_ids(g2.heroes[0]), [])
        self.assertEqual(g2.minion_pool.available(MAW_CASTER), before)

    def test_destroy_outside_combat_gains_gold(self):
        g = make_game(2052)
        a, b = g.heroes
        bind(g, a, self.TID)
        a.gold = 5
        v = put(g, a, MECH_T2)
        self.assertTrue(g.destroy_minion(v, hero=a))
        self.assertEqual(a.gold, 5 + num(self.TID, 0))
        self.assertEqual(b.gold, 3)               # owner 隔离
        # 负对照: 无饰品时同一摧毁不加金
        g2 = make_game(2052)
        a2, b2 = g2.heroes
        a2.gold = 5
        v2 = put(g2, a2, MECH_T2)
        g2.destroy_minion(v2, hero=a2)
        self.assertEqual(a2.gold, 5)

    def test_in_combat_destroy_no_gold(self):
        g = make_game(2053)
        a, b = g.heroes
        bind(g, a, self.TID)
        a.gold = 5
        with InCombat(g):
            v = put(g, a, MECH_T2)
            g.destroy_minion(v, hero=a)
        self.assertEqual(a.gold, 5)
        # 正对照: 战斗外加成
        v2 = put(g, a, BEAST_T3)
        g.destroy_minion(v2, hero=a)
        self.assertEqual(a.gold, 5 + num(self.TID, 0))

    def test_opponent_actor_no_gold(self):
        g = make_game(2054)
        a, b = g.heroes
        bind(g, a, self.TID)
        a.gold = 5
        v = put(g, b, MECH_T2)
        g.destroy_minion(v, hero=b)
        self.assertEqual(a.gold, 5)
        # 正对照: 本人施动
        v2 = put(g, a, BEAST_T3)
        g.destroy_minion(v2, hero=a)
        self.assertEqual(a.gold, 5 + num(self.TID, 0))

    def test_maw_caster_own_battlecry_triggers_trinket(self):
        """端到端: 真实打出 Maw Caster（战吼 Destroy a friendly Undead
        → `destroy_minion` 统一入口）→ 本饰品结算。"""
        g = make_game(2055)
        a, b = g.heroes
        a.gold = 30
        bind(g, a, self.TID)
        caster = put(g, a, MAW_CASTER)
        a.gold = 5
        a.hand.append(caster)
        a.board.remove(caster)
        caster.zone = Zone.HAND
        # 友方亡灵作为战吼目标
        undead = put(g, a, PLAYER_UNDEAD)
        self.assertTrue(g.play_minion(a, caster))
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices.pop(0)
        choice.choose(0)
        self.assertTrue(undead.dead or undead not in a.board)
        self.assertEqual(a.gold, 5 + num(self.TID, 0))

    def test_duplicate_trinket_stacks(self):
        g = make_game(2056)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertIsNotNone(g.grant_trinket(a, self.TID, duplicate=True))
        a.gold = 5
        v = put(g, a, MECH_T2)
        g.destroy_minion(v, hero=a)
        self.assertEqual(a.gold, 5 + 2 * num(self.TID, 0))

    def test_pool_conservation_on_destroy(self):
        g = make_game(2057)
        a, b = g.heroes
        bind(g, a, self.TID)
        v = put(g, a, MECH_T2)                 # 棋盘占用 1 份
        held = g.minion_pool.available(MECH_T2)
        a.gold = 5
        g.destroy_minion(v, hero=a)
        # 招募期摧毁 → 回池 1 份（RULES §2.3）
        self.assertEqual(g.minion_pool.available(MECH_T2), held + 1)
        self.assertEqual(a.gold, 5 + num(self.TID, 0))   # 正效果同方法内

    def test_full_hand_queues_copy(self):
        g = make_game(2058)
        a, b = g.heroes
        while len(a.hand) < 10:
            a.hand.append(g.create_spell("BG28_168", controller=a))
        bind(g, a, self.TID)
        queued = [e for h, e in g.pending_hand_queue
                  if h is a and e.card_id == MAW_CASTER]
        self.assertEqual(len(queued), 1)

    def test_listener_persists_across_turn(self):
        g = make_game(2059)
        a, b = g.heroes
        bind(g, a, self.TID)
        put(g, a, ELEMENTAL_T1)
        put(g, b, ELEMENTAL_T1)
        g.end_recruit_phase()                    # 真实跨回合
        a.gold = 5
        v = put(g, a, MECH_T2)
        g.destroy_minion(v, hero=a)
        self.assertEqual(a.gold, 5 + num(self.TID, 0))


# ══════════════ BG32_MagicItem_280 Eclectic Shrine ══════════════


class TestEclecticShrine(unittest.TestCase):
    """280 — SoC: 每个不同类型各一只友方随从 +num(0)/+num(1)，永久改善。"""

    TID = ECLECTIC

    def _soc(self, game, trinket):
        game.run_script_hook(trinket, "start_of_combat")

    def test_soc_buffs_one_minion_per_type(self):
        g = make_game(2801)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        atk, health = num(self.TID, 0), num(self.TID, 1)
        murloc = put(g, a, MURLOC_T2)
        mech = put(g, a, MECH_T2)
        beast = put(g, a, BEAST_T3)
        self._soc(g, t)
        self.assertEqual((murloc.atk, murloc.max_health),
                         (get_db().get(MURLOC_T2).atk + atk,
                          get_db().get(MURLOC_T2).health + health))
        self.assertEqual((mech.atk, mech.max_health),
                         (get_db().get(MECH_T2).atk + atk,
                          get_db().get(MECH_T2).health + health))
        self.assertEqual((beast.atk, beast.max_health),
                         (get_db().get(BEAST_T3).atk + atk,
                          get_db().get(BEAST_T3).health + health))
        # 负对照: 无饰品时同一钩子不发生
        g2 = make_game(2801)
        a2, b2 = g2.heroes
        m2 = put(g2, a2, MURLOC_T2)
        base2 = (m2.atk, m2.max_health)
        g2.events.fire(g2, "start_of_combat", hero=a2)
        self.assertEqual((m2.atk, m2.max_health), base2)

    def test_one_minion_of_each_race_only_once(self):
        """每个种族恰选一只（2 只同族 → 合计只 +1 份）。"""
        g = make_game(2802)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        m1 = put(g, a, MURLOC_T2)
        m2 = put(g, a, MURLOC_T2)
        self._soc(g, t)
        atk, health = num(self.TID, 0), num(self.TID, 1)
        gained = [(m.atk - get_db().get(MURLOC_T2).atk,
                   m.max_health - get_db().get(MURLOC_T2).health)
                  for m in (m1, m2)]
        self.assertEqual(sorted(gained), sorted([(0, 0), (atk, health)]))

    def test_improves_permanently(self):
        g = make_game(2803)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        m = put(g, a, MURLOC_T2)
        base_atk = get_db().get(MURLOC_T2).atk
        base_health = get_db().get(MURLOC_T2).health
        atk, health = num(self.TID, 0), num(self.TID, 1)
        self._soc(g, t)
        self.assertEqual(m.atk, base_atk + atk)              # 第 1 次 1×
        self._soc(g, t)
        self.assertEqual(m.atk, base_atk + 3 * atk)          # +2× → 累计 3×
        self._soc(g, t)
        self.assertEqual(m.atk, base_atk + 6 * atk)          # +3× → 累计 6×
        self.assertEqual(m.max_health, base_health + 6 * health)
        self.assertEqual(t._eclectic_triggers, 3)

    def test_amalgam_eligible_for_every_type(self):
        """单只 ALL 型随从 = 11 个种族各命中一次（官方 Amalgam 语义; 37.0 起 ABERRATION 入域）。"""
        g = make_game(2804)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        am = put(g, a, AMALGAM)
        d = get_db().get(AMALGAM)
        self._soc(g, t)
        races = [r for r in Race
                 if r not in (Race.INVALID, Race.NONE, Race.ALL)]
        self.assertEqual(len(races), 11)
        self.assertEqual(am.atk, d.atk + 11 * num(self.TID, 0))
        self.assertEqual(am.max_health, d.health + 11 * num(self.TID, 1))

    def test_opponent_board_not_buffed(self):
        g = make_game(2805)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        mine = put(g, a, MURLOC_T2)
        theirs = put(g, b, MURLOC_T2)
        base_theirs = (theirs.atk, theirs.max_health)
        self._soc(g, t)
        self.assertGreater(mine.atk, get_db().get(MURLOC_T2).atk)
        self.assertEqual((theirs.atk, theirs.max_health), base_theirs)

    def test_empty_board_whiffs_and_still_improves(self):
        g = make_game(2806)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self._soc(g, t)                       # 空棋盘 → 落空不报错
        self.assertEqual(t._eclectic_triggers, 1)
        m = put(g, a, MURLOC_T2)
        self._soc(g, t)                       # 正对照: 下次 2×
        self.assertEqual(m.atk,
                         get_db().get(MURLOC_T2).atk + 2 * num(self.TID, 0))
    def test_same_seed_same_pick(self):
        picks = []
        counts = []
        for _ in range(2):
            g = make_game(2807)
            a, b = g.heroes
            t = bind(g, a, self.TID)
            m1 = put(g, a, MURLOC_T2)
            m2 = put(g, a, MURLOC_T2)
            put(g, a, MECH_T2)
            self._soc(g, t)
            md = get_db().get(MURLOC_T2)
            picks.append(m1.atk > md.atk)
            counts.append((m1.atk - md.atk) + (m2.atk - md.atk))
        self.assertEqual(picks[0], picks[1])
        # 正对照: 该种族恰命中一次（非同 seed 下的恒 0 假通过）
        self.assertEqual(counts[0], num(self.TID, 0))
        self.assertEqual(counts[1], num(self.TID, 0))

    def test_real_run_combat_dispatches_soc_and_rolls_back(self):
        g = make_game(2808)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        m = put(g, a, MURLOC_T2)
        put(g, b, BEAST_T3)
        seen = {}

        def cb(gg, hero=None, **kw):
            if hero is a:
                seen["board"] = [(x.card_id, x.atk) for x in a.board]

        g.events.register(Listener(event="start_of_combat", owner=a,
                                   callback=cb))
        g.run_combat(a, b)
        self.assertTrue(seen.get("board"))
        self.assertEqual(seen["board"][0][1],
                         get_db().get(MURLOC_T2).atk + num(self.TID, 0))
        # 战后快照复原（RULES §3.5）但改善计数永久保留
        self.assertEqual(m.atk, get_db().get(MURLOC_T2).atk)
        self.assertEqual(t._eclectic_triggers, 1)

    def test_duplicate_trinket_stacks(self):
        g = make_game(2809)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertIsNotNone(g.grant_trinket(a, self.TID, duplicate=True))
        m = put(g, a, MURLOC_T2)
        t2 = [e for e in a.trinkets if e.card_id == self.TID]
        self.assertEqual(len(t2), 2)
        for e in t2:
            self._soc(g, e)
        self.assertEqual(m.atk,
                         get_db().get(MURLOC_T2).atk + 2 * num(self.TID, 0))

    def test_none_race_minion_not_buffed(self):
        """无类型随从（race NONE）不属于任何种族 → 不被选中。"""
        g = make_game(2810)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertEqual(get_db().get("BG_OG_221").race, Race.NONE)
        plain = put(g, a, "BG_OG_221")           # Selfless Hero（NONE）
        base = (plain.atk, plain.max_health)
        self._soc(g, t)
        self.assertEqual((plain.atk, plain.max_health), base)
        self.assertEqual(t._eclectic_triggers, 1)


# ══════════════ BG32_MagicItem_802 Fountain Pen ══════════════


class TestFountainPen(unittest.TestCase):
    """802 — 元素 give-stats 额外 +2/+1。"""

    TID = FOUNTAIN_PEN

    def test_bind_writes_elemental_extra_tags(self):
        g = make_game(8021)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 2)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), 1)
        self.assertEqual(b.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 0)
        self.assertEqual(b.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), 0)

    def test_elemental_giver_stats_include_bonus(self):
        """端到端: 元素给予者（Dancing Barnstormer）的 give-stats 数额
        吃 hero 级加成（消费点 `racefx.elemental_give_bonus`）。"""
        for with_pen in (False, True):
            g = make_game(8022)
            a, b = g.heroes
            if with_pen:
                bind(g, a, self.TID)
            elem = put_tavern(g, a, ELEMENTAL_T1)
            base = (elem.atk, elem.max_health)
            d = get_db().get(BARNSTORMER)
            barn = g.create_minion(BARNSTORMER, controller=a)
            a.hand.append(barn)
            self.assertTrue(g.play_minion(a, barn))
            extra = (2, 1) if with_pen else (0, 0)
            self.assertEqual(
                (elem.atk, elem.max_health),
                (base[0] + d.num(0) + extra[0],
                 base[1] + d.num(1) + extra[1]))
            # 负对照锚点: 无饰品时恰为基础值
            if not with_pen:
                self.assertEqual(elem.atk, base[0] + d.num(0))

    def test_all_race_givers_consume_bonus(self):
        """**ALL 种族**（=元素）给予者同样吃加成（2026-09-02 对抗审查 F1）。

        旧实现只接了 5 张原文族（Baller 三兄弟 / Waveling / En-Djinn
        Blazer / Stone Age Slab / Dancing Barnstormer），漏掉 Motley
        Phalanx / The Last One Standing / One-Amalgam Tour Group。
        """
        db = get_db()
        # 1) One-Amalgam Tour Group（BG30_102, ALL, 打出任意牌 → 同档或
        #    更低友方 +2/+1）
        for pen in (False, True):
            g = make_game(8025)
            a, b = g.heroes
            if pen:
                bind(g, a, FOUNTAIN_PEN)
            # 目标用**无触发**随从（Molten Rock 会在打出元素时自增益 →
            # 会污染增量断言）; 必须在棋盘（buff 域）
            target = put(g, a, MURLOC_T2)
            base = (target.atk, target.max_health)
            amal = g.create_minion("BG30_102", controller=a)
            a.hand.append(amal)
            self.assertTrue(g.play_minion(a, amal))
            d = db.get("BG30_102")
            extra = (2, 1) if pen else (0, 0)
            self.assertEqual((target.atk, target.max_health),
                             (base[0] + d.num(0) + extra[0],
                              base[1] + d.num(1) + extra[1]))
        # 2) Motley Phalanx（BG27_080, ALL, 亡语给每种类型一个友方 +3/+3）
        for pen in (False, True):
            g = make_game(8026)
            a, b = g.heroes
            if pen:
                bind(g, a, FOUNTAIN_PEN)
            target = put(g, a, MURLOC_T2)          # 无触发目标
            base = (target.atk, target.max_health)
            motley = put(g, a, "BG27_080")
            game_d = db.get("BG27_080")
            g.trigger_deathrattle(motley, hero=a)
            extra = (2, 1) if pen else (0, 0)
            # Murloc 目标恰被 MURLOC 一档选中一次 → 增量 = num + extra
            self.assertEqual((target.atk - base[0],
                              target.max_health - base[1]),
                             (game_d.num(0) + extra[0],
                              game_d.num(1) + extra[1]))

    def test_non_elemental_giver_not_buffed(self):
        """Champion of Sargeras 无种族 → 不吃元素加成。"""
        g = make_game(8023)
        a, b = g.heroes
        bind(g, a, self.TID)
        elem = put_tavern(g, a, ELEMENTAL_T1)
        base = (elem.atk, elem.max_health)
        d = get_db().get(CHAMPION)
        champ = g.create_minion(CHAMPION, controller=a)
        a.hand.append(champ)
        self.assertTrue(g.play_minion(a, champ))
        self.assertEqual((elem.atk, elem.max_health),
                         (base[0] + d.num(0), base[1] + d.num(1)))
        # 正对照: 同一局面下元素给予者吃加成
        barn = g.create_minion(BARNSTORMER, controller=a)
        a.hand.append(barn)
        g.play_minion(a, barn)
        bd = get_db().get(BARNSTORMER)
        self.assertEqual(elem.atk, base[0] + d.num(0) + bd.num(0) + 2)

    def test_applies_to_persistent_tavern_buff_face(self):
        """持久酒馆面（ApplyTavernBuff）同样吃加成: 后续入馆元素继承。"""
        g = make_game(8024)
        a, b = g.heroes
        bind(g, a, self.TID)
        barn = g.create_minion(BARNSTORMER, controller=a)
        a.hand.append(barn)
        self.assertTrue(g.play_minion(a, barn))
        d = get_db().get(BARNSTORMER)
        fresh = g.create_minion(ELEMENTAL_T3, controller=a)
        g.add_tavern_entity(a, fresh)
        fd = get_db().get(ELEMENTAL_T3)
        self.assertEqual(fresh.atk, fd.atk + d.num(0) + 2)
        self.assertEqual(fresh.max_health, fd.health + d.num(1) + 1)

    def test_duplicate_trinket_stacks(self):
        g = make_game(8025)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertIsNotNone(g.grant_trinket(a, self.TID, duplicate=True))
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 4)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), 2)

    def test_tag_persists_across_turn(self):
        g = make_game(8026)
        a, b = g.heroes
        bind(g, a, self.TID)
        put(g, a, ELEMENTAL_T1)
        put(g, b, ELEMENTAL_T1)
        g.end_recruit_phase()
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 2)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), 1)

    def test_opponent_giver_not_buffed(self):
        """对手的给予者不吃本人 Fountain Pen 的加成（hero 作用域 tag）；
        同方法内正对照: 本人给予者吃加成。"""
        g = make_game(8027)
        a, b = g.heroes
        bind(g, a, self.TID)
        theirs = put_tavern(g, b, ELEMENTAL_T1)
        mine = put_tavern(g, a, ELEMENTAL_T1)
        d = get_db().get(BARNSTORMER)
        ed = get_db().get(ELEMENTAL_T1)
        barn_b = g.create_minion(BARNSTORMER, controller=b)
        b.hand.append(barn_b)
        self.assertTrue(g.play_minion(b, barn_b))
        self.assertEqual((theirs.atk, theirs.max_health),
                         (ed.atk + d.num(0), ed.health + d.num(1)))
        self.assertEqual(b.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 0)
        self.assertEqual((mine.atk, mine.max_health), (ed.atk, ed.health))
        # 正对照: 本人给予者 → 吃 +2/+1
        barn_a = g.create_minion(BARNSTORMER, controller=a)
        a.hand.append(barn_a)
        self.assertTrue(g.play_minion(a, barn_a))
        self.assertEqual(mine.atk, ed.atk + d.num(0) + 2)
        self.assertEqual(mine.max_health, ed.health + d.num(1) + 1)


# ══════════════ BG30_MagicItem_992 Darnassus Pie ══════════════


class TestDarnassusPie(unittest.TestCase):
    """992 — 酒馆随从按"本回合已售随从数"获得 +1/+1。"""

    TID = DARNASSUS_PIE

    def test_sell_buffs_all_tavern_minions(self):
        g = make_game(9921)
        a, b = g.heroes
        bind(g, a, self.TID)
        a.tavern.clear()
        t1 = put_tavern(g, a, MURLOC_T2)
        t2 = put_tavern(g, a, ELEMENTAL_T1)
        b1 = (t1.atk, t1.max_health)
        b2 = (t2.atk, t2.max_health)
        seller = put(g, a, BEAST_T3)
        self.assertTrue(g.sell_minion(a, seller))
        self.assertEqual((t1.atk, t1.max_health), (b1[0] + 1, b1[1] + 1))
        self.assertEqual((t2.atk, t2.max_health), (b2[0] + 1, b2[1] + 1))
        # 负对照: 无饰品时同一出售不动酒馆
        g2 = make_game(9921)
        a2, b2h = g2.heroes
        a2.tavern.clear()
        tm = put_tavern(g2, a2, MURLOC_T2)
        tb = (tm.atk, tm.max_health)
        s2 = put(g2, a2, BEAST_T3)
        g2.sell_minion(a2, s2)
        self.assertEqual((tm.atk, tm.max_health), tb)

    def test_sales_before_bind_are_counted(self):
        """绑定**之前**当回合售出的随从同样计入（引擎 `MINIONS_SOLD_
        THIS_TURN` 历史读取点；2026-09-02 对抗审查证伪旧实现从 0 起算）。"""
        g = make_game(9925)
        a, b = g.heroes
        a.tavern.clear()
        t = put_tavern(g, a, MURLOC_T2)
        base = (t.atk, t.max_health)
        for cid in (BEAST_T3, MECH_T2):
            g.sell_minion(a, put(g, a, cid))
        self.assertEqual(a.get(GameTag.MINIONS_SOLD_THIS_TURN, 0), 2)
        bind(g, a, self.TID)                       # 先卖后绑
        self.assertEqual((t.atk, t.max_health),
                         (base[0] + 2, base[1] + 2))
        # 正对照: 无饰品时先卖不产生任何酒馆增益
        g2 = make_game(9925)
        a2, _ = g2.heroes
        a2.tavern.clear()
        t2 = put_tavern(g2, a2, MURLOC_T2)
        b2 = (t2.atk, t2.max_health)
        g2.sell_minion(a2, put(g2, a2, BEAST_T3))
        self.assertEqual((t2.atk, t2.max_health), b2)

    def test_multiple_sells_stack_and_new_entries_inherit(self):
        g = make_game(9922)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        a.tavern.clear()
        resident = put_tavern(g, a, MURLOC_T2)
        base = (resident.atk, resident.max_health)
        for cid in (BEAST_T3, MECH_T2):
            s = put(g, a, cid)
            g.sell_minion(a, s)
        self.assertEqual((resident.atk, resident.max_health),
                         (base[0] + 2, base[1] + 2))
        self.assertEqual(t._pie_sold, 2)
        fresh = g.create_minion(ELEMENTAL_T1, controller=a)
        g.add_tavern_entity(a, fresh)
        fd = get_db().get(ELEMENTAL_T1)
        self.assertEqual((fresh.atk, fresh.max_health),
                         (fd.atk + 2, fd.health + 2))

    def test_turn_start_reclaims_tavern_resident_buff(self):
        g = make_game(9923)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        a.tavern.clear()
        resident = put_tavern(g, a, MURLOC_T2)
        base = (resident.atk, resident.max_health)
        s = put(g, a, BEAST_T3)
        g.sell_minion(a, s)
        self.assertEqual(resident.atk, base[0] + 1)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual((resident.atk, resident.max_health), base)
        self.assertEqual(t._pie_sold, 0)
        # 正对照: 新回合再售 1 只 → 只 +1（计数已归零）
        s2 = put(g, a, MECH_T2)
        g.sell_minion(a, s2)
        self.assertEqual(resident.atk, base[0] + 1)

    def test_bought_minion_keeps_buff_across_turn(self):
        g = make_game(9924)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        a.tavern.clear()
        m = put_tavern(g, a, MURLOC_T2)
        md = get_db().get(MURLOC_T2)
        s = put(g, a, BEAST_T3)
        g.sell_minion(a, s)
        buffed = (m.atk, m.max_health)
        self.assertEqual(buffed, (md.atk + 1, md.health + 1))   # 正效果
        a.gold = 30
        self.assertTrue(g.buy_from_tavern(a, m))
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual((m.atk, m.max_health), buffed)   # 战利品不回收
        self.assertIn(m, a.hand)

    def test_opponent_sales_not_counted(self):
        g = make_game(9925)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        a.tavern.clear()
        resident = put_tavern(g, a, MURLOC_T2)
        base = (resident.atk, resident.max_health)
        sb = put(g, b, BEAST_T3)
        g.sell_minion(b, sb)
        self.assertEqual((resident.atk, resident.max_health), base)
        self.assertEqual(t._pie_sold, 0)
        # 正对照: 本人售出计数
        sa = put(g, a, MECH_T2)
        g.sell_minion(a, sa)
        self.assertEqual(t._pie_sold, 1)
        self.assertEqual(resident.atk, base[0] + 1)

    def test_real_end_recruit_phase_reclaims_frozen_tavern(self):
        g = make_game(9926)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        a.tavern.clear()
        resident = put_tavern(g, a, ELEMENTAL_T1)
        base = (resident.atk, resident.max_health)
        s = put(g, a, BEAST_T3)
        g.sell_minion(a, s)
        self.assertEqual(resident.atk, base[0] + 1)
        resident.set(GameTag.FROZEN, True)     # 跨回合保留观察点
        g.end_recruit_phase()
        self.assertIn(resident, a.tavern)
        self.assertEqual((resident.atk, resident.max_health), base)
        self.assertEqual(t._pie_sold, 0)

    def test_pool_conservation(self):
        g = make_game(9927)
        a, b = g.heroes
        bind(g, a, self.TID)
        a.tavern.clear()
        resident = put_tavern(g, a, MURLOC_T2)
        md = get_db().get(MURLOC_T2)
        held = g.minion_pool.available(BEAST_T3)
        s = put(g, a, BEAST_T3)
        self.assertEqual(g.minion_pool.available(BEAST_T3), held)
        g.sell_minion(a, s)
        self.assertEqual(g.minion_pool.available(BEAST_T3), held + 1)
        self.assertEqual(resident.atk, md.atk + 1)      # 正效果同方法内

    def test_duplicate_trinket_stacks(self):
        g = make_game(9928)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertIsNotNone(g.grant_trinket(a, self.TID, duplicate=True))
        a.tavern.clear()
        resident = put_tavern(g, a, MURLOC_T2)
        base = (resident.atk, resident.max_health)
        s = put(g, a, BEAST_T3)
        g.sell_minion(a, s)
        self.assertEqual((resident.atk, resident.max_health),
                         (base[0] + 2, base[1] + 2))   # 两份副本各 +1/+1

    def test_spell_in_tavern_not_buffed(self):
        """文本是 "Minions in the Tavern"——馆内法术不入资格集；
        同方法内正对照: 馆内随从照常 +1/+1。"""
        g = make_game(9929)
        a, b = g.heroes
        bind(g, a, self.TID)
        a.tavern.clear()
        spell = g.create_spell("BG28_168", controller=a)
        g.add_tavern_entity(a, spell)
        m = put_tavern(g, a, MURLOC_T2)
        md = get_db().get(MURLOC_T2)
        s = put(g, a, BEAST_T3)
        g.sell_minion(a, s)
        self.assertEqual((m.atk, m.max_health),
                         (md.atk + 1, md.health + 1))     # 正对照
        self.assertEqual(len(a.tavern), 2)
        self.assertIs(a.tavern[0], spell)


# ══════════════ 注册表 / 台账守卫（结构性） ══════════════


class TestBatchTrinkets24Registry(unittest.TestCase):
    """@engine-only

    结构性守卫: 注册集合、DEFERRED 不注册、CardDef 数值/文本一致性。
    与脚本钩子无关（空转审计白名单）。
    """

    def test_registered_ids_exact(self):
        for tid in IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            cls = REGISTRY[tid]
            self.assertEqual(cls.__module__,
                             "hsrl2.scripts.batches.batch_trinkets24", tid)
        self.assertEqual(len(set(IMPLEMENTED)), 5)
        # 419 已由 batch_trinkets28 注册; 417 已由 batch_trinkets30 注册
        # （原 13 项 → 11）
        # 944 已由 batch_trinkets33 注册; 274 已由 batch_trinkets34 注册
        # 804 已由 batch_trinkets35 注册; 803 已由 batch_trinkets36 注册
        # 987 Balladist / 283 Czarina 已由 batch_trinkets31 注册（2026-09-19）
        # 971 / 179 已由 batch_family_races 注册（2026-09-21）→ 5 降为 3
        self.assertEqual(len(set(DEFERRED)), 3)

    def test_deferred_ids_not_registered(self):
        for tid in DEFERRED:
            self.assertNotIn(tid, REGISTRY, tid)

    def test_all_ids_are_shop_pool_trinkets(self):
        pool = {d.id for d in get_db().trinket_offer_pool()}
        for tid in IMPLEMENTED + DEFERRED:
            self.assertIn(tid, pool, tid)

    def test_eclectic_params_match_carddef(self):
        d = get_db().get(ECLECTIC)
        self.assertEqual(d.num(0), 3)
        self.assertEqual(d.num(1), 2)
        self.assertIn("+{0}/+{1}", d.text)
        self.assertIn("Improve this permanently", d.text)

    def test_maw_caster_gold_param_matches_carddef(self):
        d = get_db().get(MAW_CASTER_PORTRAIT)
        self.assertEqual(d.num(0), 2)
        self.assertIn("{0} Gold", d.text)

    def test_literal_cards_have_no_template_params(self):
        """204 / 802 / 992 的数值是文本字面量——CardDef 无 {0}/{1} 参数。"""
        for tid in (KELTHUZAD, FOUNTAIN_PEN, DARNASSUS_PIE):
            d = get_db().get(tid)
            for i in range(4):
                self.assertIsNone(d.num(i), f"{tid}.num({i})")
            self.assertNotIn("{0}", d.text)

    def test_related_card_data_chain(self):
        self.assertEqual(get_db().get(ARCHLICH).id, "BG28_308")
        self.assertEqual(get_db().get(MAW_CASTER).id, "BG32_340")
        self.assertFalse(get_db().get(ARCHLICH).is_pool_minion)
        self.assertTrue(get_db().get(MAW_CASTER).is_pool_minion)

    def test_eclectic_race_domain_is_eleven(self):
        """37.0（255130）标准种族域 = 11（新增 ABERRATION=126）。"""
        from hsrl2.tags import STANDARD_RACES
        races = [r for r in Race
                 if r not in (Race.INVALID, Race.NONE, Race.ALL)]
        self.assertEqual(len(races), len(STANDARD_RACES))
        self.assertEqual(len(races), 11)
        self.assertIn(Race.ABERRATION, races)


if __name__ == "__main__":
    unittest.main()
