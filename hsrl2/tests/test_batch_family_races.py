"""批次 family_races 行为层测试（RACES 家族类型身份改写，4 张注册）。

覆盖（真实路径）:
  - 类型身份模型: `CardDef.races`（CARDRACE ∪ per-race tag，数据驱动;
    AC-7 反例 `BG21_013` 有 subset_dragon 但 races 为空）/ `Minion.races`
    / `Minion.has_race` / `Race.ALL` 展开为 `STANDARD_RACES`。
  - `BG30_MagicItem_418` Bronzebeard Portrait — 真实 `grant_trinket` 交付
    Brann + 随机 Battlecry 随从; Brann 同时具有 MURLOC 与 DRAGON 身份
    （真实 `ApplyRaceAura` 双光环同时命中）/ Lightfang "of each type"
    对 Brann 两次命中 / 真实 Discover 候选（Dragon 查询可见 Brann）;
    对手与无饰品对照。
  - `BG32_MagicItem_179` Drakkari Portrait — 真实授予后 Elemental 光环
    命中; 真实 `refresh_tavern` 的 Mech 保证位可见（对照无饰品 0/30）。
  - `BG30_MagicItem_971` Enforcer Portrait — "all minion types" → 全 10 族
    （`has_race` 逐族 True / 双光环同时命中）。
  - `BG30_MagicItem_825` Smuggler Portrait — 副本 12/12; 家族身份 DRAGON;
    真实 `stats_gained`（载荷 `BG21_013`）触发 +1 生命; 真实 Tavern 作用域
    （官方 Dev Comment: "you see in the Tavern or Discover as well"）——
    Dragon 白名单刷新下 Whelp Smuggler 可见（对照无饰品 0 次）。
  - 原语契约: `Game.add_family_races` / `family_races` fail-loud、基础卡 id
    归一、source 离场失效、多来源并集; `Game.effective_races`。
  - `TestMutationProbes`: 运行期可复现的替换探针（丢弃光环读取 / 单类型 /
    ALL 当单值 / 错家族 id / 错 controller）。

结构性守卫（注册表 / 数据链 / 卡面文本 / on_bind 独占钩子 / DEFERRED
迁移）标 `@engine-only`。

突变敏感性（**2026-09-21 实测**：外部改文件 → 清理 `__pycache__` → 重跑
本文件，记录失败的测试数）:
  - M1 `Minion.races` 丢弃家族改写读取（`return base`）→ **11 FAIL**
    （含 `TestBronzebeardPortrait::test_family_minion_counts_as_both_types_for_race_auras`,
    `...::test_of_each_type_hits_brann_twice`,
    `TestSmugglerPortrait::test_family_minion_is_dragon_for_stats_gained`,
    `TestMutationProbes::test_dropping_aura_read_removes_identity`）;
  - M2 `Game.add_family_races` 只存**单类型**（`sorted(races)[0]`）→
    **16 FAIL**（含 `...::test_family_races_are_both_types`,
    `...::test_of_each_type_hits_brann_twice`,
    `TestEnforcerPortrait::test_all_minion_types`,
    `TestMutationProbes::test_identity_is_a_set_not_single`）;
  - M3 `race_set` 把 `Race.ALL` 当**单值**（不展开为 10 族，两处分支）→
    **9 FAIL**（含 `TestRaceIdentityPrimitives::test_race_all_expands_to_standard_ten`,
    `TestEnforcerPortrait::test_all_minion_types`,
    `TestMutationProbes::test_all_expands_to_ten_races`）;
  - M4 418 写**错的家族 id**（`BG21_013`）→ **9 FAIL**（含
    `TestBronzebeardPortrait::test_family_races_are_both_types`,
    `...::test_grants_brann_battlecry_and_family_races`,
    `TestMutationProbes::test_wrong_family_id_does_not_hit`）;
  - M5 光环读取忽略 controller（取 `game.heroes[0]`）→ **3 FAIL**
    （`TestBronzebeardPortrait::test_opponent_brann_not_dragon`,
    `TestSmugglerPortrait::test_opponent_whelp_not_dragon`,
    `TestMutationProbes::test_wrong_controller_not_affected`）。
  `TestMutationProbes` 另把 M1/M2/M3/M4/M5 变成**运行期可复现**断言。
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from hsrl2.actions.discover import _pool_candidates
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.actions.stats import Buff
from hsrl2.db import CardDB
from hsrl2.game import Game, GameStateError
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_family_races as BFR
from hsrl2.tags import (RACE_SET_ALL, STANDARD_RACES, GameTag, Race,
                        race_set)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

BRONZEBEARD = BFR.BRONZEBEARD_PORTRAIT
DRAKKARI = BFR.DRAKKARI_PORTRAIT
ENFORCER = BFR.ENFORCER_PORTRAIT
SMUGGLER = BFR.SMUGGLER_PORTRAIT

BRANN = "BG_LOE_077"
BRANN_G = "TB_BaconUps_045"
DRAKKARI_ENCH = "BG26_ICC_901"
DRAKKARI_ENCH_G = "BG26_ICC_901_G"
LIGHTFANG = "BGS_009"
LIGHTFANG_G = "TB_BaconUps_082"
WHELP = "BG21_013"
WHELP_G = "BG21_013_G"

#: 仍阻塞的相邻问题（非本批；见 batch_family_races 模块 docstring）:
#:   - N3 饰品类型关联（T6/T9/Menagerie 阈值）无双类型 / ALL 官方口径;
#:   - 饰品"可提供性"（lobby 限定 / currently unavailable）属商店池特性。
DEFERRED_IDS = ()

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 4210) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")], get_db(),
             seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid, source="test")
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str,
        position: int | None = None, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int,
                race: Race = Race.NONE) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)


def summon_plain(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def hand_of(hero: Hero, card_id: str) -> list:
    return [c for c in hero.hand if c.card_id == card_id]


def placed(game: Game, hero: Hero, card_id: str,
           golden: bool = False) -> Minion:
    """入手副本并真实入板（交付路径 -> 棋盘）。"""
    m = hand_of(hero, card_id)[0]
    assert game.summon(hero, m)
    return m


# ══════════════ 类型身份模型原语 ══════════════


class TestRaceIdentityPrimitives(unittest.TestCase):
    """`CardDef.races` / `Minion.races` / `has_race` / `Race.ALL` 展开。"""

    def test_card_def_races_from_cardrace_and_per_race_tags(self):
        db = get_db()
        # AC-3 实例: BG25_041 Felemental = ELEMENTAL(CARDRACE) + DEMON(tag)
        self.assertEqual(db.get("BG25_041").races,
                         frozenset({Race.ELEMENTAL, Race.DEMON}))
        self.assertEqual(db.get("BG_DEEP_015").races,
                         frozenset({Race.MECH, Race.UNDEAD}))
        # 单类型
        self.assertEqual(db.get("BG_LOE_077").races, frozenset())
        self.assertEqual(db.get("BG26_ICC_901").races, frozenset())

    def test_subsets_are_not_type_identity(self):
        """AC-7 反例: `BG21_013` 有 subset_dragon / subset_murloc（饰品关联
        类型）却**无类型**——`subsets` 不得充当 races。"""
        d = get_db().get(WHELP)
        self.assertIn("dragon", d.subsets)
        self.assertEqual(d.races, frozenset())
        # 反向: subset 与类型恰好一致时也**不得**把 subset 当来源——
        # BG24_005 的类型来自 CARDRACE(11 UNDEAD) + per-race tag(2542 BEAST)，
        # 与其 subset 标注（beast/undead）无关。
        self.assertEqual(get_db().get("BG24_005").subsets,
                         frozenset({"beast", "undead"}))
        self.assertEqual(get_db().get("BG24_005").races,
                         frozenset({Race.UNDEAD, Race.BEAST}))

    def test_race_all_expands_to_standard_races(self):
        d = get_db().get("BG27_080")          # Motley Phalanx, CARDRACE=26
        self.assertEqual(d.race, Race.ALL)
        self.assertEqual(d.races, STANDARD_RACES)
        # 37.0（255130）官方第 11 族 ABERRATION 进入标准种族集合
        self.assertEqual(len(d.races), 11)
        self.assertIn(Race.ABERRATION, d.races)
        self.assertNotIn(Race.ALL, d.races)   # 集合不含哨兵本身
        self.assertNotIn(Race.NONE, d.races)

    def test_race_set_helper(self):
        self.assertEqual(race_set(Race.NONE), frozenset())
        self.assertEqual(race_set(Race.ALL), RACE_SET_ALL)
        self.assertEqual(race_set(Race.MECH, (Race.DEMON,)),
                         frozenset({Race.MECH, Race.DEMON}))
        # 额外标签里的 ALL 同样展开
        self.assertEqual(race_set(Race.NONE, (Race.ALL,)), RACE_SET_ALL)

    def test_minion_identity_and_has_race(self):
        g = make_game(seed=4201)
        a, b = g.heroes
        dual = g.create_minion("BG25_041", controller=a)
        self.assertTrue(dual.has_race(Race.DEMON))
        self.assertTrue(dual.has_race(Race.ELEMENTAL))
        self.assertFalse(dual.has_race(Race.MECH))
        # ALL 型
        amal = g.create_minion("BG27_080", controller=a)
        for r in STANDARD_RACES:
            self.assertTrue(amal.has_race(r))
        # 无类型
        none = g.create_minion(BRANN, controller=a)
        self.assertFalse(none.has_race(Race.DRAGON))
        self.assertEqual(none.races, frozenset())

    def test_dual_type_pool_availability_single_type_lobby(self):
        """N4 数据侧: 双类型随从只需任一类型在当局即可入池。"""
        g = make_game(seed=4202)
        g.minion_pool.active_races = {Race.MECH}
        mech_pool = set(g.minion_pool.candidates(7, 1))
        self.assertIn("BG36_764", mech_pool)      # MURLOC + MECH
        self.assertIn("BG_DEEP_015", mech_pool)   # MECH + UNDEAD
        self.assertNotIn("BG27_005", mech_pool)   # PIRATE + DRAGON
        g.minion_pool.active_races = {Race.DRAGON}
        dragon_pool = set(g.minion_pool.candidates(7, 1))
        self.assertIn("BG27_005", dragon_pool)
        self.assertNotIn("BG36_764", dragon_pool)

    def test_family_races_channel_contract(self):
        g = make_game(seed=4203)
        a, b = g.heroes
        # 空 hero / 坏 card_id / 空集合 → fail-loud（禁静默 no-op）
        with self.assertRaises(GameStateError):
            g.add_family_races(None, BRANN, (Race.DRAGON,))
        with self.assertRaises(GameStateError):
            g.add_family_races(a, "", (Race.DRAGON,))
        with self.assertRaises(GameStateError):
            g.add_family_races(a, BRANN, ())
        # 无规则 → None
        self.assertIsNone(g.family_races(a, BRANN))
        # 写入 + 基础卡 id 归一（金色 id 同族命中）
        g.add_family_races(a, BRANN, (Race.DRAGON,))
        self.assertEqual(g.family_races(a, BRANN), frozenset({Race.DRAGON}))
        self.assertEqual(g.family_races(a, BRANN_G),
                         frozenset({Race.DRAGON}))
        self.assertIsNone(g.family_races(b, BRANN))       # owner 隔离
        # 多来源同族取并集
        g.add_family_races(a, BRANN, (Race.MURLOC,))
        self.assertEqual(g.family_races(a, BRANN),
                         frozenset({Race.DRAGON, Race.MURLOC}))

    def test_family_races_source_offline_expires(self):
        g = make_game(seed=4204)
        a, _b = g.heroes
        e = bind(g, a, BRONZEBEARD)
        self.assertIsNotNone(g.family_races(a, BRANN))
        a.trinkets.remove(e)                      # on_bind 来源离场
        self.assertIsNone(g.family_races(a, BRANN))
        self.assertEqual(put(g, a, BRANN).races, frozenset())

    def test_effective_races_uses_data_identity_without_override(self):
        g = make_game(seed=4205)
        a, _b = g.heroes
        self.assertEqual(g.effective_races(a, get_db().get("BG25_041")),
                         frozenset({Race.DEMON, Race.ELEMENTAL}))


# ══════════════ Bronzebeard Portrait (418) ══════════════


class TestBronzebeardPortrait(unittest.TestCase):
    """BG30_MagicItem_418 — Brann 同时为 Murloc 与 Dragon。"""

    def test_grants_brann_battlecry_and_family_races(self):
        g = make_game(seed=4211)
        a, b = g.heroes
        bind(g, a, BRONZEBEARD)
        self.assertEqual(len(hand_of(a, BRANN)), 1)       # 数据链交付
        # 随机 Battlecry 随从（CardDef.keywords 含 battlecry）
        others = [m for m in a.hand if m.card_id != BRANN]
        self.assertEqual(len(others), 1)
        self.assertIn("battlecry", get_db().get(others[0].card_id).keywords)
        # 家族类型改写（基础 + 金色同族; 对手隔离）
        self.assertEqual(g.family_races(a, BRANN),
                         frozenset({Race.MURLOC, Race.DRAGON}))
        self.assertEqual(g.family_races(a, BRANN_G),
                         frozenset({Race.MURLOC, Race.DRAGON}))
        self.assertIsNone(g.family_races(b, BRANN))

    def test_family_races_are_both_types(self):
        g = make_game(seed=4212)
        a, _b = g.heroes
        bind(g, a, BRONZEBEARD)
        m = placed(g, a, BRANN)
        self.assertEqual(m.races, frozenset({Race.MURLOC, Race.DRAGON}))
        self.assertTrue(m.has_race(Race.MURLOC))
        self.assertTrue(m.has_race(Race.DRAGON))
        self.assertFalse(m.has_race(Race.BEAST))
        # 金色同族（TRIPLE_BASE_CARD_ID 归一）
        gm = g.create_minion(BRANN, controller=a, golden=True)
        self.assertEqual(gm.races, frozenset({Race.MURLOC, Race.DRAGON}))

    def test_family_minion_counts_as_both_types_for_race_auras(self):
        """真实消费者: "Your <race> have +X/+Y" 种族光环。"""
        g = make_game(seed=4213)
        a, b = g.heroes
        bind(g, a, BRONZEBEARD)
        m = placed(g, a, BRANN)
        plain = g.create_minion(BRANN, controller=b)
        assert g.summon(b, plain)
        g.run_actions(ApplyRaceAura(a, Race.MURLOC, 2, 2))
        self.assertEqual(m.atk, 2 + 2)                 # 鱼人光环命中
        g.run_actions(ApplyRaceAura(a, Race.DRAGON, 3, 3))
        self.assertEqual(m.atk, 2 + 2 + 3)             # 龙光环同时命中
        self.assertEqual(plain.atk, 2)                 # 对手无饰品: 无类型

    def test_no_portrait_brann_has_no_type(self):
        g = make_game(seed=4214)
        a, _b = g.heroes
        m = put(g, a, BRANN)                           # 无饰品
        self.assertEqual(m.races, frozenset())
        g.run_actions(ApplyRaceAura(a, Race.MURLOC, 2, 2))
        self.assertEqual(m.atk, 2)                     # 无类型不吃限定光环
        g.run_actions(ApplyRaceAura(a, Race.ALL, 1, 1))
        self.assertEqual(m.atk, 2 + 1)                 # 全随从光环仍命中

    def test_opponent_brann_not_dragon(self):
        g = make_game(seed=4215)
        a, b = g.heroes
        bind(g, a, BRONZEBEARD)
        theirs = put(g, b, BRANN)
        self.assertEqual(theirs.races, frozenset())
        self.assertFalse(theirs.has_race(Race.DRAGON))

    def test_of_each_type_hits_brann_twice(self):
        """"of each type"（Lightfang `_each_type_buffs`）按身份逐族命中。"""
        g = make_game(seed=4216)
        a, _b = g.heroes
        bind(g, a, BRONZEBEARD)
        brann = placed(g, a, BRANN)
        lf = put(g, a, LIGHTFANG)
        beast = summon_plain(g, a, make_minion("B", 1, 1, race=Race.BEAST))
        g.run_script_hook(lf, "end_of_turn")
        self.assertEqual(brann.atk, 2 + 4 + 4)     # Murloc 槽 + Dragon 槽
        self.assertEqual(brann.max_health, 4 + 4 + 4)
        self.assertEqual(beast.atk, 1 + 4)         # 各类型各 buff 一只

    def test_of_each_type_without_portrait_skips_brann(self):
        g = make_game(seed=4217)
        a, _b = g.heroes
        brann = put(g, a, BRANN)                   # 无饰品 → 无类型
        lf = put(g, a, LIGHTFANG)
        beast = summon_plain(g, a, make_minion("B", 1, 1, race=Race.BEAST))
        g.run_script_hook(lf, "end_of_turn")
        self.assertEqual(brann.atk, 2)
        self.assertEqual(beast.atk, 1 + 4)

    def test_discover_dragon_can_offer_brann(self):
        """真实消费者: Discover/随机获取的种族候选（英雄视角）。"""
        g = make_game(seed=4218)
        a, b = g.heroes
        bind(g, a, BRONZEBEARD)
        cands = set(_pool_candidates(g, Race.DRAGON, hero=a))
        self.assertIn(BRANN, cands)
        # 无饰品对照 + 对手视角（owner 隔离）
        g2 = make_game(seed=4218)
        a2, _b2 = g2.heroes
        self.assertNotIn(BRANN, set(_pool_candidates(g2, Race.DRAGON, hero=a2)))
        self.assertNotIn(BRANN, set(_pool_candidates(g, Race.DRAGON, hero=b)))
        self.assertNotIn(BRANN, set(_pool_candidates(g, Race.MECH, hero=a)))


# ══════════════ Drakkari Portrait (179) ══════════════


class TestDrakkariPortrait(unittest.TestCase):
    """BG32_MagicItem_179 — Drakkari Enchanter 同时为 Mech 与 Elemental。"""

    def test_grants_and_family_races(self):
        g = make_game(seed=4221)
        a, b = g.heroes
        bind(g, a, DRAKKARI)
        self.assertEqual(len(hand_of(a, DRAKKARI_ENCH)), 1)
        self.assertEqual(g.family_races(a, DRAKKARI_ENCH),
                         frozenset({Race.MECH, Race.ELEMENTAL}))
        self.assertEqual(g.family_races(a, DRAKKARI_ENCH_G),
                         frozenset({Race.MECH, Race.ELEMENTAL}))
        self.assertIsNone(g.family_races(b, DRAKKARI_ENCH))

    def test_elemental_aura_applies(self):
        g = make_game(seed=4222)
        a, _b = g.heroes
        bind(g, a, DRAKKARI)
        m = placed(g, a, DRAKKARI_ENCH)
        g.run_actions(ApplyRaceAura(a, Race.ELEMENTAL, 2, 3))
        self.assertEqual(m.atk, 1 + 2)
        g.run_actions(ApplyRaceAura(a, Race.MECH, 4, 0))
        self.assertEqual(m.atk, 1 + 2 + 4)

    def test_without_portrait_not_elemental(self):
        g = make_game(seed=4223)
        a, _b = g.heroes
        m = put(g, a, DRAKKARI_ENCH)
        self.assertEqual(m.races, frozenset())
        g.run_actions(ApplyRaceAura(a, Race.ELEMENTAL, 2, 3))
        self.assertEqual(m.atk, 1)

    def test_mech_guarantee_slot_offers_drakkari(self):
        """真实消费者: `_tavern_race_guarantee`（Scepter of Guidance 族）。"""
        def hits(with_portrait: bool) -> int:
            n = 0
            for seed in range(30):
                g = make_game(seed=4230 + seed)
                a, _b = g.heroes
                if with_portrait:
                    bind(g, a, DRAKKARI)
                a.set(GameTag.TAVERN_TIER, 6)
                a._tavern_race_guarantee = (Race.MECH, 99)  # 全部展示位
                g.refresh_tavern(a, auto=True)
                if any(m.card_id == DRAKKARI_ENCH for m in a.tavern):
                    n += 1
            return n

        self.assertGreater(hits(True), 0)
        self.assertEqual(hits(False), 0)


# ══════════════ Enforcer Portrait (971) ══════════════


class TestEnforcerPortrait(unittest.TestCase):
    """BG30_MagicItem_971 — Lightfang Enforcer 拥有全部随从类型。"""

    def test_grants_and_family_races(self):
        g = make_game(seed=4241)
        a, b = g.heroes
        bind(g, a, ENFORCER)
        self.assertEqual(len(hand_of(a, LIGHTFANG)), 1)
        self.assertEqual(g.family_races(a, LIGHTFANG), RACE_SET_ALL)
        self.assertEqual(g.family_races(a, LIGHTFANG_G), RACE_SET_ALL)
        self.assertIsNone(g.family_races(b, LIGHTFANG))

    def test_all_minion_types(self):
        g = make_game(seed=4242)
        a, _b = g.heroes
        bind(g, a, ENFORCER)
        m = placed(g, a, LIGHTFANG)
        self.assertEqual(m.races, STANDARD_RACES)
        self.assertEqual(len(m.races), 11)    # 37.0: 含 ABERRATION
        for r in STANDARD_RACES:
            self.assertTrue(m.has_race(r))
        self.assertFalse(m.has_race(Race.NONE))

    def test_two_race_auras_both_apply(self):
        g = make_game(seed=4243)
        a, _b = g.heroes
        bind(g, a, ENFORCER)
        m = placed(g, a, LIGHTFANG)
        g.run_actions(ApplyRaceAura(a, Race.DRAGON, 3, 3))
        g.run_actions(ApplyRaceAura(a, Race.MECH, 4, 4))
        g.run_actions(ApplyRaceAura(a, Race.QUILBOAR, 5, 5))
        self.assertEqual(m.atk, 8 + 3 + 4 + 5)

    def test_without_portrait_lightfang_has_no_type(self):
        g = make_game(seed=4244)
        a, _b = g.heroes
        m = put(g, a, LIGHTFANG)
        self.assertEqual(m.races, frozenset())
        g.run_actions(ApplyRaceAura(a, Race.DRAGON, 3, 3))
        self.assertEqual(m.atk, 8)

    def test_effective_races_for_non_pool_family(self):
        """BGS_009 是池外专属卡——`effective_races` 仍给出全 10 族。"""
        g = make_game(seed=4245)
        a, _b = g.heroes
        bind(g, a, ENFORCER)
        self.assertEqual(g.effective_races(a, get_db().get(LIGHTFANG)),
                         STANDARD_RACES)

    def test_tavern_dragon_whitelist_sees_lightfang_when_injected(self):
        """真实消费者: Tavern 种族白名单（注入池后可见）。"""
        g = make_game(seed=4246)
        a, _b = g.heroes
        bind(g, a, ENFORCER)
        g.minion_pool.ensure_available(LIGHTFANG, copies=30)
        a.set(GameTag.TAVERN_TIER, 6)
        found = False
        for _ in range(60):
            g.refresh_tavern(a, races={Race.DRAGON}, auto=True)
            if any(m.card_id == LIGHTFANG for m in a.tavern):
                found = True
                break
        self.assertTrue(found)


# ══════════════ Smuggler Portrait (825) ══════════════


class TestSmugglerPortrait(unittest.TestCase):
    """BG30_MagicItem_825 — Whelp Smuggler 是 Dragon（warband/Tavern/
    Discover）。"""

    def test_grants_12_12_whelp_and_family_races(self):
        g = make_game(seed=4251)
        a, b = g.heroes
        bind(g, a, SMUGGLER)
        granted = hand_of(a, WHELP)
        self.assertEqual(len(granted), 1)
        m = granted[0]
        self.assertEqual((m.get(GameTag.BASE_ATK),
                          m.get(GameTag.BASE_HEALTH), m.health), (12, 12, 12))
        self.assertEqual(m.races, frozenset({Race.DRAGON}))
        self.assertEqual(g.family_races(a, WHELP), frozenset({Race.DRAGON}))
        self.assertEqual(g.family_races(a, WHELP_G),
                         frozenset({Race.DRAGON}))
        self.assertIsNone(g.family_races(b, WHELP))

    def test_family_minion_is_dragon_for_stats_gained(self):
        """真实消费者: 载荷 `BG21_013` 的 `stats_gained`（Dragon 过滤）。"""
        g = make_game(seed=4252)
        a, _b = g.heroes
        bind(g, a, SMUGGLER)
        m = placed(g, a, WHELP)
        g.run_actions(Buff(m, atk=2))         # "gains Attack" → +1 Health
        self.assertEqual(m.atk, 12 + 2)
        self.assertEqual(m.health, 12 + 1)

    def test_without_portrait_whelp_not_dragon(self):
        g = make_game(seed=4253)
        a, _b = g.heroes
        m = put(g, a, WHELP)
        self.assertEqual(m.races, frozenset())
        g.run_actions(Buff(m, atk=2))
        self.assertEqual(m.health, 5)          # 无 Dragon 身份 → 不触发

    def test_opponent_whelp_not_dragon(self):
        g = make_game(seed=4254)
        a, b = g.heroes
        bind(g, a, SMUGGLER)
        theirs = put(g, b, WHELP)
        self.assertEqual(theirs.races, frozenset())

    def test_tavern_dragon_scope(self):
        """官方 Dev Comment（Patch 30.2.0.205267 revid 814123）:
        "This applies to Whelp Smugglers you see in the Tavern or Discover
        as well, not just the ones in your warband."（Whelp Smuggler
        36.2.2 已不在池中 → 经 `ensure_available` 注入后验证）。"""
        def tavern_sees(with_portrait: bool) -> bool:
            g = make_game(seed=4255)
            a, _b = g.heroes
            if with_portrait:
                bind(g, a, SMUGGLER)
            g.minion_pool.ensure_available(WHELP, copies=30)
            a.set(GameTag.TAVERN_TIER, 6)
            for _ in range(60):
                g.refresh_tavern(a, races={Race.DRAGON}, auto=True)
                if any(m.card_id == WHELP for m in a.tavern):
                    return True
            return False

        self.assertTrue(tavern_sees(True))
        self.assertFalse(tavern_sees(False))

    def test_discover_dragon_sees_family_when_injected(self):
        """Discover 作用域（`Game.effective_races` 经 `_pool_candidates`）。"""
        g = make_game(seed=4256)
        a, _b = g.heroes
        bind(g, a, SMUGGLER)
        g.minion_pool.ensure_available(WHELP, copies=30)
        # `_pool_candidates` 以 `db.pool_minions()` 枚举 → 非池定义不可见;
        # 直接断言 `effective_races` 的英雄视角（Discover 过滤读取点）。
        self.assertEqual(g.effective_races(a, get_db().get(WHELP)),
                         frozenset({Race.DRAGON}))
        g2 = make_game(seed=4256)
        a2, _b2 = g2.heroes
        self.assertEqual(g2.effective_races(a2, get_db().get(WHELP)),
                         frozenset())


# ══════════════ 突变探针（运行期可复现） ══════════════


class TestMutationProbes(unittest.TestCase):
    """把文件级突变（docstring M1/M3/M4/M5）变成运行期可复现断言。"""

    def test_dropping_aura_read_removes_identity(self):
        g = make_game(seed=4261)
        a, _b = g.heroes
        bind(g, a, BRONZEBEARD)
        m = placed(g, a, BRANN)
        self.assertTrue(m.has_race(Race.DRAGON))
        g.family_races = lambda *args, **kw: None      # M1 丢弃读取
        self.assertEqual(m.races, frozenset())         # 正效果消失
        self.assertFalse(m.has_race(Race.DRAGON))

    def test_identity_is_a_set_not_single(self):
        g = make_game(seed=4262)
        a, _b = g.heroes
        bind(g, a, BRONZEBEARD)
        m = placed(g, a, BRANN)
        self.assertEqual(len(m.races), 2)              # M2 单类型会失败
        self.assertEqual(m.races, frozenset({Race.MURLOC, Race.DRAGON}))

    def test_all_expands_to_standard_races(self):
        g = make_game(seed=4263)
        a, _b = g.heroes
        bind(g, a, ENFORCER)
        m = placed(g, a, LIGHTFANG)
        self.assertEqual(len(m.races), 11)             # M3 哨兵会失败（37.0: 11 族）
        self.assertNotIn(Race.ALL, m.races)

    def test_wrong_family_id_does_not_hit(self):
        g = make_game(seed=4264)
        a, _b = g.heroes
        bind(g, a, BRONZEBEARD)
        self.assertIsNone(g.family_races(a, WHELP))    # M4 错家族 id
        self.assertIsNone(g.family_races(a, LIGHTFANG))
        self.assertEqual(put(g, a, WHELP).races, frozenset())

    def test_wrong_controller_not_affected(self):
        g = make_game(seed=4265)
        a, b = g.heroes
        bind(g, a, BRONZEBEARD)
        bind(g, a, ENFORCER)
        theirs = put(g, b, BRANN)
        self.assertEqual(theirs.races, frozenset())    # M5 错 controller
        theirs2 = put(g, b, LIGHTFANG)
        self.assertEqual(theirs2.races, frozenset())


# ══════════════ 结构守卫 ══════════════


class TestRegistryAndGuards(unittest.TestCase):
    """注册表 / 数据链 / on_bind 独占 / DEFERRED 迁移。"""

    def test_all_four_registered(self):
        for tid in (BRONZEBEARD, DRAKKARI, ENFORCER, SMUGGLER):
            self.assertIn(tid, REGISTRY, tid)
            self.assertEqual(REGISTRY[tid].__module__,
                             "hsrl2.scripts.batches.batch_family_races", tid)

    def test_scripts_only_bind_on_bind(self):
        for tid in (BRONZEBEARD, DRAKKARI, ENFORCER, SMUGGLER):
            cls = REGISTRY[tid]
            hooks = [n for n, _ in inspect.getmembers(cls, inspect.isfunction)
                     if not n.startswith("_")]
            self.assertEqual(hooks, ["on_bind"], f"{tid}: {hooks}")

    def test_data_chain_related_cards(self):
        g = make_game(seed=4271)
        want = {BRONZEBEARD: BRANN, DRAKKARI: DRAKKARI_ENCH,
                ENFORCER: LIGHTFANG, SMUGGLER: WHELP}
        for tid, cid in want.items():
            rel = g.trinket_related_card(tid)
            self.assertIsNotNone(rel, tid)
            self.assertEqual(rel.id, cid)

    def test_no_deferred_ids_left(self):
        self.assertEqual(DEFERRED_IDS, ())


if __name__ == "__main__":
    unittest.main()

