"""批次 anomalies2 语义测试（作业单 2026-09-02）。

覆盖:
  - BG27_Anomaly_572/559/570/571/573 Treasure Hoard
  - BG31_Anomaly_124 Golden Arrow（+ token BG31_Anomaly_124t4）
  - BG27_Anomaly_751 Perfected Alchemy（+ token BG26_813t The Goldenizer）
  - BG27_Anomaly_505 Reckless Enhancement

测试验证脚本 docstring 的 Formal spec（非实现细节）: 真实回合驱动
（`_begin_recruit_for`）、PendingChoice 结算、金卡本体（数据权威）、
英雄隔离、满手排队、once 语义。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType, GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

GOLDEN_ARROW_TOKEN = "BG31_Anomaly_124t4"
GOLDENIZER = "BG26_813t"
VANILLA = "BG20_100"           # Razorfen Geomancer 2/1 T1 无四关键词

ALL_IDS = (
    "BG27_Anomaly_572", "BG27_Anomaly_559", "BG27_Anomaly_570",
    "BG27_Anomaly_571", "BG27_Anomaly_573",
    "BG31_Anomaly_124", "BG31_Anomaly_124t4",
    "BG27_Anomaly_751", "BG26_813t",
    "BG27_Anomaly_505",
)


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def game_with(anomaly: str, seed: int = 40) -> Game:
    g = Game([Hero("TB_BaconShop_HERO_52", "A"),
              Hero("TB_BaconShop_HERO_52", "B")],
             get_db(), seed=seed, anomaly=anomaly)
    g.start_game()
    return g


def begin_all(game: Game) -> None:
    """驱动一回合开始（每存活英雄一次），不跑战斗编排。"""
    for h in game.heroes:
        if h.is_alive:
            game._begin_recruit_for(h)


def take_choice(game: Game, kind: str, owner=None):
    """按 kind（可选 owner）取出一条 PendingChoice 并出队（SOP §8 契约）。"""
    if owner is None:
        choice = next(c for c in game.pending_choices if c.kind == kind)
    else:
        choice = next(c for c in game.pending_choices
                      if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(choice)
    return choice


def golden_doubled(card_id: str) -> bool:
    """该卡的金卡本体是否为翻倍属性（BG 规则; 2 张池卡例外）。"""
    d = get_db().get(card_id)
    gd = get_db().golden_version(d)
    return gd is not None and (gd.atk, gd.health) == (d.atk * 2, d.health * 2)


class TestRegistry(unittest.TestCase):
    def test_all_ids_registered(self):
        for cid in ALL_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_token_lookup_by_name(self):
        db = get_db()
        arrow = [d for d in db._by_id.values()
                 if d.name == "Golden Arrow" and d.card_type == CardType.SPELL]
        self.assertEqual([d.id for d in arrow], [GOLDEN_ARROW_TOKEN])
        gold = [d for d in db._by_id.values() if d.name == "The Goldenizer"]
        self.assertEqual([d.id for d in gold], [GOLDENIZER])


# ══════════════════ Treasure Hoard ══════════════════


class TestTreasureHoard(unittest.TestCase):
    """On Turn N, Discover a Golden Tier T minion."""

    CASES = (
        ("BG27_Anomaly_572", 5, 3),
        ("BG27_Anomaly_559", 6, 4),
        ("BG27_Anomaly_570", 7, 5),
        ("BG27_Anomaly_571", 8, 6),
        ("BG27_Anomaly_573", 9, 7),
    )

    def _assert_case(self, aid: str, turn: int, tier: int) -> None:
        db = get_db()
        g = game_with(aid)
        a, b = g.heroes
        # 触发前一回合: 发现未发生（condition 锁 turn）
        g.turn = turn - 1
        begin_all(g)
        self.assertEqual(
            [c for c in g.pending_choices if c.kind == "discover_minion"], [])
        # 触发回合: 每英雄各一份发现（闭包 _h=h 绑定）
        g.turn = turn
        begin_all(g)
        choices = [c for c in g.pending_choices if c.kind == "discover_minion"]
        self.assertEqual(len(choices), 2)
        self.assertEqual({id(c.owner) for c in choices}, {id(a), id(b)})
        ca = next(c for c in choices if c.owner is a)
        cb = next(c for c in choices if c.owner is b)
        # 选项全为该异变的 tier，且为三选一
        self.assertEqual(len(ca.options), 3)
        for cid in ca.options:
            self.assertEqual(db.get(cid).tech_level, tier, cid)
        # 选一个金卡本体属性翻倍的选项（金卡数据权威）
        idx = next(i for i, cid in enumerate(ca.options)
                   if golden_doubled(cid))
        picked = ca.options[idx]
        g.pending_choices.remove(ca)
        ca.choose(idx)
        hand_a = [e for e in a.hand if isinstance(e, Minion)]
        self.assertEqual(len(hand_a), 1)
        m = hand_a[0]
        base = db.get(picked)
        gold = db.golden_version(base)
        self.assertEqual(m.card_id, gold.id)          # 金卡本体（独立定义）
        self.assertTrue(m.is_golden)
        self.assertEqual(m.atk, gold.atk)
        self.assertEqual(m.max_health, gold.health)
        self.assertEqual(m.atk, base.atk * 2)         # 属性翻倍
        self.assertEqual(m.max_health, base.health * 2)
        self.assertEqual(m.get(GameTag.TRIPLE_BASE_CARD_ID), picked)
        # 英雄隔离: B 自己的发现尚未结算 → B 手牌无随从
        self.assertEqual([e for e in b.hand if isinstance(e, Minion)], [])
        g.pending_choices.remove(cb)
        cb.choose(0)
        hand_b = [e for e in b.hand if isinstance(e, Minion)]
        self.assertEqual(len(hand_b), 1)
        self.assertTrue(hand_b[0].is_golden)
        self.assertNotEqual(hand_b[0].uuid, m.uuid)

    def test_572_turn5_tier3(self):
        self._assert_case("BG27_Anomaly_572", 5, 3)

    def test_559_turn6_tier4(self):
        self._assert_case("BG27_Anomaly_559", 6, 4)

    def test_570_turn7_tier5(self):
        self._assert_case("BG27_Anomaly_570", 7, 5)

    def test_571_turn8_tier6(self):
        self._assert_case("BG27_Anomaly_571", 8, 6)

    def test_573_turn9_tier7(self):
        self._assert_case("BG27_Anomaly_573", 9, 7)

    def test_tier_table_matches_text_and_num(self):
        """tier 是文本字面量; turn = num(0)+1（数据权威交叉核对）。"""
        from hsrl2.scripts.batches.batch_anomalies2 import (
            _TREASURE_HOARD_TIERS)
        db = get_db()
        for aid, turn, tier in self.CASES:
            d = db.get(aid)
            self.assertIn(f"Golden Tier {tier} minion", d.text)
            self.assertEqual(turn, d.num(0) + 1)
            self.assertEqual(_TREASURE_HOARD_TIERS[aid], tier)

    def test_fires_once_per_hero(self):
        g = game_with("BG27_Anomaly_572")
        g.turn = 5
        begin_all(g)
        choices = [c for c in g.pending_choices if c.kind == "discover_minion"]
        self.assertEqual(len(choices), 2)
        for c in choices:
            g.pending_choices.remove(c)
            c.choose(0)
        # 重入同一回合: once 监听器已消费 → 不再产生发现
        g.turn = 5
        begin_all(g)
        self.assertEqual(
            [c for c in g.pending_choices if c.kind == "discover_minion"], [])


# ══════════════════ Golden Arrow ══════════════════


class TestGoldenArrow(unittest.TestCase):
    """Every 3 turns, get a Golden Arrow. (BG31_Anomaly_124)"""

    def test_grants_from_turn_num0_plus_1_then_every_period(self):
        """相位裁定: 首次触发 = num(0)+1 = 第 4 回合（同批 Treasure
        Hoard "On Turn N" ↔ num(0)=N−1 模型 + 完成态 "(Next turn!)"）。"""
        g = game_with("BG31_Anomaly_124")
        a, b = g.heroes
        def arrows(hero):
            return len([e for e in hero.hand
                        if e.card_id == GOLDEN_ARROW_TOKEN])
        # 第 1/2/3 回合都不给（旧实现第 3 回合误给）
        for t in (1, 2, 3):
            g.turn = t
            begin_all(g)
            self.assertEqual(arrows(a), 0, f"turn {t}")
        g.turn = 4
        begin_all(g)
        self.assertEqual(arrows(a), 1)
        self.assertEqual(arrows(b), 1)          # 每英雄独立
        for t in (5, 6):
            g.turn = t
            begin_all(g)
            self.assertEqual(arrows(a), 1, f"turn {t}")
        g.turn = 7
        begin_all(g)
        self.assertEqual(arrows(a), 2)
        self.assertEqual(arrows(b), 2)

    def test_arrow_token_is_targeted_tavern_spell(self):
        d = get_db().get(GOLDEN_ARROW_TOKEN)
        self.assertEqual(d.card_type, CardType.SPELL)
        self.assertIn("Choose a minion in the", d.text)
        script = REGISTRY[GOLDEN_ARROW_TOKEN]
        self.assertTrue(getattr(script, "needs_target", False))

    def test_arrow_makes_tavern_minion_golden(self):
        g = game_with("BG31_Anomaly_124")
        a, b = g.heroes
        g.turn = 4
        begin_all(g)
        arrow = next(e for e in a.hand
                     if e.card_id == GOLDEN_ARROW_TOKEN)
        # 受控酒馆: 1 个可金卡化随从（带 buff）+ 1 张法术（非候选）
        target = g.create_minion(VANILLA, controller=a)
        target.zone = Zone.TAVERN
        target.add_buff(BuffEnchant(atk=1, health=2,
                                    source_id="test_arrow"))
        tavern_spell = g.create_spell("BG28_830", controller=a)
        tavern_spell.zone = Zone.TAVERN
        a.tavern = [target, tavern_spell]

        self.assertTrue(g.play_spell(a, arrow))
        pc = take_choice(g, kind="spell_target")
        self.assertEqual(pc.options, [target])       # 法术不在候选
        pc.choose(0)

        new = a.tavern[0]
        base = get_db().get(VANILLA)
        gold = get_db().golden_version(base)
        self.assertEqual(new.card_id, gold.id)        # 金卡本体
        self.assertTrue(new.is_golden)
        self.assertTrue(new.get(GameTag.GILDED_NOT_TRIPLED, False))
        self.assertEqual(new.atk, gold.atk + 1)        # buff 保留
        self.assertEqual(new.max_health, gold.health + 2)
        self.assertEqual(new.health, new.max_health)   # 金色化满血
        self.assertNotIn(arrow, a.hand)                # 法术已消耗
        self.assertIs(a.tavern[1], tavern_spell)       # 法术原位保留
        # 英雄隔离: B 的箭仍在手
        self.assertEqual(len([e for e in b.hand
                              if e.card_id == GOLDEN_ARROW_TOKEN]), 1)

    def test_arrow_with_empty_tavern_fizzles(self):
        g = game_with("BG31_Anomaly_124")
        a = g.heroes[0]
        g.turn = 4
        begin_all(g)
        arrow = next(e for e in a.hand
                     if e.card_id == GOLDEN_ARROW_TOKEN)
        a.tavern = []
        self.assertTrue(g.play_spell(a, arrow))        # 无目标仍消耗
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "spell_target"], [])
        self.assertNotIn(arrow, a.hand)

    def test_full_hand_queues_arrow_until_space(self):
        g = game_with("BG31_Anomaly_124")
        a = g.heroes[0]
        while not a.hand_full():
            a.add_to_hand(g.create_spell("BG28_830", controller=a))
        g.turn = 4
        begin_all(g)
        self.assertEqual([e for e in a.hand
                          if e.card_id == GOLDEN_ARROW_TOKEN], [])
        queued = [e for h, e in g.pending_hand_queue if h is a]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].card_id, GOLDEN_ARROW_TOKEN)
        a.hand.pop()                                   # 腾出手牌位
        g.turn = 5
        begin_all(g)
        self.assertEqual(len([e for e in a.hand
                              if e.card_id == GOLDEN_ARROW_TOKEN]), 1)


# ══════════════════ Perfected Alchemy / The Goldenizer ══════════════════


class TestPerfectedAlchemy(unittest.TestCase):
    """Start with a Goldenizer. (BG27_Anomaly_751)"""

    def test_goldenizer_card_definition(self):
        d = get_db().get(GOLDENIZER)
        self.assertEqual(d.name, "The Goldenizer")
        self.assertEqual(d.card_type, CardType.BACON_SPELL)
        self.assertEqual(d.text, "Make a friendly minion Golden.")
        self.assertIn(GOLDENIZER, REGISTRY)             # 此前无脚本 → 本批实现

    def test_start_with_goldenizer_per_hero(self):
        g = game_with("BG27_Anomaly_751")
        for h in g.heroes:
            self.assertEqual(
                [e.card_id for e in h.hand if e.card_id == GOLDENIZER],
                [GOLDENIZER])

    def test_goldenizer_targets_friendly_board_minion(self):
        g = game_with("BG27_Anomaly_751")
        a, b = g.heroes
        spell = next(e for e in a.hand if e.card_id == GOLDENIZER)
        ally = g.create_minion(VANILLA, controller=a)
        enemy = g.create_minion(VANILLA, controller=b)
        g.summon(a, ally)
        g.summon(b, enemy)
        self.assertTrue(g.play_spell(a, spell))
        pc = take_choice(g, kind="spell_target")
        self.assertEqual(pc.options, [ally])            # 敌方不在候选
        pc.choose(0)
        new = a.board[0]
        base = get_db().get(VANILLA)
        gold = get_db().golden_version(base)
        self.assertEqual(new.card_id, gold.id)
        self.assertTrue(new.is_golden)
        self.assertTrue(new.get(GameTag.GILDED_NOT_TRIPLED, False))
        self.assertEqual(new.atk, gold.atk)
        self.assertEqual(new.max_health, gold.health)
        self.assertNotIn(spell, a.hand)
        # 英雄隔离: 敌方随从与 B 的手牌不受影响
        self.assertEqual(b.board[0].card_id, VANILLA)
        self.assertFalse(b.board[0].is_golden)
        self.assertEqual(len([e for e in b.hand if e.card_id == GOLDENIZER]), 1)

    def test_goldenizer_with_no_friendly_minion_fizzles(self):
        g = game_with("BG27_Anomaly_751")
        a = g.heroes[0]
        spell = next(e for e in a.hand if e.card_id == GOLDENIZER)
        self.assertTrue(g.play_spell(a, spell))         # 无候选仍消耗
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "spell_target"], [])
        self.assertNotIn(spell, a.hand)


# ══════════════════ Reckless Enhancement ══════════════════


class TestRecklessEnhancement(unittest.TestCase):
    """Minions in the Tavern each randomly gain Taunt, Windfury,
    Divine Shield, or Reborn. (BG27_Anomaly_505)"""

    KEYWORDS = (GameTag.TAUNT, GameTag.WINDFURY,
                GameTag.DIVINE_SHIELD, GameTag.REBORN)
    KW_NAME = {GameTag.TAUNT: "taunt", GameTag.WINDFURY: "windfury",
               GameTag.DIVINE_SHIELD: "divine_shield",
               GameTag.REBORN: "reborn"}

    def _count(self, m) -> int:
        return sum(1 for t in self.KEYWORDS if m.has(t))

    def test_initial_shop_minions_gain_one_of_four(self):
        """开局自动刷新的馆内每个随从各得四关键词之一。"""
        g = game_with("BG27_Anomaly_505", seed=7)
        db = get_db()
        n_min = 0
        for h in g.heroes:
            mins = [e for e in h.tavern if isinstance(e, Minion)]
            self.assertTrue(mins)
            n_min += len(mins)
            for m in mins:
                innate = {t for t in self.KEYWORDS
                          if self.KW_NAME[t] in db.get(m.card_id).keywords}
                if not innate:        # 白板随从必定恰好获得 1 个
                    self.assertEqual(self._count(m), 1, m.card_id)
                else:
                    self.assertGreaterEqual(self._count(m), 1, m.card_id)
        # 每个馆内随从各消耗一次随机决策（监听逐随从生效）
        decisions = [d for d in g.rng.decisions
                     if d[0] == "reckless_enhancement"]
        self.assertEqual(len(decisions), n_min)

    def test_real_refresh_grants_exactly_one_to_kept_vanilla(self):
        """真实回合路径: 冻结保留的白板随从刷新后恰好得 1 个关键词。"""
        g = game_with("BG27_Anomaly_505")
        a = g.heroes[0]
        vanilla = g.create_minion(VANILLA, controller=a)   # 2/1 无关键词
        vanilla.zone = Zone.TAVERN
        a.tavern = [vanilla]
        a.set(GameTag.FROZEN, True)        # 整馆冻结 → 刷新保留该实体
        before = sum(1 for d in g.rng.decisions
                     if d[0] == "reckless_enhancement")
        g.turn = 2
        g._begin_recruit_for(a)            # 真实回合开始（含自动刷新）
        self.assertIn(vanilla, a.tavern)
        self.assertEqual(self._count(vanilla), 1)
        after = sum(1 for d in g.rng.decisions
                    if d[0] == "reckless_enhancement")
        n_min = len([e for e in a.tavern if isinstance(e, Minion)])
        self.assertEqual(after - before, n_min)

    def test_hero_isolation_and_board_untouched(self):
        g = game_with("BG27_Anomaly_505")
        a, b = g.heroes
        ta = g.create_minion(VANILLA, controller=a)
        ta.zone = Zone.TAVERN
        tb = g.create_minion(VANILLA, controller=b)
        tb.zone = Zone.TAVERN
        a.tavern = [ta]
        b.tavern = [tb]
        board = g.create_minion(VANILLA, controller=a)
        g.summon(a, board)

        g.events.fire(g, "tavern_refresh", hero=a)
        self.assertEqual(self._count(ta), 1)
        self.assertEqual(self._count(tb), 0)       # 英雄隔离
        self.assertEqual(self._count(board), 0)    # 棋盘不受影响
        g.events.fire(g, "tavern_refresh", hero=b)
        self.assertEqual(self._count(tb), 1)
        self.assertEqual(self._count(ta), 1)       # A 不被 B 的刷新重复施加


if __name__ == "__main__":
    unittest.main()
