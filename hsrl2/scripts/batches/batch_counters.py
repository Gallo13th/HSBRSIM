"""批次 counters — 计数/光环/战斗触发随从（作业单 2026-08-22，15 张）。

OK 13 张主体（含金色 id 共 26 个注册 id）:
  动态属性钩子（atk/health 覆盖式——entity.py 契约，本批为首例消费方）6:
    BG35_921 Abyssal Bruiser（TAVERN_SPELLS_CAST_THIS_GAME 计数）
    BG35_342 Falling Sky Golem（COUNTER_DEATHRATTLES 计数）
    BG36_524 Maritime Extortionist（GOLDEN_MINIONS_PLAYED 计数）
    BG25_008 Eternal Knight（hero.deaths_by_card_id 家族计数）
    BG25_013 Rot Hide Gnoll（combat_death_log 本场计数 + in_combat 闸门）
    BG_TTN_401 Ancestral Automaton（hero 级 summon 家族 uuid 簿记）
  事件监听 7:
    BGS_071 Deflect-o-Bot（SUMMON×战斗内 Mech → 攻+DS）
    BG26_817 Blade Collector（CLEAVE tag 自举——XML 无 1017，数据缺口）
    BG36_514 Barrier Banshee（reborn → DS+stats）
    BG36_515 Snazzy Phantom（reborn → 最右 Undead 得 stats）
    BG36_763 Treasure Parrot（本体伤害累计 ≥ num(1) → Golden Touch）
    BG33_155 Devout Hellcaller（友方 Demon 造伤 → 永久增益）
    BG24_004 Warpwing（IMMUNE_WHILE_ATTACKING tag 自举）

DEFERRED 2 张（不注册，见各类 docstring）:
  BGS_126 Wildfire Elemental — requires 受击前血量/excess_damage 事件
  BG33_891 Magicfin Mycologist — requires spell_bought 事件 + teach 机制

引擎缺口报告（主线处理）:
  1. spell_bought 事件缺失: buy_from_tavern 仅对 Minion fire
     minion_bought（game.py:373-375），购买酒馆法术无任何事件——
     Magicfin Mycologist "after you buy a Tavern spell" 无法监听;
     另需 "1/1 Murloc token + teach it that spell" 实体携带机制。
  2. attack ctx 受击前血量缺失: _execute_attack 的 after_attack 只带
     (attacker, defender)，defender 已死且 health 被 clamp 到 0，
     excess = atk - 受击前血量 不可恢复（take_damage 返回未截断值但
     事后不可反推）。精确替代方案（供主线裁决）: before_attack 快照
     defender.health + damage 事件 amount（=宣告攻击力）双监听组合
     ——非近似但依赖两事件拼合，越权自建 ctx，本批按作业单 DEFERRED。
  3. CLEAVE 数据缺口: Blade Collector XML 无 tag 1017（2026-08-22
     核实），生成器仅匹配 "Cleave" 字样漏检 "Also damages" 文本
     → 本批 on_summon 置 tag 兜底; 建议 generate_bg_data.py 补
     文本检测（同漏检风险: 未来 "Also damages" 卡）。
  4. COUNTER_DEATHRATTLES 不随 Titus/Brann 式亡语翻倍倍增
     （game.py:1163 在 dr_times 循环外、按 宿主+磁力亡语附件 计）:
     Falling Sky Golem "for each Deathrattle you've triggered" 是否
     按触发次数计（翻倍=2 次）未公布——沿用引擎现口径并在此备案。
  5. 战斗中死亡即 unregister_owner: 死亡→复生（Reborn）的随从自身
     持有的监听器当场合停摆（快照恢复在战后）——Barrier Banshee
     自身复生不触发自增益属此引擎语义，非脚本缺陷。
  6. Devout Hellcaller "permanently" 经 PERSIST_COMBAT_CHANGES 通道
     实现（run_combat 例外 1: 战内增益战后重放为永久 Buff）: 该通道
     保留战内**全部**增益——若有第三方战斗增益落在 Hellcaller 上会
     一并保留，比卡面文本略宽（实际牌局中无此来源，主线知悉）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import Buff, GainKeyword
from hsrl2.events import DAMAGE, Listener, REBORN_EVENT, SUMMON
from hsrl2.tags import GameTag, Race, Zone

# 跨批复用（batch_avenge_misc/batch_bloodgem import 先例）
from hsrl2.scripts.batches.batch_deathrattle2 import _get_pool_spell

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.minion import Minion

_MECH_RACES = (Race.MECH, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)
_DEMON_RACES = (Race.DEMON, Race.ALL)

# 家族 id 集（身份标识非数值——batch_misc _ZARJIRA_IDS 先例;
# 金色独立卡定义与本体的家族并集）
_ETERNAL_KNIGHT_IDS = frozenset({"BG25_008", "BG25_008_G"})
_AUTOMATON_IDS = frozenset({"BG_TTN_401", "BG_TTN_401_G"})

# Golden Touch（BG28_830，池法术单份）——法术 id 无数据链，字面量
# （batch_deathrattle2 "BG28_168" 先例）
_GOLDEN_TOUCH_ID = "BG28_830"


# ══════════════════ 动态钩子公共复算 ══════════════════


def _static_total_atk(source: "Minion") -> int:
    """覆盖式 atk 钩子的全量复算: BASE + Σbuffs + 种族光环。

    entity.atk 的契约（entity.py:100-114）: 脚本钩子返回 int 时
    **替换**引擎默认值（base+buffs+aura），故钩子须手动复算全部
    三项再附加计数项; 返回 None 时回落引擎默认。种族光环经
    Minion._aura_atk()（engine 动态属性先例注释指定的消费路径）。
    """
    return (source.get(GameTag.BASE_ATK, 0)
            + sum(b.atk for b in source.buffs)
            + source._aura_atk())


def _static_total_health(source: "Minion") -> int:
    """同 _static_total_atk（max_health 口径）。"""
    return (source.get(GameTag.BASE_HEALTH, 0)
            + sum(b.health for b in source.buffs)
            + source._aura_health())


# ══════════════════ BG35_921 Abyssal Bruiser ══════════════════


class AbyssalBruiserScript:
    """
    Natural language: [x]<b>Divine Shield</b>\\nHas +{0}/+{1} for each\\nTavern
    spell you've\\ncast this game.

    Formal spec:
      1. atk/health 动态钩子（覆盖式，entity.py 契约——返回 int 替换
         base+buffs+aura 全量、None 回落）: 计数 = hero.
         TAVERN_SPELLS_CAST_THIS_GAME（play_spell 对 is_pool_spell
         法术递增——"Tavern spell" 官方口径 = 酒馆法术卡池，血宝石/
         Spellcraft 不计，SOP §8 同源）。
      2. 计数 0 → None（回落引擎默认）; >0 → 全量 =
         _static_total_atk/health + 计数 × num(0)/num(1)。
      3. "this game" 无 "wherever this is" 后缀但计数器为 hero 级、
         钩子对手牌/棋盘实体同效（官方同类卡均为 wherever 语义，
         引擎按实体属性实时读数）。SILENCED 由 entity 属性统一闸门。
      4. 金色 num(0)/num(1)=4/2 经金色 CardDef 自然体现（同类注册）。

    Test: test_batch_counters.py — 计数 3 → +3×num(0)/num(1) /
    计数 0 回落基础值 / 附加 Buff 参与全量复算 / 金色 4/2

    Params: {0}=2 {1}=1（36.2.2 基线，金色 {0}=4 {1}=2）
    """

    @staticmethod
    def atk(source):
        hero = source.controller
        if hero is None or source.game is None:
            return None
        count = hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        if count <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_atk(source) + count * d.num(0)

    @staticmethod
    def health(source):
        hero = source.controller
        if hero is None or source.game is None:
            return None
        count = hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        if count <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_health(source) + count * d.num(1)


# ══════════════════ BG35_342 Falling Sky Golem ══════════════════


class FallingSkyGolemScript:
    """
    Natural language: <b>Divine Shield</b>. Has +{0}/+{1} for each
    <b>Deathrattle</b> you've triggered this game <i>(wherever this is).</i>

    Formal spec:
      1. atk/health 动态钩子（覆盖式，同 Abyssal Bruiser 契约）:
         计数 = hero.COUNTER_DEATHRATTLES（_process_single_death 对
         宿主+磁力亡语附件逐次递增——"Deathrattle you've triggered"
         引擎现口径，Titus 翻倍不倍增计数，见批次 docstring 缺口 4）。
      2. 计数 0 → None 回落; >0 → 全量 = 复算 + 计数 × num(0)/num(1)。
      3. "wherever this is": 手牌/棋盘同效; DS 由 data keywords 权威。

    Test: test_batch_counters.py — 计数 2 → +8/+4 / 计数 0 回落 /
    真实路径（战斗中友方亡语随从死亡 → 计数+1 → 攻击抬升）/ 金色 8/4

    Params: {0}=4 {1}=2（36.2.2 基线，金色 {0}=8 {1}=4）
    """

    @staticmethod
    def atk(source):
        hero = source.controller
        if hero is None or source.game is None:
            return None
        count = hero.get(GameTag.COUNTER_DEATHRATTLES, 0)
        if count <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_atk(source) + count * d.num(0)

    @staticmethod
    def health(source):
        hero = source.controller
        if hero is None or source.game is None:
            return None
        count = hero.get(GameTag.COUNTER_DEATHRATTLES, 0)
        if count <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_health(source) + count * d.num(1)


# ══════════════════ BG36_524 Maritime Extortionist ══════════════════


class MaritimeExtortionistScript:
    """
    Natural language: [x]Has +{0}/+{1} for each\\nGolden minion you've\\nplayed
    this game\\n<i>(wherever this is)</i>.

    Formal spec:
      1. atk/health 动态钩子（覆盖式）: 计数 = hero.
         GOLDEN_MINIONS_PLAYED（play_minion 对 is_golden 实体递增，
         SOP §10 原语——金色打出路径自动簿记）。
      2. 计数 0 → None 回落; >0 → 全量 = 复算 + 计数 × num(0)/num(1)。
      3. "wherever this is": 手牌/棋盘同效。

    Test: test_batch_counters.py — 计数 1 → +7/+7 / 计数 0 回落 /
    真实路径（打出金色随从 → 计数+1）/ 金色 14/14

    Params: {0}=7 {1}=7（36.2.2 基线，金色 {0}=14 {1}=14）
    """

    @staticmethod
    def atk(source):
        hero = source.controller
        if hero is None or source.game is None:
            return None
        count = hero.get(GameTag.GOLDEN_MINIONS_PLAYED, 0)
        if count <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_atk(source) + count * d.num(0)

    @staticmethod
    def health(source):
        hero = source.controller
        if hero is None or source.game is None:
            return None
        count = hero.get(GameTag.GOLDEN_MINIONS_PLAYED, 0)
        if count <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_health(source) + count * d.num(1)


# ══════════════════ BG25_008 Eternal Knight ══════════════════


class EternalKnightScript:
    """
    Natural language: [x]Has +{0}/+{1} for each friendly\\nEternal Knight
    that died this\\n__game <i>(wherever this is)</i>.

    Formal spec:
      1. atk/health 动态钩子（覆盖式）: 计数 = Σ hero.deaths_by_card_id
         [家族 id]（_process_single_death 按死者 controller 的 hero
         簿记、跨战斗持久——"friendly" = 己方英雄名下计数; SOP §10
         原语）。
      2. 家族 = 基础 BG25_008 + 金色 BG25_008_G（金色也是 Eternal
         Knight，金色实体读本卡钩子时须并入统计——金色 CardDef 无
         家族展开数据链，_ETERNAL_KNIGHT_IDS 身份标识集先例）。
      3. 计数 0 → None 回落; >0 → 全量 = 复算 + 计数 × num(0)/num(1)。
      4. 敌方 Knight 死亡记入对方 hero 簿记，不影响本方。

    Test: test_batch_counters.py — 己方 2 Knight 死 → +8/+4 / 0 死
    回落 / 敌方 Knight 死不计数 / 金色 Knight 死亡计入家族 / 金色 8/4

    Params: {0}=4 {1}=2（36.2.2 基线，金色 {0}=8 {1}=4）
    """

    @staticmethod
    def _count(source) -> int:
        hero = source.controller
        if hero is None:
            return 0
        deaths = getattr(hero, "deaths_by_card_id", {})
        return sum(deaths.get(cid, 0) for cid in _ETERNAL_KNIGHT_IDS)

    @staticmethod
    def atk(source):
        if source.game is None or EternalKnightScript._count(source) <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_atk(source) \
            + EternalKnightScript._count(source) * d.num(0)

    @staticmethod
    def health(source):
        if source.game is None or EternalKnightScript._count(source) <= 0:
            return None
        d = source.game.db.get(source.card_id)
        return _static_total_health(source) \
            + EternalKnightScript._count(source) * d.num(1)


# ══════════════════ BG25_013 Rot Hide Gnoll ══════════════════


class RotHideGnollScript:
    """
    Natural language: Has +1 Attack for each friendly minion that died
    this combat.

    Formal spec:
      1. atk 动态钩子（覆盖式; 仅攻击——生命不变）: 计数 =
         Σ game.combat_death_log 中 controller is source.controller
         （本场按死亡事件计——复生随从再死占两次，Kangor's
         Apprentice 作业单同裁定; 战斗开始清空/战后保留但被 2 闸门
         屏蔽）。
      2. game.in_combat 闸门: "this combat" 官方语义 = 战斗中成长、
         战后回落——战后 combat_death_log 仍保留上一场数据（run_combat
         仅下场开始清空），无闸门则招募期误读 → 非战斗态一律 None
         回落基础值。
      3. 敌方死亡不计（controller 过滤）; 金色 "+2 Attack" → 子类
         per_atk=2（金色 CardDef 无模板参数，文本字面量）。

    Test: test_batch_counters.py — 战斗中己方死 1/2 个 → 攻 +1/+2 /
    战后回落基础攻 / 敌方死亡不计 / run_combat 全周期回落 / 金色 +2

    Params: atk_per_death=1（"+1 Attack" 文本字面量——CardDef 无模板
    参数; 金色 atk_per_death=2 "+2 Attack"）
    """

    per_atk = 1   # 金色 "+2 Attack" → 2（金色文本字面量）

    @staticmethod
    def atk(source):
        game = source.game
        hero = source.controller
        if game is None or hero is None or not game.in_combat:
            return None
        deaths = sum(1 for m in game.combat_death_log
                     if m.controller is hero)
        if deaths <= 0:
            return None
        return _static_total_atk(source) + deaths * source.scripts.per_atk


class RotHideGnollGoldenScript(RotHideGnollScript):
    """
    Natural language: Has +2 Attack for each friendly minion that died
    this combat.

    Formal spec: 同基础版，per_atk=2（金色文本字面量，金色 CardDef
    无模板参数）。

    Test: test_batch_counters.py — 金色战斗中己方死 1 个 → 攻 +2

    Params: atk_per_death=2（"+2 Attack" 金色文本字面量）
    """

    per_atk = 2


# ══════════════════ BG_TTN_401 Ancestral Automaton ══════════════════


class AncestralAutomatonScript:
    """
    Natural language: [x]Has +3/+2 for each other\\nAncestral Automaton
    you've\\nsummoned this game\\n<i>(wherever this is)</i>.

    Formal spec:
      1. hero 级召唤簿记（"you've summoned this game" 不可回溯，无
         引擎计数 → 脚本层簿记）: 首只 Automaton 入场（on_summon）时
         以 hero._automaton_summoned_uuids = 当前棋盘家族实体 uuid 集
         种子化（game.summon 先 fire SUMMON 后跑 on_summon——自身
         已在棋盘、恰补漏记的自身事件），并注册 owner=hero 的 SUMMON
         持久监听器（Hero 永不注销 = "this game"; Waveling 亡语
         owner=hero 先例）追加家族 uuid。
         首次注册必在招募期（战斗内召唤的都是已入场者的复制/衍生物，
         其入场前必经招募期 summon 注册监听器、已入快照），不受战斗
         监听器表回滚影响。
      2. "other" = 簿记集减自身 uuid（在场必在集; 手牌实体不在集、
         不减——手牌读本卡时计数全部已召唤者）。售出/吞噬者保留在集
         （"summoned this game" 累计不回落）。
      3. atk/health 动态钩子（覆盖式）: others=0 → None 回落; >0 →
         全量 = 复算 + others × per_atk/per_health。
      4. 数值 3/2 为文本字面量（CardDef 无模板参数，XML 核实
         nums=[None×4]）; 金色 "+6/+4" 子类覆写。

    Test: test_batch_counters.py — 1 只无加成 / 2 只各 +3/+2 / 3 只各
    +6/+4 / 手牌实体计数场上者 / 售出后重新入场仍累计 / 金色 +6/+4

    Params: per_atk=3 per_health=2（"+3/+2" 文本字面量——CardDef 无
    模板参数; 金色 per_atk=6 per_health=4 "+6/+4"）
    """

    per_atk = 3     # 文本字面量 "+3/+2"（金色 "+6/+4" 子类覆写）
    per_health = 2

    @staticmethod
    def on_summon(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        if not hasattr(hero, "_automaton_summoned_uuids"):
            hero._automaton_summoned_uuids = {
                m.uuid for m in hero.board
                if m.card_id in _AUTOMATON_IDS}

            def on_any_summon(g, minion=None, **kw):
                if (minion is not None and minion.controller is hero
                        and minion.card_id in _AUTOMATON_IDS):
                    hero._automaton_summoned_uuids.add(minion.uuid)

            game.events.register(Listener(
                event=SUMMON, owner=hero, callback=on_any_summon))
        return None

    @staticmethod
    def _others(source) -> int:
        hero = source.controller
        if hero is None:
            return 0
        uuids = set(getattr(hero, "_automaton_summoned_uuids", set()))
        uuids.discard(source.uuid)
        return len(uuids)

    @staticmethod
    def atk(source):
        if source.game is None or AncestralAutomatonScript._others(source) <= 0:
            return None
        return (_static_total_atk(source)
                + AncestralAutomatonScript._others(source)
                * source.scripts.per_atk)

    @staticmethod
    def health(source):
        if source.game is None or AncestralAutomatonScript._others(source) <= 0:
            return None
        return (_static_total_health(source)
                + AncestralAutomatonScript._others(source)
                * source.scripts.per_health)


class AncestralAutomatonGoldenScript(AncestralAutomatonScript):
    """
    Natural language: [x]Has +6/+4 for each other\\nAncestral Automaton
    you've\\nsummoned this game\\n<i>(wherever this is)</i>.

    Formal spec: 同基础版，per_atk=6 / per_health=4（金色文本字面量，
    金色 CardDef 无模板参数）。

    Test: test_batch_counters.py — 金色与他者同场各按 6/4 计

    Params: per_atk=6 per_health=4（"+6/+4" 金色文本字面量）
    """

    per_atk = 6
    per_health = 4


# ══════════════════ BGS_071 Deflect-o-Bot ══════════════════


class DeflectOBotScript:
    """
    Natural language: [x]<b>Divine Shield</b>\\nWhenever you summon a Mech\\n
    during combat, gain +{0} Attack\\nand <b>Divine Shield</b>.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件 SUMMON（引擎
         对新入场者先 fire 事件后跑其 on_summon——新入场的
         Deflect-o-Bot 不自触发; 已在场者对后续召唤照常触发，
         Banana Slamma 同序先例）。
      2. 条件: g.in_combat（"during combat"——招募期召唤不触发）且
         minion.controller is source.controller（"you summon"; 敌方
         Mech 不计）且 minion.race ∈ (MECH, ALL)。
      3. 触发: Buff(source, atk=num(0), temporary=True)——战斗内成长
         战后随快照回落（官方战斗期增益语义）+ GainKeyword(DIVINE_
         SHIELD)（幂等: 盾已被打破则重获，"and Divine Shield" 每次
         触发都给）。金色 num(0)=4 经金色 CardDef 自然体现。
      4. 监听器随战斗快照恢复（战死复活后续战生效——引擎保证）。

    Test: test_batch_counters.py — 战斗中召唤 Mech → +num(0) 攻且重获
    DS / 招募期不触发 / 非 Mech 不触发 / 敌方 Mech 不触发 / 金色 +4

    Params: {0}=2（36.2.2 基线，金色 TB_BaconUps_123 {0}=4）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_summoned(g, minion=None, **kw):
            if not g.in_combat or minion is None:
                return
            if minion.controller is not source.controller:
                return
            if minion.race not in _MECH_RACES:
                return
            d = g.db.get(source.card_id)
            g.run_actions([
                Buff(source, atk=d.num(0), temporary=True),
                GainKeyword(source, GameTag.DIVINE_SHIELD),
            ])

        game.events.register(Listener(
            event=SUMMON, owner=source, callback=on_summoned))
        return None


# ══════════════════ BG26_817 Blade Collector ══════════════════


class BladeCollectorScript:
    """
    Natural language: Also damages the enemies next to whomever this attacks.

    Formal spec:
      1. on_summon 置 GameTag.CLEAVE——引擎 CombatScheduler 已消费该
         tag（攻击时对防守方相邻实体同攻伤害、宣告时锁定目标，C5），
         与卡面 "enemies next to whomever this attacks" 语义一致。
      2. 数据缺口（批次 docstring 缺口 3）: XML 无 tag 1017、生成器
         仅匹配 "Cleave" 字样漏检 "Also damages" 文本 → keywords 空
         集，脚本层 tag 自举兜底（Warpwing IMMUNE_WHILE_ATTACKING
         test_core_invariants 手动置 tag 同构）。
      3. 金色同文（无强化子句），同类注册。

    Test: test_batch_counters.py — 入场携带 CLEAVE tag / 攻击中间目标
    时其两侧均受等同攻击伤害 / 普通随从攻击无溅射（负例）

    Params: 无模板参数（顺劈无数值）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.CLEAVE, True)
        return None


# ══════════════════ BG36_514 Barrier Banshee ══════════════════


class BarrierBansheeScript:
    """
    Natural language: After a friendly minion is <b>Reborn</b>, gain
    <b>Divine Shield</b> and +{0}/+{1}.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件 reborn
         （REBORN_EVENT; _process_single_death 复生原位回归后 fire，
         minion=复活体——此时已回到棋盘）。
      2. 条件: minion.controller is source.controller（"a friendly
         minion"; 复活体含任意种族）。
      3. 触发: GainKeyword(DIVINE_SHIELD) + Buff(source, num(0),
         num(1), temporary=True)——复生仅发生于战斗内，增益随战后
         快照回落（战斗期语义）; DS 已有时幂等。
      4. 已知引擎语义（批次 docstring 缺口 5）: 自身复生不触发——
         战斗中死亡即 unregister_owner，监听器战后快照恢复后续战
         生效。

    Test: test_batch_counters.py — 友方复生 → DS + num(0)/num(1) /
    敌方复生不触发 / 普通死亡（无复生）不触发 / 金色 14/14

    Params: {0}=7 {1}=7（36.2.2 基线，金色 {0}=14 {1}=14）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_reborn(g, minion=None, **kw):
            if minion is None or minion.controller is not source.controller:
                return
            d = g.db.get(source.card_id)
            g.run_actions([
                GainKeyword(source, GameTag.DIVINE_SHIELD),
                Buff(source, atk=d.num(0), health=d.num(1),
                     temporary=True),
            ])

        game.events.register(Listener(
            event=REBORN_EVENT, owner=source, callback=on_reborn))
        return None


# ══════════════════ BG36_515 Snazzy Phantom ══════════════════


class SnazzyPhantomScript:
    """
    Natural language: After a friendly minion is <b>Reborn</b>, give stats
    equal to its Attack to your right-most Undead.

    Formal spec:
      1. on_summon 注册 reborn 监听器（owner=source; 条件 friendly 同
         Barrier Banshee）。
      2. 触发: 目标 = 己方棋盘最右 Undead（race ∈ (UNDEAD, ALL)、
         存活、含 Phantom 自身与复活体——按 zone_position 取 max;
         无 Undead → 落空）。增益 = Buff(atk=X, health=X,
         temporary=True)，X = 复活体当前攻击（"stats equal to its
         Attack" = +X/+X; 复活体已回场、攻击实时读数）; 战斗期增益
         随快照回落。
      3. 金色 "double its Attack" → mult=2（文本字面量）。

    Test: test_batch_counters.py — 复活 4 攻随从 → 最右 Undead +4/+4 /
    最右判定（Phantom 在左不取）/ 敌方复生不触发 / 无 Undead 落空 /
    金色 double

    Params: 无模板参数（X 运行时取复活体攻击）; mult=1（金色 mult=2
    "double" 文本字面量）
    """

    mult = 1   # 金色 "double its Attack" → 2（金色文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_reborn(g, minion=None, **kw):
            hero = source.controller
            if minion is None or hero is None:
                return
            if minion.controller is not hero:
                return
            undeads = [m for m in hero.board
                       if not m.dead and m.race in _UNDEAD_RACES]
            if not undeads:
                return
            target = max(undeads, key=lambda m: m.zone_position)
            stats = minion.atk * source.scripts.mult
            g.run_actions(Buff(target, atk=stats, health=stats,
                               temporary=True))

        game.events.register(Listener(
            event=REBORN_EVENT, owner=source, callback=on_reborn))
        return None


class SnazzyPhantomGoldenScript(SnazzyPhantomScript):
    """
    Natural language: [x]After a friendly minion is\\n<b>Reborn</b>, give
    stats equal to\\ndouble its Attack to your\\nright-most Undead.

    Formal spec: 同基础版，mult=2——X = 2 × 复活体攻击。

    Test: test_batch_counters.py — 金色复活 4 攻随从 → +8/+8

    Params: mult=2（"double its Attack" 金色文本字面量）
    """

    mult = 2


# ══════════════════ BG36_763 Treasure Parrot ══════════════════


class TreasureParrotScript:
    """
    Natural language: [x]Once this deals {1} damage,\\nget a Golden Touch.\\n
    <i>({0} left!)</i>@[x]Once this deals {1} damage,\\nget a Golden Touch.\\n
    <i>(Done!)</i>

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件 damage
         (minion=受害者, amount=实际值, source=伤害来源)——"this
         deals" = 来源为本体（攻击主/反击/顺劈/Hit 全路径 fire）;
         amount>0 才计（圣盾抵消不算造成伤害，C7）。
      2. 累计 source._parrot_damage += amount; 达 num(1)（=35）且未
         发放 → 一次性发放（@ 后 "(Done!)" 变体 = 本局仅一次，非
         循环重置）Golden Touch ×times: _get_pool_spell（首份占法术
         池、池空净增——batch_deathrattle2 统一裁定路径）。
      3. num(0)=35 为 "{0} left!" 显示参数（与阈值同值不同义，本卡
         混排勿混用）。金色 "two Golden Touches" → times=2。
      4. 伤害计数随实体（出售后新实体重新累计——官方按卡实例）。

    Test: test_batch_counters.py — 累计 35 → 手牌 +1 Golden Touch 且占
    池 / 34 不触发 / 敌方造伤不计 / 发放后继续造伤不二次发放 /
    金色两份

    Params: {0}=35 {1}=35（36.2.2 基线，金色同值; {0} 显示参数、{1}
    阈值）; times=1（金色 times=2 "two" 文本字面量）
    """

    times = 1   # 金色 "get two Golden Touches" → 2（金色文本字面量）

    @staticmethod
    def on_summon(source, game, ctx):
        parrot = source
        if not hasattr(parrot, "_parrot_damage"):
            parrot._parrot_damage = 0

        def cond(minion=None, amount=None, source=None, **kw):
            return bool(amount) and source is parrot

        def on_damage(g, minion=None, amount=None, source=None, **kw):
            if getattr(parrot, "_touch_done", False):
                return
            d = g.db.get(parrot.card_id)
            parrot._parrot_damage += amount
            if parrot._parrot_damage < d.num(1):
                return
            parrot._touch_done = True
            hero = parrot.controller
            if hero is not None:
                _get_pool_spell(g, hero, _GOLDEN_TOUCH_ID,
                                parrot.scripts.times)

        game.events.register(Listener(
            event=DAMAGE, owner=parrot, condition=cond,
            callback=on_damage))
        return None


class TreasureParrotGoldenScript(TreasureParrotScript):
    """
    Natural language: [x]Once this deals {1} damage,\\nget two Golden
    Touches.\\n<i>({0} left!)</i>@...<i>(Done!)</i>

    Formal spec: 同基础版，times=2——首份占池、第二份池空净增
    （法术池每张 1 副本，金色文本总额权威）。

    Test: test_batch_counters.py — 金色达阈值 → 手牌 2 份 Golden Touch

    Params: {0}=35 {1}=35（36.2.2 基线）; times=2（"two" 文本字面量）
    """

    times = 2


# ══════════════════ BG33_155 Devout Hellcaller ══════════════════


class DevoutHellcallerScript:
    """
    Natural language: After another friendly Demon deals damage, gain
    +{0}/+{1} permanently.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件 damage
         (source=伤害来源)。条件: amount>0 且 source ≠ 本体
         （"another"——Hellcaller 自身是 Demon，排除自触发）且
         source.controller is source.controller（"friendly"）且
         source.race ∈ (DEMON, ALL)。
      2. 触发: Buff(source, num(0), num(1)) 永久附魔（非 temporary）。
      3. "permanently" 的战斗快照通道（批次 docstring 缺口 6）:
         run_combat 战后 restore_state 会回滚战内全部附魔——on_summon
         同时置 GameTag.PERSIST_COMBAT_CHANGES（引擎例外 1 通道），
         战内增益战后重放为永久 Buff（game.py 已支持）; 招募期触发
         （Hit/招募期攻击路径）直接永久生效。金色 num=2/4 经金色
         CardDef 自然体现。

    Test: test_batch_counters.py — 友方 Demon 造伤 → +num(0)/num(1) 且
    PERSIST tag / 本体造伤不计 / 友方非 Demon 不计 / 敌方 Demon 不计 /
    run_combat 全周期后增益保留 / 金色 2/4

    Params: {0}=1 {1}=2（36.2.2 基线，金色 {0}=2 {1}=4）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        hellcaller = source

        def cond(minion=None, amount=None, source=None, **kw):
            return (bool(amount) and source is not None
                    and source is not hellcaller
                    and source.controller is hellcaller.controller
                    and source.race in _DEMON_RACES)

        def on_damage(g, minion=None, amount=None, source=None, **kw):
            d = g.db.get(hellcaller.card_id)
            g.run_actions(Buff(hellcaller, atk=d.num(0),
                               health=d.num(1)))

        game.events.register(Listener(
            event=DAMAGE, owner=hellcaller, condition=cond,
            callback=on_damage))
        # "permanently": 战内增益经引擎 PERSIST 通道战后重放为永久
        source.set(GameTag.PERSIST_COMBAT_CHANGES, True)
        return None


# ══════════════════ BG24_004 Warpwing ══════════════════


class WarpwingScript:
    """
    Natural language: <b>Immune</b> while attacking.

    Formal spec:
      1. on_summon 置 GameTag.IMMUNE_WHILE_ATTACKING——引擎
         CombatScheduler._execute_attack 已消费（attacker_immune 时
         不承受反击伤害; Invulnerability Dark Gift 同 tag 通道，
         game.py _gift_invulnerability 先例）。
      2. 金色同文，同类注册。

    Test: test_batch_counters.py — 入场携带 tag / 攻击带攻目标自身
    零损 / 普通随从攻击承受反击（负例对照）

    Params: 无模板参数（关键词无数值）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.IMMUNE_WHILE_ATTACKING, True)
        return None


# ══════════════════ 以下不注册 REGISTRY ══════════════════


class WildfireElementalScript:
    """
    Natural language: After this attacks and\\nkills a minion, deal\\nexcess
    damage to an adjacent enemy.（金色 TB_BaconUps_166: ... to both
    adjacent enemies.）

    Status: DEFERRED — requires 受击前血量快照 / excess_damage 事件

    Dependency:
      1. "excess damage" = 攻击力 − 目标受击前血量。after_attack 时
         目标已死且 health 被 clamp 到 0，事后不可反推（作业单
         2026-08-22 裁定 DEFERRED）; take_damage 返回的 amount =
         未截断攻击力，亦不含受击前血量信息。
      2. 精确替代方案（供主线裁决，非近似）: before_attack 快照
         defender.health + damage 事件（source=本体、minion=主目标
         过滤顺劈邻位）快照 amount=宣告攻击力，双监听在
         after_attack 合成 excess——依赖两事件拼合自建攻击上下文，
         属引擎 ctx 职责，脚本层拼装越权。
      3. 建议: _execute_attack 的 attack ctx 携带 (atk_power,
         defender_hp_before) 或新增 excess_damage 事件。

    Params: 无模板参数（excess 运行时计算）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        return None


class MagicfinMycologistScript:
    """
    Natural language: [x]Once per turn, after you\\nbuy a Tavern spell, get
    a\\n1/1 Murloc and teach\\nit that spell. <i>({0} left!)</i>（金色
    BG33_891_G: Twice per turn ...）

    Status: DEFERRED — requires spell_bought 事件 + "teach" 实体机制

    Dependency:
      1. 购买法术无事件: buy_from_tavern 仅对 Minion fire
         minion_bought（game.py:373-375），酒馆法术购买路径静默——
         "after you buy a Tavern spell" 不可监听（监听 spend_gold/
         hand 变化均为近似，禁止）。
      2. "get a 1/1 Murloc and teach it that spell": 需 1/1 Murloc
         token 定义 + 实体携带法术（"teach"）的机制与消费出口
         （token 施放该法术? 官方文案无细则），引擎双缺口。
      3. num(0)=1（金色 2）为 "once/twice per turn" 次数。

    Params: {0}=1（36.2.2 基线，金色 {0}=2）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        return None


# ══════════════════ 注册 ══════════════════

# （含金色 id——金色=独立卡定义）
_REGISTRATIONS = [
    ("BG35_921", AbyssalBruiserScript),
    ("BG35_921_G", AbyssalBruiserScript),        # num=4/2 自然体现
    ("BG35_342", FallingSkyGolemScript),
    ("BG35_342_G", FallingSkyGolemScript),       # num=8/4 自然体现
    ("BG36_524", MaritimeExtortionistScript),
    ("BG36_524_G", MaritimeExtortionistScript),  # num=14/14 自然体现
    ("BG25_008", EternalKnightScript),
    ("BG25_008_G", EternalKnightScript),         # num=8/4 自然体现
    ("BG25_013", RotHideGnollScript),
    ("BG25_013_G", RotHideGnollGoldenScript),    # "+2 Attack"
    ("BG_TTN_401", AncestralAutomatonScript),
    ("BG_TTN_401_G", AncestralAutomatonGoldenScript),   # "+6/+4"
    ("BGS_071", DeflectOBotScript),
    ("TB_BaconUps_123", DeflectOBotScript),      # 金色 id（num=4 自然体现）
    ("BG26_817", BladeCollectorScript),
    ("BG26_817_G", BladeCollectorScript),        # 同文
    ("BG36_514", BarrierBansheeScript),
    ("BG36_514_G", BarrierBansheeScript),        # num=14/14 自然体现
    ("BG36_515", SnazzyPhantomScript),
    ("BG36_515_G", SnazzyPhantomGoldenScript),   # "double its Attack"
    ("BG36_763", TreasureParrotScript),
    ("BG36_763_G", TreasureParrotGoldenScript),  # "two Golden Touches"
    ("BG33_155", DevoutHellcallerScript),
    ("BG33_155_G", DevoutHellcallerScript),      # num=2/4 自然体现
    ("BG24_004", WarpwingScript),
    ("BG24_004_G", WarpwingScript),              # 同文
]
# DEFERRED 未注册: BGS_126/TB_BaconUps_166 Wildfire Elemental /
# BG33_891(_G) Magicfin Mycologist（见各类 docstring）


def register() -> list:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list = []
    for card_id, script_cls in _REGISTRATIONS:
        _register(card_id, script_cls)
        registered.append(card_id)
    return registered
