"""批次 eot_sot 卡牌语义测试（作业单 2026-08-21，11 张 EoT 池随从）。

覆盖: BG26_152 Utility Drone / BG28_595 Ignition Specialist /
BG31_326 Gem Rat / BG32_235 Surfing Sylvar / BG32_821 Felfire Conjurer /
BG32_837 Fauna Whisperer / BG34_145 Futurefin / BG34_684 Trench Fighter /
BG35_123 Cataclysmic Harbinger / BG35_142 Cousin Errgl / BG36_764 Gearfin
（含金色）。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）; 文本无占位符的卡用
文本字面量并注明。EoT 触发方式: game.run_script_hook(m, "end_of_turn")。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.constants import HAND_SIZE, POOL_COPIES_BY_TIER
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.pools import SpellPool
from hsrl2.scripts import REGISTRY
from hsrl2.tags import Race, Zone

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
    """创建随从（REGISTRY 脚本绑定由 create_minion 完成）→ 召唤。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def summon_plain(game: Game, hero: Hero, m: Minion,
                 position: int | None = None) -> Minion:
    game.summon(hero, m, position)
    return m


def find_plain(db, *, tier: int | None = None):
    """无任何效果关键词、有金色定义的池随从（金色计数测试靶）。"""
    for d in sorted(db.pool_minions(), key=lambda x: x.id):
        if tier is not None and d.tech_level != tier:
            continue
        if d.keywords:
            continue
        if db.golden_version(d) is None:
            continue
        return d
    raise AssertionError("no plain pool card with golden def")


def drain_spell_pool(game: Game, *, cost: int | None = None) -> None:
    """排空（指定费用的）酒馆法术池。"""
    for d in game.db.pool_spells():
        if cost is not None and d.cost != cost:
            continue
        while game.spell_pool.acquire(d.id):
            pass


def play_pool_spell(game: Game, hero: Hero, card_id: str):
    """模拟"购买并施放"一个池法术: acquire → 入手 → play_spell
    （施放后引擎自动 release 回池）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    assert game.play_spell(hero, s)
    return s


class TestRegistryState(unittest.TestCase):
    """批次注册面: 11 卡 + 金色全部注册。"""

    def test_all_cards_registered(self):
        for cid in ("BG26_152", "BG26_152_G", "BG28_595", "BG28_595_G",
                    "BG31_326", "BG31_326_G", "BG32_235", "BG32_235_G",
                    "BG32_821", "BG32_821_G", "BG32_837", "BG32_837_G",
                    "BG34_145", "BG34_145_G", "BG34_684", "BG34_684_G",
                    "BG35_123", "BG35_123_G", "BG35_142", "BG35_142_G",
                    "BG36_764", "BG36_764_G"):
            self.assertIn(cid, REGISTRY)


class TestUtilityDrone(unittest.TestCase):
    """BG26_152 — EoT: 每随从按磁力吸附数 +num(0)/num(1)。"""

    def test_buffs_per_magnetization(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG26_152")
        drone = put(game, "BG26_152", a)
        mech = summon_plain(game, a, make_minion("M", 2, 3, race=Race.MECH))
        plain = summon_plain(game, a, make_minion("P", 5, 5))
        game._magnetic_stack[mech.uuid] = ["BG_BOT_312t", "BG_BOT_314t"]
        game.run_script_hook(drone, "end_of_turn")
        # 2 吸附 × num(0)/num(1)
        self.assertEqual(mech.atk, 2 + d.num(0) * 2)
        self.assertEqual(mech.max_health, 3 + d.num(1) * 2)
        # 负例: 无吸附随从（含无人机自身）不变
        self.assertEqual(plain.atk, 5)
        self.assertEqual(plain.max_health, 5)
        self.assertEqual(drone.atk, d.atk)
        self.assertEqual(drone.max_health, d.health)

    def test_golden_uses_golden_nums(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        gd = get_db().get("BG26_152_G")
        drone = put(game, "BG26_152", a, golden=True)
        mech = summon_plain(game, a, make_minion("M", 0, 1, race=Race.MECH))
        game._magnetic_stack[mech.uuid] = ["X"]
        game.run_script_hook(drone, "end_of_turn")
        self.assertEqual(mech.atk, 0 + gd.num(0))
        self.assertEqual(mech.max_health, 1 + gd.num(1))


class TestIgnitionSpecialist(unittest.TestCase):
    """BG28_595 — EoT: get 2 random Tavern spells（占池）。"""

    def test_gets_two_random_pool_spells(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        snap = {d.id: game.spell_pool.available(d.id)
                for d in game.db.pool_spells()}
        spec = put(game, "BG28_595", a)
        game.run_script_hook(spec, "end_of_turn")
        ids = [c.card_id for c in a.hand]
        self.assertEqual(len(ids), 2)                     # 文本字面量 2
        for cid in ids:   # 多副本池 → 两次独立抽取可同卡
            self.assertIn(cid, [d.id for d in game.db.pool_spells()])
            self.assertEqual(game.spell_pool.available(cid),
                             snap[cid] - ids.count(cid))  # 每张占 1 份

    def test_golden_gets_four(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        spec = put(game, "BG28_595", a, golden=True)
        game.run_script_hook(spec, "end_of_turn")
        self.assertEqual(len(a.hand), 4)                  # 金色文本字面量 4

    def test_empty_pool_yields_nothing(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        drain_spell_pool(game)
        spec = put(game, "BG28_595", a)
        game.run_script_hook(spec, "end_of_turn")
        self.assertEqual(len(a.hand), 0)                  # 池空落空


class TestGemRat(unittest.TestCase):
    """BG31_326 — EoT: get a Gem Day（数据链、非池卡不占池）。"""

    def _gem_day_id(self) -> str:
        d = get_db().get("BG31_326")
        return get_db().by_dbf(d.evolution_card_id).id

    def test_gets_one_gem_day(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        rat = put(game, "BG31_326", a)
        gid = self._gem_day_id()
        self.assertFalse(get_db().get(gid).is_pool_spell)  # 非池卡
        game.run_script_hook(rat, "end_of_turn")
        self.assertEqual([c.card_id for c in a.hand], [gid])

    def test_golden_gets_two(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        rat = put(game, "BG31_326", a, golden=True)
        gid = self._gem_day_id()
        game.run_script_hook(rat, "end_of_turn")
        self.assertEqual([c.card_id for c in a.hand], [gid, gid])

    def test_full_hand_queues_not_destroys(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        for _ in range(HAND_SIZE):
            filler = make_minion("F", 1, 1)
            a.hand.append(filler)
        rat = put(game, "BG31_326", a)
        game.run_script_hook(rat, "end_of_turn")
        self.assertEqual(len(a.hand), HAND_SIZE)          # 不溢出
        self.assertEqual(len(game.pending_hand_queue), 1)  # P6 排队


class TestSurfingSylvar(unittest.TestCase):
    """BG32_235 — EoT: 相邻 +num(0) Atk × (1+金色随从数)。"""

    def test_no_golden_single_application(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG32_235")
        m1 = summon_plain(game, a, make_minion("L", 1, 1))
        sylvar = put(game, "BG32_235", a)
        m2 = summon_plain(game, a, make_minion("R", 2, 2))
        far = summon_plain(game, a, make_minion("Far", 7, 7))
        game.run_script_hook(sylvar, "end_of_turn")
        self.assertEqual(m1.atk, 1 + d.num(0))
        self.assertEqual(m2.atk, 2 + d.num(0))
        # 负例: 自身与远端不变; 不加生命
        self.assertEqual(sylvar.atk, d.atk)
        self.assertEqual(far.atk, 7)
        self.assertEqual(m1.max_health, 1)

    def test_repeats_for_each_friendly_golden(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        d = get_db().get("BG32_235")
        plain = find_plain(get_db())
        m1 = summon_plain(game, a, make_minion("L", 1, 1))
        sylvar = put(game, "BG32_235", a)
        m2 = summon_plain(game, a, make_minion("R", 2, 2))
        g1 = put(game, plain.id, a, golden=True)
        g2 = put(game, plain.id, a, golden=True)
        self.assertTrue(g1.is_golden and g2.is_golden)
        g1_before = (g1.atk, g1.max_health)
        game.run_script_hook(sylvar, "end_of_turn")
        # 1 + 2 金色 = 3 次; 相邻 m1/m2 各 +num(0)×3
        self.assertEqual(m1.atk, 1 + d.num(0) * 3)
        self.assertEqual(m2.atk, 2 + d.num(0) * 3)
        self.assertEqual((g1.atk, g1.max_health), g1_before)  # 远端不吃

    def test_golden_sylvar_double_value(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        gd = get_db().get("BG32_235_G")
        m1 = summon_plain(game, a, make_minion("L", 1, 1))
        sylvar = put(game, "BG32_235", a, golden=True)
        game.run_script_hook(sylvar, "end_of_turn")
        # 金色自身计入 friendly Golden → 1+1=2 次 × num(0)=2
        self.assertEqual(m1.atk, 1 + gd.num(0) * 2)


class TestFelfireConjurer(unittest.TestCase):
    """BG32_821 — EoT: TAVERN_SPELL_EXTRA_* 叠加 num(0)/num(1)。"""

    def test_accumulates_each_turn(self):
        from hsrl2.tags import GameTag
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG32_821")
        conjurer = put(game, "BG32_821", a)
        # 负例: 触发前 tag 为 0
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)
        game.run_script_hook(conjurer, "end_of_turn")
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), d.num(0))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), d.num(1))
        game.run_script_hook(conjurer, "end_of_turn")
        # 每回合累积
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), d.num(0) * 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), d.num(1) * 2)

    def test_tavern_spell_buff_consumes_extra(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        d = get_db().get("BG32_821")
        target = summon_plain(game, a, make_minion("T", 1, 1))
        conjurer = put(game, "BG32_821", a)
        game.run_script_hook(conjurer, "end_of_turn")
        buff = tavern_spell_buff(target, 1, 1)
        self.assertEqual(buff.atk, 1 + d.num(0))
        self.assertEqual(buff.health, 1 + d.num(1))

    def test_golden_doubles(self):
        from hsrl2.tags import GameTag
        game = make_game(seed=3)
        a = game.heroes[0]
        gd = get_db().get("BG32_821_G")
        conjurer = put(game, "BG32_821", a, golden=True)
        game.run_script_hook(conjurer, "end_of_turn")
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), gd.num(0))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), gd.num(1))


class TestFaunaWhisperer(unittest.TestCase):
    """BG32_837 — EoT: 对相邻各施放 Natural Blessing（按其文本实现）。"""

    def _nb(self):
        d = get_db().get("BG32_837")
        return get_db().by_dbf(d.evolution_card_id)

    def test_casts_on_each_adjacent(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        nb = self._nb()
        beast1 = summon_plain(game, a, make_minion("B1", 1, 1, race=Race.BEAST))
        fw = put(game, "BG32_837", a)
        beast2 = summon_plain(game, a, make_minion("B2", 2, 2, race=Race.BEAST))
        naga = summon_plain(game, a, make_minion("N", 3, 3, race=Race.NAGA))
        game.run_script_hook(fw, "end_of_turn")
        # 每相邻一次施放: 两兽各吃 2 次 +nb.num
        self.assertEqual(beast1.atk, 1 + nb.num(0) * 2)
        self.assertEqual(beast1.max_health, 1 + nb.num(1) * 2)
        self.assertEqual(beast2.atk, 2 + nb.num(0) * 2)
        self.assertEqual(beast2.max_health, 2 + nb.num(1) * 2)
        # 负例: 不同族（含施法者自身 NAGA）不吃
        self.assertEqual(naga.atk, 3)
        self.assertEqual(fw.max_health, get_db().get("BG32_837").health)

    def test_amalgam_shares_all_types(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        nb = self._nb()
        amalgam = summon_plain(game, a,
                               make_minion("A", 1, 1, race=Race.ALL))
        fw = put(game, "BG32_837", a)
        game.run_script_hook(fw, "end_of_turn")
        # 相邻 Amalgam 为目标: 全体（含 Amalgam 自身）与其共享类型
        self.assertEqual(amalgam.atk, 1 + nb.num(0))
        self.assertEqual(fw.atk, get_db().get("BG32_837").atk + nb.num(0))

    def test_tavern_spell_extra_amplifies(self):
        from hsrl2.tags import GameTag
        game = make_game(seed=3)
        a = game.heroes[0]
        nb = self._nb()
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 1)   # Felfire 类增幅
        beast1 = summon_plain(game, a, make_minion("B1", 1, 1, race=Race.BEAST))
        fw = put(game, "BG32_837", a)
        game.run_script_hook(fw, "end_of_turn")
        # 每次施放 +（nb.num(0)+1）
        self.assertEqual(beast1.atk, 1 + (nb.num(0) + 1))

    def test_golden_casts_twice(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        nb = self._nb()
        beast1 = summon_plain(game, a, make_minion("B1", 1, 1, race=Race.BEAST))
        fw = put(game, "BG32_837", a, golden=True)
        beast2 = summon_plain(game, a, make_minion("B2", 1, 1, race=Race.BEAST))
        game.run_script_hook(fw, "end_of_turn")
        # 2 相邻 × twice = 每兽 4 次
        self.assertEqual(beast1.atk, 1 + nb.num(0) * 4)
        self.assertEqual(beast2.atk, 1 + nb.num(0) * 4)


class TestFuturefin(unittest.TestCase):
    """BG34_145 — EoT: 给手牌最左随从自身 stats。"""

    def test_buffs_leftmost_minion_skipping_spells(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG34_145")
        fin = put(game, "BG34_145", a)
        spell = game.create_spell("BG28_698", controller=a)   # 更靠左的法术
        a.hand.append(spell)
        left = make_minion("L", 2, 3)
        right = make_minion("R", 4, 5)
        a.hand.append(left)
        a.hand.append(right)
        game.run_script_hook(fin, "end_of_turn")
        # stats = atk + max_health（快照语义）
        self.assertEqual(left.atk, 2 + d.atk)
        self.assertEqual(left.max_health, 3 + d.health)
        # 负例: 更左法术与更右随从不动
        self.assertEqual(right.atk, 4)
        self.assertIn(spell, a.hand)

    def test_no_minion_in_hand_whiffs(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        fin = put(game, "BG34_145", a)
        a.hand.append(game.create_spell("BG28_698", controller=a))
        game.run_script_hook(fin, "end_of_turn")
        self.assertEqual(len(a.hand), 1)   # 无新卡、无异常

    def test_golden_doubles_stats(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        d = get_db().get("BG34_145")
        gd = get_db().get("BG34_145_G")
        fin = put(game, "BG34_145", a, golden=True)
        left = make_minion("L", 0, 1)
        a.hand.append(left)
        game.run_script_hook(fin, "end_of_turn")
        # 金色 "double" ×2（金色文本字面量）: 金色 stats ×2
        self.assertEqual(left.atk, 0 + gd.atk * 2)
        self.assertEqual(left.max_health, 1 + gd.health * 2)
        self.assertEqual(gd.atk, d.atk * 2)


class TestTrenchFighter(unittest.TestCase):
    """BG34_684 — EoT: get a Gem Confiscation（池法术 acquire）。"""

    def _gc_id(self) -> str:
        d = get_db().get("BG34_684")
        return get_db().by_dbf(d.evolution_card_id).id

    def test_gets_one_occupying_pool(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        gid = self._gc_id()
        self.assertTrue(get_db().get(gid).is_pool_spell)
        avail = game.spell_pool.available(gid)
        fighter = put(game, "BG34_684", a)
        game.run_script_hook(fighter, "end_of_turn")
        self.assertEqual([c.card_id for c in a.hand], [gid])
        self.assertEqual(game.spell_pool.available(gid),
                         avail - 1)   # 占池

    def test_pool_empty_whiffs(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        gid = self._gc_id()
        while game.spell_pool.available(gid):   # 抽干（per-tier 副本）
            assert game.spell_pool.acquire(gid)
        fighter = put(game, "BG34_684", a)
        game.run_script_hook(fighter, "end_of_turn")
        self.assertEqual(len(a.hand), 0)      # 落空则无（作业单语义）

    def test_golden_second_copy_from_pool(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        gid = self._gc_id()
        avail = game.spell_pool.available(gid)
        fighter = put(game, "BG34_684", a, golden=True)
        game.run_script_hook(fighter, "end_of_turn")
        # 金色 "Get 2": 两枚均自池 acquire（per-tier 副本充足，
        # 旧单副本模型的"第 2 枚落空"缺口随池模型修正自然消除）
        self.assertEqual([c.card_id for c in a.hand], [gid, gid])
        self.assertEqual(game.spell_pool.available(gid), avail - 2)


class TestCataclysmicHarbinger(unittest.TestCase):
    """BG35_123 — EoT: get a copy of the last Tavern spell you cast。"""

    def test_gets_copy_of_last_cast_spell(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        harb = put(game, "BG35_123", a)   # on_summon 注册监听器
        # 未注册脚本的池法术（无副作用）——BG28_698 已由 batch_unfreeze
        # 解冻（Gem Confiscation 定向法术），换 BG31_243 作惰性靶
        sid = "BG31_243"
        cap = SpellPool.POOL_COPIES_BY_TIER[get_db().get(sid).tech_level]
        play_pool_spell(game, a, sid)
        self.assertEqual(game.spell_pool.available(sid), cap)  # 施放后回池
        game.run_script_hook(harb, "end_of_turn")
        self.assertEqual([c.card_id for c in a.hand], [sid])
        # 副本不占池（copy 语义）
        self.assertEqual(game.spell_pool.available(sid), cap)

    def test_no_cast_whiffs(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        harb = put(game, "BG35_123", a)
        game.run_script_hook(harb, "end_of_turn")
        self.assertEqual(len(a.hand), 0)

    def test_opponent_cast_not_tracked(self):
        game = make_game(seed=3)
        a, b = game.heroes
        harb = put(game, "BG35_123", a)
        play_pool_spell(game, b, "BG31_243")   # 对手施放
        game.run_script_hook(harb, "end_of_turn")
        self.assertEqual(len(a.hand), 0)

    def test_golden_gets_two_copies(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        harb = put(game, "BG35_123", a, golden=True)
        sid = "BG31_243"
        play_pool_spell(game, a, sid)
        game.run_script_hook(harb, "end_of_turn")
        self.assertEqual([c.card_id for c in a.hand], [sid, sid])
        self.assertEqual(
            game.spell_pool.available(sid),
            SpellPool.POOL_COPIES_BY_TIER[get_db().get(sid).tech_level])


class TestCousinErrgl(unittest.TestCase):
    """BG35_142 — EoT: get a Mama Mrrglton or a Papa Mrrglton。"""

    def _mama_id(self) -> str:
        d = get_db().get("BG35_142")
        return get_db().by_dbf(d.evolution_card_id).id

    def _papa_id(self) -> str:
        return "BG35_141"

    def test_gets_one_of_the_pair(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        mama, papa = self._mama_id(), self._papa_id()
        errgl = put(game, "BG35_142", a)
        game.run_script_hook(errgl, "end_of_turn")
        self.assertEqual(len(a.hand), 1)
        got = a.hand[0].card_id
        self.assertIn(got, (mama, papa))
        # 50/50 中选者占池（tier3 池副本数 - 1）
        tier = get_db().get(got).tech_level
        self.assertEqual(game.minion_pool.available(got),
                         POOL_COPIES_BY_TIER[tier] - 1)
        other = papa if got == mama else mama
        self.assertEqual(game.minion_pool.available(other),
                         POOL_COPIES_BY_TIER[get_db().get(other).tech_level])

    def test_golden_gets_both(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        mama, papa = self._mama_id(), self._papa_id()
        errgl = put(game, "BG35_142", a, golden=True)
        game.run_script_hook(errgl, "end_of_turn")
        self.assertEqual({c.card_id for c in a.hand}, {mama, papa})

    def test_both_pools_drained_whiffs(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        for cid in (self._mama_id(), self._papa_id()):
            while game.minion_pool.acquire(cid):
                pass
        errgl = put(game, "BG35_142", a)
        game.run_script_hook(errgl, "end_of_turn")
        self.assertEqual(len(a.hand), 0)


class TestGearfin(unittest.TestCase):
    """BG36_764 — EoT: get two 1-Cost Tavern spells。"""

    def test_gets_two_one_cost_spells(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        snap = {d.id: game.spell_pool.available(d.id)
                for d in game.db.pool_spells() if d.cost == 1}
        fin = put(game, "BG36_764", a)
        game.run_script_hook(fin, "end_of_turn")
        ids = [c.card_id for c in a.hand]
        self.assertEqual(len(ids), 2)                     # 文本字面量 2
        for cid in ids:   # 多副本池 → 两次独立抽取可同卡
            self.assertEqual(get_db().get(cid).cost, 1)   # 1-Cost
            self.assertEqual(game.spell_pool.available(cid),
                             snap[cid] - ids.count(cid))  # 每张占 1 份

    def test_one_cost_drained_whiffs_despite_other_spells(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        drain_spell_pool(game, cost=1)
        # 负例前置: 池内仍有非 1 费法术
        self.assertTrue(any(
            game.spell_pool.available(d.id) > 0
            for d in game.db.pool_spells() if d.cost != 1))
        fin = put(game, "BG36_764", a)
        game.run_script_hook(fin, "end_of_turn")
        self.assertEqual(len(a.hand), 0)

    def test_golden_gets_four(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        fin = put(game, "BG36_764", a, golden=True)
        game.run_script_hook(fin, "end_of_turn")
        self.assertEqual(len(a.hand), 4)                  # 金色文本字面量 4


if __name__ == "__main__":
    unittest.main()
