"""批次 37x_poolgap1 行为层测试（3 张池内卡 + 3 张金色独立 CardDef）。

真实引擎路径:
  - SoC / Rally: 真实 `CombatScheduler._start_of_combat_phase()` 与真实
    `combat.execute_immediate_attack`（`before_attack` / Rally 广播）
  - Avenge: 真实死亡流程 `game.destroy_minion` → `check_deaths` →
    引擎 Avenge 计数（`AVENGE_TARGET`/战斗内守卫）
  - 打出触发: 真实 `game.play_minion`（`card_played` 广播）
  - 过期: 真实 `game._begin_recruit_for`（`turn_start` 广播）
每个效果都有正对照 + 负对照（非 Elemental / 对手 / 无战斗对 / 阈值未达）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_37x_poolgap1 as B
from hsrl2.tags import GameTag, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


ELEMENTAL = "BGS_119"          # Crackling Cyclone 2/1 T1 Elemental（白板）
NON_ELEMENTAL = "BG25_001"     # Risen Rider 2/1 T1 Undead（白板）


def make_game(seed: int = 37) -> Game:
    a, b = Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")
    return Game([a, b], get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def make_minion(name: str, atk: int, health: int) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health)


def dummy(hero: Hero, atk: int = 0, health: int = 100) -> Minion:
    m = make_minion("Dummy", atk, health)
    m.game = hero.game
    m.controller = hero
    m.zone = Zone.PLAY
    hero.board.append(m)
    return m


def hand_card(game: Game, hero: Hero, card_id: str,
              golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def custom_hand(game: Game, hero: Hero, name: str, atk: int, health: int,
                race) -> Minion:
    """手牌中的测试随从（无 CardDef/脚本——避免用带原生圣盾/效果的卡
    干扰 Ichoron 的正/负对照）。"""
    m = Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)
    m.game = game
    m.controller = hero
    m.zone = Zone.HAND
    hero.hand.append(m)
    return m


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    game.in_combat = True
    game._active_combat = (a, b)


def soc(game: Game, a: Hero, b: Hero) -> None:
    """单独驱动 SoC 阶段（真实 `CombatScheduler._start_of_combat_phase`）。"""
    game.in_combat = True
    game._active_combat = (a, b)
    CombatScheduler(game, a, b)._start_of_combat_phase()


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 池归属 / 阈值数据 / 金色定义。"""

    def test_registered(self):
        for cid in (B.HEROIC_BROODMOTHER, B.HEROIC_BROODMOTHER_G,
                    B.ETERNAL_TYCOON, B.ETERNAL_TYCOON_G,
                    B.ICHORON, B.ICHORON_G):
            self.assertIn(cid, REGISTRY, cid)

    def test_pool_membership(self):
        db = get_db()
        for cid in (B.HEROIC_BROODMOTHER, B.ETERNAL_TYCOON, B.ICHORON):
            self.assertTrue(db.get(cid).is_pool_minion, cid)

    def test_avenge_threshold_from_data(self):
        d = get_db().get(B.ETERNAL_TYCOON)
        self.assertEqual(d.avenge_target, 5)
        self.assertEqual(d.num(0), 5)

    def test_golden_card_defs(self):
        db = get_db()
        for base, golden in (
                (B.HEROIC_BROODMOTHER, B.HEROIC_BROODMOTHER_G),
                (B.ETERNAL_TYCOON, B.ETERNAL_TYCOON_G),
                (B.ICHORON, B.ICHORON_G)):
            g = db.golden_version(db.get(base))
            self.assertIsNotNone(g, base)
            self.assertEqual(g.id, golden)


# ══════════════════════════════════════════════════════════════════════
# BG36_849 Heroic Broodmother
# ══════════════════════════════════════════════════════════════════════


class TestHeroicBroodmother(unittest.TestCase):
    def test_soc_attacks_immediately_and_rally_gives_divine_shield(self):
        game = make_game(seed=2001)
        a, b = game.heroes
        brood = put(game, B.HEROIC_BROODMOTHER, a)
        target = dummy(b, atk=0, health=40)
        soc(game, a, b)
        self.assertEqual(target.health, 40 - 7)      # SoC 立即攻击
        self.assertTrue(brood.has(GameTag.DIVINE_SHIELD))  # Rally 圣盾

    def test_golden_attacks_twice(self):
        game = make_game(seed=2002)
        a, b = game.heroes
        brood = put(game, B.HEROIC_BROODMOTHER, a, golden=True)
        self.assertEqual(brood.card_id, B.HEROIC_BROODMOTHER_G)
        self.assertEqual(brood.atk, 14)              # 金色 CardDef 14/14
        target = dummy(b, atk=0, health=60)
        soc(game, a, b)
        self.assertEqual(target.health, 60 - 28)     # 两次 14 点

    def test_rally_gain_shield_via_real_attack(self):
        game = make_game(seed=2003)
        a, b = game.heroes
        brood = put(game, B.HEROIC_BROODMOTHER, a)
        target = dummy(b, atk=0, health=40)
        enter_combat(game, a, b)
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, brood, target)
        self.assertTrue(brood.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(target.health, 40 - 7)

    def test_no_opponent_fizzles(self):
        game = make_game(seed=2004)
        a, b = game.heroes
        brood = put(game, B.HEROIC_BROODMOTHER, a)
        # 无 _active_combat（招募期/直接调钩子）→ 不攻击不崩溃
        B.HeroicBroodmotherScript.start_of_combat(brood, game, {})
        self.assertEqual(len(b.board), 0)
        self.assertEqual(brood.atk, 7)

    def test_rally_noop_when_already_shielded(self):
        game = make_game(seed=2005)
        a, b = game.heroes
        brood = put(game, B.HEROIC_BROODMOTHER, a)
        brood.set(GameTag.DIVINE_SHIELD, True)
        self.assertIsNone(
            B.HeroicBroodmotherScript.rally(brood, game, {}))
        self.assertTrue(brood.has(GameTag.DIVINE_SHIELD))


# ══════════════════════════════════════════════════════════════════════
# BG34_403 Eternal Tycoon
# ══════════════════════════════════════════════════════════════════════


class TestEternalTycoon(unittest.TestCase):
    def _avenge_setup(self, seed: int, golden: bool = False):
        game = make_game(seed=seed)
        a, b = game.heroes
        tycoon = put(game, B.ETERNAL_TYCOON, a, golden=golden)
        fodder = put(game, "BG34_630t", a)           # 3/3 白板 token
        target = dummy(b, atk=0, health=60)
        enter_combat(game, a, b)
        tycoon.set(GameTag.AVENGE_COUNTER, 4)        # 引擎计数差 1
        return game, a, b, tycoon, fodder, target

    def test_avenge_five_summons_knight_that_attacks(self):
        game, a, b, tycoon, fodder, target = self._avenge_setup(2101)
        game.destroy_minion(fodder)                  # 第 5 次友方死亡
        knights = [m for m in a.board if m.card_id == B.ETERNAL_KNIGHT]
        self.assertEqual(len(knights), 1)
        self.assertEqual((knights[0].atk, knights[0].max_health), (4, 2))
        self.assertEqual(target.health, 60 - 4)      # 立即攻击

    def test_golden_summons_golden_knight(self):
        game, a, b, tycoon, fodder, target = self._avenge_setup(
            2102, golden=True)
        self.assertEqual(tycoon.card_id, B.ETERNAL_TYCOON_G)
        game.destroy_minion(fodder)
        knights = [m for m in a.board if m.card_id == "BG25_008_G"]
        self.assertEqual(len(knights), 1)
        self.assertEqual((knights[0].atk, knights[0].max_health), (8, 4))

    def test_threshold_not_reached_no_trigger(self):
        game = make_game(seed=2103)
        a, b = game.heroes
        put(game, B.ETERNAL_TYCOON, a)
        dummy(b, atk=0, health=60)
        enter_combat(game, a, b)
        for _ in range(4):                           # 4 < 5: 不触发
            fodder = put(game, "BG34_630t", a)
            game.destroy_minion(fodder)
        self.assertEqual(
            len([x for x in a.board if x.card_id == B.ETERNAL_KNIGHT]), 0)

    def test_recruit_phase_deaths_do_not_count(self):
        """Avenge 是战斗关键词（RULES §6.11）：招募期死亡不触发。"""
        game = make_game(seed=2104)
        a, b = game.heroes
        tycoon = put(game, B.ETERNAL_TYCOON, a)
        tycoon.set(GameTag.AVENGE_COUNTER, 4)
        fodder = put(game, "BG34_630t", a)
        game.destroy_minion(fodder)                  # 无 _active_combat
        self.assertEqual(
            len([x for x in a.board if x.card_id == B.ETERNAL_KNIGHT]), 0)

    def test_full_board_summon_fizzles(self):
        game = make_game(seed=2105)
        a, b = game.heroes
        tycoon = put(game, B.ETERNAL_TYCOON, a)
        for _ in range(6):
            put(game, "BG34_630t", a)
        self.assertTrue(a.board_full())
        dummy(b, atk=0, health=20)
        enter_combat(game, a, b)
        B.EternalTycoonScript.avenge(tycoon, game, {})
        self.assertEqual(len(a.board), 7)
        self.assertEqual(
            len([x for x in a.board if x.card_id == B.ETERNAL_KNIGHT]), 0)


# ══════════════════════════════════════════════════════════════════════
# BG31_812 Ichoron the Protector
# ══════════════════════════════════════════════════════════════════════


class TestIchoron(unittest.TestCase):
    def _elemental_in_hand(self, game, hero) -> Minion:
        from hsrl2.tags import Race
        return custom_hand(game, hero, "Elem", 2, 2, Race.ELEMENTAL)

    def test_played_elemental_gains_divine_shield_until_next_turn(self):
        game = make_game(seed=2201)
        a, b = game.heroes
        put(game, B.ICHORON, a)                      # 注册监听器
        elem = self._elemental_in_hand(game, a)
        self.assertFalse(elem.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(game.play_minion(a, elem))
        self.assertTrue(elem.has(GameTag.DIVINE_SHIELD))
        game._begin_recruit_for(a)                   # 下一回合开始
        self.assertFalse(elem.has(GameTag.DIVINE_SHIELD))

    def test_non_elemental_does_not_trigger(self):
        game = make_game(seed=2202)
        a, b = game.heroes
        put(game, B.ICHORON, a)
        from hsrl2.tags import Race
        m = custom_hand(game, a, "Beast", 2, 2, Race.BEAST)
        self.assertTrue(game.play_minion(a, m))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_opponent_elemental_does_not_trigger(self):
        game = make_game(seed=2203)
        a, b = game.heroes
        put(game, B.ICHORON, a)
        m = self._elemental_in_hand(game, b)
        self.assertTrue(game.play_minion(b, m))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_golden_shield_is_permanent(self):
        game = make_game(seed=2204)
        a, b = game.heroes
        ichoron = put(game, B.ICHORON, a, golden=True)
        self.assertEqual(ichoron.card_id, B.ICHORON_G)
        elem = self._elemental_in_hand(game, a)
        self.assertTrue(game.play_minion(a, elem))
        self.assertTrue(elem.has(GameTag.DIVINE_SHIELD))
        game._begin_recruit_for(a)
        self.assertTrue(elem.has(GameTag.DIVINE_SHIELD))

    def test_preexisting_shield_not_removed_by_expiry(self):
        game = make_game(seed=2205)
        a, b = game.heroes
        put(game, B.ICHORON, a)
        # BGS_119 数据自带圣盾（"Has Divine Shield"对照）
        elem = hand_card(game, a, ELEMENTAL)
        self.assertTrue(elem.has(GameTag.DIVINE_SHIELD))   # data 原生
        self.assertTrue(game.play_minion(a, elem))
        game._begin_recruit_for(a)
        self.assertTrue(elem.has(GameTag.DIVINE_SHIELD))

    def test_combat_shield_prevents_damage(self):
        """获得的圣盾在下一场战斗中真实生效（真实单次攻击）。"""
        game = make_game(seed=2206)
        a, b = game.heroes
        put(game, B.ICHORON, a)
        elem = self._elemental_in_hand(game, a)      # 2/2
        self.assertTrue(game.play_minion(a, elem))
        enemy = dummy(b, atk=10, health=20)
        enter_combat(game, a, b)
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, enemy, elem)
        self.assertFalse(elem.has(GameTag.DIVINE_SHIELD))   # 盾破
        self.assertEqual(elem.health, 2)                    # 未受伤


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
