"""批次 trinkets22 — 饰品第二十二批（作业单 2026-09-13，16 张）。

台账来源: `docs/agents/TRINKET_LEDGER.md` 片 4/5（BG36_MagicItem_362 …
BG36_MagicItem_841）。与 batch_trinkets1..21 的 id 集合互不相交（运行核验:
16 张中 15 张为 `CardDB.trinket_offer_pool()` 成员; `BG36_MagicItem_810t`
为有同名本体的升级变体，不进商店池——本批一并注册其脚本，使升级变体
（Greater 8/8）与基础版行为一致）。

**官方文本权威**（本批语义裁定依据）:
  https://us.forums.blizzard.com/en/hearthstone/t/battlegrounds-season-14-trinket-updates/163710
  （Blizzard 官方 S14 Trinket Updates 全表; 与本批 16 张逐条比对，见下）
数值权威仍为 `hsdata/CardDefs.xml` → `CardDef.num(i)`。**两处官方预告与
36.2.2 数据不一致，一律以数据为准**（已在各类 docstring 记档）:
  - `BG36_MagicItem_363` Escapee Portrait: 预告 "open **2** turns sooner"
    vs `num(0)=1`（36.2.2 数据）→ 用 num(0)。
  - `BG36_MagicItem_372` Sphere of Memory: 预告 "get **2** copies"
    vs `num(0)=3`（36.2.2 数据）→ 用 num(0)。

实现 12 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG36_MagicItem_363 Escapee Portrait — 数据链交付金色 Enterprising
      Escapee + `card_gained` 监听把每个新入手的 Lockbox 倒计时
      -num(0)（等价 "Your Lockboxes open N turns sooner"）。

  BG36_MagicItem_370 Maldraxxus Dagger — on_bind + 每回合 `start_of_turn`
      "Discover a plain copy of a minion in your warband with a Dark
      Gift"：候选 = 本人棋盘随从的**基础** CardDef（去重）→
      `Game._pair_gifts`（**含换候选重抽**）各配互不相同合法 Dark
      Gift → `PendingChoice(kind="dark_gift")` → resolve:
      `create_minion` + `apply_dark_gift` + `pending_hand_add`。
      **不占池**——"a plain copy of a minion in your warband" 是副本
      （RULES §7.4.6 池记账只对"从池中获取的卡"; 同文本先例 Siren's
      Song BG27_514t "get a copy of" 不占池）。

  BG36_MagicItem_371 Honeycomb Ring — on_bind 永久 +num(0)/+num(1) 到
      `TAVERN_SPELL_EXTRA_*`（`racefx.tavern_spell_buff` 消费点）; 每次
      **在随从上施放法术**再叠加同额（"improve" 增量 = 印面值，
      全仓 "improve this" 惯例）并记入本回合临时账; 每回合
      `start_of_turn` 扣除临时账（"for this turn only"）。

  BG36_MagicItem_372 Sphere of Memory — on_bind 注册 `tavern_spell_cast`
      监听记录 `hero._last_tavern_spell_id`（引擎无全局"上一个法术"
      追踪——BG35_123 Cataclysmic Harbinger 同一脚本层协议）;
      EoT 入手 num(0) 份副本（copy 语义不占池，同 BG35_123）。

  BG36_MagicItem_390 Baller Portrait — on_bind + 每回合随机（50/50，
      Cousin Errgl 先例）交付 Fire Baller 或 Snow Baller（均为池随从
      → `grant_card_copy_to_hand` 占池）。

  BG36_MagicItem_800 Demonic Bloodletter — 每次施放酒馆法术: 持久
      `TavernBuff(+num(0)/+num(1))` + 立即 `BuffCurrentTavern`
      （"give minions in the Tavern +X/+Y this game" 家族; Nomi Sticker
      先例）。

  BG36_MagicItem_801 Consuming Claw — `minion_consumed` 监听: 友方
      **Demon** 吞噬后额外 +num(0)/+num(1) 并移转受害者战斗关键词
      （"Bonus Keywords" = 全仓约定的战斗关键词集，Methodical Madness
      BG36_880 先例）。

  BG36_MagicItem_810 (+ 升级变体 810t) Inductive Gyroblade — EoT 入手
      一个 Satellite token（BG31_171t，BASE 覆盖）: 尺寸 =
      num(0)*(1+本回合酒馆法术数) / num(1)*(1+本回合酒馆法术数)。
      **证据**: 官方 S14 表 Lesser "get a **4/4**" / Greater "get a
      **8/8**" 印面值即 0 次施放时的尺寸; "Improved by each Tavern
      spell" 的增量 = 印面值（论坛实测
      https://us.forums.blizzard.com/en/hearthstone/t/balinda-stonehearth-doesnt-improve-inductive-gyroblade/165377
      "each spell … only gave the trinket **+4/+4**"）。

  BG36_MagicItem_812 Emergency Gearblade — EoT 对本人**最左机械**效果
      施放关联法术 Repair Job（数据链 → BG36_624，`cast_spell_effect`，
      RULES §7.4.7b）。

  BG36_MagicItem_820 Flighty Portrait — 数据链交付 Flighty Scout;
      每次施放酒馆法术给手牌 + 棋盘的全部 Flighty Scout +num(0)/+num(1)。

  BG36_MagicItem_830 Bloodfury Shield — 每次施放酒馆法术向
      `game._fodder_refresh_pending[hero]` 追加 1 枚 Fodder（下次刷新
      附加; Twisted Wrathguard 同协议）。

  BG36_MagicItem_831 Felsteel Cleaver — `card_played` 监听: 法术
      **以酒馆随从为目标**时，随机友方随从吞噬该随从并获得其属性
      （`ConsumeMinion`——酒馆来源回池、不触发亡语、fire
      `minion_consumed`）。

DEFERRED 3 张（不注册; 依赖与实现路径见各类 docstring）——另 1 张
（`BG36_MagicItem_362`）已解冻，见下行。
═══════════════════════════════════════════════════════════════════════
  BG36_MagicItem_362 Cyclist Portrait — **已解冻（2026-09-18，
      batch_trinkets31 注册）**: 原阻塞"无逐 buff 按来源持久化通道"已由
      `Buff(persist=True)` + `Game.add_persist_source` 解决。
  BG36_MagicItem_373 Multilayered Shield — "improved by each different
      friendly minion type" 需要**动态** `TAVERN_SPELL_EXTRA_*` 求值
      （当前是静态 tag，`racefx.tavern_spell_buff` 只读一次）。
  BG36_MagicItem_380 Amplifying Essence — `ELEMENTAL_EXTRA_ATK/HEALTH`
      的 give-stats 消费点缺失（`batch_consume.elemental_buff` 全仓零
      生产调用点——BG32_MagicItem_802 Fountain Pen / BG32_841 Sand
      Swirler 同一缺口）。
  BG36_MagicItem_841 Assembler Portrait — 战斗内磁力吸附的
      `game._magnetic_stack` 不入 `run_combat` 快照/恢复（SoC 吸附会
      永久累积到宿主的亡语栈；脚本侧改写引擎私有状态被 SOP §2 禁止）。

关联卡台账（RULES §7.4.6——关联卡自身脚本状态不阻塞本批 CORRECT）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链 `evolution_card_id` → `db.by_dbf`） | 脚本状态 |
  |------|--------------------------------------------------|-----------|
  | BG36_MagicItem_363 | BG36_523_G Golden Enterprising Escapee | **未迁移**
  |      | （金色 def 本体；`triple_base_id`=BG36_523）      | （本体卡；本
  |      |                                                   | 饰品只用金色
  |      |                                                   | 交付路径） |
  | BG36_MagicItem_390 | BG31_816 Fire Baller（数据链）      | 未注册 |
  |      | BG31_818 Snow Baller（**无数据链**，按名核实）      | 未注册 |
  | BG36_MagicItem_812 | BG36_624 Repair Job（池法术 T3）    | **已注册**
  |      |                                                   | （batch_spells_final）
  | BG36_MagicItem_820 | BG32_330 Flighty Scout（池随从 T1） | **已注册**
  |      |                                                   | （batch_consume）
  | BG36_MagicItem_810 | BG31_171t Satellite（token）        | 无脚本（纯
  |      |                                                   | Magnetic） |
  | BG36_MagicItem_830 | BG35_150t Demon Fodder（token）     | 无脚本（引擎
  |      |                                                   | refresh 生成） |
  说明: BG31_816/BG31_818 的 "Improve your future Ballers" 属该两张卡自身
  的迁移台账；本饰品只交付白板副本（RULES §7.4.6 "Get a X" 判定）。

接线审计读取点（W1/W2/W3 核对）
═══════════════════════════════════════════════════════════════════════
  饰品仅分发 `on_bind` / `start_of_turn` / `end_of_turn`（W1 白名单）。
  监听事件全部有引擎/脚本生产点: `card_gained`（hero.add_to_hand）、
  `tavern_spell_cast`（game._finish_play_spell，仅池法术）、
  `card_played`（game._finish_play_spell / 生成法术路径）、
  `minion_consumed`（actions/consume.py ConsumeMinion）。无
  `game._x`/`hero._x` 私有标记写入（W3）——Fodder 走引擎公开消费的
  `game._fodder_refresh_pending`（消费点 game.refresh_tavern），
  `hero._last_tavern_spell_id` 为跨批次既有协议（BG35_123 / Nobundo）。
"""

from __future__ import annotations

from typing import List, Optional

from hsrl2 import constants as C
from hsrl2.actions import Buff, GainKeyword
from hsrl2.actions.consume import ConsumeMinion
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, \
    TavernBuff
from hsrl2.events import (
    CARD_PLAYED,
    MINION_CONSUMED,
    TAVERN_SPELL_CAST,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
ESCAPEE_PORTRAIT = "BG36_MagicItem_363"     # Escapee Portrait（Greater）
MALDRAXXUS_DAGGER = "BG36_MagicItem_370"    # Maldraxxus Dagger（Greater）
HONEYCOMB_RING = "BG36_MagicItem_371"       # Honeycomb Ring（Greater）
SPHERE_OF_MEMORY = "BG36_MagicItem_372"     # Sphere of Memory（Greater）
BALLER_PORTRAIT = "BG36_MagicItem_390"      # Baller Portrait（Lesser）
DEMONIC_BLOODLETTER = "BG36_MagicItem_800"  # Demonic Bloodletter（Lesser）
CONSUMING_CLAW = "BG36_MagicItem_801"       # Consuming Claw（Lesser）
INDUCTIVE_GYROBLADE = "BG36_MagicItem_810"  # Inductive Gyroblade（Lesser）
INDUCTIVE_GYROBLADE_T = "BG36_MagicItem_810t"   # 升级变体（Greater 8/8）
EMERGENCY_GEARBLADE = "BG36_MagicItem_812"  # Emergency Gearblade（Lesser）
FLIGHTY_PORTRAIT = "BG36_MagicItem_820"     # Flighty Portrait（Lesser）
BLOODFURY_SHIELD = "BG36_MagicItem_830"     # Bloodfury Shield（Greater）
FELSTEEL_CLEAVER = "BG36_MagicItem_831"     # Felsteel Cleaver（Greater）

# ── 关联卡 / token id（CardDB 按名核实） ──
FIRE_BALLER = "BG31_816"        # Fire Baller（池随从 T2; 数据链）
SNOW_BALLER = "BG31_818"        # Snow Baller（池随从 T2; 无数据链 → 常量）
SATELLITE = "BG31_171t"         # Satellite token（非池; batch_magnetic 裁定）
FLIGHTY_SCOUT = "BG32_330"      # Flighty Scout（池随从 T1; 数据链）
FLIGHTY_SCOUT_G = "BG32_330_G"  # 金色 Flighty Scout（独立卡定义）

# "Bonus Keyword" 官方定义域 = **6 张**（wiki.gg `Battlegrounds/Bonus_Keyword`
# 全文: Divine Shield / Reborn / Stealth / Taunt / Venomous / Windfury;
# 2026-09-02 对抗审查以该页 oldid 830663 订正——旧实现误抄
# `game._PERSIST_KEYWORD_TAGS` 的 8 集，把 POISONOUS/CLEAVE 也移转，
# 属 MAJOR 语义错误）。与 `batch_hero_passives2._BONUS_KEYWORD_TAGS` 同集。
_BONUS_KEYWORD_TAGS = (
    GameTag.TAUNT,
    GameTag.DIVINE_SHIELD,
    GameTag.WINDFURY,
    GameTag.VENOMOUS,
    GameTag.REBORN,
    GameTag.STEALTH,
)

# 含 ALL 型的匹配族（Amalgam 规则，RULES §6.18）
_MECH_RACES = (Race.MECH, Race.ALL)
_DEMON_RACES = (Race.DEMON, Race.ALL)

# rng 审计标签（全仓约定: 每次随机带可读 label）
_BALLER_LABEL = "baller_portrait_pick"
_CLEAVER_LABEL = "felsteel_cleaver_consumer"

# "Add a Fodder to your next Refresh"（文本字面量 "a" = 1 枚）
_FODDER_PER_CAST = 1


def _hero(ctx):
    """on_bind ctx → 饰品持有英雄（引擎 grant_trinket 传 ctx={"hero": h}）。"""
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef 模板参数（缺失 → fail-loud，SOP §3）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _base_card_id(game, entity) -> Optional[str]:
    """实体的**基础**卡 id（金色 → TRIPLE_BASE_CARD_ID，缺省 card_id）。

    用于 plain copy / "Flighty Scouts in your hand and warband" 的身份
    判定（SOP §16b item 17: 金色化实体不得用 card_id 直判）。
    """
    if entity is None:
        return None
    base = entity.get(GameTag.TRIPLE_BASE_CARD_ID, None)
    return base or entity.card_id


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


# ══════════════ BG36_MagicItem_363 Escapee Portrait ══════════════


class EscapeePortraitScript:
    """
    Natural language: Get a Golden Enterprising Escapee. Your Lockboxes
    open {0} |4(turn, turns) sooner.

    Formal spec:
      1. on_bind: 数据链交付金色关联卡——`game.trinket_related_card(id)`
         的 `evolution_card_id`(132763) 指向**金色** def `BG36_523_G`
         （36.2.2 数据核实; `triple_base_id`=132762 → BG36_523）→
         `game.grant_card_copy_to_hand(hero, gd, golden=True)`（补
         `GOLDEN` / `TRIPLE_BASE_CARD_ID` tag; RULES §7.4.6 + Curator
         Sticker 先例）。**池记账**: 金色 def `is_pool_minion=False`
         → 统一入口零池操作（RULES §7.4.6; 与 batch_trinkets15
         Curator Sticker 同口径）
      2. 注册 `card_gained` 持久监听（owner=饰品; RULES §7.4.6b）:
         `hero is 本人` 且 `card.card_id == constants.LOCKBOX_CARD_ID`
         → `game.open_lockbox_early(hero, num(0))`——等价于"该 Lockbox
         的初始倒计时 -num(0)"（Lockbox 初始 = CardDef.num(0)=5，
         `create_spell` 写入 `LOCKBOX_TURNS_LEFT`）
      3. "Your Lockboxes" 是**全局修饰**（此后每个入手/生成的 Lockbox
         都享受）; 只作用于本人（对手入手 Lockbox 不触发）
      4. 数值: num(0)=1（36.2.2 数据）。**官方 S14 预告文本写 "open 2
         turns sooner"**——数据与预告不一致，按数据权威取 num(0)
         （任务约定: 一律 `CardDef.num()`，禁止硬编码）
      5. 副本条款: 两份副本各注册一条监听 → 各减 num(0)（叠加 =
         官方副本语义）

    Test: test_batch_trinkets22.py — 绑定后手牌出现金色 Escapee
      （GOLDEN tag + TRIPLE_BASE_CARD_ID=BG36_523 + 属性 = 金色 def）/
      此后入手的 Lockbox 倒计时 = 基础值 - num(0)（正对照: 无饰品
      = 基础值）/ 对手入手 Lockbox 不减 / 已有 Lockbox（绑定前入手）
      不被追溯（监听只对**入手**事件生效——本卡文本无 "it opens
      sooner" 子句, 与 Lockbox Portrait 区分）/ 两份副本叠加减 2×num(0)

    Params: {0}=num(0)=1（BG36_MagicItem_363）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        gd = game.trinket_related_card(source.card_id)
        if gd is not None:
            game.grant_card_copy_to_hand(h, gd, golden=True)
        step = _num(game, source.card_id, 0)

        def on_gained(g, hero=None, card=None, **kw):
            if hero is not h or card is None:
                return
            if card.card_id != C.LOCKBOX_CARD_ID:
                return
            g.open_lockbox_early(h, step)

        game.events.register(Listener(event="card_gained", owner=source,
                                      callback=on_gained))
        return None


# ══════════════ BG36_MagicItem_370 Maldraxxus Dagger ══════════════


class MaldraxxusDaggerScript:
    """
    Natural language: [x]<b>Discover</b> a plain copy of a minion in your
    warband with a <b>Dark Gift</b>. At the start of each turn, repeat
    this.

    Formal spec:
      1. 候选集 = 本人棋盘**存活**随从的**基础** CardDef id（金色 →
         `TRIPLE_BASE_CARD_ID`; `_base_card_id`），去重（同一随从两只
         只提供一个同名选项——"a minion in your warband" 的 Discover
         选项是"可复制的随从"）。空棋盘 → 无候选 → **落空**（不产生
         PendingChoice、不报错）
      2. trio = `game.rng.sample(候选, min(3, len))`（无放回; ≤3 时取
         全部——官方 Discover 三选一，候选不足则全给）
      3. 每个候选配一枚**互不相同**的合法 Dark Gift: `Game._pair_gifts`
         （`Game.use_dark_gift` 同构: `darkgifts.eligible_gifts` 按窗口/
         池资格加权抽取 + **某位配不出 gift 时从候选换随从重抽 ≤20 次**;
         窗口回合取 `max(game.turn, C.DARK_GIFT_START_TURN)`——饰品在
         T9+ 购买但同一断言对开局授予也成立）。2026-09-02 对抗审查:
         旧实现用无重抽的 `_pair_gift_options` → turn=3 时大量 T1–T3
         候选无合法 gift，三选一退化为 2（SOP §16c #41）
      4. `PendingChoice(hero, options=(card_id, gift_id), kind=
         "dark_gift")`（与 `Game.use_dark_gift` / Ominous Stone 同一
         选择协议）; resolve:
         `create_minion(card_id)`（**plain**——不带任何附魔/金色）→
         `game.apply_dark_gift(m, gift_id)` → `pending_hand_add`
         （满手排队 RULES §3.3）
      5. **不占池**: "a plain copy of a minion in your warband" 是自有
         实体的副本（RULES §7.4.6 池记账只约束"从池中获取的卡"）——
         同文本先例 Siren's Song `BG27_514t` "get a copy of" 与
         `game._plain_copy_to_hand` 均不占池; 因此也**不做预留**
         （副本之间无共享资源可争）
      6. 触发点: `on_bind`（获得饰品即 "this" 发生——同族先例
         Maldraxxus Dagger 文本 "At the start of each turn, repeat
         this" 的 on_bind + start_of_turn 双点模型）+ 每回合
         `start_of_turn`
      7. 无合法 gift（gift 池耗尽 / 候选全试过仍无）→ `_pair_gifts`
         返回空 → 落空; 只进本人手牌（owner 隔离）

    Test: test_batch_trinkets22.py — 绑定后产生 1 条 dark_gift 选择且
      选项随从 ∈ 本人棋盘基础 id 集合、各配不同 gift / 选定后手牌出现
      该基础卡的 plain 副本（DARK_GIFT tag 已设、无附魔）/
      **golden 棋盘随从 → 交付基础（非金）副本** / 空板落空（无选择、
      无手牌变化）/ 对手棋盘不计入候选（owner 隔离）/ 真实
      `end_recruit_phase` 后再次产生选择 / 随从池余量不变（不占池）/
      同 seed 选项序列可复现

    Params: 无模板参数（候选/数量均动态; CardDef num(0..3) 全 None）
    """

    @staticmethod
    def _warband_bases(game, hero) -> List[str]:
        out: List[str] = []
        for m in _living(hero):
            base = _base_card_id(game, m)
            if base is not None and base not in out:
                out.append(base)
        return out

    @staticmethod
    def _discover(game, hero) -> int:
        """产生一次 Discover-with-Dark-Gift; 返回选项数（0=落空）。"""
        cands = MaldraxxusDaggerScript._warband_bases(game, hero)
        if not cands:
            return 0
        k = min(3, len(cands))
        trio = (game.rng.sample(cands, k, label="maldraxxus_dagger_trio")
                if k < len(cands) else list(cands))
        eff_turn = max(game.turn, C.DARK_GIFT_START_TURN)
        # 复用引擎配对（**含"某位配不出 gift 就从候选换随从重抽"**）——
        # `_pair_gift_options` 无重抽，turn=3 时大量 T1–T3 候选无合法 gift
        # → 三选一退化为 2（2026-09-02 对抗审查证伪, SOP §16c #41）
        options = game._pair_gifts(hero, trio, list(cands), turn=eff_turn)
        if not options:
            return 0

        def resolve(pick) -> None:
            if pick not in options:
                raise GameStateError(
                    f"maldraxxus dagger pick {pick} 不在提供选项中 "
                    f"{options}")
            card_id, gift_id = pick
            m = game.create_minion(card_id, controller=hero)
            game.apply_dark_gift(m, gift_id)
            game.pending_hand_add(hero, m)

        game.pending_choices.append(PendingChoice(
            hero, options, "dark_gift", resolve_callback=resolve))
        return len(options)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        MaldraxxusDaggerScript._discover(game, h)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        MaldraxxusDaggerScript._discover(game, h)
        return None


# ══════════════ BG36_MagicItem_371 Honeycomb Ring ══════════════


def _add_tavern_spell_extra(hero, atk: int, health: int) -> None:
    """`TAVERN_SPELL_EXTRA_*` 叠加（消费点 `racefx.tavern_spell_buff`）。"""
    hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
             hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + atk)
    hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
             hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + health)


def _is_minion_spell_target(hero, target) -> bool:
    """法术是否"施放在一个随从上"（本人棋盘或本人酒馆的 Minion）。

    裁定（SOP §6b 第 1 步 + 仓内先例）: 目标须是**存活 Minion** 且
    属于本人棋盘（`BG36_853` Glambot "cast a spell on a Mech" 的
    `zone == Zone.PLAY` + `controller is hero` 口径）或本人酒馆
    （酒馆随从同样是"a minion"——`BG27_514t` Siren's Song 以酒馆随从
    为目标的定向法术即属此类）。
    """
    if not isinstance(target, Minion) or target.dead:
        return False
    if target in hero.board and target.controller is hero:
        return True
    return target in hero.tavern


class HoneycombRingScript:
    """
    Natural language: [x]Your Tavern spells give an extra +{0}/+{1}.
    After you cast a spell on a minion, improve for this turn only.

    Formal spec:
      1. on_bind: 永久 `TAVERN_SPELL_EXTRA_ATK += num(0)` /
         `..._HEALTH += num(1)`（消费点 `racefx.tavern_spell_buff`——
         所有 give-stats 酒馆法术的统一出口; RULES §7.4.5 家族）
      2. 注册 **`spell_resolved`** 持久监听（owner=饰品; 引擎**每次
         施放、效果结算后**广播——手牌路径与 `cast_spell_effect` 同源）:
         条件
         `isinstance(spell, Spell)` 且 `spell.controller is 本人`
         （"you cast a spell"）; 回调内验目标
         `_is_minion_spell_target`（棋盘 / 酒馆随从）——命中则再叠加
         同额 num(0)/num(1)。**per-cast 而非 per-play**: 双施
         （SPELL_DOUBLER / spell_first）下每个 cast 各 improve 一次，
         且**正在结算的这次法术吃基准值、improve 对其后的施放生效**
         （"After you cast..." 后置语义）。旧实现听 `card_played` 每次
         打出只广播一次 → 双施只 +1 次（2026-09-02 对抗审查证伪,
         RULES §7.4.12）。本脚本只改 tag 不施法 → 无需重入闸
         （"improve" 增量 = **印面值**，全仓
         "improve this" 惯例: Heart of the Forest / Bubble Crown /
         Vashjir Anemone; 本卡 num(0)=num(1)=1，两种读法同值）并把
         增量记入 `source._honeycomb_temp`（本回合临时账）
      3. "for this turn only": 每回合 `start_of_turn` 把临时账从
         `TAVERN_SPELL_EXTRA_*` 中扣除并清零（"until next turn" =
         下一个招募阶段开始，RULES §6.13 / SOP §16 item 16 单 tick
         模型）。永久面（步骤 1 与各次 improve 的**永久**部分不存在
         ——本卡的 improve 全部是临时）不受影响
      4. 只作用于本人（hero 作用域 tag）; 对手施法不计入、对手不获得
      5. 副本条款: 两份副本各自监听与各自临时账 → 效果叠加
      6. 落空: 无随从目标的法术（如"获得一张牌"类）不触发; 目标在
         结算时已离场 → 不触发（不消耗任何资源）

    Test: test_batch_trinkets22.py — 绑定后 tag == num(0)/num(1) /
      真实 `play_spell`（定向 +stats 酒馆法术打在友方随从上）→
      tag 再 +num(0)/+num(1)，且同回合第二次施放继续叠加 /
      **双施（SPELL_DOUBLER）按 cast 各 improve 一次** /
      下一回合 `start_of_turn` → 临时增量全部清除、仅余基准 /
      无随从目标的法术不提升 / 对手施法不提升、对手 tag 不变 /
      两份副本叠加（基准 2×num、每次提升 2×num）/
      真实 `end_recruit_phase` 跨回合清除

    Params: {0}=num(0)=1 {1}=num(1)=1（BG36_MagicItem_371）
    """

    @staticmethod
    def _apply(source, game, h, atk: int, health: int,
               temporary: bool) -> None:
        _add_tavern_spell_extra(h, atk, health)
        if temporary:
            temp = getattr(source, "_honeycomb_temp", None)
            if temp is None:
                temp = [0, 0]
                source._honeycomb_temp = temp
            temp[0] += atk
            temp[1] += health

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)
        HoneycombRingScript._apply(source, game, h, atk, health,
                                   temporary=False)

        def on_resolved(g, spell=None, target=None, **kw):
            # **每次施放、效果结算后**（per-cast + 后置）: `card_played`
            # 每次打出只广播一次（双施只 improve 1 次），`spell_resolving`
            # 是前置时点（improve 会被正在结算的这次法术自己吃到——文本是
            # "**After** you cast a spell on a minion"）。故用
            # `spell_resolved`（RULES §7.4.12; 2026-09-02 对抗审查 +
            # 时点裁定）。本脚本只改 tag 不施法 → 无需重入闸
            if not isinstance(spell, Spell) or spell.controller is not h:
                return
            if not _is_minion_spell_target(h, target):
                return
            HoneycombRingScript._apply(source, g, h, atk, health,
                                       temporary=True)

        game.events.register(Listener(event="spell_resolved", owner=source,
                                      callback=on_resolved))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        """扣除上一回合累积的临时增量（"for this turn only" 到期）。"""
        h = source.controller
        if h is None:
            return None
        temp = getattr(source, "_honeycomb_temp", None)
        if not temp or (temp[0] == 0 and temp[1] == 0):
            return None
        h.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
              max(0, h.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) - temp[0]))
        h.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
              max(0, h.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) - temp[1]))
        temp[0] = 0
        temp[1] = 0
        return None


# ══════════════ BG36_MagicItem_372 Sphere of Memory ══════════════


class SphereOfMemoryScript:
    """
    Natural language: [x]At the end of your turn, get {0} copies of the
    last Tavern spell you cast.

    Formal spec:
      1. 读取**引擎维护**的 `hero._last_tavern_spell_id`（
         `_finish_play_spell` 对 `is_pool_spell` 的每次施放写入——正是
         "Tavern spell" 语义）。2026-09-02 主线收口: 该读取点由引擎
         维护、与监听器注册时点无关 → **绑定前同回合施放的法术同样
         可见**（旧实现自建 `tavern_spell_cast` 监听，绑定前施放不可见
         → EoT 0 份; 对抗审查证伪）。BG35_123 Cataclysmic Harbinger /
         BG31_HERO_003p Nobundo 的同一脚本层协议可陆续迁移
      2. EoT: 有记录且 `db.get(id)` 存在 → `create_spell(id)` ×
         num(0) → `pending_hand_add`（满手排队 RULES §3.3）。
         **copy 语义不占池**（同 BG35_123 已验收口径——副本之后被施放
         时 `SpellPool.release` 封顶于该 tier 的池上限，不产生泄漏）;
         无记录 → 落空（不报错、不产生空牌）
      3. 数值: num(0)（36.2.2 数据 = 3）。**官方 S14 预告文本写 "get 2
         copies"**——与数据不一致，按数据权威取 num(0)
      4. 只作用于本人记录（对手施法不覆盖本人记录——BG35_123 同款
         owner 隔离）; 副本各自记录/各自入手（叠加）

    Test: test_batch_trinkets22.py — 真实施放酒馆法术 → EoT 入手恰好
      num(0) 张同 id 法术（正对照: 未施放 → 无）/ **绑定前同回合施放
      的法术在绑定后的 EoT 同样交付**（引擎读取点）/
      施放后回池且副本入手后池余量不变 / 对手施法不触发本人 EoT
      （owner 隔离）/ 真实 `end_recruit_phase` 触发 EoT /
      两份副本各入手 num(0) 张 / 记录被新施放覆盖为最新一张

    Params: {0}=num(0)=3（BG36_MagicItem_372）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        last = getattr(h, "_last_tavern_spell_id", None)
        if last is None or game.db.get(last) is None:
            return None
        for _ in range(_num(game, source.card_id, 0)):
            game.pending_hand_add(
                h, game.create_spell(last, controller=h))
        return None


# ══════════════ BG36_MagicItem_390 Baller Portrait ══════════════


class BallerPortraitScript:
    """
    Natural language: [x]Get a Fire Baller or a Snow Baller. At the
    start of each turn, repeat this.

    Formal spec:
      1. 每次触发: 二选一 = `game.rng.choice([BG31_816, BG31_818])`
         ——文本无 "Choose"，"or" 二选一按随机（Cousin Errgl
         `BG35_142` "get a Mama Mrrglton or a Papa Mrrglton" 已验收
         先例; SOP §9 目标语义裁决库）
      2. 交付: `game.grant_card_copy_to_hand(hero, def)`——两者均为
         **池随从**（BG31_816 / BG31_818, tier 2, `is_pool_minion`
         36.2.2 数据核实）→ 先 `minion_pool.acquire` 占池;
         池中无副本 → 本次落空（RULES §2.4/§7.4.6）
      3. 触发点: `on_bind`（获得饰品即结算一次——"At the start of each
         turn, repeat **this**" 的双点模型，同族先例
         `BG32_MagicItem_286` Lavish Cape / `BG36_MagicItem_370`）+
         每回合 `start_of_turn`
      4. **数据链订正**: `evolution_card_id`(116736) 只指向 Fire Baller;
         Snow Baller `BG31_818` 无数据链 → 常量（36.2.2 `bg_cards.json`
         按名核实）。两者的 "Improve your future Ballers" 属各自卡脚本
         台账，不阻塞本饰品（RULES §7.4.6 "Get a X" 判定）
      5. 只进本人手牌; 满手排队（RULES §3.3）; 副本各自结算

    Test: test_batch_trinkets22.py — 绑定后手牌恰多 1 张 ∈ {Fire,
      Snow} Baller 且对应池 -1（正对照: 两者池同时排空 → 落空且手牌
      不变）/ 每回合 `start_of_turn` 再交付 1 张 / 真实
      `end_recruit_phase` 后再次交付 / 对手手牌不变 / 同 seed 序列
      可复现 / 两份副本各交付 1 张

    Params: 无模板参数（卡 id 经数据链/常量; rng 二选一无数值）
    """

    @staticmethod
    def _grant(game, hero) -> bool:
        ids = [FIRE_BALLER, SNOW_BALLER]
        pick = game.rng.choice(ids, label=_BALLER_LABEL)
        d = game.db.get(pick)
        if d is None:
            return False
        return game.grant_card_copy_to_hand(hero, d)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        BallerPortraitScript._grant(game, h)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        BallerPortraitScript._grant(game, h)
        return None


# ══════════════ BG36_MagicItem_800 Demonic Bloodletter ══════════════


class DemonicBloodletterScript:
    """
    Natural language: [x]Whenever you cast a Tavern spell, give minions
    in the Tavern +{0}/+{1} this game.

    Formal spec:
      1. on_bind: 注册 `tavern_spell_cast` 持久监听（owner=饰品; 引擎仅
         对 `is_pool_spell` 广播）: `spell.controller is 本人` → 双面结算
         （Nomi Sticker `BG30_MagicItem_544` 已验收先例）:
           a) **立即面** `BuffCurrentTavern(hero, tb)`——当前馆内全部
              随从（无种族/tier 过滤）即时 +num(0)/+num(1)、购买带走
           b) **持久面** `ApplyTavernBuff(hero, tb)`——登记
              `hero.tavern_buffs`，`refresh_tavern` 对新入馆随从自动
              应用 → "this game" 累积（打出 N 次后新入馆随从共
              +N·num(0)/+N·num(1)）
      2. 每次施放独立登记一条 `TavernBuff`（叠加式；不覆盖既有来源）
      3. 只作用于本人酒馆（`hero.tavern_buffs` 为 hero 级——对手酒馆
         不受影响，SOP §12 item 9）
      4. 落空: 非池法术（Spellcraft / 血宝石 / 效果施法）不广播该事件
         → 不触发; 馆内无随从时"立即面"无事发生但仍登记持久面
         （"this game" 对**未来**随从依然有效）
      5. 副本条款: 两份副本各注册监听 → 每次施放叠加 2×num

    Test: test_batch_trinkets22.py — 真实 `play_spell`（池法术）后馆内
      随从 +num(0)/+num(1) 且 `hero.tavern_buffs` 多 1 条（无过滤）/
      随后 `refresh_tavern` 的新随从自动继承同等增益（"this game" 持久
      面; 正对照: 无饰品时新随从无增益）/ 对手施法不加成、对手
      `tavern_buffs` 不变 / 非池法术（血宝石）不触发 / 两份副本叠加

    Params: {0}=num(0)=1 {1}=num(1)=1（BG36_MagicItem_800）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            tb = TavernBuff(atk=atk, health=health,
                            source_id=source.card_id)
            g.run_actions([ApplyTavernBuff(h, tb),
                           BuffCurrentTavern(h, tb)])

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        return None


# ══════════════ BG36_MagicItem_801 Consuming Claw ══════════════


class ConsumingClawScript:
    """
    Natural language: [x]Whenever a friendly Demon consumes a minion,
    it also gains its <b><b>Bonus Keyword</b>s</b> and +{0}/+{1}.

    Evidence: 官方 S14 Trinket 表（Lesser, cost 0）文本仅到 "Bonus
    Keywords"; 36.2.2 `CardDefs.xml` 文本含 "and +{0}/+{1}"
    （num(0)=num(1)=5）——**数值/文本以数据为准**（任务约定）。

    Formal spec:
      1. on_bind: 注册 `minion_consumed` 持久监听（owner=饰品;
         `actions/consume.py::ConsumeMinion` 结算后广播 demon=/minion=）:
         条件 = consumer 属于本人（`demon.controller is 本人`）且
         consumer 是 **Demon**（race ∈ (DEMON, ALL)——文本 "a friendly
         Demon"）
      2. 触发: `demon` 额外获得（"it also gains"——`ConsumeMinion` 已给
         基础属性）
           a) 受害者**战斗关键词**（Taunt / Divine Shield / Windfury /
              Poisonous / Venomous / Reborn / Stealth / Cleave）逐个
              `GainKeyword` 移转——"Bonus Keywords" 全仓约定集
              （Methodical Madness `BG36_880` 官方 36.2 报道口径:
              "transfer Divine Shield, Taunt or other properties";
              读取对象为受害者实体，事件触发时其关键词仍在）
           b) `Buff(demon, atk=num(0), health=num(1))` 永久
      3. 受害者无任何该集关键词 → 只给 b)（不报错）; 已拥有的关键词
       `GainKeyword` 幂等（set True）
      4. 只作用于本人 Demon（对手吞噬不触发; 本人**非 Demon** 随从吞噬
         不触发——owner + 种族双条件）
      5. 副本条款: 两份副本各注册监听 → 每次吞噬叠加 2×num

    Test: test_batch_trinkets22.py — 真实 `ConsumeMinion`（友方 Demon 吞噬
      带 Taunt+Divine Shield 的馆内随从）→ demon 获得两关键词 +
      num(0)/num(1)（正对照: 无饰品时仅获受害者属性）/
      受害者无关键词集成员 → 只有 +num（不误移转）/
      友方**非 Demon** 吞噬不触发 / 对手 Demon 吞噬不触发 /
      两份副本叠加 / 馆内受害者回池（池守恒断言）

    Params: {0}=num(0)=5 {1}=num(1)=5（BG36_MagicItem_801）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def cond(demon=None, **kw):
            return (isinstance(demon, Minion) and demon.controller is h
                    and demon.race in _DEMON_RACES)

        def on_consumed(g, demon=None, minion=None, **kw):
            if minion is None:
                return
            actions = []
            for tag in _BONUS_KEYWORD_TAGS:
                if minion.has(tag):
                    actions.append(GainKeyword(demon, tag))
            actions.append(Buff(demon, atk=atk, health=health))
            g.run_actions(actions)

        game.events.register(Listener(event=MINION_CONSUMED, owner=source,
                                      callback=on_consumed, condition=cond))
        return None


# ══════════════ BG36_MagicItem_810 Inductive Gyroblade ══════════════


class InductiveGyrobladeScript:
    """
    Natural language: [x]At the end of your turn, get a {0}/{1}
    <b>Magnetic</b> Satellite. <i>(Improved by each Tavern spell you've
    cast this turn!)</i>

    Evidence:
      - 官方 S14 Trinket 表: Lesser "get a **4/4** Magnetic Satellite" /
        Greater "get a **8/8** …" —— 印面值 num(0)/num(1) 即**本回合
        0 次施放**时的尺寸（Lesser num=4/4 / 升级变体 810t num=8/8）。
      - 增量 = 印面值: 论坛实测帖
        https://us.forums.blizzard.com/en/hearthstone/t/balinda-stonehearth-doesnt-improve-inductive-gyroblade/165377
        "each spell that casted twice only gave the trinket **+4/+4**"
        （一次施放 = +num(0)/+num(1)）。

    Formal spec:
      1. `end_of_turn`（饰品 EoT 钩子）: 尺寸 =
         num(0) * (1 + spells) / num(1) * (1 + spells)，其中 spells =
         `hero.TAVERN_SPELLS_CAST_THIS_TURN`（引擎对 `is_pool_spell`
         累计的权威 tag——"each Tavern spell you've cast **this
         turn**" 是本回合口径，引擎每回合重置）
      2. 产物: Satellite token `BG31_171t`（非池 → 零池操作;
         `batch_magnetic`/`batch_consume` 裁定的 token 身份）经
         `create_minion` + `BASE_ATK/BASE_HEALTH/HEALTH` 覆盖为上述
         尺寸（Beetle/Reusable Batteries 先例）→ `pending_hand_add`
         （"get" = 进手牌; 满手排队 RULES §3.3）
      3. 数值: num(0)/num(1) 分别读基础版（4/4）与升级变体（8/8）——
         同一脚本类注册两个 id，金色/升级差异由各自 CardDef 体现
      4. 落空: 无 `TAVERN_SPELLS_CAST_THIS_TURN`（0 次）仍给基础尺寸
         （文本 "(Improved by …)" 是增量，非门槛）; 卡定义/参数缺失
         fail-loud
      5. 只进本人手牌; 副本每次 EoT 各给一枚

    Test: test_batch_trinkets22.py — 0 次施放 EoT → 手牌 Satellite
      属性 == num(0)/num(1) / 真实施放 n 张池法术（引擎计数）→ 属性 ==
      num(0)*(1+n) / num(1)*(1+n)（旧式"快照基线"实现在绑定前施放时
      会少算，本测试钉死本回合口径）/  非池法术（血宝石）不改善 /
      真实 `end_recruit_phase` 触发 EoT 且下回合计数归零 /
      池余量不变（token 不占池）/ 升级变体 810t 给 8/8 基础尺寸 /
      两份副本各给一枚

    Params: {0}=num(0)=4 {1}=num(1)=4（BG36_MagicItem_810;
            升级变体 BG36_MagicItem_810t = 8/8）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        base_atk = _num(game, source.card_id, 0)
        base_health = _num(game, source.card_id, 1)
        spells = h.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0)
        atk = base_atk * (1 + spells)
        health = base_health * (1 + spells)
        sat = game.create_minion(SATELLITE, controller=h)
        if sat is None:
            return None
        sat.set(GameTag.BASE_ATK, atk)
        sat.set(GameTag.BASE_HEALTH, health)
        sat.set(GameTag.HEALTH, health)
        game.pending_hand_add(h, sat)
        return None


# ══════════════ BG36_MagicItem_812 Emergency Gearblade ══════════════


class EmergencyGearbladeScript:
    """
    Natural language: At the end of your turn, cast Repair Job on your
    left-most Mech.

    Formal spec:
      1. `end_of_turn`: 目标 = 本人棋盘**最左**的 Mech（race ∈
         (MECH, ALL)——Amalgam 视为机械，RULES §6.18）; 无 Mech →
         本次落空（不报错、不消耗任何资源）
      2. 施放: `game.cast_spell_effect(hero, repair_job_id, target=目标)`
         ——效果施法统一入口（RULES §7.4.7b: 不经手牌/不计费/不动法术
         池/不广播 `tavern_spell_cast`; 会广播 `spell_resolving` 且
         `RepairJobScript` 的 `tavern_spell_buff` 出口吃
         `TAVERN_SPELL_EXTRA_*`）
      3. Repair Job id 经**数据链** `game.trinket_related_card(本饰品)`
         （`evolution_card_id` 133711 → `BG36_624`; 池法术 T3，脚本已由
         batch_spells_final 迁移——载荷就绪，RULES §7.4.6 例外条款不
         触发）。解析失败 → 落空
      4. 目标在施放瞬间已离场 → `cast_spell_effect` 内部落空返回 False
      5. 只作用于本人棋盘; 副本各施放一次

    Test: test_batch_trinkets22.py — 棋盘 [非机械 A, 机械 M1, 机械 M2]
      EoT → **只有 M1** 获得 Repair Job 的 +num(0)/+num(1)（正对照:
      无饰品不变）/ 无 Mech → 落空且资源不变 / 真实
      `end_recruit_phase` 触发 EoT / 对手棋盘不变 /
      `cast_spell_effect` 不动法术池、不计费 / 两份副本各施放一次

    Params: Repair Job 自身 {0}=4 {1}=8（BG36_624）; 本饰品无模板参数
    """

    @staticmethod
    def _leftmost_mech(hero) -> Optional[Minion]:
        for m in hero.board:
            if not m.dead and m.race in _MECH_RACES:
                return m
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        target = EmergencyGearbladeScript._leftmost_mech(h)
        if target is None:
            return None
        rel = game.trinket_related_card(source.card_id)
        if rel is None:
            return None
        game.cast_spell_effect(h, rel.id, target=target)
        return None


# ══════════════ BG36_MagicItem_820 Flighty Portrait ══════════════


class FlightyPortraitScript:
    """
    Natural language: [x]Get a Flighty Scout. After you cast a Tavern
    spell, give Flighty Scouts in your hand and warband +{0}/+{1}.

    Formal spec:
      1. on_bind: 数据链交付 Flighty Scout（`evolution_card_id`(120677)
         → `BG32_330`，池随从 T1，统一入口占池 1 份; 脚本已由
         batch_consume 迁移——`hand_soc` SoC 载荷就绪）
      2. 注册 `tavern_spell_cast` 持久监听（owner=饰品; 引擎仅对
         `is_pool_spell` 广播）: `spell.controller is 本人` → 对
         **手牌 + 棋盘**中所有 Flighty Scout 各 `Buff(+num(0)/+num(1))`
         永久（"give … +X/+Y" = 永久增益，SOP §3 动词表）
      3. 身份判定 `_base_card_id`（金色 → `TRIPLE_BASE_CARD_ID`）==
         `BG32_330`——金色 Flighty Scout（`BG32_330_G`，独立卡定义）
         同样属于 "Flighty Scouts"（RULES §2.3 金色=独立 def 但同名）
      4. 范围 = 本人手牌 + 本人棋盘（文本明示; **不含**酒馆——与
         Demonic Bloodletter 的 "minions in the Tavern" 区分）
      5. 落空: 非池法术不触发; 无 Flighty Scout 时无事发生
      6. 副本条款: 两份副本各注册监听 → 每施放叠加 2×num

    Test: test_batch_trinkets22.py — 绑定后手牌出现 Flighty Scout
      （池 -1）/ 真实 `play_spell`（池法术）→ 手牌与棋盘的 Flighty
      Scout 同时 +num(0)/+num(1)（正对照: 无饰品不变）/
      其他随从与对手同类随从不变（owner+身份双隔离）/
      金色 Flighty Scout 也算 / 非池法术（血宝石）不触发 /
      真实 `end_recruit_phase` 后监听仍在（跨回合持久）/
      两份副本叠加

    Params: {0}=num(0)=3 {1}=num(1)=3（BG36_MagicItem_820）
    """

    @staticmethod
    def _is_flighty(game, entity) -> bool:
        if not isinstance(entity, Minion):
            return False
        return _base_card_id(game, entity) == FLIGHTY_SCOUT

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = game.trinket_related_card(source.card_id)
        if rel is not None:
            game.grant_card_copy_to_hand(h, rel)
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            targets = [e for e in list(h.hand)
                       if FlightyPortraitScript._is_flighty(g, e)]
            targets += [e for e in list(h.board)
                        if FlightyPortraitScript._is_flighty(g, e)]
            if not targets:
                return
            g.run_actions([Buff(e, atk=atk, health=health)
                           for e in targets])

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        return None


# ══════════════ BG36_MagicItem_830 Bloodfury Shield ══════════════


class BloodfuryShieldScript:
    """
    Natural language: Whenever you cast a Tavern spell, add a
    <b>Fodder</b> to your next <b>Refresh</b>.

    Formal spec:
      1. on_bind: 注册 `tavern_spell_cast` 持久监听（owner=饰品）:
         `spell.controller is 本人` → `game._fodder_refresh_pending[hero]`
         累加 1 次刷新额度（协议 v2 元组 `(剩余刷新次数, 每次附加枚数)`:
         每次施放 `(prev[0] + 1, max(prev[1], 1))` → 之后每次刷新各附加
         1 枚 Demon Fodder token 并递减计数）
      2. Fodder token = `constants.FODDER_CARD_ID`（BG35_150t，非池卡
         → 零池操作; 生成点为引擎 `refresh_tavern`，本脚本不创建实体）
      3. 协议同源: Demonology Dark Gift（game.py）/ Twisted Wrathguard
         （batch_econ_misc2）——引擎消费点唯一，脚本侧只写额度
      4. 只作用于本人（对手施法不计入; `_fodder_refresh_pending` 按
         hero 键控）
      5. 落空: 非池法术不触发; 副本条款 → 每次施放累加 2 次刷新额度

    Test: test_batch_trinkets22.py — 真实 `play_spell` 后
      `_fodder_refresh_pending[本人] == (1,1)`（正对照: 无饰品为空）/
      真实 `refresh_tavern` 后酒馆含 Fodder token 且额度清零 /
      连施 2 次 → 额度 2、连续两次刷新各得 1 枚（不是一次 2 枚）/
      对手施法不计入 / 非池法术（血宝石）不触发 /
      两份副本叠加（每次施放 +2）

    Params: 无模板参数（"a Fodder" = 1 枚，文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            prev = g._fodder_refresh_pending.get(h, (0, 0))
            g._fodder_refresh_pending[h] = (
                prev[0] + 1, max(prev[1], _FODDER_PER_CAST))

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        return None


# ══════════════ BG36_MagicItem_831 Felsteel Cleaver ══════════════


class FelsteelCleaverScript:
    """
    Natural language: [x]After you cast a spell on a Tavern minion, a
    random friendly minion consumes it to gain its stats.

    Formal spec:
      1. on_bind: 注册 `card_played` 持久监听（owner=饰品）: 条件
         `isinstance(card, Spell)` 且 `card.controller is 本人`——
         `card_played` 在法术效果结算后广播且携带 `target=`（引擎
         Wave2 G2 接线; 池法术 / Spellcraft / 生成法术统一路径）
      2. 回调内验目标: `isinstance(target, Minion)` 且 `target in
         hero.tavern`（"a Tavern minion" = **本人**酒馆展示区随从;
         仓内先例 `BG27_514t` Siren's Song 以酒馆随从为定向目标）
      3. 触发: 随机友方棋盘随从（`game.rng.choice`，label 审计）作为
         consumer → `ConsumeMinion(consumer, target)`（Action:
         消费者获得受害者 atk/max_health 永久 Buff、酒馆来源回池、
         不触发亡语、fire `minion_consumed`）; 本人棋盘为空 → 落空
         （无 consumer，不消耗、不报错）
      4. 只作用于本人（对手施法/对手酒馆不触发）; 目标在回调时已
         离场（被法术效果移除）→ 落空
      5. 副本条款: 两份副本各注册监听 → 每次命中产生两位 consumer

    Test: test_batch_trinkets22.py — 真实 `play_spell`（定向法术，目标
      为酒馆随从）→ 酒馆该随从被移除、随机友方获得其
      atk/max_health、受害者回池（正对照: 无饰品不变）/
      目标为**棋盘**随从（非酒馆）→ 不触发 /
      空棋盘 → 落空且酒馆不变 / 对手施法不触发（owner 隔离）/
      两份副本 → 两位 consumer 各获属性（酒馆只剩一个受害者 →
      第二次落空） / 真实 `end_recruit_phase` 后监听仍在

    Params: 无模板参数（"a random friendly minion" / "its stats" 全动态）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, target=None, **kw):
            if not isinstance(card, Spell) or card.controller is not h:
                return
            if not isinstance(target, Minion) or target not in h.tavern:
                return
            consumers = _living(h)
            if not consumers:
                return
            consumer = g.rng.choice(consumers, label=_CLEAVER_LABEL)
            g.run_actions(ConsumeMinion(consumer, target))

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════ DEFERRED（不注册） ══════════════


# 2026-09-18: `CyclistPortraitScript` 占位 DEFERRED 台账删除——
# `BG36_MagicItem_362` 已由 batch_trinkets31 注册
# （`Buff(persist=True)` 按来源跨战斗持久化 + 家族规则读取点
# `Game.add_persist_source` / `Game.persist_source_id`，
# RULES §3.5 例外 4）。载荷 `BG31_925` 已由 batch_deathrattle 注册。


class MultilayeredShieldScript:
    """
    Natural language: [x]Your Tavern spells give an extra +{0}/+{1}.
    <i>(Improved by each different friendly minion type!)</i>

    Status: DEFERRED — requires 动态 `TAVERN_SPELL_EXTRA_*` 求值点
    Dependency:
      1. `TAVERN_SPELL_EXTRA_ATK/HEALTH` 是**静态** hero tag，唯一读取点
         `racefx.tavern_spell_buff(target, atk, health)` 在法术结算时
         一次性读取。本卡的额外值随**棋盘不同随从类型数**实时变化
         （入场/死亡/出售/金色化/`Transform`/战斗复原/换入），静态写入
         无法表达（写一次 → 之后不再更新 = 空转标记，SOP §16b item 32
         明令"光环用入场即 buff 近似会漏路径"）。
      2. 官方 S14 Trinket 表文本未给出"每个类型"的增量口径（印面值
         +1/+2 是基准还是 1 个类型时的值），两种读法
         （`num0*(1+T)` vs `num0*T`）无权威（SOP §6b 第 4 步）。
    Implementation path: `racefx.tavern_spell_buff` 增加**动态提供者**:
      `hero.tavern_spell_extra_providers: list[(source, fn(hero)->(atk,
      health))]`，结算时逐条求值（与 `hero.race_auras` /
      `game.add_tier_aura` 的"读取时校验 source 仍在场"生命周期同构）;
      同时取得官方对 T 口径的权威（wiki 卡页 Notes / 实测）。
      阻塞卡: BG36_MagicItem_373。

    Test: 不注册（DEFERRED）——同上台账守卫。
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class AmplifyingEssenceScript:
    """
    Natural language: [x]Your Elementals give an extra +{1}/+{2}. After
    you play 5 Elementals, improve this. <i>({0} left!)</i>

    Status: DEFERRED — requires 元素 give-stats 效果的
      `ELEMENTAL_EXTRA_ATK/HEALTH` 消费点
    Dependency: `GameTag.ELEMENTAL_EXTRA_HEALTH(1055)` /
      `ELEMENTAL_EXTRA_ATK(1057)` 已入册，唯一读取方
      `batch_consume.elemental_buff()` 在全仓**零生产调用点**
      （`grep -rn "elemental_buff(" hsrl2/` 只命中定义）——元素
      give-stats 随从脚本（Moat Custodian / Glowing Cinder /
      Sand Swirler 等）没有任何一处经该出口构造 Buff。本卡只会写 tag
      而无人读取 = 100% 空转（同一缺口的既有 DEFERRED:
      `BG32_MagicItem_802` Fountain Pen / `BG32_841` Sand Swirler）。
    Implementation path: 主线把 `elemental_buff`（或其等价物）并入
      `hsrl2/actions/racefx.py`，让**全部**元素 give-stats 效果统一经
      该出口构造 Buff（与 `tavern_spell_buff` 对酒馆法术的地位相同），
      并加 AST/行为测试守住"消费点可达"。随后本卡（含 "After you
      play 5 Elementals, improve this" 的滚动计数）按 Heart of the
      Forest 模式注册。阻塞卡: BG36_MagicItem_380（+ Fountain Pen /
      Sand Swirler）。

    Test: 不注册（DEFERRED）——同上台账守卫。
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class AssemblerPortraitScript:
    """
    Natural language: [x]<b>Start of Combat:</b> <b>Magnetize</b> an
    Auto Assembler to all your Mechs.

    Status: DEFERRED — requires 战斗内磁力吸附的战斗级恢复
    Dependency:
      1. `game.attach_magnetic(hero, attached, host)` 把附件 id 追加到
         `game._magnetic_stack[host.uuid]`（宿主亡语栈/关键词/属性并入
         的数据源），而 `run_combat` 的快照/恢复（game.py finally）**不
         包含** `_magnetic_stack`：SoC 吸附会在每个战斗开始时再次追加，
         宿主的亡语栈无限累积（与 SOP §13 item 2/3 的"无界循环"同类
         风险）。
      2. "an Auto Assembler" 的来源语义未定（`BG32_172` 是**池随从**
         T4 `is_pool_minion=True`）：是每只 Mech 各占 1 份池副本
         （多 Mech 时可能池空），还是无条件生成副本（token 式）？
         无权威（SOP §6b 第 4 步）。
    Implementation path:
      (a) 引擎把 `_magnetic_stack` 纳入 `run_combat` 快照并在 finally
          恢复（或提供 `attach_magnetic(..., combat_only=True)`——
          战斗结束剥离本次追加项）;
      (b) 裁定 Auto Assembler 的副本来源（池占返 vs 生成），随后
          本卡 SoC 对每只 `race ∈ (MECH, ALL)` 的友方随从调用
          `attach_magnetic`。阻塞卡: BG36_MagicItem_841
          （同族战斗内磁化: `BG32_174` Electron, Powered Up /
          `BG34_Giant_610` Timewarped Electron 亦待此原语）。

    Test: 不注册（DEFERRED）——同上台账守卫。
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        return None


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册本批 12 张 CORRECT 饰品（4 张 DEFERRED 不注册）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (ESCAPEE_PORTRAIT, EscapeePortraitScript),
        (MALDRAXXUS_DAGGER, MaldraxxusDaggerScript),
        (HONEYCOMB_RING, HoneycombRingScript),
        (SPHERE_OF_MEMORY, SphereOfMemoryScript),
        (BALLER_PORTRAIT, BallerPortraitScript),
        (DEMONIC_BLOODLETTER, DemonicBloodletterScript),
        (CONSUMING_CLAW, ConsumingClawScript),
        (INDUCTIVE_GYROBLADE, InductiveGyrobladeScript),
        (INDUCTIVE_GYROBLADE_T, InductiveGyrobladeScript),
        (EMERGENCY_GEARBLADE, EmergencyGearbladeScript),
        (FLIGHTY_PORTRAIT, FlightyPortraitScript),
        (BLOODFURY_SHIELD, BloodfuryShieldScript),
        (FELSTEEL_CLEAVER, FelsteelCleaverScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
