"""批次 rally2 — 剩余 Rally 池随从（作业单 2026-08-21，前批 rally 完成后）。

覆盖 15 张 OK: BG20_101 Roadboar / BG20_104 Bonker / BG33_883 Razorfen
Vineweaver / BG33_885 Sanguine Refiner / BG34_604 Heroic Underdog /
BG34_925 Seafloor Recruiter / BG36_200 Flittering Bat / BG36_204
Headhunter Gryphon / BG36_207 Wolf Pup / BG36_208 Deathstrider /
BG36_210 Hoarding Hyena / BG36_241 Crimson Vindicator / BG36_242 Bronze
Timewalker / BG36_243 Sky-hatch Runaway / BG36_331 Bramble Tunneler
（含金色 id; 金色=独立卡定义）。
附带注册 2 张被 "Cast" 引用的法术脚本: BG28_518 Chef's Choice /
BG36_246 Mighty Dragonbreath（法术批次勿重复注册）。

DEFERRED 2 张（不注册，详见各类 docstring）: BG36_333 Jailbird
Juggernaut / BG36_351 Moat Custodian。

共性语义（RULES §6.16）: Rally 在攻击宣告时、伤害结算前触发，
ctx={"target": 防守方}（CombatScheduler._execute_attack 与招募期攻击
game.recruit_phase_attack 均保证）。经验库: ctx["target"] 触发时保证
存活，无需 dead 检查。文本无 "permanent" 的战斗内效果经引擎快照恢复
战后回滚（RULES §3.5）; "this game" 效果落在 hero 级持久状态。

效果施法（"Cast X"）统一裁定（PlayBloodGisms 同族先例）: 施加法术
on_play 效果本体——不经手牌、不耗金币、不动法术池（施放即回池的
官方流程在效果施法路径下净变化为 0）、不计 TAVERN_SPELLS_CAST /
不广播 tavern_spell_cast / card_played（事件语义为手牌打出）。
引擎缺口报告: 缺 "效果施法" 专用事件。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GetRandomMinion, ScheduleNextTurn, Summon
from hsrl2.actions.bloodgem import (
    GetBloodGems,
    ImproveBloodGems,
    PlayBloodGems,
    _gem_values,
)
from hsrl2.actions.discover import _pool_candidates
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.events import AFTER_ATTACK, Listener
from hsrl2.tags import GameTag, Race, Zone

# 身份标识常量（card id 非数值——bloodgem.BLOOD_GEM_VARIANTS 先例）
CHEFS_CHOICE_ID = "BG28_518"          # Chef's Choice（Seafloor Recruiter 施放）
MIGHTY_DRAGONBREATH_ID = "BG36_246"   # Mighty Dragonbreath（Crimson Vindicator 施放）
FORAGING_BAT_ID = "BG36_200t"         # Flittering Bat 的 1/1 Beast token（XML 权威）
TASTY_LOBSTER_ID = "BG36_202"         # Hoarding Hyena 召唤的池随从

# Chromadrake 基础卡全集（非池 token——data 无 is_pool_minion 标志，
# "Get a random Chromadrake" 不占池）。漂移守护测试对照
# hsdata/CardDefs.xml（名称以 Chromadrake 结尾的非金色 minion）。
CHROMADRAKE_IDS = (
    "BG34_634t",   # Blue Chromadrake
    "BG34_635t",   # Black Chromadrake
    "BG34_636t",   # Green Chromadrake
    "BG34_637t",   # Bronze Chromadrake
    "BG34_638t",   # Red Chromadrake
)

# Choose One 池卡全集（引擎缺口: 生成器未导出 CHOOSE_ONE 标签 →
# 硬编码 + 漂移守护测试对照 XML CHOOSE_ONE ∩ 池标志）。
# "card" 通名涵盖随从与法术（Glass of Perspective BG36_MagicItem_303
# 同文先例）。金色版不参与（"a random Choose One card" 基础卡语义）。
CHOOSE_ONE_MINION_IDS = frozenset({
    "BG27_084",   # Sprightly Scarab
    "BG30_123",   # Fearless Foodie
    "BG31_320",   # Crater Miner
    "BG32_237",   # Intrepid Botanist
    "BG36_330",   # Sly Infiltrator
    "BG36_332",   # Snare Trapper
    "BG36_341",   # Veteran Brigand
})
CHOOSE_ONE_SPELL_IDS = frozenset({
    "BG31_880",   # Alliance Flag
    "BG31_881",   # Time Management
    "BG31_886",   # Forest's Bounty
    "BG31_890",   # Boundless Potential
})


def _rally_target(ctx):
    return (ctx or {}).get("target")


def _has_rally_hook(m) -> bool:
    """随从是否具有 Rally 效果（Deathstrider / Sky-hatch Runaway 的
    "Rally minion" 判定）。

    双通道: GameTag.RALLY（data 关键词权威）**或** 脚本类含 rally 钩子
    ——金色卡定义不携带关键词标志（batch_rally 已报告的数据缺口），
    经脚本钩子存在性兜底; 引擎 rally 分发即 call_script("rally")，
    脚本存在性是行为权威。窄缺口（报告主线）: Dark Gift rally 链式
    override（_script_overrides）与磁力吸附的 rally 不被本判定识别。
    """
    if m.has(GameTag.RALLY):
        return True
    return getattr(m.scripts, "rally", None) is not None


# ══════════════════ BG20_101 Roadboar ══════════════════


class RoadboarScript:
    """
    Natural language: <b>Rally:</b> Get a <b>Blood Gem</b>.

    Formal spec:
      1. rally（攻击宣告时、伤害前）: GetBloodGems(控制者, times)——
         times 颗 vanilla 血宝石进手牌（满手 pending_hand_add 排队，
         RULES §3.3）; 血宝石非池卡不占池
      2. 战斗中获得的手牌不受快照影响; 招募期攻击（Fishbait 场景）
         同样触发（rally 钩子统一路径）
      3. 金色版文本 "Get 2 Blood Gems" → times=2（金色文本字面量，
         CardDef 无模板参数）

    Test: test_batch_rally2.py — 攻击后手牌 +times 张 BG20_GEM /
    无效 controller 落空 / 金色 2 张

    Params: 无数值参数（"a"/"2" 为文本语义字面量; 宝石数值唯一来源
    BG20_GEM CardDef）
    """

    times = 1

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GetBloodGems(hero, source.scripts.times)


class RoadboarGoldenScript(RoadboarScript):
    """
    Natural language: <b>Rally:</b> Get 2 <b>Blood Gems</b>.

    Formal spec: 同基础版，times=2（两颗独立宝石实体进手牌）。

    Test: test_batch_rally2.py — 金色一次攻击手牌 +2 张 BG20_GEM

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ BG20_104 Bonker ══════════════════


class BonkerScript:
    """
    Natural language: <b>Windfury</b> <b>Rally:</b> This plays {0}
    <b>Blood Gems</b> on all your other minions.

    Formal spec:
      1. rally: 对同棋盘全部**其他**友方随从（非 source、存活）各
         PlayBloodGems(m, num(0), source)——"plays ... on" 官方语义
         = 不经手牌直接施加 num(0) 次 vanilla 宝石 buff（含
         BLOOD_GEM_BONUS_* 增益，bloodgem.py 保证）
      2. 无其他随从 → 落空; 风怒连续攻击 → 每次攻击宣告各触发一次
         （Windfury 由 data 关键词映射，攻击轮转由引擎处理）
      3. 战斗内 buff 战后回滚（文本无 "permanent"，RULES §3.5）;
         招募期攻击路径无回滚自然持久
      4. 金色版文本同构（num(0)=2）→ 同一脚本类注册两个 id

    Test: test_batch_rally2.py — 其他随从各 +宝石值×num(0)、自身
    排除 / 单独在场落空 / 金色 ×2

    Params: {0}=1（36.2.2 基线，金色 =2）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        others = [m for m in hero.board
                  if m is not source and not m.dead]
        if not others:
            return None
        return [PlayBloodGems(m, d.num(0), source) for m in others]


# ══════════════════ BG33_883 Razorfen Vineweaver ══════════════════


class RazorfenVineweaverScript:
    """
    Natural language: <b>Rally:</b> This plays 3 permanent
    <b>Blood Gems</b> on itself.

    Formal spec:
      1. rally: PlayBloodGems(source, times, source)——times 颗 vanilla
         宝石立即施加（"plays ... on itself"，Tusked Camper 同构）
      2. "permanent" 路径分流（引擎快照恢复回滚战斗内 buff，
         RULES §3.5 默认被文本 "permanent" 覆盖——The Last One
         Standing 双路径先例）:
         a) 招募期攻击（not in_combat）: 无回滚，仅 1 立即生效即永久
         b) 战斗内: 立即施加 + 按**rally 时点**的每颗宝石值
            （BG20_GEM.num + hero BLOOD_GEM_BONUS_*，_gem_values 快照）
            调度 times 个 ScheduleNextTurn(Buff)——下一招募回合开始在
            金币重置后重放，净效果 = 永久保留（两次之间无玩家可观测
            窗口）。取值锁定在 rally 时点: 后续宝石增强不追溯已打出的
            宝石（宝石在打出瞬间结算完毕）
      3. times 颗逐颗调度（times 个独立 buff 实例——对 buff 计数类
         观察者语义正确）
      4. 金色版 "6 permanent" → times=6（金色文本字面量）

    Test: test_batch_rally2.py — 立即 +times 颗宝石值 / run_combat 后
    经下回合重放保留（permanent）/ 招募期路径单份 / 金色 6 颗

    Params: 无模板参数（"3"/"6" 为文本字面量; 宝石数值唯一来源
    BG20_GEM CardDef + hero 增益 tags）
    """

    times = 3

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        n = source.scripts.times
        if not game.in_combat:
            return PlayBloodGems(source, n, source)
        gem_atk, gem_health = _gem_values(game, "BG20_GEM", hero)
        actions = [PlayBloodGems(source, n, source)]
        actions.extend(
            ScheduleNextTurn(hero, Buff(source, atk=gem_atk,
                                        health=gem_health))
            for _ in range(n))
        return actions


class RazorfenVineweaverGoldenScript(RazorfenVineweaverScript):
    """
    Natural language: <b>Rally:</b> This plays 6 permanent
    <b>Blood Gems</b> on itself.

    Formal spec: 同基础版，times=6。

    Test: test_batch_rally2.py — 金色战斗内 6 颗（6 个重放调度）

    Params: 无模板参数（"6" 为金色文本字面量）
    """

    times = 6


# ══════════════════ BG33_885 Sanguine Refiner ══════════════════


class SanguineRefinerScript:
    """
    Natural language: [x]<b>Rally:</b> Your <b>Blood Gems</b> give an
    extra +{0}/+{1} this game.

    Formal spec:
      1. rally: ImproveBloodGems(hero, num(0), num(1))——hero 的
         BLOOD_GEM_BONUS_ATK/HEALTH 各叠加 num(0)/num(1)（"this game"
         永久; hero tag 不在战斗快照内，战后保留; 每次 Rally 触发
         各叠加一次）
      2. 生效点: _gem_values 读取点统一（手牌打出与 PlayBloodGems
         施放的宝石同时生效，bloodgem.py 保证）
      3. 金色版文本同构（num=2/2）→ 同一脚本类注册两个 id

    Test: test_batch_rally2.py — tag 各 +num / 叠加 / gem_values 集成
    生效 / 金色 +2/+2

    Params: {0}=1 {1}=1（36.2.2 基线，金色 =2/2）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        return ImproveBloodGems(hero, atk=d.num(0), health=d.num(1))


# ══════════════════ BG34_604 Heroic Underdog ══════════════════


class HeroicUnderdogScript:
    """
    Natural language: <b>Stealth</b> <b>Rally:</b> Gain the target's
    Attack.

    Formal spec:
      1. rally（伤害前）: source 获得 +target.atk 攻击（快照防守方
         实时值——含光环/rally 增益）; mult 倍（金色 "double" → 2）
      2. 增益先于攻击伤害结算 → 本次攻击伤害已含增益（RULES §6.16）
      3. 文本无 "permanent" → 战斗内生效战后回滚（RULES §3.5）;
         招募期攻击路径无回滚自然持久
      4. target 缺失（Sky-hatch Runaway 招募期触发等）→ 落空;
         target.atk == 0 → 无增益落空
      5. 自身 Stealth 由 create_minion 关键词映射（data 权威）

    Test: test_batch_rally2.py — 攻击伤害含 rally 增益 / 目标 0 攻
    落空 / 金色双倍

    Params: 无模板参数（增益 = target.atk 运行时值）
    """

    mult = 1   # 金色 "double the target's Attack" → 2（文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        target = _rally_target(ctx)
        if target is None:
            return None
        gain = target.atk * source.scripts.mult
        if gain <= 0:
            return None
        return Buff(source, atk=gain)


class HeroicUnderdogGoldenScript(HeroicUnderdogScript):
    """
    Natural language: <b>Stealth</b> <b>Rally:</b> Gain double the
    target's Attack.

    Formal spec: 同基础版，mult=2——增益 = target.atk × 2。

    Test: test_batch_rally2.py — 金色攻击伤害 = atk + 2×target.atk

    Params: 无模板参数（"double" 为金色文本语义）
    """

    mult = 2


# ══════════════════ BG28_518 Chef's Choice（法术，Recruiter 施放） ══════════════════


class ChefsChoiceScript:
    """
    Natural language: Choose a minion. Get a different minion of the
    same type.

    目标选择与获取裁定（hearthstone.wiki.gg 官方页 Wiki tags 2026-08-21
    核实）: [Targeted] + [Generate]——"Choose a minion" 是定向选择，
    "Get ..." 是随机生成（非三选一发现）。Seafloor Recruiter 施放时
    目标被强制为 Recuiter 右邻，本脚本仅消费 ctx["target"]。

    Formal spec:
      1. on_play（ctx["target"] = 被选随从）: 随机 Get 一张**不同**
         card_id 的同类型随从进手牌（满手 pending_hand_add 排队）:
         - 目标 race R: 候选 = 池内 race ∈ (R, ALL)（Amalgam 匹配
           任何类型，_pool_candidates 语义）
         - 目标 race ALL: 候选 = 池内全部**有类型**随从（race != NONE
           ——Patch 28.6.0.193541 官方 bugfix: "All" 目标不再给出无
           类型随从）
         - 目标 race NONE: 候选 = 池内 race == NONE（无类型即同类型;
           Amalgam 不匹配——它有类型）
         全部候选经池剩余量 + active_races 过滤（_pool_candidates），
         排除 target.card_id; 无候选 → 落空（真实游戏池空行为）
      2. 选中 minion_pool.acquire 占池（RULES §2.3）+ create_minion
         + pending_hand_add
      3. 无 target / 非 Minion 目标 → GameStateError（fail-loud，
         BloodGemScript 定向法术先例——引擎 play_spell 的
         needs_target 分流由法术批次声明）
      4. 本类经 Recruiter rally 的效果施法路径调用（模块 docstring
         统一裁定: 不计费/不动池/不广播）

    Test: test_batch_rally2.py — 同族目标获得不同 card_id 同族随从且
    占池 / ALL 目标不给无类型 / NONE 目标只给无类型 / 池耗尽落空

    Params: 无数值参数
    """

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.game import GameStateError
        from hsrl2.minion import Minion
        hero = source.controller
        if hero is None:
            return None
        target = (ctx or {}).get("target")
        if target is None:
            raise GameStateError(
                f"{source.card_id} is a targeted spell: ctx['target'] "
                f"required")
        if not isinstance(target, Minion):
            raise GameStateError(
                f"{source.card_id} target must be a Minion, got "
                f"{type(target).__name__}")
        race = target.race
        cands = []
        for cid in _pool_candidates(game):
            d = game.db.get(cid)
            if cid == target.card_id:
                continue
            if race == Race.ALL:
                if d.race == Race.NONE:
                    continue      # 官方 bugfix: "All" 目标不给无类型
            elif d.race not in (race, Race.ALL):
                continue
            cands.append(cid)
        if not cands:
            return None
        pick = game.rng.choice(cands, label="chefs_choice_minion")
        if not game.minion_pool.acquire(pick):
            raise GameStateError(
                f"Chef's Choice: acquire failed for {pick}")
        game.pending_hand_add(hero, game.create_minion(pick,
                                                       controller=hero))
        return None


# ══════════════════ BG34_925 Seafloor Recruiter ══════════════════


class SeafloorRecruiterScript:
    """
    Natural language: <b>Rally:</b> Cast Chef's Choice on the minion
    to the right.

    Formal spec:
      1. rally: target = 同棋盘 source 右侧一位随从（zone_position+1，
         即 board[idx+1]）; source 为最右 → 落空; 右邻已死 → 落空
      2. 施放 Chef's Choice（BG28_518）: create_spell + 以
         ctx={"target": 右邻} 运行其 on_play 脚本（效果本体见
         ChefsChoiceScript）——"Cast X on Y" = 效果直接以 Y 为目标
         结算（模块 docstring 效果施法统一裁定: 不经手牌/不计费/
         不动法术池/不广播）; 施放后法术实体 zone=REMOVED
      3. times 次独立施放（金色 "twice"——两次独立随机获取）
      4. HDT changelog 佐证: "Fixed Seafloor Recruiter unable to
         target minions without a tribe"——右邻可为无类型随从

    Test: test_batch_rally2.py — 右邻触发获得同族随从 / 最右位落空 /
    金色两次获得 2 张

    Params: 无数值参数
    """

    times = 1   # 金色 "twice" → 2（金色文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        board = hero.board
        try:
            idx = board.index(source)
        except ValueError:
            return None
        if idx + 1 >= len(board):
            return None
        target = board[idx + 1]
        if target.dead:
            return None
        for _ in range(source.scripts.times):
            spell = game.create_spell(CHEFS_CHOICE_ID, controller=hero)
            game.run_script_hook(spell, "on_play", ctx={"target": target})
            spell.zone = Zone.REMOVED
        return None


class SeafloorRecruiterGoldenScript(SeafloorRecruiterScript):
    """
    Natural language: <b>Rally:</b> Cast Chef's Choice on the minion
    to the right twice.

    Formal spec: 同基础版，times=2——同一右邻连续两次施放（两次独立
    随机获取，可同 card_id 可不同——池内多副本）。

    Test: test_batch_rally2.py — 金色一次攻击获得 2 张同族随从

    Params: 无数值参数（"twice" 为金色文本语义）
    """

    times = 2


# ══════════════════ BG36_200 Flittering Bat ══════════════════


class FlitteringBatScript:
    """
    Natural language: <b>Rally:</b> Summon a {0}/{1} Beast.

    Formal spec:
      1. rally: Summon(hero, FORAGING_BAT_ID) times 次——token BG36_200t
         Foraging Bat（XML 权威 1/1 Beast; {0}/{1}=1/1 为显示参数与
         token CardDef 数值一致，属性以 token 定义为准）; token 非池卡
         不占池（SOP 清单）
      2. 召唤位置 = 最右（Summon position=None）; 满场由 game.summon
         处理（fire minion_overflow 后跳过， Summon Action 不吞信号）
      3. 战斗中召唤的 token 战后随引擎 board 恢复消失（不在战前快照，
         RULES §3.5）; 招募期攻击路径召唤的 token 滞留（无公开
         RemoveFromBoard API——Expert Aviator _expire_combat_copy 同族
         引擎缺口，报告主线）
      4. 金色 "Summon two {0}/{1} Beasts"（金色 num 仍 1/1）→ times=2
         （金色文本字面量; 两个独立 token 实体）

    Test: test_batch_rally2.py — 攻击后棋盘 +times 只 Foraging Bat /
    满场不召唤 / 金色 2 只

    Params: {0}=1 {1}=1（显示参数; token 实际属性唯一来源
    BG36_200t CardDef）
    """

    times = 1   # 金色 "two" → 2（金色文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return [Summon(hero, FORAGING_BAT_ID)
                for _ in range(source.scripts.times)]


class FlitteringBatGoldenScript(FlitteringBatScript):
    """
    Natural language: <b>Rally:</b> Summon two {0}/{1} Beasts.

    Formal spec: 同基础版，times=2。

    Test: test_batch_rally2.py — 金色一次攻击召唤 2 只 token

    Params: {0}=1 {1}=1（金色显示参数）
    """

    times = 2


# ══════════════════ BG36_204 Headhunter Gryphon ══════════════════


class HeadhunterGryphonScript:
    """
    Natural language: <b>Rally:</b> Get a random Beast.

    Formal spec:
      1. rally: GetRandomMinion(hero, race=Race.BEAST) times 次——
         池感知（available 闸门 + acquire 占池 RULES §2.3; Amalgam
         经 ALL 匹配）、满手 pending_hand_add 排队、池内无 Beast
         副本时单次落空（真实游戏行为）
      2. times 次独立获取（金色 "2 random Beasts"——两次独立，可同
         card_id 可不同，池内多副本）
      3. 战斗中获得进手牌不受快照影响

    Test: test_batch_rally2.py — 攻击后手牌 +times 张 Beast 且占池 /
    金色 2 张

    Params: 无数值参数（"a random"/"2 random" 为文本语义）
    """

    times = 1   # 金色 "2 random Beasts" → 2（金色文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return [GetRandomMinion(hero, race=Race.BEAST)
                for _ in range(source.scripts.times)]


class HeadhunterGryphonGoldenScript(HeadhunterGryphonScript):
    """
    Natural language: <b>Rally:</b> Get 2 random Beasts.

    Formal spec: 同基础版，times=2（两个独立 GetRandomMinion Action）。

    Test: test_batch_rally2.py — 金色一次攻击获得 2 张 Beast

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ BG36_207 Wolf Pup ══════════════════


class WolfPupScript:
    """
    Natural language: <b>Rally:</b> Give your other minions +{0}/+{1}.

    Formal spec:
      1. rally: 同棋盘全部**其他**友方随从（非 source、存活）各
         Buff(+num(0), +num(1))
      2. 无其他随从 → 落空
      3. 文本无 "permanent" → 战斗内生效战后回滚（RULES §3.5）;
         招募期攻击路径自然持久
      4. 金色版文本同构（num=8/2）→ 同一脚本类注册两个 id

    Test: test_batch_rally2.py — 其他随从各 +num(0)/num(1)、自身
    排除 / 单独在场落空 / 金色 +8/+2

    Params: {0}=4 {1}=1（36.2.2 基线，金色 =8/2）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        others = [m for m in hero.board
                  if m is not source and not m.dead]
        if not others:
            return None
        return [Buff(m, atk=d.num(0), health=d.num(1)) for m in others]


# ══════════════════ BG36_208 Deathstrider ══════════════════


class DeathstriderScript:
    """
    Natural language: [x]After a friendly <b>Rally</b> minion attacks,
    trigger your left-most <b>Deathrattle</b>.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source，出售/招募期死亡/移除
         时自动注销; 战斗中战死注销、战后随监听器表快照恢复——引擎
         保证）: 事件 AFTER_ATTACK（引擎在伤害与死亡结算后广播，C4）
      2. 条件（回调内过滤）:
         a) attacker.controller is source.controller（"friendly"）
         b) attacker 是 Rally 随从——_has_rally_hook 双通道判定
            （GameTag.RALLY 或脚本 rally 钩子; 金色关键词数据缺口
            兜底，见该函数 docstring）
         c) 攻击者已战死不影响（"attacks" 完成——AFTER_ATTACK 无论
            存活与否都广播）
       3. 触发: 左-most 友方持 DEATHRATTLE tag 的存活随从（含磁力
          并入宿主——attach_magnetic 置 tag）以 run_script_hook 触发
          其 deathrattle 钩子（**无死亡**——Jaws of Death Dark Gift
          同构先例）。不计入 COUNTER_DEATHRATTLES、不广播
          deathrattle_trigger（依据 2026-08-23 查证维持: Deathstrider
          卡页 Wiki mechanics [Trigger Deathrattle]、Jaws of Death
          页（BG36_MidGameEffect_000t16）均无 Notes（全文核对）;
          推导: COUNTER_DEATHRATTLES 语义 = "本局已**死亡**触发的
          亡语数"（tags.py 1047，_process_single_death 死亡路径计数
          ——Darkcrest... Death's Embrace 资格），无死亡的触发不在
          死亡簿记面; 亡语召唤位置用 bearer.zone_position，随从仍在场
          语义良定义）
      4. passes 次（金色 "twice"）——左-most 判定一次、同一随从触发
         passes 次（"trigger your left-most Deathrattle twice" 语法
         = 同一亡语触发两次）; 无亡语随从 → 无效果
      5. 招募期攻击（recruit_phase_attack 同样广播 AFTER_ATTACK）→
         照常触发

    Test: test_batch_rally2.py — Rally 随从攻击后左-most 亡语触发 /
    非 Rally 攻击者不触发 / 对手 Rally 攻击不触发 / 无亡语落空 /
    金色两次

    Params: 无数值参数
    """

    passes = 1   # 金色 "twice" → 2（金色文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_after_attack(g, attacker=None, defender=None, **kw):
            hero = source.controller
            if hero is None or attacker is None:
                return
            if attacker.controller is not hero:
                return
            if not _has_rally_hook(attacker):
                return
            bearers = [m for m in hero.board
                       if not m.dead and m.has(GameTag.DEATHRATTLE)]
            if not bearers:
                return
            left = bearers[0]
            for _ in range(source.scripts.passes):
                g.run_script_hook(left, "deathrattle")

        game.events.register(Listener(
            event=AFTER_ATTACK,
            owner=source,
            callback=on_after_attack,
        ))
        return None


class DeathstriderGoldenScript(DeathstriderScript):
    """
    Natural language: [x]After a friendly <b>Rally</b> minion attacks,
    trigger your left-most <b>Deathrattle</b> twice.

    Formal spec: 同基础版，passes=2——左-most 亡语随从的钩子连续
    触发 2 次（左-most 判定一次）。

    Test: test_batch_rally2.py — 金色一次攻击触发同一亡语 2 次

    Params: 无数值参数（"twice" 为金色文本语义）
    """

    passes = 2


# ══════════════════ BG36_210 Hoarding Hyena ══════════════════


class HoardingHyenaScript:
    """
    Natural language: <b>Rally:</b> Summon a Tasty Lobster.

    Formal spec:
      1. rally: 满板预检（board_full → 落空，避免先占池后溢出的池
         泄漏）; Tasty Lobster（BG36_202）是**池随从**（data
         IS_BACON_POOL_MINION，RULES §2.3）→ minion_pool.acquire
         占池，成功后 create_minion + game.summon（最右）; 池内无
         副本 → 落空（RULES §2.4 池空不可获取——GetRandomMinion
         同语义）
      2. Lobster 自身亡语（"Give a random friendly Beast +{0}/+{1}.
         Improve your future Tasty Lobsters"）由其自身脚本负责——
         需 hero 级持久改进状态（引擎缺口，见作业报告），不在本批次
      3. 战斗中召唤的 Lobster 战后随 board 恢复消失且不回池（战前
         未持有）; 招募期路径召唤的 Lobster 滞留棋盘

    Test: test_batch_rally2.py — 攻击后棋盘 +1 Lobster 且占池 /
    池耗尽落空 / 满板不占池不召唤

    Params: 无数值参数（召唤目标为文本指名的身份标识）
    """

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None or hero.board_full():
            return None
        if not game.minion_pool.acquire(TASTY_LOBSTER_ID):
            return None
        lobster = game.create_minion(TASTY_LOBSTER_ID, controller=hero)
        game.summon(hero, lobster)
        return None


class HoardingHyenaGoldenScript(HoardingHyenaScript):
    """
    Natural language: <b>Rally:</b> Summon a Golden Tasty Lobster.

    Formal spec:
      1. 同基础版满板预检; 召唤**金色** Lobster（BG36_202_G 经
         create_minion(golden=True) 金色数据链解析）
       2. 池记账（Lockbox 金色先例 game._open_lockbox）: 金色 = 3 副本
          合成 → acquire min(GOLDEN_POOL_RETURN_COPIES, available) 份
          基础卡; 池不足 3 份甚至耗尽时仍召唤（依据 2026-08-23 查证:
          wiki.gg/wiki/Battlegrounds/Lockbox 无 Notes（全文核对）——
          "get a random Golden minion" 授予语义对池存量不设门（先例:
          Magicfin Mycologist 35.2.0 hotfix "每次购买只消耗一个充能"
          ——授予面与池面分离）; 按"仍给"实现，acquire 尽池扣减）
      3. 金色 Lobster 亡语同样不在本批次（同基础版注 2）

    Test: test_batch_rally2.py — 金色攻击召唤 BG36_202_G 且池 -3 /
    池 1 份时仍召唤（acquire 1）

    Params: 无数值参数
    """

    @staticmethod
    def rally(source, game, ctx):
        import hsrl2.constants as C
        hero = source.controller
        if hero is None or hero.board_full():
            return None
        for _ in range(min(C.GOLDEN_POOL_RETURN_COPIES,
                           game.minion_pool.available(TASTY_LOBSTER_ID))):
            if not game.minion_pool.acquire(TASTY_LOBSTER_ID):
                from hsrl2.game import GameStateError
                raise GameStateError(
                    "Hoarding Hyena golden: lobster acquire failed")
        lobster = game.create_minion(TASTY_LOBSTER_ID, controller=hero,
                                     golden=True)
        game.summon(hero, lobster)
        return None


# ══════════════════ BG36_246 Mighty Dragonbreath（法术，Vindicator 施放） ══════════════════


class MightyDragonbreathScript:
    """
    Natural language: [x]Give your minions +{0}/+{1}. Repeat for your
    Dragons. Repeat for your minions with <b>Divine Shield</b>.

    Formal spec:
      1. on_play: 三波增益，每波对当波成员各 +num(0)/num(1):
         wave1 全部友方存活随从; wave2 友方 Dragon（含 ALL）;
         wave3 友方持 DIVINE_SHIELD 随从（持有判定取施放时点——
         本法术不改变种族/圣盾，预收集与逐波结算等价）
      2. 每波 buff 经 tavern_spell_buff(target, num(0), num(1))
         构造（racefx 契约: 酒馆法术施加增益的统一出口——"Your
         Tavern spells give an extra +X" 修饰符正确叠加，效果施法
         路径同样适用）
      3. 无友方随从 → 落空; 战斗内（Vindicator rally 施放）buff 战后
         回滚（RULES §3.5）; 手牌打出路径（招募期）自然持久
      4. 属池法术（is_pool_spell）——手牌打出流程（计费/计数/回池）
         由引擎 play_spell 处理，法术批次可补 needs_target 声明
         （本法术无目标）

    Test: test_batch_rally2.py — 三波合计断言（龙/圣盾叠加次数）/
    TAVERN_SPELL_EXTRA 集成 / 空板落空

    Params: {0}=2 {1}=1（36.2.2 基线）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        board = [m for m in hero.board if not m.dead]
        actions = []
        for wave in (board,
                     [m for m in board
                      if m.race in (Race.DRAGON, Race.ALL)],
                     [m for m in board if m.divine_shield]):
            actions.extend(tavern_spell_buff(m, d.num(0), d.num(1))
                           for m in wave)
        return actions or None


# ══════════════════ BG36_241 Crimson Vindicator ══════════════════


class CrimsonVindicatorScript:
    """
    Natural language: <b>Divine Shield</b> <b>Rally:</b> Cast Mighty
    Dragonbreath.

    Formal spec:
      1. rally: 施放 Mighty Dragonbreath（BG36_246）times 次——
         create_spell + 运行其 on_play 脚本（效果本体见
         MightyDragonbreathScript; 模块 docstring 效果施法统一裁定:
         不经手牌/不计费/不动法术池/不广播）; 施放后法术实体
         zone=REMOVED
      2. 自身 Divine Shield 由 create_minion 关键词映射（data 权威）
      3. times 次独立施放（金色 "twice"——两套三波增益）

    Test: test_batch_rally2.py — 攻击后三波增益到位 / 金色两套

    Params: 无数值参数
    """

    times = 1   # 金色 "twice" → 2（金色文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(source.scripts.times):
            spell = game.create_spell(MIGHTY_DRAGONBREATH_ID,
                                      controller=hero)
            game.run_script_hook(spell, "on_play", ctx={})
            spell.zone = Zone.REMOVED
        return None


class CrimsonVindicatorGoldenScript(CrimsonVindicatorScript):
    """
    Natural language: <b>Divine Shield</b> <b>Rally:</b> Cast Mighty
    Dragonbreath twice.

    Formal spec: 同基础版，times=2。

    Test: test_batch_rally2.py — 金色单次攻击 = 两套三波增益

    Params: 无数值参数（"twice" 为金色文本语义）
    """

    times = 2


# ══════════════════ BG36_242 Bronze Timewalker ══════════════════


class BronzeTimewalkerScript:
    """
    Natural language: <b>Rally:</b> Get a random <b>Chromadrake</b>.

    Formal spec:
      1. rally: 从 CHROMADRAKE_IDS（5 张基础 Chromadrake——Blue/Black/
         Green/Bronze/Red，非池 token）随机取 times 张进手牌
         （create_minion + pending_hand_add 满手排队）; token 非池卡
         不占池（SOP 清单; 漂移守护测试对照 XML）
      2. times 次独立选取（金色 "2 random Chromadrakes"——可同可
         不同，非池无副本约束）
      3. Chromadrake 各自的 Battlecry 由其自身脚本负责（token 批次，
         不在本批次）
      4. 战斗中获得进手牌不受快照影响

    Test: test_batch_rally2.py — 攻击后手牌 +times 张 Chromadrake /
    不占随从池 / CHROMADRAKE_IDS 与 XML 漂移守护 / 金色 2 张

    Params: 无数值参数
    """

    times = 1   # 金色 "2 random Chromadrakes" → 2（金色文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(source.scripts.times):
            cid = game.rng.choice(CHROMADRAKE_IDS,
                                  label="chromadrake_pick")
            game.pending_hand_add(hero,
                                  game.create_minion(cid, controller=hero))
        return None


class BronzeTimewalkerGoldenScript(BronzeTimewalkerScript):
    """
    Natural language: <b>Rally:</b> Get 2 random <b>Chromadrakes</b>.

    Formal spec: 同基础版，times=2（两次独立随机选取）。

    Test: test_batch_rally2.py — 金色一次攻击获得 2 张 Chromadrake

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ BG36_243 Sky-hatch Runaway ══════════════════


class SkyHatchRunawayScript:
    """
    Natural language: <b>Activate ({0}):</b> Trigger a friendly
    minion's <b>Rally</b>.

    目标选择裁定（hearthstone.wiki.gg 官方页 Wiki tags 2026-08-21
    核实）: [Targeted] + Rally-related——玩家选择目标（Kelp Keeper
    BG36_701 终裁同例），PendingChoice 建模而非随机近似。

    Formal spec:
      1. activate（引擎已扣 num(0)=activate_cost 金并置
         ACTIVATE_USED_THIS_TURN，game.use_activate 保证）:
         候选 = 控制者棋盘上存活的 Rally 随从（_has_rally_hook 双通道
         判定——含金色关键词数据缺口兜底; 本卡自身无 Rally 自然不在
         候选）
      2. 候选为空 → 无效果返回 None（Activate 费用已扣——官方: 无合法
         目标时 activate 仍可按但无效果，Kelp Keeper 批次 1b 裁定）
      3. 否则 pending_choices.append(PendingChoice(owner, 候选,
         "activate_target", resolve))——选定目标以 run_script_hook
         触发其 rally 钩子 times 次（ctx=None: 招募期触发无攻击目标，
         target 依赖型 Rally 落空是官方可观测行为; ctx=None/{} 等价
         ——脚本侧 (ctx or {}).get("target")）
      4. run_script_hook 同时合并磁力吸附的 rally 效果（引擎语义）

    Test: test_batch_rally2.py — 扣费 + PendingChoice 选择后目标 Rally
    触发 / 无候选无效果不崩 / 金色同目标两次 / 每回合一次

    Params: {0}=1（activate 费用，与 activate_cost 同值）
    """

    times = 1   # 金色 "twice" → 2（金色文本字面量）

    @staticmethod
    def activate(source, game, ctx):
        from hsrl2.game import PendingChoice
        hero = source.controller
        if hero is None:
            return None
        candidates = [m for m in hero.board
                      if not m.dead and _has_rally_hook(m)]
        if not candidates:
            return None

        def resolve(pick):
            for _ in range(source.scripts.times):
                game.run_script_hook(pick, "rally", ctx=None)

        game.pending_choices.append(PendingChoice(
            hero, candidates, "activate_target",
            resolve_callback=resolve))
        return None


class SkyHatchRunawayGoldenScript(SkyHatchRunawayScript):
    """
    Natural language: <b>Activate ({0}):</b> Trigger a friendly
    minion's <b>Rally</b> twice.

    Formal spec: 同基础版，times=2——单一选择，该目标 Rally 触发
    2 次（KelpKeeperGolden "twice" 同模型）。

    Test: test_batch_rally2.py — 金色选择后目标 Rally 效果 ×2

    Params: {0}=1（金色 activate 费用，与 activate_cost 同值）
    """

    times = 2


# ══════════════════ BG36_331 Bramble Tunneler ══════════════════


class BrambleTunnelerScript:
    """
    Natural language: <b>Rally:</b> Get a random <b>Choose One</b>
    card.

    Formal spec:
      1. rally: 从 Choose One 池卡全集随机 Get times 张进手牌——
         "card" 通名涵盖随从与法术（Glass of Perspective
         BG36_MagicItem_303 同文先例）:
         候选 = CHOOSE_ONE_MINION_IDS ∩ 池可用（_pool_candidates 语义:
         available>0 + active_races）∪ CHOOSE_ONE_SPELL_IDS ∩
         spell_pool 可用; 候选均匀单选
      2. 占池: 随从 minion_pool.acquire + create_minion; 法术
         spell_pool.acquire（1 份）+ create_spell; 均
         pending_hand_add 满手排队（RULES §2.3/§3.3）
      3. times 次独立选取（金色 "2 random"——每次重新评估候选: 法术
         池单份被取后第二次不再出现，随从池多副本可重复同 card_id）
      4. 无候选（两池 Choose One 全耗尽）→ 该次落空
      5. 引擎缺口（报告主线）: 生成器未导出 CHOOSE_ONE 标签 →
         CHOOSE_ONE_*_IDS 硬编码 + 漂移守护测试对照 XML

    Test: test_batch_rally2.py — 攻击后手牌 +1 张 Choose One 卡且占池
    （随从/法术两路径）/ 两池耗尽落空 / 漂移守护 / 金色 2 张

    Params: 无数值参数
    """

    times = 1   # 金色 "2 random Choose One cards" → 2（金色文本字面量）

    @staticmethod
    def rally(source, game, ctx):
        from hsrl2.game import GameStateError
        hero = source.controller
        if hero is None:
            return None
        avail_minions = set(_pool_candidates(game))
        for _ in range(source.scripts.times):
            minion_cands = [cid for cid in CHOOSE_ONE_MINION_IDS
                            if cid in avail_minions]
            spell_cands = [cid for cid in CHOOSE_ONE_SPELL_IDS
                           if game.spell_pool.available(cid) > 0]
            cands = minion_cands + spell_cands
            if not cands:
                return None
            pick = game.rng.choice(cands, label="choose_one_pick")
            d = game.db.get(pick)
            if d.is_pool_spell:
                if not game.spell_pool.acquire(pick):
                    raise GameStateError(
                        f"Bramble Tunneler: spell acquire failed {pick}")
                game.pending_hand_add(
                    hero, game.create_spell(pick, controller=hero))
            else:
                if not game.minion_pool.acquire(pick):
                    raise GameStateError(
                        f"Bramble Tunneler: minion acquire failed {pick}")
                game.pending_hand_add(
                    hero, game.create_minion(pick, controller=hero))
        return None


class BrambleTunnelerGoldenScript(BrambleTunnelerScript):
    """
    Natural language: <b>Rally:</b> Get 2 random <b>Choose One</b>
    cards.

    Formal spec: 同基础版，times=2（两次独立选取，候选逐次重估）。

    Test: test_batch_rally2.py — 金色一次攻击获得 2 张

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ 以下 DEFERRED（不注册 REGISTRY） ══════════════════


class JailbirdJuggernautScript:
    """
    Natural language: [x]<b>Rally:</b> Summon a Golem with stats equal
    to this minion's <b>Blood Gems</b> to attack the target first.
    <i>({0}/{1})</i>

    Status: DEFERRED — requires 每随从血宝石计数 + 召唤即攻击机制

    Dependency（引擎缺口，主线处理）:
      1. **per-minion Blood Gem 计数**: PlayBloodGems/BloodGemScript
         施加的宝石是匿名 entity.Buff，无来源标记——"stats equal to
         this minion's Blood Gems"（宝石数 N → N/N）不可观测。
         需 Minion 级 GEMS_PLAYED 计数 tag（tags.py 主线专属）或
         Buff source_id 标注（bloodgem.py 改造）
      2. **召唤即攻击**: "to attack the target first"——Golem 在
         本体攻击伤害前对 rally 目标发起一次完整攻击（双向伤害/
         反伤/死亡结算/可能的 Venomous 交互）。rally 时点位于
         CombatScheduler._execute_attack 内层，无嵌套攻击 API
         （recruit_phase_attack 语义不符）; 需引擎提供
         "insert_attack(attacker, defender)" 原子
      3. {0}/{1} 为运行时动态显示参数（Golem 实时攻/血），CardDef
         num 为 None 属预期——非 PARAM_MISSING
    """

    @staticmethod
    def rally(source, game, ctx):
        return None


class MoatCustodianScript:
    """
    Natural language: [x]<b>Rally:</b> Your Elementals give an extra
    +{0}/+{1} this game.

    Status: DEFERRED — requires ELEMENTAL_EXTRA_ATK tag + 元素 give 出口

    Dependency（引擎缺口，主线处理）:
      1. tags.py 仅有 ELEMENTAL_EXTRA_HEALTH(1055)（Glowing Cinder
         BG32_842 消费）——本卡 +{0}/+{1} 双值需要
         ELEMENTAL_EXTRA_ATK（tags.py 主线专属，subagent 禁改）
      2. "Your Elementals give an extra" 家族（Sand Swirler BG32_841 /
         Glowing Cinder / Amplifying Essence）需要元素系 give-效果
         统一出口（tavern_spell_buff 同构的 elemental_give_buff），
         当前无消费方脚本迁移——单写 tag 无法验证语义闭环
    """

    @staticmethod
    def rally(source, game, ctx):
        return None


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG20_101", RoadboarScript)
    _add("BG20_101_G", RoadboarGoldenScript)               # 2 Gems
    _add("BG20_104", BonkerScript)
    _add("BG20_104_G", BonkerScript)                       # num(0)=2 自然体现
    _add("BG33_883", RazorfenVineweaverScript)
    _add("BG33_883_G", RazorfenVineweaverGoldenScript)     # 6 Gems
    _add("BG33_885", SanguineRefinerScript)
    _add("BG33_885_G", SanguineRefinerScript)              # num=2/2 自然体现
    _add("BG34_604", HeroicUnderdogScript)
    _add("BG34_604_G", HeroicUnderdogGoldenScript)         # double
    _add("BG34_925", SeafloorRecruiterScript)
    _add("BG34_925_G", SeafloorRecruiterGoldenScript)      # twice
    _add("BG36_200", FlitteringBatScript)
    _add("BG36_200_G", FlitteringBatGoldenScript)          # two Beasts
    _add("BG36_204", HeadhunterGryphonScript)
    _add("BG36_204_G", HeadhunterGryphonGoldenScript)      # 2 Beasts
    _add("BG36_207", WolfPupScript)
    _add("BG36_207_G", WolfPupScript)                      # num=8/2 自然体现
    _add("BG36_208", DeathstriderScript)
    _add("BG36_208_G", DeathstriderGoldenScript)           # twice
    _add("BG36_210", HoardingHyenaScript)
    _add("BG36_210_G", HoardingHyenaGoldenScript)          # Golden Lobster
    _add("BG36_241", CrimsonVindicatorScript)
    _add("BG36_241_G", CrimsonVindicatorGoldenScript)      # twice
    _add("BG36_242", BronzeTimewalkerScript)
    _add("BG36_242_G", BronzeTimewalkerGoldenScript)       # 2 Chromadrakes
    _add("BG36_243", SkyHatchRunawayScript)
    _add("BG36_243_G", SkyHatchRunawayGoldenScript)        # twice
    _add("BG36_331", BrambleTunnelerScript)
    _add("BG36_331_G", BrambleTunnelerGoldenScript)        # 2 cards
    # 被 "Cast" 引用的法术效果本体（法术批次勿重复注册）
    _add("BG28_518", ChefsChoiceScript)                    # Chef's Choice
    _add("BG36_246", MightyDragonbreathScript)             # Mighty Dragonbreath
    return registered
