"""批次 trinkets20 行为层测试（11 张饰品 + 1 张 Spellcraft 法术注册）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）
  - 关联卡授予: `game.grant_trinket_related_card` /
    `grant_card_copy_to_hand`（RULES §7.4.6）
  - 回合钩子: `game.run_script_hook(trinket, "start_of_turn"/"end_of_turn")`
    （引擎 `_begin_recruit_for`/`end_recruit_phase` 的实际调用形态）与
    真实 `game.end_recruit_phase()`（跨回合语义）
  - 战斗: 真实 `game.run_combat`（SoC 阶段）+ 战斗内
    `start_of_combat` 探针（SoC 增益战后被快照复原，RULES §3.5）
  - 攻击: `game.events.fire(g, "before_attack", ...)`（引擎两处攻击路径
    的统一广播形态）与真实 `game.recruit_phase_attack`
  - 购买: 真实 `game.buy_from_tavern`（`minion_bought` 广播）
  - 施放: 真实 `game.play_spell`（定向法术）+ `game.cast_spell_effect`
  - 复生: 真实 `_process_single_death` 路径（`game.check_deaths`）
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法）: 每个测试方法至少含一条**正效果**断言
（负对照与正对照同方法内），owner 隔离（2 英雄），跨回合语义，
池空/无候选落空，一次性/额度语义，CardDef.num 双向钉死。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id）
BEAST_T3 = "BG25_806"        # Sly Raptor 1/3 T3 野兽（池）
MURLOC_T2 = "BG22_202"       # Tad 2/2 T2 鱼人（池）
QUILBOAR_T1 = "BG20_100"     # Razorfen Geomancer 2/1 T1 野猪人（池）
QUILBOAR_T2 = "BG20_101"     # Roadboar 2/4 T2 野猪人（池）
NAGA_T1 = "BG23_000"         # Mini-Myrmidon 1/4 T1 纳迦（池）
NAGA_T3 = "BG23_004"         # Deep-Sea Angler 2/3 T3 纳迦（池）
BANANA_SLAMMA = "BG26_802"   # 3/6 T4 野兽（池，无脚本钩子——"plain"体）
UNDEAD_T2 = "BG25_008"       # Eternal Knight 4/2 T2 亡灵（池）
PLAGUERUNNER = "BG34_690"    # 4/2 T4 亡灵（池，亡语: 友方亡灵 +num 攻击）
BANANA = "BG28_897"          # Tavern Dish Banana T1 池法术（定向 +num/+num）
BUTCHERING = "BG28_604"      # Butchering T5 池法术（定向**仅亡灵**: 消灭）

# 本批 id
TYPEWRITER = "BG35_MagicItem_931"
LIONFISH = "BG36_MagicItem_201"
OMINOUS = "BG36_MagicItem_206"
CANDLE = "BG36_MagicItem_208"
CANDLE_SPELL = "BG36_MagicItem_208t"
LOCKET = "BG36_MagicItem_211"
WREATH = "BG36_MagicItem_217"
LOCKBOX = "BG36_MagicItem_301"
MALLET = "BG36_MagicItem_302"
GLASS = "BG36_MagicItem_303"
WAX_LANCE = "BG36_MagicItem_309"
MYRMIDON = "BG36_MagicItem_361"

# 关联卡（数据链）
LIONFISH_CARD = "BG36_201"

IMPLEMENTED = (TYPEWRITER, LIONFISH, OMINOUS, CANDLE, CANDLE_SPELL, LOCKET,
               WREATH, LOCKBOX, MALLET, GLASS, WAX_LANCE, MYRMIDON)

# DEFERRED（不注册；台账见 batch_trinkets20 模块 docstring）
# BG36_MagicItem_204 Plaguerunner Portrait 已由 batch_trinkets26 注册
# （game.destroy_minion + minion_destroyed，commit 481617f）。
DEFERRED = ()
# 930/214/216/308 已由 batch_unlock_final 注册（2026-09-15:
# copies_of_warband / trigger_friendly_rallies / add_card_aura /
# hero 级 CHOOSE_BOTH）——迁出 DEFERRED 台账，仍计入本批 16 张范围
MIGRATED = (
    "BG35_MagicItem_930",   # Warband Whistle
    "BG36_MagicItem_214",   # Insurrectionist's Blade
    "BG36_MagicItem_216",   # Eternal Portrait
    "BG36_MagicItem_308",   # Trailblazer Sticker
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 920) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str, position=None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m, position)
    return m


def kill(game: Game, m: Minion) -> None:
    m.health = 0
    game.check_deaths()


def num(card_id: str, index: int) -> int:
    v = get_db().get(card_id).num(index)
    assert v is not None, f"{card_id}.num({index}) missing"
    return v


def stock_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    """把一只随从放进酒馆（按池记账: 从池取 1 份——官方刷新路径同款）。"""
    game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def drain(game: Game, card_id: str) -> int:
    n = 0
    while game.minion_pool.acquire(card_id):
        n += 1
    return n


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


class InCombat:
    """手动进入战斗态的上下文管理器（test_batch_soc 先例）。"""

    def __init__(self, game: Game):
        self.game = game

    def __enter__(self):
        self.game.in_combat = True
        return self.game

    def __exit__(self, *exc):
        self.game.in_combat = False
        return False


def soc_probe(game: Game, owner) -> dict:
    """战斗内 SoC 探测（引擎在全部 SoC 钩子之后逐英雄广播 `hero=`）。"""
    out: dict = {}

    def cb(g, hero=None, **kw):
        if hero is None:
            return
        out[hero] = [(m.card_id, m.atk, m.health) for m in hero.board]

    game.events.register(Listener(event="start_of_combat", owner=owner,
                                  callback=cb))
    return out


# ══════════════ BG35_MagicItem_931 Transcribing Typewriter ══════════════


class TestTranscribingTypewriter(unittest.TestCase):
    """购买随从时额外入手一份白板副本（额度 num(1)）。"""

    TID = TYPEWRITER

    def test_buy_grants_extra_plain_copy(self):
        g = make_game(9201)
        a, b = g.heroes
        a.gold = 30
        t = bind(g, a, self.TID)
        self.assertEqual(t._typewriter_left, num(self.TID, 1))
        pool_before = g.minion_pool.available(QUILBOAR_T1)
        tavern = stock_tavern(g, a, QUILBOAR_T1)
        self.assertTrue(g.buy_from_tavern(a, tavern))
        self.assertEqual(hand_ids(a), [QUILBOAR_T1, QUILBOAR_T1])
        # 额外副本占池一份（买入的来自馆内预留，额外副本另取 1）
        self.assertEqual(g.minion_pool.available(QUILBOAR_T1),
                         pool_before - 2)
        self.assertEqual(t._typewriter_left, num(self.TID, 1) - 1)

    def test_full_hand_still_consumes_budget(self):
        """满手（副本入等待队列）**仍算成功**、照常扣额度。

        旧实现 `grant_card_copy_to_hand` 把"已排队"与"落空"都返回
        False → 额度不减、每个满手购买都白拿一份副本（2026-09-02
        对抗审查证伪 BG35_MagicItem_931）。
        """
        g = make_game(9203)
        a, b = g.heroes
        a.gold = 30
        t = bind(g, a, self.TID)
        while len(a.hand) < 9:            # 买入后手牌恰满，副本排入等待队列
            a.hand.append(g.create_spell("BG28_168", controller=a))
        tavern = stock_tavern(g, a, QUILBOAR_T1)
        self.assertTrue(g.buy_from_tavern(a, tavern))
        queued = [e for h, e in g.pending_hand_queue if h is a
                  and e.card_id == QUILBOAR_T1]
        self.assertEqual(len(queued), 1)
        self.assertEqual(t._typewriter_left, num(self.TID, 1) - 1)

    def test_budget_exhausts_and_stops_copying(self):
        g = make_game(9202)
        a, b = g.heroes
        a.gold = 30
        t = bind(g, a, self.TID)
        bought = [QUILBOAR_T1, QUILBOAR_T2][:num(self.TID, 1)]
        self.assertEqual(len(bought), num(self.TID, 1))
        for cid in bought:
            tavern = stock_tavern(g, a, cid)
            g.buy_from_tavern(a, tavern)
        self.assertEqual(t._typewriter_left, 0)
        # 每次购买各得 1 份额外副本（不同卡 → 不触发三连合并）
        for cid in bought:
            self.assertEqual(hand_ids(a).count(cid), 2, cid)
        # 额度用尽: 再买不再复制
        tavern2 = stock_tavern(g, a, MURLOC_T2)
        g.buy_from_tavern(a, tavern2)
        self.assertEqual(hand_ids(a).count(MURLOC_T2), 1)

    def test_pool_exhausted_does_not_consume_budget(self):
        g = make_game(9203)
        a, b = g.heroes
        a.gold = 30
        t = bind(g, a, self.TID)
        tavern = stock_tavern(g, a, QUILBOAR_T1)
        drain(g, QUILBOAR_T1)                     # 池中已无额外副本
        self.assertEqual(g.minion_pool.available(QUILBOAR_T1), 0)
        self.assertTrue(g.buy_from_tavern(a, tavern))
        self.assertEqual(hand_ids(a), [QUILBOAR_T1])      # 副本落空
        self.assertEqual(t._typewriter_left, num(self.TID, 1))  # 额度未消耗
        # 正对照: 有池可取的购买照常复制
        tavern2 = stock_tavern(g, a, QUILBOAR_T2)
        g.buy_from_tavern(a, tavern2)
        self.assertEqual(hand_ids(a).count(QUILBOAR_T2), 2)
        self.assertEqual(t._typewriter_left, num(self.TID, 1) - 1)

    def test_opponent_buy_not_copied(self):
        g = make_game(9204)
        a, b = g.heroes
        a.gold = 30
        b.gold = 30
        t = bind(g, a, self.TID)
        tavern_b = stock_tavern(g, b, QUILBOAR_T1)
        b_before_pool = g.minion_pool.available(QUILBOAR_T1)
        self.assertTrue(g.buy_from_tavern(b, tavern_b))
        self.assertEqual(hand_ids(b), [QUILBOAR_T1])       # 对手无额外副本
        self.assertEqual(t._typewriter_left, num(self.TID, 1))
        # 正对照: 本人购买照常复制
        tavern_a = stock_tavern(g, a, QUILBOAR_T2)
        g.buy_from_tavern(a, tavern_a)
        self.assertEqual(hand_ids(a).count(QUILBOAR_T2), 2)
        self.assertGreater(b_before_pool, 0)

    def test_without_trinket_control(self):
        g = make_game(9205)
        a, b = g.heroes
        a.gold = 30
        tavern = stock_tavern(g, a, QUILBOAR_T1)
        self.assertTrue(g.buy_from_tavern(a, tavern))
        self.assertEqual(hand_ids(a), [QUILBOAR_T1])
        # 正对照: 另一个 game 绑定饰品后同步骤产生副本
        g2 = make_game(9205)
        a2, b2 = g2.heroes
        a2.gold = 30
        bind(g2, a2, self.TID)
        tavern2 = stock_tavern(g2, a2, QUILBOAR_T1)
        g2.buy_from_tavern(a2, tavern2)
        self.assertEqual(hand_ids(a2), [QUILBOAR_T1, QUILBOAR_T1])


# ══════════════ BG36_MagicItem_201 Lionfish Portrait ══════════════


class TestLionfishPortrait(unittest.TestCase):
    """Get a Lurking Lionfish；友方野兽攻击时 +num(0)/+num(1)。"""

    TID = LIONFISH

    def test_grants_related_card_and_consumes_pool(self):
        g = make_game(2011)
        a, b = g.heroes
        before = g.minion_pool.available(LIONFISH_CARD)
        bind(g, a, self.TID)
        self.assertEqual(hand_ids(a), [LIONFISH_CARD])
        self.assertEqual(g.minion_pool.available(LIONFISH_CARD), before - 1)
        self.assertEqual(hand_ids(b), [])

    def test_beast_attack_buffed_non_beast_not(self):
        g = make_game(2012)
        a, b = g.heroes
        beast = put(g, a, BEAST_T3)
        other = put(g, a, QUILBOAR_T1)
        bind(g, a, self.TID)
        g.events.fire(g, "before_attack", attacker=beast, defender=None)
        self.assertEqual(beast.atk, get_db().get(BEAST_T3).atk
                         + num(self.TID, 0))
        self.assertEqual(beast.health, get_db().get(BEAST_T3).health
                         + num(self.TID, 1))
        self.assertEqual(other.atk, get_db().get(QUILBOAR_T1).atk)
        self.assertEqual(other.health, get_db().get(QUILBOAR_T1).health)

    def test_opponent_beast_not_buffed(self):
        g = make_game(2013)
        a, b = g.heroes
        mine = put(g, a, BEAST_T3)
        theirs = put(g, b, BEAST_T3)
        bind(g, a, self.TID)
        g.events.fire(g, "before_attack", attacker=theirs, defender=None)
        self.assertEqual(theirs.atk, get_db().get(BEAST_T3).atk)
        # 正对照: 本人野兽照常
        g.events.fire(g, "before_attack", attacker=mine, defender=None)
        self.assertEqual(mine.atk, get_db().get(BEAST_T3).atk
                         + num(self.TID, 0))

    def test_recruit_phase_attack_triggers(self):
        g = make_game(2014)
        a, b = g.heroes
        beast = put(g, a, BEAST_T3)
        beast.set(GameTag.BASE_HEALTH, 50)
        beast.set(GameTag.HEALTH, 50)
        bind(g, a, self.TID)
        target = stock_tavern(g, a, QUILBOAR_T1)
        g.recruit_phase_attack(beast, target)
        self.assertFalse(beast.dead)
        self.assertEqual(beast.atk, get_db().get(BEAST_T3).atk
                         + num(self.TID, 0))

    def test_without_trinket_control(self):
        g = make_game(2015)
        a, b = g.heroes
        beast = put(g, a, BEAST_T3)
        g.events.fire(g, "before_attack", attacker=beast, defender=None)
        self.assertEqual(beast.atk, get_db().get(BEAST_T3).atk)
        # 正对照
        g2 = make_game(2015)
        a2, b2 = g2.heroes
        beast2 = put(g2, a2, BEAST_T3)
        bind(g2, a2, self.TID)
        g2.events.fire(g2, "before_attack", attacker=beast2, defender=None)
        self.assertGreater(beast2.atk, get_db().get(BEAST_T3).atk)


# ══════════════ BG36_MagicItem_206 Ominous Stone ══════════════


class TestOminousStone(unittest.TestCase):
    """Discover 一个 Tier 4 的众数类型随从并带 Dark Gift。"""

    TID = OMINOUS

    def test_options_are_tier4_most_common_type(self):
        g = make_game(2061)
        a, b = g.heroes
        put(g, a, BEAST_T3)
        put(g, a, BANANA_SLAMMA)
        put(g, a, MURLOC_T2)
        self.assertEqual(len(g.pending_choices), 0)
        pre = {d.id: g.minion_pool.available(d.id)
               for d in get_db().pool_minions()}
        bind(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices[0]
        self.assertEqual(choice.kind, "dark_gift")
        self.assertGreaterEqual(len(choice.options), 1)
        gifts = []
        for cid, gid in choice.options:
            cd = get_db().get(cid)
            self.assertEqual(cd.tech_level, 4)
            self.assertIn(cd.race, (Race.BEAST, Race.ALL))
            gifts.append(gid)
        self.assertEqual(len(set(gifts)), len(gifts))     # gift 互不相同
        picked = choice.options[0]
        g.pending_choices.pop(0).choose(0)
        ents = [e for e in a.hand if e.card_id == picked[0]]
        self.assertEqual(len(ents), 1)
        self.assertEqual(ents[0].get(GameTag.DARK_GIFT), picked[1])
        # 预留语义: 选中项净 -1（选项生成即 acquire、resolve 保留），
        # 未选选项 resolve 时回池（净 0）——对照 bind 前快照
        for cid, _gid in choice.options:
            after = g.minion_pool.available(cid)
            if cid == picked[0]:
                self.assertEqual(after, pre[cid] - 1, cid)
            else:
                self.assertEqual(after, pre[cid], cid)
        self.assertEqual(hand_ids(b), [])

    def test_empty_board_falls_back_to_any_tier4(self):
        g = make_game(2062)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 1)
        for cid, _gid in g.pending_choices[0].options:
            self.assertEqual(get_db().get(cid).tech_level, 4)

    def test_opponent_board_not_counted_for_mode(self):
        g = make_game(2063)
        a, b = g.heroes
        put(g, a, MURLOC_T2)                    # 本人 1 鱼人
        put(g, b, BEAST_T3)                     # 对手 2 野兽（不计入）
        put(g, b, BANANA_SLAMMA)
        bind(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 1)
        for cid, _gid in g.pending_choices[0].options:
            self.assertIn(get_db().get(cid).race, (Race.MURLOC, Race.ALL))

    def test_without_trinket_control(self):
        g = make_game(2064)
        a, b = g.heroes
        put(g, a, BEAST_T3)
        self.assertEqual(len(g.pending_choices), 0)
        # 正对照
        bind(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 1)


# ══════════════ BG36_MagicItem_208 Floating Candle Set ══════════════


class TestFloatingCandleSet(unittest.TestCase):
    """Spellcraft（208t）: Trigger a friendly minion's Deathrattle。"""

    TID = CANDLE

    def test_bind_grants_spellcraft_spell(self):
        g = make_game(2081)
        a, b = g.heroes
        bind(g, a, self.TID)
        spells = [e for e in a.hand if isinstance(e, Spell)]
        self.assertEqual([s.card_id for s in spells], [CANDLE_SPELL])
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))
        self.assertEqual(hand_ids(b), [])

    def test_next_turn_regenerates_exactly_one(self):
        g = make_game(2082)
        a, b = g.heroes
        bind(g, a, self.TID)
        # 绑定即得第一张（脚本 on_bind 的职责——突变后本断言失败）
        self.assertEqual(
            [e.card_id for e in a.hand if isinstance(e, Spell)],
            [CANDLE_SPELL])
        g.end_recruit_phase()
        spells = [e for e in a.hand
                  if isinstance(e, Spell) and e.card_id == CANDLE_SPELL]
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), 0)

    def test_target_candidates_require_deathrattle(self):
        g = make_game(2083)
        a, b = g.heroes
        bind(g, a, self.TID)
        plag = put(g, a, PLAGUERUNNER)
        put(g, a, QUILBOAR_T1)
        spell = [e for e in a.hand if e.card_id == CANDLE_SPELL][0]
        cands = spell.scripts.target_candidates(spell, g)
        self.assertEqual([m.card_id for m in cands], [PLAGUERUNNER])
        self.assertEqual(cands, [plag])

    def test_play_triggers_deathrattle(self):
        g = make_game(2084)
        a, b = g.heroes
        bind(g, a, self.TID)
        plag = put(g, a, PLAGUERUNNER)
        undead = put(g, a, UNDEAD_T2)
        opp_undead = put(g, b, UNDEAD_T2)
        atk_before = undead.atk
        spell = [e for e in a.hand if e.card_id == CANDLE_SPELL][0]
        self.assertTrue(g.play_spell(a, spell, target=plag))
        # Plaguerunner 亡语: 本人亡灵 +攻击；招募期（非战斗）取 num(1)
        # （"（+{1} if triggered outside combat!）"），且不消灭目标
        self.assertEqual(undead.atk, atk_before + num(PLAGUERUNNER, 1))
        self.assertFalse(plag.dead)
        self.assertEqual(opp_undead.atk, get_db().get(UNDEAD_T2).atk)

    def test_without_trinket_control(self):
        g = make_game(2085)
        a, b = g.heroes
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])
        # 正对照
        bind(g, a, self.TID)
        self.assertEqual(len([e for e in a.hand if isinstance(e, Spell)]), 1)


# ══════════════ BG36_MagicItem_211 Lovely Locket ══════════════


class TestLovelyLocket(unittest.TestCase):
    """对友方随从施法后，把同一法术随机再施于另一友方随从。"""

    TID = LOCKET

    def _cast(self, g, hero, card_id, target):
        sp = g.create_spell(card_id, controller=hero)
        hero.hand.append(sp)
        sp.zone = Zone.HAND
        return g.play_spell(hero, sp, target=target)

    def test_recast_on_another_friendly_minion(self):
        g = make_game(2111)
        a, b = g.heroes
        bind(g, a, self.TID)
        m1 = put(g, a, QUILBOAR_T1)
        m2 = put(g, a, QUILBOAR_T2)
        opp = put(g, b, QUILBOAR_T1)
        d = get_db().get(BANANA)
        self.assertTrue(self._cast(g, a, BANANA, m1))
        self.assertEqual(m1.atk, get_db().get(QUILBOAR_T1).atk + d.num(0))
        self.assertEqual(m1.health,
                         get_db().get(QUILBOAR_T1).health + d.num(1))
        self.assertEqual(m2.atk, get_db().get(QUILBOAR_T2).atk + d.num(0))
        self.assertEqual(m2.health,
                         get_db().get(QUILBOAR_T2).health + d.num(1))
        self.assertEqual(opp.atk, get_db().get(QUILBOAR_T1).atk)

    def test_single_minion_whiffs(self):
        g = make_game(2112)
        a, b = g.heroes
        bind(g, a, self.TID)
        only = put(g, a, QUILBOAR_T1)
        d = get_db().get(BANANA)
        self.assertTrue(self._cast(g, a, BANANA, only))
        # 无"另一个"目标 → 只结算原法术一次
        self.assertEqual(only.atk, get_db().get(QUILBOAR_T1).atk + d.num(0))
        # 正对照: 加入第二个友方随从后确实再施放
        second = put(g, a, QUILBOAR_T2)
        self._cast(g, a, BANANA, only)
        self.assertEqual(second.atk, get_db().get(QUILBOAR_T2).atk + d.num(0))

    def test_respects_spell_target_restrictions(self):
        g = make_game(2113)
        a, b = g.heroes
        bind(g, a, self.TID)
        u1 = put(g, a, UNDEAD_T2)
        u2 = put(g, a, UNDEAD_T2)
        beast = put(g, a, BANANA_SLAMMA)
        self.assertTrue(self._cast(g, a, BUTCHERING, u1))
        # 原法术消灭 u1；再施放只能落在合法第二亡灵
        self.assertFalse(u1 in a.board)
        self.assertFalse(u2 in a.board)
        self.assertIn(beast, a.board)                 # 非法目标（野兽）幸存
        self.assertEqual(beast.atk, get_db().get(BANANA_SLAMMA).atk)

    def test_recast_does_not_rebroadcast_card_played(self):
        g = make_game(2114)
        a, b = g.heroes
        bind(g, a, self.TID)
        m1 = put(g, a, QUILBOAR_T1)
        m2 = put(g, a, QUILBOAR_T2)
        seen = []
        g.events.register(Listener(
            event="card_played", owner=a,
            callback=lambda g, card=None, **kw: seen.append(card)))
        self._cast(g, a, BANANA, m1)
        # 效果确实发生（再施放落在 m2）
        self.assertEqual(m2.atk, get_db().get(QUILBOAR_T2).atk
                         + get_db().get(BANANA).num(0))
        # 但只广播了一次 card_played（cast_spell_effect 不广播 → 无递归）
        self.assertEqual(len(seen), 1)

    def test_recast_of_choose_one_spell_enqueues_second_choice(self):
        """Choose One 法术（BG31_880）再施放 → 再入队一个 choose_one。"""
        g = make_game(2117)
        a, b = g.heroes
        bind(g, a, self.TID)
        m1 = put(g, a, QUILBOAR_T1)
        m2 = put(g, a, QUILBOAR_T2)
        self._cast(g, a, "BG31_880", m1)
        kinds = [c.kind for c in g.pending_choices]
        self.assertEqual(kinds, ["choose_one", "choose_one"])
        while g.pending_choices:
            g.pending_choices.pop(0).choose(0)
        d = get_db().get("BG31_880")
        self.assertEqual(m1.atk, get_db().get(QUILBOAR_T1).atk + d.num(0))
        self.assertEqual(m2.atk, get_db().get(QUILBOAR_T2).atk + d.num(0))

    def test_opponent_cast_not_recast(self):
        g = make_game(2115)
        a, b = g.heroes
        bind(g, a, self.TID)
        mine1 = put(g, a, QUILBOAR_T2)
        mine2 = put(g, a, QUILBOAR_T1)
        theirs1 = put(g, b, QUILBOAR_T1)
        theirs2 = put(g, b, QUILBOAR_T2)
        d = get_db().get(BANANA)
        self._cast(g, b, BANANA, theirs1)
        # 对手施法不触发本饰品（mine1/mine2 均不变），对手第二个随从也不变
        self.assertEqual(mine1.atk, get_db().get(QUILBOAR_T2).atk)
        self.assertEqual(mine2.atk, get_db().get(QUILBOAR_T1).atk)
        self.assertEqual(theirs2.atk, get_db().get(QUILBOAR_T2).atk)
        # 正对照: 本人施法 → 再施放落在 mine2
        self._cast(g, a, BANANA, mine1)
        self.assertEqual(mine1.atk, get_db().get(QUILBOAR_T2).atk + d.num(0))
        self.assertEqual(mine2.atk, get_db().get(QUILBOAR_T1).atk + d.num(0))

    def test_without_trinket_control(self):
        g = make_game(2116)
        a, b = g.heroes
        m1 = put(g, a, QUILBOAR_T1)
        m2 = put(g, a, QUILBOAR_T2)
        d = get_db().get(BANANA)
        self._cast(g, a, BANANA, m1)
        self.assertEqual(m2.atk, get_db().get(QUILBOAR_T2).atk)
        # 正对照
        g2 = make_game(2116)
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        n1 = put(g2, a2, QUILBOAR_T1)
        n2 = put(g2, a2, QUILBOAR_T2)
        self._cast(g2, a2, BANANA, n1)
        self.assertEqual(n2.atk, get_db().get(QUILBOAR_T2).atk + d.num(0))


# ══════════════ BG36_MagicItem_217 Funeral Wreath ══════════════


class TestFuneralWreath(unittest.TestCase):
    """友方复生后入手白板副本（每场战斗 num(1) 次）。"""

    TID = WREATH
    # 无亡语/无入场触发的测试随从（避免亡语召唤与三连合并干扰计数）
    CARDS = (MURLOC_T2, QUILBOAR_T1, QUILBOAR_T2, NAGA_T3)

    def _reborn(self, g, hero, card_id, golden=False):
        m = put(g, hero, card_id, golden=golden)
        m.set(GameTag.REBORN, True)
        kill(g, m)
        return m

    def test_reborn_in_combat_grants_plain_copy(self):
        g = make_game(2171)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertEqual(t._wreath_left, num(self.TID, 1))
        pool_before = g.minion_pool.available(MURLOC_T2)
        with InCombat(g):
            m = self._reborn(g, a, MURLOC_T2)
            self.assertEqual(m.health, 1)             # 复生回归
            self.assertEqual(hand_ids(a), [MURLOC_T2])
        self.assertEqual(g.minion_pool.available(MURLOC_T2), pool_before - 1)
        self.assertEqual(t._wreath_left, num(self.TID, 1) - 1)

    def test_golden_reborn_gives_plain_base_copy(self):
        g = make_game(2172)
        a, b = g.heroes
        bind(g, a, self.TID)
        with InCombat(g):
            m = self._reborn(g, a, MURLOC_T2, golden=True)
            self.assertTrue(m.is_golden)
        self.assertEqual(hand_ids(a), [MURLOC_T2])     # 非金（"plain copy"）

    def test_full_hand_still_consumes_budget(self):
        """满手（副本入等待队列）仍扣额度——"({1} times per combat)"上限
        不得被满手绕过（2026-09-02 对抗审查证伪：6 次复生全排队、
        `_wreath_left` 仍为 3）。"""
        g = make_game(2175)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        while len(a.hand) < 10:
            a.hand.append(g.create_spell("BG28_168", controller=a))
        limit = num(self.TID, 1)
        with InCombat(g):
            self._reborn(g, a, MURLOC_T2)
        queued = [e for h, e in g.pending_hand_queue if h is a
                  and e.card_id == MURLOC_T2]
        self.assertEqual(len(queued), 1)
        self.assertEqual(t._wreath_left, limit - 1)

    def test_budget_caps_at_num1_per_combat(self):
        g = make_game(2173)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        limit = num(self.TID, 1)
        cards = self.CARDS[:limit + 1]
        self.assertGreaterEqual(len(cards), limit + 1)
        with InCombat(g):
            for cid in cards:
                self._reborn(g, a, cid)
        got = [cid for cid in hand_ids(a) if cid in cards]
        self.assertEqual(got, list(cards[:limit]))     # 额度封顶
        self.assertNotIn(cards[limit], hand_ids(a))
        self.assertEqual(t._wreath_left, 0)

    def test_start_of_combat_resets_budget(self):
        g = make_game(2174)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        limit = num(self.TID, 1)
        with InCombat(g):
            for cid in self.CARDS[:limit]:
                self._reborn(g, a, cid)
        self.assertEqual(t._wreath_left, 0)
        g.run_combat(a, b)                            # 真实 SoC 重置
        self.assertEqual(t._wreath_left, limit)
        with InCombat(g):
            self._reborn(g, a, self.CARDS[limit])
        self.assertIn(self.CARDS[limit], hand_ids(a))
        self.assertEqual(
            len([c for c in hand_ids(a) if c in self.CARDS]), limit + 1)

    def test_out_of_combat_reborn_no_copy(self):
        g = make_game(2175)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self._reborn(g, a, MURLOC_T2)                  # 非战斗
        self.assertEqual(hand_ids(a), [])
        self.assertEqual(t._wreath_left, num(self.TID, 1))
        # 正对照: 战斗内同步骤发放
        with InCombat(g):
            self._reborn(g, a, QUILBOAR_T1)
        self.assertEqual(hand_ids(a), [QUILBOAR_T1])

    def test_opponent_reborn_not_copied(self):
        g = make_game(2176)
        a, b = g.heroes
        bind(g, a, self.TID)
        with InCombat(g):
            self._reborn(g, b, MURLOC_T2)
        self.assertEqual(hand_ids(a), [])
        self.assertEqual(hand_ids(b), [])
        # 正对照: 本人复生照常
        with InCombat(g):
            self._reborn(g, a, QUILBOAR_T1)
        self.assertEqual(hand_ids(a), [QUILBOAR_T1])

    def test_without_trinket_control(self):
        g = make_game(2177)
        a, b = g.heroes
        with InCombat(g):
            self._reborn(g, a, MURLOC_T2)
        self.assertEqual(hand_ids(a), [])
        # 正对照
        g2 = make_game(2177)
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        with InCombat(g2):
            self._reborn(g2, a2, MURLOC_T2)
        self.assertEqual(hand_ids(a2), [MURLOC_T2])


# ══════════════ BG36_MagicItem_301 Lockbox Portrait ══════════════


class TestLockboxPortrait(unittest.TestCase):
    """Get a Lockbox；已有则提前 num(0) 回合开启；每回合开始重复。"""

    TID = LOCKBOX

    def _lockbox_id(self):
        import hsrl2.constants as C
        return C.LOCKBOX_CARD_ID

    def test_bind_grants_lockbox_with_default_timer(self):
        g = make_game(3011)
        a, b = g.heroes
        bind(g, a, self.TID)
        lid = self._lockbox_id()
        boxes = [e for e in a.hand if e.card_id == lid]
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0].get(GameTag.LOCKBOX_TURNS_LEFT),
                         num(lid, 0))
        self.assertEqual(hand_ids(b), [])

    def test_existing_lockbox_opens_sooner(self):
        g = make_game(3012)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        lid = self._lockbox_id()
        g.run_script_hook(t, "start_of_turn")
        boxes = [e for e in a.hand if e.card_id == lid]
        self.assertEqual(len(boxes), 1)               # 不重复获取
        self.assertEqual(boxes[0].get(GameTag.LOCKBOX_TURNS_LEFT),
                         num(lid, 0) - num(self.TID, 0))

    def test_full_hand_does_not_requeue(self):
        """满手绑定: Lockbox 在等待队列，也不得每回合再排一份。

        旧实现只扫 `hero.hand` → 每个 SoT 再排一份（实测 queue
        1→2→3→4、事后一次性入手多张开金卡）——本条为突变对照。
        """
        g = make_game(3015)
        a, b = g.heroes
        lid = self._lockbox_id()
        while len(a.hand) < 10:                       # 填满手牌
            a.hand.append(g.create_spell("BG28_168", controller=a))
        t = bind(g, a, self.TID)
        queued = [e for h, e in g.pending_hand_queue if h is a]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].card_id, lid)
        for _ in range(3):
            g.run_script_hook(t, "start_of_turn")
        queued = [e for h, e in g.pending_hand_queue if h is a]
        self.assertEqual(len(queued), 1)               # 不重复排队

    def test_opens_when_timer_reaches_zero(self):
        g = make_game(3013)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        lid = self._lockbox_id()
        base_pool = {d.id: g.minion_pool.available(d.id)
                     for d in get_db().pool_minions()}
        per = num(self.TID, 0)
        steps = -(-num(lid, 0) // per)                # 向上取整
        for _ in range(steps):
            g.run_script_hook(t, "start_of_turn")
        self.assertEqual([e for e in a.hand if e.card_id == lid], [])
        golden = [e for e in a.hand
                  if isinstance(e, Minion) and getattr(e, "is_golden", False)]
        self.assertEqual(len(golden), 1)
        # 金色开启产物按非三连金口径回池 1 份基础副本
        base = golden[0].get(GameTag.TRIPLE_BASE_CARD_ID)
        self.assertIsNotNone(base)
        got = min(3, base_pool[base])                 # _open_lockbox 口径
        self.assertEqual(g.minion_pool.available(base), base_pool[base] - got)

    def test_start_of_turn_repeats(self):
        g = make_game(3014)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        lid = self._lockbox_id()

        def left():
            boxes = [e for e in a.hand if e.card_id == lid]
            return (boxes[0].get(GameTag.LOCKBOX_TURNS_LEFT)
                    if boxes else None)

        first = left()
        self.assertEqual(first, num(lid, 0))
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(left(), first - num(self.TID, 0))
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(left(), first - 2 * num(self.TID, 0))
        self.assertEqual(hand_ids(b), [])

    def test_without_trinket_control(self):
        g = make_game(3015)
        a, b = g.heroes
        lid = self._lockbox_id()
        self.assertEqual([e for e in a.hand if e.card_id == lid], [])
        # 正对照
        bind(g, a, self.TID)
        self.assertEqual(len([e for e in a.hand if e.card_id == lid]), 1)


# ══════════════ BG36_MagicItem_302 Gold Mallet ══════════════


class TestGoldMallet(unittest.TestCase):
    """EoT: 全体随从 +(num(0)+GMP)/+(num(1)+GMP)。"""

    TID = MALLET

    def test_base_buff_without_golden(self):
        g = make_game(3021)
        a, b = g.heroes
        mine = put(g, a, QUILBOAR_T1)
        theirs = put(g, b, QUILBOAR_T1)
        t = bind(g, a, self.TID)
        self.assertEqual(a.get(GameTag.GOLDEN_MINIONS_PLAYED, 0), 0)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(mine.atk, get_db().get(QUILBOAR_T1).atk
                         + num(self.TID, 0))
        self.assertEqual(mine.health, get_db().get(QUILBOAR_T1).health
                         + num(self.TID, 1))
        self.assertEqual(theirs.atk, get_db().get(QUILBOAR_T1).atk)

    def test_improves_by_golden_played(self):
        g = make_game(3022)
        a, b = g.heroes
        mine = put(g, a, QUILBOAR_T2)
        t = bind(g, a, self.TID)
        golden = g.create_minion(QUILBOAR_T1, controller=a, golden=True)
        a.hand.append(golden)
        golden.zone = Zone.HAND
        self.assertTrue(g.play_minion(a, golden))
        self.assertEqual(a.get(GameTag.GOLDEN_MINIONS_PLAYED, 0), 1)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(mine.atk, get_db().get(QUILBOAR_T2).atk
                         + num(self.TID, 0) + 1)
        self.assertEqual(mine.health, get_db().get(QUILBOAR_T2).health
                         + num(self.TID, 1) + 1)

    def test_opponent_golden_not_counted(self):
        g = make_game(3023)
        a, b = g.heroes
        mine = put(g, a, QUILBOAR_T2)
        t = bind(g, a, self.TID)
        golden = g.create_minion(QUILBOAR_T1, controller=b, golden=True)
        b.hand.append(golden)
        golden.zone = Zone.HAND
        g.play_minion(b, golden)
        self.assertEqual(a.get(GameTag.GOLDEN_MINIONS_PLAYED, 0), 0)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(mine.atk, get_db().get(QUILBOAR_T2).atk
                         + num(self.TID, 0))
        # 正对照: 本人金色计入
        own = g.create_minion(QUILBOAR_T1, controller=a, golden=True)
        a.hand.append(own)
        own.zone = Zone.HAND
        g.play_minion(a, own)
        before = mine.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(mine.atk, before + num(self.TID, 0) + 1)

    def test_persists_across_turns(self):
        g = make_game(3024)
        a, b = g.heroes
        mine = put(g, a, QUILBOAR_T2)
        t = bind(g, a, self.TID)
        golden = g.create_minion(QUILBOAR_T1, controller=a, golden=True)
        a.hand.append(golden)
        golden.zone = Zone.HAND
        g.play_minion(a, golden)
        g.run_script_hook(t, "end_of_turn")
        first = mine.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(mine.atk, first + num(self.TID, 0) + 1)

    def test_empty_board_whiffs(self):
        g = make_game(3025)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertIsNone(g.run_script_hook(t, "end_of_turn"))
        # 正对照: 放入随从后生效
        m = put(g, a, QUILBOAR_T1)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(m.atk, get_db().get(QUILBOAR_T1).atk
                         + num(self.TID, 0))

    def test_without_trinket_control(self):
        g = make_game(3026)
        a, b = g.heroes
        m = put(g, a, QUILBOAR_T1)
        g.events.fire(g, "end_of_turn", turn=1)
        self.assertEqual(m.atk, get_db().get(QUILBOAR_T1).atk)
        # 正对照
        g2 = make_game(3026)
        a2, b2 = g2.heroes
        m2 = put(g2, a2, QUILBOAR_T1)
        t2 = bind(g2, a2, self.TID)
        g2.run_script_hook(t2, "end_of_turn")
        self.assertGreater(m2.atk, get_db().get(QUILBOAR_T1).atk)


# ══════════════ BG36_MagicItem_303 Glass of Perspective ══════════════


class TestGlassOfPerspective(unittest.TestCase):
    """Get a random Choose One card；每回合开始再来一张。"""

    TID = GLASS

    def _sets(self):
        from hsrl2.scripts.batches.batch_rally2 import (
            CHOOSE_ONE_MINION_IDS, CHOOSE_ONE_SPELL_IDS)
        return CHOOSE_ONE_MINION_IDS, CHOOSE_ONE_SPELL_IDS

    def test_bind_grants_choose_one_card_from_sets(self):
        g = make_game(3031)
        a, b = g.heroes
        minions, spells = self._sets()
        self.assertEqual(hand_ids(a), [])
        pre_minion = {cid: g.minion_pool.available(cid) for cid in minions}
        pre_spell = {cid: g.spell_pool.available(cid) for cid in spells}
        bind(g, a, self.TID)
        self.assertEqual(len(a.hand), 1)
        cid = a.hand[0].card_id
        self.assertIn(cid, set(minions) | set(spells))
        # 池记账: 随从占 minion_pool / 池法术占 spell_pool（各 -1）
        if get_db().get(cid).is_pool_spell:
            self.assertEqual(g.spell_pool.available(cid), pre_spell[cid] - 1)
        else:
            self.assertEqual(g.minion_pool.available(cid),
                             pre_minion[cid] - 1)
        self.assertEqual(hand_ids(b), [])

    def test_start_of_turn_grants_another(self):
        g = make_game(3032)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertEqual(len(a.hand), 1)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(a.hand), 2)
        self.assertEqual(hand_ids(b), [])

    def test_pools_exhausted_whiffs(self):
        g = make_game(3033)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        minions, spells = self._sets()
        for cid in minions:
            drain(g, cid)
        for cid in spells:
            while g.spell_pool.acquire(cid):
                pass
        before = len(a.hand)
        self.assertIsNone(g.run_script_hook(t, "start_of_turn"))
        self.assertEqual(len(a.hand), before)
        # 正对照: 补充一张池卡后又可获取
        g.minion_pool.release(sorted(minions)[0], 1)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(a.hand[-1].card_id, sorted(minions)[0])

    def test_carddef_ids_are_pool_choose_one(self):
        """结构/漂移守护: 常量集 id 必须在 db 且为池卡（batch_rally2 集）。"""
        minions, spells = self._sets()
        self.assertTrue(minions and spells)
        for cid in minions:
            d = get_db().get(cid)
            self.assertIsNotNone(d, cid)
            self.assertTrue(d.is_pool_minion, cid)
            self.assertIn("choose_one", d.keywords)
        for cid in spells:
            d = get_db().get(cid)
            self.assertIsNotNone(d, cid)
            self.assertTrue(d.is_pool_spell, cid)

    def test_without_trinket_control(self):
        g = make_game(3034)
        a, b = g.heroes
        self.assertEqual(hand_ids(a), [])
        # 正对照
        bind(g, a, self.TID)
        self.assertEqual(len(a.hand), 1)


# ══════════════ BG36_MagicItem_309 Wax Lance ══════════════


class TestWaxLance(unittest.TestCase):
    """Discover 一个 Tier 7 随从并带 Dark Gift。"""

    TID = WAX_LANCE

    def test_options_are_tier7_with_distinct_gifts(self):
        g = make_game(3091)
        a, b = g.heroes
        self.assertEqual(len(g.pending_choices), 0)
        bind(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices[0]
        self.assertEqual(choice.kind, "dark_gift")
        # Discover 3 选项: T7 池 12 张 → 恰 3 个（旧实现无重抽时曾退化为
        # 2 个——2026-09-02 对抗审查证伪; 本条即回归守卫）
        self.assertEqual(len(choice.options), 3)
        gifts = []
        for cid, gid in choice.options:
            self.assertEqual(get_db().get(cid).tech_level, 7)
            gifts.append(gid)
        self.assertEqual(len(set(gifts)), len(gifts))

    def test_giftless_candidate_is_redrawn(self):
        """某候选配不出合法 gift → 换随从重抽（选项数不退化）。

        直接以 T7 全员为候选（确定性入口）: 旧实现
        `_pair_gift_options` 无重抽 → 提供 < 3 个选项。
        """
        from hsrl2.scripts.batches.batch_trinkets20 import (
            _dark_gift_discover)
        g = make_game(3096)
        a, b = g.heroes
        t7 = [d.id for d in get_db().pool_minions() if d.tech_level == 7]
        self.assertGreaterEqual(len(t7), 4)
        self.assertEqual(_dark_gift_discover(g, a, t7), 3)
        choice = g.pending_choices[0]
        self.assertEqual(len(choice.options), 3)
        for cid, gid in choice.options:
            self.assertIsInstance(gid, str)
            self.assertEqual(get_db().get(cid).tech_level, 7)

    def test_resolve_grants_tier7_with_gift(self):
        g = make_game(3092)
        a, b = g.heroes
        pre = {d.id: g.minion_pool.available(d.id)
               for d in get_db().pool_minions()}
        bind(g, a, self.TID)
        choice = g.pending_choices[0]
        picked = choice.options[0]
        g.pending_choices.pop(0).choose(0)
        ents = [e for e in a.hand if e.card_id == picked[0]]
        self.assertEqual(len(ents), 1)
        self.assertEqual(ents[0].get(GameTag.DARK_GIFT), picked[1])
        self.assertEqual(get_db().get(picked[0]).tech_level, 7)
        for cid, _gid in choice.options:
            after = g.minion_pool.available(cid)
            if cid == picked[0]:
                self.assertEqual(after, pre[cid] - 1, cid)
            else:
                self.assertEqual(after, pre[cid], cid)
        self.assertEqual(hand_ids(b), [])

    def test_empty_tier7_pool_whiffs(self):
        g = make_game(3093)
        a, b = g.heroes
        for d in get_db().pool_minions():
            if d.tech_level == 7:
                drain(g, d.id)
        bind(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 0)
        self.assertEqual(hand_ids(a), [])
        # 正对照: 池中恢复 1 份 T7 → 重新产生三选一
        g2 = make_game(3093)
        a2, b2 = g2.heroes
        t7 = [d.id for d in get_db().pool_minions()
              if d.tech_level == 7 and g2.minion_pool.available(d.id) > 0]
        self.assertTrue(t7)
        bind(g2, a2, self.TID)
        self.assertEqual(len(g2.pending_choices), 1)

    def test_without_trinket_control(self):
        g = make_game(3094)
        a, b = g.heroes
        self.assertEqual(len(g.pending_choices), 0)
        # 正对照
        bind(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 1)


# ══════════════ BG36_MagicItem_361 Myrmidon Sticker ══════════════


class TestMyrmidonSticker(unittest.TestCase):
    """SoC: 最左与最右纳迦属性翻倍。"""

    TID = MYRMIDON

    def test_soc_doubles_left_and_right_naga(self):
        g = make_game(3611)
        a, b = g.heroes
        left = put(g, a, NAGA_T1)
        put(g, a, QUILBOAR_T2)
        put(g, a, NAGA_T3)
        put(g, b, NAGA_T1)
        t = bind(g, a, self.TID)
        out = soc_probe(g, t)
        g.run_combat(a, b)
        board = dict((cid, (atk, hp)) for cid, atk, hp in out[a])
        d1 = get_db().get(NAGA_T1)
        d2 = get_db().get(NAGA_T3)
        dm = get_db().get(QUILBOAR_T2)
        self.assertEqual(board[NAGA_T1], (2 * d1.atk, 2 * d1.health))
        self.assertEqual(board[NAGA_T3], (2 * d2.atk, 2 * d2.health))
        self.assertEqual(board[QUILBOAR_T2], (dm.atk, dm.health))
        # 对手纳迦不被翻倍（owner 隔离）
        self.assertEqual(out[b], [(NAGA_T1, d1.atk, d1.health)])
        self.assertIn(left, a.board)

    def test_single_naga_doubled_once(self):
        g = make_game(3612)
        a, b = g.heroes
        only = put(g, a, NAGA_T3)
        t = bind(g, a, self.TID)
        out = soc_probe(g, t)
        g.run_combat(a, b)
        board = dict((cid, (atk, hp)) for cid, atk, hp in out[a])
        self.assertEqual(board[NAGA_T3], (2 * get_db().get(NAGA_T3).atk,
                                          2 * get_db().get(NAGA_T3).health))
        self.assertIn(only, a.board)

    def test_no_naga_whiffs(self):
        g = make_game(3613)
        a, b = g.heroes
        put(g, a, QUILBOAR_T1)
        t = bind(g, a, self.TID)
        out = soc_probe(g, t)
        g.run_combat(a, b)
        board = dict((cid, (atk, hp)) for cid, atk, hp in out[a])
        self.assertEqual(board[QUILBOAR_T1], (get_db().get(QUILBOAR_T1).atk,
                                              get_db().get(QUILBOAR_T1).health))
        # 正对照: 同 setup 加入纳迦后被翻倍
        g2 = make_game(3613)
        a2, b2 = g2.heroes
        put(g2, a2, QUILBOAR_T1)
        put(g2, a2, NAGA_T3)
        t2 = bind(g2, a2, self.TID)
        out2 = soc_probe(g2, t2)
        g2.run_combat(a2, b2)
        board2 = dict((cid, (atk, hp)) for cid, atk, hp in out2[a2])
        d = get_db().get(NAGA_T3)
        self.assertEqual(board2[NAGA_T3], (2 * d.atk, 2 * d.health))

    def test_without_trinket_control(self):
        g = make_game(3614)
        a, b = g.heroes
        put(g, a, NAGA_T3)
        out = soc_probe(g, a)
        g.run_combat(a, b)
        board = dict((cid, (atk, hp)) for cid, atk, hp in out[a])
        self.assertEqual(board[NAGA_T3], (get_db().get(NAGA_T3).atk,
                                          get_db().get(NAGA_T3).health))
        # 正对照
        g2 = make_game(3614)
        a2, b2 = g2.heroes
        put(g2, a2, NAGA_T3)
        t2 = bind(g2, a2, self.TID)
        out2 = soc_probe(g2, t2)
        g2.run_combat(a2, b2)
        board2 = dict((cid, (atk, hp)) for cid, atk, hp in out2[a2])
        self.assertEqual(board2[NAGA_T3], (2 * get_db().get(NAGA_T3).atk,
                                           2 * get_db().get(NAGA_T3).health))


# ══════════════ 注册表 / DEFERRED 台账 ══════════════


class TestRegistryAndDeferredLedger(unittest.TestCase):
    """注册清单与 DEFERRED 台账守卫（结构性）。"""

    def test_implemented_registered(self):
        for cid in IMPLEMENTED:
            self.assertIn(cid, REGISTRY, cid)

    def test_deferred_not_registered(self):
        for cid in DEFERRED:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_spellcraft_spell_registered(self):
        self.assertIn(CANDLE_SPELL, REGISTRY)
        self.assertTrue(getattr(REGISTRY[CANDLE_SPELL], "needs_target", False))

    def test_batch_id_partition(self):
        """结构性: 注册 12 项（11 饰品 + 1 法术），DEFERRED 0 项 +
        迁出 4 项（batch_unlock_final），本批范围 16 张不变。

        BG36_MagicItem_204 已由 batch_trinkets26 注册（destroy 事件）。
        """
        self.assertEqual(len(IMPLEMENTED), 12)
        self.assertEqual(len(DEFERRED), 0)
        self.assertEqual(len(MIGRATED), 4)
        self.assertEqual(len(set(IMPLEMENTED) | set(DEFERRED)
                             | set(MIGRATED)), 16)


if __name__ == "__main__":
    unittest.main()
