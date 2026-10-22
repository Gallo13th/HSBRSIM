"""批次 trinkets36 行为层测试（1 张注册饰品 = 1 CORRECT / 0 DEFERRED）。

覆盖（真实路径）:
  - `BG32_MagicItem_803` Macaw Portrait — 真实 `grant_trinket` →
    `on_bind` 经 `evolution_card_id` 数据链授予 `BGS_078` Monstrous Macaw
    + 写入 `hero.family_flags`（条件化追加触发，RULES §7.4.17）。
  - 持饰品 → 真实攻击路径（`CombatScheduler._execute_attack`，Rally 在
    伤害前）**同一 Rally** 依次触发: 最左**亡语**（`passes` 次）+ 最左
    **战吼**（1 次）; 资格集 = 带战吼者（跳过更靠左的非战吼随从）;
    追加项走 `TriggerBattlecry` 统一入口（计数 + 广播 + Brann 翻倍）。
  - 无饰品 → **没有追加项**（负对照，防"静默半实现"）: 战吼不触发、
    `COUNTER_BATTLECRIES` 不变; 亡语项照常（回归保护）。
  - 金色 `TB_BaconUps_135`: 亡语 2 次（`passes=2`）/ 追加战吼 **1 次**
    （饰品文本无 "twice"）。
  - 与 `BG32_MagicItem_804` Selfless Portrait 组合: 最左战吼可为"被授予
    战吼的无私英雄"——两 Portrait 在 §7.4.17 同一通道上正确复合。

结构性守卫（注册表 / 数据链 / 只挂 on_bind / 载荷消费点 / 本体不是战吼）
标 `@engine-only`。引擎原语契约见
`test_engine_primitives.py::TestConditionalBattlecryChannel`。
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from hsrl2.actions import Buff, Summon
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_payload_minions as BP
from hsrl2.scripts.batches import batch_trinkets36 as B36
from hsrl2.tags import CardType, GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

PORTRAIT = B36.MACAW_PORTRAIT
MACAW = "BGS_078"
MACAW_G = "TB_BaconUps_135"
SELFLESS = "BG_OG_221"
SELFLESS_PORTRAIT = "BG32_MagicItem_804"
FLAG = BP.FLAG_MACAW_EXTRA_BATTLECRY

# 同族 Portrait 台账（仍未注册——见 batch_trinkets24/28/29/30/31 与
# ENGINE_BACKLOG；本批只闭合 803）
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


def make_game(seed: int = 3601) -> Game:
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


class _BattlecryProbe:
    """测试探针: 战吼 = 自身 +1 Attack（**无条件**钩子）。"""

    @staticmethod
    def battlecry(source, game, ctx=None):
        return Buff(source, atk=1)


class _DeathrattleProbe:
    """测试探针: 亡语 = 自身 +1 Attack。"""

    @staticmethod
    def deathrattle(source, game, ctx):
        return Buff(source, atk=1)


def probe_battlecry(game: Game, hero: Hero, name: str,
                    atk: int = 1, health: int = 9) -> Minion:
    m = make_minion(name, atk, health)
    m.scripts = _BattlecryProbe
    return summon_plain(game, hero, m)


def probe_deathrattle(game: Game, hero: Hero, name: str,
                      atk: int = 1, health: int = 9) -> Minion:
    m = make_minion(name, atk, health)
    m.scripts = _DeathrattleProbe
    return summon_plain(game, hero, m)


class _SummonBattlecryProbe:
    """测试探针: 亡语 = 在**位置 0** 召唤一个带战吼的真实随从。

    用于锁定"先亡语后追加战吼"的结算顺序: 若顺序颠倒，追加战吼会命中
    结算前的最左战吼随从，而非亡语刚召唤出来的新随从。
    """

    SUMMONED = "BG20_100"          # 真实 tag-BATTLECRY 随从（CardDB 核实）

    @staticmethod
    def deathrattle(source, game, ctx):
        return Summon(source.controller, _SummonBattlecryProbe.SUMMONED,
                      position=0)


def probe_summon_battlecry(game: Game, hero: Hero, name: str) -> Minion:
    m = make_minion(name, 0, 9)
    m.scripts = _SummonBattlecryProbe
    return summon_plain(game, hero, m)


def probe_plain(game: Game, hero: Hero, name: str,
                atk: int = 1, health: int = 9) -> Minion:
    return summon_plain(game, hero, make_minion(name, atk, health))


def attack(game: Game, attacker: Minion, defender: Minion) -> None:
    """真实攻击路径（Rally 在伤害前，`_execute_attack`）。"""
    CombatScheduler(game, attacker.controller,
                    defender.controller)._execute_attack(attacker, defender)


def battlecry_broadcasts(game: Game, owner) -> list:
    """记录 `battlecry_trigger` 广播（统一入口证据）。"""
    seen = []
    game.events.register(Listener(
        "battlecry_trigger", owner=owner,
        callback=lambda g, **kw: seen.append(kw["minion"])))
    return seen


# ═══════════════════ 结构性守卫（注册面 / 数据链 / 接线） ═══════════════════


class TestRegistryAndLedger(unittest.TestCase):
    """注册面 / 数据链 / DEFERRED 台账 / 接线结构（@engine-only）。"""

    def test_registered_and_register_returns_id(self):
        self.assertIn(PORTRAIT, REGISTRY)
        self.assertIs(REGISTRY[PORTRAIT], B36.MacawPortraitScript)
        # register() 已在批次发现时调用（不可重复调用——registry 防重）,
        # 故以源码结构断言注册映射
        src = inspect.getsource(B36.register)
        self.assertIn("MACAW_PORTRAIT", src)
        self.assertIn("MacawPortraitScript", src)

    def test_script_only_hooks_on_bind(self):
        """饰品脚本不复刻效果本体（SOP §12）——只挂 on_bind。"""
        hooks = [n for n, v in vars(B36.MacawPortraitScript).items()
                 if callable(v) and not n.startswith("__")]
        self.assertEqual(hooks, ["on_bind"])

    def test_data_chain_and_text(self):
        db = get_db()
        d = db.get(PORTRAIT)
        self.assertIsNotNone(d)
        self.assertEqual(d.card_type, CardType.BACON_TRINKET)
        self.assertEqual(d.cost, 2)
        self.assertIn("also trigger your left-most", d.text)
        self.assertIn("Battlecry", d.text)
        g = make_game()
        a = g.heroes[0]
        rel = g.trinket_related_card(PORTRAIT)
        self.assertIsNotNone(rel, "evolution_card_id 数据链断裂")
        self.assertEqual(rel.id, MACAW)
        self.assertIsNotNone(db.get(MACAW_G), "金色定义缺失")

    def test_flag_constant_owned_by_payload(self):
        self.assertEqual(FLAG, "macaw_extra_battlecry")
        self.assertIs(B36.FLAG_MACAW_EXTRA_BATTLECRY, FLAG)
        g = make_game()
        a = g.heroes[0]
        src = inspect.getsource(BP.MonstrousMacawScript)
        self.assertIn("FLAG_MACAW_EXTRA_BATTLECRY", src)
        self.assertIn("TriggerBattlecry", src)
        # 本体**不是**条件化战吼随从（不声明 battlecry_flag）
        self.assertFalse(hasattr(BP.MonstrousMacawScript, "battlecry_flag"))
        m = g.create_minion(MACAW, controller=a)
        self.assertFalse(g.has_battlecry(m))

    def test_deferred_ledger_does_not_list_803(self):
        self.assertNotIn(PORTRAIT, DEFERRED_IDS)
        for cid in DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, f"{cid} 已注册应移出台账")


# ══════════════════════════ 行为（真实路径） ══════════════════════════


class TestMacawPortrait(unittest.TestCase):
    """`BG32_MagicItem_803` — "Your Monstrous Macaws also trigger your
    left-most Battlecry"。"""

    def test_grant_grants_macaw_and_writes_flag(self):
        g = make_game(seed=3601)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        self.assertEqual([c.card_id for c in a.hand], [MACAW])
        self.assertTrue(g.family_flag(a, MACAW, FLAG))
        self.assertTrue(g.family_flag(a, MACAW_G, FLAG))    # 金色归一
        self.assertFalse(g.family_flag(b, MACAW, FLAG))     # owner 隔离

    def test_rally_skips_non_battlecry_and_triggers_leftmost(self):
        """资格集 = 带战吼者: 更靠左的**非战吼**随从被跳过。"""
        g = make_game(seed=3602)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        enemy = probe_plain(g, b, "ENEMY", 0, 30)
        plain = probe_plain(g, a, "PLAIN")          # 最左——非战吼，应跳过
        bc_left = probe_battlecry(g, a, "BC_L")     # 最左战吼 → 命中
        dr = probe_deathrattle(g, a, "DR")          # 最左亡语 → 命中
        bc_right = probe_battlecry(g, a, "BC_R")    # 非最左战吼 → 不触发
        macaw = put(g, a, MACAW)
        attack(g, macaw, enemy)
        self.assertEqual((plain.atk, bc_left.atk), (1, 2))    # 跳过 plain
        self.assertEqual(bc_right.atk, 1)
        self.assertEqual(dr.atk, 2)                            # 同一 Rally
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 1)

    def test_no_portrait_no_extra_trigger(self):
        """负对照: 无饰品 → 追加项不存在（亡语项照常）。"""
        g = make_game(seed=3603)
        a, b = g.heroes
        enemy = probe_plain(g, b, "ENEMY", 0, 30)
        bc = probe_battlecry(g, a, "BC")
        dr = probe_deathrattle(g, a, "DR")
        macaw = put(g, a, MACAW)
        attack(g, macaw, enemy)
        self.assertEqual(bc.atk, 1)
        self.assertEqual(dr.atk, 2)                 # 亡语项不受影响
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)

    def test_deathrattle_resolves_before_extra_battlecry(self):
        """时序: 先亡语后追加战吼（对抗验证 MINOR 1——原无测试锁定，
        顺序颠倒的 mutation 曾整套存活）。本体的亡语在**位置 0** 召唤
        一个带战吼的随从 → 追加战吼应命中它，而不是结算前的最左战吼。"""
        g = make_game(seed=3611)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        enemy = probe_plain(g, b, "ENEMY", 0, 40)
        left_bc = probe_battlecry(g, a, "BC_L")          # 结算前的最左战吼
        probe_summon_battlecry(g, a, "DR_SUMMON")        # 亡语召唤者
        macaw = put(g, a, MACAW)
        spy = battlecry_broadcasts(g, macaw)
        attack(g, macaw, enemy)
        self.assertEqual(len(spy), 1)
        self.assertEqual(spy[0].card_id, _SummonBattlecryProbe.SUMMONED)
        self.assertEqual(left_bc.atk, 1)                 # 未被追加项选中

    def test_golden_deathrattle_twice_battlecry_once(self):
        """金色 `TB_BaconUps_135`: 亡语 2 次 / 追加战吼 1 次。"""
        g = make_game(seed=3604)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        enemy = probe_plain(g, b, "ENEMY", 0, 30)
        dr = probe_deathrattle(g, a, "DR")
        bc = probe_battlecry(g, a, "BC")
        macaw = put(g, a, MACAW, golden=True)
        attack(g, macaw, enemy)
        self.assertEqual(dr.atk, 1 + 2)             # passes=2
        self.assertEqual(bc.atk, 1 + 1)             # 恒 1 次
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 1)

    def test_extra_trigger_goes_through_unified_entry(self):
        """追加项走 `TriggerBattlecry` 统一入口 → 计数 + 广播。"""
        g = make_game(seed=3605)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        enemy = probe_plain(g, b, "ENEMY", 0, 30)
        bc = probe_battlecry(g, a, "BC")
        macaw = put(g, a, MACAW)
        spy = battlecry_broadcasts(g, macaw)
        attack(g, macaw, enemy)
        self.assertEqual(bc.atk, 2)
        self.assertEqual(len(spy), 1)
        self.assertIs(spy[0], bc)

    def test_no_battlecry_bearer_whiffs(self):
        """无带战吼的友方 → 追加项落空（不计数/不崩溃）。"""
        g = make_game(seed=3606)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        enemy = probe_plain(g, b, "ENEMY", 0, 30)
        plain = probe_plain(g, a, "PLAIN")
        macaw = put(g, a, MACAW)
        attack(g, macaw, enemy)
        self.assertEqual(plain.atk, 1)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)
        self.assertEqual(macaw.atk, 5)

    def test_trinket_removal_kills_extra_trigger(self):
        g = make_game(seed=3607)
        a, b = g.heroes
        e = bind(g, a, PORTRAIT)
        enemy = probe_plain(g, b, "ENEMY", 0, 30)
        bc = probe_battlecry(g, a, "BC")
        macaw = put(g, a, MACAW)
        a.trinkets.remove(e)
        attack(g, macaw, enemy)
        self.assertEqual(bc.atk, 1)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)

    def test_owner_isolation(self):
        """对手 Macaw 不追加触发（开关只写本英雄）。"""
        g = make_game(seed=3608)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        mine = probe_plain(g, a, "MINE", 0, 30)
        theirs = probe_battlecry(g, b, "THEIRS")
        macaw_b = put(g, b, MACAW)
        attack(g, macaw_b, mine)
        self.assertEqual(theirs.atk, 1)
        self.assertEqual(b.get(GameTag.COUNTER_BATTLECRIES, 0), 0)

    def test_granted_selfless_hero_can_be_the_target(self):
        """与 Selfless Portrait 组合: 最左战吼 = 被授予战吼的无私英雄。"""
        g = make_game(seed=3609)
        a, b = g.heroes
        bind(g, a, PORTRAIT)
        bind(g, a, SELFLESS_PORTRAIT)
        enemy = probe_plain(g, b, "ENEMY", 0, 30)
        selfless = put(g, a, SELFLESS)              # 最左战吼（含追加授予）
        macaw = put(g, a, MACAW)
        spy = battlecry_broadcasts(g, macaw)
        attack(g, macaw, enemy)
        # 圣盾落点随机（本体或 Macaw），故断言"触发的**主体**是自私英雄"
        # ——广播目标确定性，避免 seed 依赖的脆弱断言（对抗验证 MINOR 2）
        self.assertEqual(len(spy), 1)
        self.assertIs(spy[0], selfless)
        self.assertTrue([m for m in a.board if m.get(GameTag.DIVINE_SHIELD)],
                        "无私英雄的被授予战吼未触发")
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 1)

    def test_extra_trigger_only_on_rally(self):
        """非攻击路径（回合结束 hook）不追加触发——只有 Rally 读该开关。"""
        g = make_game(seed=3610)
        a, _b = g.heroes
        bind(g, a, PORTRAIT)
        bc = probe_battlecry(g, a, "BC")
        put(g, a, MACAW)
        g.run_script_hook(a.board[-1], "end_of_turn")
        self.assertEqual(bc.atk, 1)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 0)


if __name__ == "__main__":
    unittest.main()
