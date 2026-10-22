"""B 类动态状态迁移测试 — 官方 `ScriptDataNum` 注入（非 NUM_3 通用计数）。

覆盖 7 张卡的"进度/计时/标记"迁移（F-11）：
  Patient Scout(NUM_1=tier) / Gluttonous Trogg(NUM_1=购买进度) /
  Sky Admiral Rogers(NUM_1=Gold left) / Upbeat Frontdrake/Duo(NUM_1=turns left) /
  Zesty Shaker(NUM_1=once-per-turn used) / Scarlet Survivor(NUM_2=Done).

契约：无注入时旧行为逐位不变；注入值仅作回放窗口前基线。
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

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None
_SPELLCRAFT_SPELL_ID = "BG23_000t"


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 700) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    return g


def put(game: Game, hero: Hero, card_id: str, *, golden: bool = False,
        inject: dict | None = None) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    for num, value in (inject or {}).items():
        m.set_script_data(num, value)
    assert game.summon(hero, m)
    return m


def spellcraft_to_hand(game: Game, hero: Hero):
    s = game.create_spell(_SPELLCRAFT_SPELL_ID, controller=hero)
    s.scripts = REGISTRY.get(_SPELLCRAFT_SPELL_ID)
    s.set(GameTag.SPELLCRAFT, True)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def spellcraft_copies(hero: Hero) -> list:
    return [c for c in hero.hand if c.card_id == _SPELLCRAFT_SPELL_ID]


class TestPatientScoutTier(unittest.TestCase):
    """BG24_715 — NUM_1 = 当前 Discover tier。"""

    def test_injected_tier_overrides_turn_formula(self):
        g = make_game(seed=701)
        a = g.heroes[0]
        scout = put(g, a, "BG24_715", inject={1: 4})
        g.turn = 1                    # 旧公式会得到 Tier 1
        g.sell_minion(a, scout)
        choice = g.pending_choices[0]
        for opt in choice.options:
            self.assertEqual(get_db().get(opt).tech_level, 4)

    def test_no_injection_keeps_turn_formula(self):
        g = make_game(seed=702)
        a = g.heroes[0]
        scout = put(g, a, "BG24_715")
        g.turn = 3
        g.sell_minion(a, scout)
        for opt in g.pending_choices[0].options:
            self.assertEqual(get_db().get(opt).tech_level, 3)


class TestGluttonousTroggProgress(unittest.TestCase):
    """BG35_801 — NUM_1 = 当前购买进度（1..4）。"""

    def test_injected_progress_triggers_on_next_buy(self):
        g = make_game(seed=703)
        a = g.heroes[0]
        m = put(g, a, "BG35_801", inject={1: 3})
        dummy = Minion("TEST_BUY", "Buy", atk=1, health=1)
        dummy.game = g
        dummy.controller = a
        g.events.fire(g, "minion_bought", minion=dummy)
        d = get_db().get("BG35_801")
        self.assertEqual(m.atk, d.atk + d.num(1))
        self.assertEqual(m.max_health, d.health + d.num(2))

    def test_injected_done_does_not_rebuff(self):
        g = make_game(seed=704)
        a = g.heroes[0]
        m = put(g, a, "BG35_801", inject={1: 4})
        base = (m.atk, m.max_health)
        dummy = Minion("TEST_BUY", "Buy", atk=1, health=1)
        dummy.game = g
        dummy.controller = a
        g.events.fire(g, "minion_bought", minion=dummy)
        self.assertEqual((m.atk, m.max_health), base)


class TestSkyAdmiralRogersProgress(unittest.TestCase):
    """BG33_823 — NUM_1 = "Gold left"（阈值 9 - 已花）。"""

    def test_injected_gold_left_credits_spent_progress(self):
        g = make_game(seed=705)
        a = g.heroes[0]
        before = len(a.hand)
        put(g, a, "BG33_823", inject={1: 6})     # 已花 3 金
        g.events.fire(g, "gold_spent", amount=6, hero=a)  # 3+6=9 → 1 Bounty
        self.assertEqual(len(a.hand) + len(g.pending_hand_queue),
                         before + 1)


class TestUpbeatTimers(unittest.TestCase):
    """BG26_529 / BG26_199 — NUM_1 = "X turns left"。"""

    def test_frontdrake_injected_one_triggers_next_eot(self):
        g = make_game(seed=706)
        a = g.heroes[0]
        before = len(a.hand)
        put(g, a, "BG26_529", inject={1: 1})
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertEqual(len(a.hand) + len(g.pending_hand_queue),
                         before + 1)

    def test_duo_injected_one_triggers_next_eot(self):
        g = make_game(seed=707)
        a = g.heroes[0]
        neighbor = g.create_minion("BG25_001", controller=a)
        assert g.summon(a, neighbor)
        before = len(a.hand)
        put(g, a, "BG26_199", inject={1: 1})
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertTrue([m for m in a.hand
                         if isinstance(m, Minion)
                         and m.card_id == "BG25_001"])
        self.assertEqual(len(a.hand) + len(g.pending_hand_queue),
                         before + 1)


class TestZestyUsedFlag(unittest.TestCase):
    """BG26_505 — NUM_1=1 = 本回合已用。"""

    def test_injected_used_blocks_same_turn(self):
        g = make_game(seed=708)
        a = g.heroes[0]
        shaker = put(g, a, "BG26_505", inject={1: 1})
        s = spellcraft_to_hand(g, a)
        g.play_spell(a, s, target=shaker)
        self.assertEqual(spellcraft_copies(a), [])

    def test_no_injection_allows_first_cast(self):
        g = make_game(seed=709)
        a = g.heroes[0]
        shaker = put(g, a, "BG26_505")
        s = spellcraft_to_hand(g, a)
        g.play_spell(a, s, target=shaker)
        self.assertEqual(len(spellcraft_copies(a)), 1)


class TestScarletDone(unittest.TestCase):
    """BG35_814 — NUM_2=1 = "(Done!)" 已获圣盾。"""

    def test_injected_done_grants_divine_shield(self):
        g = make_game(seed=710)
        a = g.heroes[0]
        m = put(g, a, "BG35_814", inject={2: 1})
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(getattr(m, "_scarlet_done", False))

    def test_no_injection_below_threshold_no_shield(self):
        g = make_game(seed=711)
        a = g.heroes[0]
        m = put(g, a, "BG35_814")
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))


class TestScriptDataInjectionMarker(unittest.TestCase):
    """CardDef 静态初始化 ≠ 官方注入（B 类迁移只在真实注入时覆盖旧行为）。"""

    def test_static_carddef_init_not_marked_injected(self):
        g = make_game(seed=712)
        m = g.create_minion("BG33_823", controller=g.heroes[0])
        # 静态 NUM_1=9 已进通道，但不是注入
        self.assertEqual(m.get_script_data(1), 9)
        self.assertFalse(m.is_script_data_injected(1))

    def test_set_script_data_marks_and_clear_unmarks(self):
        g = make_game(seed=713)
        m = g.create_minion("BG33_823", controller=g.heroes[0])
        m.set_script_data(1, 6)
        self.assertTrue(m.is_script_data_injected(1))
        m.clear_script_data(1)
        self.assertFalse(m.is_script_data_injected(1))


if __name__ == "__main__":
    unittest.main()
