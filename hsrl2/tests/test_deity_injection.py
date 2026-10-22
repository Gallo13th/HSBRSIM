"""F-15: 官方战斗边界 Deity 快照注入（默认行为不变）。

state_corpus（bridge-analyst）六字段：deity_card_id / atk / health /
progress / awakened / sigil_card_id。diff-harness 在构建战斗前调用
`Game.inject_deity_state`；未注入时引擎仍走 F-07 惰性派生，逐位不变。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.tags import GameTag

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 31500) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    return g


class TestDeityInjection(unittest.TestCase):
    def test_default_behavior_unchanged(self):
        g = make_game()
        a = g.heroes[0]
        self.assertIsNone(getattr(a, "deity", None))
        # 未注入：旧惰性派生仍可用
        state = g.deity(a)
        self.assertIn(state.card_id, ("BGFYM_000", "BGFYM_011"))
        self.assertFalse(state.injected)
        self.assertEqual((state.atk, state.health), (1, 1))
        self.assertIsNone(state.sigil_card_id)

    def test_inject_exact_snapshot(self):
        g = make_game(seed=31501)
        a = g.heroes[0]
        st = g.inject_deity_state(
            a, card_id="BGFYM_000", atk=33, health=33,
            progress=0, awakened=False, sigil_card_id="BG_OldGod")
        self.assertIs(g.deity(a), st)
        self.assertEqual((st.atk, st.health), (33, 33))
        self.assertEqual(st.progress, 0)
        self.assertFalse(st.awakened)
        self.assertEqual(st.sigil_card_id, "BG_OldGod")
        self.assertTrue(st.injected)

    def test_injected_state_survives_combat_reset(self):
        g = make_game(seed=31502)
        a = g.heroes[0]
        g.inject_deity_state(
            a, card_id="BGFYM_000", atk=87, health=86,
            progress=3, awakened=True, sigil_card_id="BG_OldGod")
        # run_combat 开始会调用 _reset_deity_combat；注入态不得被清零
        g.run_combat(a, g.heroes[1])
        st = g.deity(a)
        self.assertEqual((st.progress, st.awakened), (3, True))
        self.assertEqual((st.atk, st.health), (87, 86))

    def test_non_injected_state_reset_unchanged(self):
        g = make_game(seed=31503)
        a = g.heroes[0]
        st = g.deity(a)
        st.progress = 2
        st.awakened = True
        g._reset_deity_combat()
        self.assertEqual((st.progress, st.awakened), (0, False))

    def test_set_progress_and_sigil_helpers(self):
        g = make_game(seed=31504)
        a = g.heroes[0]
        g.set_deity_progress(a, 2, awakened=False)
        g.set_deity_sigil(a, "BG_OldGod")
        st = g.deity(a)
        self.assertEqual((st.progress, st.awakened), (2, False))
        self.assertEqual(st.sigil_card_id, "BG_OldGod")
        self.assertTrue(st.injected)

    def test_invalid_deity_rejected(self):
        from hsrl2.game import GameStateError
        g = make_game(seed=31505)
        with self.assertRaises(GameStateError):
            g.inject_deity_state(g.heroes[0], card_id="BGFYM_999")

    def test_sigil_object_injection(self):
        g = make_game(seed=31506)
        a = g.heroes[0]
        g.inject_deity_sigil(a, "BG_OldGod", progress=2, awakened=True)
        self.assertIsNotNone(a.deity_sigil)
        self.assertEqual(a.deity_sigil.card_id, "BG_OldGod")
        self.assertEqual(a.deity_sigil.progress, 2)
        self.assertTrue(a.deity_sigil.awakened)
        self.assertEqual(g.deity(a).sigil_card_id, "BG_OldGod")

    def test_board_deity_token_injection(self):
        g = make_game(seed=31507)
        a = g.heroes[0]
        st = g.inject_deity_state(
            a, card_id="BGFYM_000", atk=33, health=33,
            progress=0, awakened=False, sigil_card_id="BG_OldGod",
            board_tokens=[{"card_id": "BGFYM_000", "atk": 33,
                           "health": 33, "position": 0,
                           "keywords": ["taunt"]}])
        self.assertEqual(st.card_id, "BGFYM_000")
        self.assertEqual(len(a.board), 1)
        token = a.board[0]
        self.assertEqual(token.card_id, "BGFYM_000")
        self.assertEqual((token.atk, token.max_health), (33, 33))
        self.assertTrue(token.has(GameTag.TAUNT))

    def test_board_token_custom_position(self):
        g = make_game(seed=31508)
        a = g.heroes[0]
        game = g
        first = game.create_minion("BG25_013", controller=a)
        self.assertTrue(game.summon(a, first))
        game.inject_deity_state(
            a, card_id="BGFYM_011", atk=10, health=10,
            board_tokens=[{"card_id": "BGFYM_011", "atk": 10,
                           "health": 10, "position": 0}])
        self.assertEqual(a.board[0].card_id, "BGFYM_011")
        self.assertEqual(a.board[1].card_id, "BG25_013")


if __name__ == "__main__":
    unittest.main()
