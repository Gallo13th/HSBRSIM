"""批次 trinkets39 行为层测试（2 张注册饰品 = 2 CORRECT / 0 DEFERRED）。

覆盖（真实路径）:
  - `BG30_MagicItem_803` Kaboom Bot Portrait — 真实 `grant_trinket` →
    `on_bind` 经 `evolution_card_id` 数据链授予 `BG_BOT_606` Kaboom Bot
    + 写入 `hero.family_flags`; 真实 `run_combat`（战斗内 DAMAGE 探针）
    下 Kaboom 亡语伤害实例 = `num(0)` + **10**（无饰品对照 4）; 金色
    "twice" 的两个实例**各自** +10（[14, 14] —— owner 裁定的逐实例
    读法）; 对手持有饰品不影响我方; 非家族随从的亡语不被改写; 饰品被
    移除后开关失效。
  - `BG32_MagicItem_820` Impulsive Portrait — 真实 `grant_trinket` 交付
    **6/6** 的 `BG21_006`（文本字面量覆盖; 无饰品本体 5/5）; 真实
    `_process_single_death` 下亡语目标集合由"随机一名友方"改为**两个
    相邻随从各得全额 max_health**（无饰品对照：恰一名随机友方得到）;
    金色两个实例各打相邻集合 → 相邻各得 2 × max_health; 无相邻随从
    落空; 对手/非家族均不受影响; 饰品被移除后开关失效。

结构性守卫（注册表 / offer 池 / 数据链 / 卡面文本漂移 / DEFERRED 迁移 /
只挂 on_bind / 载荷消费点）标 `@engine-only`。引擎原语契约（归一/
生效期/fail-loud）见 `test_engine_primitives.py::TestFamilyFlagChannel`。

突变敏感性（**2026-09-18 实测**：外部改文件重跑本文件 +
test_batch_remaining2/test_batch_payload_minions，逐项记录失败的**新文件**
测试；每次都清理 `__pycache__` 以避免陈旧字节码）:
  - M1 载荷停止读 Kaboom 开关（`if False`）→ FAIL
    `TestKaboomBotPortrait::test_combat_damage_with_portrait_is_fourteen`,
    `...::test_golden_two_instances_each_fourteen`;
  - M2 加成数额 10→8 → FAIL 上述两项 +
    `TestRegistryAndLedger::test_flag_constants_owned_by_payload`;
  - M3 加成只作用于第一个实例 → FAIL
    `TestKaboomBotPortrait::test_golden_two_instances_each_fourteen`;
  - M4 载荷停止读 Impulsive 开关（`if False`）→ FAIL
    `TestImpulsivePortrait::test_adjacent_both_get_full_max_health`,
    `...::test_golden_both_adjacent_get_twice`;
  - M5 目标集合改为"单个相邻"（`targets[:1]`）→ FAIL 上述两项;
  - M6 数额均分（`amount // len(targets)`）→ FAIL 上述两项;
  - M7 6/6 覆盖改为 5（`IMPULSIVE_STAT = 5`）→ FAIL
    `TestImpulsivePortrait::test_grants_six_six_trickster_and_flag`,
    `...::test_granted_six_six_is_playable`,
    `TestRegistryAndLedger::test_flag_constants_owned_by_payload`。
  `TestMutationProbes` 另把 M1/M4 变成**运行期可复现**断言（钉死
  `game.family_flag` 为未命中 → 正效果消失）。
"""

from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

from hsrl2.actions import Hit
from hsrl2.db import CardDB
from hsrl2.events import DAMAGE, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_payload_minions as BP
from hsrl2.scripts.batches import batch_remaining2 as BR2
from hsrl2.scripts.batches import batch_trinkets39 as B39
from hsrl2.tags import CardType, GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 本批 id（CardDB 按名核实——禁止凭记忆写 id） ──
KABOOM_PORTRAIT = B39.KABOOM_BOT_PORTRAIT
IMPULSIVE_PORTRAIT = B39.IMPULSIVE_PORTRAIT
KABOOM = BR2.KABOOM
KABOOM_G = BR2.KABOOM_G
IMPULSIVE = BP.IMPULSIVE
IMPULSIVE_G = BP.IMPULSIVE_G
SCARLET_SKULL = "BG25_022"        # 非家族亡语对照（随机 Undead +1/+2）

# 同族/同批 DEFERRED 台账（仍阻塞的 Portrait——803/820 已由本批迁出）
# 868 Rewinder / 987 Balladist / 869 Felblood / 824 Implicator Portrait 已由
# batch_trinkets31 注册（2026-09-19——owner 权威序: wiki 页无 Notes → 卡面
# 天然语言; 868/987/283 型 "also give X" 增量 = 同句既有量; 824 =
# `hero.consume_policies` + `Game.pick_consume_victim` 读取点）→ 移出本
# 台账，DEFERRED 清零。
DEFERRED_IDS = ()

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 3901) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid, source="test")
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str,
        position: int | None = None, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int,
                race: Race = Race.NONE) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)


def summon_plain(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def slay(game: Game, m: Minion) -> None:
    """真实死亡路径（亡语分发，ctx["position"] = 死者让出的板位）。"""
    m.health = 0
    game._process_single_death(m)


def damage_probe(game: Game, victim: Minion) -> list:
    """在 `victim` 上装 DAMAGE 探针，返回 (amount, source_card_id) 列表。

    `source_card_id` = 伤害来源卡 id（攻击路径 = 攻击者; 亡语 `Hit` 不传
    source → None），据此把亡语伤害实例与攻击伤害分开断言。
    """
    log: list = []

    def cb(g, minion=None, amount=None, source=None, **kw):
        if minion is victim and amount:
            log.append((amount,
                        source.card_id if source is not None else None))

    game.events.register(Listener(event=DAMAGE, owner=victim, callback=cb))
    return log


def _hand_of(hero: Hero, card_id: str) -> list:
    return [c for c in hero.hand if c.card_id == card_id]


def _norm(text: str) -> str:
    t = text.replace("[x]", " ")
    t = re.sub(r"</?b>", "", t)
    t = re.sub(r"<i>|</i>", "", t)
    return " ".join(t.replace("_", " ").split())


# ══════════════ Kaboom Bot Portrait 行为层 ══════════════


class TestKaboomBotPortrait(unittest.TestCase):
    """BG30_MagicItem_803 — 家族亡语每个伤害实例 +10（金色 14+14）。"""

    def test_grants_kaboom_and_flag(self):
        g = make_game(seed=3901)
        a, b = g.heroes
        bind(g, a, KABOOM_PORTRAIT)
        granted = _hand_of(a, KABOOM)
        self.assertEqual(len(granted), 1)              # 真实数据链授予
        self.assertFalse(granted[0].is_golden)         # "Get a Kaboom Bot"
        self.assertTrue(g.family_flag(a, KABOOM, BR2.FLAG_KABOOM_DR_BONUS))
        self.assertTrue(g.family_flag(a, KABOOM_G,
                                      BR2.FLAG_KABOOM_DR_BONUS))  # 金色归一
        self.assertFalse(g.family_flag(b, KABOOM,
                                       BR2.FLAG_KABOOM_DR_BONUS))  # owner 隔离
        # 非家族卡 id 不命中同一开关
        self.assertFalse(g.family_flag(a, IMPULSIVE,
                                       BR2.FLAG_KABOOM_DR_BONUS))

    def test_combat_damage_with_portrait_is_fourteen(self):
        g = make_game(seed=3902)
        a, b = g.heroes
        bind(g, a, KABOOM_PORTRAIT)
        put(g, a, KABOOM)
        enemy = make_minion("ENEMY", 1, 30)
        summon_plain(g, b, enemy)
        log = damage_probe(g, enemy)
        g.run_combat(a, b)
        dmg = [amt for amt, src in log if src is None]
        self.assertEqual(dmg, [14])            # 4 + 10（文本字面量钉死）
        self.assertEqual(len([d for d in g.rng.decisions
                              if d[0] == "kaboom_bot_target"]), 1)

    def test_control_without_portrait_is_four(self):
        g = make_game(seed=3903)
        a, b = g.heroes
        put(g, a, KABOOM)
        enemy = make_minion("ENEMY", 1, 30)
        summon_plain(g, b, enemy)
        log = damage_probe(g, enemy)
        g.run_combat(a, b)
        self.assertEqual([amt for amt, src in log if src is None], [4])

    def test_golden_two_instances_each_fourteen(self):
        """金色 "twice" 的两个实例**各自** +10（owner 裁定读法）。"""
        g = make_game(seed=3904)
        a, b = g.heroes
        bind(g, a, KABOOM_PORTRAIT)
        bomb = put(g, a, KABOOM_G)
        bomb.set(GameTag.ATK, 0)
        bomb.set(GameTag.BASE_ATK, 0)
        for i in range(2):
            summon_plain(g, b, make_minion(f"E{i}", 2, 30))
        log = []
        g.events.register(Listener(
            event=DAMAGE, owner=None,
            callback=lambda gg, minion=None, amount=0, source=None, **kw: (
                log.append(amount) if source is None else None)))
        g.run_combat(a, b)
        self.assertEqual(log, [14, 14])

    def test_golden_control_without_portrait(self):
        g = make_game(seed=3905)
        a, b = g.heroes
        bomb = put(g, a, KABOOM_G)
        bomb.set(GameTag.ATK, 0)
        bomb.set(GameTag.BASE_ATK, 0)
        for i in range(2):
            summon_plain(g, b, make_minion(f"E{i}", 2, 30))
        log = []
        g.events.register(Listener(
            event=DAMAGE, owner=None,
            callback=lambda gg, minion=None, amount=0, source=None, **kw: (
                log.append(amount) if source is None else None)))
        g.run_combat(a, b)
        self.assertEqual(log, [4, 4])

    def test_opponent_portrait_does_not_affect_my_kaboom(self):
        g = make_game(seed=3906)
        a, b = g.heroes
        bind(g, b, KABOOM_PORTRAIT)          # 对手持有饰品
        put(g, a, KABOOM)
        enemy = make_minion("ENEMY", 1, 30)
        summon_plain(g, b, enemy)
        log = damage_probe(g, enemy)
        g.run_combat(a, b)
        self.assertEqual([amt for amt, src in log if src is None], [4])

    def test_non_family_deathrattle_unaffected(self):
        """非家族亡语（Scarlet Skull 随机 Undead +1/+2）不被改写。"""
        g = make_game(seed=3907)
        a, _b = g.heroes
        bind(g, a, KABOOM_PORTRAIT)
        skull = put(g, a, SCARLET_SKULL)
        u1 = summon_plain(g, a, make_minion("U1", 1, 1, race=Race.UNDEAD))
        u2 = summon_plain(g, a, make_minion("U2", 1, 1, race=Race.UNDEAD))
        slay(g, skull)
        gained = [(u1.atk - 1, u1.max_health - 1),
                  (u2.atk - 1, u2.max_health - 1)]
        self.assertEqual(sorted(gained), [(0, 0), (1, 2)])   # 恰一名 +1/+2
        # 开关不泄漏到非家族卡 id
        self.assertFalse(g.family_flag(a, SCARLET_SKULL,
                                       BR2.FLAG_KABOOM_DR_BONUS))

    def test_flag_expires_when_trinket_removed(self):
        g = make_game(seed=3908)
        a, b = g.heroes
        ent = bind(g, a, KABOOM_PORTRAIT)
        self.assertTrue(g.family_flag(a, KABOOM, BR2.FLAG_KABOOM_DR_BONUS))
        a.trinkets.remove(ent)
        self.assertFalse(g.family_flag(a, KABOOM, BR2.FLAG_KABOOM_DR_BONUS))
        kaboom = put(g, a, KABOOM)
        enemy = make_minion("ENEMY", 1, 30)
        summon_plain(g, b, enemy)
        log = damage_probe(g, enemy)
        g._active_combat = (a, b)
        try:
            slay(g, kaboom)
        finally:
            g._active_combat = None
        self.assertEqual([amt for amt, src in log if src is None], [4])


# ══════════════ Impulsive Portrait 行为层 ══════════════


class TestImpulsivePortrait(unittest.TestCase):
    """BG32_MagicItem_820 — 交付 6/6 + 亡语目标改为相邻（全额逐目标）。"""

    def test_grants_six_six_trickster_and_flag(self):
        g = make_game(seed=3921)
        a, b = g.heroes
        bind(g, a, IMPULSIVE_PORTRAIT)
        granted = _hand_of(a, IMPULSIVE)
        self.assertEqual(len(granted), 1)
        self.assertFalse(granted[0].is_golden)
        self.assertEqual((granted[0].atk, granted[0].max_health),
                         (B39.IMPULSIVE_STAT, B39.IMPULSIVE_STAT))   # 6/6
        # 当前生命也必须被设为 6: 只改 max_health 时入手实体为 6/5,
        # 既有断言察觉不到（对抗验证 M19 变异存活）。
        self.assertEqual(granted[0].health, B39.IMPULSIVE_STAT)
        base = get_db().get(IMPULSIVE)
        self.assertNotEqual((granted[0].atk, granted[0].max_health),
                            (base.atk, base.health))   # 覆盖确实生效
        self.assertTrue(g.family_flag(a, IMPULSIVE,
                                      BP.FLAG_IMPULSIVE_ADJACENT))
        self.assertTrue(g.family_flag(a, IMPULSIVE_G,
                                      BP.FLAG_IMPULSIVE_ADJACENT))
        self.assertFalse(g.family_flag(b, IMPULSIVE,
                                       BP.FLAG_IMPULSIVE_ADJACENT))
        self.assertFalse(g.family_flag(a, KABOOM,
                                       BP.FLAG_IMPULSIVE_ADJACENT))

    def _middle_trickster(self, g, golden: bool = False):
        a, _b = g.heroes
        far = summon_plain(g, a, make_minion("FAR", 1, 1))
        left = summon_plain(g, a, make_minion("LEFT", 1, 1))
        trick = put(g, a, IMPULSIVE, golden=golden)
        right = summon_plain(g, a, make_minion("RIGHT", 1, 1))
        return far, left, trick, right

    def test_adjacent_both_get_full_max_health(self):
        """两个相邻随从**各得全额** max_health（非均分）。"""
        g = make_game(seed=3922)
        a, _b = g.heroes
        bind(g, a, IMPULSIVE_PORTRAIT)
        far, left, trick, right = self._middle_trickster(g)
        amount = trick.max_health
        self.assertEqual(amount, get_db().get(IMPULSIVE).health)  # 5/5 本体
        slay(g, trick)
        self.assertEqual(left.max_health, 1 + amount)
        self.assertEqual(right.max_health, 1 + amount)
        self.assertEqual(far.max_health, 1)      # 非相邻不变
        # 正效果断言: 增量合计 = 2 × amount（均分读法会给 2 × amount/2）
        self.assertEqual((left.max_health - 1) + (right.max_health - 1),
                         2 * amount)

    def test_control_without_portrait_random_single_target(self):
        g = make_game(seed=3923)
        a, _b = g.heroes
        far, left, trick, right = self._middle_trickster(g)
        amount = trick.max_health
        slay(g, trick)
        gained = sorted([left.max_health - 1, right.max_health - 1,
                         far.max_health - 1])
        self.assertEqual(gained, [0, 0, amount])   # 恰一名随机友方
        self.assertEqual(len([d for d in g.rng.decisions
                              if d[0] == "impulsive_trickster_target"]), 1)

    def test_golden_both_adjacent_get_twice(self):
        g = make_game(seed=3924)
        a, _b = g.heroes
        bind(g, a, IMPULSIVE_PORTRAIT)
        far, left, trick, right = self._middle_trickster(g, golden=True)
        amount = trick.max_health                # 金色本体 10/10
        self.assertEqual(amount, 10)
        slay(g, trick)
        self.assertEqual(left.max_health, 1 + 2 * amount)
        self.assertEqual(right.max_health, 1 + 2 * amount)
        self.assertEqual(far.max_health, 1)

    def test_no_adjacent_fizzles(self):
        g = make_game(seed=3925)
        a, _b = g.heroes
        bind(g, a, IMPULSIVE_PORTRAIT)
        trick = put(g, a, IMPULSIVE)
        before = trick.max_health
        slay(g, trick)
        self.assertEqual(a.board, [])            # 本体是唯一友方 → 落空
        self.assertEqual(before, get_db().get(IMPULSIVE).health)

    def test_opponent_portrait_does_not_affect_my_trickster(self):
        g = make_game(seed=3926)
        a, b = g.heroes
        bind(g, b, IMPULSIVE_PORTRAIT)
        far, left, trick, right = self._middle_trickster(g)
        amount = trick.max_health
        slay(g, trick)
        gained = sorted([left.max_health - 1, right.max_health - 1,
                         far.max_health - 1])
        self.assertEqual(gained, [0, 0, amount])   # 仍随机单目标

    def test_non_family_deathrattle_unaffected(self):
        g = make_game(seed=3927)
        a, _b = g.heroes
        bind(g, a, IMPULSIVE_PORTRAIT)
        skull = put(g, a, SCARLET_SKULL)
        u1 = summon_plain(g, a, make_minion("U1", 1, 1, race=Race.UNDEAD))
        u2 = summon_plain(g, a, make_minion("U2", 1, 1, race=Race.UNDEAD))
        slay(g, skull)
        gained = sorted([(u1.atk - 1, u1.max_health - 1),
                         (u2.atk - 1, u2.max_health - 1)])
        self.assertEqual(gained, [(0, 0), (1, 2)])   # 恰一名 +1/+2
        self.assertFalse(g.family_flag(a, SCARLET_SKULL,
                                       BP.FLAG_IMPULSIVE_ADJACENT))

    def test_flag_expires_when_trinket_removed(self):
        g = make_game(seed=3928)
        a, _b = g.heroes
        ent = bind(g, a, IMPULSIVE_PORTRAIT)
        self.assertTrue(g.family_flag(a, IMPULSIVE,
                                      BP.FLAG_IMPULSIVE_ADJACENT))
        a.trinkets.remove(ent)
        self.assertFalse(g.family_flag(a, IMPULSIVE,
                                       BP.FLAG_IMPULSIVE_ADJACENT))
        far, left, trick, right = self._middle_trickster(g)
        amount = trick.max_health
        slay(g, trick)
        gained = sorted([left.max_health - 1, right.max_health - 1,
                         far.max_health - 1])
        self.assertEqual(gained, [0, 0, amount])   # 回到随机单目标

    def test_granted_six_six_is_playable(self):
        """6/6 副本真实打出后棋盘本体为 6/6（文本字面量贯通）。"""
        g = make_game(seed=3929)
        a, _b = g.heroes
        bind(g, a, IMPULSIVE_PORTRAIT)
        granted = _hand_of(a, IMPULSIVE)[0]
        self.assertTrue(g.play_minion(a, granted))
        self.assertEqual((a.board[-1].atk, a.board[-1].max_health), (6, 6))


# ══════════════ 运行期变异探针（@engine-only） ══════════════


class TestMutationProbes(unittest.TestCase):
    """@engine-only 引擎读取点变异探针（SOP §16 手工判定法的可复现版本）。

    把 `game.family_flag` 钉死为"未命中"（等价于删掉载荷的读取点），
    断言正效果**消失**——即"载荷确实经 family_flag 读开关"是可复现断言，
    不依赖外部改文件重跑。完整离线突变记录（含改数额 / 改目标集合 / 改
    6-6）见模块 docstring。
    """

    def test_engine_kaboom_flag_read_is_load_bearing(self):
        g = make_game(seed=3941)
        a, b = g.heroes
        bind(g, a, KABOOM_PORTRAIT)
        g.family_flag = lambda *args, **kw: False       # 变异: 关闭读取点
        put(g, a, KABOOM)
        enemy = make_minion("ENEMY", 1, 30)
        summon_plain(g, b, enemy)
        log = damage_probe(g, enemy)
        g.run_combat(a, b)
        self.assertEqual([amt for amt, src in log if src is None], [4])

    def test_engine_impulsive_flag_read_is_load_bearing(self):
        g = make_game(seed=3942)
        a, _b = g.heroes
        bind(g, a, IMPULSIVE_PORTRAIT)
        g.family_flag = lambda *args, **kw: False       # 变异: 关闭读取点
        far = summon_plain(g, a, make_minion("FAR", 1, 1))
        left = summon_plain(g, a, make_minion("LEFT", 1, 1))
        trick = put(g, a, IMPULSIVE)
        right = summon_plain(g, a, make_minion("RIGHT", 1, 1))
        amount = trick.max_health
        slay(g, trick)
        gained = sorted([left.max_health - 1, right.max_health - 1,
                         far.max_health - 1])
        self.assertEqual(gained, [0, 0, amount])   # 回到随机单目标


# ══════════════ 注册表 / 台账（结构性，@engine-only） ══════════════


class TestRegistryAndLedger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / offer 池 / 数据链 / DEFERRED / 接线。"""

    def test_registered_ids(self):
        self.assertIs(REGISTRY.get(KABOOM_PORTRAIT),
                      B39.KaboomBotPortraitScript)
        self.assertIs(REGISTRY.get(IMPULSIVE_PORTRAIT),
                      B39.ImpulsivePortraitScript)
        for tid in (KABOOM_PORTRAIT, IMPULSIVE_PORTRAIT):
            self.assertEqual(REGISTRY.get(tid).__module__,
                             "hsrl2.scripts.batches.batch_trinkets39", tid)

    def test_in_trinket_offer_pool(self):
        pool = {d.id for d in get_db().trinket_offer_pool()}
        for tid in (KABOOM_PORTRAIT, IMPULSIVE_PORTRAIT):
            self.assertIn(tid, pool)

    def test_card_defs(self):
        db = get_db()
        for tid in (KABOOM_PORTRAIT, IMPULSIVE_PORTRAIT):
            d = db.get(tid)
            self.assertEqual(d.card_type, CardType.BACON_TRINKET, tid)
            self.assertEqual(d.spell_school, 11, tid)      # Lesser
            self.assertEqual([d.num(i) for i in range(5)],
                             [None] * 5, tid)              # 无模板参数
            self.assertIn("Deathrattles", d.text, tid)

    def test_related_card_data_chain(self):
        db = get_db()
        self.assertEqual(  # noqa: SIM300
            db.by_dbf(db.get(KABOOM_PORTRAIT).evolution_card_id).id, KABOOM)
        self.assertEqual(  # noqa: SIM300
            db.by_dbf(db.get(IMPULSIVE_PORTRAIT).evolution_card_id).id,
            IMPULSIVE)

    def test_card_text_matches_docstring(self):
        """卡面文本签名（数据漂移守卫）必须出现在脚本类 docstring 中。"""
        db = get_db()
        for tid, cls in ((KABOOM_PORTRAIT, B39.KaboomBotPortraitScript),
                         (IMPULSIVE_PORTRAIT, B39.ImpulsivePortraitScript)):
            want = _norm(db.get(tid).text)
            self.assertIn(" ".join(want.split()),
                          " ".join(_norm(cls.__doc__).split()), tid)

    def test_flag_constants_owned_by_payload(self):
        """开关名常量定义在载荷侧（唯一消费点），饰品侧导入同一常量。"""
        self.assertEqual(B39.FLAG_KABOOM_DR_BONUS,
                         BR2.FLAG_KABOOM_DR_BONUS)
        self.assertEqual(B39.FLAG_IMPULSIVE_ADJACENT,
                         BP.FLAG_IMPULSIVE_ADJACENT)
        self.assertEqual(B39.FLAG_KABOOM_DR_BONUS,
                         "kaboom_deathrattle_damage_bonus")
        self.assertEqual(B39.FLAG_IMPULSIVE_ADJACENT,
                         "impulsive_trickster_target_adjacent")
        self.assertEqual(BR2.KABOOM_EXTRA_DAMAGE, 10)
        self.assertEqual(B39.IMPULSIVE_STAT, 6)

    def test_scripts_declare_only_on_bind(self):
        hooks = ("battlecry", "deathrattle", "start_of_combat", "avenge",
                 "rally", "start_of_turn", "end_of_turn", "on_sell",
                 "on_summon", "on_play", "activate", "atk", "health",
                 "hero_power")
        for cls in (B39.KaboomBotPortraitScript,
                    B39.ImpulsivePortraitScript):
            self.assertTrue(callable(getattr(cls, "on_bind", None)))
            self.assertEqual([h for h in hooks if h in vars(cls)], [], cls)

    def test_payloads_consume_flag(self):
        """载荷消费点存在且非装饰性接线（源码内含 read + 常量）。"""
        kab = inspect.getsource(BR2.KaboomBotScript.deathrattle)
        self.assertIn("family_flag", kab)
        self.assertIn("FLAG_KABOOM_DR_BONUS", kab)
        self.assertIn("KABOOM_EXTRA_DAMAGE", kab)
        imp = inspect.getsource(BP.ImpulsiveTricksterScript.deathrattle)
        self.assertIn("family_flag", imp)
        self.assertIn("FLAG_IMPULSIVE_ADJACENT", imp)
        self.assertIn("_adjacent_minions", imp)

    def test_deferred_not_registered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid), tid)

    def test_deferred_ids_exist_as_trinkets(self):
        for tid in DEFERRED_IDS:
            d = get_db().get(tid)
            self.assertIsNotNone(d, tid)
            self.assertEqual(d.card_type, CardType.BACON_TRINKET, tid)


if __name__ == "__main__":
    unittest.main()
