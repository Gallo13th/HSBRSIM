"""批次 trinkets33 行为层测试（2 张注册饰品 = 2 CORRECT / 0 DEFERRED）。

覆盖（每张卡真实路径）:
  - `BG30_MagicItem_944` Redeemer Portrait — 真实 `grant_trinket` →
    `on_bind` 授予 `BG28_551` Nalaa the Redeemer + `hero.giver_bonus`
    写入; 真实 `play_spell` 酒馆法术 → 每族代表 +num(0)+extra /
    +num(1)+extra; 金色 Nalaa 基础量取金色 CardDef 且同吃 extra;
    owner 隔离（对手 Nalaa 不加成）; 无饰品对照。
  - `BG30_MagicItem_828` Shaker Portrait — 真实 `grant_trinket` →
    授予 `BG26_505` Zesty Shaker + `copies=1`; Spellcraft 打在本体 →
    **2** 份副本（对照 1 份）; 金色本体 3 份; 对手本体 1 份;
    "Once per turn" 仍生效（同回合第二次不复制）。

结构性守卫（注册表 / 数据链 / 台账 / 无第三态）标 `@engine-only`。
DEFERRED 台账（868/987/869）保持未注册——见模块 docstring; 803 已由
batch_trinkets39 注册迁出（2026-09-18）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game, GameStateError
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets33 as B33
from hsrl2.tags import CardType, GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

REDEEMER = B33.REDEEMER_PORTRAIT
SHAKER = B33.SHAKER_PORTRAIT
NALAA = B33.NALAA
NALAA_G = "BG28_551_G"
ZESTY = B33.ZESTY_SHAKER
ZESTY_G = "BG26_505_G"

# 真实卡（CardDB 按名核实——禁止凭记忆写 id）
MURLOC = "BG26_137"            # Bream Counter（无脚本 Murloc——buff 靶）
_TAVERN_SPELL_ID = "BG28_805"     # Strike Oil T2 池法术（驱动 tavern_spell_cast）
_SPELLCRAFT_SPELL_ID = "BG23_000t"  # Mini-Myrmidon 法术（Spellcraft 驱动）

# 868 Rewinder / 987 Balladist / 869 Felblood Portrait 已由 batch_trinkets31
# 注册（2026-09-19——owner 权威序: wiki 页无 Notes → 卡面天然语言
# "also give X" 增量 = 同句既有量; 869 的两载荷同批由 batch_payload_minions
# 注册）→ 移出本台账，DEFERRED 清零。
DEFERRED_IDS = ()
# 803 Kaboom Bot Portrait 已由 batch_trinkets39 注册（2026-09-18——家族
# 亡语伤害加成读取点 RULES §7.4.16 `family_flags` + `FLAG_KABOOM_DR_BONUS`；
# 金色逐实例 +10 按 wiki 无 Notes → 卡面天然语言）→ 移出本台账

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 3301) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid, source="test")
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def cast_tavern_spell(game: Game, hero: Hero, target=None) -> None:
    """施放一张池法术（驱动 `tavern_spell_cast` / Nalaa 监听）。"""
    assert game.spell_pool.acquire(_TAVERN_SPELL_ID)
    s = game.create_spell(_TAVERN_SPELL_ID, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    assert game.play_spell(hero, s, target=target)


def add_spellcraft_to_hand(game: Game, hero: Hero):
    """构造手牌中的 Spellcraft 法术（镜像 test_batch_econ_misc helper）。"""
    s = game.create_spell(_SPELLCRAFT_SPELL_ID, controller=hero)
    s.scripts = REGISTRY.get(_SPELLCRAFT_SPELL_ID)
    s.set(GameTag.SPELLCRAFT, True)
    s.spellcraft_source_uuid = None
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def _hand_of(hero: Hero, card_id: str) -> list:
    return [c for c in hero.hand if c.card_id == card_id]


class TestRedeemerPortrait(unittest.TestCase):
    """BG30_MagicItem_944 — 授予 Nalaa 且其给予量 +num(0)/+num(1)。"""

    def test_grants_nalaa_and_extra_stats(self):
        g = make_game(seed=3301)
        a, _b = g.heroes
        bind(g, a, REDEEMER)
        granted = _hand_of(a, NALAA)
        self.assertEqual(len(granted), 1)          # 真实数据链授予
        self.assertTrue(g.play_minion(a, granted[0]))
        murloc = put(g, a, MURLOC)
        d = get_db().get(NALAA)
        ex = get_db().get(REDEEMER)
        before = (murloc.atk, murloc.max_health)
        cast_tavern_spell(g, a, target=murloc)
        self.assertEqual(
            (murloc.atk - before[0], murloc.max_health - before[1]),
            (d.num(0) + ex.num(0), d.num(1) + ex.num(1)))

    def test_no_portrait_control_base_stats(self):
        g = make_game(seed=3302)
        a, _b = g.heroes
        put(g, a, NALAA)
        murloc = put(g, a, MURLOC)
        d = get_db().get(NALAA)
        before = (murloc.atk, murloc.max_health)
        cast_tavern_spell(g, a, target=murloc)
        self.assertEqual(
            (murloc.atk - before[0], murloc.max_health - before[1]),
            (d.num(0), d.num(1)))

    def test_golden_nalaa_gets_extra_on_golden_base(self):
        """金色基础量取金色 CardDef（8/6），extra 仍 +num(0)/+num(1)。"""
        g = make_game(seed=3303)
        a, _b = g.heroes
        ex = get_db().get(REDEEMER)
        g.add_giver_bonus(a, NALAA, atk=ex.num(0), health=ex.num(1))
        put(g, a, NALAA, golden=True)
        murloc = put(g, a, MURLOC)
        dg = get_db().get(NALAA_G)
        before = (murloc.atk, murloc.max_health)
        cast_tavern_spell(g, a, target=murloc)
        self.assertEqual(
            (murloc.atk - before[0], murloc.max_health - before[1]),
            (dg.num(0) + ex.num(0), dg.num(1) + ex.num(1)))

    def test_opponent_nalaa_unaffected(self):
        g = make_game(seed=3304)
        a, b = g.heroes
        bind(g, a, REDEEMER)                        # 加成只写 A
        put(g, b, NALAA)
        murloc = put(g, b, MURLOC)
        d = get_db().get(NALAA)
        before = (murloc.atk, murloc.max_health)
        cast_tavern_spell(g, b, target=murloc)
        self.assertEqual(
            (murloc.atk - before[0], murloc.max_health - before[1]),
            (d.num(0), d.num(1)))

    def test_bonus_expires_when_portrait_leaves(self):
        """`source` 离场（饰品被替换）→ 加成失效（RULES §7.4.15 生效期）。"""
        g = make_game(seed=3305)
        a, _b = g.heroes
        ent = bind(g, a, REDEEMER)
        ex = get_db().get(REDEEMER)
        self.assertEqual(g.giver_bonus(a, NALAA)["atk"], ex.num(0))
        a.trinkets.remove(ent)                      # 饰品被替换/移除
        self.assertEqual(g.giver_bonus(a, NALAA),
                         {"atk": 0, "health": 0, "copies": 0})

    def test_broken_data_chain_fails_loud(self):
        """`evolution_card_id` 链条断裂 → GameStateError（SOP §6b）。"""
        g = make_game(seed=3306)
        a, _b = g.heroes
        orig = g.trinket_related_card
        g.trinket_related_card = lambda tid: None
        try:
            with self.assertRaises(GameStateError):
                g.grant_trinket(a, REDEEMER, source="test")
        finally:
            g.trinket_related_card = orig


class TestShakerPortrait(unittest.TestCase):
    """BG30_MagicItem_828 — 授予 Zesty Shaker 且其额外 1 份副本。"""

    def test_grants_shaker_and_extra_copy(self):
        g = make_game(seed=3311)
        a, _b = g.heroes
        bind(g, a, SHAKER)
        granted = _hand_of(a, ZESTY)
        self.assertEqual(len(granted), 1)
        self.assertTrue(g.play_minion(a, granted[0]))
        shaker = a.board[-1]
        s = add_spellcraft_to_hand(g, a)
        self.assertTrue(g.play_spell(a, s, target=shaker))
        copies = _hand_of(a, _SPELLCRAFT_SPELL_ID)
        self.assertEqual(len(copies), 2)           # 1 base + 1 extra
        self.assertTrue(all(c.has(GameTag.SPELLCRAFT) for c in copies))

    def test_no_portrait_control_single_copy(self):
        g = make_game(seed=3312)
        a, _b = g.heroes
        shaker = put(g, a, ZESTY)
        s = add_spellcraft_to_hand(g, a)
        self.assertTrue(g.play_spell(a, s, target=shaker))
        self.assertEqual(len(_hand_of(a, _SPELLCRAFT_SPELL_ID)), 1)

    def test_golden_shaker_three_copies(self):
        g = make_game(seed=3313)
        a, _b = g.heroes
        g.add_giver_bonus(a, ZESTY, copies=1)
        shaker = put(g, a, ZESTY, golden=True)
        s = add_spellcraft_to_hand(g, a)
        self.assertTrue(g.play_spell(a, s, target=shaker))
        self.assertEqual(len(_hand_of(a, _SPELLCRAFT_SPELL_ID)), 3)

    def test_opponent_shaker_unaffected(self):
        g = make_game(seed=3314)
        a, b = g.heroes
        bind(g, a, SHAKER)                          # extra 只写 A
        shaker = put(g, b, ZESTY)
        s = add_spellcraft_to_hand(g, b)
        self.assertTrue(g.play_spell(g.heroes[1], s, target=shaker))
        self.assertEqual(len(_hand_of(b, _SPELLCRAFT_SPELL_ID)), 1)

    def test_once_per_turn_still_enforced(self):
        g = make_game(seed=3315)
        a, _b = g.heroes
        bind(g, a, SHAKER)
        granted = _hand_of(a, ZESTY)
        self.assertTrue(g.play_minion(a, granted[0]))
        shaker = a.board[-1]
        s1 = add_spellcraft_to_hand(g, a)
        s2 = add_spellcraft_to_hand(g, a)
        self.assertTrue(g.play_spell(a, s1, target=shaker))
        self.assertTrue(g.play_spell(a, s2, target=shaker))
        # 同回合第二次不复制 → 仍只 2 份（extra 只随首次触发）
        self.assertEqual(len(_hand_of(a, _SPELLCRAFT_SPELL_ID)), 2)


class TestRegistryAndLedger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链。"""

    def test_registered_ids(self):
        for tid, cls in ((REDEEMER, B33.RedeemerPortraitScript),
                         (SHAKER, B33.ShakerPortraitScript)):
            self.assertIs(REGISTRY.get(tid), cls, tid)

    def test_registry_classes_are_from_this_batch(self):
        for tid in (REDEEMER, SHAKER):
            self.assertEqual(REGISTRY.get(tid).__module__,
                             "hsrl2.scripts.batches.batch_trinkets33", tid)

    def test_deferred_not_registered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid), tid)

    def test_deferred_ids_exist_as_trinkets(self):
        for tid in DEFERRED_IDS:
            d = get_db().get(tid)
            self.assertIsNotNone(d, tid)
            self.assertEqual(d.card_type, CardType.BACON_TRINKET, tid)

    def test_related_card_data_chain(self):
        db = get_db()
        for tid, rel in ((REDEEMER, NALAA), (SHAKER, ZESTY)):
            evo = db.get(tid).evolution_card_id
            self.assertIsNotNone(evo, tid)
            self.assertEqual(db.by_dbf(evo).id, rel, tid)

    def test_scripts_declare_only_on_bind(self):
        """两张卡的脚本只挂 on_bind（接线审计 W1 白名单）。"""
        hooks = ("battlecry", "deathrattle", "start_of_combat", "avenge",
                 "rally", "start_of_turn", "end_of_turn", "on_sell",
                 "on_summon", "on_play", "activate", "atk", "health",
                 "hero_power")
        for cls in (B33.RedeemerPortraitScript, B33.ShakerPortraitScript):
            self.assertTrue(callable(getattr(cls, "on_bind", None)))
            self.assertEqual([h for h in hooks if h in vars(cls)], [])


if __name__ == "__main__":
    unittest.main()
