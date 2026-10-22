"""批次 trinkets34 行为层测试（1 张注册饰品 = 1 CORRECT / 0 DEFERRED）。

覆盖（真实路径）:
  - `BG32_MagicItem_274` Bristlebach Portrait — 真实 `grant_trinket` →
    `on_bind` 经 `evolution_card_id` 数据链授予 `BG26_157` Bristlebach
    + 写入 `hero.family_flags`; 战斗内 Avenge 达标后目标集合由"你的野猪人"
    放宽为**全体存活友方随从**（非野猪人同样吃 2 颗血宝石）; 无饰品对照
    仍只打野猪人; 金色本体 4 颗且按基础卡 id 归一吃开关; 饰品被移除后
    开关失效; 对手棋盘不受影响。

结构性守卫（注册表 / 数据链 / DEFERRED 台账 / 只挂 on_bind）标
`@engine-only`。引擎原语契约（归一/生效期/fail-loud）见
`test_engine_primitives.py::TestFamilyFlagChannel`。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_payload_minions as BP
from hsrl2.scripts.batches import batch_trinkets34 as B34
from hsrl2.tags import CardType, GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

PORTRAIT = B34.BRISTLEBACH_PORTRAIT
FLAG = BP.FLAG_SCOPE_ALL_FRIENDLY
BRISTLEBACH = BP.BRISTLEBACH
BRISTLEBACH_G = BP.BRISTLEBACH_G

# 同族 Portrait 台账（仍未注册——见 batch_trinkets33 / batch_trinkets14;
# 803 Kaboom Bot Portrait 已由 batch_trinkets39 注册迁出，2026-09-18）
# 868 Rewinder / 987 Balladist / 869 Felblood Portrait 已由 batch_trinkets31
# 注册（2026-09-19——owner 权威序: wiki 页无 Notes → 卡面天然语言
# "also give X" 增量 = 同句既有量）→ 移出本台账，DEFERRED 清零。
DEFERRED_IDS = ()

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 3401) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid, source="test")
    assert e is not None, f"{tid} 未授予"
    return e


def make_minion(name: str, atk: int, health: int,
                race: Race = Race.NONE) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)


def summon_plain(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def put(game: Game, hero: Hero, card_id: str, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def hit_kill(game: Game, victim: Minion, in_combat: bool) -> None:
    """Hit 致死 → check_deaths（Avenge 计数需战斗上下文）。"""
    from hsrl2.actions import Hit
    prev = game.in_combat
    game.in_combat = in_combat
    try:
        game.run_actions(Hit(victim, victim.health))
    finally:
        game.in_combat = prev


def trigger_avenge(game: Game, hero: Hero, deaths: int = 2) -> None:
    """战斗内制造 N 次友方死亡（达标即触发 Avenge）。"""
    for i in range(deaths):
        hit_kill(game, summon_plain(
            game, hero, make_minion(f"FODDER{i}", 1, 1)), in_combat=True)


def _hand_of(hero: Hero, card_id: str) -> list:
    return [c for c in hero.hand if c.card_id == card_id]


class TestBristlebachPortrait(unittest.TestCase):
    """BG32_MagicItem_274 — 授予 Bristlebach + 目标集合放宽为全体友方。"""

    def test_grants_bristlebach_and_flag(self):
        g = make_game(seed=3401)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        granted = _hand_of(a, BRISTLEBACH)
        self.assertEqual(len(granted), 1)          # 真实数据链授予
        self.assertFalse(granted[0].is_golden)     # "Get a Bristlebach" = 基础
        self.assertTrue(g.family_flag(a, BRISTLEBACH, FLAG))
        self.assertTrue(g.family_flag(a, BRISTLEBACH_G, FLAG))  # 金色归一
        self.assertFalse(g.family_flag(b, BRISTLEBACH, FLAG))   # owner 隔离

    def test_scope_all_friendly_when_portrait_active(self):
        """达标后：野猪人与非野猪人友方随从同样 +2 颗（含本体）。"""
        g = make_game(seed=3402)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        granted = _hand_of(a, BRISTLEBACH)
        self.assertTrue(g.play_minion(a, granted[0]))
        bristle = a.board[-1]
        quil = summon_plain(g, a, make_minion(
            "QUIL", 1, 1, race=Race.QUILBOAR))
        beast = summon_plain(g, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        enemy = summon_plain(g, b, make_minion(
            "EQUIL", 1, 1, race=Race.QUILBOAR))
        # 未达标不触发（负对照）
        hit_kill(g, summon_plain(g, a, make_minion("S0", 1, 1)),
                 in_combat=True)
        self.assertEqual(beast.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        # 达标 → 全体友方（含本体 / 非野猪人 / 无类型）
        trigger_avenge(g, a, deaths=1)
        for m in (bristle, quil, beast):
            self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON, 0), 2, m.name)
        self.assertEqual(beast.atk, 1 + 2)
        self.assertEqual(beast.max_health, 1 + 2)
        self.assertEqual(enemy.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_control_without_portrait_limits_to_quilboar(self):
        g = make_game(seed=3403)
        a, _b = g.heroes
        put(g, a, BRISTLEBACH)
        quil = summon_plain(g, a, make_minion(
            "QUIL", 1, 1, race=Race.QUILBOAR))
        beast = summon_plain(g, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        trigger_avenge(g, a)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 2)
        self.assertEqual(beast.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_golden_bristlebach_four_gems_scope_all(self):
        """金色本体吃开关（基础卡 id 归一），颗数仍取金色 CardDef = 4。"""
        g = make_game(seed=3404)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        put(g, a, BRISTLEBACH, golden=True)
        beast = summon_plain(g, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        trigger_avenge(g, a)
        self.assertEqual(beast.get(GameTag.GEMS_PLAYED_ON, 0), 4)
        self.assertEqual(beast.atk, 1 + 4)

    def test_opponent_board_unaffected(self):
        """A 持有饰品: B 的 Bristlebach 仍只打 B 的野猪人（owner 隔离）。"""
        g = make_game(seed=3405)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        put(g, b, BRISTLEBACH)
        b_quil = summon_plain(g, b, make_minion(
            "BQUIL", 1, 1, race=Race.QUILBOAR))
        b_beast = summon_plain(g, b, make_minion(
            "BBEAST", 1, 1, race=Race.BEAST))
        trigger_avenge(g, b)
        self.assertEqual(b_quil.get(GameTag.GEMS_PLAYED_ON, 0), 2)
        self.assertEqual(b_beast.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_flag_expires_when_trinket_removed(self):
        """`source` 离场（饰品被替换）→ 开关失效（RULES §7.4.16 生效期）。"""
        g = make_game(seed=3406)
        a, _b = g.heroes
        ent = bind(g, a, PORTRAIT)
        self.assertTrue(g.family_flag(a, BRISTLEBACH, FLAG))
        a.trinkets.remove(ent)
        self.assertFalse(g.family_flag(a, BRISTLEBACH, FLAG))
        put(g, a, BRISTLEBACH)
        beast = summon_plain(g, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        trigger_avenge(g, a)
        self.assertEqual(beast.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_recruit_phase_deaths_do_not_trigger(self):
        """开关只改目标集合，不改战斗上下文门槛（RULES §6.11）。"""
        g = make_game(seed=3407)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        put(g, a, BRISTLEBACH)
        beast = summon_plain(g, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        for i in range(2):
            hit_kill(g, summon_plain(
                g, a, make_minion(f"R{i}", 1, 1)), in_combat=False)
        self.assertEqual(beast.get(GameTag.GEMS_PLAYED_ON, 0), 0)


class TestRegistryAndLedger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链。"""

    def test_registered_ids(self):
        self.assertIs(REGISTRY.get(PORTRAIT), B34.BristlebachPortraitScript)

    def test_registry_class_is_from_this_batch(self):
        self.assertEqual(REGISTRY.get(PORTRAIT).__module__,
                         "hsrl2.scripts.batches.batch_trinkets34")

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
        evo = db.get(PORTRAIT).evolution_card_id
        self.assertIsNotNone(evo)
        self.assertEqual(db.by_dbf(evo).id, BRISTLEBACH)
        self.assertEqual(db.by_dbf(evo).card_type, CardType.MINION)

    def test_flag_constant_owned_by_payload(self):
        """开关名常量定义在载荷侧（唯一消费点），饰品侧导入同一常量。"""
        self.assertEqual(B34.FLAG_SCOPE_ALL_FRIENDLY,
                         BP.FLAG_SCOPE_ALL_FRIENDLY)
        self.assertEqual(FLAG, "bristlebach_scope_all_friendly")

    def test_script_declares_only_on_bind(self):
        """本卡脚本只挂 on_bind（接线审计 W1 白名单）。"""
        hooks = ("battlecry", "deathrattle", "start_of_combat", "avenge",
                 "rally", "start_of_turn", "end_of_turn", "on_sell",
                 "on_summon", "on_play", "activate", "atk", "health",
                 "hero_power")
        cls = B34.BristlebachPortraitScript
        self.assertTrue(callable(getattr(cls, "on_bind", None)))
        self.assertEqual([h for h in hooks if h in vars(cls)], [])

    def test_payload_consumes_flag(self):
        """载荷消费点存在: `avenge` 读 `game.family_flag`（非装饰性接线）。"""
        import inspect
        src = inspect.getsource(BP.BristlebachScript.avenge)
        self.assertIn("family_flag", src)
        self.assertIn("FLAG_SCOPE_ALL_FRIENDLY", src)


if __name__ == "__main__":
    unittest.main()
