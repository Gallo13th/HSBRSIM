"""批次 quest_rewards7 语义测试（作业单 2026-09-15）——临时金色。

覆盖 The Golden Hammer（`BG24_Reward_719` 奖励 + `BG24_Reward_719t`
定向 token 法术）:
  - 真实 `complete_quest` → Spellcraft 立即授予第一张法术
  - 每回合开始再生成（`spellcraft.generate_for_hero`）
  - 真实 `play_spell` → 目标金色化（金色独立卡定义 + 附魔保留）
  - 控制者下一个 `turn_start` → 回滚为非金

约定: 每个落空断言配正对照; 数值/身份期望从 CardDB 读取; owner 隔离。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.stats import Buff
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.spellcraft import generate_for_hero
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

HERO_A = "BG20_HERO_103"
REWARD = "BG24_Reward_719"
TOKEN = "BG24_Reward_719t"
TEST_MINION = "BG25_001"        # Risen Rider（有金色独立定义）


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 70) -> Game:
    g = Game([Hero(HERO_A, "A"), Hero(HERO_A, "B")], get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero) -> None:
    hero._quest_reward_id = REWARD
    game.complete_quest(hero)


def tokens(hero):
    return [s for s in hero.hand if getattr(s, "card_id", None) == TOKEN]


class TestGoldenHammer(unittest.TestCase):
    def test_bind_grants_first_spellcraft_spell(self):
        game = make_game()
        a = game.heroes[0]
        self.assertIn(TOKEN, REGISTRY)
        self.assertIn(REWARD, REGISTRY)
        self.assertEqual(tokens(a), [])
        bind(game, a)
        got = tokens(a)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].has(GameTag.SPELLCRAFT))

    def test_next_turn_generates_another(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        bind(game, a)
        self.assertEqual(len(tokens(a)), 1)
        generate_for_hero(a, game)          # = 回合开始的生成点
        self.assertEqual(len(tokens(a)), 2)

    def test_owner_isolation(self):
        game = make_game(seed=72)
        a, b = game.heroes
        bind(game, a)
        self.assertEqual(len(tokens(a)), 1)
        self.assertEqual(tokens(b), [])

    def test_cast_makes_golden_then_reverts(self):
        game = make_game(seed=73)
        a = game.heroes[0]
        bind(game, a)
        spell = tokens(a)[0]
        d = get_db().get(TEST_MINION)
        g = get_db().golden_version(d)
        m = game.create_minion(TEST_MINION, controller=a)
        game.summon(a, m)
        game.run_actions(Buff(m, atk=2, health=2))
        self.assertTrue(game.play_spell(a, spell, target=m))
        gold = a.board[0]
        self.assertTrue(gold.is_golden)
        self.assertEqual(gold.card_id, g.id)
        self.assertEqual(gold.atk, g.atk + 2)          # 附魔保留
        self.assertEqual(gold.max_health, g.health + 2)
        self.assertTrue(gold.get(GameTag.GILDED_NOT_TRIPLED))
        # 对手回合不回滚
        game.events.fire(game, "turn_start", turn=2, hero=game.heroes[1])
        self.assertTrue(a.board[0].is_golden)
        # 控制者下回合开始 → 回滚（附魔保留）
        game.events.fire(game, "turn_start", turn=2, hero=a)
        back = a.board[0]
        self.assertFalse(back.is_golden)
        self.assertEqual(back.card_id, d.id)
        self.assertEqual(back.atk, d.atk + 2)

    def test_empty_board_whiffs_but_consumes(self):
        game = make_game(seed=74)
        a = game.heroes[0]
        bind(game, a)
        spell = tokens(a)[0]
        self.assertTrue(game.play_spell(a, spell))     # 无候选 → 落空
        self.assertEqual(tokens(a), [])
        self.assertNotIn(spell, a.hand)                # 法术已离手

    def test_cast_without_target_uses_pending_choice(self):
        """定向法术未给 target → 产生 spell_target 选择（正对照）。"""
        game = make_game(seed=75)
        a = game.heroes[0]
        bind(game, a)
        spell = tokens(a)[0]
        m = game.create_minion(TEST_MINION, controller=a)
        game.summon(a, m)
        game.play_spell(a, spell)                       # 不传 target
        kinds = [c.kind for c in game.pending_choices]
        self.assertIn("spell_target", kinds)
        choice = next(c for c in game.pending_choices
                      if c.kind == "spell_target")
        game.pending_choices.remove(choice)
        choice.choose(0)
        self.assertTrue(a.board[0].is_golden)


if __name__ == "__main__":
    unittest.main()
