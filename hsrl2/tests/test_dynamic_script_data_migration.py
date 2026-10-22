"""动态属性脚本家族迁移测试 — 官方 `TAG_SCRIPT_DATA_NUM_3` 注入通道。

覆盖 `batch_counters.py` 7 族 + `batch_unlock_final.py` EternalPortrait:
  AbyssalBruiser / AncestralAutomaton / FallingSkyGolem /
  FlourishingFrostling / MaritimeExtortionist / RotHideGnoll(+金) /
  EternalKnight（迁移回归） / EternalPortrait（家族光环计数）。

契约（与 F-03 Eternal Knight 一致）:
  - 无注入: 旧"印面值 × 引擎计数"行为逐位不变；
  - 有注入: 计数 = 引擎计数/簿记 + 注入基线（`script_data_or_card(3)`）；
  - 金色: 各自 CardDef 数值；
  - owner 隔离: 每个实体只读自己的注入通道/本方计数。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 1000) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def put(game: Game, hero: Hero, card_id: str,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def base_atk(m: Minion) -> int:
    return m.get(GameTag.BASE_ATK, 0)


def base_health(m: Minion) -> int:
    return m.get(GameTag.BASE_HEALTH, 0)


def dnums(m: Minion) -> tuple:
    d = m.game.db.get(m.card_id)
    return (d.num(0), d.num(1))


def inject(m: Minion, value: int) -> None:
    m.set_script_data(3, value)


class TestAbyssalBruiser(unittest.TestCase):
    """BG35_921 — 每个已施放酒馆法术 +2/+1。"""

    def _run(self, golden: bool, casts: int, injected: int | None):
        g = make_game()
        a, b = g.heroes
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, casts)
        m = put(g, a, "BG35_921", golden=golden)
        if injected is not None:
            inject(m, injected)
        n0, n1 = dnums(m)
        total = casts + (injected or 0)
        return m, (base_atk(m) + total * n0,
                   base_health(m) + total * n1)

    def test_no_injection_matches_old(self):
        m, expected = self._run(golden=False, casts=2, injected=None)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_injection_adds_baseline(self):
        m, expected = self._run(golden=False, casts=2, injected=3)
        self.assertEqual((m.atk, m.max_health), expected)
        self.assertEqual(m.script_data_or_card(3), 3)

    def test_golden_values(self):
        m, expected = self._run(golden=True, casts=1, injected=2)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_owner_isolation(self):
        g = make_game()
        a, b = g.heroes
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 2)
        b.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        mine = put(g, a, "BG35_921")
        enemy = put(g, b, "BG35_921")
        inject(mine, 5)
        self.assertEqual((enemy.atk, enemy.max_health),
                         (base_atk(enemy), base_health(enemy)))


class TestFallingSkyGolem(unittest.TestCase):
    """BG35_342 — 每个已触发亡语 +4/+2。"""

    def _run(self, golden: bool, count: int, injected: int | None):
        g = make_game()
        a, _b = g.heroes
        a.set(GameTag.COUNTER_DEATHRATTLES, count)
        m = put(g, a, "BG35_342", golden=golden)
        if injected is not None:
            inject(m, injected)
        n0, n1 = dnums(m)
        total = count + (injected or 0)
        return m, (base_atk(m) + total * n0,
                   base_health(m) + total * n1)

    def test_no_injection_matches_old(self):
        m, expected = self._run(False, 2, None)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_injection_adds_baseline(self):
        m, expected = self._run(False, 1, 3)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_golden_values(self):
        m, expected = self._run(True, 1, 1)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_owner_isolation(self):
        g = make_game()
        a, b = g.heroes
        a.set(GameTag.COUNTER_DEATHRATTLES, 2)
        mine = put(g, a, "BG35_342")
        enemy = put(g, b, "BG35_342")
        inject(mine, 4)
        self.assertEqual((enemy.atk, enemy.max_health),
                         (base_atk(enemy), base_health(enemy)))


class TestFlourishingFrostling(unittest.TestCase):
    """BG26_537 — 每个已打出元素 +2/+1。"""

    def _run(self, golden: bool, count: int, injected: int | None):
        g = make_game()
        a, _b = g.heroes
        a.set(GameTag.COUNTER_ELEMENTALS_PLAYED, count)
        m = put(g, a, "BG26_537", golden=golden)
        if injected is not None:
            inject(m, injected)
        n0, n1 = dnums(m)
        total = count + (injected or 0)
        return m, (base_atk(m) + total * n0,
                   base_health(m) + total * n1)

    def test_no_injection_matches_old(self):
        m, expected = self._run(False, 2, None)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_injection_adds_baseline(self):
        m, expected = self._run(False, 1, 2)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_golden_values(self):
        m, expected = self._run(True, 1, 2)
        self.assertEqual((m.atk, m.max_health), expected)


class TestMaritimeExtortionist(unittest.TestCase):
    """BG36_524 — 每个已打出金色随从 +7/+7。"""

    def _run(self, golden: bool, count: int, injected: int | None):
        g = make_game()
        a, _b = g.heroes
        a.set(GameTag.GOLDEN_MINIONS_PLAYED, count)
        m = put(g, a, "BG36_524", golden=golden)
        if injected is not None:
            inject(m, injected)
        n0, n1 = dnums(m)
        total = count + (injected or 0)
        return m, (base_atk(m) + total * n0,
                   base_health(m) + total * n1)

    def test_no_injection_matches_old(self):
        m, expected = self._run(False, 1, None)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_injection_adds_baseline(self):
        m, expected = self._run(False, 1, 2)
        self.assertEqual((m.atk, m.max_health), expected)

    def test_golden_values(self):
        m, expected = self._run(True, 1, 1)
        self.assertEqual((m.atk, m.max_health), expected)


class TestAncestralAutomaton(unittest.TestCase):
    """BG_TTN_401 — 每个其他已召唤 Automaton +3/+2（金色 +6/+4）。"""

    def test_no_injection_first_copy_no_bonus(self):
        g = make_game()
        a, _b = g.heroes
        m = put(g, a, "BG_TTN_401")
        self.assertEqual((m.atk, m.max_health),
                         (base_atk(m), base_health(m)))

    def test_injection_adds_others(self):
        g = make_game()
        a, _b = g.heroes
        m = put(g, a, "BG_TTN_401")
        inject(m, 2)
        self.assertEqual((m.atk, m.max_health),
                         (base_atk(m) + 6, base_health(m) + 4))

    def test_golden_injection(self):
        g = make_game()
        a, _b = g.heroes
        m = put(g, a, "BG_TTN_401", golden=True)
        inject(m, 2)
        self.assertEqual((m.atk, m.max_health),
                         (base_atk(m) + 12, base_health(m) + 8))

    def test_owner_isolation(self):
        g = make_game()
        a, b = g.heroes
        mine = put(g, a, "BG_TTN_401")
        enemy = put(g, b, "BG_TTN_401")
        inject(mine, 3)
        self.assertEqual((enemy.atk, enemy.max_health),
                         (base_atk(enemy), base_health(enemy)))


class TestRotHideGnoll(unittest.TestCase):
    """BG25_013 — 本场每个友方死亡 +1 攻（金色 +2）。"""

    def _setup(self, golden: bool, deaths: int, injected: int | None):
        g = make_game()
        a, b = g.heroes
        g.in_combat = True
        g._active_combat = (a, b)
        m = put(g, a, "BG25_013", golden=golden)
        for i in range(deaths):
            dead = Minion(f"TEST_DEAD{i}", "D", atk=1, health=1)
            dead.game = g
            dead.controller = a
            g.combat_death_log.append(dead)
        if injected is not None:
            inject(m, injected)
        per = 2 if golden else 1
        total = deaths + (injected or 0)
        return m, base_atk(m) + total * per

    def test_no_injection_matches_old(self):
        m, expected = self._setup(False, 1, None)
        self.assertEqual(m.atk, expected)

    def test_injection_adds_baseline(self):
        m, expected = self._setup(False, 1, 2)
        self.assertEqual(m.atk, expected)

    def test_golden_values(self):
        m, expected = self._setup(True, 1, 1)
        self.assertEqual(m.atk, expected)

    def test_enemy_deaths_not_counted(self):
        g = make_game()
        a, b = g.heroes
        g.in_combat = True
        g._active_combat = (a, b)
        m = put(g, a, "BG25_013")
        dead = Minion("TEST_ENEMY", "E", atk=1, health=1)
        dead.game = g
        dead.controller = b
        g.combat_death_log.append(dead)
        inject(m, 1)
        self.assertEqual(m.atk, base_atk(m) + 1)


class TestEternalKnightMigration(unittest.TestCase):
    """BG25_008 — 迁移回归（原 F-03 行为不变）。"""

    def test_symbol_and_injection(self):
        g = make_game()
        a, _b = g.heroes
        m = put(g, a, "BG25_008")
        self.assertEqual((m.atk, m.max_health),
                         (base_atk(m), base_health(m)))
        inject(m, 2)
        self.assertEqual((m.atk, m.max_health),
                         (base_atk(m) + 8, base_health(m) + 4))


class TestEternalPortrait(unittest.TestCase):
    """BG36_MagicItem_216 — 友方 Undead 死亡累计光环（NUM_3 基线注入）。"""

    PORTRAIT = "BG36_MagicItem_216"
    ETERNAL = "BG25_008"
    UNDEAD = "BG25_013"

    def _bind(self, g, hero):
        from hsrl2.scripts import REGISTRY
        e = g.grant_trinket(hero, self.PORTRAIT)
        assert e is not None
        assert REGISTRY.get(self.PORTRAIT) is not None
        return e

    def test_no_injection_matches_old(self):
        g = make_game()
        a, _b = g.heroes
        self._bind(g, a)
        ek = put(g, a, self.ETERNAL)
        base = (ek.atk, ek.max_health)
        u = put(g, a, self.UNDEAD)
        u.health = 0
        g.check_deaths()
        self.assertEqual((ek.atk, ek.max_health),
                         (base[0] + 4, base[1] + 2))

    def test_injection_adds_baseline(self):
        g = make_game()
        a, _b = g.heroes
        portrait = self._bind(g, a)
        ek = put(g, a, self.ETERNAL)
        base = (ek.atk, ek.max_health)
        inject(portrait, 2)
        u = put(g, a, self.UNDEAD)
        u.health = 0
        g.check_deaths()
        # k = 1 observed + 2 injected → +12/+6
        self.assertEqual((ek.atk, ek.max_health),
                         (base[0] + 12, base[1] + 6))

    def test_owner_isolation(self):
        g = make_game()
        a, b = g.heroes
        self._bind(g, a)
        mine = put(g, a, self.ETERNAL)
        enemy = put(g, b, self.ETERNAL)
        enemy_base = (enemy.atk, enemy.max_health)
        u = put(g, b, self.UNDEAD)      # 敌方 Undead 死亡不计
        u.health = 0
        g.check_deaths()
        self.assertEqual((enemy.atk, enemy.max_health), enemy_base)
        self.assertEqual((mine.atk, mine.max_health),
                         (base_atk(mine), base_health(mine)))


if __name__ == "__main__":
    unittest.main()
