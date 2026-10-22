"""例外 4（persist Buff）重复应用回归测试。

第四十三轮对抗验证发现: 战斗前已获得的 persistent 附魔在 `run_combat`
恢复后又被"例外 4"重放一次 → 每场战斗属性无限增长（实测 4/5 → 5/6 →
6/7…）。本文件用**真实卡路**（饰品 + 招募期授予）钉死"只保留一次、连续
多场不累积"。

Natural language: 永久授予只应发生一次。
Formal spec: 战斗前快照已含的 persist 附魔在恢复时已回来, 不得 add_buff
  重放; 连续 N 场战斗后属性不变。
Test: 本文件。
"""
from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 101) -> Game:
    g = Game([Hero("A", "A"), Hero("B", "B")], get_db(), seed=seed)
    g.start_game()
    return g


class TestPersistNoDoubleApply(unittest.TestCase):
    def test_ribbon_persist_survives_once_across_combats(self):
        g = make_game(101)
        a, b = g.heroes
        g.grant_trinket(a, "BG35_MagicItem_923")
        m = g.create_minion("BG23_004", controller=a)
        g.summon(a, m)                              # 2/3 Naga
        sp = g.create_spell("BG28_168", controller=a)
        a.hand.append(sp)
        sp.zone = Zone.HAND
        g.play_spell(a, sp)                         # 招募期授予 persist 附魔
        pre = (m.atk, m.max_health)
        for i in range(2):
            g.summon(b, Minion(f"BIG{i}", f"BIG{i}", atk=10, health=500))
            g.run_combat(a, b)
            self.assertEqual(
                (m.atk, m.max_health), pre,
                f"第 {i + 1} 场战斗后 persist 附魔被重复应用")

    def test_cyclist_recruit_deathrattle_persist_survives_once(self):
        g = make_game(102)
        a, b = g.heroes
        g.grant_trinket(a, "BG36_MagicItem_362")
        cyc = g.create_minion("BG31_925", controller=a)
        g.summon(a, cyc)
        naga = g.create_minion("BG23_004", controller=a)
        g.summon(a, naga)
        cyc.set(GameTag.HEALTH, 0)
        g.check_deaths()                            # 招募期亡语 → persist 附魔
        pre = (naga.atk, naga.max_health)
        g.summon(b, Minion("BIG2", "BIG2", atk=10, health=500))
        g.run_combat(a, b)
        self.assertEqual((naga.atk, naga.max_health), pre,
                         "招募期 persist 附魔被重复应用")


if __name__ == "__main__":
    unittest.main()
