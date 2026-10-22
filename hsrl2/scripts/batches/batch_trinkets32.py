"""批次 trinkets32 — "新引擎原语解锁"复评批（作业单 2026-09-15，3 张）。

台账来源: 派发作业单给定的 3 个 id（`docs/agents/ENGINE_BACKLOG.md` §B3
F 组"引擎原语缺失"残项）。3/3 在 `CardDB` 存在、3/3 在
`CardDB.trinket_offer_pool()` 中（运行核验——商店可提供成员），且在本批
之前 3/3 全部**不在** `REGISTRY`（与既有 batch_trinkets1..31 /
batch_unlock_final / batch_misc_final 注册集合互不相交，运行核验）。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码; 本批 3 张文本
**均无**数值占位符——`BG30_MagicItem_804` num(0..4) 全 None;
`BG30_MagicItem_440` 只有 num(1)=99、`BG30_MagicItem_822` 只有 num(1)=1
（内部 `script_data_num_2` 计数参数，**非文本占位符**，卡面一字不含
"99"/"1"）——按 SOP §3 在各类 `Params:` 行显式声明并给出数据核实）;
关联卡: 3 张 `evolution_card_id` 均为空（36.2.2 数据核实），无交付条款;
随机: 本批 3 张均无随机（禁 `import random`）; 状态写在 hero 级 tag /
source 实体属性（无 game 级 flag——SOP §12 item 9）。

**新引擎原语逐条核对（2026-09-02 闭环项，RULES §3.5/§6.20/§7.4.10b）**
═══════════════════════════════════════════════════════════════════════
  | 原语（生产点） | 本批消费卡 | 核验结论 |
  |----------------|-----------|---------|
  | `hero.extra_triggers["hp_times"]`（消费点 `game.py::_finish_hero_power`
    L1823 `times = 1 + hero.extra_trigger("hp_times")`，循环 N+1 次调用
    `script.hero_power`） | 804 | 与 `hp_uses`（"多使用几次"——每回合
    次数上限）**独立**: 一次 `use_hero_power` 内效果结算 N+1 次;
    额度是 hero 级永久声明（`extra_triggers` 不带回合/战斗清零） |
  | `events.fire(self, "combat_slot_freed", hero=hero)`（`game.py::
    _process_death_inner` L2195——战斗内**友方随从离场**（已从棋盘移除、
    让出板位）且 `len(hero.board) < BOARD_SIZE` 时广播; 每次死亡至多一次） | 440 / 822 | 有界触发点（**非** AFTER_ATTACK 循环补位——SOP §13
    item 3 禁止形态: Drek'Thar/Ozumat 曾致 2001 轮 `CombatLoopError`）;
    消费者自行保证每场至多 1 次 |
  | `hero._combat_dead_snaps`（`game.py::_process_death_inner` L2218——
    每英雄按**死亡顺序**的轻量快照，`run_combat` 开头 `= []` 清空;
    每项含 `card_id / golden / race / atk / max_health / keywords /
    buffs`） | 440 | 键集/语义已就绪（附魔面 = **独立** `Buff` 实例列表;
    关键词 = 死亡瞬间 `True` tag 元组），但**追加发生在
    `combat_slot_freed` 广播之后**（L2211-2234 晚于 L2195）——事件内读
    它仍是空表，故本批在 `death` 事件（离场前、实体可读）按同一键集
    自行快照（`_snapshot_of`），等价且时序正确 |
  | `game.combat_summon_log`（`game.py::summon` L1230 在 `in_combat`
    时 append; `run_combat` L2715 `= []` 清空） | 822 | 本场召唤顺序日志;
    本卡另注册 `summon`（events.py `SUMMON`）在**召唤瞬间**取快照，
    不事后读日志（首召唤物可能在腾位前已死——快照须是入场态） |

**CORRECT 3 项（注册 3 个 id）**
═══════════════════════════════════════════════════════════════════════
  BG30_MagicItem_804 Ancient Wishbone (Lesser, school=11) —
      "Your Hero Power triggers twice." on_bind 写
      `hero.extra_triggers["hp_times"] = 1`（永久额度; 引擎
      `_finish_hero_power` 按 `1 + hp_times` 结算）——一次
      `use_hero_power` 内技能脚本被调用 **2** 次。

  BG30_MagicItem_440 Boom Controller (Greater, school=12) —
      "[x]When you have space, summon an exact copy of your first Mech
      that died each combat." on_bind 注册 `combat_slot_freed` 持久监听
      （owner=饰品）: 本人棋盘腾位且**本场尚未召唤过**（实例级 once 闩）
      时，取 `death` 事件内记录的**第一只** race ∈ {MECH, ALL} 快照 →
      `create_minion(card_id, golden=)` + `BASE_ATK/BASE_HEALTH =
      快照最终值 − Σ附魔` + 附魔以**独立** `Buff` 实例重放 + 快照关键词
      复原 → `game.summon`。每场至多 1 次（有界）。

  BG30_MagicItem_822 Twin Sky Lanterns (Greater, school=12) —
      "[x]When you have space, summon a copy of the first minion you
      summon each combat." on_bind 注册 `summon` 持久监听
      （`minion.controller is 本人`）**在召唤瞬间**快照**本场第一只被
      召唤的随从**; 每场结束（`combat_restored`）重置闩 + 清空记录;
      `combat_slot_freed` 时（本人棋盘腾位且本场尚未召唤过）按其快照
      召唤一份副本（同样是"copy"——与 440 的"exact copy"同构复原）。
      **排除自身触发的副本**（本卡召唤的副本也广播 `summon`——若不加
      闩会自我引用无界，SOP §13 item 3）。

**DEFERRED 0 张**（本批 3 张全部 CORRECT; 无台账守卫缺口）

关联卡台账（RULES §7.4.6）
═══════════════════════════════════════════════════════════════════════
  3 张的 `evolution_card_id` 均为空、无 "Get a X" 条款 → 无关联卡。

测试: `hsrl2/tests/test_batch_trinkets32.py`（行为层: 真实
`use_hero_power` 结算 / 真实 `game.run_combat` + 真实死亡链
`_process_single_death` / 负对照+正对照 / owner 隔离 / 每场一次 /
腾位瞬间被另一消费者填满 → 落空 / 跨战斗重置 / 同 seed 确定性;
结构性台账守卫按 TEST_SOP 标 `@engine-only`）。
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from hsrl2.entity import Buff as EntityBuff, suppress_stats_gained
from hsrl2.events import DEATH, Listener, SUMMON
from hsrl2.game import GameStateError
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.minion import Minion

# ── 卡 id（CardDB 按名核实——禁止凭记忆写 id） ──
ANCIENT_WISHBONE = "BG30_MagicItem_804"
BOOM_CONTROLLER = "BG30_MagicItem_440"
TWIN_SKY_LANTERNS = "BG30_MagicItem_822"

# 机械资格集（融合怪 Race.ALL 视为属于全部类型——RULES §8/§6.19 既有口径）
_MECH_RACES = (Race.MECH, Race.ALL)

# `combat_slot_freed` 尚无 events.py 常量（引擎以字面量广播——
# `game.py::_process_death_inner`; 全仓既有消费脚本一律用字面量）
COMBAT_SLOT_FREED = "combat_slot_freed"
# `combat_restored` 亦为引擎字面量事件（`run_combat` finally 内、
# 棋盘快照还原后; batch_trinkets30/31 先例）
COMBAT_RESTORED = "combat_restored"


def _hero(ctx) -> Optional["Hero"]:
    """on_bind ctx → 饰品持有英雄（引擎 grant_trinket 传 ctx={"hero": h}）。"""
    return (ctx or {}).get("hero")


def _controller(source) -> Optional["Hero"]:
    """source 实体的控制者（ctx 缺失时的回落——见 `_bind_hero`）。"""
    return getattr(source, "controller", None)


def _bind_hero(source, ctx) -> Optional["Hero"]:
    """绑定者 = `ctx["hero"]`，缺失时回落 `source.controller`。

    回调内**不得**读 `source.controller` 判归属: 饰品实体不随战斗快照
    换 controller，但 owner 隔离测试会以 `_h` 默认参数钉死绑定者
    （SOP §11 item 1 闭包晚绑定纪律）。
    """
    h = _hero(ctx)
    if h is None:
        h = _controller(source)
    return h


def _restore_from_snapshot(game: "Game", hero: "Hero",
                           snap: dict) -> Optional["Minion"]:
    """按死亡/召唤瞬间的轻量快照**精确复原**一份副本并召唤。

    顺序（与 `batch_unlock_final._summon_from_snapshot` 同口径 + 附魔面）:
      1. `create_minion(snap.card_id, controller=hero, golden=snap.golden)`
         —— 金色是独立卡定义（RULES §2.3），`golden=True` 走
         `db.golden_version` 并由 `create_minion` 打
         `TRIPLE_BASE_CARD_ID`/`GOLDEN`
      2. `BASE_ATK/BASE_HEALTH = 快照最终值 − Σ附魔`（第 3 步会以独立
         实例重放附魔，故基础值须**扣除**附魔——否则附魔被计两次;
         快照属性 = 死亡/召唤瞬间的最终值; `max_health` 属性而非当前
         `health`——SOP §3。战斗内光环由 `_aura_atk/_aura_health` 对
         新实体实时重算，故**不**烘入基础值——避免光环双计）
      3. `buffs` 逐项以**新 Buff 实例**复原（`Entity.copy_buffs_to` 的
         逐项 `add_buff` 新构造等价物——禁止共享可变 `_buffs` 对象，
         SOP §16b item 20）; 整段置于 `suppress_stats_gained()` 窗口内
         （**复制不是"获得"**——否则副本封装的附魔会伪造 `stats_gained`
         并对该族监听器触发; ENGINE_BACKLOG §E2 #4）
      4. 快照关键词（死亡瞬间的 `True` tag）逐项复原
      5. `game.summon`（满场 → `minion_overflow` 落空并返回 False，
         调用方不消耗闩）

    战斗召唤不入池（token/副本零池操作——RULES §2.3；
    `_process_death_inner` 的 `minion_pool.release_minion_entity` 只对
    `not in_combat` 生效）。
    """
    m = game.create_minion(snap["card_id"], controller=hero,
                           golden=bool(snap.get("golden")))
    if m is None:
        return None
    buffs = tuple(snap.get("buffs", ()))
    m.set(GameTag.BASE_ATK,
          snap["atk"] - sum(b.atk for b in buffs))
    m.set(GameTag.BASE_HEALTH,
          snap["max_health"] - sum(b.health for b in buffs))
    for tag in snap.get("keywords", ()):
        if tag != GameTag.DEAD:            # 状态 tag 一律不复原
            m.set(tag, True)
    m.clear(GameTag.DEAD)                  # 副本必须存活（BUG-440）
    # 附魔重放 = **复制**（非"获得"，ENGINE_BACKLOG §E2 #4）→ 整段置于
    # `suppress_stats_gained()` 抑制窗口内: 否则副本封装的附魔会对
    # "每当……获得攻击力"类监听器（如 BG34_Giant_064）伪造一次真实获得
    # （2026-09-20 对抗验证实测: 棋盘上有监听器时副本 4→10 生命）。
    # 与 `Entity.copy_buffs_to` 同口径（该方法内部亦用同一抑制窗口）。
    with suppress_stats_gained():
        for buff in buffs:
            m.add_buff(EntityBuff(atk=buff.atk, health=buff.health,
                                  temporary=buff.temporary,
                                  source_id=buff.source_id,
                                  dark_gift=buff.dark_gift, gem=buff.gem))
    if not game.summon(hero, m):
        return None
    return m


def _snapshot_of(m: "Minion") -> dict:
    """某实体**当前瞬间**的轻量快照（822 的首召唤物入场态）。

    与引擎 `hero._combat_dead_snaps` 的键集一致（`card_id / golden /
    race / atk / max_health / keywords / buffs`）——`buffs` 是**新构造**
    的独立 `Buff` 实例（不得共享被快照实体的 `_buffs` 对象）。

    属性口径 = `stats_without_aura()`（base + 附魔，**不含光环**）——
    `_restore_from_snapshot` 会把快照值写回 BASE_ATK/HEALTH 并重放附魔，
    光环由新实体在棋盘上实时重算; 记录 `m.atk`（含光环）会双计
    （2026-09-13 对抗验证 MAJOR）。
    """
    _atk, _health = m.stats_without_aura()
    return {
        "card_id": m.card_id,
        "golden": bool(m.is_golden),
        "race": m.race,
        "atk": _atk,
        "max_health": _health,
        # 关键词**白名单**（引擎 helper；不含 DEAD 等状态 tag——BUG-440）
        "keywords": (tuple(m.game.keyword_tags_of(m))
                     if getattr(m, "game", None) is not None
                     else tuple(t for t, v in m.tags.items() if v is True)),
        "buffs": [EntityBuff(atk=b.atk, health=b.health,
                             temporary=b.temporary,
                             source_id=b.source_id,
                             dark_gift=b.dark_gift, gem=b.gem)
                  for b in m._buffs],
    }


# ══════════════ BG30_MagicItem_804 Ancient Wishbone ══════════════


class AncientWishboneScript:
    """
    Natural language: Your Hero Power triggers twice.

    Formal spec:
      1. on_bind: `hero.extra_triggers["hp_times"] = 1`（hero 级永久
         额度; 引擎 `_finish_hero_power` 在**每次** `use_hero_power`
         结算处读 `1 + extra_trigger("hp_times")` → 技能脚本被调用
         2 次）
      2. 与 `hp_uses`（"多使用几次"——`use_hero_power` 的每回合次数
         上限）**独立**: 一次使用内效果结算两次，而使用次数仍为 1
      3. 只写绑定者（`ctx["hero"]`）——对手技能不受影响（owner 隔离）
      4. 幂等: 已达 1 不再累加（同一饰品两份副本不得把总额度抬到 2）
      5. **生命周期**: 本卡文本是**常驻被动**（无触发时机/持续时间），
         且引擎的饰品替换路径（`copy_trinket(replace=)` /
         `replace_trinket`）只在**替换发生的那一刻**注销监听器——
         它不提供"饰品离场"回调，`extra_triggers` 也无清除点。因此
         额度按 hero 级 tag 语义**在本局剩余时间内保持**（玩家主动
         替换掉本饰品后额度仍生效）——与 `hp_uses` 类同族配额的
         hero 级生命周期一致。此为该族的引擎既定口径（RULES §6.20:
         `extra_triggers` = 永久额度，只有每回合/每场战斗的**已用
         次数** `extra_trigger_used` 会重置）; 若主线日后补"饰品离场"
         钩子，应在此清 `hp_times`（实现路径见下）。

    Test: test_batch_trinkets32.py — 真实 `use_hero_power`（探针技能
      脚本计数）绑定后一次使用结算 2 次 / 负对照（未绑定）1 次 /
      对手技能仍 1 次 / 两份副本不叠加（仍 2 次）/ 同 seed 确定性

    Params: 无模板参数（`BG30_MagicItem_804` num(0..4) 全 None——
            36.2.2 数据核实; 文本无占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _bind_hero(source, ctx)
        if hero is None:
            raise GameStateError("Ancient Wishbone: no binding hero")
        # 幂等（两份副本不叠加; 旧值已 ≥1 保持不动）
        hero.extra_triggers["hp_times"] = max(
            1, int(hero.extra_triggers.get("hp_times", 0) or 0))
        return None


# ══════════════ BG30_MagicItem_440 Boom Controller ══════════════


class BoomControllerScript:
    """
    Natural language: [x]When you have space,
    summon an exact copy
    of your first Mech that
    died each combat.

    Formal spec:
      1. on_bind 注册两个持久监听器（owner=饰品 → 替换即注销）:
         (a) `death`（`events.DEATH`——引擎在**离场之前**广播，此时实体
             仍可读）: `minion.controller is 绑定者` 且本场尚未记录过
             Mech 时，按**死亡瞬间**状态快照该实体
             （`_snapshot_of`）→ `source._boom_first_snap`。**必须**在此
             时点快照: 引擎的 `hero._combat_dead_snaps` 追加发生在
             `combat_slot_freed` 广播**之后**（后者在离场即广播），
             消费者若只读引擎快照会在事件内看到空列表。
         (b) `combat_slot_freed`: 引擎在**战斗内**本人随从离场且棋盘
             出现空位时广播（`_process_death_inner`; 每次死亡至多一次、
             **非** AFTER_ATTACK 无限补位——SOP §13 item 3）
      2. 回调守卫（全部命中才结算）:
         (a) `hero is 绑定者`（owner 隔离——对手棋盘腾位不触发）
         (b) 本场尚未召唤过（实例级闩 `source._boom_controller_done`）
         (c) `source._boom_first_snap` 存在（本场有 Mech 死亡）
      3. 候选 = **第一只**死亡的 Mech（`death` 顺序; ALL 融合怪视为
         机械，RULES §8）——记录闩在首次记录时置位（后续非 Mech 死亡
         不覆盖）
      4. 精确副本 = `create_minion(card_id, golden=快照 golden)`
         + `BASE_ATK/BASE_HEALTH = 快照最终值 − Σ附魔`（附魔下一步
         重放，须从基础值扣除——否则附魔双计）
         + `buffs` 独立实例复原 + 死亡瞬间关键词复原 → `game.summon`
         （"exact copy" 含附魔与关键词，RULES §7.4.10b/§16b item 20）
      5. **有界**: 每场至多 1 次（闩只在 `summon` 成功后置位——满场
         落空不消耗闩。引擎仅在 `len(board) < BOARD_SIZE` 时广播
         `combat_slot_freed`，故"满场落空"的真实来源是**另一
         "when you have space" 消费者抢先占位**——测试即以此构造）
      6. 每场重置: `combat_restored`（`run_combat` finally 内棋盘快照
         已还原后广播）清闩 + 清记录——下一场战斗可再触发一次;
         招募期死亡不广播 `combat_slot_freed`，天然不触发
      7. 无 Mech 死亡 → 落空（正对照: 有 Mech 死亡时确实召唤）

    Test: test_batch_trinkets32.py — 真实 `game.run_combat` 内真实死亡链
      （`_process_single_death`）: 首只死亡 Mech → 腾位事件内召唤出
      exact copy（card_id/golden/atk/max_health/关键词/独立 buff 逐一
      断言）/ 首死非 Mech 而后续有 Mech 死亡 → 仍取第一只 Mech /
      无 Mech 死亡 → 不召唤 / 每场至多一次 / 跨战斗再次触发且每场一次 /
      对手隔离 / 腾位瞬间被另一消费者填满 → 落空（正对照成立）/
      同 seed 确定性

    Params: 无模板参数（`script_data_num_2=99` 为内部计数参数，
            非文本占位符——卡面不含 "99"; num(0)/num(2..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _bind_hero(source, ctx)
        if hero is None:
            raise GameStateError("Boom Controller: no binding hero")
        source._boom_controller_done = False
        source._boom_first_snap = None
        source._boom_recorded = False

        def on_death(g, minion=None, _bind=hero, **kw):
            if minion is None or getattr(minion, "controller", None) is \
                    not _bind:
                return
            if getattr(source, "_boom_recorded", False):
                return
            if not g.in_combat:
                return
            if getattr(minion, "race", None) not in _MECH_RACES:
                return
            source._boom_first_snap = _snapshot_of(minion)
            source._boom_recorded = True

        def on_slot_freed(g, hero=None, _bind=hero, **kw):
            if hero is not _bind:
                return
            if getattr(source, "_boom_controller_done", False):
                return
            snap = getattr(source, "_boom_first_snap", None)
            if snap is None:
                return
            if _restore_from_snapshot(g, _bind, snap) is None:
                return
            source._boom_controller_done = True

        def on_combat_restored(g, hero_a=None, hero_b=None, _bind=hero,
                               **kw):
            if _bind is hero_a or _bind is hero_b:
                source._boom_controller_done = False
                source._boom_first_snap = None
                source._boom_recorded = False

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        game.events.register(Listener(event=COMBAT_SLOT_FREED,
                                      owner=source, callback=on_slot_freed))
        game.events.register(Listener(event=COMBAT_RESTORED, owner=source,
                                      callback=on_combat_restored))
        return None


# ══════════════ BG30_MagicItem_822 Twin Sky Lanterns ══════════════


class TwinSkyLanternsScript:
    """
    Natural language: [x]When you have space,
    summon a copy of the
    first minion you summon
    each combat.

    Formal spec:
      1. on_bind 注册持久监听 `summon`（owner=饰品）: `minion.controller
         is 绑定者` 且**本场尚未记录过**时，按**召唤瞬间**的实体状态
         构建轻量快照（`_snapshot_of`——禁事后读 `combat_summon_log`
         再取快照: 首召唤物可能在腾位前已死/被 buff，入场态才是权威）
         → `source._lantern_first_snap`; 闩 `source._lantern_recorded`
         **在记录时**置位（本卡自己召唤的副本也广播 `summon`——不加闩
         会自我引用无界，SOP §13 item 3）
      2. `combat_restored`（`run_combat` finally 内、棋盘快照已还原后
         广播；`START_OF_COMBAT` 在战斗中不会重跑，本事件与"每场"生命
         周期一致）: 清记录闩 + 快照 + 副本闩（每场重新记录"第一只"）
      3. `combat_slot_freed`: 本人棋盘腾位且本场**尚未召唤过**副本
         （实例级闩 `source._lantern_done`）且已有记录 → 按快照复原
         一份副本并 `game.summon`（同 440 的精确复原通道）
      4. **有界**: 每场至多 1 次副本（`_lantern_done`）; 记录也只一次
      5. `on_summon` 只记录**战斗内**召唤（"each combat" 的权威口径 =
         战斗阶段; 招募期 `summon` 不入日志、也不构成本场"召唤"）
      6. 对手召唤不记录（owner 隔离）
      7. 记录在 `combat_restored` 清零（本场结束）——跨场不残留

    Test: test_batch_trinkets32.py — 真实 `game.run_combat`: 本场首只
      召唤物在腾位时被复制（入场态属性/buff 独立实例复原）/ 首只召唤
      物为对手者不记录 / 每场至多一次（后续腾位不再召唤）/ 跨战斗重置
      （下一场记录新首召唤物）/ 无召唤记录 → 腾位落空 /
      腾位瞬间被另一消费者填满 → 落空（正对照成立）/ 同 seed 确定性

    Params: 无模板参数（`script_data_num_2=1` 为内部计数参数，非文本
            占位符——卡面不含 "1" 数值; num(0)/num(2..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _bind_hero(source, ctx)
        if hero is None:
            raise GameStateError("Twin Sky Lanterns: no binding hero")
        source._lantern_recorded = False
        source._lantern_first_snap = None
        source._lantern_done = False

        def on_summon(g, minion=None, _bind=hero, **kw):
            if minion is None or getattr(minion, "controller", None) is \
                    not _bind:
                return
            if getattr(source, "_lantern_recorded", False):
                return
            if not g.in_combat:
                return
            source._lantern_first_snap = _snapshot_of(minion)
            source._lantern_recorded = True

        def on_slot_freed(g, hero=None, _bind=hero, **kw):
            if hero is not _bind:
                return
            if getattr(source, "_lantern_done", False):
                return
            snap = getattr(source, "_lantern_first_snap", None)
            if snap is None:
                return
            if _restore_from_snapshot(g, _bind, snap) is None:
                return
            source._lantern_done = True

        def on_combat_restored(g, hero_a=None, hero_b=None, _bind=hero,
                               **kw):
            if _bind is hero_a or _bind is hero_b:
                source._lantern_recorded = False
                source._lantern_first_snap = None
                source._lantern_done = False

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summon))
        game.events.register(Listener(event=COMBAT_SLOT_FREED,
                                      owner=source, callback=on_slot_freed))
        game.events.register(Listener(event=COMBAT_RESTORED, owner=source,
                                      callback=on_combat_restored))
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 32 批 3 张（全部 CORRECT，0 DEFERRED）。

    SOP §6b 二态铁律: 本批无第三态。
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (ANCIENT_WISHBONE, AncientWishboneScript),
        (BOOM_CONTROLLER, BoomControllerScript),
        (TWIN_SKY_LANTERNS, TwinSkyLanternsScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
