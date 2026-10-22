"""批次 trinkets35 行为层测试（1 张注册饰品 = 1 CORRECT / 0 DEFERRED）。

覆盖（真实路径）:
  - `BG32_MagicItem_804` Selfless Portrait — 真实 `grant_trinket` →
    `on_bind` 经 `evolution_card_id` 数据链授予 `BG_OG_221` Selfless Hero
    + 写入 `hero.family_flags`（条件化战吼，RULES §7.4.17）。
  - 持饰品 → 该家族**具有战吼**（`Game.has_battlecry` 真）: 真实
    `play_minion` 打出即结算亡语效果（随机 k 只友方获圣盾）;
    `TriggerBattlecry`（Snicker Snacks `BG24_Reward_107` EoT）同样可触发;
    War Drum `bc_first` 配额被消费; `COUNTER_BATTLECRIES` +1。
  - 无饰品 → **没有战吼**（负对照，防"静默半实现"）: 打出自私英雄不给圣盾、
    `has_battlecry` 假、不消费 War Drum 配额、不计数、`TriggerBattlecry`
    落空（本轮同时收紧 `TriggerBattlecry` 的无战吼门禁）。
  - 金色载荷按基础卡 id 归一同吃开关（"Give 2 random friendly minions"
    由载荷 `_targets=2` 体现——本脚本不复刻效果，SOP §12）。

结构性守卫（注册表 / 数据链 / DEFERRED 台账 / 只挂 on_bind / 载荷消费点）
标 `@engine-only`。引擎原语契约（条件化战吼门禁）见
`test_engine_primitives.py::TestConditionalBattlecryChannel`。
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
from hsrl2.scripts.batches import batch_payload_minions as BP
from hsrl2.scripts.batches import batch_trinkets35 as B35
from hsrl2.scripts.batches import batch_trinkets8 as B8
from hsrl2.tags import CardType, GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

PORTRAIT = B35.SELFLESS_PORTRAIT
SELFLESS = "BG_OG_221"
SELFLESS_G = "TB_BaconUps_014"
FLAG = BP.FLAG_SELFLESS_BATTLECRY
SNICKER = "BG24_Reward_107"

# 同族 Portrait 台账（仍未注册——见 batch_trinkets24/28/29/30/31 与
# ENGINE_BACKLOG；804 由本批闭合、803 由 batch_trinkets36 闭合）
# 868 Rewinder / 987 Balladist / 283 Czarina Portrait 已由 batch_trinkets31
# 注册（2026-09-19——owner 权威序: wiki 页无 Notes → 卡面天然语言
# "also give X" 增量 = 同句既有量）→ 移出本台账，DEFERRED 清零。
DEFERRED_IDS = ()

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 3501) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid, source="test")
    assert e is not None, f"{tid} 未授予"
    return e


def make_minion(name: str, atk: int, health: int,
                race: Race = Race.NONE) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)


def summon_plain(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def put(game: Game, hero: Hero, card_id: str, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def play_from_hand(game: Game, hero: Hero, card_id: str,
                   golden: bool = False) -> Minion:
    """真实入手（`grant_card_copy_to_hand`，池记账）+ 真实 `play_minion`。

    金色副本的 `card_id` 是金色独立定义（`TB_BaconUps_014`），故取
    末位手牌而非按 id 过滤。
    """
    d = get_db().get(card_id)
    assert d is not None, card_id
    assert game.grant_card_copy_to_hand(hero, d, golden=golden)
    card = hero.hand[-1]
    assert game.play_minion(hero, card)
    return hero.board[-1]


def hand_of(hero: Hero, card_id: str) -> list:
    return [c for c in hero.hand if c.card_id == card_id]


def bind_reward(game: Game, hero: Hero, rid: str):
    """真实任务奖励接线路径（`complete_quest` 同构: 建实体 + on_bind）。"""
    e = game.create_entity(rid, controller=hero)
    hero.quest_rewards.append(e)
    game.run_script_hook(e, "on_bind", ctx={"hero": hero})
    return e


def war_drum_ready(hero: Hero) -> None:
    """模拟 War Drum `BG32_MagicItem_416` 的每回合配额已生效。"""
    hero.extra_triggers["bc_first"] = 1
    hero.extra_triggers["bc_first_times"] = 1
    hero.extra_trigger_used["bc_first"] = 0


class TestSelflessPortrait(unittest.TestCase):
    """BG32_MagicItem_804 — 家族"条件化战吼"。"""

    def test_grants_selfless_hero_and_flag(self):
        g = make_game(seed=3501)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        granted = hand_of(a, SELFLESS)
        self.assertEqual(len(granted), 1)          # 真实数据链授予
        self.assertFalse(granted[0].is_golden)
        self.assertTrue(g.family_flag(a, SELFLESS, FLAG))
        self.assertTrue(g.family_flag(a, SELFLESS_G, FLAG))   # 金色归一
        self.assertFalse(g.family_flag(b, SELFLESS, FLAG))    # owner 隔离
        self.assertEqual(FLAG, "selfless_hero_extra_battlecry")

    def test_battlecry_on_play_shields_self(self):
        """持饰品: 真实 `play_minion` 打出本体 → 结算战吼（唯一友方=本体）。"""
        g = make_game(seed=3502)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        m = play_from_hand(g, a, SELFLESS)
        self.assertTrue(m.has(GameTag.BATTLECRY)
                        or g.has_battlecry(m))
        self.assertTrue(g.has_battlecry(m))
        self.assertTrue(m.get(GameTag.DIVINE_SHIELD))
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 1)

    def test_no_battlecry_without_portrait(self):
        """负对照: 无饰品时打出自私英雄**不给圣盾、不计数**。"""
        g = make_game(seed=3503)
        a, _b = g.heroes
        m = play_from_hand(g, a, SELFLESS)
        self.assertFalse(g.has_battlecry(m))
        self.assertFalse(g.granted_battlecry(m))
        self.assertFalse(m.get(GameTag.DIVINE_SHIELD))
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)

    def test_golden_battlecry_uses_base_value_twice(self):
        """金色（基础卡 id 归一动开关）: 引擎金色模型 = **每次触发用基础值**
        （`battlecry_targets`=1）× 引擎触发 2 次 → 总额 2 只; 断言两次触发
        与每次基础值（`_targets`=2 只服务单次触发的亡语路径）。"""
        g = make_game(seed=3504)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        m = play_from_hand(g, a, SELFLESS, golden=True)
        self.assertTrue(m.is_golden)
        self.assertTrue(g.has_battlecry(m))
        self.assertEqual(BP.SelflessHeroScript.battlecry_targets, 1)
        self.assertEqual(BP.SelflessHeroGoldenScript._targets, 2)
        # 棋盘仅本体 → 两次触发都只能选中本体: 圣盾恒成立、计数 = 2
        self.assertTrue(m.get(GameTag.DIVINE_SHIELD))
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 2)

    def test_golden_battlecry_behaviour_pins_base_per_trigger(self):
        """**行为级**金色口径（对抗验证 NIT 4）: 金色 = 2 次触发 × 每次
        基础值 1 只随机友方。3 友方 + 本体（4 候选）下，基础口径两次
        1-选-1 最多命中 2 只; 若误把每次触发的目标数改成 2（= 金色文本值
        二次计入），同 seed 会命中 3 只。seed 3602 实测 base=2 / 误实现=3，
        故 `== 2` 是真正的行为判别（非仅结构断言）。"""
        g = make_game(seed=3602)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        for i in range(3):
            summon_plain(g, a, make_minion(f"GF{i}", 1, 1))
        m = play_from_hand(g, a, SELFLESS, golden=True)
        shielded = [x for x in a.board if x.get(GameTag.DIVINE_SHIELD)]
        self.assertTrue(m.is_golden)
        self.assertEqual(len(shielded), 2)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 2)

    def test_golden_without_portrait_gives_nothing(self):
        g = make_game(seed=3505)
        a, _b = g.heroes
        play_from_hand(g, a, SELFLESS, golden=True)
        self.assertFalse(any(m.get(GameTag.DIVINE_SHIELD) for m in a.board))

    def test_gate_follows_trinket_lifecycle(self):
        """同一实体: 开关写入 → 有战吼; 饰品移除 → 立刻失去战吼。"""
        g = make_game(seed=3506)
        a, _b = g.heroes
        m = put(g, a, SELFLESS)
        self.assertFalse(g.has_battlecry(m))
        ent = bind(g, a, PORTRAIT)
        self.assertTrue(g.has_battlecry(m))
        a.trinkets.remove(ent)
        self.assertFalse(g.has_battlecry(m))
        self.assertFalse(g.granted_battlecry(m))

    def test_war_drum_quota_only_consumed_with_portrait(self):
        """核心防泄漏: 无饰品不得消费 War Drum `bc_first` 配额。"""
        g = make_game(seed=3507)
        a, _b = g.heroes
        war_drum_ready(a)
        play_from_hand(g, a, SELFLESS)
        self.assertEqual(a.extra_trigger_used.get("bc_first", 0), 0)
        # 持饰品 → 消费 1 次（它现在真的有战吼）
        g2 = make_game(seed=3507)
        a2, _b2 = g2.heroes
        bind(g2, a2, PORTRAIT)
        war_drum_ready(a2)
        play_from_hand(g2, a2, SELFLESS)
        self.assertEqual(a2.extra_trigger_used.get("bc_first", 0), 1)

    def test_snicker_snacks_triggers_granted_battlecry(self):
        """权威路径: Snicker Snacks（32.4 补丁说明条目）可触发该战吼。"""
        g = make_game(seed=3508)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        m = put(g, a, SELFLESS)          # 棋盘上只有它 → EoT 必被选中
        bind_reward(g, a, SNICKER)
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertTrue(m.get(GameTag.DIVINE_SHIELD))
        self.assertGreaterEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 1)

    def test_snicker_snacks_noop_without_portrait(self):
        g = make_game(seed=3509)
        a, _b = g.heroes
        m = put(g, a, SELFLESS)
        bind_reward(g, a, SNICKER)
        g.events.fire(g, "turn_end", turn=g.turn)
        self.assertFalse(m.get(GameTag.DIVINE_SHIELD))
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)

    def test_trigger_battlecry_action_gate(self):
        """`TriggerBattlecry`（重触发原子）按开关与"无战吼"门禁生效。"""
        from hsrl2.actions.trigger import TriggerBattlecry
        g = make_game(seed=3510)
        a, _b = g.heroes
        m = put(g, a, SELFLESS)
        g.run_actions(TriggerBattlecry(m))
        self.assertFalse(m.get(GameTag.DIVINE_SHIELD))     # 无战吼 → 落空
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)
        bind(g, a, PORTRAIT)
        g.run_actions(TriggerBattlecry(m))
        self.assertTrue(m.get(GameTag.DIVINE_SHIELD))
        self.assertGreaterEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 1)

    def test_trigger_battlecry_ignores_vanilla_minion(self):
        """无战吼的普通随从被重触发 → 不计数、不广播（门禁收紧）。"""
        from hsrl2.actions.trigger import TriggerBattlecry
        g = make_game(seed=3511)
        a, _b = g.heroes
        f = summon_plain(g, a, make_minion("VANILLA", 2, 2))
        fired = []
        g.events.register(Listener(
            event="battlecry_trigger", owner=a,
            callback=lambda gg, **kw: fired.append(kw.get("minion"))))
        g.run_actions(TriggerBattlecry(f))
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)
        self.assertEqual(fired, [])

    def test_battlecry_trigger_broadcast_with_portrait(self):
        g = make_game(seed=3512)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        m = put(g, a, SELFLESS)
        fired = []
        g.events.register(Listener(
            event="battlecry_trigger", owner=a,
            callback=lambda gg, **kw: fired.append(kw.get("minion"))))
        from hsrl2.actions.trigger import TriggerBattlecry
        g.run_actions(TriggerBattlecry(m))
        self.assertEqual(fired, [m])

    def test_opponent_family_unaffected(self):
        """owner 隔离: B 的无私英雄无战吼，A 的饰品不惠及 B。"""
        g = make_game(seed=3513)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        m_b = put(g, b, SELFLESS)
        self.assertFalse(g.has_battlecry(m_b))
        from hsrl2.actions.trigger import TriggerBattlecry
        g.run_actions(TriggerBattlecry(m_b))
        self.assertFalse(m_b.get(GameTag.DIVINE_SHIELD))

    def test_deathrattle_path_unchanged(self):
        """开关不得改写亡语本体: 无饰品时死亡仍给圣盾。"""
        from hsrl2.actions import Hit
        g = make_game(seed=3514)
        a, _b = g.heroes
        m = put(g, a, SELFLESS)
        friend = summon_plain(g, a, make_minion("FR", 1, 1))
        g.run_actions(Hit(m, m.health))
        self.assertTrue(friend.get(GameTag.DIVINE_SHIELD))


class TestRegistryAndLedger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链 / 接线。"""

    def test_registered_id(self):
        self.assertIs(REGISTRY.get(PORTRAIT), B35.SelflessPortraitScript)
        self.assertEqual(REGISTRY.get(PORTRAIT).__module__,
                         "hsrl2.scripts.batches.batch_trinkets35")

    def test_deferred_not_registered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid), tid)

    def test_deferred_ids_are_trinkets(self):
        for tid in DEFERRED_IDS:
            d = get_db().get(tid)
            self.assertIsNotNone(d, tid)
            self.assertEqual(d.card_type, CardType.BACON_TRINKET, tid)

    def test_related_card_data_chain(self):
        db = get_db()
        evo = db.get(PORTRAIT).evolution_card_id
        self.assertIsNotNone(evo)
        self.assertEqual(db.by_dbf(evo).id, SELFLESS)
        self.assertEqual(db.by_dbf(evo).card_type, CardType.MINION)

    def test_flag_constant_owned_by_payload(self):
        self.assertEqual(B35.FLAG_SELFLESS_BATTLECRY,
                         BP.FLAG_SELFLESS_BATTLECRY)
        self.assertEqual(
            BP.SelflessHeroScript.battlecry_flag, FLAG)
        self.assertEqual(
            BP.SelflessHeroGoldenScript.battlecry_flag, FLAG)

    def test_script_declares_only_on_bind(self):
        hooks = ("battlecry", "deathrattle", "start_of_combat", "avenge",
                 "rally", "start_of_turn", "end_of_turn", "on_sell",
                 "on_summon", "on_play", "activate", "atk", "health",
                 "hero_power")
        cls = B35.SelflessPortraitScript
        self.assertTrue(callable(getattr(cls, "on_bind", None)))
        self.assertEqual([h for h in hooks if h in vars(cls)], [])

    def test_payload_consumes_flag(self):
        """载荷消费点存在且自守（非装饰性接线）: `battlecry` 读
        `granted_battlecry`，效果与亡语共用同一函数。"""
        import inspect
        src = inspect.getsource(BP.SelflessHeroScript.battlecry)
        self.assertIn("granted_battlecry", src)
        self.assertIn("_give_divine_shield", src)
        self.assertIn("_give_divine_shield",
                      inspect.getsource(BP.SelflessHeroScript.deathrattle))

    def test_engine_gates_use_unified_helper(self):
        """引擎/脚本侧"是否有战吼"门禁统一走 `has_battlecry`
        （否则条件化战吼会泄漏到无饰品场景）。"""
        import inspect
        from hsrl2.actions.trigger import TriggerBattlecry
        self.assertIn("has_battlecry",
                      inspect.getsource(TriggerBattlecry.do))
        self.assertIn("has_battlecry",
                      inspect.getsource(B8._has_battlecry_hook))


if __name__ == "__main__":
    unittest.main()
