"""批次 spells1 — 13 张池法术（作业单 2026-08-21）。

实现状态总览:
  OK:    BG28_168 Shiny Ring / BG28_169 Azerite Empowerment /
         BG28_500 Armor Stash / BG28_503 Fortify / BG28_504 Recruit a
         Trainee / BG28_507 Sacred Gift / BG28_512 Enchanted Lasso /
         BG28_520 Tricky Trousers / BG28_521 Planar Telescope（含
         BG28_521t Consolation Coin token 注册）/ BG28_571 Hasty
         Excavation / BG28_573 Upper Hand / BG28_601 Cloning Conch /
         BG28_603 Boon of Beetles
  DEFERRED: 无
  语义查证（2026-08-23，EFFECT_SCRIPT_SOP §6b）:
    BG28_573 / BG28_603 的法术 SoC 时点 = RULES §4.2 事件档（第 4 档，
    英雄技能同档）——引擎层既定依据; 卡页均无 Notes（wiki 全文核对）。
    BG28_603 "when you have space in combat" = 战斗内腾位延迟（见该类
    docstring Evidence: r/BobsTavern 实测 + 30.2/33.6 官方同款句式）。

与作业单卡面描述的偏差（数据权威，hsdata/CardDefs.xml）:
  - BG28_168 / BG28_169 文本为 "Give **your minions** +{0}/+{1}"（全体
    友方，非定向）——作业单简写 "a minion" 与数据不符，按数据实现
    （Runic Arcanist BG36_245 batch_soc 先例同一读法）
  - 金色文本（@ 分隔，如 Fortify）在本数据基线**无独立金色卡实体**
    （池法术无 _G/TB_BaconUps 条目）——金色分支不可达，脚本按基础
    CardDef 实现

引擎缺口（见作业返回清单）:
  1. buy_from_tavern 无 health_cost 支持（BG28_571 "This costs Health
     to buy instead of Gold" 的购买侧扣血; 数据已导出 health_cost 标志，
     引擎 buy_from_tavern 仅走金币）——脚本侧仅实现施放效果 Gain 1 Gold
  2. 法术 SoC 无独立挂载点——本批经 START_OF_COMBAT 事件监听器实现
     （owner=hero），时点落在 §4.2 优先级第 4 档（英雄技能同档、随从
     SoC 之后）

池法术 buff 纪律: 一切 "Give a minion +X/+Y" 经 racefx.tavern_spell_buff
构造（自动叠加 TAVERN_SPELL_EXTRA_*，"Your Tavern spells give an extra
+X" 家族联动）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import Discover, GainGold, GainKeyword, GetRandomMinion, \
    LoseKeyword
from hsrl2.actions.discover import _pool_candidates
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.darkgifts import most_common_board_race
from hsrl2.events import AFTER_ATTACK, START_OF_COMBAT, Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

_TOKEN_BEETLE = "BG28_603t"      # Beetle 2/2 BEAST（BG28_603 关联 token）
_COIN_CONSOLATION = "BG28_521t"  # Planar Telescope 无效型保底 token


def _spell_target(ctx):
    """on_play 目标解析（play_spell 协议: ctx={"target": ...}）。

    None（定向法术无候选落空路径）→ 效果落空返回 None，禁止随机近似。
    """
    return ctx.get("target") if ctx else None


def _num(d, index: int, card_id: str) -> int:
    """必需模板参数取值——缺失即 GameStateError（fail-loud，Felboar
    batch_consume 先例），杜绝 None 参与算术的隐性崩溃。"""
    val = d.num(index)
    if val is None:
        from hsrl2.game import GameStateError
        raise GameStateError(
            f"{card_id}: missing num({index}) template param")
    return val


def _enemy_of(game: "Game", hero: "Hero"):
    """当前战斗对中 hero 的对手（引擎契约: CombatScheduler.run 在 SoC
    阶段前设置 game._active_combat = (a, b)；combat.py 注释明示该暴露
    供 "all other minions" 类卡定位敌方）。非战斗对中 → None。"""
    pair = getattr(game, "_active_combat", None)
    if not pair:
        return None
    x, y = pair
    if x is hero:
        return y
    if y is hero:
        return x
    return None


# ══════════════════ BG28_168 Shiny Ring ══════════════════


class ShinyRingScript:
    """
    Natural language: Give your minions +{0}/+{1}.

    Formal spec:
      1. on_play: 对控制者棋盘全部存活随从（"your minions" 无 other——
         数据文本全体友方，非定向; 作业单简写与数据不符，数据权威）
         各施加 tavern_spell_buff(num(0), num(1)) 永久 buff（受
         TAVERN_SPELL_EXTRA_* 增幅——酒馆法术 buff 统一出
         racefx.tavern_spell_buff）
      2. 空棋盘 → 无效果（法术照常消耗）
      3. 引擎侧（play_spell）: is_pool_spell → 计入
         TAVERN_SPELLS_CAST_* 并广播 tavern_spell_cast

    Test: test_batch_spells1.py — 全板各 +num(0)/num(1) / TAVERN_SPELL_
    EXTRA 联动 / 施放计数 +1 / 空板落空

    Params: {0}=1 {1}=1（36.2.2 基线）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        buffs = [tavern_spell_buff(m, _num(d, 0, source.card_id),
                                   _num(d, 1, source.card_id))
                 for m in hero.board if not m.dead]
        return buffs or None


# ══════════════════ BG28_169 Azerite Empowerment ══════════════════


class AzeriteEmpowermentScript:
    """
    Natural language: Give your minions +{0}/+{1} twice.

    Formal spec:
      1. on_play: times 次独立施加（"twice"——每次对全板存活随从各一个
         tavern_spell_buff(num(0), num(1)); 每次均叠加 TAVERN_SPELL_
         EXTRA_*，总额 = times×(num+extra)）; 逐次独立结算（与官方
         "twice" 两次独立效果一致，非单次翻倍）
      2. 空棋盘 → 无效果

    Test: test_batch_spells1.py — 全板 2×num / EXTRA 联动双计

    Params: {0}=2 {1}=2（36.2.2 基线）; times=2（"twice" 文本字面量）
    """

    times = 2   # "twice" 文本字面量

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        buffs = []
        for _ in range(source.scripts.times):
            buffs.extend(
                tavern_spell_buff(m, _num(d, 0, source.card_id),
                                  _num(d, 1, source.card_id))
                for m in hero.board if not m.dead)
        return buffs or None


# ══════════════════ BG28_500 Armor Stash ══════════════════


class ArmorStashScript:
    """
    Natural language: Set your Armor to 5.

    Formal spec:
      1. on_play: hero.armor = 5——"Set" 覆盖式（高于 5 时**降低**到 5、
         低于 5 时抬升到 5，非叠加; hero.armor setter 钳 ≥0）
      2. 无既有 SetArmor Action（actions/ 无护甲类）——直接属性写，
         与 hero.take_damage 的 armor 直改同构

    Test: test_batch_spells1.py — armor 12→5 / armor 0→5（覆盖语义）

    Params: armor=5（"Set your Armor to 5" 文本字面量——CardDef 无模板
    参数; 数据基线无金色独立卡，金色分支不可达）
    """

    armor_value = 5   # 文本字面量

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hero.armor = source.scripts.armor_value
        return None


# ══════════════════ BG28_503 Fortify ══════════════════


class FortifyScript:
    """
    Natural language: Give a minion +{1} Health and <b>Taunt</b>.

    Formal spec:
      1. needs_target=True（"Give a minion" 定向——play_spell 产生
         PendingChoice(kind="spell_target")，无候选时落空但法术消耗）
      2. on_play: target 施加 tavern_spell_buff(num(0)→攻（基础版文本
         无 {0}，CardDef num(0)=None → 0）， num(1)) 永久 buff +
         GainKeyword(TAUNT)
      3. 文本 @ 后金色分支（"+{0}/+{1} and Taunt"）在本数据基线无独立
         金色卡实体——不可达，按基础 CardDef 实现
      4. target=None → 落空

    Test: test_batch_spells1.py — +0/+num(1)+Taunt / EXTRA_HEALTH 联动 /
    PendingChoice 分流 / 空板落空

    Params: {1}=3（36.2.2 基线; {0} 基础版缺省 = 0 攻）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        d = game.db.get(source.card_id)
        return [tavern_spell_buff(target, d.num(0, 0),
                                  _num(d, 1, source.card_id)),
                GainKeyword(target, GameTag.TAUNT)]


# ══════════════════ BG28_504 Recruit a Trainee ══════════════════


class RecruitATraineeScript:
    """
    Natural language: [x]Get a random\nTier 1 minion.

    Formal spec:
      1. on_play: GetRandomMinion(hero, min_tier=1, max_tier=1)——
         池感知（池剩余量/active_races 过滤，RULES §2.3/§2.4）: 随机
         走 game.rng、acquire 占池、满手 pending_hand_add 排队 (P6)
      2. 池空（无 T1 可用）→ 落空（真实池空行为）

    Test: test_batch_spells1.py — 手牌得 T1 随从且池对应 id 减 1

    Params: min_tier=1 max_tier=1（"Tier 1" 文本字面量——无占位符）
    """

    min_tier = 1   # "Tier 1" 文本字面量
    max_tier = 1

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GetRandomMinion(hero,
                               min_tier=source.scripts.min_tier,
                               max_tier=source.scripts.max_tier)


# ══════════════════ BG28_507 Sacred Gift ══════════════════


class SacredGiftScript:
    """
    Natural language: Give a minion\n<b>Divine Shield</b>.

    Formal spec:
      1. needs_target=True（定向圣盾，PendingChoice kind="spell_target"）
      2. on_play: GainKeyword(target, DIVINE_SHIELD)（非数值 buff——
         tavern_spell_buff 不适用，TAVERN_SPELL_EXTRA_* 仅增幅属性）
      3. target=None → 落空

    Test: test_batch_spells1.py — 目标获得圣盾 / 无 target 走
    PendingChoice 分流后授予

    Params: 无数值参数（文本无占位符）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        return GainKeyword(target, GameTag.DIVINE_SHIELD)


# ══════════════════ BG28_512 Enchanted Lasso ══════════════════


class EnchantedLassoScript:
    """
    Natural language: Steal a random minion from the Tavern.

    Formal spec:
      1. on_play: 候选 = hero.tavern 中的 Minion 实体（"minion"——馆内
         法术不可偷）; rng.choice 随机（label 审计）; 无候选 → 落空
      2. Steal = **实体转移**（Decoy Conjurer BG36_354 batch_activate
         裁定先例）: 馆内随从在抽取展示时已 acquire 占池 → 偷取**不
         重复占池**; hero.tavern.remove → zone=HAND → pending_hand_add
         （满手排队不销毁，P6）; 后续出售/淘汰经 release_minion_entity
         正常回池，池守恒
      3. 转移保留实体全部状态（含酒馆期 buff——与购买同语义）

    Test: test_batch_spells1.py — 馆内随机随从实体入手（身份断言）、
    池不重复占用 / 馆内法术不可偷 / 空馆落空

    Params: 无数值参数（"a random minion" = 1 个，文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = [m for m in hero.tavern if isinstance(m, Minion)]
        if not cands:
            return None
        victim = game.rng.choice(cands, label="enchanted_lasso_steal")
        hero.tavern.remove(victim)
        victim.zone = Zone.HAND
        game.pending_hand_add(hero, victim)
        return None


# ══════════════════ BG28_520 Tricky Trousers ══════════════════


class TrickyTrousersScript:
    """
    Natural language: Give a minion +{0}/+{1} and <b>Taunt</b>. If it
    already has <b>Taunt</b>, remove it.

    Formal spec:
      1. needs_target=True（定向，PendingChoice kind="spell_target"）
      2. on_play: 先快照 had_taunt = target.has(TAUNT)（判定基准=
         施加前），随后:
         a) tavern_spell_buff(target, num(0), num(1)) 永久 buff——
            **无论是否已有 Taunt 均施加**（"Give ... +X/+Y and Taunt.
            If it already has Taunt, remove it." 官方语义: buff 恒给、
            关键词切换）
         b) had_taunt → LoseKeyword(TAUNT)（"remove it" 移除嘲讽）;
            否则 GainKeyword(TAUNT)
      3. target=None → 落空

    Test: test_batch_spells1.py — 无嘲讽目标 +num+获得嘲讽 / 已嘲讽
    目标 +num+失去嘲讽

    Params: {0}=1 {1}=2（36.2.2 基线）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        d = game.db.get(source.card_id)
        had_taunt = target.has(GameTag.TAUNT)
        actions = [tavern_spell_buff(target, _num(d, 0, source.card_id),
                                     _num(d, 1, source.card_id))]
        if had_taunt:
            actions.append(LoseKeyword(target, GameTag.TAUNT))
        else:
            actions.append(GainKeyword(target, GameTag.TAUNT))
        return actions


# ══════════════════ BG28_521 Planar Telescope ══════════════════


class PlanarTelescopeScript:
    """
    Natural language: [x]<b>Discover</b> a minion of\nyour most common
    type.

    Formal spec:
      1. on_play: race = darkgifts.most_common_board_race(hero, rng)
         （batch_rally2 同源帮助函数: 只计棋盘有种族随从、ALL 不计入、
         并列 rng 任选）; 无候选种族（空板/全无种族）→ Consolation
         Coin（BG28_521t "Gain 1 Gold. (There were no available minions
         of a valid type.)"——数据在册 token，create_spell +
         pending_hand_add）
      2. 有众数种族 → Discover(hero, candidates=_pool_candidates(
         race=race))（池过滤权威: 剩余量/active_races/ALL 匹配，
         RULES §6.18）; 默认 resolve = 选中 acquire 占池 → create_
         minion → 入手（三选一队列化）
      3. 众数种族存在但池内该种族无副本 → 同 Coin（"no available
         minions of a valid type" 文本双条件: 无有效型 / 有效型无
         可得随从）

    Test: test_batch_spells1.py — 众数种族三选一（选项全该种族、选中
    占池入手）/ 空板得 Coin 且施放 +1 金 / 池空该种族得 Coin

    Params: 无数值参数（"most common" 运行时计算）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        race = most_common_board_race(hero, game.rng)
        cands = _pool_candidates(game, race=race) if race is not None else []
        if not cands:
            game.pending_hand_add(
                hero, game.create_spell(_COIN_CONSOLATION, controller=hero))
            return None
        return Discover(hero, candidates=cands)


class ConsolationCoinScript:
    """
    Natural language: [x]Gain 1 Gold.\n<i>(There were no available
    __minions of a valid type.)</i>

    Formal spec:
      1. Planar Telescope（BG28_521）无有效发现时的保底 token（数据
         在册、非池法术——不计 TAVERN_SPELLS_CAST）
      2. on_play: GainGold(hero, 1)

    Test: test_batch_spells1.py — 施放 Coin 金币 +1

    Params: amount=1（"Gain 1 Gold" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GainGold(hero, 1)


# ══════════════════ BG28_571 Hasty Excavation ══════════════════


class HastyExcavationScript:
    """
    Natural language: Gain 1 Gold.\nThis costs Health to\nbuy instead
    of Gold.

    Formal spec:
      1. on_play: GainGold(hero, 1)（"Gain 1 Gold" 施放效果全量）
      2. "This costs Health to buy instead of Gold" = **购买侧**属性
         （酒馆购买价格改扣英雄生命）——属引擎 buy_from_tavern 职责;
         数据已导出 health_cost 标志但引擎购买路径未消费（引擎缺口
         #1，见模块 docstring）。脚本不越权实现购买语义

    Test: test_batch_spells1.py — 施放后金币 +1

    Params: amount=1（"Gain 1 Gold" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GainGold(hero, 1)


# ══════════════════ BG28_573 Upper Hand ══════════════════


class UpperHandScript:
    """
    Natural language: <b>Start of Combat:</b> Set\na random enemy
    minion's Health to 1.

    Formal spec:
      1. on_play（法术施放即挂载）: 注册 once Listener(START_OF_COMBAT,
         owner=hero)——法术实体施放后 REMOVED 不可作 owner，hero 恒在
         场; condition: hero is 施放者（旁观战斗不消耗）
      2. 触发（施放者的下一场战斗的 SoC 阶段，START_OF_COMBAT 事件档
          ——RULES §4.2 第 4 档（英雄技能同档），晚于随从 SoC; 法术
          SoC 相对顺序的引擎层依据，卡页无 Notes——wiki.gg/wiki/
          Battlegrounds/Upper_Hand 全文核对，28.2.3 官方 bugfix 仅
          "Fixed bugs causing issues" 无时序细节）: 对手 = _enemy_of(
          game, hero)（引擎 _active_combat 暴露）; 敌方存活随从
          rng.choice 随机一个（Wiki tags [Random]）→ BASE_HEALTH=1 且
          HEALTH=1（"Set Health" 覆盖式，Wiki mechanics [Set health],
          Sly Raptor BG25_806 "Set its stats" 先例——max health 一并
          归 1）; 敌方无随从 → 落空
      3. 单场效果实现于本类 start_of_combat 钩子（audit_card_registry_
         v2: data start_of_combat 关键词 → 钩子必须在册）; 引擎对
         REMOVED 法术实体不驱动钩子（combat.py 仅枚举饰品/奖励/棋盘/
         hand_soc 随从）→ on_play 经监听器回调同一实现（法术 SoC 挂载
         点 = 引擎缺口 #2）
      4. 生命周期: once=True 单次消耗——引擎 run_combat 监听器快照恢复
         按 _fired 标记过滤已触发 once（game.py:1284 修复），战斗后不
         复活、下一场战斗不再触发; 效果落在战斗内 → 战后随棋盘快照
         恢复回滚（RULES §3.5）

    Test: test_batch_spells1.py — SoC 后随机敌方随从 Health/BaseHealth
    =1 / 完整战斗后监听器消耗（第二场不再触发）

    Params: health=1（"Health to 1" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = (ctx or {}).get("hero") or source.controller
        if hero is None:
            return
        enemy = _enemy_of(game, hero)
        if enemy is None:
            return
        cands = [m for m in enemy.board
                 if isinstance(m, Minion) and not m.dead]
        if not cands:
            return
        victim = game.rng.choice(cands, label="upper_hand_victim")
        victim.set(GameTag.BASE_HEALTH, 1)
        victim.health = 1

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None

        def on_soc(g, hero=None, **kw):
            UpperHandScript.start_of_combat(source, g, {"hero": hero})

        game.events.register(Listener(
            event=START_OF_COMBAT,
            owner=hero,
            once=True,
            condition=lambda hero=None, **kw: hero is not None
            and hero is source.controller,
            callback=on_soc,
        ))
        return None


# ══════════════════ BG28_601 Cloning Conch ══════════════════


class CloningConchScript:
    """
    Natural language: Get a random Murloc and a copy of it.

    Formal spec:
      1. on_play: 候选 = _pool_candidates(race=MURLOC)（池剩余量/
         active_races/ALL 匹配，Amalgam 规则）; 无候选 → 落空
      2. 随机 Murloc: rng.choice → minion_pool.acquire 占池（首份，
         RULES §2.3）→ create_minion → pending_hand_add（满手排队）
      3. "a copy of it": create_minion(同 card_id) 白板副本入手——
         **不占池**（copy 语义，SOP §3; 原件为池新取白板 → 副本与
         原件恒同构，无状态漂移）
      4. 非金色副本（法术无金色实体，金色分支不可达）

    Test: test_batch_spells1.py — 手牌 2 张同 id Murloc 且池仅减 1 /
    池无 Murloc 落空

    Params: 无数值参数（"a random Murloc and a copy" = 1+1，文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = _pool_candidates(game, race=Race.MURLOC)
        if not cands:
            return None
        cid = game.rng.choice(cands, label="cloning_conch_murloc")
        if not game.minion_pool.acquire(cid):
            from hsrl2.game import GameStateError
            raise GameStateError(
                f"Cloning Conch: pool acquire failed for {cid}")
        game.pending_hand_add(
            hero, game.create_minion(cid, controller=hero))
        game.pending_hand_add(
            hero, game.create_minion(cid, controller=hero))
        return None


# ══════════════════ BG28_603 Boon of Beetles ══════════════════


class BoonOfBeetlesScript:
    """
    Natural language: [x]When you have space
    in combat, summon two
    {0}/{1} Beetles and give
    them <b>Taunt</b>. <i>({2} left!)</i>

    Formal spec:
      1. on_play（法术施放即挂载）: 注册常驻 Listener(START_OF_COMBAT,
         owner=hero)，剩余次数 charges = num(2)（"(N left!)" 卡面计数
         ——Felboar BG28_633 batch_consume 同族语义: 有限次数效果）。
         每场战斗 SoC 触发（单场效果实现于本类 start_of_combat 钩子——
         audit_card_registry_v2 关键词↔钩子校验; 引擎对 REMOVED 法术
         实体不驱动钩子 → 监听器回调同一实现）: 有空位 → 召唤 beetles
         个 Beetle token（BG28_603t，属性覆盖为本卡 num(0)/num(1)
         ——Beetle 系卡自带参数覆盖属性先例，Buzzing Vermin
         BG31_803）+ GainKeyword(TAUNT)，次数 -1; **满板 → 不召唤
         不消耗**，转入 2
      2. **战斗内腾位补召**（Evidence 见下）: SoC 满板时注册战斗内
         AFTER_ATTACK 检查点（owner=hero、condition=charges>0——
         战斗中注册的监听器随引擎监听器表恢复出队，不外溢招募期）;
         每次攻击结算后有空间 → 按 1 款召唤并消耗 1 次
      3. 召唤为战斗 token: game.summon（in_combat）→ combat_summon_log
         可观测; 不在战前 board_before 快照 → 战后随引擎 board 恢复
         消失（RULES §3.5）; 不占池（Summon token 语义）
      4. 次数耗尽 → 监听器休眠（condition False），效果停止
      5. 恰 1 空位: 逐只 game.summon（MINION_OVERFLOW 拒绝溢出只），
         次数仍消耗 1（效果已触发计——边角，无官方反证，r/BobsTavern
         实测仅确认"满板不消耗+腾位补召"主干）

    Evidence:
      - r/BobsTavern 实测（reddit.com/r/BobsTavern/comments/1dq54cu）:
        "Full board doesn't affect this. **It summons when there's
        space.**" ——满板不阻止，腾位即召
      - 官方同款句式（延迟语义佐证）: 30.2 任务奖励 "When you have
        space, summon an exact copy of your first Mech that died each
        combat"（playhearthstone.com/en-us/blog/24122902）; 33.6 被动
        "When you have space in combat, summon a copy of your
        highest-Attack minion"（/blog/24232759）
      - 35.6.0 官方 bugfix "could trigger twice incorrectly"（触发
        幂等性先例）; 卡页无 Notes（wiki.gg/wiki/Battlegrounds/
        Boon_of_Beetles 全文核对）
      - 法术 SoC 时点: RULES §4.2 事件档（英雄技能同档，晚于随从
        SoC）——引擎层既定依据

    Test: test_batch_spells1.py — SoC 召 2 只 Beetle（BASE==num(0)/
    num(1)、Taunt）/ 板满不消耗且**腾位后补召** / 完整战斗次数逐场
    耗尽且战后 token 消失

    Params: {0}=2 {1}=2 {2}=2（36.2.2 基线）; beetles=2（"two" 文本
    字面量）
    """

    beetles = 2   # "summon two" 文本字面量

    @staticmethod
    def start_of_combat(source, game, ctx):
        """单场战斗效果: 召唤 Beetle 战斗 token。返回 True=已消耗一次
        （有空位且召唤结算），False=板满未消耗（转腾位补召）。"""
        hero = (ctx or {}).get("hero") or source.controller
        if hero is None or hero.board_full():
            return False
        d = game.db.get(source.card_id)
        atk = _num(d, 0, source.card_id)
        health = _num(d, 1, source.card_id)
        for _ in range(source.scripts.beetles):
            m = game.create_minion(_TOKEN_BEETLE, controller=hero)
            m.set(GameTag.BASE_ATK, atk)
            m.set(GameTag.BASE_HEALTH, health)
            if game.summon(hero, m):
                game.run_actions(GainKeyword(m, GameTag.TAUNT))
        return True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        charges = [_num(d, 2, source.card_id)]

        def on_soc(g, hero=None, **kw):
            if hero is not source.controller:
                return
            if BoonOfBeetlesScript.start_of_combat(source, g,
                                                   {"hero": hero}):
                charges[0] -= 1
                return
            # 满板: 战斗内腾位补召（AFTER_ATTACK 检查点）
            def on_after_attack(g2, **kw2):
                if charges[0] <= 0 or hero.board_full():
                    return
                if BoonOfBeetlesScript.start_of_combat(source, g2,
                                                       {"hero": hero}):
                    charges[0] -= 1

            g.events.register(Listener(
                event=AFTER_ATTACK, owner=hero,
                condition=lambda **kw3: charges[0] > 0,
                callback=on_after_attack))

        game.events.register(Listener(
            event=START_OF_COMBAT,
            owner=hero,
            condition=lambda hero=None, **kw: hero is not None
            and hero is source.controller
            and charges[0] > 0,
            callback=on_soc,
        ))
        return None


def register() -> list[str]:
    """注册本批次全部脚本，返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG28_168", ShinyRingScript)
    _add("BG28_169", AzeriteEmpowermentScript)
    _add("BG28_500", ArmorStashScript)
    _add("BG28_503", FortifyScript)
    _add("BG28_504", RecruitATraineeScript)
    _add("BG28_507", SacredGiftScript)
    _add("BG28_512", EnchantedLassoScript)
    _add("BG28_520", TrickyTrousersScript)
    _add("BG28_521", PlanarTelescopeScript)
    _add("BG28_521t", ConsolationCoinScript)
    _add("BG28_571", HastyExcavationScript)
    _add("BG28_573", UpperHandScript)
    _add("BG28_601", CloningConchScript)
    _add("BG28_603", BoonOfBeetlesScript)
    return registered
