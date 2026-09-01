"""批次 choose_one 语义测试（作业单 2026-08-22，12 张）。

覆盖: 5 张 Choose One 随从（两分支各测 + 金色 + both 双效）/ Turbo
Hogrider 触发 / Thorned Trailblazer 光环 / Humon'gozz / Enchanted
Sentinel / Sand Swirler / Lurking Leviathan（含金色）。
AMBIGUOUS: BG33_319 Rimescale Priestess——未注册即正确状态守护
（Jailbird/batch_bloodgem 先例）。

数值断言一律 CardDef.num()（TEST_SOP §4）。Choose One 驱动:
play_minion → PendingChoice(kind="choose_one").choose(idx)（引擎
协议，test_engine_gaps.TestChooseOne 同构）; CHOOSE_BOTH 双效 =
棋盘 Trailblazer 在场时引擎直接 choose="both" 不弹选择。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import GetBloodGems
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_choose_one import _is_choose_one_card
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

GEM_ID = "BG20_GEM"          # 血宝石基础值唯一来源（bloodgem.py 同源）
GEM_DAY_DBF = 116596         # BG31_320/BG31_326 evolution 数据链 → BG31_893

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
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def hand_ids(hero: Hero) -> list:
    return [c.card_id for c in hero.hand]


def play_choose(game: Game, hero: Hero, card_id: str, idx: int,
                golden: bool = False) -> Minion:
    """打出 Choose One 随从并解决选择（引擎协议驱动）。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.add_to_hand(m)
    assert game.play_minion(hero, m)
    pc = game.pending_choices.pop(0)
    assert pc.kind == "choose_one"
    pc.choose(idx)
    return m


class TestDataDriftGuards(unittest.TestCase):
    """硬编码 id / 模板参数 / Choose One 判定式漂移守护（36.2.2 基线）。"""

    def test_card_identity(self):
        db = get_db()
        for cid, name, nums in [
            ("BG31_320", "Crater Miner", (2, None, None, None)),
            ("BG36_330", "Sly Infiltrator", (2, 3, None, None)),
            ("BG36_332", "Snare Trapper", (1, None, None, None)),
            ("BG36_341", "Veteran Brigand", (3, 3, None, None)),
            ("BG31_327", "Thorned Trailblazer", (1, None, None, None)),
            ("BG35_341", "Enchanted Sentinel", (None, 1, 1, None)),
            ("BG32_841", "Sand Swirler", (2, None, None, None)),
            ("BG35_602", "Lurking Leviathan", (None, 2, None, None)),
        ]:
            d = db.get(cid)
            self.assertIsNotNone(d, cid)
            self.assertEqual(d.name, name)
            self.assertEqual(tuple(d.num(i) for i in range(4)), nums, cid)

    def test_gem_day_data_chain(self):
        db = get_db()
        for src in ("BG31_320", "BG36_341"):
            d = db.get(src)
            self.assertIsNotNone(d.evolution_card_id)
            t = db.by_dbf(d.evolution_card_id)
            self.assertIsNotNone(t, f"{src} evolution target in db")
        self.assertEqual(db.by_dbf(GEM_DAY_DBF).id, "BG31_893")
        self.assertEqual(db.by_dbf(GEM_DAY_DBF).name, "Gem Day")

    def test_choose_one_detection_matches_official_tag_set(self):
        """判定式 = CardDefs CHOOSE_ONE tag 等价集（XML 核对快照，
        36.2.2 基线; 文本提及型/Spellcraft 宿主排除）。"""
        game = make_game()
        positive = ["BG26_355", "BG27_084", "BG30_110", "BG30_117t",
                    "BG30_123", "BG30_128", "BG31_144", "BG31_320",
                    "BG31_325", "BG31_825", "BG31_842", "BG31_880",
                    "BG31_881", "BG31_884", "BG31_886", "BG31_893",
                    "BG32_237", "BG36_330", "BG36_332", "BG36_341"]
        negative = ["BG31_323", "BG31_327", "BG31_329", "BG36_331",
                    "BG31_892", "BG30_117"]
        for cid in positive:
            card = type("C", (), {"card_id": cid})()
            self.assertTrue(_is_choose_one_card(game, card), cid)
        for cid in negative:
            card = type("C", (), {"card_id": cid})()
            self.assertFalse(_is_choose_one_card(game, card), cid)


class TestCraterMiner(unittest.TestCase):
    """BG31_320 — Choose One: Get {0} Blood Gems; or Get a Gem Day."""

    GEMS, GEMDAY = 0, 1

    def test_gems_branch(self):
        game = make_game(seed=400)
        a = game.heroes[0]
        play_choose(game, a, "BG31_320", self.GEMS)
        n = get_db().get("BG31_320").num(0)
        self.assertEqual(hand_ids(a), [GEM_ID] * n)

    def test_gemday_branch_resolves_data_chain(self):
        game = make_game(seed=401)
        a = game.heroes[0]
        play_choose(game, a, "BG31_320", self.GEMDAY)
        self.assertEqual(hand_ids(a), ["BG31_893"])   # evolution 116596 链
        # Gem Day 非池法术——不占法术池
        self.assertEqual(game.spell_pool.available("BG31_893"), 0)

    def test_no_effect_before_choice(self):
        game = make_game(seed=402)
        a = game.heroes[0]
        m = game.create_minion("BG31_320", controller=a)
        hero_add = a.add_to_hand(m)
        self.assertTrue(hero_add)
        self.assertTrue(game.play_minion(a, m))
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "choose_one")
        self.assertEqual(pc.options, ["gems", "gemday"])
        self.assertEqual(hand_ids(a), [])             # 选择前无效果
        self.assertEqual(a.board[-1], m)              # 官方顺序: 先入场

    def test_golden_totals(self):
        db = get_db()
        for idx, expect in ((self.GEMS, [GEM_ID] * db.get("BG31_320_G").num(0)),
                            (self.GEMDAY, ["BG31_893"] * 2)):
            game = make_game(seed=403)
            a = game.heroes[0]
            play_choose(game, a, "BG31_320", idx, golden=True)
            self.assertEqual(hand_ids(a), expect)


class TestSlyInfiltrator(unittest.TestCase):
    """BG36_330 — Choose One: Gain {0} free Refreshes; or Get {1} Blood Gems."""

    REFRESHES, GEMS = 0, 1

    def test_free_refreshes_branch(self):
        game = make_game(seed=410)
        a = game.heroes[0]
        a.gold = 10
        play_choose(game, a, "BG36_330", self.REFRESHES)
        n = get_db().get("BG36_330").num(0)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), n)
        game.refresh_tavern(a)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), n - 1)
        self.assertEqual(a.gold, 10)                  # 免费次数优先于金币

    def test_gems_branch(self):
        game = make_game(seed=411)
        a = game.heroes[0]
        play_choose(game, a, "BG36_330", self.GEMS)
        n = get_db().get("BG36_330").num(1)
        self.assertEqual(hand_ids(a), [GEM_ID] * n)

    def test_golden_totals(self):
        db = get_db()
        g = db.get("BG36_330_G")
        game = make_game(seed=412)
        a = game.heroes[0]
        play_choose(game, a, "BG36_330", self.REFRESHES, golden=True)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), g.num(0))
        game2 = make_game(seed=413)
        a2 = game2.heroes[0]
        play_choose(game2, a2, "BG36_330", self.GEMS, golden=True)
        self.assertEqual(hand_ids(a2), [GEM_ID] * g.num(1))


class TestSnareTrapper(unittest.TestCase):
    """BG36_332 — Choose One: Get a random Quilboar; or +{0} max Gold."""

    QUILBOAR, MAXGOLD = 0, 1

    def test_quilboar_branch(self):
        game = make_game(seed=420)
        a = game.heroes[0]

        def pool_total():
            return sum(game.minion_pool.available(d.id)
                       for d in get_db().pool_minions())

        before = pool_total()
        play_choose(game, a, "BG36_332", self.QUILBOAR)
        self.assertEqual(len(a.hand), 1)
        m = a.hand[0]
        self.assertIn(m.race, (Race.QUILBOAR, Race.ALL))
        self.assertEqual(pool_total(), before - 1)   # 占池（P2）

    def test_maxgold_branch(self):
        game = make_game(seed=421)
        a = game.heroes[0]
        base_cap = a.income_cap
        play_choose(game, a, "BG36_332", self.MAXGOLD)
        n = get_db().get("BG36_332").num(0)
        self.assertEqual(a.income_cap, base_cap + n)  # Strike Oil 同构

    def test_golden_maxgold(self):
        game = make_game(seed=422)
        a = game.heroes[0]
        base_cap = a.income_cap
        play_choose(game, a, "BG36_332", self.MAXGOLD, golden=True)
        self.assertEqual(a.income_cap,
                         base_cap + get_db().get("BG36_332_G").num(0))


class TestVeteranBrigand(unittest.TestCase):
    """BG36_341 — Choose One: {0} Blood Gems on all your minions; or
    cast Blood Gem Barrage {1} times."""

    GEMS, BARRAGE = 0, 1

    def _barrage_def(self):
        db = get_db()
        return db.by_dbf(db.get("BG36_341").evolution_card_id)

    def test_gems_branch_all_friendly_minions(self):
        game = make_game(seed=430)
        a = game.heroes[0]
        dummy1 = make_minion("D1", 1, 1)
        game.summon(a, dummy1)
        dummy2 = make_minion("D2", 2, 2)
        game.summon(a, dummy2)
        brig = play_choose(game, a, "BG36_341", self.GEMS)
        n = get_db().get("BG36_341").num(0)
        gem_atk = get_db().get(GEM_ID).num(0)
        gem_hp = get_db().get(GEM_ID).num(1)
        for m in (dummy1, dummy2, brig):              # 含 Brigand 自身
            self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), n)
        self.assertEqual(dummy1.atk, 1 + gem_atk * n)
        self.assertEqual(dummy1.max_health, 1 + gem_hp * n)
        self.assertEqual(dummy2.atk, 2 + gem_atk * n)
        self.assertEqual(brig.atk, get_db().get("BG36_341").atk + gem_atk * n)

    def test_barrage_branch_buffs_tavern_on_refresh(self):
        game = make_game(seed=431)
        a = game.heroes[0]
        a.gold = 10
        play_choose(game, a, "BG36_341", self.BARRAGE)
        casts = get_db().get("BG36_341").num(1)
        bd = self._barrage_def()
        game.refresh_tavern(a)
        offers = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(offers)                       # T1 馆内有随从
        for m in offers:
            d = get_db().get(m.card_id)
            self.assertEqual(m.atk, d.atk + bd.num(0) * casts, m.card_id)
            self.assertEqual(m.max_health, d.health + bd.num(1) * casts)
            self.assertTrue(any(b.gem for b in m._buffs))
        # "this game": 卖出 Brigand 后仍生效（新一批馆内随从再 +1 轮）
        game.sell_minion(a, a.board[0])
        game.refresh_tavern(a)
        offers = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(offers)
        for m in offers:
            d = get_db().get(m.card_id)
            self.assertEqual(m.atk, d.atk + bd.num(0) * casts)

    def test_golden_barrage_six_casts(self):
        game = make_game(seed=432)
        a = game.heroes[0]
        a.gold = 10
        play_choose(game, a, "BG36_341", self.BARRAGE, golden=True)
        bd = self._barrage_def()
        casts = get_db().get("BG36_341_G").num(1)     # 6 = 2 触发 × 基础 3
        game.refresh_tavern(a)
        offers = [m for m in a.tavern if isinstance(m, Minion)]
        self.assertTrue(offers)
        for m in offers:
            d = get_db().get(m.card_id)
            self.assertEqual(m.atk, d.atk + bd.num(0) * casts)

    def test_opponent_refresh_not_affected(self):
        game = make_game(seed=433)
        a, b = game.heroes
        a.gold = 10
        b.gold = 10
        play_choose(game, a, "BG36_341", self.BARRAGE)
        bd = self._barrage_def()
        game.refresh_tavern(b)                        # 对手刷新
        for m in b.tavern:
            if not isinstance(m, Minion):
                continue
            d = get_db().get(m.card_id)
            self.assertEqual(m.atk, d.atk)            # 无 Barrage 增益


class TestTurboHogrider(unittest.TestCase):
    """BG31_323 — After you play a Choose One card, plays a Blood Gem on
    all your other Quilboar."""

    def _setup(self, seed, golden=False):
        game = make_game(seed=seed)
        a = game.heroes[0]
        hog = put(game, "BG31_323", a, golden=golden)
        boar = make_minion("Boar", 1, 1, race=Race.QUILBOAR)
        game.summon(a, boar)
        elf = make_minion("Elf", 1, 1, race=Race.ELEMENTAL)
        game.summon(a, elf)
        return game, a, hog, boar, elf

    def test_triggers_on_choose_one_play(self):
        game, a, hog, boar, elf = self._setup(440)
        gem_atk = get_db().get(GEM_ID).num(0)
        times = REGISTRY["BG31_323"].times
        play_choose(game, a, "BG31_320", 0)           # 任一 Choose One 卡
        self.assertEqual(boar.atk, 1 + gem_atk * times)
        self.assertEqual(elf.atk, 1)                  # 非 Quilboar 不触发
        self.assertEqual(hog.atk, get_db().get("BG31_323").atk)  # 自身排除

    def test_choose_one_spell_play_triggers(self):
        game, a, hog, boar, elf = self._setup(441)
        # Choose One 池法术（BG31_881 Time Management，spells4 手动
        # 选择协议）打出同样触发——引擎 play_spell 尾部广播
        # card_played(card=spell)（game.py:791）
        spell = game.create_spell("BG31_881", controller=a)
        a.add_to_hand(spell)
        self.assertTrue(game.play_spell(a, spell))
        if game.pending_choices:                      # spells4 手动选择
            game.pending_choices.pop(0).choose(0)
        # Time Management 自身也 buff 随从——以宝石记账断言（每颗 gem=True
        # buff 计 1，GEMS_PLAYED_ON 为两路径统一数据源）
        times = REGISTRY["BG31_323"].times
        self.assertEqual(boar.get(GameTag.GEMS_PLAYED_ON), times)
        self.assertEqual(elf.get(GameTag.GEMS_PLAYED_ON), 0)
        self.assertTrue(any(b.gem for b in boar._buffs))

    def test_non_choose_one_card_does_not_trigger(self):
        game, a, hog, boar, elf = self._setup(442)
        GetBloodGems(a, 1).do(game)
        gem = a.hand[0]
        game.play_spell(a, gem, target=boar)          # 血宝石非 Choose One
        self.assertEqual(elf.atk, 1)
        self.assertEqual(boar.atk, 1 + get_db().get(GEM_ID).num(0))

    def test_another_hogrider_does_not_trigger(self):
        game, a, hog, boar, elf = self._setup(443)
        before = boar.atk
        hog2 = game.create_minion("BG31_323", controller=a)
        a.add_to_hand(hog2)
        game.play_minion(a, hog2)                     # 提及型卡不计
        self.assertEqual(boar.atk, before)

    def test_golden_two_gems(self):
        game, a, hog, boar, elf = self._setup(444, golden=True)
        play_choose(game, a, "BG31_320", 0)
        gem_atk = get_db().get(GEM_ID).num(0)
        self.assertEqual(boar.atk, 1 + gem_atk * 2)


class TestThornedTrailblazer(unittest.TestCase):
    """BG31_327 — One Choose One card each turn has both effects
    combined.（wiki "(1 left!)"/金色 "(2 left!)" → 每回合计数器）"""

    def _play_miner(self, game, a):
        m = game.create_minion("BG31_320", controller=a)
        a.add_to_hand(m)
        return game.play_minion(a, m)

    def test_first_choose_one_each_turn_dual(self):
        game = make_game(seed=450)
        a = game.heroes[0]
        put(game, "BG31_327", a)
        self.assertTrue(self._play_miner(game, a))
        self.assertEqual(game.pending_choices, [])    # 首张: 不弹选择
        # 双效: 2 gems + 1 Gem Day（入牌顺序无关断言）
        n = get_db().get("BG31_320").num(0)
        self.assertEqual(hand_ids(a).count(GEM_ID), n)
        self.assertEqual(hand_ids(a).count("BG31_893"), 1)

    def test_second_choose_one_same_turn_restores_choice(self):
        game = make_game(seed=453)
        a = game.heroes[0]
        put(game, "BG31_327", a)
        self.assertTrue(self._play_miner(game, a))    # 消耗本回合额度
        self.assertTrue(self._play_miner(game, a))    # 第二张: 恢复选择
        self.assertEqual(game.pending_choices[0].kind, "choose_one")

    def test_counter_resets_next_turn(self):
        game = make_game(seed=454)
        a = game.heroes[0]
        put(game, "BG31_327", a)
        self.assertTrue(self._play_miner(game, a))
        self.assertEqual(game.pending_choices, [])
        game._begin_recruit_for(a)                    # 下一回合开始
        self.assertTrue(self._play_miner(game, a))
        self.assertEqual(game.pending_choices, [])    # 额度已重置

    def test_golden_two_per_turn(self):
        game = make_game(seed=455)
        a = game.heroes[0]
        put(game, "BG31_327", a, golden=True)
        self.assertTrue(self._play_miner(game, a))
        self.assertEqual(game.pending_choices, [])
        self.assertTrue(self._play_miner(game, a))    # 金色: 第 2 张仍双效
        self.assertEqual(game.pending_choices, [])
        self.assertTrue(self._play_miner(game, a))    # 第 3 张: 恢复选择
        self.assertEqual(game.pending_choices[0].kind, "choose_one")

    def test_aura_ends_when_sold(self):
        game = make_game(seed=451)
        a = game.heroes[0]
        trail = put(game, "BG31_327", a)
        game.sell_minion(a, trail)
        m = game.create_minion("BG31_320", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.pending_choices[0].kind, "choose_one")

    def test_non_choose_one_play_unaffected(self):
        game = make_game(seed=452)
        a = game.heroes[0]
        put(game, "BG31_327", a)
        # 非 Choose One 战吼随从照常
        m = game.create_minion("BG32_841", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(
            a.get(GameTag.ELEMENTAL_EXTRA_ATK),
            get_db().get("BG32_841").num(0))


class TestIntrepidBotanist(unittest.TestCase):
    """BG32_237 — Choose One: Tavern spells +1 Attack this game; or
    +1 Health."""

    ATK, HEALTH = 0, 1

    def test_atk_and_health_branches(self):
        db = get_db()
        extra = 1   # 文本字面量 "+1"（无模板参数）
        game = make_game(seed=460)
        a = game.heroes[0]
        play_choose(game, a, "BG32_237", self.ATK)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), extra)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 0)
        game2 = make_game(seed=461)
        a2 = game2.heroes[0]
        play_choose(game2, a2, "BG32_237", self.HEALTH)
        self.assertEqual(a2.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), extra)

    def test_buff_exit_integration(self):
        game = make_game(seed=462)
        a = game.heroes[0]
        dummy = make_minion("D", 1, 1)
        dummy.controller = a
        play_choose(game, a, "BG32_237", self.ATK)
        b = tavern_spell_buff(dummy, 1, 1)            # racefx 统一出口
        self.assertEqual(b.atk, 2)                    # 1 + EXTRA_ATK 1
        self.assertEqual(b.health, 1)

    def test_golden_double(self):
        game = make_game(seed=463)
        a = game.heroes[0]
        play_choose(game, a, "BG32_237", self.ATK, golden=True)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2)  # 2×1


class TestHumongozz(unittest.TestCase):
    """BG32_341 — DS. Your Tavern spells give an extra +1/+2.
    （wiki Full tags AURA=1 → 在场光环，离场撤销）"""

    def test_on_summon_stacks(self):
        game = make_game(seed=470)
        a = game.heroes[0]
        m = put(game, "BG32_341", a)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 2)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))  # CardDef 关键词

    def test_golden_values(self):
        game = make_game(seed=471)
        a = game.heroes[0]
        put(game, "BG32_341", a, golden=True)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 4)

    def test_aura_revoked_when_sold(self):
        game = make_game(seed=472)
        a = game.heroes[0]
        m = put(game, "BG32_341", a)
        game.sell_minion(a, m)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 0)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 0)


class TestEnchantedSentinel(unittest.TestCase):
    """BG35_341 — Magnetic. Your Tavern spells give an extra +{1}/+{2}.
    （wiki Full tags AURA=1 + [Ongoing effect] → 在场光环）"""

    def test_on_summon_indices_one_two(self):
        game = make_game(seed=480)
        a = game.heroes[0]
        d = get_db().get("BG35_341")
        m = put(game, "BG35_341", a)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(1))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), d.num(2))
        self.assertTrue(m.has(GameTag.MAGNETIC))

    def test_golden_reads_own_def(self):
        game = make_game(seed=481)
        a = game.heroes[0]
        d = get_db().get("BG35_341_G")
        put(game, "BG35_341", a, golden=True)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(1))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), d.num(2))

    def test_aura_revoked_when_sold(self):
        game = make_game(seed=482)
        a = game.heroes[0]
        m = put(game, "BG35_341", a)
        game.sell_minion(a, m)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 0)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 0)


class TestSandSwirler(unittest.TestCase):
    """BG32_841 — Battlecry: Your Elementals give an extra +{0} Attack."""

    def _play(self, seed, golden=False):
        game = make_game(seed=seed)
        a = game.heroes[0]
        m = game.create_minion("BG32_841", controller=a, golden=golden)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        return game, a

    def test_battlecry_elemental_extra_atk(self):
        game, a = self._play(490)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK),
                         get_db().get("BG32_841").num(0))

    def test_golden_totals_four(self):
        game, a = self._play(491, golden=True)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK),
                         get_db().get("BG32_841_G").num(0))

    def test_elemental_buff_exit_integration(self):
        from hsrl2.scripts.batches.batch_consume import elemental_buff
        game, a = self._play(492)
        e = make_minion("Elem", 1, 1, race=Race.ELEMENTAL)
        e.controller = a
        b = elemental_buff(e, 1, 1)                   # batch_consume 出口
        self.assertEqual(b.atk, 1 + get_db().get("BG32_841").num(0))
        self.assertEqual(b.health, 1)


class TestLurkingLeviathan(unittest.TestCase):
    """BG35_602 — Whenever you summon a Beast, give it +{1} Attack and
    improve this permanently."""

    def test_progressive_improve(self):
        game = make_game(seed=500)
        a = game.heroes[0]
        put(game, "BG35_602", a)
        n = get_db().get("BG35_602").num(1)
        b1 = make_minion("B1", 1, 1, race=Race.BEAST)
        game.summon(a, b1)
        self.assertEqual(b1.atk, 1 + n)               # 第 1 次: num×1
        b2 = make_minion("B2", 1, 1, race=Race.BEAST)
        game.summon(a, b2)
        self.assertEqual(b2.atk, 1 + n * 2)           # 第 2 次: num×2

    def test_non_beast_and_self_excluded(self):
        game = make_game(seed=501)
        a = game.heroes[0]
        lev = put(game, "BG35_602", a)                # 自身是 Beast
        self.assertEqual(lev.atk, get_db().get("BG35_602").atk)
        mech = make_minion("M", 1, 1, race=Race.MECH)
        game.summon(a, mech)
        self.assertEqual(mech.atk, 1)

    def test_opponent_summon_excluded(self):
        game = make_game(seed=502)
        a, b = game.heroes
        put(game, "BG35_602", a)
        beast = make_minion("OB", 1, 1, race=Race.BEAST)
        game.summon(b, beast)
        self.assertEqual(beast.atk, 1)

    def test_golden_reads_own_def(self):
        game = make_game(seed=503)
        a = game.heroes[0]
        put(game, "BG35_602", a, golden=True)
        n = get_db().get("BG35_602_G").num(1)
        b1 = make_minion("B1", 1, 1, race=Race.BEAST)
        game.summon(a, b1)
        self.assertEqual(b1.atk, 1 + n)
        b2 = make_minion("B2", 1, 1, race=Race.BEAST)
        game.summon(a, b2)
        self.assertEqual(b2.atk, 1 + n * 2)


class TestRimescalePriestessAmbiguous(unittest.TestCase):
    """BG33_319 — AMBIGUOUS（候选集无权威分类）: 未注册即正确状态。"""

    def test_not_registered(self):
        self.assertNotIn("BG33_319", REGISTRY)
        self.assertNotIn("BG33_319_G", REGISTRY)

    def test_data_chain_intact_for_unfreeze(self):
        d = get_db().get("BG33_319")
        self.assertIsNotNone(d.spellcraft_id)         # 122259 法术链完好


if __name__ == "__main__":
    unittest.main()
