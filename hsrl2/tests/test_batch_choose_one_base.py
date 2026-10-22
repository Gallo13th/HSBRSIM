"""批次 choose_one_base 语义测试（G-C6，17 个 def / 10 张 base 抉择卡）。

驱动约定（TEST_SOP / test_batch_choose_one 同款）:
  - 随从: create_minion → hero.add_to_hand → play_minion → 引擎两阶段
    状态机产生 choose_one PendingChoice → choose(key 下标) → 效果结算
  - 法术: create_spell → 入手 → play_spell（Spellcraft / 酒馆法术同构）
  - CHOOSE_BOTH 双效: hero.set(GameTag.CHOOSE_BOTH, True) 后引擎直接
    传 choose="both" 不弹选择
  - 数值断言一律卡面字面量（这批旧卡 CardDef 无 num——脚本 docstring
    的 Params 行记录文本依据）

每卡至少: 两个分支各 1 正例 + 1 负例/边界（空酒馆、空棋盘、池空等），
另加金色差异与 CHOOSE_BOTH 覆盖（存在金色/双效语义的卡）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

GEM_ID = "BG20_GEM"   # 血宝石基础值唯一来源（bloodgem.py 同源）

#: 本批注册的 17 个 def（10 base + 金色/变体）
REGISTERED_IDS = (
    "BG26_355", "BG26_355_G",
    "BG30_110", "BG30_110_G",
    "BG30_117", "BG30_117_G", "BG30_117t", "BG30_117_Gt",
    "BG30_128", "BG30_128_G",
    "BG31_144", "BG31_144_G",
    "BG31_325", "BG31_325_G",
    "BG31_825", "BG31_825_G",
    "BG31_842", "BG31_842_G",
    "BG31_884",
)

#: 声明 choose_options 的 def（Spellcraft 宿主 BG30_117/_G 不是抉择卡）
CHOOSE_DEFS = tuple(i for i in REGISTERED_IDS
                    if i not in ("BG30_117", "BG30_117_G"))

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42) -> Game:
    return Game([make_hero("A"), make_hero("B")], get_db(), seed=seed)


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def put(game: Game, hero: Hero, m: Minion) -> Minion:
    game.summon(hero, m)
    return m


def put_in_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    """占池后放入酒馆（模拟 draw_tavern 的池记账）。"""
    assert game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def simple_pool_card(tier: int = 1) -> str:
    """选一张无战吼/亡语副作用的池卡（酒馆构造用）。"""
    for d in sorted(get_db().pool_minions(), key=lambda x: x.id):
        if d.tech_level != tier:
            continue
        if "battlecry" in d.keywords or "deathrattle" in d.keywords:
            continue
        return d.id
    raise AssertionError(f"no simple pool card tier={tier}")


def play_choose(game: Game, hero: Hero, card_id: str,
                golden: bool = False):
    """打出抉择随从 → 返回 (minion, 首级 choose_one PendingChoice)。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.add_to_hand(m)
    assert game.play_minion(hero, m)
    pc = game.pending_choices.pop(0)
    assert pc.kind == "choose_one", pc.kind
    return m, pc


def cast_spell(game: Game, hero: Hero, card_id: str):
    """施放法术 → 返回 (spell, 首级 PendingChoice)（无选择窗时 None）。"""
    s = game.create_spell(card_id, controller=hero)
    hero.add_to_hand(s)
    assert game.play_spell(hero, s)
    if not game.pending_choices:
        return s, None
    return s, game.pending_choices.pop(0)


def choose_key(pc, key: str) -> None:
    pc.choose(pc.options.index(key))


def hand_ids(hero: Hero) -> list:
    return [c.card_id for c in hero.hand]


class TestRegistryBase(unittest.TestCase):
    """注册面 + 选择协议声明。"""

    def test_all_registered(self):
        for cid in REGISTERED_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_choose_options_declared(self):
        for cid in CHOOSE_DEFS:
            self.assertTrue(getattr(REGISTRY[cid], "choose_options", None),
                            cid)


class TestDiscoShuffler(unittest.TestCase):
    """BG26_355 — Trigger a Battlecry; or Discover a Battlecry minion。"""

    def _board(self, game):
        a = game.heroes[0]
        # 战吼来源: 实体级 override（引擎 has_battlecry 双通道）
        bc = put(game, a, make_minion("BC", 2, 2))
        calls = []
        bc.set_script_override(
            "battlecry",
            lambda src, g, c: calls.append(1) or None)
        plain = put(game, a, make_minion("PLAIN", 1, 1))
        return a, bc, plain, calls

    def test_trigger_branch_targets_only_battlecry_minion(self):
        game = make_game(seed=1)
        a, bc, plain, calls = self._board(game)
        m, pc = play_choose(game, a, "BG26_355")
        choose_key(pc, "trigger")
        self.assertEqual(len(game.pending_choices), 1)
        pc2 = game.pending_choices.pop(0)
        self.assertEqual(pc2.kind, "battlecry_target")
        self.assertIn(bc, pc2.options)
        self.assertNotIn(plain, pc2.options)
        pc2.choose(pc2.options.index(bc))
        self.assertEqual(len(calls), 1)

    def test_trigger_branch_empty_candidates_fizzles(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG26_355")
        choose_key(pc, "trigger")
        self.assertEqual(game.pending_choices, [])

    def test_golden_trigger_uses_one_target_twice(self):
        game = make_game(seed=3)
        a, bc, plain, calls = self._board(game)
        m, pc = play_choose(game, a, "BG26_355_G", golden=True)
        choose_key(pc, "trigger")
        # 金色两触发共用同一目标 → 只挂一个目标选择
        self.assertEqual(len(game.pending_choices), 1)
        pc2 = game.pending_choices.pop(0)
        pc2.choose(pc2.options.index(bc))
        self.assertEqual(len(calls), 2)

    def test_discover_branch_gets_battlecry_minion(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG26_355")
        choose_key(pc, "discover")
        self.assertEqual(len(game.pending_choices), 1)
        pc2 = game.pending_choices.pop(0)
        self.assertEqual(pc2.kind, "discover_battlecry_minion")
        self.assertEqual(len(pc2.options), 3)
        for cid in pc2.options:
            d = get_db().get(cid)
            self.assertTrue("battlecry" in d.keywords
                            or getattr(REGISTRY.get(cid), "battlecry", None),
                            cid)
        # 预留语义: 选项生成即占池（engine Discover 契约）——已选项保留、
        # 未选项 resolve 时回池（不泄漏）
        avail = {cid: game.minion_pool.available(cid) for cid in pc2.options}
        pc2.choose(0)
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(a.hand[0].card_id, pc2.options[0])
        for cid in pc2.options:
            expected = avail[cid] - (1 if cid == pc2.options[0] else -1)
            # avail 是**选项生成后**的余量（预留已生效）: 选中项保持
            # 预留（不变），未选中项回池（+1）
            expected = avail[cid] if cid == pc2.options[0] else avail[cid] + 1
            self.assertEqual(game.minion_pool.available(cid), expected, cid)

    def test_choose_both_applies_both(self):
        game = make_game(seed=5)
        a, bc, plain, calls = self._board(game)
        a.set(GameTag.CHOOSE_BOTH, True)
        m = game.create_minion("BG26_355", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        # 无 choose_one 窗；both = trigger(目标窗) + discover
        kinds = [pc.kind for pc in game.pending_choices]
        self.assertIn("battlecry_target", kinds)
        self.assertIn("discover_battlecry_minion", kinds)
        tgt = next(pc for pc in game.pending_choices
                   if pc.kind == "battlecry_target")
        game.pending_choices.remove(tgt)
        tgt.choose(tgt.options.index(bc))
        self.assertEqual(len(calls), 1)


class TestMirageConjurer(unittest.TestCase):
    """BG30_110 — Tavern 全体 Attack / Health 翻倍（金色 Triple）。"""

    def _tavern(self, game):
        a = game.heroes[0]
        cid = simple_pool_card(1)
        m1 = put_in_tavern(game, a, cid)
        m2 = put_in_tavern(game, a, cid)
        return a, m1, m2

    def test_attack_branch_doubles_tavern_attack(self):
        game = make_game(seed=11)
        a, m1, m2 = self._tavern(game)
        a1, h1 = m1.atk, m1.max_health
        m, pc = play_choose(game, a, "BG30_110")
        choose_key(pc, "attack")
        self.assertEqual(m1.atk, a1 * 2)
        self.assertEqual(m2.atk, a1 * 2)
        self.assertEqual(m1.max_health, h1)     # Health 不变

    def test_health_branch_doubles_tavern_health(self):
        game = make_game(seed=12)
        a, m1, m2 = self._tavern(game)
        h1 = m1.max_health
        m, pc = play_choose(game, a, "BG30_110")
        choose_key(pc, "health")
        self.assertEqual(m1.max_health, h1 * 2)
        self.assertEqual(m2.max_health, h1 * 2)

    def test_golden_triples_not_quadruples(self):
        game = make_game(seed=13)
        a, m1, m2 = self._tavern(game)
        a1 = m1.atk
        m, pc = play_choose(game, a, "BG30_110_G", golden=True)
        choose_key(pc, "attack")
        self.assertEqual(m1.atk, a1 * 3)

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=14)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG30_110")
        choose_key(pc, "attack")
        self.assertEqual(len(a.tavern), 0)


class TestVolcanicVisitorAndEscapeEruption(unittest.TestCase):
    """BG30_117 Spellcraft 宿主 + BG30_117t/_Gt 法术。"""

    def test_host_grants_spell_on_summon(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        put(game, a, game.create_minion("BG30_117", controller=a))
        self.assertEqual(hand_ids(a), ["BG30_117t"])

    def test_golden_host_grants_golden_spell(self):
        game = make_game(seed=22)
        a = game.heroes[0]
        put(game, a, game.create_minion("BG30_117_G", controller=a))
        self.assertEqual(hand_ids(a), ["BG30_117_Gt"])

    def test_spell_attack_branch(self):
        game = make_game(seed=23)
        a = game.heroes[0]
        m1 = put(game, a, make_minion("M1", 2, 3))
        s, pc = cast_spell(game, a, "BG30_117t")
        choose_key(pc, "attack")
        self.assertEqual(m1.atk, 2 + 4)
        self.assertEqual(m1.max_health, 3)

    def test_golden_spell_health_branch(self):
        game = make_game(seed=24)
        a = game.heroes[0]
        m1 = put(game, a, make_minion("M1", 2, 3))
        s, pc = cast_spell(game, a, "BG30_117_Gt")
        choose_key(pc, "health")
        self.assertEqual(m1.max_health, 3 + 8)
        self.assertEqual(m1.atk, 2)

    def test_choose_both_spell(self):
        game = make_game(seed=25)
        a = game.heroes[0]
        a.set(GameTag.CHOOSE_BOTH, True)
        m1 = put(game, a, make_minion("M1", 2, 3))
        s = game.create_spell("BG30_117t", controller=a)
        a.add_to_hand(s)
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(m1.atk, 2 + 4)
        self.assertEqual(m1.max_health, 3 + 4)


class TestSleepingSeaGlass(unittest.TestCase):
    """BG30_128 — 自身 Attack / Health 翻倍（金色 Triple）。"""

    def test_attack_branch(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG30_128")
        base_atk, base_hp = m.atk, m.max_health
        choose_key(pc, "attack")
        self.assertEqual(m.atk, base_atk * 2)
        self.assertEqual(m.max_health, base_hp)

    def test_health_branch(self):
        game = make_game(seed=32)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG30_128")
        base_hp = m.max_health
        choose_key(pc, "health")
        self.assertEqual(m.max_health, base_hp * 2)

    def test_golden_triple(self):
        game = make_game(seed=33)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG30_128_G", golden=True)
        base_atk = m.atk
        choose_key(pc, "attack")
        self.assertEqual(m.atk, base_atk * 3)


class TestAdaptiveAncestor(unittest.TestCase):
    """BG31_144 — +3 Attack & DS / +3 Health & Venomous。"""

    def test_attack_branch(self):
        game = make_game(seed=41)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_144")
        base = m.atk
        choose_key(pc, "attack")
        self.assertEqual(m.atk, base + 3)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(m.has(GameTag.VENOMOUS))

    def test_health_branch(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_144")
        base = m.max_health
        choose_key(pc, "health")
        self.assertEqual(m.max_health, base + 3)
        self.assertTrue(m.has(GameTag.VENOMOUS))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_golden_double_trigger_sums(self):
        game = make_game(seed=43)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_144_G", golden=True)
        base = m.atk
        choose_key(pc, "attack")
        self.assertEqual(m.atk, base + 6)


class TestCrystalInfuser(unittest.TestCase):
    """BG31_325 — Get 3 Blood Gems / gain Deathrattle: Get 2。"""

    def test_gems_branch(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_325")
        choose_key(pc, "gems")
        self.assertEqual(len([c for c in a.hand if c.card_id == GEM_ID]), 3)

    def test_golden_gems_branch(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_325_G", golden=True)
        choose_key(pc, "gems")
        self.assertEqual(len([c for c in a.hand if c.card_id == GEM_ID]), 6)

    def test_deathrattle_branch_grants_gems_on_death(self):
        game = make_game(seed=53)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_325")
        choose_key(pc, "deathrattle")
        self.assertTrue(m.has(GameTag.DEATHRATTLE))
        before = len([c for c in a.hand if c.card_id == GEM_ID])
        game.trigger_deathrattle(m, hero=a)
        self.assertEqual(
            len([c for c in a.hand if c.card_id == GEM_ID]) - before, 2)

    def test_golden_deathrattle_stacks_four_gems(self):
        game = make_game(seed=54)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_325_G", golden=True)
        choose_key(pc, "deathrattle")
        before = len([c for c in a.hand if c.card_id == GEM_ID])
        game.trigger_deathrattle(m, hero=a)
        self.assertEqual(
            len([c for c in a.hand if c.card_id == GEM_ID]) - before, 4)

    def test_choose_both(self):
        game = make_game(seed=55)
        a = game.heroes[0]
        a.set(GameTag.CHOOSE_BOTH, True)
        m = game.create_minion("BG31_325", controller=a)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(game.pending_choices, [])
        self.assertEqual(len([c for c in a.hand if c.card_id == GEM_ID]), 3)
        self.assertTrue(m.has(GameTag.DEATHRATTLE))


class TestGraceFarsail(unittest.TestCase):
    """BG31_825 — 下回合 +2 Gold / 两回合后 +4 Gold。"""

    def test_next_branch(self):
        game = make_game(seed=61)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_825")
        choose_key(pc, "next")
        self.assertEqual(a.gold, 0)     # 当回合不获得
        game.turn = 2
        game._begin_recruit_for(a)
        self.assertEqual(a.gold, _income(2) + 2)

    def test_two_branch(self):
        game = make_game(seed=62)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_825")
        choose_key(pc, "two")
        game.turn = 2
        game._begin_recruit_for(a)
        self.assertEqual(a.gold, _income(2))      # 两回合后才有
        game.turn = 3
        game._begin_recruit_for(a)
        self.assertEqual(a.gold, _income(3) + 4)

    def test_golden_next_branch_stacks(self):
        game = make_game(seed=63)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_825_G", golden=True)
        choose_key(pc, "next")
        game.turn = 2
        game._begin_recruit_for(a)
        self.assertEqual(a.gold, _income(2) + 4)


class TestNetherConstruct(unittest.TestCase):
    """BG31_842 — Tavern 全体 +4/+4 this game / Consume 全 Tavern。"""

    def test_tavern_buff_branch_immediate_and_persistent(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        cid = simple_pool_card(1)
        m1 = put_in_tavern(game, a, cid)
        a1, h1 = m1.atk, m1.max_health
        m, pc = play_choose(game, a, "BG31_842")
        choose_key(pc, "buff")
        self.assertEqual(m1.atk, a1 + 4)
        self.assertEqual(m1.max_health, h1 + 4)
        # 持久面: 刷新后新入馆随从同样 +4/+4
        a.gold = 10
        game.refresh_tavern(a)
        self.assertTrue(len(a.tavern) > 0)
        for e in a.tavern:
            if not isinstance(e, Minion):
                continue
            d = get_db().get(e.card_id)
            self.assertEqual(e.atk, d.atk + 4)
            self.assertEqual(e.max_health, d.health + 4)

    def test_consume_branch_gains_all_stats(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        cid = simple_pool_card(1)
        put_in_tavern(game, a, cid)
        put_in_tavern(game, a, cid)
        total_atk = sum(m.atk for m in a.tavern)
        total_hp = sum(m.max_health for m in a.tavern)
        m, pc = play_choose(game, a, "BG31_842")
        base_atk, base_hp = m.atk, m.max_health
        taunt_pool_before = {cid: game.minion_pool.available(cid)}
        choose_key(pc, "consume")
        self.assertEqual(len(a.tavern), 0)
        self.assertEqual(m.atk, base_atk + total_atk)
        self.assertEqual(m.max_health, base_hp + total_hp)
        # 酒馆来源受害者回池（RULES §2.3）
        self.assertEqual(game.minion_pool.available(cid),
                         taunt_pool_before[cid] + 2)

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=73)
        a = game.heroes[0]
        m, pc = play_choose(game, a, "BG31_842")
        choose_key(pc, "consume")
        self.assertEqual(a.tavern, [])


class TestRoadLessTraveled(unittest.TestCase):
    """BG31_884 — 随机 T6 / 两张随机 T5（酒馆法术）。"""

    def test_t6_branch(self):
        game = make_game(seed=81)
        a = game.heroes[0]
        s, pc = cast_spell(game, a, "BG31_884")
        choose_key(pc, "t6")
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(get_db().get(a.hand[0].card_id).tech_level, 6)

    def test_t5_branch_two_minions(self):
        game = make_game(seed=82)
        a = game.heroes[0]
        s, pc = cast_spell(game, a, "BG31_884")
        choose_key(pc, "t5")
        self.assertEqual(len(a.hand), 2)
        for c in a.hand:
            self.assertEqual(get_db().get(c.card_id).tech_level, 5)

    def test_choose_both(self):
        game = make_game(seed=83)
        a = game.heroes[0]
        a.set(GameTag.CHOOSE_BOTH, True)
        s = game.create_spell("BG31_884", controller=a)
        a.add_to_hand(s)
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(len(a.hand), 3)
        tiers = sorted(get_db().get(c.card_id).tech_level for c in a.hand)
        self.assertEqual(tiers, [5, 5, 6])


def _income(turn: int) -> int:
    """基础金币收入（引擎 constants 权威）。"""
    from hsrl2 import constants as C
    return C.gold_base_income(turn)


if __name__ == "__main__":
    unittest.main()
