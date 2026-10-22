"""F-06: `ELEMENTALS_PLAYED_THIS_TURN` 本回合元素打出计数（引擎原语）。

背景
═══════════════════════════════════════════════════════════════════════
37.0 卡牌 "Improved by each Elemental you played this turn"
（BG35_910 Conflagration / 宿主 BG35_882 Firelands Fugitive）需要
**本回合**元素打出数；引擎此前只有游戏长计数
`GameTag.COUNTER_ELEMENTALS_PLAYED`（tags 1092，供 BG26_537
Flourishing Frostling "this game" 动态属性使用），无本回合计数/清零点。

契约
═══════════════════════════════════════════════════════════════════════
- `Hero.elementals_played_this_turn`（int，英雄级公开属性）：
  - `_begin_recruit_for` 每回合清零（与 CARDS_PLAYED_THIS_TURN 同点位）
  - 元素随从**从手牌打出**（`Game.play_minion` 普通路径，含战吼结算后）
    +1；非元素不变
  - 公开读取点: `Game.elementals_played_this_turn(hero)`
- 边界（有意，记档 `docs/ENGINE_NOTES.md` F-06）:
  - **不**统计"召唤"（只有 played——官方文本 "you played"）
  - **不**统计磁力吸附路径（与既有 `COUNTER_ELEMENTALS_PLAYED` 口径
    一致；37.0 当前池内无 Elemental+Magnetic，实际不可达；非池
    BG31_859 Technical Element 若未来入池/被生成需重评）
  - 不改写游戏长 `COUNTER_ELEMENTALS_PLAYED`（避免改变既有卡
    Flourishing Frostling 等的行为）
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


def make_game(seed: int = 606) -> Game:
    heroes = [Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")]
    return Game(heroes, get_db(), seed=seed)


def play_hand_minion(game: Game, hero: Hero, card_id: str,
                     golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    assert game.play_minion(hero, m)
    return m


def dummy(hero: Hero, name: str, atk: int = 1, health: int = 5,
          race: Race | None = None) -> Minion:
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


def elemental_id() -> str:
    for d in get_db().pool_minions():
        if Race.ELEMENTAL in d.races and Race.ALL not in d.races:
            return d.id
    raise AssertionError("no elemental")


def non_elemental_id() -> str:
    for d in get_db().pool_minions():
        if not d.races or (Race.ELEMENTAL not in d.races
                           and Race.ALL not in d.races):
            return d.id
    raise AssertionError("no non-elemental")


class TestElementalsPlayedThisTurn(unittest.TestCase):
    """F-06 契约: 英雄级本回合元素计数 + 公开读取点 + 每回合清零。"""

    def test_initialized_to_zero(self):
        game = make_game()
        hero = game.heroes[0]
        self.assertEqual(hero.elementals_played_this_turn, 0)
        self.assertEqual(game.elementals_played_this_turn(hero), 0)

    def test_playing_elemental_increments(self):
        game = make_game()
        hero = game.heroes[0]
        play_hand_minion(game, hero, elemental_id())
        self.assertEqual(hero.elementals_played_this_turn, 1)
        self.assertEqual(game.elementals_played_this_turn(hero), 1)

    def test_playing_non_elemental_does_not_increment(self):
        game = make_game()
        hero = game.heroes[0]
        play_hand_minion(game, hero, non_elemental_id())
        self.assertEqual(game.elementals_played_this_turn(hero), 0)

    def test_accumulates_within_turn(self):
        game = make_game()
        hero = game.heroes[0]
        for _ in range(3):
            play_hand_minion(game, hero, elemental_id())
        self.assertEqual(game.elementals_played_this_turn(hero), 3)

    def test_counts_only_own_hero(self):
        game = make_game()
        a, b = game.heroes
        play_hand_minion(game, a, elemental_id())
        self.assertEqual(game.elementals_played_this_turn(a), 1)
        self.assertEqual(game.elementals_played_this_turn(b), 0)

    def test_summon_does_not_count(self):
        game = make_game()
        hero = game.heroes[0]
        m = game.create_minion(elemental_id(), controller=hero)
        assert game.summon(hero, m)
        self.assertEqual(game.elementals_played_this_turn(hero), 0)

    def test_reset_at_next_recruit_phase(self):
        game = make_game(seed=607)
        a, b = game.heroes
        play_hand_minion(game, a, elemental_id())
        self.assertEqual(game.elementals_played_this_turn(a), 1)
        dummy(a, "Wall", 50, 100)          # 保证战斗不淘汰双方
        dummy(b, "Wall", 50, 100)
        game.end_recruit_phase()
        self.assertEqual(game.elementals_played_this_turn(a), 0)
        self.assertEqual(game.elementals_played_this_turn(b), 0)


if __name__ == "__main__":
    unittest.main()
