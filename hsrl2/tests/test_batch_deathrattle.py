"""死亡语批次语义测试（作业单 2026-08-21，19 张池随从 + 金色）。

覆盖 batch_deathrattle.py 全部注册卡: BG23_318 Leeroy / BG25_009 Eternal
Summoner / BG25_010 Handless / BG25_022 Scarlet Skull / BG25_806 Sly
Raptor / BG26_148 Scrap Scraper / BG26_162 Barnstormer / BG27_016
Champion of Sargeras / BG27_080 Motley Phalanx / BG28_300 Bonehead /
BG28_309 Mummifier / BG29_611 Cord Puller / BG30_125 Cadaver Caretaker /
BG31_801 Forest Rover / BG31_803 Buzzing Vermin / BG31_809 Turquoise
Skitterer / BG31_925 Showy Cyclist / BG32_111 Par-tea Guest / BG32_170
Metallic Hunter。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）; 无模板参数的卡用文本
字面量并注明。金色战吼模型: 引擎触发 2 次 × 基础值 = 金色文本总额;
金色亡语单次触发 = 金色文本总额。

死亡路径统一走 m.take_damage(...) + game.check_deaths()（引擎 C6:
亡语先于移除/复生——位置断言依赖该时序）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.discover import _pool_candidates
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.pools import SpellPool
from hsrl2.scripts import REGISTRY
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


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    """创建随从（scripts 已由 create_minion 绑定 REGISTRY）→ 召唤。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def kill(game: Game, m: Minion, source: Minion | None = None) -> None:
    """招募期致死（take_damage + check_deaths → 亡语→复生/移除全链路）。

    圣盾先破（直伤路径不经过攻击者的破盾语义——金卡关键词导出后
    金色 Cord Puller 等带 DS 的金卡会挡住一次伤害）。
    """
    if m.has(GameTag.DIVINE_SHIELD):
        m.clear(GameTag.DIVINE_SHIELD)
    m.take_damage(99, source=source)
    game.check_deaths()


def tavern_minion(game: Game, hero: Hero, race: Race) -> Minion:
    """取一张指定种族的**真实池卡**入馆（BuffCurrentTavern 需 db 定义）。"""
    d = next(d for d in get_db().pool_minions() if d.race == race)
    m = game.create_minion(d.id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def board_ids(hero: Hero) -> list[str]:
    return [m.card_id for m in hero.board]


# ══════════════════ BG23_318 Leeroy the Reckless ══════════════════


class TestLeeroyTheReckless(unittest.TestCase):
    """DR: Destroy the minion that killed this（金色同文共用类）。"""

    def test_destroys_killer(self):
        game = make_game(seed=1)
        a, b = game.heroes
        attacker = make_minion("ATK", 10, 10)
        game.summon(b, attacker)
        leeroy = put(game, "BG23_318", a)
        kill(game, leeroy, source=attacker)
        self.assertTrue(attacker.dead)
        self.assertNotIn(attacker, b.board)
        self.assertEqual(a.board, [])            # Leeroy 自身正常移除

    def test_golden_destroys_killer(self):
        game = make_game(seed=2)
        a, b = game.heroes
        attacker = make_minion("ATK", 12, 12)
        game.summon(b, attacker)
        leeroy = put(game, "BG23_318", a, golden=True)
        self.assertEqual(leeroy.card_id, "BG23_318_G")
        kill(game, leeroy, source=attacker)
        self.assertTrue(attacker.dead)

    def test_no_killer_no_effect(self):
        game = make_game(seed=3)
        a, b = game.heroes
        attacker = make_minion("ATK", 10, 10)
        game.summon(b, attacker)
        leeroy = put(game, "BG23_318", a)
        kill(game, leeroy)                        # 无来源伤害（EoT 类）
        self.assertFalse(attacker.dead)
        self.assertIn(attacker, b.board)

    def test_destroy_bypasses_divine_shield(self):
        game = make_game(seed=4)
        a, b = game.heroes
        attacker = make_minion("ATK", 10, 10)
        attacker.set(GameTag.DIVINE_SHIELD, True)
        game.summon(b, attacker)
        leeroy = put(game, "BG23_318", a)
        kill(game, leeroy, source=attacker)
        # Destroy 非伤害实例: 圣盾未被消耗但随从仍被消灭
        self.assertTrue(attacker.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(attacker.dead)

    def test_dead_killer_not_destroyed_again(self):
        game = make_game(seed=5)
        a, b = game.heroes
        attacker = make_minion("ATK", 10, 10)
        game.summon(b, attacker)
        attacker.take_damage(99)
        game.check_deaths()                       # 击杀者先死并离场
        leeroy = put(game, "BG23_318", a)
        kill(game, leeroy, source=attacker)       # KILLER 指向已离场实体
        self.assertEqual(a.board, [])
        self.assertEqual(b.board, [])


# ══════════════════ BG25_009 Eternal Summoner ══════════════════


class TestEternalSummoner(unittest.TestCase):
    """Reborn + DR: Summon 1 Eternal Knight（金色=金色骑士）。"""

    def test_dr_summons_knight_at_host_position_with_reborn(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        left = make_minion("L", 1, 5)
        game.summon(a, left, 0)
        es = put(game, "BG25_009", a, position=1)
        right = make_minion("R", 1, 5)
        game.summon(a, right, 2)
        kill(game, es)
        # 亡语先于复生: 骑士插入宿主位 1，复生 Summoner 右移原地 1 血复活
        self.assertEqual(board_ids(a), ["TEST_L", "BG25_008", "BG25_009",
                                        "TEST_R"])
        knight = a.board[1]
        kd = get_db().get("BG25_008")
        self.assertEqual(knight.atk, kd.atk)
        self.assertEqual(knight.health, kd.health)
        self.assertFalse(es.dead)
        self.assertEqual(es.health, 1)             # 复生 1 血

    def test_golden_dr_summons_golden_knight(self):
        game = make_game(seed=7)
        a = game.heroes[0]
        es = put(game, "BG25_009", a, golden=True)
        kill(game, es)
        knight = a.board[0]
        self.assertEqual(knight.card_id, "BG25_008_G")
        self.assertTrue(knight.is_golden)
        kd = get_db().get("BG25_008_G")
        self.assertEqual((knight.atk, knight.health), (kd.atk, kd.health))


# ══════════════════ BG25_010 Handless Forsaken ══════════════════


class TestHandlessForsaken(unittest.TestCase):
    """DR: Summon a 2/1 Hand with Reborn（金色 two = 基础 token ×2）。"""

    def test_dr_summons_helping_hand(self):
        game = make_game(seed=8)
        a = game.heroes[0]
        hf = put(game, "BG25_010", a)
        kill(game, hf)
        self.assertEqual(board_ids(a), ["BG25_010t"])
        hand = a.board[0]
        td = get_db().get("BG25_010t")
        self.assertEqual((hand.atk, hand.health), (td.atk, td.health))
        self.assertTrue(hand.has(GameTag.REBORN))

    def test_golden_dr_summons_two_base_hands(self):
        game = make_game(seed=9)
        a = game.heroes[0]
        hf = put(game, "BG25_010", a, golden=True)
        kill(game, hf)
        # 金色文本 "two 2/1 Hands" = 基础 token ×2（非金色 token 4/2）
        self.assertEqual(board_ids(a), ["BG25_010t", "BG25_010t"])
        for hand in a.board:
            self.assertEqual((hand.atk, hand.health), (2, 1))
            self.assertTrue(hand.has(GameTag.REBORN))


# ══════════════════ BG25_022 Scarlet Skull ══════════════════


class TestScarletSkull(unittest.TestCase):
    """Reborn + DR: Give a friendly Undead +1/+2（金色 +2/+4，文本字面量）。"""

    def test_dr_buffs_one_undead(self):
        game = make_game(seed=10)
        a = game.heroes[0]
        u1 = make_minion("U1", 3, 3, race=Race.UNDEAD)
        game.summon(a, u1)
        u2 = make_minion("U2", 5, 5, race=Race.UNDEAD)
        game.summon(a, u2)
        skull = put(game, "BG25_022", a)
        kill(game, skull)
        # 随机单目标: 合计增量 == +1/+2（文本字面量，CardDef 无参数）
        self.assertEqual(u1.atk + u2.atk, 3 + 5 + 1)
        self.assertEqual(u1.health + u2.health, 3 + 5 + 2)

    def test_golden_dr_buffs_one_undead(self):
        game = make_game(seed=11)
        a = game.heroes[0]
        u1 = make_minion("U1", 3, 3, race=Race.UNDEAD)
        game.summon(a, u1)
        skull = put(game, "BG25_022", a, golden=True)
        kill(game, skull)
        self.assertEqual(u1.atk, 3 + 2)
        self.assertEqual(u1.health, 3 + 4)

    def test_no_undead_candidates_no_effect(self):
        game = make_game(seed=12)
        a = game.heroes[0]
        beast = make_minion("B", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        skull = put(game, "BG25_022", a)
        kill(game, skull)                    # 第一次死亡: 复生复活（1 血）
        self.assertTrue(skull.reborn is False and not skull.dead)
        kill(game, skull)                    # 第二次死亡: 亡语再触发仍无候选
        self.assertEqual((beast.atk, beast.health), (2, 2))
        self.assertEqual(board_ids(a), ["TEST_B"])


# ══════════════════ BG25_806 Sly Raptor ══════════════════


class TestSlyRaptor(unittest.TestCase):
    """DR: Summon a random Beast. Set its stats to {0}/{1}（占池）。"""

    def test_dr_summons_pool_beast_with_set_stats(self):
        game = make_game(seed=13)
        a = game.heroes[0]
        before = {cid: game.minion_pool.available(cid)
                  for cid in _pool_candidates(game, race=Race.BEAST)}
        raptor = put(game, "BG25_806", a)
        kill(game, raptor)
        summoned = [m for m in a.board if m.card_id != "BG25_806"]
        self.assertEqual(len(summoned), 1)
        m = summoned[0]
        d = get_db().get("BG25_806")
        self.assertIn(m.race, (Race.BEAST, Race.ALL))
        self.assertEqual(m.get(GameTag.BASE_ATK), d.num(0))     # 6
        self.assertEqual(m.get(GameTag.BASE_HEALTH), d.num(1))  # 6
        self.assertEqual(m.health, d.num(1))
        self.assertEqual(m.atk, d.num(0))       # 覆盖式（无光环叠加）
        # 占池: 该 id 池副本 -1（宿主招募期死亡回池只影响 BG25_806 自身）
        self.assertEqual(game.minion_pool.available(m.card_id),
                         before[m.card_id] - 1)

    def test_golden_dr_sets_golden_stats(self):
        game = make_game(seed=14)
        a = game.heroes[0]
        raptor = put(game, "BG25_806", a, golden=True)
        kill(game, raptor)
        m = a.board[0]
        dg = get_db().get("BG25_806_G")
        self.assertEqual(m.get(GameTag.BASE_ATK), dg.num(0))    # 12
        self.assertEqual(m.get(GameTag.BASE_HEALTH), dg.num(1))  # 12

    def test_no_candidates_no_effect(self):
        game = make_game(seed=15)
        a = game.heroes[0]
        while True:   # 抽干全部 Beast/ALL 池副本
            cands = _pool_candidates(game, race=Race.BEAST)
            if not cands:
                break
            for cid in cands:
                game.minion_pool.acquire(cid)
        raptor = put(game, "BG25_806", a)
        kill(game, raptor)
        self.assertEqual(a.board, [])


# ══════════════════ BG26_148 Scrap Scraper ══════════════════


def _magnetic_pool_ids(game: Game) -> list[str]:
    return [d.id for d in get_db().pool_minions()
            if "magnetic" in d.keywords
            and d.race in (Race.MECH, Race.ALL)]


class TestScrapScraper(unittest.TestCase):
    """DR: Get a random Magnetic Mech（金色 Get 2，num(0)=2）。"""

    def test_dr_gets_magnetic_mech_from_pool(self):
        game = make_game(seed=16)
        a = game.heroes[0]
        before = {cid: game.minion_pool.available(cid)
                  for cid in _magnetic_pool_ids(game)}
        scraper = put(game, "BG26_148", a)
        kill(game, scraper)
        mechs = [m for m in a.hand if m.card_id in before]
        self.assertEqual(len(mechs), 1)
        self.assertTrue(all("magnetic" in get_db().get(m.card_id).keywords
                            for m in mechs))
        self.assertEqual(game.minion_pool.available(mechs[0].card_id),
                         before[mechs[0].card_id] - 1)

    def test_golden_dr_gets_two(self):
        game = make_game(seed=17)
        a = game.heroes[0]
        ids = set(_magnetic_pool_ids(game))
        scraper = put(game, "BG26_148", a, golden=True)
        kill(game, scraper)
        mechs = [m for m in a.hand if m.card_id in ids]
        self.assertEqual(len(mechs), 2)

    def test_no_candidates_no_effect(self):
        game = make_game(seed=18)
        a = game.heroes[0]
        for cid in _magnetic_pool_ids(game):
            while game.minion_pool.available(cid) > 0:
                game.minion_pool.acquire(cid)
        scraper = put(game, "BG26_148", a)
        kill(game, scraper)
        self.assertEqual(a.hand, [])


# ══════════════════ BG26_162 Dancing Barnstormer ══════════════════


class TestDancingBarnstormer(unittest.TestCase):
    """BC&DR: Give Elementals in the Tavern +{0}/+{1} this game（金色 twice）。"""

    def setUp(self):
        self.game = make_game(seed=19)
        self.a = self.game.heroes[0]
        self.e1 = tavern_minion(self.game, self.a, Race.ELEMENTAL)
        self.e2 = tavern_minion(self.game, self.a, Race.ELEMENTAL)
        self.mech = tavern_minion(self.game, self.a, Race.MECH)
        self.e1_base = (self.e1.atk, self.e1.max_health)

    def test_battlecry_buffs_current_tavern_elementals(self):
        card = put(self.game, "BG26_162", self.a)
        self.game.run_script_hook(card, "battlecry")
        d = get_db().get("BG26_162")
        self.assertEqual(self.e1.atk, self.e1_base[0] + d.num(0))
        self.assertEqual(self.e1.max_health, self.e1_base[1] + d.num(1))
        self.assertEqual(self.e2.atk,
                         self.e2.get(GameTag.BASE_ATK, 0) + d.num(0))
        self.assertNotEqual(self.mech.atk, 0)   # 机械不匹配（基值不变）
        buffs = getattr(self.a, "tavern_buffs", [])
        self.assertEqual(len(buffs), 1)         # "this game" 持久登记
        self.assertEqual((buffs[0].atk, buffs[0].health),
                         (d.num(0), d.num(1)))
        self.assertEqual(buffs[0].race_filter, Race.ELEMENTAL)

    def test_deathrattle_same_effect(self):
        card = put(self.game, "BG26_162", self.a)
        kill(self.game, card)
        d = get_db().get("BG26_162")
        self.assertEqual(self.e1.atk, self.e1_base[0] + d.num(0))
        self.assertEqual(len(getattr(self.a, "tavern_buffs", [])), 1)

    def test_golden_battlecry_via_play_totals_twice(self):
        golden = self.game.create_minion("BG26_162", controller=self.a,
                                         golden=True)
        self.a.add_to_hand(golden)
        self.game.play_minion(self.a, golden)
        # 引擎金色战吼触发 2 次 × 基础 8/8 = 金色文本总额 16/16
        d = get_db().get("BG26_162")
        self.assertEqual(self.e1.atk, self.e1_base[0] + 2 * d.num(0))
        self.assertEqual(self.e1.max_health, self.e1_base[1] + 2 * d.num(1))
        self.assertEqual(len(getattr(self.a, "tavern_buffs", [])), 2)

    def test_golden_deathrattle_applies_twice(self):
        golden = put(self.game, "BG26_162", self.a, golden=True)
        kill(self.game, golden)
        d = get_db().get("BG26_162_G")
        self.assertEqual(self.e1.atk, self.e1_base[0] + 2 * d.num(0))
        self.assertEqual(len(getattr(self.a, "tavern_buffs", [])), 2)


# ══════════════════ BG27_016 Champion of Sargeras ══════════════════


class TestChampionOfSargeras(unittest.TestCase):
    """BC&DR: Give minions in the Tavern +{0}/+{1} this game（金色 16/16）。"""

    def setUp(self):
        self.game = make_game(seed=20)
        self.a = self.game.heroes[0]
        self.e1 = tavern_minion(self.game, self.a, Race.ELEMENTAL)
        self.mech = tavern_minion(self.game, self.a, Race.MECH)
        self.e1_base = (self.e1.atk, self.e1.max_health)
        self.mech_base = (self.mech.atk, self.mech.max_health)

    def test_battlecry_buffs_all_tavern_minions(self):
        card = put(self.game, "BG27_016", self.a)
        self.game.run_script_hook(card, "battlecry")
        d = get_db().get("BG27_016")
        self.assertEqual(self.e1.atk, self.e1_base[0] + d.num(0))   # 8
        self.assertEqual(self.mech.atk, self.mech_base[0] + d.num(0))
        buffs = getattr(self.a, "tavern_buffs", [])
        self.assertEqual(len(buffs), 1)
        self.assertIsNone(buffs[0].race_filter)   # 不限种族

    def test_deathrattle_same_effect(self):
        card = put(self.game, "BG27_016", self.a)
        kill(self.game, card)
        d = get_db().get("BG27_016")
        self.assertEqual(self.e1.atk, self.e1_base[0] + d.num(0))
        self.assertEqual(len(getattr(self.a, "tavern_buffs", [])), 1)

    def test_golden_battlecry_via_play_totals_16(self):
        golden = self.game.create_minion("BG27_016", controller=self.a,
                                         golden=True)
        self.a.add_to_hand(golden)
        self.game.play_minion(self.a, golden)
        dg = get_db().get("BG27_016_G")
        self.assertEqual(self.e1.atk, self.e1_base[0] + dg.num(0))   # 16
        self.assertEqual(self.mech.atk, self.mech_base[0] + dg.num(0))
        self.assertEqual(len(getattr(self.a, "tavern_buffs", [])), 2)

    def test_golden_deathrattle_single_application_of_16(self):
        golden = put(self.game, "BG27_016", self.a, golden=True)
        kill(self.game, golden)
        dg = get_db().get("BG27_016_G")
        self.assertEqual(self.e1.atk, self.e1_base[0] + dg.num(0))
        buffs = getattr(self.a, "tavern_buffs", [])
        self.assertEqual(len(buffs), 1)
        self.assertEqual((buffs[0].atk, buffs[0].health),
                         (dg.num(0), dg.num(1)))


# ══════════════════ BG27_080 Motley Phalanx ══════════════════


class TestMotleyPhalanx(unittest.TestCase):
    """Taunt + DR: Give a friendly minion of each type +{0}/{+1} permanently。"""

    def test_dr_buffs_one_of_each_type(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        demon = make_minion("Demon", 3, 3, race=Race.DEMON)
        game.summon(a, demon)
        amalgam = make_minion("Amalgam", 1, 1, race=Race.ALL)
        game.summon(a, amalgam)
        phalanx = put(game, "BG27_080", a)
        kill(game, phalanx)
        d = get_db().get("BG27_080")
        n_races = 10   # 真实种族数（UNDEAD..NAGA）
        # 每个类型独立随机 1 份 → 全场合计 10 × +num(0)/+num(1)
        self.assertEqual(beast.atk + demon.atk + amalgam.atk,
                         2 + 3 + 1 + n_races * d.num(0))
        self.assertEqual(
            beast.max_health + demon.max_health + amalgam.max_health,
            2 + 3 + 1 + n_races * d.num(1))
        # Amalgam 匹配全部 10 类: 至少 9 份稳得（BEAST 类与 Beast 争夺）
        self.assertGreaterEqual(amalgam.atk, 1 + (n_races - 1) * d.num(0))

    def test_golden_dr_doubles_values(self):
        game = make_game(seed=22)
        a = game.heroes[0]
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        amalgam = make_minion("Amalgam", 1, 1, race=Race.ALL)
        game.summon(a, amalgam)
        phalanx = put(game, "BG27_080", a, golden=True)
        kill(game, phalanx)
        dg = get_db().get("BG27_080_G")
        self.assertEqual(beast.atk + amalgam.atk,
                         2 + 1 + 10 * dg.num(0))

    def test_no_friendly_minions_no_effect(self):
        game = make_game(seed=23)
        a = game.heroes[0]
        phalanx = put(game, "BG27_080", a)
        kill(game, phalanx)
        self.assertEqual(a.board, [])


# ══════════════════ BG28_300 Harmless Bonehead ══════════════════


class TestHarmlessBonehead(unittest.TestCase):
    """DR: Summon two 1/1 Skeletons（金色 four）。"""

    def test_dr_summons_two_skeletons_at_host_position(self):
        game = make_game(seed=24)
        a = game.heroes[0]
        left = make_minion("L", 1, 5)
        game.summon(a, left, 0)
        bh = put(game, "BG28_300", a, position=1)
        right = make_minion("R", 1, 5)
        game.summon(a, right, 2)
        kill(game, bh)
        self.assertEqual(board_ids(a),
                         ["TEST_L", "BG_ICC_026t", "BG_ICC_026t", "TEST_R"])
        td = get_db().get("BG_ICC_026t")
        for s in a.board[1:3]:
            self.assertEqual((s.atk, s.health), (td.atk, td.health))

    def test_golden_dr_summons_four(self):
        game = make_game(seed=25)
        a = game.heroes[0]
        bh = put(game, "BG28_300", a, golden=True)
        kill(game, bh)
        self.assertEqual(board_ids(a).count("BG_ICC_026t"), 4)


# ══════════════════ BG28_309 Mummifier ══════════════════


class TestMummifier(unittest.TestCase):
    """DR: Give a different friendly Undead Reborn（金色 2 different）。"""

    def test_dr_gives_one_undead_reborn(self):
        game = make_game(seed=26)
        a = game.heroes[0]
        undeads = [make_minion(f"U{i}", 2, 2, race=Race.UNDEAD)
                   for i in range(3)]
        for u in undeads:
            game.summon(a, u)
        mech = make_minion("M", 3, 3, race=Race.MECH)
        game.summon(a, mech)
        mumm = put(game, "BG28_309", a)
        kill(game, mumm)
        self.assertEqual(sum(u.has(GameTag.REBORN) for u in undeads), 1)
        self.assertFalse(mech.has(GameTag.REBORN))

    def test_golden_dr_gives_two_different(self):
        game = make_game(seed=27)
        a = game.heroes[0]
        undeads = [make_minion(f"U{i}", 2, 2, race=Race.UNDEAD)
                   for i in range(3)]
        for u in undeads:
            game.summon(a, u)
        mumm = put(game, "BG28_309", a, golden=True)
        kill(game, mumm)
        self.assertEqual(sum(u.has(GameTag.REBORN) for u in undeads), 2)

    def test_no_candidates_no_effect(self):
        game = make_game(seed=28)
        a = game.heroes[0]
        mech = make_minion("M", 3, 3, race=Race.MECH)
        game.summon(a, mech)
        mumm = put(game, "BG28_309", a)
        kill(game, mumm)
        self.assertFalse(mech.has(GameTag.REBORN))


# ══════════════════ BG29_611 Cord Puller ══════════════════


class TestCordPuller(unittest.TestCase):
    """DS + DR: Summon a 1/1 Microbot（金色 2/2 金色 Microbot 卡定义）。"""

    def test_dr_summons_microbot(self):
        game = make_game(seed=29)
        a = game.heroes[0]
        cp = put(game, "BG29_611", a)
        self.assertTrue(cp.has(GameTag.DIVINE_SHIELD))   # def 关键词映射
        cp.clear(GameTag.DIVINE_SHIELD)   # 圣盾会抵消致死伤害——移除后再杀
        kill(game, cp)
        self.assertEqual(board_ids(a), ["BG_BOT_312t"])
        bot = a.board[0]
        self.assertEqual(bot.race, Race.MECH)
        td = get_db().get("BG_BOT_312t")
        self.assertEqual((bot.atk, bot.health), (td.atk, td.health))

    def test_golden_dr_summons_golden_microbot(self):
        game = make_game(seed=30)
        a = game.heroes[0]
        cp = put(game, "BG29_611", a, golden=True)
        kill(game, cp)
        bot = a.board[0]
        # db.golden_version(BG_BOT_312t) 数据链 → TB_BaconUps_032t 2/2
        self.assertEqual(bot.card_id, "TB_BaconUps_032t")
        self.assertEqual((bot.atk, bot.health), (2, 2))


# ══════════════════ BG30_125 Cadaver Caretaker ══════════════════


class TestCadaverCaretaker(unittest.TestCase):
    """DR: Summon three 1/1 Skeletons（金色 six）。"""

    def test_dr_summons_three_consecutive(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        left = make_minion("L", 1, 5)
        game.summon(a, left, 0)
        cc = put(game, "BG30_125", a, position=1)
        right = make_minion("R", 1, 5)
        game.summon(a, right, 2)
        kill(game, cc)
        self.assertEqual(board_ids(a),
                         ["TEST_L"] + ["BG_ICC_026t"] * 3 + ["TEST_R"])

    def test_golden_dr_summons_six(self):
        game = make_game(seed=32)
        a = game.heroes[0]
        cc = put(game, "BG30_125", a, golden=True)
        kill(game, cc)
        self.assertEqual(board_ids(a).count("BG_ICC_026t"), 6)


# ══════════════════ BG31_801 Forest Rover ══════════════════


class TestForestRover(unittest.TestCase):
    """BC: Your Beetles have +{2}/+{3} this game + DR: Summon a {0}/{1} Beetle。"""

    def test_battlecry_applies_beast_race_aura(self):
        game = make_game(seed=33)
        a = game.heroes[0]
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        mech = make_minion("M", 3, 3, race=Race.MECH)
        game.summon(a, mech)
        rover = put(game, "BG31_801", a)
        game.run_script_hook(rover, "battlecry")
        d = get_db().get("BG31_801")
        self.assertEqual(beast.atk, 2 + d.num(2))       # +2
        self.assertEqual(beast.max_health, 2 + d.num(3))  # +1
        self.assertEqual((mech.atk, mech.max_health), (3, 3))

    def test_deathrattle_summons_beetle_with_card_params(self):
        game = make_game(seed=34)
        a = game.heroes[0]
        rover = put(game, "BG31_801", a)
        kill(game, rover)
        self.assertEqual(board_ids(a), ["BG28_603t"])
        beetle = a.board[0]
        d = get_db().get("BG31_801")
        self.assertEqual(beetle.get(GameTag.BASE_ATK), d.num(0))
        self.assertEqual(beetle.get(GameTag.BASE_HEALTH), d.num(1))
        self.assertEqual(beetle.race, Race.BEAST)

    def test_golden_battlecry_via_play_totals_4_2(self):
        game = make_game(seed=35)
        a = game.heroes[0]
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        golden = game.create_minion("BG31_801", controller=a, golden=True)
        a.add_to_hand(golden)
        game.play_minion(a, golden)
        dg = get_db().get("BG31_801_G")
        # 引擎金色 BC 触发 2 次 × 基础 {2}/{3}(2/1) = 金色总额 4/2
        self.assertEqual(beast.atk, 2 + dg.num(2))
        self.assertEqual(beast.max_health, 2 + dg.num(3))

    def test_golden_deathrattle_summons_two_beetles(self):
        game = make_game(seed=36)
        a = game.heroes[0]
        rover = put(game, "BG31_801", a, golden=True)
        kill(game, rover)
        self.assertEqual(board_ids(a).count("BG28_603t"), 2)
        d = get_db().get("BG31_801_G")
        for beetle in a.board:
            self.assertEqual(beetle.get(GameTag.BASE_ATK), d.num(0))
            self.assertEqual(beetle.get(GameTag.BASE_HEALTH), d.num(1))


# ══════════════════ BG31_803 Buzzing Vermin ══════════════════


class TestBuzzingVermin(unittest.TestCase):
    """Taunt + DR: Summon a {0}/{1} Beetle（金色 two）。"""

    def test_dr_summons_beetle(self):
        game = make_game(seed=37)
        a = game.heroes[0]
        bv = put(game, "BG31_803", a)
        self.assertTrue(bv.has(GameTag.TAUNT))
        kill(game, bv)
        self.assertEqual(board_ids(a), ["BG28_603t"])
        beetle = a.board[0]
        d = get_db().get("BG31_803")
        self.assertEqual(beetle.get(GameTag.BASE_ATK), d.num(0))
        self.assertEqual(beetle.get(GameTag.BASE_HEALTH), d.num(1))

    def test_golden_dr_summons_two(self):
        game = make_game(seed=38)
        a = game.heroes[0]
        bv = put(game, "BG31_803", a, golden=True)
        kill(game, bv)
        self.assertEqual(board_ids(a).count("BG28_603t"), 2)


# ══════════════════ BG31_809 Turquoise Skitterer ══════════════════


class TestTurquoiseSkitterer(unittest.TestCase):
    """DR: Your Beetles have +{2}/+{3} this game. Summon a {0}/{1} Beetle。"""

    def test_dr_aura_and_beetle(self):
        game = make_game(seed=39)
        a = game.heroes[0]
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        mech = make_minion("M", 3, 3, race=Race.MECH)
        game.summon(a, mech)
        ts = put(game, "BG31_809", a)
        kill(game, ts)
        d = get_db().get("BG31_809")
        self.assertEqual(beast.atk, 2 + d.num(2))        # +5
        self.assertEqual(beast.max_health, 2 + d.num(3))  # +5
        self.assertEqual((mech.atk, mech.max_health), (3, 3))
        beetles = [m for m in a.board if m.card_id == "BG28_603t"]
        self.assertEqual(len(beetles), 1)
        self.assertEqual(beetles[0].get(GameTag.BASE_ATK), d.num(0))   # 2
        self.assertEqual(beetles[0].get(GameTag.BASE_HEALTH), d.num(1))

    def test_golden_dr_aura_10_10_and_two_beetles(self):
        game = make_game(seed=40)
        a = game.heroes[0]
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        ts = put(game, "BG31_809", a, golden=True)
        kill(game, ts)
        dg = get_db().get("BG31_809_G")
        self.assertEqual(beast.atk, 2 + dg.num(2))        # +10
        self.assertEqual(beast.max_health, 2 + dg.num(3))
        self.assertEqual(board_ids(a).count("BG28_603t"), 2)


# ══════════════════ BG31_925 Showy Cyclist ══════════════════


class TestShowyCyclist(unittest.TestCase):
    """DR: Give all your Naga +{1}/+{3}, improved by every {0}=3 spells。"""

    def _setup(self, seed, golden=False):
        game = make_game(seed=seed)
        a = game.heroes[0]
        n1 = make_minion("N1", 2, 2, race=Race.NAGA)
        game.summon(a, n1)
        n2 = make_minion("N2", 3, 3, race=Race.NAGA)
        game.summon(a, n2)
        mech = make_minion("M", 4, 4, race=Race.MECH)
        game.summon(a, mech)
        cyc = put(game, "BG31_925", a, golden=golden)
        return game, a, n1, n2, mech, cyc

    def test_zero_casts_base_values(self):
        game, a, n1, n2, mech, cyc = self._setup(41)
        kill(game, cyc)
        d = get_db().get("BG31_925")
        mult = 1 + 0 // d.num(0)
        for n in (n1, n2):
            self.assertEqual(n.atk, n.get(GameTag.BASE_ATK, 0)
                             + d.num(1) * mult)       # +2
            self.assertEqual(n.max_health, n.get(GameTag.BASE_HEALTH, 0)
                             + d.num(3) * mult)       # +1
        self.assertEqual((mech.atk, mech.max_health), (4, 4))

    def test_three_casts_doubles(self):
        game, a, n1, _, _, cyc = self._setup(42)
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 3)
        kill(game, cyc)
        d = get_db().get("BG31_925")
        self.assertEqual(n1.atk, n1.get(GameTag.BASE_ATK, 0)
                         + d.num(1) * 2)              # +4
        self.assertEqual(n1.max_health, n1.get(GameTag.BASE_HEALTH, 0)
                         + d.num(3) * 2)              # +2

    def test_seven_casts_triples(self):
        game, a, n1, _, _, cyc = self._setup(43)
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 7)   # 7//3=2 → ×3
        kill(game, cyc)
        d = get_db().get("BG31_925")
        self.assertEqual(n1.atk, n1.get(GameTag.BASE_ATK, 0) + d.num(1) * 3)
        self.assertEqual(n1.max_health,
                         n1.get(GameTag.BASE_HEALTH, 0) + d.num(3) * 3)

    def test_golden_base_values(self):
        game, a, n1, _, _, cyc = self._setup(44, golden=True)
        kill(game, cyc)
        dg = get_db().get("BG31_925_G")
        self.assertEqual(n1.atk, n1.get(GameTag.BASE_ATK, 0) + dg.num(1))
        self.assertEqual(n1.max_health,
                         n1.get(GameTag.BASE_HEALTH, 0) + dg.num(3))

    def test_no_nagas_no_effect(self):
        game = make_game(seed=45)
        a = game.heroes[0]
        mech = make_minion("M", 4, 4, race=Race.MECH)
        game.summon(a, mech)
        cyc = put(game, "BG31_925", a)   # 自身是 Naga 但亡语时已死
        kill(game, cyc)
        self.assertEqual((mech.atk, mech.max_health), (4, 4))
        self.assertEqual(a.board, [mech])


# ══════════════════ BG32_111 Nightmare Par-tea Guest ══════════════════


class TestNightmareParteaGuest(unittest.TestCase):
    """BC&DR: Get a Misplaced Tea Set（池法术 acquire; 金色 2）。"""

    def test_battlecy_and_deathrattle_get_tea_set_from_spell_pool(self):
        game = make_game(seed=46)
        a = game.heroes[0]
        cap = SpellPool.POOL_COPIES_BY_TIER[
            get_db().get("BG28_888").tech_level]
        self.assertEqual(game.spell_pool.available("BG28_888"), cap)
        card = put(game, "BG32_111", a)
        game.run_script_hook(card, "battlecry")
        self.assertEqual([s.card_id for s in a.hand], ["BG28_888"])
        self.assertEqual(game.spell_pool.available("BG28_888"),
                         cap - 1)  # 占池
        kill(game, card)
        # DR: 再自池取 1 份（per-tier 副本充足，总额 2）
        self.assertEqual(len([s for s in a.hand
                              if s.card_id == "BG28_888"]), 2)

    def test_golden_battlecry_via_play_gets_two(self):
        game = make_game(seed=47)
        a = game.heroes[0]
        golden = game.create_minion("BG32_111", controller=a, golden=True)
        a.add_to_hand(golden)
        game.play_minion(a, golden)
        teas = [s for s in a.hand if s.card_id == "BG28_888"]
        self.assertEqual(len(teas), 2)   # 引擎×2 触发 × 每次 1 张

    def test_golden_deathrattle_gets_two(self):
        game = make_game(seed=48)
        a = game.heroes[0]
        avail = game.spell_pool.available("BG28_888")
        golden = put(game, "BG32_111", a, golden=True)
        kill(game, golden)
        teas = [s for s in a.hand if s.card_id == "BG28_888"]
        self.assertEqual(len(teas), 2)
        self.assertEqual(game.spell_pool.available("BG28_888"), avail - 2)


# ══════════════════ BG32_170 Metallic Hunter ══════════════════


class TestMetallicHunter(unittest.TestCase):
    """DR: Get a Pointy Arrow（非池法术直接 create; 金色 2）。"""

    def test_dr_gets_pointy_arrow_without_pool(self):
        game = make_game(seed=49)
        a = game.heroes[0]
        hunter = put(game, "BG32_170", a)
        kill(game, hunter)
        self.assertEqual([s.card_id for s in a.hand], ["EBG_Spell_014"])
        self.assertEqual(game.spell_pool.available("EBG_Spell_014"), 0)

    def test_golden_dr_gets_two(self):
        game = make_game(seed=50)
        a = game.heroes[0]
        hunter = put(game, "BG32_170", a, golden=True)
        kill(game, hunter)
        self.assertEqual([s.card_id for s in a.hand],
                         ["EBG_Spell_014", "EBG_Spell_014"])


# ══════════════════ 注册完整性 ══════════════════


class TestBatchRegistration(unittest.TestCase):
    """19 张基础 + 19 张金色全部注册（防遗漏/拼写）。"""

    IDS = [
        "BG23_318", "BG23_318_G", "BG25_009", "BG25_009_G",
        "BG25_010", "BG25_010_G", "BG25_022", "BG25_022_G",
        "BG25_806", "BG25_806_G", "BG26_148", "BG26_148_G",
        "BG26_162", "BG26_162_G", "BG27_016", "BG27_016_G",
        "BG27_080", "BG27_080_G", "BG28_300", "BG28_300_G",
        "BG28_309", "BG28_309_G", "BG29_611", "BG29_611_G",
        "BG30_125", "BG30_125_G", "BG31_801", "BG31_801_G",
        "BG31_803", "BG31_803_G", "BG31_809", "BG31_809_G",
        "BG31_925", "BG31_925_G", "BG32_111", "BG32_111_G",
        "BG32_170", "BG32_170_G",
    ]

    def test_all_registered_with_deathrattle_hook(self):
        for cid in self.IDS:
            self.assertIn(cid, REGISTRY, cid)
            self.assertTrue(hasattr(REGISTRY[cid], "deathrattle"), cid)


if __name__ == "__main__":
    unittest.main()
