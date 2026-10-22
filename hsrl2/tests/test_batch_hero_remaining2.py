"""批次 hero_remaining2 语义测试（作业单 2026-09-02，11 技能 + 1 token）。

驱动协议:
  - 被动/触发技能: 显式调 ``REGISTRY[power.id].on_bind(hero, game)``
    （start_game 接线的人工等价物）后走真实事件路径
    （refresh_tavern / run_combat / check_deaths / buy_from_tavern）。
  - 未绑定英雄的旧技能（Tag380 无指向）: 引擎协议
    ``game.replace_hero_power(hero, power_id)`` 选中后再
    ``use_hero_power``（Sulfuras/Finley 同协议; 不得绕过引擎直接调脚本）。
  - 数值断言一律 CardDef.num()/raw cost 计算（TEST_SOP §4）。
  - 每个"不可用/落空"断言都配**正对照**（同 setup 有效果路径确实发生）;
    listener/passive 一律带 ≥2 英雄的 owner 隔离; SoC 用战斗内探针
    （SOP §16 item 15/24 + 空转测试判定法）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import entity
from hsrl2.db import CardDB
from hsrl2.events import START_OF_COMBAT, TURN_START, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

PLAIN_T1 = "BG25_001"          # Risen Rider — 2/1（池 T1 随从）
UNDEAD_T2 = "BG25_011"         # Nerubian Deathswarmer — T2 Undead
TAVERN_COIN = "BG28_810"       # Tavern Coin（T1 池法术）

OK_IDS = (
    "BG22_HERO_004p", "TB_BaconShop_HP_009", "TB_BaconShop_HP_018",
    "TB_BaconShop_HP_019", "TB_BaconShop_HP_027", "TB_BaconShop_HP_043",
    "TB_BaconShop_HP_050", "TB_BaconShop_HP_051", "TB_BaconShop_HP_065t2",
    "TB_BaconShop_HP_085", "TB_BaconShop_HP_702", "BG28_885",
)
DEFERRED_IDS = (
    "BG20_HERO_202p", "BG20_HERO_242p", "BG20_HERO_283p",
    "BG20_HERO_283p_t1", "BG20_HERO_283p_t2", "BG20_HERO_283p_t3",
    "BG20_HERO_201p2", "BG22_HERO_000p", "BG22_HERO_000p_t1",
    "BG22_HERO_000p_t2", "BG22_HERO_000p_t3", "BG22_HERO_000p_t4",
    "BG24_HERO_100p", "BG25_HERO_100p", "BG31_HERO_801p",
    "BG31_HERO_811p", "BG31_HERO_811p2", "BG31_HERO_811p3",
    "BG33_HERO_001p_ALT", "BG34_HERO_000p", "BG34_HERO_004p",
    "BG35_HERO_001p", "TB_BaconShop_HP_017", "TB_BaconShop_HP_020",
    "TB_BaconShop_HP_101", "TB_BaconShop_HP_106",
)
# "inspect and decide" 变体: 已由基础脚本处理 / 与基础同效 → 不注册
VARIANT_NOT_REGISTERED = (
    "BG26_HERO_102p2", "BG28_HERO_400p2",
    "BG22_HERO_001p_t1", "BG22_HERO_001p_t2", "BG22_HERO_001p_t3",
    "BG22_HERO_001p_t4",
    # BG31_Anomaly_117t 迁出（batch_anomalies7 已注册——Emergency
    # Landing 的第二技能槽载荷，配 MinionPool.purge 永久移除原语）
    # BG27_Anomaly_805t 迁出（batch_anomalies_final 已注册——BG27_Anomaly_805
    # Match Fixing 的第二技能槽 0 费载荷，委托 TB_BaconShop_HP_081 同机制）
    # BG35_Anomaly_002t 迁出（batch_anomalies5 已注册）
    # BG35_Anomaly_007t/_008t 迁出（batch_anomalies6 已注册——第二技能槽
    # 变为饰品副本，RULES §9.5）
)
VARIANT_HANDLED_BASE = (
    "BG26_HERO_102p", "BG28_HERO_400p", "BG22_HERO_001p",
    "TB_BaconShop_HP_081", "TB_BaconShop_HP_085t",
)


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def raw_cost(card_id: str) -> int:
    d = get_db().get(card_id)
    return d.raw.get("cost", 0)


def make_game(hero_a: str, hero_b: str = "TEST_HERO_B",
              seed: int = 7) -> Game:
    return Game([Hero(hero_a, "A"), Hero(hero_b, "B")], get_db(),
                seed=seed)


def bind(game: Game, hero: Hero, power_id: str):
    """on_bind 接线（手动调 replace 选中的旧技能需显式接线）。"""
    script = REGISTRY[power_id]
    script.on_bind(hero, game)
    return script


def select(game: Game, hero: Hero, power_id: str):
    """选中旧/未绑定技能（引擎协议; 重置当回合使用计数）。"""
    game.replace_hero_power(hero, power_id)
    return REGISTRY[power_id]


def put(game: Game, hero: Hero, card_id: str, *,
        buff: tuple[int, int] | None = None) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    game.summon(hero, m)
    if buff is not None:
        m.add_buff(entity.Buff(atk=buff[0], health=buff[1]))
    return m


def fake_minion(game: Game, hero: Hero, name: str, atk: int,
                health: int, race: Race = Race.NONE) -> Minion:
    m = Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)
    m.game = game
    m.controller = hero
    game.summon(hero, m)
    return m


def tavern_put(game: Game, hero: Hero, card_id: str) -> Minion:
    game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def buy_tavern_minion(game: Game, hero: Hero, card_id: str) -> bool:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return game.buy_from_tavern(hero, m)


def buy_tavern_spell(game: Game, hero: Hero, card_id: str = TAVERN_COIN):
    s = game.create_spell(card_id, controller=hero)
    s.zone = Zone.TAVERN
    hero.tavern.append(s)
    return game.buy_from_tavern(hero, s)


def choose(game: Game, kind: str, index: int = 0):
    choice = game.pending_choices.pop(0)
    assert choice.kind == kind, f"expect {kind}, got {choice.kind}"
    pick = choice.options[index]
    choice.choose(index)
    return pick


def soc_probe(game: Game, power_id: str, n_enemies: int):
    """战斗内 SoC 探针: 记录 A 的 SoC 与 B 的 SoC 时敌方板血量。

    返回 (before, snap_a, snap_b)——before = 开战前血量（= 战斗内重置
    后的满血）; 差值即本技能伤害。snap_b（B 的 SoC 时敌方板）用于
    证明本技能**每场恰一次**（owner 隔离）。
    """
    a, b = game.heroes
    select(game, a, power_id)
    bind(game, a, power_id)
    enemies = []
    for _ in range(n_enemies):
        m = put(game, b, UNDEAD_T2, buff=(0, 100))
        enemies.append(m)
    before = {m.uuid: m.health for m in enemies}
    snap_a: list = []
    snap_b: list = []

    def on_a(g, hero=None, **kw):
        if hero is a:
            snap_a.append({x.uuid: x.health for x in b.board})

    def on_b(g, hero=None, **kw):
        if hero is b:
            snap_b.append({x.uuid: x.health for x in b.board})

    game.events.register(Listener(event=START_OF_COMBAT, owner=a,
                                  callback=on_a))
    game.events.register(Listener(event=START_OF_COMBAT, owner=a,
                                  callback=on_b))
    game.run_combat(a, b)
    deltas = {u: before[u] - snap_a[0].get(u, before[u]) for u in before}
    return deltas, snap_a, snap_b


class TestRegistryState(unittest.TestCase):
    """批次注册面: 11 技能 + Lantern Light token; DEFERRED 不注册。"""

    def test_ok_registered(self):
        for cid in OK_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_deferred_not_registered(self):
        for cid in DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_variants_not_re_registered_but_base_handled(self):
        """变体台账: 不重复注册（与已处理基础同效/dependent）。"""
        for cid in VARIANT_NOT_REGISTERED:
            self.assertNotIn(cid, REGISTRY, cid)
        for cid in VARIANT_HANDLED_BASE:
            self.assertIn(cid, REGISTRY, cid)

    def test_murloc_token_dependency_absent(self):
        """Murloc King DEFERRED 的载荷前提: 1/1 Murloc token 不在库。"""
        db = get_db()
        tokens = [d.id for d in db._by_id.values()
                  if d.card_type.name == "MINION" and d.atk == 1
                  and d.health == 1 and d.tech_level <= 0
                  and "murloc" in d.name.lower()]
        self.assertEqual(tokens, [])
        self.assertNotIn("TB_BaconShop_HP_017", REGISTRY)
        self.assertIsNone(db.by_dbf(1078))


class TestVarden(unittest.TestCase):
    """BG22_HERO_004p — 刷新复制最高 tier 并冻结两者。"""

    HERO = "BG22_HERO_004"

    def make(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        bind(game, a, "BG22_HERO_004p")
        return game, a

    def test_passive_not_clickable(self):
        game, a = self.make()
        a.gold = 10
        self.assertTrue(getattr(REGISTRY["BG22_HERO_004p"], "passive"))
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)
        # 正对照: 不可点击但效果确实发生（刷新触发复制）
        a._tavern_offer_override = 1
        game.refresh_tavern(a, free=True)
        self.assertEqual(len([e for e in a.tavern
                              if isinstance(e, Minion)]), 2)

    def test_refresh_copies_highest_tier_and_freezes_both(self):
        game, a = self.make()
        a._tavern_offer_override = 1
        game.refresh_tavern(a, free=True)
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(mins), 2)          # 1 抽出 + 1 复制
        self.assertEqual(mins[0].card_id, mins[1].card_id)
        src = mins[0]
        copy = mins[1]
        # plain copy: 无 buff（wiki 22.4.3 bugfix）
        d = get_db().get(src.card_id)
        self.assertEqual((copy.atk, copy.health), (d.atk, d.health))
        self.assertEqual(copy._buffs, [])
        # 冻结两者（实体级 FROZEN）
        self.assertTrue(src.has(GameTag.FROZEN))
        self.assertTrue(copy.has(GameTag.FROZEN))

    def test_buffed_frozen_source_copied_plain(self):
        game, a = self.make()
        a._tavern_offer_override = 1
        src = tavern_put(game, a, PLAIN_T1)
        src.add_buff(entity.Buff(atk=5, health=5))
        src.set(GameTag.FROZEN, True)
        game.refresh_tavern(a, free=True)       # 保留 src（冻结），不再抽
        mins = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(mins), 2)
        d = get_db().get(PLAIN_T1)
        self.assertEqual((src.atk, src.health), (d.atk + 5, d.health + 5))
        copy = [m for m in mins if m is not src][0]
        self.assertEqual((copy.atk, copy.health), (d.atk, d.health))
        self.assertEqual(copy._buffs, [])

    def test_frozen_pair_retained_on_next_refresh(self):
        game, a = self.make()
        a._tavern_offer_override = 1
        game.refresh_tavern(a, free=True)
        first = {e.uuid for e in a.tavern if isinstance(e, Minion)}
        game.refresh_tavern(a, free=True)
        now = {e.uuid for e in a.tavern if isinstance(e, Minion)}
        self.assertTrue(first <= now)           # 冻结对保留（未被回池）

    def test_empty_tavern_whiffs(self):
        game, a = self.make()
        a._tavern_offer_override = 0
        game.refresh_tavern(a, free=True)
        self.assertEqual([e for e in a.tavern if isinstance(e, Minion)], [])
        # 正对照: 给一只冻结随从后再刷新 → 复制发生
        src = tavern_put(game, a, PLAIN_T1)
        src.set(GameTag.FROZEN, True)
        game.refresh_tavern(a, free=True)
        self.assertEqual(len([e for e in a.tavern
                              if isinstance(e, Minion)]), 2)

    def test_owner_isolation(self):
        game, a = self.make()
        b = game.heroes[1]
        b._tavern_offer_override = 1
        game.refresh_tavern(b, free=True)
        b_mins = [e for e in b.tavern if isinstance(e, Minion)]
        self.assertEqual(len(b_mins), 1)        # B 无技能 → 不复制
        self.assertEqual([e for e in a.tavern if isinstance(e, Minion)],
                         [])
        # 正对照: A 自己的刷新确实复制
        a._tavern_offer_override = 1
        game.refresh_tavern(a, free=True)
        self.assertEqual(len([e for e in a.tavern
                              if isinstance(e, Minion)]), 2)


class TestSkilledBartender(unittest.TestCase):
    """TB_BaconShop_HP_009 — 升级费 -1（被动）。"""

    HERO = "TB_BaconShop_HERO_70"

    def test_upgrade_discount_and_owner_isolation(self):
        game = make_game(self.HERO, "TB_BaconShop_HERO_52")
        a, b = game.heroes
        bind(game, a, "TB_BaconShop_HP_009")
        self.assertTrue(getattr(REGISTRY["TB_BaconShop_HP_009"], "passive"))
        a.gold = 50
        b.gold = 50
        base_a = a.upgrade_cost
        base_b = b.upgrade_cost
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD, 0), -1)
        self.assertEqual(b.get(GameTag.UPGRADE_COST_MOD, 0), 0)
        self.assertTrue(game.upgrade_tavern(a))
        self.assertTrue(game.upgrade_tavern(b))
        self.assertEqual(a.gold, 50 - (base_a - 1))
        self.assertEqual(b.gold, 50 - base_b)   # 正对照: 未绑定付全价

    def test_not_clickable(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        bind(game, a, "TB_BaconShop_HP_009")
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)
        # 正对照: 不可点击但被动确实生效（升级费 base−1）
        base = a.upgrade_cost
        self.assertTrue(game.upgrade_tavern(a))
        self.assertEqual(a.gold, 10 - (base - 1))


class TestRagePotion(unittest.TestCase):
    """TB_BaconShop_HP_018 — +10 攻击直到下回合（定向）。"""

    HERO = "TB_BaconShop_HERO_70"
    PID = "TB_BaconShop_HP_018"

    def make(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        a.gold = 10
        return game, a

    def test_no_candidate_rejected(self):
        game, a = self.make()
        self.assertFalse(game.use_hero_power(a))    # 空板无候选
        self.assertEqual(a.gold, 10)
        # 正对照: 同 setup 有候选时可用且生效
        m = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, m))
        self.assertEqual(m.atk, 12)

    def test_buff_applied_and_expires_next_turn(self):
        game, a = self.make()
        b = game.heroes[1]
        m = put(game, a, PLAIN_T1)
        base = m.atk
        self.assertTrue(game.use_hero_power(a, m))  # 正对照: 有效果
        self.assertEqual(a.gold, 10 - raw_cost(self.PID))
        self.assertEqual(m.atk, base + 10)
        self.assertTrue(any(getattr(x, "temporary", False)
                            for x in m._buffs))
        # 对手回合不消耗（owner 隔离）
        game.events.fire(game, TURN_START, turn=2, hero=b)
        self.assertEqual(m.atk, base + 10)
        # 目标控制者下一招募阶段开始 → 精确回落
        game.events.fire(game, TURN_START, turn=2, hero=a)
        self.assertEqual(m.atk, base)

    def test_stale_target_whiffs_no_gold(self):
        game, a = self.make()
        other_hero_minion = put(game, game.heroes[1], PLAIN_T1)
        self.assertFalse(game.use_hero_power(a, other_hero_minion))
        self.assertEqual(a.gold, 10)
        self.assertEqual(other_hero_minion.atk, 2)
        # 正对照: 己方棋盘目标可用且 +10
        mine = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, mine))
        self.assertEqual(mine.atk, 12)
        self.assertEqual(a.gold, 10 - raw_cost(self.PID))


class TestSocDamage(unittest.TestCase):
    """TB_BaconShop_HP_019 / 027 / 043 — Start of Combat 伤害（被动）。"""

    HERO = "TB_BaconShop_HERO_70"

    def test_die_insects_two_random_for_8(self):
        game = make_game(self.HERO)
        deltas, _, _ = soc_probe(game, "TB_BaconShop_HP_019", 3)
        self.assertEqual(sorted(deltas.values()), [0, 8, 8])

    def test_fire_the_cannons_two_random_for_4(self):
        game = make_game(self.HERO)
        deltas, _, _ = soc_probe(game, "TB_BaconShop_HP_027", 3)
        self.assertEqual(sorted(deltas.values()), [0, 4, 4])

    def test_nefarious_fire_all_enemies_for_1(self):
        game = make_game(self.HERO)
        deltas, _, _ = soc_probe(game, "TB_BaconShop_HP_043", 3)
        self.assertEqual(sorted(deltas.values()), [1, 1, 1])

    def test_two_targets_distinct(self):
        game = make_game(self.HERO)
        deltas, _, _ = soc_probe(game, "TB_BaconShop_HP_019", 4)
        self.assertEqual(sorted(deltas.values()), [0, 0, 8, 8])

    def test_single_enemy_takes_full_damage(self):
        game = make_game(self.HERO)
        deltas, _, _ = soc_probe(game, "TB_BaconShop_HP_019", 1)
        self.assertEqual(list(deltas.values()), [8])

    def test_triggers_exactly_once_per_combat(self):
        """owner 隔离: B 的 SoC 不二次触发（敌方板血量不变）。"""
        game = make_game(self.HERO)
        deltas, snap_a, snap_b = soc_probe(game, "TB_BaconShop_HP_019", 3)
        # 正对照: 伤害确实发生（否则 snap_a == snap_b 无信息量）
        self.assertEqual(sorted(deltas.values()), [0, 8, 8])
        self.assertEqual(snap_a[0], snap_b[0])

    def test_empty_enemy_board_no_crash(self):
        game = make_game(self.HERO)
        deltas, snap_a, _ = soc_probe(game, "TB_BaconShop_HP_019", 0)
        self.assertEqual(deltas, {})
        self.assertEqual(snap_a, [{}])
        # 正对照: 同 setup 有敌板时伤害照常发生
        deltas2, _, _ = soc_probe(make_game(self.HERO),
                                  "TB_BaconShop_HP_019", 3)
        self.assertEqual(sorted(deltas2.values()), [0, 8, 8])

    def test_passive_not_clickable(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, "TB_BaconShop_HP_019")
        bind(game, a, "TB_BaconShop_HP_019")
        a.gold = 10
        self.assertTrue(getattr(REGISTRY["TB_BaconShop_HP_019"],
                                "passive"))
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)
        # 正对照: 未使用但 SoC 确实造成伤害
        deltas, _, _ = soc_probe(make_game(self.HERO),
                                 "TB_BaconShop_HP_019", 3)
        self.assertEqual(sorted(deltas.values()), [0, 8, 8])


class TestBansheesBlessing(unittest.TestCase):
    """TB_BaconShop_HP_050 — 移除友方，相邻 +1/+1（定向）。"""

    HERO = "TB_BaconShop_HERO_70"
    PID = "TB_BaconShop_HP_050"

    def make(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        a.gold = 10
        return game, a

    def test_remove_middle_buffs_both_neighbors(self):
        game, a = self.make()
        game.minion_pool.acquire(PLAIN_T1)      # 占池以验证不回池
        m1 = put(game, a, PLAIN_T1)
        m2 = put(game, a, PLAIN_T1)
        m3 = put(game, a, PLAIN_T1)
        avail = game.minion_pool.available(PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, m2))
        self.assertNotIn(m2, a.board)
        self.assertEqual(m2.zone, Zone.REMOVED)
        self.assertEqual(a.gold, 10)            # cost=0
        self.assertEqual((m1.atk, m1.health), (3, 2))
        self.assertEqual((m3.atk, m3.health), (3, 2))
        self.assertEqual(game.minion_pool.available(PLAIN_T1), avail)

    def test_left_edge_only_right_neighbor(self):
        game, a = self.make()
        m1 = put(game, a, PLAIN_T1)
        m2 = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, m1))
        self.assertEqual((m2.atk, m2.health), (3, 2))
        self.assertEqual(len(a.board), 1)

    def test_opponent_minion_rejected(self):
        game, a = self.make()
        b = game.heroes[1]
        enemy = put(game, b, PLAIN_T1)
        self.assertFalse(game.use_hero_power(a, enemy))
        self.assertEqual(a.gold, 10)
        self.assertIn(enemy, b.board)
        self.assertEqual((enemy.atk, enemy.health), (2, 1))
        # 正对照: 己方随从可用——移除 + 相邻 +1/+1 真实发生
        m1 = put(game, a, PLAIN_T1)
        m2 = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, m1))
        self.assertNotIn(m1, a.board)
        self.assertEqual((m2.atk, m2.health), (3, 2))

    def test_stale_target_whiffs(self):
        game, a = self.make()
        m = put(game, a, PLAIN_T1)
        a.board.remove(m)
        m.zone = Zone.REMOVED
        self.assertFalse(game.use_hero_power(a, m))
        self.assertEqual(a.gold, 10)
        # 正对照: 在场目标可用且邻居增益真实发生
        m1 = put(game, a, PLAIN_T1)
        m2 = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, m1))
        self.assertEqual((m2.atk, m2.health), (3, 2))


class TestHonorableWarband(unittest.TestCase):
    """TB_BaconShop_HP_051 — 无类型友方 +1/+1（主动，cost 2）。"""

    HERO = "TB_BaconShop_HERO_70"
    PID = "TB_BaconShop_HP_051"

    def test_only_no_type_minions_buffed(self):
        game = make_game(self.HERO)
        a, b = game.heroes
        select(game, a, self.PID)
        a.gold = 10
        none_m = fake_minion(game, a, "NONE", 1, 1, Race.NONE)
        typed = put(game, a, PLAIN_T1)           # Race.BEAST
        enemy = put(game, b, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.gold, 10 - raw_cost(self.PID))
        self.assertEqual((none_m.atk, none_m.health), (2, 2))
        self.assertEqual((typed.atk, typed.health), (2, 1))
        self.assertEqual((enemy.atk, enemy.health), (2, 1))

    def test_no_none_type_still_usable(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        a.gold = 10
        typed = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual((typed.atk, typed.health), (2, 1))
        self.assertEqual(a.gold, 10 - raw_cost(self.PID))
        # 正对照: 加入无类型随从后再用 → 确实 +1/+1
        none_m = fake_minion(game, a, "NONE2", 1, 1, Race.NONE)
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual((none_m.atk, none_m.health), (2, 2))


class TestSpectralSight(unittest.TestCase):
    """TB_BaconShop_HP_065t2 — 每回合首个随从购买免费（被动）。"""

    HERO = "TB_BaconShop_HERO_70"
    PID = "TB_BaconShop_HP_065t2"

    def test_first_buy_free_each_turn(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        bind(game, a, self.PID)
        a.gold = 10
        game.events.fire(game, TURN_START, turn=1, hero=a)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 1)
        self.assertTrue(buy_tavern_minion(game, a, PLAIN_T1))
        self.assertEqual(a.gold, 10)             # 首个免费
        self.assertTrue(buy_tavern_minion(game, a, PLAIN_T1))
        self.assertEqual(a.gold, 10 - 3)         # 第二个全价
        game.events.fire(game, TURN_START, turn=2, hero=a)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 1)

    def test_spell_buy_does_not_consume_free_minion(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        bind(game, a, self.PID)
        a.gold = 10
        game.events.fire(game, TURN_START, turn=1, hero=a)
        self.assertTrue(buy_tavern_spell(game, a))
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 1)
        self.assertTrue(buy_tavern_minion(game, a, PLAIN_T1))
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 0)

    def test_unbound_hero_pays_and_owner_isolation(self):
        game = make_game(self.HERO)
        a, b = game.heroes
        bind(game, a, self.PID)
        a.set(GameTag.FREE_MINION_BUYS_THIS_TURN, 0)
        b.gold = 10
        game.events.fire(game, TURN_START, turn=1, hero=b)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 0)
        self.assertEqual(b.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 0)
        self.assertTrue(buy_tavern_minion(game, b, PLAIN_T1))
        self.assertEqual(b.gold, 10 - 3)         # 未绑定付全价
        # 正对照: 绑定者自己的回合置 1 且首个随从免费
        a.gold = 10
        game.events.fire(game, TURN_START, turn=1, hero=a)
        self.assertEqual(a.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0), 1)
        self.assertTrue(buy_tavern_minion(game, a, PLAIN_T1))
        self.assertEqual(a.gold, 10)


class TestTavernLighting(unittest.TestCase):
    """TB_BaconShop_HP_085 + BG28_885 — 获得/打出 Lantern Light。"""

    HERO = "TB_BaconShop_HERO_70"
    PID = "TB_BaconShop_HP_085"

    def test_gets_lantern_light_from_evolution_chain(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        a.gold = 10
        d = get_db().get(self.PID)
        token_def = get_db().by_dbf(d.evolution_card_id)
        self.assertEqual(token_def.id, "BG28_885")
        self.assertFalse(token_def.is_pool_spell)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.gold, 10 - raw_cost(self.PID))
        spells = [x for x in a.hand if x.card_id == "BG28_885"]
        self.assertEqual(len(spells), 1)

    def test_lantern_light_gives_tier_stats(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))
        spell = [x for x in a.hand if x.card_id == "BG28_885"][0]
        target = put(game, a, PLAIN_T1)
        a.set(GameTag.TAVERN_TIER, 4)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.health), (2 + 4, 1 + 4))
        self.assertNotIn(spell, a.hand)

    def test_lantern_light_pending_choice_path(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        a.gold = 10
        game.use_hero_power(a)
        spell = [x for x in a.hand if x.card_id == "BG28_885"][0]
        target = put(game, a, PLAIN_T1)
        a.set(GameTag.TAVERN_TIER, 2)
        self.assertTrue(game.play_spell(a, spell))
        pick = choose(game, "spell_target")
        self.assertIs(pick, target)
        self.assertEqual((target.atk, target.health), (4, 3))

    def test_lantern_light_no_candidate_whiffs(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        a.gold = 10
        game.use_hero_power(a)
        spell = [x for x in a.hand if x.card_id == "BG28_885"][0]
        self.assertTrue(game.play_spell(a, spell))   # 无候选仍消耗
        self.assertNotIn(spell, a.hand)
        self.assertEqual(game.pending_choices, [])


class TestRunicEmpowerment(unittest.TestCase):
    """TB_BaconShop_HP_702 — +{1}/+{1}，五名友方死亡升级一次。"""

    HERO = "TB_BaconShop_HERO_70"
    PID = "TB_BaconShop_HP_702"

    def make(self):
        game = make_game(self.HERO)
        a = game.heroes[0]
        select(game, a, self.PID)
        bind(game, a, self.PID)
        a.gold = 10
        return game, a

    @staticmethod
    def _kill(game, hero, n):
        for _ in range(n):
            m = game.create_minion(PLAIN_T1, controller=hero)
            game.summon(hero, m)
            m.set(GameTag.HEALTH, 0)
        game.check_deaths()

    def test_base_buff_matches_num1(self):
        game, a = self.make()
        d = get_db().get(self.PID)
        self.assertEqual((d.num(0), d.num(1)), (5, 1))
        target = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, target))
        self.assertEqual(a.gold, 10 - raw_cost(self.PID))
        self.assertEqual((target.atk, target.health),
                         (2 + d.num(1), 1 + d.num(1)))

    def test_no_upgrade_after_four_deaths(self):
        game, a = self.make()
        self._kill(game, a, 4)
        self.assertEqual(a._runic_bonus, 1)
        self.assertEqual(a._runic_deaths, 4)
        target = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, target))
        self.assertEqual((target.atk, target.health), (3, 2))

    def test_upgrade_after_five_deaths(self):
        game, a = self.make()
        self._kill(game, a, 5)
        self.assertEqual(a._runic_bonus, 2)
        self.assertEqual(a._runic_deaths, 0)
        target = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, target))
        self.assertEqual((target.atk, target.health), (4, 3))

    def test_enemy_deaths_not_counted(self):
        game, a = self.make()
        b = game.heroes[1]
        self._kill(game, b, 5)
        self.assertEqual(a._runic_bonus, 1)
        self.assertEqual(a._runic_deaths, 0)

    def test_stale_target_whiffs_no_gold(self):
        game, a = self.make()
        enemy = put(game, game.heroes[1], PLAIN_T1)
        self.assertFalse(game.use_hero_power(a, enemy))
        self.assertEqual(a.gold, 10)
        self.assertEqual((enemy.atk, enemy.health), (2, 1))
        # 正对照: 己方目标可用且 +num(1)/+num(1)
        mine = put(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a, mine))
        self.assertEqual((mine.atk, mine.health), (3, 2))
        self.assertEqual(a.gold, 10 - raw_cost(self.PID))


if __name__ == "__main__":
    unittest.main()
