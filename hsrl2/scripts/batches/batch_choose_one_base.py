"""批次 choose_one_base — 非池/旧赛季 base Choose One 卡脚本（G-C6）。

作业来源: `docs/AUDIT_ENGINE_MECHANICS.md` G-C6 —— 10 张 base Choose One
卡在 `REGISTRY` 无脚本（`is_pool_minion/is_pool_spell` 均为 False，旧
赛季/非池卡）。本批按**权威判定**（`hsrl2/scripts/choose_one_authority.py`
= 标题正则 ∩ 非 Spellcraft 宿主）逐张实现并注册；数据 `choose_one`
文本兜底标志的 9 个提及型误报（BG31_323/_G、BG31_327/_G、BG31_329/_G、
BG31_892、BG36_331/_G）**不造脚本**（不是抉择卡）。

覆盖（17 个 def = 10 base + 金色/变体）:
  BG26_355 / _G      Disco Shuffler       Trigger a Battlecry; or Discover
                                           a Battlecry minion（金色 twice / 2）
  BG30_110 / _G      Mirage Conjurer      Tavern 全体 Attack / Health 翻倍
                                           （金色 Triple）
  BG30_117 / _G      Volcanic Visitor     Spellcraft 宿主（on_summon 授予
                                           BG30_117t / _Gt）
  BG30_117t / _Gt    Escape Eruption      全体 +4 Attack / +4 Health
                                           （金 +8）
  BG30_128 / _G      Sleeping Sea Glass   自身 Attack / Health 翻倍
                                           （金色 Triple）
  BG31_144 / _G      Adaptive Ancestor    +3 Attack & DS / +3 Health &
                                           Venomous（金 +6 由引擎双触发）
  BG31_325 / _G      Crystal Infuser      3 Blood Gems / Deathrattle: Get 2
                                           （金 6 / 4）
  BG31_825 / _G      Grace Farsail        下回合 +2 Gold / 两回合后 +4
                                           （金 4 / 8）
  BG31_842 / _G      Nether Construct     Tavern 全体 +4/+4 this game /
                                           Consume 全 Tavern 获属性（金 +8）
  BG31_884           The Road Less Traveled 随机 T6 / 两张随机 T5

共性裁定
--------
1. **引擎 Choose One 协议**（2026-10-22 两阶段状态机，
   `hsrl2/game.py::play_minion/play_spell`）: 脚本声明
   `choose_options = [(key, label), ...]` → 引擎挂 `choose_one`
   PendingChoice，选定 key 经 `ctx["choose"]` 触发 battlecry/on_play；
   `CHOOSE_BOTH` 光环/308 饰品/实体 tag 命中时直接传 `choose="both"`
   （两分支并联——本批所有脚本显式处理 "both"）。
2. **金色战吼模型**: 引擎对金色随从触发 2 次、每次按基础 CardDef
   （`_per_trigger_def`）。**加法型**效果自然满足金色文本（2×基础 =
   金色总额）；**乘法/持久登记型**效果（Mirage Conjurer / Sleeping
   Sea Glass 的 Double→Triple、Nether Construct 的 this game buff
   为加法故自然）需按金色文本字面量覆写 `mult` 并只结算一次
   （`single_apply = True` + 首触发标记），避免引擎双触发把
   Double 变 Quadruple。
3. **无目标子句的抉择卡**不做目标选择；Disco Shuffler 的 "Trigger a
   friendly minion's Battlecry" 是**分支内**定向（仅 "trigger" 分支
   需要目标），故不走引擎 `needs_target`（两阶段协议会在 Discover
   分支也强加目标窗）——由脚本在分支内自建一次
   `PendingChoice(kind="battlecry_target")`，金色两触发共用同一目标
   （首触发挂起、次触发跳过，resolve 内按金色次数重复触发）。
4. **Discover 候选口径**: "Discover a Battlecry minion" = 池内带战吼
   随从（`CardDef.keywords` 含 battlecry **或** 注册脚本含 battlecry
   钩子——条件化战吼如 Selfless Portrait 走同一门禁），tier 上限沿
   引擎 `Discover` 默认（`max_tavern_tier`），池预留/未选释放由引擎
   Discover Action 负责。
5. **"my/your" 语义**: 酒馆/棋盘均指**施放者自己**（hero.tavern /
   hero.board）；对手不沾。
6. **数据核实**: 数值全部来自卡面字面量（这些旧卡 CardDef 无
   `script_data_num_*`）——各处 `Params:` 行记录文本依据；dash/文本
   布局不影响权威判定（"<b>Choose One</b> -" 与 "<b>Choose One - </b>"
   两种格式均命中）。
"""

from __future__ import annotations

from hsrl2.actions import (
    Buff,
    Discover,
    GainKeyword,
    GainGold,
    GetRandomMinion,
    ScheduleNextTurn,
    TriggerBattlecry,
)
from hsrl2.actions.bloodgem import GetBloodGems
from hsrl2.actions.consume import ConsumeMinion
from hsrl2.actions.tavern_buff import (
    ApplyTavernBuff,
    BuffCurrentTavern,
    TavernBuff,
)
from hsrl2.game import PendingChoice
from hsrl2.minion import Minion
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Zone

_BATTLE_TARGET_KIND = "battlecry_target"


# ══════════════════ 通用帮助 ══════════════════


def _living_board(hero) -> list:
    return [m for m in hero.board if not m.dead]


def _def_has_battlecry(game, card_id: str) -> bool:
    """"带战吼"判定（Discover a Battlecry minion 候选资格）。

    双通道（与引擎 `has_battlecry` 同口径）: CardDef 关键词
    `battlecry` **或** REGISTRY 脚本含 battlecry 钩子（含条件化战吼
    的实体级 override 来源卡——脚本存在性即资格）。
    """
    d = game.db.get(card_id)
    if d is None:
        return False
    if "battlecry" in d.keywords:
        return True
    from hsrl2.scripts import REGISTRY
    script = REGISTRY.get(card_id)
    return script is not None and getattr(script, "battlecry", None) is not None


def _battlecry_minion_candidates(game) -> list:
    """池内带战吼随从的 card_id 列表（池剩余量感知）。"""
    from hsrl2.actions.discover import _pool_candidates
    return [cid for cid in _pool_candidates(game)
            if _def_has_battlecry(game, cid)]


def _is_own_friendly_minion(hero, entity) -> bool:
    return (isinstance(entity, Minion) and not entity.dead
            and entity.zone == Zone.PLAY and entity.controller is hero)


def _apply_to_one_branch(key: str, branch: str) -> bool:
    """分支命中判定: 选定该分支，或 CHOOSE_BOTH 双效。"""
    return key == branch or key == "both"


# ══════════════════ BG26_355 / _G Disco Shuffler ══════════════════


class DiscoShufflerScript:
    """
    Natural language: <b>Choose One - </b>Trigger a friendly minion's
    <b>Battlecry</b>; or <b>Discover</b> a <b>Battlecry</b> minion.

    金色 BG26_355_G: "Trigger a friendly minion's Battlecry **twice**;
    or Discover **2** Battlecry minions."

    Formal spec:
      1. choose_options = [("trigger", ...), ("discover", ...)]；引擎
         两阶段状态机挂 choose_one，ctx["choose"] 进 battlecry；
         CHOOSE_BOTH → "both"（两分支并联）。
      2. "trigger": 分支内定向（文本 "a friendly minion's Battlecry"，
         [Targeted]）: 候选 = 本人棋盘存活且**带战吼**的随从
         （`game.has_battlecry` 双通道），**排除 source 自身**——自身
         battlecry 就是本次抉择，自触发会形成无意义递归（官方同类
         定向"trigger a Battlecry"效果的实际口径；边界记档）。
         无候选 → 该分支落空。
         - 首触发挂一个 PendingChoice(kind="battlecry_target")，
           金色第二触发因 `_disco_trigger_queued` 标记跳过（两触发
           共用**同一目标**，与引擎定向战吼口径一致）；
         - resolve: 对选定目标执行 `TriggerBattlecry`（走引擎统一
           入口: Brann 翻倍 / COUNTER_BATTLECRIES / 广播全生效），
           金色执行 2 次 = "twice"。
      3. "discover": `Discover(hero, candidates=带战吼池随从)`——三选一、
         池预留/未选释放由引擎负责，选中入手（占池 + 满手排队）。
         金色引擎触发第二次 → 再 Discover 一次 = "2 Battlecry minions"。
      4. "both": 先触发再发现（文本序）。

    Test: test_batch_choose_one_base.py — 两分支效果 / 目标候选仅带
    战吼随从 / 分支选择前无效果 / 金色 trigger 同目标触发 2 次 /
    金色 discover 2 张 / CHOOSE_BOTH 双效 / 空候选落空

    Params: 无数值模板参数（twice/2 为金色文本字面量）
    """

    choose_options = [
        ("trigger", "Trigger a friendly minion's Battlecry"),
        ("discover", "Discover a Battlecry minion"),
    ]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        c = ctx or {}
        key = c.get("choose")
        if hero is None or key is None:
            return []
        out = []
        if _apply_to_one_branch(key, "trigger"):
            out.extend(DiscoShufflerScript._trigger_branch(
                source, game, hero))
        if _apply_to_one_branch(key, "discover"):
            cands = _battlecry_minion_candidates(game)
            if cands:
                out.append(Discover(hero, candidates=cands,
                                    kind="discover_battlecry_minion"))
        return out

    @staticmethod
    def _trigger_branch(source, game, hero) -> list:
        candidates = [m for m in _living_board(hero)
                      if m is not source and game.has_battlecry(m)]
        if not candidates:
            return []
        # 金色: 两触发共用同一目标（第一触发挂起、第二触发跳过）
        if getattr(source, "_disco_trigger_queued", False):
            return []
        source._disco_trigger_queued = True
        times = 2 if source.is_golden else 1

        def resolve(pick) -> None:
            source._disco_trigger_queued = False
            if not _is_own_friendly_minion(hero, pick):
                return
            for _ in range(times):
                game.run_actions(TriggerBattlecry(pick))

        game.pending_choices.append(PendingChoice(
            hero, candidates, _BATTLE_TARGET_KIND,
            resolve_callback=resolve))
        return []


class DiscoShufflerGoldenScript(DiscoShufflerScript):
    """
    Natural language: <b>Choose One - </b>Trigger a friendly minion's
    <b>Battlecry</b> twice; or <b>Discover</b> 2 <b>Battlecry</b>
    minions.

    Formal spec: 同基础版；"twice" 由 `_trigger_branch` 的
    `source.is_golden` 分支实现（同一目标 2 次），"2 minions" 由
    引擎金色双触发 → 两次 Discover 实现。

    Test: test_batch_choose_one_base.py — 金色 trigger 2 次 / 金色
    discover 2 张

    Params: 无数值模板参数（文本字面量）
    """


# ══════════════════ BG30_110 / _G Mirage Conjurer ══════════════════


class MirageConjurerScript:
    """
    Natural language: <b>Choose One -</b> Double the Attack of all
    minions in the Tavern; or Double their Health.

    金色 BG30_110_G: "**Triple** the Attack ...; or Triple their Health."

    Formal spec:
      1. choose_options = [("attack", ...), ("health", ...)]；
         CHOOSE_BOTH → "both"。
      2. "attack": 对 hero.tavern 内每个随从 `Buff(atk=当前攻击 ×
         (mult-1))` → 攻击变为 mult 倍（mult=2 基础 / 3 金色）。
      3. "health": 同构 × `max_health`（"Health" = 属性上限值，
         SOP §3 快照口径）。空酒馆 → 落空（合法）。
      4. 金色: mult=3 且 **只结算一次**（引擎双触发会把 Double 变
         4 倍——`single_apply` 首触发标记跳过第二触发）。
      5. "this turn"/"this game" 均无 → 永久增益（随实体购买带走；
         酒馆实体被刷新移除即消失，官方语义）。

    Test: test_batch_choose_one_base.py — attack/health 分支数值 /
    金色 Triple / CHOOSE_BOTH / 空酒馆落空

    Params: mult=2（金色 mult=3 文本字面量；CardDef 无 num）
    """

    choose_options = [
        ("attack", "Double the Attack of all minions in the Tavern"),
        ("health", "Double their Health"),
    ]
    mult = 2
    single_apply = False

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return []
        cls = source.scripts   # 脚本类（REGISTRY 注册的是类，非实例）
        if cls.single_apply:
            if getattr(source, "_mirage_applied", False):
                return []
            source._mirage_applied = True
        out = []
        for m in list(hero.tavern):
            if not isinstance(m, Minion):
                continue
            if _apply_to_one_branch(key, "attack"):
                out.append(Buff(m, atk=m.atk * (cls.mult - 1)))
            if _apply_to_one_branch(key, "health"):
                out.append(Buff(m, health=m.max_health * (cls.mult - 1)))
        return out


class MirageConjurerGoldenScript(MirageConjurerScript):
    """
    Natural language: <b>Choose One -</b> Triple the Attack of all
    minions in the Tavern; or Triple their Health.

    Formal spec: 同基础版，mult=3 且 single_apply=True（引擎金色双
    触发只结算一次——目标值 3 倍而非 4 倍）。

    Test: test_batch_choose_one_base.py — 金色 Triple（非 Quadruple）

    Params: mult=3（金色文本字面量）
    """

    mult = 3
    single_apply = True


# ══════════════════ BG30_117 / _G Volcanic Visitor（Spellcraft 宿主） ═══════════


class VolcanicVisitorScript:
    """
    Natural language: [x]<b><b>Spellcraft:</b> Choose One - </b>Give
    your minions +4 Attack; or +4 Health.

    金色 BG30_117_G: +8 Attack / +8 Health。

    Formal spec:
      1. on_summon: SPELLCRAFT tag 自举 + `grant_spellcraft_spell`
         ——打出/召唤立即获得法术（RULES §6.13）；金色随从的
         `spellcraft_id=114102` 直指金色法术 BG30_117_Gt
         （`spellcraft.py` 数据链自动选择）。
      2. 后续每招募阶段开始再给一张由引擎 `generate_for_hero` 负责。
      3. 法术效果本体见 `EscapeEruptionSpellScript`。

    Test: test_batch_choose_one_base.py — 入场立即获得法术 / 金色
    随从给金色法术

    Params: 法术侧 +4 / 金色 +8（法术文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.SPELLCRAFT, True)
        grant_spellcraft_spell(source, game)
        return None


# ══════════════════ BG30_117t / _Gt Escape Eruption（Spellcraft 法术） ═══════


class EscapeEruptionSpellScript:
    """
    Natural language: <b>Choose One -</b> Give your minions +4 Attack;
    or +4 Health.

    金色 BG30_117_Gt: +8 Attack / +8 Health。

    Formal spec:
      1. choose_options = [("attack", ...), ("health", ...)]；引擎
         play_spell 两阶段状态机挂 choose_one，ctx["choose"] 进 on_play；
         CHOOSE_BOTH（Fandral/308）→ "both" 两分支并联。
      2. "attack"/"health": 对本人棋盘每个存活随从 `Buff(atk=bonus)`
         / `Buff(health=bonus)`（Spellcraft 法术不是酒馆法术——
         不走 `tavern_spell_buff` 的"酒馆法术加成"修饰，官方语义）。
      3. `bonus` 按**本卡自身** CardDef 文本：基础 +4、金色 +8
         （法术无金色随机模型，读自身 card_id → 类属性）。
      4. 空棋盘 → 落空（合法）。

    Test: test_batch_choose_one_base.py — attack/health 分支全体 /
    金色 +8 / CHOOSE_BOTH / 空棋盘落空

    Params: bonus=4（金色 bonus=8，文本字面量；CardDef 无 num）
    """

    choose_options = [
        ("attack", "Give your minions +4 Attack"),
        ("health", "Give your minions +4 Health"),
    ]
    bonus = 4

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return []
        cls = source.scripts   # 脚本类（REGISTRY 注册的是类，非实例）
        bonus = cls.bonus
        out = []
        for m in _living_board(hero):
            if _apply_to_one_branch(key, "attack"):
                out.append(Buff(m, atk=bonus))
            if _apply_to_one_branch(key, "health"):
                out.append(Buff(m, health=bonus))
        return out


class EscapeEruptionGoldenSpellScript(EscapeEruptionSpellScript):
    """
    Natural language: <b>Choose One -</b> Give your minions +8 Attack;
    or +8 Health.

    Formal spec: 同基础版，bonus=8（金色法术文本字面量）。

    Test: test_batch_choose_one_base.py — 金色 +8

    Params: bonus=8（金色文本字面量）
    """

    bonus = 8


# ══════════════════ BG30_128 / _G Sleeping Sea Glass ══════════════════


class SleepingSeaGlassScript:
    """
    Natural language: [x]<b>Choose One -</b> Double this minion's
    Attack; or Health.

    金色 BG30_128_G: "**Triple** this minion's Attack; or Health."

    Formal spec:
      1. choose_options = [("attack", ...), ("health", ...)]；
         CHOOSE_BOTH → "both"。
      2. "attack": `Buff(source, atk=source.atk × (mult-1))` → 自身
         攻击 ×mult；"health": 同构 × `max_health`。
      3. 金色: mult=3 且 single_apply=True（引擎双触发只结算一次）。

    Test: test_batch_choose_one_base.py — attack/health 分支 / 金色
    Triple / CHOOSE_BOTH

    Params: mult=2（金色 mult=3 文本字面量）
    """

    choose_options = [
        ("attack", "Double this minion's Attack"),
        ("health", "Double this minion's Health"),
    ]
    mult = 2
    single_apply = False

    @staticmethod
    def battlecry(source, game, ctx):
        key = (ctx or {}).get("choose")
        if key is None:
            return []
        cls = source.scripts   # 脚本类（REGISTRY 注册的是类，非实例）
        if cls.single_apply:
            if getattr(source, "_sea_glass_applied", False):
                return []
            source._sea_glass_applied = True
        out = []
        if _apply_to_one_branch(key, "attack"):
            out.append(Buff(source, atk=source.atk * (cls.mult - 1)))
        if _apply_to_one_branch(key, "health"):
            out.append(Buff(source,
                            health=source.max_health * (cls.mult - 1)))
        return out


class SleepingSeaGlassGoldenScript(SleepingSeaGlassScript):
    """
    Natural language: [x]<b>Choose One -</b> Triple this minion's
    Attack; or Health.

    Formal spec: 同基础版，mult=3 且 single_apply=True。

    Test: test_batch_choose_one_base.py — 金色 Triple

    Params: mult=3（金色文本字面量）
    """

    mult = 3
    single_apply = True


# ══════════════════ BG31_144 / _G Adaptive Ancestor ══════════════════


class AdaptiveAncestorScript:
    """
    Natural language: [x]<b>Choose One - </b>Gain +3 Attack and
    <b>Divine Shield</b>; or +3 Health and <b>Venomous</b>.

    金色 BG31_144_G: +6 Attack and Divine Shield; or +6 Health and
    Venomous。

    Formal spec:
      1. choose_options = [("attack", ...), ("health", ...)]；
         CHOOSE_BOTH → "both"。
      2. "attack": `Buff(source, atk=3)` + `GainKeyword(source,
         DIVINE_SHIELD)`；"health": `Buff(source, health=3)` +
         `GainKeyword(source, VENOMOUS)`。
      3. 金色自然模型: 引擎双触发 × 每次 +3 = +6 ✓（加法型无需覆写）。

    Test: test_batch_choose_one_base.py — 两分支数值与关键词 / 金色
    +6 / CHOOSE_BOTH（+6/+6 与两关键词）

    Params: atk/health=3（文本字面量；CardDef 无 num）
    """

    choose_options = [
        ("attack", "Gain +3 Attack and Divine Shield"),
        ("health", "Gain +3 Health and Venomous"),
    ]
    gain = 3

    @staticmethod
    def battlecry(source, game, ctx):
        key = (ctx or {}).get("choose")
        if key is None:
            return []
        cls = source.scripts   # 脚本类（REGISTRY 注册的是类，非实例）
        out = []
        if _apply_to_one_branch(key, "attack"):
            out += [Buff(source, atk=cls.gain),
                    GainKeyword(source, GameTag.DIVINE_SHIELD)]
        if _apply_to_one_branch(key, "health"):
            out += [Buff(source, health=cls.gain),
                    GainKeyword(source, GameTag.VENOMOUS)]
        return out


# ══════════════════ BG31_325 / _G Crystal Infuser ══════════════════


class CrystalInfuserScript:
    """
    Natural language: <b>Choose One - </b>Get 3 <b>Blood Gems</b>; or
    gain "<b>Deathrattle:</b> Get 2 <b>Blood Gems</b>."

    金色 BG31_325_G: Get 6 Blood Gems; or gain "Deathrattle: Get 4
    Blood Gems."

    Formal spec:
      1. choose_options = [("gems", ...), ("deathrattle", ...)]；
         CHOOSE_BOTH → "both"。
      2. "gems": `GetBloodGems(hero, 3)`（进手牌，满手排队；非池卡
         不占池）。金色引擎第二次触发 → 再 3 颗 = 6 ✓。
      3. "deathrattle": 给 source 追加一个永久亡语
         "Deathrattle: Get 2 Blood Gems"（`_grant_crystal_deathrattle`:
         per-entity override + 计数累加；若随从已有原生亡语则链式保留
         ——原生先结算，追加亡语按获得次数逐条结算）。金色双触发
         → 2 条 "Get 2" = 4 ✓。
      4. 死亡时控制者解析: 以 `source.controller` 为宝石接收者。

    Test: test_batch_choose_one_base.py — gems 分支手牌 +3 / 金色 +6 /
    deathrattle 死亡后 +2 宝石 / 金色 +4 宝石 / CHOOSE_BOTH

    Params: gems=3/dr_gems=2（金色 6/4 由引擎双触发自然体现——
    CardDef 无 num，文本字面量）
    """

    choose_options = [
        ("gems", "Get 3 Blood Gems"),
        ("deathrattle", 'Gain "Deathrattle: Get 2 Blood Gems."'),
    ]
    gems = 3
    dr_gems = 2

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return []
        cls = source.scripts   # 脚本类（REGISTRY 注册的是类，非实例）
        out = []
        if _apply_to_one_branch(key, "gems"):
            out.append(GetBloodGems(hero, cls.gems))
        if _apply_to_one_branch(key, "deathrattle"):
            CrystalInfuserScript._grant_deathrattle(
                game, source, cls.dr_gems)
        return out

    @staticmethod
    def _grant_deathrattle(game, source, gems_per: int) -> None:
        """追加永久亡语 "Get N Blood Gems"（多次获得 → 多条叠加）。

        首次获得时捕获原生亡语（`source.scripts.deathrattle` / 已有
        实体 override）用于链式调用；之后每条追加在原生之后结算。
        """
        state = getattr(source, "_crystal_dr_state", None)
        if state is None:
            native_override = source._script_overrides.get("deathrattle")
            if native_override is not None:
                native = native_override
            else:
                script = source.scripts
                native = getattr(script, "deathrattle", None) \
                    if script is not None else None
            state = {"native": native,
                     "extra": 0,
                     "tag_was": source.has(GameTag.DEATHRATTLE)}
            source._crystal_dr_state = state

            def chain(src, g, c):
                outs = []
                if state["native"] is not None:
                    result = state["native"](src, g, c)
                    if result is not None:
                        outs.extend(result if isinstance(result, list)
                                    else [result])
                owner = src.controller
                if owner is not None:
                    total = state["extra"] * gems_per
                    if total > 0:
                        outs.append(GetBloodGems(owner, total))
                return outs or None

            source.set_script_override("deathrattle", chain)
            source.set(GameTag.DEATHRATTLE, True)
        state["extra"] += 1


class CrystalInfuserGoldenScript(CrystalInfuserScript):
    """
    Natural language: <b>Choose One - </b>Get 6 <b>Blood Gems</b>; or
    gain "<b>Deathrattle:</b> Get 4 <b>Blood Gems</b>."

    Formal spec: 同基础版；金色引擎双触发 × 每次 3 = 6 颗 /
    × 每次 2 = 两条共 4 颗（`_grant_deathrattle` 计数叠加）。

    Test: test_batch_choose_one_base.py — 金色 6 颗 / 金色亡语 4 颗

    Params: 同基础版（加法型，金色由引擎双触发自然体现）
    """


# ══════════════════ BG31_825 / _G Grace Farsail ══════════════════


class GraceFarsailScript:
    """
    Natural language: <b>Choose One - </b>Gain 2 Gold next turn; or Gain
    4 Gold in two turns.

    金色 BG31_825_G: Gain 4 Gold next turn; or Gain 8 Gold in two
    turns。

    Formal spec:
      1. choose_options = [("next", ...), ("two", ...)]；
         CHOOSE_BOTH → "both"（两分支并联）。
      2. "next": `ScheduleNextTurn(hero, GainGold(hero, 2))`——下个
         招募阶段开始（`_begin_recruit_for` 金币重置后）执行。
      3. "two": 两层延迟 `ScheduleNextTurn(hero, ScheduleNextTurn(hero,
         GainGold(hero, 4)))`——第二层在**再下一个**招募阶段开始执行
         = "in two turns"（Maiev "After 2 turns" 两级 tick 先例）。
      4. 金色引擎双触发 × 每触发基础值 = 下回合 4 / 两回合后 8 ✓
         （加法型，无需覆写）。

    Test: test_batch_choose_one_base.py — next 分支下回合 +2 /
    two 分支隔回合 +4 / 当回合无金 / 金色总额 / CHOOSE_BOTH

    Params: next=2 / two=4（金色由引擎双触发自然体现；文本字面量）
    """

    choose_options = [
        ("next", "Gain 2 Gold next turn"),
        ("two", "Gain 4 Gold in two turns"),
    ]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return []
        out = []
        if _apply_to_one_branch(key, "next"):
            out.append(ScheduleNextTurn(hero, GainGold(hero, 2)))
        if _apply_to_one_branch(key, "two"):
            out.append(ScheduleNextTurn(
                hero, ScheduleNextTurn(hero, GainGold(hero, 4))))
        return out


# ══════════════════ BG31_842 / _G Nether Construct ══════════════════


class NetherConstructScript:
    """
    Natural language: [x]<b>Choose One</b> - Give minions in the Tavern
    +4/+4 this game; or Consume all minions in the Tavern to gain their
    stats.

    金色 BG31_842_G: +8/+8 this game。

    Formal spec:
      1. choose_options = [("buff", ...), ("consume", ...)]；
         CHOOSE_BOTH → "both"（先 buff 再 consume，文本序）。
      2. "buff": `ApplyTavernBuff(hero, TavernBuff(atk=4, health=4))`
         （持久面: 之后刷新入馆的随从自动获得，引擎
         `refresh_tavern` 消费 `hero.tavern_buffs`）+ 
         `BuffCurrentTavern(hero, TavernBuff(atk=4, health=4))`
         （立即面对当前酒馆）。金色双触发 = +8/+8 ✓（两笔 +4 叠加）。
      3. "consume": 对 `hero.tavern` 内每个随从执行
         `ConsumeMinion(demon=source, victim=m)`——source 获得其 atk/
         max_health（永久）；酒馆来源受害者回池（RULES §2.3）。
         金色双触发: 第一触发吞空酒馆，第二触发无受害者 → 落空（净
         效果与基础版相同——金色文本的 consume 子句无数值差异）。
      4. 空酒馆 → 两分支均落空（合法）。

    Test: test_batch_choose_one_base.py — buff 分支当前馆 +4/+4 且
    刷新后新随从 +4/+4 / consume 分支吞噬全部且 source 得属性总和、
    池回补 / 金色 buff +8/+8 / CHOOSE_BOTH / 空馆落空

    Params: atk/health=4（金色 +8/+8 由引擎双触发自然体现；文本字面量）
    """

    choose_options = [
        ("buff", "Give minions in the Tavern +4/+4 this game"),
        ("consume", "Consume all minions in the Tavern to gain their stats"),
    ]
    gain = 4

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return []
        cls = source.scripts   # 脚本类（REGISTRY 注册的是类，非实例）
        buff = TavernBuff(atk=cls.gain, health=cls.gain,
                          source_id=source.card_id)
        out = []
        if _apply_to_one_branch(key, "buff"):
            out.append(ApplyTavernBuff(hero, buff))
            out.append(BuffCurrentTavern(hero, buff))
        if _apply_to_one_branch(key, "consume"):
            for m in list(hero.tavern):
                if isinstance(m, Minion) and not m.dead:
                    out.append(ConsumeMinion(source, m))
        return out


# ══════════════════ BG31_884 The Road Less Traveled（酒馆法术） ═══════════════


class RoadLessTraveledScript:
    """
    Natural language: [x]<b>Choose One - </b>Get a random Tier 6
    minion; or Get two random Tier 5 minions.

    Formal spec:
      1. choose_options = [("t6", ...), ("t5", ...)]；引擎 play_spell
         两阶段状态机挂 choose_one，ctx["choose"] 进 on_play；
         CHOOSE_BOTH（Fandral/308）→ "both" 两分支并联。
      2. "t6": `GetRandomMinion(hero, min_tier=6, max_tier=6)`——池感知、
         占池、入手（满手排队）。
      3. "t5": 两次 `GetRandomMinion(hero, min_tier=5, max_tier=5)`
         （"two random" = 两次独立随机，可为同 card_id 不同副本）。
      4. 池空 → 对应 Get 落空（真实行为）。

    Test: test_batch_choose_one_base.py — t6 分支入手 T6 且占池 /
    t5 分支两张 T5 / CHOOSE_BOTH 三张 / 池耗尽落空

    Params: 无模板参数（Tier 6/5 为文本字面量）
    """

    choose_options = [
        ("t6", "Get a random Tier 6 minion"),
        ("t5", "Get two random Tier 5 minions"),
    ]

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return []
        out = []
        if _apply_to_one_branch(key, "t6"):
            out.append(GetRandomMinion(hero, min_tier=6, max_tier=6))
        if _apply_to_one_branch(key, "t5"):
            out.append(GetRandomMinion(hero, min_tier=5, max_tier=5))
            out.append(GetRandomMinion(hero, min_tier=5, max_tier=5))
        return out


# ══════════════════ 注册 ══════════════════

#: card_id → 脚本类（10 base + 金色/变体共 17 def）
_SCRIPTS = {
    # Disco Shuffler
    "BG26_355": DiscoShufflerScript,
    "BG26_355_G": DiscoShufflerGoldenScript,
    # Mirage Conjurer
    "BG30_110": MirageConjurerScript,
    "BG30_110_G": MirageConjurerGoldenScript,
    # Volcanic Visitor（Spellcraft 宿主）+ Escape Eruption（法术）
    "BG30_117": VolcanicVisitorScript,
    "BG30_117_G": VolcanicVisitorScript,
    "BG30_117t": EscapeEruptionSpellScript,
    "BG30_117_Gt": EscapeEruptionGoldenSpellScript,
    # Sleeping Sea Glass
    "BG30_128": SleepingSeaGlassScript,
    "BG30_128_G": SleepingSeaGlassGoldenScript,
    # Adaptive Ancestor（金色自然双触发）
    "BG31_144": AdaptiveAncestorScript,
    "BG31_144_G": AdaptiveAncestorScript,
    # Crystal Infuser（金色自然双触发）
    "BG31_325": CrystalInfuserScript,
    "BG31_325_G": CrystalInfuserGoldenScript,
    # Grace Farsail（金色自然双触发）
    "BG31_825": GraceFarsailScript,
    "BG31_825_G": GraceFarsailScript,
    # Nether Construct（金色自然双触发：两笔 +4）
    "BG31_842": NetherConstructScript,
    "BG31_842_G": NetherConstructScript,
    # The Road Less Traveled（酒馆法术，无金色 def）
    "BG31_884": RoadLessTraveledScript,
}


def register() -> list[str]:
    """注册本批 17 个 def。"""
    from hsrl2.scripts.registry import register as reg

    registered = []
    for card_id, script in _SCRIPTS.items():
        reg(card_id, script)
        registered.append(card_id)
    return registered
