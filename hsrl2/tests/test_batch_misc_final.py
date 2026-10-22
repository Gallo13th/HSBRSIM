"""batch_misc_final 行为层测试（439 Designer Eyepatch / 156 Flaming Portrait）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

EYEPATCH = "BG30_MagicItem_439"
PORTRAIT = "BG35_MagicItem_156"
FISHY = "BG30_MagicItem_821t2"
GOLDEN_FISH = "TB_BaconUps_307"
BASE_FISH = "TB_BaconShop_HP_105t"   # 基础版（正对照——无 "twice"）
MICROBOT = "BG_BOT_312t"             # Cord Puller 亡语召唤物（计量单位）
FLAMING = "BG34_500"           # Flaming Enforcer（池随从，Avenge 家族）
FLAMING_G = "BG34_500_G"
PIRATE = "BGS_061"             # Scallywag 3/1 海盗（非池 token? 由下方断言核实）
BEAST = "BG31_803"             # Buzzing Vermin 1/1 野兽（池）
VICTIM = "BG25_013"            # Rot Hide Gnoll 1/4（池）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def put_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


class TestDesignerEyepatch(unittest.TestCase):
    """439 — 海盗只需 2 份成金。"""

    def test_two_pirates_make_golden(self):
        g = make_game(901)
        a, b = g.heroes
        bind(g, a, EYEPATCH)
        self.assertEqual(a.triple_threshold_race.get(Race.PIRATE), 2)
        pid = next(d.id for d in sorted(get_db().pool_minions(),
                                        key=lambda d: d.id)
                   if d.race == Race.PIRATE
                   and get_db().golden_version(d) is not None)
        last = None
        for _ in range(2):
            m = g.create_minion(pid, controller=a)
            a.hand.append(m)
            m.zone = Zone.HAND
            last = m
        g.check_for_triple(a, last)
        self.assertEqual(len([x for x in a.hand if x.is_golden]), 1)

    def test_non_pirate_still_needs_three_and_opponent_unaffected(self):
        g = make_game(902)
        a, b = g.heroes
        bind(g, a, EYEPATCH)
        # **正对照**（同方法内——防"on_bind 改 no-op 仍通过"的空转）
        pid = next(d.id for d in sorted(get_db().pool_minions(),
                                        key=lambda d: d.id)
                   if d.race == Race.PIRATE
                   and get_db().golden_version(d) is not None)
        last_p = None
        for _ in range(2):
            m = g.create_minion(pid, controller=a)
            a.hand.append(m)
            m.zone = Zone.HAND
            last_p = m
        g.check_for_triple(a, last_p)
        self.assertEqual(len([x for x in a.hand if x.is_golden]), 1,
                         "装备 439 后 2 张海盗应成金（正对照）")
        a.hand.clear()          # 清场: 后续只测"非海盗仍为 3 / 对手不受影响"
        # 野兽 2 张不合成（阈值仍为 3）
        last = None
        for _ in range(2):
            m = g.create_minion(BEAST, controller=a)
            a.hand.append(m)
            m.zone = Zone.HAND
            last = m
        g.check_for_triple(a, last)
        self.assertEqual([x for x in a.hand if x.is_golden], [])
        # 对手（无饰品）2 张海盗也不合成
        last_b = None
        for _ in range(2):
            m = g.create_minion(pid, controller=b)
            b.hand.append(m)
            m.zone = Zone.HAND
            last_b = m
        g.check_for_triple(b, last_b)
        self.assertEqual([x for x in b.hand if x.is_golden], [])


class TestFlamingPortrait(unittest.TestCase):
    """156 — 火焰执行者触发时把属性也给左右邻。"""

    def _setup(self, seed=910):
        g = make_game(seed)
        a, b = g.heroes
        t = bind(g, a, PORTRAIT)
        self.assertIn(FLAMING, [x.card_id for x in a.hand])
        left = put(g, a, BEAST)
        fe = put(g, a, FLAMING)
        right = put(g, a, BEAST)
        return g, a, b, t, left, fe, right

    def test_trigger_mirrors_stats_to_neighbors(self):
        g, a, b, t, left, fe, right = self._setup(911)
        a.tavern.clear()
        victim = put_tavern(g, a, VICTIM)
        base_l = (left.atk, left.max_health)
        base_r = (right.atk, right.max_health)
        fe_before = (fe.atk, fe.max_health)
        game_victim = (victim.atk, victim.max_health)
        g.run_script_hook(fe, "end_of_turn")          # 本体 EoT 吞噬
        self.assertGreater((fe.atk, fe.max_health), fe_before)   # 本体照常获得
        self.assertEqual((left.atk, left.max_health),
                         (base_l[0] + game_victim[0],
                          base_l[1] + game_victim[1]))
        self.assertEqual((right.atk, right.max_health),
                         (base_r[0] + game_victim[0],
                          base_r[1] + game_victim[1]))

    def test_other_source_consume_not_mirrored(self):
        """被其它卡驱动吞噬（无自身 EoT 触发）不镜像（负对照）。"""
        g, a, b, t, left, fe, right = self._setup(912)
        a.tavern.clear()
        victim = put_tavern(g, a, VICTIM)
        base_l = (left.atk, left.max_health)
        from hsrl2.actions.consume import ConsumeMinion
        ConsumeMinion(fe, victim).do(g)               # 直接吞噬，非 EoT 触发
        self.assertEqual((left.atk, left.max_health), base_l)

    def test_opponent_trigger_not_mirrored(self):
        g, a, b, t, left, fe, right = self._setup(913)
        # 对手也有 Flaming Enforcer 与馆内受害者
        opp_fe = put(g, b, FLAMING)
        b.tavern.clear()
        put_tavern(g, b, VICTIM)
        base_l = (left.atk, left.max_health)
        g.run_script_hook(opp_fe, "end_of_turn")
        self.assertEqual((left.atk, left.max_health), base_l)

    def test_without_trinket_control(self):
        g = make_game(914)
        a, b = g.heroes
        left = put(g, a, BEAST)
        fe = put(g, a, FLAMING)
        a.tavern.clear()
        put_tavern(g, a, VICTIM)
        base_l = (left.atk, left.max_health)
        g.run_script_hook(fe, "end_of_turn")
        self.assertEqual((left.atk, left.max_health), base_l)


class TestFishySticker(unittest.TestCase):
    """821t2 — SoC 召唤金色 Fish of N'Zoth（脚本经金色回落生效）。"""

    def _fish_with_gained_dr(self, g, a, fish_id):
        """真实 `summon` 走 `on_summon` 注册监听 → 战斗内真实 `death`
        事件登记 1 张亡语（`BG29_611` Cord Puller "Summon a 1/1 Microbot"，
        重放次数可直接用 Microbot 数量计量）。"""
        fish = g.create_minion(fish_id, controller=a)
        self.assertTrue(g.summon(a, fish))
        self.assertEqual(fish._gained_drs, [], "on_summon 未生效")
        victim = g.create_minion("BG29_611", controller=a)
        g.in_combat = True
        g.events.fire(g, "death", minion=victim, hero=a)
        g.in_combat = False
        self.assertEqual(fish._gained_drs, ["BG29_611"])
        return fish

    def test_golden_fish_replays_gained_deathrattle_twice(self):
        """金色文本 "gain its Deathrattle **twice**"（对抗验证证伪项）。"""
        g = make_game(917)
        a, b = g.heroes
        fish = self._fish_with_gained_dr(g, a, GOLDEN_FISH)
        g.trigger_deathrattle(fish)
        bots = [m for m in a.board if m.card_id == MICROBOT]
        self.assertEqual(len(bots), 2, "金色 Fish 应重放亡语 2 次")
        self.assertTrue(all(b.atk == 1 and b.max_health == 1 for b in bots))

    def test_base_fish_replays_once_control(self):
        """正对照: 基础版 `TB_BaconShop_HP_105t` 文本无 "twice" → 1 次。"""
        g = make_game(918)
        a, b = g.heroes
        fish = self._fish_with_gained_dr(g, a, BASE_FISH)
        g.trigger_deathrattle(fish)
        bots = [m for m in a.board if m.card_id == MICROBOT]
        self.assertEqual(len(bots), 1)

    def test_soc_summons_golden_fish(self):
        g = make_game(915)
        a, b = g.heroes
        bind(g, a, FISHY)
        seen = {}
        from hsrl2.events import Listener as _L
        g.events.register(_L(event="start_of_combat", owner=a,
                            callback=lambda gg, hero=None, **kw:
                            seen.update(
                                board=[(m.card_id, m.is_golden)
                                       for m in a.board])))
        g.run_combat(a, b)
        self.assertIn((GOLDEN_FISH, True), seen["board"])
        # 金色 token 独立脚本已注册（不再依赖回落静默降级为 1 次）
        self.assertIs(REGISTRY[GOLDEN_FISH].__name__,
                      "GoldenFishOfNZothScript")
        # 战后复原: 召唤物不留场（RULES §3.5）
        self.assertNotIn(GOLDEN_FISH, [m.card_id for m in a.board])

    def test_opponent_not_affected_and_control(self):
        g = make_game(916)
        a, b = g.heroes
        bind(g, a, FISHY)
        seen, seen_b = {}, {}
        from hsrl2.events import Listener as _L
        g.events.register(_L(event="start_of_combat", owner=a,
                             callback=lambda gg, hero=None, **kw:
                             seen.update(
                                 board=[m.card_id for m in a.board])))
        g.events.register(_L(event="start_of_combat", owner=b,
                             callback=lambda gg, hero=None, **kw:
                             seen_b.update(
                                 board=[m.card_id for m in b.board])))
        g.run_combat(a, b)
        # 正对照: 本人 SoC 确有金色 Fish（防钩子 no-op 仍通过）
        self.assertIn(GOLDEN_FISH, seen["board"])
        # 对手不受影响
        self.assertNotIn(GOLDEN_FISH, seen_b["board"])
        # 负对照: 无饰品
        g2 = make_game(916)
        a2, b2 = g2.heroes
        seen2 = {}
        g2.events.register(_L(event="start_of_combat", owner=a2,
                              callback=lambda gg, hero=None, **kw:
                              seen2.update(
                                  board=[m.card_id for m in a2.board])))
        g2.run_combat(a2, b2)
        self.assertNotIn(GOLDEN_FISH, seen2.get("board", []))


class TestRegistry(unittest.TestCase):
    def test_all_registered(self):
        self.assertIs(REGISTRY[EYEPATCH].__name__,
                      "DesignerEyepatchScript")
        self.assertIs(REGISTRY[PORTRAIT].__name__,
                      "FlamingPortraitScript")
        self.assertIs(REGISTRY[FISHY].__name__, "FishyStickerScript")
        # 金色 Fish 独立脚本（2026-09-13 证伪"回落基础版静默降级"后注册）
        self.assertIs(REGISTRY[GOLDEN_FISH].__name__,
                      "GoldenFishOfNZothScript")


if __name__ == "__main__":
    unittest.main()
