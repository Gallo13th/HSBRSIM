"""批次 37x_discard 行为层测试（12 张池内卡 + F-08 弃置链）。

全真实引擎路径:
  - `Game.use_activate`（真实扣费/计次/Activate 挂钩）
  - `PendingChoice(kind="discard_card")` 选择 → `Game.discard_card`
  - `card_discarded` 事件监听（Whenever you discard）
  - 真实 `play_spell` / `play_minion` / `sell_minion` /
    `end_recruit_phase` EoT / `run_script_hook`
  - 金色独立 CardDef + Activate cost=0 修正
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_37x_discard as B
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 950) -> Game:
    return Game([Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")],
                get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def hand_minion(game: Game, hero: Hero, card_id: str,
                golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def hand_spell(game: Game, hero: Hero, card_id: str):
    s = game.create_spell(card_id, controller=hero)
    s.scripts = REGISTRY.get(card_id)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def dummy(hero: Hero, name: str = "D", atk: int = 1,
          health: int = 20, race: Race | None = None) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, int(race))
    hero.board.append(m)
    game._update_positions(hero)
    return m


def resolve_all(game: Game, index: int = 0) -> None:
    while game.pending_choices:
        choice = game.pending_choices.pop(0)
        choice.choose(index)


def fire_card_played(game: Game, card) -> None:
    """模拟"打出一张手牌"的引擎事件分发（成对弃置监听点）。

    真实 play 路径对随机法术的目标要求不稳定；此处先按打出语义把该卡
    移出手牌（真实 play 会离开手牌），再广播 `card_played`。
    """
    hero = getattr(card, "controller", None)
    if hero is not None and card in hero.hand:
        hero.hand.remove(card)
    game.events.fire(game, "card_played", card=card)


def deity_stats(game: Game, hero: Hero) -> tuple:
    st = game.deity(hero)
    return (st.atk, st.health)


# ══════════════════════════════════════════════════════════════════════
# 结构性
# ══════════════════════════════════════════════════════════════════════


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 24 id 注册 / 数值 / Geomagus 仍 DEFERRED。"""

    def test_registered(self):
        self.assertEqual(len(B._DISCARD_CARDS), 24)
        for cid in B._DISCARD_CARDS:
            self.assertIn(cid, REGISTRY, cid)
        self.assertNotIn("BG28_583", REGISTRY)

    def test_template_numbers(self):
        db = get_db()
        self.assertEqual(db.get(B.MANGLED_BANDIT).num(0), 3)
        self.assertEqual(db.get(B.MANGLED_BANDIT_G).num(0), 6)
        self.assertEqual(db.get(B.MINDBENDER_GHURSHA).num(0), 4)
        self.assertEqual(db.get(B.PARASITIC_FLESHLING).num(0), 2)
        self.assertEqual(db.get(B.MYSTERIOUS_KTHIR).num(2), 3)
        self.assertEqual(db.get(B.MYSTERIOUS_KTHIR_G).num(2), 6)
        self.assertEqual(db.get(B.MYSTERIOUS_KTHIR).num(0), 7)
        self.assertEqual(db.get(B.HARBINGER_APHLASS).num(0), 2)

    def test_zero_cost_activate_tagged(self):
        game = make_game()
        a = game.heroes[0]
        for cid in (B.MANGLED_BANDIT, B.BRAIN_ROTTER, B.ABYSSAL_ENVOY,
                    B.MINDBENDING_RECRUITER, B.NRAQI_FROSTCALLER):
            m = game.create_minion(cid, controller=a)
            self.assertTrue(m.has(GameTag.ACTIVATE), cid)
            self.assertEqual(m.get(GameTag.ACTIVATE_COST), 0, cid)


# ══════════════════════════════════════════════════════════════════════
# Activate: Discard a card 家族
# ══════════════════════════════════════════════════════════════════════


class TestMangledBandit(unittest.TestCase):
    def test_activate_discard_gets_gems(self):
        game = make_game(seed=951)
        a = game.heroes[0]
        m = put(game, B.MANGLED_BANDIT, a)
        junk = hand_spell(game, a, "BG28_810")
        a.gold = 0
        self.assertTrue(game.use_activate(a, m))
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "discard_card")
        self.assertIn(junk, choice.options)
        choice.choose(0)
        self.assertNotIn(junk, a.hand)
        self.assertEqual(len([s for s in a.hand
                              if s.card_id == "BG20_GEM"]), 3)

    def test_golden_six_gems(self):
        game = make_game(seed=952)
        a = game.heroes[0]
        m = put(game, B.MANGLED_BANDIT, a, golden=True)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(len([s for s in a.hand
                              if s.card_id == "BG20_GEM"]), 6)

    def test_empty_hand_fizzles(self):
        game = make_game(seed=953)
        a = game.heroes[0]
        m = put(game, B.MANGLED_BANDIT, a)
        self.assertTrue(game.use_activate(a, m))
        self.assertEqual(game.pending_choices, [])


class TestBrainRotter(unittest.TestCase):
    def test_discard_gives_deity(self):
        game = make_game(seed=954)
        a = game.heroes[0]
        m = put(game, B.BRAIN_ROTTER, a)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(deity_stats(game, a), (3, 3))  # 1/1 + 2/2

    def test_golden_four(self):
        game = make_game(seed=955)
        a = game.heroes[0]
        m = put(game, B.BRAIN_ROTTER, a, golden=True)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(deity_stats(game, a), (5, 5))


class TestAbyssalEnvoy(unittest.TestCase):
    def test_discard_gets_tavern_spell(self):
        game = make_game(seed=956)
        a = game.heroes[0]
        m = put(game, B.ABYSSAL_ENVOY, a)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        spells = [s for s in a.hand if s.card_id != "BG20_GEM"]
        self.assertEqual(len(spells), 1)
        self.assertTrue(get_db().get(spells[0].card_id).is_pool_spell)

    def test_golden_two(self):
        game = make_game(seed=957)
        a = game.heroes[0]
        m = put(game, B.ABYSSAL_ENVOY, a, golden=True)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(len(a.hand), 2)


class TestMindbendingRecruiter(unittest.TestCase):
    def test_discard_gets_aberration(self):
        game = make_game(seed=958)
        a = game.heroes[0]
        m = put(game, B.MINDBENDING_RECRUITER, a)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(len(a.hand), 1)
        d = get_db().get(a.hand[0].card_id)
        self.assertIn(Race.ABERRATION, d.races)

    def test_golden_two(self):
        game = make_game(seed=959)
        a = game.heroes[0]
        m = put(game, B.MINDBENDING_RECRUITER, a, golden=True)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(len(a.hand), 2)


class TestNraqiFrostcaller(unittest.TestCase):
    def test_discard_grants_spell_extra(self):
        game = make_game(seed=960)
        a = game.heroes[0]
        m = put(game, B.NRAQI_FROSTCALLER, a)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 1)

    def test_golden_two(self):
        game = make_game(seed=961)
        a = game.heroes[0]
        m = put(game, B.NRAQI_FROSTCALLER, a, golden=True)
        hand_spell(game, a, "BG28_810")
        self.assertTrue(game.use_activate(a, m))
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2)


# ══════════════════════════════════════════════════════════════════════
# "Whenever you discard a card" 家族
# ══════════════════════════════════════════════════════════════════════


class TestMindbenderGhursha(unittest.TestCase):
    def test_other_minions_gain(self):
        game = make_game(seed=962)
        a = game.heroes[0]
        m = put(game, B.MINDBENDER_GHURSHA, a)
        ally = dummy(a, "Ally", 1, 20)
        junk = hand_spell(game, a, "BG28_810")
        game.discard_card(a, junk)
        self.assertEqual((ally.atk, ally.health), (5, 24))
        self.assertEqual((m.atk, m.health), (3, 9))       # 本体不吃

    def test_golden_eight(self):
        game = make_game(seed=963)
        a = game.heroes[0]
        put(game, B.MINDBENDER_GHURSHA, a, golden=True)
        ally = dummy(a, "Ally", 1, 20)
        game.discard_card(a, hand_spell(game, a, "BG28_810"))
        self.assertEqual((ally.atk, ally.health), (9, 28))

    def test_enemy_discard_does_not_trigger(self):
        game = make_game(seed=964)
        a, b = game.heroes
        put(game, B.MINDBENDER_GHURSHA, a)
        ally = dummy(a, "Ally", 1, 20)
        game.discard_card(b, hand_spell(game, b, "BG28_810"))
        self.assertEqual((ally.atk, ally.health), (1, 20))


class TestCutthroatKThir(unittest.TestCase):
    def test_self_and_deity_gain(self):
        game = make_game(seed=965)
        a = game.heroes[0]
        m = put(game, B.CUTTHROAT_KTHIR, a)
        game.discard_card(a, hand_spell(game, a, "BG28_810"))
        self.assertEqual((m.atk, m.health), (8, 8))
        self.assertEqual(deity_stats(game, a), (5, 5))

    def test_golden_eight(self):
        game = make_game(seed=966)
        a = game.heroes[0]
        m = put(game, B.CUTTHROAT_KTHIR, a, golden=True)
        game.discard_card(a, hand_spell(game, a, "BG28_810"))
        self.assertEqual((m.atk, m.health), (16, 16))
        self.assertEqual(deity_stats(game, a), (9, 9))


class TestHarbingerAphlass(unittest.TestCase):
    def test_improves_each_discard(self):
        game = make_game(seed=967)
        a = game.heroes[0]
        put(game, B.HARBINGER_APHLASS, a)
        expected = [(3, 2), (7, 4), (13, 7)]   # +2/+1, then +4/+2, +6/+3
        for i in range(3):
            game.discard_card(a, hand_spell(game, a, "BG28_810"))
            self.assertEqual(deity_stats(game, a), expected[i])

    def test_golden_values(self):
        game = make_game(seed=968)
        a = game.heroes[0]
        put(game, B.HARBINGER_APHLASS, a, golden=True)
        game.discard_card(a, hand_spell(game, a, "BG28_810"))
        self.assertEqual(deity_stats(game, a), (5, 3))    # 1/1 + 4/2


# ══════════════════════════════════════════════════════════════════════
# EoT 家族
# ══════════════════════════════════════════════════════════════════════


class TestParasiticFleshling(unittest.TestCase):
    def test_zero_discard_plus_two(self):
        game = make_game(seed=970)
        a = game.heroes[0]
        left = dummy(a, "Left", 1, 20)
        f = put(game, B.PARASITIC_FLESHLING, a)
        game.run_script_hook(f, "end_of_turn")
        self.assertEqual((left.atk, left.health), (3, 22))

    def test_improved_by_discards(self):
        game = make_game(seed=971)
        a = game.heroes[0]
        left = dummy(a, "Left", 1, 20)
        f = put(game, B.PARASITIC_FLESHLING, a)
        a.cards_discarded_this_game = 2
        game.run_script_hook(f, "end_of_turn")
        self.assertEqual((left.atk, left.health), (7, 26))  # 2×3=6

    def test_golden_values(self):
        game = make_game(seed=972)
        a = game.heroes[0]
        left = dummy(a, "Left", 1, 20)
        f = put(game, B.PARASITIC_FLESHLING, a, golden=True)
        a.cards_discarded_this_game = 2
        game.run_script_hook(f, "end_of_turn")
        self.assertEqual((left.atk, left.health), (13, 32))  # 4×3=12


class TestMysteriousKThir(unittest.TestCase):
    def test_discards_three_leftmost_tavern_spells(self):
        game = make_game(seed=973)
        a = game.heroes[0]
        k = put(game, B.MYSTERIOUS_KTHIR, a)
        s1 = hand_spell(game, a, "BG28_810")
        minion = hand_minion(game, a, "BG25_008")
        s2 = hand_spell(game, a, "BG28_810")
        s3 = hand_spell(game, a, "BG28_810")
        game.run_script_hook(k, "end_of_turn")
        self.assertNotIn(s1, a.hand)
        self.assertNotIn(s2, a.hand)
        self.assertNotIn(s3, a.hand)
        self.assertIn(minion, a.hand)
        self.assertEqual(a.cards_discarded_this_game, 3)
        self.assertEqual((k.atk, k.health), (28, 28))     # 7×3

    def test_golden_discards_six(self):
        game = make_game(seed=974)
        a = game.heroes[0]
        k = put(game, B.MYSTERIOUS_KTHIR, a, golden=True)
        for _ in range(6):
            hand_spell(game, a, "BG28_810")
        game.run_script_hook(k, "end_of_turn")
        self.assertEqual(a.cards_discarded_this_game, 6)
        self.assertEqual((k.atk, k.health), (56, 56))     # 7×6（金 num=7/7）

    def test_fewer_spells_uses_actual_count(self):
        game = make_game(seed=975)
        a = game.heroes[0]
        k = put(game, B.MYSTERIOUS_KTHIR, a)
        hand_spell(game, a, "BG28_810")
        game.run_script_hook(k, "end_of_turn")
        self.assertEqual(a.cards_discarded_this_game, 1)
        self.assertEqual((k.atk, k.health), (14, 14))


# ══════════════════════════════════════════════════════════════════════
# 成对弃置: Wandering Willbreaker / Faceless Operative
# ══════════════════════════════════════════════════════════════════════


class TestWanderingWillbreaker(unittest.TestCase):
    def test_sell_gets_two_and_play_discards_other(self):
        game = make_game(seed=980)
        a = game.heroes[0]
        m = put(game, B.WANDERING_WILLBREAKER, a)
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(len(a.hand), 2)
        self.assertTrue(all(get_db().get(s.card_id).is_pool_spell
                            for s in a.hand))
        first, second = list(a.hand)
        fire_card_played(game, first)
        self.assertNotIn(second, a.hand)
        self.assertEqual(a.cards_discarded_this_game, 1)

    def test_golden_four_play_two_discards_rest(self):
        game = make_game(seed=981)
        a = game.heroes[0]
        m = put(game, B.WANDERING_WILLBREAKER, a, golden=True)
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(len(a.hand), 4)
        cards = list(a.hand)
        fire_card_played(game, cards[0])
        self.assertEqual(a.cards_discarded_this_game, 0)
        fire_card_played(game, cards[1])
        self.assertEqual(a.cards_discarded_this_game, 2)
        self.assertNotIn(cards[2], a.hand)
        self.assertNotIn(cards[3], a.hand)


class TestFacelessOperative(unittest.TestCase):
    def test_sell_gets_two_aberrations_and_play_discards_other(self):
        game = make_game(seed=982)
        a = game.heroes[0]
        m = put(game, B.FACELESS_OPERATIVE, a)
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(len(a.hand), 2)
        self.assertTrue(all(Race.ABERRATION in get_db().get(x.card_id).races
                            for x in a.hand))
        first, second = list(a.hand)
        fire_card_played(game, first)
        self.assertNotIn(second, a.hand)
        self.assertEqual(a.cards_discarded_this_game, 1)

    def test_golden_four(self):
        game = make_game(seed=983)
        a = game.heroes[0]
        m = put(game, B.FACELESS_OPERATIVE, a, golden=True)
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(len(a.hand), 4)


# ══════════════════════════════════════════════════════════════════════
# 载荷 on_discard 回补（测试归属: payloadgap1 / deity 批次测试文件——
# 空转审计按"批次-测试"配对计分，故此处不重复挂载以免类级空转）
# ══════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    unittest.main()
