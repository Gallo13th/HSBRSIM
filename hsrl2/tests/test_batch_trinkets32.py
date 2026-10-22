"""批次 trinkets32 行为层测试（3 张注册饰品 = 3 CORRECT / 0 DEFERRED）。

覆盖（每张卡真实路径）:
  - `BG30_MagicItem_804` Ancient Wishbone — 真实 `game.use_hero_power`
    结算（探针技能脚本计数）; 负对照（未绑定 1 次）; owner 隔离
    （对手技能 1 次）; 两份副本不叠加; 同 seed 确定性。
  - `BG30_MagicItem_440` Boom Controller — 真实 `game.run_combat`（空板
    完成引擎每场重置）+ 真实死亡链（`_process_single_death` +
    `combat_slot_freed` 广播）: 首只死亡 Mech 的 **exact copy**
    （card_id/golden/属性/关键词/**独立** Buff 实例，附魔不双计）;
    首死非 Mech 时取第一只 Mech; 无 Mech 不召唤; 每场至多一次; 跨战斗
    重置; 对手隔离; 腾位瞬间被另一消费者填满 → `game.summon` 落空。
  - `BG30_MagicItem_822` Twin Sky Lanterns — 真实 `game.run_combat`:
    本场首只**战斗内召唤**随从的入场态副本; 对手召唤不记录; 每场至多
    一次; 跨战斗重置; 无记录落空; 满场落空; 同 seed 确定性。

`combat_slot_freed` 仅在 `len(hero.board) < BOARD_SIZE` 时广播
（game.py:2194），故"满场落空"以**另一消费者抢先占位**的真实竞争构造
（两个 "when you have space" 消费者争同一板位）。

结构性守卫（注册表 / 数据 / 数值 / 无第三态）标 `@engine-only`。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff as BuffAction
from hsrl2.db import CardDB
from hsrl2.entity import Buff as EntityBuff
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets32 as B32
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

WISHBONE = B32.ANCIENT_WISHBONE
BOOM = B32.BOOM_CONTROLLER
LANTERNS = B32.TWIN_SKY_LANTERNS

# 真实卡（CardDB 按名核实——禁止凭记忆写 id）
MECHAROO = "TB_BaconUps_002"    # Mecharoo 2/2 Mech（无脚本触发）
SEWER_RAT = "BG19_010"          # Sewer Rat 3/2 Beast（亡语: 2/3 龟）
DUMMY = "BG25_013"              # Rot Hide Gnoll 1/4 T1（无触发）
OTHER_MECH = "BG29_611"         # Cord Puller 1/1 Mech（圣盾 + 亡语: 1/1 Microbot）
STATS_LISTENER = "BG34_Giant_064"   # Timewarped Whelp Smuggler: 友方随从
                                    # 获得攻击力 → 给它 +3 生命（stats_gained
                                    # 监听器——副本重放的负对照探针）

# 探针技能: 真实免费技能 `TB_BaconShop_HP_052` Arcane Alteration
# （cost=0、每回合 1 次、无 available 门槛），测试期把 REGISTRY 的脚本
# 换成计数探针——验证"一次 `use_hero_power` 内技能脚本被结算几次"
# （技能机制与费用路径仍走真实引擎）。
PROBE_POWER = "TB_BaconShop_HP_052"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 3201) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str, duplicate: bool = False):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid, source="test", duplicate=duplicate)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


class _ProbePower:
    """计数探针技能脚本（真实引擎结算路径；无副作用）。"""

    calls = 0

    @staticmethod
    def hero_power(hero, game, ctx):
        _ProbePower.calls += 1
        return None


def _install_probe():
    """把真实免费技能 `PROBE_POWER` 的脚本临时替换为计数探针。

    返回还原回调（SOP §16c item 33: 测试改 REGISTRY 必须保存/还原）。
    """
    original = REGISTRY.get(PROBE_POWER)
    REGISTRY[PROBE_POWER] = _ProbePower
    _ProbePower.calls = 0

    def restore():
        if original is None:
            REGISTRY.pop(PROBE_POWER, None)
        else:
            REGISTRY[PROBE_POWER] = original

    return restore


def _use_probe_power(game: Game, hero: Hero) -> bool:
    """用真实 `use_hero_power` 结算一次真实免费技能（每回合计数清零后）。"""
    hero.clear(GameTag.HERO_POWER_USED_THIS_TURN)
    hero._power_uses_this_turn.pop(PROBE_POWER, None)
    return game.use_hero_power(hero, power_id=PROBE_POWER)


def _arm_probe_power(game: Game, hero: Hero) -> None:
    hero._active_power_id = PROBE_POWER
    hero._second_power_id = None


def _kill_death_event(game: Game, victim: Minion) -> None:
    """驱动完整战斗内死亡链（`_process_single_death` → 腾位广播 → 亡语）。

    `in_combat` **全程**保持真（含 `check_deaths()` 内的亡语召唤）——
    否则亡语召唤体不入 `combat_summon_log`，与真实战斗不符。
    """
    prev = game.in_combat
    game.in_combat = True
    try:
        victim.set(GameTag.HEALTH, 0)
        game._process_single_death(victim)
        game.check_deaths()
    finally:
        game.in_combat = prev


def _combat_summon(game: Game, hero: Hero, card_id: str) -> Minion:
    """真实战斗内的召唤（`in_combat=True` → 入 `combat_summon_log`）。

    本批两张"when you have space"饰品的**触发**依赖 `combat_slot_freed`
    （战斗内广播）; 被复制对象是"本场首召唤物"，故测试在 `run_combat`
    之后以 `in_combat=True` 置入实体（战斗内时点由插入式死亡探针精确
    驱动——TEST_SOP §8 既有口径）。
    """
    prev = game.in_combat
    game.in_combat = True
    try:
        m = game.create_minion(card_id, controller=hero)
        assert game.summon(hero, m)
    finally:
        game.in_combat = prev
    return m


def _copies(game: Game, hero: Hero, card_id: str,
            exclude=None) -> list:
    """本场召唤日志中属于 hero 的某卡**副本**（战斗内召唤顺序）。

    `exclude` = 用于记录快照的"本场首召唤物"实体本身（它也在日志里）——
    断言"饰品召唤了几份副本"时须把它剔除。
    """
    out = [m for m in game.combat_summon_log
           if m.controller is hero and m.card_id == card_id]
    if exclude is not None:
        out = [m for m in out if m is not exclude]
    return out


# ══════════════ BG30_MagicItem_804 Ancient Wishbone ══════════════


class TestAncientWishbone(unittest.TestCase):
    TID = WISHBONE

    def setUp(self):
        self.restore = _install_probe()

    def tearDown(self):
        self.restore()

    def test_bound_triggers_hero_power_twice(self):
        """真实 `use_hero_power`: 绑定后一次使用技能脚本结算 2 次。"""
        g = make_game(seed=3201)
        a, _b = g.heroes
        _arm_probe_power(g, a)
        bind(g, a, self.TID)
        self.assertEqual(a.extra_triggers.get("hp_times"), 1)
        self.assertTrue(_use_probe_power(g, a))
        self.assertEqual(_ProbePower.calls, 2)

    def test_control_without_trinket_triggers_once(self):
        """负对照 + 正对照: 未绑定 1 次; 同局绑定后同路径 2 次。"""
        g = make_game(seed=3201)
        a, _b = g.heroes
        _arm_probe_power(g, a)
        self.assertTrue(_use_probe_power(g, a))
        self.assertEqual(_ProbePower.calls, 1)          # 未绑定 → 1 次
        bind(g, a, self.TID)
        self.assertTrue(_use_probe_power(g, a))
        self.assertEqual(_ProbePower.calls, 3)          # 绑定后 1 + 2 次**
        # **注: 累计 3 = 负对照 1 + 绑定后一次结算 2; 正对照的关键是
        # "绑定后单次使用贡献 2 次"（下方差值断言，突变 on_bind 后为 1）
        _ProbePower.calls = 0
        self.assertTrue(_use_probe_power(g, a))
        self.assertEqual(_ProbePower.calls, 2)

    def test_opponent_hero_power_unaffected(self):
        """owner 隔离: 绑定者 2 次，对手仍 1 次。"""
        g = make_game(seed=3202)
        a, b = g.heroes
        _arm_probe_power(g, a)
        _arm_probe_power(g, b)
        bind(g, a, self.TID)
        self.assertTrue(_use_probe_power(g, a))
        self.assertEqual(_ProbePower.calls, 2)
        _ProbePower.calls = 0
        self.assertTrue(_use_probe_power(g, b))
        self.assertEqual(_ProbePower.calls, 1)
        self.assertEqual(b.extra_triggers.get("hp_times"), None)

    def test_two_copies_do_not_stack(self):
        """两份副本（duplicate）幂等: 额度仍为 1 → 仍结算 2 次。"""
        g = make_game(seed=3203)
        a, _b = g.heroes
        _arm_probe_power(g, a)
        bind(g, a, self.TID)
        bind(g, a, self.TID, duplicate=True)
        self.assertEqual(a.extra_triggers.get("hp_times"), 1)
        self.assertTrue(_use_probe_power(g, a))
        self.assertEqual(_ProbePower.calls, 2)

    def test_second_use_same_turn_also_doubles(self):
        """额度是**永久**声明（非一次性）: 清每回合计数后再用仍 2 次。"""
        g = make_game(seed=3204)
        a, _b = g.heroes
        _arm_probe_power(g, a)
        bind(g, a, self.TID)
        self.assertTrue(_use_probe_power(g, a))
        self.assertTrue(_use_probe_power(g, a))
        self.assertEqual(_ProbePower.calls, 4)

    def test_deterministic_same_seed(self):
        """同 seed 确定性。"""
        results = []
        for _ in range(2):
            _ProbePower.calls = 0
            g = make_game(seed=3205)
            a, _b = g.heroes
            _arm_probe_power(g, a)
            bind(g, a, self.TID)
            _use_probe_power(g, a)
            results.append(_ProbePower.calls)
        self.assertEqual(results, [2, 2])


# ══════════════ BG30_MagicItem_440 Boom Controller ══════════════


class TestBoomController(unittest.TestCase):
    TID = BOOM

    @staticmethod
    def _fresh_combat(g: Game, a: Hero, b: Hero) -> None:
        """真实 `run_combat`（**空板**）完成引擎每场重置 → 本场账本归零。

        空板战斗无死亡/无召唤，`run_combat` finally 的 `combat_restored`
        清空本卡的闩与快照（RULES §7.4.10b/§6.20）。其后以插入式死亡
        探针（`_kill_death_event`）在**本场**内驱动真实死亡链
        （TEST_SOP §8 既有口径）。
        """
        g.run_combat(a, b)
        assert g.combat_summon_log == []
        assert a._combat_dead_snaps == []

    def test_copy_is_alive_after_real_damage_death(self):
        """BUG-440 回归（对抗验证 MAJOR）: 真实伤害致死（health setter 置
        `DEAD`）后副本必须**活着入场**。

        旧实现把"所有 True tag"（含 `DEAD`）记入快照并复原，且 `summon`
        不清 `DEAD` → 副本死着入场、不能攻击、立即进死亡链触发自身亡语。
        作者的 `_kill_death_event` 用 raw `set(HEALTH,0)`（绕过 health
        setter，不产生 `DEAD`）→ 掩盖了缺陷; 本测试走**真实 `take_damage`**。
        """
        g = make_game(seed=3219)
        a, b = g.heroes
        self._fresh_combat(g, a, b)
        bind(g, a, self.TID)
        mech = put(g, a, MECHAROO)
        mech.take_damage(mech.health)          # 真实伤害路径 → DEAD tag
        self.assertTrue(mech.has(GameTag.DEAD))
        prev = g.in_combat
        g.in_combat = True
        try:
            g.check_deaths()
        finally:
            g.in_combat = prev
        copies = _copies(g, a, MECHAROO)
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertFalse(copy.has(GameTag.DEAD), "副本带着 DEAD tag 入场")
        self.assertFalse(copy.dead, "副本死着入场")
        self.assertEqual(copy.zone, Zone.PLAY, "副本应在棋盘（PLAY）")
        self.assertTrue(copy.get(GameTag.HEALTH, 0) > 0)
        # 快照关键词白名单: 不含状态 tag（引擎 helper）
        self.assertNotIn(GameTag.DEAD,
                         g.keyword_tags_of(mech))

    def test_first_mech_died_is_copied_exactly(self):
        """真实战斗: 首只死亡 Mech → 腾位事件内 summon **精确副本**。"""
        g = make_game(seed=3210)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        mech = put(g, a, MECHAROO)
        put(g, a, DUMMY)
        snap = (mech.atk, mech.max_health, mech.race)   # 死亡前取值
        _kill_death_event(g, mech)                      # 真实死亡链
        copies = _copies(g, a, MECHAROO)
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy.card_id, MECHAROO)
        self.assertFalse(copy.is_golden)
        self.assertEqual(copy.race, snap[2])
        self.assertEqual(copy.atk, snap[0])
        self.assertEqual(copy.max_health, snap[1])

    def test_copy_excludes_aura_so_aura_not_double_counted(self):
        """对抗验证 MAJOR（2026-09-13）: 快照**不得烘入光环**。

        副本入场后实时光环重算 → 最终属性 == 死亡瞬间属性; 若快照记录
        含光环的 `atk`/`max_health` 再写回基础值，光环被计两次
        （修复前实测 4/4 副本 → 6/6）。
        """
        from hsrl2.actions.racefx import ApplyRaceAura
        g = make_game(seed=3225)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        g.run_actions([ApplyRaceAura(a, Race.MECH, 2, 2)])
        base = get_db().get(MECHAROO)
        mech = put(g, a, MECHAROO)
        put(g, a, DUMMY)
        self.assertEqual((mech.atk, mech.max_health),
                         (base.atk + 2, base.health + 2))   # 光环生效
        dead_state = (mech.atk, mech.max_health)
        _kill_death_event(g, mech)
        copies = _copies(g, a, MECHAROO)
        self.assertEqual(len(copies), 1)
        self.assertEqual((copies[0].atk, copies[0].max_health), dead_state,
                         "光环双计（副本烘入光环后又重算一次）")
        # 无光环对照: 同一路径下副本 == 本体基础值
        g2 = make_game(seed=3226)
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        self._fresh_combat(g2, a2, b2)
        mech2 = put(g2, a2, MECHAROO)
        put(g2, a2, DUMMY)
        _kill_death_event(g2, mech2)
        c2 = _copies(g2, a2, MECHAROO)
        self.assertEqual(len(c2), 1)
        self.assertEqual((c2[0].atk, c2[0].max_health),
                         (base.atk, base.health))

    def test_copy_restores_buffs_as_independent_instances(self):
        """`exact copy` 含附魔，且 Buff 是**独立实例**（非共享对象）。"""
        g = make_game(seed=3211)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        mech = put(g, a, MECHAROO)
        mech.add_buff(EntityBuff(atk=3, health=2))
        put(g, a, DUMMY)
        snap = (mech.atk, mech.max_health,
                [(x.atk, x.health) for x in mech.buffs])
        _kill_death_event(g, mech)
        copies = _copies(g, a, MECHAROO)
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy.atk, snap[0])          # 附魔不双计
        self.assertEqual(copy.max_health, snap[1])
        self.assertEqual([(x.atk, x.health) for x in copy.buffs], snap[2])
        self.assertEqual(len(copy.buffs), 1)
        self.assertIsNot(copy.buffs[0], mech.buffs[0])   # 独立实例

    def test_copy_replay_does_not_trigger_stats_gained_listener(self):
        """副本附魔重放 = **复制**（非"获得"）→ 不得触发 `stats_gained`
        监听器（2026-09-20 对抗验证纠错）。

        真实路径: Boom Controller 绑定 → 真实战斗内死亡链
        （`_process_single_death` → `combat_slot_freed`）→
        `_restore_from_snapshot` 以独立 Buff 实例重放死者附魔。棋盘上放
        真实监听器 `BG34_Giant_064`（"友方随从获得攻击力 → 给它 +3
        生命"）: 若重放未被 `suppress_stats_gained()` 包裹，副本的
        +3 攻击会被当成真实"获得" → 监听器给副本额外 +3 生命并广播
        2 次 `stats_gained`（修复前实测副本 5/5 → 5/8 + 3 事件）。
        去掉抑制窗口时本用例转红。
        """
        g = make_game(seed=3215)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        mech = put(g, a, MECHAROO)
        # 真实 `Buff` Action（生产点）先于监听器接线 → 快照只含该附魔
        g.run_actions(BuffAction(mech, atk=3, health=3))
        put(g, a, STATS_LISTENER)
        seen: list = []
        g.events.register(Listener(
            event="stats_gained", owner=a,
            callback=lambda gg, **kw: seen.append(kw)))
        _kill_death_event(g, mech)                     # 真实死亡链
        copies = _copies(g, a, MECHAROO)
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual((copy.atk, copy.max_health), (5, 5),
                         "副本属性偏离快照（监听器对重放多触发了）")
        self.assertEqual([e for e in seen if e["minion"] is copy], [],
                         "副本重放被当成'获得'并触发了 stats_gained")

    def test_copy_restores_keywords(self):
        """精确副本复原死亡瞬间关键词（Cord Puller 的圣盾）。"""
        g = make_game(seed=3212)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        mech = put(g, a, OTHER_MECH)
        self.assertTrue(mech.has(GameTag.DIVINE_SHIELD))
        put(g, a, DUMMY)
        _kill_death_event(g, mech)
        copies = _copies(g, a, OTHER_MECH)
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].has(GameTag.DIVINE_SHIELD))

    def test_first_mech_died_order_not_first_death(self):
        """首死非 Mech → 取**第一只** Mech（死亡顺序过滤，不是首个死亡者）。"""
        g = make_game(seed=3213)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        beast = put(g, a, DUMMY)
        mech = put(g, a, MECHAROO)
        put(g, a, DUMMY)
        _kill_death_event(g, beast)          # 首死是 Beast → 不记录、不召唤
        self.assertEqual(g.combat_summon_log, [])
        _kill_death_event(g, mech)           # 第二死才是 Mech
        self.assertEqual(_copies(g, a, DUMMY), [])
        copies = _copies(g, a, MECHAROO)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].card_id, MECHAROO)

    def test_no_mech_died_no_summon(self):
        """负对照 + 正对照: 无 Mech 死亡不召唤; 随后 Mech 死亡即召唤。"""
        g = make_game(seed=3214)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        beast = put(g, a, DUMMY)
        mech = put(g, a, MECHAROO)
        _kill_death_event(g, beast)              # 非 Mech → 落空
        self.assertEqual(g.combat_summon_log, [])
        _kill_death_event(g, mech)               # 正对照: Mech → 副本
        self.assertEqual(len(_copies(g, a, MECHAROO)), 1)

    def test_once_per_combat(self):
        """每场至多 1 次: 第二只 Mech 死亡不再召唤。"""
        g = make_game(seed=3215)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        m1 = put(g, a, MECHAROO)
        m2 = put(g, a, OTHER_MECH)
        put(g, a, DUMMY)
        put(g, a, DUMMY)
        _kill_death_event(g, m1)
        self.assertEqual(len(_copies(g, a, MECHAROO)), 1)
        before = len(g.combat_summon_log)
        _kill_death_event(g, m2)
        # 第二只 Mech 死亡不产生副本（本卡闩已消费）
        self.assertEqual(_copies(g, a, OTHER_MECH), [])
        self.assertTrue(a.trinkets[0]._boom_controller_done)
        # 日志仅新增 m2 自身亡语召唤的 1 只 Microbot
        self.assertEqual(len(g.combat_summon_log), before + 1)
        self.assertEqual(g.combat_summon_log[-1].card_id, "BG_BOT_312t")

    def test_resets_next_combat(self):
        """跨战斗重置: 下一场战斗再次触发（每场一次）。"""
        g = make_game(seed=3216)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        m1 = put(g, a, MECHAROO)
        _kill_death_event(g, m1)
        self.assertEqual(len(_copies(g, a, MECHAROO)), 1)
        # 第二场: 真实 `run_combat`（对手空板 → 无死亡）→ `combat_restored`
        # 清闩/快照，本场账本从零
        g.run_combat(a, b)
        trinket = a.trinkets[0]
        self.assertFalse(trinket._boom_controller_done)
        self.assertFalse(trinket._boom_recorded)
        self.assertIsNone(trinket._boom_first_snap)
        self.assertEqual(g.combat_summon_log, [])
        m2 = put(g, a, MECHAROO)
        _kill_death_event(g, m2)
        self.assertEqual(len(_copies(g, a, MECHAROO)), 1)

    def test_opponent_board_space_does_not_trigger(self):
        """owner 隔离: 对手 Mech 死亡/腾位不召唤本人副本。"""
        g = make_game(seed=3217)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        theirs = put(g, b, MECHAROO)
        mine = put(g, a, MECHAROO)
        _kill_death_event(g, theirs)          # 对手 Mech 死亡（快照归 b）
        self.assertTrue(any(s["card_id"] == MECHAROO
                            for s in b._combat_dead_snaps))
        self.assertEqual(_copies(g, a, MECHAROO), [])
        _kill_death_event(g, mine)            # 自己 Mech 死亡才触发
        self.assertEqual(len(_copies(g, a, MECHAROO)), 1)

    def test_full_board_no_summon_then_positive_contrast(self):
        """棋盘在腾位瞬间被另一消费者填满 → `game.summon` 落空; 正对照成立。

        引擎**仅在** `len(hero.board) < BOARD_SIZE` 时广播
        `combat_slot_freed`（game.py:2194），故"满场落空"的唯一真实构造
        是另一消费者抢先占位（两个"when you have space"消费者竞争同一
        板位）——本测试以真实 `game.summon` 竞争者复现该竞争。
        """
        g = make_game(seed=3218)
        a, b = g.heroes
        fillers = []

        def refill(game, hero=None, **kw):
            if hero is not a:
                return
            m = game.create_minion(DUMMY, controller=a)
            if game.summon(a, m):
                fillers.append(m)

        self._fresh_combat(g, a, b)
        # 竞争者在**本卡监听器之前**注册（EventBus 按注册顺序派发）
        g.events.register(Listener(event=B32.COMBAT_SLOT_FREED,
                                   owner="test-refill", callback=refill))
        bind(g, a, self.TID)
        mech = put(g, a, MECHAROO)
        for _ in range(6):
            put(g, a, DUMMY)
        self.assertTrue(a.board_full())
        _kill_death_event(g, mech)            # 腾位 → 竞争者先填满
        self.assertEqual(len(fillers), 1)     # 竞争者确实占位
        self.assertEqual(_copies(g, a, MECHAROO), [])   # 本卡落空
        self.assertFalse(a.trinkets[0]._boom_controller_done)  # 闩未消费
        g.events.unregister_owner("test-refill")

        # 正对照: 无竞争者时同路径确实召唤
        g2 = make_game(seed=3218)
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        self._fresh_combat(g2, a2, b2)
        mech2 = put(g2, a2, MECHAROO)
        for _ in range(6):
            put(g2, a2, DUMMY)
        _kill_death_event(g2, mech2)
        self.assertEqual(len(_copies(g2, a2, MECHAROO)), 1)

    def test_deterministic_same_seed(self):
        """同 seed 确定性。"""
        seen = []
        for _ in range(2):
            g = make_game(seed=3219)
            a, b = g.heroes
            bind(g, a, self.TID)
            self._fresh_combat(g, a, b)
            mech = put(g, a, MECHAROO)
            put(g, a, DUMMY)
            _kill_death_event(g, mech)
            seen.append([(m.card_id, m.atk, m.max_health)
                         for m in _copies(g, a, MECHAROO)])
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(len(seen[0]), 1)


# ══════════════ BG30_MagicItem_822 Twin Sky Lanterns ══════════════


class TestTwinSkyLanterns(unittest.TestCase):
    TID = LANTERNS

    @staticmethod
    def _fresh_combat(g: Game, a: Hero, b: Hero) -> None:
        """真实 `run_combat`（空板）完成引擎每场重置（同 440 口径）。"""
        g.run_combat(a, b)
        assert g.combat_summon_log == []

    def test_first_summoned_minion_is_copied(self):
        """真实战斗内首只召唤体的副本（属性按入场态快照复原）。"""
        g = make_game(seed=3220)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        first = _combat_summon(g, a, OTHER_MECH)   # 本场首只召唤（被记录）
        _combat_summon(g, a, DUMMY)
        snap_atk, snap_hp = first.atk, first.max_health
        _kill_death_event(g, first)                # 腾位
        copies = _copies(g, a, OTHER_MECH, exclude=first)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].card_id, OTHER_MECH)
        self.assertEqual(copies[0].atk, snap_atk)
        self.assertEqual(copies[0].max_health, snap_hp)

    def test_copy_excludes_aura_not_double_counted(self):
        """对抗验证 MAJOR（2026-09-13）: 召唤瞬间快照同样**不含光环**。"""
        from hsrl2.actions.racefx import ApplyRaceAura
        g = make_game(seed=3227)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        g.run_actions([ApplyRaceAura(a, Race.MECH, 2, 2)])
        first = _combat_summon(g, a, OTHER_MECH)
        _combat_summon(g, a, DUMMY)
        snap = (first.atk, first.max_health)
        self.assertEqual(snap, (get_db().get(OTHER_MECH).atk + 2,
                                get_db().get(OTHER_MECH).health + 2))
        _kill_death_event(g, first)
        copies = _copies(g, a, OTHER_MECH, exclude=first)
        self.assertEqual(len(copies), 1)
        self.assertEqual((copies[0].atk, copies[0].max_health), snap,
                         "光环双计（副本烘入光环后又重算一次）")

    def test_copy_of_snapshot_not_live_state(self):
        """副本按**召唤瞬间**快照复原（记录后 buff 不回流副本）。"""
        g = make_game(seed=3221)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        first = _combat_summon(g, a, OTHER_MECH)
        _combat_summon(g, a, DUMMY)
        snap_atk, snap_hp = first.atk, first.max_health
        first.add_buff(EntityBuff(atk=5, health=5))   # 记录后 buff
        _kill_death_event(g, first)
        copies = _copies(g, a, OTHER_MECH, exclude=first)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].atk, snap_atk)
        self.assertEqual(copies[0].max_health, snap_hp)

    def test_once_per_combat(self):
        """每场至多 1 次副本（后续腾位不再召唤）。"""
        g = make_game(seed=3222)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        first = _combat_summon(g, a, OTHER_MECH)
        d1 = _combat_summon(g, a, DUMMY)
        d2 = _combat_summon(g, a, DUMMY)
        _kill_death_event(g, d1)
        self.assertEqual(len(_copies(g, a, OTHER_MECH, exclude=first)), 1)
        _kill_death_event(g, d2)
        self.assertEqual(len(_copies(g, a, OTHER_MECH, exclude=first)), 1)
        self.assertTrue(a.trinkets[0]._lantern_done)

    def test_resets_next_combat(self):
        """跨战斗重置: 第二场真实 `run_combat` 的 `combat_restored` 清零。"""
        g = make_game(seed=3223)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        first = _combat_summon(g, a, OTHER_MECH)
        _combat_summon(g, a, DUMMY)
        _kill_death_event(g, first)
        self.assertEqual(len(_copies(g, a, OTHER_MECH, exclude=first)), 1)
        # 第二场: 真实 `run_combat`（对手空板 → 无死亡/召唤）→ 清零
        g.run_combat(a, b)
        trinket = a.trinkets[0]
        self.assertFalse(trinket._lantern_recorded)
        self.assertIsNone(trinket._lantern_first_snap)
        self.assertFalse(trinket._lantern_done)
        self.assertEqual(g.combat_summon_log, [])
        # 第二场首召唤物 = 新 Mech（再次记录 + 腾位时召唤）
        new_first = _combat_summon(g, a, MECHAROO)
        _combat_summon(g, a, DUMMY)
        _kill_death_event(g, new_first)
        self.assertEqual(len(_copies(g, a, MECHAROO,
                                     exclude=new_first)), 1)
        self.assertEqual(_copies(g, a, OTHER_MECH), [])

    def test_opponent_summon_not_recorded(self):
        """owner 隔离: 对手召唤不记录 → 自己腾位时不召唤。"""
        g = make_game(seed=3224)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        theirs = _combat_summon(g, b, OTHER_MECH)   # 对手召唤
        mine = _combat_summon(g, a, DUMMY)          # 本人首召唤（记录）
        _kill_death_event(g, mine)
        # 本人副本只能是"自己的首召唤物"（DUMMY），绝不是对手的 Mech
        self.assertEqual(_copies(g, a, OTHER_MECH), [])
        self.assertEqual(len(_copies(g, a, DUMMY, exclude=mine)), 1)
        self.assertIn(theirs, g.combat_summon_log)

    def test_no_record_fizzles(self):
        """本场无召唤记录 → 腾位落空（负对照）。"""
        g = make_game(seed=3225)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        # 招募期入板（`in_combat=False` → 不入日志、本卡不记录）
        mine = put(g, a, DUMMY)
        self.assertFalse(a.trinkets[0]._lantern_recorded)
        _kill_death_event(g, mine)
        self.assertEqual(g.combat_summon_log, [])

    def test_no_trinket_no_copy(self):
        """负对照 + 正对照: 未绑定不产生副本; 绑定后同 setup 产生副本。"""
        g = make_game(seed=3226)
        a, b = g.heroes
        self._fresh_combat(g, a, b)
        d1 = _combat_summon(g, a, DUMMY)
        _kill_death_event(g, d1)
        self.assertEqual(g.combat_summon_log, [d1])     # 未绑定 → 仅本体
        # 正对照: 同 seed 同 setup，绑定后首召唤物被复制
        g2 = make_game(seed=3226)
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        self._fresh_combat(g2, a2, b2)
        f2 = _combat_summon(g2, a2, DUMMY)
        _kill_death_event(g2, f2)
        self.assertEqual(len(_copies(g2, a2, DUMMY, exclude=f2)), 1)

    def test_full_board_no_summon(self):
        """腾位瞬间被另一消费者填满 → `game.summon` 落空（同 440 口径）。"""
        g = make_game(seed=3227)
        a, b = g.heroes
        fillers = []

        def refill(game, hero=None, **kw):
            if hero is not a:
                return
            m = game.create_minion(DUMMY, controller=a)
            if game.summon(a, m):
                fillers.append(m)

        self._fresh_combat(g, a, b)
        # 竞争者在**本卡监听器之前**注册（EventBus 按注册顺序派发）
        g.events.register(Listener(event=B32.COMBAT_SLOT_FREED,
                                   owner="test-refill", callback=refill))
        bind(g, a, self.TID)
        first = _combat_summon(g, a, OTHER_MECH)    # 本场首召唤（记录）
        for _ in range(6):
            _combat_summon(g, a, DUMMY)
        self.assertTrue(a.board_full())
        _kill_death_event(g, first)                 # 腾位 → 竞争者先填满
        self.assertEqual(len(fillers), 1)
        self.assertEqual(_copies(g, a, OTHER_MECH, exclude=first), [])
        self.assertFalse(a.trinkets[0]._lantern_done)
        g.events.unregister_owner("test-refill")

    def test_positive_contrast_when_space_exists(self):
        """正对照: 无竞争者、存在空位时，首召唤物的副本确实出现。"""
        g = make_game(seed=3227)
        a, b = g.heroes
        bind(g, a, self.TID)
        self._fresh_combat(g, a, b)
        first = _combat_summon(g, a, OTHER_MECH)
        _combat_summon(g, a, DUMMY)
        _kill_death_event(g, first)
        copies = _copies(g, a, OTHER_MECH, exclude=first)
        self.assertEqual(len(copies), 1)
        self.assertTrue(a.trinkets[0]._lantern_done)

    def test_deterministic_same_seed(self):
        """同 seed 确定性。"""
        seen = []
        for _ in range(2):
            g = make_game(seed=3228)
            a, b = g.heroes
            bind(g, a, self.TID)
            self._fresh_combat(g, a, b)
            first = _combat_summon(g, a, OTHER_MECH)
            _combat_summon(g, a, DUMMY)
            _kill_death_event(g, first)
            seen.append([(m.card_id, m.atk, m.max_health)
                         for m in _copies(g, a, OTHER_MECH,
                                          exclude=first)])
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(len(seen[0]), 1)


# ══════════════ 注册表 / 数据守卫（结构性） ══════════════


class TestBatch32Ledger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 数据 / 数值 / 二态铁律（与钩子无关）。"""

    IDS = (WISHBONE, BOOM, LANTERNS)

    def test_registry_auto_discovered(self):
        """本批由 `hsrl2/scripts/batches` 自动发现并在导入时注册 3 个 id。"""
        self.assertEqual(len(self.IDS), 3)
        self.assertTrue(callable(B32.register))
        for tid in self.IDS:
            self.assertIn(tid, REGISTRY, tid)

    def test_all_ids_registered_to_own_classes(self):
        expected = {
            WISHBONE: "AncientWishboneScript",
            BOOM: "BoomControllerScript",
            LANTERNS: "TwinSkyLanternsScript",
        }
        for tid, cls_name in expected.items():
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B32, cls_name), tid)

    def test_all_ids_exist_as_bacon_trinkets(self):
        db = get_db()
        for tid in self.IDS:
            d = db.get(tid)
            self.assertIsNotNone(d, tid)
            self.assertEqual(d.card_type, 44, tid)          # BACON_TRINKET
            self.assertIn(d.spell_school, (11, 12), tid)

    def test_offer_pool_membership(self):
        db = get_db()
        offer = {d.id for d in db.trinket_offer_pool()}
        for tid in self.IDS:
            self.assertIn(tid, offer, tid)

    def test_carddef_num_params_pinned(self):
        """数值纪律: 3 张的 num(0..4) 逐位钉死（文本无占位符）。"""
        db = get_db()
        expected = {
            WISHBONE: (None, None, None, None, None),
            BOOM: (None, 99, None, None, None),
            LANTERNS: (None, 1, None, None, None),
        }
        for tid, exp in expected.items():
            self.assertEqual(tuple(db.get(tid).num(i) for i in range(5)),
                             exp, tid)

    def test_no_card_definition_evolution_link(self):
        db = get_db()
        for tid in self.IDS:
            self.assertIsNone(db.get(tid).evolution_card_id, tid)

    def test_carddef_text_matches_docstring(self):
        """卡面文本漂移守卫（签名同时存在于 CardDef.text 与 docstring）。"""
        db = get_db()
        signatures = {
            WISHBONE: "your hero power triggers twice",
            BOOM: "summon an exact copy of your first mech that died "
                  "each combat",
            LANTERNS: "summon a copy of the first minion you summon "
                      "each combat",
        }
        classes = {
            WISHBONE: B32.AncientWishboneScript,
            BOOM: B32.BoomControllerScript,
            LANTERNS: B32.TwinSkyLanternsScript,
        }
        for tid, frag in signatures.items():
            text = _norm(db.get(tid).text)
            doc = _norm(classes[tid].__doc__ or "")
            self.assertIn(frag, text, tid)
            self.assertIn(frag, doc, tid)

    def test_no_deferred_state_in_batch(self):
        """二态铁律: 本批 0 DEFERRED，`register()` 不返回空、类都有钩子。"""
        self.assertIn("DEFERRED 0 张", B32.__doc__ or "")
        self.assertTrue(hasattr(B32.AncientWishboneScript, "on_bind"))
        self.assertTrue(hasattr(B32.BoomControllerScript, "on_bind"))
        self.assertTrue(hasattr(B32.TwinSkyLanternsScript, "on_bind"))
        for tid in self.IDS:
            self.assertNotIn("Status: DEFERRED",
                             (REGISTRY[tid].__doc__ or ""))


def _norm(s: str) -> str:
    """归一化（去 markup / 空白 / 大小写）——文本漂移守卫用。"""
    import re
    s = re.sub(r"\[x\]|<b>|</b>|<i>|</i>", "", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


if __name__ == "__main__":
    unittest.main()
