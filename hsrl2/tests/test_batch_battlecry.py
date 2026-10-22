"""批次 battlecry 卡牌语义测试（作业单 2026-08-21，17 张池随从）。

覆盖: BG23_002 Shell Collector / BG25_011 Nerubian Deathswarmer /
BG25_034 Captain Sanders / BG26_135 Southsea Busker / BG26_814 Lovesick
Balladist / BG27_002 Oozeling Gladiator / BG28_303 Disguised Graverobber /
BG31_330 Ominous Seer / BG33_830 Azsharan Cutlassier / BG34_865 En-Djinn
Blazer / BG35_140+141 Mrrglton / BG35_150 Laboratory Assistant /
BG35_152 Void Pup Trainer / BG36_520 Bilgewater Breakout /
BGS_116 Refreshing Anomaly（含金色）。
BG32_841 Sand Swirler: 2026-08-22 由 batch_choose_one 解冻实现
（ELEMENTAL_EXTRA_ATK 1057 入册后）——本文件原 "未注册即正确状态"
占位守护随之删除，语义测试见 test_batch_choose_one.py。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）; 文本无占位符的卡用
文本字面量并注明。金色战吼模型: 引擎触发 2 次 × 基础值 = 金色文本总额。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.constants import LOCKBOX_CARD_ID, gold_base_income
from hsrl2.db import CardDB
from hsrl2.entity import Buff
from hsrl2.events import Listener
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
    """创建随从（REGISTRY 脚本绑定由 create_minion 完成）→ 召唤。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def to_hand(game: Game, card_id: str, hero: Hero,
            golden: bool = False) -> Minion:
    """创建随从入手（不召唤——play_minion 测试用）。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def find_plain(db, *, tier: int | None = None) -> "object":
    """无任何效果关键词、有金色定义的池随从（Sanders 金色化测试靶）。"""
    for d in sorted(db.pool_minions(), key=lambda x: x.id):
        if tier is not None and d.tech_level != tier:
            continue
        if d.keywords:
            continue
        if db.golden_version(d) is None:
            continue
        return d
    raise AssertionError("no plain pool card with golden def")


def tavern_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    """池占位 + 创建入馆（池守恒: 先 acquire）。"""
    assert game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


class TestRegistryState(unittest.TestCase):
    """批次注册面: OK 卡全注册（含金色），DEFERRED 卡不注册。"""

    def test_all_ok_cards_registered(self):
        for cid in ("BG23_002", "BG23_002_G", "BG25_011", "BG25_011_G",
                    "BG25_034", "BG25_034_G", "BG26_135", "BG26_135_G",
                    "BG26_814", "BG26_814_G", "BG27_002", "BG27_002_G",
                    "BG28_303", "BG28_303_G", "BG31_330", "BG31_330_G",
                    "BG33_830", "BG33_830_G", "BG34_865", "BG34_865_G",
                    "BG35_140", "BG35_140_G", "BG35_141", "BG35_141_G",
                    "BG35_150", "BG35_150_G", "BG35_152", "BG35_152_G",
                    "BG36_520", "BG36_520_G", "BGS_116", "TB_BaconUps_167"):
            self.assertIn(cid, REGISTRY)

    def test_sand_swirler_unfrozen_by_choose_one_batch(self):
        """2026-08-22 解冻: BG32_841 由 batch_choose_one 注册（原 DEFERRED
        状态守护反转——语义/数值测试在 test_batch_choose_one.py）。"""
        self.assertIn("BG32_841", REGISTRY)
        self.assertIn("BG32_841_G", REGISTRY)


class TestShellCollector(unittest.TestCase):
    """BG23_002 — BC: Get a Tavern Coin（池法术，evolution 数据链）。"""

    def _coin_id(self) -> str:
        d = get_db().get("BG23_002")
        return get_db().by_dbf(d.evolution_card_id).id

    def test_battlecry_gets_tavern_coin_occupying_spell_pool(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        coin_id = self._coin_id()
        tier = get_db().get(coin_id).tech_level
        self.assertEqual(get_db().get(coin_id).is_pool_spell, True)
        self.assertEqual(game.spell_pool.available(coin_id),
                         SpellPool.POOL_COPIES_BY_TIER[tier])  # 满库存
        sc = to_hand(game, "BG23_002", a)
        self.assertTrue(game.play_minion(a, sc))
        coins = [c for c in a.hand if c.card_id == coin_id]
        self.assertEqual(len(coins), 1)
        self.assertEqual(game.spell_pool.available(coin_id),
                         SpellPool.POOL_COPIES_BY_TIER[tier] - 1)  # 占池

    def test_golden_gets_two_coins_second_minted_when_pool_empty(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        coin_id = self._coin_id()
        sc = to_hand(game, "BG23_002", a, golden=True)
        self.assertEqual(sc.card_id, "BG23_002_G")
        self.assertTrue(game.play_minion(a, sc))
        coins = [c for c in a.hand if c.card_id == coin_id]
        # 金色 "Get 2 Tavern Coins": 第 2 枚池空生成（Mystic Essence 先例）
        self.assertEqual(len(coins), 2)

    def test_pool_already_held_still_mints(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        coin_id = self._coin_id()
        while game.spell_pool.available(coin_id):   # 抽干（per-tier 副本）
            assert game.spell_pool.acquire(coin_id)
        sc = to_hand(game, "BG23_002", a)
        self.assertTrue(game.play_minion(a, sc))
        self.assertEqual(
            len([c for c in a.hand if c.card_id == coin_id]), 1)


class TestNerubianDeathswarmer(unittest.TestCase):
    """BG25_011 — BC: Your Undead have +1 Attack this game (wherever)。"""

    def _setup(self, game, hero):
        board_undead = make_minion("U", 2, 3, race=Race.UNDEAD)
        game.summon(hero, board_undead)
        board_beast = make_minion("B", 2, 3, race=Race.BEAST)
        game.summon(hero, board_beast)
        hand_undead = game.create_minion("BG25_011", controller=hero)
        hero.hand.append(hand_undead)
        hand_undead.zone = Zone.HAND
        return board_undead, board_beast, hand_undead

    def test_battlecry_race_aura_wherever_they_are(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        u, b, hu = self._setup(game, a)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG25_011", a)))
        self.assertEqual(a.race_auras.get(Race.UNDEAD), (1, 0))  # 文本字面量 1
        self.assertEqual(u.atk, 2 + 1)          # 棋盘 Undead
        self.assertEqual(hu.atk, 1 + 1)         # 手牌 Undead（wherever）
        self.assertEqual(b.atk, 2)              # 非 Undead 不变

    def test_golden_total_plus_two(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        u = make_minion("U", 2, 3, race=Race.UNDEAD)
        game.summon(a, u)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG25_011", a, golden=True)))
        self.assertEqual(a.race_auras.get(Race.UNDEAD), (2, 0))  # 2×1=+2


class TestCaptainSanders(unittest.TestCase):
    """BG25_034 — BC: Make a friendly minion from Tier 6 or below Golden
    （定向; Reno 语义: Transform 保留 buff、不发三连奖励）。"""

    def test_pending_choice_flow_and_goldenize_keeps_buffs(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        d = find_plain(get_db(), tier=2)
        gd = get_db().golden_version(d)
        target = put(game, d.id, a)
        target.add_buff(Buff(atk=2, health=3))
        self.assertTrue(game.play_minion(a, to_hand(game, "BG25_034", a)))
        self.assertEqual(len(game.pending_choices), 1)
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "battlecry_target")
        self.assertIn(target, pc.options)
        idx = pc.options.index(target)
        pos_before = a.board.index(target)
        pc.choose(idx)
        new = a.board[pos_before]
        self.assertTrue(new.is_golden)
        self.assertEqual(new.card_id, gd.id)
        self.assertEqual(new.get(GameTag.TRIPLE_BASE_CARD_ID), d.id)
        # 保留 buff: 金色基础值 + 原附魔（Reno 语义）
        self.assertEqual(new.atk, gd.atk + 2)
        self.assertEqual(new.max_health, gd.health + 3)
        # 金色化 ≠ 三连: 无三连奖励发现
        self.assertEqual([c.kind for c in game.pending_choices
                          if c.kind == "triple_reward"], [])

    def test_candidates_exclude_t7_and_golden(self):
        game = make_game(seed=7)
        a = game.heroes[0]
        d = find_plain(get_db(), tier=2)
        put(game, d.id, a)
        put(game, d.id, a, golden=True)                 # 已金色排除
        sanders = to_hand(game, "BG25_034", a)          # 自身 T7 排除
        self.assertTrue(game.play_minion(a, sanders))
        self.assertEqual(len(game.pending_choices), 1)
        opts = game.pending_choices[0].options
        self.assertEqual(len(opts), 1)                  # 仅非金色 T2 靶
        self.assertFalse(any(m.is_golden or m.tech_level > 6 for m in opts))

    def test_no_candidates_battlecry_fizzles_minion_played(self):
        game = make_game(seed=8)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(a, to_hand(game, "BG25_034", a)))
        self.assertEqual(len(game.pending_choices), 0)
        self.assertEqual(len(a.board), 1)               # Sanders 照常入场

    def test_golden_makes_two_minions_golden(self):
        game = make_game(seed=9)
        a = game.heroes[0]
        d = find_plain(get_db(), tier=2)
        t1 = put(game, d.id, a)
        t2 = put(game, d.id, a)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG25_034", a, golden=True)))
        pc1 = game.pending_choices.pop(0)
        pos1 = a.board.index(t1)
        pc1.choose(pc1.options.index(t1))
        new1 = a.board[pos1]                    # Transform 后新实体占原位
        self.assertTrue(new1.is_golden)
        # 第 2 次触发: 追加第二次选择（"two friendly minions"）
        self.assertEqual(len(game.pending_choices), 1)
        pc2 = game.pending_choices.pop(0)
        self.assertEqual(pc2.kind, "battlecry_target")
        pos2 = a.board.index(t2)
        pc2.choose(pc2.options.index(t2))
        self.assertTrue(a.board[pos2].is_golden)
        # 金色化目标 = 2 只（金色 Sanders 自身也是 GOLDEN，排除计数）
        sanders_golden = sum(1 for m in a.board
                             if m.is_golden and m.card_id.startswith("BG25_034"))
        self.assertEqual(
            sum(1 for m in a.board if m.is_golden) - sanders_golden, 2)

    def test_golden_single_candidate_second_choice_fizzles(self):
        game = make_game(seed=10)
        a = game.heroes[0]
        d = find_plain(get_db(), tier=2)
        t1 = put(game, d.id, a)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG25_034", a, golden=True)))
        game.pending_choices.pop(0).choose(0)
        # 金色化目标仅 1 只（金色 Sanders 自身排除计数）
        sanders_golden = sum(1 for m in a.board
                             if m.is_golden and m.card_id.startswith("BG25_034"))
        self.assertEqual(
            sum(1 for m in a.board if m.is_golden) - sanders_golden, 1)
        self.assertEqual(len(game.pending_choices), 0)  # 无第二候选落空


class TestSouthseaBusker(unittest.TestCase):
    """BG26_135 — BC: Gain 1 Gold next turn（ScheduleNextTurn）。"""

    def test_gold_deferred_to_next_turn(self):
        game = make_game(seed=11)
        a = game.heroes[0]
        a.gold = 5
        self.assertTrue(game.play_minion(a, to_hand(game, "BG26_135", a)))
        self.assertEqual(a.gold, 5)                     # 当回合不获得
        game.turn = 5
        game._begin_recruit_for(a)
        self.assertEqual(a.gold, gold_base_income(5) + 1)   # 文本字面量 1

    def test_golden_gains_two(self):
        game = make_game(seed=12)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG26_135", a, golden=True)))
        game.turn = 4
        game._begin_recruit_for(a)
        self.assertEqual(a.gold, gold_base_income(4) + 2)


class TestLovesickBalladist(unittest.TestCase):
    """BG26_814 — BC: Give a Pirate +{1} Health, Improved by each Gold
    spent this turn（[Targeted]; 公式 num(1)+GOLD_SPENT_THIS_TURN）。"""

    def test_targeted_zero_spent_base_health(self):
        game = make_game(seed=13)
        a = game.heroes[0]
        base = get_db().get("BG26_814").num(1)          # =1
        pirate = make_minion("P", 3, 3, race=Race.PIRATE)
        game.summon(a, pirate)
        beast = make_minion("Z", 3, 3, race=Race.BEAST)
        game.summon(a, beast)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG26_814", a)))
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "battlecry_target")
        self.assertIn(pirate, pc.options)
        self.assertNotIn(beast, pc.options)             # 非 Pirate 排除
        pc.choose(pc.options.index(pirate))
        self.assertEqual(pirate.max_health, 3 + base)   # 0 支出: 基值

    def test_improved_by_gold_spent_this_turn(self):
        game = make_game(seed=14)
        a = game.heroes[0]
        base = get_db().get("BG26_814").num(1)
        pirate = make_minion("P", 3, 3, race=Race.PIRATE)
        game.summon(a, pirate)
        a.gold = 10
        game.spend_gold(a, 3)                           # 本回合支出 3 金
        self.assertTrue(game.play_minion(a, to_hand(game, "BG26_814", a)))
        pc = game.pending_choices.pop(0)
        pc.choose(pc.options.index(pirate))
        self.assertEqual(pirate.max_health, 3 + base + 3)

    def test_golden_twice_same_target(self):
        game = make_game(seed=15)
        a = game.heroes[0]
        base = get_db().get("BG26_814").num(1)
        pirate = make_minion("P", 3, 3, race=Race.PIRATE)
        game.summon(a, pirate)
        a.gold = 5
        game.spend_gold(a, 2)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG26_814", a, golden=True)))
        pc = game.pending_choices.pop(0)
        pc.choose(pc.options.index(pirate))
        # "twice" = 2 触发 ×（num(1) + 2）= 2×3
        self.assertEqual(pirate.max_health, 3 + 2 * (base + 2))


class TestOozelingGladiator(unittest.TestCase):
    """BG27_002 — BC: Get two Slimy_Shields（token 法术，非池）。"""

    def test_battlecry_gets_two_shields(self):
        game = make_game(seed=16)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(a, to_hand(game, "BG27_002", a)))
        shields = [c for c in a.hand if c.card_id == "BG27_002t"]
        self.assertEqual(len(shields), 2)               # 文本字面量 "two"

    def test_golden_gets_four(self):
        game = make_game(seed=17)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG27_002", a, golden=True)))
        self.assertEqual(
            len([c for c in a.hand if c.card_id == "BG27_002t"]), 4)


class TestDisguisedGraverobber(unittest.TestCase):
    """BG28_303 — BC: Destroy a friendly Undead to get a plain copy of it
    （定向; 完整死亡链; plain copy 无 buff）。"""

    def _undead(self, game, hero):
        # 池占位 + 入场（死亡回池断言的池守恒前提）
        cid = "BG25_011"                                # Undead 池卡
        assert game.minion_pool.acquire(cid)
        m = game.create_minion(cid, controller=hero)
        game.summon(hero, m)
        return m, game.minion_pool.available(cid)

    def test_targeted_destroy_death_chain_and_plain_copy(self):
        game = make_game(seed=18)
        a = game.heroes[0]
        target, avail_before = self._undead(game, a)
        d = get_db().get(target.card_id)
        target.add_buff(Buff(atk=5, health=5))
        beast = make_minion("Z", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        deaths = []
        game.events.register(Listener(
            event="death", owner=beast,
            callback=lambda g, minion=None, **kw: deaths.append(minion)))
        self.assertTrue(game.play_minion(a, to_hand(game, "BG28_303", a)))
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "battlecry_target")
        self.assertIn(target, pc.options)
        self.assertNotIn(beast, pc.options)             # 仅 Undead 候选
        pc.choose(pc.options.index(target))
        # 完整死亡链: death 事件 fire、棋盘移除、GRAVEYARD、招募期回池
        self.assertEqual(deaths, [target])
        self.assertNotIn(target, a.board)
        self.assertEqual(target.zone, Zone.GRAVEYARD)
        self.assertEqual(game.minion_pool.available(target.card_id),
                         avail_before + 1)
        # plain copy 入手: 白板（无 buff）
        copies = [m for m in a.hand if m.card_id == target.card_id]
        self.assertEqual(len(copies), 1)
        self.assertEqual((copies[0].atk, copies[0].max_health),
                         (d.atk, d.health))

    def test_golden_two_copies_single_destroy(self):
        game = make_game(seed=19)
        a = game.heroes[0]
        target, _ = self._undead(game, a)
        d = get_db().get(target.card_id)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG28_303", a, golden=True)))
        pc = game.pending_choices.pop(0)
        pc.choose(pc.options.index(target))
        copies = [m for m in a.hand if m.card_id == target.card_id]
        self.assertEqual(len(copies), 2)                # "2 plain copies"
        self.assertEqual(a.graveyard.count(target), 1)  # 只摧毁一次
        for c in copies:
            self.assertEqual((c.atk, c.max_health), (d.atk, d.health))

    def test_no_undead_candidates_fizzle(self):
        game = make_game(seed=20)
        a = game.heroes[0]
        beast = make_minion("Z", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG28_303", a)))
        self.assertEqual(len(game.pending_choices), 0)
        self.assertEqual(len(a.board), 2)               # 随从照常入场
        self.assertEqual(beast.health, 2)


class TestOminousSeer(unittest.TestCase):
    """BG31_330 — BC: The next Tavern spell you buy costs (1) less。"""

    def _tavern_spell(self, game, hero):
        cands = [d for d in get_db().pool_spells()]
        d = sorted(cands, key=lambda x: x.id)[0]
        assert game.spell_pool.acquire(d.id)
        s = game.create_spell(d.id, controller=hero)
        s.zone = Zone.TAVERN
        hero.tavern.append(s)
        return s, d

    def test_sets_next_spell_reduction_and_consumed_on_buy(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(a, to_hand(game, "BG31_330", a)))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 1)
        s, d = self._tavern_spell(game, a)
        a.gold = 10
        cost = s.get(GameTag.COST, 3)
        self.assertTrue(game.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 10 - max(0, cost - 1))  # 折扣 1 生效
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 0)

    def test_golden_discount_two(self):
        game = make_game(seed=22)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG31_330", a, golden=True)))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 2)
        s, d = self._tavern_spell(game, a)
        a.gold = 10
        cost = s.get(GameTag.COST, 3)
        self.assertTrue(game.buy_from_tavern(a, s))
        self.assertEqual(a.gold, 10 - max(0, cost - 2))  # (2) less
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 0)


class TestAzsharanCutlassier(unittest.TestCase):
    """BG33_830 — BC: Your Tavern spells give an extra +1 Attack this game
    （TAVERN_SPELL_EXTRA_ATK，tavern_spell_buff 消费）。"""

    def test_sets_extra_atk_and_buff_outlet_reflects(self):
        game = make_game(seed=23)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(a, to_hand(game, "BG33_830", a)))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 1)
        # 消费点: racefx.tavern_spell_buff 构造的法术 buff 自动 +1 攻
        target = make_minion("T", 2, 2)
        target.controller = a
        buff = tavern_spell_buff(target, atk=1, health=1)
        game.run_actions(buff)
        self.assertEqual(target.atk, 2 + 1 + 1)         # 1 基值 + 1 extra
        self.assertEqual(target.max_health, 2 + 1)      # health 无增幅

    def test_golden_two(self):
        game = make_game(seed=24)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG33_830", a, golden=True)))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2)


class TestEnDjinnBlazer(unittest.TestCase):
    """BG34_865 — BC: After the Tavern is Refreshed this game, give a
    random minion in it +{0}/+{1}（TAVERN_REFRESH 持久监听）。"""

    def _refresh(self, game, hero):
        game.refresh_tavern(hero, auto=False, free=True)

    def _tavern_delta(self, hero):
        total_atk = total_hp = 0
        for e in hero.tavern:
            if isinstance(e, Minion):
                d = get_db().get(e.card_id)
                total_atk += e.atk - d.atk
                total_hp += e.max_health - d.health
        return total_atk, total_hp

    def test_each_refresh_buffs_random_tavern_minion(self):
        game = make_game(seed=25)
        a = game.heroes[0]
        d = get_db().get("BG34_865")
        self.assertTrue(game.play_minion(a, to_hand(game, "BG34_865", a)))
        self._refresh(game, a)
        self.assertEqual(self._tavern_delta(a), (d.num(0), d.num(1)))
        # 每次刷新对**当时馆内**随机一只加成——旧馆内容被刷新置换回池，
        # 新馆仅含本次触发的 +num/num（"this game" = 触发持续非数值累积）
        self._refresh(game, a)
        self.assertEqual(self._tavern_delta(a), (d.num(0), d.num(1)))

    def test_effect_persists_after_source_sold(self):
        game = make_game(seed=26)
        a = game.heroes[0]
        djinn = to_hand(game, "BG34_865", a)
        self.assertTrue(game.play_minion(a, djinn))     # 战吼注册监听
        game.sell_minion(a, djinn)                      # 随从离场
        self._refresh(game, a)
        d = get_db().get("BG34_865")
        self.assertEqual(self._tavern_delta(a), (d.num(0), d.num(1)))

    def test_empty_tavern_no_crash(self):
        game = make_game(seed=27)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(a, to_hand(game, "BG34_865", a)))
        a.tavern = []                                   # 退化场景: 馆空
        game.events.fire(game, "tavern_refresh", hero=a)
        self.assertEqual(a.tavern, [])

    def test_golden_twice_per_refresh(self):
        game = make_game(seed=28)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG34_865", a, golden=True)))
        self._refresh(game, a)
        d = get_db().get("BG34_865")
        # "twice": 2 监听器 × num(0)/num(1)（单随从场景叠加 +20/+20）
        self.assertEqual(self._tavern_delta(a),
                         (2 * d.num(0), 2 * d.num(1)))


class TestMrrglton(unittest.TestCase):
    """BG35_140/141 — BC: Give your other Murlocs +{0} A/H. (Improved by
    each Mrrglton you played this game!（Mama/Papa 共享计数，含自身裁定）"""

    def test_first_mama_includes_self_plus_base(self):
        game = make_game(seed=29)
        a = game.heroes[0]
        base = get_db().get("BG35_140").num(0)          # =3
        murloc = make_minion("M", 4, 4, race=Race.MURLOC)
        game.summon(a, murloc)
        amalgam = make_minion("A", 2, 2, race=Race.ALL)
        game.summon(a, amalgam)
        beast = make_minion("Z", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG35_140", a)))
        # 裁定: 计数含当前打出 → +（3 + 1）; ALL 种族匹配; 非 Murloc 不变
        self.assertEqual(murloc.atk, 4 + base + 1)
        self.assertEqual(amalgam.atk, 2 + base + 1)
        self.assertEqual(beast.atk, 2)
        self.assertEqual(murloc.max_health, 4)

    def test_papa_shares_count_health_dimension(self):
        game = make_game(seed=30)
        a = game.heroes[0]
        base = get_db().get("BG35_141").num(0)
        murloc = make_minion("M", 4, 4, race=Race.MURLOC)
        game.summon(a, murloc)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG35_140", a)))
        self.assertEqual(murloc.atk, 4 + get_db().get("BG35_140").num(0) + 1)
        # 第 2 只 Mrrglton: 共享计数=2 → +（3+2）Health
        self.assertTrue(game.play_minion(a, to_hand(game, "BG35_141", a)))
        self.assertEqual(murloc.max_health, 4 + base + 2)

    def test_golden_mama_two_triggers(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        base = get_db().get("BG35_140").num(0)
        murloc = make_minion("M", 4, 4, race=Race.MURLOC)
        game.summon(a, murloc)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG35_140", a, golden=True)))
        # 首只金色 Mama: 计数=1（含自身）→ 2 触发 ×（3+1）= +8
        self.assertEqual(murloc.atk, 4 + 2 * (base + 1))

    def test_summoned_mrrglton_retrigger_excludes_self(self):
        """Evidence: "played this game" 文本口径——召唤入场（无打出）的
        Mrrglton 被 TriggerBattlecry 重触发时计数不含自身（2026-08-23
        修正，_in_play_effects 路径区分）。"""
        from hsrl2.actions import TriggerBattlecry
        game = make_game(seed=33)
        a = game.heroes[0]
        base = get_db().get("BG35_140").num(0)
        murloc = make_minion("M", 4, 4, race=Race.MURLOC)
        game.summon(a, murloc)
        summoned = to_hand(game, "BG35_140", a)
        game.summon(a, summoned)          # 召唤入场（不经 play_minion）
        game.run_actions(TriggerBattlecry(summoned))
        # 计数=0（从未打出）→ +（3+0）
        self.assertEqual(murloc.atk, 4 + base)

    def test_no_other_murlocs_no_op(self):
        game = make_game(seed=32)
        a = game.heroes[0]
        beast = make_minion("Z", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG35_140", a)))
        self.assertEqual(beast.atk, 2)
        self.assertEqual(len(a.board), 2)


class TestLaboratoryAssistant(unittest.TestCase):
    """BG35_150 — BC: Add a Fodder to your next {0} Refreshes。"""

    def _fodder_count(self, hero):
        return sum(1 for e in hero.tavern if e.card_id == "BG35_150t")

    def test_next_three_refreshes_each_add_one_fodder(self):
        game = make_game(seed=33)
        a = game.heroes[0]
        n = get_db().get("BG35_150").num(0)             # =3
        self.assertTrue(game.play_minion(a, to_hand(game, "BG35_150", a)))
        for i in range(n):
            game.refresh_tavern(a, auto=False, free=True)
            self.assertEqual(self._fodder_count(a), 1,
                             f"refresh {i + 1}: 恰 1 枚（旧馆内容被刷新置换）")
        game.refresh_tavern(a, auto=False, free=True)   # 第 n+1 次: 不再附加
        self.assertEqual(self._fodder_count(a), 0)

    def test_golden_two_fodders_per_refresh_three_refreshes(self):
        game = make_game(seed=34)
        a = game.heroes[0]
        n = get_db().get("BG35_150").num(0)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG35_150", a, golden=True)))
        game.refresh_tavern(a, auto=False, free=True)
        self.assertEqual(self._fodder_count(a), 2)      # 2 枚/刷新
        for _ in range(n - 1):
            game.refresh_tavern(a, auto=False, free=True)
            self.assertEqual(self._fodder_count(a), 2)
        game.refresh_tavern(a, auto=False, free=True)   # 配额尽
        self.assertEqual(self._fodder_count(a), 0)


class TestVoidPupTrainer(unittest.TestCase):
    """BG35_152 — BC: Give minions in the Tavern from Tier 3 and below
    +{0}/+{1} this game（立即面 + 持久面）。"""

    def test_immediate_and_persistent_faces(self):
        game = make_game(seed=35)
        a = game.heroes[0]
        d = get_db().get("BG35_152")
        t2 = find_plain(get_db(), tier=2)
        t5 = find_plain(get_db(), tier=5)
        low = tavern_minion(game, a, t2.id)
        high = tavern_minion(game, a, t5.id)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG35_152", a)))
        # 立即面: 当前馆 T≤3 +num/num; T5 不变
        self.assertEqual(low.atk, t2.atk + d.num(0))
        self.assertEqual(low.max_health, t2.health + d.num(1))
        self.assertEqual(high.atk, t5.atk)
        # 持久面: 刷新后新入馆 T≤3（tier=3 抽取全部 ≤3）自动加成
        a.set(GameTag.TAVERN_TIER, 3)
        game.refresh_tavern(a, auto=False, free=True)
        buffed = 0
        for e in a.tavern:
            if not isinstance(e, Minion):
                continue
            ed = get_db().get(e.card_id)
            self.assertEqual(e.atk, ed.atk + d.num(0))
            self.assertEqual(e.max_health, ed.health + d.num(1))
            buffed += 1
        self.assertGreater(buffed, 0)

    def test_golden_six_six_total(self):
        game = make_game(seed=36)
        a = game.heroes[0]
        d = get_db().get("BG35_152")
        t2 = find_plain(get_db(), tier=2)
        low = tavern_minion(game, a, t2.id)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG35_152", a, golden=True)))
        # 金色 = 2 触发 ×（3/3）= 6/6
        self.assertEqual(low.atk, t2.atk + 2 * d.num(0))
        self.assertEqual(low.max_health, t2.health + 2 * d.num(1))


class TestBilgewaterBreakout(unittest.TestCase):
    """BG36_520 — BC: Get a Lockbox. If you already have one, it opens
    {0} turn(s) sooner instead。"""

    def test_no_lockbox_gets_one(self):
        game = make_game(seed=37)
        a = game.heroes[0]
        lock_def = get_db().get(LOCKBOX_CARD_ID)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG36_520", a)))
        boxes = [c for c in a.hand if c.card_id == LOCKBOX_CARD_ID]
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0].get(GameTag.LOCKBOX_TURNS_LEFT),
                         lock_def.num(0))               # =5，未被提前

    def test_existing_lockbox_opens_one_turn_sooner(self):
        game = make_game(seed=38)
        a = game.heroes[0]
        n = get_db().get("BG36_520").num(0)             # =1
        lock = game.create_spell(LOCKBOX_CARD_ID, controller=a)
        lock.set(GameTag.LOCKBOX_TURNS_LEFT, 5)
        a.hand.append(lock)
        self.assertTrue(game.play_minion(a, to_hand(game, "BG36_520", a)))
        self.assertEqual(lock.get(GameTag.LOCKBOX_TURNS_LEFT), 5 - n)
        self.assertEqual(len(a.hand), 1)   # 仅原锁在手（Breakout 已打出）

    def test_golden_sooner_two_and_no_self_decrement(self):
        game = make_game(seed=39)
        a = game.heroes[0]
        gd = get_db().get("BG36_520_G")
        self.assertEqual(gd.num(0), 2)                  # 金色数据核对
        lock = game.create_spell(LOCKBOX_CARD_ID, controller=a)
        lock.set(GameTag.LOCKBOX_TURNS_LEFT, 5)
        a.hand.append(lock)
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BG36_520", a, golden=True)))
        self.assertEqual(lock.get(GameTag.LOCKBOX_TURNS_LEFT), 5 - 2)
        # 金色无锁分支: 守卫防第 2 次触发把刚入手的锁再提前
        game2 = make_game(seed=40)
        b = game2.heroes[0]
        self.assertTrue(game2.play_minion(
            b, to_hand(game2, "BG36_520", b, golden=True)))
        boxes = [c for c in b.hand if c.card_id == LOCKBOX_CARD_ID]
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0].get(GameTag.LOCKBOX_TURNS_LEFT), 5)


class TestRefreshingAnomaly(unittest.TestCase):
    """BGS_116 — BC: Gain 2 free Refreshes。"""

    def test_gains_two_free_refreshes(self):
        game = make_game(seed=41)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(a, to_hand(game, "BGS_116", a)))
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), 2)
        a.gold = 5
        gold_before = a.gold
        game.refresh_tavern(a, auto=False)              # 消耗免费次数非金币
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), 1)
        self.assertEqual(a.gold, gold_before)

    def test_golden_four(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        self.assertTrue(game.play_minion(
            a, to_hand(game, "BGS_116", a, golden=True)))
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), 4)


if __name__ == "__main__":
    unittest.main()
