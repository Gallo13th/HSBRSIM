"""批次 trinkets20 — 饰品第二十批（作业单 2026-09-14，台账片 6/7）。

与既有批次（batch_trinkets1..19/21）的 id 集合互不相交；16 张目标 id
全部在 `CardDB.trinket_offer_pool()` 中（16/16 运行核验）。数值一律
`CardDef.num(i)`；`CardDef` 无参数而文本含字面量者按 SOP §3 在各类
`Params:` 行声明为文本权威。关联卡一律走数据链
`CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6，零硬编码
卡 id；Spellcraft 法带走 `CardDef.spellcraft_id`）；随机一律 `game.rng`；
全部状态写在 hero 作用域 / source 实体属性 / 监听闭包（无 game 级 flag
——SOP §12 item 9）。

注册 11 张饰品 + 1 张 Spellcraft 法术（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG35_MagicItem_931  Transcribing Typewriter — 下一次购买的 num(1)
                                                 个随从各额外入手一份
                                                 白板副本
  BG36_MagicItem_201  Lionfish Portrait      — Get a Lurking Lionfish;
                                                 友方野兽每次攻击 +num(0)/+num(1)
  BG36_MagicItem_206  Ominous Stone          — Discover 一个 Tier 4 的
                                                 最常见类型随从并带
                                                 Dark Gift
  BG36_MagicItem_208  Floating Candle Set    — Spellcraft（208t）:
                                                 Trigger a friendly
                                                 minion's Deathrattle
  BG36_MagicItem_211  Lovely Locket          — 对友方随从施法后，把同一
                                                 法术随机再施于另一友方
                                                 随从（wiki [Random]）
  BG36_MagicItem_217  Funeral Wreath         — 友方复生后入手其白板副本
                                                 （每场战斗 num(1) 次）
  BG36_MagicItem_301  Lockbox Portrait       — Get a Lockbox; 已有则提前
                                                 num(0) 回合开启; 每回合
                                                 开始重复
  BG36_MagicItem_302  Gold Mallet            — EoT: 全体随从
                                                 +(num(0)+GMP)/
                                                 +(num(1)+GMP)，GMP =
                                                 本局已打出金色随从数
  BG36_MagicItem_303  Glass of Perspective   — 随机 Get 一张 Choose One
                                                 卡; 每回合开始再来一张
  BG36_MagicItem_309  Wax Lance              — Discover 一个 Tier 7 随从
                                                 并带 Dark Gift
  BG36_MagicItem_361  Myrmidon Sticker       — SoC: 最左与最右纳迦属性
                                                 翻倍
  BG36_MagicItem_208t Floating Candle Set    — Spellcraft 法术本体:
                                                 定向触发友方亡语

DEFERRED 5 张（**不注册**；逐张给出依赖 + 实现路径——SOP §6b 二态铁律）
════════════════════════════════════════════════════════════════════════
  - BG35_MagicItem_930 Warband Whistle — "Gain a free **Refresh** that
    contains plain copies of minions in your warband."
    **引擎缺"自定义内容的免费刷新"协议**: `refresh_tavern`
    （`Game.refresh_tavern`）只会按 `minion_pool` 加权抽取整馆，无"本次刷新的
    内容 = 指定 card_id 列表（且不占池）"的入口；`FREE_REFRESH_REMAINING`
    只控制费用不控制内容。此外三条语义无权威: (a) 副本是否占池
    （wiki Patch 35.6.0.243002 bugfix "could be overwritten by refresh
    effects" 说明它占用一个**独立刷新槽**，与普通刷新不叠加）;
    (b) 同名随从是否允许重复（warband 天然可同名）; (c) 该刷新被再次
    刷新时如何回池。实现路径: 引擎新增
    `hero._custom_refresh: Optional[list[str]]`（一次性）+
    `refresh_tavern` 命中时以该列表填充展示区（副本走
    `create_minion`，按"复制体不占池"记账）、消耗后清空; 并在 RULES
    §7.4 记录刷新槽优先级（本卡刷新先于/独立于自动刷新）。被阻塞卡: 930。
  - BG36_MagicItem_204 Plaguerunner Portrait — "Get a Plaguerunner.
    After you destroy a Plaguerunner outside combat, get a plain copy."
    **`minion_destroyed` 事件 + `game.destroy_minion()` 缺失**（2026-09-02 已落地）（ENGINE_
    BACKLOG §A4，与 BG30_MagicItem_204 Kel'Thuzad Portrait /
    BG30_MagicItem_205 Maw Caster Portrait 同缺口）。`DEATH` 事件无施动
    者、无法区分"被效果摧毁"与"战斗/招募期死亡"，"outside combat" 更
    需要 `destroyed_in_combat` 位。实现路径: 新事件
    `minion_destroyed(hero=, minion=, in_combat=)` + 摧毁统一入口
    `game.destroy_minion(hero, minion)`（置 HEALTH 0 → check_deaths →
    广播该事件），本卡监听并按 `minion.card_id` ∈ Plaguerunner 家族
    （关联卡 dbf 126451 → BG34_690 + 其金色 `_G`）发放白板副本。
    被阻塞卡: 204。
    Status: 已由 batch_trinkets26 注册（minion_destroyed/destroy_minion 原语已于 2026-09-02 落地）
  - BG36_MagicItem_214 Insurrectionist's Blade — "At the end of your
    turn, trigger all friendly **Rallies**."
    **引擎无"攻击外触发 Rally"协议，且目标的 ctx 语义无权威**。
    `Game.run_rally(attacker, ctx)` 只在
    `CombatScheduler._execute_attack` 与
    `Game.recruit_phase_attack` 两处被调用，ctx 恒为
    `{"target": defender}`; 存活 rally 脚本全部经 `_rally_target(ctx)`
    取防御者（batch_rally.py/batch_rally2.py）。EoT 无防御者，
    官方未公布"被触发的 Rally 以谁为目标"（自指/随机敌方/空目标三读
    法都无证据）。XML 权威确认触发时机（CardDefs.xml 133402:
    `END_OF_TURN_TRIGGER=1` + `BACON_RALLY=1`——与文本一致）。
    实现路径: (a) 先由官方/实测裁定无攻击者时 rally 的 `target` 取值
    并写入 RULES §6.16; (b) 引擎新增
    `Game.trigger_friendly_rallies(hero, ctx)`（逐存活友方
    `run_rally(m, ctx)`，含 `rally_extra` 配额）——**禁止**脚本自行
    调 `run_rally`（会绕过额外触发配额与磁力栈）。被阻塞卡: 214。
  - BG36_MagicItem_216 Eternal Portrait — "Get a Golden Eternal Knight.
    After a friendly Undead dies, your Eternal Knights have +{0}/+{1}
    this game."
    第一条款可交付（数据链 95262 → BG25_008_G，`triple_base_id`
    95261 → BG25_008，`grant_card_copy_to_hand(base, golden=True)`）;
    **第二条款双重阻塞**: (a) "your Eternal Knights have +X this game"
    是**按卡家族的光环**（对照 BG25_008 自身 "Has +{0}/{1} ... 
    (wherever this is)" 显式写了 wherever，本卡没写）+ 永久累积，
    引擎只有 `hero.race_auras`（种族维度）与 `hero.tier_auras`（档位
    维度），无"指定卡家族"读取点; SOP §32 明确禁止用"入场即 buff"
    近似光环（`Transform` / 直接 `board[idx]=` 等非 summon 入板路径
    会漏）。实现路径: 引擎新增 `game.add_card_aura(source, family_ids,
    atk, health)` → `hero.card_auras[uuid] = (frozenset(ids), atk,
    health)`，读取点并入 `Entity._aura_atk/_aura_health`（与
    `_tier_aura_active` 同构，source 离场即失效）; (b) 官方对作用域
    （仅棋盘 / 含手牌 / wherever）与"金色 Eternal Knight 是否计入"的
    证据。被阻塞卡: 216。
  - BG36_MagicItem_308 Trailblazer Sticker — "Your **Choose One** cards
    have both effects combined."
    引擎的 CHOOSE_BOTH 读取点只有**棋盘随从**两处:
    `Game.play_minion`（`any(m.has(GameTag.CHOOSE_BOTH)
    for m in hero.board) or minion.has(...)`）与 `play_spell`
    （`Game.play_spell` 中 `any(... for m in hero.board)`）——饰品实体不在
    棋盘，脚本写 `hero.set(GameTag.CHOOSE_BOTH, True)` 无任何读取方
    （W3 空转标记）。实现路径: 两处 both 判定增
    `or hero.get(GameTag.CHOOSE_BOTH, False)`（或统一抽
    `Game.choose_both_active(hero)`），并补盘外来源（饰品/任务奖励）
    的引擎回归测试; 之后本卡 `on_bind` 置 hero 级 CHOOSE_BOTH 即
    CORRECT。被阻塞卡: 308。

**关联卡台账**（RULES §7.4.6 —— 交付正确即 CORRECT，关联卡自身脚本未
迁移不阻塞；下表登记被授予卡当前的迁移状态供主线跟踪）:
  | 饰品 | 关联卡（数据链 dbf → id） | 被授予卡脚本状态 |
  |---|---|---|
  | BG36_MagicItem_201 | 132794 → BG36_201 Lurking Lionfish (T2, 池随从) | 已注册（minions.py LionfishScript） |
  | BG36_MagicItem_208 | spellcraft_id 133396 → BG36_MagicItem_208t (Spellcraft 法术) | **本批注册**（FloatingCandleSetSpellScript） |
  | BG36_MagicItem_301 | 132766 → BG36_520t Lockbox (法术, 非池) | 引擎内建（`game._open_lockbox`），无独立脚本 |
  | BG36_MagicItem_216 | 95262 → BG25_008_G Eternal Knight (金色, 非池) | 已注册（batch_counters.EternalKnightScript）——整卡仍 DEFERRED（第二条款） |
  | BG36_MagicItem_204 | 126451 → BG34_690 Plaguerunner (T4, 池随从) | 已注册（batch_deathrattle2.PlaguerunnerScript）——整卡已由 batch_trinkets26 注册（destroy 事件已于 2026-09-02 落地; 原 DEFERRED 台账保留） |
  注: `BG36_MagicItem_206` / `BG36_MagicItem_309` 的 "with a Dark Gift"
  不授予关联卡，走引擎 `game.apply_dark_gift` 协议（RULES §9.x），交付
  物为"被发现的随从 + 一枚合法 Dark Gift"，无关联卡台账行。

**协议注记**:
  - `BG36_MagicItem_206` / `BG36_MagicItem_309` 走 `PendingChoice
    (kind="dark_gift")`，与 `Game.use_dark_gift` 同构:
    选项生成即 `minion_pool.acquire` 预留、resolve 保留选中释放其余
    （SOP §13 item 5 的"n 选 1 必须预留"契约; 早期 Tras'tath 的
    resolve 才 acquire 属旧模式，本批不复制该缺陷）。gift 配对复用
    `batch_hero_combat3._pair_gift_options`（trinkets16 跨批复用先例）。
  - `BG36_MagicItem_206` 的 "your most common type" 用
    `darkgifts.most_common_board_race`（只计棋盘有种族随从、ALL 不计入、
    并列 rng 任选）; 无有种族随从 → **不限族**（`BG33_814 Friendly
    Bounty` "Get a random minion of your most common type" 的同文先例，
    batch_spells4 已验收）。
  - `BG36_MagicItem_302` 的 "(Improved by Golden minions you've played
    this game!)" 按仓内既有 "Improved by" 家族**加法**裁定: 基值 +
    每实例 +1（`batch_unfreeze.HooktuskScript` "num(0)+GMP/num(1)+GMP"
    与 `batch_battlecry.LovesickBalladistScript` "Improved by each Gold
    you spent this turn" = num(1)+GOLD_SPENT 的已验收先例）。GMP =
    `hero.GOLDEN_MINIONS_PLAYED`（tag 1063，play_minion 对 is_golden
    实体自动递增，SOP §10）。
  - `BG36_MagicItem_211` 监听 `card_played`（法术侧在效果**结算后**广播
    且带 `target=`（`Game._finish_play_spell` 结尾）——恰是 "After you cast a spell on a
    friendly minion" 的时点），再施放走 `game.cast_spell_effect`
    （不广播 card_played/spell_resolving → 天然无递归）。
  - `BG36_MagicItem_217` 的 "(N times per combat.)" 采用 batch_trinkets8
    `DivineSignetScript` / `MechagonAdapterScript` 已验收口径:
    `game.in_combat` 闸门 + `start_of_combat` 重置额度。
  - `BG36_MagicItem_201` 的 "Whenever a friendly Beast attacks" 监听
    `before_attack`（`CombatScheduler._execute_attack` 与
         `Game.recruit_phase_attack` 招募期攻击两路统一
    广播），**不设** `in_combat` 闸门（文本无 "per combat"、wiki 分类
    无 Combat-related——对照 Divine Signet 的 Combat-related 裁定）。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff
from hsrl2.actions.discover import _pool_candidates
from hsrl2.constants import LOCKBOX_CARD_ID
from hsrl2.darkgifts import most_common_board_race
from hsrl2.events import (
    BEFORE_ATTACK,
    CARD_PLAYED,
    MINION_BOUGHT,
    REBORN_EVENT,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

import hsrl2.constants as C

# Natural Blessing 之外本批自用的匹配族（Amalgam 全种族，RULES §6.4）
_BEAST_RACES = (Race.BEAST, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)

# "Tier 4" / "Tier 7" 为文本字面量（BG36_MagicItem_206 无 {0} 占位符，
# 其 num(0)=2 无任何文本引用；309 num 全 None）
_OMINOUS_TIER = 4
_WAX_LANCE_TIER = 7


def _hero(ctx):
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _base_def(game, card_id: str):
    """卡 id 的**基础**定义（金卡定义 → `triple_base_id` 回落）。

    用于 "get a **plain** copy of it" 家族: 金卡是独立 CardDef，
    文本明示 plain → 交付非金副本。
    """
    d = game.db.get(card_id)
    if d is None:
        return None
    if d.is_golden_def and d.triple_base_id is not None:
        base = game.db.by_dbf(d.triple_base_id)
        if base is not None:
            return base
    return d


def _has_deathrattle(game, m: Minion) -> bool:
    """实体是否会真的触发亡语（含磁力栈叠的同钩子——game.py
    `_has_deathrattle_hook` 的脚本侧镜像；不引用引擎私有方法）。
    """
    if m.has(GameTag.DEATHRATTLE):
        return True
    script = getattr(m, "scripts", None)
    if script is not None and getattr(script, "deathrattle", None) is not None:
        return True
    for aid in getattr(game, "_magnetic_stack", {}).get(m.uuid, []):
        ad = game.db.get(aid)
        if ad is not None and "deathrattle" in ad.keywords:
            return True
    return False


def _dark_gift_discover(game, hero, card_ids) -> int:
    """「Discover a <候选集> with a **Dark Gift**」统一协议。

    与 `Game.use_dark_gift` 同构:
      1. 从候选随机抽 ≤3 个不同 card_id（trio）
      2. 每个配一枚**互不相同**的合法 Dark Gift——直接复用引擎
         `Game._pair_gifts(hero, trio, 候选, turn=)`（**含"某位无合法
         gift 则从候选换随从重抽 ≤20 次"**）: 旧实现用
         `_pair_gift_options`（无重抽）→ T7 三人组里有一张配不出 gift
         时只提供 2 个选项（Discover 3 选项退化，2026-09-02 对抗审查
         证伪 `BG36_MagicItem_309`）。窗口回合取
         `max(game.turn, C.DARK_GIFT_START_TURN)`——饰品在 T6+ 购买但
         同一断言对开局授予也成立
      3. **预留语义**（RULES §6.18 / SOP §13 item 5）: 选项生成即
         `minion_pool.acquire`，resolve 保留选中、release 其余
      4. resolve: `create_minion` → `apply_dark_gift` → `pending_hand_add`
         （满手排队 RULES §3.3）

    返回提供选项数（0 = 候选/合法 gift/预留三重落空之一，不产生
    PendingChoice）。
    """
    if not card_ids:
        return 0
    k = min(3, len(card_ids))
    trio = (game.rng.sample(card_ids, k, label="trinket_dark_gift_trio")
            if k < len(card_ids) else list(card_ids))
    eff_turn = max(game.turn, C.DARK_GIFT_START_TURN)
    paired = game._pair_gifts(hero, trio, list(card_ids), turn=eff_turn)
    options = [(cid, gid) for (cid, gid) in paired
               if game.minion_pool.acquire(cid)]
    if not options:
        return 0

    def resolve(pick) -> None:
        if pick not in options:
            raise GameStateError(
                f"dark gift discover pick {pick} 不在提供选项中 {options}")
        card_id, gift_id = pick
        for cid, _gid in options:
            if cid != card_id:
                game.minion_pool.release(cid, 1)
        m = game.create_minion(card_id, controller=hero)
        game.apply_dark_gift(m, gift_id)
        game.pending_hand_add(hero, m)

    game.pending_choices.append(PendingChoice(
        hero, options, "dark_gift", resolve_callback=resolve))
    return len(options)


# ══════════════════ BG35_MagicItem_931 Transcribing Typewriter ══════════════════


class TranscribingTypewriterScript:
    """
    Natural language: [x]Get an extra copy of the
    next {1} minions you buy.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind: `source._typewriter_left = num(1)`——文本 "the next {1}
         minions you buy" 的 {1}=num(1)=2 是**额度总数**; `{0}`=num(0)
         是同值的实时计数占位符（36.2.2 数据核实 num(0)==num(1)==2）
      2. 持久 `minion_bought` 监听（owner=饰品; `Game.buy_from_tavern` 在购买入手后
         广播 `minion=`）:
         - 条件 `minion.controller is 本人` 且额度 > 0
         - 命中: `grant_card_copy_to_hand(本人, 该随从 CardDef,
           golden=该实体 is_golden)`——**白板副本**入手（池内随从
           `minion_pool.acquire` 占池、池空落空; 满手 `pending_hand_add`
           排队 RULES §3.3）; 副本金色状态随购买实体（Sinstone Sticker
           "金色发现的副本丢金色"修复同口径）
         - **成功才扣减额度**（落空不消耗——Primordial Terrarium
           "折扣只在成交时消耗"同族裁定; 池耗尽时玩家仍有剩余额度）
      3. 只作用于本人购买（对手购买不触发）; 只进本人手牌
      4. 额度用尽后监听器保持注册但不再生效（一次性语义）

    Test: test_batch_trinkets20.py — 绑定后额度 == num(1); 真实
      `buy_from_tavern` 购买 2 只 → 手牌各多 1 份同卡白板副本且池各
      -1（正对照: 无饰品买入不产生额外副本）/ 第 3 次购买不再复制
      （一次性）/ 池耗尽时购买不扣额度、之后购买仍复制（落空不消耗
      正负对照）/ 对手购买不触发 / 满手排队（副本进入
      pending_hand_queue 且不丢失）

    Params: {0}=2 {1}=2（BG35_MagicItem_931 num(0)/num(1)——额度取
            num(1)，num(0) 为同值实时计数占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._typewriter_left = _num(game, source.card_id, 1)

        def on_bought(g, minion=None, _h=h, _src=source, **kw):
            if minion is None or minion.controller is not _h:
                return
            if getattr(_src, "_typewriter_left", 0) <= 0:
                return
            d = g.db.get(minion.card_id)
            if d is None:
                return
            golden = bool(getattr(minion, "is_golden", False))
            if g.grant_card_copy_to_hand(_h, d, golden=golden):
                _src._typewriter_left -= 1

        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        return None


# ══════════════════ BG36_MagicItem_201 Lionfish Portrait ══════════════════


class LionfishPortraitScript:
    """
    Natural language: [x]Get a Lurking Lionfish.
    Whenever a friendly Beast
    attacks, give it +{0}/+{1}.

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(本人, 本饰品 id)`——
         数据链 `evolution_card_id`（dbf 132794）→ `db.by_dbf` →
         `BG36_201` Lurking Lionfish（T2、`is_pool_minion=True` →
         `minion_pool.acquire` 占池、池空落空; 36.2.2 数据核实）
      2. on_bind 注册持久 `before_attack` 监听（owner=饰品;
         `CombatScheduler._execute_attack` 战斗攻击与
         `Game.recruit_phase_attack` 招募期攻击
         （`recruit_phase_attack`）在**伤害结算前**统一广播:
         `attacker=, defender=`）:
         - 条件: `attacker.controller is 本人` ∧ `not attacker.dead` ∧
           `race ∈ (BEAST, ALL)`（Amalgam 视为野兽——RULES §6.4）
         - 命中: `Buff(attacker, atk=num(0), health=num(1))`——在
           `atk_power = attacker.atk` 快照**之前**入队解析，故本次攻击
           即按增益后攻击力结算（"Whenever ... attacks" 先于伤害）
         - **不设 `in_combat` 闸门**: 文本无 "(N times per combat)"、
           wiki 分类无 Combat-related（对照 Divine Signet 的
           Combat-related 裁定; 招募期攻击（Fishbait）同样计入）
      3. 无次数上限; 每次攻击（含风怒连续攻击）各触发一次
      4. 只作用于本人随从（对手野兽攻击不触发）

    Test: test_batch_trinkets20.py — 真实 `run_combat` 内
      `before_attack` 探针读到野兽已 +num(0)/+num(1) 后再受伤（正对照:
      非野兽同场不变）/ 对手野兽攻击不获得 / 招募期攻击
      （`recruit_phase_attack`）同样触发 / 无饰品对照不变 / 绑定入手
      1 只 BG36_201 且池 -1

    Params: {0}=2 {1}=2（BG36_MagicItem_201 num(0)/num(1)，36.2.2）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def on_attack(g, attacker=None, _h=h, **kw):
            if attacker is None or getattr(attacker, "dead", False):
                return
            if attacker.controller is not _h:
                return
            if attacker.race not in _BEAST_RACES:
                return
            g.run_actions(Buff(attacker, atk=atk, health=health))

        game.events.register(Listener(event=BEFORE_ATTACK, owner=source,
                                      callback=on_attack))
        return None


# ══════════════════ BG36_MagicItem_206 Ominous Stone ══════════════════


class OminousStoneScript:
    """
    Natural language: [x]<b>Discover</b> a Tier 4 minion
    of your most common
    type with a <b>Dark Gift</b>.

    Formal spec:
      1. on_bind: 众数种族 `race = darkgifts.most_common_board_race(本人,
         rng)`（只计棋盘有种族随从、ALL 不计入、并列 rng 任选——
         batch_spells1 Planar Telescope 同源帮助函数）
      2. 候选 = `_pool_candidates(game, race=race, min_tier=4,
         max_tier=4)`（池剩余量 / active_races / ALL 匹配过滤，RULES
         §6.18; "Tier 4" 为文本字面量——`num(0)=2` 无 {0} 占位符引用）。
         无有种族随从（空板 / 全无类型）→ **不限族**（`BG33_814
         Friendly Bounty` "your most common type" 同文先例，
         batch_spells4 已验收）
      3. `_dark_gift_discover`: 抽 ≤3 候选各配互不相同合法 Dark Gift →
         `PendingChoice(kind="dark_gift")` → resolve 时
         `create_minion` + `apply_dark_gift` + `pending_hand_add`
      4. 候选为空 / 无合法 gift / 预留失败 → 本次落空（不产生选择、
         不报错）
      5. 只进本人手牌（owner 隔离）

    Test: test_batch_trinkets20.py — 2 野兽 + 1 鱼人棋盘: 选项随从的
      CardDef 全部 `tech_level == 4` 且 race ∈ (众数族, ALL)；选定后
      入手实体带 DARK_GIFT tag（正对照: 无饰品无选择）/ 空板 → 不限族
      仍产生 T4 选项（回退裁定）/ 对手手牌不变 / 对手棋盘类型不计入
      众数（owner 隔离: 对手 2 野兽 + 本人 1 鱼人 → 众数鱼人）/ 池
      记账: 未选项在 resolve 后回池（预留语义）

    Params: {0}=2（BG36_MagicItem_206 num(0)——文本无占位符引用，未用）
            ; tier=4（文本字面量 "Tier 4"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        race = most_common_board_race(h, game.rng)
        cands = _pool_candidates(game, race=race,
                                 min_tier=_OMINOUS_TIER,
                                 max_tier=_OMINOUS_TIER)
        _dark_gift_discover(game, h, cands)
        return None


# ══════════════════ BG36_MagicItem_208 Floating Candle Set ══════════════════


class FloatingCandleSetScript:
    """
    Natural language: <b>Spellcraft:</b> Trigger a friendly minion's
    <b>Deathrattle</b>.

    Formal spec:
      1. on_bind: `spellcraft.grant_spellcraft_spell(source, game)`——
         RULES §6.13 "获得法术塑造时立即获得第一张"（饰品版先例
         batch_trinkets18 Jailer Sticker / batch_trinkets2 Harvested
         Pearl）。**每回合**的再次生成由**引擎**负责
         （`spellcraft.generate_for_hero` 扫描 `hero.board +
         hero.trinkets + hero.quest_rewards`; `create_entity` 依
         `CardDef.spellcraft_id=133396` 打 SPELLCRAFT tag），脚本
         **不得**再写 `start_of_turn` 生成（否则同回合双发）
      2. 实效由法术脚本 `FloatingCandleSetSpellScript`
         （`BG36_MagicItem_208t`）完成
      3. 该法术是临时法术（未使用则回合结束丢弃），由引擎处理

    Test: test_batch_trinkets20.py — 绑定后手牌恰 +1 张
      `BG36_MagicItem_208t` 且带 SPELLCRAFT tag / 真实
      `_begin_recruit_for` 下一回合再生成 1 张（每回合恰 1 张，不双发）/
      对手手牌不受影响 / 无饰品对照 0 张

    Params: 无模板参数（法术 id 经 `CardDef.spellcraft_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)
        return None


class FloatingCandleSetSpellScript:
    """
    Natural language: Trigger a friendly minion's <b>Deathrattle</b>.

    Evidence: wiki.gg Battlegrounds/Floating_Candle_Set_(spell) 的
    "Wiki tags" 明示 **[Targeted]**（对照 Kelp Keeper
    "Trigger a friendly minion's Battlecry" 同族）→ 玩家选择目标，
    禁止随机近似。

    Formal spec:
      1. `needs_target = True`（引擎 `play_spell` 产生
         PendingChoice(kind="spell_target")）;
         `target_candidates(source, game)` = 本人棋盘存活且
         **真的会触发亡语**的随从（`_has_deathrattle`: 实体 DEATHRATTLE
         tag / 脚本 deathrattle 钩子 / 磁力栈叠的亡语随从——与引擎
         `_has_deathrattle_hook` 同口径）
      2. on_play: 目标必须仍是本人棋盘上的存活随从（挂起期离场 →
         落空，SOP §16 item 24）→ `game.run_script_hook(target,
         "deathrattle")`（与 `recruit_phase_attack` 的酒馆目标亡语、
         `_process_single_death` 同一分发出口; 亡语脚本自身按
         `game.in_combat` 选择数值口径——Plaguerunner 家族）
      3. 目标无亡语 / 无候选 → 落空（法术照常消耗——引擎路径）
      4. 不改动目标的生命/区域（"Trigger" 不是"Destroy"）

    Test: test_batch_trinkets20.py — 真实 `play_spell` 触发带亡语的
      池随从（BG34_690 Plaguerunner: 本人棋盘亡灵 +num(0) 攻击）/
      无亡语候选时不产生选择（对照: 同 setup 有候选时恰好 1 个选择）/
      挂起期目标离场 → 落空不抛错 / 对手随从不受影响

    Params: 无模板参数（效果量由被触发亡语的卡决定）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in _living(hero) if _has_deathrattle(game, m)]

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or not isinstance(target, Minion):
            return None
        if target.dead or target.controller is not hero \
                or target not in hero.board:
            return None
        # 统一亡语入口（RULES §6.20）: "Trigger a Deathrattle" 与真实亡语
        # 等价 → 应用 Titus 倍率 / dr_extra / dr_first 并计入
        # deathrattle_trigger（旧实现直调 run_script_hook → Titus 在场
        # 也只得 1 次; 2026-09-02 对抗审查证伪）
        game.trigger_deathrattle(target, hero=hero)
        return None


# ══════════════════ BG36_MagicItem_211 Lovely Locket ══════════════════


class LovelyLocketScript:
    """
    Natural language: [x]After you cast a spell on
    a friendly minion, this
    casts it on another
    friendly minion.

    Evidence: wiki.gg Battlegrounds/Lovely_Locket 的 "Wiki tags" 明示
    **[Random]**（再施放目标是随机另一友方随从，非玩家选择）;
    官方 bug 报告（us.forums.blizzard.com "Lovely Locket ignores spell
    restrictions bug"）确认**再施放应当尊重原法术的目标限制**（旧实现
    忽略限制是 bug）→ 本脚本从原法术脚本的 `target_candidates` 取合法
    目标集合。

    Formal spec:
      1. on_bind 注册持久 **`spell_resolved`** 监听（owner=饰品; 每次
         施放**效果结算后**广播，RULES §7.4.12）: `spell` 即本次施放，
         `target` 即其目标。"After you cast a spell on a friendly minion"
         是**后置**语义 → 再施放发生在原法术结算之后。
         **按施放次数计**——`card_played` 每次**打出**只广播一次，双施
         （`SPELL_DOUBLER` Balinda / Replica Cathedral / Sushi Roll）时
         会漏掉第二次再施放（2026-09-02 对抗审查证伪; 与 Bloodbound
         Earrings / Archaic Scroll 的计数域同源）
      2. 条件: `spell.controller is 本人` ∧ `target` 是**本人**的随从
         （"on a friendly minion"）——**只**校验 controller（不校验
         `dead`/仍在棋盘）: 原目标可能已被本次法术消灭（`BG28_604
         Butchering`），但"对友方随从施放"已成立
      3. 再施放目标 = 本人棋盘**其他**存活随从中随机一个（`game.rng`）
         ∩ 原法术脚本声明的 `target_candidates`（尊重限制）;
         无候选 → 落空
      4. 再施放走 `game.cast_spell_effect(本人, spell.card_id,
         target=pick)`——**效果施法**统一入口（不经手牌、不耗金币、
         不动法术池、不广播 card_played/tavern_spell_cast，也不计入
         `TAVERN_SPELLS_CAST_*`）。`cast_spell_effect` **会**广播
         `spell_resolving`/`spell_resolved`（效果施法同样是"施放了一个
         法术"）→ 用 game 级 `_lovely_locket_recast` 重入闸防止再施放
         自我递归（含多份饰品副本互相触发的死循环）
      5. 只作用于本人棋盘（对手施法/对手随从不受影响）

    Test: test_batch_trinkets20.py — 真实 `play_spell`（BG28_897
      Tavern Dish Banana 定向本人随从）后**另一个**友方随从也获得同额
      增益（正对照: 对手随从不变）/ 只有一个友方随从时不产生第二次
      施放（落空不报错）/ 限制尊重: 用只允许亡灵的 BG28_604 Butchering
      验证非法目标（野兽）不被选、合法第二亡灵被消灭 / 再施放不广播
      card_played（无递归——计数探针）/ **双施按 cast 计**（SPELL_DOUBLER
      在场时 2 次施放 → 2 次再施放; 旧 card_played 实现只 1 次）/ 无饰品
      对照不变 / 对手施法不触发

    Params: 无模板参数（效果量由被再施放的法术 CardDef 决定）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_resolved(g, spell=None, target=None, _h=h, **kw):
            if getattr(g, "_lovely_locket_recast", False):
                return          # 重入闸: 本次再施放不得再触发本效果
            if not isinstance(spell, Spell) or spell.controller is not _h:
                return
            if not isinstance(target, Minion) or target.controller is not _h:
                return
            others = [m for m in _living(_h) if m is not target]
            if not others:
                return
            # 尊重原法术的目标限制（官方 bugfix 口径）
            from hsrl2.scripts import REGISTRY
            cls = REGISTRY.get(spell.card_id)
            cand_fn = getattr(cls, "target_candidates", None) \
                if cls is not None else None
            if cand_fn is not None:
                allowed = {id(x) for x in cand_fn(spell, g)}
                others = [m for m in others if id(m) in allowed]
            if not others:
                return
            pick = g.rng.choice(others, label="lovely_locket")
            g._lovely_locket_recast = True
            try:
                # source= 原始法术实体 → 重施放继承 spellcraft_source_uuid，
                # 使"permanent Spellcraft"（920/933）在效果施法路径同样生效
                # （ENGINE_BACKLOG #26，2026-09-14 第二十四轮）
                g.cast_spell_effect(_h, spell.card_id, target=pick,
                                    source=spell)
            finally:
                g._lovely_locket_recast = False

        game.events.register(Listener(event="spell_resolved", owner=source,
                                      callback=on_resolved))
        return None


# ══════════════════ BG36_MagicItem_217 Funeral Wreath ══════════════════


class FuneralWreathScript:
    """
    Natural language: [x]After a friendly minion is
    <b>Reborn</b>, get a plain
    copy of it. <i>({1} times
    per combat.)</i>

    Formal spec:
      1. on_bind 注册持久 `reborn` 监听（owner=饰品; `Game._process_single_death` 复生分支在
         复生体原位回归后广播 `minion=`）; 额度
         `source._wreath_left = num(1)`——文本 "({1} times per combat.)"
         的 {1}=num(1)=3（{0} 为同值实时计数占位符）
      2. 条件: `minion.controller is 本人` ∧ `game.in_combat` ∧ 额度 > 0
         ——"(N times per combat)" 的额度只在战斗内存在（batch_trinkets8
         `DivineSignetScript`/`MechagonAdapterScript` 已验收口径）
      3. 命中: `grant_card_copy_to_hand(本人, **基础** CardDef)`——
         文本明示 "plain copy" → 金卡定义经 `triple_base_id` 回落非金
         本体（`_base_def`）; 池内随从占池、池空落空; 满手排队 RULES
         §3.3; **成功才扣减额度**（落空不消耗）
      4. `start_of_combat`（饰品 SoC 钩子，先于攻击循环）重置额度为
         num(1)——每场战斗独立额度
      5. 只作用于本人（对手复生不触发）; 只进本人手牌

    Test: test_batch_trinkets20.py — 战斗内真实复生路径
      （`_process_single_death` 于 run_combat 内）: 前 num(1) 次各入手
      1 份白板副本且池 -1、第 num(1)+1 次不再发放（正对照: 有额度时
      发放）/ 真实 `run_combat` 结束后额度重置（下一场首个复生再次
      发放）/ 招募期复生（非战斗）不发放 / 对手复生不发放 /
      金色复生体交付**非金**副本（plain 口径）

    Params: {0}=3 {1}=3（BG36_MagicItem_217 num(0)/num(1)——额度取
            num(1)，num(0) 为同值实时计数占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._wreath_left = _num(game, source.card_id, 1)

        def on_reborn(g, minion=None, _h=h, _src=source, **kw):
            if minion is None or minion.controller is not _h:
                return
            if not g.in_combat:
                return
            if getattr(_src, "_wreath_left", 0) <= 0:
                return
            d = _base_def(g, minion.card_id)
            if d is None:
                return
            if g.grant_card_copy_to_hand(_h, d):
                _src._wreath_left -= 1

        game.events.register(Listener(event=REBORN_EVENT, owner=source,
                                      callback=on_reborn))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        if source.controller is None:
            return None
        source._wreath_left = _num(game, source.card_id, 1)
        return None


# ══════════════════ BG36_MagicItem_301 Lockbox Portrait ══════════════════


class LockboxPortraitScript:
    """
    Natural language: [x]Get a Lockbox. If you already
    have one, it opens {0} |4(turn, turns)
    sooner instead. At the start
    of each turn, repeat this.

    Formal spec:
      1. on_bind 与 `start_of_turn` 各执行一次 `_apply`
         （"At the start of each turn, repeat this"）:
         - 本人手牌**已有** Lockbox（`card.card_id ==
           constants.LOCKBOX_CARD_ID`）→
           `game.open_lockbox_early(本人, num(0))`——倒计时提前
           num(0)=2 回合，归零即 `_open_lockbox`（随机有种族金随从
           入手、池扣 min(3, 剩余)——引擎内建）
         - 否则 `game.grant_trinket_related_card(本人, 本饰品 id)`——
           数据链 `evolution_card_id`（dbf 132766）→ `db.by_dbf` →
           `BG36_520t` Lockbox（`card_type=5`、非池; `create_spell`
           保证 `LOCKBOX_TURNS_LEFT` 初始 = Lockbox CardDef num(0)=5）
         （同一实现已在 `minions.py.LockedUpMutineerScript` 亡语版验收，
           本卡为饰品版同构）
      2. 两分支互斥（已有则提前、没有则获取）; 只作用于本人手牌。
         "已有"判定 = **手牌 + 满手等待队列**（`_lockbox_present`）——
         满手时 Lockbox 在 `pending_hand_queue`，只扫手牌会判为"还没有"
         → 每个 SoT 再排一份、事后一次性入手多张（2026-09-02 对抗审查
         实测证伪）
      3. 倒计时未归零 → 继续留在手牌; 归零 → Lockbox 开启并离手
         （引擎保证）

    Test: test_batch_trinkets20.py — 绑定后本人手牌 1 张
      `LOCKBOX_CARD_ID` 且 `LOCKBOX_TURNS_LEFT == Lockbox num(0)` /
      再次 `start_of_turn` → 倒计时 -num(0) 且仍为 1 张（不重复获取）/
      **满手绑定时不重复排队**（旧实现 queue 1→2→3→4）/ 归零后真实
      `_open_lockbox` 路径（倒计时归零）→ 金卡随从入手且基础池配平
      （正对照: 不调用时池不变）/ 对手手牌不变 / 无饰品对照手牌无
      Lockbox

    Params: {0}=2（BG36_MagicItem_301 num(0)——"opens 2 turns sooner"）
    """

    @staticmethod
    def _lockbox_present(game, hero) -> bool:
        """本人是否已持有 Lockbox——**手牌 + 满手等待队列**双查。

        满手时 `pending_hand_add` 把 Lockbox 排进
        `game.pending_hand_queue`（RULES §3.3），只扫 `hero.hand` 会
        判为"还没有"→ 每个 SoT 再排一份（实测 queue 1→2→3→4，事后
        一次性入牌、各开一张金卡; 2026-09-02 对抗审查证伪）。
        """
        for card in hero.hand:
            if card.card_id == LOCKBOX_CARD_ID:
                return True
        for h, entity in getattr(game, "pending_hand_queue", []):
            if h is hero and getattr(entity, "card_id", None) \
                    == LOCKBOX_CARD_ID:
                return True
        return False

    @staticmethod
    def _apply(game, source) -> None:
        h = source.controller
        if h is None:
            return
        if LockboxPortraitScript._lockbox_present(game, h):
            game.open_lockbox_early(h, _num(game, source.card_id, 0))
            return
        game.grant_trinket_related_card(h, source.card_id)

    @staticmethod
    def on_bind(source, game, ctx):
        if _hero(ctx) is None:
            return None
        LockboxPortraitScript._apply(game, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        LockboxPortraitScript._apply(game, source)
        return None


# ══════════════════ BG36_MagicItem_302 Gold Mallet ══════════════════


class GoldMalletScript:
    """
    Natural language: [x]At the end of your turn, give
    your minions +{0}/+{1}.
    <i>(Improved by Golden minions
    you've played this game!)</i>

    Formal spec:
      1. `end_of_turn`: 本人棋盘全部存活随从各获
         `Buff(atk=num(0)+GMP, health=num(1)+GMP)`，
         `GMP = hero.get(GameTag.GOLDEN_MINIONS_PLAYED, 0)`
         （tag 1063——`play_minion` 对 `is_golden` 实体自动递增，
         SOP §10 引擎原语）
      2. "Improved by ... you've played this game" 按仓内既有
         **加法**裁定: 基值 + 每实例 +1——已验收先例:
         `batch_unfreeze.HooktuskScript`（"num(0)+GMP / num(1)+GMP"）与
         `batch_battlecry.LovesickBalladistScript`（"Improved by each
         Gold you spent this turn" = num(1)+GOLD_SPENT_THIS_TURN，
         依据 34.6.0 补丁历史: 基值独立于 improvement 叠加）
      3. 跨回合累积（GMP 是"本局"计数，不随回合清零）; 绑定前的金色
         打出计入（GMP 是历史计数——文本 "you've played this game"）
      4. 空场 → 落空（不报错）; 只作用于本人棋盘（对手随从不变）

    Test: test_batch_trinkets20.py — 无金色打出时 EoT 恰好 +num(0)/
      +num(1)（钉死 CardDef 值）/ 真实打出 1 只金色随从后 EoT
      +（num(0)+1）/+(num(1)+1)（正对照: 同 setup 无金色为基值）/
      跨回合累积（连续两个 `end_recruit_phase`）/ 对手打出金色不计入
      （owner 隔离）/ 对手随从不获得 / 空场落空不报错

    Params: {0}=2 {1}=1（BG36_MagicItem_302 num(0)/num(1)，36.2.2）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        targets = _living(h)
        if not targets:
            return None
        gmp = h.get(GameTag.GOLDEN_MINIONS_PLAYED, 0)
        atk = _num(game, source.card_id, 0) + gmp
        health = _num(game, source.card_id, 1) + gmp
        return [Buff(m, atk=atk, health=health) for m in targets]


# ══════════════════ BG36_MagicItem_303 Glass of Perspective ══════════════════


class GlassOfPerspectiveScript:
    """
    Natural language: Get a random <b>Choose One</b> card. At the start
    of each turn, get another.

    Formal spec:
      1. 候选 = Choose One **池卡全集**（`batch_rally2.CHOOSE_ONE_MINION_IDS`
         ∩ `_pool_candidates` 池可用）∪
         (`CHOOSE_ONE_SPELL_IDS` ∩ `spell_pool.available > 0`)——
         "card" 通名涵盖随从与法术（batch_rally2 Bramble Tunneler
         "Get a random Choose One card" 同文先例，其常量集带 XML 漂移
         守护测试）; 金色版不参与（"a random Choose One card" 基础卡
         语义）
      2. on_bind 与 `start_of_turn` 各随机 Get 1 张（`game.rng`）:
         随从 → `minion_pool.acquire` + `create_minion`; 池法术 →
         `spell_pool.acquire` + `create_spell`; 均 `pending_hand_add`
         （满手排队 RULES §3.3）
      3. 无候选（两池 Choose One 全耗尽）→ 该次落空（不报错）
      4. 只进本人手牌（owner 隔离）
      5. 引擎缺口（沿用 batch_rally2 报告）: 生成器未导出 CHOOSE_ONE
         标签 → 常量集硬编码 + 漂移守护测试对照 CardDefs.xml

    Test: test_batch_trinkets20.py — 绑定后本人手牌恰 +1 张 Choose One
      卡且该卡在常量集内、占池（随从池 -1 或法术池 -1）/ 真实
      `end_recruit_phase` 后再 +1（跨回合语义; 同回合重复调用
      start_of_turn 不叠加由引擎每回合一次保证）/ 对手手牌不变 /
      无饰品对照 0 张 / 两池耗尽 → 落空不报错

    Params: 无数值参数（CardDef num 全 None）
    """

    @staticmethod
    def _grant(game, h) -> bool:
        from hsrl2.scripts.batches.batch_rally2 import (
            CHOOSE_ONE_MINION_IDS, CHOOSE_ONE_SPELL_IDS)
        avail = set(_pool_candidates(game))
        minion_cands = [cid for cid in sorted(CHOOSE_ONE_MINION_IDS)
                        if cid in avail]
        spell_cands = [cid for cid in sorted(CHOOSE_ONE_SPELL_IDS)
                       if game.spell_pool.available(cid) > 0]
        cands = minion_cands + spell_cands
        if not cands:
            return False
        pick = game.rng.choice(cands, label="glass_of_perspective")
        d = game.db.get(pick)
        if d is None:
            return False
        if d.is_pool_spell:
            if not game.spell_pool.acquire(pick):
                return False
            game.pending_hand_add(h, game.create_spell(pick, controller=h))
        else:
            if not game.minion_pool.acquire(pick):
                return False
            game.pending_hand_add(h, game.create_minion(pick, controller=h))
        return True

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        GlassOfPerspectiveScript._grant(game, h)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        GlassOfPerspectiveScript._grant(game, h)
        return None


# ══════════════════ BG36_MagicItem_309 Wax Lance ══════════════════


class WaxLanceScript:
    """
    Natural language: <b>Discover</b> a Tier 7 minion with a
    <b>Dark Gift</b>.

    Formal spec:
      1. on_bind: 候选 = `_pool_candidates(game, min_tier=7,
         max_tier=7)`——与 `Discover(min_tier=7, max_tier=7)` 同一候选
         源（显式 min_tier=7 才越出 `game.max_tavern_tier` 封顶，
         RULES §6.18 / `Discover.do` 的显式候选封顶; 标准局 T6 封顶不适用于本卡的
         显式 Tier 7）
      2. `_dark_gift_discover`: 抽 ≤3 个 T7 候选各配互不相同合法
         Dark Gift（**不**套用 `DG.eligible_minions` 的回合 tier 曲线
         ——本卡显式指定 Tier 7，只按档位过滤）→
         `PendingChoice(kind="dark_gift")` → resolve 时
         `create_minion` + `apply_dark_gift` + `pending_hand_add`
      3. 候选为空 / 无候选有合法 gift / 预留失败 → 本次落空
      4. 只进本人手牌（owner 隔离）

    Test: test_batch_trinkets20.py — 选项随从 CardDef 全部
      `tech_level == 7` 且各带不同 gift（正对照: 无饰品无选择）/
      选定后入手 T7 实体带 DARK_GIFT tag 且池 -1 / 未选项 resolve 后
      回池（预留语义 + 池配平）/ 对手手牌不变 / 池中 T7 被抽空 →
      落空不报错

    Params: 无模板参数（CardDef num 全 None）; tier=7（文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        cands = _pool_candidates(game, min_tier=_WAX_LANCE_TIER,
                                 max_tier=_WAX_LANCE_TIER)
        _dark_gift_discover(game, h, cands)
        return None


# ══════════════════ BG36_MagicItem_361 Myrmidon Sticker ══════════════════


class MyrmidonStickerScript:
    """
    Natural language: <b>Start of Combat:</b> Double your left and
    right-most Naga's stats.

    Formal spec:
      1. `start_of_combat`（饰品 SoC 钩子，先于攻击循环）: 目标 = 本人
         棋盘**最左**与**最右**的存活纳迦（race ∈ (NAGA, ALL)，
         Amalgam 视为纳迦——RULES §6.4）; 只有一个纳迦时最左=最右 →
         去重为单次
      2. 各获 `Buff(atk=m.atk, health=m.health)`——"stats" 翻倍取
         **当前值**（战斗内属性; 引擎 Dark Gift 家族
         `RESISTANCE 生命翻倍 = Buff(0, m.health)` /
         `TRANSCENDENCE 属性三倍 = Buff(2*m.atk, 2*m.health)`
         `RESISTANCE`/`TRANSCENDENCE` 同口径）; 本场战斗限定（`run_combat` 战后
         快照复原，RULES §3.5）
      3. 有无纳迦 → 无目标落空（不报错）; 只作用于本人棋盘

    Test: test_batch_trinkets20.py — 真实 `run_combat` 内 SoC 探针读到
      最左/最右纳迦属性各翻倍、中间纳迦不变（正对照: 同场有中间纳迦
      且其属性不变）/ 单纳迦棋盘只翻倍一次（去重，不 ×4）/ 无纳迦
      不报错且其余随从不变 / 对手纳迦不变 / 无饰品对照不变

    Params: 无模板参数（CardDef num 全 None）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        nagas = [m for m in _living(h) if m.race in _NAGA_RACES]
        if not nagas:
            return None
        targets = []
        for m in (nagas[0], nagas[-1]):
            if not any(m is seen for seen in targets):
                targets.append(m)
        return [Buff(m, atk=m.atk, health=m.health) for m in targets]


# ═════════════════════════ 注册 ═════════════════════════


def register() -> list[str]:
    """注册饰品第二十批 11 张 + Spellcraft 法术 1 张。

    （DEFERRED 5 张台账见模块 docstring: 930 自定义刷新 / 204 destroy
    事件 / 214 攻击外 Rally 协议 / 216 卡家族光环 / 308 hero 级
    CHOOSE_BOTH 读取点。）
    Status: BG36_MagicItem_204 已由 batch_trinkets26 注册
      （minion_destroyed/destroy_minion 原语已于 2026-09-02 落地; 该条从
      DEFERRED 台账迁出，余 930/214/216/308 四张）。
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_MagicItem_931", TranscribingTypewriterScript),
        ("BG36_MagicItem_201", LionfishPortraitScript),
        ("BG36_MagicItem_206", OminousStoneScript),
        ("BG36_MagicItem_208", FloatingCandleSetScript),
        ("BG36_MagicItem_208t", FloatingCandleSetSpellScript),
        ("BG36_MagicItem_211", LovelyLocketScript),
        ("BG36_MagicItem_217", FuneralWreathScript),
        ("BG36_MagicItem_301", LockboxPortraitScript),
        ("BG36_MagicItem_302", GoldMalletScript),
        ("BG36_MagicItem_303", GlassOfPerspectiveScript),
        ("BG36_MagicItem_309", WaxLanceScript),
        ("BG36_MagicItem_361", MyrmidonStickerScript),
    ]
    for cid, cls in pairs:
        reg(cid, cls)
    return [cid for cid, _cls in pairs]
