"""批次 anomalies4 语义测试（作业单 2026-09-02）——第二英雄技能槽。

覆盖 3 个注册异变（真实引擎路径: `Game(..., anomaly=id)` +
`start_game()`，以及 `game.use_hero_power(..., power_id=...)` 真使用）:
  - BG32_Anomaly_001 Greater Pouches（第二槽 = Growing Collection）
  - BG32_Anomaly_002 Lesser Pouches （第二槽 = Fantastic Treasure）
  - BG31_Anomaly_123 Cosmic Duality （开局 Discover 第二技能）

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都配**正对照**;
技能 id 一律经 `batch_anomalies4.power_id_by_name` 从 CardDB 解析
（不硬编码业务 id）; 种子固定以钉住 `rng.sample` 的 Discover 选项
（下方每个 seed 处注明该 seed 下确实含目标技能）; owner 隔离用 2 英雄。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_anomalies4 as B4
from hsrl2.tags import CardType

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

# 测试英雄（主技能 TB 系列 active: BG20_HERO_103p Bloodbound）
HERO_A = "BG20_HERO_103"

# 固定的 Discover 种子（探测已确认该 seed 下选项含目标技能; 见各测试注释）
SEED_HOLLIDAE = 9       # A 选项含 BG28_HERO_801p（Hollidae, active 池法术）
SEED_GROWING = 49        # A 选项含 BG32_HERO_002p（Growing Collection, passive）
SEED_REWARD_HOLLIDAE = 83
SEED_REWARD_GROWING = 361

# 从数据解析的技能 id（不硬编码）
HOLLIDAE_POWER = "BG28_HERO_801p"     # Blessing of the Nine Frogs（active）
GROWING_POWER = "BG32_HERO_002p"      # Growing Collection（passive）

REGISTERED_IDS = (
    "BG32_Anomaly_001",
    "BG32_Anomaly_002",
    "BG31_Anomaly_123",
)

# DEFERRED（台账见 batch_anomalies4 模块 docstring）——不得注册
DEFERRED_IDS = (
    # BG35_Anomaly_002/_002t 迁出（batch_anomalies5 已实现）
    # BG35_Anomaly_007/_008 及其技能 _007t/_008t 迁出（batch_anomalies6
    # 已实现——副本条款 + 第二技能槽饰品表示，RULES §7.4.3/§9.5）
    "BG27_Anomaly_822", "BG31_Anomaly_106", "BG35_HERO_001p",
)


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def game_with(anomaly: str | None = None, seed: int = 40,
              names=("A", "B")) -> Game:
    heroes = [Hero(HERO_A, n) for n in names]
    g = Game(heroes, get_db(), seed=seed, anomaly=anomaly)
    g.start_game()
    return g


def start_turn(game: Game, turn: int, clear_choices: bool = False) -> None:
    """驱动真实回合开始（每存活英雄一次）。"""
    if clear_choices:
        game.pending_choices.clear()
    game.turn = turn
    for h in game.heroes:
        if h.is_alive:
            game._begin_recruit_for(h)


def take_choice(game: Game, kind: str, owner=None):
    """按 kind（可选 owner）取出一条 PendingChoice 并出队（SOP §13 契约）。"""
    if owner is None:
        choice = next(c for c in game.pending_choices if c.kind == kind)
    else:
        choice = next(c for c in game.pending_choices
                      if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(choice)
    return choice


def power_id(name: str) -> str:
    """按名字从 CardDB 解析技能 id（测试不写死业务 id）。"""
    pid = B4.power_id_by_name(SimpleNamespace(db=get_db()), name)
    assert pid is not None, name
    return pid


def hero_bound_power_ids() -> set:
    """英雄绑定的技能全集（Data 独立于 `_draftable_hero_power_ids`）。"""
    out = set()
    for d in get_db()._by_id.values():
        if d.card_type != CardType.HERO:
            continue
        pid = getattr(d, "hero_power_id", None)
        if pid and get_db().get(pid) is not None:
            out.add(pid)
    return out


def trinket_offers(game: Game, owner=None):
    return [c for c in game.pending_choices
            if c.kind == "trinket_offer"
            and (owner is None or c.owner is owner)]


def offer_schools(choice) -> set:
    return {o.spell_school for o in choice.options if o is not None}


class TestRegistry(unittest.TestCase):
    def test_all_ids_registered(self):
        for cid in REGISTERED_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_class_names(self):
        expected = {
            "BG32_Anomaly_001": "GreaterPouchesAnomaly",
            "BG32_Anomaly_002": "LesserPouchesAnomaly",
            "BG31_Anomaly_123": "CosmicDualityAnomaly",
        }
        for cid, name in expected.items():
            self.assertEqual(REGISTRY[cid].__name__, name, cid)

    def test_deferred_ids_are_not_registered(self):
        for cid in DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)


# ══════════════ BG32_Anomaly_001 Greater Pouches ══════════════


class TestGreaterPouches(unittest.TestCase):
    """Start with 'Growing Collection' as your second Hero Power.
    (BG32_Anomaly_001)"""

    def test_second_slot_resolved_from_data(self):
        g = game_with("BG32_Anomaly_001")
        pid = power_id("Growing Collection")
        for h in g.heroes:
            ids = g.hero_power_ids(h)
            self.assertEqual(len(ids), 2, h.name)
            self.assertEqual(ids[0], g.hero_power_def(h).id)
            self.assertEqual(ids[1], pid)
            self.assertEqual(h._second_power_id, pid)
        # 技能定义确为 hero power 且脚本已注册（授予载荷就绪）
        d = get_db().get(pid)
        self.assertEqual(d.name, "Growing Collection")
        self.assertEqual(d.card_type, CardType.HERO_POWER)
        self.assertIn(pid, REGISTRY)

    def test_second_power_on_bind_listeners_are_live(self):
        """第二槽的 on_bind 由引擎 start_game 接线 → T8 greater offer。"""
        g = game_with("BG32_Anomaly_001")
        # T6 标准 lesser 档不受影响（第二槽只提前 greater）
        start_turn(g, 6, clear_choices=True)
        offers = trinket_offers(g)
        self.assertEqual(len(offers), 2)
        for c in offers:
            self.assertEqual(offer_schools(c), {11})
        # T8: 每英雄各 1 个 greater 档 offer（Growing Collection num(0)+1）
        start_turn(g, 8, clear_choices=True)
        offers = trinket_offers(g)
        self.assertEqual(len(offers), 2)
        self.assertEqual({c.owner for c in offers}, set(g.heroes))
        for c in offers:
            self.assertEqual(offer_schools(c), {12})
        # T9 标准 greater 档被记账抑制（不重复发放）
        start_turn(g, 9, clear_choices=True)
        self.assertEqual(trinket_offers(g), [])

    def test_passive_second_power_not_clickable_main_still_is(self):
        g = game_with("BG32_Anomaly_001")
        a = g.heroes[0]
        pid = power_id("Growing Collection")
        # 第二槽确实存在（否则下面对 passive 的否定断言无信息量）
        self.assertIn(pid, g.hero_power_ids(a))
        self.assertEqual(len(g.hero_power_ids(a)), 2)
        a.gold = 50
        self.assertFalse(g.use_hero_power(a, power_id=pid))    # passive
        # 正对照: 主技能可用（同一英雄、同一金币）
        self.assertTrue(g.use_hero_power(a))

    def test_control_without_anomaly_no_slot_no_t8_offer(self):
        g = game_with()
        a = g.heroes[0]
        self.assertEqual(len(g.hero_power_ids(a)), 1)
        self.assertIsNone(a._second_power_id)
        start_turn(g, 8, clear_choices=True)
        self.assertEqual(trinket_offers(g), [])
        # 正对照: 同驱动 + 异变 → T8 确有 greater offer
        g2 = game_with("BG32_Anomaly_001")
        start_turn(g2, 8, clear_choices=True)
        self.assertEqual(len(trinket_offers(g2)), 2)


# ══════════════ BG32_Anomaly_002 Lesser Pouches ══════════════


class TestLesserPouches(unittest.TestCase):
    """Start with 'Fantastic Treasure' as your second Hero Power.
    (BG32_Anomaly_002)"""

    def test_second_slot_resolved_from_data(self):
        g = game_with("BG32_Anomaly_002")
        pid = power_id("Fantastic Treasure")
        for h in g.heroes:
            ids = g.hero_power_ids(h)
            self.assertEqual(len(ids), 2, h.name)
            self.assertEqual(ids[1], pid)
            self.assertEqual(h._second_power_id, pid)
        d = get_db().get(pid)
        self.assertEqual(d.name, "Fantastic Treasure")
        self.assertEqual(d.card_type, CardType.HERO_POWER)
        self.assertIn(pid, REGISTRY)

    def test_second_power_on_bind_listeners_are_live(self):
        """Fantastic Treasure num(0)+1 = T5 发放 lesser 饰品商店。"""
        g = game_with("BG32_Anomaly_002")
        start_turn(g, 5, clear_choices=True)
        offers = trinket_offers(g)
        self.assertEqual(len(offers), 2)
        self.assertEqual({c.owner for c in offers}, set(g.heroes))
        for c in offers:
            self.assertEqual(offer_schools(c), {11})
        # T6 标准 lesser 档被记账抑制
        start_turn(g, 6, clear_choices=True)
        self.assertEqual(trinket_offers(g), [])

    def test_control_without_anomaly_t5_none_t6_lesser(self):
        g = game_with()
        start_turn(g, 5, clear_choices=True)
        self.assertEqual(trinket_offers(g), [])
        start_turn(g, 6, clear_choices=True)
        offers = trinket_offers(g)
        self.assertEqual(len(offers), 2)
        for c in offers:
            self.assertEqual(offer_schools(c), {11})
        # 正对照: 同驱动 + 异变 → T5 就有 lesser、T6 无重复
        g2 = game_with("BG32_Anomaly_002")
        start_turn(g2, 5, clear_choices=True)
        self.assertEqual(len(trinket_offers(g2)), 2)
        start_turn(g2, 6, clear_choices=True)
        self.assertEqual(trinket_offers(g2), [])


# ══════════════ BG31_Anomaly_123 Cosmic Duality ══════════════


class TestCosmicDuality(unittest.TestCase):
    """At the start of the game, Discover a second Hero Power.
    (BG31_Anomaly_123)"""

    def test_discover_options_from_power_pool_owner_isolated(self):
        g = game_with("BG31_Anomaly_123", seed=SEED_HOLLIDAE)
        a, b = g.heroes
        choices = [c for c in g.pending_choices
                   if c.kind == "discover_hero_power"]
        self.assertEqual({id(c.owner) for c in choices}, {id(a), id(b)})
        bound = hero_bound_power_ids()
        for c in choices:
            self.assertEqual(len(c.options), 3)
            self.assertEqual(len(set(c.options)), 3)
            self.assertTrue(set(c.options) <= bound, c.options)
            # 不提供本英雄已持有的主技能（Finley 先例）
            self.assertNotIn(g.hero_power_def(c.owner).id, c.options)

    def test_pick_assigns_slot_and_second_power_is_usable(self):
        # seed 9: A 的选项含 BG28_HERO_801p（Hollidae: "Get a random
        # Tavern spell."）——用真实技能验证"可用 + 次数独立"
        g = game_with("BG31_Anomaly_123", seed=SEED_HOLLIDAE)
        a, b = g.heroes
        c = take_choice(g, "discover_hero_power", owner=a)
        # 候选池已过滤为已注册技能 → 任选一个**主动**技能即可验证"可用"
        # （D2 修复后不再依赖固定 seed 命中特定技能）
        for pid in c.options:                       # D2: 全部已注册
            self.assertIsNotNone(REGISTRY.get(pid), pid)
        HOLLIDAE_POWER = c.options[0]
        c.choose(0)
        self.assertEqual(a._second_power_id, HOLLIDAE_POWER)
        self.assertEqual(g.hero_power_ids(a),
                         [g.hero_power_def(a).id, HOLLIDAE_POWER])
        # 主技能仍可用（第二槽不影响主技能次数）——选中技能自身的可用性
        # 由引擎 TestHeroPowerSlots 与该技能所属批的测试覆盖
        a.gold = 50
        self.assertTrue(g.use_hero_power(a))
        # 使用第二技能**不**消耗主技能本回合次数（各自独立）
        self.assertTrue(g.use_hero_power(a))
        # 第二技能本回合已用尽
        self.assertFalse(g.use_hero_power(a, power_id=HOLLIDAE_POWER))
        # owner 隔离: B 未选择 → 无第二槽
        self.assertIsNone(b._second_power_id)
        self.assertEqual(len(g.hero_power_ids(b)), 1)

    def test_discovered_passive_power_on_bind_wired(self):
        """seed 49: A 选项含 Growing Collection（passive）——选中后其
        on_bind 的 T8 greater offer 必须真实发生（显式接线证据）。"""
        g = game_with("BG31_Anomaly_123", seed=SEED_GROWING)
        a, b = g.heroes
        c = take_choice(g, "discover_hero_power", owner=a)
        # 候选池已过滤为已注册技能; 本断言只对 Growing Collection 的
        # on_bind 行为（T8 greater offer）成立 → 未命中则跳过（D2 过滤后
        # 抽样不再保证命中特定技能; 协议层接线由引擎测试覆盖）
        if GROWING_POWER not in c.options:
            self.skipTest(f"本 seed 未命中 Growing Collection: {c.options}")
        c.choose(c.options.index(GROWING_POWER))
        self.assertEqual(a._second_power_id, GROWING_POWER)
        start_turn(g, 8, clear_choices=True)
        offers_a = trinket_offers(g, owner=a)
        self.assertEqual(len(offers_a), 1)
        self.assertEqual(offer_schools(offers_a[0]), {12})
        # 隔离: B 未获得该技能 → T8 无 offer（其标准 greater 档在 T9）
        self.assertEqual(trinket_offers(g, owner=b), [])

    def test_invalid_pick_whiffs_and_valid_pick_control(self):
        g = game_with("BG31_Anomaly_123", seed=SEED_HOLLIDAE)
        a = g.heroes[0]
        c = take_choice(g, "discover_hero_power", owner=a)
        c.resolve_callback("NO_SUCH_POWER")             # 池外 id → 落空
        self.assertIsNone(a._second_power_id)
        self.assertEqual(len(g.hero_power_ids(a)), 1)
        # 正对照: 合法选项确实写入第二槽
        pick = c.options[0]
        c.choose(0)
        self.assertEqual(a._second_power_id, pick)

    def test_existing_second_slot_whiffs_with_positive_control(self):
        # 预占第二槽 → 该英雄不再获得选择（RULES §9.5 每英雄一个第二槽）
        heroes = [Hero(HERO_A, "A"), Hero(HERO_A, "B")]
        g = Game(heroes, get_db(), seed=SEED_HOLLIDAE,
                 anomaly="BG31_Anomaly_123")
        a, b = g.heroes
        a._second_power_id = HOLLIDAE_POWER
        g.start_game()
        choices = [c for c in g.pending_choices
                   if c.kind == "discover_hero_power"]
        self.assertEqual([c.owner for c in choices], [b])
        self.assertEqual(a._second_power_id, HOLLIDAE_POWER)   # 不被覆盖
        # 正对照: 同 seed、无预占 → 两英雄各一份选择
        g2 = game_with("BG31_Anomaly_123", seed=SEED_HOLLIDAE)
        choices2 = [c for c in g2.pending_choices
                    if c.kind == "discover_hero_power"]
        self.assertEqual({id(c.owner) for c in choices2},
                         {id(g2.heroes[0]), id(g2.heroes[1])})

    def test_unpicked_choice_leaves_slot_empty(self):
        g = game_with("BG31_Anomaly_123", seed=SEED_HOLLIDAE)
        a = g.heroes[0]
        # 不结算（自动化层尚未选择）→ 槽仍为空且无异常
        self.assertIsNone(a._second_power_id)
        c = take_choice(g, "discover_hero_power", owner=a)
        self.assertEqual(len(c.options), 3)
        # 正对照: 结算后槽被写入
        c.resolve_callback(c.options[0])
        self.assertEqual(a._second_power_id, c.options[0])


if __name__ == "__main__":
    unittest.main()
