"""批次 hero_passives — 被动英雄技能 15 张（作业单 2026-08-22）。

被动协议（本批约定，见作业单）:
  - 脚本类声明 ``passive = True`` + 静态方法 ``on_bind(hero, game)``
  - on_bind 注册事件监听器 **owner=hero**——英雄实体整局在场、离场不
    注销（对照: 随从侧监听器 owner=minion 死亡即注销），符合"被动持续
    整局"语义
  - 引擎 use_hero_power 对 passive=True 恒返回 False（game.py:899）
    ——被动不可主动使用 ✓（本批测试断言）
  - ⚠️ 引擎缺口（报告主线）: Game.start_game/构造时**无被动接线**——
    需主线在 start_game 对每个 hero 补一行:
    ``REGISTRY[power.id].on_bind(hero, game)``
    （power = game.hero_power_def(hero)，脚本类带 on_bind 属性才调）
    本批测试显式调用 on_bind 验证（接线后测试无需改动）

数据侦察（36.2.2，116 名英雄全量打印）+ 选卡:
  被动 = 文本为持续光环/事件触发（"After you ..."/"At the start of
  ..."/"Start of Combat:"/"Start the game with ..."），全部依赖引擎
  既有事件: minion_bought / minion_sold / tavern_upgraded / turn_start /
  tavern_refresh / death / start_of_combat / combat_end（hero_damage_
  taken 本批无选卡命中）。

  逐卡数值核实（db.num 权威; None = 无模板参数→文本字面量）:
    BG26_HERO_101p  Hoggarr     无参数（"gain 1 Gold"→1 字面量）
    TB_BaconShop_HP_063 Nozdormu 无参数（"a free Refresh"→1 次）
    TB_BaconShop_HP_082 Omu      无参数（"gain 2 Gold"→2 字面量）
    TB_BaconShop_HP_056 Flurgl   num(0)=num(1)=5（阈值）
    TB_BaconShop_HP_066 Kael'thas 无参数（"3 minions"→3 字面量;
                      无 evolution 链 → Tavern Coin=BG28_810 卡 id 字面量，
                      该 id 已注册 TavernCoinScript batch_spells2）
    TB_BaconShop_HP_008 Gallywix 无参数（"1 Gold next turn"→1 字面量）
    TB_BaconShop_HP_048 Dinotamer Brann 无参数（"4 Battlecry
                      minions"→4 字面量）; evolution_card_id=96786 →
                      BG_LOE_077 Brann Bronzebeard（数据链解析，零硬编码）
    BG22_HERO_200p  Ini Stormcoil num(0)=9（阈值）
    TB_BaconShop_HP_086 Al'Akir  无参数（三关键词）
    TB_BaconShop_HP_103 Y'Shaarj 无参数（"of your Tier"动态）
    TB_BaconShop_HP_061 Deathwing 无参数（"+2 Attack"→2 字面量）
    TB_BaconShop_HP_062 Ysera    无参数（"an extra Dragon"→1 只）
    BG20_HERO_100p  Rokara       无参数（"+1 Attack"→1 字面量）
    TB_BaconShop_HP_033 Curator  无参数（Amalgam token =
                      TB_BaconShop_HP_033t 2/2 Venomous race=ALL(26)
                      已核实，卡 id 字面量——无数据链）
    TB_BaconShop_HP_035 Patchwerk 无参数（"30 extra Health"→30 字面量）

"permanently" 战斗跨回合裁定（Deathwing / Rokara）:
  引擎战后快照回滚（run_combat restore_state）会清除战斗内 Buff——
  官方 "permanently" = 战斗中即时生效（影响本场后续攻击结算）**且**
  战后保留。脚本层协议: SoC/击杀时即时 Buff（参与本场结算）+ 记录
  pending（hero 闭包）; combat_end（引擎在棋盘复原后广播，game.py
  end_recruit_phase / run_ghost_combat）重放永久 Buff。净效果 = 官方。
  幽灵战同样广播 combat_end ✓（配对含幽灵时照常重放）。
  Rokara 击杀者若本场随后战死: 战后棋盘复原含战死随从（BG 复活语义）
  → 重放照常落在其身上 ✓ 官方一致; 战斗召唤物（不在战前棋盘）不重放
  ——其本体战后即消失 ✓。

实现状态总览:
  OK 15: Hoggarr / Nozdormu / Omu / Flurgl / Kael'thas / Gallywix /
          Dinotamer Brann / Ini Stormcoil / Al'Akir / Y'Shaarj /
          Deathwing / Ysera / Rokara / The Curator / Patchwerk
  DEFERRED 1（不注册）: TB_BaconShop_HP_087 Ragnaros "BUY, INSECT!"
      ——**2026-08-23 已解冻**: 引擎三项缺口（被动接线/turn_end 广播/
      英雄技能替换协议）由主线落地后，本卡连同 Sulfuras
      （TB_BaconShop_HP_087t）在 batch_hero_passives2 批注册实现;
      本文件遗留的 RagnarosScript 类为历史台账、未注册（注册表
      键由 passives2 批持有）。

跳过名单（作业单点名、经数据核实不属本批）:
  - Nefarian: 36.2.2 数据无此英雄（116 英雄全量打印无命中，仅
    存在名称匹配空——已退出英雄池）
  - Professor Putricide "Craft a custom Undead": 主动合成 UI 技能
    （多步选择链），下批主动技能体系
  - A.F. Kay "Skip your first two turns, then Discover...": 跳过
    回合需经济系统 turn-skip 原语 + 延迟发现链，复杂度超本批
  - Pyramad "Steal a random minion from the Tavern. Double its
    Health."（cost=2）: 现行文本为**主动**技能（一次性效果动词
    开头），归下批
  - 主动技能英雄（"Hero Power" 可点击）一律下批

引擎缺口汇总（报告主线）:
  1. 被动接线: start_game 需为每个 hero 调
     REGISTRY[hero_power_id].on_bind(hero, game)（本批协议）
  2. turn_end 事件未广播（Ragnaros/Sulfuras/C'Thun 类 EoT 被动阻塞）
  3. 英雄技能替换协议缺失（"get/replace Hero Power" 类阻塞:
     Ragnaros / Genn / Master Nguyen / Sir Finley）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.actions import GainGold, GetRandomMinion, ScheduleNextTurn
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    COMBAT_END,
    DEATH,
    MINION_BOUGHT,
    MINION_SOLD,
    START_OF_COMBAT,
    TAVERN_REFRESH,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# 事件名常量 events.py 未导出（引擎以字面量 fire，game.py:832）
TAVERN_UPGRADED = "tavern_upgraded"

# 卡 id 字面量（无数据链可解析; 对照引擎 FODDER_CARD_ID 先例）:
_TAVERN_COIN_ID = "BG28_810"             # Tavern Coin（已注册 TavernCoinScript）
_AMALGAM_ID = "TB_BaconShop_HP_033t"     # The Curator 的 Amalgam token

# ALL 视为所有种族 (RULES §6.18)
_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_DRAGON_RACES = (Race.DRAGON, Race.ALL)


def _power_def(game: "Game", power_id: str):
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    return d


# ═══════════════════ BG26_HERO_101p Cap'n Hoggarr ═══════════════════

class CapnHoggarrScript:
    """
    Natural language: After you buy a Pirate, gain 1 Gold.

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 minion_bought
         (minion=)——buy_from_tavern 购买随从路径
      2. 条件: minion.controller is hero（"you buy"）、
         minion.race ∈ {PIRATE, ALL}
      3. 触发: GainGold(hero, 1)——hero.gold setter 执行 99 持有
         上限（RULES §1.4）; 每买一只海盗触发一次
      4. 法术购买不触发（spell_bought 是独立事件，非 minion_bought）

    Test: test_batch_hero_passives.py — 买海盗 +1 金 / 买非海盗不加 /
    敌方购买不触发 / 金币 99 上限钳制

    Params: amount=1（文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_bought(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            if minion.race not in _PIRATE_RACES:
                return
            g.run_actions(GainGold(hero, amount=1))

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_bought))


# ═══════════════════ TB_BaconShop_HP_063 Nozdormu ═══════════════════

class NozdormuScript:
    """
    Natural language: At the start of your turn, gain a free Refresh.

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 turn_start
         (turn=, hero=)
      2. 条件: hero is 绑定英雄（"your turn"）
      3. 触发: hero.FREE_REFRESH_REMAINING += 1——refresh_tavern 非
         auto 路径优先消耗免费次数（game.py:267-270，先于金币）;
         回合开始的 auto 刷新不消耗次数（auto=True 跳过计费）→
         免费次数留给本回合手动刷新 ✓ 官方语义
      4. 多次 turn_start 多次 +1（每回合各一次）; 次数跨回合不清零
         （引擎无清零点——未用的免费刷新留存，官方行为一致）

    Test: test_batch_hero_passives.py — turn_start 后手动刷新不扣金 /
    免费次数耗尽后回落扣金 / 敌方回合不触发

    Params: 无模板参数（"a free Refresh"=1 次/回合——回合频率由
            turn_start 事件本身保证）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_turn_start(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            _owner.set(GameTag.FREE_REFRESH_REMAINING,
                       _owner.get(GameTag.FREE_REFRESH_REMAINING, 0) + 1)

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════════ TB_BaconShop_HP_082 Forest Warden Omu ═══════════════════

class ForestWardenOmuScript:
    """
    Natural language: After you upgrade the Tavern, gain 2 Gold.

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 "tavern_upgraded"
         (hero=, tier=)——upgrade_tavern 成功路径 fire（game.py:832）
      2. 条件: hero is 绑定英雄
      3. 触发: GainGold(hero, 2)——立即获得（本回合可用，官方语义）
      4. 每次升级触发一次（T1→T2 … T5→T6 各一次）

    Test: test_batch_hero_passives.py — 升级后净金 = -升级费 +2 /
    金币不足升级失败不触发 / 敌方升级不触发

    Params: amount=2（文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_upgraded(g, hero=None, _owner=hero, tier=0, **kw):
            if hero is not _owner:
                return
            g.run_actions(GainGold(_owner, amount=2))

        game.events.register(Listener(
            event=TAVERN_UPGRADED, owner=hero, callback=on_upgraded))


# ═══════════════════ TB_BaconShop_HP_056 Fungalmancer Flurgl ═══════════════════

class FungalmancerFlurglScript:
    """
    Natural language: After you sell 5 minions, get a random Murloc.
    <i>(@ left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 minion_sold
         (minion=)——sell_minion 路径（含 on_sell 效果之后）
      2. 条件: minion.controller is hero（"you sell"; 招募期出售
         手牌/棋盘随从均 fire）
      3. 计数: 闭包 state（跨回合累积）+ 取模消费——达 num(0)=5 触发
         并清零（"(@ left!)" 为逐次进度显示，每 5 次 repeat）
      4. 触发: GetRandomMinion(hero, race=MURLOC)——池约束（≤tier
         不限、种族 Murloc 含 ALL）、占池 acquire、满手排队
         （RULES §2.3/§2.4/§3.3）; 池空落空（官方行为）
      5. 金色无此卡（英雄技能无金色）

    Test: test_batch_hero_passives.py — 卖 4 只不触发 / 第 5 只入手
    random Murloc（占池）/ 取模: 再卖 5 只再触发 / 敌方出售不计数

    Params: {0}=5（阈值=script_data_num_1; num(1)=5 为进度显示参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        threshold = _power_def(game, "TB_BaconShop_HP_056").num(0)
        state = {"sold": 0}

        def on_sold(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            state["sold"] += 1
            if state["sold"] >= threshold:
                state["sold"] -= threshold
                g.run_actions(GetRandomMinion(hero, race=Race.MURLOC))

        game.events.register(Listener(
            event=MINION_SOLD, owner=hero, callback=on_sold))


# ═══════════════════ TB_BaconShop_HP_066 Kael'thas Sunstrider ═══════════════════

class KaelthasScript:
    """
    Natural language: After you buy 3 minions, get a Tavern Coin.

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 minion_bought
         (minion=)——仅随从购买（法术走 spell_bought，"3 minions"
         严格词）
      2. 计数: 闭包 state 跨回合计数 + 取模消费（每 3 只触发）
      3. 触发: 获得 Tavern Coin（BG28_810，池法术 is_pool_spell=True，
         36.2.2 数据核实; power CardDef 无 evolution 链 → 卡 id 字面量
         _TAVERN_COIN_ID）走池语义（Shell Collector batch_battlecry
         先例）: 池内有副本 → spell_pool.acquire（占池）; 池空 → 仍
         生成不占池（Mystic Essence Dark Gift 先例）;
         create_spell + pending_hand_add（满手排队）
      4. Tavern Coin "Gain 1 Gold." 的 on_play 已由 batch_spells2
         TavernCoinScript 注册（打出去 +1 金闭环 ✓）

    Test: test_batch_hero_passives.py — 买 2 只不触发 / 第 3 只入手
    Tavern Coin（占用法术池）/ 买法术不计数 / 取模 repeat

    Params: count=3（文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        state = {"bought": 0}

        def on_bought(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            state["bought"] += 1
            if state["bought"] >= 3:
                state["bought"] -= 3
                if not g.spell_pool.acquire(_TAVERN_COIN_ID):
                    pass   # 池空: 仍生成不占池（先例见类 docstring）
                g.pending_hand_add(
                    hero, g.create_spell(_TAVERN_COIN_ID, controller=hero))

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_bought))


# ═══════════════════ TB_BaconShop_HP_008 Trade Prince Gallywix ═══════════════════

class TradePrinceGallywixScript:
    """
    Natural language: After you sell a minion, gain 1 Gold next turn.
    （@[x] 升级变体 "... <i>({0} Gold saved.)</i>" 仅进度显示）

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 minion_sold
      2. 条件: minion.controller is hero
      3. 触发: ScheduleNextTurn(hero, GainGold(hero, 1))——
         game.defer_until_next_turn 队列; _begin_recruit_for 在金币
         覆盖式重置**之后**执行延迟动作（game.py:170-177 注释即为本
         类效果设计: "GainGold 类延迟效果叠加在基础收入之上"）→
         官方 "gain 1 Gold next turn" 精确语义
      4. 每卖一只叠加一条延迟 GainGold（同回合多卖多得，官方无上限
         文本）; 延迟动作随下一招募开始结算后出队

    Test: test_batch_hero_passives.py — 卖出后入延迟队列 / 下一回合
    金币 = 基础收入 + 1 / 敌方出售不触发

    Params: amount=1（文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_sold(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            g.run_actions(ScheduleNextTurn(hero, GainGold(hero, amount=1)))

        game.events.register(Listener(
            event=MINION_SOLD, owner=hero, callback=on_sold))


# ═══════════════════ TB_BaconShop_HP_048 Dinotamer Brann ═══════════════════

class DinotamerBrannScript:
    """
    Natural language: After you buy 4 Battlecry minions, get a Brann
    Bronzebeard. <i>(Once per game.)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 minion_bought
      2. 条件: minion.controller is hero、minion.has(BATTLECRY)
         （create_minion 从 CardDef.keywords 映射 BATTLECRY tag）
      3. 计数: 闭包 state 跨回合计数 + 取模清零; 达 4 触发
         "Once per game": done 标记后不再触发（计数器停摆）
       4. 触发: Brann Bronzebeard 卡 id 经 power CardDef
          evolution_card_id=96786 数据链解析（by_dbf → BG_LOE_077，
          零硬编码）; 池内可用 → minion_pool.acquire（占池，Brann 是
          池卡 is_pool_minion=True）+ create_minion +
          pending_hand_add; 池耗尽（他人持有全部副本）→ 本轮落空、
          不消耗 once。依据（2026-08-23 查证）: 官方 29.2.0 bugfix
          "Dinotamer Brann's Hero Power will now **wait until you
          have handspace**"（wiki.gg/wiki/Battlegrounds/Dinotamer_
          Brann#Bug_fixes——投递失败官方语义 = 等待不消耗; 本实现
          pending_hand_add 满手排队同构）+ RULES §2.4 池空不可获取
          （GetRandomMinion 同语义）; 池耗尽场景官方无直接记载（卡页/
          Battle Brand 页均无 Notes，已查），按投递失败不消耗处理
      5. 金色 Brann（TB_BaconUps_045）非本卡产物（Brann 自身三连的
         独立演化，与本技能无关）

    Test: test_batch_hero_passives.py — 买 3 只战吼随从不触发 / 第
    4 只入手 Brann（BG_LOE_077，占池）/ once per game: 再买 4 只不再
    给 / 非战吼随从不计数 / 敌方购买不计数

    Params: count=4（文本字面量——CardDef 无模板参数; 目标卡 id 经
            evolution_card_id 数据链）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "TB_BaconShop_HP_048")
        if d.evolution_card_id is None:
            raise GameStateError(
                "TB_BaconShop_HP_048: evolution_card_id broken data chain")
        brann_def = game.db.by_dbf(d.evolution_card_id)
        if brann_def is None:
            raise GameStateError(
                f"TB_BaconShop_HP_048: evolution_card_id "
                f"{d.evolution_card_id} not in db")
        state = {"bought": 0, "done": False}

        def on_bought(g, minion=None, **kw):
            if state["done"] or not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            if not minion.has(GameTag.BATTLECRY):
                return
            state["bought"] += 1
            if state["bought"] >= 4:
                state["bought"] -= 4
                if g.minion_pool.available(brann_def.id) > 0:
                    if not g.minion_pool.acquire(brann_def.id):
                        raise GameStateError(
                            f"dinotamer brann acquire failed "
                            f"for {brann_def.id}")
                    g.pending_hand_add(
                        hero, g.create_minion(brann_def.id,
                                              controller=hero))
                    state["done"] = True

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_bought))


# ═══════════════════ BG22_HERO_200p Ini Stormcoil ═══════════════════

class IniStormcoilScript:
    """
    Natural language: After 9 friendly minions die, get a random Mech.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 death (minion=)
         ——_process_single_death 官方死亡路径（战斗内/招募期双路径）
      2. 条件: minion.controller is hero（"friendly"——友方死亡;
         敌方/酒馆区死亡不计）
      3. 计数: 闭包 state 跨回合计数（"this game" 累计）+ 取模消费
         ——达 num(0)=9 触发并清零（repeat）
      4. 触发: GetRandomMinion(hero, race=MECH)——池约束、占池、
         满手排队; 池空落空
      5. 复生二次死亡照常计数（引擎每次死亡各 fire 一次 death——
         Avenge 同构，RULES §6.11 "任何友方死亡"先例）

    Test: test_batch_hero_passives.py — 8 次友方死亡不触发 / 第 9 次
    入手 random Mech（占池）/ 敌方死亡不计数 / 取模 repeat

    Params: {0}=9（阈值=script_data_num_1）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        threshold = _power_def(game, "BG22_HERO_200p").num(0)
        state = {"deaths": 0}

        def on_death(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            state["deaths"] += 1
            if state["deaths"] >= threshold:
                state["deaths"] -= threshold
                g.run_actions(GetRandomMinion(hero, race=Race.MECH))

        game.events.register(Listener(
            event=DEATH, owner=hero, callback=on_death))


# ═══════════════════ TB_BaconShop_HP_086 Al'Akir ═══════════════════

class AlAkirScript:
    """
    Natural language: Start of Combat: Give your left-most minion
    Windfury, Divine Shield, and Taunt.

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 start_of_combat
         (hero=)——CombatScheduler._start_of_combat_phase 第 4 步
         （英雄技能被动，combat.py:111 专为被动预留的广播点）
      2. 条件: hero is 绑定英雄（每场战斗单次触发——SoC 对战双方各
         fire 一次，condition 过滤己方）
      3. 触发: 棋盘最左（board[0]，ZONE_POSITION=0）存活随从 set
         WINDFURY / DIVINE_SHIELD / TAUNT
      4. 仅本场战斗生效: 关键词在 run_combat 战后快照回滚中清除
         （restore_state，RULES §3.5 战斗变化不延续）——官方 SoC
         临时增益语义 ✓ 空场落空
      5. 风怒的连续攻击由战斗调度器 WINDFURY tag 驱动（先攻判定后
         的攻击循环读取，SoC 早于先攻 C12 → 当场生效 ✓）

    Test: test_batch_hero_passives.py — SoC 后最左随从获三关键词 /
    第二只不受 / 空场安全 / 战后回滚（run_combat 后关键词消失）

    Params: 无模板参数（三关键词为文本字面量——非数值）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner or not _owner.board:
                return
            left_most = _owner.board[0]
            if left_most.dead:
                return
            left_most.set(GameTag.WINDFURY, True)
            left_most.set(GameTag.DIVINE_SHIELD, True)
            left_most.set(GameTag.TAUNT, True)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))


# ═══════════════════ TB_BaconShop_HP_103 Y'Shaarj ═══════════════════

class YshaarjScript:
    """
    Natural language: Start of Combat: Summon and get a minion of
    your Tier.

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 start_of_combat
         (hero=)，条件 hero is 绑定英雄（每场单次）
      2. 候选: _pool_candidates(min_tier=max_tier=hero.tavern_tier)
         ——池约束（RULES §2.4/§6.18）; 空落空
      3. 选中 cid: rng.choice + minion_pool.acquire（**1 份**——
         "get" 的手牌副本占池; 战斗召唤物为临时体不占池、战后随
         board_before 复原消失，无回池泄漏）
      4. "Summon": 棋盘未满时 create_minion + game.summon（战斗中
         召唤计入 combat_summon_log; 满板 → minion_overflow 落空，
         "get" 照常）; "get": create_minion 副本 pending_hand_add
         （满手排队 RULES §3.3）
      5. 两体同 card_id（官方: 召唤即获得其复制）

    Test: test_batch_hero_passives.py — SoC 后棋盘 +1 只 tier=本馆
    等级随从且手牌出现同 id 副本（占池 1 份）/ 满板时仅手牌 /
    池空落空

    Params: 无模板参数（Tier 动态 = hero.tavern_tier）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            tier = _owner.tavern_tier
            cands = _pool_candidates(g, min_tier=tier, max_tier=tier)
            if not cands:
                return
            cid = g.rng.choice(cands, label="yshaarj_tier_minion")
            if not g.minion_pool.acquire(cid):
                raise GameStateError(
                    f"yshaarj acquire failed for {cid}")
            if not _owner.board_full():
                combat_copy = g.create_minion(cid, controller=_owner)
                g.summon(_owner, combat_copy)
            g.pending_hand_add(
                _owner, g.create_minion(cid, controller=_owner))

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))


# ═══════════════════ TB_BaconShop_HP_061 Deathwing ═══════════════════

class DeathwingScript:
    """
    Natural language: Start of Combat: Give ALL minions +2 Attack
    permanently.

    Formal spec:
      1. on_bind 注册两个持久监听器（owner=hero）:
         a) start_of_combat (hero=)——战斗即时面
         b) combat_end (hero_a=, hero_b=, result=)——永久重放面
      2. SoC 条件: hero is 绑定英雄（每场单次）; 战斗对经引擎
         game._active_combat=(a, b) 定位（combat.py:70-72 专为 SoC
         "含敌方" 卡暴露的协议，Boom-in-a-Box 先例）——"ALL minions"
         = 交战双方棋盘全部存活随从（英雄技能被动影响对手侧，官方
         Deathwing 语义）; 非战斗上下文无 _active_combat → 落空
      3. SoC 触发: 双方棋盘各 Buff +2 攻（影响本场后续攻击结算——
         快照在 SoC 前拍摄，战斗结束 restore_state 回滚本 buff）
      4. combat_end 条件: 绑定英雄 ∈ (hero_a, hero_b)——此时棋盘已
         复原为战前快照（= SoC 时点在场者; 战斗召唤物已消失）→
         双方棋盘各重放 Buff +2 攻（净效果 = 官方 "permanently";
         幽灵战 combat_end 同样广播，配对含幽灵照常重放）
      5. 逐场叠加: 每场战斗 SoC+重放各 +2（第二场后累计 +4）

    Test: test_batch_hero_passives.py — SoC 双方全体 +2（战斗时点）/
    run_combat 后回滚至基线、combat_end 重放后永久 +2（双方）/
    第二场累计 +4 / 非本英雄配对的 combat_end 不重放

    Params: atk=2（文本字面量——CardDef 无模板参数）
    """

    passive = True
    _ATK_GAIN = 2   # "+2 Attack"（文本字面量，CardDef 无模板参数）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        gain = DeathwingScript._ATK_GAIN

        def _buff_board(g, combatant) -> None:
            for m in list(combatant.board):
                if not m.dead:
                    m.add_buff(entity.Buff(atk=gain))

        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            pair = getattr(g, "_active_combat", None)
            if pair is None:
                return
            for combatant in pair:
                _buff_board(g, combatant)

        def on_combat_end(g, hero_a=None, hero_b=None, **kw):
            if hero is not hero_a and hero is not hero_b:
                return
            for combatant in (hero_a, hero_b):
                _buff_board(g, combatant)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))
        game.events.register(Listener(
            event=COMBAT_END, owner=hero, callback=on_combat_end))


# ═══════════════════ TB_BaconShop_HP_062 Ysera ═══════════════════

class YseraScript:
    """
    Natural language: The Tavern offers an extra Dragon whenever it is
    Refreshed.

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: 事件 tavern_refresh
         (hero=)——refresh_tavern 末尾 fire（auto 回合开始刷新与手动
         刷新都触发，官方 "whenever it is Refreshed" 双路径 ✓）
      2. 条件: hero is 绑定英雄
      3. 触发: 追加 1 只额外 Dragon 入馆:
         a) 候选 = _pool_candidates(race=DRAGON, max_tier=
            hero.tavern_tier)（ALL 种族匹配，RULES §6.18）——与常规
            馆内展示同 tier 上限; 池空落空（诚实缺省）
         b) rng.choice + minion_pool.acquire（占池）+ create_minion
            + zone=TAVERN + hero.tavern.append
         c) 持久酒馆 Buff（hero.tavern_buffs，Saurfang 类）对新入馆
            随从照常应用——镜像 refresh_tavern 引擎逻辑（game.py:
            304-309），冻结保留项不重复应用（本卡只处理自己注入的
            这一只）
      4. 冻结/未购的额外 Dragon 下次刷新走既有回池路径（池守恒）

    Test: test_batch_hero_passives.py — 每次刷新馆内 Dragon 数恰 +1
    且 tier ≤ 本馆等级（对比刷新前后差量）/ 池空落空不报错

    Params: 无模板参数（"an extra Dragon"=1 只/次刷新）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_refresh(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            cands = _pool_candidates(g, race=Race.DRAGON,
                                     max_tier=_owner.tavern_tier)
            if not cands:
                return
            cid = g.rng.choice(cands, label="ysera_extra_dragon")
            if not g.minion_pool.acquire(cid):
                raise GameStateError(f"ysera acquire failed for {cid}")
            m = g.create_minion(cid, controller=_owner)
            m.zone = Zone.TAVERN
            for tb in getattr(_owner, "tavern_buffs", []):
                if tb.matches(g.db.get(cid)):
                    m.add_buff(entity.Buff(atk=tb.atk, health=tb.health,
                                           source_id=tb.source_id))
            _owner.tavern.append(m)

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=hero, callback=on_refresh))


# ═══════════════════ BG20_HERO_100p Rokara ═══════════════════

class RokaraScript:
    """
    Natural language: After a friendly minion kills an enemy, give it
    +1 Attack permanently.

    Formal spec:
      1. on_bind 注册两个持久监听器（owner=hero）:
         a) death (minion=)——击杀检测面
         b) combat_end (hero_a=, hero_b=)——永久重放面
      2. death 条件: 死者 minion.controller **不是**绑定英雄（敌方
         随从）、minion.KILLER 为 Minion 且 killer.controller is
         绑定英雄（友方击杀者; KILLER 由 Minion.take_damage 写入
         minion.py:109——含 Venomous/反击/招募期攻击 Fishbait 全
         路径）; 酒馆区死亡（controller 恒为己方英雄）不满足"enemy"
         → 不触发
      3. 击杀时: killer 即时 Buff +1 攻（影响本场后续结算）; 若
         g.in_combat 则 pending[killer] += 1（战后重放账本）;
         招募期击杀（Fishbait 路径）不在战斗内 → 无回滚风险，
         不记账本（Buff 直接持久）
      4. combat_end 条件: 绑定英雄 ∈ (hero_a, hero_b); 棋盘已复原
         → 对账本中仍在场（战前棋盘成员，BG 战后复活语义）的
         killer 重放 n×Buff(+1 攻) 后清账; 战斗召唤物击杀者战后
         消失（不在复原棋盘）→ 丢弃（其临时 +1 已随回滚消失，
         官方: 召唤物不保留）
      5. 击杀者随后战死不影响: 战后复原使其回场 → 照常重放 ✓

    Test: test_batch_hero_passives.py — _execute_attack 击杀后即时
    +1 攻 / 友方死亡与敌方击杀友方不触发 / run_combat 全流程:
    战后回滚至基线 → combat_end 重放永久 +1 / 多次击杀累计重放

    Params: atk=1（文本字面量——CardDef 无模板参数）
    """

    passive = True
    _ATK_GAIN = 1   # "+1 Attack"（文本字面量，CardDef 无模板参数）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        gain = RokaraScript._ATK_GAIN
        pending: dict = {}

        def on_death(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is hero:
                return
            killer = minion.get(GameTag.KILLER, None)
            if not isinstance(killer, Minion):
                return
            if killer.controller is not hero:
                return
            killer.add_buff(entity.Buff(atk=gain))
            if g.in_combat:
                pending[killer] = pending.get(killer, 0) + 1

        def on_combat_end(g, hero_a=None, hero_b=None, **kw):
            if hero is not hero_a and hero is not hero_b:
                return
            for m, n in list(pending.items()):
                ctrl = m.controller
                if ctrl is not None and m in ctrl.board:
                    m.add_buff(entity.Buff(atk=gain * n))
            pending.clear()

        game.events.register(Listener(
            event=DEATH, owner=hero, callback=on_death))
        game.events.register(Listener(
            event=COMBAT_END, owner=hero, callback=on_combat_end))


# ═══════════════════ TB_BaconShop_HP_033 The Curator ═══════════════════

class TheCuratorScript:
    """
    Natural language: Start the game with a 2/2 Amalgam with Venomous
    and all minion types.

    Formal spec:
      1. on_bind（= 游戏开始接线点）: create_minion(TB_BaconShop_
         HP_033t)——Amalgam token CardDef（36.2.2 数据核实: atk=2
         health=2 race=ALL(26) keywords={venomous}，create_minion
         自动映射 VENOMOUS tag）+ game.summon 入场（开局空板 ✓）
      2. token 非池卡（is_pool_minion=False）: 不占池; 出售/淘汰
         回池走 release_minion_entity 的非池跳过（池守恒）
      3. 卡 id 字面量 _AMALGAM_ID——power CardDef 无 evolution 链，
         引擎 FODDER_CARD_ID 硬编码先例（数值 2/2/Venomous/ALL 全部
         来自 token CardDef，零数值硬编码）

    Test: test_batch_hero_passives.py — on_bind 后棋盘恰 1 只
    Amalgam（2/2、VENOMOUS、race=ALL，数值全取自 db）

    Params: 无模板参数（2/2/Venomous/all types 全由 token CardDef
            权威）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        game.summon(hero, game.create_minion(_AMALGAM_ID,
                                             controller=hero))


# ═══════════════════ TB_BaconShop_HP_035 Patchwerk ═══════════════════

class PatchwerkScript:
    """
    Natural language: Start the game with 30 extra Health.

    Formal spec:
      1. on_bind（= 游戏开始接线点）: hero.health += 30——Hero
         HEALTH2 setter（max(0,·)）; 基础 30（C.HERO_BASE_HEALTH）
         → 60
      2. "30" 文本字面量（CardDef 无模板参数，power 文本无占位符
         → 按纪律允许并注明）; 与护甲无关（armor 不变）

    Test: test_batch_hero_passives.py — on_bind 后 health =
    C.HERO_BASE_HEALTH + 30 / 重复绑定会叠加（接线协议单次调用由
    主线保证）

    Params: 无模板参数（30 extra Health = 30 文本字面量）
    """

    passive = True
    _EXTRA_HEALTH = 30   # "30 extra Health"（文本字面量，无模板参数）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        hero.health += PatchwerkScript._EXTRA_HEALTH


# ═══════════════════ TB_BaconShop_HP_087 Ragnaros（DEFERRED） ═══════════════════

class RagnarosScript:
    """
    Natural language: After you buy 12 cards, get Sulfuras.
    <i>(@ left!)</i>

    Status: DEFERRED — requires 英雄技能替换协议 + turn_end 事件

    Dependency:
      1. "get Sulfuras"（num(0)=12 购买计数面可实现: minion_bought +
         spell_bought 双事件计数）的落点 Sulfuras =
         TB_BaconShop_HP_087t，CardType.HERO_POWER(10)——语义为
         **替换**当前英雄技能（Ragnaros 专属变身），引擎无替换协议:
         hero_power_def(hero) 恒读 hero CardDef.hero_power_id 静态链
         （game.py:871-876），无 swap/override API（subagent 禁改
         引擎）。需主线: hero.hero_power_override 槽 +
         hero_power_def 读取顺序。
      2. Sulfuras 自身 "At the end of your turn, give your left and
         right-most minions +8/+8" 依赖 turn_end 事件——引擎从不
         广播（TURN_END 常量存在但零 fire，grep 验证）; 需主线在
         end_recruit_phase 英雄 EoT 段补 fire。
      两项就绪后按: 双事件计数取模 12 → 替换技能 + 注册
      TB_BaconShop_HP_087t（EoT 监听器 owner=hero，+8/+8 文本
      字面量）。

    Params: {0}=12（script_data_num_1）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        return None


def register() -> list[str]:
    """注册本批次被动英雄技能脚本（注册键 = 技能 card_id）。

    OK 15/16（DEFERRED 1 不注册: TB_BaconShop_HP_087 Ragnaros——
    英雄技能替换协议 + turn_end 事件双缺口，缺口审计盯）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for power_id, script in (
        ("BG26_HERO_101p", CapnHoggarrScript),
        ("TB_BaconShop_HP_063", NozdormuScript),
        ("TB_BaconShop_HP_082", ForestWardenOmuScript),
        ("TB_BaconShop_HP_056", FungalmancerFlurglScript),
        ("TB_BaconShop_HP_066", KaelthasScript),
        ("TB_BaconShop_HP_008", TradePrinceGallywixScript),
        ("TB_BaconShop_HP_048", DinotamerBrannScript),
        ("BG22_HERO_200p", IniStormcoilScript),
        ("TB_BaconShop_HP_086", AlAkirScript),
        ("TB_BaconShop_HP_103", YshaarjScript),
        ("TB_BaconShop_HP_061", DeathwingScript),
        ("TB_BaconShop_HP_062", YseraScript),
        ("BG20_HERO_100p", RokaraScript),
        ("TB_BaconShop_HP_033", TheCuratorScript),
        ("TB_BaconShop_HP_035", PatchwerkScript),
    ):
        reg(power_id, script)
        registered.append(power_id)
    return registered
