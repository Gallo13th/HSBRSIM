"""批次 activate — S14 Activate 池随从 14 张（作业单 2026-08-21）。

OK 10 张（含金色 id; 金色=独立卡定义）:
  BG36_180 Living Prison / BG36_201 Lurking Lionfish / BG36_240 Hired
  Mount / BG36_342 Clever Castaway / BG36_346 Fruit Vendor /
  BG36_354 Decoy Conjurer / BG36_503 Soulkeeping Jailer /
  BG36_506 Drone Duplicator / BG36_507 Breakout Mastermind /
  BG36_511 Dead Bellringer

AMBIGUOUS 3 张（不注册，主线查 wiki 裁决后实现）:
  BG36_345 Suspicious Prisonguard — "Give another minion +{0}/+{1}"
    目标选择方式无文本证据（无 "Choose"/"random"/[Targeted] 档案）。
    候选: A) 玩家定向（PendingChoice kind="activate_target"，Kelp
    Keeper BG36_701 终裁先例——若 wiki tags 含 [Targeted]）;
    B) 随机另一友方随从（Mummifier "a different friendly Undead"
    随机先例）。数值索引陷阱: 费用是 num(2)=1，buff 是 num(0)/num(1)
    =3/3（金色 6/6）。
  BG36_356 Tyrael — "Set another minion's stats to {1}/{2}"
    同 Prisonguard 目标歧义（候选 A/B 同上）。数值: num(1)/num(2)
    =50/50（金色 100/100）。
  BG36_621 Deft Deserter — "Give all minions in the Tavern +{1}/+{2}
    and Taunt, Divine Shield, or Windfury"（作业单文本截断，全文含
    "Divine Shield, or Windfury" 三选一子句）。关键词子句无
    "Choose"/"random" 证据。候选: A) 玩家三选一（PendingChoice，
    选定关键词授予全体馆内随从）; B) 每随从独立随机三选一;
    C) 单次随机三选一授予全体。数值: num(1)/num(2)=8/8（金色 16/16）。

DEFERRED 1 张（不注册）:
  BG36_508 Cagey Conjurer — "Cast {1} random Tavern spells (targets
    this if possible)"。效果直施（Runic Arcanist 先例）要求被施法术
    的 on_play 脚本全量就绪; 当前 75 张池法术中仅 2 张已注册
    （BG28_518 Chef's Choice / BG36_246 Mighty Dragonbreath），随机
    候选过滤为"已注册子集"会扭曲官方分布=近似，禁止。详见
    CageyConjurerScript docstring 的未注册清单。

共性: activate 钩子在 game.use_activate 内触发——金币扣减
（ACTIVATE_COST 来自 data activate_cost）、每回合 1 次
（ACTIVATE_USED_THIS_TURN）由引擎保证，脚本只写效果本体。
[Targeted]/Choose 类经 PendingChoice 队列化建模（Kelp Keeper /
Sky-hatch Runaway 先例），"Choose a card in the Tavern" 用
kind="tavern_pick"（本批作业单约定）。

引擎缺口报告（主线处理）:
  1. Fishbait (BG36_205) "This can't gain stats" 无引擎机制/无 tag
     （tags.py 主线专属）——馆内 buff 类效果（Deft Deserter 等）无法
     豁免它; 本批 Lionfish 仅创建实体不受影响。
  2. Cagey Conjurer 依赖的池法术脚本缺口见 DEFERRED 清单（法术批次）。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainKeyword, GetRandomMinion
from hsrl2.actions.consume import ConsumeMinion, ConsumeRandomTavernMinion
from hsrl2.events import MINION_BOUGHT, Listener, MAGNETIZED
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

# Chromadrake token 全集复用（batch_rally2 漂移守护测试同源）
from hsrl2.scripts.batches.batch_rally2 import CHROMADRAKE_IDS

_TAVERN_DISCOVER_KIND = "discover_spell"   # 作业单约定 kind
_TAVERN_PICK_KIND = "tavern_pick"          # 作业单约定 kind


def _undead_races() -> tuple:
    return (Race.UNDEAD, Race.ALL)


# ══════════════════ BG36_180 Living Prison ══════════════════


class LivingPrisonScript:
    """
    Natural language: <b>Activate ({0}):</b> Gain the stats of the next
    minion you buy this turn.

    Formal spec:
      1. activate: 在 hero 上记录待决状态（脚本层契约属性
         ``hero._living_prison_pending = (source.uuid, mult, game.turn)``，
         spellcraft_source_uuid 同款模式）——**最新激活覆盖旧值**
         （同回合多次激活以最后一次为准，ACTIVATE_USED_THIS_TURN 引擎
         保证同随从每回合仅一次，不同 Living Prison 各自激活时后写胜）。
      2. on_summon 注册持久监听器（owner=source，出售/招募期死亡注销）:
         事件 MINION_BOUGHT（buy_from_tavern 购买随从后 fire; 法术购买
         不 fire——"the next minion you buy" 语义精确匹配）。
      3. 回调条件: 待决状态存在、uuid 匹配**本 Prison**（激活者获益，
         多 Prison 在场不串扰）、turn 匹配（"this turn" 过期作废）。
         满足 → 快照买到的随从 atk / max_health（SOP 属性快照纪律），
         Buff(source, atk=atk×mult, health=max_health×mult)，然后清空
         待决状态（"the next" 一次性）。
      4. Prison 在购买发生前离场（出售/死亡）→ 监听器已注销，无效果;
         本回合未购买 → 回合戳失配，作废。
      5. 金色版 "Gain double the stats" → mult=2（金色文本字面量）。

    Test: test_batch_activate.py — 激活后购买随从 Prison 获得其
    atk/max_health / 跨回合作废 / 法术购买不消耗 / 金色双倍 /
    未激活时购买无效果

    Params: {0}=1（activate 费用显示参数，与 activate_cost 同值;
    增益数值来源 = 买到随从的运行时属性，无模板参数）
    """

    mult = 1   # 金色 "double" → 2（金色文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_bought(g, minion=None, **kw):
            hero = source.controller
            if hero is None or minion is None:
                return
            pending = getattr(hero, "_living_prison_pending", None)
            if pending is None:
                return
            prison_uuid, mult, turn = pending
            if prison_uuid != source.uuid or turn != g.turn:
                return
            hero._living_prison_pending = None
            g.run_actions(Buff(source, atk=minion.atk * mult,
                               health=minion.max_health * mult))

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=source, callback=on_bought))
        return None

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hero._living_prison_pending = (
            source.uuid, source.scripts.mult, game.turn)
        return None


class LivingPrisonGoldenScript(LivingPrisonScript):
    """
    Natural language: <b>Activate ({0}):</b> Gain double the stats of
    the next minion you buy this turn.

    Formal spec: 同基础版，mult=2——买到的随从 atk/max_health ×2。

    Test: test_batch_activate.py — 金色激活后购买，+2×(atk/max_health)

    Params: {0}=1（金色 activate 费用，与 activate_cost 同值）
    """

    mult = 2


# ══════════════════ BG36_201 Lurking Lionfish ══════════════════


class LurkingLionfishScript:
    """
    Natural language: <b>Activate ({0}):</b> Choose a card in the Tavern.
    Replace it with a Fishbait for your left-most Beast to attack.

    Formal spec:
      1. activate: 候选 = hero.tavern 全部实体（随从**与**法术——
         "a card" 通名）; 空馆 → 无效果（费用已扣，Sky-hatch Runaway
         批次先例）。否则 pending_choices.append(PendingChoice(owner,
         候选, kind="tavern_pick", resolve))。
      2. resolve(被选者) 依次:
         a) 移出酒馆并回池（"被替换 = 未购买 → 回池"，Snarky Shark
            1b 裁定）: Minion → release_minion_entity（金色 3 份/
            token 不回池由池内守卫保证）; 池法术 → spell_pool.release;
            非池实体仅移除。zone=REMOVED。
         b) Fishbait 实体: create_minion(由 source 的 CardDef.
            evolution_card_id 数据链解析——BG36_201→BG36_205、金色
            BG36_201_G→BG36_205_G，零硬编码卡 id），zone=TAVERN，
            **插入被替换者的原槽位**（"Replace" 语义）。
         c) 最左 Beast 攻击: 候选 = hero.board 存活 race ∈
            (BEAST, ALL)——**含 source 自身**（Lionfish 是 Beast 且
            在场，区别于 Snarky Shark 已售出场景）; 取最左，
            game.recruit_phase_attack(beast, fishbait)——双向同时
            伤害 / KILLER 设置 / Fishbait 死亡从酒馆移除不回池 /
            Rally(伤害前) / after_attack 均由该 API 保证。
            无 Beast（理论仅存种族改写边角）→ 不攻击，Fishbait
            留在酒馆（官方行为，Snarky Shark 同款）。
      3. Fishbait 自身亡语（"Give the minion that killed this
         +{0}/+{1}"）由其自身脚本负责（本批未含，见模块 docstring
         引擎缺口/后续批次）。
      4. 金色版经 evolution_card_id 金色链自动取 BG36_205_G →
         同一脚本类注册两个 id。

    Test: test_batch_activate.py — 选择随从被替换回池且 Fishbait 入馆
    被最左 Beast（含 Lionfish 自身）击杀移除 / 选择法术走法术池回池 /
    金色出金色 Fishbait / 空馆无效果不崩

    Params: {0}=2（activate 费用显示参数，与 activate_cost 同值）
    """

    @staticmethod
    def activate(source, game, ctx):
        from hsrl2.game import PendingChoice
        hero = source.controller
        if hero is None:
            return None
        candidates = list(hero.tavern)
        if not candidates:
            return None

        def resolve(pick):
            idx = hero.tavern.index(pick)
            hero.tavern.pop(idx)
            if isinstance(pick, Minion):
                game.minion_pool.release_minion_entity(pick)
            else:
                d = game.db.get(pick.card_id)
                if d is not None and d.is_pool_spell:
                    game.spell_pool.release(pick.card_id)
            pick.zone = Zone.REMOVED
            d = game.db.get(source.card_id)
            fishbait = game.create_minion(
                game.db.by_dbf(d.evolution_card_id).id, controller=hero)
            fishbait.zone = Zone.TAVERN
            hero.tavern.insert(idx, fishbait)
            beasts = [m for m in hero.board
                      if not m.dead and m.race in (Race.BEAST, Race.ALL)]
            if beasts:
                game.recruit_phase_attack(beasts[0], fishbait)

        game.pending_choices.append(PendingChoice(
            hero, candidates, _TAVERN_PICK_KIND, resolve_callback=resolve))
        return None


# ══════════════════ BG36_240 Hired Mount ══════════════════


class HiredMountScript:
    """
    Natural language: <b>Activate ({0}):</b> Get a random
    <b>Chromadrake</b>.

    Formal spec:
      1. activate: 从 CHROMADRAKE_IDS（5 张非池 token——batch_rally2
         漂移守护同源）随机取 times 张进手牌（create_minion +
         pending_hand_add 满手排队，RULES §3.3）; token 不占池
         （SOP 清单）。
      2. times 次独立选取（金色 "2 random Chromadrakes"——可同可不同）。
      3. Chromadrake 各自 Battlecry 由其自身脚本负责（token 批次）。

    Test: test_batch_activate.py — 激活后手牌 +times 张 Chromadrake /
    不占随从池 / 金色 2 张

    Params: {0}=2（activate 费用显示参数，与 activate_cost 同值;
    "a random" 无数量模板参数）
    """

    times = 1   # 金色 "2 random Chromadrakes" → 2（金色文本字面量）

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(source.scripts.times):
            cid = game.rng.choice(CHROMADRAKE_IDS,
                                  label="hired_mount_chromadrake")
            game.pending_hand_add(hero,
                                  game.create_minion(cid, controller=hero))
        return None


class HiredMountGoldenScript(HiredMountScript):
    """
    Natural language: <b>Activate ({0}):</b> Get 2 random
    <b>Chromadrakes</b>.

    Formal spec: 同基础版，times=2（两次独立随机选取）。

    Test: test_batch_activate.py — 金色一次激活获得 2 张 Chromadrake

    Params: {0}=2（金色 activate 费用，与 activate_cost 同值）
    """

    times = 2


# ══════════════════ BG36_342 Clever Castaway ══════════════════


class CleverCastawayScript:
    """
    Natural language: <b>Activate ({0}): Discover</b> a Tavern spell.

    Formal spec:
      1. activate: discovers 次独立发现（金色 "Discover 2 Tavern
         spells" = 两个独立 PendingChoice，队列化不互相覆盖）。
      2. 每次发现: 候选 = db.pool_spells() 中 spell_pool.available>0
         者（池约束 RULES §6.18; 作业单约定——无 tier 过滤，"a
         Tavern spell" 通指酒馆法术卡池全量）; rng.sample 抽 3 个
         **不同**选项（不足 3 全给，Discover 官方行为）;
         无候选 → 该次落空。
      3. resolve(pick_id): spell_pool.acquire 占池（每张 1 份，
         RULES §3.6.1）→ create_spell → pending_hand_add。
         自定义 resolve——actions/discover.Discover 的默认 resolve
         是随从语义（minion_pool.acquire + create_minion），不适用，
         故直接构造 PendingChoice。
      4. 候选无 tier 限制对照: engine SpellPool.draw_tavern 的 tier
         过滤是**展示**约束; Discover 不经展示，全池候选（作业单
         约定; 池感知仅 available 闸门）。

    Test: test_batch_activate.py — PendingChoice(kind="discover_spell")
    选定后法术入手且占池 / 选项不含池外/已耗尽法术 / 金色两次发现 /
    法术池耗尽落空

    Params: {0}=2（activate 费用显示参数，与 activate_cost 同值;
    "3" 为 Discover 官方选项数文本字面量）
    """

    discovers = 1   # 金色 "Discover 2 Tavern spells" → 2（金色文本字面量）

    @staticmethod
    def activate(source, game, ctx):
        from hsrl2.game import GameStateError, PendingChoice
        hero = source.controller
        if hero is None:
            return None
        for _ in range(source.scripts.discovers):
            cands = [d.id for d in game.db.pool_spells()
                     if game.spell_pool.available(d.id) > 0]
            if not cands:
                continue
            options = game.rng.sample(cands, min(3, len(cands)),
                                      label="castaway_spell_options")

            def resolve(pick_id):
                if not game.spell_pool.acquire(pick_id):
                    raise GameStateError(
                        f"Clever Castaway: spell pick {pick_id} no "
                        f"longer available in pool")
                game.pending_hand_add(
                    hero, game.create_spell(pick_id, controller=hero))

            game.pending_choices.append(PendingChoice(
                hero, options, _TAVERN_DISCOVER_KIND,
                resolve_callback=resolve))
        return None


class CleverCastawayGoldenScript(CleverCastawayScript):
    """
    Natural language: <b>Activate ({0}): Discover</b> 2 Tavern spells.

    Formal spec: 同基础版，discovers=2——两个独立发现依次入队
    （PendingChoice 队列化，玩家逐个选择）。

    Test: test_batch_activate.py — 金色激活产生 2 个 discover_spell
    PendingChoice，各自选择各自占池

    Params: {0}=2（金色 activate 费用，与 activate_cost 同值）
    """

    discovers = 2


# ══════════════════ BG36_346 Fruit Vendor ══════════════════


class FruitVendorScript:
    """
    Natural language: <b>Activate ({0}):</b> Get {1} Tavern Dish Bananas.

    Formal spec:
      1. activate: Tavern Dish Banana = BG28_897（池法术 T1 "Give a
         minion +{0}/+{1}"）——卡 id 经 source 的 CardDef.
         evolution_card_id 数据链解析（dbf 105752，Snarky Shark
         Fishbait 同款零硬编码）。
      2. 获取 num(1) 份: 池法术全局单份（RULES §3.6.1）——首份
         spell_pool.acquire 占池; 余份（池已无副本）生成为净增实体
         不占池（Mystic Essence Dark Gift "池空生成不占池" 先例;
         官方 "Get {1}" 恒给满 num(1) 份）。每份 create_spell →
         pending_hand_add（满手排队）。打出的回池经 spell_pool
         release 的集合语义自然去重，无池超计。
      3. 金色版 num(1)=4 → 同一脚本类注册两个 id，数值自然体现。

    Test: test_batch_activate.py — 激活后手牌 +num(1) 张 BG28_897（池
    单份不截断）/ 首份占池 / 金色 4 张

    Params: {0}=1 {1}=2（36.2.2 基线，金色 {1}=4）
    """

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        banana_id = game.db.by_dbf(d.evolution_card_id).id
        for _ in range(d.num(1)):
            game.spell_pool.acquire(banana_id)   # 单份池: 有则占，无则净增
            game.pending_hand_add(
                hero, game.create_spell(banana_id, controller=hero))
        return None


# ══════════════════ BG36_354 Decoy Conjurer ══════════════════


class DecoyConjurerScript:
    """
    Natural language: <b>Activate ({0}):</b> Steal the highest-Attack
    minion in the Tavern.

    Formal spec:
      1. activate: 候选 = hero.tavern 中的 Minion（"minion"——法术
         不可偷）。
      2. steals 次迭代（金色 "the 2 highest-Attack minions"）: 每次取
         当前候选中最高 atk 者; 并列最高 → rng.choice 平票随机
         （官方未公布平票规则，随机为标准建模）; 逐次从候选剔除
         （偷走的不再参与后续"最高"判定）。
      3. Steal = **实体转移**（作业单裁定）: 该随从在馆 = 抽取展示时
         已 acquire 占池 → 偷取不重复占池; hero.tavern.remove →
         zone=HAND → pending_hand_add（满手排队不销毁，P6）。
         后续出售/淘汰经 release_minion_entity 正常回池，池守恒。
      4. 馆内无随从（仅法术/空馆）→ 无效果（费用已扣）。

    Test: test_batch_activate.py — 偷走最高攻随从实体入手（身份断言
    同一实体）且不重复占池 / 平票不崩 / 金色偷 2 张 / 无随从落空

    Params: {0}=2（activate 费用显示参数，与 activate_cost 同值;
    "highest-Attack" 为运行时比较无模板参数）
    """

    steals = 1   # 金色 "the 2 highest-Attack" → 2（金色文本字面量）

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = [m for m in hero.tavern if isinstance(m, Minion)]
        for _ in range(source.scripts.steals):
            if not cands:
                break
            top = max(m.atk for m in cands)
            tied = [m for m in cands if m.atk == top]
            victim = game.rng.choice(tied, label="decoy_conjurer_steal")
            cands.remove(victim)
            hero.tavern.remove(victim)
            victim.zone = Zone.HAND
            game.pending_hand_add(hero, victim)
        return None


class DecoyConjurerGoldenScript(DecoyConjurerScript):
    """
    Natural language: <b>Activate ({0}):</b> Steal the 2 highest-Attack
    minions in the Tavern.

    Formal spec: 同基础版，steals=2——两次迭代偷走前二高攻
    （每次重估当前最高，含平票随机）。

    Test: test_batch_activate.py — 金色偷走 2 张（最高+次高）

    Params: {0}=2（金色 activate 费用，与 activate_cost 同值）
    """

    steals = 2


# ══════════════════ BG36_503 Soulkeeping Jailer ══════════════════


class SoulkeepingJailerScript:
    """
    Natural language: <b>Activate ({0}):</b> Your Demons each consume a
    random minion in the Tavern to gain its stats.

    Formal spec:
      1. activate: 候选恶魔 = hero.board 存活 race ∈ (DEMON, ALL)
         ——**含 source 自身**（Jailer 是 Demon，"Your Demons each"
         官方语义含自身）; 无恶魔 → 无效果（费用已扣）。
      2. 每个恶魔一个 ConsumeRandomTavernMinion(demon)（actions/
         consume.py 全套保证: 随机走 game.rng、受害者 atk/max_health
         永久 Buff、酒馆来源回池、不触发亡语、fire minion_consumed）;
         逐恶魔依次结算——馆内随从被逐一消耗，后者从剩余中随机。
      3. 馆内无随从的恶魔 → 其 consume 落空（ConsumeRandomTavernMinion
         空候选直接 return，真实游戏行为）。

    Test: test_batch_activate.py — 每恶魔各吞 1 随从且获得其
    atk/max_health、馆内移除+回池 / 含 Jailer 自身 / 空馆不崩 /
    金色双倍

    Params: {0}=2（activate 费用显示参数，与 activate_cost 同值;
    增益数值来源 = 受害者运行时属性）
    """

    mult = 1   # 金色 "gain double its stats" → 2（金色文本字面量）

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        demons = [m for m in hero.board
                  if not m.dead and m.race in (Race.DEMON, Race.ALL)]
        if not demons:
            return None
        return [ConsumeRandomTavernMinion(d) for d in demons]


class SoulkeepingJailerGoldenScript(SoulkeepingJailerScript):
    """
    Natural language: [x]<b>Activate ({0}):</b> Your Demons each consume
    a random minion in the Tavern to __gain double its stats.

    Formal spec:
      1. 同基础版候选（含自身，逐恶魔依次）。
      2. 双倍实现（actions/ 无乘数参数 → 复用 ConsumeMinion 组合，
         不新建 Action）: 每恶魔 rng.choice 馆内随从 → ConsumeMinion.
         do（1× buff + 移除/回池/事件全保证）→ 追加 (mult-1) 次
         Buff(demon, atk=victim.atk, health=victim.max_health)——
         总增益恰为受害者属性 ×2（受害者属性在 ConsumeMinion 内
         快照于移除前，本处引用同一实体值，等价）。
      3. 空馆恶魔 → 落空（与基础版同）。

    Test: test_batch_activate.py — 金色每恶魔获得 2× 受害者
    atk/max_health、受害者移除+回池

    Params: {0}=2（金色 activate 费用，与 activate_cost 同值）
    """

    mult = 2

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        demons = [m for m in hero.board
                  if not m.dead and m.race in (Race.DEMON, Race.ALL)]
        if not demons:
            return None
        for demon in demons:
            cands = [m for m in hero.tavern if isinstance(m, Minion)]
            if not cands:
                continue
            victim = game.rng.choice(cands,
                                     label="consume_random_tavern")
            ConsumeMinion(demon, victim).do(game)
            for _ in range(source.scripts.mult - 1):
                Buff(demon, atk=victim.atk,
                     health=victim.max_health).do(game)
        return None


# ══════════════════ BG36_506 Drone Duplicator ══════════════════


class DroneDuplicatorScript:
    """
    Natural language: [x]<b>Divine Shield</b> <b>Activate ({0}):</b> The
    next <b>Magnetization</b> to this minion this turn is doubled.

    Formal spec:
      1. activate: 在 source 上记录回合戳（脚本层契约属性
         ``source._drone_dup_turn = game.turn``，spellcraft_source_uuid
         同款模式）——同回合多次激活不叠加（引擎每回合限 1 次，
         属性覆盖写幂等）。
      2. on_summon 注册持久监听器（owner=source）: 事件 MAGNETIZED
         (host=, attached=)——engine attach_magnetic 在属性并入
         （BASE_ATK/BASE_HEALTH += attached.atk/max_health）与关键词
         并入**之后** fire。
      3. 回调条件: host **is source**（"to this minion" 只认本机）且回
         合戳 == 当前回合（"this turn" 过期）。满足 → 追加
         (mult-1) × Buff(source, atk=attached.atk,
         health=attached.max_health)，总并入 = attached 属性 ×mult;
         随即清空回合戳（"The next" 一次性——同回合后续磁力不再翻倍）。
         关键词不翻倍（无 "×2 关键词" 语义，文本 "Magnetization is
         doubled" 指属性并入部分）。
      4. 未激活时磁力 → 引擎原生 1×（负例）; 激活后跨回合磁力 →
         回合戳失配 1×。
      5. 金色版 "tripled" → mult=3。
      6. Divine Shield 由 create_minion 关键词映射（data 权威）。

    Test: test_batch_activate.py — 激活后磁力属性 ×2 / 未激活 ×1 /
    一次性（第二次磁力不再翻倍）/ 跨回合失效 / 金色 ×3

    Params: {0}=1（activate 费用显示参数，与 activate_cost 同值;
    增益数值来源 = 被磁力随从运行时属性）
    """

    mult = 2   # 基础 "doubled" → 2; 金色 "tripled" → 3（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_magnetized(g, host=None, attached=None, **kw):
            if host is not source or attached is None:
                return
            if getattr(source, "_drone_dup_turn", None) != g.turn:
                return
            source._drone_dup_turn = None   # "The next" 一次性
            for _ in range(source.scripts.mult - 1):
                g.run_actions(Buff(source, atk=attached.atk,
                                   health=attached.max_health))

        game.events.register(Listener(
            event=MAGNETIZED, owner=source, callback=on_magnetized))
        return None

    @staticmethod
    def activate(source, game, ctx):
        source._drone_dup_turn = game.turn
        return None


class DroneDuplicatorGoldenScript(DroneDuplicatorScript):
    """
    Natural language: [x]<b>Divine Shield</b> <b>Activate ({0}):</b> The
    next <b>Magnetization</b> to this minion this turn is tripled.

    Formal spec: 同基础版，mult=3——总并入 = attached 属性 ×3
    （引擎 1× + 追加 2×）。

    Test: test_batch_activate.py — 金色激活后磁力属性 ×3

    Params: {0}=1（金色 activate 费用，与 activate_cost 同值）
    """

    mult = 3


# ══════════════════ BG36_507 Breakout Mastermind ══════════════════


class BreakoutMastermindScript:
    """
    Natural language: <b>Activate ({0}):</b> Get a random Murloc.

    Formal spec:
      1. activate: GetRandomMinion(hero, race=MURLOC) times 次——池
         感知（available 闸门 + acquire 占池、Amalgam 经 ALL 匹配、
         active_races 过滤，actions/discover 保证）、满手
         pending_hand_add 排队; 池内无 Murloc 副本时单次落空。
      2. times 次独立获取（金色 "2 random Murlocs"）。

    Test: test_batch_activate.py — 激活后手牌 +times 张 Murloc 且占池 /
    金色 2 张

    Params: {0}=2（activate 费用显示参数，与 activate_cost 同值）
    """

    times = 1   # 金色 "2 random Murlocs" → 2（金色文本字面量）

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return [GetRandomMinion(hero, race=Race.MURLOC)
                for _ in range(source.scripts.times)]


class BreakoutMastermindGoldenScript(BreakoutMastermindScript):
    """
    Natural language: <b>Activate ({0}):</b> Get 2 random Murlocs.

    Formal spec: 同基础版，times=2（两个独立 GetRandomMinion）。

    Test: test_batch_activate.py — 金色一次激活获得 2 张 Murloc

    Params: {0}=2（金色 activate 费用，与 activate_cost 同值）
    """

    times = 2


# ══════════════════ BG36_511 Dead Bellringer ══════════════════


class DeadBellringerScript:
    """
    Natural language: <b>Activate ({0}):</b> Give a different friendly
    Undead <b>Reborn</b>. Then destroy it to gain +{1}/+{2}.

    目标选择裁定（作业单）: "a different friendly Undead" 无 Choose/
    [Targeted] 证据 → 随机（Mummifier BG28_309 "a different friendly
    Undead" 随机先例，batch_deathrattle 已验收）。

    Formal spec:
      1. activate: 候选 = hero.board 存活友方 Undead（race ∈
         (UNDEAD, ALL)），排除 source 自身（"different"; Bellringer
         本身是 Undead，显式排除）; 无候选 → 无效果（费用已扣）。
      2. 随机选 1（rng.choice）→ GainKeyword(target, REBORN)
         （含 keyword_gained 广播）。
      3. Then destroy: target.health = 0 + game.check_deaths()——
         完整死亡链（Disguised Graverobber batch_battlecry 先例）:
         fire death → 离场 → 亡语（若有）→ **复生**（刚获得的
         REBORN 生效: 原位 1 血回归、保留 buff/关键词——官方设计
         意图即 "给 Reborn 再杀" 的组合）→ Avenge 计数。
         招募期死亡回池被 will_reborn 分支豁免（复生不回池）。
         Destroy 无视圣盾（batch_deathrattle 裁定——非伤害路径）。
      4. gain +{1}/+{2}: Buff(source, num(1), num(2))——动作在
         destroy 之后入队（"Then ... to gain" 时序; 队列 FIFO 保证）。
      5. 金色版 num=8/8 → 同一脚本类注册两个 id，数值自然体现。

    Test: test_batch_activate.py — 目标获得 Reborn→死亡→1 血原位复生、
    Bellringer +num(1)/num(2) / 排除自身 / 无候选落空（费用已扣）/
    金色 +8/+8

    Params: {0}=1 {1}=4 {2}=4（36.2.2 基线，金色 {1}=8 {2}=8）
    """

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        cands = [m for m in hero.board
                 if m is not source and not m.dead
                 and m.race in _undead_races()]
        if not cands:
            return None
        target = game.rng.choice(cands, label="dead_bellringer_target")
        GainKeyword(target, GameTag.REBORN).do(game)
        if not target.dead and target.zone == Zone.PLAY:
            target.health = 0
            game.check_deaths()
        return Buff(source, atk=d.num(1), health=d.num(2))


# ══════════════════ 以下不注册 REGISTRY ══════════════════


class SuspiciousPrisonguardScript:
    """
    Natural language: <b>Activate ({2}):</b> Give another minion
    +{0}/+{1}.

    Status: AMBIGUOUS — 目标选择方式无文本证据，等待主线查 wiki
    （hearthstone.wiki.gg Wiki tags 段）裁决

    候选解释（主线批量查 wiki 裁决）:
      A) [Targeted]（若 wiki 卡片页 Wiki tags 含 [Targeted]）: 玩家
         定向选择——PendingChoice(kind="activate_target")，候选 =
         友方棋盘**其他**随从（Kelp Keeper BG36_701 / Sky-hatch
         Runaway BG36_243 终裁先例）
      B) 无 [Targeted]: 随机另一随从（Play Dead 先例; 目标域亦有
         友方棋盘 vs 全体馆内+棋盘 两读——wiki 佐证）
    数值索引（裁决后实现时）: 费用 = num(2) = activate_cost = 1
    （引擎经 ACTIVATE_COST tag 已保证，脚本无需处理）; buff =
    num(0)/num(1) = 3/3（金色 6/6）。**勿按惯例取 num(0)/num(1)
    之外的槽位——本卡 {0}/{1}/{2} 混排是本批特例**。

    Params: {0}=3 {1}=3 {2}=1（金色 6/6/1）
    """

    @staticmethod
    def activate(source, game, ctx):
        return None


class TyraelScript:
    """
    Natural language: <b>Activate ({0}):</b> Set another minion's stats
    to {1}/{2}.

    Status: AMBIGUOUS — 目标选择方式无文本证据，等待主线查 wiki 裁决

    候选解释（同 Suspicious Prisonguard）:
      A) [Targeted]: 玩家定向——PendingChoice(kind="activate_target")
      B) 随机另一随从
    实现备注（裁决后）: Set stats = 覆盖式写 BASE_ATK/BASE_HEALTH
    + HEALTH = max_health（Sly Raptor 先例）; {0}=num(0)=2 为费用
    显示参数（activate_cost=2），{1}/{2} = num(1)/num(2) = 50/50
    （金色 100/100）。

    Params: {0}=2 {1}=50 {2}=50（金色 {1}=100 {2}=100）
    """

    @staticmethod
    def activate(source, game, ctx):
        return None


class CageyConjurerScript:
    """
    Natural language: [x]<b>Activate ({0}):</b> Cast {1} random Tavern
    spells __<i>(targets this if possible)</i>.

    Status: DEFERRED — requires 池法术 on_play 脚本全量注册（法术批次）

    Dependency:
      1. "Cast random Tavern spells" = 效果直施（Runic Arcanist
         BG36_245 batch_soc 先例: 不经手牌/不占池/不计
         TAVERN_SPELLS_CAST/不广播）× num(1) 次，每次 rng.choice 池
         法术 card_id 并以 ctx={"target": source} 运行其 on_play。
      2. 随机候选 = db.pool_spells() 全量（作业单约定）——**过滤为
         "已注册脚本子集"会扭曲官方分布 = 近似，禁止**。
      3. 当前 REGISTRY 仅 2/75 张池法术有 on_play 脚本
         （BG28_518 / BG36_246），未注册清单（73 张，法术批次缺口）:
         BG28_168 BG28_169 BG28_500 BG28_503 BG28_504 BG28_507
         BG28_512 BG28_520 BG28_521 BG28_571 BG28_573 BG28_601
         BG28_603 BG28_604 BG28_606 BG28_607 BG28_698 BG28_800
         BG28_805 BG28_810 BG28_825 BG28_827 BG28_830 BG28_838
         BG28_845 BG28_849 BG28_882 BG28_884 BG28_886 BG28_888
         BG28_897 BG28_966 BG28_GIL_836 BG30_804 BG31_242 BG31_243
         BG31_244 BG31_819 BG31_880 BG31_881 BG31_886 BG31_889
         BG31_890 BG31_892 BG31_896 BG32_815 BG33_101 BG33_811
         BG33_812 BG33_813 BG33_814 BG33_815 BG33_817 BG33_899
         BG34_272 BG34_330 BG34_444 BG34_689 BG34_888 BG34_889
         BG34_990 BG35_149 BG35_912 BG35_922 BG35_951 BG36_624
         BG36_880 BG36_883 BG36_884 EBG_Spell_017 EBG_Spell_032
         EBG_Spell_037 EBG_Spell_038
      4. "targets this if possible" 分流: 法术脚本 needs_target=True
         时 ctx target=source 生效; 无法术目标语义（needs_target 但
         无候选）时按 play_spell 官方语义落空——依赖各法术脚本自身
         的目标处理，脚本全量就绪前不可验证。

    Params: {0}=1 {1}=2（金色 {1}=4）
    """

    @staticmethod
    def activate(source, game, ctx):
        return None


class DeftDeserterScript:
    """
    Natural language: <b>Activate ({0}):</b> Give all minions in the
    Tavern +{1}/+{2} and <b>Taunt</b>, <b>Divine Shield</b>, or
    <b>Windfury</b>.

    Status: AMBIGUOUS — 关键词三选一子句（"Taunt, Divine Shield, or
    Windfury"）的选择主体无文本证据（作业单卡面文本截断至
    "and Taunt"，data 全文含三选一），等待主线查 wiki 裁决

    候选解释（主线批量查 wiki 裁决）:
      A) 玩家三选一（若 wiki 佐证 [Targeted]/类似 Choose 交互）:
         PendingChoice(kind="activate_keyword"?) 单选一种关键词，
         授予全体馆内随从
      B) 每随从独立随机三选一（rng.choice per minion）
      C) 单次随机三选一授予全体
    无歧义部分（裁决后实现时共用）: 馆内全体 Minion 各
    Buff(num(1), num(2)) + GainKeyword(选定); {0}=num(0)=1 为费用
    显示参数（activate_cost=1），{1}/{2} = num(1)/num(2) = 8/8
    （金色 16/16）。注: Fishbait 在馆时 "This can't gain stats"
    应豁免 buff——引擎缺口（模块 docstring #1）。

    Params: {0}=1 {1}=8 {2}=8（金色 {1}=16 {2}=16）
    """

    @staticmethod
    def activate(source, game, ctx):
        return None


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG36_180", LivingPrisonScript)
    _add("BG36_180_G", LivingPrisonGoldenScript)           # double
    _add("BG36_201", LurkingLionfishScript)
    _add("BG36_201_G", LurkingLionfishScript)              # 金色链 BG36_205_G
    _add("BG36_240", HiredMountScript)
    _add("BG36_240_G", HiredMountGoldenScript)             # 2 Chromadrakes
    _add("BG36_342", CleverCastawayScript)
    _add("BG36_342_G", CleverCastawayGoldenScript)         # 2 Discovers
    _add("BG36_346", FruitVendorScript)
    _add("BG36_346_G", FruitVendorScript)                  # num(1)=4 自然体现
    _add("BG36_354", DecoyConjurerScript)
    _add("BG36_354_G", DecoyConjurerGoldenScript)          # 2 highest
    _add("BG36_503", SoulkeepingJailerScript)
    _add("BG36_503_G", SoulkeepingJailerGoldenScript)      # double stats
    _add("BG36_506", DroneDuplicatorScript)
    _add("BG36_506_G", DroneDuplicatorGoldenScript)        # tripled
    _add("BG36_507", BreakoutMastermindScript)
    _add("BG36_507_G", BreakoutMastermindGoldenScript)     # 2 Murlocs
    _add("BG36_511", DeadBellringerScript)
    _add("BG36_511_G", DeadBellringerScript)               # num=8/8 自然体现
    # 不注册（模块 docstring）: BG36_345(+_G) AMBIGUOUS /
    # BG36_356(+_G) AMBIGUOUS / BG36_508(+_G) DEFERRED /
    # BG36_621(+_G) AMBIGUOUS
    return registered
