"""批次 37x_combatgap — 37.0 当前池内「combat 相关但缺脚本」的 7 张卡。

背景
═══════════════════════════════════════════════════════════════════════
差分 harness（679 场官方 BG 战斗）在上一批（37x_missing1 + 37x_poolgap1）
后仍有 `missing_script` 归因。本批补齐其中**当前轮换池内**、直接影响
战斗数值/差分精度的 7 张（全部 `db.pool_minions()` 内、`IS_BACON_POOL_MINION=1`）：

  BG36_102 / _G      De-volition-ist（T5 4/8 Aberration）
      After this attacks, deal damage equal to this minion's Attack to the
      highest-Health enemy minion.（金色文本: "equal to **double** this
      minion's Attack"）
  BG36_848 / _G      Lichling Hoarder（T5 6/9 Undead）
      Avenge (3): Get a plain copy of a minion that started in your warband
      this combat.（金色: **2** plain copies）
  BG36_364 / _G      Hopebringer（T5 4/3 Dragon）
      Start of Combat: Give your minions +4/+3.（金色 +8/+6）
      (Permanently improves after a friendly minion loses Divine Shield!)
  BGS_040 / TB_BaconUps_154　Nadina the Red（T6 8/4，无类型）
      Deathrattle: Give 3 friendly Dragons Divine Shield.（金色 **6**）
  BGS_008 / TB_BaconUps_057　Ghastcoiler（T5 7/7 Beast）
      Deathrattle: Summon 2 random Deathrattle minions.（金色 **4**）
  BG31_810 / _G      Ultraviolet Ascendant（T6 6/6 Elemental）
      Start of Combat: Give your other Elementals +3/+3.（金色 +6/+6）
      (Improves after you play an Elemental!)
  BG33_828 / _G      Ship Master Eudora（T5 8/3 Pirate）
      Deathrattle: Give your minions +6/+6. Golden ones keep it permanently.
      （金色文本 "... +{0}/{1} **twice**" = 6/6 两次）

数值/语义权威（按 EFFECT_SCRIPT_SOP §17 权威序）
═══════════════════════════════════════════════════════════════════
- **CardDef.num() 是数值唯一来源**（37.0.0.255130 官方数据，含金色独立
  CardDef 的数值；金色倍率由金色 CardDef 自然体现，脚本只对**行为差异**
  ——"double"/"twice"/"2 copies"/"6 Dragons"——分支）。
- 本地官方 CardDefs（`reversed/data_255130_input/CardDefs.merged.xml`）
  的多语言 `CARDTEXT` 用于消歧:
  * De-volition-ist: deDE "dem feindlichen Diener mit dem **höchsten
    Leben**" / jaJP "最も**体力**が高い" → "highest-Health" = **当前生命**
    （与 SOP §16b #23 一致），不是最大生命; 并列时 `game.rng.choice`
    （无官方 Notes，自然语言解读: 随机其一）。
  * Lichling Hoarder: frFR "une **copie non dorée**" / jaJP "**未強化通常
    コピー**" / koKR "**강화 효과가 없는 일반 하수인**" → plain copy =
    **无附魔、非金色**的原始卡副本（金色原件也给非金色副本）；"Get" =
    进手牌（满手走 `pending_hand_add` 等待队列）。
  * Ship Master Eudora: deDE "**Goldene Diener** behalten dies dauerhaft" /
    zhCN "**金色随从**可永久保留此效果" → "Golden ones" = **金色随从**
    （不是金色 Eudora）：普通随从的 +6/+6 只在本场战斗内（快照回滚），
    金色随从通过 `Buff(persist=True)` 跨战斗保留。
  * Nadina the Red: 金色文本硬编码 "Give **6** friendly Dragons"
    （CardDef 无模板参数）→ 行为分支 3/6。
  * Ghastcoiler: 金色 `TB_BaconUps_057` NUM_1=4（基础 2）。
- **Improve 增量**（Hopebringer / Ultraviolet Ascendant）:
  官方 wiki 卡页无 Notes; 官方 CardDefs 只有基础 NUM_1/NUM_2（改善后的
  动态计数值不在客户端数据内）。按**全仓 Improve 家族口径**（SOP §16b
  "improve this" 无独立参数 → 增量 = 印面值; 先例 `batch_soc.py`
  FireForgedEvoker `mult = 1 + improve_count`、Tasty Lobster / Lurking
  Leviathan / Tumbling Disaster 等）: 每次改善令 SoC 增益
  **+num(0)/+num(1)**（金色按金色 CardDef 数值）。
  旁证: 中文攻略（7723.cn 元素升腾流，2025-02）对旧版 Ultraviolet
  （当时 +2/+1、金色 +4/+2）明确 "普通卡是一张元素就提升 +2/1 的数值，
  合金翻倍为 +4/2" —— 每次打出元素提升 = 该卡当前印面值（金色翻倍），
  与本批 `mult = 1 + count` 完全一致。
  **官方轨迹交叉验证**（runs/official_traces/17493f10c0afbbad.json，
  36.x 历史对局，BobsBuddy 打印 `ScriptDataNum1=9 / Num2=6 / Num3=2`）:
  该补丁 Ultraviolet 印面值 +3/+2，改善 2 次 → 当前 SoC 增益
  `3×(1+2)=9` / `2×(1+2)=6`，**逐位吻合** "计数 ×（1+印面值）" 公式；
  `ScriptDataNum3` = 改善次数。注: diff harness 目前把
  `dynamic_script_data` 当上下文缺口、不把动态计数写入实体，因此该
  历史轨迹里本卡会按 count=0 结算（数值偏小）——这是 harness 侧可改进项，
  不是脚本语义问题。
  Improve 计数挂在**实体 Python 属性**（`source._xxx_improves`）——
  `run_combat` 的 `restore_state` 只回滚 tags/buffs，Python 属性跨战斗
  持久 = "permanently"；实体离场重入场归零（官方 Improve 随在场累积，
  同 FireForgedEvoker 先例）。
- 未注册任何 DEFERRED 卡（7/7 全部实现）。DEFERRED 台账为空。

实现要点
═══════════════════════════════════════════════════════════════════
- 全部走公开 Action / 真实事件 / 真实引擎路径:
  `Buff` / `GainKeyword` / `Hit`（圣盾/剧毒交互）/ `Listener`（
  `after_attack` / `keyword_lost` / `card_played`）/ `game.summon` /
  `game.pending_hand_add` / `game.minion_pool` / `game.trigger_deathrattle`
  （引擎亡语入口，含 Titus/dr_extra 倍率）。
- 目标规则本地复现 RULES §4.4（随机、嘲讽优先、潜行不可击）仅用于
  De-volition-ist 的"敌方最高生命"（不是攻击目标，不需要嘲讽/潜行语义
  ——实际按"存活敌方随从"排序，见 §Formal spec）。
- Lichling Hoarder 的 "started in your warband this combat" 数据源:
  `hero.last_combat_board`（引擎在 `end_recruit_phase` 战斗前写好的
  **战前战团快照**，RULES §4.8a; 与 Tess/幽灵阵容同源）。为兼容
  diff harness 的裸 `run_combat`（不经过 `end_recruit_phase`，该字段为
  空），在自身 `start_of_combat` 钩子再取一份兜底快照。
- Ship Master Eudora 的"金色随从永久保留"用 `Buff(persist=True)`——
  引擎 `run_combat` 恢复阶段按实体重放 persist 附魔（RULES §3.5 例外 4，
  Bewitched Ribbon 同通道）。
- 监听器一律 `owner=source`（离场自动注销）+ `condition` 做 owner/
  阵营过滤（SOP §16b 模式 27）; `on_transform = on_summon` 重接线
  （SOP §16c 模式 40）。

Test: `hsrl2/tests/test_batch_37x_combatgap.py`（真实 `run_combat` /
`CombatScheduler._execute_attack` / 真实 `trigger_deathrattle` /
真实 `run_script_hook` SoC / 真实 `play_minion` card_played; 每卡正对照
+ 负对照 + 金色独立 CardDef 断言）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2.actions import Buff, GainKeyword, Hit
from hsrl2.events import AFTER_ATTACK, CARD_PLAYED, KEYWORD_LOST, Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 卡 id（一律 CardDB 按名核实，禁止凭记忆写 id）──
DE_VOLITIONIST = "BG36_102"
DE_VOLITIONIST_G = "BG36_102_G"
LICHLING_HOARDER = "BG36_848"
LICHLING_HOARDER_G = "BG36_848_G"
HOPEBRINGER = "BG36_364"
HOPEBRINGER_G = "BG36_364_G"
NADINA = "BGS_040"
NADINA_G = "TB_BaconUps_154"        # 金色独立 CardDef（triple_upgrade_id=63780）
GHASTCOILER = "BGS_008"
GHASTCOILER_G = "TB_BaconUps_057"   # 金色独立 CardDef（triple_upgrade_id=58424）
ULTRAVIOLET = "BG31_810"
ULTRAVIOLET_G = "BG31_810_G"
EUDORA = "BG33_828"
EUDORA_G = "BG33_828_G"

#: 金色 Nadina 文本硬编码 "Give 6 friendly Dragons Divine Shield"
#: （CardDef 无模板参数；官方 CardDefs TB_BaconUps_154 CARDTEXT 权威）。
NADINA_GOLDEN_DRAGONS = 6
#: 金色 Eudora 文本 "Give your minions +{0}/{1} **twice**"（字面量）。
EUDORA_GOLDEN_TIMES = 2


# ══════════════════════════════════════════════════════════════════════
# 公共工具
# ══════════════════════════════════════════════════════════════════════


def _num(game: "Game", card_id: str, index: int) -> int:
    """`CardDef.num(index)` 权威取值; 缺失即 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        from hsrl2.game import GameStateError
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return int(value)


def _opponent_of(game: "Game", hero: "Hero") -> Optional["Hero"]:
    """当前战斗对中的对手（`_active_combat` 由 CombatScheduler 曝光）。"""
    ac = getattr(game, "_active_combat", None)
    if ac is None:
        return None
    a, b = ac
    return b if a is hero else (a if b is hero else None)


def _living_enemies(game: "Game", hero: "Hero") -> list:
    """战斗对手的存活棋盘随从（无战斗对/空板 → 空列表）。"""
    opp = _opponent_of(game, hero)
    if opp is None:
        return []
    return [m for m in opp.living_minions()]


def _dynamic_improve_count(entity) -> int:
    """读取**外部注入**的动态 Improve 初值（官方 `TAG_SCRIPT_DATA_NUM_3`）。

    通道: `Entity.script_data_or_card(3)` → 通道键 **3**（= 官方
    `TAG_SCRIPT_DATA_NUM_3`，枚举成员 `ScriptDataNum.NUM_3`；注意该
    成员的**数值**是官方 enumID 2889，而通道键是 1..5 的序号，不能混用
    `int(ScriptDataNum.NUM_3)`）。来源:
      - 官方轨迹重建（`Game.inject_script_data_from_trace` /
        `Game.set_entity_script_data`）注入的当前改善次数；
      - 引擎侧动态生产点（如有）。
    **无注入时**返回 0 —— 与旧行为逐位一致（本函数是纯增量通道）。
    """
    getter = getattr(entity, "script_data_or_card", None)
    if getter is None:
        return 0
    try:
        value = getter(3)
    except (TypeError, ValueError):
        return 0
    return int(value) if value else 0


# ══════════════════════════════════════════════════════════════════════
# BG36_102 De-volition-ist
# ══════════════════════════════════════════════════════════════════════


class DeVolitionistScript:
    """
    Natural language: [x]After this attacks, deal damage equal to this
    minion's Attack to the highest-Health enemy minion.

    依据: CardDefs 37.0 BG36_102（T5 4/8 Aberration, TRIGGER_VISUAL）;
    金色 BG36_102_G 文本 "deal damage equal to **double** this minion's
    Attack to the highest-Health enemy minion."（行为分支读金色文本）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source，离场/战死自动注销）:
         事件 `after_attack`(attacker=, defender=)——伤害与死亡结算**后**
         广播（引擎 C4; 攻击/顺劈/招募期攻击同一路径）。条件
         `attacker is source`（"After **this** attacks"; 作为防守方反击
         不触发; 被 `execute_immediate_attack` 强制攻击**会**触发——它
         同样是"this attacks"）。
      2. 目标 = 战斗对手棋盘上**当前生命（`m.health`）最高**的存活随从
         （deDE "höchsten Leben" / jaJP "最も体力" 权威 = 当前生命，不是
         max_health——SOP §16b #23）; 并列 `game.rng.choice` 任取（无官方
         Notes，自然语言解读，docstring 记边界）。敌方无存活随从 → 落空。
      3. 伤害 = `source.atk` **触发时快照**（攻击后 buff 计入）; 金色 ×2
         （文本 "double" 字面量）。经 `Hit`（target.take_damage + damage
         事件 + check_deaths）—— 圣盾抵消、剧毒/猛毒不由此路径触发（
         引擎 Hit 语义）。
      4. source 在攻击中战死 → 监听器已随死亡注销 → 不触发（官方: 死亡
         随从的触发不结算）。
      5. 招募期无 `_active_combat` → 落空（本卡不会在招募期攻击）。

    Test: test_batch_37x_combatgap.py — 真实 `_execute_attack`: 攻击后对
    最高当前生命敌方随从造成 4 伤 / 3 血残血目标不吃（选 10 血者）/
    金色 16 伤 / 敌方空板不崩 / 作为防守方不触发。

    Params: 无模板参数（伤害 = 运行时 Attack；金色 "double" 为文本字面量）
    """

    damage_mult = 1     # 金色 "double" → 2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_after_attack(g, attacker=None, defender=None, **kw):
            if attacker is not source:
                return
            if source.dead or source.zone != Zone.PLAY:
                return
            enemies = _living_enemies(g, hero)
            if not enemies:
                return
            top = max(m.health for m in enemies)
            tied = [m for m in enemies if m.health == top]
            victim = g.rng.choice(tied, label="devolitionist_target")
            amount = source.atk * DeVolitionistScript.damage_mult \
                if not source.is_golden \
                else source.atk * DeVolitionistGoldenScript.damage_mult
            if amount <= 0:
                return
            g.run_actions(Hit(victim, amount, source=source))

        game.events.register(Listener(
            event=AFTER_ATTACK, owner=source, callback=on_after_attack))
        return None

    #: Transform 后按新卡面重新接线（SOP §16c 模式 40）
    on_transform = on_summon


class DeVolitionistGoldenScript(DeVolitionistScript):
    """
    Natural language: [x]After this attacks, deal damage equal to double
    this minion's Attack to the highest-Health enemy minion.

    Formal spec: 同基础版，伤害 = `source.atk × 2`（金色文本 "double"
    字面量；金色 CardDef ATK=8 → 实测 16 伤）。

    Test: test_batch_37x_combatgap.py — 金色 8/16 攻击后对最高当前生命
    敌方随从造成 16 伤。

    Params: 无模板参数（"double" 为文本字面量）
    """

    damage_mult = 2


# ══════════════════════════════════════════════════════════════════════
# BG36_848 Lichling Hoarder
# ══════════════════════════════════════════════════════════════════════


class LichlingHoarderScript:
    """
    Natural language: [x]<b>Avenge ({0}):</b> Get a plain copy of a minion
    that started in your warband this combat.

    依据: CardDefs 37.0 BG36_848（T5 6/9 Undead; `avenge_target`=3 =
    NUM_1 {0}）；金色 BG36_848_G 文本 "Get **2** plain copies of a minion
    that started in your warband this combat"。
    多语言消歧（官方 CardDefs CARDTEXT）: frFR "copie **non dorée**" /
    jaJP "**未強化通常コピー**" / koKR "**강화 효과가 없는 일반 하수인**"
    → plain copy = 无附魔、**非金色**原始卡副本；"Get" = 进手牌。

    Formal spec:
      1. Avenge 阈值 3 由引擎读取 `CardDef.avenge_target` 并计数
         （引擎仅战斗内计数，RULES §6.11; 招募期死亡不计数），脚本只实现
         `avenge` 效果体。
      2. "started in your warband this combat" 数据源 =
         `hero.last_combat_board`（`end_recruit_phase` 在全部战斗前写入的
         战前战板快照，RULES §4.8a）。`start_of_combat` 兜底: 若该字段为
         空（diff harness 裸 `run_combat` 路径不经过 `end_recruit_phase`），
         取 SoC 时刻的 `hero.board` 快照。
      3. avenge: 从快照中**随机 1 个**随从（"a minion"，无描述符/无
         Notes → 随机; Play Dead 先例）; 生成**plain copy**:
         `create_minion(base_id)`（非金色、无 buff; base_id =
         TRIPLE_BASE_CARD_ID 回落），`pending_hand_add` 入手（满手排队）。
         金色 Lichling → **2 份**同一随从的副本（"2 plain copies of a
         minion" 单数）。
      4. 快照为空 / 无 Minion → 落空（不崩溃）。副本不占池（复制体语义，
         同 `SummonPlainCopy` / Scabbs 先例）。

    Test: test_batch_37x_combatgap.py — 战斗中 3 次友方死亡 → 入手 1 张
    plain 副本（属性 = CardDef 原始值）/ 2 次死亡不触发 / 金色 2 张 /
    招募期死亡不计数 / 满手排队。

    Params: {0}=3（`avenge_target`；金色同值——引擎按 CardDef 计阈值）
    """

    copies = 1          # 金色 "2 plain copies" → 2（文本字面量）

    # ── 战前战团快照 ──
    @staticmethod
    def start_of_combat(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        # 兜底快照（真实路径优先 hero.last_combat_board，见 avenge）
        source._started_warband = [m for m in hero.board
                                   if isinstance(m, Minion)]
        return None

    @staticmethod
    def avenge(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None or source.dead:
            return None
        started = list(getattr(hero, "last_combat_board", None) or [])
        if not started:
            started = list(getattr(source, "_started_warband", None) or [])
        started = [m for m in started if isinstance(m, Minion)]
        if not started:
            return None
        pick = game.rng.choice(started, label="lichling_copy_target")
        base_id = (pick.get(GameTag.TRIPLE_BASE_CARD_ID, None)
                   or pick.card_id)
        copies = (LichlingHoarderGoldenScript.copies
                  if source.is_golden else LichlingHoarderScript.copies)
        for _ in range(copies):
            copy = game.create_minion(base_id, controller=hero)
            if copy is None:
                return None
            game.pending_hand_add(hero, copy)
        return None


class LichlingHoarderGoldenScript(LichlingHoarderScript):
    """
    Natural language: [x]<b>Avenge ({0}):</b> Get 2 plain copies of a
    minion that started in your warband this combat.

    Formal spec: 同基础版，一次 avenge 入手**同一随从的 2 张** plain
    copy（金色文本 "2 ... of a minion"；副本仍**非金色**——frFR
    "copie non dorée" 权威）。

    Test: test_batch_37x_combatgap.py — 金色 avenge 入手 2 张同名
    plain 副本。

    Params: {0}=3（avenge_target）
    """

    copies = 2


# ══════════════════════════════════════════════════════════════════════
# BG36_364 Hopebringer
# ══════════════════════════════════════════════════════════════════════


class HopebringerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give your minions
    +{0}/+{1}. <i>(Permanently improves after a friendly minion loses
    <b>Divine Shield</b>!)</i>

    依据: CardDefs 37.0 BG36_364（T5 4/3 Dragon, START_OF_COMBAT;
    NUM_1=4 NUM_2=3）; 金色 BG36_364_G 的 NUM_1=8 NUM_2=6（金色独立
    CardDef，脚本无需分支）。"Permanently improves" 的增量: 官方 wiki
    无 Notes、CardDefs 无独立参数 → Improve 家族口径 = 增量取印面值
    （SOP §16b; 先例 `batch_soc.py` FireForgedEvoker `mult=1+count`）。

    Formal spec:
      1. SoC: 对己方棋盘**全部存活随从**（含 source——"your minions" 无
         "other"）Buff(+num(0)×M, +num(1)×M)，M = 1 + 已累积 Improve
         次数; 战斗内 buff 由快照战后回滚（RULES §3.5）。
      2. Improve: on_summon 注册持久监听器 `keyword_lost`(minion=, tag=)
         （引擎两条失去圣盾路径都广播该事件: `Minion.take_damage` 破盾与
         `LoseKeyword` action——只监听它可避免 `divine_shield_lost`
         重复计数）。条件: `tag is DIVINE_SHIELD` 且
         `minion.controller is source.controller`（"friendly"——含自己）。
         每次 +1 计数; 计数存 `source._hopebringer_improves`（实体 Python
         属性——`restore_state` 只回滚 tags/buffs → 跨战斗永久保留 =
         "permanently"；离场重入场归零）。
         **动态初值**: SoC 的改善倍数额外叠加
         `_dynamic_improve_count(source)`（= 官方 `TAG_SCRIPT_DATA_NUM_3`
         独立通道，见 `hsrl2.tags.ScriptDataNum`；官方轨迹重建可经
         `Game.set_entity_script_data/inject_script_data_from_trace`
         注入当前改善次数）。无注入 → 0 → 旧行为逐位不变。
      3. 金色数值由金色 CardDef 的 num(0)/num(1) 自然体现（每次改善
         +8/+6）。
      4. 敌方随从失去圣盾不触发（controller 过滤）。

    Test: test_batch_37x_combatgap.py — SoC 全板 +4/+3（含自身）/ 友方
    失去圣盾后下一场 +8/+6 / 敌方失去圣盾不改善 / 金色 +8/+6 起步且
    改善 +8/+6 / `restore_state`（战斗快照复原）后计数保留。

    Params: {0}=4 {1}=3（金色 =8/=6，金色独立 CardDef 体现）
    """

    improves_attr = "_hopebringer_improves"

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_keyword_lost(g, minion=None, tag=None, **kw):
            if tag is not GameTag.DIVINE_SHIELD:
                return
            if minion is None or minion.controller is not hero:
                return
            count = getattr(source, HopebringerScript.improves_attr, 0)
            setattr(source, HopebringerScript.improves_attr, count + 1)

        game.events.register(Listener(
            event=KEYWORD_LOST, owner=source, callback=on_keyword_lost))
        return None

    #: Transform 后按新卡面重新接线（SOP §16c 模式 40）
    on_transform = on_summon

    @staticmethod
    def start_of_combat(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk = d.num(0)
        health = d.num(1)
        if atk is None or health is None:
            from hsrl2.game import GameStateError
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1)")
        mult = (1
                + _dynamic_improve_count(source)
                + getattr(source, HopebringerScript.improves_attr, 0))
        return [Buff(m, atk=int(atk) * mult, health=int(health) * mult)
                for m in hero.board if not m.dead]


# ══════════════════════════════════════════════════════════════════════
# BGS_040 Nadina the Red
# ══════════════════════════════════════════════════════════════════════


class NadinaScript:
    """
    Natural language: <b>Deathrattle:</b> Give 3 friendly Dragons
    <b>Divine Shield</b>.

    依据: CardDefs 37.0 BGS_040（T6 8/4，无类型，DEATHRATTLE）; 金色
    `TB_BaconUps_154` CARDTEXT "Give **6** friendly Dragons Divine
    Shield"（硬编码数字，CardDef 无模板参数）→ 行为分支 3/6。

    Formal spec:
      1. deathrattle（真实死亡流程 / `trigger_deathrattle`）: 候选 =
         己方棋盘**存活且具有 DRAGON 类型身份**的随从（`has_race`
         集合语义: 多类型/ALL 均命中）; 无候选 → 落空。
      2. 随机取 min(3 或 6, 候选数) 个**互不相同**的龙（"Give 3
         friendly Dragons" 无 Target/Choose 字样 → 随机; 无官方 Notes，
         自然语言解读，docstring 记边界）。已持圣盾的龙也参与选择
         （文本无"without Divine Shield"限定; 选中者 GainKeyword 幂等）。
      3. 逐目标 `GainKeyword(target, DIVINE_SHIELD)`（战斗内授予随战斗
         快照回滚；招募期死亡产生的永久授予照常保留）。
      4. 金色 = 6 只（`NADINA_GOLDEN_DRAGONS` 字面量，金色 CardDef
         文本权威）。

    Test: test_batch_37x_combatgap.py — 真实 `destroy_minion` → 亡语:
    三条友方龙获得圣盾（任意 3/5）/ 非龙不获得 / 龙不足 3 时全给 /
    金色 6 只 / 无龙不崩。

    Params: 无模板参数（3 为文本字面量; 金色 6 为金色文本字面量）
    """

    dragons = 3         # 金色 = 6（金色 CardDef 文本字面量）

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        candidates = [m for m in hero.board
                      if not m.dead and m.has_race(Race.DRAGON)]
        if not candidates:
            return None
        count = (NadinaGoldenScript.dragons if source.is_golden
                 else NadinaScript.dragons)
        k = min(count, len(candidates))
        picks = game.rng.sample(candidates, k, label="nadina_dragons")
        return [GainKeyword(m, GameTag.DIVINE_SHIELD) for m in picks]


class NadinaGoldenScript(NadinaScript):
    """
    Natural language: <b>Deathrattle:</b> Give 6 friendly Dragons
    <b>Divine Shield</b>.

    Formal spec: 同基础版，数量 = 6（金色 CardDef `TB_BaconUps_154`
    CARDTEXT 硬编码数字权威）。

    Test: test_batch_37x_combatgap.py — 金色给 6 条龙圣盾（7 龙取 6）。

    Params: 无模板参数（6 为金色文本字面量）
    """

    dragons = NADINA_GOLDEN_DRAGONS


# ══════════════════════════════════════════════════════════════════════
# BGS_008 Ghastcoiler
# ══════════════════════════════════════════════════════════════════════


class GhastcoilerScript:
    """
    Natural language: <b>Deathrattle:</b> Summon {0} random
    <b>Deathrattle</b> minions.

    依据: CardDefs 37.0 BGS_008（T5 7/7 Beast, DEATHRATTLE, NUM_1=2）;
    金色 `TB_BaconUps_057` NUM_1=4（金色独立 CardDef，`num(0)` 自然体现
    4 只，脚本无需分支）。

    Formal spec:
      1. deathrattle: 候选 = 池内**带 DEATHRATTLE 关键词**且
         `minion_pool.available > 0` 的随从定义。范围与引擎随机获取口径
         一致: `d.tech_level <= game.max_tavern_tier`（标准局 6、异变
         Secrets of Norgunnon 7——`_pool_candidates` 先例）; 存在档白名单
         （异变 101/102 `game._tavern_tier_ladder`）过滤; 本局禁用种族
         （`pool.active_races`）过滤; NONE/ALL 永远可用（同池语义）。
      2. 逐只: `game.rng.choice(候选)` 取值（同一 id 可重复命中——池内
         多副本，"2 random minions" 语义; Sly Raptor/Scrap Scraper 先例）
         → `minion_pool.acquire` 占池（RULES §2.3/§2.4）→
         `create_minion` → `game.summon`（位置 = 亡语 ctx["position"]
         起，逐只 +1; 满场由 summon 落空）。
      3. 候选耗尽: 后续只落空（`acquire` 失败 → 停止，不抛错——池空是
         真实游戏行为）。
      4. 金色只影响数量（NUM_1=4），行为同基础版。

    Test: test_batch_37x_combatgap.py — 真实 `destroy_minion` → 亡语
    召唤 2 只池内亡语随从且池副本各 -1 / 金色 4 只 / 招募期死亡同样
    结算（亡语不分阶段）/ 无候选（max_tier=0）不崩。

    Params: {0}=2（金色 =4，金色独立 CardDef 体现）
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        count = d.num(0) if d is not None else None
        if count is None:
            from hsrl2.game import GameStateError
            raise GameStateError(
                f"{source.card_id}: missing num(0) template parameter")
        position = (ctx or {}).get("position")
        pool = game.minion_pool
        ladder = getattr(game, "_tavern_tier_ladder", None)
        max_tier = getattr(game, "max_tavern_tier", 6)

        def candidates() -> list:
            out = []
            for cdef in game.db.pool_minions():
                if "deathrattle" not in cdef.keywords:
                    continue
                if pool.available(cdef.id) <= 0:
                    continue
                if cdef.tech_level > max_tier:
                    continue
                if ladder is not None and cdef.tech_level not in ladder:
                    continue
                if pool.active_races is not None \
                        and cdef.race not in (Race.NONE, Race.ALL) \
                        and not (cdef.races & set(pool.active_races)):
                    continue
                out.append(cdef.id)
            return out

        for i in range(int(count)):
            cands = candidates()
            if not cands:
                break
            cid = game.rng.choice(cands, label="ghastcoiler_deathrattle")
            if not pool.acquire(cid):
                break
            m = game.create_minion(cid, controller=hero)
            if m is None:
                break
            pos = None if position is None else position + i
            game.summon(hero, m, pos)
        return None


# ══════════════════════════════════════════════════════════════════════
# BG31_810 Ultraviolet Ascendant
# ══════════════════════════════════════════════════════════════════════


class UltravioletAscendantScript:
    """
    Natural language: <b>Start of Combat:</b> Give your other Elementals
    +{0}/+{1}. <i>(Improves after you play an Elemental!)</i>

    依据: CardDefs 37.0 BG31_810（T6 6/6 Elemental, START_OF_COMBAT;
    NUM_1=3 NUM_2=3）; 金色 BG31_810_G NUM_1=6 NUM_2=6（金色独立
    CardDef，脚本无需分支）。Improve 增量: 官方 wiki 无 Notes、
    CardDefs 无独立参数 → Improve 家族口径（增量 = 印面值; 先例
    FireForgedEvoker `mult=1+count`）。旁证（中文攻略 7723.cn
    "元素升腾流"，2025-02，旧版 +2/+1→金色 +4/+2 时代）:
    "普通卡是一张元素就提升 +2/1 的数值，合金翻倍为 +4/2" —— 每次
    打出元素提升额 = 该卡当前印面值（金色翻倍），与本实现
    `mult = 1 + count` 一致。

    Formal spec:
      1. SoC: 对己方棋盘**其他**存活元素（`has_race(ELEMENTAL)` 集合
         语义; **排除 source 自身**——"your **other** Elementals"）
         Buff(+num(0)×M, +num(1)×M)，M = 1 + 已累积 Improve 次数。
         两只 Ultraviolet 互相给对方加成（各排除自身、包含对方）。
      2. Improve: on_summon 注册持久监听器 `card_played`(card=)。
         条件: `card` 是 Minion、`card.controller is source.controller`
         （"you play"）、`card.has_race(RACE_ELEMENTAL)`。每次 +1 计数;
         计数存 `source._ultraviolet_improves`（实体 Python 属性——
         `restore_state` 不回滚 → 跨战斗保留; 离场重入场归零）。
         **在手牌时不登记监听 → 在手牌期间打元素不改善**（攻略明确
         "这张卡在手牌的时候，使用元素是不能获得效果提升的"）。
         打出的元素若在 `card_played` 广播前已死亡/离场则不计
          （`card.dead or zone != PLAY` 守卫）。
         **动态初值**: SoC 的改善倍数额外叠加
         `_dynamic_improve_count(source)`（官方 `TAG_SCRIPT_DATA_NUM_3`
         独立通道；轨迹重建可注入当前改善次数 —— 实测旧版轨迹
         `ScriptDataNum3=2` 即改善 2 次）。无注入 → 0 → 旧行为逐位不变。
      3. 金色数值由金色 CardDef num(0)/num(1) 自然体现（每次改善
         +6/+6）。
      4. 非元素打出 / 对手打出元素 → 不改善。

    Test: test_batch_37x_combatgap.py — SoC 其他元素 +3/+3 且自身不加 /
    非元素不加 / 真实 play_minion 打出元素后下一场 +6/+6 / 对手打出
    元素不改善 / 金色 +6/+6 起步、改善后 +12/+12 / restore_state 后
    计数保留。

    Params: {0}=3 {1}=3（金色 =6/=6，金色独立 CardDef 体现）
    """

    improves_attr = "_ultraviolet_improves"

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_card_played(g, card=None, **kw):
            if not isinstance(card, Minion):
                return
            if card.controller is not hero:
                return
            if not card.has_race(Race.ELEMENTAL):
                return
            if card.dead or card.zone != Zone.PLAY:
                return
            count = getattr(source, UltravioletAscendantScript.improves_attr, 0)
            setattr(source, UltravioletAscendantScript.improves_attr,
                    count + 1)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_card_played))
        return None

    #: Transform 后按新卡面重新接线（SOP §16c 模式 40）
    on_transform = on_summon

    @staticmethod
    def start_of_combat(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk = d.num(0)
        health = d.num(1)
        if atk is None or health is None:
            from hsrl2.game import GameStateError
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1)")
        mult = (1
                + _dynamic_improve_count(source)
                + getattr(source, UltravioletAscendantScript.improves_attr, 0))
        return [Buff(m, atk=int(atk) * mult, health=int(health) * mult)
                for m in hero.board
                if not m.dead and m is not source
                and m.has_race(Race.ELEMENTAL)]


# ══════════════════════════════════════════════════════════════════════
# BG33_828 Ship Master Eudora
# ══════════════════════════════════════════════════════════════════════


class ShipMasterEudoraScript:
    """
    Natural language: <b>Deathrattle:</b> Give your minions +{0}/+{1}.
    Golden ones keep it permanently.

    依据: CardDefs 37.0 BG33_828（T5 8/3 Pirate, DEATHRATTLE; NUM_1=6
    NUM_2=6）; 金色 BG33_828_G 文本 "... +{0}/{1} **twice**"（NUM=6/6
    → 总额 +12/+12）。多语言消歧: deDE "**Goldene Diener** behalten
    dies dauerhaft" / zhCN "**金色随从**可永久保留此效果" → "Golden
    ones" 指**金色随从**（不是金色 Eudora）。

    Formal spec:
      1. deathrattle: 对己方棋盘**当前存活**随从逐个 Buff(+num(0),
         +num(1))——"your minions"（Eudora 自身已离场，不在棋盘）。
      2. 每目标: `target.is_golden` → `Buff(..., persist=True)`（引擎
         `run_combat` 恢复阶段按实体重放 persist 附魔 = 永久保留，
         RULES §3.5 例外 4/Bewitched Ribbon 同通道）; 非金色 →
         普通 `Buff`（战斗内增益随快照回滚 = 只在本次战斗有效）。
      3. 金色 Eudora: 先对**每个**目标做一次 +6/+6（金色→persist），
         再重复一次（"twice" 字面量）——金色随从累计永久 +12/+12。
      4. 敌方随从不 buff（"your minions"）; 空板落空不崩。

    Test: test_batch_37x_combatgap.py — 真实 `trigger_deathrattle`:
    己方全板 +6/+6、金色目标 buff 带 persist 标记 / 对手不加 /
    金色两次（金色目标 +12/+12 且 persist）/ 空板不崩。

    Params: {0}=6 {1}=6（金色同值，次数 = 2 为金色文本字面量）
    """

    times = 1           # 金色 "twice" → 2（文本字面量）

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk = d.num(0)
        health = d.num(1)
        if atk is None or health is None:
            from hsrl2.game import GameStateError
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1)")
        times = (ShipMasterEudoraGoldenScript.times
                 if source.is_golden else ShipMasterEudoraScript.times)
        actions = []
        for m in hero.board:
            if m.dead:
                continue
            for _ in range(times):
                actions.append(Buff(
                    m, atk=int(atk), health=int(health),
                    persist=bool(m.is_golden),
                    source_id=source.card_id))
        return actions or None


class ShipMasterEudoraGoldenScript(ShipMasterEudoraScript):
    """
    Natural language: <b>Deathrattle:</b> Give your minions +{0}/{1}
    twice. Golden ones keep it permanently.

    Formal spec: 同基础版，对每个目标结算 **2 次**（"twice" 字面量）；
    金色随从两次均 persist → 永久 +12/+12。

    Test: test_batch_37x_combatgap.py — 金色: 金色目标 +12/+12 且
    persist、非金色目标只在本场战斗（restore 后回滚）。

    Params: {0}=6 {1}=6（次数 = 2 为文本字面量）
    """

    times = EUDORA_GOLDEN_TIMES


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册 14 张（7 张池内卡 + 各自金色独立卡定义；0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (DE_VOLITIONIST, DeVolitionistScript),
        (DE_VOLITIONIST_G, DeVolitionistGoldenScript),
        (LICHLING_HOARDER, LichlingHoarderScript),
        (LICHLING_HOARDER_G, LichlingHoarderGoldenScript),
        (HOPEBRINGER, HopebringerScript),
        (HOPEBRINGER_G, HopebringerScript),
        (NADINA, NadinaScript),
        (NADINA_G, NadinaGoldenScript),
        (GHASTCOILER, GhastcoilerScript),
        (GHASTCOILER_G, GhastcoilerScript),
        (ULTRAVIOLET, UltravioletAscendantScript),
        (ULTRAVIOLET_G, UltravioletAscendantScript),
        (EUDORA, ShipMasterEudoraScript),
        (EUDORA_G, ShipMasterEudoraGoldenScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
