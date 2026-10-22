"""批次 bloodgem 语义测试（作业单 2026-08-21，血宝石池随从 6 张）。

覆盖: BG20_100 Razorfen Geomancer / BG23_017 Sanguine Champion /
BG33_430 Prodigious Tusker / BG34_682 Razorfen Flapper /
BG34_683 Briarback Drummer / BG36_510 Vigilant Bristlemane（含金色）。
DEFERRED: BG36_333 Jailbird Juggernaut——占位守护测试（未注册即正确
状态，test_batch_deathrattle2 先例）。

数值断言一律 CardDef.num() / _gem_values 计算（TEST_SOP §4）。
金色战吼模型: 引擎触发 2 次 × 基础每次值 = 金色文本总额; 金色亡语
单次触发 = 金色总额。AFTER_ATTACK 驱动: CombatScheduler._execute_attack
（test_batch_rally2 经验库）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import GetBloodGems, _gem_values
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.pools import SpellPool
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_bloodgem import BLOOD_GEM_BARRAGE_ID
from hsrl2.tags import GameTag

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

GEM_ID = "BG20_GEM"   # 血宝石基础值唯一来源（bloodgem.py 同源）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    """创建随从（create_minion 自动绑定 REGISTRY 脚本）→ 召唤。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def dummy(hero: Hero, health: int = 100, atk: int = 0) -> Minion:
    return make_minion("Dummy", atk, health)


def attack(game: Game, attacker: Minion, defender: Minion) -> None:
    """单次攻击驱动 AFTER_ATTACK（test_batch_rally2 经验库）。"""
    a, b = game.heroes[0], game.heroes[1]
    CombatScheduler(game, a, b)._execute_attack(attacker, defender)


def kill(game: Game, m: Minion) -> None:
    """公开死亡路径: 致死 → check_deaths（亡语先于移除, C6）。"""
    m.health = 0
    game.check_deaths()


def hand_ids(hero: Hero) -> list:
    return [c.card_id for c in hero.hand]


def put_friendly(game: Game, hero: Hero, name: str, atk: int,
                 health: int) -> Minion:
    """合成随从上场（controller=hero，AFTER_ATTACK 友方判定依赖）。"""
    m = make_minion(name, atk, health)
    game.summon(hero, m)
    return m


def gem_into_hand(game: Game, hero: Hero, count: int = 1) -> None:
    """经 GetBloodGems 放入绑定脚本的血宝石（引擎 create_spell 不自动
    绑定——GetBloodGems 手动绑定，官方路径）。"""
    GetBloodGems(hero, count).do(game)


class TestDataDriftGuards(unittest.TestCase):
    """硬编码 id / 池语义漂移守护（对照 data 36.2.2 基线）。"""

    def test_barrage_id_is_pool_spell(self):
        d = get_db().get(BLOOD_GEM_BARRAGE_ID)
        self.assertIsNotNone(d)
        self.assertEqual(d.name, "Blood Gem Barrage")
        self.assertTrue(d.is_pool_spell)   # Get 路径占法术池的数据依据

    def test_gem_values_from_carddef(self):
        d = get_db().get(GEM_ID)
        self.assertIsNotNone(d.num(0))
        self.assertIsNotNone(d.num(1))


class TestRazorfenGeomancer(unittest.TestCase):
    """BG20_100 — Battlecry: Get 2 Blood Gems."""

    def test_battlecry_gets_two_gems(self):
        game = make_game(seed=300)
        a = game.heroes[0]
        m = game.create_minion("BG20_100", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(hand_ids(a), [GEM_ID, GEM_ID])
        # 血宝石非池卡不占法术池
        self.assertEqual(game.spell_pool.available(GEM_ID), 0)

    def test_golden_battlecry_total_four(self):
        game = make_game(seed=301)
        a = game.heroes[0]
        m = game.create_minion("BG20_100", controller=a, golden=True)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        # 金色战吼 ×2 × 每次触发 2 = 总额 4（金色文本 "Get 4"）
        self.assertEqual(hand_ids(a), [GEM_ID] * 4)


class TestSanguineChampion(unittest.TestCase):
    """BG23_017 — Battlecry and Deathrattle: Your Blood Gems give an
    extra +1/+1 this game."""

    def test_battlecry_improves_gems(self):
        game = make_game(seed=302)
        a = game.heroes[0]
        m = game.create_minion("BG23_017", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 1)
        # 集成: _gem_values 读取点统一（手牌/施放路径同时生效）
        base = get_db().get(GEM_ID)
        self.assertEqual(_gem_values(game, GEM_ID, a),
                         (base.num(0) + 1, base.num(1) + 1))

    def test_deathrattle_stacks(self):
        game = make_game(seed=303)
        a = game.heroes[0]
        m = put(game, "BG23_017", a)
        kill(game, m)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 1)

    def test_bc_and_dr_stack_to_two(self):
        game = make_game(seed=304)
        a = game.heroes[0]
        m = game.create_minion("BG23_017", controller=a)
        a.add_to_hand(m)
        game.play_minion(a, m)
        kill(game, m)   # 死亡时已在场上（打出即入场）
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 2)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 2)

    def test_golden_bc_total_two_two(self):
        game = make_game(seed=305)
        a = game.heroes[0]
        m = game.create_minion("BG23_017", controller=a, golden=True)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        # 金色战吼 ×2 × 每次触发 +1/+1 = 总额 +2/+2（金色文本）
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 2)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 2)

    def test_golden_dr_two_two(self):
        game = make_game(seed=306)
        a = game.heroes[0]
        m = put(game, "BG23_017", a, golden=True)
        kill(game, m)
        # 金色亡语单次触发 = 金色文本总额 +2/+2
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 2)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 2)


class TestProdigiousTusker(unittest.TestCase):
    """BG33_430 — Whenever another friendly minion attacks, this plays
    a Blood Gem on it."""

    def test_friendly_attack_plays_gem_on_attacker(self):
        game = make_game(seed=307)
        a, b = game.heroes
        put(game, "BG33_430", a)
        ally = put_friendly(game, a, "Ally", 3, 3)
        attack(game, ally, dummy(b))
        ga, gh = _gem_values(game, GEM_ID, a)
        self.assertEqual(ally.atk, 3 + ga)
        self.assertEqual(ally.health, 3 + gh)

    def test_tusker_own_attack_does_not_trigger(self):
        game = make_game(seed=308)
        a, b = game.heroes
        tusker = put(game, "BG33_430", a)
        atk0, hp0 = tusker.atk, tusker.health
        attack(game, tusker, dummy(b))   # dummy 0 攻 → 无战损
        self.assertEqual((tusker.atk, tusker.health), (atk0, hp0))

    def test_enemy_attack_does_not_trigger(self):
        game = make_game(seed=309)
        a, b = game.heroes
        put(game, "BG33_430", a)
        foe = put_friendly(game, b, "Foe", 3, 3)
        attack(game, foe, dummy(a))
        self.assertEqual((foe.atk, foe.health), (3, 3))

    def test_dead_attacker_skipped(self):
        game = make_game(seed=310)
        a, b = game.heroes
        put(game, "BG33_430", a)
        ally = put_friendly(game, a, "Ally", 1, 1)
        big_foe = dummy(b, health=100, atk=5)
        attack(game, ally, big_foe)   # ally 战死（受 5 点反击）
        self.assertTrue(ally.dead)
        # 战死随从不获亡后 buff（存活时 ga 会改变 atk）
        self.assertEqual(ally.atk, 1)

    def test_golden_plays_two_gems(self):
        game = make_game(seed=311)
        a, b = game.heroes
        put(game, "BG33_430", a, golden=True)
        ally = put_friendly(game, a, "Ally", 3, 3)
        attack(game, ally, dummy(b))
        ga, gh = _gem_values(game, GEM_ID, a)
        self.assertEqual(ally.atk, 3 + 2 * ga)
        self.assertEqual(ally.health, 3 + 2 * gh)


class TestRazorfenFlapper(unittest.TestCase):
    """BG34_682 — Deathrattle: Get a Blood Gem Barrage."""

    def test_deathrattle_gets_barrage_from_pool(self):
        game = make_game(seed=312)
        a = game.heroes[0]
        tier = get_db().get(BLOOD_GEM_BARRAGE_ID).tech_level
        self.assertEqual(game.spell_pool.available(BLOOD_GEM_BARRAGE_ID),
                         SpellPool.POOL_COPIES_BY_TIER[tier])  # 满库存
        m = put(game, "BG34_682", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), [BLOOD_GEM_BARRAGE_ID])
        self.assertEqual(game.spell_pool.available(BLOOD_GEM_BARRAGE_ID),
                         SpellPool.POOL_COPIES_BY_TIER[tier] - 1)

    def test_generates_when_pool_empty(self):
        game = make_game(seed=313)
        a = game.heroes[0]
        while game.spell_pool.available(BLOOD_GEM_BARRAGE_ID):  # 抽干
            assert game.spell_pool.acquire(BLOOD_GEM_BARRAGE_ID)
        m = put(game, "BG34_682", a)
        kill(game, m)
        self.assertEqual(hand_ids(a), [BLOOD_GEM_BARRAGE_ID])

    def test_golden_deathrattle_two_barrages(self):
        game = make_game(seed=314)
        a = game.heroes[0]
        avail = game.spell_pool.available(BLOOD_GEM_BARRAGE_ID)
        m = put(game, "BG34_682", a, golden=True)
        kill(game, m)
        # 两份均自池 acquire（per-tier 副本充足）
        self.assertEqual(hand_ids(a), [BLOOD_GEM_BARRAGE_ID] * 2)
        self.assertEqual(game.spell_pool.available(BLOOD_GEM_BARRAGE_ID),
                         avail - 2)


class TestBriarbackDrummer(unittest.TestCase):
    """BG34_683 — Battlecry: Get a Blood Gem Barrage."""

    def test_battlecry_gets_barrage_from_pool(self):
        game = make_game(seed=315)
        a = game.heroes[0]
        avail = game.spell_pool.available(BLOOD_GEM_BARRAGE_ID)
        m = game.create_minion("BG34_683", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(hand_ids(a), [BLOOD_GEM_BARRAGE_ID])
        self.assertEqual(game.spell_pool.available(BLOOD_GEM_BARRAGE_ID),
                         avail - 1)

    def test_golden_battlecry_total_two(self):
        game = make_game(seed=316)
        a = game.heroes[0]
        avail = game.spell_pool.available(BLOOD_GEM_BARRAGE_ID)
        m = game.create_minion("BG34_683", controller=a, golden=True)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        # 金色战吼 ×2 × 每次触发 1 = 总额 2（金色文本 "Get 2"，均占池）
        self.assertEqual(hand_ids(a), [BLOOD_GEM_BARRAGE_ID] * 2)
        self.assertEqual(game.spell_pool.available(BLOOD_GEM_BARRAGE_ID),
                         avail - 2)

    def test_generates_when_pool_empty(self):
        game = make_game(seed=317)
        a = game.heroes[0]
        while game.spell_pool.available(BLOOD_GEM_BARRAGE_ID):  # 抽干
            assert game.spell_pool.acquire(BLOOD_GEM_BARRAGE_ID)
        m = game.create_minion("BG34_683", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(hand_ids(a), [BLOOD_GEM_BARRAGE_ID])


class TestVigilantBristlemane(unittest.TestCase):
    """BG36_510 — Whenever you cast a spell on this, it plays a Blood
    Gem on adjacent minions."""

    def _board(self, game, golden=False):
        a = game.heroes[0]
        left = put_friendly(game, a, "Left", 2, 2)
        bristle = put(game, "BG36_510", a, golden=golden)
        right = put_friendly(game, a, "Right", 2, 2)
        return a, left, bristle, right

    def _cast_gem_on(self, game, hero, target):
        gem_into_hand(game, hero)
        gem = next(c for c in hero.hand if c.card_id == GEM_ID)
        self.assertTrue(game.play_spell(hero, gem, target=target))

    def test_spell_on_this_gems_adjacent(self):
        game = make_game(seed=318)
        a, left, bristle, right = self._board(game)
        ga, gh = _gem_values(game, GEM_ID, a)
        self._cast_gem_on(game, a, bristle)
        # 相邻各获 1 颗（本卡效果）
        self.assertEqual((left.atk, left.health), (2 + ga, 2 + gh))
        self.assertEqual((right.atk, right.health), (2 + ga, 2 + gh))
        # Bristlemane 自身只受所施法术本身 buff（不在 adjacent 内）
        self.assertEqual(bristle.atk, 3 + ga)

    def test_spell_on_other_minion_no_trigger(self):
        game = make_game(seed=319)
        a, left, bristle, right = self._board(game)
        self._cast_gem_on(game, a, left)
        self.assertEqual((left.atk, left.health), (2 + 1, 2 + 1))
        self.assertEqual((right.atk, right.health), (2, 2))   # 未触发

    def test_opponent_spell_no_trigger(self):
        game = make_game(seed=320)
        a, left, bristle, right = self._board(game)
        b = game.heroes[1]
        gem_into_hand(game, b)
        gem = next(c for c in b.hand if c.card_id == GEM_ID)
        self.assertTrue(game.play_spell(b, gem, target=bristle))
        # "you cast"——对手施放不给相邻宝石（Bristlemane 仍受法术本体）
        self.assertEqual((left.atk, left.health), (2, 2))
        self.assertEqual((right.atk, right.health), (2, 2))

    def test_minion_play_no_trigger(self):
        game = make_game(seed=321)
        a, left, bristle, right = self._board(game)
        m = game.create_minion("BG20_100", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        # 随从打出的 card_played 不带 target → 不触发
        self.assertEqual((left.atk, left.health), (2, 2))
        self.assertEqual((right.atk, right.health), (2, 2))

    def test_golden_two_gems_adjacent(self):
        game = make_game(seed=322)
        a, left, bristle, right = self._board(game, golden=True)
        ga, gh = _gem_values(game, GEM_ID, a)
        self._cast_gem_on(game, a, bristle)
        self.assertEqual((left.atk, left.health), (2 + 2 * ga, 2 + 2 * gh))
        self.assertEqual((right.atk, right.health), (2 + 2 * ga, 2 + 2 * gh))


class TestJailbirdDeferredGuard(unittest.TestCase):
    """BG36_333 — 2026-08-22 batch_unfreeze 解冻后的注册面守护。"""

    def test_registered(self):
        # execute_immediate_attack + GEMS_PLAYED_ON 原语就绪后解冻
        self.assertIn("BG36_333", REGISTRY)
        self.assertIn("BG36_333_G", REGISTRY)

    def test_rally_summons_golem_and_first_attacks(self):
        from hsrl2.combat import CombatScheduler
        game = make_game(seed=323)
        a, b = game.heroes
        m = put(game, "BG36_333", a)
        m.set(GameTag.GEMS_PLAYED_ON, 2)   # 2 颗宝石 → 2/2 Golem
        target = make_minion("Dummy", 0, 100)
        target.controller = b
        target.game = game
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(m, target)
        golem = [x for x in a.board
                 if x.card_id == "BG30_MagicItem_442t" and not x.dead]
        self.assertEqual(len(golem), 1)
        self.assertEqual((golem[0].atk, golem[0].max_health), (2, 2))


if __name__ == "__main__":
    unittest.main()
