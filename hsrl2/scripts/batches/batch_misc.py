"""批次 misc — 杂项未注册池卡 + 解冻 DEFERRED（作业单 2026-08-21）。

覆盖（按发现脚本实际未注册者实现; 含金色 id，金色=独立卡定义）:

OK 24 张主体（含法术/token id 共 34 个注册 id）:
  discover/random/summon 9: BG26_525 Imposing Percussionist / BG28_550
  Rodeo Performer / BG32_340 Maw Caster / BGS_020 Primalfin Lookout /
  BG36_343 Silent Deliverer / BGS_123 Tavern Tempest / BG33_823 Sky
  Admiral Rogers / BG34_322 Stalwart Kodo / BG26_802 Banana Slamma
  deathrattle 3: BGS_012 Kangor's Apprentice / BG34_856 Waveling /
  BG36_209 Ravaging Scorpid
  解冻 4: BG28_805 Strike Oil（INCOME_CAP_BONUS）/ BG28_849 Saloon's
  Finest（refresh spells_only）/ BGS_012（combat_death_log）/
  BG29_300 Very Hungry Winterfinner（damage 事件）
  activate 裁决 2: BG36_345 Suspicious Prisonguard（主线 wiki 裁定
  [Targeted]）/ BG36_356 Tyrael（wiki 页 Wiki tags=[Targeted]，
  2026-08-21 本批核实）
  choose_one 2: BG27_084 Sprightly Scarab / BG30_123 Fearless Foodie
  spellcraft2 5/6: BG23_004 Deep-Sea Angler / BG31_920 Darkcrest
  Strategist / BG31_924 Thaumaturgist / BG27_514 Sea Witch Zar'jira /
  BG32_835 Tranquil Meditative（各含法术 id 注册）

AMBIGUOUS 2 张（不注册）:
  BG36_621 Deft Deserter — "Taunt, Divine Shield, or Windfury" 三选一
    子句的选择主体无文本证据; wiki 卡片页不存在（404，2026-08-21
    核实 hearthstone.wiki.gg/wiki/Battlegrounds/Deft_Desperter），
    无 Wiki tags/Notes 可裁决 → 维持 AMBIGUOUS（batch_activate 同判）
  BG33_319 Rimescale Priestess — "Get a random Tavern spell that gives
    stats" 的合格法术集无权威数据源（CardDef 无 "gives stats" 标志、
    wiki 页无 Notes 列表）→ 文本正则近似 = 简化实现，禁止

DEFERRED 2 张（不注册，见各类 docstring）:
  BG36_344 Hooktusk — requires GOLDEN_MINIONS_PLAYED_THIS_GAME 引擎计数
  BG36_333 Jailbird Juggernaut — requires Force attack 引擎原语
  （BG36_508 Cagey Conjurer 仍 DEFERRED 于 batch_activate，池法术脚本
   覆盖 47/75 仍未全量，本批不重复立项）

金色战吼模型（引擎 play_minion 对 GOLDEN 触发 2 次）: battlecry 钩子
实现"每次触发的基础值"——数值经 _per_trigger_def（金色实体回基础
CardDef）; 结构差异卡（Maw Caster "Destroy 1 to Discover 2"）经
幂等分解实现（见该类 docstring）。

引擎缺口报告（主线处理）:
  1. Force attack 原语缺失（Jailbird Juggernaut "to attack the target
     first"——wiki mechanics: Force attack; Golem token BG30_MagicItem_442t
     "Blood Golem" 已在 db，引擎备好即时攻击窗口即可解冻）
  2. GOLDEN_MINIONS_PLAYED_THIS_GAME hero 计数缺失（Hooktusk "Improved
     by Golden minions you played this game"——历史打出不可回溯，
     需在 _run_play_events 计数）
  3. 池法术无 "gives stats" 资格标志（Rimescale Priestess 依赖;
     建议 generate_bg_data.py 导出或主线给出权威清单）
  4. choose_one + 定向战吼（Sprightly Scarab）引擎无组合分流——
     play_minion 的 choose_options 分支吞掉 needs_target 分支，目标
     PendingChoice 由脚本层 battlecry 自建（本批模式，报告主线评审）
  5. Evolving Strategy 的 tier 状态随来源随从（spellcraft_source_uuid
     解析）; 随从离场后法术回退基础 tier（边角: 官方无记载，已查
     wiki 三页无 Notes——见 EvolvingStrategySpellScript docstring）
"""

from __future__ import annotations

from hsrl2 import entity
from hsrl2.actions import (
    Buff,
    Discover,
    GainKeyword,
    GetRandomMinion,
)
from hsrl2.actions.bloodgem import GetBloodGems, ImproveBloodGems
from hsrl2.actions.discover import _pool_candidates
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.actions.summon import SummonPlainCopy
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

# 跨批复用（batch_activate import batch_rally2 先例）
from hsrl2.scripts.batches.batch_deathrattle import (  # noqa: F401
    _TOKEN_BEETLE,
    SummonTokenSetStats,
    _per_trigger_def,
)
from hsrl2.scripts.batches.batch_rally import BOUNTY_SPELL_IDS
from hsrl2.scripts.batches.batch_spells2 import SetStats
from hsrl2.scripts.spells import _expire_at_next_turn
from hsrl2.events import (
    AFTER_ATTACK,
    DAMAGE,
    GOLD_SPENT,
    Listener,
    SUMMON,
    TAVERN_REFRESH,
)
from hsrl2.minion import Minion

# 3 = Discover 官方三选一选项数（文本字面量）
_DISCOVER_OPTIONS = 3

_MURLOC_RACES = (Race.MURLOC, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)
_BEAST_RACES = (Race.BEAST, Race.ALL)
_MECH_RACES = (Race.MECH, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_DEMON_RACES = (Race.DEMON, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)

# Sea Witch Zar'jira 法术候选排除集（卡面 "except Sea Witch Zar'jira";
# 身份标识非数值——bloodgem.BLOOD_GEM_VARIANTS 先例）
_ZARJIRA_IDS = frozenset({"BG27_514", "BG27_514_G"})

_TAVERN_DISCOVER_KIND = "discover_spell"    # batch_activate 约定 kind
_ACTIVATE_TARGET_KIND = "activate_target"   # Kelp Keeper 终裁先例 kind


def _max_naga_tier(game) -> int:
    """池内 Naga（含 ALL）最高 tier——Evolving Strategy 升级上限
    （数据驱动。依据 2026-08-23: wiki [Upgradable] 无上限记载（卡页/
    法术页/Spellcraft 关键词页全文核对）; 池内 Naga tier 实际分布
    1..7（36.2.2 data）——每档 +1 均落在存在的档位、Tier 7 Naga 经
    本法术可达（constants "Tier 7 仅特殊效果可达" 的获取面之一），
    超出最高档无候选即无意义 → 上限 = 池内可达最高档。Patient
    Scout（batch_avenge_misc）同族 "Improves each turn" 先例同构）。"""
    return max((d.tech_level for d in game.db.pool_minions()
                if d.race in _NAGA_RACES), default=1)


# ══════════════════ BG26_525 Imposing Percussionist ══════════════════


class ImposingPercussionistScript:
    """
    Natural language: [x]<b><b>Battlecry:</b> Discover</b> a Demon. Deal
    damage to ___your hero equal to its Tier.

    Formal spec:
      1. battlecry（每次触发; 金色引擎触发 2 次 = "Discover 2 Demons"）:
         候选 = 池内 Demon（_pool_candidates: available 闸门 +
         active_races 过滤）; rng.sample 抽 3 个不同选项，不足 3 全给;
         无候选 → 该次落空。
      2. resolve(pick_id)（玩家选定）: minion_pool.acquire 占池 →
         create_minion → pending_hand_add → hero.take_damage(选中
         Demon 的 tech_level)（护甲先扣，RULES §1.3; HERO_DAMAGE_TAKEN
         广播由 Hero.take_damage 保证）。金色 "their Tiers" = 每次
         发现各自结算 → 两次触发两次伤害，模型自洽。
      3. 伤害在选定之后（"Discover ... Deal damage ... equal to its
         Tier"——its = 被发现的那个 Demon）。

    Test: test_batch_misc.py — 选定后 Demon 入手且英雄掉血=其 tier /
    池空落空 / 金色两次两次伤害 / 占池正确

    Params: {tier}=运行时（伤害值 = 选中卡 tech_level，无模板参数;
    count=3 为 Discover 官方选项数文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = _pool_candidates(game, race=Race.DEMON)
        if not cands:
            return None
        options = game.rng.sample(cands, min(_DISCOVER_OPTIONS, len(cands)),
                                  label="percussionist_demon_options")

        def resolve(pick_id: str) -> None:
            if not game.minion_pool.acquire(pick_id):
                raise GameStateError(
                    f"Imposing Percussionist: pool acquire failed "
                    f"for {pick_id}")
            m = game.create_minion(pick_id, controller=hero)
            game.pending_hand_add(hero, m)
            hero.take_damage(game.db.get(pick_id).tech_level)

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_minion", resolve_callback=resolve))
        return None


# ══════════════════ BG28_550 Rodeo Performer ══════════════════


class RodeoPerformerScript:
    """
    Natural language: <b>Battlecry:</b> <b>Discover</b> a Tavern spell.

    Formal spec:
      1. battlecry（每次触发; 金色引擎触发 2 次 = "Discover 2 Tavern
         spells"，两个独立 PendingChoice 队列化不互相覆盖）: 候选 =
         db.pool_spells() 中 spell_pool.available>0 者（池约束
         RULES §6.18; 无 tier 过滤——"a Tavern spell" 通指酒馆法术
         卡池全量，Clever Castaway batch_activate 同款约定）;
         rng.sample 抽 3 个不同选项; 无候选 → 该次落空。
      2. resolve(pick_id): spell_pool.acquire 占池（每张 1 份，
         RULES §3.6.1）→ create_spell → pending_hand_add。

    Test: test_batch_misc.py — PendingChoice(kind=discover_spell) 选定后
    法术入手且占池 / 金色两次 / 法术池耗尽落空

    Params: count=3（Discover 官方选项数，文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = [d.id for d in game.db.pool_spells()
                 if game.spell_pool.available(d.id) > 0]
        if not cands:
            return None
        options = game.rng.sample(cands, min(_DISCOVER_OPTIONS, len(cands)),
                                  label="rodeo_spell_options")

        def resolve(pick_id: str) -> None:
            if not game.spell_pool.acquire(pick_id):
                raise GameStateError(
                    f"Rodeo Performer: spell pick {pick_id} no longer "
                    f"available in pool")
            game.pending_hand_add(
                hero, game.create_spell(pick_id, controller=hero))

        game.pending_choices.append(PendingChoice(
            hero, options, _TAVERN_DISCOVER_KIND, resolve_callback=resolve))
        return None


# ══════════════════ BG32_340 Maw Caster ══════════════════


class MawCasterScript:
    """
    Natural language: <b>Battlecry:</b> Destroy a friendly Undead to
    <b>Discover</b> an Undead.

    Formal spec:
      1. 定向（"Destroy a friendly Undead"——Butchering BG28_604 先例:
         Choose 语义 → 引擎 play_minion 产生 PendingChoice(
         kind="battlecry_target")）: 候选 = 友方棋盘存活 Undead
         （含 ALL 种族; 含 source 自身——Maw Caster 是 Undead，
         官方可自毁换发现）。无候选 → 战吼落空随从照常入场（引擎
         no-candidate 路径）。
      2. 选定后按文本序: a) 摧毁——health=0 + check_deaths 完整死亡链
         （death 事件→亡语→招募期回池; Disguised Graverobber 先例;
         无视圣盾——非伤害路径）; b) Discover(hero, race=UNDEAD)——
         每次触发 1 个发现（选项 3 个三选一）。
      3. **金色幂等分解**（金色文本 "Destroy a friendly Undead to
         Discover 2 Undead" vs 引擎对金色战吼触发 2 次且共用同一
         target）: 每次触发 = "目标仍在场则摧毁 + 1 个发现"。基础版
         1 次触发 = 摧 1 发现 1; 金色 2 次触发 = 第 1 次摧毁 + 发现、
         第 2 次目标已亡跳过摧毁、仍发现 → 摧 1 发现 2 = 金色文本
         总额 ✓。Brann 叠加同理（+2 发现/份）。
      4. 防御: target 非 Minion / 已离场 / 非 Undead → 跳过摧毁仅发现
         （引擎流不会送达非法目标; 显式 target 由调用方保证）。

    Test: test_batch_misc.py — 摧毁走死亡链（GRAVEYARD+回池）后产生
    Undead 发现 / 无 Undead 候选战吼落空 / 金色 = 摧 1 发现 2 /
    目标含自身 / 自带亡语的目标亡语触发

    Params: {count}=1（每次触发发现数——"an Undead" 文本字面量;
    count=3 为 Discover 官方选项数文本字面量）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in _UNDEAD_RACES]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or not isinstance(target, Minion):
            return None
        if (target.race in _UNDEAD_RACES and not target.dead
                and target in hero.board):
            target.health = 0
            game.check_deaths()            # 完整死亡链（亡语/回池）
        return Discover(hero, race=Race.UNDEAD)


# ══════════════════ BGS_020 Primalfin Lookout ══════════════════


class PrimalfinLookoutScript:
    """
    Natural language: <b>Battlecry:</b> If you control another Murloc,
    <b>Discover</b> a_Murloc.

    Formal spec:
      1. battlecry: 条件 = 棋盘上存在**其他**友方 Murloc（race ∈
         (MURLOC, ALL)，排除 source 自身——"another Murloc"，Primalfin
         本身是 Murloc）; 不满足 → 无效果（负例）。
      2. 满足 → Discover(hero, race=MURLOC)（Action 池感知: 选项按
         池剩余量过滤 + 选中 acquire 占池, RULES §6.18/§2.3）。
      3. 数据缺口: db 无 BGS_020_G 金色定义 → 仅注册基础 id（金色
         合成/获取是引擎侧缺口，非脚本层）。

    Test: test_batch_misc.py — 有另一 Murloc 时产生 Murloc 发现且选定
    入手 / 无其他 Murloc 无发现 / Amalgam（ALL）满足条件

    Params: 无模板参数（条件运行时判定; count=3 为 Discover 官方
    选项数文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        others = [m for m in hero.board
                  if m is not source and not m.dead
                  and m.race in _MURLOC_RACES]
        if not others:
            return None
        return Discover(hero, race=Race.MURLOC)


# ══════════════════ BG36_343 Silent Deliverer ══════════════════


class SilentDelivererScript:
    """
    Natural language: [x]<b>Battlecry:</b> Get a random Golden minion
    from Tier {0}. It doesn't give a Triple Reward.

    Formal spec:
      1. battlecry（每次触发; 金色引擎触发 2 次 = "Get two random
         Golden minions"）: tier = 基础 CardDef.num(0)（金色经
         _per_trigger_def 回基础定义; 基础/金色 num(0) 均为 4）。
      2. 候选 = _pool_candidates(min_tier=tier, max_tier=tier)（池
         剩余量 + active_races 过滤）; 无候选 → 该次落空; 选中
         rng.choice 1 张。
      3. 金色获取 = Lockbox 先例（game._open_lockbox 同款）:
         acquire min(3, available) 份基础卡 → create_minion(
         golden=True) → pending_hand_add。
      4. "doesn't give a Triple Reward": create_minion(golden=True)
         不设 TRIPLE_REWARD_PENDING（该 tag 仅手牌三连合成路径设置,
         game.check_for_triple）→ 打出时不发三连奖励，语义自然成立。
      5. 池记账: 副本售出经 release_minion_entity 金色 3 份回池，
         与扣减配对守恒。

    Test: test_batch_misc.py — 手牌 +1 张金色 tier=num(0) 随从（is_golden
    且池扣 3 份）/ 无 TRIPLE_REWARD_PENDING（打出不发奖励断言由三连
    系统测试覆盖，此处断言 tag 缺席）/ 池耗尽落空 / 金色战吼 2 张

    Params: {0}=4（36.2.2 基线，金色同值; count=3/1 为金色占池份数与
    获取数文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        cands = _pool_candidates(game, min_tier=d.num(0), max_tier=d.num(0))
        if not cands:
            return None
        base_id = game.rng.choice(cands, label="silent_deliverer_golden")
        for _ in range(min(3, game.minion_pool.available(base_id))):
            if not game.minion_pool.acquire(base_id):
                raise GameStateError(
                    f"Silent Deliverer: pool acquire failed for {base_id}")
        m = game.create_minion(base_id, controller=hero, golden=True)
        game.pending_hand_add(hero, m)
        return None


# ══════════════════ BGS_123 Tavern Tempest ══════════════════


class TavernTempestScript:
    """
    Natural language: <b>Battlecry:</b> Get a random Elemental.

    Formal spec:
      1. battlecry: GetRandomMinion(hero, race=ELEMENTAL)——池感知
         （available 闸门 + acquire 占池、Amalgam 经 ALL 匹配、
         active_races 过滤，actions/discover 保证）、满手
         pending_hand_add 排队; 池内无 Elemental 副本时落空（真实
         游戏行为）。
      2. 数量 1 = 文本 "a random Elemental" 字面量。
      3. 数据缺口: db 无 BGS_123_G 金色定义 → 仅注册基础 id。

    Test: test_batch_misc.py — 手牌 +1 张 Elemental 且占池 /
    池内 Elemental 耗尽时落空

    Params: count=1（"a random" 文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GetRandomMinion(hero, race=Race.ELEMENTAL)


# ══════════════════ BG33_823 Sky Admiral Rogers ══════════════════


class SkyAdmiralRogersScript:
    """
    Natural language: [x]After you spend {2} Gold, get a random
    <b>Bounty</b>. <i>({0} Gold left!)</i>

    Formal spec:
      1. on_summon 注册持久监听器（owner=source，出售/招募期死亡注销）:
         事件 GOLD_SPENT（game.spend_gold fire，kwargs: amount=,
         hero=——购买/刷新/升级/Activate/Dark Gift 全路径）。
      2. 条件: hero is source.controller; 进度累加
         source._rogers_progress（脚本层契约属性）+= amount;
         while 进度 >= num(2)（阈值 = CardDef.num(2) = 9; num(0)=9
         为剩余显示参数，本批混排特例勿混用）: 进度 -= 阈值，发放
         1 个 random Bounty（金色子类 times=2——"two random
         Bounties" 文本字面量）。Gunpowder Courier "Whenever you
         spend 5 Gold" 家族语义 = 累积跨回合循环计数。
      3. Bounty 发放: 候选 = BOUNTY_SPELL_IDS（batch_rally 从 XML
         BACON_BOUNTY tag 核定的 5 张，漂移守护测试同源）中
         spell_pool.available>0 者（Bounty 是 is_pool_spell 池法术，
         占池 RULES §2.3）; 无可用 → 该次落空（池语义）。
         rng.choice → spell_pool.acquire → create_spell →
         pending_hand_add（满手排队 P6）。
      4. 监听器随战斗快照恢复（随从战死后复活——引擎保证）。

    Test: test_batch_misc.py — 累计花费 9 金后手牌 +1 张 Bounty 且占
    法术池 / 不足 9 金不触发 / 跨回合累积 / 单笔大额消费循环触发 /
    金色每次 2 张 / Bounty 池耗尽落空

    Params: {0}=9 {2}=9（36.2.2 基线; {0} 为显示参数、{2} 为阈值，
    同值但语义不同）; count=1（每次发放数文本字面量）
    """

    times = 1   # 金色 "two random Bounties" → 2（金色文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_gold_spent(g, amount=None, hero=None, **kw):
            if hero is not source.controller or not amount:
                return
            threshold = g.db.get(source.card_id).num(2)
            progress = getattr(source, "_rogers_progress", 0) + amount
            while progress >= threshold:
                progress -= threshold
                for _ in range(source.scripts.times):
                    cands = [b for b in BOUNTY_SPELL_IDS
                             if g.spell_pool.available(b) > 0]
                    if not cands:
                        break
                    bid = g.rng.choice(cands, label="rogers_bounty")
                    if not g.spell_pool.acquire(bid):
                        raise GameStateError(
                            f"Sky Admiral Rogers: acquire failed {bid}")
                    g.pending_hand_add(
                        hero, g.create_spell(bid, controller=hero))
            source._rogers_progress = progress

        game.events.register(Listener(
            event=GOLD_SPENT, owner=source, callback=on_gold_spent))
        return None


class SkyAdmiralRogersGoldenScript(SkyAdmiralRogersScript):
    """
    Natural language: [x]After you spend {2} Gold, get two random
    <b>Bounties</b>. <i>({0} Gold left!)</i>

    Formal spec: 同基础版，times=2——每跨一次阈值发 2 张**独立随机**
    Bounty（两次 rng.choice，可同可不同; 池内单份约束下第二张自动
    换候选）。

    Test: test_batch_misc.py — 金色跨阈值一次获得 2 张 Bounty

    Params: {0}=9 {2}=9（36.2.2 基线）; count=2（"two" 文本字面量）
    """

    times = 2


# ══════════════════ BG34_322 Stalwart Kodo ══════════════════


class StalwartKodoScript:
    """
    Natural language: [x]After you summon a minion in combat, give it
    this minion's maximum stats. <i>(3 times per combat.)</i>

    Formal spec:
      1. on_summon（招募期入场）注册两个监听器（owner=source）:
         a) SUMMON——战斗内友方召唤 buff 触发器
         b) start_of_combat——每场战斗开始重置剩余次数
      2. SUMMON 回调条件: g.in_combat（"in combat"; 招募期召唤不触发）
         且 minion.controller is source.controller（"you summon"）。
         满足且剩余次数 >0: Buff(minion, atk=source.atk × mult,
         health=source.max_health × mult)（"maximum stats" = 攻击/
         max_health 属性快照，SOP §3 纪律），剩余次数 -1。
      3. 次数: 基础 num(0)=3（"3 times per combat"——@ 后变体
         "({0} left!)" 为动态显示）; 每场战斗开始（start_of_combat
         事件, condition hero is source.controller——调度器对双方各
         fire 一次）重置为 num(0)。金色 num(0) 同 3。
      4. mult: 基础 1（"this minion's maximum stats"）; 金色 2
         （"double"，金色文本字面量）。
      5. 生命周期: Kodo 战斗中战死 → unregister_owner 即停（死后光环
         失效）; 战后监听器表快照恢复（复活续效）。buff 目标为战斗
         召唤物时随战后 board 复原丢弃，无跨战斗泄漏。

    Test: test_batch_misc.py — 战斗内召唤友方获得 Kodo 当前
    atk/max_health / 招募期召唤不触发 / 3 次后停止 / 下一场重置 /
    敌方召唤不触发 / 金色双倍

    Params: {0}=3（36.2.2 基线，每场次数）; mult=1（"maximum stats"
    ×1 文本字面量; 金色 mult=2 "double"）
    """

    mult = 1   # 金色 "double this minion's maximum stats" → 2

    @staticmethod
    def on_summon(source, game, ctx):
        source._kodo_left = game.db.get(source.card_id).num(0)

        def reset(g, hero=None, **kw):
            if hero is source.controller:
                source._kodo_left = g.db.get(source.card_id).num(0)

        def on_summoned(g, minion=None, **kw):
            if not g.in_combat or minion is None:
                return
            if minion.controller is not source.controller:
                return
            if getattr(source, "_kodo_left", 0) <= 0:
                return
            source._kodo_left -= 1
            g.run_actions(Buff(minion, atk=source.atk * source.scripts.mult,
                               health=source.max_health
                               * source.scripts.mult))

        game.events.register(Listener(
            event="start_of_combat", owner=source, callback=reset))
        game.events.register(Listener(
            event=SUMMON, owner=source, callback=on_summoned))
        return None


class StalwartKodoGoldenScript(StalwartKodoScript):
    """
    Natural language: [x]After you summon a minion in combat, give it
    double this minion's maximum stats. <i>(3 times per combat.)</i>

    Formal spec: 同基础版，mult=2——buff = 2 × (source.atk /
    source.max_health)。

    Test: test_batch_misc.py — 金色战斗内召唤获得双倍快照

    Params: {0}=3（36.2.2 基线）; mult=2（"double" 文本字面量）
    """

    mult = 2


# ══════════════════ BG26_802 Banana Slamma ══════════════════


class BananaSlammaScript:
    """
    Natural language: [x]After you summon a Beast in combat, double
    its Attack.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件 SUMMON
         （game.summon 在 on_summon 脚本钩子**之前** fire——新入场的
         Slamma 自身不会自触发; 已在场的 Slamma 对后续召唤照常触发）。
      2. 条件: g.in_combat（"in combat"）且 minion.controller is
         source.controller 且 minion.race ∈ (BEAST, ALL)（Amalgam
         是 Beast）。
      3. 触发: Buff(minion, atk=minion.atk × extra)——"double its
         Attack" = 当前攻击 ×2 → 增量 = ×1; 金色 "triple" → 增量
         ×2。快照时机 = 召唤事件当下（含召唤来源施加的初始 buff）。
      4. buff 战斗快照恢复 / 战斗召唤物战后丢弃——无跨战斗泄漏。

    Test: test_batch_misc.py — 战斗内召唤 Beast 攻击翻倍 / 招募期不
    触发 / 非 Beast 不触发 / 敌方不触发 / 金色三倍

    Params: extra=1（"double" 增量文本字面量; 金色 extra=2 "triple"）
    """

    extra = 1   # "double" → 增量 ×1; 金色 "triple" → ×2（文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_summoned(g, minion=None, **kw):
            if not g.in_combat or minion is None:
                return
            if minion.controller is not source.controller:
                return
            if minion.race not in _BEAST_RACES:
                return
            g.run_actions(Buff(minion,
                               atk=minion.atk * source.scripts.extra))

        game.events.register(Listener(
            event=SUMMON, owner=source, callback=on_summoned))
        return None


class BananaSlammaGoldenScript(BananaSlammaScript):
    """
    Natural language: [x]After you summon a Beast in combat, triple
    its Attack.

    Formal spec: 同基础版，extra=2——增量 = 2 × 当前攻击（总额三倍）。

    Test: test_batch_misc.py — 金色战斗内召唤 Beast 攻击 ×3

    Params: extra=2（"triple" 文本字面量）
    """

    extra = 2


# ══════════════════ BGS_012 Kangor's Apprentice（解冻 B3） ══════════════════


class KangorsApprenticeScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Summon plain copies of
    your first 2 Mechs that died this combat.

    Formal spec:
      1. deathrattle（直调模式——batch_deathrattle 引擎约束惯例，
         返回 None）: mechs = game.combat_death_log 中
         controller is source.controller 且 race ∈ (MECH, ALL) 的
         前两名（按死亡顺序; 复生随从再死 = 第二次死亡事件占一个
         名额——官方 "first 2 Mechs that died" 按死亡事件计，作业单
         核定）。
      2. 对每个死者: SummonPlainCopy(死者, position=ctx["position"]
         + i)——"plain copies" = 白板复制（不带死者 buff/受击状态），
         金色死者 → 金色复制（SummonPlainCopy 语义）; 位置 = 亡语
         宿主让出的板位起连续右移（batch_deathrattle token 位置惯例）。
      3. 引擎时序: combat_death_log 战斗开始清空（run_combat）、
         每次死亡处理 append（_process_single_death）; Kangor 自身
         在**自身亡语之后**才入 log（先 hook 后 append）——自身非
         Mech 无影响; 招募期死亡不 append（in_combat 闸门）。
      4. 满场由 game.summon 处理（minion_overflow 丢弃）。
      5. 数据缺口: db 无 BGS_012_G 金色定义 → 仅注册基础 id。

    Test: test_batch_misc.py — 战斗中两只友方 Mech 先死、Kangor 后死
    → 白板复制两张（属性=卡面，无死者 buff）/ 死亡顺序取前二 /
    非友方 Mech 死亡不计 / 金色死者出金色复制 / 复生二死者占两名额

    Params: count=2（"first 2 Mechs" 文本字面量）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        mechs = [m for m in game.combat_death_log
                 if m.controller is hero and m.race in _MECH_RACES][:2]
        base_pos = (ctx or {}).get("position", source.zone_position)
        for i, dead in enumerate(mechs):
            SummonPlainCopy(dead, position=base_pos + i).do(game)
        return None


# ══════════════════ BG34_856 Waveling ══════════════════


class WavelingScript:
    """
    Natural language: [x]<b>Deathrattle:</b> After the Tavern is
    <b>Refreshed</b> this game, give a random minion in it +{0}/+{1}.

    Formal spec:
      1. deathrattle（直调模式）: 登记**游戏级持久**监听器（owner=
         source.controller 的 Hero——随从 owner 会在其死亡处理时
         unregister_owner 立即注销，故不可用; Hero owner 永不注销，
         "this game" 语义）。多次 Waveling 亡语叠加多个独立监听器。
      2. 监听器: 事件 TAVERN_REFRESH（game.refresh_tavern 尾部 fire，
         kwargs: hero=）; condition hero is 亡语时闭包持有的 hero
         （只对本方刷新生效）。
      3. 回调: 候选 = hero.tavern 中 Minion（"a random minion in
         it"——馆内随从，法术不可）; 无候选 → 落空; rng.choice 选取
         → Buff(+num(0), +num(1))（36.2.2 基线 4/4）。
      4. 金色 "+{0}/+{1} twice"（金色子类 count=2）: 两次**独立**随机
         选取（可同可不同——"give a random minion ... twice" 官方
         语义按两次独立触发建模）。
      5. 亡语触发本身**不**立即 buff——效果从下一次 Refresh 起生效
         （"After the Tavern is Refreshed this game"）。

    Test: test_batch_misc.py — 亡语后下一次刷新馆内随机随从 +num(0)/
    num(1) / 亡语当次不生效 / 对手刷新不触发 / 空馆（仅法术）落空 /
    金色两次独立 / 多只 Waveling 叠加

    Params: {0}=4 {1}=4（36.2.2 基线，金色同值）; count=1（金色
    count=2 "twice" 文本字面量）
    """

    count = 1   # 金色 "twice" → 2（金色文本字面量）

    @staticmethod
    def deathrattle(source, game, ctx):
        owner_hero = source.controller
        if owner_hero is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = d.num(0), d.num(1)
        times = source.scripts.count

        def on_refresh(g, hero=None, **kw):
            if hero is not owner_hero:
                return
            cands = [m for m in owner_hero.tavern if isinstance(m, Minion)]
            for _ in range(times):
                if not cands:
                    return
                target = g.rng.choice(cands, label="waveling_tavern_minion")
                Buff(target, atk=atk, health=health).do(g)

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=owner_hero, callback=on_refresh))
        return None


class WavelingGoldenScript(WavelingScript):
    """
    Natural language: [x]<b>Deathrattle:</b> After the Tavern is
    <b>Refreshed</b> this game, give a random minion in it +{0}/+{1}
    twice.

    Formal spec: 同基础版，count=2——每次刷新两次独立随机选取各
    +num(0)/+num(1)。

    Test: test_batch_misc.py — 金色亡语后一次刷新共两笔 +4/+4

    Params: {0}=4 {1}=4（36.2.2 基线）; count=2（"twice" 文本字面量）
    """

    count = 2


# ══════════════════ BG36_209 Ravaging Scorpid ══════════════════


class RavagingScorpidScript:
    """
    Natural language: [x]After a friendly minion attacks, your Beetles
    have +{2}/+{3} this game. <b>Deathrattle:</b> Summon a {0}/{1}
    Beetle.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件 AFTER_ATTACK
         （引擎在伤害与死亡结算后广播, C4; 攻击者战死不影响——
         "attacks" 完成）。条件: attacker.controller is
         source.controller（"friendly"; 招募期攻击同样广播 → 照常
         触发，Deathstrider 先例）。
      2. 触发: ApplyRaceAura(hero, Race.BEAST, num(2), num(3))——
         "your Beetles have +X/+Y this game" 经种族光环建模
         （**Forest Rover BG31_801 batch_deathrattle 已验收同款
         先例**: Beetle token BG28_603t 种族为 BEAST; 局限——同样
         惠及其他 Beast，Beetle 专属跟踪需引擎卡 id 级光环，已报告
         主线）。board/hand/未来 Beast 全生效且当前血量同步抬升。
      3. deathrattle（直调模式）: 宿主原位召唤 beetle_count 个 Beetle
         token（BG28_603t），属性覆盖为本卡 num(0)/num(1)
         （SummonTokenSetStats batch_deathrattle 复用）; 金色
         "two" → 2 个、金色 num(2)/num(3)=10/10 光环增量经金色
         CardDef 自然体现。
      4. 光环对已召唤 Beetle 叠加于覆盖后的基础值之上（官方:
         Beetle 2/2 + 光环 = 2+5/2+5）。

    Test: test_batch_misc.py — 友方攻击后友方 Beast +num(2)/num(3) 且
    手牌 Beast 同步 / 敌方攻击不触发 / 亡语出 BG28_603t 且
    BASE==num(0)/num(1) / 金色亡语 2 个、光环 +num(2)/num(3)

    Params: {0}=2 {1}=2 {2}=5 {3}=5（36.2.2 基线，金色
            {0}=2 {1}=2 {2}=10 {3}=10）; count=1（金色 count=2
            "two" 文本字面量）
    """

    beetle_count = 1   # 金色 "two Beetles" → 2（金色文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_after_attack(g, attacker=None, defender=None, **kw):
            if attacker is None or attacker.controller is not source.controller:
                return
            d = g.db.get(source.card_id)
            g.run_actions(ApplyRaceAura(
                source.controller, Race.BEAST, d.num(2), d.num(3),
                source_id=source.card_id))

        game.events.register(Listener(
            event=AFTER_ATTACK, owner=source, callback=on_after_attack))
        return None

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        base_pos = (ctx or {}).get("position", source.zone_position)
        for i in range(source.scripts.beetle_count):
            SummonTokenSetStats(hero, _TOKEN_BEETLE, d.num(0), d.num(1),
                                position=base_pos + i).do(game)
        return None


class RavagingScorpidGoldenScript(RavagingScorpidScript):
    """
    Natural language: [x]After a friendly minion attacks, your Beetles
    have +{2}/+{3} this game. <b>Deathrattle:</b> Summon two {0}/{1}
    Beetles.

    Formal spec: 同基础版，beetle_count=2——两个 Beetle token（各按
    金色 num(0)/num(1)=2/2 覆盖属性，宿主位连续右移）; 光环增量按
    金色 CardDef num(2)/num(3)=10/10。

    Test: test_batch_misc.py — 金色亡语出 2 个 Beetle、攻击触发
    +10/+10

    Params: {0}=2 {1}=2 {2}=10 {3}=10（金色 CardDef，36.2.2 基线）;
    count=2（"two" 文本字面量）
    """

    beetle_count = 2


# ══════════════════ BG28_805 Strike Oil（解冻 B1） ══════════════════


class StrikeOilScript:
    """
    Natural language: Increase your maximum Gold by 1.

    Formal spec:
      1. on_play（play_spell 扣费后）: hero.set(INCOME_CAP_BONUS,
         现值 + 1)——hero.income_cap = GOLD_INCOME_CAP + 该 tag
         （hero.py:80），下一回合起 gold_base_income 上限抬升
         （constants.gold_base_income(turn, income_cap)）。
      2. "+1" = 文本字面量（CardDef 无模板参数）; 法术金色版 "@" 后
         文本在当前数据无独立金色定义、不可达（batch_spells2 批通用
         裁定），仅注册基础 id。
      3. 可叠加: 连续施放每张 +1。

    Test: test_batch_misc.py — 施放后 income_cap +1、下回合基础收入
    上限抬升 / 叠加两次 +2

    Params: amount=1（"+1" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hero.set(GameTag.INCOME_CAP_BONUS,
                 hero.get(GameTag.INCOME_CAP_BONUS, 0) + 1)
        return None


# ══════════════════ BG28_849 Saloon's Finest（解冻 B2） ══════════════════


class SaloonsFinestScript:
    """
    Natural language: <b>Refresh</b> the Tavern with Tavern spells.

    Formal spec:
      1. on_play: game.refresh_tavern(hero, auto=False, free=True,
         spells_only=True)——spells_only 语义: 旧内容回池 (P1) 后
         只抽法术（数量 = TAVERN_OFFERS[tier] − 冻结保留数，馆内
         展示全部为法术）; free=True（刷新费已含在法术购买价中，
         引擎 spells_only 参数即为本卡 2026-08-21 主线接线）。
      2. 冻结整馆保留、Fodder 附加、tavern_refresh 广播由引擎
         refresh_tavern 统一保证。
      3. 无模板参数; 法术金色版不可达（batch_spells2 批通用裁定）。

    Test: test_batch_misc.py — 施放后酒馆全为法术且数量=该 tier 随从
    展示数 / 原随从回池 / 不扣刷新费（金币不变）

    Params: 无模板参数（效果无数值）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        game.refresh_tavern(hero, auto=False, free=True, spells_only=True)
        return None


# ══════════════════ BG29_300 Very Hungry Winterfinner（解冻 B4） ══════════════════


class VeryHungryWinterfinnerScript:
    """
    Natural language: <b>Taunt</b> Whenever this takes damage, give a
    minion in your hand +2/+1.

    目标选择裁定（作业单: subagent 报告已核定 wiki [Random]）:
    "a minion in your hand" → 随机（文本无 Choose，wiki 无
    [Targeted]——SOP §9 目标语义裁决库）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件 DAMAGE
         （引擎全覆盖: 攻击主/反击/顺劈/招募期攻击/Hit Action 均
         fire (minion=, amount=, source=)）; condition: minion is
         source（"this takes damage"——圣盾抵消时 amount=0 不触发，
         amount>0 才算受伤，官方 C7 语义）。
      2. 回调: 候选 = hero.hand 中 Minion 实体（"a minion in your
         hand"——法术/宝石不可）; 无候选 → 落空; rng.choice 随机
         1 个 → Buff(+buff_atk, +buff_hp)。
      3. 数值: CardDef 无模板参数 → 文本字面量（基础 +2/+1、金色
        +4/+2，金色子类覆写）。Taunt 由 create_minion 关键词映射
        （data 权威）。
      4. 战斗中受伤同样触发（手牌 buff 跨战斗保留——RULES §3.5
         快照只回滚棋盘实体）。

    Test: test_batch_misc.py — 受伤后手牌随机 Minion +2/+1（多张手牌
    恰一张命中）/ 无受伤不触发 / 手牌无法术不触发（空手落空）/
    圣盾抵消不触发 / 金色 +4/+2

    Params: atk=2 health=1（文本字面量——CardDef 无模板参数;
    金色 atk=4 health=2）
    """

    buff_atk = 2    # 文本字面量 "+2/+1"（金色 "+4/+2"）
    buff_hp = 1

    @staticmethod
    def on_summon(source, game, ctx):
        def on_damage(g, minion=None, amount=None, **kw):
            if minion is not source or not amount:
                return
            hero = source.controller
            if hero is None:
                return
            cands = [c for c in hero.hand if isinstance(c, Minion)]
            if not cands:
                return
            target = g.rng.choice(cands, label="winterfinner_hand_minion")
            g.run_actions(Buff(target, atk=source.scripts.buff_atk,
                               health=source.scripts.buff_hp))

        game.events.register(Listener(
            event=DAMAGE, owner=source,
            condition=lambda minion=None, **kw: minion is source,
            callback=on_damage))
        return None


class VeryHungryWinterfinnerGoldenScript(VeryHungryWinterfinnerScript):
    """
    Natural language: <b>Taunt</b> Whenever this takes damage, give a
    minion in your hand +4/+2.

    Formal spec: 同基础版，buff_atk=4 / buff_hp=2（金色文本字面量，
    金色 CardDef 无模板参数）。

    Test: test_batch_misc.py — 金色受伤手牌随从 +4/+2

    Params: atk=4 health=2（金色文本字面量）
    """

    buff_atk = 4
    buff_hp = 2


# ══════════════════ BG36_345 Suspicious Prisonguard（activate 裁决） ══════════════════


class SuspiciousPrisonguardScript:
    """
    Natural language: <b>Activate ({2}):</b> Give another minion
    +{0}/+{1}.

    目标选择裁定（主线 2026-08-21 wiki 裁定: [Targeted]）: 玩家定向
    ——PendingChoice(kind="activate_target")，Kelp Keeper BG36_701 终裁
    先例; 候选 = 友方棋盘**其他**随从（"another"——排除自身）。

    Formal spec:
      1. activate（引擎已扣 num(2)=activate_cost=1 金并置
         ACTIVATE_USED_THIS_TURN）: 候选 = hero.board 存活随从排除
         source; 空 → 无效果返回 None（费用已扣——官方无合法目标时
         activate 仍可按但无效果，批次 1b 裁定）。
      2. PendingChoice(activate_target) → resolve(pick):
         Buff(pick, num(0), num(1))。
      3. **数值索引陷阱（batch_activate docstring 核定）**: buff =
         num(0)/num(1) = 3/3（金色 6/6）; 费用 = num(2) = 1（引擎经
         ACTIVATE_COST 保证，脚本不处理）——本卡 {0}/{1}/{2} 混排。
      4. 金色注册同一脚本类，金色 CardDef num 自然体现 6/6。

    Test: test_batch_misc.py — 激活产生 activate_target 选择、选定后
    +num(0)/num(1) 且扣费 / 候选排除自身 / 无候选落空不崩 / 金色 6/6

    Params: {0}=3 {1}=3 {2}=1（36.2.2 基线，金色 {0}=6 {1}=6 {2}=1）
    """

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        candidates = [m for m in hero.board
                      if m is not source and not m.dead]
        if not candidates:
            return None
        d = game.db.get(source.card_id)

        def resolve(pick):
            game.run_actions(Buff(pick, atk=d.num(0), health=d.num(1)))

        game.pending_choices.append(PendingChoice(
            hero, candidates, _ACTIVATE_TARGET_KIND,
            resolve_callback=resolve))
        return None


# ══════════════════ BG36_356 Tyrael（activate 裁决） ══════════════════


class TyraelScript:
    """
    Natural language: <b>Activate ({0}):</b> Set another minion's stats
    to {1}/{2}.

    目标选择裁定（本批 2026-08-21 核实 hearthstone.wiki.gg/wiki/
    Battlegrounds/Tyrael "Wiki tags" 段 = **[Targeted]**）: 玩家定向
    ——PendingChoice(kind="activate_target")，Kelp Keeper 终裁先例;
    候选 = 友方棋盘**其他**随从（"another"——排除自身）。

    Formal spec:
      1. activate（引擎已扣 num(0)=activate_cost=2 金）: 候选 =
         hero.board 存活随从排除 source; 空 → 无效果（费用已扣）。
      2. resolve(pick): SetStats(pick, num(1), num(2))——覆盖式设
         属性（附魔全清、BASE_ATK/BASE_HEALTH=X/Y、HEALTH 同步，
         batch_spells2.SetStats 复用; Sly Raptor/Perfect Vision
         "set stats" 同语义）。
      3. 数值: num(1)/num(2) = 50/50（金色 100/100——金色 CardDef
         自然体现，XML TAG_SCRIPT_DATA_NUM_2/3=100/100 权威）。

    Test: test_batch_misc.py — 激活选定后目标恰为 num(1)/num(2) 且
    附魔清除 / 排除自身 / 无候选落空 / 金色 100/100

    Params: {0}=2 {1}=50 {2}=50（36.2.2 基线，金色 {1}=100 {2}=100）
    """

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        candidates = [m for m in hero.board
                      if m is not source and not m.dead]
        if not candidates:
            return None
        d = game.db.get(source.card_id)

        def resolve(pick):
            game.run_actions(SetStats(pick, d.num(1), d.num(2)))

        game.pending_choices.append(PendingChoice(
            hero, candidates, _ACTIVATE_TARGET_KIND,
            resolve_callback=resolve))
        return None


# ══════════════════ BG27_084 Sprightly Scarab（choose_one） ══════════════════


class SprightlyScarabScript:
    """
    Natural language: [x]<b>Choose One -</b> Give a Beast +{0}/+{1} and
    <b>Reborn</b>; or +{2} Attack and <b>Windfury</b>.

    Formal spec:
      1. choose_options = [("reborn", ...), ("windfury", ...)]——引擎
         play_minion 产生 PendingChoice(kind="choose_one")，选定 key
         经 ctx["choose"] 触发 battlecry。金色引擎触发 2 次 → 同一
         key 应用 2 次、每次按基础 CardDef（_per_trigger_def）→
         总额 = 金色文本（2/2/8）。
      2. 目标: "Give a Beast"（两分支同一目标域）——引擎 choose_options
         分支不产生目标 PendingChoice（缺口 #4）→ 脚本层自建: ctx 无
         target 时 append PendingChoice(kind="battlecry_target",
         候选=友方存活 Beast 含 ALL、含 source 自身——文本无
         "another"/"other"); resolve → apply(key, pick)。显式 target
         传入时直接 apply。
      3. apply(key, target): "reborn" → [Buff(num(0), num(1)),
         GainKeyword(REBORN)]; "windfury" → [Buff(atk=num(2)),
         GainKeyword(WINDFURY)]。金色触发 2 次时两次目标选择各自
         独立（官方金色定向战妁双选）。
      4. 无 Beast 候选 → 战吼落空。

    Test: test_batch_misc.py — 选 reborn 分支目标 Beast +num(0)/num(1)
    且 Reborn / 选 windfury 分支 +num(2) 攻且 Windfury / 目标候选仅
    Beast / 金色两次应用总额=金色 num / 无 Beast 落空

    Params: {0}=1 {1}=1 {2}=4（36.2.2 基线，金色 {0}=2 {1}=2 {2}=8;
    每次触发值=基础 CardDef）
    """

    choose_options = [
        ("reborn", "Give a Beast +{0}/+{1} and Reborn"),
        ("windfury", "Give a Beast +{2} Attack and Windfury"),
    ]

    @staticmethod
    def _apply(source, game, key, target):
        d = _per_trigger_def(game, source)
        if key == "reborn":
            return [Buff(target, atk=d.num(0), health=d.num(1)),
                    GainKeyword(target, GameTag.REBORN)]
        if key == "windfury":
            return [Buff(target, atk=d.num(2)),
                    GainKeyword(target, GameTag.WINDFURY)]
        return None

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        c = ctx or {}
        key = c.get("choose")
        if hero is None or key is None:
            return None
        target = c.get("target")
        if target is not None:
            return SprightlyScarabScript._apply(source, game, key, target)
        candidates = [m for m in hero.board
                      if not m.dead and m.race in _BEAST_RACES]
        if not candidates:
            return None

        def resolve(pick):
            game.run_actions(
                SprightlyScarabScript._apply(source, game, key, pick))

        game.pending_choices.append(PendingChoice(
            hero, candidates, "battlecry_target",
            resolve_callback=resolve))
        return None


# ══════════════════ BG30_123 Fearless Foodie（choose_one） ══════════════════


class FearlessFoodieScript:
    """
    Natural language: <b>Choose One - </b>Your <b>Blood Gems</b> give
    an extra +{0}/+{1} this game; or Get {2} <b>Blood Gems</b>.

    Formal spec:
      1. choose_options = [("improve", ...), ("gems", ...)]; 选定 key
         经 ctx["choose"] 触发 battlecry（非定向——无目标子句）。
      2. "improve" → ImproveBloodGems(hero, num(0), num(1))——hero 的
         BLOOD_GEM_BONUS_ATK/HEALTH 递增（对手牌打出与 PlayBloodGems
         直施的宝石统一生效，actions/bloodgem 契约）。
      3. "gems" → GetBloodGems(hero, num(2))——进手牌（满手排队）。
      4. 每次触发值 = 基础 CardDef（_per_trigger_def）; 金色引擎触发
         2 次 → improve 总额 2×(1/1)=2/2 = 金色 num、gems 总额
         2×4=8 = 金色 num(2) ✓。

    Test: test_batch_misc.py — improve 分支 BLOOD_GEM_BONUS_ATK/HEALTH
    +num(0)/num(1) / gems 分支手牌 +num(2) 张 BG20_GEM / 金色总额
    =金色 num / 后续宝石实际增益抬升

    Params: {0}=1 {1}=1 {2}=4（36.2.2 基线，金色 {0}=2 {1}=2 {2}=8;
    每次触发值=基础 CardDef）
    """

    choose_options = [
        ("improve", "Your Blood Gems give an extra +{0}/+{1} this game"),
        ("gems", "Get {2} Blood Gems"),
    ]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return None
        d = _per_trigger_def(game, source)
        if key == "improve":
            return ImproveBloodGems(hero, atk=d.num(0), health=d.num(1))
        if key == "gems":
            return GetBloodGems(hero, d.num(2))
        return None


# ══════════════════ spellcraft2 — 法术塑造随从（5/6） ══════════════════


class _SpellcraftMinionBase:
    """Spellcraft 随从公共 on_summon（scripts/minions.py
    _SpellcraftMinionMixin 同构——本批文件不可改 minions.py）:
    SPELLCRAFT tag 自举 + 打出/召唤立即获得第一张法术。"""

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.SPELLCRAFT, True)
        grant_spellcraft_spell(source, game)
        return None


class DeepSeaAnglerScript(_SpellcraftMinionBase):
    """
    Natural language: [x]<b>Spellcraft:</b> Give a minion +{0}/+{1} and
    <b>Taunt</b> until next turn.

    Formal spec:
      1. on_summon: tag 自举 + 立即获得法术 BG23_004t（金色随从
         BG23_004_G → 金色法术 BG23_004_Gt，spellcraft_id 数据链）;
         后续每招募阶段 generate_for_hero 再给。
      2. 法术效果本体见 AnglersLureSpellScript（法术 id 注册）。

    Test: test_batch_misc.py — 入场立即获得法术 / 金色随从给金色法术

    Params: 法术侧 {0}=2 {1}=6（金色 {0}=4 {1}=12，法术脚本声明）
    """


class AnglersLureSpellScript:
    """
    Natural language: Give a minion +{0}/+{1} and <b>Taunt</b> until
    next turn.（金色 BG23_004_Gt: +{0}/+{1} and Taunt until next turn）

    Formal spec:
      1. needs_target=True → 引擎 play_spell 产生 PendingChoice(
         kind="spell_target")，候选默认全体友方存活随从; 显式 target
         直接生效。target=None（无候选落空路径）→ 效果落空（法术
         照常消耗，WaveriderSpellScript 先例）。
      2. on_play: temporary Buff(+num(0)/+num(1)) + Taunt（施加前已
         持有则记录，防误删自带永久嘲讽）——两者同一过期时点:
         目标控制者下一招募阶段开始（_expire_at_next_turn，
         scripts/spells.py 复用）。
      3. 金色法术（BG23_004_Gt，金色随从生成）num=4/12 同类自然体现。

    Test: test_batch_misc.py — 目标 +num(0)/num(1) 且 Taunt / 下一回合
    开始 buff 回落 + Taunt 移除 / 自带嘲讽目标过期后保留 / 金色
    +4/+12

    Params: {0}=2 {1}=6（BG23_004t）; 金色 {0}=4 {1}=12（BG23_004_Gt）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        d = game.db.get(source.card_id)
        buff = entity.Buff(atk=d.num(0), health=d.num(1),
                           temporary=True, source_id=source.card_id)
        target.add_buff(buff)
        keywords = {GameTag.TAUNT: target.has(GameTag.TAUNT)}
        game.run_actions(GainKeyword(target, GameTag.TAUNT))
        _expire_at_next_turn(game, source, target,
                             buffs=[buff], keywords=keywords)
        return None


class DarkcrestStrategistScript(_SpellcraftMinionBase):
    """
    Natural language: <b>Spellcraft:</b> Get a random Tier @ Naga.
    <i>(Improves each turn!)</i>

    Formal spec:
      1. on_summon: tag 自举 + 立即获得法术 BG31_920t（金色 →
         BG31_920_Gt "Get two random"）+ 初始化升级档
         source._strategist_tier = num(0) = 1（wiki 满标签
         TAG_SCRIPT_DATA_NUM_1=1、END_OF_TURN_TRIGGER=1 权威）。
      2. end_of_turn（引擎对棋盘随从逐个触发）: tier = min(tier + 1,
          池内 Naga 最高 tier)（"Improves each turn"; 上限依据见
          _max_naga_tier docstring——数据驱动池内可达最高档 7）。
      3. 法术效果本体见 EvolvingStrategySpellScript（tier 经
         spellcraft_source_uuid 回读本随从）。

    Test: test_batch_misc.py — 入场获得法术 / 回合结束 tier+1（封顶）
    / 售出后不再升级

    Params: {0}=1（起始 tier，36.2.2 基线，基础/金色同值）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        _SpellcraftMinionBase.on_summon(source, game, ctx)
        source._strategist_tier = game.db.get(source.card_id).num(0)
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        cap = _max_naga_tier(game)
        source._strategist_tier = min(
            getattr(source, "_strategist_tier", 1) + 1, cap)
        return None


class EvolvingStrategySpellScript:
    """
    Natural language: Get a random Tier @ Naga.（金色 BG31_920_Gt:
    Get two random Tier @ Naga.）

    Formal spec:
      1. on_play: tier = 来源随从当前升级档——经 spell.spellcraft_
         source_uuid 在 hero.board 解析来源 Darkcrest Strategist
         （spellcraft.py 生成协议）; 随从已离场（边角）→ 回退本法术
         CardDef.num(0) = 1（来源离场后的法术读数官方无记载——
         2026-08-23 查证: 卡页/法术页/Spellcraft 关键词页均无 Notes;
         回基础档为保守读法，边角上报主线: 需生成时点 tier 快照
         原语（引擎 grant 钩子）方可实现"冻结末档"备选）。
      2. GetRandomMinion(hero, race=NAGA, min_tier=tier, max_tier=tier)
         × times——池感知（available 闸门 + acquire 占池 + active_
         races 过滤）、满手排队; 池内无该档 Naga 副本 → 该次落空。
      3. 金色法术 BG31_920_Gt（金色随从生成）"two" → times=2
         （金色文本字面量），两次独立随机。

    Test: test_batch_misc.py — tier=1 时获得 tier-1 Naga / 随从升级后
    tier 跟随 / 金色两次 / 池耗尽落空

    Params: {0}=1（回退基础档）; times=1（金色 times=2 "two" 文本
    字面量）
    """

    times = 1   # 金色 "Get two random" → 2（金色文本字面量）

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        tier = d.num(0)
        origin_uuid = getattr(source, "spellcraft_source_uuid", None)
        if origin_uuid is not None:
            for m in hero.board:
                if m.uuid == origin_uuid:
                    tier = getattr(m, "_strategist_tier", d.num(0))
                    break
        return [GetRandomMinion(hero, race=Race.NAGA,
                                min_tier=tier, max_tier=tier)
                for _ in range(source.scripts.times)]


class EvolvingStrategyGoldenSpellScript(EvolvingStrategySpellScript):
    """
    Natural language: Get two random Tier @ Naga.

    Formal spec: 同基础版，times=2——两次独立随机获取。

    Test: test_batch_misc.py — 金色法术获得 2 张同档 Naga

    Params: {0}=1（回退基础档）; times=2（"two" 文本字面量）
    """

    times = 2


class ThaumaturgistScript(_SpellcraftMinionBase):
    """
    Natural language: [x]<b>Spellcraft:</b> Give a minion +{1}/+{1}
    until next turn. <i>(Improved by every 3 spells you've cast this
    game!)</i>

    Formal spec:
      1. on_summon: tag 自举 + 立即获得法术 BG31_924t（金色 →
         BG31_924_Gt）。
      2. 法术效果本体见 ThaumaturgySpellScript。

    Test: test_batch_misc.py — 入场获得法术 / 金色随从给金色法术

    Params: 法术侧 {0}=3 {1}=1（金色 {0}=3 {1}=2，法术脚本声明）
    """


class ThaumaturgySpellScript:
    """
    Natural language: [x]Give a minion +{1}/+{1} until next turn.
    <i>(Improved by every 3 spells you've cast this game!)</i>
    （金色 BG31_924_Gt 同文，基础值 +{1}=2）

    Formal spec:
      1. needs_target=True → 引擎 PendingChoice(kind="spell_target")
         / 显式 target; target=None → 落空。
      2. on_play: mult = 1 + hero.TAVERN_SPELLS_CAST_THIS_GAME //
         num(0)（"every 3 spells" 整除递进: 0-2 次 ×1、3-5 次 ×2 …;
         计数器=酒馆法术计数，作业单裁定——Showy Cyclist
         batch_deathrattle 已验收先例; Spellcraft 法术与血宝石不计
         入，引擎 tag 口径）; buff 值 = num(1) × mult（基础 1、金色 2
         ——金色法术 CardDef 自然体现）。
      3. temporary buff + 目标控制者下一招募阶段开始过期
         （_expire_at_next_turn 复用）。

    Test: test_batch_misc.py — 0 施法 +num(1)/num(1) / 3 施法 ×2 /
    7 施法 ×3 / 下一回合回落 / 金色基础 2×mult

    Params: {0}=3 {1}=1（BG31_924t）; 金色 {0}=3 {1}=2（BG31_924_Gt）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        casts = hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        mult = 1 + casts // d.num(0)
        val = d.num(1) * mult
        buff = entity.Buff(atk=val, health=val, temporary=True,
                           source_id=source.card_id)
        target.add_buff(buff)
        _expire_at_next_turn(game, source, target, buffs=[buff])
        return None


class SeaWitchZarjiraScript(_SpellcraftMinionBase):
    """
    Natural language: [x]<b>Spellcraft:</b> Choose a different minion
    in the  Tavern to get a copy of.

    Formal spec:
      1. on_summon: tag 自举 + 立即获得法术 BG27_514t（金色 →
         BG27_514t_G "get 2 copies"）。
      2. 法术效果本体见 SirensSongSpellScript。

    Test: test_batch_misc.py — 入场获得法术 / 金色随从给金色法术

    Params: 法术侧无数值参数（复制语义）
    """


class SirensSongSpellScript:
    """
    Natural language: Choose a minion in the Tavern to get a copy of
    <i>(except Sea Witch Zar'jira).</i>（金色 BG27_514t_G: ... get 2
    copies of ...）

    Formal spec:
      1. needs_target=True + target_candidates（引擎 play_spell 分流
         PendingChoice(kind="spell_target")）: 候选 = hero.tavern 中
         Minion，排除 Sea Witch Zar'jira（card_id ∈ _ZARJIRA_IDS——
         卡面 "except Sea Witch Zar'jira"; 馆内实体为基础 id，含
         金色 id 防御）; 无候选 → 法术落空但照常消耗。
      2. on_play: 复制 times 份进手牌——create_minion(同 card_id,
         golden=目标是否金色) + 逐 buff 复制（entity.Buff 公共构造
         ——atk/health/temporary/source_id 全保真，"get a copy of"
         官方复制语义含附魔）; HEALTH = max_health 满血初始化;
         pending_hand_add 满手排队。
      3. 池记账: 生成复制不占池（game._plain_copy_to_hand Dark Gift
         Double Vision 主线先例——复制自有实体不消耗池副本）。
      4. 金色法术 times=2（"2 copies" 文本字面量）。

    Test: test_batch_misc.py — 选定馆内随从获得其副本（含 buff 保真、
    满血）/ 候选排除 Zar'jira / 无候选（空馆）落空 / 金色 2 份 /
    不占池

    Params: times=1（金色 times=2 "2 copies" 文本字面量）
    """

    needs_target = True
    times = 1   # 金色 "2 copies" → 2（金色子类覆写，文本字面量）

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.tavern
                if isinstance(m, Minion) and m.card_id not in _ZARJIRA_IDS]

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or not isinstance(target, Minion):
            return None
        if target not in hero.tavern:
            return None
        for _ in range(source.scripts.times):
            copy = game.create_minion(
                target.card_id, controller=hero,
                golden=target.is_golden)
            for b in target.buffs:
                copy.add_buff(entity.Buff(
                    atk=b.atk, health=b.health, temporary=b.temporary,
                    source_id=b.source_id))
            game.pending_hand_add(hero, copy)
        return None


class SirensSongGoldenSpellScript(SirensSongSpellScript):
    """
    Natural language: [x]Choose a minion in the Tavern to get 2 copies
    of <i>(except Sea Witch Zar'jira).</i>

    Formal spec: 同基础版，times=2——两份独立副本。

    Test: test_batch_misc.py — 金色法术获得 2 份副本

    Params: times=2（"2 copies" 文本字面量）
    """

    times = 2


class TranquilMeditativeScript(_SpellcraftMinionBase):
    """
    Natural language: [x]<b>Spellcraft:</b> Your Tavern spells give an
    extra +{0}/+{1} this game.

    Formal spec:
      1. on_summon: tag 自举 + 立即获得法术 BG32_835t（金色 →
         BG32_835_Gt）。
      2. 法术效果本体见 MeditationSpellScript。

    Test: test_batch_misc.py — 入场获得法术 / 金色随从给金色法术

    Params: 法术侧 {0}=1 {1}=1（金色 {0}=2 {1}=2，法术脚本声明）
    """


class MeditationSpellScript:
    """
    Natural language: Your Tavern spells give an extra +{0}/+{1} this
    game.（金色 BG32_835_Gt: ... an extra +{0}/+{1} ... {0}/{1}=2/2）

    Formal spec:
      1. on_play: hero.TAVERN_SPELL_EXTRA_ATK += num(0)、
         TAVERN_SPELL_EXTRA_HEALTH += num(1)（tags 1053/1054——
         "Your Tavern spells give an extra" 家族唯一权威出口，经
         actions/racefx.tavern_spell_buff 对全部经该出口的酒馆法术
         buff 生效; batch_battlecry Sandstone 定音锤同构先例）。
      2. 非定向、可叠加; 金色法术 num=2/2 自然体现。

    Test: test_batch_misc.py — 施放后 tag 递增 num(0)/num(1) / 经
    tavern_spell_buff 的法术增益抬升 / 金色 2/2

    Params: {0}=1 {1}=1（BG32_835t）; 金色 {0}=2 {1}=2（BG32_835_Gt）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + d.num(0))
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + d.num(1))
        return None


# ══════════════════ 以下不注册 REGISTRY ══════════════════


class HooktuskScript:
    """
    Natural language: [x]After you <b>Discover</b> a card, give your
    other Pirates +{0}/+{1}. <i>(Improved by Golden minions ___you
    played this game!)</i>

    Status: DEFERRED — requires GOLDEN_MINIONS_PLAYED_THIS_GAME 引擎计数

    Dependency:
      1. 触发器本体（AFTER Discover——引擎缺 discover 完成事件，可用
         PendingChoice resolve 后广播近似? 无权威事件 = 近似，禁止）
         与增值项 "Improved by Golden minions you played this game"
         均需引擎支持: hero 级 GOLDEN_MINIONS_PLAYED_THIS_GAME 计数
         （在 _run_play_effects 对 is_golden Minion 递增，类比
         COUNTER_BATTLECRIES）。
      2. 监听器注册于 on_summon 只能覆盖**入场后**的打出——历史金色
         打出不可回溯（无引擎计数时实现必然漏计 = 简化，禁止）。

    Params: {0}=1 {1}=1（36.2.2 基线，金色 {0}=2 {1}=2）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        return None


class JailbirdJuggernautScript:
    """
    Natural language: [x]<b>Rally:</b> Summon a Golem with stats equal
    to this minion's <b>Blood Gems</b> to attack the target first.
    <i>({0}/{1})</i>

    Status: DEFERRED — requires Force attack 引擎原语

    Dependency:
      1. wiki 卡片页（Battlegrounds/Jailbird_Juggernaut）Wiki mechanics
         明示 **Force attack** + Summon: Golem 召唤后须**立即攻击**
         rally 目标（先于本次攻击者的伤害结算）。引擎无即时攻击
         窗口（CombatScheduler._execute_attack 中途插入一次完整
         攻击: 双向同时伤害/死亡/事件序），脚本层复制战斗语义
         = 越权近似，禁止。
      2. 已备组件（解冻后可直接用）: Golem token = BG30_MagicItem_442t
         "Blood Golem"（db 已有定义）; stats = GEMS_PLAYED_ON × 单颗
         宝石值（BG20_GEM.num(0/1) + BLOOD_GEM_BONUS_*——与卡面动态
         显示 ({0}/{1}) 一致）; 金色 "double" ×2。

    Params: {0}/{1} 为动态显示参数（CardDef num=None，运行时计算）
    """

    @staticmethod
    def rally(source, game, ctx):
        return None


class DeftDeserterScript:
    """
    Natural language: <b>Activate ({0}):</b> Give all minions in the
    Tavern +{1}/+{2} and <b>Taunt</b>, <b>Divine Shield</b>, or
    <b>Windfury</b>.

    Status: AMBIGUOUS — 三选一关键词子句的选择主体无文本证据
    （batch_activate 同判）; wiki 卡片页不存在
    （hearthstone.wiki.gg/wiki/Battlegrounds/Deft_Desperter → 404，
    2026-08-21 两次核实），无 Wiki tags/Notes 可裁决

    候选解释（主线补 wiki 页后裁决）:
      A) 玩家三选一（[Targeted]/Choose 佐证）: PendingChoice 单选
         一种关键词授予全体馆内随从
      B) 每随从独立随机三选一
      C) 单次随机三选一授予全体
    无歧义部分: 馆内全体 Minion 各 Buff(num(1), num(2)) + 选定
    关键词; {0}=num(0)=1 为费用（activate_cost=1 引擎保证）。

    Params: {0}=1 {1}=8 {2}=8（36.2.2 基线，金色 {1}=16 {2}=16）
    """

    @staticmethod
    def activate(source, game, ctx):
        return None


class RimescalePriestessScript:
    """
    Natural language: <b>Spellcraft:</b> Get a random Tavern spell
    that gives stats.（金色: Get 2 random ...）

    Status: AMBIGUOUS — "that gives stats" 的合格法术集无权威数据源

    Dependency:
      1. CardDef 无 "gives stats" 标志（subsets 仅种族）; wiki 卡片页
         无 Notes 合格清单。文本正则（如含 "Give"+"+"）对边界卡
         （Perfect Vision "Set stats" / Mounting Avalanche 转移属性 /
         Blood Gem Barrage 经宝石给属性 / Boon of Beetles 召唤）分类
         无权威依据 → 近似，禁止。
      2. 建议: generate_bg_data.py 从 XML 导出资格 tag，或主线给出
         官方清单后解冻。

    Params: 无模板参数（金色 "2" 文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        return None


class DeftDeserterScript:
    """
    Natural language: <b>Activate ({0}):</b> Give all minions in the Tavern
    +{1}/+{2} and <b>Taunt</b>, <b>Divine Shield</b>, or <b>Windfury</b>.

    目标语义裁定（主线终裁 2026-08-22）: hearthstone.wiki.gg Wiki tags
    含 **[Random]**（Random-granting 家族）→ 三关键词对每个酒馆随从
    **独立随机**分配其一（非全体同一、非玩家选择）。

    Formal spec:
      1. activate 钩子（引擎已扣 num(0) 费用并管每回合 1 次）
      2. 对 hero.tavern 中每个存活 Minion:
         a. Buff(+num(1)/+num(2))——注意索引: 费用=num(0)，buff=num(1)/num(2)
            （full tags: NUM_1=1 NUM_2=8 NUM_3=8）
      3. 同批随从独立 rng.choice([TAUNT, DIVINE_SHIELD, WINDFURY]) 各
         GainKeyword 其一

    Test: test_batch_activate.py::TestDeftDeserter — buff 数值/三关键词
    恰一/金色 16/16

    Params: {0}=1（费用）{1}=8 {2}=8（金色 16/16）
    """

    @staticmethod
    def activate(source, game, ctx):
        from hsrl2.actions.stats import Buff, GainKeyword
        from hsrl2.tags import GameTag
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        keywords = (GameTag.TAUNT, GameTag.DIVINE_SHIELD, GameTag.WINDFURY)
        actions = []
        for m in hero.tavern:
            if m.dead or m.get(GameTag.CARDTYPE) != 4:
                continue
            actions.append(Buff(m, atk=d.num(1), health=d.num(2)))
            actions.append(GainKeyword(m, game.rng.choice(
                keywords, label="deft_deserter_kw")))
        return actions


def register() -> list[str]:
    """注册本批次全部脚本（含金色/法术 id），返回 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    # discover / random / summon
    _add("BG26_525", ImposingPercussionistScript)
    _add("BG26_525_G", ImposingPercussionistScript)      # 引擎 2×触发
    _add("BG28_550", RodeoPerformerScript)
    _add("BG28_550_G", RodeoPerformerScript)             # 2 Discovers
    _add("BG32_340", MawCasterScript)
    _add("BG32_340_G", MawCasterScript)                  # 幂等分解 1/2
    _add("BGS_020", PrimalfinLookoutScript)              # 无金色定义
    _add("BG36_343", SilentDelivererScript)
    _add("BG36_343_G", SilentDelivererScript)            # 2 金色获取
    _add("BGS_123", TavernTempestScript)                 # 无金色定义
    _add("BG33_823", SkyAdmiralRogersScript)
    _add("BG33_823_G", SkyAdmiralRogersGoldenScript)     # 2 Bounties
    _add("BG34_322", StalwartKodoScript)
    _add("BG34_322_G", StalwartKodoGoldenScript)         # double
    _add("BG26_802", BananaSlammaScript)
    _add("BG26_802_G", BananaSlammaGoldenScript)         # triple
    # deathrattle
    _add("BGS_012", KangorsApprenticeScript)             # 无金色定义
    _add("BG34_856", WavelingScript)
    _add("BG34_856_G", WavelingGoldenScript)             # twice
    _add("BG36_209", RavagingScorpidScript)
    _add("BG36_209_G", RavagingScorpidGoldenScript)      # 2 Beetles/10-10
    # 解冻
    _add("BG28_805", StrikeOilScript)                    # 法术无金色定义
    _add("BG28_849", SaloonsFinestScript)                # 同上
    _add("BG29_300", VeryHungryWinterfinnerScript)
    _add("BG29_300_G", VeryHungryWinterfinnerGoldenScript)   # +4/+2
    # activate 裁决
    _add("BG36_345", SuspiciousPrisonguardScript)
    _add("BG36_345_G", SuspiciousPrisonguardScript)      # num 6/6
    _add("BG36_356", TyraelScript)
    _add("BG36_356_G", TyraelScript)                     # num 100/100
    # choose_one
    _add("BG27_084", SprightlyScarabScript)
    _add("BG27_084_G", SprightlyScarabScript)            # 基础值×2 触发
    _add("BG30_123", FearlessFoodieScript)
    _add("BG30_123_G", FearlessFoodieScript)             # 基础值×2 触发
    # spellcraft2（随从 + 法术 id）
    _add("BG23_004", DeepSeaAnglerScript)
    _add("BG23_004_G", DeepSeaAnglerScript)              # → 金色法术
    _add("BG23_004t", AnglersLureSpellScript)
    _add("BG23_004_Gt", AnglersLureSpellScript)          # num 4/12
    _add("BG31_920", DarkcrestStrategistScript)
    _add("BG31_920_G", DarkcrestStrategistScript)        # → 金色法术
    _add("BG31_920t", EvolvingStrategySpellScript)
    _add("BG31_920_Gt", EvolvingStrategyGoldenSpellScript)   # two
    _add("BG31_924", ThaumaturgistScript)
    _add("BG31_924_G", ThaumaturgistScript)              # → 金色法术
    _add("BG31_924t", ThaumaturgySpellScript)
    _add("BG31_924_Gt", ThaumaturgySpellScript)          # num1=2
    _add("BG27_514", SeaWitchZarjiraScript)
    _add("BG27_514_G", SeaWitchZarjiraScript)            # → 金色法术
    _add("BG27_514t", SirensSongSpellScript)
    _add("BG27_514t_G", SirensSongGoldenSpellScript)     # 2 copies
    _add("BG32_835", TranquilMeditativeScript)
    _add("BG32_835_G", TranquilMeditativeScript)         # → 金色法术
    _add("BG32_835t", MeditationSpellScript)
    _add("BG32_835_Gt", MeditationSpellScript)           # num 2/2
    # BG36_621 Deft Deserter — 主线终裁 2026-08-22:
    # hearthstone.wiki.gg Wiki tags = [Random] → "Taunt, Divine Shield,
    # or Windfury" 每个酒馆随从**独立随机**获得其一
    _add("BG36_621", DeftDeserterScript)
    _add("BG36_621_G", DeftDeserterScript)               # 金色 num(2)/num(3)=16/16 自然体现
    # 不注册（模块 docstring / 各类 Status）: BG36_344(+_G) DEFERRED /
    # BG36_333(+_G) DEFERRED / BG33_319(+_G 及法术) AMBIGUOUS
    return registered
