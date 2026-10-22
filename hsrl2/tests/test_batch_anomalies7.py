"""批次 anomalies7 语义测试（Emergency Landing / Eject!）。

覆盖 1 张注册异变 + 1 张第二技能槽技能（真实引擎路径:
`Game(..., anomaly=id)` + `start_game()` + 真实 `use_hero_power`），
外加新引擎原语 `MinionPool.purge` 的单元级守卫:

  - `BG31_Anomaly_117`  Emergency Landing —— 第二槽 = Eject!
  - `BG31_Anomaly_117t` Eject!（Hero Power，主动，2 次/回合）——
    点名酒馆随从 → `MinionPool.purge` 永久清空该卡池内副本

约定（SOP §16 空转测试判定法）: 每个负面/落空断言都配**正对照**;
owner/目标隔离用 2 英雄; 目标卡 id 一律从真实酒馆/池读取（不硬编码
业务 id）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_anomalies7 as B7
from hsrl2.tags import CardType, GameTag
from hsrl2.minion import Minion

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

ANOMALY = B7.EMERGENCY_LANDING
EJECT = B7.EJECT

HERO_A = "BG20_HERO_103"        # 真实英雄（主技能已注册）

# 仍未注册的异变（同批范围外的对照台账——只验证"未注册"这一事实）
DEFERRED_SAMPLE = (
    "BG27_Anomaly_302",     # Bring Home the Bacon — Piggy Bank 步长无权威
    "BG27_Anomaly_503",     # The Yogg-iseum — Wheel 子系统
    "BG27_Anomaly_580",     # Audience's Choice — 共享候选协议
    "BG27_Anomaly_810",     # Bring in the Buddies — Buddy 子系统
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(anomaly: str | None = None, seed: int = 71) -> Game:
    heroes = [Hero(HERO_A, "A"), Hero(HERO_A, "B")]
    g = Game(heroes, get_db(), seed=seed, anomaly=anomaly)
    g.start_game()
    return g


def tavern_minions(hero) -> list:
    return [m for m in hero.tavern
            if not m.dead and isinstance(m, Minion)]


def use_eject(game: Game, hero, target) -> bool:
    return game.use_hero_power(hero, target=target, power_id=EJECT)


class TestEmergencyLandingWiring(unittest.TestCase):
    """异变 → 第二技能槽接线（真实 start_game 路径）。"""

    def test_second_slot_wired_for_every_hero(self):
        g = make_game(ANOMALY)
        for h in g.heroes:
            ids = g.hero_power_ids(h)
            self.assertIn(EJECT, ids, h.name)
            self.assertIn("BG20_HERO_103p", ids)         # 主技能仍在
            self.assertEqual(len(ids), 2)

    def test_control_without_anomaly_has_no_eject(self):
        g = make_game(None)
        for h in g.heroes:
            self.assertNotIn(EJECT, g.hero_power_ids(h))

    def test_eject_is_active_not_passive(self):
        """主动技能（非 passive）——passive 会被 `use_hero_power` 拒绝。"""
        script = REGISTRY.get(EJECT)
        self.assertFalse(getattr(script, "passive", False))
        self.assertEqual(script.uses_per_turn, 2)


class TestEjectEffect(unittest.TestCase):
    """Eject! 真实使用路径。"""

    def test_target_candidates_are_tavern_minions_only(self):
        g = make_game(ANOMALY)
        a, b = g.heroes
        cands = REGISTRY.get(EJECT).target_candidates(a, g)
        self.assertTrue(cands)                            # 正对照: 有候选
        self.assertTrue(all(m in a.tavern for m in cands))
        self.assertTrue(all(isinstance(m, Minion) for m in cands))
        # 酒馆法术（BACON_SPELL 实体）不是候选
        spells = [m for m in a.tavern if not isinstance(m, Minion)]
        for s in spells:
            self.assertNotIn(s, cands, s.card_id)
        # 对手酒馆随从不是候选（owner 隔离）
        self.assertFalse([m for m in b.tavern if m in cands])

    def test_use_purges_card_permanently(self):
        g = make_game(ANOMALY)
        a, _b = g.heroes
        target = tavern_minions(a)[0]
        cid = target.card_id
        before = g.minion_pool.available(cid)
        self.assertGreater(before, 0)                     # 正对照
        self.assertTrue(use_eject(g, a, target))
        self.assertTrue(g.minion_pool.is_purged(cid))
        self.assertEqual(g.minion_pool.available(cid), 0)
        self.assertFalse(g.minion_pool.acquire(cid))
        self.assertFalse(g.minion_pool.ensure_available(cid))
        # 池候选不再列出该卡；反复抽取永不出现
        self.assertNotIn(cid, g.minion_pool.candidates(max_tier=7))
        drawn = []
        for _ in range(30):
            drawn.extend(g.minion_pool.draw_tavern(tier=7, count=10))
        self.assertNotIn(cid, drawn, "已永久移除的卡不得再被抽出")

    def test_named_copy_stays_in_tavern(self):
        """卡面字面量裁定: "from your **pool**" 不含已抽出的展示副本。"""
        g = make_game(ANOMALY)
        a, _b = g.heroes
        target = tavern_minions(a)[0]
        self.assertTrue(use_eject(g, a, target))
        self.assertIn(target, a.tavern)
        self.assertFalse(target.dead)

    def test_sell_and_refresh_do_not_restore_pool(self):
        g = make_game(ANOMALY)
        a, _b = g.heroes
        target = tavern_minions(a)[0]
        cid = target.card_id
        self.assertTrue(use_eject(g, a, target))
        a.gold = 20
        bought = None
        for m in list(a.tavern):
            if m is target and g.buy_from_tavern(a, m):
                bought = m
                break
        self.assertIsNotNone(bought, "被点名的副本应可购买（仍在酒馆）")
        g.sell_minion(a, bought)                          # 出售 → release 被拒
        self.assertEqual(g.minion_pool.available(cid), 0)
        # 刷新把未冻结旧内容回池——已 purge 的卡同样不得回池
        for _ in range(3):
            g.refresh_tavern(a, free=True)
        self.assertTrue(g.minion_pool.is_purged(cid))
        self.assertEqual(g.minion_pool.available(cid), 0)
        self.assertNotIn(cid, [m.card_id for m in tavern_minions(a)])

    def test_other_cards_unaffected(self):
        """负对照: 只清点名卡，其余卡池量不变。"""
        g = make_game(ANOMALY)
        a, _b = g.heroes
        ms = tavern_minions(a)
        target = ms[0]
        other = ms[1]
        other_before = g.minion_pool.available(other.card_id)
        self.assertTrue(use_eject(g, a, target))
        self.assertFalse(g.minion_pool.is_purged(other.card_id))
        self.assertEqual(g.minion_pool.available(other.card_id),
                         other_before)

    def test_non_tavern_target_rejected(self):
        """目标域外（棋盘随从 / 酒馆法术）→ 不可用，且无副作用。"""
        g = make_game(ANOMALY)
        a, _b = g.heroes
        board_m = g.create_minion(tavern_minions(a)[0].card_id, controller=a)
        self.assertTrue(g.summon(a, board_m))
        self.assertFalse(use_eject(g, a, board_m))
        self.assertFalse(g.minion_pool.is_purged(board_m.card_id))
        spells = [m for m in a.tavern if not isinstance(m, Minion)]
        if spells:
            self.assertFalse(use_eject(g, a, spells[0]))
        self.assertEqual(a._power_uses_this_turn.get(EJECT, 0), 0)

    def test_twice_per_turn_then_rejected_and_resets(self):
        g = make_game(ANOMALY)
        a, _b = g.heroes
        ms = tavern_minions(a)
        self.assertGreaterEqual(len(ms), 2)
        gold = a.gold
        self.assertTrue(use_eject(g, a, ms[0]))
        self.assertEqual(a.gold, gold)                    # cost=0
        self.assertTrue(use_eject(g, a, ms[1]))
        self.assertFalse(use_eject(g, a, ms[0]))          # 第 3 次拒绝
        # 新回合（引擎语义: `clear(HERO_POWER_USED_THIS_TURN)` 归零）
        g.turn += 1
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        third = tavern_minions(a)[0]
        self.assertTrue(use_eject(g, a, third))

    def test_golden_tavern_display_normalizes_to_base_pool_card(self):
        """金色展示位 → `triple_base_id` 归一到池内基础定义后清池。"""
        g = make_game(ANOMALY)
        a, _b = g.heroes
        base = tavern_minions(a)[0]
        bd = get_db().get(base.card_id)
        gd = get_db().golden_version(bd)
        if gd is None:
            self.skipTest("该卡无金色定义")
        golden_entity = g.create_minion(bd.id, controller=a, golden=True)
        self.assertEqual(golden_entity.card_id, gd.id)    # 正对照
        self.assertNotEqual(gd.id, bd.id)
        a.tavern = [m for m in a.tavern if m is not base] + [golden_entity]
        self.assertTrue(use_eject(g, a, golden_entity))
        self.assertTrue(g.minion_pool.is_purged(bd.id))
        self.assertEqual(g.minion_pool.available(bd.id), 0)
        self.assertFalse(g.minion_pool.is_purged(gd.id))  # 池内只有基础定义

    def test_owner_isolation(self):
        """A 使用不影响 B 的池视图/技能次数。"""
        g = make_game(ANOMALY)
        a, b = g.heroes
        target = tavern_minions(a)[0]
        self.assertTrue(use_eject(g, a, target))
        self.assertEqual(b._power_uses_this_turn.get(EJECT, 0), 0)
        b_target = tavern_minions(b)[0]
        self.assertTrue(use_eject(g, b, b_target))


class TestRegistryAndLedger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 数据 / 台账。"""

    def test_registered_ids(self):
        self.assertIs(REGISTRY.get(ANOMALY), B7.EmergencyLandingAnomaly)
        self.assertIs(REGISTRY.get(EJECT), B7.EjectPower)

    def test_both_ids_exist_in_data(self):
        db = get_db()
        self.assertEqual(db.get(ANOMALY).card_type, CardType.BACON_ANOMALY)
        self.assertEqual(db.get(EJECT).card_type, CardType.HERO_POWER)

    def test_deferred_anomalies_still_unregistered(self):
        for cid in DEFERRED_SAMPLE:
            self.assertIsNotNone(get_db().get(cid), cid)
            self.assertIsNone(REGISTRY.get(cid), cid)


if __name__ == "__main__":
    unittest.main()
