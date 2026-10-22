"""批次 trinkets1 语义测试（2026-09-01 主线审计+对抗审计后, 8 注册项）。

行为层断言（非 flag）:
  - T433 招募期死亡不触发、战斗内首次死亡恰好 buff 1 个随机友方、
    同场第二次不再触发、COMBAT_END 重置
  - T998 只影响本人 hero 级酒馆下限（对手酒馆仍出 T1）
  - T271 购买后次回合确实出现 Greater trinket_offer
  - T802（Fountain Pen）已解冻注册（元素 give-stats 消费点
    `racefx.elemental_give_bonus` 落地）
  - T400 候选池感知 + active_races 限制
  - T111 EoT 随机 1 个 Murloc +8/+8 + Venomous
  - T543 入手 Channel the Devourer 且每回合再得一张
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.actions.discover import _pool_candidates
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 60):
    g = Game([Hero("TB_BaconShop_HERO_52", "A"),
              Hero("TB_BaconShop_HERO_52", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def buy_trinket(game, hero, tid):
    e = game.create_entity(tid, controller=hero)
    hero.trinkets.append(e)
    game.run_script_hook(e, "on_bind", ctx={"hero": hero})
    return e


class TestRegistry(unittest.TestCase):
    OK = (
        "BG30_MagicItem_996", "BG30_MagicItem_998", "BG30_MagicItem_433",
        "BG32_MagicItem_111", "BG32_MagicItem_271", "BG32_MagicItem_400",
        "BG32_MagicItem_887", "BG30_MagicItem_543",
    )
    # BG30_MagicItem_888 Souvenir Stand 已迁出（batch_trinkets13 实现——
    # 副本条款 grant_trinket(duplicate=)/copy_trinket，RULES §7.4.3）
    # BG30_MagicItem_992（Darnassus Pie）已由 batch_trinkets24、
    # BG32_MagicItem_802（Fountain Pen）已由 batch_trinkets24 注册
    # （元素 give-stats 消费点 `racefx.elemental_give_bonus` 收口）。
    DEFERRED = ("BG32_MagicItem_823",)

    def test_registered(self):
        for tid in self.OK:
            self.assertIn(tid, REGISTRY, tid)
        for tid in self.DEFERRED:
            self.assertNotIn(tid, REGISTRY, tid)


class TestT996(unittest.TestCase):
    def test_gold_and_cap(self):
        g = make_game()
        a = g.heroes[0]
        gold_before = a.gold
        buy_trinket(g, a, "BG30_MagicItem_996")
        self.assertEqual(a.gold, gold_before + 4)
        self.assertEqual(a.income_cap, 10 + 4)


class TestT998(unittest.TestCase):
    def test_gold_and_hero_scoped_flag(self):
        g = make_game(seed=66)
        a, b = g.heroes
        gold_before = a.gold
        buy_trinket(g, a, "BG30_MagicItem_998")
        self.assertEqual(a.gold, gold_before + 2)
        self.assertEqual(a._tavern_min_tier, 3)
        # 旧实现写 game 级 flag 会污染全体对手——现状: 游戏级未设置
        self.assertEqual(getattr(g, "_tavern_min_tier", 1), 1)
        self.assertEqual(getattr(b, "_tavern_min_tier", 1), 1)

    def test_owner_tavern_no_t1_t2_opponent_still_has_t1(self):
        g = make_game(seed=66)
        a, b = g.heroes
        a.set(GameTag.TAVERN_TIER, 4)
        buy_trinket(g, a, "BG30_MagicItem_998")
        g.refresh_tavern(a, auto=True)
        own = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(own)
        for e in own:
            self.assertGreaterEqual(e.tech_level, 3)
        # 对手（无 hero flag、T1 酒馆）仍展出 T1
        b.set(GameTag.TAVERN_TIER, 1)
        g.refresh_tavern(b, auto=True)
        opp = [e for e in b.tavern if isinstance(e, Minion)]
        self.assertTrue(opp)
        for e in opp:
            self.assertEqual(e.tech_level, 1)


class TestT433(unittest.TestCase):
    TID = "BG30_MagicItem_433"

    def _board(self, g, a):
        dying = g.create_minion("BG22_202", controller=a)
        o1 = g.create_minion("BG22_202", controller=a)
        o2 = g.create_minion("BG22_202", controller=a)
        g.summon(a, dying, 0)
        g.summon(a, o1, 1)
        g.summon(a, o2, 2)
        # 死者属性: 2/2 基础上 +3/+4 → atk 5, max_health 6
        g.run_actions(Buff(dying, atk=3, health=4))
        return dying, o1, o2

    def test_first_combat_death_buffs_exactly_one_by_max_stats(self):
        g = make_game(seed=61)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        dying, o1, o2 = self._board(g, a)
        gain_atk, gain_hp = dying.atk, dying.max_health
        self.assertEqual((gain_atk, gain_hp), (5, 6))

        g._active_combat = (a, b)
        try:
            dying.health = 0
            g._process_single_death(dying)
        finally:
            g._active_combat = None

        self.assertEqual(len(a.board), 2)
        buffed = [m for m in a.board if m.atk > 2]
        self.assertEqual(len(buffed), 1)                  # 恰好一个
        self.assertEqual(buffed[0].atk, 2 + gain_atk)
        self.assertEqual(buffed[0].max_health, 2 + gain_hp)
        other = a.board[1] if buffed[0] is a.board[0] else a.board[0]
        self.assertEqual((other.atk, other.max_health), (2, 2))
        # 总量证明只授予了一份（不是"每个同族都加"）
        self.assertEqual(sum(m.atk for m in a.board), 4 + gain_atk)

    def test_recruit_phase_death_does_not_trigger_nor_consume(self):
        g = make_game(seed=62)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        dying, o1, o2 = self._board(g, a)

        self.assertIsNone(getattr(g, "_active_combat", None))
        dying.health = 0
        g._process_single_death(dying)      # 招募期死亡: 不触发
        self.assertEqual([(m.atk, m.max_health) for m in a.board],
                         [(2, 2), (2, 2)])

        # 且未消耗本场次数: 战斗内首次死亡仍触发
        g._active_combat = (a, b)
        try:
            o1.health = 0
            g._process_single_death(o1)
        finally:
            g._active_combat = None
        self.assertEqual([(m.atk, m.max_health) for m in a.board], [(4, 4)])

    def test_once_per_combat_then_combat_end_resets(self):
        g = make_game(seed=63)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        dying, o1, o2 = self._board(g, a)

        g._active_combat = (a, b)
        try:
            dying.health = 0
            g._process_single_death(dying)
            buffed = [m for m in a.board if m.atk > 2]
            self.assertEqual(len(buffed), 1)
            buffed_stats = (buffed[0].atk, buffed[0].max_health)
            victim = o1 if buffed[0] is o2 else o2
            victim.health = 0
            g._process_single_death(victim)   # 同场第二次死亡: 不再触发
        finally:
            g._active_combat = None
        self.assertEqual((buffed[0].atk, buffed[0].max_health), buffed_stats)

        # COMBAT_END 重置 → 新一场再次触发
        a.board.clear()
        g.events.fire(g, "combat_end", hero_a=a, hero_b=b, result="draw")
        d2 = g.create_minion("BG22_202", controller=a)
        tgt = g.create_minion("BG22_202", controller=a)
        g.summon(a, d2, 0)
        g.summon(a, tgt, 1)
        g._active_combat = (a, b)
        try:
            d2.health = 0
            g._process_single_death(d2)
        finally:
            g._active_combat = None
        self.assertEqual([(m.atk, m.max_health) for m in a.board], [(4, 4)])


class TestT271(unittest.TestCase):
    def test_early_greater_offer_fires_next_turn(self):
        g = make_game(seed=67)
        a = g.heroes[0]
        buy_trinket(g, a, "BG32_MagicItem_271")
        self.assertEqual(a._trinket_early, {"greater": g.turn + 1})
        self.assertNotIn((a, "greater"), g._trinket_offered)

        n_before = len(g.pending_choices)
        g.end_recruit_phase()                 # 回合推进 1 → 2

        new_offers = [c for c in g.pending_choices[n_before:]
                      if c.kind == "trinket_offer" and c.owner is a]
        self.assertEqual(len(new_offers), 1)
        self.assertIn((a, "greater"), g._trinket_offered)
        for o in new_offers[0].options[:-1]:
            self.assertEqual(o.card_type, 44)      # 3 选 + 放弃


class TestT400(unittest.TestCase):
    def test_transform_all_minions_t4(self):
        g = make_game(seed=65)
        a = g.heroes[0]
        m1 = g.create_minion("BG22_202", controller=a)
        m2 = g.create_minion("BG22_202", controller=a)
        g.summon(a, m1, 0)
        g.summon(a, m2, 1)
        buy_trinket(g, a, "BG32_MagicItem_400")
        self.assertEqual(len(a.board), 2)
        for x in a.board:
            self.assertEqual(x.tech_level, 4)

    def test_transform_respects_active_races_and_pool(self):
        g = make_game(seed=64)
        a = g.heroes[0]
        g.minion_pool.active_races = {Race.DRAGON}
        m = g.create_minion("BG22_202", controller=a)
        g.summon(a, m)

        cands = _pool_candidates(g, min_tier=4, max_tier=4)
        self.assertTrue(cands)
        avail_before = {cid: g.minion_pool.available(cid) for cid in cands}

        buy_trinket(g, a, "BG32_MagicItem_400")

        new = a.board[0]
        self.assertIsNot(new, m)
        self.assertEqual(new.tech_level, 4)
        # 禁用种族（如 Beast）不得出现——只可能是龙/全种族/无种族
        self.assertIn(new.race, (Race.DRAGON, Race.ALL, Race.NONE))
        # 占池: 选中卡余量 -1
        self.assertEqual(g.minion_pool.available(new.card_id),
                         avail_before[new.card_id] - 1)


class TestT802(unittest.TestCase):
    """T802 Fountain Pen：**已解冻**（batch_trinkets24 注册）。

    @engine-only —— 本类只剩结构性守卫（注册面 + 跨仓消费点 AST 探针）;
    行为层断言在卡片本体所属批次 `test_batch_trinkets24.py::
    TestFountainPen`（含 Dancing Barnstormer 端到端 + 负对照）。

    解冻依据（2026-09-02）: 元素 give-stats 的统一消费点
    `hsrl2/actions/racefx.py::elemental_give_bonus` 落地并有生产调用方
    （Dancing Barnstormer / Unleashed Mana Surge / Baller 三兄弟 /
    Waveling / En-Djinn Blazer / Stone Age Slab），RULES §7.4.5。
    本类改为"解冻守卫": 若哪天 802 又被撤注册或消费点被移除，本测试红。
    """

    def test_now_registered(self):
        from hsrl2.scripts import REGISTRY
        self.assertIn("BG32_MagicItem_802", REGISTRY)

    def test_consumer_wired(self):
        """消费点存在真实调用方（AST 查找，文档字符串提及不算）。"""
        import ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        calls = []
        for p in root.rglob("*.py"):
            if "tests" in p.parts or "__pycache__" in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else \
                    getattr(fn, "attr", None)
                if name in ("elemental_give_bonus", "elemental_buff"):
                    calls.append(f"{p.name}:{node.lineno}")
        self.assertTrue(calls,
                        "elemental_give_bonus 无生产调用点——元素 "
                        "give-stats 加成会重新变成 write-only 空转")


class TestT111(unittest.TestCase):
    TID = "BG32_MagicItem_111"

    def test_eot_buffs_one_random_murloc_with_venomous(self):
        g = make_game(seed=71)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        m1 = g.create_minion("BG22_202", controller=a)
        m2 = g.create_minion("BG22_202", controller=a)
        g.summon(a, m1, 0)
        g.summon(a, m2, 1)

        g.run_script_hook(t, "end_of_turn")

        buffed = [m for m in (m1, m2) if m.has(GameTag.VENOMOUS)]
        self.assertEqual(len(buffed), 1)
        self.assertEqual((buffed[0].atk, buffed[0].max_health), (10, 10))
        other = m2 if buffed[0] is m1 else m1
        self.assertEqual((other.atk, other.max_health), (2, 2))
        self.assertFalse(other.has(GameTag.VENOMOUS))

    def test_eot_ignores_non_murlocs(self):
        g = make_game(seed=72)
        a = g.heroes[0]
        t = buy_trinket(g, a, self.TID)
        beast = g.create_minion("BG25_001", controller=a)   # Undead
        g.summon(a, beast)
        atk_before = beast.atk
        g.run_script_hook(t, "end_of_turn")
        self.assertEqual(beast.atk, atk_before)
        self.assertFalse(beast.has(GameTag.VENOMOUS))


class TestT823(unittest.TestCase):
    def test_not_registered(self):
        self.assertNotIn("BG32_MagicItem_823", REGISTRY)


class TestT887(unittest.TestCase):
    def test_armor_and_demon(self):
        g = make_game()
        a = g.heroes[0]
        armor_before = a.armor
        buy_trinket(g, a, "BG32_MagicItem_887")
        self.assertEqual(a.armor, armor_before + 5)
        m = g.create_minion("BG25_001", controller=a)
        m.set(GameTag.RACE, Race.DEMON)
        a.add_to_hand(m)
        g.play_minion(a, m)
        self.assertEqual(a.armor, armor_before + 5 - 1)   # 护甲吸收


class TestT543(unittest.TestCase):
    SPELL = "EBG_Spell_032"

    def test_grants_spell_and_one_more_each_turn(self):
        g = make_game(seed=68)
        a, b = g.heroes
        buy_trinket(g, a, "BG30_MagicItem_543")
        self.assertEqual([e.card_id for e in a.hand].count(self.SPELL), 1)
        self.assertEqual([e.card_id for e in b.hand], [])

        g.end_recruit_phase()                # 回合开始 TURN_START 再给一张
        self.assertEqual([e.card_id for e in a.hand].count(self.SPELL), 2)
        self.assertEqual([e.card_id for e in b.hand], [])


if __name__ == "__main__":
    unittest.main()
