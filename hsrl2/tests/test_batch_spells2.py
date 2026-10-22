"""批次 spells2 卡牌语义测试（作业单 2026-08-21，13 张池法术）。

覆盖: BG28_604 Butchering / BG28_606 Spitescale Special / BG28_607
Corrupted Cupcakes / BG28_800 Careful Investment / BG28_810 Tavern
Coin / BG28_825 Defender's Rites / BG28_827 Leaf Through the Pages /
BG28_830 Golden Touch / BG28_838 Perfect Vision / BG28_845 Natural
Blessing。
DEFERRED（不注册即正确状态）: BG28_698 Gem Confiscation /
BG28_805 Strike Oil / BG28_849 Saloon's Finest。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）; 文本无占位符的卡
用文本字面量并注明。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.constants import gold_base_income
from hsrl2.db import CardDB
from hsrl2.entity import Buff
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

BUTCHERING = "BG28_604"
SPITESCALE = "BG28_606"
CUPCAKES = "BG28_607"
CAREFUL_INVESTMENT = "BG28_800"
TAVERN_COIN = "BG28_810"
DEFENDERS_RITES = "BG28_825"
LEAF_THROUGH = "BG28_827"
GOLDEN_TOUCH = "BG28_830"
PERFECT_VISION = "BG28_838"
NATURAL_BLESSING = "BG28_845"

PLAIN_UNDEAD = "BG25_013"     # Rot Hide Gnoll 1/4 T1（无效果关键词池卡）


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


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def summon(game: Game, hero: Hero, m: Minion) -> Minion:
    game.summon(hero, m)
    return m


def hand_minion(hero: Hero, m: Minion) -> Minion:
    m.controller = hero
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def tavern_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    """池占位 + 创建入馆（池守恒: 先 acquire）。"""
    assert game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def play_pool_spell(game: Game, hero: Hero, card_id: str,
                    target=None) -> bool:
    """占池 → 入手 → 施放（引擎 play_spell 定向协议）。"""
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return game.play_spell(hero, s, target=target)


def goldenizable_pool_defs(db: CardDB, n: int) -> list:
    """有金色卡定义的池随从定义（Golden Touch 测试靶，按 id 稳定排序）。"""
    out = []
    for d in sorted(db.pool_minions(), key=lambda x: x.id):
        if db.golden_version(d) is not None:
            out.append(d)
        if len(out) >= n:
            break
    assert len(out) == n
    return out


def spellcraft_chain_ids(db: CardDB) -> set[str]:
    """Spellcraft 法术数据链（池随从 spellcraft_id → 法术定义）。"""
    ids = set()
    for d in db.pool_minions():
        if d.spellcraft_id is not None:
            t = db.by_dbf(d.spellcraft_id)
            if t is not None:
                ids.add(t.id)
    return ids


class TestRegistryState(unittest.TestCase):
    """批次注册面: 10 卡 OK; 3 张 DEFERRED 不注册。"""

    def test_all_ok_cards_registered(self):
        for cid in (BUTCHERING, SPITESCALE, CUPCAKES, CAREFUL_INVESTMENT,
                    TAVERN_COIN, DEFENDERS_RITES, LEAF_THROUGH, GOLDEN_TOUCH,
                    PERFECT_VISION, NATURAL_BLESSING):
            self.assertIn(cid, REGISTRY)

    def test_deferred_state_2026_08_22(self):
        # Strike Oil/Saloon's Finest 已由 batch_misc 解冻（income_cap 与
        # spells_only 引擎支持）; Gem Confiscation 已由 batch_unfreeze
        # 解冻（GEMS_PLAYED_ON 记账 + StealBloodGems 移转原语就绪）
        self.assertIn("BG28_805", REGISTRY)
        self.assertIn("BG28_849", REGISTRY)
        self.assertIn("BG28_698", REGISTRY)


class TestButchering(unittest.TestCase):
    """BG28_604 — Destroy a friendly Undead; Undead +{0} Attack aura。"""

    def _undead(self, game, hero):
        avail_before = game.minion_pool.available(PLAIN_UNDEAD)
        assert game.minion_pool.acquire(PLAIN_UNDEAD)
        m = game.create_minion(PLAIN_UNDEAD, controller=hero)
        game.summon(hero, m)
        return m, avail_before

    def test_destroy_then_undead_attack_aura_wherever(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get(BUTCHERING)
        undead, avail_before = self._undead(game, a)
        hand_undead = hand_minion(a, make_minion("HU", 2, 3,
                                                 race=Race.UNDEAD))
        beast = summon(game, a, make_minion("Z", 2, 2, race=Race.BEAST))
        deaths = []
        game.events.register(Listener(
            event="death", owner=beast,
            callback=lambda g, minion=None, **kw: deaths.append(minion)))
        self.assertTrue(play_pool_spell(game, a, BUTCHERING))
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "spell_target")
        self.assertIn(undead, pc.options)
        self.assertNotIn(beast, pc.options)          # 仅 Undead 候选
        pc.choose(pc.options.index(undead))
        # 完整死亡链: death 事件、GRAVEYARD、招募期回池
        self.assertEqual(deaths, [undead])
        self.assertEqual(undead.zone, Zone.GRAVEYARD)
        self.assertNotIn(undead, a.board)
        self.assertEqual(game.minion_pool.available(PLAIN_UNDEAD),
                         avail_before)               # 招募期死亡回池
        # 光环: 棋盘外（手牌）Undead 同享（"wherever they are"）;
        # 非 Undead 不受影响
        self.assertEqual(getattr(a, "race_auras", {}).get(Race.UNDEAD),
                         (d.num(0), 0))
        self.assertEqual(hand_undead.atk, 2 + d.num(0))
        self.assertEqual(beast.atk, 2)
        self.assertEqual([c for c in a.hand
                          if c.card_id == BUTCHERING], [])  # 法术已消耗

    def test_amalgam_counts_as_undead_candidate(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        amalgam = summon(game, a, make_minion("A", 1, 1, race=Race.ALL))
        self.assertTrue(play_pool_spell(game, a, BUTCHERING))
        pc = game.pending_choices[0]
        self.assertEqual(pc.options, [amalgam])
        pc.choose(0)
        self.assertEqual(amalgam.zone, Zone.GRAVEYARD)  # ALL 可被摧毁

    def test_no_undead_fizzle_spell_consumed(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        beast = summon(game, a, make_minion("Z", 2, 2, race=Race.BEAST))
        self.assertTrue(play_pool_spell(game, a, BUTCHERING))
        self.assertEqual(game.pending_choices, [])   # 无候选 → 落空
        self.assertEqual(getattr(a, "race_auras", {}), {})   # 不施光环
        self.assertEqual(beast.health, 2)            # 无事发生
        self.assertEqual(a.hand, [])                 # 法术照常消耗


class TestSpitescaleSpecial(unittest.TestCase):
    """BG28_606 — Get 3 random Spellcraft spells（不同 3 张）。"""

    def test_gets_three_distinct_spellcraft_spells(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        chain = spellcraft_chain_ids(get_db())
        self.assertGreaterEqual(len(chain), 3)       # 数据前提: ≥3 张
        self.assertTrue(play_pool_spell(game, a, SPITESCALE))
        self.assertEqual(len(a.hand), 3)             # "3"（文本字面量）
        ids = [s.card_id for s in a.hand]
        self.assertEqual(len(set(ids)), 3)           # 互不相同
        for s in a.hand:
            self.assertIn(s.card_id, chain)          # 均在数据链内
            self.assertTrue(s.has(GameTag.SPELLCRAFT))  # 回合末丢弃协议

    def test_not_pool_spells_no_spell_pool_accounting(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        self.assertTrue(play_pool_spell(game, a, SPITESCALE))
        for s in a.hand:
            self.assertFalse(get_db().get(s.card_id).is_pool_spell)


class TestCorruptedCupcakes(unittest.TestCase):
    """BG28_607 — Choose a friendly Demon; it consumes 3 random Tavern
    minions。"""

    def _tavern_fodder(self, game, hero, n):
        return [tavern_minion(game, hero, PLAIN_UNDEAD) for _ in range(n)]

    def test_demon_consumes_three_tavern_minions(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        fd = get_db().get(PLAIN_UNDEAD)
        demon = summon(game, a, make_minion("D", 2, 3, race=Race.DEMON))
        beast = summon(game, a, make_minion("Z", 4, 4, race=Race.BEAST))
        self._tavern_fodder(game, a, 3)
        avail = game.minion_pool.available(PLAIN_UNDEAD)
        self.assertTrue(play_pool_spell(game, a, CUPCAKES))
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "spell_target")
        self.assertIn(demon, pc.options)
        self.assertNotIn(beast, pc.options)          # 仅 Demon 候选
        pc.choose(pc.options.index(demon))
        # 3 连吞: atk/max_health 快照并入; 馆清空; 酒馆来源回池
        self.assertEqual(demon.atk, 2 + 3 * fd.atk)
        self.assertEqual(demon.max_health, 3 + 3 * fd.health)
        self.assertEqual([m for m in a.tavern
                          if isinstance(m, Minion)], [])
        self.assertEqual(game.minion_pool.available(PLAIN_UNDEAD),
                         avail + 3)

    def test_tavern_with_fewer_than_three_consumes_what_exists(self):
        game = make_game(seed=7)
        a = game.heroes[0]
        fd = get_db().get(PLAIN_UNDEAD)
        demon = summon(game, a, make_minion("D", 2, 3, race=Race.DEMON))
        self._tavern_fodder(game, a, 1)
        self.assertTrue(play_pool_spell(game, a, CUPCAKES))
        pc = game.pending_choices[0]
        pc.choose(pc.options.index(demon))
        self.assertEqual(demon.atk, 2 + fd.atk)      # 只吞到 1 个，不抛错
        self.assertEqual(demon.max_health, 3 + fd.health)

    def test_no_demon_fizzle_tavern_untouched(self):
        game = make_game(seed=8)
        a = game.heroes[0]
        summon(game, a, make_minion("Z", 4, 4, race=Race.BEAST))
        self._tavern_fodder(game, a, 3)
        avail = game.minion_pool.available(PLAIN_UNDEAD)
        self.assertTrue(play_pool_spell(game, a, CUPCAKES))
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(len([m for m in a.tavern
                              if isinstance(m, Minion)]), 3)
        self.assertEqual(game.minion_pool.available(PLAIN_UNDEAD), avail)


class TestCarefulInvestment(unittest.TestCase):
    """BG28_800 — Gain 2 Gold next turn。"""

    def test_gold_deferred_to_next_turn(self):
        game = make_game(seed=9)
        a = game.heroes[0]
        a.gold = 5
        self.assertTrue(play_pool_spell(game, a, CAREFUL_INVESTMENT))
        self.assertEqual(a.gold, 5)                  # 当回合不获得
        self.assertEqual(len(game.deferred_actions), 1)
        game.turn = 5
        game._begin_recruit_for(a)
        # 基础收入之上 +2（"2" 文本字面量）
        self.assertEqual(a.gold, gold_base_income(5) + 2)


class TestTavernCoin(unittest.TestCase):
    """BG28_810 — Gain 1 Gold。"""

    def test_gain_one_gold(self):
        game = make_game(seed=10)
        a = game.heroes[0]
        a.gold = 4
        self.assertTrue(play_pool_spell(game, a, TAVERN_COIN))
        self.assertEqual(a.gold, 5)                  # "1" 文本字面量


class TestDefendersRites(unittest.TestCase):
    """BG28_825 — Give a minion +{0}/+{1} and Taunt。"""

    def test_buff_and_taunt_from_db_nums(self):
        game = make_game(seed=11)
        a = game.heroes[0]
        d = get_db().get(DEFENDERS_RITES)
        m = summon(game, a, make_minion("M", 2, 3))
        self.assertTrue(play_pool_spell(game, a, DEFENDERS_RITES))
        pc = game.pending_choices[0]
        self.assertEqual(pc.options, [m])            # 默认候选=友方存活
        pc.choose(0)
        self.assertEqual(m.atk, 2 + d.num(0))
        self.assertEqual(m.max_health, 3 + d.num(1))
        self.assertTrue(m.taunt)

    def test_tavern_spell_extra_amplifies(self):
        game = make_game(seed=12)
        a = game.heroes[0]
        d = get_db().get(DEFENDERS_RITES)
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 1)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 2)
        m = summon(game, a, make_minion("M", 2, 3))
        self.assertTrue(play_pool_spell(game, a, DEFENDERS_RITES))
        pc = game.pending_choices[0]
        pc.choose(0)
        self.assertEqual(m.atk, 2 + d.num(0) + 1)    # racefx 统一出口
        self.assertEqual(m.max_health, 3 + d.num(1) + 2)

    def test_empty_board_fizzle(self):
        game = make_game(seed=13)
        a = game.heroes[0]
        self.assertTrue(play_pool_spell(game, a, DEFENDERS_RITES))
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(a.hand, [])


class TestLeafThroughThePages(unittest.TestCase):
    """BG28_827 — Gain 2 free Refreshes。"""

    def test_two_free_refreshes_consumed_before_gold(self):
        game = make_game(seed=14)
        a = game.heroes[0]
        a.gold = 10
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)
        self.assertTrue(play_pool_spell(game, a, LEAF_THROUGH))
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), 2)  # "2"
        gold_before = a.gold
        game.refresh_tavern(a)                       # 先扣免费次数
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), 1)
        self.assertEqual(a.gold, gold_before)        # 不扣金币


class TestGoldenTouch(unittest.TestCase):
    """BG28_830 — Make a random minion in the Tavern Golden。"""

    def test_random_tavern_minion_goldenized_keeps_buffs(self):
        game = make_game(seed=15)
        a = game.heroes[0]
        db = get_db()
        d1, d2 = goldenizable_pool_defs(db, 2)
        g1, g2 = db.golden_version(d1), db.golden_version(d2)
        m1 = tavern_minion(game, a, d1.id)
        m2 = tavern_minion(game, a, d2.id)
        for m in (m1, m2):
            m.add_buff(Buff(atk=1, health=1))
        avail1 = game.minion_pool.available(d1.id)
        avail2 = game.minion_pool.available(d2.id)
        self.assertTrue(play_pool_spell(game, a, GOLDEN_TOUCH))
        golden = [e for e in a.tavern if isinstance(e, Minion)
                  and e.is_golden]
        self.assertEqual(len(golden), 1)             # 恰一只（随机）
        new = golden[0]
        gd, base = ((g1, d1) if new.card_id == g1.id else (g2, d2))
        self.assertEqual(new.card_id, gd.id)
        self.assertEqual(new.get(GameTag.TRIPLE_BASE_CARD_ID), base.id)
        self.assertEqual(new.atk, gd.atk + 1)        # buff 保留（Reno 语义）
        self.assertEqual(new.max_health, gd.health + 1)
        # 不发三连奖励 / 不占池不动池
        self.assertEqual([c.kind for c in game.pending_choices
                          if c.kind == "triple_reward"], [])
        self.assertEqual(game.minion_pool.available(d1.id), avail1)
        self.assertEqual(game.minion_pool.available(d2.id), avail2)

    def test_no_goldenizable_candidate_fizzle(self):
        game = make_game(seed=16)
        a = game.heroes[0]
        plain = make_minion("NOGOLDEN", 3, 3)        # 无卡定义 → 无金色版
        plain.zone = Zone.TAVERN
        a.tavern.append(plain)
        self.assertTrue(play_pool_spell(game, a, GOLDEN_TOUCH))
        self.assertFalse(plain.is_golden)            # 落空
        self.assertIn(plain, a.tavern)


class TestPerfectVision(unittest.TestCase):
    """BG28_838 — Set a minion's stats to {0}/{1}。"""

    def test_set_stats_overrides_buffs(self):
        game = make_game(seed=17)
        a = game.heroes[0]
        d = get_db().get(PERFECT_VISION)
        m = summon(game, a, make_minion("M", 4, 5))
        m.add_buff(Buff(atk=3, health=2))
        self.assertEqual((m.atk, m.max_health), (7, 7))
        self.assertTrue(play_pool_spell(game, a, PERFECT_VISION))
        pc = game.pending_choices[0]
        self.assertEqual(pc.options, [m])
        pc.choose(0)
        self.assertEqual(m.atk, d.num(0))            # 覆盖式重置
        self.assertEqual(m.max_health, d.num(1))
        self.assertEqual(m.health, d.num(1))

    def test_empty_board_fizzle(self):
        game = make_game(seed=18)
        a = game.heroes[0]
        self.assertTrue(play_pool_spell(game, a, PERFECT_VISION))
        self.assertEqual(game.pending_choices, [])


class TestNaturalBlessing(unittest.TestCase):
    """BG28_845 — Choose a minion. Give all minions that share a type
    with it +{0}/+{1}。"""

    def _board(self, game, a):
        murloc = summon(game, a, make_minion("M", 2, 3, race=Race.MURLOC))
        beast = summon(game, a, make_minion("B", 4, 5, race=Race.BEAST))
        amalgam = summon(game, a, make_minion("A", 1, 1, race=Race.ALL))
        typeless = summon(game, a, make_minion("N", 6, 6))
        return murloc, beast, amalgam, typeless

    def test_murloc_target_buffs_murlocs_and_amalgam(self):
        game = make_game(seed=19)
        a = game.heroes[0]
        d = get_db().get(NATURAL_BLESSING)
        murloc, beast, amalgam, typeless = self._board(game, a)
        self.assertTrue(play_pool_spell(game, a, NATURAL_BLESSING))
        pc = game.pending_choices[0]
        self.assertEqual(len(pc.options), 4)        # 默认候选=全体友方
        pc.choose(pc.options.index(murloc))
        self.assertEqual(murloc.atk, 2 + d.num(0))   # 含目标自身
        self.assertEqual(murloc.max_health, 3 + d.num(1))
        self.assertEqual(amalgam.atk, 1 + d.num(0))  # ALL 共享 Murloc
        self.assertEqual(amalgam.max_health, 1 + d.num(1))
        self.assertEqual(beast.atk, 4)               # Beast 不共享
        self.assertEqual(typeless.atk, 6)            # 无类型不共享

    def test_all_target_buffs_every_typed_minion(self):
        game = make_game(seed=20)
        a = game.heroes[0]
        d = get_db().get(NATURAL_BLESSING)
        murloc, beast, amalgam, typeless = self._board(game, a)
        self.assertTrue(play_pool_spell(game, a, NATURAL_BLESSING))
        pc = game.pending_choices[0]
        pc.choose(pc.options.index(amalgam))
        self.assertEqual(murloc.atk, 2 + d.num(0))   # 一切有类型随从
        self.assertEqual(beast.atk, 4 + d.num(0))
        self.assertEqual(beast.max_health, 5 + d.num(1))
        self.assertEqual(amalgam.atk, 1 + d.num(0))
        self.assertEqual(typeless.atk, 6)            # NONE 不与 ALL 共享

    def test_typeless_target_only_typeless(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        d = get_db().get(NATURAL_BLESSING)
        murloc, beast, amalgam, typeless = self._board(game, a)
        self.assertTrue(play_pool_spell(game, a, NATURAL_BLESSING))
        pc = game.pending_choices[0]
        pc.choose(pc.options.index(typeless))
        self.assertEqual(typeless.atk, 6 + d.num(0))  # 仅无类型
        self.assertEqual(typeless.max_health, 6 + d.num(1))
        self.assertEqual(murloc.atk, 2)
        self.assertEqual(beast.atk, 4)
        self.assertEqual(amalgam.atk, 1)

    def test_tavern_spell_extra_amplifies(self):
        game = make_game(seed=22)
        a = game.heroes[0]
        d = get_db().get(NATURAL_BLESSING)
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 1)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 2)
        murloc = summon(game, a, make_minion("M", 2, 3, race=Race.MURLOC))
        self.assertTrue(play_pool_spell(game, a, NATURAL_BLESSING))
        pc = game.pending_choices[0]
        pc.choose(0)
        self.assertEqual(murloc.atk, 2 + d.num(0) + 1)
        self.assertEqual(murloc.max_health, 3 + d.num(1) + 2)


if __name__ == "__main__":
    unittest.main()
