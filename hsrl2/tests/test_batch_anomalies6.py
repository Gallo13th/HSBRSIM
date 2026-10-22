"""批次 anomalies6 语义测试（Crystal Ball 族; 作业单 2026-09-11）。

覆盖 2 张注册异变 + 2 张第二技能槽技能（真实引擎路径:
`Game(..., anomaly=id)` + `start_game()`，以及真实的
`trinket_bought` 商店购买事件 + `grant_trinket`）:

  - BG35_Anomaly_007  Lesser Fortune  —— 第二槽 = 'Lesser Crystal Ball'
  - BG35_Anomaly_008  Greater Fortune —— 第二槽 = 'Greater Crystal Ball'
  - BG35_Anomaly_007t Lesser Crystal Ball（Hero Power，passive）——
    买 Lesser 饰品时技能槽变成该饰品的**副本**（本体 + 副本两份）
  - BG35_Anomaly_008t Greater Crystal Ball —— 同上，Greater 档

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都配**正对照**;
owner 隔离用 2 英雄; 技能 id 经 `evolution_card_id` 数据链解析
（不硬编码业务 id）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import TRINKET_BOUGHT
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_anomalies6 as B6
from hsrl2.tags import CardType

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

ANOMALY_LESSER = "BG35_Anomaly_007"
ANOMALY_GREATER = "BG35_Anomaly_008"
POWER_LESSER = "BG35_Anomaly_007t"
POWER_GREATER = "BG35_Anomaly_008t"

HERO_A = "BG20_HERO_103"        # 主技能 Bloodbound（已注册）

REGISTERED_IDS = (ANOMALY_LESSER, ANOMALY_GREATER, POWER_LESSER, POWER_GREATER)
DEFERRED_IDS: tuple = ()

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def game_with(anomaly: str | None = None, seed: int = 61,
              names=("A", "B")) -> Game:
    heroes = [Hero(HERO_A, n) for n in names]
    g = Game(heroes, get_db(), seed=seed, anomaly=anomaly)
    g.start_game()
    return g


def offer_pool(kind: str) -> list:
    school = 11 if kind == "lesser" else 12
    return [d for d in get_db().trinket_offer_pool()
            if d.spell_school == school]


def buy(game: Game, hero, card_id: str, kind: str):
    """走真实商店事件契约: 先记账（`_offer_trinkets.resolve` 顺序）再广播。

    返回授予实体（与商店 resolve 的实体语义一致）。
    """
    e = game.grant_trinket(hero, card_id, source="test_buy")
    assert e is not None
    game.events.fire(game, TRINKET_BOUGHT, hero=hero, trinket=e, kind=kind)
    return e


def copies_of(hero, card_id: str) -> int:
    return sum(1 for t in hero.trinkets if t.card_id == card_id)


# ══════════════ 结构性（注册表 / 数据一致性） ══════════════

class TestRegistry(unittest.TestCase):
    """注册面 + 数据链/文本一致性（结构性，与钩子无关）。"""

    def test_all_ids_registered(self):
        for cid in REGISTERED_IDS:
            self.assertIn(cid, REGISTRY, cid)
            self.assertIsNotNone(get_db().get(cid), cid)

    def test_class_names(self):
        expected = {
            ANOMALY_LESSER: "LesserFortuneAnomaly",
            ANOMALY_GREATER: "GreaterFortuneAnomaly",
            POWER_LESSER: "LesserCrystalBallPower",
            POWER_GREATER: "GreaterCrystalBallPower",
        }
        for cid, name in expected.items():
            self.assertIs(REGISTRY[cid], getattr(B6, name), cid)

    def test_deferred_ids_not_registered(self):
        for cid in DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_data_chain_and_tier_params(self):
        """`evolution_card_id` 数据链 + `num(0)` = 触发档位（6/9）。"""
        chain = {
            ANOMALY_LESSER: (POWER_LESSER, 6),
            ANOMALY_GREATER: (POWER_GREATER, 9),
        }
        for aid, (pid, tier) in chain.items():
            d = get_db().get(aid)
            self.assertEqual(d.card_type, CardType.BACON_ANOMALY)
            power = get_db().by_dbf(d.evolution_card_id)
            self.assertIsNotNone(power, aid)
            self.assertEqual(power.id, pid)
            self.assertEqual(power.card_type, CardType.HERO_POWER)
            self.assertEqual(power.cost, 0)
            self.assertEqual(power.num(0), tier)
        # 两张技能均为被动（文本无主动使用语义）
        self.assertTrue(B6.LesserCrystalBallPower.passive)
        self.assertTrue(B6.GreaterCrystalBallPower.passive)


# ══════════════ BG35_Anomaly_007 / _008 授予第二技能 ══════════════

class TestFortuneAnomaly(unittest.TestCase):

    def test_lesser_fortune_grants_second_power(self):
        d = get_db().get(ANOMALY_LESSER)
        power = get_db().by_dbf(d.evolution_card_id)
        g = game_with(ANOMALY_LESSER, seed=61)
        for h in g.heroes:
            self.assertEqual(h._second_power_id, power.id)
            self.assertIn(power.id, g.hero_power_ids(h))
            self.assertIsNotNone(g.hero_power_def_for(h, power.id))
        # 对照局: 无异常 → 无第二槽（负面对照）
        g2 = game_with(None, seed=61)
        for h in g2.heroes:
            self.assertIsNone(h._second_power_id)
            self.assertEqual(len(g2.hero_power_ids(h)), 1)

    def test_greater_fortune_grants_greater_power(self):
        d = get_db().get(ANOMALY_GREATER)
        power = get_db().by_dbf(d.evolution_card_id)
        self.assertEqual(power.id, POWER_GREATER)
        g = game_with(ANOMALY_GREATER, seed=61)
        for h in g.heroes:
            self.assertEqual(h._second_power_id, POWER_GREATER)

    def test_no_vacuous_slot_when_power_unregistered(self):
        """技能脚本未注册 → 不授予空转槽位（载荷未就绪时整卡落空）。"""
        saved = REGISTRY.pop(POWER_LESSER)
        try:
            g = game_with(ANOMALY_LESSER, seed=61)
            for h in g.heroes:
                self.assertIsNone(h._second_power_id)     # 不占空转槽
            # 正对照: 还原注册后同 seed 授予成功
        finally:
            REGISTRY[POWER_LESSER] = saved
        g2 = game_with(ANOMALY_LESSER, seed=61)
        for h in g2.heroes:
            self.assertEqual(h._second_power_id, POWER_LESSER)

    def test_existing_second_slot_not_overwritten(self):
        """第二槽已被占用 → 该英雄跳过（单槽，RULES §9.5）。"""
        g = game_with(None, seed=61)
        a, b = g.heroes
        game_with_power = g
        g.set_second_hero_power(a, POWER_GREATER)
        # 手动跑异变 on_bind（模拟异常开局）
        game_with_power.anomaly = ANOMALY_LESSER
        B6.LesserFortuneAnomaly.on_bind(game_with_power)
        self.assertEqual(a._second_power_id, POWER_GREATER)   # 保持原槽
        self.assertEqual(b._second_power_id, POWER_LESSER)    # 空槽被授予


# ══════════════ BG35_Anomaly_007t / _008t 变形为饰品副本 ══════════════

class TestCrystalBallTransform(unittest.TestCase):

    def test_lesser_ball_transforms_on_lesser_buy(self):
        g = game_with(ANOMALY_LESSER, seed=62)
        a, b = g.heroes
        target = offer_pool("lesser")[0].id
        before_gold = a.gold
        buy(g, a, target, "lesser")
        # 槽位标记 = 饰品 id（不再是技能）
        self.assertEqual(a._second_power_id, target)
        self.assertNotIn(POWER_LESSER, g.hero_power_ids(a))
        # 本体 + 副本两份（"hold body + copy"）
        self.assertEqual(copies_of(a, target), 2)
        # 饰品 id 不作为技能可用（不误扣金币）
        self.assertFalse(g.use_hero_power(a, power_id=target))
        self.assertEqual(a.gold, before_gold)
        # owner 隔离: 对手未购买 → 仍是技能槽
        self.assertEqual(b._second_power_id, POWER_LESSER)

    def test_greater_ball_ignores_lesser_and_transforms_on_greater(self):
        g = game_with(ANOMALY_GREATER, seed=63)
        a = g.heroes[0]
        lesser = offer_pool("lesser")[0].id
        buy(g, a, lesser, "lesser")
        # 负面对照: 档位不符 → 不变形，只持有一份
        self.assertEqual(a._second_power_id, POWER_GREATER)
        self.assertEqual(copies_of(a, lesser), 1)
        self.assertIn(POWER_GREATER, g.hero_power_ids(a))
        # 正对照: Greater 档触发变形
        greater = offer_pool("greater")[0].id
        buy(g, a, greater, "greater")
        self.assertEqual(a._second_power_id, greater)
        self.assertEqual(copies_of(a, greater), 2)
        self.assertNotIn(POWER_GREATER, g.hero_power_ids(a))

    def test_lesser_ball_ignores_greater_buy(self):
        g = game_with(ANOMALY_LESSER, seed=64)
        a = g.heroes[0]
        greater = offer_pool("greater")[0].id
        buy(g, a, greater, "greater")
        self.assertEqual(a._second_power_id, POWER_LESSER)   # 未变形
        self.assertEqual(copies_of(a, greater), 1)

    def test_no_second_transform_after_slot_changed(self):
        g = game_with(ANOMALY_LESSER, seed=65)
        a = g.heroes[0]
        first = offer_pool("lesser")[0].id
        second = offer_pool("lesser")[1].id
        buy(g, a, first, "lesser")
        self.assertEqual(a._second_power_id, first)
        buy(g, a, second, "lesser")
        # 槽位已不是本技能 → 不再变形；第二张只持有一份
        self.assertEqual(a._second_power_id, first)
        self.assertEqual(copies_of(a, second), 1)
        self.assertEqual(copies_of(a, first), 2)

    def test_real_shop_purchase_path_transforms(self):
        """集成: 真实 `_offer_trinkets` 商店 resolve（扣金币 + 真实事件）。"""
        g = game_with(ANOMALY_LESSER, seed=66)
        a = g.heroes[0]
        a.gold = 99
        g._offer_trinkets(a, "lesser")
        ch = next(c for c in g.pending_choices
                  if c.kind == "trinket_offer" and c.owner is a)
        g.pending_choices.remove(ch)
        choice = ch.options[0]
        self.assertIsNotNone(choice)
        ch.choose(0)
        self.assertEqual(a._second_power_id, choice.id)
        self.assertEqual(copies_of(a, choice.id), 2)

    def test_passive_power_not_clickable(self):
        g = game_with(ANOMALY_LESSER, seed=67)
        a = g.heroes[0]
        a.gold = 20
        self.assertFalse(g.use_hero_power(a, power_id=POWER_LESSER))
        self.assertEqual(a.gold, 20)                        # 未扣费
        # 同局主技能仍可用（第二槽不影响主技能）; 正对照: 真正可用的技能
        # `use_hero_power` 必须返回 True（否则上面的 False 只是 API 恒假）
        self.assertIsNotNone(g.hero_power_def(a))
        self.assertTrue(g.use_hero_power(a))


if __name__ == "__main__":
    unittest.main()
