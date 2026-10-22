"""批次 anomalies5 语义测试（饰品授予/替换族; 作业单 2026-09-11）。

覆盖 1 张注册异变 + 1 张第二技能槽技能（真实引擎路径:
`Game(..., anomaly=id)` + `start_game()`，以及
`game.use_hero_power(hero, power_id=...)` 真使用 + PendingChoice):

  - BG35_Anomaly_002  Anomalous Cube —— 第二槽 = 'Mystery Cube'
    （`BG35_Anomaly_002t`；数据链解析，不硬编码 id）
  - BG35_Anomaly_002t Mystery Cube（Hero Power）—— Turn 5 解锁后，
    2 选 1 张未获得 Lesser 饰品免费获得，并把第二槽替换掉

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都配**正对照**;
owner 隔离用 2 英雄; 技能 id 经 `batch_anomalies5.mystery_cube_power_id`
/ 数据链解析（不硬编码业务 id）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_anomalies5 as B5
from hsrl2.tags import CardType
import hsrl2.constants as C

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

ANOMALY_CUBE = "BG35_Anomaly_002"
POWER_CUBE = "BG35_Anomaly_002t"

# 测试英雄（主技能 TB 系列 active: BG20_HERO_103 Bloodbound）
HERO_A = "BG20_HERO_103"

# 无副作用的 lesser 饰品（on_bind 不动金币; A 会发 2 张 Bounty → 可探测）
HARMLESS_LESSER_A = "BG35_MagicItem_890"   # Sunken Anchor（on_bind 发 Bounty）
HARMLESS_LESSER_B = "BG36_MagicItem_300"   # Frigid Blossom（refresh 监听）

REGISTERED_IDS = (ANOMALY_CUBE, POWER_CUBE)
# DEFERRED（台账见 batch_anomalies5 模块 docstring）——不得注册
# BG35_Anomaly_007/_008 及其技能 _007t/_008t 已于 batch_anomalies6
# 实现（副本条款 + 第二技能槽饰品表示）——本台账不再列为 DEFERRED
DEFERRED_IDS: tuple = ()

_db = None


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
    """驱动真实回合开始（每存活英雄一次）。"""
    if clear_choices:
        game.pending_choices.clear()
    game.turn = turn
    for h in game.heroes:
        if h.is_alive:
            game._begin_recruit_for(h)


def take_choice(game: Game, kind: str, owner=None):
    """取出一条 PendingChoice 并出队（SOP §13 契约: choose 只结算不出队）。"""
    if owner is None:
        ch = next(c for c in game.pending_choices if c.kind == kind)
    else:
        ch = next(c for c in game.pending_choices
                  if c.kind == kind and c.owner is owner)
    game.pending_choices.remove(ch)
    return ch


def replace_choices(game: Game, owner=None):
    return [c for c in game.pending_choices
            if c.kind == "trinket_replace"
            and (owner is None or c.owner is owner)]


def lesser_ids() -> list:
    return [d.id for d in get_db().trinket_offer_pool()
            if d.spell_school == 11]


# ══════════════ 结构性（注册表 / 数据一致性） ══════════════

class TestRegistry(unittest.TestCase):
    """注册面 + 数据链/文本一致性（结构性，与钩子无关）。"""

    def test_all_ids_registered(self):
        for cid in REGISTERED_IDS:
            self.assertIn(cid, REGISTRY, cid)
            self.assertIsNotNone(get_db().get(cid), cid)

    def test_class_names(self):
        expected = {
            ANOMALY_CUBE: "AnomalousCubeAnomaly",
            POWER_CUBE: "MysteryCubePowerScript",
        }
        for cid, name in expected.items():
            self.assertIs(REGISTRY[cid], getattr(B5, name), cid)

    def test_deferred_ids_not_registered(self):
        for cid in DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_power_id_resolved_by_name(self):
        g = game_with(None, seed=1)
        self.assertEqual(B5.mystery_cube_power_id(g), POWER_CUBE)

    def test_power_card_def_and_uses_per_game(self):
        d = get_db().get(POWER_CUBE)
        self.assertEqual(d.card_type, CardType.HERO_POWER)
        self.assertEqual(d.cost, 0)
        self.assertEqual(B5.MysteryCubePowerScript.uses_per_game, 1)
        # "Unlocks on Turn 5." 文本字面量 + 异变 num(0)=4（"4 turns left"）
        self.assertEqual(B5.MYSTERY_CUBE_UNLOCK_TURN, 5)
        self.assertEqual(get_db().get(ANOMALY_CUBE).num(0), 4)

    def test_deferred_ledger_records_dependencies(self):
        doc = B5.__doc__ or ""
        for token in ("duplicate", "_second_power_id", "Souvenir Stand"):
            self.assertIn(token, doc)


# ══════════════ BG35_Anomaly_002 Anomalous Cube ══════════════

class TestAnomalousCube(unittest.TestCase):

    def test_second_power_granted_from_data_chain(self):
        d = get_db().get(ANOMALY_CUBE)
        power = get_db().by_dbf(d.evolution_card_id)
        self.assertIsNotNone(power)
        self.assertEqual(power.id, POWER_CUBE)
        g = game_with(ANOMALY_CUBE, seed=40)
        for h in g.heroes:
            self.assertEqual(h._second_power_id, power.id)
            self.assertIn(power.id, g.hero_power_ids(h))
            self.assertIsNotNone(g.hero_power_def_for(h, power.id))
        # 对照局: 无异常 → 无第二槽（负面对照）
        g2 = game_with(None, seed=40)
        for h in g2.heroes:
            self.assertIsNone(h._second_power_id)

    def test_locked_before_turn5_unlocks_on_turn5(self):
        g = game_with(ANOMALY_CUBE, seed=41)
        a = g.heroes[0]
        pid = a._second_power_id
        for turn in (1, 2, 3, 4):
            start_turn(g, turn, clear_choices=True)
            self.assertFalse(g.use_hero_power(a, power_id=pid), turn)
            self.assertEqual(replace_choices(g, a), [])
        start_turn(g, 5, clear_choices=True)         # 正对照: Turn 5 解锁
        self.assertTrue(g.use_hero_power(a, power_id=pid))
        choices = replace_choices(g, a)
        self.assertEqual(len(choices), 1)
        self.assertEqual(len(choices[0].options), 2)   # "choose from 2"
        ids = [o.id for o in choices[0].options]
        self.assertEqual(len(set(ids)), 2)             # 互异
        for o in choices[0].options:
            self.assertEqual(o.spell_school, 11)       # Lesser
            self.assertNotIn(o.id, g._trinkets_granted)  # "new"

    def test_pick_grants_free_and_clears_slot(self):
        g = game_with(ANOMALY_CUBE, seed=42)
        a = g.heroes[0]
        pid = a._second_power_id
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(g.use_hero_power(a, power_id=pid))
        ch = take_choice(g, "trinket_replace", a)
        ch.options = [get_db().get(HARMLESS_LESSER_A),
                      get_db().get(HARMLESS_LESSER_B)]
        gold_before = a.gold
        ch.choose(0)
        self.assertIn(HARMLESS_LESSER_A, [t.card_id for t in a.trinkets])
        self.assertIn(HARMLESS_LESSER_A, g._trinkets_granted)
        self.assertEqual([t.card_id for t in a.trinkets], [HARMLESS_LESSER_A])
        bounties = [c for c in a.hand if c.card_id in C.BOUNTY_SPELL_IDS]
        self.assertEqual(len(bounties), 2)             # 被授予实体的 on_bind 生效
        self.assertEqual(a.gold, gold_before)          # "for free"
        self.assertIsNone(a._second_power_id)          # "replace this"
        self.assertNotIn(pid, g.hero_power_ids(a))

    def test_once_per_game(self):
        g = game_with(ANOMALY_CUBE, seed=43)
        a = g.heroes[0]
        pid = a._second_power_id
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(g.use_hero_power(a, power_id=pid))
        self.assertEqual(len(replace_choices(g, a)), 1)   # 正对照
        self.assertFalse(g.use_hero_power(a, power_id=pid))  # 同回合第二次
        start_turn(g, 6, clear_choices=True)
        self.assertFalse(g.use_hero_power(a, power_id=pid))  # 跨回合仍一次
        self.assertEqual(replace_choices(g, a), [])

    def test_owner_isolation(self):
        g = game_with(ANOMALY_CUBE, seed=44)
        a, b = g.heroes
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(g.use_hero_power(a, power_id=a._second_power_id))
        self.assertEqual(len(replace_choices(g, a)), 1)   # 正对照
        self.assertEqual(replace_choices(g, b), [])       # 负面
        self.assertTrue(g.use_hero_power(b, power_id=b._second_power_id))
        self.assertEqual(len(replace_choices(g, b)), 1)   # B 独立可用
        self.assertEqual(len(replace_choices(g, a)), 1)

    def test_available_false_when_candidate_pool_exhausted(self):
        g = game_with(ANOMALY_CUBE, seed=45)
        a = g.heroes[0]
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(g.use_hero_power(a, power_id=a._second_power_id))
        self.assertEqual(len(replace_choices(g, a)), 1)   # 正对照
        # 负面: 预占全部 Lesser → available False（不白扣每局次数）
        g2 = game_with(ANOMALY_CUBE, seed=46)
        a2 = g2.heroes[0]
        g2._trinkets_granted.update(lesser_ids())
        a2.trinkets_granted.update(lesser_ids())
        start_turn(g2, 5, clear_choices=True)
        self.assertFalse(
            g2.use_hero_power(a2, power_id=a2._second_power_id))
        self.assertEqual(replace_choices(g2, a2), [])

    def test_stale_option_does_not_grant_twice(self):
        g = game_with(ANOMALY_CUBE, seed=47)
        a = g.heroes[0]
        pid = a._second_power_id
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(g.use_hero_power(a, power_id=pid))
        ch = take_choice(g, "trinket_replace", a)
        ch.options = [get_db().get(HARMLESS_LESSER_A),
                      get_db().get(HARMLESS_LESSER_B)]
        self.assertIsNotNone(
            g.grant_trinket(a, HARMLESS_LESSER_A, source="test"))
        ch.choose(0)                                   # 选项已被并发授予
        self.assertEqual(
            [t.card_id for t in a.trinkets if t.card_id == HARMLESS_LESSER_A],
            [HARMLESS_LESSER_A])
        self.assertEqual(a._second_power_id, pid)      # 槽保留，未落空消耗
        ch.choose(1)                                   # 正对照: 另一选项生效
        self.assertIn(HARMLESS_LESSER_B, [t.card_id for t in a.trinkets])
        self.assertIsNone(a._second_power_id)


class TestMysteryCubePowerRefund(unittest.TestCase):
    """落空回滚: 选项在挂起期被并发授予 → 回滚本局次数，技能仍可用
    （2026-09-02 对抗审查 MINOR: 旧实现留下"可用性 True 但 use 恒
    False"的永久死技能）。"""

    def test_concurrent_grant_refunds_use(self):
        g = game_with(ANOMALY_CUBE, seed=48)
        a = g.heroes[0]
        pid = a._second_power_id
        start_turn(g, 5, clear_choices=True)
        self.assertTrue(g.use_hero_power(a, power_id=pid))
        ch = take_choice(g, "trinket_replace", a)
        pick = ch.options[0]
        a.trinkets_granted.add(pick.id)        # 并发授予（模拟对手/其它效果）
        ch.choose(0)                           # 落空 → 应回滚次数
        self.assertNotIn(pick.id, [t.card_id for t in a.trinkets])
        self.assertEqual(a._power_uses_this_game.get(pid, 0), 0)
        self.assertEqual(a._second_power_id, pid)
        # 正对照: 回滚后可再次使用（放回槽位未被替换）
        self.assertTrue(g.use_hero_power(a, power_id=pid))
        self.assertEqual(len(replace_choices(g, a)), 1)


if __name__ == "__main__":
    unittest.main()
