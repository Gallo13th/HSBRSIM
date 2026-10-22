"""批次 37x_firelands 测试（F-06 原语 + Firelands Fugitive/Conflagration）。

覆盖真实引擎路径:
  - `game.play_spell` 定向 PendingChoice / 无候选落空
  - `game.play_minion` 元素打出 → F-06 本回合计数 → Conflagration 倍率
  - `game.end_recruit_phase` 回合结束（计数清零后再次施放）
  - `game.destroy_minion` 亡语
  - spawn/召唤元素不计入 "played"
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_37x_firelands as B
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 710) -> Game:
    return Game([make_hero("A"), make_hero("B")], get_db(), seed=seed)


def dummy(hero: Hero, name: str = "Dummy", atk: int = 1,
          health: int = 50, race: Race | None = None) -> Minion:
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


def hand_spell(game: Game, hero: Hero, card_id: str):
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def hand_minion(game: Game, hero: Hero, card_id: str,
                golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def elemental_id() -> str:
    for d in get_db().pool_minions():
        if Race.ELEMENTAL in d.races and Race.ALL not in d.races \
                and REGISTRY.get(d.id) is None:
            return d.id
    raise AssertionError("no plain elemental")


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 3 id 注册 / 数值 / 非池法术标记。"""

    def test_registered(self):
        for cid in (B.CONFLAGRATION, B.FIRELANDS_FUGITIVE,
                    B.FIRELANDS_FUGITIVE_G):
            self.assertIn(cid, REGISTRY, cid)

    def test_card_flags_and_nums(self):
        db = get_db()
        spell = db.get(B.CONFLAGRATION)
        self.assertFalse(spell.is_pool_spell)
        self.assertEqual((spell.num(0), spell.num(1)), (4, 4))
        self.assertTrue(db.get(B.FIRELANDS_FUGITIVE).is_pool_minion)
        self.assertIsNotNone(db.get(B.FIRELANDS_FUGITIVE_G))


class TestConflagration(unittest.TestCase):
    """BG35_910 — 定向 +4/+4，按本回合元素打出数 Improve。"""

    def test_no_element_played_plus_four(self):
        game = make_game(seed=711)
        a = game.heroes[0]
        target = dummy(a, "T", 1, 20)
        spell = hand_spell(game, a, B.CONFLAGRATION)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.health), (1 + 4, 20 + 4))

    def test_two_elements_played_plus_twelve(self):
        game = make_game(seed=712)
        a = game.heroes[0]
        target = dummy(a, "T", 1, 20)
        for _ in range(2):
            m = hand_minion(game, a, elemental_id())
            self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.elementals_played_this_turn(a), 2)
        spell = hand_spell(game, a, B.CONFLAGRATION)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.health), (1 + 12, 20 + 12))

    def test_summoned_elemental_does_not_improve(self):
        game = make_game(seed=713)
        a = game.heroes[0]
        target = dummy(a, "T", 1, 20)
        summoned = game.create_minion(elemental_id(), controller=a)
        self.assertTrue(game.summon(a, summoned))
        self.assertEqual(game.elementals_played_this_turn(a), 0)
        spell = hand_spell(game, a, B.CONFLAGRATION)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.health), (1 + 4, 20 + 4))

    def test_counter_resets_next_turn(self):
        game = make_game(seed=714)
        a, b = game.heroes
        target = dummy(a, "T", 1, 50)
        dummy(b, "Wall", 50, 100)          # 双方存活，推进下一回合
        m = hand_minion(game, a, elemental_id())
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.elementals_played_this_turn(a), 1)
        spell = hand_spell(game, a, B.CONFLAGRATION)
        game.end_recruit_phase()
        self.assertEqual(game.elementals_played_this_turn(a), 0)
        # 上一回合留下的法术仍在手牌 → 新回合施放应只有基础 4/4
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.health), (1 + 4, 50 + 4))

    def test_tavern_spell_extra_stacks(self):
        game = make_game(seed=715)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 2)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 2)
        target = dummy(a, "T", 1, 20)
        spell = hand_spell(game, a, B.CONFLAGRATION)
        self.assertTrue(game.play_spell(a, spell, target=target))
        self.assertEqual((target.atk, target.health), (1 + 6, 20 + 6))

    def test_target_candidates_pending_choice(self):
        game = make_game(seed=716)
        a = game.heroes[0]
        t1 = dummy(a, "T1", 1, 20)
        t2 = dummy(a, "T2", 1, 20)
        spell = hand_spell(game, a, B.CONFLAGRATION)
        self.assertTrue(game.play_spell(a, spell))
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "spell_target")
        self.assertEqual(choice.options, [t1, t2])
        choice.choose(1)
        self.assertEqual((t2.atk, t2.health), (1 + 4, 20 + 4))
        self.assertEqual((t1.atk, t1.health), (1, 20))

    def test_no_candidate_fizzles(self):
        game = make_game(seed=717)
        a = game.heroes[0]
        spell = hand_spell(game, a, B.CONFLAGRATION)
        self.assertTrue(game.play_spell(a, spell))
        self.assertEqual(game.pending_choices, [])


class TestFirelandsFugitive(unittest.TestCase):
    """BG35_882 — BC+DR: Get Conflagration（非池；金 2）。"""

    def test_battlecry_one(self):
        game = make_game(seed=720)
        a = game.heroes[0]
        m = hand_minion(game, a, B.FIRELANDS_FUGITIVE)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([s.card_id for s in a.hand], [B.CONFLAGRATION])

    def test_golden_battlecry_two(self):
        game = make_game(seed=721)
        a = game.heroes[0]
        m = hand_minion(game, a, B.FIRELANDS_FUGITIVE, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 2)
        self.assertTrue(all(s.card_id == B.CONFLAGRATION for s in a.hand))

    def test_deathrattle_one(self):
        game = make_game(seed=722)
        a = game.heroes[0]
        m = self._put(game, a)
        game.destroy_minion(m)
        self.assertEqual([s.card_id for s in a.hand], [B.CONFLAGRATION])

    def test_golden_deathrattle_two(self):
        game = make_game(seed=723)
        a = game.heroes[0]
        m = self._put(game, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 2)

    def test_non_pool_spell_does_not_touch_spell_pool(self):
        game = make_game(seed=724)
        a = game.heroes[0]
        before = game.spell_pool.total_remaining()
        m = hand_minion(game, a, B.FIRELANDS_FUGITIVE)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.spell_pool.total_remaining(), before)

    @staticmethod
    def _put(game, hero, golden=False):
        m = game.create_minion(B.FIRELANDS_FUGITIVE, controller=hero,
                               golden=golden)
        assert game.summon(hero, m)
        return m


if __name__ == "__main__":
    unittest.main()
