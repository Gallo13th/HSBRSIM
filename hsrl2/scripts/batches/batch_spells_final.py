"""批次 spells_final — 清尾池法术 21 张（作业单 2026-08-22）。

覆盖 20 张 OK + 1 张 DEFERRED:
  OK: BG33_817 Sanctify / BG33_899 Mounting Avalanche /
      BG34_272 Menagerie Tableware / BG34_330 Search Through Time /
      BG34_444 Easterly Winds / BG34_689 Blood Gem Barrage /
      BG34_888 Tomb Turning / BG34_889 Brood of Nozdormu /
      BG34_990 Wave of Gold / BG35_149 Deepwater Clan /
      BG35_912 Eonar's Favor / BG35_922 Queen's Command /
      BG35_951 Might of Stormwind / BG36_624 Repair Job /
      BG36_880 Methodical Madness / BG36_883 Winner's Bread /
      BG36_884 Weapons Forge / EBG_Spell_017 Eyes of the Earth Mother /
      EBG_Spell_032 Channel the Devourer / EBG_Spell_038 Lost Staff of
      Hamuul
  DEFERRED: EBG_Spell_037 Unmasked Identity（英雄技能体系未迁移）

共性裁定（本批 docstring 内各卡另有细化）:
  - **give-buff 法术出口**: 对随从的增益一律经
    actions.racefx.tavern_spell_buff 构造（"Your Tavern spells give an
    extra +X" 修饰叠加，racefx 模块契约; 酒馆面buff同样并入——
    batch_spells3 Staff of Enrichment 快照先例）。
  - **数据核实**: 21 张均无金色卡定义（bg_cards.json 无 *_G 池法术
    条目，本批逐一验证），仅注册基础 id。
  - **"Sell a friendly minion" 类**: 走 game.sell_minion（触发 on_sell
    钩子 + 金币 + 回池——官方"sell"语义，非 destroy）; 属性快照在
    **卖出前**取（atk / max_health，SOP §3）。
  - **After the Tavern is Refreshed this game 类**: on_play 注册持久
    Listener(TAVERN_REFRESH, owner=hero, condition=hero is 施放者)，
    En-Djinn Blazer（batch_battlecry）先例。
  - **Bonus Keywords**（Methodical Madness，S14）: 官方 36.2 dev 报道
    "gain both their statistics and bonus keywords... can transfer
    Divine Shield, Taunt or other properties"——吞噬受害者身上的战斗
    关键词（Taunt/DS/Windfury/Poisonous/Venomous/Reborn/Stealth/
    Cleave，game._PERSIST_KEYWORD_TAGS 同集）移转给恶魔。
  - **v1 缺陷对照**（冻结只读，仅作反例）: v1 Mounting Avalanche /
    Channel the Devourer 用 Destroy 不触发 on_sell、快照用 health 非
    max_health; v1 Menagerie repeat=max(1,len(types)) 丢基础次; v1
    Search Through Time 未实现锁定——本批全部按 v2 语义重写。

引擎缺口（报告主线）:
  1. refresh_tavern 无 race_filter 参数——Lost Staff of Hamuul
     "Refresh the Tavern with minions of its type" 在脚本层手动重建
     （回池/冻结保留/tier 抽取/tavern_buffs 应用/Fodder 协议/事件
     广播全镜像引擎语义，见该卡 docstring）; 主线参数化后可迁移。
  2. EBG_Spell_037 Unmasked Identity DEFERRED——Discover a new Hero
     Power 依赖英雄技能系统（hero_power 脚本/池不存在）。
"""

from __future__ import annotations

import hsrl2.constants as C
from hsrl2.actions import Buff, Discover, GainKeyword, ScheduleNextTurn
from hsrl2.actions.consume import ConsumeMinion
from hsrl2.actions.discover import _pool_candidates
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, \
    TavernBuff
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.events import CARD_PLAYED, COMBAT_END, START_OF_COMBAT, \
    TAVERN_REFRESH, TURN_START, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.queue import Action
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

# 种族匹配组（ALL 视为所有种族, RULES §6.18 Amalgam 规则）
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_MURLOC_RACES = (Race.MURLOC, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)
_DEMON_RACES = (Race.DEMON, Race.ALL)

# Pointy Arrow 卡 id（BG32_170 Metallic Hunter 亡语同源 token，
# batch_deathrattle 数据核实; 非池法术不占池）
_SPELL_POINTY_ARROW = "EBG_Spell_014"

# S14 "Bonus Keywords" 移转集 = 战斗关键词（game._PERSIST_KEYWORD_TAGS
# 同集; 官方报道 "transfer Divine Shield, Taunt or other properties"）
_BONUS_KEYWORD_TAGS = (
    GameTag.TAUNT,
    GameTag.DIVINE_SHIELD,
    GameTag.WINDFURY,
    GameTag.POISONOUS,
    GameTag.VENOMOUS,
    GameTag.REBORN,
    GameTag.STEALTH,
    GameTag.CLEAVE,
)


def _require_nums(d, card_id: str, *idx: int):
    """模板参数缺失 → fail-loud（SOP §3: 禁止默认值近似）。"""
    vals = [d.num(i) for i in idx]
    if any(v is None for v in vals):
        raise GameStateError(
            f"{card_id}: missing template params "
            f"{[f'num({i})' for i, v in zip(idx, vals) if v is None]}")
    return vals


# ══════════════════ 批内自定义 Action（主线评审候选上移） ══════════════════


class DiscoverOwnTierLocked(Action):
    """Search Through Time: 发现一张本级随从并锁定 1 回合。

    - 候选 = _pool_candidates(min_tier=max_tier=hero.tavern_tier)——
      池感知（RULES §6.18）; 无候选 → 落空
    - resolve(pick_id): acquire 占池 → create_minion → 置
      LOCKED_IN_HAND tag（play_minion/play_spell 路径拒绝, SOP §10）→
      pending_hand_add（满手排队 + 三连检查）→ 注册 TURN_START once
      监听器（owner=实体, condition=控制者匹配——只在持有者下一招募
      阶段开始解锁，他人 turn_start 不消耗 once）清除 LOCKED
    - "for 1 turn" 边界: 施放回合 N 招募期内发现 → 回合 N+1 开始解锁;
      满手排队期间 turn_start 先于入队处理（game._begin_recruit_for
      顺序）——tag 清除与区域无关，解锁后再入手不被误锁
    """

    def __init__(self, hero):
        self.hero = hero

    def do(self, game) -> None:
        tier = self.hero.tavern_tier
        cands = _pool_candidates(game, min_tier=tier, max_tier=tier)
        if not cands:
            return
        k = min(3, len(cands))
        options = game.rng.sample(cands, k, label="search_time_options")
        hero = self.hero

        def resolve(pick_id: str) -> None:
            if not game.minion_pool.acquire(pick_id):
                raise GameStateError(
                    f"Search Through Time: pick {pick_id} no longer "
                    f"available in pool")
            m = game.create_minion(pick_id, controller=hero)
            m.set(GameTag.LOCKED_IN_HAND, True)
            game.pending_hand_add(hero, m)

            def _unlock(g, hero=None, **kw):
                m.clear(GameTag.LOCKED_IN_HAND)

            game.events.register(Listener(
                event=TURN_START,
                owner=m,
                once=True,
                condition=lambda hero=None, **kw: hero is m.controller,
                callback=_unlock,
            ))

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_minion", resolve_callback=resolve))


class DiscoverUndeadDiesIfPlayed(Action):
    """Tomb Turning: 发现一张 Undead，本回合打出即死。

    - 候选 = _pool_candidates(race=UNDEAD)——无 tier 限制（"Discover
      an Undead" 全池, Contracted Corpse 同构）; 无候选 → 落空
    - resolve: acquire → create_minion → pending_hand_add → 实体动态
      属性 _tomb_dies_turn = game.turn + CARD_PLAYED once 监听器
      （owner=实体, condition=card is 该实体）: 打出事件时若
      g.turn == 标记回合（"this turn" 自过期——未打出则标记自然失效,
      无需独立清除监听器）→ health=0（Destroy 语义, Leeroy 先例）+
      check_deaths（死亡链: 离场/亡语/回池/复生由引擎波次处理）
    - card_played 在战吼结算后广播（game._run_play_effects）→
      战吼正常触发后再死（官方打出→死亡的顺序）
    """

    def __init__(self, hero):
        self.hero = hero

    def do(self, game) -> None:
        cands = _pool_candidates(game, race=Race.UNDEAD)
        if not cands:
            return
        k = min(3, len(cands))
        options = game.rng.sample(cands, k, label="tomb_turning_options")
        hero = self.hero
        marked_turn = game.turn

        def resolve(pick_id: str) -> None:
            if not game.minion_pool.acquire(pick_id):
                raise GameStateError(
                    f"Tomb Turning: pick {pick_id} no longer available "
                    f"in pool")
            m = game.create_minion(pick_id, controller=hero)
            game.pending_hand_add(hero, m)
            m._tomb_dies_turn = marked_turn

            def _on_played(g, card=None, **kw):
                if card is not m:
                    return
                if g.turn != marked_turn:
                    return          # "this turn" 已过期
                m.health = 0       # Destroy 语义（无视圣盾）
                g.check_deaths()

            game.events.register(Listener(
                event=CARD_PLAYED,
                owner=m,
                once=True,
                condition=lambda card=None, **kw: card is m,
                callback=_on_played,
            ))

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_minion", resolve_callback=resolve))


class ConsumeRandomTavernWithKeywords(Action):
    """Methodical Madness 单次吞噬: ConsumeRandomTavernMinion 语义 +
    Bonus Keywords 移转（S14）。

    - 候选 = demon 控制者酒馆中的 Minion; 随机 game.rng.choice;
      空候选 → 落空（真实池空行为）
    - 受害者战斗关键词快照（_BONUS_KEYWORD_TAGS）→ ConsumeMinion.do
      （属性/回池/事件唯一权威）→ GainKeyword 移转给恶魔
    - 直接执行（Mind Muck batch_consume 直调先例）
    """

    def __init__(self, demon: Minion):
        self.demon = demon

    def do(self, game) -> None:
        hero = self.demon.controller
        if hero is None:
            raise GameStateError(
                "ConsumeRandomTavernWithKeywords: demon has no controller")
        candidates = [m for m in hero.tavern if isinstance(m, Minion)]
        if not candidates:
            return
        victim = game.rng.choice(candidates,
                                 label="methodical_madness_victim")
        kw_tags = [t for t in _BONUS_KEYWORD_TAGS if victim.has(t)]
        ConsumeMinion(self.demon, victim).do(game)
        for tag in kw_tags:
            GainKeyword(self.demon, tag).do(game)


class WinnersBreadNextTurnBuff(Action):
    """Winner's Bread 延迟第二段: 下一招募阶段开始时若目标仍在场，
    经 tavern_spell_buff 追加 +num(2)/+num(3)。

    目标执行时求值（"give it" 指该实体; 已卖出/死亡/离场 → 落空，
    官方延迟 buff 对不存在目标落空语义）。TAVERN_SPELL_EXTRA_* 在
    执行时读取（边角: 与施放时快照的取舍官方未公布——wiki 卡页无
    Notes（BG36_883 Winner's Bread，2026-08-23 全文核对），执行时
    读取与即时面同构，两读法仅差施放与下回合间的 extra 增量）。
    """

    def __init__(self, target: Minion, spell_id: str):
        self.target = target
        self.spell_id = spell_id

    def do(self, game) -> None:
        if self.target.zone != Zone.PLAY or self.target.dead:
            return
        d = game.db.get(self.spell_id)
        atk, health = _require_nums(d, self.spell_id, 2, 3)
        game.run_actions(tavern_spell_buff(self.target, atk, health))


def _refresh_tavern_of_type(game, hero: Hero, race: Race | None) -> None:
    """Lost Staff of Hamuul 手动重建酒馆（引擎 refresh_tavern 无
    race_filter——缺口 #1，本函数全镜像引擎语义）:

    1. 冻结保留（P5: 整馆保留、仅保留一轮、FROZEN 清除）
    2. 未保留内容回池（P1: Minion 1 份 / Spell 1 份）
    3. 随从位 = TAVERN_OFFERS[tier] - 保留数: _pool_candidates
       (race, min_tier=1, max_tier=tier)（Amalgam 匹配任意种族查询;
       active_races 过滤同口径）按剩余量**加权**抽取（RULES §2.4，
       draw_tavern 同算法）; 新入馆随从应用 hero.tavern_buffs
       （refresh 自动应用契约, game.refresh_tavern 同段镜像）
    4. 法术位 = TAVERN_SPELLS_PER_REFRESH - 保留法术数（常规刷新
        语义; 依据 2026-08-23 查证: wiki.gg/wiki/Battlegrounds/Lost_
        Staff_of_Hamuul 无 Notes，33.6.0 官方 bugfix（Guiding Candle
        空馆场景）确认按族过滤刷新可产出稀疏馆——法术位保留为
        常规刷新结构推论，边角上报主线）
    5. Fodder 协议 v2（game._fodder_refresh_pending, SOP §10）
    6. fire tavern_refresh（"Refresh the Tavern" 即刷新——Easterly
       Winds / Blood Gem Barrage / Fodder 类触发器可观测）
    7. 免费刷新（法术自身效果，不扣金币）
    """
    keep: list = list(hero.tavern) if hero.frozen_tavern else []
    for entity in hero.tavern:
        if entity in keep:
            continue
        if isinstance(entity, Minion):
            game.minion_pool.release(entity.card_id, 1)
        elif isinstance(entity, Spell):
            game.spell_pool.release(entity.card_id)
    count = max(0, C.TAVERN_OFFERS.get(hero.tavern_tier, 6) - len(keep))
    kept_spells = sum(1 for e in keep if not isinstance(e, Minion))
    hero.tavern = list(keep)
    hero.clear(GameTag.FROZEN)
    for _ in range(count):
        cands = _pool_candidates(game, race=race, min_tier=1,
                                 max_tier=hero.tavern_tier)
        if not cands:
            break
        weighted: list = []
        for cid in cands:
            weighted.extend([cid] * game.minion_pool.available(cid))
        pick = game.rng.choice(weighted, label="lost_staff_draw")
        if not game.minion_pool.acquire(pick):
            raise GameStateError(
                f"Lost Staff of Hamuul: pool acquire failed for {pick}")
        m = game.create_minion(pick, controller=hero)
        m.zone = Zone.TAVERN
        d = game.db.get(pick)
        for tb in getattr(hero, "tavern_buffs", []):
            if tb.matches(d):
                m.add_buff(BuffEnchant(atk=tb.atk, health=tb.health,
                                       source_id=tb.source_id))
        hero.tavern.append(m)
    spell_count = max(0, C.TAVERN_SPELLS_PER_REFRESH - kept_spells)
    for card_id in game.spell_pool.draw_tavern(hero.tavern_tier,
                                               spell_count):
        s = game.create_spell(card_id, controller=hero)
        s.zone = Zone.TAVERN
        hero.tavern.append(s)
    pending_entry = game._fodder_refresh_pending.get(hero)
    if pending_entry:
        refreshes_left, per_refresh = pending_entry
        for _ in range(per_refresh):
            fodder = game.create_minion(C.FODDER_CARD_ID, controller=hero)
            fodder.zone = Zone.TAVERN
            hero.tavern.append(fodder)
        if refreshes_left <= 1:
            del game._fodder_refresh_pending[hero]
        else:
            game._fodder_refresh_pending[hero] = \
                (refreshes_left - 1, per_refresh)
    game.events.fire(game, TAVERN_REFRESH, hero=hero)


# ══════════════════ BG33_817 Sanctify ══════════════════


class SanctifyScript:
    """
    Natural language: [x]Give your minions
    with <b>Divine Shield</b>
    +{0} Attack.
    （'@' 后金色段 "+{0}/+{1}" 为 CardDefs 遗留——BG 池法术无金色卡
    定义，data 已核实。）

    Formal spec:
      1. on_play: 全部存活友方随从中带 DIVINE_SHIELD 者，各经
         tavern_spell_buff 获得 +num(0) 攻击（TAVERN_SPELL_EXTRA_ATK
         联动; 生命 0——基础版文本仅引用 {0}，无生命加成）
      2. 无圣盾随从 → 落空（法术照常消耗）

    Test: test_batch_spells_final.py — 圣盾者 +num(0) 攻/生命不变、
    非圣盾者不动; 无圣盾落空

    Params: {0}=6（基础版无 {1}）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk, = _require_nums(d, source.card_id, 0)
        ds_minions = [m for m in hero.living_minions()
                      if m.has(GameTag.DIVINE_SHIELD)]
        if not ds_minions:
            return None
        return [tavern_spell_buff(m, atk, 0) for m in ds_minions]


# ══════════════════ BG33_899 Mounting Avalanche ══════════════════


class MountingAvalancheScript:
    """
    Natural language: [x]Sell a friendly minion.
     Give its stats to your
    left-most Elemental.

    Evidence: hearthstone.wiki.gg/wiki/Battlegrounds/Mounting_Avalanche
      — Wiki tags **[Targeted]**（玩家定向选择被卖者——needs_target
      协议）+ Wiki tags [Selling-related]/[Elemental-related]; 文本史
      33.2.2 "Then choose an Elemental" → "Give its stats to your
      **left-most** Elemental"（最左元素确定性结算，非二段选择）。
      "its stats" = 被卖者实体属性快照（卖出前——on_sell 效果可改动
      属性，官方无此边角记载，按宣告时点快照）; 最左元素在卖出后
      的棋盘序上取（板位左移后）。

    Formal spec:
      1. needs_target=True（"Sell a friendly minion" 定向——spell_target
         PendingChoice 分流，候选=棋盘存活友方随从，默认集）
      2. on_play（ctx["target"] 给定）:
         a) 快照被卖者 atk / max_health（卖出**前**——on_sell 效果可
            改动属性; max_health 为属性值, SOP §3）
         b) game.sell_minion(hero, target)——官方"sell"语义: on_sell
            钩子触发 + 出售金币 + 回池（v1 用 Destroy 是缺陷）
         c) 最左存活 Elemental（race ∈ (ELEMENTAL, ALL)，卖出后的
            棋盘序首个）经 tavern_spell_buff 获得快照属性
      3. 无 Elemental（卖后）→ 属性无处可去，落空（被卖者已售出，
         官方行为）; 空棋盘 → spell_target 无候选，法术照常消耗

    Test: test_batch_spells_final.py — PendingChoice 选定→金+1+回池+
    最左元素得快照属性 / SELL_VALUE 覆盖证明走 sell_minion /
    无元素落空 / buff 值随实体属性（非卡面）

    Params: 无模板参数（增益 = 被卖者运行时属性快照）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        snap_atk, snap_health = target.atk, target.max_health
        game.sell_minion(hero, target)
        elementals = [m for m in hero.living_minions()
                      if m.race in _ELEMENTAL_RACES]
        if not elementals:
            return None
        return tavern_spell_buff(elementals[0], snap_atk, snap_health)


# ══════════════════ BG34_272 Menagerie Tableware ══════════════════


class MenagerieTablewareScript:
    """
    Natural language: Give your minions +{0}/+{1}. Repeat for each
    different friendly minion type.

    Formal spec:
      1. on_play: 施加次数 = 1 + 棋盘不同种族数（基础 1 次 + 每个不同
         种族 repeat 1 次; "different friendly minion type" 按实体
         race 去重——NONE 算一种、ALL 算一种，作业单裁定，
         AMBIGUOUS 小点; v1 repeat=max(1,len(types)) 丢基础次且排除
         NONE/ALL——缺陷不沿用）
      2. 每次施加: 全部存活友方随从各经 tavern_spell_buff 获得
         +num(0)/+num(1)
      3. 空棋盘 → 无目标，落空

    Test: test_batch_spells_final.py — 2 鱼 1 机械（2 族）= 3 次
    +3×num(0)/num(1); 单族= 2 次; 双 NONE= 2 次; 空棋盘落空

    Params: {0}=3 {1}=3
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)
        times = 1 + len({m.race for m in living})
        actions = []
        for _ in range(times):
            for m in living:
                actions.append(tavern_spell_buff(m, atk, health))
        return actions


# ══════════════════ BG34_330 Search Through Time ══════════════════


class SearchThroughTimeScript:
    """
    Natural language: <b>Discover</b> a minion of your Tier. Lock it
    in your hand for 1 turn.

    Formal spec:
      1. on_play: DiscoverOwnTierLocked（批内 Action）——发现候选 =
         池感知的本 Tier 随从（Boundless Potential "minion" 分支同构）
      2. resolve: acquire 占池 → create_minion → LOCKED_IN_HAND tag
         （play_minion 拒绝路径, game.py 引擎已接线）→ 进手牌 →
         TURN_START once 监听器（owner=实体, condition=控制者）在
         持有者下一招募阶段开始解锁（"for 1 turn" 边界见 Action
         docstring; 满手排队路径亦被解锁覆盖）
      3. 无候选 → 落空

    Test: test_batch_spells_final.py — 发现项全为本 Tier 且选中入手
    占池 / LOCKED 期 play_minion 拒绝 / turn_start 后解锁可打出

    Params: 无数值参数（tier 取 hero.tavern_tier 运行时值）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return DiscoverOwnTierLocked(hero)


# ══════════════════ BG34_444 Easterly Winds ══════════════════


class EasterlyWindsScript:
    """
    Natural language: [x]After the Tavern
    is <b>Refreshed</b> this game,
    give a random minion
    in it +{0}/+{1}.

    Formal spec:
      1. on_play: 注册持久监听器 Listener(TAVERN_REFRESH, owner=hero)
         ——"this game" 全局持续（法术实体已 REMOVED 不可作 owner，
         hero 恒在场; En-Djinn Blazer batch_battlecry 先例）
      2. 触发条件: kw hero is 施放者（仅自己的酒馆刷新）
      3. 回调: hero.tavern 中随机 Minion（game.rng.choice; 酒馆法术
         不可为对象）经 tavern_spell_buff 获得 +num(0)/+num(1)
         永久增益（购买后随实体带走; TAVERN_SPELL_EXTRA 联动）;
         馆内无随从 → 落空（真实行为）

    Test: test_batch_spells_final.py — 刷新后馆内恰一只随从 +num(0)/
    num(1) / 他人刷新不触发 / 再刷再触发（持久）/ 空馆不崩

    Params: {0}=8 {1}=8
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)

        def on_refresh(g, hero=None, **kw):
            if hero is not source.controller:
                return
            minions = [e for e in source.controller.tavern
                       if isinstance(e, Minion) and not e.dead]
            if not minions:
                return
            m = g.rng.choice(minions, label="easterly_winds_target")
            g.run_actions(tavern_spell_buff(m, atk, health))

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=hero, callback=on_refresh))
        return None


# ══════════════════ BG34_689 Blood Gem Barrage ══════════════════


class BloodGemBarrageScript:
    """
    Natural language: After the Tavern is
     <b>Refreshed</b> this game, give its minions +{0}/+{1} worth of
     <b>Blood Gems</b>.

    Formal spec:
      1. on_play: 注册持久监听器 Listener(TAVERN_REFRESH, owner=hero,
         condition=hero is 施放者)——"this game" 全局持续（Easterly
         Winds 同构）
      2. 触发: 馆内**全部** Minion（"its minions" = 该酒馆的随从）
         各获得 gem=True 标记 Buff(+num(0)/+num(1))——数值即本卡
         模板参数（"+{0}/+{1} worth of Blood Gems" = 等值宝石，非
         BG20_GEM 基础值、不吃 BLOOD_GEM_BONUS 增强）;
         GEMS_PLAYED_ON 计数 +1 + fire blood_gem_played(target=,
         player=)（SOP §10 宝石记账——Jailbird / Gem Confiscation
         数据源统一）; 馆内无随从 → 落空
      3. 与 Easterly Winds 的差异: 全体 vs 随机一只; 宝石标记记账
         vs 普通 buff（tavern_spell_buff 出口不适用——宝石语义
         优先，普通增幅 tag 不并入宝石值）

    Test: test_batch_spells_final.py — 刷新后馆内全体 +num(0)/num(1)
    且 gem buff 存在 / GEMS_PLAYED_ON=1 / blood_gem_played 事件按随从
    数广播 / 他人刷新不触发

    Params: {0}=1 {1}=1
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)

        def on_refresh(g, hero=None, **kw):
            if hero is not source.controller:
                return
            tavern_minions = [e for e in source.controller.tavern
                              if isinstance(e, Minion) and not e.dead]
            for m in tavern_minions:
                g.run_actions(Buff(m, atk=atk, health=health, gem=True))
                m.set(GameTag.GEMS_PLAYED_ON,
                      m.get(GameTag.GEMS_PLAYED_ON, 0) + 1)
                g.events.fire(g, "blood_gem_played",
                              target=m, player=source.controller)

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=hero, callback=on_refresh))
        return None


# ══════════════════ BG34_888 Tomb Turning ══════════════════


class TombTurningScript:
    """
    Natural language: [x]<b>Discover</b> an Undead.
    It dies if you play it
    this turn.

    Formal spec:
      1. on_play: DiscoverUndeadDiesIfPlayed（批内 Action）——发现候选
         = 池感知 UNDEAD 种族（含 ALL, Amalgam 规则），无 tier 限制
         （Contracted Corpse "Discover an Undead" 同构）
      2. resolve: 选中占池入手 + CARD_PLAYED once 监听器
         （owner=实体, condition=card is 实体, 回调校验
         g.turn == 发现阶段回合——"this turn" 自过期）: 打出时
         （card_played 在战吼结算后广播——战吼先触发）health=0 +
         check_deaths（亡语/复生/回池由引擎死亡链处理）
      3. 未在本回合打出 → 标记失效（下回合打出存活）; 死亡走官方
         "dies" 路径（触发亡语; 与 consume 不同）

    Test: test_batch_spells_final.py — 发现项全 UNDEAD 且占池 /
    本回合打出即死（离场+回池）/ 下回合打出存活 / 死亡触发亡语

    Params: 无数值参数
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return DiscoverUndeadDiesIfPlayed(hero)


# ══════════════════ BG34_889 Brood of Nozdormu ══════════════════


class BroodOfNozdormuScript:
    """
    Natural language: <b>Start of Combat:</b> Double your left-most
    minion's Attack.

    Formal spec:
      1. on_play（法术施放即挂载）: 注册 once Listener(START_OF_COMBAT,
         owner=hero——法术实体已 REMOVED 不可作 owner; Upper Hand
         batch_spells1 模式: once + _fired 标记随战斗快照恢复过滤
         game.run_combat——防快照复活重复触发）
      2. 触发（施放者参与的下一场战斗 SoC 事件档, condition hero is
         施放者）: 最左存活随从获得 Buff(atk=当前 atk)——"Double" =
         增量等于现值（战斗内 plain Buff, 战后快照恢复回滚 ✓ 战斗
         buff 语义; 作业单裁定——非 BASE_ATK 覆盖式）
      3. 单场效果实现于本类 start_of_combat 钩子（audit_card_
         registry_v2: data start_of_combat 关键词 → 钩子在册）;
         空棋盘 → 落空

    Test: test_batch_spells_final.py — SoC 后最左 atk 翻倍其余不动 /
    第二场不重复（once 消耗）/ 空棋盘不崩

    Params: 无模板参数（翻倍 = 运行时属性）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = (ctx or {}).get("hero") or source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        leftmost = living[0]
        return Buff(leftmost, atk=leftmost.atk)

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None

        def on_soc(g, hero=None, **kw):
            if hero is not source.controller:
                return
            g.run_actions(BroodOfNozdormuScript.start_of_combat(
                source, g, {"hero": hero}))

        game.events.register(Listener(
            event=START_OF_COMBAT,
            owner=hero,
            once=True,
            condition=lambda hero=None, **kw:
                hero is not None and hero is source.controller,
            callback=on_soc,
        ))
        return None


# ══════════════════ BG34_990 Wave of Gold ══════════════════


class WaveOfGoldScript:
    """
    Natural language: Give your minions +{0}/+{1}. Give Golden ones
    another +{0}/+{1}.

    Formal spec:
      1. on_play: 第一遍——全部存活友方随从各经 tavern_spell_buff
         +num(0)/+num(1); 第二遍——其中 is_golden 者再各一次
      2. 金色实体判定 is_golden（GOLDEN tag——三连/Reno 式金色化均
         置位）; 空棋盘 → 落空

    Test: test_batch_spells_final.py — 金色 2×num、非金色 1×num /
    空棋盘落空

    Params: {0}=3 {1}=2
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)
        actions = [tavern_spell_buff(m, atk, health) for m in living]
        actions += [tavern_spell_buff(m, atk, health)
                    for m in living if m.is_golden]
        return actions


# ══════════════════ BG35_149 Deepwater Clan ══════════════════


class DeepwaterClanScript:
    """
    Natural language: Give a minion +{0}/+{1}. Give your Murlocs
    +{0}/{1}.（data 原文: Give a minion +{0}/+{1}. Give your
    Murlocs +{0}/+{1}.）

    Formal spec:
      1. needs_target=True（"Give a minion" 定向——spell_target
         PendingChoice 分流; 无候选棋盘 → 落空但法术照常消耗）
      2. on_play: target 经 tavern_spell_buff +num(0)/num(1);
         随后全部存活友方 Murloc（race ∈ (MURLOC, ALL)）各 +num(0)/
         num(1)——target 若为 Murloc 两句叠加共 2 份（HS 连续两句
         文本语义; v1 排除 target 是缺陷）
      3. 空棋盘 → 落空

    Test: test_batch_spells_final.py — Murloc 目标 2×num+非目标鱼
    1×num / Beast 目标: 目标 1×、鱼 1× / 空棋盘落空

    Params: {0}=2 {1}=2
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)
        actions = [tavern_spell_buff(target, atk, health)]
        actions += [tavern_spell_buff(m, atk, health)
                    for m in hero.living_minions()
                    if m.race in _MURLOC_RACES]
        return actions


# ══════════════════ BG35_912 Eonar's Favor ══════════════════


class EonarsFavorScript:
    """
    Natural language: Choose a minion. Give minions of its type in the
    Tavern +{0}/+{1} this game.

    Formal spec:
      1. needs_target=True——"Choose a minion" 定向（v1 先例: 候选 =
         己方棋盘存活随从, spell_target PendingChoice 分流）
      2. on_play（target.race 判定）:
         a) race == NONE → 落空（无 "its type" 可言, v1 先例）
         b) 否则 Staff of Enrichment 双件（batch_spells3）:
            持久面 ApplyTavernBuff(TavernBuff(+num(0)+extra /
            +num(1)+extra, race_filter=target.race))——refresh 自动
            应用新入馆匹配随从; 立即面 BuffCurrentTavern（当前馆
            race 匹配 + ALL 随从立即增益）
         c) AMBIGUOUS: target.race == ALL 时 race_filter=ALL——
            TavernBuff.matches 契约下仅 ALL 种族（Amalgam）入馆
            匹配（保守, v1 fizzles ALL 不沿用——按 matches 契约
            透传, docstring 存证）
      3. TAVERN_SPELL_EXTRA_* 施放时快照并入两面（Staff of
         Enrichment 同构——持久 buff 为不可变记录）

    Test: test_batch_spells_final.py — 馆内同族+ALL 增益/他族不动/
    hero.tavern_buffs 登记 / NONE 目标落空

    Params: {0}=3 {1}=3
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        race = target.race
        if race == Race.NONE:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)
        extra_atk = hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0)
        extra_health = hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
        tb = TavernBuff(atk=atk + extra_atk, health=health + extra_health,
                        race_filter=race, source_id=source.card_id)
        return [ApplyTavernBuff(hero, tb), BuffCurrentTavern(hero, tb)]


# ══════════════════ BG35_922 Queen's Command ══════════════════


class QueensCommandScript:
    """
    Natural language: Give your minions +{0}/+{1}. Give all your Naga
    another +{0}/+{1}.

    Formal spec:
      1. on_play: 第一遍全体存活友方 +num(0)/num(1); 第二遍 Naga
         （race ∈ (NAGA, ALL), Amalgam 规则）再各一份
      2. 空棋盘 → 落空

    Test: test_batch_spells_final.py — Naga 2×num、非 Naga 1×num /
    Amalgam 计入 Naga / 空棋盘落空

    Params: {0}=2 {1}=2
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)
        actions = [tavern_spell_buff(m, atk, health) for m in living]
        actions += [tavern_spell_buff(m, atk, health)
                    for m in living if m.race in _NAGA_RACES]
        return actions


# ══════════════════ BG35_951 Might of Stormwind ══════════════════


class MightOfStormwindScript:
    """
    Natural language: Give four random friendly minions +{0}/+{1}.

    Formal spec:
      1. on_play: 存活友方随从中 game.rng.sample 随机 4 个**不同**
         实体（不足 4 全取）各经 tavern_spell_buff +num(0)/num(1)
         （文本 "random" 显式——rng 语义, SOP §9 裁决库）
      2. 空棋盘 → 落空

    Test: test_batch_spells_final.py — 5 随从恰 4 个各 +num、余 1 个
    不动 / 空棋盘落空

    Params: {0}=1 {1}=2（count=4 为 "four" 文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        targets = game.rng.sample(living, min(4, len(living)),
                                  label="stormwind_targets")
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)
        return [tavern_spell_buff(m, atk, health) for m in targets]


# ══════════════════ BG36_624 Repair Job ══════════════════


class RepairJobScript:
    """
    Natural language: Give a minion +{0}/+{1}.

    Formal spec:
      1. needs_target=True（"Give a minion" 定向——spell_target
         PendingChoice 分流）; 无候选 → 落空但法术照常消耗（官方:
         无法术目标时法术仍可施放）
      2. on_play: target 经 tavern_spell_buff +num(0)/num(1)
         （TAVERN_SPELL_EXTRA 联动）

    Test: test_batch_spells_final.py — 目标 +num(0)/num(1) 其余不动 /
    空棋盘落空不崩

    Params: {0}=4 {1}=8
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)
        return tavern_spell_buff(target, atk, health)


# ══════════════════ BG36_880 Methodical Madness ══════════════════


class MethodicalMadnessScript:
    """
    Natural language: [x]Choose a friendly Demon.
    It consumes 2 random
    Tavern minions to gain their
    stats and <b><b>Bonus Keyword</b>s</b>.

    Formal spec:
      1. needs_target=True + target_candidates = 棋盘存活友方 Demon
         （race ∈ (DEMON, ALL)）——Mind Muck batch_consume 同构
         （wiki [Targeted]: 玩家定向）; 无候选 → 落空但法术照常消耗
      2. on_play: 2 次独立 ConsumeRandomTavernWithKeywords(target)——
         每次随机吞噬 demon 控制者酒馆一随从:
         - 属性: 恶魔获得受害者 atk/max_health（ConsumeMinion 权威:
           酒馆来源回池、不触发亡语、fire minion_consumed）
         - Bonus Keywords（S14）: 受害者战斗关键词（Taunt/DS/
           Windfury/Poisonous/Venomous/Reborn/Stealth/Cleave）
           快照移转给恶魔（官方 36.2 报道 "transfer Divine Shield,
           Taunt or other properties"）
      3. 酒馆无随从 → 对应次数落空（真实池空行为）; "2" 文本字面量

    Test: test_batch_spells_final.py — 两次吞噬属性合计+受害者关键词
    移转+馆空回池 / 候选排除非 Demon / 空酒馆落空

    Params: 无模板参数（吞噬增益 = 受害者运行时属性; count=2 为
    "2" 文本字面量）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in _DEMON_RACES]

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None or target.dead or target.zone != Zone.PLAY:
            return None
        return [ConsumeRandomTavernWithKeywords(target)
                for _ in range(2)]


# ══════════════════ BG36_883 Winner's Bread ══════════════════


class WinnersBreadScript:
    """
    Natural language: [x]Give a minion +{0}/+{1}.
    If you win your next combat,
    give it another +{2}/+{3} at
    the start of your next turn.

    Formal spec:
      1. needs_target=True（"Give a minion" 定向）; on_play 即时面:
         target 经 tavern_spell_buff +num(0)/num(1)
      2. 挂载 once Listener(COMBAT_END, owner=hero——法术实体已
         REMOVED; Overconfidence batch_spells3 模式): condition=
         hero_a/hero_b 之一是施放者（他人战斗不消耗 "your next
         combat"; 幽灵战亦广播 combat_end——引擎 Wave4 接线）
      3. 触发: result.winner is 施放者 → ScheduleNextTurn(
         WinnersBreadNextTurnBuff(target, card_id))——下一招募阶段
         开始（_begin_recruit_for 金币重置后, "at the start of your
         next turn" 时点）目标仍在场则经 tavern_spell_buff 追加
         +num(2)/num(3)（已卖出/死亡 → 落空）; 败/平 → 无第二段，
         once 无论胜负均消耗
      4. combat_end 在战后快照恢复后广播——延迟 buff 落在复原棋盘上

    Test: test_batch_spells_final.py — 即时 +num(0)/num(1); 胜→下回
    合开始 +num(2)/num(3); 败→无第二段; 目标卖出→第二段落空;
    单次消耗

    Params: {0}=2 {1}=3 {2}=4 {3}=6
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = _require_nums(d, source.card_id, 0, 1)

        def on_combat_end(g, hero_a=None, hero_b=None, result=None,
                          **kw):
            if result is None or result.winner is not hero:
                return
            g.run_actions(ScheduleNextTurn(
                hero, WinnersBreadNextTurnBuff(target, source.card_id)))

        game.events.register(Listener(
            event=COMBAT_END,
            owner=hero,
            once=True,
            condition=lambda hero_a=None, hero_b=None, **kw:
                hero_a is hero or hero_b is hero,
            callback=on_combat_end,
        ))
        return tavern_spell_buff(target, atk, health)


# ══════════════════ BG36_884 Weapons Forge ══════════════════


class WeaponsForgeScript:
    """
    Natural language: Get 3 Pointy Arrows.

    Formal spec:
      1. on_play: num(0) 张 Pointy Arrow（EBG_Spell_014——BG32_170
         Metallic Hunter 亡语同源 token, data 核实）进手牌:
         非池法术（is_pool_spell=False）不占 spell_pool——直接
         create_spell + pending_hand_add（满手排队, P6）
      2. 数量唯一来源 num(0)（=3; 模板参数权威——"3" 文本占位 {0}）

    Test: test_batch_spells_final.py — 手牌 +num(0) 张 EBG_Spell_014
    且 spell_pool 无占用

    Params: {0}=3
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        count, = _require_nums(d, source.card_id, 0)
        for _ in range(count):
            game.pending_hand_add(
                hero, game.create_spell(_SPELL_POINTY_ARROW,
                                        controller=hero))
        return None


# ══════════════════ EBG_Spell_017 Eyes of the Earth Mother ══════════════════


def _earth_mother_candidates(source, game):
    """候选: 友方存活、非金色（Reno 先例）、T≤4、金色卡定义存在。"""
    hero = source.controller
    if hero is None:
        return []
    out = []
    for m in hero.board:
        if m.dead or m.is_golden:
            continue
        if m.tech_level > 4:       # "from Tier 4 or below"
            continue
        d = game.db.get(m.card_id)
        if d is None or game.db.golden_version(d) is None:
            continue
        out.append(m)
    return out


class EyesOfTheEarthMotherScript:
    """
    Natural language: Choose a friendly minion from Tier 4 or below.
    Make it Golden.

    Formal spec:
      1. needs_target=True + target_candidates（Captain Sanders
         batch_battlecry 同构）: 友方存活、非金色（已金色不可再金色化
         ——Reno 先例）、tech_level ≤ 4（"from Tier 4 or below" 文本
         字面量）、db.golden_version 存在; 无候选 → 落空但法术照常
         消耗
      2. on_play: _goldenize（batch_battlecry Reno 式 import）——
         Transform 到金色卡定义、buff 并集保留、**不发三连奖励**
         （金色化 ≠ 三连）; v1 的 "atk/health×2 白板近似" 是缺陷

    Test: test_batch_spells_final.py — PendingChoice 流+buff 保留+
    无三连奖励 / T5 与已金色排除 / 无候选落空

    Params: 无模板参数（"Tier 4" 为文本字面量）
    """

    needs_target = True
    target_candidates = staticmethod(_earth_mother_candidates)

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        from hsrl2.scripts.batches.batch_battlecry import _goldenize
        _goldenize(game, target)
        return None


# ══════════════════ EBG_Spell_032 Channel the Devourer ══════════════════


class ChannelTheDevourerScript:
    """
    Natural language: Sell a friendly minion.
    Give its stats to a random friendly minion.

    Formal spec:
      1. needs_target=True（"Sell a friendly minion" 定向——spell_target
         PendingChoice 分流，候选=棋盘存活友方随从）
      2. on_play:
         a) 快照被卖者 atk / max_health（卖出**前**; max_health 为
            属性值, SOP §3; v1 用 health 是缺陷）
         b) game.sell_minion(hero, target)——官方"sell"语义（on_sell
            钩子 + 金币 + 回池; v1 用 Destroy 是缺陷）
         c) 卖后剩余存活友方中 game.rng.choice 随机一只经
            tavern_spell_buff 获得快照属性（卖后求值——on_sell 效果
            改动后的棋盘为准）; 无剩余 → 落空
      3. 空棋盘 → 无候选，法术照常消耗

    Test: test_batch_spells_final.py — 快照属性到随机存活者（总量
    断言）/ SELL_VALUE 证明走 sell_minion / 独子棋盘卖出后落空

    Params: 无模板参数（增益 = 被卖者运行时属性快照）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        snap_atk, snap_health = target.atk, target.max_health
        game.sell_minion(hero, target)
        others = hero.living_minions()
        if not others:
            return None
        receiver = game.rng.choice(others,
                                   label="channel_devourer_receiver")
        return tavern_spell_buff(receiver, snap_atk, snap_health)


# ══════════════════ EBG_Spell_037 Unmasked Identity ══════════════════


class UnmaskedIdentityScript:
    """
    Natural language: <b>Discover</b> a new
    Hero Power.

    Status: DEFERRED — requires 英雄技能体系

    Dependency: "Discover a new Hero Power" 需要英雄技能系统——
    v2 引擎无 hero_power 脚本/池（REFACTOR_PLAN 未迁移项，hero/
    hero_power 相关检索无英雄技能数据链），发现候选集与替换语义
    均无从谈起。近似实现（如发现随从顶替）是简化，禁止。主线
    迁移英雄技能体系后解冻。
    """

    @staticmethod
    def on_play(source, game, ctx):
        return None


# ══════════════════ EBG_Spell_038 Lost Staff of Hamuul ══════════════════


class LostStaffOfHamuulScript:
    """
    Natural language: [x]Choose a minion.
    <b>Refresh</b> the Tavern
    with minions of its type.

    Formal spec:
      1. needs_target=True——"Choose a minion" 定向（v1 先例 + Eonar's
         Favor 同构: 候选 = 己方棋盘存活随从, spell_target 分流）
      2. on_play（target.race）: _refresh_tavern_of_type（批内帮助，
         引擎 refresh_tavern 无 race_filter——缺口 #1, 手动全镜像:
         冻结保留/回池/tier 加权抽取/tavern_buffs 应用/法术位/Fodder
         协议/tavern_refresh 广播/免费）:
          - race != NONE → 抽取过滤 race（Amalgam=ALL 匹配任意查询）
          - race == NONE → 无 "its type"——按不限族常规刷新落空面
            处理（刷新仍发生，保守裁定; 卡页无 Notes，2026-08-23
            全文核对，边角上报主线）
          - race == ALL → 仅 ALL 种族入馆（TavernBuff.matches 同
            契约——Amalgam 匹配任意查询的引擎既有口径，同上报）
      3. "Refresh the Tavern" 计为刷新: fire tavern_refresh（
         Easterly Winds / Blood Gem Barrage / Fodder 可观测）;
         不扣金币（法术自身效果）

    Test: test_batch_spells_final.py — 馆内容全部为目标种族（或 ALL）
    且数量=TAVERN_OFFERS[tier] / 旧馆内容回池 / tavern_refresh 事件
    广播 / NONE 目标走不限族刷新

    Params: 无数值参数（刷新数量 = TAVERN_OFFERS 运行时值）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        race = target.race
        _refresh_tavern_of_type(game, hero,
                                None if race == Race.NONE else race)
        return None


# ════════════════════ 注册 ══════════════════

# （无金色 id——池法术无金色卡定义，见模块 docstring 数据核实）
_REGISTRATIONS = [
    ("BG33_817", SanctifyScript),
    ("BG33_899", MountingAvalancheScript),
    ("BG34_272", MenagerieTablewareScript),
    ("BG34_330", SearchThroughTimeScript),
    ("BG34_444", EasterlyWindsScript),
    ("BG34_689", BloodGemBarrageScript),
    ("BG34_888", TombTurningScript),
    ("BG34_889", BroodOfNozdormuScript),
    ("BG34_990", WaveOfGoldScript),
    ("BG35_149", DeepwaterClanScript),
    ("BG35_912", EonarsFavorScript),
    ("BG35_922", QueensCommandScript),
    ("BG35_951", MightOfStormwindScript),
    ("BG36_624", RepairJobScript),
    ("BG36_880", MethodicalMadnessScript),
    ("BG36_883", WinnersBreadScript),
    ("BG36_884", WeaponsForgeScript),
    ("EBG_Spell_017", EyesOfTheEarthMotherScript),
    ("EBG_Spell_032", ChannelTheDevourerScript),
    ("EBG_Spell_038", LostStaffOfHamuulScript),
]
# DEFERRED 未注册: EBG_Spell_037 Unmasked Identity（英雄技能体系）


def register() -> list[str]:
    """注册本批次全部脚本，返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []
    for card_id, script_cls in _REGISTRATIONS:
        _register(card_id, script_cls)
        registered.append(card_id)
    return registered
