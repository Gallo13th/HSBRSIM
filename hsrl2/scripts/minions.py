"""池随从效果脚本 — 批次 1（作业单 2026-08-21，10 张）+ 批次 1b（5 张）。

实现状态总览（详见各类 docstring）:
  OK:       BG36_509 Private Investigator / BG29_810 Thousandth Paper Drake /
            BG26_963 Electric Synthesizer / BG31_843 Meteorite Crasher /
            BG29_888 Glim Guardian / BG36_701 Kelp Keeper /
            BG30_102 One-Amalgam Tour Group / BG36_206 Snarky Shark /
            BG36_521 Locked-up Mutineer（含对应金色注册）
  DEFERRED: BG26_523 Tichondrius（HERO_DAMAGE_TAKEN 时机在战斗快照窗口内，
             详见该类 docstring——批次 1b 实验验证）
  Spellcraft 批次（首批 3/9）: OK BG23_000 Mini-Myrmidon /
             BG23_007 Waverider / BG23_008 Glowscale（含金色注册，
             法术脚本见 scripts/spells.py; 其余 6 张在批次队列）

金色模型约定（与 game.play_minion 的触发次数模型对齐）:
  - battlecry 钩子实现"每次触发的基础值"——金色打出时引擎触发 2 次，
    总额 = 2×基础值 = 金色文本总额（如 Electric Synthesizer 金色
    "+2/+2" = 2×(+1/+1)）
  - 非 battlecry 钩子（SoC/rally/deathrattle/activate/监听器）单次触发，
    金色注册类直接实现金色文本值；金色文本与基础同文仅数值差异时同一
    脚本类复用（金色 CardDef num() 自然体现）
"""

from __future__ import annotations

from hsrl2.actions import (Buff, GainGold, GainKeyword, ScheduleNextTurn,
                           TriggerBattlecry)
from hsrl2.constants import LOCKBOX_CARD_ID
from hsrl2.events import CARD_PLAYED, MINION_SOLD, Listener
from hsrl2.minion import Minion
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race, Zone

_DRAGON_RACES = (Race.DRAGON, Race.ALL)      # ALL 视为所有种族 (RULES §6.18)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_BEAST_RACES = (Race.BEAST, Race.ALL)


class PrivateInvestigatorScript:
    """
    Natural language: <b>Activate ({0}):</b> Gain {1} Gold next turn.

    Formal spec:
      1. Activate 使用时（引擎已扣 activate_cost 金并置
         ACTIVATE_USED_THIS_TURN）: 调度 GainGold(控制者, num(1)) 到
         下一个招募阶段开始执行（ScheduleNextTurn → 基础收入重置之后
         叠加，game._begin_recruit_for 顺序保证）
      2. 无实体创建；金色版数值由金色 CardDef（BG36_509_G num(1)=6）
         经 source.card_id 自然体现，同一脚本类复用

    Test: test_cards_batch1.py — 扣费 / 下回合基础收入之上 +num(1) /
    每回合一次 / 金币不足拒绝 / 金色 +6

    Params: {0}=1（activate 费用，与 activate_cost 同值） {1}=3（36.2.2 基线）
    """

    @staticmethod
    def activate(source, game, ctx):
        d = game.db.get(source.card_id)
        return ScheduleNextTurn(source.controller,
                                GainGold(source.controller, d.num(1)))


class ThousandthPaperDrakeScript:
    """
    Natural language: <b>Start of Combat:</b> Give your left-most Dragon
    +1/+2 and <b>Windfury</b>.

    Formal spec:
      1. 战斗开始时（SoC，单次触发，饰品→奖励→随从顺序由调度器保证）:
         取 source 控制者棋盘上最左侧的 Dragon（含 ALL 种族；含 source
         自身——文本无 "other"），给它 +1/+2 与 Windfury
      2. 无友方 Dragon 时不产生效果
      3. 创建: 1 个 Buff 附魔 + WINDFURY tag；战斗快照恢复 → 效果仅
         战斗内存在（RULES §3.5）

    Test: test_cards_batch1.py — 最左龙 +1/+2 且获得风怒、其余随从不变、
    无龙时无效果、战斗后回滚

    Params: 文本字面量 {0}=1 {1}=2（CardDef 无模板参数，文本原文数值）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        dragons = [m for m in source.controller.board
                   if not m.dead and m.race in _DRAGON_RACES]
        if not dragons:
            return None
        left = dragons[0]
        return [Buff(left, atk=1, health=2),
                GainKeyword(left, GameTag.WINDFURY)]


class ThousandthPaperDrakeGoldenScript:
    """
    Natural language: <b>Start of Combat:</b> Give your two left-most Dragons
    +1/+2 and <b>Windfury</b>.

    Formal spec:
      1. 同基础版，但目标为最左的**两个** Dragon（金色文本行为差异，
        36.2.2 CardDefs 金色原文）
      2. 龙不足 2 条时全给

    Test: test_cards_batch1.py — 三龙场景前两条获得效果、第三条不变

    Params: 文本字面量 {0}=1 {1}=2（金色 CardDef 文本原文数值）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        dragons = [m for m in source.controller.board
                   if not m.dead and m.race in _DRAGON_RACES]
        if not dragons:
            return None
        actions = []
        for m in dragons[:2]:
            actions.append(Buff(m, atk=1, health=2))
            actions.append(GainKeyword(m, GameTag.WINDFURY))
        return actions


class ElectricSynthesizerScript:
    """
    Natural language: <b>Battlecry and Start of Combat:</b> Give your
    other Dragons +1/+1.

    Formal spec:
      1. 打出时（battlecry，每次触发）与战斗开始时（SoC，单次触发）:
         source 控制者棋盘上除 source 外的全部 Dragon（含 ALL 种族）
         各获得 +1/+1
      2. battlecry 每次触发值 = 基础值；金色打出时引擎触发 2 次 →
        总额 +2/+2 = 金色文本总额（见模块 docstring 金色模型约定）
      3. SoC 效果战斗快照恢复 → 仅战斗内存在；battlecry buff 永久

    Test: test_cards_batch1.py — battlecry/SoC 各 buff 其他龙、不含自身、
    非龙不受影响、金色打出总额 +2/+2、Brann 叠加 2 次

    Params: 文本字面量 {0}=1 {1}=1（CardDef 无模板参数，文本原文数值）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        return [Buff(m, atk=1, health=1)
                for m in source.controller.board
                if m is not source and not m.dead
                and m.race in _DRAGON_RACES]

    @staticmethod
    def start_of_combat(source, game, ctx):
        return [Buff(m, atk=1, health=1)
                for m in source.controller.board
                if m is not source and not m.dead
                and m.race in _DRAGON_RACES]


class ElectricSynthesizerGoldenScript:
    """
    Natural language: <b>Battlecry and Start of Combat:</b> Give your
    other Dragons +2/+2.

    Formal spec:
      1. battlecry: 每次触发 +1/+1（基础值）——引擎对金色战吼触发 2 次，
        总额 = +2/+2（金色文本总额，官方金色战吼 = 2×基础触发模型）
      2. SoC: 单次触发直接给 +2/+2（金色文本值，SoC 无引擎翻倍）
      3. 目标范围同基础版: 除自身外全部友方 Dragon（含 ALL）

    Test: test_cards_batch1.py — 金色打出其他龙 +2/+2、金色 SoC +2/+2

    Params: {0}=1 {1}=1（battlecry 每次触发值 = 基础文本字面量）
            {2}=2 {3}=2（SoC 值 = 金色文本字面量）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        return [Buff(m, atk=1, health=1)
                for m in source.controller.board
                if m is not source and not m.dead
                and m.race in _DRAGON_RACES]

    @staticmethod
    def start_of_combat(source, game, ctx):
        return [Buff(m, atk=2, health=2)
                for m in source.controller.board
                if m is not source and not m.dead
                and m.race in _DRAGON_RACES]


class MeteoriteCrasherScript:
    """
    Natural language: After you sell an Elemental, gain +{0}/+{1}.

    Formal spec:
      1. 入场（on_summon）注册持久监听器（owner=source，出售/死亡/移除
         时自动注销）: 事件 "minion_sold"（game.sell_minion 在移除前
         fire，kwargs: minion=被售实体）
      2. 条件: 被出售实体是 Elemental（含 ALL 种族）且与 source 同控制者；
         出售 source 自身（其为 Elemental）同样满足——官方语义如此，
         对已离场实体加 buff 无副作用
      3. 满足时: source 获得 times 个 +num(0)/+num(1) Buff 实例
         （基础版 times=1；金色版文本 "twice" → times=2，两个独立实例）
      4. 数值在回调内经 game.db.get(source.card_id).num() 取回，
         金色注册类经金色 CardDef 自然取 +4/+4

    Test: test_cards_batch1.py — 售元素加成 / 售非元素无效果 /
    对手售元素无效果 / 金色两次共 +8/+8

    Params: {0}=4 {1}=4（36.2.2 基线，金色同值×2 次）
    """

    times = 1

    @staticmethod
    def on_summon(source, game, ctx):
        def on_sold(g, minion=None, **kw):
            d = g.db.get(source.card_id)
            n = source.scripts.times
            g.run_actions([Buff(source, atk=d.num(0), health=d.num(1))
                           for _ in range(n)])

        game.events.register(Listener(
            event=MINION_SOLD,
            owner=source,
            condition=lambda minion=None, **kw: (
                minion is not None
                and minion.race in _ELEMENTAL_RACES
                and minion.controller is source.controller),
            callback=on_sold,
        ))
        return None


class MeteoriteCrasherGoldenScript(MeteoriteCrasherScript):
    """
    Natural language: After you sell an Elemental, gain +{0}/+{1} twice.

    Formal spec:
      1. 同基础版，times=2——每次出售触发**两个独立** +num(0)/+num(1)
        buff 实例（金色文本 "twice"；数据: 金色 num(0)/num(1)=4/4，
        总额 +8/+8）
      2. 监听器注册/条件与基础版完全一致（继承）

    Test: test_cards_batch1.py — 金色售一元素得 2 个 buff 实例、+8/+8

    Params: {0}=4 {1}=4（金色 CardDef，36.2.2 基线）×2 次
    """

    times = 2


class GlimGuardianScript:
    """
    Natural language: <b>Rally:</b> Gain +{0} Attack.

    Formal spec:
      1. 攻击宣告时（rally 钩子，引擎保证先于伤害结算，RULES §6.16;
         ctx["target"] 为防守方）: source 获得 +num(0) 攻击（无生命加成）
      2. 每次攻击宣告各触发一次（风怒随从一场战斗可触发多次）
      3. 文本无 "permanent" 字样 → 战斗内生效（combat rally），战斗结束
         快照恢复（RULES §3.5）
      4. 金色版经金色 CardDef num(0)=4 自然体现，同一脚本类复用

    Test: test_cards_batch1.py — 单次攻击后 atk +num(0) 且本次攻击伤害
    已含增益（rally 先于伤害）、金色 +4

    Params: {0}=2（36.2.2 基线，金色 =4）
    """

    @staticmethod
    def rally(source, game, ctx):
        d = game.db.get(source.card_id)
        return Buff(source, atk=d.num(0))


# ══════════════════ 批次 1b（作业单 2026-08-21，依赖就绪后实现） ══════════════════


class KelpKeeperScript:
    """
    Natural language: <b>Activate ({0}):</b> Trigger a friendly minion's
    <b>Battlecry</b>.

    目标选择裁定（主线终裁 2026-08-21，证据升级）: hearthstone.wiki.gg
    官方 wiki 页 "Wiki tags" 明确将本卡归入 **[Targeted]** 分类 →
    玩家选择目标，非随机（此前"Play Dead 惯例=随机"的初裁被推翻）。
    自动化模拟的忠实建模: 产生 PendingChoice(kind="activate_target")，
    由自动化层 choice_policy 决策——而非用随机近似玩家选择。

    Formal spec:
      1. Activate 使用时（引擎已扣 num(0)=activate_cost 金并置
         ACTIVATE_USED_THIS_TURN，game.use_activate 保证）:
         候选 = 控制者棋盘上存活的 has(GameTag.BATTLECRY) 随从
      2. 候选为空 → 无效果返回 None（Activate 费用已扣——官方: 无合法
         目标时 activate 仍可按但无效果，批次 1b 作业单裁定）
      3. 否则 game.pending_choices.append(PendingChoice(
         owner, 候选, "activate_target", resolve=TriggerBattlecry(目标)))
         —— 选中目标的战吼由 TriggerBattlecry 触发（Brann 翻倍 /
         COUNTER_BATTLECRIES 计数 / BATTLECRY_TRIGGER 广播由其处理）

    Test: test_cards_batch1.py — 唯一候选触发其战吼且计数+1 / 无候选
    无效果不崩 / 金色两次 / 扣费金额

    Params: {0}=1（activate 费用，与 activate_cost 同值）
    """

    @staticmethod
    def activate(source, game, ctx):
        from hsrl2.game import PendingChoice
        from hsrl2.actions.trigger import TriggerBattlecry
        hero = source.controller
        candidates = [m for m in hero.board
                      if not m.dead and m.has(GameTag.BATTLECRY)]
        if not candidates:
            return None

        def resolve(pick):
            game.run_actions(TriggerBattlecry(pick))

        game.pending_choices.append(PendingChoice(
            hero, candidates, "activate_target", resolve_callback=resolve))
        return None


class KelpKeeperGoldenScript:
    """
    Natural language: <b>Activate ({0}):</b> Trigger a friendly minion's
    <b>Battlecry</b> twice.

    Formal spec:
      1. 候选构造与空候选处理同基础版（KelpKeeperScript spec 1-2，
         含 [Targeted] 终裁: PendingChoice 建模玩家选择）
      2. 金色 "twice" = 选定目标的战吼触发 2 次（单一选择，
         该目标战吼 ×2; 与 Brann 叠加则每次触发再翻倍——
         TriggerBattlecry 内部处理，总计可达 4 次）

    Test: test_cards_batch1.py — 金色两次触发（唯一候选 → 2×战吼值）、
    COUNTER_BATTLECRIES == 2

    Params: {0}=1（金色 activate 费用，与 activate_cost 同值）
    """

    @staticmethod
    def activate(source, game, ctx):
        from hsrl2.game import PendingChoice
        from hsrl2.actions.trigger import TriggerBattlecry
        hero = source.controller
        candidates = [m for m in hero.board
                      if not m.dead and m.has(GameTag.BATTLECRY)]
        if not candidates:
            return None

        def resolve(pick):
            game.run_actions([TriggerBattlecry(pick), TriggerBattlecry(pick)])

        game.pending_choices.append(PendingChoice(
            hero, candidates, "activate_target", resolve_callback=resolve))
        return None


class OneAmalgamTourGroupScript:
    """
    Natural language: Whenever you play a card, give friendly minions of its
    Tier or lower +{0}/+{1}.

    Formal spec:
      1. 入场（on_summon）注册持久监听器（owner=source，出售/死亡自动
         注销）: 事件 "card_played"（play_minion game.py / play_spell
         game.py 均已 fire，kwargs card=被打出的实体）
      2. 条件: card.controller is source.controller（对手打出不触发）
      3. "its Tier" = game.db.get(card.card_id).tech_level。数据核实
         2026-08-21（批次 1b）: 酒馆法术在 CardDefs 同样带 tech_level
         1-7（如 Shiny Ring T3 / Sacred Gift T7），法术的 Tier 语义
         良定义——打出法术同样触发，按法术 tier 筛选; 未知卡定义
         （db 缺失）不触发
      4. 触发: source 控制者棋盘上 tech_level ≤ 该 Tier 的存活随从各获
         +num(0)/+num(1) 永久 Buff。打出随从时其已在棋盘（summon 先于
         card_played fire）且 tier 等于自身 → 打出者自身达标受 buff;
         Tour Group 自身 Tier 6，打出 Tier ≥ 6 的卡时同样达标（含自身，
         文本无 "other"）
      5. 金色版文本同构仅数值差异（金色 num(0)/num(1)=4/2）→ 同一
         脚本类复用，数值经金色 CardDef 自然体现

    Test: test_cards_batch1.py — 打出随从按其 tier 加成且打出者自身
    达标 / 打出法术按法术 tier / 高 tier 随从不达标 / 对手打出无
    效果 / 金色 +4/+2

    Params: {0}=2 {1}=1（36.2.2 基线，金色 4/2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            if card is None:
                return
            played_def = g.db.get(card.card_id)
            if played_def is None:
                return
            tier = played_def.tech_level
            d = g.db.get(source.card_id)
            g.run_actions([
                Buff(m, atk=d.num(0), health=d.num(1))
                for m in source.controller.board
                if not m.dead and m.tech_level <= tier])

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            condition=lambda card=None, **kw: (
                card is not None
                and card.controller is source.controller),
            callback=on_played,
        ))
        return None


class SnarkySharkScript:
    """
    Natural language: When you sell this, <b>Refresh</b> the Tavern with a
    Fishbait. Your left-most Beast attacks it.

    Formal spec:
      1. 出售时（on_sell，引擎在移除/回池前调用 game.sell_minion），
         依次:
         a) 免费刷新酒馆: game.refresh_tavern(hero, auto=False,
            free=True)——效果刷新，不耗金币不耗免费刷新次数; 旧内容
            回池由 refresh_tavern 保证 (P1)
         b) Fishbait 替换: fishbait = create_minion(由 source 的
            CardDef.evolution_card_id 数据链解析——BG36_206→BG36_205、
            金色 BG36_206_G→BG36_205_G，无硬编码卡 id); 随机替换
            hero.tavern 中一张 Minion（被替换者 zone=REMOVED 并
            minion_pool.release(card_id, 1) 回池——"被替换=未购买→
            回池"，批次 1b 作业单裁定）; 酒馆内无随从（池耗尽退化
            场景）则直接 append，Fishbait 必须在场以支撑后续攻击机制
         c) 最左 Beast 攻击: 候选 = hero.board 上 race ∈ (BEAST, ALL)
            的存活随从，**排除 source 自身**（on_sell 时 source 尚未
            从棋盘移除，但官方语义中被售出者已不属于 "Your" 棋盘——
            无野兽则不攻击）取最左; 无候选 → 不攻击，Fishbait 留在
            酒馆（官方行为）
         d) game.recruit_phase_attack(beast, fishbait)——双向同时伤害 /
            KILLER 设置 / Fishbait 亡语（"Give the minion that killed
            this +5/+5"，由其自身脚本负责，本批次未含）/ 死亡从酒馆
            移除不回池，均由该 API 保证
      2. 金色版 "a Golden Fishbait" = BG36_205_G（+10/+10 亡语），经
         金色数据链自动取到，单次攻击不变 → 同一脚本类复用

    Test: test_cards_batch1.py — 免费刷新且 Fishbait 在酒馆 / 无野兽
    （含仅已售鲨鱼）时 Fishbait 留酒馆不崩 / 攻击者=最左非已售野兽且
    KILLER 正确 / 金色出金色 Fishbait

    Params: 无模板参数（Fishbait 卡 id 经 evolution_card_id 数据链解析）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        # (a) 效果刷新（免费）
        game.refresh_tavern(hero, auto=False, free=True)
        # (b) Fishbait 替换酒馆中一张随机随从（被替换者回池）
        d = game.db.get(source.card_id)
        fishbait = game.create_minion(
            game.db.by_dbf(d.evolution_card_id).id, controller=hero)
        fishbait.zone = Zone.TAVERN
        victims = [e for e in hero.tavern if isinstance(e, Minion)]
        if victims:
            victim = game.rng.choice(victims, label="snarky_shark_replace")
            hero.tavern[hero.tavern.index(victim)] = fishbait
            victim.zone = Zone.REMOVED
            game.minion_pool.release(victim.card_id, 1)
        else:
            hero.tavern.append(fishbait)
        # (c)+(d) 最左 Beast（排除已售 source）攻击 Fishbait；无则不攻击
        beasts = [m for m in hero.board
                  if m is not source and not m.dead
                  and m.race in _BEAST_RACES]
        if beasts:
            game.recruit_phase_attack(beasts[0], fishbait)
        return None


class LockedUpMutineerScript:
    """
    Natural language: <b>Deathrattle:</b> Get a Lockbox. If you already have
    one, it opens {0} turn(s) sooner instead.

    Formal spec:
      1. 死亡时（deathrattle，先于复生——引擎 C6 顺序）:
         分支 A（手牌已有 Lockbox，即 card_id == LOCKBOX_CARD_ID）:
         game.open_lockbox_early(hero, num(0))——已有 Lockbox 倒计时
         提前 num(0) 回合，归零即开（随机有种族金色随从入手、池扣减
         min(3, 剩余) 份——game._open_lockbox 保证）
         分支 B（手牌无 Lockbox）: Get = game.create_spell(
         LOCKBOX_CARD_ID)（LOCKBOX_TURNS_LEFT 初始 = Lockbox CardDef
         num(0)=5，create_spell 保证）+ game.pending_hand_add（满手
         排队等待，RULES §3.3——禁止直接 append，P6）
      2. 广播锚点 source.controller（死亡时 source 已 GRAVEYARD，
         经验库 2026-08-21）
      3. 金色版文本同构仅数值差异（金色 num(0)=2，提前 2 回合）→
         同一脚本类复用，数值经金色 CardDef 自然体现

    Test: test_cards_batch1.py — 无 Lockbox 时入手且倒计时 = Lockbox
    num(0) / 已有 Lockbox 走 early 路径倒计时 -num(0) 未归零仍在手 /
    金色 -2

    Params: {0}=1（36.2.2 基线，金色 =2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        if any(card.card_id == LOCKBOX_CARD_ID for card in hero.hand):
            game.open_lockbox_early(hero, d.num(0))
            return None
        lockbox = game.create_spell(LOCKBOX_CARD_ID, controller=hero)
        game.pending_hand_add(hero, lockbox)
        return None


# ══════════════════ 以下为 DEFERRED（不注册 REGISTRY） ══════════════════


class TichondriusScript:
    """
    Natural language: After your hero takes damage, give your Demons +{0}/+{1}.

    Status: CORRECT — 依赖已由主线修复 (2026-08-21):
      1. Hero.take_damage fire HERO_DAMAGE_TAKEN（护甲吸收也触发——
         官方 Floating Watcher 语义）
      2. run_combat 的 loser.take_damage 已移至快照恢复**之后** →
         触发时败方棋盘已复原（战斗死亡不延续），buff 正确跨回合保留
      3. 事件监听器表随战斗快照恢复 → 战斗中死亡不会注销持久触发器

    Formal spec:
      1. on_summon 注册 Listener(event=HERO_DAMAGE_TAKEN, owner=source)
      2. condition: kw["hero"] is source.controller
      3. 回调: 对每个友方存活 Demon（race == DEMON 或 ALL）Buff
         (+num(0)/+num(1))
      4. 每次受伤触发一次（多次受伤多次触发，官方语义）

    Test: test_cards_batch1.py::TestTichondrius — 受伤触发/恶魔+ALL
    过滤/多次受伤叠加

    Params: {0}=3 {1}=3（36.2.2 基线，金色 6/6 经金色 CardDef 体现）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        from hsrl2.actions.stats import Buff
        from hsrl2.events import Listener
        d = game.db.get(source.card_id)

        def on_hero_damaged(g, hero=None, amount=0, **kw):
            if hero is not source.controller:
                return
            buffs = [Buff(m, atk=d.num(0), health=d.num(1))
                     for m in source.controller.board
                     if not m.dead and m.race in (Race.DEMON, Race.ALL)]
            g.run_actions(buffs)

        game.events.register(Listener(
            event="hero_damage_taken", owner=source,
            callback=on_hero_damaged))
        return None


# ══════════════════ Spellcraft 批次（2026-08-21 作业单，首批 3/9） ══════════════════
#
# 引擎缺口（本批次自举，报告主线）: game.create_minion 未从
# CardDef.spellcraft_id 映射 SPELLCRAFT tag（_KEYWORD_TAG_MAP 无
# spellcraft 项）——由各 on_summon 显式 set(GameTag.SPELLCRAFT) 自举。
# generate_for_hero 依赖该 tag 识别棋盘 Spellcraft 随从。


class _SpellcraftMinionMixin:
    """Spellcraft 随从公共 on_summon: tag 自举 + 打出/召唤立即获得
    第一张法术（RULES §6.13）。法术身份由 CardDef.spellcraft_id
    决定（金色随从是独立卡定义 → 金色法术），各类仅差 docstring。"""

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.SPELLCRAFT, True)   # 引擎缺口自举（见上注）
        grant_spellcraft_spell(source, game)
        return None


class MiniMyrmidonScript(_SpellcraftMinionMixin):
    """
    Natural language: <b>Spellcraft:</b> Give a minion +2 Attack until
    next turn.

    Formal spec:
      1. on_summon（打出/召唤入场）: SPELLCRAFT tag 自举（引擎缺口，
         create_minion 应从 CardDef.spellcraft_id 映射）+ 立即获得
         第一张法术 BG23_000t（金色随从 BG23_000_G → BG23_000_Gt，
         grant_spellcraft_spell 按 card_id 的 spellcraft_id 解析）
      2. 后续每招募阶段开始由 spellcraft.generate_for_hero 生成
         （读 SPELLCRAFT tag，本 on_summon 已保证）
      3. 战斗中召唤的 Spellcraft 随从同样立即给法术（满手排队，
         pending_hand_add）

    Test: test_spellcraft.py — 打出立即获得法术（tag+source_uuid）/
    金色随从给金色法术 / 下一回合 generate 再给一张

    Params: 法术侧 {0}=2（+2 Attack，法术脚本 BG23_000t 声明）
    """


class WaveriderScript(_SpellcraftMinionMixin):
    """
    Natural language: [x]<b>Spellcraft:</b> Give a minion +{0}/+{1}.
    If it's a Naga, also give it <b>Windfury</b> until next turn.

    Formal spec:
      1. 同 MiniMyrmidon: tag 自举 + 立即获得法术 BG23_007t
         （金色 BG23_007_G → BG23_007_Gt +4/+4）
      2. 法术效果本体见 scripts/spells.py WaveriderSpellScript
         （temporary buff + Naga 临时风怒 + 下回合开始过期）

    Test: test_spellcraft.py — 打出立即获得法术 / 法术效果与过期
    （临时风怒路径）

    Params: 法术侧 {0}=2 {1}=2（法术脚本 BG23_007t 声明）
    """


class GlowscaleScript(_SpellcraftMinionMixin):
    """
    Natural language: <b>Taunt</b> <b>Spellcraft:</b> Give a minion
    <b>Divine Shield</b> until next turn.

    Formal spec:
      1. 同 MiniMyrmidon: tag 自举 + 立即获得法术 BG23_008t
         （金色 BG23_008_G → BG23_008_Gt，同文——DS 无数值差异）
      2. Taunt 由 create_minion 关键词映射（_KEYWORD_TAG_MAP 有项）
      3. 法术效果本体见 scripts/spells.py GlowscaleSpellScript
         （临时圣盾 + 下回合开始过期）

    Test: test_spellcraft.py — 打出立即获得法术 / Taunt tag 在场 /
    法术效果与过期（临时圣盾路径）

    Params: 法术侧无数值参数
    """
