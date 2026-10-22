"""批次 anomalies3 语义测试（作业单 2026-09-02）。

覆盖 12 个注册异变（真实引擎路径: `Game(..., anomaly=id)` +
`start_game()`，以及各效果真正挂接的事件/动作路径）:
  - BG32_Anomaly_003 Impressive Foresight
  - BG27_Anomaly_100 Big League
  - BG27_Anomaly_101 What Are the Odds?
  - BG27_Anomaly_102 How to Even??
  - BG31_Anomaly_104 Rising Current
  - BG31_Anomaly_105 Sin'dorei Mirror
  - BG31_Anomaly_109 Mystical Blossom
  - BG27_Anomaly_301 False Idols
  - BG27_Anomaly_555 No Place Like Holmes
  - BG27_Anomaly_575 Eleventh Hour
  - BG27_Anomaly_754 Path of the Treasure-Seeker
  - BG27_Anomaly_558 Feline Fortune

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都配**正对照**
（同一测试或同类内证明效果路径真的会触发）; 数值一律从
`CardDef.num(0/1)` / `C` 常量 / 文本推导，不复制字面量; owner 隔离
用 ≥2 英雄验证; "每回合/一次性"用多回合驱动验证。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_anomalies3 as B3
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

# 测试固定件（按名字/数据核实，不凭记忆写业务 id）
HERO_A = "TB_BaconShop_HERO_52"
VANILLA = "BG20_100"            # Razorfen Geomancer 2/1 T1（无四关键词）
OTHER = "BG25_013"              # Rot Hide Gnoll 1/4 T1 无关键词（隔离用）
TAVERN_SPELL = "BG28_168"       # 池法术（SpellPool 首项，T1）
TAVERN_COIN = "BG28_810"        # "Gain 1 Gold." 三连奖励替代物

REGISTERED_IDS = (
    "BG32_Anomaly_003",
    "BG27_Anomaly_100",
    "BG27_Anomaly_101",
    "BG27_Anomaly_102",
    "BG31_Anomaly_104",
    "BG31_Anomaly_105",
    "BG31_Anomaly_109",
    "BG27_Anomaly_301",
    "BG27_Anomaly_555",
    "BG27_Anomaly_575",
    "BG27_Anomaly_754",
    "BG27_Anomaly_558",
)

# DEFERRED（台账见 batch_anomalies3 模块 docstring）——不得注册
DEFERRED_IDS = (
    "BG31_Anomaly_106",
    "BG31_Anomaly_102",
    "BG31_Anomaly_115",
    "BG27_Anomaly_716",
    "BG27_Anomaly_755",
    "BG27_Anomaly_720",
    "BG27_Anomaly_723",
    "BG27_Anomaly_302",
    "BG27_Anomaly_503",
    "BG27_Anomaly_562",
    "BG27_Anomaly_577",
    "BG27_Anomaly_580",
    "BG27_Anomaly_556",
    "BG33_Anomaly_001",
    "BG33_Anomaly_005",
    "BG34_Anomaly_801",
    "BG34_Anomaly_804",
)
# batch_anomalies4 已实现原 DEFERRED 中的第二英雄技能槽族 3 张
# （BG32_Anomaly_001 / BG32_Anomaly_002 / BG31_Anomaly_123）——引擎原语
# RULES §9.5 `hero._second_power_id` 落地后迁出本台账。
# BG27_Anomaly_307 迁出（batch_anomalies_final 已注册——`num(0)=NAGA`
# 酒馆种族白名单，与 104t 族同机制）。

_STANDARD_TRINKET_TURNS = {kind: turn
                           for turn, kind in C.TRINKET_OFFER_TURNS.items()}


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def game_with(anomaly: str | None = None, seed: int = 40,
              names=("A", "B")) -> Game:
    heroes = [Hero(HERO_A, n) for n in names]
    g = Game(heroes, get_db(), seed=seed, anomaly=anomaly)
    g.start_game()
    return g


def start_turn(game: Game, turn: int, clear_choices: bool = False) -> None:
    """驱动真实回合开始（每存活英雄一次）。

    clear_choices=True 在**回合开始前**清掉上一回合遗留的待决（不得
    在回合开始后清，否则会抹掉本回合刚产生的 offer——本批测试实测教训）。
    """
    if clear_choices:
        game.pending_choices.clear()
    game.turn = turn
    for h in game.heroes:
        if h.is_alive:
            game._begin_recruit_for(h)


def take_choice(game: Game, kind: str, owner=None):
    """按 kind（可选 owner）取出一条 PendingChoice 并出队（SOP §13 契约）。"""
    if owner is None:
        choice = next(c for c in game.pending_choices if c.kind == kind)
    else:
        choice = next(c for c in game.pending_choices
                      if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(choice)
    return choice


def buy_spell(game: Game, hero, spell_id: str = TAVERN_SPELL) -> bool:
    """把一张池法术放进酒馆并真实购买（走 SPELL_BOUGHT 事件路径）。"""
    spell = game.create_spell(spell_id, controller=hero)
    spell.zone = Zone.TAVERN
    hero.tavern.append(spell)
    hero.gold = 99
    return game.buy_from_tavern(hero, spell)


class TestRegistry(unittest.TestCase):
    def test_all_ids_registered(self):
        for cid in REGISTERED_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_class_names(self):
        expected = {
            "BG32_Anomaly_003": "ImpressiveForesightAnomaly",
            "BG27_Anomaly_100": "BigLeagueAnomaly",
            "BG27_Anomaly_101": "WhatAreTheOddsAnomaly",
            "BG27_Anomaly_102": "HowToEvenAnomaly",
            "BG31_Anomaly_104": "RisingCurrentAnomaly",
            "BG31_Anomaly_105": "SindoreiMirrorAnomaly",
            "BG31_Anomaly_109": "MysticalBlossomAnomaly",
            "BG27_Anomaly_301": "FalseIdolsAnomaly",
            "BG27_Anomaly_555": "NoPlaceLikeHolmesAnomaly",
            "BG27_Anomaly_575": "EleventhHourAnomaly",
            "BG27_Anomaly_754": "PathOfTheTreasureSeekerAnomaly",
            "BG27_Anomaly_558": "FelineFortuneAnomaly",
        }
        for cid, name in expected.items():
            self.assertEqual(REGISTRY[cid].__name__, name, cid)

    def test_deferred_ids_are_not_registered(self):
        for cid in DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)


# ══════════════ BG32_Anomaly_003 Impressive Foresight ══════════════


class TestImpressiveForesight(unittest.TestCase):
    """Buy your Lesser Trinket on Turn 5, and your Greater Trinket on
    Turn 8. (BG32_Anomaly_003)"""

    @staticmethod
    def _offers(game):
        out = {}
        for c in game.pending_choices:
            if c.kind != "trinket_offer":
                continue
            out.setdefault(c.owner, set()).update(
                o.spell_school for o in c.options if o is not None)
        return out

    def test_trinket_schedule_real_turns(self):
        g = game_with("BG32_Anomaly_003")
        a, b = g.heroes
        seen = {}
        for turn in (4, 5, 6, 7, 8, 9):
            start_turn(g, turn, clear_choices=True)
            for owner, schools in self._offers(g).items():
                seen.setdefault(owner, {})[turn] = schools
        for hero in (a, b):
            # 只出现两档，且恰在文本给定的回合
            self.assertEqual(sorted(seen[hero]),
                             sorted(B3._IMPRESSIVE_FORESIGHT_TURNS.values()),
                             hero.name)
            self.assertEqual(seen[hero][B3._IMPRESSIVE_FORESIGHT_TURNS["lesser"]],
                             {11})     # 11 = Lesser
            self.assertEqual(seen[hero][B3._IMPRESSIVE_FORESIGHT_TURNS["greater"]],
                             {12})     # 12 = Greater

    def test_standard_schedule_contrast(self):
        """正对照: 无异变时 T5 无 offer、T6 Lesser、T9 Greater。"""
        g = game_with()
        for turn in (5, 6, 9):
            start_turn(g, turn, clear_choices=True)
            offers = self._offers(g)
            if turn == 5:
                self.assertEqual(offers, {})
            else:
                self.assertTrue(offers)
                school = 11 if turn == 6 else 12
                for hero, schools in offers.items():
                    self.assertEqual(schools, {school}, hero.name)
        # 正对照（异变 + 同驱动）: T5 就有 Lesser、T8 Greater、T9 无 offer
        g2 = game_with("BG32_Anomaly_003")
        expected = {5: {11}, 8: {12}, 9: None}
        for turn in (5, 8, 9):
            start_turn(g2, turn, clear_choices=True)
            offers = self._offers(g2)
            want = expected[turn]
            if want is None:
                self.assertEqual(offers, {})
            else:
                self.assertTrue(offers)
                for hero, schools in offers.items():
                    self.assertEqual(schools, want, hero.name)

    def test_table_matches_text_and_standard_schedule(self):
        d = get_db().get("BG32_Anomaly_003")
        for kind, turn in B3._IMPRESSIVE_FORESIGHT_TURNS.items():
            self.assertIn(f"Turn {turn}", d.text)
            # 相对标准档位各提前 1 回合（引擎常量派生，非独立字面量）
            self.assertEqual(turn, _STANDARD_TRINKET_TURNS[kind] - 1)


# ══════════════ BG27_Anomaly_100 Big League ══════════════


class TestBigLeague(unittest.TestCase):
    """Only Tavern Tiers 3, 4, 5, and 6 exist. Start with 10 extra
    Armor. (BG27_Anomaly_100)"""

    def test_start_state(self):
        g = game_with("BG27_Anomaly_100")
        base = game_with()                                # 对照基线护甲
        for h, ref in zip(g.heroes, base.heroes):
            self.assertEqual(h.tavern_tier, B3._BIG_LEAGUE_FLOOR_TIER)
            self.assertEqual(
                h.upgrade_cost,
                C.BASE_UPGRADE_COSTS[B3._BIG_LEAGUE_FLOOR_TIER + 1])
            self.assertEqual(h.armor,
                             ref.armor + B3._BIG_LEAGUE_EXTRA_ARMOR)

    def test_tavern_floor_and_control(self):
        g = game_with("BG27_Anomaly_100")
        a = g.heroes[0]
        tiers = {m.tech_level for m in a.tavern if isinstance(m, Minion)}
        self.assertTrue(tiers)
        for t in tiers:
            self.assertGreaterEqual(t, B3._BIG_LEAGUE_FLOOR_TIER)
        # 正对照: 标准局 T1 馆内随从未必全为 T3（此种子全 T1）
        g2 = game_with(seed=40)
        a2 = g2.heroes[0]
        tiers2 = {m.tech_level for m in a2.tavern if isinstance(m, Minion)}
        self.assertTrue(tiers2)
        self.assertTrue(all(t < B3._BIG_LEAGUE_FLOOR_TIER for t in tiers2))

    def test_upgrade_to_tier4_and_shop_stays_floored(self):
        g = game_with("BG27_Anomaly_100")
        a = g.heroes[0]
        fired = []
        from hsrl2.events import Listener
        g.events.register(Listener(
            event="tavern_upgraded", owner=None,
            callback=lambda g_, hero=None, tier=None, **kw:
                fired.append((hero, tier))))
        a.gold = 99
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.tavern_tier, B3._BIG_LEAGUE_FLOOR_TIER + 1)
        self.assertEqual(fired, [(a, B3._BIG_LEAGUE_FLOOR_TIER + 1)])
        g.refresh_tavern(a, free=True)
        tiers = {m.tech_level for m in a.tavern if isinstance(m, Minion)}
        self.assertTrue(tiers)
        for t in tiers:
            self.assertGreaterEqual(t, B3._BIG_LEAGUE_FLOOR_TIER)


# ══════════════ BG27_Anomaly_101/102 Tavern Tier ladder ══════════════

ODDS = "BG27_Anomaly_101"
EVEN = "BG27_Anomaly_102"


def pool_minion_ids(tier: int) -> list:
    """池内该档随从 id（升序，确定性固定件）。"""
    return sorted(d.id for d in get_db().pool_minions()
                  if d.tech_level == tier)


class TestTierLadderAnomalies(unittest.TestCase):
    """Only Tavern Tiers 1, 3, and 5 exist. / Only Tavern Tiers 2, 4,
    and 6 exist. Triple Rewards Discover a minion of your Tier.
    (BG27_Anomaly_101 / BG27_Anomaly_102)"""

    @staticmethod
    def _refresh_tiers(game, hero, n: int):
        """真实刷新 n 次，收集馆内随从/酒馆法术档位。"""
        minions, spells = set(), set()
        for _ in range(n):
            for e in hero.tavern:
                if isinstance(e, Minion):
                    minions.add(e.tech_level)
                elif isinstance(e, Spell):
                    spells.add(get_db().get(e.card_id).tech_level)
            hero.gold = 99
            game.refresh_tavern(hero)
        return minions, spells

    @staticmethod
    def _real_triple_reward(game, hero, minion_id: str):
        """真实三连路径: 三份入手（`pending_hand_add` → check_for_triple）
        → 金卡带 `TRIPLE_REWARD_PENDING` → 真实 `play_minion` 发奖励。"""
        for _ in range(2):
            game.pending_hand_add(
                hero, game.create_minion(minion_id, controller=hero))
        game.pending_hand_add(
            hero, game.create_minion(minion_id, controller=hero))
        golden = next(m for m in hero.hand if m.is_golden)
        assert golden.has(GameTag.TRIPLE_REWARD_PENDING)
        assert game.play_minion(hero, golden)
        return take_choice(game, "triple_reward", owner=hero)

    # ── 起手档 + 阶梯声明 ──

    def test_start_state_odds_and_even(self):
        g = game_with(ODDS)
        base = game_with()
        for h in g.heroes:
            # T1 存在 → 起手 T1（标准局同档; 正对照见下方 EVEN）
            self.assertEqual(h.tavern_tier, 1)
            self.assertEqual(h.upgrade_cost, C.BASE_UPGRADE_COSTS[2])
        self.assertEqual(g._tavern_tier_ladder, B3._ODDS_TIER_LADDER)
        self.assertEqual(g.max_tavern_tier, 5)
        self.assertIsNone(base._tavern_tier_ladder)     # 标准局无覆写
        self.assertEqual(base.max_tavern_tier, C.TAVERN_MAX_TIER)
        e = game_with(EVEN)
        for h in e.heroes:
            # T1 不存在 → 起手最低存在档 T2（Big League 起始规则同源）
            self.assertEqual(h.tavern_tier, 2)
            self.assertEqual(h.upgrade_cost, C.BASE_UPGRADE_COSTS[2])
        self.assertEqual(e._tavern_tier_ladder, B3._EVEN_TIER_LADDER)
        self.assertEqual(e.max_tavern_tier, 6)

    # ── 升级落点 + 步数计费 ──

    def test_upgrade_path_and_step_indexed_cost(self):
        g = game_with(ODDS, seed=40)
        a = g.heroes[0]
        a.gold = 99
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.tavern_tier, 3)              # 1 → 3（跳过 T2）
        # 步数口径: 第 1 次升级后基价 = 序列第 2 档 BASE[3]
        # （"目标档 + 1" 口径会得 BASE[4]，与本断言不符）
        self.assertEqual(a.upgrade_cost, C.BASE_UPGRADE_COSTS[3])
        a.gold = 99
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.tavern_tier, 5)
        a.gold = 99
        self.assertFalse(g.upgrade_tavern(a))           # T5 之上无存在档
        self.assertEqual(a.tavern_tier, 5)
        # 正对照: 标准局同一调用序列逐级 1→2，且基价同为 BASE[3]
        c = game_with(seed=40)
        b = c.heroes[0]
        b.gold = 99
        self.assertTrue(c.upgrade_tavern(b))
        self.assertEqual(b.tavern_tier, 2)
        self.assertEqual(b.upgrade_cost, C.BASE_UPGRADE_COSTS[3])

    def test_even_upgrade_path(self):
        g = game_with(EVEN)
        a = g.heroes[0]
        for expected in (4, 6):
            a.gold = 99
            self.assertTrue(g.upgrade_tavern(a))
            self.assertEqual(a.tavern_tier, expected)
        a.gold = 99
        self.assertFalse(g.upgrade_tavern(a))           # T6 = 末档
        self.assertEqual(a.tavern_tier, 6)
        # 正对照: 标准局从 T2 起可继续升到 3（存在档更多）
        c = game_with()
        b = c.heroes[0]
        b.set(GameTag.TAVERN_TIER, 2)
        b.gold = 99
        self.assertTrue(c.upgrade_tavern(b))
        self.assertEqual(b.tavern_tier, 3)

    def test_free_upgrade_and_t7_unlock_respect_ladder(self):
        """异变 005 式免费升级 + 他卡 "Unlock Tier 7" 都不得越出存在档。"""
        g = game_with(ODDS)
        a = g.heroes[0]
        g.upgrade_tavern_free(a)
        self.assertEqual(a.tavern_tier, 3)
        g.upgrade_tavern_free(a)
        self.assertEqual(a.tavern_tier, 5)
        g.max_tavern_tier = 7                           # 他卡解锁 T7
        g.upgrade_tavern_free(a)
        self.assertEqual(a.tavern_tier, 5)              # T6/T7 不存在
        a.gold = 99
        self.assertFalse(g.upgrade_tavern(a))
        # 正对照: 标准局同三次免费升级 = 2/3/4，且 max=7 后可继续
        c = game_with()
        b = c.heroes[0]
        for expected in (2, 3, 4):
            c.upgrade_tavern_free(b)
            self.assertEqual(b.tavern_tier, expected)

    # ── 展示/发现白名单（真实刷新 + 真实施法）──

    def test_odds_t3_offers_exclude_nonexistent_t2(self):
        g = game_with(ODDS, seed=7)
        a = g.heroes[0]
        a.gold = 99
        self.assertTrue(g.upgrade_tavern(a))            # 真实升到 T3
        minions, spells = self._refresh_tiers(g, a, 12)
        self.assertTrue(minions)
        self.assertEqual(minions, {1, 3})               # 无 T2（也不越 T5）
        self.assertTrue(spells)
        self.assertEqual(spells, {1, 3})                # 酒馆法术同白名单
        # 正对照（负控制）: 标准局 T3 同种子确实出 T2 随从与 T2 法术
        c = game_with(None, seed=7)
        b = c.heroes[0]
        b.gold = 99
        for _ in range(2):
            c.upgrade_tavern(b)
        self.assertEqual(b.tavern_tier, 3)
        c_minions, c_spells = self._refresh_tiers(c, b, 12)
        self.assertIn(2, c_minions)
        self.assertIn(2, c_spells)

    def test_even_start_offers_exclude_nonexistent_t1(self):
        g = game_with(EVEN, seed=7)
        a = g.heroes[0]
        minions, spells = self._refresh_tiers(g, a, 12)
        self.assertEqual(minions, {2})                  # T1/T3 均不存在
        self.assertEqual(spells, {2})
        # 正对照: 标准局 T2 起手馆内出现 T1 随从与 T1 法术
        c = game_with(None, seed=7)
        b = c.heroes[0]
        b.set(GameTag.TAVERN_TIER, 2)
        c_minions, c_spells = self._refresh_tiers(c, b, 12)
        self.assertIn(1, c_minions)
        self.assertIn(1, c_spells)

    def test_extra_tier_slot_respects_ladder(self):
        """他卡"额外高一档展示位"（Innkeeper's Stein 族）同受白名单约束:
        目标档不存在 → 该位落空（不改成"下一存在档"，白名单只移除）。"""
        g = game_with(ODDS, seed=23)
        a = g.heroes[0]
        a.set(GameTag.TAVERN_EXTRA_TIER_SLOTS, 1)
        a.set(GameTag.TAVERN_EXTRA_TIER, 2)             # T2 不存在
        a.gold = 99
        g.refresh_tavern(a)
        minions = {m.tech_level for m in a.tavern if isinstance(m, Minion)}
        self.assertEqual(minions, {1})
        # 正对照: 标准局同 setup 的额外位真的抽到 T2
        c = game_with(None, seed=23)
        b = c.heroes[0]
        b.set(GameTag.TAVERN_EXTRA_TIER_SLOTS, 1)
        b.set(GameTag.TAVERN_EXTRA_TIER, 2)
        b.gold = 99
        c.refresh_tavern(b)
        c_minions = {m.tech_level for m in b.tavern if isinstance(m, Minion)}
        self.assertIn(2, c_minions)

    def test_discover_candidates_and_explicit_list(self):
        from hsrl2.actions.discover import Discover, _pool_candidates
        g = game_with(ODDS)
        # 池候选: 显式 min/max=2 也抽不到（T2 不存在）
        self.assertEqual(
            [get_db().get(cid).tech_level
             for cid in _pool_candidates(g, min_tier=2, max_tier=2)], [])
        tiers = {get_db().get(cid).tech_level for cid in _pool_candidates(g)}
        self.assertTrue(tiers)
        self.assertLessEqual(tiers, {1, 3, 5})
        a = g.heroes[0]
        t2 = pool_minion_ids(2)[0]
        g.run_actions(Discover(a, candidates=[t2]))     # 显式非存在档
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "discover_minion"], [])
        # 正对照: 标准局同一调用 → T2 候选真的可选
        c = game_with()
        b = c.heroes[0]
        c.run_actions(Discover(b, candidates=[t2]))
        ch = take_choice(c, "discover_minion", owner=b)
        self.assertEqual(ch.options, [t2])

    # ── 三连奖励档 = 本人档（真实三连）──

    def test_triple_reward_odds_is_own_tier(self):
        g = game_with(ODDS, seed=11)
        a = g.heroes[0]
        a.gold = 99
        self.assertTrue(g.upgrade_tavern(a))            # T1 → T3
        ch = self._real_triple_reward(g, a, pool_minion_ids(1)[0])
        self.assertEqual(len(ch.options), 3)
        for cid in ch.options:
            self.assertEqual(get_db().get(cid).tech_level, 3, cid)
        # 正对照（负控制）: 无异常局 T3 同一 T1 三连 → 奖励档 = 2
        c = game_with(None, seed=11)
        b = c.heroes[0]
        b.gold = 99
        for _ in range(2):
            c.upgrade_tavern(b)
        self.assertEqual(b.tavern_tier, 3)
        ch2 = self._real_triple_reward(c, b, pool_minion_ids(1)[0])
        for cid in ch2.options:
            self.assertEqual(get_db().get(cid).tech_level, 2, cid)

    def test_triple_reward_even_is_own_tier(self):
        g = game_with(EVEN, seed=13)
        a = g.heroes[0]
        a.gold = 99
        self.assertTrue(g.upgrade_tavern(a))            # T2 → T4
        self.assertEqual(a.tavern_tier, 4)
        ch = self._real_triple_reward(g, a, pool_minion_ids(2)[0])
        self.assertTrue(ch.options)
        for cid in ch.options:
            # 本人档 T4（"被三连随从档 + 1" 口径会得 T3 = 不存在档,
            # 白名单下候选为空 → 根本不会有本 PendingChoice）
            self.assertEqual(get_db().get(cid).tech_level, 4, cid)
        # 正对照: 无异常局 T4 同一 T2 三连 → 奖励档 = 3
        c = game_with(None, seed=13)
        b = c.heroes[0]
        b.gold = 99
        for _ in range(3):
            c.upgrade_tavern(b)
        self.assertEqual(b.tavern_tier, 4)
        ch2 = self._real_triple_reward(c, b, pool_minion_ids(2)[0])
        for cid in ch2.options:
            self.assertEqual(get_db().get(cid).tech_level, 3, cid)


# ══════════════ BG31_Anomaly_104 Rising Current ══════════════


class TestRisingCurrent(unittest.TestCase):
    """After you upgrade the Tavern, Discover a Tier {1} Tavern spell.
    (Improves in {0} turns!) (BG31_Anomaly_104)"""

    def _upgrade_discover(self, g, hero, turn):
        start_turn(g, turn, clear_choices=True)
        hero.set(GameTag.TAVERN_TIER, 1)
        hero.set(GameTag.UPGRADE_COST, 0)
        hero.gold = 99
        self.assertTrue(g.upgrade_tavern(hero))
        return take_choice(g, "discover_tavern_spell", owner=hero)

    def test_tier_progression_from_num(self):
        db = get_db()
        d = db.get("BG31_Anomaly_104")
        base, every = d.num(1), d.num(0)
        g = game_with("BG31_Anomaly_104")
        a = g.heroes[0]
        for turn in (1, 2, 3, 5):
            choice = self._upgrade_discover(g, a, turn)
            expected = base + (turn - 1) // every
            self.assertEqual(len(choice.options), 3)
            for cid in choice.options:
                self.assertEqual(db.get(cid).tech_level, expected, cid)
            # 选中确实入手（预留语义 → resolve 授予）
            before = len(a.hand)
            choice.choose(0)
            self.assertEqual(len(a.hand), before + 1)

    def test_cap_at_max_tavern_tier(self):
        g = game_with("BG31_Anomaly_104")
        a = g.heroes[0]
        choice = self._upgrade_discover(g, a, 1000)
        for cid in choice.options:
            self.assertEqual(get_db().get(cid).tech_level,
                             g.max_tavern_tier)

    def test_hero_isolation(self):
        g = game_with("BG31_Anomaly_104")
        a, b = g.heroes
        choice = self._upgrade_discover(g, a, 1)
        self.assertIs(choice.owner, a)
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "discover_tavern_spell"
                          and c.owner is b], [])

    def test_num_params_exist(self):
        d = get_db().get("BG31_Anomaly_104")
        self.assertEqual(d.num(0), 2)
        self.assertEqual(d.num(1), 1)


# ══════════════ BG31_Anomaly_105 Sin'dorei Mirror ══════════════


class TestSindoreiMirror(unittest.TestCase):
    """After you buy your first Tavern spell each turn, get an extra
    copy of it. (Unlocks on Turn 5.) (BG31_Anomaly_105)"""

    @staticmethod
    def _count(hero, card_id=TAVERN_SPELL):
        return len([e for e in hero.hand if e.card_id == card_id])

    def test_first_spell_each_turn_after_unlock(self):
        g = game_with("BG31_Anomaly_105")
        a, b = g.heroes
        # 解锁前（T4）: 买了 1 张 → 手里 1 张（无副本）
        start_turn(g, 4, clear_choices=True)
        self.assertTrue(buy_spell(g, a))
        self.assertEqual(self._count(a), 1)
        # T5 首次购买 → 1（旧）+ 1（本次）+ 1（副本） = 3
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(buy_spell(g, a))
        self.assertEqual(self._count(a), 3)
        # 同回合第二次购买 → 只加本体（4），无副本
        self.assertTrue(buy_spell(g, a))
        self.assertEqual(self._count(a), 4)
        # 下回合再次生效 → 4 + 1 + 1 = 6
        start_turn(g, 6, clear_choices=True)
        self.assertTrue(buy_spell(g, a))
        self.assertEqual(self._count(a), 6)
        # 英雄隔离: B 从未购买 → 0
        self.assertEqual(self._count(b), 0)

    def test_control_without_anomaly_no_copy(self):
        g = game_with()
        a = g.heroes[0]
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(buy_spell(g, a))
        self.assertEqual(self._count(a), 1)
        # 正对照（同 setup + 异变）: 同回合确实多 1 张副本
        g2 = game_with("BG31_Anomaly_105")
        a2 = g2.heroes[0]
        start_turn(g2, 5, clear_choices=True)
        self.assertTrue(buy_spell(g2, a2))
        self.assertEqual(self._count(a2), 2)


# ══════════════ BG31_Anomaly_109 Mystical Blossom ══════════════


class TestMysticalBlossom(unittest.TestCase):
    """At the start of each turn, Discover a Tavern spell.
    (Unlocks on Turn 3.) (BG31_Anomaly_109)"""

    def test_unlock_turn_and_each_turn(self):
        db = get_db()
        g = game_with("BG31_Anomaly_109")
        a, b = g.heroes
        start_turn(g, 2, clear_choices=True)
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "discover_tavern_spell"], [])
        for turn in (3, 4):
            start_turn(g, turn, clear_choices=True)
            choices = [c for c in g.pending_choices
                       if c.kind == "discover_tavern_spell"]
            self.assertEqual(len(choices), 2, f"turn {turn}")
            self.assertEqual({id(c.owner) for c in choices},
                             {id(a), id(b)})
            ca = next(c for c in choices if c.owner is a)
            self.assertEqual(len(ca.options), 3)
            for cid in ca.options:
                self.assertEqual(db.get(cid).tech_level, a.tavern_tier)
            before = len(a.hand)
            ca.choose(0)
            self.assertEqual(len(a.hand), before + 1)
            # 出队并结算 B 的选择（清理现场，不影响下一回合）
            g.pending_choices.remove(ca)
            cb = next(c for c in g.pending_choices
                      if c.kind == "discover_tavern_spell" and c.owner is b)
            g.pending_choices.remove(cb)
            cb.choose(0)

    def test_control_without_anomaly(self):
        g = game_with()
        start_turn(g, 3, clear_choices=True)
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "discover_tavern_spell"], [])
        # 正对照: 同回合 + 异变 → 每英雄各一份发现
        g2 = game_with("BG31_Anomaly_109")
        start_turn(g2, 3, clear_choices=True)
        self.assertEqual(len([c for c in g2.pending_choices
                              if c.kind == "discover_tavern_spell"]), 2)


# ══════════════ BG27_Anomaly_301 False Idols ══════════════


class TestFalseIdols(unittest.TestCase):
    """You only need 2 copies to make minions Golden. They give Tavern
    Coins instead of Triple Rewards. (BG27_Anomaly_301)"""

    @staticmethod
    def _give(game, hero, card_id, n):
        for _ in range(n):
            game.pending_hand_add(
                hero, game.create_minion(card_id, controller=hero))

    def test_two_copies_golden_and_coin(self):
        g = game_with("BG27_Anomaly_301")
        a, b = g.heroes
        self._give(g, a, VANILLA, 2)
        golden = [e for e in a.hand
                  if isinstance(e, Minion) and e.is_golden]
        self.assertEqual(len(golden), 1)
        self.assertFalse(golden[0].get(GameTag.TRIPLE_REWARD_PENDING, False))
        self.assertEqual([e.card_id for e in a.hand
                          if e.card_id == TAVERN_COIN], [TAVERN_COIN])
        # 阈值来自文本（2 份）→ 两英雄各 2 份不同 id 互不干扰
        self._give(g, b, OTHER, 2)
        golden_b = [e for e in b.hand
                    if isinstance(e, Minion) and e.is_golden]
        self.assertEqual(len(golden_b), 1)
        self.assertEqual([e.card_id for e in b.hand
                          if e.card_id == TAVERN_COIN], [TAVERN_COIN])
        # A 的合成不因 B 的合成而变化（各 1 金 + 1 币）
        self.assertEqual([e.uuid for e in a.hand
                          if isinstance(e, Minion)], [golden[0].uuid])
        self.assertCountEqual([e.card_id for e in a.hand],
                              [TAVERN_COIN, golden[0].card_id])

    def test_control_threshold_3_and_reward_pending(self):
        g = game_with()
        a = g.heroes[0]
        self._give(g, a, VANILLA, 2)
        self.assertEqual([e for e in a.hand
                          if isinstance(e, Minion) and e.is_golden], [])
        self.assertEqual([e.card_id for e in a.hand
                          if e.card_id == TAVERN_COIN], [])
        self._give(g, a, VANILLA, 1)          # 第 3 份才合成
        golden = [e for e in a.hand
                  if isinstance(e, Minion) and e.is_golden]
        self.assertEqual(len(golden), 1)
        self.assertTrue(golden[0].get(GameTag.TRIPLE_REWARD_PENDING, False))
        self.assertEqual([e.card_id for e in a.hand
                          if e.card_id == TAVERN_COIN], [])
        # 正对照（异变 + 同份数 2）: 2 份即金 + 币、无 PENDING
        g2 = game_with("BG27_Anomaly_301")
        a2 = g2.heroes[0]
        self._give(g2, a2, VANILLA, 2)
        golden2 = [e for e in a2.hand
                   if isinstance(e, Minion) and e.is_golden]
        self.assertEqual(len(golden2), 1)
        self.assertFalse(golden2[0].get(GameTag.TRIPLE_REWARD_PENDING, False))
        self.assertEqual([e.card_id for e in a2.hand
                          if e.card_id == TAVERN_COIN], [TAVERN_COIN])

    def test_params_match_text(self):
        d = get_db().get("BG27_Anomaly_301")
        self.assertIn(f"only need {B3._FALSE_IDOLS_THRESHOLD} copies",
                      d.text)
        # 张数沿用同文 Clocksworth 先例（1 张 Tavern Coin）
        self.assertEqual(B3._FALSE_IDOLS_COINS, 1)


# ══════════════ BG27_Anomaly_555 No Place Like Holmes ══════════════


class TestNoPlaceLikeHolmes(unittest.TestCase):
    """Each turn, look at 2 minions. Guess which one your next opponent
    had last combat for a Coin. (BG27_Anomaly_555)"""

    @staticmethod
    def _seed_snapshots(g):
        """给每英雄注入"下一对手的上一场战斗阵容"。"""
        for h in g.heroes:
            opp = g.next_opponent(h)
            if opp is None:
                continue
            m = g.create_minion(VANILLA, controller=opp)
            g.summon(opp, m)
            opp.last_combat_board = [m]

    def test_no_snapshot_whiff_then_choice_when_snapshot(self):
        g = game_with("BG27_Anomaly_555")
        start_turn(g, 1, clear_choices=True)
        # 第 1 回合无上一场战斗 → 落空（负）
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "holmes_guess"], [])
        # 正对照: 注入快照后每英雄各一份 2 选项猜测
        self._seed_snapshots(g)
        start_turn(g, 3, clear_choices=True)
        choices = [c for c in g.pending_choices if c.kind == "holmes_guess"]
        self.assertEqual(len(choices), 2)
        for c in choices:
            self.assertEqual(len(c.options), 2)
            real = {m.card_id
                    for m in g.next_opponent(c.owner).last_combat_board}
            self.assertTrue(any(o[0] in real for o in c.options), c.owner)

    def test_correct_guess_gives_coin_wrong_does_not(self):
        g = game_with("BG27_Anomaly_555")
        a, b = g.heroes
        self._seed_snapshots(g)
        start_turn(g, 3, clear_choices=True)
        ca = take_choice(g, "holmes_guess", owner=a)
        real_ids = {m.card_id
                    for m in g.next_opponent(a).last_combat_board}
        idx = next(i for i, o in enumerate(ca.options) if o[0] in real_ids)
        ca.choose(idx)
        self.assertEqual([e.card_id for e in a.hand], [TAVERN_COIN])
        # 猜错（选诱饵）不得 Coin
        cb = take_choice(g, "holmes_guess", owner=b)
        wrong = next(i for i, o in enumerate(cb.options)
                     if o[0] not in {m.card_id for m in
                                     g.next_opponent(b).last_combat_board})
        cb.choose(wrong)
        self.assertEqual([e.card_id for e in b.hand], [])

    def test_control_without_anomaly_no_choice(self):
        g = game_with()
        self._seed_snapshots(g)
        start_turn(g, 3, clear_choices=True)
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "holmes_guess"], [])
        # 正对照: 同 setup + 异变 → 每英雄各一份猜测
        g2 = game_with("BG27_Anomaly_555")
        self._seed_snapshots(g2)
        start_turn(g2, 3, clear_choices=True)
        self.assertEqual(len([c for c in g2.pending_choices
                              if c.kind == "holmes_guess"]), 2)


# ══════════════ BG27_Anomaly_575 Eleventh Hour ══════════════


class TestEleventhHour(unittest.TestCase):
    """The first time your hero takes fatal damage in combat, prevent it
    and gain 11 Gold next turn instead. (BG27_Anomaly_575)"""

    @staticmethod
    def _combat(g, loser, winner):
        big = g.create_minion(VANILLA, controller=winner)
        big.add_buff(BuffEnchant(atk=30, health=30, source_id="test"))
        g.summon(winner, big)
        return g.run_combat(loser, winner, alive_count=2)

    def test_first_fatal_combat_damage_prevented_and_gold(self):
        g = game_with("BG27_Anomaly_575")
        a, b = g.heroes
        a.health = 1
        a.armor = 0
        result = self._combat(g, a, b)
        self.assertIs(result.loser, a)
        self.assertTrue(a.is_alive)                 # 被阻止
        self.assertEqual(a.health, 1)
        self.assertEqual(a.armor, 0)
        self.assertEqual(len(g.deferred_actions), 1)
        # "next turn": 下个招募阶段金币 = 基础收入 + 11
        start_turn(g, 2, clear_choices=True)
        self.assertEqual(a.gold,
                         C.gold_base_income(2, a.income_cap)
                         + B3._ELEVENTH_HOUR_GOLD)

    def test_second_fatal_not_prevented(self):
        g = game_with("BG27_Anomaly_575")
        a, b = g.heroes
        a.health = 1
        a.armor = 0
        self._combat(g, a, b)
        self.assertTrue(a.is_alive)                 # 正对照: 首次被阻止
        a.health = 1
        a.armor = 0
        self._combat(g, a, b)
        self.assertFalse(a.is_alive)                # 仅首次

    def test_recruit_phase_fatal_not_prevented(self):
        g = game_with("BG27_Anomaly_575")
        a = g.heroes[0]
        a.health = 1
        a.take_damage(99)
        self.assertFalse(a.is_alive)                # "in combat" 守卫
        self.assertEqual(g.deferred_actions, [])
        # 正对照: 同一异变在战斗内致命则被阻止并排入下回合金币
        g2 = game_with("BG27_Anomaly_575")
        a2, b2 = g2.heroes
        a2.health = 1
        a2.armor = 0
        self._combat(g2, a2, b2)
        self.assertTrue(a2.is_alive)
        self.assertEqual(len(g2.deferred_actions), 1)

    def test_control_without_anomaly_dies(self):
        g = game_with()
        a, b = g.heroes
        a.health = 1
        a.armor = 0
        self._combat(g, a, b)
        self.assertFalse(a.is_alive)
        # 正对照: 同 setup + 异变 → 被阻止
        g2 = game_with("BG27_Anomaly_575")
        a2, b2 = g2.heroes
        a2.health = 1
        a2.armor = 0
        self._combat(g2, a2, b2)
        self.assertTrue(a2.is_alive)


# ══════════════ BG27_Anomaly_754 Path of the Treasure-Seeker ═════════


class TestPathOfTheTreasureSeeker(unittest.TestCase):
    """Whenever you Refresh 5 times, find the Golden Monkey!
    (@ left!) (BG27_Anomaly_754)"""

    @staticmethod
    def _monkeys(hero, card_id):
        return [e for e in hero.hand if e.card_id == card_id]

    def test_threshold_cycle_and_isolation(self):
        db = get_db()
        d = db.get("BG27_Anomaly_754")
        n = d.num(0)
        token = B3._golden_monkey_card_id(game_with("BG27_Anomaly_754"))
        self.assertIsNotNone(token)
        g = game_with("BG27_Anomaly_754")
        a, b = g.heroes
        # 开局自动刷新已计入（引擎 tavern_refresh 无 auto 标记）
        counted = getattr(a, "_treasure_seeker_refreshes", 0)
        for _ in range(n - counted - 1):
            g.refresh_tavern(a, free=True)
        self.assertEqual(self._monkeys(a, token), [])       # 未达阈值（负）
        g.refresh_tavern(a, free=True)                      # 正对照
        self.assertEqual(len(self._monkeys(a, token)), 1)
        for _ in range(n):
            g.refresh_tavern(a, free=True)
        self.assertEqual(len(self._monkeys(a, token)), 2)   # 周期重复
        # 英雄隔离: B 未刷新 → 无猴
        self.assertEqual(self._monkeys(b, token), [])

    def test_token_is_golden_monkey_from_data_pointer(self):
        g = game_with("BG27_Anomaly_754")
        db = get_db()
        token = B3._golden_monkey_card_id(g)
        td = db.get(token)
        self.assertEqual(td.name, "Golden Monkey")
        self.assertTrue(td.is_golden_def)
        g.refresh_tavern(g.heroes[0], free=True)   # 开头已 1 次 + 本次
        for _ in range(4):
            g.refresh_tavern(g.heroes[0], free=True)
        monkey = self._monkeys(g.heroes[0], token)[0]
        self.assertTrue(monkey.is_golden)
        self.assertTrue(monkey.has(GameTag.TAUNT))
        self.assertEqual(monkey.atk, td.atk)
        self.assertEqual(monkey.max_health, td.health)

    def test_control_without_anomaly(self):
        g = game_with()
        a = g.heroes[0]
        for _ in range(10):
            g.refresh_tavern(a, free=True)
        self.assertEqual([e for e in a.hand
                          if e.card_id.startswith("BG23_353")], [])
        # 正对照: 同刷新次数 + 异变 → 得猴
        token = B3._golden_monkey_card_id(game_with("BG27_Anomaly_754"))
        g2 = game_with("BG27_Anomaly_754")
        a2 = g2.heroes[0]
        for _ in range(10):
            g2.refresh_tavern(a2, free=True)
        self.assertTrue(self._monkeys(a2, token))

    def test_params_match_text(self):
        d = get_db().get("BG27_Anomaly_754")
        self.assertEqual(d.num(0), 5)
        self.assertEqual(d.num(1), 5)
        self.assertIn("5 times", d.text)
        # 授予物由同效果随从卡的 evolution_card_id 指针解析（数据派生）
        db = get_db()
        elise = next(x for x in db._by_id.values()
                     if x.name == "Treasure-Seeker Elise")
        expected = db.by_dbf(elise.evolution_card_id)
        self.assertEqual(B3._golden_monkey_card_id(
            game_with("BG27_Anomaly_754")), expected.id)
        self.assertEqual(expected.name, "Golden Monkey")


# ══════════════ BG27_Anomaly_558 Feline Fortune ══════════════


class TestFelineFortune(unittest.TestCase):
    """After another hero dies, Discover a minion from their warband.
    It keeps enchantments. (BG27_Anomaly_558)"""

    def _eliminate(self, g, victim, card_id=VANILLA, buff=(3, 4)):
        m = g.create_minion(card_id, controller=victim)
        g.summon(victim, m)
        m.add_buff(BuffEnchant(atk=buff[0], health=buff[1],
                               source_id="test_ff"))
        victim.health = 0
        g._process_eliminations()
        return m

    def test_discover_from_dead_warband_keeps_enchantments(self):
        g = game_with("BG27_Anomaly_558", names=("A", "B", "C"))
        a, b, c = g.heroes
        source = self._eliminate(g, c)
        self.assertNotIn(c, g.heroes)
        choices = [ch for ch in g.pending_choices
                   if ch.kind == "discover_minion"]
        self.assertEqual({id(ch.owner) for ch in choices}, {id(a), id(b)})
        for ch in choices:
            self.assertIn(source, ch.options)      # 选项来自死者战团
        ca = take_choice(g, "discover_minion", owner=a)
        ca.choose(ca.options.index(source))
        base = get_db().get(VANILLA)
        copies = [e for e in a.hand if e.card_id == VANILLA]
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy.atk, base.atk + 3)            # 附魔保留
        self.assertEqual(copy.max_health, base.health + 4)
        # 英雄隔离: B 的选择未结算 → B 手牌无副本
        self.assertEqual([e for e in b.hand if e.card_id == VANILLA], [])

    def test_golden_source_copy_is_gilded_not_tripled(self):
        """金色源 → 金色副本；plain copy 须打 GILDED_NOT_TRIPLED
        （出售/淘汰按 1 份回池，RULES §2.3 非三连金口径）。"""
        g = game_with("BG27_Anomaly_558", names=("A", "B", "C"))
        a, b, c = g.heroes
        source = g.create_minion(VANILLA, controller=c, golden=True)
        self.assertTrue(source.is_golden)
        g.summon(c, source)
        c.health = 0
        g._process_eliminations()
        ca = take_choice(g, "discover_minion", owner=a)
        ca.choose(ca.options.index(source))
        copies = [e for e in a.hand if isinstance(e, Minion)]
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertTrue(copy.is_golden)
        self.assertTrue(copy.get(GameTag.GILDED_NOT_TRIPLED, False))
        # 配平: 出售该副本只回池 1 份基础卡（未打标记会回 3 份）
        base_id = copy.get(GameTag.TRIPLE_BASE_CARD_ID)
        before = g.minion_pool.available(base_id)
        self.assertTrue(g.sell_minion(a, copy))
        self.assertEqual(g.minion_pool.available(base_id), before + 1)

    def test_control_without_anomaly_no_choice(self):
        g = game_with(names=("A", "B", "C"))
        self._eliminate(g, g.heroes[2])
        self.assertEqual([ch for ch in g.pending_choices
                          if ch.kind == "discover_minion"], [])
        # 正对照: 同 setup + 异变 → 2 个存活英雄各一份发现
        g2 = game_with("BG27_Anomaly_558", names=("A", "B", "C"))
        self._eliminate(g2, g2.heroes[2])
        self.assertEqual(len([ch for ch in g2.pending_choices
                              if ch.kind == "discover_minion"]), 2)

    def test_dead_hero_does_not_get_choice(self):
        g = game_with("BG27_Anomaly_558", names=("A", "B", "C"))
        a, b, c = g.heroes
        self._eliminate(g, c)
        owners = [ch.owner for ch in g.pending_choices
                  if ch.kind == "discover_minion"]
        self.assertNotIn(c, owners)
        self.assertIn(a, owners)
        self.assertIn(b, owners)

    def test_empty_warband_no_choice(self):
        g = game_with("BG27_Anomaly_558", names=("A", "B", "C"))
        c = g.heroes[2]
        c.health = 0
        g._process_eliminations()
        self.assertEqual([ch for ch in g.pending_choices
                          if ch.kind == "discover_minion"], [])
        # 正对照: 有战团时确有选择
        g2 = game_with("BG27_Anomaly_558", names=("A", "B", "C"))
        self._eliminate(g2, g2.heroes[2])
        self.assertTrue([ch for ch in g2.pending_choices
                         if ch.kind == "discover_minion"])


if __name__ == "__main__":
    unittest.main()
