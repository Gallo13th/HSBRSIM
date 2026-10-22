"""批次 quest_rewards5 语义测试（作业单 2026-09-02）——第二英雄技能槽。

覆盖 1 个注册任务奖励（真实引擎路径: `Game(...)` + `start_game()` +
`hero._quest_reward_id` + `game.complete_quest(hero)`）:
  - BG33_Reward_017 Cosmic Reward（绑定后 Discover 一个第二英雄技能）

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都配**正对照**;
技能 id 经 `batch_anomalies4.power_id_by_name` 从 CardDB 解析; 种子固定
以钉住 `rng.sample` 的 Discover 选项; owner 隔离用 2 英雄（只有被绑定的
英雄获得选择）。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_anomalies4 as B4
from hsrl2.tags import CardType

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

HERO_A = "BG20_HERO_103"
REWARD_ID = "BG33_Reward_017"

# 固定种子（探测已确认该 seed 下奖励 Discover 选项含目标技能）
SEED_HOLLIDAE = 19       # 选项含 BG28_HERO_801p（active: 随机酒馆法术）
SEED_GROWING = 50       # 37.0 英雄技能池扩容后重新探测: 选项含
                        # BG32_HERO_002p（passive: Growing Collection）
                        # （2026-09-13 修正: 原写的 19 实测不含该技能 →
                        #   测试恒 skip、on_bind 接线零执行覆盖）

HOLLIDAE_POWER = "BG28_HERO_801p"
GROWING_POWER = "BG32_HERO_002p"


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def game_with(seed: int = 40, names=("A", "B")) -> Game:
    heroes = [Hero(HERO_A, n) for n in names]
    g = Game(heroes, get_db(), seed=seed)
    g.start_game()
    return g


def bind_reward(game: Game, hero) -> None:
    """真实任务完成路径（complete_quest → reward on_bind 接线）。"""
    hero._quest_reward_id = REWARD_ID
    game.complete_quest(hero)


def take_choice(game: Game, kind: str, owner=None):
    """按 kind（可选 owner）取出一条 PendingChoice 并出队（SOP §13 契约）。"""
    if owner is None:
        choice = next(c for c in game.pending_choices if c.kind == kind)
    else:
        choice = next(c for c in game.pending_choices
                      if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(choice)
    return choice


def power_id(name: str) -> str:
    pid = B4.power_id_by_name(SimpleNamespace(db=get_db()), name)
    assert pid is not None, name
    return pid


def hero_bound_power_ids() -> set:
    out = set()
    for d in get_db()._by_id.values():
        if d.card_type != CardType.HERO:
            continue
        pid = getattr(d, "hero_power_id", None)
        if pid and get_db().get(pid) is not None:
            out.add(pid)
    return out


class TestRegistry(unittest.TestCase):
    def test_all_ids_registered(self):
        self.assertIn(REWARD_ID, REGISTRY)

    def test_class_names(self):
        self.assertEqual(REGISTRY[REWARD_ID].__name__, "CosmicRewardScript")

    def test_reward_card_definition(self):
        d = get_db().get(REWARD_ID)
        self.assertIsNotNone(d)
        self.assertEqual(d.card_type, CardType.BACON_QUEST_REWARD)
        self.assertIn("second", d.text.lower())


# ══════════════ BG33_Reward_017 Cosmic Reward ══════════════


class TestCosmicReward(unittest.TestCase):
    """<b>Discover</b> a second Hero Power. (BG33_Reward_017)"""

    def test_bind_creates_discover_choice_owner_isolated(self):
        g = game_with(seed=SEED_HOLLIDAE)
        a, b = g.heroes
        bind_reward(g, a)
        self.assertEqual([e.card_id for e in a.quest_rewards], [REWARD_ID])
        choices = [c for c in g.pending_choices
                   if c.kind == "discover_hero_power"]
        self.assertEqual([c.owner for c in choices], [a])
        bound = hero_bound_power_ids()
        c = choices[0]
        self.assertEqual(len(c.options), 3)
        self.assertEqual(len(set(c.options)), 3)
        self.assertTrue(set(c.options) <= bound)
        self.assertNotIn(g.hero_power_def(a).id, c.options)
        # owner 隔离: B 无奖励 → 无选择、无第二槽
        self.assertIsNone(b._second_power_id)
        self.assertEqual(len(g.hero_power_ids(b)), 1)

    def test_pick_assigns_slot_and_second_power_is_usable(self):
        # seed 19: 选项含 BG28_HERO_801p（Hollidae: 随机酒馆法术入手）
        g = game_with(seed=SEED_HOLLIDAE)
        a = g.heroes[0]
        bind_reward(g, a)
        c = take_choice(g, "discover_hero_power", owner=a)
        for pid in c.options:                       # D2: 全部已注册
            self.assertIsNotNone(REGISTRY.get(pid), pid)
        self.assertIn(HOLLIDAE_POWER, c.options)
        c.choose(c.options.index(HOLLIDAE_POWER))
        self.assertEqual(a._second_power_id, HOLLIDAE_POWER)
        self.assertEqual(g.hero_power_ids(a),
                         [g.hero_power_def(a).id, HOLLIDAE_POWER])
        # 第二槽**真实可用**（`use_hero_power(power_id=...)`）——旧版只调
        # `use_hero_power(a)`（主技能），"第二技能可用"从未被验证
        # （2026-09-13 对抗验证: 取消接线后测试仍全绿）。
        a.gold = 50
        hand_before = len(a.hand)
        self.assertTrue(g.use_hero_power(a, power_id=HOLLIDAE_POWER))
        self.assertGreater(len(a.hand), hand_before)   # Hollidae: 法术入手
        # 主技能本回合次数未被第二槽消耗（正对照）
        self.assertTrue(g.use_hero_power(a))

    def test_discovered_passive_power_on_bind_wired(self):
        """SEED_GROWING: 选项含 Growing Collection（passive）——选中后其
        on_bind 的 T8 greater offer 必须真实发生（显式接线证据）。
        （2026-09-13: 原 seed 19 不含该技能导致恒 skip——本测试在
         `set_second_hero_power` 不接线时**必须**失败。）"""
        g = game_with(seed=SEED_GROWING)
        a = g.heroes[0]
        bind_reward(g, a)
        c = take_choice(g, "discover_hero_power", owner=a)
        self.assertIn(GROWING_POWER, c.options)
        c.choose(c.options.index(GROWING_POWER))
        self.assertEqual(a._second_power_id, GROWING_POWER)
        g.turn = 8
        for h in g.heroes:
            if h.is_alive:
                g._begin_recruit_for(h)
        offers = [ch for ch in g.pending_choices
                  if ch.kind == "trinket_offer" and ch.owner is a]
        self.assertEqual(len(offers), 1)
        self.assertEqual({o.spell_school for o in offers[0].options
                          if o is not None}, {12})
        # 隔离: B 未获得该技能 → 无 T8 offer
        self.assertEqual([ch for ch in g.pending_choices
                          if ch.kind == "trinket_offer"
                          and ch.owner is g.heroes[1]], [])

    def test_invalid_pick_whiffs_and_valid_pick_control(self):
        g = game_with(seed=SEED_HOLLIDAE)
        a = g.heroes[0]
        bind_reward(g, a)
        c = take_choice(g, "discover_hero_power", owner=a)
        c.resolve_callback("NO_SUCH_POWER")
        self.assertIsNone(a._second_power_id)               # 落空
        self.assertEqual(len(g.hero_power_ids(a)), 1)
        # 正对照: 合法选项确实写入第二槽
        c.choose(c.options.index(HOLLIDAE_POWER))
        self.assertEqual(a._second_power_id, HOLLIDAE_POWER)

    def test_occupied_second_slot_whiffs_with_positive_control(self):
        # 已有第二槽（如异变先授予）→ 本奖励落空、不覆盖
        g = game_with(seed=SEED_HOLLIDAE)
        a = g.heroes[0]
        a._second_power_id = HOLLIDAE_POWER
        bind_reward(g, a)
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "discover_hero_power"], [])
        self.assertEqual(a._second_power_id, HOLLIDAE_POWER)
        # 正对照: 同 seed、槽空闲 → 确有选择
        g2 = game_with(seed=SEED_HOLLIDAE)
        a2 = g2.heroes[0]
        bind_reward(g2, a2)
        self.assertEqual(len([c for c in g2.pending_choices
                              if c.kind == "discover_hero_power"]), 1)

    def test_no_second_slot_before_binding(self):
        g = game_with(seed=SEED_HOLLIDAE)
        a = g.heroes[0]
        self.assertIsNone(a._second_power_id)
        self.assertEqual([c for c in g.pending_choices
                          if c.kind == "discover_hero_power"], [])
        # 正对照: 绑定后同一英雄确有一次选择
        bind_reward(g, a)
        self.assertEqual(len([c for c in g.pending_choices
                              if c.kind == "discover_hero_power"]), 1)


if __name__ == "__main__":
    unittest.main()
