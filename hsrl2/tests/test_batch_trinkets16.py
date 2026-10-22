"""批次 trinkets16 行为层测试（13 张注册饰品, 作业单 2026-09-12）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）;
    另有 1 例走真实商店 `_offer_trinkets` 三选一 + PendingChoice.choose
  - 关联卡授予: `game.grant_trinket_related_card` /
    `grant_card_copy_to_hand`（RULES §7.4.6）
  - 战斗: 真实 `game.run_combat`（SoC 阶段）; 因战后棋盘快照复原
    （RULES §3.5——SoC 增益仅本场），战斗内断言用监听
    `start_of_combat`（引擎在 SoC 钩子**之后**逐英雄广播）探针
  - 施放: 真实 `game.play_spell`（`tavern_spell_cast` 广播）
  - 购买: 真实 `game.buy_from_tavern`（`minion_bought` 广播）
  - 刷新: 真实 `game.refresh_tavern`（免费刷新额度消费点）
  - 回合: 真实 `game.end_recruit_phase` / `turn_start` 广播
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法）: 每个测试方法至少含一条**正效果**断言
（负对照与正对照同方法内，或对同事件做正/负双探测），owner 隔离
（2 英雄），跨回合语义，池空/无候选落空，一次性语义，
CardDef.num 双向钉死。
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
MURLOC_T2 = "BG22_202"        # Tad 2/2 T2 鱼人（池）
QUILBOAR_T1 = "BG20_100"      # Razorfen Geomancer 2/1 T1 野猪人（池）
QUILBOAR_T2 = "BG20_101"      # Roadboar 2/4 T2 野猪人（池）
NAGA_T1 = "BG23_000"          # Mini-Myrmidon 1/3 T1 纳迦（池）
NAGA_T3 = "BG23_004"          # Deep-Sea Angler 2/3 T3 纳迦（池）
DEMON_T5 = "BG21_004"         # Insatiable Ur'zul 4/6 T5 恶魔（池）
BEAST_T3 = "BG25_806"         # Sly Raptor 3/2 T3 野兽（池）
TAVERN_SPELL = "BG28_168"     # Shiny Ring T3 池法术
VANILLA_GEM = "BG20_GEM"      # 香草鲜血宝石（非池法术）

# 本批 id
CLIFFDIVER = "BG32_MagicItem_890"
BLESSING = "BG32_MagicItem_894"
COMPASS = "BG32_MagicItem_901"
HOGWASH = "BG32_MagicItem_904"
ARTANIS = "BG32_MagicItem_906"
PANPIPES = "BG32_MagicItem_922"
MORGL = "BG32_MagicItem_926"
AZSHARAN = "BG32_MagicItem_931"
ANEMONE = "BG32_MagicItem_932"
DAGGER = "BG32_MagicItem_934"
EMPOWERMENT = "BG32_MagicItem_944"
GRITTY = "BG32_MagicItem_950"
PENDANT = "BG32_MagicItem_951"

# 关联卡（数据链）
NATURAL_BLESSING = "BG28_845"
AZERITE = "BG28_169"
MOTHERSHIP = "BG31_HERO_802pt7"
TIDE_ORACLE = "BG27_513"
GRITTY_HEADHUNTER = "BG31_822"
MARAUDERS_CONTRACT = "BG31_891"

# DEFERRED（台账见 batch_trinkets16 模块 docstring）
# BG32_MagicItem_920 Thaumaturgist Portrait 已由 batch_trinkets23 注册
# （`add_permanent_spellcraft_rule` 规则原语）——迁出本台账
DEFERRED = (
    # BG32_MagicItem_933 Weary Portrait 已由 batch_trinkets37 注册
    # （2026-09-14: 载荷已在 + Reinvigoration 加 permanent_spellcraft 分支
    #  → Reborn 永久保留）——迁出本台账
)
# 891/892/925 已由 batch_trinkets30 注册（2026-09-15: `BONUS_KEYWORD_TAGS`
# 六集定义域 + `grant_bonus_keyword` + `actions.TriggerBattlecry`）——迁出
# DEFERRED 台账，仍计入本批 19 张范围
# 已由 batch_unlock_final 注册（2026-09-15: minion_consumed 来源区域载荷 /
# last_minion_died 触发点）——迁出 DEFERRED 台账，仍计入本批 19 张范围
MIGRATED = (
    "BG32_MagicItem_891",   # Finley's Helmet（batch_trinkets30）
    "BG32_MagicItem_892",   # Vibrant Bubble（batch_trinkets30）
    "BG32_MagicItem_925",   # Hackerfin Portrait（batch_trinkets30）
    "BG32_MagicItem_902",   # Statue of Hir'eek
    "BG32_MagicItem_907",   # S'Thara Sticker
    "BG32_MagicItem_933",   # Weary Portrait（batch_trinkets37, 2026-09-14）
)

IMPLEMENTED = (CLIFFDIVER, BLESSING, COMPASS, HOGWASH, ARTANIS, PANPIPES,
               MORGL, AZSHARAN, ANEMONE, DAGGER, EMPOWERMENT, GRITTY,
               PENDANT)

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


def put(game: Game, hero: Hero, card_id: str, position=None, **kw) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    for tag, val in kw.items():
        m.set(getattr(GameTag, tag.upper()), val)
    assert game.summon(hero, m, position)
    return m


def tank(game: Game, hero: Hero, card_id: str, *, atk: int = 2,
         health: int = 60) -> Minion:
    """高耐久测试随从（避免战斗测试里出现死亡干扰计数）。"""
    m = game.create_minion(card_id, controller=hero)
    m.set(GameTag.BASE_ATK, atk)
    m.set(GameTag.BASE_HEALTH, health)
    m.set(GameTag.ATK, atk)
    m.set(GameTag.HEALTH, health)
    assert game.summon(hero, m)
    return m


def hand_minions(hero: Hero) -> list:
    return [e for e in hero.hand if isinstance(e, Minion)]


def hand_spells(hero: Hero, card_id: str = None) -> list:
    out = [e for e in hero.hand if isinstance(e, Spell)]
    if card_id is not None:
        out = [e for e in out if e.card_id == card_id]
    return out


def drain_pool(game: Game, card_id: str) -> int:
    n = 0
    while game.minion_pool.acquire(card_id):
        n += 1
    return n


def soak_spell(game: Game, card_id: str) -> None:
    """排空某池法术的全部副本。"""
    while game.spell_pool.acquire(card_id):
        pass


def _stock_tavern_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    """把一只随从放进酒馆（按池记账: 从池取 1 份——官方刷新路径同款）。"""
    game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def soc_probe(game: Game, owner, out: dict) -> None:
    """战斗内探测 SoC 效果（引擎在全部 SoC 钩子之后逐英雄广播）。

    战后棋盘由 `run_combat` 快照复原（RULES §3.5），故 SoC 数值只能在
    战斗内观察——监听 `start_of_combat`（`hero=` 载荷）是本仓既有做法。
    `out["boards"][hero]` 在**每个**英雄的 SoC 广播点各记录一次，
    因此可同时断言"本人获得 / 对手未获得"（owner 隔离正负对照）。
    """
    out.setdefault("boards", {})

    def cb(g, hero=None, **kw):
        if hero is None:
            return
        out["boards"][hero] = [
            (m.card_id, m.atk, m.health, m.get(GameTag.GEMS_PLAYED_ON, 0))
            for m in hero.board]

    game.events.register(Listener(event="start_of_combat", owner=owner,
                                  callback=cb))


def fire_turn_start(game: Game, hero: Hero, turn: int) -> None:
    """广播真实 turn_start（引擎 game.py:271 的载荷形状）。"""
    game.events.fire(game, "turn_start", turn=turn, hero=hero)


# ══════════════ BG32_MagicItem_890 Cliffdiver Sticker ══════════════


class TestCliffdiverSticker(unittest.TestCase):
    """EoT: 最左随从 +num(0)/+num(1)，按本回合战吼触发次数递增。"""

    TID = CLIFFDIVER

    def _setup(self, seed, with_trinket=True):
        g = make_game(seed)
        a, b = g.heroes
        left = put(g, a, QUILBOAR_T2, position=0)
        put(g, a, QUILBOAR_T1, position=1)
        t = bind(g, a, self.TID) if with_trinket else None
        return g, a, b, left, t

    def test_no_battlecry_gives_base(self):
        g, a, b, left, t = self._setup(1901)
        d = get_db().get(self.TID)
        base = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, base + d.num(0))
        self.assertEqual(left.health, 4 + d.num(1))

    def test_each_battlecry_improves(self):
        g, a, b, left, t = self._setup(1902)
        d = get_db().get(self.TID)
        base = left.atk
        hero_health = left.health
        g.events.fire(g, "battlecry_trigger", minion=left)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, base + 2 * d.num(0))       # 1 次 → ×2
        self.events_one_more(g, a, t, left, d, base, hero_health)

    def events_one_more(self, g, a, t, left, d, base, hero_health):
        """正对照: 第 2 次战吼 → ×3（同方法内的正向差分）。"""
        g.events.fire(g, "battlecry_trigger", minion=left)
        before = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, before + 3 * d.num(0))

    def test_counter_resets_on_turn_start(self):
        g, a, b, left, t = self._setup(1903)
        d = get_db().get(self.TID)
        g.events.fire(g, "battlecry_trigger", minion=left)
        g.events.fire(g, "battlecry_trigger", minion=left)
        fire_turn_start(g, a, 2)
        before = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, before + d.num(0))          # 归零 → ×1

    def test_opponent_battlecry_not_counted(self):
        g, a, b, left, t = self._setup(1904)
        d = get_db().get(self.TID)
        opp = put(g, b, QUILBOAR_T1)
        for _ in range(3):
            g.events.fire(g, "battlecry_trigger", minion=opp)
        before = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, before + d.num(0))          # 对手不计
        g.events.fire(g, "battlecry_trigger", minion=left)     # 正对照
        mid = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, mid + 2 * d.num(0))

    def test_empty_board_whiffs(self):
        g = make_game(1905)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertIsNone(g.run_script_hook(t, "end_of_turn"))
        # 正对照: 同回合放入随从后确实生效
        d = get_db().get(self.TID)
        m = put(g, a, QUILBOAR_T2)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(m.atk, get_db().get(QUILBOAR_T2).atk + d.num(0))

    def test_without_trinket_control(self):
        g, a, b, left, t = self._setup(1906, with_trinket=False)
        before = left.atk
        g.events.fire(g, "battlecry_trigger", minion=left)
        self.assertEqual(left.atk, before)
        g2, a2, b2, left2, t2 = self._setup(1906)             # 正对照
        g2.run_script_hook(t2, "end_of_turn")
        self.assertGreater(left2.atk, before)

    def test_shop_purchase_binds_effect(self):
        g = make_game(1907)
        a, b = g.heroes
        left = put(g, a, QUILBOAR_T2, position=0)
        a.gold = 50
        g._offer_trinkets(a, "lesser")
        choice = g.pending_choices.pop(0)
        choice.options = [get_db().get(self.TID)]
        choice.choose(0)
        t = a.trinkets[-1]
        d = get_db().get(self.TID)
        before = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, before + d.num(0))


# ══════════════ BG32_MagicItem_894 Blessing Portrait ══════════════


class TestBlessingPortrait(unittest.TestCase):
    """Get Natural Blessing; 每回合再来; 本人 Natural Blessing 影响手牌。"""

    TID = BLESSING

    def _setup(self, seed, with_trinket=True):
        g = make_game(seed)
        a, b = g.heroes
        t = bind(g, a, self.TID) if with_trinket else None
        return g, a, b, t

    def test_grants_pool_spell_and_consumes_pool(self):
        g = make_game(1894)
        a, b = g.heroes
        before = g.spell_pool.available(NATURAL_BLESSING)
        t = bind(g, a, self.TID)
        self.assertEqual(len(hand_spells(a, NATURAL_BLESSING)), 1)
        self.assertEqual(g.spell_pool.available(NATURAL_BLESSING),
                         before - 1)

    def test_start_of_turn_grants_another(self):
        g, a, b, t = self._setup(1895)
        self.assertEqual(len(hand_spells(a, NATURAL_BLESSING)), 1)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(hand_spells(a, NATURAL_BLESSING)), 2)

    def test_pool_exhausted_card_definition_membership(self):
        g = make_game(1896)
        a, b = g.heroes
        self.assertTrue(get_db().get(NATURAL_BLESSING).is_pool_spell)
        soak_spell(g, NATURAL_BLESSING)
        self.assertEqual(g.spell_pool.available(NATURAL_BLESSING), 0)
        t = bind(g, a, self.TID)
        self.assertEqual(len(hand_spells(a, NATURAL_BLESSING)), 0)
        self.assertIsNone(g.run_script_hook(t, "start_of_turn"))

    def test_hand_minions_of_shared_type_get_buff(self):
        g, a, b, t = self._setup(1897)
        hand_murloc = g.create_minion(MURLOC_T2, controller=a)
        a.add_to_hand(hand_murloc)
        hand_beast = g.create_minion(BEAST_T3, controller=a)
        a.add_to_hand(hand_beast)
        board_murloc = put(g, a, MURLOC_T2)
        spell = hand_spells(a, NATURAL_BLESSING)[0]
        d = get_db().get(NATURAL_BLESSING)
        m_before = (hand_murloc.atk, hand_murloc.health)
        b_before = (hand_beast.atk, hand_beast.health)
        self.assertTrue(g.play_spell(a, spell, target=board_murloc))
        # 正: 同类型手牌随从获得
        self.assertEqual(hand_murloc.atk, m_before[0] + d.num(0))
        self.assertEqual(hand_murloc.health, m_before[1] + d.num(1))
        # 负: 不同类型手牌随从不变
        self.assertEqual((hand_beast.atk, hand_beast.health), b_before)

    def test_opponent_hand_not_affected(self):
        g, a, b, t = self._setup(1898)
        opp_hand = g.create_minion(MURLOC_T2, controller=b)
        b.add_to_hand(opp_hand)
        board_murloc = put(g, a, MURLOC_T2)
        spell = hand_spells(a, NATURAL_BLESSING)[0]
        before = (opp_hand.atk, opp_hand.health)
        g.play_spell(a, spell, target=board_murloc)
        self.assertEqual((opp_hand.atk, opp_hand.health), before)

    def test_without_trinket_control(self):
        g = make_game(1899)
        a, b = g.heroes
        hand_murloc = g.create_minion(MURLOC_T2, controller=a)
        a.add_to_hand(hand_murloc)
        board_murloc = put(g, a, MURLOC_T2)
        spell = g.create_spell(NATURAL_BLESSING, controller=a)
        a.add_to_hand(spell)
        before = (hand_murloc.atk, hand_murloc.health)
        g.play_spell(a, spell, target=board_murloc)
        self.assertEqual((hand_murloc.atk, hand_murloc.health), before)
        # 正对照: 同 seed + 饰品 → 手牌随从获得
        g2, a2, b2, t2 = self._setup(1899)
        hm2 = g2.create_minion(MURLOC_T2, controller=a2)
        a2.add_to_hand(hm2)
        bm2 = put(g2, a2, MURLOC_T2)
        sp2 = hand_spells(a2, NATURAL_BLESSING)[0]
        before2 = hm2.atk
        g2.play_spell(a2, sp2, target=bm2)
        self.assertGreater(hm2.atk, before2)


# ══════════════ BG32_MagicItem_901 Gold-plated Compass ══════════════


class TestGoldPlatedCompass(unittest.TestCase):
    """下一次购买的纳迦金色化（一次性）+ 5 次免费刷新。"""

    TID = COMPASS

    def _setup(self, seed):
        g = make_game(seed)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        return g, a, b, t

    def _stock_naga(self, g, a):
        return _stock_tavern_minion(g, a, NAGA_T3)

    def test_grants_five_free_refreshes(self):
        g, a, b, t = self._setup(1911)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING), 5)
        gold = a.gold = 20
        for _ in range(5):
            g.refresh_tavern(a)
        self.assertEqual(a.gold, gold)              # 全免
        g.refresh_tavern(a)                         # 第 6 次收费（对照）
        self.assertLess(a.gold, gold)

    def test_buy_naga_turns_it_golden(self):
        g, a, b, t = self._setup(1912)
        d = get_db().get(NAGA_T3)
        a.gold = 20
        pool_before = g.minion_pool.available(NAGA_T3)
        self._stock_naga(g, a)
        self.assertTrue(g.buy_from_tavern(a, a.tavern[-1]))
        golden = [m for m in hand_minions(a) if m.is_golden]
        self.assertEqual(len(golden), 1)
        self.assertTrue(golden[0].card_id.endswith("_G"))
        self.assertTrue(golden[0].has(GameTag.GILDED_NOT_TRIPLED))
        self.assertEqual(golden[0].get(GameTag.TRIPLE_BASE_CARD_ID),
                         NAGA_T3)
        self.assertEqual(golden[0].atk, get_db().get(golden[0].card_id).atk)
        self.assertNotEqual(get_db().get(golden[0].card_id).atk, d.atk)
        self.assertLess(g.minion_pool.available(NAGA_T3), pool_before)

    def test_effect_is_one_shot(self):
        g, a, b, t = self._setup(1913)
        a.gold = 20
        self._stock_naga(g, a)
        g.buy_from_tavern(a, a.tavern[-1])
        _stock_tavern_minion(g, a, NAGA_T1)
        g.buy_from_tavern(a, a.tavern[-1])
        self.assertEqual(len([m for m in hand_minions(a) if m.is_golden]),
                         1)                              # 第二只不金

    def test_non_naga_buy_does_not_consume(self):
        g, a, b, t = self._setup(1914)
        a.gold = 20
        beast = _stock_tavern_minion(g, a, BEAST_T3)
        g.buy_from_tavern(a, beast)
        self.assertEqual([m for m in hand_minions(a) if m.is_golden], [])
        self._stock_naga(g, a)
        g.buy_from_tavern(a, a.tavern[-1])
        self.assertEqual(len([m for m in hand_minions(a) if m.is_golden]),
                         1)                              # 仍可用

    def test_already_golden_buy_does_not_consume(self):
        """wiki Patch 32.4.0.221908 bugfix: 买到已金色随从**不消耗**。"""
        g, a, b, t = self._setup(1917)
        a.gold = 20
        golden = g.create_minion(NAGA_T3, controller=a, golden=True)
        golden.zone = Zone.TAVERN
        a.tavern.append(golden)
        g.buy_from_tavern(a, golden)
        _stock_tavern_minion(g, a, NAGA_T3)
        g.buy_from_tavern(a, a.tavern[-1])
        new_golden = [m for m in hand_minions(a)
                      if m.is_golden and m is not golden]
        self.assertEqual(len(new_golden), 1)            # 效果仍在

    def test_opponent_buy_not_goldenised(self):
        g, a, b, t = self._setup(1915)
        a.gold = b.gold = 20
        naga_b = _stock_tavern_minion(g, b, NAGA_T3)
        g.buy_from_tavern(b, naga_b)
        self.assertEqual([m for m in hand_minions(b) if m.is_golden], [])
        # 正对照: 本人购买仍金色（效果未被对手消耗）
        self._stock_naga(g, a)
        g.buy_from_tavern(a, a.tavern[-1])
        self.assertEqual(len([m for m in hand_minions(a) if m.is_golden]),
                         1)

    def test_without_trinket_control(self):
        g = make_game(1916)
        a, b = g.heroes
        a.gold = 20
        naga = _stock_tavern_minion(g, a, NAGA_T3)
        g.buy_from_tavern(a, naga)
        self.assertEqual([m for m in hand_minions(a) if m.is_golden], [])
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)
        # 正对照: 同 seed 加饰品
        g2 = make_game(1916)
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        a2.gold = 20
        _stock_tavern_minion(g2, a2, NAGA_T3)
        g2.buy_from_tavern(a2, a2.tavern[-1])
        self.assertEqual(len([m for m in hand_minions(a2) if m.is_golden]),
                         1)

    def test_carddef_num0_is_naga(self):
        d = get_db().get(self.TID)
        self.assertEqual(d.num(0), int(Race.NAGA))


# ══════════════ BG32_MagicItem_904 Hogwash Basin ══════════════


class TestHogwashBasin(unittest.TestCase):
    """SoC: 对全部己方随从各施放 3 颗鲜血宝石。"""

    TID = HOGWASH

    def test_combat_start_applies_three_gems(self):
        g = make_game(1921)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        mine = tank(g, a, QUILBOAR_T2, atk=2, health=30)
        tank(g, b, QUILBOAR_T1, atk=2, health=30)
        gem = get_db().get("BG20_GEM")
        out = {}
        soc_probe(g, t, out)
        g.run_combat(a, b)
        mine_snap = dict((c, (atk, hp, gems))
                         for c, atk, hp, gems in out["boards"][a])
        theirs_snap = dict((c, (atk, hp, gems))
                           for c, atk, hp, gems in out["boards"][b])
        self.assertEqual(mine_snap[QUILBOAR_T2][2], 3)
        self.assertEqual(mine_snap[QUILBOAR_T2][0], 2 + 3 * gem.num(0))
        self.assertEqual(mine_snap[QUILBOAR_T2][1], 30 + 3 * gem.num(1))
        self.assertEqual(theirs_snap[QUILBOAR_T1][2], 0)   # 对手不吃

    def test_empty_board_whiffs(self):
        g = make_game(1922)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertIsNone(g.run_script_hook(t, "start_of_combat"))
        gem = get_db().get("BG20_GEM")
        m = tank(g, a, QUILBOAR_T2, atk=2, health=30)
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(m.get(GameTag.GEMS_PLAYED_ON), 3)
        self.assertEqual(m.atk, 2 + 3 * gem.num(0))

    def test_without_trinket_control(self):
        g = make_game(1923)
        a, b = g.heroes
        mine = tank(g, a, QUILBOAR_T2, atk=2, health=30)
        tank(g, b, QUILBOAR_T1, atk=2, health=30)
        out = {}
        soc_probe(g, mine, out)
        g.run_combat(a, b)
        snap = dict((c, (atk, hp, gems))
                    for c, atk, hp, gems in out["boards"][a])
        self.assertEqual(snap[QUILBOAR_T2][2], 0)
        self.assertEqual(snap[QUILBOAR_T2][0], 2)
        # 正对照: 同 seed 加饰品 → 3 颗宝石
        g2 = make_game(1923)
        a2, b2 = g2.heroes
        t2 = bind(g2, a2, self.TID)
        tank(g2, a2, QUILBOAR_T2, atk=2, health=30)
        tank(g2, b2, QUILBOAR_T1, atk=2, health=30)
        out2 = {}
        soc_probe(g2, t2, out2)
        g2.run_combat(a2, b2)
        snap2 = dict((c, (atk, hp, gems))
                     for c, atk, hp, gems in out2["boards"][a2])
        self.assertEqual(snap2[QUILBOAR_T2][2], 3)


# ══════════════ BG32_MagicItem_906 Artanis Sticker ══════════════


class TestArtanisSticker(unittest.TestCase):
    """Get a copy of '{0}' → Mothership（token，零池操作）。"""

    TID = ARTANIS

    def test_grants_mothership_token(self):
        g = make_game(1931)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        got = hand_minions(a)
        self.assertEqual([m.card_id for m in got], [MOTHERSHIP])
        self.assertFalse(get_db().get(MOTHERSHIP).is_pool_minion)

    def test_pool_invariant(self):
        g = make_game(1932)
        a, b = g.heroes
        probe = QUILBOAR_T2
        before = g.minion_pool.available(probe)
        bind(g, a, self.TID)
        self.assertEqual(g.minion_pool.available(probe), before)
        self.assertEqual([m.card_id for m in hand_minions(a)],
                         [MOTHERSHIP])                   # 正对照: 确已入手

    def test_opponent_hand_untouched(self):
        g = make_game(1933)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertEqual(hand_minions(b), [])
        self.assertEqual(len(hand_minions(a)), 1)        # 正对照

    def test_related_card_definition_chain_is_mothership(self):
        db = get_db()
        rel = db.by_dbf(db.get(self.TID).evolution_card_id)
        self.assertEqual(rel.id, MOTHERSHIP)


# ══════════════ BG32_MagicItem_922 Charming Panpipes ══════════════


class TestCharmingPanpipes(unittest.TestCase):
    """EoT: 最左随从 +num(0)/+num(0); 每次施放酒馆法术递增 1。"""

    TID = PANPIPES

    def _setup(self, seed, with_trinket=True):
        g = make_game(seed)
        a, b = g.heroes
        left = put(g, a, QUILBOAR_T2, position=0)
        put(g, a, QUILBOAR_T1, position=1)
        t = bind(g, a, self.TID) if with_trinket else None
        return g, a, b, left, t

    def _cast_tavern_spell(self, g, a):
        s = g.create_spell(TAVERN_SPELL, controller=a)
        a.add_to_hand(s)
        self.assertTrue(g.play_spell(a, s, target=left_first(g, a)))

    def test_base_value_without_casts(self):
        g, a, b, left, t = self._setup(1941)
        d = get_db().get(self.TID)
        base = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, base + d.num(0))
        self.assertEqual(left.health, 4 + d.num(0))

    def test_cast_improves_by_one(self):
        g, a, b, left, t = self._setup(1942)
        d = get_db().get(self.TID)
        self._cast_tavern_spell(g, a)
        base = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, base + d.num(0) + 1)
        self._cast_tavern_spell(g, a)
        mid = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, mid + d.num(0) + 2)   # 累积

    def test_each_cast_counts_including_spellcraft(self):
        """Spellcraft 非池法术也递增（正例）+ 对手施放不计（隔离）。

        旧实现监听 `tavern_spell_cast`（只对 `is_pool_spell` 广播）→
        本人 Spellcraft 施放不递增，本条即证伪旧实现。
        """
        g, a, b, left, t = self._setup(1947)
        d = get_db().get(self.TID)
        # 负对照: 对手施放一个 Spellcraft 法术 → 本人不递增
        opp_s = g.create_spell(VANILLA_GEM, controller=b)
        opp_s.set(GameTag.SPELLCRAFT, True)
        self.assertTrue(b.add_to_hand(opp_s))
        self.assertTrue(g.play_spell(b, opp_s))
        base = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, base + d.num(0))
        # 正例: 本人施放同一 Spellcraft 法术 → 递增 1
        s = g.create_spell(VANILLA_GEM, controller=a)
        s.set(GameTag.SPELLCRAFT, True)
        self.assertTrue(a.add_to_hand(s))
        self.assertTrue(g.play_spell(a, s, target=left_first(g, a)))
        mid = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, mid + d.num(0) + 1)

    def test_opponent_cast_not_counted(self):
        g, a, b, left, t = self._setup(1943)
        d = get_db().get(self.TID)
        s = g.create_spell(TAVERN_SPELL, controller=b)
        b.add_to_hand(s)
        g.play_spell(b, s, target=left_first(g, b))
        base = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, base + d.num(0))      # 对手不计
        self._cast_tavern_spell(g, a)                    # 正对照
        mid = left.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(left.atk, mid + d.num(0) + 1)

    def test_empty_board_whiffs(self):
        g = make_game(1944)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertIsNone(g.run_script_hook(t, "end_of_turn"))
        d = get_db().get(self.TID)
        m = put(g, a, QUILBOAR_T2)
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(m.atk, get_db().get(QUILBOAR_T2).atk + d.num(0))

    def test_without_trinket_control(self):
        g, a, b, left, t = self._setup(1945, with_trinket=False)
        base = left.atk
        g.run_script_hook(bind(g, b, self.TID), "end_of_turn")
        self.assertEqual(left.atk, base)
        # 正对照: 同 seed 给本人 → 生效
        g2, a2, b2, left2, t2 = self._setup(1945)
        d = get_db().get(self.TID)
        g2.run_script_hook(t2, "end_of_turn")
        self.assertEqual(left2.atk,
                         get_db().get(QUILBOAR_T2).atk + d.num(0))

    def test_cross_turn_accumulation(self):
        """递增跨回合保留（真实 end_recruit_phase 推进回合）。"""
        g, a, b, left, t = self._setup(1946)
        d = get_db().get(self.TID)
        put(g, b, QUILBOAR_T1)                 # 对手非空 → 战斗正常结算
        self._cast_tavern_spell(g, a)
        g.end_recruit_phase()
        self._cast_tavern_spell(g, a)           # 第 2 回合再 1 次 → 累计 2
        target = left_first(g, a)
        self.assertIsNotNone(target)
        before = target.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(target.atk, before + d.num(0) + 2)


def left_first(game: Game, hero: Hero):
    for m in hero.board:
        if not m.dead:
            return m
    return None


# ══════════════ BG32_MagicItem_926 Morgl Portrait ══════════════


class TestMorglPortrait(unittest.TestCase):
    """Get a Tide Oracle Morgl（池外专属卡）。"""

    TID = MORGL

    def test_grants_tide_oracle(self):
        g = make_game(1951)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertEqual([m.card_id for m in hand_minions(a)], [TIDE_ORACLE])
        self.assertFalse(get_db().get(TIDE_ORACLE).is_pool_minion)

    def test_pool_invariant(self):
        g = make_game(1952)
        a, b = g.heroes
        probe = QUILBOAR_T2
        before = g.minion_pool.available(probe)
        bind(g, a, self.TID)
        self.assertEqual(g.minion_pool.available(probe), before)
        self.assertEqual(len(hand_minions(a)), 1)      # 正对照: 确已入手

    def test_opponent_hand_untouched(self):
        g = make_game(1953)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertEqual(hand_minions(b), [])
        self.assertEqual([m.card_id for m in hand_minions(a)],
                         [TIDE_ORACLE])                    # 正对照

    def test_related_card_definition_chain(self):
        db = get_db()
        self.assertEqual(
            db.by_dbf(db.get(self.TID).evolution_card_id).id, TIDE_ORACLE)


# ══════════════ BG32_MagicItem_931 Azsharan Statuette ══════════════


class TestAzsharanStatuette(unittest.TestCase):
    """Get num(0) random Spellcraft spells; 每回合再来 num(0) 张。"""

    TID = AZSHARAN

    def test_grants_three_distinct_spellcraft_spells(self):
        g = make_game(1961)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        d = get_db().get(self.TID)
        spells = hand_spells(a)
        self.assertEqual(len(spells), d.num(0))
        self.assertEqual(len({s.card_id for s in spells}), d.num(0))
        for s in spells:
            self.assertTrue(s.has(GameTag.SPELLCRAFT))
            self.assertEqual(get_db().get(s.card_id).spell_school, 10)

    def test_spellcraft_cast_not_double_counted(self):
        g = make_game(1962)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        d = get_db().get(self.TID)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(hand_spells(a)), 2 * d.num(0))

    def test_pool_invariant(self):
        g = make_game(1963)
        a, b = g.heroes
        probe = TAVERN_SPELL
        before = g.spell_pool.available(probe)
        bind(g, a, self.TID)
        self.assertEqual(g.spell_pool.available(probe), before)
        self.assertEqual(len(hand_spells(a)), get_db().get(self.TID).num(0))

    def test_opponent_hand_untouched(self):
        g = make_game(1964)
        a, b = g.heroes
        bind(g, a, self.TID)
        g.run_script_hook(a.trinkets[-1], "start_of_turn")
        self.assertEqual(hand_spells(b), [])
        self.assertEqual(hand_minions(b), [])
        self.assertEqual(len(hand_spells(a)),
                         2 * get_db().get(self.TID).num(0))   # 正对照

    def test_without_trinket_control(self):
        g = make_game(1965)
        a, b = g.heroes
        self.assertEqual(hand_spells(a), [])
        g2 = make_game(1965)                                   # 正对照
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        self.assertEqual(len(hand_spells(a2)),
                         get_db().get(self.TID).num(0))

    def test_cross_turn_via_end_recruit_phase(self):
        """Spellcraft 法术回合末丢弃（RULES §6.13）→ 由下回合 SoT 补发。"""
        g = make_game(1966)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        d = get_db().get(self.TID)
        turn_seen = {}

        def on_ts(g_, turn=None, hero=None, **kw):
            if hero is a:
                turn_seen.setdefault("turn", turn)

        g.events.register(Listener(event="turn_start", owner=t,
                                   callback=on_ts))
        g.end_recruit_phase()
        self.assertGreaterEqual(turn_seen.get("turn", 0), 2)
        got = hand_spells(a)
        self.assertEqual(len(got), d.num(0))
        for s in got:
            self.assertTrue(s.has(GameTag.SPELLCRAFT))

    def test_num_matches_carddef(self):
        self.assertEqual(get_db().get(self.TID).num(0), 3)


# ══════════════ BG32_MagicItem_932 Vash'jir Anemone ══════════════


class TestVashjirAnemone(unittest.TestCase):
    """SoC: 己方纳迦 +num(1) Health，每 num(0) 次施法递增 num(1)。"""

    TID = ANEMONE

    def _setup(self, seed, with_trinket=True):
        g = make_game(seed)
        a, b = g.heroes
        naga = put(g, a, NAGA_T3)
        put(g, a, QUILBOAR_T1)
        t = bind(g, a, self.TID) if with_trinket else None
        return g, a, b, naga, t

    def test_no_improvement_below_threshold(self):
        g, a, b, naga, t = self._setup(1971)
        d = get_db().get(self.TID)
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, d.num(0) - 1)
        before = naga.health
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(naga.health, before + d.num(1))

    def test_every_four_casts_adds_one_rung(self):
        g, a, b, naga, t = self._setup(1972)
        d = get_db().get(self.TID)
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, d.num(0))
        before = naga.health
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(naga.health, before + 2 * d.num(1))
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 2 * d.num(0))
        mid = naga.health
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(naga.health, mid + 3 * d.num(1))

    def test_pre_bind_casts_count_this_game(self):
        """绑定前的本局施法同样计入档位（"this game" 全局口径）。

        真实路径: 先施放 num(0) 个酒馆法术（空板，避免 Shiny Ring 的
        +1/+1 干扰），再绑定 → SoC 应给 2×num(1)。旧实现存了绑定快照
        （`_anemone_base`）→ 只给 num(1)，本条即证伪旧实现。
        """
        g = make_game(1973)
        a, b = g.heroes
        d = get_db().get(self.TID)
        for _ in range(d.num(0)):
            s = g.create_spell(TAVERN_SPELL, controller=a)
            self.assertTrue(a.add_to_hand(s))
            self.assertTrue(g.play_spell(a, s))
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME),
                         d.num(0))
        naga = put(g, a, NAGA_T3)
        t = bind(g, a, self.TID)
        before = naga.health
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(naga.health, before + 2 * d.num(1))

    def test_non_naga_unaffected(self):
        g, a, b, naga, t = self._setup(1974)
        d = get_db().get(self.TID)
        other = [m for m in a.board if m.race != Race.NAGA][0]
        before = other.health
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, d.num(0))
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(other.health, before)
        self.assertGreater(naga.health, get_db().get(NAGA_T3).health)

    def test_opponent_naga_unaffected(self):
        g, a, b, naga, t = self._setup(1975)
        d = get_db().get(self.TID)
        opp = put(g, b, NAGA_T3)
        before = opp.health
        mine_before = naga.health
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, d.num(0))
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(opp.health, before)
        self.assertEqual(naga.health, mine_before + 2 * d.num(1))  # 正对照

    def test_without_trinket_control(self):
        g, a, b, naga, t = self._setup(1976, with_trinket=False)
        before = naga.health
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 8)
        self.assertEqual(naga.health, before)
        # 正对照: 同 seed 加饰品 → 生效
        g2, a2, b2, naga2, t2 = self._setup(1976)
        d = get_db().get(self.TID)
        a2.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 2 * d.num(0))
        g2.run_script_hook(t2, "start_of_combat")
        self.assertEqual(naga2.health,
                         get_db().get(NAGA_T3).health + 3 * d.num(1))

    def test_additive_not_multiplicative_on_repeat(self):
        """两次同档 SoC 各结算一次（绝对数值断言——非零基线）。"""
        g, a, b, naga, t = self._setup(1977)
        d = get_db().get(self.TID)
        a.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, d.num(0))
        base = get_db().get(NAGA_T3).health
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(naga.health, base + 2 * d.num(1))
        g.run_script_hook(t, "start_of_combat")
        self.assertEqual(naga.health, base + 4 * d.num(1))


# ══════════════ BG32_MagicItem_934 Dazzling Dagger ══════════════


class TestDazzlingDagger(unittest.TestCase):
    """己方随从 +num(1) Attack（每 num(0) 次施法递增）——光环等价。"""

    TID = DAGGER

    def _cast(self, g, a):
        """真实施放 1 个酒馆法术（Shiny Ring: +1/+1 全体）。"""
        s = g.create_spell(TAVERN_SPELL, controller=a)
        self.assertTrue(a.add_to_hand(s))
        self.assertTrue(g.play_spell(a, s))

    def test_bind_buffs_existing_minions(self):
        g = make_game(1981)
        a, b = g.heroes
        mine = put(g, a, QUILBOAR_T2)
        base_atk = mine.atk
        base_hp = mine.health
        bind(g, a, self.TID)
        d = get_db().get(self.TID)
        self.assertEqual(mine.atk, base_atk + d.num(1))
        self.assertEqual(mine.health, base_hp)     # 只加攻击

    def test_improvement_lifts_existing_and_new_minions(self):
        """8 次真实施法 → **已在场**随从与新入场随从同为 +3×num(1)。

        旧实现（on_bind 一次性 Buff + SUMMON 监听）档位提升只作用于
        新入场者，已在场随从停在 +num(1) → 本条即证伪旧实现。
        """
        g = make_game(1982)
        a, b = g.heroes
        d = get_db().get(self.TID)
        old = put(g, a, QUILBOAR_T1)
        bind(g, a, self.TID)
        for _ in range(2 * d.num(0)):
            self._cast(g, a)
        old_base = get_db().get(QUILBOAR_T1)
        self.assertEqual(old.atk, old_base.atk + 2 * d.num(0)
                         + 3 * d.num(1))          # 1 + 8//4 = 3
        new = put(g, a, QUILBOAR_T2, position=1)
        self.assertEqual(new.atk, get_db().get(QUILBOAR_T2).atk
                         + 3 * d.num(1))

    def test_pre_bind_casts_improve_at_bind(self):
        """绑定前本局已施放 8 个酒馆法术 → 绑定即 +3×num(1)。

        旧实现快照 `_dagger_base` → 绑定前施法不倒灌（只 +num(1)），
        本条即证伪旧实现。
        """
        g = make_game(1985)
        a, b = g.heroes
        d = get_db().get(self.TID)
        for _ in range(2 * d.num(0)):
            self._cast(g, a)                     # 空板施放，无 buff 干扰
        m = put(g, a, QUILBOAR_T2)
        bind(g, a, self.TID)
        self.assertEqual(m.atk,
                         get_db().get(QUILBOAR_T2).atk + 3 * d.num(1))

    def test_opponent_minions_unaffected(self):
        g = make_game(1983)
        a, b = g.heroes
        opp = put(g, b, QUILBOAR_T1)
        before = opp.atk
        mine = put(g, a, QUILBOAR_T1)
        bind(g, a, self.TID)
        self.assertEqual(opp.atk, before)
        d = get_db().get(self.TID)
        self.assertEqual(mine.atk, get_db().get(QUILBOAR_T1).atk + d.num(1))

    def test_without_trinket_control(self):
        g = make_game(1984)
        a, b = g.heroes
        mine = put(g, a, QUILBOAR_T2)
        self.assertEqual(mine.atk, get_db().get(QUILBOAR_T2).atk)
        # 正对照: 同 seed 加饰品
        g2 = make_game(1984)
        a2, b2 = g2.heroes
        m2 = put(g2, a2, QUILBOAR_T2)
        bind(g2, a2, self.TID)
        d = get_db().get(self.TID)
        self.assertEqual(m2.atk, get_db().get(QUILBOAR_T2).atk + d.num(1))

    def test_numeric_params_match_carddef(self):
        d = get_db().get(self.TID)
        self.assertEqual((d.num(0), d.num(1)), (4, 1))


# ══════════════ BG32_MagicItem_944 Empowerment Portrait ══════════════


class TestEmpowermentPortrait(unittest.TestCase):
    """Get Azerite Empowerment; 每回合再来一张。"""

    TID = EMPOWERMENT

    def test_grants_pool_spell(self):
        g = make_game(1991)
        a, b = g.heroes
        before = g.spell_pool.available(AZERITE)
        bind(g, a, self.TID)
        self.assertEqual(len(hand_spells(a, AZERITE)), 1)
        self.assertEqual(g.spell_pool.available(AZERITE), before - 1)

    def test_start_of_turn_grants_another(self):
        g = make_game(1992)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(hand_spells(a, AZERITE)), 2)

    def test_opponent_hand_untouched(self):
        g = make_game(1993)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(hand_spells(b), [])
        self.assertEqual(len(hand_spells(a, AZERITE)), 2)   # 正对照

    def test_pool_exhausted_card_definition_membership(self):
        g = make_game(1994)
        a, b = g.heroes
        self.assertTrue(get_db().get(AZERITE).is_pool_spell)
        soak_spell(g, AZERITE)
        self.assertEqual(g.spell_pool.available(AZERITE), 0)
        t = bind(g, a, self.TID)
        self.assertEqual(len(hand_spells(a, AZERITE)), 0)
        self.assertIsNone(g.run_script_hook(t, "start_of_turn"))

    def test_related_card_definition_chain(self):
        db = get_db()
        self.assertEqual(db.by_dbf(db.get(self.TID).evolution_card_id).id,
                         AZERITE)


# ══════════════ BG32_MagicItem_950 Gritty Portrait ══════════════


class TestGrittyPortrait(unittest.TestCase):
    """Get a Gritty Headhunter（反向数据链）; 每回合重复。"""

    TID = GRITTY

    def test_grants_headhunter(self):
        g = make_game(2001)
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertEqual([m.card_id for m in hand_minions(a)],
                         [GRITTY_HEADHUNTER])

    def test_start_of_turn_grants_another(self):
        g = make_game(2002)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(hand_minions(a)), 2)

    def test_pool_invariant(self):
        g = make_game(2003)
        a, b = g.heroes
        probe = QUILBOAR_T2
        before = g.minion_pool.available(probe)
        bind(g, a, self.TID)
        self.assertEqual(g.minion_pool.available(probe), before)
        self.assertEqual([m.card_id for m in hand_minions(a)],
                         [GRITTY_HEADHUNTER])              # 正对照: 确已入手

    def test_opponent_hand_untouched(self):
        g = make_game(2004)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(hand_minions(b), [])
        self.assertEqual(len(hand_minions(a)), 2)          # 正对照

    def test_reverse_card_definition_chain_resolves_headhunter(self):
        """数据链: 饰品 evolution → Marauder's Contract → 反向 → 随从。"""
        db = get_db()
        contract = db.by_dbf(db.get(self.TID).evolution_card_id)
        self.assertEqual(contract.id, MARAUDERS_CONTRACT)
        head = db.get(GRITTY_HEADHUNTER)
        self.assertEqual(head.evolution_card_id, contract.dbf_id)
        self.assertTrue(head.is_minion)
        self.assertIn("Marauder's Contract", head.text)


# ══════════════ BG32_MagicItem_951 Gold Pendant ══════════════


class TestGoldPendant(unittest.TestCase):
    """随机己方 Tier ≤ num(0) 随从金色化; 每回合重复。"""

    TID = PENDANT

    def test_bind_goldenises_low_tier(self):
        g = make_game(2011)
        a, b = g.heroes
        put(g, a, QUILBOAR_T2, position=0)      # T2
        put(g, a, DEMON_T5, position=1)         # T5 > num(0)
        bind(g, a, self.TID)
        board = a.board
        self.assertTrue(board[0].is_golden)
        self.assertTrue(board[0].has(GameTag.GILDED_NOT_TRIPLED))
        self.assertEqual(board[0].get(GameTag.TRIPLE_BASE_CARD_ID),
                         QUILBOAR_T2)
        self.assertFalse(board[1].is_golden)    # 越档不选

    def test_no_triple_reward_pending(self):
        """金色化 ≠ 三连（Reno 语义）: 无 TRIPLE_REWARD_PENDING。"""
        g = make_game(2012)
        a, b = g.heroes
        put(g, a, QUILBOAR_T2, position=0)
        bind(g, a, self.TID)
        golden = a.board[0]
        self.assertTrue(golden.is_golden)
        self.assertFalse(golden.has(GameTag.TRIPLE_REWARD_PENDING))
        self.assertEqual(golden.atk, get_db().get(golden.card_id).atk)

    def test_start_of_turn_goldenises_again(self):
        g = make_game(2013)
        a, b = g.heroes
        put(g, a, QUILBOAR_T1, position=0)
        t = bind(g, a, self.TID)
        self.assertTrue(a.board[0].is_golden)   # T1 已被金
        put(g, a, QUILBOAR_T2, position=1)
        g.run_script_hook(t, "start_of_turn")
        self.assertTrue(a.board[1].is_golden)
        self.assertTrue(a.board[0].is_golden)

    def test_without_trinket_control(self):
        g = make_game(2014)
        a, b = g.heroes
        put(g, a, QUILBOAR_T2)
        self.assertFalse(a.board[0].is_golden)
        # 正对照: 同 seed 加饰品 → 变金
        g2 = make_game(2014)
        a2, b2 = g2.heroes
        put(g2, a2, QUILBOAR_T2)
        bind(g2, a2, self.TID)
        self.assertTrue(a2.board[0].is_golden)

    def test_opponent_board_untouched(self):
        g = make_game(2015)
        a, b = g.heroes
        put(g, b, QUILBOAR_T2)
        put(g, a, QUILBOAR_T1)
        bind(g, a, self.TID)
        self.assertFalse(b.board[0].is_golden)
        self.assertTrue(a.board[0].is_golden)      # 正对照: 本人生效

    def test_empty_board_whiffs(self):
        g = make_game(2016)
        a, b = g.heroes
        t = bind(g, a, self.TID)
        self.assertIsNone(g.run_script_hook(t, "start_of_turn"))
        put(g, a, QUILBOAR_T2)
        g.run_script_hook(t, "start_of_turn")
        self.assertTrue(a.board[0].is_golden)

    def test_num_matches_carddef(self):
        self.assertEqual(get_db().get(self.TID).num(0), 4)


# ══════════════ 注册表 / 台账守卫 ══════════════


class TestRegistryLedger(unittest.TestCase):
    """注册表与 DEFERRED 台账守卫（结构性——与钩子无关）。@engine-only"""

    def test_all_implemented_registered(self):
        for tid in IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)

    def test_deferred_not_registered(self):
        for tid in DEFERRED:
            self.assertNotIn(tid, REGISTRY, f"{tid} 应为 DEFERRED")

    def test_all_ids_are_offer_pool_pool_membership(self):
        pool = {d.id for d in get_db().trinket_offer_pool()}
        for tid in IMPLEMENTED + DEFERRED + MIGRATED:
            self.assertIn(tid, pool, tid)

    def test_compass_armed_marker_is_read_by_engine_buy_path(self):
        """回归守卫: 901 的一次性标记消费点必须可达（防"买了不金"回归）。

        `minion_bought` 在 `buy_from_tavern` 中 fire（随从入手后）——真实
        购买路径必须把纳迦变金且**恰好消费一次**。
        """
        g = make_game(2031)
        a, b = g.heroes
        t = bind(g, a, COMPASS)
        a.gold = 20
        _stock_tavern_minion(g, a, NAGA_T3)
        g.buy_from_tavern(a, a.tavern[-1])
        self.assertEqual(len([m for m in hand_minions(a) if m.is_golden]), 1)
        self.assertFalse(t._compass_armed)          # 一次性标记已消费
        _stock_tavern_minion(g, a, NAGA_T3)         # 第二次 → 不再金色
        g.buy_from_tavern(a, a.tavern[-1])
        self.assertEqual(len([m for m in hand_minions(a) if m.is_golden]), 1)

    def test_counts(self):
        self.assertEqual(len(IMPLEMENTED), 13)
        self.assertEqual(len(DEFERRED), 0)
        self.assertEqual(len(MIGRATED), 6)
        self.assertEqual(len(set(IMPLEMENTED) | set(DEFERRED)
                             | set(MIGRATED)), 19)
        # 920 已由 batch_trinkets23 注册（原第 20 张）——DEFERRED 台账迁出
        # 902/907 已由 batch_unlock_final 注册（原第 3/4 张）——迁出

    def test_deferred_892_891_bonus_keyword_has_no_data(self):
        """Bonus Keyword 定义域缺口的运行时证据（RULES §9.6）。"""
        db = get_db()
        for tid in ("BG32_MagicItem_891", "BG32_MagicItem_892"):
            d = db.get(tid)
            self.assertTrue(all(d.num(i) is None for i in range(4)), tid)

    def test_925_payload_now_registered(self):
        """Hackerfin 已由 `batch_payload_minions` 注册（2026-09-02）→
        925 Hackerfin Portrait 的载荷阻塞解除（其余条款见其 docstring）。"""
        self.assertIsNotNone(REGISTRY.get("BG31_148"))

    def test_933_payload_now_registered(self):
        """Weary Mage 与其 Spellcraft 法术已由 `batch_payload_minions`
        注册 → 933 Weary Portrait 可用 `add_permanent_spellcraft_rule`。"""
        db = get_db()
        self.assertIsNotNone(REGISTRY.get("BG31_830"))
        self.assertIsNotNone(REGISTRY.get("BG31_830t"))
        self.assertEqual(db.get("BG31_830").spellcraft_id, 120896)


if __name__ == "__main__":
    unittest.main()
