"""批次 quest_rewards8 语义测试（2026-09-18）。

覆盖 `BG24_Reward_362` Essence of Zerus + 载荷 `BGS_029` Shifter Zerus:
真实 `complete_quest` 授予 → 真实 `turn_end` 入手 → 真实 `turn_start`
手牌变形（保留附魔/位次/控制者）; **自身变形可发生**（候选 = BG 池 ∪
{BGS_029}）; **不占共享池**（池计数前后不变）; 对手隔离; 不在手牌不变形;
满手/离手负对照; 变异探针（去掉变形 / 去掉附魔转移 / 去掉手牌判定 /
去掉自身候选必须失败）。

权威: `hsrl2/scripts/batches/batch_quest_rewards8.py` 模块 docstring
（wiki URL/oldid 逐条引文）——`Battlegrounds` oldid=902245: "can transform
into any Battlegrounds minion, including Shifter Zerus. It doesn't pull
from the shared pool."
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.events import TURN_START
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.tags import Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None
REWARD = "BG24_Reward_362"
ZERUS = "BGS_029"


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 60, n_heroes: int = 2):
    # 无英雄技能脚本的测试英雄——避免被动污染 EoT/SoT 断言
    g = Game([Hero("TEST_H_" + chr(65 + i), chr(65 + i))
              for i in range(n_heroes)], get_db(), seed=seed)
    g.start_game()
    return g


def grant(game, hero, rid):
    """真实发放路径: hero._quest_reward_id + game.complete_quest。"""
    hero._quest_reward_id = rid
    game.complete_quest(hero)


def zerus_in_hand(hero):
    return [m for m in hero.hand if m.card_id == ZERUS]


def _candidate_ids():
    """Shifter Zerus 的合法变形集 = BG 池 ∪ {自身}。

    权威: `Battlegrounds` oldid=902245 "can transform into any
    Battlegrounds minion, including Shifter Zerus."
    """
    return {d.id for d in get_db().pool_minions()} | {ZERUS}


def _force_pick(game, card_id):
    """受控 RNG: 在候选集内强制选中 card_id；不在集内则 fail-loud。

    只替换 `game.rng.choice` 的选择动作，其余走**真实**变形路径
    （`_transform_in_hand` → `create_minion` → 手牌替换）。变异探针:
    去掉候选集中的 `BGS_029` 会让本助手抛 AssertionError → 测试失败。
    """
    def choose(seq, label=""):
        for d in seq:
            if getattr(d, "id", None) == card_id:
                return d
        raise AssertionError(
            f"{card_id} 不在候选集 "
            f"{[getattr(d, 'id', d) for d in seq]} 内")
    game.rng.choice = choose


class TestRegistry(unittest.TestCase):
    def test_registered(self):
        self.assertIn(REWARD, REGISTRY)
        self.assertIn(ZERUS, REGISTRY)
        self.assertIs(REGISTRY[REWARD].__name__, "EssenceOfZerusScript")
        self.assertIs(REGISTRY[ZERUS].__name__, "ShifterZerusScript")

    def test_serus_is_non_pool_payload(self):
        """BGS_029 非池（只作奖励载荷; 不占共享池）。"""
        d = get_db().get(ZERUS)
        self.assertFalse(d.is_pool_minion)
        self.assertEqual(d.text,
                         "[x]Each turn this is in your\nhand, transform it"
                         " into a\nrandom minion. It keeps\nenchantments.")

    def test_reward_data_link(self):
        """奖励 → 载荷数据链（dbfId 57742 = BGS_029）。"""
        d = get_db().get(REWARD)
        self.assertEqual(d.raw.get("reward_dbf_id") or 57742, 57742)
        self.assertEqual(get_db().get(ZERUS).dbf_id, 57742)


class TestGrantZerus(unittest.TestCase):
    def test_eot_grants_one_zerus(self):
        g = make_game()
        a, b = g.heroes
        grant(g, a, REWARD)
        g.events.fire(g, "turn_end", turn=1)
        self.assertEqual(len(zerus_in_hand(a)), 1)
        m = zerus_in_hand(a)[0]
        self.assertIs(m.controller, a)
        self.assertEqual(m.zone, Zone.HAND)
        self.assertFalse(m.is_golden)
        self.assertEqual(len(a.quest_rewards), 1)

    def test_grants_each_turn(self):
        g = make_game()
        a = g.heroes[0]
        grant(g, a, REWARD)
        for t in (1, 2):
            g.events.fire(g, "turn_end", turn=t)
        self.assertEqual(len(zerus_in_hand(a)), 2)

    def test_opponent_has_no_zerus(self):
        """负对照: 只有持有者获得。"""
        g = make_game()
        a, b = g.heroes
        grant(g, a, REWARD)
        g.events.fire(g, "turn_end", turn=1)
        self.assertEqual(zerus_in_hand(b), [])

    def test_no_reward_no_zerus(self):
        """正对照: 无奖励 → EoT 不追加 Zerus。"""
        g = make_game()
        a = g.heroes[0]
        g.events.fire(g, "turn_end", turn=1)
        self.assertEqual(zerus_in_hand(a), [])

    def test_full_hand_queues_instead_of_destroying(self):
        g = make_game()
        a = g.heroes[0]
        grant(g, a, REWARD)
        while not a.hand_full():
            d = get_db().pool_minions()[0]
            a.add_to_hand(g.create_minion(d.id, controller=a))
        g.events.fire(g, "turn_end", turn=1)
        self.assertEqual(zerus_in_hand(a), [])          # 满手不入
        self.assertTrue(any(e.card_id == ZERUS
                            for _h, e in g.pending_hand_queue))


class TestHandTransform(unittest.TestCase):
    def _grant_zerus(self, g, hero):
        grant(g, hero, REWARD)
        g.events.fire(g, "turn_end", turn=1)
        return zerus_in_hand(hero)[0]

    def test_turn_start_transforms_in_hand(self):
        g = make_game(seed=61)
        a = g.heroes[0]
        z = self._grant_zerus(g, a)
        self.assertEqual(g.events._listeners.get(TURN_START) is not None,
                         True)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(len(a.hand), 1)
        new = a.hand[0]
        self.assertIsNot(new, z)
        self.assertIs(new.controller, a)
        self.assertEqual(new.zone, Zone.HAND)
        # 候选 = BG 池 ∪ {Zerus 自身}（"any Battlegrounds minion,
        # including Shifter Zerus"）
        self.assertIn(new.card_id, _candidate_ids())
        self.assertFalse(new.is_golden)

    def test_keeps_enchantments(self):
        """权威: "It keeps enchantments."（Patch 27.6.0.187190）。"""
        g = make_game(seed=62)
        a = g.heroes[0]
        z = self._grant_zerus(g, a)
        z.add_buff(Enchant(atk=5, health=5))
        g.events.fire(g, "turn_start", turn=2, hero=a)
        new = a.hand[0]
        self.assertIsNot(new, z)
        self.assertEqual([(b.atk, b.health) for b in new.buffs], [(5, 5)])

    def test_keeps_hand_position_and_cardinality(self):
        g = make_game(seed=63)
        a = g.heroes[0]
        filler = get_db().pool_minions()[0]
        a.add_to_hand(g.create_minion(filler.id, controller=a))
        z = self._grant_zerus(g, a)
        self.assertIs(a.hand[1], z)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(len(a.hand), 2)
        self.assertEqual(a.hand[0].card_id, filler.id)
        self.assertIn(a.hand[1].card_id, _candidate_ids())

    def test_opponent_turn_does_not_transform(self):
        """负对照: 只在**持有者**的回合开始变形。"""
        g = make_game(seed=64)
        a, b = g.heroes
        self._grant_zerus(g, a)
        g.events.fire(g, "turn_start", turn=2, hero=b)
        self.assertEqual(len(zerus_in_hand(a)), 1)

    def test_not_in_hand_does_not_transform(self):
        """负对照: 离手 → 不变形（原实体卡面不变、不抛错）。"""
        g = make_game(seed=65)
        a = g.heroes[0]
        z = self._grant_zerus(g, a)
        a.hand.remove(z)                    # 手工移出手牌（模拟离手）
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(z.card_id, ZERUS)

    def test_on_board_is_never_touched_by_the_hand_effect(self):
        """负对照: Zerus 被**打出到棋盘**后，手牌变形绝不动它。

        没有"在手判定"时，`hero.hand.index(_src)` 会抛 ValueError 或
        （更坏）错改棋盘实体——本测试锁住"不在手牌 = 完全不触碰"。
        """
        g = make_game(seed=70)
        a = g.heroes[0]
        z = self._grant_zerus(g, a)
        a.hand.remove(z)
        g.summon(a, z)                       # 真实入场到棋盘
        self.assertIn(z, a.board)
        board_before = [m.card_id for m in a.board]
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(z.card_id, ZERUS)
        self.assertIn(z, a.board)
        self.assertEqual([m.card_id for m in a.board], board_before)

    def test_golden_zerus_transforms_into_golden(self):
        """金色 Zerus → 随机**金色**随从（wiki 金色卡文本）。"""
        g = make_game(seed=66)
        a = g.heroes[0]
        grant(g, a, REWARD)
        g.events.fire(g, "turn_end", turn=1)
        a.hand.clear()
        gz = g.create_minion(ZERUS, controller=a, golden=True)
        a.add_to_hand(gz)
        self.assertTrue(gz.is_golden)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        new = a.hand[0]
        self.assertNotEqual(new.card_id, ZERUS)
        self.assertTrue(new.is_golden)

    def test_self_transform_is_possible(self):
        """权威: "including Shifter Zerus" —— 自身变形可发生。

        受控 RNG 强制选中 `BGS_029`，走真实 `turn_start` → 真实
        `_transform_in_hand`。变异探针: 从候选中去掉 `BGS_029`（旧实现）
        会让 `_force_pick` 抛 AssertionError → 本测试失败；旧断言
        `assertNotEqual(new.card_id, ZERUS)` 编码的是错误语义（禁止自身
        变形），已删除。
        """
        g = make_game(seed=71)
        a = g.heroes[0]
        z = self._grant_zerus(g, a)
        z.add_buff(Enchant(atk=3, health=4))
        _force_pick(g, ZERUS)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(len(a.hand), 1)
        new = a.hand[0]
        self.assertEqual(new.card_id, ZERUS)      # 自身变形 → 仍是 Zerus
        self.assertIsNot(new, z)                  # 但是新实体（卡面替换）
        self.assertEqual(new.zone, Zone.HAND)
        self.assertIs(new.controller, a)
        # 自身变形同样保留附魔（"It keeps enchantments."）
        self.assertEqual([(b.atk, b.health) for b in new.buffs], [(3, 4)])

    def test_transform_does_not_consume_pool(self):
        """负对照: "It doesn't pull from the shared pool." —— 池计数不变。"""
        g = make_game(seed=72)
        a = g.heroes[0]
        self._grant_zerus(g, a)
        mp = g.minion_pool
        before_total = mp.total_remaining()
        before_avail = dict(mp._available)
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertEqual(mp.total_remaining(), before_total)
        self.assertEqual(dict(mp._available), before_avail)

    def test_transform_is_deterministic_per_seed(self):
        """同 seed 确定（相同结果），且结果恒在候选集内。"""
        outs = []
        for _ in range(2):
            g = make_game(seed=68)
            a = g.heroes[0]
            self._grant_zerus(g, a)
            g.events.fire(g, "turn_start", turn=2, hero=a)
            outs.append(a.hand[0].card_id)
        self.assertEqual(outs[0], outs[1])
        self.assertIn(outs[0], _candidate_ids())


if __name__ == "__main__":
    unittest.main()
