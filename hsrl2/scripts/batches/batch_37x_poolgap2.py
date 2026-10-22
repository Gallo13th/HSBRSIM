"""批次 37x_poolgap2 — 37.0 当前池内「缺失脚本」第二批：10 张 combat/经济卡。

背景
═══════════════════════════════════════════════════════════════════════
`tools/audit_card_registry_v2.py --strict` 在 37x_combatgap 后仍有 44 个
**池内**脚本缺口。本批按「当前池 + 战斗/招募决策相关 + 语义可精确实现」
筛出 10 张（其余 34 张按缺口类别 DEFERRED，台账见文末 §DEFERRED）：

  BG22_403 / _G   Young Murk-Eye（T6 8/5 Murloc）
      At the end of your turn, trigger the Battlecries of adjacent
      minions.（金色 "trigger ... twice"）
  BG34_405 / _G   Relentless Deflector（T3 5/4 Mech）
      Has Taunt while this has Divine Shield. Avenge (3): Gain Divine
      Shield.（金色文本同文——CardDefs 两版 avenge_target 均 3；
      wiki 金色页 "Avenge (4)" 为旧版本残留，数据权威 255130 取 3）
  BG36_116 / _G   Underrot Spawn（T2 2/2 Aberration）
      Deathrattle: Summon an 0/2 Tentacle with Taunt. Give your minions
      +1 Attack.（金色: two Tentacles + +2 Attack，NUM_1=2）
  BG31_149 / _G   Bubble Gunner（T1 2/3 Murloc）
      Battlecry: Gain a random Bonus Keyword.（金色 "2 random" —— 引擎
      金色战吼触发 2 次，脚本每次给 1 个，自然总额 2）
  BG31_815 / _G   Dune Dweller（T1 3/3 Elemental）
      Battlecry: Give Elementals in the Tavern +1/+1 this game.
      （金色 "twice" —— 引擎金色战吼触发 2 次，每次按**基础** CardDef
      数值；两版 NUM_1/NUM_2 均 1/1）
  BG28_707 / _G   Living Azerite（T5 8/6 Elemental）
      Whenever you cast a Tavern spell, give Elementals in the Tavern
      +4/+3 this game.（金色 "twice" —— 非战吼，脚本按 times=2 分支）
  BG36_104 / _G   Dark Puppeteer（T6 8/4 Aberration）
      Deathrattle: Your Tavern spells give an extra +4 Health this game.
      （金色 NUM_1=8，单次亡语；写 hero.TAVERN_SPELL_EXTRA_HEALTH）
  BG36_101 / _G   Unwilling Slacker（T3 3/2 Aberration）
      Deathrattle: Get a random 1-Cost Tavern spell.
      （金色 "two" —— 脚本按 is_golden 给 2 张；"1-Cost" = CardDef.cost==1）
  BG36_098 / _G   Zoatroid（T1 3/2 Aberration）
      When you sell this, get a 0/2 Tentacle with Taunt.
      （金色 "two" —— 脚本按 is_golden 给 2 个；token 非金）
  BG27_000 / _G   Iron Groundskeeper（T3 2/2）
      Battlecry: Get {0} copies of Fortify.（金色 NUM_1=4 = 总份数；
      引擎金色战吼触发 2 次 → 每次按**基础** NUM_1=2，合计 4）

数值/语义权威
═══════════════════════════════════════════════════════════════════════
- 数值一律 `CardDef.num(i)`（37.0.0.255130 官方数据）。
- **金色战吼"总份数"口径**（Iron Groundskeeper / Dune Dweller）:
  金色 CardDef 的 num 是**金色文本的数值**，而引擎对金色战吼触发
  **2 次**。若金色 num 已是总数（BG27_000_G NUM_1=4），每次触发必须
  用**基础** CardDef 数值（`_per_trigger_def`，batch_soc /
  batch_deathrattle 先例）；若金色 num 与基础相同（BG31_815_G=1/1）
  则直接用当前定义即可（两次触发自然翻倍）。
- **金色亡语/回合结束/售出**不被引擎翻倍 → 行为分支读金色文本
  （Underrot Spawn / Zoatroid / Unwilling Slacker / Living Azerite /
  Young Murk-Eye 的 times/count）。
- Bubble Gunner 的 `Gain a random Bonus Keyword` 走引擎
  `Game.random_bonus_keyword()` + `Game.grant_bonus_keyword`
  （后者写 `BONUS_KEYWORDS` 并广播 `bonus_keyword_granted`，RULES §9.6）。
- Relentless Deflector 的 "Has Taunt while this has Divine Shield" 是
  **动态关键词**：`on_summon` 注册 `keyword_gained`/`keyword_lost`
  监听（owner=source，离场自动注销），DS 得失同步 `GameTag.TAUNT`。
  边界: 若 Taunt 由**其它来源**独立授予，DS 失去时会一并清除（官方
  无 "Has Taunt" 之外来源的裁定；本批记档为已知近似，见下）。
- Dune Dweller / Living Azerite 的酒馆持久 Buff 走
  `hsrl2.actions.tavern_buff`（`TavernBuff` / `ApplyTavernBuff` /
  `BuffCurrentTavern`；`game.refresh_tavern` → `add_tavern_entity`
  已接线新入馆随从自动应用）。种族过滤用 **类型身份集合**
  （`CardDef.races`，ALL/双类型按 Amalgam 规则命中）。
- Unwilling Slacker 的 "1-Cost" = **金币费** `CardDef.cost == 1`
  （batch_eot_sot Gearfin 先例；不是 tavern tier）。
- 随机一律 `game.rng`；池约束走 `Game.tavern_spell_candidates()` /
  `minion_pool` / `grant_card_copy_to_hand`（RULES §2.3/§6.18）。
- Underrot Spawn 的 0/2 Taunt token = `BGFYM_002t`（CardDB 核实:
  0/2 Taunt；金色 token BGFYM_002t_G=0/4 但本卡文本明确 "0/2" →
  两版都召唤非金 token，数量 1/2 分支）。

公开接口说明（本批无需新引擎原语）
═══════════════════════════════════════════════════════════════════════
全部效果只用现有公开 Action/API：`TriggerBattlecry` / `GainKeyword` /
`Buff` / `TavernBuff` 动作族 / `Game.random_bonus_keyword` /
`Game.grant_bonus_keyword` / `Game.tavern_spell_candidates` /
`Game.grant_card_copy_to_hand` / `Game.pending_hand_add` /
`game.summon` / `game.create_minion` / `game.minion_pool` /
`game.spell_pool` / 事件 `keyword_gained` / `keyword_lost` /
`tavern_spell_cast`。

DEFERRED 台账（44 - 10 = 34 张；按缺口类别）
═══════════════════════════════════════════════════════════════════════
A. **Deity 子系统缺失**（37.0 新机制：Deity 随从/awaken；引擎无 Deity
   实体、无 awaken 流程 —— 见 `hsrl2/darkgifts.py` 37.0 DEFERRED 注释
   "Deity" 与 `reversed/` 迁移报告的未实现子系统清单）:
   BG36_099 / BG36_106 / BG36_108 / BG36_109 / BG36_110 / BG36_111 /
   BG36_113 / BG36_318 / BGFYM_005 / BG36_103（载荷 Energizing Chamber
   依赖 Deity，随宿主一并 DEFER）。
B. **Discard 子系统缺失**（引擎无弃牌动作/事件；`darkgifts.py` 同款
   DEFERRED 记录）:
   BG28_582 / BG36_100 / BG36_114 / BG36_300 / BG36_308 / BG36_311 /
   BG36_312 / BG36_320 / BG36_097。
C. **载荷卡未注册**（宿主本身语义简单，但 "Get <载荷>" 后载荷无脚本
   = 空转第三态；按 SOP §12 先补载荷再放宿主，列为下一批）:
   BG32_336（Seafood Stew BG32_337）、BG35_881（Arcane Absorption
   BG35_911）、BG35_882（Conflagration BG35_910）、BG36_112 +
   BG36_115（Sludge Corrosion BG36_301t）、BG34_170 / BG34_171 /
   BG36_366 / BG36_367（Volumizer token BG34_170t/t2/t3 家族）。
D. **触发链无权威上限**:
   BG28_583 Geomagus Roogug——单只行为可精确实现，但**两只 Roogug**
   会互相 "play a Blood Gem on a different friendly minion" 形成无界
   互触发；官方触发链上限无权威、引擎 ActionQueue 上限 20000 会抛
   `CombatLoopError`（会打断整局）。待引擎提供"触发链配额"裁定或
   官方证据后再实现。
E. **本批未取、但可直接排下一批**（语义明确、无子系统依赖）:
   BG32_231 Elite Navigator（双目标金色链）、BG36_362 Sacrificial
   Wrathguard（酒馆 Buff + Activate Improve）、BG36_370 Victorious
   Geomant（Activate 6 Blood Gems + 溢出施放）、BG36_700 Sewer
   Escapee（Activate 定向 Murloc）、BG32_860 Shoalfin Mystic（售出
   酒馆法术额外 +1/+1）。

Test: `hsrl2/tests/test_batch_37x_poolgap2.py`（真实 `game.play_minion` /
`game.summon` / `game.destroy_minion` / `game.sell_minion` /
`game.end_recruit_phase` EoT / `run_combat` / `play_spell` 事件路径；
每卡正对照 + 负对照 + 金色独立 CardDef 断言）。

与上一批的联动: `batch_37x_combatgap`（Hopebringer / Ultraviolet）已支持
从注入的动态 `TAG_SCRIPT_DATA_NUM_3` 初始化 Improve 计数（无注入时
行为逐位不变）；本批新卡没有 Improve 类，故不含该通道。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import Buff, GainKeyword, TriggerBattlecry
from hsrl2.actions.racefx import elemental_give_bonus
from hsrl2.actions.tavern_buff import (
    ApplyTavernBuff,
    BuffCurrentTavern,
    TavernBuff,
)
from hsrl2.events import (
    KEYWORD_GAINED,
    KEYWORD_LOST,
    TAVERN_SPELL_CAST,
    Listener,
)
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 卡 id（CardDB 按名核实）──
YOUNG_MURK_EYE = "BG22_403"
YOUNG_MURK_EYE_G = "BG22_403_G"
RELENTLESS_DEFLECTOR = "BG34_405"
RELENTLESS_DEFLECTOR_G = "BG34_405_G"
UNDERROT_SPAWN = "BG36_116"
UNDERROT_SPAWN_G = "BG36_116_G"
BUBBLE_GUNNER = "BG31_149"
BUBBLE_GUNNER_G = "BG31_149_G"
DUNE_DWELLER = "BG31_815"
DUNE_DWELLER_G = "BG31_815_G"
LIVING_AZERITE = "BG28_707"
LIVING_AZERITE_G = "BG28_707_G"
DARK_PUPPETEER = "BG36_104"
DARK_PUPPETEER_G = "BG36_104_G"
UNWILLING_SLACKER = "BG36_101"
UNWILLING_SLACKER_G = "BG36_101_G"
ZOATROID = "BG36_098"
ZOATROID_G = "BG36_098_G"
IRON_GROUNDSKEEPER = "BG27_000"
IRON_GROUNDSKEEPER_G = "BG27_000_G"

#: 0/2 Taunt Aberration token（CardDB 核实；金色 token 0/4 不使用）
ABERRANT_TENTACLE = "BGFYM_002t"
#: Iron Groundskeeper 载荷（池内 T1 酒馆法术；已注册）
FORTIFY = "BG28_503"


# ══════════════════════════════════════════════════════════════════════
# 公共工具
# ══════════════════════════════════════════════════════════════════════


def _num(game: "Game", card_id: str, index: int) -> int:
    """`CardDef.num(index)` 权威取值; 缺失 fail-loud（禁止静默 0）。"""
    from hsrl2.game import GameStateError
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return int(value)


def _per_trigger_def(game: "Game", source):
    """金色战吼"每次触发值"解析: 金色实体回基础 CardDef。

    引擎对金色随从的**战吼触发 2 次**（play_minion `times *= 2`）；
    若金色 CardDef 的 num 已是"总份数"（如 Iron Groundskeeper _G
    NUM_1=4 = 2 次 × 基础 2），每次触发必须用基础定义，否则总额翻倍
    成 8。金色死亡/售出/EoT 不用本函数（引擎只触发一次）。
    """
    d = game.db.get(source.card_id)
    if d is not None and d.is_golden_def and d.triple_base_id is not None:
        base = game.db.by_dbf(d.triple_base_id)
        if base is not None:
            return base
    return d


def _tavern_buff_actions(hero: "Hero", atk: int, health: int,
                         source_id: str) -> list:
    """"Give Elementals in the Tavern +a/+h this game":
    持久登记（刷新新入馆自动应用）+ 立即应用于当前馆内匹配随从。"""
    tb = TavernBuff(atk=atk, health=health, race_filter=Race.ELEMENTAL,
                    source_id=source_id)
    return [ApplyTavernBuff(hero, tb), BuffCurrentTavern(hero, tb)]


def _gain_random_cost_tavern_spells(game: "Game", hero: "Hero",
                                    count: int, cost: int) -> int:
    """获取 count 张随机 `CardDef.cost == cost` 的池内酒馆法术进手牌。

    - 候选 = `Game.tavern_spell_candidates()`（存在档白名单/非存在档排除）
      再按金币费过滤（batch_eot_sot Gearfin 先例）
    - 每张 `spell_pool.acquire` 占池（RULES §2.3/§3.6.1）
    - `pending_hand_add`（满手排队 RULES §3.3）
    - 池空 → 少拿/落空（官方落空语义）
    返回实际获取数。
    """
    gained = 0
    while gained < count:
        cands = [cid for cid in game.tavern_spell_candidates()
                 if game.db.get(cid) is not None
                 and game.db.get(cid).cost == cost]
        if not cands:
            break
        cid = game.rng.choice(cands, label="unwilling_slacker_spell")
        if not game.spell_pool.acquire(cid):
            break
        spell = game.create_spell(cid, controller=hero)
        if spell is None:
            break
        game.pending_hand_add(hero, spell)
        gained += 1
    return gained


# ══════════════════════════════════════════════════════════════════════
# BG22_403 Young Murk-Eye
# ══════════════════════════════════════════════════════════════════════


class YoungMurkEyeScript:
    """
    Natural language: [x]At the end of your turn, trigger the
    <b>Battlecries</b> of adjacent minions.

    依据: CardDefs 37.0 BG22_403（T6 8/5 Murloc）；金色 BG22_403_G 文本
    "trigger the Battlecries of adjacent minions **twice**"。

    Formal spec:
      1. end_of_turn（真实 `end_recruit_phase` EoT 阶段对棋盘随从分发）:
         取 source 在 `hero.board` 的当前下标，左右相邻存活随从
         （左、右各一；source 在场才触发）。顺序 = 板序左→右
         （官方未公布顺序，自然语言解读，docstring 记边界）。
      2. 每次对每个相邻随从调 `TriggerBattlecry(target)`（引擎统一
         重触发原子: `has_battlecry` 门禁 / 目标金色 ×2 /
         `BATTLECRY_DOUBLER`(Brann) 叠加 / `BATTLECRY_TRIGGER` 广播 /
         `COUNTER_BATTLECRIES` 计数）。无战吼相邻随从自然无效果。
      3. 金色 = 每个相邻随从触发 **2 次**（文本 "twice"；引擎不翻倍
         EoT 钩子 → 脚本分支）。
      4. 相邻随从在 EoT 结算时已死亡（前序 EoT 效果致死）→ 跳过。

    Test: test_batch_37x_poolgap2.py — 左邻真实战吼被触发 / 右邻触发 /
    金色 2 次 / 无相邻不崩 / 相邻无战吼无效果 / 换位后跟当前板位。

    Params: 无模板参数（"twice" 为金色文本字面量）
    """

    trigger_times = 1

    @staticmethod
    def end_of_turn(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None or source.dead:
            return None
        board = hero.board
        if source not in board:
            return None
        idx = board.index(source)
        neighbors = []
        if idx > 0:
            neighbors.append(board[idx - 1])
        if idx + 1 < len(board):
            neighbors.append(board[idx + 1])
        times = (YoungMurkEyeGoldenScript.trigger_times
                 if source.is_golden else YoungMurkEyeScript.trigger_times)
        actions = []
        for m in neighbors:
            if m.dead:
                continue
            for _ in range(times):
                actions.append(TriggerBattlecry(m))
        return actions or None


class YoungMurkEyeGoldenScript(YoungMurkEyeScript):
    """
    Natural language: [x]At the end of your turn, trigger the
    <b>Battlecries</b> of adjacent minions twice.

    Formal spec: 同基础版，每个相邻随从触发 2 次（"twice" 字面量）。

    Test: test_batch_37x_poolgap2.py — 金色对每个相邻随从触发 2 次。

    Params: 无模板参数（"twice" 为金色文本字面量）
    """

    trigger_times = 2


# ══════════════════════════════════════════════════════════════════════
# BG34_405 Relentless Deflector
# ══════════════════════════════════════════════════════════════════════


class RelentlessDeflectorScript:
    """
    Natural language: Has <b>Taunt</b> while this has <b>Divine Shield</b>.
    <b>Avenge ({0}):</b> Gain <b>Divine Shield</b>.

    依据: CardDefs 37.0 BG34_405（T3 5/4 Mech，无关键词；两版
    TAG_SCRIPT_DATA_NUM_1/AVENGE 均 3，金色文本同文）。

    Formal spec:
      1. 动态 Taunt: on_summon 时同步一次（有圣盾 → 置 TAUNT），并注册
         持久监听器（owner=source，离场/战死自动注销）:
         `keyword_gained`(minion=source, tag=DIVINE_SHIELD) → 置 TAUNT;
         `keyword_lost`(minion=source, tag=DIVINE_SHIELD) → 清 TAUNT。
         覆盖所有得失圣盾路径（`Minion.take_damage` 破盾 / `GainKeyword` /
         `LoseKeyword` action；两者都广播上述事件）。
         边界: 若 TAUNT 由其它来源独立授予，本卡的 DS 失去会一并清除
         （官方无 "Has Taunt" 与外部 Taunt 并存的裁定；已知近似记档）。
      2. Avenge 阈值 3 由引擎从 `CardDef.avenge_target` 读取并只战斗内
         计数（RULES §6.11）；脚本只实现效果体: 未持圣盾 →
         `GainKeyword(source, DIVINE_SHIELD)`（已持圣盾 → 落空不重复）。
         金色文本同文（仅属性差异）→ 同一脚本类。
      3. 战斗内增益经快照回滚（RULES §3.5）；监听器在 `run_combat`
         恢复后仍有效（SOP §8）。

    Test: test_batch_37x_poolgap2.py — 真实 `GainKeyword` 后 TAUNT 置位 /
    `LoseKeyword` 破盾后 TAUNT 清除 / 真实战斗内 3 次友方死亡触发 Avenge
    获得圣盾且 TAUNT 置位 / 无圣盾时无 TAUNT / 金色同效。

    Params: {0}=3（avenge_target；金色同值）
    """

    @staticmethod
    def _sync_taunt(source) -> None:
        if source.has(GameTag.DIVINE_SHIELD):
            source.set(GameTag.TAUNT, True)
        else:
            source.clear(GameTag.TAUNT)

    @staticmethod
    def on_summon(source, game, ctx=None):
        RelentlessDeflectorScript._sync_taunt(source)

        def on_gain(g, minion=None, tag=None, **kw):
            if minion is source and tag == GameTag.DIVINE_SHIELD:
                source.set(GameTag.TAUNT, True)

        def on_lost(g, minion=None, tag=None, **kw):
            if minion is source and tag == GameTag.DIVINE_SHIELD:
                source.clear(GameTag.TAUNT)

        game.events.register(Listener(
            event=KEYWORD_GAINED, owner=source, callback=on_gain))
        game.events.register(Listener(
            event=KEYWORD_LOST, owner=source, callback=on_lost))
        return None

    #: Transform 后按新卡面重新接线（SOP §16c 模式 40）
    on_transform = on_summon

    @staticmethod
    def avenge(source, game, ctx=None):
        if source.dead or source.has(GameTag.DIVINE_SHIELD):
            return None
        return GainKeyword(source, GameTag.DIVINE_SHIELD)


# ══════════════════════════════════════════════════════════════════════
# BG36_116 Underrot Spawn
# ══════════════════════════════════════════════════════════════════════


class UnderrotSpawnScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Summon an 0/2 Tentacle with
    <b>Taunt</b>. Give your minions +{0} Attack.

    依据: CardDefs 37.0 BG36_116（T2 2/2 Aberration，DEATHRATTLE，
    NUM_1=1）；金色 BG36_116_G NUM_1=2 且文本 "Summon **two** 0/2
    Tentacles ... +{0} Attack"。

    Formal spec:
      1. deathrattle（真实死亡流程 / trigger_deathrattle）: 召唤
         `BGFYM_002t` Aberrant Tentacle（0/2 Taunt，两版均非金 token——
         文本明确 0/2）1 个（基础）/ 2 个（金色），位置 = 死者让出的
         `ctx["position"]` 起依次 +1（满场由 `game.summon` 落空）。
      2. 召唤**之后**对己方棋盘全部存活随从（含刚召唤的 Tentacle）
         `Buff(+num(0), 0)`——"Summon ... Give your minions ..." 的
         顺序语义（先召唤再给）。
      3. 金色 NUM_1=2 → +2 Attack（数值由金色 CardDef 体现，脚本只
         分支召唤数量）。

    Test: test_batch_37x_poolgap2.py — 真实 `destroy_minion`: 亡语召唤
    1 只 0/2 Taunt 并使全板 +1 Attack（含 Tentacle）/ 金色召唤 2 只且
    +2 Attack / 满场时召唤落空但 Attack 增益照常 / 死亡位置插入。

    Params: {0}=1（金色 =2，金色独立 CardDef 体现）
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk = _num(game, source.card_id, 0)
        count = 2 if source.is_golden else 1
        base_pos = (ctx or {}).get("position")
        for i in range(count):
            token = game.create_minion(ABERRANT_TENTACLE, controller=hero)
            if token is None:
                continue
            pos = None if base_pos is None else base_pos + i
            game.summon(hero, token, pos)
        return [Buff(m, atk=atk)
                for m in list(hero.board) if not m.dead]


# ══════════════════════════════════════════════════════════════════════
# BG31_149 Bubble Gunner
# ══════════════════════════════════════════════════════════════════════


class BubbleGunnerScript:
    """
    Natural language: <b>Battlecry:</b> Gain a random <b>Bonus Keyword</b>.

    依据: CardDefs 37.0 BG31_149（T1 2/3 Murloc, BATTLECRY）；金色
    BG31_149_G 文本 "Gain **2** random Bonus Keywords"。

    Formal spec:
      1. battlecry: `tag = game.random_bonus_keyword()`
         （六集: Divine Shield / Reborn / Stealth / Taunt / Venomous /
         Windfury，RULES §9.6，均匀 `game.rng`）→
         `game.grant_bonus_keyword(source, tag)`（写
         `GameTag.BONUS_KEYWORDS` 并广播 `bonus_keyword_granted`；
         非六集成员 fail-loud）。
      2. 金色 "2 random" 由**引擎金色战吼触发 2 次**实现（脚本每次给
         1 个；两次独立随机，可能重复——官方未公布去重规则，自然语言
         解读记档）。本次已获得的关键词再次命中 = 该次落空（引擎 set
         幂等）。
      3. 手牌/棋盘状态无关；无目标。

    Test: test_batch_37x_poolgap2.py — 真实 `play_minion` 后恰获得 1 个
    Bonus Keyword 且写入 BONUS_KEYWORDS / 金色 2 次（累计 2 个记录）/
    重复随机不崩。

    Params: 无模板参数（"2" 为金色文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        tag = game.random_bonus_keyword()
        game.grant_bonus_keyword(source, tag)
        return None


# ══════════════════════════════════════════════════════════════════════
# BG31_815 Dune Dweller
# ══════════════════════════════════════════════════════════════════════


class DuneDwellerScript:
    """
    Natural language: [x]<b>Battlecry:</b> Give Elementals in the Tavern
    +{0}/+{1} this game.

    依据: CardDefs 37.0 BG31_815（T1 3/3 Elemental, BATTLECRY，
    NUM_1=NUM_2=1）；金色 BG31_815_G 文本 "... this game **twice**"
    （两版 NUM 均 1/1）。

    Formal spec:
      1. battlecry: `TavernBuff(atk=NUM_1, health=NUM_2,
         race_filter=ELEMENTAL, source_id)` →
         `ApplyTavernBuff`（登记到 `hero.tavern_buffs`，`refresh_tavern`/
         `add_tavern_entity` 对**新入馆**匹配随从自动应用）+
         `BuffCurrentTavern`（对**当前**馆内匹配随从立即永久 Buff，
         购买后随实体带走）。
      2. 种族匹配 = 类型身份集合（`CardDef.races`: ALL/双类型命中）。
      3. 金色 "twice": 引擎金色战吼触发 2 次；每次按**基础** CardDef
         1/1（`_per_trigger_def`）→ 总额 +2/+2、2 条持久登记。
      4. 只影响 `hero.tavern`（不含棋盘/手牌）；法术不 Buff。

    Test: test_batch_37x_poolgap2.py — 真实 `play_minion`: 馆内元素
    +1/+1、机械不变量、tavern_buffs 登记 1 条 / 金色 +2/+2、2 条 /
    刷新后新入馆元素自动带 Buff / 已有实体购买后属性保留。

    Params: {0}=1 {1}=1（金色同值 ×2 次）
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        bonus = elemental_give_bonus(source)
        atk = int(d.num(0)) + bonus[0]
        health = int(d.num(1)) + bonus[1]
        return _tavern_buff_actions(hero, atk, health, source.card_id)


# ══════════════════════════════════════════════════════════════════════
# BG28_707 Living Azerite
# ══════════════════════════════════════════════════════════════════════


class LivingAzeriteScript:
    """
    Natural language: Whenever you cast a Tavern spell, give Elementals
    in the Tavern +{0}/+{1} this game.

    依据: CardDefs 37.0 BG28_707（T5 8/6 Elemental，NUM_1=4 NUM_2=3）；
    金色 BG28_707_G 文本 "... this game **twice**"（两版 NUM 均 4/3）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件
         `tavern_spell_cast`(spell=)——引擎只对 `is_pool_spell` 手牌法术
         广播（Spellcraft/血宝石等不广播，RULES §3.6）；
         条件 `spell.controller is source.controller`（"you cast"）。
      2. 触发: `TavernBuff(+NUM_1/+NUM_2, race_filter=ELEMENTAL)` →
         `ApplyTavernBuff` + `BuffCurrentTavern`（同 Dune Dweller 语义:
         当前馆立即 + 后续入馆自动应用）。
      3. 金色 "twice"（非战吼，引擎不翻倍）→ 每次施放结算 2 遍
         （2 条持久登记 → 新入馆元素共 +8/+6）。
      4. 对手施放不触发；法术后置时点（引擎在效果结算后广播，
         "after you cast" 语义）。

    Test: test_batch_37x_poolgap2.py — 真实 `play_spell`（池法术）后馆内
    元素 +4/+3、非元素不变 / 金色 +8/+6、2 条登记 / 对手施放不触发 /
    Spellcraft 类非池法术不触发（负对照）。

    Params: {0}=4 {1}=3（金色同值 ×2 次）
    """

    times = 1

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_tavern_spell(g, spell=None, **kw):
            if spell is None or spell.controller is not hero:
                return
            d = g.db.get(source.card_id)
            if d is None:
                return
            bonus = elemental_give_bonus(source)
            times = (LivingAzeriteGoldenScript.times
                     if source.is_golden else LivingAzeriteScript.times)
            for _ in range(times):
                g.run_actions(_tavern_buff_actions(
                    hero, int(d.num(0)) + bonus[0],
                    int(d.num(1)) + bonus[1], source.card_id))

        game.events.register(Listener(
            event=TAVERN_SPELL_CAST, owner=source,
            callback=on_tavern_spell))
        return None

    #: Transform 后按新卡面重新接线（SOP §16c 模式 40）
    on_transform = on_summon


class LivingAzeriteGoldenScript(LivingAzeriteScript):
    """
    Natural language: Whenever you cast a Tavern spell, give Elementals
    in the Tavern +{0}/+{1} this game twice.

    Formal spec: 同基础版，每次施放结算 2 遍（"twice" 字面量）。

    Test: test_batch_37x_poolgap2.py — 金色两次登记/当前馆 +8/+6。

    Params: {0}=4 {1}=3（×2 次为金色文本字面量）
    """

    times = 2


# ══════════════════════════════════════════════════════════════════════
# BG36_104 Dark Puppeteer
# ══════════════════════════════════════════════════════════════════════


class DarkPuppeteerScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Your Tavern spells give an
    extra +{0} Health this game.

    依据: CardDefs 37.0 BG36_104（T6 8/4 Aberration，DEATHRATTLE，
    NUM_1=4）；金色 NUM_1=8（单次亡语，两版文本同文）。

    Formal spec:
      1. deathrattle: `hero.TAVERN_SPELL_EXTRA_HEALTH += NUM_1`
         （hero 级 tag；酒馆法术脚本的 give-stats 载荷读取该 tag 叠加
         ——既有消费点见 batch_battlecry / batch_choose_one 的
         TAVERN_SPELL_EXTRA_* 读取）。
      2. 只影响 "Tavern spells"（`is_pool_spell` 施放路径的载荷读取）；
         不改变法术本身费用/池。
      3. 金色 NUM_1=8 → +8（数值由金色 CardDef 体现）。
      4. 该效果 "this game" 永久（hero tag 不是战斗快照对象）。

    Test: test_batch_37x_poolgap2.py — 真实 `destroy_minion` 后 hero tag
    +4 / 金色 +8 / 叠加两次累计 / 事件路径不崩。

    Params: {0}=4（金色 =8，金色独立 CardDef 体现）
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        n = _num(game, source.card_id, 0)
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + n)
        return None


# ══════════════════════════════════════════════════════════════════════
# BG36_101 Unwilling Slacker
# ══════════════════════════════════════════════════════════════════════


class UnwillingSlackerScript:
    """
    Natural language: <b>Deathrattle:</b> Get a random 1-Cost Tavern
    spell.

    依据: CardDefs 37.0 BG36_101（T3 3/2 Aberration，DEATHRATTLE，
    无数值参数）；金色 BG36_101_G 文本 "Get **two** random 1-Cost
    Tavern spells"。

    Formal spec:
      1. "1-Cost" = **金币费** `CardDef.cost == 1`（batch_eot_sot
         Gearfin 先例；不是 tavern tier）。
      2. 候选 = `Game.tavern_spell_candidates()`（池副本 >0 + 存在档
         白名单）过滤 cost==1；`rng.choice` → `spell_pool.acquire` 占池
         → `create_spell` → `pending_hand_add`（满手排队）。
      3. 基础 1 张 / 金色 **2** 张（文本 "two"；两次独立随机，可重复
         ——池内同 id 多副本）。
      4. 池空 → 落空（不崩溃；官方随机获取无候选语义）。

    Test: test_batch_37x_poolgap2.py — 真实 `destroy_minion`: 入手 1 张
    cost==1 池法术且池副本 -1 / 金色 2 张 / 手牌满进 pending 队列 /
    池耗尽落空。

    Params: 无模板参数（"1-Cost"/"two" 为文本字面量）
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        _gain_random_cost_tavern_spells(game, hero, count, cost=1)
        return None


# ══════════════════════════════════════════════════════════════════════
# BG36_098 Zoatroid
# ══════════════════════════════════════════════════════════════════════


class ZoatroidScript:
    """
    Natural language: When you sell this, get a 0/2 Tentacle with
    <b>Taunt</b>.

    依据: CardDefs 37.0 BG36_098（T1 3/2 Aberration，无关键词）；
    金色 BG36_098_G 文本 "get **two** 0/2 Tentacles"。

    Formal spec:
      1. on_sell（真实 `game.sell_minion` 的售出钩子，先于离场/回池）:
         `create_minion(BGFYM_002t)`（0/2 Taunt，非金 token；两版文本
         明确 0/2）→ `pending_hand_add`（Get = 进手牌，满手排队）。
      2. 基础 1 个 / 金色 **2** 个（文本 "two"）。
      3. token 非池卡（零池记账）；宿主出售回池由引擎处理。

    Test: test_batch_37x_poolgap2.py — 真实 `sell_minion` 后入手 1 个
    0/2 Taunt Tentacle / 金色 2 个 / 手牌满进 pending 队列 /
    直接 `on_sell` 钩子 no-op 负对照（对照测试见 vacuous audit）。

    Params: 无模板参数（"two" 为金色文本字面量）
    """

    @staticmethod
    def on_sell(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        for _ in range(count):
            token = game.create_minion(ABERRANT_TENTACLE, controller=hero)
            if token is None:
                return None
            game.pending_hand_add(hero, token)
        return None


# ══════════════════════════════════════════════════════════════════════
# BG27_000 Iron Groundskeeper
# ══════════════════════════════════════════════════════════════════════


class IronGroundskeeperScript:
    """
    Natural language: <b>Battlecry:</b> Get {0} copies of Fortify.

    依据: CardDefs 37.0 BG27_000（T3 2/2，BATTLECRY，NUM_1=2）；
    金色 BG27_000_G NUM_1=4（金色文本 "Get 4 copies" = 总份数）。

    Formal spec:
      1. battlecry: 重复 NUM_1 次
         `game.grant_card_copy_to_hand(hero, Fortify 定义)`——
         白板副本、`is_pool_spell` 走 `spell_pool.acquire` 占池
         （池空 → 该份落空，RULES §2.4）、满手 `pending_hand_add`。
      2. 金色: 引擎金色战吼触发 2 次；每次按**基础** CardDef NUM_1=2
         （`_per_trigger_def`）→ 合计 4 份 = 金色文本。
      3. 载荷 `BG28_503 Fortify` 已注册（池内 T1 酒馆法术）。

    Test: test_batch_37x_poolgap2.py — 真实 `play_minion`: 入手 2 张
    Fortify、法术池 -2 / 金色 4 张 / 池耗尽时少拿不崩 / 满手排队。

    Params: {0}=2（金色 =4 总份数，`_per_trigger_def` + 引擎 ×2）
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        count = int(d.num(0))
        card_def = game.db.get(FORTIFY)
        for _ in range(count):
            game.grant_card_copy_to_hand(hero, card_def)
        return None


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册 20 张（10 张池内卡 + 各自金色独立卡定义；0 DEFERRED 注册）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (YOUNG_MURK_EYE, YoungMurkEyeScript),
        (YOUNG_MURK_EYE_G, YoungMurkEyeGoldenScript),
        (RELENTLESS_DEFLECTOR, RelentlessDeflectorScript),
        (RELENTLESS_DEFLECTOR_G, RelentlessDeflectorScript),
        (UNDERROT_SPAWN, UnderrotSpawnScript),
        (UNDERROT_SPAWN_G, UnderrotSpawnScript),
        (BUBBLE_GUNNER, BubbleGunnerScript),
        (BUBBLE_GUNNER_G, BubbleGunnerScript),
        (DUNE_DWELLER, DuneDwellerScript),
        (DUNE_DWELLER_G, DuneDwellerScript),
        (LIVING_AZERITE, LivingAzeriteScript),
        (LIVING_AZERITE_G, LivingAzeriteGoldenScript),
        (DARK_PUPPETEER, DarkPuppeteerScript),
        (DARK_PUPPETEER_G, DarkPuppeteerScript),
        (UNWILLING_SLACKER, UnwillingSlackerScript),
        (UNWILLING_SLACKER_G, UnwillingSlackerScript),
        (ZOATROID, ZoatroidScript),
        (ZOATROID_G, ZoatroidScript),
        (IRON_GROUNDSKEEPER, IronGroundskeeperScript),
        (IRON_GROUNDSKEEPER_G, IronGroundskeeperScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
