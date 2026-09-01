"""批次 rally — 10 张 Rally 机制池随从（作业单 2026-08-21）。

覆盖: BG25_016 Sin'dorei Straight Shot / BG27_017 Obsidian Ravager /
BG33_318 Bile Spitter / BG33_323 Dustbone Devastator / BG33_822 Bigwig
Bandit / BG33_886 Tusked Camper / BG33_924 Blue Whelp / BG34_140 Expert
Aviator / BG34_319 Highkeeper Ra / BG34_320 The Last One Standing
（含金色 id; 金色=独立卡定义）。

共性语义（RULES §6.16）: Rally 在攻击宣告时、伤害结算前触发，
ctx={"target": 防守方}（CombatScheduler._execute_attack 与招募期攻击
game.recruit_phase_attack 均保证）。经验库: ctx["target"] 触发时保证
存活，无需 dead 检查。文本无 "permanent" 的战斗内效果经引擎快照恢复
战后回滚（RULES §3.5）; "this game" 效果落在 hero 级持久状态。

金色关键词数据缺口（报告主线，非本批次可修）: generate_bg_data.py
仅对 IS_BACON_POOL_MINION 实体导出关键词标志 → 金色定义（XML 上
WINDFURY/DIVINE_SHIELD/VENOMOUS/BACON_RALLY 均在）在 data/*.json
不携带关键词 → 金色实体缺 DS/Windfury/Venomous tag。Rally 本身经
card_id→REGISTRY 脚本绑定不受影响。
"""

from __future__ import annotations

from hsrl2.actions import (
    Buff,
    GainKeyword,
    GetRandomMinion,
    Hit,
    LoseKeyword,
    ScheduleNextTurn,
)
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.events import TURN_START, Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

# BG 全部标准种族（The Last One Standing "of each type" 枚举;
# 不含 NONE/ALL/INVALID——ALL 随从经候选匹配覆盖全部种族）
ALL_BG_RACES = (
    Race.UNDEAD, Race.MURLOC, Race.DEMON, Race.MECH, Race.ELEMENTAL,
    Race.BEAST, Race.PIRATE, Race.DRAGON, Race.QUILBOAR, Race.NAGA,
)

# Bounty 池（身份标识非数值——bloodgem.BLOOD_GEM_VARIANTS 先例）。
# data 36.2.2 核对: XML BACON_BOUNTY tag(4231)=1 且 CARDTYPE=42 的
# 全部法术。引擎缺口: 生成器未导出 BACON_BOUNTY → 硬编码 + 漂移
# 守护测试（test_batch_rally.py 对照 hsdata/CardDefs.xml）。
BOUNTY_SPELL_IDS = frozenset({
    "BG33_811",   # Healthy Bounty
    "BG33_812",   # Hostile Bounty
    "BG33_813",   # Selfish Bounty
    "BG33_814",   # Friendly Bounty
    "BG33_815",   # Wealthy Bounty
})


def _rally_target(ctx):
    return (ctx or {}).get("target")


def _board_neighbors(target) -> list:
    """target 在棋盘上的存活相邻随从（±1 位）。target 不在棋盘
    （招募期攻击的酒馆区目标）→ 空——酒馆区无相邻语义（与引擎
    recruit_phase_attack 同裁。依据 2026-08-23 查证: Snarky Shark
    卡页 Wiki mechanics [Force attack]，Force attack 机制页 Notes
    仅覆盖攻击次数消耗/召唤失调/重定向（hearthstone.wiki.gg/wiki/
    Force_attack#Notes），对酒馆区目标的顺劈/相邻无记载; 卡页无
    Notes——按"无相邻语义仅命中本体"实现，引擎层读法）。"""
    hero = getattr(target, "controller", None)
    board = hero.board if hero is not None else []
    if target not in board:
        return []
    pos = target.zone_position
    return [m for m in board
            if m is not target and not m.dead
            and abs(m.zone_position - pos) == 1]


class SindoreiStraightShotScript:
    """
    Natural language: [x]<b>Divine Shield</b>, <b>Windfury</b>
    <b>Rally:</b> Remove <b>Reborn</b> and
     <b>Taunt</b> from the target.（金色同文）

    Formal spec:
      1. rally（攻击宣告时、伤害前）: ctx["target"] 失去 Reborn 与
         Taunt——各自**仅在目标持有时** LoseKeyword（引擎 clear 对
         缺失 tag 安全，但 LoseKeyword 会 fire KEYWORD_LOST——
         对未持有的关键词 fire 事件属语义错误，故 has() 前置）
      2. DS/Windfury 由 create_minion 关键词映射（data 权威标签）
      3. 无新实体; 招募期攻击场景（target=酒馆区实体）同样仅做
         tag 移除
      4. 金色文本与基础版相同 → 同一脚本类注册两个 id

    Test: test_batch_rally.py — 攻击后目标 Reborn/Taunt 双移除 /
    目标无关键词时不产生 KEYWORD_LOST 事件 / 自身 DS+Windfury 在场

    Params: 无数值参数（文本无占位符）
    """

    @staticmethod
    def rally(source, game, ctx):
        target = _rally_target(ctx)
        if target is None:
            return None
        actions = []
        for tag in (GameTag.REBORN, GameTag.TAUNT):
            if target.has(tag):
                actions.append(LoseKeyword(target, tag))
        return actions or None


class ObsidianRavagerScript:
    """
    Natural language: [x]<b>Rally:</b> Deal damage equal
    to this minion's Attack to
    the target and an adjacent
    minion.

    Formal spec:
      1. rally（伤害前）: 以 source.atk 快照为伤害值，构成**独立
         伤害实例**（Hit，走圣盾/死亡结算）:
         a) Hit(target, dmg, source)
         b) Hit(target 的一个随机存活相邻随从, dmg, source)——
            相邻 = 同棋盘 zone_position ±1; 无相邻 → 仅 a)
      2. 攻击本体伤害随后另行结算（引擎 _execute_attack）——目标
         承受 rally 伤害 + 攻击伤害两实例; rally Hit 致死则触发
         亡语/复生后才轮到攻击伤害（take_damage 对 dead 返回 0）
      3. 招募期攻击场景: target 不在棋盘 → 无相邻语义，仅命中
         目标（引擎同裁——_board_neighbors docstring Evidence:
         Force attack 机制页/卡页均无酒馆区相邻记载，2026-08-23 查证）
      4. 伤害值来自 source.atk（含光环/rally 增益实时值），无模板
         参数

    Test: test_batch_rally.py — 目标受 rally+攻击双份伤害、单个
    相邻受 rally 伤害 / 无相邻仅目标 / 金色双邻全中

    Params: 无数值参数（伤害 = source.atk 运行时值）
    """

    @staticmethod
    def rally(source, game, ctx):
        target = _rally_target(ctx)
        if target is None:
            return None
        dmg = source.atk
        actions = [Hit(target, dmg, source)]
        neighbors = _board_neighbors(target)
        if neighbors:
            pick = game.rng.choice(neighbors, label="ravager_adjacent")
            actions.append(Hit(pick, dmg, source))
        return actions


class ObsidianRavagerGoldenScript(ObsidianRavagerScript):
    """
    Natural language: [x]<b>Rally:</b> Deal damage equal
    to this minion's Attack to
    the target and its
    neighbors.

    Formal spec: 同基础版，但 b) 为 target 的**全部**存活相邻随从
    （"its neighbors" 复数——左右各一，逐个 Hit 同值伤害实例）。

    Test: test_batch_rally.py — 金色左右两邻均受 rally 伤害

    Params: 无数值参数（伤害 = source.atk 运行时值）
    """

    @staticmethod
    def rally(source, game, ctx):
        target = _rally_target(ctx)
        if target is None:
            return None
        dmg = source.atk
        actions = [Hit(target, dmg, source)]
        actions.extend(Hit(n, dmg, source)
                       for n in _board_neighbors(target))
        return actions


class BileSpitterScript:
    """
    Natural language: [x]<b>Venomous</b>
    <b>Rally:</b> Give another friendly
    Murloc <b>Venomous</b>.

    Formal spec:
      1. rally: 候选 = 同棋盘（source.controller.board）存活、
         **非 source**（文本 "another"）、race ∈ (MURLOC, ALL)
         的随从; 无候选 → 落空返回 None
      2. GainKeyword(候选[随机], VENOMOUS)——不设
         VENOMOUS_CONSUMED（ Venomous S14 每场重置语义:
         reset_for_combat 战斗开始清除; 战斗中新获 Venomous
         本场即生效）
      3. 战斗内授予的 VENOMOUS 经引擎快照恢复战后回滚
         （RULES §3.5——文本无 "permanent"）
      4. 自身 Venomous 由 create_minion 关键词映射（data 权威）

    Test: test_batch_rally.py — 攻击后另一 Murloc 获 Venomous /
    无候选落空 / ALL 种族合格 / 战后回滚 / 金色 2 只

    Params: 无数值参数
    """

    times = 1   # 金色 "2 other friendly Murlocs" → 2（文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        candidates = [m for m in hero.board
                      if m is not source and not m.dead
                      and m.race in (Race.MURLOC, Race.ALL)]
        if not candidates:
            return None
        n = min(source.scripts.times, len(candidates))
        picks = (candidates if n == len(candidates)
                 else game.rng.sample(candidates, n,
                                      label="bile_spitter_murlocs"))
        return [GainKeyword(m, GameTag.VENOMOUS) for m in picks]


class BileSpitterGoldenScript(BileSpitterScript):
    """
    Natural language: [x]<b>Venomous</b>
    <b>Rally:</b> Give 2 other friendly
    Murlocs <b>Venomous</b>.

    Formal spec: 同基础版，times=2——rng.sample 抽 **2 个不同**
    Murloc（候选仅 1 只时给 1 只，官方"最多"语义）。

    Test: test_batch_rally.py — 金色 2 只 Murloc 各获 Venomous

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    times = 2


class DustboneDevastatorScript:
    """
    Natural language: <b>Rally:</b> Your Undead have
    +{0} Attack this game <i>(wherever they are).</i>

    Formal spec:
      1. rally: ApplyRaceAura(hero, Race.UNDEAD, num(0), 0)——叠加式
         永久光环（"this game"; 每次 Rally 触发各叠加一次）
      2. "wherever they are": 经 Minion._aura_atk 对棋盘/手牌/未来
         获得的全部 UNDEAD（含 ALL）实时生效
      3. 光环即时生效 → 本次攻击伤害已含 +num(0)（rally 先于伤害，
         RULES §6.16）; hero.race_auras 不在战斗快照内 → 战后保留
      4. 金色版文本同构（num(0)=2）→ 同一脚本类注册两个 id

    Test: test_batch_rally.py — 攻击伤害含增益 / 手牌 Undead 同享 /
    非 Undead 不受 / 战后保留 / 金色 +2

    Params: {0}=1（36.2.2 基线，金色 =2）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        return ApplyRaceAura(hero, Race.UNDEAD, d.num(0), 0,
                             source_id=source.card_id)


class BigwigBanditScript:
    """
    Natural language: [x]<b>Rally:</b> Get a random <b>Bounty</b>.

    Formal spec:
      1. rally: 从 BOUNTY_SPELL_IDS（= XML BACON_BOUNTY 法术全集，
         5 张）中随机 Get 一张进手牌（pending_hand_add，满手排队
         RULES §3.3）
      2. 占池: 候选限定 spell_pool.available > 0，选中 acquire
         （Bounty 是 IS_BACON_POOL_SPELL 池法术，RULES §2.3）;
         池内 Bounty 全部耗尽 → 退化为不占池生成（dark gift
         Mystic Essence 作业单同约定先例）
      3. Bounty 法术本体效果（Healthy/Hostile/... on_play）不在
         本批次范围（法术批次另行迁移）
      4. 招募期攻击同样触发（rally 钩子统一）

    Test: test_batch_rally.py — 攻击后手牌 +1 Bounty 且占池 /
    池耗尽回退不崩 / BOUNTY_SPELL_IDS 与 XML BACON_BOUNTY 集合
    一致（漂移守护）/ 金色 2 张不同

    Params: 无数值参数（"a random"=1 为文本语义）
    """

    times = 1   # 金色 "2 random Bounties" → 2（文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        count = source.scripts.times
        ordered = sorted(BOUNTY_SPELL_IDS)
        available = [cid for cid in ordered
                     if game.spell_pool.available(cid) > 0]
        if available:
            k = min(count, len(available))
            picks = game.rng.sample(available, k, label="bounty_picks")
            for cid in picks:
                if not game.spell_pool.acquire(cid):
                    from hsrl2.game import GameStateError
                    raise GameStateError(
                        f"Bigwig Bandit: bounty acquire failed {cid}")
        else:
            picks = [game.rng.choice(ordered, label="bounty_fallback")
                     for _ in range(count)]
        for cid in picks:
            game.pending_hand_add(hero,
                                  game.create_spell(cid, controller=hero))
        return None


class BigwigBanditGoldenScript(BigwigBanditScript):
    """
    Natural language: <b>Rally:</b> Get 2 random <b>Bounties</b>.

    Formal spec: 同基础版，times=2——池法术每张 1 份 → rng.sample
    抽 2 张**不同** Bounty（可用量不足时给 min(2, 可用量) 张）。

    Test: test_batch_rally.py — 金色一次获得 2 张不同 Bounty

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    times = 2


class TuskedCamperScript:
    """
    Natural language: [x]<b>Rally:</b> This plays a <b>Blood
    Gem</b> on itself.

    Formal spec:
      1. rally: PlayBloodGems(source, times)——"This plays ... on
         itself" → 目标=source 自身，source 仅为来源追溯
      2. PlayBloodGems 语义: 不经手牌不耗金币，直接施加 times 次
         vanilla 宝石 buff（每颗 +BG20_GEM.num(0)/+num(1) +
         hero BLOOD_GEM_BONUS_ATK/HEALTH，Quilboar 体系联动）
      3. 战斗内 buff 战后回滚（RULES §3.5——文本无 "permanent";
         对比 Razorfen Vineweaver BG33_883 "permanent" 才持久）

    Test: test_batch_rally.py — 攻击后自身 +宝石值 / hero 宝石
    增强生效 / 金色 2 颗

    Params: 无数值参数（宝石基础值唯一来源 BG20_GEM CardDef）
    """

    times = 1   # 金色 "2 Blood Gems" → 2（文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        return PlayBloodGems(source, source.scripts.times, source)


class TuskedCamperGoldenScript(TuskedCamperScript):
    """
    Natural language: [x]<b>Rally:</b> This plays 2 <b>Blood
    Gems</b> on itself.

    Formal spec: 同基础版，times=2。

    Test: test_batch_rally.py — 金色自身 +2 颗宝石值

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    times = 2


class BlueWhelpScript:
    """
    Natural language: <b>Rally:</b> Your Tavern spells give an
    extra +{0} Health this game.

    Formal spec:
      1. rally: hero.TAVERN_SPELL_EXTRA_HEALTH 叠加 num(0)
         （"this game" 永久; 每次 Rally 触发各叠加一次——hero tag
         不在战斗快照内，战后保留）
      2. 生效点: racefx.tavern_spell_buff() 是酒馆法术 buff 统一
         出口，读该 tag 叠加（对新施放的全部酒馆法术生效）
      3. 金色版文本同构（num(0)=2）→ 同一脚本类注册两个 id

    Test: test_batch_rally.py — 攻击后 tag +num(0) / 叠加 /
    tavern_spell_buff 集成生效 / 金色 +2

    Params: {0}=1（36.2.2 基线，金色 =2）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
                 + d.num(0))
        return None


def _expire_combat_copy(game, copy: Minion) -> None:
    """招募期攻击场景的战斗副本到期清理（Expert Aviator 专用）。

    战斗中召唤的副本由引擎 board_before 恢复自然移除（不在战前
    棋盘快照内）; 招募期召唤的副本会被计入下一次战斗的快照、
    战后复活滞留——故注册 TURN_START once 监听器在**参与一场
    战斗后的下一个招募回合开始**时移除（owner=copy，副本被售出
    时自动注销）。引擎缺口注: 无公开 RemoveFromBoard API，
    借用 game._update_positions 维持 zone_position 连续。"""

    def expire(g, hero=None, **kw):
        if hero is not None and copy in hero.board:
            hero.board.remove(copy)
            g._update_positions(hero)
        copy.zone = Zone.REMOVED

    game.events.register(Listener(
        event=TURN_START,
        owner=copy,
        once=True,
        condition=lambda hero=None, **kw: hero is copy.controller,
        callback=expire,
    ))


class ExpertAviatorScript:
    """
    Natural language: [x]<b>Rally:</b> Summon the highest-
    Attack minion from your
    __hand for this combat only.

    Formal spec:
      1. rally: 重复 num(0) 次（基础 1; 金色 "the 2 highest-Attack
         minions" → 2——CardDef script_data_num_1 基线 1/2 与文本
         一致，{0} 语义=召唤数量; 同一次 Rally 内**不重复选取同一
         手牌实体**——"the 2 highest-Attack minions" = 攻击降序
         前 2 个不同手牌随从）:
         a) 候选 = hero.hand 中全部存活 Minion（法术不参与），排除
            本次 Rally 已选取者; 无候选或棋盘已满（board_full
            预检 + game.summon 的 MINION_OVERFLOW 双保险）→
            效果失败，不召唤（作业单裁定: 官方"满板失败"语义）
         b) 取 atk 最大者（并列 rng.choice 任选）
         c) 召唤**战斗副本**（"for this combat only"）:
            create_minion(同 card_id, golden 同源) +
            restore_state(手牌实体快照)——复制当前攻/血/buff 后
            game.summon 到棋盘最右
      2. **手牌实体不离手**（副本模型）: 战斗中无任何手牌交互 →
         可观测行为与官方"借出、战后归还"等价; 副本战死照常触发
         亡语（官方: 它确实在场作战），战后随引擎 board 恢复消失，
         战斗中获得的变化不延续（RULES §3.5）
      3. 招募期攻击（S14 Fishbait）场景: 副本经下一次战斗的快照
         复活会滞留 → _expire_combat_copy 在其后首个招募回合
         开始时移除（"for this combat only" 界定副本寿命至多
         一场战斗）
       4. 副本战斗中获得的增益不随归还延续（副本战后消失、手牌原件
          不动）。Evidence（2026-08-23 查证， resolves 原裁定）:
          wiki.gg/wiki/Battlegrounds/Temporary_summon——"Cards that
          are temporarily summoned are **copied** from the hand for
          that Combat only, **while the original copy remains in the
          hand**"（官方机制页; 复制语义 = 原件不被战斗内变化触及）

    Test: test_batch_rally.py — 最高攻手牌随从入场且手牌保留 /
    空手牌落空 / 满板不召唤 / 战后副本消失（combat_summon_log
    留痕）/ 金色召唤两张

    Params: {0}=1 {1}=1（{0}=召唤数量，金色 =2; {1} 官方未公布
    用途，未使用）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        n = d.num(0)
        if n is None:
            n = 1   # 文本无占位符兜底（"the highest-Attack minion" 单数）
        picked_origins: list[Minion] = []
        for _ in range(n):
            if hero.board_full():
                break
            hand_minions = [c for c in hero.hand
                            if isinstance(c, Minion) and not c.dead
                            and c not in picked_origins]
            if not hand_minions:
                break
            top = max(m.atk for m in hand_minions)
            cands = [m for m in hand_minions if m.atk == top]
            origin = game.rng.choice(cands, label="aviator_hand_pick")
            picked_origins.append(origin)
            copy = game.create_minion(origin.card_id, controller=hero,
                                      golden=origin.is_golden)
            copy.restore_state(origin.snapshot_state())
            if game.summon(hero, copy) and not game.in_combat:
                _expire_combat_copy(game, copy)
        return None


class HighkeeperRaScript:
    """
    Natural language: <b>Battlecry, Deathrattle, and Rally:</b> Get a
    random Tier 6 minion.

    Formal spec:
      1. battlecry/rally: GetRandomMinion(hero, min_tier=6, max_tier=6)
         ——池感知（available 闸门 + acquire 占池 RULES §2.3）、
         满手 pending_hand_add 排队、无候选（T6 池耗尽）落空
      2. battlecry 单 Action 返回——金色触发 ×2 由引擎
         _run_play_effects 统一处理（金色战吼模型，勿在脚本内
         重复翻倍）
      3. deathrattle **直接应用**（Action.do(game)，不经
         run_actions/队列）并返回 None——绕开引擎重入 bug:
         _process_single_death 先触发亡语后置 zone=GRAVEYARD，
         亡语经队列解析会嵌套 check_deaths 把仍在 PLAY 的同一
         随从二次死亡结算（亡语×2 / "death" 事件×2 / 招募期
         回池×2 / graveyard 重复 append）。ENGINE_BUG 报告主线;
         GetRandomMinion.do 无致死副作用，直接应用语义等价且
         引擎修复前后行为一致
      4. deathrattle 战斗/招募期死亡均触发（引擎 run_script_hook
         统一路径）; 战斗中获得进手牌不受快照影响

    Test: test_batch_rally.py — 战吼/亡语/Rally 三路径各 +1 张
    T6 随从且占池 / 金色三路径 ×2

    Params: 无数值参数（Tier 6 为文本字面量——等级非模板参数）
    """

    times = 1   # 金色 "two random Tier 6 minions" → 2（文本字面量）

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GetRandomMinion(hero, min_tier=6, max_tier=6)

    rally = battlecry

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(source.scripts.times):
            GetRandomMinion(hero, min_tier=6, max_tier=6).do(game)
        return None


class HighkeeperRaGoldenScript(HighkeeperRaScript):
    """
    Natural language: [x]<b>Battlecry, Deathrattle, and
    Rally:</b> Get two random
    Tier 6 minions.

    Formal spec:
      1. deathrattle times=2（两次独立直接应用——"two random"，
         受池剩余量约束，可相同可不同）
      2. rally 返回 2 个独立 GetRandomMinion Action（rally 路径
         无重入暴露——其 Action 解析不在 _process_single_death
         内层）
      3. battlecry 继承单 Action（引擎对 GOLDEN 战吼触发 2 次 →
         总额 2 张，勿叠加翻倍）

    Test: test_batch_rally.py — 金色亡语/Rally 各 +2 张 T6

    Params: 无数值参数（"two" 为金色文本字面量）
    """

    times = 2

    @staticmethod
    def rally(source, game, ctx):
        return [HighkeeperRaScript.battlecry(source, game, ctx),
                HighkeeperRaScript.battlecry(source, game, ctx)]


class TheLastOneStandingScript:
    """
    Natural language: <b>Rally:</b> Give a friendly minion of
    each type +{0}/+{1} permanently.

    Formal spec:
      1. rally: 对每个标准种族 r ∈ ALL_BG_RACES（10 种）:
         候选 = 同棋盘存活、**非 source**（v1 先例 + 基数 sanity:
         source 为 ALL 种族，含自身则其包揽全部种族选取）、
         race ∈ (r, ALL) 的随从; 有候选 → rng.choice 一个目标
      2. "permanently" 路径分流（引擎快照恢复会回滚战斗内 buff
         ——RULES §3.5 默认，文本 "permanently" 明确覆盖）:
         a) 立即 Buff(+num(0), +num(1))——两种路径都本场生效
         b) 战斗路径（game.in_combat）额外 ScheduleNextTurn 同值
            Buff——快照回滚后在下一招募回合开始重放
            （deferred_actions 在金币重置后执行），净效果=永久;
            招募期攻击路径无回滚，跳过 b)（否则双份=2× 文本值）
         两次之间（战斗结束→下回合开始）无玩家可观测窗口，
         语义等价于"单次永久施加"
      3. ALL 种族随从是每个种族的合格候选——可被多个种族的
         选取各自命中（每命中一次一份 buff，官方 Amalgam 语义）
      4. 无任何种族有候选（如 source 单独在场）→ 落空

    Test: test_batch_rally.py — 每种族各 +num(0)/num(1)、自身
    排除 / 单独在场落空 / ALL 随从覆盖全部种族 / run_combat 后
    buff 持久 / 金色两轮

    Params: {0}=15 {1}=15（36.2.2 基线，金色同值两轮）
    """

    passes = 1   # 金色 "...permanently, twice." → 2 轮

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        actions = []
        for _ in range(source.scripts.passes):
            for race in ALL_BG_RACES:
                cands = [m for m in hero.board
                         if m is not source and not m.dead
                         and m.race in (race, Race.ALL)]
                if not cands:
                    continue
                pick = game.rng.choice(cands,
                                       label="last_one_standing_pick")
                actions.append(Buff(pick, atk=d.num(0),
                                    health=d.num(1)))
                if game.in_combat:
                    game.run_actions(
                        ScheduleNextTurn(hero, Buff(pick, atk=d.num(0),
                                                    health=d.num(1))))
        return actions or None


class TheLastOneStandingGoldenScript(TheLastOneStandingScript):
    """
    Natural language: <b>Rally:</b> Give a friendly minion of
    each type +{0}/+{1} permanently, twice.

    Formal spec: 同基础版，passes=2——整套种族遍历独立执行两轮
    （第二轮选取不受第一轮影响，同一随从可两轮都被选中叠加）。

    Test: test_batch_rally.py — 金色单种族随从获 2 份 buff

    Params: {0}=15 {1}=15（金色 CardDef，两轮）
    """

    passes = 2


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG25_016", SindoreiStraightShotScript)
    _add("BG25_016_G", SindoreiStraightShotScript)          # 金色同文
    _add("BG27_017", ObsidianRavagerScript)
    _add("BG27_017_G", ObsidianRavagerGoldenScript)         # "its neighbors"
    _add("BG33_318", BileSpitterScript)
    _add("BG33_318_G", BileSpitterGoldenScript)             # 2 Murlocs
    _add("BG33_323", DustboneDevastatorScript)
    _add("BG33_323_G", DustboneDevastatorScript)            # num(0)=2 自然体现
    _add("BG33_822", BigwigBanditScript)
    _add("BG33_822_G", BigwigBanditGoldenScript)            # 2 Bounties
    _add("BG33_886", TuskedCamperScript)
    _add("BG33_886_G", TuskedCamperGoldenScript)            # 2 Gems
    _add("BG33_924", BlueWhelpScript)
    _add("BG33_924_G", BlueWhelpScript)                     # num(0)=2 自然体现
    _add("BG34_140", ExpertAviatorScript)
    _add("BG34_140_G", ExpertAviatorScript)                 # num(0)=2 自然体现
    _add("BG34_319", HighkeeperRaScript)
    _add("BG34_319_G", HighkeeperRaGoldenScript)            # DR/Rally ×2
    _add("BG34_320", TheLastOneStandingScript)
    _add("BG34_320_G", TheLastOneStandingGoldenScript)      # twice
    return registered
