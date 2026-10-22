"""批次 37x_payloadgap1 行为层测试（9 载荷 + 8 宿主 + E 类 5 张）。

覆盖（全部真实引擎路径）:
  - 法术: 真实 `game.play_spell`（定向 PendingChoice / 无目标 / 池记账）
  - 战吼/亡语/EoT/售出: 真实 `game.play_minion` / `destroy_minion` /
    `end_recruit_phase`（EoT 分发）/ `sell_minion`
  - 磁力: 真实 `game.attach_magnetic`（`magnetized` 事件、
    属性/关键词/亡语栈、hero 级监听器）
  - Activate: 真实 `game.use_activate`（引擎扣费/计次）
  - 变形: 真实 `Transform(force_golden=True, gilded_not_tripled=True)`
  - 购买: 真实 `game.buy_from_tavern`（minion_bought / spell_bought）
  - 酒馆持久 Buff: 真实 `add_tavern_entity` / `buy_from_tavern`
  - 动态属性钩子: 真实 `Entity.atk/max_health`（"wherever they are"）

每卡均有正对照（钩子换 no-op 后必失败）与负对照（非目标/对手/敌方
Volumizer/无候选/满手/池耗尽/Tier 超限）。

DEFERRED 台账守卫: Deity/Discard/Geomagus/Conflagration 族不得注册。
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
from hsrl2.scripts.batches import batch_37x_payloadgap1 as B
from hsrl2.tags import CardType, GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 41, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def dummy(hero: Hero, name: str = "Dummy", atk: int = 1,
          health: int = 50, race: Race | None = None) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, race)
    hero.board.append(m)
    game._update_positions(hero)
    return m


def hand_minion(game: Game, hero: Hero, card_id: str,
                golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def hand_spell(game: Game, hero: Hero, card_id: str):
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def tavern_add(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    game.add_tavern_entity(hero, m)
    return m


def clear_tavern(hero: Hero) -> None:
    """清空初始随机酒馆，保证酒馆相关断言确定性（测试专用）。"""
    hero.tavern.clear()


def cast_spell(game: Game, hero: Hero, card_id: str,
               target=None, choose_index: int = 0) -> list:
    """施放法术。

    - `target` 给定 → 引擎直接以该目标结算（不产生 PendingChoice）。
    - `target=None` → 若有 PendingChoice 则按 choose_index 选项结算并返回
      被选中的选项列表（用于显式验证定向选择协议）。
    """
    spell = hand_spell(game, hero, card_id)
    assert game.play_spell(hero, spell, target=target)
    if target is not None:
        return [target]
    picks = []
    while game.pending_choices:
        choice = game.pending_choices.pop(0)
        picks.append(choice.options[choose_index])
        choice.choose(choose_index)
    return picks


def pirate_id() -> str:
    for d in get_db().pool_minions():
        if Race.PIRATE in d.races and d.tech_level <= 4 \
                and REGISTRY.get(d.id) is None:
            return d.id
    raise AssertionError("no plain tier<=4 pirate")


def murloc_id() -> str:
    for d in get_db().pool_minions():
        if Race.MURLOC in d.races and REGISTRY.get(d.id) is None:
            return d.id
    raise AssertionError("no plain murloc")


def elemental_id() -> str:
    for d in get_db().pool_minions():
        if Race.ELEMENTAL in d.races and REGISTRY.get(d.id) is None:
            return d.id
    raise AssertionError("no plain elemental")


# ══════════════════════════════════════════════════════════════════════
# 结构性: 注册表 / 金色 CardDef / DEFERRED 台账守卫
# ══════════════════════════════════════════════════════════════════════


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 35 id 注册 / 载荷-宿主数据链 / DEFERRED 守卫。"""

    def test_registered_payloads_and_hosts(self):
        expected = [
            # 载荷
            B.SEAFOOD_STEW, B.ARCANE_ABSORPTION, B.SLUDGE_CORROSION,
            B.RED_VOLUMIZER, B.RED_VOLUMIZER_G,
            B.BLUE_VOLUMIZER, B.BLUE_VOLUMIZER_G,
            B.GREEN_VOLUMIZER, B.GREEN_VOLUMIZER_G,
            # 宿主
            B.GORMLING_GOURMET, B.GORMLING_GOURMET_G,
            B.LEYLINE_SURFACER, B.LEYLINE_SURFACER_G,
            B.FETID_CORRODER, B.FETID_CORRODER_G,
            B.NIGHTMARE_CORRODER, B.NIGHTMARE_CORRODER_G,
            B.AUTO_ACCELERATOR, B.AUTO_ACCELERATOR_G,
            B.CONVEYOR_CONSTRUCT, B.CONVEYOR_CONSTRUCT_G,
            B.RESOURCEFUL_ROBOT, B.RESOURCEFUL_ROBOT_G,
            B.AUTO_REVEILLE, B.AUTO_REVEILLE_G,
            # E 类
            B.ELITE_NAVIGATOR, B.ELITE_NAVIGATOR_G,
            B.SACRIFICIAL_WRATHGUARD, B.SACRIFICIAL_WRATHGUARD_G,
            B.VICTORIOUS_GEOMANT, B.VICTORIOUS_GEOMANT_G,
            B.SEWER_ESCAPEE, B.SEWER_ESCAPEE_G,
            B.SHOALFIN_MYSTIC, B.SHOALFIN_MYSTIC_G,
        ]
        self.assertEqual(len(expected), 35)
        for cid in expected:
            self.assertIn(cid, REGISTRY, cid)

    def test_payload_flags(self):
        db = get_db()
        self.assertTrue(db.get(B.SEAFOOD_STEW).is_pool_spell)
        self.assertTrue(db.get(B.SLUDGE_CORROSION).is_pool_spell)
        self.assertFalse(db.get(B.ARCANE_ABSORPTION).is_pool_spell)
        for cid in (B.RED_VOLUMIZER, B.BLUE_VOLUMIZER, B.GREEN_VOLUMIZER):
            d = db.get(cid)
            self.assertEqual(d.card_type, CardType.MINION)
            self.assertIn("magnetic", d.keywords)

    def test_template_numbers(self):
        db = get_db()
        self.assertEqual((db.get(B.SEAFOOD_STEW).num(0),
                          db.get(B.SEAFOOD_STEW).num(1)), (1, 1))
        self.assertEqual((db.get(B.SLUDGE_CORROSION).num(0),
                          db.get(B.SLUDGE_CORROSION).num(1)), (1, 1))
        self.assertEqual(db.get(B.RED_VOLUMIZER).num(1), 3)
        self.assertEqual(db.get(B.RED_VOLUMIZER_G).num(1), 6)
        self.assertEqual(db.get(B.GREEN_VOLUMIZER).num(1), 1)
        self.assertEqual(db.get(B.GREEN_VOLUMIZER).num(2), 1)
        self.assertEqual(db.get(B.GREEN_VOLUMIZER_G).num(1), 2)
        self.assertEqual(db.get(B.AUTO_REVEILLE).num(2), 3)
        self.assertEqual(db.get(B.VICTORIOUS_GEOMANT).num(1), 6)
        self.assertEqual(db.get(B.VICTORIOUS_GEOMANT_G).num(1), 12)

    def test_deferred_not_registered(self):
        # 谱系: CONFLAGRATION/FIRELANDS（F-06）、BG36_103/318/110（F-07、
        # 以及 F-08 Discard 批注册 BG28_582/BGFYM_005/BG36_320 等）均已
        # 移出本守卫。剩余仅 BG28_583 Geomagus（触发链证据缺口）。
        for cid in ("BG28_583",):
            self.assertNotIn(cid, REGISTRY, cid)

    def test_hosts_payload_data_chain(self):
        """宿主 "Get <载荷>" 的卡 id 均存在于 CardDB（防拼写漂移）。"""
        db = get_db()
        for cid in (B.SEAFOOD_STEW, B.ARCANE_ABSORPTION,
                    B.SLUDGE_CORROSION):
            self.assertIsNotNone(db.get(cid))


# ══════════════════════════════════════════════════════════════════════
# C 类载荷: Seafood Stew
# ══════════════════════════════════════════════════════════════════════


class TestSeafoodStew(unittest.TestCase):
    """BG32_337 — 定向 +1/+1，按不同 Bonus Keyword 数重复。"""

    def test_no_bonus_keyword_plus_one(self):
        game = make_game(seed=100)
        a = game.heroes[0]
        target = dummy(a, "T", 1, 20)
        picks = cast_spell(game, a, B.SEAFOOD_STEW)
        self.assertEqual(picks, [target])
        self.assertEqual((target.atk, target.health), (1 + 1, 20 + 1))

    def test_repeat_for_each_distinct_bonus_keyword(self):
        game = make_game(seed=101)
        a = game.heroes[0]
        source_t = dummy(a, "ST", 1, 20)
        source_t.set(GameTag.TAUNT, True)
        source_d = dummy(a, "SD", 1, 20)
        source_d.set(GameTag.DIVINE_SHIELD, True)
        target = dummy(a, "T", 1, 20)
        cast_spell(game, a, B.SEAFOOD_STEW, target=target)
        self.assertEqual((target.atk, target.health), (1 + 3, 20 + 3))

    def test_duplicate_keywords_count_once(self):
        game = make_game(seed=102)
        a = game.heroes[0]
        for i in range(3):
            m = dummy(a, f"D{i}", 1, 20)
            m.set(GameTag.TAUNT, True)
        target = dummy(a, "T", 1, 20)
        cast_spell(game, a, B.SEAFOOD_STEW, target=target)
        self.assertEqual((target.atk, target.health), (1 + 2, 20 + 2))

    def test_tavern_spell_extra_stacks(self):
        game = make_game(seed=103)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 1)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 1)
        target = dummy(a, "T", 1, 20)
        cast_spell(game, a, B.SEAFOOD_STEW, target=target)
        self.assertEqual((target.atk, target.health), (1 + 2, 20 + 2))

    def test_granted_bonus_keyword_counts(self):
        game = make_game(seed=104)
        a = game.heroes[0]
        m = dummy(a, "G", 1, 20)
        game.grant_bonus_keyword(m, GameTag.WINDFURY)
        target = dummy(a, "T", 1, 20)
        cast_spell(game, a, B.SEAFOOD_STEW, target=target)
        self.assertEqual((target.atk, target.health), (1 + 2, 20 + 2))

    def test_target_is_pending_choice(self):
        game = make_game(seed=105)
        a = game.heroes[0]
        target = dummy(a, "T", 1, 20)
        spell = hand_spell(game, a, B.SEAFOOD_STEW)
        self.assertTrue(game.play_spell(a, spell))
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "spell_target")
        self.assertEqual(choice.options, [target])
        choice.choose(0)
        self.assertEqual((target.atk, target.health), (2, 21))


# ══════════════════════════════════════════════════════════════════════
# C 类载荷: Arcane Absorption
# ══════════════════════════════════════════════════════════════════════


class TestArcaneAbsorption(unittest.TestCase):
    """BG35_911 — 元素获得酒馆最高当前生命随从的一半属性。"""

    def test_half_stats_of_highest_health_tavern_minion(self):
        game = make_game(seed=110)
        a = game.heroes[0]
        clear_tavern(a)
        ref = tavern_add(game, a, elemental_id())
        ref_d = get_db().get(ref.card_id)
        target = dummy(a, "T", 1, 20, Race.ELEMENTAL)
        cast_spell(game, a, B.ARCANE_ABSORPTION, target=target)
        self.assertEqual((target.atk, target.health),
                         (1 + ref_d.atk // 2, 20 + ref_d.health // 2))

    def test_current_health_rule(self):
        game = make_game(seed=111)
        a = game.heroes[0]
        clear_tavern(a)
        big = tavern_add(game, a, elemental_id())
        big.set(GameTag.HEALTH, 2)                     # 当前 2 / 最大 8+
        small = tavern_add(game, a, murloc_id())
        small.set(GameTag.HEALTH, 6)                   # 当前 6 → 最高当前生命
        target = dummy(a, "T", 1, 20, Race.ELEMENTAL)
        expected_atk = small.atk // 2
        expected_hp = small.max_health // 2
        cast_spell(game, a, B.ARCANE_ABSORPTION, target=target)
        self.assertEqual((target.atk, target.health),
                         (1 + expected_atk, 20 + expected_hp))

    def test_no_element_target_not_selectable(self):
        game = make_game(seed=112)
        a = game.heroes[0]
        clear_tavern(a)
        tavern_add(game, a, elemental_id())
        dummy(a, "Beast", 1, 20, Race.BEAST)           # 非元素
        spell = hand_spell(game, a, B.ARCANE_ABSORPTION)
        self.assertTrue(game.play_spell(a, spell))
        # 无合法目标 → 引擎不产生 PendingChoice，法术落空仍消耗
        self.assertEqual(game.pending_choices, [])

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=113)
        a = game.heroes[0]
        clear_tavern(a)
        target = dummy(a, "T", 1, 20, Race.ELEMENTAL)
        spell = hand_spell(game, a, B.ARCANE_ABSORPTION)
        self.assertTrue(game.play_spell(a, spell))
        self.assertEqual((target.atk, target.health), (1, 20))


# ══════════════════════════════════════════════════════════════════════
# C 类载荷: Sludge Corrosion
# ══════════════════════════════════════════════════════════════════════


class TestSludgeCorrosion(unittest.TestCase):
    """BG36_301t — 全体 +1/+1（discard 分支由 F-08 接线）。"""

    def test_buffs_all_friendly_minions(self):
        game = make_game(seed=120)
        a, b = game.heroes
        m1 = dummy(a, "M1", 1, 10)
        m2 = dummy(a, "M2", 2, 10)
        enemy = dummy(b, "E", 1, 10)
        cast_spell(game, a, B.SLUDGE_CORROSION)
        self.assertEqual((m1.atk, m1.health), (2, 11))
        self.assertEqual((m2.atk, m2.health), (3, 11))
        self.assertEqual((enemy.atk, enemy.health), (1, 10))

    def test_extra_stacks(self):
        game = make_game(seed=121)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 2)
        m = dummy(a, "M", 1, 10)
        cast_spell(game, a, B.SLUDGE_CORROSION)
        self.assertEqual((m.atk, m.health), (2, 10 + 1 + 2))

    def test_discarded_casts_twice(self):
        """F-08: 被弃置时结算 2 次（+1/+1 → +2/+2）。"""
        game = make_game(seed=122)
        a = game.heroes[0]
        target = dummy(a, "T", 1, 10)
        spell = hand_spell(game, a, B.SLUDGE_CORROSION)
        self.assertTrue(game.discard_card(a, spell))
        self.assertEqual((target.atk, target.health), (3, 12))


# ══════════════════════════════════════════════════════════════════════
# C 类载荷: Volumizer 三变体
# ══════════════════════════════════════════════════════════════════════


class TestVolumizers(unittest.TestCase):
    """BG34_170t/t2/t3 — 首次打出/Magnetize 授予 hero 级游戏长光环。"""

    def test_red_played_grants_attack_aura(self):
        game = make_game(seed=130)
        a = game.heroes[0]
        red = put(game, B.RED_VOLUMIZER, a)
        self.assertEqual(getattr(a, "volumizer_aura_atk", 0), 3)
        self.assertEqual(red.atk, 3 + 3)

    def test_aura_reaches_hand_and_tavern(self):
        game = make_game(seed=131)
        a = game.heroes[0]
        in_hand = hand_minion(game, a, B.RED_VOLUMIZER)
        in_tavern = tavern_add(game, a, B.RED_VOLUMIZER)
        put(game, B.RED_VOLUMIZER, a)
        self.assertEqual(in_hand.atk, 3 + 3)
        self.assertEqual(in_tavern.atk, 3 + 3)

    def test_red_second_copy_accumulates(self):
        game = make_game(seed=132)
        a = game.heroes[0]
        first = put(game, B.RED_VOLUMIZER, a)
        put(game, B.RED_VOLUMIZER, a)
        self.assertEqual(getattr(a, "volumizer_aura_atk", 0), 6)
        self.assertEqual(first.atk, 3 + 6)

    def test_blue_grants_health_aura_and_current_health(self):
        game = make_game(seed=133)
        a = game.heroes[0]
        blue = put(game, B.BLUE_VOLUMIZER, a)
        self.assertEqual(getattr(a, "volumizer_aura_health", 0), 3)
        self.assertEqual(blue.max_health, 3 + 3)
        self.assertEqual(blue.health, 3 + 3)

    def test_magnetized_volumizer_grants_aura(self):
        game = make_game(seed=134)
        a = game.heroes[0]
        host = put(game, B.RED_VOLUMIZER, a)
        self.assertEqual(getattr(a, "volumizer_aura_atk", 0), 3)
        blue = hand_minion(game, a, B.BLUE_VOLUMIZER)
        self.assertTrue(game.play_minion(a, blue, magnetic_target=host))
        self.assertEqual(getattr(a, "volumizer_aura_health", 0), 3)

    def test_golden_red_grants_six(self):
        game = make_game(seed=135)
        a = game.heroes[0]
        red = put(game, B.RED_VOLUMIZER, a, golden=True)
        golden_def = get_db().get(B.RED_VOLUMIZER_G)
        self.assertEqual(getattr(a, "volumizer_aura_atk", 0), 6)
        self.assertEqual(red.atk, golden_def.atk + 6)

    def test_green_grants_both(self):
        game = make_game(seed=136)
        a = game.heroes[0]
        green = put(game, B.GREEN_VOLUMIZER, a)
        self.assertEqual(getattr(a, "volumizer_aura_atk", 0), 1)
        self.assertEqual(getattr(a, "volumizer_aura_health", 0), 1)
        self.assertEqual((green.atk, green.max_health), (4, 4))

    def test_first_time_only(self):
        game = make_game(seed=137)
        a = game.heroes[0]
        red = put(game, B.RED_VOLUMIZER, a)
        B._grant_volumizer_aura(game, red)          # 再调一次不得重复
        self.assertEqual(getattr(a, "volumizer_aura_atk", 0), 3)

    def test_non_volumizer_and_enemy_unaffected(self):
        game = make_game(seed=138)
        a, b = game.heroes
        mech = dummy(a, "Mech", 1, 20, Race.MECH)
        # 敌方 Volumizer 直接摆板（不经 on_summon → 不触发它自己的光环），
        # 验证我方光环不跨英雄生效。
        enemy_vol = game.create_minion(B.RED_VOLUMIZER, controller=b)
        enemy_vol.zone = Zone.PLAY
        b.board.append(enemy_vol)
        game._update_positions(b)
        put(game, B.RED_VOLUMIZER, a)
        self.assertEqual(mech.atk, 1)
        self.assertEqual(getattr(b, "volumizer_aura_atk", 0), 0)
        self.assertEqual(enemy_vol.atk, 3)


# ══════════════════════════════════════════════════════════════════════
# C 类宿主: Get 载荷
# ══════════════════════════════════════════════════════════════════════


class TestGormlingGourmet(unittest.TestCase):
    """BG32_336 — BC+DR: Get Seafood Stew（金 2）。"""

    def test_battlecry_gets_one_stew(self):
        game = make_game(seed=140)
        a = game.heroes[0]
        m = hand_minion(game, a, B.GORMLING_GOURMET)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([s.card_id for s in a.hand], [B.SEAFOOD_STEW])

    def test_golden_battlecry_gets_two(self):
        game = make_game(seed=141)
        a = game.heroes[0]
        m = hand_minion(game, a, B.GORMLING_GOURMET, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([s.card_id for s in a.hand],
                         [B.SEAFOOD_STEW, B.SEAFOOD_STEW])

    def test_deathrattle_gets_one(self):
        game = make_game(seed=142)
        a = game.heroes[0]
        m = put(game, B.GORMLING_GOURMET, a)
        before = game.spell_pool.available(B.SEAFOOD_STEW)
        game.destroy_minion(m)
        self.assertEqual([s.card_id for s in a.hand], [B.SEAFOOD_STEW])
        self.assertEqual(game.spell_pool.available(B.SEAFOOD_STEW),
                         before - 1)

    def test_golden_deathrattle_gets_two(self):
        game = make_game(seed=143)
        a = game.heroes[0]
        m = put(game, B.GORMLING_GOURMET, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual([s.card_id for s in a.hand],
                         [B.SEAFOOD_STEW, B.SEAFOOD_STEW])


class TestLeylineSurfacer(unittest.TestCase):
    """BG35_881 — BC+DR: Get Arcane Absorption（非池；金 2）。"""

    def test_battlecry_deathrattle(self):
        game = make_game(seed=150)
        a = game.heroes[0]
        m = hand_minion(game, a, B.LEYLINE_SURFACER)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([s.card_id for s in a.hand], [B.ARCANE_ABSORPTION])
        game.destroy_minion(m)
        self.assertEqual([s.card_id for s in a.hand],
                         [B.ARCANE_ABSORPTION, B.ARCANE_ABSORPTION])

    def test_golden_doubles(self):
        game = make_game(seed=151)
        a = game.heroes[0]
        m = hand_minion(game, a, B.LEYLINE_SURFACER, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 2)
        a.hand.clear()
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 2)

    def test_non_pool_spell_does_not_touch_spell_pool(self):
        game = make_game(seed=152)
        a = game.heroes[0]
        before = game.spell_pool.total_remaining()
        m = hand_minion(game, a, B.LEYLINE_SURFACER)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.spell_pool.total_remaining(), before)


class TestCorroders(unittest.TestCase):
    """BG36_112 Fetid / BG36_115 Nightmare — Get Sludge Corrosion。"""

    def test_fetid_battlecry(self):
        game = make_game(seed=160)
        a = game.heroes[0]
        m = hand_minion(game, a, B.FETID_CORRODER)
        before = game.spell_pool.available(B.SLUDGE_CORROSION)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([s.card_id for s in a.hand], [B.SLUDGE_CORROSION])
        self.assertEqual(game.spell_pool.available(B.SLUDGE_CORROSION),
                         before - 1)

    def test_fetid_golden_two(self):
        game = make_game(seed=161)
        a = game.heroes[0]
        m = hand_minion(game, a, B.FETID_CORRODER, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 2)

    def test_nightmare_eot(self):
        game = make_game(seed=162)
        a = game.heroes[0]
        m = put(game, B.NIGHTMARE_CORRODER, a)
        game.run_script_hook(m, "end_of_turn")
        self.assertEqual([s.card_id for s in a.hand], [B.SLUDGE_CORROSION])

    def test_nightmare_golden_two(self):
        game = make_game(seed=163)
        a = game.heroes[0]
        m = put(game, B.NIGHTMARE_CORRODER, a, golden=True)
        game.run_script_hook(m, "end_of_turn")
        self.assertEqual(len(a.hand), 2)


class TestVolumizerHosts(unittest.TestCase):
    """BG34_170/171 + BG36_366/367 — Get/Magnetize Volumizer。"""

    def test_auto_accelerator_battlecry(self):
        game = make_game(seed=170)
        a = game.heroes[0]
        m = hand_minion(game, a, B.AUTO_ACCELERATOR)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, B._VOLUMIZER_BASE_IDS)

    def test_auto_accelerator_golden_two(self):
        game = make_game(seed=171)
        a = game.heroes[0]
        m = hand_minion(game, a, B.AUTO_ACCELERATOR, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 2)

    def test_conveyor_deathrattle(self):
        game = make_game(seed=172)
        a = game.heroes[0]
        m = put(game, B.CONVEYOR_CONSTRUCT, a)
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, B._VOLUMIZER_BASE_IDS)

    def test_conveyor_golden_two(self):
        game = make_game(seed=173)
        a = game.heroes[0]
        m = put(game, B.CONVEYOR_CONSTRUCT, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 2)

    def test_resourceful_robot_eot(self):
        game = make_game(seed=174)
        a = game.heroes[0]
        r = put(game, B.RESOURCEFUL_ROBOT, a)
        atk_before, hp_before = r.atk, r.health
        game.run_script_hook(r, "end_of_turn")
        self.assertEqual(len(a.hand), 1)
        self.assertGreater((r.atk - atk_before) + (r.health - hp_before), 0)
        self.assertGreater(
            getattr(a, "volumizer_aura_atk", 0)
            + getattr(a, "volumizer_aura_health", 0), 0)

    def test_resourceful_robot_golden_two(self):
        game = make_game(seed=175)
        a = game.heroes[0]
        r = put(game, B.RESOURCEFUL_ROBOT, a, golden=True)
        game.run_script_hook(r, "end_of_turn")
        self.assertEqual(len(a.hand), 2)

    def _prepare_tavern_minions(self, game, a, count=4):
        """清空酒馆并放入 count 只**不同 id** 的随从（防购买即三连合并）。"""
        clear_tavern(a)
        cids = [d.id for d in get_db().pool_minions()
                if REGISTRY.get(d.id) is None][:count]
        assert len(cids) == count
        for cid in cids:
            tavern_add(game, a, cid)
        return [e for e in a.tavern if isinstance(e, Minion)]

    def test_auto_reveille_after_three_buys(self):
        game = make_game(seed=176)
        a = game.heroes[0]
        ar = put(game, B.AUTO_REVEILLE, a)
        a.gold = 30
        minions = self._prepare_tavern_minions(game, a)
        for i in range(2):
            self.assertTrue(game.buy_from_tavern(a, minions[i]))
        self.assertEqual(len(a.hand), 2)
        self.assertTrue(game.buy_from_tavern(a, minions[2]))
        self.assertEqual(len(a.hand), 4)      # 3 张购买 + 1 份 Volumizer 副本
        self.assertGreater(ar.atk + ar.health, 4 + 8)

    def test_auto_reveille_counts_spell_buys(self):
        game = make_game(seed=177)
        a = game.heroes[0]
        put(game, B.AUTO_REVEILLE, a)
        a.gold = 30
        clear_tavern(a)
        for _ in range(3):
            spell = game.create_spell(B.SEAFOOD_STEW, controller=a)
            game.add_tavern_entity(a, spell)
        # 买 2 张不触发、第 3 张触发（spell_bought 同样计数）
        for e in [s for s in a.tavern if not isinstance(s, Minion)][:2]:
            self.assertTrue(game.buy_from_tavern(a, e))
        self.assertEqual(len(a.hand), 2)
        third = [s for s in a.tavern if not isinstance(s, Minion)][0]
        self.assertTrue(game.buy_from_tavern(a, third))
        self.assertEqual(len(a.hand), 4)      # 3 张法术 + 1 份副本

    def test_auto_reveille_golden_two_copies(self):
        game = make_game(seed=178)
        a = game.heroes[0]
        put(game, B.AUTO_REVEILLE, a, golden=True)
        a.gold = 30
        minions = self._prepare_tavern_minions(game, a)
        for i in range(3):
            self.assertTrue(game.buy_from_tavern(a, minions[i]))
        # 3 张购买 + 2 份 golden 副本
        self.assertEqual(len(a.hand), 5)


# ══════════════════════════════════════════════════════════════════════
# E 类: Elite Navigator
# ══════════════════════════════════════════════════════════════════════


class TestEliteNavigator(unittest.TestCase):
    """BG32_231 — 战吼金化 Tier≤4 海盗（金色 2 个，两段目标链）。"""

    def _play(self, game, hero, golden=False):
        m = hand_minion(game, hero, B.ELITE_NAVIGATOR, golden=golden)
        self.assertTrue(game.play_minion(hero, m))
        return m

    def test_base_makes_one_pirate_golden(self):
        game = make_game(seed=180)
        a = game.heroes[0]
        p = put(game, pirate_id(), a)
        self._play(game, a)
        self.assertEqual(len(game.pending_choices), 1)
        game.pending_choices.pop(0).choose(0)
        self.assertTrue(a.board[0].is_golden)
        self.assertTrue(a.board[0].get(GameTag.GILDED_NOT_TRIPLED))

    def test_keeps_buffs(self):
        game = make_game(seed=181)
        a = game.heroes[0]
        p = put(game, pirate_id(), a)
        base_def = get_db().get(p.card_id)
        golden_def = get_db().by_dbf(base_def.triple_upgrade_id)
        from hsrl2.entity import Buff as Enchant
        p.add_buff(Enchant(atk=2, health=2))
        self._play(game, a)
        game.pending_choices.pop(0).choose(0)
        self.assertEqual((a.board[0].atk, a.board[0].max_health),
                         (golden_def.atk + 2, golden_def.health + 2))

    def test_tier5_pirate_not_candidate(self):
        game = make_game(seed=182)
        a = game.heroes[0]
        t5 = None
        for d in get_db().pool_minions():
            if Race.PIRATE in d.races and d.tech_level >= 5:
                t5 = d.id
                break
        put(game, t5, a)
        m = hand_minion(game, a, B.ELITE_NAVIGATOR)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.pending_choices, [])
        self.assertFalse(a.board[0].is_golden)

    def test_golden_two_stage_choice(self):
        game = make_game(seed=183)
        a = game.heroes[0]
        put(game, pirate_id(), a)
        put(game, pirate_id(), a)
        n = self._play(game, a, golden=True)
        self.assertEqual(len(game.pending_choices), 1)
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(len(game.pending_choices), 1)   # 第二段
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(
            sum(1 for m in a.board
                if m is not n and m.is_golden and m.has_race(Race.PIRATE)), 2)

    def test_golden_single_candidate_only_one(self):
        game = make_game(seed=184)
        a = game.heroes[0]
        put(game, pirate_id(), a)
        n = self._play(game, a, golden=True)
        self.assertEqual(len(game.pending_choices), 1)
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(
            sum(1 for m in a.board
                if m is not n and m.is_golden and m.has_race(Race.PIRATE)), 1)


# ══════════════════════════════════════════════════════════════════════
# E 类: Sacrificial Wrathguard
# ══════════════════════════════════════════════════════════════════════


class TestSacrificialWrathguard(unittest.TestCase):
    """BG36_362 — DR 酒馆全随从 +2/+2；Activate(1): Improve this。"""

    def test_deathrattle_buffs_all_tavern_minions(self):
        game = make_game(seed=190)
        a = game.heroes[0]
        clear_tavern(a)
        el = tavern_add(game, a, elemental_id())
        mc = tavern_add(game, a, murloc_id())
        el_def = get_db().get(el.card_id)
        mc_def = get_db().get(mc.card_id)
        w = put(game, B.SACRIFICIAL_WRATHGUARD, a)
        game.destroy_minion(w)
        self.assertEqual((el.atk, el.health),
                         (el_def.atk + 2, el_def.health + 2))
        self.assertEqual((mc.atk, mc.health),
                         (mc_def.atk + 2, mc_def.health + 2))
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 1)

    def test_activate_improves(self):
        game = make_game(seed=191)
        a = game.heroes[0]
        clear_tavern(a)
        el = tavern_add(game, a, elemental_id())
        el_def = get_db().get(el.card_id)
        w = put(game, B.SACRIFICIAL_WRATHGUARD, a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, w))
        self.assertEqual(a.gold, 9)
        self.assertEqual(getattr(w, "_wrathguard_improves", 0), 1)
        game.destroy_minion(w)
        self.assertEqual((el.atk, el.health),
                         (el_def.atk + 4, el_def.health + 4))

    def test_golden_values(self):
        game = make_game(seed=192)
        a = game.heroes[0]
        clear_tavern(a)
        el = tavern_add(game, a, elemental_id())
        el_def = get_db().get(el.card_id)
        w = put(game, B.SACRIFICIAL_WRATHGUARD, a, golden=True)
        a.gold = 10
        self.assertTrue(game.use_activate(a, w))
        game.destroy_minion(w)
        self.assertEqual((el.atk, el.health),
                         (el_def.atk + 8, el_def.health + 8))

    def test_bought_tavern_minion_keeps_buff(self):
        game = make_game(seed=193)
        a = game.heroes[0]
        clear_tavern(a)
        el = tavern_add(game, a, elemental_id())
        el_def = get_db().get(el.card_id)
        w = put(game, B.SACRIFICIAL_WRATHGUARD, a)
        game.destroy_minion(w)
        a.gold = 10
        self.assertTrue(game.buy_from_tavern(a, el))
        self.assertEqual((el.atk, el.health),
                         (el_def.atk + 2, el_def.health + 2))


# ══════════════════════════════════════════════════════════════════════
# E 类: Victorious Geomant
# ══════════════════════════════════════════════════════════════════════


class TestVictoriousGeomant(unittest.TestCase):
    """BG36_370 — Activate: Get 6 Blood Gems；放不下的施放最左随从。"""

    def _activate(self, game, hero, golden=False):
        gm = put(game, B.VICTORIOUS_GEOMANT, hero, golden=golden)
        hero.gold = 10
        self.assertTrue(game.use_activate(hero, gm))
        return gm

    def test_empty_hand_gets_six_gems(self):
        game = make_game(seed=200)
        a = game.heroes[0]
        dummy(a, "T", 1, 20)
        self._activate(game, a)
        self.assertEqual(len(a.hand), 6)
        self.assertTrue(all(s.card_id == B.BLOOD_GEM for s in a.hand))

    def test_overflow_cast_on_leftmost(self):
        game = make_game(seed=201)
        a = game.heroes[0]
        left = dummy(a, "Left", 1, 20)
        dummy(a, "Right", 1, 20)
        self._activate(game, a)
        self.assertEqual(len(a.hand), 6)
        self._activate(game, a)                       # 第 2 次：手牌 6 → 4 空位
        self.assertEqual(len(a.hand), 10)
        self.assertEqual(left.get(GameTag.GEMS_PLAYED_ON), 2)

    def test_full_hand_all_cast(self):
        game = make_game(seed=202)
        a = game.heroes[0]
        left = dummy(a, "Left", 1, 20)
        while len(a.hand) < 10:
            a.hand.append(game.create_spell("BG28_810", controller=a))
        self._activate(game, a)
        self.assertEqual(len(a.hand), 10)
        self.assertEqual(left.get(GameTag.GEMS_PLAYED_ON), 6)

    def test_golden_twelve(self):
        game = make_game(seed=203)
        a = game.heroes[0]
        dummy(a, "T", 1, 20)
        self._activate(game, a, golden=True)
        self.assertEqual(len(a.hand), 10)             # 放 10
        # 12 颗 → 10 入手 + 2 施放
        self.assertEqual(a.board[0].get(GameTag.GEMS_PLAYED_ON), 2)

    def test_full_hand_overflow_casts_on_leftmost_board_minion(self):
        """满手 0 空位：Get 的血宝石全部改为施放最左随从（本卡自身）。"""
        game = make_game(seed=204)
        a = game.heroes[0]
        while len(a.hand) < 10:
            a.hand.append(game.create_spell("BG28_810", controller=a))
        gm = put(game, B.VICTORIOUS_GEOMANT, a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, gm))
        self.assertEqual(len(a.hand), 10)                 # 一颗也没入手
        self.assertEqual(gm.get(GameTag.GEMS_PLAYED_ON), 6)


# ══════════════════════════════════════════════════════════════════════
# E 类: Sewer Escapee
# ══════════════════════════════════════════════════════════════════════


class TestSewerEscapee(unittest.TestCase):
    """BG36_700 — Activate: 另一 Murloc +7/+7 + 随机 Bonus Keyword。"""

    def _activate(self, game, hero, golden=False):
        se = put(game, B.SEWER_ESCAPEE, hero, golden=golden)
        hero.gold = 10
        self.assertTrue(game.use_activate(hero, se))
        return se

    def test_activate_target_choice_and_effect(self):
        game = make_game(seed=210)
        a = game.heroes[0]
        m = put(game, murloc_id(), a)
        se = self._activate(game, a)
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "activate_target")
        self.assertNotIn(se, choice.options)
        choice.choose(0)
        base = get_db().get(m.card_id)
        self.assertEqual((m.atk, m.health),
                         (base.atk + 7, base.health + 7))
        self.assertTrue(m.get(GameTag.BONUS_KEYWORDS))

    def test_golden_values(self):
        game = make_game(seed=211)
        a = game.heroes[0]
        m = put(game, murloc_id(), a)
        self._activate(game, a, golden=True)
        game.pending_choices.pop(0).choose(0)
        base = get_db().get(m.card_id)
        self.assertEqual((m.atk, m.health),
                         (base.atk + 14, base.health + 14))

    def test_no_other_murloc_fizzles(self):
        game = make_game(seed=212)
        a = game.heroes[0]
        self._activate(game, a)
        self.assertEqual(game.pending_choices, [])

    def test_self_not_candidate(self):
        game = make_game(seed=213)
        a = game.heroes[0]
        se = put(game, B.SEWER_ESCAPEE, a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, se))
        self.assertEqual(game.pending_choices, [])


# ══════════════════════════════════════════════════════════════════════
# E 类: Shoalfin Mystic
# ══════════════════════════════════════════════════════════════════════


class TestShoalfinMystic(unittest.TestCase):
    """BG32_860 — 售出: 酒馆法术额外 +1/+1 this game（金 +2/+2）。"""

    def test_sell_grants_extra(self):
        game = make_game(seed=220)
        a = game.heroes[0]
        m = put(game, B.SHOALFIN_MYSTIC, a)
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 1)

    def test_golden_grants_two(self):
        game = make_game(seed=221)
        a = game.heroes[0]
        m = put(game, B.SHOALFIN_MYSTIC, a, golden=True)
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 2)

    def test_stacks(self):
        game = make_game(seed=222)
        a = game.heroes[0]
        for _ in range(2):
            m = put(game, B.SHOALFIN_MYSTIC, a)
            self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2)

    def test_end_to_end_with_seafood_stew(self):
        game = make_game(seed=223)
        a = game.heroes[0]
        target = dummy(a, "T", 1, 20)
        m = put(game, B.SHOALFIN_MYSTIC, a)
        game.sell_minion(a, m)
        cast_spell(game, a, B.SEAFOOD_STEW)
        self.assertEqual((target.atk, target.health), (1 + 2, 20 + 2))


if __name__ == "__main__":
    unittest.main()
