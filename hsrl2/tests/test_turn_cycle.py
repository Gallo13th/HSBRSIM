"""hsrl2 回合状态机测试 — end_recruit_phase / 配对 / 幽灵战 / 淘汰回池 /
战斗持久化 (RULES §1.2/§2.3/§3.5/§4.8/§5/§6.13)。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.constants import TAVERN_OFFERS, gold_base_income
from hsrl2.db import CardDB
from hsrl2.entity import Buff, Entity
from hsrl2.game import PERSIST_TAG, Game
from hsrl2.hero import Hero
from hsrl2.matchmaking import pair_players
from hsrl2.minion import Minion
from hsrl2.rng import GameRNG
from hsrl2.spell import Spell
from hsrl2.tags import CardType, GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def tier1_pool_minion_id() -> str:
    return next(d.id for d in get_db().pool_minions() if d.tech_level == 1)


def pool_spell_id() -> str:
    return next(iter(get_db().pool_spells())).id


class TestEndRecruitPhaseCycle(unittest.TestCase):
    """完整走一轮: 金币重置 / 酒馆刷新 / turn+1 (RULES §1.2)。"""

    def test_full_cycle(self):
        game = make_game(seed=1)
        game.start_game()
        a, b = game.heroes
        a.gold = 1            # 回合结束不储蓄 (RULES §1.4)
        game.end_recruit_phase()
        self.assertEqual(game.turn, 2)
        self.assertFalse(game.finished)
        for h in (a, b):
            self.assertEqual(h.gold, gold_base_income(2))
            minions = [e for e in h.tavern if isinstance(e, Minion)]
            self.assertEqual(len(minions), TAVERN_OFFERS[1])
        # 双方空棋盘 → 平局不造成伤害 (RULES §4.7)
        self.assertEqual(a.health, 30)
        self.assertEqual(b.health, 30)
        self.assertEqual(len(game._opponent_history), 2)


class TestEndOfTurnOrder(unittest.TestCase):
    """EoT 顺序: 饰品 → 任务奖励 → 随从；EoT 可致死 (RULES §1.2)。"""

    def test_order_and_selfkill(self):
        game = make_game(seed=2)
        a, b = game.heroes
        order = []
        trinket = Entity("TEST_TRINKET", "Trink",
                         card_type=CardType.BACON_TRINKET)
        trinket.set_script_override(
            "end_of_turn", lambda s, g, c: order.append("trinket"))
        a.trinkets.append(trinket)
        reward = Entity("TEST_QR", "QR",
                        card_type=CardType.BACON_QUEST_REWARD)
        reward.set_script_override(
            "end_of_turn", lambda s, g, c: order.append("reward"))
        a.quest_rewards = [reward]
        m1 = make_minion("M1", 1, 5)
        m1.set_script_override(
            "end_of_turn", lambda s, g, c: order.append("m1"))
        m2 = make_minion("M2", 1, 5)
        m2.set_script_override(
            "end_of_turn", lambda s, g, c: setattr(s, "health", 0))
        a.board = [m1, m2]
        for m in a.board:
            m.controller = a
            m.zone = Zone.PLAY
        game.end_recruit_phase()
        self.assertEqual(order, ["trinket", "reward", "m1"])
        # 自残随从 EoT 死亡，不进入战斗
        self.assertNotIn(m2, a.board)
        self.assertIn(m2, a.graveyard)
        self.assertIn(m1, a.board)


class TestSpellcraftDiscard(unittest.TestCase):
    """Spellcraft 法术回合结束消失，普通酒馆法术保留 (RULES §6.13)。"""

    def test_discard(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        sc = Spell("TEST_SC", "SC")
        sc.set(GameTag.SPELLCRAFT, True)
        sc.zone = Zone.HAND
        normal = Spell("TEST_NORMAL", "N")
        normal.zone = Zone.HAND
        a.hand = [sc, normal]
        game.end_recruit_phase()
        self.assertNotIn(sc, a.hand)
        self.assertEqual(sc.zone, Zone.REMOVED)
        self.assertIn(normal, a.hand)


class TestPairPlayers(unittest.TestCase):
    """配对: 8 人无重复 / 奇数 leftover / 最近对手回避 (RULES §4.8)。"""

    def test_eight_players(self):
        heroes = [make_hero(str(i)) for i in range(8)]
        hist = {}
        pairs, leftover = pair_players(heroes, GameRNG(5), hist)
        self.assertIsNone(leftover)
        self.assertEqual(len(pairs), 4)
        flat = [h for p in pairs for h in p]
        self.assertEqual(len(set(flat)), 8)
        self.assertEqual(set(flat), set(heroes))
        for p1, p2 in pairs:
            self.assertEqual(hist[p1], [p2])
            self.assertEqual(hist[p2], [p1])

    def test_odd_leftover(self):
        heroes = [make_hero(str(i)) for i in range(7)]
        pairs, leftover = pair_players(heroes, GameRNG(6), {})
        self.assertEqual(len(pairs), 3)
        self.assertIn(leftover, heroes)
        flat = [h for p in pairs for h in p] + [leftover]
        self.assertEqual(set(flat), set(heroes))

    def test_recent_opponent_avoidance(self):
        a, b, c, d = (make_hero(n) for n in "ABCD")
        base = {a: [b], b: [a], c: [d], d: [c]}
        for seed in range(30):
            hist = {k: list(v) for k, v in base.items()}
            pairs, _ = pair_players([a, b, c, d], GameRNG(seed), hist)
            for p1, p2 in pairs:
                self.assertNotEqual({p1, p2}, {a, b}, f"seed={seed}")
                self.assertNotEqual({p1, p2}, {c, d}, f"seed={seed}")

    def test_no_immediate_repeat_eight_players(self):
        """回归: 单轮贪心尾部强制不得造成连续回合重复对手（重洗重试兜底）。"""
        heroes = [make_hero(str(i)) for i in range(8)]
        for seed in range(10):
            game_hist: dict = {}
            rng = GameRNG(seed)
            prev: dict = {}
            for _turn in range(6):
                pairs, _ = pair_players(heroes, rng, game_hist)
                for p1, p2 in pairs:
                    self.assertIsNot(prev.get(p1), p2,
                                     f"seed={seed} immediate repeat")
                prev = {p1: p2 for p1, p2 in pairs}

    def test_fallback_when_all_excluded(self):
        a, b, c = (make_hero(n) for n in "ABC")
        hist = {a: [b, c], b: [a, c], c: [a, b]}
        pairs, leftover = pair_players([a, b, c], GameRNG(7), hist)
        self.assertEqual(len(pairs), 1)
        self.assertIsNotNone(leftover)
        self.assertEqual(len(hist[a] + hist[hist[a][0]]), 4)  # 各保留最近 2


class TestEliminationPoolReturn(unittest.TestCase):
    """淘汰: 棋盘+手牌+酒馆回池（金色 3 份）→ ghost_records (RULES §2.3/§4.8)。"""

    def test_elimination_pool_accounting(self):
        game = make_game(seed=4)
        a, b = game.heroes
        cid = tier1_pool_minion_id()
        sid = pool_spell_id()
        pool = game.minion_pool
        avail0 = pool.available(cid)
        spell_avail0 = game.spell_pool.available(sid)
        # 棋盘: 普通 1 + 金色 1（金色回池 3 份）
        m1 = game.create_minion(cid, controller=b)
        mg = game.create_minion(cid, controller=b, golden=True)
        b.board = [m1, mg]
        # 手牌随从
        mh = game.create_minion(cid, controller=b)
        b.hand = [mh]
        # 酒馆: 随从 + 池内法术（先 acquire 模拟被展示占用）
        mt = game.create_minion(cid, controller=b)
        self.assertTrue(game.spell_pool.acquire(sid))
        sp = game.create_spell(sid, controller=b)
        b.tavern = [mt, sp]
        self.assertEqual(pool.available(cid), avail0)   # create 不占池
        b.health = 0
        game._process_eliminations()
        # 回池 = 棋盘(1+3) + 手牌(1) + 酒馆随从(1)
        self.assertEqual(pool.available(cid), avail0 + 6)
        # 法术: 展示占 1 份 → 淘汰回池复原量
        self.assertEqual(game.spell_pool.available(sid), spell_avail0)
        self.assertNotIn(b, game.heroes)
        self.assertEqual(len(game.ghost_records), 1)
        record = game.ghost_records[-1]
        self.assertEqual(record["name"], b.name)
        self.assertEqual(record["tavern_tier"], b.tavern_tier)
        self.assertEqual(len(record["board"]), 2)
        for orig, clone in zip(b.board, record["board"]):
            self.assertIsNot(orig, clone)
            self.assertIsNot(orig.tags, clone.tags)
            self.assertIsNot(orig._buffs, clone._buffs)
        self.assertEqual(b.health, 0)
        # 重复调用不重复回池
        game._process_eliminations()
        self.assertEqual(pool.available(cid), avail0 + 6)


class TestGhostCombat(unittest.TestCase):
    """幽灵战: 伤害公式含 tier 基数 / 胜不受伤 / 无记录跳过 (RULES §4.8/§5)。"""

    def test_no_record_skips(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        a.board = [make_minion("X", 1, 1)]
        self.assertIsNone(game.run_ghost_combat(a))
        self.assertEqual(a.health, 30)

    def _record(self, game, tier, minions):
        for m in minions:
            m.game = game
        return {"name": "DeadGuy", "board": list(minions), "tavern_tier": tier}

    def test_hero_loses_damage_formula(self):
        game = make_game(seed=8)
        a, b = game.heroes
        game.turn = 10
        game.ghost_records.append(self._record(game, 4, [
            make_minion("G1", 2, 5, tech_level=2),
            make_minion("G2", 3, 5, tech_level=3),
        ]))
        a.board = []                      # 空棋盘 → 必败
        game.run_ghost_combat(a)
        # 伤害 = ghost tier 4 + (2 + 3) = 9；2 人存活 → 无上限 (RULES §5.2)
        self.assertEqual(a.health, 30 - 9)
        # 幽灵对手记 None
        self.assertEqual(game._opponent_history[a][-1], None)
        self.assertEqual(game.combat_memory[a][-1], None)
        self.assertEqual(len(game.heroes), 2)   # 幽灵已移除

    def test_hero_wins_takes_no_damage(self):
        game = make_game(seed=9)
        a = game.heroes[0]
        game.ghost_records.append(self._record(game, 2, [
            make_minion("g", 1, 1, tech_level=1),
        ]))
        a.board = [make_minion("Big", 10, 10)]
        game.run_ghost_combat(a)
        self.assertEqual(a.health, 30)
        self.assertEqual(a.armor, 0)
        # 幽灵记录为冻结副本，战斗死亡不污染
        g = game.ghost_records[-1]["board"][0]
        self.assertEqual(g.health, 1)
        self.assertEqual(g.atk, 1)
        self.assertIsNone(g.controller)

    def test_damage_respects_cap(self):
        game = make_game(seed=10, heroes=[make_hero(n) for n in "ABCDE"])
        game.turn = 5
        game.ghost_records.append(self._record(game, 6, [
            make_minion("T6", 1, 1, tech_level=6),
            make_minion("T8", 1, 1, tech_level=8),
        ]))
        a = game.heroes[0]
        a.board = []
        game.run_ghost_combat(a)
        # 原始伤害 6+6+8=20；5 名存活玩家 → turn5 上限 10 (RULES §5.2)
        self.assertEqual(a.health, 30 - 10)


class TestRunCombatPersistence(unittest.TestCase):
    """run_combat 持久化: PERSIST 保留战斗增益 / 普通随从复原 (RULES §3.5)。"""

    @staticmethod
    def _soc_buff(src, game, ctx):
        src.add_buff(Buff(2, 2))
        src.set(GameTag.TAUNT, True)

    def test_persist_minion_keeps_combat_changes(self):
        game = make_game(seed=11)
        a, b = game.heroes
        pm = make_minion("Persist", 1, 10, tech_level=1)
        pm.set(PERSIST_TAG, True)
        pm.set_script_override("start_of_combat", self._soc_buff)
        nm = make_minion("Norm", 1, 10, tech_level=1)
        nm.set_script_override("start_of_combat", self._soc_buff)
        a.board = [pm, nm]
        b.board = []
        game.run_combat(a, b)
        # PERSIST: 战斗 buff 与关键词永久保留，HEALTH 重算为 max_health
        self.assertEqual(pm.atk, 3)
        self.assertEqual(pm.health, 12)
        self.assertEqual(len(pm.buffs), 1)
        self.assertTrue(pm.taunt)
        # 普通随从: 战斗变化消失 (RULES §3.5)
        self.assertEqual(nm.atk, 1)
        self.assertEqual(nm.health, 10)
        self.assertEqual(nm.buffs, [])
        self.assertFalse(nm.taunt)

    def test_normal_minion_death_restored(self):
        game = make_game(seed=12)
        a, b = game.heroes
        dm = make_minion("Doomed", 1, 1)
        a.board = [dm]
        killer = make_minion("Killer", 5, 5)
        b.board = [killer]
        for m in a.board + b.board:
            m.controller = a if m in a.board else b
            m.zone = Zone.PLAY
        game.run_combat(a, b)
        self.assertIn(dm, a.board)
        self.assertEqual(dm.health, 1)
        self.assertFalse(dm.dead)
        self.assertEqual(killer.health, 5)


class TestGameFinished(unittest.TestCase):
    """打到只剩 1 人 → finished (RULES §1.2)。"""

    def test_finished_when_one_survivor(self):
        game = make_game(seed=13)
        a, b = game.heroes
        b.health = 0
        game.turn = 1
        game.end_recruit_phase()
        self.assertTrue(game.finished)
        self.assertEqual(game.turn, 1)     # 终局不再推进回合
        self.assertEqual(game.heroes, [a])


if __name__ == "__main__":
    unittest.main()
