"""Blood Gem（鲜血宝石）系统测试 — 作业单 2026-08-21。

覆盖: GetBloodGems（入手/变体 id/满手排队）、PlayBloodGems（vanilla
buff/bonus 叠加/source=None）、血宝石 on_play 脚本（vanilla + 3 变体
Quilboar 关键词）、ImproveBloodGems→GetBloodGems→play 端到端。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）; bonus 提升量是
测试**输入**（ImproveBloodGems 由调用方传值，非数据派生）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import (
    GetBloodGems,
    ImproveBloodGems,
    PlayBloodGems,
)
from hsrl2.constants import HAND_SIZE
from hsrl2.db import CardDB
from hsrl2.game import Game, GameStateError
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42) -> Game:
    return Game([make_hero("A"), make_hero("B")], get_db(), seed=seed)


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def plain_on_board(game: Game, hero: Hero, atk: int = 1,
                   health: int = 1) -> Minion:
    """无种族白板随从上棋盘。"""
    m = make_minion("Plain", atk, health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    hero.board.append(m)
    return m


def quilboar_on_board(game: Game, hero: Hero) -> Minion:
    """真实 Quilboar 卡（BG20_100 Razorfen Geomancer, T1）上棋盘。"""
    m = game.create_minion("BG20_100", controller=hero)
    game.summon(hero, m)
    return m


def gem_nums():
    d = get_db().get("BG20_GEM")
    return d.num(0), d.num(1)


# (variant 名, 卡 id, 关键词 tag)
VARIANTS = [
    ("divine_shield", "BG20_GEM_DivineShield", GameTag.DIVINE_SHIELD),
    ("reborn", "BG20_GEM_Reborn", GameTag.REBORN),
    ("taunt", "BG20_GEM_Taunt", GameTag.TAUNT),
]


class TestGetBloodGems(unittest.TestCase):
    """GetBloodGems — 获得 N 颗进手牌（Get=进手牌, SOP §3 动词核对）。"""

    def test_gems_enter_hand(self):
        game = make_game()
        a = game.heroes[0]
        game.run_actions(GetBloodGems(a, 3))
        self.assertEqual(len(a.hand), 3)
        for s in a.hand:
            self.assertIsInstance(s, Spell)
            self.assertEqual(s.card_id, "BG20_GEM")
            self.assertEqual(s.zone, Zone.HAND)
            self.assertIs(s.controller, a)
            # 血宝石不是 Spellcraft（RULES §6.15 — 不回合末丢弃）
            self.assertFalse(s.has(GameTag.SPELLCRAFT))
            # 引擎缺口绕过: GetBloodGems 手动绑定 REGISTRY 脚本
            self.assertIsNotNone(s.scripts)

    def test_variant_card_ids(self):
        game = make_game()
        a = game.heroes[0]
        for variant, card_id, _tag in VARIANTS:
            with self.subTest(variant=variant):
                a.hand.clear()
                game.run_actions(GetBloodGems(a, 1, variant=variant))
                self.assertEqual(a.hand[0].card_id, card_id)

    def test_unknown_variant_rejected(self):
        game = make_game()
        with self.assertRaises(GameStateError):
            GetBloodGems(game.heroes[0], 1, variant="bogus")

    def test_full_hand_queues(self):
        """满手 → pending_hand_queue 排队等待（RULES §3.3 等待不销毁）。"""
        game = make_game()
        a = game.heroes[0]
        for _ in range(HAND_SIZE):
            a.add_to_hand(game.create_spell("BG20_GEM", controller=a))
        self.assertTrue(a.hand_full())
        game.run_actions(GetBloodGems(a, 2))
        self.assertEqual(len(a.hand), HAND_SIZE)
        queued = [e for h, e in game.pending_hand_queue if h is a]
        self.assertEqual(len(queued), 2)
        self.assertTrue(all(e.card_id == "BG20_GEM" for e in queued))


class TestPlayBloodGems(unittest.TestCase):
    """PlayBloodGems — "plays N Blood Gems" = 立即 N 次 vanilla buff。"""

    def test_vanilla_buff_per_gem(self):
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 1, 1)
        num0, num1 = gem_nums()
        game.run_actions(PlayBloodGems(m, 3))
        self.assertEqual(m.atk, 1 + 3 * num0)
        self.assertEqual(m.max_health, 1 + 3 * num1)
        self.assertEqual(m.health, 1 + 3 * num1)

    def test_source_none_path(self):
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 2, 2)
        num0, num1 = gem_nums()
        game.run_actions(PlayBloodGems(m, 1, source=None))
        self.assertEqual((m.atk, m.max_health),
                         (2 + num0, 2 + num1))

    def test_bonus_from_improve_applies(self):
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 1, 1)
        num0, num1 = gem_nums()
        game.run_actions(ImproveBloodGems(a, 2, 3))
        game.run_actions(PlayBloodGems(m, 2))
        self.assertEqual(m.atk, 1 + 2 * (num0 + 2))
        self.assertEqual(m.max_health, 1 + 2 * (num1 + 3))

    def test_improve_stacks(self):
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 1, 1)
        num0, num1 = gem_nums()
        game.run_actions([ImproveBloodGems(a, 1, 1),
                          ImproveBloodGems(a, 1, 1)])
        game.run_actions(PlayBloodGems(m, 1))
        self.assertEqual((m.atk, m.max_health),
                         (1 + num0 + 2, 1 + num1 + 2))

    def test_bonus_reads_target_controller(self):
        """bonus 从 target.controller 读（作业规格: 17 张依赖卡的锚定语义）。"""
        game = make_game()
        a, b = game.heroes
        m = plain_on_board(game, b, 1, 1)
        num0, num1 = gem_nums()
        game.run_actions(ImproveBloodGems(b, 4, 0))
        game.run_actions(PlayBloodGems(m, 1, source=None))
        self.assertEqual(m.atk, 1 + num0 + 4)


class TestBloodGemOnPlay(unittest.TestCase):
    """vanilla 血宝石从手牌打出（play_spell, ctx["target"]）。"""

    def test_play_spell_with_target(self):
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 1, 1)
        game.run_actions(GetBloodGems(a, 1))
        gem = a.hand[0]
        num0, num1 = gem_nums()
        self.assertTrue(game.play_spell(a, gem, target=m))
        self.assertEqual((m.atk, m.max_health), (1 + num0, 1 + num1))
        self.assertNotIn(gem, a.hand)
        self.assertEqual(gem.zone, Zone.REMOVED)

    def test_play_without_target_defers_to_pending_choice(self):
        """needs_target 协议（引擎已支持）: 无 target 打出 →
        PendingChoice(kind="spell_target")，选定后 buff 生效。"""
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 1, 1)
        game.run_actions(GetBloodGems(a, 1))
        self.assertTrue(game.play_spell(a, a.hand[0]))
        self.assertEqual(len(game.pending_choices), 1)
        self.assertEqual(game.pending_choices[0].kind, "spell_target")
        game.pending_choices.pop(0).choose(0)
        self.assertEqual(m.atk, 2)   # 1 base + 宝石 1


class TestVariantOnPlay(unittest.TestCase):
    """变体宝石: Quilboar（含 ALL）目标额外获得关键词，非 Quilboar 不获得。"""

    def test_variant_keyword_on_quilboar_only(self):
        for variant, card_id, tag in VARIANTS:
            with self.subTest(variant=variant):
                game = make_game()
                a = game.heroes[0]
                q = quilboar_on_board(game, a)
                m = plain_on_board(game, a, 1, 1)
                num0, num1 = gem_nums()
                game.run_actions(GetBloodGems(a, 2, variant=variant))
                gem_q, gem_m = a.hand
                self.assertTrue(game.play_spell(a, gem_q, target=q))
                self.assertTrue(game.play_spell(a, gem_m, target=m))
                # 双方都得 vanilla buff
                qd = get_db().get("BG20_100")
                self.assertEqual(q.atk, qd.atk + num0)
                self.assertEqual(q.max_health, qd.health + num1)
                self.assertEqual(m.atk, 1 + num0)
                # 关键词仅 Quilboar 目标
                self.assertTrue(q.has(tag))
                self.assertFalse(m.has(tag))

    def test_race_all_counts_as_quilboar(self):
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 1, 1)
        m.set(GameTag.RACE, Race.ALL)
        game.run_actions(GetBloodGems(a, 1, variant="divine_shield"))
        self.assertTrue(game.play_spell(a, a.hand[0], target=m))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))

    def test_bonus_applies_to_variant_play(self):
        """变体宝石同样吃 bonus（bonus 在 _gem_values 读取点统一）。"""
        game = make_game()
        a = game.heroes[0]
        q = quilboar_on_board(game, a)
        num0, num1 = gem_nums()
        game.run_actions(ImproveBloodGems(a, 2, 1))
        game.run_actions(GetBloodGems(a, 1, variant="taunt"))
        self.assertTrue(game.play_spell(a, a.hand[0], target=q))
        qd = get_db().get("BG20_100")
        self.assertEqual((q.atk, q.max_health),
                         (qd.atk + num0 + 2, qd.health + num1 + 1))
        self.assertTrue(q.has(GameTag.TAUNT))


class TestEndToEnd(unittest.TestCase):
    """ImproveBloodGems → GetBloodGems → 从手牌打出 全链路。"""

    def test_improved_gems_from_hand(self):
        game = make_game()
        a = game.heroes[0]
        m = plain_on_board(game, a, 1, 1)
        num0, num1 = gem_nums()
        game.run_actions(ImproveBloodGems(a, 2, 2))
        game.run_actions(GetBloodGems(a, 2))
        for gem in list(a.hand):
            self.assertTrue(game.play_spell(a, gem, target=m))
        self.assertEqual((m.atk, m.max_health),
                         (1 + 2 * (num0 + 2), 1 + 2 * (num1 + 2)))


if __name__ == "__main__":
    unittest.main()
