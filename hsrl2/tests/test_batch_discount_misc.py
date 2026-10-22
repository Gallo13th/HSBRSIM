"""批次 discount_misc 行为层测试（折扣/售价覆写族 3 张，RULES §7.4.5）。

全部真实路径: 真实奖励绑定（complete_quest）/ 真实饰品授予
（grant_trinket）/ 真实 `Game(anomaly=)` + start_game / 真实
`buy_from_tavern`（含失败购买）/ `sell_minion` / `upgrade_tavern` /
`refresh_tavern` / `_begin_recruit_for`。

期望值来自 CardDef.num(0/1)、文本字面量或基线对照; 每条负面断言同测试内
带正对照; owner/全桌语义分别用两英雄验证。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

REWARD = "BG28_Reward_500"
TRINKET = "BG32_MagicItem_935"
ANOMALY = "BG27_Anomaly_721"
SPELL = "BG28_168"          # Shiny Ring（池法术）
MINION = "BG25_001"         # Risen Rider


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 500, anomaly: str | None = None) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed, anomaly=anomaly)
    g.start_game()
    return g


def tavern_spell(game: Game, hero: Hero):
    s = game.create_spell(SPELL, controller=hero)
    s.zone = Zone.TAVERN
    hero.tavern = [s]
    return s


class TestBeyondTheMirage(unittest.TestCase):
    """BG28_Reward_500 — 酒馆法术持久 -1 费。"""

    def _bind(self, game: Game, hero: Hero) -> None:
        hero._quest_reward_id = REWARD
        game.complete_quest(hero)

    def test_persistent_discount_each_buy(self):
        g = make_game(seed=501)
        a, b = g.heroes
        a.gold = 20
        base = get_db().get(SPELL).cost
        self._bind(g, a)
        for i in range(2):                       # 持久: 连续两张都便宜
            s = tavern_spell(g, a)
            self.assertTrue(g.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 20 - 2 * max(0, base - 1))
        # 对手不受影响
        s = tavern_spell(g, b)
        self.assertTrue(g.buy_from_tavern(g.heroes[1], s))
        self.assertEqual(b.get(GameTag.TAVERN_SPELL_COST_MOD, 0), 0)

    def test_minion_buy_unaffected(self):
        g = make_game(seed=502)
        a = g.heroes[0]
        a.gold = 20
        self._bind(g, a)
        m = g.create_minion(MINION, controller=a)
        m.zone = Zone.TAVERN
        a.tavern = [m]
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertEqual(a.gold, 20 - get_db().get(MINION).cost)


class TestLubberSticker(unittest.TestCase):
    """BG32_MagicItem_935 — 每次刷新多 1 张法术; 每回合首张 -1 费。"""

    def _buy(self, g: Game, a: Hero) -> None:
        a.gold = 50
        a.set(GameTag.TAVERN_TIER, 6)
        assert g.grant_trinket(a, TRINKET) is not None

    def test_extra_spell_slot_hero_scoped(self):
        g = make_game(seed=503)
        a, b = g.heroes
        g.refresh_tavern(a, free=True)
        base = len([e for e in a.tavern if not isinstance(e, Minion)])
        self._buy(g, a)
        self.assertEqual(a._tavern_spell_extra, 1)
        g.refresh_tavern(a, free=True)
        self.assertEqual(len([e for e in a.tavern
                              if not isinstance(e, Minion)]), base + 1)
        g.refresh_tavern(b, free=True)          # 对手不受影响（正对照）
        self.assertEqual(len([e for e in b.tavern
                              if not isinstance(e, Minion)]), base)

    def test_first_spell_discount_each_turn(self):
        g = make_game(seed=504)
        a = g.heroes[0]
        self._buy(g, a)
        base = get_db().get(SPELL).cost
        a.gold = 20
        s = tavern_spell(g, a)
        self.assertTrue(g.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 20 - max(0, base - 1))     # 首张 -1
        s2 = tavern_spell(g, a)
        self.assertTrue(g.buy_from_tavern(a, s2))
        self.assertEqual(a.gold, 20 - max(0, base - 1) - base)  # 原价
        # 下一回合重置（正对照）
        a.gold = 20
        g.turn = 2
        g._begin_recruit_for(a)
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 1)

    def test_existing_discount_not_overwritten(self):
        """每回合首张 -1 是**叠加**语义: 不得抹掉同 tag 上已有的折扣
        （2026-09-02 对抗审查 MINOR: 两次 Ominous Seer 得 3 → 本效果
        start_of_turn 覆盖式 set 1 会静默吞掉 2 金）。"""
        g = make_game(seed=507)
        a = g.heroes[0]
        self._buy(g, a)
        a.set(GameTag.NEXT_SPELL_COST_REDUCTION, 2)     # 既有来源
        g.turn = 2
        g._begin_recruit_for(a)
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 2)

    def test_minion_buy_does_not_consume_discount(self):
        g = make_game(seed=505)
        a = g.heroes[0]
        self._buy(g, a)
        m = g.create_minion(MINION, controller=a)
        m.zone = Zone.TAVERN
        a.tavern = [m]
        a.gold = 20
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 1)


class TestUncompensatedUpset(unittest.TestCase):
    """BG27_Anomaly_721 — 开局 1 金; 随从 1 费卖 0 金; 升级 -2。"""

    def test_start_gold_minion_cost_and_sell(self):
        g = make_game(seed=506, anomaly=ANOMALY)
        a, b = g.heroes
        self.assertEqual(a.gold, 1)                     # 开局金币覆写
        self.assertEqual(b.gold, 1)                     # 全局异变
        m = g.create_minion(MINION, controller=a)
        m.zone = Zone.TAVERN
        a.tavern = [m]
        self.assertTrue(g.buy_from_tavern(a, m))        # 1 费
        self.assertEqual(a.gold, 0)
        g.summon(a, m)
        self.assertTrue(g.sell_minion(a, m))            # 卖 0 金
        self.assertEqual(a.gold, 0)

    def test_upgrade_cost_reduced(self):
        g = make_game(seed=507, anomaly=ANOMALY)
        a = g.heroes[0]
        a.gold = 20
        base = make_game(seed=507).heroes[0].upgrade_cost
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.gold, 20 - max(0, base - 2))

    def test_standard_game_control(self):
        """正对照: 标准局无这些覆写。"""
        g = make_game(seed=508)
        a = g.heroes[0]
        self.assertNotEqual(a.gold, 1)
        self.assertEqual(a.get(GameTag.TAVERN_MINION_COST_OVERRIDE, 0), 0)
        self.assertNotIn(GameTag.SELL_VALUE_OVERRIDE, a.tags)


class TestRegistry(unittest.TestCase):
    IMPLEMENTED = (REWARD, TRINKET, ANOMALY)

    def test_all_registered(self):
        for cid in self.IMPLEMENTED:
            self.assertIn(cid, REGISTRY, cid)


if __name__ == "__main__":
    unittest.main()
